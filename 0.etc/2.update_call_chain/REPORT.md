# v2 update — master cub_server 콜체인

캡처: `master-update-v2-20260520-170517/oncpu.data` (2.06 GB, 255,306 samples)
기준점: `qexec_execute_update`
  - perf report Children = **7.75% of total on-CPU**
  - raw stack tally: `qexec_execute_update` 가 포함된 sample = **19,174** (= 100% of qeu)

slave 측 참조 (`/home/youngjun/applier_paraller/5.bottleneck_analysis/6.update_server_perf_test/update_worker_10.md`) 의 `xlocator_repl_force` 자리에 master 는 `qexec_execute_update` 가 위치 (csql 의 UPDATE SQL 실행 엔트리, INSERT 의 `locator_insert_force` 와 대응되는 master 측 parent — 단 INSERT 는 per-row helper 였고 UPDATE 는 SQL 실행 main block 임).

원본 산출물:
  - `oncpu.data` / `oncpu.script` (raw perf data + 텍스트 dump)
  - `analysis/qeu_callgraph_top-down.txt` (perf report 전체 트리)
  - `analysis/qeu_callgraph_top-down_compact_0.05pct.txt` (% of total, 0.05% 컷오프)
  - `analysis/qeu_callgraph_bottom-up_entry.txt` (entry chain)
  - `analysis/qeu_callgraph_raw_normalized_0.3pct.txt` (raw stack 트리, qeu=100%)
  - `analysis/qeu_raw_inclusive_table_section3.txt` (섹션 3 표)

---

## 섹션 1 — 부모 함수 & qeu 콜체인 (% of total on-CPU, 0.05% 컷오프)

전체 on-CPU 중 UPDATE 경로가 차지하는 비중을 보는 용도.

### 1-1) 부모 함수 — caller chain (entry path)

```
[__GI___clone]
  └─ start_thread
       └─ execute_native_thread_routine
            └─ cubthread::worker_pool::core::worker::run
                 └─ cubthread::worker_pool::core::worker::execute_current_task
                      └─ css_server_task::execute              (worker dispatch)
                           └─ css_internal_request_handler (inlined)
                                └─ net_server_request          (request demux)
                                     └─ sqmgr_execute_query    (server stub)
                                          └─ xqmgr_execute_query         ★ engine entry
                                               └─ qmgr_process_query
                                                    └─ qexec_execute_query
                                                         └─ qexec_execute_mainblock
                                                              └─ qexec_execute_mainblock_internal (inlined)
                                                                   └─ qexec_execute_update         ★ UPDATE 실행 main block
```

### 1-2) `qexec_execute_update` 콜체인 (top-down, % of total, 0.05% 컷오프)

```
[ 7.75%] qexec_execute_update
   ├─ [ 7.64%] qexec_execute_update (재귀, SELECT-find phase)
   │  ├─ [ 5.15%] qexec_execute_mainblock
   │  │  └─ [ 5.15%] qexec_execute_mainblock_internal (inlined)
   │  │     ├─ [ 4.16%] qexec_intprt_fnc
   │  │     │  ├─ [ 3.08%] scan_next_scan
   │  │     │  │  └─ [ 3.07%] scan_next_scan
   │  │     │  │     └─ [ 3.05%] scan_next_index_scan (inlined)
   │  │     │  │        ├─ [ 2.24%] scan_next_scan_local
   │  │     │  │        │  ├─ [ 1.37%] locator_lock_and_get_object_with_evaluation
   │  │     │  │        │  │  └─ [ 1.30%] locator_lock_and_get_object_internal
   │  │     │  │        │  │     ├─ [ 1.22%] lock_object
   │  │     │  │        │  │     │  └─ [ 1.19%] lock_internal_perform_lock_object
   │  │     │  │        │  │     │     ├─ [ 0.98%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
   │  │     │  │        │  │     │     │  └─ [ 0.96%] lf_hash_insert_internal
   │  │     │  │        │  │     │     │     └─ [ 0.93%] lf_list_insert_internal (inlined)
   │  │     │  │        │  │     │     │        ├─ [ 0.74%] lock_res_key_compare
   │  │     │  │        │  │     │     │        └─ [ 0.12%] lf_freelist_claim
   │  │     │  │        │  │     │     │           └─ [ 0.08%] lf_freelist_alloc_block
   │  │     │  │        │  │     │     │              └─ [ 0.08%] cub_alloc → __GI___libc_malloc → _int_malloc [0.07%]
   │  │     │  │        │  │     │     └─ [ 0.13%] lf_freelist_claim
   │  │     │  │        │  │     │        └─ [ 0.06%] lf_freelist_alloc_block → __GI___libc_malloc [0.06%]
   │  │     │  │        │  │     └─ [ 0.05%] heap_get_last_version
   │  │     │  │        │  ├─ [ 0.86%] call_get_next_index_oidset
   │  │     │  │        │  │  └─ [ 0.85%] scan_get_index_oidset
   │  │     │  │        │  │     ├─ [ 0.63%] btree_range_scan
   │  │     │  │        │  │     │  ├─ [ 0.49%] btree_range_scan_start
   │  │     │  │        │  │     │  │  └─ [ 0.44%] btree_locate_key
   │  │     │  │        │  │     │  │     └─ [ 0.40%] btree_search_key_and_apply_functions (inlined)
   │  │     │  │        │  │     │  │        ├─ [ 0.21%] btree_advance_and_find_key (inlined)
   │  │     │  │        │  │     │  │        │  ├─ [ 0.14%] btree_advance_and_find_key (inlined)
   │  │     │  │        │  │     │  │        │  │  └─ [ 0.13%] btree_search_nonleaf_page
   │  │     │  │        │  │     │  │        │  └─ [ 0.06%] btree_locate_key → pgbuf_fix_release [0.05%]
   │  │     │  │        │  │     │  │        ├─ [ 0.13%] btree_locate_key → btree_search_leaf_page [0.13%]
   │  │     │  │        │  │     │  │        │  └─ [ 0.06%] btree_read_record_without_decompression
   │  │     │  │        │  │     │  └─ [ 0.06%] btree_range_scan_select_visible_oids
   │  │     │  │        │  │     ├─ [ 0.11%] scan_regu_key_to_index_key (inlined)
   │  │     │  │        │  │     └─ [ 0.07%] fetch_copy_dbval
   │  │     │  │        └─ [ 0.77%] scan_next_index_lookup_heap (inlined)
   │  │     │  │           ├─ [ 0.55%] heap_get_visible_version
   │  │     │  │           │  ├─ [ 0.44%] heap_get_visible_version_internal
   │  │     │  │           │  │  ├─ [ 0.22%] heap_scan_cache_allocate_area
   │  │     │  │           │  │  │  └─ [ 0.18%] heap_scancache::reserve_area → ::alloc_area
   │  │     │  │           │  │  │     └─ [ 0.16%] cubmem::single_block_allocator
   │  │     │  │           │  │  │        └─ [ 0.09%] operator new → __GI___libc_malloc → _int_malloc [0.08%]
   │  │     │  │           │  │  ├─ [ 0.10%] heap_get_record_data_when_all_ready
   │  │     │  │           │  │  │  └─ [ 0.06%] spage_get_record_data → __memmove_evex_unaligned_erms [0.05%]
   │  │     │  │           │  │  └─ [ 0.06%] heap_prepare_get_context
   │  │     │  │           │  └─ [ 0.09%] heap_clean_get_context
   │  │     │  │           │     └─ [ 0.07%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix [0.06%]
   │  │     │  │           └─ [ 0.08%] heap_attrinfo_read_dbvalues
   │  │     │  ├─ [ 0.63%] qexec_end_one_iteration
   │  │     │  │  ├─ [ 0.36%] qfile_generate_tuple_into_list
   │  │     │  │  │  └─ [ 0.30%] qfile_generate_tuple_into_list
   │  │     │  │  │     └─ [ 0.27%] qdata_copy_db_value_to_tuple_value
   │  │     │  │  │        └─ [ 0.17%] mr_data_writeval_string
   │  │     │  │  │           └─ [ 0.14%] pr_write_uncompressed_string_to_buffer
   │  │     │  │  └─ [ 0.24%] qexec_generate_tuple_descriptor
   │  │     │  │     └─ [ 0.19%] qdata_generate_tuple_desc_for_valptr_list
   │  │     │  │        └─ [ 0.11%] fetch_peek_dbval → qdata_evaluate_function [0.07%]
   │  │     │  └─ [ 0.40%] qexec_next_scan_block_iterations
   │  │     │     └─ [ 0.38%] qexec_next_scan_block
   │  │     │        ├─ [ 0.24%] scan_start_scan
   │  │     │        │  ├─ [ 0.14%] heap_scancache_start → heap_scancache_start_internal [0.10%]
   │  │     │        │  │  └─ [ 0.08%] heap_get_class_info → lf_hash_insert_internal [0.06%]
   │  │     │        │  └─ [ 0.06%] heap_attrinfo_start
   │  │     │        └─ [ 0.09%] scan_end_scan → heap_scancache_end [0.07%]
   │  │     ├─ [ 0.52%] qexec_open_scan
   │  │     │  └─ [ 0.46%] scan_open_index_scan
   │  │     │     ├─ [ 0.19%] heap_get_indexinfo_of_btid
   │  │     │     │  ├─ [ 0.09%] heap_classrepr_get
   │  │     │     │  └─ [ 0.06%] heap_classrepr_free
   │  │     │     ├─ [ 0.08%] pgbuf_fix_release
   │  │     │     └─ [ 0.07%] pgbuf_unfix
   │  │     ├─ [ 0.20%] qexec_start_mainblock_iterations
   │  │     │  └─ [ 0.12%] qfile_open_list → qmgr_create_new_temp_file [0.09%]
   │  │     └─ [ 0.07%] scan_close_scan
   │  ├─ [ 0.66%] locator_attribute_info_force
   │  │  ├─ [ 0.43%] locator_allocate_copy_area_by_attr_info
   │  │  │  ├─ [ 0.30%] heap_attrinfo_transform_to_disk_internal
   │  │  │  │  └─ [ 0.13%] heap_attrinfo_transform_variable_to_disk
   │  │  │  │     └─ [ 0.08%] mr_data_writeval_string
   │  │  │  └─ [ 0.06%] heap_attrinfo_set_uninitialized
   │  │  │  └─ [ 0.06%] locator_allocate_copy_area_by_length
   │  │  └─ [ 0.11%] heap_get_last_version → heap_scan_cache_allocate_area [0.05%]
   │  ├─ [ 0.27%] heap_attrinfo_set
   │  │  ├─ [ 0.13%] tp_domain_check → tp_domain_select [0.12%]
   │  │  └─ [ 0.05%] mr_setval_string
   │  ├─ [ 0.25%] scan_next_scan
   │  │  └─ [ 0.25%] scan_next_scan
   │  │     ├─ [ 0.17%] scan_next_list_scan (inlined)
   │  │     │  └─ [ 0.11%] fetch_val_list → fetch_peek_dbval_pos [0.09%]
   │  │     └─ [ 0.06%] scan_next_scan_local
   │  ├─ [ 0.22%] xtran_server_end_topop
   │  │  ├─ [ 0.10%] log_sysop_attach_to_outer
   │  │  │  └─ [ 0.07%] log_sysop_attach_to_outer → log_tdes::unlock_topop [0.06%]
   │  │  └─ [ 0.06%] cuberr::context::pop_error_stack_and_destroy
   │  ├─ [ 0.17%] qexec_upddel_setup_current_class
   │  │  └─ [ 0.13%] heap_scancache_start_modify
   │  │     └─ [ 0.09%] heap_scancache_start_modify → file_get_type [0.08%]
   │  ├─ [ 0.15%] qexec_next_scan_block_iterations → qexec_next_scan_block [0.14%]
   │  │  ├─ [ 0.07%] scan_start_scan → qfile_open_list_scan [0.05%]
   │  │  └─ [ 0.06%] scan_end_scan
   │  ├─ [ 0.14%] heap_attrinfo_start → heap_attrinfo_recache_attrepr [0.08%]
   │  ├─ [ 0.13%] qexec_clear_internal_classes
   │  │  └─ [ 0.07%] heap_attrinfo_end
   │  ├─ [ 0.12%] logtb_get_mvcc_snapshot → mvcctable::build_mvcc_info [0.10%]
   │  ├─ [ 0.11%] xtran_server_start_topop → log_sysop_start [0.10%]
   │  └─ [ 0.07%] qexec_open_scan → scan_open_list_scan [0.06%]
   └─ [ 0.11%] (subquery 별도 caller-path 잔여, qexec_execute_mainblock 경유)
```

---

## 섹션 2 — `qexec_execute_update` 콜체인 (raw stack 트리, qeu = 100%, 0.3% 컷오프)

raw `perf script` 의 stack 직접 집계 (sample 단위, cycles 가중치 없음).
qeu-containing sample = 19,174 → 100%.
분산되어 perf report 컷오프에 가렸던 함수들 (`malloc`, `__pthread_mutex_lock`, `cubmem::*` allocator 등) 도 포함.

```
[100.00%] qexec_execute_update
   ├─ [66.58%] qexec_execute_mainblock
   │  ├─ [53.80%] qexec_intprt_fnc
   │  │  ├─ [39.55%] scan_next_scan
   │  │  │  └─ [39.45%] scan_next_scan_local
   │  │  │     ├─ [17.61%] locator_lock_and_get_object_with_evaluation
   │  │  │     │  ├─ [16.62%] locator_lock_and_get_object_internal
   │  │  │     │  │  ├─ [15.57%] lock_object
   │  │  │     │  │  │  └─ [15.14%] lock_internal_perform_lock_object
   │  │  │     │  │  │     ├─ [12.45%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
   │  │  │     │  │  │     │  └─ [12.13%] lf_hash_insert_internal
   │  │  │     │  │  │     │     ├─ [ 9.35%] lock_res_key_compare
   │  │  │     │  │  │     │     └─ [ 1.46%] lf_freelist_claim
   │  │  │     │  │  │     │        ├─ [ 1.03%] lf_freelist_alloc_block
   │  │  │     │  │  │     │        │  └─ [ 1.03%] lock_alloc_resource
   │  │  │     │  │  │     │        │     └─ [ 1.02%] malloc
   │  │  │     │  │  │     │        └─ [ 0.33%] lf_stack_pop
   │  │  │     │  │  │     ├─ [ 1.71%] lf_freelist_claim
   │  │  │     │  │  │     │  ├─ [ 0.77%] lf_freelist_alloc_block
   │  │  │     │  │  │     │  │  └─ [ 0.76%] malloc
   │  │  │     │  │  │     │  │     └─ [ 0.66%] _int_malloc
   │  │  │     │  │  │     │  └─ [ 0.45%] lf_stack_pop
   │  │  │     │  │  │     └─ [ 0.39%] lock_insert_into_tran_hold_list
   │  │  │     │  │  │        └─ [ 0.33%] __pthread_mutex_lock
   │  │  │     │  │  └─ [ 0.74%] heap_get_last_version
   │  │  │     │  │     └─ [ 0.32%] heap_get_record_data_when_all_ready
   │  │  │     │  └─ [ 0.58%] heap_clean_get_context
   │  │  │     │     └─ [ 0.51%] pgbuf_unfix
   │  │  │     ├─ [11.10%] call_get_next_index_oidset
   │  │  │     │  └─ [10.89%] scan_get_index_oidset
   │  │  │     │     ├─ [ 8.17%] btree_range_scan
   │  │  │     │     │  ├─ [ 6.30%] btree_range_scan_start
   │  │  │     │     │  │  ├─ [ 5.71%] btree_locate_key
   │  │  │     │     │  │  │  ├─ [ 1.72%] btree_search_leaf_page
   │  │  │     │     │  │  │  │  └─ [ 0.33%] spage_get_record
   │  │  │     │     │  │  │  ├─ [ 1.70%] btree_search_nonleaf_page
   │  │  │     │     │  │  │  │  └─ [ 0.33%] btree_compare_key
   │  │  │     │     │  │  │  ├─ [ 0.70%] pgbuf_fix_release
   │  │  │     │     │  │  │  ├─ [ 0.62%] btree_get_root_with_key
   │  │  │     │     │  │  │  │  └─ [ 0.51%] pgbuf_fix_release
   │  │  │     │     │  │  │  └─ [ 0.41%] pgbuf_unfix
   │  │  │     │     │  │  └─ [ 0.50%] btree_range_scan_advance_over_filtered_keys
   │  │  │     │     │  ├─ [ 0.77%] btree_range_scan_select_visible_oids
   │  │  │     │     │  │  └─ [ 0.38%] btree_select_visible_object_for_range_scan
   │  │  │     │     │  └─ [ 0.45%] pgbuf_unfix
   │  │  │     │     ├─ [ 0.98%] fetch_copy_dbval
   │  │  │     │     │  ├─ [ 0.44%] fetch_peek_dbval
   │  │  │     │     │  └─ [ 0.37%] qdata_copy_db_value
   │  │  │     │     └─ [ 0.40%] btree_prepare_bts
   │  │  │     ├─ [ 7.08%] heap_get_visible_version
   │  │  │     │  ├─ [ 5.66%] heap_get_visible_version_internal
   │  │  │     │  │  ├─ [ 2.85%] heap_scan_cache_allocate_area
   │  │  │     │  │  │  ├─ [ 2.37%] heap_scancache::reserve_area
   │  │  │     │  │  │  │  └─ [ 2.32%] heap_scancache::alloc_area
   │  │  │     │  │  │  │     └─ [ 2.06%] cubmem::single_block_allocator::single_block_allocator
   │  │  │     │  │  │  │        └─ [ 1.59%] cubmem::block_allocator::block_allocator
   │  │  │     │  │  │  │           └─ [ 1.50%] operator new
   │  │  │     │  │  │  │              └─ [ 1.48%] malloc
   │  │  │     │  │  │  └─ [ 0.32%] cubmem::single_block_allocator::reserve
   │  │  │     │  │  ├─ [ 1.29%] heap_get_record_data_when_all_ready
   │  │  │     │  │  │  └─ [ 0.78%] spage_get_record_data
   │  │  │     │  │  │     └─ [ 0.66%] __memmove_evex_unaligned_erms
   │  │  │     │  │  └─ [ 0.72%] heap_prepare_get_context
   │  │  │     │  └─ [ 1.15%] heap_clean_get_context
   │  │  │     │     └─ [ 0.93%] pgbuf_unfix
   │  │  │     │        └─ [ 0.47%] pgbuf_unlatch_void_zone_bcb
   │  │  │     ├─ [ 0.95%] heap_attrinfo_read_dbvalues
   │  │  │     └─ [ 0.56%] fetch_val_list
   │  │  │        └─ [ 0.43%] fetch_peek_dbval
   │  │  ├─ [ 8.39%] qexec_end_one_iteration
   │  │  │  ├─ [ 4.64%] qfile_generate_tuple_into_list
   │  │  │  │  ├─ [ 3.54%] qdata_copy_db_value_to_tuple_value
   │  │  │  │  │  └─ [ 2.22%] mr_data_writeval_string
   │  │  │  │  └─ [ 0.57%] qfile_allocate_new_page_if_need
   │  │  │  └─ [ 3.34%] qexec_generate_tuple_descriptor
   │  │  │     └─ [ 2.72%] qdata_generate_tuple_desc_for_valptr_list
   │  │  │        ├─ [ 1.47%] fetch_peek_dbval
   │  │  │        │  └─ [ 0.87%] qdata_evaluate_function
   │  │  │        │     └─ [ 0.50%] heap_get_class_oid
   │  │  │        └─ [ 0.76%] qdata_get_tuple_value_size_from_dbval
   │  │  └─ [ 5.02%] qexec_next_scan_block_iterations
   │  │     └─ [ 4.88%] qexec_next_scan_block
   │  │        ├─ [ 3.05%] scan_start_scan
   │  │        │  ├─ [ 1.76%] heap_scancache_start
   │  │        │  │  ├─ [ 0.99%] heap_get_class_info
   │  │        │  │  │  └─ [ 0.99%] heap_hfid_cache_get
   │  │        │  │  │     └─ [ 0.72%] lf_hash_insert_internal
   │  │        │  │  └─ [ 0.43%] lock_scan
   │  │        │  └─ [ 0.79%] heap_attrinfo_start
   │  │        │     └─ [ 0.38%] heap_classrepr_get
   │  │        └─ [ 1.19%] scan_end_scan
   │  │           └─ [ 0.86%] heap_scancache_end
   │  │              └─ [ 0.86%] heap_scancache_quick_end
   │  │                 └─ [ 0.75%] heap_scancache::end_area
   │  │                    └─ [ 0.65%] cubmem::single_block_allocator::~single_block_allocator
   │  ├─ [ 6.65%] qexec_open_scan
   │  │  └─ [ 5.92%] scan_open_index_scan
   │  │     ├─ [ 2.37%] heap_get_indexinfo_of_btid
   │  │     │  ├─ [ 1.20%] heap_classrepr_get
   │  │     │  │  └─ [ 0.33%] __pthread_mutex_lock
   │  │     │  └─ [ 0.76%] heap_classrepr_free
   │  │     │     └─ [ 0.41%] __pthread_mutex_unlock_usercnt
   │  │     ├─ [ 1.09%] pgbuf_fix_release
   │  │     └─ [ 0.88%] pgbuf_unfix
   │  ├─ [ 2.61%] qexec_start_mainblock_iterations
   │  │  ├─ [ 1.55%] qfile_open_list
   │  │  │  └─ [ 1.23%] qmgr_create_new_temp_file
   │  │  │     └─ [ 0.60%] __pthread_mutex_lock
   │  │  └─ [ 0.40%] qdata_get_valptr_type_list
   │  ├─ [ 0.92%] scan_close_scan
   │  └─ [ 0.32%] lock_object
   ├─ [ 8.54%] locator_attribute_info_force
   │  ├─ [ 5.64%] locator_allocate_copy_area_by_attr_info
   │  │  ├─ [ 4.00%] heap_attrinfo_transform_to_disk_internal
   │  │  │  ├─ [ 1.76%] heap_attrinfo_transform_variable_to_disk
   │  │  │  │  └─ [ 1.13%] mr_data_writeval_string
   │  │  │  └─ [ 0.81%] heap_attrinfo_set_uninitialized
   │  │  │     └─ [ 0.35%] heap_attrvalue_read
   │  │  └─ [ 0.71%] locator_allocate_copy_area_by_length
   │  │     └─ [ 0.33%] malloc
   │  │        └─ [ 0.33%] _int_malloc
   │  ├─ [ 1.48%] heap_get_last_version
   │  │  ├─ [ 0.71%] heap_scan_cache_allocate_area
   │  │  │  └─ [ 0.56%] heap_scancache::reserve_area
   │  │  │     └─ [ 0.56%] heap_scancache::alloc_area
   │  │  │        └─ [ 0.42%] cubmem::single_block_allocator::single_block_allocator
   │  │  └─ [ 0.41%] heap_get_record_data_when_all_ready
   │  ├─ [ 0.40%] heap_clean_get_context
   │  │  └─ [ 0.33%] pgbuf_unfix
   │  └─ [ 0.36%] heap_attrinfo_check_unique_index
   ├─ [ 3.40%] heap_attrinfo_set
   │  ├─ [ 1.70%] tp_domain_check
   │  │  └─ [ 1.54%] tp_domain_select
   │  │     ├─ [ 0.58%] tp_domain_resolve_value
   │  │     └─ [ 0.50%] tp_domain_match_internal
   │  └─ [ 0.70%] mr_setval_string
   ├─ [ 3.24%] scan_next_scan
   │  └─ [ 3.18%] scan_next_scan_local
   │     ├─ [ 1.43%] fetch_val_list
   │     │  └─ [ 0.54%] mr_data_readval_string
   │     │     └─ [ 0.50%] mr_readval_string_internal
   │     ├─ [ 0.84%] resolve_domains_on_list_scan
   │     └─ [ 0.53%] qfile_scan_list_next
   ├─ [ 2.85%] xtran_server_end_topop
   │  ├─ [ 1.35%] log_sysop_attach_to_outer
   │  │  └─ [ 0.78%] log_tdes::unlock_topop
   │  │     └─ [ 0.50%] cubpl::get_session
   │  │        └─ [ 0.37%] session_get_pl_session
   │  ├─ [ 0.78%] cuberr::context::pop_error_stack_and_destroy
   │  │  └─ [ 0.38%] cuberr::context::pop_error_stack
   │  └─ [ 0.35%] cuberr::context::push_error_stack
   ├─ [ 2.09%] qexec_upddel_setup_current_class
   │  └─ [ 1.63%] heap_scancache_start_modify
   │     ├─ [ 1.02%] file_get_type
   │     │  ├─ [ 0.66%] pgbuf_fix_release
   │     │  └─ [ 0.31%] pgbuf_unfix
   │     └─ [ 0.34%] heap_scancache_reset_modify
   ├─ [ 2.00%] qexec_next_scan_block_iterations
   │  └─ [ 1.93%] qexec_next_scan_block
   │     ├─ [ 0.95%] scan_start_scan
   │     │  └─ [ 0.70%] qfile_open_list_scan
   │     │     └─ [ 0.55%] qfile_copy_list_id
   │     └─ [ 0.80%] scan_end_scan
   │        └─ [ 0.41%] qfile_close_scan
   ├─ [ 1.76%] heap_attrinfo_start
   │  ├─ [ 0.96%] heap_attrinfo_recache_attrepr
   │  └─ [ 0.54%] heap_classrepr_get
   ├─ [ 1.68%] qexec_clear_internal_classes
   │  ├─ [ 0.85%] heap_attrinfo_end
   │  │  └─ [ 0.45%] heap_attrinfo_clear_dbvalues
   │  └─ [ 0.41%] heap_scancache_quick_end
   │     └─ [ 0.38%] heap_scancache::end_area
   │        └─ [ 0.31%] cubmem::single_block_allocator::~single_block_allocator
   ├─ [ 1.56%] logtb_get_mvcc_snapshot
   │  └─ [ 1.32%] mvcctable::build_mvcc_info
   ├─ [ 1.43%] xtran_server_start_topop
   │  └─ [ 1.20%] log_sysop_start
   │     └─ [ 0.59%] rmutex_lock
   ├─ [ 0.96%] qexec_open_scan
   │  └─ [ 0.79%] scan_open_list_scan
   │     └─ [ 0.39%] prm_get_value
   ├─ [ 0.60%] qexec_create_internal_classes
   └─ [ 0.50%] qexec_set_class_locks
```

---

## 섹션 3 — 함수별 inclusive % 표 (섹션 2 트리 등장 함수, 함수명 누적, qeu = 100%)

denominator: qeu-containing stacks = 19,174. 같은 stack 안 같은 함수는 한 번만 카운트.

| % of qeu | 함수 |
|---:|---|
| 100.00 | `qexec_execute_update` |
| 99.96 | `qexec_execute_mainblock` |
| 53.80 | `qexec_intprt_fnc` |
| 42.79 | `scan_next_scan` |
| 42.63 | `scan_next_scan_local` |
| 17.61 | `locator_lock_and_get_object_with_evaluation` |
| 16.63 | `locator_lock_and_get_object_internal` |
| 16.19 | `lock_object` |
| 15.65 | `lock_internal_perform_lock_object` |
| 13.03 | `lf_hash_insert_internal` |
| 12.46 | `cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert` |
| 11.10 | `call_get_next_index_oidset` |
| 10.89 | `scan_get_index_oidset` |
|  9.35 | `lock_res_key_compare` |
|  8.54 | `locator_attribute_info_force` |
|  8.39 | `qexec_end_one_iteration` |
|  8.17 | `btree_range_scan` |
|  7.61 | `qexec_open_scan` |
|  7.08 | `heap_get_visible_version` |
|  7.02 | `qexec_next_scan_block_iterations` |
|  6.81 | `qexec_next_scan_block` |
|  6.30 | `btree_range_scan_start` |
|  5.92 | `scan_open_index_scan` |
|  5.71 | `btree_locate_key` |
|  5.66 | `heap_get_visible_version_internal` |
|  5.64 | `locator_allocate_copy_area_by_attr_info` |
|  4.73 | `malloc` |
|  4.64 | `qfile_generate_tuple_into_list` |
|  4.07 | `pgbuf_unfix` |
|  4.00 | `heap_attrinfo_transform_to_disk_internal` |
|  4.00 | `scan_start_scan` |
|  3.61 | `heap_scan_cache_allocate_area` |
|  3.55 | `qdata_copy_db_value_to_tuple_value` |
|  3.40 | `heap_attrinfo_set` |
|  3.35 | `mr_data_writeval_string` |
|  3.34 | `qexec_generate_tuple_descriptor` |
|  3.24 | `_int_malloc` |
|  3.17 | `lf_freelist_claim` |
|  2.96 | `heap_scancache::reserve_area` |
|  2.96 | `pgbuf_fix_release` |
|  2.89 | `heap_scancache::alloc_area` |
|  2.88 | `__pthread_mutex_lock` |
|  2.85 | `xtran_server_end_topop` |
|  2.72 | `qdata_generate_tuple_desc_for_valptr_list` |
|  2.61 | `qexec_start_mainblock_iterations` |
|  2.55 | `heap_attrinfo_start` |
|  2.48 | `cubmem::single_block_allocator::single_block_allocator` |
|  2.37 | `heap_get_indexinfo_of_btid` |
|  2.35 | `fetch_peek_dbval` |
|  2.34 | `std::_Function_base::_Base_manager<...>` |
|  2.21 | `heap_get_last_version` |
|  2.14 | `__pthread_mutex_unlock_usercnt` |
|  2.12 | `heap_classrepr_get` |
|  2.12 | `heap_clean_get_context` |
|  2.09 | `qexec_upddel_setup_current_class` |
|  2.08 | `operator new` |
|  2.03 | `heap_get_record_data_when_all_ready` |
|  2.00 | `scan_end_scan` |
|  1.99 | `fetch_val_list` |
|  1.80 | `lf_freelist_alloc_block` |
|  1.76 | `heap_attrinfo_transform_variable_to_disk` |
|  1.76 | `heap_scancache_start` |
|  1.72 | `btree_search_leaf_page` |
|  1.70 | `cubmem::block_allocator::block_allocator` |
|  1.70 | `btree_search_nonleaf_page` |
|  1.70 | `tp_domain_check` |
|  1.68 | `qexec_clear_internal_classes` |
|  1.67 | `logtb_get_mvcc_snapshot` |
|  1.63 | `heap_scancache_start_modify` |
|  1.62 | `spage_get_record_data` |
|  1.55 | `qfile_open_list` |
|  1.54 | `tp_domain_select` |
|  1.51 | `__memmove_evex_unaligned_erms` |
|  1.43 | `xtran_server_start_topop` |
|  1.35 | `log_sysop_attach_to_outer` |
|  1.32 | `mvcctable::build_mvcc_info` |
|  1.27 | `heap_scancache_quick_end` |
|  1.26 | `heap_hfid_cache_get` |
|  1.26 | `heap_get_class_info` |
|  1.23 | `qmgr_create_new_temp_file` |
|  1.20 | `log_sysop_start` |
|  1.18 | `heap_attrinfo_recache_attrepr` |
|  1.13 | `heap_scancache::end_area` |
|  1.05 | `heap_classrepr_free` |
|  1.04 | `heap_prepare_get_context` |
|  1.04 | `scan_close_scan` |
|  1.03 | `lock_alloc_resource` |
|  1.02 | `file_get_type` |
|  0.99 | `spage_get_record` |
|  0.98 | `fetch_copy_dbval` |
|  0.96 | `cubmem::single_block_allocator::~single_block_allocator` |
|  0.96 | `heap_attrinfo_read_dbvalues` |
|  0.87 | `qdata_evaluate_function` |
|  0.86 | `heap_scancache_end` |
|  0.85 | `heap_attrinfo_end` |
|  0.84 | `resolve_domains_on_list_scan` |
|  0.81 | `heap_attrinfo_set_uninitialized` |
|  0.79 | `scan_open_list_scan` |
|  0.78 | `cuberr::context::pop_error_stack_and_destroy` |
|  0.78 | `log_tdes::unlock_topop` |
|  0.78 | `lf_stack_pop` |
|  0.77 | `btree_range_scan_select_visible_oids` |
|  0.77 | `qdata_get_tuple_value_size_from_dbval` |
|  0.75 | `tp_domain_resolve_value` |
|  0.71 | `locator_allocate_copy_area_by_length` |
|  0.70 | `qfile_open_list_scan` |
|  0.70 | `mr_setval_string` |
|  0.62 | `btree_get_root_with_key` |
|  0.60 | `qexec_create_internal_classes` |
|  0.59 | `rmutex_lock` |
|  0.57 | `btree_range_scan_advance_over_filtered_keys` |
|  0.57 | `mr_data_readval_string` |
|  0.57 | `btree_compare_key` |
|  0.57 | `qfile_allocate_new_page_if_need` |
|  0.55 | `qfile_copy_list_id` |
|  0.53 | `qfile_scan_list_next` |
|  0.53 | `cubmem::single_block_allocator::reserve` |
|  0.52 | `heap_attrinfo_clear_dbvalues` |
|  0.50 | `tp_domain_match_internal` |
|  0.50 | `qexec_set_class_locks` |
|  0.50 | `mr_readval_string_internal` |
|  0.50 | `cubpl::get_session` |
|  0.50 | `heap_get_class_oid` |
|  0.47 | `pgbuf_unlatch_void_zone_bcb` |
|  0.43 | `lock_scan` |
|  0.41 | `qfile_close_scan` |
|  0.40 | `qdata_get_valptr_type_list` |
|  0.40 | `btree_prepare_bts` |
|  0.39 | `lock_insert_into_tran_hold_list` |
|  0.39 | `prm_get_value` |
|  0.38 | `btree_select_visible_object_for_range_scan` |
|  0.38 | `cuberr::context::pop_error_stack` |
|  0.37 | `session_get_pl_session` |
|  0.37 | `qdata_copy_db_value` |
|  0.36 | `heap_attrinfo_check_unique_index` |
|  0.35 | `heap_attrvalue_read` |
|  0.35 | `cuberr::context::push_error_stack` |
|  0.34 | `heap_scancache_reset_modify` |
