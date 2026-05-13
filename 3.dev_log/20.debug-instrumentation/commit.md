# 20.debug-instrumentation

병렬 applylogdb 동작 분석을 위해 점진적으로 추가된 디버그/계측 커밋 묶음.

## Commits

- `18a07c037` (2026-04-20 05:56:58 +0000) — add insert path logging
- `19e13c9a8` (2026-04-22 05:59:55 +0000) — Add applylogdb cache buffer diagnostics
- `92ca4bee5` (2026-04-22 06:21:39 +0000) — print debugging log prints only debug mode
- `e951865e4` (2026-04-24 08:11:16 +0000) — Add debug instrumentation for parallel applylogdb
- `8e4b0f5da` (2026-04-27 06:46:00 +0000) — log_applier: add quantitative timing breakdown for parallel apply
- `a3efdf318` (2026-04-27 16:15:57 +0000) — log_applier: add queue depth and reader bottleneck instrumentation
- `d02169053` (2026-04-29 01:44:31 +0000) — log_applier: add mid-flush and statement context diagnostics
- `02480bf49` (2026-04-30 04:32:49 +0000) — log_applier: add reader and worker throughput diagnostics

## Messages

### 18a07c037

```
add insert path logging

```

### 19e13c9a8

```
Add applylogdb cache buffer diagnostics

```

### 92ca4bee5

```
print debugging log prints only debug mode

```

### e951865e4

```
Add debug instrumentation for parallel applylogdb

```

### 8e4b0f5da

```
log_applier: add quantitative timing breakdown for parallel apply

Extend debug-only progress instrumentation so that reader and worker
time spent in each phase can be quantified from the existing
reader_progress / worker_progress lines. All counters are guarded by
!defined (NDEBUG) and have no effect on release builds.

Reader-side counters added:
  - reader_io_usec, make_usec, dispatch_usec, other_usec
  - reader_record_proc_usec (la_log_record_process total)
  - per-type: repl_data / commit / abort_sysop / other_lrec (usec + count)
  - commit_addnode_usec, commit_dispatch_order_usec
  - reader_collect_results_usec, reader_retire_usec, collect_calls
  - reader_enqueue_wait_usec (cond_wait inside la_enqueue_apply_task)

Worker-side counters added:
  - worker_busy_usec (dequeue ~ result-enqueue span)
  - worker_apply_usec (la_apply_repl_log)
  - worker_disk_fetch_usec (la_get_page + la_get_recdes in apply path)
  - worker_queue_wait_usec (cond_wait inside la_dequeue_apply_task)

Helper macros LA_TIME_BEGIN / LA_TIME_ACCUM_USEC introduced to keep
call sites concise.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

```

### a3efdf318

```
log_applier: add queue depth and reader bottleneck instrumentation

```

### d02169053

```
log_applier: add mid-flush and statement context diagnostics

```

### 02480bf49

```
log_applier: add reader and worker throughput diagnostics

```

## Review

- 8개 커밋이 debug-only 계측 누적. `LA_DEBUG_LOG` 매크로 + `!defined(NDEBUG)` gate로 release 빌드에는 영향 없도록 분리. 다만 debug 빌드에서는 `er_log_debug` 폭증으로 I/O가 성능 측정을 왜곡할 수 있음 — timing 결과 해석 시 주의.
- cache_pb 계측 (mutex/hit/miss/contention)을 위해 `total_access_count` 등 8B 카운터들을 atomic이 아닌 일반 update로 처리. mutex로 보호되는 자리면 OK이나 reader/worker 동시 진입에서 counter race 가능 — 디버그 정확도 한정의 비치명적 이슈.
- `la_dump_runtime_state_to_buffer`가 `la_Info.repl_lists`/`commit_head`/`Dispatch_order`를 락 없이 순회. signal handler에서도 호출되므로 일관성 없는 스냅샷이 출력될 수 있으나 디버그 덤프 용도라 수용 가능.
- 큰 카운터/배열을 `la_Info` 또는 `LA_CACHE_PB`에 추가하면서 구조체 크기 팽창. NDEBUG 빌드에서는 매크로로 빠지는지 차폐 정도 확인 필요.
- queue depth/throughput 등 계측이 reader/worker 양쪽에 추가되며 동일 자료구조 (e.g., `worker_progress`) 갱신 — atomic 보장 없이 worker 자신만 갱신하므로 single-writer pattern 유지. reader도 자기 카운터만 갱신.
- 마지막 묶음 (02480bf49 등)이 production-grade observability에 가깝게 확장 — PoC scope를 약간 넘어가지만 성능 분석에는 유용.

## TODO

- debug 빌드에서도 hot path er_log_debug 호출 비용 (string format + lock)이 성능을 가리지 않는지 sampling 기반으로 줄이는 옵션 검토.
- cache_pb 계측 counter는 mutex 안에서만 갱신되도록 정합 확인.

