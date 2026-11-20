-- Standalone Redis. One script owns every transition of a player's membership.
local prefix = KEYS[1]
local op = ARGV[1]
local input = cjson.decode(ARGV[2])

local function key(kind, id)
    return prefix .. ':' .. kind .. ':' .. id
end

local function read(kind, id)
    local raw = redis.call('GET', key(kind, id))
    if raw then return cjson.decode(raw) end
end

local function write(kind, id, value, ttl)
    local name = key(kind, id)
    local encoded = cjson.encode(value)
    if ttl then
        redis.call('SET', name, encoded, 'EX', ttl)
    else
        redis.call('SET', name, encoded)
    end
end

local function remove(kind, id)
    redis.call('DEL', key(kind, id))
end

local function failure(code)
    return cjson.encode({error = code})
end

local function now_ms()
    local clock = redis.call('TIME')
    return tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
end

local function membership(id)
    local member = read('member', id)
    if member and member.kind == 'room' and not read('room', member.id) then
        remove('member', id)
        return nil
    end
    return member
end

local function matching_id(member, kind, id)
    return member and member.kind == kind and member.id == id
end

local function status(member)
    if not member then return {status = 'idle'} end
    if member.kind == 'room' then
        return {
            status = member.mode and 'matched' or 'room',
            room_id = member.id, mode = member.mode,
        }
    end
    return {
        status = member.kind == 'queued' and 'queued' or 'matching',
        mode = member.mode, enqueued_at_ms = member.enqueued_ms,
    }
end

local function save_room(room)
    local ready = #room.seats >= 2
    for _, seat in ipairs(room.seats) do
        if not seat.ready then ready = false end
    end
    room.status = ready and 'ready' or 'waiting'
    write('room', room.id, room, input.room_ttl)
    for _, seat in ipairs(room.seats) do
        if not seat.bot then
            write('member', seat.player_id, {kind = 'room', id = room.id, mode = room.mode}, input.room_ttl)
        end
    end
end

local function room_seat(room, player)
    for index, seat in ipairs(room.seats) do
        if seat.player_id == player then return index end
    end
end

local function new_seat(player, name, ready, bot)
    return {player_id = player, display_name = name, ready = ready, bot = bot}
end

local function enqueue(player, name, mode, queue, since)
    write('member', player, {
        kind = 'queued', id = queue, mode = mode, enqueued_ms = since, name = name,
    }, input.queue_ttl)
    redis.call('ZADD', key('queue', queue), since, player)
end

local claims = key('claims', 'deadlines')

local function drop_claim(id)
    remove('claim', id)
    redis.call('ZREM', claims, id)
end

local function rollback(id, claim)
    for _, entry in ipairs(claim.entries) do
        local member = membership(entry.player_id)
        if not (claim.cancelled and claim.cancelled[entry.player_id])
            and matching_id(member, 'claim', id) then
            enqueue(entry.player_id, entry.name, claim.mode, claim.queue, entry.since)
        end
    end
    drop_claim(id)
end

if op == 'recover' then
    local due = redis.call('ZRANGEBYSCORE', claims, '-inf', now_ms(), 'LIMIT', 0, 32)
    for _, id in ipairs(due) do
        local claim = read('claim', id)
        if claim then rollback(id, claim) else drop_claim(id) end
    end
    return cjson.encode({count = #due})
end

if op == 'claim' then
    local queue = key('queue', input.queue)
    local entries = {}
    for _, player in ipairs(redis.call('ZRANGE', queue, 0, 31)) do
        local member = membership(player)
        if matching_id(member, 'queued', input.queue) then
            table.insert(entries, {player_id = player, name = member.name, since = member.enqueued_ms})
            if #entries == input.seats then break end
        else
            redis.call('ZREM', queue, player)
        end
    end
    local now = now_ms()
    if #entries == 0 or (#entries < input.seats and now - entries[1].since < input.bot_wait_ms) then
        return cjson.encode({})
    end
    if read('claim', input.claim_id) then return failure('id_collision') end
    local claim = {
        owner = input.owner, entries = entries, mode = input.mode, queue = input.queue,
        until_ms = now + input.lease_ms, seats = input.seats,
    }
    write('claim', input.claim_id, claim)
    redis.call('ZADD', claims, claim.until_ms, input.claim_id)
    for _, entry in ipairs(entries) do
        redis.call('ZREM', queue, entry.player_id)
        write('member', entry.player_id, {
            kind = 'claim', id = input.claim_id, mode = claim.mode, enqueued_ms = entry.since,
        }, input.queue_ttl)
    end
    return cjson.encode({claim_id = input.claim_id})
end

if op == 'finalize' or op == 'rollback' then
    local claim = read('claim', input.claim_id)
    if not claim or claim.owner ~= input.owner or claim.until_ms <= now_ms() then
        return failure('claim_lost')
    end
    if op == 'rollback' then
        rollback(input.claim_id, claim)
        return cjson.encode({})
    end
    if claim.cancelled then
        rollback(input.claim_id, claim)
        return failure('claim_cancelled')
    end
    local seats = {}
    for _, entry in ipairs(claim.entries) do
        if not matching_id(membership(entry.player_id), 'claim', input.claim_id) then
            rollback(input.claim_id, claim)
            return failure('claim_cancelled')
        end
        table.insert(seats, new_seat(entry.player_id, entry.name, true, false))
    end
    if read('room', input.room_id) then return failure('id_collision') end
    for index = #seats + 1, claim.seats do
        table.insert(seats, new_seat(nil, 'Bot ' .. tostring(index), true, true))
    end
    local room = {
        id = input.room_id, capacity = claim.seats, seats = seats,
        host_id = seats[1].player_id, mode = claim.mode,
    }
    save_room(room)
    drop_claim(input.claim_id)
    return cjson.encode(room)
end

local member = membership(input.player)

if op == 'status' then
    return cjson.encode(status(member))
end

if op == 'enqueue' then
    if member then
        if member.mode == input.mode then return cjson.encode(status(member)) end
        return failure('player_busy')
    end
    enqueue(input.player, input.name, input.mode, input.queue, now_ms())
    return cjson.encode(status(membership(input.player)))
end

if op == 'cancel' then
    if member and member.kind == 'queued' then
        redis.call('ZREM', key('queue', member.id), input.player)
        remove('member', input.player)
    elseif member and member.kind == 'claim' then
        local claim = read('claim', member.id)
        if claim then
            claim.cancelled = claim.cancelled or {}
            claim.cancelled[input.player] = true
            write('claim', member.id, claim)
        end
        remove('member', input.player)
    elseif member and member.kind == 'room' then
        return failure('player_busy')
    end
    return cjson.encode({status = 'idle'})
end

if op == 'create_room' then
    if member then return failure('player_busy') end
    if read('room', input.room_id) then return failure('id_collision') end
    local room = {
        id = input.room_id, host_id = input.player, capacity = input.capacity,
        seats = {new_seat(input.player, input.name, false, false)},
    }
    save_room(room)
    return cjson.encode(room)
end

if op == 'leave_room' and not matching_id(member, 'room', input.room_id) then
    return cjson.encode({})
end

local room = read('room', input.room_id)
if not room then return failure('room_not_found') end
local seat = room_seat(room, input.player)
local owns_seat = seat and matching_id(member, 'room', room.id)

if op == 'join_room' then
    if owns_seat then return cjson.encode(room) end
    if room.mode then return failure('room_not_found') end
    if member then return failure('player_busy') end
    if #room.seats >= room.capacity then return failure('room_full') end
    table.insert(room.seats, new_seat(input.player, input.name, false, false))
    save_room(room)
    return cjson.encode(room)
end

if not owns_seat then return failure('room_not_found') end
if op == 'get_room' then return cjson.encode(room) end

if op == 'ready' then
    if room.mode then return failure('matchmade_room') end
    room.seats[seat].ready = input.ready
    save_room(room)
    return cjson.encode(room)
end

if op == 'kick' then
    if room.mode then return failure('matchmade_room') end
    if room.host_id ~= input.player then return failure('host_required') end
    if input.target == input.player then return failure('cannot_kick_self') end
    local target = room_seat(room, input.target)
    if not target then return failure('seat_not_found') end
    table.remove(room.seats, target)
    if matching_id(membership(input.target), 'room', room.id) then
        remove('member', input.target)
    end
    save_room(room)
    return cjson.encode(room)
end

if op == 'leave_room' then
    if room.mode then
        for _, occupied in ipairs(room.seats) do
            if occupied.player_id and matching_id(membership(occupied.player_id), 'room', room.id) then
                remove('member', occupied.player_id)
            end
        end
        remove('room', room.id)
    else
        table.remove(room.seats, seat)
        remove('member', input.player)
        if #room.seats == 0 then
            remove('room', room.id)
        else
            if room.host_id == input.player then room.host_id = room.seats[1].player_id end
            save_room(room)
        end
    end
    return cjson.encode({})
end

return failure('unknown_operation')
