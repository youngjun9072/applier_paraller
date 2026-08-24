# DB 엔지니어/DBA / 3년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: HA 시작 전 점검, 운영 중 DDL, RK 조회와 변경 계획, failover/failback, `fail_count` 모니터링, 불일치 탐지·교정, 백업·복원과 부하 영향
- 확인하지 못한 전제: 실제 CUBRID 버전의 DDL 잠금 방식, 복제 로그 포맷, `fail_count` 정의, 카탈로그 컬럼, 오류 코드, 혼합 버전 지원 범위는 확인하지 않았다. 원문에 없는 구현 동작은 검증 필요로 취급한다.

## [DBA-3Y-01] RK 보장은 향후 오류만 막고 기존 불일치는 해결하지 않는다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 HA 실행 시 RK 필수 조건과 7절의 HA 전환 검사
- 사실/추론 구분: 확인된 사실 — 문서는 스키마 조건만 검사하며 기존 행 데이터의 차이를 검사하거나 복구하는 절차는 없다
- 영향 대상: DBA, 기존 HA 사용자, 복제 정합성, 장애 조치

### 문제
ON 테이블에 항상 RK 후보가 있게 만드는 규칙은 앞으로의 일부 적용 오류를 예방할 수 있다. 그러나 과거 PK 변경으로 이미 source/replica 데이터가 달라진 경우를 발견하거나 고치지 않는다. 스키마 검사만 통과한 불일치 DB에서 failover하면 잘못된 데이터가 서비스에 노출될 수 있다.

### 왜 중요한가
키는 행을 찾는 주소와 비슷하다. 새 주소 체계를 정해도 과거에 배달되지 않은 물건이 자동으로 생기지는 않는다. 따라서 DBA에게는 기능 적용 전 데이터 비교, 차이 목록, 재동기화, 재검증 순서가 필요하다.

### 재현 또는 구체적 예제
source에는 `(id=1, qty=9)`, replica에는 과거 누락 때문에 `(id=1, qty=10)`이 있다고 가정한다.

```sql
CREATE TABLE stock (
  id INT PRIMARY KEY,
  qty INT NOT NULL
) REPLICATION = ON;

UPDATE stock SET qty = qty - 1 WHERE id = 2;
```

새 UPDATE가 정상 복제되어도 id=1의 차이는 남는다. 문서상 HA 검사는 PK가 있다는 이유로 통과할 수 있다. 기대 결과는 HA 시작 또는 업그레이드 전에 기존 데이터 차이가 별도로 보고되는 것이다.

### 권고안
기능 적용 절차에 테이블별 행 수, RK 구간별 체크섬, 차이 행 상세 조회와 재동기화 방법을 넣는다. 정답 노드를 선택하는 기준과 동기화 중 쓰기 중단 여부도 설명한다. 불일치가 남은 경우 failover를 금지하거나 명시적 운영자 승인을 요구한다.

### 검증 방법
행 누락, 추가 행, 비키 값 변경, 키 값 변경을 의도적으로 만든 뒤 검사 도구가 모두 찾는지 확인한다. 문서 절차로 교정한 후 양 노드의 행 수와 RK 순서의 행별 해시를 비교하고, failover 뒤에도 결과가 같은지 검증한다.

## [DBA-3Y-02] 여러 UK 중 RK 자동 선택은 운영 계획을 세울 만큼 결정적이지 않다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절의 “UK가 여러개 존재하면 엔진이 하나 선택(ex. 명시 순서)”와 4-2절의 엔진 결정
- 사실/추론 구분: 확인된 사실 — 실제 선택 기준, 선택 유지 기간, 재시작·복원 후 지속성이 확정되어 있지 않다
- 영향 대상: DBA, 복제 정합성, 스키마 변경 자동화, 복구 작업

### 문제
여러 NOT NULL UK 중 어느 것이 활성 RK가 되는지 예시만 있고 규칙이 없다. DBA는 삭제하거나 타입을 변경할 제약이 현재 RK인지 판단할 수 없다. unload/load나 백업 복원 뒤 선택이 달라질 가능성도 문서에서 배제하지 않는다.

### 왜 중요한가
모든 UK가 행을 유일하게 찾더라도 복제 로그가 담은 값의 의미는 선택한 컬럼에 따라 다르다. source가 사번 값을 기록했는데 replica가 이메일을 RK로 해석하면 행을 찾지 못한다. 노드마다 같은 키를 선택하고 그 선택이 로그가 적용될 때까지 보존되어야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE employee (
  employee_no INT NOT NULL CONSTRAINT uq_emp_no UNIQUE,
  email VARCHAR(100) NOT NULL CONSTRAINT uq_emp_email UNIQUE,
  name VARCHAR(50)
) REPLICATION = ON;

UPDATE employee SET name = 'Park' WHERE employee_no = 1001;
```

현재 조회 결과가 ON만 표시하면 DBA는 `uq_emp_no`와 `uq_emp_email` 중 어느 키가 로그에 쓰이는지 모른다. 기대 결과는 양 노드에서 같은 활성 제약 이름과 컬럼 순서를 확인할 수 있고 재시작 뒤에도 유지되는 것이다.

### 권고안
PK 우선 이후의 UK 선택 규칙을 규범적으로 정의하고, 활성 RK의 제약 ID·이름·컬럼 순서·선택 세대를 카탈로그에 저장한다. 후보 추가만으로 활성 RK가 즉시 바뀌는지도 명시한다. 백업·복원·unload/load에서 선택 정보를 보존한다.

### 검증 방법
UK 생성 순서와 제약 이름이 다른 테이블을 만들고 source/replica의 활성 RK를 조회한다. 재시작, failover, unload/load, backup/restore 전후 동일한지 확인한다. 활성 키를 제거하는 DDL은 대체 키 전환 로그가 없으면 거부되는지 시험한다.

## [DBA-3Y-03] REPLICATION=OFF는 성능 옵션이 아니라 데이터 생명주기 정책이다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절과 4절의 OFF DML 미복제·불일치 면책, 6절의 VIEW 결과 불일치
- 사실/추론 구분: 문서에서 도출한 추론 — OFF 테이블은 노드별 로컬 데이터가 되지만 보존·초기화·백업 범위가 정의되지 않는다
- 영향 대상: DBA, 백업 담당자, 애플리케이션, 장애 조치 데이터

### 문제
문서는 OFF로 인한 불일치를 책임지지 않는다고 하지만, 운영자가 어떤 테이블에 OFF를 사용해도 되는지 판단할 기준이 없다. failover, failback, standby 재구축, 백업 복원 때 OFF 행을 보존할지 비울지도 없다.

### 왜 중요한가
복제하지 않는 테이블은 장애 조치 뒤 다른 내용을 보게 된다. 캐시라면 다시 만들 수 있지만 작업 큐나 감사 기록이라면 행 누락이 업무 장애가 된다. 옵션을 정하기 전에 데이터의 소유 노드와 복구 목표를 정해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE local_job_queue (
  job_id INT PRIMARY KEY,
  state VARCHAR(20) NOT NULL
) REPLICATION = OFF;
INSERT INTO local_job_queue VALUES (1, 'RUNNING');
```

A가 primary일 때 1번 작업이 있고 failover 후 B에서 2번 작업이 생기면, failback 시 A와 B의 작업 목록이 다르다. 문서는 합칠지, 각 노드에 유지할지, 재가입 시 지울지 말하지 않는다.

### 권고안
OFF를 “노드 로컬 테이블”로 명확히 정의하고 캐시·임시 데이터처럼 재생성 가능한 사례만 권장한다. failover/failback/재가입/백업별 보존 행렬과 정리 스크립트 실행 시점을 제공한다. 중요 테이블에 OFF를 설정할 때 경고 또는 별도 권한을 요구한다.

### 검증 방법
캐시, 작업 큐, 감사 로그 샘플을 OFF로 만든 뒤 A→B failover→A 재가입→A failback을 수행한다. 각 단계의 행을 기록해 문서 정책과 같은지 확인하고, DBA가 문서만으로 데이터 보존 결과를 정확히 예측하는지 운영 훈련을 한다.

## [DBA-3Y-04] 활성 RK와 후보를 조회하고 감사할 수 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절의 `SHOW CREATE TABLE`과 `db_class` 조회 예시, 4-2절의 후보와 활성 RK 설명
- 사실/추론 구분: 확인된 사실 — 조회 예시는 REPLICATION ON/OFF만 보여 주고 실제 RK와 후보 목록은 표시하지 않는다
- 영향 대상: DBA, 모니터링 도구, 변경 승인자, 고객 지원

### 문제
DBA가 볼 수 있는 것은 테이블이 ON인지 OFF인지뿐이다. 활성 RK, 대체 후보, 후보가 된 이유, 마지막 변경 시각을 직접 조회할 방법이 없다. 제약 정의를 보고 엔진 선택 규칙을 추측해야 한다.

### 왜 중요한가
운영 중 DDL 전에 마지막 RK를 제거하지 않는지 확인해야 한다. 실제 키를 모르면 안전한 변경 계획을 세우기 어렵고, 장애가 발생해도 어떤 값으로 replica가 행을 찾았는지 분석할 수 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (
  no INT NOT NULL UNIQUE,
  email VARCHAR(100) NOT NULL UNIQUE
) REPLICATION = ON;

SHOW CREATE TABLE member;
SELECT * FROM db_class WHERE class_name = 'member';
```

원문 형식의 결과에는 ON은 보이지만 활성 RK가 보이지 않는다. 기대 결과는 `uq_member_no` 같은 제약 이름과 `(no)` 컬럼 순서, 다른 후보 목록을 함께 확인하는 것이다.

### 권고안
전용 시스템 뷰 또는 `SHOW REPLICATION KEY OF table`을 제공한다. owner, table, ON/OFF, 활성 RK 제약, 컬럼 순서, 후보 목록, 스키마 세대와 선택 시각을 출력한다. 일반 사용자와 DBA의 조회 권한도 정의한다.

### 검증 방법
PK, 단일 UK, 여러 UK, 복합 UK 테이블을 생성하여 조회 출력이 실제 복제 로그의 키와 일치하는지 확인한다. 후보 추가·삭제와 failover 뒤 값이 갱신되는지 보고, 조회 권한이 없는 계정에는 적절한 오류가 나는지 시험한다.

## [DBA-3Y-05] single·SA·HA와 기본 ON의 조합이 모호하다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 1절의 hb start 이외는 모두 single, 2-1절의 기본 ON, 3절과 9절의 single/SA 사용 가능
- 사실/추론 구분: 확인된 사실 — 모드 용어가 일관되지 않고 RK 없는 기본 ON 테이블은 나중 HA 시작에서 실패한다
- 영향 대상: DBA, 배포 자동화, 개발·운영 환경 이관

### 문제
SA가 single과 같은지 별도 상태인지 명확하지 않다. 옵션 생략 시 ON인데 non-HA 환경에서는 RK 없이 만들 수 있어 오류가 생성 시점이 아니라 HA 도입 시점까지 지연된다. 기존 DB를 HA로 전환하는 DBA가 영향을 사전에 알기 어렵다.

### 왜 중요한가
개발에서는 정상인 DDL이 운영 HA 전환 때 전체 시작을 막을 수 있다. 모드별 허용 규칙이 표로 있어야 스키마 검사 도구와 배포 파이프라인이 같은 판단을 한다.

### 재현 또는 구체적 예제

```sql
-- non-HA 또는 SA에서 옵션 생략
CREATE TABLE import_buffer (line VARCHAR(1000));
-- 나중에 cubrid hb start 수행
```

테이블은 기본 ON이지만 RK가 없어 시작 오류 대상이다. 기대 결과는 생성 시 경고와 사전 점검 명령으로 미리 발견하는 것이다. SA에서 이 SQL이 허용되는지도 명시돼야 한다.

### 권고안
non-HA server, standalone(SA), HA primary/standby를 정의하고 CREATE/ALTER/LOAD/HA 시작 허용 행렬을 제공한다. 기본 ON을 유지한다면 RK 없는 ON 생성 시 지속 경고를 기록하고 `CHECK HA READINESS`로 언제든 찾게 한다.

### 검증 방법
모드 3종 × 옵션 생략/ON/OFF × RK 있음/없음 조합을 실행해 문서 행렬과 비교한다. 개발 DB를 HA로 전환하는 모의 작업에서 DBA가 첫 시작 전에 모든 위반 테이블을 찾는지 확인한다.

## [DBA-3Y-06] CREATE TABLE 예제가 정책 오류와 문법 오류를 섞는다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2-1절 예시 2와 4-1절 예시 10의 컬럼 목록·결과
- 사실/추론 구분: 확인된 사실 — 예시 2에는 마지막 컬럼 뒤 쉼표가 있고 오류 코드는 제시되지 않는다
- 영향 대상: DBA, QA, 문서 독자, 자동화 스크립트 작성자

### 문제
RK 없는 ON 테이블이 HA에서 거부되는 정책을 보여 주려는 예제가 SQL 파서에서 먼저 실패할 수 있다. 그러면 DBA는 RK 정책 오류를 재현하지 못한다. 옵션 위치, 공백 허용, 오류 시 테이블이 생성되지 않는다는 사후 상태도 없다.

### 왜 중요한가
운영 절차에서는 오류 원인을 구분해야 한다. 문법 오류는 SQL 수정으로 해결하지만 정책 오류는 PK/UK 추가 또는 OFF 선택이 필요하다. 둘을 섞으면 잘못된 조치를 안내하게 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE repl_table_without_rk (
  a INT,
) REPLICATION = ON;
```

후행 쉼표가 있으면 HA 규칙 전에 syntax error가 날 수 있다. 올바른 예제는 쉼표를 제거하고 HA에서 “RK 후보 없음” 오류를 내며, `SHOW TABLES`에 객체가 남지 않아야 한다.

### 권고안
모든 SQL을 실제 실행 가능한 형태로 고치고 모드·선행 상태를 적는다. 구문 오류와 정책 오류를 별도 예제로 나누며 오류 코드, 객체명, 해결 방법, 실패 후 롤백 상태를 표시한다.

### 검증 방법
빈 DB에서 문서 코드 블록을 자동 추출해 실행한다. 예제가 정책 검사 단계까지 도달하는지, 예상 오류 코드가 맞는지, 실패한 CREATE가 카탈로그나 replica에 잔여 객체를 남기지 않는지 확인한다.

## [DBA-3Y-07] DROP+ADD 키 교체의 원자성과 잠금 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 하나의 ALTER에서 키 교체
- 사실/추론 구분: 확인이 필요한 질문 — 새 제약 검증 실패와 복제 적용 실패 시 전체 ALTER가 롤백되는지 원문에 없다
- 영향 대상: DBA, 복제 정합성, 운영 중 DDL, 애플리케이션 가용성

### 문제
문서는 같은 ALTER에서 기존 키를 삭제하고 새 키를 추가하면 된다고 안내하지만, 두 동작이 전부 성공하거나 전부 취소되는지 없다. 대형 테이블에서 새 UNIQUE 검증 중 걸리는 잠금과 쓰기 차단 시간도 없다.

### 왜 중요한가
DROP만 반영되고 ADD가 실패하면 ON 테이블이 RK 없이 남을 수 있다. 원자적이어도 수억 행의 중복 검사 동안 쓰기가 오래 멈추면 서비스 장애가 된다. DBA는 실행 창구와 롤백 계획을 정할 정보가 필요하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (
  id INT CONSTRAINT pk_customer PRIMARY KEY,
  email VARCHAR(100)
) REPLICATION = ON;
INSERT INTO customer VALUES (1, 'same@x'), (2, 'same@x');

ALTER TABLE customer
  DROP CONSTRAINT pk_customer,
  ADD CONSTRAINT uq_customer_email UNIQUE (email);
```

email 중복 때문에 ADD는 실패해야 한다. 기대 결과는 DROP도 취소되어 PK/RK가 여전히 id이고 양 노드 스키마가 같은 것이다. 문서는 잠금 대기와 실패 후 상태를 말하지 않는다.

### 권고안
새 후보의 NOT NULL·중복·타입을 먼저 검증하고 전체 ALTER를 원자적으로 커밋한다고 명시한다. 잠금 수준, 온라인 DML 허용 여부, 예상 진행률, 취소·timeout·replica 실패 정책을 제공한다. 대형 테이블에는 사전 검증 명령을 제공한다.

### 검증 방법
중복·NULL·디스크 부족·replica 중단을 각각 주입해 ALTER를 실패시킨다. 매번 source/replica의 제약과 활성 RK가 시작 전 상태인지 확인한다. 대형 테이블에서 동시 INSERT/UPDATE의 대기 시간과 취소 후 복구 시간을 측정한다.

## [DBA-3Y-08] 키 컬럼 변경을 포괄하는 DDL 상태표가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 PK/UK 추가·삭제 일부 예시와 “다른 후보가 있으면 모든 DDL 허용”
- 사실/추론 구분: 확인된 사실 — 타입, 이름, NOT NULL, collation, 복합 키 일부 컬럼 변경은 설명되지 않는다
- 영향 대상: DBA, 스키마 마이그레이션, 복제 정합성

### 문제
실무 변경은 제약 삭제뿐 아니라 컬럼 rename, 타입 확대, `NOT NULL` 제거, collation 변경을 포함한다. 이 변경들이 활성 RK와 후보 자격에 미치는 결과가 없다. 다른 후보가 있다는 이유로 모든 DDL을 허용하면 활성 키 해석이 바뀌는 시점을 놓칠 수 있다.

### 왜 중요한가
복합 UK에서 컬럼 하나만 NULL 가능해져도 문서 기준의 RK 후보가 아니게 된다. 문자열 비교 규칙이 바뀌면 이전에 다른 값이 같은 값이 될 수도 있다. DBA는 실행 전 허용 여부와 전환 후 키를 알아야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE shipment (
  tenant_id INT NOT NULL,
  tracking_no VARCHAR(30) NOT NULL,
  fallback_id INT NOT NULL UNIQUE,
  CONSTRAINT uq_tracking UNIQUE (tenant_id, tracking_no)
) REPLICATION = ON;

ALTER TABLE shipment ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE shipment RENAME COLUMN fallback_id AS legacy_id;
```

어느 UK가 활성인지에 따라 두 DDL의 영향이 다르다. 기대 결과는 허용/거부, 자동 전환 여부, 사후 활성 RK가 명확한 것이다.

### 권고안
PK/UK 추가·삭제뿐 아니라 컬럼 add/drop/rename, 타입·collation·NOT NULL 변경, 복합 키 구성 변경을 활성 RK/비활성 후보/마지막 후보별로 표로 만든다. 각 셀에 잠금, 허용 결과, 오류 코드와 전환 RK를 표시한다.

### 검증 방법
상태표의 각 셀을 자동 DDL 시험으로 구현한다. 단일·복합, 숫자·문자열 키를 포함하고 명령 전후 양 노드의 제약·컬럼·활성 RK를 비교한다. 문서에 없는 조합은 배포 전에 실패 처리한다.

## [DBA-3Y-09] DDL과 DML 동시 실행 시 적용 순서를 예측할 수 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 모든 DDL 복제와 4-2절의 HA 운영 중 RK 변경 허용
- 사실/추론 구분: 확인이 필요한 질문 — DDL 잠금, 선행 트랜잭션 대기, 로그의 RK 세대 기록 여부가 없다
- 영향 대상: DBA, 애플리케이션, 복제 정합성, 장애 대응

### 문제
운영 중 키 전환 DDL과 UPDATE/DELETE가 겹치면 어느 키 정의로 로그를 만들고 적용하는지 없다. DDL이 선행 쓰기 트랜잭션을 기다리는지, replica에서도 같은 순서로 적용되는지 알 수 없다.

### 왜 중요한가
전환 전에 시작한 UPDATE가 전환 후 커밋할 수 있다. replica가 새 키 정의만 알고 옛 키 값을 해석하면 행을 못 찾아 `fail_count`가 증가할 수 있다. 이는 변경안이 막으려는 원래 문제와 같다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE wallet (
  id INT PRIMARY KEY,
  code VARCHAR(20) NOT NULL UNIQUE,
  amount INT
) REPLICATION = ON;

-- 세션 A: 아직 COMMIT하지 않음
UPDATE wallet SET amount = amount + 10 WHERE id = 7;
-- 세션 B
ALTER TABLE wallet DROP PRIMARY KEY,
  ADD CONSTRAINT pk_wallet_code PRIMARY KEY (code);
```

세션 A가 DDL 뒤 커밋할 때 B가 대기할지, A가 실패할지, 스키마 세대로 적용할지 불명확하다. 기대 결과는 양 노드가 같은 커밋 순서와 키 정의를 쓰는 것이다.

### 권고안
RK DDL은 관련 선행 쓰기 종료를 기다리고 후속 DML은 새 세대만 사용하도록 직렬화 규칙을 명시한다. DDL 로그에 이전·새 RK와 스키마 세대를 넣고 replica 적용 순서를 보장한다. 잠금 timeout과 안전한 재시도 여부를 문서화한다.

### 검증 방법
DDL 직전·중·직후 INSERT/UPDATE/DELETE의 시작·커밋 순서를 바꿔 반복한다. 복제 지연과 replica 재시작을 조합하고 최종 데이터, 로그 순서, 활성 RK, `fail_count`, 교착 여부를 확인한다.

## [DBA-3Y-10] HA 시작 검사의 일관성·비용·출력이 정의되지 않는다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절의 HA 실행 시 위반 검사와 “에러와 함께 파일 리스트 출력”
- 사실/추론 구분: 확인된 사실 — 검사 스냅샷, DDL 차단, 모든 위반 출력, 출력 형식과 소요 비용이 없다
- 영향 대상: DBA, 가용성, 자동화, 대규모 데이터베이스

### 문제
검사 도중 다른 세션이 스키마를 바꾸면 통과 직후 위반 상태가 될 수 있다. 첫 오류만 표시하는지 전체 목록을 표시하는지, “파일 리스트”가 테이블 목록인지도 불명확하다. 대량 테이블에서 시작 시간이 얼마나 늘어나는지 기준도 없다.

### 왜 중요한가
HA 시작은 장애 복구 시간에 포함될 수 있다. 1만 테이블을 검사하느라 오래 걸리거나 하나씩 오류를 수정해야 하면 가용성 목표를 지키기 어렵다. 자동화에는 안정적인 종료 코드와 객체별 원인이 필요하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key (v INT) REPLICATION = ON;
CREATE TABLE local_parent (id INT PRIMARY KEY) REPLICATION = OFF;
CREATE TABLE child (
  id INT PRIMARY KEY,
  p INT,
  FOREIGN KEY (p) REFERENCES local_parent(id)
) REPLICATION = ON;
```

위반이 두 개다. HA 시작은 둘 다 한 번에 보고해야 한다. 동시에 정상 테이블의 마지막 UK를 삭제하려는 세션이 있다면 검사와 활성화 사이에 끼어들지 못해야 한다.

### 권고안
HA 시작과 동일한 읽기 전용 readiness 검사 명령을 제공한다. 일관된 카탈로그 스냅샷 또는 전환 잠금으로 검사·활성화를 연결하고 모든 위반의 owner/table/constraint/reason/fix를 구조화해 출력한다. 예상 시간과 진행률, 취소 정책도 명시한다.

### 검증 방법
1만 테이블과 복수 위반을 만들어 검사 시간·CPU·잠금을 측정한다. 검사 중 DDL 경쟁을 발생시켜 통과 후 위반이 생기지 않는지 확인한다. 자동화가 종료 코드와 전체 오류 목록을 정확히 파싱하는지 시험한다.

## [DBA-3Y-11] failover와 failback 절차에 RK 확인 단계가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 6절의 failover 후 VIEW, 7절의 HA 시작; failback·노드 재가입 절차는 없음
- 사실/추론 구분: 확인된 사실 — 역할 전환 전 복제 지연·RK 일치·데이터 일치 확인과 전환 후 검증 절차가 없다
- 영향 대상: DBA, 서비스 가용성, 복제 정합성

### 문제
문서는 HA 시작 조건만 제시하고 실제 failover 전후 무엇을 확인할지 설명하지 않는다. planned switchover와 긴급 failover를 구분하지 않으며, 복구 노드를 재가입하거나 failback할 때 활성 RK와 OFF 데이터 처리도 빠졌다.

### 왜 중요한가
standby에 아직 DDL 또는 DML이 적용되지 않은 상태에서 승격하면 새 primary의 스키마와 데이터가 오래된 상태가 된다. 새 키 전환 중이면 더 위험하다. DBA는 자동 승격 허용 조건과 수동 점검 목록이 필요하다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE account
  ADD CONSTRAINT uq_account_email UNIQUE (email),
  DROP PRIMARY KEY;
UPDATE account SET balance = balance - 100 WHERE id = 10;
```

DDL은 적용됐지만 뒤 UPDATE는 아직 standby에 도착하지 않은 시점에 failover한다고 가정한다. 기대 결과는 로그 적용 위치와 활성 RK 세대가 안전 기준을 만족하지 않으면 planned 전환이 차단되는 것이다.

### 권고안
planned switchover, unplanned failover, failback, 재가입별 runbook을 제공한다. 복제 지연, 미해결 적용 오류, `fail_count`, 스키마/RK 세대, ON 테이블 데이터 샘플을 사전·사후 확인한다. OFF 테이블 보존 정책과 구 노드 fencing 조건도 넣는다.

### 검증 방법
DDL 적용 전·중·후와 DML backlog가 있는 시점마다 장애를 주입한다. 자동/수동 승격이 문서 조건대로 허용 또는 차단되는지 확인하고, 전환 후 양 노드의 RK 세대와 데이터 체크섬을 비교한다.

## [DBA-3Y-12] 복합 UK와 키 값 UPDATE의 적용 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절의 NOT NULL UK 후보 규칙과 4-2절의 키 제약 DDL; 복합 UK 및 키 값 DML 설명 없음
- 사실/추론 구분: 확인이 필요한 질문 — 복합 UK가 후보인지, 키 UPDATE 로그에 old/new 값 중 무엇이 저장되는지 명확하지 않다
- 영향 대상: 복제 정합성, DBA, 애플리케이션, 성능

### 문제
복합 UK의 모든 컬럼이 NOT NULL이어야 하는지 문장만으로 추론해야 하며 컬럼 순서 보존 규칙이 없다. 활성 RK 값 자체를 UPDATE할 때 replica가 이전 값으로 행을 찾는지 새 값으로 찾는지도 없다.

### 왜 중요한가
새 키 값은 replica 행에 아직 존재하지 않으므로 새 값만으로 검색하면 실패할 수 있다. 복합 키는 컬럼 순서가 달라지면 같은 값 묶음이어도 로그 해석이 달라진다. 긴 문자열 키는 로그와 검색 비용도 크게 늘린다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parcel (
  tenant_id INT NOT NULL,
  tracking_no VARCHAR(100) NOT NULL,
  status VARCHAR(20),
  CONSTRAINT uq_parcel UNIQUE (tenant_id, tracking_no)
) REPLICATION = ON;

UPDATE parcel
SET tracking_no = 'NEW-100'
WHERE tenant_id = 1 AND tracking_no = 'OLD-100';
```

기대 결과는 replica가 `(1,'OLD-100')` 행을 찾아 새 값으로 바꾸고 양쪽에 하나의 행만 남는 것이다. 중복되는 새 값이 있으면 전체 트랜잭션이 동일하게 실패해야 한다.

### 권고안
복합 후보 조건, 컬럼 순서, 지원 타입과 최대 크기를 명시한다. 키 UPDATE 로그에 old/new 이미지를 어떻게 담고 적용하는지 설명한다. NULL 또는 중복 충돌 시 source와 replica의 동일한 실패·롤백 조건을 정의한다.

### 검증 방법
2·4·8컬럼 복합 UK에서 일부/전체 키 UPDATE, 두 행의 키 교환, 중복 충돌, 긴 다국어 문자열을 시험한다. 로그 크기와 적용 지연을 측정하고 최종 행, 인덱스, `fail_count`를 비교한다.

## [DBA-3Y-13] FK의 ON/OFF 조합과 연쇄 동작 규칙이 불완전하다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식이 참조하는 부모도 ON이어야 한다는 규칙
- 사실/추론 구분: 확인된 사실 — OFF 자식→ON 부모, 기존 FK가 있는 테이블의 ON/OFF 변경, CASCADE/SET NULL은 설명되지 않는다
- 영향 대상: DBA, 데이터 정합성, 애플리케이션

### 문제
문서는 ON 자식→OFF 부모를 금지하지만 나머지 조합을 다루지 않는다. 부모를 나중에 OFF로 바꾸는 ALTER, OFF 자식이 ON 부모를 참조하는 경우, 연쇄 삭제가 OFF 경계를 넘을 때 결과가 없다.

### 왜 중요한가
FK는 부모 행이 존재해야 자식 행이 유효하다는 규칙이다. 부모가 replica에 없으면 ON 자식 적용이 실패한다. 반대로 로컬 자식은 노드마다 다를 수 있으므로 부모 삭제의 `CASCADE` 결과도 노드마다 달라질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION = ON;
CREATE TABLE local_child (
  id INT PRIMARY KEY,
  parent_id INT,
  FOREIGN KEY (parent_id) REFERENCES parent(id) ON DELETE CASCADE
) REPLICATION = OFF;

DELETE FROM parent WHERE id = 1;
ALTER TABLE parent REPLICATION = OFF;
```

source와 replica의 local_child 행이 다르면 CASCADE 결과도 다르다. ALTER가 기존 관계 때문에 거부되는지도 없다.

### 권고안
부모 ON/OFF × 자식 ON/OFF의 2×2 표를 만들고 CREATE FK, ALTER REPLICATION, DROP FK를 정의한다. CASCADE, SET NULL, RESTRICT별 복제 동작을 적고 위반 ALTER는 전체 롤백하며 관련 제약을 오류에 표시한다.

### 검증 방법
네 조합에서 INSERT/UPDATE/DELETE와 세 referential action을 실행한다. 부모·자식 ON/OFF 변경과 failover를 포함하여 허용 조합은 FK가 유효하고 금지 조합은 카탈로그가 변하지 않는지 확인한다.

## [DBA-3Y-14] OFF 테이블을 포함한 VIEW의 영향 목록을 찾을 수 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 6절의 OFF 테이블 포함 VIEW 결과 불일치와 복제 모듈 면책
- 사실/추론 구분: 확인된 사실 — 위험을 인정하지만 직접·간접 의존 VIEW 조회 및 failover 전 점검 방법은 없다
- 영향 대상: DBA, 애플리케이션, 보고서·보안 조회

### 문제
VIEW 생성은 허용하면서 어떤 VIEW가 OFF 테이블에 의존하는지 찾는 방법을 제공하지 않는다. 중첩 VIEW, 조인, 집계에서 failover 전후 결과가 어떻게 달라질지 운영자가 일일이 SQL을 읽어야 한다.

### 왜 중요한가
애플리케이션이 VIEW만 사용하면 테이블의 OFF 설정을 인식하지 못할 수 있다. 지역 필터, 권한 필터, 매출 합계가 failover 뒤 조용히 달라지면 SQL 오류 없이 잘못된 결과가 제공된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE orders (id INT PRIMARY KEY, region VARCHAR(10)) REPLICATION = ON;
CREATE TABLE local_filter (region VARCHAR(10) PRIMARY KEY) REPLICATION = OFF;
CREATE VIEW visible_orders AS
  SELECT o.* FROM orders o JOIN local_filter f ON f.region = o.region;
CREATE VIEW visible_order_count AS
  SELECT COUNT(*) AS cnt FROM visible_orders;
```

standby의 local_filter가 비어 있으면 두 VIEW 모두 다른 결과를 낸다. 직접 의존성만 보면 두 번째 VIEW의 위험을 놓친다.

### 권고안
OFF 테이블에 직접·간접 의존하는 VIEW 목록과 의존 경로를 조회하는 시스템 뷰를 제공한다. HA readiness와 failover 체크리스트에 이 목록을 포함하고, 중요 VIEW에는 생성 경고나 명시적 승인 옵션을 둔다.

### 검증 방법
직접 VIEW, 3단계 중첩 VIEW, INNER/LEFT/NOT EXISTS 조인과 집계를 만든다. 의존성 조회가 모두 찾는지 확인하고 failover 전후 결과 차이를 보고서가 예상한 대로 표시하는지 검증한다.

## [DBA-3Y-15] `fail_count`를 장애 원인과 연결할 정보가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 1~9절 전체; HA 오류와 데이터 불일치는 다루지만 `fail_count` 정의·조회·초기화는 없음
- 사실/추론 구분: 확인된 사실 — `fail_count` 운영 계약이 원문에 없다
- 영향 대상: DBA, SRE, 고객 지원, 복제 정합성

### 문제
적용 실패가 카운터에 언제 추가되는지, 같은 로그 재시도마다 증가하는지, 재시작 시 초기화되는지 알 수 없다. 카운터만으로는 문제 테이블, 제약, 로그 위치, 첫 발생 시각을 찾을 수 없다.

### 왜 중요한가
10이라는 값이 한 로그의 10회 재시도인지 서로 다른 10행 실패인지에 따라 조치가 다르다. 오류를 복구한 뒤 현재 미해결 건이 0인지도 알아야 failover를 승인할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE inventory (sku INT PRIMARY KEY, qty INT) REPLICATION = ON;
UPDATE inventory SET qty = qty - 1 WHERE sku = 404;
```

replica에서 404 행을 제거하고 같은 적용을 10회 재시도한다고 가정한다. `fail_count`가 1인지 10인지, 재시작 뒤 값이 무엇인지 문서로 판단할 수 없다.

### 권고안
누적 실패 수와 현재 미해결 로그 수를 분리한다. 증가·재시도 중복·보존·초기화 규칙을 정의하고 테이블, 오류 코드, LSA/트랜잭션, RK 세대, 첫/최근 발생 시각을 조회하게 한다. 경보 임계값과 runbook 링크를 제공한다.

### 검증 방법
행 없음, 중복 키, 스키마 불일치, 일시적 잠금 실패를 주입해 재시도·재시작 전후 메트릭을 기록한다. 원인별 오류가 구분되고 복구 뒤 미해결 수가 0이 되는지, failover 체크가 이를 사용하는지 확인한다.

## [DBA-3Y-16] 불일치 교정 중 쓰기와 실패 복구 절차가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4절과 6절의 불일치 가능성 및 면책; 복구 절차 없음
- 사실/추론 구분: 확인된 사실 — 데이터 비교 후 어느 노드를 기준으로 어떤 잠금 아래 교정할지 정의되지 않는다
- 영향 대상: DBA, 복제 정합성, 서비스 가용성

### 문제
불일치를 발견해도 온라인으로 고칠 수 있는지, 쓰기를 멈춰야 하는지, repair DML이 다시 복제되어 중복 적용되지 않는지 모른다. 중간에 실패했을 때 재시작 지점과 감사 기록도 없다.

### 왜 중요한가
비교와 교정 중 데이터가 계속 바뀌면 차이 목록이 즉시 낡는다. 잘못된 노드를 정답으로 선택하면 정상 데이터를 덮어쓸 수 있다. 복구 도구가 멱등적이지 않으면 재실행 때 중복 행을 만들 수 있다.

### 재현 또는 구체적 예제
source에 `(id=1,balance=100)`, replica에 `(id=1,balance=90)`이 있고 애플리케이션이 동시에 입금한다고 가정한다.

```sql
UPDATE account SET balance = balance + 20 WHERE id = 1;
```

교정 도구가 오래된 차이 목록으로 replica를 100으로 덮으면 정상 입금 결과 120을 잃을 수 있다. 기대 결과는 일관된 시점의 비교와 변경 충돌 검출이다.

### 권고안
정답 노드, 일관된 스냅샷, 쓰기 차단 또는 변경 캡처, 교정 DML의 복제 억제 여부를 runbook에 적는다. 작업 ID·진행 위치·변경 전후 값을 감사하고, 재실행 가능한 방식과 중단 후 롤백/재개를 제공한다.

### 검증 방법
교정 중 동시 INSERT/UPDATE/DELETE, 네트워크 단절, 프로세스 중단을 주입한다. 재개 후 행 중복·최신 변경 손실 없이 두 노드가 같아지는지 확인하고 감사 로그로 모든 수정 행을 추적한다.

## [DBA-3Y-17] 구버전 unload 파일의 기본 ON/OFF 정책이 상충한다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 복제 변수가 없으면 ON, 9절 5항은 포함하지 않는 테이블은 OFF라고 서술
- 사실/추론 구분: 확인된 사실 — 동일한 입력의 기본 처리 규칙이 서로 반대다
- 영향 대상: DBA, 데이터 이관, 업그레이드·다운그레이드, HA 시작

### 문제
구버전 unload 파일에 REPLICATION 값이 없을 때 ON과 OFF 중 어느 결과가 맞는지 알 수 없다. ON이면 키 없는 테이블 때문에 HA 시작이 막히고, OFF이면 키 있는 업무 테이블까지 복제되지 않을 수 있다.

### 왜 중요한가
load는 많은 테이블을 한 번에 만든다. 잘못된 기본값은 모든 테이블의 장애 조치 가용성을 바꾸며 작업 후 수동 확인도 어렵다. 자동 기본 처리보다 명시적 이관 정책이 필요하다.

### 재현 또는 구체적 예제

```sql
-- 구버전 파일에 옵션 없이 존재한다고 가정
CREATE TABLE keyed_data (id INT PRIMARY KEY, value VARCHAR(20));
CREATE TABLE heap_data (value VARCHAR(20));
```

8절대로 둘 다 ON이면 heap_data가 HA readiness를 실패시킨다. 9절대로 둘 다 OFF이면 keyed_data도 standby 데이터를 갖지 않는다.

### 권고안
한 정책으로 통일하고 `--default-replication=ON|OFF|ERROR` 같은 명시 옵션을 제공한다. 안전 모드에서는 값이 없을 때 dry-run 보고 후 중단하게 한다. 테이블별 결정, RK 유무, 예상 HA 위반을 load 전에 출력한다.

### 검증 방법
필드 없음/ON/OFF × RK 있음/없음 파일을 load하여 옵션별 결과와 종료 코드를 확인한다. load 후 카탈로그, 활성 RK, readiness 결과가 dry-run 보고서와 같은지 검증한다.

## [DBA-3Y-18] 백업·복원과 혼합 버전 HA의 운영 지원 범위가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 unload/load만 언급; backup/restore, 롤링 업그레이드, 서로 다른 버전 노드는 없음
- 사실/추론 구분: 확인이 필요한 질문 — REPLICATION 및 활성 RK 메타데이터의 backup/restore 보존과 구버전 노드 해석 가능 여부가 확인되지 않았다
- 영향 대상: DBA, 기존 HA 고객, 재해 복구, 릴리스 운영

### 문제
일반 백업·복원에서 ON/OFF와 활성 RK가 보존되는지 없다. 롤링 업그레이드 중 구버전 replica가 새 DDL 로그를 이해하는지, 혼합 상태에서 새 문법을 차단하는지도 정의되지 않는다.

### 왜 중요한가
재해 복구 후 테이블이 기본 ON/OFF로 바뀌면 데이터 보호 수준이 달라진다. 구버전 노드가 새 메타데이터를 무시하면 양 노드의 스키마가 갈라지고 failover가 위험해진다.

### 재현 또는 구체적 예제
노드 A는 신버전, B는 구버전이라고 가정한다.

```sql
CREATE TABLE local_cache (
  cache_key VARCHAR(100) PRIMARY KEY,
  value VARCHAR(1000)
) REPLICATION = OFF;
```

B가 `REPLICATION=OFF`를 이해하지 못하면 DDL 적용 실패 또는 다른 기본값이 가능하다. A의 백업을 복원했을 때도 OFF와 활성 RK가 동일해야 한다.

### 권고안
backup/restore/unload/load별 보존 필드와 버전 호환 표를 제공한다. N/N-1 조합에서 지원하지 않으면 클러스터 capability를 검사해 새 DDL을 선제 거부한다. 롤링 업그레이드·롤백·복원 후 readiness 절차를 문서화한다.

### 검증 방법
N과 N-1의 primary/replica 방향을 바꿔 DDL/DML/failover를 시험한다. ON/OFF와 여러 RK 후보가 있는 DB를 백업·복원하여 카탈로그, 활성 RK, 데이터와 readiness가 원본과 같은지 비교한다.

## [DBA-3Y-19] 오류 예제가 자동화 가능한 코드와 해결 정보를 주지 않는다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2-2절과 4~5절 다수 예시의 `ERROR`/`OK` 표기
- 사실/추론 구분: 확인된 사실 — 구체 오류 코드, SQLSTATE, 객체, 원인, 수정 방법이 대부분 생략된다
- 영향 대상: DBA, 모니터링·배포 자동화, 고객 지원

### 문제
마지막 RK 삭제, HA에서 OFF→ON, OFF 부모 FK 참조가 모두 단순 `ERROR`로 적혀 있다. 자동화는 이 오류가 재시도 가능한지, 사용자 수정이 필요한지, 문법 오류인지 구분할 수 없다.

### 왜 중요한가
운영 스크립트는 안정적인 코드로 성공·중단·재시도를 결정한다. 메시지만 바뀌거나 모든 경우가 같은 코드면 잘못 재시도해 장애를 길게 만들 수 있다. DBA도 어떤 제약을 추가해야 할지 즉시 알 수 없다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE only_key_table DROP PRIMARY KEY;
ALTER TABLE local_table REPLICATION = ON;
```

첫 오류는 마지막 RK 제거, 둘째는 HA 운영 중 OFF→ON 금지다. 둘 다 `ERROR`라면 자동화가 다른 수정 절차를 선택할 수 없다.

### 권고안
상황별 안정된 오류 코드와 메시지 템플릿을 정의한다. owner.table, 현재 RK, 위반 제약, 모드, 가능한 수정 SQL을 포함하고, 트랜잭션 재시도 가능 여부를 문서화한다. 성공도 사후 활성 RK를 조회하는 예제를 붙인다.

### 검증 방법
문서의 모든 실패 예제를 실행해 예상 코드·메시지 필드와 비교한다. locale이 바뀌어도 코드가 유지되고 자동화가 마지막 RK 오류와 모드 오류를 정확히 분기하는지 확인한다.

## [DBA-3Y-20] 오탈자와 불완전한 예제가 운영 runbook 사용을 방해한다

- 분류: 문서 품질
- 심각도: Minor
- 근거 위치: 원문 5-1절 `CRATE TABLE`, 7절 “파일 리스트”·“재시작해아한다”, 예시 7의 말줄임표, 9절 요약의 상충 문구
- 사실/추론 구분: 확인된 사실 — 철자·문장 오류와 실행 불가능한 예제가 있고 “파일 리스트”의 의미는 확인이 필요하다
- 영향 대상: DBA, 입문 독자, 문서·교육·지원 담당자

### 문제
`CRATE TABLE`, 후행 쉼표, 이름 없는 제약, `...` 때문에 SQL을 복사해 점검할 수 없다. “HA 전환”도 최초 HA 시작과 failover를 혼용할 수 있고, “파일 리스트”는 테이블 목록인지 실제 파일인지 불명확하다.

### 왜 중요한가
장애 중 runbook은 빠르게 복사·실행하고 결과를 판단할 수 있어야 한다. 작은 오탈자라도 정책 오류보다 먼저 문법 오류를 만들고, 모호한 용어는 잘못된 시점에 HA를 재시작하게 할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE tbl DROP CONSTRAINT ...,
  ADD CONSTRAINT ...;
```

이 예제로는 실제 제약 이름, 새 컬럼, 예상 RK를 알 수 없다. 장애 중 DBA가 그대로 실행할 수도 없고 자기 환경에 맞게 바꾸는 기준도 없다.

### 권고안
오탈자를 교정하고 HA 시작, planned switchover, unplanned failover, failback을 분리 정의한다. 모든 예제에 초기 스키마, 완전한 SQL, 예상 결과, 실패 후 상태, 원복 SQL을 넣는다. 7절은 위반 “테이블 및 제약 목록”처럼 의도한 대상을 정확히 쓴다.

### 검증 방법
문서 SQL 블록을 CI에서 빈 DB에 실행하고 `...`, 후행 쉼표, 알려진 오탈자를 정적 검사한다. 3년차 DBA가 예제만으로 사전 점검→수정→HA 시작→failover 후 검증을 수행할 수 있는지 모의 훈련한다.

## [DBA-3Y-21] ON/OFF와 RK 변경 권한 및 감사 조회가 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절은 사용자가 복제 정책을 생성·변경한다고만 한다.
- 사실/추론 구분: 확인된 사실 — 필요한 권한, 변경 이력, 실행자 조회 방법이 없다
- 영향 대상: DBA, 보안 관리자, 감사 조직

### 문제
일반 ALTER 권한으로 중요 테이블을 OFF로 바꿀 수 있는지, 누가 RK 후보를 제거했는지 추적할 수 있는지 없다.

### 왜 중요한가
OFF 전환은 schema 모양뿐 아니라 failover 데이터 보호를 바꾼다. 사고 뒤 실행자와 변경 시점을 모르면 원인 분석과 복구 범위를 정하기 어렵다.

### 재현 또는 구체적 예제

```sql
GRANT ALTER ON orders TO deploy_user;
-- deploy_user
ALTER TABLE orders REPLICATION=OFF;
```

허용 여부와 audit event가 미정이다.

### 권고안
CREATE 지정, ON→OFF, OFF→ON, 활성 RK 변경의 권한을 표로 정의한다. actor, old/new 값, constraint, 시각, transaction/LSA를 감사 시스템에서 조회하게 한다.

### 검증 방법
DBA·owner·deploy·read-only 계정으로 각 DDL을 실행하고 허용표와 감사 기록을 대조한다.

## [DBA-3Y-22] 파티션 테이블의 RK와 REPLICATION 상속 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 일반 테이블 설명과 2-3절 `partitioned` 카탈로그 출력
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 해당 파티션 DDL 지원 범위와 새 기능 결합은 확인 필요
- 영향 대상: 대형 테이블 DBA, 복제 정합성

### 문제
부모와 파티션의 ON/OFF를 따로 정할 수 있는지, UK가 각 파티션 안에서만 유일해도 RK인지, 파티션 추가·분할·교환 때 무엇을 검사하는지 없다.

### 왜 중요한가
일부 파티션만 빠지거나 같은 키가 여러 파티션에 존재하면 standby가 한 행을 확정하지 못할 수 있다.

### 재현 또는 구체적 예제
공식 지원 문법으로 월별 sales 파티션을 만든 뒤 다음 metadata를 조회한다고 하자.

```sql
SELECT class_name, partitioned, replication
FROM db_class WHERE class_name='sales';
```

부모 상태만으로 자식 정책과 RK를 알 수 없다.

### 권고안
지원 여부와 부모 정책 상속, 전체 유일성, 파티션 DDL별 허용·잠금·복제 결과를 표로 제공한다. 미지원 조합은 DDL 전에 거부한다.

### 검증 방법
공식 파티션 작업을 후보 0/1/복수와 조합하고 source/replica 전체 행 및 활성 RK를 비교한다.

## [DBA-3Y-23] ON/OFF 테이블 혼합 트랜잭션의 failover 결과가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절·4절의 테이블별 DML 복제 규칙
- 사실/추론 구분: 문서에서 도출한 추론 — 한 transaction의 일부 변경만 standby에 남을 수 있다
- 영향 대상: DBA, 애플리케이션, 복제 정합성

### 문제
한 transaction이 ON과 OFF 테이블을 함께 변경하면 source에서는 원자적이지만 standby에는 ON 부분만 보일 수 있다.

### 왜 중요한가
운영자는 commit 성공을 하나의 업무 단위로 이해한다. failover 뒤 절반만 남으면 주문·감사·작업 상태가 서로 맞지 않는다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO orders(id,status) VALUES (10,'PAID'); -- ON
INSERT INTO local_note(order_id,note) VALUES (10,'done'); -- OFF
COMMIT;
```

새 primary에는 첫 행만 있을 수 있다.

### 권고안
혼합 transaction의 결과를 명시하고 strict HA 환경에서는 commit 경고 또는 거부를 지원한다. 교차 쓰기 목록을 점검하는 SQL/audit 방법을 제공한다.

### 검증 방법
commit·rollback·deadlock·crash를 섞어 두 정책의 테이블을 변경한 뒤 failover 행 집합을 확인한다.

## [DBA-3Y-24] trigger와 자동 생성 DML의 복제 위치가 불명확하다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4~5절은 직접 DML과 FK만 다루며 trigger·내부 DML은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID trigger의 실제 지원 문법과 복제 방식은 확인 필요
- 영향 대상: DBA, trigger 사용자, 데이터 정합성

### 문제
ON 테이블 trigger가 OFF를 쓰거나 그 반대일 때 source 결과를 로그로 보내는지 standby에서 trigger를 다시 실행하는지 없다.

### 왜 중요한가
둘 다 수행하면 중복되고 둘 다 생략하면 누락된다. 장애 조사 때 내부 DML인지 사용자 DML인지도 구분해야 한다.

### 재현 또는 구체적 예제
orders INSERT trigger가 local_audit OFF에 기록한다고 가정한다.

```sql
INSERT INTO orders(id,status) VALUES (11,'NEW');
SELECT COUNT(*) FROM local_audit WHERE order_id=11;
```

failover 후 기대 count가 정의되지 않았다.

### 권고안
trigger, cascade, default/generated 변경의 log 책임과 standby 재실행 억제 규칙을 문서화한다. ON/OFF 경계를 넘는 dependency를 조회하게 한다.

### 검증 방법
ON→ON, ON→OFF, OFF→ON trigger 조합에서 DML 후 실행 횟수·로그·양 노드 데이터를 비교한다.

## [DBA-3Y-25] TRUNCATE와 bulk 명령의 ON/OFF 처리 기준이 없다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 4절의 “모든 DDL 복제, ON 데이터만 복제”
- 사실/추론 구분: 확인이 필요한 질문 — 각 bulk/복사 문법의 현행 지원과 분류는 확인 필요
- 영향 대상: 배치 DBA, 로컬 데이터, 복제 정합성

### 문제
TRUNCATE, bulk load, `INSERT ... SELECT`, 테이블 복사처럼 많은 데이터를 처리하는 명령이 DDL인지 DML인지에 따라 OFF 결과가 달라진다.

### 왜 중요한가
OFF가 node-local이어도 TRUNCATE를 DDL로 복제하면 standby 로컬 데이터까지 삭제될 수 있다. DBA는 작업 전에 결과를 알아야 한다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache;
INSERT INTO archive SELECT * FROM orders;
```

대상 OFF일 때 standby 행 변화가 없다.

### 권고안
지원 명령별 schema/data replication 표와 log volume, transaction/rollback 범위를 제공한다. OFF 대상 bulk 작업에는 사전 경고를 낸다.

### 검증 방법
ON/OFF에서 각 지원 bulk 명령을 실행해 양 노드 행 수, schema, rollback, log 크기를 비교한다.

## [DBA-3Y-26] loaddb 부분 실패의 정리와 재시도 절차가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 8절은 최종 load 정책만 설명하고 중간 실패는 없다.
- 사실/추론 구분: 확인된 사실 — load transaction 단위와 resume/cleanup이 정의되지 않았다
- 영향 대상: 데이터 이관 DBA, 복구 시간

### 문제
일부 테이블 생성 뒤 RK 위반·disk full로 중단되면 앞선 객체를 유지하는지 rollback하는지, 같은 파일을 재실행해도 되는지 없다.

### 왜 중요한가
대용량 load를 처음부터 반복하면 복구 시간이 길고, 잔여 객체가 있으면 재시도 결과도 달라진다.

### 재현 또는 구체적 예제
dump 순서가 a(ON+PK), b(ON+무키), c(OFF)라고 하자.

```sql
SELECT class_name, replication FROM db_class
WHERE class_name IN ('a','b','c');
```

b 실패 뒤 a/c 상태가 불명확하다.

### 권고안
객체/파일/전체 단위 원자성, checkpoint, stop/continue, cleanup, idempotent resume를 정한다. schema dry-run으로 위반을 load 전에 전부 찾는다.

### 검증 방법
create, data, index 단계에 실패를 주입한 뒤 문서 절차로 재개한다. 중복·누락·잘못된 ON/OFF가 없는지 확인한다.

## [DBA-3Y-27] 장기 트랜잭션과 구 RK 로그 보관 한계가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 운영 중 RK 변경을 허용하지만 장기 transaction·log retention은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, 저장 공간, 지연 replica

### 문제
RK 변경 전에 시작해 나중에 commit하는 transaction과 오래 중지된 replica를 위해 구 RK 정의·로그를 언제까지 보존할지 없다.

### 왜 중요한가
너무 빨리 폐기하면 과거 로그를 해석하지 못하고 무기한 보관하면 디스크가 찬다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE account SET balance=80 WHERE id=10;
-- 다른 session이 RK를 email로 교체한 6시간 뒤
COMMIT;
```

DR replica도 하루 정지됐다고 하면 보관 조건이 더 길어진다.

### 권고안
지원 최대 transaction/lag, RK epoch·log retention, 경고 임계값과 replica re-seed 조건을 정의한다. RK DDL precheck에 long transaction과 lag를 넣는다.

### 검증 방법
장기 transaction과 replica 정지를 조합해 경계 전후 replay, 경고, disk 사용량과 재가입 동작을 확인한다.

## [DBA-3Y-28] 정상 복제를 판단할 lag·마지막 성공·RK 세대 지표가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절은 ON/OFF 조회만 하고 원문 전체는 정상 apply 관측 항목이 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, SRE, failover 승인

### 문제
`fail_count=0`이어도 apply가 멈춰 새 실패가 발생하지 않는 상태일 수 있다. 현재 적용 위치와 RK 세대 일치를 볼 수 없다.

### 왜 중요한가
승격 전에 standby가 최신이고 같은 schema인지 확인해야 한다. ON 설정만으로는 실제 보호 여부를 판단할 수 없다.

### 재현 또는 구체적 예제

```sql
INSERT INTO ha_probe(id,created_at) VALUES (1001,CURRENT_DATETIME);
```

standby 반영 지연의 허용 기준과 조회 방법이 없다.

### 권고안
node/database/table별 send/apply LSA, seconds/bytes lag, last success, active RK epoch, promotability를 제공하고 기본 경보를 정한다.

### 검증 방법
정상·apply stop·network 단절·회복을 순서대로 만들고 metric·alert·승격 차단 상태가 실제와 같은지 확인한다.

## [DBA-3Y-29] split-brain 뒤 이전 primary 재가입을 안전하게 처리할 절차가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4~7절은 단일 primary/standby와 failover만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, HA manager, 데이터 정합성

### 문제
network partition으로 양 노드가 쓰기를 받으면 같은 RK에 다른 값이 생긴다. 재연결 때 자동 로그 apply를 계속할지 재-seed할지 없다.

### 왜 중요한가
RK는 충돌 해결 규칙이 아니다. 임의 병합은 잔액·재고를 잘못 만들 수 있다.

### 재현 또는 구체적 예제

```sql
-- node A
UPDATE account SET balance=900 WHERE id=10;
-- node B
UPDATE account SET balance=800 WHERE id=10;
```

둘 중 권위 값은 업무 판단 없이는 정할 수 없다.

### 권고안
fencing, stale writer 차단, divergence 검사, 권위 노드 선택, old primary 폐기·re-seed runbook을 제공한다. 자동 병합을 금지한다.

### 검증 방법
network/fencing 장애를 주입해 단일 writer 유지 여부를 검사한다. 분기 발생 시 자동 재가입이 차단되고 명확한 복구 경로가 제공되는지 확인한다.

## [DBA-3Y-30] RK 오류 진단에 개인정보가 노출될 수 있다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문은 오류 상세와 RK 값의 출력·권한·보존 규칙을 제공하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 개인정보 담당자, 로그 시스템

### 문제
email·전화번호 UK가 RK이면 행 미발견 로그에 원문 값이 들어갈 수 있다. 중앙 로그와 support bundle에 불필요하게 복사될 위험이 있다.

### 왜 중요한가
DBA 진단에는 사건 연결 정보가 필요하지만 개인정보 원문 전체가 항상 필요한 것은 아니다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET state='A' WHERE email='person@example.com';
```

apply 실패 로그의 email 노출 여부가 없다.

### 권고안
일반 로그에는 constraint와 keyed hash를 쓰고 원문 조회는 DBA 권한·감사·짧은 보존 기간으로 제한한다.

### 검증 방법
민감 RK 실패를 만들고 log, dashboard, support bundle을 역할별로 검사해 원문 노출과 진단 가능성을 확인한다.

## [DBA-3Y-31] 인덱스 재구축·제약 이름 변경·통계 갱신의 RK 영향이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 제약 DROP과 일부 index DROP만 다루고 유지보수 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 지원하는 rebuild/rename/statistics 문법과 RK 결합은 확인 필요
- 영향 대상: DBA 정기 유지보수, optimizer, 복제 정합성

### 문제
활성 RK의 backing index를 rebuild하거나 제약 이름을 바꾸고 통계를 갱신할 때 RK identity·선택 순서가 바뀌는지 없다.

### 왜 중요한가
정기 유지보수만으로 RK가 재선택되면 과거 로그와 달라질 수 있다. 통계 변경이 RK 선택에 영향을 줘서도 안 된다.

### 재현 또는 구체적 예제
지원 문법으로 `uq_email`을 rebuild/rename한 뒤 다음을 비교한다고 하자.

```sql
SHOW CREATE TABLE member;
SELECT * FROM db_class WHERE class_name='member';
```

활성 RK logical identity가 유지되는지 알 수 없다.

### 권고안
물리 index와 logical RK identity를 분리하고 rebuild·rename·statistics별 불변식을 명시한다. 필요한 경우 log drain·lock 요구를 제공한다.

### 검증 방법
각 지원 유지보수 작업 전후·재시작 후 활성 RK, DML 로그 해석, query plan과 checksum을 비교한다.

## [DBA-3Y-32] 테이블 clone·rename 경로에서 ON/OFF와 RK 복사 규칙이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 2절은 일반 CREATE/ALTER만 다루며 테이블 복사·rename 경로는 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID가 지원하는 정확한 clone/LIKE/CTAS 문법은 확인 필요
- 영향 대상: DBA, schema migration, 자동화 도구

### 문제
OFF 테이블 구조를 복사할 때 정책을 상속하는지 기본 ON인지, rename 시 선택 RK의 identity가 유지되는지 없다.

### 왜 중요한가
schema 관리 도구가 clone 경로를 사용하면 의도하지 않은 ON은 HA 시작 실패, 의도하지 않은 OFF는 데이터 미복제를 만든다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE local_cache RENAME TO local_cache_old;
SHOW CREATE TABLE local_cache_old;
```

rename 뒤 OFF와 RK metadata 보존 여부가 없다.

### 권고안
지원 생성·복사·rename·schema 이동별 정책 상속, logical RK identity, DDL 복제 결과를 표로 정한다. 모호한 복사에는 명시 ON/OFF를 요구한다.

### 검증 방법
ON/OFF와 복수 UK 테이블에 모든 지원 clone/rename 경로를 실행하고 양 노드 metadata와 데이터를 비교한다.

## [DBA-3Y-33] HA 시작 위반의 차단 범위가 명확하지 않다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절·7절은 위반 시 HA 실행 불가라고만 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 다중 DB DBA, 서비스 가용성

### 문제
한 DB의 무키 ON 테이블이 해당 DB만, 한 node만, 전체 HA group까지 막는지 없다. 부분 기동 뒤 정리 상태도 알 수 없다.

### 왜 중요한가
개발용 DB 하나가 무관한 운영 DB의 HA를 막으면 장애 범위가 예상보다 커진다. 반대로 부분 시작은 보호 상태 오인을 만든다.

### 재현 또는 구체적 예제
같은 운영 단위의 `prod`는 정상이고 `sandbox`에 다음 위반만 있다고 하자.

```sql
CREATE TABLE scratch (v INT) REPLICATION=ON;
```

`cubrid hb start`의 영향 범위가 없다.

### 권고안
검사와 차단 단위를 database/node/group별로 정의하고 부분 시작 허용 여부, 명령 종료 코드, cleanup 절차를 제공한다.

### 검증 방법
다중 DB 중 하나만 위반시켜 시작하고 실제 process, DB service, heartbeat 상태를 문서와 대조한다.

## [DBA-3Y-34] OFF 테이블의 노드별 로컬 쓰기 충돌을 정리할 기준이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 OFF 데이터 불일치를 허용하지만 각 노드 쓰기·재가입을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, failover/failback, 데이터 생명주기

### 문제
standby의 OFF 테이블에 직접 쓸 수 있는지, 역할 전환 뒤 양 노드에 같은 PK의 다른 값이 있으면 무엇을 보존하는지 없다.

### 왜 중요한가
자동 병합은 권위 값을 알 수 없고 단순 보존은 역할마다 결과가 바뀌게 한다.

### 재현 또는 구체적 예제

```sql
-- node A
INSERT INTO local_cache VALUES (1,'A');
-- node B
INSERT INTO local_cache VALUES (1,'B');
```

failback 또는 OFF→ON 준비 때 충돌 해결 규칙이 필요하다.

### 권고안
OFF를 node-local로 정의하고 standby write 허용, 승격 시 초기화/보존, 재가입 시 폐기, ON 복귀 전 권위 snapshot 선택을 runbook으로 제공한다.

### 검증 방법
양 노드에 충돌 데이터를 만든 뒤 failover·failback·재가입을 수행하고 조용한 병합 없이 정한 수명주기로 처리되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 14개
- 최종 리뷰 항목 수: 34개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID 파티션·trigger·bulk·clone·index 유지보수 문법별 실제 지원 범위, standby에서 OFF 테이블 직접 쓰기 가능 여부, log/RK 세대 보관의 현행 한계
