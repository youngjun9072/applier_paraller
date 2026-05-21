# v2 insert — master cub_server 콜체인

캡처: `master-insert-v2-20260520-165550/oncpu.data` (3.49 GB, 432,195 samples)
기준점: `locator_insert_force`
  - perf report Children = **5.13% of total on-CPU**
  - raw stack tally: `locator_insert_force` 가 포함된 sample = **21,071** (= 100% of lif)

원본 산출물:
  - `oncpu.data` / `oncpu.script` (raw perf data + 텍스트 dump)
  - `analysis/lif_callgraph_top-down.txt` (perf report 전체 트리)
  - `analysis/lif_callgraph_top-down_compact_0.05pct.txt` (% of total, 0.05% 컷오프)
  - `analysis/lif_callgraph_bottom-up_entry.txt` (entry chain)
  - `analysis/lif_callgraph_raw_normalized_0.3pct.txt` (raw stack 트리, lif=100%)
  - `analysis/lif_raw_inclusive_table_section3.txt` (섹션 3 표)

---

## 섹션 1 — 부모 함수 & lif 콜체인 (% of total on-CPU, 0.05% 컷오프)

전체 on-CPU 중 INSERT 경로가 차지하는 비중을 보는 용도.

### 1-1) 부모 함수 — caller chain (entry path)

```
[__GI___clone]
  └─ start_thread
       └─ execute_native_thread_routine
            └─ cubthread::worker_pool::core::worker::run
                 └─ cubthread::worker_pool::core::worker::execute_current_task
                      └─ css_server_task::execute              (worker dispatch)
                           └─ css_server_task::execute         (inner)
                                └─ net_server_request          (request demux)
                                     └─ sqmgr_execute_query    (server stub)
                                          └─ xqmgr_execute_query         ★ engine entry
                                               └─ qmgr_process_query
                                                    └─ qexec_execute_query
                                                         └─ qexec_execute_mainblock
                                                              └─ qexec_execute_mainblock (재귀, INSERT 서브플랜)
                                                                   └─ qexec_execute_insert    ★ per-row INSERT 부모
                                                                        └─ locator_attribute_info_force
                                                                             └─ locator_insert_force
```

### 1-2) `locator_insert_force` 콜체인 (top-down, % of total, 0.05% 컷오프)

```
[5.13%] locator_insert_force
├─ [4.08%] heap_insert_logical
│   ├─ [1.92%] heap_insert_logical (재귀)
│   │   ├─ [1.54%] heap_stats_find_best_page
│   │   │   ├─ [0.74%] heap_stats_find_best_page (재귀)
│   │   │   │   └─ [0.67%] file_alloc
│   │   │   │       ├─ [0.21%] pgbuf_fix_release
│   │   │   │       │   └─ [0.18%] pgbuf_claim_bcb_for_fix
│   │   │   │       │       ├─ [0.08%] pgbuf_allocate_bcb
│   │   │   │       │       └─ [0.07%] pgbuf_claim_bcb_for_fix
│   │   │   │       │           └─ [0.06%] thread_suspend_timeout_wakeup_and_unlock_entry
│   │   │   │       ├─ [0.14%] file_perm_alloc
│   │   │   │       │   ├─ [0.08%] log_append_undoredo_data2
│   │   │   │       │   │   └─ [0.08%] log_append_undoredo_crumbs
│   │   │   │       │   └─ [0.06%] file_perm_alloc (재귀)
│   │   │   │       ├─ [0.13%] heap_vpid_init_new
│   │   │   │       │   └─ [0.07%] log_append_undoredo_data
│   │   │   │       │       └─ [0.07%] log_append_undoredo_crumbs
│   │   │   │       ├─ [0.08%] log_sysop_end_logical_undo
│   │   │   │       │   └─ [0.08%] log_sysop_commit_internal
│   │   │   │       │       └─ [0.05%] log_append_sysop_end
│   │   │   │       └─ [0.05%] pgbuf_unfix
│   │   │   │   └─ [0.07%] spage_max_space_for_new_record
│   │   │   │       └─ [0.06%] spage_get_total_saved_spaces
│   │   │   │           └─ [0.05%] spage_get_saved_spaces
│   │   │   ├─ [0.37%] heap_vpid_alloc
│   │   │   │   ├─ [0.22%] log_append_undoredo_data → log_append_undoredo_crumbs
│   │   │   │   │   ├─ [0.15%] prior_lsa_alloc_and_copy_crumbs
│   │   │   │   │   │   └─ [0.13%] prior_lsa_gen_undoredo_record_from_crumbs
│   │   │   │   │   │       └─ [0.06%] log_zip
│   │   │   │   │   │           └─ [0.05%] LZ4_resetStream_fast
│   │   │   │   │   └─ [0.06%] prior_lsa_next_record_internal
│   │   │   │   └─ [0.06%] log_sysop_commit → log_sysop_commit_internal
│   │   │   ├─ [0.22%] heap_stats_find_page_in_bestspace
│   │   │   │   └─ [0.06%] heap_stats_add_bestspace
│   │   │   └─ [0.11%] heap_stats_find_best_page (재귀)
│   │   │       └─ [0.10%] file_alloc
│   │   └─ [0.36%] spage_insert_at
│   │       ├─ [0.29%] spage_insert_data
│   │       │   └─ [0.27%] __memmove_evex_unaligned_erms
│   │       └─ [0.06%] spage_find_empty_slot_at
│   ├─ [1.29%] heap_get_insert_location_with_lock (inlined)
│   │   └─ [1.25%] lock_object
│   │       └─ [1.23%] lock_internal_perform_lock_object
│   │           ├─ [0.95%] lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│   │           │   └─ [0.92%] lf_hash_insert_internal
│   │           │       └─ [0.90%] lf_list_insert_internal
│   │           │           ├─ [0.74%] lock_res_key_compare
│   │           │           └─ [0.07%] lf_freelist_claim
│   │           └─ [0.20%] lf_freelist_claim
│   │               └─ [0.12%] lf_freelist_alloc_block
│   │                   └─ [0.12%] __GI___libc_malloc
│   │                       └─ [0.11%] _int_malloc
│   │                           └─ [0.05%] sysmalloc
│   └─ [0.74%] heap_log_insert_physical
│       └─ [0.65%] heap_log_insert_physical (재귀)
│           └─ [0.65%] log_append_undoredo_crumbs
│               ├─ [0.40%] prior_lsa_alloc_and_copy_crumbs
│               │   ├─ [0.19%] prior_lsa_alloc_and_copy_crumbs (재귀)
│               │   │   └─ [0.18%] log_zip
│               │   │       └─ [0.16%] (LZ4 inlined chain)
│               │   │           └─ [0.14%] LZ4_resetStream_fast
│               │   │               └─ [0.13%] __memset_evex_unaligned_erms
│               │   ├─ [0.15%] prior_lsa_gen_undoredo_record_from_crumbs
│               │   └─ [0.05%] cub_alloc
│               └─ [0.16%] prior_lsa_next_record_internal
│                   └─ [0.09%] prior_lsa_next_record_internal (재귀)
│       └─ [0.08%] heap_mvcc_log_insert
├─ [0.89%] locator_add_or_remove_index_internal
│   ├─ [0.30%] repl_log_insert       ★ master-only (송신측 replication log 생성)
│   ├─ [0.25%] heap_get_class_name_alloc_if_diff
│   │   ├─ [0.10%] cub_strdup
│   │   │   └─ [0.09%] cub_alloc → __GI___libc_malloc → _int_malloc [0.08%]
│   │   └─ [0.05%] heap_get_class_record
│   ├─ [0.06%] heap_attrinfo_read_dbvalues
│   └─ [0.06%] heap_attrinfo_end
└─ [0.11%] locator_check_foreign_key
    └─ [0.05%] heap_attrinfo_start_with_index
```

---

## 섹션 2 — `locator_insert_force` 콜체인 (raw stack 트리, lif = 100%, 0.3% 컷오프)

raw `perf script` 의 stack 직접 집계 (perf report 의 cycles 가중치가 아닌 sample 단위).
lif-containing sample = 21,071 → 100%.
분산되어 perf report 트리 컷오프에 가렸던 함수들 (`malloc`, `__pthread_mutex_lock`, `__lll_lock_wait`, `__lll_unlock_wake`, `pthread_cond_timedwait` 등) 도 포함.

```
[100.00%] locator_insert_force
   ├─ [80.22%] heap_insert_logical
   │  ├─ [31.71%] heap_stats_find_best_page
   │  │  ├─ [17.32%] file_alloc
   │  │  │  ├─ [ 7.43%] pgbuf_fix_release
   │  │  │  │  └─ [ 6.03%] pgbuf_claim_bcb_for_fix
   │  │  │  │     ├─ [ 3.00%] thread_suspend_timeout_wakeup_and_unlock_entry
   │  │  │  │     │  ├─ [ 2.60%] pthread_cond_timedwait
   │  │  │  │     │  └─ [ 0.37%] __pthread_mutex_unlock_usercnt
   │  │  │  │     │     └─ [ 0.37%] __lll_unlock_wake
   │  │  │  │     └─ [ 0.78%] pgbuf_get_victim
   │  │  │  │        └─ [ 0.40%] pgbuf_get_victim_from_lru_list
   │  │  │  ├─ [ 2.99%] file_perm_alloc
   │  │  │  │  ├─ [ 1.65%] log_append_undoredo_data2
   │  │  │  │  │  └─ [ 1.62%] log_append_undoredo_crumbs
   │  │  │  │  │     └─ [ 1.01%] prior_lsa_alloc_and_copy_crumbs
   │  │  │  │  │        └─ [ 0.79%] malloc
   │  │  │  │  │           └─ [ 0.63%] _int_malloc
   │  │  │  │  └─ [ 0.96%] log_append_undoredo_data
   │  │  │  │     └─ [ 0.95%] log_append_undoredo_crumbs
   │  │  │  │        └─ [ 0.54%] prior_lsa_alloc_and_copy_crumbs
   │  │  │  │           └─ [ 0.46%] malloc
   │  │  │  │              └─ [ 0.37%] _int_malloc
   │  │  │  ├─ [ 2.77%] heap_vpid_init_new
   │  │  │  │  ├─ [ 1.49%] log_append_undoredo_data
   │  │  │  │  │  └─ [ 1.47%] log_append_undoredo_crumbs
   │  │  │  │  │     ├─ [ 0.65%] prior_lsa_next_record_internal
   │  │  │  │  │     └─ [ 0.60%] prior_lsa_alloc_and_copy_crumbs
   │  │  │  │  │        └─ [ 0.51%] malloc
   │  │  │  │  │           └─ [ 0.33%] _int_malloc
   │  │  │  │  └─ [ 0.92%] spage_insert
   │  │  │  │     └─ [ 0.80%] spage_find_empty_slot
   │  │  │  │        └─ [ 0.58%] spage_has_enough_total_space
   │  │  │  │           └─ [ 0.32%] lf_hash_find
   │  │  │  ├─ [ 1.77%] log_sysop_end_logical_undo
   │  │  │  │  └─ [ 1.75%] log_sysop_commit_internal
   │  │  │  │     └─ [ 1.09%] log_append_sysop_end
   │  │  │  │        ├─ [ 0.59%] prior_lsa_next_record_internal
   │  │  │  │        └─ [ 0.45%] prior_lsa_alloc_and_copy_data
   │  │  │  ├─ [ 1.13%] pgbuf_unfix
   │  │  │  │  └─ [ 0.75%] pgbuf_unlatch_void_zone_bcb
   │  │  │  ├─ [ 0.49%] prior_lsa_next_record_internal
   │  │  │  └─ [ 0.42%] log_sysop_start_atomic
   │  │  ├─ [ 4.13%] log_append_undoredo_data
   │  │  │  └─ [ 4.12%] log_append_undoredo_crumbs
   │  │  │     ├─ [ 2.80%] prior_lsa_alloc_and_copy_crumbs
   │  │  │     │  ├─ [ 1.19%] log_zip
   │  │  │     │  │  └─ [ 0.93%] LZ4_resetStream_fast
   │  │  │     │  │     └─ [ 0.87%] __memset_evex_unaligned_erms
   │  │  │     │  └─ [ 0.75%] malloc
   │  │  │     │     └─ [ 0.53%] _int_malloc
   │  │  │     └─ [ 1.08%] prior_lsa_next_record_internal
   │  │  │        ├─ [ 0.44%] __pthread_mutex_lock
   │  │  │        └─ [ 0.33%] __pthread_mutex_unlock_usercnt
   │  │  ├─ [ 1.91%] heap_stats_add_bestspace
   │  │  │  ├─ [ 0.93%] mht_get
   │  │  │  └─ [ 0.34%] __pthread_mutex_unlock_usercnt
   │  │  ├─ [ 1.53%] spage_max_space_for_new_record
   │  │  │  └─ [ 0.82%] lf_hash_find
   │  │  │     └─ [ 0.38%] lf_list_find
   │  │  ├─ [ 1.06%] log_sysop_commit
   │  │  │  └─ [ 1.06%] log_sysop_commit_internal
   │  │  │     └─ [ 0.90%] log_append_sysop_end
   │  │  │        ├─ [ 0.53%] prior_lsa_next_record_internal
   │  │  │        └─ [ 0.36%] prior_lsa_alloc_and_copy_data
   │  │  │           └─ [ 0.35%] malloc
   │  │  ├─ [ 0.82%] pgbuf_unfix
   │  │  ├─ [ 0.75%] mht_get2
   │  │  └─ [ 0.73%] __pthread_mutex_lock
   │  ├─ [24.83%] lock_object
   │  │  ├─ [24.02%] lock_internal_perform_lock_object
   │  │  │  ├─ [18.20%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
   │  │  │  │  └─ [17.60%] lf_hash_insert_internal
   │  │  │  │     ├─ [14.23%] lock_res_key_compare
   │  │  │  │     └─ [ 1.39%] lf_freelist_claim
   │  │  │  │        ├─ [ 0.84%] lf_freelist_alloc_block
   │  │  │  │        │  └─ [ 0.83%] lock_alloc_resource
   │  │  │  │        │     └─ [ 0.82%] malloc
   │  │  │  │        │        └─ [ 0.61%] _int_malloc
   │  │  │  │        └─ [ 0.36%] lf_stack_pop
   │  │  │  ├─ [ 3.75%] lf_freelist_claim
   │  │  │  │  ├─ [ 2.25%] lf_freelist_alloc_block
   │  │  │  │  │  └─ [ 2.24%] malloc
   │  │  │  │  │     └─ [ 2.00%] _int_malloc
   │  │  │  │  │        ├─ [ 0.98%] sysmalloc
   │  │  │  │  │        │  └─ [ 0.88%] __mprotect
   │  │  │  │  │        └─ [ 0.56%] malloc_consolidate
   │  │  │  │  └─ [ 0.87%] lf_stack_pop
   │  │  │  └─ [ 0.64%] lock_insert_into_tran_hold_list
   │  │  │     └─ [ 0.58%] __pthread_mutex_lock
   │  │  └─ [ 0.34%] lock_get_class_lock
   │  ├─ [13.98%] heap_log_insert_physical
   │  │  ├─ [12.26%] log_append_undoredo_crumbs
   │  │  │  ├─ [ 7.55%] prior_lsa_alloc_and_copy_crumbs
   │  │  │  │  ├─ [ 3.52%] log_zip
   │  │  │  │  │  └─ [ 2.72%] LZ4_resetStream_fast
   │  │  │  │  │     └─ [ 2.53%] __memset_evex_unaligned_erms
   │  │  │  │  ├─ [ 1.49%] malloc
   │  │  │  │  │  └─ [ 0.83%] _int_malloc
   │  │  │  │  ├─ [ 0.65%] prior_lsa_copy_redo_data_to_node
   │  │  │  │  │  └─ [ 0.55%] malloc
   │  │  │  │  │     └─ [ 0.41%] _int_malloc
   │  │  │  │  └─ [ 0.51%] __memmove_evex_unaligned_erms
   │  │  │  ├─ [ 2.99%] prior_lsa_next_record_internal
   │  │  │  │  ├─ [ 0.89%] __pthread_mutex_lock
   │  │  │  │  └─ [ 0.77%] __pthread_mutex_unlock_usercnt
   │  │  │  └─ [ 0.36%] log_does_allow_replication
   │  │  ├─ [ 0.52%] heap_page_update_chain_after_mvcc_op
   │  │  └─ [ 0.32%] heap_page_get_vacuum_status@plt
   │  ├─ [ 6.61%] spage_insert_at
   │  │  ├─ [ 5.31%] spage_insert_data
   │  │  │  └─ [ 4.94%] __memmove_evex_unaligned_erms
   │  │  └─ [ 1.12%] spage_find_empty_slot_at
   │  │     └─ [ 0.83%] spage_check_space
   │  │        └─ [ 0.80%] spage_has_enough_total_space
   │  │           └─ [ 0.33%] lf_hash_find
   │  └─ [ 0.90%] pgbuf_unfix
   ├─ [16.84%] locator_add_or_remove_index_internal
   │  ├─ [ 5.64%] repl_log_insert       ★ master-only (송신측 replication log)
   │  │  ├─ [ 0.86%] malloc
   │  │  │  └─ [ 0.62%] _int_malloc
   │  │  ├─ [ 0.86%] repl_log_info_alloc
   │  │  │  └─ [ 0.60%] realloc
   │  │  │     └─ [ 0.58%] mremap_chunk
   │  │  │        └─ [ 0.56%] __GI___mremap
   │  │  ├─ [ 0.75%] heap_get_class_name_alloc_if_diff
   │  │  ├─ [ 0.61%] heap_get_class_tde_algorithm
   │  │  ├─ [ 0.55%] or_packed_value_size
   │  │  └─ [ 0.42%] or_pack_mem_value
   │  ├─ [ 4.68%] heap_get_class_name_alloc_if_diff
   │  │  ├─ [ 1.62%] malloc
   │  │  │  └─ [ 1.41%] _int_malloc
   │  │  ├─ [ 0.95%] heap_get_class_record
   │  │  │  └─ [ 0.39%] heap_get_last_version
   │  │  ├─ [ 0.82%] heap_scancache_end
   │  │  │  └─ [ 0.81%] heap_scancache_quick_end
   │  │  │     └─ [ 0.65%] pgbuf_unfix
   │  │  └─ [ 0.33%] heap_scancache_quick_start_root_hfid
   │  ├─ [ 1.12%] heap_attrinfo_read_dbvalues
   │  ├─ [ 1.08%] heap_attrinfo_end
   │  │  └─ [ 0.36%] heap_classrepr_free
   │  ├─ [ 0.62%] heap_attrvalue_get_key
   │  ├─ [ 0.60%] heap_attrinfo_start_with_index
   │  └─ [ 0.44%] btree_insert
   └─ [ 2.09%] locator_check_foreign_key
      ├─ [ 0.96%] heap_attrinfo_start_with_index
      │  └─ [ 0.37%] heap_classrepr_get
      └─ [ 0.46%] heap_attrinfo_read_dbvalues
```

---

## 섹션 3 — 함수별 inclusive % 표 (섹션 2 트리 등장 함수, 함수명 누적, lif = 100%)

denominator: lif-containing stacks = 21,071. 같은 stack 안 같은 함수는 한 번만 카운트.

| % of lif | 함수 |
|---:|---|
| 100.00 | `locator_insert_force` |
| 80.22 | `heap_insert_logical` |
| 31.71 | `heap_stats_find_best_page` |
| 24.83 | `lock_object` |
| 24.02 | `lock_internal_perform_lock_object` |
| 20.47 | `log_append_undoredo_crumbs` |
| 18.20 | `cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert` |
| 17.60 | `lf_hash_insert_internal` |
| 17.32 | `file_alloc` |
| 16.84 | `locator_add_or_remove_index_internal` |
| 14.26 | `lock_res_key_compare` |
| 13.98 | `heap_log_insert_physical` |
| 12.54 | `prior_lsa_alloc_and_copy_crumbs` |
| 11.61 | `malloc` |
|  8.66 | `_int_malloc` |
|  7.43 | `pgbuf_fix_release` |
|  6.90 | `prior_lsa_next_record_internal` |
|  6.61 | `spage_insert_at` |
|  6.59 | `log_append_undoredo_data` |
|  6.03 | `pgbuf_claim_bcb_for_fix` |
|  5.97 | `__pthread_mutex_lock` |
|  5.71 | `__memmove_evex_unaligned_erms` |
|  5.64 | `repl_log_insert` |
|  5.44 | `heap_get_class_name_alloc_if_diff` |
|  5.39 | `spage_insert_data` |
|  5.14 | `lf_freelist_claim` |
|  4.71 | `log_zip` |
|  3.74 | `__pthread_mutex_unlock_usercnt` |
|  3.66 | `LZ4_resetStream_fast` |
|  3.51 | `pgbuf_unfix` |
|  3.40 | `__memset_evex_unaligned_erms` |
|  3.09 | `lf_freelist_alloc_block` |
|  3.00 | `thread_suspend_timeout_wakeup_and_unlock_entry` |
|  2.99 | `file_perm_alloc` |
|  2.83 | `log_sysop_commit_internal` |
|  2.77 | `heap_vpid_init_new` |
|  2.61 | `pthread_cond_timedwait@@GLIBC_2.3.2` |
|  2.09 | `locator_check_foreign_key` |
|  2.00 | `log_append_sysop_end` |
|  1.92 | `heap_stats_add_bestspace` |
|  1.77 | `log_sysop_end_logical_undo` |
|  1.66 | `log_append_undoredo_data2` |
|  1.58 | `heap_attrinfo_read_dbvalues` |
|  1.57 | `heap_attrinfo_start_with_index` |
|  1.55 | `__lll_unlock_wake` |
|  1.53 | `spage_max_space_for_new_record` |
|  1.52 | `lf_hash_find` |
|  1.49 | `spage_has_enough_total_space` |
|  1.37 | `heap_attrinfo_end` |
|  1.23 | `lf_stack_pop` |
|  1.12 | `spage_find_empty_slot_at` |
|  1.08 | `log_sysop_commit` |
|  1.08 | `prior_lsa_alloc_and_copy_data` |
|  1.03 | `sysmalloc` |
|  0.99 | `heap_scancache_end` |
|  0.99 | `heap_get_class_record` |
|  0.98 | `heap_scancache_quick_end` |
|  0.94 | `spage_check_space` |
|  0.93 | `__mprotect` |
|  0.93 | `mht_get` |
|  0.92 | `spage_insert` |
|  0.86 | `repl_log_info_alloc` |
|  0.83 | `lock_alloc_resource` |
|  0.80 | `spage_find_empty_slot` |
|  0.79 | `pgbuf_get_victim` |
|  0.77 | `lf_list_find` |
|  0.76 | `prior_lsa_copy_redo_data_to_node` |
|  0.75 | `pgbuf_unlatch_void_zone_bcb` |
|  0.75 | `mht_get2` |
|  0.68 | `malloc_consolidate` |
|  0.67 | `log_does_allow_replication` |
|  0.64 | `lock_insert_into_tran_hold_list` |
|  0.62 | `heap_attrvalue_get_key` |
|  0.61 | `heap_get_class_tde_algorithm` |
|  0.60 | `realloc` |
|  0.58 | `mremap_chunk` |
|  0.56 | `__GI___mremap` |
|  0.55 | `or_packed_value_size` |
|  0.53 | `heap_scancache_quick_start_root_hfid` |
|  0.52 | `heap_page_update_chain_after_mvcc_op` |
|  0.48 | `heap_classrepr_free` |
|  0.44 | `btree_insert` |
|  0.42 | `or_pack_mem_value` |
|  0.42 | `log_sysop_start_atomic` |
|  0.40 | `pgbuf_get_victim_from_lru_list` |
|  0.39 | `heap_get_last_version` |
|  0.38 | `heap_classrepr_get` |
|  0.34 | `lock_get_class_lock` |
|  0.32 | `heap_page_get_vacuum_status@plt` |
