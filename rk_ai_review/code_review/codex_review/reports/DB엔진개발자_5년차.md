# DB 엔진 개발자 5년차 코드 리뷰 — CBRD-26246

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

## 분석 결과

공식 `/home/youngjun/Workspace/claude`에서 `git diff upstream/develop...HEAD` (`5b9c0d815...9e094324b`), PR_HISTORY, compile DB와 clangd, source caller-callee를 함께 확인했다. **유효 finding 10건**이다. 동일 root cause와 develop 동일 결함을 제거했으며 **더 이상 근거 있는 독립 문제를 찾지 못함**.

## ENG5-00 rkcheck가 NULL `FILE *`를 출력 macro에 전달한다

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거: `open_violation_list_file` `src/executables/util_cs.c:2855-2864`는 `fopen` 결과를 그대로 반환한다. `rkcheck` `src/executables/util_cs.c:3320`은 NULL 여부를 확인하지 않고 `3332-3343`에서 출력 macro에 전달한다.
- 실행 경로: HA start → `proc_execute(cub_admin rkcheck)` → open failure → `fprintf(NULL,...)` 계열의 undefined behavior, 정상 cleanup과 violation error 설정 전에 이탈.
- develop 비교/PR: rkcheck는 feature/#6658 신규. #7370 inline review에 이미 포착됐지만 latest HEAD에 남았다.
- 재현/불변식: `fopen` EACCES/ENOSPC/EMFILE fault. utility error paths는 유효 stream 여부와 무관하게 정의되어야 한다.
- 수정·테스트: NULL 즉시 검사, `er_set`/errno 보존 후 공통 cleanup, 세 fault와 RK/FK flag 조합 unit/integration test.

## ENG5-01 client와 server의 복합 RK predicate가 다르다

- 심각도/신뢰도/관점: Critical / High / DB 엔진 개발자
- feature 근거: `src/object/class_object.c:95-98` → `sm_has_non_null_attribute`(`src/object/schema_manager.c:16115-16129`)는 any; `or_is_replication_candidate_key`(`src/base/object_representation_sr.c:4707-4721`)는 all.
- 실행 경로: DDL/rkcheck는 `classobj_has_class_repl_key_constraint`; insert/delete/update log path는 `or_is_replication_candidate_key`.
- develop 비교/PR: 두 predicate 모두 RK feature 신규. #6477/`88d6cc300` 이후에도 composite mismatch 잔존.
- 재현/불변식: 2-column UK에서 하나만 NN. 모든 layer의 `is_candidate(schema,index)` 결과는 같아야 한다.
- 수정·테스트: canonical predicate를 공유하거나 client/server별 동등성 unit test를 exhaustive하게 둔다.

## ENG5-02 do_alter가 loop 변수 대신 head node를 검사한다

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거/경로: `src/query/execute_schema.c:1843-2057` loop에서 `alter_code`를 만들지만 `2051`은 `alter->info.alter.code` 사용. 뒤 절만 RK-related이면 후검사 생략.
- develop 비교/PR: #6637 리팩터링 신규.
- 재현/불변식: first unrelated + second DROP RK. postcondition validator는 실행된 절 집합의 함수여야 한다.
- 수정·테스트: `alter_code` 사용과 branch coverage.

## ENG5-03 RK eligibility를 바꾸는 ALTER code 집합이 불완전하다

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거/경로: macro `src/query/execute_schema.c:109-114`는 ADD/DROP attr, DROP constraint/PK만 포함. `PT_CHANGE_ATTR`, `PT_MODIFY_ATTR_MTHD` 처리(`1874-1947,2013-2016`)는 NN을 제거할 수 있다.
- develop 비교/PR: #6618/#6739 신규 검증 공백.
- 재현/불변식: only RK UK의 NN 제거. replicated class postcondition은 every successful DDL 뒤 유지돼야 한다.
- 수정·테스트: 변경 유형 allowlist 대신 final schema에 무조건 validator 적용 또는 정확한 mutation predicate.

## ENG5-04 RK identity가 constraint가 아니라 class representation 배열 순서다

- 심각도/신뢰도/관점: Critical / High / DB 엔진 개발자
- feature 근거/경로: `btree_get_rkey_btid` `src/storage/btree.c:8285-8298`과 insert/delete index loop `src/transaction/locator_sr.c:8039-8055`가 first match로 결정한다. `src/base/object_representation_sr.c:4692` TODO가 이를 명시한다. 가정된 UPDATE helper 수정은 후보 선택 로직과 독립이다.
- develop 비교/PR: develop은 PK라는 단일 semantic identity. #6467/#7370 신규 악화.
- 재현/불변식: PK+UK 또는 UK 2개에서 repr/index 순서를 바꾸면 RK가 바뀐다. row identity는 physical ordering과 무관해야 한다.
- 수정·테스트: catalog에 selected constraint OID/name 저장, PK precedence만으로 땜질하지 말고 schema evolution test.

## ENG5-05 source와 applier가 RK를 독립 계산한다

- 심각도/신뢰도/관점: Critical / High / DB 엔진 개발자
- feature 근거/경로: source `locator_add_or_remove_index_internal`/`locator_update_index`가 local candidate key를 log에 넣고, applier force 준비 `src/transaction/locator_sr.c:6846-6858`가 `btree_get_rkey_btid`로 target local candidate를 재선택한다.
- develop 비교/PR: develop PK 고정 대비 feature 신규.
- 재현/불변식: 양 노드에 후보가 있지만 순서/constraint가 다름. serialized row-key schema와 lookup index schema가 같아야 한다.
- 수정·테스트: replication record에 RK identifier/domain fingerprint 포함, mismatch면 apply 중단.

## ENG5-06 rkcheck FK diagnostic에서 `pk_c` NULL dereference

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거/경로: `src/query/execute_schema.c:9837-9839`가 `db_constraint_find_primary_key` 결과를 검사하지 않는다. 정상 FK 생성은 referenced PK를 강제하지만 restore·legacy·손상 catalog를 검사하는 diagnostic path에서는 lookup 실패가 crash로 이어질 수 있다.
- develop 비교/PR: #6658 신규 함수.
- 재현/불변식: FK OID는 남았지만 referenced PK cache가 없는 fixture에서 `rkcheck --check-fk`. diagnostic은 malformed metadata에서도 안전해야 한다.
- 수정·테스트: FK의 referenced constraint metadata를 출력; NULL/fetch failure fault test.

## ENG5-08 partition promote의 stateful boolean이 attribute별 결정을 오염시킨다

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거/경로: `src/query/execute_schema.c:7948` 조건의 `!has_notnull_unique` 때문에 첫 match 이후 모든 attribute가 else로 가서 UNIQUE flags를 제거한다. `7978`은 같은 boolean으로 property 전체 유지 여부를 결정한다.
- develop 비교/PR: #6552/#7370 변경 신규.
- 재현/불변식: two separate NN UK attrs. attribute cache와 property list는 constraint별 bijection을 유지해야 한다.
- 수정·테스트: local `is_current_attr_rk`와 global count를 분리하고 reload serialization test.

## ENG5-09 SBR dependency 분석이 OFF read source를 무시한다

- 심각도/신뢰도/관점: High / High / DB 엔진 개발자
- feature 근거/경로: `is_data_repl_log_enabled` `src/query/execute_statement.c:3315-3343`은 modify specs만 보고 source dependency를 검사하지 않는다. `do_statement:3405-3407`은 true면 RBR suppress 후 SBR을 남긴다.
- develop 비교/PR: #6908 commit body의 known limitation; OFF class 기능이 source state divergence를 의도적으로 만들므로 feature에서 악화.
- 재현/불변식: ON target + OFF source SBR. deterministic replay는 모든 read dependency가 replicated snapshot이어야 한다.
- 수정·테스트: source dependency walker로 OFF를 감지해 reject/RBR, trigger/subquery도 포함.

## ENG5-10 derived-vclass 탐색은 write provenance 없이 subtree의 아무 ON spec이나 채택한다

- 심각도/신뢰도/관점: Medium / Medium / DB 엔진 개발자
- feature 근거/경로: `pt_spec_repl_class_walk` `src/query/execute_statement.c:3239-3263`은 모든 nested PT_SPEC를 훑고 첫 ON class에 stop한다. `spec_has_replication_class:3294-3300`은 이를 수정 target 판정으로 사용한다.
- develop 비교/PR: #6908의 derived vclass 보강에서 신규.
- 재현/불변식: derived rewrite tree에서 ON join-only spec + OFF actual base target. SBR decision은 read presence가 아니라 write provenance에 따라야 한다.
- 수정·테스트: vclass update mapping/target flags를 보존해 실제 modified base만 평가하고 nested subquery false-positive test.

## LSP 및 검증 한계

공식 worktree의 compile DB와 clangd는 정의·참조 및 caller-callee 탐색에 사용했다. 결론은 source mode, `git diff`/`git blame`, PR_HISTORY로 재확정했다. 실행 가능한 HA cluster가 없어 런타임 재현은 회귀 테스트로 남긴다.
