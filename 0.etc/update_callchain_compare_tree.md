# UPDATE 콜체인 비교 (트리 버전) — v2 (2.) vs tuned (5.)

비교 대상:
- `2.update_call_chain/REPORT.md` 섹션 2 (v2 raw stack 트리, qeu=100%, 0.3% 컷오프)
- `5.update_call_chain_tuned/parallel_update_perf_final.md` 섹션 2 (tuned, qeu=100%, 0.3% 컷오프)

기준: `qexec_execute_update` = 100% (qeu inclusive %).
v2 트리 구조를 기준으로 각 노드에 v2/tuned 값과 Δ(=tuned−v2)를 병기했습니다.
tuned 트리의 0.3% 컷오프로 사라진 노드는 `--` 로 표기 (실제로 사라진 게 아니라 컷오프 아래로 분산된 경우도 포함).

## 형식 설명

각 노드는 다음 형식으로 표기:

```
[v2% / tn%, Δ] function_name
```

- **v2%** — `2.update_call_chain/REPORT.md` 섹션 2 트리에서 해당 노드의 inclusive % (qeu=100% 기준으로 정규화). 즉, qeu 가 들어간 전체 stack 중 이 호출 경로 (root→...→해당 노드) 가 등장한 비율.
- **tn%** — `5.update_call_chain_tuned/parallel_update_perf_final.md` 섹션 2 트리에서 같은 위치(같은 부모 경로 아래 같은 함수)의 inclusive %. tuned 트리는 0.3% 컷오프이므로 그 아래로 떨어진 노드는 `--` 로 표기.
- **Δ** — `tn% − v2%`. 양수면 tuned 에서 비중이 늘어난 것, 음수면 줄어든 것. `−` 는 Unicode minus (U+2212), `+` 는 ASCII. tuned 가 `--` 면 Δ 도 `--`.

읽는 법:
- inclusive % 는 "그 노드 + 그 노드의 모든 자손 시간" 의 합 비율이므로, 자식 노드들의 % 합이 부모 % 보다 작거나 같음 (perf 의 다른 자식이 컷오프로 안 보일 수 있고, 자기 자신의 self-time 도 부모에 포함됨).
- **같은 함수가 트리의 다른 위치에 등장하면 각 위치마다 별도의 노드로 나타나고, 위치별 Δ 가 서로 다를 수 있음.** UPDATE 트리는 이 효과가 매우 두드러짐:
  - `scan_next_scan` 은 `qexec_intprt_fnc` 아래 (v2 39.55 → tn 36.28, Δ −3.27) 와 root 직속 (v2 3.24 → tn 40.14, Δ +36.90) 두 군데 등장. 트리 구조 자체가 tuned 에서 root-level 쪽으로 더 분기됨.
  - `lock_object` 도 `locator_lock_and_get_object_internal` 아래 (Δ −6.22) 와 `qexec_execute_mainblock` 직속 (Δ +9.32) 두 위치에 등장.
  - 함수명 기준으로 합산한 값은 `update_callchain_compare.md` 의 표 참고.
- v2 와 tuned 의 트리는 캡처 자체가 다르므로 (다른 빌드, 다른 시점), 같은 위치라도 약간의 노이즈가 섞일 수 있음. ±0.3% 정도의 작은 Δ 는 노이즈 가능성을 염두에 두고 해석.
- `--` 가 의미하는 것: tuned 트리의 0.3% 컷오프 아래로 분산됐거나, 실제로 거의 사라졌거나 둘 중 하나. 트리만으론 구분 불가 — `parallel_update_perf_final.md` 의 perf script raw dump 를 직접 봐야 확정 가능.

예:
- `[15.57 / 9.35, −6.22] lock_object` (`locator_lock_and_get_object_internal` 아래) → v2 에선 qeu 의 15.57% 가 이 경로로 lock_object 에 진입했지만 tuned 에선 9.35% 로 6.22%p 감소.
- `[3.24 / 40.14, +36.90] scan_next_scan` (root 직속) → 위치별 비중이 폭증. 다른 위치의 `scan_next_scan` 은 줄었으므로 (위 참고), 트리 구조가 root-level 로 옮겨간 것.
- `[0.39 / --, --] lock_insert_into_tran_hold_list` → v2 에선 0.39% 잡혔지만 tuned 트리엔 컷오프 아래로 빠짐.

## 트리

```
[100.00 / 100.00, 0.00] qexec_execute_update
├─ [66.58 / 62.48, −4.10] qexec_execute_mainblock
│  ├─ [53.80 / 50.67, −3.13] qexec_intprt_fnc
│  │  ├─ [39.55 / 36.28, −3.27] scan_next_scan
│  │  │  └─ [39.45 / 36.16, −3.29] scan_next_scan_local
│  │  │     ├─ [17.61 / 12.08, −5.53] locator_lock_and_get_object_with_evaluation
│  │  │     │  ├─ [16.62 / 10.86, −5.76] locator_lock_and_get_object_internal
│  │  │     │  │  ├─ [15.57 / 9.35, −6.22] lock_object
│  │  │     │  │  │  └─ [15.14 / 8.93, −6.21] lock_internal_perform_lock_object
│  │  │     │  │  │     ├─ [12.45 / 7.19, −5.26] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│  │  │     │  │  │     │  └─ [12.13 / 7.01, −5.12] lf_hash_insert_internal
│  │  │     │  │  │     │     ├─ [9.35 / 5.18, −4.17] lock_res_key_compare
│  │  │     │  │  │     │     └─ [1.46 / 0.74, −0.72] lf_freelist_claim
│  │  │     │  │  │     │        ├─ [1.03 / 0.43, −0.60] lf_freelist_alloc_block
│  │  │     │  │  │     │        │  └─ [1.03 / 0.42, −0.61] lock_alloc_resource
│  │  │     │  │  │     │        │     └─ [1.02 / --, --] malloc
│  │  │     │  │  │     │        └─ [0.33 / --, --] lf_stack_pop
│  │  │     │  │  │     ├─ [1.71 / 1.66, −0.05] lf_freelist_claim
│  │  │     │  │  │     │  ├─ [0.77 / 0.84, +0.07] lf_freelist_alloc_block
│  │  │     │  │  │     │  │  └─ [0.76 / --, --] malloc
│  │  │     │  │  │     │  │     └─ [0.66 / --, --] _int_malloc
│  │  │     │  │  │     │  └─ [0.45 / 0.46, +0.01] lf_stack_pop
│  │  │     │  │  │     └─ [0.39 / --, --] lock_insert_into_tran_hold_list
│  │  │     │  │  │        └─ [0.33 / --, --] __pthread_mutex_lock
│  │  │     │  │  └─ [0.74 / 1.11, +0.37] heap_get_last_version
│  │  │     │  │     └─ [0.32 / 0.36, +0.04] heap_get_record_data_when_all_ready
│  │  │     │  └─ [0.58 / 0.62, +0.04] heap_clean_get_context
│  │  │     │     └─ [0.51 / 0.52, +0.01] pgbuf_unfix
│  │  │     ├─ [11.10 / 11.51, +0.41] call_get_next_index_oidset
│  │  │     │  └─ [10.89 / 11.26, +0.37] scan_get_index_oidset
│  │  │     │     ├─ [8.17 / 8.40, +0.23] btree_range_scan
│  │  │     │     │  ├─ [6.30 / 6.55, +0.25] btree_range_scan_start
│  │  │     │     │  │  ├─ [5.71 / 5.73, +0.02] btree_locate_key
│  │  │     │     │  │  │  ├─ [1.72 / 1.74, +0.02] btree_search_leaf_page
│  │  │     │     │  │  │  │  └─ [0.33 / --, --] spage_get_record
│  │  │     │     │  │  │  ├─ [1.70 / 1.96, +0.26] btree_search_nonleaf_page
│  │  │     │     │  │  │  │  └─ [0.33 / 0.44, +0.11] btree_compare_key
│  │  │     │     │  │  │  ├─ [0.70 / 1.05, +0.35] pgbuf_fix_release
│  │  │     │     │  │  │  ├─ [0.62 / 0.56, −0.06] btree_get_root_with_key
│  │  │     │     │  │  │  │  └─ [0.51 / 0.46, −0.05] pgbuf_fix_release
│  │  │     │     │  │  │  └─ [0.41 / 0.34, −0.07] pgbuf_unfix
│  │  │     │     │  │  └─ [0.50 / 0.69, +0.19] btree_range_scan_advance_over_filtered_keys
│  │  │     │     │  ├─ [0.77 / 0.76, −0.01] btree_range_scan_select_visible_oids
│  │  │     │     │  │  └─ [0.38 / 0.38, 0.00] btree_select_visible_object_for_range_scan
│  │  │     │     │  └─ [0.45 / 0.70, +0.25] pgbuf_unfix
│  │  │     │     ├─ [0.98 / 1.13, +0.15] fetch_copy_dbval
│  │  │     │     │  ├─ [0.44 / 0.50, +0.06] fetch_peek_dbval
│  │  │     │     │  └─ [0.37 / 0.48, +0.11] qdata_copy_db_value
│  │  │     │     └─ [0.40 / 0.56, +0.16] btree_prepare_bts
│  │  │     ├─ [7.08 / 8.65, +1.57] heap_get_visible_version
│  │  │     │  ├─ [5.66 / 7.27, +1.61] heap_get_visible_version_internal
│  │  │     │  │  ├─ [2.85 / 2.73, −0.12] heap_scan_cache_allocate_area
│  │  │     │  │  │  ├─ [2.37 / 2.24, −0.13] heap_scancache::reserve_area
│  │  │     │  │  │  │  └─ [2.32 / 2.17, −0.15] heap_scancache::alloc_area
│  │  │     │  │  │  │     └─ [2.06 / 1.90, −0.16] cubmem::single_block_allocator::single_block_allocator
│  │  │     │  │  │  │        └─ [1.59 / 1.31, −0.28] cubmem::block_allocator::block_allocator
│  │  │     │  │  │  │           └─ [1.50 / 1.22, −0.28] operator new
│  │  │     │  │  │  │              └─ [1.48 / --, --] malloc
│  │  │     │  │  │  └─ [0.32 / 0.37, +0.05] cubmem::single_block_allocator::reserve
│  │  │     │  │  ├─ [1.29 / 2.36, +1.07] heap_get_record_data_when_all_ready
│  │  │     │  │  │  └─ [0.78 / 1.87, +1.09] spage_get_record_data
│  │  │     │  │  │     └─ [0.66 / 1.79, +1.13] __memmove_evex_unaligned_erms
│  │  │     │  │  └─ [0.72 / 1.29, +0.57] heap_prepare_get_context
│  │  │     │  └─ [1.15 / 1.14, −0.01] heap_clean_get_context
│  │  │     │     └─ [0.93 / 0.88, −0.05] pgbuf_unfix
│  │  │     │        └─ [0.47 / --, --] pgbuf_unlatch_void_zone_bcb
│  │  │     ├─ [0.95 / 1.06, +0.11] heap_attrinfo_read_dbvalues
│  │  │     └─ [0.56 / 0.68, +0.12] fetch_val_list
│  │  │        └─ [0.43 / 0.53, +0.10] fetch_peek_dbval
│  │  ├─ [8.39 / 7.91, −0.48] qexec_end_one_iteration
│  │  │  ├─ [4.64 / 3.96, −0.68] qfile_generate_tuple_into_list
│  │  │  │  ├─ [3.54 / 2.96, −0.58] qdata_copy_db_value_to_tuple_value
│  │  │  │  │  └─ [2.22 / 1.62, −0.60] mr_data_writeval_string
│  │  │  │  └─ [0.57 / 0.50, −0.07] qfile_allocate_new_page_if_need
│  │  │  └─ [3.34 / 3.56, +0.22] qexec_generate_tuple_descriptor
│  │  │     └─ [2.72 / 2.96, +0.24] qdata_generate_tuple_desc_for_valptr_list
│  │  │        ├─ [1.47 / 1.56, +0.09] fetch_peek_dbval
│  │  │        │  └─ [0.87 / 0.92, +0.05] qdata_evaluate_function
│  │  │        │     └─ [0.50 / 0.56, +0.06] heap_get_class_oid
│  │  │        └─ [0.76 / 0.79, +0.03] qdata_get_tuple_value_size_from_dbval
│  │  └─ [5.02 / 5.60, +0.58] qexec_next_scan_block_iterations
│  │     └─ [4.88 / 5.41, +0.53] qexec_next_scan_block
│  │        ├─ [3.05 / 3.46, +0.41] scan_start_scan
│  │        │  ├─ [1.76 / 1.89, +0.13] heap_scancache_start
│  │        │  │  ├─ [0.99 / 0.90, −0.09] heap_get_class_info
│  │        │  │  │  └─ [0.99 / 0.90, −0.09] heap_hfid_cache_get
│  │        │  │  │     └─ [0.72 / 0.58, −0.14] lf_hash_insert_internal
│  │        │  │  └─ [0.43 / 0.60, +0.17] lock_scan
│  │        │  └─ [0.79 / 1.07, +0.28] heap_attrinfo_start
│  │        │     └─ [0.38 / 0.47, +0.09] heap_classrepr_get
│  │        └─ [1.19 / 1.25, +0.06] scan_end_scan
│  │           └─ [0.86 / 0.95, +0.09] heap_scancache_end
│  │              └─ [0.86 / 0.94, +0.08] heap_scancache_quick_end
│  │                 └─ [0.75 / 0.81, +0.06] heap_scancache::end_area
│  │                    └─ [0.65 / 0.70, +0.05] cubmem::single_block_allocator::~single_block_allocator
│  ├─ [6.65 / 5.75, −0.90] qexec_open_scan
│  │  └─ [5.92 / 4.83, −1.09] scan_open_index_scan
│  │     ├─ [2.37 / 1.81, −0.56] heap_get_indexinfo_of_btid
│  │     │  ├─ [1.20 / 0.81, −0.39] heap_classrepr_get
│  │     │  │  └─ [0.33 / --, --] __pthread_mutex_lock
│  │     │  └─ [0.76 / 0.53, −0.23] heap_classrepr_free
│  │     │     └─ [0.41 / --, --] __pthread_mutex_unlock_usercnt
│  │     ├─ [1.09 / 0.96, −0.13] pgbuf_fix_release
│  │     └─ [0.88 / 0.63, −0.25] pgbuf_unfix
│  ├─ [2.61 / 2.20, −0.41] qexec_start_mainblock_iterations
│  │  ├─ [1.55 / 1.22, −0.33] qfile_open_list
│  │  │  └─ [1.23 / 0.86, −0.37] qmgr_create_new_temp_file
│  │  │     └─ [0.60 / --, --] __pthread_mutex_lock
│  │  └─ [0.40 / 0.41, +0.01] qdata_get_valptr_type_list
│  ├─ [0.92 / 1.05, +0.13] scan_close_scan
│  └─ [0.32 / 9.64, +9.32] lock_object       ※ qexec_execute_mainblock 직속 lock_object — tuned 에서 위치별 비중 급증
├─ [8.54 / 9.36, +0.82] locator_attribute_info_force
│  ├─ [5.64 / 6.15, +0.51] locator_allocate_copy_area_by_attr_info
│  │  ├─ [4.00 / 4.71, +0.71] heap_attrinfo_transform_to_disk_internal
│  │  │  ├─ [1.76 / 1.89, +0.13] heap_attrinfo_transform_variable_to_disk
│  │  │  │  └─ [1.13 / 1.16, +0.03] mr_data_writeval_string
│  │  │  └─ [0.81 / 0.92, +0.11] heap_attrinfo_set_uninitialized
│  │  │     └─ [0.35 / 0.43, +0.08] heap_attrvalue_read
│  │  └─ [0.71 / 0.49, −0.22] locator_allocate_copy_area_by_length
│  │     └─ [0.33 / --, --] malloc
│  │        └─ [0.33 / --, --] _int_malloc
│  ├─ [1.48 / 1.78, +0.30] heap_get_last_version
│  │  ├─ [0.71 / 0.83, +0.12] heap_scan_cache_allocate_area
│  │  │  └─ [0.56 / 0.59, +0.03] heap_scancache::reserve_area
│  │  │     └─ [0.56 / 0.57, +0.01] heap_scancache::alloc_area
│  │  │        └─ [0.42 / 0.42, 0.00] cubmem::single_block_allocator::single_block_allocator
│  │  └─ [0.41 / 0.53, +0.12] heap_get_record_data_when_all_ready
│  ├─ [0.40 / 0.42, +0.02] heap_clean_get_context
│  │  └─ [0.33 / 0.36, +0.03] pgbuf_unfix
│  └─ [0.36 / 0.41, +0.05] heap_attrinfo_check_unique_index
├─ [3.40 / 4.25, +0.85] heap_attrinfo_set
│  ├─ [1.70 / 2.06, +0.36] tp_domain_check
│  │  └─ [1.54 / 1.86, +0.32] tp_domain_select
│  │     ├─ [0.58 / 0.83, +0.25] tp_domain_resolve_value
│  │     └─ [0.50 / 0.52, +0.02] tp_domain_match_internal
│  └─ [0.70 / 0.99, +0.29] mr_setval_string
├─ [3.24 / 40.14, +36.90] scan_next_scan       ※ root 직속 scan_next_scan — tuned 에서 위치별 비중 급증
│  └─ [3.18 / 39.94, +36.76] scan_next_scan_local
│     ├─ [1.43 / 2.62, +1.19] fetch_val_list
│     │  └─ [0.54 / 0.74, +0.20] mr_data_readval_string
│     │     └─ [0.50 / 0.69, +0.19] mr_readval_string_internal
│     ├─ [0.84 / 0.83, −0.01] resolve_domains_on_list_scan
│     └─ [0.53 / 0.58, +0.05] qfile_scan_list_next
├─ [2.85 / 3.22, +0.37] xtran_server_end_topop
│  ├─ [1.35 / 1.48, +0.13] log_sysop_attach_to_outer
│  │  └─ [0.78 / 0.77, −0.01] log_tdes::unlock_topop
│  │     └─ [0.50 / 0.44, −0.06] cubpl::get_session
│  │        └─ [0.37 / 0.35, −0.02] session_get_pl_session
│  ├─ [0.78 / 0.78, 0.00] cuberr::context::pop_error_stack_and_destroy
│  │  └─ [0.38 / 0.43, +0.05] cuberr::context::pop_error_stack
│  └─ [0.35 / 0.46, +0.11] cuberr::context::push_error_stack
├─ [2.09 / 2.22, +0.13] qexec_upddel_setup_current_class
│  └─ [1.63 / 1.77, +0.14] heap_scancache_start_modify
│     ├─ [1.02 / 0.98, −0.04] file_get_type
│     │  ├─ [0.66 / 0.58, −0.08] pgbuf_fix_release
│     │  └─ [0.31 / 0.33, +0.02] pgbuf_unfix
│     └─ [0.34 / 0.55, +0.21] heap_scancache_reset_modify
├─ [2.00 / 7.78, +5.78] qexec_next_scan_block_iterations       ※ root 직속 — tuned 에서 비중 급증
│  └─ [1.93 / 7.47, +5.54] qexec_next_scan_block
│     ├─ [0.95 / 4.38, +3.43] scan_start_scan
│     │  └─ [0.70 / 0.57, −0.13] qfile_open_list_scan
│     │     └─ [0.55 / 0.44, −0.11] qfile_copy_list_id
│     └─ [0.80 / 2.11, +1.31] scan_end_scan
│        └─ [0.41 / 0.49, +0.08] qfile_close_scan
├─ [1.76 / 2.94, +1.18] heap_attrinfo_start
│  ├─ [0.96 / 1.41, +0.45] heap_attrinfo_recache_attrepr
│  └─ [0.54 / 0.92, +0.38] heap_classrepr_get
├─ [1.68 / 2.01, +0.33] qexec_clear_internal_classes
│  ├─ [0.85 / 0.95, +0.10] heap_attrinfo_end
│  │  └─ [0.45 / 0.59, +0.14] heap_attrinfo_clear_dbvalues
│  └─ [0.41 / 0.56, +0.15] heap_scancache_quick_end
│     └─ [0.38 / 0.49, +0.11] heap_scancache::end_area
│        └─ [0.31 / 0.42, +0.11] cubmem::single_block_allocator::~single_block_allocator
├─ [1.56 / 1.79, +0.23] logtb_get_mvcc_snapshot
│  └─ [1.32 / 1.43, +0.11] mvcctable::build_mvcc_info
├─ [1.43 / 1.64, +0.21] xtran_server_start_topop
│  └─ [1.20 / 1.25, +0.05] log_sysop_start
│     └─ [0.59 / 0.72, +0.13] rmutex_lock
├─ [0.96 / 6.47, +5.51] qexec_open_scan       ※ root 직속 qexec_open_scan — tuned 에서 비중 급증
│  └─ [0.79 / 0.57, −0.22] scan_open_list_scan
│     └─ [0.39 / --, --] prm_get_value
├─ [0.60 / 0.69, +0.09] qexec_create_internal_classes
└─ [0.50 / 0.60, +0.10] qexec_set_class_locks
```

## 주요 변화 (큰 Δ 만)

### 줄어든 경로 (tuned 가 더 작음, 주로 lock contention 쪽)
- `qexec_intprt_fnc → scan_next_scan_local → locator_lock_and_get_object_with_evaluation` 서브트리: 17.61 → 12.08 (−5.53).
  - 그 안의 `lock_object` (−6.22), `lock_internal_perform_lock_object` (−6.21), `lockfree_hashmap::find_or_insert` (−5.26), `lf_hash_insert_internal` (−5.12), `lock_res_key_compare` (−4.17) — INSERT 와 마찬가지로 lock_res_key_compare / lf_hash_insert 비중 큰 폭 감소.
- `qexec_open_scan → scan_open_index_scan` (qexec_execute_mainblock 직속): 6.65 → 5.75 (−0.90).
- `qexec_end_one_iteration` 전체: 8.39 → 7.91 (−0.48). 안쪽 `qfile_generate_tuple_into_list` (−0.68), `mr_data_writeval_string` (−0.60).

### 늘어난 경로 (tuned 가 더 큼)
- **root 직속 `scan_next_scan`**: 3.24 → 40.14 (+36.90). v2 에선 거의 안 보이던 경로가 tuned 에선 메인 비중을 차지. 같은 함수의 `qexec_intprt_fnc` 아래 위치는 오히려 줄었으므로 (39.55 → 36.28), tuned 의 콜체인이 root-level scan_next_scan 으로 더 많이 분기된 것으로 보임. 위치별 함수 합산은 `update_callchain_compare.md` 표 참고.
- **root 직속 `qexec_next_scan_block_iterations`**: 2.00 → 7.78 (+5.78), 그 안의 `scan_start_scan` +3.43, `scan_end_scan` +1.31.
- **root 직속 `qexec_open_scan`**: 0.96 → 6.47 (+5.51). 직속 child `scan_open_list_scan` 은 −0.22 로 작으므로, 늘어난 5.51% 의 대부분은 컷오프 아래로 분산된 것으로 추정.
- **root 직속 `lock_object`** (qexec_execute_mainblock 직속): 0.32 → 9.64 (+9.32). 마찬가지로 `qexec_intprt_fnc` 아래 lock_object 는 줄었지만 다른 위치로 옮겨간 형태.
- `heap_get_visible_version` 서브트리: 7.08 → 8.65 (+1.57). 안쪽 `heap_get_record_data_when_all_ready` +1.07, `spage_get_record_data` +1.09, `__memmove_evex_unaligned_erms` +1.13 — record body 복사 비중 증가 (INSERT 의 `spage_insert_data` 와 같은 양상).
- root 직속 `heap_attrinfo_start`: 1.76 → 2.94 (+1.18).
- `locator_attribute_info_force` 서브트리: 8.54 → 9.36 (+0.82).
- `heap_attrinfo_set`: 3.40 → 4.25 (+0.85).

## 주의

- tuned 트리의 0.3% 컷오프 때문에 `malloc` / `_int_malloc` / `__pthread_mutex_lock` / `__pthread_mutex_unlock_usercnt` / `lock_insert_into_tran_hold_list` / `pgbuf_unlatch_void_zone_bcb` / `spage_get_record` / `prm_get_value` 등은 트리에 안 잡혀서 `--` 로 표기. **완전히 사라진 게 아니라 컷오프 아래로 분산됐을 수 있음.**
- 위 트리는 v2 의 트리 구조를 기준으로 노드별 값을 병기한 것이므로, 같은 함수가 트리의 다른 위치에 나타나면 각 위치마다 Δ 가 별도로 계산됨. 예) `scan_next_scan` 은 `qexec_intprt_fnc` 아래 (−3.27) 와 root 직속 (+36.90) 위치에서 Δ 가 정반대. 함수명 누적으로 보면 (`update_callchain_compare.md` 의 표) 두 캡처 합산값은 v2 42.79% → tuned 76.42% (+33.63) 로 전체적으로는 늘었음.
- 두 캡처의 qeu 자체 비중 (전체 on-CPU 중) — v2: 7.75%, tuned: 9.77% — 은 다르지만, 위 트리는 두 쪽 모두 qeu=100% 로 정규화한 값이므로 함수별 비율 비교는 그대로 유효함.
- 함수별 누적 합산값은 `update_callchain_compare.md` 의 표 참고.
