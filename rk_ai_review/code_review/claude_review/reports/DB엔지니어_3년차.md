# CUBRID RK/REPLICATION 기능 코드 리뷰 — DB엔지니어(DBA/운영) 3년차

> **2차 재리뷰 (기준 `734f4959d`)** — upstream 동기화 이후 재검증. 1차 리포트(HEAD `44468ed73`) 대비
> 유지 12건 / 해소 2건 / 폐기 0건, 신규 1건. 상세는 문서 맨 끝 "재검증 요약" 참조.

## 페르소나

3년차 DBA/운영 엔지니어. 신규 기능 자체를 설계하기보다, **이 기능이 운영 환경에 배포됐을 때 실제로 무엇이 터질지**를 먼저 본다.
관심사는 다음 네 가지로 좁혔다.

1. `rkcheck` 같은 운영 유틸리티가 **비정상 입력·비정상 환경에서도 죽지 않고, 명확한 exit code/에러 메시지를 남기는가**
2. HA 기동·failover 경로에서 이 검사가 **언제 어떤 조건으로 실행/생략되는가**
3. 장애가 났을 때 **로그·에러 메시지만 보고 원인을 되짚어갈 수 있는가**
4. 대량 테이블/다중 노드 환경에서 이 기능이 **성능·시간 예산을 얼마나 잡아먹는가**

리뷰는 grep으로 끝내지 않고, clangd LSP(정의 점프·참조 추적)로 실제 호출 체인을 따라가며 진행했다.

## 총평 (2차)

1차 리뷰에서 가장 우려했던 것 — "PR 히스토리에 이미 기록된 `heap_is_replication_class()`의 bool-swallow
안티패턴이 리뷰 대상 스냅샷에 그대로 남아 있다"는 지적(구 문제 5·7)은 이번 동기화(`#7697`, `9e094324b`)로
**실제로 해소됐다.** 함수가 `heap_get_class_repl_on()`(에러코드 반환 + out-parameter)으로 바뀌었고,
호출부(`locator_add_or_remove_index_internal`)는 실패를 `goto error`로 정상 전파한다. 부수적으로
`&&` 체인 순서가 `!replicated`를 먼저 보도록 바뀌면서, RK가 이미 확정된 뒤 남은 인덱스에 대해
반복 호출되던 불필요한 heap 접근(구 문제 7)도 함께 없어졌다.

반면 **다중 절 `ALTER TABLE`의 RK 재검증 게이트가 항상 첫 번째 절만 본다**는 문제(문제 1), `rkcheck`의
NULL 파일 포인터 쓰기·FK NULL 역참조(문제 3·4), RK 판정 기준이 DDL 검사와 실제 DML 실행에서 서로
다르다는 문제(문제 6)를 비롯한 나머지 12건은 새 HEAD에서도 코드가 손대지 않아 그대로 유지된다.

새로 발굴한 문제(문제 15)는 이번 동기화가 가져온 SBR 버그 수정(`#7678`, `3b6ebd1a9`) 자체에서 나온
것이다. 팀이 `heap_is_replication_class`에서 막 걷어낸 바로 그 "카탈로그 조회 실패를 bool로 삼켜
false로 답한다"는 패턴이, 같은 날 커밋된 클라이언트 측 신규 함수 `is_replication_class()`에 그대로
재도입되어 있다. 서버 측 사례처럼 실측으로 증명된 것은 아니라 심각도는 한 단계 낮춰 잡았지만, 팀이
방금 근본 원인을 규명하고 고친 안티패턴이 같은 기능 영역에 다시 나타났다는 점에서 짚어둔다.

---

## 문제 1 — [치명] 다중 절 `ALTER TABLE`에서 RK 재검증 게이트가 항상 "첫 번째 절"의 코드만 검사한다

**재검증**: 유지. 새 HEAD에서도 동일한 줄에 동일한 버그가 있다.

**위치**: `src/query/execute_schema.c:1851`(루프 시작), `:1854`(절별 `alter_code` 지역변수), `:2051`(재검증 게이트)

**로직 설명**: `do_alter()`는 `for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next)`로
콤마로 나열된 ALTER 절들을 순회한다(`:1851`). 각 반복에서 `const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;`
(`:1854`)로 **현재 절**의 코드를 뽑아 switch문을 태우고 실제 DDL을 수행한다. 그런데 절 처리가 끝난 뒤 RK
재검증 여부를 결정하는 코드는 다음과 같다.

```c
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
  {
    need_check_repl_constraint = true;
  }
```

여기서 쓰인 것은 루프에서 매번 갱신되는 `crt_clause`/`alter_code`가 아니라, 함수 진입 시 고정된
**`alter`(연결리스트의 첫 노드, 함수 파라미터)**다. `alter`는 루프 안에서 절대 재대입되지 않으므로
`alter->info.alter.code`는 몇 번째 절을 처리 중이든 항상 **연결리스트의 첫 번째 절의 코드**다.
`IS_REPL_CONSTRAINT_RELATED_ALTER`는 `PT_ADD_ATTR_MTHD`/`PT_DROP_ATTR_MTHD`/`PT_DROP_CONSTRAINT`/
`PT_DROP_PRIMARY_CLAUSE`만 재검증 대상으로 인정한다(`:109-114`).

**문제 시나리오**: `ALTER TABLE t CHANGE COLUMN c c INT COMMENT 'x', DROP PRIMARY KEY;`처럼, RK를 실제로
제거하는 절(`DROP PRIMARY KEY` → `PT_DROP_PRIMARY_CLAUSE`)이 **두 번째 이후**에 오고 첫 번째 절이
`IS_REPL_CONSTRAINT_RELATED_ALTER` 목록에 없는 종류(코멘트 변경, 소유자 변경, RENAME 등)이면,
`alter->info.alter.code`는 끝까지 그 첫 번째 절의 코드로 고정되어 `need_check_repl_constraint`가
결코 `true`가 되지 않는다. 결과적으로 `check_ha_repl_constraint()`가 **한 번도 호출되지 않은 채** PK가
삭제된 상태로 커밋된다. HA 모드에서 REPLICATION=ON 테이블이 RK 없이 남게 되어, 이후 모든 DML이
복제되지 않거나(§문제 6 참조) 슬레이브 적용 시 대상 행을 찾지 못하는 장애로 이어진다. `#6637`에서
"여러 clause를 한 문장에 나열해 PK를 교체하는 패턴을 지원"하려고 검사 위치를 `do_alter()`로 옮긴
바로 그 취지가, 절 순서에 따라 다시 무력화되는 셈이다.

**제안**: `alter->info.alter.code` → 루프 지역 변수 `alter_code`(즉 `crt_clause->info.alter.code`)로
교체한다. 한 줄짜리 수정이지만 이 기능의 핵심 불변조건과 직결된다.

---

## 문제 2 — [치명] `ALTER TABLE ... DROP INDEX`로 RK를 제거해도 재검증 게이트에 아예 걸리지 않는다

**재검증**: 유지. `IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로에 여전히 `PT_DROP_INDEX_CLAUSE`가 없다.

**위치**: `src/query/execute_schema.c:109-114`(`IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로), `:2012-2014`
(`PT_DROP_INDEX_CLAUSE` 분기), `:1707-1753`(`do_alter_clause_drop_index`)

**로직 설명**: CUBRID는 UNIQUE 제약을 `CONSTRAINT UNIQUE(...)` 문법뿐 아니라 `CREATE UNIQUE INDEX`/
`ALTER TABLE ... ADD INDEX ... UNIQUE` 문법으로도 만들 수 있고, 이렇게 만든 UNIQUE 인덱스도
`db_get_constraints()`가 `SM_CONSTRAINT_UNIQUE` 타입으로 동일하게 돌려준다(`IS_HA_REPLICATION_KEY_CONSTRAINT`가
이 타입을 RK 후보로 인정). 이런 UNIQUE 인덱스를 지우는 절은 파서 단계에서 `PT_DROP_CONSTRAINT`가 아니라
**별도의 `PT_DROP_INDEX_CLAUSE`**로 분류되고, `do_alter()`의 switch문에서 `do_alter_clause_drop_index()`
(`:2013`)로 라우팅되어 실제 드롭을 수행한다. 그런데 `IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로(`:109-114`)의
목록에는 `PT_DROP_CONSTRAINT`/`PT_DROP_PRIMARY_CLAUSE`만 있고 **`PT_DROP_INDEX_CLAUSE`는 없다**.

**문제 시나리오**: PK 없이 `NOT NULL UNIQUE` 인덱스 하나만으로 RK 자격을 얻은 REPLICATION=ON 테이블에서,
`ALTER TABLE t DROP INDEX uq_idx;`(CONSTRAINT 문법이 아니라 INDEX 문법으로 만든 그 유일한 유니크
인덱스를 지우는 경우)를 실행하면 — 문제 1의 게이트 버그와 무관하게, 애초에 `PT_DROP_INDEX_CLAUSE`가
목록에 없으므로 **단일 절짜리 ALTER TABLE이라도** 재검증이 걸리지 않는다. 이 테이블은 이제 RK가
하나도 없는데도 REPLICATION=ON 상태로 정상 커밋되며, `#6618`이 만들려 했던 "RK를 지우면 대체 RK가
있는지 검사한다"는 보호장치가 이 경로에서는 전혀 동작하지 않는다.

**제안**: `IS_REPL_CONSTRAINT_RELATED_ALTER`에 `PT_DROP_INDEX_CLAUSE`를 추가하거나, `do_alter_clause_drop_index()`
내부에서 드롭 대상이 UNIQUE였을 때 직접 `need_check_repl_constraint`에 준하는 처리를 하도록 한다.

---

## 문제 3 — [치명] `rkcheck`: 위반목록 파일 오픈에 실패하면 NULL 파일 포인터로 그대로 쓰기를 시도해 죽는다

**재검증**: 유지. `open_violation_list_file()`의 반환값은 새 HEAD에서도 어디서도 NULL 체크되지 않는다.

**위치**: `src/executables/util_cs.c:2855-2864`(`open_violation_list_file`), `:92-110`(`PRINT_SECTION_TITLE`/
`PRINT_BLANK_LINE`/`PRINT_MESSAGE` 매크로), `:3320`(호출부), `:3332-3391`(사용부), `:3403-3406`(`fp != NULL`
체크가 있는 유일한 지점)

**로직 설명**: `rkcheck()`는 `db_restart()`로 서버 접속에 성공한 **직후** `fp = open_violation_list_file(...)`
(`:3320`)로 `$CUBRID/log` 밑에 `<db>_rkcheck_YYYYMMDD_HHMM.list` 파일을 `fopen(..., "w")`으로 연다.
이 반환값은 **어디서도 NULL 체크되지 않는다**. 이어서 RK/FK 검사 루프 전후로 `PRINT_SECTION_TITLE(fp, ...)`,
`PRINT_MESSAGE(fp, ...)`, `PRINT_BLANK_LINE(fp)`가 무조건 호출되는데, 이 매크로들은 전부
`fprintf((stream), ...)` 한 줄짜리 래퍼다(`:92-110`). `fp`가 NULL이면 `fprintf(NULL, ...)`이 되어
정의되지 않은 동작(대부분 SIGSEGV)이다. `end1:` 라벨에서만 `if (fp != NULL) fclose(fp);`로 NULL
체크를 하고 있어(`:3403-3406`), 애초에 "fp가 NULL일 수 있다"는 것을 작성자가 인지는 했지만 **쓰기
시점의 체크를 빠뜨린** 형태다.

**문제 시나리오**: `$CUBRID/log` 디렉터리 퍼미션 문제, 디스크 풀(disk full), 로그 볼륨이 read-only로
마운트된 경우 등 — 운영 환경에서 흔히 발생하는 조건에서 `fopen`이 실패한다. 이 유틸리티는 `cubrid hb start`
시 `us_hb_process_rkcheck()`가 자동으로 호출하므로, **HA 기동 전 사전 점검 도구가 디스크 문제 때문에
먼저 죽어버리는** 상황이 된다. DBA 입장에서는 "hb start가 왜 안 되지" 하고 살펴봤더니 rkcheck가
코어를 남겼다는, 원인 추적을 한 단계 더 어렵게 만드는 실패 모드다.

**제안**: `fopen` 실패 시 명확한 에러 메시지(`PRINT_AND_LOG_ERR_MSG`)를 남기고 `err = ER_FAILED; goto end1;`로
안전하게 종료하도록 NULL 체크를 추가한다.

---

## 문제 4 — [치명] `rkcheck`의 FK 검사가, 참조 대상 테이블에 PK가 없으면 NULL 포인터를 역참조한다

**재검증**: 유지. 새 HEAD에서도 `pk_c` NULL 체크가 없다.

**위치**: `src/query/execute_schema.c:9817-9845`(`log_ha_repl_fk_ref_all_replicated`), 특히 `:9837-9839`

**로직 설명**: `rkcheck -f`(또는 기본 실행)는 각 복제 테이블의 FK들을 순회하며, 참조하는(부모) 테이블이
복제 대상이 아니면 위반으로 기록한다.

```c
if (!sm_is_replication_class (ref_class_mop))
  {
    DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
    fprintf (fp, "%s(%s) -> %s(%s)\n", sm_get_ch_name (class_obj), tmp_c->name,
             sm_get_ch_name (ref_class_mop), pk_c->name);
    ret++;
  }
```

`db_constraint_find_primary_key()`는 제약 목록에 `SM_CONSTRAINT_PRIMARY_KEY` 타입이 없으면 **NULL을
리턴**하는 것이 정상 동작이다(문서화된 계약). 그런데 CUBRID의 FK는 부모 테이블의 PK뿐 아니라 UNIQUE
제약도 참조할 수 있고, 이 기능 자체가 "PK가 없어도 NOT NULL UNIQUE만으로 RK가 성립한다"는 것을
전제로 설계됐다(`#6467`). 즉 부모 테이블이 PK 없이 `NOT NULL UNIQUE`만 갖고 그 컬럼을 FK가 참조하는
구성이 이 기능 자체가 정당한 스키마로 인정하는 형태인데, 이 진단 출력 코드는 그 경우 `pk_c`가 NULL이
되는 걸 검사하지 않고 바로 `pk_c->name`을 읽는다.

**문제 시나리오**: `CREATE TABLE parent (id INT NOT NULL UNIQUE) REPLICATION=OFF;` / `CREATE TABLE child
(pid INT, FOREIGN KEY (pid) REFERENCES parent(id)) REPLICATION=ON;` 같은, 이 기능이 지원한다고 주장하는
정확히 그 스키마 조합에서 `rkcheck`(또는 `hb start`가 자동으로 부르는 rkcheck)를 실행하면 FK 위반을
"기록"하려는 순간 NULL 역참조로 죽는다.

**제안**: `pk_c == NULL`이면 참조 제약이 PK가 아니라 UNIQUE라는 뜻이므로, 해당 UNIQUE 제약을 별도로
찾아 이름을 출력하거나 최소한 `"(unique key)"` 같은 안전한 대체 문자열을 쓰도록 방어 코드를 추가한다.

---

## 문제 6 — [중요] "RK가 있는지" 판정 기준이 DDL 검사(느슨)와 실제 복제 실행(엄격)에서 서로 달라, 생성은 성공하지만 DML이 조용히 전혀 복제되지 않는 조합이 존재한다

**재검증**: 유지. 두 판정 함수 모두 새 HEAD에서 변경되지 않았다.

**위치**: `src/object/class_object.c:95-98`(`IS_HA_REPLICATION_KEY_CONSTRAINT`), `src/object/schema_manager.c:16115-16130`
(`sm_has_non_null_attribute` — "하나라도 NOT NULL"), `src/base/object_representation_sr.c:4693-4722`
(`or_is_replication_candidate_key` — "전부 NOT NULL"), `src/transaction/locator_sr.c:8041-8056`(INSERT/DELETE
경로), `src/storage/btree.c:8263-8307`(`btree_get_rkey_btid`)

**로직 설명**: 두 판정 함수의 실제 사용처를 추적하면 기준이 다르다는 게 드러난다.

- **CREATE/ALTER 시점, `rkcheck`**: `classobj_has_class_repl_key_constraint()` → `IS_HA_REPLICATION_KEY_CONSTRAINT(c)`
  매크로가 `sm_has_non_null_attribute((c)->attributes)`를 쓰는데, 이 함수는 "구성 컬럼 중 **하나라도**
  NOT NULL이면" 참을 반환한다. 즉 `UNIQUE(a, b)`에서 `a`만 NOT NULL이고 `b`는 NULL 허용이어도 "RK 있음"으로
  통과된다.
- **실제 DML 복제 실행 시점**: `or_is_replication_candidate_key()`(서버 측)는 인덱스의 **모든** 구성
  컬럼이 `is_notnull`일 때만 참이다. 이 함수는 `btree_get_rkey_btid()`와 `locator_sr.c:8041`/`locator_update_index`
  (INSERT/DELETE/UPDATE 시 실제로 복제 로그를 쓸지 결정하는 지점) 양쪽에서 실제 판정 기준으로 쓰인다.

**문제 시나리오**: `CREATE TABLE t (a INT NOT NULL, b INT, UNIQUE(a,b)) REPLICATION=ON;` — HA 모드에서도
CREATE는 통과하고(`IS_HA_REPLICATION_KEY_CONSTRAINT`가 "하나만 NOT NULL"을 허용하므로), `rkcheck`도
위반으로 잡지 않는다(같은 매크로 사용). 그런데 실제 INSERT/DELETE 시 인덱스 순회 루프(`locator_sr.c:8041`)에서
이 UNIQUE 인덱스는 `or_is_replication_candidate_key()`(전부 NOT NULL 요구)를 통과하지 못하므로
`replicated`가 끝내 `true`가 되지 않는다 — **그 테이블에 PK가 따로 없다면, 모든 INSERT/DELETE가 복제
로그를 한 줄도 남기지 않는다.** `heap_get_class_repl_on()`은 여전히 참(복제 대상)이라고 답하는데도
실제로는 복제되지 않는, 겉보기엔 정상인데 슬레이브만 계속 비어가는 조용한 장애다.

**제안**: `sm_has_non_null_attribute()`를 "구성 컬럼 전부 NOT NULL"로 강화하거나(그러면 CREATE 단계에서
애초에 막힘), 최소한 `check_ha_repl_constraint()`가 `or_is_replication_candidate_key()`와 동일한 기준을
쓰도록 통일한다. 두 기준이 다르면 DDL이 보장한다고 믿는 것과 런타임이 실제로 하는 것이 어긋난다.

---

## 문제 8 — [중요] `rkcheck`의 `database_name@localhost` 조합 버퍼가 여전히 오버런 가능성을 안고 있다 (PR #6934 TODO 미해결)

**재검증**: 유지. 코드·주석 모두 변경 없음.

**위치**: `src/executables/util_cs.c:3273`(`char tmp_database_name[CUB_MAXHOSTNAMELEN]`), `:3297-3302`

**로직 설명**:

```c
char tmp_database_name[CUB_MAXHOSTNAMELEN];   /* 256 */
...
if (strchr (database_name, '@') == NULL)
  {
    /* TODO: Handle truncation explicitly here; ... */
    snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
    database_name = tmp_database_name;
  }
```

`CUB_MAXHOSTNAMELEN`은 256이다. CUBRID 데이터베이스 이름은 최대 255자까지 허용되는데, `"@localhost"`
(10자)까지 합치면 최악의 경우 265자로 256을 초과한다. `snprintf`라서 버퍼 오버플로 자체는 없지만,
**조용히 잘린 이름**이 그대로 `check_database_name()`/`db_restart()`에 전달된다. 이 이슈는 PR `#6934`
리뷰에서 vimkim이 MAJOR로 지적했고, 저자가 "마이너한 리뷰라 바로 머지"하며 TODO로 남긴 것과 정확히
같은 코드다.

**문제 시나리오**: DB 이름을 255자 가까이 길게 짓는 것은 흔치 않지만, 자동화 스크립트가 이름 규칙으로
긴 이름을 생성하는 조직에서는 실제로 발생할 수 있다. 이 경우 `rkcheck`가 엉뚱하게 잘린 이름으로 접속을
시도해 "그런 DB 없음" 류의 오류를 내며, 원인이 "이름이 너무 길어서 잘렸다"는 것을 로그만 보고는 알기
어렵다.

**제안**: `snprintf`의 리턴값(요구된 길이)을 검사해 버퍼 크기를 초과하면 명시적으로 에러 메시지를
내고 종료한다. `#6934`에서 남긴 TODO를 이번 기회에 해소할 것을 권한다.

---

## 문제 9 — [중요] `cubrid hb start`가 호출하는 `rkcheck`에 타임아웃이 없어, 문제 있는 DB 하나가 전체 HA 기동을 무기한 지연시킬 수 있다

**재검증**: 유지. `us_hb_process_rkcheck()`의 `proc_execute(... wait_child=true ...)` 호출부에 여전히
타임아웃 처리가 없다.

**위치**: `src/executables/util_service.c:3193-3238`(`us_hb_process_rkcheck`), `:3233`(`proc_execute` 호출부),
`:5041-5043`(호출 지점)

**로직 설명**: `us_hb_process_rkcheck()`는 `ha_conf->db_names`에 등록된 각 DB에 대해 순차적으로
`proc_execute(UTIL_ADMIN_NAME, rkcheck_args, true, false, false, NULL)`을 호출한다. 세 번째 인자
`wait_child=true`는 자식 프로세스(=`rkcheck` 서브프로세스)가 끝날 때까지 블로킹 대기함을 의미하며,
이 호출 경로 어디에도 타임아웃 처리가 없다. 이 함수는 `us_hb_copylogdb_start()`보다 **먼저** 호출되므로,
HA 프로세스(copylogdb/applylogdb 등) 기동 자체가 이 사전 점검이 끝나야 진행된다.

**문제 시나리오**: 특정 DB의 볼륨이 손상되었거나, 스토리지 I/O가 멈췄거나, 락 경합으로 `db_restart()`가
오래 걸리는 상황에서 `rkcheck`가 그 DB에 대해 멈춰버리면, `cubrid hb start` 명령 자체가 응답 없이
걸려버린다. 여러 DB를 서비스하는 노드에서 한 DB의 장애가 나머지 정상 DB들의 HA 기동까지 지연시키는,
장애 반경(blast radius)이 넓어지는 경우다.

**제안**: `proc_execute` 호출에 상한 시간을 두거나, `hb start`가 rkcheck 단계에 자체 타임아웃을 걸어
"특정 DB 점검이 N초 이상 걸리면 실패로 간주하고 스킵/보고" 하도록 한다.

---

## 문제 10 — [중요] `sm_is_replication_class()`가 NULL/조회 실패를 `assert(false)` + `false`로 조용히 처리한다

**재검증**: 유지. 코드 변경 없음.

**위치**: `src/object/schema_manager.c:3395-3407`(`sm_is_replication_class`)

**로직 설명**:

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

`op == NULL`이거나 `au_fetch_class_force()`가 실패(권한 문제, 존재하지 않는 클래스, 인터럽트 등)하면
`assert(false)`(release 빌드에서는 무시) 후 `false`("REPLICATION=OFF")를 반환한다. 이 함수는
`check_ha_repl_fk_ref_all_replicated()`(FK 참조 대상이 복제 클래스인지 판정)와
`log_ha_repl_fk_ref_all_replicated()`(`rkcheck -f`가 쓰는 실제 카운트 함수)에서
`ws_mop(&(tmp_c->fk_info->ref_class_oid), NULL)`의 결과에 바로 적용된다.

**문제 시나리오**: FK가 참조하는 클래스의 OID가 일시적으로 workspace에서 해석되지 않거나(`ws_mop`이
NULL 반환), `au_fetch_class_force`가 권한/락 문제로 실패하는 경우 — 이 함수는 "그 부모 테이블은
REPLICATION=OFF"라고 **확정적으로** 답해버린다. `check_ha_repl_constraint()`/`rkcheck` 양쪽 모두 이
값을 근거로 FK 위반 여부를 판단하므로, 일시적 조회 실패가 "영구적인 정책 위반"으로 둔갑해 CREATE
TABLE이 부당하게 거부되거나(오탐), 반대로 실제 문제가 있는데도 원인이 은폐된 채 다른 에러로 보고될
수 있다.

**제안**: 최소한 `au_fetch_class_force` 실패 시 `er_errid()`를 로그에 남기도록 하거나, 이 함수를
호출하는 상위 로직이 "확실히 OFF"와 "조회 실패"를 구분할 수 있는 시그니처로 바꾼다.

---

## 문제 11 — [보통] `SM_CLASSFLAG_DATA_REPLICATION_OFF` 값(32)이 계층을 건너뛰어 매직넘버로 중복 정의되어 있다

**재검증**: 유지. 코드·주석 모두 변경 없음(주석의 상수명도 여전히 옛 이름).

**위치**: `src/base/object_representation_sr.c:782-791`(`or_class_is_replication_on`), 원본 정의는
`src/object/class_object.h:312`

**로직 설명**: `src/base`는 `src/object`보다 하위 계층이라 `class_object.h`를 인클루드할 수 없다
(레이어링 제약). 그래서 `or_class_is_replication_on()`은 다음과 같이 값을 그대로 베껴 썼다.

```c
int replication_off_flag = 32;  /* SM_CLASSFLAG_REPLICATION_OFF = 32 */
```

주석에 적힌 상수 이름(`SM_CLASSFLAG_REPLICATION_OFF`)도 실제 헤더의 이름(`SM_CLASSFLAG_DATA_REPLICATION_OFF`,
`#6477`에서 개명됨)과 다르다 — 리팩토링 시 주석이 따라가지 못한 흔적이다.

**문제 시나리오**: 당장은 `class_object.h`의 플래그가 비트 오어(1,2,4,8,16,32) 순서로 늘어나는 구조라
재배치될 가능성은 낮지만, 이런 "값만 복사, 이름은 어긋남" 패턴은 나중에 플래그 하나가 폐기·재배치될
때 `base` 계층의 이 하드코딩된 32를 놓치기 딱 좋은 자리다.

**제안**: `class_object.h`에 플래그 값을 순수 매크로 정의로 분리하거나, `static_assert`로 두 값이
같음을 컴파일 타임에 보증한다. 최소한 주석의 상수 이름은 실제 헤더와 일치시킨다.

---

## 문제 12 — [보통] `rkcheck`가 `db_login()` 반환값을 검사하지 않는다

**재검증**: 유지. 코드 변경 없음.

**위치**: `src/executables/util_cs.c:3295`(`db_login ("DBA", NULL);`)

**로직 설명**: 같은 파일의 `applyinfo()`는 `db_login()` 실패 시 즉시 조기 종료하는 반면, `rkcheck()`는
리턴값을 버리고 바로 `db_restart()`로 진행한다. `db_restart()`가 내부적으로 인증 실패를 다시 검출하긴
하겠지만, 실패 지점이 한 단계 뒤로 밀리면서 에러 메시지가 "로그인 실패"가 아니라 "재기동 실패"로
뭉뚱그려질 수 있다.

**문제 시나리오**: DBA 계정 정책이 바뀌어(예: 패스워드 필수화) `db_login("DBA", NULL)`이 실패하는
환경에서, 에러 메시지만 보고는 인증 문제인지 다른 재기동 문제인지 바로 구분하기 어렵다.

**제안**: `applyinfo()`와 동일한 패턴으로 `db_login()` 반환값을 확인해 조기 종료하고 명확한 메시지를
남긴다.

---

## 문제 13 — [보통] 다중 DB 환경에서 `rkcheck`가 순차 실행되며 첫 실패 DB에서 나머지 DB 전부가 "점검 자체를 받지 못한 채" 방치된다

**재검증**: 유지. `us_hb_process_rkcheck()`의 `for` 루프와 `break` 로직 변경 없음.

**위치**: `src/executables/util_service.c:3205-3238`(`for (i = 0; dbs[i] != NULL; i++)` 루프,
`:3234-3237`의 `status != NO_ERROR` 시 `break`)

**로직 설명**: 한 노드가 여러 DB를 서비스하는 구성(`database.txt`에 다중 DB)에서 `hb start`는
`ha_conf->db_names`를 순서대로 돌며 각 DB에 rkcheck를 실행한다. 하나라도 `status != NO_ERROR`가
나오면 즉시 `break`로 루프를 빠져나온다. 그 결과 **뒤 순서의 DB들은 위반이 있어도 없어도 전혀
점검되지 않은 채** hb start가 종료된다.

**문제 시나리오**: `database.txt`에 `db1, db2, db3`이 나열되어 있고 `db1`에서 RK 위반이 발견되면,
운영자는 `db1`만 고치고 재시도할 것이다. 그런데 `db3`에도 실제로는 위반이 있다면, `db1`이 통과하는
순간까지 그 사실이 드러나지 않는다.

**제안**: 첫 실패에서 멈추더라도, 최소한 어떤 DB들을 아직 점검하지 못했는지 터미널에 명시한다. 여유가
된다면 전체 DB를 다 점검한 뒤 종합 결과를 보고하는 옵션을 고려한다.

---

## 문제 14 — [사소] `rkcheck` 위반목록 파일명이 분 단위 타임스탬프라, 같은 분에 두 번 실행하면 이전 결과가 덮어써진다

**재검증**: 유지. `generate_violation_list_file_name()`의 포맷 문자열 변경 없음(초 단위 없음).

**위치**: `src/executables/util_cs.c:2838-2853`(`generate_violation_list_file_name`, `"%04d%02d%02d_%02d%02d.list"`)

**로직 설명**: 파일명은 년월일_시분까지만 포함하고 초 단위가 없다. `open_violation_list_file()`은
`fopen(..., "w")`으로 여는데, 이는 기존 동일 이름 파일이 있으면 **덮어쓴다**(append가 아님).

**문제 시나리오**: DBA가 위반을 발견하고 스키마를 고친 뒤 "됐는지 확인"하려고 60초 이내에 `rkcheck`를
재실행하면, 직전 실행의 `.list` 파일이 같은 이름으로 덮어써진다.

**제안**: 타임스탬프에 초 단위를 추가하거나, 파일이 이미 존재하면 접미사를 붙인다.

---

## 문제 15 — [중요] (신규) SBR 버그 수정(`#7678`)이 도입한 `is_replication_class()`가, 팀이 방금 `heap_is_replication_class`에서 걷어낸 것과 같은 "조회 실패를 bool로 삼킨다" 패턴을 재도입했다

**위치**: `src/query/execute_statement.c:3201-3218`(`is_replication_class`), `:3304-3336`
(`is_data_repl_log_enabled`, 이 함수가 호출부), `:3405`/`:4110`(`do_statement`/`do_execute_statement`에서
SBR 여부 결정 지점)

**로직 설명**: `#7678`(`3b6ebd1a9`, SBR 로그 복제 버그 수정)이 새로 추가한 `is_replication_class()`는
다음과 같다.

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

`db_find_class()`가 NULL을 반환하는 경우 — 클래스가 실제로 없거나(이 시점엔 이미 컴파일/이름 해석을
통과한 대상이라 흔치 않음), 혹은 다른 사유로 조회가 실패하는 경우 — 이 함수는 `assert(false)`(release
빌드에서는 무시) 후 그냥 `false`("복제 클래스 아님")를 반환한다. 이 값은 `spec_has_replication_class()`
→ `is_data_repl_log_enabled()`를 거쳐 `do_statement()`/`do_execute_statement()`에서
"이 INSERT/UPDATE/DELETE에 대해 SBR(statement-based replication) 로그를 남길지"를 결정하는 데 바로
쓰인다(`:3405`, `:4110`). 즉 이 함수가 "복제 클래스 아님"으로 잘못 답하면, **정확히 `#7678`이 고치려던
바로 그 증상**(REPLICATION=ON 테이블인데 SBR이 생성되지 않아 슬레이브가 조용히 divergence)이 재발한다.

이는 서버 측 `heap_is_replication_class()`가 갖고 있던 것과 완전히 같은 형태의 안티패턴이다 —
"조회 실패의 원인을 구분하지 않고 assert(debug 전용) + false로 뭉갠다." 다만 차이가 있다: `#7697`이
실측으로 증명한 문제는 **서버 측** `heap_get_class_record()`가 `pgbuf_fix`를 통해 인터럽트(`KILL QUERY`)에
직접 노출되는 경로였고, `do_statement`/`is_replication_class()`는 클라이언트 측(`db_vdb.c` → `db_execute()`)
경로에서 호출되며 이 시점에는 대상 클래스가 이미 컴파일 단계에서 workspace에 캐시돼 있을 가능성이 높다.
따라서 `#7697`만큼 재현이 쉽다고 단정할 수는 없다 — **이 부분은 실측하지 못한 추정**이다. 그럼에도
"실패 원인을 구분하지 않고 조용히 false로 답한다"는 설계 자체가, 팀이 같은 기능 영역에서 막 근본
원인으로 지목하고 고친 패턴과 동일하다는 점은 짚어둘 가치가 있다.

**문제 시나리오(추정)**: 세션/트랜잭션 도중 권한 재검증 실패, 혹은 동시에 해당 클래스가 DROP되는
극단적 레이스 등으로 `db_find_class()`가 NULL을 반환하면, REPLICATION=ON 테이블에 대한 USE_SBR 힌트
DML이 SBR 로그 없이 조용히 실행된다 — `#7678`이 고쳤다고 주장하는 바로 그 계열의 결과(슬레이브 데이터
불일치, `checksumdb`로만 뒤늦게 발견)로 이어질 수 있다.

**제안**: `db_find_class()` 실패를 "복제 아님"으로 단정하지 말고, 호출부(`is_data_repl_log_enabled`)가
"판정 불가"와 "복제 아님"을 구분할 수 있는 시그니처로 바꾸거나, 최소한 실패 시 에러를 로그에 남기고
호출자가 이를 인지할 수 있게 한다(예: SBR을 생략하는 대신 안전한 쪽으로 fail — 즉 SBR을 강제 생성).

---

## 조사 종료 선언

**훑은 영역(1차 + 2차 재검증)**: `rkcheck` 유틸리티 전체 흐름(`util_cs.c` 신규 함수 전부), `cubrid hb start`의
rkcheck 연동(`util_service.c`), CREATE/ALTER TABLE의 REPLICATION 옵션·RK 제약 검사 경로(`execute_schema.c`의
`do_alter()`/`do_create_entity()`/`check_ha_repl_constraint()`/`log_ha_repl_fk_ref_all_replicated()`),
RK 판정 함수 계열(`IS_HA_REPLICATION_KEY_CONSTRAINT`, `or_is_replication_candidate_key`,
`heap_get_class_repl_on`/`or_class_is_replication_on`/`sm_is_replication_class`)의 정의와 LSP 참조 추적,
INSERT/DELETE/UPDATE 시 실제 복제 로그 생성 경로(`locator_sr.c`), 그리고 이번 2차 재리뷰의 신규 범위인
동기화 델타 `#7678`(`3b6ebd1a9`, `execute_statement.c`/`checksumdb.c`/`locator_sr.c`)와 `#7697`(`9e094324b`,
`heap_file.c`/`heap_file.h`/`locator_sr.c`) 전량을 라인 단위로 diff·현재 코드 대조했다.

**더 없다고 보는 근거**: `#7678`이 추가한 `spec_has_replication_class`/`pt_spec_repl_class_walk`/
`get_spec_classname`의 널 안전성과 워크플로우, `checksumdb.c`의 `db_set_suppress_repl_on_transaction`
성공/실패 처리(리턴값을 baseline으로 잡고 이후 실행 실패가 그 값을 덮어쓰는 구조)는 직접 추적한 결과
설계 의도대로 동작해 새 문제로 잡지 않았다(resume 실패가 발생해도 최종 `error`에 반영되므로 은폐되지
않음 — 다만 resume이 실패한 채로 남을 경우 이후 statement에 suppress 플래그가 걸려 있을 가능성은
이론적으로 남지만, `db_set_suppress_repl_on_transaction`이 실패하는 경로 자체가 연결 단절 수준의
전제조건이 필요해 실무적 근거가 약하다고 판단해 별도 항목화하지 않았다). `#7697`의 실제 수정(`heap_get_class_repl_on`
+ `goto error` 전파)은 코드·호출부·헤더 시그니처까지 전부 확인했고 의도대로 구현되어 있다. `PT_MERGE`가
`is_stmt_based_repl_type`의 USE_SBR 힌트 분기에 없는 것은 이번 동기화 이전부터 존재하던 기존 갭이라
신규 지적에서 제외했다. 이 이상은 같은 패턴(에러를 bool로 삼키는 함수, 재검증 게이트 누락)의 변주를
찾는 작업이 될 것이라 판단해 여기서 마무리한다.

---

## 재검증 요약

| 구분 | 건수 | 번호 |
|---|---:|---|
| 유지 | 12 | 1, 2, 3, 4, 6, 8, 9, 10, 11, 12, 13, 14 |
| 해소 | 2 | 5, 7 |
| 폐기 | 0 | — |
| 신규 | 1 | 15 |

- **문제 5 해소**: `heap_is_replication_class()`(bool 반환, 조회 실패를 assert+false로 삼김)가 `#7697`
  (`9e094324b`)에서 `heap_get_class_repl_on()`(int 에러코드 반환 + out-parameter)으로 근본 수정됐고,
  호출부 `locator_add_or_remove_index_internal()`이 실패를 `goto error`로 정상 전파하도록 바뀌었다.
- **문제 7 해소**: 같은 `#7697` 수정이 `&&` 체인 순서를 `!replicated`가 `heap_get_class_repl_on()` 호출보다
  먼저 오도록 바꾼 부수 효과로, RK가 이미 확정된 뒤 남은 인덱스에 대한 반복 heap 조회가 더 이상
  발생하지 않는다.

## 심각도별 집계 (2차, 유지+신규)

| 심각도 | 건수 | 번호 |
|---|---:|---|
| 치명 | 4 | 1, 2, 3, 4 |
| 중요 | 5 | 6, 8, 9, 10, 15 |
| 보통 | 3 | 11, 12, 13 |
| 사소 | 1 | 14 |
| **합계** | **13** | |
