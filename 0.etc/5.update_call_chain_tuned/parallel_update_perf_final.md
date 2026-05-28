# Parallel poc update perf final

## 측정 날짜
2026-05-26

## 버전
 - branch: feature/parallel_applylogdb_poc
 - build: 72099e6

## 설정

- double_write_buffer_size=0
- data_buffer_size=5G
- log_buffer_size=5G
- log_volume_size=1G
- checkpoint_interval=30min (실험 전 csql -u dba --sysadm 으로 접속해 ;checkpoint 수행)
- addvoldb 로 100기가 볼륨 추가
- addvoldb 로 temp 볼륨 추가

## 1-2) qexec_execute_update call chain remapped (% of total, 0.05% cutoff)


```
[  9.77%] qexec_execute_update
└─ [  9.77%] qexec_execute_update (재귀, SELECT-find phase)
   ├─ [  6.10%] qexec_execute_mainblock
   │  └─ [  4.95%] qexec_execute_mainblock_internal (inlined)
   │     ├─ [  4.95%] qexec_intprt_fnc
   │     │  ├─ [  3.54%] scan_next_scan
   │     │  │  └─ [  3.54%] scan_next_scan
   │     │  │     └─ [  3.53%] scan_next_index_scan (inlined)
   │     │  │        ├─ [  3.53%] scan_next_scan_local
   │     │  │        │  ├─ [  1.18%] locator_lock_and_get_object_with_evaluation
   │     │  │        │  │  └─ [  1.06%] locator_lock_and_get_object_internal
   │     │  │        │  │     ├─ [  0.91%] lock_object
   │     │  │        │  │     │  └─ [  0.87%] lock_internal_perform_lock_object
   │     │  │        │  │     │     ├─ [  0.70%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
   │     │  │        │  │     │     │  └─ [  0.68%] lf_hash_insert_internal
   │     │  │        │  │     │     │     └─ [  0.59%] lf_list_insert_internal (inlined)
   │     │  │        │  │     │     │        ├─ [  0.51%] lock_res_key_compare
   │     │  │        │  │     │     │        └─ [  0.07%] lf_freelist_claim
   │     │  │        │  │     │     └─ [  0.16%] lf_freelist_claim
   │     │  │        │  │     │        └─ [  0.08%] lf_freelist_alloc_block → __GI___libc_malloc [0.06%]
   │     │  │        │  │     └─ [  0.11%] heap_get_last_version
   │     │  │        │  └─ [  1.12%] call_get_next_index_oidset
   │     │  │        │     └─ [  1.10%] scan_get_index_oidset
   │     │  │        │        ├─ [  0.82%] btree_range_scan
   │     │  │        │        │  ├─ [  0.64%] btree_range_scan_start
   │     │  │        │        │  │  └─ [  0.56%] btree_locate_key
   │     │  │        │        │  │     └─ [  0.49%] btree_search_key_and_apply_functions (inlined)
   │     │  │        │        │  │        ├─ [  0.28%] btree_advance_and_find_key (inlined)
   │     │  │        │        │  │        │  ├─ [  0.28%] btree_advance_and_find_key (inlined)
   │     │  │        │        │  │        │  │  └─ [  0.19%] btree_search_nonleaf_page
   │     │  │        │        │  │        │  └─ [  0.10%] btree_locate_key → pgbuf_fix_release [0.05%]
   │     │  │        │        │  │        └─ [  0.17%] btree_locate_key → btree_search_leaf_page [0.13%]
   │     │  │        │        │  │           └─ [  0.06%] btree_read_record_without_decompression
   │     │  │        │        │  └─ [  0.07%] btree_range_scan_select_visible_oids
   │     │  │        │        ├─ [  0.15%] scan_regu_key_to_index_key (inlined)
   │     │  │        │        └─ [  0.11%] fetch_copy_dbval
   │     │  │        └─ [  1.47%] scan_next_index_lookup_heap (inlined)
   │     │  │           ├─ [  0.85%] heap_get_visible_version
   │     │  │           │  ├─ [  0.71%] heap_get_visible_version_internal
   │     │  │           │  │  ├─ [  0.27%] heap_scan_cache_allocate_area
   │     │  │           │  │  ├─ [  0.23%] heap_get_record_data_when_all_ready
   │     │  │           │  │  │  └─ [  0.17%] spage_get_record_data → __memmove_evex_unaligned_erms [0.05%]
   │     │  │           │  │  └─ [  0.13%] heap_prepare_get_context
   │     │  │           │  └─ [  0.11%] heap_clean_get_context
   │     │  │           │     └─ [  0.07%] pgbuf_unfix → pgbuf_unlatch_bcb_upon_unfix [0.06%]
   │     │  │           └─ [  0.10%] heap_attrinfo_read_dbvalues
   │     │  ├─ [  0.77%] qexec_end_one_iteration
   │     │  │  ├─ [  0.39%] qfile_generate_tuple_into_list
   │     │  │  │  └─ [  0.39%] qfile_generate_tuple_into_list
   │     │  │  │     └─ [  0.29%] qdata_copy_db_value_to_tuple_value
   │     │  │  │        └─ [  0.16%] mr_data_writeval_string
   │     │  │  │           └─ [  0.14%] pr_write_uncompressed_string_to_buffer
   │     │  │  └─ [  0.35%] qexec_generate_tuple_descriptor
   │     │  │     └─ [  0.29%] qdata_generate_tuple_desc_for_valptr_list
   │     │  │        └─ [  0.09%] fetch_peek_dbval → qdata_evaluate_function [0.07%]
   │     │  └─ [  0.55%] qexec_next_scan_block_iterations
   │     │     └─ [  0.53%] qexec_next_scan_block
   │     │        ├─ [  0.34%] scan_start_scan
   │     │        │  ├─ [  0.18%] heap_scancache_start → heap_scancache_start_internal [0.10%]
   │     │        │  │  └─ [  0.06%] heap_get_class_info → lf_hash_insert_internal [0.06%]
   │     │        │  └─ [  0.10%] heap_attrinfo_start
   │     │        └─ [  0.09%] scan_end_scan → heap_scancache_end [0.07%]
   │     ├─ [  0.56%] qexec_open_scan
   │     │  └─ [  0.47%] scan_open_index_scan
   │     │     ├─ [  0.18%] heap_get_indexinfo_of_btid
   │     │     │  ├─ [  0.08%] heap_classrepr_get
   │     │     │  └─ [  0.05%] heap_classrepr_free
   │     │     ├─ [  0.09%] pgbuf_fix_release
   │     │     └─ [  0.06%] pgbuf_unfix
   │     ├─ [  0.21%] qexec_start_mainblock_iterations
   │     │  └─ [  0.08%] qfile_open_list → qmgr_create_new_temp_file [0.09%]
   │     └─ [  0.10%] scan_close_scan
   ├─ [  0.91%] locator_attribute_info_force
   │  ├─ [  0.60%] locator_allocate_copy_area_by_attr_info
   │  │  ├─ [  0.46%] heap_attrinfo_transform_to_disk_internal
   │  │  │  └─ [  0.18%] heap_attrinfo_transform_variable_to_disk
   │  │  │     └─ [  0.11%] mr_data_writeval_string
   │  │  └─ [  0.09%] heap_attrinfo_set_uninitialized
   │  └─ [  0.08%] heap_get_last_version → heap_scan_cache_allocate_area [0.05%]
   ├─ [  0.41%] heap_attrinfo_set
   │  ├─ [  0.18%] tp_domain_check → tp_domain_select [0.12%]
   │  └─ [  0.10%] mr_setval_string
   ├─ [  3.92%] scan_next_scan
   │  └─ [  3.92%] scan_next_scan
   │     ├─ [  0.35%] scan_next_list_scan (inlined)
   │     │  └─ [  0.18%] fetch_val_list → fetch_peek_dbval_pos [0.09%]
   │     └─ [  3.90%] scan_next_scan_local
   ├─ [  0.31%] xtran_server_end_topop
   │  ├─ [  0.14%] log_sysop_attach_to_outer
   │  │  └─ [  0.07%] log_sysop_attach_to_outer → log_tdes::unlock_topop [0.06%]
   │  └─ [  0.08%] cuberr::context::pop_error_stack_and_destroy
   ├─ [  0.22%] qexec_upddel_setup_current_class
   │  └─ [  0.17%] heap_scancache_start_modify
   │     └─ [  0.10%] heap_scancache_start_modify → file_get_type [0.08%]
   ├─ [  0.73%] qexec_next_scan_block_iterations → qexec_next_scan_block [0.14%]
   │  ├─ [  0.06%] scan_start_scan → qfile_open_list_scan [0.05%]
   │  └─ [  0.21%] scan_end_scan
   ├─ [  0.14%] heap_attrinfo_start → heap_attrinfo_recache_attrepr [0.08%]
   ├─ [  0.20%] qexec_clear_internal_classes
   │  └─ [  0.09%] heap_attrinfo_end
   ├─ [  0.14%] logtb_get_mvcc_snapshot → mvcctable::build_mvcc_info [0.10%]
   ├─ [  0.12%] xtran_server_start_topop → log_sysop_start [0.10%]
   └─ [  0.06%] qexec_open_scan → scan_open_list_scan [0.06%]
```

## 섹션 2 — qexec_execute_update call chain remapped (qexec_execute_update = 100%, 0.3% cutoff)


```
[100.00%] qexec_execute_update
├─ [ 62.48%] qexec_execute_mainblock
│  ├─ [ 50.67%] qexec_intprt_fnc
│  │  ├─ [ 36.28%] scan_next_scan
│  │  │  └─ [ 36.16%] scan_next_scan_local
│  │  │     ├─ [ 12.08%] locator_lock_and_get_object_with_evaluation
│  │  │     │  ├─ [ 10.86%] locator_lock_and_get_object_internal
│  │  │     │  │  ├─ [  9.35%] lock_object
│  │  │     │  │  │  └─ [  8.93%] lock_internal_perform_lock_object
│  │  │     │  │  │     ├─ [  7.19%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│  │  │     │  │  │     │  └─ [  7.01%] lf_hash_insert_internal
│  │  │     │  │  │     │     ├─ [  5.18%] lock_res_key_compare
│  │  │     │  │  │     │     └─ [  0.74%] lf_freelist_claim
│  │  │     │  │  │     │        └─ [  0.43%] lf_freelist_alloc_block
│  │  │     │  │  │     │           └─ [  0.42%] lock_alloc_resource
│  │  │     │  │  │     └─ [  1.66%] lf_freelist_claim
│  │  │     │  │  │        ├─ [  0.84%] lf_freelist_alloc_block
│  │  │     │  │  │        └─ [  0.46%] lf_stack_pop
│  │  │     │  │  └─ [  1.11%] heap_get_last_version
│  │  │     │  │     └─ [  0.36%] heap_get_record_data_when_all_ready
│  │  │     │  └─ [  0.62%] heap_clean_get_context
│  │  │     │     └─ [  0.52%] pgbuf_unfix
│  │  │     ├─ [ 11.51%] call_get_next_index_oidset
│  │  │     │  └─ [ 11.26%] scan_get_index_oidset
│  │  │     │     ├─ [  8.40%] btree_range_scan
│  │  │     │     │  ├─ [  6.55%] btree_range_scan_start
│  │  │     │     │  │  ├─ [  5.73%] btree_locate_key
│  │  │     │     │  │  │  ├─ [  1.74%] btree_search_leaf_page
│  │  │     │     │  │  │  ├─ [  1.96%] btree_search_nonleaf_page
│  │  │     │     │  │  │  │  └─ [  0.44%] btree_compare_key
│  │  │     │     │  │  │  ├─ [  1.05%] pgbuf_fix_release
│  │  │     │     │  │  │  ├─ [  0.56%] btree_get_root_with_key
│  │  │     │     │  │  │  │  └─ [  0.46%] pgbuf_fix_release
│  │  │     │     │  │  │  └─ [  0.34%] pgbuf_unfix
│  │  │     │     │  │  └─ [  0.69%] btree_range_scan_advance_over_filtered_keys
│  │  │     │     │  ├─ [  0.76%] btree_range_scan_select_visible_oids
│  │  │     │     │  │  └─ [  0.38%] btree_select_visible_object_for_range_scan
│  │  │     │     │  └─ [  0.70%] pgbuf_unfix
│  │  │     │     ├─ [  1.13%] fetch_copy_dbval
│  │  │     │     │  ├─ [  0.50%] fetch_peek_dbval
│  │  │     │     │  └─ [  0.48%] qdata_copy_db_value
│  │  │     │     └─ [  0.56%] btree_prepare_bts
│  │  │     ├─ [  8.65%] heap_get_visible_version
│  │  │     │  ├─ [  7.27%] heap_get_visible_version_internal
│  │  │     │  │  ├─ [  2.73%] heap_scan_cache_allocate_area
│  │  │     │  │  │  ├─ [  2.24%] heap_scancache::reserve_area
│  │  │     │  │  │  │  └─ [  2.17%] heap_scancache::alloc_area
│  │  │     │  │  │  │     └─ [  1.90%] cubmem::single_block_allocator::single_block_allocator
│  │  │     │  │  │  │        └─ [  1.31%] cubmem::block_allocator::block_allocator
│  │  │     │  │  │  │           └─ [  1.22%] operator new
│  │  │     │  │  │  └─ [  0.37%] cubmem::single_block_allocator::reserve
│  │  │     │  │  ├─ [  2.36%] heap_get_record_data_when_all_ready
│  │  │     │  │  │  └─ [  1.87%] spage_get_record_data
│  │  │     │  │  │     └─ [  1.79%] __memmove_evex_unaligned_erms
│  │  │     │  │  └─ [  1.29%] heap_prepare_get_context
│  │  │     │  └─ [  1.14%] heap_clean_get_context
│  │  │     │     └─ [  0.88%] pgbuf_unfix
│  │  │     ├─ [  1.06%] heap_attrinfo_read_dbvalues
│  │  │     └─ [  0.68%] fetch_val_list
│  │  │        └─ [  0.53%] fetch_peek_dbval
│  │  ├─ [  7.91%] qexec_end_one_iteration
│  │  │  ├─ [  3.96%] qfile_generate_tuple_into_list
│  │  │  │  ├─ [  2.96%] qdata_copy_db_value_to_tuple_value
│  │  │  │  │  └─ [  1.62%] mr_data_writeval_string
│  │  │  │  └─ [  0.50%] qfile_allocate_new_page_if_need
│  │  │  └─ [  3.56%] qexec_generate_tuple_descriptor
│  │  │     └─ [  2.96%] qdata_generate_tuple_desc_for_valptr_list
│  │  │        ├─ [  1.56%] fetch_peek_dbval
│  │  │        │  └─ [  0.92%] qdata_evaluate_function
│  │  │        │     └─ [  0.56%] heap_get_class_oid
│  │  │        └─ [  0.79%] qdata_get_tuple_value_size_from_dbval
│  │  └─ [  5.60%] qexec_next_scan_block_iterations
│  │     └─ [  5.41%] qexec_next_scan_block
│  │        ├─ [  3.46%] scan_start_scan
│  │        │  ├─ [  1.89%] heap_scancache_start
│  │        │  │  ├─ [  0.90%] heap_get_class_info
│  │        │  │  │  └─ [  0.90%] heap_hfid_cache_get
│  │        │  │  │     └─ [  0.58%] lf_hash_insert_internal
│  │        │  │  └─ [  0.60%] lock_scan
│  │        │  └─ [  1.07%] heap_attrinfo_start
│  │        │     └─ [  0.47%] heap_classrepr_get
│  │        └─ [  1.25%] scan_end_scan
│  │           └─ [  0.95%] heap_scancache_end
│  │              └─ [  0.94%] heap_scancache_quick_end
│  │                 └─ [  0.81%] heap_scancache::end_area
│  │                    └─ [  0.70%] cubmem::single_block_allocator::~single_block_allocator
│  ├─ [  5.75%] qexec_open_scan
│  │  └─ [  4.83%] scan_open_index_scan
│  │     ├─ [  1.81%] heap_get_indexinfo_of_btid
│  │     │  ├─ [  0.81%] heap_classrepr_get
│  │     │  └─ [  0.53%] heap_classrepr_free
│  │     ├─ [  0.96%] pgbuf_fix_release
│  │     └─ [  0.63%] pgbuf_unfix
│  ├─ [  2.20%] qexec_start_mainblock_iterations
│  │  ├─ [  1.22%] qfile_open_list
│  │  │  └─ [  0.86%] qmgr_create_new_temp_file
│  │  └─ [  0.41%] qdata_get_valptr_type_list
│  ├─ [  1.05%] scan_close_scan
│  └─ [  9.64%] lock_object
├─ [  9.36%] locator_attribute_info_force
│  ├─ [  6.15%] locator_allocate_copy_area_by_attr_info
│  │  ├─ [  4.71%] heap_attrinfo_transform_to_disk_internal
│  │  │  ├─ [  1.89%] heap_attrinfo_transform_variable_to_disk
│  │  │  │  └─ [  1.16%] mr_data_writeval_string
│  │  │  └─ [  0.92%] heap_attrinfo_set_uninitialized
│  │  │     └─ [  0.43%] heap_attrvalue_read
│  │  └─ [  0.49%] locator_allocate_copy_area_by_length
│  ├─ [  1.78%] heap_get_last_version
│  │  ├─ [  0.83%] heap_scan_cache_allocate_area
│  │  │  └─ [  0.59%] heap_scancache::reserve_area
│  │  │     └─ [  0.57%] heap_scancache::alloc_area
│  │  │        └─ [  0.42%] cubmem::single_block_allocator::single_block_allocator
│  │  └─ [  0.53%] heap_get_record_data_when_all_ready
│  ├─ [  0.42%] heap_clean_get_context
│  │  └─ [  0.36%] pgbuf_unfix
│  └─ [  0.41%] heap_attrinfo_check_unique_index
├─ [  4.25%] heap_attrinfo_set
│  ├─ [  2.06%] tp_domain_check
│  │  └─ [  1.86%] tp_domain_select
│  │     ├─ [  0.83%] tp_domain_resolve_value
│  │     └─ [  0.52%] tp_domain_match_internal
│  └─ [  0.99%] mr_setval_string
├─ [ 40.14%] scan_next_scan
│  └─ [ 39.94%] scan_next_scan_local
│     ├─ [  2.62%] fetch_val_list
│     │  └─ [  0.74%] mr_data_readval_string
│     │     └─ [  0.69%] mr_readval_string_internal
│     ├─ [  0.83%] resolve_domains_on_list_scan
│     └─ [  0.58%] qfile_scan_list_next
├─ [  3.22%] xtran_server_end_topop
│  ├─ [  1.48%] log_sysop_attach_to_outer
│  │  └─ [  0.77%] log_tdes::unlock_topop
│  │     └─ [  0.44%] cubpl::get_session
│  │        └─ [  0.35%] session_get_pl_session
│  ├─ [  0.78%] cuberr::context::pop_error_stack_and_destroy
│  │  └─ [  0.43%] cuberr::context::pop_error_stack
│  └─ [  0.46%] cuberr::context::push_error_stack
├─ [  2.22%] qexec_upddel_setup_current_class
│  └─ [  1.77%] heap_scancache_start_modify
│     ├─ [  0.98%] file_get_type
│     │  ├─ [  0.58%] pgbuf_fix_release
│     │  └─ [  0.33%] pgbuf_unfix
│     └─ [  0.55%] heap_scancache_reset_modify
├─ [  7.78%] qexec_next_scan_block_iterations
│  └─ [  7.47%] qexec_next_scan_block
│     ├─ [  4.38%] scan_start_scan
│     │  └─ [  0.57%] qfile_open_list_scan
│     │     └─ [  0.44%] qfile_copy_list_id
│     └─ [  2.11%] scan_end_scan
│        └─ [  0.49%] qfile_close_scan
├─ [  2.94%] heap_attrinfo_start
│  ├─ [  1.41%] heap_attrinfo_recache_attrepr
│  └─ [  0.92%] heap_classrepr_get
├─ [  2.01%] qexec_clear_internal_classes
│  ├─ [  0.95%] heap_attrinfo_end
│  │  └─ [  0.59%] heap_attrinfo_clear_dbvalues
│  └─ [  0.56%] heap_scancache_quick_end
│     └─ [  0.49%] heap_scancache::end_area
│        └─ [  0.42%] cubmem::single_block_allocator::~single_block_allocator
├─ [  1.79%] logtb_get_mvcc_snapshot
│  └─ [  1.43%] mvcctable::build_mvcc_info
├─ [  1.64%] xtran_server_start_topop
│  └─ [  1.25%] log_sysop_start
│     └─ [  0.72%] rmutex_lock
├─ [  6.47%] qexec_open_scan
│  └─ [  0.57%] scan_open_list_scan
├─ [  0.69%] qexec_create_internal_classes
└─ [  0.60%] qexec_set_class_locks
```
