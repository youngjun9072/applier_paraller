# Writeset SBR 직렬화와 벤치마크 측정 방식 변경

## 0. 결론

현재 `full`, `fk`, `unique` 벤치마크의 측정용 `USE_SBR` 문장은 실제 workload와 같은 트랜잭션에 들어 있다. 최신 writeset PoC 서버는 SBR을 하나라도 포함한 트랜잭션을 `ws_overflow`로 표시하고, 실제 키 충돌 대신 직전 commit LSA를 `dependency_seq`로 기록한다.

따라서 모든 병렬 workload 파일에 SBR 마커가 들어가면 master가 다음 의존성 사슬을 만든다.

```text
T1.dep = 이전 commit
T2.dep = T1.commit
T3.dep = T2.commit
...
```

slave는 이 의존성을 지키기 위해 `T2`, `T3`를 PARK한다.

```text
T1 적용 완료 → T2 적용 완료 → T3 적용 완료 → ...
```

즉, 여러 `csql` 프로세스를 병렬로 실행해도 slave에서는 한 번에 하나의 트랜잭션만 실행된다. 이는 제품의 writeset 병렬 성능이 아니라 **SBR 정합성 fallback의 직렬 성능**을 측정하는 것이다.

벤치마크를 바꿔야 하는 이유는 단순히 SBR이 느리기 때문이 아니다.

> 측정을 위해 삽입한 SBR 마커가 측정 대상인 workload 트랜잭션의 dependency를 변경하여 정상 writeset 병렬 경로를 우회하기 때문이다.

---

## 1. 기존 full 벤치마크의 SBR 및 INSERT 처리 방식

### 1.1 테이블별 SQL 파일 생성

파일: `/home/youngjun/ha_bench_tool/lib/dataset.sh`  
함수: `generate_dataset()`  
라인: 175~190

```bash
for ((table = 1; table <= NTABLES; table++)); do
    table_name="${TABLE_PREFIX}${table}"

    # INSERT 파일
    append_autocommit_off "$insert_file"
    append_prepare "$table_name" "insert"
    append_phase_start_log "$table_name" "insert" "$INSERT_LOG_TABLE"
    append_insert_executes "$table_name" "$TOTAL_DATA"
    append_phase_end_log "$table_name" "insert" "$INSERT_LOG_TABLE"

    # UPDATE 파일
    append_autocommit_off "$update_file"
    append_prepare "$table_name" "update"
    append_phase_start_log "$table_name" "update" "$UPDATE_LOG_TABLE"
    append_update_executes "$table_name" "$TOTAL_DATA"
    append_phase_end_log "$table_name" "update" "$UPDATE_LOG_TABLE"
done
```

`full`은 테이블마다 INSERT 파일과 UPDATE 파일을 하나씩 만든다.

```text
insert/tbl1.sql   update/tbl1.sql
insert/tbl2.sql   update/tbl2.sql
...               ...
insert/tbl10.sql  update/tbl10.sql
```

### 1.2 START/END 마커가 workload 파일 안에 포함됨

파일: `/home/youngjun/ha_bench_tool/lib/dataset.sh`  
함수: `append_phase_start_log()`, `append_phase_end_log()`  
라인: 37~61

```bash
append_phase_start_log() {
    ...
    echo "INSERT /*+ USE_SBR */
          INTO ${log_table} (table_name, event_ts)
          VALUES ('${table}_start', SYS_DATETIME);"
}

append_phase_end_log() {
    ...
    echo "INSERT /*+ USE_SBR */
          INTO ${log_table} (table_name, event_ts)
          VALUES ('${table}_end', SYS_DATETIME);"
    echo "COMMIT;"
}
```

기본 설정은 다음과 같다.

파일: `/home/youngjun/ha_bench_tool/config/default.json`

```json
{
  "total_data": 100000,
  "transaction_data": 100000,
  "ntables": 10
}
```

생성되는 INSERT 파일 한 개는 다음과 같은 구조다.

```sql
;autocommit off

PREPARE st_tbl1_insert FROM
  'INSERT INTO tbl1 VALUES (?, ?, ...)';

INSERT /*+ USE_SBR */
  INTO insert_perf_log (table_name, event_ts)
  VALUES ('tbl1_start', SYS_DATETIME);

EXECUTE st_tbl1_insert USING 1, ...;
EXECUTE st_tbl1_insert USING 2, ...;
...
EXECUTE st_tbl1_insert USING 100000, ...;

INSERT /*+ USE_SBR */
  INTO insert_perf_log (table_name, event_ts)
  VALUES ('tbl1_end', SYS_DATETIME);

COMMIT;
```

`append_insert_executes()`의 중간 commit 조건은 다음과 같다.

파일: `/home/youngjun/ha_bench_tool/lib/dataset.sh`  
함수: `append_insert_executes()`  
라인: 89~105

```bash
for ((id = 1; id <= count; id++)); do
    echo "EXECUTE ${stmt_name} USING ${id}, ${values};"

    if (( id % TRANSACTION_DATA == 0 )) && (( id < count )); then
        echo "COMMIT;"
    fi
done
```

기본값에서는 `TOTAL_DATA == TRANSACTION_DATA == 100000`이고 마지막 행은 `id < count`를 만족하지 않으므로 중간 commit이 없다.

```text
┌────────────── tbl1 INSERT 트랜잭션 하나 ──────────────┐
│ START SBR                                            │
│ INSERT 1~100,000                                     │
│ END SBR                                              │
│ COMMIT                                               │
└──────────────────────────────────────────────────────┘
```

UPDATE도 같은 구조다.

```text
┌────────────── tbl1 UPDATE 트랜잭션 하나 ──────────────┐
│ START SBR                                            │
│ UPDATE 1~100,000                                     │
│ END SBR                                              │
│ COMMIT                                               │
└──────────────────────────────────────────────────────┘
```

### 1.3 파일 호출 자체는 병렬

파일: `/home/youngjun/ha_bench_tool/bin/run_insert.sh`  
라인: 28~35

```bash
for ((i = 1; i <= NTABLES; i++)); do
    run_sql_file_master \
        "$(phase_file "${TABLE_PREFIX}${i}" "insert")" &
    pids+=("$!")
done

for pid in "${pids[@]}"; do
    wait "$pid"
done
```

따라서 master에는 10개의 독립 `csql` 프로세스가 동시에 요청을 보낸다.

```text
run_insert.sh
  ├─ csql insert/tbl1.sql
  ├─ csql insert/tbl2.sql
  ├─ ...
  └─ csql insert/tbl10.sql
```

문제는 병렬 호출 여부가 아니라 각 파일의 트랜잭션 안에 SBR이 들어 있다는 점이다.

---

## 2. 기존 writeset 측정에서는 왜 문제가 없어 보였는가

### 2.1 SBR overflow 처리는 FK REF 수집 변경 자체가 아님

두 CUBRID 브랜치의 공통 원격 기준은 다음 커밋이다.

```text
e375bfc8c  Floor applylogdb memory budget at 4000MB (temp)
```

이 기준의 `repl_log_insert_statement()`에는 `ws_overflow` 설정이 없다.

파일: `src/transaction/replication.c`  
함수: `repl_log_insert_statement()`  
기준: `e375bfc8c`

```cpp
if (tdes->suppress_replication != 0)
  {
    return NO_ERROR;
  }

/* 여기에는 tdes->ws_overflow = true가 없었음 */

if (REPL_LOG_IS_NOT_EXISTS (tran_index)
    && repl_log_info_alloc (...) != NO_ERROR)
  {
    ...
  }
```

SBR을 commit-order fallback으로 처리하는 변경은 다음 별도 커밋으로 추가됐다.

```text
writeset_poc 로컬 브랜치
  2b11ac12f  writeset PoC fix: demote statement-replicated transactions to commit order

writeset_poc_fk 브랜치
  d1f87c393  writeset PoC fix: demote statement-replicated transactions to commit order
```

두 커밋은 동일한 내용이 각 분기에서 반영된 것이다. FK REF 수집은 그보다 앞선 별도 커밋이다.

```text
781274c5e  writeset v2 stage 1: collect FK reference hashes (probe-only)
```

따라서 관계를 정확히 표현하면 다음과 같다.

```text
FK REF 수집 기능
    ≠ SBR 직렬화 원인

statement replication 정합성 보완
    + 기존 벤치마크의 트랜잭션 내부 SBR 마커
    = workload 전체 overflow 및 slave 직렬화
```

SBR 보완 커밋은 FK 브랜치에서 발견된 DDL 순서 문제를 해결하는 과정에서 추가됐지만, 동작 범위는 FK가 아니라 모든 statement replication이다.

### 2.2 변경 전에는 같은 트랜잭션의 workload writeset을 계속 사용함

변경 전에는 측정용 SBR 문장이 있어도 트랜잭션의 `ws_overflow`가 설정되지 않았다. 따라서 같은 트랜잭션에서 수집된 실제 INSERT/UPDATE 키들이 commit dependency 계산에 사용됐다.

```text
변경 전

SBR START
  → statement replication log만 추가
  → ws_overflow는 false 유지

INSERT 100,000건
  → PK WRITE hash 수집

SBR END
  → statement replication log만 추가

COMMIT
  → 수집된 PK WRITE hash로 dependency 계산
```

테이블이 서로 다르면 class OID가 다르기 때문에 writeset hash도 충돌하지 않는다.

```text
tbl1 INSERT writeset ─┐
tbl2 INSERT writeset ─┼─ 서로 충돌하지 않음 → 병렬 가능
tbl3 INSERT writeset ─┘
```

이 때문에 SBR fallback 변경 전 서버로 `full`을 측정했다면 병렬로 보일 수 있다.

### 2.3 변경 후에는 workload writeset을 수집했더라도 commit에서 사용하지 않음

변경 후에는 첫 START SBR에서 곧바로 트랜잭션 전체가 overflow 상태가 된다.

```text
변경 후

SBR START
  → ws_overflow=true

INSERT 100,000건
  → 정상 dependency 계산 대상으로 사용할 수 없음

SBR END
  → ws_overflow=true 유지

COMMIT
  → actual writeset 대신 직전 commit을 dependency로 선택
```

### 2.4 과거 측정 결과 확인 시 구분할 항목

과거 `full` 결과가 병렬로 보였다면 다음을 확인해야 한다.

1. 실행한 서버 바이너리가 `2b11ac12f`/`d1f87c393` 이전인지
2. `transaction_data`가 `total_data`보다 작아 중간의 순수 DML 트랜잭션들이 병렬 실행된 것인지
3. dataset cache가 현재 설정과 같은 SQL을 사용했는지
4. `slave.host`가 비어 있어 report가 실제 slave가 아니라 master를 다시 조회한 것은 아닌지

`transaction_data=10000`, `total_data=100000`이면 구조가 다음과 같다.

```text
첫 10,000행 + START SBR  → overflow
중간 10,000행 batch들    → 정상 writeset
마지막 10,000행 + END SBR → overflow
```

반면 현재 기본값 `100000 == 100000`에서는 workload 전체가 하나의 overflow 트랜잭션이다.

---

## 3. Master에서 last_committed를 조정하는 방법

### 3.1 용어 대응

현재 CUBRID PoC 코드에 `last_committed`라는 이름의 필드는 없다. 같은 역할을 하는 값은 다음과 같다.

```text
MySQL 계열 용어              CUBRID writeset PoC
────────────────────────────────────────────────────
last_committed              ws_dependency_seq / dependency_seq
직전 commit sequence         log_Writeset_prev_commit_lsa
현재 transaction sequence   commit_lsa
```

이 문서에서 `last_committed`는 이해를 돕기 위한 개념명이고, 실제 코드 필드명은 `dependency_seq`다.

### 3.2 SBR을 만나면 트랜잭션을 overflow로 표시

파일: `src/transaction/replication.c`  
함수: `repl_log_insert_statement()`  
라인: 512~540

```cpp
int
repl_log_insert_statement (THREAD_ENTRY *thread_p,
                           REPL_INFO_SBR *repl_info)
{
  LOG_TDES *tdes;

  ...

  /* SBR은 row image가 없어 writeset hash로 효과를 표현할 수 없다. */
  tdes->ws_overflow = true;

  ...
}
```

이 값은 statement 하나가 아니라 현재 트랜잭션 descriptor에 붙는다.

```text
SBR 하나 실행
    ↓
현재 트랜잭션의 tdes->ws_overflow = true
    ↓
COMMIT까지 유지
```

### 3.3 Commit probe에서 직전 commit을 dependency로 선택

파일: `src/transaction/log_writeset.c`  
함수: `log_writeset_commit_probe()`  
라인: 399~417

```cpp
pthread_mutex_lock (&log_Writeset_history.latch);

if (tdes != NULL && tdes->ws_overflow)
  {
    /* 실제 key history를 probe하지 않고 commit-order로 fallback */
    LSA_COPY (ws_parent_out,
              &log_Writeset_prev_commit_lsa);

    pthread_mutex_unlock (&log_Writeset_history.latch);
    return;
  }
```

이를 개념식으로 표현하면 다음과 같다.

```text
overflow transaction:
    last_committed(T) = prev_commit_lsa

normal transaction:
    last_committed(T) = 실제 writeset이 충돌한 선행 commit
```

모든 workload가 SBR을 포함하면 master commit 순서에 따라 다음 사슬이 만들어진다.

```text
master commit 순서: T1, T2, T3, T4

T1.dependency_seq = P0.commit_lsa
T2.dependency_seq = T1.commit_lsa
T3.dependency_seq = T2.commit_lsa
T4.dependency_seq = T3.commit_lsa
```

### 3.4 Dependency label을 commit 바로 앞 로그에 기록

파일: `src/transaction/log_manager.c`  
함수: `log_append_ws_label_with_lock()`  
라인: 4681~4696

```cpp
node = prior_lsa_alloc_and_copy_data (...,
                                      LOG_DUMMY_WS_LABEL,
                                      ...);

ws_label = (LOG_REC_WS_LABEL *) node->data_header;

LSA_COPY (&ws_label->dependency_seq,
          &tdes->ws_dependency_seq);

prior_lsa_next_record_with_lock (thread_p, node, tdes);
```

master WAL에는 다음 순서로 기록된다.

```text
... transaction replication records ...
LOG_DUMMY_WS_LABEL(dependency_seq)
LOG_COMMIT(commit_lsa)
```

예를 들면 다음과 같다.

```text
T1: WS_LABEL(dep=P0) → COMMIT(C1)
T2: WS_LABEL(dep=C1) → COMMIT(C2)
T3: WS_LABEL(dep=C2) → COMMIT(C3)
```

### 3.5 Commit 후 history clear 및 floor 이동

파일: `src/transaction/log_writeset.c`  
함수: `log_writeset_commit_flush()`  
라인: 471~547

```cpp
/* 다음 트랜잭션이 사용할 직전 commit 기준 갱신 */
if (LSA_ISNULL (&log_Writeset_prev_commit_lsa)
    || LSA_GT (commit_lsa, &log_Writeset_prev_commit_lsa))
  {
    LSA_COPY (&log_Writeset_prev_commit_lsa,
              commit_lsa);
  }

if (tdes->ws_overflow)
  {
    /* 불완전한 hash history를 이후 트랜잭션이 신뢰하지 않도록 제거 */
    log_Writeset_history.map.clear ();

    if (LSA_GT (commit_lsa,
                &log_Writeset_history.history_start))
      {
        LSA_COPY (&log_Writeset_history.history_start,
                  commit_lsa);
      }
  }
```

master에서 일어나는 일을 구분해야 한다.

```text
Master에서 하는 일
  1. SBR을 보고 ws_overflow 설정
  2. dependency_seq를 직전 commit으로 지정
  3. dependency_seq를 WAL에 기록
  4. history를 clear하고 floor를 현재 commit으로 이동

Master에서 하지 않는 일
  - 여러 workload 클라이언트의 DML 실행 자체를 한 워커로 직렬화
```

master는 직렬 실행해야 한다는 **의존성 메타데이터**를 만들고, 실제 적용 직렬화는 slave가 수행한다.

---

## 4. Slave에서 dependency를 처리하는 방법

### 4.1 WS_LABEL에서 dependency 복원

파일: `src/transaction/log_applier.c`  
함수: `la_retrieve_ws_label()`  
라인: 6793~6820

```cpp
ws_label =
  (LOG_REC_WS_LABEL *) ((char *) pg->area + offset);

LSA_COPY (dependency_seq,
          &ws_label->dependency_seq);
```

reader는 label을 잠시 보관했다가 같은 `trid`의 `LOG_COMMIT`을 읽을 때 task에 넣는다.

파일: `src/transaction/log_applier.c`  
함수: 로그 reader의 `LOG_COMMIT` 처리 경로  
라인: 10068~10086

```cpp
task.tranid = lrec->trid;
LSA_COPY (&task.commit_lsa, final);

if (la_ws_label_trid == lrec->trid)
  {
    LSA_COPY (&task.dependency_seq,
              &la_ws_label_dependency_seq);
  }
else
  {
    LSA_SET_NULL (&task.dependency_seq);
  }
```

slave는 writeset hash를 다시 계산하지 않는다. master가 계산해 보낸 dependency를 그대로 gate에 사용한다.

### 4.2 Dependency 충족 여부 검사

파일: `src/transaction/log_applier.c`  
함수: `la_gate_is_satisfied()`  
라인: 1676~1688

```cpp
static bool
la_gate_is_satisfied (const LOG_LSA *dep)
{
  if (LSA_ISNULL (dep))
    {
      return true;
    }

  if (la_Gate_frontier_seeded
      && LSA_LE (dep, &la_Gate_frontier))
    {
      return true;
    }

  return la_gate_set_contains (dep);
}
```

통과 조건은 다음 셋 중 하나다.

```text
1. dependency가 NULL
2. dependency가 gap-free 완료 frontier 이하
3. dependency가 out-of-order 완료 집합에 존재
```

### 4.3 미충족 task는 worker에 보내지 않고 PARK

파일: `src/transaction/log_applier.c`  
함수: 로그 reader의 `LOG_COMMIT` 처리 경로  
라인: 10102~10124

```cpp
if (la_gate_is_satisfied (&task.dependency_seq))
  {
    la_gate_dispatch_now (&task);
  }
else
  {
    la_gate_enqueue_pending (&task);

    er_log_debug (...,
                  "ws_reader PARK "
                  "trid=%d commit=%lld|%d dep=%lld|%d\n",
                  ...);
  }
```

`PARK`된 task는 worker queue에 들어가지 않는다. 따라서 worker가 10개여도 실행할 task가 없으면 idle 상태로 남는다.

### 4.4 선행 commit 완료 후 pending을 다시 dispatch

파일: `src/transaction/log_applier.c`  
함수: `la_collect_worker_results()`  
라인: 2473~2529

```cpp
while (la_try_dequeue_apply_result (&la_apply_Workers[i],
                                    &result) == NO_ERROR)
  {
    ...

    if (result.rectype == LOG_COMMIT)
      {
        la_gate_mark_completed (&result.commit_lsa);
      }
  }

la_gate_advance_frontier ();

/* 완료된 dependency로 풀린 pending task를 dispatch */
la_gate_drain_ready ();
```

slave DB commit이 끝난 선행 LSA가 완료 집합에 들어가면 pending queue를 다시 검사한다.

---

## 5. 왜 병렬 workload가 직렬화되는가

### 5.1 정상 writeset의 기대 그래프

`tbl1`, `tbl2`, `tbl3`가 서로 다른 키와 테이블을 사용한다면 정상 dependency는 공통 floor만 가리키거나 NULL이다.

```text
             ┌── T1
BASE ────────├── T2
             └── T3
```

slave에서는 세 트랜잭션을 서로 다른 worker에 동시에 dispatch할 수 있다.

```text
worker 0: [ T1 ]
worker 1: [ T2 ]
worker 2: [ T3 ]
```

### 5.2 모든 workload 트랜잭션이 SBR을 포함한 경우

master의 실제 commit 순서가 `T2, T1, T3`라고 가정한다.

```text
T2: overflow → dep=BASE → commit=C2
T1: overflow → dep=C2   → commit=C1
T3: overflow → dep=C1   → commit=C3
```

의존성 그래프는 실제 키 관계와 무관하게 한 줄이 된다.

```text
BASE → T2 → T1 → T3
```

slave reader가 세 commit을 읽으면 다음 상태가 된다.

```text
T2: dep=BASE, 충족     → DISPATCH
T1: dep=T2, 미충족     → PARK
T3: dep=T1, 미충족     → PARK
```

T2가 끝난 뒤에야 T1 하나가 풀리고, T1이 끝난 뒤에야 T3가 풀린다.

```text
시간 ─────────────────────────────────────────▶

worker 0: [ T2 ]
worker 1:        [ T1 ]
worker 2:               [ T3 ]
```

워커 수를 늘려도 READY task가 한 개뿐이므로 처리량이 증가하지 않는다.

### 5.3 Full 기본 설정에서의 실제 결과

Full은 10개 파일을 병렬 호출하지만 각 파일 전체가 하나의 SBR 포함 트랜잭션이다.

```text
Master 요청:
  tbl1 INSERT ┐
  tbl2 INSERT ├─ 10개 csql 병렬
  ...         │
  tbl10 INSERT┘

Master dependency 생성:
  tbl5 → tbl1 → tbl3 → tbl9 → ...

Slave 적용:
  tbl5 END → tbl1 START
           tbl1 END → tbl3 START
                      ...
```

따라서 perf log의 구간이 겹치지 않고 테이블별 처리 시간 간격으로 나타난다.

### 5.4 문제의 정확한 위치

```text
SBR이 master DML 실행을 직렬화한다          → 아님
SBR 때문에 master가 직렬 dependency를 만든다 → 맞음
slave gate가 dependency를 실행 순서로 강제한다 → 맞음
FK REF가 형제 트랜잭션을 직렬화한다          → 이번 현상의 원인이 아님
```

---

## 6. 벤치마크 방법을 바꿔야 하는 이유

### 6.1 현재 측정은 관찰 대상에 영향을 줌

원래 측정하려는 것은 다음 경로다.

```text
순수 INSERT/UPDATE
  → WRITE/REF hash 수집
  → 실제 충돌 기반 dependency 생성
  → slave 병렬 dispatch
```

하지만 현재 측정 마커가 만드는 경로는 다음과 같다.

```text
SBR START + INSERT/UPDATE + SBR END
  → ws_overflow=true
  → 실제 WRITE/REF hash 무시
  → commit-order fallback
  → slave 직렬 dispatch
```

따라서 현재 결과로는 다음을 평가할 수 없다.

- 서로 다른 테이블의 writeset 병렬성
- 부모별 FK dependency가 올바르게 분리되는지
- 같은 부모를 참조하는 형제 child가 병렬 실행되는지
- worker 수 증가에 따른 정상 writeset 처리량

### 6.2 SBR fallback 자체는 제거 대상이 아님

SBR fallback은 DDL처럼 row image가 없는 statement를 안전하게 복제하기 위한 정합성 장치다. 벤치마크 때문에 서버의 이 동작을 제거하면 DDL과 뒤따르는 DML의 순서가 다시 깨질 수 있다.

```text
CREATE TABLE T       -- SBR, hash로 표현 불가
INSERT INTO T ...    -- RBR, row hash 존재
```

두 트랜잭션을 독립으로 표시하면 slave에서 INSERT가 CREATE보다 먼저 실행될 수 있다. 따라서 고쳐야 할 곳은 서버 정합성 fallback이 아니라 **측정용 마커의 배치 방식**이다.

### 6.3 SBR/DDL을 방어적으로 처리하는 정확한 이유

SBR이 본질적으로 병렬 실행 불가능한 것은 아니다. 현재 PoC가 statement의 실제 영향 범위를 writeset hash로 표현하지 못하기 때문에 안전한 dependency를 계산할 수 없는 것이 핵심이다.

DDL은 일반적으로 statement replication 형태로 복제되므로 다음 관계로 이해할 수 있다.

```text
Statement Replication(SBR)
  ├─ DDL: CREATE / ALTER / DROP ...
  └─ USE_SBR로 강제한 DML
```

RBR DML은 변경된 행의 class OID와 PK를 알고 있으므로 실제 충돌 키를 생성할 수 있다.

```sql
UPDATE tbl1
   SET value = value + 1
 WHERE id = 10;
```

```text
WRITE hash = hash(tbl1 class OID, PK=10)
```

반면 다음 SBR DML은 실행할 SQL 문장은 있어도 writeset scheduler가 사용할 확정적인 row image가 없다.

```sql
UPDATE /*+ USE_SBR */ tbl1
   SET value = value + 1
 WHERE status = 'READY';
```

현재 SBR replication 정보만으로는 다음 내용을 간단하고 정확하게 알 수 없다.

```text
- 실제로 변경된 PK 목록
- 다른 트랜잭션과 충돌하는 행 범위
- statement 실행 시점의 predicate 결과
- DDL로 생성·변경·삭제되는 schema object
- 뒤따르는 DML이 영향을 받는 범위
```

DDL과 DML의 예를 보면 문제가 더 명확하다.

```text
Master commit 순서

T1: CREATE TABLE parent (...)
T2: INSERT INTO parent VALUES (1)
```

행 기반 writeset만 보면 다음과 같이 보인다.

```text
T1 writeset: 없음
T2 writeset: hash(parent, PK=1)
```

T1과 T2를 독립으로 표시하면 slave에서 순서가 뒤집힐 수 있다.

```text
worker 1: T2 INSERT
worker 2: T1 CREATE TABLE
```

그 결과 다음 문제가 가능하다.

```text
- 테이블이 아직 없어 INSERT 실패
- INSERT 후 CREATE가 적용되어 먼저 들어간 데이터가 사라짐
- ALTER/DROP과 DML의 적용 순서가 바뀌어 schema 불일치
- index/constraint 생성 시점이 바뀌어 master와 다른 결과 발생
```

실제로 SBR fallback 커밋 `2b11ac12f`/`d1f87c393`의 설명에도 `CREATE TABLE`이 뒤의 INSERT보다 늦게 적용되어 데이터가 사라진 사례가 변경 이유로 기록되어 있다.

이 때문에 현재 구현은 SBR을 발견하면 해당 트랜잭션을 보수적인 순서 경계로 만든다.

```text
이전 트랜잭션들
       ↓
     SBR/DDL
       ↓
이후 트랜잭션들
```

master에서는 다음 메타데이터를 만든다.

```cpp
/* SBR 발견 */
tdes->ws_overflow = true;

/* commit probe */
dependency_seq = prev_commit_lsa;

/* commit flush */
writeset_history.clear ();
history_start = current_commit_lsa;
```

이 처리의 목적은 두 방향의 순서 역전을 막는 것이다.

```text
1. SBR이 앞선 transaction보다 먼저 slave에 적용되는 것 방지
2. 뒤따르는 DML이 SBR보다 먼저 slave에 적용되는 것 방지
```

SBR 하나만 존재하는 일반적인 의도는 SBR을 통과한 정상 workload가 다시 병렬로 분기하는 것이다.

```text
                 ┌── W1
이전 → SBR ──────├── W2
                 └── W3
```

그러나 기존 벤치마크는 각 workload 트랜잭션마다 SBR START/END를 넣었다.

```text
SBR+W1
SBR+W2
SBR+W3
SBR+W4
```

따라서 모든 트랜잭션이 방어적 fallback 대상이 되어 다음 직렬 사슬이 만들어진다.

```text
SBR+W1 → SBR+W2 → SBR+W3 → SBR+W4
```

정리하면 다음과 같다.

> SBR/DDL은 병렬 실행이 원천적으로 불가능한 것이 아니다. 현재 PoC가 statement의 실제 영향 범위를 writeset으로 표현하지 못하므로 순서가 뒤집혀 정합성이 깨지는 것보다 성능을 희생하는 commit-order fallback을 선택한 것이다.

향후 DDL에 schema/table dependency를 만들거나 SBR DML에 실제 영향 행 또는 table-level dependency를 생성할 수 있다면 더 세밀한 병렬화가 가능하다. 현재 단계에서는 서버의 방어적 처리를 유지하고, 벤치마크 마커를 workload 트랜잭션에서 분리해야 한다.

---

## 7. 해결 방법

## 7.1 권장안: workload에서 SBR을 제거하고 coordinator가 측정

병렬 호출은 SQL 파일 하나가 아니라 여러 `csql` 프로세스를 관리하는 벤치마크 coordinator가 담당해야 한다.

```text
1. coordinator가 시작 시각 기록
2. SBR 없는 workload 파일 N개 병렬 실행
3. master의 모든 csql 프로세스 종료 대기
4. slave에서 모든 완료 토큰/최종 row count 확인
5. 확인 완료 순간을 slave_done으로 기록
```

개념적인 호출 구조는 다음과 같다.

```bash
benchmark_start=$(date +%s%N)

for workload_file in "${workload_files[@]}"; do
    run_sql_file_master "$workload_file" &
    pids+=("$!")
done

for pid in "${pids[@]}"; do
    wait "$pid"
done

master_end=$(date +%s%N)

wait_for_all_slave_completion_tokens
wait_for_expected_slave_row_counts

slave_done=$(date +%s%N)
```

이때 측정값은 다음처럼 정의한다.

```text
master workload duration = master_end - benchmark_start
replication drain time    = slave_done - master_end
end-to-end duration       = slave_done - benchmark_start
```

### 7.2 각 workload의 완료는 SBR이 아닌 RBR 토큰으로 확인

각 workload 파일 끝에 `USE_SBR`이 없는 고유 완료 토큰을 같은 트랜잭션으로 넣을 수 있다.

```sql
;autocommit off

-- 순수 workload
INSERT INTO tbl1 ...;
...

-- USE_SBR 없음: workload와 원자적으로 slave에 적용되는 완료 토큰
INSERT INTO benchmark_done (workload_name)
VALUES ('insert_tbl1');

COMMIT;
```

slave에서 토큰이 보인다는 것은 해당 workload의 slave commit도 끝났다는 뜻이다.

```text
benchmark_done('insert_tbl1') 확인
    ⇒ tbl1 workload slave commit 완료
```

모든 토큰은 서로 다른 PK를 사용해야 토큰끼리 불필요한 writeset 충돌을 만들지 않는다.

```text
insert_tbl1
insert_tbl2
...
insert_tbl10
```

### 7.3 SBR timestamp가 꼭 필요할 때의 차선안

slave가 직접 평가한 `SYS_DATETIME`을 반드시 DB에 보관해야 한다면 SBR을 workload와 분리한다.

```text
START SBR 트랜잭션
→ COMMIT
→ slave START marker 확인
→ SBR 없는 workload 파일 병렬 호출
→ master workload COMMIT 완료
→ slave의 모든 RBR 완료 토큰 및 row count 확인
→ END SBR 트랜잭션
→ COMMIT
→ slave END marker 확인
```

SQL 경계는 다음과 같아야 한다.

```sql
-- M1: 별도 START marker 트랜잭션
INSERT /*+ USE_SBR */ INTO perf_log (...) VALUES (..., SYS_DATETIME);
COMMIT;

-- W1..WN: 각자 별도 순수 workload 트랜잭션
INSERT ...;
...
INSERT INTO benchmark_done (...) VALUES (...);  -- RBR
COMMIT;

-- M2: 모든 slave 완료 검증 후 별도 END marker 트랜잭션
INSERT /*+ USE_SBR */ INTO perf_log (...) VALUES (..., SYS_DATETIME);
COMMIT;
```

START SBR 한 개는 완료 후 여러 정상 workload가 공통으로 기다리는 fan-out 경계를 만들 수 있다.

```text
                 ┌── W1
START marker ────├── W2
                 └── W3
```

그러나 workload 직후 master에 END SBR 하나를 기록하는 것만으로는 모든 병렬 workload의 slave 완료를 보장하지 못한다. 현재 dependency label은 선행 LSA 하나만 표현하기 때문이다.

```text
W1 ─────────────── 아직 실행 중
W2 ───── 완료
W3 ─────── 완료
             │
             └─ END marker가 직전 commit 하나만 기다리고 보일 수 있음
```

따라서 END SBR은 완료 barrier로 사용하지 말고, **모든 토큰과 row count를 확인한 뒤 slave-local 종료 시각을 보관하는 용도**로만 사용해야 한다.

### 7.4 기존 단일 replcheck도 전체 barrier로 간주하면 안 됨

현재 `run_insert.sh`는 모든 master 프로세스가 끝난 뒤 하나의 marker를 넣는다.

파일: `/home/youngjun/ha_bench_tool/bin/run_insert.sh`  
라인: 33~38

```bash
for pid in "${pids[@]}"; do
    wait "$pid"
done

run_sql_master \
    "INSERT INTO ${INSERT_REPLCHECK_TABLE} VALUES(1);"

wait_for_replication_marker "$INSERT_REPLCHECK_TABLE"
```

병렬 applier에서는 뒤의 marker 하나가 앞선 독립 트랜잭션 전체에 대한 다중 dependency를 표현하지 않는다. 따라서 다음을 함께 확인해야 한다.

```text
모든 workload별 완료 토큰
+ 최종 row count
+ 필요 시 데이터 정합성 query
```

---

## 8. Full 및 FK 권장 실행 흐름

### 8.1 Full

```text
INSERT phase 시작 시각 기록
→ tbl1~tbl10 INSERT 파일 병렬 실행(SBR 없음)
→ master 프로세스 10개 종료
→ slave INSERT 완료 토큰 10개 + row count 확인
→ INSERT phase 종료 시각 기록

UPDATE phase 시작 시각 기록
→ tbl1~tbl10 UPDATE 파일 병렬 실행(SBR 없음)
→ master 프로세스 10개 종료
→ slave UPDATE 완료 토큰 10개 + 결과 확인
→ UPDATE phase 종료 시각 기록
```

### 8.2 FK dependency 검증 모드

```text
START 기록
→ 부모 P1/P3/P5/P7/P9를 master에서 병렬 실행
→ 부모 master commit 완료
→ 자식 C2-1/C2-2/...를 master에서 병렬 실행
→ slave에서 부모·자식 완료 토큰 15개와 row count 확인
→ END 기록
```

이 방식은 부모가 slave에서 아직 적용 중일 때 자식이 도착할 수 있어 FK gate를 실제로 검증한다.

```text
P1 ──┬── C2-1
     └── C2-2

P3 ──┬── C4-1
     └── C4-2
```

엄격하게 “모든 부모 slave 적용 완료 후 모든 자식 실행”을 확인하려면 부모 토큰을 전부 확인한 뒤 자식을 실행한다. 다만 이 경우 자식이 도착할 때 부모가 이미 완료되어 FK의 실제 PARK/해제 경로는 거의 발생하지 않는다.

---

## 9. 팀 공유용 요약

```text
1. 기존 full/fk 벤치마크는 각 workload 트랜잭션 안에
   START/END USE_SBR 마커를 넣었다.

2. 초기 writeset PoC에서는 SBR이 ws_overflow를 설정하지 않아
   같은 트랜잭션의 INSERT/UPDATE writeset이 dependency 계산에 사용됐다.
   그래서 과거 full 결과가 병렬로 보일 수 있었다.

3. DDL 등 row image가 없는 statement의 정합성을 보장하기 위해
   최신 서버는 SBR을 포함한 트랜잭션 전체를 ws_overflow로 격하한다.

4. overflow 트랜잭션은 실제 writeset 충돌 대신 직전 commit LSA를
   dependency_seq(MySQL 용어의 last_committed 역할)로 기록한다.

5. 모든 workload에 SBR이 있으므로 T1→T2→T3 형태의 dependency chain이 생긴다.

6. slave gate는 선행 transaction이 완료될 때까지 후속 transaction을 PARK한다.
   따라서 worker가 여러 개여도 한 번에 하나만 실행된다.

7. 이 상태의 벤치마크는 정상 writeset 병렬 성능이 아니라
   SBR commit-order fallback 성능을 측정한다.

8. 서버의 SBR 정합성 처리는 유지하고, 측정용 SBR을 workload transaction에서
   분리해야 한다. workload 완료는 고유 RBR 토큰 전체와 row count로 확인하고,
   시간은 coordinator가 기록하는 방식을 권장한다.
```
