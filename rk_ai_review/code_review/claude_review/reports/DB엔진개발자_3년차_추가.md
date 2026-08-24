# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 3년차 (3차 전수 재수색)

> **3차 전수 재수색(기준 `734f4959d`)** — merge-base(`b646647ec`)…HEAD 전체 diff 35파일을 다시 훑었다. 기존 2차 리포트(문제 2~18, 유지 16건)와 이미 병합된 67건(dedup_existing.json: K-1~K-69 + K2-1/2/3)을 뿌리 기준으로 대조해, **loc·원인이 겹치지 않는 신규 결함만** 추가한다. 문제 번호는 기존 리포트(최대 18)에 이어서 붙인다.
>
> 잔여 쿼터 = 50 − 16(기존 유지) = 34. 아래 전수 수색 결과 **근거 있는 신규 결함 2건**만 성립했고, 나머지 diff 영역은 기존 83건(67+16)이 이미 뿌리째 덮고 있어 억지 지적 없이 종료를 선언한다.

---

## 문제 19

**[심각도: 보통] rkcheck의 `check_repl_constraint_violations()`가 `db_is_system_class()`의 3-상태 반환(음수=에러)을 방어하지 않는다 — fetch 실패한 클래스를 "시스템 클래스"로 오판해 RK/FK 검사에서 조용히 건너뛴다**

- 위치: `src/executables/util_cs.c:3216-3226` (`check_repl_constraint_violations`), 호출 헬퍼 `db_is_system_class` → `src/object/schema_manager.c` `sm_is_system_class` → `sm_get_class_flag`

로직 설명:
```c
is_vclass = db_is_vclass (c->op);
if (is_vclass < 0)          /* db_is_vclass는 음수 방어함 */
  {
    return is_vclass;
  }
if (db_is_system_class (c->op) || is_vclass > 0 || !sm_is_replication_class (c->op))
  {
    continue;               /* skip */
  }
*violation_count += check_func (c->op, fp);
```
- `db_is_system_class()`는 `sm_is_system_class()` → `sm_get_class_flag()`로 이어지는데, `sm_get_class_flag`는 `locator_is_class()`가 `<= 0`이면 그 값을, `au_fetch_class_force()`가 실패하면 그 **음수 에러 코드**를 그대로 반환한다(`schema_manager.c`, `result <= 0` / `result == NO_ERROR` 분기). 즉 이 함수는 `1`(시스템)/`0`(아님)/`음수`(에러)의 3-상태다.
- C에서 음수는 참(truthy)이므로 `db_is_system_class(c->op)`가 에러 음수를 돌려주면 조건 전체가 참이 되어 그 클래스는 `continue`로 **검사에서 제외**된다.
- 바로 위 `db_is_vclass`는 `is_vclass < 0`으로 음수를 명시적으로 걸러 `return`하는데, **같은 조건식 안의 `db_is_system_class`만 이 방어가 빠져 있다.** 이건 PR #6939에서 vimkim이 정확히 지적해 고친 결함(`db_is_vclass`의 음수 truthy 오판, "코드베이스 25곳 중 18곳이 이미 `> 0` 비교")과 동일 계열의 실수가 형제 함수에 남은 것이다.

문제 시나리오: rkcheck는 `cubrid hb start` 시 자동 실행되며 실행 중 서버에 붙어 `db_get_all_classes()` 각 클래스를 fetch한다. 어떤 사용자 클래스의 `au_fetch_class_force`가 락 대기 타임아웃·인터럽트·일시적 오류로 실패하면 `db_is_system_class`가 음수를 반환 → 그 클래스는 RK/FK 검사에서 조용히 스킵된다. 그 클래스가 실제로는 RK 없는 복제 테이블(위반)이어도 `rk_violation_count`에 세어지지 않아, rkcheck가 "이상 없음"으로 보고하고 HA가 위반 상태로 기동된다. rkcheck의 존재 이유(기동 전 위반 사전 차단)가 무력화되는 침묵성 미검출이다.

제안: `db_is_vclass`와 대칭으로 `int is_system = db_is_system_class(c->op); if (is_system < 0) return is_system;`처럼 음수를 에러로 전파한 뒤 `is_system > 0`으로 비교해야 한다. `sm_is_replication_class` 역시 fetch 실패를 false로 뭉개(assert+false) 같은 스킵을 유발하므로(K-7 계열) 판정 불가와 "비복제"를 구분해 전파하는 것이 근본이다.

---

## 문제 20

**[심각도: 사소] `pt_print_table_option()`이 REPLICATION 옵션 값을 `ON/OFF`가 아니라 원시 정수 `0/1`로 출력한다 — 파스트리 재출력이 문법으로 되읽을 수 없는 텍스트를 만든다**

- 위치: `src/parser/parse_tree_cl.c:8041-8043`(REPLICATION 케이스), 값 출력 `:8071-8074`(`else` 분기), 대조 `:8060-8070`(ENCRYPT 특수 매핑), 문법 `src/parser/csql_grammar.y` `opt_replication_option`(`ON_`/`OFF_`/empty만 허용)

로직 설명:
```c
case PT_TABLE_OPTION_REPLICATION:
  q = pt_append_nulstring (parser, q, "replication = ");
  break;
...
if (p->info.table_option.val != NULL) {
  ...
  else if (option == PT_TABLE_OPTION_ENCRYPT) {   /* ENCRYPT는 정수를 알고리즘명으로 매핑 */
    tde_algo_name = tde_get_algorithm_name (val->info.value.data_value.i);
    r1 = pt_append_bytes (...tde_algo_name...);
  }
  else {                                          /* REPLICATION은 여기로 빠짐 */
    r1 = pt_print_bytes_l (parser, p->info.table_option.val);  /* PT_VALUE 정수를 그대로 */
  }
}
```
- 문법에서 REPLICATION 옵션 값은 `PT_VALUE`/`PT_TYPE_INTEGER`로 저장된다(`class_replication_spec`: `node->info.value.data_value.i = $3`, ON=1/OFF=0).
- `pt_print_table_option`은 ENCRYPT처럼 정수→문자열 매핑을 해주는 특수 분기가 REPLICATION엔 없어, `else`의 `pt_print_bytes_l`로 정수를 그대로 찍는다. 결과 텍스트는 `replication = 1` / `replication = 0`이 된다.
- 그런데 파서 규칙 `opt_replication_option`은 `ON_`, `OFF_`, 또는 empty만 받는다. 즉 이 재출력 텍스트를 다시 파싱하면 `replication = 1`의 `1`에서 **문법 에러**가 난다(round-trip 불가).

문제 시나리오: 이 함수는 CREATE 파스트리를 SQL 텍스트로 되돌리는 경로(`parser_print_tree`/`pt_print_bytes` 계열, CREATE ENTITY 테이블 옵션 출력)에서 쓰인다. SHOW CREATE·unloaddb는 `object_printer`(`REPLICATION=ON/OFF`)를 쓰므로 영향이 없지만, 파스트리를 다시 문자열화하는 소비자(문장 에코/디버그 출력, 재파싱 경로)가 있으면 `replication = 1`처럼 사람이 읽기에도 어긋나고 재파싱 시 깨진다. ENCRYPT가 정수를 알고리즘명으로 매핑한 것과 대비되는 명백한 누락이다.

제안: REPLICATION 전용 분기를 두어 `val->info.value.data_value.i ? "ON" : "OFF"`로 출력하도록 한다(ENCRYPT 분기와 동일한 패턴).

---

## 조사 종료 선언 (3차 전수 재수색)

전체 35파일 diff를 파일 단위로 재수색했다. 아래는 훑은 영역과, 신규 지적을 더 내지 않는 근거다(잔여 쿼터 34 중 2건만 성립 → 억지 미채움).

**신규로 성립한 것 (2건)**
- 문제 19: `db_is_system_class` 음수 truthy 미방어(rkcheck 침묵 스킵) — 기존 67건·2차 16건 어디에도 없음(db_is_vclass만 다룸).
- 문제 20: `pt_print_table_option` REPLICATION 값 정수 출력 — 기존 어디에도 없음.

**기존 83건(67 병합 + 2차 16)이 이미 뿌리째 덮어 신규로 세지 않은 영역**
- 파서/문법: `csql_lexer.l`(REPLICATION 토큰), `csql_grammar.y`(`class_replication_spec`/`opt_replication_option`, 비예약어 목록·ALTER 중복절)=K-11/K-20, `parse_tree.h`/`parse_tree_cl.c`(PT_CHANGE_REPLICATION·PT_TABLE_OPTION_REPLICATION), `semantic_check.c`(CREATE 중복 옵션 검사; ALTER 미검사=K-20).
- 스키마/객체: `class_object.c/h`(IS_HA_REPLICATION_KEY_CONSTRAINT·`classobj_copy_pk_and_uk_notnull_constraints`·`classobj_has_class_repl_key_constraint`·`classobj_find_cons_replication_key`)=K-5/K-24/K-35, `schema_manager.c`(`sm_is_replication_class` assert+false)=K-7, `schema_template.c`(`find_index_catalog_class` dead code)=K-33, `object_printer.cpp`(describe_class)=K-29/K-50/K-68, 카탈로그 install/query_spec(신규 컬럼 위치·포맷 vararg)=K-19/K-42.
  - `classobj_copy_pk_and_uk_notnull_constraints`는 `SM_IS_CONSTRAINT_UNIQUE_FAMILY`가 PRIMARY_KEY를 포함(class_object.h:111)함을 확인 → PK 누락 우려는 오판, 미지적. 범용 attribute-copy 부작용은 K-24로 덮임.
- 서버 복제 경로: `object_representation_sr.c`(`or_class_is_replication_on` 매직32·`or_is_replication_candidate_key` REVERSE_UNIQUE/BTREE_UNIQUE 불일치·filter/function 인덱스)=K-10/K-5/K-26, `heap_file.c`(`heap_get_class_repl_on`)=#7697로 해소(문제 1), `locator_sr.c`(INSERT/DELETE는 `heap_get_class_repl_on`+에러전파, `!replicated` 단락; OFF+다중후보 반복 fetch=K2-2), `btree.c`(`btree_get_rkey_btid` 배열순서 의존)=K-58, `btree.h`(파라미터명 미변경)=2차 문제 17.
  - `locator_update_index`의 잔존 `heap_is_replication_class` 호출은 §7 가정에 따라 수정 완료 간주·미지적.
- DDL 실행: `execute_schema.c`(do_alter 재검사 게이트 첫절만=K-1/문제4, 매크로 누락=K-6/문제5, `check_ha_repl_constraint`/FK 헬퍼 중복·NULL·주석불일치=K-4/K-25/K-35/문제7·8, `do_alter_change_replication` 세이브포인트 재사용=K-9, `do_promote_partition`/`has_notnull_unique_constraints`=K-14/K-51/K-64/문제10, `do_create_partition` 복붙=K-37, CREATE LIKE+REPLICATION=K-21, CTAS=K-69, UNDER 상속=K-53). do_alter 최종 `return NO_ERROR`는 AU_ENABLE(:1996)로 균형 잡혀 자원누수 없음 확인 → NULL vclass만 K-17로 덮임.
- DML/SBR: `execute_statement.c`(`is_data_repl_log_enabled`/`spec_has_replication_class`/`pt_spec_repl_class_walk`=#7678, `is_replication_class` assert+false=K-15/문제18, `truncate_need_repl_log`=K-32, 혼합 ON/OFF·USE_SBR join=K-52/K2-1, 비-DML `default:return true`=문제11). `is_stmt_based_repl_type`가 MERGE를 포함하지 않아 MERGE는 이 게이트에 도달하지 않음을 확인 → MERGE 미복제 가설은 오판, 미지적.
- 유틸/에러: `util_cs.c` rkcheck 파일·버퍼·종료코드·중복순회·로그명=K-2/K-13/K-34/K-38~K-47/K-59/K-62/K-63/K-65/문제3·12·14·15, `util_service.c`(rkcheck 순서·타임아웃·break·failover 우회)=K-28/K-30/K-44/K-55, `util_admin.c`/`utility.h`(rkcheck enum 중간삽입)=K-61, `unload_schema.c`(버전가드·fetch실패)=K-27/K-45, `checksumdb.c`(SBR 억제 대칭구조; resume 실패 시 에러 베이스라인 유지는 커밋 명시 의도로 2차에서 이미 검토)=#7678, `error_code.h`/`cubrid.msg`(신규 -1375~-1378, 메시지 1375~1378 번호·인자 정합 확인; dbi_compat.h는 이 프로젝트에서 인접 코드도 미포함이라 동기화 대상 아님; 국문 "테이블 생성 시" 고정=K-23), `msg .../utils.msg`(사용법 형식)=K-60.
- 무관/무의미 변경: `px_worker_manager.cpp`(네임스페이스 빈 줄 추가 1줄)는 RK/REPLICATION과 무관한 no-op → 억지 지적 회피 위해 제외.

가장 시급한 것은 여전히 2차 문제 2(치명, 클라이언트/서버 RK 판정 불일치=K-5)이며, 3차에서 추가된 두 건은 rkcheck 침묵 스킵(문제 19)과 파스트리 재출력 정합(문제 20)이다.
