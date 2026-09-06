# RK/REPLICATION 기능 코드 리뷰 — 통합 최종보고서

## 대상

- **기능**: CUBRID HA "테이블별 REPLICATION 옵션 + RK(Replication Key, 복제 키) 제약사항" — 테이블 단위로 복제를 켜고 끄는 REPLICATION 옵션과, 복제 대상 테이블이 반드시 갖춰야 하는 RK 제약을 DDL·런타임·유틸리티 전 계층에 걸쳐 구현한다.
- **브랜치/커밋**: `feature/CBRD-26246-develop` @ `734f4959d` (upstream 동기화 반영). `develop`(merge-base `b646647ec`) 대비 diff는 **35개 파일 +1,444 라인**.
- **리뷰 방법**: 20개 페르소나(PM · DB엔지니어 · SQL 사용자 · 응용개발자 · DB엔진개발자 각 1/3/5/10년차)가 서로 다른 관점에서 코드를 읽어 결함을 발굴했다. 각 결함은 clangd LSP로 정의 점프·참조 추적을 따라가며 실제 로직으로 검증했고, 관련 PR 히스토리 21건을 교차 참조해 결함이 심긴 경위를 확인했다. 모든 신규 지적은 `develop`(`b646647ec`)에 같은 코드가 있는지 대조해 "이 브랜치가 만든 것"만 남겼으며, 이슈마다 진입 최소 상태 / 스키마·데이터 조건 / master·applier·slave 실행 순서 / 최소 재현 입력 / 대조 조건으로 구성된 end-to-end 재현 명세를 도출했다.
- **수록 기준**: 신뢰도 **높음** 이슈만 §2 본문에 전문(코드 발췌·재현 명세 포함) 수록한다. 신뢰도 **중간·낮음** 이슈는 §3 부록 표로, 각 이슈의 원문 개별 리포트는 `reports/` 디렉토리에 둔다.
- **코드 표기 규약**: 이슈마다 관련 코드를 `파일:라인`·함수명으로 리스트업하고, 항목별로 분리된 코드 블록으로 발췌한다. 코드 블록 안의 `...` 은 중간 생략을 뜻한다.

---

## 0. 이 문서를 읽는 법 (용어 먼저)

- **RK (Replication Key, 복제 키)**: 마스터에서 바뀐 한 행(row)을 슬레이브에서 똑같이 찾아 고치기 위한 "행을 유일하게 가리키는 열쇠". 이 기능에서는 **PK(기본 키) 또는 NOT NULL UNIQUE(모든 컬럼이 NOT NULL인 유일 인덱스)**를 RK로 인정한다. RK가 없으면 슬레이브가 어느 행을 고쳐야 할지 못 찾으므로, HA 모드에서 복제 대상 테이블은 반드시 RK를 가져야 한다.
- **REPLICATION 옵션**: 테이블 단위로 복제를 켜고(ON) 끄는(OFF) 스위치. 내부적으로는 "복제 제외 테이블만 표시"하는 음성 플래그 `SM_CLASSFLAG_DATA_REPLICATION_OFF`로 저장된다(옛 백업 호환을 위해 이렇게 설계됨 — PR #6454).
- **rkcheck**: `cubrid hb start`(HA 하트비트 기동) 직전에 자동 실행되어, RK/FK 제약 위반이 있으면 HA를 못 켜게 막는 사전 점검 유틸리티(PR #6658).
- **SBR (Statement-Based Replication)**: 행 단위가 아니라 SQL 문장 자체를 슬레이브에 보내 재실행시키는 복제 방식. `USE_SBR` 힌트로 켠다.
- **"에러를 삼킨다(swallow)"**: 조회·인터럽트 실패를 호출자에게 알리지 않고 그냥 `false`(=복제 아님)로 뭉개는 것. release 빌드에서는 조용히 틀린 판정을, debug 빌드에서는 `assert(false)`로 서버 크래시를 일으킨다.

---

## 1. 요약

### 머지 가능 여부: **불가 (NEEDS_FIX)**

이 기능은 머지할 수 없다. 근거는 두 갈래다.

1. **크래시 3종이 rkcheck 경로에 남아 있다.** K-2(위반목록 파일 오픈 실패 시 `fprintf(NULL)` 세그폴트), K-4(참조 부모에 PK가 없을 때 `pk_c->name` NULL 역참조 세그폴트), K-62(`localtime_r` 실패 시 미초기화 버퍼로 `fopen`). rkcheck는 `cubrid hb start`가 자동 실행하므로, 로그 디렉터리 문제나 특정 스키마만으로 HA 기동 전체가 좌초된다.
2. **크래시 없이 마스터/슬레이브가 조용히 갈라지는 결함이 남아 있다** — 크래시보다 위험하다. K-5(DDL 검증과 런타임 복제가 서로 다른 함수로 RK를 판정해 기준이 어긋남), K-1/K-6(멀티절 ALTER의 RK 재검사 게이트가 첫 절만 보거나 화이트리스트가 불완전해 재검증이 통째로 스킵됨), K-7/K-8/K-15(조회 실패를 "비복제"로 삼키는 안티패턴이 스키마·클라이언트 계층에 잔존), K2-1(REPLICATION=OFF 테이블을 소스로 읽는 SBR 문장이 슬레이브를 갈라지게 함, 저자가 주석에 known limitation으로 명시).

상위 develop 동기화로 가장 위험했던 부채(인덱스 계층의 크래시성 삼킴 근본 수정, 반복 카탈로그 조회 조건식 정정, checksumdb 억제 해제 처리 정리)는 이미 갚아졌다. 그러나 **같은 처방이 형제 함수·형제 진입점까지 퍼지지 못한 구조적 문제**가 그대로이고, 새 유틸리티(rkcheck)의 마감 부실이 통째로 남아 있으며, 동기화로 새로 들어온 SBR 경로가 오히려 새 결함을 만들었다.

### 수치

- **총 73건.** 본문(신뢰도 높음) **48건** + 부록(신뢰도 중간·낮음) **25건**.
- 본문 48건 심각도: **치명 5 · 중요 11 · 보통 23 · 사소 9.**
- 부록 25건 심각도: **치명 1(K-7) · 중요 10 · 보통 10 · 사소 4.**
- 이와 별개로 `develop`에서 유래해 이 기능의 책임이 아닌 항목 1건(K-42)은 §3-③에 분리 기재한다.

### 수정 우선순위 로드맵

**1순위 — 크래시 · 조용한 데이터 갈라짐 (머지 차단 요인).**
- 크래시: K-2(NULL FILE*), K-4(NULL PK 역참조), K-62(미초기화 버퍼) — rkcheck가 `hb start`를 좌초시킨다.
- 조용한 divergence: K-5(DDL↔런타임 RK 불일치), K-1/K-6(멀티절 ALTER 재검사 스킵), K2-1(SBR 소스 테이블 미검사), 그리고 K-7/K-8/K-15/K-29/K-45(남은 삼킴 패턴을 스키마·클라이언트 계층까지 int 반환+out-param으로 일괄 정리).

**2순위 — 하위호환 · 운영 안정성.**
- K-11(예약어 하위호환 파손), K-21(LIKE+REPLICATION 무시), K-27(구버전 loaddb 파싱 실패), K-28/K-30(hb start 순서·타임아웃), K-31(모순 에러 안내), K-40(종료코드 절단).

**3순위 — 설계 정합성 (재발 방지).**
- 판정 로직 단일화: K-5/K-25/K-49를 하나의 공통 RK/복제 판정 함수로 수렴. 진입점별 OFF 처리 통일(K-32/K-52/K-53/K-54). K2-2(OFF 클래스 루프 조기 이탈)도 여기서 함께.

**4순위 — 정리성 (보통/사소).**
- dead code·주석·네이밍·usage·링키지: K-33/K-34/K-35/K-59/K-60/K-64/K2-3(static 부여). 1~3순위 수정 중 함께 처리.

재심사 조건: 1순위 전건 수정 및 2노드 HA 실측(K-5·K-52·K-58·K2-1·K2-2 재현) 완료.

---

## 2. 이슈 상세 (신뢰도 높음 — 본문 전문 수록)

### 치명 (5건)

#### K-5. RK 인정 기준이 DDL 검증과 런타임 복제에서 불일치 → 조용한 마스터/슬레이브 갈라짐

- **로직**: 같은 "이 인덱스를 RK로 인정할까?"라는 판정을 두 계층이 **서로 다른 함수**로 한다.
  - **DDL 쪽**(CREATE/ALTER·rkcheck) 매크로 `IS_HA_REPLICATION_KEY_CONSTRAINT`는 `PK || (UNIQUE_FAMILY && sm_has_non_null_attribute(attrs))`다. 그런데 `SM_IS_CONSTRAINT_UNIQUE_FAMILY`는 UNIQUE·PRIMARY_KEY뿐 아니라 **REVERSE UNIQUE**까지 참으로 치고, `sm_has_non_null_attribute`는 배열을 훑다 **컬럼 하나라도 NOT NULL이면 즉시 1**을 반환한다(전 컬럼 NOT NULL을 요구하지 않음).
  - **런타임 쪽**(실제 DML 복제 로그 기록) `or_is_replication_candidate_key`는 `BTREE_PRIMARY_KEY`거나, `BTREE_UNIQUE`이면서 **모든** 키 컬럼이 `is_notnull`일 때만 참을 준다. REVERSE UNIQUE(`BTREE_REVERSE_UNIQUE`)는 `type != BTREE_UNIQUE`라 거부, 부분 NOT NULL도 루프에서 하나라도 아니면 거부.

- **관련 코드**
  1. `src/object/class_object.c:95` — `IS_HA_REPLICATION_KEY_CONSTRAINT()` — DDL 계층의 느슨한 RK 판정 매크로.
  2. `src/object/class_object.h:111` — `SM_IS_CONSTRAINT_UNIQUE_FAMILY()` — REVERSE UNIQUE까지 UNIQUE 계열로 인정하는 하위 매크로.
  3. `src/object/schema_manager.c:16114` — `sm_has_non_null_attribute()` — 컬럼 배열에서 첫 NOT NULL을 만나면 1을 반환.
  4. `src/base/object_representation_sr.c:4694` — `or_is_replication_candidate_key()` — 런타임 계층의 엄격한 RK 판정.

**① IS_HA_REPLICATION_KEY_CONSTRAINT() — src/object/class_object.c:95~98**
```c
/* src/object/class_object.c:95 — DDL 판정 (느슨) */
#define IS_HA_REPLICATION_KEY_CONSTRAINT(c) \
  ((c)->type == SM_CONSTRAINT_PRIMARY_KEY || \
    (SM_IS_CONSTRAINT_UNIQUE_FAMILY((c)->type) && \
     sm_has_non_null_attribute((c)->attributes)))   /* ← REVERSE UNIQUE 포함 + '하나라도' NOT NULL */
```

**② SM_IS_CONSTRAINT_UNIQUE_FAMILY() — src/object/class_object.h:111~115**
```c
/* src/object/class_object.h:111 — REVERSE UNIQUE까지 UNIQUE_FAMILY로 인정 */
#define SM_IS_CONSTRAINT_UNIQUE_FAMILY(c) \
        (((c) == SM_CONSTRAINT_UNIQUE          || \
          (c) == SM_CONSTRAINT_PRIMARY_KEY     || \
          (c) == SM_CONSTRAINT_REVERSE_UNIQUE)    \
          ? true : false )                          /* ← REVERSE UNIQUE도 참 */
```

**③ sm_has_non_null_attribute() — src/object/schema_manager.c:16114~16130**
```c
/* src/object/schema_manager.c:16114 — 하나라도 NOT NULL이면 1 */
int
sm_has_non_null_attribute (SM_ATTRIBUTE ** attrs)
{
  for (i = 0; attrs[i] != NULL; i++)
    if (attrs[i]->flags & SM_ATTFLAG_NON_NULL)
      return 1;                                     /* ← 첫 NOT NULL에서 조기 반환 */
  return 0;
}
```

**④ or_is_replication_candidate_key() — src/base/object_representation_sr.c:4694~4722**
```c
/* src/base/object_representation_sr.c:4694 — 런타임 판정 (엄격) */
bool
or_is_replication_candidate_key (const OR_INDEX * index)
{
  if (index->type == BTREE_PRIMARY_KEY)
    return true;
  if (index->type != BTREE_UNIQUE || index->n_atts <= 0 || index->atts == NULL)
    return false;                                   /* ← REVERSE UNIQUE 거부 */
  for (int i = 0; i < index->n_atts; i++)
    if (index->atts[i] == NULL || !index->atts[i]->is_notnull)
      return false;                                 /* ← 전 컬럼 NOT NULL 요구 */
  return true;
}
```

- **시나리오**: "일부 컬럼만 NOT NULL인 복합 UNIQUE"나 "REVERSE UNIQUE"를 RK로 삼은 테이블은 **CREATE와 rkcheck는 통과(생성·HA 기동 성공)하지만, 런타임에서 RK로 인정받지 못해 DML 복제 로그가 한 건도 안 생긴다.** → 마스터/슬레이브가 아무 에러 없이 조용히 갈라진다. 크래시보다 위험하다.
- **제안**: DDL 판정과 런타임 판정을 **하나의 공통 함수**로 통일하고, "전 컬럼 NOT NULL, BTREE_UNIQUE만" 기준으로 일치시킨다.
- **PR 맥락**: "PK뿐 아니라 NOT NULL UNIQUE도 RK"라는 개념이 #6467에서 생겼는데, DDL 검증과 실제 DML 복제 경로가 서로 다른 함수로 발전하며 정의가 벌어졌다.
- **재현 명세 (end-to-end)**
  - **진입 최소 상태**: HA 모드 2노드(마스터+슬레이브). DDL 게이트는 `check_ha_repl_constraint`가 `HA_DISABLED()`면 그냥 통과하므로 마스터가 `ha_mode=on`이어야 하고, 갈라짐은 슬레이브의 applylogdb가 복제 로그를 못 받는 형태로 나타나므로 실제 복제가 도는 2노드가 필요하다. 런타임 판정은 서버(`SERVER_MODE`)의 `locator_sr.c`가 인덱스 루프에서 `or_is_replication_candidate_key`로 수행한다(locator_sr.c:8042).
  - **스키마·데이터 조건**: RK가 오직 (a) REVERSE UNIQUE거나 (b) 일부 컬럼만 NOT NULL인 복합 UNIQUE인 복제 대상 테이블. PK도, 전 컬럼 NOT NULL UNIQUE도 없어야 한다(있으면 그게 런타임 RK로 인정돼 갈라짐이 안 남).
  - **실행 순서**: 마스터에서 CREATE(DDL 매크로가 느슨해 통과) → `cubrid hb start`의 rkcheck도 같은 느슨 기준이라 통과 → HA 정상 기동 → 마스터에서 그 테이블에 INSERT/UPDATE → 서버 인덱스 루프에서 `or_is_replication_candidate_key`가 이 인덱스를 RK 후보로 거부 → 복제 로그(repl_records) 미생성 → 슬레이브 applylogdb에 해당 DML이 도착하지 않음 → 슬레이브 테이블이 마스터와 조용히 갈라짐.
  - **최소 재현 입력**:
    ```sql
    -- 케이스 (b): 복합 UNIQUE인데 일부 컬럼만 NOT NULL
    CREATE TABLE t (
      a INT NOT NULL,
      b INT,                       -- NOT NULL 아님
      CONSTRAINT uk UNIQUE (a, b)  -- 'a'만 NOT NULL → DDL은 통과, 런타임은 거부
    );
    INSERT INTO t VALUES (1, 10);  -- 마스터엔 들어가나 복제 로그 미생성 → 슬레이브 누락
    -- 케이스 (a): CREATE REVERSE UNIQUE INDEX rk ON t (a); 를 유일 RK로 삼아도 동일
    ```
  - **대조 조건**: 같은 테이블에 **전 컬럼 NOT NULL UNIQUE**(`UNIQUE (a, b)` + `b INT NOT NULL`)나 PK를 두면 런타임 판정도 참이 되어 복제 로그가 생기고 갈라짐이 사라진다. 즉 "부분 NOT NULL → 전 컬럼 NOT NULL"로 하나만 바꾸면 미발생.
- **신뢰도**: 높음 — 두 판정 함수의 조건식 차이(REVERSE 포함/제외, any/all NOT NULL)를 코드에서 직접 대조 확인. 갈라짐의 실제 빈도만 2노드 실측 권장.

#### K-1. 다중 절 ALTER TABLE의 RK 재검사 게이트가 항상 "첫 번째 절"만 검사

- **로직**: `do_alter()`는 한 문장에 여러 절(clause)을 콤마로 나열한 `ALTER TABLE`을 실행하는 함수다. 각 절은 `PT_NODE` 링크드 리스트로 이어져 있고, 함수는 그 리스트를 처음부터 끝까지 도는 for 루프로 절을 하나씩 처리한다(현재 절 = `crt_clause`). 루프를 다 돌고 나면 "이 ALTER가 복제 키(RK)를 건드렸으니 다시 검증해야 하나?"를 정하는 게이트 변수 `need_check_repl_constraint`를 보고, 참이면 `check_ha_repl_constraint()`로 RK가 여전히 있는지 재확인한다. 문제는 이 게이트를 세울 때 **현재 절 `crt_clause`가 아니라 함수 진입 시 받은 첫 절 `alter` 노드의 `code`**를 검사한다는 점이다. 그래서 RK를 없애는 절이 두 번째 이후에 오면 게이트가 켜지지 않는다.

- **관련 코드**
  1. `src/query/execute_schema.c:2051` — `do_alter()` — 절 루프 안에서 재검사 게이트를 세울 때 현재 절이 아닌 첫 절 `alter->info.alter.code`를 참조.

**① do_alter() — src/query/execute_schema.c:1829~2065 (발췌)**
```c
/* src/query/execute_schema.c:1829 — do_alter() */
int
do_alter (PARSER_CONTEXT * parser, PT_NODE * alter)
{
  ...
  for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next)  /* :1851 절 루프 */
    {
      PT_NODE *const save_next = crt_clause->next;
      const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;   /* :1854 현재 절 코드(사용 안 됨) */
      ...
      /* :2051 — 게이트를 crt_clause가 아니라 첫 절 alter로 검사 */
      if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))  /* ← crt_clause여야 함 */
        {
          need_check_repl_constraint = true;
        }
      do_semantic_checks = true;
    }

  if (need_check_repl_constraint)                                      /* :2059 */
    {
      vclass = db_find_class (entity_name);
      if (!sm_is_replication_class (vclass))
        {
          return NO_ERROR;
        }
      error_code = check_ha_repl_constraint (vclass);                  /* RK 여전히 있는지 재검증 */
      ...
    }
}
```

- **시나리오**: `ALTER TABLE t COMMENT='x', DROP PRIMARY KEY`처럼 RK와 무관한 절이 앞에 오고 RK를 없애는 절(DROP PRIMARY KEY / DROP CONSTRAINT)이 뒤에 오면, 게이트가 첫 절(COMMENT)만 보고 "재검사 불필요"로 판단해 **`check_ha_repl_constraint()` 재검증이 통째로 스킵**된다. → RK 없는 복제 테이블이 조용히 만들어진다.
- **제안**: 게이트 판정을 루프 변수 `crt_clause->info.alter.code`(=이미 뽑아 둔 `alter_code`) 기준으로 바꾸고, 절 중 하나라도 RK 관련이면 재검사가 걸리도록 OR 누적한다.
- **PR 맥락**: 검사 위치를 `do_alter()`로 옮긴 것이 바로 #6637(멀티 ALTER로 PK 교체 허용)의 핵심 변경이다. 그 리팩토링이 "첫 절 고정" 실수를 함께 심었다 — #6637이 풀려던 문제의 정반대 회귀.
- **재현 명세 (end-to-end)**
  - **진입 최소 상태**: HA 모드에서만 발현. `do_alter()`는 클라이언트 측 DDL 실행 경로이고, 재검증 본체 `check_ha_repl_constraint()`가 서두에서 `if (HA_DISABLED ()) return NO_ERROR;`(execute_schema.c:9863)로 빠지기 때문이다. 즉 `ha_mode=on`으로 기동한 마스터 노드에서 실행해야 한다. 게이트가 켜지지 않는 스킵 자체는 모드와 무관하지만, "RK 없는 복제 테이블이 잔존"하는 결함으로 이어지려면 HA 모드가 필요하다.
  - **스키마·데이터 조건**: PK를 가진 복제 대상 테이블 하나. 그 PK가 유일한 RK여야 한다(NOT NULL UNIQUE 등 대체 RK가 없어야 결함이 실질 위험이 됨).
  - **실행 순서**: (단일 노드에서 관찰 가능한 DDL 결함 — HA 왕복 불필요) 마스터에서 멀티절 ALTER 실행 → `do_alter` 루프가 마지막 절(DROP PRIMARY KEY)까지 처리 → 게이트가 첫 절 기준이라 `need_check_repl_constraint`가 false로 남음 → 재검증 없이 ALTER 커밋 → RK 없는 복제 테이블 성립. 이후 마스터에서 그 테이블에 DML이 일어나면 슬레이브가 행을 식별하지 못한다.
  - **최소 재현 입력**:
    ```sql
    -- ha_mode=on 마스터에서
    CREATE TABLE t (a INT PRIMARY KEY, b INT);   -- 복제 대상, RK=PK
    ALTER TABLE t COMMENT='x', DROP PRIMARY KEY;  -- RK 무관 절이 먼저, RK 삭제 절이 뒤
    -- 기대: ER_HA_REPLICATION_KEY_REQUIRED로 거부
    -- 실제: 통과 → RK 없는 복제 테이블 잔존
    ```
  - **대조 조건**: 같은 두 절의 **순서만 뒤집으면**(`ALTER TABLE t DROP PRIMARY KEY, COMMENT='x'`) 첫 절이 `PT_DROP_PRIMARY_CLAUSE`라 게이트가 켜지고 재검증이 돌아 정상 거부된다. 또는 절을 하나만 쓰면(`ALTER TABLE t DROP PRIMARY KEY`) 첫 절=현재 절이라 정상 동작한다.
- **신뢰도**: 높음 — 게이트 조건식이 `alter->info.alter.code`(첫 절)를 참조함을 코드에서 직접 확인, 스킵 분기까지 확정.

#### K-6. IS_REPL_CONSTRAINT_RELATED_ALTER 매크로에 CHANGE/MODIFY·RENAME·DROP INDEX·REPLICATION 경로 누락

- **로직**: 이 매크로는 "이 ALTER 절이 RK를 건드릴 수 있으니 끝나고 재검사해야 한다"고 표시할 절 코드의 **허용 목록(화이트리스트)**이다(K-1의 게이트가 이 매크로를 쓴다). 그런데 목록에 `PT_ADD_ATTR_MTHD / PT_DROP_ATTR_MTHD / PT_DROP_CONSTRAINT / PT_DROP_PRIMARY_CLAUSE` 네 개만 들어 있다. 정작 `do_alter`의 switch가 실제로 처리하는 절 중 RK를 없앨 수 있는 `PT_DROP_INDEX_CLAUSE`(UNIQUE 인덱스 삭제), `PT_CHANGE_ATTR/PT_MODIFY_ATTR`(NOT NULL 해제), `PT_RENAME_ENTITY`(테이블 스왑), `PT_CHANGE_REPLICATION`(복제 옵션 전환)이 빠져 있다.

- **관련 코드**
  1. `src/query/execute_schema.c:109` — `IS_REPL_CONSTRAINT_RELATED_ALTER()` — 재검사 게이트가 참조하는 절 코드 화이트리스트 매크로.

**① IS_REPL_CONSTRAINT_RELATED_ALTER() — src/query/execute_schema.c:109~114**
```c
/* src/query/execute_schema.c:109 */
#define IS_REPL_CONSTRAINT_RELATED_ALTER(code)              \
  ( ((code) == PT_ADD_ATTR_MTHD)         ||                 \
    ((code) == PT_DROP_ATTR_MTHD)        ||                 \
    ((code) == PT_DROP_CONSTRAINT)       ||                 \
    ((code) == PT_DROP_PRIMARY_CLAUSE)                     \
  )   /* ← PT_DROP_INDEX_CLAUSE / PT_CHANGE_ATTR / PT_MODIFY_ATTR / PT_RENAME_ENTITY / PT_CHANGE_REPLICATION 누락 */
```

- **시나리오**: `DROP INDEX`로 UNIQUE 인덱스(=RK)를 제거하거나, `MODIFY`로 NOT NULL을 풀거나, `RENAME`으로 그림자 테이블을 스왑해 RK가 사라져도 **게이트가 켜지지 않아 재검사가 발동하지 않는다** → RK 없는 복제 테이블 잔존. (특히 DROP INDEX 누락이 치명)
- **제안**: 매크로에 누락된 절 코드를 모두 추가. 근본적으로는 "화이트리스트"가 아니라 "RK를 건드릴 수 있는 모든 절 뒤 무조건 재검사"로 뒤집는 것이 안전하다.
- **PR 맥락**: RK 삭제 제약 #6618, 검사 위치 이동 #6637. K-1과 한 세트로 do_alter 게이트 설계가 미완성.
- **재현 명세 (end-to-end)**
  - **진입 최소 상태**: HA 모드(마스터 `ha_mode=on`). K-1과 같은 이유로 재검증 본체가 HA에서만 동작한다. 이 매크로가 게이트(execute_schema.c:2051)의 유일한 판정식이므로, 목록에 없는 절은 단독으로 써도 `need_check_repl_constraint`가 false로 남는다.
  - **스키마·데이터 조건**: RK가 UNIQUE 인덱스(또는 NOT NULL 컬럼)로만 성립하는 복제 대상 테이블. 그 하나뿐인 RK를 해당 절로 제거할 수 있어야 한다.
  - **실행 순서**: (단일 노드에서 DDL 통과 관찰 가능) 마스터에서 RK를 없애는 ALTER 실행 → 매크로에 없는 절이라 게이트 미점화 → 재검증 스킵 → RK 없는 복제 테이블 성립.
  - **최소 재현 입력**:
    ```sql
    -- ha_mode=on 마스터
    CREATE TABLE t (a INT NOT NULL, CONSTRAINT uk UNIQUE (a));  -- RK = NOT NULL UNIQUE 인덱스
    ALTER TABLE t DROP INDEX uk;    -- PT_DROP_INDEX_CLAUSE — 매크로 목록에 없음 → 재검사 스킵
    -- 또는: ALTER TABLE t MODIFY a INT;   (NOT NULL 해제 → RK 소멸, PT_CHANGE_ATTR)
    -- 기대: ER_HA_REPLICATION_KEY_REQUIRED  / 실제: 통과
    ```
  - **대조 조건**: 같은 RK를 **매크로에 포함된 절로 제거**하면(예: PK를 `ALTER TABLE t DROP PRIMARY KEY`로) 게이트가 켜져 정상 거부된다. 즉 결함은 "제거에 쓴 절 종류"에만 좌우된다.
- **신뢰도**: 높음 — 매크로 정의와 do_alter switch가 처리하는 절 코드 집합을 대조해 누락을 확정. 게이트가 이 매크로만 참조함도 확인.

#### K-2. rkcheck가 위반목록 파일 오픈 실패(NULL FILE*)를 검사 없이 fprintf 호출 → 크래시

- **로직**: rkcheck는 검사 결과를 텍스트 파일(`.list`)에 적는다. 그 파일을 여는 `open_violation_list_file()`은 `fopen`의 결과를 **그대로 반환**하는데, `fopen`은 실패 시 NULL을 돌려준다. 호출부(rkcheck의 3320행)는 이 반환값 `fp`를 NULL 검사 없이 받아, 곧바로 3332의 `PRINT_SECTION_TITLE(fp, ...)`(내부적으로 `fprintf(fp, ...)`)에 넘긴다. `fp`가 NULL이면 `fprintf(NULL, ...)`가 되어 역참조 크래시가 난다.

- **관련 코드**
  1. `src/executables/util_cs.c:2855` — `open_violation_list_file()` — `.list` 파일을 열어 `fopen` 결과(실패 시 NULL)를 그대로 반환.
  2. `src/executables/util_cs.c:3320` — `rkcheck()` — 반환된 `fp`를 NULL 검사 없이 `PRINT_SECTION_TITLE(fp, ...)`에 전달.

**① open_violation_list_file() — src/executables/util_cs.c:2855~2864**
```c
/* src/executables/util_cs.c:2855 */
static FILE *
open_violation_list_file (const char *database_name, const char *util_name, char *file_path, size_t file_path_size)
{
  char violation_list_file[PATH_MAX];
  envvar_logdir_file (file_path, file_path_size,
                      generate_violation_list_file_name (violation_list_file, (char *) database_name, util_name));
  file_path[file_path_size - 1] = '\0';
  return fopen (file_path, "w");            /* :2863 실패 시 NULL을 그대로 반환 */
}
```

**② rkcheck() — src/executables/util_cs.c:3320~3332 (발췌)**
```c
/* src/executables/util_cs.c:3320 — rkcheck(), NULL 검사 없음 */
  fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);

  classes = db_get_all_classes ();
  ...
  if ((repl_check_flags & REPL_CHECK_RK) != 0)
    {
      PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);   /* :3332 fprintf(NULL,...) → 세그폴트 ← 여기 */
      ...
    }
```

- **시나리오**: 로그 디렉터리 권한/부재 등으로 `.list` 파일을 못 열면 그 자체로 **세그폴트**. rkcheck는 `cubrid hb start`가 자동 실행하므로, 로그 디렉터리 문제만으로 HA 기동 전체가 크래시로 좌초된다.
- **제안**: `fopen` 직후 NULL 검사, 실패 시 `PRINT_AND_LOG_ERR_MSG` 후 에러 코드 반환. (K-62의 미초기화 버퍼 파일명과도 연결됨)
- **PR 맥락**: rkcheck 신설 #6658, 파일명 규칙 #6934. 새 유틸리티의 방어 코드 부실.
- **재현 명세 (end-to-end)**
  - **진입 최소 상태**: 단일 노드 재현 가능(유틸 크래시). `cubrid rkcheck <db>`(또는 `cubrid hb start`가 부르는 동일 경로)를 실행하는 rkcheck 유틸 프로세스 하나면 충분하다. HA 왕복 불필요. 크래시 지점(3332)에 도달하려면 `open_violation_list_file`이 NULL을 반환하고, 그 직후 `db_get_all_classes()`가 NULL이 아니어야(정상 접속) `if ((repl_check_flags & REPL_CHECK_RK)…)`(3330) 분기로 들어간다. `repl_check_flags`는 `-r`/`-f` 미지정 시 기본 RK+FK라 RK 블록에 반드시 진입한다.
  - **스키마·데이터 조건**: 스키마 무관. 유일한 조건은 `.list` 파일을 못 여는 파일시스템 상태(로그 디렉터리 부재·권한 없음·경로 문제).
  - **실행 순서**: rkcheck 시작 → `db_restart` 성공 → `open_violation_list_file`이 `fopen` 실패로 NULL 반환(로그 디렉터리 문제) → `db_get_all_classes()`는 정상 → RK 검사 블록 진입 → `PRINT_SECTION_TITLE(NULL,...)` → 세그폴트.
  - **최소 재현 입력**: SQL 아님(정적/환경 트리거). 예: 로그 디렉터리를 읽기 전용/부재로 만든 뒤 `cubrid rkcheck demodb` 실행. 또는 `CUBRID`/logdir 권한을 제거해 `fopen(..., "w")`이 실패하게 한다.
  - **대조 조건**: 로그 디렉터리가 쓰기 가능해 `fopen`이 유효 FILE*를 돌려주면 크래시 없이 정상 진행한다. 즉 "파일 오픈 성공"이 음성 대조군.
- **신뢰도**: 높음 — `fopen` 반환값 무검사 → `fprintf(NULL)` 경로를 코드에서 직접 확인. 트리거는 파일시스템 상태라 결정적.

#### K-4. log_ha_repl_fk_ref_all_replicated가 참조 테이블 PK 부재 시 NULL 역참조 크래시

- **로직**: 이 함수는 rkcheck가 FK 위반을 출력할 때, 각 FK가 가리키는 부모(참조) 테이블이 비복제라면 위반으로 세고 그 내용을 파일에 찍는다. 출력 형식에 "부모 테이블의 PK 이름"을 넣으려고 `db_constraint_find_primary_key()`로 부모의 PK 제약을 찾아 `pk_c->name`을 바로 읽는다. 그러나 이 기능에서 RK는 "PK **또는** NOT NULL UNIQUE"이므로, 부모가 PK 없이 NOT NULL UNIQUE만으로 복제되는 정상 테이블이면 `db_constraint_find_primary_key()`가 **NULL**을 돌려줄 수 있다. NULL 검사 없이 `pk_c->name`을 읽어 역참조 크래시가 난다.

- **관련 코드**
  1. `src/query/execute_schema.c:9817` — `log_ha_repl_fk_ref_all_replicated()` — 비복제 부모를 참조하는 FK를 위반으로 출력하며 부모 PK 이름(`pk_c->name`)을 NULL 검사 없이 역참조.

**① log_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9817~9845**
```c
/* src/query/execute_schema.c:9817 */
int
log_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj, FILE * fp)
{
  ...
  for (tmp_c = db_get_constraints (class_obj); tmp_c; tmp_c = db_constraint_next (tmp_c))
    {
      if (tmp_c->type != SM_CONSTRAINT_FOREIGN_KEY)
        continue;

      ref_class_mop = ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL);
      if (!sm_is_replication_class (ref_class_mop))
        {
          DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));  /* PK 없으면 NULL */
          fprintf (fp, "%s(%s) -> %s(%s)\n", sm_get_ch_name (class_obj), tmp_c->name,
                   sm_get_ch_name (ref_class_mop), pk_c->name);       /* :9839 pk_c->name NULL 역참조 ← 여기 */
          ret++;
        }
    }
  return ret;
}
```

- **시나리오**: FK가 "PK 없는 UNIQUE-only 부모 테이블"을 참조하는 스키마에서 `rkcheck -f`(FK 검사)를 실행하면, 그 부모가 비복제로 판정되는 순간 위반 출력을 만들다가 `pk_c->name`에서 **세그폴트**.
- **제안**: `pk_c` NULL 검사 추가, PK가 없으면 RK로 쓰인 NOT NULL UNIQUE 제약을 대신 조회하거나 이름 필드를 빈 문자열로 대체.
- **PR 맥락**: FK 검증 #6505/#6618, rkcheck 출력 #6658. K-25(FK 검증 중복 구현)와 뿌리가 같다.
- **재현 명세 (end-to-end)**
  - **진입 최소 상태**: 단일 노드 재현 가능(유틸 크래시). `cubrid rkcheck -f <db>`(또는 hb start 자동 경로)를 도는 rkcheck 프로세스. 크래시 분기 진입 조건은 `if (!sm_is_replication_class (ref_class_mop))` — 즉 **참조 부모가 비복제로 판정**되어야 한다. 그 안에서 `db_constraint_find_primary_key(...)`가 NULL(부모에 PK 없음)이어야 역참조가 터진다.
  - **스키마·데이터 조건**: 자식 테이블에 FK가 있고, 그 FK가 가리키는 부모 테이블이 **PK 없이 NOT NULL UNIQUE만** 가진다. 그리고 그 부모가 비복제(REPLICATION=OFF)여야 `!sm_is_replication_class` 분기로 들어간다. 행 데이터는 불필요(스키마만으로 트리거).
  - **실행 순서**: rkcheck -f 시작 → 접속 → 클래스 순회 → 자식 클래스의 FK 발견 → 부모 mop이 비복제 → `db_constraint_find_primary_key(부모)` = NULL → `pk_c->name` 역참조 → 세그폴트.
  - **최소 재현 입력**:
    ```sql
    -- 부모: PK 없이 NOT NULL UNIQUE만, 비복제
    CREATE TABLE parent (uk INT NOT NULL UNIQUE) REPLICATION=OFF;
    -- 자식: parent.uk를 FK로 참조
    CREATE TABLE child (a INT, FOREIGN KEY (a) REFERENCES parent (uk));
    -- 그 후: cubrid rkcheck -f demodb  → 부모 비복제 판정 시 pk_c->name에서 세그폴트
    ```
  - **대조 조건**: 부모에 **PK를 주면**(`CREATE TABLE parent (id INT PRIMARY KEY, ...)`) `db_constraint_find_primary_key`가 유효 포인터를 돌려 크래시가 사라진다. 또는 부모를 복제 대상으로 두면(`REPLICATION` 미지정/ON) `!sm_is_replication_class` 분기 자체에 들어가지 않아 미발생.
- **신뢰도**: 높음 — 반환값 NULL 가능성(PK 없는 RK)과 무검사 역참조를 코드에서 확정. 부모 비복제 진입 가드까지 명시적.

### 중요 (11건)

#### K-21. CREATE TABLE ... LIKE ... + REPLICATION 명시가 조용히 무시됨

**관련 코드**
1. `src/query/execute_schema.c:10258~10272` — `do_create_entity()` — 테이블 생성 후 복제 스위치(`is_replication_on`)를 결정하는데, `create_like` 분기에서 사용자 명시 옵션을 참조하지 않는다.

**① do_create_entity() — src/query/execute_schema.c:10258~10272**
```c
/* src/query/execute_schema.c:10258 — do_create_entity() */
if (create_like)
  {
    is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF); /* ← 여기: 원본(source) 플래그만 본다, 사용자 명시 tbl_opt_replication 무시 */
  }
else
  {
    is_replication_on = IS_CREATE_STMT_SET_REPL_OPTION (tbl_opt_replication); /* 사용자 명시는 이 분기에서만 반영 */
  }

if (is_replication_on)
  {
    error = check_ha_repl_constraint (class_obj);
    ...
  }
else
  {
    error = sm_set_class_flag (class_obj, SM_CLASSFLAG_DATA_REPLICATION_OFF, TRUE);
    ...
  }
```

- **로직**: `do_create_entity()`는 테이블을 만든 뒤 복제 스위치를 정한다. `is_replication_on`(복제 켤지 말지)을 두 갈래로 계산하는데, `create_like`(다른 테이블을 본떠 만드는 `... LIKE ...`)일 때는 사용자가 문장에 직접 적은 REPLICATION 옵션을 아예 쳐다보지 않고 원본(source) 테이블의 플래그만으로 값을 정한다. 즉 `if (create_like)` 분기에서는 원본의 `SM_CLASSFLAG_DATA_REPLICATION_OFF`(복제 제외 표시 비트)를 반전한 값만 쓰고, 사용자가 준 `tbl_opt_replication`은 `else`(=LIKE 아님)에서만 반영된다. #6943 본문(Remarks)에서 "LIKE + REPLICATION 동시 사용 시 에러"로 확정했다고 기록됐으나, 그 에러 처리가 코드에 구현되지 않았다.
- **시나리오**: `CREATE TABLE t2 LIKE t1 REPLICATION=OFF`에서 명시한 `REPLICATION=OFF`가 말없이 버려지고 원본 t1의 플래그가 적용된다 — 사용자 의도와 다른 복제 설정이 조용히 만들어진다.
- **제안**: LIKE 분기에서 사용자 명시 옵션이 있으면 #6943 규칙대로 에러 처리(또는 명시 값 우선).
- **재현 명세**
  - **진입 최소 상태**: 단일 노드 재현 가능(DDL 클라이언트 경로). HA 왕복 불필요. 문법상 `LIKE`와 테이블 옵션을 함께 파싱할 수 있어야 하고(파서가 `tbl_opt_replication` 노드를 만들어 `create_like`와 공존), 코드 진입점은 `do_create_entity()`의 `create_like==true` 분기. `check_ha_repl_constraint`는 `HA_DISABLED()`면 즉시 NO_ERROR라 HA 여부와 무관하게 "옵션이 버려지는" 오동작 자체는 재현된다.
  - **스키마·데이터 조건**: 원본 테이블 `t1`이 존재하고 그 복제 플래그가 사용자가 새로 지정하려는 값과 **반대**여야 관찰된다(예: t1은 REPLICATION=ON, t2는 OFF로 지정). 행 데이터는 불필요.
  - **실행 순서**: 단일 노드. (1) `t1` 생성(REPLICATION 기본 ON) → (2) `CREATE TABLE t2 LIKE t1 REPLICATION=OFF` 실행 → (3) `SHOW CREATE TABLE t2` 또는 카탈로그로 t2의 REPLICATION 값 확인.
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t1 (a INT PRIMARY KEY);              -- 기본 REPLICATION=ON
    CREATE TABLE t2 LIKE t1 REPLICATION=OFF;          -- OFF 지정이 버려짐
    -- 기대: t2 = OFF / 실제: t2 = ON(원본 상속)
    ```
  - **대조 조건**: `LIKE`를 빼고 `CREATE TABLE t2 (a INT PRIMARY KEY) REPLICATION=OFF`로 쓰면 `else` 분기를 타 사용자 명시값이 그대로 반영된다(문제 미발생). 또는 원본 t1도 OFF면 상속값과 지정값이 우연히 일치해 증상이 가려진다.
- **신뢰도**: 높음 — `if (create_like)` 분기가 `tbl_opt_replication`을 참조하지 않음을 코드에서 직접 확인.

---

#### K-30. hb start가 rkcheck보다 cub_server를 먼저 기동해 "반쪽 HA 마스터" 발생

**관련 코드**
1. `src/executables/util_service.c:3963~3973` — `us_hb_process_start()` — HA 기동 절차를 순서대로 실행하며, 서버 기동을 RK 위반 검사보다 먼저 호출한다.

**① us_hb_process_start() — src/executables/util_service.c:3963~3973**
```c
/* src/executables/util_service.c:3963 — us_hb_process_start() */
status = us_hb_server_start (ha_conf, db_name);     /* ← ① 서버 먼저 기동(연결 수락 시작) */
if (status != NO_ERROR) { goto ret; }

status = us_hb_process_rkcheck (ha_conf, db_name);  /* ← ② RK 검사는 그 다음 */
if (status != NO_ERROR) { goto ret; }

status = us_hb_copylogdb_start (pids, ha_conf, db_name, NULL, NULL);
...
```

- **로직**: `us_hb_process_start`는 HA 기동 절차를 순서대로 실행한다. 그런데 서버 기동 `us_hb_server_start`를 먼저(3963행) 호출하고, RK/FK 위반을 막는 `us_hb_process_rkcheck`를 그 뒤(3969행)에 호출한다. 서버가 먼저 떠서 클라이언트 연결을 받는 상태가 된 다음에야 rkcheck가 도는 것이라, "위반이면 기동을 막는다"는 rkcheck의 취지가 무력화된다.
- **시나리오**: RK 위반이 있어도 서버가 이미 클라이언트 연결을 받는 상태가 된 뒤에야 검사가 돈다 → rkcheck의 "위반 시 기동 차단" 취지가 무력화.
- **제안**: rkcheck를 서버 기동 이전으로 이동.
- **PR 맥락**: rkcheck-hb 연결 #6658.
- **재현 명세**:
  - **진입 최소 상태**: 단일 노드에서 순서 관찰 가능(유틸리티 경로). HA 모드 DB. `cubrid hb start` 진입 → `us_hb_process_start`. rkcheck가 실패(위반)를 반환하는 상황이 관찰 핵심.
  - **스키마·데이터 조건**: RK 위반 스키마(예: RK 없는 복제 테이블, 또는 FK가 비복제 부모 참조 — K-4/K-57 계열). 이래야 rkcheck가 위반으로 실패한다.
  - **실행 순서**: (1) RK 위반 스키마 준비 → (2) `cubrid hb start` → (3) 3963행에서 cub_server가 먼저 기동해 연결 수락 → (4) 3969행 rkcheck가 위반 감지·실패 → hb start는 이후 goto ret로 중단되지만 **서버는 이미 떠 있는 "반쪽 마스터"** 상태.
  - **최소 재현 입력**:
    ```sql
    -- RK 없는 복제 테이블(위반) 상태를 만든 뒤 hb start
    CREATE TABLE t (a INT) REPLICATION=ON;  -- RK 부재(위반) — 단, CREATE 게이트를 우회한 경로여야 잔존
    ```
    운영 관점 재현: 위반 스키마 존재 → `cubrid hb start` → rkcheck 실패 전에 서버가 이미 떠 있음.
  - **대조 조건**: rkcheck 호출을 `us_hb_server_start` **이전**으로 옮기면(제안), 위반 시 서버가 아예 뜨지 않아 반쪽 마스터가 발생하지 않는다. 위반이 없는 정상 스키마면 순서 문제와 무관하게 정상 기동.
- **신뢰도**: 높음 — 서버 기동(3963)이 rkcheck(3969)보다 먼저임을 코드에서 직접 확인.

---

#### K-27. unloaddb/SHOW CREATE가 버전 가드 없이 REPLICATION 절을 항상 출력 → 구버전 loaddb 파싱 실패

**관련 코드**
1. `src/executables/unload_schema.c:1794~1801` — `emit_schema()`/`extract_classes_to_file()` 경로 — 스키마를 텍스트 CREATE 문으로 덤프하며 REPLICATION 절을 버전 가드 없이 무조건 출력한다.

**① 스키마 emit 경로 — src/executables/unload_schema.c:1794~1801**
```c
/* src/executables/unload_schema.c:1794 — emit_schema()/extract_classes_to_file() 경로: 무조건 emit */
if (sm_is_replication_class (cl->op))
  {
    output_ctx (", REPLICATION=ON");
  }
else
  {
    output_ctx (", REPLICATION=OFF");   /* ← 여기: 버전/옵션 가드 없이 항상 출력 */
  }
```

- **로직**: unloaddb는 스키마를 텍스트 `CREATE` 문으로 덤프한다. 그 과정에서 REUSE_OID·COLLATE 등 테이블 옵션을 한 줄씩 이어 붙이는데, REPLICATION 절도 버전 조건·플래그 가드 없이 모든 일반 클래스에 대해 `sm_is_replication_class()` 결과에 따라 `REPLICATION=ON` 또는 `REPLICATION=OFF`를 무조건 찍는다. 즉 REPLICATION 문법을 모르는 옛 버전으로 덤프를 되돌려 적재하면 첫 CREATE부터 파싱 에러가 난다.
- **시나리오**: REPLICATION 문법을 모르는 구버전 CUBRID로 loaddb 재적재(다운그레이드·이기종 이관) 시 첫 CREATE부터 문법 에러로 로드 실패.
- **제안**: 출력 대상 버전이 REPLICATION 문법을 아는 경우에만 emit(또는 옵션 플래그).
- **PR 맥락**: unload/load 옵션 보존 #6570. (K-45/K-68과 같은 출력 경로)
- **재현 명세**:
  - **진입 최소 상태**: 단일 노드 재현 가능(유틸리티 경로). HA 무관. `unloaddb`가 스키마를 덤프하는 `--schema-only` 등 경로. 이 브랜치(REPLICATION 지원)로 덤프하고, REPLICATION 문법이 없는 **구버전** CUBRID로 loaddb만 하면 된다.
  - **스키마·데이터 조건**: 아무 일반 테이블 하나면 충분(뷰 아님). REPLICATION 값은 ON이든 OFF든 절이 출력되므로 무관.
  - **실행 순서**: (1) 현재 브랜치에서 `cubrid unloaddb -s db` → schema 파일에 `..., REPLICATION=ON` 포함 → (2) 구버전 CUBRID에서 `cubrid loaddb -s schema_file` → 첫 CREATE에서 문법 에러.
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (a INT PRIMARY KEY);   -- 덤프 시 "CREATE CLASS t (...) ..., REPLICATION=ON ..." 생성
    ```
    → 이 덤프 텍스트를 REPLICATION 미지원 버전 loaddb에 투입.
  - **대조 조건**: 덤프 대상/적재 대상이 모두 REPLICATION 문법을 아는 동일·상위 버전이면 파싱 성공(문제 미발생). 즉 다운그레이드/이기종 이관만의 결함.
- **신뢰도**: 높음 — emit이 버전 가드 없이 무조건 출력됨을 코드로 확정. (구버전 파서가 이 토큰을 거부한다는 것은 하위호환 정의상 자명.)

---

#### K-25. FK 참조 복제여부 검증 로직이 두 함수에 중복 구현

**관련 코드**
1. `src/query/execute_schema.c:9782~9803` — `check_ha_repl_fk_ref_all_replicated()` — DDL 검증용. FK 부모 클래스가 복제 대상인지 검사해 위반 시 즉시 `false` 반환.
2. `src/query/execute_schema.c:9817~9845` — `log_ha_repl_fk_ref_all_replicated()` — rkcheck 출력용. 같은 순회를 재구현해 위반 개수를 세고 파일로 상세를 출력.

**① check_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9782~9803**
```c
/* src/query/execute_schema.c:9789 — check_ha_repl_fk_ref_all_replicated() (bool, DDL 검증용) */
for (tmp_c = db_get_constraints (class_obj); tmp_c; tmp_c = db_constraint_next (tmp_c))
  {
    if (tmp_c->type != SM_CONSTRAINT_FOREIGN_KEY) continue;
    if (!sm_is_replication_class (ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL)))
      return false;                         /* ← 판정 A */
  }
return true;
```

**② log_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9817~9845**
```c
/* src/query/execute_schema.c:9826 — log_ha_repl_fk_ref_all_replicated() (int, rkcheck 출력용): 같은 순회 재구현 */
for (tmp_c = db_get_constraints (class_obj); tmp_c; tmp_c = db_constraint_next (tmp_c))
  {
    if (tmp_c->type != SM_CONSTRAINT_FOREIGN_KEY) continue;
    ref_class_mop = ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL);
    if (!sm_is_replication_class (ref_class_mop))
      {
        DB_CONSTRAINT *pk_c = db_constraint_find_primary_key (db_get_constraints (ref_class_mop));
        fprintf (fp, "%s(%s) -> %s(%s)\n", ..., pk_c->name);  /* ← 판정 B (+K-4 NULL 역참조) */
        ret++;
      }
  }
return ret;
```

- **로직**: 두 함수가 완전히 같은 뼈대를 각자 다시 짰다. 둘 다 `db_get_constraints()`로 제약을 돌며 FK만 골라, 그 FK가 가리키는 부모 클래스가 복제 대상인지 `sm_is_replication_class()`로 검사한다. 차이는 반환 형태뿐: DDL 검증용은 위반이 하나라도 있으면 즉시 `false`, rkcheck 출력용은 위반을 세어 개수를 반환하고 파일로 상세를 찍는다. 로직이 갈라져 있어 규칙(예: RK 인정 기준)을 한쪽만 고치면 DDL 검증과 rkcheck 사전점검이 서로 다른 판정을 낸다.
- **시나리오**: 향후 규칙을 한쪽만 고치면 DDL 검증과 rkcheck 사전점검 결과가 어긋난다(K-4의 뿌리이기도).
- **제안**: 판정 로직을 단일 헬퍼로 추출해 두 곳이 공유.
- **PR 맥락**: FK 검증 #6505→#6618에서 한 번 통합했던 함수가 다시 갈라졌다.
- **재현 명세**:
  - **진입 최소 상태**: 정적(구조) 결함 — 컴파일·실행으로 즉시 크래시하지 않음. 두 함수가 병존한다는 사실 자체가 결함이라 **트리거 불필요**. HA 모드에서 CREATE(DDL 검증)와 `rkcheck`(출력) 두 경로가 각각 호출한다.
  - **스키마·데이터 조건**: FK를 가진 복제 테이블. 두 경로의 판정이 갈라지는 것을 실증하려면 "한쪽 함수만 규칙이 다르게 진화한" 상태가 필요한데 현재는 로직이 동일하므로, 현시점 재현은 "잠재적 발산 위험"의 정적 확인에 그친다.
  - **실행 순서**: (1) FK 있는 테이블 CREATE → `check_ha_repl_fk_ref_all_replicated` 경유. (2) `cubrid rkcheck -f` → `log_ha_repl_fk_ref_all_replicated` 경유. 두 경로가 서로 다른 코드로 같은 질문에 답한다.
  - **최소 재현 입력**: 정적 결함이라 단일 SQL로 오작동을 트리거하지 못한다(현재 두 로직이 우연히 일치). 트리거 불가 사유 = 중복 자체가 유지보수 위험이며 실제 오동작은 미래 편측 수정 시 발현.
  - **대조 조건**: 판정을 공통 헬퍼 하나로 통합하면(제안) 규칙 변경이 양 경로에 동시 반영되어 발산이 원천 차단된다.
- **신뢰도**: 높음 — 두 함수의 순회·판정 코드가 동일 구조로 중복됨을 직접 대조 확인. (실 divergence는 미래 편측 수정 조건부이므로 심각도는 중요.)

---

#### K-20. ALTER TABLE의 중복/혼합 REPLICATION 절에 세만틱 체크 부재로 조용히 덮어씀

**관련 코드**
1. `src/parser/csql_grammar.y:5862~5871` — ALTER의 REPLICATION 절 문법 액션 — alter_node에 code를 세팅하나, code가 이미 `PT_CHANGE_REPLICATION`이면 두 번째 절을 버린다.
2. `src/parser/semantic_check.c:8503~8516` — CREATE 경로 세만틱 체크 — REPLICATION 중복 지정 시 에러를 낸다(ALTER엔 대칭 검사 부재).

**① ALTER REPLICATION 절 액션 — src/parser/csql_grammar.y:5862~5871**
```yacc
/* src/parser/csql_grammar.y:5862 — ALTER의 REPLICATION 절 */
| class_replication_spec
    {{
        PT_NODE *alter_node = parser_get_alter_node();
        if (alter_node != NULL && alter_node->info.alter.code != PT_CHANGE_REPLICATION)  /* ← 여기: 두 번째 절은 이 가드가 false → 버려짐 */
          {
            alter_node->info.alter.code = PT_CHANGE_REPLICATION;
            alter_node->info.alter.alter_clause.replication.tbl_replication = $1;
          }
    }}
```

**② CREATE 경로 중복 검사 — src/parser/semantic_check.c:8503~8516**
```c
/* src/parser/semantic_check.c:8506 — CREATE 경로: 대칭 중복 검사 존재 */
case PT_TABLE_OPTION_REPLICATION:
  if (found_tbl_replication)
    {
      PT_ERRORmf (parser, node, ..., MSGCAT_SEMANTIC_DUPLICATE_TABLE_OPTION, ...);  /* CREATE는 에러 */
      return;
    }
  else { found_tbl_replication = true; }
  break;
/* ← ALTER에는 이런 중복 검사가 없음 */
```

- **로직**: CREATE TABLE의 옵션 목록은 `semantic_check.c`가 순회하며 `found_tbl_replication` 플래그로 REPLICATION이 두 번 나오면 `MSGCAT_SEMANTIC_DUPLICATE_TABLE_OPTION` 에러를 낸다(8506-8518). 반면 ALTER의 REPLICATION 절은 문법(csql_grammar.y:5862-5871)에서 alter_node 하나에 code를 세팅하는 방식인데, 가드가 `alter_node->info.alter.code != PT_CHANGE_REPLICATION`이다. 첫 절이 code를 `PT_CHANGE_REPLICATION`으로 만들면, 두 번째 절은 이 가드가 false라 아무것도 하지 않고 그냥 버려진다(tbl_replication에 재대입 안 됨). 그래서 `REPLICATION=ON, REPLICATION=OFF`를 주면 두 번째 값이 조용히 무시되고 첫 값(ON)만 남으며, 사용자에게 어떤 경고·에러도 없다.
- **시나리오**: `REPLICATION=ON, REPLICATION=OFF`가 경고 없이 한쪽 값으로 조용히 처리된다.
- **제안**: ALTER에도 중복 옵션 세만틱 체크 추가.
- **PR 맥락**: CREATE 중복 검사 #6394. CREATE/ALTER 비대칭.
- **재현 명세**
  - **진입 최소 상태**: 싱글/비HA 모드(REPLICATION ALTER는 K-9/K-31처럼 `HA_DISABLED()`에서만 최종 실행되나, 파싱·세만틱 단계의 조용한 덮어씀은 모드와 무관하게 성립). 클라이언트 파서.
  - **스키마·데이터 조건**: 임의 테이블 1개. 한 ALTER 문에 REPLICATION 절을 콤마로 2개 이상.
  - **실행 순서**: **단일 노드 재현 가능**(파서/세만틱 단계, HA 불필요). 파서가 첫 절에서 code=PT_CHANGE_REPLICATION 세팅 → 두 번째 절이 가드에 막혀 버려짐 → 세만틱 체크는 CREATE와 달리 중복을 안 봄.
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (a INT);
    ALTER TABLE t REPLICATION=ON, REPLICATION=OFF;   -- 경고 없이 ON만 적용(뒤 OFF 무시)
    -- 대조: CREATE는 에러
    CREATE TABLE t2 (a INT) REPLICATION=ON REPLICATION=OFF;   -- DUPLICATE_TABLE_OPTION 에러
    ```
  - **대조 조건**: REPLICATION 절을 하나만 주면(중복 없음) 정상 적용 → 미발생. CREATE 경로로 같은 중복을 주면 `MSGCAT_SEMANTIC_DUPLICATE_TABLE_OPTION`로 명시적 에러가 나므로, CREATE/ALTER의 비대칭이 곧 원인 특정 지점.
- **신뢰도**: 높음 — 문법 가드로 두 번째 절이 버려지는 경로, CREATE 측 대칭 중복 검사 존재를 양쪽 소스에서 직접 확인. ALTER에 검사 부재도 좌표로 확정.

---

#### K-31. 1375 메시지가 권하는 해결책이 ALTER/HA 컨텍스트에서 -1376으로 차단되는 모순

**관련 코드**
1. `src/query/execute_schema.c:11740~11745` — `do_alter_change_replication()` — HA 모드에서 REPLICATION 변경을 -1376(변경 불가)으로 즉시 거부하는 게이트.
2. `msg/ko_KR.utf8/cubrid.msg:1477` — 메시지 1375 — RK가 없을 때 "REPLICATION 옵션을 OFF로 설정하십시오"라고 안내.

**① do_alter_change_replication() — src/query/execute_schema.c:11740~11745**
```c
/* src/query/execute_schema.c:11740 — do_alter_change_replication(): 안내대로 REPLICATION=OFF 하려 하면 여기서 차단 */
static int
do_alter_change_replication (PARSER_CONTEXT * const parser, PT_NODE * const alter)
{
  ...
  if (!HA_DISABLED ())        /* ← 여기: HA 모드에서는 무조건 */
    {
      error = ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED;   /* -1376 */
      er_set (ER_ERROR_SEVERITY, ARG_FILE_LINE, error, 0);
      goto exit;
    }
  ...
}
```

**② 메시지 1375 — msg/ko_KR.utf8/cubrid.msg:1477**
```
# msg/ko_KR.utf8/cubrid.msg:1477 (메시지 1375)
1375 ... 없을 경우 REPLICATION 옵션을 OFF로 설정하십시오.   /* ← 권하는 해결책이 HA에서 -1376으로 막힘 */
```

- **로직**: RK가 없을 때 나오는 에러 1375는 "없으면 REPLICATION 옵션을 OFF로 설정하십시오"라고 안내한다. 그런데 그 해결책을 실행하려면 `ALTER TABLE ... REPLICATION=OFF`를 해야 하고, 이것을 처리하는 `do_alter_change_replication`은 HA 모드에서 곧바로 -1376(복제 옵션 변경 불가)으로 거부한다(`if (!HA_DISABLED())` → `ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED`). 즉 에러가 권하는 길이 같은 상황에서 막혀 있는 막다른 길이다.
- **시나리오**: 사용자가 에러 안내대로 따라 해도 실행 불가능한 막다른 길.
- **제안**: 메시지에서 실현 가능한 대안(PK/NOT NULL UNIQUE 추가)만 안내하도록 문구 수정.
- **PR 맥락**: ON/OFF 전환 금지 #6477, 에러코드 교체 #6814.
- **재현 명세**:
  - **진입 최소 상태**: HA 모드(`!HA_DISABLED()`가 참이어야 -1376 게이트 발동). 단일 노드에서 HA 파라미터만 켜면 모순 재현 가능. DDL 클라이언트 경로.
  - **스키마·데이터 조건**: RK가 없어 1375를 유발하는 복제 테이블(예: PK도 NOT NULL UNIQUE도 없는 상태로 만들려는 시도). 행 데이터 무관.
  - **실행 순서**: 단일 노드. (1) HA 기동 → (2) RK 없는 테이블 CREATE 시도 → 1375 발생, "REPLICATION=OFF로 하라" 안내 → (3) 안내대로 `ALTER TABLE ... REPLICATION=OFF` → `do_alter_change_replication`이 -1376으로 거부.
  - **최소 재현 입력**:
    ```sql
    -- HA 모드
    CREATE TABLE t (a INT);              -- RK 없음 → ER_HA_REPLICATION_KEY_REQUIRED(-1375), "REPLICATION=OFF 하라"
    ALTER TABLE t REPLICATION=OFF;       -- 안내 따라 시도 → ER_...OPTION_CHANGE_NOT_ALLOWED(-1376) 거부
    ```
  - **대조 조건**: HA를 끄면(`HA_DISABLED()` 참) 11740 게이트를 통과해 REPLICATION=OFF가 실제로 적용된다(모순 미발생) — 즉 이 막다른 길은 HA 모드 전용이다. 또는 처음부터 PK/NOT NULL UNIQUE를 추가하면 1375 자체가 안 난다.
- **신뢰도**: 높음 — 메시지가 권하는 REPLICATION=OFF가 HA에서 -1376으로 차단되는 게이트를 코드에서 직접 확인.

---

#### K3-1. checksumdb가 복제 억제 해제(RPC) 실패를 체크섬 계산 실패로 오판해 성공한 청크까지 롤백·조기 중단하고, 그 실패에 진단 메시지(er_set)도 남기지 않음

**관련 코드**
1. `src/executables/checksumdb.c:1727~1763` — `chksum_calculate_checksum()` — 한 청크의 체크섬을 계산해 마스터 결과 테이블에 기록. 억제 해제 RPC 반환값을 `:1741`에서 무조건 `error`에 대입한다.
2. `src/executables/checksumdb.c:2005~2019` — `chksum_start()` — 호출자. 반환 `error`가 NO_ERROR가 아니면 `db_abort_transaction()`으로 롤백하고 `break`로 남은 청크 처리를 중단.

**① chksum_calculate_checksum() — src/executables/checksumdb.c:1727~1763**
```c
/* src/executables/checksumdb.c:1727 — chksum_calculate_checksum() */
error = db_set_suppress_repl_on_transaction (true);        /* 1727 억제 켜기: 실패 시 er_set 후 return */
if (error != NO_ERROR)
  {
    snprintf (err_msg, LINE_MAX,
              "Failed to suppress the row-based replication log." " (table name: %s, chunk id: %d)", table_name,
              chunk_id);
    er_set (ER_ERROR_SEVERITY, ARG_FILE_LINE, ER_CHKSUM_GENERIC_ERR, 2, err_msg, error);  /* 1733 진단 있음 */
    return error;
  }

res = db_execute (query, &query_result, &query_error);      /* 1737 로컬 계산 실행 */

/* resume row-based replication right after the local execution */
error = db_set_suppress_repl_on_transaction (false);        /* 1741 ← 여기: 반환값 무조건 대입, er_set 없음 */

if (res >= 0)
  {
    db_query_end (query_result);
    res = chksum_update_master_checksum (parser, table_name, chunk_id);  /* 1747 */
    if (res < 0)
      {
        error = res;                                         /* 1750 실패 시만 error 갱신 */
      }
    /* ← res>=0(정상)이면 error는 :1741의 RPC 반환값 그대로 유지 */
  }
else
  {
    ...
    er_set (ER_ERROR_SEVERITY, ARG_FILE_LINE, ER_CHKSUM_GENERIC_ERR, 2, err_msg, res);  /* 1758 */
    error = res;
  }
return error;                                                /* 1762 */
```

**② chksum_start() 호출자 — src/executables/checksumdb.c:2005~2019**
```c
/* src/executables/checksumdb.c:2005 — chksum_start() */
error =
  chksum_calculate_checksum (parser, class_oidp, table_name, attributes, lower_bound, chunk_id,
                             chksum_arg->chunk_size);        /* 2005 */
if (error != NO_ERROR)
  {
    (void) db_abort_transaction ();                          /* 2010 ← 방금 기록한 체크섬 롤백 */
    if (error != ER_INTERRUPTED)
      {
        break;                                               /* 2014 ← 남은 청크 처리 중단 */
      }
    error = NO_ERROR;
    force_refetch_class_info = true;
    SLEEP_MILISEC (0, chksum_arg->sleep_msecs);
    continue;
  }
```

- **로직 (콜체인)**: `chksum_start`가 테이블을 청크 단위로 돌면서 청크마다 `chksum_calculate_checksum`을 부른다. 이 함수는 한 청크의 체크섬을 계산해 마스터 쪽 결과 테이블에 기록한다. 순서는 이렇다. 먼저 이 청크를 재계산하라는 SBR(statement-based replication) 로그를 하나 쓴다 — 슬레이브(복제본)는 이 쿼리를 자기 데이터로 다시 실행해 스스로 체크섬을 구한다. 그런 다음 마스터가 로컬에서 같은 계산을 실행하는데, 이때 마스터가 계산한 체크섬 "행"까지 행 기반(row-based)으로 슬레이브에 실려 가면 슬레이브가 스스로 구한 값을 덮어써 진짜 불일치를 감춰버린다. 그래서 로컬 실행 직전에 `db_set_suppress_repl_on_transaction(true)`로 행 기반 복제를 억제하고(`:1727`), 실행이 끝나면 `db_set_suppress_repl_on_transaction(false)`로 다시 켠다(`:1741`). 두 호출 모두 `net_client_request` 기반의 서버 RPC다. 계산이 끝나면 호출자 `chksum_start`는 반환된 `error`가 `NO_ERROR`가 아니면 방금 기록한 체크섬을 `db_abort_transaction()`으로 롤백하고 `break`로 남은 청크 처리를 통째로 중단한다.

  문제의 핵심은 `:1741`에서 억제 해제 RPC의 반환값을 `error`에 무조건 대입한다는 점이다. 정상 경로(`db_execute`가 `res >= 0`, 이어서 `chksum_update_master_checksum`도 `res >= 0`)에서는 `error`가 다시 세팅되지 않으므로, `:1741`이 남긴 억제-해제 RPC 반환값이 그대로 최종 `error`로 살아남는다.
- **문제 시나리오**: `db_execute`(청크 계산)와 `chksum_update_master_checksum`(마스터 결과 기록)이 모두 성공한 정상 경로에서, 억제 해제 RPC(`:1741`) 한 번이 네트워크·서버 사정으로 실패해 음수를 반환하면 `error != NO_ERROR`가 된다. 그러면 계산 자체는 성공했는데도 `chksum_start`가 이를 실패로 오판해 `db_abort_transaction()`으로 방금 기록한 체크섬을 롤백하고 `break`로 이후 모든 청크·테이블 처리를 조기 종료한다. 데이터 정합성 자체는 abort로 보호되지만, 도구가 아무 결과도 못 남기고 조용히 죽는다. 게다가 억제를 켤 때(`:1727`)와 달리 끌 때(`:1741`)는 `er_set` 호출이 없어, 운영자는 abort·중단의 원인이 무엇인지 에러 로그에서 확인할 수 없다.
- **제안**: 같은 PR(#6908)의 원조 패턴(`execute_statement.c`)처럼 억제-해제 반환값을 무조건 대입하지 말고, 기존 실행 결과가 성공일 때만 조건부로 반영한다. 예: `res >= 0`인 정상 경로에서는 억제-해제 실패를 치명적 오류로 승격시키지 않거나(계산·기록은 이미 커밋 대상이므로), 최소한 별도 지역 변수(`suppress_off_error`)에 받아 실제 실행 실패(`res < 0`)가 없을 때는 별도 로깅만 하고 흐름을 깨지 않도록 한다. 억제 해제가 실패하면 `:1733`과 대칭으로 `er_set(... ER_CHKSUM_GENERIC_ERR ...)`을 남겨 진단 비대칭을 없앤다.
- **재현 명세 (5필드)**
  1. **진입 최소 상태**: `chksum_start`가 청크 루프 진입 후 정상 청크 하나를 계산 완료한 상태. 가드는 호출자 `if (error != NO_ERROR)`(`:2008`) 이후 `if (error != ER_INTERRUPTED) { break; }`(`:2012-2015`) — 억제-해제 RPC 반환값이 `ER_INTERRUPTED`가 아닌 임의 음수이면 곧바로 `break`.
  2. **스키마/데이터 조건**: 복제 대상(replication ON) 사용자 테이블 1개 이상, 청크 1개 이상 생성될 만큼의 행 존재. `checksumdb`가 정상 실행되는 마스터 DB.
  3. **실행 순서 (master→applier→slave)**: 마스터에서 `checksumdb` 실행 중 로컬 청크 계산(`db_execute`)·마스터 결과 기록(`chksum_update_master_checksum`)이 성공한 직후 억제-해제 RPC(`:1741`)만 실패해야 함. 슬레이브/애플라이어 관여 불필요 — 실패 지점이 마스터-서버 RPC이므로 마스터 노드에서 관측되는 결함. (재현 자체는 마스터 단일 노드에서 RPC 실패를 주입해 확인 가능.)
  4. **최소 재현 SQL/명령**: `cubrid checksumdb <db_name>` 실행. RPC 실패 주입은 `db_set_suppress_repl_on_transaction(false)` 반환 경로에 음수를 강제하는 디버거 브레이크포인트/폴트 인젝션(정상 SQL만으로는 결정적 재현 불가, RPC 실패 조건 필요).
  5. **대조 조건**: `:1741`을 별도 변수로 받아 `res >= 0`일 때 흐름에 반영하지 않도록 고치면, 동일 RPC 실패 주입에도 체크섬이 롤백되지 않고 남은 청크가 계속 처리됨.
- **신뢰도**: 높음. 코드 경로(`:1741` 무조건 대입 → 정상 경로 `error` 미갱신 → 호출자 abort+break)와 억제 켜기/끄기 간 `er_set` 비대칭을 소스에서 직접 확인. 다만 트리거 조건이 "성공 경로에서 억제-해제 RPC만 실패"라는 드문 상황이라 실제 발생 빈도는 낮아 severity는 중요 수준이 타당.

---

#### K-11. REPLICATION 토큰이 비예약어(identifier) 목록에서 누락되어 기존 식별자와 충돌

**관련 코드**
1. `src/parser/csql_grammar.y:1669` — REPLICATION 토큰 선언.
2. `src/parser/csql_grammar.y:20755, 20882, 20883` — identifier 비예약 목록 — 이웃 키워드(DISK_SIZE·REUSE_OID·REVERSE)는 등록됐으나 REPLICATION 행이 없어 완전 예약어가 됐다.

**① REPLICATION 토큰 선언 — src/parser/csql_grammar.y:1669**
```yacc
/* src/parser/csql_grammar.y:1669 — 토큰은 선언되어 있음 */
%token <cptr> REPLICATION
```

**② identifier 비예약 목록 — src/parser/csql_grammar.y:20755, 20882, 20883**
```yacc
/* src/parser/csql_grammar.y — identifier 비예약 목록 (일부): 이웃 키워드는 등록됨 */
| DISK_SIZE              {{ SET_CPTR_2_PTNAME($$, $1, @$.buffer_pos); }}   /* :20755 */
| REUSE_OID              {{ SET_CPTR_2_PTNAME($$, $1, @$.buffer_pos); }}   /* :20882 */
| REVERSE                {{ SET_CPTR_2_PTNAME($$, $1, @$.buffer_pos); }}   /* :20883 */
/* ← 여기: 이 목록 어디에도 `| REPLICATION` 행이 없음 → REPLICATION은 완전 예약어 */
```

- **로직**: 함께 추가된 이웃 키워드 `DISK_SIZE/REUSE_OID/REVERSE`는 비예약 identifier 목록에 있는데 `REPLICATION`만 빠져 완전 예약어가 됐다.
- **로직 풀이**: bison 문법에서 키워드는 두 부류다. (1) 완전 예약어 — 식별자로 못 씀, (2) 비예약 키워드 — 문법상 키워드지만 `identifier` 규칙에도 등록해 컬럼/테이블 이름으로도 쓸 수 있게 한 것. CUBRID는 하위 호환을 위해 새 키워드를 대부분 (2)로 넣는다. `csql_grammar.y`의 `identifier` 대체목록(20755~약 20900의 `| KEYWORD {{ SET_CPTR_2_PTNAME(...) }}` 행들)에 `REUSE_OID`(20882)·`REVERSE`(20883)는 있으나 `REPLICATION`(토큰 선언은 1669행에 존재)은 없다 — 이 목록 전체를 grep한 결과 `REPLICATION`의 `SET_CPTR_2_PTNAME` 행이 하나도 없다. 따라서 `REPLICATION`은 (1) 완전 예약어가 되어 식별자로 못 쓴다.
- **시나리오**: 기존에 `replication`을 컬럼/테이블/별칭 이름으로 쓰던 스키마·쿼리가 업그레이드 후 따옴표 없이는 문법 에러로 깨진다(하위 호환 파손).
- **제안**: identifier 규칙에 `REPLICATION` 추가.
- **PR 맥락**: 파서 키워드 추가 #6394. "기존 다른 옵션들과 동일하게" 처리하기로 합의했으나 비예약 등록이 누락됐다.
- **재현 명세**
  - **진입 최소 상태**: 클라이언트 파서(CSQL 등 SQL 입력이 파서를 타는 모든 경로). 특별한 모드/플래그 불요 — 파서는 항상 이 문법을 쓴다.
  - **스키마·데이터 조건**: `replication`이라는 이름의 컬럼/테이블/별칭이 이미 존재하거나 새로 만들려는 상황.
  - **실행 순서**: **단일 노드 재현 가능**(파싱 단계에서 즉시 에러, 서버 실행·HA 불필요).
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (replication INT);   -- syntax error (REPLICATION이 예약어라 컬럼명 불가)
    SELECT a AS replication FROM t;      -- syntax error (별칭 불가)
    CREATE TABLE replication (a INT);    -- syntax error (테이블명 불가)
    -- 우회: 큰따옴표로 quoting해야만 통과
    CREATE TABLE t ("replication" INT);  -- OK
    ```
  - **대조 조건**: `identifier` 규칙에 `| REPLICATION {{ SET_CPTR_2_PTNAME(...) }}` 한 행을 추가하면(=이웃 REUSE_OID와 동일 처리) 따옴표 없이도 통과 → 미발생. 또는 애초에 `replication`을 식별자로 쓰지 않았다면 무영향.
- **신뢰도**: 높음 — 토큰 선언 존재·identifier 목록 부재를 grep으로 이중 확인, 이웃 키워드와의 비대칭도 좌표로 확정.

---

#### K-19. 신규 카탈로그 컬럼 is_replication_class를 db_class 뷰 중간에 삽입해 위치기반 파싱 파손

**관련 코드**
1. `src/object/schema_system_catalog_install.cpp:1312~1317` — db_class 뷰 컬럼 정의 — `is_replication_class`를 `is_system_class`와 `tde_algorithm` 사이에 삽입.
2. `src/object/schema_system_catalog_install_query_spec.cpp:73~75` — SELECT 프로젝션(정의부의 짝) — 동일 위치에 삽입.

**① 컬럼 정의 — src/object/schema_system_catalog_install.cpp:1312~1317**
```cpp
/* src/object/schema_system_catalog_install.cpp:1312 — 컬럼 정의 */
{"is_system_class", format_varchar (3)},
{"is_replication_class", format_varchar (3)},   /* ← 여기: 끝이 아니라 중간 삽입 */
{"tde_algorithm", format_varchar (32)},           /* 이하 서수 전부 +1 밀림 */
{"statistics_strategy", format_varchar (8)},
{"partitioned", format_varchar (3)},
```

**② SELECT 프로젝션(짝) — src/object/schema_system_catalog_install_query_spec.cpp:73~75**
```cpp
/* src/object/schema_system_catalog_install_query_spec.cpp:73 — SELECT 프로젝션, 정의부와 짝 */
"CASE WHEN [c].[is_system_class] = 1 THEN 'YES' ELSE 'NO' END AS [is_system_class], "
"CASE WHEN ([c].[flags] & %d) <> 0 THEN 'NO' ELSE 'YES' END AS [is_replication_class], "  /* ← 여기 (%d=SM_CLASSFLAG_DATA_REPLICATION_OFF) */
"CASE [c].[tde_algorithm] WHEN 0 THEN 'NONE' ... END AS [tde_algorithm], "
```

- **로직**: `is_replication_class`를 뷰 끝이 아니라 `is_system_class`와 `tde_algorithm` 사이에 삽입해 이후 컬럼 서수가 전부 밀렸다(관례=끝에 추가).
- **로직 풀이**: `db_class`(정확히는 뷰 정의 CTV_CLASS_NAME)는 컬럼 정의(catalog install)와 SELECT 프로젝션(query_spec)이 같은 순서로 짝을 이뤄야 하는 시스템 뷰다. 신규 컬럼 `is_replication_class`를 두 파일 모두 `is_system_class` 바로 뒤·`tde_algorithm` 앞에 끼워 넣었다. 정의부(catalog_install:1312-1314)와 프로젝션(query_spec:73-75)이 서로 일치하므로 뷰 자체는 정상 동작하지만, 관례상 신규 컬럼은 뷰 맨 끝에 추가해야 기존 도구의 컬럼 서수가 유지된다. 중간 삽입으로 `tde_algorithm`부터 뒤 컬럼 전체의 위치(ordinal)가 한 칸씩 밀렸다.
- **시나리오**: db_class를 컬럼 위치(서수)로 읽는 드라이버·도구의 메타데이터가 어긋난다.
- **제안**: 컬럼을 뷰 맨 끝으로 이동.
- **PR 맥락**: db_class 조회 기능 #6454, 표기 수정 #6814.
- **재현 명세**
  - **진입 최소 상태**: 어느 노드든 서버가 뜬 상태에서 `SELECT * FROM db_class`를 하는 클라이언트/드라이버. 특별한 모드 불요.
  - **스키마·데이터 조건**: 임의의 테이블(카탈로그에 클래스 1개 이상). 뷰 컬럼 순서 자체가 결함이라 데이터 조건은 무관.
  - **실행 순서**: **단일 노드 재현 가능**(카탈로그 뷰 조회, HA 불필요).
  - **최소 재현 입력**:
    ```sql
    SELECT * FROM db_class;   -- 4번째 컬럼이 tde_algorithm이 아니라 is_replication_class로 바뀜
    -- 위치(서수)로 tde_algorithm을 읽던 도구는 엉뚱한 값을 집음
    ```
  - **대조 조건**: 신규 컬럼을 뷰 **맨 끝**(comment/checked_time 뒤)에 두 파일 동일하게 추가했다면 기존 서수가 보존되어 미발생. 컬럼을 **이름으로만** 참조하는 클라이언트(위치 무관)에게는 애초에 영향 없음.
  - **호환성 주의**: `SELECT *`의 컬럼 순서가 바뀌는 것은 이 뷰 스키마를 소비하는 하위 도구 관점의 회귀이며, 이름 기반 접근에는 영향이 없다.
- **신뢰도**: 높음 — 두 파일에서 삽입 위치(중간)를 좌표로 직접 확인, 정의/프로젝션 짝 일치도 대조. 관례(끝 추가) 위반은 명확.

---

#### K-23. ER_HA_REPLICATION_KEY_REQUIRED 국문 메시지가 ALTER 상황에서도 "테이블 생성 시"로 고정

**관련 코드**
1. `src/query/execute_schema.c:9868~9871` — `check_ha_repl_constraint()` — RK가 없으면 -1375를 발신. CREATE(`:10269`)·ALTER(`:2068`) 두 경로가 공유.
2. `msg/ko_KR.utf8/cubrid.msg:1477` / `msg/en_US.utf8/cubrid.msg:1375` — 메시지 1375 — 국문은 "테이블 생성 시"로 상황 고정, 영문은 "in HA mode"로 중립.

**① check_ha_repl_constraint() 발신부 — src/query/execute_schema.c:9868~9871**
```c
/* src/query/execute_schema.c:9868 — check_ha_repl_constraint(): RK 없으면 발신 (CREATE·ALTER 공용) */
if (!classobj_has_class_repl_key_constraint (db_get_constraints (class_obj)))
  {
    er_set (ER_ERROR_SEVERITY, ARG_FILE_LINE, ER_HA_REPLICATION_KEY_REQUIRED, 0);
    return ER_HA_REPLICATION_KEY_REQUIRED;
  }
```

**② 메시지 1375 국/영문 대조 — msg/ko_KR.utf8/cubrid.msg:1477, msg/en_US.utf8/cubrid.msg:1375**
```
# msg/ko_KR.utf8/cubrid.msg:1477 (메시지 1375)
1375 HA 복제 제약 위반: 테이블 생성 시 복제 후보 키(기본 키 또는 NOT NULL UNIQUE 제약)가 필요합니다. ...  /* ← "테이블 생성 시" 고정 */
# msg/en_US.utf8/cubrid.msg (메시지 1375)
1375 HA constraint violation: A replication key candidate (PRIMARY KEY or NOT NULL UNIQUE) is required in HA mode. ...  /* 상황 중립 */
```

- **로직**: `check_ha_repl_constraint()`는 복제 후보 키(RK)가 없으면 `ER_HA_REPLICATION_KEY_REQUIRED`(-1375)를 던진다. 이 한 함수를 CREATE 경로(10269행)와 ALTER 경로(2068행) 양쪽이 공유한다. 그런데 국문 메시지 문구는 "테이블 생성 시"로 상황을 CREATE로 못박아, `ALTER TABLE ... DROP PRIMARY KEY`로 RK가 사라져 같은 에러가 나는 상황을 잘못 설명한다. 영문판(en_US:1375)은 "in HA mode"로 상황을 특정하지 않아 국/영문이 서로 다르다.
- **시나리오**: `ALTER TABLE ... DROP PRIMARY KEY`에서 이 에러를 만난 한국어 사용자를 오도, 영어판과 불일치.
- **제안**: 메시지를 상황 중립("HA 모드에서 복제 후보 키가 필요합니다")으로.
- **PR 맥락**: 에러 메시지 정정 #6796/#6814 흐름의 연장.
- **재현 명세**:
  - **진입 최소 상태**: HA 모드(`HA_DISABLED()`가 false여야 `check_ha_repl_constraint`가 실제 검사 수행; `HA_DISABLED()`면 곧장 NO_ERROR). 단일 노드에서 HA 파라미터만 켜면 메시지 문구 오류는 관찰 가능. DDL 클라이언트 경로.
  - **스키마·데이터 조건**: RK가 PK 하나뿐이고 복제 대상인 테이블. ALTER로 그 PK를 제거해 RK가 0이 되는 순간을 만든다.
  - **실행 순서**: 단일 노드. (1) HA 모드로 기동 → (2) `ALTER TABLE t DROP PRIMARY KEY` → (3) 반환된 한국어 에러 메시지 문구 확인.
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (a INT PRIMARY KEY);
    ALTER TABLE t DROP PRIMARY KEY;   -- ko 메시지: "테이블 생성 시 ..." (실제는 ALTER)
    ```
  - **대조 조건**: 같은 에러를 CREATE 경로(`CREATE TABLE t (a INT) ...` RK 없이)로 유발하면 문구가 상황과 일치해 오해가 없다. 즉 CREATE에서는 정상, ALTER에서만 문구가 어긋난다. (locale을 en_US로 두면 영문판은 상황 중립이라 문제 미발생.)
- **신뢰도**: 높음 — 단일 함수를 CREATE(10269)·ALTER(2068)가 공유하고 메시지가 "생성 시"로 고정됨을 코드·메시지 파일에서 직접 확인.

---

#### K-10. or_class_is_replication_on이 클래스 플래그를 매직넘버 32로 하드코딩, 주석은 폐기된 옛 상수명 인용

**관련 코드**
1. `src/base/object_representation_sr.c:781~792` — `or_class_is_replication_on()` — 서버가 디스크 클래스 레코드(RECDES)의 flags 비트로 복제 여부를 판정. 플래그 값을 리터럴 32로 하드코딩.
2. `src/object/class_object.h:312` — 실제 enum 정의 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32` — 주석이 인용한 이름(`SM_CLASSFLAG_REPLICATION_OFF`)과 불일치.

**① or_class_is_replication_on() — src/base/object_representation_sr.c:781~792**
```c
/* src/base/object_representation_sr.c:781 — or_class_is_replication_on() */
bool
or_class_is_replication_on (RECDES * record)
{
  int flags = 0;
  int replication_off_flag = 32;  /* SM_CLASSFLAG_REPLICATION_OFF = 32 */  /* ← 여기: 매직넘버 + 폐기된 상수명 */

  or_class_flags (record, &flags);
  return !(flags & replication_off_flag);
}
```

**② 실제 enum 정의 — src/object/class_object.h:312**
```c
/* src/object/class_object.h:312 — 현행 상수명(주석의 이름과 불일치) */
/*   SM_CLASSFLAG_DATA_REPLICATION_OFF = 32   ← 주석이 인용한 SM_CLASSFLAG_REPLICATION_OFF는 코드베이스에 존재하지 않음 */
```

- **로직**: base 계층이 object 계층 헤더를 include할 수 없어 `int replication_off_flag = 32; /* SM_CLASSFLAG_REPLICATION_OFF = 32 */`로 리터럴 하드코딩. 실제 enum명은 `SM_CLASSFLAG_DATA_REPLICATION_OFF`(=32)이고 주석이 인용한 이름은 #6477에서 폐기되어 존재하지 않는다.
- **로직 풀이**: 서버는 디스크에 저장된 클래스 레코드(RECDES)의 flags 비트를 직접 읽어 복제 여부를 판정한다. 정의부(`src/object/class_object.h:312`)에서 확인하면 진짜 enum은 `SM_CLASSFLAG_DATA_REPLICATION_OFF = 32`이며, 주석이 인용한 `SM_CLASSFLAG_REPLICATION_OFF`는 이 코드베이스 어디에도 없다(grep 무결과, #6477 리네임에서 사라짐). 값 32 자체는 우연히 맞지만, 소스 상수를 참조하지 않고 숫자를 박아넣은 탓에 나중에 누가 enum 값을 바꿔도 컴파일러가 불일치를 잡지 못한다.
- **시나리오**: 나중에 enum 값이 바뀌면 컴파일 에러 없이 서버 측 복제 판정이 조용히 틀어진다.
- **제안**: 헤더 의존을 피하려면 static_assert로 값 일치를 강제하거나, 값을 노출하는 경량 접근자 헤더를 둔다. 최소한 주석의 상수명을 현행으로 정정.
- **PR 맥락**: 네이밍 리팩토링 #6477이 옛 주석을 남겼다.
- **재현 명세**
  - **진입 최소 상태**: 서버 프로세스(`SERVER_MODE`). `object_representation_sr.c`는 base 계층이라 object 계층 헤더(`class_object.h`)를 include할 수 없어 심볼 대신 리터럴을 쓴다 — 이것이 하드코딩의 근본 원인. 별도 플래그 불요.
  - **스키마·데이터 조건**: 임의 클래스 레코드. 현재 값이 32로 일치하므로 어떤 데이터로도 오동작하지 않는다.
  - **실행 순서**: **단일 노드(서버)·정적 결함**. 런타임 왕복 불필요.
  - **최소 재현 입력**: **트리거 불가(정적 결함)** — 현재 값이 일치하므로 오동작이 나타나지 않는다. 결함은 "미래 enum 변경 시 컴파일 에러 없이 조용히 틀어짐"이라는 잠재 위험이며, 재현하려면 `class_object.h`의 enum 값을 인위적으로 바꿔 두 곳이 어긋나게 만들어야 한다.
  - **대조 조건**: `SM_CLASSFLAG_DATA_REPLICATION_OFF` enum 값이 32로 유지되는 한 오동작 없음. 값을 바꾸면(가정) or_class_is_replication_on만 옛 32를 계속 봐서 판정이 반전.
- **신뢰도**: 높음 — 매직넘버·주석의 폐기 상수명은 코드로 확정, 실제 enum명/값(`DATA_REPLICATION_OFF=32`)도 정의부에서 대조 확인. 단 현재는 값 일치라 무증상(잠재 결함).

### 보통 (23건)

#### K-32. TRUNCATE가 REPLICATION=OFF를 무시하고 RK만으로 복제 로그 생성
- **심각도**: 보통
- **로직**: `do_replicate_statement()`는 마스터에서 DDL/일부 DML을 슬레이브에 문장 그대로 보내기 위해 복제 로그를 남기는 함수로, 진입 즉시 `log_does_allow_replication()`(HA 활성)일 때만 동작한다. `PT_TRUNCATE` 절에서 이 함수는 `truncate_need_repl_log()`가 true면 `CUBRID_STMT_TRUNCATE` 복제 레코드를 만든다. 그런데 `truncate_need_repl_log()`는 대상 테이블에 RK(PK 또는 NOT NULL UNIQUE)가 있는지(`classobj_find_cons_replication_key`)만 보고, 테이블이 `REPLICATION=OFF`(`SM_CLASSFLAG_DATA_REPLICATION_OFF`)인지는 전혀 확인하지 않는다. 반면 같은 테이블의 일반 INSERT/UPDATE/DELETE는 서버가 `heap_get_class_repl_on()`으로 OFF 플래그를 보고 복제를 억제한다. 즉 진입점(TRUNCATE vs DML)마다 OFF 처리가 갈린다.
- **관련 코드**
  1. `src/query/execute_statement.c:341-384` — `truncate_need_repl_log()` — TRUNCATE 대상에 RK가 있으면 "복제 필요"로 판정 (OFF 플래그 미검사)
  2. `src/query/execute_statement.c:16673-16682` — `do_replicate_statement()` — `PT_TRUNCATE`에 대해 복제 레코드 생성 (`log_does_allow_replication()` 게이트 하위)

**① truncate_need_repl_log() — src/query/execute_statement.c:341~384**
```c
/* src/query/execute_statement.c:361 — truncate_need_repl_log() */
  for (entity = entity_list; entity != NULL; entity = entity->next)
    {
      class_name = entity->info.name.original;
      class_mop = db_find_class (class_name);
      ...
      error = au_fetch_class (class_mop, &class_, AU_FETCH_READ, DB_AUTH_NONE);
      ...
      cons = classobj_find_cons_replication_key (class_->constraints);   /* ← RK 유무만 본다 */
      if (cons != NULL)
        {
          return true;      /* ← 여기: DATA_REPLICATION_OFF 검사 없이 "복제 필요" */
        }
    }
  return false;
```

**② do_replicate_statement() — src/query/execute_statement.c:16673~16682**
```c
/* src/query/execute_statement.c:16673 — do_replicate_statement() (log_does_allow_replication() 게이트 하위) */
    case PT_TRUNCATE:
      if (!truncate_need_repl_log (statement))
        {
          return NO_ERROR;
        }
      ...
      repl_stmt.statement_type = CUBRID_STMT_TRUNCATE;   /* ← 여기: OFF 테이블도 여기 도달 */
```

- **재현 명세**
  - **진입 최소 상태**: HA 모드 마스터 서버(cub_server). `do_replicate_statement`가 `log_does_allow_replication () == false`면 즉시 반환하므로(`:16514`) HA 복제가 켜진 상태여야 진입한다.
  - **스키마·데이터 조건**: `REPLICATION=OFF`로 만든 테이블 `t`에 PK 또는 NOT NULL UNIQUE(RK) 존재. 행 몇 건 적재.
  - **실행 순서**: master에서 `TRUNCATE t` → `truncate_need_repl_log()`=true → `CUBRID_STMT_TRUNCATE` 복제 로그 기록 → copylogdb/applylogdb가 slave에서 TRUNCATE 재실행 → slave의 `t`가 비워진다. 그러나 같은 `t`에 대한 INSERT/UPDATE/DELETE는 OFF라 복제되지 않아, 슬레이브 `t`가 마스터와 독립적으로 삭제된다.
  - **최소 재현 입력**: (양 노드) `CREATE TABLE t(a INT PRIMARY KEY) REPLICATION=OFF; INSERT INTO t VALUES(1);` → 마스터에서 `TRUNCATE TABLE t;`
  - **대조 조건**: `t`에 RK가 아예 없으면 `truncate_need_repl_log`가 false를 반환해 복제되지 않아 불일치가 없다(`:376-379`가 근거). 또는 `REPLICATION=ON`이면 DML도 함께 복제되어 정합.
- **제안**: `truncate_need_repl_log`의 RK 검사 앞에 `!(class_->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF)`(또는 `sm_is_replication_class(class_mop)`) AND 조건을 추가.
- **PR 맥락**: #6826(truncate bug fix)에서 PK 검사를 RK 검사로 확장했는데, 그 경로에 REPLICATION=OFF 플래그 검사가 빠졌다.
- **신뢰도**: 높음 — 분기 조건식(376-379에 OFF 플래그 부재, 16514 HA 게이트)을 코드로 확정. 슬레이브 실제 divergence는 2노드 실측 시 확인 권장이나 경로는 확정.

---

#### K-53. 상속(UNDER)이 부모 REPLICATION 옵션을 상속하지 않음(파티션과 불일치)
- **심각도**: 보통
- **핵심 문제**: 부모가 OFF여도 옵션을 생략한 자식은 기본 ON이 된다.
- **로직**: `CREATE TABLE`이 복제 옵션을 정할 때, `LIKE` 분기는 원본 테이블 플래그를 상속(`is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF)`)한다. 그러나 `UNDER`(상속) 분기는 이 `else`로 떨어져 `IS_CREATE_STMT_SET_REPL_OPTION(tbl_opt_replication)`만 본다. 이 매크로는 옵션이 생략되면(`NULL`) **무조건 ON**이므로, REPLICATION=OFF 부모를 상속하며 옵션을 생략한 자식은 부모 의도와 달리 ON이 된다. 파티션(`do_create_partition`은 부모 OFF를 상속)과도 동작이 불일치.
- **관련 코드**
  1. `src/query/execute_schema.c:96-97` — `IS_CREATE_STMT_SET_REPL_OPTION` 매크로 — 옵션 생략(NULL) 시 무조건 ON으로 평가
  2. `src/query/execute_schema.c:10258-10265` — `do_create_entity()` — LIKE만 부모 플래그 상속, UNDER는 super_class 플래그 미반영

**① IS_CREATE_STMT_SET_REPL_OPTION 매크로 — src/query/execute_schema.c:96~97**
```c
/* src/query/execute_schema.c:96 — IS_CREATE_STMT_SET_REPL_OPTION */
#define IS_CREATE_STMT_SET_REPL_OPTION(_opt) \
  ( (_opt) == NULL || (_opt)->info.table_option.val->info.value.data_value.i )   /* ← 생략 시 ON */
```

**② do_create_entity() — src/query/execute_schema.c:10258~10265**
```c
/* src/query/execute_schema.c:10258 — do_create_entity() */
if (create_like)
  is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF);   /* LIKE: 부모 상속 */
else
  is_replication_on = IS_CREATE_STMT_SET_REPL_OPTION (tbl_opt_replication); /* ← 여기: UNDER super_class 플래그 미반영 */
```

- **시나리오**: `CREATE TABLE child UNDER parent_off (...)`에서 자식이 부모의 REPLICATION=OFF를 이어받지 못하고 기본 ON이 되어, 사용자가 의도한 복제 제외가 조용히 뒤집힌다.
- **재현 명세**
  - **진입 최소 상태**: 단일 노드 재현 가능(플래그 설정 자체는 HA 무관, RK 검사만 HA 모드에서 `check_ha_repl_constraint` 발동).
  - **스키마·데이터 조건**: REPLICATION=OFF로 만든 부모 테이블 + 옵션 생략한 상속 자식.
  - **실행 순서**: 단일 노드. 부모 CREATE(OFF) → 자식 `UNDER` CREATE(옵션 생략) → 자식 플래그 ON.
  - **최소 재현 입력**: `CREATE TABLE p(a INT) REPLICATION=OFF; CREATE TABLE c UNDER p (b INT);` → `SHOW CREATE TABLE c`가 `REPLICATION=ON`.
  - **대조 조건**: 자식에 `REPLICATION=OFF`를 명시하면 정상; 또는 `LIKE`로 만들면(부모 플래그 상속) OFF가 유지된다.
- **제안**: super_class 플래그 상속.
- **신뢰도**: 높음 — LIKE만 부모 상속하고 UNDER는 `else`로 기본 ON임을 코드에서 직접 확인.

---

#### K-54. `do_alter_change_replication`이 FK·역참조 복제 제약을 재검증하지 않음
- **심각도**: 보통
- **핵심 문제**: 싱글모드 ON/OFF 전환 시 `check_ha_repl_constraint`를 호출하지 않아, OFF 전환으로 자식 FK 참조가 깨지거나 RK 없는 테이블의 ON 전환이 rkcheck에서야 드러난다.
- **로직**: `ALTER TABLE ... REPLICATION=ON|OFF`를 처리하는 이 함수는 HA 모드에서는 `!HA_DISABLED()` 게이트로 아예 차단(-1376)되고, 싱글 모드에서만 플래그를 바꾼다. 그런데 플래그 설정(`sm_set_class_flag`) 전후로 `check_ha_repl_constraint`(RK 존재 + FK 참조 대상 복제여부 검사)를 **한 번도 부르지 않는다.** CREATE 경로(:10269)는 이 검사를 부르는데, ALTER 전환 경로는 빠졌다.
- **관련 코드**
  1. `src/query/execute_schema.c:11729-11827` — `do_alter_change_replication()` — 싱글모드에서 REPLICATION 플래그만 바꾸고 RK/FK 제약 재검증 없음

**① do_alter_change_replication() — src/query/execute_schema.c:11740~11801**
```c
/* src/query/execute_schema.c:11740 — do_alter_change_replication() */
if (!HA_DISABLED ())
  { error = ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED; ... goto exit; }
...
class_mop = ctemplate->op;
error = sm_set_class_flag (class_mop, SM_CLASSFLAG_DATA_REPLICATION_OFF,
                           !IS_ALTER_STMT_SET_REPL_OPTION (replication_node)); /* ← 플래그만 바꾸고 */
/* ← 여기: check_ha_repl_constraint() 호출 없음 — RK/FK 재검증 생략 */
```

- **시나리오**: 싱글 모드에서 RK 없는 테이블을 `REPLICATION=ON`으로 켜도 이 시점엔 거부되지 않고, 나중에 HA 기동 시 rkcheck에서야 위반이 드러난다. 반대로 FK가 참조하는 부모를 OFF로 바꿔 참조 무결성-복제 제약이 깨져도 전환 시점에 막지 못한다.
- **재현 명세**
  - **진입 최소 상태**: 단일(비-HA) 노드. `HA_DISABLED()`가 true여야 전환이 허용된다(HA 모드면 -1376으로 차단).
  - **스키마·데이터 조건**: RK 없는 테이블(ON 전환용) 또는 FK로 참조되는 부모 테이블(OFF 전환용).
  - **실행 순서**: 단일 노드. `ALTER ... REPLICATION=ON/OFF` → 플래그 변경 → 제약 재검증 없이 커밋.
  - **최소 재현 입력**: `CREATE TABLE t(a INT) REPLICATION=OFF; ALTER TABLE t REPLICATION=ON;` (t에 RK 없음) → 전환 성공, 이후 HA 기동 시 rkcheck 실패.
  - **대조 조건**: 전환 함수가 CREATE처럼 `check_ha_repl_constraint`를 부르면 RK 없는 ON 전환이 즉시 거부된다.
- **제안**: 전환 경로에 제약 재검증 추가.
- **신뢰도**: 높음 — 함수 본문에 `check_ha_repl_constraint` 호출이 없음을 코드에서 직접 확인(CREATE 경로와 대조).

---

#### K-57. `check_ha_repl_fk_ref_all_replicated`가 참조 클래스 fetch 실패를 비복제로 오판 → 스퓨리어스 CREATE 거부
- **심각도**: 보통
- **핵심 문제**: `ws_mop`/`sm_is_replication_class`가 실패하면 ON 테이블도 OFF로 오판되어, 정상 FK가 위반으로 거부된다.
- **로직**: FK가 참조하는 모든 부모 테이블이 복제 대상인지 검사하는 함수다. FK마다 `ws_mop(&ref_class_oid)`로 부모 객체를 얻어 `sm_is_replication_class`로 복제 여부를 본다. 그런데 `sm_is_replication_class`는 조회/NULL 실패를 `assert(false); return false`로 삼키므로(K-7), 부모 객체 fetch가 일시 실패하면 실제로는 복제 ON인 부모도 "비복제"로 판정되고, 이 함수가 `false`를 반환해 정상 FK를 가진 CREATE가 위반으로 거부된다.
- **관련 코드**
  1. `src/query/execute_schema.c:9782-9803` — `check_ha_repl_fk_ref_all_replicated()` — FK 참조 부모의 복제 여부 검사, fetch 실패를 false(비복제)로 오판

**① check_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9782~9803**
```c
/* src/query/execute_schema.c:9789 — check_ha_repl_fk_ref_all_replicated() */
for (tmp_c = db_get_constraints (class_obj); tmp_c; tmp_c = db_constraint_next (tmp_c))
  {
    if (tmp_c->type != SM_CONSTRAINT_FOREIGN_KEY) continue;
    if (!sm_is_replication_class (ws_mop (&(tmp_c->fk_info->ref_class_oid), NULL)))  /* ← 여기: fetch 실패=false=비복제 오판 */
      return false;                 /* ← 정상 FK CREATE가 거부됨 */
  }
return true;
```

- **시나리오**: 부모 테이블 fetch가 일시 실패(락/조회 오류)하면, 실제로는 복제 ON인 부모를 참조하는 정상 FK 테이블 CREATE가 "참조 대상이 비복제"라는 이유로 거부된다. 조회 실패가 곧 정책 위반으로 둔갑.
- **재현 명세**
  - **진입 최소 상태**: HA 모드(`check_ha_repl_constraint`가 이 함수를 부르는 경로는 `HA_DISABLED()`가 false일 때). CREATE/ALTER 클라이언트 경로.
  - **스키마·데이터 조건**: FK로 복제 ON 부모를 참조하는 자식 테이블. 부모 객체 fetch가 실패하는 상태(일시 락/조회 오류).
  - **실행 순서**: 단일 노드에서 판정 관찰 가능(클라이언트 계층). CREATE 자식(FK 포함) → `check_ha_repl_constraint` → `check_ha_repl_fk_ref_all_replicated` → `sm_is_replication_class` fetch 실패 → false → CREATE 거부.
  - **최소 재현 입력**: 정상 입력으로는 통과. 트리거하려면 부모 클래스 fetch를 실패시켜야 한다(경계 케이스).
  - **대조 조건**: 부모 객체 fetch가 정상이면 실제 복제 상태를 올바로 읽어 정상 FK가 통과한다.
- **제안**: fetch 실패를 에러로 구분(K-8 연동).
- **신뢰도**: 높음 — fetch 실패 삼킴(K-7)이 이 함수의 `false` 반환으로 직결됨을 코드에서 확인. 실제 fetch 실패 유발 조건은 경계 케이스.

---

#### K3-2. ALTER VIEW/VCLASS에 REPLICATION 옵션 지정 시 entity_type 검증 부재로 뷰에 무의미한 DATA_REPLICATION_OFF 플래그가 에러 없이 설정됨
- **심각도**: 보통
- **로직**: `ALTER VIEW v REPLICATION=OFF` 같은 문장의 처리는 세 단계를 거친다. (1) 문법(`csql_grammar.y`): `opt_class_type`가 `VIEW`/`VCLASS`를 `PT_VCLASS`로 받고(`:5720-5729`), `class_replication_spec`가 `alter.code`를 `PT_CHANGE_REPLICATION`으로 세팅해(`:5866-5869`) 파싱이 성공한다. (2) 세만틱 체크(`semantic_check.c`의 `pt_check_alter`): 여기서 클래스를 찾고 entity_type이 실제 타입과 맞는지 검사한 뒤(`:4864-4870`, `PT_VCLASS`면 `db_is_vclass`로 통과만 시킴), `code`에 대한 `switch`(`:4882~`)로 코드별 추가 검증을 하는데 이 switch에 `PT_CHANGE_REPLICATION` case가 아예 없어(파일 전체 심볼 부재) 뷰가 복제 대상이 될 수 있는지 같은 의미 검증이 전혀 일어나지 않는다. (3) 실행(`execute_schema.c`의 `do_alter_change_replication`): `HA_DISABLED()`면 통과하고(`:11740`), `db_find_class`로 찾은 객체에 entity_type 검사 없이 `sm_set_class_flag(class_mop, SM_CLASSFLAG_DATA_REPLICATION_OFF, ...)`(`:11795-11796`)를 그대로 설정한다. 뷰의 `SM_CLASS`에도 아무 저항 없이 플래그가 박힌다.
- **관련 코드**
  1. `src/parser/csql_grammar.y:5862-5871` — `class_replication_spec` — VIEW에도 `alter.code = PT_CHANGE_REPLICATION`을 동일하게 세팅해 파싱 성공
  2. `src/parser/semantic_check.c:4864-4882` — `pt_check_alter()` — entity_type 타입일치만 확인, code switch에 `PT_CHANGE_REPLICATION` 뷰 거부 case 없음
  3. `src/query/execute_schema.c:11740-11796` — `do_alter_change_replication()` — 뷰/클래스 구분 없이 `sm_set_class_flag(REPLICATION_OFF)` 설정

**① class_replication_spec (문법) — src/parser/csql_grammar.y:5862~5871**
```c
/* src/parser/csql_grammar.y:5862 — class_replication_spec */
    | class_replication_spec
        {{
            PT_NODE *alter_node = parser_get_alter_node();
            if (alter_node != NULL && alter_node->info.alter.code != PT_CHANGE_REPLICATION)
              {
                alter_node->info.alter.code = PT_CHANGE_REPLICATION;   /* ← 여기: VIEW에도 동일하게 세팅 */
                alter_node->info.alter.alter_clause.replication.tbl_replication = $1;
              }
        }}
```

**② pt_check_alter() — src/parser/semantic_check.c:4864~4882**
```c
/* src/parser/semantic_check.c:4864 — pt_check_alter() */
      type = alter->info.alter.entity_type;
      if ((type == PT_CLASS && db_is_class (db) <= 0) || (type == PT_VCLASS && db_is_vclass (db) <= 0))
        {                                                       /* ← v가 vclass면 그냥 통과 */
          PT_ERRORmf2 (parser, alter, ..., MSGCAT_SEMANTIC_IS_NOT_A, ...);
          return;
        }
    ...
  code = alter->info.alter.code;
  switch (code)                                                 /* :4882 ← PT_CHANGE_REPLICATION case 없음 */
    {
    case PT_ADD_ATTR_MTHD:
      ...
    /* ← 여기: PT_CHANGE_REPLICATION 에 대한 뷰 거부 검증이 존재하지 않음 */
    }
```

**③ do_alter_change_replication() — src/query/execute_schema.c:11740~11796**
```c
/* src/query/execute_schema.c:11740 — do_alter_change_replication() */
  if (!HA_DISABLED ())                                          /* :11740 */
    {
      error = ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED;
      er_set (...); goto exit;
    }
  ...
  class_obj = db_find_class (entity_name);                      /* :11763 ← 뷰/클래스 구분 없이 찾음 */
  ...
  class_mop = ctemplate->op;
  error =
    sm_set_class_flag (class_mop, SM_CLASSFLAG_DATA_REPLICATION_OFF,   /* :11795 ← 여기: 뷰에도 플래그 설정 */
                       !IS_ALTER_STMT_SET_REPL_OPTION (replication_node));
```

- **시나리오**: `ALTER VIEW v REPLICATION=OFF`(또는 `ALTER VCLASS`)가 문법·세만틱·실행 어느 단계에서도 거부되지 않고 성공하며, 뷰의 `SM_CLASS`에 `SM_CLASSFLAG_DATA_REPLICATION_OFF`가 설정된다. 뷰는 heap 데이터가 없어 DML 복제 대상이 될 수 없으므로 이 플래그는 원천적으로 무의미한데도 남는다. 이후 `SHOW CREATE VIEW`/`unloaddb`에 `REPLICATION=OFF`가 출력돼 사용자·운영자에게 "이 뷰에 복제 설정이 걸려 있다"는 잘못된 인상을 주고, 스키마 재적재 시 혼란을 유발한다. `HA_DISABLED()`가 기본값인 대다수 비HA 설치에서 재현된다.
- **재현 명세**
  - **진입 최소 상태**: 비HA 설치(`HA_DISABLED()`가 참). 실행 가드는 `do_alter_change_replication`의 `if (!HA_DISABLED ())`(`:11740`) — HA 미사용이면 이 블록을 건너뛰어 플래그 설정까지 도달.
  - **스키마·데이터 조건**: 임의 기반 테이블 1개와 그 위의 뷰(vclass) 1개. 데이터 유무 무관.
  - **실행 순서**: 단일 노드 재현(비HA, 마스터/슬레이브 불필요).
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (a INT);
    CREATE VIEW v AS SELECT a FROM t;
    ALTER VIEW v REPLICATION=OFF;   -- 에러 없이 성공 (버그)
    SHOW CREATE VIEW v;             -- REPLICATION=OFF 노출로 확인
    ```
  - **대조 조건**: 동일 문장을 실제 테이블에 걸면(`ALTER TABLE t REPLICATION=OFF`) 의도된 동작. 뷰에 대해서는 세만틱 에러로 거부되어야 정상.
- **제안**: `pt_check_alter`의 code switch에 `PT_CHANGE_REPLICATION` case를 추가해 `alter.entity_type`이 `PT_VCLASS`이거나 `db_is_vclass(db) > 0`이면 세만틱 에러(`MSGCAT_SEMANTIC_IS_NOT_A` 또는 전용 메시지)로 거부한다. 이중 방어로 `do_alter_change_replication`에서도 `db_is_vclass` 체크 후 뷰면 에러 반환하도록 가드를 추가한다. (K-20 중복/혼합 절, K-68 뷰 출력과는 원인이 다른 세만틱 검증 자체의 부재이므로 별개 수정 지점.)
- **신뢰도**: 높음 — 세 단계 모두 소스에서 검증(문법 파싱 성공, semantic switch case 부재 grep 0건, 실행부 entity_type 미검사·플래그 설정). 비HA 기본 환경에서 순수 SQL만으로 결정적 재현 가능.

---

#### K-44. us_hb_process_rkcheck가 첫 실패 DB에서 break
- **심각도**: 보통
- **로직**: `cubrid hb start`(db_name 미지정)는 `us_hb_process_rkcheck()`가 `ha_conf->db_names`를 순서대로 돌며 DB마다 `cub_admin rkcheck`를 자식 프로세스로 실행한다. 그런데 어느 DB에서 `proc_execute()`가 실패(=위반 발견)를 반환하면 즉시 `break`로 루프를 빠져나온다. 결과적으로 뒤 순서 DB들은 위반이 있어도 점검되지 않은 채 hb start가 종료된다.
- **관련 코드**
  1. `src/executables/util_service.c:3205-3238` — `us_hb_process_rkcheck()` — DB 목록을 순회하며 rkcheck 실행, 첫 실패에서 `break`(`:3236`)

**① us_hb_process_rkcheck() — src/executables/util_service.c:3205~3238**
```c
/* src/executables/util_service.c:3205 — us_hb_process_rkcheck() */
  for (i = 0; dbs[i] != NULL; i++)
    {
      ...
      status = proc_execute (UTIL_ADMIN_NAME, rkcheck_args, true, false, false, NULL);
      if (status != NO_ERROR)
        {
          break;          /* ← 여기: 첫 실패 DB에서 순회 중단, 뒤 DB 미점검 */
        }
    }
```

- **재현 명세**
  - **진입 최소 상태**: HA 기동 경로 — `cubrid hb start`가 `us_hb_process_start`(3969)를 통해 `us_hb_process_rkcheck`를 호출. db_name을 지정하지 않아 전체 순회에 진입해야 한다(3208 `continue` 게이트 참조).
  - **스키마·데이터 조건**: `database.txt`(ha_conf)에 HA DB가 2개 이상, 그중 둘 이상에 각각 독립적 RK/FK 위반.
  - **실행 순서**: hb start → 순회 중 앞선 위반 DB에서 `break` → 나머지 DB 미점검 → 운영자는 앞 DB만 고치고 재시도 → 다음 실행에서야 뒤 DB 위반을 처음 본다(반복 재기동).
  - **최소 재현 입력**: `database.txt`에 `db1,db2`, 둘 다 RK 위반 테이블을 만든 뒤 `cubrid hb start` → db1 위반만 보고됨.
  - **대조 조건**: 위반 DB가 하나뿐이거나 `hb start <db>`로 특정 DB만 지정하면(3208) 이 누락이 없다.
- **제안**: `break` 대신 실패를 기록만 하고 계속 순회해, 모든 DB 위반을 한 번에 집계 보고한 뒤 마지막에 실패 반환.
- **신뢰도**: 높음 — 루프·break 구조 확정.

---

#### K-46. rkcheck 중단 시 `.list` 위반목록 파일에 완료 표시가 없어 "이상없음"으로 오인
- **심각도**: 보통
- **핵심 문제**: 조기 종료 시 부분 결과만 남아, 파일만 보고는 정상 종료와 구분할 수 없다.
- **로직**: `rkcheck()`는 서버 기동 후 `.list` 파일(`fp`)을 열고, RK/FK 각 섹션 제목을 `fp`에 찍은 뒤 `check_repl_constraint_violations()`로 위반을 순회한다. 위반이 0이면 섹션에 "compliance" 문장을 남긴다. 그런데 검사가 성공적으로 끝났음을 알리는 **완료 문장은 `.list` 파일이 아니라 터미널(`stdout`)에만** 출력된다. 따라서 검사가 중간에 실패(`goto end1`)해 부분 결과만 남은 `.list`와, 정상적으로 "위반 없음"으로 끝난 `.list`를 파일만 봐서는 구분할 수 없다.
- **관련 코드**
  1. `src/executables/util_cs.c:3320-3393` — `rkcheck()` — RK/FK 섹션 순회 후 완료 문장을 `.list`(`fp`)가 아닌 `stdout`에만 출력

**① rkcheck() — src/executables/util_cs.c:3320~3393**
```c
/* src/executables/util_cs.c:3330 — rkcheck() (RK 섹션: 에러면 완료 표시 없이 end1로 이탈) */
if ((repl_check_flags & REPL_CHECK_RK) != 0)
  {
    PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);
    err = check_repl_constraint_violations (classes, fp, check_rk_constraint, &rk_violation_count);
    if (err != NO_ERROR)
      {
        PRINT_AND_LOG_ERR_MSG (...);
        goto end1;                                  /* ← 여기: .list엔 섹션 제목만 남고 중단 */
      }
    if (rk_violation_count == 0)
      PRINT_MESSAGE (fp, RK_CONSTRAINT_COMPLIANCE_MESSAGE);
    ...
  }
...
/* src/executables/util_cs.c:3393 — "완료" 문장은 fp가 아니라 stdout에만 */
fprintf (stdout, "\nConstraint checks completed for all replication-enabled tables.\n\n"); /* ← 여기 */
end1:
  ...
```

- **시나리오**: `check_repl_constraint_violations`가 중간 클래스에서 실패해 `end1`로 빠지면, `.list`에는 섹션 제목만 있고 위반 목록도 완료 표시도 없다. 사후에 이 파일을 열어 본 운영자가 "위반이 안 찍혔으니 이상 없음"으로 오판한다.
- **재현 명세**
  - **진입 최소 상태**: 단일 노드에서 재현 가능. `cubrid rkcheck <db>` 유틸리티(또는 `cubrid hb start`가 자동 실행) 프로세스 하나면 된다. 서버가 정상 기동되어 `.list` 파일이 열린 뒤(`fp != NULL`), RK 또는 FK 순회 중 오류가 나야 한다.
  - **스키마·데이터 조건**: `check_repl_constraint_violations` 루프가 오류로 이탈할 조건 — 예를 들어 순회 도중 `db_is_vclass (c->op) < 0`가 되도록 카탈로그 조회를 실패시키는 클래스(락/일시 오류)가 하나 있으면 된다.
  - **실행 순서**: 단일 노드. rkcheck 기동 → 서버 재시작 성공 → `.list` open → RK 섹션 제목 출력 → 순회 중 오류 → `end1` → 파일 닫힘. 완료 문장은 stdout에만.
  - **최소 재현 입력**: `cubrid rkcheck -r <db>` 실행 중 특정 클래스 조회를 실패시키기(권한 회수·락 등). 순수 정적 관찰로도 "정상 종료 시 완료 문장이 fp로 안 감"은 코드로 확인된다.
  - **대조 조건**: 완료 문장을 `PRINT_MESSAGE(fp, ...)`로 `.list`에도 남기면, 파일만 보고도 정상 종료/중단을 구분할 수 있어 오인이 사라진다.
- **제안**: 완료 sentinel을 `.list`에 기록.
- **신뢰도**: 높음 — 완료 문장이 `fp`가 아닌 `stdout`으로만 나가고 에러 경로가 완료 표시 없이 이탈함을 코드에서 직접 확인.

---

#### K-47. `check_repl_constraint_violations`가 오류 시 실패한 클래스 이름을 기록하지 않음
- **심각도**: 보통
- **핵심 문제**: `db_is_vclass < 0`일 때 어느 클래스에서 실패했는지 로그가 없다.
- **로직**: 이 함수는 전체 클래스 목록을 돌며 각 클래스가 뷰인지(`db_is_vclass`) 검사한다. 이 호출이 음수(오류)를 반환하면 그 값을 그대로 상위로 되돌리고 종료하는데, **어느 클래스에서 실패했는지**는 아무 데도 남기지 않는다. 상위 `rkcheck()`는 `"RK constraint check failed (error=%d)"`처럼 에러 코드만 찍으므로, 운영자는 문제 클래스를 특정할 수 없다.
- **관련 코드**
  1. `src/executables/util_cs.c:2928-2951` — `check_repl_constraint_violations()` — `db_is_vclass<0` 시 실패 클래스명 없이 그대로 반환

**① check_repl_constraint_violations() — src/executables/util_cs.c:2928~2951**
```c
/* src/executables/util_cs.c:2935 — check_repl_constraint_violations() */
for (c = classes; c != NULL; c = c->next)
  {
    is_vclass = db_is_vclass (c->op);
    if (is_vclass < 0)
      {
        return is_vclass;                 /* ← 여기: 실패 클래스명(c->op) 없이 그냥 반환 */
      }
    if (db_is_system_class (c->op) || is_vclass > 0 || !sm_is_replication_class (c->op))
      continue;
    *violation_count += check_func (c->op, fp);
  }
```

- **시나리오**: 특정 클래스에서 일시적 조회 실패가 나면 rkcheck는 "error=N"만 남기고 죽는다. `cubrid hb start`가 이걸 자동 실행하므로, DBA는 어떤 테이블이 HA 기동을 막았는지 모른 채 원인 추적에 시간을 쓴다.
- **재현 명세**
  - **진입 최소 상태**: 단일 노드에서 재현 가능. rkcheck 유틸리티 프로세스. `is_vclass < 0` 분기 진입.
  - **스키마·데이터 조건**: `db_is_vclass`가 음수를 반환할 클래스(카탈로그 페이지 조회 실패·락 충돌 등)가 목록에 하나라도 있으면 된다.
  - **실행 순서**: 단일 노드. rkcheck → `db_get_all_classes()` → 루프 진입 → 문제 클래스에서 `db_is_vclass<0` → 클래스명 없이 반환.
  - **최소 재현 입력**: 정적 결함(로깅 누락). 트리거하려면 순회 중 특정 클래스 조회를 강제로 실패시켜야 한다.
  - **대조 조건**: 모든 클래스 조회가 정상이면 이 경로에 도달하지 않아 로깅 누락이 드러나지 않는다.
- **제안**: 실패 클래스명을 `er_set`/로깅.
- **신뢰도**: 높음 — 실패 반환 지점에 클래스 식별 정보 기록이 전혀 없음을 코드에서 확인.

---

#### K-38. rkcheck check_database_name 실패 시 에러 없이 종료
- **심각도**: 보통
- **로직**: `rkcheck()`는 `db_restart()` 실패 시에는 `PRINT_AND_LOG_ERR_MSG(...)`로 명확한 메시지를 남기지만(3313), 바로 앞의 `check_database_name()` 실패 분기(3304)에서는 `err = ER_FAILED; goto end2;`만 하고 아무 메시지도 남기지 않는다. `check_database_name` 실패 시 `er_set()`이 호출되지 않아 `db_error_string()`이 빈 문자열이 되는 문제다.
- **관련 코드**
  1. `src/executables/util_cs.c:3304-3308` — `rkcheck()` — `check_database_name` 실패 분기에 진단 메시지 없음 (`db_restart` 실패 분기와 비대칭)

**① rkcheck() — src/executables/util_cs.c:3304~3313**
```c
/* src/executables/util_cs.c:3304 — rkcheck() */
  if (check_database_name (database_name))
    {
      err = ER_FAILED;
      goto end2;                 /* ← 여기: 메시지 없이 조용히 종료 */
    }

  if (db_restart (arg->command_name, TRUE, database_name))
    {
      err = ER_FAILED;
      PRINT_AND_LOG_ERR_MSG ("%s: %s\n", arg->command_name, db_error_string (3));   /* ← 여긴 메시지 있음 */
      goto end2;
    }
```

- **재현 명세**
  - **진입 최소 상태**: 단일 노드 재현 가능 — `cub_admin rkcheck` 유틸 프로세스만으로 발현.
  - **스키마·데이터 조건**: 없음(입력 검증 단계).
  - **실행 순서**: HA 왕복 불필요. 유틸 실행 → `check_database_name`이 거부하는 형식의 DB명 → 종료 코드만 실패, 화면·로그에 설명 없음.
  - **최소 재현 입력**: `cubrid rkcheck '@@bad'` 같이 `check_database_name`이 거부하는 형식의 이름 전달.
  - **대조 조건**: 바로 다음 `db_restart` 실패 경로는 `PRINT_AND_LOG_ERR_MSG`로 원인을 알려 준다 — 두 경로의 비대칭이 원인.
- **제안**: 이 분기에도 `PRINT_AND_LOG_ERR_MSG`로 "잘못된 데이터베이스 이름" 메시지를 추가.
- **PR 맥락**: #6934가 동일 지적을 MINOR로 남겼던 것과 같은 패턴.
- **신뢰도**: 높음 — 분기 코드 확정.

---

#### K-43. rkcheck가 db_login 반환값 미검사
- **심각도**: 보통
- **로직**: `rkcheck()`는 `db_login("DBA", NULL)`의 반환값을 버리고 곧장 `db_restart()`로 진행한다. 같은 파일의 `applyinfo()`는 `db_login()` 실패 시 즉시 조기 종료하는 것과 대비된다. `db_restart()`가 내부적으로 인증 실패를 다시 검출하긴 하지만, 실패 지점이 한 단계 뒤로 밀려 에러 메시지가 "로그인 실패"가 아니라 "재기동 실패"로 뭉뚱그려진다.
- **관련 코드**
  1. `src/executables/util_cs.c:3295` — `rkcheck()` — `db_login("DBA", NULL)` 반환값을 검사하지 않고 진행

**① rkcheck() — src/executables/util_cs.c:3293~3300**
```c
/* src/executables/util_cs.c:3293 — rkcheck() */
  AU_DISABLE_PASSWORDS ();
  db_set_client_type (DB_CLIENT_TYPE_ADMIN_UTILITY);
  db_login ("DBA", NULL);        /* ← 여기: 반환값 미검사 */
  ...
  if (db_restart (arg->command_name, TRUE, database_name))   /* 여기서야 실패가 드러남 */
```

- **재현 명세**
  - **진입 최소 상태**: 단일 노드 — `cub_admin rkcheck` 유틸.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: DBA 계정 정책이 바뀌어(예: 비밀번호 필수화) `db_login("DBA", NULL)`이 실패하는 환경에서 rkcheck 실행 → 에러 메시지가 인증 문제임을 특정하지 못한다.
  - **대조 조건**: `applyinfo()`처럼 반환값을 검사하면 실패 지점과 메시지가 명확해진다.
- **제안**: `applyinfo()`와 동일한 패턴으로 `db_login()` 반환값을 확인해 조기 종료.
- **신뢰도**: 높음 — 미검사 확정. 실무 발현은 `db_restart`가 재검출해 부분 완화.

---

#### K2-2. heap_get_class_repl_on()이 REPLICATION=OFF + RK 후보 다중 시 인덱스 루프에서 반복 호출
- **심각도**: 보통
- **로직**: `locator_add_or_remove_index_internal()`는 한 행을 삽입/삭제할 때 그 클래스의 **인덱스를 개수만큼(`num_btids`) 루프**로 돌며 각 인덱스에 키를 넣고 뺀다(서버 측). 루프 안에는 복제 로그를 남기는 블록이 있는데, `replicated`(한 번 로그를 남기면 true) 플래그로 "행당 한 번만" 기록하도록 되어 있다. 값싼 검사(`!replicated && or_is_replication_candidate_key(index)`)가 앞에, 무거운 카탈로그 조회가 뒤에 오도록 배치돼 있지만, `replicated`는 **`repl_on == true`일 때만** 세워진다. 따라서 REPLICATION=OFF 클래스는 `replicated`가 영영 false로 남고, `!replicated && or_is_replication_candidate_key(index)`가 RK 후보(PK 또는 NOT NULL UNIQUE)마다 참이 되어, 같은 class_oid에 대해 `heap_get_class_repl_on()`(카탈로그 페이지 fetch)이 **후보키 개수만큼 반복 호출**된다. 루프 위 8039행 TODO가 "RK 확정 시에만 로그를 남기고 모든 RK 후보를 검사하며 replicated 플래그를 다루는 방식을 재검토 필요(EPIC CBRD-26096)"라며 이 지점을 인정한다.
- **관련 코드**
  1. `src/transaction/locator_sr.c:8041-8057` — `locator_add_or_remove_index_internal()` — 인덱스 루프 내부 복제 블록, OFF 클래스는 후보키마다 `heap_get_class_repl_on` 호출
  2. `src/storage/heap_file.c:11085-11114` — `heap_get_class_repl_on()` — 매 호출이 클래스 레코드 페이지를 fetch/래치

**① locator_add_or_remove_index_internal() — src/transaction/locator_sr.c:8041~8057**
```c
/* src/transaction/locator_sr.c:8041 — locator_add_or_remove_index_internal() (인덱스 루프 내부) */
if (error_code == NO_ERROR && need_replication && !replicated   /* ← OFF 클래스는 replicated가 계속 false */
    && or_is_replication_candidate_key (index)                  /* ← RK 후보(PK/NOT NULL UNIQUE)마다 true */
    && !LOG_CHECK_LOG_APPLIER (thread_p) && log_does_allow_replication () == true)
  {
    bool repl_on = false;
    error_code = heap_get_class_repl_on (thread_p, class_oid, &repl_on);  /* ← 여기: 카탈로그 페이지 fetch, 후보키 수만큼 반복 */
    if (error_code == NO_ERROR && repl_on)
      {
        error_code = repl_log_insert (...);
        replicated = true;                                      /* ← ON일 때만 세워짐 */
      }
  }
```

**② heap_get_class_repl_on() — src/storage/heap_file.c:11085~11114**
```c
/* src/storage/heap_file.c:11085 — heap_get_class_repl_on() */
int heap_get_class_repl_on (THREAD_ENTRY * thread_p, const OID * class_oid, bool * repl_on)
{
  ...
  if (heap_get_class_record (thread_p, class_oid, &recdes, &scan_cache, PEEK) != S_SUCCESS)  /* ← 여기: 페이지 fetch/래치 */
    { ... return error_code; }
  *repl_on = or_class_is_replication_on (&recdes);
  ...
}
```

- **시나리오**: 정합성 버그는 아니다. 대량 INSERT/DELETE 워크로드(100만 행 규모)에서 REPLICATION=OFF + RK 후보 2개 이상인 클래스가 대상이면, 행마다 카탈로그 페이지를 후보키 수만큼 fetch해 성능 저하 + 카탈로그 페이지 래치 경합이 생긴다.
- **재현 명세**
  - **진입 최소 상태**: 서버 측(`cub_server`, `SERVER_MODE`) DML 실행 경로. 복제 로그 블록의 가드는 `need_replication && !LOG_CHECK_LOG_APPLIER(thread_p) && log_does_allow_replication()==true`이므로, HA 마스터로서 복제가 켜진 서버(applier가 아닌 일반 트랜잭션 경로)에서 진입. 결함은 정합성이 아닌 성능이라 크래시/오답은 없다 — 단일 노드에서 프로파일링으로 관측 가능.
  - **스키마·데이터 조건**: 대상 클래스가 **REPLICATION=OFF**(→ `repl_on=false` → `replicated`가 계속 false)이고, RK 후보 인덱스가 **2개 이상**(예: PK 1개 + NOT NULL UNIQUE 1개, 또는 NOT NULL UNIQUE 2개). `or_is_replication_candidate_key`가 이 후보마다 true를 반환.
  - **실행 순서**: master의 한 행 INSERT/DELETE → `locator_add_or_remove_index_internal`이 `num_btids`만큼 루프 → 각 RK 후보 인덱스 반복에서 `heap_get_class_repl_on` 호출 → 매번 `heap_get_class_record`가 클래스 레코드 페이지를 PEEK fetch. HA 왕복 불필요, 단일 노드에서 재현 가능(성능 결함).
  - **최소 재현 입력**:
    ```sql
    CREATE TABLE t (a INT NOT NULL, b INT NOT NULL, c INT,
                    PRIMARY KEY(a), CONSTRAINT uk UNIQUE(b)) REPLICATION=OFF;  -- RK 후보 2개(PK, NOT NULL UNIQUE)
    -- 대량 적재로 행당 후보키 수(2)만큼 heap_get_class_repl_on 반복 관측
    INSERT INTO t SELECT ... ;   -- 100만 행 규모
    ```
  - **대조 조건**: RK 후보 인덱스가 **1개뿐**이면(PK만) 행당 1회 호출이라 반복이 없다. 또는 REPLICATION=ON이면 첫 후보에서 `replicated=true`가 세워져 이후 후보에서 `!replicated`가 거짓이 되어 반복이 끊긴다(OFF에서만 발생).
- **제안**: OFF 클래스는 첫 조회로 repl_on=false를 확인한 뒤 루프에서 조기 이탈(class 단위 1회 평가).
- **PR 맥락**: #6908 MAJOR 이월 건. K-12(모든 인덱스마다 무조건 카탈로그 조회)의 좁은 잔여.
- **신뢰도**: 높음 — "OFF → replicated 영영 false → 후보키마다 카탈로그 fetch" 분기를 코드로 완전히 확정. 정량적 성능 영향(래치 경합 규모)만 실측 대상.

---

#### K-41. rkcheck가 RK/FK 검사마다 전체 클래스 목록 중복 순회
- **심각도**: 보통
- **로직**: `rkcheck()`는 `check_repl_constraint_violations()`를 RK용(3333)·FK용(3349)으로 두 번 호출하고, 그 함수는 매번 `classes` 전체 목록을 순회하며 클래스마다 `db_is_vclass`·`db_is_system_class`·`sm_is_replication_class`를 다시 조회한다. 즉 전체 클래스 스캔과 카탈로그 조회가 2배로 든다. rkcheck는 `hb start`가 동기적으로 기다리는 경로라 기동 지연으로 이어진다.
- **관련 코드**
  1. `src/executables/util_cs.c:2928-2951` — `check_repl_constraint_violations()` — 한 번 호출당 전체 클래스 목록 순회
  2. `src/executables/util_cs.c:3333, 3349` — `rkcheck()` — 같은 `classes`를 RK·FK로 두 번 순회

**① check_repl_constraint_violations() — src/executables/util_cs.c:2928~2951**
```c
/* src/executables/util_cs.c:2935 — check_repl_constraint_violations() (한 번 호출당 전체 목록 순회) */
  for (c = classes; c != NULL; c = c->next)
    {
      is_vclass = db_is_vclass (c->op);
      ...
      if (db_is_system_class (c->op) || is_vclass > 0 || !sm_is_replication_class (c->op))
        {
          continue;
        }
      *violation_count += check_func (c->op, fp);
    }
```

**② rkcheck() — src/executables/util_cs.c:3333~3349**
```c
/* src/executables/util_cs.c:3333 — rkcheck() (같은 classes를 두 번 순회) */
      err = check_repl_constraint_violations (classes, fp, check_rk_constraint, &rk_violation_count);  /* 1회차 */
      ...
      err = check_repl_constraint_violations (classes, fp, check_fk_constraint, &fk_violation_count);  /* 2회차 ← 여기 */
```

- **재현 명세**
  - **진입 최소 상태**: 단일 노드 — `cub_admin rkcheck` 유틸. 정합성 결함 아님(성능).
  - **스키마·데이터 조건**: 클래스가 많은 DB일수록 비용 차이가 커진다.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: 트리거 불가(오답이 아니라 중복 비용). 옵션 없이 `cubrid rkcheck db`(기본 RK+FK 모두)면 두 순회가 모두 실행된다.
  - **대조 조건**: `-r` 또는 `-f` 한쪽만 주면 순회가 1회로 줄어(3330/3346 플래그 게이트), 중복이 사라진다.
- **제안**: 목록을 1회 순회하며 RK/FK를 동시에 검사하도록 통합.
- **신뢰도**: 높음 — 두 호출·순회 구조 확정. 성능 영향 정량치는 미측정.

---

#### K3-4. pt_print_table_option이 REPLICATION 옵션 값을 ON/OFF가 아닌 원시 정수(1/0)로 재출력해 재파싱 왕복이 깨지고 중복옵션 에러 메시지에 내부 인코딩이 노출됨
- **심각도**: 보통
- **로직**: `CREATE TABLE t (...) REPLICATION=ON` 같은 문장에서 문법 `class_replication_spec`은 REPLICATION 값을 `PT_VALUE` 노드에 `PT_TYPE_INTEGER`로 저장한다 — `opt_replication_option`이 ON을 `1`, OFF를 `0`, 생략을 `1`로 매핑해 `data_value.i`에 넣는다. 이 파스트리를 다시 텍스트로 찍는 `pt_print_table_option`은 옵션 종류별로 값 출력 방식을 나눈다. CHARSET/COLLATION은 따옴표 없는 문자열로, ENCRYPT는 정수를 `tde_get_algorithm_name`으로 알고리즘 이름으로 변환해 출력한다. 그런데 REPLICATION은 라벨 `"replication = "`만 붙일 뿐 정수→키워드(ON/OFF) 변환 분기가 없어, 공통 `else`의 `pt_print_bytes_l`로 폴백해 정수 `1`/`0`을 그대로 찍는다. 결과는 `replication = 1` / `replication = 0`.
- **관련 코드**
  1. `src/parser/parse_tree_cl.c:8041-8073` — `pt_print_table_option()` — REPLICATION 전용 값 변환 분기 부재, `else`(`pt_print_bytes_l`)로 폴백해 정수 그대로 출력
  2. `src/parser/csql_grammar.y:19891-19901` — `class_replication_spec` — REPLICATION 값을 `PT_TYPE_INTEGER`(ON=1/OFF=0)로 저장
  3. `src/parser/csql_grammar.y:19987-19997` — `opt_replication_option` — 재파싱 시 `ON_`/`OFF_`/생략만 허용(정수 불가)

**① pt_print_table_option() — src/parser/parse_tree_cl.c:8041~8073**
```c
/* src/parser/parse_tree_cl.c:8041 — pt_print_table_option() */
    case PT_TABLE_OPTION_ENCRYPT:
      q = pt_append_nulstring (parser, q, "encrypt = ");
      break;
    case PT_TABLE_OPTION_REPLICATION:
      q = pt_append_nulstring (parser, q, "replication = ");    /* :8042 ← 라벨만, 값 변환 분기 없음 */
      break;
    default:
      break;
    }
  if (p->info.table_option.val != NULL)
    {
      if (p->info.table_option.option == PT_TABLE_OPTION_CHARSET
          || p->info.table_option.option == PT_TABLE_OPTION_COLLATION)
        { ... }
      else if (p->info.table_option.option == PT_TABLE_OPTION_ENCRYPT)   /* :8060 ← ENCRYPT는 정수→이름 변환 */
        {
          ...
          tde_algo_name = tde_get_algorithm_name ((TDE_ALGORITHM) p->info.table_option.val->info.value.data_value.i);
          ...
        }
      else
        {
          r1 = pt_print_bytes_l (parser, p->info.table_option.val);   /* :8073 ← 여기: REPLICATION은 정수 그대로 출력 */
        }
      q = pt_append_varchar (parser, q, r1);
    }
```

**② class_replication_spec (문법) — src/parser/csql_grammar.y:19891~19901**
```c
/* src/parser/csql_grammar.y:19891 — class_replication_spec (값을 PT_TYPE_INTEGER로 저장) */
class_replication_spec
  : REPLICATION opt_equalsign opt_replication_option
        {{
            PT_NODE *node = parser_new_node (this_parser, PT_VALUE);
            if (node)
              {
                node->type_enum = PT_TYPE_INTEGER;
                node->info.value.data_value.i = $3;              /* ← ON=1/OFF=0 정수 */
                ...
              }
        }}
```

**③ opt_replication_option (문법) — src/parser/csql_grammar.y:19987~19997**
```c
/* src/parser/csql_grammar.y:19987 — opt_replication_option (ON_/OFF_/생략만 허용) */
opt_replication_option
  : /* empty */   { $$ = 1; }   /* default ON  */
  | ON_           { $$ = 1; }
  | OFF_          { $$ = 0; }
  ;
```

- **시나리오**
  - **Round-trip 깨짐**: `pt_print_table_option`이 만든 `replication = 1`(또는 `= 0`) 텍스트를 다시 파싱하면, 문법 `opt_replication_option`은 `ON_`/`OFF_`/생략만 허용하므로 정수 `1`/`0`에서 문법 에러가 난다. 즉 실행 DDL과 재구성 DDL이 왕복(파스→출력→재파스)에서 어긋난다.
  - **에러 메시지 인코딩 노출**: `CREATE TABLE t (...) REPLICATION=ON, REPLICATION=OFF`처럼 옵션을 중복 지정하면 `semantic_check.c`의 중복 옵션 검사(`:8503-8514`)가 `MSGCAT_SEMANTIC_DUPLICATE_TABLE_OPTION` 에러를 내는데, 이 메시지가 `parser_print_tree(parser, tbl_opt)`를 거쳐 `pt_print_table_option`으로 옵션을 렌더링한다. 그 결과 사용자가 입력한 적 없는 정수 인코딩(`replication = 1`)이 에러 메시지에 노출돼 재작성 시 혼란을 준다.
- **재현 명세**
  1. **진입 최소 상태**: 파스트리에 `PT_TABLE_OPTION_REPLICATION` 노드(`val`이 `PT_TYPE_INTEGER`)가 존재하고, `pt_print_table_option`이 호출되는 경로(SHOW CREATE 재출력, round-trip, 또는 중복 옵션 세만틱 에러 렌더). 결함 가드는 값 출력 분기의 `else { r1 = pt_print_bytes_l(...); }`(`:8071-8073`).
  2. **스키마/데이터 조건**: 임의 컬럼 1개 이상 테이블. 데이터 불필요.
  3. **실행 순서**: 단일 노드 재현(파서/출력 경로, 복제 무관).
  4. **최소 재현 입력**:
     - Round-trip: `CREATE TABLE t (a INT) REPLICATION=ON;` 후 파스트리 재출력(`parser_print_tree`)을 재파싱하면 `replication = 1`에서 문법 에러.
     - 에러 인코딩 노출: `CREATE TABLE t (a INT) REPLICATION=ON, REPLICATION=OFF;` → 중복 옵션 에러 메시지에 `replication = 1` 노출.
  5. **대조 조건**: ENCRYPT 옵션은 정수→이름 변환 분기가 있어 `encrypt = AES_256`처럼 사람이 읽는 값으로 정상 출력됨 — 동일 위치에 REPLICATION 분기를 추가하면 `replication = ON/OFF`로 대칭 복원.
- **제안**: `pt_print_table_option`에 `PT_TABLE_OPTION_REPLICATION` 전용 분기를 추가해(ENCRYPT의 정수→이름 변환 패턴을 따라) `data_value.i`가 1이면 `ON`, 0이면 `OFF` 키워드를 출력하도록 한다. 그러면 round-trip이 복원되고 중복 옵션 에러 메시지도 사용자 표기(`replication = ON`)로 나온다. (object_printer/unload의 직접 문자열 출력 K-50/K-27과는 파일·경로가 다른 별개 경로.)
- **신뢰도**: 높음 — 라벨/값 출력 분기, 정수 저장, 문법 허용집합을 모두 소스에서 확인했고 재현이 순수 파서 경로라 결정적. 다만 DDL SBR은 원문 텍스트를 쓰므로 실제 복제는 안 깨지고 영향이 진단/재출력 경로에 국한돼 severity 보통이 타당.

---

#### K3-5. pt_print_alter_one_clause switch에 PT_CHANGE_REPLICATION case 부재로 ALTER TABLE ... REPLICATION 절이 파스트리 재출력에서 통째로 소실됨
- **심각도**: 보통
- **로직**: `ALTER TABLE t REPLICATION=OFF`는 파싱 단계에서 `alter.code = PT_CHANGE_REPLICATION`으로 저장된다(`csql_grammar.y:5866-5869`). 이 파스트리를 다시 텍스트 DDL로 찍는 함수가 `pt_print_alter_one_clause`인데, 이 함수는 `switch (p->info.alter.code)`로 코드별 출력 분기를 한다(`:5784`). switch 맨 앞은 `default: break;`(`:5786-5787`)이고, 이어서 `PT_CHANGE_OWNER`, `PT_CHANGE_TABLE_COMMENT`, `PT_CHANGE_COLLATION`, `PT_ADD_QUERY`/`PT_DROP_QUERY`/`PT_MODIFY_QUERY`/`PT_RESET_QUERY`, `PT_ADD_ATTR_MTHD`/`PT_DROP_ATTR_MTHD` 등의 case가 있다. 그런데 `PT_CHANGE_REPLICATION` case가 없어(파일 전체 grep 부재), REPLICATION 변경 절은 `default: break`로 빠져 출력에서 아무것도 남기지 않는다. `PT_CHANGE_OWNER`/`PT_CHANGE_TABLE_COMMENT`/`PT_CHANGE_COLLATION`은 case가 있어 정상 출력되는 것과 비대칭이다.
- **관련 코드**
  1. `src/parser/parse_tree_cl.c:5775-5920` — `pt_print_alter_one_clause()` — `p->info.alter.code` switch에 `PT_CHANGE_REPLICATION` case 부재, REPLICATION 절이 `default:break`로 소실
  2. `src/parser/csql_grammar.y:5866-5869` — `class_replication_spec` — ALTER 절에 `alter.code = PT_CHANGE_REPLICATION`을 세팅(재출력 대상 코드)

**① pt_print_alter_one_clause() — src/parser/parse_tree_cl.c:5784~5798**
```c
/* src/parser/parse_tree_cl.c:5784 — pt_print_alter_one_clause() */
  switch (p->info.alter.code)
    {
    default:
      break;                                                    /* :5786 ← 여기: PT_CHANGE_REPLICATION이 이 default로 빠짐 */
    case PT_CHANGE_OWNER:                                       /* :5788 (존재) */
      r1 = pt_print_bytes_l (parser, p->info.alter.alter_clause.user.user_name);
      q = pt_append_nulstring (parser, q, " owner to ");
      q = pt_append_varchar (parser, q, r1);
      break;
    case PT_CHANGE_TABLE_COMMENT:                                /* :5793 (존재) */
      ...
    case PT_CHANGE_COLLATION:                                    /* :5798 (존재) */
      ...
    /* ← case PT_CHANGE_REPLICATION: 없음 → 절 소실 */
    }
```
확인된 switch case 목록(`:5775-5925` 범위): `PT_CHANGE_OWNER`, `PT_CHANGE_TABLE_COMMENT`, `PT_CHANGE_COLLATION`, `PT_ADD_QUERY`, `PT_DROP_QUERY`, `PT_MODIFY_QUERY`, `PT_RESET_QUERY`, `PT_ADD_ATTR_MTHD`, `PT_DROP_ATTR_MTHD` — `PT_CHANGE_REPLICATION` 없음.

- **시나리오**: `ALTER TABLE t REPLICATION=OFF`의 파스트리를 `pt_print_alter_one_clause`로 재출력하면 REPLICATION 절이 통째로 사라지고, 본문이 빈 no-op ALTER처럼 재구성된다. `PT_CHANGE_OWNER`/`PT_CHANGE_TABLE_COMMENT`/`PT_CHANGE_COLLATION`은 정상 출력되는데 REPLICATION만 누락돼 비대칭이다. `do_alter` 디스패치(`execute_schema.c:2033`)와 CREATE 옵션 출력에는 REPLICATION 처리가 있어, ALTER 전용 절 역출력에만 구멍이 있다. DDL SBR은 `sql_user_text`(원문)를 쓰므로 복제 자체는 안 깨지지만, `parser_print_tree`를 소비하는 다른 경로(회귀 round-trip 테스트, 진단 덤프, DDL 정규화·재조립)에서는 실행 DDL과 재구성 DDL이 어긋나 조용한 불일치가 생긴다.
- **재현 명세**
  1. **진입 최소 상태**: `alter.code == PT_CHANGE_REPLICATION`인 파스트리에 대해 `pt_print_alter_one_clause`(→`parser_print_tree`)가 호출되는 경로. 결함 가드는 switch 맨 앞 `default: break;`(`:5786-5787`).
  2. **스키마/데이터 조건**: 실테이블 1개(비HA 환경, `HA_DISABLED()`에서 실행 성공). 데이터 불필요.
  3. **실행 순서**: 단일 노드 재현(파서/출력 경로).
  4. **최소 재현 입력**:
     ```sql
     CREATE TABLE t (a INT);
     ALTER TABLE t REPLICATION=OFF;
     ```
     이후 이 ALTER 파스트리를 `parser_print_tree`로 재출력하면 REPLICATION 절이 빠진 빈 ALTER가 나옴(회귀 round-trip/진단 덤프 경로에서 확인).
  5. **대조 조건**: 같은 함수에서 `ALTER TABLE t COMMENT='x'`(PT_CHANGE_TABLE_COMMENT)나 `ALTER TABLE t OWNER TO u`(PT_CHANGE_OWNER)는 case가 있어 절이 정상 재출력됨.
- **제안**: `pt_print_alter_one_clause` switch에 `PT_CHANGE_REPLICATION` case를 추가해 `alter_clause.replication.tbl_replication`을 렌더링(`" replication = ON/OFF"`)하도록 한다. K3-4와 동일하게 정수값을 ON/OFF 키워드로 변환해 출력해야 round-trip이 온전하다.
- **신뢰도**: 높음 — switch case 부재를 grep으로 열거 확인했고 문법이 code를 세팅함도 확인. 다만 실제 복제는 원문 텍스트를 써서 안 깨지고 영향이 재출력 소비처에 국한돼 severity 보통이 타당.

---

#### K-48. SBR 판정용 `is_replication_class`가 이미 리졸브된 참조 대신 이름으로 재조회
- **심각도**: 보통
- **핵심 문제**: `flat_entity_list`의 `db_object`를 안 쓰고, 문장마다 불필요한 카탈로그 조회를 한다.
- **로직**: SBR(문장 기반 복제) 대상이 복제 테이블인지 판정하는 `spec_has_replication_class()`는 먼저 spec의 이름 문자열을 뽑아 `is_replication_class(name)`을 부른다. 이 함수는 이름으로 `db_find_class()`를 **다시** 실행해 객체를 얻는다. 그런데 같은 spec의 `flat_entity_list`에는 이미 이름 해석(name resolution)이 끝난 `db_object`가 들어 있고, 바로 아래 루프는 그 객체를 직접 쓴다. 즉 첫 경로만 굳이 이름→객체 재조회를 하는 비효율이자, `db_find_class` 실패를 `assert(false)`로 삼키는(K-15) 취약점까지 끌어들인다.
- **관련 코드**
  1. `src/query/execute_statement.c:3200-3218` — `is_replication_class()` — 이름으로 `db_find_class` 재조회 + 실패를 `assert(false)`로 삼킴
  2. `src/query/execute_statement.c:3282-3292` — `spec_has_replication_class()` — 이름 경유 판정과 리졸브된 `db_object` 직접 판정이 공존

**① is_replication_class() — src/query/execute_statement.c:3200~3218**
```c
/* src/query/execute_statement.c:3210 — is_replication_class() (이름으로 재조회 + 실패 삼킴) */
class_obj = db_find_class (classname);        /* ← 여기: 이미 리졸브된 객체가 있는데 재조회 */
if (class_obj == NULL)
  {
    assert (false);
    return false;
  }
return sm_is_replication_class (class_obj);
```

**② spec_has_replication_class() — src/query/execute_statement.c:3282~3292**
```c
/* src/query/execute_statement.c:3282 — spec_has_replication_class() (리졸브된 db_object를 그대로 사용) */
if (is_replication_class (get_spec_classname (spec)))   /* ← 이름 경유(재조회 유발) */
  return true;
for (cls = spec->info.spec.flat_entity_list; cls != NULL; cls = cls->next)
  if (cls->info.name.db_object != NULL && sm_is_replication_class (cls->info.name.db_object)) /* ← 객체 직접 사용 */
    return true;
```

- **시나리오**: SBR 문장을 실행할 때마다 대상 테이블 수만큼 `db_find_class` 카탈로그 조회가 중복 발생한다. 정합성 버그는 아니나 반복 SBR 워크로드에서 불필요 비용 + K-15 삼킴 노출.
- **재현 명세**
  - **진입 최소 상태**: 단일 노드에서 정적 확인 가능. 실제 호출은 HA 모드 + SBR 경로 게이트 `!HA_DISABLED() && is_stmt_based_repl_type(statement) && is_data_repl_log_enabled(...)`(:3405)를 통과해야 한다 → HA 활성 + `USE_SBR` 힌트.
  - **스키마·데이터 조건**: `entity_name`을 가진 일반(비-파생) 복제 대상 테이블 1개 이상.
  - **실행 순서**: 단일 노드(클라이언트 계층 판정). SBR 힌트 DML 파싱 → `is_data_repl_log_enabled` → `spec_has_replication_class` → `is_replication_class(name)` → `db_find_class` 재조회.
  - **최소 재현 입력**: `UPDATE /*+ USE_SBR */ t SET c=1 WHERE ...;` (HA 모드, t는 복제 테이블). 매 실행마다 이름 재조회.
  - **대조 조건**: `is_replication_class(name)` 경로 대신 `flat_entity_list`의 `db_object`를 먼저 검사하면 재조회가 없어진다.
- **제안**: 리졸브된 객체 재사용.
- **신뢰도**: 높음 — 이름 재조회 경로와 객체 직접 사용 경로가 같은 함수에 공존함을 코드에서 확인.

---

#### K-49. 신규 FK/제약 함수들의 bool/int 반환타입 혼용
- **심각도**: 보통
- **핵심 문제**: `check_ha_repl*` 3함수의 반환 규약(bool / 위반 개수 / 에러 코드)이 제각각이다.
- **로직**: FK 복제 제약을 다루는 세 함수가 의미가 다른 반환값을 쓴다 — `check_ha_repl_fk_ref_all_replicated`는 "모두 복제되면 true"(bool), `log_ha_repl_fk_ref_all_replicated`는 "위반 개수"(int, 0=정상), `check_ha_repl_constraint`는 "에러 코드"(int, `NO_ERROR`=정상). 같은 접두사(`check_ha_repl`)를 쓰면서 성공/실패의 부호와 의미가 반대라, 호출자가 반환값을 헷갈려 `if (check_...())`를 잘못 분기하기 쉽다.
- **관련 코드**
  1. `src/query/execute_schema.c:9782-9803` — `check_ha_repl_fk_ref_all_replicated()` — 반환 규약 bool(true=정상)
  2. `src/query/execute_schema.c:9817-9845` — `log_ha_repl_fk_ref_all_replicated()` — 반환 규약 int(0=정상, 양수=위반 개수)
  3. `src/query/execute_schema.c:9860-` — `check_ha_repl_constraint()` — 반환 규약 int(NO_ERROR=정상, 음수=에러)

**① check_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9782~9803**
```c
/* src/query/execute_schema.c:9782 — check_ha_repl_fk_ref_all_replicated() (true=정상) */
bool check_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj)
{ ... return true; }              /* 모두 복제 시 true */
```

**② log_ha_repl_fk_ref_all_replicated() — src/query/execute_schema.c:9817~9845**
```c
/* src/query/execute_schema.c:9817 — log_ha_repl_fk_ref_all_replicated() (0=정상, 양수=위반 개수) */
int log_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj, FILE * fp)
{ ... return ret; }               /* ← 같은 뜻인데 부호 규약이 정반대 */
```

**③ check_ha_repl_constraint() — src/query/execute_schema.c:9860~**
```c
/* src/query/execute_schema.c:9860 — check_ha_repl_constraint() (NO_ERROR(0)=정상, 음수=에러) */
int check_ha_repl_constraint (DB_OBJECT * class_obj)
{ if (HA_DISABLED ()) return NO_ERROR; ... }
```

- **시나리오**: 향후 유지보수자가 세 함수를 같은 규약으로 오인해 조건 분기를 뒤집으면, RK/FK 검증이 통째로 무력화되거나 정상 스키마가 거부된다.
- **재현 명세**
  - **진입 최소 상태**: 정적 결함(API 설계). 트리거 불가 — 컴파일·실행되지만 사람이 오용할 때만 발현한다.
  - **스키마·데이터 조건**: 무관.
  - **실행 순서**: 해당 없음(정적).
  - **최소 재현 입력**: 트리거 불가(반환 규약 불일치는 정적 지적).
  - **대조 조건**: 세 함수가 모두 "0=성공, 음수=에러" 같은 단일 규약이면 오용 위험이 사라진다.
- **제안**: 반환 규약 통일.
- **PR 맥락**: #6908에서 지적된 안티패턴과 동일 유형.
- **신뢰도**: 높음 — 세 함수의 반환 타입·의미가 서로 다름을 코드에서 직접 확인.

---

#### K-39. .err/.list 로그 파일명 명명 규칙 불일치
- **심각도**: 보통
- **로직**: `.err` 파일명은 `@localhost` 정규화 **이전**의 원본 `database_name`으로 만들어지고(3290), `.list` 파일명은 정규화 **이후**의 `database_name`(= `db@localhost`)으로 만들어진다(3300에서 덮어쓴 뒤 3320에서 사용). 결과적으로 같은 실행이 남기는 두 진단 파일의 접두 이름이 서로 달라진다.
- **관련 코드**
  1. `src/executables/util_cs.c:3290` — `rkcheck()` — `.err` 파일명을 정규화 이전 원본 이름으로 생성
  2. `src/executables/util_cs.c:3320` — `rkcheck()` — `.list` 파일명을 정규화 이후 이름(`db@localhost`)으로 생성

**① rkcheck() (.err/.list 파일명) — src/executables/util_cs.c:3290~3320**
```c
/* src/executables/util_cs.c:3290 — rkcheck() (정규화 전 원본 이름 사용) */
  snprintf (er_msg_file, PATH_MAX, "%s_%s.err", database_name, arg->command_name);   /* db_rkcheck.err */
  ...
  if (strchr (database_name, '@') == NULL)
    {
      snprintf (tmp_database_name, sizeof (tmp_database_name), "%s@localhost", database_name);
      database_name = tmp_database_name;      /* ← 여기서 이름이 db@localhost 로 바뀜 */
    }
  ...
/* src/executables/util_cs.c:3320 — 정규화 후 이름 사용 */
  fp = open_violation_list_file (database_name, arg->command_name, violation_list_file, PATH_MAX);
  /* → db@localhost_rkcheck_YYYYMMDD_HHMM.list */
```

- **재현 명세**
  - **진입 최소 상태**: 단일 노드 재현 가능 — `cub_admin rkcheck` 유틸.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: `@` 없는 이름으로 `cubrid rkcheck testdb` 실행 → `testdb_rkcheck.err`와 `testdb@localhost_rkcheck_....list`가 나란히 생성된다.
  - **대조 조건**: 이미 `@host`가 포함된 이름을 넘기면 3297 조건이 거짓이라 정규화가 생략되어 두 이름이 일치한다.
- **제안**: 정규화된 이름으로 `.err`·`.list`를 통일.
- **신뢰도**: 높음 — 정규화 시점(3300) 전후 사용 위치를 코드로 확정.

---

#### K-37. do_create_partition의 REPLICATION 상속 코드 복붙(2분기)
- **심각도**: 보통
- **로직**: 파티션 자식 테이블을 만드는 두 시점(해시/레인지 등 분기)에서, 부모의 REPLICATION 옵션을 자식에 상속시키는 동일한 블록이 글자 그대로 중복돼 있다. 한쪽만 고치고 다른 쪽을 놓치면 파티션 종류에 따라 복제 설정 상속이 어긋난다.
- **관련 코드**
  1. `src/query/execute_schema.c:4955-4962` — `do_create_partition()` — REPLICATION 상속 블록 (분기 A)
  2. `src/query/execute_schema.c:5187-5194` — `do_create_partition()` — 동일 블록 복붙 (분기 B)

**① do_create_partition() 분기 A — src/query/execute_schema.c:4955~4962**
```c
/* src/query/execute_schema.c:4955 — do_create_partition() (분기 A) */
  if (!replication_opt)
    {
      error = sm_set_class_flag (newpci->obj, SM_CLASSFLAG_DATA_REPLICATION_OFF, TRUE);
      if (error != NO_ERROR)
        {
          goto end_create;
        }
    }
```

**② do_create_partition() 분기 B — src/query/execute_schema.c:5187~5194**
```c
/* src/query/execute_schema.c:5187 — do_create_partition() (분기 B, 위와 완전히 동일한 블록) */
  if (!replication_opt)
    {
      error = sm_set_class_flag (newpci->obj, SM_CLASSFLAG_DATA_REPLICATION_OFF, TRUE);   /* ← 여기: 복붙 */
      if (error != NO_ERROR)
        {
          goto end_create;
        }
    }
```

- **재현 명세**
  - **진입 최소 상태**: 정적(유지보수) 결함 — 현재 동작은 두 분기가 같으므로 정상. 단일 노드.
  - **스키마·데이터 조건**: 없음(구조 문제).
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: 트리거 불가(동작 결함 아님). 향후 한쪽 블록만 수정하는 패치가 들어오면 파티션 종류별 상속 불일치로 발현.
  - **대조 조건**: 두 블록을 공통 헬퍼로 추출하면 한쪽만 고치는 위험이 사라진다.
- **제안**: REPLICATION 상속 블록을 헬퍼 함수로 추출.
- **PR 맥락**: 파티션 자식 속성 상속 #6552 계열.
- **신뢰도**: 높음 — 두 블록의 완전 동일성 확인.

---

#### K-35. 주석·헤더가 실제 함수명·파라미터와 불일치
- **심각도**: 보통
- **로직**: 두 곳의 함수 주석이 실제 시그니처와 어긋난다. (1) `class_object.c`의 헤더 주석은 함수 이름을 `classobj_copy_pk_unique_constraints()`(542)라 적었으나 실제 정의는 `classobj_copy_pk_and_uk_notnull_constraints`(561)다. (2) `execute_schema.c`의 `check_ha_repl_constraint()` 주석은 `repl_opt(in) — Replication option (true = ON, false = OFF)`(9851) 파라미터를 설명하지만, 실제 시그니처는 `check_ha_repl_constraint (DB_OBJECT * class_obj)`(9861)로 `repl_opt` 인자가 없다.
- **관련 코드**
  1. `src/object/class_object.c:541-561` — `classobj_copy_pk_and_uk_notnull_constraints()` — 주석의 함수명(옛 이름)과 실제 정의명 불일치
  2. `src/query/execute_schema.c:9847-9866` — `check_ha_repl_constraint()` — 주석이 존재하지 않는 `repl_opt` 인자를 설명

**① classobj_copy_pk_and_uk_notnull_constraints() — src/object/class_object.c:541~561**
```c
/* src/object/class_object.c:541 — 주석의 이름과 실제 정의명이 다름 */
/*
 * classobj_copy_pk_unique_constraints() - Copy PK or NOT NULL UNIQUE ...   ← 옛 이름
 */
static int
classobj_copy_pk_and_uk_notnull_constraints (const SM_ATTRIBUTE * src, SM_ATTRIBUTE * dest)   /* ← 실제 이름 */
```

**② check_ha_repl_constraint() — src/query/execute_schema.c:9847~9866**
```c
/* src/query/execute_schema.c:9851 / 9861 — 주석은 없는 param(repl_opt)을 설명 */
 *   repl_opt(in)  : Replication option (true = ON, false = OFF)    /* ← 존재하지 않는 인자 */
...
int
check_ha_repl_constraint (DB_OBJECT * class_obj)   /* ← class_obj 하나뿐 */
```

- **재현 명세**
  - **진입 최소 상태**: 정적(문서) 결함 — 컴파일·런타임에 영향 없음. 단일 노드에서 소스 대조만으로 확인.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: 트리거 불가(순수 주석 불일치).
  - **대조 조건**: 주석을 현행 함수명·시그니처로 갱신하면 해소.
- **제안**: 두 주석을 실제 함수명/파라미터로 현행화.
- **신뢰도**: 높음 — 주석과 시그니처를 직접 대조 확정.

---

#### K-36. 전방선언과 정의의 static 키워드 불일치
- **심각도**: 보통
- **로직**: 전방 선언은 `static int check_ha_repl_constraint(...)`와 `static bool check_ha_repl_fk_ref_all_replicated(...)`로 둘 다 `static`인데, 정의부는 `bool check_ha_repl_fk_ref_all_replicated(...)`(9783)·`int check_ha_repl_constraint(...)`(9861)로 `static`이 빠져 있다. C에서는 앞선 선언에 `static`이 있으면 식별자가 내부 링키지를 갖지만, 정의부만 보면 외부 API처럼 읽혀 링키지 의도가 애매해진다.
- **관련 코드**
  1. `src/query/execute_schema.c:417-418` — 전방 선언 — 두 함수 모두 `static`
  2. `src/query/execute_schema.c:9783` — `check_ha_repl_fk_ref_all_replicated()` — 정의부에 `static` 누락
  3. `src/query/execute_schema.c:9861` — `check_ha_repl_constraint()` — 정의부에 `static` 누락

**① 전방 선언 — src/query/execute_schema.c:417~418**
```c
/* src/query/execute_schema.c:417 — 선언은 static */
static int check_ha_repl_constraint (DB_OBJECT * class_obj);
static bool check_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj);
```

**② check_ha_repl_fk_ref_all_replicated() 정의 — src/query/execute_schema.c:9783**
```c
/* src/query/execute_schema.c:9783 — 정의는 static 없음 */
bool
check_ha_repl_fk_ref_all_replicated (DB_OBJECT * class_obj)     /* ← static 누락 */
```

**③ check_ha_repl_constraint() 정의 — src/query/execute_schema.c:9861**
```c
/* src/query/execute_schema.c:9861 — 정의는 static 없음 */
int
check_ha_repl_constraint (DB_OBJECT * class_obj)               /* ← static 누락 */
```

- **재현 명세**
  - **진입 최소 상태**: 정적 결함 — 컴파일/링크 시점. 단일 노드.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: 트리거 불가(링키지 규약 혼선의 정적 결함). 다른 TU에서 정의부 시그니처만 보고 extern으로 선언·호출을 시도하면 링크 에러로 드러난다.
  - **대조 조건**: 정의부에도 `static`을 붙여 선언과 통일하면 해소. (참고: 인접한 `log_ha_repl_fk_ref_all_replicated`는 util_cs.c에서 실제로 cross-TU 호출되므로 비-static이 맞다 — 이 두 함수만 파일 내부 전용.)
- **제안**: 정의에 `static`을 붙여 선언과 일치시킨다. (K2-3과 동일 유형이므로 묶어 처리.)
- **신뢰도**: 높음 — 선언/정의 대조 확정.

---

#### K2-3. is_data_repl_log_enabled()가 static 없이 정의됐으나 헤더 선언도 없어 링키지가 애매
- **심각도**: 보통
- **로직**: #7678이 같은 델타에서 추가한 4개 헬퍼 — `is_replication_class`(:3200), `get_spec_classname`(:3222), `pt_spec_repl_class_walk`(:3238), `spec_has_replication_class`(:3270) — 는 모두 `static`으로 파일 내부 링키지를 갖는다. 그런데 이들을 묶는 진입점 `is_data_repl_log_enabled`만 `static`이 빠져 **외부 링키지(전역 심볼)** 를 갖는다. 헤더(`execute_statement.h`)에는 이웃 `is_stmt_based_repl_type`만 `extern`으로 공개돼 있고, 이 함수는 헤더에도 파일 내 전방선언 블록에도 없다. 호출부는 :3405/:4113 두 곳 모두 같은 파일 안이다 — 즉 "파일 내부 전용"도 "정식 공개 API"도 아닌 애매한 상태로, 다른 번역 단위에 같은 이름 심볼이 있으면 링크 충돌 소지가 있고, 공개 의도라면 헤더 선언이 빠진 것이다.
- **관련 코드**
  1. `src/query/execute_statement.c:3303-3304` — `is_data_repl_log_enabled()` — 정의에 `static` 없음(외부 링키지), 헤더 선언도 없음
  2. `src/query/execute_statement.c:3200, 3270` — 형제 헬퍼(`is_replication_class`/`spec_has_replication_class`) — 모두 `static`
  3. `src/query/execute_statement.h:193` — 헤더 — 이웃 `is_stmt_based_repl_type`만 `extern` 공개

**① 형제 헬퍼(static) — src/query/execute_statement.c:3200, 3270**
```c
/* src/query/execute_statement.c:3200 — 형제 헬퍼 (static ✓) */
static bool
is_replication_class (const char *classname)
...
/* src/query/execute_statement.c:3270 — 형제 헬퍼 (static ✓) */
static bool
spec_has_replication_class (PARSER_CONTEXT * parser, PT_NODE * spec)
```

**② is_data_repl_log_enabled() 정의 — src/query/execute_statement.c:3303~3304**
```c
/* src/query/execute_statement.c:3303 — 진입점 (static 없음) */
bool
is_data_repl_log_enabled (PARSER_CONTEXT * parser, PT_NODE * statement)  /* ← 여기: static 누락, 헤더 선언도 없음 */
```

**③ 헤더 선언 — src/query/execute_statement.h:193**
```c
/* src/query/execute_statement.h:193 — 이웃만 extern */
extern bool is_stmt_based_repl_type (const PT_NODE * node);
/* ← is_data_repl_log_enabled 선언 없음 — 그런데 정의는 외부 링키지 */
```

- **시나리오**: 링크 충돌·유지보수 오해 소지(K-36과 동일 유형의 링키지 불일치가 이 델타의 다른 함수에서 나타남). 현 코드가 오작동하는 것은 아니라 정적 결함이다.
- **재현 명세**
  - **진입 최소 상태**: 런타임 결함이 아니라 컴파일·링크 시점의 정적 결함. 어떤 DB 상태·HA 모드도 요구하지 않는다. 단일 노드(빌드 환경)에서만 관측 가능하며 별도 프로세스 실행조차 불필요.
  - **스키마·데이터 조건**: 해당 없음.
  - **실행 순서**: 해당 없음(런타임 이벤트 없음). 관측은 소스 정적 점검 또는 링크 단계에서 이루어진다.
  - **최소 재현 입력**: 런타임 트리거 불가(정적 결함). 발현시키려면 다른 번역 단위(다른 `.c`)에 `is_data_repl_log_enabled`라는 동일 이름의 외부 링키지 심볼을 두어 링커 충돌(중복 정의)을 유발하는 인위적 구성이 필요하다. 현 코드베이스에는 그런 중복이 없어 지금 당장 빌드가 깨지지는 않는다.
  - **대조 조건**: 정의에 `static`을 붙이면(형제 헬퍼들과 동일) 외부 링키지가 사라져 충돌 소지가 없어진다. 반대로 공개 API 의도라면 `execute_statement.h`에 `extern` 선언을 추가하면 애매함이 해소된다.
- **제안**: 파일 내부 전용이면 static 부여, 공개 API면 헤더에 선언. (K-36과 묶어 처리)
- **신뢰도**: 높음 — 정의(static 없음)·헤더(선언 없음)·호출부(동일 파일 2곳)·형제 함수(전부 static)를 코드로 모두 확정. 정적 사실 관계라 실측 여지 없음.

---

#### K-34. 유령 전방선언 get_print_flags (실 정의는 get_repl_check_flags)
- **심각도**: 보통
- **로직**: 파일 앞부분에 `static int get_print_flags (UTIL_ARG_MAP *);`(187)이 선언돼 있지만, 실제로 정의된 함수는 `get_repl_check_flags()`(2867)이고 호출도 `get_repl_check_flags(arg_map)`(3287)로 이뤄진다. `get_print_flags`라는 이름은 선언 1곳만 있고 정의도 호출도 없다 — 함수 이름을 리네임하며 전방 선언만 옛 이름으로 남긴 잔재다. static 선언이라 참조가 없으면 컴파일 에러는 아니지만, 나중에 누군가 이 유령 선언을 보고 `get_print_flags`를 호출하면 링크 에러가 난다.
- **관련 코드**
  1. `src/executables/util_cs.c:187` — 유령 전방선언 `get_print_flags` — 정의도 호출도 없음
  2. `src/executables/util_cs.c:2866-2891, 3287` — `get_repl_check_flags()` — 실제 정의와 호출

**① 유령 전방선언 get_print_flags — src/executables/util_cs.c:187**
```c
/* src/executables/util_cs.c:187 */
static int get_print_flags (UTIL_ARG_MAP * arg_map);   /* ← 유령: 정의도 호출도 없음 */
```

**② get_repl_check_flags() 정의·호출 — src/executables/util_cs.c:2866, 3287**
```c
/* src/executables/util_cs.c:2866 — 실제 정의는 이 이름 */
static int
get_repl_check_flags (UTIL_ARG_MAP * arg_map)
{ ... }
/* src/executables/util_cs.c:3287 — 실제 호출도 이 이름 */
  repl_check_flags = get_repl_check_flags (arg_map);
```

- **재현 명세**
  - **진입 최소 상태**: 정적 결함 — 단일 노드 컴파일/링크 시점. 런타임 경로 없음.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요.
  - **최소 재현 입력**: 트리거 불가(현재는 미참조 static이라 무해). `get_print_flags(...)`를 실제로 호출하는 코드를 추가하면 링크 에러로 재현.
  - **대조 조건**: 선언 이름을 `get_repl_check_flags`로 고치거나 유령 선언을 삭제하면 불일치가 사라진다.
- **제안**: 187행 선언을 실제 이름으로 고치거나, 정의를 호출부보다 앞으로 옮기고 유령 선언을 삭제.
- **신뢰도**: 높음 — grep으로 `get_print_flags` 정의/호출 0건 확정.

---

#### K-33. find_index_catalog_class 데드 코드
- **심각도**: 보통
- **로직**: 인덱스 카탈로그 클래스(`CT_INDEX_NAME`)를 이름으로 찾아 주는 static 함수 `find_index_catalog_class()`가 추가됐으나, 코드베이스 전체에서 호출부가 하나도 없다(선언 120 + 정의 5134 두 곳뿐, grep으로 재확인). `static` 함수라 외부 링크도 불가능하므로 순수 죽은 코드다.
- **관련 코드**
  1. `src/object/schema_template.c:120` — `find_index_catalog_class` — 전방 선언
  2. `src/object/schema_template.c:5133-5159` — `find_index_catalog_class()` — 정의, 어디서도 호출되지 않음

**① 전방 선언 find_index_catalog_class — src/object/schema_template.c:120**
```c
/* src/object/schema_template.c:120 */
static MOP find_index_catalog_class (const char *name);   /* ← 전방 선언 */
```

**② find_index_catalog_class() 정의 — src/object/schema_template.c:5133~5159**
```c
/* src/object/schema_template.c:5133 — 정의, 그러나 어디서도 호출되지 않음 */
static MOP
find_index_catalog_class (const char *index_name)
{
  ...
  index_class = db_find_class (CT_INDEX_NAME);
  ...
  index_catalog_class = db_find_unique (index_class, "index_name", &value);
end:
  AU_ENABLE (save);
  return index_catalog_class;
}
```

- **재현 명세**
  - **진입 최소 상태**: 정적 결함 — 단일 노드 컴파일 시점에만 관찰. 런타임 경로 없음.
  - **스키마·데이터 조건**: 없음.
  - **실행 순서**: HA 왕복 불필요. 빌드(컴파일) 단계에서 `-Wunused-function` 경고 대상.
  - **최소 재현 입력**: 트리거 불가(호출부 부재의 정적 결함). `-Werror` 빌드에서는 컴파일 실패로 드러난다.
  - **대조 조건**: 실제 호출부를 추가하거나 함수를 삭제하면 경고가 사라진다. `-Wunused-function`을 끈 빌드에서는 무해.
- **제안**: 실제로 쓸 계획이 없으면 삭제하고, 후속 PR에서 쓸 예정이면 그 PR로 미룬다.
- **신뢰도**: 높음 — grep으로 호출 0건 확정, static이라 외부 링크 불가.

### 사소 이슈 통합 (9건)

배치는 실질 위험이 큰 순서다: 운영 중 실제로 벌어지는 결함(K-63, K-69) → 잠재적 빌드/링크 위험(K3-6, K-61) → 가독성·유지보수 함정(K-66, K-59) → 문서·표기 완성도(K-65, K-60, K-64).

---

#### K-63. 위반목록 파일명이 분 단위라 같은 분 재실행 시 이전 진단 덮어씀

**관련 코드**
1. `src/executables/util_cs.c:2839` — `generate_violation_list_file_name()` — 위반목록 파일명을 `YYYYMMDD_HHMM` 분 단위 타임스탬프로 생성(초 필드 없음).
2. `src/executables/util_cs.c:2856` — `open_violation_list_file()` — 생성된 파일명으로 항상 트렁케이트(`"w"`) 모드로 오픈.

**① generate_violation_list_file_name() — src/executables/util_cs.c:2838~2853**
```c
/* src/executables/util_cs.c:2839 — generate_violation_list_file_name() */
static char *
generate_violation_list_file_name (char *out, char *database_name, const char *util_name)
{
  time_t log_time;
  struct tm log_tm, *log_tm_p = &log_tm;

  log_time = time (NULL);
  log_tm_p = localtime_r (&log_time, &log_tm);
  if (log_tm_p != NULL)
    {
      snprintf (out, PATH_MAX - 1, "%s_%s_%04d%02d%02d_%02d%02d.list",
                database_name, util_name, log_tm_p->tm_year + 1900, log_tm_p->tm_mon + 1, log_tm_p->tm_mday,
                log_tm_p->tm_hour, log_tm_p->tm_min);   /* ← 여기: 초(sec) 필드 없음 */
    }
  return out;
}
```

**② open_violation_list_file() — src/executables/util_cs.c:2855~2864**
```c
/* src/executables/util_cs.c:2863 — open_violation_list_file() */
static FILE *
open_violation_list_file (const char *database_name, const char *util_name, char *file_path, size_t file_path_size)
{
  char violation_list_file[PATH_MAX];
  envvar_logdir_file (file_path, file_path_size,
                      generate_violation_list_file_name (violation_list_file, (char *) database_name, util_name));
  file_path[file_path_size - 1] = '\0';

  return fopen (file_path, "w");   /* ← 여기: 항상 트렁케이트 오픈 */
}
```

**로직 설명**: 파일명이 `DB_유틸리티명_YYYYMMDD_HHMM.list`까지만 포함해 초 단위가 없다. `open_violation_list_file()`은 이 이름으로 항상 `"w"`(트렁케이트) 모드로 `fopen`한다. rkcheck 본문(`util_cs.c:3320` 부근)에서 DB 재기동에 성공하면 위반 여부와 무관하게 매번 이 파일을 새로 연다.

**문제 시나리오**: 같은 분 안에 rkcheck를 두 번 실행하면(예: HA 기동 재시도 스크립트가 짧은 간격으로 반복 호출) 두 번째 실행이 첫 번째 진단 파일을 그대로 덮어써, 첫 실행이 남긴 위반 목록이 사라진다.

**제안**: 파일명에 초 단위 추가(또는 PID) 하거나 append 모드로 변경.

**재현 명세**
- 진입 최소 상태: 단일 노드(유틸리티 프로세스) — HA/서버 상태 무관, `cubrid rkcheck`가 `db_restart()`에 성공하기만 하면 도달.
- 스키마·데이터 조건: 없음 — 위반이 있든 없든 파일은 항상 새로 열린다.
- 실행 순서: 단일 노드 재현 가능. `cubrid rkcheck db1` 실행 → 같은 분 내 `cubrid rkcheck db1` 재실행.
- 최소 재현 입력(쉘):
```bash
cubrid rkcheck db1; cubrid rkcheck db1   # 같은 분 안에 연속 실행되면 두 번째가 첫 결과 덮어씀
```
- 대조 조건: 두 실행 사이에 분(minute)이 바뀌면 파일명이 달라져 덮어쓰기가 발생하지 않는다.

**신뢰도**: 높음 — `snprintf` 포맷 문자열에 초 필드 부재와 `fopen(..., "w")` 모두 코드로 확정.

---

#### K-69. CTAS가 HA 모드 기본 ON이라 항상 RK-필수 에러(원인 불명 안내)

**관련 코드**
1. `src/query/execute_schema.c:9860` — `check_ha_repl_constraint()` — HA 모드에서 RK(PK/NOT NULL UNIQUE) 부재 시 CTAS 여부 언급 없는 범용 에러를 낸다.
2. `src/query/execute_schema.c:10247` — `do_create_entity()` — CTAS 포함 REPLICATION 옵션 미지정 시 기본 ON으로 판정해 RK 검사를 강제한다.

**① check_ha_repl_constraint() — src/query/execute_schema.c:9860~9880**
```c
/* src/query/execute_schema.c:9860 — check_ha_repl_constraint() */
int
check_ha_repl_constraint (DB_OBJECT * class_obj)
{
  if (HA_DISABLED ())
    {
      return NO_ERROR;                                  /* 싱글 모드면 항상 통과 */
    }

  if (!classobj_has_class_repl_key_constraint (db_get_constraints (class_obj)))
    {
      er_set (ER_ERROR_SEVERITY, ARG_FILE_LINE, ER_HA_REPLICATION_KEY_REQUIRED, 0);
      /* ← 여기: CTAS 여부를 구분하지 않는 범용 메시지 */
      return ER_HA_REPLICATION_KEY_REQUIRED;
    }
  ...
  return NO_ERROR;
}
```

**② do_create_entity() — src/query/execute_schema.c:10247~10284**
```c
/* src/query/execute_schema.c:10258 — do_create_entity() */
      if (create_like)
        {
          is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF);
        }
      else
        {
          is_replication_on = IS_CREATE_STMT_SET_REPL_OPTION (tbl_opt_replication);
          /* ← 여기: REPLICATION 옵션 미지정 시 기본 true(ON) */
        }

      if (is_replication_on)
        {
          error = check_ha_repl_constraint (class_obj);   /* ← 여기: CTAS 결과 테이블도 그대로 RK 요구 */
          if (error != NO_ERROR)
            {
              goto error_exit;
            }
        }
```

**로직 설명**: `CREATE TABLE ... AS SELECT`(CTAS)로 만든 테이블은 `SELECT` 결과 컬럼으로만 구성되므로 PK나 NOT NULL UNIQUE(RK)가 자동으로 붙지 않는다. `do_create_entity()`는 CTAS든 일반 `CREATE TABLE`이든 REPLICATION 옵션을 명시하지 않으면 `IS_CREATE_STMT_SET_REPL_OPTION`이 기본 `true`(ON)를 돌려주고, HA 모드에서는 `check_ha_repl_constraint()`가 RK 부재를 그대로 에러(`ER_HA_REPLICATION_KEY_REQUIRED`)로 잡는다.

**문제 시나리오**: HA 모드에서 `CREATE TABLE t AS SELECT ...`을 REPLICATION 옵션이나 PK 지정 없이 실행하면 **항상** RK 필수 에러가 난다. 그런데 에러 메시지는 "PRIMARY KEY 또는 NOT NULL UNIQUE를 추가하라"는 일반 안내만 할 뿐, "CTAS라서 RK가 자동으로 안 붙는다"는 원인은 설명하지 않아 사용자가 왜 매번 실패하는지 헷갈리기 쉽다.

**제안**: CTAS 경로 감지 시 에러 메시지에 CTAS 상황을 안내하는 문구 추가.

**재현 명세**
- 진입 최소 상태: HA 모드(`!HA_DISABLED()`) + CTAS에서 `REPLICATION` 옵션 미지정(기본 ON).
- 스키마·데이터 조건: 소스 테이블/뷰는 임의(예: `db_root`). CTAS 결과 테이블에 PK·NOT NULL UNIQUE를 별도로 추가하지 않은 상태.
- 실행 순서: 단일 노드 재현 가능(서버가 HA 모드로 기동돼 있으면 됨, 슬레이브 왕복 불필요).
- 최소 재현 입력:
```sql
-- (전제) 서버가 HA 모드로 기동된 상태
CREATE TABLE ctas_t AS SELECT 1 AS c1 FROM db_root;
-- → ER_HA_REPLICATION_KEY_REQUIRED, 메시지에 "CTAS라서 그렇다"는 설명 없음
```
- 대조 조건: (1) 싱글 모드(비-HA)면 `HA_DISABLED()`가 참이라 통과. (2) `CREATE TABLE ctas_t (REPLICATION=OFF) AS SELECT ...`처럼 REPLICATION=OFF를 명시하면 `check_ha_repl_constraint` 자체가 호출되지 않아 통과.

**신뢰도**: 높음 — `IS_CREATE_STMT_SET_REPL_OPTION`의 기본값 true, `check_ha_repl_constraint`의 `HA_DISABLED()` 게이트, `do_create_entity`의 호출 순서를 모두 코드로 직접 확인.

---

#### K3-6. 신규 헬퍼 or_class_flags()가 프로토타입 없는 비-static 외부 심볼로 새어나가고 or_is_replication_candidate_key도 이웃과 달리 extern 없이 선언돼 링키지 의도 불명확

**관련 코드**
1. `src/base/object_representation_sr.c:770` — `or_class_flags()` — 클래스 레코드에서 플래그 정수를 읽는 보조 함수, static도 헤더 선언도 없이 정의됨.
2. `src/base/object_representation_sr.c:781` — `or_class_is_replication_on()` — `or_class_flags()`의 유일한 호출부(동일 TU).
3. `src/base/object_representation_sr.h:241-244` — 형제 헬퍼 3종의 extern 선언(대조군).
4. `src/base/object_representation_sr.h:282` — `or_is_replication_candidate_key()` 선언, extern 누락.

**① or_class_flags() — src/base/object_representation_sr.c:770~779**
```c
/* src/base/object_representation_sr.c:770 — or_class_flags() */
void
or_class_flags (RECDES * record, int *flags)   /* ← 여기: static 아님, 헤더 선언 없음 */
{
  char *ptr;
  assert (OR_GET_OFFSET_SIZE (record->data) == BIG_VAR_OFFSET_SIZE);
  ptr = record->data + OR_FIXED_ATTRIBUTES_OFFSET (record->data, ORC_CLASS_VAR_ATT_COUNT);
  *(int *) flags = OR_GET_INT (ptr + ORC_CLASS_FLAGS);
}
```

**② or_class_is_replication_on() — src/base/object_representation_sr.c:781~792**
```c
/* src/base/object_representation_sr.c:789 — or_class_is_replication_on() */
bool
or_class_is_replication_on (RECDES * record)
{
  int flags = 0;
  int replication_off_flag = 32;  /* SM_CLASSFLAG_REPLICATION_OFF = 32 */
  ...
  or_class_flags (record, &flags);   /* ← 여기: 유일한 호출부(동일 TU) */
  return !(flags & replication_off_flag);
}
```

**③ 형제 헬퍼 extern 선언(대조군) — src/base/object_representation_sr.h:241~244**
```c
/* src/base/object_representation_sr.h:242 — or_class_hfid() 등 헤더 선언부 */
extern void or_class_rep_dir (RECDES * record, OID * rep_dir_p);
extern void or_class_hfid (RECDES * record, HFID * hfid);
extern void or_class_tde_algorithm (RECDES * record, TDE_ALGORITHM * tde_algo);
extern bool or_class_is_replication_on (RECDES * record);
/* ← 여기: or_class_flags 선언 자체가 이 헤더 어디에도 없음(grep 부재) */
```

**④ or_is_replication_candidate_key() 선언 — src/base/object_representation_sr.h:281~282**
```c
/* src/base/object_representation_sr.h:282 — or_is_replication_candidate_key() 선언 */
extern int or_mvcc_set_log_lsa_to_record (RECDES * record, LOG_LSA * lsa);
bool or_is_replication_candidate_key (const OR_INDEX * index);   /* ← 여기: extern 누락(이웃과 불일치) */
```

**로직 설명**: `or_class_is_replication_on`(클래스 레코드에서 복제 OFF 플래그를 읽어 복제 여부를 판정하는 헬퍼)은 내부에서 플래그 정수를 뽑아오는 보조 함수 `or_class_flags(RECDES*, int*)`를 부른다. 이 `or_class_flags`는 (1) 어떤 헤더에도 선언이 없고, (2) `static`도 아니며, (3) 유일한 호출부는 동일 번역단위(TU) 안의 `or_class_is_replication_on` 한 곳뿐이다. 형제 헬퍼 `or_class_hfid`·`or_class_tde_algorithm`·`or_class_is_replication_on`은 모두 헤더에 `extern` 선언을 갖는 것과 달리, `or_class_flags`만 의도치 않게 전역 링키지로 노출된다. 또한 `or_is_replication_candidate_key`는 헤더에서 이웃 선언들(모두 `extern`)과 달리 `extern` 없이 선언된다.

**문제 시나리오**: `or_class_flags`가 `static`도 아니고 헤더 프로토타입도 없어 전역 링키지로 새어나간다. 이 상태는 (1) 다른 TU에 동명 심볼이 있으면 링크타임 심볼 충돌 위험, (2) 다른 파일에서 선언 없이 부르면 암시적 선언(이 코드베이스는 C++로 컴파일되므로 컴파일 에러/경고), (3) `-Wmissing-prototypes` 경고 유발 가능성을 남긴다. `or_is_replication_candidate_key`의 `extern` 누락도 컴파일 결과(파일 스코프 함수 선언은 기본 external linkage)는 이웃과 같지만 표기 일관성이 깨져 코드 리뷰·정적분석에서 혼선을 준다.

**제안**: `or_class_flags`는 호출부가 동일 TU 한 곳뿐이므로 `static`으로 선언해 파일 스코프로 가두는 것이 가장 간단·안전하다(다른 TU에서 쓸 계획이면 대신 헤더에 `extern` 프로토타입 추가). `or_is_replication_candidate_key`는 이웃 선언과 맞춰 `extern`을 붙여 표기를 일관화한다.

**재현 명세**
- 진입 최소 상태: 런타임 상태 무관 — 컴파일/링크 타임 결함. 관측 지점은 `or_class_flags`가 `static`/헤더선언 없이 정의된 지점과 `or_is_replication_candidate_key`의 extern 없는 선언.
- 스키마/데이터 조건: 해당 없음(정적 코드 속성).
- 실행 순서: 단일 노드 재현(빌드 단계, 복제 무관).
- 최소 재현 절차: `grep -rn "or_class_flags" src/`로 정의 1 + 동일 TU 호출 1, 선언 0건 확인 → 비-static 전역 심볼임에도 프로토타입 부재 확인. `-Wmissing-prototypes` 활성 빌드에서 경고 관측 가능(빌드 옵션 의존).
- 대조 조건: 형제 `or_class_hfid`/`or_class_tde_algorithm`/`or_class_is_replication_on`은 헤더 extern 선언 보유가 대조군 — `or_class_flags`만 누락. `or_is_replication_candidate_key`는 이웃(모두 extern)이 대조군. static화 또는 extern 추가 후 비대칭 해소.

**신뢰도**: 높음 — static/extern 표기, 헤더 선언 부재, 단일 TU 호출을 모두 grep/Read로 확정. 다만 기능적 오작동이 아니라 링키지 위생·경고 위험 수준이라 심각도 사소가 타당.

---

#### K-61. UTIL_INDEX enum에 RKCHECK를 끝이 아닌 중간 삽입

**관련 코드**
1. `src/executables/utility.h:788-832` — `UTIL_INDEX` enum — `RKCHECK`가 마지막 원소 `LOGFILEDUMP` 바로 앞에 삽입되어 `LOGFILEDUMP`의 서수 값이 하나 밀림.

**① UTIL_INDEX enum — src/executables/utility.h:788~832**
```c
/* src/executables/utility.h:826 — UTIL_INDEX enum */
  VACUUMDB,
  CHECKSUMDB,
  TDE,
  FLASHBACK,
  MEMMON,
  RKCHECK,        /* ← 여기: 새 유틸리티를 끝이 아니라 LOGFILEDUMP 앞에 끼워 넣음 */
  LOGFILEDUMP
} UTIL_INDEX;
```

**로직 설명**: `UTIL_INDEX`는 각 유틸리티를 나열하는 enum으로, 목록 끝에 새 항목을 추가하는 것이 기존 관례다(그래야 기존 값들의 서수가 안 바뀐다). 이번 기능은 `RKCHECK`를 마지막 원소 `LOGFILEDUMP` 바로 앞에 끼워 넣어, `LOGFILEDUMP`의 서수 값이 하나 밀렸다.

**문제 시나리오**: 현재 `grep -rn "UTIL_INDEX"`로 전체 소스를 훑어도 이 타입이나 `LOGFILEDUMP` enum 상수를 서수(정수)로 취급하는 소비처가 코드베이스에 없어, 지금 당장 값이 밀려도 실제로 깨지는 곳은 없다. 다만 향후 이 enum을 배열 인덱스나 직렬화 값으로 쓰는 코드가 추가되면 관례 위반이 실제 버그로 발전한다.

**제안**: enum 끝(`LOGFILEDUMP` 뒤)에 추가.

**재현 명세**: 재현 불필요 — 정적 결함, 현재 이 enum의 서수 값을 소비하는 코드가 없어 트리거 자체가 불가능.

**신뢰도**: 높음 — enum 선언과 `grep -rn UTIL_INDEX`/`LOGFILEDUMP` 전체 검색으로 소비처 부재까지 확인.

---

#### K-66. do_alter에서 일반 테이블 객체 변수명이 vclass

**관련 코드**
1. `src/query/execute_schema.c:1837` — `do_alter()` 지역변수 선언 — 이름은 '뷰'인데 테이블도 담는 범용 변수.
2. `src/query/execute_schema.c:2061` — `do_alter()` RK 재검사 게이트 — 이 변수에 일반 테이블 객체를 담아 사용.

**① do_alter() 변수 선언 — src/query/execute_schema.c:1829~1837**
```c
/* src/query/execute_schema.c:1837 — do_alter() 지역변수 */
do_alter (PARSER_CONTEXT * parser, PT_NODE * alter)
{
  int error_code = NO_ERROR;
  PT_NODE *crt_clause = NULL;
  ...
  DB_OBJECT *vclass;                 /* ← 여기: 이름은 '뷰'인데 테이블도 담는 범용 변수 */
```

**② do_alter() RK 재검사 게이트 — src/query/execute_schema.c:2059~2068**
```c
/* src/query/execute_schema.c:2061 — do_alter() RK 재검사 게이트, K-1/K-6과 같은 지점 */
  if (need_check_repl_constraint)
    {
      vclass = db_find_class (entity_name);      /* entity_name은 ALTER TABLE 대상 — 뷰가 아니어도 여기 담김 */
      if (!sm_is_replication_class (vclass))
        {
          return NO_ERROR;
        }
      error_code = check_ha_repl_constraint (vclass);
```

**로직 설명**: CUBRID 코드 관례상 `vclass`는 "뷰(virtual class)"를 가리키는 이름인데, `do_alter()`는 `ALTER TABLE`(일반 테이블)을 처리하는 함수이고 RK 재검사 게이트에서도 이 변수에 **일반 테이블**의 `DB_OBJECT*`를 담는다. 이름과 실제 담기는 값의 의미가 어긋나 읽는 사람이 "뷰 전용 분기인가?"로 오해하기 쉽다.

**제안**: `class_obj` 등 중립적인 이름으로 변경.

**재현 명세**: 재현 불필요 — 정적 결함(가독성/명명 문제, 동작에 영향 없음).

**신뢰도**: 높음 — 선언부와 실사용 지점(RK 재검사 게이트)을 모두 확인, `entity_name`이 `ALTER TABLE`의 대상 이름임을 코드로 확정.

---

#### K-59. PRINT_MESSAGE 매크로에 불필요한 라인 연속 백슬래시

**관련 코드**
1. `src/executables/util_cs.c:106-109` — `PRINT_MESSAGE` 매크로 — 형제 매크로와 달리 `} while (0)` 뒤에 줄 연속 백슬래시가 남아 매크로 정의가 다음 줄까지 편입됨.

**① PRINT_MESSAGE 매크로 — src/executables/util_cs.c:92~109**
```c
/* src/executables/util_cs.c:106 — PRINT_MESSAGE 매크로 */
#define PRINT_SECTION_TITLE(stream, title)                                    \
  do                                                                          \
    {                                                                         \
      fprintf ((stream), "< %s >\n", (title));                                \
    }                                                                         \
  while (0)

#define PRINT_MESSAGE(stream, detail)  \
  do {                                                          \
    fprintf ((stream), "%s\n", detail);                                 \
  } while (0)                                                   \
                              /* ← 여기: 다음 줄(공백줄)까지 매크로 정의에 편입됨 */
```

**로직 설명**: rkcheck 결과 출력에 쓰는 세 매크로 `PRINT_SECTION_TITLE`·`PRINT_BLANK_LINE`·`PRINT_MESSAGE`는 모두 `do { ... } while(0)` 패턴이다. 앞의 두 매크로는 `while (0)`으로 정의가 끝나는데, `PRINT_MESSAGE`만 `} while (0)` 뒤에 줄 연속 백슬래시 `\`가 하나 더 붙어 있다. 다음 줄이 빈 줄이라 지금 당장은 전처리 결과에 영향이 없지만, 매크로가 "아직 안 끝났다"는 상태이므로 이 자리에 주석이나 다른 `#define`을 무심코 붙이면 그 줄까지 조용히 매크로 본문에 흡수된다.

**제안**: 마지막 줄의 백슬래시 제거.

**재현 명세**: 재현 불필요 — 정적 결함(현재 코드에서 기능적 영향 없음, 잠재적 유지보수 함정).

**신뢰도**: 높음 — 형제 매크로 2개와 직접 대조해 백슬래시 유무 차이를 코드로 확인.

---

#### K-65. rkcheck usage가 -r/-f 생략 시 기본동작(RK+FK 모두) 미문서화

**관련 코드**
1. `src/executables/util_cs.c:2867` — `get_repl_check_flags()` — `-r`/`-f`를 둘 다 안 주면 RK·FK 검사를 둘 다 켠다.
2. `msg/en_US.utf8/utils.msg:1382-1390` — rkcheck usage 메시지 — 옵션 생략 시 동작을 언급하지 않음.

**① get_repl_check_flags() — src/executables/util_cs.c:2866~2891**
```c
/* src/executables/util_cs.c:2885 — get_repl_check_flags() */
static int
get_repl_check_flags (UTIL_ARG_MAP * arg_map)
{
  ...
  if (repl_check_flags == 0)
    {
      repl_check_flags = REPL_CHECK_RK | REPL_CHECK_FK;   /* ← 여기: -r/-f 둘 다 생략 시 기본값 */
    }

  return repl_check_flags;
}
```

**로직 설명**: `get_repl_check_flags()`는 `-r`/`-f`를 둘 다 안 주면(`repl_check_flags == 0`) RK·FK 검사를 **둘 다** 켠다. 그런데 usage 메시지는 `-r`, `-f` 옵션 각각의 뜻만 설명할 뿐, "옵션을 아무것도 안 주면 어떻게 되는지"는 한 줄도 언급하지 않는다.

**문제 시나리오**: `cubrid rkcheck --help`만 보고 사용하는 운영자는 옵션 없이 실행했을 때 아무 검사도 안 하는지, 기본 검사를 하는지 알 길이 없다 — 문서 완성도 문제로 오동작은 아니다.

**제안**: usage에 "옵션 생략 시 RK+FK 모두 검사"를 명시.

**재현 명세**: 재현 불필요 — 정적 결함(문서 누락). 확인은 `cubrid rkcheck --help` 출력과 `get_repl_check_flags()` 실제 동작을 대조하는 것으로 충분하다.

**신뢰도**: 높음 — 기본값 분기와 usage 메시지 전문을 모두 코드로 대조.

---

#### K-60. rkcheck usage 메시지 형식 오류(단수/trailing 공백/개행 누락)

**관련 코드**
1. `msg/en_US.utf8/utils.msg:1382-1390` — rkcheck usage 메시지(en) — "valid option:"(단수) 및 파일 끝 개행 누락.
2. `msg/ko_KR.utf8/utils.msg:1362-1369` — rkcheck usage 메시지(ko) — 동일 결함.

**① rkcheck usage 메시지(en) — msg/en_US.utf8/utils.msg:1387~1390**
```
# msg/en_US.utf8/utils.msg:1387-1390 ($set 61 MSGCAT_UTIL_SET_RKCHECK)
valid option:\n\
    -r, --rk-check           Check RK(Replication Key) constraint violations\n\
    -f, --fk-check           Check FK(Foreign Key) constraint violations\n
                                                                          /* ← 파일이 개행 없이 끝남 */
```

**로직 설명**: rkcheck usage는 옵션이 `-r`/`-f` 두 개인데 en/ko 파일 모두 "valid option:"(단수)를 쓴다. 같은 파일의 다른 유틸리티 40여 곳은 전부 "valid options:"(복수)이므로 rkcheck만 관례에서 벗어난다. 또한 `xxd`로 파일 끝을 확인하면 en/ko 두 파일 모두 마지막 바이트가 개행(`\n`) 없이 공백으로 끝난다(POSIX 텍스트 파일 관례 위반). 기능 동작에는 영향 없고 `msgcat` 편집 시 diff 노이즈·툴 경고 정도의 영향이다.

**제안**: "valid option:"→"valid options:" 통일, 파일 끝 개행 보강.

**재현 명세**: 재현 불필요 — 정적 결함(메시지 카탈로그 텍스트 자체의 오탈자).

**신뢰도**: 높음 — grep으로 전체 "valid option(s)" 용례 대조 + `xxd`로 EOF 바이트 직접 확인.

---

#### K-64. do_promote_partition 미사용 지역변수 tmp/c

**관련 코드**
1. `src/query/execute_schema.c:7877-7999` — `do_promote_partition()` — 지역변수 `tmp`, `c`가 선언만 되고 함수 끝까지 한 번도 안 쓰임.

**① do_promote_partition() 변수 선언 — src/query/execute_schema.c:7877~7888**
```c
/* src/query/execute_schema.c:7887 — do_promote_partition() */
static int
do_promote_partition (SM_CLASS * class_)
{
  MOP subclass_mop = NULL;
  int error = NO_ERROR;
  SM_CLASS *current = NULL;
  DB_CTMPL *ctemplate = NULL;
  SM_ATTRIBUTE *smattr = NULL;
  bool has_notnull_unique = false;

  DB_CONSTRAINT *tmp;              /* ← 여기: 함수 끝(7999)까지 한 번도 안 쓰임 */
  SM_CLASS_CONSTRAINT *c;          /* ← 여기: 마찬가지 */
  CHECK_1ARG_ERROR (class_);
```

**로직 설명**: `do_promote_partition()`은 파티션을 승격(부모와 분리해 독립 테이블화)할 때 RK 제약을 재확인하는 함수다. `tmp`, `c` 두 변수는 선언만 되고 함수 끝까지 대입도 참조도 없다 — grep으로 함수 본문 전체를 훑어도 두 식별자가 다시 등장하지 않는다.

**제안**: 미사용 변수 제거(컴파일러 경고 해소).

**재현 명세**: 재현 불필요 — 정적 결함(컴파일 경고, 런타임 동작 무관).

**신뢰도**: 높음 — 함수 시작부터 끝까지 전체를 grep으로 대조해 재참조 없음을 확인.

---

---

## 3. 부록

### ① 신뢰도 중간·낮음 이슈 (25건)

정적 분석으로 결함(방어 부재·불일치·중복)은 확정했으나, 실제 발현 빈도·조건이 경계 케이스이거나 런타임 실측이 필요해 신뢰도를 중간·낮음으로 둔 이슈다. 원문 개별 리포트는 `reports/` 참조.

| ID | 심각도 | 제목 | 위치 | 요지 | 신뢰도 |
|---|---|---|---|---|---|
| K-7 | 치명 | sm_is_replication_class가 조회/NULL 실패를 assert(false)+false로 삼킴 | `src/object/schema_manager.c:3394-3407` | fetch 실패·NULL mop을 에러 전파 없이 "비복제"로 뭉갬(release 조용한 오판·debug abort), int 반환+out-param 처방 미적용 | 중간 |
| K-8 | 중요 | 삼킴 안티패턴이 신규 복제판정 함수 2곳에 잔존 | `schema_manager.c:3404` `sm_is_replication_class`, `execute_statement.c:3213` `is_replication_class` | 두 판정 함수가 클래스 fetch/이름 해석 실패를 `assert(false); return false`로 삼켜 release에서 조회 실패가 "비복제"로 오판됨(K-15/K-29/K-45 공통 뿌리) | 중간 |
| K-9 | 중요 | do_alter_change_replication이 COMMENT 변경용 세이브포인트 이름을 재사용 | `execute_schema.c:11747, 11823` | REPLICATION 변경이 전용 세이브포인트 없이 COMMENT용 `"cHANGEtBLcOMMENT"`를 재사용해, 한 ALTER에 두 절이 오면 동명 세이브포인트가 중복 생성돼 롤백 지점이 뒤섞임 | 중간 |
| K-13 | 중요 | rkcheck/applyinfo 호스트명 버퍼 오버플로우·트렁케이션이 TODO만 남긴 채 미해결 | `util_cs.c:3273, 3297-3302, 4092-4095` | rkcheck는 `snprintf` 반환값 미검사로 긴 DB명 결합 시 조용한 트렁케이션, applyinfo는 경계 미검사 `strcpy/strcat` — 엉뚱한 DB로 db_restart 위험 | 중간 |
| K-14 | 중요 | 파티션 승격 시 복합 NOT NULL UNIQUE의 두 번째 이후 컬럼 UNIQUE 플래그가 잘못 제거 | `execute_schema.c:7833-7994` `do_promote_partition` | 클래스 단위 bool `has_notnull_unique`를 per-attr 가드로 오용해 복합 UNIQUE의 2번째 이후 컬럼 `SM_ATTFLAG_UNIQUE`가 소거되어 attribute 플래그와 프로퍼티 불일치 | 중간 |
| K-15 | 중요 | is_replication_class(execute_statement)가 이름 해석 실패를 삼켜 SBR 조용히 미복제 | `execute_statement.c:3210-3216` | `db_find_class` 실패를 `assert(false); return false`로 삼켜 SBR 로그 미생성 → 슬레이브 미반영(호출부 flat_entity_list 폴백으로 실무 영향 부분 완화) | 중간 |
| K-17 | 중요 | do_alter 최종 재검사가 db_find_class NULL을 미검사하고 sm_is_replication_class(NULL)에 전달 | `execute_schema.c:2061-2066`, `schema_manager.c:3391-3406` | NULL 미검사로 release에선 RK 재검사가 조용히 NO_ERROR로 생략, debug에선 assert(false) 서버 abort | 중간 |
| K-24 | 중요 | 파티션 승격 전용 제약 복사 로직이 범용 attribute-copy 경로에 부작용 | `class_object.c:560-587` `classobj_copy_pk_and_uk_notnull_constraints`, `:4815-4822`, `:4882` | 승격용 특수 복사가 공용 copy 경로에 `if (src->constraints != NULL)`만으로 무조건 삽입돼 플래트닝·FK 복사 등에서 부모 BTID 공유 오염 위험 | 중간 |
| K-26 | 중요 | or_is_replication_candidate_key가 filter_predicate·함수 기반 인덱스를 RK에서 구분하지 않음 | `object_representation_sr.c:4694-4722`, `.h:187-188` | 부분(filtered)·함수 기반 UNIQUE를 전역 유일로 오인해 RK로 통과시켜 필터 밖 행이 슬레이브에서 유일 식별되지 않고 행 매칭 어긋남 | 중간 |
| K-28 | 중요 | hb start가 자동 실행하는 rkcheck에 타임아웃이 없어 무기한 대기 가능 | `util_service.c:3233` `us_hb_process_rkcheck` (`proc_execute` wait_child=true) | 타임아웃 인자 없는 `wait_child=true`로 특정 DB rkcheck가 디스크/락에 멈추면 `cubrid hb start` 전체가 무기한 블록 | 중간 |
| K-29 | 중요 | describe_class(SHOW CREATE TABLE)가 클래스 조회 실패 시 REPLICATION=OFF로 오표시 | `object_printer.cpp:1137-1145` | `sm_is_replication_class`의 삼킴(K-7)으로 일시적 fetch 실패 시 복제 ON 테이블이 OFF로 표시돼 DBA 오도 | 중간 |
| K-40 | 보통 | rkcheck 종료코드 체계 비일관(음수 ER 코드 8비트 절단) | `src/executables/util_cs.c:3283·3306·3387·3411` (`rkcheck`) | 유틸 종료코드에 엔진 에러코드(-1378)를 그대로 반환, 하위 8비트만 유효해 향후 반환값이 256 배수면 exit 0으로 잘려 위반에도 HA 기동 | 중간 |
| K-45 | 보통 | unloaddb 클래스 조회 실패 시 잘못된 REPLICATION=OFF 덤프 | `src/executables/unload_schema.c:1739-1742·1794-1801` (`emit_schema`) | fetch 실패로 class_=NULL이어도 REPLICATION 블록만 NULL 가드 없이 `sm_is_replication_class` 호출→ON 테이블이 OFF로 덤프 | 중간 |
| K-50 | 보통 | SHOW CREATE/unload의 `=` 표기가 스펙(공백)과 불일치 | `src/object/object_printer.cpp:1137-1145` (`describe_class`) | `REPLICATION=ON`을 등호로 출력해 스펙 공백 표기·타 옵션(COLLATE/ENCRYPT)과 불일치(cosmetic) | 중간 |
| K-51 | 보통 | `has_notnull_unique_constraints`가 PK를 감지 못 하는데 주석은 PK 보존 약속 | `src/query/execute_schema.c:7837-7871` (`has_notnull_unique_constraints`) | PK 미감지, PK 보존이 드롭목록에 PK가 없어 우연히 성립—드롭목록 변경 시 조용히 깨질 소지 | 중간 |
| K-52 | 보통 | 혼합 ON/OFF 멀티테이블 SBR UPDATE/DELETE가 슬레이브의 OFF 대상 테이블까지 변경 | `src/query/execute_statement.c:3320-3343` (`is_data_repl_log_enabled`) | 대상 중 하나라도 ON이면 문장 전체 SBR→슬레이브 재실행이 OFF 대상까지 수정→divergence | 중간 |
| K-55 | 보통 | Failover/switchover/failback 승격 경로가 rkcheck 검증을 우회 | `src/executables/util_service.c:3963-3973` (`us_hb_process_start`) | rkcheck는 최초 start 경로에만—역할전환 승격은 미검증, RK 사라진 테이블도 승격 진행 | 중간 |
| K-56 | 보통 | ADD PRIMARY KEY가 RK를 UK→PK로 무경고 재할당 | `src/base/object_representation_sr.c:4693-4722` (`or_is_replication_candidate_key`), `src/storage/btree.c:8285-8299` (`btree_get_rkey_btid`) | PK 최우선 선택이라 UK를 RK로 쓰던 테이블에 PK 추가 시 RK가 말없이 이동, 경고 없음 | 중간 |
| K-58 | 보통 | RK 자동 선택이 인덱스 배열 순서에 의존, 마스터/슬레이브 독립 재계산 | `src/storage/btree.c:8285-8299` (`btree_get_rkey_btid`) | RK 후보 복수 시 두 노드가 배열 순서대로 독립 선택→다른 키로 매칭→divergence (CBRD-26096 TODO 미구현) | 중간 |
| K2-1 | 보통 | USE_SBR 문이 REPLICATION=OFF 테이블을 소스로 참조하면 슬레이브가 조용히 갈라진다 | `src/query/execute_statement.c:3315-3318·3324-3343` (`is_data_repl_log_enabled`) | 대상만 검사하고 INSERT…SELECT 소스 OFF 테이블 미검사→SBR 재실행 시 소스 불일치로 대상 divergence(저자 known limitation) | 중간 |
| K3-3 | 보통 | rkcheck가 `db_is_system_class` 음수(에러)를 방어 안 해 fetch 실패 클래스를 시스템클래스로 오판·제외 | `src/executables/util_cs.c:2929-2951` (`check_repl_constraint_violations`) | `db_is_vclass`는 `<0` 방어하나 `db_is_system_class`는 미방어—음수가 truthy→continue로 위반 테이블 조용히 검사 제외 | 중간 |
| K-62 | 사소 | generate_violation_list_file_name이 localtime_r 실패 시 미초기화 버퍼 반환 | src/executables/util_cs.c:2838-2853 | localtime_r 실패 시 out 버퍼를 초기화하지 않고 반환해, 쓰레기 경로로 fopen 시도 위험(K-2와 연쇄 가능) | 중간 |
| K-67 | 사소 | 복제 옵션 매크로가 노드 NULL 미방어(주석 일부는 정확) | src/query/execute_schema.c:93-103 | IS_CREATE_STMT_SET_REPL_OPTION은 하위 필드 val을, IS_ALTER_STMT_SET_REPL_OPTION은 노드 자체를 NULL 미방어하나 정상 파싱 경로에서 트리거하는 실패 경로는 확인 못함 | 낮음 |
| K-68 | 사소 | SHOW CREATE/unload가 옵션 없는 VIEW에도 REPLICATION 출력(정책 불일치) | src/object/object_printer.cpp:1137-1144; src/parser/parser_support.c:7176-7192 | describe_class()가 클래스 종류를 구분 않고 REPLICATION 출력, pt_help_show_create_table의 return 누락으로 뷰에서도 호출됨(unload 경로는 현재 코드에서 재현 안 됨) | 중간 |
| K3-7 | 사소 | do_create_entity의 REPLICATION=OFF 분기만 break라 do_flush_class_mop 선행 상태에서 assert(error==NO_ERROR) 위반 가능 | src/query/execute_schema.c:10275-10284 | REUSE_OID로 do_flush_class_mop=true가 선행 세팅된 뒤 REPLICATION=OFF의 sm_set_class_flag가 실패하면 break로 탈출해 후처리 assert 위반(디버그 abort/릴리스 오류 마스킹), 트리거는 오류주입 필요 | 중간 |

### ② 런타임 확인 필요 항목

정적 분석으로 결함(방어 부재·불일치)은 확정했으나, 실제 발현 빈도·조건은 2노드 HA 실측이 권장되는 항목이다.

| ID | 확정된 사실 | 런타임으로 확인할 것 |
|---|---|---|
| K-17 | db_find_class NULL 미검사 + assert(NULL) 위험 | entity_name이 실제 NULL을 반환하는 do_alter 경로 존재 여부(도달성 낮다고 판단) |
| K-56 / K-58 | RK 자동 선택이 인덱스 배열 순서 의존, 무경고 재할당 | 마스터·슬레이브의 인덱스 배열 순서가 실제로 어긋나는 시나리오를 재현해 불일치 발생 여부 |
| K-52 | 멀티테이블 SBR 재실행이 OFF '대상' 테이블도 수정 | 혼합 ON/OFF 멀티테이블 UPDATE에서 슬레이브의 OFF 테이블이 실제 수정되는지 실측 |
| K-13 | snprintf 반환값 미확인 | 255자 DB명 + @localhost 조합에서 트렁케이션 후 db_restart가 엉뚱한 DB로 붙는지 재현 |
| K2-1 | SBR 소스 테이블 미검사 | 대상 ON / 소스 OFF의 INSERT…SELECT를 2노드에서 실행해 대상 테이블 divergence 실측 |
| K2-2 | OFF + RK 후보 다중 시 카탈로그 fetch 반복 | 100만 행 적재 워크로드에서 카탈로그 페이지 래치 경합·지연 정량 측정 |

### ③ develop 유래 항목 (이 기능 책임 아님)

| ID | 제목 | 위치 | 왜 "기존"인가 |
|---|---|---|---|
| K-42 | db_class 카탈로그 뷰 정의의 포맷 문자열–vararg 수동 위치 매칭 취약 | schema_system_catalog_install_query_spec.cpp:74,138 | sprintf `%d` 자리표시자를 vararg 목록과 손으로 맞추는 취약 패턴은 develop에 이미 `is_reuse_oid_class`로 동일하게 존재한다. 이번 diff는 같은 패턴으로 컬럼 하나(`is_replication_class`)를 더 추가했을 뿐, 취약성 클래스 자체를 이 기능이 도입한 것은 아니다. 동기화 뒤에도 미변경. 단 K-19/K-42가 함께 시사하듯 카탈로그 뷰 수정 방식 전반의 개선 여지는 있다. |
