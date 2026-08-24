# DBMS를 개발하는 엔진 개발자 / 3년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-23
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 복제 로그와 카탈로그 표현, DDL 적용 순서, schema/RK 캐시 무효화, 오류 경로와 자동 회귀 테스트 관점에서 검토했다.
- 확인하지 못한 전제: 실제 CUBRID 소스 코드의 로그 레코드 구조, 카탈로그 컬럼·OID 안정성, DDL transaction 구현, apply 병렬성, cache 구조, 오류 코드와 `fail_count` 구현은 원문만으로 확인하지 못했다.

## 컨셉·문제 정의·대안 (3개)

## [엔진개발자-3년차-01] RK 존재 조건과 로그 해석 가능 조건이 구분되지 않았다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 ON 테이블에 RK가 필요하다고 하고 4절은 후보 하나 이상을 유지하도록 제한한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 복제 로그, apply 엔진, 데이터 정합성

### 문제
현재 카탈로그에 RK가 하나 있다는 조건만 있다. DML 로그가 생성될 당시의 RK 정의가 apply 시점까지 해석 가능해야 한다는 조건은 없다.

### 왜 중요한가
standby가 늦으면 구 RK로 기록된 UPDATE 뒤에 RK 변경 DDL이 이미 source에서 끝날 수 있다. apply가 현재 카탈로그만 보면 구 로그의 키 컬럼을 알 수 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE account (id INT PRIMARY KEY, email VARCHAR(100) NOT NULL UNIQUE, balance INT) REPLICATION=ON;
UPDATE account SET balance=900 WHERE id=10;
ALTER TABLE account DROP PRIMARY KEY;
```

첫 로그가 `id=10`을 저장하고 현재 RK가 email이면 apply가 어느 schema를 사용할지 불명확하다.

### 권고안
각 DML 로그에 RK schema epoch 또는 안정된 constraint ID와 before-key를 기록한다. 모든 standby의 low-water mark가 구 epoch를 넘기 전까지 구 정의를 보존한다.

### 검증 방법
apply를 정지한 채 DML과 RK 변경을 쌓은 뒤 재개한다. 구 로그가 성공하고 source/standby checksum과 오류 수가 같은지 확인한다.

## [엔진개발자-3년차-02] 여러 UK 자동 선택 함수의 결정성 요구가 없다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 여러 UK 중 엔진이 선택하며 선언이 빠른 순서 등을 예로 든다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 카탈로그, source/standby, 복원

### 문제
“예”는 구현 규칙이 아니다. catalog scan 순서, hash iteration, constraint OID 중 무엇을 쓰는지에 따라 노드·재시작·load 후 선택이 달라질 수 있다.

### 왜 중요한가
비결정적 순회 결과에 의존하면 같은 스키마에서 source와 standby가 다른 RK를 택한다. 테스트에서 우연히 통과하고 운영에서만 실패할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE contact (
 email VARCHAR(100) NOT NULL CONSTRAINT uk_email UNIQUE,
 phone VARCHAR(30) NOT NULL CONSTRAINT uk_phone UNIQUE
) REPLICATION=ON;
```

catalog reload 전후 `uk_email`과 `uk_phone` 중 선택이 같아야 한다.

### 권고안
PK 우선 뒤에는 영속 constraint ID 또는 완전한 정렬 기준을 정의한다. 더 안전하게 선택 결과를 카탈로그에 저장하고 DDL로 복제한다.

### 검증 방법
제약 생성·이름 순서를 조합하고 재시작, unload/load, 통계 갱신을 반복한다. RK 선택 결과가 항상 동일한지 property test로 확인한다.

## [엔진개발자-3년차-03] 모든 컬럼 대안 배제의 엔진 비용 모델이 없다

- 분류: 성능
- 심각도: Major
- 근거 위치: 원문 1~4절은 PK/NOT NULL UK만 RK로 인정하고 무키 ON 테이블은 HA에서 금지한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 엔진 설계, 성능, 기존 사용자

### 문제
모든 컬럼을 before-image로 기록하는 대안과 RK 방식의 로그 크기·탐색 비용·중복 처리 비교가 없다. 결과적으로 기능 제한의 근거를 구현·시험 기준으로 바꿀 수 없다.

### 왜 중요한가
설계 선택은 측정 가능한 기준이 있어야 회귀를 판단할 수 있다. 넓은 복합 UK는 모든 컬럼 방식과 비용 차이가 작을 수도 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE wide_t (
 k1 VARCHAR(500) NOT NULL, k2 VARCHAR(500) NOT NULL,
 payload VARCHAR(4000), UNIQUE(k1,k2)
) REPLICATION=ON;
```

이 RK의 로그와 비교 비용이 짧은 정수 PK보다 얼마나 큰지 기준이 없다.

### 권고안
row width, RK width, column count, duplicate/NULL에 따른 비용 모델과 benchmark를 스펙 부록에 둔다. RK 최대 폭 제한이나 경고 기준도 결정한다.

### 검증 방법
정수 PK, 복합 문자열 UK, 모든 컬럼 prototype을 같은 DML로 비교해 로그 byte, CPU, apply TPS를 측정한다.

## 용어·기본값·사용자 계약 (2개)

## [엔진개발자-3년차-04] 후보와 선택 RK의 카탈로그 표현이 정의되지 않았다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1절은 후보와 선택 결과를 구분하지만 2-3절은 `replication` 열만 보여 준다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 카탈로그, cache, 조회 도구

### 문제
선택 RK를 계산값으로 둘지 영속 metadata로 둘지, constraint를 이름·OID 중 무엇으로 참조할지 없다. 복합 키 컬럼 순서와 schema version 표현도 없다.

### 왜 중요한가
이 결정은 cache invalidation, log decoding, backup 호환성을 모두 좌우한다. 이름은 rename될 수 있고 OID는 load 후 달라질 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE contact RENAME CONSTRAINT uk_email AS uk_login;
```

이름 기반 RK 참조라면 rename과 로그 기록을 원자적으로 갱신해야 한다.

### 권고안
stable logical constraint ID, ordered column IDs, RK epoch, ON/OFF를 카탈로그 schema로 명시한다. 이름 변경과 drop/recreate 시 ID 규칙을 추가한다.

### 검증 방법
제약 rename, column rename, unload/load 뒤 RK reference가 유효하고 과거 로그도 적용되는지 확인한다.

## [엔진개발자-3년차-05] 생략 기본값의 적용 계층이 서로 충돌한다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2-1절은 CREATE 생략 시 ON, 8절은 legacy load 필드 누락 시 ON, 9절은 누락 시 OFF라고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: parser, catalog upgrade, loaddb

### 문제
신규 parser default, catalog migration default, dump deserializer default가 구분되지 않고 8·9절은 반대다. 구현 위치마다 다른 기본값이 들어갈 위험이 있다.

### 왜 중요한가
같은 테이블이 생성 경로에 따라 ON/OFF가 달라지면 재현이 어렵고 데이터 보호가 깨진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE legacy_log (id INT, body VARCHAR(1000));
```

직접 CREATE, 구 catalog upgrade, legacy loaddb 세 경로의 결과를 하나의 표로 정할 수 없다.

### 권고안
세 경로의 default를 별도 규범으로 결정하고 단일 helper가 정책을 적용하게 한다. 8·9절 상충을 해소하고 선택 결과를 load report에 남긴다.

### 검증 방법
동일 DDL을 세 생성 경로로 구성해 catalog bit와 HA 검사 결과를 비교하는 parameterized test를 만든다.

## SQL 문법과 상태 전이 (3개)

## [엔진개발자-3년차-06] 복합 ALTER 검증과 commit 순서가 정의되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13은 DROP+ADD를 한 SQL로 허용한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DDL 엔진, 카탈로그, 복제 정합성

### 문제
새 키 유일성 검사, 인덱스 생성, 구 키 제거, RK 포인터 변경, DDL 로그 기록의 순서와 rollback이 없다.

### 왜 중요한가
ADD가 실패한 뒤 구 키가 이미 삭제되면 RK 0개 상태가 된다. crash recovery가 중간 journal을 잘못 재생해도 같은 문제가 난다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE coupon (id INT PRIMARY KEY, code INT) REPLICATION=ON;
INSERT INTO coupon VALUES (1,7),(2,7);
ALTER TABLE coupon DROP PRIMARY KEY, ADD CONSTRAINT uk_code UNIQUE(code);
```

새 UK 실패 시 구 PK/RK가 완전히 남아야 한다.

### 권고안
validate → build shadow index → atomic catalog switch → log commit → deferred old cleanup 상태 기계를 정의한다. 각 단계 rollback/redo를 명시한다.

### 검증 방법
각 단계에 중복, disk full, crash를 주입한다. restart 후 구/신 중 완전한 한 상태만 존재하는지 확인한다.

## [엔진개발자-3년차-07] RK 변경 시 schema cache 무효화 범위가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 운영 중 RK 후보 추가·삭제·교체를 허용하지만 cache 동작은 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: query executor, log writer, apply worker

### 문제
세션별 class cache, prepared statement, log writer와 apply worker가 구 RK descriptor를 들고 있을 수 있다. DDL commit 뒤 어느 시점에 무엇을 invalidate하는지 없다.

### 왜 중요한가
카탈로그는 새 RK인데 worker cache는 구 RK면 같은 transaction이 다른 key format의 로그를 만들 수 있다.

### 재현 또는 구체적 예제

```sql
PREPARE s FROM 'UPDATE account SET balance=? WHERE id=?';
ALTER TABLE account DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
EXECUTE s USING 900,10;
```

prepared statement 재검증과 log descriptor 갱신 결과가 불명확하다.

### 권고안
DDL commit에 schema epoch를 증가시키고 관련 class cache, plan cache, replication descriptor를 원자적으로 invalidate한다. stale epoch 사용은 retry하게 한다.

### 검증 방법
많은 session이 prepared DML을 반복하는 중 RK를 바꾼다. 로그 epoch, plan 재컴파일, 결과 checksum을 검사한다.

## [엔진개발자-3년차-08] RK 구성 컬럼 DDL 분류가 완전하지 않다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 PK/UK DROP 중심이며 복합 키, rename, type, collation, NULL 변경은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DDL validator, 복제 로그

### 문제
`DROP NOT NULL`, type 변경, column rename, 복합 키 일부 변경이 RK 파괴 또는 epoch 변경인지 정의되지 않았다.

### 왜 중요한가
UK 컬럼 하나가 nullable이면 후보 자격이 사라지고 collation 변경은 동일 값 비교 의미를 바꾼다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE stock (warehouse INT NOT NULL, sku VARCHAR(30) NOT NULL,
 UNIQUE(warehouse,sku)) REPLICATION=ON;
ALTER TABLE stock ALTER COLUMN warehouse DROP NOT NULL;
```

마지막 후보면 거부해야 하지만 validator rule이 스펙에 없다.

### 권고안
모든 column/constraint DDL을 `RK-neutral`, `RK-epoch-change`, `RK-invalidating`으로 분류하고 후보 수 검사를 공통 함수로 수행한다.

### 검증 방법
DDL 종류 × 후보 수 × single/HA 조합을 생성한 table-driven test로 예상 허용·거부를 검사한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [엔진개발자-3년차-09] DDL과 DML 로그 사이 barrier가 명시되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 모든 DDL을 복제하고 RK 관련 DML 제한을 설명하지만 적용 순서는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log writer, parallel apply, 데이터 정합성

### 문제
병렬 apply에서 RK 변경 DDL 전후의 DML이 재정렬될 수 있다. table 단위 barrier와 transaction dependency가 없다.

### 왜 중요한가
신 RK DML이 DDL보다 먼저 적용되거나 구 RK DML이 구 metadata 폐기 뒤 적용되면 행을 못 찾는다.

### 재현 또는 구체적 예제

```sql
UPDATE customer SET name='A' WHERE id=10;
ALTER TABLE customer DROP PRIMARY KEY, ADD CONSTRAINT uk_email UNIQUE(email);
UPDATE customer SET name='B' WHERE email='a@example.com';
```

세 로그는 모든 worker에서 이 순서를 지켜야 한다.

### 권고안
DDL record를 table-scoped apply barrier로 정의하고 앞선 DML 완료 후 epoch를 switch한다. 뒤 DML은 새 epoch 확인 후 dispatch한다.

### 검증 방법
parallel apply thread 수와 지연을 무작위화해 수천 번 실행한다. trace ordering과 최종 checksum을 assert한다.

## [엔진개발자-3년차-10] HA 시작 검사와 동시 DDL 사이 TOCTOU가 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 7절은 HA 시작 시 RK·FK를 검사하지만 검사 원자성은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: HA state manager, DDL engine

### 문제
검사가 한 테이블을 지난 뒤 다른 session이 RK를 제거하면 검사 통과와 HA enable 사이에 위반 상태가 생긴다.

### 왜 중요한가
검사한 상태와 실제 시작 상태가 같아야 사전 검사가 의미 있다. 테이블 수가 많을수록 틈이 길어진다.

### 재현 또는 구체적 예제

```sql
-- HA 검사 중 다른 session
ALTER TABLE audit DROP PRIMARY KEY;
```

DDL 차단, schema generation 재확인, 검사 재시도 중 무엇을 할지 없다.

### 권고안
검사 시작 schema generation을 기록하고 HA enable 직전 compare-and-swap 한다. 변경되면 재검사하거나 RK 관련 DDL을 잠근다.

### 검증 방법
수만 테이블 검사 중 DDL fuzzing을 실행한다. 위반 schema로 HA가 한 번도 시작되지 않는지 확인한다.

## [엔진개발자-3년차-11] RK DDL 중 crash와 failover의 recovery state가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절은 운영 중 RK 변경, 7절은 HA 전환을 다루지만 둘의 중첩은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: recovery manager, failover, 카탈로그

### 문제
index build, catalog switch, DDL log apply 중 장애가 나면 승격 노드가 어느 epoch를 사용해야 하는지 없다.

### 왜 중요한가
부분 index와 새 RK pointer가 섞이면 정상 조회는 되어도 복제 행 탐색만 실패하는 잠복 버그가 된다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY,
 ADD CONSTRAINT pk_external PRIMARY KEY(external_id);
-- internal stage마다 process kill 및 failover
```

기대 상태는 완전한 구 또는 신 epoch 하나다.

### 권고안
WAL redo/undo와 failover eligibility를 RK DDL state별로 정의한다. 미완료 state는 승격 전 recovery 완료 또는 승격 거부로 처리한다.

### 검증 방법
각 log record 경계에서 kill injection을 하고 restart/failover한다. catalog, index, cache epoch, DML 결과가 한 상태로 일치하는지 검사한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [엔진개발자-3년차-12] RK 값 UPDATE의 before/after image 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 RK constraint DDL만 설명하고 RK 컬럼 값 UPDATE는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log record, apply 엔진, 재시도

### 문제
standby 행 탐색에는 before RK가 필요하고 변경에는 after RK가 필요하다. 로그 재적용 시 이미 after 상태인 경우의 멱등성도 정의되지 않았다.

### 왜 중요한가
after만 저장하면 첫 적용에서 행을 못 찾고, before만 저장하면 변경 결과 검증과 재적용 판단이 어렵다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (email VARCHAR(100) NOT NULL UNIQUE, name VARCHAR(30)) REPLICATION=ON;
UPDATE member SET email='new@x' WHERE email='old@x';
```

로그는 old/new를 함께 다룰 필요가 있다.

### 권고안
RK-changing DML record에 before/after image와 epoch를 정의한다. 0행, 2행 이상, after 충돌, duplicate replay의 상태 전이를 명시한다.

### 검증 방법
단일·복합 RK UPDATE와 duplicate replay, apply crash를 조합해 정확히 한 행만 최종 변경되는지 확인한다.

## [엔진개발자-3년차-13] FK 검증이 전체 dependency graph와 cascade를 다루지 않는다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절은 ON 자식의 참조 부모도 ON이어야 한다고 하나 다단계·순환·cascade는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: FK validator, DDL engine, apply

### 문제
CREATE뿐 아니라 부모 ON→OFF ALTER가 기존 자식들을 역방향으로 찾아야 한다. 순환 FK와 `ON DELETE/UPDATE CASCADE`에서 생성되는 내부 DML의 복제 정책도 없다.

### 왜 중요한가
직접 테이블만 검사하면 기존 FK를 통해 위반 상태를 만들 수 있다. cascade는 한 statement에서 여러 table을 바꾼다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE child (id INT PRIMARY KEY, pid INT,
 FOREIGN KEY(pid) REFERENCES parent(id) ON DELETE CASCADE) REPLICATION=ON;
ALTER TABLE parent REPLICATION=OFF;
```

ALTER validator가 child edge를 찾아 거부해야 한다.

### 권고안
catalog FK graph의 양방향 traversal과 cycle guard를 구현 규범으로 명시한다. cascade 내부 DML의 ON/OFF 판정 시점을 정의한다.

### 검증 방법
chain, diamond, cycle, self-FK와 모든 ON/OFF 조합을 생성해 CREATE/ALTER/HA 검사를 자동화한다.

## [엔진개발자-3년차-14] VIEW 의존성 cache가 OFF 전환 후 stale해질 수 있다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절은 OFF 테이블 포함 VIEW 결과가 다를 수 있다고 하지만 의존성 추적과 cache 갱신은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: view cache, query optimizer, 사용자

### 문제
테이블 ON→OFF 전환 뒤 cached view plan과 의존성 경고 목록이 갱신되지 않으면 운영 도구가 영향 VIEW를 누락할 수 있다.

### 왜 중요한가
VIEW는 중첩될 수 있어 전이적 dependency invalidation이 필요하다. 객체는 실행되지만 결과만 다르므로 탐지가 더 어렵다.

### 재현 또는 구체적 예제

```sql
CREATE VIEW v1 AS SELECT * FROM local_rate;
CREATE VIEW v2 AS SELECT * FROM v1;
ALTER TABLE local_rate REPLICATION=OFF;
```

`v2`까지 영향 상태가 전파되어야 한다.

### 권고안
REPLICATION 속성을 schema dependency version에 포함하고 모든 transitive view plan/metadata cache를 invalidate한다.

### 검증 방법
깊은 중첩 VIEW를 준비해 plan cache를 채운 뒤 ON/OFF를 전환한다. 모든 영향 VIEW의 재컴파일과 경고 상태를 확인한다.

## 운영·오류·관측 가능성 (2개)

## [엔진개발자-3년차-15] `fail_count`가 오류 사건과 apply 상태를 표현하지 못한다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체는 구체적인 `fail_count` 증가·재시도·초기화 계약을 제공하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: apply 엔진, DBA, 모니터링

### 문제
동일 record 재시도 횟수와 고유 실패 record 수가 구분되지 않는다. 오류 후 skip, table quarantine, global stop 중 어느 동작인지도 없다.

### 왜 중요한가
단순 숫자는 테스트 assertion과 운영 복구 모두에 부족하다. skip 후 계속하면 데이터 분기가 확대될 수 있다.

### 재현 또는 구체적 예제

```sql
UPDATE inventory SET qty=5 WHERE id=100;
UPDATE inventory SET qty=6 WHERE id=101;
```

첫 target가 없을 때 둘째 처리 여부와 count 변화가 불명확하다.

### 권고안
error event ID, LSA, table, RK epoch, retry count, 상태 `RETRY/QUARANTINE/STOP/REPAIRED`를 저장한다. counter reset과 repair를 분리한다.

### 검증 방법
0행·복수행·schema mismatch를 주입해 event와 state transition을 assert하고 restart 후 영속성을 확인한다.

## [엔진개발자-3년차-16] 오류 경로에서 민감 RK 값과 진단 정보의 균형이 없다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문 7절은 위반 목록, 여러 절은 ERROR만 요구하며 진단 field와 접근 권한은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 로그 시스템, 사용자 개인정보, 기술지원

### 문제
행 탐색 실패를 진단하려면 RK가 필요하지만 email·전화번호 같은 값은 개인정보일 수 있다. 원문은 원문 값, hash, masking, 권한 정책을 정하지 않는다.

### 왜 중요한가
값을 전부 숨기면 복구가 어렵고 로그에 그대로 쓰면 개인정보가 장기간 남는다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET name='Kim' WHERE email='person@example.com';
```

적용 실패 로그에 email을 그대로 기록할지 정의가 필요하다.

### 권고안
기본 로그에는 keyed hash와 constraint ID만 기록하고 권한 있는 진단 명령에서 제한적으로 원문을 보이게 한다. 보존 기간과 audit를 정한다.

### 검증 방법
민감 RK 오류를 발생시키고 일반 로그·관리자 조회·감사 로그의 노출 범위를 역할별로 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [엔진개발자-3년차-17] 로그·카탈로그 버전 협상 없이 롤링 업그레이드를 정의할 수 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절은 새 SQL/카탈로그, 8절은 새 dump field를 도입하지만 mixed-version HA는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log decoder, catalog upgrader, HA

### 문제
구버전 standby가 RK epoch와 REPLICATION DDL record를 읽는지, 모르면 source가 생성 전 차단하는지 없다.

### 왜 중요한가
unknown record를 기록한 뒤 발견하면 standby가 영구 중단될 수 있다. rollback 가능한 시점도 사라진다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE local_cache REPLICATION=OFF;
```

신 source/구 standby에서 이 DDL의 허용 여부가 없다.

### 권고안
log format version, cluster capability negotiation, feature activation gate, downgrade boundary를 정의한다. unknown record는 생성 전에 차단한다.

### 검증 방법
인접 버전 조합별로 DDL/DML/failover를 수행하고 unsupported feature가 사전 거부되는지 확인한다.

## [엔진개발자-3년차-18] unload/load가 선택 RK identity를 보존하지 않는다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 ON/OFF 저장과 load 시 자동 RK 할당만 설명한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: loaddb, catalog, 후속 로그 적용

### 문제
여러 UK 중 선택된 RK를 dump에 저장하지 않으면 load 후 다른 RK를 선택할 수 있다. 백업 이후 로그를 이어 적용할 때 schema epoch도 맞지 않을 수 있다.

### 왜 중요한가
같은 DDL과 데이터가 있어도 RK identity가 달라지면 복제 로그 해석과 성능이 바뀐다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE person (
 email VARCHAR(100) NOT NULL UNIQUE,
 phone VARCHAR(30) NOT NULL UNIQUE
) REPLICATION=ON;
```

제약 출력 순서가 바뀐 dump를 load하면 다른 RK가 될 수 있다.

### 권고안
dump format에 selected logical constraint ID, ordered columns, RK epoch를 저장한다. legacy input의 선택 정책과 경고도 정의한다.

### 검증 방법
복수 UK 테이블을 unload/load하고 원본·복원 RK identity와 후속 DML 적용 결과를 비교한다.

## 문서 품질·예제·오탈자 (2개)

## [엔진개발자-3년차-19] 상태 조합별 규범표가 없어 회귀 테스트를 완성할 수 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~7절은 예제가 흩어져 있고 많은 결과가 `OK/ERROR`뿐이다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 엔진 개발자, QA

### 문제
mode × ON/OFF × 후보 수 × DDL 종류 × 동시 DML의 기대 코드가 한 표에 없다. 빠진 경계 조건을 알기 어렵다.

### 왜 중요한가
table-driven test는 입력 상태와 결과가 정확해야 한다. 산문만으로 구현자마다 다른 해석이 생긴다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE t DROP PRIMARY KEY;
ALTER TABLE t REPLICATION=OFF;
ALTER TABLE t REPLICATION=ON;
```

single/SA/HA와 후보 0/1/2개에서 각 결과가 필요하다.

### 권고안
고유 requirement ID가 있는 상태 전이표, 오류 코드, transaction 결과를 제공한다. concurrency·crash 항목도 별도 표로 만든다.

### 검증 방법
표를 test parameter로 변환해 모든 조합을 실행하고 미정의·상충 셀이 없는지 검사한다.

## [엔진개발자-3년차-20] 문법 오류와 상충 문장이 parser와 load 시험을 왜곡한다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2절·5절의 마지막 쉼표, 5-1절 `CRATE TABLE`, 8·9절 load 기본값 상충.
- 사실/추론 구분: 확인된 사실
- 영향 대상: parser 개발, loaddb 개발, QA

### 문제
기능 검사 전에 parser 오류가 나며 load default는 두 구현 정답을 만든다. `ERROR`만으로 기대 오류 위치도 구분할 수 없다.

### 왜 중요한가
잘못된 예제가 test fixture가 되면 RK validator 대신 parser failure를 성공으로 오인할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key (
 a INT,
) REPLICATION=ON;
```

의도한 HA RK 오류보다 syntax error가 먼저 발생할 수 있다.

### 권고안
예제를 실제 parser CI에서 검증하고 정확한 error code와 phase(parse/semantic/runtime)를 적는다. 8·9절 default를 하나로 통일한다.

### 검증 방법
모든 코드 블록을 parse·execute하고 예상 phase/code를 assert한다. 규범 문구 consistency lint로 상충이 0건인지 확인한다.

## [엔진개발자-3년차-21] ON/OFF 혼합 트랜잭션의 복제 commit 의미가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절·4절은 table별 DML 복제 여부만 규정한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: transaction log, apply engine, 데이터 정합성

### 문제
한 transaction의 ON record만 전송하면 replica에는 원 transaction의 부분 결과가 나타난다. commit record가 제외 record 존재를 표현하는지도 없다.

### 왜 중요한가
transaction atomicity를 replica가 동일하게 보존하지 못한다. FK가 없어도 application invariant가 깨진다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO orders(id,status) VALUES (1,'PAID'); -- ON
INSERT INTO local_audit(id,msg) VALUES (1,'ok'); -- OFF
COMMIT;
```

apply transaction 구성 규칙이 없다.

### 권고안
log transaction에 included/excluded table provenance를 기록하고 strict mode에서 mixed policy commit을 거부한다. replica atomic unit과 visibility를 정의한다.

### 검증 방법
mixed DML, rollback, savepoint, crash를 조합해 source/replica visibility와 commit record를 검사한다.

## [엔진개발자-3년차-22] partition catalog와 RK identity 범위가 정의되지 않았다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 class만 다루고 2-3절에 `partitioned` field가 보인다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 partition 기능·DDL 지원 범위 확인 필요
- 영향 대상: catalog, constraint validator, replication

### 문제
parent/child class에 policy와 selected RK를 중복 저장할지, local unique index가 global identity인지, partition 이동 시 logical ID를 보존할지 없다.

### 왜 중요한가
같은 key가 두 partition에 있으면 apply가 한 행을 확정하지 못한다. metadata 중복은 parent와 child drift를 만든다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, partitioned, replication
FROM db_class WHERE class_name='sales';
```

child RK metadata와 global uniqueness가 보이지 않는다.

### 권고안
partition root가 policy/RK owner인지 명시하고 routing key, global/local uniqueness, split/merge/move epoch transition을 정의한다.

### 검증 방법
지원 partition DDL과 concurrent DML을 fuzzing해 duplicate key 탐색과 catalog invariant를 검사한다.

## [엔진개발자-3년차-23] trigger·cascade 내부 DML의 provenance와 중복 실행 방지가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4~5절은 직접 DML과 FK policy만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문 — trigger 실행/복제 방식 확인 필요
- 영향 대상: executor, log writer, apply engine

### 문제
generated row change를 기록하면서 standby에서도 trigger/cascade를 재실행하면 이중 적용될 수 있다. ON/OFF 판단 대상도 original statement인지 generated table인지 없다.

### 왜 중요한가
내부 DML은 사용자 SQL에 보이지 않아 누락이나 중복을 찾기 어렵다.

### 재현 또는 구체적 예제
orders ON insert가 audit OFF를 쓰는 trigger를 가진다고 하자.

```sql
INSERT INTO orders(id,status) VALUES (2,'NEW');
SELECT COUNT(*) FROM audit WHERE order_id=2;
```

standby trigger 실행 횟수가 미정이다.

### 권고안
log record에 origin/provenance를 표시하고 apply 시 trigger suppression 또는 statement replay 중 하나를 결정한다. policy는 실제 변경 대상 table에 적용한다.

### 검증 방법
recursive trigger, cascade, rollback과 ON/OFF 조합에서 source/apply trace와 최종 row를 비교한다.

## [엔진개발자-3년차-24] TRUNCATE·bulk·CTAS를 표현할 복제 record 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 모든 DDL과 ON DML을 구분하지만 경계·대량 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: parser, log manager, apply, OFF data

### 문제
TRUNCATE를 schema record로 보낼지 row deletes로 보낼지, CTAS의 schema와 rows를 한 epoch로 묶는지 없다.

### 왜 중요한가
OFF에서 schema record만 전달해 standby local rows가 삭제되면 node-local 의미가 깨진다. row logging은 log 폭증을 만든다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache;
CREATE TABLE archive AS SELECT * FROM orders;
```

지원 문법별 log record와 atomicity가 미정이다.

### 권고안
각 statement를 schema/data/mixed record로 분류하고 policy evaluation, rollback, replay idempotency와 size limit을 정의한다.

### 검증 방법
ON/OFF에서 대량 row, crash, duplicate replay를 조합해 record sequence와 최종 상태를 확인한다.

## [엔진개발자-3년차-25] REPLICATION 변경 권한 검사와 감사 record의 원자성이 없다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문 2절은 권한과 audit를 설명하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: authorization engine, catalog, audit log

### 문제
권한을 어느 semantic 단계에서 검사하며 policy DDL commit과 audit event를 같은 transaction으로 보존하는지 없다.

### 왜 중요한가
변경은 성공했는데 audit가 빠지거나 audit만 남고 rollback되면 사고 이력이 거짓이 된다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE payment REPLICATION=OFF;
ROLLBACK;
```

DDL rollback 지원 여부와 audit 상태가 미정이다.

### 권고안
별도 privilege와 authorization snapshot 시점, 성공/실패 audit schema, commit ordering을 규정한다.

### 검증 방법
권한 revoke race, rollback, crash를 주입해 catalog와 audit가 정의된 상태로 일치하는지 확인한다.

## [엔진개발자-3년차-26] selected RK logical ID 할당과 복원 충돌 규칙이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 1절은 engine 선택, 8절은 load 때 자동 RK 할당만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: catalog ID allocator, loaddb, replica

### 문제
constraint OID를 RK identity로 쓰면 dump/load·clone에서 바뀌고, logical ID를 새로 만들면 기존 ID와 충돌할 수 있다.

### 왜 중요한가
log가 ID를 참조한다면 잘못 재사용된 ID는 다른 constraint로 해석될 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE person (
 email VARCHAR(100) NOT NULL UNIQUE,
 phone VARCHAR(30) NOT NULL UNIQUE
) REPLICATION=ON;
```

clone/load 두 번의 logical ID 결과가 없다.

### 권고안
globally/stably scoped ID format, allocation, tombstone, clone remap manifest와 collision detection을 정의한다.

### 검증 방법
동시 create, drop/recreate, dump/load, clone을 반복해 ID uniqueness와 old log mapping을 property test한다.

## [엔진개발자-3년차-27] 구 RK epoch와 index의 garbage collection 조건이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 RK 변경을 허용하지만 과거 metadata 폐기는 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: catalog, index storage, log retention

### 문제
지연 replica·장기 transaction·PITR 때문에 구 epoch가 필요한 동안 old index와 comparator를 언제 제거할지 없다.

### 왜 중요한가
조기 GC는 replay 실패, 무기한 보존은 disk/catalog 비대화를 만든다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
```

DR replica가 7일 늦으면 old PK index cleanup 기준이 필요하다.

### 권고안
replica low-water mark, oldest transaction, backup horizon을 합친 GC safe point와 quota/alert를 정의한다.

### 검증 방법
세 horizon을 독립적으로 지연하고 GC가 필요한 객체만 적시에 보존·삭제하는지 확인한다.

## [엔진개발자-3년차-28] 로그 압축·암호화가 RK before/after 해석을 보존하는지 없다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문은 RK 값 로그 표현과 log 보관 변환을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log codec, archive, apply

### 문제
복합 문자열 RK의 before/after를 압축·deduplicate하거나 archive 변환할 때 schema epoch와 NULL/collation 의미를 함께 보존해야 한다.

### 왜 중요한가
codec version bug는 오래된 archive 복구에서만 나타날 수 있다. 일부 key field 손실은 행 오탐색을 만든다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET email='new@example.com'
WHERE email='old@example.com';
```

압축 log가 old/new와 epoch를 lossless하게 복원하는 계약이 없다.

### 권고안
versioned codec, required fields, checksum/authentication, backward decoder와 unknown version 거부 규칙을 정의한다.

### 검증 방법
타입·길이·Unicode 경계 RK를 codec round-trip하고 old archive를 새 decoder로 replay해 byte/semantic equality를 검사한다.

## [엔진개발자-3년차-29] 중복·재정렬 record에서 apply 멱등성 범위가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문은 정상 순서 적용만 암시하고 network duplicate·restart replay를 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: apply protocol, crash recovery, 데이터 정합성

### 문제
RK-changing UPDATE와 DDL barrier record가 중복 전달되거나 마지막 ack 전 crash로 재적용될 때 성공·skip·오류 규칙이 없다.

### 왜 중요한가
at-least-once 전달에서는 duplicate가 정상이다. 두 번 UPDATE되거나 `old key 없음`으로 fail_count가 늘면 복구가 불안정하다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET email='new@x' WHERE email='old@x';
```

동일 record를 두 번 apply하는 결과가 필요하다.

### 권고안
transaction/record identity, applied watermark, DDL job id와 duplicate detection을 정의한다. 멱등 성공과 진짜 0-row corruption을 구분한다.

### 검증 방법
record duplication, ack loss, worker crash, out-of-order delivery를 fuzzing해 exactly-once visible result를 검사한다.

## [엔진개발자-3년차-30] savepoint와 transaction abort가 RK metadata를 되돌리는 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 2·4절은 DDL 성공/실패만 말하고 savepoint·abort는 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID DDL transaction/savepoint 지원 범위 확인 필요
- 영향 대상: transaction manager, catalog, cache

### 문제
policy/RK DDL을 transaction에 넣고 savepoint rollback하거나 deadlock victim이 되면 catalog epoch, cache invalidation, log reservation을 어떻게 취소하는지 없다.

### 왜 중요한가
rollback된 DDL epoch를 다른 session이 관찰하거나 log가 남으면 node별 schema가 갈린다.

### 재현 또는 구체적 예제

```sql
BEGIN;
SAVEPOINT s1;
ALTER TABLE t REPLICATION=OFF;
ROLLBACK TO SAVEPOINT s1;
COMMIT;
```

지원 여부와 최종 policy가 미정이다.

### 권고안
DDL auto-commit/savepoint 지원 matrix, provisional epoch visibility, undo와 cache publication 순서를 정의한다.

### 검증 방법
savepoint, deadlock, statement abort, transaction abort를 각 DDL state에서 주입해 catalog/log/cache 일치를 확인한다.

## [엔진개발자-3년차-31] RK catalog 손상을 탐지·격리·수리하는 check 경로가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2-3절은 정상 조회, 7절은 후보 검사만 다룬다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: checkdb, recovery, catalog

### 문제
selected constraint ID가 존재하지 않거나 ordered column list가 실제 index와 다를 때 HA 시작 검사가 무엇을 하는지 없다.

### 왜 중요한가
catalog corruption을 후보 재선택으로 숨기면 과거 로그 의미가 달라진다. 자동 repair가 더 위험할 수 있다.

### 재현 또는 구체적 예제
시험 hook으로 selected RK ID가 삭제된 constraint를 가리키게 한 뒤 실행한다.

```sql
SELECT class_name, replication FROM db_class WHERE class_name='orders';
```

ON만으로 손상을 찾을 수 없다.

### 권고안
cross-catalog invariant checker, corruption error, table quarantine, non-destructive report와 승인된 repair/re-seed 절차를 제공한다.

### 검증 방법
ID, column order, index root, epoch를 각각 손상시켜 검사 탐지율과 무단 자동 재선택 방지를 확인한다.

## [엔진개발자-3년차-32] PITR checkpoint와 RK DDL replay의 시작 상태가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 logical load만 다루며 PITR는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: WAL recovery, backup, catalog

### 문제
checkpoint가 RK DDL의 BUILDING/SWITCHED/DRAINING 중간 state를 담을 때 restore가 어디서 재개·rollback할지 없다.

### 왜 중요한가
데이터 page, index, catalog epoch가 다른 시점이면 복구 뒤 행 탐색만 잘못되는 잠복 오류가 된다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE big_t DROP PRIMARY KEY,
 ADD CONSTRAINT uk_external UNIQUE(external_id);
-- index build 중 checkpoint와 crash
```

PITR target별 state가 필요하다.

### 권고안
checkpointed DDL state, redo/undo idempotency, target-time validity와 incomplete job cleanup을 정의한다.

### 검증 방법
각 durable state에서 backup/crash/PITR를 실행해 구/신 중 완전한 epoch로 수렴하는지 확인한다.

## [엔진개발자-3년차-33] split-brain fencing epoch가 RK schema epoch와 분리돼 있다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 failover에는 network partition과 old primary rejoin이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: HA manager, log protocol, recovery

### 문제
node leadership term과 RK schema epoch가 각각 맞아도 old term에서 생성한 DML을 new primary에 적용하면 divergent history가 섞인다.

### 왜 중요한가
schema version만으로 writer 권위를 증명할 수 없다. stale primary 로그는 정상 format이라 더 위험하다.

### 재현 또는 구체적 예제

```sql
-- term 10 node A
UPDATE account SET balance=90 WHERE id=1;
-- term 11 node B
UPDATE account SET balance=80 WHERE id=1;
```

term 10 record 수용 여부가 필요하다.

### 권고안
모든 replicated record에 leadership term을 포함하고 apply가 current history ancestry를 검증하도록 한다. divergence는 quarantine한다.

### 검증 방법
term change, partition, stale record injection을 조합해 old-term write가 절대 정상 history에 합쳐지지 않는지 확인한다.

## [엔진개발자-3년차-34] index rebuild·constraint rename·통계 갱신의 RK 불변식이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 DROP INDEX 일부만 설명하고 유지보수 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 지원 문법 확인 필요
- 영향 대상: index manager, optimizer, catalog

### 문제
physical index 교체나 constraint rename이 logical RK ID를 바꾸는지, 통계 기반으로 자동 선택을 재계산하는지 없다.

### 왜 중요한가
정기 유지보수 때문에 RK가 바뀌면 과거 로그와 cache가 무효화된다. optimizer 결정이 복제 정합성을 좌우하면 안 된다.

### 재현 또는 구체적 예제
지원 문법으로 active UK index를 rebuild/rename한 뒤 다음을 조회한다.

```sql
SHOW CREATE TABLE member;
SELECT * FROM db_class WHERE class_name='member';
```

logical identity 보존이 미정이다.

### 권고안
logical RK, physical index, optimizer statistics를 분리하고 각 maintenance operation의 epoch/cache/log 효과를 정의한다.

### 검증 방법
rebuild·rename·statistics 전후, crash와 replica lag에서 logical RK와 log apply를 비교한다.

## [엔진개발자-3년차-35] RK DDL 임시 객체와 자원 quota의 cleanup 규칙이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 4-2절은 key 추가를 허용하지만 disk/temp/memory 한계는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DDL engine, storage manager, 전체 DB 가용성

### 문제
shadow index와 validation buffer가 quota를 넘을 때 작업을 언제 거부하고 crash 후 orphan을 누가 정리하는지 없다.

### 왜 중요한가
안전 key 추가가 disk full을 일으키면 WAL과 다른 transaction까지 실패할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE event_10b ADD CONSTRAINT uk_uuid UNIQUE(event_uuid);
```

95%에서 temp space exhaustion을 가정한다.

### 권고안
preflight estimate, per-job quota, throttling, progress, cancel, crash cleanup journal과 WAL reserved space를 정의한다.

### 검증 방법
quota 경계, disk full, cancel, repeated restart를 주입해 기존 RK·WAL·DML이 정상이고 orphan space가 회수되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 15개
- 최종 리뷰 항목 수: 35개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID 파티션·trigger·bulk·savepoint·index 유지보수 기능의 실제 지원 범위, 복제 log codec·leadership term·RK epoch의 현행 구조, PITR checkpoint와 catalog repair 구현
