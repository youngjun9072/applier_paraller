# DB를 사용하는 애플리케이션 개발자 / 5년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 대규모 애플리케이션 배포, 높은 동시성, ORM·migration 도구 호환, 관측성과 성능, FK·VIEW·failover 등 기능 상호작용을 검토했다.
- 확인하지 못한 전제: 실제 CUBRID 복제 로그와 DDL 잠금 구현, JDBC 오류·failover 동작, 카탈로그 API, ORM dialect 지원 버전, `fail_count` 정의와 혼합 버전 지원 정책은 원문만으로 확인하지 못했다.

## 컨셉·문제 정의·대안 (3개)

## [앱개발자-5년차-01] RK의 정합성 보장 범위가 행 탐색에만 머물러 있다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 PK 또는 NOT NULL UK를 RK로 선택하고 4절은 후보가 하나 이상 남도록 제한한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션, 복제 정합성, 장애 복구

### 문제
RK가 있으면 standby에서 행을 찾을 수 있다는 전제만 있고, 로그 생성 당시 RK 정의와 적용 당시 정의가 다를 때의 보장은 없다. 이미 쌓인 DML, DDL 전환, 재시도를 아우르는 시간축 계약이 빠졌다.

### 왜 중요한가
대규모 서비스에서는 apply lag이 수분 이상 생길 수 있다. source가 새 키로 전환한 동안 standby가 구 키 로그를 처리해야 하면 현재 키 존재만으로 안전하지 않다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE orders (
  id BIGINT PRIMARY KEY,
  external_id VARCHAR(100) NOT NULL UNIQUE,
  status VARCHAR(20)
) REPLICATION=ON;
UPDATE orders SET status='PAID' WHERE id=100;
ALTER TABLE orders DROP PRIMARY KEY;
```

첫 로그가 `id=100`을 담고 두 번째 DDL 뒤에는 `external_id`가 RK라면, 지연 standby가 구 로그를 어떻게 적용하는지 없다.

### 권고안
로그마다 RK schema version과 구 키 값을 보존하고 모든 미적용 로그가 해석 가능해야 한다는 불변식을 정의한다. 구 RK 메타데이터의 폐기 시점을 전체 standby apply 위치와 연결한다.

### 검증 방법
apply를 지연한 상태에서 DML과 RK DDL을 교차 실행한다. 지연 시간과 재시작 여부를 바꿔도 양 노드 checksum과 `fail_count`가 일치하는지 확인한다.

## [앱개발자-5년차-02] 자동 RK 선택이 서비스 성능 SLO와 분리되어 있다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 1절은 PK 우선, 이후 여러 UK 중 엔진이 하나를 선택한다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 성능, 용량 계획

### 문제
후보의 폭, 타입, 변경 빈도를 고려하는지 없다. 짧은 숫자 키와 긴 복합 문자열 키 중 잘못된 선택은 로그·네트워크·인덱스 비용을 키우지만 애플리케이션은 선택을 통제할 수 없다.

### 왜 중요한가
요청당 비용이 조금만 늘어도 초당 수만 건에서는 큰 차이가 난다. staging과 production에서 선택 RK가 다르면 성능 시험도 무효가 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE event (
  event_id BIGINT NOT NULL UNIQUE,
  tenant VARCHAR(100) NOT NULL,
  source VARCHAR(200) NOT NULL,
  external_ref VARCHAR(500) NOT NULL,
  UNIQUE(tenant,source,external_ref)
) REPLICATION=ON;
```

복합 문자열 UK가 선택되면 모든 UPDATE 로그의 식별 값이 커질 수 있다.

### 권고안
명시적 RK 지정 기능과 후보별 예상 key byte 크기·cardinality 조회를 제공한다. 자동 선택은 안정적 비용 규칙을 공개하고 선택 변경 시 경고한다.

### 검증 방법
두 후보를 각각 RK로 고정해 동일 부하를 실행한다. TPS, p99, 로그 바이트, network, apply lag을 비교하고 자동 선택이 기준을 충족하는지 확인한다.

## [앱개발자-5년차-03] OFF를 데이터 등급과 연결하지 않으면 조직적으로 오용된다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절·6절은 OFF 데이터와 VIEW 결과의 불일치를 책임지지 않는다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션, 데이터 거버넌스, failover

### 문제
OFF는 스키마 작성자가 자유롭게 지정할 수 있으나 중요 데이터, 개인정보, 재생성 가능 캐시를 구분하는 통제 장치가 없다. 여러 팀이 사용하는 DB에서는 편의상 OFF가 퍼질 수 있다.

### 왜 중요한가
복제되지 않는 데이터가 주문·권한에 섞이면 failover 후 조용한 손실이 난다. 코드 리뷰만으로 수백 테이블의 위험을 계속 관리하기 어렵다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE authorization_grant (
  user_id BIGINT, resource_id BIGINT,
  UNIQUE(user_id,resource_id)
) REPLICATION=OFF;
```

문법상 허용되지만 failover 후 권한 결과가 달라질 수 있다.

### 권고안
OFF 허용 데이터 등급, owner, 재구축 source와 RTO를 metadata로 기록하게 한다. CI policy가 중요 도메인의 OFF를 차단하고 예외는 승인하도록 한다.

### 검증 방법
스키마 저장소에서 OFF 테이블을 수집해 owner·등급 정보 누락을 검사한다. failover game day에서 각 OFF 테이블의 재구축이 선언 RTO 안에 끝나는지 확인한다.

## 용어·기본값·사용자 계약 (2개)

## [앱개발자-5년차-04] 실제 RK와 후보의 machine-readable 계약이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 1절은 후보 선택을 설명하지만 2-3절 조회는 ON/OFF만 예시로 든다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: migration lint, ORM, 관측 도구

### 문제
자동화가 실제 RK, 후보, 선택 이유, schema version을 안정적으로 조회할 인터페이스가 없다. `SHOW CREATE TABLE` 문자열 파싱은 포맷 변경에 취약하다.

### 왜 중요한가
대규모 배포에서는 사람이 테이블을 하나씩 보지 않는다. 배포 gate가 위험한 RK 변경을 감지하려면 구조화된 metadata가 필요하다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, replication FROM db_class WHERE class_name='customer';
```

이 결과로는 현재 RK 제약·컬럼·후보를 알 수 없어 migration 영향 분석이 불가능하다.

### 권고안
시스템 catalog view로 `table`, `selected_rk`, `ordered_columns`, `candidates`, `schema_epoch`를 제공하고 버전 호환성을 약속한다.

### 검증 방법
CI가 metadata를 읽어 RK 삭제·nullable 전환을 차단하는 integration test를 만든다. 재시작·복원 후에도 동일 결과인지 확인한다.

## [앱개발자-5년차-05] 기본 ON은 환경 간 schema parity를 깨뜨릴 수 있다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 생략 시 ON, 3절은 single에서도 무키 ON 생성을 허용, 7절은 HA 전환에서 실패한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: CI/CD, ORM 사용자, 운영 환경

### 문제
개발·test는 single, production은 HA이면 동일 migration이 다른 시점에 실패한다. ORM 보조 테이블과 temporary-like 영구 테이블도 모두 ON으로 분류된다.

### 왜 중요한가
CI 성공이 production 성공을 예측해야 한다. 오류가 HA start 때까지 지연되면 배포나 장애 복구의 critical path에서 발견된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE batch_work (job_id BIGINT, shard_no INT, payload VARCHAR(1000));
```

single에는 생성되지만 암묵적 ON·무키 상태로 운영 HA를 막을 수 있다.

### 권고안
CI에서 HA strict schema mode를 제공하고 옵션 생략을 lint할 수 있게 한다. 신규·기존·load 테이블의 기본값을 구분하고 production과 같은 검사를 사전에 수행한다.

### 검증 방법
동일 migration bundle을 single strict와 HA에 적용해 결과가 같은지 확인한다. ORM이 만든 모든 테이블도 검사 목록에 포함한다.

## SQL 문법과 상태 전이 (3개)

## [앱개발자-5년차-06] schema-as-code가 REPLICATION 상태 drift를 교정할 방법이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절은 새 CREATE/ALTER 옵션과 SHOW/db_class 조회를 추가한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ORM, migration 도구, GitOps 배포

### 문제
도구가 ON/OFF를 모델 속성으로 저장·비교할 표준 contract가 없다. introspection 누락으로 운영에서 수동 변경된 OFF가 drift 검사에 보이지 않을 수 있다.

### 왜 중요한가
선언 파일은 ON인데 실제 테이블은 OFF이면 배포는 성공해도 데이터는 보호되지 않는다. 반대로 자동 교정이 HA 중 OFF→ON을 실행하면 문서상 실패한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE session REPLICATION=OFF;
-- 이후 migration 도구가 선언 모델 ON과 실제 상태를 비교
```

도구가 차이를 읽는 법과 HA에서 안전하게 교정하는 법이 없다.

### 권고안
metadata API와 migration DSL 매핑을 제공한다. drift는 자동 수정 전에 위험도와 모드 제약을 보고하고 OFF→ON은 별도 재동기화 workflow로 보내야 한다.

### 검증 방법
수동 ON→OFF drift를 만든 뒤 schema diff를 실행한다. 정확히 탐지하고 HA에서 위험한 자동 ALTER를 실행하지 않는지 확인한다.

## [앱개발자-5년차-07] 키 교체 DDL의 원자성과 migration ledger가 연결되지 않는다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절·4-2절은 한 ALTER의 DROP+ADD를 허용하지만 부분 실패·rollback을 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: CI/CD, 복제 정합성, 애플리케이션

### 문제
새 UK 생성이 중복·disk full·timeout으로 실패할 때 기존 키와 migration history의 상태가 어떻게 정렬되는지 없다. DDL 자동 commit이면 도구 transaction과 결과가 달라질 수 있다.

### 왜 중요한가
배포 시스템은 migration ledger를 보고 재시도한다. DB는 반쯤 바뀌었는데 ledger만 실패면 같은 ALTER 재실행이 더 큰 오류를 만든다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE coupon (id INT PRIMARY KEY, code VARCHAR(20)) REPLICATION=ON;
INSERT INTO coupon VALUES (1,'A'),(2,'A');
ALTER TABLE coupon DROP PRIMARY KEY,
 ADD CONSTRAINT uk_coupon_code UNIQUE(code);
```

ADD 실패 시 PK/RK와 migration ledger가 모두 변경 전이어야 한다.

### 권고안
DDL 원자성·commit 규칙을 명시하고 사전 검증, 실행, 사후 assertion으로 나눈 migration template을 제공한다. 재시도 가능한 상태 식별도 정의한다.

### 검증 방법
각 내부 단계에 장애를 주입하고 migration runner를 재시작한다. DB state와 ledger가 한 단계로 수렴하며 RK가 항상 유효한지 확인한다.

## [앱개발자-5년차-08] 온라인 RK 변경에 expand-contract 상태가 정의되지 않았다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절은 기존 키와 다른 후보가 있으면 DDL을 허용하지만 단계적 데이터 채움과 앱 호환은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 대규모 배포, 애플리케이션 버전 호환

### 문제
새 RK 컬럼을 nullable로 추가한 뒤 backfill하고 NOT NULL UK로 만드는 동안에는 후보가 아니다. 각 단계에서 old/new 앱과 RK가 어떤 상태인지 정의되지 않았다.

### 왜 중요한가
대형 테이블은 한 transaction으로 새 키를 채울 수 없다. 여러 시간 동안 dual-write와 backfill이 공존하며 누락·충돌을 막아야 한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer ADD COLUMN customer_uuid VARCHAR(36);
-- 작은 batch로 반복
UPDATE customer SET customer_uuid=? WHERE id=? AND customer_uuid IS NULL;
ALTER TABLE customer ADD CONSTRAINT uk_customer_uuid UNIQUE(customer_uuid);
```

NOT NULL 전환, dual-write 종료, RK 교체 순서가 원문에 없다.

### 권고안
expand → dual-write → resumable backfill → 검증 → NOT NULL UK → RK 전환 → contract의 상태표와 rollback point를 제공한다.

### 검증 방법
구·신 앱을 동시에 실행하고 backfill을 중단·재개한다. NULL·중복이 없고 모든 단계에서 읽기/쓰기와 복제가 정상인지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [앱개발자-5년차-09] 병렬 apply와 동시 DDL/DML의 ordering contract가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 모든 DDL 복제와 RK 변경을 다루지만 DML과의 순서·병렬 적용은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, 애플리케이션, DBA

### 문제
높은 처리량을 위해 로그 apply가 병렬이라면 RK DDL 앞뒤 DML에 barrier가 필요하다. 트랜잭션 커밋 순서와 standby 적용 순서가 어떻게 일치하는지 없다.

### 왜 중요한가
새 RK를 요구하는 UPDATE가 DDL보다 먼저 적용되거나 구 RK 로그가 DDL 뒤에 적용되면 행을 찾지 못할 수 있다.

### 재현 또는 구체적 예제

```sql
UPDATE customer SET name='A' WHERE id=10;
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_customer_email UNIQUE(email);
UPDATE customer SET name='B' WHERE email='a@example.com';
```

standby가 반드시 이 순서를 지켜야 한다.

### 권고안
table/schema epoch별 DDL barrier와 병렬 apply 제한을 정의한다. 앱이 DDL 완료와 모든 standby 적용을 확인할 수 있는 wait API를 제공한다.

### 검증 방법
병렬 apply와 큰 lag을 켜고 세 이벤트를 반복한다. 적용 trace 순서와 최종 checksum, 오류율을 확인한다.

## [앱개발자-5년차-10] DDL 부하가 connection pool 전체로 전파되는 위험이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 4-2절은 운영 중 키 추가·교체를 허용하지만 잠금·진행률·취소 동작은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션 응답 시간, connection pool, 배포

### 문제
대형 UK 인덱스 구축이 DML을 막으면 pool connection이 대기 요청으로 소진될 수 있다. timeout 뒤 DDL이 계속되는지, cancel이 안전한지도 없다.

### 왜 중요한가
한 테이블 migration이 무관한 API까지 장애로 만들 수 있다. retry가 겹치면 DB 부하가 더 커지는 연쇄 장애가 난다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE billion_row_order
 ADD CONSTRAINT uk_order_external UNIQUE(external_id);
-- 동시에 수천 개 UPDATE/SELECT 요청
```

읽기·쓰기 잠금 범위와 p99 영향이 불명확하다.

### 권고안
온라인 가능 여부, lock phase, 진행률, cancel/rollback, timeout 오류를 명시한다. 앱에는 pool 격리, circuit breaker, retry budget, maintenance window 가이드를 제공한다.

### 검증 방법
production 규모 복제본과 실제 pool 설정으로 부하 테스트한다. pool saturation, p99, error rate, lag가 수용 기준 안인지 확인한다.

## [앱개발자-5년차-11] failover 중 outcome-unknown 쓰기의 멱등성 계약이 빠졌다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절·6절은 failover 후 조회를 말하지만 열린 connection과 commit 결과는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 결제·주문 애플리케이션, 데이터 중복

### 문제
COMMIT 성공 응답 전 연결이 끊기면 앱은 적용 여부를 모른다. 드라이버 자동 재연결과 transaction 재실행 범위도 정의되지 않았다.

### 왜 중요한가
무조건 재시도하면 이중 결제, 재시도하지 않으면 주문 누락이 생긴다. RK는 이 업무 중복을 해결하지 않는다.

### 재현 또는 구체적 예제

```sql
INSERT INTO payment(payment_id,order_id,amount) VALUES ('P100',10,5000);
COMMIT;
-- 응답 직전 failover
```

새 primary에서 `P100` 존재를 확인한 뒤 재시도할 계약이 필요하다.

### 권고안
commit outcome unknown 오류, driver 재연결 범위, RPO를 명시한다. 전 요청에 idempotency key를 저장하고 새 transaction으로 결과 조회 후 조건부 재시도하는 패턴을 제공한다.

### 검증 방법
commit 여러 단계에서 장애를 주입하고 대량 retry를 발생시킨다. 최종 업무 행이 요청당 정확히 하나이고 사용자 응답이 일관적인지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [앱개발자-5년차-12] RK 변경 UPDATE의 멱등성과 충돌 의미가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 RK DDL만 설명하고 RK 컬럼 값 DML은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, 복제 정합성

### 문제
RK 값을 바꿀 때 old/new 키 중 무엇으로 탐색하는지, 로그 재적용 시 이미 new 값이면 성공으로 볼지 오류로 볼지 없다.

### 왜 중요한가
email·external_id 같은 업무 키 변경은 흔하다. 재시작이나 중복 전달에서도 한 행만 정확히 바뀌어야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (email VARCHAR(320) NOT NULL UNIQUE, name VARCHAR(50)) REPLICATION=ON;
UPDATE member SET email='new@example.com' WHERE email='old@example.com';
```

standby는 old로 찾고 new 유일성을 확인해야 하며 재적용도 안전해야 한다.

### 권고안
로그의 before/after RK, 0행·복수행·new 충돌, retry semantics를 명시한다. 실패가 table apply를 중단하는지 격리하는지도 정의한다.

### 검증 방법
동일 로그 재적용, new 값 선점, target 행 누락을 각각 재현한다. 오류 분류와 최종 데이터가 규정대로인지 확인한다.

## [앱개발자-5년차-13] FK 그래프와 서비스 경계가 충돌할 수 있다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절은 ON 자식의 부모도 ON이어야 한다고 하지만 다단계·순환·CASCADE와 ON→OFF 전환은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 마이크로서비스, ORM, 참조 무결성

### 문제
여러 서비스가 공유 DB에서 서로 소유한 테이블을 FK로 연결하면 한 팀의 OFF 변경이 다른 서비스 배포를 막거나 정합성을 깨뜨릴 수 있다. 전체 의존 경로 출력이 없다.

### 왜 중요한가
직접 부모만 확인해도 cascade나 중첩 참조로 변경 영향이 멀리 전파된다. 소유 팀이 다르면 사전 조율이 필요하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT,
 FOREIGN KEY(customer_id) REFERENCES customer(id)) REPLICATION=ON;
ALTER TABLE customer REPLICATION=OFF;
```

ALTER가 어떤 owner/service에 영향을 주는지 문서로 알 수 없다.

### 권고안
CREATE/ALTER/HA 검사에서 전체 FK 그래프와 CASCADE를 분석하고 위반 경로·owner를 출력한다. schema registry와 배포 승인 예제를 제공한다.

### 검증 방법
다단계·순환 FK를 여러 schema owner로 만들고 OFF 전환을 시도한다. 모든 영향 경로가 탐지되고 부분 변경이 남지 않는지 확인한다.

## [앱개발자-5년차-14] OFF 의존 VIEW가 데이터 API 캐시를 오염시킬 수 있다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절은 VIEW 실행에는 제약이 없으나 OFF 데이터 때문에 노드 간 결과가 다를 수 있다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: API, 캐시, 분석·보고 시스템

### 문제
failover 후 잘못된 VIEW 결과가 정상 응답으로 캐시에 저장되면 OFF 데이터를 재구축한 뒤에도 오류가 오래 지속된다. 중첩 VIEW 의존성도 표시되지 않는다.

### 왜 중요한가
DB가 회복돼도 CDN·Redis·앱 캐시에 빈 목록이나 잘못된 집계가 남는다. 장애 영향이 DB 밖으로 확산된다.

### 재현 또는 구체적 예제

```sql
CREATE VIEW priced_item AS
 SELECT i.id, i.price-d.discount final_price
 FROM item i JOIN local_discount d ON i.id=d.item_id;
```

`local_discount`가 OFF이고 failover 후 비면 API가 빈 결과를 1시간 캐시할 수 있다.

### 권고안
OFF 전이 의존성을 조회하고 failover 이벤트를 앱에 전달한다. 영향 API의 cache bypass/invalidation 및 데이터 재구축 후 readiness 복원 순서를 명시한다.

### 검증 방법
failover 후 API 호출로 캐시를 채운 뒤 OFF 데이터 재구축을 수행한다. invalidation이 실행되고 정상 결과가 즉시 복원되는지 확인한다.

## 운영·오류·관측 가능성 (2개)

## [앱개발자-5년차-15] 복제 실패를 요청·배포와 연결할 telemetry 계약이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문은 여러 `ERROR`와 HA 검사만 제시하며 `fail_count` 상세 및 앱 추적 연결을 다루지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션, SRE, 장애 대응

### 문제
복제 오류에 table, RK hash, LSA, schema migration version, 최초 request 시각이 없으면 어떤 배포와 사용자 요청이 영향을 받았는지 찾기 어렵다.

### 왜 중요한가
대규모 서비스에서는 단일 숫자 증가만으로 영향 범위를 계산할 수 없다. 장애 복구와 고객 안내가 늦어진다.

### 재현 또는 구체적 예제

```sql
UPDATE order_item SET qty=3 WHERE order_id=100 AND line_no=2;
```

앱 trace `R-77`에서 발생한 변경이 standby에서 실패했을 때 DB 사건과 연결할 공통 정보가 없다.

### 권고안
구조화 이벤트에 DB/table/schema_epoch/LSA/error code/RK 안전 hash를 넣고 metrics·logs·traces 연결 규칙을 제공한다. 민감 키 원문은 권한으로 보호한다.

### 검증 방법
canary 배포 직후 적용 오류를 유발한다. trace에서 실패 로그와 영향 행까지 정해진 시간 내 추적 가능하며 민감정보가 노출되지 않는지 확인한다.

## [앱개발자-5년차-16] 오류 코드에 retry·rollback·격리 상태가 포함되지 않는다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2절·4절·5절의 실패 결과는 주로 `ERROR`뿐이다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 오류 처리, CI/CD

### 문제
RK 없음, lock timeout, mixed-version 거부, FK 정책 위반이 동일하게 보인다. transaction이 전체 rollback됐는지와 재시도 가능 여부도 없다.

### 왜 중요한가
무조건 retry는 폭주를 만들고 정책 오류는 절대 해결하지 못한다. 반대로 일시 오류를 즉시 실패시키면 가용성이 낮아진다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE cache REPLICATION=ON;
ALTER TABLE orders DROP PRIMARY KEY;
```

둘 다 HA에서 실패할 수 있지만 수정 행동이 다르다.

### 권고안
안정된 code/SQLSTATE, retryable, transaction state, failed object, cluster mode를 정의한다. SDK별 예외 분류와 exponential backoff가 허용되는 오류 목록을 제공한다.

### 검증 방법
각 오류를 JDBC에서 발생시키고 자동 처리 분기를 검증한다. locale과 patch version 변경에도 코드 의미가 유지되는지 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [앱개발자-5년차-17] 혼합 버전 클러스터의 feature gate가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절·8절은 새 SQL·카탈로그·dump 필드를 도입하지만 rolling upgrade는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, DB 롤링 업그레이드, rollback

### 문제
신버전 source가 새 DDL/RK 로그를 생성하면 구버전 standby가 이해하는지 없다. 앱 migration이 클러스터 일부만 업그레이드된 상태에서 실행될 수 있다.

### 왜 중요한가
DB와 앱 fleet을 동시에 교체할 수 없다. 새 기능이 일찍 사용되면 복제가 멈추고 구버전으로 rollback도 못할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE local_cache REPLICATION=OFF;
```

구버전 standby가 있는 상태에서 이 SQL을 source가 받아야 하는지 불명확하다.

### 권고안
cluster capability와 minimum version을 조회하게 하고 migration runner가 feature gate를 검사하도록 한다. 지원 행렬, activation point, downgrade 제한을 제공한다.

### 검증 방법
모든 인접 버전 조합에서 migration, CRUD, failover, app rollback을 실행한다. 미지원 SQL은 로그 생성 전 명확히 거부되는지 확인한다.

## [앱개발자-5년차-18] 구버전 dump 기본값 충돌이 재현 환경의 신뢰를 없앤다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 필드 없음=ON, 9절은 필드 없음=OFF라고 서로 다르게 말한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: CI, staging, 재해복구

### 문제
같은 production dump를 CI/staging/DR에 load해도 기대 ON/OFF를 정할 수 없다. 테스트 환경이 운영과 다른 복제 정책을 갖게 될 수 있다.

### 왜 중요한가
성능·failover 시험은 schema policy가 같아야 유효하다. OFF가 ON으로 바뀌면 부하는 늘고, ON이 OFF로 바뀌면 정합성 검사가 무의미하다.

### 재현 또는 구체적 예제

```sql
-- legacy dump
CREATE TABLE legacy_audit (event_time DATETIME, body VARCHAR(1000));
```

신버전 load 후 값의 단일 정답이 없다.

### 권고안
충돌을 해소하고 `--default-replication=ON|OFF|ERROR`를 명시하게 한다. dry-run manifest와 load 후 policy checksum을 제공한다.

### 검증 방법
동일 dump와 설정으로 CI/staging/DR을 만들고 모든 테이블의 policy checksum과 HA 사전 검사 결과를 비교한다.

## 문서 품질·예제·오탈자 (2개)

## [앱개발자-5년차-19] 규범 상태표 없이 산재한 예제로는 자동 검증을 만들기 어렵다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~7절에 모드별 예제가 흩어져 있고 오류는 대부분 `ERROR`이며 Single/SA 용어가 혼용된다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 개발자, QA, migration 도구

### 문제
single/SA/HA × ON/OFF × RK 후보 수 × DDL 종류의 기대 결과를 한눈에 볼 규범 표가 없다. 예제만으로는 누락된 조합을 알 수 없다.

### 왜 중요한가
자동 회귀 테스트는 입력 상태와 기대 code가 명확해야 한다. 산문 해석으로 팀마다 다른 테스트를 만들 가능성이 크다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE t REPLICATION=ON;
ALTER TABLE t REPLICATION=OFF;
ALTER TABLE t DROP PRIMARY KEY;
```

세 SQL의 모드별, 후보 0/1/2개별 결과표가 필요하다.

### 권고안
모든 상태 전이를 표와 고유 requirement ID로 정의하고 각 칸에 성공 또는 오류 코드를 넣는다. 예제는 해당 ID를 참조하게 한다.

### 검증 방법
표의 각 칸을 parameterized integration test로 생성한다. 명세에 없는 결과와 중복·상충 요구가 없는지 확인한다.

## [앱개발자-5년차-20] 실행 불가능·상충 예제가 릴리스 기준을 훼손한다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2절·5절의 마지막 쉼표와 `...`, 5-1절 `CRATE TABLE`, 7절 오탈자, 8절과 9절 기본값 상충.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 개발자, QA, 기술지원

### 문제
문법 오류 때문에 기능 검증 전에 parser가 실패하고, load 기본값은 두 정답을 가진다. 실제 오류 코드 없이 `ERROR`만 있어 SDK 테스트도 작성할 수 없다.

### 왜 중요한가
스펙은 구현·클라이언트·문서·QA의 공통 계약이다. 모호한 계약은 각 구성 요소가 서로 다른 동작을 구현하게 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE repl_table_without_rk (
  a INT,
) REPLICATION=ON;
```

의도는 모드별 RK 검증이지만 마지막 쉼표로 문법 오류가 먼저 날 수 있다.

### 권고안
모든 SQL 블록을 실제 DB CI에서 실행하고 완전한 제약 이름·오류 code를 기입한다. `CRATE` 등 오탈자와 8/9절 상충을 수정하고 summary는 규범 요구를 자동 생성해 중복 편집을 피한다.

### 검증 방법
문서 예제를 single/SA/HA fixture에서 자동 실행한다. 예상 result/error가 모두 일치하고 parser 오류와 상충 요구가 0건인지 확인한다.

## [앱개발자-5년차-21] 배포 계정의 복제 정책 변경 권한이 분리되지 않았다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-2절은 사용자가 ON/OFF를 변경한다고만 하고 권한 모델은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: CI/CD, migration runner, 업무 데이터 보호

### 문제
schema migration 계정의 일반 ALTER 권한으로 OFF와 RK 변경까지 가능한지 없다. read-only metadata 조회와 위험 변경 권한도 분리되지 않았다.

### 왜 중요한가
배포 도구는 넓은 권한을 오래 보유한다. 잘못 생성된 migration이 OFF를 실행하면 코드 배포는 성공해도 다음 failover에서 데이터가 사라진 것처럼 보인다.

### 재현 또는 구체적 예제
```sql
-- CI migration 계정이라고 가정
ALTER TABLE settlement REPLICATION=OFF;
```
실행 성공 여부, 승인 필요 여부와 transaction rollback 범위가 없다.

### 권고안
metadata read, CREATE 지정, ON→OFF, OFF→ON, RK 변경을 별도 권한으로 분리한다. CI는 dry-run 권한만 기본 부여하고 위험 변경은 승인 token을 요구한다.

### 검증 방법
CI·app runtime·DBA 계정별 up/down migration을 실행한다. 권한 우회와 connection reuse 후 stale privilege가 없는지 확인한다.

## [앱개발자-5년차-22] 상태 변경 감사 이벤트를 배포·요청 추적과 연결할 수 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절은 현재 상태만 조회하며 변경 이력 API는 누락한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 배포 추적, incident response, 감사

### 문제
ON/OFF·RK 변경에 actor, migration ID, trace/deployment ID, old/new state와 LSA를 연결하는 이벤트가 없다.

### 왜 중요한가
복제 오류가 배포 30분 뒤 나타나면 애플리케이션 로그와 DB 변경을 시간만으로 맞춰야 한다. 여러 서비스가 동시에 배포되면 원인 찾기가 어렵다.

### 재현 또는 구체적 예제
release-842가 `orders` RK를 바꾸고 곧 `fail_count`가 증가한다. DB 감사에 release-842나 constraint old/new가 없으면 어떤 배포를 rollback할지 알 수 없다.

### 권고안
DDL comment/session context의 deployment ID를 감사 event에 보존하고 actor/time/object/old-new/RK/transaction/result를 구조화해 제공한다.

### 검증 방법
여러 병렬 배포에서 성공·실패·rollback DDL을 실행한다. tracing backend가 각 DB event를 정확한 release에 연결하는지 확인한다.

## [앱개발자-5년차-23] 파티션·샤드 라우팅 키와 RK의 결합 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1~4절은 일반 테이블만 설명하며 파티션·샤딩 상호작용은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 분할 데이터 서비스, ORM routing, 복제 정합성

### 문제
대상 CUBRID/배포 구성이 파티션 또는 샤딩을 지원한다면 RK가 routing key를 반드시 포함해야 하는지, 파티션별 UK도 유효한지, 이동 중 DML이 어떻게 적용되는지 없다.

### 왜 중요한가
같은 `id=10`이 두 shard/partition에 있으면 id만으로 replica 행을 고를 수 없다. 애플리케이션은 tenant/routing key를 생략한 ORM query를 만들 수도 있다.

### 재현 또는 구체적 예제
```sql
CREATE TABLE tenant_order (
 tenant_id INT NOT NULL, order_id INT NOT NULL,
 PRIMARY KEY(tenant_id,order_id)
) REPLICATION=ON;
```
tenant를 옮기는 작업과 RK 변경이 겹칠 때 before/after routing 결과가 없다.

### 권고안
지원 범위를 확인해 routing key 포함 규칙, global/local uniqueness, 이동/attach/detach의 schema barrier와 ORM query 조건을 명시한다.

### 검증 방법
동일 order_id를 여러 영역에 만들고 이동 중 CRUD/failover를 실행한다. 정확한 tenant 행만 바뀌는지 확인한다.

## [앱개발자-5년차-24] bulk ingest와 outbox/CDC 전달의 원자성 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 일반 DML과 loaddb만 다루며 bulk·외부 변경 소비는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ETL, outbox, CDC 소비자, 이벤트 일관성

### 문제
bulk load·TRUNCATE가 row log를 만드는지, outbox/CDC가 REPLICATION OFF와 같은 필터를 보는지, batch와 업무 event의 commit 경계가 없다.

### 왜 중요한가
DB 행은 적재됐지만 event가 없으면 검색·캐시·메시지 소비자가 갱신되지 않는다. 반대로 replay가 중복되면 downstream 이벤트도 두 번 처리될 수 있다.

### 재현 또는 구체적 예제
한 batch가 `orders` 1만 행과 `outbox` 1만 행을 적재하다 중단된다. orders ON, outbox OFF라면 failover 후 업무 행은 있지만 발행 event가 없을 수 있다.

### 권고안
지원 bulk 경로의 row logging, transactional batch, OFF 필터와 CDC/outbox 호환을 표로 정한다. resume token과 idempotent consumer 패턴을 제공한다.

### 검증 방법
batch 중단·retry·failover에서 업무 행과 event ID를 비교한다. downstream이 누락·중복 없이 한 번 처리하는지 확인한다.

## [앱개발자-5년차-25] PITR 후 애플리케이션 이벤트 재생 기준이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load만 설명하고 PITR과 앱 event replay는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 재해 복구, event-driven 앱, idempotency

### 문제
PITR 지원 시 DB 목표 시점의 RK/schema version, outbox offset와 외부 broker offset을 어떻게 맞추는지 없다. RK DDL log가 만료된 경우도 미정이다.

### 왜 중요한가
DB를 03:30으로 돌렸는데 broker가 04:00이면 이미 취소된 행의 이벤트가 다시 적용될 수 있다. 반대면 DB 행은 있지만 이벤트가 없다.

### 재현 또는 구체적 예제
02시 RK switch, 03시 order/outbox commit, 04시 사고 후 03:30 PITR을 한다. 소비자 offset과 DDL/DML logs를 같은 recovery point에 맞춰야 한다.

### 권고안
backup manifest에 schema/RK version과 application recovery token을 포함하고 broker/cache/search 재생 순서와 idempotency 기준을 정의한다.

### 검증 방법
여러 목표 시점 restore 후 event replay를 수행한다. API·DB·broker projection checksum이 일치하는지 확인한다.

## [앱개발자-5년차-26] 물리 snapshot으로 만든 테스트 환경의 schema/RK 일관성이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 8절은 논리 unload/load만 설명하고 storage snapshot은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: staging clone, CI 성능 시험, 재해 복구

### 문제
data/catalog/log snapshot을 어떤 시점에 함께 떠야 하는지, standby snapshot을 개발 환경에 복제해도 되는지 없다.

### 왜 중요한가
RK metadata와 index build가 다른 시점이면 clone은 열려도 migration 시험 결과가 운영과 다르다. 테스트 성공을 신뢰할 수 없다.

### 재현 또는 구체적 예제
email UK build 중 data volume과 log volume을 다른 초에 snapshot해 staging을 만든다. `SHOW`는 새 RK지만 index가 불완전할 수 있다.

### 권고안
지원 snapshot 유형, checkpoint/quiesce, volume atomicity, clone 후 schema/RK validation 절차를 문서화한다.

### 검증 방법
DDL 각 phase snapshot clone에서 migration·CRUD·failover simulation을 실행한다. production schema manifest와 같아야 한다.

## [앱개발자-5년차-27] split-brain 중 클라이언트 write fencing과 stale connection 처리가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4·7절은 정상 failover만 설명하고 network partition은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: connection pool, service discovery, 데이터 정합성

### 문제
old primary connection이 pool에 남은 상태에서 new primary가 승격되면 양쪽 write가 가능한지, fencing token을 driver/session에서 확인하는지 없다.

### 왜 중요한가
DNS/service discovery가 바뀌어도 기존 TCP connection은 살아 있을 수 있다. 한쪽은 OFF, 다른 쪽은 새 RK로 쓰면 재결합이 불가능해진다.

### 재현 또는 구체적 예제
pool A는 old primary에 주문101, pool B는 new primary에 주문102를 쓴다. old connection이 즉시 commit 거부돼야 한다.

### 권고안
promotion epoch/fencing token을 write transaction에 검증하고 old sessions를 강제 invalidate한다. driver retry는 idempotency key를 요구한다.

### 검증 방법
network 분할 후 stale pooled connection과 새 connection으로 동시 write한다. 오직 current epoch만 성공하는지 확인한다.

## [앱개발자-5년차-28] 다중 read replica의 schema version 라우팅 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 source/replica 한 쌍만 가정한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: read scaling, connection router, 점진 배포

### 문제
다중 standby/read replica를 지원하는 구성에서 일부만 RK/DDL을 적용했을 때 새 앱 query를 어느 노드로 보내는지 없다.

### 왜 중요한가
새 column을 읽는 앱이 옛 schema replica에 연결되면 column-not-found가 난다. 단순 lag 수치만으로 schema compatibility를 보장할 수 없다.

### 재현 또는 구체적 예제
replica A는 `login_email` DDL 적용, B는 미적용 상태에서 router가 round-robin한다. 새 앱 요청 절반이 실패할 수 있다.

### 권고안
node별 schema/RK version과 capability를 discovery metadata에 노출하고 앱 요구 version 이상 노드로만 route한다.

### 검증 방법
replica별 DDL apply를 지연하고 old/new app query를 routing한다. 호환 node만 선택되고 없으면 명확한 degraded 오류를 내는지 본다.

## [앱개발자-5년차-29] RK 타입·collation을 driver codec과 함께 검증할 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 PK/NOT NULL UK만 말하고 타입별 비교·직렬화는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: driver binding, 다국어 key, JSON/LOB/실수 모델

### 문제
지원 RK 타입, bytes 한도, collation version과 driver parameter codec이 같은 값을 생성하는지 없다.

### 왜 중요한가
Unicode normalization, floating 표현, timezone/decimal 변환이 source query와 replica key encoding에서 다르면 논리적으로 같은 값을 못 찾을 수 있다.

### 재현 또는 구체적 예제
애플리케이션이 서로 다른 Unicode normalization의 `é`를 email UK에 bind한다. DB collation이 같다고 보아도 driver byte 표현과 log key가 어떻게 canonicalize되는지 없다.

### 권고안
지원 타입/collation/normalization과 driver 버전별 codec contract를 제공하고 불안정 타입은 RK 후보에서 거부한다.

### 검증 방법
공식 driver마다 경계 숫자·Unicode·timezone corpus를 round-trip하고 failover 후 동일 entity를 조회한다.

## [앱개발자-5년차-30] index 유지보수 후 prepared statement와 schema cache 처리 규칙이 없다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 4-2절은 DROP INDEX만 다루고 rebuild·rename·통계 갱신은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: prepared statement, ORM metadata cache, connection pool

### 문제
RK index rebuild/constraint rename 뒤 기존 prepared statement가 재사용 가능한지, driver가 schema-changed 오류를 받아 reprepare해야 하는지 없다.

### 왜 중요한가
DB는 논리적으로 같은 RK를 유지해도 물리 descriptor가 바뀔 수 있다. 오래된 pool이 stale plan을 쓰면 일부 instance에서만 오류가 난다.

### 재현 또는 구체적 예제
pool 100개가 email 조회 statement를 prepare한 뒤 UK index를 online rebuild한다. 일부 connection만 재prepare하면 간헐 오류가 생길 수 있다.

### 권고안
유지보수 작업별 RK ID 유지와 schema invalidation event/error code, driver auto-reprepare 지원을 명시한다.

### 검증 방법
여러 driver/pool에서 prepared statement를 유지한 채 rebuild/rename/statistics를 실행한다. 자동 reprepare와 결과 일치를 확인한다.

## [앱개발자-5년차-31] 임시·도구 테이블이 migration drift와 HA 검사를 오염시킬 수 있다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 2-1·7절은 객체 유형별 예외를 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: migration tool, test fixture, HA preflight

### 문제
임시 테이블, ORM migration ledger, ETL stage와 system/tool table이 기본 ON·RK 검사 대상인지 없다.

### 왜 중요한가
세션용 객체 때문에 HA start가 막히거나 migration ledger를 OFF로 해 failover 후 배포 이력이 사라지면 자동화가 잘못된 migration을 재실행한다.

### 재현 또는 구체적 예제
ORM이 키 없는 `_migration_lock`을 영구 생성한다. 기본 ON이면 HA 시작 실패, OFF이면 failover 후 lock history가 없어질 수 있다.

### 권고안
지원 객체 유형별 기본/검사 범위와 migration ledger 권장 schema를 정의한다. tool vendor가 capability를 선언하도록 한다.

### 검증 방법
주요 migration/ETL fixture를 생성해 preflight, failover, 재배포한다. ledger와 lock 상태가 안전한지 확인한다.

## [앱개발자-5년차-32] 신기능 사용 후 down migration과 binary downgrade 경계가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 old dump 입력만 다루며 신기능 사용 후 구버전 원복은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: release rollback, migration down, mixed version

### 문제
OFF 또는 새 RK log를 사용한 뒤 앱 down migration과 DB binary downgrade가 가능한지, 되돌릴 수 없는 epoch가 무엇인지 없다.

### 왜 중요한가
앱 rollback은 코드만 내리면 끝나지 않는다. old app/DB가 새 catalog·log를 이해하지 못하면 서비스는 떠도 복제가 깨질 수 있다.

### 재현 또는 구체적 예제
release N에서 `cache OFF`와 email RK switch를 실행한 뒤 성능 문제로 N-1 앱·DB로 되돌린다. old migration ledger와 engine이 상태를 처리할지 없다.

### 권고안
feature activation epoch, reversible up/down 단계, binary downgrade gate와 full backup/resync 요구를 정의한다. migration tool이 epoch 이후 down을 거부하게 한다.

### 검증 방법
신기능 미사용·OFF 사용·RK switch 각 시점에서 app/DB rollback rehearsal을 한다. 지원 경로는 상태 보존, 미지원 경로는 사전 차단되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 12개
- 최종 리뷰 항목 수: 32개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·샤딩·bulk/CDC·PITR·물리 snapshot·다중 replica·임시 객체 지원 여부와 정확한 문법, 실제 RBAC·감사·fencing·driver codec/cache invalidation API, downgrade epoch 구현
