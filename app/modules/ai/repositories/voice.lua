local prefix, op = KEYS[1], ARGV[1]
local input = cjson.decode(ARGV[2])
local queue, active = prefix .. ':voice:queue', prefix .. ':voice:active'
local clock = redis.call('TIME')
local now = tonumber(clock[1]) * 1000 + math.floor(tonumber(clock[2]) / 1000)
local function job_key(id) return prefix .. ':voice:job:' .. id end
local function lease_key(id) return prefix .. ':voice:lease:' .. id end
local function read(id)
    local value = redis.call('GET', job_key(id))
    if value then return cjson.decode(value) end
end
local function save(id, value)
    redis.call('SET', job_key(id), cjson.encode(value), 'EX', 86400)
end
local function drop(id)
    redis.call('ZREM', queue, id)
    redis.call('ZREM', active, id)
    redis.call('DEL', lease_key(id))
end

if op == 'enqueue' then
    local job = read(input.id)
    if not job then
        job = {status = 'pending', attempts = 0, text = input.text, voice = input.voice}
        save(input.id, job)
        redis.call('ZADD', queue, now, input.id)
    end
    return cjson.encode({status = job.status})
end

if op == 'claim' then
    redis.call('ZREMRANGEBYSCORE', active, '-inf', now)
    if redis.call('ZCARD', active) >= input.concurrency then return '{}' end
    for _, id in ipairs(redis.call('ZRANGEBYSCORE', queue, '-inf', now, 'LIMIT', 0, 16)) do
        local job = read(id)
        if not job or job.status ~= 'pending' then
            drop(id)
        elseif job.attempts >= 3 then
            job.status = 'failed'
            save(id, job)
            drop(id)
        else
            job.attempts = job.attempts + 1
            save(id, job)
            redis.call('SET', lease_key(id), input.owner, 'PX', 20000)
            redis.call('ZADD', queue, now + 20000, id)
            redis.call('ZADD', active, now + 20000, id)
            return cjson.encode({id = id, text = job.text, voice = job.voice})
        end
    end
    return '{}'
end

local job = read(input.id)
if not job or redis.call('GET', lease_key(input.id)) ~= input.owner then return '{}' end
drop(input.id)
if op == 'complete' then
    job.status = 'ready'
    redis.call('SET', prefix .. ':voice:clip:' .. input.id, input.clip, 'EX', 86400)
elseif job.attempts >= 3 then
    job.status = 'failed'
else
    redis.call('ZADD', queue, now + 2 ^ job.attempts * 1000, input.id)
end
save(input.id, job)
return '{}'
