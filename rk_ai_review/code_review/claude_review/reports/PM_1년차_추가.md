# PM 1년차 — RK/REPLICATION 기능 코드 리뷰 (3차 전수 재수색)

> 기준: `feature/CBRD-26246-develop` HEAD `734f4959d`, diff 범위 `b646647ec...HEAD`(35파일 +1,444/−57).
> 목적: 페르소나 누적 문제 수를 50건 기준까지 채우되, 근거 없는 억지 지적은 금지. 문제 번호는 기존
> `PM_1년차.md`(2차 리포트, 활성 15건: 문제 1·2·4·5·7·9·10·11·12·13·14·15·16·17·18)에 이어 19번부터 시작한다.

## 현재 상태

- **기존 리포트(PM_1년차.md) 활성 문제 수**: 15건(치명 4·중요 2·보통 6·사소 3). 해소 3건(문제 3, 6, 8)은 집계 제외.
- **잔여 쿼터**: 50 − 15 = **35건**.
- **이미 병합된 전체 리뷰(20페르소나) 중복 목록**: `dedup_existing.json` 67건(K-1~K-69 중 일부 결번 + K2-1~K2-3).

## 이번 라운드 수색 범위 (기존 리포트·67건이 아직 얕게 훑거나 아예 안 본 파일 우선)

diff 35개 파일 전체를 `git diff b646647ec...HEAD --stat`로 다시 뽑고, 파일별로 실제 diff hunk를 Read로
읽어 로직을 따라갔다. 이번에 새로 처음부터 끝까지 diff를 확인한 파일:

- `src/parser/csql_lexer.l`, `src/parser/parse_tree.h`, `src/parser/parse_tree_cl.c`, `src/parser/semantic_check.c`
- `src/parser/csql_grammar.y`의 REPLICATION 관련 규칙 전체(`class_replication_spec`, `opt_replication_option`,
  `alter_clause_for_alter_list`의 `PT_CHANGE_REPLICATION` 분기)
- `src/object/class_object.h`, `src/object/schema_manager.c`/`.h`(신규 `sm_is_replication_class`)
- `src/object/schema_template.c`(신규 `find_index_catalog_class`)
- `src/object/class_object.c`(신규 `classobj_copy_pk_and_uk_notnull_constraints`,
  `classobj_has_class_repl_key_constraint`, `classobj_find_cons_replication_key`)
- `src/base/object_representation_sr.c`/`.h`(신규 `or_class_flags`, `or_class_is_replication_on`,
  `or_is_replication_candidate_key`)
- `src/storage/heap_file.c`/`.h`(신규 `heap_get_class_repl_on`), `src/storage/btree.h`(rename만)
- `src/transaction/locator_sr.c` 전체 diff(INSERT/DELETE 경로 `locator_add_or_remove_index_internal`,
  UPDATE 경로 `locator_update_index` 양쪽 다시 라인 단위로 대조)
- `src/executables/checksumdb.c`(신규 `db_set_suppress_repl_on_transaction` 호출 2곳),
  `src/executables/util_admin.c`(신규 `ua_Rkcheck_Option*`), `src/executables/utility.h`(신규 RKCHECK 상수 전체)
- `src/executables/unload_schema.c`, `src/object/object_printer.cpp`(REPLICATION 출력부)
- `src/query/execute_schema.h`(신규 extern 선언), `src/query/parallel/px_worker_manager.cpp`(빈 줄 1개)

## 발견한 후보와 판정

아래는 코드를 실제로 읽고 로직까지 확인했으나, 최종적으로 **기존 지적과 동일 뿌리** 또는 **작업지시서상
지적 금지 항목**으로 판정해 신규로 세지 않은 것들이다(억지로 각도만 바꿔 새 번호를 매기지 않기 위해 판단
근거를 남긴다).

1. **`locator_update_index()`가 여전히 옛 `heap_is_replication_class()`(bool 반환, 실패 시
   `assert(false); return false;`)를 호출** — `locator_sr.c:8427` 부근, `or_is_replication_candidate_key(index)
   && heap_is_replication_class(thread_p, class_oid)`. `locator_add_or_remove_index_internal()`(INSERT/DELETE
   경로)만 `heap_get_class_repl_on()`(에러 전파형)으로 교체됐고, UPDATE 경로는 그대로다.
   → **작업지시서 §7이 명시적으로 "지적 금지" 처리한 항목**("`locator_update_index()`의 옛
   `heap_is_replication_class` 잔존 호출은 커밋 `60648d919`대로 수정 완료된 것으로 간주"). 코드를 직접
   대조한 결과 실제로는 그 커밋이 이 경로까지 반영하지 않은 것으로 보이지만, 지시에 따라 신규 문제로
   등록하지 않는다.
2. **`locator_update_index()`의 RK 후보 선택이 인덱스 배열의 첫 매치(`rk_btid_index == -1` 게이트)에만
   의존** — `locator_sr.c:8427-8433`. PK와 별도의 NOT NULL UNIQUE가 공존하는 테이블에서 어떤 인덱스가
   복제키로 채택되는지가 `new_attrinfo->last_classrepr->indexes[]` 배열 순서에 좌우된다.
   → `dedup_existing.json`의 **K-58**("RK 자동 선택이 인덱스 배열 순서에 의존해 마스터/슬레이브가 독립
   재계산")과 같은 뿌리(인덱스 배열 순서 의존)로 판단, 신규 등록하지 않음.
3. **`classobj_copy_pk_and_uk_notnull_constraints()`가 복합(다중 컬럼) UNIQUE 제약을 컬럼 단위
   `SM_ATTFLAG_NON_NULL` 체크로 판단해 컬럼별로 다르게 복사** — `class_object.c:561-593`(정의),
   `:4813-4820`(`classobj_init_attribute` 호출부). 파티션 승격 시 첫 컬럼만 NOT NULL이면 그 컬럼에만
   제약 사본이 붙고 나머지 컬럼엔 안 붙는 것으로 보인다.
   → `dedup_existing.json`의 **K-24**(같은 함수·같은 호출부, "파티션 승격 전용 제약 복사 로직이 범용
   attribute-copy 경로에 부작용") 및 **K-14**(같은 증상의 do_promote_partition 쪽 관찰)와 동일 뿌리로
   판단, 신규 등록하지 않음.
4. **ALTER TABLE에 REPLICATION 절을 두 번 쓰면(`ALTER TABLE t REPLICATION=ON, REPLICATION=OFF;`) 파서가
   중복 검사 없이 첫 번째 값만 유지하고 두 번째를 조용히 무시** — `csql_grammar.y`
   `alter_clause_for_alter_list`의 `class_replication_spec` 분기(`if (alter_node->info.alter.code !=
   PT_CHANGE_REPLICATION)`), `semantic_check.c`의 `pt_check_alter()`에는 CREATE 쪽
   `found_tbl_replication`과 대응하는 중복 검사가 없음.
   → `dedup_existing.json`의 **K-20**("ALTER TABLE의 중복/혼합 REPLICATION 절에 대한 세만틱 체크 부재")과
   위치·근본원인(ALTER 경로에 REPLICATION 중복 검사 자체가 없음)이 동일해 신규 등록하지 않음(정확한 증상
   문구가 "덮어씀"과 "첫 값 유지"로 다르지만 뿌리는 "중복 검사 부재"로 같다).
5. **`checksumdb.c`의 `chksum_calculate_checksum()`에서 `db_set_suppress_repl_on_transaction(false)`
   호출이 반환한 에러가 `db_execute()`/`chksum_update_master_checksum()` 성공 여부와 무관하게 `error`
   변수를 갱신** — `checksumdb.c:1737-1751`. 코드 분석 결과 이 호출은 CS 모드 연결 유실 같은 극히 드문
   경우에만 실패하며(`db_admin.c:1543-1548`의 `CHECK_CONNECT_ERROR()` 게이트), 실패 시에도 상위 루프가
   `db_abort_transaction()` 후 루프를 중단하는 것 자체는 이미 다른 실패 케이스와 동일하게 처리되는
   흐름이라 명백한 오동작이라 보기 어렵다. 2차 리포트에서 이미 이 경로("db_set_suppress_repl_on_transaction
   성공/실패 처리 순서")를 직접 검토해 결함 없음으로 결론 낸 바 있고, 이번에 다시 봐도 동일 결론이라
   신규 등록하지 않는다.

## 조사 종료 선언

이번 3차 전수 재수색은 diff 35개 파일 중 기존 리포트·67건 병합 결과가 아직 라인 단위로 다루지 않았던
파서(lexer/grammar/parse_tree/semantic_check), 스키마 객체 계층(class_object/schema_manager/
schema_template), 저장 계층 헬퍼(object_representation_sr, heap_file), `locator_sr.c` 전체, 신규 유틸리티
배선(checksumdb.c의 SBR-suppress 로직, util_admin.c/utility.h의 RKCHECK 옵션 등록)까지 실제 코드를 Read로
읽고 콜체인을 따라가며 검증했다. 위 5건의 후보를 찾았으나 모두 (a) 작업지시서가 명시적으로 지적을
금지한 항목이거나 (b) 이미 병합된 67건 중 하나와 위치·근본 원인이 같은 재탕으로 판정되어, **이번
라운드에서 새로 세는 문제는 0건**이다.

잔여 쿼터 35건 중 신규 발굴분은 없다. 이는 억지로 채우지 않은 결과이며, "코드가 실제로 하는 일과
문서/주석/이웃 코드/PR 히스토리가 말하는 바가 다른" 수준의 검증 가능한 결함은 1~2차 라운드에서 이미
전부 소진되었다고 판단한다.

- **누적 문제 수(변동 없음)**: 15건 (문제 1, 2, 4, 5, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18)
- **3차 신규**: 0건
