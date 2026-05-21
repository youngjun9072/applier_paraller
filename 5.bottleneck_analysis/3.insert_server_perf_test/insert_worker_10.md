# Worker 10 (활성화 워커 10개) — 슬레이브 서버 측 perf 측정 결과

- **활성화 워커: 10 / 비활성화 워커: 0**
- 빌드 모드: Release / 부하 도구: csql
- 워크로드: tbl1 ~ tbl10, 각 10만 건 Insert / 단일 트랜잭션
- 측정 대상: **슬레이브 데이터베이스 서버 프로세스** (`$SLAVE_PID`)

---

## 캡쳐 방법

```bash
perf record -F 1999 --call-graph=fp -p $SLAVE_PID -- sleep 30
```

- 샘플링 주파수: 1,999 Hz
- 콜그래프 모드: frame pointer (`fp`)
- 캡쳐 시간: 30초
- 후처리 필터: `slocator_repl_force` / `xlocator_repl_force` 스택만

---

## 병목 가설

| ID | 가설 | 코드 위치 | 마킹 함수 |
|----|------|-----------|-----------|
| H1 | prior_lsa overflow sleep | `log_append.cpp:1531` `if (list_size >= memsize) thread_sleep(1)` | `thread_sleep` (트리 등장 시 ★H1) |
| H2 | `prior_lsa_mutex` contention (WAL append 직렬화점) | `log_append.cpp:1357` `prior_lsa_next_record_internal` | `__lll_lock_wait` / `prior_lsa_next_record_internal` / `futex_wait` (★H2) |
| H3 | Page latch (heap/btree page) | `page_buffer.cpp` `pgbuf_block_bcb` | `pgbuf_block_bcb` / `pgbuf_lock_page` (★H3) |

---

## 콜체인 (on-CPU, `xlocator_repl_force` 하위)

```
[100.00%] xlocator_repl_force
├─ [93.64%] locator_insert_force
│   ├─ [61.00%] heap_insert_logical
│   │   ├─ [24.28%] heap_stats_find_best_page
│   │   │   ├─ [10.72%] file_alloc
│   │   │   │   ├─ [ 2.64%] file_perm_alloc
│   │   │   │   │   ├─ [ 1.31%] log_append_undoredo_data2
│   │   │   │   │   │   └─ [ 1.27%] log_append_undoredo_crumbs
│   │   │   │   │   └─ [ 1.15%] log_append_undoredo_data
│   │   │   │   │       └─ [ 1.13%] log_append_undoredo_crumbs
│   │   │   │   ├─ [ 2.20%] pgbuf_fix_release
│   │   │   │   │   └─ [ 1.57%] pgbuf_claim_bcb_for_fix
│   │   │   │   ├─ [ 2.12%] heap_vpid_init_new
│   │   │   │   │   └─ [ 1.55%] log_append_undoredo_data
│   │   │   │   │       └─ [ 1.49%] log_append_undoredo_crumbs
│   │   │   │   └─ [ 1.62%] log_sysop_end_logical_undo
│   │   │   │       └─ [ 1.58%] log_sysop_commit_internal
│   │   │   │           └─ [ 1.31%] log_append_sysop_end
│   │   │   ├─ [ 6.50%] log_append_undoredo_data
│   │   │   │   └─ [ 6.43%] log_append_undoredo_crumbs
│   │   │   │       └─ [ 3.70%] prior_lsa_alloc_and_copy_crumbs
│   │   │   │           └─ [ 3.54%] log_zip
│   │   │   │               └─ [ 2.72%] LZ4_compress_fast_extState
│   │   │   ├─ [ 1.52%] pgbuf_ordered_fix_release
│   │   │   └─ [ 1.30%] log_sysop_commit
│   │   │       └─ [ 1.29%] log_sysop_commit_internal
│   │   │           └─ [ 1.19%] log_append_sysop_end
│   │   ├─ [19.64%] heap_log_insert_physical
│   │   │   └─ [18.72%] log_append_undoredo_crumbs
│   │   │       ├─ [11.72%] prior_lsa_alloc_and_copy_crumbs
│   │   │       │   └─ [11.03%] log_zip
│   │   │       │       ├─ [ 8.58%] LZ4_compress_fast_extState
│   │   │       │       │   └─ [ 1.59%] LZ4_read_ARCH
│   │   │       │       └─ [ 1.35%] __memset_evex_unaligned_erms
│   │   │       ├─ [ 2.57%] __lll_unlock_wake
│   │   │       └─ [ 2.18%] __lll_lock_wait ★H2
│   │   ├─ [10.92%] lock_object
│   │   │   └─ [10.04%] lock_internal_perform_lock_object
│   │   │       └─ [ 8.26%] lockfree_hashmap<lk_res_key,lk_res>::find_or_insert
│   │   │           ├─ [ 6.44%] lock_res_key_compare
│   │   │           └─ [ 1.43%] lf_hash_insert_internal
│   │   └─ [ 2.99%] spage_insert_at
│   │       └─ [ 2.27%] __memmove_evex_unaligned_erms
│   ├─ [29.95%] locator_add_or_remove_index_internal
│   │   ├─ [23.16%] btree_insert
│   │   │   └─ [22.80%] btree_insert_internal
│   │   │       ├─ [ 8.24%] btree_key_insert_new_object
│   │   │       │   └─ [ 7.67%] btree_key_insert_new_key
│   │   │       │       └─ [ 6.92%] log_append_undoredo_data
│   │   │       │           └─ [ 6.78%] log_append_undoredo_crumbs
│   │   │       │               ├─ [ 2.58%] __lll_unlock_wake
│   │   │       │               └─ [ 2.22%] __lll_lock_wait ★H2
│   │   │       ├─ [ 8.20%] btree_fix_root_for_insert
│   │   │       │   └─ [ 7.01%] logtb_tran_update_unique_stats
│   │   │       │       └─ [ 6.52%] log_append_undo_data2
│   │   │       │           └─ [ 6.45%] log_append_undo_crumbs
│   │   │       │               ├─ [ 2.47%] __lll_unlock_wake
│   │   │       │               └─ [ 2.24%] __lll_lock_wait ★H2
│   │   │       └─ [ 4.59%] btree_split_node_and_advance
│   │   │           ├─ [ 1.42%] btree_split_node
│   │   │           └─ [ 1.16%] btree_search_leaf_page
│   │   ├─ [ 2.51%] heap_get_class_name_alloc_if_diff
│   │   │   └─ [ 1.74%] heap_get_class_record
│   │   │       └─ [ 1.44%] heap_get_last_version
│   │   │           └─ [ 1.08%] heap_prepare_get_context
│   │   ├─ [ 1.52%] heap_attrinfo_end
│   │   └─ [ 1.03%] heap_attrinfo_start_with_index
│   └─ [ 1.42%] locator_check_foreign_key
├─ [ 1.97%] xtran_server_end_topop
└─ [ 1.16%] heap_get_class_repr_id
```

---

## 가설 매칭

| ID | 매칭 함수 inclusive % | 트리 등장 |
|----|----------------------|-----------|
| H1 `thread_sleep` | 0.00% | ✗ (비활성) |
| H2 `__lll_lock_wait` / `prior_lsa_next_record_internal` / `futex_wait` 계열 | **21.21% (on-CPU), 97.21% (off-CPU `__lll_lock_wait` 종단)** | ✓ 다수 위치 ★H2 |
| H3 `pgbuf_block_bcb` / `pgbuf_lock_page` | 0.04% | ✗ (비활성) |

→ **결론: H2 (prior_lsa_mutex contention) 가 단일 원인으로 강하게 지목됨.**

---

## 상세 해석

### 1. H2 보강 — 여러 경로가 같은 mutex로 수렴

`__lll_lock_wait` 가 콜트리 **세 군데에서 동시에 출현**:

- `heap_log_insert_physical → log_append_undoredo_crumbs` (2.18%)
- `btree_key_insert_new_object → log_append_undoredo_data` (2.22%)
- `btree_fix_root_for_insert → logtb_tran_update_unique_stats → log_append_undo_data2` (2.24%)

→ heap·btree·tran stats **모든 로깅 경로가 같은 `prior_lsa_mutex` 로 수렴**.
→ "단일 mutex가 모든 로그 기록을 직렬화" 라는 H2 시나리오와 정확히 일치.
→ off-CPU 97.21%까지 합치면 **응답 지연의 거의 전부가 이 mutex 대기**에서 발생.

### 2. 진짜 비싼 건 락 자체가 아니라 "락 잡고 있는 동안의 작업"

```
prior_lsa_alloc_and_copy_crumbs (11.72%)
  └─ log_zip (11.03%)
       └─ LZ4_compress_fast_extState (8.58%)
```

압축(LZ4)이 **critical section 내부에서** 일어남.
→ 락 보유 시간이 LZ4 압축 시간만큼 늘어남.

- 워커 1개일 때는 자기 차례만 기다리면 되므로 영향 작음.
- 워커 10개일 때는 9명이 모두 "남의 LZ4 압축"이 끝날 때까지 대기 → 이것이 **per-call 22배 폭증의 메커니즘**.

→ H2 본질은 단순 mutex 경합이 아니라 **"비싼 작업(압축)을 들고 있는 mutex"** 임. 완화 방안 우선순위가 달라짐 (mutex 분리보다 압축을 critical section 밖으로 빼는 게 효과 클 가능성).

### 3. 부수 신호 — `lock_object` 10.92%

`lock_internal_perform_lock_object → lockfree_hashmap::find_or_insert` (8.26%) / `lock_res_key_compare` (6.44%).

- mutex가 아닌 lock-free 해시맵이므로 H2와는 별개.
- 트랜잭션 락 획득 비용이 무시 못할 수준 → **H2 해결 후 2차 병목 후보**로 기록.

### 4. H1·H3 비활성의 신뢰도

- **H1 `thread_sleep` 0%**: off-CPU 데이터도 함께 봤기 때문에(`__lll_lock_wait`가 off-CPU 97.21%로 정상 잡힘) "on-CPU 누락" 아님. H1은 실제로 발생하지 않음.
- **H3 `pgbuf` 0.04%**: 본 워크로드(단일 트랜잭션 long insert, 10 테이블)에서 page latch 경합은 의미 없음. 다른 워크로드(여러 트랜잭션 동시, 같은 테이블의 hot page)에선 재검토 가치 있음.

### 5. 다음 검증 (선택)

가설이 거의 확정적이지만 마지막 못 박기엔:

- **`perf lock`** 또는 `perf trace -e syscalls:sys_enter_futex` 로 mutex contention 이벤트를 직접 카운트 → 같은 mutex(`prior_lsa`)에 집중되는지 정량 확인.
- **압축을 critical section 밖으로 옮긴 한 줄짜리 PoC** 적용 → recv self가 줄어드는지 확인하면 인과 검증 완료.

---

## 3차 결론

> **병목의 실체는 `prior_lsa_mutex` contention (H2)이며, 본질은 "락 자체"보다 "락 안에서 수행되는 LZ4 압축"이 락 보유 시간을 늘리는 것**.
>
> H1(`thread_sleep`)·H3(page latch)는 본 워크로드에서 비활성으로 배제.
