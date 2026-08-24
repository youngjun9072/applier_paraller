# 16.guard-client-globals

- commit: `aa3fe0020`
- date: 2026-04-22 14:18:55 +0000

## Message

```
Guard client globals shared by parallel applylogdb worker startup

The earlier locator cache fix removed one double-free vector but a later
test run showed slave applylogdb still aborted with tcache corruption
detected at thread exit. The bt placed the corruption before shutdown:
N=10 workers started back-to-back each ran ws_init() which in turn calls
area_create() for several module-level AREAs. area_create inserts into
the global area_List under area_List_lock, but in CS/SA mode a top-of-file
macro block turned every pthread_mutex_* call in area_alloc.c into a
no-op, and the lock itself was only declared under SERVER_MODE. Concurrent
workers therefore trampled area_List->next pointers and the heap damage
surfaced later as an unaligned tcache chunk.

Drop the no-op macro block and declare area_List_lock unconditionally as a
real static pthread_mutex_t so the guard works in every build mode. Add
la_worker_init_mutex and wrap la_apply_worker_start_session with it so the
whole per-worker bring-up path (net_client_sub_init, boot_register_client,
ws_init, sm_init, au_start, tr_init, ...) runs serially. That covers any
other shared client global that still sits behind a similarly no-op'd
mutex and protects worker startup even if future refactors introduce new
ones.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

```

## Review

- `area_alloc.c`의 no-op `pthread_mutex_*` 매크로 블록 제거 + `area_List_lock`을 항상 실제 mutex로 — CS/SA 빌드에서 area_List 동시 갱신 race 해소. 다른 파일에도 비슷한 no-op 매크로가 남아있을 가능성 (`locator.c`는 15에서 정리됨).
- `la_worker_init_mutex`로 worker bring-up 전체를 직렬화 — 광범위 가드라 안전하지만 동시 시작 시 정렬 비용 발생. 워커 N=10 기준 ws_init/boot_register_client/sm_init 등이 직렬화 → 시작 latency 누적. 실서비스에서는 init만 끝나면 사라지므로 영향 작음.
- mutex unlock이 `out:` 라벨에서 일괄 처리되어 모든 실패 경로 커버 — 누수 없음.
- 본질적 해결은 client global 각 site에 mutex를 정확히 거는 것이지만, PoC로는 startup 직렬화가 합리적.

## TODO

- 다른 client globals에 남아있는 no-op pthread_mutex 매크로 잔재 점검.
