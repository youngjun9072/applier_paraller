# 09.fix-perf-and-parser

- commit: `2c0be3126`
- date: 2026-04-16 08:44:15 +0000

## Message

```
Fix applylogdb worker performance and parser thread-safety

- Remove unnecessary sm_flush_objects() in la_repl_add_object:
  repl path uses WS_REPL_OBJ list flushed via locator_repl_flush_all,
  not the MOP dirty list. Eliminates per-item server round-trips.

- Replace ws_filter_dirty + ws_cull_mops with ws_intern_instances
  in la_commit_transaction: properly decaches MOPs left behind by
  locator_repl_flush_all (DONT_DECACHE), preventing workspace bloat
  after bulk inserts.

- Add la_sql_compile_mutex to serialize SQL parser access between
  reader and worker threads. Parser static globals are not thread-safe
  and concurrent access causes assertion failures in parser_pop_hint_node.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>

```

## Review

- `sm_flush_objects` 제거는 repl path가 `WS_REPL_OBJ` 리스트를 사용한다는 사실에 의존 — 정확하지만 추후 다른 item type (update/delete with FK 등) 추가 시 회기 누락 가능. PoC scope에 한정.
- `la_sql_compile_mutex`로 SQL parser global을 직렬화. parser globals이 thread-safe해질 때까지의 합리적 우회. 다만 `la_update_query_execute_with_values`도 동일 mutex로 묶이고, reader와 worker가 모두 같은 mutex로 경합 — `_db_ha_apply_info` 갱신과 worker statement 적용이 충돌할 수 있다. PoC PKG insert만 다루면 영향 적음.
- `ws_filter_dirty + ws_cull_mops` → `ws_intern_instances` 루프로 변경 — `ws_Resident_classes`가 08에서 TLS화된 상태와 정합. 다만 `ws_Resident_classes`를 잠금 없이 순회하므로 worker 내에서만 안전. reader가 동일 list에 접근하면 안 됨.
- mutex가 PTHREAD_MUTEX_INITIALIZER로 정적 초기화돼 fork-safety는 별 문제 없음.

## TODO

- (none)
