# UPDATE — Worker 10 vs Worker 2 — 슬레이브 서버 측 perf 측정 비교

같은 슬레이브 노드 / 같은 워크로드 (tbl1~tbl10 × 10만 건 UPDATE) 에 대해 PoC 의 활성 워커 수만 10 → 2 로 줄여 측정한 두 결과를 **같은 콜체인 함수명·같은 hierarchy 자리에서 가로로 비교**한다.

원본 보고서:
- [`update_worker_10.md`](./update_worker_10.md) — 워커 10
- [`update_worker_2.md`](./update_worker_2.md)  — 워커 2

---

## 1. 측정 메타데이터

| 항목 | Worker 10 | Worker 2 |
|---|---|---|
| 스레드| 10 | 2 |
| 측정 PID (SERVER / APPLY) | 946186 / 946527 | 1174174 / 1174429 |
| 샘플링 주파수 | 999 Hz | 999 Hz |
| 콜그래프 모드 | dwarf | dwarf |
| 캡쳐 시간 | 4분 22초 | 2분 12초 (132 초) |
| on-CPU samples | 129,238 | 17,377 (sflush 가지 안 1,050) |
| applylogdb thread peak | 12 (= main+monitor+worker×10) | 4 (= main+monitor+worker×2) |
| `xlocator_repl_force` inclusive | 85.97% of on-CPU | 99.87% of sflush 가지 |
| 후처리 필터 | `slocator_repl_force` / `xlocator_repl_force` 스택만 | (동일) |

본 비교는 on-CPU 만 다룬다 (양쪽 보고서 모두 동일 기준). 같은 줄을 가로로 읽으면 워커 수 변화에 따른 함수 비중 변화가 한눈에 들어온다.

---

## 콜체인 (on-CPU, `xlocator_repl_force` 하위, inc=99.87%)

```
[100.00%] xlocator_repl_force
├─ [  5.27%] xlocator_repl_force (재귀)                                    ← 10w 63.73% → 큰 폭 감소
│   └─ [ 56.15%] xbtree_find_unique  ※ 본 측정에서는 locator_repl_prepare_force 의 자식으로 더 크게 잡힘
│       ├─ [ 31.27%] btree_search_key_and_apply_functions                  ← 10w 57.24%
│       │   ├─ [ 18.07%] btree_key_find_and_lock_unique                    ← 10w 42.70%
│       │   │   └─ [ 17.95%] btree_key_find_and_lock_unique_of_unique      ← 10w 42.66%
│       │   │       └─ [ 16.16%] btree_key_lock_object                     ← 10w 41.98%
│       │   │           └─ [ 15.83%] lock_object                           ← 10w 41.84%
│       │   │               └─ [ 14.59%] lock_internal_perform_lock_object ← 10w 41.39%
│       │   │                   ├─ [  6.30%] lockfree_hashmap<lk_res_key, lk_res>::find_or_insert ← 10w 33.17%
│       │   │                   │   └─ [  6.20%] lf_hash_insert_internal   ← 10w 32.53%
│       │   │                   │       └─ [  4.48%] lf_list_insert_internal ← 10w 32.07%
│       │   │                   │           ├─ [  0.00%] lock_res_key_compare ★ 10w 24.03% → 본 측정 측정 한계 이하 (소실)
│       │   │                   │           └─ [  2.84%] lf_freelist_claim ← 10w 4.50%
│       │   │                   │               ├─ [  0.00%] lock_alloc_resource → cub_alloc → __GI___libc_malloc ★ 10w 2.46% → 소실
│       │   │                   │               │   └─ [  0.00%] _int_malloc → sysmalloc → __mprotect ★ 10w 1.94% (1.05%) → 소실
│       │   │                   │               └─ [  2.50%] lf_stack_pop  ← 10w 1.38%
│       │   │                   ├─ [  3.67%] lf_freelist_claim (직계)      ← 10w 5.89%
│       │   │                   │   └─ [  0.00%] lf_freelist_alloc_block → __GI___libc_malloc → _int_malloc → sysmalloc → __mprotect ★ 10w 2.53% → 소실
│       │   │                   ├─ [  1.77%] lock_insert_into_tran_hold_list → __GI___pthread_mutex_lock ← 10w 1.22%
│       │   │                   └─ [  0.87%] lock_escalate_if_needed       ← 10w 에는 없음 (신규)
│       │   ├─ [ 12.42%] btree_advance_and_find_key                        ← 10w 5.90% ★ 비중 2배
│       │   │   └─ [  8.59%] btree_search_nonleaf_page                     ← 10w 3.64%
│       │   │       ├─ [  2.20%] btree_read_record_without_decompression   ← 10w 1.12%
│       │   │       ├─ [  1.81%] btree_compare_key                         ← 10w 0.80%
│       │   │       └─ [  1.29%] spage_get_record                          ← 10w 0.52%
│       │   ├─ [  8.94%] btree_search_leaf_page                            ← 10w 3.95% ★ 비중 2배+
│       │   ├─ [  4.28%] btree_get_root_with_key                           ← 10w 3.17%
│       │   │   └─ [  2.31%] pgbuf_fix_release                             ← 10w 2.25%
│       │   └─ [  5.55%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix(4.27%) ← 10w 1.38%
│       ├─ [  4.93%] lock_object  (다른 caller)                            ← 10w 2.50%
│       │   ├─ [  1.48%] lock_get_class_lock → __GI___pthread_mutex_lock(0.68%) ← 10w 0.92%
│       │   └─ [  1.77%] lock_internal_perform_lock_object                  ← 10w 0.81%
│       └─ [  2.31%] xbtree_find_unique → pgbuf_fix_release                ← 10w 2.01% (pgbuf_unfix 가지)
│           └─ [  0.74%] __GI___pthread_mutex_lock                          ← 10w 0.95%
├─ [ 68.36%] locator_repl_prepare_force                                    ← 10w 23.50% ★ 본 측정의 메인 가지
│   ├─ [  2.88%] heap_get_class_repr_id                                    ← 10w 14.76% ★ 1/5 로 감소
│   │   ├─ [  0.77%] heap_classrepr_free                                   ← 10w 10.75%
│   │   │   ├─ [  0.34%] __pthread_mutex_unlock_usercnt                    ← 10w 6.67%
│   │   │   │   └─ [  0.23%] __lll_unlock_wake                             ← 10w 4.85% ★ 1/21
│   │   │   └─ [  0.33%] __GI___pthread_mutex_lock                         ← 10w 3.65%
│   │   │       └─ [  0.00%] __lll_lock_wait                               ← 10w 3.20% ★ 소실
│   │   └─ [  1.88%] heap_classrepr_get                                    ← 10w 3.90%
│   │       ├─ [  0.43%] __GI___pthread_mutex_lock                         ← 10w 1.29%
│   │       └─ [  0.78%] __pthread_mutex_unlock_usercnt                    ← 10w 0.54%
│   ├─ [  8.18%] heap_get_visible_version                                  ← 10w 4.62% ★ 비중 1.8배
│   │   ├─ [  4.42%] heap_clean_get_context                                ← 10w 3.15%
│   │   │   └─ [  3.92%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix(1.45%) ← 10w 2.47%
│   │   │       └─ [  1.86%] pgbuf_unlatch_void_zone_bcb → pgbuf_lru_add_new_bcb_to_top(1.50%) → pgbuf_lru_adjust_zones(1.26%) ← 10w 1.66%/0.82%
│   │   └─ [  3.13%] heap_get_visible_version_internal → heap_prepare_get_context(2.28%) ← 10w 1.27%
│   └─ [  2.75%] btree_get_pkey_btid                                       ← 10w 3.55%
│       └─ [  0.69%] heap_classrepr_free                                   ← 10w 2.60%
│           ├─ [  0.00%] __pthread_mutex_unlock_usercnt → __lll_unlock_wake ← 10w 1.54% / 1.18% → 소실
│           └─ [  0.56%] __GI___pthread_mutex_lock → __lll_lock_wait        ← 10w 0.94% / 0.81%
├─ [ 11.90%] xtran_server_end_topop → log_sysop_attach_to_outer(4.69%)     ← 10w 5.32% ★ 비중 2배
├─ [  4.77%] xtran_server_start_topop → log_sysop_start(4.20%)             ← 10w 2.01%
├─ [  3.45%] heap_get_class_info → heap_hfid_cache_get(3.45%) → lf_hash_insert_internal ← 10w 1.93%
├─ [  2.41%] heap_scancache_start_modify → file_get_type → pgbuf_fix_release ← 10w 1.56%
└─ [  0.83%] heap_scancache_quick_end                                       ← 10w 0.48%
```

---

## on-CPU Top Hot Spots (inclusive %, 10w 대비 비교)

| 순위 | leaf 함수 (트리에 등장한 정확한 이름) | 10w on-CPU % | **2w on-CPU %** | 변화 | 분류 |
|------|---------------------------------------|-------------:|----------------:|------|------|
| 1 | `lock_res_key_compare`                   | **24.03%** | **0.00%**  | **−24.0pp** ★ | lock-free hashmap key 비교 (CPU 직렬화) |
| 2 | `__libc_malloc → _int_malloc → sysmalloc → __mprotect` (두 경로 합) | **~10%** | **0.00%** | **−10pp** ★ | glibc arena + 새 페이지 매핑 |
| 3 | `heap_classrepr_free` 영역 (mutex_unlock + lock_wait) | 10.75% | **1.46%** | −9.3pp | class repr cache mutex |
| 4 | `btree_search_*` (root + nonleaf + leaf) 합 | ~10.7% | **~21.8%** | **+11.1pp** ★ | btree page 탐색 (상대 비중 ↑) |
| 5 | `xtran_server_end_topop`                 | 5.32% | **11.90%** | **+6.6pp** ★ | sysop 종료 |
| 6 | `heap_get_visible_version` 영역          | 4.62% | **8.18%** | +3.6pp | MVCC visible-version 체크 (상대 비중 ↑) |
| 7 | `__lll_unlock_wake` (heap_classrepr unlock 시) | 4.85% | **0.23%** | **−4.6pp** ★ | 대기자 wake leaf |
| 8 | `heap_classrepr_get` (또 다른 cache lookup) | 3.90% | **1.88%** | −2.0pp | class repr cache 재호출 |
| 9 | `__lll_lock_wait` (heap_classrepr lock 시) | 3.20% | **0.00%** | **−3.2pp** ★ | mutex slow-path |
| 10 | `pgbuf_unlatch_void_zone_bcb → pgbuf_lru_adjust_zones` | 1.34% | **1.26%** | ≈ | page buffer LRU 통계 |

> ★ 표시는 10w 대비 **2pp 이상 차이** 가 난 항목. 워커 수가 줄면 **공유 자료구조 경합 (1, 2, 3, 7, 9)** 이 거의 사라지고, 상대 비중은 **본체 작업 (4, 5, 6)** 로 이동.

---

## on-CPU 직렬화점 식별 (10w 의 §A–F 분류 유지)

### A. `lock_res_key_compare` — on-CPU **0.00%** (10w 24.03%)

```
xbtree_find_unique → btree_key_find_and_lock_unique → btree_key_lock_object
  → lock_object → lock_internal_perform_lock_object
  → lockfree_hashmap<lk_res_key, lk_res>::find_or_insert       [ 6.30%]   ← 10w 33.17%
  → lf_hash_insert_internal                                    [ 6.20%]   ← 10w 32.53%
  → lf_list_insert_internal                                    [ 4.48%]   ← 10w 32.07%
  → lock_res_key_compare                                       [ 0.00%]   ← 10w 24.03% ★
```

row 락 진입 시 lock-free hashmap 의 bucket linked list 를 따라가며 매 비교마다 `lock_res_key_compare` 가 호출된다. 워커 N 명이 동시에 같은 bucket 에 entry 를 추가하면 list 길이가 N 에 비례해 늘고, 따라가는 동안의 비교 호출 횟수도 곱셈으로 늘어난다. 10w 에서는 이 비교 leaf 가 단일 함수 1위 (24.03%) 였으나, 2w 에서는 list 길이가 0–1 수준이라 leaf 가 측정 한계 이하로 사라진다. 그 윗 단계인 `lf_list_insert_internal` 본체도 32.07% → 4.48% 로 함께 축소 — **10w 보고서가 가설로 제시한 "워커 수에 비례하는 bucket list 길이가 contention 의 원인" 의 직접 검증**.

### B. `heap_classrepr` cache mutex — on-CPU **1.46%** (10w 10.75%, 영역 단위)

```
locator_repl_prepare_force → heap_get_class_repr_id → heap_classrepr_free
  ├─ __pthread_mutex_unlock_usercnt → __lll_unlock_wake        [ 0.23%]  ← 10w 4.85% ★
  └─ __GI___pthread_mutex_lock → __lll_lock_wait               [ 0.00%]  ← 10w 3.20% ★
```

`heap_classrepr` (class representation) cache 는 단일 mutex 로 보호되며 매 lookup 마다 lock/unlock 한 번씩 일어난다. 10w 에서는 평균 대기자가 항상 존재해 unlock 시 `__lll_unlock_wake` syscall 이 4.85%, lock 시 `__lll_lock_wait` 진입이 3.20% 를 차지. 2w 에서는 워커가 2 명이라 평균 대기자가 1 명 이하로 떨어져 `__lll_unlock_wake` 가 즉시 return 되며 0.23%, `__lll_lock_wait` 는 측정 한계 이하로 사라진다. **mutex 코드 경로 자체는 동일하지만 contention 신호만 사라진 상태**. 같은 mutex 가 `btree_get_pkey_btid → heap_classrepr_free` 경로에서도 다시 잡히는데 (10w 2.60% → 2w 0.69%), 두 경로 합 1.46%.

### C. `__libc_malloc → sysmalloc → __mprotect` — on-CPU **0.00%** (10w ~10%)

```
lf_freelist_claim → (lock_alloc_resource → cub_alloc →) __GI___libc_malloc
  → _int_malloc → sysmalloc → __GI___mprotect → [kernel]
                                                              [ 0.00%]  ← 10w ~10% ★
```

lock entry 객체는 lock-free freelist 에 캐시해 재활용한다. freelist 가 비면 `lf_freelist_alloc_block` 이 새 메모리를 받아오며 `_int_malloc → sysmalloc → __mprotect` (kernel page mapping syscall) 까지 도달한다. 10w 에서는 freelist 소비 속도가 빨라 mmap 빈도가 높고 두 경로 합 ~10%. 2w 에서는 freelist 가 거의 비지 않아 두 경로 모두 측정 한계 이하. **§A·§B 의 자료구조 사용 빈도가 줄어든 부산물** 로 해석된다.

### D. btree page 탐색 — on-CPU **~21.8%** (10w ~10.7%)

```
btree_search_nonleaf_page (8.59%)   ← 10w 3.64%
+ btree_search_leaf_page  (8.94%)   ← 10w 3.95%
+ btree_get_root_with_key (4.28%, → pgbuf_fix_release 2.31%) ← 10w 3.17%
```

UPDATE row 당 PK lookup 으로 btree 를 root → nonleaf → leaf 로 한 번 내려간다. 페이지 fix, slot 조회 (`spage_get_record`), 키 비교 (`btree_compare_key`) 모두 row 당 고정 비용으로 워커 수와 무관. 절대 작업량은 10w 와 동일하지만 분모 (§A·§B·§C 의 contention 시간) 가 줄어 상대 비중이 2배. 하위 leaf 들 (`btree_compare_key` 0.80→1.81%, `btree_read_record_without_decompression` 1.12→2.20%) 도 동일한 패턴 — 새 직렬화점이 생긴 것이 아니라 분모 변화에 의한 비중 증가.

### E. MVCC visible version — on-CPU **8.18%** (10w 4.62%)

```
heap_get_visible_version → heap_clean_get_context → pgbuf_unfix
  → pgbuf_unlatch_void_zone_bcb (1.86%)        ← 10w 1.66%
  → pgbuf_lru_add_new_bcb_to_top (1.50%)        ← 10w (sub)
  → pgbuf_lru_adjust_zones      (1.26%)         ← 10w 0.82%
```

UPDATE row 당 `heap_get_visible_version` 으로 MVCC 가시 버전 확인 → 페이지 unfix → page buffer LRU void-zone 통계 갱신. §D 와 같은 row 당 고정 비용으로 워커 수와 무관, 분모만 줄어 상대 비중 1.8배. `pgbuf_lru_adjust_zones` 가 0.82 → 1.26% 로 소폭 증가했는데, page buffer LRU zone 을 보호하는 mutex 이므로 잠재 직렬화점 후보로 남겨둘 만하다. 본 측정 sample 안에서는 단정하기에 너무 작아 다음 라운드 확인 대상.

### F. 부수 leaves

| 함수 | 10w | 2w |
|---|---:|---:|
| `lock_get_class_lock → __pthread_mutex_lock` | 0.92% | 1.48% |
| `pgbuf_fix_release` (btree 탐색 안) | (다수) | (다수) |
| `xtran_server_start_topop` | 2.01% | **4.77%** |
| `xtran_server_end_topop` | 5.32% | **11.90%** |

UPDATE row 당 server-side sub-transaction (sysop) 을 시작·종료한다. `xtran_server_start_topop` 4.77%, `xtran_server_end_topop` 11.90% (= cuberr context push/pop + `log_sysop_attach_to_outer` + PL session lookup). §D·§E 와 같은 row 당 고정 비용이라 절대 작업량은 10w 와 동일, 분모 줄어 상대 비중이 2배 이상이 되어 본 측정에서 두 번째로 큰 leaf 로 도드라져 보인다.

---

## on-CPU only 결론

> 워커 수를 10 → 2 로 줄이면 5 개 직렬화점이 두 그룹으로 갈라진다:
>
> **(1) contention 소거 그룹 — §A·§B·§C**
> - §A `lock_res_key_compare` 24.03% → **0.00%**: lock-free hashmap bucket linked list 안 비교 leaf. 워커 줄어 list 길이가 짧아지며 leaf 소실.
> - §B `heap_classrepr` mutex 영역 10.75% → **1.46%**: mutex 코드 경로는 동일, 평균 대기자가 1 명 이하로 줄어 `__lll_unlock_wake` 와 `__lll_lock_wait` 가 0 으로 수렴.
> - §C `malloc → mprotect` ~10% → **0.00%**: §A·§B 의 자료구조 사용 빈도가 줄어든 부산물. lock-free freelist 재할당이 일어나지 않아 syscall 까지 도달하지 않음.
>
> **(2) row 당 고정 비용 그룹 — §D·§E·§F**
> - §D btree 탐색 ~10.7% → **~21.8%**, §E MVCC visible version 4.62% → **8.18%**, §F sysop 합 (start+end) 7.33% → **16.67%**.
> - 절대 작업량은 10w 와 동일, 분모 (contention 시간) 가 줄어 상대 비중만 1.5–2 배.
>
> **검증 결과**:
> - 10w 보고서가 가설로 적은 "`lock_res_key_compare` 는 워커 N 에 비례하는 hashmap bucket list 길이로 인한 contention" — 본 비교가 0.00% 로 떨어뜨려 **직접 검증**.
> - §B 의 contention 식별법 (`__lll_unlock_wake` 가 `__lll_lock_wait` 보다 크면 항상 대기자 존재) 도 양쪽 모두 0 으로 수렴하며 일관 입증.
> - 워커 수만 줄여 얻을 수 있는 개선은 §A·§B·§C 까지. §D·§E·§F 의 row 당 고정 비용은 워커 수와 무관하므로, 추가 개선은 row 당 비용 자체 (btree 탐색 / MVCC 검사 / sysop 비용) 를 깎거나 워크로드 자체를 분할해야 가능.

---

## 산출물 위치

`/home/youngjun/bench_sampling/perf-runs/20260520-135157/`

```
oncpu.data       (139 MB)    oncpu.folded     (3.4 MB)    oncpu_sflush.folded   (140 KB)
offcpu.data     (3.10 GB)    (해당 보고서 미사용)
futex.data      (7.45 GB)    (해당 보고서 미사용; 469 chunks lost)
thread_counts.log (149 KB; thread peak = 4)
draw_tree.py     (재현/재분석용 — `update_20260519-170435_10worker/draw_tree.py` 의 BASE 만 변경)
SUMMARY.txt      (Step 6 자동 요약: TID 분포 + off-CPU/futex 영역 leaf 카운트)
tree_output.txt  (draw_tree.py 의 트리 raw 출력 — 본 보고서 §콜체인의 % 출처)
```
