# DBMS를 개발하는 엔진 개발자 / 10년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-23
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 장기 시스템 불변식, 로그·카탈로그 버전, 최악의 crash와 recovery, 혼합 버전 운영, 기능의 장기 유지보수 비용을 검토했다.
- 확인하지 못한 전제: 실제 CUBRID WAL/복제 record, catalog ID 안정성, DDL transaction과 recovery 구현, apply protocol, cache architecture, backup/PITR와 version negotiation 정책은 원문만으로 확인하지 못했다.

## 컨셉·문제 정의·대안 (3개)

## [엔진개발자-10년차-01] 핵심 안전성을 “현재 RK 존재”가 아닌 세대별 행 식별 불변식으로 정의해야 한다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 ON 테이블에 PK/NOT NULL UK RK가 있어야 한다고 하고 4절은 후보 하나 이상 유지를 요구한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 복제 프로토콜, recovery, 데이터 정합성

### 문제
정적 schema 검사는 과거 로그, in-flight transaction, crash redo를 포괄하지 않는다. 안전성은 “모든 미적용 변경이 생성 당시 의미로 정확히 한 행을 찾는다”여야 한다.

### 왜 중요한가
RK 후보가 계속 하나 있어도 구 로그가 `id`를 요구하는데 현재 metadata가 `email`만 알면 적용은 실패한다. 시간에 따라 유지되는 조건이 제품의 실제 불변식이다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE ledger (id BIGINT PRIMARY KEY,
 ref VARCHAR(80) NOT NULL UNIQUE, amount INT) REPLICATION=ON;
UPDATE ledger SET amount=200 WHERE id=9;
ALTER TABLE ledger DROP PRIMARY KEY;
```

지연 standby의 첫 로그는 구 RK 세대가 필요하다.

### 권고안
table마다 monotonic RK epoch를 두고 DML record에 epoch·before-key를 기록한다. epoch 보존·폐기는 등록 replica의 replay horizon, backup/PITR horizon과 함께 정의한다.

### 검증 방법
시간 지연, replica 장기 중지, backup 복원, RK 교체를 조합한 history test에서 모든 record가 정확히 한 행을 변경하는지 확인한다.

## [엔진개발자-10년차-02] 엔진 자동 선택은 영구 호환 계약으로 부적절하다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절은 여러 UK 중 엔진 선택을 “선언 순서가 빠른 것” 등의 예로만 든다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: catalog, upgrade, 복원, 성능

### 문제
catalog scan 순서 같은 구현 세부가 장기 로그 의미가 될 수 있다. 내부 자료구조 최적화나 dump 재정렬만으로 선택이 바뀌면 향후 구현 변경이 제한된다.

### 왜 중요한가
한 번 영속 데이터와 로그가 의존하면 사소한 정렬 변경도 compatibility bug가 된다. 유지보수 비용을 줄이려면 사용자 의도를 stable metadata로 만들어야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE identity_map (
 short_id BIGINT NOT NULL UNIQUE,
 long_name VARCHAR(500) NOT NULL UNIQUE
) REPLICATION=ON;
```

catalog storage 순서가 바뀌어 `long_name`이 선택되면 로그 성능도 달라진다.

### 권고안
명시 RK 지정과 영속 logical ID를 도입한다. 자동 선택은 생성 시 한 번만 수행해 결과를 저장하고 향후 버전에서 재계산하지 않는다고 규정한다.

### 검증 방법
여러 catalog layout과 엔진 버전으로 동일 DB를 open·upgrade한다. 선택 logical ID가 절대 바뀌지 않는지 golden-image test로 확인한다.

## [엔진개발자-10년차-03] 테이블별 OFF가 복제 경계를 넘어 transaction 의미를 바꾼다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 DDL은 모두 복제하지만 OFF 테이블 DML은 제외한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: transaction log, atomicity, failover

### 문제
하나의 transaction이 ON과 OFF 테이블을 함께 변경하면 standby에는 일부 write만 나타난다. commit atomicity가 복제 경계에서 의도적으로 깨지지만 그 의미가 없다.

### 왜 중요한가
원본에서는 두 변경이 함께 성공했어도 failover 후 ON 변경만 보인다. 애플리케이션 불변식이 두 테이블에 걸쳐 있으면 데이터가 논리적으로 손상된다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO orders(id,status) VALUES (10,'PAID');          -- ON
INSERT INTO payment_audit(order_id,message) VALUES (10,'ok'); -- OFF
COMMIT;
```

standby에는 첫 행만 생길 수 있다.

### 권고안
ON/OFF 혼합 transaction의 복제 의미를 명시하고 commit 시 경고·금지하는 strict policy를 검토한다. log record에는 제외된 table 존재를 표시해 failover 영향 분석을 가능하게 한다.

### 검증 방법
ON/OFF/FK/trigger 조합 transaction을 실행하고 source·standby 및 failover 결과가 정의된 정책과 일치하는지 검사한다.

## 용어·기본값·사용자 계약 (2개)

## [엔진개발자-10년차-04] 정책·선택·실행 상태를 하나의 REPLICATION 개념에 담고 있다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 2절은 ON/OFF를 테이블 종류로, 3절은 single에서도 ON 사용 가능, 4절은 실제 복제 여부로 설명한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: catalog API, monitoring, upgrade

### 문제
configured policy, selected RK, runtime eligibility, current apply state가 분리되지 않았다. ON인데 RK가 없어 single에서만 유효한 상태도 존재한다.

### 왜 중요한가
상태를 명확히 분리하지 않으면 cache·monitor·도구가 같은 값을 다르게 해석한다. 새 상태 추가 때마다 기존 API 의미가 흔들린다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (v INT) REPLICATION=ON;
SELECT replication FROM db_class WHERE class_name='t';
```

ON이지만 HA-eligible가 아니다.

### 권고안
`policy=ON/OFF`, `eligibility=VALID/NO_RK/FK_VIOLATION`, `selected_rk`, `runtime=INACTIVE/APPLYING/ERROR`를 별도 계약으로 둔다.

### 검증 방법
single→HA→apply stop→error 상태를 전환하며 각 field가 독립적으로 올바르게 변하는지 state-machine test를 한다.

## [엔진개발자-10년차-05] “필드 없음”의 의미가 생성·upgrade·load 경로마다 정의되지 않았다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2-1절과 8절은 누락 시 ON, 9절은 누락 시 OFF라고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: parser, catalog upgrader, dump reader

### 문제
동일한 null/absent 표현을 신규 문법 default, legacy catalog, legacy dump에서 서로 다르게 처리할 수 있다. 8·9절은 직접 상충한다.

### 왜 중요한가
default가 여러 코드 경로에 복제되면 시간이 지나며 drift한다. ON/OFF 오류는 데이터 보호 여부를 바꾼다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE legacy_event (id INT, body VARCHAR(1000));
```

직접 CREATE, old DB open, old dump load에서 같은지 다른지 정답이 없다.

### 권고안
각 origin을 tagged input으로 구분하고 정책 결정을 하나의 versioned migration layer에 둔다. 8·9절을 통일하고 결정 결과를 manifest에 남긴다.

### 검증 방법
버전별 golden catalog·dump를 모든 upgrade path로 통과시켜 expected policy matrix와 비교한다.

## SQL 문법과 상태 전이 (3개)

## [엔진개발자-10년차-06] RK 교체는 단순 ALTER가 아니라 장기 실행 state machine이다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절·4-2절은 한 SQL의 DROP+ADD만 제시한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DDL, WAL, recovery, replication

### 문제
대형 key 검증·index build·replica 적용·구 epoch drain은 오래 걸린다. 이를 한 parser statement의 성공/실패만으로 표현하면 진행·취소·복구 상태가 사라진다.

### 왜 중요한가
중간 crash, disk full, 사용자 cancel은 정상적인 운영 사건이다. 각 단계가 idempotent하고 재개 가능하지 않으면 대형 테이블에서 사용할 수 없다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE billion_row_t DROP PRIMARY KEY,
 ADD CONSTRAINT uk_external UNIQUE(external_id);
```

수 시간 index build 중 process kill을 가정하면 재시작 상태가 정의되지 않는다.

### 권고안
`VALIDATING/BUILDING/PREPARED/SWITCHED/DRAINING/CLEANED` 상태와 durable transition을 정의한다. 외부 SQL은 비동기 job ID·진행·취소·resume을 제공할 수 있다.

### 검증 방법
각 상태 경계에서 kill, disk full, cancel, retry를 주입한다. orphan object 없이 구/신 상태로 수렴하고 DML이 정확한지 확인한다.

## [엔진개발자-10년차-07] schema epoch와 cache coherence protocol이 필요하다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 운영 중 RK 변경을 허용하지만 session·plan·apply cache를 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: parser, optimizer, log writer, apply worker

### 문제
여러 process와 thread가 cached class representation을 가질 때 단순 invalidation broadcast는 유실될 수 있다. stale descriptor가 새 DML 로그를 만들 위험이 있다.

### 왜 중요한가
cache coherence가 틀리면 catalog는 정상인데 일부 session만 구 RK를 쓰는 희귀 데이터 버그가 된다.

### 재현 또는 구체적 예제

```sql
PREPARE p FROM 'UPDATE account SET balance=? WHERE id=?';
ALTER TABLE account DROP PRIMARY KEY, ADD CONSTRAINT uk_email UNIQUE(email);
EXECUTE p USING 90,10;
```

prepared plan과 replication descriptor의 epoch 검사가 필요하다.

### 권고안
모든 실행·로그 생성 경로가 catalog epoch를 검증하고 mismatch 시 rebind하도록 한다. invalidation은 최적화일 뿐 정확성은 epoch check로 보장한다.

### 검증 방법
invalidation message를 의도적으로 drop하고 오래된 prepared statement를 실행한다. stale RK log가 생성되지 않는지 확인한다.

## [엔진개발자-10년차-08] RK 영향 DDL 분류를 중앙화하지 않으면 규칙이 누락된다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절은 DROP PK/UK 중심이며 type, collation, rename, NOT NULL, partition DDL은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DDL validator, 유지보수 비용

### 문제
각 DDL handler가 자체적으로 후보 수를 검사하면 새 DDL 추가 때 RK 규칙이 빠질 수 있다. 복합 컬럼과 inheritance/partition 등 확장 기능도 위험하다.

### 왜 중요한가
장기 제품에서는 DDL 종류가 늘어난다. 안전 규칙이 흩어지면 회귀 테스트가 모든 조합을 따라가지 못한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE stock (w INT NOT NULL, sku VARCHAR(30) NOT NULL,
 UNIQUE(w,sku)) REPLICATION=ON;
ALTER TABLE stock ALTER COLUMN w DROP NOT NULL;
```

일반 column handler가 RK 자격 상실을 놓칠 수 있다.

### 권고안
DDL 변경 전후 schema를 공통 `validate_replication_invariants()`에 전달한다. semantic diff가 RK-neutral/transition/invalidating을 판정하도록 한다.

### 검증 방법
지원 DDL grammar에서 AST를 생성해 후보 수·컬럼 속성 조합을 fuzzing하고 invariant 위반 성공이 0건인지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [엔진개발자-10년차-09] 복제 프로토콜에 DDL barrier와 epoch fencing이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 DDL이 모두 복제된다고 하지만 병렬 apply·다중 standby ordering은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: replication protocol, parallel apply

### 문제
각 replica의 worker가 DDL 이전 record를 모두 끝낸 뒤 epoch를 전환하고 이후 record를 풀어야 한다. 단순 LSA 순서만으로 transaction dependency가 충분한지 정의되지 않았다.

### 왜 중요한가
한 replica라도 순서를 달리 적용하면 동일 로그로 다른 결과가 된다. 느린 replica는 구 epoch 보존 기간도 늘린다.

### 재현 또는 구체적 예제

```sql
UPDATE customer SET name='before' WHERE id=1;
ALTER TABLE customer DROP PRIMARY KEY, ADD CONSTRAINT uk_email UNIQUE(email);
UPDATE customer SET name='after' WHERE email='a@x';
```

세 사건의 전역 순서가 모든 replica에서 같아야 한다.

### 권고안
barrier record, table epoch, replica acknowledgment, low-water mark protocol을 명시한다. lag limit을 넘은 replica는 재-seed 대상으로 fence한다.

### 검증 방법
worker scheduling과 replica lag을 무작위화하고 packet duplication/reordering을 주입해 최종 상태와 trace order를 검증한다.

## [엔진개발자-10년차-10] split-brain 이후 RK 로그 병합은 정의 가능한 일반 연산이 아니다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 5~7절은 failover만 설명하고 network partition·old primary rejoin은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: HA manager, replication, 데이터 정합성

### 문제
양쪽에서 같은 RK 또는 서로 다른 RK epoch로 write가 생기면 자동 log replay만으로 충돌을 해결할 수 없다.

### 왜 중요한가
RK는 row identity이지 conflict-resolution rule이 아니다. 두 잔액 변경의 올바른 병합은 업무 의미 없이는 결정할 수 없다.

### 재현 또는 구체적 예제

```sql
-- node A
UPDATE account SET balance=900 WHERE id=10;
-- partition 중 node B
UPDATE account SET balance=800 WHERE id=10;
```

재연결 때 last-write-win을 임의 적용해서는 안 된다.

### 권고안
term/epoch 기반 write fencing을 핵심 불변식으로 둔다. divergence가 검출되면 자동 apply를 중단하고 권위 노드 선택·export·repair·re-seed workflow로 전환한다.

### 검증 방법
fencing service 장애까지 포함한 partition test를 한다. stale writer가 차단되고, 실패 시 divergence가 조용히 병합되지 않는지 확인한다.

## [엔진개발자-10년차-11] 승격 가능성은 RK DDL의 durable state와 결합되어야 한다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절은 RK 변경, 7절은 HA 시작 검사만 규정한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: recovery, failover controller

### 문제
replica가 DDL record를 받았지만 index build 또는 catalog switch를 끝내지 않은 순간 승격될 수 있다. 단순 RK 후보 검사만으로 완전한 state인지 알 수 없다.

### 왜 중요한가
부분 준비 노드가 primary가 되면 새 DML을 기록할 안정된 epoch가 없다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY,
 ADD CONSTRAINT pk_external PRIMARY KEY(external_id);
-- replica PREPARED 단계에서 source crash
```

PREPARED replica를 자동 승격할지 규칙이 없다.

### 권고안
각 durable state별 `promotable` 여부와 recovery action을 정의한다. controller는 applied LSA뿐 아니라 schema job state와 epoch readiness를 확인한다.

### 검증 방법
모든 DDL state에서 source kill과 자동 failover를 실행한다. 허용 state만 승격되고 다른 state는 recovery 또는 명확한 차단이 되는지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [엔진개발자-10년차-12] 문자열 RK의 비교 의미를 로그 세대에 고정해야 한다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 NOT NULL UK를 RK로 인정하지만 collation·charset·타입 변경과 혼합 버전 비교는 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: index, log apply, upgrade

### 문제
문자열 유일성과 검색은 collation 구현 버전에 의존한다. 노드 버전 또는 schema epoch가 다르면 같은 bytes가 같거나 다르게 비교될 수 있다.

### 왜 중요한가
source에서는 유일한 key가 standby에서는 두 행과 일치할 수 있다. 이는 잘못된 행 UPDATE로 이어질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE login (name VARCHAR(100) NOT NULL UNIQUE, value INT) REPLICATION=ON;
ALTER TABLE login CHANGE name name VARCHAR(200) COLLATE utf8_bin;
```

변경 전 로그의 비교 규칙을 새 collation으로 처리하면 안 될 수 있다.

### 권고안
RK epoch에 type/collation version을 포함하고 apply가 일치하는 comparator를 선택하게 한다. 지원 불가 변환은 backlog drain 뒤에만 허용한다.

### 검증 방법
대소문자·accent·Unicode normalization 경계값과 혼합 엔진 버전을 조합해 정확히 한 행 탐색을 검증한다.

## [엔진개발자-10년차-13] FK·trigger·cascade로 생성된 내부 DML의 정책이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절은 FK 부모 ON 조건만 다루고 cascade와 trigger는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: executor, log writer, 참조 무결성

### 문제
한 사용자 DML이 cascade/trigger로 ON과 OFF 테이블을 함께 변경할 때 내부 DML을 statement 단위로 재실행할지 row log로 보낼지, 중복 실행을 막는지 없다.

### 왜 중요한가
source에서 trigger 결과를 기록하면서 standby에서도 trigger를 다시 실행하면 중복 변경이 생길 수 있다. OFF 경계가 끼면 더 복잡하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE child (id INT PRIMARY KEY, pid INT,
 FOREIGN KEY(pid) REFERENCES parent(id) ON DELETE CASCADE) REPLICATION=OFF;
DELETE FROM parent WHERE id=1;
```

source의 내부 child DELETE와 standby 동작이 정의되지 않았다.

### 권고안
user/generated DML provenance, ON/OFF 판정, trigger suppression, cascade logging 규칙을 protocol에 명시한다. 안전하지 않은 schema 조합은 DDL 단계에서 차단한다.

### 검증 방법
trigger, cascade, recursive FK, ON/OFF 조합별로 source 생성 로그와 standby 실행 trace를 비교한다.

## [엔진개발자-10년차-14] VIEW 면책은 dependency와 optimizer 유지비를 숨긴다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 6절은 OFF 포함 VIEW의 결과 차이를 책임지지 않는다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: catalog dependency, optimizer, 관리 도구

### 문제
사용자 경고를 구현하려면 nested VIEW, materialization 가능성, prepared plan까지 의존성을 추적해야 한다. 아무 기능도 제공하지 않으면 조용한 오류를 제품 사용자가 떠안는다.

### 왜 중요한가
ON/OFF 변경은 데이터가 아니라 query 의미의 HA 안정성도 바꾼다. dependency 상태가 cache되지 않으면 매번 비싼 graph traversal이 필요하다.

### 재현 또는 구체적 예제

```sql
CREATE VIEW v1 AS SELECT * FROM local_rate;
CREATE VIEW v2 AS SELECT * FROM v1;
ALTER TABLE local_rate REPLICATION=OFF;
```

`v2`까지 transitive impact가 있다.

### 권고안
dependency graph에 replication-safety attribute를 유지하고 incremental propagation·cache invalidation 규칙을 정의한다. 기능 범위와 비용을 명시적으로 수용한다.

### 검증 방법
깊고 넓은 VIEW graph에서 OFF 전환 시간, 영향 목록 정확성, cached plan invalidation을 측정한다.

## 운영·오류·관측 가능성 (2개)

## [엔진개발자-10년차-15] `fail_count`는 복구 의미가 없는 lossy metric이다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체는 `fail_count`의 사건 모델, skip/stop/retry, 영속성과 복구를 정의하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: apply engine, monitoring, repair

### 문제
한 record의 100회 retry와 100개 record skip이 같은 숫자다. counter reset은 손상된 데이터를 고치지 않으며 failover safety도 알려 주지 않는다.

### 왜 중요한가
관측 모델이 실제 상태를 잃으면 사후 forensic과 정확한 repair가 불가능하다.

### 재현 또는 구체적 예제

```sql
UPDATE inventory SET qty=5 WHERE id=100;
UPDATE inventory SET qty=6 WHERE id=101;
```

첫 record 실패 뒤 둘째의 상태를 count로 알 수 없다.

### 권고안
durable failure ledger에 record identity, LSA, table, epoch, reason, retries, blocked range, resolution을 저장한다. count는 여기서 파생한 metric으로만 둔다.

### 검증 방법
retry·skip·restart·repair를 조합하고 ledger가 사건을 잃지 않으며 metric이 정확히 파생되는지 확인한다.

## [엔진개발자-10년차-16] 온라인 repair가 정상 복제와 경쟁할 때의 protocol이 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문은 기존 불일치 탐지·수리와 repair 중 DML을 다루지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: repair tool, replication, 사용자 데이터

### 문제
source snapshot에서 행을 복사하는 동안 새 DML이 들어오면 repair가 최신 값을 덮어쓸 수 있다. 권위 snapshot LSA와 apply pause/resume 경계가 필요하다.

### 왜 중요한가
잘못된 repair는 원래 불일치보다 더 큰 데이터 손실을 만든다. 운영자는 쓰기를 장시간 멈추기 어렵다.

### 재현 또는 구체적 예제

```sql
-- repair가 balance=100을 읽은 뒤
UPDATE account SET balance=90 WHERE id=10;
-- repair가 늦게 standby에 100을 기록
```

최종 standby가 100이면 최신 변경을 잃는다.

### 권고안
repair snapshot LSA, compare-and-set, per-range barrier, 이후 log replay protocol을 정의한다. 충돌은 자동 overwrite하지 않고 재검사한다.

### 검증 방법
repair 중 같은 key를 고빈도로 UPDATE하고 worker crash를 주입한다. 종료 후 source와 standby checksum이 같고 최신 값이 보존되는지 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [엔진개발자-10년차-17] version negotiation과 downgrade horizon이 설계에 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절·8절은 새 SQL/catalog/dump를 도입하지만 혼합 버전과 rollback을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: protocol, rolling upgrade, release engineering

### 문제
신 record를 구 replica가 모를 때 처리, feature activation, 한번 사용한 뒤 downgrade 가능 여부가 없다.

### 왜 중요한가
unknown log가 생성된 뒤 문제를 알면 구 replica는 재생 불능이 되고 upgrade rollback도 막힌다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE cache REPLICATION=OFF;
```

신 source·구 standby에서 실행 가능 여부가 정의되지 않았다.

### 권고안
capability handshake, minimum cluster version, feature bit, record version, point-of-no-return와 downgrade checker를 규정한다. 미지원 기능은 record 생성 전에 차단한다.

### 검증 방법
지원 버전 조합 전체에서 DDL/DML/failover/downgrade를 시험하고 unknown record가 영속되기 전 거부되는지 확인한다.

## [엔진개발자-10년차-18] backup/PITR가 RK epoch history를 함께 보존해야 한다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load ON/OFF와 자동 RK 선택만 다루며 물리 backup·PITR·선택 RK 보존은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: recovery, backup format, 장기 보존

### 문제
복원 snapshot 뒤의 로그를 재생하려면 당시 RK epoch·comparator·constraint identity가 필요하다. load에서 재선택하면 원본 history와 달라진다.

### 왜 중요한가
backup은 수년 보존될 수 있다. 미래 엔진이 과거 epoch를 해석하지 못하면 법적·재해 복구 요구를 충족하지 못한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE person (email VARCHAR(100) NOT NULL UNIQUE,
 phone VARCHAR(30) NOT NULL UNIQUE) REPLICATION=ON;
```

복원 후 다른 UK가 선택되면 이후 archived log 적용이 위험하다.

### 권고안
backup/dump에 선택 logical ID, epoch history, type/collation version과 required engine capability를 저장한다. 지원 종료 정책과 migration converter를 마련한다.

### 검증 방법
여러 메이저 버전의 backup을 최신 엔진에서 복원하고 archived log를 end-to-end 재생해 checksum과 RK history를 비교한다.

## 문서 품질·예제·오탈자 (2개)

## [엔진개발자-10년차-19] 규범 요구와 예제가 분리되지 않아 구현 유지비가 커진다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~7절은 규칙을 예제로 산재시키고 결과를 주로 `OK/ERROR`로 적는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 엔진 개발, QA, 장기 유지보수

### 문제
상태 전이, invariant, error phase/code가 고유 requirement로 정리되지 않았다. 새 DDL이나 mode가 추가될 때 어느 예제를 갱신해야 하는지 알기 어렵다.

### 왜 중요한가
10년 유지할 기능은 문장보다 machine-testable contract가 필요하다. 중복 산문은 시간이 지나며 상충한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE t DROP PRIMARY KEY;
ALTER TABLE t REPLICATION=OFF;
ALTER TABLE t REPLICATION=ON;
```

mode·후보 수·in-flight log별 기대 상태와 error code 표가 없다.

### 권고안
고유 ID가 있는 invariant, state transition table, protocol event와 error catalog를 규범 본문으로 둔다. SQL 예제는 규범 ID에서 자동 시험되게 연결한다.

### 검증 방법
requirements-to-tests 추적표에서 모든 규범 ID가 하나 이상 시험되고 모든 시험이 규범 ID를 참조하는지 검사한다.

## [엔진개발자-10년차-20] 상충 default와 실행 불가 SQL은 release blocker다

- 분류: 문서 품질
- 심각도: Blocker
- 근거 위치: 원문 8절은 legacy 누락=ON, 9절은 누락=OFF이며 2·5절에는 마지막 쉼표, 5-1절에는 `CRATE TABLE`이 있다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 구현자, QA, parser, loaddb

### 문제
두 팀이 반대 default를 구현해도 각자 원문 근거가 있다. syntax error 예제는 semantic validator 시험을 거짓 통과시킬 수 있다.

### 왜 중요한가
ON/OFF default는 실제 데이터 복제 여부를 바꾸므로 문서 결함이 곧 데이터 결함으로 이어진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key (
 value INT,
) REPLICATION=ON;
```

마지막 쉼표 때문에 의도한 HA RK 오류에 도달하지 못한다.

### 권고안
default 결정을 하나로 승인받기 전 구현을 동결한다. 모든 예제를 parser·semantic·execution 단계별 CI에 넣고 정확한 error code를 기록한다. summary는 규범 본문에서 생성한다.

### 검증 방법
문서 consistency lint와 executable example test를 release gate로 둔다. 상충 0건, parser 오탈자 0건, 기대 phase/code 불일치 0건을 확인한다.

## [엔진개발자-10년차-21] partition hierarchy에서 RK identity 소유자가 정의되지 않았다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 table만 다루며 2-3절 출력에는 `partitioned`가 보인다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID 파티션·상속 기능의 실제 지원 범위 확인 필요
- 영향 대상: catalog architecture, constraint manager, replication

### 문제
root와 child가 policy/RK를 각각 저장하는지, local unique가 global identity인지, partition split/move가 logical RK를 보존하는지 없다.

### 왜 중요한가
metadata ownership이 중복되면 root와 child drift가 생긴다. 같은 key가 다른 child에 있으면 apply가 행을 확정하지 못한다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, partitioned, replication
FROM db_class WHERE class_name='sales';
```

child별 selected RK와 global uniqueness가 보이지 않는다.

### 권고안
partition root를 authoritative catalog owner로 둘지 결정하고 routing identity, global/local constraint, split/merge epoch transition을 규정한다.

### 검증 방법
지원 partition DDL, concurrent move와 DML을 model-based test로 실행해 catalog·index·row identity 불변식을 확인한다.

## [엔진개발자-10년차-22] TRUNCATE·bulk·CTAS의 protocol record 유형이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 DDL 전체와 ON DML을 구분하지만 mixed/bulk statement는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: WAL, replication protocol, OFF data

### 문제
TRUNCATE를 schema event로 보낼지 row deletes로 보낼지, CTAS schema와 data를 한 atomic unit으로 표현할지 없다.

### 왜 중요한가
OFF table의 local rows를 schema event가 삭제할 수 있고, row expansion은 log retention을 폭발시킨다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache;
CREATE TABLE archive AS SELECT * FROM orders;
```

record sequence와 policy evaluation이 미정이다.

### 권고안
schema/data/mixed record taxonomy, atomicity, policy bit, replay idempotency, size/backpressure를 protocol에 정의한다.

### 검증 방법
대용량 ON/OFF, cancel, crash, duplicate replay에서 record trace와 최종 page/checksum을 검증한다.

## [엔진개발자-10년차-23] 권한 판정과 감사 기록이 catalog commit과 원자적이지 않을 수 있다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절은 REPLICATION DDL의 authorization·audit를 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: authorization, audit subsystem, catalog

### 문제
권한 revoke와 DDL이 경쟁할 때 어느 snapshot을 쓰는지, policy 변경 성공과 audit event를 같은 durable boundary로 보존하는지 없다.

### 왜 중요한가
변경만 성공하고 audit가 유실되면 보호 등급 하락을 증명할 수 없다. 반대면 rollback된 변경을 실제로 오인한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE payment REPLICATION=OFF;
-- 동시에 ALTER 권한 REVOKE 또는 process crash
```

최종 catalog·audit pair가 미정이다.

### 권고안
authorization snapshot, dedicated privilege, commit ordering, success/failure audit schema와 recovery replay를 정의한다.

### 검증 방법
revoke race, deadlock, crash, audit disk failure를 주입해 catalog와 audit의 허용 상태 집합을 검사한다.

## [엔진개발자-10년차-24] logical RK ID의 namespace와 clone remap 계약이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문은 engine 선택과 load 시 자동 RK 할당만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: catalog IDs, clone/load, archived logs

### 문제
OID는 복원 시 바뀌고 UUID형 logical ID는 clone 간 중복될 수 있다. drop/recreate 때 ID 재사용 여부도 없다.

### 왜 중요한가
old log가 재사용 ID를 새 constraint로 해석하면 형식상 정상인 잘못된 행 탐색이 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE person (
 email VARCHAR(100) NOT NULL UNIQUE,
 phone VARCHAR(30) NOT NULL UNIQUE
) REPLICATION=ON;
```

두 clone과 restore의 selected ID mapping이 필요하다.

### 권고안
cluster/database scoped stable ID, generation, tombstone 비재사용 기간, clone remap manifest와 log ancestry 검증을 정의한다.

### 검증 방법
동시 create, drop/recreate, clone merge, dump/load를 fuzzing해 collision과 stale log 오해석이 없는지 확인한다.

## [엔진개발자-10년차-25] RK epoch garbage collection의 전역 safe point가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 기존 1·9·18번 근거인 원문에는 구 metadata 폐기 조건이 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: catalog, index storage, replica, backup

### 문제
old epoch/index/comparator는 모든 replica, oldest transaction, backup/PITR horizon이 지난 뒤에만 제거할 수 있다. 전역 계산과 탈퇴 replica 처리가 없다.

### 왜 중요한가
조기 GC는 replay 불능, 무기한 보존은 storage leak과 미래 코드 유지비를 만든다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
```

7일 지연 replica와 30일 PITR가 동시에 있으면 safe point가 달라진다.

### 권고안
replica low-water mark, transaction horizon, backup retention, membership tombstone을 합친 monotonic safe point와 forced re-seed 정책을 설계한다.

### 검증 방법
각 horizon을 독립적으로 진행·후퇴시키고 premature delete와 unbounded retention이 없는지 확인한다.

## [엔진개발자-10년차-26] log codec canonicalization이 타입·collation 의미를 장기 보존하지 않는다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문은 RK log binary 표현, compression, endian, archive format을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log codec, cross-version apply, archive

### 문제
복합 RK의 length, NULL marker, numeric scale, Unicode/collation version을 canonical format으로 고정하지 않으면 플랫폼·버전별 decoder 결과가 다를 수 있다.

### 왜 중요한가
같은 bytes가 다른 key로 해석되면 checksum은 통과해도 다른 행을 찾는다. archive는 수년 뒤 다른 CPU/버전에서 재생된다.

### 재현 또는 구체적 예제

```sql
UPDATE price SET amount=10.00
WHERE region='가' AND external_id='A';
```

numeric scale과 multibyte key의 wire representation이 필요하다.

### 권고안
versioned canonical encoding, endian, field tags, comparator version, authenticated checksum과 unknown-version fail-closed를 정의한다.

### 검증 방법
cross-architecture golden vector와 old/new codec round-trip으로 byte 및 semantic equality를 검증한다.

## [엔진개발자-10년차-27] duplicate replay와 ack loss의 정확히 한 번 가시성 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문은 DDL/DML 정상 적용만 설명하고 duplicate delivery·ack loss는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: apply protocol, crash recovery, fail_count

### 문제
RK-changing UPDATE나 DDL barrier가 적용 후 ack 전에 crash하면 동일 record가 다시 도착할 수 있다. duplicate 성공과 진짜 0-row 오류의 구분이 없다.

### 왜 중요한가
at-least-once transport에서 duplicate는 정상이다. 이를 corruption으로 세면 fail_count가 늘고, 무조건 skip하면 실제 누락을 숨긴다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET email='new@x' WHERE email='old@x';
```

동일 record를 두 번 처리할 결과가 필요하다.

### 권고안
transaction/record ID, durable applied watermark, before/after proof와 duplicate classification을 정의한다.

### 검증 방법
record duplicate, ack loss, worker restart, partial page flush를 systematic fault injection해 exactly-once visible result를 확인한다.

## [엔진개발자-10년차-28] nested transaction·savepoint에서 schema epoch publication 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 ALTER 성공·실패만 다루며 savepoint·transactional DDL은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID DDL transaction 지원 범위 확인 필요
- 영향 대상: transaction manager, catalog, cache coherence

### 문제
savepoint rollback과 deadlock victim 처리 중 provisional RK epoch가 다른 session/log writer에 보일 수 있는지 없다.

### 왜 중요한가
rollback된 schema로 DML log 한 건만 생성돼도 영구적으로 해석할 metadata가 없다.

### 재현 또는 구체적 예제

```sql
BEGIN;
SAVEPOINT s;
ALTER TABLE t REPLICATION=OFF;
ROLLBACK TO SAVEPOINT s;
COMMIT;
```

지원 여부와 epoch visibility가 필요하다.

### 권고안
DDL auto-commit/savepoint matrix, provisional catalog namespace, publication at commit, abort invalidation과 reserved log cleanup을 규정한다.

### 검증 방법
savepoint·deadlock·statement/transaction abort를 모든 DDL state에서 주입해 catalog/log/cache 상태를 model과 비교한다.

## [엔진개발자-10년차-29] catalog 손상 시 자동 RK 재선택은 위험한 repair다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 2-3절은 정상 조회, 7절은 후보 존재 검사만 다룬다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: checkdb, catalog recovery, 데이터 정합성

### 문제
selected logical ID, column order, index root, epoch chain이 손상됐을 때 후보를 다시 골라 계속할지 중단할지 없다.

### 왜 중요한가
자동 재선택은 현재 query를 살릴 수 있지만 archived/in-flight log의 의미를 바꿔 더 큰 손상을 만든다.

### 재현 또는 구체적 예제
시험 hook으로 selected RK가 존재하지 않는 constraint ID를 가리키게 한다.

```sql
SELECT class_name, replication FROM db_class WHERE class_name='orders';
```

ON 조회만 정상일 수 있다.

### 권고안
cross-catalog integrity checker, fail-closed quarantine, evidence-preserving dump, 승인 기반 repair/re-seed를 정의한다. 자동 재선택을 금지한다.

### 검증 방법
각 metadata component를 독립 손상시켜 탐지, 승격 차단, forensic 보존과 repair 결과를 검증한다.

## [엔진개발자-10년차-30] RK DDL의 admission control과 WAL 생존 공간이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 4-2절은 key 추가를 허용하지만 자원 quota·temp cleanup은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: storage manager, WAL, 전체 DB 가용성

### 문제
shadow index가 disk를 소진하면 WAL조차 쓸 공간이 없어 전체 DB recovery가 위험해질 수 있다.

### 왜 중요한가
maintenance 실패가 기존 workload와 recovery 능력까지 파괴해서는 안 된다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE event_10b ADD CONSTRAINT uk_uuid UNIQUE(event_uuid);
```

95%에서 disk full을 가정한다.

### 권고안
WAL reserved space, preflight estimate, per-job quota, throttle, crash-cleanup journal과 orphan scavenger를 설계한다.

### 검증 방법
disk full, quota, cancel, repeated crash를 주입해 WAL recovery·old RK·normal DML과 space reclamation을 검증한다.

## [엔진개발자-10년차-31] 암호화 키 교체와 오래된 RK 로그 복호화 수명이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문은 RK가 개인정보 UK일 수 있으나 log 암호화·키 rotation·폐기를 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: encrypted log/archive, PITR, 개인정보

### 문제
RK before/after가 archive에 오래 남을 때 encryption key를 폐기하면 PITR가 불가능하고, 무기한 보존하면 보안 위험이다.

### 왜 중요한가
데이터 보존 기간과 복구 기간, crypto key lifetime이 함께 설계돼야 한다. email 같은 RK는 민감하다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET email='new@example.com'
WHERE email='old@example.com';
```

old/new key가 포함된 1년 archive의 key rotation 결과가 없다.

### 권고안
archive encryption envelope, key version, rotation/re-encryption, destruction horizon과 PITR 지원 기간을 하나의 lifecycle로 정의한다.

### 검증 방법
여러 key version archive를 복구하고 rotation·revocation 전후 허용된 PITR와 원문 노출을 확인한다.

## [엔진개발자-10년차-32] replica membership 변경이 RK epoch safe point를 교란할 수 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 고정 master/slave만 설명하고 replica 추가·제거·재가입은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: membership service, epoch GC, HA

### 문제
느린 replica를 제거한 직후 구 epoch를 GC하고 같은 replica가 old snapshot으로 재가입하면 필요한 metadata가 없다.

### 왜 중요한가
membership tombstone과 data/log horizon이 원자적이지 않으면 retired node가 stale history를 다시 들여올 수 있다.

### 재현 또는 구체적 예제
replica R을 RK epoch 3에서 제거하고 primary가 epoch 5까지 진행·GC한 뒤 R을 재연결한다고 하자.

```sql
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
```

R은 incremental replay가 불가능할 수 있다.

### 권고안
membership generation, replica tombstone, minimum snapshot epoch, full re-seed handshake와 GC safe point를 결합한다.

### 검증 방법
replica add/remove/rejoin을 DDL transition·GC와 교차해 stale incremental join이 허용되지 않는지 확인한다.

## [엔진개발자-10년차-33] 다중 DB HA 시작의 부분 성공을 표현하는 recovery model이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절은 위반 시 HA 실행 불가라고만 하며 DB·node·group 범위가 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: HA orchestrator, service manager, operator

### 문제
DB A 검사는 성공하고 B가 실패했을 때 A process를 rollback할지 유지할지, command journal과 재시도 상태가 없다.

### 왜 중요한가
부분 기동은 관리 plane과 실제 data plane 상태를 다르게 만들고 자동화가 HA 정상으로 오인하게 한다.

### 재현 또는 구체적 예제
DB A는 정상이고 DB B에 무키 ON table이 있다고 하자.

```sql
CREATE TABLE scratch (v INT) REPLICATION=ON;
```

group start failure의 허용 state가 없다.

### 권고안
start transaction scope, prepare/commit/abort phases, per-DB status, cleanup idempotency와 resumable operation ID를 정의한다.

### 검증 방법
각 DB start 단계에 failure/crash를 주입하고 orchestrator journal과 process/catalog 상태가 허용 state로 수렴하는지 확인한다.

## [엔진개발자-10년차-34] 상태 공간을 탐색할 formal model과 test oracle이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문은 개별 예시만 제공하고 동시성·장애의 전체 상태 기계를 규범화하지 않는다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 설계 검증, QA, 장기 유지보수

### 문제
RK epoch, DDL job, transaction, replica apply, leadership term, membership을 조합하면 사람이 예제로 모든 interleaving을 다룰 수 없다.

### 왜 중요한가
희귀 순서 버그가 데이터 손상으로 이어진다. 구현 test만으로는 빠진 상태를 발견하기 어렵다.

### 재현 또는 구체적 예제

```sql
UPDATE t SET v=1 WHERE id=1;
ALTER TABLE t DROP PRIMARY KEY, ADD CONSTRAINT uk_b UNIQUE(b);
```

두 작업과 crash/failover의 interleaving 수가 급증한다.

### 권고안
핵심 invariant와 transition을 TLA+/state-machine 같은 executable model 또는 동등한 model checker로 정의하고 implementation trace와 대조한다.

### 검증 방법
model에서 safety violation 0, injected broken transition 탐지, production trace conformance를 release gate로 확인한다.

## [엔진개발자-10년차-35] 대규모 catalog backfill의 중단·재개·downgrade가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문은 기존 catalog에 REPLICATION·selected RK 필드를 추가하는 upgrade 절차를 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: catalog upgrader, rolling upgrade, 기존 고객

### 문제
수십만 table에 default와 selected RK를 채우는 중 crash하면 어느 object까지 변환됐는지, 구 engine이 부분 catalog를 열 수 있는지 없다.

### 왜 중요한가
catalog migration은 data file open path에 있으며 부분 실패가 전체 DB를 기동 불능으로 만들 수 있다.

### 재현 또는 구체적 예제
100만 class 중 50만 개를 backfill한 시점에 process kill을 가정한다.

```sql
SELECT class_name, replication FROM db_class;
```

NULL/new/legacy row 혼합 상태의 reader 계약이 없다.

### 권고안
versioned shadow catalog, resumable checkpoint, idempotent backfill, preflight, atomic activation bit와 downgrade converter를 정의한다.

### 검증 방법
모든 checkpoint에서 crash/restart/downgrade를 수행하고 old 또는 new의 완전한 readable state로 수렴하는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 15개
- 최종 리뷰 항목 수: 35개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID partition·bulk·savepoint·다중 DB HA의 실제 지원 범위, catalog ID·replication codec·membership·암호화 key 관리의 현행 구조, formal model과 catalog upgrader 구현
