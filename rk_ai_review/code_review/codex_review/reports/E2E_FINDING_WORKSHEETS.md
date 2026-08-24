# CBRD-26246 E2E 후보 검증 작업표

- 대상: `feature/CBRD-26246-develop@9e094324b8ef`
- 기준: `upstream/develop@5b9c0d8155f8`
- 목적: 코드 좌표만 보고 결함을 추정하지 않고, 실제로 그 분기에 진입하는 입력과
  master → replication log → applylogdb → slave 결과를 고정한다.
- 상태 표기: `확정`, `조건부`, `오분석`, `develop 기존/feature 악화`, `운영 권고`

## E2E-01 / CR-02 — mixed-null 복합 UNIQUE가 승인되지만 master가 로그를 만들지 않는다

- 판정: **확정 / High / feature 신규**
- 최소 내부 상태: HA enabled, class `REPLICATION=ON`, PK 없음, 유일한 UNIQUE의 컬럼 중 일부만
  NOT NULL이다.
- schema/data:

```sql
CREATE TABLE t (
  a INT NOT NULL,
  b INT,
  UNIQUE (a, b)
) REPLICATION=ON;
INSERT INTO t VALUES (1, 10);
```

- 문제 코드:

```c
/* src/query/execute_schema.c:109-114 — IS_HA_REPLICATION_KEY_CONSTRAINT
 * src/object/schema_manager.c — sm_has_non_null_attribute
 * client CREATE/ALTER/rkcheck: 한 컬럼이라도 NOT NULL이면 승인(ANY).
 */
SM_IS_CONSTRAINT_UNIQUE_FAMILY (c->type)
  && sm_has_non_null_attribute (c->attributes);
```

```c
/* src/base/object_representation_sr.c:4694-4723
 * or_is_replication_candidate_key
 * master와 slave server 공통 runtime: 모든 컬럼이 NOT NULL이어야 승인(ALL).
 */
for (int i = 0; i < index->n_atts; i++)
  if (index->atts[i] == NULL || !index->atts[i]->is_notnull)
    return false;
```

- 실행 순서:
  1. client DDL 검사는 `UNIQUE(a,b)`를 RK로 승인한다.
  2. master INSERT의 `locator_add_or_remove_index_internal()`이 server predicate를 호출한다.
  3. `b`가 nullable인 schema이므로 후보가 false가 된다. row 값이 현재 non-NULL인지는 관계없다.
  4. 다른 후보가 없으므로 `repl_log_insert()`가 호출되지 않는다.
  5. applylogdb가 받을 row log가 없으므로 slave server도 호출되지 않는다.
  6. master에만 `(1,10)`이 남는다.
- 무결함 대조 조건: `a`와 `b`를 모두 NOT NULL로 만들거나 PK를 별도로 두면 master가 RK log를 만든다.
- develop 비교: develop은 PK-only라 이 UNIQUE를 RK로 승인하는 신규 경로가 없다.
- 기존 오분석 교정: client와 **applier**가 서로 다른 판정을 해 apply가 실패하는 문제가 아니다.
  master runtime이 먼저 같은 server predicate에서 탈락하여 log 자체가 없다.

## E2E-02 / CR-03 — REVERSE UNIQUE도 같은 master 무로그 상태를 만든다

- 판정: **확정 / High / feature 신규**
- 최소 내부 상태: HA enabled, ON class, PK·일반 UNIQUE 없음, NOT NULL REVERSE UNIQUE만 존재.
- 최소 입력:

```sql
CREATE TABLE t (a INT NOT NULL, REVERSE UNIQUE (a)) REPLICATION=ON;
INSERT INTO t VALUES (1);
```

- 코드 차이:

```c
/* src/object/class_object.h — SM_IS_CONSTRAINT_UNIQUE_FAMILY
 * client는 SM_CONSTRAINT_REVERSE_UNIQUE를 UNIQUE family에 포함한다.
 */
UNIQUE || PRIMARY_KEY || REVERSE_UNIQUE
```

```c
/* src/base/object_representation_sr.c:4694-4709
 * or_is_replication_candidate_key
 * server는 PK 또는 BTREE_UNIQUE만 허용한다.
 */
if (index->type == BTREE_PRIMARY_KEY) return true;
if (index->type != BTREE_UNIQUE) return false;
```

- 실행 순서: DDL/rkcheck 승인 → master runtime에서 reverse type 탈락 → row log 없음 → applier 미호출 →
  slave에 INSERT 없음.
- 무결함 대조 조건: 동일 컬럼을 일반 UNIQUE 또는 PK로 정의한다.
- CR-02와 분리한 이유: 증상은 같지만 수정해야 할 root cause가 nullability quantifier가 아니라
  지원 enum 집합이다.

## E2E-03 / CR-04A — filtered UNIQUE 밖의 INSERT/DELETE는 로그가 없다

- 판정: **확정 / High / feature 신규**
- 최소 내부 상태: ON class, PK 없음, 유일 RK 후보가 filtered NOT NULL UNIQUE, 입력 행은 predicate false.
- 최소 입력(문법은 CUBRID filtered-index 문법에 맞게 조정):

```sql
CREATE TABLE t (id INT NOT NULL, active INT) REPLICATION=OFF;
CREATE UNIQUE INDEX uk_t_id ON t(id) WHERE active = 1;
ALTER TABLE t REPLICATION=ON;
INSERT INTO t VALUES (10, 0);
```

- 문제 코드:

```c
/* src/transaction/locator_sr.c:7861-7875
 * locator_add_or_remove_index_internal
 */
if (or_pred && or_pred->pred_stream) {
  locator_eval_filter_predicate (..., &ev_res);
  if (ev_res != V_TRUE)
    continue;  /* replication block(8040+)보다 먼저 다음 index로 감 */
}
```

```c
/* src/base/object_representation_sr.c:4694-4723
 * or_is_replication_candidate_key
 * filter_predicate와 index_status를 검사하지 않는다.
 */
return type_is_pk_or_unique && all_attributes_not_null;
```

- 실행 순서: DDL은 UK를 RK로 인정 → master는 행을 heap에 넣음 → filter false라 index loop가
  replication block 전에 continue → log 없음 → slave 미변경.
- DELETE도 동일하게 predicate 밖 행의 index entry가 없어 같은 분기를 탄다.
- 무결함 대조 조건: `active=1`인 행 또는 filter 없는 PK/UNIQUE를 사용한다.
- 추가 상태: online-build 중인 UNIQUE도 후보 predicate가 status를 거르지 않아 완성되지 않은 index를
  RK로 선택할 수 있다.

## E2E-04 / CR-04B — filtered UNIQUE 밖의 UPDATE는 존재하지 않는 old key를 기록할 수 있다

- 판정: **확정 / High / CR-04의 동일 root cause**
- 최소 상태: 위 schema에서 기존 행 `(10,0)`을 UPDATE하며 다른 RK 후보가 없다.
- 최소 입력:

```sql
UPDATE t SET active = 0 WHERE id = 10;
-- 또는 predicate false → true/true → false 전환 조합을 각각 시험한다.
```

- 문제 코드:

```c
/* src/transaction/locator_sr.c:8428-8433 — locator_update_force
 * filter를 평가하기 전에 RK index 위치를 저장한다.
 */
if (rk_btid_index == -1 && or_is_replication_candidate_key (index))
  rk_btid_index = i;
```

```c
/* src/transaction/locator_sr.c:8467-8480,8782-8817 — locator_update_force
 * old/new predicate가 모두 false여도 index 선택값은 남는다.
 */
if (old_filter != V_TRUE && new_filter != V_TRUE)
  continue;
...
if (rk_btid_index != -1) {
  repl_old_key = heap_attrvalue_get_key (..., rk_btid_index, old_recdes, ...);
  repl_log_insert (..., RVREPL_DATA_UPDATE, repl_old_key, ...);
}
```

- 실행 순서: master가 filtered index를 RK로 선점 → 실제 index update는 건너뜀 → fallback이 old row에서
  key 값 `10`을 만들어 UPDATE log 기록 → slave가 자신의 filtered UNIQUE에서 key `10`을 찾음 →
  predicate 밖 행에는 index entry가 없어 lookup/apply 실패.
- 무결함 대조 조건: filter true인 행 또는 별도 PK를 첫 RK로 둔다.

## E2E-05 / CR-06 — multi ALTER가 첫 clause 순서에 따라 마지막 RK 제거를 허용한다

- 판정: **확정 / High / feature 신규**
- 최소 상태: HA enabled, ON class, RK 후보가 하나뿐이다.
- 최소 입력:

```sql
CREATE TABLE t (
  id INT NOT NULL,
  CONSTRAINT u_t_id UNIQUE(id)
) REPLICATION=ON;
ALTER TABLE t ADD COLUMN note VARCHAR(10), DROP CONSTRAINT u_t_id;
```

- 문제 코드:

```c
/* src/query/execute_schema.c:1829-2073 — do_alter
 * loop의 현재 값 alter_code를 만들었지만 2051에서 head node를 검사한다.
 */
for (crt_clause = alter; crt_clause != NULL; crt_clause = crt_clause->next) {
  const PT_ALTER_CODE alter_code = crt_clause->info.alter.code;
  ...
  if (!need_check_repl_constraint
      && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))
    need_check_repl_constraint = true;
}
```

- 실행 순서: 첫 ADD COLUMN은 관련 allowlist가 아님 → 뒤 DROP CONSTRAINT 실행 → 검사 flag는 계속 false →
  statement final `check_ha_repl_constraint()` 미호출 → RK 0개 schema commit → 이후 master DML은 row log 없음.
- 무결함 대조 조건: clause 순서를 `DROP CONSTRAINT ..., ADD COLUMN ...`로 바꾸면 head가 관련 절이라 최종
  검사가 실행되고 같은 최종 schema가 거부된다. 이 순서 의존성이 결함의 직접 대조 증거다.

## E2E-06 / CR-07 — standalone DROP INDEX가 마지막 RK를 제거한다

- 판정: **확정 / High / feature 신규**
- 최소 상태: ON class의 유일 RK가 constraint-backed NOT NULL UNIQUE index다.
- 최소 입력:

```sql
CREATE TABLE t (
  id INT NOT NULL,
  CONSTRAINT uk_t_id UNIQUE(id)
) REPLICATION=ON;
DROP INDEX uk_t_id ON t;
INSERT INTO t VALUES (1);
```

- 코드 흐름:

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

- 실행 순서: DDL SBR은 양 노드에서 index를 제거 → ON class가 RK 0개가 됨 → master INSERT는 후보를
  못 찾아 row log를 만들지 않음 → slave 누락.
- 무결함 대조 조건: DROP 전에 다른 PK/NN UNIQUE를 추가하거나, DROP 성공 후 final validator를 호출한다.
- 추가 coverage 공백: `IS_REPL_CONSTRAINT_RELATED_ALTER`에는 CHANGE/MODIFY 및
  `PT_DROP_INDEX_CLAUSE`도 빠져 있어 nullable 전환과 ALTER 내부 DROP INDEX를 함께 회귀 시험해야 한다.

## E2E-07 / CR-09 — ON/OFF write target 혼합 SBR이 OFF table까지 복제한다

- 판정: **확정 / High / feature 신규 상호작용**
- 최소 상태: 한 문장이 ON과 OFF table을 모두 수정하며 SBR 경로를 사용한다.
- 의사 입력:

```sql
-- 실제 지원되는 multi-target UPDATE/DELETE 문법 또는 VCLASS write 변환으로 구성
UPDATE /*+ USE_SBR */ on_t, off_t
   SET on_t.v = on_t.v + 1,
       off_t.v = off_t.v + 1
 WHERE on_t.id = off_t.id;
```

- 문제 코드:

```text
/* src/query/execute_statement.c:3304-3348 — is_data_repl_log_enabled
 * write target 중 하나라도 ON이면 true를 반환한다.
 * src/query/execute_statement.c:3405-3423,4113-4130 — do_statement 계열
 * 문장 전체의 local RBR을 억제한다.
 * src/query/execute_statement.c:16502-16705 — do_replicate_statement
 * 원본 SQL 하나를 SBR로 기록한다.
 */
ANY(write_target.replication == ON)
  -> suppress RBR for whole statement
  -> replicate original SQL for all targets
```

- 실행 순서: master가 두 target 모두 변경 → ANY-ON이므로 원본 SQL 기록 → slave가 SQL 전체 재실행 →
  OFF target까지 변경. OFF의 “직접 DML을 복제하지 않는다”는 실행 의미와 충돌한다.
- 무결함 대조 조건: 모든 write target이 ON이거나 문장이 ON/OFF target을 함께 수정하지 않는다.
- CR-10과 분리 이유: 이 항목은 write set 경계 문제이며, CR-10은 read dependency가 노드별로 다른 문제다.

## E2E-08 / CR-10 — OFF read source에 의존한 SBR 결과가 노드마다 달라진다

- 판정: **확정 / High / feature 신규 상호작용**
- 최소 상태: ON target과 OFF source가 있고 OFF source의 데이터가 master/slave에서 다르다.
- 최소 입력:

```sql
CREATE TABLE src (id INT PRIMARY KEY, v INT) REPLICATION=OFF;
CREATE TABLE dst (id INT PRIMARY KEY, v INT) REPLICATION=ON;

-- master src: (1,100), slave src: (1,900)인 허용된 OFF 상태
INSERT /*+ USE_SBR */ INTO dst
SELECT id, v FROM src WHERE id = 1;
```

- 코드 흐름:

```text
/* src/query/execute_statement.c:3304-3348 — is_data_repl_log_enabled
 * INSERT는 target, UPDATE/DELETE는 write target만 replication flag를 검사한다.
 * src/query/execute_statement.c:16502-16705 — do_replicate_statement
 */
dst == ON -> original INSERT...SELECT SQL을 SBR로 기록
read source src == OFF -> dependency set에는 포함되지 않음
```

- 실행 순서: master는 OFF source 값 `100`으로 dst를 생성 → SQL text가 slave로 전달 → slave는 자신의
  OFF source 값 `900`을 다시 읽어 dst 생성 → ON target이 서로 달라짐.
- 무결함 대조 조건: source가 ON이어서 양 노드 데이터가 같거나, OFF source snapshot/value를 row image로
  기록하거나, 양 노드 OFF 데이터가 우연히 같다.

## E2E-09 / CR-11 — OFF table의 TRUNCATE가 slave에서도 실행된다

- 판정: **확정 / High / feature 신규 상호작용**
- 최소 상태: OFF class에 PK 또는 NN UNIQUE RK가 있고 master/slave에 서로 보존해야 할 데이터가 있다.
- 최소 입력:

```sql
CREATE TABLE local_cache (id INT PRIMARY KEY, v INT) REPLICATION=OFF;
TRUNCATE TABLE local_cache;
```

- 문제 코드:

```c
/* src/query/execute_statement.c:342-383 — truncate_need_repl_log
 * RK 존재만 확인하고 class replication flag를 확인하지 않는다.
 */
cons = classobj_find_cons_replication_key (class_->constraints);
if (cons != NULL)
  return true;
```

```text
/* src/query/execute_statement.c:16502-16705 — do_replicate_statement
 * PT_TRUNCATE가 위 predicate를 통과하면 원본 TRUNCATE를 SBR로 기록한다.
 */
```

- 실행 순서: master OFF table truncate → RK가 있으므로 SQL log 생성 → applylogdb가 slave server에
  TRUNCATE 실행 요청 → slave의 독립 OFF 데이터도 삭제.
- 무결함 대조 조건: 같은 OFF table에 RK가 없으면 현재 코드는 우연히 log를 만들지 않는다. ON/OFF가
  아니라 RK 유무가 결과를 바꾸는 것이 결함의 직접 증거다.
- develop 비교: develop에도 PK 기반 TRUNCATE SBR은 있지만 class별 OFF 상태가 없으므로 이 조합은 없다.

## E2E-10 / CR-12 — HA start 중 실패해도 먼저 시작한 프로세스를 rollback하지 않는다

- 판정: **develop 기존 / feature 악화 / 운영 Major**
- 최소 상태: heartbeat 설정에 여러 DB가 있거나, server start는 성공하지만 rkcheck/copy/apply 중 하나가 실패.
- 의사 입력:

```text
cubrid heartbeat start
DB1 server start: success
DB2 server start: success
DB1 rkcheck: success
DB2 rkcheck: failure
```

- 문제 코드:

```c
/* src/executables/util_service.c:3947-4008 — us_hb_process_start
 * 성공한 단계의 pid/state ownership을 rollback하지 않는다.
 */
status = us_hb_server_start (...);
if (status != NO_ERROR) goto ret;
status = us_hb_process_rkcheck (...);
if (status != NO_ERROR) goto ret;
status = us_hb_copylogdb_start (...);
...
ret:
  da_destroy (pids);  /* 추적 배열만 파기 */
  return status;      /* server stop 또는 앞선 DB rollback 없음 */
```

- 실행 결과: command는 실패하지만 이미 시작된 DB server가 남는다. 관리자는 전체 HA가 내려갔다고
  오인할 수 있고 반복 start에서 already-running/stale 상태와 충돌한다.
- 무결함 대조 조건: 첫 server start 자체가 실패해 아무 프로세스도 시작되지 않았거나, 실패 시 역순으로
  이번 invocation이 시작한 process만 stop한다.
- develop 비교: develop에도 server→copy→apply 사이 rollback 부재가 있다. feature는 server 뒤에 rkcheck라는
  새 실패 지점을 추가했다. 따라서 finding을 삭제하지 않되 feature 순수 신규로 집계하면 안 된다.

## E2E-11 / CR-13 — invalid RK 상태의 누락 로그를 applier-done gate가 감지하지 못한다

- 판정: **조건부 확정 / High / CR-06·07 선행 결함 의존**
- 최소 상태: 두 노드에 DDL SBR이 적용되어 ON class의 마지막 RK가 제거됐고, 그 뒤 master DML이
  RK 부재로 로그 없이 성공했으며 source가 장애 난다.
- 최소 순서:

```sql
-- 양 노드에 DDL SBR 적용
DROP INDEX uk_t_id ON t;  -- CR-07 경로

-- master에서만 실행되고 RK가 없어 row log가 생기지 않음
INSERT INTO t VALUES (100);

-- source 장애 후 standby promotion
```

- promotion 코드:

```c
/* src/connection/server_support.c:1885-1967 — css_change_ha_server_state
 */
state = css_transit_ha_server_state (..., HA_SERVER_STATE_ACTIVE);
if (css_check_ha_log_applier_done ())
  state = css_transit_ha_server_state (..., HA_SERVER_STATE_ACTIVE);
if (state == HA_SERVER_STATE_ACTIVE)
  logtb_enable_update (thread_p);
```

- 실행 순서: DDL은 양 노드에 도착 → 이후 DML은 master에서 log 자체가 없음 → standby는 받은 log를
  모두 적용했으므로 `css_check_ha_log_applier_done()`을 만족 → promotion 시 RK/FK 재검사 없이 write enable →
  성공했던 row `(100)`이 없는 노드가 새 master가 됨.
- 무결함 대조 조건: CR-06/07을 막아 RK 0개 상태를 만들 수 없게 하거나, promotion gate가 catalog RK와
  데이터/schema readiness까지 확인한다.
- 범위 제한: 단순히 promotion 함수에 `rkcheck` 호출이 없다는 것만으로는 결함이 아니다. 기존 applier-done
  gate는 존재하며, 위처럼 log가 애초에 생성되지 않는 선행 경로가 있어야 실제 누락을 통과시킨다.

## E2E-12 / CR-14 — rkcheck 결과 파일 open 실패 뒤 NULL stream을 사용한다

- 판정: **확정 / High / feature 신규**
- 최소 상태: DB server 접속은 성공하지만 log directory가 read-only, 디스크 full, inode/FD 고갈 등으로
  결과 파일 `fopen()`이 실패한다.
- 문제 코드:

```c
/* src/executables/util_cs.c:2856-2863 — open_violation_list_file */
return fopen (file_path, "w");
```

```c
/* src/executables/util_cs.c:3320-3333 — rkcheck
 * fp == NULL 검사 없이 macro/fprintf 계열에 전달한다.
 */
fp = open_violation_list_file (...);
classes = db_get_all_classes ();
...
PRINT_SECTION_TITLE (fp, RK_CONSTRAINT_VIOLATIONS_SECTION_TITLE);
```

- 실행 결과: constraint 결과를 정상 오류로 반환하기 전에 NULL `FILE *`를 사용하는 undefined behavior로
  utility가 crash할 수 있다. heartbeat start는 실제 RK 위반과 진단 파일 생성 실패를 구분하지 못한다.
- 무결함 대조 조건: writable log directory 또는 `fp == NULL`에서 명시적 I/O error를 반환한다.
- PR 이력: #7370 inline review에 이미 지적됐으나 현재 HEAD에 남아 있다.

## E2E-13 / CR-15 — 손상·legacy FK metadata 진단 중 PK NULL을 역참조할 수 있다

- 판정: **조건부 / Medium / feature 신규**
- 최소 상태: FK metadata는 참조 class를 가리키지만 해당 class의 PK constraint가 catalog 손상, legacy
  migration 또는 불완전 복구로 존재하지 않는다.
- 코드 흐름:

```text
/* src/query/execute_schema.c:9818-9840 — log_ha_repl_fk_ref_all_replicated
 * referenced class constraint list에서 PK를 찾음
 * pk_c == NULL 방어 없이 pk_c->name을 진단 출력에 사용
 */
pk_c = classobj_find_cons_primary_key (referenced_constraints)
diagnostic(fp, pk_c->name)
```

- 실행 결과: 정상 DB에서는 FK 생성 규칙이 PK 존재를 보장하지만, 바로 그런 catalog 이상을 찾아야 하는
  readiness utility가 위반 목록 대신 crash할 수 있다.
- 무결함 대조 조건: 정상 DDL로 생성된 FK/PK metadata에서는 `pk_c != NULL`이라 발생하지 않는다.
- 최종 처리 원칙: 일반 사용자 SQL로 재현되는 정합성 결함과 같은 등급으로 세지 않고 손상 복구 진단의
  방어성 문제로 명시한다.

## E2E-14 / NEW-004 — 1분 내 rkcheck 재실행이 직전 진단 파일을 덮어쓴다

- 판정: **운영 권고 / Low / feature 신규**
- 최소 입력: 같은 database·utility를 같은 분 안에 두 번 실행한다.
- 문제 코드:

```c
/* src/executables/util_cs.c:2839-2863
 * generate_violation_list_file_name / open_violation_list_file
 */
snprintf (..., "%s_%s_%04d%02d%02d_%02d%02d.list", ...); /* 초 없음 */
return fopen (file_path, "w");                            /* truncate */
```

- 실행 결과: 첫 실패의 위반 목록을 수정 전/후 비교하려고 즉시 재실행하면 동일 경로가 truncate되어
  incident evidence가 사라진다.
- 무결함 대조 조건: 다음 분에 실행하거나 초·PID·exclusive-create/rotation을 파일명 정책에 포함한다.
- 범위: HA 데이터 정합성 오류는 아니므로 최종 핵심 결함과 분리한다.

## E2E-15 / NEW-008 — OFF class DML이 RK 후보 수만큼 class record를 다시 읽는다

- 판정: **확정된 코드 경로 / Low 성능 후보 / feature 신규**
- 최소 상태: OFF class에 PK와 여러 NN UNIQUE 후보가 있고 bulk INSERT/DELETE를 수행한다.
- 문제 코드:

```c
/* src/transaction/locator_sr.c:8039-8057
 * locator_add_or_remove_index_internal
 * helper가 RK 후보 조건 안에 있고 replicated는 OFF에서 끝까지 false다.
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
/* src/storage/heap_file.c:11075-11115 — heap_get_class_repl_on
 * 각 호출이 root HFID scan cache를 열고 class record를 fetch한다.
 */
heap_scancache_quick_start_root_hfid (...);
heap_get_class_record (..., PEEK);
or_class_is_replication_on (&recdes);
heap_scancache_end (...);
```

- 실행 순서: 첫 후보에서 OFF 확인 → `replicated=false` 유지 → 다음 후보에서도 동일 catalog fetch 반복 →
  row 수 × RK 후보 수에 비례한 catalog access.
- 무결함 대조 조건: ON class는 첫 성공 log 뒤 `replicated=true`여서 이후 helper 호출을 건너뛴다. class flag를
  index loop 밖에서 한 번 읽으면 OFF도 1회로 고정된다.
- 사용자 가정과의 관계: `heap_is_replication_class`를 `heap_get_class_repl_on`으로 교체했다고 가정한 뒤에도
  남는 호출 배치 문제다. 교체되지 않았다는 finding은 아니다.

## 독립 finding으로 채택하지 않는 운영·품질 후보

| 후보 | 판정 | E2E 대조 근거 |
|---|---|---|
| CR-05 첫 RK 후보 identity | 입증 보류 | log에 identity가 없다는 위험은 사실이나 같은 HA DDL history에서 두 노드의 logical index 순서가 달라지는 도달 경로를 확정하지 못함 |
| CR-08 partition promotion | 오분석/CR-02 종속 | runtime constraint/RK는 property에서 재구성되며 정상 ON root의 PK/UNIQUE property가 promotion 뒤 남음 |
| NEW-001 ALTER VCLASS REPLICATION | 품질/정책 | 무의미한 flag metadata는 저장 가능하지만 row replication 정합성 실패 경로 없음 |
| NEW-002 crash restart | CR-13 병합 | 정상 start를 통과한 동일 catalog 재시작에는 재검사 필요성이 없음 |
| NEW-003 failback | CR-13 병합 | 기존 client fencing/drain이 있으며 invalid catalog 선행 시에만 영향 |
| NEW-005 get_print_flags 선언 | 품질 | 정의·호출 없는 static prototype이며 runtime 경로 없음 |
| NEW-006 stale backup start gate | 정책/조건부 | local stale catalog를 apply 전에 검사해 self-block할 수 있으나 수동 copy/apply 절차와 의도된 readiness 순서 확인이 필요 |
| NEW-007 OFF child cascade | 정책 | slave의 parent apply가 FK cascade를 다시 수행해 정합성은 유지됨. OFF를 직접 로그 금지로 볼지 간접 변경 금지로 볼지 계약 문제 |
| CR-16 helper 미교체 | 사용자 요청 제외 | 모든 호출이 `heap_get_class_repl_on`으로 교체됐다고 가정 |
| CR-17 public error code | 오분석 | public 설치 대상 `error_code.h`를 `dbi.h`/`dbi_compat.h`가 include함 |
