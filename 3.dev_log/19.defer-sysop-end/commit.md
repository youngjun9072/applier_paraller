# 19.defer-sysop-end

- commit: `aa86c77e8`
- date: 2026-04-23 14:12:44 +0000

## Message

```
log_applier: defer sysop end handling to commit dispatch

```

## Review

- `LOG_SYSOP_END` 처리를 별도 case로 분리하고 reader가 즉시 dispatch task로 만들지 않게 변경. 대신 LOG_COMMIT만 task 생성 → worker는 `assert(rectype == LOG_COMMIT)`로 가정.
- `la_apply_repl_log` 끝에서 SYSOP_END/COMMIT 분기 처리(has_more_commit_items)를 제거. SYSOP_END는 worker에서 더 이상 보지 않음. 시퀀스에서 SYSOP_END 자체에 의존하던 anchor item 처리/재시작 로직이 누락되지 않는지 확인 필요 — long transaction 경로에서 영향 가능성.
- worker가 `final_flush`를 `task.rectype == LOG_COMMIT`일 때만 수행하도록 한정 — pre_flush를 제거하고 threshold-based flush만 남김. flush가 누락된 채 다음 트랜잭션이 같은 worker에서 처리되면 `__gv_loc_repl` pending 누적 가능. 다만 `rectype`은 항상 LOG_COMMIT이므로 final_flush가 매번 실행.
- pre_flush 제거로 single-item flush 비용 줄지만 large transaction 중간에 메모리 압박 시 OOM 위험은 증가 — threshold가 LA_MAX_UNFLUSHED_REPL_ITEMS로 한정되므로 cap 됨.

## TODO

- long transaction에서 SYSOP_END를 무시한 효과 검증 (anchor item 재구성/last_lsa 갱신이 정상 동작하는지).
