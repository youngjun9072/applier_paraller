# 06.fix-session-isolation

- commit: `d21022d0d`
- date: 2026-04-15 06:32:08 +0000

## Message

```
Fix applylogdb worker session isolation issues

Register a thread-local error context in applylogdb worker threads to prevent cuberr::context::get_thread_local_context() assertion during worker-side db_commit_transaction().

Initialize worker-local client sessions with net_client_sub_init() and worker-local replication workspace through __gv_loc_repl to avoid concurrent workers sharing the same client connection and flush state.

Enable MULTI_CONN_TO_A_SERVER consistently for cubridcs/cubridsa consumers to fix TLS/non-TLS link mismatches for __gv_client_support and __gv_loc_repl.

Make deferred query-end state and latest query status thread-local to prevent Reader and Worker commits from sharing client-side query transaction state.

Split Reader apply-info commit from worker apply commit so Reader no longer calls la_flush_repl_items() or la_commit_transaction() from the legacy la_log_commit() path.

```

## Review

- `net_Deferred_end_queries[]`와 `tm_Tran_latest_query_status`를 TLS화 — reader/worker가 다른 client transaction 컨텍스트를 가질 때 의미가 있다. 단 이 커밋 시점에는 worker가 `boot_register_client`를 하지 않아 사실상 reader index를 빌려쓰는 상태라 효과는 부분적. 07에서 client transaction 분리 후 완전한 효과 발생.
- `la_log_commit`을 `la_reader_commit_apply_info` 단순 호출로 축약하면서 기존 flush/commit/error 분기 처리가 사라졌다. 새 함수가 동일 분기를 커버하는지 (특히 ER_NET_CANT_CONNECT 외 경로) 호출자에서 재검증 필요.
- `res > 0` / `res == 0` / `res < 0` 분기가 `la_update_ha_last_applied_info`의 반환 규약 (행 개수 > 0)을 가정 — 회기에서 0이 정상으로 흐를 수 있어 `fail_counter` 누적 부작용 가능. PoC에선 영향 미미.

## TODO

- (none)
