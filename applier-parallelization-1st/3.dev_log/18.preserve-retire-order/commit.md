# 18.preserve-retire-order

- commit: `988f15ea9`
- date: 2026-04-23 04:47:37 +0000

## Message

```
Preserve applylogdb retire order across worker results

Add invalid timezone debug logging and update cubrid-cci build number.

```

## Review

- 핵심은 `la_collect_worker_results`/`la_retire_ready_results` 2단 분리. worker 결과는 도착 순서대로 일단 entry에 채워두고, retire는 dispatch_order head부터 순서대로만 진행 — out-of-order 완료를 허용하면서 committed_lsa는 in-order 갱신.
- `la_dispatch_order_find_by_seq`가 O(N) 선형 탐색. 큐 깊이가 깊어지면 reader 부하 증가. PoC에서 dispatch 큐 깊이가 worker_count × queue_capacity = 10240까지 가능 — 부하 측정 필요.
- 커밋 메시지 (`Add invalid timezone debug logging and update cubrid-cci build number`)가 실제 diff 핵심과 무관 — 메시지 오류로 보임. 본질 변경은 retire 분리.
- `seq`를 UINT64로 부여하므로 overflow는 실질적으로 무시 가능. dispatch_order entry에 `result` 전체를 복사 저장 — `stats.last_class_name` 같은 큰 필드 포함 시 메모리 비용 약간 증가.
- entry->apply slot reclaim 위치를 retire 단계로 이동 — 동시에 collect 단계에서는 슬롯 건드리지 않음. 정합 OK.

## TODO

- `la_dispatch_order_find_by_seq` O(N) 탐색 → seq→index 매핑 또는 ring buffer 직접 인덱싱으로 개선.
- 커밋 메시지가 변경 본질을 반영하도록 정정.
