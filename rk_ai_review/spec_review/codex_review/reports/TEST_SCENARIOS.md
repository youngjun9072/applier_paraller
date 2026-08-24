# CUBRID HA 복제 키 시험 시나리오

> **후속 필터링 주의:** 아래 시나리오는 원래 스펙 리뷰 범위를 보존한다. CUBRID가 지원하지 않는 topology·객체·병렬 apply 전제는 [CUBRID_FIT_FILTER_FEATURE.md](CUBRID_FIT_FILTER_FEATURE.md)의 판정에 따라 제외하고, 확정·판정불가 항목을 우선 시험한다.

- 대상 스펙: ../../user_spec/user_spec.html
- 근거: `reports/raw/`의 확장 원시 리뷰 691건
- 작성일: 2026-08-23
- 시나리오 수: 53개

## 1. 실행 원칙

이 문서에서 source는 현재 쓰기를 받는 primary, replica는 변경 로그를 적용하는 standby를 뜻한다. 실제 명령·오류 코드·fault injection 방법은 구현에서 확정해야 한다. 원문이 결과를 정하지 않은 경우 아래의 “기대 결과”는 데이터 정합성을 위한 **권고 수용 기준**이다.

공통으로 다음 값을 시험 전후 수집한다.

- 양 노드의 `SHOW CREATE TABLE`, REPLICATION 값, 활성 RK와 후보 목록
- source commit LSA, replica receive/flush/apply LSA와 schema/RK generation
- 행 수, RK 순서의 행별 checksum, FK 유효성, VIEW 결과
- `fail_count`, 고유 미해결 오류 수, 첫 오류 코드·테이블·LSA
- DDL 시간, lock wait, 임시 디스크, 로그 bytes, apply lag, CPU·메모리

각 SQL 블록의 제약 이름과 CUBRID 문법은 구현 확정 뒤 문서 실행 시험으로 고정한다. `...`를 그대로 사용해서는 안 된다.

## 2. 정상 동작

### [TS-N01] PK를 RK로 사용하는 ON 테이블의 기본 CRUD

- 목적: 가장 단순한 정상 경로에서 PK가 활성 RK가 되고 CRUD가 한 번씩 복제되는지 확인한다.
- 사전 조건: 동일 버전 2노드 HA, apply lag 0, `fail_count=0`.
- SQL·이벤트 순서:

```sql
CREATE TABLE account (
  id INT CONSTRAINT pk_account PRIMARY KEY,
  balance INT NOT NULL
) REPLICATION=ON;
INSERT INTO account VALUES (1,1000);
UPDATE account SET balance=900 WHERE id=1;
DELETE FROM account WHERE id=1;
```

- 기대 결과: 생성 뒤 활성 RK는 `pk_account(id)`다. 각 commit 뒤 replica가 같은 행 상태에 도달하며 DELETE 후 양쪽 모두 0행이다. 오류와 재시도는 없다.
- 검증 지표: 활성 RK ID/컬럼, apply LSA, 행 수·checksum, `fail_count=0`, 각 DML 적용 횟수 1.
- 연결된 원시 리뷰 ID: `DBDEV-1Y-01`, `DBDEV-5Y-01`, `USER-1Y-01`

### [TS-N02] PK 없는 테이블에서 하나의 NOT NULL UK 선택

- 목적: PK가 없을 때 유효한 UK가 RK가 되는 기본 우선순위를 확인한다.
- 사전 조건: HA 정상, `email` 중복·NULL 없음.
- SQL·이벤트 순서:

```sql
CREATE TABLE member (
  email VARCHAR(100) NOT NULL CONSTRAINT uq_member_email UNIQUE,
  name VARCHAR(50)
) REPLICATION=ON;
INSERT INTO member VALUES ('a@example.com','Kim');
UPDATE member SET name='Lee' WHERE email='a@example.com';
```

- 기대 결과: 활성 RK는 `uq_member_email(email)`이고 source/replica가 동일 제약 ID·컬럼 순서를 사용한다. UPDATE 결과는 양쪽에서 `Lee`다.
- 검증 지표: 후보·활성 RK 조회, 로그의 RK generation, checksum, `fail_count=0`.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-04`, `DBA-3Y-04`, `DBDEV-1Y-04`

### [TS-N03] 여러 UK의 결정적 선택과 재시작 지속성

- 목적: 여러 후보에서 선택이 결정적이고 재시작·failover로 바뀌지 않는지 확인한다.
- 사전 조건: PK 없음, 영구 RK 식별자 조회 가능.
- SQL·이벤트 순서:

```sql
CREATE TABLE employee (
  employee_no INT NOT NULL CONSTRAINT uq_emp_no UNIQUE,
  email VARCHAR(100) NOT NULL CONSTRAINT uq_emp_email UNIQUE
) REPLICATION=ON;
```

1. 양 노드에서 활성 RK를 조회한다.
2. replica와 source를 차례로 재시작한다.
3. failover 후 다시 조회하고 UPDATE/DELETE한다.

- 기대 결과: 스펙에서 확정한 tie-breaker 또는 source가 기록한 영구 ID에 따라 모든 단계에서 같은 RK가 유지된다. 노드가 독립적으로 다른 UK를 재선택하지 않는다.
- 검증 지표: 재시작 전후 RK ID·generation, DML 성공률, checksum.
- 연결된 원시 리뷰 ID: `PM-5Y-02`, `DBA-10년차-02`, `DBDEV-5Y-04`

### [TS-N04] PK에서 UK로 원자적 전환

- 목적: 새 UK를 준비한 뒤 PK를 제거할 때 중간 RK 공백 없이 전환되는지 확인한다.
- 사전 조건: `email`은 NOT NULL·유일, replica lag 0.
- SQL·이벤트 순서:

```sql
CREATE TABLE customer (
  id INT CONSTRAINT pk_customer PRIMARY KEY,
  email VARCHAR(100) NOT NULL CONSTRAINT uq_customer_email UNIQUE,
  state VARCHAR(20)
) REPLICATION=ON;
INSERT INTO customer VALUES (1,'a@x','A');
ALTER TABLE customer DROP CONSTRAINT pk_customer;
UPDATE customer SET state='B' WHERE email='a@x';
```

- 기대 결과: ALTER commit 전에는 PK, commit 후에는 UK가 활성 RK다. DDL과 후속 DML이 동일 순서로 적용되고 언제나 활성 RK가 하나 이상이다.
- 검증 지표: RK generation 전환 LSA, 양 노드 schema, UPDATE checksum, apply 오류 0.
- 연결된 원시 리뷰 ID: `PM-5Y-07`, `DBA-5Y-08`, `DBDEV-5Y-08`

### [TS-N05] UK에서 PK로 원자적 전환

- 목적: PK 추가 우선순위로 활성 RK가 UK에서 PK로 안전하게 바뀌는지 확인한다.
- 사전 조건: PK 없음, `email` UK가 현재 RK, 새 `id` 값은 유일·NOT NULL.
- SQL·이벤트 순서:

```sql
ALTER TABLE customer ADD COLUMN id INT;
UPDATE customer SET id=1 WHERE email='a@x';
ALTER TABLE customer ALTER COLUMN id SET NOT NULL,
  ADD CONSTRAINT pk_customer PRIMARY KEY(id);
UPDATE customer SET state='C' WHERE id=1;
```

- 기대 결과: id가 NULL인 중간 단계에는 후보가 아니며 기존 UK가 유지된다. 최종 ALTER가 성공한 commit에서 PK로 전환되고 과거 UK 로그도 적용 가능하다.
- 검증 지표: 단계별 후보/RK, NULL·중복 사전 검사, schema generation, checksum.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-07`, `사용자-5년차-08`, `DBDEV-5Y-07`

### [TS-N06] ON→OFF 정상 cutover와 OFF 로컬 데이터

- 목적: 전환 LSA 이전 DML은 복제되고 이후 DML만 제외되는 경계를 확인한다.
- 사전 조건: ON 테이블이 양 노드에서 동일, 전환 LSA 조회 가능.
- SQL·이벤트 순서:

```sql
UPDATE cache_data SET value='before' WHERE id=1;
ALTER TABLE cache_data REPLICATION=OFF;
UPDATE cache_data SET value='after' WHERE id=1;
```

- 기대 결과: replica에는 `before`, source에는 `after`가 남는다. ALTER는 명시된 barrier를 형성하고 이 의도된 차이가 감사 기록에 남는다.
- 검증 지표: cutover LSA, 이전/이후 log 포함 여부, 양 노드 값, 감사 event.
- 연결된 원시 리뷰 ID: `DBA-10년차-06`, `PM-5Y-38`, `DBDEV-5Y-03`

### [TS-N07] 파티션 테이블의 RK와 설정 상속

- 목적: 지원되는 파티션 객체에서 전역 행 식별과 새 파티션의 설정 상속을 검증한다.
- 사전 조건: 대상 버전의 파티션 문법·global/local unique 지원을 먼저 확정한다.
- SQL·이벤트 순서:

```sql
-- 실제 지원 문법으로 치환
CREATE TABLE sales (
  month_id INT NOT NULL,
  sale_id BIGINT NOT NULL,
  amount INT,
  UNIQUE(month_id,sale_id)
) REPLICATION=ON PARTITION BY RANGE(month_id) (...);
```

1. 파티션별 동일 `sale_id`를 삽입한다.
2. 파티션 ADD/SPLIT 또는 지원되는 EXCHANGE를 수행한다.
3. 경계 행을 UPDATE하고 failover한다.

- 기대 결과: 부모/파티션의 설정과 RK identity가 명세대로 상속된다. 같은 local key가 있어도 정확한 파티션 행 한 개를 찾으며 DDL·데이터가 양 노드에서 같다.
- 검증 지표: partition map, RK encoding, 파티션별 checksum, apply lag.
- 연결된 원시 리뷰 ID: `DBA-5Y-23`, `엔진개발자-10년차-21`, `USER-3Y-23`

## 3. 오류 및 거부 동작

### [TS-E01] HA에서 RK 없는 기본 ON 테이블 생성 거부

- 목적: 문법 오류가 아닌 RK 정책 오류와 안전한 rollback을 확인한다.
- 사전 조건: HA 실행 중, 올바른 SQL 문법 사용.
- SQL·이벤트 순서:

```sql
CREATE TABLE no_key (value INT) REPLICATION=ON;
```

- 기대 결과: 안정된 `RK_MISSING` 계열 코드로 실패하고 source/replica catalog에 객체·임시 index가 남지 않는다. 오류는 PK/NOT NULL UK 추가 또는 OFF 선택을 안내한다.
- 검증 지표: 오류 코드·SQLSTATE, catalog 잔여 객체 0, DDL log 미생성, `fail_count` 불변.
- 연결된 원시 리뷰 ID: `USER-1Y-10`, `DBA-3Y-06`, `DBDEV-1Y-19`

### [TS-E02] 마지막 RK 후보 삭제 거부

- 목적: ON 테이블이 후보 0개가 되는 DDL을 모든 진입 경로에서 차단한다.
- 사전 조건: PK 하나만 있는 ON 테이블.
- SQL·이벤트 순서:

```sql
ALTER TABLE only_key DROP PRIMARY KEY;
ALTER TABLE only_key DROP COLUMN id;
```

- 기대 결과: 두 SQL 모두 같은 정책 범주의 안정된 오류로 실패하고 기존 PK/RK와 데이터가 유지된다.
- 검증 지표: 오류 코드, 전후 `SHOW CREATE TABLE`, RK generation 불변, replica DDL 없음.
- 연결된 원시 리뷰 ID: `USER-3Y-07`, `DBA-3Y-08`, `DBDEV-1Y-08`

### [TS-E03] 새 키 중복으로 복합 ALTER 전체 rollback

- 목적: DROP+ADD 중 ADD 검증 실패가 old PK를 제거하지 않는지 확인한다.
- 사전 조건: 새 email 값에 중복 존재.
- SQL·이벤트 순서:

```sql
CREATE TABLE c (id INT PRIMARY KEY, email VARCHAR(100)) REPLICATION=ON;
INSERT INTO c VALUES (1,'dup@x'),(2,'dup@x');
ALTER TABLE c DROP PRIMARY KEY,
  ADD CONSTRAINT uq_c_email UNIQUE(email);
```

- 기대 결과: 전체 ALTER가 실패하고 id PK/RK가 양 노드에 유지된다. partial index·catalog·DDL log가 없다.
- 검증 지표: old constraint 존재, shadow object cleanup, checksum, 오류 phase·코드.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-08`, `DBA-10년차-08`, `DBDEV-5Y-08`

### [TS-E04] ON 자식이 OFF 부모를 참조하는 FK 거부

- 목적: CREATE와 ALTER 양쪽이 같은 FK/REPLICATION 불변식을 적용하는지 확인한다.
- 사전 조건: `local_parent`는 OFF.
- SQL·이벤트 순서:

```sql
CREATE TABLE local_parent (id INT PRIMARY KEY) REPLICATION=OFF;
CREATE TABLE child (
  id INT PRIMARY KEY,
  parent_id INT,
  FOREIGN KEY(parent_id) REFERENCES local_parent(id)
) REPLICATION=ON;
```

- 기대 결과: child CREATE 전체가 실패하고 부모는 변하지 않는다. 반대로 기존 ON FK 부모를 OFF로 바꾸는 ALTER도 의존 경로와 함께 거부된다.
- 검증 지표: 오류의 parent/child/constraint, catalog 잔여 객체, FK graph 검사.
- 연결된 원시 리뷰 ID: `USER-1Y-13`, `DBA-10년차-13`, `DBDEV-5Y-13`

### [TS-E05] OFF 노드별 데이터가 다른 상태의 데이터 의존 DDL

- 목적: source에서만 성공 가능한 UNIQUE/NOT NULL DDL을 조용히 복제하지 않는지 확인한다.
- 사전 조건: 같은 OFF 테이블에 source는 `1,2`, replica는 로컬 `1,1` 값 보유.
- SQL·이벤트 순서:

```sql
ALTER TABLE local_code ADD CONSTRAINT uq_local_code UNIQUE(code);
```

- 기대 결과: 권고 기준은 HA 중 선제 거부 또는 모든 노드 prepare 검증 실패 후 전체 취소다. source만 commit하고 replica만 실패한 split-schema는 금지한다.
- 검증 지표: 노드별 validation 결과, schema 동일성, apply barrier, 승격 가능 상태.
- 연결된 원시 리뷰 ID: `DBDEV-5Y-21`, `DBA-5Y-29`, `PM-5Y-11`

### [TS-E06] RK 타입·NULL·collation 부적합 거부

- 목적: RK 후보의 타입과 비교 의미 제한을 검증한다.
- 사전 조건: 지원/금지 타입 및 최대 bytes 표가 구현에 확정됨.
- SQL·이벤트 순서:

```sql
CREATE TABLE bad_key (
  k VARCHAR(2000) UNIQUE,
  value INT
) REPLICATION=ON;
ALTER TABLE login_name ALTER COLUMN name DROP NOT NULL;
```

- 기대 결과: NULL 가능 또는 크기·타입·collation 조건을 위반하면 후보로 세지 않으며 마지막 후보 상실 DDL은 사전 거부된다. 오류는 정확한 컬럼과 이유를 표시한다.
- 검증 지표: candidate 계산, 오류 코드, catalog rollback, 경계값 행 검색.
- 연결된 원시 리뷰 ID: `USER-3Y-27`, `DBA-10년차-29`, `DBDEV-5Y-12`

## 4. 동시성 및 순서

### [TS-C01] 장기 DML과 RK DDL의 직렬화

- 목적: DDL 전 시작해 DDL 후 commit하는 transaction의 schema pinning을 확인한다.
- 사전 조건: 두 세션과 apply 지연 제어 가능.
- SQL·이벤트 순서:

```sql
-- 세션 A: UPDATE 후 commit 대기
UPDATE account SET balance=balance-10 WHERE id=10;
-- 세션 B
ALTER TABLE account DROP PRIMARY KEY,
  ADD CONSTRAINT pk_account_email PRIMARY KEY(email);
-- A/B commit 순서를 교차
```

- 기대 결과: 정의된 wait/abort/epoch 규칙 중 하나로 serial history와 동등하다. old DML을 new key로 잘못 해석하지 않는다.
- 검증 지표: lock wait, transaction schema generation, commit LSA 순서, checksum.
- 연결된 원시 리뷰 ID: `PM-5Y-09`, `DBA-5Y-09`, `DBDEV-5Y-09`

### [TS-C02] 활성 RK 값 자체 UPDATE의 old/new image

- 목적: key 변경 DML이 old key로 정확히 한 행을 찾아 new key를 저장하는지 확인한다.
- 사전 조건: UK `tracking`이 활성 RK.
- SQL·이벤트 순서:

```sql
UPDATE parcel SET tracking='NEW' WHERE tracking='OLD';
```

추가로 두 행 key swap, 중복 new key, rollback과 동일 log 재적용을 수행한다.

- 기대 결과: 성공 시 양쪽에 NEW 행 하나만 있고 OLD는 없다. 충돌은 양쪽에서 같은 transaction 단위로 rollback되며 duplicate replay는 추가 효과가 없다.
- 검증 지표: old/new encoded key, 행 수, unique 검사 결과, 재적용 후 checksum.
- 연결된 원시 리뷰 ID: `사용자-5년차-12`, `DBA-10년차-28`, `DBDEV-1Y-13`

### [TS-C03] ON→OFF 전환과 backlog drain

- 목적: 전환 이전 로그와 이후 제외 로그의 경계를 지연 상황에서 검증한다.
- 사전 조건: replica apply를 중지하고 UPDATE 1만 건 backlog 생성.
- SQL·이벤트 순서:

```text
LSA 100: ON UPDATE
LSA 101: ALTER REPLICATION=OFF
LSA 102: OFF UPDATE
```

apply를 재개하고 각 LSA 직전·직후 crash를 주입한다.

- 기대 결과: 100은 적용, 101은 barrier, 102는 제외된다. 재시작 횟수와 무관하게 같은 결과이며 cutover LSA가 조회된다.
- 검증 지표: log filter 결과, apply LSA, 전환 전 checksum, 감사 event.
- 연결된 원시 리뷰 ID: `PM-5Y-38`, `DBA-10년차-06`, `DBDEV-5Y-03`

### [TS-C04] OFF→ON 재편입의 snapshot과 catch-up

- 목적: 과거 OFF 차이를 가진 테이블을 단순 설정 변경 없이 완전히 bootstrap하는지 확인한다.
- 사전 조건: source에만 100만 행, 유효 RK, 공식 rejoin 절차 사용.
- SQL·이벤트 순서:

1. 일관된 snapshot LSA를 잡는다.
2. baseline을 replica로 복사한다.
3. 복사 중 DML을 capture/catch-up한다.
4. checksum 확인 후 ON activation barrier를 commit한다.
5. failover한다.

- 기대 결과: 활성화 시점에 양쪽 전체 데이터가 같고 이후 DML도 정상 적용된다. 중간 실패 시 OFF로 안전 복귀하거나 resume한다.
- 검증 지표: baseline LSA, catch-up backlog, checksum, activation 상태, failover CRUD.
- 연결된 원시 리뷰 ID: `PM-5Y-37`, `DBA-10년차-07`, `DBA-5Y-03`

### [TS-C05] ON/OFF 혼합 transaction

- 목적: 원 transaction에서 복제되는 ON 부분집합의 원자성과 사용자 경고를 검증한다.
- 사전 조건: `account` ON, `local_outbox` OFF.
- SQL·이벤트 순서:

```sql
BEGIN;
UPDATE account SET balance=balance-100 WHERE id=1;
INSERT INTO local_outbox VALUES (1,'PAID');
SAVEPOINT s;
COMMIT;
```

- 기대 결과: 제품이 금지하면 commit 전에 명확히 거부한다. 허용하면 replica에서 ON subset 전체가 한 transaction으로 한 번 적용되고 OFF record는 정책대로 제외된다.
- 검증 지표: replicated transaction ID, record count/checksum, rollback/savepoint 결과, failover 업무 상태.
- 연결된 원시 리뷰 ID: `사용자-5년차-22`, `APPDEV-1Y-29`, `DBDEV-5Y-25`

### [TS-C06] 병렬 apply의 테이블·의존성 DDL barrier

- 목적: 여러 apply worker가 old/new descriptor를 동시에 사용하지 않는지 검증한다.
- 사전 조건: 병렬 apply 지원 시 worker 4개, FK parent/child와 DML backlog.
- SQL·이벤트 순서:

```text
W1: parent old-RK UPDATE 적용 중
W2: parent new-RK 이후 UPDATE 대기
W3: child FK DML 적용 중
DDL worker: parent RK switch
```

- 기대 결과: 지정된 table/dependency barrier가 관련 worker를 drain한 뒤 DDL을 publish한다. unrelated table worker는 가능한 경우 진행한다.
- 검증 지표: worker epoch/ACK, barrier 대기, throughput, serial reference checksum.
- 연결된 원시 리뷰 ID: `DBA-5Y-26`, `DBDEV-1Y-25`, `DBDEV-5Y-32`

### [TS-C07] 동시 migration runner와 DDL 응답 유실

- 목적: DDL이 정확히 한 번 논리 적용되고 client timeout 뒤 blind retry하지 않는지 확인한다.
- 사전 조건: migration runner 10개, 공통 migration lock/version table.
- SQL·이벤트 순서:

1. 모든 runner가 같은 PK→UK migration을 요청한다.
2. winner의 commit 직후 응답 연결을 끊는다.
3. runner들을 재시작해 migration state를 조회한다.

- 기대 결과: 한 runner만 DDL을 commit한다. 결과 미확인 runner는 schema/RK와 request ID를 조회해 완료로 정리하며 DROP/ADD를 반복하지 않는다.
- 검증 지표: DDL commit 수 1, migration version, lock owner, 오류·retry 횟수.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-22`, `APPDEV-1Y-23`, `엔진개발자-10년차-27`

## 5. 장애 조치와 네트워크 장애

### [TS-F01] RK DDL 단계별 primary 장애와 승격

- 목적: index build·catalog switch·DDL log 전송 각 단계의 장애에서 안전한 승격 조건을 확인한다.
- 사전 조건: PK→UK 전환 state와 fault injection hook.
- SQL·이벤트 순서:

```sql
ALTER TABLE huge_customer DROP PRIMARY KEY,
  ADD CONSTRAINT uq_customer_email UNIQUE(email);
```

new index build 50%, metadata commit 직전/직후, replica apply 중에 primary를 각각 종료한다.

- 기대 결과: replica는 완전한 old 또는 new schema일 때만 승격한다. PREPARED/부분 DDL 노드는 승격이 차단되고 복구·rollback한다.
- 검증 지표: DDL state, promotion eligibility, RK generation, recovery 시간, checksum.
- 연결된 원시 리뷰 ID: `사용자-5년차-10`, `DBA-5Y-10`, `DBDEV-5Y-11`

### [TS-F02] COMMIT 성공 직후 장애의 RPO와 read-your-write

- 목적: client 성공 응답과 새 primary의 데이터 가시성 관계를 검증한다.
- 사전 조건: 지원 복제 동기화 모드별 실행.
- SQL·이벤트 순서:

```sql
INSERT INTO payment(id,status) VALUES(500,'PAID');
COMMIT;
-- ACK 직후 primary 전원 차단과 failover
```

- 기대 결과: 동기 모드는 약속한 durable 위치까지 성공 commit을 보존한다. 비동기 모드는 유실 가능 범위와 마지막 안전 LSA를 명확히 보고하고 idempotent retry가 중복을 만들지 않는다.
- 검증 지표: ACK/flush/apply LSA, 새 primary 행, RPO, API retry 결과.
- 연결된 원시 리뷰 ID: `DBA-10년차-11`, `APPDEV-1Y-32`, `USER-10Y-10`

### [TS-F03] split-brain과 상충 RK DDL

- 목적: 네트워크 분할에서 단일 writer fencing과 divergence 격리를 검증한다.
- 사전 조건: fencing 실패도 의도적으로 시험할 수 있는 격리 환경.
- SQL·이벤트 순서:

```text
분할 중 A: RK id→email 및 email 기반 UPDATE
분할 중 B: RK id→external_no 및 external_no 기반 UPDATE
네트워크 복구
```

- 기대 결과: 정상 정책에서는 stale primary 쓰기가 거부된다. fencing 실패로 분기되면 자동 merge/rejoin을 금지하고 두 RK epoch·DML 범위를 보존해 수동 복구 상태로 둔다.
- 검증 지표: cluster term/fencing epoch, 거부된 write, divergence report, 자동 apply 0.
- 연결된 원시 리뷰 ID: `PM-5Y-32`, `DBA-10년차-10`, `엔진개발자-10년차-10`

### [TS-F04] 다중 standby의 지연과 old RK epoch 보관

- 목적: 빠른·느린 standby 모두 옛 로그를 적용할 때까지 필요한 descriptor/index가 보존되는지 확인한다.
- 사전 조건: B lag 1초, C lag 2시간 또는 cascade topology.
- SQL·이벤트 순서:

1. C apply를 정지한다.
2. source에서 id→email→external_id로 두 번 전환한다.
3. B를 최신으로 유지하고 GC를 실행한다.
4. C를 재개하거나 C 승격을 시도한다.

- 기대 결과: C backlog가 참조하는 epoch는 GC하지 않는다. 보존 한계를 넘겼다면 C는 재-seed 필요로 격리되고 승격되지 않는다.
- 검증 지표: replica별 low-water mark, descriptor GC, C apply 결과, promotion eligibility.
- 연결된 원시 리뷰 ID: `DBA-5Y-32`, `PM-5Y-31`, `엔진개발자-10년차-25`

### [TS-F05] OFF 테이블과 의존 VIEW의 failover 결과

- 목적: 의도된 로컬 차이를 탐지하고 중요 VIEW를 조용한 오답으로 서비스하지 않는지 확인한다.
- 사전 조건: `orders` ON, `local_acl` OFF, NOT EXISTS VIEW.
- SQL·이벤트 순서:

```sql
CREATE VIEW allowed_orders AS
SELECT o.* FROM orders o WHERE NOT EXISTS (
  SELECT 1 FROM local_acl a WHERE a.region=o.region
);
```

source와 replica의 `local_acl`을 다르게 만든 뒤 failover한다.

- 기대 결과: 의존성 검사가 직접·중첩 VIEW를 보고한다. 중요 태그 VIEW는 승격 차단 또는 명시 승인 대상이며 앱 readiness가 오답 200 응답을 막는다.
- 검증 지표: dependency path, VIEW 전후 행 수, 경고/차단, 앱 응답.
- 연결된 원시 리뷰 ID: `PM-5Y-13`, `DBA-10년차-14`, `APPDEV-1Y-14`

## 6. 호환성 및 이관

### [TS-H01] legacy unload/load 무표기 기본값 결정

- 목적: 원문 8절 ON과 9절 OFF의 상충을 해소한 정책이 모든 경로에서 일관적인지 검증한다.
- 사전 조건: legacy fixture에 REPLICATION field 없음; PK 있음/없음 테이블 포함.
- SQL·이벤트 순서:

1. `--default-replication=ON`, `OFF`, `ERROR` 또는 확정된 정책으로 dry-run한다.
2. load 중간에 중단·재개한다.
3. 결과 DB의 readiness와 failover를 시험한다.

- 기대 결과: 무표기를 조용히 임의 해석하지 않고 선택·경고가 dry-run과 실제 결과에서 같다. 재개는 idempotent하며 테이블별 ON/OFF·RK 판정이 기록된다.
- 검증 지표: manifest version, table mapping, load exit code, schema diff, readiness.
- 연결된 원시 리뷰 ID: `PM-5Y-17`, `USER-1Y-17`, `DBDEV-5Y-17`

### [TS-H02] 혼합 버전 rolling upgrade와 feature gate

- 목적: 구버전 노드가 새 DDL/RK log를 오해하지 않고 기능 사용 전 capability를 검사하는지 확인한다.
- 사전 조건: 지원 인접 버전 N/N-1 양방향 역할 조합.
- SQL·이벤트 순서:

```sql
ALTER TABLE audit REPLICATION=OFF;
ALTER TABLE customer DROP PRIMARY KEY,
  ADD CONSTRAINT uq_customer_email UNIQUE(email);
```

혼합 기간, 전체 N 전환 후, downgrade 요청 시 각각 실행한다.

- 기대 결과: capability 부족 시 source가 log 생성 전에 거부한다. 전체 지원 후에는 정상 적용되며 point-of-no-return 이후 downgrade는 사전 검사에서 차단된다.
- 검증 지표: protocol negotiation, feature marker, DDL 오류, failover/failback, checksum.
- 연결된 원시 리뷰 ID: `PM-5Y-18`, `DBA-10년차-17`, `DBDEV-5Y-18`

### [TS-H03] schema export/import와 관리 도구 round-trip

- 목적: csql·JDBC/CCI·지원 ORM/schema diff가 ON/OFF와 활성 RK 의미를 보존하는지 확인한다.
- 사전 조건: ON/PK, ON/여러 UK, OFF 테이블 fixture.
- SQL·이벤트 순서:

1. 각 도구로 introspect/export한다.
2. 빈 DB에 import/create한다.
3. 다시 diff하여 변경 0을 기대한다.

- 기대 결과: OFF가 기본 ON으로 바뀌지 않고 영구 RK identity는 안전하게 remap된다. 구버전 도구는 조용히 필드를 버리지 않고 지원 불가 경고를 낸다.
- 검증 지표: semantic schema diff, ON/OFF, 후보/활성 RK, tool exit code.
- 연결된 원시 리뷰 ID: `PM-5Y-34`, `DBA-10년차-35`, `APPDEV-1Y-06`

### [TS-H04] in-place catalog upgrade의 중단·재개·downgrade

- 목적: 기존 객체 backfill이 부분 상태를 노출하지 않는지 확인한다.
- 사전 조건: 10만 class legacy DB, new field 없음.
- SQL·이벤트 순서:

1. catalog migration batch 10%, 50%, activation 직전에 crash한다.
2. 신버전으로 resume한다.
3. 지원 지점에서는 구버전 rollback을 시도한다.

- 기대 결과: migration은 idempotent하며 final activation 전 old semantics, 이후 new semantics 한 가지다. mixed implicit/explicit state로 HA가 시작되지 않는다.
- 검증 지표: format version, migrated count, duplicate RK ID, activation marker, restart 결과.
- 연결된 원시 리뷰 ID: `PM-5Y-35`, `DBDEV-5Y-37`, `엔진개발자-10년차-35`

## 7. 성능과 자원

### [TS-P01] 넓은 복합 RK의 로그 증폭과 apply 처리량

- 목적: 정수 PK 대비 긴 복합 문자열 UK의 용량·지연 비용을 측정한다.
- 사전 조건: 동일 행 수와 DML workload, 1/2/4/8컬럼 key fixture.
- SQL·이벤트 순서:

```sql
CREATE TABLE wide_key (
  tenant VARCHAR(100) NOT NULL,
  external_code VARCHAR(500) NOT NULL,
  region VARCHAR(100) NOT NULL,
  UNIQUE(tenant,external_code,region)
) REPLICATION=ON;
```

초당 목표 TPS로 INSERT/UPDATE/DELETE와 key UPDATE를 1시간 수행한다.

- 기대 결과: 합의한 최대 key bytes와 성능 SLO 안에서 ingest보다 apply throughput이 낮지 않다. 한계를 넘는 key는 생성 시 경고·거부한다.
- 검증 지표: bytes/record, network, CPU, p95 apply lag, index probe latency, TPS.
- 연결된 원시 리뷰 ID: `PM-5Y-14`, `DBA-5Y-12`, `DBDEV-5Y-18`

### [TS-P02] 온라인 RK 인덱스 구축의 자원 고갈과 안전 취소

- 목적: disk full·memory quota·timeout에서 old RK와 WAL 생존 공간을 보존하는지 확인한다.
- 사전 조건: 10억 행 또는 축소 부하 모델, 디스크 여유 임계값 조정.
- SQL·이벤트 순서:

```sql
ALTER TABLE huge_event
  ADD CONSTRAINT uq_event_external UNIQUE(external_id),
  DROP PRIMARY KEY;
```

index build 50%에서 disk full, cancel, process kill을 각각 주입한다.

- 기대 결과: admission control이 불충분한 공간이면 시작 전 거부한다. 실행 중 실패하면 old RK가 유지되고 shadow/temporary object가 정리 또는 resume 가능하다. replica 부분 성공 노드는 승격되지 않는다.
- 검증 지표: 예상/실제 임시 bytes, WAL reserve, progress, cleanup 시간, schema/RK, promotion state.
- 연결된 원시 리뷰 ID: `DBA-5Y-24`, `DBA-5Y-29`, `엔진개발자-10년차-30`

### [TS-P03] 대규모 HA readiness 검사

- 목적: 5만 table·10만 FK에서도 일관된 snapshot으로 전체 위반을 제한 자원 안에서 찾는지 확인한다.
- 사전 조건: RK 없음, OFF 부모 FK, OFF 의존 VIEW 등 위반 5천 개 주입.
- SQL·이벤트 순서:

1. dry-run readiness를 실행한다.
2. 검사 중 마지막 UK 삭제·CREATE/DROP을 경쟁시킨다.
3. HA start와 동일 token/snapshot을 사용한다.

- 기대 결과: 한 snapshot 기준 전체 위반을 pagination/구조화 출력한다. 검사와 활성화 사이 TOCTOU가 없고 timeout·취소 뒤 lock이 남지 않는다.
- 검증 지표: 시간, CPU·메모리, 탐지율 100%, false positive, lock wait, output bytes.
- 연결된 원시 리뷰 ID: `PM-5Y-10`, `DBA-10년차-34`, `DBDEV-5Y-15`

## 8. 복구와 재동기화

### [TS-R01] RK 전환 전후 PITR

- 목적: 백업 시점부터 목표 시점까지 RK DDL/DML epoch를 정확히 재생한다.
- 사전 조건: 물리/논리 복구 방식별 지원 범위 확정.
- SQL·이벤트 순서:

```text
T1: PK(id)에서 full backup
T2: id 기반 UPDATE
T3: PK(id)→UK(email)
T4: email 기반 UPDATE
T5: 목표 시점
```

T1~T5 각 경계로 복원하고 중간 replay crash도 주입한다.

- 기대 결과: 각 목표 시점의 schema, 활성 RK, 데이터와 log position이 원본과 같다. 전환 중 비일관 시점은 명시적으로 거부한다.
- 검증 지표: backup manifest RK epoch, replay LSA, schema/checksum, resume 횟수.
- 연결된 원시 리뷰 ID: `PM-5Y-30`, `DBA-10년차-18`, `엔진개발자-10년차-18`

### [TS-R02] apply crash와 duplicate replay 멱등성

- 목적: row 적용 후 progress 저장 전 crash에서도 DML·DDL을 두 번 반영하지 않는다.
- 사전 조건: apply record 전/후 crash hook.
- SQL·이벤트 순서:

1. balance UPDATE, RK 값 UPDATE, DELETE, RK switch를 각각 기록한다.
2. record 적용 직전, row 변경 후, progress flush 전후에 crash한다.
3. 여러 번 재시작한다.

- 기대 결과: 재시작 횟수와 무관하게 최종 결과가 한 번 적용과 같다. 정상 duplicate DELETE를 영구 row-not-found 오류로 세지 않는다.
- 검증 지표: transaction/record ID, apply count, checksum, `fail_count`, progress LSA.
- 연결된 원시 리뷰 ID: `DBDEV-5Y-10`, `엔진개발자-10년차-27`, `엔진개발자-3년차-29`

### [TS-R03] 기존 불일치 탐지와 멱등 repair

- 목적: 새 기능 이전의 행 누락·추가·값 차이를 일관된 snapshot에서 찾아 안전하게 고친다.
- 사전 조건: source `(1,100),(2,200)`, replica `(1,90),(3,210)` 등 분기 fixture.
- SQL·이벤트 순서:

1. RK range checksum을 같은 기준 LSA에서 계산한다.
2. 차이 행과 source-of-truth를 승인한다.
3. repair 중 동시 DML·네트워크 단절을 주입한다.
4. 같은 repair ID로 재개·재실행한다.

- 기대 결과: 모든 차이를 찾고 최신 commit을 덮어쓰지 않는다. 재실행은 추가 효과가 없고 감사 기록 뒤 checksum이 같다.
- 검증 지표: 탐지율, conflict 수, repair checkpoint, 전후 checksum, 감사 행 수.
- 연결된 원시 리뷰 ID: `PM-5Y-16`, `DBA-10년차-16`, `DBDEV-1Y-16`

### [TS-R04] 손상 standby 재-seed와 catch-up

- 목적: 대형 snapshot 복사 중 RK 전환이 있어도 새 standby를 정확히 재구축한다.
- 사전 조건: generation 5에서 snapshot, 이후 generation 6 전환과 DML.
- SQL·이벤트 순서:

1. snapshot LSA와 필요한 epoch retention을 예약한다.
2. baseline copy 중 DML과 RK 전환을 수행한다.
3. copy를 중단·재개하고 catch-up한다.
4. checksum 후 promotion eligibility를 설정한다.

- 기대 결과: T1 snapshot과 후속 모든 로그가 빈틈 없이 연결된다. 검증 전에는 승격되지 않으며 완료 후 source와 동일하다.
- 검증 지표: snapshot/catch-up LSA, retained epoch, copy resume, checksum, RTO.
- 연결된 원시 리뷰 ID: `DBA-10년차-33`, `PM-5Y-31`, `엔진개발자-10년차-32`

## 9. 보안·권한

### [TS-S01] REPLICATION 변경 최소 권한과 감사 원자성

- 목적: 보호 등급 변경을 승인된 역할만 수행하고 commit과 감사가 함께 남는지 확인한다.
- 사전 조건: runtime, migration, owner, DBA 계정과 별도 권한 행렬.
- SQL·이벤트 순서:

```sql
ALTER TABLE orders REPLICATION=OFF;
ALTER TABLE orders REPLICATION=ON;
```

각 계정으로 성공·실패·rollback하고 audit flush 지점에 crash를 주입한다.

- 기대 결과: runtime/권한 없는 계정은 변경 로그도 만들지 못한다. 승인된 commit에는 actor, old/new state, LSA, migration ID가 정확히 한 건 남고 rollback에는 성공 event가 없다.
- 검증 지표: authorization code, catalog state, audit count·LSA, 변조 권한.
- 연결된 원시 리뷰 ID: `PM-5Y-21`, `DBA-10년차-21`, `DBDEV-5Y-30`, `DBDEV-5Y-31`

### [TS-S02] 민감 RK redaction과 손상 log 방어

- 목적: email 같은 RK가 진단에 노출되지 않고 malformed record가 apply crash/OOM을 만들지 않는지 확인한다.
- 사전 조건: transport/archive encryption과 redaction 정책 확정, fuzz harness.
- SQL·이벤트 순서:

```sql
UPDATE member SET name='Kim' WHERE email='person@example.com';
```

이후 RK record의 length, column count, type OID, checksum을 변조한다.

- 기대 결과: 정상 apply에는 원 key를 사용할 수 있으나 metric·일반 오류·support bundle에는 정책대로 마스킹된다. 손상 record는 row lookup 전에 탐지되어 fatal barrier/quarantine이 되고 process는 생존한다.
- 검증 지표: 평문 검색 결과 0(승인 저장소 제외), checksum 오류, memory peak, crash 0, row 변경 0.
- 연결된 원시 리뷰 ID: `사용자-5년차-31`, `DBDEV-5Y-34`, `DBDEV-5Y-35`

## 10. 드라이버·도구·진단 연동

### [TS-T01] ORM·connection pool의 schema 변경과 failover

- 목적: cached metadata/prepared statement와 stale primary 연결을 안전하게 폐기·재준비한다.
- 사전 조건: 지원 driver/ORM/pool 버전, 구·신 앱 동시 실행.
- SQL·이벤트 순서:

1. 여러 pool 연결에서 old-column UPDATE를 prepare한다.
2. 호환 migration 또는 rename/RK DDL을 수행한다.
3. failover하고 old connection을 재사용한다.
4. documented reprepare/pool recycle을 수행한다.

- 기대 결과: stale statement는 안정된 schema 오류 또는 자동 reprepare로 처리되고 transaction 중복은 없다. old primary 연결은 fencing 오류로 폐기된다.
- 검증 지표: exception class/code, pool 전환 시간, reprepare 수, duplicate DML, 양 노드 checksum.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-21`, `APPDEV-1Y-33`, `DBDEV-5Y-06`

### [TS-T02] 구조화·국제화 오류와 CI 진단

- 목적: 메시지 언어가 달라도 자동화가 원인을 정확히 분류하고 전체 위반을 처리한다.
- 사전 조건: 한국어/영어 locale, JSON 또는 고정 컬럼 진단 형식.
- SQL·이벤트 순서:

1. RK 없음, 마지막 RK 삭제, FK OFF, lock timeout, mixed-version 오류를 만든다.
2. locale을 바꾸어 반복한다.
3. CI가 코드·필드로 수정 작업을 분기한다.

- 기대 결과: 사람용 문구만 번역되고 안정된 오류 코드, retryable flag, owner.table, constraint, RK generation은 유지된다. 대량 readiness 결과는 pagination해도 누락되지 않는다.
- 검증 지표: 코드 안정성, parser 성공률 100%, 중복/누락 진단 0, 잘못된 retry 0.
- 연결된 원시 리뷰 ID: `USER-3Y-29`, `DBA-10년차-19`, `APPDEV-1Y-15`

## 11. 추가 예상 시나리오

아래 13개는 최초 40개 시나리오와 30개 통합 결함을 대조한 뒤 발견한 누락이다. CUBRID가 실제로 지원하지 않는 객체나 명령은 성공을 기대하지 않는다. 이 경우 기대 결과는 일관된 명시적 비지원 오류, 데이터·카탈로그 무변경, 문서상 범위 명시다.

### [TS-X01] trigger·procedure·FK cascade 내부 DML의 단일 적용

- 목적: 사용자 DML에서 파생된 내부 DML이 source와 replica에서 중복 실행되거나 누락되지 않는지 확인한다.
- 사전 조건: trigger 또는 procedure가 감사 테이블을 변경하고, FK는 `ON DELETE CASCADE`를 사용한다. 관련 테이블의 ON/OFF 조합은 시험별로 명시한다.
- SQL·이벤트 순서:

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE child (
  id INT PRIMARY KEY,
  parent_id INT,
  CONSTRAINT fk_child_parent FOREIGN KEY(parent_id)
    REFERENCES parent(id) ON DELETE CASCADE
) REPLICATION=ON;
```

1. parent와 child에 행을 넣고 trigger가 별도 audit 행을 한 건 생성하게 한다.
2. source에서 parent를 삭제한다.
3. 복제 로그에 원 DML과 파생 DML이 어떻게 기록되는지 확인한다.
4. replica apply를 한 번 중단·재시작하고 동일 로그를 재적용한다.

- 기대 결과: cascade와 trigger 결과는 source와 replica에 각각 정확히 한 번만 나타난다. source에서 생성된 파생 DML을 replica가 다시 생성해 이중 삭제·이중 INSERT하지 않는다. ON 자식이 OFF 부모를 참조하는 금지 조합은 DDL 시점에 거부된다.
- 검증 지표: 원 DML/파생 DML provenance, 행별 적용 횟수, audit 행 수, FK 검증, checksum, 중복·누락 0.
- 연결된 원시 리뷰 ID: `사용자-5년차-24`, `DBDEV-5Y-26`, `엔진개발자-10년차-13`

### [TS-X02] TRUNCATE·bulk·CTAS·LIKE·clone·rename의 정책 보존

- 목적: 일반 CREATE/INSERT와 다른 빠른 경로가 REPLICATION 정책과 RK 카탈로그를 우회하지 않는지 확인한다.
- 사전 조건: ON/PK 테이블과 OFF/무키 테이블이 각각 존재하고, 각 명령의 CUBRID 지원 여부가 정리돼 있다.
- SQL·이벤트 순서:

1. ON 테이블을 대상으로 `TRUNCATE`와 지원되는 bulk load를 각각 수행한다.
2. `CREATE TABLE ... AS SELECT`, `LIKE` 또는 CUBRID가 지원하는 동등 기능으로 새 테이블을 만든다.
3. 테이블 clone과 rename을 지원한다면 clone 후 원본·복제본의 객체 ID를, rename 후 변경 전·후 객체 ID를 조회한다.
4. 각 단계 뒤 failover하고 schema, 정책, 데이터와 RK를 조회한다.

- 기대 결과: 지원 명령은 정책 상속/초기화 규칙대로 동작하고 source·replica 결과가 같다. clone은 새 논리 객체 ID를 받고 rename은 기존 논리 ID와 과거 로그 연결을 보존한다. 미지원 명령은 변경 전에 명확히 거부된다.
- 검증 지표: 명령별 로그 유형, ON/OFF, 논리 테이블·RK ID, epoch, 행 수·checksum, round-trip metadata.
- 연결된 원시 리뷰 ID: `DBDEV-5Y-24`, `DBA-10년차-31`, `엔진개발자-10년차-22`

### [TS-X03] loaddb 부분 실패의 멱등 재개와 정리

- 목적: 여러 테이블을 load하는 중 한 객체가 RK 조건을 위반하거나 프로세스가 종료돼도 재실행이 중복·혼합 상태를 만들지 않는지 확인한다.
- 사전 조건: ON/PK 테이블, ON/무키 테이블, OFF 테이블이 섞인 dump와 load 진행 상태를 조회할 방법이 있다.
- SQL·이벤트 순서:

1. 첫 테이블 load 완료 직후 프로세스를 강제 종료한다.
2. 두 번째 실행에서는 ON/무키 테이블의 정책 오류를 발생시킨다.
3. 문제를 교정하고 동일 작업 ID로 resume한다.
4. 완료된 load를 한 번 더 실수로 실행한다.

- 기대 결과: 도구는 완료·실패·미시작 객체와 commit 경계를 기록한다. resume는 완료 객체를 중복 생성·적재하지 않으며 실패 객체부터 안전하게 이어 간다. cleanup과 처음부터 재시작 중 필요한 조치를 구조화해 출력한다.
- 검증 지표: 객체별 상태 ledger, duplicate row·object 0, 최종 ON/OFF·RK, 재시도 횟수, 종료 코드, checksum.
- 연결된 원시 리뷰 ID: `USER-1Y-26`, `DBA-3Y-26`, `사용자-5년차-27`

### [TS-X04] 물리 snapshot의 crash consistency와 OFF 데이터 노드 귀속

- 목적: 파일시스템/스토리지 snapshot이 데이터 시점, RK epoch, 복제 위치를 함께 보존하며 OFF 로컬 데이터의 출처를 숨기지 않는지 확인한다.
- 사전 조건: source와 replica의 OFF 테이블 값이 의도적으로 다르고 RK 전환과 DML이 진행 중이다.
- SQL·이벤트 순서:

1. RK 전환 PREPARING 또는 지원되는 중간 상태에서 source와 replica snapshot을 각각 만든다.
2. snapshot manifest 없이 복원을 시도한다.
3. 올바른 manifest가 있는 source snapshot과 replica snapshot을 별도 환경에 복원한다.
4. 복원 DB에서 HA 연결·PITR·failover readiness를 검사한다.

- 기대 결과: manifest 없는 복원은 안전하게 거부되거나 비HA 격리 상태로 열린다. manifest에는 node identity, checkpoint/LSA, RK epoch와 전환 상태가 있고, OFF 데이터는 어느 노드 사본인지 표시된다. 서로 다른 노드 snapshot을 조합하지 않는다.
- 검증 지표: crash recovery 성공, manifest 필드, ON checksum, OFF provenance, epoch/LSA 일치, 잘못된 승격 0.
- 연결된 원시 리뷰 ID: `DBA-5Y-28`, `USER-10Y-27`, `DBA-10년차-32`

### [TS-X05] 반복 apply 실패의 retry budget·quarantine·재기동

- 목적: 같은 행 미발견 또는 RK decode 오류가 무한 재시도와 `fail_count` 폭증을 일으키지 않는지 확인한다.
- 사전 조건: 특정 로그 record가 결정적으로 실패하도록 fault injection하고 후속 정상 record도 준비한다.
- SQL·이벤트 순서:

1. 실패 record를 적용하고 replica process를 여러 번 재시작한다.
2. retry budget에 도달시킨다.
3. 운영자가 오류 상세와 영향 범위를 확인한다.
4. 데이터 또는 metadata를 교정하고 명시적으로 quarantine을 해제한다.

- 기대 결과: 동일 오류는 안정된 event ID로 집계되고 무제한 CPU·로그·알람을 만들지 않는다. ordering을 보존해야 하는 후속 record는 임의로 건너뛰지 않는다. 재시작 후에도 quarantine 상태가 유지되며 교정 후 한 번만 적용된다.
- 검증 지표: 실제 시도 횟수, unique failure 수, `fail_count` 의미, CPU·로그량, quarantine 지속성, 후속 LSA, 최종 checksum.
- 연결된 원시 리뷰 ID: `DBA-5Y-31`, `DBDEV-1Y-29`, `앱개발자-5년차-16`

### [TS-X06] index rebuild·제약 rename·통계 갱신 중 논리 RK 보존

- 목적: 물리 인덱스 유지보수와 이름 변경이 활성 RK의 논리 정체성이나 과거 로그 해석을 바꾸지 않는지 확인한다.
- 사전 조건: UK가 활성 RK이며 replica apply가 지연돼 과거 RK 로그가 남아 있다.
- SQL·이벤트 순서:

1. 지원되는 방식으로 RK backing index를 rebuild한다.
2. 제약 또는 인덱스 rename을 지원하면 이름을 변경한다.
3. 통계를 갱신하고 optimizer plan을 바꿀 수 있는 데이터를 적재한다.
4. 각 작업 중 과거·현재 epoch DML을 병렬 적용한다.

- 기대 결과: 논리 RK ID와 key semantics는 유지된다. 물리 인덱스 교체 중 row lookup은 정의된 old/new 구조 또는 barrier를 사용하며 scan fallback 여부도 계약대로다. optimizer 선택이 복제 정확성을 바꾸지 않는다.
- 검증 지표: 논리 RK ID/epoch, 물리 index ID, apply plan, row lookup 수, 누락·오적용 0, 처리량.
- 연결된 원시 리뷰 ID: `DBA-5Y-33`, `사용자-5년차-32`, `DBDEV-5Y-36`, `엔진개발자-3년차-34`

### [TS-X07] surrogate PK의 identity·sequence와 failover

- 목적: PK 없는 기존 테이블에 surrogate PK를 추가할 때 identity/sequence의 값 생성 상태가 HA 전환 후 충돌하지 않는지 확인한다.
- 사전 조건: 여러 기존 행, online backfill 경로, identity 또는 sequence 지원 여부가 확인돼 있다.
- SQL·이벤트 순서:

1. 기존 행에 새 surrogate 값과 PK를 backfill한다.
2. source와 replica에서 sequence/identity durable 위치를 조회한다.
3. backfill 직후 failover하고 새 행을 동시에 삽입하려 시도한다.
4. 이전 primary를 재가입한 뒤 추가 INSERT를 실행한다.

- 기대 결과: 기존 행은 모두 유일한 비NULL PK를 갖고 활성 RK 전환은 원자적이다. 승격한 노드의 다음 값은 이미 사용된 범위와 충돌하지 않는다. CUBRID가 해당 기능을 지원하지 않으면 승인된 대체 키 생성 절차를 시험한다.
- 검증 지표: 중복 PK 0, NULL 0, sequence/identity 위치, backfill 누락 0, 재가입 후 checksum.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-31`, `DBDEV-5Y-28`

### [TS-X08] savepoint·transaction abort에서 RK metadata와 감사 rollback

- 목적: DDL이 transactional/savepoint 범위에 들어가는 경우 abort가 schema epoch, RK metadata와 감사 기록을 일관되게 되돌리는지 확인한다.
- 사전 조건: CUBRID의 실제 transactional DDL 및 savepoint 지원 범위를 먼저 확인한다.
- SQL·이벤트 순서:

1. transaction과 savepoint를 시작한다.
2. RK 후보 추가 또는 REPLICATION 변경을 실행한다.
3. savepoint rollback, 전체 abort, client disconnect, crash를 각각 주입한다.
4. source·replica와 감사 저장소를 조회한다.

- 기대 결과: 지원되는 transactional 경로에서는 미커밋 RK epoch가 외부와 replica에 공개되지 않는다. rollback 감사 이벤트는 실제 결과와 맞고 성공으로 기록되지 않는다. 미지원 경로는 DDL 실행 전에 transaction 경계를 명확히 알린다.
- 검증 지표: catalog/schema epoch, WAL commit marker, audit outcome, replica event 수, orphan index·temporary file 0.
- 연결된 원시 리뷰 ID: `엔진개발자-3년차-30`, `엔진개발자-10년차-28`, `DBDEV-5Y-31`

### [TS-X09] RK catalog 손상 탐지·격리·수리

- 목적: 활성 RK ID, epoch 또는 구성 컬럼 metadata가 손상됐을 때 엔진이 임의의 UK를 자동 선택해 조용히 계속하지 않는지 확인한다.
- 사전 조건: 테스트 전용 fault injection으로 catalog checksum/참조를 손상할 수 있다.
- SQL·이벤트 순서:

1. replica의 활성 RK 참조를 존재하지 않는 논리 ID로 변경하거나 checksum 오류를 주입한다.
2. restart, readiness 검사와 DML apply를 수행한다.
3. 진단/check 명령으로 영향 객체를 조회한다.
4. 승인된 repair 또는 replica reseed를 수행한다.

- 기대 결과: 손상 노드는 apply와 promotion에서 격리되고 다른 후보를 자동 선택하지 않는다. 진단은 민감한 키 값을 노출하지 않고 객체·epoch·오류 종류를 알려 준다. repair 뒤 source 기준 ID와 checksum이 일치해야 해제된다.
- 검증 지표: 손상 탐지율, 잘못된 row 변경 0, promotion 가능=false, repair audit, 최종 catalog/data checksum.
- 연결된 원시 리뷰 ID: `엔진개발자-3년차-31`, `엔진개발자-10년차-29`

### [TS-X10] 여러 DB의 HA readiness 부분 실패와 재실행

- 목적: 한 `cubrid hb start` 범위에 여러 DB가 있을 때 한 DB의 RK 위반이 다른 DB를 어떤 상태로 남기는지 확인한다.
- 사전 조건: DB A는 정상이고 DB B에는 ON/무키 테이블, DB C에는 ON 자식→OFF 부모 FK가 있다.
- SQL·이벤트 순서:

1. 세 DB를 포함한 HA 시작을 수행한다.
2. 프로세스 생성과 검사 단계마다 상태를 수집한다.
3. B만 교정하고 재실행한 뒤 C를 교정해 다시 실행한다.
4. 각 실패 지점에서 stop/cleanup 명령도 실행한다.

- 기대 결과: 명령은 검사 scope와 all-or-nothing/부분 성공 정책을 정확히 따른다. 부분 시작을 허용한다면 DB별 상태와 cleanup 방법이 명확하고, 준비되지 않은 DB는 쓰기·승격되지 않는다. 위반 목록은 한 번에 반환된다.
- 검증 지표: 명령 종료 코드, DB별 process/readiness, 누락 진단 0, orphan process 0, 반복 실행 멱등성.
- 연결된 원시 리뷰 ID: `USER-1Y-33`, `엔진개발자-10년차-33`, `DBDEV-5Y-15`

### [TS-X11] 로그 압축·암호화 키 교체와 장기 RK epoch 해석

- 목적: old RK epoch 로그가 압축·암호화돼 보관되는 동안 codec 또는 암호화 키를 교체해도 복구와 지연 apply가 가능한지 확인한다.
- 사전 조건: 로그 압축/암호화 기능이 지원될 경우에만 실행하며, old epoch 로그와 지연 replica를 준비한다.
- SQL·이벤트 순서:

1. RK epoch 1에서 DML을 기록하고 archive한다.
2. RK를 전환해 epoch 2를 만들고 codec/암호화 키를 교체한다.
3. 지연 replica가 epoch 1부터 재생하게 한다.
4. backup/PITR 환경에서도 동일 archive를 복호화·적용한다.
5. old key를 제거하려 할 때 safe point 검사를 확인한다.

- 기대 결과: record header가 codec·key ID·RK epoch를 결정적으로 식별한다. 필요한 replica/PITR가 남아 있는 동안 old key 삭제를 막고, 해석 실패는 행 변경 전 quarantine된다. 미지원 기능은 범위에서 명시적으로 제외된다.
- 검증 지표: archive decode 성공률, key retention reference, checksum 오류, apply LSA, 잘못된 변경 0, key 삭제 차단 코드.
- 연결된 원시 리뷰 ID: `엔진개발자-3년차-28`, `DBDEV-5Y-33`, `엔진개발자-10년차-31`

### [TS-X12] tenant 정책 격리와 cross-owner FK·소유권 이전

- 목적: 한 테이블 단위 설정이 여러 tenant·owner의 서로 다른 RPO와 권한 경계를 침범하지 않는지 확인한다.
- 사전 조건: tenant A/B 또는 owner A/B가 같은 DB에 있고, 복제 정책 변경 권한과 cross-owner FK 지원 여부가 정의돼 있다.
- SQL·이벤트 순서:

1. tenant A 권한으로 tenant B 테이블을 OFF로 바꾸려 한다.
2. owner A의 ON 자식이 owner B의 부모를 참조하게 한다.
3. 부모 테이블의 소유권 이전 또는 tenant별 단계적 기능 활성화를 수행한다.
4. 감사 이벤트와 failover readiness를 조회한다.

- 기대 결과: 권한 없는 보호 수준 하향은 거부된다. cross-owner 의존성은 전체 ON/OFF 그래프와 권한을 검사한다. 소유권 이전은 기존 RK·정책을 조용히 변경하지 않으며, tenant별 요구를 표현할 수 없다면 기능 제한을 명시한다.
- 검증 지표: 권한 오류 코드, 정책 무변경, 감사 actor/approver, dependency 검사, tenant별 readiness와 checksum.
- 연결된 원시 리뷰 ID: `APPDEV-1Y-38`, `APPDEV-10Y-34`, `DBA-10년차-36`

### [TS-X13] replica membership 변경과 old RK epoch garbage collection

- 목적: 느린 replica 제거·재가입·신규 추가가 구 RK metadata의 안전한 삭제 시점을 잘못 앞당기지 않는지 확인한다.
- 사전 조건: 3개 이상의 replica, old RK epoch backlog가 큰 느린 replica, membership epoch 조회 기능.
- SQL·이벤트 순서:

1. replica R3를 지연시킨 상태에서 RK를 두 번 전환한다.
2. R3를 membership에서 제거하고 old epoch garbage collection을 시도한다.
3. 제거된 R3를 로그만으로 다시 붙이려 한다.
4. R3를 snapshot reseed한 뒤 새 membership epoch로 가입한다.
5. 신규 R4를 추가하고 safe point를 재계산한다.

- 기대 결과: 현재 membership과 PITR 보존 요구를 포함한 전역 safe point 이전에는 old epoch가 삭제되지 않는다. 이미 제거돼 필요한 로그를 잃은 R3는 단순 재가입이 거부되고 reseed가 필요하다. membership 변경과 RK epoch가 감사·manifest에 남는다.
- 검증 지표: membership/RK epoch, replica별 apply LSA, GC 대상 목록, 잘못된 로그 재가입 0, reseed 후 checksum.
- 연결된 원시 리뷰 ID: `엔진개발자-10년차-25`, `엔진개발자-10년차-32`, `DBA-10년차-33`

## 12. 완료 판정

기능 공개 전 최소 다음 조건을 만족해야 한다.

- 모든 Blocker 연결 시나리오가 지원 topology와 인접 버전 조합에서 통과한다.
- 허용된 PK↔UK 전환과 DDL/DML interleaving에서 ON 테이블 checksum 차이와 조용한 log skip이 0건이다.
- 오류 주입 뒤 partial schema, 승격 가능한 stale node, 미분류 `fail_count`가 남지 않는다.
- OFF의 의도된 차이는 cutover LSA·감사·의존성 목록으로 설명 가능하다.
- 문서 SQL은 parser 오류가 아닌 의도한 semantic 결과를 내며 CI에서 자동 실행된다.
- CUBRID가 실제 지원하지 않는 객체·topology 시나리오는 “통과”로 지우지 않고 명시적 비지원 오류와 문서 범위로 검증한다.
