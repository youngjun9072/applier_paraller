# 02.error-context-registration

- commit: `e0e474aac`
- date: 2026-04-15 04:09:46 +0000

## Message

```
Register error context in applylogdb worker thread

Initialize worker-local error handling for the applylogdb PoC worker.

- include error_context.hpp in log_applier
- create cuberr::context in worker thread entry
- register thread-local error context before DB API calls
- deregister and destroy context on worker exit
- fix assertion failure in db_commit_transaction path

```

## Review

- `er_context_p = new ...`가 실패하면 그대로 throw — 워커 진입 직후의 정상 종료 경로가 없으나 PoC 범위에서 수용 가능.
- `register_thread_local`만 하고 client session 분리는 아직 없음 (05/06에서 진행). 즉 이 단계에서는 reader와 worker가 여전히 동일 client state를 공유.

## TODO

- (none)
