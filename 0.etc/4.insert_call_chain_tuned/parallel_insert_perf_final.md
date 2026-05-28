# Parallel poc insert perf final

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

## 1-2) locator_insert_force call chain remapped (% of total, 0.05% cutoff)


```
[  5.78%] locator_insert_force
├─ [  4.33%] heap_insert_logical
│  ├─ [  2.34%] heap_insert_logical (재귀)
│  │  ├─ [  1.53%] heap_stats_find_best_page
│  │  │  ├─ [  0.10%] heap_stats_find_best_page (재귀)
│  │  │  ├─ [  1.04%] heap_vpid_alloc
│  │  │  │  └─ [  0.29%] log_append_undoredo_data → log_append_undoredo_crumbs
│  │  │  │     └─ [  0.21%] prior_lsa_alloc_and_copy_crumbs
│  │  │  │        └─ [  0.16%] prior_lsa_gen_undoredo_record_from_crumbs
│  │  │  ├─ [  0.27%] heap_stats_find_page_in_bestspace
│  │  │  └─ [  0.10%] heap_stats_find_best_page (재귀)
│  │  └─ [  0.78%] spage_insert_at
│  │     ├─ [  0.67%] spage_insert_data
│  │     │  └─ [  0.65%] __memmove_evex_unaligned_erms
│  │     └─ [  0.09%] spage_find_empty_slot_at
│  ├─ [  0.91%] heap_get_insert_location_with_lock (inlined)
│  │  └─ [  0.86%] lock_object
│  │     └─ [  0.83%] lock_internal_perform_lock_object
│  │        └─ [  0.18%] lf_freelist_claim
│  │           └─ [  0.09%] lf_freelist_alloc_block
│  │              └─ [  0.08%] __GI___libc_malloc
│  │                 └─ [  0.06%] _int_malloc
│  └─ [  0.88%] heap_log_insert_physical
│     ├─ [  0.78%] heap_log_insert_physical (재귀)
│     │  └─ [  0.77%] log_append_undoredo_crumbs
│     │     ├─ [  0.49%] prior_lsa_alloc_and_copy_crumbs
│     │     │  ├─ [  0.43%] prior_lsa_gen_undoredo_record_from_crumbs
│     │     │  └─ [  0.13%] cub_alloc
│     │     └─ [  0.12%] prior_lsa_next_record_internal
│     │        └─ [  0.07%] prior_lsa_next_record_internal (재귀)
│     └─ [  0.09%] heap_mvcc_log_insert
├─ [  1.22%] locator_add_or_remove_index_internal
│  ├─ [  0.39%] repl_log_insert       ★ master-only (송신측 replication log 생성)
│  ├─ [  0.35%] heap_get_class_name_alloc_if_diff
│  │  ├─ [  0.10%] cub_strdup
│  │  └─ [  0.08%] heap_get_class_record
│  ├─ [  0.10%] heap_attrinfo_read_dbvalues
│  └─ [  0.09%] heap_attrinfo_end
└─ [  0.16%] locator_check_foreign_key
   └─ [  0.08%] heap_attrinfo_start_with_index
```

## 섹션 2 — locator_insert_force call chain remapped (locator_insert_force = 100%, 0.3% cutoff)


```
[100.00%] locator_insert_force
├─ [ 74.92%] heap_insert_logical
│  ├─ [ 26.54%] heap_stats_find_best_page
│  │  ├─ [ 12.81%] file_alloc
│  │  │  ├─ [  4.36%] pgbuf_fix_release
│  │  │  │  └─ [  3.69%] pgbuf_claim_bcb_for_fix
│  │  │  ├─ [  3.08%] file_perm_alloc
│  │  │  │  ├─ [  1.69%] log_append_undoredo_data2
│  │  │  │  │  └─ [  1.64%] log_append_undoredo_crumbs
│  │  │  │  │     └─ [  0.90%] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  └─ [  0.84%] log_append_undoredo_data
│  │  │  │     └─ [  0.83%] log_append_undoredo_crumbs
│  │  │  │        └─ [  0.52%] prior_lsa_alloc_and_copy_crumbs
│  │  │  ├─ [  2.04%] heap_vpid_init_new
│  │  │  │  ├─ [  0.83%] log_append_undoredo_data
│  │  │  │  │  └─ [  0.83%] log_append_undoredo_crumbs
│  │  │  │  │     └─ [  0.43%] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  └─ [  0.88%] spage_insert
│  │  │  │     └─ [  0.75%] spage_find_empty_slot
│  │  │  │        └─ [  0.61%] spage_has_enough_total_space
│  │  │  ├─ [  1.33%] log_sysop_end_logical_undo
│  │  │  │  └─ [  1.32%] log_sysop_commit_internal
│  │  │  │     └─ [  0.69%] log_append_sysop_end
│  │  │  │        └─ [  0.36%] prior_lsa_alloc_and_copy_data
│  │  │  ├─ [  0.86%] pgbuf_unfix
│  │  │  │  └─ [  0.57%] pgbuf_unlatch_void_zone_bcb
│  │  │  ├─ [  1.30%] prior_lsa_next_record_internal
│  │  │  └─ [  0.35%] log_sysop_start_atomic
│  │  ├─ [  5.02%] log_append_undoredo_data
│  │  │  └─ [  5.00%] log_append_undoredo_crumbs
│  │  │     ├─ [  3.57%] prior_lsa_alloc_and_copy_crumbs
│  │  │     │  └─ [  0.98%] log_zip
│  │  │     │     └─ [  0.71%] LZ4_resetStream_fast
│  │  │     │        └─ [  0.64%] __memset_evex_unaligned_erms
│  │  │     └─ [  0.80%] prior_lsa_next_record_internal
│  │  ├─ [  1.44%] heap_stats_add_bestspace
│  │  │  └─ [  0.75%] mht_get
│  │  ├─ [  1.55%] spage_max_space_for_new_record
│  │  │  └─ [  0.70%] lf_hash_find
│  │  │     └─ [  0.44%] lf_list_find
│  │  ├─ [  0.81%] log_sysop_commit
│  │  │  └─ [  0.81%] log_sysop_commit_internal
│  │  │     └─ [  0.49%] log_append_sysop_end
│  │  ├─ [  1.76%] pgbuf_unfix
│  │  └─ [  0.84%] mht_get2
│  ├─ [ 15.74%] lock_object
│  │  ├─ [ 14.67%] lock_internal_perform_lock_object
│  │  │  ├─ [ 10.86%] cubthread::lockfree_hashmap<lk_res_key, lk_res>::find_or_insert
│  │  │  │  └─ [ 10.52%] lf_hash_insert_internal
│  │  │  │     ├─ [  7.54%] lock_res_key_compare
│  │  │  │     └─ [  1.11%] lf_freelist_claim
│  │  │  │        ├─ [  0.57%] lf_freelist_alloc_block
│  │  │  │        │  └─ [  0.55%] lock_alloc_resource
│  │  │  │        └─ [  0.36%] lf_stack_pop
│  │  │  └─ [  3.07%] lf_freelist_claim
│  │  │     ├─ [  1.51%] lf_freelist_alloc_block
│  │  │     └─ [  0.82%] lf_stack_pop
│  │  └─ [  0.48%] lock_get_class_lock
│  ├─ [ 15.15%] heap_log_insert_physical
│  │  ├─ [ 13.40%] log_append_undoredo_crumbs
│  │  │  ├─ [  8.42%] prior_lsa_alloc_and_copy_crumbs
│  │  │  │  ├─ [  3.69%] log_zip
│  │  │  │  │  └─ [  2.64%] LZ4_resetStream_fast
│  │  │  │  │     └─ [  2.40%] __memset_evex_unaligned_erms
│  │  │  │  ├─ [  0.75%] prior_lsa_copy_redo_data_to_node
│  │  │  │  └─ [  0.71%] __memmove_evex_unaligned_erms
│  │  │  ├─ [  2.10%] prior_lsa_next_record_internal
│  │  │  │  └─ [  0.34%] __pthread_mutex_unlock_usercnt
│  │  │  └─ [  0.47%] log_does_allow_replication
│  │  └─ [  0.55%] heap_page_update_chain_after_mvcc_op
│  ├─ [ 13.45%] spage_insert_at
│  │  ├─ [ 11.57%] spage_insert_data
│  │  │  └─ [ 11.27%] __memmove_evex_unaligned_erms
│  │  └─ [  1.63%] spage_find_empty_slot_at
│  │     └─ [  1.18%] spage_check_space
│  │        └─ [  1.14%] spage_has_enough_total_space
│  │           └─ [  0.43%] lf_hash_find
│  └─ [  2.50%] pgbuf_unfix
├─ [ 21.13%] locator_add_or_remove_index_internal
│  ├─ [  6.78%] repl_log_insert       ★ master-only (송신측 replication log)
│  │  ├─ [  0.63%] repl_log_info_alloc
│  │  ├─ [  1.00%] heap_get_class_name_alloc_if_diff
│  │  ├─ [  0.67%] heap_get_class_tde_algorithm
│  │  ├─ [  0.98%] or_packed_value_size
│  │  └─ [  0.70%] or_pack_mem_value
│  ├─ [  5.99%] heap_get_class_name_alloc_if_diff
│  │  ├─ [  1.42%] heap_get_class_record
│  │  │  └─ [  0.48%] heap_get_last_version
│  │  ├─ [  1.11%] heap_scancache_end
│  │  │  └─ [  1.09%] heap_scancache_quick_end
│  │  │     └─ [  0.66%] pgbuf_unfix
│  │  └─ [  0.62%] heap_scancache_quick_start_root_hfid
│  ├─ [  1.68%] heap_attrinfo_read_dbvalues
│  ├─ [  1.57%] heap_attrinfo_end
│  │  └─ [  0.35%] heap_classrepr_free
│  ├─ [  1.02%] heap_attrvalue_get_key
│  ├─ [  0.92%] heap_attrinfo_start_with_index
│  └─ [  0.49%] btree_insert
└─ [  2.75%] locator_check_foreign_key
   ├─ [  1.34%] heap_attrinfo_start_with_index
   │  └─ [  0.50%] heap_classrepr_get
   └─ [  0.63%] heap_attrinfo_read_dbvalues
```
