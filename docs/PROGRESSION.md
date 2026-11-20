# Friends, parties and progression

Players can request and accept friendships, then invite accepted friends to a party with up to four seats. The leader can queue the whole party in classic mode. Redis reserves all party players together and treats them as one unit when choosing a table. Cancelling before the table is published releases the whole party. Ranked queues are solo.

A match settlement awards eligible humans earned coins and season progress exactly once. Escaping gives a bonus, and match credits are capped at 100 coins per UTC day. The store sells cosmetics for earned coins. The wallet lock and unique references protect purchases and repeat claims.

Each scheduled season has 30 free tiers and five weekly challenges. Its Season Bank adds a bonus equal to one fifth of credited match coins. The close pays the bank and peak-MMR rewards once, preserves the standings and resets current MMR halfway toward 1200. Admin season writes require the Secure session cookie, CSRF token and a reason. The [HTTP contract](api/openapi.json) lists the routes and payloads.
