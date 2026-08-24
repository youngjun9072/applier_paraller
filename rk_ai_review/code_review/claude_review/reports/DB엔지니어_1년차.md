# CUBRID RK/REPLICATION 기능 코드 리뷰 — DB 엔지니어 1년차

> **2차 재리뷰(기준 `734f4959d`)** — 1차 리뷰(기준 `44468ed73`) 이후 fork가 upstream과 동기화되어
> `#7678`(SBR/checksumdb, `3b6ebd1a9`)과 `#7697`(인터럽트 assert 수정, `9e094324b`)이 새로 브랜치에 들어왔다.
> 이 문서는 1차 리포트의 17개 문제를 새 HEAD에서 전부 재검증하고, 동기화 델타와 전체 diff에서 신규 문제를 추가 발굴해 재작성한 것이다.

## 페르소나 소개

저는 입사 1년차 DBA/운영 엔지니어입니다. 아직 CUBRID 엔진 내부 구조에 정통하지는 않지만, 매일 `cubrid hb start`로 HA를 올리고, 장애가 나면 `.err`/`.log` 파일을 뒤져 원인을 찾고, 대량 테이블이 있는 운영 DB에서 점검 스크립트를 돌리는 사람입니다. 이번 리뷰에서는 코드의 우아함보다 "이 코드가 새벽 3시에 장애를 일으켰을 때 내가 원인을 찾을 수 있는가", "대량 테이블 환경에서 점검 도구가 끝까지 살아남는가", "에러 메시지·종료 코드만 보고 자동화 스크립트를 짤 수 있는가"를 기준으로 봤습니다.

모든 지적은 Read로 함수 본문을 직접 확인하고 grep/LSP로 호출자·피호출자를 추적해 콜체인을 검증했습니다. 재검증은 `git show`로 `#7678`/`#7697` 두 커밋의 실제 diff를 열어, 1차 리포트가 지적한 코드가 그대로인지 바뀌었는지 직접 대조했습니다.

## 재검증 요약

- **유지 16건** (문제 1, 2, 4~17): 새 HEAD에서도 해당 코드가 그대로 존재함을 확인. `execute_schema.c`, `util_cs.c`, `object_representation_sr.c`, `schema_manager.c`, `schema_system_catalog_install_query_spec.cpp`, `msg/en_US.utf8/utils.msg`는 이번 동기화 델타(`#7678`/`#7697`)가 건드리지 않은 파일이라 줄 번호도 거의 그대로였습니다.
- **해소 1건** (문제 3): `#7697`이 정확히 이 문제를 근본 수정했습니다. `heap_is_replication_class()`(bool 반환, 실패를 삼킴)가 `heap_get_class_repl_on()`(int 에러코드 반환 + out-parameter)으로 바뀌었고, 호출부 `locator_add_or_remove_index_internal()`도 에러를 `goto error`로 정상 전파하도록 수정되었습니다. 실측 검증(원본 PR 리뷰에서 H2SU가 확인)까지 거친 수정이 그대로 반영된 것을 `git show 9e094324b`로 직접 확인했습니다.
- **폐기 0건**: 재검증 결과 오판으로 판명된 문제는 없었습니다.
- **신규 1건** (문제 18): `#7697`이 고친 바로 그 코드 블록(`locator_add_or_remove_index_internal`의 인덱스 순회)에서, `#6908` 리뷰 때 이미 지적됐던 "같은 class_oid에 대해 반복 호출" 성능 문제가 이번 수정에서도 그대로 남아있음을 확인해 추가했습니다.

---

## 문제 1 — [치명] rkcheck가 FK 위반을 로깅하다 NULL 포인터를 역참조해 크래시할 수 있다 (유지)

**위치**: `src/query/execute_schema.c:9818-9840` (`log_ha_repl_fk_ref_all_replicated`), 호출자 `src/executables/util_cs.c` `check_fk_constraint()`

**재검증**: 새 HEAD(`734f4959d`)에서도 동일 코드가 그대로 존재합니다(`db_constraint_find_primary_key()` 반환값 NULL 체크 없이 `pk_c->name` 역참조). 이 함수는 `#7678`/`#7697`이 건드린 파일(`heap_file.c`, `locator_sr.c`, `checksumdb.c`, `execute_statement.c`)에 포함되지 않아 영향받지 않았습니다.

**로직 설명**: `rkcheck`가 `-f`(FK 검사) 옵션으로 각 복제 대상 클래스를 순회하면서, FK가 참조하는 테이블이 복제 대상이 아니면 위반으로 기록합니다. 위반을 `.list` 파일에 적을 때 다음과 같이 참조 테이블의 "PK 이름"을 출력합니다.

```c
DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
fprintf (fp, "%s(%s) -> %s(%s)\n", sm_get_ch_name (class_obj), tmp_c->name,
         sm_get_ch_name (ref_class_mop), pk_c->name);
```

`db_constraint_find_primary_key()`(`src/compat/db_info.c:2003`)는 PK 제약이 없으면 **NULL을 반환**하도록 명시적으로 문서화되어 있습니다(`return : constraint descriptor (or NULL if not found)`).

**문제 시나리오**: 이번 기능의 핵심은 "RK(복제 키)가 PK가 아니라 NOT NULL UNIQUE여도 된다"는 것입니다(PR #6467). 즉 참조 테이블(`ref_class_mop`)이 **PK 없이 NOT NULL UNIQUE만으로 복제 테이블 자격을 갖춘 정상적인 케이스**가 이 기능이 허용하는 합법적인 스키마입니다. 이런 테이블을 FK로 참조하면서 그 참조 테이블의 REPLICATION 옵션이 OFF인 경우, 이 코드는 `pk_c`가 NULL인 채로 `pk_c->name`을 역참조해 **세그멘테이션 폴트**를 일으킵니다. rkcheck는 `hb start` 시 자동 호출되므로, 이 조합의 테이블이 하나라도 있으면 **HA 기동 사전 점검 자체가 크래시로 끝나고**, 나머지 테이블에 대한 점검 결과도 전혀 얻을 수 없게 됩니다.

**제안**: `pk_c == NULL`인 경우 PK 이름 대신 "RK constraint name"(예: `classobj_find_cons_replication_key()`로 찾은 실제 RK 제약 이름)을 출력하도록 수정. 최소한 NULL 가드를 추가해 크래시만이라도 막아야 합니다.

---

## 문제 2 — [치명] rkcheck가 위반목록 파일을 열지 못했을 때 검사 없이 크래시할 수 있다 (유지)

**위치**: `src/executables/util_cs.c:3320` (`fp = open_violation_list_file(...)`), 이후 `:3332` `PRINT_SECTION_TITLE(fp, ...)` 등

**재검증**: 새 HEAD에서도 `fp` NULL 체크가 여전히 없습니다. `util_cs.c`는 이번 동기화 델타의 대상 파일이 아닙니다.

**로직 설명**: `rkcheck()`는 서버 접속에 성공한 뒤 `.list` 위반목록 파일을 엽니다.

```c
fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);
classes = db_get_all_classes ();
if (classes == NULL) { ... goto end1; }
if ((repl_check_flags & REPL_CHECK_RK) != 0)
  {
    PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);   /* fp가 NULL이어도 그대로 fprintf */
    ...
  }
```

`open_violation_list_file()`(`util_cs.c:2856`)은 내부적으로 `fopen(file_path, "w")`을 호출하고 그 반환값을 그대로 리턴합니다. `fopen`이 실패하면(로그 디렉터리 권한 문제, 디스크 풀 등) `NULL`을 반환하는데, `rkcheck()`는 **이 반환값을 전혀 검사하지 않습니다.** `PRINT_SECTION_TITLE`/`PRINT_MESSAGE`/`PRINT_BLANK_LINE` 매크로는 모두 `fprintf(fp, ...)`를 조건 없이 실행합니다.

**문제 시나리오**: `$CUBRID/log` 디렉터리 권한이 잘못됐거나 디스크가 가득 찬 상태에서 HA를 기동하면(`us_hb_process_start()` → `us_hb_process_rkcheck()` → `rkcheck` 자동 호출), `fopen`이 실패해 `fp == NULL`인 채로 `fprintf(NULL, ...)`가 호출되어 **정의되지 않은 동작(대부분 세그폴트)**이 발생합니다. 운영자 입장에서는 "HA가 안 올라온다"는 것만 보이고, 정작 원인은 크래시 때문에 `.err`/`.list` 파일 어디에도 남지 않습니다.

**제안**: `fp == NULL` 체크 후 `db_error_string`류 메시지로 즉시 실패 처리(`err = ER_FAILED; goto end1;`).

---

## 문제 3 — [치명 → 해소] "KILL QUERY 무시" 버그의 원인이었던 `heap_is_replication_class()`가 #7697로 근본 수정됨

**1차 위치**: `src/storage/heap_file.c:11074-11102`(`heap_is_replication_class`), 호출자 `src/transaction/locator_sr.c`의 `locator_add_or_remove_index_internal()`

**재검증 결과**: **해소.** `git show 9e094324b`(#7697, 2026-08-20 병합)로 실제 코드를 직접 확인했습니다.

```c
-bool
-heap_is_replication_class (THREAD_ENTRY * thread_p, const OID * class_oid)
+int
+heap_get_class_repl_on (THREAD_ENTRY * thread_p, const OID * class_oid, bool * repl_on)
 {
   ...
   if (heap_get_class_record (thread_p, class_oid, &recdes, &scan_cache, PEEK) != S_SUCCESS)
     {
-      assert (false);
-      return false;
+      ASSERT_ERROR_AND_SET (error_code);
+      heap_scancache_end (thread_p, &scan_cache);
+      return error_code;
     }
```

호출부 `locator_add_or_remove_index_internal()`(`src/transaction/locator_sr.c:8038-8055`)도 `&&` 사슬에 박혀 있던 판정을 분리해, `error_code != NO_ERROR`이면 `goto error`로 실제 인터럽트를 트랜잭션에 전파하도록 바뀌었습니다.

```c
bool repl_on = false;
error_code = heap_get_class_repl_on (thread_p, class_oid, &repl_on);
if (error_code == NO_ERROR && repl_on)
  {
    error_code = repl_log_insert (...);
    replicated = true;
  }
```

1차 리포트가 지적한 "인터럽트(KILL QUERY)로 인한 클래스 레코드 fetch 실패가 `false`(비복제)로 뭉개져 트랜잭션 취소가 무시된다"는 문제는 이제 에러 코드가 그대로 호출자까지 전파되어 트랜잭션이 정상적으로 abort/rollback되므로 더 이상 성립하지 않습니다.

**resolved_nums 근거**: 문제 3은 `#7697`(`9e094324b`)로 해소. `heap_is_replication_class`(bool) → `heap_get_class_repl_on`(int 에러코드+out-param) 전환 및 `locator_add_or_remove_index_internal`의 에러 전파 확인.

---

## 문제 4 — [중요] `do_alter()`의 복제 제약 재검사 게이트가 매번 "최초 절"의 코드만 본다 (유지)

**위치**: `src/query/execute_schema.c:1854`(반복문 내 지역 변수) vs `:2051`(게이트 조건)

**재검증**: 줄 번호 그대로 확인. `execute_schema.c`는 동기화 델타 대상이 아닙니다.

**로직 설명**: `do_alter()`는 하나의 `ALTER TABLE` 문에 여러 절이 나열될 수 있음을 알고, 각 절을 순회하며 처리합니다.

```c
for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next)
  {
    const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;   /* line 1854: 절마다 갱신되는 지역변수 */
    switch (alter_code) { ... }
    ...
    if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))  /* line 2051 */
      {
        need_check_repl_constraint = true;
      }
  }
```

여기서 `alter`는 **매개변수로 받은 최초(첫 번째) 절 노드 자체**이고, `crt_clause`는 반복문이 진행되며 바뀌는 "현재 처리 중인 절"입니다. 그런데 재검사 여부를 결정하는 게이트(`IS_REPL_CONSTRAINT_RELATED_ALTER`)는 반복문 안에 있으면서도 **매 반복마다 `alter->info.alter.code`(=고정된 첫 절의 코드)만 검사**하고, 정작 방금 계산한 지역변수 `alter_code`나 `crt_clause->info.alter.code`는 쓰지 않습니다.

**문제 시나리오**: `ALTER TABLE t ADD COLUMN c INT, DROP CONSTRAINT pk_t;` 처럼 첫 절이 RK와 무관한 종류이고 두 번째 절이 실제로 RK를 제거하는 경우, `need_check_repl_constraint`가 절대 true가 되지 않을 수 있습니다. 이는 필터링 결과표 C-9("게이트가 alter 문장의 첫 절 코드만 봄")가 지적한 현상의 정확한 코드상 원인이며, PR #6637이 "여러 절을 아우르는 검사"를 만들려던 취지 자체가 이 버그로 무력화됩니다.

**제안**: `alter->info.alter.code` 대신 반복문 내부의 `alter_code`(또는 `crt_clause->info.alter.code`)를 사용해 모든 절에 대해 게이트를 평가하도록 수정.

---

## 문제 5 — [중요] 재검사 시 `db_find_class()` 실패를 확인하지 않고 바로 사용한다 (유지)

**위치**: `src/query/execute_schema.c:2060-2064`; `src/object/schema_manager.c:3390-3406`(`sm_is_replication_class`)

**재검증**: 새 HEAD에서 정확한 줄 번호는 2060(`vclass = db_find_class (entity_name);`)~2064로 소폭 확인되었을 뿐 로직은 동일합니다.

```c
vclass = db_find_class (entity_name);
if (!sm_is_replication_class (vclass))
  {
    return NO_ERROR;
  }
```

`sm_is_replication_class()`의 구현은:

```c
bool
sm_is_replication_class (MOP op)
{
  SM_CLASS *class_;
  if (op != NULL && au_fetch_class_force (op, &class_, AU_FETCH_READ) == NO_ERROR)
    {
      return !(class_->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF);
    }
  assert (false);
  return false;
}
```

`op == NULL`이면 `assert(false)` 후 `false`를 반환합니다. 릴리스 빌드에서는 assert가 비활성화되므로 조용히 "비복제 클래스"로 오판되어 `do_alter()`는 재검사를 건너뛰고 성공 처리해 버립니다. 반면 디버그 빌드(QA 환경)에서는 이 지점에서 곧바로 assert 크래시가 납니다.

**문제 시나리오**: RENAME을 동반한 복합 ALTER 등으로 `entity_name`이 최종 이름으로 갱신된 뒤 조회에 실패하는 경계 상황이 생기면, 릴리스 빌드는 조용히 넘어가고, QA에서는 원인 불명의 assert 크래시로 나타나 재현이 어렵습니다. 같은 패턴이 `execute_statement.c`의 `is_replication_class()`(`db_find_class` 실패 시 동일하게 `assert(false); return false;`)에서도 반복됩니다 — 이 함수는 `#7678` 동기화 델타에도 포함되어 있지만 `44468ed73`와 `3b6ebd1a9` 사이의 diff가 없어(동일 패치가 재병합된 것) 이미 1차 리포트 시점 코드와 완전히 동일함을 `git diff 44468ed73 3b6ebd1a9`로 확인했습니다.

**제안**: `vclass == NULL`을 명시적으로 처리(에러 반환 또는 최소 `er_set` 후 실패 처리)하고, `sm_is_replication_class()`의 NULL 입력을 "assert 대상 버그"가 아니라 "정상적으로 실패할 수 있는 입력"으로 재분류.

---

## 문제 6 — [중요] `do_alter_change_replication()`이 다른 기능(COMMENT 변경)의 세이브포인트 이름을 그대로 재사용한다 (유지)

**위치**: `src/query/execute_schema.c:11747` (신규), 비교 대상 `:11505`(`do_alter_change_tbl_comment`, 기존)

**재검증**: 새 HEAD에서도 두 함수 모두 `UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`를 공유합니다.

```c
static int
do_alter_change_replication (PARSER_CONTEXT * const parser, PT_NODE * const alter)
{
  ...
  error = tran_system_savepoint (UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT);   /* COMMENT 변경용 상수 재사용 */
  ...
  if (error != NO_ERROR && tran_saved && error != ER_LK_UNILATERALLY_ABORTED)
    {
      (void) tran_abort_upto_system_savepoint (UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT);
    }
  ...
}
```

함수 구조(변수명 `entity_name`/`class_obj`/`ctemplate`, 에러 처리 순서, `pt_record_error` 호출 위치)가 `do_alter_change_tbl_comment`와 거의 동일한 것으로 보아, 이 함수를 복사해서 만들면서 세이브포인트 상수 이름을 바꾸는 것만 빠뜨린 전형적인 복붙 실수로 보입니다.

**문제 시나리오**: 현재는 `do_alter()` 전체가 `UNIQUE_SAVEPOINT_MULTIPLE_ALTER`로 한 번 더 감싸여 있어(원자성 보장, PR #6637) 최종적으로 전체 롤백은 되지만, 이름이 겹치는 세이브포인트가 같은 트랜잭션 안에 스택으로 쌓이는 것은 잠재적 위험입니다. 향후 `do_alter_change_tbl_comment` 쪽 에러 처리가 바뀌어 `UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`를 롤백 대상으로 삼는 코드가 추가되면, `ALTER TABLE t COMMENT='x', REPLICATION=OFF` 같은 복합 문에서 의도치 않게 REPLICATION 변경까지 함께 롤백되거나 그 반대가 될 수 있습니다.

**제안**: `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 전용 상수를 새로 정의해 사용.

---

## 문제 7 — [중요] FK 참조 검증 로직이 두 곳에 중복 구현되어 있다 (유지)

**위치**: `src/query/execute_schema.c:9783-9805`(`check_ha_repl_fk_ref_all_replicated`, bool 반환, DDL 검증용) vs `:9806-9845`(`log_ha_repl_fk_ref_all_replicated`, int 반환, rkcheck 출력용)

**재검증**: 새 HEAD에서 줄 번호가 근소하게(9793→9783 등) 다를 뿐 두 함수 모두 그대로 중복 존재합니다.

**로직 설명**: 두 함수 모두 "이 클래스의 FK가 참조하는 테이블이 복제 대상인지" 확인하기 위해 `db_get_constraints()` → FK 타입 필터링 → `ws_mop(&ref_class_oid)` → `sm_is_replication_class()` 순으로 동일한 순회를 각각 독립적으로 구현합니다.

**문제 시나리오**: PR #6618에서는 정반대로 "호출 로직이 같다"는 이유로 비슷한 두 함수를 하나의 공용 함수(`check_ha_repl_constraint`)로 통합한 바 있습니다. 이번 diff는 그 교훈과 반대로 FK 순회 로직을 다시 둘로 쪼갰습니다. 향후 FK 검증 규칙이 바뀌면 두 함수 중 하나만 고치고 다른 하나를 빠뜨리는 회귀가 발생하기 쉽습니다.

**제안**: 공통 순회 로직을 하나로 묶고, "출력 여부"만 콜백/플래그로 분기.

---

## 문제 8 — [보통] 복제 판정에 매직 넘버 32가 하드코딩되어 있고 주석의 상수명도 옛 이름이다 (유지)

**위치**: `src/base/object_representation_sr.c:781-791`(`or_class_is_replication_on`)

**재검증**: 새 HEAD에서도 동일합니다. 이 파일은 동기화 델타에 포함되지 않았습니다.

```c
bool
or_class_is_replication_on (RECDES * record)
{
  int flags = 0;
  int replication_off_flag = 32;	/* SM_CLASSFLAG_REPLICATION_OFF = 32 */
  ...
  return !(flags & replication_off_flag);
}
```

실제 플래그 상수는 `src/object/class_object.h`에 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`로 정의되어 있습니다(PR #6477에서 개명됨). 주석에 적힌 상수 이름(`SM_CLASSFLAG_REPLICATION_OFF`)조차 실제로 존재하지 않는 옛 이름입니다.

**문제 시나리오**: 향후 누군가 `class_object.h`에서 플래그 비트 값을 재배치하면 이 파일의 `32`는 컴파일러가 잡아줄 방법이 없이 조용히 틀린 값이 되어, RK 판정이 전면적으로 잘못될 수 있습니다.

**제안**: 최소한 주석을 현재 상수명으로 수정. 가능하면 값을 두 계층이 공유하는 별도의 상수 헤더로 옮기거나, `static_assert`로 두 값의 일치를 컴파일 타임에 검증.

---

## 문제 9 — [보통] rkcheck의 `.err` 로그 파일명과 `.list` 위반목록 파일명이 서로 다른 규칙을 쓴다 (유지)

**위치**: `src/executables/util_cs.c:3290`(er_msg_file 생성) vs `:3320`(violation_list_file 생성)

**재검증**: 새 HEAD에서도 동일합니다.

```c
snprintf (er_msg_file, PATH_MAX, "%s_%s.err", database_name, arg->command_name);   /* @localhost 붙기 전 이름 */
er_init (er_msg_file, ER_NEVER_EXIT);
...
if (strchr (database_name, '@') == NULL)
  {
    snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
    database_name = tmp_database_name;   /* 이후부터 database_name은 @localhost가 붙은 값 */
  }
...
fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);  /* @localhost 붙은 이름 */
```

사용자가 `rkcheck demodb`처럼 호스트 없이 실행하면 `.err` 파일은 `demodb_rkcheck.err`로, `.list` 파일은 `demodb@localhost_rkcheck_YYYYMMDD_HHMM.list`로 생성됩니다.

**문제 시나리오**: 여러 노드/여러 DB를 운영하는 환경에서 장애 발생 시 `.err`와 `.list`를 같이 대조하며 원인을 찾아야 하는데, 두 파일이 서로 다른 명명 규칙을 쓰면 자동화 스크립트나 로그 수집 도구가 "같은 실행의 짝"임을 파일명만으로 매칭하기 어렵습니다.

**제안**: `.err` 파일명도 `@localhost` 정규화 이후의 `database_name`으로 생성하도록 순서를 바꾸거나, 두 파일이 같은 타임스탬프/식별자를 공유하도록 통일.

---

## 문제 10 — [보통] rkcheck가 이미 지적된 호스트명 버퍼 트렁케이션 위험을 새 코드에 그대로 재도입했다 (유지)

**위치**: `src/executables/util_cs.c:3273`, `:3297-3302`

**재검증**: 새 HEAD에서도 동일한 `TODO` 주석과 함께 그대로 존재합니다.

```c
char tmp_database_name[CUB_MAXHOSTNAMELEN];   /* 256바이트 */
...
if (strchr (database_name, '@') == NULL)
  {
    /* TODO: Handle truncation explicitly here; keep this in sync with applyinfo() local_database_name build path. */
    snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
    database_name = tmp_database_name;
  }
```

**PR 히스토리 근거**: PR #6934(2026-03-31)에서 vimkim이 정확히 이 패턴(`applyinfo()`의 `local_database_name` 조합)을 두고 "CUB_MAXHOSTNAMELEN(256)이 최대 길이 DB 이름(255자)+`@localhost`(10자)를 모두 담기엔 부족할 수 있다"고 MAJOR로 지적했고, 저자는 "TODO로 남긴 채 마이너한 리뷰라 바로 머지하겠다"고 처리했습니다.

**문제 시나리오**: 이번 diff는 그 미해결 TODO를 알고 있으면서도 `rkcheck()`라는 새 유틸리티에 동일한 크기의 버퍼로 동일한 패턴을 복제했습니다. DB 이름이 246자를 넘으면 `@localhost`가 잘려나가 `check_database_name()`이 의도와 다른 문자열을 검사하게 됩니다.

**제안**: `applyinfo()`와 `rkcheck()`가 공유하는 "DB 이름에 @localhost 붙이기" 헬퍼 함수를 하나 만들어 트렁케이션을 명시적으로 에러 처리.

---

## 문제 11 — [보통] rkcheck의 종료 코드 체계가 뒤섞여 있고 문서화되어 있지 않다 (유지)

**위치**: `src/executables/util_cs.c:3283`(`EXIT_FAILURE`), `:3306`/`:3312`(`ER_FAILED`), `:3387`(`ER_HA_REPLICATION_CONSTRAINT_VIOLATION`); `msg/en_US.utf8/utils.msg`(RKCHECK 사용법 메시지)

**재검증**: 새 HEAD에서도 동일한 구조입니다.

**로직 설명**: `rkcheck()`는 실패 상황마다 서로 다른 도메인의 값을 `err`에 담아 반환합니다 — 사용법 오류는 `EXIT_FAILURE`(1), 접속/서버 오류는 `ER_FAILED`, 제약 위반은 CUBRID 내부 에러코드(`ER_HA_REPLICATION_CONSTRAINT_VIOLATION`, 실제 값 -1378). 이 값은 `main()`을 거쳐 프로세스 종료 코드로 그대로 리턴되므로 OS 관례상 하위 1바이트로 잘립니다(예: -1378 → 158). `us_hb_process_rkcheck()`는 `WEXITSTATUS(status)`로 이 값을 받아 "0이 아니면 실패"로만 판단하므로 자동화 경로 자체는 정상 동작하지만, 사람이 직접 `cub_admin rkcheck db; echo $?`를 실행했을 때 158/1/255 같은 숫자가 무엇을 의미하는지는 문서화되어 있지 않습니다.

**제안**: 종료 코드 표를 `RKCHECK_MSG_USAGE`에 추가하거나 최소한 운영 매뉴얼에 기재.

---

## 문제 12 — [보통] rkcheck가 RK/FK 검사마다 전체 클래스 목록을 처음부터 다시 순회한다 (대량 스키마 성능) (유지)

**위치**: `src/executables/util_cs.c:3330-3360`

**재검증**: 새 HEAD에서도 동일한 구조(RK 패스와 FK 패스가 각각 `check_repl_constraint_violations()`를 독립적으로 호출)입니다.

```c
if ((repl_check_flags & REPL_CHECK_RK) != 0)
  {
    err = check_repl_constraint_violations (classes, fp, check_rk_constraint, &rk_violation_count);
    ...
  }
if ((repl_check_flags & REPL_CHECK_FK) != 0)
  {
    err = check_repl_constraint_violations (classes, fp, check_fk_constraint, &fk_violation_count);
    ...
  }
```

**문제 시나리오**: 기본 옵션(`-r`/`-f` 둘 다 생략)으로 실행하면 클래스 목록 전체 순회 및 `db_is_vclass()`/`db_is_system_class()`/`sm_is_replication_class()` 호출이 두 번씩 반복됩니다. 테이블이 수천 개인 대형 스키마에서 `hb start`마다 자동으로 rkcheck가 도는데, 옵션을 지정하지 않으면 불필요하게 카탈로그 스캔이 두 배가 되어 HA 기동 시간이 늘어나고 카탈로그 락 경합 창도 길어집니다.

**제안**: 한 번의 순회에서 RK/FK 판정을 모두 계산하도록 `check_repl_constraint_violations()`를 한 번만 호출하는 구조로 리팩토링.

---

## 문제 13 — [사소] 죽은 전방선언 — `get_print_flags`는 정의되지 않는다 (유지)

**위치**: `src/executables/util_cs.c:187`

**재검증**: 새 HEAD에서도 `static int get_print_flags (UTIL_ARG_MAP * arg_map);` 선언이 그대로 있고, 실제 구현·호출되는 함수는 `get_repl_check_flags()`(`:2867`, `:3287`)입니다. `get_print_flags`는 여전히 정의되어 있지 않습니다.

**제안**: 미사용 전방선언 삭제.

---

## 문제 14 — [사소] `PRINT_MESSAGE` 매크로 정의 끝에 불필요한 라인 연속 문자가 남아있다 (유지)

**위치**: `src/executables/util_cs.c:106-109`

**재검증**: 새 HEAD에서도 `PRINT_MESSAGE`만 `while (0)` 다음에 불필요한 `\`이 남아 있고 다른 매크로(`PRINT_SECTION_TITLE`, `PRINT_BLANK_LINE`)와 스타일이 다릅니다.

**제안**: 다른 매크로와 동일한 스타일로 정리.

---

## 문제 15 — [보통] `db_class` 카탈로그 뷰 정의가 `%d` 자리표시자와 인자 목록을 수작업으로 순서 맞춰야 하는 구조다 (유지)

**위치**: `src/object/schema_system_catalog_install_query_spec.cpp:71-141`

**재검증**: 새 HEAD에서도 `is_replication_class` 컬럼의 `%d` 자리표시자와 `SM_CLASSFLAG_DATA_REPLICATION_OFF` 인자 위치가 정확히 일치함을 재확인했습니다(위치 자체는 문제 없음). 다만 이 함수 구조 자체(포맷 문자열-인자 순서를 사람이 맞춰야 함, 컴파일러 검증 없음)는 그대로입니다.

**문제 시나리오**: 앞으로 `db_class` 같은 시스템 카탈로그 뷰에 컬럼을 더 추가하는 담당자가 문자열 중간에 자리표시자를 끼워 넣으면서 인자 목록에서는 다른 위치에 끼워 넣거나 순서를 헷갈리면, 컴파일은 되지만 카탈로그 조회 결과가 조용히 틀어집니다.

**제안**: 최소한 각 `%d` 옆에 대응 인자 이름을 주석으로 병기(이미 일부는 그렇게 되어 있음). 장기적으로는 named placeholder 방식이나 컴파일 타임 검증 도입을 검토.

---

## 문제 16 — [보통] `check_ha_repl_constraint()`의 문서 주석이 실제로 존재하지 않는 파라미터를 설명한다 (유지)

**위치**: `src/query/execute_schema.c:9847-9866` (새 HEAD 기준 실제로는 `:9847` 부근, 소폭 이동)

**재검증**: 새 HEAD에서도 주석에 `repl_opt(in)` 파라미터 설명이 남아 있으나 함수 시그니처는 `class_obj` 하나뿐입니다.

```c
/*
 * check_ha_repl_constraint() - Validate replication-related constraints in HA mode.
 *   return  : Error code (NO_ERROR if valid)
 *   class_obj(in) : The class object being created or altered
 *   repl_opt(in)  : Replication option (true = ON, false = OFF)
 * ...
 */
int
check_ha_repl_constraint (DB_OBJECT * class_obj)
```

**제안**: 주석에서 `repl_opt` 설명 삭제, 필요하면 "호출 전 REPLICATION=ON임을 호출자가 보장해야 함"이라는 전제 조건을 명시.

---

## 문제 17 — [사소] rkcheck 사용법 메시지 파일이 개행 없이 끝난다 (유지)

**위치**: `msg/en_US.utf8/utils.msg` (파일 끝)

**재검증**: `cat -A`로 마지막 줄을 확인한 결과 `-f, --fk-check ...` 줄이 `$`(개행 표시) 없이 파일이 끝나는 것을 재확인했습니다.

**제안**: 파일 끝에 개행 추가.

---

## 문제 18 — [보통, 신규] `#7697`이 고친 코드 경로에, 이미 알려진 "인덱스 순회마다 반복 호출" 성능 문제가 그대로 남아있다

**위치**: `src/transaction/locator_sr.c:8038-8055` (`locator_add_or_remove_index_internal`), 호출 대상 `src/storage/heap_file.c:11085`(`heap_get_class_repl_on`, `#7697`이 새로 만든 함수)

**로직 설명**: `locator_add_or_remove_index_internal()`은 한 행(row)에 걸린 여러 후보 인덱스(PK, 복수의 NOT NULL UNIQUE 등)를 순회하는 반복문 안에서 복제 로그 생성 여부를 판단합니다. `#7697`이 새로 만든 `heap_get_class_repl_on()` 호출은 다음과 같이 이 반복문 내부에 그대로 위치합니다.

```c
if (error_code == NO_ERROR && need_replication && !replicated
    && or_is_replication_candidate_key (index)
    && !LOG_CHECK_LOG_APPLIER (thread_p) && log_does_allow_replication () == true)
  {
    bool repl_on = false;
    error_code = heap_get_class_repl_on (thread_p, class_oid, &repl_on);   /* 인덱스 순회마다 재호출 */
    if (error_code == NO_ERROR && repl_on)
      {
        error_code = repl_log_insert (...);
        replicated = true;   /* 성공하면 다음 인덱스부터는 !replicated 조건으로 스킵 */
      }
  }
```

`!replicated` 조건 덕분에 이미 복제 로그가 한 번 기록된 뒤로는 스킵되지만, **`class_oid`가 복제 대상이 아닌 경우(`repl_on == false`)에는 `replicated`가 결코 `true`가 되지 않으므로, 같은 행에 걸린 복제 후보 키 인덱스(PK 하나 + NOT NULL UNIQUE 여러 개)가 있는 한 매 인덱스마다 `heap_get_class_repl_on()`이 다시 호출**됩니다. 이 함수는 내부적으로 `heap_scancache_quick_start_root_hfid()` + `heap_get_class_record()`로 카탈로그 페이지를 다시 fetch하는 비용이 있으며, 같은 `class_oid`에 대한 결과는 이 트랜잭션 동안 바뀌지 않으므로 반복 호출은 순수 낭비입니다.

**PR 히스토리 근거**: 이 정확한 패턴은 `pr_히스토리.md`의 `#6908` 리뷰에서 이미 "MAJOR" 등급으로 지적된 바 있습니다 — "`heap_is_replication_class()`가 btree 인덱스 순회 루프 안에서 매번 호출되어 불필요한 heap scan이 반복된다. 같은 `class_oid`에 대해서는 결과가 항상 동일하므로 루프 밖으로 빼야 한다." `#7697`은 이 함수를 이름까지 바꿔가며 정확히 이 호출부를 다시 작성했지만, 목적이 "인터럽트 에러 전파"였을 뿐이라 이 성능 지적은 손대지 않고 그대로 남겼습니다.

**문제 시나리오**: PK 하나에 NOT NULL UNIQUE 인덱스가 여러 개 걸린 REPLICATION=OFF 테이블(합법적인 스키마입니다 — REPLICATION 옵션과 RK 개수는 독립적)에 대량 INSERT/서버측 loaddb를 실행하면, 행마다 "복제 후보 키 개수"만큼 카탈로그 클래스 레코드 재조회가 반복됩니다. 대량 스키마·대량 적재 환경에서는 이 반복 fetch가 누적되어 적재 성능에 영향을 주고, 카탈로그 페이지에 대한 래치 경합도 그만큼 늘어납니다. `#7697`의 재현 시나리오 자체가 "100만 행 서버측 적재"였다는 점을 고려하면, 바로 그 워크로드에서 이 비효율이 가장 크게 드러납니다.

**제안**: `class_oid`별 `repl_on` 판정 결과를 인덱스 순회 반복문 진입 전에 한 번만 계산해 지역 변수에 캐시하고, 반복문 안에서는 그 값을 재사용하도록 리팩토링(리뷰에서 이미 제안됐던 방향과 동일).

---

## 조사 종료 선언

**재검증 방법**: 1차 리포트의 17개 문제 전부를 `git show`/`git diff`로 `44468ed73`(1차 기준) ↔ `734f4959d`(2차 기준) 사이에 실제로 무엇이 바뀌었는지 직접 대조했습니다. `#7678`(`3b6ebd1a9`)은 `44468ed73`와 `checksumdb.c`/`execute_statement.c`/`locator_sr.c` 세 파일 모두 **diff가 없는 동일 내용**임을 `git diff 44468ed73 3b6ebd1a9`로 확인했습니다(포크 동기화로 커밋 해시만 바뀐 재병합). `#7697`(`9e094324b`)은 `heap_file.c`/`heap_file.h`/`locator_sr.c` 세 파일에 실질적인 새 코드를 추가했으며, 이것이 문제 3을 해소하는 동시에 문제 18을 새로 드러냈습니다.

**신규 발굴 범위**: 동기화 델타 두 커밋의 전체 diff를 라인 단위로 읽었고, 1차 리포트의 17개 문제가 걸려 있던 파일들(`execute_schema.c`, `util_cs.c`, `object_representation_sr.c`, `schema_manager.c`, `schema_system_catalog_install_query_spec.cpp`, `utils.msg`)은 이번 델타의 영향을 받지 않음을 확인해 재검증만 수행했습니다.

**더 찾지 않은 근거**: `#7678`의 새 코드(`is_data_repl_log_enabled`/`spec_has_replication_class`/`pt_spec_repl_class_walk` 등, derived vclass 처리)는 `44468ed73`와 완전히 동일해 1차 리뷰 시점에 이미 검토 대상이었던 코드입니다. `#7697`의 새 코드(`heap_get_class_repl_on`)는 에러 전파 경로, out-parameter 초기화, `OID_ISNULL` 조기 반환, 호출부의 `goto error` 연결까지 모두 직접 추적했고, 문제 18 외의 추가 결함(예: 이중 해제, NULL 역참조)은 발견하지 못했습니다. 이 시점에서 남은 시간을 들여도 억지 지적 외에 새로운 발견이 나올 가능성이 낮다고 판단해 18건(유지 16 + 해소 1 + 신규 1)에서 조사를 마칩니다.

---

## 심각도별 집계

| 심각도 | 건수 | 문제 번호 |
|---|---|---|
| 치명 | 2 | 1, 2 |
| 중요 | 4 | 4, 5, 6, 7 |
| 보통 | 8 | 8, 9, 10, 11, 12, 15, 16, 18 |
| 사소 | 3 | 13, 14, 17 |
| **합계(현재 유효)** | **17** | |
| 해소(참고, 집계 제외) | 1 | 3 (#7697로 해소) |

**재검증 요약**: 유지 16건, 해소 1건, 폐기 0건, 신규 1건 → 최종 유효 문제 17건.
