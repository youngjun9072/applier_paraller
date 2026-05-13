# 05.worker-local-client-sessions

- commit: `19e34f4cc`
- date: 2026-04-15 06:07:12 +0000

## Message

```
Enable worker-local client sessions for applylogdb PoC

Initialize a worker-local client connection with net_client_sub_init() in applylogdb worker threads.

Initialize and clear worker-local replication workspace through __gv_loc_repl for each worker.

Keep worker error context registration before worker session setup so client/session errors can use thread-local error context.

Enable MULTI_CONN_TO_A_SERVER consistently for client-side targets that link cubridcs or cubridsa.

Fix TLS/non-TLS ABI mismatches for __gv_client_support by applying the same compile definitions to util, broker, and CM targets.

```

## Review

- `MULTI_CONN_TO_A_SERVER`를 `COMMON_DEFS`로 옮겨 모든 빌드 타깃에 일괄 적용 — 04에서 cs/sa에만 정의해 생겼던 ABI 불일치를 해소. cs/sa의 개별 PRIVATE define은 다시 제거 (define이 COMMON_DEFS에 포함되므로 의도된 정리).
- `la_apply_worker_start_session`이 `net_client_sub_init` 실패 시 곧장 `la_applier_need_shutdown=true`로 처리하지만 thread-local error context는 그대로 deregister/delete 경로를 타므로 정상 종료. 다만 reader가 이 신호를 알아채는 데 한 사이클 지연이 있을 수 있음.
- 이 시점에 net_client_sub_init은 process-global `net_Server_name/net_Server_host`를 그대로 재사용 — diff 내 TODO 주석 명시. multi-host/multi-db 상황에서 위험.
- worker 시작 시 client transaction (`boot_register_client`)은 아직 수행하지 않아 reader의 `tm_Tran_index`를 그대로 사용 — 07에서 분리.

## TODO

- net_client_sub_init이 reader의 net_Server target을 공유 — worker별 host/db 명시 전달 경로 마련 (코드 내 TODO 주석 유지).
