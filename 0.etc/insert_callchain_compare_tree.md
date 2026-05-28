# INSERT 콜체인 비교 (트리 버전) — default (1.) vs tuned (4.)

비교 대상:
- `1.insert_call_chain/REPORT.md` 섹션 2 (default raw stack 트리, lif=100%, 0.3% 컷오프)
- `4.insert_call_chain_tuned/parallel_insert_perf_final.md` 섹션 2 (tuned, lif=100%, 0.3% 컷오프)

기준: `locator_insert_force` = 100% (lif inclusive %).
default 트리 구조를 기준으로 각 노드에 default/tuned 값과 Δ(=tuned−default)를 병기했습니다.
tuned 트리의 0.3% 컷오프로 사라진 노드는 `--` 로 표기 (실제로 사라진 게 아니라 컷오프 아래로 분산된 경우도 포함).

## 형식 설명

각 노드는 다음 형식으로 표기:

```
[default% / tn%, Δ] function_name
```

- **default%** — `1.insert_call_chain/REPORT.md` 섹션 2 트리에서 해당 노드의 inclusive % (lif=100% 기준으로 정규화). 즉, lif 가 들어간 전체 stack 중 이 호출 경로 (root→...→해당 노드) 가 등장한 비율.
- **tn%** — `4.insert_call_chain_tuned/parallel_insert_perf_final.md` 섹션 2 트리에서 같은 위치(같은 부모 경로 아래 같은 함수)의 inclusive %. tuned 트리는 0.3% 컷오프이므로 그 아래로 떨어진 노드는 `--` 로 표기.
- **Δ** — `tn% − default%`. 양수면 tuned 에서 비중이 늘어난 것, 음수면 줄어든 것. `−` 는 Unicode minus (U+2212), `+` 는 ASCII. tuned 가 `--` 면 Δ 도 `--`.

읽는 법:
- inclusive % 는 "그 노드 + 그 노드의 모든 자손 시간" 의 합 비율이므로, 자식 노드들의 % 합이 부모 % 보다 작거나 같음 (perf 의 다른 자식이 컷오프로 안 보일 수 있고, 자기 자신의 self-time 도 부모에 포함됨).
- 같은 함수가 트리의 다른 위치(다른 부모 경로 아래)에 등장하면 각 위치마다 별도의 노드로 나타남 → 위치별로 Δ 가 다를 수 있음. 함수명 기준으로 합산한 값은 `insert_callchain_compare.md` 의 표 참고.
- default 와 tuned 의 트리는 캡처 자체가 다르므로 (다른 빌드, 다른 시점), 같은 위치라도 약간의 노이즈가 섞일 수 있음. ±0.3% 정도의 작은 Δ 는 노이즈 가능성을 염두에 두고 해석.
- `--` 가 의미하는 것: tuned 트리의 0.3% 컷오프 아래로 분산됐거나, 실제로 거의 사라졌거나 둘 중 하나. 트리만으론 구분 불가 — `parallel_insert_perf_final.md` 의 perf script raw dump 를 직접 봐야 확정 가능.

예:
- `[80.22 / 74.92, −5.30] heap_insert_logical` → default 에선 lif 의 80.22% 가 이 경로로, tuned 에선 74.92% 로 5.30%p 감소.
- `[3.00 / --, --] thread_suspend_timeout_wakeup_and_unlock_entry` → default 에선 3.00% 잡혔지만 tuned 트리엔 컷오프 아래로 빠짐.
- `[6.61 / 13.45, +6.84] spage_insert_at` → tuned 에서 비중이 두 배 가까이 늘어남.

## 트리

```
[100.00 / 100.00, 0.00] locator_insert_force
├─ [80.22 / 74.92, −5.30] heap_insert_logical
│  ├─ [31.71 / 26.54, −5.17] heap_stats_find_best_page
│  │  ├─ [17.32 / 12.81, −4.51] file_alloc
│  │  │  ├─ [7.43 / 4.36, −3.07] pgbuf_fix_release
│  │  │  │  └─ [6.03 / 3.69, −2.34] pgbuf_claim_bcb_for_fix
│  │  │  │     ├─ [3.00 / --, --] thread_suspend_timeout_wakeup_and_unlock_entry
│  │  │  │     │  ├─ [2.60 / --, --] pthread_cond_timedwait
│  │  │  │     │  └─ [0.37 / --, --] __pthread_mutex_unlock_usercnt
│  │  │  │     │     └─ [0.37 / --, --] __lll_unlock_wake
│  │  │  │     └─ [0.78 / --, --] pgbuf_get_victim
│  │  │  │        └─ [0.40 / --, --] pgbuf_get_victim_from_lru_list
│  │  │  ├─ [2.99 / 3.08, +0.09] file_perm_alloc
│  │  │  │  ├─ [1.65 / 1.69, +0.04] log_append_undoredo_data2
│  │  │  │  │  └─ [1.62 / 1.64, +0.02] log_append_undoredo_crumbs
│  │  │  │  │     └─ [1.01 / 0.90, −0.11] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  │        └─ [0.79 / --, --] malloc
│  │  │  │  │           └─ [0.63 / --, --] _int_malloc
│  │  │  │  └─ [0.96 / 0.84, −0.12] log_append_undoredo_data
│  │  │  │     └─ [0.95 / 0.83, −0.12] log_append_undoredo_crumbs
│  │  │  │        └─ [0.54 / 0.52, −0.02] prior_lsa_alloc_and_copy_crumbs
│  │  │  │           └─ [0.46 / --, --] malloc
│  │  │  │              └─ [0.37 / --, --] _int_malloc
│  │  │  ├─ [2.77 / 2.04, −0.73] heap_vpid_init_new
│  │  │  │  ├─ [1.49 / 0.83, −0.66] log_append_undoredo_data
│  │  │  │  │  └─ [1.47 / 0.83, −0.64] log_append_undoredo_crumbs
│  │  │  │  │     ├─ [0.65 / --, --] prior_lsa_next_record_internal
│  │  │  │  │     └─ [0.60 / 0.43, −0.17] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  │        └─ [0.51 / --, --] malloc
│  │  │  │  │           └─ [0.33 / --, --] _int_malloc
│  │  │  │  └─ [0.92 / 0.88, −0.04] spage_insert
│  │  │  │     └─ [0.80 / 0.75, −0.05] spage_find_empty_slot
│  │  │  │        └─ [0.58 / 0.61, +0.03] spage_has_enough_total_space
│  │  │  │           └─ [0.32 / --, --] lf_hash_find
│  │  │  ├─ [1.77 / 1.33, −0.44] log_sysop_end_logical_undo
│  │  │  │  └─ [1.75 / 1.32, −0.43] log_sysop_commit_internal
│  │  │  │     └─ [1.09 / 0.69, −0.40] log_append_sysop_end
│  │  │  │        ├─ [0.59 / --, --] prior_lsa_next_record_internal
│  │  │  │        └─ [0.45 / 0.36, −0.09] prior_lsa_alloc_and_copy_data
│  │  │  ├─ [1.13 / 0.86, −0.27] pgbuf_unfix
│  │  │  │  └─ [0.75 / 0.57, −0.18] pgbuf_unlatch_void_zone_bcb
│  │  │  ├─ [0.49 / 1.30, +0.81] prior_lsa_next_record_internal
│  │  │  └─ [0.42 / 0.35, −0.07] log_sysop_start_atomic
│  │  ├─ [4.13 / 5.02, +0.89] log_append_undoredo_data
│  │  │  └─ [4.12 / 5.00, +0.88] log_append_undoredo_crumbs
│  │  │     ├─ [2.80 / 3.57, +0.77] prior_lsa_alloc_and_copy_crumbs
│  │  │     │  ├─ [1.19 / 0.98, −0.21] log_zip
│  │  │     │  │  └─ [0.93 / 0.71, −0.22] LZ4_resetStream_fast
│  │  │     │  │     └─ [0.87 / 0.64, −0.23] __memset_evex_unaligned_erms
│  │  │     │  └─ [0.75 / --, --] malloc
│  │  │     │     └─ [0.53 / --, --] _int_malloc
│  │  │     └─ [1.08 / 0.80, −0.28] prior_lsa_next_record_internal
│  │  │        ├─ [0.44 / --, --] __pthread_mutex_lock
│  │  │        └─ [0.33 / --, --] __pthread_mutex_unlock_usercnt
│  │  ├─ [1.91 / 1.44, −0.47] heap_stats_add_bestspace
│  │  │  ├─ [0.93 / 0.75, −0.18] mht_get
│  │  │  └─ [0.34 / --, --] __pthread_mutex_unlock_usercnt
│  │  ├─ [1.53 / 1.55, +0.02] spage_max_space_for_new_record
│  │  │  └─ [0.82 / 0.70, −0.12] lf_hash_find
│  │  │     └─ [0.38 / 0.44, +0.06] lf_list_find
│  │  ├─ [1.06 / 0.81, −0.25] log_sysop_commit
│  │  │  └─ [1.06 / 0.81, −0.25] log_sysop_commit_internal
│  │  │     └─ [0.90 / 0.49, −0.41] log_append_sysop_end
│  │  │        ├─ [0.53 / --, --] prior_lsa_next_record_internal
│  │  │        └─ [0.36 / --, --] prior_lsa_alloc_and_copy_data
│  │  │           └─ [0.35 / --, --] malloc
│  │  ├─ [0.82 / 1.76, +0.94] pgbuf_unfix
│  │  ├─ [0.75 / 0.84, +0.09] mht_get2
│  │  └─ [0.73 / --, --] __pthread_mutex_lock
│  ├─ [24.83 / 15.74, −9.09] lock_object
│  │  ├─ [24.02 / 14.67, −9.35] lock_internal_perform_lock_object
│  │  │  ├─ [18.20 / 10.86, −7.34] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│  │  │  │  └─ [17.60 / 10.52, −7.08] lf_hash_insert_internal
│  │  │  │     ├─ [14.23 / 7.54, −6.69] lock_res_key_compare
│  │  │  │     └─ [1.39 / 1.11, −0.28] lf_freelist_claim
│  │  │  │        ├─ [0.84 / 0.57, −0.27] lf_freelist_alloc_block
│  │  │  │        │  └─ [0.83 / 0.55, −0.28] lock_alloc_resource
│  │  │  │        │     └─ [0.82 / --, --] malloc
│  │  │  │        │        └─ [0.61 / --, --] _int_malloc
│  │  │  │        └─ [0.36 / 0.36, 0.00] lf_stack_pop
│  │  │  ├─ [3.75 / 3.07, −0.68] lf_freelist_claim
│  │  │  │  ├─ [2.25 / 1.51, −0.74] lf_freelist_alloc_block
│  │  │  │  │  └─ [2.24 / --, --] malloc
│  │  │  │  │     └─ [2.00 / --, --] _int_malloc
│  │  │  │  │        ├─ [0.98 / --, --] sysmalloc
│  │  │  │  │        │  └─ [0.88 / --, --] __mprotect
│  │  │  │  │        └─ [0.56 / --, --] malloc_consolidate
│  │  │  │  └─ [0.87 / 0.82, −0.05] lf_stack_pop
│  │  │  └─ [0.64 / --, --] lock_insert_into_tran_hold_list
│  │  │     └─ [0.58 / --, --] __pthread_mutex_lock
│  │  └─ [0.34 / 0.48, +0.14] lock_get_class_lock
│  ├─ [13.98 / 15.15, +1.17] heap_log_insert_physical
│  │  ├─ [12.26 / 13.40, +1.14] log_append_undoredo_crumbs
│  │  │  ├─ [7.55 / 8.42, +0.87] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  ├─ [3.52 / 3.69, +0.17] log_zip
│  │  │  │  │  └─ [2.72 / 2.64, −0.08] LZ4_resetStream_fast
│  │  │  │  │     └─ [2.53 / 2.40, −0.13] __memset_evex_unaligned_erms
│  │  │  │  ├─ [1.49 / --, --] malloc
│  │  │  │  │  └─ [0.83 / --, --] _int_malloc
│  │  │  │  ├─ [0.65 / 0.75, +0.10] prior_lsa_copy_redo_data_to_node
│  │  │  │  │  └─ [0.55 / --, --] malloc
│  │  │  │  │     └─ [0.41 / --, --] _int_malloc
│  │  │  │  └─ [0.51 / 0.71, +0.20] __memmove_evex_unaligned_erms
│  │  │  ├─ [2.99 / 2.10, −0.89] prior_lsa_next_record_internal
│  │  │  │  ├─ [0.89 / --, --] __pthread_mutex_lock
│  │  │  │  └─ [0.77 / 0.34, −0.43] __pthread_mutex_unlock_usercnt
│  │  │  └─ [0.36 / 0.47, +0.11] log_does_allow_replication
│  │  ├─ [0.52 / 0.55, +0.03] heap_page_update_chain_after_mvcc_op
│  │  └─ [0.32 / --, --] heap_page_get_vacuum_status@plt
│  ├─ [6.61 / 13.45, +6.84] spage_insert_at
│  │  ├─ [5.31 / 11.57, +6.26] spage_insert_data
│  │  │  └─ [4.94 / 11.27, +6.33] __memmove_evex_unaligned_erms
│  │  └─ [1.12 / 1.63, +0.51] spage_find_empty_slot_at
│  │     └─ [0.83 / 1.18, +0.35] spage_check_space
│  │        └─ [0.80 / 1.14, +0.34] spage_has_enough_total_space
│  │           └─ [0.33 / 0.43, +0.10] lf_hash_find
│  └─ [0.90 / 2.50, +1.60] pgbuf_unfix
├─ [16.84 / 21.13, +4.29] locator_add_or_remove_index_internal
│  ├─ [5.64 / 6.78, +1.14] repl_log_insert       ★ master-only (송신측 replication log)
│  │  ├─ [0.86 / --, --] malloc
│  │  │  └─ [0.62 / --, --] _int_malloc
│  │  ├─ [0.86 / 0.63, −0.23] repl_log_info_alloc
│  │  │  └─ [0.60 / --, --] realloc
│  │  │     └─ [0.58 / --, --] mremap_chunk
│  │  │        └─ [0.56 / --, --] __GI___mremap
│  │  ├─ [0.75 / 1.00, +0.25] heap_get_class_name_alloc_if_diff
│  │  ├─ [0.61 / 0.67, +0.06] heap_get_class_tde_algorithm
│  │  ├─ [0.55 / 0.98, +0.43] or_packed_value_size
│  │  └─ [0.42 / 0.70, +0.28] or_pack_mem_value
│  ├─ [4.68 / 5.99, +1.31] heap_get_class_name_alloc_if_diff
│  │  ├─ [1.62 / --, --] malloc
│  │  │  └─ [1.41 / --, --] _int_malloc
│  │  ├─ [0.95 / 1.42, +0.47] heap_get_class_record
│  │  │  └─ [0.39 / 0.48, +0.09] heap_get_last_version
│  │  ├─ [0.82 / 1.11, +0.29] heap_scancache_end
│  │  │  └─ [0.81 / 1.09, +0.28] heap_scancache_quick_end
│  │  │     └─ [0.65 / 0.66, +0.01] pgbuf_unfix
│  │  └─ [0.33 / 0.62, +0.29] heap_scancache_quick_start_root_hfid
│  ├─ [1.12 / 1.68, +0.56] heap_attrinfo_read_dbvalues
│  ├─ [1.08 / 1.57, +0.49] heap_attrinfo_end
│  │  └─ [0.36 / 0.35, −0.01] heap_classrepr_free
│  ├─ [0.62 / 1.02, +0.40] heap_attrvalue_get_key
│  ├─ [0.60 / 0.92, +0.32] heap_attrinfo_start_with_index
│  └─ [0.44 / 0.49, +0.05] btree_insert
└─ [2.09 / 2.75, +0.66] locator_check_foreign_key
   ├─ [0.96 / 1.34, +0.38] heap_attrinfo_start_with_index
   │  └─ [0.37 / 0.50, +0.13] heap_classrepr_get
   └─ [0.46 / 0.63, +0.17] heap_attrinfo_read_dbvalues
```

## 주요 변화 (큰 Δ 만)

### 줄어든 경로 (tuned 가 더 작음)
- `lock_object` 서브트리: 24.83 → 15.74 (−9.09), 자식 `lock_internal_perform_lock_object` −9.35, `lockfree_hashmap::find_or_insert` −7.34, `lf_hash_insert_internal` −7.08, `lock_res_key_compare` −6.69 — lock contention 경로가 전체적으로 감소.
- `heap_stats_find_best_page` 서브트리: 31.71 → 26.54 (−5.17), `file_alloc` 안의 `pgbuf_fix_release` (−3.07), `pgbuf_claim_bcb_for_fix` (−2.34) — page allocation/victim 경로 줄어듦. tuned 측은 `thread_suspend_timeout_wakeup_and_unlock_entry` / `pgbuf_get_victim` 가 컷오프 아래로 빠졌으므로 실제 감소폭은 표 값보다 더 클 수 있음.

### 늘어난 경로 (tuned 가 더 큼)
- `spage_insert_at`: 6.61 → 13.45 (+6.84), 자식 `spage_insert_data` +6.26, 그 자식 `__memmove_evex_unaligned_erms` +6.33 — record body 복사가 절대비 기준 2배 가까이 늘어남 (lock/wait 가 줄어든 만큼 실제 work 비중이 커진 효과).
- `locator_add_or_remove_index_internal`: 16.84 → 21.13 (+4.29), 안쪽으로 `repl_log_insert` +1.14, `heap_get_class_name_alloc_if_diff` +1.31.
- `pgbuf_unfix` (lock_object 형제): 0.90 → 2.50 (+1.60).
- `heap_log_insert_physical`: 13.98 → 15.15 (+1.17).

## 주의

- tuned 트리의 0.3% 컷오프 때문에 `malloc` / `_int_malloc` / `__pthread_mutex_lock` / `__pthread_mutex_unlock_usercnt` / `pthread_cond_timedwait` / `__lll_unlock_wake` / `thread_suspend_timeout_wakeup_and_unlock_entry` / `pgbuf_get_victim` / `pgbuf_get_victim_from_lru_list` / `sysmalloc` / `__mprotect` / `malloc_consolidate` / `lock_insert_into_tran_hold_list` / `realloc` / `mremap_chunk` / `__GI___mremap` / `heap_page_get_vacuum_status@plt` 등은 트리에 안 잡혀서 `--` 로 표기. **완전히 사라진 게 아니라 컷오프 아래로 분산됐을 수 있음.**
- 두 캡처의 lif 자체 비중 (전체 on-CPU 중) — default: 5.13%, tuned: 5.78% — 은 다르지만, 위 트리는 두 쪽 모두 lif=100% 로 정규화한 값이므로 함수별 비율 비교는 그대로 유효함.
- 함수별 누적 합산값 (같은 함수가 트리 여러 위치에 등장할 때 합) 은 `insert_callchain_compare.md` 의 표 참고.
