# UPDATE — Worker 10 (활성화 워커 10개) — 슬레이브 서버 측 perf 측정 결과

- **활성화 워커: 10 / 비활성화 워커: 0**
- 빌드 모드: Release / 부하 도구: ha-bench (csql 병렬)
- 워크로드: tbl1 ~ tbl10, 각 10만 건 **UPDATE** / 단일 트랜잭션
- 측정 대상: **슬레이브 데이터베이스 서버 프로세스** (`$SERVER_PID`=946186) + **applylogdb** (`$APPLY_PID`=946527)

---

## 캡쳐 방법

```bash
# on-CPU (본 보고서는 on-CPU 기준 분석)
sudo -n perf record -F 999 -g --call-graph dwarf -p $SERVER_PID,$APPLY_PID -o oncpu.data
```

- 샘플링 주파수: 999 Hz
- 콜그래프 모드: dwarf
- 캡쳐 시간: 4분 22초 (워크로드 자체 약 1분 + slave apply trailing 포함)
- on-CPU samples: 129,238
- 후처리 필터: `slocator_repl_force` / `xlocator_repl_force` 스택만

> (참고) 같은 윈도우에 off-CPU/futex 트랙도 함께 capture 했으나 본 보고서는 **on-CPU 만** 분석. off-CPU/futex 는 별도.

---

## 콜체인 (on-CPU, `xlocator_repl_force` 하위, inc=85.97%)

```
[100.00%] xlocator_repl_force
├─ [63.73%] xlocator_repl_force (재귀)
│   └─ [63.03%] xbtree_find_unique                                   ← UPDATE 본 워크로드 (PK lookup)
│       ├─ [57.24%] btree_search_key_and_apply_functions
│       │   ├─ [42.70%] btree_key_find_and_lock_unique
│       │   │   └─ [42.66%] btree_key_find_and_lock_unique_of_unique
│       │   │       └─ [41.98%] btree_key_lock_object
│       │   │           └─ [41.84%] lock_object
│       │   │               └─ [41.39%] lock_internal_perform_lock_object
│       │   │                   ├─ [33.17%] lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│       │   │                   │   └─ [32.53%] lf_hash_insert_internal
│       │   │                   │       └─ [32.07%] lf_list_insert_internal
│       │   │                   │           ├─ [24.03%] lock_res_key_compare
│       │   │                   │           └─ [ 4.50%] lf_freelist_claim
│       │   │                   │               ├─ [ 2.46%] lock_alloc_resource → cub_alloc → __GI___libc_malloc
│       │   │                   │               │   └─ [ 1.94%] _int_malloc → sysmalloc → __mprotect (1.05%)
│       │   │                   │               └─ [ 1.38%] lf_stack_pop
│       │   │                   ├─ [ 5.89%] lf_freelist_claim
│       │   │                   │   └─ [ 2.53%] lf_freelist_alloc_block → __GI___libc_malloc → _int_malloc → sysmalloc → __mprotect
│       │   │                   ├─ [ 1.22%] lock_insert_into_tran_hold_list → __GI___pthread_mutex_lock
│       │   │                   └─ [ 0.50%] lock_event_set_xasl_id_to_entry → LOG_FIND_TDES
│       │   ├─ [ 5.90%] btree_advance_and_find_key
│       │   │   └─ [ 3.64%] btree_search_nonleaf_page
│       │   │       ├─ [ 1.12%] btree_read_record_without_decompression
│       │   │       ├─ [ 0.80%] btree_compare_key
│       │   │       └─ [ 0.52%] spage_get_record
│       │   ├─ [ 3.95%] btree_search_leaf_page
│       │   ├─ [ 3.17%] btree_get_root_with_key
│       │   │   └─ [ 2.25%] pgbuf_fix_release
│       │   └─ [ 1.38%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix
│       ├─ [ 2.50%] lock_object  (다른 caller)
│       │   ├─ [ 0.92%] lock_get_class_lock → __GI___pthread_mutex_lock
│       │   └─ [ 0.81%] lock_internal_perform_lock_object
│       └─ [ 2.01%] xbtree_find_unique → pgbuf_unfix
│           └─ [ 0.95%] __GI___pthread_mutex_lock
├─ [23.50%] locator_repl_prepare_force
│   ├─ [14.76%] heap_get_class_repr_id
│   │   ├─ [10.75%] heap_classrepr_free
│   │   │   ├─ [ 6.67%] __pthread_mutex_unlock_usercnt
│   │   │   │   └─ [ 4.85%] __lll_unlock_wake          ← 대기자 wake (contention 직접 증거)
│   │   │   └─ [ 3.65%] __GI___pthread_mutex_lock
│   │   │       └─ [ 3.20%] __lll_lock_wait
│   │   └─ [ 3.90%] heap_classrepr_get
│   │       ├─ [ 1.29%] __GI___pthread_mutex_lock
│   │       └─ [ 0.54%] __pthread_mutex_unlock_usercnt
│   ├─ [ 4.62%] heap_get_visible_version
│   │   ├─ [ 3.15%] heap_clean_get_context
│   │   │   └─ [ 2.47%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix
│   │   │       └─ [ 1.66%] pgbuf_unlatch_void_zone_bcb → pgbuf_lru_add_new_bcb_to_top → pgbuf_lru_adjust_zones (0.82%)
│   │   └─ [ 1.27%] heap_get_visible_version_internal → heap_prepare_get_context
│   └─ [ 3.55%] btree_get_pkey_btid
│       └─ [ 2.60%] heap_classrepr_free
│           ├─ [ 1.54%] __pthread_mutex_unlock_usercnt → __lll_unlock_wake (1.18%)
│           └─ [ 0.94%] __GI___pthread_mutex_lock → __lll_lock_wait (0.81%)
├─ [ 5.32%] xtran_server_end_topop → log_sysop_attach_to_outer
├─ [ 2.01%] xtran_server_start_topop → log_sysop_start
├─ [ 1.93%] heap_get_class_info → heap_hfid_cache_get → lf_hash_insert_internal
├─ [ 1.56%] heap_scancache_start_modify → file_get_type → pgbuf_fix_release
└─ [ 0.48%] heap_scancache_quick_end
```

---

## on-CPU Top Hot Spots (inclusive %)

| 순위 | leaf 함수 (트리에 등장한 정확한 이름) | on-CPU % | 분류 |
|------|---------------------------------------|----------|------|
| **1** | `lock_res_key_compare` | **24.03%** | lock-free hashmap key 비교 (CPU 직렬화) |
| **2** | `__libc_malloc → _int_malloc → sysmalloc → __mprotect` (두 경로 합) | **~10%** | glibc arena + 새 페이지 매핑 |
| **3** | `heap_classrepr_free` 영역 (mutex_unlock_usercnt + lock_wait) | **10.75%** | class repr cache mutex |
| 4 | `btree_search_*` (root + nonleaf + leaf) 합 | ~10.7% | btree page 탐색 |
| 5 | `xtran_server_end_topop` | 5.32% | sysop 종료 |
| 6 | `heap_get_visible_version` 영역 | 4.62% | MVCC visible-version 체크 |
| 7 | `__lll_unlock_wake` (heap_classrepr unlock 시 leaf) | 4.85% | 대기자 wake leaf |
| 8 | `heap_classrepr_get` (또 다른 cache lookup) | 3.90% | class repr cache 재호출 |
| 9 | `__lll_lock_wait` (heap_classrepr lock 시) | 3.20% | mutex slow-path |
| 10 | `pgbuf_unlatch_void_zone_bcb → pgbuf_lru_adjust_zones` | 1.34% | page buffer LRU 통계 |

---

## on-CPU 직렬화점 식별

### A. `lock_res_key_compare` — on-CPU 24.03% (단일 leaf 1위)

```
xbtree_find_unique → btree_key_find_and_lock_unique → btree_key_lock_object
  → lock_object → lock_internal_perform_lock_object
  → lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
  → lf_hash_insert_internal → lf_list_insert_internal
  → lock_res_key_compare  [24.03%]
```

mutex 가 아닌 **lock-free hash bucket linked-list 의 키 비교 hot loop**. 10명의 워커가 같은 자료구조를 CAS-traverse → CPU cache line 무효화로 직렬화. 워커가 잠들지 않고 CPU 태우면서 직렬화되는 spin-like contention. 워커 N 늘면 bucket 안 list 가 길어져 비교 횟수가 곱셈으로 증가하는 자료구조 특성.

### B. `heap_classrepr` cache mutex — on-CPU 10.75% (영역 단위)

```
locator_repl_prepare_force → heap_get_class_repr_id → heap_classrepr_free
  ├─ __pthread_mutex_unlock_usercnt → __lll_unlock_wake [4.85%]
  └─ __GI___pthread_mutex_lock → __lll_lock_wait [3.20%]
```

추가로 `btree_get_pkey_btid → heap_classrepr_free` 경로 (2.60%) 에서도 같은 mutex 호출. 두 경로 합 13.35%.

**`__lll_unlock_wake` 가 4.85% 차지가 결정적 증거**:
- futex `FUTEX_WAKE` syscall 은 **대기자가 0이면 즉시 return** — 코드 path 가 짧음
- 4.85% on-CPU 가 wake 경로에 쓰이는 건 = unlock 마다 **항상 wake 가 필요한 대기자 존재** = 워커 9명이 늘 줄섬
- 즉 mutex 가 짧게 잡혔다 풀렸다 반복되어 lock_wait 자체 비용 (3.20%) 보다 wake 가 더 큰 양상

### C. `__libc_malloc → sysmalloc → __mprotect` — on-CPU ~10%

```
lf_freelist_claim → (lock_alloc_resource → cub_alloc →) __GI___libc_malloc
  → _int_malloc → sysmalloc → __GI___mprotect → [kernel]
```

두 경로 합 약 10% (lockfree_hashmap 안 4.50% + 별도 5.89%). lock resource 할당 빈도가 매우 높아 glibc arena mutex + 새 페이지 mmap syscall 까지 도달. 페이지 매핑 syscall 이 kernel stack 깊게 들어가는 게 특징.

### D. btree page 탐색 — on-CPU ~10.7%

```
btree_search_nonleaf_page (3.64%) + btree_search_leaf_page (3.93%)
+ btree_get_root_with_key (3.17%, → pgbuf_fix_release 2.25%)
```

매 row PK 검색 시 btree root → nonleaf → leaf 페이지 fix 비용 누적. 페이지 read 자체 + spage_get_record + btree_compare_key 등 disk-or-cache I/O 비용.

### E. MVCC visible version — on-CPU 4.62%

```
heap_get_visible_version → heap_clean_get_context → pgbuf_unfix
  → pgbuf_unlatch_void_zone_bcb → pgbuf_lru_adjust_zones
```

UPDATE 매 row 마다 visible version 조회 → 페이지 unfix → page buffer LRU void-zone 통계 조정 (1.66%). LRU zone 보호 mutex 는 H-라벨 없이 보더라도 별개 직렬화점 후보.

### F. 부수 leaves (각 < 2%)

- `lock_get_class_lock → __pthread_mutex_lock` (0.92%) — class lock 획득
- `pgbuf_fix_release` 곳곳 (btree 탐색 안) — 페이지 fix 비용
- `xtran_server_start_topop / end_topop` (2.01% + 5.32%) — sysop 시작/종료 (cuberr context push/pop 포함)

---

## on-CPU only 결론

> UPDATE 워크로드의 on-CPU 시간은 다음 다섯 곳에 집중:
>
> 1. **`lock_res_key_compare` (24.03%)** — row-lock lock-free hashmap 의 CPU-bound 직렬화
> 2. **`heap_classrepr_free` 영역 (10.75% + 2.60% = 13.35%)** — class repr cache mutex.
>    `__lll_unlock_wake (4.85%)` 가 항상 대기자 있음을 직접 증언
> 3. **`__libc_malloc → sysmalloc → __mprotect` 합 (~10%)** — glibc arena + 페이지 mmap
> 4. **btree page 탐색 합 (~10.7%)** — root/nonleaf/leaf 페이지 fix
> 5. **MVCC `heap_get_visible_version` (4.62%)** + 그 안의 `pgbuf_unlatch_void_zone_bcb` (1.66%)
>
> `__lll_lock_wait` 자체는 on-CPU 3.67% 로 작아 보이지만 **`__lll_unlock_wake` 4.85%** 가 더 결정적인 contention 신호. mutex 가 짧게 잡혔다 풀렸다 반복되며 wait 시간보다 wake syscall 비용이 더 큰 패턴.

---

## 산출물 위치

`/home/youngjun/bench_sampling/perf-runs/update_20260519-170435/`

```
oncpu.data       (1.03 GB)   oncpu.folded     (3.6 MB)   oncpu_sflush.folded   (633 KB)
offcpu.data     (14.29 GB)   offcpu.folded               offcpu_sflush.folded
futex.data      (29.53 GB)   futex.folded
thread_counts.log (6.3 KB)
draw_tree.py     (재현/재분석용)
```
