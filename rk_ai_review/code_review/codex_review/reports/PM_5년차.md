# PM 5년차 코드 리뷰 — CBRD-26246

> **2026-08-24 전수 재감사 알림:** 아래 9개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 9개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 검토 기준

- 대상: 공식 worktree `/home/youngjun/Workspace/claude`, `feature/CBRD-26246-develop` (`9e094324b`) vs `upstream/develop` (`5b9c0d815`)
- 방법: feature diff에서 진입점을 잡고 공식 compile DB와 clangd로 심볼을 확인한 뒤 caller-callee와 실제 소스를 대조했다.
- 결과: 유효 finding 9건. 최대 50건을 채우기 위한 중복·정책 선호를 제외했으며 **더 이상 근거 있는 독립 문제를 찾지 못함**.

## PM5-00 rkcheck 결과 파일 생성 실패가 HA 시작 프로세스를 비정상 종료시킬 수 있다

- 심각도/신뢰도/관점: High / High / PM(HA 기동 안정성)
- feature 근거: `src/executables/util_cs.c:2855-2864`의 `open_violation_list_file`은 `fopen` 실패를 그대로 NULL로 반환한다. `rkcheck`는 `src/executables/util_cs.c:3320`에서 NULL을 검사하지 않고 `3332-3343`의 `PRINT_*`/`fprintf` 계열에 전달한다.
- 실행 경로: `heartbeat start` → `us_hb_process_rkcheck` → `cub_admin rkcheck` → log directory read-only/ENOSPC/FD 고갈로 `fopen` 실패 → NULL stream 사용 → utility crash 또는 정의되지 않은 동작.
- develop 비교/PR: rkcheck와 결과 파일 경로는 feature/#6658 신규이며 upstream/develop에는 없다. #7370 inline review에서 지적됐지만 `9e094324b`에도 남아 있다.
- 재현/불변식: log directory 쓰기 권한을 제거하거나 `fopen` fault를 주입하고 HA start. 출력 실패는 명시적 오류여야 하며 process crash가 되어서는 안 된다.
- 수정·테스트: `fp == NULL`이면 errno를 포함한 utility error로 공통 정리 경로를 타고, EACCES/ENOSPC/EMFILE fault-injection 테스트를 추가한다.

## PM5-01 복합 UNIQUE의 일부 컬럼만 NOT NULL이어도 HA 생성 검사를 통과한다

- 심각도/신뢰도/관점: High / High / PM(데이터 정합성·릴리스 차단)
- feature 근거: `src/object/class_object.c:95-98`의 `IS_HA_REPLICATION_KEY_CONSTRAINT`는 `sm_has_non_null_attribute`를 호출하고, `src/object/schema_manager.c:16115-16129`는 하나라도 NOT NULL이면 true다. 반면 서버 DML 경로 `src/base/object_representation_sr.c:4707-4721`은 UNIQUE의 모든 컬럼이 NOT NULL이어야 후보로 본다.
- 실행 경로: `CREATE TABLE` → `do_create_entity` → `check_ha_repl_constraint` → client 판정 통과 → DML `locator_add_or_remove_index_internal` → `or_is_replication_candidate_key` 실패 → 복제 로그 없음.
- develop 비교/PR: develop에는 RK 허용 로직 자체가 없다. #6477과 그 후속 `88d6cc300`이 “같은 컬럼 집합” 문제를 고쳤지만 복합키 all 조건은 현재 HEAD에 남았다.
- 재현/불변식: `UNIQUE(a,b), a NOT NULL, b NULL`인 REPLICATION=ON 테이블을 HA에서 생성하고 INSERT. “허용된 복제 테이블의 모든 DML은 행 식별 로그를 가진다”가 깨진다.
- 수정·테스트: client 후보 판정을 `all attributes NOT NULL`로 통일하고 1/2/전부 NOT NULL인 복합 UK 행렬 테스트를 추가한다.

## PM5-02 멀티 ALTER의 RK 제거 여부를 첫 절만 보고 결정한다

- 심각도/신뢰도/관점: High / High / PM(온라인 스키마 변경 안전성)
- feature 근거: `src/query/execute_schema.c:2051-2054`는 loop의 `crt_clause->info.alter.code`가 아니라 최초 `alter->info.alter.code`를 반복 검사한다.
- 실행 경로: `do_alter`가 여러 절 실행 → 첫 절이 비관련이면 뒤의 `DROP CONSTRAINT`가 있어도 `need_check_repl_constraint=false` → 최종 RK 검사 생략.
- develop 비교/PR: feature 신규. #6618의 제거 방지와 #6637의 multi-ALTER 원자성 목적을 현재 구현이 일부 무력화한다.
- 재현/불변식: HA에서 `ALTER TABLE t RENAME ..., DROP CONSTRAINT rk`처럼 첫 절을 비관련 절로 둔다. 성공 후 REPLICATION=ON인데 RK가 없는 상태가 가능하다.
- 수정·테스트: `IS_REPL_CONSTRAINT_RELATED_ALTER(alter_code)`로 바꾸고 관련 절의 모든 순열을 테스트한다.

## PM5-03 CHANGE/MODIFY로 NOT NULL을 제거하면 RK 검사가 실행되지 않는다

- 심각도/신뢰도/관점: High / High / PM(호환성과 마이그레이션)
- feature 근거: `src/query/execute_schema.c:109-114`의 관련 ALTER 목록에 `PT_CHANGE_ATTR`, `PT_MODIFY_ATTR_MTHD`가 없다. 실제 실행 switch는 `src/query/execute_schema.c:1874-1947,2013-2016`에서 이들을 처리한다.
- 실행 경로: HA의 NN UNIQUE RK → `ALTER ... MODIFY/CHANGE ... NULL` → 스키마 변경 → `need_check_repl_constraint` 미설정 → RK 없는 복제 테이블.
- develop 비교/PR: feature 신규 검증 공백. #6618/#6739는 RK 제거 방지를 다뤘지만 현재 HEAD의 속성 변경 경로는 누락됐다.
- 재현/불변식: 단일 NN UNIQUE 컬럼의 NOT NULL을 제거한 뒤 INSERT한다. client/DDL은 성공하지만 서버는 그 UK를 RK로 쓰지 않는다.
- 수정·테스트: RK 적격성에 영향을 주는 ALTER 코드를 완전 열거하거나 변경 후 모든 replicated class를 무조건 검사한다.

## PM5-04 선택된 RK가 스키마에 고정되지 않아 노드마다 다른 키를 고를 수 있다

- 심각도/신뢰도/관점: Critical / High / PM(HA 정합성)
- feature 근거: master insert/delete는 `src/transaction/locator_sr.c:8039-8055`에서 첫 후보를 로그 키로 삼고, replica 조회는 `src/storage/btree.c:8285-8298`에서 로컬 class representation의 첫 후보 BTID를 고른다. `src/base/object_representation_sr.c:4692` TODO도 master의 RK 이름 전달 필요를 인정한다. UPDATE도 가정된 helper 수정과 무관하게 같은 first-candidate 구조다.
- 실행 경로: HA OFF에서 노드별 index 생성/삭제 이력 차이 → HA 시작의 `rkcheck`는 후보 존재만 확인 → master는 UK-A로 로그 → replica는 UK-B로 row lookup.
- develop 비교/PR: develop은 PK 하나를 고정 사용했다. #6467/#7370이 UK를 허용하면서 신규/악화됐다.
- 재현/불변식: 동일 데이터·서로 다른 후보 index 순서를 만든 두 노드를 HA로 시작해 update/delete를 수행한다. “로그 키와 apply lookup 키가 동일하다”가 깨진다.
- 수정·테스트: RK constraint ID/name을 catalog와 로그에 명시하고 start 시 노드 간 일치를 검증한다.

## PM5-05 HA 전환(promote)은 rkcheck의 보호를 받지 않는다

- 심각도/신뢰도/관점: High / High / PM(장애 전환 약속)
- feature 근거: `src/executables/util_service.c:3963-3973`의 명시적 HA process start에만 `us_hb_process_rkcheck`가 있다. heartbeat promotion 경로에는 호출이 없으며 `rg`상 유일 호출은 start와 수동 command다.
- 실행 경로: 기동 후 제약/메타데이터가 어긋난 replica → heartbeat가 active로 승격 → RK 검증 없이 쓰기 허용.
- develop 비교/PR: #6658에서 startup gate가 신규 추가됐지만 failover gate는 없다. develop에는 RK 규칙 자체가 없어 기능 신규 위험이다.
- 재현/불변식: standby의 RK를 불일치 상태로 만든 뒤 강제 failover한다. promotion 전에 검사 또는 fencing되어야 한다.
- 수정·테스트: promotion state machine에서 동일 validator를 호출하고 실패 시 승격을 차단하는 failover 테스트를 추가한다.

## PM5-06 rkcheck 실패 뒤 서버가 실행된 채 남을 수 있다

- 심각도/신뢰도/관점: Medium / High / PM(운영 경험·부분 기동)
- feature 근거: `src/executables/util_service.c:3963`에서 server를 먼저 시작하고 `3969-3973`에서 rkcheck 실패 시 `ret`으로 간다. `3999-4007` 정리에는 PID 배열 해제만 있고 server stop/rollback이 없다.
- 실행 경로: `cubrid heartbeat start` → server start 성공 → rkcheck 위반 → command 실패 반환, 이미 뜬 server 존속.
- develop 비교/PR: #6658이 start 사이에 gate를 넣으면서 생긴 신규 부분 성공 상태다.
- 재현/불변식: RK 없는 ON 테이블로 HA start 후 process 상태를 확인한다. “실패한 start는 시작 전 상태로 복구된다”가 깨진다.
- 수정·테스트: 검사 실패 시 시작한 server를 정지하거나 read-only validation 가능한 순서로 바꾸고 rollback 테스트를 추가한다.

## PM5-07 REPLICATION=OFF 테이블을 읽는 SBR은 replica에서 다른 결과를 낼 수 있다

- 심각도/신뢰도/관점: High / High / PM(기능 조합 호환성)
- feature 근거: `src/query/execute_statement.c:3315-3343`은 수정 대상만 ON인지 보고 SBR을 결정하며 INSERT...SELECT source와 join-only source의 replication 상태는 의도적으로 보지 않는다. #6908 통합 commit `3b6ebd1a9` 본문도 이 제한을 명시한다.
- 실행 경로: ON target을 OFF source로 `INSERT...SELECT`/join UPDATE + USE_SBR → master 결과를 statement로 기록 → OFF source가 비어 있거나 다른 replica에서 재실행 → 다른 rows 변경.
- develop 비교/PR: #6908의 target 판정 수정은 했지만 REPLICATION=OFF 도입으로 source 불일치가 새롭게 사용자 노출된다.
- 재현/불변식: OFF source에 master-only row를 넣고 ON target에 SBR INSERT SELECT. replica target이 master와 같아야 하나 달라진다.
- 수정·테스트: OFF source를 참조한 SBR을 거부하거나 snapshot 값을 RBR로 전달하고 INSERT/UPDATE/DELETE 조합을 테스트한다.

## PM5-08 partition promote가 여러 NN UNIQUE 속성의 메타데이터를 불일치시킨다

- 심각도/신뢰도/관점: High / High / PM(파티션 기능 회귀)
- feature 근거: `src/query/execute_schema.c:7943-7956`의 전역 `has_notnull_unique`가 첫 qualifying attribute 뒤 true가 되어 이후 qualifying attribute의 UNIQUE flags를 지운다. 그러나 하나라도 있으면 `7976-7983`에서 class UNIQUE properties 전체를 보존한다.
- 실행 경로: 여러 NN UNIQUE를 가진 partition promote → 첫 attribute만 flag 유지, property에는 여러 constraint 잔존 → schema/RK 판정과 server index 표현 불일치.
- develop 비교/PR: develop은 promote 시 unique를 모두 제거했다. #6552/#7370의 RK 보존 변경이 신규로 만든 불일치다.
- 재현/불변식: 두 NN UNIQUE 컬럼/제약이 있는 partition을 promote하고 `SHOW CREATE`, constraint cache, DML RK 선택을 비교한다.
- 수정·테스트: attribute별 보존 여부를 계산하고 property도 같은 constraint 단위로 필터링하는 다중 UK 테스트를 추가한다.

## 결론

출시 차단 우선순위는 PM5-04, PM5-01, PM5-02/03, PM5-07이다. 문서 선호나 미래 기능 요구는 finding으로 세지 않았다.
