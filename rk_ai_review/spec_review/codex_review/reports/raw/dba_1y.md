# DB 엔지니어/DBA / 1년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 처음 HA를 운영하는 DBA가 안전하게 테이블을 생성·변경하고, RK 상태를 점검하며, 장애와 불일치를 발견·복구할 수 있는지 검토했다.
- 확인하지 못한 전제: 실제 CUBRID 엔진 구현, 오류 코드 체계, 복제 로그 형식, `fail_count`의 정확한 증가·초기화 조건, 혼합 버전 지원 정책은 원문만으로 확인하지 못했다. 예제 SQL의 세부 문법은 구현과 공식 SQL 참조에서 추가 검증이 필요하다.

## 컨셉·문제 정의·대안 (3개)

## [DBA-1년차-01] RK가 기존 PK 변경 누락을 어떻게 막는지 연결 설명이 없다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 PK 또는 NOT NULL UK를 RK로 선택한다고 규정하고, 4절은 RK 후보 유지 제약을 제시하지만 기존 복제 누락 원인과 새 규칙의 연결은 설명하지 않는다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, 복제 정합성, 장애 조치

### 문제
문서는 “RK가 하나 이상 있어야 한다”는 결과만 말한다. DML 로그가 어느 시점의 RK 값과 RK 정의를 담는지, PK 속성 변경 전 로그가 변경 후 standby에서 어떻게 적용되는지는 없다. 따라서 RK 후보를 남겨 두는 것만으로 과거의 `fail_count` 증가와 변경 누락이 실제로 차단되는지 판단할 수 없다.

### 왜 중요한가
복제는 source에서 바뀐 행을 standby에서 다시 찾아야 한다. 예전 로그가 `id`로 행을 찾도록 기록됐는데 DDL 후 적용기가 `email`만 안다면, 두 키가 모두 유일하더라도 행을 찾지 못할 수 있다. 초급 DBA는 “키가 하나 있으니 안전하다”고 오해할 수 있다.

### 재현 또는 구체적 예제
초기 상태는 `id`가 PK이자 RK이고 standby 적용이 10초 늦은 상태다.

```sql
CREATE TABLE account (
  id INT PRIMARY KEY,
  email VARCHAR(100) NOT NULL UNIQUE,
  balance INT NOT NULL
) REPLICATION = ON;

UPDATE account SET balance = 900 WHERE id = 10;
ALTER TABLE account DROP PRIMARY KEY;
```

첫 `UPDATE` 로그가 `id=10`을 담았는지, `DROP` 후 UK인 `email`로 변환되는지 불명확하다. 기대 결과는 standby가 로그 생성 당시 RK 정의로 정확히 한 행을 갱신하거나, 안전한 적용이 불가능하면 DDL을 사전에 거부하는 것이다.

### 권고안
RK를 복제 로그에 기록하는 방식, DDL과 DML의 적용 순서, 구 RK 로그가 모두 소진되기 전 정의를 보존하는 규칙을 스펙에 추가한다. “항상 RK 후보 1개”뿐 아니라 “이미 생성된 모든 DML 로그를 해석 가능한 RK 정의가 유지된다”를 불변식과 수용 기준으로 명시한다.

### 검증 방법
standby 적용을 의도적으로 지연한 뒤 위 순서를 실행한다. 양 노드의 `id=10` 잔액, 적용 오류, `fail_count`를 비교하고 DDL 전 로그가 모두 성공 적용되는지 확인한다.

## [DBA-1년차-02] 모든 컬럼 비교 대안과 RK 방식의 손익 기준이 없다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 1절은 PK 또는 NOT NULL UK만 RK 후보로 인정하며, 2절은 키가 없는 ON 테이블을 HA에서 허용하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 기존 무키 테이블 사용자, 성능

### 문제
키 없는 행을 모든 컬럼으로 찾는 방식 대신 RK를 택한 이유와 적용 범위가 원문에 없다. 어떤 워크로드에서 모든 컬럼 비교가 느린지, HA 시작을 막는 비용과 비교해 왜 이 정책이 적절한지 판단 자료가 부족하다.

### 왜 중요한가
업무상 중복 행을 허용하는 로그 테이블에는 PK/UK를 추가할 수 없을 수 있다. 이때 DBA는 복제를 포기해 `OFF`로 둘지, 데이터 모델을 바꿀지 결정해야 한다. 장단점과 측정값이 없으면 성능을 이유로 정합성을 포기할 위험이 있다.

### 재현 또는 구체적 예제
초기 테이블은 중복 이벤트를 허용하고 키가 없다.

```sql
CREATE TABLE raw_event (
  source VARCHAR(20), payload VARCHAR(4000), created_at DATETIME
) REPLICATION = ON;
INSERT INTO raw_event VALUES ('sensor-1', 'same', DATETIME '2026-08-22 10:00:00');
INSERT INTO raw_event VALUES ('sensor-1', 'same', DATETIME '2026-08-22 10:00:00');
```

HA 시작 시 오류가 기대되지만, 대안은 `OFF`뿐인지 surrogate PK 추가가 권장되는지 불명확하다. 모든 컬럼을 사용하면 두 동일 행 중 하나를 확정할 수 없다는 문제도 예제로 설명해야 한다.

### 권고안
“모든 컬럼 방식 미지원”의 이유를 중복 행, NULL 비교, 긴 값의 로그·검색 비용으로 나눠 설명한다. 키 없는 기존 테이블에는 정수 surrogate PK 추가, `OFF` 전환, 데이터 재설계라는 선택지와 각각의 위험을 제시한다.

### 검증 방법
폭이 좁은 정수 테이블과 4KB 문자열 20개를 가진 테이블에서 INSERT/UPDATE 복제 처리량과 로그 크기를 측정한다. 또한 중복 행 예제에서 모든 컬럼 방식이 단일 행을 보장할 수 없는지 설계 검토로 확인한다.

## [DBA-1년차-03] `REPLICATION=OFF`가 허용하는 불일치의 경계가 지나치게 넓다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절과 4절은 OFF 테이블의 DDL은 복제하지만 데이터는 복제하지 않으며 그 불일치는 책임지지 않는다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 애플리케이션, failover 데이터 정합성

### 문제
“책임지지 않는다”는 문구는 동작 계약이 아니다. 기존 standby 데이터의 유지·삭제 여부, TRUNCATE 같은 명령의 분류, failover 후 OFF 테이블 접근 가능 여부가 정의되지 않았다.

### 왜 중요한가
DDL로 빈 테이블 구조만 만들어지고 DML은 전달되지 않으면 양 노드가 서로 다른 데이터를 갖는다. 새 primary로 전환하면 사용자는 테이블이 존재하므로 정상이라고 생각하지만 결과는 비어 있거나 오래됐을 수 있다.

### 재현 또는 구체적 예제
두 노드에 `local_cache` 구조가 있고 source에서만 데이터를 넣는다.

```sql
CREATE TABLE local_cache (id INT PRIMARY KEY, value VARCHAR(100)) REPLICATION = OFF;
INSERT INTO local_cache VALUES (1, 'source-only');
-- failover 후 새 primary에서 실행
SELECT * FROM local_cache WHERE id = 1;
```

기대 결과가 빈 결과인지, 기존 로컬 값인지, 접근 오류인지 문서상 불명확하다. DBA는 failover 후 캐시 재생성 필요 여부를 알 수 없다.

### 권고안
OFF의 정확한 대상 명령을 표로 정의하고, 각 노드 데이터는 로컬 소유임을 명시한다. failover runbook에 OFF 테이블 목록 확인, 초기화 또는 외부 원본으로부터 재구축하는 절차를 포함한다.

### 검증 방법
INSERT, UPDATE, DELETE, TRUNCATE, ALTER를 각각 실행한 뒤 양 노드의 행 수와 스키마를 비교한다. failover 후 문서에 명시한 결과 및 재구축 절차와 일치하는지 확인한다.

## 용어·기본값·사용자 계약 (2개)

## [DBA-1년차-04] RK 후보와 실제 선택된 RK를 조회할 계약이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 1절은 후보 중 엔진이 하나를 선택한다고 하고, 2-3절 조회 예제는 `replication: ON`만 보여 준다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 변경 계획, 감사

### 문제
DBA는 ON/OFF는 볼 수 있지만 실제 RK의 제약 이름과 컬럼을 볼 수 없다. 후보와 현재 RK를 구분하지 못하면 어떤 키 변경이 제한되며 어떤 로그가 어떤 컬럼을 사용하는지 예측할 수 없다.

### 왜 중요한가
PK가 있으면 PK가 RK이고 PK가 없으면 UK 중 하나라는 규칙만으로는 여러 UK의 실제 선택을 알 수 없다. 운영 변경 전에 현재 RK를 알아야 삭제 가능 여부와 로그 비용을 계산할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (
  email VARCHAR(100) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL UNIQUE,
  name VARCHAR(50)
) REPLICATION = ON;
SHOW CREATE TABLE member;
SELECT * FROM db_class WHERE class_name = 'member';
```

초기 상태에 두 UK가 있다. 문서 예제의 출력으로는 `email`과 `phone` 중 어느 것이 RK인지 알 수 없다. 기대 결과는 `rk_constraint`, 순서가 보존된 `rk_columns`, 선택 사유를 조회하는 것이다.

### 권고안
공식 카탈로그 또는 `SHOW REPLICATION KEY member` 같은 조회 문법과 권한을 정의한다. 출력 예제에 실제 RK, 후보 목록, ON/OFF, 마지막 변경 시각을 포함한다.

### 검증 방법
PK만, UK 하나, UK 여러 개, 복합 UK인 테이블을 만들고 조회 결과가 실제 선택 규칙과 일치하는지 확인한다. 재시작 후에도 동일한 결과인지 검사한다.

## [DBA-1년차-05] 기본값 ON은 기존 사용자에게 안전한 기본값이 아닐 수 있다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 옵션 생략 시 ON, 3절은 single에서도 옵션 사용 가능, 7절은 무키 ON 테이블이 있으면 HA 시작 오류라고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, 기존 애플리케이션, HA 기동

### 문제
기존 SQL은 `REPLICATION`을 쓰지 않았으므로 모두 ON으로 해석된다. single에서 키 없는 임시·로그 테이블을 만든 뒤 HA로 바꾸면 전체 HA 시작이 차단될 수 있으나, 경고나 사전 점검 시점이 없다.

### 왜 중요한가
기본값은 사용자가 아무것도 지정하지 않았을 때 적용되는 정책이다. 기존에 성공하던 `CREATE TABLE`이 장래 HA 기동을 막는다면 호환성 영향이 크며, 오류가 배포 시점이 아니라 장애 대응 시점에 드러날 수 있다.

### 재현 또는 구체적 예제

```sql
-- single 모드의 기존 배포 스크립트
CREATE TABLE import_stage (line_no INT, raw_text VARCHAR(4000));
-- 수개월 후: cubrid hb start
```

테이블은 암묵적으로 ON이지만 RK가 없어 HA 시작이 실패하는 것이 문서상 예상된다. 기대 동작은 생성 시 경고, 사전 검사 명령, 또는 업그레이드 시 명시적 변환 정책 제공이다.

### 권고안
ON 기본값을 유지한다면 버전 업그레이드 시 기존 테이블의 값 결정 규칙과 경고를 명시한다. `checkdb` 성격의 사전 검사 명령과 `ALTER TABLE import_stage REPLICATION=OFF` 수정 예제를 제공한다.

### 검증 방법
구버전 DB에 키 없는 테이블을 만든 뒤 새 버전으로 업그레이드한다. 카탈로그 값, 경고, HA 시작 검사 결과와 수정 후 재시작 결과를 확인한다.

## SQL 문법과 상태 전이 (3개)

## [DBA-1년차-06] 여러 UK 중 선택 규칙이 결정적이고 지속적인지 불명확하다

- 분류: 모호성
- 심각도: Blocker
- 근거 위치: 원문 1절은 여러 UK 중 엔진이 선택하며 “예: 테이블 내 명시된 순서 중 가장 빠른 순서”라고만 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, DBA, 백업·복원

### 문제
“예”는 규칙이 아니며, 명시 순서가 카탈로그·unload/load·노드마다 보존되는지도 없다. source와 standby가 다른 UK를 RK로 선택하면 같은 로그를 동일하게 적용한다고 보장할 수 없다.

### 왜 중요한가
결정적이라는 말은 같은 입력이면 항상 같은 결과가 나온다는 뜻이다. 이름 정렬인지 생성 순서인지 명확하지 않으면 재시작이나 복원 후 RK가 뜻하지 않게 바뀔 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE contact (
  email VARCHAR(100) NOT NULL,
  phone VARCHAR(30) NOT NULL,
  CONSTRAINT uk_z_phone UNIQUE(phone),
  CONSTRAINT uk_a_email UNIQUE(email)
) REPLICATION = ON;
```

선언 순서라면 `uk_z_phone`, 이름 순서라면 `uk_a_email`이 선택된다. unload/load 과정에서 제약 출력 순서가 바뀔 때 RK가 유지되는지 불명확하다. 기대 결과는 모든 노드와 복원 후에도 동일한 식별자를 선택하는 것이다.

### 권고안
PK 우선, 그다음에는 영속적인 제약 ID나 명시된 완전한 정렬 규칙을 사용한다고 규정한다. 가능하면 선택 결과를 카탈로그에 저장하고 복제·백업하도록 한다. 동률 처리도 명시한다.

### 검증 방법
제약 이름과 선언 순서를 반대로 만든 뒤 재시작, unload/load, 복제 노드 생성 과정을 수행한다. 각 단계에서 조회된 RK 제약과 컬럼이 동일한지 비교한다.

## [DBA-1년차-07] 한 ALTER의 기존 키 삭제와 새 키 추가가 원자적인지 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13은 한 문장에서 DROP과 ADD를 허용한다고만 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, DBA, DDL 복구

### 문제
두 동작이 하나의 트랜잭션처럼 전부 성공하거나 전부 실패하는지, 내부 처리 중 잠시 RK가 0개가 될 수 있는지 정의되지 않았다. 새 키 생성이 중복 값 때문에 실패하면 이전 키가 이미 삭제됐는지도 알 수 없다.

### 왜 중요한가
원자성은 여러 변경을 하나의 단위로 다루는 성질이다. 원자적이지 않으면 실패한 DDL 하나가 테이블을 복제 불가능한 중간 상태로 남길 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (id INT PRIMARY KEY, code INT, value INT) REPLICATION = ON;
INSERT INTO t VALUES (1, 7, 10), (2, 7, 20);
ALTER TABLE t DROP PRIMARY KEY, ADD CONSTRAINT uk_t_code UNIQUE(code);
```

새 UK는 `code=7` 중복 때문에 실패해야 한다. 기대 결과는 전체 ALTER가 실패하고 기존 PK와 RK `id`가 그대로 남는 것이다. 문서는 실제 결과를 설명하지 않는다.

### 권고안
복합 ALTER의 검증을 변경 전 상태에서 먼저 끝내고, 카탈로그와 복제 로그에 단일 원자 연산으로 반영한다고 명시한다. 실패 시 원래 RK가 보존되는 오류 코드와 예제를 추가한다.

### 검증 방법
중복 값, 디스크 공간 부족, 강제 프로세스 종료를 각각 ADD 단계에 유발한다. 재시작 후 PK/RK와 데이터가 변경 전 상태이거나 변경 후 상태 중 하나이며 중간 상태가 아님을 확인한다.

## [DBA-1년차-08] 복합 키와 키 컬럼 속성 변경의 허용 표가 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 4-2절은 PK/UK의 추가·삭제만 예시로 들고 복합 키, 타입·이름·NULL 가능 여부 변경은 다루지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 스키마 변경, 복제 정합성

### 문제
복합 PK/UK의 일부 컬럼 삭제, 이름 변경, 자료형 변경, `NOT NULL` 제거가 RK 변경으로 간주되는지 없다. UK 컬럼 하나가 NULL 가능해지면 더 이상 RK 후보 조건을 만족하지 않는다.

### 왜 중요한가
복합 키는 두 개 이상의 값을 합쳐 한 행을 구별한다. 구성 컬럼 하나만 바뀌어도 전체 행 식별 규칙이 바뀐다. 일반 컬럼 변경처럼 허용하면 적용기가 행을 찾지 못할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE stock (
  warehouse_id INT NOT NULL,
  sku VARCHAR(30) NOT NULL,
  qty INT,
  CONSTRAINT uk_stock UNIQUE(warehouse_id, sku)
) REPLICATION = ON;

ALTER TABLE stock CHANGE sku product_code VARCHAR(100);
ALTER TABLE stock ALTER COLUMN warehouse_id DROP NOT NULL;
```

첫 DDL에서 구 로그의 컬럼 이름·값 변환 방법, 둘째 DDL의 허용 여부가 불명확하다. 후보가 하나뿐이면 둘째 DDL은 원자적으로 거부되어야 한다.

### 권고안
RK 구성 컬럼별 `RENAME`, 타입 확대·축소, collation 변경, `DROP NOT NULL`, 컬럼 순서 변경의 허용/거부 표를 제공한다. 허용 시 구 로그 호환 방식도 규정한다.

### 검증 방법
복합 정수·문자열 UK를 만들고 각 DDL을 하나씩 실행한다. 허용된 경우 지연 중인 UPDATE/DELETE가 정확한 한 행에 적용되는지, 거부된 경우 스키마가 전혀 변하지 않는지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [DBA-1년차-09] DDL과 DML 동시 실행의 직렬화 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 운영 중 DDL 허용 범위를 말하지만 동시 트랜잭션과 로그 순서는 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, 애플리케이션, DBA

### 문제
RK 값을 갱신하는 DML과 RK를 교체하는 DDL이 겹칠 때 잠금, 대기, 거부, 로그 순서 규칙이 없다. source에서 성공한 순서와 standby 적용 순서가 달라질 가능성을 배제할 근거가 없다.

### 왜 중요한가
DDL이 새 키를 만들 때 기존 행을 검사하는 동안 DML이 그 값을 바꾸면 검사 결과가 즉시 오래될 수 있다. 같은 순서가 보장되지 않으면 standby에서 중복 또는 미발견 오류가 나고 `fail_count`가 늘 수 있다.

### 재현 또는 구체적 예제
초기 RK는 `id`다. 세션 A의 트랜잭션을 커밋하지 않은 상태에서 세션 B를 실행한다.

```sql
-- 세션 A
UPDATE account SET email='new@example.com' WHERE id=10;

-- 세션 B
ALTER TABLE account DROP PRIMARY KEY,
  ADD CONSTRAINT uk_account_email UNIQUE(email);
```

기대 동작은 B가 A 종료까지 대기하거나 명확한 오류로 거부되고, 커밋 순서와 복제 로그 순서가 일치하는 것이다. 현재 문서에는 답이 없다.

### 권고안
DDL 잠금 수준, 대기 제한, 교착 처리, 커밋/로그 순서를 상태 전이 표로 명시한다. RK 관련 DDL은 기존 DML과 직렬화하고 타임아웃 오류를 구분하도록 한다.

### 검증 방법
두 세션의 시작·커밋 순서를 바꾼 동시성 시험을 100회 반복한다. source/standby 체크섬, 적용 오류와 `fail_count`, DDL 결과가 항상 같은지 검사한다.

## [DBA-1년차-10] failover가 RK 전환 중 발생할 때의 복구 상태가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 운영 중 RK 변경을 허용하고 7절은 HA 시작 전 검사만 다루며, 변경 도중 failover는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 장애 조치, 복제 정합성

### 문제
새 RK 인덱스 구축, 카탈로그 변경, DDL 로그 적용 사이에 source 장애가 나면 새 primary가 구 RK와 신 RK 중 무엇을 사용해야 하는지 정의되지 않았다.

### 왜 중요한가
failover는 가장 준비가 덜 된 순간에도 발생한다. 일부 단계만 적용된 standby가 primary가 되면 이후 쓰기가 서로 다른 키 규칙으로 기록되어 failback도 어려워질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE orders (
  id BIGINT PRIMARY KEY,
  external_id VARCHAR(100) NOT NULL UNIQUE,
  amount INT
) REPLICATION = ON;

ALTER TABLE orders DROP PRIMARY KEY,
  ADD CONSTRAINT pk_orders_external PRIMARY KEY(external_id);
-- 인덱스 구축 또는 DDL 복제 중 source 강제 종료 후 failover
```

기대 결과는 DDL이 미커밋이면 구 RK, 커밋이면 신 RK로 완전 복구되는 것이다. “부분 전환” 상태에서는 승격을 거부해야 한다.

### 권고안
RK 변경의 durable commit 지점, standby 승격 전 검사, 미완료 DDL의 rollback/redo 규칙을 명시한다. 자동 failover와 수동 복구 각각의 runbook을 제공한다.

### 검증 방법
DDL 처리 단계마다 장애를 주입해 standby를 승격한다. 카탈로그, 인덱스, 실제 RK 조회가 모두 구 상태 또는 신 상태로 일치하며 DML 복제가 재개되는지 확인한다.

## [DBA-1년차-11] HA 시작 전 검사가 원자적이지 않으면 통과 직후 위반될 수 있다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절은 HA 실행 시 무키 ON 테이블과 OFF 참조 FK를 검사하고 파일 리스트를 출력한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, HA 기동, 복제 정합성

### 문제
검사 대상 스키마의 스냅샷, 검사 중 DDL 차단, HA 활성화 시점과의 원자성이 없다. 검사가 끝난 직후 다른 세션이 RK를 제거하면 잘못된 상태로 HA가 시작될 수 있다.

### 왜 중요한가
검사와 사용 사이에 틈이 있으면 “확인했을 때는 안전했지만 시작할 때는 위험한” 경쟁 조건이 생긴다. 테이블이 많아 검사가 오래 걸릴수록 가능성이 커진다.

### 재현 또는 구체적 예제

```sql
-- 세션 A: HA 시작 검사가 많은 테이블을 순회 중
-- 세션 B: 검사 완료된 테이블을 변경
ALTER TABLE audit_log DROP PRIMARY KEY;
-- 세션 A: cubrid hb start 완료
```

기대 결과는 B가 차단·거부되거나 A가 동일 스키마 버전을 다시 확인하고 시작을 실패하는 것이다. 원문에는 잠금과 재검사 규칙이 없다.

### 권고안
검사 시작부터 HA 모드 확정까지 스키마 세대 번호를 고정하거나 RK 관련 DDL을 차단한다. 오류 출력은 “파일 리스트”가 아니라 DB·소유자·테이블·위반 이유·수정 SQL 후보를 제공하도록 정의한다.

### 검증 방법
1만 개 테이블로 검사 시간을 늘리고 검사 중 반복 DDL을 시도한다. HA가 위반 상태로 한 번도 시작되지 않는지, 오류 목록이 모든 위반 테이블을 빠짐없이 담는지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [DBA-1년차-12] RK 값 자체를 UPDATE할 때 이전 값과 새 값의 사용 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절과 4-2절은 RK 제약의 DDL만 다루며 RK 컬럼 값에 대한 DML은 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, 애플리케이션

### 문제
RK 컬럼 값을 변경하면 standby에서 행을 찾을 때 변경 전 값이 필요하다. 로그에 이전 값과 새 값 중 무엇이 기록되며, 두 값이 어떻게 검증되는지 없다.

### 왜 중요한가
standby 행은 아직 이전 값을 가지고 있으므로 새 값으로 검색하면 찾을 수 없다. 먼저 이전 값으로 정확히 한 행을 찾은 뒤 새 값으로 바꿔야 한다. 재적용 때 이미 새 값이면 멱등 처리 규칙도 필요하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (
  email VARCHAR(100) NOT NULL UNIQUE,
  name VARCHAR(50)
) REPLICATION = ON;
INSERT INTO customer VALUES ('old@example.com', 'Kim');
UPDATE customer SET email='new@example.com' WHERE email='old@example.com';
```

기대 결과는 로그가 old와 new를 충분히 담고 standby의 단 한 행을 변경하는 것이다. 적용 재시도와 충돌 시 오류 동작은 문서상 불명확하다.

### 권고안
RK 변경 DML은 이전 RK로 대상을 찾고 새 RK 유일성을 검사한다는 규칙, 로그 필드, 0행·2행 이상 발견 시 오류와 중단 정책을 명시한다.

### 검증 방법
단일·복합 RK 값을 변경하고 적용기를 중간에 재시작해 로그를 재적용한다. 양 노드에 정확히 한 행만 있으며 `fail_count`가 증가하지 않는지 확인한다.

## [DBA-1년차-13] FK 규칙이 참조 방향과 연쇄 동작을 충분히 다루지 않는다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 5절은 ON인 자식 테이블이 OFF인 부모를 참조하는 경우만 금지하며 `ON DELETE/UPDATE`와 OFF 자식의 경우는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 참조 무결성, failover

### 문제
부모 ON/자식 OFF, 부모 OFF/자식 OFF 조합과 연쇄 삭제·수정이 DDL인지 DML인지에 따른 복제 결과가 없다. 특히 source에서 부모 삭제가 OFF 자식 행을 연쇄 삭제하면 standby의 로컬 자식 데이터와 달라질 수 있다.

### 왜 중요한가
FK는 자식 값이 실제 부모를 가리키도록 보장한다. 연쇄 동작은 한 SQL이 다른 테이블 DML을 자동 발생시킨다. 테이블별 ON/OFF가 다르면 자동 DML의 복제 여부를 명확히 해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parent (id INT PRIMARY KEY) REPLICATION = ON;
CREATE TABLE child (
  id INT PRIMARY KEY,
  parent_id INT,
  FOREIGN KEY(parent_id) REFERENCES parent(id) ON DELETE CASCADE
) REPLICATION = OFF;
INSERT INTO parent VALUES (1);
INSERT INTO child VALUES (10, 1);
DELETE FROM parent WHERE id=1;
```

source의 OFF 자식은 연쇄 삭제될 수 있다. standby에는 부모 DELETE만 적용될 때 로컬 child가 있으면 FK 오류가 나는지 불명확하다.

### 권고안
부모/자식 ON·OFF 4가지 조합과 `RESTRICT`, `CASCADE`, `SET NULL`별 허용 표를 추가한다. 안전하지 않은 조합은 CREATE와 ALTER 시 거부하고 기존 위반은 HA 시작 검사에 포함한다.

### 검증 방법
각 조합에서 부모 UPDATE/DELETE를 실행하고 source/standby의 결과, 적용 오류, failover 후 FK 검사 결과를 기록한다.

## [DBA-1년차-14] OFF 테이블을 포함한 VIEW를 “제약 없음”으로 표현하면 위험하다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절은 모든 DDL이 반영되므로 failover 후 VIEW 사용에 제약이 없다고 하면서 결과 불일치는 책임지지 않는다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사용자, DBA, 조회 정합성

### 문제
VIEW 객체가 존재하는 것과 같은 결과를 반환하는 것은 다르다. “제약 없음”은 조회가 정상이라는 의미로 읽히며, OFF 테이블을 JOIN하거나 집계한 업무 뷰가 failover 후 조용히 잘못된 결과를 낼 수 있다.

### 왜 중요한가
오류가 나면 운영자가 알아차릴 수 있지만 빈 결과나 작은 합계는 정상값처럼 보인다. 이는 탐지하기 어려운 데이터 정합성 문제다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (id INT PRIMARY KEY, name VARCHAR(50)) REPLICATION = ON;
CREATE TABLE local_grade (customer_id INT PRIMARY KEY, grade INT) REPLICATION = OFF;
CREATE VIEW vip_customer AS
  SELECT c.id, c.name FROM customer c JOIN local_grade g
  ON c.id=g.customer_id WHERE g.grade >= 5;
```

source에는 등급 행이 있지만 standby에는 없다고 가정한다. failover 후 뷰는 오류 없이 0행을 반환할 수 있다. 기대 결과는 최소한 의존성 경고와 운영자 확인이다.

### 권고안
VIEW 생성·변경 시 OFF 의존성을 경고하고 카탈로그에서 조회 가능하게 한다. HA 시작 및 failover 사전 점검에 영향받는 VIEW 목록을 출력하고, 문구를 “실행은 가능하지만 결과 동일성은 보장되지 않음”으로 고친다.

### 검증 방법
직접·중첩 VIEW와 ON/OFF JOIN을 만들고 의존성 목록을 검사한다. failover 전후 결과 차이가 경고·모니터링에서 탐지되는지 확인한다.

## 운영·오류·관측 가능성 (2개)

## [DBA-1년차-15] `fail_count`의 증가·경보·초기화 계약이 빠져 있다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 1~9절 전체에서 HA 오류와 ERROR는 언급하지만 `fail_count`의 의미, 위치, 조치 절차는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 모니터링, 장애 대응

### 문제
변경 목적과 직접 관련된 복제 실패를 운영자가 어떻게 발견할지 없다. 어떤 이벤트가 카운터를 늘리고 성공 재시도 시 줄거나 초기화되는지, 테이블·LSA별 세부 원인을 어디서 보는지 정의되지 않았다.

### 왜 중요한가
숫자가 커져도 원인을 모르면 경보 기준을 정할 수 없다. 카운터만 수동 초기화하면 실제 누락은 그대로인데 정상으로 오인할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE inventory (id INT PRIMARY KEY, qty INT) REPLICATION = ON;
UPDATE inventory SET qty=qty-1 WHERE id=100;
-- 시험 환경에서 standby의 id=100 행을 미리 제거한 뒤 적용
```

적용 대상 0행 오류가 발생한다고 가정한다. 기대 결과는 `fail_count` 증가와 함께 DB/테이블/로그 위치/구 RK/오류 코드가 기록되고 경보가 발생하는 것이다. 단순 재시작 후 카운터가 어떻게 되는지는 불명확하다.

### 권고안
카운터 정의, 영속성, 초기화 권한, 오류 분류, 권장 임계값을 명시한다. 테이블별 마지막 실패와 재시도 결과를 조회하는 명령 및 “카운터 초기화는 데이터 복구가 아니다”라는 경고를 추가한다.

### 검증 방법
0행, 중복 행, UK 충돌, 스키마 불일치 오류를 각각 유발한다. 카운터와 로그가 정확히 대응하고 재시작 후 보존되며, 복구·재적용 후 상태가 문서대로 변하는지 확인한다.

## [DBA-1년차-16] 기존 데이터 불일치를 탐지하고 교정하는 절차가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 1절과 4절은 불일치 가능성을 인정하고 7절은 스키마 조건만 검사한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 기존 설치, 복제 정합성

### 문제
새 기능은 앞으로의 잘못된 DDL을 제한할 뿐 이미 누락된 행을 찾아 복구하는 방법을 제공하지 않는다. 스키마가 유효해도 데이터가 다르면 failover는 안전하지 않다.

### 왜 중요한가
PK 변경으로 과거 UPDATE가 빠졌다면 RK를 추가해도 잔액 같은 값은 자동으로 돌아오지 않는다. 기동 검사가 통과했다는 사실을 데이터 일치 확인으로 착각할 수 있다.

### 재현 또는 구체적 예제

```sql
-- source 결과
SELECT id, balance FROM account WHERE id=10; -- 10, 900
-- standby 결과가 과거 누락으로 10, 1000이라고 가정
ALTER TABLE account ADD CONSTRAINT uk_account_email UNIQUE(email);
```

UK 추가는 성공할 수 있지만 `balance` 차이는 남는다. 기대 결과는 체크섬 비교로 차이를 찾고 서비스 영향 없이 재동기화하는 공식 절차가 있는 것이다.

### 권고안
테이블별 행 수·범위 체크섬 비교, 불일치 상세 추출, 쓰기 중지 또는 snapshot 기준의 재동기화, 복구 후 검증 순서를 문서화한다. OFF 테이블은 비교 대상에서 명시적으로 구분한다.

### 검증 방법
시험 환경에서 행 누락·값 차이·추가 행을 만든다. 제공 절차가 세 유형을 모두 탐지하고, 재동기화 뒤 같은 snapshot의 체크섬이 일치하며 애플리케이션 영향이 기록되는지 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [DBA-1년차-17] 구버전 unload 파일 기본값이 8절과 9절에서 충돌한다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 변수가 없으면 ON으로 간주한다고 하고, 9절 요약 5는 정보를 포함하지 않는 테이블은 모두 OFF라고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 백업·복원, 업그레이드

### 문제
동일한 입력 파일을 ON과 OFF 중 어느 것으로 복원할지 문서가 서로 반대로 말한다. 구현자가 어느 문장을 따르느냐에 따라 데이터 복제 여부가 달라진다.

### 왜 중요한가
구버전 파일에는 새 필드가 없으므로 기본값이 유일한 결정 수단이다. ON이면 무키 테이블 때문에 HA 기동이 실패할 수 있고, OFF이면 사용자가 기대한 데이터가 standby에 전달되지 않을 수 있다.

### 재현 또는 구체적 예제
구버전 unload 파일에 다음과 같은 테이블 정의가 있고 `REPLICATION` 필드는 없다고 가정한다.

```sql
CREATE TABLE legacy_log (seq INT, message VARCHAR(1000));
-- 신버전 single 모드에서 loaddb 후 상태 조회
SELECT class_name, replication FROM db_class WHERE class_name='legacy_log';
```

8절 기대는 ON, 9절 기대는 OFF라 하나의 정답이 없다. 이는 구현·시험을 시작하기 전 결정해야 한다.

### 권고안
정책 하나를 결정해 8절과 9절을 일치시킨다. 안전을 위해 loaddb 옵션으로 `--default-replication=ON|OFF|ERROR`를 제공하고, 무키 ON 테이블 목록과 선택 결과를 요약 출력한다.

### 검증 방법
필드가 없는 구버전, ON, OFF가 명시된 신버전 파일을 각각 load한다. 옵션 조합별 카탈로그 상태, 경고, HA 시작 가능 여부가 명세와 정확히 일치하는지 확인한다.

## [DBA-1년차-18] 롤링 업그레이드와 대형 키의 성능 시험 범위가 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 1~9절은 새 문법·카탈로그·unload 형식을 제안하지만 서로 다른 버전 노드와 부하 시험을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 가용성, 성능, 호환성

### 문제
구버전 standby가 새 `REPLICATION` DDL과 RK 로그를 이해하는지, 무중단 롤링 업그레이드가 가능한지 없다. 또한 긴 복합 문자열 UK를 RK로 선택했을 때 로그 크기와 적용 속도 상한도 없다.

### 왜 중요한가
HA는 노드를 한 번에 모두 내리지 않고 순차 업그레이드하는 경우가 많다. 한 노드가 새 로그를 읽지 못하면 복제가 멈춘다. RK가 넓으면 각 DML 로그와 인덱스 비교 비용도 커질 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE shipment (
  region VARCHAR(100) NOT NULL,
  partner VARCHAR(200) NOT NULL,
  external_no VARCHAR(500) NOT NULL,
  payload VARCHAR(4000),
  UNIQUE(region, partner, external_no)
) REPLICATION = ON;
UPDATE shipment SET payload='changed'
 WHERE region='KR' AND partner='P1' AND external_no='X1';
```

구버전 standby에 이 DML과 `ALTER TABLE ... REPLICATION=OFF`가 전달될 때 허용·거부 여부가 없다. 기대 결과는 지원 행렬과 사전 호환성 차단이다.

### 권고안
source/standby 버전 조합별 읽기·쓰기·DDL 지원 행렬과 업그레이드 순서를 제시한다. RK 폭·컬럼 수별 로그 크기, 처리량, 지연의 수용 기준을 정하고 지나치게 넓은 후보 선택을 피하는 규칙도 검토한다.

### 검증 방법
구→신, 신→구 혼합 구성에서 CREATE/ALTER/DML/failover를 수행한다. 1·3·10개 RK 컬럼과 정수·긴 문자열을 비교해 TPS, 로그 바이트, 적용 지연, CPU를 기록하고 기준 초과 여부를 판정한다.

## 문서 품질·예제·오탈자 (2개)

## [DBA-1년차-19] 예제의 오류가 실제 실행과 학습을 방해한다

- 분류: 문서 품질
- 심각도: Minor
- 근거 위치: 원문 2-1절 예시 2와 5절 예시 23에는 마지막 컬럼 뒤 쉼표가 있고, 5-1절 제목은 `CRATE TABLE`, 7절에는 “재시작해아한다”가 있다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 초급 DBA, 문서 신뢰성, 시험 자동화

### 문제
의도한 기능 오류와 SQL 구문 오류가 섞여 있다. `ERROR`만 표시된 예제는 RK 제약 때문에 실패했는지 잘못된 쉼표 때문에 실패했는지 구별할 수 없다.

### 왜 중요한가
초급 독자는 예제를 그대로 실행해 배운다. 구문이 틀리면 제품 정책을 시험하기 전에 파서가 거부하므로 스펙의 기대 동작을 검증하지 못한다.

### 재현 또는 구체적 예제

```sql
-- 원문 예시 2의 형태
CREATE TABLE repl_table_without_rk (
  a INT,
) REPLICATION = ON;
```

초기 상태와 무관하게 마지막 쉼표 때문에 구문 오류가 날 수 있다. 문서가 의도한 결과는 single에서 성공하고 HA에서 RK 부재 오류가 나는 것이므로 서로 다른 실행 예제로 나눠야 한다.

### 권고안
쉼표를 제거하고 `CRATE`를 `CREATE`, “재시작해아한다”를 “재시작해야 한다”로 고친다. 모든 예제에 실행 모드와 실제 오류 코드·메시지를 넣고 `//` 주석 문법도 공식 지원 여부를 확인한다.

### 검증 방법
문서의 모든 SQL 코드 블록을 추출해 single과 HA의 지정 환경에서 자동 실행한다. 예상 성공/실패 및 오류 코드가 문서와 일치하고 단순 파서 오류가 0건인지 확인한다.

## [DBA-1년차-20] 모드 정의와 오류 출력 설명이 초급 운영 절차로 부족하다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 1절은 `cubrid hb start` 이외를 모두 single로 부르고, 3절·9절은 Single과 SA를 함께 언급하며, 7절은 “파일 리스트”를 출력한다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 초급 DBA, 운영 자동화, 장애 대응

### 문제
single, SA, HA의 관계와 각 SQL의 허용 여부가 한 표에 정리되지 않았다. 위반 대상은 테이블인데 “파일 리스트”라고 표현해 무엇이 출력되는지 알 수 없고 오류 예제는 대부분 `ERROR`뿐이다.

### 왜 중요한가
운영자는 현재 모드를 정확히 알아야 DDL 성공 여부와 수정 절차를 예측한다. 오류 메시지에 테이블과 이유가 없으면 수백 개 객체를 수동 조사해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key (value INT) REPLICATION = ON;
ALTER TABLE no_key REPLICATION = OFF;
ALTER TABLE no_key REPLICATION = ON;
```

이 세 문장을 single, SA, HA에서 각각 실행했을 때의 결과 표가 없다. HA 시작 오류 또한 `dba.no_key: RK 없음` 같은 객체 목록인지 OS 파일 경로인지 불명확하다.

### 권고안
모드별 CREATE ON/OFF, OFF→ON, ON→OFF, RK DDL 허용 표를 추가한다. 현재 모드 확인 명령, 종료·수정·재시작 순서, 실제 오류 코드와 `owner.table`, 위반 유형, 권장 조치를 포함한 출력 예제를 제공한다.

### 검증 방법
새 DBA가 표만 보고 세 모드에서 위 SQL의 결과를 사전 작성하게 한 뒤 실제 실행 결과와 비교한다. 여러 위반 테이블을 만든 HA 시작 시험에서 출력만으로 모든 수정 SQL을 작성할 수 있는지 확인한다.

## [DBA-1년차-21] 복제 정책 변경 권한과 최소 권한 운영 방법이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-2절은 사용자가 ON/OFF를 바꾼다고 하지만 필요한 권한은 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 초급 DBA, 애플리케이션 계정, 데이터 보호

### 문제
일반 테이블 `ALTER` 권한만 있으면 `REPLICATION=OFF`도 실행 가능한지, 별도의 DBA 권한이 필요한지 알 수 없다. 상태 조회와 RK 변경 권한도 분리되어 있지 않다.

### 왜 중요한가
OFF는 테이블 구조를 조금 바꾸는 작업이 아니라 standby로 DML을 보내지 않는 보호 정책 변경이다. 배포 계정이 성능 문제를 해결하려고 OFF로 바꾸면 failover 후 업무 데이터가 보이지 않을 수 있다.

### 재현 또는 구체적 예제
```sql
-- 일반 ALTER 권한만 가진 deploy_user라고 가정
ALTER TABLE payment REPLICATION=OFF;
```
성공, 권한 오류, 추가 승인 필요 중 어느 결과인지 없다. 초급 DBA는 계정에 과도한 권한을 줄 가능성이 있다.

### 권고안
CREATE ON/OFF, 상태 조회, ON→OFF, OFF→ON, RK 후보 변경별 필요 권한을 표로 정한다. 복제 정책 변경은 별도 시스템 권한으로 분리하고 업무 핵심 테이블에는 변경 금지 정책을 제공한다.

### 검증 방법
DBA, owner, ALTER-only, SELECT-only 계정으로 모든 명령을 실행한다. 권한 행렬과 오류 코드가 일치하고 우회 가능한 명령이 없는지 확인한다.

## [DBA-1년차-22] 누가 언제 ON/OFF와 RK를 바꿨는지 감사할 방법이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절은 현재 상태 조회만 제안하고 변경 이력은 누락한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 초급 DBA, 감사, 장애 원인 분석

### 문제
현재 ON/OFF는 볼 수 있지만 변경 사용자, 시각, 이전·새 값, 실제 RK 변경 이유를 확인할 수 없다. 실패한 DDL과 rollback된 시도도 기록되는지 없다.

### 왜 중요한가
failover 후 테이블이 비어 있으면 DBA는 OFF가 의도된 설정인지 실수인지 판단해야 한다. 이력이 없으면 여러 배포 로그를 뒤지거나 담당자 기억에 의존한다.

### 재현 또는 구체적 예제
월요일 `orders`가 OFF로 변경되고 금요일 failover에서 주문이 부족하다. `db_class`는 현재 OFF만 보여 주므로 누가 실행했는지와 당시 HA 상태를 알 수 없다.

### 권고안
actor, timestamp, database/owner/table, old/new 상태와 RK, DDL, 성공/실패, source node를 감사 로그에 남긴다. 초급 DBA용 조회 예와 보존 기간을 제공한다.

### 검증 방법
서로 다른 계정으로 성공·실패·rollback된 상태 변경을 실행한다. 모든 감사 이벤트를 검색할 수 있고 실제 DDL 순서를 재구성할 수 있는지 확인한다.

## [DBA-1년차-23] 파티션 테이블에서 ON/OFF와 RK 적용 단위를 알 수 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1~4절은 일반 테이블만 설명하며 파티션 관련 객체는 언급하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 대형 테이블 DBA, 복제 정합성

### 문제
대상 CUBRID 버전이 파티션 테이블을 지원한다면 부모와 각 파티션 중 어디에 상태가 저장되는지, 새 파티션이 상태와 RK를 상속하는지, 파티션 내부에서만 유일한 키가 RK가 될 수 있는지 없다.

### 왜 중요한가
월별 파티션 하나가 OFF이면 특정 월 데이터만 standby에서 빠질 수 있다. 파티션별 중복 값을 전체 행 식별자로 쓰면 다른 파티션의 같은 키를 잘못 찾을 수도 있다.

### 재현 또는 구체적 예제
```sql
-- 정확한 CUBRID 파티션 문법과 지원 버전은 확인 필요
CREATE TABLE sales (sale_date DATE, id INT, amount INT,
  PRIMARY KEY (sale_date,id)) REPLICATION=ON;
```
새 월 파티션 추가·분할·교환 시 ON과 복합 RK가 유지되는지 문서에 없다.

### 권고안
지원 여부를 명시하고 지원한다면 부모/자식 상태, local/global uniqueness, 파티션 추가·삭제·교환의 전이 표를 제공한다. 점검 명령은 모든 파티션을 펼쳐 보여 줘야 한다.

### 검증 방법
지원되는 파티션 DDL마다 ON/OFF와 키 조합을 만들고 경계 양쪽 DML을 실행한다. failover 후 모든 파티션 행 수와 checksum을 비교한다.

## [DBA-1년차-24] bulk load와 TRUNCATE의 복제 여부가 분명하지 않다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1·4절은 DDL/DML을 일반적으로 설명하지만 대량 적재와 TRUNCATE는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 배치 운영, 데이터 이관, 로그 용량

### 문제
운영 중 bulk utility, 대량 INSERT, `TRUNCATE TABLE`이 ON/OFF를 따르는지, 일반 row log를 우회하는지 없다. 8절의 `loaddb`와 일상 bulk load의 차이도 설명되지 않는다.

### 왜 중요한가
bulk 경로가 복제 로그를 만들지 않으면 ON인데도 standby 데이터가 비게 된다. 반대로 1억 행을 모두 로그로 보내면 디스크와 apply 지연이 급격히 늘 수 있다.

### 재현 또는 구체적 예제
```sql
TRUNCATE TABLE event_stage;
-- 이후 지원되는 bulk 도구로 1억 행을 적재한다고 가정
```
TRUNCATE DDL과 적재 데이터가 각각 replica에 가는지, 중간 failover 결과가 무엇인지 없다.

### 권고안
지원되는 대량 변경 명령·도구별 ON/OFF 동작, log량, atomicity, 취소와 failover 제한을 표로 제공한다. HA-safe 도구와 사전 공간 계산법을 알려 준다.

### 검증 방법
일반 INSERT, bulk load, TRUNCATE 후 load를 ON/OFF에서 실행한다. source/replica 행 수·checksum, 로그 증가량과 중간 failover 결과를 확인한다.

## [DBA-1년차-25] 대형 테이블 RK 추가의 진행률·잠금·취소 절차가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 3·4절은 PK/UK 추가를 해결 방법으로 제시하지만 작업 비용은 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 초급 DBA, 대형 테이블, 서비스 가용성

### 문제
UK/PK 추가가 online인지, 쓰기를 막는 잠금과 timeout, 진행률 확인, 취소 후 부분 인덱스 정리 방법이 없다. online DDL 지원 여부도 대상 버전에서 확인해야 한다.

### 왜 중요한가
수억 행에 UK를 만들려면 모든 행을 읽고 중복을 검사한다. 초급 DBA가 작은 테스트 결과만 보고 운영에 실행하면 오랜 lock과 디스크 부족을 만들 수 있다.

### 재현 또는 구체적 예제
```sql
ALTER TABLE customer
  ADD CONSTRAINT uq_customer_email UNIQUE(email);
```
5억 행에서 70% 진행 중 취소하거나 lock timeout이 나면 기존 RK, 임시 공간과 쓰기 서비스가 어떤 상태인지 없다.

### 권고안
행 수·키 폭 기반 예상 공간, lock 수준, online 지원, 진행률 조회, 취소·cleanup·retry 절차를 제공한다. 운영 실행 전 중복 검사와 유지보수 창 승인을 요구한다.

### 검증 방법
대형 샘플에서 쓰기 부하 중 DDL을 실행·취소·timeout시킨다. 진행률, 요청 지연, 임시 파일 정리와 기존 RK 유지 여부를 확인한다.

## [DBA-1년차-26] PITR과 복제 로그 보관 기간이 RK 변경과 연결되지 않는다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load만 설명하고 시점 복구와 로그 보관은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 백업·복구 DBA, RPO/RTO

### 문제
PITR을 지원하는 구성이라면 backup 시점의 RK와 이후 변경 로그를 함께 보존해야 한다. 필요한 DDL 로그가 만료됐을 때 후속 DML만 적용할 수 있는지, 새 baseline backup이 필요한지 없다.

### 왜 중요한가
PITR은 backup 뒤 로그를 시간 순으로 재생한다. id→email RK 변경 기록 없이 email 기반 DML만 남으면 복구 엔진이 어느 키로 행을 찾을지 알 수 없다.

### 재현 또는 구체적 예제
01시 full backup, 02시 RK 변경, 03시 DML, 04시 사고 후 03시 30분으로 복구한다. 02시 DDL 로그가 보관 만료됐다면 안전한 복구가 불가능할 수 있다.

### 권고안
지원 복구 방식과 backup manifest에 REPLICATION/RK 정보를 명시하고 DDL·DML 로그의 공동 보관 하한을 정한다. 부족하면 미리 경고하고 새 full backup을 요구한다.

### 검증 방법
RK 변경 전 backup에서 여러 시점으로 복구한다. 중간 DDL 로그를 제거한 시험은 조용히 부분 복구되지 않고 명확한 오류로 중단되는지 확인한다.

## [DBA-1년차-27] 디스크 full 시 source와 standby의 RK가 갈라질 수 있다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4-2절은 성공 또는 단순 ERROR만 다루고 자원 부족 중간 실패는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 초급 DBA, 복제 apply, failover 안전성

### 문제
새 UK 생성·복제 중 source에는 공간이 충분하지만 standby가 disk full이면 source만 새 RK로 전환될 수 있다. 부분 DDL이 rollback되는지, 후속 로그와 승격이 차단되는지 없다.

### 왜 중요한가
standby가 옛 RK에서 멈춘 뒤 source가 새 RK DML을 만들면 연쇄 apply 실패가 발생한다. 이 상태에서 source 장애가 나도 standby를 안전하게 승격할 수 없다.

### 재현 또는 구체적 예제
email UK index가 standby에서 90% 생성됐을 때 디스크를 가득 채운다. source DDL은 성공한 뒤 email 기반 UPDATE가 이어진다. DBA에게 필요한 경보와 복구 순서가 없다.

### 권고안
작업 전 양 노드 공간 사전 검사와 예약, DDL apply failure barrier, 승격 불가 표시, 임시 index cleanup과 full resync 조건을 정의한다.

### 검증 방법
source와 standby 각각 index build 단계에서 disk full을 주입한다. 부분 상태가 남지 않고 후속 apply/승격이 안전하게 차단되며 공간 확보 후 문서 절차로 복구되는지 본다.

## [DBA-1년차-28] 네트워크 분할 시 단일 writer 보장과 DDL 금지 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4·7절은 정상 master/slave와 failover만 설명하며 split-brain은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: HA 운영, 데이터 정합성, 장애 대응

### 문제
네트워크가 분리되어 두 노드가 자신을 primary로 판단할 때 한쪽에서 OFF, 다른 쪽에서 RK 변경이 가능한지 없다. 재연결 시 두 schema와 데이터를 합치는 정책도 없다.

### 왜 중요한가
split-brain은 두 사람이 같은 문서를 서로 다르게 수정한 것과 같다. 같은 행에 다른 값과 키 정의가 생기면 자동 병합이 안전하지 않다.

### 재현 또는 구체적 예제
노드 A는 `orders OFF` 후 주문 101, 노드 B는 email RK 전환 후 주문 102를 만든다. 재연결 뒤 단순 로그 교환은 서로의 키·복제 정책을 이해하지 못할 수 있다.

### 권고안
quorum/fencing으로 한 노드만 쓰도록 보장하고 fencing이 확인되지 않으면 RK·REPLICATION DDL을 거부한다. 권위 노드 선택과 다른 노드 재구축 runbook을 제공한다.

### 검증 방법
heartbeat와 복제 네트워크를 각각 분리해 양쪽 DDL/DML을 시도한다. 한쪽 쓰기가 차단되고 재결합 뒤 데이터·RK가 하나의 권위 상태로 수렴하는지 확인한다.

## [DBA-1년차-29] 같은 apply 오류의 반복 재시도와 재시작 정책이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 전체에 `fail_count` 이후 retry·중단·격리 동작이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 초급 DBA, 복제 자원, 경보

### 문제
영구 row-not-found를 계속 재시도하는지, 건너뛰는지, node를 격리하는지 없다. 재시작 뒤 실패 LSA와 `fail_count`가 유지되는지도 불명확하다.

### 왜 중요한가
무한 재시도는 CPU와 로그 공간을 소모하고 후속 변경을 막는다. 건너뛰면 조용한 불일치가 생긴다. 단순 재시작으로 증상이 숨으면 초급 DBA가 해결된 것으로 오해한다.

### 재현 또는 구체적 예제
standby에 대상 행이 없어 같은 UPDATE가 100번 실패한 뒤 apply 프로세스를 재시작한다. 다시 100번 실패하는지, 로그를 skip하는지, 정지하는지 문서에 없다.

### 권고안
오류별 retry 횟수와 backoff, fatal barrier, quarantine, 운영자 승인과 resync 조건을 정의한다. 실패 LSA·원인은 재시작 후에도 유지하고 상태 조회 명령에 표시한다.

### 검증 방법
영구 row-not-found와 일시 I/O 오류를 주입하고 재시작한다. 일시 오류만 재시도로 복구되고 영구 오류는 건너뛰지 않은 채 격리·경보되는지 확인한다.

## [DBA-1년차-30] 인덱스 재구축과 제약 이름 변경의 RK 영향이 없다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 4-2절은 DROP INDEX만 다루며 rebuild·rename·통계 갱신은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 정기 유지보수, RK 지속성, 복제 정합성

### 문제
UNIQUE 의미는 유지하면서 인덱스를 rebuild하거나 제약 이름을 바꿀 때 실제 RK가 유지되는지 없다. 통계 갱신이나 optimizer 선택이 RK 선택에 영향을 주는지도 알 수 없다.

### 왜 중요한가
초급 DBA는 인덱스 재구축을 성능 유지보수로만 생각한다. 내부 ID가 바뀌어 RK까지 바뀐다면 대기 복제 로그와 충돌할 수 있다.

### 재현 또는 구체적 예제
email UK가 RK인 `member`의 index를 지원 명령으로 rebuild하고 제약 이름을 변경한다고 하자. 변경 전 DML 로그가 옛 ID를 가리켜도 새 index로 적용돼야 한다.

### 권고안
지원되는 rebuild/rename/reorganize/statistics 작업별 RK ID 유지 여부와 잠금·로그 처리를 표로 정한다. RK 선택은 optimizer 통계와 분리해야 한다.

### 검증 방법
각 유지보수 작업 전후 선택 RK와 지연 DML apply를 비교한다. 재시작·failover 후에도 동일 key descriptor를 사용하는지 확인한다.

## [DBA-1년차-31] 임시·시스템·도구 생성 테이블의 정책 범위가 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 2-1·7절은 모든 테이블처럼 표현하며 제외 객체 유형은 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 초급 DBA, HA 사전 검사, 관리 도구

### 문제
임시 테이블, 시스템 catalog, 관리 도구가 내부 생성하는 테이블, 세션 수명 객체에 REPLICATION 기본 ON과 RK 필수 규칙이 적용되는지 없다. 실제 지원 객체 종류는 대상 버전 확인이 필요하다.

### 왜 중요한가
로컬 임시 객체까지 검사하면 불필요하게 HA 시작이 막힐 수 있다. 반대로 영구 도구 테이블이 검사에서 빠지면 중요한 상태가 standby에 없을 수 있다.

### 재현 또는 구체적 예제
백업·모니터링 도구가 `tool_stage(value INT)`를 PK 없이 자동 생성한다고 하자. 이것이 영구 user table이면 기본 ON으로 HA 시작을 막고, 임시 table이면 제외돼야 할 수 있다.

### 권고안
지원 객체 유형별 ON/OFF 지정 가능 여부, 기본값, HA 검사·DDL 복제 포함 여부를 표로 제공한다. 사전 검사 출력에는 객체 유형과 생성 주체를 표시한다.

### 검증 방법
지원되는 임시·영구·시스템/도구 객체를 생성해 catalog와 HA 검사 결과를 비교한다. 제외 객체가 시작을 막지 않고 포함 객체는 누락되지 않는지 확인한다.

## [DBA-1년차-32] 관리 화면과 자동 점검용 대량 조회 형식이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절은 단일 SHOW 예와 `select * from db_class`, 7절은 파일 리스트만 제안한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 초급 DBA, 모니터링, 수천 테이블 환경

### 문제
수천 테이블의 ON/OFF, 실제 RK, 후보, FK/VIEW 위험을 한 번에 필터링·내보내는 구조화된 조회가 없다. `select *`는 버전별 열 추가와 출력 순서에 취약하다.

### 왜 중요한가
초급 DBA가 모든 `SHOW CREATE TABLE`을 수동 확인할 수 없다. 자동 점검은 안정된 열 이름과 상태 코드가 있어야 하며 국제화된 자연어 오류만으로는 파싱하기 어렵다.

### 재현 또는 구체적 예제
1만 테이블 중 RK 없는 ON 5개, OFF 부모 FK 3개, OFF 의존 VIEW 20개가 있다고 하자. 현재 예제로는 각 테이블을 일일이 조회해야 하고 결과를 운영 도구에 넣기 어렵다.

### 권고안
안정된 관리 view/API에 owner, table, object type, ON/OFF, selected RK, candidate count, violation code를 제공한다. CSV/JSON 출력, pagination과 국제화와 무관한 code를 지원한다.

### 검증 방법
1만 객체를 만들어 필터·pagination·내보내기를 시험한다. 모든 위반이 중복·누락 없이 나오고 자동화가 locale 변경에도 같은 결정을 내리는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 12개
- 최종 리뷰 항목 수: 32개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·임시 객체·bulk/online DDL·PITR 지원 여부와 정확한 문법, 실제 권한 이름·감사 저장소·관리 API, 인덱스 rebuild/rename 명령, 엔진 코드와 자원 산정 수치
