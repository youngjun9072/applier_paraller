---
tags: [writeset, mysql, 자료조사, fk]
---

# 3. FK(외래키) 처리 — 메커니즘

> 목차: [[0-자료조사-목차|자료조사 목차]]


FK가 writeset에서 영향을 주는 코드는 한 곳이 아니라 두 곳에 나뉘어 있다. 하나는 **의존성 추적 단계**다. 트랜잭션이 부모 테이블, 즉 다른 테이블의 FK가 참조하는 테이블의 행을 썼다면, 그 트랜잭션은 해시 대조와 무관하게 writeset 낮춤을 포기하고 커밋 순서 값을 그대로 쓰며 이력을 비운다(3-1). 다른 하나는 **추출 단계**다. 자식 행을 쓸 때, 그 행이 부모를 가리키는 FK 값을 부모 키와 같은 모양으로 해시해 write set에 함께 넣는다(3-2).

주의할 점은 이 둘을 일으키는 트랜잭션이 서로 다르다는 것이다. 추출 쪽은 **자식 테이블을 쓰는 트랜잭션**에서, 의존성 추적 쪽은 **부모 테이블을 쓰는 트랜잭션**에서 일어난다. 간단한 예시로 이 둘이 언제 일어나는지 보자.

```sql
CREATE TABLE parent (id INT PRIMARY KEY);
CREATE TABLE child  (id INT PRIMARY KEY, pid INT,
                     FOREIGN KEY (pid) REFERENCES parent(id));

T1: UPDATE parent SET ... WHERE id = 7;    -- 부모 행을 쓰는 트랜잭션
T2: INSERT INTO child VALUES (100, 7);     -- 자식 행 삽입 (parent 7을 가리킴)
```

```
seq=1  T1 (parent id=7 갱신)
        실행 중: H(parent, 7) 해시 생성. "참조당하는 부모" 표시도 켬
        커밋 시: 표시를 보고 writeset 포기. 방금 만든 해시를 이력에 넣지 못하고,
                이력을 비우며 하한선을 1로 올림              ← 3-1의 일
seq=2  T2 (child 100 삽입, pid=7)
        실행 중: 자기 PK 해시 + FK 해시 H(parent, 7) 생성    ← 3-2의 일
                (부모 키 해시와 같은 값이 되게 만든 것)
        커밋 시: 이력에서 H(parent, 7)을 찾지만 없다(T1이 지웠으므로).
                결국 하한선 때문에 T1 뒤에 선다
```

이 예시가 보여주듯, 자식이 부모 뒤에 서는 결과 자체는 맞지만 그 이유가 FK 해시의 대조 성공이 아니다. 부모를 쓴 트랜잭션은 충돌을 발견해서가 아니라 **부모를 썼다는 표시만으로** 포기하며, 그 과정에서 부모 해시가 이력에서 사라지므로 3-2이 심어 둔 매칭은 정작 부모와 성사되지 않는다. 이 엇갈림이 3장의 핵심이며, 상세한 의미는 3-2 끝에서 다시 본다. 이제 둘을 나눠 본다.

### 3-1. 의존성 추적 단계 — 부모 테이블에 쓰기가 있으면 writeset 포기
추출 단계의 add_pke는 테이블이 **부모**(= 다른 테이블의 FK가 이 테이블을 참조, `foreign_key_parents > 0`)이면 `has_related_foreign_keys` 플래그를 켜 둔다(코드는 3-2의 [코드 7] 끝). 이 플래그가 켜진 트랜잭션은 의존성 추적 단계에서 writeset을 못 쓰게 된다.

호출 시점은 의존성 추적 단계다. 커밋 처리 중, binlog에 트랜잭션을 써 넣는 함수가 GTID 이벤트를 만들기 직전에 [코드 3]인 get_dependency를 부르고, 그 안의 writeset 추적기 본문이 [코드 8]이다.

```
트랜잭션 COMMIT  (커밋 처리 중 = 의존성 추적 단계)
 └ MYSQL_BIN_LOG::write_transaction()  (binlog.cc)
     └ Transaction_dependency_tracker::get_dependency()     ← [코드 3]
         ├ 커밋 순서 추적기: 보수값 배정
         └ writeset 추적기: 낮춤 또는 폴백                   ← [코드 8]이 이 본문
```

**[코드 8] 의존성 추적 — 부모 테이블에 쓰기가 있으면 writeset 포기(폴백)**
```c
bool can_use_writesets =
     (writeset 있음 || has_missing_keys || 빈트랜잭션)
  && !is_create_table_as_query_block(thd)          // CTAS 아님
  && binlog_format == ROW                          // ROW 포맷
  && !ws_ctx->get_has_related_foreign_keys()       // ★ 참조당하는 부모를 건드리지 않음
  && !ws_ctx->was_write_set_limit_reached();       // 크기 한도 이내

if (can_use_writesets) {
  int64 last_parent = m_writeset_history_start;
  for (auto h : *writeset) {                        // 내 해시들
    auto it = m_writeset_history.find(h);           // 최근 커밋 이력에서 겹치는지
    if (it != end) {
      if (it->second > last_parent && it->second < seq) last_parent = it->second;
      it->second = seq;                             // 이력 갱신
    } else if (!exceeds_capacity) {
      m_writeset_history.insert({h, seq});
    }
  }
  commit_parent = min(last_parent, commit_parent);  // ★ 겹치는 것만 의존 → 나머진 병렬
}

if (exceeds_capacity || !can_use_writesets) {        // 폴백(또는 이력 초과)
  m_writeset_history_start = seq;                     // 이후 트랜잭션은 이 지점보다 앞 못 감
  m_writeset_history.clear();                         // 이력 초기화 = "장벽"
}
```

동작 요약:
- **일반 트랜잭션**: writeset으로 `commit_parent`를 낮춰 **병렬**.
- **참조당하는 부모를 건드리는 트랜잭션**: `can_use_writesets=false` → writeset 개선을 건너뜀 → 커밋 순서 기본값 유지 + **이력 clear(장벽)**. 이 장벽 때문에 뒤따르는 자식이 이 부모보다 앞서 적용될 수 없다(= 순서 안전).
- 코드 주석의 근거: *"참조되는 테이블의 변경이 다른 테이블로 cascade 될 수 있으니 커밋 순서로 되돌려 정합성을 지킨다."*
- **주의**: 이 폴백은 **동작 종류(CASCADE/RESTRICT/SET NULL) 무관**하게 "부모를 건드리면" 무조건이다. 트랜잭션 단위(그 부모를 건드릴 때만). 그리고 **폴백 ≠ 직렬** — 커밋 순서 병렬성(마스터에서 같이 커밋된 것끼리)은 남는다. 다만 그 상한이 마스터 커밋 동시성에 묶인다.

**clear(하한선 올림 + 이력 비우기)는 FK 전용이 아니다** — [코드 8]의 `exceeds_capacity || !can_use_writesets` 분기로 들어오는 모든 경우에 실행된다:
- **FK 부모**(`has_related_foreign_keys`) — 이 절의 주제.
- **이력 용량 초과**(`exceeds_capacity`) — 이력 맵은 크기 제한이 있는 유한 메모리라, 꽉 차면 더 오래된 의존을 추적할 수 없어 "그 이전과는 전부 의존"으로 보수화해야 한다.
- **빈 writeset(DDL 등) · CTAS · 비ROW 포맷** — 영향을 행 해시로 표현할 수 없는 경우.
- binlog **rotate** 시에도 `rotate()`가 같은 처리를 한다.

예외 하나: **has_missing_keys(PK 없는 테이블)는 폴백해도 clear 하지 않는다** — 소스 주석: *"revert to COMMIT_ORDER, update and **not reset history**"* (그 테이블을 참조하는 트랜잭션도 어차피 폴백하므로 불필요). → clear는 "폴백이면 무조건"이 아니라 **필요한 경우에만 쓰는 선별 장치**다.

### 3-2. 추출 단계 — 자식의 FK 값을 "부모 키처럼" 해시
자식 행을 쓸 때, 그 FK가 가리키는 값을 **부모의 유니크 인덱스 이름으로** 해시한다. 그러면 부모 행의 그 키 해시와 **같은 값**이 된다.

"같은 값"의 효과는 별도 장치가 아니라 3-1에서 본 의존성 추적의 이력 조회에서 그대로 나타난다. 커밋하는 트랜잭션은 자기 해시들을 이력에서 하나씩 찾아 **매칭된 것들 중 가장 큰 seq**를 `last_parent`로 잡고, `commit_parent = min(last_parent, 커밋 순서 값)`으로 `last_committed`를 계산한다(`rpl_trx_tracking.cc:290-317`). 부모 트랜잭션이 이 해시를 먼저 이력에 실어 뒀다면 자식의 조회에서 부모의 seq가 나오고, min을 거쳐도 자식의 `last_committed`는 **부모 seq 아래로 내려가지 않는다** — 리플리카는 부모가 끝나기 전에 자식을 시작하지 않는다. 즉 "부모-자식이 해시로 이어진다"의 실체는 이 `last_committed` 계산이다.

호출 시점은 추출 단계다. 자식 행이 쓰일 때 [코드 1]의 add_pke 안에서 실행되는 인라인 블록이며, 별도 함수가 아니다.

```
자식 행 INSERT/UPDATE/DELETE  (문장 실행 중 = 추출 단계)
 └ 행 이벤트를 binlog 캐시에 기록하며 add_pke() 호출        ← [코드 1]
     ├ PK/UNIQUE 루프 → generate_hash_pke()                (2장)
     └ /* Foreign keys handling. */ 블록                    ← [코드 7]이 이 블록
         └ generate_hash_pke()
```

**[코드 7] FK 추출 — 자식 FK를 부모 키처럼 해시**
```c
if (!(thd->variables.option_bits & OPTION_NO_FOREIGN_KEY_CHECKS) &&
    table->s->foreign_keys > 0) {                 // 이 테이블이 FK를 가진 "자식"
  for (uint k = 0; k < table->s->foreign_keys; k++) {

    // 참조 대상이 유니크가 아니면(=참조 유니크 인덱스 이름이 없으면) 건너뜀
    if (fk[k].unique_constraint_name.length == 0) continue;

    pke.clear();
    pke.append(fk[k].unique_constraint_name);       // 참조하는 "부모 유니크 인덱스 이름"
    pke.append(SEP);
    pke.append(fk[k].referenced_table_db);          // 부모 DB
    pke.append(SEP); pke.append(len(referenced_table_db));
    pke.append(fk[k].referenced_table_name);        // 부모 테이블
    pke.append(SEP); pke.append(len(referenced_table_name));

    for (each FK 컬럼) {
      Field *field = (자식에서 그 FK 컬럼);
      if (field->is_null(ptrdiff)) continue;        // NULL FK는 제외
      size_t max_length = strnxfrmlen(cs, field->pack_length());   // ★ 컬럼 전체 길이 기준
      length = field->make_sort_key(pk_value, max_length);         // (2-인자)
      pke.append(pk_value, length);
      pke.append(SEP); pke.append(std::to_string(length));
    }
    generate_hash_pke(pke, thd);   // 자식 FK값을 부모 키 해시와 "같은 모양"으로 만들어 넣음
  }

  if (table->s->foreign_key_parents > 0)            // ★ 이 테이블이 "참조당하는 부모"이면
    ws_ctx->set_has_related_foreign_keys();         //    의존성 추적 쪽 폴백 플래그를 켬 (3-1)
}
```

포인트:
- **자식 FK 해시 = 참조 유니크 인덱스이름 + 부모 db/테이블 + 자식 FK값** → 부모의 그 키 해시와 매칭되게 설계됨. (예: 부모 삭제와 자식 삽입이 같은 부모키 해시로 충돌 → 순서 잡힘)
- 참조 대상이 **유니크가 아니면 해시 자체를 안 만든다**(`continue`).
- FK 컬럼 NULL은 제외(참조 없음).

> **꼭 짚을 점 — "FK 해시 매칭 장치는 있지만 지금은 안 쓰인다"**
> 위에서 봤듯 자식 FK 해시는 **부모 키 해시와 같은 값이 되도록** 만들어져 있다(= 충돌검사용 장치). 그런데 부모를 쓰는 트랜잭션이 폴백하며(3-1) `history.clear()`로 **부모 해시를 이력에서 지워버린다.** 그래서 자식이 부모 해시와 **직접 매칭할 대상이 이력에 없어**, 현재 자식이 부모 뒤로 가는 것은 이 해시 매칭이 아니라 **장벽(`history_start` 바닥)** 덕분이다.
> → 즉 **"부모키 == 자식FK 해시" 장치는 존재하지만, clear 때문에 실제 순서잡기에는 쓰이지 않는다.** 이 폴백/clear를 없애면 부모 해시가 이력에 남아 **그 매칭이 비로소 순서잡기의 주역**이 된다(적용 설계 논의는 [[3. writeset_v2_POC_설계]]).

### 3-3. 부모 키 해시 vs 자식 FK 해시 — 정규화가 미묘하게 다르다
같은 값을 넣어도 **정규화(값을 비교 가능한 바이트열로 바꾸는 것)의 절단 길이**가 부모 쪽과 자식 쪽에서 다르다.

"다르다"의 실체는 별도 구현이 아니다. `make_sort_key`의 3-인자판은 셋째 인자로 "몇 **문자**까지 정규화할지"(절단 위치)를 받는데, 문자열 계열(Field_string/varstring/blob)만 이걸 실제로 구현하고, **2-인자판은 같은 구현을 컬럼 전체 문자 수(`char_length()`)로 부르는 래퍼**다(`field.cc:6296-6298`). 문자열이 아닌 타입은 반대로 3-인자판이 셋째 인자를 무시하고 2-인자판을 그대로 부른다(`field.h:1349-1351`). 어느 쪽이든 **구현은 하나이고, 다른 것은 "어디까지 자르느냐"라는 인자뿐**이다: 부모의 유니크 키 해시는 인덱스에 정의된 길이(프리픽스면 그 문자 수)로 자르고, 자식 FK 해시는 컬럼 전체 길이로 정규화한다.

**[코드 9] 부모 키 해시 vs 자식 FK 해시 — 정규화 차이**
```c
// 부모: 자기 유니크 키 해시 (2장)
size_t key_length = key_part[i].length;                 // 인덱스에 정의된 길이(프리픽스 가능)
make_sort_key(v, strnxfrmlen(cs, key_length), key_length/mbmaxlen);   // 3-인자

// 자식: FK 해시 (3-2)
make_sort_key(v, strnxfrmlen(cs, field->pack_length()));              // 2-인자, 컬럼 전체 길이
```
- 컬럼 전체를 키로 쓰는 평범한 경우엔 결과가 같아 매칭된다.
- 프리픽스 인덱스는 부모가 **전체 길이 표현(②, 2-5)도 함께 발행**하므로, 자식 FK(전체 길이)와 그 ②가 매칭된다. (근거: `add_pke`가 프리픽스 키를 만나면 — 정규화 버퍼 길이가 컬럼 전체 기준과 달라지는 것으로 감지, `rpl_write_set_handler.cc:1016-1018` — 두 번째 패스에서 컬럼 전체 길이 기준의 pke를 하나 더 만든다 :1002-1014.)
- 하지만 뒤(3-5)에서 보듯 **부분/비표준 참조**에서는 값 개수 자체가 달라 아예 못 맞는다.

### 3-4. 왜 부모와의 의존성을 writeset 매칭으로 보지 않고 폴백하는가

3-2의 장치대로라면 부모 키 해시와 자식 FK 해시가 같은 값이므로, 부모가 커밋할 때 자기 해시를 이력에 남기고 자식이 그것을 대조하게 두면 폴백 없이도 순서를 잡을 수 있어 보인다. 그런데 MySQL은 그 길 대신 3-1의 폴백을 택했다.

이유를 이해하려면 충돌검사의 전제부터 봐야 한다. writeset 충돌검사가 병렬을 보장하는 것은 **모든 트랜잭션의 변경 내역이 빠짐없이, 서로 비교 가능한 해시로 기록될 때뿐**이다. "안 겹쳤다"는 판정은 기록이 완전할 때만 "정말 독립"을 뜻한다. FK가 있으면 이 전제가 세 가지 방식으로 깨질 수 있다.

| 구멍        | 무엇이 깨지나                                                                | 발생 조건                                                 |
| --------- | ---------------------------------------------------------------------- | ----------------------------------------------------- |
| ① 변경분 누락  | cascade가 엔진 내부에서 자식 행을 바꿔, 그 트랜잭션의 writeset이 실제 변경보다 작아진다              | 8.x, 그리고 9.x를 native 모드로 기동한 경우 (기본 모드에서는 발생 안 함, 아래) |
| ② 식별 키 부재 | PK와 UNIQUE가 없는 테이블은 해시를 만들 수 없어 비교 자체가 불가능하다                           | 스키마에 따라 상시                                            |
| ③ 해시 불일치  | 비유니크 키나 복합 키 일부를 참조하는 FK는 부모 키 해시와 값 개수·모양이 달라 영원히 겹치지 않는다(3-3, 4-3) | 레거시 스키마 (9.x 신규 생성은 DDL에서 차단, 4-1 결말)               |

**① 변경분 누락 — cascade.** [코드 8] 위의 소스 주석이 밝히는 공식 이유다. 부모 행의 변경은 FK의 ON DELETE/UPDATE 규칙을 따라 다른 테이블의 행까지 함께 바꿀 수 있고, 주석은 "커밋 순서로 되돌리고 이력을 비워 정합성을 지킨다"고 적는다. 다만 이 누락이 실제로 일어나는지는 FK 실행 계층에 따라 갈린다. 9.7에는 FK 실행 모드가 둘 있다(`innodb_native_foreign_keys`, read-only 전역, 기본 OFF, `sys_vars.cc:7685`).

> **용어 — 두 가지 FK 실행 모드.** "모드"는 FK 제약(검사와 cascade)을 누가 실행하느냐의 선택이다. 서버 기동 시 결정되며 런타임 변경은 불가하고, 어느 모드였는지는 행 이벤트마다 플래그(`USE_SQL_FOREIGN_KEY_F`)로 함께 복제되어 리플리카가 일관되게 처리한다.
>
> **SQL 계층 모드(OFF, 9.7 기본)** — 부모를 DELETE하면 cascade로 지워질 자식 행들을 서버(`sql_foreign_key_constraint.cc`)가 직접 한 행씩 지운다(`ha_delete_row` 경유). 서버 계층을 지나가므로 자식 행 변경이 binlog에 독립 행 이벤트로 기록되고, 그 길목의 `add_pke()`도 타서 자식 행의 writeset 해시가 만들어진다. 리플리카는 마스터가 보낸 자식 이벤트를 그대로 적용한다(재실행 없음).
>
> **native 모드(ON, 8.x까지의 유일한 방식)** — 부모 DELETE를 InnoDB에 넘기면 cascade 자식 삭제를 엔진이 내부에서 처리한다. 서버 계층을 안 거치므로 자식 행 변경이 binlog에 기록되지 않고 writeset 해시도 만들어지지 않는다. 리플리카는 부모 이벤트만 받고, 자기 엔진이 cascade를 재실행해 자식을 맞춘다.
>
> native에서 writeset이 줄어드는 건 writeset이 만들어지는 **위치** 때문이다. writeset은 트랜잭션이 만진 행을 전역 장치가 모아주는 게 아니라, 서버가 행 변경 하나를 처리하는 길목 — 행 핸들러 호출이 서버 계층을 지나 binlog 행 이벤트를 기록하는 지점 — 에서 `add_pke()`가 불려 그때그때 쌓인다. 엔진 내부 cascade는 이 길목을 아예 안 지나가 "자식 행이 바뀌었다"는 행 단위 통지 자체가 없고, 통지가 없으니 해시가 만들어질 계기도 없다. 같은 "부모 삭제 + cascade 자식 100건"이라도 SQL 계층 모드에선 writeset이 101행 몫, native에선 부모 1행 몫만 남는다. 이 줄어듦은 최적화가 아니라 **못 본 것**이다 — 트랜잭션이 실제로 자식 행들을 바꿨는데 writeset은 모르니 자식을 건드리는 다른 트랜잭션과의 충돌을 해시 매칭으로 못 잡는다(= 구멍 ①). binlog에 자식 이벤트가 없는 것과 writeset에 해시가 없는 것은 같은 원인의 두 증상이다.
>
> 3-6의 실측은 이 변수를 건드리지 않았으므로 **기본값(SQL 계층 모드)에서 측정**된 결과다.

전통적인 InnoDB 내장 방식(위 변수 ON, 8.x의 고전 동작)에서는 cascade로 지워지는 자식 행이 엔진 내부에서 처리된다(`row_ins_foreign_check_on_constraint`, row0ins.cc:1011 → `row_update_cascade_for_mysql`, row0mysql.cc:2562). 서버 계층의 handler 래퍼를 거치지 않으므로 binlog 행 이벤트에도, add_pke에도 잡히지 않는다. 자식 변경이 binlog에 없으니 리플리카는 부모 DELETE 이벤트를 적용하는 순간 자기 엔진이 cascade를 재실행해 자식을 지운다. 그 재실행이 올바르려면 부모 이벤트와, 자식 테이블을 만지는 다른 트랜잭션들의 순서가 반드시 지켜져야 하고, 폴백이 그 순서를 보장하는 안전판이었다.

**[예시] 대조 — T1이 폴백과 clear를 하지 않았다고 가정하면 (InnoDB 내장 모드)**
```
자식 child(id PK, pid FK→parent, ON DELETE CASCADE)

seq=1  T0: INSERT child(100, 7)     → 이력에 H(child,100) 등록, 주인 = T0
seq=2  T1: DELETE parent(7)         → cascade가 child(100)도 삭제
                                       (엔진 내부 실행이라 이력에 흔적이 안 남음)
seq=3  T2: INSERT child(100, 8)     → 마스터에선 cascade 뒤라 정상 성공 (id 재사용)
```
T2가 이력에서 H(child,100)을 찾을 때 주인은 여전히 T0다. T1의 cascade 삭제가 이력에 남지 않았기 때문이다. 그러면 T2의 commit_parent가 T0 언저리까지 낮아져 T1과 병렬로 스케줄될 수 있고, 리플리카에서 T2의 삽입과 T1의 부모 삭제(및 그에 딸린 cascade 재실행)가 뒤엉키면 마스터에서 살아남은 행이 리플리카에서는 지워지는 불일치가 생긴다. 하한선과 clear는 이력에 남지 못한 이 변경분을 대신해, T1 이전과는 아무도 병렬할 수 없다는 일괄 제한으로 막는 장치다.

그런데 9.7의 기본은 SQL 계층 FK다(위 변수 OFF → `OPTION_USE_SQL_FOREIGN_KEY_HANDLING`, sql_class.cc:911). 이 모드에서 cascade 자식 삭제는 서버의 `ha_delete_row`를 거치므로(`sql_foreign_key_constraint.cc:1040`), 자식 행이 **독립된 행 이벤트로 binlog에 기록되고 add_pke도 통과해 writeset에 담긴다.** 리플리카는 마스터가 펼쳐 보낸 자식 이벤트를 FK 체크를 끈 채 부모보다 먼저 적용한다(소스 주석: "child binlog is applied before parent at replica during CASCADE ... so FK checks are skipped", `sql_foreign_key_constraint.cc:1035-1039`). 즉 9.7 기본 모드에서 ①은 메워져 있다.

**② 식별 키 부재.** PK와 UNIQUE가 없는 테이블은 해시를 만들 수 없으므로 충돌검사의 대상이 될 수 없다. 이 구멍의 처치는 부모 폴백이 아니라 **missing_keys 폴백**이다. 그런 테이블을 쓰는 트랜잭션은 전부 min(낮춤) 한 줄만 건너뛰고 커밋 순서 값을 유지하므로, 그 테이블을 만지는 트랜잭션들끼리는 커밋 순서로 상호 순서가 유지된다. 전원이 같은 처지라 남을 막을 필요가 없어 하한선과 clear는 하지 않는다(3-1의 예외 항목). 주의할 점 하나: **부모 테이블이 이 상태이면 ①③용 처치인 부모 폴백이 발동조차 못 한다**(플래그가 PK-필요 블록 안에 있으므로). 이것이 4-1(#109923)의 구멍이다.

**③ 해시 불일치.** FK가 부모의 비유니크 키나 복합 키의 선행 일부만 참조하면, 자식 FK 해시와 부모 키 해시는 값 개수와 모양이 달라 영원히 만나지 못한다(3-3). 복합 키 자체가 문제인 것은 아니다. `PRIMARY KEY(a,b,c)`를 통째로 참조하면 양쪽 모두 세 값을 이어붙인 해시 하나라 정상 매칭되고(2-3), **일부만 참조할 때**(예: `REFERENCES t1(a)`) 부모는 세 값의 해시, 자식은 한 값의 해시가 되어 어긋난다. 이런 스키마에서는 매칭이 원리적으로 불가능하므로 **하한선만이 유일한 순서 보장 수단**이다. 9.x는 이런 FK의 신규 생성을 DDL에서 차단하지만, 구버전에서 만들어져 살아남은 레거시는 남는다(4-1 결말, 4-4).

**처치를 정리하면** 구멍마다 강도가 다르다.

| 구멍 | 처치 | 강도가 그런 이유 |
|------|------|----------------|
| ①③ | 부모 폴백 + 하한선/clear | 빠졌거나 안 맞는 변경분은 이력에 없으므로, 자기만 물러나서는 부족하고 뒤에 올 트랜잭션들의 낮춤 한도까지 올려야 한다 |
| ② | missing_keys 폴백 (min만 스킵) | 그 테이블을 만지는 전원이 같은 처지라 서로는 커밋 순서로 이미 안전하다. 남을 막을 필요가 없다 |

**마무리 — 보수적 설계 선택.** MySQL은 ①③을 정밀하게 구분하는 대신 "부모 테이블에 쓰기가 있으면 무조건"이라는 일괄 규칙 하나로 덮었다. 커밋 순서 값은 느릴 뿐 항상 안전한 상한이므로(0장), 확신이 없을 때 그리로 되돌리는 것이 가장 단순하고 틀리지 않기 때문이다. WL#9556은 FR13에서 이 방식을 명시하면서 스스로 "sub-optimal"(차선)이라고 인정했다. 9.7 기본 모드에서 ①이 메워진 뒤에도 규칙이 그대로인 이유는, 같은 코드가 native 모드를 겸용해야 하고, 레거시 ③이 남아 있을 수 있으며, 재설계가 이루어지지 않았기 때문이다.

이 선택의 대가가 3-1에서 본 그림이다. 매칭 장치(3-2)는 설치되어 있지만 부모 해시가 이력에 남지 않아 쓰이지 못하고, 순서는 하한선이 대신 잡으며, 구멍이 실제로 없는 스키마에서도 부모 뒤의 무관한 트랜잭션까지 함께 직렬화된다(5-5).
