# PM 1년차 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 범위와 방법

- 공식 최신 비교: `upstream/develop` (`5b9c0d815`) → `/home/youngjun/Workspace/claude` HEAD (`9e094324b`, #7697 포함)
- clangd 20.1.8로 feature compile DB의 SA_MODE C++17 정의·참조를 탐색하고 source caller/callee와 대조했다.
- 유효 finding은 10건이다. 최대 50건을 채우기 위한 중복 분할은 하지 않았으며, **더 이상 근거 있는 독립 문제를 찾지 못함**.

## PM1-01 복합 UNIQUE의 일부 컬럼만 NOT NULL이어도 HA 생성 검사를 통과한다

- 심각도/신뢰도: **Critical / High**
- 영향: HA 전환 후 데이터 누락·복제 중단 위험을 정상 스키마로 승인한다.
- feature 근거: `src/object/class_object.c:95-98`의 `IS_HA_REPLICATION_KEY_CONSTRAINT` → `src/object/schema_manager.c:16115-16129`의 `sm_has_non_null_attribute`는 하나만 NOT NULL이면 참이다. 반면 서버는 `src/base/object_representation_sr.c:4712-4719`에서 모든 컬럼을 요구한다. CREATE 경로는 `src/query/execute_schema.c:10267-10273`, DML 로그 경로는 `src/transaction/locator_sr.c:8041-8049,8421-8426`이다.
- develop 비교: develop은 PK만 복제키로 사용했다. UNIQUE RK를 추가하면서 새로 생긴 client/server 판정 불일치다.
- PR 이력: 통합 #7370 및 RK 검증 후속 #6477/#6739 맥락과 관련되나 현재 HEAD에 불일치가 남아 있다.
- 재현/불변식: `UNIQUE(a,b), a NOT NULL, b NULL 허용`인 `REPLICATION=ON` 테이블이 HA DDL 검사를 통과해도 서버는 RK를 찾지 못한다. “승인된 replicated class는 모든 DML에서 RK 로그를 생성한다”가 깨진다.
- 수정/테스트: 공용 `all key attributes NOT NULL` 판정으로 통합하고 CREATE/INSERT/UPDATE/DELETE 및 rkcheck를 같은 fixture로 검증한다.

## PM1-02 RK의 정체성이 저장되지 않아 노드별로 다른 UNIQUE를 선택할 수 있다

- 심각도/신뢰도: **Critical / High**
- 영향: 동일 스키마처럼 보여도 master가 기록한 key와 replica가 검색하는 key가 달라질 수 있다.
- feature 근거: source는 인덱스 배열의 첫 후보에서 로그를 남긴다(`src/transaction/locator_sr.c:8039-8049,8418-8426`). replica는 자신의 class representation 첫 후보를 다시 고른다(`src/storage/btree.c:8285-8298` → `src/transaction/locator_sr.c:6848-6856`). `src/base/object_representation_sr.c:4692` TODO도 master의 RK 이름 전달 필요를 명시한다.
- develop 비교: develop은 의미상 단일 PK를 사용했다. 여러 UNIQUE 후보를 허용하면서 신규 발생했다.
- PR 이력: #7370 통합 후에도 TODO(EPIC CBRD-26096)로 남은 설계 부채다.
- 재현/불변식: 두 노드에 동치 스키마를 서로 다른 constraint 생성 순서로 구성하고 UNIQUE 두 개의 값이 서로 교차하도록 DML한다. 로그 key와 apply 검색 BTID가 달라질 수 있다.
- 수정/테스트: catalog/log에 canonical RK constraint id/name과 key domain을 저장·전송하고 schema order가 다른 두 노드 테스트를 추가한다.

## PM1-03 filtered/function UNIQUE가 RK로 승인되어 일부 행의 로그가 사라질 수 있다

- 심각도/신뢰도: **High / High**
- 영향: 지원한다고 노출된 SQL 조합에서 선택적으로 데이터가 복제되지 않는다.
- feature 근거: client 후보식은 filter/function 정보를 보지 않는다(`src/object/class_object.c:95-98`). 서버 후보식도 type/NOT NULL만 본다(`src/base/object_representation_sr.c:4702-4721`). INSERT/DELETE는 filter가 거짓이면 후보 index를 `continue`한다(`src/transaction/locator_sr.c:7863-7876`)고, 로그 삽입은 그 뒤 `8041-8049`에 있다.
- develop 비교: PK 전용일 때는 이 경로가 RK가 아니었다. UNIQUE RK 확장으로 신규 노출됐다.
- PR 이력: #7370 기능 범위와 관련되며, 현재 코드에는 제외 조건이 없다.
- 재현/불변식: `UNIQUE(a) WHERE flag=1`, `a NOT NULL`인 ON 테이블에 `flag=0` 행을 삽입한다. “replication ON의 모든 row 변화는 하나의 로그를 갖는다”가 깨진다.
- 수정/테스트: filtered/function/reverse/online-building index를 RK 후보에서 제외하거나 전 행 식별 가능성을 별도 증명·저장한다.

## PM1-04 다중 ALTER는 첫 절만 보고 RK 재검사 여부를 정한다

- 심각도/신뢰도: **High / High**
- 영향: 지원되는 multi-clause DDL로 HA 필수 제약을 우회할 수 있다.
- feature 근거: loop의 현재 code는 `crt_clause->info.alter.code`로 얻지만(`src/query/execute_schema.c:1851-1855`), gate는 `alter->info.alter.code`를 사용한다(`2051-2054`). 검사 대상 macro도 CHANGE/RENAME을 누락한다(`109-114`). 최종 검사는 gate가 참일 때만 실행된다(`2059-2072`).
- develop 비교: RK 강제 검사가 없던 develop에는 같은 신규 불변식이 없었다.
- PR 이력: multi ALTER PK 보완 #6637과 RK 제거 보완 #6618/#6739 이후에도 현재 절 사용 오류가 남아 있다.
- 재현/불변식: 첫 절을 비관련 변경, 뒤 절을 RK 제거/nullable 변경으로 구성한다. 최종 ON 테이블에 RK가 없어도 commit될 수 있다.
- 수정/테스트: `alter_code`를 사용하고 RK 자격을 바꿀 수 있는 모든 ALTER code를 포함한다. 순서를 뒤집은 조합 테스트가 필요하다.

## PM1-05 rkcheck 실패 시 먼저 시작한 서버를 되돌리지 않는다

- 심각도/신뢰도: **High / High**
- 영향: `cubrid heartbeat start` 실패 표시 뒤 서버만 살아 있는 부분 시작 상태가 남는다.
- feature 근거: 서버 시작이 먼저다(`src/executables/util_service.c:3963-3967`), rkcheck 실패는 즉시 `ret`로 간다(`3969-3973`). 정리부는 PID 배열만 파괴하고 서버 stop/rollback이 없다(`4001-4008`).
- develop 비교: rkcheck가 feature에서 시작 절차 중간에 추가되면서 새 partial-failure 상태가 생겼다.
- PR 이력: HA 시작 검증 #6658 및 multi-host #6934와 직접 관련된다.
- 재현/불변식: RK 위반 DB로 HA start 후 실패 코드를 확인하고 cub_server 생존 여부를 확인한다.
- 수정/테스트: check를 server start 전 가능한 모드로 수행하거나 실패 시 이번 호출이 시작한 서버를 종료한다. 다중 DB 중간 실패 rollback도 시험한다.

## PM1-06 자동 failover 승격 경로에는 rkcheck가 없다

- 심각도/신뢰도: **High / Medium**
- 영향: 시작 검사를 우회해 생긴 invalid schema가 standby 승격 시 write 가능한 상태가 될 수 있다.
- feature 근거: rkcheck 호출은 utility start/명시 명령에만 있다(`src/executables/util_service.c:3194-3249,3969,5041-5043`). 실제 ACTIVE 전환은 `src/connection/server_support.c:1852-1928`, heartbeat 요청은 `src/executables/master_heartbeat.c:4396-4485`이며 RK 검증 호출이 없다.
- develop 비교: develop에는 RK 승격 전제 자체가 없었다. feature의 필수 RK 정책을 모든 상태 전이에 적용하지 못한 신규 공백이다.
- PR 이력: #6658은 시작 시 검사 맥락이나 승격 경로는 현재 HEAD에서 연결되지 않는다.
- 재현/불변식: PM1-04로 invalid ON schema를 만든 뒤 standby를 ACTIVE로 승격한다. write enable 전 차단되지 않는다.
- 수정/테스트: ACTIVE 전이 전에 server-side RK/FK 검증을 수행하고 실패 시 상태 전이를 거부한다.

## PM1-07 mixed-target SBR은 REPLICATION=OFF 테이블까지 replay한다

- 심각도/신뢰도: **High / Medium**
- 영향: 부분 복제를 선택한 고객의 제외 테이블 데이터가 replica에서 변경된다.
- feature 근거: multi UPDATE/DELETE에서 대상 중 하나라도 ON이면 true다(`src/query/execute_statement.c:3320-3343`). 그러면 전체 SQL text를 SBR로 처리하고 RBR을 억제한다(`3404-3419,4112-4125`; `16502-16517`). 문장은 ON/OFF 대상을 분리하지 않는다.
- develop 비교: feature가 class별 replication flag와 SBR gate를 함께 추가해 새 의미 충돌을 만들었다.
- PR 이력: class DML #6467, SBR 보완 #6908 후 현재 ANY 정책이 남아 있다.
- 재현/불변식: 한 multi-table UPDATE가 ON 테이블과 OFF 테이블을 모두 수정하게 한다. replica에서 OFF 테이블까지 SQL이 실행되는지 확인한다.
- 수정/테스트: mixed target SBR을 거부하거나 대상별 RBR/SBR로 분리한다. trigger/derived-vclass 조합도 검증한다.

## PM1-08 OFF 테이블 TRUNCATE도 RK 존재만으로 복제된다

- 심각도/신뢰도: **Medium / High**
- 영향: OFF 테이블의 독립 데이터를 replica에서 예기치 않게 삭제할 수 있다.
- feature 근거: `truncate_need_repl_log`는 class flag가 아니라 RK 존재만 확인한다(`src/query/execute_statement.c:361-383`). PT_TRUNCATE는 이 결과가 참이면 전체 statement log를 만든다(`16673-16682`).
- develop 비교: develop은 PK 존재를 보았고 class별 OFF 의미가 없었다. feature가 OFF를 추가하면서 flag 검사를 추가하지 않은 악화다.
- PR 이력: TRUNCATE 수정 #6826 및 SBR 수정 #6908 이후 현재 HEAD에도 남아 있다.
- 재현/불변식: HA disabled 상태에서 `REPLICATION=OFF` + PK 테이블을 준비한 뒤 HA 기동 및 TRUNCATE를 수행한다.
- 수정/테스트: `sm_is_replication_class`를 먼저 확인하고 ON/OFF 각각의 TRUNCATE replay 테스트를 추가한다.

## PM1-09 rkcheck 결과 파일 생성 실패가 NULL stream 사용으로 이어진다

- 심각도/신뢰도: **High / High**
- 영향: 권한 부족·디스크 full 같은 운영 실패가 정상 오류가 아니라 HA 사전검사의 비정상 종료가 된다.
- feature 근거: `open_violation_list_file`은 `fopen` 결과를 그대로 반환한다(`src/executables/util_cs.c:2856-2864`). `rkcheck`는 `fp`를 검사하지 않고 출력 macro와 검사 callback에 넘긴다(`3320-3334,3346-3349`).
- develop 비교: baseline에는 rkcheck와 출력 경로가 없어 feature 신규다.
- PR 이력: #6658/#6934의 시작 검사 경로이며 #7370 inline review에서 지적됐지만 최신 HEAD에 남아 있다.
- 재현/불변식: log directory를 EACCES 또는 ENOSPC로 만들고 rkcheck/HA start. 파일 실패는 명시적 error code로 종료돼야 한다.
- 수정/테스트: `fp == NULL` 즉시 errno 기반 오류를 설정하고 EACCES/ENOSPC fault test를 추가한다.

## PM1-10 FK 위반 보고가 PK lookup 결과를 무조건 역참조한다

- 심각도/신뢰도: **High / Medium**
- 영향: HA 시작을 차단해야 할 진단 경로 자체가 metadata 예외에서 crash할 수 있다.
- feature 근거: replication OFF referenced class에서 `db_constraint_find_primary_key` 결과 검증 없이 `pk_c->name`을 출력한다(`src/query/execute_schema.c:9833-9840`). rkcheck callback은 `src/executables/util_cs.c:2910-2914`다.
- develop 비교: HA FK 검사·진단이 feature에서 추가돼 신규다.
- PR 이력: #6505/#6658/#7370 관련이며 #7370 inline review에서 NULL 역참조가 지적됐다.
- 재현/불변식: restore/legacy catalog에서 referenced class PK lookup이 실패하는 FK violation을 검사한다. 검사는 crash 없이 class/constraint를 보고해야 한다.
- 수정/테스트: `pk_c`와 name을 NULL-safe 처리하고 malformed catalog fixture로 rkcheck를 시험한다.

## 제외 메모

오류 메시지 문구, 문서 정책, 백업 제품 정책은 코드 실행 결함으로 세지 않았지만 후보 보존표에 판정 상태를 남겼다. #7697에서 해결된 interrupt/error propagation과 per-index lookup 성능 후보는 `후속 PR 해결` 상태로 보존했다. 위 10건은 통합 시 다른 페르소나 보고서와 root cause 기준으로 병합한다.
