# UPDATE — Worker 2 (활성화 워커 2개) — 슬레이브 서버 측 perf 측정 결과

- **활성화 워커: 2 / 비활성화 워커: 8**
- 빌드 모드: Release / 부하 도구: ha-bench (csql 병렬)
- 워크로드: tbl1 ~ tbl10, 각 10만 건 **UPDATE** / 단일 트랜잭션
- 측정 대상: **슬레이브 데이터베이스 서버 프로세스** (`$SERVER_PID`=1174174) + **applylogdb** (`$APPLY_PID`=1174429)

---

## 캡쳐 방법

```bash
# on-CPU (본 보고서는 on-CPU 기준 분석)
sudo -n perf record -F 999 -g --call-graph dwarf -p $SERVER_PID,$APPLY_PID -o oncpu.data
```

- 샘플링 주파수: 999 Hz
- 콜그래프 모드: dwarf
- 캡쳐 시간: 2분 12초 (132 초)
- on-CPU samples: 17,377 (sflush 가지 안 1,050 samples)
- 후처리 필터: `slocator_repl_force` / `xlocator_repl_force` 스택만
- applylogdb thread peak: **4** (= main + monitor + worker × 2)

> (참고) 같은 윈도우에 off-CPU/futex 트랙도 함께 capture 했으나 본 보고서는 **on-CPU 만** 분석. off-CPU/futex 는 별도.

---

## 콜체인 (on-CPU, `xlocator_repl_force` 하위, inc=99.87%)

```
[100.00%] xlocator_repl_force
├─ [ 68.36%] locator_repl_prepare_force                                    ← 본 측정의 메인 분지
│   ├─ [ 56.15%] xbtree_find_unique                                         (UPDATE 본 워크로드: PK lookup)
│   │   ├─ [ 31.27%] btree_search_key_and_apply_functions
│   │   │   ├─ [ 18.07%] btree_key_find_and_lock_unique
│   │   │   │   └─ [ 17.95%] btree_key_find_and_lock_unique_of_unique
│   │   │   │       └─ [ 16.16%] btree_key_lock_object
│   │   │   │           └─ [ 15.83%] lock_object
│   │   │   │               └─ [ 14.59%] lock_internal_perform_lock_object
│   │   │   │                   ├─ [  6.30%] lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│   │   │   │                   │   └─ [  6.20%] lf_hash_insert_internal
│   │   │   │                   │       └─ [  4.48%] lf_list_insert_internal
│   │   │   │                   │           ├─ [  2.84%] lf_freelist_claim
│   │   │   │                   │           │   └─ [  2.50%] lf_stack_pop
│   │   │   │                   │           └─ [  0.74%] __GI___pthread_mutex_lock
│   │   │   │                   ├─ [  3.67%] lf_freelist_claim
│   │   │   │                   ├─ [  1.77%] lock_insert_into_tran_hold_list → __GI___pthread_mutex_lock
│   │   │   │                   └─ [  0.87%] lock_escalate_if_needed
│   │   │   ├─ [ 12.42%] btree_advance_and_find_key
│   │   │   │   └─ [  8.59%] btree_search_nonleaf_page
│   │   │   │       ├─ [  2.20%] btree_read_record_without_decompression
│   │   │   │       ├─ [  1.81%] btree_compare_key
│   │   │   │       └─ [  1.29%] spage_get_record
│   │   │   ├─ [  8.94%] btree_search_leaf_page
│   │   │   ├─ [  4.28%] btree_get_root_with_key
│   │   │   │   └─ [  2.31%] pgbuf_fix_release
│   │   │   └─ [  5.55%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix (4.27%)
│   │   ├─ [  4.93%] lock_object  (다른 caller)
│   │   │   ├─ [  1.48%] lock_get_class_lock → __GI___pthread_mutex_lock (0.68%)
│   │   │   └─ [  1.77%] lock_internal_perform_lock_object
│   │   └─ [  2.31%] xbtree_find_unique → pgbuf_fix_release
│   ├─ [  8.18%] heap_get_visible_version
│   │   ├─ [  4.42%] heap_clean_get_context
│   │   │   └─ [  3.92%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix (1.45%)
│   │   │       └─ [  1.86%] pgbuf_unlatch_void_zone_bcb → pgbuf_lru_add_new_bcb_to_top (1.50%) → pgbuf_lru_adjust_zones (1.26%)
│   │   └─ [  3.13%] heap_get_visible_version_internal → heap_prepare_get_context (2.28%)
│   ├─ [  2.88%] heap_get_class_repr_id
│   │   ├─ [  1.88%] heap_classrepr_get
│   │   │   ├─ [  0.43%] __GI___pthread_mutex_lock
│   │   │   └─ [  0.78%] __pthread_mutex_unlock_usercnt
│   │   └─ [  0.77%] heap_classrepr_free
│   │       ├─ [  0.34%] __pthread_mutex_unlock_usercnt → __lll_unlock_wake (0.23%)
│   │       └─ [  0.33%] __GI___pthread_mutex_lock
│   └─ [  2.75%] btree_get_pkey_btid
│       └─ [  0.69%] heap_classrepr_free → __GI___pthread_mutex_lock (0.56%)
├─ [ 11.90%] xtran_server_end_topop
│   ├─ [  4.69%] log_sysop_attach_to_outer → log_tdes::unlock_topop (3.68%) → cubpl::get_session (2.19%)
│   ├─ [  3.67%] cuberr::context::pop_error_stack_and_destroy
│   └─ [  2.17%] cuberr::context::push_error_stack → operator new → __GI___libc_malloc
├─ [  5.27%] xlocator_repl_force (재귀)
│   ├─ [  2.88%] heap_get_class_repr_id
│   └─ [  2.04%] or_unpack_mem_value
├─ [  4.77%] xtran_server_start_topop → log_sysop_start (4.20%)
├─ [  3.45%] heap_get_class_info → heap_hfid_cache_get (3.45%) → lf_hash_insert_internal
├─ [  2.41%] heap_scancache_start_modify → file_get_type → pgbuf_fix_release
└─ [  0.83%] heap_scancache_quick_end
```

---

## on-CPU Top Hot Spots (inclusive %)

| 순위 | leaf / 영역 (트리에 등장한 정확한 이름) | on-CPU % | 분류 |
|------|------------------------------------------|---------:|------|
| **1** | `btree_search_*` (root + nonleaf + leaf) 합 | **21.79%** | btree page 탐색 (PK lookup) |
| **2** | `lock_object → lock_internal_perform_lock_object` | **14.59%** | row-lock 자료구조 진입 |
| **3** | `xbtree_find_unique → btree_advance_and_find_key` | **12.42%** | btree 탐색 (재귀 가지) |
| **4** | `xtran_server_end_topop` | **11.90%** | sysop 종료 (cuberr push/pop + log_sysop_attach_to_outer) |
| **5** | `heap_get_visible_version` 영역 | **8.18%** | MVCC visible-version 체크 |
| 6 | `lockfree_hashmap::find_or_insert` | 6.30% | row-lock lock-free hashmap |
| 7 | `pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix` (btree 탐색 안) | 5.98% | page buffer unfix |
| 8 | `xtran_server_start_topop` | 4.77% | sysop 시작 |
| 9 | `lf_list_insert_internal` (lockfree hashmap insert leaf) | 4.48% | lockfree hashmap insert |
| 10 | `heap_get_class_info → heap_hfid_cache_get` | 3.45% | hfid 캐시 lookup |
| 11 | `heap_classrepr_free` 영역 (mutex unlock + lock_wait) | ~1.46% | class repr cache mutex |
| 12 | `pgbuf_unlatch_void_zone_bcb → pgbuf_lru_adjust_zones` | 1.26% | page buffer LRU 통계 |

---

## on-CPU 직렬화점 식별

### A. btree page 탐색 — on-CPU 21.79% (단일 영역 1위)

```
xbtree_find_unique → btree_search_key_and_apply_functions
  ├─ btree_advance_and_find_key → btree_search_nonleaf_page [ 8.59%]
  │     ├─ btree_read_record_without_decompression          [ 2.20%]
  │     ├─ btree_compare_key                                 [ 1.81%]
  │     └─ spage_get_record                                  [ 1.29%]
  ├─ btree_search_leaf_page                                  [ 8.94%]
  └─ btree_get_root_with_key                                 [ 4.28%]
        └─ pgbuf_fix_release                                 [ 2.31%]
```

UPDATE 매 row 마다 PK 로 row 위치를 찾기 위해 btree root → nonleaf → leaf 페이지를 fix/탐색한다. 페이지 read 자체 + `spage_get_record` 슬롯 조회 + `btree_compare_key` 키 비교가 모두 누적되어 본 측정에서 가장 큰 단일 영역을 차지. UPDATE row 당 고정 비용이라 워커 수와 무관하게 발생.

### B. row-lock 자료구조 진입 — on-CPU 14.59%

```
xbtree_find_unique → btree_key_find_and_lock_unique
  → btree_key_lock_object → lock_object
  → lock_internal_perform_lock_object              [14.59%]
      ├─ lockfree_hashmap::find_or_insert         [ 6.30%]
      │   └─ lf_hash_insert_internal               [ 6.20%]
      │       └─ lf_list_insert_internal           [ 4.48%]
      │           └─ lf_freelist_claim             [ 2.84%]
      │               └─ lf_stack_pop              [ 2.50%]
      ├─ lf_freelist_claim (직계)                  [ 3.67%]
      └─ lock_insert_into_tran_hold_list           [ 1.77%]
              → __GI___pthread_mutex_lock           [ 1.77%]
```

매 row 의 PK 락을 잡기 위해 lock-free hashmap 의 bucket 을 traverse 한다. 워커 2 환경에서는 hashmap bucket 안 list 가 짧아 비교 hot loop (`lock_res_key_compare`) 가 별도 leaf 로 잡히지 않으며, `lock_internal_perform_lock_object` 자체의 비중도 14.59% 로 §A 보다 작다. **본 측정에서는 lock-free 자료구조 진입이 CPU-bound 직렬화 점이 아닌 일반 비용 항목** 이다.

### C. sysop 시작/종료 — on-CPU 16.67% (4.77% + 11.90%)

```
xtran_server_end_topop                              [11.90%]
  ├─ log_sysop_attach_to_outer                      [ 4.69%]
  │   └─ log_tdes::unlock_topop                     [ 3.68%]
  │       └─ cubpl::get_session                     [ 2.19%]
  ├─ cuberr::context::pop_error_stack_and_destroy   [ 3.67%]
  └─ cuberr::context::push_error_stack              [ 2.17%]
        → operator new → __GI___libc_malloc

xtran_server_start_topop                            [ 4.77%]
  └─ log_sysop_start                                [ 4.20%]
```

매 UPDATE 한 건마다 server-side sub-transaction (sysop) 을 시작/종료. 종료 쪽이 더 비싸 (`cuberr` 컨텍스트 push/pop + sysop unlock + PL session lookup) 11.90% 를 차지. 새 error stack 객체 할당에서 glibc malloc 까지 도달.

### D. MVCC visible version 체크 — on-CPU 8.18%

```
heap_get_visible_version                            [ 8.18%]
  ├─ heap_clean_get_context                         [ 4.42%]
  │   └─ pgbuf_unfix                                [ 3.92%]
  │       └─ pgbuf_unlatch_bcb_upon_unfix           [ 1.45%]
  │       └─ pgbuf_unlatch_void_zone_bcb            [ 1.86%]
  │           └─ pgbuf_lru_add_new_bcb_to_top       [ 1.50%]
  │               └─ pgbuf_lru_adjust_zones         [ 1.26%]
  └─ heap_get_visible_version_internal              [ 3.13%]
      └─ heap_prepare_get_context                   [ 2.28%]
```

UPDATE 매 row 마다 MVCC visible version 을 조회 → 페이지 unfix → page buffer LRU void-zone 통계 조정. `pgbuf_lru_adjust_zones` (1.26%) 가 LRU zone 보호 mutex 의 별개 직렬화점 후보지만 본 측정 sample 안에서는 hot leaf 가 아님.

### E. class representation cache mutex — on-CPU 1.46% (영역 단위)

```
locator_repl_prepare_force
  ├─ heap_get_class_repr_id → heap_classrepr_free   [ 0.77%]
  │     ├─ __pthread_mutex_unlock_usercnt           [ 0.34%]
  │     │   └─ __lll_unlock_wake                    [ 0.23%]
  │     └─ __GI___pthread_mutex_lock                [ 0.33%]
  └─ btree_get_pkey_btid → heap_classrepr_free      [ 0.69%]
        └─ __GI___pthread_mutex_lock (0.56%)
```

`heap_classrepr_free` 영역 합 ~1.46%. `__lll_unlock_wake` 0.23% 와 `__lll_lock_wait` 본 측정 한계 이하 — mutex 코드 경로는 살아있지만 **대기자가 거의 없어 contention 신호가 약함**. 본 측정에서는 직렬화점이라기보다는 일반 cache lookup 비용.

### F. 부수 leaves (각 < 4%)

- `lf_list_insert_internal` 안의 `__GI___pthread_mutex_lock` (0.74%) — bucket-level mutex
- `lock_get_class_lock → __pthread_mutex_lock` (0.68%) — class lock 획득
- `pgbuf_fix_release` 곳곳 (btree 탐색 안) — 페이지 fix 비용
- `heap_get_class_info → heap_hfid_cache_get` (3.45%) — hfid 캐시 lookup (별도 lockfree hashmap)
- `heap_scancache_start_modify` (2.41%) / `heap_scancache_quick_end` (0.83%) — scan cache 시작/종료

---

## on-CPU only 결론

> 워커 2 환경에서 UPDATE 워크로드의 on-CPU 시간은 다음 다섯 곳에 집중:
>
> 1. **btree page 탐색 합 (21.79%)** — root/nonleaf/leaf 페이지 fix 가 가장 큰 영역. UPDATE row 당 PK lookup 의 고정 비용.
> 2. **row-lock 자료구조 진입 (14.59%)** — `lock_object → lock_internal_perform_lock_object → lockfree_hashmap` 경로. lock-free hashmap 자체는 진입하지만 bucket list 가 짧아 비교 hot loop 는 별도 leaf 로 검출되지 않음.
> 3. **sysop 시작/종료 합 (16.67%)** — sysop 종료 (cuberr 컨텍스트 + log_sysop_attach_to_outer + PL session lookup) 가 11.90%, 시작 4.77%. UPDATE row 당 server-side sub-tran 비용.
> 4. **MVCC visible version (8.18%)** + 그 안의 page buffer LRU 조정 (1.26%) — UPDATE row 당 고정 비용.
> 5. **class repr cache mutex 영역 (1.46%)** + **page buffer LRU void-zone (1.86%)** — mutex 경로는 존재하나 대기자/wake 신호가 본 측정 한계 이하. 별도 직렬화 점으로 확정할 만한 contention 신호 없음.
>
> 본 측정의 핫스팟은 모두 **per-row 의 본체 작업 (btree, sysop, MVCC)** 으로 구성되며, lock contention 류 leaf (`__lll_lock_wait`, `__lll_unlock_wake`, lockfree hashmap 의 키 비교 hot loop) 는 측정 sample 안에서 직접적 비용으로 잡히지 않는다.

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
