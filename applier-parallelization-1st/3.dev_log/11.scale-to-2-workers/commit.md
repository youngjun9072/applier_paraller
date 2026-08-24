# 11.scale-to-2-workers

- commit: `33987f5cc`
- date: 2026-04-20 03:43:06 +0000

## Message

```
Scale applylogdb to 2 workers with dispatch-order FIFO

- Raise LA_APPLY_WORKER_COUNT from 1 to 2 and hash each transaction to
  a worker via tranid so a single transaction always lands on the same
  session/workspace.
- Add an LA_DISPATCH_ORDER FIFO owned by the reader so results are
  consumed in commit LSA order across workers, avoiding out-of-order
  committed_lsa advancement.
- Pre-map repl_list pointer on the reader side (task.apply) so workers
  no longer call la_find_apply_list; drop la_lock_dbname and
  la_release_all_page_buffers from the worker path since those are
  reader-owned (lock fd acquired once before the main loop,
  cache_pb drained by the reader).
- Move slot reclamation (apply->tranid = 0) from the worker into
  la_collect_apply_results so the reader's la_add_apply_list cannot
  reassign a slot while the worker is still using it.
- la_apply_commit_list wraps la_find_apply_list for source compatibility
  only (call path is legacy/dead under the new dispatch).

Also add temporary er_log_debug traces in reader dispatch, worker main
loop, and la_update_query_execute to diagnose CREATE TABLE not reaching
the slave under N=2. These logs should be removed once the issue is
resolved.

```

## Review

- `la_Dispatch_order`는 락 없이 reader 전용으로 가정하지만, `la_collect_apply_results`가 메인 루프와 같은 reader thread에서만 호출됨을 가정하고 있어 안전. 다만 후속 커밋(18)에서 retire 분리되며 가정이 부서지지 않는지 재확인 필요 — 18 diff에서 여전히 reader-only로 유지됨.
- `la_apply_repl_log` 시그니처를 `(LA_APPLY *apply, ...)`로 바꿔 `la_find_apply_list` 호출을 제거 — repl_lists 배열 reuse 레이스 회피. 단 reader가 `la_collect_apply_results`에서 `apply->tranid = 0`을 수행할 때까지 워커가 결과를 enqueue한 직후라도 reader가 같은 slot에 새 트랜잭션을 할당하지 못하는지 — 슬롯 반환을 retire 시점에 두므로 OK.
- `task.apply = la_find_apply_list(lrec->trid)` 결과를 task에 실어 보내는데, reader가 후속 동일 tranid를 보면 같은 apply pointer를 재사용하게 된다. PoC scope (insert-only, 동일 tx 동일 worker hash)에서는 안전하지만 향후 SBR/abort 흐름과 함께 보면 위험.
- `la_apply_commit_list`는 legacy 잔존 호환용 — diff 주석으로 명시. 죽은 코드인지 다음 단계에서 정리 필요.
- 임시 er_log_debug 다수 추가 (`reader dispatch`, `worker dequeued`, `update_query_execute`). 출시 빌드에서 빠지는지 — 12에서 `LA_DEBUG_LOG` 매크로화, 20번 묶음에서 NDEBUG gate 적용으로 정리됨.
- `la_lock_dbname`을 메인 루프 진입 직전에 한 번 선행 획득 — 워커에서 호출 제거. 그러나 `la_apply_log_file` 내 다른 진입 경로(롤백 등)에서도 안전한지 확인 필요.

## TODO

- legacy `la_apply_commit_list` 죽은 코드 제거.
