# CUBRID RK/REPLICATION 기능 코드 리뷰 — DB엔지니어(DBA/운영) 3년차 — 3차 전수 재수색

> **기준**: `feature/CBRD-26246-develop` HEAD `734f4959d`, diff 범위 `merge-base(upstream/develop) b646647ec...HEAD`
> (35파일, +1,444/−57). 기존 리포트(`DB엔지니어_3년차.md`, 문제 1~15, 해소 2건 제외 **유지 13건**)에
> 이어 번호를 매기며, 이미 병합된 K-1~K-69·K2-1~K2-3(67건, `dedup_existing.json`)와 같은 뿌리의
> 지적은 신규로 세지 않는다.

## 수색 방법

1. `git diff b646647ec...HEAD --stat`로 35개 파일 전체 목록을 확보.
2. 기존 문서(내 1·2차 리포트 + 병합 67건)가 언급하지 않은 파일부터 우선 순회:
   `src/base/error_code.h`, `src/executables/checksumdb.c`, `src/executables/util_admin.c`,
   `src/object/class_object.h`, `src/object/schema_manager.h`, `src/parser/csql_lexer.l`,
   `src/parser/parse_tree.h`, `src/parser/parse_tree_cl.c`, `src/query/execute_schema.h`,
   `src/query/parallel/px_worker_manager.cpp`, `src/storage/btree.h`, `src/storage/heap_file.h`.
3. 이어서 이미 다룬 파일이라도 diff 전체(추가된 함수·조건문 단위)를 다시 라인 단위로 읽어,
   기존 지적이 놓친 별개의 로직 경로가 있는지 확인: `execute_schema.c`(405줄 추가분 전체),
   `execute_statement.c`(156줄 전체, `is_data_repl_log_enabled`/`spec_has_replication_class`/
   `pt_spec_repl_class_walk` 전체 본문), `class_object.c`(`classobj_copy_pk_and_uk_notnull_constraints`),
   `object_representation_sr.c`(`or_is_replication_candidate_key`/`or_class_is_replication_on`),
   `locator_sr.c`(`locator_add_or_remove_index_internal`/`locator_update_index` 전체 diff),
   `util_service.c`(`us_hb_process_rkcheck` 신규 함수 전체), `util_cs.c`(`get_repl_check_flags`),
   `schema_template.c`(`find_index_catalog_class`), `object_printer.cpp`/`unload_schema.c`/
   `schema_system_catalog_install*.cpp`/`btree.c`의 REPLICATION 관련 신규 코드 전량.
4. 매크로 정의(`SM_IS_CONSTRAINT_UNIQUE_FAMILY`, `IS_HA_REPLICATION_KEY_CONSTRAINT`,
   `ASSERT_ERROR_AND_SET`)를 직접 열어 실제 포함 범위를 확인(추측 금지).
5. 작업지시서 §7 가정에 따라 `locator_update_index()`의 잔존 `heap_is_replication_class` 호출은
   실제 코드에는 아직 옛 형태로 남아 있음을 확인했으나(커밋 `60648d919`가 현재 브랜치 이력에
   병합되어 있지 않음), 지시에 따라 **지적하지 않는다**.

## 재확인했으나 신규로 세지 않은 것들 (근거)

- **`do_alter()`의 `PT_CHANGE_REPLICATION` 경로**: `do_alter_change_replication()`이 함수 진입 시점에
  `if (!HA_DISABLED())`로 HA 모드에서의 REPLICATION 옵션 변경 자체를 즉시 차단(`ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED`)한다.
  `IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로에 `PT_CHANGE_REPLICATION`이 빠져 있어도, HA 모드에서는
  애초에 이 절 자체가 실행되지 못하므로 RK 재검증 누락으로 이어지지 않는다 — 별개 문제 아님.
- **`classobj_copy_pk_and_uk_notnull_constraints()`가 PK를 빠뜨리는지**: 함수 주석이 "PK 또는 NOT NULL
  UNIQUE"라고 적어놓고 조건은 `SM_IS_CONSTRAINT_UNIQUE_FAMILY(type)`만 검사해 PK 누락을 의심했으나,
  `class_object.h:111`에서 직접 확인한 결과 이 매크로는 `SM_CONSTRAINT_PRIMARY_KEY`를 포함한다 —
  실제로는 누락 없음(K-24가 다루는 "범용 경로에 파티션 전용 로직이 새는 것" 자체는 이미 지적됨).
- **`or_is_replication_candidate_key()`가 `BTREE_REVERSE_UNIQUE`를 인정하지 않는 것**: DDL 판정
  (`IS_HA_REPLICATION_KEY_CONSTRAINT`, `SM_IS_CONSTRAINT_UNIQUE_FAMILY` 경유)은 REVERSE UNIQUE를
  RK 후보로 인정하지만 런타임 판정은 `BTREE_UNIQUE`만 본다는 지적은, 기존 K-5의 제목("DDL 검증(하나라도
  NOT NULL/REVERSE UNIQUE 허용)과 런타임 복제(전부 NOT NULL/BTREE_UNIQUE)에서 불일치")에 이미
  명시적으로 포함되어 있다 — 같은 뿌리.
- **`heap_get_class_repl_on()`이 인덱스 순회 루프에서 RK 후보마다 반복 호출되는 것**
  (`locator_add_or_remove_index_internal`): 기존 K2-2와 동일 지점·동일 원인.
- **`checksumdb.c`의 `db_set_suppress_repl_on_transaction(false)` 리턴값 처리**: `error`를 baseline으로
  잡고 이후 실행 실패가 있으면 그 값이 최종 `error`를 덮어쓰는 구조를, 내 1차 리포트의 "조사 종료 선언"에서
  이미 직접 추적해 "resume 실패가 있어도 은폐되지 않는다"고 판단해 배제한 바 있다 — 이번에 재확인해도
  동일 결론(다만 `db_set_suppress_repl_on_transaction`이 실패하려면 연결 단절 수준의 전제조건이 필요해
  실무적 근거가 약하다는 판단도 유지).
- **`us_hb_process_rkcheck()`의 `PRM_ID_HA_MODE_FOR_SA_UTILS_ONLY` 강제 설정 패턴**: 같은 파일의
  `us_hb_copylogdb_start`/`us_hb_applylogdb_start` 등 기존 함수들과 동일한 관용구(먼저
  `HA_MODE_FAIL_BACK`으로 강제 설정 후 `sysprm_load_and_init`으로 실제 값을 로드해 판별)를 그대로
  재사용한 것으로, 신규 버그가 아니라 기존 관례를 따른 것이다.
- **`us_hb_process_rkcheck()`가 `us_hb_server_start()` 뒤·`us_hb_copylogdb_start()` 앞에 호출되는 순서**:
  기존 K-30("hb start가 rkcheck보다 cub_server를 먼저 기동")과 정확히 같은 지점.
- **REPLICATION 절 중복 지정 시 무경고 덮어쓰기**: `csql_grammar.y`의
  `alter_clause_for_alter_list: class_replication_spec { if (...code != PT_CHANGE_REPLICATION) ... }`
  가드를 직접 열어봤고, `ALTER TABLE`에서 두 번째 REPLICATION 절이 조용히 무시되는 것은 기존
  K-20과 동일 지점.
- **`db_class` 카탈로그 뷰에 `is_replication_class` 컬럼이 중간에 삽입되는 것**: `schema_system_catalog_install.cpp:1313`,
  `_query_spec.cpp:74,138`을 직접 diff했고 기존 K-19와 동일.
- **`btree_get_rkey_btid()`/`or_class_is_replication_on()`/`classobj_find_cons_replication_key()`**:
  각각 기존 K-58/K-10/K-32 계열과 동일한 함수의 리네이밍·로직으로, 새 문제를 추가하지 않는다.

## 훑었으나 문제를 찾지 못한 영역

- `src/base/error_code.h`(신규 에러코드 4개 -1375~-1378, `ER_LAST_ERROR` 갱신)와 4개 메시지 파일의
  숫자가 1:1로 정확히 대응함을 직접 대조 확인(코드↔메시지 어긋남 없음).
- `src/executables/util_admin.c`(`ua_Rkcheck_Option_Map`/`ua_Rkcheck_Option`)의 옵션 등록이
  `utility.h`의 `RKCHECK_CHECK_RK_CONSTRAINT_S/L` 등 상수와 정확히 매칭됨을 확인.
- `src/parser/csql_lexer.l`(REPLICATION 키워드 추가)과 `parse_tree.h`/`parse_tree_cl.c`의
  `PT_TABLE_OPTION_REPLICATION`/`PT_CHANGE_REPLICATION` 열거값·프린터 케이스는 형식적으로 정상.
- `src/query/parallel/px_worker_manager.cpp`의 변경은 빈 줄 한 줄 추가뿐으로 REPLICATION 기능과 무관.
- `get_repl_check_flags()`(util_cs.c:2867)의 `-r`/`-f` 플래그 조합 로직(둘 다 생략 시 둘 다 검사)은
  의도대로 동작.

## 결론

이번 3차 전수 재수색에서 35개 파일 diff 전량을 라인 단위로 재확인했으나, 기존 82건(2차 리포트 13건
유지 + 병합 67건)과 다른 뿌리를 가진 **신규 문제를 발견하지 못했다**. 발견된 후보들은 모두 위 "재확인
했으나 신규로 세지 않은 것들"에서 근거와 함께 기각했다.

**잔여 쿼터 37건 중 0건 추가.**

## 조사 종료 선언

1·2·3차에 걸쳐 REPLICATION/RK 기능 diff 35개 파일(+1,444/−57) 전량을 grep이 아닌 라인 단위 diff
대조와 매크로/함수 정의 직접 확인(`SM_IS_CONSTRAINT_UNIQUE_FAMILY`, `IS_HA_REPLICATION_KEY_CONSTRAINT`,
`ASSERT_ERROR_AND_SET`, `IS_REPL_CONSTRAINT_RELATED_ALTER` 등)으로 검증했다. 유지 13건(문제 1~15 중
5·7 해소)이 이 기능의 핵심 결함(다중 절 ALTER 게이트 우회, DROP INDEX 경로 누락, rkcheck의 여러
크래시·운영 결함, DDL/런타임 RK 판정 불일치)을 이미 포괄하고 있고, 이번 라운드에서 확인한 나머지
변경분(에러코드·메시지 정합성, 파서 토큰, 카탈로그 뷰 컬럼, `us_hb_process_rkcheck` 신규 함수 등)은
모두 기존 지적과 같은 뿌리이거나 정상 동작으로 확인됐다. 이 이상은 이미 식별된 안티패턴(에러를
bool/무시로 삼키는 함수, 재검증 게이트 누락, 순서 의존성)의 변주를 찾는 작업이 될 것으로 판단해
여기서 3차 재수색을 마무리한다.
