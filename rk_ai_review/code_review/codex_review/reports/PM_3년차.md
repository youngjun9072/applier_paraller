# PM 3년차 관점 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

- 공식 대상: `/home/youngjun/Workspace/claude`, `feature/CBRD-26246-develop` (`9e094324b`) vs `upstream/develop` (`5b9c0d815`)
- 방법: feature compile DB(1,186 entries)와 clangd 20.1.8로 변경 심볼을 탐색하고, 실제 source의 DDL→catalog→DML log→apply 및 HA 시작 호출 경로를 대조했다. clangd의 전체-TU 진단은 생성 헤더가 develop build를 가리키므로 결함 판정의 단독 근거로 쓰지 않았다.
- 결과: 유효 finding **10건**. 최대 50건을 목표로 후보를 검토했으나, 중복 root cause와 develop에도 동일한 문제를 제외한 뒤 **더 이상 근거 있는 문제를 찾지 못함**.
- 영향받는 페르소나 필드: 아래 10건 모두 `PM 3년차`이며, 각 항목의 `영향`은 추가 영향 범위를 적는다.
- 최신 필터: #7697이 해결한 interrupt/error propagation 및 per-index lookup 성능 후보는 `후속 PR 해결` 상태로만 보존한다.

## PM3-01 — HA 사전검사는 통과하지만 복제 로그를 만들 수 없는 복합 UK가 허용된다

- 심각도/신뢰도: **High / High**
- 영향: PK 없는 기존 업무 테이블을 UK로 HA 편입하면 준비 완료로 오판한다.
- feature 근거/실행 경로: `src/object/class_object.c:95-98` → `src/object/schema_manager.c:16115-16129`는 복합 UK 컬럼 중 **하나라도** NOT NULL이면 RK로 인정한다. CREATE/ALTER/rkcheck는 이 판정을 사용한다(`src/query/execute_schema.c:9861-9872`, `src/executables/util_cs.c:2898-2907`). 반면 DML은 `src/base/object_representation_sr.c:4694-4721`에서 **모든** 컬럼이 NOT NULL이어야 로그를 만든다(`src/transaction/locator_sr.c:8041-8055,8425-8433`).
- develop 비교: RK/UK 기능 자체가 없어 동일 경로가 없으며 feature 신규.
- PR 이력: #6798에서 PK 강제를 제거해 UK를 RK로 확장한 맥락과 직접 관련되고, #7370 통합 후 현재 HEAD에도 남아 있다.
- 재현/불변식: `(a INT NOT NULL, b INT, UNIQUE(a,b)) REPLICATION=ON`으로 HA에서 생성 후 INSERT/UPDATE. “readiness가 승인한 ON 테이블의 모든 DML은 RK 로그를 생성한다”는 불변식이 깨진다.
- 수정/테스트: client 공용 판정을 all-NOT-NULL로 바꾸고 server와 동일 helper/규칙을 공유한다. 복합 UK의 NN 조합별 CREATE, rkcheck, INSERT/UPDATE/DELETE를 회귀 시험한다.

## PM3-02 — REVERSE UNIQUE가 준비 완료로 승인되지만 서버 RK 후보에서는 제외된다

- 심각도/신뢰도: **High / High**
- 영향: 지원되는 것처럼 보이는 스키마가 실제 HA 데이터 복제를 수행하지 못한다.
- feature 근거/실행 경로: `SM_IS_CONSTRAINT_UNIQUE_FAMILY`은 REVERSE_UNIQUE를 포함한다(`src/object/class_object.h:111-115`), 그래서 `class_object.c:95-98`의 CREATE/ALTER/rkcheck 검증은 승인한다. 서버는 `object_representation_sr.c:4702-4709`에서 PK와 `BTREE_UNIQUE`만 허용하고 reverse unique를 거부한다.
- develop 비교: UK를 RK로 쓰는 기능이 없어 feature 신규.
- PR 이력: #6798/#7370의 UK 기반 RK 범위 구현에 포함된 타입 집합 불일치다.
- 재현/불변식: PK 없이 `REVERSE UNIQUE(a)`와 `a NOT NULL`만 둔 ON 테이블로 HA 시작 후 DML. 승인 계층과 실행 계층의 후보 집합이 같아야 한다.
- 수정/테스트: reverse unique를 명시적으로 양쪽에서 제외하거나 서버/apply까지 지원한다. SHOW CREATE→rkcheck→DML apply 종단 시험을 추가한다.

## PM3-03 — 복수 ALTER의 후속 절이 RK를 제거해도 첫 절만 보고 최종 검사를 생략한다

- 심각도/신뢰도: **High / High**
- 영향: 정상적인 스키마 배포 한 문장으로 ON 테이블을 복제 불가능 상태로 만들 수 있다.
- feature 근거/실행 경로: `do_alter()`는 각 `crt_clause`를 순회하지만 `src/query/execute_schema.c:2051`에서 `crt_clause->info.alter.code`가 아니라 첫 노드인 `alter->info.alter.code`를 검사한다. 따라서 첫 절이 비관련이고 뒤 절이 `DROP CONSTRAINT/PRIMARY KEY`면 `check_ha_repl_constraint()` 호출(`2059-2069`)이 생략된다.
- develop 비교: RK 최종 검증 gate가 feature에서 추가되어 신규.
- PR 이력: #6637의 multi ALTER PK 변경과 #6739의 제거 제약/refactoring 이후에도 현재 식별자 오류가 남았다.
- 재현/불변식: `ALTER TABLE t ADD COLUMN x INT, DROP CONSTRAINT only_rk;`. 성공 후 ON 테이블에 RK가 없어서는 안 된다.
- 수정/테스트: 2051을 `alter_code`/`crt_clause` 기준으로 바꾸고 절 순서를 뒤집은 조합 시험을 추가한다.

## PM3-04 — 컬럼 MODIFY/CHANGE로 UK의 NOT NULL을 제거해도 RK 검사가 실행되지 않는다

- 심각도/신뢰도: **High / High**
- 영향: 일반 migration이 HA 복제 가능성을 조용히 제거한다.
- feature 근거/실행 경로: `IS_REPL_CONSTRAINT_RELATED_ALTER`는 ADD/DROP attribute, DROP constraint/PK만 포함한다(`src/query/execute_schema.c:109-114`). 실제 ALTER dispatcher에는 `PT_MODIFY_ATTR_MTHD`, `PT_CHANGE_ATTR`가 존재한다(`1874-1879,2018-2020`). NOT NULL 제거 뒤 최종 검사(`2059-2069`)가 실행되지 않는다.
- develop 비교: feature 신규 RK invariant라 신규.
- PR 이력: #6618/#6739의 “RK 제거 제약”이 constraint drop만 막고 속성 변경 경로를 덜 포괄한 상태다.
- 재현/불변식: 유일 RK가 `UNIQUE(a), a NOT NULL`인 ON 테이블에서 `ALTER ... MODIFY a ... NULL`; HA 중 최종 스키마에는 유효 RK가 남아야 한다.
- 수정/테스트: RK 후보 자격을 바꿀 수 있는 MODIFY/CHANGE/NOT NULL 관련 모든 코드를 gate에 넣고 단일·복수 ALTER를 시험한다.

## PM3-05 — 부분 UNIQUE와 구축 중 UNIQUE도 활성 RK로 선택될 수 있다

- 심각도/신뢰도: **High / Medium**
- 영향: 온라인 인덱스 배포 또는 부분 인덱스 사용 중 일부 행이 replica에서 식별되지 않을 수 있다.
- feature 근거/실행 경로: `OR_INDEX`에는 `filter_predicate`, `func_index_info`, `index_status`가 있다(`src/base/object_representation_sr.h:179-194`). 그러나 후보 함수는 type/NOT NULL만 본다(`object_representation_sr.c:4694-4721`). 선택은 첫 후보에서 끝난다(`src/storage/btree.c:8285-8298`), DML도 같은 느슨한 판정을 사용한다(`locator_sr.c:8041-8055`).
- develop 비교: PK 고정 시에는 PK가 부분/online UK로 대체되지 않았으므로 feature에서 노출.
- PR 이력: #6798의 PK 제거 및 #7370 통합 범위. 현재 TODO도 master가 RK identity를 전달하는 후속 설계를 언급한다(`object_representation_sr.c:4692`).
- 재현/불변식: PK 없는 ON 테이블에 all-NN filtered UNIQUE를 만들거나 ONLINE build 중 DML을 수행한다. RK는 모든 row를 즉시 조회 가능한 완성 인덱스여야 한다.
- 수정/테스트: predicate/function index와 building/invisible 상태의 자격 정책을 정하고, 최소한 partial/building 후보를 제외한다. predicate 밖 행과 build 전환 중 DML을 시험한다.

## PM3-06 — failover 승격 시 RK readiness를 다시 확인하지 않는다

- 심각도/신뢰도: **High / Medium**
- 영향: 시작 이후 DDL 우회나 catalog 차이가 생기면 불완전한 standby가 primary로 승격될 수 있다.
- feature 근거/실행 경로: `cubrid heartbeat start`는 server 시작 후 `us_hb_process_rkcheck()`를 호출하고 copy/apply를 시작한다(`src/executables/util_service.c:3954-3978`). 그러나 failover/promotion을 담당하는 heartbeat/connection/boot 호출 그래프에는 `rkcheck` 또는 `check_ha_repl_constraint` 참조가 없다. 정적 참조는 수동 명령과 최초 start에만 있다(`util_service.c:5026-5043`).
- develop 비교: RK readiness라는 새 gate가 feature에서 start에만 추가되어 promotion 누락도 feature 신규.
- PR 이력: #6658의 HA 시작 검사와 #6934 multi db-host 보완 후에도 승격 경로는 연결되지 않았다.
- 재현/불변식: 시작 후 PM3-03/04 경로로 standby schema를 RK 부적합 상태로 만든 뒤 failover. 승격 전 replication-enabled class 전체가 적용 가능한 RK를 가져야 한다.
- 수정/테스트: promotion 직전 로컬 catalog 검사를 수행하고 실패 시 승격을 차단한다. start/switchover/failover/failback별 시험을 추가한다.

## PM3-07 — `REPLICATION`을 새 예약 토큰으로 만들어 기존 SQL 호환성을 깬다

- 심각도/신뢰도: **Medium / High**
- 영향: 기존 고객의 컬럼·별칭·변수명이 업그레이드 후 parse error가 될 수 있다.
- feature 근거/실행 경로: lexer가 모든 문맥의 `replication`을 전용 `REPLICATION` token으로 반환한다(`src/parser/csql_lexer.l:916-918`); grammar는 table option에서 이를 소비한다(`src/parser/csql_grammar.y:19891-19996`). identifier fallback/비예약 keyword 처리가 함께 추가되지 않았다.
- develop 비교: develop lexer에는 이 token rule이 없어 feature 신규 회귀.
- PR 이력: #6394의 CREATE TABLE option 도입, #7370 통합 후 현재 HEAD 상태다.
- 재현/불변식: develop에서 `CREATE TABLE t(replication INT)` 및 `SELECT 1 AS replication`을 실행하고 feature와 비교한다. 새 옵션은 기존 unquoted identifier를 불필요하게 깨지 않아야 한다.
- 수정/테스트: 문맥 키워드/비예약 키워드로 처리하거나 identifier 허용 production에 추가하고 DDL/DML 호환 회귀를 만든다.

## PM3-08 — 사용자가 어떤 constraint가 실제 RK인지 조회할 수 없다

- 심각도/신뢰도: **Medium / High**
- 영향: 여러 PK/UK 후보가 있는 테이블에서 배포 전후 key 전환과 장애 원인을 판단할 수 없다.
- feature 근거/실행 경로: 선택은 class representation의 첫 후보다(`src/storage/btree.c:8285-8298`), source DML도 순회 첫 후보에서 `replicated=true`로 끝난다(`src/transaction/locator_sr.c:8041-8055`). SHOW CREATE와 `db_class`는 ON/OFF만 출력한다(`src/object/object_printer.cpp:1137-1145`, `src/object/schema_system_catalog_install_query_spec.cpp:68-75`).
- develop 비교: RK 선택 자체와 metadata gap 모두 feature 신규.
- PR 이력: #7370 통합 코드의 TODO(`object_representation_sr.c:4692`)가 index-dependent 선택을 후속 과제로 남긴다.
- 재현/불변식: 두 개의 all-NN UK가 있는 테이블에서 index 생성/재구축 전후 SHOW CREATE와 catalog를 조회해도 활성 RK를 식별할 수 없다.
- 수정/테스트: 선택된 논리 constraint identity를 catalog에 저장·노출하고 source/apply가 그 identity를 공유하도록 한다. 복수 후보/PK 추가/rebuild 시험을 추가한다.

## PM3-09 — HA 시작 사전검사가 결과 파일 생성 실패를 오류로 처리하지 못한다

- 심각도/신뢰도: **High / High**
- 영향: 로그 디렉터리 권한·용량 문제 하나가 명확한 운영 오류가 아니라 `rkcheck` crash 또는 비정상 종료로 나타나 HA 시작을 방해한다.
- feature 근거/실행 경로: heartbeat start는 `us_hb_process_rkcheck()`를 copy/apply 시작 전에 실행한다(`src/executables/util_service.c:3954-3978`). `open_violation_list_file()`은 `fopen()` 결과를 그대로 반환하지만(`src/executables/util_cs.c:2855-2864`), caller는 NULL 검증 없이 `PRINT_SECTION_TITLE(fp,...)`를 호출한다(`3320-3333`; 이후 3375-3388도 동일 fp 사용).
- develop 비교: `rkcheck` utility와 heartbeat 연결이 baseline에 없으므로 feature 신규.
- PR 이력: #6658에서 start gate를 추가했고 #6934에서 multi-host를 보완했지만, #7370 inline review의 NULL stream 지적은 최신 HEAD에도 남아 있다.
- 재현/불변식: HA log directory를 read-only로 만들거나 ENOSPC를 주고 `cubrid heartbeat start`/`heartbeat rkcheck` 실행. readiness utility는 파일 생성 실패를 안정적인 오류 코드로 반환해야 한다.
- 수정/테스트: `fp == NULL`이면 errno를 포함한 전용 오류를 설정하고 DB shutdown cleanup으로 이동한다. EACCES/ENOSPC/EMFILE fault test와 heartbeat start 실패 출력을 검증한다.

## PM3-10 — FK 위반 진단이 PK metadata 부재 시 프로세스를 종료시킬 수 있다

- 심각도/신뢰도: **Medium / Medium**
- 영향: 가장 필요한 부적합 catalog 진단 상황에서 원인 목록 대신 utility crash가 발생할 수 있다.
- feature 근거/실행 경로: `rkcheck`의 FK 검사(`src/executables/util_cs.c:2910-2914,3346-3353`)는 `log_ha_repl_fk_ref_all_replicated()`로 들어간다. OFF referenced class를 만나면 `db_constraint_find_primary_key()` 결과를 검사하지 않고 `pk_c->name`을 출력한다(`src/query/execute_schema.c:9833-9840`). legacy/partition promotion/손상 catalog에서 FK metadata는 남고 PK cache가 없으면 NULL 역참조다.
- develop 비교: 이 FK replication 진단 경로는 feature 신규.
- PR 이력: #6505의 CREATE FK 검사와 #6658의 rkcheck 결합에서 생겼고 #7370 inline review에서도 지적됐으나 미해결이다.
- 재현/불변식: referenced OFF class의 PK constraint cache가 없는 legacy/손상 catalog fixture로 `rkcheck --check-fk` 실행. 진단기는 부적합 metadata를 만나도 crash하지 않아야 한다.
- 수정/테스트: `pk_c` NULL을 별도 `<missing primary key>` 진단/오류로 처리하고 class/constraint name도 NULL-safe 출력한다. 정상 FK, OFF target, missing-PK fixture를 시험한다.
