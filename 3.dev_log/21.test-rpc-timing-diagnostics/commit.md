# 21.test-rpc-timing-diagnostics

> **종류: 테스트/계측 코드**. 운영 동작을 변경하는 기능 커밋이 아니라, 병렬 apply 경로의 호출별 timing과 식별자 진단을 위한 디버그/계측 코드.

- commit: `7cf20e2d6`
- date: 2026-05-13 15:50:20 +0000

## Message

```
applylogdb: add per-call timing and identity diagnostics across RPC path

Adds end-to-end NDEBUG-only instrumentation to investigate per-call wall
inflation under parallel apply:

- log_applier: new add_and_flush wall/count series (combined per-call cost of
  la_repl_add_object + la_flush_repl_items inside one apply_{insert,update,
  delete}_log call) and milestone logs (every 1000 calls) that print TLS
  identity (client_support, locator_repl, locator_Keep addresses) so we can
  confirm per-worker isolation. Also adds a TEST-ONLY
  LA_APPLY_WORKER_REPL_ACTIVE_COUNT toggle to skip repl_obj add+flush for
  workers >= N, isolating the add/flush contribution to overall throughput.
- network_interface_sr / locator_sr: per-call wall around slocator_repl_force
  and xlocator_repl_force entry points, splitting client RPC wall from
  server-side processing time when comparing N=1 vs N>1 runs.
- client_support / locator: small diagnostic accessors
  (css_get_open_conn_fd_for_host, locator_get_keep_addr) used only for the
  identity logs above.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>

```

## Review

- 측정/식별용 코드로 운영 경로는 NDEBUG 분기로 차폐. 기능 변경 없음.
- `LA_APPLY_WORKER_REPL_ACTIVE_COUNT` 토글은 add+flush 기여도를 분리해 보기 위한 임시 우회. 실험 종료 후 제거 필요.
- 매 1000 calls 단위 milestone 로그가 hot path I/O를 일으키므로 측정값 자체 왜곡 가능성 — sampling 간격을 결과에 함께 기록.
- per-call wall 추가가 lock/syscall 비용 비교를 위해 RPC entry/return 양쪽에 들어감. 측정 종료 후 정리할 entry 위치 명확히 표시.

## TODO

- 실험 종료 후 `LA_APPLY_WORKER_REPL_ACTIVE_COUNT` 토글 및 진단 accessor (`css_get_open_conn_fd_for_host`, `locator_get_keep_addr`) 제거.
- 측정 결과 정리 후 진단 로그/계측 코드 운영 코드에서 분리 (옵션: 별도 debug-only 파일로 이동).
