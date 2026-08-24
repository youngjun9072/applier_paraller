# DB를 사용하는 애플리케이션 개발자 / 3년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 일반적인 ORM·스키마 마이그레이션·CI/CD 경험을 바탕으로 동시 배포, 오류 처리, failover 후 애플리케이션 동작과 하위 호환성을 검토했다.
- 확인하지 못한 전제: 실제 CUBRID JDBC/드라이버의 오류 매핑, SQL 문법 지원 범위, ORM dialect 현황, DDL 트랜잭션 성질, 복제 로그 형식과 `fail_count` API는 원문만으로 확인하지 못했다.

## 컨셉·문제 정의·대안 (3개)

## [앱개발자-3년차-01] RK가 애플리케이션 식별자와 다른 경우를 설명하지 않는다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 1절은 PK 우선, PK가 없으면 NOT NULL UK 중 엔진이 하나를 RK로 선택한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션 개발자, ORM, 복제 성능

### 문제
애플리케이션은 ORM의 `@Id`나 비즈니스 키로 행을 식별하지만 엔진은 다른 UK를 RK로 선택할 수 있다. 두 식별자가 다를 때 정상 동작 여부와 키 값 변경 비용이 없다.

### 왜 중요한가
ORM이 `email`로 UPDATE를 만들더라도 복제 로그가 `phone`을 RK로 쓰면 phone 값의 크기와 변경 빈도가 성능에 영향을 준다. 개발자는 SQL만 보고 복제 동작을 예측할 수 없다.

### 재현 또는 구체적 예제
애플리케이션 엔티티는 `email`을 논리 ID로 사용하지만 테이블에는 두 UK가 있다.

```sql
CREATE TABLE member (
  email VARCHAR(320) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL UNIQUE,
  nickname VARCHAR(100)
) REPLICATION=ON;
UPDATE member SET nickname='neo' WHERE email='a@example.com';
```

엔진이 phone을 RK로 선택할 수 있는지, 선택 결과를 앱 개발자가 확인할 수 있는지 불명확하다.

### 권고안
애플리케이션 조건절과 RK가 독립적임을 설명하고 실제 RK 조회 방법을 제공한다. ORM ID와 다른 RK를 사용할 때 로그·성능·키 UPDATE 주의점을 예제로 추가한다.

### 검증 방법
두 UK 중 하나를 ORM 식별자로 매핑하고 다른 하나가 RK인 환경을 만든다. CRUD, 배치 UPDATE, RK 값 변경 후 source/standby 데이터와 처리 시간을 비교한다.

## [앱개발자-3년차-02] 무키 테이블의 대안이 애플리케이션 변경 비용까지 다루지 않는다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 2절·4절은 무키 ON 테이블을 single에서는 허용하지만 HA에서는 금지하고 OFF로 만들 수 있다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션 개발자, 기존 데이터 모델, CI/CD

### 문제
모든 컬럼 비교를 사용하지 않고 PK/UK를 요구하는 정책은 이해할 수 있으나, 기존 무키 테이블에 surrogate PK를 추가할 때 모델·INSERT·데이터 이관이 어떻게 바뀌는지 안내하지 않는다.

### 왜 중요한가
ORM은 보통 엔티티마다 ID를 요구한다. 운영 데이터가 있는 테이블에 새 ID를 추가하려면 기존 행 채우기, NOT NULL 전환, 중복 없는 생성 전략과 구버전 앱 호환을 함께 해결해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE event_log (created_at DATETIME, body VARCHAR(4000)) REPLICATION=ON;
ALTER TABLE event_log ADD COLUMN event_id BIGINT;
```

기존 행의 `event_id`는 NULL이므로 바로 PK로 만들 수 없다. OFF 전환 외에 안전한 단계적 예제가 없다.

### 권고안
nullable ID 추가 → 기존 행 backfill → 신규 앱의 ID 쓰기 → NOT NULL/PK 전환 순서를 예시로 제공한다. 각 단계에서 구버전과 신버전 앱이 함께 동작할 조건을 설명한다.

### 검증 방법
운영 데이터 복제본에서 두 앱 버전을 동시에 실행하며 단계별 migration을 적용한다. INSERT 실패, NULL ID, 중복 ID가 없고 최종 HA 검사를 통과하는지 확인한다.

## [앱개발자-3년차-03] OFF 테이블을 애플리케이션이 안전하게 사용하는 기준이 없다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절·6절은 OFF 데이터와 이를 포함한 VIEW의 노드 간 불일치를 허용하고 책임지지 않는다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션, 사용자 데이터, failover

### 문제
OFF가 적합한 데이터 유형, failover 후 초기화 방법, API가 빈 결과를 받을 때의 계약이 없다. 개발자가 키 제약을 피하려고 업무 테이블을 OFF로 둘 위험이 있다.

### 왜 중요한가
테이블 구조는 새 primary에도 존재하므로 쿼리는 성공하지만 행은 없다. 애플리케이션은 오류가 아닌 정상적인 빈 결과로 처리해 잘못된 비즈니스 동작을 할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE rate_limit_state (
  user_id BIGINT PRIMARY KEY, request_count INT
) REPLICATION=OFF;
```

failover 후 count가 사라지는 것을 허용할지, 외부 저장소로 재구축할지 앱 계약이 필요하다. 주문·권한 테이블에는 같은 선택이 안전하지 않다.

### 권고안
OFF는 재생성 가능 캐시·노드 로컬 임시 데이터에만 권장한다고 명시한다. 앱 시작/failover hook에서 재구축하거나 접근을 차단하는 패턴과 금지 사례를 제공한다.

### 검증 방법
OFF 테이블을 사용하는 API에 failover 통합 테스트를 수행한다. 빈 데이터가 허용된 API는 정상 복구되고 영속 데이터 API는 배포 검사에서 OFF 사용이 차단되는지 확인한다.

## 용어·기본값·사용자 계약 (2개)

## [앱개발자-3년차-04] ON/OFF가 설정값인지 현재 복제 상태인지 불분명하다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 2절은 ON을 “복제 테이블”이라고 부르고 3절은 single에서도 ON을 사용할 수 있다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션, 상태 점검 API, 운영 대시보드

### 문제
single에서 ON은 실제 복제 중이 아니므로 정책과 실행 상태가 다르다. 앱 readiness 검사가 카탈로그의 ON만 보고 HA 보호가 정상이라고 판단할 수 있다.

### 왜 중요한가
설정은 “복제해야 한다”는 의도이고 상태는 “현재 적용 중이다”라는 사실이다. 둘을 섞으면 연결 끊김이나 apply 중지를 놓친다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, replication FROM db_class WHERE class_name='orders';
```

single, 정상 HA, apply 정지 환경에서 모두 ON이 나올 수 있다. 앱 health endpoint가 사용할 런타임 상태가 별도로 필요하다.

### 권고안
ON/OFF를 테이블 정책이라고 정의하고 클러스터 역할, 전송, apply, lag 상태의 조회 API를 분리한다. 앱 readiness에서 사용할 최소 조건을 문서화한다.

### 검증 방법
standby apply 중지와 네트워크 단절을 만들고 정책 값은 ON으로 유지되지만 health 상태가 비정상으로 바뀌는지 확인한다.

## [앱개발자-3년차-05] 암묵적 ON이 ORM 생성 스키마에 예기치 않게 적용된다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 `REPLICATION` 생략 시 ON이고 무키 ON 테이블은 HA 시작 시 오류라고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: ORM 사용자, CI/CD, HA 기동

### 문제
기존 ORM dialect는 새 옵션을 출력하지 않는다. join table, migration history, 임시 테이블도 암묵적으로 ON이 되며 PK가 없으면 운영 HA 시작을 막을 수 있다.

### 왜 중요한가
개발 환경은 single이고 운영만 HA이면 같은 ORM migration이 개발에서 성공하고 운영 기동 때 실패한다. 애플리케이션 개발자는 생성된 보조 테이블을 직접 관리하지 않을 수도 있다.

### 재현 또는 구체적 예제

```sql
-- ORM이 자동 생성한 다대다 연결 테이블
CREATE TABLE user_role (user_id BIGINT, role_id BIGINT);
```

옵션 생략으로 ON이고 PK/NOT NULL UK가 없어 HA 검사 실패 대상이 된다.

### 권고안
지원 ORM별 dialect 갱신과 자동 생성 테이블 규칙을 제공한다. CI에서 production 모드 스키마를 검사하고 무키 테이블에는 복합 PK를 넣거나 명시적 OFF를 요구한다.

### 검증 방법
지원 ORM의 schema generation으로 실제 DB를 만들고 HA dry-run을 실행한다. 보조·이력 테이블까지 위반 없이 생성되는지 확인한다.

## SQL 문법과 상태 전이 (3개)

## [앱개발자-3년차-06] ORM과 schema diff 도구가 새 테이블 옵션을 보존할 방법이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절은 CREATE/ALTER에 `REPLICATION={ON|OFF}`를 추가하고 2-3절은 SHOW와 `db_class` 조회를 제시한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ORM, migration 도구, 애플리케이션 개발자

### 문제
기존 SQL parser와 ORM metadata API가 테이블 옵션을 인식하지 못할 수 있다. schema diff가 OFF를 읽지 못하면 다음 배포에서 옵션을 누락하거나 테이블 재생성 시 ON으로 되돌릴 수 있다.

### 왜 중요한가
마이그레이션 도구는 실제 스키마와 선언 파일을 비교해 변경 SQL을 만든다. 새 속성이 표준 metadata에 노출되지 않으면 drift가 반복된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE local_cache (cache_key VARCHAR(100) PRIMARY KEY) REPLICATION=OFF;
SHOW CREATE TABLE local_cache;
```

도구가 마지막 `REPLICATION OFF`를 무시하고 테이블을 다시 만들면 기본 ON으로 변할 수 있다.

### 권고안
JDBC metadata와 카탈로그에서 안정적으로 조회하는 방법, 문법 grammar, schema diff 기대 동작을 공개한다. 주요 migration 도구용 최소 예제와 버전 요구를 제공한다.

### 검증 방법
도구로 introspect → diff → no-op migration → 재-introspect를 반복한다. OFF가 보존되고 불필요한 ALTER가 생성되지 않는지 확인한다.

## [앱개발자-3년차-07] 복합 ALTER 실패가 migration transaction을 어떻게 처리하는지 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절·4-2절은 한 ALTER에서 기존 키 삭제와 새 키 추가를 허용한다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: CI/CD, migration 도구, 복제 정합성

### 문제
DROP 성공 후 ADD가 중복 때문에 실패할 때 전체 DDL이 rollback되는지 없다. migration 도구가 이를 transaction에 묶어도 CUBRID DDL의 실제 commit 규칙에 따라 결과가 달라질 수 있다.

### 왜 중요한가
배포 도구는 실패 시 자동 rollback했다고 기록할 수 있다. 실제 DB에 구 키가 사라졌다면 앱 배포 기록과 스키마가 어긋나고 HA도 위험해진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE coupon (id INT PRIMARY KEY, code VARCHAR(30)) REPLICATION=ON;
INSERT INTO coupon VALUES (1,'A'),(2,'A');
ALTER TABLE coupon DROP PRIMARY KEY,
  ADD CONSTRAINT uk_coupon_code UNIQUE(code);
```

새 UK 생성은 실패해야 한다. 기대 결과는 기존 PK/RK가 남고 migration 전체가 실패로 기록되는 것이다.

### 권고안
복합 ALTER의 원자성, 자동 commit, rollback 범위를 규정한다. migration 전 중복 검사와 실패 후 실제 PK/RK 확인 SQL을 제공한다.

### 검증 방법
중복, 잠금 타임아웃, 디스크 부족을 유발해 migration을 실패시킨다. 도구 기록과 DB의 키·RK·데이터가 모두 변경 전 상태인지 확인한다.

## [앱개발자-3년차-08] 여러 UK와 복합 키 전환이 migration diff에서 결정적이지 않다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절은 여러 UK 중 엔진 선택을 예시적 순서로만 설명하고 4-2절은 복합 키와 컬럼 속성 변경을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: migration 도구, 애플리케이션, 복제 성능

### 문제
제약 생성 순서는 도구마다 달라질 수 있고 복합 UK의 컬럼 순서도 diff 과정에서 재작성될 수 있다. 같은 모델을 배포해도 환경별 RK가 달라질 가능성을 배제할 수 없다.

### 왜 중요한가
개발·staging·production의 RK가 다르면 성능 시험 결과가 운영을 대표하지 않는다. 복합 키 일부를 nullable로 변경하면 후보 자체가 사라질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE tenant_user (
  tenant_id INT NOT NULL,
  email VARCHAR(320) NOT NULL,
  external_id BIGINT NOT NULL UNIQUE,
  UNIQUE(tenant_id,email)
) REPLICATION=ON;
ALTER TABLE tenant_user ALTER COLUMN email DROP NOT NULL;
```

환경별로 어떤 UK가 RK였는지에 따라 ALTER 영향이 달라질 수 있다.

### 권고안
완전한 RK 선택 규칙과 명시 지정 기능을 제공한다. 복합 키 컬럼의 순서·NULL·타입 변경을 migration lint가 감지할 수 있는 metadata를 공개한다.

### 검증 방법
두 migration 도구로 동일 모델을 생성하고 제약 순서를 다르게 한다. 환경별 실제 RK와 ALTER 결과가 일치하는지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [앱개발자-3년차-09] 구버전·신버전 앱 동시 실행 중 RK 컬럼 변경 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 HA 중 RK DDL을 다루지만 애플리케이션의 동시 버전 배포와 DML은 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, CI/CD, 복제 정합성

### 문제
rolling deploy 동안 구버전은 이전 컬럼으로, 신버전은 새 컬럼으로 쓰거나 조회할 수 있다. 키 rename/drop을 한 번에 수행하면 구버전 요청이 즉시 실패하고 DDL/DML 로그 순서도 복잡해진다.

### 왜 중요한가
일반적인 expand-and-contract 배포는 두 앱 버전이 한동안 공존한다. 스키마가 양쪽 요청을 모두 받아야 무중단 배포가 가능하다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer ADD COLUMN customer_uuid VARCHAR(36);
-- 구버전: UPDATE customer SET name=? WHERE id=?
-- 신버전: UPDATE customer SET name=? WHERE customer_uuid=?
ALTER TABLE customer DROP PRIMARY KEY,
  ADD CONSTRAINT uk_customer_uuid UNIQUE(customer_uuid);
```

backfill과 NOT NULL 전환 전에 새 UK를 만들 수 없으며, 구버전 종료 전 id 제거도 위험하다.

### 권고안
새 컬럼 추가, dual write/backfill, NOT NULL UK 생성, 신버전 전환, 구키 제거의 단계별 패턴을 제공한다. 각 단계의 RK와 허용 앱 버전을 표로 작성한다.

### 검증 방법
구·신 버전 인스턴스에 실제 트래픽을 보내며 단계별 migration을 실행한다. API 오류, NULL/중복, 복제 지연과 양 노드 checksum을 검사한다.

## [앱개발자-3년차-10] DDL 잠금과 앱 요청 timeout·retry 계약이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 운영 중 키 관련 ALTER를 허용하지만 잠금, 대기, 동시 DML 결과는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 사용자 요청, DB connection pool

### 문제
대형 테이블 UK 생성과 RK 교체가 DML을 얼마나 막는지, JDBC에 어떤 오류가 전달되는지 없다. 앱이 무조건 재시도하면 중복 쓰기나 retry storm이 날 수 있다.

### 왜 중요한가
DDL은 짧은 문장이어도 인덱스 구축 때문에 오래 걸린다. connection pool이 모두 대기하면 unrelated API까지 멈춘다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders ADD CONSTRAINT uk_orders_external UNIQUE(external_id);
-- 동시에 앱 요청
UPDATE orders SET status='PAID' WHERE id=500;
```

UPDATE가 대기·실패·성공 중 무엇인지, 재시도가 안전한지 알 수 없다.

### 권고안
잠금 수준, timeout 오류 코드, transaction rollback 범위, 재시도 가능 여부를 명시한다. 온라인/오프라인 DDL 구분과 배포 전 예상 소요·진행률 조회를 제공한다.

### 검증 방법
대형 테이블에서 ALTER 중 읽기·쓰기를 실행해 응답 시간과 JDBC exception을 수집한다. 문서의 retry 정책으로 중복 DML 없이 정상 회복하는지 확인한다.

## [앱개발자-3년차-11] failover 후 connection과 미확정 transaction 처리 지침이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절·6절은 failover 후 데이터 접근 결과를 언급하지만 앱 연결, transaction 결과, 재시도 계약은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 사용자 요청, 데이터 중복

### 문제
failover 순간 COMMIT 응답을 받지 못한 요청이 새 primary에 적용됐는지 알 수 없다. 드라이버가 새 노드로 자동 연결하는지, 열린 transaction이 재개되는지도 없다.

### 왜 중요한가
상태를 모르는 쓰기를 단순 재시도하면 주문이나 결제가 두 번 생성될 수 있다. 연결 복구와 업무 멱등성을 함께 설계해야 한다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO payment(payment_id, order_id, amount) VALUES ('P-100',10,5000);
COMMIT;
-- COMMIT 응답 전에 failover
```

앱이 timeout을 받았을 때 `P-100` 존재 확인 후 재시도할지 지침이 없다.

### 권고안
드라이버 failover, transaction 단절, commit outcome unknown 오류를 정의한다. 업무 고유 idempotency key와 새 연결에서 결과 확인 후 재시도하는 예제를 제공한다.

### 검증 방법
BEGIN, DML, commit flush, 응답 직전 단계마다 장애를 주입한다. 앱 retry 후 payment가 정확히 한 건이고 오류 타입이 문서와 같은지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [앱개발자-3년차-12] RK 값 변경 DML의 로그 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 RK 제약 변경만 다루며 RK 컬럼 값 UPDATE는 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 복제 정합성

### 문제
email 같은 UK가 RK일 때 애플리케이션이 email을 변경하면 standby는 구 값을 가진 행을 찾아야 한다. 이전·새 값 기록과 재적용 동작이 정의되지 않았다.

### 왜 중요한가
새 값으로 행을 찾으면 0행이고, 로그 재시도 때 구 값으로만 찾으면 이미 적용된 행을 못 찾는다. 두 상태를 안전하게 구분해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (email VARCHAR(320) NOT NULL UNIQUE, name VARCHAR(100)) REPLICATION=ON;
UPDATE member SET email='new@example.com' WHERE email='old@example.com';
```

기대 결과는 standby 한 행만 갱신되고 재시도에도 중복이나 오류가 없는 것이다.

### 권고안
RK UPDATE 로그에 old/new 값이 포함되는지, 0행·복수행·new 충돌 오류를 명시한다. 앱에게 RK 변경을 별도 중요 operation으로 취급하도록 안내한다.

### 검증 방법
단일·복합 RK를 여러 번 변경하고 apply를 각 지점에서 재시작한다. 최종 데이터와 행 수, `fail_count`가 일치하는지 확인한다.

## [앱개발자-3년차-13] FK ON/OFF 제한이 ORM cascade와 충돌할 수 있다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 5절은 ON 자식이 OFF 부모를 참조하면 오류라고 하지만 다른 조합과 연쇄 동작은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: ORM, 애플리케이션, 참조 무결성

### 문제
ORM의 cascade delete와 DB의 `ON DELETE CASCADE`는 동작 위치가 다르다. 부모 ON·자식 OFF 등 정책이 섞일 때 앱이 발생시킨 여러 DELETE와 DB 자동 DELETE가 각각 복제되는 방식이 없다.

### 왜 중요한가
ORM cascade는 여러 SQL을 보내고 DB cascade는 서버가 추가 DML을 만든다. 둘의 복제 정책이 다르면 source와 standby 결과가 달라질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE child (id INT PRIMARY KEY, parent_id INT,
 FOREIGN KEY(parent_id) REFERENCES parent(id) ON DELETE CASCADE) REPLICATION=OFF;
DELETE FROM parent WHERE id=1;
```

source child 삭제와 standby의 FK 적용 결과가 불명확하다.

### 권고안
부모/자식 ON/OFF 네 조합과 DB cascade별 허용 규칙을 제시한다. ORM cascade 사용 시 권장 mapping과 위험한 혼용 예제를 추가한다.

### 검증 방법
ORM cascade와 DB cascade를 각각 켜고 부모 삭제를 수행한다. SQL 로그, 두 노드 행, FK 오류가 규정과 일치하는지 확인한다.

## [앱개발자-3년차-14] OFF 테이블을 포함한 VIEW의 API 결과 계약이 위험하다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절은 VIEW 실행에 제약이 없지만 OFF 데이터 때문에 결과가 다를 수 있다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션, API 사용자, 캐시

### 문제
failover 후 VIEW가 오류 대신 빈 목록이나 다른 집계를 반환할 수 있다. 앱은 이를 정상 응답으로 캐시하거나 외부 시스템에 전송할 수 있다.

### 왜 중요한가
명시적인 DB 오류보다 잘못된 정상 응답이 탐지하기 어렵다. 중첩 VIEW를 통해 간접적으로 OFF를 참조하면 개발자가 의존성을 모를 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE item (id INT PRIMARY KEY, price INT) REPLICATION=ON;
CREATE TABLE local_discount (item_id INT PRIMARY KEY, rate INT) REPLICATION=OFF;
CREATE VIEW sale_item AS SELECT i.id, i.price-d.rate final_price
 FROM item i JOIN local_discount d ON i.id=d.item_id;
```

failover 후 API가 `sale_item`에서 0행을 받아 캐시에 저장할 수 있다.

### 권고안
OFF 의존 VIEW를 카탈로그에서 조회하고 생성·ALTER 시 경고한다. 앱 문서에는 failover 후 해당 API를 비활성화하거나 로컬 데이터를 재구축한 뒤 준비 상태로 전환하는 패턴을 넣는다.

### 검증 방법
중첩 VIEW를 사용하는 API를 failover하고 응답·캐시를 관찰한다. 의존성 검사와 readiness gate가 잘못된 응답 노출을 막는지 확인한다.

## 운영·오류·관측 가능성 (2개)

## [앱개발자-3년차-15] 안정된 오류 코드와 재시도 가능 여부가 정의되지 않았다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2절·4절·5절의 예제는 대부분 `ERROR`만 표시한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션, JDBC, 운영 자동화

### 문제
RK 없음, HA 중 OFF→ON 금지, FK 정책 위반, 잠금 timeout을 앱이 구별할 코드가 없다. 문자열 메시지에 의존하면 언어·버전 변화에 취약하다.

### 왜 중요한가
잠금 timeout은 재시도할 수 있지만 스키마 정책 위반은 코드를 고쳐야 한다. 모든 오류를 재시도하면 장애를 키우고, 모두 실패 처리하면 일시 오류 복구를 놓친다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE cache REPLICATION=ON;
ALTER TABLE orders DROP PRIMARY KEY;
```

HA에서 둘 다 ERROR지만 원인과 조치가 다르다. JDBC exception에서 안정적으로 구별할 수 있어야 한다.

### 권고안
오류 코드, SQLSTATE, retryable 여부, transaction 상태, 객체 이름을 정의한다. Java 등 대표 언어의 예외 분기와 사용자에게 반환할 메시지 예제를 제공한다.

### 검증 방법
각 오류를 JDBC 통합 테스트로 발생시키고 code/SQLSTATE/rollback 상태를 assert한다. locale 변경 후에도 분기가 유지되는지 확인한다.

## [앱개발자-3년차-16] 애플리케이션 관측 지표와 DB `fail_count`를 연결할 수 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 전체는 `fail_count`의 테이블·로그 단위 상세, 조회·경보 방법을 제시하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 개발자, SRE, 장애 분석

### 문제
API 오류·지연이 특정 복제 적용 실패와 같은 사건인지 연결할 correlation 정보가 없다. failover 후 데이터가 다를 때 어느 DB 로그부터 조사할지도 알 수 없다.

### 왜 중요한가
앱 로그에는 request ID와 업무 키가 있고 DB에는 LSA와 RK가 있다. 둘을 연결할 수 없으면 장애 원인과 영향 사용자 범위를 찾는 시간이 길어진다.

### 재현 또는 구체적 예제

```sql
UPDATE orders SET status='SHIPPED' WHERE order_id=1001;
```

standby 적용 실패 시 앱의 `request_id=R77`, `order_id=1001`과 DB 오류 사건을 연결할 필드가 없다.

### 권고안
복제 오류 이벤트에 DB, table, RK 값 또는 안전한 hash, LSA, 시간, 오류 코드를 제공한다. 민감정보 노출 없이 앱 trace와 연결하는 운영 예제를 추가한다.

### 검증 방법
추적 ID를 가진 요청으로 의도적 적용 오류를 만들고 앱 로그에서 DB 사건까지 찾는 시간을 측정한다. 권한 없는 사용자는 키 원문을 볼 수 없는지도 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [앱개발자-3년차-17] 구버전 unload 기본값 상충이 ephemeral test DB까지 흔든다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 필드 누락 시 ON, 9절 요약은 누락 시 OFF라고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: CI/CD, 테스트 DB, migration

### 문제
같은 dump를 개발·CI·운영에 복원했을 때 ON/OFF 결과를 정할 수 없다. 환경별 load 옵션이 다르면 테스트가 운영 정책을 재현하지 못한다.

### 왜 중요한가
CI는 production dump 일부를 ephemeral DB에 load해 migration을 검증할 수 있다. 기본값이 다르면 CI에서 통과한 FK·HA 검사가 운영에서 실패한다.

### 재현 또는 구체적 예제

```sql
-- 구버전 dump에 새 필드 없이 존재
CREATE TABLE migration_history (version VARCHAR(50), applied_at DATETIME);
```

8절에 따르면 ON, 9절에 따르면 OFF다. 자동화가 기대할 단일 결과가 없다.

### 권고안
상충을 해소하고 load에 명시적 기본 정책 옵션과 dry-run 보고서를 제공한다. CI와 운영에서 동일 설정 파일을 사용하는 예제를 제시한다.

### 검증 방법
구·신 형식 dump를 CI와 운영 복제 환경에 같은 옵션으로 load한다. 모든 테이블의 ON/OFF와 HA 검사 결과가 동일한지 비교한다.

## [앱개발자-3년차-18] 드라이버·ORM·혼합 DB 버전의 호환성 시험표가 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 2절은 새 SQL과 조회 열을 추가하지만 클라이언트·DB 버전 조합과 롤링 업그레이드는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 드라이버, 롤링 배포

### 문제
구 JDBC 드라이버가 새 `db_class.replication` 열이나 SHOW 결과를 처리하는지, 구 DB가 새 migration SQL을 받을 때 오류가 명확한지 없다. DB 노드가 혼합 버전일 때 새 DDL 사용 시점도 없다.

### 왜 중요한가
앱과 DB는 동시에 업그레이드되지 않는다. 조합별 계약이 없으면 rollback한 앱이 새 스키마를 읽지 못하거나 구 standby가 복제 로그를 적용하지 못할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE session_cache REPLICATION=OFF;
SELECT replication FROM db_class WHERE class_name='session_cache';
```

구 드라이버/구 DB/신 드라이버/신 DB 네 조합의 성공 여부가 없다.

### 권고안
DB source/standby, driver, ORM dialect, migration tool 버전의 지원 행렬과 업그레이드 순서를 제공한다. capability 확인 후 새 SQL을 실행하도록 예제를 추가한다.

### 검증 방법
지원 조합별로 schema migration, CRUD, failover, app rollback을 자동화한다. 미지원 조합은 사전에 명확히 차단되고 데이터 변경이 남지 않는지 확인한다.

## 문서 품질·예제·오탈자 (2개)

## [앱개발자-3년차-19] SQL 예제가 복사 실행 및 자동 테스트에 부적합하다

- 분류: 문서 품질
- 심각도: Minor
- 근거 위치: 원문 2-1절·5절 일부 예제의 마지막 쉼표, 5-1절 `CRATE TABLE`, `//` 주석, 다수의 `...`와 단순 `ERROR`.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 개발자, QA, 문서 사용자

### 문제
예제를 그대로 migration에 넣을 수 없고 기능 오류와 문법 오류가 섞인다. 실제 제약 이름과 오류 코드가 없어 테스트 assertion을 만들 수도 없다.

### 왜 중요한가
개발자는 문서를 기반으로 작은 재현 테스트를 만든다. 실행 불가능한 예제는 잘못된 학습과 지원 요청을 늘린다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE new_orders (
  order_id INT PRIMARY KEY,
);
```

마지막 쉼표가 있으면 원래 확인하려던 FK/REPLICATION 규칙에 도달하지 못한다.

### 권고안
모든 코드를 지정 CUBRID 버전에서 실행하고 주석 문법도 확인한다. 초기 상태, 모드, 실제 제약 이름, 예상 result set 또는 오류 코드가 포함된 독립 예제로 고친다.

### 검증 방법
문서의 각 코드 블록을 CI에서 새 DB에 순서대로 또는 독립 fixture로 실행한다. 예상과 다른 parser 오류와 미정의 객체 참조가 0건인지 확인한다.

## [앱개발자-3년차-20] 앱 배포 관점의 종단간 migration 예제가 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~8절은 개별 SQL과 HA 제약을 설명하지만 CI 검증부터 앱 롤아웃·failover까지 연결한 예제는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 개발자, CI/CD, 운영팀

### 문제
개발자가 스키마 검사, backward-compatible 변경, 데이터 backfill, 앱 버전 전환, 구 키 제거, HA 검증을 어떤 순서로 해야 하는지 알 수 없다.

### 왜 중요한가
개별 SQL이 맞아도 두 앱 버전이 공존하는 순서를 빠뜨리면 요청 실패가 생긴다. rollback 가능한 시점과 불가능한 시점도 배포 전에 정해야 한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer ADD COLUMN customer_uuid VARCHAR(36);
-- backfill
UPDATE customer SET customer_uuid=... WHERE customer_uuid IS NULL;
ALTER TABLE customer ADD CONSTRAINT uk_customer_uuid UNIQUE(customer_uuid);
```

실제 값 생성, batch 크기, dual write, NOT NULL 전환, 구 앱 종료 시점이 생략되어 있다.

### 권고안
CI dry-run → expand schema → dual write → online backfill → 검증 → RK 전환 → 신 앱 100% → contract schema → failover rehearsal 순서의 완전한 예제를 제공한다. 각 단계의 rollback 조건을 표시한다.

### 검증 방법
구·신 앱 인스턴스를 함께 실행하는 staging에서 runbook을 그대로 수행한다. 배포·rollback·failover 동안 API 성공률, 중복/NULL, DB checksum과 복제 지연이 기준을 만족하는지 확인한다.

## [앱개발자-3년차-21] migration 계정의 REPLICATION 변경 권한과 감사 API가 없다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문 2절은 사용자가 새 옵션을 실행한다고만 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: migration runner, 애플리케이션 개발자, 보안팀

### 문제
배포 계정에 일반 ALTER만 주면 ON→OFF도 가능한지, 별도 권한이 필요하면 CI가 어떤 오류를 받는지 없다.

### 왜 중요한가
과도한 DBA 권한을 runner에 주면 사고 범위가 커지고 권한 부족은 운영 배포에서만 실패할 수 있다.

### 재현 또는 구체적 예제

```sql
GRANT ALTER ON orders TO migration_user;
-- migration_user
ALTER TABLE orders REPLICATION=OFF;
```

허용 여부와 audit event가 미정이다.

### 권고안
DDL별 최소 권한, SQLSTATE, audit metadata를 정의한다. runner에는 필요한 권한만 주고 OFF 변경은 별도 승인하게 한다.

### 검증 방법
CI에서 권한 조합별 migration을 실행하고 성공·거부 및 actor/commit 감사 기록을 검증한다.

## [앱개발자-3년차-22] ON/OFF 혼합 트랜잭션이 애플리케이션 원자성을 깨뜨린다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절·4절은 테이블별 DML 복제를 규정한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션, failover, 업무 정합성

### 문제
한 transaction이 ON과 OFF를 함께 바꾸면 source에서는 원자적이지만 standby에는 ON write만 보일 수 있다.

### 왜 중요한가
서비스 코드는 transaction 성공을 업무 단위 성공으로 본다. failover 후 일부만 남으면 상태 machine이 깨진다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO orders(id,status) VALUES (1,'PAID'); -- ON
INSERT INTO local_outbox(order_id,event) VALUES (1,'paid'); -- OFF
COMMIT;
```

새 primary에는 order만 남을 수 있다.

### 권고안
혼합 transaction의 결과를 명시하고 strict mode에서 거부하거나 경고한다. transaction이 함께 쓰는 테이블 정책을 정적 분석하는 예제를 제공한다.

### 검증 방법
commit·rollback·retry·failover를 조합하고 domain invariant와 양 노드 행을 assert한다.

## [앱개발자-3년차-23] ORM 파티션 매핑에서 RK 범위를 알 수 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문은 일반 테이블만 설명하고 2-3절에는 `partitioned` 속성이 보인다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID 파티션 기능과 ORM 지원 범위 확인 필요
- 영향 대상: ORM 사용자, 대형 테이블 애플리케이션

### 문제
ORM entity는 한 table로 보지만 DB 파티션별 unique 범위와 ON/OFF 상속이 다를 수 있다. metadata API가 이를 노출하는지도 없다.

### 왜 중요한가
ORM ID가 파티션 내부에서만 unique이면 전체 RK로 행을 확정하지 못할 수 있다. 새 파티션 배포가 HA를 깨뜨릴 수도 있다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, partitioned, replication
FROM db_class WHERE class_name='event';
```

이 결과만으로 entity key의 global uniqueness를 확인할 수 없다.

### 권고안
파티션 정책 상속, global/local key, 지원 DDL과 JDBC metadata를 정의하고 ORM migration lint 예제를 제공한다.

### 검증 방법
공식 파티션 schema를 ORM에서 introspect·CRUD·migration하고 source/standby ID 일치와 failover를 검사한다.

## [앱개발자-3년차-24] trigger가 만든 숨은 DML이 앱 transaction 예상과 다를 수 있다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4~5절은 직접 DML과 FK 일부만 다룬다.
- 사실/추론 구분: 확인이 필요한 질문 — trigger 지원·복제 방식 확인 필요
- 영향 대상: 애플리케이션, ORM, 데이터 정합성

### 문제
ON write가 trigger로 OFF를 바꾸거나 반대일 때 generated DML을 로그로 보낼지 standby에서 trigger를 다시 실행할지 없다.

### 왜 중요한가
앱 SQL log에는 숨은 변경이 안 보인다. 중복 실행·누락은 ORM cache와 DB 상태를 어긋나게 한다.

### 재현 또는 구체적 예제
orders insert trigger가 local_audit OFF에 기록한다고 하자.

```sql
INSERT INTO orders(id,status) VALUES (2,'NEW');
SELECT COUNT(*) FROM local_audit WHERE order_id=2;
```

failover 결과가 미정이다.

### 권고안
trigger/cascade DML provenance, logging, replica 재실행 억제와 ON/OFF 규칙을 명시한다. ORM SQL trace와 DB 내부 trace를 연결한다.

### 검증 방법
trigger 방향과 transaction rollback을 조합해 실행 횟수·양 노드 행·ORM cache refresh를 확인한다.

## [앱개발자-3년차-25] JDBC batch와 bulk SQL의 복제·오류 단위가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 단일 DML 예만 전제로 하며 bulk/TRUNCATE 경계 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 배치 애플리케이션, JDBC, 복제 지연

### 문제
batch 일부 실패, `INSERT ... SELECT`, TRUNCATE가 ON/OFF에서 어느 단위로 복제·rollback되는지 없다.

### 왜 중요한가
JDBC batch는 일부 statement 성공 count를 반환할 수 있다. source와 standby의 실패 단위가 다르면 재시도가 중복 데이터를 만든다.

### 재현 또는 구체적 예제

```sql
INSERT INTO archive SELECT * FROM orders;
TRUNCATE TABLE local_cache;
```

archive/local_cache가 OFF일 때 동작과 batch result가 없다.

### 권고안
명령·batch별 atomicity, update count, SQLSTATE, ON/OFF result와 log volume을 명시한다. idempotent batch key 사용을 안내한다.

### 검증 방법
중간 unique 충돌과 connection loss를 주입한 JDBC batch를 재시도하고 양 노드에 정확히 한 번 반영됐는지 확인한다.

## [앱개발자-3년차-26] PITR 후 애플리케이션 schema version과 RK 세대 정합성이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load만 설명하고 PITR는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션 rollback, migration ledger, 재해 복구

### 문제
DB를 RK migration 전 시점으로 복구하면 배포된 앱·migration history가 새 컬럼과 RK를 기대할 수 있다.

### 왜 중요한가
데이터 복구가 성공해도 앱 binary와 schema가 맞지 않으면 즉시 API 오류 또는 잘못된 재-migration이 생긴다.

### 재현 또는 구체적 예제

```sql
-- migration V42
ALTER TABLE customer ADD CONSTRAINT uk_uuid UNIQUE(customer_uuid);
-- V42 이전으로 PITR, 앱은 V42 상태
```

app/migration ledger 조정 절차가 없다.

### 권고안
PITR target의 schema/RK epoch, app minimum version, migration ledger 재조정과 deployment rollback 순서를 제공한다.

### 검증 방법
V41/V42 시점으로 각각 복구하고 구·신 앱을 연결해 startup guard, migration replay, CRUD와 checksum을 검사한다.

## [앱개발자-3년차-27] 장기 앱 트랜잭션이 RK migration과 로그 보관을 막을 수 있다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 RK DDL을 허용하지만 long transaction과 retention은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션, connection pool, DBA

### 문제
요청이나 batch가 RK 변경 전 시작해 오래 열려 있으면 어느 RK epoch로 commit하는지, DDL이 기다리는지 없다.

### 왜 중요한가
transaction leak 하나가 migration을 수시간 막고 구 로그 보관으로 disk를 채울 수 있다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE account SET balance=80 WHERE id=10;
-- connection이 pool에 오래 열린 뒤 RK 변경 후 COMMIT
COMMIT;
```

timeout과 commit 결과가 미정이다.

### 권고안
DDL precheck에 oldest transaction·lag을 표시하고 maximum age, cancellation SQLSTATE, pool timeout 가이드를 정의한다.

### 검증 방법
transaction leak과 정상 request를 조합해 DDL, pool saturation, log growth, rollback 결과를 확인한다.

## [앱개발자-3년차-28] split-brain 방지가 client routing 계약에 연결되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 failover 설명에는 old primary connection과 network partition이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: JDBC routing, 애플리케이션, 데이터 정합성

### 문제
connection pool 일부가 old primary에 남고 다른 pool이 new primary로 연결되면 양쪽 write가 발생할 수 있다.

### 왜 중요한가
RK는 같은 행 충돌을 해결하지 않는다. DNS·VIP·driver cache가 늦게 바뀌는 현실을 고려해야 한다.

### 재현 또는 구체적 예제

```sql
-- old primary connection
UPDATE stock SET qty=9 WHERE id=1;
-- new primary connection
UPDATE stock SET qty=8 WHERE id=1;
```

stale connection의 write 차단 계약이 없다.

### 권고안
server term fencing, driver role validation, connection eviction, retry 금지 오류를 정의한다. 앱은 매 write 전 역할을 추측하지 않아도 server가 차단해야 한다.

### 검증 방법
pool의 절반을 old node에 고정한 채 failover한다. old write가 안정된 code로 거부되고 duplicate retry가 없는지 확인한다.

## [앱개발자-3년차-29] RK 오류를 trace에 연결할 때 개인정보가 노출될 수 있다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문은 RK 오류 detail과 app telemetry 연계·마스킹 규칙이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션 로그, 개인정보, observability

### 문제
email·전화번호 RK를 request trace label이나 DB error에 원문으로 넣으면 telemetry에 개인정보가 퍼진다.

### 왜 중요한가
trace는 높은 cardinality 비용과 보안 위험을 동시에 만든다. 장애 correlation에는 원문이 아닌 안정된 식별자가 필요하다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET state='A' WHERE email='person@example.com';
```

DB event와 trace를 어떤 안전한 값으로 연결할지 없다.

### 권고안
keyed hash/event ID를 공통 correlation key로 쓰고 RK 원문은 trace attribute에서 금지한다. SDK 예제와 redaction test를 제공한다.

### 검증 방법
민감 RK 오류를 end-to-end 발생시켜 app log, metric, trace, DB bundle의 원문 노출을 scan한다.

## [앱개발자-3년차-30] RK 변경 후 prepared statement와 ORM metadata cache 처리 규칙이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 온라인 RK 변경을 허용하지만 기존 session·prepared plan은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: connection pool, ORM, 애플리케이션 가용성

### 문제
오래된 connection의 prepared statement와 ORM metadata cache가 구 column/constraint 정의를 계속 사용할 수 있다.

### 왜 중요한가
새 connection만 정상이고 기존 pool 요청만 실패하는 간헐 장애가 생긴다. DDL 완료가 앱 준비 완료를 뜻하지 않는다.

### 재현 또는 구체적 예제

```sql
PREPARE p FROM 'UPDATE customer SET name=? WHERE id=?';
ALTER TABLE customer RENAME COLUMN id AS customer_id;
EXECUTE p USING 'Kim',10;
```

재prepare 또는 오류 contract가 없다.

### 권고안
schema change 후 server plan invalidation, driver error, pool recycle 필요 여부를 정의하고 ORM metadata refresh 절차를 제공한다.

### 검증 방법
수백 cached prepared statement를 실행 중 DDL하고 old/new connection의 결과·error·recovery를 확인한다.

## [앱개발자-3년차-31] blue/green DB clone에서 REPLICATION 정책이 drift할 수 있다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2·8절은 기본 CREATE와 unload/load만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 clone/LIKE/복사 지원 범위 확인 필요
- 영향 대상: blue/green 배포, ephemeral DB, schema tool

### 문제
clone이나 table rename/copy가 OFF와 selected RK를 보존하는지 없다. 기본 ON이 적용되면 환경 parity가 깨진다.

### 왜 중요한가
green 환경에서 다른 policy로 시험하면 전환 후 부하와 데이터 결과가 예상과 다르다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE local_cache RENAME TO local_cache_old;
SHOW CREATE TABLE local_cache_old;
```

policy/RK identity 보존이 미정이다.

### 권고안
지원 clone/copy/rename별 metadata 보존 규칙과 policy checksum manifest를 제공한다.

### 검증 방법
blue schema를 green에 복제해 모든 table의 ON/OFF, selected RK와 failover test 결과를 비교한다.

## [앱개발자-3년차-32] CDC·outbox 소비자가 OFF와 RK 변경을 해석할 계약이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문은 HA 복제만 다루고 변경 데이터 캡처·외부 consumer와의 상호작용은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 관련 CDC/tool 지원 범위 확인 필요
- 영향 대상: event-driven 애플리케이션, integration

### 문제
OFF DML이 CDC에는 보이는지, RK 변경 때 event key schema가 바뀌는지 없다.

### 왜 중요한가
downstream consumer가 key를 partitioning·dedup에 쓰면 예고 없는 전환으로 순서와 중복 제거가 깨진다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY,
 ADD CONSTRAINT uk_external UNIQUE(external_id);
UPDATE orders SET status='PAID' WHERE id=10;
```

외부 event key가 id인지 external_id인지 미정이다.

### 권고안
HA RK와 CDC key의 관계, schema event, compatibility version, OFF 포함 여부를 명시하고 consumer migration 예제를 제공한다.

### 검증 방법
지원 CDC 도구로 DDL 전후 event를 수집해 key schema, order, duplicate와 OFF event를 검사한다.

## [앱개발자-3년차-33] tenant별 데이터 보호 정책을 한 테이블 속성만으로 표현하기 어렵다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문은 table 전체에 ON/OFF 하나를 설정한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: multi-tenant 애플리케이션, 데이터 거버넌스

### 문제
같은 shared table의 일부 tenant만 local/non-HA로 운영할 수는 없다. 팀이 tenant 요구를 맞추려고 table을 분리하면 FK·migration 복잡도가 생긴다.

### 왜 중요한가
정책 단위가 table임을 명확히 알아야 schema architecture를 결정할 수 있다. row별 예외를 가정하면 데이터가 의도와 다르게 복제된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE tenant_cache (
 tenant_id INT NOT NULL, cache_key VARCHAR(100) NOT NULL,
 value VARCHAR(1000), UNIQUE(tenant_id,cache_key)
) REPLICATION=OFF;
```

한 tenant만 ON으로 만들 수 없다.

### 권고안
정책 단위가 table임을 명시하고 tenant별 요구가 다르면 table/schema 분리, FK 제한, migration 비용을 설명한다.

### 검증 방법
tenant별 ON/OFF 요구가 있는 sample architecture를 문서 가이드로 설계하고 failover 시 각 tenant 결과가 요구와 같은지 확인한다.

## [앱개발자-3년차-34] failover 직후 replica read의 read-after-write 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 failover 후 VIEW/FK 문제를 다루지만 최근 성공 write의 가시성은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자 요청, cache, API 일관성

### 문제
primary에서 성공한 직후 failover하면 새 primary가 해당 write를 반드시 포함하는지, 앱이 이전 값을 읽을 수 있는지 없다.

### 왜 중요한가
사용자는 성공 응답 뒤 자신의 변경을 다시 볼 것으로 기대한다. 이전 값을 읽으면 중복 요청이나 잘못된 보상이 발생한다.

### 재현 또는 구체적 예제

```sql
UPDATE profile SET nickname='neo' WHERE user_id=7;
COMMIT;
-- 즉시 failover 후 SELECT
```

`neo` 보장의 범위가 없다.

### 권고안
복제 mode별 RPO, commit acknowledgment, failover read consistency를 명시한다. 필요하면 write token/LSA를 전달해 새 primary가 해당 위치까지 왔는지 확인하게 한다.

### 검증 방법
commit 처리 각 시점에 failover를 주입하고 API가 반환한 값·retry·cache invalidation을 검증한다.

## [앱개발자-3년차-35] application 시작 시 schema/RK readiness 확인 계약이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 7절은 HA 시작 검사만 다루고 application startup gate는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 배포, readiness probe

### 문제
DB HA가 시작됐어도 migration 미완료, 다른 RK epoch, apply lag으로 앱의 새 버전을 받을 준비가 안 됐을 수 있다.

### 왜 중요한가
앱이 먼저 traffic을 받으면 schema error나 오래된 data를 사용자에게 노출한다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, replication FROM db_class
WHERE class_name IN ('customer','orders');
```

ON만으로 migration/RK/apply readiness를 알 수 없다.

### 권고안
앱이 확인할 machine-readable schema version, selected RK epoch, apply health, minimum DB version endpoint를 정의한다.

### 검증 방법
migration·replication을 의도적으로 지연하고 readiness probe가 traffic을 차단했다가 조건 충족 후 열리는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 15개
- 최종 리뷰 항목 수: 35개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID 파티션·trigger·bulk·CDC·clone 기능과 ORM별 실제 지원 범위, PITR의 RK metadata 보존, server/driver의 prepared statement invalidation과 write-token 지원 여부
