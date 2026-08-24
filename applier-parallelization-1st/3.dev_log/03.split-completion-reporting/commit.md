# 03.split-completion-reporting

- commit: `9dd3c53c1`
- date: 2026-04-15 04:36:12 +0000

## Message

```
Split applylogdb worker completion reporting from reader dispatch

Restructure the applylogdb PoC worker flow to decouple task dispatch from completion handling.

- replace the single worker result slot with a ring-buffer result queue
- enqueue committed transactions without waiting immediately in the reader path
- collect completed worker results from the main apply loop
- update committed_lsa and _db_ha_apply_info only after worker completion is reported
- keep the single-worker PoC while preparing the reader/worker split for later parallelism

```

## Review

- `la_collect_apply_results`가 worker[0] 한 곳만 폴링 — 단일 워커 가정 하드코딩. 11에서 다중 워커 dispatch order로 일반화.
- 메인 루프 매 반복에서 폴링 수집을 수행하는데, 큐가 비면 즉시 return하므로 busy-wait 우려는 적지만 backpressure 메커니즘이 없어 enqueue 측이 `idle_cond`에 block될 가능성 — 부하 테스트 필요.
- 결과 수집 실패 시 `la_applier_need_shutdown=true`로 처리. 부분 적용된 transaction의 abort/rollback 회수가 명시적이지 않다.
- `la_reader_commit_apply_info`로 reader가 `_db_ha_apply_info` 갱신을 담당하도록 분리. 다만 reader와 worker가 아직 동일 client session을 공유하므로 commit이 worker 측 transaction에 영향을 줄 수 있음 (07에서 격리).

## TODO

- (none)
