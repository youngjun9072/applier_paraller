# DB 엔지니어 3년차 관점 코드 리뷰

> **2026-08-24 전수 재감사 알림:** 아래 10개 항목은 최초 탐색 원문이므로 삭제하지 않았다. 다만 일부 설명은 E2E 검증 뒤 정정됐다. CR-02는 master 무로그, CR-05는 입증 보류, CR-08·17은 오분석, CR-12는 develop 기존/feature 악화, CR-13은 선행 결함 의존이며 CR-16은 사용자 가정에 따라 제외한다. 현재 판정은 [187개 재감사 매핑](RAW_187_REAUDIT_MAP.md)과 [E2E 작업표](E2E_FINDING_WORKSHEETS.md)를 우선한다. 이 페르소나는 최대 50건까지 재탐색했으나 10개에서 근거 있는 관찰이 소진되어 **더 이상 발견되지 않음**으로 종료했다.

> 비채택 후보도 삭제하지 않으며, 상태와 판정 근거는 [후보 보존표](CANDIDATE_AUDIT.md#비채택-후보-보존표)에 기록한다.

- 공식 대상/방법: `/home/youngjun/Workspace/claude` HEAD `9e094324b` vs `upstream/develop` `5b9c0d815`; feature compile DB와 clangd, `do_alter`/`rkcheck`/heartbeat start/row apply caller-callee를 추적했다.
- 결과: 유효 finding **10건**. develop 동일 문제와 동일 root cause 중복을 제외한 뒤 **더 이상 근거 있는 문제를 찾지 못함**.
- 영향받는 페르소나 필드: 아래 10건 모두 `DB 엔지니어 3년차(DBA/HA 운영자)`다.
- 최신 필터: #7697이 해결한 interrupt/error propagation 및 per-index lookup 성능 후보는 `후속 PR 해결` 상태로만 보존한다.

## DBA3-01 — rkcheck가 승인한 복합 UK가 서버에서는 RK가 아니다

- 심각도/신뢰도: **High / High**
- 영향 페르소나: DBA/HA 운영자.
- feature 근거/실행 경로: `cubrid hb start` → `us_hb_process_rkcheck()`(`src/executables/util_service.c:3954-3978`) → `check_rk_constraint()`(`src/executables/util_cs.c:2898-2907`) → client macro(`src/object/class_object.c:95-98`) → `sm_has_non_null_attribute()`(`src/object/schema_manager.c:16115-16129`, any-NN). DML은 `or_is_replication_candidate_key()`(`src/base/object_representation_sr.c:4712-4719`, all-NN)를 사용한다.
- develop 비교/PR: feature 신규. #6658의 start 검사와 #6798의 UK RK 확장 결합에서 생겼고 #7370 HEAD에 잔존.
- 재현/불변식: `(a NOT NULL,b NULL,UNIQUE(a,b))`만 가진 ON table로 hb start가 성공한 뒤 DML이 복제되지 않는다. readiness와 runtime 후보 집합은 같아야 한다.
- 수정·테스트: 하나의 공용 “all key columns NN” 판정 사용; rkcheck→DML→apply 종단 시험.

## DBA3-02 — REVERSE UNIQUE 전용 테이블도 rkcheck만 통과한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: client unique family에는 reverse unique가 포함된다(`src/object/class_object.h:111-115`, `class_object.c:95-98`). server 후보는 `BTREE_UNIQUE`만 허용한다(`src/base/object_representation_sr.c:4702-4709`).
- develop 비교/PR: feature 신규; #6798/#7370의 후보 타입 정의 불일치.
- 재현/불변식: NOT NULL REVERSE UNIQUE만 가진 ON table로 rkcheck 및 DML. 승인된 테이블은 server에서 null BTID가 나오면 안 된다(`src/storage/btree.c:8274-8306`).
- 수정·테스트: 양 계층 후보 enum을 통일하고 reverse unique 단독 schema 회귀 시험.

## DBA3-03 — 복수 ALTER 후반의 RK 삭제가 readiness 검사를 우회한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `do_alter()`는 `crt_clause`를 순회(`src/query/execute_schema.c:1851-1854`)하지만 gate는 첫 `alter->info.alter.code`만 본다(`2051-2054`). 후속 DROP 이후 최종 검사(`2059-2069`)가 실행되지 않는다.
- develop 비교/PR: feature 신규; #6637 multi ALTER, #6739 제거 제약 이후 잔존.
- 재현/불변식: 비관련 첫 절 + 유일 RK DROP. ON class의 transaction commit 시 유효 RK가 반드시 남아야 한다.
- 수정·테스트: 현재 절의 `alter_code` 사용; 모든 절 순열과 rollback 확인.

## DBA3-04 — NULL 허용으로 바꾸는 ALTER가 RK 검사를 우회한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: gate macro(`src/query/execute_schema.c:109-114`)가 dispatcher의 MODIFY/CHANGE(`1874-1879,2018-2020`)를 포함하지 않는다. UK는 남아도 RK 자격은 사라진다.
- develop 비교/PR: feature 신규; #6618/#6739 범위 누락.
- 재현/불변식: `UNIQUE(a), a NOT NULL`의 NN을 제거하고 hb를 재시작하지 않은 채 운영. 모든 RK 자격 변경 DDL은 commit 전에 검사돼야 한다.
- 수정·테스트: MODIFY/CHANGE 및 NOT NULL add/drop을 gate에 포함; 단일/복합 ALTER 회귀.

## DBA3-05 — online-building/partial UNIQUE를 readiness와 DML이 활성 RK로 간주한다

- 심각도/신뢰도: **High / Medium**
- feature 근거/실행 경로: server representation은 predicate/function/status를 보유한다(`src/base/object_representation_sr.h:179-194`). 후보 판정은 이를 무시한다(`object_representation_sr.c:4694-4721`); first-match BTID가 apply lookup에 사용된다(`src/storage/btree.c:8285-8298`, `src/transaction/locator_sr.c:6846-6858`).
- develop 비교/PR: develop의 PK 고정 경로보다 feature에서 악화; #6798/#7370.
- 재현/불변식: partial unique의 predicate 밖 row 또는 online build 중 DML을 apply. RK는 모든 row를 안정적으로 찾아야 한다.
- 수정·테스트: partial/function/building/invisible 후보 제외 정책과 상태 전환 barrier 추가; fault/concurrent DML 시험.

## DBA3-06 — 최초 HA start 이후 promotion에는 rkcheck gate가 없다

- 심각도/신뢰도: **High / Medium**
- feature 근거/실행 경로: start는 server→rkcheck→copylogdb→applylogdb 순서다(`src/executables/util_service.c:3954-3978`). 정적 참조상 `master_heartbeat.c`, connection/boot promotion 경로에는 rkcheck 호출이 없고 수동 command만 있다(`util_service.c:5026-5043`).
- develop 비교/PR: #6658에서 새 start gate를 도입했으나 failover에 연결하지 않은 feature 신규 gap; #6934 뒤에도 잔존.
- 재현/불변식: start 후 RK가 사라진 standby를 failover. 승격 직전 readiness 검사가 성공해야 한다.
- 수정·테스트: promotion 전 local RK/FK 검사 및 실패 fencing; switchover/failover/failback 회귀.

## DBA3-07 — 첫 physical candidate 선택이라 운영자가 실제 RK 전환을 관측할 수 없다

- 심각도/신뢰도: **Medium / High**
- feature 근거/실행 경로: source와 apply는 각각 첫 후보를 순회 선택한다(`src/transaction/locator_sr.c:8041-8055,8425-8433`, `src/storage/btree.c:8285-8298`). log에는 constraint identity가 없고 코드 TODO도 master RK name 전달 필요를 기록한다(`src/base/object_representation_sr.c:4692`). SHOW/catalog는 ON/OFF만 노출한다(`src/object/object_printer.cpp:1137-1145`).
- develop 비교/PR: feature 신규; #7370 후속 EPIC으로 남음.
- 재현/불변식: 복수 UK 상태에서 PK add/rebuild 전후 master/replica의 class representation order가 다르면 같은 key를 조회한다는 보장이 없다.
- 수정·테스트: logical RK identity 영속/로그 전달/metadata 노출; DDL/rebuild/failover 조합 시험.

## DBA3-08 — apply 오류 로그에 UK 원문이 그대로 기록된다

- 심각도/신뢰도: **Medium / High**
- feature 근거/실행 경로: bulk flush 실패 시 key를 `db_sprint_value()`로 문자열화하고 error 및 reconnect 메시지에 넣는다(`src/transaction/log_applier.c:4791-4838`). feature는 PK 외 업무 UK(email/전화번호 등)를 RK로 확대한다.
- develop 비교/PR: 원래 PK도 출력했지만 feature가 PII 가능성이 큰 arbitrary UK로 노출 범위를 악화. #6798의 UK 확장과 관련, #7370 HEAD에 redaction 없음.
- 재현/불변식: email UK를 RK로 사용하고 replica apply 충돌을 유도한 뒤 applylogdb error log 검사. 기본 운영 로그에는 민감 key 원문이 없어야 한다.
- 수정·테스트: 기본 hash/redaction, opt-in 상세 로그; 문자열/복합/LOB 유사 key와 reconnect 경로 시험.

## DBA3-09 — rkcheck list 파일을 열지 못하면 NULL FILE을 사용한다

- 심각도/신뢰도: **High / High**
- feature 근거/실행 경로: `open_violation_list_file()`은 `fopen()`을 그대로 반환한다(`src/executables/util_cs.c:2855-2864`). `rkcheck()` caller는 `fp` NULL을 검사하지 않고 section/title/message를 출력한다(`3320-3343,3346-3359,3375-3388`). heartbeat start가 이를 선행 호출한다(`src/executables/util_service.c:3954-3978`).
- develop 비교/PR: baseline에 rkcheck가 없어 feature 신규. #6658/#6934 이후 #7370 review에서 확인됐고 현재도 미해결.
- 재현/불변식: log directory EACCES/ENOSPC/FD exhaustion 뒤 수동 rkcheck와 hb start. 운영 검사기는 환경 오류를 crash 없이 반환해야 한다.
- 수정·테스트: fopen 실패 즉시 errno 기반 오류 설정 및 cleanup; EACCES/ENOSPC/EMFILE와 다중 DB start 회귀.

## DBA3-10 — FK 위반 보고 중 referenced PK가 없으면 NULL을 역참조한다

- 심각도/신뢰도: **Medium / Medium**
- feature 근거/실행 경로: `check_fk_constraint()`(`src/executables/util_cs.c:2910-2914`) → `log_ha_repl_fk_ref_all_replicated()`. OFF target에서 PK lookup 후 NULL 검사 없이 `pk_c->name` 사용(`src/query/execute_schema.c:9833-9840`).
- develop 비교/PR: feature 신규 진단 경로. #6505/#6658, #7370 inline discussion에 해당하며 최신 HEAD 잔존.
- 재현/불변식: FK metadata는 있으나 referenced PK cache가 없는 legacy/손상 fixture에서 `rkcheck --check-fk`. 손상 진단이 추가 손상을 일으키면 안 된다.
- 수정·테스트: NULL-safe constraint 표기와 catalog inconsistency 오류; 정상/OFF/missing-PK 세 경로 시험.
