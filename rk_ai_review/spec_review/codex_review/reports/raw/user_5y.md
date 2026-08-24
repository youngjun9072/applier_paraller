# 최종 사용자 / 5년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: CUBRID를 여러 해 사용하며 배포·장애 조치·성능 문제를 경험한 사용자가 새 기능을 예측 가능하게 사용하고, 실무 마이그레이션과 오류 복구를 수행할 수 있는지 검토했다.
- 확인하지 못한 전제: 실제 CUBRID 버전의 SQL 문법, 오류 코드, RK 조회 인터페이스, `fail_count`의 노출·초기화 규칙, 복제 로그 내부 형식과 혼합 버전 지원 범위는 원문만으로 확인하지 못했다.

## 컨셉·문제 정의·대안 (3개)

## [사용자-5년차-01] RK 도입이 기존 데이터 누락을 자동 복구하는 것처럼 오해될 수 있다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절은 RK가 없는 ON 테이블로 HA를 실행할 수 없다고 하고 4절은 운영 중 키 변경을 제한하지만, 도입 전 불일치 데이터는 설명하지 않는다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 기존 사용자, 데이터 정합성, 장애 조치

### 문제
문서는 앞으로 RK가 항상 있도록 만드는 정책만 설명한다. 기존 PK 변경 때문에 이미 standby에 누락되거나 잘못된 값이 있을 때 새 버전 설치 또는 UK 추가가 그 데이터를 고치는지는 명시하지 않는다.

### 왜 중요한가
스키마가 안전해진 것과 데이터가 다시 같아진 것은 별개다. 사용자는 HA 시작 검사가 성공하면 데이터까지 정상이라고 믿고 failover할 수 있지만, 과거 누락은 그대로 남아 있을 수 있다.

### 재현 또는 구체적 예제
source와 standby의 `id=10` 잔액이 각각 900과 1000으로 이미 다른 상태라고 가정한다.

```sql
ALTER TABLE account ADD CONSTRAINT uk_account_email UNIQUE(email);
SELECT id, balance FROM account WHERE id=10;
```

새 RK 후보 추가는 성공해도 잔액 차이는 자동으로 해소된다는 규정이 없다. 기대 결과는 업그레이드 전후 데이터 검증과 재동기화가 별도 작업임을 분명히 알리는 것이다.

### 권고안
기능 목적을 “향후 위험한 RK 변경 방지”로 한정하고 기존 불일치 자동 수리 여부를 명시한다. 업그레이드 절차에 source/standby checksum 비교와 불일치 발견 시 재동기화 단계를 넣는다.

### 검증 방법
업그레이드 전 시험 클러스터에 행 누락과 값 차이를 만들고 새 기능을 활성화한다. 검사 도구가 차이를 알리는지, 단순 HA 시작은 차이를 고치지 않는다는 문서 설명과 실제가 일치하는지 확인한다.

## [사용자-5년차-02] 모든 컬럼 방식 대신 RK만 허용한 사용자 선택의 비용이 설명되지 않았다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 1절·2절은 ON 테이블에 PK 또는 NOT NULL UK를 요구하고 키 없는 테이블은 HA에서 금지한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 키 없는 기존 테이블 사용자, 성능, 데이터 모델

### 문제
키가 없는 테이블에서 모든 컬럼으로 행을 찾는 대안과 비교한 이유, 성능 차이, 중복 행 문제, 사용자가 선택할 수 있는 마이그레이션 방법이 없다.

### 왜 중요한가
감사 로그나 원시 수집 테이블은 중복을 허용해 의도적으로 PK가 없을 수 있다. 이런 사용자는 HA를 포기할지, 임의 ID를 넣을지 결정해야 하며 각 선택은 저장 공간과 애플리케이션에 영향을 준다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE raw_log (
  event_time DATETIME,
  host VARCHAR(100),
  message VARCHAR(4000)
) REPLICATION=ON;
```

single에서는 생성되지만 HA 전환은 실패한다. 기대 가이드는 `log_id BIGINT AUTO_INCREMENT PRIMARY KEY` 같은 대체 키 추가 또는 명시적 OFF 전환과 그 결과를 비교하는 것이다.

### 권고안
모든 컬럼 비교를 채택하지 않은 이유를 긴 값 비교 비용, NULL, 완전 중복 행으로 설명한다. 테이블 유형별로 surrogate PK 추가, 자연 UK 사용, OFF 전환의 장단점과 샘플 마이그레이션을 제공한다.

### 검증 방법
동일 데이터를 키 없음, 정수 PK, 긴 복합 UK 세 구조로 시험해 저장 공간·DML 처리량·복제 지연을 비교한다. 문서의 선택 가이드가 실제 측정 결과와 일치하는지 확인한다.

## [사용자-5년차-03] OFF는 사용 편의 기능이 아니라 failover 데이터 손실 선택임을 더 강하게 알려야 한다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 OFF 데이터가 복제되지 않아 불일치할 수 있고 책임지지 않는다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 애플리케이션, failover

### 문제
OFF를 키가 없는 테이블을 쉽게 허용하는 옵션처럼 소개하지만, failover 시 데이터가 사라지거나 과거 값으로 보이는 실질적 영향은 충분히 강조하지 않는다. “책임지지 않는다”는 문구만으로 안전한 사용 범위를 알 수 없다.

### 왜 중요한가
테이블 구조가 standby에도 있으므로 사용자는 보호되는 것으로 착각할 수 있다. 오류 대신 빈 결과가 나오면 장애를 늦게 발견한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE feature_flag (
  name VARCHAR(100) PRIMARY KEY,
  enabled INT
) REPLICATION=OFF;
INSERT INTO feature_flag VALUES ('new_checkout',1);
-- failover 후
SELECT enabled FROM feature_flag WHERE name='new_checkout';
```

새 primary에 행이 없으면 서비스 동작이 바뀐다. 기대 문서는 이러한 테이블을 캐시·재생성 가능한 데이터로만 제한하도록 경고해야 한다.

### 권고안
OFF 사용 시 확인 경고, 영향받는 VIEW/FK 목록, failover 재구축 절차를 제시한다. 주문·계정·권한처럼 영속성이 필요한 데이터에는 OFF를 사용하지 말라는 명확한 지침을 넣는다.

### 검증 방법
OFF 테이블을 포함한 시험 서비스를 failover하고 사용자 기능 변화를 기록한다. 문서의 재구축 절차로 정상 상태가 복원되며 데이터 손실 경고가 관리 도구에 표시되는지 확인한다.

## 용어·기본값·사용자 계약 (2개)

## [사용자-5년차-04] 후보 키와 현재 RK를 구분해 보여 주지 않는다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 1절은 PK와 여러 UK 중 하나를 선택한다고 하지만 2-3절 조회 예제는 ON/OFF만 출력한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 배포 담당자, 성능 분석

### 문제
`SHOW CREATE TABLE`로 UK 후보는 볼 수 있어도 실제 RK가 어느 제약인지 알 수 없다. 사용자는 변경 전에 어떤 제약이 보호 대상인지, 복제 로그가 얼마나 큰 키를 쓰는지 예측할 수 없다.

### 왜 중요한가
여러 UK 중 하나를 삭제했을 때 다른 후보가 있으니 성공할 것으로 생각할 수 있지만 삭제 대상이 현재 RK라면 전환 과정의 동작이 중요하다. 숙련 사용자도 조회 수단 없이는 추측만 하게 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE contact (
  email VARCHAR(320) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL UNIQUE,
  display_name VARCHAR(100)
) REPLICATION=ON;
SHOW CREATE TABLE contact;
```

출력에는 두 UK와 ON만 있고 선택된 RK는 드러나지 않는다. 기대 결과는 현재 RK와 후보를 구별해 표시하는 것이다.

### 권고안
`SHOW REPLICATION KEY contact` 또는 안정된 카탈로그 열을 제공한다. 제약 이름, 순서 있는 컬럼, 선택 이유, 마지막 변경 시각을 함께 보여 주고 권한 요구 사항을 문서화한다.

### 검증 방법
PK, 단일 UK, 복수 UK, 복합 UK 테이블을 생성한다. 조회 결과가 선택 규칙과 일치하고 재시작·복원 후에도 동일한지 확인한다.

## [사용자-5년차-05] 기본 ON이 실무 배포에서 뒤늦은 HA 기동 실패를 만든다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 옵션 생략 시 ON이고 무키 테이블은 single에서 생성 가능하나 7절의 HA 전환 검사에서 실패한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 기존 사용자, 배포 자동화, 가용성

### 문제
평상시 single/SA 테스트에서는 키 없는 CREATE가 성공하고 실제 HA 환경 전환 때만 실패할 수 있다. 기본 ON과 지연된 검증의 조합이 배포 단계마다 다른 결과를 만든다.

### 왜 중요한가
개발·시험 환경은 single이고 운영만 HA인 경우가 흔하다. 운영 배포나 재해 복구 중 처음 오류를 보면 수정 시간이 길고 가동 목표를 놓친다.

### 재현 또는 구체적 예제

```sql
-- 개발 환경에서 성공
CREATE TABLE import_stage (line_no INT, raw VARCHAR(4000));
-- 운영 DB 복원 후 cubrid hb start
```

암묵적 ON이므로 RK 부재로 전체 기동이 막힐 수 있다. 생성 시점 경고나 CI용 검사 명령이 필요하다.

### 권고안
HA 사용 예정 DB에서는 무키 ON 생성 시 경고 또는 strict 모드를 지원한다. 배포 전 모든 위반 테이블과 수정 SQL을 출력하는 검증 명령을 제공한다.

### 검증 방법
single CI에서 스키마를 적용하고 strict 검사 결과가 운영 HA 시작 결과와 동일한지 비교한다. 명시적 OFF 또는 PK 추가 후 두 환경 모두 통과하는지 확인한다.

## SQL 문법과 상태 전이 (3개)

## [사용자-5년차-06] 여러 UK 중 자동 선택 규칙이 재현 가능하지 않다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절은 여러 UK가 있으면 엔진이 하나를 선택하며 선언이 빠른 순서 등을 예로 든다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 성능, 백업·복원

### 문제
“예”로 제시한 선언 순서는 확정 규칙이 아니며, dump 도구가 제약 순서를 바꾸거나 업그레이드 후 엔진 규칙이 달라질 때 선택이 유지되는지 없다.

### 왜 중요한가
서로 다른 RK는 같은 데이터라도 로그 크기와 UPDATE 처리 비용이 다르다. 복원 후 갑자기 긴 문자열 키가 선택되면 성능이 떨어지고 운영자가 원인을 찾기 어렵다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE product (
  short_id BIGINT NOT NULL UNIQUE,
  global_name VARCHAR(500) NOT NULL UNIQUE,
  price INT
) REPLICATION=ON;
```

기대는 짧은 `short_id`지만 문서는 선택을 보장하지 않는다. unload/load 후 제약 순서가 바뀌면 선택도 바뀔 수 있다.

### 권고안
완전한 결정 규칙을 명시하고 가능하면 사용자가 `REPLICATION KEY`를 지정하게 한다. 자동 선택 결과가 바뀌려 할 때 경고와 사전 비용 추정치를 제공한다.

### 검증 방법
제약 선언 순서·이름을 바꾸고 unload/load와 업그레이드를 수행한다. 실제 RK, 로그 크기, 복제 지연이 예측한 결과와 일치하는지 확인한다.

## [사용자-5년차-07] 한 ALTER에서 키 교체 실패 시 원래 상태 보장이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13은 한 ALTER에서 DROP과 ADD를 함께 수행하면 된다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 스키마 마이그레이션, 복제 정합성

### 문제
새 키 생성이 중복 값이나 자원 부족으로 실패하면 기존 키 삭제까지 취소되는지 명시하지 않는다. 성공/실패가 원자적이지 않으면 테이블이 RK 없는 중간 상태로 남을 수 있다.

### 왜 중요한가
실무 데이터에는 예상하지 못한 중복이 자주 있다. 마이그레이션이 실패해도 원래 서비스가 계속되어야 하며, 사용자는 rollback 결과를 믿을 수 있어야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE coupon (id INT PRIMARY KEY, code VARCHAR(30)) REPLICATION=ON;
INSERT INTO coupon VALUES (1,'A'),(2,'A');
ALTER TABLE coupon DROP PRIMARY KEY,
  ADD CONSTRAINT uk_coupon_code UNIQUE(code);
```

ADD는 중복으로 실패해야 한다. 기대 결과는 전체 ALTER가 취소되고 기존 PK와 RK가 유지되는 것이다.

### 권고안
복합 ALTER는 전체 성공 또는 전체 실패임을 규정하고 새 키 사전 검사 방법을 안내한다. 실패 후 `SHOW`로 원래 PK/RK를 확인하는 예제와 오류 코드를 추가한다.

### 검증 방법
중복, NULL, 디스크 부족, 잠금 타임아웃을 각각 유발한다. 매번 데이터·PK·RK가 변경 전과 완전히 같은지 확인한다.

## [사용자-5년차-08] 복합 키의 부분 변경과 NULL·타입 전환 규칙이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 단일 PK/UK의 추가·삭제 예시만 있고 복합 키, 컬럼 이름·타입·NULL 가능 여부 변경은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 마이그레이션 도구, 복제 정합성

### 문제
복합 UK의 한 컬럼을 nullable로 바꾸거나 이름·타입을 바꾸면 RK 후보 자격 또는 비교 의미가 달라진다. 다른 후보가 있을 때 어떤 순서로 전환되는지도 알 수 없다.

### 왜 중요한가
복합 키는 모든 구성 컬럼을 합쳐 한 행을 구별한다. 한 컬럼의 조건만 바뀌어도 전체 식별 규칙이 변하므로 일반 컬럼 변경처럼 다뤄서는 안 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE stock (
  warehouse_id INT NOT NULL,
  sku VARCHAR(30) NOT NULL,
  qty INT,
  UNIQUE(warehouse_id, sku)
) REPLICATION=ON;
ALTER TABLE stock ALTER COLUMN warehouse_id DROP NOT NULL;
ALTER TABLE stock CHANGE sku product_code VARCHAR(100);
```

후보가 하나라면 첫 DDL은 거부될 것으로 예상되지만 문서에 없다. 둘째 DDL의 과거 로그 해석도 불명확하다.

### 권고안
복합 RK의 ADD/DROP/RENAME/type/collation/NOT NULL 변경별 허용 표를 제공한다. 거부 사유와 안전한 다단계 변경 예제를 실제 제약 이름으로 작성한다.

### 검증 방법
각 변경을 후보 1개와 2개 상태에서 실행한다. 성공 시 DML 복제 결과가 일치하고 실패 시 스키마가 전혀 바뀌지 않는지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [사용자-5년차-09] 무중단 배포 중 DDL과 애플리케이션 DML의 충돌 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 HA 운영 중 일부 RK DDL을 허용하지만 동시 DML, 잠금, 대기 시간을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 애플리케이션, 복제 정합성

### 문제
트래픽이 계속되는 동안 RK를 바꾸면 기존 키를 사용하는 UPDATE와 새 키 인덱스 구축이 겹친다. DDL이 대기하는지, DML이 실패하는지, 어느 순서로 로그가 생성되는지 없다.

### 왜 중요한가
숙련 사용자는 무중단 배포를 시도한다. 동시성 계약이 없으면 테스트에서는 성공해도 운영 부하에서 잠금 장애나 복제 누락이 생길 수 있다.

### 재현 또는 구체적 예제

```sql
-- 세션 A, 미커밋
UPDATE account SET email='new@example.com' WHERE id=10;
-- 세션 B
ALTER TABLE account DROP PRIMARY KEY,
  ADD CONSTRAINT uk_account_email UNIQUE(email);
```

기대 동작은 B가 A를 기다리거나 명확한 타임아웃으로 실패하고, source와 standby의 커밋 순서가 같은 것이다.

### 권고안
RK DDL의 잠금 범위, DML 대기 여부, 타임아웃, 재시도 가능 오류를 명시한다. 트래픽 중 실행 가능한 온라인 절차와 유지보수 창이 필요한 절차를 나눈다.

### 검증 방법
지속적인 INSERT/UPDATE/DELETE 부하 중 키 교체를 반복한다. 오류율, 잠금 대기, p99 지연, 복제 지연, 양 노드 checksum을 함께 측정한다.

## [사용자-5년차-10] RK 변경 도중 failover 결과가 예측 불가능하다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절은 운영 중 RK 변경을, 5~7절은 failover와 HA 시작을 다루지만 두 상황의 결합은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 장애 조치, 데이터 정합성

### 문제
새 인덱스 구축, DDL 로그 전송, standby 적용 사이에 장애가 나면 승격 노드가 구 RK와 신 RK 중 무엇을 사용하는지 정의되지 않았다.

### 왜 중요한가
장애는 유지보수 완료를 기다리지 않는다. 절반만 적용된 노드가 승격되면 새 쓰기가 잘못된 키로 기록되고 failback까지 막힐 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY,
  ADD CONSTRAINT pk_orders_external PRIMARY KEY(external_id);
-- 실행 중 source 프로세스 종료 후 자동 failover
```

기대 결과는 변경 전이나 변경 후의 완전한 상태 중 하나로만 승격되는 것이다. 중간 상태면 자동 승격을 막아야 한다.

### 권고안
DDL commit 지점, standby 준비 상태, 승격 전 검사와 미완료 DDL rollback/redo 규칙을 문서화한다. 사용자가 진행률과 failover-safe 여부를 조회할 수 있게 한다.

### 검증 방법
RK 변경의 각 단계에서 장애를 주입해 승격한다. PK/RK/인덱스가 한 세대로 일치하고 정상 DML이 가능하며 데이터 checksum이 같은지 확인한다.

## [사용자-5년차-11] HA 시작 실패가 전체 서비스에 미치는 범위와 수정 흐름이 부족하다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 7절은 위반 시 에러와 파일 리스트를 출력하고 single에서 수정 후 HA를 재시작한다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 운영 자동화, 가동 시간

### 문제
위반 테이블 하나가 전체 DB 또는 클러스터 시작을 막는지, 부분 서비스가 가능한지 없다. “파일 리스트”가 테이블 목록인지도 불명확하고 여러 위반을 한 번에 모두 보여 주는지 알 수 없다.

### 왜 중요한가
사용자는 장애 시간에 빠르게 수정해야 한다. 첫 오류만 반복 노출되거나 정확한 객체·원인이 없으면 재시작을 여러 번 하게 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key_a (v INT) REPLICATION=ON;
CREATE TABLE no_key_b (v INT) REPLICATION=ON;
-- cubrid hb start
```

기대 결과는 `owner.table`, RK 없음, 가능한 수정 SQL을 두 테이블 모두에 대해 한 번에 출력하는 것이다.

### 권고안
검사 범위와 실패 단위를 명시하고 전체 위반을 구조화된 형식으로 출력한다. dry-run 검사, 수정, 재검사, HA 시작 순서와 예상 소요 시간을 안내한다.

### 검증 방법
RK·FK 위반을 여러 개 섞어 만든다. 한 번의 사전 검사로 모두 발견하고 안내 SQL 적용 후 추가 오류 없이 HA가 시작되는지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [사용자-5년차-12] RK 값 UPDATE의 이전 값·새 값 처리 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 RK 제약 DDL만 다루고 RK 컬럼 자체의 UPDATE는 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 복제 정합성, 애플리케이션

### 문제
UK가 RK인 테이블에서 그 UK 값을 바꾸면 standby의 행은 아직 이전 값을 가진다. 로그가 이전 값과 새 값을 모두 담는지, 재시도 시 어떤 값을 검색하는지 없다.

### 왜 중요한가
새 값만으로 검색하면 standby에서 행을 찾지 못한다. 이전 값으로 찾고 새 값의 유일성을 확인해야 하며, 중간 재시작 후 같은 로그를 다시 처리해도 안전해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (email VARCHAR(320) NOT NULL UNIQUE, name VARCHAR(100)) REPLICATION=ON;
INSERT INTO member VALUES ('old@example.com','Kim');
UPDATE member SET email='new@example.com' WHERE email='old@example.com';
```

기대 결과는 정확한 한 행이 변경되고 적용 재시도에도 중복이나 `fail_count` 증가가 없는 것이다.

### 권고안
RK 값 UPDATE 로그에 이전·새 키를 포함하고 대상 0행·복수 행·새 키 충돌의 오류 정책을 명시한다. 단일·복합 RK 변경 예제를 추가한다.

### 검증 방법
RK를 연속 변경하고 각 로그 적용 직전 프로세스를 재시작한다. 최종 값, 행 수, 오류와 `fail_count`가 source와 standby에서 일치하는지 확인한다.

## [사용자-5년차-13] FK의 ON/OFF 조합과 연쇄 동작이 완전하지 않다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절은 ON 자식이 OFF 부모를 참조하는 경우를 금지하지만 반대 방향, 다단계 참조, CASCADE는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 참조 무결성, failover

### 문제
부모 ON·자식 OFF, 부모 OFF·자식 OFF 조합과 `ON DELETE CASCADE`, `ON UPDATE`, `SET NULL`의 복제 결과가 정의되지 않았다. ALTER로 기존 테이블을 OFF로 바꿀 때 의존 FK 검사도 예제로 보이지 않는다.

### 왜 중요한가
연쇄 옵션은 한 SQL이 관련 테이블을 자동 수정한다. 부모와 자식의 복제 정책이 다르면 standby에는 일부 변경만 도착해 FK 오류나 고아 행이 생길 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE child (id INT PRIMARY KEY, parent_id INT,
  FOREIGN KEY(parent_id) REFERENCES parent(id) ON DELETE CASCADE) REPLICATION=OFF;
DELETE FROM parent WHERE id=1;
```

source의 child는 자동 삭제될 수 있지만 standby의 로컬 child 처리와 부모 DELETE 적용 결과는 불명확하다.

### 권고안
부모/자식 ON/OFF 네 조합과 연쇄 옵션별 허용 표를 제공한다. CREATE·ALTER·HA 시작에서 같은 검사를 수행하고 위험한 조합은 원자적으로 거부한다.

### 검증 방법
각 조합에서 부모 UPDATE/DELETE와 failover를 수행한다. FK 검사, 데이터 결과, 적용 오류가 문서 표와 일치하는지 확인한다.

## [사용자-5년차-14] OFF 의존 VIEW는 정상 실행되어 더 위험할 수 있다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절은 failover 후 VIEW 사용에 제약이 없지만 OFF 데이터로 결과가 다를 수 있다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 보고서, 의사결정

### 문제
“제약이 없다”는 표현은 기능이 안전하다는 인상을 준다. 실제로는 오류 없이 빈 결과나 잘못된 합계를 반환할 수 있으며 중첩 VIEW의 간접 의존성은 언급되지 않는다.

### 왜 중요한가
명시적 오류는 알아차릴 수 있지만 정상 형식의 잘못된 결과는 알아차리기 어렵다. 대시보드·정산·권한 판정에 쓰이면 영향이 커진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE sales (id INT PRIMARY KEY, amount INT) REPLICATION=ON;
CREATE TABLE local_rate (id INT PRIMARY KEY, rate NUMERIC(8,4)) REPLICATION=OFF;
CREATE VIEW converted_sales AS
 SELECT s.id, s.amount*r.rate total FROM sales s JOIN local_rate r ON r.id=1;
```

failover 후 rate 행이 없으면 뷰가 0행을 반환할 수 있다. 기대 결과는 생성·승격 전에 영향 경고를 받는 것이다.

### 권고안
직접·간접 OFF 의존 VIEW 목록 조회를 제공하고 생성 시 경고한다. 중요한 VIEW에는 failover 차단 또는 데이터 재구축 hook을 설정할 수 있게 한다.

### 검증 방법
중첩 VIEW를 만들고 기반 테이블 ON/OFF를 변경한다. 의존성 경고가 갱신되며 failover 전후 결과 차이를 점검 도구가 탐지하는지 확인한다.

## 운영·오류·관측 가능성 (2개)

## [사용자-5년차-15] `fail_count`만으로는 장애 원인과 데이터 영향 범위를 알 수 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체는 오류를 주로 `ERROR`로만 보여 주며 `fail_count`의 증가 조건·초기화·상세 조회를 다루지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 모니터링, 장애 대응

### 문제
누적 숫자는 한 로그가 반복 실패한 것인지 여러 행이 각각 실패한 것인지 알려 주지 않는다. 어떤 테이블과 키가 영향을 받았고 다음 로그가 계속 적용됐는지도 알 수 없다.

### 왜 중요한가
같은 카운터 100이라도 한 행 재시도 100회와 서로 다른 100행 누락은 복구 방법이 다르다. 사용자가 카운터만 초기화하면 실제 불일치를 숨길 수 있다.

### 재현 또는 구체적 예제

```sql
UPDATE inventory SET qty=5 WHERE id=100;
UPDATE inventory SET qty=6 WHERE id=101;
```

standby에 `id=100`이 없다고 가정한다. 첫 실패 뒤 둘째 UPDATE가 적용되는지, 재시도마다 count가 증가하는지 알 수 없다.

### 권고안
고유 오류 사건, LSA, 테이블, RK, 최초/최근 시각, 재시도 횟수와 후속 적용 상태를 조회하게 한다. 경보 기준과 “초기화는 복구가 아님”을 명시한다.

### 검증 방법
0행, 복수 행, UK 충돌 오류를 각각 만들고 카운터·이벤트·로그를 대조한다. 재시작 후 정보가 보존되고 실제 repair 후에만 정상으로 표시되는지 확인한다.

## [사용자-5년차-16] 사용자가 수행할 데이터 비교와 복구 절차가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절·6절은 불일치 가능성을 말하지만 7절은 스키마 검사와 single 수정만 설명한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 데이터 정합성, failover 준비

### 문제
행 수, checksum, 차이 행 추출, 권위 노드 결정, 재동기화 절차가 없다. 단순히 키를 고친 뒤 HA를 다시 시작해도 기존 데이터 차이는 남는다.

### 왜 중요한가
failover 직전에 데이터가 같은지 확인할 방법이 없으면 HA가 제공하는 신뢰성을 사용자 스스로 검증할 수 없다. 대형 테이블은 수동 SELECT 비교도 현실적이지 않다.

### 재현 또는 구체적 예제

```sql
SELECT MOD(id,1000) bucket, COUNT(*), SUM(balance)
FROM account GROUP BY MOD(id,1000);
```

양 노드에서 범위별 비교를 시작할 수 있지만 서로 다른 시점의 쓰기를 비교하면 거짓 차이가 난다. 동일 snapshot 기준이 필요하다.

### 권고안
동일 LSA/snapshot에서 범위 checksum을 계산하고 차이 행을 좁히는 공식 도구를 제공한다. 쓰기 처리, 재동기화, 사후 검증, OFF 제외 규칙을 runbook으로 작성한다.

### 검증 방법
행 누락·추가·값 차이를 의도적으로 만들고 도구로 모두 찾는다. 복구 후 같은 snapshot의 checksum이 일치하고 서비스 영향이 문서 범위 안인지 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [사용자-5년차-17] 구버전 load의 기본 처리 상충으로 마이그레이션 결과를 예측할 수 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 복제 필드가 없으면 ON이라고 하고 9절 요약 5는 필드가 없으면 OFF라고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 업그레이드, 백업·복원

### 문제
같은 구버전 unload 파일을 load했을 때 ON과 OFF라는 반대 결과가 규정되어 있다. ON이면 무키 테이블이 HA를 막을 수 있고 OFF이면 업무 데이터가 복제되지 않을 수 있다.

### 왜 중요한가
마이그레이션 기본값은 수많은 테이블에 한 번에 적용된다. 잘못된 선택이 조용히 적용되면 사용자가 모든 테이블을 일일이 점검해야 한다.

### 재현 또는 구체적 예제

```sql
-- REPLICATION 필드가 없는 구버전 unload 정의
CREATE TABLE legacy_event (event_id INT, body VARCHAR(1000));
-- 새 버전 loaddb 후 db_class 조회
```

8절 기대는 ON, 9절 기대는 OFF여서 시험의 정답이 없다.

### 권고안
하나의 정책으로 통일하고 `--default-replication=ON|OFF|ERROR` 같은 명시 옵션을 제공한다. load 전 예상 결과와 무키 ON 테이블 목록을 dry-run으로 출력한다.

### 검증 방법
필드 없는 구버전 파일과 ON/OFF 명시 신버전 파일을 각각 load한다. 옵션별 카탈로그 값, 경고, HA 시작 결과가 명세와 같은지 확인한다.

## [사용자-5년차-18] 롤링 업그레이드와 넓은 RK의 성능 영향이 검증되지 않았다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 1~9절은 새 문법·카탈로그·dump 필드를 제안하지만 혼합 버전과 성능 수용 기준은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자, 가용성, 응답 시간

### 문제
구버전 standby가 새 DDL과 RK 로그를 읽는지, 기능을 언제 활성화할 수 있는지 없다. 복합 문자열 UK가 RK로 선택될 때 source DML과 apply 지연이 얼마나 늘어날지도 없다.

### 왜 중요한가
롤링 업그레이드 중 복제가 멈추면 무중단 목표를 잃는다. 로그 키가 커지면 디스크·네트워크·CPU가 함께 증가해 기존 용량 계획이 깨질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE shipment (
  region VARCHAR(100) NOT NULL,
  partner VARCHAR(200) NOT NULL,
  external_no VARCHAR(500) NOT NULL,
  payload VARCHAR(4000),
  UNIQUE(region,partner,external_no)
) REPLICATION=ON;
```

긴 3열 RK로 초당 1만 UPDATE를 수행할 때 로그 크기와 지연 기준이 없다. 혼합 버전에서 이 로그를 허용할지도 불명확하다.

### 권고안
버전 조합별 지원 행렬과 업그레이드 순서, 새 기능 활성화 시점을 제공한다. RK 폭·컬럼 수별 TPS, p99 지연, 로그 크기, apply lag 수용 기준과 사전 추정 도구를 정의한다.

### 검증 방법
정수 단일 RK와 긴 복합 RK를 같은 부하로 비교하고 혼합 버전 노드에서도 반복한다. 처리량·응답 시간·네트워크·로그·lag가 공개 기준을 충족하는지 확인한다.

## 문서 품질·예제·오탈자 (2개)

## [사용자-5년차-19] 예제의 문법 오류와 `ERROR`만 있는 결과가 원인 학습을 막는다

- 분류: 문서 품질
- 심각도: Minor
- 근거 위치: 원문 2-1절 예시 2와 5절 예시 23의 마지막 쉼표, 5-1절 `CRATE TABLE`, 여러 예제의 단순 `ERROR` 출력.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, 기술지원, 테스트 자동화

### 문제
SQL 문법 오류와 제품이 의도적으로 거부한 오류가 섞인다. 사용자는 어떤 제약 때문에 실패했는지 알 수 없고 예제를 회귀 테스트로 재사용할 수도 없다.

### 왜 중요한가
숙련 사용자도 정확한 오류 코드가 없으면 운영 장애와 문서 예제를 연결하기 어렵다. 잘못된 쉼표는 RK 검사 전에 파서 오류를 발생시킨다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE repl_table_without_rk (
  a INT,
) REPLICATION=ON;
```

문서 의도는 single 성공·HA 오류지만 실제로는 마지막 쉼표 때문에 어느 모드에서나 구문 오류일 수 있다.

### 권고안
모든 SQL을 실제 실행해 교정하고 모드, 초기 상태, 정확한 오류 코드·메시지를 넣는다. `CRATE`를 `CREATE`로 고치고 성공 예제에는 조회 결과도 보여 준다.

### 검증 방법
문서 코드 블록을 CI에서 single/SA/HA 지정 환경에 실행한다. 예상 성공·실패와 코드가 일치하며 의도하지 않은 parser 오류가 없는지 확인한다.

## [사용자-5년차-20] 기능별 설명은 있으나 안전한 전체 마이그레이션 예제가 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~8절은 개별 CREATE/ALTER/FK/load 예제를 제공하지만 기존 운영 DB를 새 정책으로 전환하는 종단간 절차는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 기존 사용자, 배포 담당자, 장애 복구

### 문제
사용자가 어떤 순서로 inventory, 위험 분류, 키 추가, OFF 결정, FK/VIEW 검사, 데이터 비교, HA 재시작을 해야 하는지 없다. 예시 7의 `...`는 실제 제약 이름과 rollback 방법도 보여 주지 않는다.

### 왜 중요한가
개별 SQL이 맞아도 실행 순서가 틀리면 긴 잠금, 기동 실패, 데이터 불일치가 생긴다. 실무 마이그레이션은 사전 점검과 되돌리기가 핵심이다.

### 재현 또는 구체적 예제

```sql
-- 1) 후보 확인
SELECT class_name, replication FROM db_class;
-- 2) 무키 업무 테이블에 PK 추가
ALTER TABLE order_log ADD COLUMN log_id BIGINT;
-- 3) VIEW/FK 영향 확인 후 HA dry-run
```

2단계에서 기존 행 채우기, NOT NULL 전환, PK 생성 순서와 장기 잠금 회피 방법이 원문에는 없다.

### 권고안
소규모·대형 DB 각각의 종단간 runbook을 제공한다. 사전 백업, dry-run, 데이터 채움, 키 생성, FK/VIEW 검사, checksum, HA 시작, failover 연습, rollback 기준을 실제 SQL과 예상 출력으로 설명한다.

### 검증 방법
구버전과 유사한 샘플 DB를 준비하고 신규 사용자가 runbook만 따라 전환한다. 서비스 중단 시간, 실패 시 rollback, 최종 HA·checksum·failover 결과가 수용 기준을 만족하는지 관찰한다.

## [사용자-5년차-21] REPLICATION 정책 변경의 권한·승인·감사 계약이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절은 사용자가 ON/OFF를 생성·변경한다고만 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 숙련 사용자, DBA, 보안·감사 조직

### 문제
일반 ALTER 권한이 있으면 ON→OFF까지 가능한지, 중요 테이블에 별도 승인이 필요한지, 누가 언제 변경했는지 조회하는 방법이 없다.

### 왜 중요한가
OFF 전환은 단순 schema 변경이 아니라 failover 보호 등급을 낮춘다. 변경 이력이 없으면 장애 시점과 영향 DML 범위를 추적하기 어렵다.

### 재현 또는 구체적 예제

```sql
GRANT ALTER ON orders TO deploy_user;
-- deploy_user
ALTER TABLE orders REPLICATION=OFF;
```

성공 여부와 감사 이벤트 형식이 미정이다.

### 권고안
CREATE 지정, ON→OFF, OFF→ON, 활성 RK 변경별 권한을 분리한다. actor, reason, old/new policy, constraint, transaction/LSA를 감사 조회에 제공한다.

### 검증 방법
역할별 DDL을 실행하고 허용표와 audit trail을 대조한다. 감사 레코드만으로 변경 경계 DML을 좁힐 수 있는지 확인한다.

## [사용자-5년차-22] ON/OFF 혼합 트랜잭션은 업무 원자성을 깨뜨릴 수 있다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절·4절은 테이블 단위로 DML 복제 여부를 정한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션 데이터, failover, 사용자

### 문제
한 transaction이 ON과 OFF를 함께 갱신하면 source에서는 모두 commit되지만 standby에는 ON 부분만 나타날 수 있다.

### 왜 중요한가
업무 불변식이 여러 테이블에 걸치면 failover 후 절반 상태가 된다. DB transaction의 원자성이 HA 경계에서 달라진다는 중요한 계약이다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO invoice(id,total) VALUES (10,1000); -- ON
INSERT INTO local_receipt(invoice_id,body) VALUES (10,'ok'); -- OFF
COMMIT;
```

새 primary에는 invoice만 있을 수 있다.

### 권고안
혼합 transaction을 경고·금지할 strict policy와 schema/runtime 탐지 방법을 제공한다. 같은 업무 단위 데이터는 같은 복제 정책을 쓰도록 가이드한다.

### 검증 방법
commit·rollback·deadlock·crash를 조합해 혼합 transaction을 실행하고 failover 결과와 경고를 확인한다.

## [사용자-5년차-23] 파티션 테이블의 RK 유일성과 정책 상속이 정의되지 않았다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 테이블만 다루고 2-3절 출력에는 `partitioned`가 보인다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 해당 파티션 기능 지원 범위 확인 필요
- 영향 대상: 대형 테이블 사용자, 데이터 정합성

### 문제
부모 ON/OFF가 자식 파티션에 상속되는지, UK가 파티션 로컬이면 RK로 충분한지, ADD/SPLIT/EXCHANGE 중 복제 규칙이 없다.

### 왜 중요한가
같은 키가 다른 파티션에 중복되거나 일부 파티션만 미복제되면 행 탐색과 기간별 데이터가 어긋난다.

### 재현 또는 구체적 예제
공식 지원 문법으로 월별 sales 파티션을 운영한다고 하자.

```sql
SELECT class_name, partitioned, replication
FROM db_class WHERE class_name='sales';
```

이 결과만으로 파티션별 정책과 RK 범위를 알 수 없다.

### 권고안
정책 상속, global/local uniqueness, 파티션 DDL별 잠금·로그·오류를 지원표로 제공한다. 미지원 조합은 사전 차단한다.

### 검증 방법
지원 파티션 DDL을 후보 0/1/복수와 조합하고 전체 key 중복, 양 노드 행 집합과 failover 결과를 비교한다.

## [사용자-5년차-24] trigger·cascade·프로시저가 만든 내부 DML의 책임이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4~5절은 직접 DML과 FK 일부만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 지원 trigger·프로시저 기능과 복제 방식 확인 필요
- 영향 대상: 숙련 사용자, 애플리케이션, 데이터 정합성

### 문제
서버가 자동 생성한 DML이 ON/OFF 경계를 넘을 때 결과를 row log로 보내는지 standby에서 logic을 재실행하는지 없다.

### 왜 중요한가
두 방식이 겹치면 중복되고 빠지면 누락된다. application SQL trace에 직접 나타나지 않아 장애 분석도 어렵다.

### 재현 또는 구체적 예제
orders ON insert가 local_audit OFF를 쓰는 trigger를 가진다고 하자.

```sql
INSERT INTO orders(id,status) VALUES (20,'NEW');
SELECT COUNT(*) FROM local_audit WHERE order_id=20;
```

failover 뒤 expected count가 없다.

### 권고안
user/generated DML provenance, log 위치, standby trigger suppression, ON/OFF 판단 규칙을 명시하고 위험 dependency 조회 기능을 제공한다.

### 검증 방법
ON→ON, ON→OFF, OFF→ON 및 cascade를 조합해 실행 횟수·로그·최종 데이터를 확인한다.

## [사용자-5년차-25] TRUNCATE·bulk load·CTAS의 복제 분류가 없다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 4절은 모든 DDL과 ON 데이터 복제를 구분하지만 경계 명령을 열거하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 지원 bulk/CTAS 문법 확인 필요
- 영향 대상: 배치 사용자, OFF 로컬 데이터, 복제 부하

### 문제
구조와 데이터를 함께 다루는 명령이 OFF에서 어떻게 처리되는지 없다. TRUNCATE가 DDL로 전달되면 standby의 local data까지 지워질 수 있다.

### 왜 중요한가
숙련 사용자는 대량 작업으로 로그 폭증과 복제 지연도 관리해야 한다. 단순 INSERT와 다른 계약이 필요하다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache;
INSERT INTO archive SELECT * FROM orders;
```

각 테이블이 OFF일 때 standby 행과 log volume이 불명확하다.

### 권고안
명령별 schema/data replication, transaction, rollback, log volume 표를 제공하고 대량 작업 전 lag·공간 precheck를 지원한다.

### 검증 방법
지원 명령을 ON/OFF에서 큰 데이터로 실행해 양 노드 결과, log byte, lag, rollback을 대조한다.

## [사용자-5년차-26] PITR에서 RK 변경 전후 로그를 재생하는 계약이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 unload/load만 다루고 물리 backup·시점 복구는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 재해 복구 사용자, 백업 담당자

### 문제
backup 뒤 RK를 바꾸고 후속 로그를 특정 시점까지 재생할 때 구·신 RK 정의가 함께 복원되는지 없다.

### 왜 중요한가
PITR는 snapshot 이후 로그를 차례로 적용한다. 당시 key 의미가 없으면 복구가 실패하거나 잘못된 행을 바꿀 수 있다.

### 재현 또는 구체적 예제

```sql
-- 10:00 backup
-- 10:05
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
-- 10:10 DML, 10:11로 PITR
```

두 RK 세대의 replay 규칙이 없다.

### 권고안
backup/PITR가 selected RK identity, epoch, collation/type 의미를 보존한다고 명시하고 복구 후 HA 재가입·checksum 절차를 제공한다.

### 검증 방법
RK 전환 직전·중·후 backup을 여러 target time으로 복구해 RK history와 checksum, 후속 log apply를 검증한다.

## [사용자-5년차-27] loaddb 부분 실패의 idempotent 재개 방법이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 8절은 정상 load 결과만 설명한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: migration 사용자, 운영 시간

### 문제
일부 object/data/index 적재 뒤 RK 위반이나 disk full이 나면 checkpoint·cleanup·resume가 없다.

### 왜 중요한가
대용량 load를 매번 처음부터 하면 RTO가 길어진다. 잔여 객체에 재실행하면 중복 또는 다른 default가 적용될 수 있다.

### 재현 또는 구체적 예제
dump 순서가 a(ON+PK), b(ON+무키), c(OFF)라고 하자.

```sql
SELECT class_name, replication FROM db_class
WHERE class_name IN ('a','b','c');
```

b 실패 후 실제 state가 없다.

### 권고안
transaction 단위, checkpoint, continue/stop, cleanup과 idempotent resume를 정의한다. dry-run manifest로 모든 RK/FK/default 문제를 먼저 찾는다.

### 검증 방법
각 적재 단계에 failure를 주입하고 재개한다. object·row 중복 없이 manifest와 같은 최종 상태가 되는지 확인한다.

## [사용자-5년차-28] 장기 트랜잭션과 replica lag이 구 RK 보관 비용을 만든다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 운영 중 RK 변경을 허용하지만 transaction age·log retention은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 운영 사용자, 저장 공간, DR replica

### 문제
RK 변경 전 시작해 나중에 commit한 transaction과 오래 중지된 replica는 구 RK metadata/log를 요구한다. 지원 horizon이 없다.

### 왜 중요한가
구 정보를 조기 삭제하면 replica가 재생 불능이고 무기한 보관하면 primary disk가 찬다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE account SET balance=80 WHERE id=10;
-- RK 교체 6시간 뒤 COMMIT
COMMIT;
```

DR replica도 24시간 지연됐다고 가정한다.

### 권고안
최대 transaction/lag, epoch/log retention, pre-DDL 경고, re-seed 조건을 명시한다. 예상 보관 byte를 조회하게 한다.

### 검증 방법
transaction age와 replica lag을 경계 전후로 조합해 정상 replay, 경고, DDL 거부, re-seed 상태를 확인한다.

## [사용자-5년차-29] fail_count 외의 정상 상태 SLI가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2-3절은 ON/OFF만, 15번의 근거인 원문 전체는 실패 상세도 제공하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, SRE, failover 승인

### 문제
ON이고 오류 0이어도 apply가 멈출 수 있다. send/apply 위치, last success, RK epoch agreement, promotability가 없다.

### 왜 중요한가
장애 전에 최신 standby인지 판단하려면 실패뿐 아니라 진행 상태를 봐야 한다.

### 재현 또는 구체적 예제

```sql
INSERT INTO repl_probe(id,created_at) VALUES (100,CURRENT_DATETIME);
```

30분 미반영이어도 fail_count는 0일 수 있다.

### 권고안
seconds/bytes lag, send/apply LSA, last success, RK epoch, blocked table, promotability를 metric/API로 제공하고 SLO·경보를 정의한다.

### 검증 방법
정상·lag·apply stop·회복에서 dashboard와 alert가 실제 상태를 정확히 보여 주는지 확인한다.

## [사용자-5년차-30] split-brain 뒤 자동 재가입은 데이터 충돌을 숨길 수 있다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4~7절은 정상 failover만 다루고 network partition·old primary rejoin은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 숙련 사용자, HA, 데이터 정합성

### 문제
양 노드가 같은 RK에 다른 값을 쓴 뒤 재연결할 때 충돌을 감지·격리하는 계약이 없다.

### 왜 중요한가
RK는 row를 식별하지만 업무상 어느 값이 옳은지는 판단하지 못한다. last-write-wins는 손실을 숨긴다.

### 재현 또는 구체적 예제

```sql
-- A
UPDATE inventory SET qty=9 WHERE id=1;
-- B
UPDATE inventory SET qty=8 WHERE id=1;
```

재연결 후 자동 병합 정답이 없다.

### 권고안
term/fencing, stale write 거부, divergence report, 권위 노드 선택과 full re-seed runbook을 제공한다. 분기 노드는 자동 apply하지 않는다.

### 검증 방법
network와 fencing 장애를 조합한다. 단일 writer가 유지되거나 분기가 명확히 quarantine되는지 확인한다.

## [사용자-5년차-31] RK 오류 telemetry에서 개인정보가 유출될 수 있다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문은 error detail과 RK 값의 log·API·support bundle 노출 정책이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 개인정보, 보안 운영, 고객지원

### 문제
email·전화번호 같은 UK가 RK일 때 실패 event가 원문 key를 여러 telemetry system에 복사할 수 있다.

### 왜 중요한가
분산 로그는 DB보다 접근자가 많고 보존 기간도 길다. 진단 가능성과 최소 수집을 함께 설계해야 한다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET state='A' WHERE email='person@example.com';
```

apply failure event의 email 노출 범위가 없다.

### 권고안
기본 telemetry는 constraint ID와 keyed hash를 쓰고 원문은 break-glass 권한·감사·짧은 보존으로 제한한다.

### 검증 방법
민감 RK 오류를 만들어 log/metric/trace/bundle의 노출과 role-based access를 검사한다.

## [사용자-5년차-32] 인덱스 rebuild·제약 rename·통계 갱신이 RK를 바꾸는지 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 일부 DROP만 설명하고 정기 유지보수 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문 — 실제 지원 유지보수 문법 확인 필요
- 영향 대상: 숙련 사용자, 정기 maintenance, 성능

### 문제
활성 RK backing index를 rebuild하거나 constraint 이름을 바꿀 때 logical RK가 유지되는지, 통계 변화로 자동 선택이 바뀌는지 없다.

### 왜 중요한가
일상 유지보수만으로 RK가 바뀌면 과거 로그 해석과 성능 baseline이 흔들린다.

### 재현 또는 구체적 예제
지원 문법으로 `uk_member_email`을 rebuild/rename한 뒤 다음을 비교한다.

```sql
SHOW CREATE TABLE member;
SELECT * FROM db_class WHERE class_name='member';
```

활성 logical RK 확인 방법이 없다.

### 권고안
physical index와 logical RK identity를 분리하고 rebuild/rename/statistics의 불변식, lock과 log drain 요구를 명시한다.

### 검증 방법
유지보수 전후·재시작·failover 후 RK identity, query plan, log apply와 checksum을 비교한다.

## [사용자-5년차-33] clone·rename·schema diff에서 REPLICATION 속성 보존 규칙이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절은 일반 CREATE/ALTER와 SHOW만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문 — 지원 clone/LIKE/CTAS 문법 확인 필요
- 영향 대상: migration tool, 숙련 사용자, schema drift

### 문제
OFF 테이블 clone이 default ON이 되는지, rename 후 선택 RK identity가 유지되는지, diff 도구가 속성을 보존하는지 없다.

### 왜 중요한가
자동 schema 작업이 보호 정책을 조용히 바꾸면 테스트와 운영의 데이터 결과가 달라진다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE local_cache RENAME TO local_cache_old;
SHOW CREATE TABLE local_cache_old;
```

OFF와 RK metadata 보존 contract가 없다.

### 권고안
지원 copy/rename/schema 이동별 상속 규칙과 machine-readable metadata를 제공하고 schema diff round-trip을 인증한다.

### 검증 방법
ON/OFF·복수 UK 객체를 tool로 introspect→clone/rename→diff하여 policy와 RK identity drift가 없는지 확인한다.

## [사용자-5년차-34] OFF 테이블의 노드별 쓰기 충돌과 재가입 정책이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 OFF 불일치를 허용하지만 node-local write와 rejoin은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 숙련 사용자, failover/failback, OFF 데이터

### 문제
두 노드 OFF 테이블에 같은 key의 다른 값이 있으면 역할 전환·재가입·ON 복귀 시 어느 값을 보존할지 없다.

### 왜 중요한가
자동 merge는 권위 값을 알 수 없고 보존하면 역할마다 다른 값이 보인다. 복귀 전에 data lifecycle 결정을 해야 한다.

### 재현 또는 구체적 예제

```sql
-- node A
INSERT INTO local_cache VALUES (1,'A');
-- node B
INSERT INTO local_cache VALUES (1,'B');
```

failback 또는 OFF→ON 때 collision이 생긴다.

### 권고안
OFF를 node-local로 정의하고 standby write, promotion 초기화/보존, old node rejoin cleanup, ON 전환 전 authoritative snapshot과 rebuild 절차를 규정한다.

### 검증 방법
양 노드 충돌 데이터를 만든 뒤 failover/failback/rejoin/ON 전환을 수행해 조용한 병합 없이 정책대로 처리되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 14개
- 최종 리뷰 항목 수: 34개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID 파티션·trigger·프로시저·bulk·clone·index 유지보수 문법별 실제 지원 범위, PITR의 현행 RK metadata 보존, standby OFF 테이블 직접 쓰기 가능 여부
