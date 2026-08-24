# 01.transaction-worker-queue

- commit: `2047f7208`
- date: 2026-04-15 04:00:07 +0000

## Message

```
Add transaction-level worker queue skeleton for applylogdb parallel PoC

Introduce a minimal applylogdb parallelization PoC skeleton.

- add single apply worker and ring-buffer task queue
- dispatch committed transactions from reader to worker
- let worker process apply/flush/commit per transaction
- report worker result back to reader for committed_lsa update
- limit PoC scope to CREATE TABLE, DROP TABLE and INSERT

```

## Review

- 단일 워커지만 `la_enqueue_apply_task` 직후 `la_wait_apply_result`로 곧바로 블로킹하므로 사실상 동기 처리. PoC 골격으로는 OK이나 큐 용량 1024가 무용지물 — 03에서 해소.
- 워커가 `la_apply_repl_log`/`la_flush_repl_items`/`la_commit_transaction`을 호출하지만 이 시점에는 reader와 동일 client session/`tm_Tran_index`/workspace를 공유. 동시 호출이 아니라 문제는 안 되지만 isolation 가정이 전혀 없다는 점이 위험.
- `la_apply_worker_main`에서 thread-local error context 등록이 없어 `db_commit_transaction` 호출 시 assertion 우려 — 02에서 해결.
- `LOG_ABORT` 경로를 `la_add_node_into_la_commit_list`에서 `la_free_repl_items_by_tranid` 단순 free로 바꿨는데, dispatch 흐름과 abort 경로 모두에서 ordering 보장은 아직 없음.
- `la_is_supported_poc_item`로 INSERT/CREATE/DROP만 통과시키는 하드코딩 필터 — PoC 의도대로 명시.

## TODO

- (none)
