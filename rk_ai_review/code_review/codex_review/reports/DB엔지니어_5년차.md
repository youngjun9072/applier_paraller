# DB 엔지니어 5년차 코드 리뷰 — CBRD-26246

> **2026-08-24 전수 재감사 알림:** 아래 9개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 9개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 범위와 결과

공식 `/home/youngjun/Workspace/claude` HEAD `9e094324b`와 `upstream/develop` `5b9c0d815`를 함수 호출 경로로 비교했다. 공식 compile DB와 clangd로 정의·참조를 확인하고 source/mode를 재대조했다. **유효 finding 9건**이며, 중복을 제외한 뒤 **더 이상 근거 있는 문제를 찾지 못함**.

## DBA5-00 rkcheck list 파일 open 실패를 검사하지 않는다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/executables/util_cs.c:2855-2864`의 `fopen`은 실패 시 NULL이나, caller `3320`은 확인 없이 `3332-3343`의 출력 macro에 사용한다. `heartbeat start → us_hb_process_rkcheck → rkcheck`.
- develop 비교/PR: feature/#6658 신규. #7370 review discussion의 미해결 지적으로 최신 HEAD에도 동일하다.
- 재현/불변식: log directory를 read-only로 만들거나 FD 고갈/ENOSPC를 주입해 start. rkcheck는 crash가 아니라 비정상 종료 코드와 원인을 반환해야 한다.
- 수정·테스트: NULL 즉시 검사와 errno logging, DB shutdown을 포함한 공통 cleanup; EACCES/ENOSPC/EMFILE 및 multi-DB start 테스트.

## DBA5-01 startup rkcheck 실패가 이미 시작한 server를 되돌리지 않는다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/executables/util_service.c:3963-3973`에서 server start 후 rkcheck를 실행하고 실패 즉시 `ret`; `3999-4007`은 server를 멈추지 않는다. `heartbeat start → us_hb_server_start → us_hb_process_rkcheck → ret`.
- develop 비교/PR: #6658 신규 gate 도입으로 생긴 부분 기동 상태; develop에는 해당 중간 실패점이 없다.
- 재현/불변식: RK 위반 DB로 start 후 server/heartbeat process를 조회. 실패 command는 시작 전 상태를 보존해야 한다.
- 수정·테스트: 시작된 server rollback 또는 사전 standalone 검사; multi-DB 중 N번째 실패 rollback도 검증한다.

## DBA5-02 failover promotion에는 rkcheck가 없다

- 심각도/신뢰도/관점: Critical / High / DB 엔지니어
- 근거·경로: `src/executables/util_service.c:3194-3249` validator는 `3969`의 명시 start와 수동 rkcheck에만 연결된다. master heartbeat promotion/role change caller에는 연결되지 않는다.
- develop 비교/PR: #6658이 startup만 보호한 feature 신규 공백.
- 재현/불변식: 시작 후 standby schema를 부적격 상태로 만들고 primary 장애를 유도. 유효 RK 확인 전에는 active write를 열면 안 된다.
- 수정·테스트: promotion precondition으로 validator를 넣고 실패 시 fencing/상태 노출 테스트.

## DBA5-03 노드별 첫 후보 RK 선택으로 apply가 다른 index를 조회할 수 있다

- 심각도/신뢰도/관점: Critical / High / DB 엔지니어
- 근거·경로: source insert/delete `src/transaction/locator_sr.c:8039-8055`와 replica `src/transaction/locator_sr.c:6846-6858 → src/storage/btree.c:8285-8298`가 각각 로컬 첫 candidate를 계산한다. `src/base/object_representation_sr.c:4692`도 index-dependent 한계를 명시한다. UPDATE도 가정된 helper 수정과 무관하게 같은 후보 순서를 사용한다.
- develop 비교/PR: develop의 PK 고정에서 #6467/#7370 이후 신규 악화.
- 재현/불변식: 후보 UK 2개를 서로 다른 DDL 순서로 만든 두 노드를 시작하고 delete/update. source log key와 target lookup key는 같은 constraint여야 한다.
- 수정·테스트: 명시 RK ID를 복제하고 start 시 schema fingerprint 비교.

## DBA5-04 startup 검사는 RK의 존재만 보고 노드 간 동일성을 보지 않는다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/executables/util_cs.c:2897-2907`의 `check_rk_constraint`는 `classobj_has_class_repl_key_constraint` boolean만 센다. `src/executables/util_service.c:3226-3236`은 각 DB에서 이 결과만 사용한다.
- develop 비교/PR: #6658/#6934의 신규 검사 범위가 feature의 복수 후보 설계를 충분히 검증하지 못한다.
- 재현/불변식: 양 노드 모두 candidate 하나 이상이지만 이름/순서가 다르게 구성. rkcheck 성공 후 DML apply 실패.
- 수정·테스트: class별 선택 RK signature와 모든 참여 node의 equality를 검사한다.

## DBA5-05 rkcheck FK 위반 출력이 PK 없는 참조 테이블에서 NULL 역참조한다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/query/execute_schema.c:9833-9840`은 위반 대상의 `db_constraint_find_primary_key` 결과를 확인하지 않고 `pk_c->name`을 출력한다. 정상 FK 생성은 referenced PK를 강제하지만 restore·legacy·손상 catalog에서는 lookup 실패가 가능하다. `rkcheck → check_repl_constraint_violations → check_fk_constraint → log_ha_repl_fk_ref_all_replicated`.
- develop 비교/PR: 함수와 NN UNIQUE RK가 feature/#6658에서 신규.
- 재현/불변식: PK 없이 NN UNIQUE를 FK target으로 쓰는 REPLICATION=OFF class를 ON class가 참조한 상태로 rkcheck. 진단은 crash 없이 위반을 보고해야 한다.
- 수정·테스트: FK가 실제 참조하는 constraint name을 사용하고 NULL/error를 처리한다.

## DBA5-06 복합 UK 판정 차이로 rkcheck 성공 후 DML 로그가 빠진다

- 심각도/신뢰도/관점: Critical / High / DB 엔지니어
- 근거·경로: `src/object/class_object.c:95-98` + `src/object/schema_manager.c:16115-16129`는 any NOT NULL, `src/base/object_representation_sr.c:4707-4721`은 all NOT NULL. `rkcheck`는 전자를 사용하고 DML은 후자를 사용한다.
- develop 비교/PR: feature 신규; #6477 후속 수정에도 잔존.
- 재현/불변식: `UNIQUE(a,b)` 중 a만 NOT NULL로 구성해 rkcheck 후 insert/delete. 검사 성공은 실제 log 가능성을 보장해야 한다.
- 수정·테스트: 공통 predicate 구현과 client/server/utility 동일성 테스트.

## DBA5-07 SBR이 OFF source를 replica에서 다시 읽어 데이터가 달라진다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/query/execute_statement.c:3315-3343`은 target만 검사하고 OFF source는 무시한다. `do_statement:3405-3407`에서 SBR을 켜 row log를 suppress한다.
- develop 비교/PR: #6908 commit이 known limitation으로 남겼고, OFF 데이터가 replica에 없게 되는 feature와 결합해 신규 사용자 영향.
- 재현/불변식: OFF source master-only rows로 ON target에 USE_SBR INSERT SELECT/UPDATE join. master/replica rowset 일치 불변식 위반.
- 수정·테스트: OFF source 포함 시 RBR 또는 실행 거부; 세 DML별 테스트.

## DBA5-09 여러 NN UNIQUE가 있는 partition promote 후 catalog 표현이 갈라진다

- 심각도/신뢰도/관점: High / High / DB 엔지니어
- 근거·경로: `src/query/execute_schema.c:7943-7956`은 첫 qualifying attr 뒤 다른 attr의 UNIQUE flag를 제거하지만 `7976-7983`은 UNIQUE property 전체를 보존한다.
- develop 비교/PR: develop은 unique를 전부 제거; #6552/#7370 변경의 신규 회귀.
- 재현/불변식: NN UK 두 개의 partition promote 후 `SHOW CREATE`, db_class/constraint, rkcheck와 DML을 비교하면 동일 schema state를 보여야 한다.
- 수정·테스트: constraint별 filter 및 promote 후 catalog 재로드/재시작 테스트.
