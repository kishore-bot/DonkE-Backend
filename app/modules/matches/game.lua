local prefix, operation = KEYS[1], ARGV[1]
local input = cjson.decode(ARGV[2])
local function key(domain, kind, id) return prefix .. ':' .. domain .. ':' .. kind .. ':' .. id end
local function ok(data) return cjson.encode(data or {}) end
local function fail(code) return ok({error = code}) end
local function get(name)
    local value = redis.call('GET', name)
    if value then return cjson.decode(value) end
end
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local ready = key('lobby', 'rooms', 'ready')
local due = key('game', 'index', 'turns')
local pending = key('game', 'index', 'settlement')
local deferred_finishes = key('game', 'index', 'deferred_finishes')

if operation == 'season_settlement_status' then
    if now < input.ends_ms then return ok({status = 'active'}) end
    local upper = '(' .. tostring(input.ends_ms)
    if redis.call('ZCOUNT', deferred_finishes, input.starts_ms, upper) > 0 then
        return ok({status = 'pending'})
    end
    -- The pending score is the completion time until the first retry.
    for _, game_id in ipairs(redis.call('ZRANGEBYSCORE', pending, input.starts_ms, upper)) do
        if not redis.call('ZSCORE', deferred_finishes, game_id) then
            return ok({status = 'pending'})
        end
    end
    return ok({status = 'clear'})
end

local id = input.game_id
local state_key = key('game', 'state', id)
local log = key('game', 'events', id)
local requests = key('game', 'commands', id)

if operation == 'defer_room' or operation == 'defer_turn' or operation == 'defer_settlement' then
    local index = operation == 'defer_room' and ready or (operation == 'defer_turn' and due or pending)
    local scheduled = redis.call('ZSCORE', index, id)
    if scheduled and tonumber(scheduled) <= now then
        if index == pending then
            redis.call('ZADD', deferred_finishes, 'NX', scheduled, id)
        end
        redis.call('ZADD', index, now + 5000, id)
    end
    return ok()
end

local function append(sequence, events)
    redis.call('XADD', log, tostring(sequence) .. '-0', 'events', events)
end

if operation == 'start' then
    local room_key = key('lobby', 'room', input.room_id)
    local room = get(room_key)
    if not room then
        redis.call('ZREM', ready, input.room_id)
        return fail('room_missing')
    end
    if room.game_id then return ok({game_id = room.game_id}) end
    if room.status ~= 'ready' or room.revision ~= input.room_revision or room.start_at_ms > now then
        return fail('room_changed')
    end
    if redis.call('EXISTS', state_key) == 1 then return fail('game_collision') end
    for _, seat in ipairs(room.seats) do
        if seat.player_id then
            local member = get(key('lobby', 'member', seat.player_id))
            if not member or member.kind ~= 'room' or member.id ~= room.id then
                return fail('room_changed')
            end
        end
    end
    local state = cjson.decode(input.state)
    room.status, room.game_id = 'playing', id
    redis.call('SET', room_key, cjson.encode(room))
    for _, seat in ipairs(room.seats) do
        if seat.player_id then redis.call('PERSIST', key('lobby', 'member', seat.player_id)) end
    end
    redis.call('SET', state_key, input.state)
    append(1, input.events)
    redis.call('ZREM', ready, room.id)
    redis.call('ZADD', due, state.deadline_ms, id)
    return ok({game_id = id})
end

local state = get(state_key)

if operation == 'prepare_settlement' then
    local scheduled = redis.call('ZSCORE', pending, id)
    if not scheduled then return ok() end
    if not state then
        redis.call('ZREM', pending, id)
        redis.call('ZREM', deferred_finishes, id)
        return ok()
    end
    if state.status ~= 'finished' then return fail('game_active') end
    local finished_ms = redis.call('ZSCORE', deferred_finishes, id) or scheduled
    return ok({state = state, finished_ms = tonumber(finished_ms)})
end

if not state then return fail('game_missing') end

if operation == 'settled' then
    if state.status ~= 'finished' then return fail('game_active') end
    if redis.call('ZREM', pending, id) == 0 then return ok() end
    redis.call('ZREM', deferred_finishes, id)
    for _, seat in ipairs(state.seats) do
        if type(seat.player_id) == 'string' then
            local member_key = key('lobby', 'member', seat.player_id)
            local member = get(member_key)
            if member and member.kind == 'room' and member.id == state.room_id then
                redis.call('DEL', member_key)
            end
        end
    end
    local room_key = key('lobby', 'room', state.room_id)
    local room = get(room_key)
    if room and room.game_id == id then
        room.status = 'finished'
        redis.call('SET', room_key, cjson.encode(room), 'EX', input.retention)
    end
    for _, name in ipairs({state_key, log, requests}) do redis.call('EXPIRE', name, input.retention) end
    return ok()
end

if operation == 'renew' or operation == 'disconnect' then
    local connection = key('game', 'connection', id .. ':' .. input.player_id)
    if redis.call('GET', connection) ~= input.owner then return fail('connection_replaced') end
    if operation == 'renew' then redis.call('EXPIRE', connection, 15) else redis.call('DEL', connection) end
    return ok()
end

if input.player_id then
    local connection = key('game', 'connection', id .. ':' .. input.player_id)
    if redis.call('GET', connection) ~= input.owner then return fail('connection_replaced') end
else
    local lease = key('game', 'lease', id)
    if redis.call('GET', lease) ~= input.owner or state.deadline_ms > now then return fail('turn_unclaimed') end
end

if input.command then
    local recorded = redis.call('HGET', requests, input.command)
    if recorded then
        local ack = cjson.decode(recorded)
        if ack.signature ~= input.signature then return fail('request_id_reused') end
        return ok({sequence = ack.sequence, version = ack.version})
    end
end
if state.version ~= input.expected then return fail('stale_version') end
if state.status ~= 'active' then return fail('game_finished') end
if input.player_id and not input.is_leave and state.deadline_ms <= now then return fail('turn_expired') end

local next_state = cjson.decode(input.state)
redis.call('SET', state_key, input.state)
append(next_state.sequence, input.events)
if input.command then
    redis.call('HSET', requests, input.command, ok({
        signature = input.signature, sequence = next_state.sequence, version = next_state.version
    }))
end
if next_state.status == 'finished' then
    redis.call('ZREM', due, id)
    redis.call('ZADD', pending, now, id)
else
    redis.call('ZADD', due, next_state.deadline_ms, id)
end
if not input.player_id then redis.call('DEL', key('game', 'lease', id)) end
return ok({sequence = next_state.sequence, version = next_state.version})
