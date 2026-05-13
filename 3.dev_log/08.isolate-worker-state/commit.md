# 08.isolate-worker-state

- commit: `f404d5416`
- date: 2026-04-15 14:49:32 +0000

## Message

```
Isolate applylogdb worker state

```

## Review

- `db_Session_id`, `db_Keep_session`, `db_Row_count`, `ws_Mop_table/Commit_mops/Resident_classes/Stats/Num_dirty_mop`, `sm_Root_class*`, trigger/auth/quick_fit/set_object globals 등 광범위한 client 전역을 `CUB_THREAD_LOCAL`로 일괄 전환 — 격리 범위는 정당하나 lifecycle 관리(init/free) 책임을 호출자에 떠넘김. 워커가 `ws_init`/`au_start`/`tr_init`을 호출하지 않으면 미초기화 TLS에 접근. 07에서 `boot_register_client` 호출하므로 일반 경로는 커버되지만, 사용자 정의 trigger/auth path는 확인 필요.
- `tr_Stack[]`, `tr_Invalid_transaction_trigger[]` 같은 large 배열을 TLS로 옮기면 워커 수 ↑ 시 메모리 사용량 (VSZ) 팽창 — 17에서 max_mem_size 하한 상향으로 대응.
- `Set_Ref_Area`/`Set_Obj_Area`/`Objlist_area`를 TLS로 전환하면서도 `area_alloc.c`의 area_List는 여전히 process-global (16에서 mutex 가드). 따라서 워커가 동시에 `area_create`를 호출하면 area_List 경합 — 16에서 처리.
- `la_apply_stats`/`LA_APPLY_RESULT` 구조 확장 (counter, num_unflushed, committed_rep_lsa)으로 결과 수집 일관성 개선. counter는 결과 수집 후 `la_Info`에 누적되어 reader에서 합산.
- `la_apply_worker_context` 같은 worker-local scratch 분리는 아직 없음 — 12에서 도입. 즉 `la_recdes_pool`/`undo_unzip_ptr`/`redo_unzip_ptr` 등은 여전히 reader 공유.
- detach helper `la_detach_worker_server_credential`이 4번 string copy 중 한 곳에서 실패하면 이전 성공 카피들을 free 후 return — partial credential 상태로 호출자가 다시 호출하면 double-free 위험. 다행히 호출자에서 후속 호출 없어 보임.

## TODO

- worker-local scratch (rec_type/unzip_ptr/recdes_pool) 분리.
