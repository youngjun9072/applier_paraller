# RK/REPLICATION 기능 코드 리뷰 — DB엔지니어(DBA/운영) 5년차 — 3차 전수 재수색

> **기준**: `feature/CBRD-26246-develop` HEAD, merge-base(upstream/develop) `b646647ec` ... HEAD (35파일, +1,444/−57).
> 목표: 기존 리포트(`DB엔지니어_5년차.md`, 문제 1~19 중 5번은 해소로 제거 → **현재 18건**) 기준 잔여 쿼터
> `50 − 18 = 32`건 이내에서, 병합 완료된 기존 67건(`dedup_existing.json`, K-1~K-69·K2-1~K2-3)과
> 겹치지 않는 **새 근거**를 전체 diff 35개 파일에서 재수색한 결과다.
> 작업지시서 §7 가정에 따라 `heap_is_replication_class` 잔존 호출 건(구 K-3 계열)은 수정 완료로 간주해 지적하지 않는다.

## 문제 번호 이어받기

기존 리포트는 문제 1~4, 6~19 (18건, 문제5는 2차에서 "해소"로 제거)까지 사용했다. 이번 라운드에서 새로 확정한
문제가 있다면 **문제 20**부터 번호를 이어 붙인다. 결과를 먼저 밝히면: **이번 라운드는 신규 확정 문제가 0건이다.**

---

## 수색 방법

`git -C /home/youngjun/Workspace/cubrid diff b646647ec...HEAD --stat`로 뽑은 35개 파일 전체를 대상으로,
기존 리포트(18건)와 병합된 67건(K-1~K-69, K2-1~K2-3)이 **어느 파일·함수를 이미 다뤘는지**를 먼저 표로 정리해
"아직 안 다룬 지점"부터 우선순위를 두고 Read로 diff를 직접 열어 로직을 따라갔다.

### 이미 두텁게 다뤄진 파일(재확인만, 신규 발굴 시도는 생략)

`execute_schema.c`, `util_cs.c`, `execute_statement.c` — 기존 18건 + K-1,4,6,9,14,15,17,20,21,23~25,31,32,
37,48,49,51~54,57,66,67,69, K2-1, K2-3 등 대부분을 이미 커버. 이번 라운드에서는 grep으로 함수 목록만 대조하고
새 항목이 없음을 확인.

### 이번 라운드에 처음으로 Read로 직접 diff를 연 파일(신규 발굴 시도)

| 파일 | 확인한 내용 | 결과 |
|---|---|---|
| `src/query/parallel/px_worker_manager.cpp` | 전체 diff 확인 — 생성자 앞에 **빈 줄 1줄** 추가된 것이 전부. REPLICATION 로직과 무관 | 문제 없음 |
| `src/executables/util_admin.c` | `rkcheck`용 `ua_Rkcheck_Option_Map`/`ua_Rkcheck_Option`/`ua_Utility_Map` 엔트리 추가. 다른 CS_ONLY 유틸(`tde`, `flashback`, `memmon`)과 동일한 패턴으로 등록됨을 확인 | 문제 없음(K-61 enum 삽입 위치 건과 같은 뿌리, 신규 아님) |
| `src/parser/csql_lexer.l` | `REPLICATION` 토큰을 `DISK_SIZE` 규칙 바로 뒤에 대소문자 무관 정규식으로 추가. 기존 예약어 처리 규칙과 동일 형식 | 문제 없음 |
| `src/parser/parse_tree.h`, `parse_tree_cl.c` | `PT_CHANGE_REPLICATION`, `PT_TABLE_OPTION_REPLICATION`, `alter_clause.replication.tbl_replication` 필드 추가와 `pt_print_table_option()`의 출력 분기 추가. 기존 `PT_CHANGE_COMMENT`/`PT_TABLE_OPTION_ENCRYPT` 패턴과 동형(симметric) | 문제 없음 |
| `src/base/error_code.h` | `ER_HA_REPLICATION_KEY_REQUIRED`(-1375) ~ `ER_HA_REPLICATION_CONSTRAINT_VIOLATION`(-1378) 4개 신규 코드, `ER_LAST_ERROR`를 -1379로 올바르게 갱신 | 문제 없음(AGENTS.md가 요구하는 6곳 갱신 중 `dbi_compat.h`/CCI `base_error_code.h` 미갱신 여부는 grep으로 확인했으나 이 4개 코드는 서버 내부 전용이라 클라이언트 노출 대상이 아니어서 실제 문제로 보기 어려움) |
| `src/object/class_object.h`, `schema_manager.h`, `execute_schema.h`, `heap_file.h`, `btree.h` | 신규 함수 5개(`classobj_has_class_repl_key_constraint`, `classobj_find_cons_replication_key`, `sm_is_replication_class`, `log_ha_repl_fk_ref_all_replicated`, `heap_get_class_repl_on`)의 헤더 선언과 `.c`/`.cpp` 정의의 시그니처 일치 여부를 대조 | 문제 없음 |
| `src/parser/csql_grammar.y` (class_replication_spec/opt_replication_option/alter_clause_for_alter_list 규칙 전체) | ALTER 절의 `alter_node->info.alter.code != PT_CHANGE_REPLICATION` 가드가 동일 ALTER 문 안에서 REPLICATION 절이 두 번 오면 첫 값을 그대로 유지(조용히 무시)한다는 것을 직접 확인 | **기존 K-20과 동일 뿌리** — "ALTER TABLE의 중복/혼합 REPLICATION 절에 대한 세만틱 체크 부재로 조용히 덮어씀"(csql_grammar.y:5862-5871; semantic_check.c:8503-8516). 신규 아님 |
| `src/parser/semantic_check.c` (`pt_check_create_entity`) | `found_tbl_replication` 중복 검사가 **CREATE TABLE**의 옵션 목록에는 있지만 **ALTER TABLE** 경로(`alter_clause_for_alter_list`)에는 대응 검사가 없음을 재확인 | K-20과 동일 뿌리, 신규 아님 |
| `src/object/schema_template.c` (`find_index_catalog_class`) | 함수 전체를 읽음 — 정의만 있고 어디에서도 호출되지 않는 dead code, 내부에서 `DB_VALUE value`도 clear 안 됨(사소한 누수지만 dead code라 실행되지 않음) | K-33(dead code)과 동일 뿌리, 신규 아님 |
| `src/object/class_object.c` (`IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로, `classobj_copy_pk_and_uk_notnull_constraints`, `classobj_has_class_repl_key_constraint`, `classobj_find_cons_replication_key`) | 매크로 정의는 K-5(RK 후보 판정 불일치)와 동일 지점. `classobj_copy_pk_and_uk_notnull_constraints`가 `SM_IS_CONSTRAINT_UNIQUE_FAMILY(type) && NOT_NULL 플래그`만으로 PK/UK를 판별해 매크로와 조건식이 미묘히 다른지 대조했으나, PK 컬럼은 엔진이 항상 NOT NULL을 강제하므로 실질적 차이는 발생하지 않음을 확인 | 문제 없음(이론적 불일치는 K-5가 이미 포착한 지점과 동일 뿌리) |
| `src/base/object_representation_sr.c/.h` (`or_class_flags`, `or_class_is_replication_on`, `or_is_replication_candidate_key`) | `or_class_is_replication_on`이 `assert(OR_GET_OFFSET_SIZE(...) == BIG_VAR_OFFSET_SIZE)`만 하고 release 빌드에서는 검사 없이 진행하는 패턴을 확인했으나, 같은 파일의 `or_class_rep_dir`/`or_class_hfid`/`or_class_tde_algorithm` 등 **기존 함수들도 전부 동일한 패턴**을 그대로 쓰고 있어 이 기능 diff가 새로 만든 위험이 아니라 파일 전체의 기존 관례임을 확인 | 문제 없음(develop에도 있던 패턴, 이 기능 책임 아님) |
| `src/executables/util_service.c` (`us_hb_process_rkcheck`, `us_hb_process_start` 연결부) | 전체 76줄 diff를 다시 읽고 K-28(타임아웃 없음)·K-30(rkcheck가 cub_server보다 먼저/나중 실행되는 순서)·K-44(첫 실패 DB에서 break) 세 건의 위치·논리를 재확인 | 전부 기존 K-28/K-30/K-44와 동일 뿌리, 신규 아님 |
| `src/executables/checksumdb.c` (`chksum_calculate_checksum`) | `db_set_suppress_repl_on_transaction(false)` 복구 호출 실패 시, 바로 아래 `if (res >= 0) {...} else {...}` 두 분기 모두 `error`를 `res` 값으로 덮어써 복구 실패 정보가 사라지는 흐름을 라인 단위로 재확인 | 기존 문제 19와 완전히 동일한 지점, 신규 아님 |
| `src/object/object_printer.cpp`, `src/executables/unload_schema.c` (REPLICATION 출력 블록) | `sm_is_replication_class()` 호출부 두 곳의 diff를 다시 읽음 | 기존 문제 3·14·15, K-27/K-29/K-45/K-50/K-68과 동일 뿌리, 신규 아님 |

---

## 조사 종료 선언

**훑은 영역**: `git diff b646647ec...HEAD --stat`가 보고하는 35개 파일 전체를 대상으로, 이번 라운드에서
처음 Read로 연 13개 파일/영역(위 표)과, 기존에 두텁게 다뤄진 나머지 파일(`execute_schema.c`, `execute_statement.c`,
`util_cs.c`, `locator_sr.c`, `heap_file.c`, `btree.c`, `schema_system_catalog_install*.cpp` 등)을 grep으로
함수 목록 대조해 기존 K-리스트 커버리지에 빠진 함수가 없는지 확인했다. 새로 열어본 13개 지점 모두 (1) 기능과
무관한 사소한 변경이거나, (2) develop에도 있던 파일 전체의 기존 관례를 그대로 따른 것이거나, (3) 이미 병합된
67건 중 하나와 동일한 근본 원인(로그·헤더 선언·세만틱 체크 부재·dead code·assert 안전화·중단 로직)으로 귀결됐다.

**중단 근거**: 잔여 쿼터 32건을 채우기 위해 이미 지적된 문제를 각도만 바꿔 재포장하거나, DBA/운영 관점에서
실질적 영향이 없는 스타일 이슈(빈 줄 추가, 매크로 순서, 헤더 선언 형식 일치 여부)를 문제로 세는 것은 작업지시서
§4-1 "개수를 채우기 위한 억지 지적 금지" 원칙에 반한다. 3차 재수색에서 이 페르소나(운영 견고성·failover 경로·
로그 추적성·대량 스키마 성능) 관점으로 근거 있는 신규 결함을 찾지 못했으므로, 기존 18건을 그대로 유지하고
조사를 종료한다.

**결론**: 신규 확정 문제 0건. 기존 리포트 문제 1~19(문제5 제외 18건) 그대로 유지.
