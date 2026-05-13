# 10.suppress-state-notify

- commit: `0cd95f555`
- date: 2026-04-19 13:23:04 +0000

## Message

```
Suppress HA applier state notification from worker sessions

Worker sessions connect with DB_CLIENT_TYPE_LOG_APPLIER alongside the
reader, which made master's ha_log_applier_state_table track each
worker as a separate applier and skewed state aggregation.

Identify worker sessions by the " [worker]" suffix on the client's
program name and short-circuit css_notify_ha_log_applier_state for
them, so only the reader reports applier state to the master.

```

## Review

- worker session 식별 방식이 program_name suffix `" [worker]"` 문자열 매칭 — 하드코딩이지만 PoC로는 충분. 다만 worker 등록 측에서 실제로 이 suffix를 program_name에 붙이는 코드가 어디인지 diff에 안 보임. 07의 `client_credential.program_name = db_Program_name` 그대로면 동작 X. 13/16 등 후속 커밋에서 suffix 부여가 있어야 의미를 가짐.
- 서버 측 csect_enter 후 즉시 early return — 락 해제는 추가했으나 다른 부수 효과 (state aggregation, host registration 등)도 같이 건너뛰는 것이 의도인지 명시 필요.

## TODO

- worker program_name suffix `" [worker]"`를 실제 client 등록 시점에 부여하는 코드 확인/보강.
