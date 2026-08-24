# 13.increase-workers-tls-globals

- commit: `013a4e348`
- date: 2026-04-22 01:16:26 +0000

## Message

```
Increase applylogdb worker count and split selected globals to thread-local state

```

## Review

- `method_request_id`를 TLS화 — `MULTI_CONN_TO_A_SERVER` on/off 분기 둘 다 TLS로 동일하게 만든 점은 정상. `extern` 선언 (`connection_cl.cpp`)도 같이 TLS로 맞춰 ABI 정합.
- `LA_APPLY_WORKER_COUNT`를 2 → 4로 상향. dispatch_order capacity가 `WORKER_COUNT * QUEUE_CAPACITY + 1`이라 자동 확장되나 메모리는 LA_DISPATCH_ORDER_ENTRY × 4097 ≒ 수십 KB로 부담 적음.
- `net_client_sub_init`에 TODO 주석만 추가, 실제 worker별 target 분리는 미구현 — 향후 multi-host에서 필요.

## TODO

- worker별 net_Server target 명시 전달.
