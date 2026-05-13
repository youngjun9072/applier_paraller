# Step 1. 병렬화 개발 — 최종 변경사항 요약

- **브랜치**: `feature/parallel_applylogdb_poc` (vs `develop`)
- **기간**: 2026-04-15 ~ 2026-04-30
- **커밋 수**: 27개 (디버그/계측 8개 묶음 포함 → 본 디렉토리 기준 20개 항목)
- **변경 규모**: 46 files changed, +4,038 / −907

## 최종 도달 상태

### 구조 변경
- `log_applier.c`에 LogReader/ApplyWorker 분리 구조 도입 — 단일 흐름을 reader 디스패치 + 다수 worker 스레드로 재구성.
- transaction 단위 worker 큐 도입, commit log 시점에 dispatch.
- worker 완료 보고와 retire 순서 보존 메커니즘 추가.
- long transaction의 sysop end 처리를 commit dispatch 시점으로 지연.

### Worker 격리
- worker별 client session / transaction 분리.
- worker-local scratch state (`rec_type`, unzip ptr, recdes pool 등) 도입.
- `locator_Keep` 캐시를 thread-local로 전환.
- 일부 전역 client state를 thread-local로 분리, 시작 시점 race 가드 추가.
- HA applier state notification을 worker session에서 억제.

### 클라이언트/네트워크
- CS/SA 빌드에서 multi-connection client 지원 활성화.
- parser thread-safety 보강.

### 운영 파라미터
- worker 수 확장 경로 마련 (2 worker → N).
- VSZ 팽창 완화를 위해 `max_mem_size` 하한 상향.

### 디버그/계측
- reader/worker 처리량, queue depth, flush/statement context, cache buffer, timing breakdown 등 다층 진단 로그 추가 (debug 모드 한정 출력).

## 항목별 인덱스

| # | 디렉토리 | 핵심 |
| --- | --- | --- |
| 01 | `01.transaction-worker-queue` | transaction 단위 worker queue 스켈레톤 |
| 02 | `02.error-context-registration` | worker thread error context 등록 |
| 03 | `03.split-completion-reporting` | 완료 보고와 reader dispatch 분리 |
| 04 | `04.multi-connection-client` | CS/SA multi-connection 지원 |
| 05 | `05.worker-local-client-sessions` | worker-local client session |
| 06 | `06.fix-session-isolation` | session 격리 버그 수정 |
| 07 | `07.isolate-client-transactions` | client transaction 격리 |
| 08 | `08.isolate-worker-state` | worker state 격리 |
| 09 | `09.fix-perf-and-parser` | 성능/파서 thread-safety |
| 10 | `10.suppress-state-notify` | worker session HA state notify 억제 |
| 11 | `11.scale-to-2-workers` | 2 worker + dispatch-order FIFO |
| 12 | `12.worker-local-scratch` | worker-local scratch state |
| 13 | `13.increase-workers-tls-globals` | worker 수 확장 + 전역 TLS 분리 |
| 14 | `14.refine-thread-local-tran` | thread-local tran state 정제 |
| 15 | `15.locator-cache-tls` | `locator_Keep` cache TLS화 |
| 16 | `16.guard-client-globals` | client globals startup race 가드 |
| 17 | `17.raise-max-mem-size` | `max_mem_size` 하한 상향 |
| 18 | `18.preserve-retire-order` | worker 결과 retire 순서 보존 |
| 19 | `19.defer-sysop-end` | sysop end를 commit dispatch로 지연 |
| 20 | `20.debug-instrumentation` | 디버그/계측 커밋 묶음 (8개) |

## 잔여 이슈 / TODO

- 다수 worker 환경에서 flush/commit 경합 정량화.
- file 동시 접근 I/O 병목 측정.
- cache & buffer 페이지 참조 lock 정책 정리.
- worker 수 ↑ 시 메모리 사용량 (VSZ) 안정화.

## Review 요약

- 단계적 격리: error context (02) → client session (05/06) → client transaction (07) → worker state TLS (08) → scratch context (12) → locator cache TLS (15) → startup race 가드 (16) 순으로 worker 간 공유 상태를 좁혀 나감. 매 단계에서 직전 단계가 미해결로 남긴 race를 정확히 짚어 해소하는 흐름.
- Dispatch/Retire 분리: 단일 worker 큐(01)에서 동기 wait(03), dispatch_order FIFO(11), seq 기반 out-of-order collect + in-order retire(18)까지 점진 확장. committed_lsa는 항상 reader가, 커밋 LSA 순서로만 갱신하는 원칙은 일관됨.
- PoC 한정 트레이드오프: `MULTI_CONN_TO_A_SERVER` 일괄 적용, `MAX(max_mem_size, 4000)` 하한 강제, parser/SQL 직렬화 mutex, worker startup 직렬화 mutex 등 임시방편이 반복 등장. 모두 주석/메시지에 의도 명시.
- 누락/오류 신호: 10번 worker session 식별용 `" [worker]"` suffix는 정의만 되고 어디서도 program_name에 부여되지 않음. 18번 커밋 메시지는 실제 변경 본질(retire-order 보존)이 아닌 무관 항목을 적어 정합성 깨짐.
- 디버그 부담: 11~20에 걸쳐 er_log_debug가 폭증. NDEBUG gate와 `LA_DEBUG_LOG` 매크로로 release는 차폐되나, debug 빌드에서 hot path I/O가 측정값을 왜곡할 수 있음.
- 메모리/리소스: TLS 폭이 넓어지고 worker 수가 1→10으로 증가하면서 per-thread arena와 large TLS 배열로 VSZ가 빠르게 늘어남. 17번이 임시 대응이지만 RSS 기반 회계로의 전환이 미해결 본질 과제.

## 잔여 TODO 집계

### Client session / network
- net_client_sub_init이 reader의 `net_Server_name/net_Server_host`를 그대로 공유 — worker별 host/db target 명시 전달 경로 마련 (05/13).
- worker session 식별용 `" [worker]"` suffix 정의만 존재. 실제 worker 등록 시 program_name 끝에 suffix를 부여하는 코드 추가 (10).

### 격리 / 정합성
- 다른 client globals에 남아있는 no-op `pthread_mutex_*` 매크로 잔재 점검 (16).

### 정리 / 청소
- legacy `la_apply_commit_list` 죽은 코드 제거 (11).
- 18번 커밋 메시지를 retire-order 변경 본질에 맞게 정정 (18).

### 성능
- `la_dispatch_order_find_by_seq` O(N) 선형 탐색 → seq→index 매핑/직접 인덱싱으로 개선 (18).
- worker-local scratch 분리 (12에서 일부 진행 → 후속에서 추가 가능 항목 추적) (08).

### 메모리
- `la_get_mem_size()`를 VSZ → RSS 기반으로 전환하고 임시 `MAX(max_mem_size, 4000)` wrapper 제거 (17).

### 시나리오 검증
- long transaction 경로에서 SYSOP_END 무시한 효과 검증 (anchor item 재구성/last_lsa 갱신) (19).

### 디버그/계측
- debug 빌드 hot path `er_log_debug` 비용으로 인한 성능 측정 왜곡 — sampling 등 비용 절감 옵션 검토 (20).
- cache_pb 계측 counter 갱신이 모두 mutex 안에서 일어나는지 정합 점검 (20).
