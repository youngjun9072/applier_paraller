# 07.isolate-client-transactions

- commit: `c2f6af924`
- date: 2026-04-15 07:37:43 +0000

## Message

```
Isolate applylogdb worker client transactions

Register each applylogdb worker as a separate client transaction after opening its worker-local client connection.

Move client transaction state used in request headers to thread-local storage so Reader and Worker requests do not share tm_Tran_index or related transaction settings.

Keep _db_ha_apply_info updates on the Reader path by disabling statement auto-commit for apply-info SQL and committing explicitly after query completion.

Clean up worker-local client registration, replication workspace, and server credential data during worker shutdown.

```

## Review

- `la_apply_worker_register_client`가 reader의 `db_get_client_type()`/`db_Program_name`/`boot_get_host_name`을 그대로 읽어 사용 — reader 등록이 완료된 후라야 안전한데 동시 시작 시 race 가능. 16에서 startup mutex로 가드.
- `la_apply_worker_unregister_client`가 `tm_Tran_index = NULL_TRAN_INDEX`로 강제 초기화하는데, `tm_Tran_index`가 14에서 TLS화되기 전이라면 reader의 index를 덮어쓸 위험. 다행히 동일 커밋에서 `tm_Tran_index` 외 다수 변수를 CUB_THREAD_LOCAL로 전환해 해소.
- `la_update_query_execute`/`la_update_query_execute_with_values`를 `db_execute` → `db_open_buffer_and_compile_first_statement` + `db_set_statement_auto_commit(false)` + `db_execute_statement_local`로 재작성. auto_commit 끄기는 reader가 명시 commit하기 위한 변경이지만, `session`이 NULL이거나 `stmt_no==0`인 분기에서 `db_close_session_local`이 항상 호출되는지 — 코드상 NULL 가드 있으므로 OK.
- worker server credential 복사가 `db_private_free_and_init`을 무조건 호출 — boot_register_client 실패 경로에서 credential 미할당 상태에서도 `db_private_free_and_init(NULL, NULL)` 호출이지만, `db_private_free_and_init` 매크로는 NULL ptr 안전한지 확인 필요.

## TODO

- (none)
