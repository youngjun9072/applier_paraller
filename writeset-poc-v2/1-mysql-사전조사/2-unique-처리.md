---
tags: [writeset, mysql, 자료조사, unique]
---

# 2. UNIQUE 키 처리 (PK 포함)

> 목차: [[0-자료조사-목차|자료조사 목차]]


### 2-0. v1은 PK만 봤지만, 실제로는 "유니크 키 전부"가 해시된다

v1 분석과 PoC는 "행 식별 = PK"라는 전제 아래 **PK 기준**으로만 진행했다. 하지만 MySQL의 writeset 추출은 **PK를 특별 취급하지 않는다** — 유니크 키면 모두 해시한다. 해시를 만드는 곳은 **`add_pke()` 한 곳**(`sql/rpl_write_set_handler.cc`)으로, 1장에서 본 추출 단계에 해당한다. 콜체인은 다음과 같다:

**[그림 1] writeset 추출 콜체인**
  ```
  행 write/update  (handler.cc, rpl_injector.cc)
    └ add_pke(table, thd, record)                     
      // 이 행의 PK·UNIQUE·FK 해시 생성
        ├ (키 루프) HA_NOSAME 인 키마다 → generate_hash_pke()   // 유니크면 전부
        └ generate_hash_pke() 
          → get_transaction_write_set_ctx()
          -> add_write_set(hash)
  ```
이 루프는 키를 "PK냐"로 고르지 않고 **"유니크(HA_NOSAME)냐"로 고른다.** 그래서 해시 대상은 PK와 모든 UNIQUE 인덱스이고, PK는 유니크 키들 중 하나로 처리될 뿐이며, 제외되는 것은 비유니크 인덱스뿐이다(실제 판정 코드는 [[#2-1. 어떤 키가 해시 대상인가|2-1]]). 결국 v1의 "PK 기준" 관점은 대상을 좁게 본 것이고, FK와 유니크를 논할 때도 "유니크 키 전체"를 단위로 봐야 한다. 다만 값이 NULL인 유니크 키는 그 행에서 해시가 스킵되므로(2-4 참조), 항상 값이 있는 PK나 NOT NULL UNIQUE가 안정적인 식별자가 된다.

**왜 UNIQUE도 해시해야 하나 — DELETE→INSERT 재사용 예시 (PK만 보면 깨진다)**

`t(id PK, email UNIQUE)` 에서:

**[예시] 유니크 값 재사용 — 마스터 커밋 순서**
```sql
T1 (seq1): DELETE FROM t WHERE id=1;           -- 이 행의 email='X' 가 비워짐
T2 (seq2): INSERT INTO t VALUES (id=2, 'X');   -- 비워진 email='X' 를 재사용
```

PK만 해시하면 T1=H(PK,1), T2=H(PK,2)로 서로 달라 독립으로 판정되어 리플리카에서 순서 없이 병렬 적용된다. 그런데 T2가 T1보다 먼저 적용되면:

```sql
-- 리플리카 (PK만 해시 → 순서 안 지킴)
T2: INSERT INTO t VALUES (id=2, 'X');   -- id=1의 email='X'가 아직 살아 있음 → UNIQUE 위반, 실패
T1: DELETE FROM t WHERE id=1;           -- 뒤늦게 email='X' 비움 (T2는 이미 깨진 뒤)
```

email도 해시하면 T1과 T2가 모두 `H(email,'X')`를 포함해 겹치므로 의존이 걸리고, T1→T2 순서가 강제되어 안전하다.

그래서 MySQL은 PK뿐 아니라 **모든 유니크 키를 해시**한다. 해시 계산이 유니크 개수만큼 늘어나는 비용이 있지만, 이 정합성 때문에 필요한 비용이다.

### 2-1. 어떤 키가 해시 대상인가
`add_pke()`는 **PK가 있는 테이블에 한해**, 그 테이블의 **모든 유니크 인덱스(PK 포함)** 에 대해 해시를 만든다. 비유니크 인덱스는 대상이 아니며, **PK가 없는 테이블은 UNIQUE 인덱스가 있어도 아래 블록 전체가 스킵돼 해시가 하나도 만들어지지 않는다**.

**[코드 4] 해시 대상 키 판정 — `add_pke()`의 골격 (왼쪽 숫자=원본 라인, `...`=생략)**
```c
 910:  if (table->key_info && table->s->primary_key < MAX_KEY) {   // ★ 대문: PK가 있어야 진입
 912:    // "SEP db SEP len(db) 테이블 SEP len(테이블)" 를 미리 만들어 재사용
         std::string pke_schema_table = SEP + db + SEP + len(db) + table + SEP + len(table);
  ...
 930:    for (uint key = 0; key < table->s->keys; key++) {
 932:      if (!(table->key_info[key].flags & HA_NOSAME)) continue;   // ★ 유니크(HA_NOSAME)만
  ...        // 이 키의 pke 조립 + generate_hash_pke (942~1043) → [코드 5]에서 확대
       }
1082:    // 자식 테이블이면: FK 값으로 부모 키 모양 해시 생성 (3-2의 인라인 블록)
  ...
1191:    if (table->s->foreign_key_parents > 0)
1192:      ws_ctx->set_has_related_foreign_keys();   // 부모 폴백 플래그(3-1)도 이 대문 안!
1196:  }                                             // ★ 대문 닫힘
1197:  if (!writeset_hashes_added) ws_ctx->set_has_missing_keys();
```

> **용어**
> `HA_NOSAME`: 인덱스 플래그로 그 인덱스가 유일성을 강제한다(=유니크). PK·UNIQUE는 켜져 있고 일반(비유니크) 인덱스는 꺼져 있어, 위 루프가 유니크 키만 고른다.
>
> `SEP`: 조각 구분자 `HASH_STRING_SEPARATOR`. 수식이 아니라 문자 하나다 — "½"(U+00BD, UTF-8 `0xC2 0xBD`)라는 글자 자체가 구분자 값이고, CSV의 쉼표처럼 조각(인덱스명·db·테이블·값) 사이에 끼워 넣는다. 일반 데이터에 잘 안 나오는 문자라서 골랐을 뿐이다. 다만 값은 임의 바이트라 이 바이트가 우연히 나올 수 있으므로 구분자만 믿지 않고, 가변 조각 뒤에는 `SEP` 다음에 그 조각의 길이를 함께 붙여 경계를 확정한다(그래서 "ab"+"c"와 "a"+"bc"가 같은 문자열로 뭉개지지 않는다).

> 마지막에 해시가 하나도 안 만들어지면 `set_has_missing_keys()`가 켜진다(:1197). **PK 없는 테이블이 여기 해당한다 — UNIQUE 인덱스가 있어도 대문에서 걸러지므로 마찬가지다.** 이 경우 뒤(의존성 추적 단계)에서 낮춤만 생략하는 커밋 순서 폴백을 받는다(이력 clear 없음, 3-1). 그리고 FK 해시(3-2)와 부모 폴백 플래그(3-1)도 같은 대문 안이라, PK 없는 테이블은 그 둘도 받지 못한다 — 이 조합이 만드는 문제는 5-7 실측 참조.

### 2-2. 해시 문자열(pke)의 구성
키 하나의 해시 문자열은 **인덱스이름 + 스키마/테이블 + (키 컬럼 값들)** 을 이어붙인 것이다. 아래 [코드 5]는 [코드 4]의 유니크 키 루프(930~932) 안쪽(942~1043)을 확대한 것이다.

**[코드 5] pke 문자열 조립 — `add_pke()` 핵심 경로 발췌 (`sql/rpl_write_set_handler.cc`, 왼쪽 숫자=원본 라인, `...`=생략)**
```c
 942:  pke.clear();
 943:  pke.append(table->key_info[key].name);   // 인덱스 이름 (예: "PRIMARY")
 944:  pke.append(pke_schema_table);            // + SEP db SEP len 테이블 SEP len
  ...
 949:  for (i = 0; i < key.user_defined_key_parts; i++) {   // 키를 이루는 컬럼들
  ...
 953:    Field *field = ...;
  ...
 956:    if (field->is_null(ptrdiff)) break;               // NULL이면 이 키는 중단(아래 참조)
  ...
 976:    // 값을 memcmp로 비교 가능한 "정규화 문자열"로 바꿔 이어붙임 (원문 주석 요약)
 980:    length = field->make_sort_key(pk_value, max_length, ...);
  ...
 984:    pke.append(pk_value, length);
 985:    pke.append(HASH_STRING_SEPARATOR);
 986:    pke.append(std::to_string(length));               // 값 + 구분자 + 길이
  ...
1022:  }
  ...
1031:  if (i == key.user_defined_key_parts)                // 모든 키파트가 비-NULL이었으면
  ...
1043:    generate_hash_pke(pke, thd);                      // → 해시 1개 추가
```

즉 pke 문자열 골격:

**[그림 2] pke 문자열 레이아웃**
```
"PRIMARY" <SEP> "db" <SEP> "2" "t1" <SEP> "2"  <정규화(값1)> <SEP> len1  <정규화(값2)> <SEP> len2 ...
 └인덱스┘      └db/테이블/길이┘                └────────── 키 컬럼 값들 ──────────┘
```

### 2-3. 복합 키 (여러 컬럼) — 해시 1개
`PRIMARY KEY (a, b, c)` 처럼 여러 컬럼으로 된 키는 **컬럼 값들을 하나의 문자열로 이어붙여 해시 1개**를 만든다(컬럼별 별도 아님). [코드 5]의 루프가 a, b, c를 차례로 같은 `pke`에 append 하고 끝나서 `generate_hash_pke`를 한 번 부른다.

예 — 행 `(a=1, b=2, c=3)`:

**[그림 3] 복합 PK — 해시 1개 예시**
```
"PRIMARY" SEP "db" SEP "2" "t1" SEP "2"  norm(1) SEP l  norm(2) SEP l  norm(3) SEP l   → 해시 1개
```

### 2-4. NULL 처리
키를 이루는 컬럼 중 **하나라도 NULL이면 그 키의 해시를 만들지 않는다**(`break` 후 `i != key_parts`라 `generate_hash_pke` 호출 안 함). NULL은 어떤 값과도 충돌하지 않으므로 병렬을 막을 이유가 없다. (PK는 NOT NULL이라 항상 만들어진다.)

### 2-5. 부분값(prefix) 인덱스 — 해시 2개 발행
`INDEX(name(10))` 처럼 **컬럼의 앞 일부만** 인덱싱한 경우, 값을 두 가지 길이 기준으로 정규화해 **해시를 2개** 만든다.

**[코드 6] prefix 인덱스 — 해시 2개 발행**
```c
size_t max_length  = strnxfrmlen(cs, key_part[i].length);     // ① 인덱스에 정의된(프리픽스) 길이
size_t pack_length = strnxfrmlen(cs, field->pack_length());   // ② 컬럼 전체 길이
if (STANDARD_PKE)        make_sort_key(v, max_length, key_len/mbmaxlen);  // ① 기준 해시
if (NO_PARTIAL_KEYS_PKE) make_sort_key(v, pack_length);                    // ② 기준 해시
if (STANDARD_PKE && max_length != pack_length)
  old_pke_needed = true;   // 두 길이가 다르면(=프리픽스면) ②도 발행하도록 한 번 더 루프
```
- **이유**: 그룹 복제에서 구/신 버전 멤버가 같은 행을 다른 길이 표현으로 식별할 수 있어, 어느 쪽과도 충돌을 놓치지 않으려고 두 표현을 모두 넣는다.
- 프리픽스가 아닌 일반 키는 `max_length == pack_length`라 해시 1개.

---

