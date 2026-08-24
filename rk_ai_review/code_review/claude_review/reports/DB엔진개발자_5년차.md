# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 5년차 관점

> **2차 재리뷰 (기준 HEAD `734f4959d`, feature/CBRD-26246-develop)**
> upstream 동기화(#7678 `3b6ebd1a9`, #7697 `9e094324b`) 이후 재검증. 1차 리포트의 19개 문제를 새 HEAD에서 유지/해소/폐기로 분류하고, 동기화 델타와 전체 diff에서 신규 문제를 추가 발굴했다.
> 결과: 유지 16건 · 해소 3건(문제 1·6·15) · 폐기 0건 · 신규 0건.

## 페르소나 소개

저는 DBMS 엔진을 5년째 만지는 개발자입니다. 제 눈이 가장 먼저 가는 곳은 "정상 경로"가 아니라 **에러 경로와 희귀 조합**입니다. 즉 실패가 중간에 터졌을 때 자원(락·트랜잭션·파일·메모리)이 제대로 풀리는가, 경계값(NULL·빈 목록·최대 길이)에서 죽지 않는가, 여러 절(clause)이 한 문장에 섞이거나 동시 실행될 때 검사가 새지 않는가를 봅니다. 복제(replication) 기능은 "마스터에서 로그를 남기느냐 마느냐"라는 **단 한 번의 판정**이 슬레이브 정합성을 좌우하기 때문에, 그 판정이 조용히(silently) 틀리는 지점을 특히 경계합니다.

## 총평 (2차)

1차에서 가장 무겁게 지적했던 **"판정 함수가 실패(에러)를 성공(false)으로 뭉개는" 설계 결함**(구 문제 1, `heap_is_replication_class()`의 KILL QUERY 삼킴)은 이번 동기화로 들어온 **#7697에서 근본 수정**되어 해소됐습니다. 함수가 `int`(에러코드) 반환 + out-parameter 구조로 바뀌었고, 호출부가 `&&` 사슬에서 검사를 분리해 `error_code != NO_ERROR`면 `goto error`로 인터럽트를 트랜잭션에 전파합니다. 이에 딸린 성능 지적(구 문제 6, 인덱스 루프 안 매 반복 heap 조회)도 판정 호출이 "복제 후보 키를 찾았고 아직 미복제일 때"로 게이팅되며 자연히 해소됐습니다. checksumdb의 복제 억제 해제 반환값 미검사(구 문제 15)는 **#7678에서 반환값을 캡처·전파**하도록 수정되어 해소됐습니다.

다만 **정확성에 직접 영향을 주는 나머지 결함들은 그대로 살아 있습니다.** 다중 절 ALTER 게이트가 엉뚱한 노드(첫 절)를 보는 버그(문제 2), 부분 NOT NULL 복합 UNIQUE의 RK 오인(문제 3), 서버 측 RK 후보 판정의 필터/함수 인덱스 미검사(문제 4), rkcheck의 파일 포인터 NULL 미검사 크래시(문제 5)가 모두 유지됩니다. 아래에 심각도 순으로 정리합니다(번호는 1차 유지).

용어를 미리 풀어둡니다. **RK(Replication Key)**는 슬레이브가 어떤 행을 고칠지 찾는 열쇠로, PK이거나 "모든 구성 컬럼이 NOT NULL인 UNIQUE"여야 각 행을 유일하게 지목할 수 있습니다. **SBR**은 문장 그대로 슬레이브에서 재실행하는 복제(Statement-Based), **RBR**은 바뀐 행 이미지를 실어 보내는 복제(Row-Based)입니다.

---

## 문제 2
**[심각도: 중요] 다중 절 ALTER의 RK 재검증 게이트가 "현재 절"이 아니라 "첫 절"의 코드를 본다**

- 위치: `src/query/execute_schema.c:2051`

로직 설명: `do_alter()`는 `for (crt_clause = alter; ...; crt_clause = crt_clause->next)`로 각 ALTER 절을 순회하며 루프 진입 시 `const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;`(현재 절의 코드)를 뽑아 씁니다. 그런데 RK 재검증 필요 여부를 켜는 게이트는

```
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
```

처럼 `crt_clause`(현재 절)나 지역변수 `alter_code`가 아니라 **`alter->info.alter.code`(리스트의 머리 노드=첫 절)**를 검사합니다. 이 값은 루프 내내 바뀌지 않는 상수입니다. 같은 루프의 RENAME 처리(:2006)는 올바르게 `crt_clause`를 써서 `entity_name`을 절마다 갱신하고 있어 이 비대칭이 실수임을 강하게 시사합니다.

문제 시나리오: `ALTER TABLE t RENAME COLUMN a AS b, DROP CONSTRAINT uk;` 처럼 **첫 절이 제약과 무관(PT_RENAME_ATTR_MTHD)**이고 **뒤 절에서 RK를 떨어뜨리는(PT_DROP_CONSTRAINT)** 조합을 실행하면, 게이트가 첫 절 코드만 보므로 `need_check_repl_constraint`가 켜지지 않고 → 문 끝의 `check_ha_repl_constraint()`가 호출되지 않습니다. 즉 마지막 남은 RK를 제거하는 멀티 절 ALTER가 HA 제약 검사를 우회합니다.

제안: 게이트를 `IS_REPL_CONSTRAINT_RELATED_ALTER (alter_code)`로 바꿔 현재 절 기준으로 판정해야 합니다.

---

## 문제 3
**[심각도: 중요] 부분 NOT NULL 복합 UNIQUE가 RK로 인정되어 슬레이브 행 유일 식별이 깨진다**

- 위치: `src/object/class_object.c:95`(`IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로) → `src/object/schema_manager.c:16114`(`sm_has_non_null_attribute`)

로직 설명: RK 후보 판정 매크로는 `type == PRIMARY_KEY || (UNIQUE_FAMILY && sm_has_non_null_attribute((c)->attributes))`입니다. 그런데 `sm_has_non_null_attribute()`는 주석부터 "**at least one** non null constraint"라고 적혀 있고 실제로도 구성 컬럼 배열을 돌다가 **하나라도** NOT NULL이면 곧장 1을 반환합니다(:16121-16126). 즉 "모든 구성 컬럼이 NOT NULL"을 요구하지 않습니다. `classobj_has_class_repl_key_constraint()`(RK 존재 검사)와 `classobj_find_cons_replication_key()`가 모두 이 매크로에 의존합니다.

문제 시나리오: `UNIQUE(x, y)`에서 `x`는 NOT NULL, `y`는 NULL 허용인 복합 UNIQUE 하나만 가진 복제 테이블을 만듭니다. 매크로는 "y가 NULL 허용"임을 무시하고 이 UNIQUE를 RK로 승인합니다. UNIQUE 인덱스는 NULL이 섞인 키의 중복을 막지 않으므로, `(1, NULL)`과 `(1, NULL)` 같은 행이 공존할 수 있습니다. 슬레이브가 UPDATE/DELETE 복제를 적용할 때 이 키로 대상 행을 찾으면 여러 행에 걸리거나 못 찾아 마스터-슬레이브가 어긋납니다.

제안: 매크로를 "UNIQUE의 **모든** 구성 컬럼이 NOT NULL"로 강화해야 합니다. 서버 측 판정 `or_is_replication_candidate_key()`(object_representation_sr.c:4712-4719)는 이미 전 컬럼 `is_notnull` 검사를 하는데, 클라이언트 측 매크로만 느슨해 두 판정이 불일치합니다. (스펙 2C-4)

---

## 문제 4
**[심각도: 중요] `or_is_replication_candidate_key()`가 필터/함수 기반 UNIQUE·미완성 인덱스를 RK로 오인한다**

- 위치: `src/base/object_representation_sr.c:4694`

로직 설명: 서버 측 RK 후보 판정은 `index->type`이 PK면 true, UNIQUE면 모든 `atts`가 `is_notnull`인지만 봅니다(:4702-4721). `OR_INDEX`에는 `filter_predicate`(부분 인덱스)와 `func_index_info`(함수 기반 인덱스), 인덱스 빌드 상태 같은 필드가 있는데 이들을 전혀 확인하지 않습니다.

문제 시나리오: `CREATE UNIQUE INDEX ... ON t(col) WHERE col > 0`(부분 UNIQUE)이나 함수 기반 UNIQUE만 가진 복제 테이블은, 인덱스가 테이블의 **일부 행에만** 유일성을 보장합니다. 그런데도 이 인덱스가 RK로 선택되면(`btree_get_rkey_btid`가 이 btid를 고름), 필터 조건 밖의 행이나 함수 값이 겹치는 행은 슬레이브에서 유일하게 식별되지 않아 오적용/누락이 발생합니다.

제안: `filter_predicate != NULL`이거나 함수 기반이면 RK 후보에서 제외하고, 온라인 빌드 중(미완성) 인덱스도 배제해야 합니다. (스펙 2M-8)

---

## 문제 5
**[심각도: 중요] `rkcheck()`가 위반 목록 파일 포인터 NULL을 검사하지 않아 파일 열기 실패 시 크래시**

- 위치: `src/executables/util_cs.c:3320`(`fp = open_violation_list_file(...)`) → `:3332` 이하 `PRINT_SECTION_TITLE(fp, ...)`

로직 설명: `open_violation_list_file()`(:2856)은 `fopen(file_path, "w")`의 결과를 그대로 반환하며, 실패 시 `NULL`을 돌려줍니다. `rkcheck()`는 이 반환값을 `fp`에 받은 뒤 **NULL 검사 없이** 곧바로 `PRINT_SECTION_TITLE(fp, ...)`(매크로가 `fprintf((stream), ...)`, util_cs.c:92-97)와 `check_repl_constraint_violations(classes, fp, ...)`(내부에서 `fprintf(fp, ...)`)를 호출합니다.

문제 시나리오: 로그 디렉토리(`envvar_logdir_file`가 가리키는 경로)에 쓰기 권한이 없거나, 디스크가 가득 찼거나, 파일 수 제한에 걸리면 `fopen`이 NULL을 반환합니다. 그러면 `fprintf(NULL, ...)`로 널 포인터 역참조가 일어나 rkcheck가 죽습니다. rkcheck는 `cubrid hb start` 경로에서 자동 호출되므로, HA 기동 자체가 세그폴트로 실패합니다.

제안: `fp == NULL`이면 명확한 에러 메시지를 남기고 정상 종료 경로로 빠져야 합니다. 검사 결과를 파일 없이 stdout으로라도 낼지도 함께 정해야 합니다.

---

## 문제 7
**[심각도: 보통] `TRUNCATE`가 REPLICATION=OFF 테이블에서도 RK만 있으면 복제 로그를 남긴다**

- 위치: `src/query/execute_statement.c:342`(`truncate_need_repl_log`, RK 확인은 :376)

로직 설명: `truncate_need_repl_log()`는 `classobj_find_cons_replication_key(class_->constraints)`로 RK 존재 여부만 확인해 true/false를 반환합니다(:376-380). 클래스의 `SM_CLASSFLAG_DATA_REPLICATION_OFF`(복제 제외) 플래그는 보지 않습니다.

문제 시나리오: `REPLICATION=OFF`로 만든 테이블이라도 PK나 NOT NULL UNIQUE가 있으면(대개 있습니다) `TRUNCATE`가 복제 로그를 생성합니다. 그러면 복제에서 제외하려던 테이블의 TRUNCATE가 슬레이브에 전파되어, 사용자가 기대한 "이 테이블은 복제 안 함"과 어긋납니다. 일반 DML 경로(`locator_*`)는 `heap_get_class_repl_on` 게이트로 OFF 테이블을 걸러내는데 TRUNCATE만 이 게이트가 빠졌습니다.

제안: RK 존재 확인 앞에 `sm_is_replication_class`(또는 동등한 플래그 확인)를 두어 OFF면 즉시 false를 반환해야 합니다. (스펙 2m-4)

---

## 문제 8
**[심각도: 보통] DDL(SBR) 복제가 테이블 REPLICATION 플래그와 무관하게 무조건 재실행된다**

- 위치: `src/query/execute_statement.c:3345`(`is_data_repl_log_enabled`의 `default` 분기)

로직 설명: `is_data_repl_log_enabled()`는 INSERT/UPDATE/DELETE만 대상 spec의 복제 여부를 따지고(#7678에서 derived vclass·수정 대상 spec 기준으로 정교화됨), 그 외 문장 타입은 `default: return true;`(:3345-3346)로 무조건 "복제 허용"을 반환합니다. 이 함수는 `is_stmt_based_repl_type(statement)`가 참일 때 게이트로 쓰이는데, 그 함수는 **모든 DDL**과 `PT_DROP_VARIABLE`에 대해 true를 반환합니다(:396-405). 따라서 DDL·DROP_VARIABLE은 항상 default 경로로 빠집니다.

문제 시나리오: DDL이 `REPLICATION=OFF` 테이블을 겨냥하더라도 default 경로로 빠져 무조건 복제·재실행됩니다. 슬레이브에서 OFF 테이블 대상 DDL이 실패하면(예: OFF라 데이터가 비어 참조가 깨짐) 이를 격리할 경로가 없어 `fail_count`가 오르거나 어플라이어가 멈출 수 있습니다.

제안: default 분기가 무조건 true를 반환하기 전에, 그 문장이 실제로 겨냥하는 클래스의 복제 플래그를 확인하는 경로를 두어야 합니다. 최소한 어떤 문장 타입이 default로 빠지는지 명시적으로 열거하고 위험군을 분리하는 것이 안전합니다. (스펙 2C-6)

---

## 문제 9
**[심각도: 보통] `CREATE TABLE ... LIKE ... REPLICATION=OFF`에서 명시한 옵션이 조용히 무시된다**

- 위치: `src/query/execute_schema.c:10258`(create_like 분기) / `src/parser/semantic_check.c:8856`(create_like 검증)

로직 설명: `do_create_entity()`는 `create_like`이면 `is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF);`(:10260)로 **원본 테이블의 플래그만** 사용하고, `else`에서만 `IS_CREATE_STMT_SET_REPL_OPTION(tbl_opt_replication)`(사용자 명시 옵션, :10264)을 봅니다. 즉 LIKE 생성에서는 사용자가 적은 `REPLICATION` 옵션이 완전히 무시됩니다. semantic_check의 create_like 처리(:8856-8875)에도 "LIKE와 REPLICATION 동시 지정 시 에러"를 거는 코드가 없습니다.

문제 시나리오: 원본 `y`가 REPLICATION=ON일 때 `CREATE TABLE x LIKE y REPLICATION=OFF`를 실행하면, 사용자의 OFF 의도와 달리 `x`가 ON으로 생성되고 아무 경고도 나오지 않습니다. #6943 리뷰에서 "LIKE와 REPLICATION 동시 명시는 에러"로 규칙이 확정됐는데, 인라인 상속 로직만 반영되고 상충 거부는 누락된 것으로 보입니다.

제안: create_like이면서 `tbl_opt_replication != NULL`이면 semantic_check 단계에서 에러로 거부하거나, 최소한 명시 옵션을 우선 적용해야 합니다.

---

## 문제 10
**[심각도: 보통] `do_alter()`의 최종 RK 검사가 클래스 조회 실패를 성공으로 오인해 검사를 건너뛴다**

- 위치: `src/query/execute_schema.c:2061-2065`

로직 설명: 모든 절 처리 후 `need_check_repl_constraint`이면 `vclass = db_find_class(entity_name);` 한 뒤 `if (!sm_is_replication_class(vclass)) { return NO_ERROR; }`로 진행합니다. `sm_is_replication_class()`(schema_manager.c)는 인자가 NULL이거나 `au_fetch_class_force`가 실패하면 `assert(false)` 후 **`false`를 반환**합니다.

문제 시나리오: 멀티 절 ALTER 도중 이름 갱신 로직과 실제 스키마 상태가 어긋나거나, 권한/락 문제로 `db_find_class(entity_name)`가 NULL을 돌려주면, `sm_is_replication_class(NULL)`이 false를 반환 → "복제 대상 아님"으로 오인 → `return NO_ERROR`로 **RK 제약 검사를 조용히 건너뛰고 성공 처리**합니다. 릴리스 빌드에서는 assert도 무력화되어 흔적이 안 남습니다.

제안: `vclass == NULL`을 별도로 처리해 실제 에러(`er_errid()`)를 반환하고, 조회 성공 시에만 복제 여부로 분기해야 합니다.

---

## 문제 11
**[심각도: 보통] RK 재검증 게이트 목록에 MODIFY/CHANGE COLUMN·RENAME이 빠져 있다**

- 위치: `src/query/execute_schema.c:109`(`IS_REPL_CONSTRAINT_RELATED_ALTER`)

로직 설명: 재검증 대상 코드 목록은 `PT_ADD_ATTR_MTHD`, `PT_DROP_ATTR_MTHD`, `PT_DROP_CONSTRAINT`, `PT_DROP_PRIMARY_CLAUSE` 넷뿐입니다(:110-113). 다음 경로가 빠져 있습니다: `PT_CHANGE_ATTR`(MODIFY/CHANGE COLUMN — NOT NULL 해제나 타입 변경으로 RK 자격 상실 가능), `PT_RENAME_ENTITY`(그림자 스왑으로 OFF 테이블을 운영 이름 자리에 밀어넣기).

문제 시나리오: `ALTER TABLE t MODIFY x VARCHAR(10);`처럼 RK를 이루던 NOT NULL UNIQUE 컬럼의 NOT NULL 속성을 CHANGE/MODIFY로 없애면, 이 경로가 게이트에 없어 RK 재검사가 돌지 않고 → 복제 테이블이 RK 없는 상태로 남습니다. HA 기동 시 rkcheck가 뒤늦게 잡을 수는 있으나, 온라인 상태에서 즉시 차단되지 않습니다.

제안: 최소 `PT_CHANGE_ATTR`와 `PT_RENAME_ENTITY`를 목록에 추가해야 합니다. (스펙 C-9/2M-6/2m-3)

---

## 문제 12
**[심각도: 보통] `db_class` 뷰의 신규 컬럼 `is_replication_class`가 목록 중간에 삽입되어 위치 기반 접근을 흔든다**

- 위치: `src/object/schema_system_catalog_install.cpp:1313` / `src/object/schema_system_catalog_install_query_spec.cpp:74`

로직 설명: `is_replication_class` 컬럼이 `db_class` 컬럼 정의에서 `is_system_class`(:1312)와 `tde_algorithm`(:1314) **사이**에 삽입됐고, 뷰 쿼리(query_spec.cpp:73-75)에서도 동일하게 두 컬럼 사이에 삽입됐습니다. 시스템 카탈로그 뷰는 "새 컬럼은 항상 끝에 추가"가 관례인데, 중간 삽입은 뒤 컬럼들의 순서(ordinal position)를 모두 한 칸씩 밀어냅니다.

문제 시나리오: `SELECT *`의 컬럼 위치나 ordinal에 의존하는 도구/스크립트/드라이버 메타데이터 캐시가 있으면, 업그레이드 후 `tde_algorithm` 이후 컬럼을 잘못 읽습니다. 특히 JDBC `DatabaseMetaData` 경로가 `db_class`를 참조한다면 영향이 큽니다.

제안: 신규 컬럼을 뷰 정의 맨 끝으로 옮기는 것이 안전합니다. 이미 배포·문서화된 인터페이스라 유지가 불가피하다면, 릴리스 노트에 컬럼 순서 변경을 명시해야 합니다. (스펙 2m-8)

---

## 문제 13
**[심각도: 사소] `or_class_is_replication_on()`이 복제 제외 플래그를 매직 넘버 `32`로 하드코딩한다**

- 위치: `src/base/object_representation_sr.c:785`

로직 설명: 서버 측에서 클래스 레코드의 flags를 읽어 복제 여부를 판단하는데, `int replication_off_flag = 32; /* SM_CLASSFLAG_REPLICATION_OFF = 32 */`(:785)처럼 열거형 값을 숫자로 박아 넣었습니다. 주석의 이름(`SM_CLASSFLAG_REPLICATION_OFF`)도 실제 열거형 이름(`SM_CLASSFLAG_DATA_REPLICATION_OFF`)과 다릅니다.

문제 시나리오: 향후 누군가 `SM_CLASS_FLAG` 열거형에 값을 재배치하거나 새 플래그를 중간에 끼우면, 이 하드코딩 32가 조용히 다른 플래그를 가리켜 복제 판정이 뒤집힙니다. 컴파일러가 잡아주지 못합니다.

제안: 서버/클라이언트가 공유하는 헤더에 상수를 두거나, 최소한 `static_assert`로 열거형 값과 32의 일치를 강제해야 합니다.

---

## 문제 14
**[심각도: 사소] `log_ha_repl_fk_ref_all_replicated()`가 참조 테이블 PK를 NULL 검사 없이 역참조한다**

- 위치: `src/query/execute_schema.c:9837-9839`

로직 설명: FK 위반을 파일에 기록할 때 `DB_CONSTRAINT *pk_c = db_constraint_find_primary_key(db_get_constraints(ref_class_mop));`(:9837)로 참조 테이블의 PK를 찾은 뒤 곧바로 `pk_c->name`(:9839)을 씁니다. `db_constraint_find_primary_key`는 PK가 없으면 NULL을 반환합니다. 또한 `ref_class_mop = ws_mop(...)` 결과도 NULL 검사 없이 `sm_is_replication_class(ref_class_mop)`에 넘깁니다.

문제 시나리오: CUBRID FK는 참조 대상에 PK가 있어야 생성되므로(없으면 `ER_FK_REF_CLASS_HAS_NOT_PK`) 정상 경로에서는 `pk_c`가 NULL이 아닙니다. 다만 카탈로그가 손상됐거나, 향후 UNIQUE 키 참조 FK를 허용하도록 확장되면 이 경로가 NULL 역참조로 rkcheck를 죽입니다. 방어 코드가 없어 잠재 위험이 남습니다.

제안: `pk_c != NULL` 확인 후 이름을 출력하고, NULL이면 대체 문구(예: 참조 인덱스명)로 처리해야 합니다.

---

## 문제 16
**[심각도: 사소] `UTIL_INDEX` 열거형에 `RKCHECK`를 중간 삽입해 이후 값이 한 칸씩 밀린다**

- 위치: `src/executables/utility.h:830`

로직 설명: `UTIL_INDEX` 열거형에서 `RKCHECK`가 `LOGFILEDUMP` 앞에 끼워졌습니다(:830-831). 이로써 `LOGFILEDUMP`를 비롯한 뒤 값들의 정수 값이 바뀝니다.

문제 시나리오: 이 열거형 값이 배열 인덱스나 프로세스 간/버전 간 직렬화에 쓰이면, 혼합 버전 환경에서 유틸리티 식별이 어긋날 수 있습니다. 현재 `ua_Utility_Map`은 이름 매핑을 쓰므로 즉각적 문제는 없어 보이나, 관례상 새 항목은 끝에 추가하는 편이 안전합니다.

제안: 값 의존성이 없음을 확인하고, 없더라도 신규 항목은 열거형 끝에 두는 것을 권합니다.

---

## 문제 17
**[심각도: 사소] `generate_violation_list_file_name()`이 `localtime_r` 실패 시 미초기화 버퍼를 파일명으로 돌려준다**

- 위치: `src/executables/util_cs.c:2839`

로직 설명: 이 함수는 `localtime_r`이 성공할 때만 `out`에 `snprintf`로 파일명을 채우고(:2846-2851), 실패하면 `out`을 채우지 않은 채 그대로 반환합니다(:2852). 호출부 `open_violation_list_file`(:2856)은 이 `out`(스택의 `violation_list_file[PATH_MAX]`, 초기화 안 됨)을 파일명으로 그대로 씁니다.

문제 시나리오: `localtime_r`이 NULL을 반환하는 드문 상황에서 초기화되지 않은 스택 내용이 파일 경로로 사용되어, 엉뚱한 경로에 파일을 만들거나 `fopen`이 실패합니다(그리고 문제 5의 NULL fp 크래시로 이어질 수 있습니다).

제안: 함수 진입 시 `out[0] = '\0'`로 초기화하고, `localtime_r` 실패를 호출부가 감지할 수 있게 NULL을 반환해야 합니다.

---

## 문제 18
**[심각도: 사소] `is_replication_class()`가 클래스 조회 실패를 release에서 조용히 복제 스킵으로 처리**

- 위치: `src/query/execute_statement.c:3201`(`is_replication_class` 정적 함수)

로직 설명: `is_replication_class(classname)`은 `db_find_class(classname)`가 NULL이면 `assert(false)` 후 `false`를 반환합니다(:3211-3215). `is_data_repl_log_enabled` → `spec_has_replication_class` → 이 함수로 이어지는 SBR 게이트에서 쓰입니다.

문제 시나리오: 정상적으로 마스터에서 실행되는 문장이라면 클래스가 존재하므로 드문 경우지만, 시노님/동시 DROP 등으로 조회가 실패하면 릴리스 빌드에서 assert가 무력화되어 `false`("복제 안 함")로 처리되고 SBR 로그가 조용히 생략됩니다. 구 문제 1과 동일한 "에러를 false로 뭉개는" 패턴입니다(#7697이 heap 경로만 고쳤을 뿐 이 SBR 경로는 남아 있습니다).

제안: 조회 실패를 호출자에 전파하거나, 최소한 에러 로그를 남겨 조용한 복제 누락을 관측 가능하게 해야 합니다.

---

## 문제 19
**[심각도: 사소] `REPLICATION`이 예약어가 되어 기존 `replication` 컬럼/테이블 이름과 충돌한다**

- 위치: `src/parser/csql_grammar.y:1669`(REPLICATION 전용 토큰) / 비예약 식별자 규칙(`identifier_without_dot`, :20622~)에 REPLICATION 미포함

로직 설명: 문법에 `%token <cptr> REPLICATION`(:1669)을 새로 넣었지만, 비예약 식별자(identifier) 규칙 목록(REGEXP·REMOVE·REPEATABLE·RESPECT·REVERSE 등이 들어 있는 :20870~20890 구간)에는 `REPLICATION`을 추가하지 않았습니다. 이웃 키워드들은 비예약 목록에 들어가 있어 대비됩니다.

문제 시나리오: 업그레이드 전에 `replication`이라는 이름의 컬럼이나 테이블을 쓰던 사용자는, 업그레이드 후 그 이름을 따옴표 없이 참조하는 기존 SQL이 문법 오류로 깨집니다.

제안: `csql_grammar.y`의 비예약 식별자 규칙에 `REPLICATION`을 추가해 하위 호환을 유지해야 합니다. (스펙 T-5)

---

## 재검증 요약 (1차 → 2차)

| 1차 문제 | 심각도 | 판정 | 근거 |
|---|---|---|---|
| 1 (heap_is_replication_class KILL QUERY 삼킴) | 치명 | **해소** | #7697이 `heap_get_class_repl_on()`(int 반환+out-param)으로 재설계, 호출부가 `error_code != NO_ERROR` 시 `goto error`로 인터럽트 전파(locator_sr.c:8047-8062) |
| 2 (다중 절 ALTER 게이트 오참조) | 중요 | 유지 | execute_schema.c:2051 `alter->info.alter.code` 그대로 |
| 3 (부분 NOT NULL UNIQUE RK 오인) | 중요 | 유지 | class_object.c:95 매크로·schema_manager.c:16114 그대로 |
| 4 (필터/함수 UNIQUE RK 오인) | 중요 | 유지 | object_representation_sr.c:4694 필터/함수 미검사 그대로 |
| 5 (rkcheck NULL fp 크래시) | 중요 | 유지 | util_cs.c:3320 NULL 검사 없음 그대로 |
| 6 (인덱스 루프 매 반복 heap 조회) | 중요 | **해소** | #7697 재구조화로 판정 호출이 "후보 키 발견+미복제"로 게이팅, 인덱스 루프 내 반복 조회 제거(locator_sr.c:8041-8057) |
| 7 (TRUNCATE OFF 무시) | 보통 | 유지 | execute_statement.c:376 그대로 |
| 8 (DDL 무조건 복제) | 보통 | 유지 | execute_statement.c:3345 default:return true 그대로 |
| 9 (LIKE REPLICATION 무시) | 보통 | 유지 | execute_schema.c:10258 그대로 |
| 10 (do_alter 조회 실패 오인) | 보통 | 유지 | execute_schema.c:2061-2065 그대로 |
| 11 (재검증 게이트 목록 누락) | 보통 | 유지 | execute_schema.c:109 4개 코드만 그대로 |
| 12 (db_class 컬럼 중간 삽입) | 보통 | 유지 | install.cpp:1313 / query_spec.cpp:74 그대로 |
| 13 (매직 넘버 32) | 사소 | 유지 | object_representation_sr.c:785 그대로 |
| 14 (FK PK NULL 역참조) | 사소 | 유지 | execute_schema.c:9837-9839 그대로 |
| 15 (checksumdb 억제 해제 미검사) | 사소 | **해소** | #7678이 억제 설정/해제 반환값을 캡처·전파(checksumdb.c:1727-1741), 억제 실패 시 db_execute 전 abort |
| 16 (UTIL_INDEX 중간 삽입) | 사소 | 유지 | utility.h:830 그대로 |
| 17 (localtime_r 미초기화 버퍼) | 사소 | 유지 | util_cs.c:2839 그대로 |
| 18 (is_replication_class 조용한 스킵) | 사소 | 유지 | execute_statement.c:3201 assert(false)+false 그대로 |
| 19 (REPLICATION 예약어화) | 사소 | 유지 | csql_grammar.y:1669 토큰, 비예약 목록 미포함 그대로 |

**집계**: 유지 16 · 해소 3(1·6·15) · 폐기 0

## 신규 발굴 (2차) — 조사 종료 선언

동기화 델타(#7678·#7697)와 전체 diff를 다시 훑었으나 **새로 추가할 결함을 찾지 못했습니다.** 근거:

- **#7697 (heap_file.c/.h, locator_sr.c 3파일)**: `heap_get_class_repl_on()`은 fetch 실패 시 `ASSERT_ERROR_AND_SET`로 실제 에러코드를 잡아 반환하고, 호출부(locator_add_or_remove_index_internal)는 `&&` 사슬에서 검사를 분리해 에러를 캡처·전파합니다. `*repl_on = false` 선초기화, OID_ISNULL 조기 반환도 안전합니다. `repl_log_insert` 실패 시 `replicated=true`가 세팅되지만 곧바로 `if (error_code != NO_ERROR) goto error`로 빠지므로 무해합니다. 신규 결함 없음.
- **#7678 checksumdb.c**: `db_set_suppress_repl_on_transaction(true)` 실패 시 db_execute 전에 반환, `(false)` 해제 실패는 error에 담겨 실행 성공 시 그대로 반환됩니다. 해제 실패로 tdes 억제 플래그가 남더라도 에러 반환으로 트랜잭션이 abort되어 정리되므로 실질 위험은 없습니다. 신규 결함 없음.
- **#7678 execute_statement.c**: `spec_has_replication_class`/`get_spec_classname`/`pt_spec_repl_class_walk`는 entity_name·flat_entity_list·derived_table 서브트리를 모두 NULL 안전하게 검사합니다(`get_spec_classname`이 NULL 반환 → `is_replication_class(NULL)=false`). UPDATE/DELETE가 `PT_SPEC_FLAG_UPDATE/DELETE` 붙은 실제 수정 대상 spec만 보도록 정교화된 것도 정합합니다. 다만 `is_data_repl_log_enabled`의 `default: return true`(문제 8)는 이 델타에서도 그대로여서 유지 문제로 남습니다. 신규 결함 없음.

핵심 유지 결함(다중 절 게이트 오참조, 부분 NOT NULL UNIQUE RK 오인, 서버 RK 후보 필터/함수 미검사, rkcheck NULL fp)의 수정·런타임 검증이 우선이라 판단하며, 정적 분석만으로 새 결함을 억지로 늘리지 않고 여기서 종료합니다.

---

## 심각도별 집계 (2차, 유지 기준)

| 심각도 | 개수 | 문제 번호 |
|---|---|---|
| 치명 | 0 | — |
| 중요 | 4 | 2, 3, 4, 5 |
| 보통 | 6 | 7, 8, 9, 10, 11, 12 |
| 사소 | 6 | 13, 14, 16, 17, 18, 19 |
| **계** | **16** | |
