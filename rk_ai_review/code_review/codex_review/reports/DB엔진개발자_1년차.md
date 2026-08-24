# DB 엔진 개발자 1년차 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 분석 메모

- 공식 최신 `/home/youngjun/Workspace/claude@9e094324b`를 `upstream/develop@5b9c0d815`와 비교하고 feature compile DB의 SA_MODE C++17 정의·참조를 source와 대조했다.
- 채택 finding은 **10건**. #7697에서 해결된 interrupt assert·error propagation과 per-index lookup 성능 후보는 삭제하지 않고 `후속 PR 해결` 상태로 보존했다. 독립 root cause가 소진되어 **더 이상 근거 있는 문제를 찾지 못함**.

## ENG1-01 client/server RK predicate가 동일하지 않다

- 심각도/신뢰도: **Critical / High**; 영향: DB 엔진
- feature 근거: `class_object.c:95-98`의 unique-family+ANY NN과 `object_representation_sr.c:4707-4719`의 BTREE_UNIQUE+ALL NN가 다르다. callers는 `execute_schema.c:9861-9878,10267-10273`, `locator_sr.c:8041-8049,8421-8426`이다.
- develop 비교: PK-only predicate를 확장한 feature 신규 회귀.
- PR 이력: #6477/#6739/#7370.
- 재현/불변식: composite UK 일부 nullable 및 REVERSE UNIQUE 각각에 대해 client 승인/server 후보 결과를 비교.
- 수정·테스트: serialized class representation 기준의 단일 pure predicate를 client/server에서 공유하거나 서버 RPC 검증으로 단일화.

## ENG1-02 RK identity 없이 index array order를 protocol로 사용한다

- 심각도/신뢰도: **Critical / High**
- feature 근거: source loops `locator_sr.c:7861-8049,8418-8426`; apply `btree.c:8276-8298` → `locator_sr.c:6848-6856`. `object_representation_sr.c:4692`가 결함 가능성을 직접 TODO로 남긴다.
- develop 비교: PK identity가 유일했던 develop 대비 신규.
- PR 이력: #7370/CBRD-26096.
- 재현/불변식: 동일 논리 schema의 OR_CLASSREP index order를 다르게 만들고 packed key를 apply.
- 수정·테스트: replication log에 constraint stable id와 domain signature 포함; apply 시 일치 검증.

## ENG1-03 filtered unique의 predicate-false branch가 replication block도 건너뛴다

- 심각도/신뢰도: **High / High**
- feature 근거: candidate는 filter를 보지 않는다(`object_representation_sr.c:4694-4721`). `locator_add_or_remove_index_internal`은 `7863-7876`에서 continue하고 replication insertion은 `8041-8049`이다.
- develop 비교: UNIQUE RK 도입 신규.
- PR 이력: #7370.
- 재현/불변식: predicate false insert/delete에서 `repl_insert_lsa`/log record 부재 확인.
- 수정·테스트: partial index를 후보에서 제외. candidate unit test와 locator integration test.

## ENG1-04 function/reverse unique의 두 표현 계층 type mapping이 불일치한다

- 심각도/신뢰도: **High / High**
- feature 근거: client는 `SM_IS_CONSTRAINT_UNIQUE_FAMILY`라 reverse unique를 포함(`class_object.h:111-114`, `class_object.c:95-98`)하지만 server는 `BTREE_UNIQUE`만 허용(`object_representation_sr.c:4707`). function metadata도 client/server 자격식 어디에도 배제되지 않는다.
- develop 비교: feature 신규.
- PR 이력: #7370.
- 재현/불변식: reverse unique 또는 nullable 결과를 낼 수 있는 function unique가 유일한 candidate인 ON class 생성 후 DML.
- 수정·테스트: 허용 type을 명시적으로 일치시키고 expression 결과의 total/non-null/global uniqueness를 보장하지 못하면 제외.

## ENG1-05 multi ALTER loop가 잘못된 node를 참조한다

- 심각도/신뢰도: **High / High**
- feature 근거: loop local `alter_code`는 `execute_schema.c:1851-1855`; 새 gate는 `alter->info.alter.code`를 참조(`2051-2054`). macro `109-114`도 `PT_CHANGE_ATTR`/rename 등을 빠뜨린다.
- develop 비교: feature 신규 code defect.
- PR 이력: #6618/#6637/#6739.
- 재현/불변식: 첫 clause non-related, second clause drops/invalidates RK; `need_check_repl_constraint`는 false 유지.
- 수정·테스트: local `alter_code`, exhaustive switch/helper, each relevant code at every list position.

## ENG1-06 rkcheck 삽입은 start state machine을 원자적으로 만들지 못했다

- 심각도/신뢰도: **High / High**
- feature 근거: `util_service.c:3963-3973` server side effect 후 check; error unwind `4001-4008`은 pids container만 destroy.
- develop 비교: #6658 단계 삽입으로 신규 partial state.
- PR 이력: #6658/#6934.
- 재현/불변식: child server start 성공/check 실패 injection. 함수 실패 반환 시 이전 process set과 같아야 한다.
- 수정·테스트: compensating stop 또는 preflight; fault injection at each DB/check iteration.

## ENG1-07 ANY-target SBR 선택이 per-class replication invariant를 파괴한다

- 심각도/신뢰도: **High / Medium**
- feature 근거: `execute_statement.c:3320-3343`은 bool ANY를 반환; caller `3404-3419,4112-4125`는 전체 statement의 RBR을 suppress하고 `do_replicate_statement`가 SQL text를 기록(`16502-16517`).
- develop 비교: #6908 계열 feature 변경 신규.
- PR 이력: #6467/#6908.
- 재현/불변식: ON/OFF mixed multi-target update/delete. class flag가 false인 target에는 어떤 replication effect도 없어야 한다.
- 수정·테스트: per-target plan 또는 mixed SBR rejection; derived view/trigger 포함.

## ENG1-08 TRUNCATE SBR gate가 class flag를 읽지 않는다

- 심각도/신뢰도: **Medium / High**
- feature 근거: `execute_statement.c:342-383`은 constraint만 찾고 `sm_is_replication_class`를 호출하지 않는다. caller `16673-16682`.
- develop 비교: PK→RK 치환만 하고 신규 OFF flag semantics를 반영하지 못한 악화.
- PR 이력: #6826/#6908.
- 재현/불변식: OFF class with PK/UK를 truncate. no statement replication이어야 한다.
- 수정·테스트: flag 선검사 및 ON/OFF × PK/UK/no-key matrix.

## ENG1-09 rkcheck가 nullable `FILE *`를 성공 전제로 사용한다

- 심각도/신뢰도: **High / High**; 영향: DB 엔진/utility
- feature 근거: `open_violation_list_file`은 `fopen`을 그대로 반환한다(`util_cs.c:2856-2864`). caller는 NULL branch 없이 출력 macro와 callbacks에 전달한다(`3320-3359`).
- develop 비교: feature 신규 utility code.
- PR 이력: #6658/#6934/#7370 inline review 미해결.
- 재현/불변식: fopen fault injection. 외부 resource 실패는 CUBRID error model로 전파되어야 한다.
- 수정·테스트: NULL 확인, `er_set`/errno 보존, cleanup 경로와 EACCES/ENOSPC 시험.

## ENG1-10 FK violation formatter가 PK lookup 성공을 검증하지 않는다

- 심각도/신뢰도: **High / Medium**; 영향: DB 엔진/utility
- feature 근거: `execute_schema.c:9833-9840`에서 `db_constraint_find_primary_key` 결과의 `pk_c->name`을 무조건 사용하고 `util_cs.c:2910-2914` callback 경로에서 실행된다.
- develop 비교: feature 신규 HA FK diagnostic.
- PR 이력: #6505/#6658/#7370 inline review 미해결.
- 재현/불변식: referenced class metadata에서 PK lookup 실패를 주입. 검증기는 metadata 이상을 진단해야지 자체 crash하면 안 된다.
- 수정·테스트: `pk_c == NULL` 처리, fallback 출력, malformed catalog test.

## 엔진 관점 우선 수정 순서

1. ENG1-01/02로 RK predicate와 identity protocol을 단일화한다.
2. ENG1-03/04로 허용 index 종류를 좁힌다.
3. ENG1-05~10의 DDL/HA/SBR/utility 오류 경로 회귀 테스트를 추가한다.
