# 14.refine-thread-local-tran

- commit: `2b6d9ffb5`
- date: 2026-04-22 02:23:23 +0000

## Message

```
Refine thread-local transaction client state

```

## Review

- `tm_Query_begin`, `tm_Query_timeout`, `tm_libcas_depth`, `user_savepoint_list` 4개 static을 추가 TLS화 — 07에서 빠진 잔여 transaction state 보강. 작지만 query timeout/method callback이 worker에서 호출될 때 reader 값을 오염시킬 가능성을 차단.
- `user_savepoint_list`는 사용자 savepoint 리스트인데 PoC scope에서 호출 경로가 없을 가능성이 큼. 그래도 격리는 안전 측.

## TODO

- (none)
