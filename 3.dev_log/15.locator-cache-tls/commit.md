# 15.locator-cache-tls

- commit: `82b4434dc`
- date: 2026-04-22 14:16:04 +0000

## Message

```
Convert locator_Keep cache to thread-local storage for parallel applylogdb

applylogdb runs as CS_MODE and with N>1 apply workers N threads share a
single process-wide locator_Keep cache whose pthread mutex is no-op'd in
non-SERVER modes. Concurrent allocate/free paths would hand out the same
cached LC_COPYAREA pointer to multiple workers, each calling free(), and
the resulting double-free corrupted the tcache.

Give every thread its own locator_Keep via __thread storage, drop the
per-area pthread_mutex_t fields that no longer serve a purpose, and add
locator_ensure_tls_initialized() so lazily-started threads get a valid
cache on first use. Wire la_apply_worker_main's exit path to call
locator_free_areas() so per-worker slots are released instead of leaked.

Bump LA_APPLY_WORKER_COUNT from 4 to 10 in the same change to match the
PoC target the TLS conversion is designed for.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>

```

## Review

- `locator_Keep`을 `__thread`로 전환하고 per-area pthread mutex 필드를 제거 — 핵심 double-free 원인 해소. `locator_free_areas()`를 worker exit 경로에서 호출하여 slot leak 방지.
- `locator_ensure_tls_initialized()`를 모든 allocate/free 진입에서 호출하지만, `locator_Is_initialized` 자체가 TLS이므로 첫 호출 시점은 thread별. lazy init 자체는 OK인데, `locator_initialize_areas`를 reader가 별도로 호출한다면 reader 스레드에서만 init되고 worker 첫 호출 시 또 init되는 구조는 정합.
- `__thread`는 C++ globals와 함께 쓸 때 destructor가 자동 호출되지 않으므로 명시적 `locator_free_areas()`가 필수. worker 외 다른 worker-스타일 short-lived thread가 등장하면 leak 가능.
- `LA_APPLY_WORKER_COUNT` 4 → 10으로 동시에 상향 — TLS 변환의 효과 측정 의도이지만 메모리 footprint도 비례 증가.

## TODO

- (none)
