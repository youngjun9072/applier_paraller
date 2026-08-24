# DB 엔진 개발자 3년차 관점 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 12개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 12개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

- 공식 대상: `/home/youngjun/Workspace/claude`, HEAD `9e094324b` vs `upstream/develop` `5b9c0d815`.
- 방법: compile DB 1,186 entries와 clangd 20.1.8로 정의/참조를 보조 탐색하고, client schema cache→server OR_INDEX→locator replication log→log-applier lookup, ALTER와 heartbeat 호출 그래프를 source로 검증했다. clangd `--check`는 대형 TU refactoring-tweak 오류/시간 제한이 있어 진단 자체는 finding 근거에서 제외했다.
- 결과: 채택 finding **12건**. 동일 root cause, 현재 HEAD에서 수정된 후보, develop 동일 결함은 삭제하지 않고 각각 `중복 병합`, `후속 PR 해결`, `develop 기존` 상태로 보존했다. **더 이상 근거 있는 문제를 찾지 못함**.
- 영향받는 페르소나 필드: 아래 12건 모두 `DB 엔진 개발자 3년차`다.
- 최신 필터: #7697의 interrupt/error propagation 수정과 per-index lookup 성능 후보는 `후속 PR 해결`로만 보존한다.

## ENG3-01 — client RK validator의 existential 조건이 server의 universal 조건과 다르다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `IS_HA_REPLICATION_KEY_CONSTRAINT`(`src/object/class_object.c:95-98`) → `sm_has_non_null_attribute`(`src/object/schema_manager.c:16115-16129`)는 `exists(NOT NULL)`. `or_is_replication_candidate_key`(`src/base/object_representation_sr.c:4712-4719`)는 `forall(NOT NULL)`. 전자는 CREATE/ALTER/rkcheck(`src/query/execute_schema.c:9861-9872`, `src/executables/util_cs.c:2898-2907`), 후자는 INSERT/DELETE/UPDATE log(`src/transaction/locator_sr.c:8041-8055,8425-8433`)를 지배한다.
- develop 비교/PR: feature 신규; #6798 UK RK 확장/#7370 통합에 잔존.
- 재현/불변식: mixed-nullability composite UK. 모든 계층의 `is_rk_candidate` 결과가 동일해야 한다.
- 수정·테스트: constraint 단위 all-NN helper 하나로 client/server representation을 생성하고 truth-table unit test + HA 종단 시험.

## ENG3-02 — client는 REVERSE_UNIQUE를 승인하고 server는 거부한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `SM_IS_CONSTRAINT_UNIQUE_FAMILY` 정의(`src/object/class_object.h:111-115`)는 reverse 포함. server는 `index->type != BTREE_UNIQUE`를 거부(`src/base/object_representation_sr.c:4707-4709`). `btree_get_rkey_btid`는 후보가 없는데도 null BTID와 NO_ERROR로 반환할 수 있다(`src/storage/btree.c:8274-8306`), apply lookup은 이를 사용한다(`src/transaction/locator_sr.c:6846-6858`).
- develop 비교/PR: feature 신규; #6798/#7370.
- 재현/불변식: reverse unique 단독 schema. readiness-success는 non-null valid BTID를 함의해야 한다.
- 수정·테스트: enum mapping을 공용화하고 “후보 없음”은 명시 오류로 반환; reverse type unit/integration test.

## ENG3-03 — multi ALTER gate가 loop variable 대신 head node를 검사한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: loop 변수와 cached code는 `crt_clause`/`alter_code`(`src/query/execute_schema.c:1851-1854`)인데 `2051`은 `alter->info.alter.code`를 검사한다. 후속 RK destructive clause가 `need_check_repl_constraint`를 set하지 못한다.
- develop 비교/PR: feature 신규 코드 결함; #6637 multi ALTER와 #6739 refactoring 뒤 현재 HEAD에 잔존.
- 재현/불변식: non-related head + DROP sole RK. transaction 종료 전 final representation은 RK invariant를 만족해야 한다.
- 수정·테스트: `IS_REPL_CONSTRAINT_RELATED_ALTER(alter_code)` 사용; 모든 head/tail 조합 및 rollback test.

## ENG3-04 — RK 자격을 바꾸는 ALTER code set이 불완전하다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: macro는 네 code뿐(`src/query/execute_schema.c:109-114`), dispatcher는 MODIFY/CHANGE/DROP_INDEX 등을 별도 처리(`1874-1879,2009-2020`). 특히 nullable 전환은 constraint object를 남기면서 server all-NN 자격만 제거한다.
- develop 비교/PR: feature 신규; #6618/#6739 제거 제약 coverage gap.
- 재현/불변식: MODIFY/CHANGE로 sole UK attr NN 제거, 또는 실제 unique constraint를 제거 가능한 DROP INDEX syntax를 대상별 확인. 어떤 DDL entry point도 ON class를 keyless로 commit하면 안 된다.
- 수정·테스트: alter-code allowlist 대신 변경 후 ON class를 일관되게 검증하거나 exhaustive enum test를 둔다.

## ENG3-05 — RK 후보 함수가 partial index를 배제하지 않는다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `OR_INDEX.filter_predicate`(`src/base/object_representation_sr.h:187`)가 있는데 `or_is_replication_candidate_key`는 확인하지 않는다(`src/base/object_representation_sr.c:4694-4721`). locator는 index iteration 중 이 후보에 한 번 로그를 쓰고 `replicated=true`로 종료(`src/transaction/locator_sr.c:8039-8055`), replica는 동일 BTID unique lookup(`6846-6858`).
- develop 비교/PR: PK-only develop에는 없는 feature 악화; #6798/#7370.
- 재현/불변식: filtered all-NN unique의 predicate 밖 row DELETE/UPDATE. RK index coverage는 heap row set과 같아야 한다.
- 수정·테스트: `filter_predicate == NULL` 강제; predicate true/false DML and apply test.

## ENG3-06 — RK 후보 함수가 online build 상태를 배제하지 않는다

- 심각도/신뢰도: **High / Medium**
- feature 근거/실행 경로: `OR_INDEX.index_status`와 `OR_ONLINE_INDEX_BUILDING_IN_PROGRESS`가 존재(`src/base/object_representation_sr.h:163-193`). 후보 함수는 status를 보지 않는다. locator는 building index를 별도 dispatcher로 갱신하면서도(`src/transaction/locator_sr.c:7962-7977`) 같은 index를 RK log 후보로 삼는다(`8041-8055`).
- develop 비교/PR: feature의 arbitrary UK RK로 신규/악화; #7370.
- 재현/불변식: PK 없는 ON table에서 online unique build와 concurrent DML/apply. 활성 RK는 publish 완료 전 선택되면 안 된다.
- 수정·테스트: `OR_NORMAL_INDEX`(정책에 따라 visible 포함)만 후보; build commit/abort와 concurrent DML fault test.

## ENG3-07 — source와 applier가 RK identity 없이 각각 첫 index를 선택한다

- 심각도/신뢰도: **High / Medium**
- feature 근거/실행 경로: source INSERT/DELETE와 UPDATE는 각 index array 첫 후보(`src/transaction/locator_sr.c:8041-8055,8425-8433`), applier는 자기 classrepr 첫 후보(`src/storage/btree.c:8285-8298`, caller `locator_sr.c:6846-6858`)를 사용한다. payload는 value만 전달하며 코드 TODO가 master RK name 방식 필요를 명시(`src/base/object_representation_sr.c:4692`).
- develop 비교/PR: develop은 PK identity가 schema상 단일해서 후보 모호성이 없었고 feature에서 악화. #6798/#7370.
- 재현/불변식: 복수 all-NN UK/PK add/rebuild 후 source와 replica representation order를 달리해 동일 DML 적용. log key domain과 lookup BTID는 같은 logical constraint여야 한다.
- 수정·테스트: stable constraint ID/name+domain을 log/catalog에 연결하거나 deterministic sticky selection; reorder/rebuild/DDL barrier tests.

## ENG3-08 — failover promotion caller graph에 RK validation이 연결되지 않았다

- 심각도/신뢰도: **High / Medium**
- feature 근거/실행 경로: 최초 start caller는 `us_hb_process_start` → `us_hb_process_rkcheck` → copy/apply(`src/executables/util_service.c:3954-3978`). rkcheck command 참조는 수동 service dispatcher에도 있지만(`5026-5043`), `master_heartbeat.c`와 promotion/boot 경로에는 호출이 없다.
- develop 비교/PR: feature 신규 readiness invariant의 partial wiring. #6658/#6934 이후 현재 HEAD 잔존.
- 재현/불변식: start 이후 invalid catalog를 만든 standby promotion. server state가 primary로 전환되기 전 RK/FK invariant를 재검증해야 한다.
- 수정·테스트: promotion state transition의 precondition으로 in-process/read-only validator 연결; failure rollback/fencing tests.

## ENG3-09 — partition promotion의 UNIQUE flag 보존이 첫 발견 attribute에만 의존한다

- 심각도/신뢰도: **Medium / Medium**
- feature 근거/실행 경로: RK 후속 코드 `has_notnull_unique_constraints()`는 attribute별 판정(`src/query/execute_schema.c:7836-7871`)을 하지만 `do_promote_partition()`은 함수 전체 bool `has_notnull_unique`를 사용한다(`7887,7943-7956`). 첫 qualifying attribute 이후 모든 뒤 attribute는 `else`로 가 UNIQUE/REVERSE_UNIQUE flag를 지운다. 그럼에도 하나라도 찾으면 property list의 UNIQUE 전체를 보존한다(`7976-7983`). attribute flags와 class constraint properties가 어긋날 수 있다.
- develop 비교/PR: 해당 helper/보존 분기가 feature commit에서 추가되어 신규. partition option 상속/승격 관련 #6552 및 #7370 맥락.
- 재현/불변식: 여러 독립 NOT NULL UNIQUE 또는 뒤쪽 composite UK를 가진 partition을 promote한 뒤 `db_get_constraints`, SHOW CREATE, RK candidate와 DML을 비교. attribute flags와 class properties는 같은 constraint set을 나타내야 한다.
- 수정·테스트: global bool과 per-attribute 보존 결정을 분리하고 보존할 constraint identity 집합으로 처리; unique 순서/복수/composite/reverse partition promotion tests.

## ENG3-10 — rkcheck가 fopen 실패 후 NULL FILE을 dereference 경로로 전달한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `open_violation_list_file()`은 `fopen(file_path,"w")`를 반환(`src/executables/util_cs.c:2855-2864`). `rkcheck()`는 line 3320에서 받은 `fp`를 검사하지 않고 `PRINT_SECTION_TITLE/PRINT_MESSAGE/PRINT_BLANK_LINE`에 반복 전달한다(`3330-3359,3375-3388`).
- develop 비교/PR: utility 전체가 feature 신규. #6658/#6934 후 #7370 inline comment `r3503435009`에서 확인됐지만 HEAD 잔존.
- 재현/불변식: EACCES/ENOSPC/EMFILE을 주입하고 rkcheck 실행. 모든 external resource acquisition은 사용 전에 성공 여부를 검사해야 한다.
- 수정·테스트: NULL이면 errno 보존 후 `ER_IO_*` 또는 utility error를 설정하고 단일 cleanup으로 이동; 세 errno와 db_restart 이후 cleanup 시험.

## ENG3-11 — FK violation logger가 nullable PK lookup 결과를 역참조한다

- 심각도/신뢰도: **Medium / Medium**
- feature 근거/실행 경로: OFF referenced class 분기에서 `db_constraint_find_primary_key(db_get_constraints(ref_class_mop))`가 반환한 `pk_c`를 NULL 검사 없이 `pk_c->name`으로 넘긴다(`src/query/execute_schema.c:9833-9840`). caller는 rkcheck callback이다(`src/executables/util_cs.c:2910-2914,3346-3353`).
- develop 비교/PR: HA FK diagnostic이 feature 신규. #6505/#6658 이후 #7370 inline comment `r3503434957`에도 남았다.
- 재현/불변식: FK OID metadata가 존재하지만 PK constraint cache가 없는 legacy/corrupt/partition-promotion fixture. verifier는 malformed metadata에서도 memory-safe해야 한다.
- 수정·테스트: ref class/constraint/fk_info와 `pk_c`를 모두 NULL-safe 검증하고 catalog inconsistency를 반환; corrupted cache fixture와 sanitizer test.

## ENG3-12 — storage 계층이 replication-off flag 값을 32로 중복 하드코딩한다

- 심각도/신뢰도: **Low / High**
- feature 근거/실행 경로: catalog 정의는 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`(`src/object/class_object.h:312`)지만 server record reader는 object header를 공유하지 않고 별도 local `int replication_off_flag = 32`를 사용한다(`src/base/object_representation_sr.c:781-791`). DML class 판정은 `heap_get_class_repl_on()` → 이 reader로 이어진다(`src/storage/heap_file.c:11085-11119`). 두 값이 바뀌면 compile-time 경고 없이 ON/OFF 의미가 반전될 수 있다.
- develop 비교/PR: flag와 reader 모두 feature 신규. #6467/#7370 구현이며 #7370 inline comment `r3503435143`에서 지적됐다.
- 재현/불변식: object flag enum 값을 임시 변경하는 mutation build에서 server reader 결과가 함께 바뀌지 않는다. serialized flag bit에는 단일 source of truth가 있어야 한다.
- 수정·테스트: base/object 양 계층이 공유 가능한 disk-format 상수로 이동하거나 static_assert로 동기화; ON/OFF record decode unit test.
