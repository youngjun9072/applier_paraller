---
tags: [writeset, mysql, 자료조사, 실측]
---

# 5. FK 동작 실측 (MySQL 9.7.2)

> 목차: [[0-자료조사-목차|자료조사 목차]]



> [!warning] 실측 버전 함정 — 이력 맵 기본 용량이 버전마다 400배 다르다
> `binlog_transaction_dependency_history_size` 기본값: **8.x = 25,000** (8.0 `sys_vars.cc:4278`) vs **9.7 = 10,000,000** (`sys_vars.cc:4084`). 이력 용량을 넘는 트랜잭션은 자기 해시를 이력에 넣지 못하고 처리 후 이력을 비우므로(`rpl_trx_tracking.cc:283-304`), 8.x에서 대형 트랜잭션(예: 5만 행 = 해시 10만 개)으로 실측하면 FK 형제 사슬이 원리적으로 관측되지 않는다. 2026-08-26 대조실험에서 8.4로 측정했다가 사슬이 안 보여 이 차이를 확인했고, 9.7에서 재측정해 사슬(lc 사슬)을 재현했다. 상세: [[2. writeset_MySQL_FK_병렬화_실측_2026-08-26]].


실측 환경: MySQL 9.7.2(공식 컨테이너). 문장마다 **별개 autocommit 트랜잭션**으로 실행하고, binlog의 `last_committed` / `sequence_number` 를 확인했다.

#### 5-1. 복합 PK는 해시 1개 (설명 2-3·4-3)
`CREATE TABLE t1(a INT, b INT, c INT, PRIMARY KEY(a,b,c));` — 행 `(1,2,3)`은 a·b·c를 이어붙인 해시 **하나**로 표현된다(2-3). 컬럼별 해시가 아니다. 그래서 자식 FK가 이 PK의 일부(선행 접두사)만 참조하면 자식 해시(값 하나)와 부모 해시(값 셋)의 개수가 달라 영원히 매칭되지 않는다(4-3 부분 참조 불일치의 전제).

#### 5-2. 비표준 FK는 9.7.2에서 아예 만들 수 없다 (MySQL 9.7.2 실측) (설명 4-1·4-3)

4-1 결말·4-3에서 "MySQL이 비표준 FK를 DDL에서 막는다"고 했다. 9.7.2에서 실제로 막히는지 직접 만들어 확인했으며, 확인 결과 전부 실패한다.

`SELECT @@restrict_fk_on_non_standard_key;` = **1 (기본 ON)** 확인.

**[코드 11] 비표준 FK 생성 시도 (MySQL 9.7.2)**
```sql
CREATE TABLE t1(a INT, b INT, c INT, PRIMARY KEY (a,b,c));

FOREIGN KEY (d)   REFERENCES t1(a)     -- ❌ ERROR 6125
FOREIGN KEY (d,e) REFERENCES t1(a,b)   -- ❌ ERROR 6125
FOREIGN KEY (d)   REFERENCES t1(b)     -- ❌ ERROR 6125
-- 비유니크 보조 인덱스 참조도 동일:
CREATE TABLE p(did INT, KEY(did));
FOREIGN KEY (pid) REFERENCES p(did)    -- ❌ ERROR 6125
```
에러 원문: `ERROR 6125 (HY000): Failed to add the foreign key constraint. Missing unique key for constraint '...' in the referenced table '...'`

→ 접두사든 비유니크 보조 인덱스든 **완전한 유니크 키가 아닌 참조는 생성 자체가 거부**된다. 4-1 "결말"과 4-3의 DDL 차단이 기본 설정에서 실제로 작동함을 확인. (구버전에서 만들어져 살아남은 FK는 별개 — 4-1)

#### 5-3. FK 값이 실제로 의존성을 만든다 (MySQL 9.7.2 실측) (설명 3-2·4-2)
부모 `par(id)`, 자식 `ch(id PK, pid FK→par.id)`. 자식에 순차 INSERT 후 binlog의 `last_committed`:

**[그림 4] 자식만 순차 INSERT — last_committed**
```
seq=1  ch(1, pid=1)   last_committed=0
seq=2  ch(2, pid=1)   last_committed=1   ← pid 같음 → seq1에 의존(직렬)
seq=3  ch(3, pid=2)   last_committed=1   ← pid 다름 → seq2에 의존 안 함(병렬 가능)
seq=4  ch(4, pid=2)   last_committed=3   ← pid 같음 → seq3에 의존
```
PK(id)가 달라도 **pid(FK값)가 같은 것끼리만 직렬화**된다 → FK값이 writeset 판정에 쓰인다는 실증이자, 4-2 과직렬화의 실증.

#### 5-4. 부모를 끼우면 완전 직렬 (MySQL 9.7.2 실측) (설명 3-1·4-2)
부모 테이블을 섞은 순차 INSERT(par→ch→par→ch)는 **네 건 모두 `last_committed = seq - 1`** 로 완전 직렬화됐다. 부모 쓰기가 매번 폴백하며 이력을 비우기 때문(3-1). → 폴백이 실제로 작동함을 확인.

#### 5-5. 부모 트랜잭션이 세우는 하한선 — 앞은 무사, 뒤는 무관해도 끌려간다 (설명 3-1·4-2)

앞의 5-4는 "부모+자식만 번갈아 쓰면 다 직렬"이라는 확인이다. 그런데 폴백의 **진짜 손해**는 부모와 **아무 상관없는 다른 테이블** 트랜잭션까지 함께 직렬화된다는 데 있다. 부모보다 **앞**에 커밋된 것과 **뒤**에 커밋된 것의 운명이 갈리는 걸 한 예시로 본다.

**셋업**: 서로 독립인 세 테이블 **A · B-Parent · C**. 그중 **B-Parent만 부모**(B-Child1·B-Child2가 B-Parent를 FK로 참조; A·C를 참조하는 자식은 스키마에 없음). 각 쓰기는 **별개 트랜잭션**이다 — writeset은 트랜잭션 단위로 만들어지고 순서/병렬 판정은 트랜잭션들 **사이**의 문제라서, 한 트랜잭션 안이면 애초에 순서 문제가 없다. 그리고 셋 다 **id=1을 수정**한다고 하자(값이 같아도 겹치지 않음을 보이기 위해).

**[예시] 부모가 중간 — 앞의 A는 무사, 뒤의 C는 끌려감**
```
seq=1  T1: A의 id=1 수정               ← B-Parent와 무관 (부모보다 앞)
seq=2  T2: B-Parent의 id=1 수정        ← "참조당하는 부모" → 폴백
seq=3  T3: C의 id=1 수정               ← B-Parent와 무관 (부모보다 뒤)
seq=4  T4: B-Child1 삽입(FK→B-Parent.id=1)  ← 진짜 자식
seq=5  T5: B-Child2 삽입(FK→B-Parent.id=1)  ← 진짜 자식
```

해시로 보면 (pke에 **인덱스명+db+테이블명+값**이 들어가므로):

| Tx | 만드는 해시 | 비고 |
|-----|------------|------|
| T1 | H(PRIMARY, A, 1) = H_A | 값이 같은 1이어도 테이블명이 달라 서로 다름 |
| T2 | H(PRIMARY, B-Parent, 1) = **H_B** | + 부모 플래그 켜짐 |
| T3 | H(PRIMARY, C, 1) = H_C | 〃 |
| T4 | 자기 PK 해시 + **FK 해시 = H_B** | 자식 FK 해시는 부모 키 해시와 같은 모양(3-2) |
| T5 | 자기 PK 해시 + **FK 해시 = H_B** | 〃 |

→ **진짜 충돌은 H_B를 가진 {T2, T4, T5}뿐.** A·C는 같은 id=1을 수정해도 아무와도 안 겹친다. 참고로 T4·T5는 **서로 다른 행을 삽입**하므로 논리적으로는 서로 충돌이 없다 — 둘 다 "부모(T2) 뒤"이기만 하면 되고, **서로는 병렬이 바람직**하다. (단 부모 T2와는 절대 병렬 불가 — 부모 행이 아직 안 만들어졌으면 자식 FK가 실패한다.)

실제 `commit_parent`는 이렇게 나온다:

| seq | Tx | writeset 사용? | commit_parent | 기다리는 대상 |
|-----|-----|---------------|---------------|-----------|
| 1 | T1 (A) | ✅ | 0 (이력 비어 있음) | — (선두) |
| 2 | T2 (B-Parent) | ❌ 폴백 | 커밋 순서 기본값 → seq1 + **`history_start`를 seq2로 올림 + 이력 clear(H_A도 지워짐)** | T1 |
| 3 | T3 (C) | ✅ | `last_parent`가 seq2에서 시작(하한선) → seq2 | **T2 (무관한데 끌려감!)** |
| 4 | T4 (B-Child1) | ✅ | seq2 (T2의 H_B는 이력에 없음 → 하한선이 잡음) | T2 (맞는 결과, 단 해시 매칭이 아니라 하한선 덕분) |
| 5 | T5 (B-Child2) | ✅ | seq4 (T4가 넣은 H_B에 매칭) | **T4 (형제끼리도 직렬! = 4-2 과직렬화)** |

→ 파동: **`T1 | T2 | T3 T4 | T5`**

**실측 확인 (MySQL 9.7.2)**: 위 시나리오 그대로(무관 ta → 부모 bparent → 무관 tc → 자식 bchild1 → 자식 bchild2, 전부 id=1 대상) 실행한 binlog 결과 — `last_committed` = **T1=0, T2=1, T3=2, T4=2, T5=4** 로 분석 예측과 정확히 일치. 무관한 T3가 하한선(2)에 걸리는 것, T4가 해시 매칭 없이 하한선으로 부모 뒤에 서는 것, T5만 T4에 매칭되는 것(형제 직렬)까지 모두 재현됐다.

> **주의 — `T1 | T2` 경계는 T1이 세운 하한선이 아니다.** T1은 폴백하지 않으므로 하한선·clear를 만들지 않는다. 이 경계는 **폴백한 T2 자신이 받는 커밋 순서 값** 때문이다: 커밋 순서 추적기는 `commit_parent = trn_ctx->last_committed`(= 이 트랜잭션이 커밋을 시작할 때 이미 커밋 완료돼 있던 가장 최근 트랜잭션)로 계산하는데, 순차 커밋에서는 그게 직전 T1이다. 마스터에서 T1·T2가 같은 그룹 커밋이었다면 T2는 T1과 병렬일 수도 있다(3-1 "폴백 ≠ 직렬").

이 한 예시에 손해가 세 겹으로 보인다:
1. **부모 자신(T2)**: A와 무관한데도 커밋 순서 폴백이라 T1을 기다린다(보수적).
2. **부모 뒤의 무관한 C(T3)**: 하한선에 걸려 T2를 기다린다. 반면 부모보다 **앞**에 커밋된 A(T1)는 아무 피해 없다 — **폴백 손해는 "부모 뒤에 오는 무관한 트랜잭션 수"에 비례**한다(위치가 운명을 가른다).
3. **형제 자식끼리(T4→T5)**: 서로 충돌이 없는데도 같은 H_B를 공유해 체인으로 직렬된다(4-2 #110071). "부모 뒤"라는 필요한 순서를 넘어 **불필요한 형제 직렬**까지 생긴다.

**왜 코드 때문인가 — "낮춤(min) 모델"로 보면 명확하다.** 커밋 시 모든 트랜잭션은 두 단계를 지난다([코드 3]·[코드 8]):
```c
// 1단계: commit-order가 보수적 시작값을 배정 (모든 트랜잭션 공통)
//        순차 커밋이면 ≈ 직전 seq ("직전 것 기다려" — 느릴 뿐 항상 안전)
commit_parent = trn_ctx->last_committed;

// 2단계: writeset이 그 값을 "낮춰서" 병렬을 만든다 — 올리는 코드는 없다
int64 last_parent = m_writeset_history_start;          // 낮춤의 바닥 = 하한선
... 이력에서 내 해시와 겹친 상대 중 가장 최신 seq → last_parent ...
commit_parent = std::min(last_parent, commit_parent);  // ★ min = 낮춤뿐
```
이 모델로 부모 T2가 남기는 흔적 둘을 다시 읽으면:
- **폴백** = T2 자신이 **2단계(낮춤)를 통째로 건너뜀** → 보수 시작값(seq1)이 그대로 최종값. `T1 | T2` 경계의 정체는 장벽이 아니라 **낮춤 생략**이다.
- **하한선 + clear** = T2가 커밋 처리 끝에 남기는 것:
```c
if (exceeds_capacity || !can_use_writesets) {   // 부모(has_related_foreign_keys)면 여기
  m_writeset_history_start = seq;   // ① 하한선을 현재 seq로 올림 → 이후의 "낮춤 한도"
  m_writeset_history.clear();       // ② 이력 비우기
}
```
  다음 트랜잭션들의 `last_parent`가 이 하한선에서 시작하므로 `commit_parent`는 그 밑으로 못 내려간다. **해시가 겹치든 말든** T3·T4는 최소 seq2에 매달린다 — 진짜 장벽은 이 **하한선 하나**이고, **뒤쪽(이후 트랜잭션)으로만** 작동한다.

**대조 — 만약 T2가 폴백하지 않았다면** (하한선 0 유지·이력 보존이라고 가정하고, 하한선의 효과만 분리 확인하는 사고실험):

| seq | Tx | 1단계 시작값 | 2단계 낮춤 | 최종 |
|-----|-----|------------|-----------|------|
| 3 | T3 (C) | 2 (직전 T2) | H_C 아무와도 안 겹침, 바닥 0 → **0까지 낮아짐** | **0 → T1·T2와 병렬** |

→ 실제(하한선 있음)의 T3=seq2와 비교하면, **T3가 끌려간 이유가 오로지 하한선(낮춤 한도) 때문**임이 분리 확인된다.

(폴백 없이 writeset 매칭만으로 처리했을 때의 전체 파동 비교는 [[3. writeset_v2_POC_설계]] 참조.)

#### 5-6. 그런데 이 폴백은 "없어선 안 된다" — #109923 반증 (설명 4-1)

폴백이 무관한 트랜잭션까지 직렬화하는 손해가 있다고 해서 그냥 없애면 정합성이 깨진다. 그 반증이 **Bug #109923**이다.

이슈 원문 증상(그대로):
> *"...the `last_committed` of the child table's row will be smaller than it should be, causing SQL thread aborted."*
> (자식 행의 `last_committed`가 실제보다 작게 계산되어 SQL 스레드가 중단된다)

재현 테이블(원문):
```sql
CREATE TABLE parent (did INT, KEY (did)) ENGINE=INNODB;              -- PK·UNIQUE 없음, 보조 인덱스뿐
CREATE TABLE child  (id INT PRIMARY KEY, parent_id INT,
                     INDEX par_ind (parent_id),
                     FOREIGN KEY (parent_id) REFERENCES parent(did)) ENGINE=INNODB;
```

부모에 **PK도 UNIQUE도 없어서** 삼중으로 폴백이 안 걸린다:
1. 자식 FK 해시 = 참조 대상(did)이 비유니크라 **생성 스킵**(3-2, `unique_constraint_name.length==0`).
2. 부모 해시 = PK 없어 `add_pke` 본 블록을 **통째로 스킵** → 아예 안 만들어짐.
3. 폴백 플래그 = 그 PK-필요 블록 안에 있어 **안 켜짐**(4-1) → 의존성 추적 단계에서 `history_start`도 안 올라가고 이력 clear도 안 됨.

→ 부모를 뒤에 오는 자식보다 앞에 붙들어 둘 **하한선이 없다** → 자식의 `commit_parent`가 부모보다 작게 나옴 → 자식이 부모보다 **먼저** 적용 → `HA_ERR_NO_REFERENCED_ROW`(참조할 부모 없음).

**즉 "부모를 기점으로 하한선을 세우고 이력을 비우는 폴백 처리(`history_start` 갱신 + clear)"가 빠지면 순서가 깨진다는 반증이다.** 그래서 이 처리는 손해가 있어도 **정합성상 필수**다. (용어 주의: 이슈 원문엔 "clear/history/장벽" 같은 표현이 없다. 이슈는 `last_committed`가 작게 계산됨으로만 서술하고, `clear`/COMMIT_ORDER 되돌림은 [코드 8]과 WL#9556 FR13의 표현이다.)

#### 5-7. PK 없는 부모 + UNIQUE 참조 — 자식이 부모를 기다리지 않는다 (MySQL 9.7.2 실측) (설명 4-1)

4-1 "잔존 확인"의 실측. 부모의 PK 유무만 다른 동일 4커밋을 두 벌 돌려 `last_committed`를 비교했다.

```sql
-- 실험군: PK 없는 부모 (UNIQUE만) — 9.7.2에서도 FK 생성이 허용된다(표준 참조라서)
CREATE TABLE parent2 (did INT, name VARCHAR(10), UNIQUE KEY (did));
CREATE TABLE child2  (id INT PRIMARY KEY, did INT, FOREIGN KEY (did) REFERENCES parent2(did));
-- 대조군: PK 있는 부모
CREATE TABLE parent3 (did INT PRIMARY KEY, name VARCHAR(10));
CREATE TABLE child3  (id INT PRIMARY KEY, did INT, FOREIGN KEY (did) REFERENCES parent3(did));

-- 각 벌: FLUSH BINARY LOGS 후 순차 4커밋 (autocommit, 한 문장 = 한 트랜잭션)
INSERT INTO ta VALUES (1);            -- T1 무관
INSERT INTO parent_ VALUES (7,'c');   -- T2 부모 행 쓰기
INSERT INTO tc VALUES (1);            -- T3 무관
INSERT INTO child_ VALUES (3, 7);     -- T4 자식 (방금 그 부모 행 7을 참조)
```

binlog의 (sequence_number, last_committed) 결과:

| seq | 트랜잭션 | 실험군 (PK 없음) | 대조군 (PK 있음) |
|---|---|---|---|
| 1 | T1 무관 | 0 | 0 |
| 2 | T2 부모 | 1 (직전 커밋 = missing_keys 폴백의 흔적) | 1 |
| 3 | T3 무관 | 1 (하한선 없음 — clear 없는 폴백이라 안 끌려감) | **2** (부모 폴백 하한선에 끌려감 — 5-5와 동일 패턴) |
| 4 | **T4 자식** | **1 — 부모(seq 2)를 기다리지 않음** | **2 — 하한선 덕에 부모 뒤** |

판정: 대조군에서는 부모 폴백(하한선+clear)이 자식을 부모 뒤(2)에 세운다. 실험군에서는 부모가 [코드 4]의 대문(PK 게이트)에서 걸러져 **해시도 폴백 플래그도 받지 못하므로**, 자식의 FK 해시가 이력에서 매칭할 대상이 없고 `T4.last_committed(1) < T2.seq(2)` — 리플리카가 자식을 부모보다 먼저 적용할 수 있다. #109923과 같은 증상이, 이번에는 업그레이드 레거시가 아니라 **지금도 합법인 DDL**로 재현된 것이다.

(각주: 바닥값이 0이 아니라 1인 것은 `FLUSH BINARY LOGS` 회전이 이력 floor를 1로 세우는 부수 효과로, 판정과 무관하다.)

---

