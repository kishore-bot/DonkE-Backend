local pending = KEYS[1]
local limit, lease_ms = tonumber(ARGV[1]), tonumber(ARGV[2])
local clock = redis.call('TIME')
local now = tonumber(clock[1]) + tonumber(clock[2]) / 1000000
local claimed = {}

-- The retry score hides leased items from subsequent scans. Look farther on
-- rollout to move existing leases from the old scheduler out of the due range.
for _, game in ipairs(redis.call('ZRANGEBYSCORE', pending, '-inf', now, 'LIMIT', 0, limit + 128)) do
    local lease = pending .. ':lease:' .. game
    if redis.call('SET', lease, '1', 'NX', 'PX', lease_ms) then
        redis.call('ZADD', pending, now + lease_ms / 1000, game)
        claimed[#claimed + 1] = game
        if #claimed == limit then break end
    else
        local remaining_ms = redis.call('PTTL', lease)
        redis.call('ZADD', pending, now + math.max(1, remaining_ms) / 1000, game)
    end
end
return claimed
