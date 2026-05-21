# INSERT vs UPDATE — Worker 10 환경 비교 분석

worker_10 (활성화 워커 10개) 환경에서 동일 슬레이브 노드에 동일 측정 기법으로 잡은 두 워크로드의 perf 결과 비교.

원본 보고서:
- [`insert_worker_10.md`](../3.insert_server_perf_test/insert_worker_10.md) — tbl1~tbl10 각 10만 건 INSERT
- [`update_worker_10.md`](./update_worker_10.md) — tbl1~tbl10 각 10만 건 UPDATE

---

## 1. 측정 조건 차이 (먼저 분리)

| 항목 | INSERT | UPDATE |
|------|--------|--------|
| 샘플링 주파수 | 1,999 Hz | 999 Hz |
| 콜그래프 모드 | frame pointer (`fp`) | dwarf |
| 캡쳐 시간 | 30초 | 4분 22초 |
| 측정 PID | `$SLAVE_PID` (cub_server 단독) | `$SERVER_PID` + `$APPLY_PID` (cub_server + applylogdb) |
| on-CPU samples | (보고서 미명시) | 129,238 |
| off-CPU samples | (보고서 미명시) | 1,739,443 |

> 비율 비교는 valid 하지만 절대값/lost sample 측면에서 UPDATE 가 더 무거운 캡쳐. 콜그래프 모드 차이 (`fp` ↔ `dwarf`) 는 같은 라이브러리 함수 (e.g. `__pthread_mutex_lock`, `__lll_lock_wait`) 해석에 영향 없음 — 두 모드 다 user-space stack 을 같은 함수명으로 잡음. dwarf 는 stack 비용이 더 크지만 frame pointer 미빌드 코드에도 동작.

---

## 2. 가설 매칭 — 한눈 비교

| 가설 | INSERT (on-CPU) | INSERT (off-CPU) | UPDATE (on-CPU) | UPDATE (off-CPU) |
|------|----------------|------------------|----------------|------------------|
| H1 `thread_sleep` | 0.00% | (제시 없음) | 0.00% | 0.00% |
| **H2** `__lll_lock_wait` 계열 | **21.21%** | **97.21%** | **3.67%** | **84.02%** |
| H3 `pgbuf_block_bcb` / `pgbuf_lock_page` | 0.04% | — | 0.00% | 0.00% |

→ **공통**: H1·H3 둘 다 양쪽 워크로드에서 **비활성**.
→ **공통**: H2 (단일 mutex 직렬화) 가 양쪽의 본체이며 **off-CPU 시간의 80%+ 가 mutex wait**.
→ **차이**:
  - INSERT 는 on-CPU 시간의 21% 도 lock_wait → CPU 위에서도 spin-like contention 시간이 많음
  - UPDATE 는 on-CPU 시간 중 lock_wait 는 3.67% 로 적고 대신 다른 hot path (xbtree_find_unique 의 lockfree-hashmap 비교) 가 CPU 를 점유

---

## 3. 본체 mutex 가 다름 — 핵심 발견

같은 H2 패턴이지만 **워크로드별로 hot 한 mutex 가 다름**:

| | INSERT 본체 mutex | UPDATE 본체 mutex |
|---|---|---|
| 함수 위치 | `prior_lsa_next_record_internal` (WAL append 직렬화점) | `heap_classrepr_free` 의 mutex (class representation cache) |
| 호출 경로 | `log_append_undoredo_crumbs` (heap·btree·tran-stats 3 경로 모두 수렴) | `xlocator_repl_force → heap_get_class_repr_id` (46.93%) + `locator_repl_prepare_force → btree_get_pkey_btid → heap_classrepr_free` (15.51%) |
| critical section 안의 비싼 작업 | **LZ4 압축** (`prior_lsa_alloc_and_copy_crumbs → log_zip → LZ4_compress_fast_extState` 8.58%) | (compression 안 보임 — pure cache lookup) |
| off-CPU 비중 (단일 mutex) | ~97% (거의 전부 prior_lsa) | ~62.44% (heap_classrepr) + 23.17% (pgbuf_unlatch_void_zone_bcb) → 두 mutex 로 분산 |

### 메커니즘 해석

- **INSERT**: 매 row 마다 heap insert + btree insert + tran-stats update → 모두 `log_append_undoredo_crumbs` 호출 → `prior_lsa_mutex` 안에서 **LZ4 압축이 실행**되며 락 보유 시간이 압축 시간만큼 늘어남. 9명이 남의 압축 끝나길 기다림. INSERT 보고서의 "락 자체보다 락 안의 LZ4 압축" 결론과 정합.
- **UPDATE**: 매 row 마다 PK 로 row 찾기 (`xbtree_find_unique`) + MVCC visible version 체크 (`heap_get_visible_version`) + class representation lookup (`heap_get_class_repr_id`) → 모두 `heap_classrepr_free` 의 mutex 가 hot. 게다가 `locator_repl_prepare_force` 의 `btree_get_pkey_btid` 도 같은 mutex 로 수렴.
  - log_append 자체는 트리에 거의 안 보임 (UPDATE 는 row 자체 수정량 작아 로그 양 적음 → prior_lsa_mutex 가 INSERT 만큼 hot 하지 않음).
  - 대신 cache lookup 빈도가 매우 높아 `heap_classrepr` mutex 가 hot.

---

## 4. 콜체인 비교 — `xlocator_repl_force` 직계 자식 분포

### INSERT (on-CPU)
```
[100.00%] xlocator_repl_force
├─ [93.64%] locator_insert_force
│   ├─ [61.00%] heap_insert_logical
│   │   ├─ [24.28%] heap_stats_find_best_page
│   │   ├─ [19.64%] heap_log_insert_physical     ← __lll_lock_wait 2.18% ★H2
│   │   └─ [10.92%] lock_object
│   ├─ [29.95%] locator_add_or_remove_index_internal
│   │   └─ [23.16%] btree_insert
│   │       ├─ [ 8.24%] btree_key_insert_new_object  ← __lll_lock_wait 2.22% ★H2
│   │       ├─ [ 8.20%] btree_fix_root_for_insert    ← __lll_lock_wait 2.24% ★H2
│   │       └─ [ 4.59%] btree_split_node_and_advance
│   └─ [ 1.42%] locator_check_foreign_key
├─ [ 1.97%] xtran_server_end_topop
└─ [ 1.16%] heap_get_class_repr_id              ← INSERT 에서는 1.16% 에 불과
```

### UPDATE (on-CPU)
```
[100.00%] xlocator_repl_force
├─ [63.73%] xlocator_repl_force (재귀)
│   └─ [63.03%] xbtree_find_unique               ← INSERT 에는 없는 path
│       └─ [41.84%] lock_object → lockfree_hashmap → lock_res_key_compare (24.03%)
├─ [23.50%] locator_repl_prepare_force
│   ├─ [14.76%] heap_get_class_repr_id          ← UPDATE 에서는 14.76% 로 폭증
│   │   └─ [10.75%] heap_classrepr_free → __lll_lock_wait 3.20% ★H2
│   ├─ [ 4.62%] heap_get_visible_version
│   └─ [ 3.55%] btree_get_pkey_btid → heap_classrepr_free → __lll_lock_wait 0.81% ★H2
├─ [ 5.32%] xtran_server_end_topop
└─ [ 1.93%] heap_get_class_info
```

**관찰**:
1. **INSERT 의 `locator_insert_force` (93.64%) ↔ UPDATE 의 `xbtree_find_unique` (63.03%) + `locator_repl_prepare_force` (23.50%)** — 워크로드 본질의 차이가 그대로 콜그래프 구조에 반영됨.
2. **`heap_get_class_repr_id`** 가 INSERT 1.16% → UPDATE 14.76% 로 **12배 폭증**. UPDATE 의 본 병목 mutex 가 여기 박혀 있음.
3. **`__lll_lock_wait ★H2` 등장 위치**:
   - INSERT: log_append_undoredo_crumbs 안 3곳 (모두 prior_lsa_mutex)
   - UPDATE: heap_classrepr_free 안 2곳 + pgbuf_unlatch_void_zone_bcb 1곳 (off-CPU) + (futex 분석 시 추가될 수 있음)
4. **`lock_object → lockfree_hashmap` 경로**:
   - INSERT: 10.92% (insert 시 row lock 획득)
   - UPDATE: 41.84% — **4배 더 큼**. UPDATE 는 row 찾고 lock 까지 잡아야 하니 lock_object 비중이 압도적.

---

## 5. 공통 부수 신호

### A. `lockfree_hashmap<lk_res_key, lk_res>::find_or_insert` + `lock_res_key_compare`

| | INSERT | UPDATE |
|---|---|---|
| lockfree_hashmap | on-CPU **8.26%** | on-CPU **33.17%** |
| lock_res_key_compare | on-CPU **6.44%** | on-CPU **24.03%** |

같은 자료구조의 같은 hot loop. 워커 10이 같은 hash bucket 의 linked list 를 CAS-traverse 하며 **CPU cache line ping-pong**. UPDATE 에서 4배 큼 — 워크로드가 lock_object 를 더 자주 호출하기 때문.

mutex 가 아닌 lock-free 구조이므로 H2 별개로 분류되지만, **"같은 자료구조를 동시 접근하는 워커 수"** 가 늘면 곱셈으로 증가. lockfree 가 항상 빠르지 않음을 보여주는 사례.

### B. malloc arena

| | INSERT | UPDATE |
|---|---|---|
| `lf_freelist_claim → __libc_malloc → sysmalloc → __mprotect` | (트리에 1.43%, 부분 미세 항목) | on-CPU 5%, off-CPU 1.7% |

UPDATE 에서 lock 자원 할당이 더 자주 → glibc arena lock 이 작지만 의미있게 등장.

---

## 6. UPDATE 만의 신호

INSERT 트리에는 없는 두 가지:

### (a) `pgbuf_unlatch_void_zone_bcb` mutex (off-CPU 23.17%)
```
heap_get_visible_version → pgbuf_unfix → pgbuf_unlatch_void_zone_bcb
  → __GI___pthread_mutex_lock → __lll_lock_wait ★H2
```
Page buffer LRU void-zone 통계 mutex. UPDATE 의 visible-version 조회로 페이지 unfix 가 빈번 → LRU 통계 mutex 가 경합. 이는 **H3 의 page latch 와 다른 종류** (latch ≠ LRU stats mutex). UPDATE-특이 직렬화점.

### (b) `pgbuf_allocate_bcb → __pthread_cond_timedwait` (off-CPU 1.29%)
워커가 새 페이지 fix 시 빈 BCB 못 찾아 cond_timedwait 로 잠듦. 작지만 **page buffer victim 부족** 신호 — UPDATE 워크로드가 페이지 접근 더 많아서 발생.

---

## 7. INSERT 만의 신호

UPDATE 트리에 없는 것:

### LZ4 압축이 critical section 안에서 8.58%
```
prior_lsa_alloc_and_copy_crumbs → log_zip → LZ4_compress_fast_extState (8.58%)
```
INSERT 의 "락 잡은 채 비싼 작업" 본질. UPDATE 는 log_append 자체가 hot 하지 않아 이 패턴 안 보임.

### btree_split_node_and_advance (4.59%)
새 row INSERT 가 btree leaf overflow 시 split 트리거. UPDATE 에는 분할 없음.

---

## 8. 핵심 정리

| 관점 | 결론 |
|------|------|
| **공통 가설** | H1 (thread_sleep) · H3 (page latch) 둘 다 **비활성**. H2 (단일 mutex 직렬화) 가 양쪽 워크로드의 본체. |
| **메커니즘 일치** | "단일 mutex + 그 안의 비싼 작업" 패턴이 둘 다 적용. INSERT 는 비싼 작업이 LZ4 압축, UPDATE 는 비싼 작업이 cache lookup. |
| **mutex 가 다름** | INSERT: `prior_lsa_mutex` (WAL append). UPDATE: `heap_classrepr` cache mutex. **워크로드 hot path 가 어디로 들어가느냐가 어떤 mutex 가 hot 한지 결정**. |
| **2차 병목** | INSERT 와 UPDATE 둘 다 lockfree_hashmap 의 `lock_res_key_compare` 가 부수 hot spot. UPDATE 에서 4배 더 큼 (lock_object 호출 빈도가 높아서). |
| **UPDATE 특이점** | `pgbuf_unlatch_void_zone_bcb` mutex (off-CPU 23.17%) — page buffer LRU stats. INSERT 에는 없음. |
| **INSERT 특이점** | LZ4 압축이 critical section 안 (on-CPU 8.58%) — 락 보유 시간 폭증의 본질. |

---

## 9. PoC / 다음 검증 — 워크로드별 효과 예측

| 완화 PoC | INSERT 효과 예측 | UPDATE 효과 예측 |
|----------|----------------|----------------|
| LZ4 압축을 critical section 밖으로 | **큼** (INSERT 의 본체 비용 직접 제거) | 작음 (UPDATE 의 prior_lsa_mutex 자체가 hot 아님) |
| `prior_lsa_mutex` 분리/sharding | 중 (mutex 분리는 lock 보유 시간을 줄이지 않음. PoC 1 보다 작은 효과) | 무관 |
| `heap_classrepr` cache → RW lock 또는 sharded mutex | 작음 (INSERT 에선 1.16% 에 불과) | **큼** (UPDATE off-CPU 62.44% 제거 가능) |
| `pgbuf_unlatch_void_zone_bcb` mutex 분리 | 무관 (INSERT 에 없음) | 중 (off-CPU 23.17%) |
| lockfree_hashmap bucket 수 증가 (lock_res_key 분산) | 중 (on-CPU 6.44%) | **중-대** (on-CPU 24.03%, CPU 점유 큰 부분 직접 완화) |

→ **단일 PoC 가 모든 워크로드를 다 잡지 않는다**. 워크로드 별로 우선 PoC 가 달라야 함.

---

## 10. 결론

> **워커 10 환경에서 INSERT/UPDATE 두 워크로드의 병목은 같은 H2 패턴 (단일 mutex 직렬화) 이지만 hot 한 mutex 가 다르다**.
>
> - INSERT → `prior_lsa_mutex` (WAL append) + LZ4 압축이 critical section 안
> - UPDATE → `heap_classrepr` cache mutex (off-CPU 62%) + `pgbuf_unlatch_void_zone_bcb` (off-CPU 23%)
> - 공통 2차 병목: lockfree row-lock hashmap 의 `lock_res_key_compare` (UPDATE 에서 4배 더 큼)
>
> H1·H3 는 양쪽 워크로드에서 모두 비활성으로 배제.
>
> 완화 PoC 우선순위는 워크로드별로 달라야 하며, 일반화 가능한 교훈은 **"단일 mutex + 그 안의 비싼 작업"이 워커 N 의 직렬화 본질**이라는 점이다.
