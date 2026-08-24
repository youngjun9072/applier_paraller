# CBRD-26246 후보 감사 및 최종 집계

- 재감사일: 2026-08-24
- feature: `9e094324b8ef`
- develop: `5b9c0d8155f8`
- 공통 조상: `b646647eca4236057ea7c3c28960e61c53b0c209`
- raw 관찰: 20개 개발 관련 페르소나, 187개
- 조사 범위: feature 고유 35개 파일의 모든 diff hunk와 영향 caller/callee

## 결론 수량

기존 문서의 “최종 16건”은 이번 E2E 재감사 뒤 더 이상 유효하지 않다.

| 상태 | 수 | ID | 의미 |
|---|---:|---|---|
| 확정 feature 결함 | **10** | CR-02, 03, 04, 06, 07, 09, 10, 11, 14, NEW-008 | 현재 HEAD에서 실행 경로와 반대 조건을 모두 확인 |
| 선행 상태·손상 metadata 조건부 | **2** | CR-13, CR-15 | 조건을 명시하면 도달 가능하지만 단독 정상 SQL 결함으로 일반화할 수 없음 |
| develop 기존/feature 악화 | **1** | CR-12 | 원문을 지우지 않되 feature 신규 결함 수에서는 제외 |
| 운영 권고 | **1** | NEW-004 | 진단 증거 보존 문제이며 데이터 정합성 결함은 아님 |
| 입증 보류·정책/품질 | **5** | CR-05, NEW-001, 005, 006, 007 | 코드 사실은 있으나 독립 사용자 실패 또는 제품 계약 미확정 |
| 오분석·종속·사용자 제외 | **3** | CR-08, CR-17, CR-16 | 삭제하지 않고 정정 상태 보존 |
| CR-13에 병합 | **2** | NEW-002, NEW-003 | restart/failback의 단순 rkcheck 부재는 독립 결함이 아님 |

따라서 최종보고서는 **확정 feature 결함 10건**을 핵심 결과로 제시하고, 조건부 2건,
develop 기존/악화 1건, 운영 권고 1건을 별도 절에 남긴다. 숫자를 모두 합쳐 “14개 동일 신뢰도의
결함”으로 표현하지 않는다.

## 확정 feature 결함

| ID | 심각도 | 독립 root cause | E2E 핵심 | develop 비교 | 현재 HEAD |
|---|---|---|---|---|---|
| CR-02 | High | composite UNIQUE의 ANY-NN client 승인과 ALL-NN server 판정 불일치 | DDL/rkcheck 성공 후 master가 row log를 만들지 않아 applier 미호출 | PK-only라 비노출 | 잔존 |
| CR-03 | High | client unique family에는 reverse가 있으나 server는 `BTREE_UNIQUE`만 허용 | reverse-only ON table의 master row log 없음 | PK-only라 비노출 | 잔존 |
| CR-04 | High | filtered/online UNIQUE를 total-row RK 후보로 인정 | predicate 밖 INSERT/DELETE 무로그, UPDATE는 존재하지 않는 old key lookup | filtered UK를 RK로 사용하지 않음 | 잔존 |
| CR-06 | High | multi ALTER loop가 현재 clause가 아닌 head code 검사 | 비관련 head + sole-RK DROP이면 final check 우회 | 신규 RK validator 없음 | 잔존, #7370 review 미해결 |
| CR-07 | High | DROP INDEX 등 RK mutation entry point가 final validator 밖 | standalone DROP INDEX 뒤 ON class가 RK 0개 | UK-RK invariant 없음 | 잔존 |
| CR-09 | High | write target 중 ANY ON이면 원본 SQL 전체 SBR | OFF write target까지 slave에서 변경 | class별 OFF 없음 | 잔존, #6908 포함 |
| CR-10 | High | SBR eligibility가 OFF read dependency를 검사하지 않음 | master/slave의 OFF source 값으로 ON target 결과 분기 | class별 OFF 없음 | 잔존, #6908 포함 |
| CR-11 | High | TRUNCATE gate가 RK만 보고 class ON/OFF를 보지 않음 | OFF+RK table의 slave 데이터도 truncate | 기존 PK SBR은 있으나 OFF 없음 | 잔존 |
| CR-14 | High | rkcheck가 `fopen` 반환 NULL을 검사하지 않음 | EACCES/ENOSPC/EMFILE에서 NULL stream 사용 | utility 없음 | 잔존, #7370 review 미해결 |
| NEW-008 | Low | OFF class flag fetch가 RK 후보 loop 안에 있음 | row 수×후보 수만큼 class record fetch | class OFF 없음 | #7697 뒤에도 잔존 |

## 조건부·develop 기존·운영 권고

| ID | 상태 | 조건과 제한 | 처리 |
|---|---|---|---|
| CR-13 | 조건부 High | CR-06/07로 RK가 사라지고 이후 DML log가 누락돼야 applier-done promotion이 손실을 통과시킴 | 선행 결함을 막고 promotion defense-in-depth 추가 검토 |
| CR-15 | 조건부 Medium | 정상 FK에는 PK가 존재한다. 손상·legacy catalog에서 `pk_c`가 NULL일 때만 진단 crash | malformed catalog용 NULL-safe 진단 |
| CR-12 | develop 기존/feature 악화 | develop도 server start 뒤 copy/apply failure rollback이 없다. feature가 rkcheck 실패 지점을 추가 | 신규 결함 집계 제외, HA start 원자성 개선 항목으로 보존 |
| NEW-004 | 운영 권고 Low | 같은 분의 동일 DB rkcheck가 같은 `.list`를 `w`로 다시 열 때만 직전 증거 삭제 | 초/PID/rotation/exclusive create 정책 검토 |

## 비채택 후보 보존표

| 후보 | 판정 | 근거 |
|---|---|---|
| CR-05 source/applier first local candidate | 입증 보류 | log에 logical RK identity가 없는 것은 사실이나, 동일 HA DDL history에서 node별 logical index order가 달라지는 최소 경로를 입증하지 못함 |
| CR-08 partition promotion metadata | 오분석/CR-02 종속 | runtime constraint는 property에서 재구성되고 정상 ON root의 PK/UNIQUE property가 promotion 뒤 남음 |
| CR-16 helper 미교체 | 사용자 요청 제외 | 모든 `heap_is_replication_class`가 `heap_get_class_repl_on`으로 교체됐다고 가정 |
| CR-17 public error constants | 오분석 | 설치 대상 `src/base/error_code.h`를 `dbi.h`/`dbi_compat.h`가 include하며 CMake도 public header로 설치 |
| NEW-001 ALTER VCLASS flag | 정책/품질 | 의미 없는 metadata는 허용되지만 row replication failure가 없음 |
| NEW-002 heartbeat crash restart | CR-13 병합 | 정상 start 뒤 동일 catalog 재시작은 재검사 부재만으로 결함이 아님 |
| NEW-003 failback/switchover | CR-13 병합 | 기존 client fencing/drain이 있으며 invalid catalog 선행 때만 영향 |
| NEW-005 `get_print_flags` prototype | 품질 | 정의·caller 없는 static declaration이며 build/runtime failure 없음 |
| NEW-006 stale backup pre-apply rkcheck | 정책/조건부 | 자동 start가 future repair DDL 적용 전에 막힐 수 있으나 공식 rejoin/readiness 순서 확인이 필요 |
| NEW-007 OFF child→ON parent CASCADE | 정책 | slave parent apply가 cascade를 다시 수행해 무결성은 유지됨. OFF의 제품 의미 결정 필요 |
| function UNIQUE 전체 | 판정 불가 | expression이 양 노드에서 동일 평가될 수 있어 filtered index 실패를 그대로 일반화할 수 없음 |
| class flag 값 32 하드코딩 | 유지보수 위험 | 현재 enum 값과 일치해 현재 실행 오류 없음 |
| generation/epoch/quorum/fencing 일반론 | feature 코드 비적용 | CUBRID의 기존 HA 구조 전체에 대한 스펙 요구이며 이 diff의 독립 결함으로 특정되지 않음 |
| server-side flag fetch interrupt/assert | 후속 PR 해결 | #7697이 error-returning helper로 교체. 사용자의 교체 완료 가정과도 일치 |

## 187개에서 위 결과로 병합한 기준

다음 세 가지가 같을 때만 한 root cause로 병합했다.

1. 최초 잘못된 상태를 만드는 코드 지점
2. 깨지는 불변식
3. 수정해야 할 함수 또는 계층

직군에 따른 영향 설명은 원문에 보존했다. 반대로 같은 사용자 증상이라도 수정 지점이 다른 CR-02와
CR-03은 분리했고, CR-04의 INSERT/DELETE와 UPDATE는 실행 흐름을 따로 검증하되 후보 자격에 filter가
없다는 동일 root cause로 하나로 병합했다.

## 검증 자료

- 최소 입력·실행 순서·대조 조건: [E2E_FINDING_WORKSHEETS.md](E2E_FINDING_WORKSHEETS.md)
- 187개 관찰의 최신 상태 색인: [RAW_187_REAUDIT_MAP.md](RAW_187_REAUDIT_MAP.md)
- 공통 조상 삼자 비교와 세션 체크포인트: [RAW_FULL_REAUDIT.md](RAW_FULL_REAUDIT.md)
- 관련 PR 도입·후속 해결: [PR_HISTORY.md](PR_HISTORY.md)
