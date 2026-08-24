# PM 1년차 — RK/REPLICATION 기능 코드 리뷰 (2차 재리뷰, 기준 734f4959d)

> 2026-08-23 upstream 동기화 이후 재검증. 1차 리뷰 범위는 `23789cbfa...44468ed73`였고,
> 이번 2차는 `b646647ec...734f4959d`(merge-base가 upstream/develop 최신으로 갱신됨)를 기준으로
> 1차 문제 17건을 전부 재검증하고, 동기화로 새로 들어온 델타(#7678=`3b6ebd1a9`, #7697=`9e094324b`)와
> 전체 diff에서 신규 문제를 추가 발굴했다.

## 페르소나

CUBRID 입사 1년차 프로덕트 매니저(PM)다. 개발 경력은 짧지만 "코드가 스펙 요구를 빠짐없이 구현했는가", "에러 메시지·유틸리티 출력이 고객에게 나가도 되는 품질인가", "카탈로그·unload 포맷·기존 DDL 동작이 조용히 바뀌지 않는가", "TODO·주석 처리된 코드 같은 미완성 흔적이 남아 있지 않은가"를 체크리스트처럼 확인하는 역할을 맡고 있다. 연차가 낮은 만큼 화려한 아키텍처 판단보다는 "이 코드를 처음 읽었을 때 이해가 되는가", "주석과 실제 동작이 맞는가", "복붙 흔적·오타·짝이 안 맞는 변수/이름이 없는가" 같은, 신입 개발자가 코드 리뷰에서 가장 먼저 걸려 넘어지는 지점을 잡아내는 데 집중했다.

## 재검증 총평

1차에서 지적한 17건 중 **3건이 이번 동기화로 실제로 해소**되었고(문제 3, 6, 8), 나머지 **14건은 새 HEAD 코드에서도 코드를 다시 읽어 동일하게 재현**됨을 확인했다(위치 대부분 그대로, 일부는 몇 줄 밀림). 특히 문제 3과 6은 정확히 1차 리포트가 "PR 히스토리는 고쳤다고 하는데 코드엔 없다"고 지적했던 그 결함이, 이번 동기화로 들어온 `#7697`(`9e094324b`)에 의해 실제로 근본 수정된 것을 코드 레벨에서 직접 확인했다 — `heap_is_replication_class()`(bool 반환)가 `heap_get_class_repl_on()`(int 에러코드 반환 + out-param)으로 교체되었고, `locator_add_or_remove_index_internal()`이 그 에러를 `goto error`로 정상 전파한다. 같은 수정이 부수적으로 문제 6(호출 순서/빈도)도 함께 해결했다. 문제 8(무관 CDC/페이지버퍼 코드 혼입)도 새 merge-base(`b646647ec`)가 develop 최신에 맞춰지면서 diff 범위 자체에서 사라져 해소됐다 — 1차 리포트가 "diff 기준점부터 재확인이 필요하다"고 남긴 우려가 정확히 그 원인이었음이 이번에 증명된 셈이다.

동기화 델타(#7678 SBR/checksumdb, #7697 인터럽트 수정) 자체가 새로 넣은 코드도 라인 단위로 다시 읽었다. 로직 결함은 발견하지 못했으나(에러 전파 경로, `db_set_suppress_repl_on_transaction` 성공/실패 처리 모두 설계 의도대로 동작), 이 델타가 새로 추가한 헬퍼 함수들 사이에서 **문제 12와 동일한 유형의 static 선언 누락**을 하나 더 찾았다(신규 문제 18).

---

## 문제 1 [심각도: 치명] (유지) 여러 절(clause)로 이뤄진 ALTER TABLE에서 복제키 재검사가 "첫 번째 절"의 코드만 보고 결정된다

**위치**: `src/query/execute_schema.c:1854`(지역변수 `alter_code`), `:2051`(재검사 게이트) — 1차와 동일 라인, 재검증 결과 변동 없음.

**로직 설명**: `do_alter()`는 `ALTER TABLE t CLAUSE1, CLAUSE2, ...`처럼 콤마로 나열된 절들을 `crt_clause`로 순회하며 하나씩 실행한다. 각 반복마다 `const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;`로 **현재 절**의 코드를 지역변수에 담아 그 절을 실행하는 데 쓴다(`:1854`). 그런데 절 실행이 끝난 뒤 "이 ALTER가 복제키 관련 절을 포함했는지" 플래그를 세우는 코드는 다음과 같다.

```c
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
  {
    need_check_repl_constraint = true;
  }
```

여기서 검사 대상이 방금 실행한 `crt_clause`(또는 그 코드를 담은 지역변수 `alter_code`)가 아니라 **루프 헤드 노드인 `alter`의 코드**다. `alter`는 ALTER TABLE 문 전체를 대표하는 첫 번째 절의 노드이므로, `alter->info.alter.code`는 루프를 몇 바퀴 돌든 항상 "이 문장의 첫 번째 절이 무엇이었는가"라는 고정값이다. 즉 이 조건은 루프 안에 있을 뿐 사실상 루프 밖에서 한 번 검사하는 것과 동일하게 동작하며, 두 번째 이후 절에서 실제로 무슨 일이 일어났는지는 전혀 보지 않는다.

**문제 시나리오**: `ALTER TABLE t ADD COLUMN c2 INT COMMENT 'x', DROP PRIMARY KEY;`처럼 **PK를 제거하는 절이 두 번째 이후에 오고, 첫 번째 절이 `IS_REPL_CONSTRAINT_RELATED_ALTER` 목록 밖에 있는 코드**라면, 두 번째 절에서 실제로 PK를 삭제했음에도 `need_check_repl_constraint`가 끝까지 `false`로 남아 `check_ha_repl_constraint()`가 아예 호출되지 않는다. 결과적으로 HA 모드에서 REPLICATION=ON 테이블의 유일한 RK를 다른 대체 RK 없이 제거하는 ALTER가 **에러 없이 통과**한다.

**제안**: `IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code)`를 `IS_REPL_CONSTRAINT_RELATED_ALTER (alter_code)`로 수정. 아울러 문제 9에서 지적하는 매크로 목록 자체의 누락(`PT_CHANGE_ATTR`, `PT_RENAME_ENTITY`, `PT_CHANGE_REPLICATION`)도 함께 보완해야 한다.

---

## 문제 2 [심각도: 치명] (유지) NOT NULL REVERSE UNIQUE 제약이 "생성 시점 RK 판정"과 "실행 시점 RK 판정"에서 서로 다르게 취급된다 — 조용히 복제가 되지 않는 테이블이 만들어질 수 있다

**위치**: `src/object/class_object.c:95-98`(`IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로), `src/base/object_representation_sr.c:4694-4710`(`or_is_replication_candidate_key`) — 1차와 동일 라인, 재검증 결과 변동 없음.

**로직 설명**: CREATE/ALTER TABLE 시점에 "이 테이블에 RK가 있는가"를 판정하는 `classobj_has_class_repl_key_constraint()`는 `IS_HA_REPLICATION_KEY_CONSTRAINT(c)` 매크로를 쓴다.

```c
#define IS_HA_REPLICATION_KEY_CONSTRAINT(c) \
  ((c)->type == SM_CONSTRAINT_PRIMARY_KEY || \
    (SM_IS_CONSTRAINT_UNIQUE_FAMILY((c)->type) && \
     sm_has_non_null_attribute((c)->attributes)))
```

`SM_IS_CONSTRAINT_UNIQUE_FAMILY(c)`는 `SM_CONSTRAINT_REVERSE_UNIQUE`도 포함한다. 즉 "NOT NULL REVERSE UNIQUE" 제약만 있는 테이블도 `check_ha_repl_constraint()`의 "RK가 있어야 한다" 검사를 통과해 `CREATE TABLE ... REPLICATION=ON`이 성공한다. 그런데 실제 INSERT/UPDATE/DELETE 경로가 "이 인덱스가 복제키 후보인가"를 판정할 때 쓰는 `or_is_replication_candidate_key()`는 `BTREE_UNIQUE`만 인정하고 `BTREE_REVERSE_UNIQUE`는 즉시 `false`가 된다.

```c
if (index->type == BTREE_PRIMARY_KEY) return true;
if (index->type != BTREE_UNIQUE || index->n_atts <= 0 || index->atts == NULL) return false;
```

**문제 시나리오**: `CREATE TABLE t (c1 INT NOT NULL, CONSTRAINT rc REVERSE UNIQUE (c1)) REPLICATION=ON;`처럼 RK 후보가 NOT NULL REVERSE UNIQUE 하나뿐인 테이블은 DDL 검사를 통과해 정상 생성된다. 그러나 INSERT/UPDATE/DELETE가 발생해도 `or_is_replication_candidate_key()`가 이 인덱스를 후보로 인정하지 않으므로 **복제 로그 자체가 한 줄도 만들어지지 않는다.** 사용자는 `CREATE TABLE ... REPLICATION=ON`이 성공했으므로 당연히 복제되고 있다고 믿게 되지만, 실제로는 마스터에만 데이터가 쌓인다. `rkcheck`도 생성 시점과 동일한(REVERSE UNIQUE를 인정하는) 판정 함수를 쓰므로 이 상태를 위반으로 잡아내지 못한다.

**제안**: `or_is_replication_candidate_key()`의 조건을 `index->type != BTREE_UNIQUE && index->type != BTREE_REVERSE_UNIQUE`로 맞추거나, 반대로 REVERSE UNIQUE를 RK 후보에서 완전히 제외하는 것이 설계 의도라면 `IS_HA_REPLICATION_KEY_CONSTRAINT` 쪽에서 `SM_CONSTRAINT_REVERSE_UNIQUE`를 제외해 판정 기준을 일치시켜야 한다.

---

## 문제 3 [심각도: 치명 → 해소] `heap_is_replication_class()`의 "인터럽트 삼킴" 결함 — #7697 동기화로 근본 수정 확인

**1차 지적**: 리뷰 범위(`23789cbfa...44468ed73`) 코드에는 PR #7697이 문서화한 수정(bool→int 에러코드 + out-param 재설계)이 반영되어 있지 않았고, 옛 `heap_is_replication_class()`(bool 반환, 실패 시 `assert(false); return false;`)가 그대로 남아 있었다.

**재검증 결과**: 이번 동기화로 들어온 `9e094324b`(#7697)를 코드 레벨에서 직접 확인했다. `src/storage/heap_file.c:11085`의 함수가 실제로 `heap_get_class_repl_on(THREAD_ENTRY *, const OID *, bool *repl_on)`으로 교체되었고, 반환 타입이 `int`(에러코드)로 바뀌었으며 `heap_get_class_record()` 실패 시 `ASSERT_ERROR_AND_SET(error_code)`로 실제 에러코드를 반환한다(`ASSERT_ERROR_AND_SET`은 `er_errid()`가 `NO_ERROR`이면 `ER_FAILED`로 강제하므로 항상 0이 아닌 에러코드가 보장된다). 호출부 `locator_sr.c:8047`(`locator_add_or_remove_index_internal`)도 이 에러를 캡처해 `error_code != NO_ERROR`면 `goto error`로 정상 전파하도록 바뀌어 있다(`:8058-8062`). PR 히스토리가 예고한 수정이 정확히 이번 HEAD에 반영되어 있음을 확인했다.

**판정**: **해소**. 더 이상 지적하지 않는다.

---

## 문제 4 [심각도: 치명] (유지) rkcheck의 FK 위반 로그 출력이 참조 테이블에 PRIMARY KEY가 없으면 NULL 포인터를 그대로 역참조한다

**위치**: `src/query/execute_schema.c:9818-9845`(`log_ha_repl_fk_ref_all_replicated`), 특히 `:9837-9839` — 1차와 동일 라인, 재검증 결과 변동 없음.

**로직 설명**:

```c
if (!sm_is_replication_class (ref_class_mop))
  {
    DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
    fprintf (fp, "%s(%s) -> %s(%s)\n", sm_get_ch_name (class_obj), tmp_c->name,
             sm_get_ch_name (ref_class_mop), pk_c->name);
    ret++;
  }
```

`db_constraint_find_primary_key()`는 PK가 없으면 NULL을 반환한다. 그런데 반환값을 검사하지 않고 곧바로 `pk_c->name`에 접근한다.

**문제 시나리오**: FK가 참조하는 대상 테이블이 PK 없이 NOT NULL UNIQUE 제약만 갖고 있는 것은 이 기능의 핵심 개념(RK는 PK 또는 NOT NULL UNIQUE)상 정상적이고 흔히 있을 수 있는 스키마다. 이런 참조 대상 테이블이 REPLICATION=OFF라서 FK 위반으로 잡히는 순간(바로 이 함수가 로그를 남기려는 그 순간) `pk_c`가 NULL이라 `pk_c->name`에서 곧바로 크래시가 난다. `rkcheck`는 `cubrid hb start` 실행 시 자동으로 호출되는 사전 점검 도구이므로, 운영자가 정확히 이 위반을 확인하려는 순간 유틸리티가 죽어버려 "왜 HA가 안 뜨는지" 원인 파악 자체가 막힌다.

**제안**: `pk_c == NULL`이면 PK 대신 FK가 실제로 참조하는 제약(또는 컬럼명, 혹은 "NOT NULL UNIQUE")을 출력하도록 분기 추가. 최소한 크래시 대신 안전한 대체 문자열(예: `"(no PK)"`)을 넣어야 한다.

---

## 문제 5 [심각도: 치명] (유지) rkcheck가 위반 목록 파일을 열지 못했을 때 NULL 파일 포인터로 그대로 fprintf를 호출한다

**위치**: `src/executables/util_cs.c:3320`(`open_violation_list_file` 호출), `:3332` 이하 `PRINT_SECTION_TITLE`/`PRINT_MESSAGE` 사용부 — 1차와 동일 라인, 재검증 결과 변동 없음.

**로직 설명**: `rkcheck()`는 `fp = open_violation_list_file(...)`의 반환값(`fopen()`이 실패하면 NULL)을 검사하지 않고 곧바로 `PRINT_SECTION_TITLE(fp, ...)` 등 `fp`를 쓰는 매크로를 호출한다. 이 매크로들은 결국 `fprintf(fp, ...)`로 전개되며, `fp == NULL`인 상태의 `fprintf`는 정의되지 않은 동작(대부분 세그폴트)이다. 함수 맨 끝에 `if (fp != NULL) { fclose(fp); }`가 있는 것으로 보아 작성자도 NULL 가능성은 인지했지만, 정작 쓰기 시작하는 지점의 검사를 빠뜨렸다.

**문제 시나리오**: 로그 디렉터리가 어떤 이유로든 쓰기 불가능한 상태에서 `cubrid hb start`(또는 `cub_admin rkcheck`)를 실행하면, 위반 유무와 무관하게 `PRINT_SECTION_TITLE`이 항상 먼저 호출되므로 크래시가 난다. HA 기동 직전 자동 점검 경로이므로 운영 영향이 크다.

**제안**: `fp == NULL`이면 즉시 에러 메시지를 출력하고 종료하는 방어 코드 추가.

---

## 문제 6 [심각도: 중요 → 해소] `locator_add_or_remove_index_internal`의 `heap_is_replication_class()` 루프 내 반복 호출 — #7697 동기화로 순서·빈도 모두 해소

**1차 지적**: 인덱스 여러 개를 순회하는 루프에서 `heap_is_replication_class(...)`가 `!replicated`나 `or_is_replication_candidate_key(index)`보다 먼저 평가되어, 이미 복제 로그를 남겼거나 RK 후보가 아닌 인덱스에도 매번 heap scan이 반복됐다(PR #6908이 정확히 이 문제를 "루프 밖으로 빼라"고 지적한 바 있음). 같은 조건을 쓰는 `locator_update_index()`는 순서가 달라 이 문제가 없었다.

**재검증 결과**: `9e094324b`(#7697)가 `locator_add_or_remove_index_internal()`의 조건문을 재구성하면서 이 문제도 함께 해결했다. 현재 `locator_sr.c:8041-8057`은 다음과 같다.

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

`heap_get_class_repl_on()` 호출이 `&&` 사슬 밖, 즉 `!replicated`와 `or_is_replication_candidate_key(index)`를 포함한 다른 모든 조건이 통과된 뒤에만 실행되는 `if` 블록 안으로 옮겨졌다. 이제 `locator_update_index()`(`rk_btid_index == -1 && ... && or_is_replication_candidate_key(index) && heap_is_replication_class(...)`)와 동일한 순서·빈도로 정렬되어, RK 후보가 아니거나 이미 복제 로그를 남긴 인덱스에서는 heap scan이 전혀 발생하지 않는다.

**판정**: **해소**. 더 이상 지적하지 않는다.

---

## 문제 7 [심각도: 중요] (유지) `do_alter_change_replication()`이 자기 전용 세이브포인트를 만들지 않고 COMMENT 변경용 세이브포인트 이름을 그대로 재사용한다

**위치**: `src/query/execute_schema.c:11747`, `:11823`(REPLICATION 변경용), 비교 대상 `:11505`, `:11571`(COMMENT 변경용) — 1차와 완전히 동일한 라인.

**로직 설명**: 이 파일은 각 ALTER 하위 기능마다 고유한 세이브포인트 이름 매크로를 갖고 있다(`:78-82`). 그런데 `do_alter_change_replication()`은 새 매크로를 만들지 않고 `do_alter_change_tbl_comment()`가 쓰는 `UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`(`"cHANGEtBLcOMMENT"`)를 그대로 가져다 쓴다.

**문제 시나리오**: `ALTER TABLE t COMMENT='x', REPLICATION=OFF;`처럼 한 문장에 COMMENT 절과 REPLICATION 절을 함께 지정하면, `do_alter()` 루프 안에서 두 함수가 순서대로 호출되며 **동일한 이름의 시스템 세이브포인트를 두 번 생성**한다. 세이브포인트 이름은 함수 하나에 하나씩 대응한다는 이 파일 전체의 관례를 깨고 있어, 향후 두 함수 중 하나만 롤백 조건을 바꾸는 유지보수가 들어오면 잘못된 지점으로 롤백될 위험을 안고 있다.

**제안**: `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 같은 전용 매크로를 새로 정의해 사용.

---

## 문제 8 [심각도: 중요 → 해소] 이번 diff에 REPLICATION 기능과 무관한 CDC/flashback·메모리 정렬 변경이 섞여 들어와 있던 문제 — 새 merge-base로 diff 범위 자체가 정리됨

**1차 지적**: `log_manager.c`(CDC 아카이브 삭제 동시성), `log_page_buffer.c`, `page_buffer.c`(`pgbuf_status` alignas(64)), `memory_cwrapper.h`(`cub_aligned_alloc`) 등 REPLICATION 기능과 논리적으로 무관한 5개 파일이 리뷰 대상 diff에 섞여 들어와 있어, "이 커밋의 책임 범위가 무엇인가"부터 재확인이 필요하다고 지적했다. 원인으로 "diff 추출 기준점(`23789cbfa`)이 낡아서 develop에 이미 있던 코드가 신규 코드처럼 보이는 것일 수 있다"는 가설을 제시했다.

**재검증 결과**: 이번 2차 리뷰의 새 diff 범위(`b646647ec...HEAD`, 새 merge-base가 upstream/develop 최신에 맞춰짐)를 확인한 결과, 지적했던 4개 파일(`log_manager.c`, `log_page_buffer.c`, `page_buffer.c`, `memory_cwrapper.h`)이 diff에서 **완전히 사라졌다** — 실제로 `b646647ec` 자체가 그 정렬 할당 기능을 담은 커밋(`[CBRD-26964] Add cache-line aligned allocation`)이었고, `b2dc2c68a`([CBRD-26509] CDC 아카이브 보호)도 이미 develop 상에 존재해 새 merge-base에 흡수되었다. 남은 것은 `px_worker_manager.cpp`의 빈 줄 추가 1건뿐이다. 1차 리포트가 제기한 "diff 기준점부터 재확인이 필요하다"는 가설이 정확히 맞았음이 이번 동기화로 증명된 셈이다.

**판정**: **해소**(diff 기준점 갱신으로 무관 코드가 리뷰 범위에서 배제됨). 더 이상 지적하지 않는다.

---

## 문제 9 [심각도: 중요] (유지) 복제 제약 재검사 게이트(`IS_REPL_CONSTRAINT_RELATED_ALTER`)에 RENAME·컬럼 타입 변경·REPLICATION 옵션 변경 자체가 빠져 있다

**위치**: `src/query/execute_schema.c:106-114` — 1차와 완전히 동일한 라인.

**로직 설명**: 문제 1에서 다룬 게이트가 "관련 절"로 인정하는 목록은 다음 4가지뿐이다.

```c
#define IS_REPL_CONSTRAINT_RELATED_ALTER(code)              \
  ( ((code) == PT_ADD_ATTR_MTHD)         ||                 \
    ((code) == PT_DROP_ATTR_MTHD)        ||                 \
    ((code) == PT_DROP_CONSTRAINT)       ||                 \
    ((code) == PT_DROP_PRIMARY_CLAUSE)                     \
  )
```

`PT_CHANGE_ATTR`(컬럼 타입 변경/`MODIFY`·`CHANGE COLUMN`으로 `NOT NULL` 해제 가능), `PT_RENAME_ENTITY`(테이블 이름 변경), `PT_CHANGE_REPLICATION`(REPLICATION 옵션 변경 그 자체) 어느 것도 이 목록에 없다.

**문제 시나리오**: 스펙 필터링 결과표에서 이미 확정된 사안(C-9/2M-6/2m-3)이다. 이번 코드에서 실제 매크로 정의를 직접 재확인한 결과 세 이름이 여전히 코드에 없음을 확인했다. 문제 1의 버그(첫 절 코드만 봄)까지 겹치면, 설령 이 목록에 항목을 채워 넣더라도 "관련 절이 두 번째 이후에 있으면" 여전히 무력화된다는 점에서 두 문제는 함께 고쳐야 한다.

**제안**: 매크로에 `PT_CHANGE_ATTR`, `PT_RENAME_ENTITY`, `PT_CHANGE_REPLICATION`을 추가하고, 문제 1의 수정과 함께 실제로 매 절마다 검사되는지 테스트로 확인.

---

## 문제 10 [심각도: 보통] (유지) `classobj_copy_pk_and_uk_notnull_constraints()`의 문서 주석이 실제와 다른 옛 함수 이름을 가리킨다

**위치**: `src/object/class_object.c:546-561` 부근 — 1차와 동일 위치.

**로직 설명**: 함수 정의 바로 위 주석 블록의 첫 줄은 `classobj_copy_pk_unique_constraints() - Copy PK or NOT NULL UNIQUE constraints`이지만, 실제 함수 이름은 `classobj_copy_pk_and_uk_notnull_constraints`다. 주석에 적힌 이름의 함수는 이 파일 어디에도 존재하지 않는다.

**문제 시나리오**: 컴파일·동작에는 영향 없지만, 이 함수를 처음 보는 개발자가 IDE에서 주석에 적힌 이름으로 검색하면 아무것도 찾지 못한다. 함수 이름을 리팩토링하면서 주석 갱신을 빠뜨린 전형적인 패턴이다.

**제안**: 주석의 함수명을 실제 이름으로 수정.

---

## 문제 11 [심각도: 보통] (유지) `or_class_is_replication_on()`의 주석이 이미 폐기된 옛 매크로 이름을 인용한다

**위치**: `src/base/object_representation_sr.c:782-792` — 1차와 동일 위치.

**로직 설명**:

```c
bool
or_class_is_replication_on (RECDES * record)
{
  int flags = 0;
  int replication_off_flag = 32;	/* SM_CLASSFLAG_REPLICATION_OFF = 32 */
  ...
}
```

실제로 정의된 매크로 이름은 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`다(PR #6477에서 "데이터 복제라는 의미를 강조"하기 위해 리네이밍된 결과물). 이 파일(`src/base/`)은 상위 레이어 헤더를 직접 include할 수 없어 매직넘버 `32`를 하드코딩한 것으로 보이는데, 주석에 적힌 참조용 이름이 이미 없어진 옛 이름 그대로 남아 있다.

**문제 시나리오**: 향후 `SM_CLASSFLAG_DATA_REPLICATION_OFF`의 비트 값이 바뀌거나 플래그가 재배치되면, 이 파일의 `32`도 함께 바꿔야 하는데 주석에 적힌 이름으로 grep해도 진짜 정의를 찾지 못해 이 하드코딩 지점을 놓치기 쉽다.

**제안**: 주석을 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`로 갱신. 가능하면 값 자체를 하드코딩하는 대신 빌드 시점에 두 값이 같은지 확인하는 `static_assert`류 안전장치를 검토.

---

## 문제 12 [심각도: 보통] (유지) 새로 추가된 두 static 헬퍼 함수가 전방선언은 `static`인데 정의에는 `static`이 빠져 있다

**위치**: `src/query/execute_schema.c:417-418`(전방선언), `:9783`(`check_ha_repl_fk_ref_all_replicated` 정의), `:9861`(`check_ha_repl_constraint` 정의) — 1차와 완전히 동일한 라인.

**로직 설명**:

```c
static int check_ha_repl_constraint (DB_OBJECT * class_obj);
static bool check_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj);
```

로 `static` 전방선언해 놓고, 실제 정의부는 `static` 없이 작성되어 있다. C에서는 먼저 나온 `static` 선언이 링키지를 확정하므로 컴파일은 되지만, 정의만 따로 읽으면 마치 다른 파일에서도 호출 가능한 전역 함수처럼 보인다.

**문제 시나리오**: 다른 개발자가 이 함수를 다른 파일에서 호출하려고 시도하면 "이미 비-static으로 정의돼 있으니 되겠지"라고 착각하고 진행하다가, 원래 전방선언이 `static`이라 실제로는 컴파일/링크 에러가 나는 시점에야 문제를 알게 된다. (신규 문제 18에서 정확히 이 유형의 변종을 하나 더 찾았다 — 이번엔 반대로 forward declaration 자체가 아예 없이 `static`이 통째로 빠진 케이스다.)

**제안**: 정의부에도 `static` 키워드를 명시해 전방선언과 일치시킨다.

---

## 문제 13 [심각도: 보통] (유지) `is_replication_class()` 헬퍼가 클래스 조회 실패를 `assert(false)`로 처리해 디버그 빌드에서 예기치 않게 죽을 수 있다

**위치**: `src/query/execute_statement.c:3201-3217`(`is_replication_class`) — 1차와 동일 위치.

**로직 설명**: SBR 대상 판정에 쓰이는 헬퍼다.

```c
static bool
is_replication_class (const char *classname)
{
  DB_OBJECT *class_obj;
  if (classname == NULL) { return false; }
  class_obj = db_find_class (classname);
  if (class_obj == NULL)
    {
      assert (false);
      return false;
    }
  return sm_is_replication_class (class_obj);
}
```

**문제 시나리오**: `db_find_class()`가 실패하는 정상적인(비정상이 아닌) 경로가 하나라도 존재하면, 디버그 빌드에서는 `assert(false)`가 프로세스를 그대로 멈춰 세우고, 릴리스 빌드에서는 `assert`가 컴파일아웃되어 조용히 `false`를 반환한다 — 디버그/릴리스 빌드의 동작이 달라진다는 뜻이다. 이번 재검증에서 `heap_file.c`의 동일 패턴(문제 3)은 #7697로 근본 수정됐지만, 이 함수는 여전히 같은 패턴을 새로 도입한 채 남아 있다 — 즉 "assert(false)로 실패를 삼키는" 설계가 이 커밋 안에서도 아직 완전히 정리되지 않았다는 뜻이다.

**제안**: `db_find_class()` 실패가 정말 불가능하다면 그 근거를 주석으로 남기고, 확신이 없다면 `assert` 대신 안전하게 `false`를 반환(현재도 반환은 하고 있으니 `assert` 제거)하거나 에러를 상위로 전파하는 것을 검토.

---

## 문제 14 [심각도: 보통] (유지) `do_create_partition()`에서 REPLICATION 옵션 상속 코드가 두 분기에 그대로 복붙되어 있다

**위치**: `src/query/execute_schema.c:4957`, `:5189`(2줄 밀림, 1차는 `:4955-4963`, `:5187-5195`) — 재검증 결과 로직 변동 없음, 라인만 살짝 이동.

**로직 설명**: 파티션 자식 테이블을 만드는 두 시점 각각에서 다음과 같은 동일한 블록이 반복된다.

```c
if (!replication_opt)
  {
    error = sm_set_class_flag (newpci->obj, SM_CLASSFLAG_DATA_REPLICATION_OFF, TRUE);
    if (error != NO_ERROR)
      {
        goto end_create;
      }
  }
```

**문제 시나리오**: 당장 두 블록은 동일하게 동작하지만, 향후 REPLICATION=OFF 파티션 상속 로직에 예외 처리나 로깅을 추가해야 할 때 한쪽만 고치고 다른 쪽을 빠뜨리는 실수가 나기 쉬운 구조다.

**제안**: 공통 부분을 작은 헬퍼 함수로 뽑아 두 지점에서 호출.

---

## 문제 15 [심각도: 사소] (유지) `PRINT_MESSAGE` 매크로 정의 끝에 다른 두 매크로와 다르게 불필요한 라인 연속 백슬래시가 남아 있다

**위치**: `src/executables/util_cs.c:106-109`(1차는 `:112-115`, 파일 앞부분 코드 변동으로 6줄 당겨짐) — 재검증 결과 내용 변동 없음.

**로직 설명**: 같은 파일에 나란히 정의된 세 매크로 중 `PRINT_MESSAGE`만 스타일이 다르다.

```c
#define PRINT_MESSAGE(stream, detail)  \
  do {                                                          \
    fprintf ((stream), "%s\n", detail);                                 \
  } while (0)                                                   \

```

`} while (0)` 뒤에도 백슬래시가 붙어 있고, 그 다음이 빈 줄이다. 다른 두 매크로(`PRINT_SECTION_TITLE`, `PRINT_BLANK_LINE`)와 스타일이 다르고, 이 매크로 바로 뒤에 코드를 추가하려는 사람이 실수로 매크로 정의에 이어붙이게 될 위험이 있는 군더더기다.

**제안**: 마지막 줄의 불필요한 백슬래시 제거, 세 매크로의 스타일 통일.

---

## 문제 16 [심각도: 사소] (유지) `utils.msg`의 rkcheck 사용법 메시지가 옵션이 2개인데 "valid option:"(단수)으로 표기되어 있다

**위치**: `msg/en_US.utf8/utils.msg` `MSGCAT_UTIL_SET_RKCHECK` 섹션(파일 끝) — 1차와 동일.

**로직 설명**: 같은 파일 바로 위에 있는 기존 유틸리티(`cleanfiledb` 등)의 메시지는 옵션이 여러 개일 때 `valid options:\n`(복수형)을 쓴다. rkcheck는 `-r`/`-f` 두 옵션이 있는데도 `valid option:`(단수)로 적혀 있다.

**문제 시나리오**: 기능에는 영향이 없지만, `cub_admin rkcheck --help` 출력이 다른 유틸리티들과 일관되지 않은 문구를 보여주는 것은 이번 리뷰 관점(유틸리티 출력의 릴리스 품질) 그대로다.

**제안**: `valid options:`로 통일.

---

## 문제 17 [심각도: 사소] (유지) REPLICATION 토큰이 identifier 비예약어 목록에서 빠져 이웃 키워드들과 취급이 다르다 (스펙 필터링 확정 T-5 재확인)

**위치**: `src/parser/csql_grammar.y`의 `identifier` 규칙(`:20646`부터) — `DISK_SIZE`(`:20755`)와 `REVERSE`(`:20883`)는 이 목록에 있으나 `REPLICATION` 토큰(`:1669` `%token <cptr> REPLICATION`)은 없음. 1차와 완전히 동일한 라인.

**로직 설명**: `csql_lexer.l`이 `replication`을 전용 키워드 토큰으로 인식하도록 추가했는데, `identifier` 문법 규칙에 `REPLICATION`을 다시 식별자로도 허용하는 항목이 빠져 있다. 반면 이번 기능과 무관하게 이미 있던 `DISK_SIZE`, `REVERSE` 같은 예약어들은 이 비예약 목록에 포함되어 있어 기존 컬럼/테이블명으로도 쓸 수 있다.

**문제 시나리오**: `replication`이라는 이름의 컬럼이나 테이블을 이미 갖고 있는 기존 데이터베이스에서, 따옴표 없이 `SELECT replication FROM t`처럼 쓰던 기존 쿼리/애플리케이션 코드가 이번 업그레이드 이후 문법 에러로 깨질 수 있다.

**제안**: `identifier` 규칙에 `REPLICATION` 항목 추가.

---

## 문제 18 [심각도: 보통] (신규, #7678 델타) `is_data_repl_log_enabled()`가 같은 커밋에서 나란히 추가된 형제 함수들과 달리 `static`이 빠진 채 정의됐고 헤더에도 선언이 없다

**위치**: `src/query/execute_statement.c:3304`(`is_data_repl_log_enabled` 정의), 비교 대상 `:3200`(`is_replication_class`, static), `:3221`(`get_spec_classname`, static), `:3232`(`pt_spec_repl_class_walk`, static), `:3271`(`spec_has_replication_class`, static)

**로직 설명**: `#7678`(`3b6ebd1a9`)이 `execute_statement.c`에 SBR 판정용 헬퍼 5개를 한꺼번에 추가했다.

```c
static bool
is_replication_class (const char *classname) { ... }

static const char *
get_spec_classname (PT_NODE * spec) { ... }

static PT_NODE *
pt_spec_repl_class_walk (PARSER_CONTEXT * parser, PT_NODE * node, void *arg, int *continue_walk) { ... }

static bool
spec_has_replication_class (PARSER_CONTEXT * parser, PT_NODE * spec) { ... }

bool
is_data_repl_log_enabled (PARSER_CONTEXT * parser, PT_NODE * statement) { ... }
```

앞의 네 함수는 모두 `static`으로 파일 내부 전용임을 명시했는데, 마지막 `is_data_repl_log_enabled()`만 `static`이 빠져 외부 링키지를 갖는다. 그런데 `src/query/execute_statement.h`에는 이 함수의 `extern` 선언이 없고(호출부는 같은 파일 안의 `do_statement()`(`:3405`)와 `do_execute_statement()`(`:4113`) 두 곳뿐), 파일 앞부분의 static 전방선언 블록에도 이 함수의 선언이 없다. 같은 파일의 형제 예측 함수 `truncate_need_repl_log()`(`:194`에서 `static`으로 전방선언됨)나 `is_stmt_based_repl_type()`(`execute_statement.h:193`에 `extern`으로 정식 공개됨)과 비교하면, `is_data_repl_log_enabled()`는 "파일 내부 전용"도 "정식 공개 API"도 아닌 애매한 상태로 남아 있다. 문제 12에서 지적한 것과 같은 종류의 static 선언 관리 소홀이 이 델타에서 새로 하나 더 생긴 것이다.

**문제 시나리오**: 당장 컴파일이나 동작에는 문제가 없지만(같은 파일 안에서만 쓰이므로), 이 함수가 실제로는 파일 내부 헬퍼인데 외부 링키지를 갖고 있어 링커가 심볼을 노출시키고, 컴파일러의 미사용 static 함수 경고 대상에서도 빠진다. 다른 개발자가 "다른 파일에서도 쓸 수 있는 함수인가 보다"라고 오해하고 `execute_statement.h`에 선언을 추가해 외부에서 호출하기 시작하면, 이 함수가 `parser`/`statement`의 특정 전제(파서가 이미 완전히 컴파일한 트리, `flat_entity_list`가 채워진 상태 등)에 의존하고 있다는 것을 모른 채 잘못된 문맥에서 호출하는 사고로 이어질 수 있다.

**제안**: `static bool is_data_repl_log_enabled (PARSER_CONTEXT * parser, PT_NODE * statement);`를 파일 앞부분의 static 전방선언 블록에 추가하고 정의에도 `static`을 붙인다. 만약 향후 다른 파일에서도 이 판정이 필요하다면 그때 `execute_statement.h`에 `extern` 선언을 정식으로 추가한다.

---

## 조사 종료 선언

이번 2차 재리뷰는 다음을 훑었다.

- **1차 문제 17건 전부 재검증**: 코드를 다시 읽어 위치를 갱신하고 판정을 확정했다(유지 14 / 해소 3).
- **동기화 델타 자체**: `9e094324b`(#7697)의 `heap_file.c`/`heap_file.h`/`locator_sr.c` 변경 전체, `3b6ebd1a9`(#7678)의 `checksumdb.c`/`execute_statement.c`/`locator_sr.c` 변경 전체를 라인 단위로 다시 읽었다. `is_data_repl_log_enabled()`/`spec_has_replication_class()`/`pt_spec_repl_class_walk()`의 에러 전파·NULL 안전성·순회 로직, `chksum_calculate_checksum()`의 `db_set_suppress_repl_on_transaction()` 성공/실패 처리 순서를 직접 따라가며 확인했으나, 문제 18 외에 새로운 로직 결함은 찾지 못했다.
- **새 diff 범위 확인**: `b646647ec...HEAD`의 파일 목록을 develop 히스토리와 대조해, 1차가 지적했던 무관 파일 혼입(문제 8)이 새 merge-base로 실제 해소됐음을 확인했다.
- **메시지·에러코드**: `error_code.h`, `cubrid.msg`, `utils.msg`의 신규 추가분(1375~1378)이 이번 diff 범위 밖(기존 기능 본체에 이미 있던 것)임을 확인해 재지적하지 않았다.

더 뒤지면 사소한 스타일 지적은 계속 나올 수 있으나, "코드가 실제로 하는 일과 문서/주석/이웃 코드가 말하는 바가 다른" 수준의 지적은 이 시점에서 소진됐다고 판단해 여기서 마친다.

---

## 심각도별 집계 (2차 재리뷰 최종)

| 심각도 | 건수 | 번호 |
|---|---:|---|
| 치명 | 4 | 1, 2, 4, 5 |
| 중요 | 2 | 7, 9 |
| 보통 | 6 | 10, 11, 12, 13, 14, 18 |
| 사소 | 3 | 15, 16, 17 |
| **합계** | **15** | |

## 재검증 요약

- **유지**: 14건 (문제 1, 2, 4, 5, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17)
- **해소**: 3건 (문제 3, 6, 8 — 모두 `#7697`/`#7678` 동기화 또는 새 merge-base로 실제 해결됨을 코드로 확인)
- **폐기(오판)**: 0건
- **신규**: 1건 (문제 18)
