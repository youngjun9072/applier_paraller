# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 3년차 관점

> **2차 재리뷰(기준 `734f4959d`)** — 1차 리뷰(`44468ed73`) 이후 fork가 upstream과 동기화되어 기준선이 바뀌었다. 새 HEAD는 `44468ed73`에 `#7678`(`3b6ebd1a9`, SBR/checksumdb) + `#7697`(`9e094324b`, repl-class 인터럽트 근본 수정) 동기화 머지가 얹힌 상태다. 1차 리포트의 문제를 새 코드에서 재검증(유지/해소/폐기)하고, 동기화 델타에서 새 문제를 발굴했다. 재검증 결과는 문서 끝 요약 참조.

## 페르소나 소개

저는 CUBRID 엔진을 3년째 만지는 개발자입니다. 서버 코드에서 "락을 잡는 순서", "에러가 났을 때 자원을 제대로 되돌리는가", "NULL/경계값을 안 챙긴 곳", "모든 진입점이 같은 검사를 타는가"를 실제 콜체인을 따라가며 확인합니다. 이번 재리뷰는 `git diff b646647ec...734f4959d`를 대상으로, 1차 지적을 새 HEAD에서 clangd LSP·소스 정독으로 다시 따라갔습니다.

## 총평

1차에서 가장 시급하다고 꼽았던 **문제 1(`heap_is_replication_class()`가 bool을 반환해 KILL QUERY 인터럽트를 삼키는 #7697 회귀)** 은 동기화로 들어온 **#7697이 근본 수정**했습니다. 함수는 `heap_get_class_repl_on()`(반환 `int`, 판정은 out-param `repl_on`)으로 바뀌었고, INSERT/DELETE 경로 `locator_add_or_remove_index_internal()`는 `error_code != NO_ERROR`면 `goto error`로 인터럽트를 트랜잭션에 전파합니다. 같은 재설계가 1차 **문제 6(인덱스 루프 안 반복 호출)** 도 함께 해소했습니다 — 이제 `or_is_replication_candidate_key(index)`가 먼저 게이트하고 `!replicated` 단락으로, 정상(복제 ON) 테이블에서는 첫 후보 키에서 한 번만 클래스 레코드를 fetch합니다.

그럼에도 이 기능의 **가장 큰 뿌리 문제는 그대로 남아 있습니다(문제 2)**: "복제 키(RK)가 무엇인가"를 판정하는 규칙이 클라이언트("복합 UNIQUE 중 하나만 NOT NULL이어도 RK")와 서버("전부 NOT NULL이어야 RK")에서 서로 다릅니다. 생성·rkcheck는 통과하는데 실제 DML은 조용히 복제되지 않는 데이터 유실 시나리오가 새 HEAD에서도 성립합니다. #7697이 "인터럽트를 삼키던" 침묵은 갚았지만, "판정 규칙 불일치로 복제 로그가 아예 안 생기는" 침묵은 아직 남았습니다.

그 밖에 rkcheck 파일 포인터 NULL 미검사(문제 3), 멀티 절 ALTER 재검사 게이트가 첫 절만 보는 문제(문제 4), MODIFY COLUMN 경로 누락(문제 5) 등 "진입점마다 검사가 고르게 적용되지 않는" 이 기능 특유의 패턴은 동기화 이후에도 코드 위치만 밀렸을 뿐 그대로입니다.

동기화 델타(#7678의 checksumdb SBR 억제, execute_statement의 modify-target 기반 SBR 판정)는 정독했으나 새로 성립하는 결함을 추가로 찾지 못했습니다(근거는 조사 종료 선언 참조).

---

## 문제 2

**[심각도: 치명] RK 판정 규칙이 클라이언트("하나라도 NOT NULL")와 서버("전부 NOT NULL")에서 불일치 — 부분 NOT NULL 복합 UK 테이블의 DML이 조용히 복제되지 않는다**

- 위치: 클라이언트 `src/object/class_object.c:95-98`(`IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로) + `src/object/schema_manager.c:16114-16130`(`sm_has_non_null_attribute`), 서버 `src/base/object_representation_sr.c:4694-4722`(`or_is_replication_candidate_key`)

로직 설명:
- 클라이언트 RK 판정: `IS_HA_REPLICATION_KEY_CONSTRAINT`는 `SM_IS_CONSTRAINT_UNIQUE_FAMILY(type) && sm_has_non_null_attribute(attributes)`를 씁니다. `sm_has_non_null_attribute()`는 이름 그대로 "구성 컬럼 중 **하나라도** NOT NULL이면 1"을 돌려줍니다(`schema_manager.c:16121-16127`, 첫 `SM_ATTFLAG_NON_NULL`을 만나면 즉시 `return 1`).
- 서버 RK 판정: `or_is_replication_candidate_key()`는 UNIQUE 인덱스에 대해 `for (i...) if (attr == NULL || !attr->is_notnull) return false;`로 **모든** 구성 컬럼이 NOT NULL일 때만 true입니다(`object_representation_sr.c:4712-4719`).

두 규칙은 복합 UK에서 갈립니다. CREATE 검사(`check_ha_repl_constraint` → `classobj_has_class_repl_key_constraint`)와 rkcheck(`check_rk_constraint`)는 모두 클라이언트 규칙을 쓰고, 실제 복제 로그 생성(`locator_add_or_remove_index_internal`, `locator_update_index`)과 슬레이브 RK 재계산(`btree_get_rkey_btid` → `or_is_replication_candidate_key`)은 서버 규칙을 씁니다.

문제 시나리오: HA 모드에서
```sql
CREATE TABLE t (a INT NOT NULL, b INT, UNIQUE(a, b)) REPLICATION=ON;
```
- CREATE 시 클라이언트 검사: UNIQUE(a,b)에서 a가 NOT NULL이므로 `sm_has_non_null_attribute`가 1 → RK 있음으로 판정 → `ER_HA_REPLICATION_KEY_REQUIRED` 안 남 → 생성 성공.
- rkcheck도 같은 규칙이라 "위반 없음" → HA 정상 기동.
- 그러나 INSERT/UPDATE/DELETE 시 서버 `or_is_replication_candidate_key`는 b가 nullable이라 이 UNIQUE를 RK 후보로 인정하지 않음 → 어떤 인덱스도 RK로 선택되지 않음 → **복제 로그가 아예 생성되지 않음**. 마스터에는 데이터가 쌓이는데 슬레이브는 영원히 못 받고, rkcheck가 "이상 없음"으로 안심시켜 탐지도 안 됩니다.

제안: 두 판정을 한 함수로 단일화해야 합니다. `IS_HA_REPLICATION_KEY_CONSTRAINT`/`classobj_has_class_repl_key_constraint`가 "구성 컬럼 **전부** NOT NULL"을 요구하도록 강화하거나(스펙 2C-4 권고), "모든 컬럼 NOT NULL" 검사 헬퍼를 새로 만들어 클라이언트/서버가 공유해야 합니다. (스펙 확정 2C-4)

---

## 문제 3

**[심각도: 중요] rkcheck: `open_violation_list_file()`가 돌려준 FILE*를 NULL 검사 없이 `fprintf`에 넘긴다 — 로그 디렉토리 쓰기 실패 시 `cubrid hb start` 중 세그폴트**

- 위치: `src/executables/util_cs.c:3320`(fp 획득), `:3332` 이하(`PRINT_SECTION_TITLE(fp,...)` 등)

로직 설명: `rkcheck()`는 `fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);`(`:3320`)로 `.list` 파일을 엽니다. `open_violation_list_file`는 내부에서 `return fopen (file_path, "w");`(`util_cs.c:2863`)만 하고, `rkcheck()`에는 `fp`에 대한 NULL 검사가 전혀 없습니다. 곧이어 `PRINT_SECTION_TITLE (fp, ...)`(=`fprintf(fp, ...)`, `:3332`), `check_repl_constraint_violations(classes, fp, ...)`가 실행됩니다. 종료부(`:3403`)에서만 `if (fp != NULL) fclose`로 가드할 뿐, 쓰기 진입 전 가드는 없습니다.

문제 시나리오: 로그 디렉토리(`CUBRID/log`)가 없거나 권한이 없거나 디스크가 꽉 차면 `fopen`이 NULL을 돌려주고, 첫 `fprintf(NULL, ...)`에서 즉시 크래시합니다. rkcheck는 `us_hb_process_start()`가 `cubrid hb start` 도중 자동 호출하므로, 로그 쓰기 실패라는 사소한 운영 문제가 HA 기동 프로세스의 크래시로 번집니다.

제안: `fp == NULL`이면 에러 로그를 남기고 `err = ER_FAILED; goto end1;`(종료부 `fclose`는 이미 NULL 가드됨)로 안전하게 종료해야 합니다.

---

## 문제 4

**[심각도: 중요] 멀티 절 ALTER의 복제 재검사 게이트가 첫 절(`alter->info.alter.code`)만 본다 — 뒤쪽 절의 RK 변경이 재검사를 건너뜀**

- 위치: `src/query/execute_schema.c:2051`(`IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code)`), 루프 `:1851-2057`

로직 설명: `do_alter()`는 `for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next)`(`:1851`)로 각 절을 돌며 지역 변수 `alter_code = crt_clause->info.alter.code`(`:1854`)를 씁니다. 그런데 루프 끝의 재검사 게이트는
```c
if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
  need_check_repl_constraint = true;
```
처럼 `crt_clause`(현재 절)나 지역 `alter_code`가 아니라 **`alter`(리스트 헤드 = 항상 첫 절)**의 code를 봅니다. 즉 여러 절이 있어도 게이트는 첫 절 하나만 반복 검사합니다.

문제 시나리오: HA 모드에서
```sql
ALTER TABLE t CHANGE c1 c1 INT NOT NULL, DROP CONSTRAINT uk_c2;
```
- 첫 절 code = `PT_CHANGE_ATTR`(게이트 목록에 없음, 문제 5 참조).
- 둘째 절 code = `PT_DROP_CONSTRAINT`(게이트 목록에 있음).

게이트는 `alter->info.alter.code`(=첫 절 `PT_CHANGE_ATTR`)만 보므로 `need_check_repl_constraint`가 끝까지 false → 마지막 RK 상태를 검증하는 `check_ha_repl_constraint()`가 아예 호출되지 않습니다. 유일한 RK였던 `uk_c2`가 사라져도 통과되어, RK 없는 복제 테이블이 만들어집니다(HA 기동 시 rkcheck가 뒤늦게 잡을 수는 있으나, 생성 단계 방어선은 뚫림).

제안: 게이트를 `IS_REPL_CONSTRAINT_RELATED_ALTER (alter_code)`(현재 절)로 바꿔 모든 절을 OR 누적해야 합니다. (스펙 확정 C-9, #6637에서 검사 위치를 do_alter로 옮긴 취지와 어긋남)

---

## 문제 5

**[심각도: 중요] `IS_REPL_CONSTRAINT_RELATED_ALTER`가 `PT_CHANGE_ATTR`/`PT_MODIFY_ATTR_MTHD`를 빠뜨림 — MODIFY로 RK 컬럼의 NOT NULL을 풀면 재검사 없이 RK 자격 상실**

- 위치: `src/query/execute_schema.c:109-114`

로직 설명: 재검사 대상 매크로는 `PT_ADD_ATTR_MTHD`, `PT_DROP_ATTR_MTHD`, `PT_DROP_CONSTRAINT`, `PT_DROP_PRIMARY_CLAUSE` 넷만 나열합니다. `PT_CHANGE_ATTR`(CHANGE/MODIFY COLUMN)와 `PT_MODIFY_ATTR_MTHD`는 없습니다. RK가 "NOT NULL UNIQUE"인 테이블에서 그 컬럼의 NOT NULL을 MODIFY로 해제하면, `or_is_replication_candidate_key`(문제 2) 기준으로 그 UNIQUE는 더 이상 RK가 아니게 되지만 이 경로는 게이트에 없어 재검사가 안 됩니다.

문제 시나리오: HA 모드에서
```sql
CREATE TABLE t (a INT NOT NULL UNIQUE) REPLICATION=ON;  -- a가 RK
ALTER TABLE t MODIFY a INT NULL;                        -- NOT NULL 해제
```
`MODIFY` 절 code는 `PT_CHANGE_ATTR`/`PT_MODIFY_ATTR_MTHD`라 게이트를 못 타 재검사 없이 성공. 이제 t는 서버 기준으로 RK가 없어 DML이 복제되지 않지만, ALTER는 아무 경고 없이 통과합니다.

제안: 매크로에 `PT_CHANGE_ATTR`, `PT_MODIFY_ATTR_MTHD`를 추가하고, 문제 4의 per-clause 수정과 함께 적용해야 합니다. (스펙 확정 C-9)

---

## 문제 7

**[심각도: 보통] `log_ha_repl_fk_ref_all_replicated()`가 `db_constraint_find_primary_key()` 결과를 NULL 검사 없이 역참조**

- 위치: `src/query/execute_schema.c:9837-9839`(함수 `log_ha_repl_fk_ref_all_replicated`, `:9817-`)

로직 설명: rkcheck의 FK 검사에서 참조 대상이 비복제(OFF)면 위반으로 출력하는데,
```c
ref_class_mop = ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL);
if (!sm_is_replication_class (ref_class_mop))
  {
    DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
    fprintf (fp, "%s(%s) -> %s(%s)\n", ..., pk_c->name);
```
처럼 `pk_c`를 바로 `pk_c->name`으로 씁니다. `db_constraint_find_primary_key`는 PK가 없으면 NULL을 돌려줍니다.

문제 시나리오: 통상 CUBRID FK는 참조 테이블에 PK 존재를 강제(`ER_FK_REF_CLASS_HAS_NOT_PK`)하므로 대개 non-NULL이지만, 참조 대상이 상속/특수 경로로 PK를 직접 보유하지 않거나 카탈로그 조회가 어긋나면 `pk_c`가 NULL이 되어 rkcheck가 세그폴트합니다. rkcheck는 HA 기동 경로에서 돌므로 방어적 NULL 검사가 필수입니다.

제안: `if (pk_c != NULL) fprintf(...pk_c->name...); else fprintf(...참조 키명 미상 표기...);`로 가드해야 합니다.

---

## 문제 8

**[심각도: 보통] `check_ha_repl_fk_ref_all_replicated()`가 `ws_mop()`/`sm_is_replication_class()` 실패를 "비복제"로 오판 → 잘못된 FK 위반 판정**

- 위치: `src/query/execute_schema.c:9789-9800`, `src/object/schema_manager.c`(`sm_is_replication_class`)

로직 설명: `sm_is_replication_class(ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL))`(`:9796`)을 그대로 조건에 씁니다. `sm_is_replication_class`는 `au_fetch_class_force`가 실패하면 `assert(false); return false;`로 "복제 아님"을 돌려줍니다. `ws_mop`이 NULL을 주거나 참조 클래스 fetch가 권한/락 사유로 실패하면, 실제로는 복제 ON인 참조 테이블도 "OFF"로 오판되어 FK 위반으로 기록됩니다.

문제 시나리오: CREATE TABLE에서 방금 만든 FK의 참조 클래스가 아직 워크스페이스에 로드되지 않았거나 fetch가 일시 실패하면, 정상 스키마인데도 `ER_HA_FK_CONSTRAINT_VIOLATION`으로 생성이 거부될 수 있습니다.

제안: fetch 결과와 MOP NULL 여부를 별도 에러 코드로 구분해 전파하고, "판정 불가"를 "위반"으로 뭉개지 말아야 합니다.

---

## 문제 9

**[심각도: 보통] RK 자동 선택이 인덱스 배열 순서에 의존 — 마스터/슬레이브가 독립 재계산하므로 순서가 어긋나면 서로 다른 키로 복제**

- 위치: `src/storage/btree.c:8285-8298`(`btree_get_rkey_btid`), `src/base/object_representation_sr.c:4692`(미구현 TODO 주석), 마스터측 `src/transaction/locator_sr.c:8041`/`:8420`

로직 설명: 슬레이브는 `btree_get_rkey_btid`가 클래스 표현의 인덱스 배열을 `for (i=0, curr_idx=cls_repr->indexes; ...)`로 순회하며 `or_is_replication_candidate_key(curr_idx)`가 true인 **첫 인덱스**를 RK로 삼습니다(`:8294-8298`). 마스터도 DML 루프에서 첫 후보를 씁니다. `or_is_replication_candidate_key`는 PK든 NOT NULL UNIQUE든 모두 true이므로, PK와 UNIQUE가 공존하면 "배열 순서상 먼저 오는 것"이 RK가 됩니다. `object_representation_sr.c:4692` 주석도 "마스터에서 RK 이름을 받아쓰는 방식으로 바꿔야 한다(EPIC CBRD-26096)"는 TODO를 남겨 미구현임을 인정합니다.

문제 시나리오: 마스터와 슬레이브의 인덱스 배열 순서가 동일하다는 보장이 코드로 강제되지 않습니다. 스키마 재생성 순서·언로드/로드·파티션 승격 등으로 인덱스 생성 순서가 노드 간 달라지면, 마스터는 PK로 UPDATE old-key를 기록했는데 슬레이브는 UNIQUE로 행을 찾는 식으로 어긋나 복제 불일치가 발생할 수 있습니다.

제안: TODO대로 마스터가 선택한 RK 제약명을 복제 로그에 실어 슬레이브가 재계산 대신 받아쓰게 하거나, 최소한 "PK 우선, 없으면 이름 순 UNIQUE" 같은 결정적 규칙을 양측이 공유하도록 명문화해야 합니다. (스펙 확정 C-1)

---

## 문제 10

**[심각도: 보통] `do_promote_partition()`이 NOT NULL UNIQUE를 첫 하나만 보존 — 복합/다중 UNIQUE의 나머지 컬럼은 UNIQUE 플래그가 벗겨진다**

- 위치: `src/query/execute_schema.c:7943-7959`, 헬퍼 `has_notnull_unique_constraints` `:7849-7872`

로직 설명: 승격 시 컬럼 플래그 정리 루프가
```c
if (!has_notnull_unique && has_notnull_unique_constraints (smattr))
  has_notnull_unique = true;         /* 첫 NOT NULL UNIQUE 컬럼만 보존 */
else {
  smattr->flags &= ~(SM_ATTFLAG_UNIQUE);
  smattr->flags &= ~(SM_ATTFLAG_REVERSE_UNIQUE);
}
```
로 되어 있습니다(`:7948-7956`). `has_notnull_unique_constraints`는 컬럼 단위로 "이 컬럼이 NOT NULL이고 UNIQUE 제약을 가지는가"를 봅니다. 한 번 `has_notnull_unique`가 true가 되면 이후의 모든 NOT NULL UNIQUE 컬럼은 `else`로 빠져 UNIQUE 플래그가 제거됩니다.

문제 시나리오:
- 복합 UNIQUE(a, b)에서 a, b 둘 다 NOT NULL이면, 컬럼 a에서 플래그가 켜지고 컬럼 b는 `else`로 가 `SM_ATTFLAG_UNIQUE`가 벗겨집니다. 같은 인덱스를 구성하는 두 컬럼의 attflag가 비대칭이 됩니다.
- 서로 다른 두 개의 NOT NULL UNIQUE 제약(uk1(a), uk2(c))이 있으면 uk2 쪽 컬럼의 UNIQUE 플래그만 제거됩니다.

승격 후 클래스 프로퍼티는 `if (!has_notnull_unique)`(`:7978`)일 때만 UNIQUE/REVERSE_UNIQUE 프로퍼티를 드롭하므로, 컬럼 attflag와 클래스 제약 프로퍼티 사이에 불일치가 남을 수 있습니다. 파티션 승격은 드문 경로지만 스키마 손상 가능성이 있습니다.

제안: "RK로 쓸 대표 하나만 남기고 나머지는 제거"가 의도라면, 컬럼 단위 플래그가 아니라 클래스 제약(SM_CLASS_CONSTRAINT) 단위로 "보존할 RK 제약 하나"를 정하고 그 구성 컬럼 전체의 플래그를 일괄 처리해야 합니다. 최소한 복합 UNIQUE의 구성 컬럼들이 같은 취급을 받도록 해야 합니다. (#6552 파티션 상속)

---

## 문제 11

**[심각도: 보통] DDL(SBR)은 테이블 REPLICATION=OFF와 무관하게 항상 복제·재실행된다**

- 위치: `src/query/execute_statement.c:3345-3346`(`is_data_repl_log_enabled`의 `default: return true;`), 게이트 `:3405`, `:4113`

로직 설명: #7678이 `is_data_repl_log_enabled()`를 modify-target spec 기반으로 다듬었지만, INSERT/UPDATE/DELETE만 대상 테이블의 복제 플래그로 판정하고 그 외 문장 유형은 여전히 `default: return true;`(`:3345-3346`)로 무조건 복제 대상입니다. `is_stmt_based_repl_type()`가 앞서 거르는 SBR성 DDL/문장은 전부 이 default를 타 REPLICATION=OFF 테이블에 대한 DDL도 슬레이브에서 재실행됩니다. (#7678 커밋 메시지도 "join으로 참조하는 replication-off 테이블은 슬레이브에서 빈/발산 테이블에 재실행된다"는 미해결 한계를 스스로 명시합니다.)

문제 시나리오: `REPLICATION=OFF`로 지정해 슬레이브에는 존재하지 않거나 다른 상태여야 할 테이블에 대한 SBR성 문장이 슬레이브에서 재실행되면, 슬레이브에 없는 개체를 건드려 적용 실패(fail_count) 또는 예기치 않은 반영이 생길 수 있습니다. 스키마는 항상 복제한다는 설계 의도와, 데이터는 OFF라는 사용자 기대 사이의 경계가 문장 기반 경로에서 흐려지는 지점입니다.

제안: 스키마 DDL은 항상 복제라는 정책이 맞다면 문서로 못박고, 최소한 "OFF 테이블만 대상으로 하는 데이터성 SBR 문장"은 격리하는 분기를 두는 것이 안전합니다. (스펙 확정 2C-6, #6908)

---

## 문제 12

**[심각도: 보통] rkcheck의 `tmp_database_name[CUB_MAXHOSTNAMELEN]`(256)가 `"<255자 DB명>@localhost"`(265자)를 담기엔 부족 — 잘림**

- 위치: `src/executables/util_cs.c:3273`(버퍼 선언), `:3300`(snprintf), TODO `:3299`

로직 설명:
```c
char tmp_database_name[CUB_MAXHOSTNAMELEN];   /* 256 */
...
/* TODO: Handle truncation explicitly here; keep this in sync with applyinfo() ... */
snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
```
DB 이름 최대 길이(255) + `"@localhost"`(10) = 265자로 256 버퍼를 넘겨 `snprintf`가 잘라냅니다. `:3299`에 "Handle truncation explicitly here"라는 TODO가 그대로 붙어 있어 이미 인지된 미해결 사항(#6934에서 MAJOR로 지적되고 TODO로 남은 것)임을 보여줍니다.

문제 시나리오: 긴 이름의 DB에 대해 `cubrid hb rkcheck`/`hb start` 시 잘린 이름 `...@localho`처럼 되어 `check_database_name`/`db_restart`가 엉뚱하게 실패합니다.

제안: 버퍼를 `SM_MAX_IDENTIFIER_LENGTH + strlen("@localhost") + 1` 이상으로 잡거나, `snprintf` 반환값으로 잘림을 감지해 명시적 에러를 내야 합니다. `applyinfo()`의 동일 경로(`:4095`의 TODO)도 같이 정리하는 것이 좋습니다. (#6934)

---

## 문제 13

**[심각도: 사소] `or_class_is_replication_on()`이 플래그 값 32를 하드코딩하고, 주석의 상수명이 실제와 다르다**

- 위치: `src/base/object_representation_sr.c:781-792`

로직 설명:
```c
int replication_off_flag = 32;  /* SM_CLASSFLAG_REPLICATION_OFF = 32 */
...
return !(flags & replication_off_flag);
```
실제 enum은 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`(`class_object.h:312`)로, 주석의 이름(`SM_CLASSFLAG_REPLICATION_OFF`)은 실제 심볼과 다릅니다. 또 값 32를 매직 넘버로 박아 enum과 컴파일 타임 연결이 없습니다.

문제 시나리오: 훗날 누군가 새 클래스 플래그를 추가하며 값 배치를 바꾸면, `class_object.h`의 enum과 이 매직 넘버가 조용히 어긋나 복제 판정이 통째로 뒤집힙니다(빌드 에러도 안 남). src/base가 src/object 헤더를 못 쓰는 계층 문제라면 최소한 `STATIC_ASSERT`나 공유 상수 헤더로 못박아야 합니다.

제안: enum 값을 참조하거나 정적 단언으로 동기화를 강제하고, 주석 이름을 `SM_CLASSFLAG_DATA_REPLICATION_OFF`로 정정.

---

## 문제 14

**[심각도: 사소] rkcheck가 엔진 에러 코드(-1378)를 프로세스 종료 코드로 반환 — 하위 바이트 우연에 의존**

- 위치: `src/executables/util_cs.c:3387`(`err = ER_HA_REPLICATION_CONSTRAINT_VIOLATION;`) → `:3411`(`return err;`), 호출 `src/executables/util_service.c`(`proc_execute` 결과 검사)

로직 설명: `rkcheck()`는 위반 시 `err = ER_HA_REPLICATION_CONSTRAINT_VIOLATION`(-1378)을 반환하고, 이 값이 `cub_admin` 프로세스의 종료 코드가 됩니다. `us_hb_process_rkcheck`는 `proc_execute` 결과가 `NO_ERROR`가 아니면 중단합니다. 프로세스 종료 코드는 하위 8비트만 유효하므로 `-1378 & 0xFF = 158`(nonzero)라 지금은 우연히 동작합니다. (참고: 인자 오류 등 다른 경로는 이미 `EXIT_FAILURE`를 쓰는데 위반 경로만 엔진 에러 코드를 그대로 반환해 표현이 섞여 있습니다.)

문제 시나리오: 향후 반환하는 에러 코드가 256의 배수(예: 가상의 -256, -512)가 되면 종료 코드가 0으로 잘려 "성공"으로 오인되어, 위반이 있는데도 HA가 기동됩니다.

제안: 유틸리티 종료 코드는 `EXIT_SUCCESS`/`EXIT_FAILURE`로 정규화하고, 상세 사유는 에러 로그로 전달해야 합니다.

---

## 문제 15

**[심각도: 사소] `generate_violation_list_file_name()`이 `localtime_r` 실패 시 미초기화 버퍼를 그대로 파일명으로 반환**

- 위치: `src/executables/util_cs.c:2839-2852`, 호출부 `open_violation_list_file` `:2856-2864`

로직 설명:
```c
static char *
generate_violation_list_file_name (char *out, ...) {
  ...
  log_tm_p = localtime_r (&log_time, &log_tm);
  if (log_tm_p != NULL) { snprintf (out, ...); }
  return out;   /* localtime_r 실패 시 out은 미초기화 */
}
```
호출부 `open_violation_list_file`는 `char violation_list_file[PATH_MAX];`(초기화 안 함, `:2858`)를 넘깁니다. `localtime_r`가 NULL을 돌려주면 `out`은 스택 쓰레기 값 그대로 `envvar_logdir_file`(`:2859`)에 넘어가 임의 경로가 됩니다.

문제 시나리오: 극단적 시각 값 등으로 `localtime_r`가 실패하면 예측 불가한 파일명으로 fopen을 시도해, 엉뚱한 파일 생성 또는 실패(문제 3과 연쇄해 크래시)로 이어집니다.

제안: 실패 시 `out[0] = '\0'` 또는 결정적 기본 파일명을 세팅하고, 호출부에서 빈 문자열을 검사해야 합니다.

---

## 문제 16

**[심각도: 사소] `db_find_class(entity_name)` 결과를 NULL 검사 없이 `sm_is_replication_class`에 넘겨, 조회 실패 시 재검사가 조용히 생략**

- 위치: `src/query/execute_schema.c:2061-2066`

로직 설명: `do_alter()`의 재검사 블록은
```c
vclass = db_find_class (entity_name);
if (!sm_is_replication_class (vclass)) { return NO_ERROR; }
error_code = check_ha_repl_constraint (vclass);
```
`db_find_class`가 NULL을 줄 수 있는데 검사가 없습니다. `sm_is_replication_class(NULL)`은 `assert(false); return false;`라, 릴리스 빌드에서는 조용히 false → `return NO_ERROR`로 RK 재검사가 통째로 생략됩니다.

문제 시나리오: RENAME과 결합된 멀티 절 ALTER 등으로 `entity_name`이 최종 클래스명과 어긋나 조회에 실패하면(문제 4의 연쇄), 위반 검사가 침묵으로 건너뛰어집니다.

제안: `if (vclass == NULL) { error_code = er_errid(); goto error_exit; }`를 추가.

---

## 문제 17

**[심각도: 사소] 네이밍/복사 흔적: `btree_get_rkey_btid` 헤더 파라미터명 미변경, `do_alter_change_replication`이 COMMENT 세이브포인트명 재사용**

- 위치: `src/storage/btree.h:729`(`... BTID * pkey_btid`), `src/query/execute_schema.c:11747`(`tran_system_savepoint (UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT)`, 함수 `do_alter_change_replication` `:11730-`)

로직 설명: `.c`에서는 `btree_get_pkey_btid` → `btree_get_rkey_btid`로 개명하고 인자도 `rkey_btid`로 바꿨지만(`btree.c:8264`), 헤더 선언의 파라미터명은 `pkey_btid`로 남았습니다(동작엔 무해하나 혼동 유발). 또 `do_alter_change_replication`은 COMMENT 변경용 세이브포인트 상수 `UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`를 그대로 씁니다 — `do_alter_change_tbl_comment`(`:11505`)에서 복사한 흔적으로, 단일 문장 내에서는 충돌하지 않지만 의미가 맞지 않습니다.

문제 시나리오: 기능 결함은 아니나, 향후 세이브포인트를 이름으로 부분 롤백하는 코드가 생기면 의미 불일치가 버그의 온상이 됩니다.

제안: 헤더 파라미터명을 `rkey_btid`로, 세이브포인트는 `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 전용 상수로 정리.

---

## 문제 18

**[심각도: 사소] `is_replication_class()`(execute_statement.c)가 조회 실패를 `assert(false)+false`로 삼켜, 일부 타깃을 비복제로 오판할 수 있다**

- 위치: `src/query/execute_statement.c:3200-3218`

로직 설명: `is_data_repl_log_enabled`의 하위 헬퍼 `is_replication_class(classname)`은
```c
if (classname == NULL) { return false; }
class_obj = db_find_class (classname);
if (class_obj == NULL) { assert (false); return false; }
return sm_is_replication_class (class_obj);
```
classname이 non-NULL이어도 `db_find_class`가 실패할 수 있는 경우(예: 동의어/특수 이름 해석 실패)를 "복제 아님"으로 처리합니다. (#7678이 `get_spec_classname()`/`spec_has_replication_class()`로 NULL 안전성은 강화했지만, "찾았는데 조회 실패"를 false로 뭉개는 이 지점은 그대로입니다.)

문제 시나리오: 정상적으로는 spec의 이름이 잘 해석되지만, 이름 해석이 어긋나는 경계 케이스에서 복제 대상 테이블이 "비복제"로 판정되어 복제 로그가 생성되지 않을 수 있습니다(문제 2와 같은 침묵성 유실 계열). 다만 `spec_has_replication_class`가 `flat_entity_list`와 derived 서브트리도 함께 보므로 상당수는 보완됩니다.

제안: 조회 실패를 false로 뭉개지 말고, 호출 문맥에서 이름이 이미 해석 완료라는 전제를 `flat_entity_list->info.name.db_object` 경로로 통일해 사용하는 것이 안전합니다.

---

## 조사 종료 선언

여기서 조사를 마칩니다. 아래는 재검증·신규 발굴에서 훑은 영역과 더 이상 새 지적을 내지 않는 근거입니다.

**동기화 델타(#7678·#7697) 정독 결과 — 새 결함 없음**
- `#7697` `heap_get_class_repl_on()`(`heap_file.c:11074-`) + `locator_add_or_remove_index_internal()`(`locator_sr.c:8041-8059`): 반환을 `int`+out-param으로 바꾸고 `error_code != NO_ERROR`이면 `goto error`로 전파하는 재설계를 라인바이라인 확인했습니다. `repl_on`은 진입 시 false로 초기화되고, `or_is_replication_candidate_key(index)` 게이트를 앞세워 후보 키가 아니면 fetch를 아예 안 하며, 복제 성공 시 `replicated=true`로 `!replicated` 단락됩니다. 인터럽트 전파·자원 해제·조건 순서에서 새 결함을 찾지 못했습니다(오히려 1차 문제 1·6을 해소).
- `#7678` checksumdb `chksum_calculate_checksum()`(`checksumdb.c:1685-1763`): `db_set_suppress_repl_on_transaction(true)` 실패 시 db_execute 전에 return하고, 실행 후 `(false)`로 재개하는 대칭 구조를 확인했습니다. "재개 결과를 에러 베이스라인으로 두고 실제 실행 실패가 덮어쓴다"는 처리는 커밋 메시지에 명시된 의도이며(리뷰에서 이미 다뤄진 결정), `res>=0`/`res<0` 분기에서 `query_result` 수명·에러 전파에 결함을 찾지 못했습니다.
- `#7678` `is_data_repl_log_enabled()`/`spec_has_replication_class()`/`pt_spec_repl_class_walk()`(`execute_statement.c:3200-3348`): modify-target spec(`PT_SPEC_FLAG_UPDATE/DELETE`) 기반 판정과 derived vclass 서브트리 walk를 확인했습니다. `parser`는 `do_statement`/`do_execute_statement` 경로에서 항상 유효하고 NULL 역참조 경로가 없어 결함 없음(단, 비-DML `default: return true` 정책 경계는 1차 문제 11로 유지).

**재검증으로 훑은 기존 영역(콜체인 추적 완료)**
- DDL 경로: `do_alter`/`do_alter_change_replication`, `check_ha_repl_constraint`/FK 헬퍼, `do_promote_partition`. 자원 해제는 `error_exit`/`dbt_abort_class`로 수렴함을 재확인 — 검사 게이트 논리 결함(문제 4·5·16·10)에 집중.
- 서버 복제 로그: `locator_add_or_remove_index_internal`, `locator_update_index`, `btree_get_rkey_btid`, `heap_get_class_repl_on`, `or_is_replication_candidate_key`, `or_class_is_replication_on`. UPDATE old-key 스냅샷 로직은 실질 변경 없음(정합성 문제 없음).
- 유틸: `rkcheck`(util_cs.c), checksumdb SBR 억제. rkcheck 파일/버퍼/종료코드 계열(문제 3·12·14·15)을 재확인.

**제외 처리**
- RK/REPLICATION과 무관하게 diff에 함께 들어온 변경(`page_buffer.c`, `log_page_buffer.c` cdc_find_lsa 카운터 등)은 락/자원 관점에서 결함을 찾지 못해 억지 지적을 피하기 위해 제외합니다.

가장 시급한 것은 문제 2(치명)입니다. #7697이 "인터럽트를 삼키는 bool" 침묵은 갚았으나, "클라이언트/서버 RK 규칙 불일치로 복제 로그가 조용히 누락"되는 침묵은 그대로 남아 RK 판정 함수 단일화가 여전히 필요합니다.

---

## 심각도별 집계 (2차 재리뷰 기준)

| 심각도 | 개수 | 문제 번호 |
|---|---|---|
| 치명 | 1 | 2 |
| 중요 | 3 | 3, 4, 5 |
| 보통 | 6 | 7, 8, 9, 10, 11, 12 |
| 사소 | 6 | 13, 14, 15, 16, 17, 18 |
| **계** | **16** | |

## 재검증 요약

| 구분 | 수 | 상세 |
|---|---|---|
| 유지 | 16 | 문제 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18 (위치는 새 HEAD 기준으로 갱신) |
| 해소 | 2 | 문제 1(#7697이 `heap_get_class_repl_on` int+out-param+`goto error` 전파로 근본 수정), 문제 6(#7697 재설계가 후보키 게이트+`!replicated` 단락으로 루프 내 반복 fetch 제거) |
| 폐기 | 0 | — |
| 신규 | 0 | 동기화 델타·전체 diff 정독 결과 새로 성립하는 결함 없음(근거: 조사 종료 선언) |

1차 18건 중 2건(문제 1·6)이 동기화(#7697)로 해소되어 16건이 유지됩니다. 신규 발굴은 없습니다.
