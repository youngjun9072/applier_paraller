# DB 엔지니어 1년차 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 요약

공식 최신 `/home/youngjun/Workspace/claude@9e094324b`와 `upstream/develop@5b9c0d815`의 HA 시작·적용·전환 caller를 clangd compile command와 source로 추적했다. 채택 finding은 **10건**이며, 중복을 늘리지 않았고 **더 이상 근거 있는 문제를 찾지 못함**. #7697에서 해결된 interrupt/error propagation 및 per-index lookup 성능 후보는 삭제하지 않고 `후속 PR 해결` 상태로 보존했다.

## DBA1-01 DDL 검사는 통과하지만 서버 DML은 복합 UNIQUE를 RK로 인정하지 않는다

- 심각도/신뢰도: **Critical / High**; 영향 페르소나: DBA/운영
- feature 근거/경로: `class_object.c:95-98` → `schema_manager.c:16115-16129`(ANY NOT NULL) → `execute_schema.c:10267-10273`; 서버는 `object_representation_sr.c:4712-4719`(ALL NOT NULL) → `locator_sr.c:8041-8049,8421-8426`이다.
- develop 비교: PK-only였던 develop과 달리 UNIQUE RK 확장에서 신규 발생.
- PR 이력: #6477/#6739/#7370 관련; 현재 HEAD 미해결.
- 재현/불변식: `UNIQUE(a,b)` 중 a만 NOT NULL인 ON 테이블 생성 후 DML. 승인된 테이블에서 replication log가 누락된다.
- 수정·테스트: 공용 ALL 판정과 CREATE/rkcheck/DML 동일 fixture.

## DBA1-02 노드마다 첫 번째 RK 후보를 다시 선택한다

- 심각도/신뢰도: **Critical / High**
- feature 근거/경로: source `locator_sr.c:8039-8049,8418-8426`; replica `btree.c:8285-8298` → `locator_sr.c:6848-6856`; master RK 이름 전달 TODO `object_representation_sr.c:4692`.
- develop 비교: 단일 PK에서 다중 UNIQUE 후보로 확장하며 신규.
- PR 이력: #7370 이후 EPIC CBRD-26096 TODO로 잔존.
- 재현/불변식: 노드별 constraint 물리 순서를 다르게 만든 뒤 DML apply. 동일 로그가 동일 row를 가리켜야 한다.
- 수정·테스트: RK id/name/domain을 catalog와 log에 고정하고 순서 불일치 노드 시험.

## DBA1-03 filtered/function UNIQUE가 RK 후보여서 행별 로그 공백이 생긴다

- 심각도/신뢰도: **High / High**
- feature 근거/경로: 자격식 `class_object.c:95-98`, `object_representation_sr.c:4702-4721`은 filter/function을 제외하지 않는다. filter false는 `locator_sr.c:7863-7876`에서 로그 지점 `8041-8049` 전에 continue한다.
- develop 비교: UNIQUE가 RK가 아니던 develop에는 없음.
- PR 이력: #7370 기능 도입 범위.
- 재현/불변식: filtered unique의 predicate 밖 행을 insert/delete하고 copy/apply LSA 및 row count 비교.
- 수정·테스트: 전 행을 덮지 않는 index를 RK에서 제외하고 rkcheck에도 동일 판정 사용.

## DBA1-04 다중 ALTER의 후속 RK 제거를 검사하지 않는다

- 심각도/신뢰도: **High / High**
- feature 근거/경로: 현재 절은 `execute_schema.c:1851-1855`인데 gate는 첫 `alter`를 사용한다(`2051-2054`); final check `2059-2072`.
- develop 비교: feature 신규 RK 불변식의 신규 우회.
- PR 이력: #6618/#6637/#6739 후속에도 남음.
- 재현/불변식: 비관련 첫 절 + RK 제거 후 `cubrid heartbeat start`; invalid schema가 생성되고 후속 rkcheck에서야 실패한다.
- 수정·테스트: `alter_code` 사용, CHANGE/RENAME/DROP INDEX 포함, 절 순서 조합 테스트.

## DBA1-05 rkcheck 실패 뒤 cub_server만 실행된 부분 시작 상태가 남는다

- 심각도/신뢰도: **High / High**
- feature 근거/경로: `util_service.c:3963-3973`에서 server start 뒤 rkcheck; `4001-4008`에는 server rollback이 없다.
- develop 비교: feature가 중간 validation step을 추가하며 신규.
- PR 이력: #6658/#6934 관련.
- 재현/불변식: 위반 DB HA start 실패 후 process/status 확인. 실패한 start는 시작 전 상태로 복구돼야 한다.
- 수정·테스트: 선검사 또는 서버 rollback, 여러 DB 중 N번째 실패 테스트.

## DBA1-06 자동 승격은 RK/FK를 재검사하지 않는다

- 심각도/신뢰도: **High / Medium**
- feature 근거/경로: rkcheck 호출은 `util_service.c:3194-3249,3969,5041-5043`; 승격은 `server_support.c:1852-1928`, `master_heartbeat.c:4396-4485`로 별도이며 연결이 없다.
- develop 비교: RK 필수 정책 도입 후 새 상태전이 공백.
- PR 이력: 시작 검사 #6658의 범위 밖.
- 재현/불변식: invalid schema 상태의 standby를 승격하고 ACTIVE 이전 차단 여부 확인.
- 수정·테스트: ACTIVE transition server-side precondition으로 검사.

## DBA1-07 mixed-target SBR이 OFF 대상도 변경한다

- 심각도/신뢰도: **High / Medium**
- feature 근거/경로: `execute_statement.c:3320-3343`은 ON 대상이 하나라도 있으면 전체 statement를 선택하고, `3404-3419,4112-4125`에서 RBR을 억제한다.
- develop 비교: class별 OFF와 신규 SBR gate 조합에서 발생.
- PR 이력: #6467/#6908 관련.
- 재현/불변식: ON/OFF 테이블 동시 UPDATE 후 replica OFF table checksum 비교.
- 수정·테스트: mixed target 금지/분리, checksumdb 회귀 시험.

## DBA1-08 OFF 테이블 TRUNCATE가 복제될 수 있다

- 심각도/신뢰도: **Medium / High**
- feature 근거/경로: `execute_statement.c:361-383`은 RK만 확인하고 flag를 확인하지 않으며 `16673-16682`가 SBR을 만든다.
- develop 비교: OFF 의미가 추가됐지만 기존 PK 기반 조건을 RK로만 치환해 악화.
- PR 이력: #6826/#6908 관련.
- 재현/불변식: OFF+PK table truncate 후 replica 독립 데이터 보존 확인.
- 수정·테스트: class replication flag gate 추가.

## DBA1-09 rkcheck가 violation list 파일 open 실패를 검사하지 않는다

- 심각도/신뢰도: **High / High**; 영향 페르소나: DBA/운영
- feature 근거/경로: `util_cs.c:2856-2864`의 `fopen` NULL이 `rkcheck`에서 확인되지 않고 `3320-3334,3346-3349`의 출력/검사 stream으로 전달된다.
- develop 비교: rkcheck 신규 utility 경로이므로 feature 신규.
- PR 이력: #6658/#6934/#7370; #7370 inline review 미해결.
- 재현/불변식: log directory EACCES/ENOSPC에서 HA start 또는 rkcheck. I/O 실패는 crash가 아닌 원인 보존 error여야 한다.
- 수정·테스트: open 직후 NULL/errno 처리와 권한·용량 fault injection을 추가한다.

## DBA1-10 FK violation 출력이 NULL `pk_c`를 역참조할 수 있다

- 심각도/신뢰도: **High / Medium**; 영향 페르소나: DBA/운영
- feature 근거/경로: `execute_schema.c:9833-9840`에서 PK lookup 결과를 검사하지 않고 `pk_c->name` 사용; `util_cs.c:2910-2914`에서 rkcheck가 호출한다.
- develop 비교: feature HA FK 진단 신규.
- PR 이력: #6505/#6658/#7370 inline review 미해결.
- 재현/불변식: restore/legacy catalog에서 referenced class PK lookup 실패 상태를 rkcheck한다.
- 수정·테스트: NULL-safe fallback 출력과 malformed catalog fixture를 추가한다.

## 운영 우선순위

DBA 관점에서는 DBA1-01/02를 데이터 정합성 차단 이슈로, DBA1-05/06을 HA runbook 차단 이슈로 우선 처리해야 한다.
