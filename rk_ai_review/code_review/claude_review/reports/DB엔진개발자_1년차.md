# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 1년차 (2차 재리뷰, 기준 734f4959d)

## 페르소나 소개

저는 CUBRID 엔진 팀에 들어온 지 1년 된 개발자입니다. 아직 이 거대한 코드베이스의 모든
관습(에러 모델, memory_wrapper, 클래스 레코드 인코딩 등)에 익숙하지는 않지만, 오히려 그래서
"처음 읽는 눈"으로 이상한 곳을 잘 잡습니다. 이해가 안 되는 함수, 이름과 실제 동작이 어긋나는 곳,
주석과 코드가 따로 노는 곳, 복붙(copy-paste)하다 남은 흔적, 그리고 락·에러 경로·NULL 처리처럼
"정상 흐름에서는 안 보이지만 실패하면 터지는" 곳을 집중해서 봤습니다.

## 2차 재리뷰 안내

이 리포트는 upstream 동기화 이후 새 기준 `feature/CBRD-26246-develop` HEAD `734f4959d`
(= `44468ed73` + #7678 `3b6ebd1a9` + #7697 `9e094324b`)에서 1차 문제들을 재검증하고
동기화 델타(#7678 SBR/checksumdb, #7697 인터럽트 수정)와 전체 diff에서 새 문제를 발굴한 결과다.

- **재검증 방법**: 각 1차 문제를 새 HEAD 코드에서 LSP·Read로 다시 확인해 위치(file:line)를
  갱신하고, 성립 여부를 판정했다.
- **주요 변화**: #7697이 `heap_is_replication_class()`(bool 반환, 인터럽트 삼킴)를
  `heap_get_class_repl_on()`(int 에러코드 + out-param)으로 근본 교체하고
  `locator_add_or_remove_index_internal()`의 `&&` 사슬을 분리해 인터럽트를 전파하도록 고쳤다.
  이로써 1차 **문제 1(치명, 인터럽트 삼킴)**의 근본 원인이 사라졌고, 그 과정에서 조건 순서가
  재정렬되어 1차 **문제 12(성능·순서 불일치)**도 함께 해소됐다. 두 건은 본문에서 제외한다.
- **번호 규칙**: 유지되는 문제는 1차 번호를 그대로 쓰고(2~22, 12 제외), 신규 문제는 이어서
  번호를 붙였다(23).

## 총평

기능 본체는 여러 PR을 거치며 촘촘히 다듬어졌고, 동기화로 가장 위험했던 인터럽트 삼킴 버그가
근본 해결됐습니다. 다만 **정합성의 핵심**인 "무엇이 복제키(RK)인가"라는 판정이 여전히
**경로마다 서로 다른 정의**로 구현돼 있고(문제 4), 실패 경로에서 NULL을 역참조하는 크래시
위험(문제 5·6)과 다중 절 ALTER의 재검사 게이트가 첫 절만 보는 버그(문제 2·3)가 그대로
남아 있습니다. 동기화로 새로 들어온 SBR 판정 코드에서는, 방금 #7697이 없앤 것과 똑같은
"조회 실패에 `assert(false)`" 안티패턴이 다시 등장한 지점(문제 23)을 발견했습니다.
억지로 개수를 채우지 않고, 근거를 확인한 것만 적었습니다.

---

## 문제 2

**[심각도: 중요] 다중 절 ALTER의 복제 재검사 게이트가 "첫 절 코드"만 본다**

**위치**: `src/query/execute_schema.c:2051` (`do_alter`)

**로직 설명**: `do_alter()`는 clause 리스트를 `for (crt_clause = alter; ...; crt_clause = crt_clause->next)`로
순회하며 각 절 코드를 `alter_code = crt_clause->info.alter.code`(:1854)로 꺼내 처리합니다.
그런데 재검사 필요 여부를 켜는 게이트는
`IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code)`(:2051)로, **루프 변수 `crt_clause`가 아니라
리스트 머리 `alter`의 코드**를 봅니다. 이 값은 루프 내내 변하지 않고 항상 첫 절의 코드입니다.

**문제 시나리오**: `ALTER TABLE t COMMENT='x', DROP CONSTRAINT uk_rk;`처럼 첫 절이 복제 무관
(PT_CHANGE_TABLE_COMMENT)이고 뒤 절이 RK를 제거(PT_DROP_CONSTRAINT)하는 경우, 게이트는 첫 절
코드(comment)만 보므로 `need_check_repl_constraint`가 켜지지 않습니다. 결과적으로
`check_ha_repl_constraint()`(:2068) 재검사가 실행되지 않아, RK가 하나도 없는데 REPLICATION=ON인
테이블이 그대로 남습니다. HA 기동 전 rkcheck가 잡아주기 전까지는 무증상입니다.

**제안**: 게이트를 `IS_REPL_CONSTRAINT_RELATED_ALTER (alter_code)`(= `crt_clause->info.alter.code`)로
바꿔 절 단위로 판정해야 합니다. (#6637에서 검사 위치를 do_alter로 옮긴 취지가 "모든 절 처리 후
최종 상태 검사"인데, 게이트가 첫 절만 보면 그 취지가 깨집니다.)

---

## 문제 3

**[심각도: 중요] `IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로에 MODIFY/CHANGE COLUMN 경로가 빠져 있다**

**위치**: `src/query/execute_schema.c:109-114` (매크로 정의)

**로직 설명**: 이 매크로는 `PT_ADD_ATTR_MTHD`, `PT_DROP_ATTR_MTHD`, `PT_DROP_CONSTRAINT`,
`PT_DROP_PRIMARY_CLAUSE`만 "복제 제약에 영향 주는 절"로 인정합니다. 그런데 `do_alter`의 switch에는
`PT_CHANGE_ATTR`(MODIFY/CHANGE COLUMN)와 `PT_MODIFY_ATTR_MTHD`도 있고, 이들은 컬럼의 NOT NULL
속성이나 타입을 바꿀 수 있습니다.

**문제 시나리오**: RK가 `NOT NULL UNIQUE(x)`인 테이블에서 `ALTER TABLE t MODIFY x INTEGER;`로
`x`의 NOT NULL을 떼면, 그 UNIQUE는 더 이상 RK 자격이 없어집니다(NOT NULL이 빠졌으므로). 하지만
PT_CHANGE_ATTR는 게이트 매크로에 없어 `check_ha_repl_constraint()` 재검사가 돌지 않습니다.
결과적으로 RK 없는 REPLICATION=ON 테이블이 조용히 만들어집니다. 이는 스펙 리뷰 C-9와 동일한
지점입니다.

**제안**: 매크로에 `PT_CHANGE_ATTR`, `PT_MODIFY_ATTR_MTHD`를 추가하고, 문제 2와 함께 절 단위로
판정하도록 고쳐야 합니다. (C-9, 2M-6, 2m-3)

---

## 문제 4

**[심각도: 중요] "무엇이 RK인가"의 정의가 경로마다 다르다 — 스키마 검사는 "하나라도 NOT NULL", 복제 로그 경로는 "전부 NOT NULL"**

**위치**: `src/object/class_object.c:95-98`(`IS_HA_REPLICATION_KEY_CONSTRAINT` → `sm_has_non_null_attribute`,
`src/object/schema_manager.c:16115`) vs `src/base/object_representation_sr.c:4694`
(`or_is_replication_candidate_key`)

**로직 설명**: RK 판정이 두 군데에 서로 다르게 구현돼 있습니다.
- 스키마/DDL 쪽: `IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로가 복합 UNIQUE에 대해
  `sm_has_non_null_attribute(attrs)`를 씁니다. 이 함수는 "구성 컬럼 중 **하나라도** NOT NULL이면 1"을
  반환합니다(schema_manager.c:16121-16127 확인, 첫 NON_NULL 발견 시 즉시 1 반환).
- 복제 로그 쪽: `or_is_replication_candidate_key`는 복합 UNIQUE의 모든 att를 순회하며
  **하나라도 `is_notnull`이 아니면 false**를 반환합니다(즉 "전부 NOT NULL", object_representation_sr.c:4712-4719).
  이 정의는 서버측 `btree_get_rkey_btid`, `locator_add_or_remove_index_internal`(:8042),
  `locator_update_index`(:8429)에서 쓰입니다.

**문제 시나리오**: `UNIQUE(x, y)`인데 `x`만 NOT NULL, `y`는 NULL 허용인 복합 UNIQUE를 가진 테이블을
HA 모드에서 REPLICATION=ON으로 CREATE합니다. DDL 검사는 "x가 NOT NULL이니 RK 있음"으로 판단해
생성을 **허용**합니다. 그러나 실제 DML이 일어나면 `or_is_replication_candidate_key`는 "y가 NULL
허용이니 RK 아님"으로 판단해 RK btid를 못 찾습니다. 마스터가 이 테이블의 행 복제 로그를 만들지
못하거나(무성 skip), 슬레이브가 행을 유일 식별하지 못해 데이터가 어긋납니다. 두 정의가 합의돼
있어야 하는데 어긋나 있습니다. (스펙 2C-4)

**제안**: 두 경로가 동일한 판정을 공유하도록 통일해야 합니다. 정합성상 올바른 정의는
`or_is_replication_candidate_key`의 "구성 컬럼 전부 NOT NULL"입니다. `IS_HA_REPLICATION_KEY_CONSTRAINT`가
`sm_has_non_null_attribute`(하나라도) 대신 "전부 NOT NULL"을 검사하도록 고쳐야 합니다.

---

## 문제 5

**[심각도: 중요] `log_ha_repl_fk_ref_all_replicated()` — PK가 없는 참조 테이블에서 `pk_c->name` NULL 역참조 크래시**

**위치**: `src/query/execute_schema.c:9837-9839`

**로직 설명**: rkcheck의 FK 검사에서, FK가 참조하는 테이블이 복제 대상이 아니면 위반으로
기록합니다. 그 출력 로직이
`DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));`(:9837)로
참조 테이블의 PK를 찾은 뒤, 곧바로 `pk_c->name`을 `fprintf`에 씁니다(:9839).
`db_constraint_find_primary_key`는 PK가 없으면 NULL을 반환합니다.

**문제 시나리오**: 이 기능의 핵심 전제가 "RK = PK **또는** NOT NULL UNIQUE"입니다. 따라서 참조
테이블이 PK 없이 NOT NULL UNIQUE만 가진 채 FK의 대상이 될 수 있습니다(CUBRID는 UNIQUE 키를
FK 대상으로 허용). 이 경우 `pk_c`가 NULL이 되어 `pk_c->name`에서 즉시 크래시합니다. 하필 이 코드는
HA 기동 전 사전 점검(rkcheck)에서 도는데, 점검 도중 유틸리티가 죽으면 사용자는 원인 파악이 어렵고
HA 기동 절차가 통째로 막힙니다.

**제안**: `pk_c`가 NULL이면 PK 대신 RK로 쓰인 UNIQUE 제약명을 찾아 출력하거나, 최소한 NULL 검사 후
대체 문자열(예: 제약명 미상 표기)을 쓰도록 방어해야 합니다.

---

## 문제 6

**[심각도: 중요] rkcheck — `fopen` 실패 시 NULL `fp`를 그대로 `fprintf`에 넘겨 크래시**

**위치**: `src/executables/util_cs.c:3320`(`fp = open_violation_list_file(...)`), 이후 `:3332`, `:3333`, `:3348` 등

**로직 설명**: `open_violation_list_file()`는 내부적으로 `fopen(file_path, "w")` 결과를 그대로
반환합니다(util_cs.c:2856-2864, `return fopen (file_path, "w");`). rkcheck는
`fp = open_violation_list_file(...)`(:3320) 후 **NULL 검사 없이** `PRINT_SECTION_TITLE (fp, ...)`
(→ `fprintf(fp, ...)`, :3332), `check_repl_constraint_violations(classes, fp, ...)`
(→ 위반마다 `fprintf(fp, ...)`, :3333)를 호출합니다. 정작 함수 끝에서는 `if (fp != NULL) fclose (fp);`로
NULL 가능성을 인지하고 있으면서, 앞의 사용처는 보호하지 않습니다.

**문제 시나리오**: 로그 디렉터리 권한 문제, 경로 길이 초과, 디스크 풀 등으로 `fopen`이 NULL을
반환하면, 첫 `PRINT_SECTION_TITLE(fp, ...)`에서 NULL 스트림에 `fprintf`하여 크래시합니다. HA 기동
경로(`us_hb_process_start` → rkcheck)에서 터지면 기동이 비정상 종료됩니다.

**제안**: `fp == NULL`이면 에러 메시지를 남기고 정리 후 실패 반환해야 합니다. 파일 없이 stdout으로
폴백하는 것도 대안입니다.

---

## 문제 7

**[심각도: 중요] `REPLICATION`이 예약어가 되어 기존 `replication` 식별자를 깨뜨린다(T-5)**

**위치**: `src/parser/csql_lexer.l:918`(REPLICATION 토큰 반환),
`src/parser/csql_grammar.y:1669`(`%token <cptr> REPLICATION`), 비예약 identifier 목록 `:20880-20883` 부근

**로직 설명**: 렉서가 `replication`을 전용 토큰 `REPLICATION`으로 반환합니다(:918). 그런데
이웃 비예약 키워드들(RESPECT :20880, RETAIN :20881, REUSE_OID :20882, REVERSE :20883)은 모두
비예약 identifier 규칙에 `{{ SET_CPTR_2_PTNAME(...) }}`로 등록돼 있어 따옴표 없이 식별자로도 쓸 수
있습니다. 반면 **REPLICATION은 이 목록에 없습니다**(해당 구간 grep 결과 부재 확인).

**문제 시나리오**: 기존 스키마에 `replication`이라는 이름의 컬럼이나 테이블이 있으면,
`SELECT replication FROM t;` 같은 쿼리가 이번 변경 이후 문법 에러가 납니다. 업그레이드 시 조용한
하위 호환 회귀입니다.

**제안**: `csql_grammar.y`의 비예약 identifier 규칙(20880 부근)에
`| REPLICATION { SET_CPTR_2_PTNAME(...) }`를 추가해 이웃 키워드들과 동일하게 식별자로도 허용해야
합니다.

---

## 문제 8

**[심각도: 보통] `find_index_catalog_class()`는 죽은 코드(정의만 있고 호출 없음)**

**위치**: `src/object/schema_template.c:5134` (정의), `:120` (forward 선언)

**로직 설명**: `static MOP find_index_catalog_class (const char *index_name)`(:5134)와 forward
선언(:120)이 있는데, 전 트리 grep 결과 **어디서도 호출되지 않습니다**(선언·정의 2곳이 전부).
static이라 파일 밖에서도 못 부릅니다.

**문제 시나리오**: squash 재적용 과정에서 어떤 호출부가 빠지고 함수 정의만 남은 것으로 보입니다.
`-Wunused-function` 경고 대상이고, 읽는 사람에게 "어디서 쓰이나?" 하는 혼란을 줍니다.

**제안**: 실제로 필요 없으면 삭제, 필요하면 호출부를 복구해야 합니다.

---

## 문제 9

**[심각도: 보통] `or_class_is_replication_on()`의 매직 넘버 32 + 잘못된 주석 이름**

**위치**: `src/base/object_representation_sr.c:785`

**로직 설명**: `int replication_off_flag = 32; /* SM_CLASSFLAG_REPLICATION_OFF = 32 */`(:785)로 플래그
값을 하드코딩합니다. 실제 enum 이름은 `SM_CLASSFLAG_DATA_REPLICATION_OFF`인데 주석은
**옛 이름 `SM_CLASSFLAG_REPLICATION_OFF`**(#6477에서 이미 개명됨)를 가리킵니다. 서버측 파일이라
클라이언트 SM enum을 직접 include하기 어려워 리터럴을 쓴 사정은 이해하지만, 값과 이름이 코드에서
분리돼 있습니다.

**문제 시나리오**: 누군가 `SM_CLASSFLAG_DATA_REPLICATION_OFF` 값을 바꾸면(플래그 재배치 등) 이
리터럴 32는 조용히 어긋나 복제 판정이 통째로 틀어집니다. 컴파일러가 잡아주지 못합니다.

**제안**: 공용 상수 헤더에 값을 한 번만 정의해 양쪽이 공유하거나, 최소한 주석을 현재 이름
(`SM_CLASSFLAG_DATA_REPLICATION_OFF`)으로 고치고 `static_assert`로 값 일치를 강제해야 합니다.

---

## 문제 10

**[심각도: 보통] TRUNCATE 복제 판정이 REPLICATION=OFF를 무시한다**

**위치**: `src/query/execute_statement.c:342` (`truncate_need_repl_log`), 호출부 `:16674`

**로직 설명**: `truncate_need_repl_log()`는 대상 테이블에 RK가 있는지
(`classobj_find_cons_replication_key`, :376)만 확인해 있으면 `true`(복제 로그 필요)를 반환합니다.
`SM_CLASSFLAG_DATA_REPLICATION_OFF`(테이블의 복제 옵션)는 검사하지 않습니다.

**문제 시나리오**: REPLICATION=OFF로 만든 테이블이라도 RK(PK 또는 NOT NULL UNIQUE)가 있으면
`TRUNCATE t;`가 복제 로그를 남깁니다(do_replicate_statement PT_TRUNCATE 분기, :16673-16682).
일반 DML은 복제 클래스 게이트로 OFF를 걸러내는데, TRUNCATE 경로만 이 게이트가 없어 OFF 테이블의
TRUNCATE가 슬레이브로 전파됩니다. #6826이 "PK만 보던 것을 RK로 확장"할 때 REPLICATION 옵션 검사를
함께 넣지 않은 누락입니다. (스펙 2m-4)

**제안**: `sm_is_replication_class(class_mop)`(또는 플래그 직접 검사)를 조건에 추가해 OFF 테이블은
`false`를 반환하도록 해야 합니다.

---

## 문제 11

**[심각도: 보통] `do_promote_partition()` — NOT NULL UNIQUE가 2개 이상이면 두 번째부터 플래그가 지워져 속성/프로퍼티 불일치**

**위치**: `src/query/execute_schema.c:7880` (함수), `:7944-7959`(속성 루프), `:7976-7984`(프로퍼티 정리)

**로직 설명**: 승격 시 속성 루프가
`if (!has_notnull_unique && has_notnull_unique_constraints (smattr)) has_notnull_unique = true;
else { UNIQUE/REVERSE_UNIQUE 플래그 제거 }`(:7948-7956) 구조입니다. 즉 **첫 번째** NOT NULL UNIQUE
속성만 플래그를 보존하고, `has_notnull_unique`가 true가 된 이후의 두 번째 NOT NULL UNIQUE 속성은
`else`로 빠져 UNIQUE 플래그가 제거됩니다. 반면 프로퍼티 정리부는
`if (!has_notnull_unique) drop UNIQUE/REVERSE_UNIQUE;`(:7978)라서, NOT NULL UNIQUE가 하나라도 있으면
UNIQUE 프로퍼티 리스트(두 제약 모두 포함)는 통째로 보존됩니다.

**문제 시나리오**: 서로 다른 두 개의 NOT NULL UNIQUE 제약을 가진 파티션을 일반 테이블로 승격하면,
두 번째 UNIQUE는 **속성 플래그는 제거됐는데 프로퍼티 리스트에는 남는** 불일치가 생깁니다. 이후
그 제약을 참조하는 로직에서 상태가 어긋날 수 있습니다.

**제안**: RK로 하나만 남기는 게 의도라면 프로퍼티도 함께 정리하고, 원래 UNIQUE 제약을 모두
보존해야 한다면 `!has_notnull_unique` 가드를 빼고 NOT NULL UNIQUE 속성 전부의 플래그를 유지해야
합니다. 속성 플래그와 프로퍼티 리스트가 항상 같은 결론이 되도록 맞춰야 합니다.

---

## 문제 13

**[심각도: 보통] `is_replication_class` 카탈로그 컬럼이 db_class 뷰 중간에 삽입됨(위치 기반 파싱 위험)**

**위치**: `src/object/schema_system_catalog_install.cpp:1313`,
`src/object/schema_system_catalog_install_query_spec.cpp`

**로직 설명**: 새 컬럼 `is_replication_class`가 db_class 뷰의 **끝이 아니라** `is_system_class`(:1312)와
`tde_algorithm`(:1314) 사이에 삽입됐습니다.

**문제 시나리오**: `SELECT * FROM db_class`를 컬럼 순서(위치)에 의존해 파싱하는 기존 클라이언트·도구는
`tde_algorithm` 이후 컬럼이 한 칸씩 밀려 오작동합니다. 시스템 카탈로그 뷰는 "새 컬럼은 항상 끝에
추가"가 안전한 관례입니다. (스펙 2m-8)

**제안**: 특별한 이유가 없으면 컬럼을 뷰 끝으로 옮기거나, 이미 배포된 인터페이스라 불가피하다면
릴리스 노트에 위치 변경을 명시해야 합니다.

---

## 문제 14

**[심각도: 보통] 주석/시그니처 불일치 (rename·copy-paste 흔적)**

**위치**:
- `src/query/execute_schema.c:9851` — `check_ha_repl_constraint()` 헤더 주석이 존재하지 않는 파라미터
  `repl_opt(in)`을 설명하지만, 실제 시그니처는 `(DB_OBJECT * class_obj)`(:9861) 하나뿐.
- `src/query/execute_schema.c:9805-9816` — `log_ha_repl_fk_ref_all_replicated()` 헤더 주석이
  존재하지 않는 파라미터 `do_print(in)`을 설명하지만, 실제 시그니처는
  `(DB_OBJECT * class_obj, FILE * fp)`(:9818).
- `src/object/class_object.c:542` — 함수 헤더 주석은 `classobj_copy_pk_unique_constraints()`라고
  적혀 있으나 실제 함수명은 `classobj_copy_pk_and_uk_notnull_constraints()`(:561).

**로직 설명/시나리오**: 코드는 동작하지만, 주석이 옛 이름·있지도 않은 파라미터를 가리켜 처음 읽는
사람을 오도합니다. 특히 없는 파라미터를 "in"으로 설명하면 잘못된 호출 관례를 유추하게 됩니다.

**제안**: 주석을 현재 시그니처·함수명에 맞게 갱신해야 합니다. (신입 관점: 이런 불일치가 여러 개면
"이 파일은 리팩토링 도중"이라는 인상을 줘 신뢰가 떨어집니다.)

---

## 문제 15

**[심각도: 보통] `do_alter_change_replication()`이 엉뚱한 savepoint 이름을 재사용(copy-paste)**

**위치**: `src/query/execute_schema.c:11730` (`do_alter_change_replication`), savepoint 상수
`UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`(:81 정의 `"cHANGEtBLcOMMENT"`), 사용 `:11747`, `:11823`

**로직 설명**: 복제 옵션 변경 함수가 `tran_system_savepoint(UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT)`(:11747)와
`tran_abort_upto_system_savepoint(UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT)`(:11823)를 씁니다. 이름은
"CHANGE TABLE COMMENT"용인데(같은 상수를 `do_alter_change_tbl_comment`가 :11505/:11571에서 사용)
실제로는 REPLICATION 변경에 쓰입니다.

**문제 시나리오**: 기능상 롤백은 동작하지만, savepoint 이름이 실제 작업과 무관해 디버깅·로그 추적
시 혼란을 줍니다. `do_alter_change_tbl_comment`에서 복붙한 흔적으로 보입니다. 동일 트랜잭션에서
comment 변경과 replication 변경이 겹치면 같은 이름의 savepoint를 공유해 미묘한 롤백 범위 혼동
가능성도 있습니다.

**제안**: `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 같은 전용 상수를 정의해 쓰는 게 안전합니다.

---

## 문제 16

**[심각도: 보통] `get_print_flags`는 선언만 있고 정의는 `get_repl_check_flags` — 불일치 죽은 선언**

**위치**: `src/executables/util_cs.c:187` (forward 선언), `:2867` (실제 정의는 `get_repl_check_flags`)

**로직 설명**: 파일 상단 forward 선언은 `static int get_print_flags (UTIL_ARG_MAP * arg_map);`(:187)인데,
실제 정의·사용되는 함수는 `get_repl_check_flags`(:2867, rkcheck에서 :3287 호출)입니다.
`get_print_flags`는 정의도 호출도 없습니다.

**문제 시나리오**: rename 도중 선언만 옛 이름으로 남은 흔적입니다. static 함수의 미사용 선언은
컴파일은 되지만 코드 독해를 방해하고, 누군가 `get_print_flags`를 호출하면 링크 에러가 납니다.

**제안**: `get_print_flags` 선언을 삭제하고, 필요하면 `get_repl_check_flags`의 forward 선언으로
교체해야 합니다.

---

## 문제 17

**[심각도: 보통] Failover/switchover/failback 경로가 rkcheck 검증을 우회한다**

**위치**: `src/executables/util_service.c:3969` (`us_hb_process_start`에서 `us_hb_process_rkcheck` 호출),
`:5042` (수동 `hb rkcheck`)

**로직 설명**: `us_hb_process_rkcheck()`(:3194)는 `us_hb_process_start()`(즉 `cubrid hb start`) 경로(:3969)와
수동 `hb rkcheck` 명령(:5042)에서만 호출됩니다. 실제로 마스터가 바뀌는 failover/switchover/failback
경로에는 이 재검증이 걸려 있지 않습니다(전 트리에서 해당 경로의 재검증 호출 없음).

**문제 시나리오**: 기동 시점에는 RK 제약을 만족했더라도, 운영 중 RK가 사라지는 변경(문제 2·3의
게이트 누락으로 통과된 경우 등)이 있었다면, 이후 failover로 슬레이브가 마스터로 승격될 때 아무런
검증 없이 승격됩니다. RK를 잃은 테이블이 있으면 승격 직후 복제가 깨진 상태로 운영됩니다. (스펙 2C-2)

**제안**: 역할 전환 경로에도 최소한의 RK/FK 재검증(또는 경고)을 연결하는 것을 검토해야 합니다.

---

## 문제 18

**[심각도: 보통] ADD PRIMARY KEY가 RK를 UK→PK로 조용히 재할당(경고 없음)**

**위치**: RK 선택 로직 `src/base/object_representation_sr.c:4694`(PK를 UNIQUE보다 우선),
`src/storage/btree.c:8294` (첫 후보 채택)

**로직 설명**: RK 선택은 클래스 인덱스 배열을 순회하며 첫 번째 복제 후보 인덱스를 채택하고,
`or_is_replication_candidate_key`가 PK(BTREE_PRIMARY_KEY)를 UNIQUE보다 앞서 판정하므로 PK가 있으면
PK가 RK가 됩니다. 따라서 NOT NULL UNIQUE가 RK이던 테이블에 나중에 PK를 추가하면 RK가 조용히 새
PK로 넘어갑니다. 관련 NOTICE/WARNING 에러코드는 추가되지 않았습니다(cubrid.msg에 1375~1378만 신설).

**문제 시나리오**: 운영자가 "RK가 여전히 그 UNIQUE"라고 생각하고 PK를 추가했는데, 복제의 행 식별
기준이 말없이 바뀝니다. 마스터/슬레이브가 같은 규칙을 쓰므로 즉시 깨지진 않지만, 이후 그 PK를
다시 바꾸는 등의 시나리오에서 운영자의 오해가 사고로 이어질 수 있습니다. (스펙 2M-12)

**제안**: RK가 바뀌는 DDL에서 최소한 NOTICE/WARNING을 남기거나, 현재 RK를 조회할 수 있는 수단을
제공해야 합니다.

---

## 문제 19

**[심각도: 사소] rkcheck의 `db_name@localhost` 조합에서 버퍼 절단 위험(TODO 미해결)**

**위치**: `src/executables/util_cs.c:3273`(`char tmp_database_name[CUB_MAXHOSTNAMELEN];`),
`:3299`(TODO 주석), `:3300`(`snprintf(..., "%s@localhost", database_name)`)

**로직 설명**: 코드 자신이 `/* TODO: Handle truncation explicitly here ... */`(:3299) 주석을 달아둔
지점입니다. `CUB_MAXHOSTNAMELEN`은 256이고, 최대 길이 DB 이름(255) + `"@localhost"`(10)는 이를 넘겨
`snprintf`(:3300)가 절단합니다.

**문제 시나리오**: 아주 긴 DB 이름에서 이름이 잘려 엉뚱한 DB에 접속하거나 접속 실패합니다.
#6934에서 이미 인지됐지만 TODO로 남겨둔 상태입니다.

**제안**: 버퍼를 충분히 키우거나(이름 최대 길이 + suffix), 절단을 감지해 명시적 에러를 반환해야
합니다.

---

## 문제 20

**[심각도: 사소] utils.msg의 rkcheck 사용법 메시지 블록 말미 형식 오류**

**위치**: `msg/en_US.utf8/utils.msg` (`$set 61 MSGCAT_UTIL_SET_RKCHECK` 블록 끝)

**로직 설명**: 마지막 옵션 줄(`-f, --fk-check ...\n`)이 개행으로 끝난 뒤, **공백 4칸만 있는 줄**이
오고 파일 끝에 개행이 없습니다(git diff `\ No newline at end of file` 및 `tail -c` 확인:
`...violations\n`(리터럴) + 실제 개행 `0a` + 공백 4바이트로 EOF). 다른 메시지 블록은 마지막 줄을
`\`(계속) 또는 `\n`으로 깔끔히 마무리합니다.

**문제 시나리오**: 메시지 카탈로그 컴파일은 통과하겠지만, 사용법 출력 끝에 의도치 않은 공백 줄이
붙거나 파서에 따라 경고가 날 수 있습니다. ko_KR/utils.msg도 동일한지 확인이 필요합니다.

**제안**: 말미 공백 줄을 제거하고 파일 끝에 개행을 넣어야 합니다.

---

## 문제 21

**[심각도: 사소] `UTIL_INDEX` enum에 RKCHECK를 LOGFILEDUMP 앞에 삽입(끝에 추가 관례 위반)**

**위치**: `src/executables/utility.h:830` 부근 (`... MEMMON, RKCHECK, LOGFILEDUMP`)

**로직 설명**: 기존에 마지막이던 `LOGFILEDUMP`(:831) 앞에 `RKCHECK`(:830)를 끼워 넣어 `LOGFILEDUMP`의
enum 값이 한 칸 밀렸습니다.

**문제 시나리오**: `UTIL_INDEX` 값이 어딘가에서 배열 첨자나 직렬화 값으로 쓰인다면 `LOGFILEDUMP`가
어긋납니다(현재는 맵 탐색으로 쓰이는 것으로 보여 즉각적 문제는 낮음). enum은 "새 항목은 끝에
추가"가 안전합니다.

**제안**: `RKCHECK`를 `LOGFILEDUMP` 뒤(목록 끝)로 옮기는 것을 권합니다.

---

## 문제 22

**[심각도: 사소] VIEW에도 `REPLICATION=ON`이 무의미하게 출력된다**

**위치**: `src/object/object_printer.cpp:1138-1140` (`describe_class`),
`src/executables/unload_schema.c:1794-1796` (`emit_schema`)

**로직 설명**: 두 곳 모두 `sm_is_replication_class(op)`가 true면 `", REPLICATION=ON"`을 출력합니다.
`sm_is_replication_class`는 `!(flags & SM_CLASSFLAG_DATA_REPLICATION_OFF)`이므로, VIEW(VCLASS)는 이
플래그가 설정될 일이 없어 항상 true → 뷰의 SHOW CREATE/unload 출력에도 `REPLICATION=ON`이 붙습니다.
정작 rkcheck·복제 로직은 뷰를 복제 대상에서 제외합니다.

**문제 시나리오**: 뷰 정의를 unload한 스크립트에 무의미한 `REPLICATION=ON`이 섞여 나오고, loaddb로
되불러올 때 뷰 생성 문법이 이 옵션을 받는지에 따라 에러가 날 수도 있습니다. 최소한 사용자에게
혼란입니다. (스펙 M-2와 연결)

**제안**: 뷰(class_type이 VCLASS)일 때는 REPLICATION 표기를 생략하도록 분기해야 합니다.

---

## 문제 23 (신규 — #7678 동기화 델타)

**[심각도: 보통] SBR 판정 신규 코드 `is_replication_class()`가 `db_find_class()` NULL에 `assert(false)` — #7697이 방금 없앤 안티패턴의 재등장**

**위치**: `src/query/execute_statement.c:3201`(`is_replication_class` 정의), `:3210`(`db_find_class`),
`:3213`(`assert (false)`)

**로직 설명**: #7678이 SBR(문장 기반 복제) 판정을 위해 새로 추가한 파일 로컬 함수입니다.

```c
static bool
is_replication_class (const char *classname)
{
  DB_OBJECT *class_obj;
  if (classname == NULL) return false;
  class_obj = db_find_class (classname);
  if (class_obj == NULL) { assert (false); return false; }
  return sm_is_replication_class (class_obj);
}
```

`db_find_class()`(compat/db_info.c:133 → `db_find_class_with_purpose` → `sm_find_class_with_purpose`)는
(1) 미접속(`CHECK_CONNECT_NULL`), (2) 클래스 미발견, (3) 권한/기타 에러 시 **정상적으로 NULL을
반환**합니다. 그런데 이 함수는 NULL을 "불가능"으로 보고 `assert(false)`(:3213)로 처리합니다. 이는
#7697이 `heap_get_class_repl_on()`에서 방금 제거한 "조회 실패에 `assert(false)`" 안티패턴과 정확히
같은 형태입니다(#7697 커밋 메시지: "이 함수만 fetch 실패를 assert(false)로 '불가능'으로 취급").

호출 경로: `do_statement`/`do_execute_statement`(:3405, :4113) → `is_data_repl_log_enabled`(:3304) →
`spec_has_replication_class` → `is_replication_class`. `classname`은
`get_spec_classname(spec)`(:3223)이 돌려주는 `spec->info.spec.entity_name->info.name.original`, 즉
사용자가 문장에 적은 **원본 이름**입니다.

**문제 시나리오**: 이 코드는 클라이언트(CAS) 측 do_statement에서 돕니다.
- 동시 DDL: 세션 A가 REPLICATION 대상 테이블에 `USE_SBR` 힌트로 DML을 실행하는 사이, 세션 B가 그
  테이블을 DROP하면 `db_find_class`가 NULL을 반환합니다. 디버그 빌드에서는 `assert(false)`로 CAS가
  abort합니다(릴리스에서는 false 반환 후 `spec_has_replication_class`의 flat_entity_list 경로로
  흐르지만, entity_name 경로 자체가 취약합니다).
- `entity_name.original`이 클래스로 곧바로 해석되지 않는 경우(예: 시노님을 통한 참조 등)에도
  `db_find_class`가 NULL을 낼 수 있습니다.

즉 #7697이 손보고 있던 바로 그 파일 계열에서, 같은 실수(정당하게 실패 가능한 조회에 대한
`assert(false)`)가 새 코드로 다시 들어왔습니다.

**제안**: NULL을 `assert(false)` 대신 정상 경로로 처리해야 합니다(예: `return false;` 만 두거나,
필요 시 에러코드를 상위로 전파). `spec_has_replication_class`가 어차피 resolved된 `flat_entity_list`의
`db_object`로 `sm_is_replication_class`를 재확인하므로, entity_name 기반 조회 자체를 없애고
flat_entity_list만 신뢰하는 것도 방법입니다. (#7697과 동일 취지)

---

## 조사 종료 선언

여기서 2차 재리뷰를 마칩니다.

**재검증 결과**
- 1차 문제 1(치명, `heap_is_replication_class` 인터럽트 삼킴)의 근본 원인은 #7697이
  `heap_get_class_repl_on()`(int 에러코드 + out-param)로 교체하고 호출부에서 `goto error` 전파를
  넣어 사라졌습니다 — 본문에서 제외.
- 1차 문제 12(성능·조건 순서 불일치)는 #7697/#7678의 재정렬로, INSERT/DELETE·UPDATE 두 경로 모두
  `or_is_replication_candidate_key`를 먼저 검사한 뒤에야 클래스 레코드를 조회하도록 바뀌어 해소됐습니다
  (클래스 레코드 fetch가 후보키에 대해서만 발생) — 본문에서 제외.
- 나머지 1차 문제(2~11, 13~22)는 새 HEAD에서 코드·위치를 재확인해 **전부 유지**됩니다(위치 갱신 완료).
  해당 파일들(execute_schema.c, util_cs.c, class_object.c, object_representation_sr.c, csql_grammar.y,
  utils.msg 등)은 동기화 델타가 건드리지 않아 문제가 그대로 남아 있습니다.

**신규 발굴**
- #7678이 새로 넣은 SBR 판정 코드(execute_statement.c의 `is_replication_class`,
  `spec_has_replication_class`, `is_data_repl_log_enabled`, `pt_spec_repl_class_walk`)와 checksumdb의
  suppress-repl 브래킷을 로직 추적했습니다. 유효한 신규 결함은 문제 23(assert(false) 안티패턴 재등장)
  1건입니다.
- checksumdb의 `db_set_suppress_repl_on_transaction(false)` 실패 시 억제 플래그 잔류 가능성도
  살폈으나, 이 API는 `CHECK_CONNECT_ERROR`(미접속)에서만 실패하고 그 경우 전체 실행이 실패하므로
  실질적으로 발현되지 않는다고 판단해 지적에서 제외했습니다(억지 지적 회피).
- `is_data_repl_log_enabled`의 default 경로(INSERT/UPDATE/DELETE 외 = DDL·DROP VARIABLE)는 true를
  반환해 기존과 동일하게 복제되므로 회귀가 아님을 확인했습니다.

**더 없다고 보는 근거**
- 정합성의 최종 확인(마스터/슬레이브 실제 어긋남 등)은 정적 분석 범위를 넘어 런타임 테스트가
  필요합니다 — 문제 4·10은 코드 근거는 확정했고 영향 재현은 QA로 넘깁니다.

---

## 심각도별 집계

| 심각도 | 개수 | 문제 번호 |
|---|---:|---|
| 치명 | 0 | — |
| 중요 | 6 | 2, 3, 4, 5, 6, 7 |
| 보통 | 11 | 8, 9, 10, 11, 13, 14, 15, 16, 17, 18, 23 |
| 사소 | 4 | 19, 20, 21, 22 |
| **계** | **21** | |

## 재검증 요약

| 구분 | 수 | 비고 |
|---|---:|---|
| 유지 | 20 | 문제 2~11, 13~22 (위치 갱신) |
| 해소(동기화) | 1 | 문제 12 (#7697/#7678 재정렬) |
| 신규 | 1 | 문제 23 (#7678 SBR 판정 코드) |
