# PoC Design vs Implementation 비교

> 기준: 디자인 `2.design/poc_design.md` ↔ 구현 `feature/parallel_applylogdb_poc` cumulative vs `develop`.
> 작성일: 2026-05-13.

## 요약

- **`ha_worker` 설정 파라미터 미구현**. 워커 수는 여전히 `#define LA_APPLY_WORKER_COUNT 10` 하드코딩. (`cubrid_ha.conf` 경로 없음)
- **`ws_Repl_objs` / `ws_Repl_error_link` worker별 분리 미구현**. 설계는 "전역 변수를 제거하고 worker별로 분리한다"고 명시했으나 `src/object/work_space.c` 의 두 전역은 diff 에 한 줄도 나타나지 않음. parser-serialize mutex 와 client transaction 격리로 race 만 회피.
- **Reader 의 `_db_ha_apply_info` 갱신이 POC 우회로 비활성화**. `la_reader_commit_apply_info()` 호출이 주석 처리되고 `db_commit_transaction()` 만 수행 (commit `log_applier.c:2111`). 설계 단계 12 (LogReader 가 `_db_ha_apply_info` 업데이트) 가 실행되지 않음.
- **워커-로컬 통계/카운터가 일부만 격리**. `LA_APPLY_STATS` 로 결과만 전달하고 글로벌 `la_Info.insert_counter` 등에 누적 (reader 측 집계 패턴). 설계가 명시한 "worker별 보관" 의도와는 다른 방식이지만 race 는 회피.
- **설계가 명시한 long transaction worker 재탐색은 구현됨**. (`is_long_trans` 플래그 + `la_get_next_repl_item` refetch)

## 디자인에는 있는데 구현에 없음 (Gap)

### 1. `ha_worker` 설정 파라미터
- **디자인 위치**: poc_design.md "Appendix · Parameter" 및 요구사항 "worker 개수는 파라미터로 설정 가능해야 하며".
- **기대**: `cubrid_ha.conf` 에 `ha_worker=[n] # default=1`. 시작 시 파라미터 값으로 워커 N개 생성.
- **현실**: `src/transaction/log_applier.c:103` 에 `#define LA_APPLY_WORKER_COUNT 10` 으로 하드코딩. 모든 디버그 배열/상수가 이 매크로에 직접 의존. `PRM_ID_HA_*` 추가 없음 (`system_parameter.{c,h}` diff 0 라인). 전체 diff 에 "ha_worker" 토큰 등장 0회.
- **임팩트**: 운영 환경에서 worker 수 조정 불가. 빌드 재컴파일 필요.
- **권장**: `system_parameter.{c,h}` 에 `PRM_ID_HA_APPLYLOGDB_WORKER_COUNT` 추가, `la_apply_Workers` 동적 배열로 전환.

### 2. `ws_Repl_objs` / `ws_Repl_error_link` worker별 분리
- **디자인 위치**: 요구사항 "ws_Repl_objs와 ws_Repl_error_link는 전역 변수를 제거하고 worker별로 분리한다"; 변수 정리 표 "Worker-local".
- **기대**: 두 전역을 worker workspace 내부 멤버로 옮겨 worker가 독립 적재/flush.
- **현실**: `src/object/work_space.{c,h}` diff 에 `ws_Repl_objs` 도 `ws_Repl_error_link` 도 등장하지 않음. 두 전역은 그대로 유지됨. flush race 는 parser/SQL 직렬화 mutex 와 client tran 격리로만 회피 (사실상 직렬화).
- **임팩트**: 워커 간 flush 동시성이 사실상 직렬화되어 병렬화 효과가 제한됨 (`SUMMARY.md` 의 "다수 worker 환경에서 flush/commit 경합 정량화" 미해결 항목과 일치).
- **권장**: workspace 분리를 PoC 후속에서 우선 처리. `LA_APPLY_WORKER_CONTEXT` 에 ws state 멤버 추가.

### 3. LogReader 의 `_db_ha_apply_info` 갱신
- **디자인 위치**: 처리 흐름 12 "LogReader는 _db_ha_apply_info를 업데이트한다", 중요 원칙 "global committed_lsa와 _db_ha_apply_info는 LogReader가 관리한다".
- **기대**: retire 시점에 reader 가 `la_update_ha_last_applied_info()` 호출 → commit.
- **현실**: `log_applier.c:2111` 영역에서 `la_reader_commit_apply_info()` 호출이 `/* POC: skip only _db_ha_apply_info update for bottleneck verification */` 주석과 함께 비활성화됨. 환경변수 `LA_SKIP_READER_COMMIT_APPLY_INFO` 분기까지 추가 (debug 한정). 결과적으로 retire 경로에서는 `db_commit_transaction()` 만 호출.
- **임팩트**: PoC 측정 의도는 명시되어 있으나, 운영 적용 시 슬레이브 재시작/모니터링이 정상 동작하지 않음. master `_db_ha_apply_info` 가 갱신되지 않음.
- **권장**: PoC 후속에서 reader-side commit 경로 재활성화 + 비용 측정 분리.

### 4. Worker session 식별자 (`[worker]` suffix)
- **디자인 위치**: 명시적 요구는 아님. SUMMARY.md 의 잔여 TODO 와 commit 10번 컨텍스트.
- **기대**: worker session 의 `program_name` 끝에 `[worker]` suffix 를 붙여 마스터에서 식별 가능.
- **현실**: `CSS_HA_APPLIER_WORKER_PROGRAM_SUFFIX " [worker]"` 매크로 정의만 존재 (commit 10). 실제로 program_name 에 부여하는 호출처 없음.
- **임팩트**: HA 모니터링/디버깅 시 reader/worker 구분 불가.
- **권장**: worker session 시작 시 program_name suffix 부여.

### 5. 워커별 commit interval / flush threshold 독립 관리
- **디자인 위치**: 요구사항 "flush threshold와 commit interval도 worker별로 관리한다"; 변수 정리 Worker-local 의 `num_unflushed`, `la_check_time_commit(): static ha_mode`, `la_get_adaptive_time_commit_interval(): static delay_hist_idx` 등.
- **기대**: 각 워커가 자체 num_unflushed/commit interval state 유지.
- **현실**: `la_Info.num_unflushed` 는 여전히 글로벌 단일 필드 (`log_applier.c:514`). 워커는 `LA_APPLY_STATS.num_unflushed` 로 결과만 보고 → reader 측에서 `la_Info.num_unflushed += result->stats.num_unflushed` 누적 (line 2094). `la_check_time_commit` / `la_get_adaptive_time_commit_interval` 의 static 들도 worker-local 로 분리되지 않음. commit interval 자체가 retire 경로 단일 흐름이라 worker별 분리 의미가 약함.
- **임팩트**: 워커별 flush 타이밍 독립 제어 불가. 설계 의도 (워커별 독립 흐름) 와 실제 (reader 가 통합) 의 모델 차이.
- **권장**: 설계 의도를 유지할지(워커별 분리), reader 집계 패턴으로 변경할지 결정 후 설계 문서 또는 코드 정합 맞춤.

### 6. Worker-local 통계 카운터 (insert/update/delete/schema/commit/fail counter, total_rows 등)
- **디자인 위치**: 변수 정리 표 "Worker-local" 의 8개 counter / `total_rows` / `prev_total_rows` / `log_record_time` / `log_commit_time` / `status`.
- **기대**: 각 워커가 독립 카운터 보유 → 보고만 reader 가 수집.
- **현실**: 글로벌 `la_Info.{insert,update,delete,schema,commit,fail}_counter` 는 그대로 유지. `LA_APPLY_STATS` 가 result 단위 카운터를 운반하고 reader retire 경로에서 `la_Info.*_counter += result->stats.*_counter` 로 누적. 즉 "워커별 보관" 이 아니라 "워커가 보고하면 reader 가 합산" 패턴.
- **임팩트**: 기능적으로는 등가, race 도 회피. 다만 설계 명세와는 위치가 다름.
- **권장**: 설계 vs 실제 패턴 중 하나로 통일 (설계 문서를 reader-집계 패턴으로 갱신하는 편이 현실적).

### 7. Reader 의 `committed_rep_lsa` / `log_record_time` 워커 분리
- **디자인 위치**: 변수 정리 표 "Worker-local" 의 `committed_rep_lsa`, `log_record_time`, `log_commit_time`, `last_committed_lsa`, `last_committed_rep_lsa`.
- **기대**: worker-local 변수.
- **현실**: 글로벌 `la_Info` 멤버 유지 (line 467-469). result 가 운반하고 reader 가 일괄 갱신.
- **임팩트**: 항목 6 과 동일 — 패턴 차이.
- **권장**: 항목 6 과 함께 결정.

## 디자인과 다르게 구현된 부분 (Deviation)

### A. Dispatch-order FIFO 기반 in-order retire 추가
- **디자인 위치**: 설계는 "commit LSA 순서 기준으로 전역 완료 여부를 판정" 만 명시.
- **차이**: 구현은 `LA_DISPATCH_ORDER` FIFO 를 도입해 reader 가 dispatch 한 순서대로만 retire 함 (commit `18.preserve-retire-order`). 워커 결과는 out-of-order 도착 허용, retire 만 in-order. 설계보다 강한 제약.
- **임팩트**: 트랜잭션간 dependency 가 있을 때 안전. 단, 빠른 워커가 다음 결과를 대기하므로 throughput 상한이 commit LSA 순서에 묶임.
- **참고**: O(N) 선형 탐색 (`la_dispatch_order_find_by_seq`) 도 SUMMARY 의 후속 TODO.

### B. `la_apply_commit_list` 레거시 dead code 유지
- 본문 주석: "현재 호출 경로가 없는 (구) 레거시 함수지만 컴파일 호환을 위해 시그니처만 맞춘다" (line 8916).
- **임팩트**: 코드 가독성 저하, dead code path. SUMMARY 의 잔여 TODO 11번과 일치.
- **권장**: 정리 단계에서 제거.

### C. Final flush gating: `LA_APPLY_WORKER_REPL_ACTIVE_COUNT`
- 워커 main 에서 `if (worker_context.worker_idx < LA_APPLY_WORKER_REPL_ACTIVE_COUNT)` 조건으로만 final flush 수행 (현재 값 10 = WORKER_COUNT 와 동일이라 무영향이지만, "TEST ONLY" 주석 동봉).
- **임팩트**: PoC 측정용 토글로 의도되어있으나 코드 잔재.
- **권장**: 정리 단계에서 토글 제거 또는 환경변수화.

### D. `LOG_SYSOP_END` retire 처리 분기
- commit 19 "defer sysop end" 가 `entry->rectype != LOG_SYSOP_END` 일 때만 repl_list 슬롯 반환하도록 함.
- 설계에는 sysop end 처리 흐름이 명시되지 않음. 실제로는 long transaction 결합 시 anchor item 재구성과 `last_lsa` 갱신에 영향.
- SUMMARY 의 "long transaction 경로에서 SYSOP_END 무시한 효과 검증" 미해결 TODO.

## 디자인 명시 TODO 의 현재 상태

| 디자인 TODO | 상태 | 비고 |
| --- | --- | --- |
| 파일 동시 접근 시 I/O 병목 가능 | 미해결 | 측정 미수행. SUMMARY "file 동시 접근 I/O 병목 측정" 후속 항목. 워커 별 file descriptor 분리 안 함 (worker 가 `la_Info.act_log` 등 reader-owned 자원을 사용) |
| 캐시 & 버퍼 페이지 참조 시 lock 필요 | 부분 | cache_pb 계측 counter 추가 (commit 19 cache buffer diagnostics) 했으나 lock 정책은 미정. SUMMARY "cache_pb 계측 counter 갱신이 모두 mutex 안에서 일어나는지 정합 점검" 후속. `la_get_page` 경로의 cache 동시성 보호는 미명세 |

## 참고: 디자인 부합 항목 (간단 체크리스트)

- LogReader/ApplyWorker 모듈 분리: 추가 (구조체 `LA_APPLY_WORKER`, `la_apply_worker_main`)
- transaction 단위 worker queue: 추가 (`LA_WORKER_QUEUE`)
- commit 시점 dispatch: 추가 (`la_dispatch_apply_task`)
- LA_APPLY / LA_ITEM 공유 + worker 참조: 동작 (worker 가 `task.apply` 포인터 직접 사용)
- repl_lists 슬롯 retire 시 반환 (worker 즉시 반환 → race) 회피: 추가 (retire 시점에만 슬롯 반환)
- Worker-local scratch (`rec_type`, `undo_unzip_ptr`, `redo_unzip_ptr`, `recdes_pool`): `LA_APPLY_WORKER_CONTEXT` 로 격리
- Worker-local client session/transaction: 격리됨 (commit 05/06/07)
- `locator_Keep` thread-local: 전환됨 (commit 15)
- Long transaction anchor + log range re-traversal: 구현됨 (`is_long_trans` + `la_get_next_repl_item` refetch path)
- statement/DDL 워커 직접 실행: 동작 (`la_apply_statement_log` 워커 컨텍스트에서 호출)
- transaction 단위 처리 원칙: 준수
- queue → flush → commit 순서: 준수 (`la_apply_worker_main` 단계 enum)
- global `committed_lsa` reader 단독 갱신: 준수 (retire 경로에서만)
- HA applier state notification worker session 억제: 추가 (commit 10)
- `ha_worker` 설정 파라미터: 미구현 (Gap 1)
- `ws_Repl_objs` / `ws_Repl_error_link` worker별 분리: 미구현 (Gap 2)
- Reader 가 `_db_ha_apply_info` 갱신: 비활성 (Gap 3)
- 워커 session program_name suffix: 정의만 (Gap 4)
- 워커별 flush threshold/commit interval 독립 관리: 미구현 또는 패턴 차이 (Gap 5)
- 워커별 통계 카운터 보관: 패턴 차이 (Gap 6/7)
- `la_apply_commit_list` 정리: 미정리 (Deviation B)
- LA_APPLY_WORKER_REPL_ACTIVE_COUNT 테스트 토글 정리: 미정리 (Deviation C)
- 파일 동시 접근 I/O 병목 측정: 미수행
- 캐시/버퍼 lock 정책: 미수립
