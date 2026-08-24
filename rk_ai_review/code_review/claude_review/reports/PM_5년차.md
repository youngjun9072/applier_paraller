# CUBRID RK/REPLICATION 기능 코드 리뷰 — PM (5년차)

> **2차 재리뷰 (기준 `734f4959d`)** — 2026-08-23
> 1차 리뷰(기준 `44468ed73`) 이후 브랜치가 upstream과 동기화되어(`b646647ec` 기준 merge-base),
> `#7678`(`3b6ebd1a9`, SBR/checksumdb) · `#7697`(`9e094324b`, 인터럽트 수정)이 새로 들어왔다.
> 1차 리포트의 12개 문제를 새 HEAD 코드에서 전부 재검증하고, 동기화 델타와 전체 diff에서
> 신규 문제를 추가 발굴했다.

## 페르소나 소개

5년차 프로덕트 매니저(PM)로서 이 리뷰에 참여했다. 코드를 직접 짜는 사람은 아니지만, 요구사항이
빠짐없이 구현됐는지(추적성), 에러 메시지·유틸리티 출력이 실제 운영자가 읽고 이해할 수 있는
품질인지, 하위 버전과의 호환성(카탈로그·unload 포맷·기존 DDL 동작)이 깨지지 않는지, 그리고
TODO나 죽은 코드 같은 "미완성 흔적"이 릴리스에 그대로 남아있지 않은지를 본다. 5년차답게 단순
표면 확인에 그치지 않고, 에러가 나는 경로·경계값·다중 절 ALTER 같은 드문 조합·실패 시 정리
(cleanup) 누락까지 파고들었다.

## 총평 (2차)

1차 리포트의 핵심 지적이었던 "다중 절 ALTER TABLE에서 RK 재검증 게이트가 루프 불변값만
본다"(문제 1)는 이번 동기화에서도 전혀 손대지 않아 **그대로 유지**된다 — `do_alter()`가
`crt_clause` 대신 함수 매개변수 `alter`(첫 번째 절)의 코드를 계속 참조한다. 반면 1차에서
가장 심각하다고 봤던 "인터럽트로 인한 조회 실패를 비복제로 오판"하는 문제(구 문제 2)와 그로
인해 증폭되던 반복 호출 문제(구 문제 3)는 **`#7697`이 정확히 이 지점을 근본 수정하면서
해소됐다** — `heap_is_replication_class()`가 `heap_get_class_repl_on()`(int 반환 + out-param)으로
교체되고, 호출부(`locator_add_or_remove_index_internal`)는 `!replicated`를 먼저 검사한 뒤에만
비싼 조회를 하도록 순서가 바뀌었다. 다만 이번 재검증에서 `#7678`(SBR/checksumdb 동기화 델타)
**자신이 도입한 새 코드**(`execute_statement.c`의 `is_replication_class()`)에 바로 그 "조회
실패를 assert(false)+false로 삼키는" 동일한 안티패턴이 다시 심어져 있는 것을 확인했다(신규
문제 14) — 한 PR에서 고친 결함 패턴이 거의 같은 시기에 병합된 다른 PR에서 재발한 사례다.
그 밖에 나머지 9개 문제(4~11, 12 제외)는 코드가 손대지 않아 그대로 유지되고, 진단 리포트
불일치(신규 문제 13)를 추가로 찾았다.

---

## 유지된 문제 (1차 번호 유지)

### 문제 1 — [심각도: 치명] 다중 절 ALTER TABLE에서 RK/FK 재검증이 "맨 첫 번째 절"에만 반응한다

**재검증 결과: 유지 (변경 없음)** — 위치도 동일: `src/query/execute_schema.c:2051`(게이트),
`:1854`(루프 변수 `alter_code` 정의).

**로직 설명**: `do_alter()`는 `crt_clause`로 절을 순회하며 각 반복에서
`const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;`(1854)로 **현재 절**의 코드를
얻는다. 그런데 재검증 게이트는:

```c
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
  {
    need_check_repl_constraint = true;
  }
```

(2051) 여기서 `alter`는 함수 매개변수, 즉 **절 목록의 첫 번째 노드**이며 루프 내내
재할당되지 않는다. 2차 재검증에서도 `do_alter()` 전체를 다시 읽고 `alter`를 재대입하는 코드가
없음을 재확인했다. `IS_REPL_CONSTRAINT_RELATED_ALTER`도 `PT_ADD_ATTR_MTHD`,
`PT_DROP_ATTR_MTHD`, `PT_DROP_CONSTRAINT`, `PT_DROP_PRIMARY_CLAUSE` 4가지만 포함한 채
그대로다(`execute_schema.c:109-114`) — 1차에서 제안했던 `PT_CHANGE_ATTR`, `PT_RENAME_ENTITY`,
`PT_CHANGE_REPLICATION` 추가도 반영되지 않았다.

**문제 시나리오**: (1차와 동일)

```sql
ALTER TABLE t RENAME COLUMN old_pk_col AS new_pk_col, DROP PRIMARY KEY;
```

첫 절 `PT_RENAME_ATTR_MTHD`이 매크로 목록에 없어 `need_check_repl_constraint`가 루프 내내
`false`로 고정되고, 두 번째 절의 `PT_DROP_PRIMARY_CLAUSE`(PK 제거)가 실제로 실행돼도
`check_ha_repl_constraint()`가 호출되지 않는다. HA 모드에서 RK가 없는 복제 테이블이 아무
에러 없이 만들어질 수 있다 — 바로 `#6618`(CBRD-26273)이 막으려던 상황.

**제안**: (1차와 동일) 2051번 줄의 `alter->info.alter.code`를 `alter_code`(1854, 루프 내
실제 처리 코드)로 교체. `IS_REPL_CONSTRAINT_RELATED_ALTER`에 `PT_CHANGE_ATTR`,
`PT_RENAME_ENTITY`, `PT_CHANGE_REPLICATION` 추가.

---

### 문제 4 — [심각도: 중요] `sm_has_non_null_attribute()`가 "구성 컬럼 중 하나라도" NOT NULL이면 통과시켜, 부분 NULL 허용 복합 UNIQUE가 RK로 인정된다

**재검증 결과: 유지 (변경 없음)** — `src/object/class_object.c:95`(매크로, 줄 번호 동일),
`src/object/schema_manager.c:16114-16130`(구현, 줄 번호 동일).

로직·문제 시나리오·제안 모두 1차와 동일하다. `sm_has_non_null_attribute()`는 여전히
"하나라도 NOT NULL인 컬럼이 있는가"만 검사하고(`schema_manager.c:16121-16127`),
`IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로가 이를 그대로 사용한다. `UNIQUE(a, b)`에서 `a`만
NOT NULL이어도 RK로 인정되어, 슬레이브에서 행을 유일하게 식별하지 못하는 문제가 그대로
남아있다.

**제안**: `sm_has_non_null_attribute()`를 "모든 구성 컬럼이 NOT NULL인지" 검사하도록
수정하거나 별도 헬퍼를 신설.

---

### 문제 5 — [심각도: 중요] `checksumdb`에서 복제 억제 해제(`db_set_suppress_repl_on_transaction(false)`) 실패가 메시지 없이 삼켜진다

**재검증 결과: 유지 (변경 없음)** — `src/executables/checksumdb.c:1727-1762`, 줄 번호까지
동일. 흥미롭게도 이번 동기화 델타(`#7678`, `3b6ebd1a9`)의 커밋 메시지 중 하나가 정확히
"checksumdb: handle db_set_suppress_repl_on_transaction errors"인데, 실제로 반영된 것은
`db_set_suppress_repl_on_transaction(true)`(억제 **설정**, 1727) 실패 시 `db_execute` 전에
중단하는 부분뿐이었다(이미 1차 코드에도 있던 처리). 억제 **해제**(`false`, 1741) 실패 경로는
1차 리포트가 지적한 그대로 전용 에러 메시지 없이 `error`에만 대입되고 넘어간다:

```c
res = db_execute (query, &query_result, &query_error);

/* resume row-based replication right after the local execution; keep its result as the error baseline,
 * an actual execution failure below supersedes it */
error = db_set_suppress_repl_on_transaction (false);   /* 실패해도 er_set 없음 */
```

**문제 시나리오·제안**: 1차와 동일 — 네트워크 순단 등으로 해제 요청만 실패하면 체크섬
계산 자체는 성공했는데 원인 설명 없는 에러가 반환된다. `true` 설정 실패와 동일하게 `er_set`
으로 원인(테이블명·청크 id)을 남겨야 한다.

---

### 문제 6 — [심각도: 보통] `rkcheck`의 호스트명 접미사 처리에 "트렁케이션은 나중에"라는 TODO가 미해결로 남아 있다

**재검증 결과: 유지 (변경 없음, 위치만 소폭 이동)** — `src/executables/util_cs.c:3273`(버퍼
선언), TODO 주석은 `:3299`(1차 `:3297-3302` 범위 내, 소폭 이동)에 그대로 있다:

```c
if (strchr (database_name, '@') == NULL)
  {
    /* TODO: Handle truncation explicitly here; keep this in sync with applyinfo() local_database_name build path. */
    snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
    database_name = tmp_database_name;
  }
```

로직·문제 시나리오·제안 모두 1차와 동일 — `snprintf`라 오버플로우는 없지만 긴 DB 이름은
조용히 잘리고, 반환값 검사가 없어 트렁케이션 자체를 감지하지 못한다.

---

### 문제 7 — [심각도: 보통] `do_alter_change_replication()`이 다른 기능의 세이브포인트 이름을 그대로 복사해 쓴다

**재검증 결과: 유지 (변경 없음)** — `src/query/execute_schema.c:11747`,`:11823`, 줄 번호까지
1차와 완전히 동일. `do_alter_change_replication()`이 여전히
`UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`를 세이브포인트 이름으로 재사용한다. 로직·시나리오·제안
동일 — `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 같은 전용 이름 신설 제안 유효.

---

### 문제 8 — [심각도: 보통] TRUNCATE 복제 여부 판정이 REPLICATION=OFF 플래그를 무시하고 RK 존재만 확인한다

**재검증 결과: 유지 (변경 없음)** — `src/query/execute_statement.c:341-384`
(`truncate_need_repl_log()`), 줄 번호 동일. `classobj_find_cons_replication_key()`로 RK
존재만 확인하고 `SM_CLASSFLAG_DATA_REPLICATION_OFF`는 여전히 검사하지 않는다. `REPLICATION=OFF`
테이블도 `TRUNCATE`는 복제 로그를 만들어, 일반 DML(복제 안 됨)과 TRUNCATE(복제 됨)의 동작이
어긋나는 문제가 그대로다.

---

### 문제 9 — [심각도: 보통] `REPLICATION`이 비예약어(식별자 허용) 목록에서 빠져, 새 예약어가 기존 컬럼·테이블명과 충돌한다

**재검증 결과: 유지 (변경 없음)** — `src/parser/csql_grammar.y:1669`(토큰 선언). 이웃 옵션
키워드 `DISK_SIZE`(:20755), `REUSE_OID`(:20882), `REVERSE`(:20883)는 identifier 비예약어
규칙에 등록돼 있지만, `REPLICATION`은 여전히 그 목록에 없다(전체 파일 grep으로 재확인).
`replication`을 컬럼/테이블명으로 쓰던 기존 사용자가 업그레이드 후 문법 에러를 겪는 문제가
그대로 남아있다.

---

### 문제 10 — [심각도: 사소] `find_index_catalog_class()` 함수가 정의만 되고 어디서도 호출되지 않는다

**재검증 결과: 유지 (변경 없음, 정의부 위치만 1줄 이동)** — 전방 선언
`src/object/schema_template.c:120`, 정의 `:5134-5160`(1차 `:5133-5159`, 1줄 이동). LSP
`find_references`로 재확인한 결과 여전히 전방 선언·정의 외 호출부가 없다. static 함수라
외부 링크도 불가능하다.

---

### 문제 11 — [심각도: 사소] `utils.msg` 두 로케일 파일 모두 새 `rkcheck` 사용법 블록 뒤에 공백뿐인 줄과 파일 끝 개행 누락이 남아 있다

**재검증 결과: 유지 (변경 없음)** — 바이트 단위로 재확인(`xxd`): 두 파일 모두
`...\n    `(개행 후 공백 4칸)으로 끝나고 마지막 개행 문자가 없다. en/ko 양쪽 완전히 동일한
형태로 남아있다.

---

## 해소/폐기된 문제

### 구 문제 2 — `heap_is_replication_class()`가 인터럽트로 인한 조회 실패를 "비복제"로 오판한다 → **해소 (#7697)**

`#7697`(`9e094324b`)이 정확히 1차 리포트가 지적한 그 지점을 근본 수정했다.
`src/storage/heap_file.c:11084-11115`의 신규 함수 `heap_get_class_repl_on()`은:

```c
int
heap_get_class_repl_on (THREAD_ENTRY * thread_p, const OID * class_oid, bool * repl_on)
{
  ...
  if (heap_get_class_record (thread_p, class_oid, &recdes, &scan_cache, PEEK) != S_SUCCESS)
    {
      ASSERT_ERROR_AND_SET (error_code);
      heap_scancache_end (thread_p, &scan_cache);
      return error_code;      /* 더 이상 assert(false)+false로 삼키지 않는다 */
    }
  *repl_on = or_class_is_replication_on (&recdes);
  ...
  return NO_ERROR;
}
```

`bool` 반환 대신 `int` 에러코드를 반환하고 판정 결과는 out-param `repl_on`으로 넘긴다.
호출부 `locator_add_or_remove_index_internal()`(`locator_sr.c:8047`)도
`error_code = heap_get_class_repl_on(...)` 후 `error_code == NO_ERROR && repl_on`을 확인하고,
루프 하단에서 `if (error_code != NO_ERROR) goto error;`로 실제 에러(인터럽트 포함)를 트랜잭션에
전파한다. 1차가 지적한 "인터럽트가 KILL QUERY를 무시한 채 커밋될 수 있다"는 문제 자체가
해결됐다.

### 구 문제 3 — `heap_is_replication_class()`가 인덱스 개수만큼 반복 호출된다 → **해소 (#7697)**

같은 수정에서 호출 순서 자체가 바뀌었다. 기존에는 `heap_is_replication_class(...)`가 `&&`
사슬의 앞쪽에 있어 `!replicated`보다 먼저 평가되므로, 이미 복제 로그가 기록된 이후에도 매
인덱스마다 힙 스캔이 반복됐다. 새 코드(`locator_sr.c:8036-8055`)는:

```c
if (error_code == NO_ERROR && need_replication && !replicated
    && or_is_replication_candidate_key (index)
    && !LOG_CHECK_LOG_APPLIER (thread_p) && log_does_allow_replication () == true)
  {
    bool repl_on = false;
    error_code = heap_get_class_repl_on (thread_p, class_oid, &repl_on);
    ...
  }
```

`!replicated`를 먼저(비싼 호출 이전에) 검사하도록 순서를 바꿔, 이미 복제 로그가 기록된
뒤에는(`replicated == true`) `heap_get_class_repl_on()` 자체가 더 이상 호출되지 않는다. 1차가
지적한 반복 호출 문제(및 그로 인한 인터럽트 유실 확률 증폭)는 해소됐다. 다만 코드에 남은
TODO 주석("RK가 이미 결정된 이후에만 검사하도록... 종합적인 리팩토링 필요, EPIC CBRD-26096")은
그대로다 — 복수의 RK 후보 인덱스를 가진(비복제) 테이블에서는 여전히 후보 인덱스 수만큼
호출될 수 있는 좁은 잔여 케이스가 있으나, 1차가 지적한 "매 인덱스 반복"이라는 일반적
문제로서는 더 이상 성립하지 않아 해소로 판정한다.

### 구 문제 12 — 리뷰 대상 diff에 RK/REPLICATION 기능과 무관한 변경이 섞여 있어 변경 단위의 추적성이 떨어진다 → **해소 (merge-base 갱신)**

1차가 지적했던 `log_manager.c`(CDC 카운터), `log_page_buffer.c`(아카이브 정리 대기),
`memory_cwrapper.h`(`cub_aligned_alloc`)는 2차 diff 범위(`b646647ec...HEAD`, 35파일)에
**더 이상 포함되지 않는다** — merge-base가 최신 upstream(`b646647ec`)으로 갱신되면서 그
파일들의 변경이 이미 base 쪽에 들어갔기 때문이다. 새 diff에 남은 비-RK 파일은
`src/query/parallel/px_worker_manager.cpp`(빈 줄 1개 추가)뿐으로, 실질적인 추적성 문제로
보기 어려운 수준이라 해소로 판정한다. (참고: 같은 diff에 새로 등장한 `util_admin.c`,
`util_service.c` 변경은 `rkcheck` CLI 옵션·`hb start` 연동 코드로 RK/REPLICATION 기능 자체에
속하며 무관한 변경이 아니다.)

---

## 신규 문제 (이어서 번호)

### 문제 13 — [심각도: 보통] `ER_HA_REPLICATION_KEY_REQUIRED`(1375) 국문 메시지가 ALTER 상황에서도 "테이블 생성 시"로 고정 표기된다

**위치**: `msg/ko_KR.utf8/cubrid.msg` 1375번 메시지, 사용처 `src/query/execute_schema.c:9870-9871`
(`check_ha_repl_constraint()`)

**로직 설명**: 이번 동기화로 `error_code.h`에 새 에러 4종(`ER_HA_REPLICATION_KEY_REQUIRED`
-1375 등)이 정식 추가된 것을 확인했다(1차 diff에도 있었으나 이번에 메시지 카탈로그 전체를
다시 대조했다). 국문 메시지:

```
1375 HA 복제 제약 위반: 테이블 생성 시 복제 후보 키(기본 키 또는 NOT NULL UNIQUE 제약)가
     필요합니다. 없을 경우 REPLICATION 옵션을 OFF로 설정하십시오.
```

영문 메시지는 "in HA mode"라고만 하고 상황을 특정하지 않는다:

```
1375 HA constraint violation: A replication key candidate (PRIMARY KEY or NOT NULL UNIQUE)
     is required in HA mode. Otherwise, set the replication option to OFF.
```

이 에러를 실제로 발생시키는 `check_ha_repl_constraint()`(`execute_schema.c:9847-9878`)는
`do_create_entity()`뿐 아니라 `do_alter()`(문제 1에서 확인한 :2068)에서도 호출된다 — 즉
**CREATE와 ALTER 양쪽에서 동일하게 발생**하는데, 국문 메시지만 "테이블 생성 시"로 상황을
단정해 버렸다.

**문제 시나리오**: `ALTER TABLE t DROP PRIMARY KEY;`처럼 이미 존재하는 테이블에서 RK가
사라지는 ALTER를 시도해 이 에러를 만난 한국어 사용자는 "테이블 생성 시"라는 문구 때문에
"나는 지금 ALTER를 하고 있는데 왜 생성 시라고 하지?"라고 오인할 수 있다. 영문판 사용자는
이 혼란을 겪지 않으므로 로케일 간 품질이 어긋난다. PR 히스토리(`#6814`)에서 이미 한 차례
"실제 상황과 맞지 않는 에러코드/메시지"를 바로잡은 전례가 있는 영역인데, 이번 신규 에러
메시지 4종을 만들 때 그 교훈이 국문판에는 반영되지 않았다.

**제안**: 국문 메시지에서 "테이블 생성 시"를 삭제하거나 영문판과 동일하게 "HA 모드에서는"
정도로 일반화한다.

---

### 문제 14 — [심각도: 중요] 동기화 델타(#7678)가 도입한 `is_replication_class()`(execute_statement.c)가, `#7697`이 근본 수정한 것과 동일한 "조회 실패를 assert(false)+false로 삼키는" 패턴을 재도입했다

**위치**: `src/query/execute_statement.c:3199-3216`

**로직 설명**: `#7678`(`3b6ebd1a9`, SBR/checksumdb 버그 수정)이 `execute_statement.c`에 새로
추가한 정적 함수다:

```c
static bool
is_replication_class (const char *classname)
{
  DB_OBJECT *class_obj;

  if (classname == NULL)
    {
      return false;
    }

  class_obj = db_find_class (classname);
  if (class_obj == NULL)
    {
      assert (false);
      return false;
    }

  return sm_is_replication_class (class_obj);
}
```

`db_find_class()`가 `NULL`을 반환하는 경우(클래스 이름 해석 실패)를 "이럴 리 없다"고
`assert(false)` 처리한 뒤 그대로 `false`(= "복제 대상 아님")를 반환한다. 이 함수는
`spec_has_replication_class()` → `is_data_repl_log_enabled()`를 거쳐 `USE_SBR` 힌트가 붙은
INSERT/UPDATE/DELETE 문장의 **SBR(Statement-Based Replication) 로그 생성 여부**를 최종
결정하는 값으로 쓰인다(같은 커밋이 도입, `do_execute_statement()`/`do_execute()`에서 호출,
`checksumdb`가 바로 이 경로를 쓰도록 설계됐다는 것이 `#7678`의 커밋 메시지 요지다).

**문제 시나리오**: 정확히 같은 시기(같은 날 병합된)`#7697`이 근본 수정한 문제(=
`heap_is_replication_class()`가 `pgbuf_fix()` 인터럽트로 인한 클래스 레코드 fetch 실패를
`assert(false)+false`로 삼켜 KILL QUERY가 무시되는 버그)와 **완전히 동일한 구조의 결함**이
바로 옆 계층(이름 해석 → `db_find_class`)에 새로 심어졌다. `db_find_class()` 내부도 결국
카탈로그/워크스페이스 조회를 수반하므로 트랜잭션 인터럽트나 일시적 락 대기 실패로 `NULL`을
반환할 수 있는 경로이며, 이 경우:
- 릴리스 빌드에서는 `assert`가 무력화되어 `is_replication_class()`가 조용히 `false`를 반환,
  `spec_has_replication_class()`도 `false`가 되어 **SBR 로그가 생성되지 않는다** — `#7678`이
  고치려던 것과 정반대로, 이번엔 REPLICATION=ON 테이블의 statement가 복제 로그 없이 넘어가
  슬레이브가 그 문장을 놓치는 새로운 divergence 경로가 생긴다.
- 디버그 빌드에서는 `assert(false)`가 그대로 발동해 서버가 abort된다 — `#7697`이 정확히 이
  패턴 때문에 재현했던 코어와 같은 종류다.

`#7697`의 커밋 메시지는 "heap_get_class_record 호출부 28곳 중 실패를 assert(false)로 봉인한
곳은 이 함수가 유일하다"고 명시했는데, 그 조사 시점(2026-08-20 병합) 이후 같은 날 `#7678`이
동기화되며 **또 다른 하나**가 생겨난 셈이다. 두 PR이 병합 순서상 겹치며 서로의 교훈을
반영하지 못한 전형적 사례로 보인다.

**제안**: `is_replication_class()`를 `db_find_class()` 실패 시 호출자에게 에러를 알릴 수
있는 형태(예: 에러코드 반환 + out-param, 또는 최소한 `er_errid()`로 인터럽트 여부를 구분해
그 경우에만 `assert`를 건너뛰는 `#7697` 1단계 수정과 동일한 완화)로 바꾼다. 최소한 이
함수가 SBR 로그 생성 여부라는 복제 정합성에 직결된 값을 반환한다는 점을 감안해, `#7697`이
정리한 "인터럽트 실패를 정상 실패로 문서화" 원칙을 여기에도 적용해야 한다.

---

## 조사 종료 선언 (2차)

이번 2차 재검증에서는:

1. 1차 리포트의 12개 문제를 새 HEAD(`734f4959d`) 코드에서 Read + grep으로 file:line 단위까지
   전부 재대조했다 — 9건은 코드가 손대지 않아 그대로 유지(위치도 대부분 완전히 동일하고,
   2건만 1줄 내외로 이동), 3건은 동기화(`#7697` 2건, merge-base 갱신 1건)로 해소됐음을
   커밋 diff로 직접 확인했다.
2. `#7678`(`3b6ebd1a9`)·`#7697`(`9e094324b`) 두 동기화 델타의 전체 diff를 커밋 메시지까지
   포함해 정독하고, `#7697`이 고친 안티패턴이 `#7678`에서 재발한 지점(문제 14)을 찾아냈다.
3. 새 diff 범위(`b646647ec...HEAD`, 35파일)의 파일 목록을 1차 범위(40파일)와 비교해 무엇이
   빠지고 무엇이 새로 들어왔는지 확인했고(`error_code.h`, `cubrid.msg` 신규 에러 4종 포함),
   그 과정에서 국문 메시지 표기 불일치(문제 13)를 발견했다.
4. `find_index_catalog_class`, `checksumdb` 억제 플래그, `rkcheck` TODO 등 PR 히스토리가
   예고한 취약 지점은 모두 재확인했으며 여전히 미해결임을 확인했다.

더 이상 새로운 문제를 추가하지 않는다. 억지로 개수를 채우기 위한 지적(변수명 취향, 스타일
문제 등)은 배제했다.

---

## 심각도별 집계 (2차)

| 심각도 | 건수 | 문제 번호 |
|---|---:|---|
| 치명 | 1 | 1 |
| 중요 | 3 | 4, 5, 14 |
| 보통 | 5 | 6, 7, 8, 9, 13 |
| 사소 | 2 | 10, 11 |
| **합계** | **11** | |

## 재검증 요약

| 구분 | 건수 | 내용 |
|---|---:|---|
| 유지 | 9 | 1, 4, 5, 6, 7, 8, 9, 10, 11 |
| 해소 | 3 | 2(#7697), 3(#7697), 12(merge-base 갱신) |
| 폐기 | 0 | — |
| 신규 | 2 | 13, 14 |
