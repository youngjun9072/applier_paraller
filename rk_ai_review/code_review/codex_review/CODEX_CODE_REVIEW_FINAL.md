# CBRD-26246 RK 기능 코드 리뷰 최종보고서

- 작성일: 2026-08-24
- 대상: `feature/CBRD-26246-develop@9e094324b8ef`
- 비교: `upstream/develop@5b9c0d8155f8`
- 공통 조상: `b646647eca4236057ea7c3c28960e61c53b0c209`
- 범위: 공통 조상 대비 feature 고유 35개 변경 파일, `+1,444/-57`
- 방법: 개발 관련 20개 관점 → 187개 raw 관찰 → LSP/호출 흐름 → E2E 입력과 대조 조건 →
  develop 삼자 비교 → 관련 closed PR 및 현재 HEAD 재대조

> 이 파일 하나만 읽어도 기능 목적, 조사 방법, 확정 문제 10건, 조건부·develop 기존·운영 항목과
> 기각 근거를 이해할 수 있도록 작성했다. 각 finding은 최소 상태, 입력, master→log→applier→slave
> 순서, 문제가 없는 대조 조건, 실제 코드 또는 출처가 붙은 의사코드를 포함한다.

## 1. 결론

현재 feature HEAD에서 독립 실행 경로가 확인된 결함은 **10건**이다.

| 상태 | 수 | ID |
|---|---:|---|
| 확정 feature 결함 | **10** | CR-02, 03, 04, 06, 07, 09, 10, 11, 14, PERF-01 |
| 조건부 | 2 | CR-13, CR-15 |
| develop 기존/feature 악화 | 1 | CR-12 |
| 운영 권고 | 1 | OPS-01 |

기존 보고서의 16건에서 CR-05는 실행 전제 미입증, CR-08과 CR-17은 오분석으로 내려갔다. CR-16은
후속 반영 예정인 `heap_get_class_repl_on()` 교체가 적용된 상태를 리뷰 전제로 삼아 제외했다. 반대로
#7697 뒤에도 남은 OFF class 반복 fetch는 PERF-01로 복원했다.

병합 차단 권고 범위는 데이터 누락·오적용 또는 OFF 계약 위반을 만드는 High 9건(CR-02, 03, 04,
06, 07, 09, 10, 11, 14)이다. PERF-01은 Low이므로 같은 우선순위로 취급하지 않는다.

## 2. 기능이 하려는 일

기존 HA row replication은 PK로 standby의 대상 행을 찾는다. 이 feature는 다음을 추가한다.

1. PK가 없으면 NOT NULL UNIQUE도 Replication Key(RK)로 사용한다.
2. `REPLICATION=ON|OFF`로 table별 DML 복제 여부를 선택한다. DDL은 양 노드 schema 유지를 위해 복제한다.
3. ON table이 마지막 RK를 잃는 DDL을 HA 중 거부한다.
4. `rkcheck`로 RK 존재와 FK 대상 table의 복제 상태를 검사하고 heartbeat start에 연결한다.
5. SBR/RBR, partition, unload/load, SHOW CREATE와 catalog에 정책을 전달한다.

핵심 불변식은 “DDL/rkcheck가 승인한 ON table의 모든 row는 master와 slave가 같은 RK로 식별한다”와
“OFF table의 직접 DML은 slave에 재실행되지 않는다”이다. 이번 확정 결함은 이 두 불변식을 계층마다
다르게 해석하면서 발생한다.

## 3. 조사와 필터링 방식

- feature 귀속은 `merge-base→feature`, develop 후속 변화는 `merge-base→develop`로 따로 보았다.
  `develop→feature` 직접 diff에 섞이는 develop의 후속 commit 역변경은 RK 결함으로 세지 않았다.
- 20개 관점은 각각 최대 50건까지 탐색했으나 실제 관찰 7~13건에서 근거가 소진됐다. 187은 같은
  root cause를 직군별 영향으로 반복 관찰한 수다.
- 키워드가 존재한다는 이유로 채택하지 않았다. caller/callee, CS/SA/server 경계, log 생성 여부와
  applier 도달 여부를 따라갔다.
- develop 기존과 후속 PR 해결 항목은 삭제하지 않고 상태를 표시했다.
- GitHub closed-PR 목록을 2026-08-24에 재확인했다. #7370은 closed/unmerged, #6908과 #7697은 merged이며
  현재 feature HEAD가 결과 commit을 포함한다.
- clangd는 정의·참조·자료형 확인에 사용하되 진단만으로 finding을 확정하지 않았다. 실제 checkout에
  남은 `heap_is_replication_class` 1곳은 후속 `heap_get_class_repl_on` 교체가 적용된 상태를 전제로 했다.

## 4. 확정 feature 결함

### CR-02 [High] mixed-null 복합 UNIQUE는 승인되지만 master가 로그를 만들지 않는다

최소 상태는 HA enabled, ON table, PK 없음, 유일한 복합 UNIQUE 중 일부 컬럼만 NOT NULL인 경우다.

```sql
CREATE TABLE t (a INT NOT NULL, b INT, UNIQUE(a,b)) REPLICATION=ON;
INSERT INTO t VALUES (1,10);
```

```c
/* src/query/execute_schema.c:109-114 — IS_HA_REPLICATION_KEY_CONSTRAINT
 * src/object/schema_manager.c — sm_has_non_null_attribute
 * client DDL/rkcheck는 한 컬럼만 NOT NULL이어도 true(ANY).
 */
SM_IS_CONSTRAINT_UNIQUE_FAMILY (c->type)
  && sm_has_non_null_attribute (c->attributes);
```

```c
/* src/base/object_representation_sr.c:4694-4723
 * or_is_replication_candidate_key
 * master와 slave server runtime은 모든 컬럼을 요구(ALL).
 */
for (int i = 0; i < index->n_atts; i++)
  if (index->atts[i] == NULL || !index->atts[i]->is_notnull)
    return false;
```

실행은 DDL/rkcheck 승인 → master INSERT runtime 후보 탈락 → `repl_log_insert()` 미호출 → applylogdb가
받을 log 없음 → slave 미변경 순서다. applier가 client와 다른 predicate를 호출해 실패하는 것이 아니다.
applier는 호출되지 않는다. 두 컬럼을 모두 NOT NULL로 만들거나 PK를 추가하면 log가 생기는 것이 대조
조건이다. develop은 PK-only라 이 승인 경로가 없다.

권고: client/server representation이 공유하는 ALL-key-columns-NOT-NULL 함수를 사용하고 nullability
truth table을 CREATE, ALTER, rkcheck, INSERT/UPDATE/DELETE에 동일 적용한다.

### CR-03 [High] REVERSE UNIQUE를 client는 RK로 승인하고 server는 거부한다

```sql
CREATE TABLE t (a INT NOT NULL, REVERSE UNIQUE(a)) REPLICATION=ON;
INSERT INTO t VALUES (1);
```

```c
/* src/object/class_object.h — SM_IS_CONSTRAINT_UNIQUE_FAMILY */
UNIQUE || PRIMARY_KEY || REVERSE_UNIQUE
```

```c
/* src/base/object_representation_sr.c:4694-4709
 * or_is_replication_candidate_key
 */
if (index->type == BTREE_PRIMARY_KEY) return true;
if (index->type != BTREE_UNIQUE) return false;
```

DDL/rkcheck는 성공하지만 master runtime에서 reverse type이 탈락해 log가 없고 slave가 바뀌지 않는다.
일반 UNIQUE 또는 PK면 발생하지 않는다. CR-02와 증상은 같아도 수정점이 nullability가 아니라 enum/type
집합이므로 별도 root cause다. 지원하지 않을 타입이면 DDL에서 명시적으로 거부해야 한다.

### CR-04 [High] filtered/online UNIQUE를 전 행 RK로 선택한다

최소 schema는 PK 없이 filtered NN UNIQUE만 가진 ON table이다.

```sql
CREATE TABLE t (id INT NOT NULL, active INT) REPLICATION=OFF;
CREATE UNIQUE INDEX uk_t_id ON t(id) WHERE active=1;
ALTER TABLE t REPLICATION=ON;
INSERT INTO t VALUES (10,0);
```

```c
/* src/transaction/locator_sr.c:7861-7875
 * locator_add_or_remove_index_internal
 */
if (or_pred && or_pred->pred_stream) {
  locator_eval_filter_predicate (..., &ev_res);
  if (ev_res != V_TRUE)
    continue;  /* replication block(8039+)보다 먼저 건너뜀 */
}
```

INSERT/DELETE는 predicate 밖 행에서 log가 없어진다. UPDATE는 더 나쁘다.

```c
/* src/transaction/locator_sr.c:8428-8433 — locator_update_force
 * filter 평가 전에 RK index를 선점한다.
 */
if (rk_btid_index == -1 && or_is_replication_candidate_key (index))
  rk_btid_index = i;

/* src/transaction/locator_sr.c:8467-8480,8782-8817
 * old/new가 모두 filter 밖이어도 rk_btid_index가 남아 old key log를 만든다.
 */
if (old_filter != V_TRUE && new_filter != V_TRUE) continue;
...
repl_old_key = heap_attrvalue_get_key (..., rk_btid_index, old_recdes, ...);
repl_log_insert (..., RVREPL_DATA_UPDATE, repl_old_key, ...);
```

slave는 filtered index에 존재하지 않는 key로 행을 찾아 apply가 실패한다. filter true 행 또는 별도 PK가
첫 RK면 발생하지 않는다. `or_is_replication_candidate_key()`는 filter와 online-build status를 검사하지
않으므로 publish가 끝나지 않은 index도 같은 범주다. filtered/building index를 RK에서 제외해야 한다.

### CR-06 [High] multi ALTER가 현재 clause 대신 첫 clause만 보고 RK 검사를 결정한다

```sql
CREATE TABLE t (
  id INT NOT NULL,
  CONSTRAINT u_t_id UNIQUE(id)
) REPLICATION=ON;
ALTER TABLE t ADD COLUMN note VARCHAR(10), DROP CONSTRAINT u_t_id;
```

```c
/* src/query/execute_schema.c:1829-2073 — do_alter */
for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next) {
  const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;
  ...
  /* BUG: 현재 alter_code가 아니라 statement head인 alter를 반복 검사 */
  if (!need_check_repl_constraint
      && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
    need_check_repl_constraint = true;
}
```

첫 ADD COLUMN은 관련 절이 아니어서 flag가 false로 남고, 뒤 DROP은 실행되지만 final
`check_ha_repl_constraint()`가 호출되지 않는다. RK 0개 schema가 commit된 뒤 DML은 log를 만들지 못한다.
clause 순서를 DROP→ADD로 바꾸면 같은 최종 schema가 거부되는 것이 대조 증거다. 현재 `alter_code`를
검사하고 모든 clause 순열을 회귀 시험해야 한다. #7370 inline review에도 있었지만 HEAD에 남아 있다.

### CR-07 [High] standalone DROP INDEX 등 RK mutation entry point가 final 검사 밖에 있다

```sql
CREATE TABLE t (
  id INT NOT NULL,
  CONSTRAINT uk_t_id UNIQUE(id)
) REPLICATION=ON;
DROP INDEX uk_t_id ON t;
INSERT INTO t VALUES (1);
```

```text
/* src/parser/csql_grammar.y — standalone DROP [UNIQUE] INDEX grammar
 * src/query/execute_schema.c:3590-3646 — do_drop_index
 */
PT_DROP_INDEX
  -> do_drop_index()
  -> create_or_drop_index_helper(..., DO_INDEX_DROP)
  -> 성공 반환
  -> check_ha_repl_constraint() 호출 없음
```

DDL SBR로 양 노드가 index를 제거한 뒤 master INSERT는 RK가 없어 log를 만들지 않는다. 다른 PK/NN UK가
있으면 문제없다. `IS_REPL_CONSTRAINT_RELATED_ALTER`에도 CHANGE/MODIFY와
`PT_DROP_INDEX_CLAUSE`가 빠져 있으므로 nullable 전환과 ALTER 내부 DROP INDEX도 함께 막아야 한다.
allowlist를 계속 늘리기보다 모든 schema mutation 성공 직전 ON class의 최종 representation을 검증하는
편이 안전하다.

### CR-09 [High] ON/OFF write target 혼합 SBR이 OFF target까지 재실행한다

최소 상태는 CUBRID가 지원하는 multi-table UPDATE 한 문장이 ON과 OFF table을 함께 수정하는 경우다.
`csql_grammar.y:7718-7777`의 `extended_table_spec_list`가 여러 target을 허용한다.

```sql
UPDATE /*+ USE_SBR */ on_t, off_t
   SET on_t.v=on_t.v+1, off_t.v=off_t.v+1
 WHERE on_t.id=off_t.id;
```

```text
/* src/query/execute_statement.c:3304-3348 — is_data_repl_log_enabled
 * src/query/execute_statement.c:3405-3423,4113-4130 — do_statement 계열
 * src/query/execute_statement.c:16502-16705 — do_replicate_statement
 */
ANY(write_target.replication == ON)
  -> 문장 전체 local RBR 억제
  -> 원본 SQL 하나를 SBR log로 기록
  -> slave가 ON/OFF target 전체를 다시 수정
```

모든 write target이 ON이거나 ON/OFF를 한 문장에 섞지 않으면 발생하지 않는다. mixed target SBR을
거부하거나 target별로 안전한 log 형식으로 분리해야 한다.

### CR-10 [High] OFF read source를 사용한 SBR이 ON target을 서로 다르게 만든다

```sql
CREATE TABLE src (id INT PRIMARY KEY, v INT) REPLICATION=OFF;
CREATE TABLE dst (id INT PRIMARY KEY, v INT) REPLICATION=ON;

-- master src=(1,100), slave src=(1,900)인 허용된 상태
INSERT /*+ USE_SBR */ INTO dst SELECT id,v FROM src WHERE id=1;
```

`is_data_repl_log_enabled()`은 INSERT target 또는 UPDATE/DELETE write target만 검사하고 read dependency는
보지 않는다. master는 `100`을 dst에 넣은 뒤 SQL text를 기록하고, slave는 자신의 OFF source `900`을
읽어 dst에 넣는다. OFF source가 양 노드에서 같거나 source도 ON이면 문제가 없다. SBR eligibility가
read dependency closure를 검사하거나 source value를 row image로 고정해야 한다.

### CR-11 [High] OFF table의 TRUNCATE가 slave에도 적용된다

```sql
CREATE TABLE local_cache (id INT PRIMARY KEY, v INT) REPLICATION=OFF;
TRUNCATE TABLE local_cache;
```

```c
/* src/query/execute_statement.c:342-383 — truncate_need_repl_log */
cons = classobj_find_cons_replication_key (class_->constraints);
if (cons != NULL)
  return true;  /* class의 ON/OFF는 확인하지 않음 */
```

PT_TRUNCATE가 이를 통과하면 `do_replicate_statement()`가 원본 SQL을 기록하고 slave server도 truncate한다.
같은 OFF table에 RK가 없으면 우연히 log가 생기지 않는 것이 대조 조건이다. develop에도 PK 기반
TRUNCATE SBR은 있지만 class별 OFF가 없어 이 계약 위반은 feature 상호작용이다. RK 검사보다 먼저
target class의 replication flag를 확인해야 한다.

### CR-14 [High] rkcheck가 결과 파일 open 실패 후 NULL stream을 사용한다

최소 상태는 DB 접속은 성공하지만 log directory가 read-only, full 또는 FD 고갈 상태인 경우다.

```c
/* src/executables/util_cs.c:2856-2863 — open_violation_list_file */
return fopen (file_path, "w");
```

```c
/* src/executables/util_cs.c:3320-3333 — rkcheck */
fp = open_violation_list_file (...);
classes = db_get_all_classes ();
...
PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);
```

`fp == NULL` 검사가 없어 EACCES/ENOSPC/EMFILE에서 위반 결과를 반환하기 전에 NULL stream을 사용한다.
writable directory면 발생하지 않는다. `fopen` 직후 errno 기반 명시 오류로 종료하고 heartbeat start가
constraint violation과 output I/O failure를 구분하게 해야 한다. #7370 review 뒤에도 남아 있다.

### PERF-01 [Low] OFF class는 RK 후보 수만큼 class record를 다시 읽는다

```c
/* src/transaction/locator_sr.c:8039-8057
 * locator_add_or_remove_index_internal
 */
if (... && !replicated && or_is_replication_candidate_key (index)) {
  bool repl_on = false;
  error_code = heap_get_class_repl_on (thread_p, class_oid, &repl_on);
  if (error_code == NO_ERROR && repl_on) {
    repl_log_insert (...);
    replicated = true;
  }
}
```

```c
/* src/storage/heap_file.c:11075-11115 — heap_get_class_repl_on */
heap_scancache_quick_start_root_hfid (...);
heap_get_class_record (..., PEEK);
*repl_on = or_class_is_replication_on (&recdes);
heap_scancache_end (...);
```

ON class는 첫 log 뒤 `replicated=true`가 되어 반복을 멈추지만 OFF class는 false가 유지되어 PK와 여러
NN UNIQUE 후보마다 같은 catalog record를 fetch한다. bulk DML 비용이 row 수×후보 수로 증가한다.
class flag를 index loop 밖에서 한 번 읽으면 된다. 이는 helper가 교체되지 않았다는 문제가 아니다.
사용자가 요청한 `heap_get_class_repl_on()` 교체를 가정해도 호출 배치가 남는다. #7697은 error propagation을
해결했지만 이 반복 호출은 현재 HEAD에도 있다.

## 5. 조건부 finding

### CR-13 [조건부 High] invalid RK의 무로그 DML을 promotion의 applier-done gate가 감지하지 못한다

이 항목은 “promotion에 rkcheck가 없다”만으로 성립하지 않는다. 기존 코드에는 이미 log applier가 done인지
확인하는 gate가 있다. 다음 선행 상태가 모두 필요하다.

```sql
-- CR-07로 양 노드에 DDL SBR 적용, 마지막 RK 제거
DROP INDEX uk_t_id ON t;

-- master에서 성공하지만 RK가 없어 row log가 생성되지 않음
INSERT INTO t VALUES (100);

-- source 장애 후 standby promotion
```

```c
/* src/connection/server_support.c:1885-1967 — css_change_ha_server_state */
state = css_transit_ha_server_state (..., HA_SERVER_STATE_ACTIVE);
if (css_check_ha_log_applier_done ())
  state = css_transit_ha_server_state (..., HA_SERVER_STATE_ACTIVE);
if (state == HA_SERVER_STATE_ACTIVE)
  logtb_enable_update (thread_p);
```

DDL까지는 slave에 왔지만 다음 DML log는 애초에 없으므로 standby는 “받은 로그를 모두 적용한” done
상태다. promotion은 `(100)`이 없는 노드를 ACTIVE로 만들 수 있다. CR-06/07을 막으면 이 최소 경로는
사라진다. 따라서 독립 root cause로 확정 집계하지 않고, promotion 전에 server-side RK/FK readiness를
재검사하는 defense-in-depth 항목으로 남긴다. 자동 restart와 failback의 단순 rkcheck 부재는 이 항목에
병합했고, 정상 catalog를 재시작하는 경우는 결함으로 보지 않았다.

### CR-15 [조건부 Medium] 손상·legacy FK metadata에서 rkcheck가 PK NULL을 역참조할 수 있다

```text
/* src/query/execute_schema.c:9818-9840 — log_ha_repl_fk_ref_all_replicated
 * src/executables/util_cs.c:2913 — check_fk_constraint caller
 */
pk_c = classobj_find_cons_primary_key (referenced_constraints)
diagnostic(fp, pk_c->name)  // pk_c NULL 방어 없음
```

정상 DDL로 만든 FK는 참조 PK 존재를 보장하므로 일반 SQL 재현은 되지 않는다. 하지만 catalog 손상,
legacy migration 또는 불완전 복구에서 FK metadata만 남으면 이상 상태를 진단해야 할 rkcheck가 crash할
수 있다. 정상 FK/PK fixture가 대조 조건이다. malformed catalog에서 constraint name 대신 명시적
catalog inconsistency를 출력하도록 NULL-safe 처리해야 한다.

## 6. develop 기존/feature 악화

### CR-12 [Major] HA start 실패 뒤 이미 시작한 process를 rollback하지 않는다

```text
cubrid heartbeat start
DB1 server: success
DB2 server: success
DB1 rkcheck: success
DB2 rkcheck: failure
결과: command failure, 먼저 시작된 server는 남을 수 있음
```

```c
/* src/executables/util_service.c:3947-4008 — us_hb_process_start */
status = us_hb_server_start (...);
if (status != NO_ERROR) goto ret;
status = us_hb_process_rkcheck (...);
if (status != NO_ERROR) goto ret;
status = us_hb_copylogdb_start (...);
...
ret:
  da_destroy (pids);  /* 추적 배열만 파기, server stop/rollback 없음 */
  return status;
```

develop도 server start 뒤 copylogdb/applylogdb 실패를 rollback하지 않는 동일 구조다. feature는 그 사이에
rkcheck라는 새 실패 지점을 추가했다. 따라서 원문을 지우지 않되 “feature 신규”로 세지 않는다. 이번
invocation이 시작한 process ownership을 기록해 실패 시 역순 정리하고, 다중 DB 중간 실패와 반복 start를
시험해야 한다.

## 7. 운영 권고

### OPS-01 [Low] 같은 분에 rkcheck를 재실행하면 직전 진단 파일을 덮어쓴다

```c
/* src/executables/util_cs.c:2839-2863
 * generate_violation_list_file_name / open_violation_list_file
 */
snprintf (..., "%s_%s_%04d%02d%02d_%02d%02d.list", ...); /* 초 없음 */
return fopen (file_path, "w");                            /* 기존 파일 truncate */
```

동일 DB의 rkcheck를 같은 분 안에 다시 실행하면 수정 전/후 비교에 필요한 첫 위반 목록이 사라진다.
다음 분에 실행하면 발생하지 않는다. 데이터 정합성 결함은 아니므로 확정 10건과 분리했다. 파일명에
초·PID를 포함하거나 exclusive create/rotation 정책을 적용하는 것이 안전하다.

## 8. 채택하지 않은 주요 의견과 이유

| 후보 | 최종 상태 | 이유 |
|---|---|---|
| CR-05 첫 RK identity | 입증 보류 | log에 identity가 없는 설계 위험은 사실이나 같은 HA history에서 node별 logical index order가 갈리는 최소 경로 미입증 |
| CR-08 partition promotion | 오분석/CR-02 종속 | runtime constraint는 property에서 재구성되고 정상 ON root의 PK/UNIQUE property가 남음 |
| CR-16 helper 미교체 | 리뷰 전제에서 제외 | 후속 반영 예정인 `heap_get_class_repl_on()` 교체가 적용됐다고 가정 |
| CR-17 public error code | 오분석 | public 설치 대상 `error_code.h`를 `dbi.h`와 `dbi_compat.h`가 include |
| ALTER VCLASS REPLICATION | 정책/품질 | 의미 없는 flag metadata는 가능하지만 row replication failure 없음 |
| stale backup의 pre-apply rkcheck | 정책/조건부 | future repair DDL 적용 전 자동 start가 막힐 수 있으나 공식 rejoin/readiness 계약 확인 필요 |
| OFF child→ON parent CASCADE | 정책 | slave parent apply가 cascade를 다시 실행해 FK 정합성은 유지됨 |
| function UNIQUE 전체 | 판정 불가 | expression이 양 노드에서 동일 평가될 수 있어 filtered index 실패를 일반화할 수 없음 |
| class flag 값 32 | 유지보수 위험 | 현재 enum과 일치해 현 HEAD 실행 오류 없음 |
| generation/epoch/quorum 일반론 | 코드 리뷰 범위 밖 | 중요한 스펙 주제지만 feature diff의 특정 실행 결함으로 연결되지 않음 |

## 9. failover·failback·restart 운영 결론

| 상태 전이 | 확인 결과 |
|---|---|
| 최초 start | server→rkcheck→copy→apply 순서. 중간 실패 rollback은 CR-12 |
| server/copy/apply crash restart | heartbeat가 argv로 재실행. 정상 catalog라면 rkcheck 재호출 부재 자체는 결함 아님 |
| standby→ACTIVE | applier-done gate와 write enable 존재. CR-13의 선행 무로그 상태만 별도 방어 필요 |
| ACTIVE→STANDBY failback | 신규 client 차단과 기존 client drain 존재. feature가 직접 깨뜨린 독립 경로 없음 |
| stale backup rejoin | local catalog를 apply 전에 검사해 future repair DDL까지 못 갈 수 있는 정책 후보가 남음 |
| 반복 start | partial process 상태(CR-12)와 진단 파일 overwrite(OPS-01)를 확인 |
| OFF child cascade | slave parent apply도 cascade를 수행해 정합성은 유지. OFF 의미의 제품 계약만 필요 |

## 10. 수정 우선순위와 수용 기준

1. RK 후보 정의를 하나로 통합한다: PK/UNIQUE type, 모든 컬럼 NOT NULL, filter 없음, normal/published
   status를 client/server/rkcheck/apply가 공유해야 한다.
2. 모든 schema mutation의 최종 ON class representation을 한 지점에서 검사한다. multi ALTER 절 순서와
   standalone DROP INDEX가 같은 validator를 지나야 한다.
3. SBR 안전성은 write target뿐 아니라 전체 read/write dependency의 ON/OFF를 검증한다. OFF TRUNCATE는
   log가 없어야 한다.
4. rkcheck의 파일 I/O와 malformed catalog를 명시적 오류로 처리한다.
5. HA start rollback과 promotion defense-in-depth를 운영 회귀 시험에 넣는다.
6. OFF class flag는 row/index loop 밖에서 한 번만 fetch한다.

필수 E2E 회귀는 다음 결과를 동시에 확인해야 한다.

- DDL/rkcheck 승인 여부와 master row-log 생성 여부가 모든 RK 후보 조합에서 같다.
- 승인된 DML 뒤 master/slave row checksum이 같다.
- 거부 대상 filtered/reverse/mixed-null/online 후보는 DDL 또는 RK 선택 단계에서 일관되게 거부된다.
- multi ALTER clause 순서를 바꿔도 같은 최종 schema는 같은 결과를 낸다.
- ON/OFF 혼합 SBR은 안전하게 거부·분리되고 OFF TRUNCATE는 slave에 도달하지 않는다.
- log directory EACCES/ENOSPC/EMFILE에서 crash 없이 구분 가능한 error를 반환한다.
- 다중 DB start의 어느 단계에 fault를 넣어도 invocation 전 상태로 되돌아간다.
- invalid RK 선행 상태에서는 standby가 ACTIVE/write-enabled 상태가 되지 않는다.

## 11. 감사 추적 자료

팀 공유에는 이 문서만 필요하다. 기존 187개 관찰과 develop 기존·후속 해결·오분석 기록은 삭제하지
않고 아래 내부 자료에 보존했다. 동일 코드 지점·불변식·수정 위치인 관찰만 하나로 병합했다.

- `reports/RAW_187_REAUDIT_MAP.md`: 187개 관찰의 최신 상태 색인
- `reports/E2E_FINDING_WORKSHEETS.md`: 최소 입력과 실행 순서 상세
- `reports/CANDIDATE_AUDIT.md`: 집계와 비채택 근거
- `reports/PR_HISTORY.md`: PR 도입·후속 해결 이력
- `reports/RAW_FULL_REAUDIT.md`: 세션 체크포인트와 35개 파일 coverage

## 12. 분석 한계

- 이 결과는 정적 E2E control-flow 검증이다. 두 노드 CUBRID HA 환경에서 SQL fixture를 실제 실행한
  결과가 아니므로 수정 PR에서는 위 수용 기준의 통합 테스트가 필요하다.
- CR-09의 구체 SQL은 parser의 multi-table UPDATE 경로를 확인했지만 두 노드 HA fixture에서 실행하지는
  않았다.
- PERF-01은 호출 횟수의 코드상 상한을 확인했지만 wall-clock benchmark는 수행하지 않았다.
- feature source는 수정하지 않았고 detached HEAD는 clean 상태를 유지했다.
