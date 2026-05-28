# UPDATE 콜체인 비교 — v2 (2.) vs tuned (5.)

비교 대상:
- `2.update_call_chain/REPORT.md` (v2 master, 섹션 2/3)
- `5.update_call_chain_tuned/parallel_update_perf_final.md` (tuned, 섹션 2)

기준: `qexec_execute_update` = 100% (qeu inclusive %)

## 함수별 inclusive % 비교

tuned 값은 트리 내 동일 함수가 여러 경로에 등장하면 합산했습니다.
v2 트리에는 있지만 tuned 트리에는 안 보이는 함수(0.3% 컷오프 아래로 떨어졌거나 제거된 경우)는 `-` 로 표기했습니다.

| 함수 | v2 (2.) % | tuned (5.) % | Δ (tuned − v2) |
|---|---:|---:|---:|
| `qexec_execute_update` | 100.00 | 100.00 | 0.00 |
| `qexec_execute_mainblock` | 99.96 | 62.48 | −37.48 |
| `qexec_intprt_fnc` | 53.80 | 50.67 | −3.13 |
| `scan_next_scan` | 42.79 | 76.42 | +33.63 |
| `scan_next_scan_local` | 42.63 | 76.10 | +33.47 |
| `locator_lock_and_get_object_with_evaluation` | 17.61 | 12.08 | −5.53 |
| `locator_lock_and_get_object_internal` | 16.63 | 10.86 | −5.77 |
| `lock_object` | 16.19 | 18.99 | +2.80 |
| `lock_internal_perform_lock_object` | 15.65 | 8.93 | −6.72 |
| `lf_hash_insert_internal` | 13.03 | 7.59 | −5.44 |
| `lockfree_hashmap<lk_res_key,lk_res>::find_or_insert` | 12.46 | 7.19 | −5.27 |
| `call_get_next_index_oidset` | 11.10 | 11.51 | +0.41 |
| `scan_get_index_oidset` | 10.89 | 11.26 | +0.37 |
| `lock_res_key_compare` | 9.35 | 5.18 | −4.17 |
| `locator_attribute_info_force` | 8.54 | 9.36 | +0.82 |
| `qexec_end_one_iteration` | 8.39 | 7.91 | −0.48 |
| `btree_range_scan` | 8.17 | 8.40 | +0.23 |
| `qexec_open_scan` | 7.61 | 12.22 | +4.61 |
| `heap_get_visible_version` | 7.08 | 8.65 | +1.57 |
| `qexec_next_scan_block_iterations` | 7.02 | 13.38 | +6.36 |
| `qexec_next_scan_block` | 6.81 | 12.88 | +6.07 |
| `btree_range_scan_start` | 6.30 | 6.55 | +0.25 |
| `scan_open_index_scan` | 5.92 | 4.83 | −1.09 |
| `btree_locate_key` | 5.71 | 5.73 | +0.02 |
| `heap_get_visible_version_internal` | 5.66 | 7.27 | +1.61 |
| `locator_allocate_copy_area_by_attr_info` | 5.64 | 6.15 | +0.51 |
| `malloc` | 4.73 | − | — |
| `qfile_generate_tuple_into_list` | 4.64 | 3.96 | −0.68 |
| `pgbuf_unfix` | 4.07 | 3.76 | −0.31 |
| `heap_attrinfo_transform_to_disk_internal` | 4.00 | 4.71 | +0.71 |
| `scan_start_scan` | 4.00 | 7.84 | +3.84 |
| `heap_scan_cache_allocate_area` | 3.61 | 3.56 | −0.05 |
| `qdata_copy_db_value_to_tuple_value` | 3.55 | 2.96 | −0.59 |
| `heap_attrinfo_set` | 3.40 | 4.25 | +0.85 |
| `mr_data_writeval_string` | 3.35 | 2.78 | −0.57 |
| `qexec_generate_tuple_descriptor` | 3.34 | 3.56 | +0.22 |
| `_int_malloc` | 3.24 | − | — |
| `lf_freelist_claim` | 3.17 | 2.40 | −0.77 |
| `heap_scancache::reserve_area` | 2.96 | 2.83 | −0.13 |
| `pgbuf_fix_release` | 2.96 | 3.05 | +0.09 |
| `heap_scancache::alloc_area` | 2.89 | 2.74 | −0.15 |
| `__pthread_mutex_lock` | 2.88 | − | — |
| `xtran_server_end_topop` | 2.85 | 3.22 | +0.37 |
| `qdata_generate_tuple_desc_for_valptr_list` | 2.72 | 2.96 | +0.24 |
| `qexec_start_mainblock_iterations` | 2.61 | 2.20 | −0.41 |
| `heap_attrinfo_start` | 2.55 | 4.01 | +1.46 |
| `cubmem::single_block_allocator::single_block_allocator` | 2.48 | 2.32 | −0.16 |
| `heap_get_indexinfo_of_btid` | 2.37 | 1.81 | −0.56 |
| `fetch_peek_dbval` | 2.35 | 2.59 | +0.24 |
| `std::_Function_base::_Base_manager<...>` | 2.34 | − | — |
| `heap_get_last_version` | 2.21 | 2.89 | +0.68 |
| `__pthread_mutex_unlock_usercnt` | 2.14 | − | — |
| `heap_classrepr_get` | 2.12 | 2.20 | +0.08 |
| `heap_clean_get_context` | 2.12 | 2.18 | +0.06 |
| `qexec_upddel_setup_current_class` | 2.09 | 2.22 | +0.13 |
| `operator new` | 2.08 | 1.22 | −0.86 |
| `heap_get_record_data_when_all_ready` | 2.03 | 3.25 | +1.22 |
| `scan_end_scan` | 2.00 | 3.36 | +1.36 |
| `fetch_val_list` | 1.99 | 3.30 | +1.31 |
| `lf_freelist_alloc_block` | 1.80 | 1.27 | −0.53 |
| `heap_attrinfo_transform_variable_to_disk` | 1.76 | 1.89 | +0.13 |
| `heap_scancache_start` | 1.76 | 1.89 | +0.13 |
| `btree_search_leaf_page` | 1.72 | 1.74 | +0.02 |
| `cubmem::block_allocator::block_allocator` | 1.70 | 1.31 | −0.39 |
| `btree_search_nonleaf_page` | 1.70 | 1.96 | +0.26 |
| `tp_domain_check` | 1.70 | 2.06 | +0.36 |
| `qexec_clear_internal_classes` | 1.68 | 2.01 | +0.33 |
| `logtb_get_mvcc_snapshot` | 1.67 | 1.79 | +0.12 |
| `heap_scancache_start_modify` | 1.63 | 1.77 | +0.14 |
| `spage_get_record_data` | 1.62 | 1.87 | +0.25 |
| `qfile_open_list` | 1.55 | 1.22 | −0.33 |
| `tp_domain_select` | 1.54 | 1.86 | +0.32 |
| `__memmove_evex_unaligned_erms` | 1.51 | 1.79 | +0.28 |
| `xtran_server_start_topop` | 1.43 | 1.64 | +0.21 |
| `log_sysop_attach_to_outer` | 1.35 | 1.48 | +0.13 |
| `mvcctable::build_mvcc_info` | 1.32 | 1.43 | +0.11 |
| `heap_scancache_quick_end` | 1.27 | 1.50 | +0.23 |
| `heap_hfid_cache_get` | 1.26 | 0.90 | −0.36 |
| `heap_get_class_info` | 1.26 | 0.90 | −0.36 |
| `qmgr_create_new_temp_file` | 1.23 | 0.86 | −0.37 |
| `log_sysop_start` | 1.20 | 1.25 | +0.05 |
| `heap_attrinfo_recache_attrepr` | 1.18 | 1.41 | +0.23 |
| `heap_scancache::end_area` | 1.13 | 1.30 | +0.17 |
| `heap_classrepr_free` | 1.05 | 0.53 | −0.52 |
| `heap_prepare_get_context` | 1.04 | 1.29 | +0.25 |
| `scan_close_scan` | 1.04 | 1.05 | +0.01 |
| `lock_alloc_resource` | 1.03 | 0.42 | −0.61 |
| `file_get_type` | 1.02 | 0.98 | −0.04 |
| `spage_get_record` | 0.99 | − | — |
| `fetch_copy_dbval` | 0.98 | 1.13 | +0.15 |
| `cubmem::single_block_allocator::~single_block_allocator` | 0.96 | 1.12 | +0.16 |
| `heap_attrinfo_read_dbvalues` | 0.96 | 1.06 | +0.10 |
| `qdata_evaluate_function` | 0.87 | 0.92 | +0.05 |
| `heap_scancache_end` | 0.86 | 0.95 | +0.09 |
| `heap_attrinfo_end` | 0.85 | 0.95 | +0.10 |
| `resolve_domains_on_list_scan` | 0.84 | 0.83 | −0.01 |
| `heap_attrinfo_set_uninitialized` | 0.81 | 0.92 | +0.11 |
| `scan_open_list_scan` | 0.79 | 0.57 | −0.22 |
| `cuberr::context::pop_error_stack_and_destroy` | 0.78 | 0.78 | 0.00 |
| `log_tdes::unlock_topop` | 0.78 | 0.77 | −0.01 |
| `lf_stack_pop` | 0.78 | 0.46 | −0.32 |
| `btree_range_scan_select_visible_oids` | 0.77 | 0.76 | −0.01 |
| `qdata_get_tuple_value_size_from_dbval` | 0.77 | 0.79 | +0.02 |
| `tp_domain_resolve_value` | 0.75 | 0.83 | +0.08 |
| `locator_allocate_copy_area_by_length` | 0.71 | 0.49 | −0.22 |
| `qfile_open_list_scan` | 0.70 | 0.57 | −0.13 |
| `mr_setval_string` | 0.70 | 0.99 | +0.29 |
| `btree_get_root_with_key` | 0.62 | 0.56 | −0.06 |
| `qexec_create_internal_classes` | 0.60 | 0.69 | +0.09 |
| `rmutex_lock` | 0.59 | 0.72 | +0.13 |
| `btree_range_scan_advance_over_filtered_keys` | 0.57 | 0.69 | +0.12 |
| `mr_data_readval_string` | 0.57 | 0.74 | +0.17 |
| `btree_compare_key` | 0.57 | 0.44 | −0.13 |
| `qfile_allocate_new_page_if_need` | 0.57 | 0.50 | −0.07 |
| `qfile_copy_list_id` | 0.55 | 0.44 | −0.11 |
| `qfile_scan_list_next` | 0.53 | 0.58 | +0.05 |
| `cubmem::single_block_allocator::reserve` | 0.53 | 0.37 | −0.16 |
| `heap_attrinfo_clear_dbvalues` | 0.52 | 0.59 | +0.07 |
| `tp_domain_match_internal` | 0.50 | 0.52 | +0.02 |
| `qexec_set_class_locks` | 0.50 | 0.60 | +0.10 |
| `mr_readval_string_internal` | 0.50 | 0.69 | +0.19 |
| `cubpl::get_session` | 0.50 | 0.44 | −0.06 |
| `heap_get_class_oid` | 0.50 | 0.56 | +0.06 |
| `pgbuf_unlatch_void_zone_bcb` | 0.47 | − | — |
| `lock_scan` | 0.43 | 0.60 | +0.17 |
| `qfile_close_scan` | 0.41 | 0.49 | +0.08 |
| `qdata_get_valptr_type_list` | 0.40 | 0.41 | +0.01 |
| `btree_prepare_bts` | 0.40 | 0.56 | +0.16 |
| `lock_insert_into_tran_hold_list` | 0.39 | − | — |
| `prm_get_value` | 0.39 | − | — |
| `btree_select_visible_object_for_range_scan` | 0.38 | 0.38 | 0.00 |
| `cuberr::context::pop_error_stack` | 0.38 | 0.43 | +0.05 |
| `session_get_pl_session` | 0.37 | 0.35 | −0.02 |
| `qdata_copy_db_value` | 0.37 | 0.48 | +0.11 |
| `heap_attrinfo_check_unique_index` | 0.36 | 0.41 | +0.05 |
| `heap_attrvalue_read` | 0.35 | 0.43 | +0.08 |
| `cuberr::context::push_error_stack` | 0.35 | 0.46 | +0.11 |
| `heap_scancache_reset_modify` | 0.34 | 0.55 | +0.21 |

## 주의

- tuned 트리의 0.3% 컷오프 때문에 `malloc` / `_int_malloc` / `__pthread_mutex_lock` / `__pthread_mutex_unlock_usercnt` / `pgbuf_unlatch_void_zone_bcb` / `lock_insert_into_tran_hold_list` / `prm_get_value` / `spage_get_record` / `std::_Function_base::_Base_manager<...>` 같은 함수는 트리에 안 잡혀서 `-` 로 처리됐습니다. **완전히 사라졌다는 의미가 아니라 컷오프 아래로 분산됐을 수도 있습니다.**
- v2 측 % 는 `REPORT.md` 섹션 3 표(같은 stack 안 같은 함수는 한 번만 카운트한 dedup 값)를 그대로 가져온 값이고, tuned 측 % 는 섹션 2 트리에 나온 inclusive % 를 함수별로 단순 합산한 값입니다. 동일 stack 내 중복이 있을 경우 tuned 값은 약간 과대평가될 수 있습니다 (특히 `scan_next_scan` / `scan_next_scan_local` 같이 트리 내 동일 함수가 여러 위치에 등장하는 경우 합산 결과가 v2 dedup 값보다 크게 부풀려질 수 있음 — 위 표의 `scan_next_scan` Δ +33.63 등은 이 효과가 섞여 있으므로 절댓값보다 추세로 해석하는 것을 권장).
- 두 캡처의 qeu 자체 비중 (전체 on-CPU 중) — v2: 7.75%, tuned: 9.77% — 은 다르지만, 위 표는 두 trees 모두 qeu=100% 로 정규화한 값이므로 함수별 비율 비교는 그대로 유효합니다.
