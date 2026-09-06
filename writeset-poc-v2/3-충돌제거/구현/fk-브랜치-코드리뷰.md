---
tags: [writeset, v2, FK, branch-diff, 코드리뷰]
date: 2026-08-24
status: in-progress
---

# writeset v2 FK 브랜치 변경분 코드리뷰

> [!summary] 리뷰 범위
> `feature/parallel_applylogdb_writeset_poc`을 기준으로 `feature/parallel_applylogdb_writeset_poc_fk`에서 바뀐 코드를 호출부부터 commit history까지 흐름 순서로 리뷰한다.
>
> 라인 번호는 문서 작성 시점의 `feature/parallel_applylogdb_writeset_poc_fk` 기준이다. 코드가 바뀌면 라인은 이동할 수 있으므로 파일명과 함수명을 함께 사용한다.

## 1. 브랜치 비교 기준

### 1.1 현재 tip 간 직접 차이

```text
base:
  feature/parallel_applylogdb_writeset_poc
  2b11ac12f

target:
  feature/parallel_applylogdb_writeset_poc_fk
  d1f87c393

직접 diff:
  src/transaction/locator_sr.c
  src/transaction/log_impl.h
  src/transaction/log_writeset.c
  src/transaction/log_writeset.h

  4 files, +513 / -29
```

`log_applier.c`의 committed LSA/frontier 보정과 `replication.c`의 SBR/DDL commit-order 격하는 양쪽 브랜치에 모두 있다. 따라서 현재 tip 기준 FK 브랜치 고유 변경분은 아니다.

### 1.2 변경 흐름

```text
INSERT / DELETE
  → locator_add_or_remove_index_internal()
      → FK index 발견
      → locator_writeset_collect_fk_ref()

UPDATE
  → locator_update_index()
      → old FK REF 수집
      → FK가 바뀌면 new FK REF도 수집

locator_writeset_collect_fk_ref()
  → child FK DB_VALUE 추출
  → parent PK domain 조회
  → log_writeset_add_ref_dbvalue()

log_writeset_add_ref_dbvalue()
  → child FK를 parent PK domain으로 cast
  → H(parent class OID, packed parent-key)
  → LOG_WRITESET_KIND_REF로 트랜잭션에 저장

COMMIT
  → log_writeset_commit_probe()
      WRITE와 REF 모두 history 조회

  → log_writeset_commit_flush()
      WRITE만 history에 게시
      REF는 게시하지 않음
```

---

## 2. 변경 블록 1 — writeset 엔트리에 `WRITE` / `REF` 구분 추가

### 2.1 기준 브랜치

```cpp
/*
 * 파일: src/transaction/log_impl.h
 * 구조체: LOG_TDES
 * 기준 브랜치 라인: 544 부근
 */

std::vector<LOG_WRITESET_HASH> ws_hashes;
bool ws_overflow;
LOG_LSA ws_dependency_seq;
```

기존 writeset은 해시 값만 저장했다. 해당 키를 트랜잭션이 직접 써서 변경했는지, FK로 참조만 했는지는 표현할 수 없었다.

### 2.2 FK 브랜치

**파일**: `src/transaction/log_impl.h`  
**구조체**: `LOG_WRITESET_KIND`, `LOG_WRITESET_ENTRY`  
**라인**: 478–498

```cpp
typedef UINT64 LOG_WRITESET_HASH;

typedef enum
{
  LOG_WRITESET_KIND_WRITE = 0,
  LOG_WRITESET_KIND_REF = 1
} LOG_WRITESET_KIND;

typedef struct log_writeset_entry LOG_WRITESET_ENTRY;
struct log_writeset_entry
{
  LOG_WRITESET_HASH hash;
  LOG_WRITESET_KIND kind;
};
```

**파일**: `src/transaction/log_impl.h`  
**구조체**: `LOG_TDES`  
**라인**: 560–566

```cpp
/* writeset PoC: per-transaction writeset-key hashes (tdes-lifetime). */
std::vector<LOG_WRITESET_ENTRY> ws_hashes;
bool ws_overflow;
LOG_LSA ws_dependency_seq;
```

변경 후 트랜잭션 엔트리는 다음 두 의미를 표현한다.

```text
WRITE:
  이 트랜잭션이 해당 키의 owner row를 쓰거나 삭제함
  예: parent PK, row PK, UNIQUE key

REF:
  이 트랜잭션이 child FK로 parent key를 가리킴
```

### 2.3 메모리 크기 검토

기준 브랜치의 엔트리는 `UINT64` 하나였다.

```text
기존:
  LOG_WRITESET_HASH = 8 bytes

변경:
  hash = 8 bytes
  kind = 일반적으로 4 bytes
  alignment padding 포함 시 entry = 일반적으로 16 bytes
```

FK가 없는 트랜잭션도 `ws_hashes` element type이 바뀌므로 transaction-local vector 메모리가 증가한다. `LOG_WRITESET_TX_LIMIT`는 element 개수 기준으로 유지되므로 대형 트랜잭션 메모리 측정이 필요하다.

---

## 3. 변경 블록 2 — INSERT / DELETE의 FK REF 수집 호출부

### 3.1 공용 index loop에서 FK index를 발견한다

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_add_or_remove_index_internal()`  
**라인**: 8035–8056

```cpp
/* UNIQUE/REVERSE_UNIQUE는 기존 WRITE 해시를 수집한다. */
if (datayn
    && need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && (index->type == BTREE_UNIQUE
        || index->type == BTREE_REVERSE_UNIQUE))
  {
    LOG_TDES *ws_tdes =
      LOG_FIND_TDES (LOG_FIND_THREAD_TRAN_INDEX (thread_p));

    (void) log_writeset_add_dbvalue (
      thread_p, ws_tdes, class_oid, key_dbvalue);
  }

/* FK index는 parent key 모양의 REF 해시를 수집한다. */
if (datayn
    && need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && index->type == BTREE_FOREIGN_KEY)
  {
    locator_writeset_collect_fk_ref (
      thread_p,
      index,
      i,
      &index_attrinfo,
      recdes,
      inst_oid);
  }
```

이 함수는 INSERT와 DELETE의 index 처리를 공유한다.

```text
INSERT:
  is_insert = true
  recdes = new row image
  → new FK 값 수집

DELETE:
  is_insert = false
  recdes = old row image
  → old FK 값 수집
```

`!LOG_CHECK_LOG_APPLIER(thread_p)` 조건으로 master의 RBR 생성 경로에서만 수집한다. slave가 replication row를 같은 locator 계층으로 적용할 때는 writeset을 다시 수집하지 않는다.

### 3.2 수집 시점

FK REF는 실제 B-tree 변경보다 먼저 수집된다.

```text
index key 추출
  → writeset REF 수집
  → btree_insert() 또는 btree_delete()
```

뒤의 index/FK 검사가 실패하면 transaction abort 정리 경로가 `ws_hashes`를 비우는 기존 계약에 의존한다.

---

## 4. 변경 블록 3 — UPDATE의 old/new FK REF 수집

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_update_index()`  
**라인**: 8722–8749

```cpp
/* UNIQUE key는 old를 수집하고, 값이 바뀌면 new도 수집한다. */
if (repl_info != NULL
    && repl_info->need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && (index->type == BTREE_UNIQUE
        || index->type == BTREE_REVERSE_UNIQUE))
  {
    LOG_TDES *ws_tdes =
      LOG_FIND_TDES (LOG_FIND_THREAD_TRAN_INDEX (thread_p));

    (void) log_writeset_add_dbvalue (
      thread_p, ws_tdes, class_oid, old_key);

    if (!same_key)
      {
        (void) log_writeset_add_dbvalue (
          thread_p, ws_tdes, class_oid, new_key);
      }
  }

/* FK도 old parent를 수집하고, 값이 바뀌면 new parent도 수집한다. */
if (repl_info != NULL
    && repl_info->need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && index->type == BTREE_FOREIGN_KEY)
  {
    locator_writeset_collect_fk_ref (
      thread_p, index, i, old_attrinfo, old_recdes, oid);

    if (!same_key)
      {
        locator_writeset_collect_fk_ref (
          thread_p, index, i, new_attrinfo, new_recdes, oid);
      }
  }
```

두 경우를 구분하면 다음과 같다.

```text
UPDATE child SET v = v + 1 WHERE id = 10   (FK 컬럼 parent_id를 건드리지 않음)
  old FK == new FK
  → old REF만 수집

UPDATE child SET parent_id = 2 WHERE id = 10
  old FK = 1
  new FK = 2
  → REF(parent=1), REF(parent=2) 모두 수집
```

첫 예제처럼 SQL이 `parent_id`를 바꾸지 않아도 old FK REF를 항상 한 번 수집한다. 이유: UPDATE된 child row가 여전히 그 parent를 참조하므로, 그 parent의 선행 WRITE 뒤로 이 트랜잭션을 순서 지어야 정합성이 유지되기 때문이다. 즉 REF(old)는 "FK 값이 바뀌었는가"와 무관하게 "이 row가 참조하는 parent"를 표현한다. FK 값이 실제로 바뀌면 new parent에도 순서를 걸어야 하므로 REF(new)를 추가로 수집한다.

---

## 5. 변경 블록 4 — child FK 값을 parent key 해시 입력으로 변환

### 5.1 parent 메타데이터와 child FK key 추출

`locator_writeset_collect_fk_ref()`는 이 FK 브랜치에서 **새로 추가된 함수**다. 위 §3(INSERT/DELETE)·§4(UPDATE) 호출부가 FK index를 만날 때 이 함수를 호출한다(호출 흐름은 §1.2 참조).

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_writeset_collect_fk_ref()` (신규)  
**라인**: 7792–7844

```cpp
static void
locator_writeset_collect_fk_ref (
  THREAD_ENTRY *thread_p,
  OR_INDEX *index,
  int btid_index,
  HEAP_CACHE_ATTRINFO *attrinfo,
  RECDES *recdes,
  OID *inst_oid)
{
  LOG_TDES *tdes;
  TP_DOMAIN *parent_pk_domain;
  DB_VALUE *fk_key;
  DB_VALUE dbvalue;
  BTID fk_btid;
  char buf[DBVAL_BUFSIZE + MAX_ALIGNMENT];
  char *aligned_buf;

  if (index == NULL
      || index->type != BTREE_FOREIGN_KEY
      || index->fk == NULL)
    {
      return;
    }

  tdes = LOG_FIND_TDES (
    LOG_FIND_THREAD_TRAN_INDEX (thread_p));

  if (tdes == NULL || tdes->ws_overflow)
    {
      return;
    }

  parent_pk_domain = btree_read_key_type (
    thread_p,
    &index->fk->ref_class_pk_btid);

  if (parent_pk_domain == NULL)
    {
      return;
    }

  db_make_null (&dbvalue);
  aligned_buf = PTR_ALIGN (buf, MAX_ALIGNMENT);

  fk_key = heap_attrvalue_get_key (
    thread_p,
    btid_index,
    attrinfo,
    recdes,
    &fk_btid,
    &dbvalue,
    aligned_buf,
    NULL,
    NULL,
    inst_oid,
    true);

  if (fk_key == NULL)
    {
      return;
    }

  (void) log_writeset_add_ref_dbvalue (
    thread_p,
    tdes,
    &index->fk->ref_class_oid,
    fk_key,
    parent_pk_domain);

  if (fk_key == &dbvalue)
    {
      pr_clear_value (&dbvalue);
    }
}
```

핵심 입력은 다음 두 개다.

```text
ref_class_oid:
  child class가 아니라 parent class OID

parent_pk_domain:
  child FK column domain이 아니라 parent PK B-tree key domain
```

따라서 다음 해시 동치를 목표로 한다.

```text
parent WRITE:
  H(parent class OID, parent PK domain으로 packed된 1)

child REF:
  child FK 1
    → parent PK domain으로 cast
    → H(parent class OID, parent PK domain으로 packed된 1)
```

---

## 6. 변경 블록 5 — REF packing과 commit 시점 dependency 확정

§3~§5는 locator_sr.c 쪽(REF 수집)이었다. 여기부터는 log_writeset.c / log_manager.c 쪽으로, REF를 parent 해시로 packing하고 commit 시점에 dependency를 확정·기록하는 변경이다.

### 6.1 REF를 parent PK domain으로 cast하여 packed byte 동치 보장

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_add_ref_dbvalue()`  
**라인**: 334–377

```cpp
cast_status = tp_value_cast (fk_value, &casted, parent_pk_domain, false);
if (cast_status != DOMAIN_COMPATIBLE)
  {
    ...
    return NO_ERROR;   /* 실패 시 이 REF는 누락(보수적 경로) */
  }

buf_len = OR_VALUE_ALIGNED_SIZE (&casted);
buf = (char *) malloc ((size_t) buf_len);
memset (buf, 0, (size_t) buf_len);
ptr = or_pack_mem_value (buf, &casted, &packed_len);

error = log_writeset_push (thread_p, tdes, ref_class_oid, buf, packed_len,
                           LOG_WRITESET_KIND_REF);
```

목표 불변식은 parent WRITE 해시와 child REF 해시가 같은 바이트가 되는 것이다.

```text
H(parent class OID, pack(parent.id       in parent domain))
==
H(parent class OID, pack(child.parent_id cast to parent domain))
```

### 6.2 debug 자가검증 (`pthread_once`)

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_add_ref_dbvalue()`  
**라인**: 300–310

```cpp
#if !defined (NDEBUG)
  {
    static pthread_once_t selfcheck_once = PTHREAD_ONCE_INIT;
    pthread_once (&selfcheck_once, log_writeset_selfcheck_packing);
  }
#endif
```

여러 server thread가 동시에 첫 FK DML을 실행해도 pack 동치 자가검증은 프로세스 생명주기에서 한 번만 실행된다. release(`NDEBUG`) 빌드에는 들어가지 않아 benchmark timing과 무관하다.

### 6.3 commit 직전 history probe — `dependency_seq = min(prev_commit, ws_parent)`

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_commit_probe()`  
**라인**: 419–444

```cpp
LSA_COPY (&ws_parent, &log_Writeset_history.history_start);
for (const LOG_WRITESET_ENTRY &e : tdes->ws_hashes)
  {
    auto it = log_Writeset_history.map.find (e.hash);
    if (it != log_Writeset_history.map.end () && LSA_GT (&it->second, &ws_parent))
      LSA_COPY (&ws_parent, &it->second);
  }
/* dependency_seq = min(prev_commit_lsa, ws_parent) */
if (LSA_ISNULL (&log_Writeset_prev_commit_lsa) || LSA_LT (&ws_parent, &log_Writeset_prev_commit_lsa))
  LSA_COPY (ws_parent_out, &ws_parent);
else
  LSA_COPY (ws_parent_out, &log_Writeset_prev_commit_lsa);
```

WRITE와 REF 모두 같은 history map을 조회한다. 한 트랜잭션이 여러 부모를 참조하면 매칭 중 가장 최신 LSA를 골라 트랜잭션에는 최종 dependency 하나가 붙는다(행 단위 수집 → 트랜잭션 단위 dependency).

### 6.4 WRITE만 history에 게시 — 형제 직렬화 회피 ★

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_commit_flush()`  
**라인**: 487–524

```cpp
/* WRITE만 현재 commit LSA의 소유자로 history에 게시한다. REF는 게시하지 않는다. */
for (const LOG_WRITESET_ENTRY &e : tdes->ws_hashes)
  {
    if (e.kind == LOG_WRITESET_KIND_WRITE)
      log_Writeset_history.map[e.hash] = *commit_lsa;
  }
```

REF를 게시하지 않는 것이 **형제 병렬의 핵심**이다.

```text
parent P WRITE → history[H(P)] = P.commit
child C1 REF(P): probe만, publish 안 함 → C1.dep = P.commit
child C2 REF(P): history[H(P)] 여전히 P.commit → C2.dep = P.commit
결과: C1, C2는 부모가 끝난 뒤 서로 병렬 가능
```

만약 C1의 REF까지 게시했다면 C2가 C1을 보게 되어 `P → C1 → C2 → …` 불필요한 사슬이 생긴다. (MySQL은 이와 달리 복제본 FK 처리에서 같은 부모 자식들을 직렬화한다 — [[2. writeset_MySQL_FK_병렬화_실측_2026-08-26]] 6.3절.)

### 6.5 dependency label을 COMMIT 바로 앞에 기록

**파일**: `src/transaction/log_manager.c`  
**함수**: `log_append_ws_label_with_lock()` / `log_append_repl_info_and_commit_log()`  
**라인**: 4665–4696

```cpp
log_append_ws_label_with_lock (thread_p, tdes);      /* LOG_DUMMY_WS_LABEL(dependency_seq) */
log_append_commit_log_with_lock (thread_p, tdes, commit_lsa);
log_Gl.prior_info.prior_lsa_mutex.unlock ();
```

label과 commit을 같은 `prior_lsa_mutex` 구간에서 연달아 기록하므로 복제 로그 모양은 항상 다음이다.

```text
... replication data records ...
LOG_DUMMY_WS_LABEL(dependency_seq)
LOG_COMMIT(same trid)
```

---

## 7. 변경 블록 6 — slave가 dependency를 읽고 gate로 실행

### 7.1 WS label을 읽고 다음 COMMIT에 붙인다

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_log_record_process()`  
**라인**: 10206–10213

```cpp
case LOG_DUMMY_WS_LABEL:
  la_retrieve_ws_label (
    pg_ptr,
    final,
    &la_ws_label_dependency_seq);

  la_ws_label_trid = lrec->trid;
  break;
```

바로 뒤의 같은 `trid` COMMIT에서 task로 옮긴다.

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_log_record_process()`  
**라인**: 10088–10107

```cpp
task.tranid = lrec->trid;
task.rectype = lrec->type;
LSA_COPY (&task.commit_lsa, final);
task.apply = la_find_apply_list (lrec->trid);

if (la_ws_label_trid == lrec->trid)
  {
    LSA_COPY (
      &task.dependency_seq,
      &la_ws_label_dependency_seq);

    la_ws_label_trid = NULL_TRANID;
  }
else
  {
    LSA_SET_NULL (&task.dependency_seq);
  }
```

여기서 중요한 사실은 **COMMIT record를 읽은 시점에야 task가 만들어진다**는 것이다.

### 7.2 dependency가 만족되면 dispatch, 아니면 PARK

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_log_record_process()`  
**라인**: 10123–10145

```cpp
if (la_gate_is_satisfied (&task.dependency_seq))
  {
    er_log_debug (..., "ws_reader DISPATCH ...");
    error = la_gate_dispatch_now (&task);
  }
else
  {
    error = la_gate_enqueue_pending (&task);
    er_log_debug (..., "ws_reader PARK ...");
  }
```

PARK는 reader thread 자체의 정지가 아니다.

```text
자식 C가 부모 P를 기다림
  → C task만 pending queue에 저장
  → reader는 다음 log record를 계속 읽음
  → 뒤에서 만나는 독립 트랜잭션 X는 별도로 dispatch 가능
```

### 7.3 정확한 부모 한 건의 완료만으로도 풀린다

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_gate_is_satisfied()`  
**라인**: 1682–1692

```cpp
if (LSA_ISNULL (dep))
  {
    return true;                  // dependency 없음
  }

if (la_Gate_frontier_seeded
    && LSA_LE (dep, &la_Gate_frontier))
  {
    return true;                  // gap-free frontier 이하
  }

return la_gate_set_contains (dep); // exact dependency가 완료됐는지 확인
```

따라서 자식은 전역 `committed_lsa`가 자기 순번까지 도달할 때까지 기다릴 필요가 없다.

```text
전역 frontier가 아직 낮음
  + parent P가 out-of-order로 먼저 완료됨
  + completed_set에 P.commit_lsa가 있음

→ child.dep == P.commit_lsa
→ exact membership 검사 성공
→ 즉시 dispatch 가능
```

이 completed-set 경로가 없고 `dep <= frontier`만 검사했다면, 앞선 무관 트랜잭션의 느린 완료 때문에 자식이 불필요하게 끌려갈 수 있다.

### 7.4 worker START와 END가 의미하는 범위

현재 PoC는 release 빌드에서도 최소 timing 로그를 남긴다.

**파일**: `src/transaction/log_applier.c`  
**매크로**: `LA_BENCH_TIMING_LOG`  
**라인**: 111–119

```cpp
#if !defined (NDEBUG)
#define LA_DEBUG_LOG(...) er_log_debug (__VA_ARGS__)
#else
#define LA_DEBUG_LOG(...) ((void) 0)
#endif

/* release에서도 이 두 timing 로그는 남는다. */
#define LA_BENCH_TIMING_LOG(...) _er_log_debug (__VA_ARGS__)
```

worker 수는 현재 10개다.

**파일**: `src/transaction/log_applier.c`  
**라인**: 102–106

```cpp
#define LA_APPLY_WORKER_COUNT             10
#define LA_APPLY_WORKER_REPL_ACTIVE_COUNT 10
```

START는 worker가 task를 dequeue한 직후다.

**파일**: `src/transaction/log_applier.c`  
**worker main loop**  
**라인**: 3411–3418

```cpp
LA_BENCH_TIMING_LOG (
  ARG_FILE_LINE,
  "ws_apply START worker=%d trid=%d ... commit_lsa=%lld|%d dep=%lld|%d",
  ...);
```

START 뒤 실제 작업 순서는 다음과 같다.

**파일**: `src/transaction/log_applier.c`  
**worker main loop**  
**라인**: 3429–3489

```cpp
result.error = la_apply_repl_log (...);

if (result.error == NO_ERROR
    && task.rectype == LOG_COMMIT)
  {
    result.error = la_flush_repl_items (true, &result.stats);
  }

if (result.error == NO_ERROR
    && task.rectype == LOG_COMMIT)
  {
    result.error = la_commit_transaction (...);
  }
```

그 다음 END를 기록한다.

**파일**: `src/transaction/log_applier.c`  
**worker main loop**  
**라인**: 3514–3537

```cpp
LA_BENCH_TIMING_LOG (
  ARG_FILE_LINE,
  "ws_apply END worker=%d trid=%d ... elapsed_usec=%llu applied=%llu ...",
  ...);

la_enqueue_apply_result (worker, &result);
```

그러므로 `ws_apply END`의 의미는 다음과 같다.

```text
해당 transaction의 replication item 적용 완료
+ final flush 완료
+ slave DB transaction commit 완료
= ws_apply END
```

END 이후의 시간을 “그 부모를 DB에 flush하는 시간”이라고 해석하면 안 된다.

### 7.5 완료 결과를 exact completed set에 등록한다

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_collect_worker_results()`  
**라인**: 2508–2528

```cpp
entry->result = result;
entry->result_ready = true;

if (result.rectype == LOG_COMMIT)
  {
    la_gate_mark_completed (&result.commit_lsa);
  }

la_gate_advance_frontier ();
la_gate_drain_ready ();
```

즉 worker가 DB commit을 마치고 result를 넘기면 다음 reader/coordinator 순회에서:

```text
parent exact commit LSA를 completed_set에 등록
→ frontier 전진 시도
→ PARK된 task 중 dependency가 풀린 것을 dispatch
```

한다.

### 7.6 `committed_lsa`와 `committed_rep_lsa`의 역할

`la_Info.committed_lsa`는 gap-free frontier를 따라 단조 증가하며 재시작 안전선으로 영속화된다.

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_retire_ready_results()`  
**라인**: 2574–2600

```cpp
if (la_Gate_frontier_seeded
    && !LSA_ISNULL (&la_Gate_frontier)
    && LSA_GT (&la_Gate_frontier, &la_Info.committed_lsa))
  {
    LSA_COPY (
      &la_Info.committed_lsa,
      &la_Gate_frontier);
  }
```

`committed_rep_lsa`는 현재 correctness gate가 아니라 monitoring 정보다.

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_retire_ready_results()`  
**라인**: 2603–2610

```cpp
/* committed_rep_lsa is monitoring-only now. */
if (!LSA_ISNULL (&result->committed_rep_lsa)
    && LSA_GT (&result->committed_rep_lsa,
               &la_Info.committed_rep_lsa))
  {
    LSA_COPY (
      &la_Info.committed_rep_lsa,
      &result->committed_rep_lsa);
  }
```

정리하면 다음 표와 같다.

| 상태 | 의미 | 자식 dependency 즉시 해제에 사용되는가? |
|---|---|---:|
| `la_Gate_frontier` | 이 LSA 이하가 모두 완료된 gap-free 하한 | 예 |
| `la_Gate_completed_slots` | frontier 위에서 먼저 끝난 exact commit 집합 | 예 |
| `la_Info.committed_lsa` | 영속화할 gap-free 적용 위치 | 직접 gate 조건은 아님 |
| `la_Info.committed_rep_lsa` | 마지막 replication item 위치의 monitoring 값 | 아니오 |

---

---

## 8. 변경 블록 7 — SBR/DDL overflow 직렬화

RBR은 어떤 행의 어떤 key를 변경했는지 writeset으로 표현할 수 있다. 반면 DDL과 일반 statement replication은 row image가 없어서 hash만으로 영향 범위를 완전하게 표현할 수 없다.

**파일**: `src/transaction/replication.c`  
**함수**: `repl_log_insert_statement()`  
**라인**: 533–540

```cpp
/* Statement replication은 writeset hash로 영향을 표현할 수 없다.
 * commit order로 보수 격하한다. */
tdes->ws_overflow = true;
```

commit probe에서 overflow 트랜잭션은 직전 commit을 dependency로 사용한다.

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_commit_probe()`  
**라인**: 405–415

```cpp
if (tdes != NULL && tdes->ws_overflow)
  {
    LSA_COPY (ws_parent_out, &log_Writeset_prev_commit_lsa);
    ...
    return;
  }
```

따라서 측정용 `USE_SBR` INSERT를 workload와 같은 트랜잭션에 넣으면 실제 DML writeset을 무효화하고 commit-order 사슬을 만든다.

```text
잘못된 측정 트랜잭션

START SBR
INSERT 100,000 rows
END SBR
COMMIT

→ ws_overflow=true
→ 실제 PK/FK writeset 대신 직전 commit dependency
→ 여러 파일을 병렬 호출해도 slave에서 직렬화
```

현재 벤치마크는 SBR boundary를 workload 밖의 독립 트랜잭션으로 분리했다. 자세한 변경 배경은 [[writeset_SBR_벤치마크_직렬화와_측정방식_변경]]에 정리돼 있다.

---

---

## 9. 현재까지의 코드 리뷰 finding

### Finding 1 — [높음] 실패 시 보수 fallback 주석과 실제 동작이 다르다

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_writeset_collect_fk_ref()`  
**라인**: 7792–7838

주석은 실패한 경우 기존의 보수적 경로로 fallback한다고 설명한다.

```cpp
/*
 * Multi-column parent keys and NULL foreign keys are skipped.
 * Best effort: on any failure the row order falls back
 * to the conservative existing path.
 */
```

그러나 parent domain 조회나 FK key 추출이 실패하면 그냥 반환한다.

```cpp
parent_pk_domain = btree_read_key_type (...);
if (parent_pk_domain == NULL)
  {
    return;
  }

fk_key = heap_attrvalue_get_key (...);
if (fk_key == NULL)
  {
    return;
  }
```

이 경로는 `tdes->ws_overflow = true`를 설정하지 않고 기존 `ws_hashes`도 비우지 않는다.

```text
주석이 의미하는 안전 fallback:
  FK REF 생성 불가
  → ws_overflow = true
  → transaction 전체를 commit order로 격하

실제 동작:
  FK REF 생성 불가
  → 해당 REF만 누락
  → 나머지 writeset은 완전한 것처럼 commit
```

composite parent PK도 같은 문제가 있다. 후속 블록에서 `log_writeset_add_ref_dbvalue()`의 `DB_TYPE_MIDXKEY` 분기와 함께 최종 판정한다.

### Finding 2 — [중간] typed entry로 기존 non-FK writeset의 transaction-local 메모리도 증가한다

```cpp
/* 기준 브랜치 */
std::vector<LOG_WRITESET_HASH> ws_hashes;

/* FK 브랜치 */
std::vector<LOG_WRITESET_ENTRY> ws_hashes;
```

64-bit 빌드에서 `LOG_WRITESET_ENTRY` 크기가 16 bytes라면 element 크기가 8 bytes에서 16 bytes로 증가한다. FK가 없는 기존 workload도 영향을 받으므로 실제 빌드의 `sizeof(LOG_WRITESET_ENTRY)`와 대형 트랜잭션 메모리를 측정해야 한다.

---

## 10. 설계에서 반드시 다뤄야 할 잠재 문제 시나리오

이 절은 현재 코드가 모두 잘못되었다는 판정표가 아니라, writeset v2 설계가 명시적으로 허용하거나 차단해야 할 **사례 장부**다.

```text
[정적 확인]       현재 코드만으로 실행 경로 또는 표현 한계를 확인함
[동적 검증 필요]  실제 worker 순서·lock·오류 처리는 HA 통합 테스트가 필요함
[설계 결정 필요]  최종 수렴, 중간 상태 노출, 오류 로그 허용 범위를 계약으로 정해야 함
```

### S1 — 하나의 transaction이 서로 독립적인 여러 선행 writer를 참조

**상태**: 정적 확인 / 동적 검증 필요  
**영향 범위**: 기본 writeset PoC와 FK PoC 모두

```text
parent_a(id=1)          parent_b(id=7)
       ^                       ^
       | FK a_id               | FK b_id
       +-------- child --------+

T1: WRITE parent_a(1)                 commit LSA=100
T2: WRITE parent_b(7)                 commit LSA=200
T3: REF parent_a(1), REF parent_b(7)
```

T3이 실제로 필요로 하는 dependency는 집합이다.

```text
required(T3) = { T1, T2 }
```

현재 master의 commit probe는 두 history entry를 모두 조회하지만 단일 `ws_parent`에 가장 큰 LSA만 남긴다.

```cpp
// 개념화한 현재 동작
for (entry : T3.ws_hashes)
  {
    if (history contains entry.hash)
      {
        ws_parent = max (ws_parent, history[entry.hash]);
      }
  }

// 결과
T3.dependency_seq = T2;
```

이 압축은 `dependency_seq=T2`를 **누적 완료 watermark**, 즉 “T2 이하가 모두 완료됨”으로 소비하면 안전하다. 그러나 slave gate가 T2 하나의 out-of-order 완료 membership만으로 통과시키면 다음 실행이 가능하다.

```text
T1 START -------------------------------- END
T2 START -------- END
                   T3 START

T3 시작 시점:
  T2는 완료 집합에 있음
  T1은 아직 실행 중
```

따라서 설계는 다음 중 하나를 선택해야 한다.

```text
A. 단일 dependency label + gap-free frontier >= label
B. 정확한 dependency 집합 {T1, T2}
C. generation/join으로 집합을 압축

피해야 할 조합:
  단일 max label + exact completed-membership
```

> [!important]
> 여기서 문제는 여러 값 중 `min`을 택해서 생기는 것이 아니다. 여러 선행 관계를 `max LSA` 하나로 압축해 놓고, slave가 그것을 누적 watermark가 아니라 특정 transaction 하나로 해석하는 의미 불일치가 핵심이다.

### S2 — 먼저 실행된 child REF와 나중 parent WRITE의 역방향 관계가 history에 남지 않음

**상태**: 정적 확인 / action별 동적 검증 필요  
**상세 분석**: [[5. writeset_v2_한계_부모삭제_순서역전_가능성]]

```text
parent(id=1)
    ^
    | child.parent_id
child(id=10, parent_id=1)

master:
  T1 child DELETE     → REF(parent, 1)
  T2 parent DELETE    → WRITE(parent, 1)
```

현재 의도는 REF를 history에 publish하지 않아 같은 부모를 읽는 형제 child transaction의 병렬성을 유지하는 것이다.

```cpp
// 개념화한 commit flush
for (entry : ws_hashes)
  {
    if (entry.kind == LOG_WRITESET_KIND_WRITE)
      {
        history[entry.hash] = current_commit_lsa;
      }

    // REF는 probe하지만 history에는 게시하지 않음
  }
```

그 결과 T2가 history에서 T1을 발견할 수 없다.

```text
after T1 commit:
  history[parent-key=1]에는 T1 REF가 없음

T2 probe WRITE(parent-key=1):
  dependency로 T1을 찾지 못함

slave에서 가능한 순서:
  T2 parent DELETE → T1 child DELETE
```

설계에서 FK action별로 다음 계약을 결정해야 한다.

| FK action | 검토할 결과 |
|---|---|
| RESTRICT / NO ACTION | log applier의 FK 검사 생략 조건, transaction 사이 중간 orphan 노출 허용 여부 |
| CASCADE | parent DELETE가 child를 먼저 지운 뒤 명시적 child DELETE가 object-not-found가 되는 경로와 error/skip 정책 |
| SET NULL | parent DELETE가 child를 갱신한 뒤 과거 child DELETE/UPDATE가 적용되는 순서와 최종 수렴 |

### S3 — 같은 parent key를 참조하는 여러 active child transaction 뒤에 parent WRITE

**상태**: 설계 표현력 부족 확인 / 동적 검증 필요

```text
                 parent(id=1)
                  ^       ^
                  |       |
T4: child A REF(1)        |       오래 실행
T5: child B REF(1) --------       먼저 완료
T6: parent WRITE(1)
```

REF를 history에 단순히 마지막 LSA 하나로 게시하는 보완만으로도 충분하지 않다.

```text
active refs for parent(1) = { T4, T5 }

last_ref = T5 하나만 보관
T5 완료 membership 확인
T4 미완료
→ T6을 잘못 dispatch할 수 있음
```

필요한 표현은 `active_refs={T4,T5}`, REF generation/join, 또는 `frontier >= T5` 같은 보수적 barrier다. 단, frontier 방식은 T5 이전의 무관한 transaction까지 기다린다.

### S4 — composite FK/PK는 REF 생성 없이 성공 반환

**상태**: 정적 확인

```text
parent PRIMARY KEY (tenant_id, object_id)
child  FOREIGN KEY (tenant_id, object_id) REFERENCES parent
```

현재 `log_writeset_add_ref_dbvalue()`는 parent key domain이 `DB_TYPE_MIDXKEY`이면 REF를 만들지 않고 성공으로 반환한다.

```cpp
// 파일: src/transaction/log_writeset.c
// 함수: log_writeset_add_ref_dbvalue()
// 정확한 라인은 후속 호출 흐름 리뷰에서 갱신

if (TP_DOMAIN_TYPE (parent_pk_domain) == DB_TYPE_MIDXKEY)
  {
    return NO_ERROR;
  }
```

따라서 composite FK workload에서 다음을 결정해야 한다.

```text
1. 미지원으로 명시하고 transaction 전체를 commit-order fallback할지
2. MIDXKEY element별 parent-domain cast/packing을 구현할지
3. 조용히 REF만 생략하는 현재 동작을 허용할지
```

안전성 관점에서는 3번을 기본값으로 두면 안 된다. 지원하지 못한 관계를 정상적인 완전한 writeset처럼 표시하기 때문이다.

### S5 — parent domain 조회·child key 추출·cast/packing 실패 시 dependency 누락

**상태**: 정적 확인

```text
btree_read_key_type() 실패
heap_attrvalue_get_key() 실패
tp_value_cast() 실패
packing 실패
```

주석의 “conservative existing path로 fallback”과 달리 일부 경로는 단순 반환하며 `ws_overflow`를 설정하지 않는다.

```text
기대하는 안전 fallback:
  REF를 만들 수 없음
  → transaction의 writeset이 불완전함
  → ws_overflow=true
  → commit-order/barrier 적용

현재 위험 경로:
  REF를 만들 수 없음
  → 해당 REF만 누락
  → 나머지 writeset을 완전한 것으로 취급
```

NULL FK는 관계가 없으므로 의도적으로 생략할 수 있지만, 오류와 미지원 형식은 NULL과 구별해야 한다.

### S6 — parent/child domain은 FK 호환이지만 packed byte가 다를 수 있음

**상태**: 보정 코드 존재 / 타입 조합별 검증 필요

```text
parent.id        NUMERIC(10, 2) = 123.45
child.parent_id  NUMERIC(15, 4) = 123.4500
```

논리적으로 같은 값이어도 `DB_VALUE`가 가진 precision/scale과 packing 표현은 다를 수 있다. parent WRITE와 child REF가 같은 hash가 되려면 child 값을 parent PK domain으로 cast한 뒤 packing해야 한다.

```text
parent WRITE hash input:
  parent class OID + pack(parent-domain, 123.45)

child REF hash input:
  parent class OID + pack(parent-domain,
                          cast(child-value 123.4500 → parent-domain))
```

테스트 매트릭스에는 최소한 NUMERIC precision/scale, 문자열 collation/길이, timezone 계열, coercion 경계값을 넣어야 한다. debug selfcheck 한 번은 일반적인 invariant 검증이지 모든 실제 schema/domain 조합을 검증하지 않는다.

### S7 — DDL/SBR overflow barrier가 단일 exact dependency로 약해질 가능성

**상태**: 정적 코드 흐름 발견 / 후속 리뷰와 동적 검증 필요  
**영향 범위**: FK 변경분 자체가 아니라 공통 writeset PoC

statement replication은 transaction의 `ws_overflow`를 설정하고, commit probe는 직전 commit LSA에 의존시켜 “앞선 작업 전체 뒤”의 barrier를 만들려는 구조다.

```cpp
// 파일: src/transaction/replication.c
// 함수: repl_log_insert_statement()
// 라인: 512–600 부근

tdes->ws_overflow = true;
```

```text
T1 오래 실행 ------------------------- END
T2 짧게 실행 ---- END
T3 DDL/SBR, dependency_seq=T2
```

slave가 `T2가 완료 집합에 있다`는 사실만으로 T3을 통과시키면 T1이 끝나기 전에 DDL이 실행될 수 있다. DDL 이전 barrier의 의도가 “모든 앞선 transaction 완료”라면 DDL dependency는 exact membership이 아니라 gap-free frontier로 판정해야 한다.

DDL commit 뒤 history를 비우고 `history_start`를 전진시키는 후반 barrier와, DDL 자체가 앞선 transaction을 기다리는 전반 barrier를 별도로 검증해야 한다.

### S8 — slave PoC 지원 필터 밖의 DDL 처리

**상태**: 정적 분석 중 / 최종 판정 전

`la_apply_statement_log()`는 여러 DDL 유형을 처리하지만, 그 앞단의 PoC item 지원 필터에는 일부 statement만 열려 있다. 다음 DDL을 각각 추적해야 한다.

```text
CREATE CLASS / DROP CLASS
ALTER CLASS
CREATE INDEX / DROP INDEX
TRUNCATE
기타 statement replication 유형
```

검토 질문은 다음과 같다.

```text
1. 지원 필터 밖 item이 순차 경로로 fallback하는가
2. 오류로 중단하는가
3. 성공 처리처럼 건너뛰는가
4. schema와 후속 DML의 dependency/barrier는 유지되는가
```

이 항목은 후속 DDL 호출 흐름 리뷰에서 실제 코드 블록과 정확한 라인을 추가한 뒤 등급을 확정한다.

### S9 — 대형 transaction의 typed entry 메모리와 overflow 경계

**상태**: 정적 영향 확인 / 측정 필요

```text
기준 브랜치 element: LOG_WRITESET_HASH
FK 브랜치 element:   LOG_WRITESET_ENTRY { hash, kind }
```

구조체 alignment로 element가 8 bytes에서 16 bytes가 되면 FK가 없는 transaction도 local vector 메모리가 약 두 배가 될 수 있다. 반면 transaction limit이 byte 수가 아니라 element 수 기준이라면 같은 limit에서 메모리 상한이 달라진다.

```text
검증 항목:
  sizeof(LOG_WRITESET_ENTRY)
  vector capacity 포함 peak memory
  FK index 수가 많은 row의 entry 증가율
  limit 도달 시 ws_overflow 전환 시점
```

### S10 — debug logging과 DDL history clear로 인한 체감 지연

**상태**: 정적 후보 / 성능 계측 필요

debug build에서는 `er_log_debug`가 활성화될 수 있고 writeset 수집·probe·dispatch/apply 같은 hot path에 transaction별 또는 key별 로그가 존재한다.

```text
대량 DML:
  row × PK/UNIQUE/FK entry마다 writeset 로그 가능

DDL/SBR:
  ws_overflow
  → 전역 history clear
  → 이후 history 재축적
```

따라서 “DDL 자체가 느리다”와 “DDL 전후 대량 debug log I/O/history clear가 느리다”를 분리 측정해야 한다.

```text
동일 debug binary에서 비교:
  er_log_debug=yes / no
  error log bytes/sec
  writeset insert hash 로그 건수
  DDL 전 history size와 clear 시간
  slave statement compile/execute mutex 대기 시간
```

`pthread_once(log_writeset_selfcheck_packing)`은 process 전체에서 첫 FK REF에 한 번만 동기 실행되므로 지속적인 동기화 저하의 1차 후보는 아니다.

### S11 — UNIQUE key handoff와 canonical equality

**상태**: 기본 경로 정적 확인 / collation·NULL·중복 수집 동적 검증 필요  
**영향 범위**: 기본 writeset PoC와 FK PoC 모두. UNIQUE 수집 자체는 두 branch에 공통이며 FK branch의 신규 변경이 아니다.

#### S11.1 UNIQUE는 `REF`가 아니라 `WRITE`로 수집한다

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_add_or_remove_index_internal()`  
**라인**: 7975–8047

INSERT/DELETE 공용 index loop는 partial-index predicate를 먼저 평가하고, 실제 B-tree key를 만든 다음 UNIQUE/REVERSE_UNIQUE key를 수집한다.

```cpp
or_pred = index->filter_predicate;
if (or_pred && or_pred->pred_stream)
  {
    error_code = locator_eval_filter_predicate (..., &ev_res);
    if (error_code == ER_FAILED)
      {
        goto error;
      }
    else if (ev_res != V_TRUE)
      {
        continue;
      }
  }

key_dbvalue = heap_attrvalue_get_key (
  thread_p, i, &index_attrinfo, recdes,
  &btid, &dbvalue, aligned_buf,
  (func_preds ? &func_preds[i] : NULL),
  NULL, inst_oid, false);

...

if (datayn && need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && (index->type == BTREE_UNIQUE
        || index->type == BTREE_REVERSE_UNIQUE))
  {
    LOG_TDES *ws_tdes = LOG_FIND_TDES (
      LOG_FIND_THREAD_TRAN_INDEX (thread_p));

    (void) log_writeset_add_dbvalue (
      thread_p, ws_tdes, class_oid, key_dbvalue);
  }
```

`log_writeset_add_dbvalue()`는 최종적으로 `LOG_WRITESET_KIND_WRITE`를 넣는다.

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_add_dbvalue()` → `log_writeset_add_key()`  
**라인**: 200–263

```cpp
int
log_writeset_add_key (..., const OID *class_oid,
                      const char *packed, int len)
{
  return log_writeset_push (
    thread_p, tdes, class_oid, packed, len,
    LOG_WRITESET_KIND_WRITE);
}

int
log_writeset_add_dbvalue (..., DB_VALUE *pk)
{
  ...
  memset (buf, 0, (size_t) buf_len);
  ptr = or_pack_mem_value (buf, pk, &packed_len);
  ...
  error = log_writeset_add_key (
    thread_p, tdes, class_oid, buf, packed_len);
  ...
}
```

따라서 UNIQUE key의 history 동작은 PK WRITE와 같다.

```text
transaction local:
  UNIQUE key → WRITE hash

commit probe:
  history[UNIQUE hash]를 조회

commit flush:
  history[UNIQUE hash] = current commit LSA
```

#### S11.2 DELETE 후 같은 UNIQUE 값 재사용은 현재 구현의 주된 정상 시나리오다

```sql
CREATE TABLE account (
  id    INT PRIMARY KEY,
  email VARCHAR(100) UNIQUE
);

INSERT INTO account VALUES (1, 'a@example.com');
```

```text
T1: DELETE id=1, UNIQUE email='a@example.com'
    WRITE H(account, pack('a@example.com'))

T2: INSERT id=2, UNIQUE email='a@example.com'
    WRITE H(account, pack('a@example.com'))
```

master에서 T2는 T1이 UNIQUE 값을 해제할 때까지 기다린 뒤 성공한다. T1 commit flush가 같은 hash를 게시하므로 T2 commit probe가 T1을 찾는다.

```text
history[email=a@example.com] = T1
T2.dependency includes T1

slave:
  T1 DELETE 완료
  → T2 INSERT
```

이 dependency가 없다면 slave가 T2 INSERT를 먼저 실행해 UNIQUE violation을 내고 row를 건너뛸 수 있다.

#### S11.3 UPDATE는 old UNIQUE와 변경된 new UNIQUE를 모두 수집한다

**파일**: `src/transaction/locator_sr.c`  
**함수**: `locator_update_index()`  
**라인**: 8697–8737

```cpp
same_key = true;
...
c = btree_compare_key (
  old_key, new_key, key_domain, 0, 1, NULL);

if (c != DB_EQ)
  {
    same_key = false;
  }

if (repl_info != NULL && repl_info->need_replication
    && !LOG_CHECK_LOG_APPLIER (thread_p)
    && log_does_allow_replication () == true
    && (index->type == BTREE_UNIQUE
        || index->type == BTREE_REVERSE_UNIQUE))
  {
    LOG_TDES *ws_tdes = LOG_FIND_TDES (
      LOG_FIND_THREAD_TRAN_INDEX (thread_p));

    (void) log_writeset_add_dbvalue (
      thread_p, ws_tdes, class_oid, old_key);

    if (!same_key)
      {
        (void) log_writeset_add_dbvalue (
          thread_p, ws_tdes, class_oid, new_key);
      }
  }
```

```text
T1: UPDATE account SET email='new' WHERE id=1

T1 writeset:
  PK(1)
  UNIQUE old('old')   ← old 값을 재사용할 후속 INSERT/UPDATE와 연결
  UNIQUE new('new')   ← new 값을 건드리는 선행/후속 transaction과 연결
```

UNIQUE 값이 변하지 않아도 old key 하나는 수집한다. 즉 같은 UNIQUE 값을 가진 동일 row에 대한 반복 UPDATE도 PK뿐 아니라 UNIQUE history를 갱신한다.

partial UNIQUE index는 old/new predicate 결과에 따라 `do_insert_only` 또는 `do_delete_only`를 정한 뒤 이 블록에 들어온다. old와 new가 모두 predicate 밖이면 index loop를 건너뛴다.

#### S11.4 [높음 후보] UNIQUE equality와 writeset hash equality가 같지 않을 수 있다

UNIQUE 중복 여부는 B-tree domain 비교로 결정된다.

**파일**: `src/storage/btree.c`  
**함수**: `btree_compare_key()`  
**라인**: 19460 이후

```cpp
if (are_types_comparable)
  {
    c = key_domain->type->cmpval (
      key1, key2,
      do_coercion, total_order,
      NULL, key_domain->collation_id);
  }
```

반면 writeset은 B-tree의 비교용 canonical sort key를 쓰지 않고 `or_pack_mem_value()`가 만든 DB_VALUE 직렬화 바이트를 해시한다.

**파일**: `src/object/object_representation.c`  
**함수**: `or_pack_mem_value()`  
**라인**: 5053 이후

```cpp
domain = tp_domain_resolve_value (value, NULL);
rc = or_put_domain (buf, domain, 1, 0);

if (rc == NO_ERROR)
  {
    or_get_align64 (buf);
    rc = type->data_writeval (buf, value);
  }
```

문자열 `data_writeval`은 collation weight로 정규화하지 않고 원 문자열 데이터를 기록한다. 따라서 다음 반례를 검증해야 한다.

```sql
CREATE TABLE ci_unique_t (
  id   INT PRIMARY KEY,
  code VARCHAR(20) COLLATE utf8_en_ci UNIQUE
);

INSERT INTO ci_unique_t VALUES (1, 'ABC');
```

```text
collation 비교:
  'ABC' == 'abc'

현재 writeset 후보:
  H(class, pack('ABC')) != H(class, pack('abc'))

T1: DELETE id=1               -- UNIQUE 'ABC' 해제
T2: INSERT id=2, code='abc'   -- 같은 UNIQUE equivalence class 재사용

master: T1 → T2 순서로 성공 가능
slave:  hash가 다르면 T2 → T1 역전 가능
        → T2 UNIQUE violation
```

같은 위험은 case-insensitive뿐 아니라 accent-insensitive, trailing-space-insensitive, expansion을 가진 collation 등 **서로 다른 바이트가 같은 index key로 비교되는 모든 domain**에 적용된다.

> [!warning]
> 이는 코드 구조로 확인한 높은 위험 후보이며 실제 hash와 slave 역전은 동적 테스트로 확정해야 한다. 해결 방향은 raw DB_VALUE serialization이 아니라 B-tree equality와 동일한 canonical key/sort-key 표현을 해시하거나, index 계층이 사용하는 비교 동치 표현을 제공하는 것이다.

#### S11.5 UNIQUE index 식별자가 hash namespace에 없다

현재 hash 입력은 다음뿐이다.

**파일**: `src/transaction/log_writeset.c`  
**함수**: `log_writeset_fnv1a()`  
**라인**: 62–89

```text
hash input = class_oid + packed key
```

`BTID`, constraint OID, index name/type은 포함하지 않는다.

```sql
CREATE TABLE two_unique_t (
  id INT PRIMARY KEY,
  u1 INT UNIQUE,
  u2 INT UNIQUE
);
```

```text
T1: UPDATE ... SET u1=7
T2: UPDATE ... SET u2=7

실제 제약 관계:
  서로 다른 UNIQUE index이므로 독립

현재 hash:
  H(class, pack(7)) == H(class, pack(7))
```

이는 dependency 누락이 아니라 **거짓 dependency**이므로 정합성에는 보수적으로 안전하지만 병렬성을 낮춘다. 같은 class의 PK와 UNIQUE 값이 우연히 동일한 domain/packed bytes인 경우도 충돌한다.

정확도를 높이려면 WRITE hash namespace에 index identity를 넣어야 한다. 다만 FK REF가 parent PK WRITE를 재현해야 하므로 parent PK의 index identity를 FK 쪽에서도 동일하게 넣어야 한다.

#### S11.6 NULL UNIQUE는 서로 독립이어도 같은 hash로 직렬화될 수 있다

CUBRID UNIQUE는 NULL을 허용한다.

**파일**: `src/object/schema_template.c`  
**함수**: constraint 생성/공유 index 검사 블록  
**라인**: 2040–2044

```cpp
/* ... Because unique constraint allows null value ... */
```

현재 UNIQUE 수집부는 NULL을 별도로 건너뛰지 않고 `log_writeset_add_dbvalue()`로 보낸다. NULL DB_VALUE도 domain과 함께 packing될 수 있으므로 같은 table/domain의 NULL들이 같은 hash를 만들 가능성이 높다.

```text
T1: INSERT (id=1, email=NULL)
T2: INSERT (id=2, email=NULL)

DB 제약상:
  둘 다 허용, 독립 실행 가능

현재 writeset:
  UNIQUE NULL hash가 같음
  → 불필요한 dependency chain 가능
```

이 역시 정합성 오류보다는 병렬성 저하다. NULL을 수집하지 않더라도 row identity인 PK는 별도로 수집되므로 서로 다른 row는 독립으로 둘 수 있다. composite UNIQUE는 “어느 column의 NULL이면 중복 허용인가”라는 실제 CUBRID 규칙에 맞춰 skip 조건을 정해야 한다.

#### S11.7 composite UNIQUE는 현재 수집된다

FK REF helper가 composite parent PK를 생략하는 것과 달리, 일반 UNIQUE는 `heap_attrvalue_get_key()`가 만든 `DB_TYPE_MIDXKEY`를 그대로 `log_writeset_add_dbvalue()`에서 packing한다.

```text
UNIQUE (tenant_id, code)

key_dbvalue:
  DB_TYPE_MIDXKEY(tenant_id, code)

writeset:
  WRITE H(class_oid, pack(midxkey))
```

따라서 composite UNIQUE 자체를 의도적으로 skip하는 코드는 없다. 다만 다음은 테스트가 필요하다.

```text
INSERT/DELETE/UPDATE 경로의 동일 MIDXKEY가 같은 bytes로 packing되는가
collation-equivalent component가 canonicalize되는가
일부 component가 NULL인 UNIQUE의 실제 중복 규칙과 hash 정책이 맞는가
ASC/DESC 또는 REVERSE_UNIQUE domain 표현이 안정적인가
```

#### S11.8 한 transaction 안의 중복 key가 vector와 capacity를 부풀린다

주석은 “distinct-key limit”이라고 표현하지만 `ws_hashes`는 vector이며 push 전에 transaction-local dedup을 하지 않는다.

```text
T1이 같은 UNIQUE key를 여러 번 touch:
  [H(u), H(u), H(u), ...]

commit probe:
  같은 history lookup 반복

commit flush:
  같은 map slot 반복 overwrite

capacity 계산:
  write_count는 중복을 모두 셈
```

정합성은 유지되지만 다음 문제가 생길 수 있다.

```text
실제 distinct key 수보다 일찍 TX_LIMIT overflow
map.size() + write_count가 실제 신규 map entry 수보다 커짐
→ history를 불필요하게 clear
→ commit-order fallback과 병렬성 저하
```

#### S11.9 UNIQUE ordering 누락 시 slave 오류는 기본적으로 로그 후 skip될 수 있다

**파일**: `src/transaction/log_applier.c`  
**함수**: `la_flush_repl_items()`  
**라인**: 8090–8184

```cpp
error = __gv_loc_repl.locator_repl_flush_all ();

if (error == ER_LC_PARTIALLY_FAILED_TO_FLUSH)
  {
    while ((flush_err = ws_get_repl_error_from_error_link ()) != NULL)
      {
        er_set (..., flush_err->error_code, ...);
        stats->fail_counter++;

        if (la_restart_on_bulk_flush_error (
              flush_err->error_code) == true)
          {
            return ER_LC_PARTIALLY_FAILED_TO_FLUSH;
          }

        ws_free_repl_flush_error (flush_err);
      }

    error = NO_ERROR;
  }
```

기본 retry/ignore integer list는 `{0}`이고 `ER_BTREE_UNIQUE_FAILED(-670)`는 내장 retry error 목록에도 없다. 따라서 별도 설정이 없다면 UNIQUE violation은 error/fail counter를 남긴 뒤 해당 replication object를 skip하고 flush 전체는 `NO_ERROR`로 돌아갈 수 있다.

```text
writeset UNIQUE dependency 누락
→ slave INSERT/UPDATE 순서 역전
→ ER_BTREE_UNIQUE_FAILED
→ 로그 + fail_counter
→ 해당 row skip
→ master/slave 최종 데이터 불일치 가능
```

그러므로 UNIQUE canonical equality 문제는 단순한 일시 오류가 아니라 최종 수렴을 깨뜨릴 수 있는 정합성 사례로 다뤄야 한다.

### 10.1 설계/테스트 체크리스트

| ID | 반드시 답할 설계 질문 | 우선순위 |
|---|---|---|
| S1 | dependency label은 cumulative watermark인가 exact transaction인가 | 매우 높음 |
| S2 | REF→후속 WRITE 역방향 순서를 어느 FK action까지 보장하는가 | 매우 높음 |
| S3 | 같은 key의 여러 active REF를 어떻게 표현·회수하는가 | 매우 높음 |
| S4 | composite FK를 지원할지, 명시적 fallback할지 | 높음 |
| S5 | REF 생성 실패를 반드시 transaction fallback으로 승격할지 | 높음 |
| S6 | parent-domain canonical packing의 타입별 테스트 범위 | 높음 |
| S7 | DDL 전 barrier를 frontier로 강제할지 | 매우 높음 |
| S8 | 미지원 DDL/SBR의 fallback·skip·error 계약 | 매우 높음 |
| S9 | entry byte 증가를 반영한 memory/overflow limit | 중간 |
| S10 | debug/DDL 성능 회귀의 계측 기준 | 중간 |
| S11 | UNIQUE equality와 hash equality를 일치시키고 index namespace·NULL 정책을 정할지 | 매우 높음 |

---

## 11. 다음 리뷰 블록

```text
log_writeset_add_ref_dbvalue()
  → parent domain cast
  → NULL/composite/cast 실패 처리
  → packed byte 동치 조건
  → LOG_WRITESET_KIND_REF 저장

log_writeset_commit_probe()
  → WRITE/REF 모두 history probe

log_writeset_commit_flush()
  → WRITE만 publish
  → REF probe-only가 만드는 dependency graph
```

## 관련 문서

- [[3. writeset_v2_POC_설계]]
- [[writeset_v2_테스트]]
- [[5. writeset_v2_한계_부모삭제_순서역전_가능성]]
- [[1. writeset_v2_자료조사]]
