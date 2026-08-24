# 12.worker-local-scratch

- commit: `a49e01c2a`
- date: 2026-04-20 07:41:23 +0000

## Message

```
Add applylogdb worker-local scratch state and debug logs

  - applylogdb worker에 LA_APPLY_WORKER_CONTEXT를 도입해 rec_type, unzip buffer, recdes_pool을 worker-local로 분리
  - row decode/apply 경로가 shared scratch 대신 worker context를 사용하도록 la_get_recdes, la_apply_insert_log, la_apply_update_log, la_apply_delete_log, la_apply_repl_log 시
    그니처와 호출부 정리
  - worker main에서 context init/final lifecycle 추가
  - reader/global recdes pool 및 unzip scratch 초기화/정리 제거
  - insert apply 디버그 로그 보강:
      - BEGIN, pre_flush, recdes, add_object, END
      - worker[idx], tid, tran, class/key, LSA, pending count 포함
  - enqueue 디버그 로그 추가:
      - enqueue_wait, enqueued, enqueue_fail
      - worker index, trid, rectype, queue count 포함
  - worker commit 디버그 로그 추가:
      - commit_transaction BEGIN/END
      - worker index, tran, trid, applied count 포함

```

## Review

- `LA_APPLY_WORKER_CONTEXT`로 `rec_type`, `undo_unzip_ptr`, `redo_unzip_ptr`, `recdes_pool`을 worker-local로 분리 — 설계 문서의 worker-local scratch 요구를 만족.
- `la_apply_repl_log` 등 인자 체인에 context 포인터를 추가하면서 호출부 광범위 수정. 누락된 호출이 한 곳이라도 있으면 NULL deref. `la_apply_commit_list`(legacy) 경로도 함께 호환 처리되었는지 확인 — 11 시점에서 legacy로 유지 중.
- `la_apply_pre()`에서 reader용으로 `la_Info.rec_type` 등 초기화 코드를 제거했지만, 만약 reader path 어디서든 이 필드를 참조하면 NULL deref. 현재 reader는 worker로 모두 위임된 상태라 안전.
- 디버그 로그 부피가 매우 큼 — 모든 insert/enqueue/commit 단계마다 `er_log_debug` 호출. release 빌드 게이트는 20.debug-instrumentation 묶음에서 `LA_DEBUG_LOG` 매크로화로 일괄 처리.

## TODO

- (none)
