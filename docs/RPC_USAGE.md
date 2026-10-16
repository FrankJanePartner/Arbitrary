# RPC request budget

The worker's RPC quota is a local safety cap stored in the application's SQLite database. It is counted separately by chain and UTC day. Reaching the cap blocks further requests for that chain until the UTC date changes; `doctor` also uses the same quota.

Observe mode is intentionally paced to reduce RPC use:

- It waits at least four minutes between scans, even if `poll_seconds` is lower.
- It evaluates at most two routes and two loan sizes per scan.
- It reuses discovered pools for up to 15 minutes, and refreshes sooner if the chain registry changes or the block number moves backwards.
- It reads flash-loan terms once per loan asset per scan.

This trades freshness and coverage for a better chance of staying within a small provider quota. It does not change simulate or live polling. Those modes can use substantially more RPC calls, and the local daily cap still stops the worker when reached. Provider billing and request-unit limits are separate from this local call counter.
