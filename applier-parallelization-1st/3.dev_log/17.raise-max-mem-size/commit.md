# 17.raise-max-mem-size

- commit: `171b8bf32`
- date: 2026-04-22 14:54:14 +0000

## Message

```
Raise max_mem_size floor to mitigate VSZ inflation from parallel applylogdb workers

Multiple worker threads create per-thread glibc arenas (~64MB each),
causing VSZ-based memory checks to exceed limits despite low RSS.
Temporarily enforce MAX(max_mem_size, 4000) until RSS-based accounting is applied.

Tested with 10 threads, 4 tables, 100k rows each (success).

```

## Review

- `MAX(max_mem_size, 4000)`로 하한을 강제 — VSZ 기반 check를 우회하는 임시방편. 사용자가 설정한 더 큰 값은 그대로 존중되므로 부작용 작음.
- 진짜 해결책 (RSS 기반 accounting)은 미수행 — 주석에 명시. PoC scope에서 수용.

## TODO

- `la_get_mem_size()`를 RSS 기반으로 전환하고 임시 `MAX()` wrapper 제거.
