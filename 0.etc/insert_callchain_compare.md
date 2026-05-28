# INSERT 콜체인 비교 — v2 (1.) vs tuned (4.)

비교 대상:
- `1.insert_call_chain/REPORT.md` (v2 master, 섹션 2/3)
- `4.insert_call_chain_tuned/parallel_insert_perf_final.md` (tuned, 섹션 2)

기준: `locator_insert_force` = 100% (lif inclusive %)

## 함수별 inclusive % 비교

tuned 값은 트리 내 동일 함수가 여러 경로에 등장하면 합산했습니다.
v2 트리에는 있지만 tuned 트리에는 안 보이는 함수(0.3% 컷오프 아래로 떨어졌거나 제거된 경우)는 `-` 로 표기했습니다.

| 함수 | v2 (1.) % | tuned (4.) % | Δ (tuned − v2) |
|---|---:|---:|---:|
| `locator_insert_force` | 100.00 | 100.00 | 0.00 |
| `heap_insert_logical` | 80.22 | 74.92 | −5.30 |
| `heap_stats_find_best_page` | 31.71 | 26.54 | −5.17 |
| `lock_object` | 24.83 | 15.74 | −9.09 |
| `lock_internal_perform_lock_object` | 24.02 | 14.67 | −9.35 |
| `log_append_undoredo_crumbs` | 20.47 | 21.70 | +1.23 |
| `lockfree_hashmap<lk_res_key,lk_res>::find_or_insert` | 18.20 | 10.86 | −7.34 |
| `lf_hash_insert_internal` | 17.60 | 10.52 | −7.08 |
| `file_alloc` | 17.32 | 12.81 | −4.51 |
| `locator_add_or_remove_index_internal` | 16.84 | 21.13 | +4.29 |
| `lock_res_key_compare` | 14.26 | 7.54 | −6.72 |
| `heap_log_insert_physical` | 13.98 | 15.15 | +1.17 |
| `prior_lsa_alloc_and_copy_crumbs` | 12.54 | 13.84 | +1.30 |
| `malloc` | 11.61 | − | — |
| `_int_malloc` | 8.66 | − | — |
| `pgbuf_fix_release` | 7.43 | 4.36 | −3.07 |
| `prior_lsa_next_record_internal` | 6.90 | 4.20 | −2.70 |
| `spage_insert_at` | 6.61 | 13.45 | +6.84 |
| `log_append_undoredo_data` | 6.59 | 6.69 | +0.10 |
| `pgbuf_claim_bcb_for_fix` | 6.03 | 3.69 | −2.34 |
| `__pthread_mutex_lock` | 5.97 | − | — |
| `__memmove_evex_unaligned_erms` | 5.71 | 11.98 | +6.27 |
| `repl_log_insert` | 5.64 | 6.78 | +1.14 |
| `heap_get_class_name_alloc_if_diff` | 5.44 | 6.99 | +1.55 |
| `spage_insert_data` | 5.39 | 11.57 | +6.18 |
| `lf_freelist_claim` | 5.14 | 4.18 | −0.96 |
| `log_zip` | 4.71 | 4.67 | −0.04 |
| `__pthread_mutex_unlock_usercnt` | 3.74 | 0.34 | −3.40 |
| `LZ4_resetStream_fast` | 3.66 | 3.35 | −0.31 |
| `pgbuf_unfix` | 3.51 | 5.78 | +2.27 |
| `__memset_evex_unaligned_erms` | 3.40 | 3.04 | −0.36 |
| `lf_freelist_alloc_block` | 3.09 | 2.08 | −1.01 |
| `thread_suspend_timeout_wakeup_and_unlock_entry` | 3.00 | − | — |
| `file_perm_alloc` | 2.99 | 3.08 | +0.09 |
| `log_sysop_commit_internal` | 2.83 | 2.13 | −0.70 |
| `heap_vpid_init_new` | 2.77 | 2.04 | −0.73 |
| `pthread_cond_timedwait` | 2.61 | − | — |
| `locator_check_foreign_key` | 2.09 | 2.75 | +0.66 |
| `log_append_sysop_end` | 2.00 | 1.18 | −0.82 |
| `heap_stats_add_bestspace` | 1.92 | 1.44 | −0.48 |
| `log_sysop_end_logical_undo` | 1.77 | 1.33 | −0.44 |
| `log_append_undoredo_data2` | 1.66 | 1.69 | +0.03 |
| `heap_attrinfo_read_dbvalues` | 1.58 | 2.31 | +0.73 |
| `heap_attrinfo_start_with_index` | 1.57 | 2.26 | +0.69 |
| `__lll_unlock_wake` | 1.55 | − | — |
| `spage_max_space_for_new_record` | 1.53 | 1.55 | +0.02 |
| `lf_hash_find` | 1.52 | 1.13 | −0.39 |
| `spage_has_enough_total_space` | 1.49 | 1.75 | +0.26 |
| `heap_attrinfo_end` | 1.37 | 1.57 | +0.20 |
| `lf_stack_pop` | 1.23 | 1.18 | −0.05 |
| `spage_find_empty_slot_at` | 1.12 | 1.63 | +0.51 |
| `log_sysop_commit` | 1.08 | 0.81 | −0.27 |
| `prior_lsa_alloc_and_copy_data` | 1.08 | 0.36 | −0.72 |
| `sysmalloc` | 1.03 | − | — |
| `heap_scancache_end` | 0.99 | 1.11 | +0.12 |
| `heap_get_class_record` | 0.99 | 1.42 | +0.43 |
| `heap_scancache_quick_end` | 0.98 | 1.09 | +0.11 |
| `spage_check_space` | 0.94 | 1.18 | +0.24 |
| `__mprotect` | 0.93 | − | — |
| `mht_get` | 0.93 | 0.75 | −0.18 |
| `spage_insert` | 0.92 | 0.88 | −0.04 |
| `repl_log_info_alloc` | 0.86 | 0.63 | −0.23 |
| `lock_alloc_resource` | 0.83 | 0.55 | −0.28 |
| `spage_find_empty_slot` | 0.80 | 0.75 | −0.05 |
| `pgbuf_get_victim` | 0.79 | − | — |
| `lf_list_find` | 0.77 | 0.44 | −0.33 |
| `prior_lsa_copy_redo_data_to_node` | 0.76 | 0.75 | −0.01 |
| `pgbuf_unlatch_void_zone_bcb` | 0.75 | 0.57 | −0.18 |
| `mht_get2` | 0.75 | 0.84 | +0.09 |
| `malloc_consolidate` | 0.68 | − | — |
| `log_does_allow_replication` | 0.67 | 0.47 | −0.20 |
| `lock_insert_into_tran_hold_list` | 0.64 | − | — |
| `heap_attrvalue_get_key` | 0.62 | 1.02 | +0.40 |
| `heap_get_class_tde_algorithm` | 0.61 | 0.67 | +0.06 |
| `realloc` | 0.60 | − | — |
| `mremap_chunk` | 0.58 | − | — |
| `__GI___mremap` | 0.56 | − | — |
| `or_packed_value_size` | 0.55 | 0.98 | +0.43 |
| `heap_scancache_quick_start_root_hfid` | 0.53 | 0.62 | +0.09 |
| `heap_page_update_chain_after_mvcc_op` | 0.52 | 0.55 | +0.03 |
| `heap_classrepr_free` | 0.48 | 0.35 | −0.13 |
| `btree_insert` | 0.44 | 0.49 | +0.05 |
| `or_pack_mem_value` | 0.42 | 0.70 | +0.28 |
| `log_sysop_start_atomic` | 0.42 | 0.35 | −0.07 |
| `pgbuf_get_victim_from_lru_list` | 0.40 | − | — |
| `heap_get_last_version` | 0.39 | 0.48 | +0.09 |
| `heap_classrepr_get` | 0.38 | 0.50 | +0.12 |
| `lock_get_class_lock` | 0.34 | 0.48 | +0.14 |
| `heap_page_get_vacuum_status@plt` | 0.32 | − | — |

## 주의

- tuned 트리의 0.3% 컷오프 때문에 `malloc` / `_int_malloc` / `__pthread_mutex_lock` / `pthread_cond_timedwait` 같은 함수는 트리에 안 잡혀서 `-` 로 처리됐습니다. **완전히 사라졌다는 의미가 아니라 컷오프 아래로 분산됐을 수도 있습니다.**
- v2 측 % 는 `REPORT.md` 섹션 3 표(같은 stack 안 같은 함수는 한 번만 카운트한 dedup 값)를 그대로 가져온 값이고, tuned 측 % 는 섹션 2 트리에 나온 inclusive % 를 함수별로 단순 합산한 값입니다. 동일 stack 내 중복이 있을 경우 tuned 값은 약간 과대평가될 수 있습니다.
- 두 캡처의 lif 자체 비중 (전체 on-CPU 중) — v2: 5.13%, tuned: 5.78% — 은 다르지만, 위 표는 두 trees 모두 lif=100% 로 정규화한 값이므로 함수별 비율 비교는 그대로 유효합니다.
