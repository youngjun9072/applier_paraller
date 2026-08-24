# RK/REPLICATION 기능 코드 리뷰 — DB엔지니어(DBA/운영) 5년차

> **2차 재리뷰(기준 `734f4959d`)** — 1차 리뷰(기준 `44468ed73`) 이후 브랜치가 upstream과 동기화되어
> `feature/CBRD-26246-develop`의 HEAD가 `734f4959d`(= `44468ed73` + #7678 동기화 병합 `3b6ebd1a9` + #7697 동기화 병합 `9e094324b`)로 바뀌었다.
> diff 범위는 `merge-base(upstream/develop) b646647ec ... HEAD`(35파일, +1,444/−57)이다.
> 아래는 1차 리포트의 문제점을 새 HEAD에서 전부 재확인하고, 동기화 델타(#7678·#7697) 자체와 전체 diff에서
> 추가 발굴을 시도한 결과다.

## 페르소나 소개

5년차 CUBRID DBA/운영 엔지니어. 신규 기능의 문법이나 SQL 의미론보다는 "이 기능이 새벽 3시 장애 상황에서 나를 도와주는가, 아니면 배신하는가"를 본다.
구체적으로는 다음 네 가지 축으로 코드를 읽었다.

1. **rkcheck 등 운영 유틸리티의 견고성** — 에러 처리, exit code, 다중 노드, 대량 테이블 환경에서의 동작.
2. **HA 전환·failover 경로에서의 동작** — 특히 "정상 상태를 가정하고 짠 코드가 비정상 상태를 만나면 어떻게 되는가."
3. **로그·에러 메시지로 장애 원인을 추적할 수 있는가** — 실패했을 때 관리자가 "왜?"를 알 수 있는가.
4. **업그레이드/다운그레이드 시 카탈로그 호환, 대량 스키마에서의 검사 비용**.

## 총평 (2차)

1차에서 지적한 rkcheck의 두 크래시 경로(FK 위반 보고 시 NULL 포인터 역참조, 위반 목록 파일을 못 열었을 때의 NULL FILE*)는 동기화 이후에도 코드가 전혀 손대지지 않아 **그대로 유지**된다. 다중 절 ALTER TABLE의 RK 재검사 게이트가 첫 절의 코드만 보는 버그(`alter->info.alter.code` vs `crt_clause->info.alter.code`)도 동일하게 남아 있다. 반면 1차에서 "PR #6908 리뷰 논점이 재발했다"고 지적한 문제 중 하나 — `locator_add_or_remove_index_internal()`이 `!replicated` 검사보다 heap 조회를 먼저 평가해 인덱스마다 불필요한 heap scan을 반복하던 문제 — 는 이번 동기화가 들여온 #7697 커밋에서 조건식이 재구성되며 **실제로 해소**되었다(§재검증 요약 참고). "메타데이터 조회 실패를 REPLICATION=OFF로 뭉개는" 안티패턴은 여전히 `sm_is_replication_class`/`is_replication_class`/`describe_class` 호출부/`emit_schema` 호출부 네 곳에 남아 있다. 파티션 승격 시 복합키 플래그 소실, 세이브포인트 이름 재사용 등 나머지 항목도 코드 변경이 없어 그대로다. 동기화 델타(#7678의 SBR 판정 로직 재작성, #7697의 인터럽트 전파 수정) 자체는 이미 리뷰 코멘트에 따라 여러 차례 후속 커밋으로 다듬어진 흔적(NULL 안전화, bool 반환 통일, 에러 처리 추가)이 뚜렷했고, 직접 로직을 따라간 결과 이 페르소나 관점에서 새로 지적할 만한 구체적 결함은 찾지 못했다.

---

## 문제 1. [치명] rkcheck가 FK 위반을 보고하는 순간 NULL 포인터 역참조로 크래시한다

**위치**: `src/query/execute_schema.c:9817-9845` (`log_ha_repl_fk_ref_all_replicated`), 호출자 `src/executables/util_cs.c:2911`(`check_fk_constraint`) → `rkcheck()`

**로직 설명**: `log_ha_repl_fk_ref_all_replicated()`는 클래스의 FK 제약을 순회하며, 참조 대상 테이블(`ref_class_mop`)이 REPLICATION=OFF이면 위반으로 기록한다.

```c
if (!sm_is_replication_class (ref_class_mop))
  {
    DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
    fprintf (fp, "%s(%s) -> %s(%s)\n", sm_get_ch_name (class_obj), tmp_c->name,
             sm_get_ch_name (ref_class_mop), pk_c->name);   /* pk_c 가 NULL이면 여기서 크래시 */
    ret++;
  }
```

`db_constraint_find_primary_key()`(`src/compat/db_info.c:1998-2015`)는 주석에 명시된 대로 **"PK가 없으면 NULL을 반환"**한다. 그런데 이 분기에 들어오는 조건 자체가 "`ref_class_mop`이 REPLICATION=OFF"인 경우다. REPLICATION=OFF 테이블은 PK/RK가 아예 없어도 정상 생성 가능하므로, rkcheck가 검출하려는 바로 그 위반 시나리오(외래키 테이블이 참조하는 모든 테이블은 복제 대상이어야 한다) — "PK 없는 OFF 테이블을 FK가 참조" — 가 실제로 발생하면 `pk_c`는 반드시 NULL이 되고, `pk_c->name`에서 크래시한다.

**문제 시나리오**:
1. 싱글 모드에서 `CREATE TABLE customers(id INT) REPLICATION=OFF;`(PK 없음, 허용됨) 후 `orders`가 `customers`를 FK로 참조. `do_alter_change_replication()`이 역방향 FK 참조를 검사하지 않으므로, `customers`가 나중에 `REPLICATION=OFF`로 전환돼도 검사 없이 통과할 수 있다.
2. HA 기동을 위해 `rkcheck`(또는 `cubrid hb start`가 자동 호출하는 rkcheck)가 실행되면, `-f`(FK 체크) 섹션에서 `orders`를 순회하다가 `customers`가 REPLICATION=OFF이고 PK가 없음을 확인 → `pk_c == NULL` → `pk_c->name` 크래시.
3. "위반을 사전에 안전하게 잡아 HA 기동을 막는" 유틸리티가, 정작 위반이 있을 때 코어덤프를 남기고 죽어버려 `cubrid hb start` 자체가 알 수 없는 방식으로 실패한다.

**제안**: `pk_c == NULL`일 때는 "PRIMARY KEY 없음"을 명시하는 문자열로 대체 출력한다(`pk_c != NULL ? pk_c->name : "(no primary key)"`).

---

## 문제 2. [치명] rkcheck가 위반 목록 파일을 열지 못하면 NULL FILE*로 그대로 진행해 크래시한다

**위치**: `src/executables/util_cs.c:2856-2864`(`open_violation_list_file`), `src/executables/util_cs.c:3320`, `:3332-3376`(`rkcheck`)

**로직 설명**: `rkcheck()`는 `db_restart()` 성공 뒤 `fp = open_violation_list_file(...)`로 `.list` 파일을 연다.

```c
fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);
classes = db_get_all_classes ();
...
PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);   /* fp 사용, NULL 체크 없음 */
```

`open_violation_list_file`은 내부적으로 `fopen(file_path, "w")`의 결과를 그대로 리턴하며, 호출부(`rkcheck`) 어디에도 `fp == NULL` 체크가 없다. `PRINT_SECTION_TITLE`/`PRINT_MESSAGE`/`check_rk_constraint`/`log_ha_repl_fk_ref_all_replicated` 등은 모두 이 `fp`에 바로 `fprintf`를 호출한다. glibc에서 `fprintf(NULL, ...)`는 정의되지 않은 동작(대개 세그폴트)이다.

**문제 시나리오**: 로그 디렉터리가 디스크 풀, 권한 문제, 로그 로테이션 직후 심볼릭 링크 깨짐 등으로 쓰기 불가능하면 `fopen`이 NULL을 반환한다. `db_restart()`는 이미 성공해 서버에 연결된 상태이므로, rkcheck는 "정상적으로 시작했지만 로그 파일만 못 만드는" 흔한 운영 사고 패턴에 걸려 그대로 크래시한다. `cubrid hb start` 경로에서 발생하면 자동화 스크립트가 원인(디스크/권한 문제)을 코어덤프 뒤에서 못 찾는다.

**제안**: `fp == NULL`이면 `strerror(errno)`를 포함한 명확한 에러 메시지를 남기고 `db_shutdown()` 후 실패로 종료한다.

---

## 문제 3. [치명] "메타데이터 조회 실패 시 REPLICATION=OFF로 간주"하는 안티패턴이 여러 신규 함수에 반복 이식됨

**위치(모두 이번 diff 범위 신규 코드)**:
- `src/object/schema_manager.c:3394-3407` (`sm_is_replication_class`)
- `src/query/execute_statement.c:3200-3218` (`is_replication_class`, #7678이 SBR 판정 로직을 재작성하며 동일 자리에 다시 정의)
- `src/object/object_printer.cpp:1138` (`describe_class`의 호출부, `sm_is_replication_class` 경유)
- `src/executables/unload_schema.c:1794` (`emit_schema`의 호출부, `sm_is_replication_class` 경유)

**로직 설명**: 네 곳 모두 동일한 형태다. `schema_manager.c:3394`:

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
  return false;   /* "복제 대상 아님"으로 처리됨 */
}
```

`execute_statement.c:3200`의 `is_replication_class()`도 `db_find_class()`가 NULL을 반환하면 `assert(false); return false;`로 동일하다. `assert()`는 release 빌드(NDEBUG)에서 완전히 사라지는 매크로이므로, 프로덕션에서는 이 실패가 로그 한 줄 없이 조용히 "비복제"로 처리된다.

**문제 시나리오**:
- (`sm_is_replication_class`) `do_alter()`의 RK 재검사(`execute_schema.c:2059`)나 `log_ha_repl_fk_ref_all_replicated`가 클래스 fetch 실패(락 타임아웃, 캐시 미스 등 일시적 상황) 시 "비복제"로 오판 → RK 재검사가 통째로 스킵되어 `return NO_ERROR`로 빠질 수 있다.
- (`object_printer.cpp` / `unload_schema.c`) `SHOW CREATE TABLE`이나 `unloaddb` 실행 중 일시적 fetch 실패가 나면 실제로는 REPLICATION=ON인 테이블이 화면/백업 파일에 `REPLICATION=OFF`로 잘못 표시된다(문제 14·15 참조). 운영자가 장애 조사 중 이 출력을 신뢰하면 잘못된 결론에 이르고, `unloaddb`→`loaddb` 재구성 시나리오라면 실제로 테이블이 비복제로 재생성되는 사고로 이어진다.

**제안**: 네 함수 모두 `bool` 대신 에러 코드를 반환하고 실패를 호출자에게 전파하도록 시그니처를 바꿔야 한다. 최소한 release 빌드에서도 남는 `er_set()`/로그 기록을 추가해, "비복제로 판단됨"과 "조회 자체가 실패함"을 구분할 수 있게 해야 한다.

---

## 문제 4. [중요] 다중 절 ALTER TABLE에서 RK 재검사 게이트가 "항상 첫 번째 절의 코드"만 본다

**위치**: `src/query/execute_schema.c:2051`, 매크로 정의 `:109-114`

**로직 설명**: `do_alter()`는 한 ALTER TABLE 문에 여러 절(clause)이 있을 때 `for (crt_clause = alter; ...; crt_clause = crt_clause->next)`로 순회하며 각 절을 실행한다. 절 실행 후 RK 재검사 필요 여부를 다음과 같이 판단한다.

```c
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
  {
    need_check_repl_constraint = true;
  }
```

루프 변수는 `crt_clause`인데, 조건식은 `crt_clause->info.alter.code`가 아니라 **`alter->info.alter.code`**를 본다. `alter`는 함수 인자로 받은, 절 목록의 맨 처음 노드(head)로 루프 내내 고정된 값이다. 즉 이 조건은 몇 번째 절을 처리하는 중이든 항상 "첫 번째 절의 종류"만 검사하며, 두 번째 이후 절이 RK를 깨는 변경(예: `PT_DROP_CONSTRAINT`, `PT_DROP_PRIMARY_CLAUSE`)이어도 첫 번째 절이 그 목록에 없으면 재검사 자체가 트리거되지 않는다.

**문제 시나리오**: `ALTER TABLE t CHANGE COLUMN c c INT COMMENT 'x', DROP PRIMARY KEY;`처럼 RK와 무관한 절이 먼저 오고 RK를 제거하는 절이 뒤에 오는 ALTER 문을 실행하면, 첫 절의 코드가 매크로 목록에 없으므로 `need_check_repl_constraint`가 끝까지 `false`로 남아 `check_ha_repl_constraint()`가 아예 호출되지 않는다. HA 모드에서 유일한 RK를 제거했는데도 검사를 통과해버린다.

**제안**: `alter->info.alter.code`를 `crt_clause->info.alter.code`로 수정한다.

---

## 문제 6. [중요] 파티션 승격(`PROMOTE PARTITION`) 시 복합 PK/UK의 두 번째 이후 컬럼에서 UNIQUE 관련 플래그가 잘못 제거된다

**위치**: `src/query/execute_schema.c:7850-7862`(`has_notnull_unique_constraints`), `:7948-7955`(`do_promote_partition`의 컬럼 순회)

**로직 설명**:

```c
for (smattr = ctemplate->attributes; smattr != NULL; smattr = ...)
  {
    ...
    if (!has_notnull_unique && has_notnull_unique_constraints (smattr))
      {
        has_notnull_unique = true;                 /* 이 컬럼은 보존 */
      }
    else
      {
        smattr->flags &= ~(SM_ATTFLAG_UNIQUE);      /* 이 컬럼은 UNIQUE 플래그 제거 */
        smattr->flags &= ~(SM_ATTFLAG_REVERSE_UNIQUE);
      }
    ...
  }
```

`has_notnull_unique`는 클래스 전체에 걸친 단일 불리언인데, 조건이 `!has_notnull_unique && ...`로 되어 있어 "아직 RK 후보를 하나도 못 찾았을 때만" 개별 컬럼을 보존 대상으로 인정한다. 복합(다중 컬럼) PK나 복합 NOT NULL UNIQUE는 여러 컬럼이 각자 자신의 제약을 걸고 있는데, 순회 중 첫 번째로 만난 컬럼만 `has_notnull_unique = true`로 마킹되며 그 뒤로는 같은 복합 키에 속한 두 번째 이후 컬럼이라도 무조건 else 분기로 빠져 UNIQUE 플래그가 제거된다.

**문제 시나리오**: `PARTITION BY ...` 테이블에 `PRIMARY KEY(a, b)`같은 복합 PK를 두고 특정 파티션을 `PROMOTE PARTITION`으로 독립 테이블화하면, 승격된 테이블에서 `b` 컬럼의 UNIQUE 어트리뷰트 플래그가 소실된다. 스키마 진단 도구나 JDBC `DatabaseMetaData`로 조회하면 잘못된 답을 얻는다.

**제안**: 조건에서 `!has_notnull_unique`를 제거하고, 각 컬럼을 그 컬럼 자신의 `has_notnull_unique_constraints(smattr)` 결과만으로 독립적으로 판단하도록 수정한다.

---

## 문제 7. [중요] `classobj_copy_pk_and_uk_notnull_constraints`가 범용 attribute-copy 경로에 부작용을 만든다

**위치**: `src/object/class_object.c:561-593`(`classobj_copy_pk_and_uk_notnull_constraints`), 호출부 `:4817`(`classobj_init_attribute`, `copy=1` 분기)

**로직 설명**: `classobj_init_attribute()`는 클래스 정의 전반에 걸쳐 쓰이는 공용 복사 루틴이다(뷰 컬럼 별칭 처리 등 RK와 무관한 여러 스키마 연산에서도 쓰인다). 이번 diff는 여기에 새 헬퍼를 추가했다.

```c
if (src->constraints != NULL)
  {
    error = classobj_copy_pk_and_uk_notnull_constraints (src, dest);   /* 새로 constraints를 채움 */
    ...
  }
```

이 헬퍼는 원본과 무관한 새 제약 객체를 만들어 `dest->constraints`에 연결한다. 함수 자체의 코드 주석에 "TODO: 제약 캐시를 복사하거나 destination에서 재생성하는 방법을 고민해야 한다"라고 저자 스스로 불확실성을 남겨두었다. 손댄 지점은 파티션 승격 전용 코드가 아니라 `classobj_init_attribute`라는 범용 함수다.

**문제 시나리오**: `classobj_copy_attribute()`가 호출되는 다른 스키마 연산(CREATE TABLE ... LIKE, 뷰 컬럼 복사 등)에서, 원본과 독립적으로 새로 생성된 제약 객체가 실제 클래스 속성(properties)의 진짜 정의와 다른 BTID/캐시 상태를 갖게 되면, 제약 캐시 불일치로 이어질 잠재 위험이 있다.

**제안**: 파티션 승격에만 필요한 이 로직을 `do_promote_partition()` 전용 헬퍼로 국한시키는 것을 검토한다.

---

## 문제 8. [보통] `do_alter_change_replication()`이 `do_alter_change_tbl_comment()`와 동일한 세이브포인트 이름을 재사용한다

**위치**: `src/query/execute_schema.c:11747`(재사용), 원래 정의 `:11505`, 상수 정의 `:81`

**로직 설명**: 시스템 세이브포인트 이름은 `#define UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT "cHANGEtBLcOMMENT"` 하나뿐인데, `do_alter_change_replication()`이 자신만의 세이브포인트 상수를 만들지 않고 이 기존 상수를 그대로 재사용한다.

**문제 시나리오**: 현재는 `do_alter()`가 다중 절 ALTER 실패 시 항상 최상위 `UNIQUE_SAVEPOINT_MULTIPLE_ALTER`까지 롤백하므로 즉시 데이터 오류로 이어지지는 않는다. 그러나 코드를 읽는 사람이 오인하기 쉽고, 향후 두 절 처리 방식이 얽히는 리팩토링이 있으면 이름 충돌로 인한 잘못된 지점으로의 롤백이 재현될 수 있는 시한폭탄이다.

**제안**: `UNIQUE_SAVEPOINT_CHANGE_TBL_REPLICATION` 같은 전용 상수를 새로 정의해 사용한다.

---

## 문제 9. [보통] rkcheck의 반환값이 음수 에러코드라 프로세스 종료코드로 노출될 때 의미 없는 값으로 잘린다

**위치**: `src/executables/util_cs.c:3387`(`err = ER_HA_REPLICATION_CONSTRAINT_VIOLATION; ...`), `src/base/error_code.h:1771`(`ER_HA_REPLICATION_CONSTRAINT_VIOLATION = -1378`)

**로직 설명**: 위반이 발견되면 `rkcheck()`는 `err = ER_HA_REPLICATION_CONSTRAINT_VIOLATION`(즉 `-1378`)을 그대로 리턴한다. POSIX 프로세스 종료코드는 하위 8비트만 보존되므로 `(-1378) & 0xFF = 158`이 되며, 이 값 자체가 문서화된 의미가 없다.

**문제 시나리오**: 운영팀이 `cub_admin rkcheck mydb; if [ $? -ne 0 ]; then ...` 형태로 자동화 스크립트를 짤 때, "0=정상, 0이 아니면 위반"까지는 동작하지만 RK 위반인지 FK 위반인지, 몇 건인지는 종료코드만으로 구분할 수 없다.

**제안**: rkcheck 전용으로 관례적인 셸 종료코드(0=성공, 1=위반 발견, 2=실행 오류 등)를 별도로 정의해 리턴하고, 상세 원인은 `.err`/`.list` 파일에만 담는다.

---

## 문제 10. [보통] `applyinfo()`가 여전히 `strcpy`/`strcat`로 `@localhost`를 접합한다 — rkcheck는 고쳤지만 같은 파일의 자매 함수는 TODO만 남기고 방치

**위치**: `src/executables/util_cs.c:4095-4097`(diff에서 주석만 추가), 비교 대상 `rkcheck()`의 `:3300-3301`

**로직 설명**: PR #6934 리뷰에서 지적된 문제(`database.txt`에 여러 호스트가 있을 때 `@localhost`를 붙이는 로직의 버퍼 크기 우려)를 이번 diff는 `rkcheck()`에서는 `snprintf`로 안전하게 처리했다. 그런데 같은 파일의 `applyinfo()`는 여전히 예전 방식 그대로다.

```c
/* TODO: Replace strcpy/strcat with bounded formatting and keep behavior aligned with rkcheck() tmp_database_name path. */
strcpy (local_database_name, database_name);
strcat (local_database_name, "@localhost");
```

이번 diff가 이 줄에 TODO 주석을 새로 추가했다는 것은 작성자가 문제를 인지했다는 뜻이다. 그런데 `strcpy`/`strcat`는 그대로 두고 주석만 남겼다. 대상 버퍼(`CUB_MAXHOSTNAMELEN`, 256바이트) 크기를 넘는 입력에 대해 자르지 않고 그대로 덮어써 실제 버퍼 오버플로우를 일으킬 수 있다.

**문제 시나리오**: `database.txt`에 매우 긴 DB 이름이 등록된 상태에서 `cubrid applyinfo`를 실행하면 `local_database_name` 버퍼를 넘는 이름에서 스택 오버플로우가 발생할 수 있다.

**제안**: `applyinfo()`도 `rkcheck()`와 동일하게 `snprintf` 기반으로 통일한다.

---

## 문제 11. [보통] rkcheck의 데이터베이스 이름 `@localhost` 접합이 길이를 넘으면 경고 없이 조용히 잘린다

**위치**: `src/executables/util_cs.c:3300-3301`

**로직 설명**: `rkcheck()`는 `snprintf`를 써서 오버플로우는 막았지만 반환값(잘렸는지 여부)을 확인하지 않는다.

```c
snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
database_name = tmp_database_name;
```

**문제 시나리오**: DB 이름이 길어 `CUB_MAXHOSTNAMELEN`(256바이트)를 초과하면 `tmp_database_name`은 조용히 잘린 문자열이 되고, 이후 `db_restart()`가 존재하지 않는 잘린 이름으로 시도되어 원인과 무관해 보이는 에러 메시지를 관리자가 받게 된다.

**제안**: `snprintf`의 반환값(요구 길이)을 확인해 초과 시 명시적인 에러로 종료한다.

---

## 문제 12. [보통] `check_repl_constraint_violations`가 `db_is_vclass()` 에러로 조기 종료하면 `.list` 파일이 "타이틀만 있고 결과 없음"의 애매한 상태로 남는다

**위치**: `src/executables/util_cs.c:2917-2937`(`check_repl_constraint_violations`), 호출부 `:3333`, `:3349`

**로직 설명**: `check_repl_constraint_violations()`는 `db_is_vclass(c->op)`가 음수(에러)를 반환하면 즉시 그 값을 리턴한다. 이미 RK 섹션 타이틀이 출력된 뒤 클래스 목록 중간에서 에러를 만나면 그 시점까지 순회한 클래스들의 위반 여부만 `.list` 파일에 적힌 채로 함수가 중단되고, FK 섹션은 아예 실행되지 않는다.

**문제 시나리오**: 운영자가 `.list` 파일을 열어봤을 때 RK 섹션은 있는데 FK 섹션이 없으면 "FK 위반이 없어서 안 적힌 것"인지 "검사 도중 에러로 중단된 것"인지 파일만 보고는 구분할 수 없다.

**제안**: 조기 종료 시 `.list` 파일에도 "검사가 중단되었습니다. 상세 원인은 .err 파일을 참고하십시오" 같은 명시적 문구를 남긴다.

---

## 문제 13. [보통] rkcheck가 클래스마다 개별 fetch를 수행해 대량 스키마에서 HA 기동 지연을 유발할 수 있다

**위치**: `src/executables/util_cs.c:2917-2937`(`check_repl_constraint_violations`의 루프), `src/query/execute_schema.c:9818`(`log_ha_repl_fk_ref_all_replicated`)

**로직 설명**: rkcheck는 `db_get_all_classes()`로 얻은 전체 클래스 목록을 순회하며, RK 검사에서는 클래스당 `db_get_constraints()` 한 번, FK 검사에서는 클래스의 FK 개수만큼 `sm_is_replication_class(ref_class_mop)`를 수행한다. `hb start` 직후처럼 캐시가 비어 있는 시점에 수천~수만 개 테이블이 있는 스키마에서는 클래스 fetch가 실질적인 I/O로 이어질 수 있다.

**문제 시나리오**: 테이블이 매우 많은 스키마(파티션 자식 테이블까지 포함하면 쉽게 커진다)에서 `cubrid hb start`를 실행하면 `us_hb_process_rkcheck()`가 매 DB마다 rkcheck를 동기적으로 실행하고 결과를 기다린 뒤에야 다음 단계로 진행한다. failover 후 최대한 빨리 서비스를 복구해야 하는 상황과 충돌할 수 있다.

**제안**: 대량 스키마 환경에서의 rkcheck 소요 시간을 실측해, 필요하다면 배치 조회로 전환하는 것을 검토한다.

---

## 문제 14. [중요] `describe_class`(SHOW CREATE TABLE)가 클래스 조회 실패 시 REPLICATION=OFF로 잘못 표시할 수 있다

**위치**: `src/object/object_printer.cpp:1138-1144`

**로직 설명**: 문제 3에서 다룬 패턴의 구체적 발현 지점이다.

```c
if (sm_is_replication_class (class_op))
  {
    m_buf (", REPLICATION=ON");
  }
else
  {
    m_buf (", REPLICATION=OFF");
  }
```

`sm_is_replication_class()`가 `au_fetch_class_force()` 실패 시 `assert(false)` 후 `false`를 반환하므로, `SHOW CREATE TABLE` 실행 도중 일시적인 클래스 fetch 실패가 있으면 실제로는 ON인 테이블이 화면에 OFF로 표시된다.

**문제 시나리오**: 장애 조사 중인 DBA가 `SHOW CREATE TABLE`을 쳤는데, 하필 그 순간 락 경합/캐시 미스로 fetch가 실패해 `REPLICATION=OFF`로 잘못 표시되면, DBA는 잘못된 결론에 도달해 진짜 원인을 못 보고 지나칠 수 있다.

**제안**: 문제 3과 동일한 방향(에러 전파)으로 해결하되, 최소한 조회 실패 시 `REPLICATION=<조회 실패>`처럼 실패 자체를 드러내야 한다.

---

## 문제 15. [보통] `unloaddb`가 클래스 조회 실패 시 REPLICATION 상태를 잘못 기록해 백업 파일이 오염될 수 있다

**위치**: `src/executables/unload_schema.c:1737-1741`(`au_fetch_class_force` 실패 처리), `:1794-1800`(REPLICATION 출력)

**로직 설명**: `emit_schema()`는 클래스마다 먼저 `au_fetch_class_force()`를 호출해 `class_` 포인터를 얻는다. 실패하면 `class_ = NULL`로 두고 COLLATE 등의 출력은 `class_ != NULL` 가드로 건너뛰지만, REPLICATION 출력 블록은 이 가드 밖에 있어 무조건 실행되며 내부에서 `sm_is_replication_class(cl->op)`를 다시 호출한다. 이 함수 역시 실패하면 조용히 `false`(OFF)를 반환한다.

**문제 시나리오**: 대량 스키마를 `unloaddb`로 백업하는 도중 특정 클래스에서 일시적인 fetch 실패가 발생하면, REPLICATION 절이 `REPLICATION=OFF`로 명시되어 덤프 파일에 기록된다. 이 덤프로 `loaddb`를 수행해 새 노드/재해복구 환경을 구성하면, 원래 REPLICATION=ON이던 테이블이 조용히 비복제 테이블로 재생성된다.

**제안**: `au_fetch_class_force()` 실패가 이미 확인된 클래스에 대해서는 REPLICATION 절도 함께 생략하거나, 최소한 `unloaddb` 자체를 비정상 종료시켜 관리자가 알아채게 해야 한다.

---

## 문제 16. [사소] `do_promote_partition`에 사용되지 않는 지역 변수가 선언되어 있다

**위치**: `src/query/execute_schema.c:7889-7890`

**로직 설명**: `do_promote_partition()`에 `DB_CONSTRAINT *tmp;`와 `SM_CLASS_CONSTRAINT *c;`가 선언되어 있으나, 함수 본문 어디에서도 참조되지 않는다.

**문제 시나리오**: 직접적인 기능 문제는 아니지만, 죽은 변수의 존재는 "이 함수의 로직이 리뷰 과정에서 방향을 바꿨는데 정리가 안 됐다"는 신호로, 문제 6에서 지적한 로직 결함과 같은 뿌리일 가능성을 시사한다.

**제안**: 미사용 변수를 제거한다.

---

## 문제 17. [사소] rkcheck 사용법 메시지 파일에 트레일링 공백과 파일 끝 개행 누락이 있다

**위치**: `msg/en_US.utf8/utils.msg:1382-1390`, `msg/ko_KR.utf8/utils.msg` 동일 위치

**로직 설명**: `MSGCAT_UTIL_SET_RKCHECK` 메시지 블록 끝에 불필요한 공백만 있는 줄과 파일 끝 개행 누락이 있다.

**문제 시나리오**: 실사용에 지장은 없으나, 메시지 카탈로그 파일에 새 항목을 이어 붙이는 향후 작업에서 병합 충돌이나 파싱 실수의 소지가 된다.

**제안**: 트레일링 공백 제거, 파일 끝 개행 추가.

---

## 문제 18. [사소] rkcheck 사용법 메시지가 "`-r`/`-f` 둘 다 생략 시 RK+FK 둘 다 검사한다"는 기본 동작을 문서화하지 않는다

**위치**: `msg/en_US.utf8/utils.msg:1382-1390`, 실제 동작 `src/executables/util_cs.c:2867`(`get_repl_check_flags`)

**로직 설명**: `get_repl_check_flags()`는 `-r`, `-f` 둘 다 지정되지 않으면 `REPL_CHECK_RK | REPL_CHECK_FK`(둘 다 검사)로 기본 설정한다. 그러나 `rkcheck --help` 사용법 메시지에는 이 기본 동작에 대한 설명이 없다.

**문제 시나리오**: 처음 rkcheck를 접하는 운영자가 아무 옵션 없이 실행했을 때, 실제로는 FK 검사까지 함께 수행된다는 것을 모른 채 결과를 해석할 수 있다.

**제안**: 사용법 메시지에 "옵션을 지정하지 않으면 RK/FK를 모두 검사합니다" 한 줄을 추가한다.

---

## 문제 19. [사소] `checksumdb`가 `db_set_suppress_repl_on_transaction(false)` 복구 호출의 실패를 구분해서 알리지 않는다

**위치**: `src/executables/checksumdb.c:1727-1745`

**로직 설명**: `chksum_calculate_checksum()`은 로컬 checksum 쿼리를 실행하기 전 `db_set_suppress_repl_on_transaction(true)`로 행 기반 복제를 억제하고, 실행 직후 다시 `db_set_suppress_repl_on_transaction(false)`로 복구한다.

```c
res = db_execute (query, &query_result, &query_error);

/* resume row-based replication right after the local execution; keep its result as the error baseline,
 * an actual execution failure below supersedes it */
error = db_set_suppress_repl_on_transaction (false);

if (res >= 0)
  {
    ...
  }
```

복구 호출의 반환값은 `error`에 담겨 `db_execute`/`chksum_update_master_checksum`이 모두 성공하면 함수의 최종 반환값으로 그대로 전파된다(완전한 방치는 아니다). 다만 이 특정 실패에 대해서는 별도의 `er_set()` 메시지가 없어, 호출자가 받는 에러코드만으로는 "checksum 쿼리 자체가 실패했다"와 "복제 억제 플래그 복구만 실패했다"를 구분할 수 없다.

**문제 시나리오**: `db_execute()`는 성공했지만 바로 다음의 suppress-해제 호출 자체가 실패하는 극히 드문 경우(예: tdes 상태 이상), 로그에는 checksumdb가 실패했다는 사실만 남고 "왜"는 남지 않는다. 다만 발생 확률이 매우 낮고, checksumdb 자체가 반복적으로 suppress(true)를 재설정하는 구조라 실질 영향은 제한적이다.

**제안**: `db_set_suppress_repl_on_transaction(false)`이 실패했을 때 전용 `er_set()` 메시지를 별도로 남겨 원인 구분이 되게 한다.

---

## 심각도별 집계

| 심각도 | 건수 | 번호 |
|---|---:|---|
| 치명 | 3 | 1, 2, 3 |
| 중요 | 4 | 4, 6, 7, 14 |
| 보통 | 7 | 8, 9, 10, 11, 12, 13, 15 |
| 사소 | 4 | 16, 17, 18, 19 |
| **합계** | **18** | |

---

## 재검증 요약

- **유지 18건**: 문제 1, 2, 3(내용 일부 조정, 아래 참고), 4, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19 — 코드 로직 변경 없이 그대로 유지. util_cs.c는 upstream 동기화로 무관한 코드가 앞부분에 섞여 들어오며 라인 번호가 상당 폭 이동해, 이번 재검증에서 전부 현재 HEAD 기준으로 갱신했다.
- **해소 1건**: **문제 5**("`locator_add_or_remove_index_internal`에서 heap 조회가 `!replicated` 체크보다 먼저 평가되어 인덱스 개수만큼 반복 호출된다") — 동기화가 들여온 #7697 커밋이 해당 조건식을 `error_code == NO_ERROR && need_replication && !replicated && ...` 순서로 재구성하면서, heap 조회 호출 자체를 조건이 모두 참인 `if` 블록 안으로 옮겼다. 이제 `replicated`가 true가 되는 순간부터는 바깥쪽 `&&` 사슬에서 이미 걸러져 heap 조회가 더 이상 호출되지 않는다(`src/transaction/locator_sr.c:8041-8057`). 원래 지적한 반복 호출 문제 자체가 해소되어 리포트에서 제거하고 여기 기록만 남긴다.
- **폐기 0건**: 오판으로 확인되어 삭제한 항목 없음.
- **문제 3 범위 조정**: 발현 지점을 `sm_is_replication_class`, `is_replication_class`, `describe_class` 호출부, `emit_schema` 호출부 네 곳으로 정리했다.

---

## 조사 종료 선언

**훑은 영역**: 1차 리포트의 19개 문제점 전부를 현재 HEAD(`734f4959d`)의 실제 코드로 다시 열어 확인했고, 동기화가 들여온 두 커밋(`3b6ebd1a9` #7678, `9e094324b` #7697)의 diff를 라인 단위로 전부 읽었다 — `checksumdb.c`(suppress-repl 처리), `execute_statement.c`(`is_data_repl_log_enabled`/`spec_has_replication_class`/`get_spec_classname`/`pt_spec_repl_class_walk` 신규 헬퍼 전체), `heap_file.c`, `locator_sr.c`(`locator_add_or_remove_index_internal`)를 모두 확인했다. `#7678`이 새로 만든 SBR 판정 로직(`is_data_repl_log_enabled`)은 UPDATE/DELETE의 실제 수정 대상 spec만 보도록 고치고, 파생 vclass(derived table) 대상까지 훑도록 보강했으며, `parser` NULL 안전화·bool 반환 통일 등 리뷰 코멘트로 여러 차례 다듬어진 흔적이 뚜렷해 이 페르소나 관점(운영 견고성·failover·추적성·대량 스키마 성능)에서 추가로 지적할 구체적 결함을 찾지 못했다.

**중단 근거**: 유지된 18건은 전부 실제 콜체인을 다시 열어 라인 단위로 재확인한 것이고, 새로 발견한 것은 문제 5의 해소 1건뿐이다. 동기화 델타 자체에서 억지로 문제를 만들어내기보다, 실제 코드가 바뀌지 않은 부분은 그대로 유지하고 바뀐 부분은 검증된 사실(해소)만 반영하는 것이 이번 2차 재리뷰의 목적에 부합한다고 판단해 조사를 마친다.
