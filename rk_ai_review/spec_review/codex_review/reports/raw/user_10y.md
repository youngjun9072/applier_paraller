# 최종 사용자 / 10년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 장기 호환성, 최악 장애와 복구 가능성, 제품 계약의 지속성, 운영 자동화, 위험한 기본값과 실수 방지, 여러 기능의 상호작용
- 확인하지 못한 전제: 실제 CUBRID 복제 로그·카탈로그·잠금 구현, 오류 코드, `fail_count` 정의, backup/restore 포맷, 버전 혼합 지원 정책은 확인하지 못했다. 외부 DB 제품과 동일한 동작은 가정하지 않는다.

## [USER-10Y-01] 기능의 핵심 불변식과 완료 조건이 없다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 RK 필수화, 4절의 DDL 복제, 9절 요약
- 사실/추론 구분: 확인된 사실 — 허용된 전환 뒤 source/replica의 스키마·행·로그 해석이 같아야 한다는 불변식이 명시되지 않는다
- 영향 대상: 장기 사용자, 복제 정합성, 장애 조치, 제품 지원

### 문제
문서는 “항상 RK 후보가 하나 이상”이라는 스키마 조건만 강조한다. 그러나 실제 목적은 DDL 전후 모든 커밋된 DML이 같은 행에 한 번 적용되고 양 노드 데이터가 같아지는 것이다. 키가 존재해도 로그가 옛 키로 기록되고 replica가 새 키로 해석하면 원래 장애가 반복될 수 있다.

### 왜 중요한가
불변식은 여러 구현 선택이 달라도 반드시 지켜야 하는 약속이다. 장기 운영에서는 재시작, 지연, 장애 조치, 버전 변경이 겹친다. 단순 후보 수가 아니라 로그 생성 시점의 키 정의와 적용 시점의 키 정의가 연결되어야 데이터가 보존된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE account (
  id INT PRIMARY KEY,
  email VARCHAR(100) NOT NULL UNIQUE,
  balance INT NOT NULL
) REPLICATION = ON;

UPDATE account SET balance = balance - 100 WHERE id = 10;
ALTER TABLE account DROP PRIMARY KEY,
  ADD CONSTRAINT pk_account_email PRIMARY KEY (email);
```

UPDATE 로그가 아직 replica에 적용되지 않은 상태에서 DDL이 처리되는 최악 순서를 가정한다. 기대 결과는 어떤 재시작·지연에서도 양쪽 잔액이 같고 `fail_count`가 키 전환 때문에 증가하지 않는 것이다.

### 권고안
제품 계약에 최소 불변식을 추가한다: ON 테이블은 커밋 경계마다 유효한 활성 RK가 있고, DML 로그는 해당 RK 세대를 식별하며, DDL/DML 커밋 순서는 모든 노드에서 보존되고, 재적용은 멱등적이며, 성공한 로그가 조용히 누락되지 않는다. 각 불변식을 출시 수용 기준에 연결한다.

### 검증 방법
PK→PK, PK→UK, UK→PK, UK→UK 전환에서 DML 지연·재시작·크래시·failover를 모든 경계에 주입한다. 최종 스키마, 행별 체크섬, 로그 적용 위치, `fail_count`를 비교하고 한 불변식이라도 위반하면 출시를 차단한다.

## [USER-10Y-02] 여러 UK의 RK 선택이 장기간 안정적인 객체 정체성이 아니다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절의 여러 UK 중 엔진 선택 예시와 4-2절의 사용자 직접 변경 불가
- 사실/추론 구분: 확인된 사실 — 선택 기준이 예시일 뿐이며 백업·복원·재작성·업그레이드 후 지속 규칙이 없다
- 영향 대상: 장기 사용자, 복제 정합성, 스키마 관리 도구, 지원 조직

### 문제
“테이블에 명시된 순서 중 빠른 것”은 영구적인 식별 규칙이 아니다. unload/load, DDL 재생성, 제약 rename, 카탈로그 마이그레이션이 순서를 바꿀 수 있다. 엔진 버전이 선택 알고리즘을 바꿔도 사용자에게 보이는 호환성 약속이 없다.

### 왜 중요한가
10년 이상 운영한 스키마는 여러 번 이동·복원·업그레이드된다. 같은 논리 스키마가 매번 다른 활성 RK를 선택하면 과거 로그와 새 카탈로그가 충돌한다. 선택은 제약 이름의 우연한 정렬보다 영구 ID와 명시된 전환 기록에 연결돼야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE employee (
  employee_no INT NOT NULL CONSTRAINT uq_emp_no UNIQUE,
  email VARCHAR(100) NOT NULL CONSTRAINT uq_emp_email UNIQUE
) REPLICATION = ON;
```

원본 DB는 `uq_emp_no`, unload/load된 DB는 `uq_emp_email`을 선택한다고 가정한다. 같은 UPDATE 로그의 값 `1001`을 후자는 이메일로 찾을 수 없다. 기대 결과는 복원 후에도 동일한 활성 RK 또는 안전한 세대 전환이다.

### 권고안
활성 RK를 영구 제약 ID·컬럼 ID·순서·스키마 세대로 저장하고 복제·백업·unload에 포함한다. 엔진 선택 알고리즘은 공개된 결정 규칙으로 버전화한다. 자동 재선택은 후보 추가 시가 아니라 명시된 원자적 전환에서만 수행하는 방안을 우선 검토한다.

### 검증 방법
동일 DB를 수차례 unload/load, backup/restore, 제약 rename, 메이저 업그레이드한다. 매 단계의 활성 RK ID와 컬럼 순서를 비교하고, 보존되지 않는 설계라면 전환 전후 로그 모두 정상 적용되는지 확인한다.

## [USER-10Y-03] REPLICATION=OFF의 면책은 지속 가능한 제품 계약이 아니다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절의 불일치 면책과 6절 VIEW 면책
- 사실/추론 구분: 확인된 사실 — OFF로 데이터 불일치를 허용하지만 보존·복구·지원 범위와 적합한 사용 사례가 없다
- 영향 대상: 장기 사용자, 법적·감사 데이터, 지원 조직, 장애 조치

### 문제
“책임지지 않는다”는 문구는 구현 범위를 줄일 수 있지만 고객의 운영 계약을 만들지는 못한다. OFF 데이터가 노드 로컬인지, 백업에는 포함되는지, 재가입 때 유지되는지, failback 때 어느 사본이 남는지 정의되지 않는다.

### 왜 중요한가
오늘은 캐시로 만든 테이블이 몇 년 뒤 업무 데이터로 재사용될 수 있다. 옵션 의미가 데이터 사전과 모니터링에 노출되지 않으면 담당자 교체 뒤 위험을 잊는다. 장애 시 두 노드에 갈라진 데이터는 자동으로 병합할 수 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE local_job (
  id INT PRIMARY KEY,
  state VARCHAR(20),
  payload VARCHAR(1000)
) REPLICATION = OFF;
```

A에서 id=1, failover 후 B에서 id=2가 생성되고 다시 A로 failback한다고 가정한다. 1과 2를 합칠지 한쪽을 폐기할지 원문에 답이 없다.

### 권고안
OFF를 별도의 “node-local” 데이터 등급으로 정의하고 지원 수명 동안 유지할 생명주기 계약을 제공한다. 생성 경고, 데이터 사전 표시, 중요 테이블 정책 차단, failover/failback/재가입/backup별 보존 행렬과 수동 병합 책임을 명시한다.

### 검증 방법
캐시·작업 큐·감사 로그·결제 데이터의 5년 운영 시나리오를 검토해 OFF 허용 여부가 담당자마다 일치하는지 확인한다. 두 번의 failover와 노드 재구축 뒤 행 보존 결과가 행렬과 같은지 시험한다.

## [USER-10Y-04] 활성 RK를 관찰하고 변경 이력을 감사할 계약이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절의 REPLICATION 조회와 4-2절의 엔진 자동 선택
- 사실/추론 구분: 확인된 사실 — 조회 예시는 ON/OFF만 표시하며 활성 RK, 후보, 선택 세대, 이력이 없다
- 영향 대상: 장기 사용자, 감사 담당자, DBA, 장애 분석

### 문제
현재 활성 RK가 무엇인지와 언제 왜 바뀌었는지를 사용자가 확인할 수 없다. `SHOW CREATE TABLE`의 PK/UK 정의만으로 엔진 내부 선택을 추론해야 한다. 과거 장애 로그가 어떤 키 세대를 사용했는지도 연결할 수 없다.

### 왜 중요한가
장기 운영에서 현재 상태만으로는 사고 원인을 분석할 수 없다. DDL 배포 시각과 RK 변경 시각, 첫 적용 오류를 연결해야 재발 방지와 데이터 교정 범위를 정할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE member ADD CONSTRAINT uq_member_email UNIQUE (email);
ALTER TABLE member DROP PRIMARY KEY;
```

현재 조회가 ON만 보이면 첫 ALTER 뒤 활성 키가 유지됐는지, 둘째 뒤 언제 UK로 전환됐는지 알 수 없다. 기대 결과는 현재와 이전 RK 세대 및 변경 트랜잭션을 조회하는 것이다.

### 권고안
시스템 뷰에 테이블, 활성 RK 제약/컬럼 ID, 후보 목록, 세대, 시작·종료 로그 위치, 변경 트랜잭션과 시각을 제공한다. 이력 보존 기간과 감사 백업 포함 여부, 조회 권한을 제품 계약으로 정한다.

### 검증 방법
여러 번 키를 전환하고 재시작·failover한 뒤 이력만으로 각 DML 로그의 키 세대를 추적한다. 오래된 이력이 보존 정책대로 남고 장애 분석에 필요한 객체가 rename 뒤에도 연결되는지 확인한다.

## [USER-10Y-05] 기본 ON과 지연 실패는 기존 스키마에 큰 운영 함정이다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 2-1절의 생략 시 ON, 3절의 키 없는 ON 허용, 7절의 HA 시작 거부
- 사실/추론 구분: 확인된 사실 — 키 없는 테이블 생성은 non-HA에서 성공하고 나중 HA 시작에서 실패한다
- 영향 대상: 기존 사용자, 대규모 스키마, 개발·운영 전환

### 문제
옵션 생략을 ON으로 해 기존 문법을 유지하지만 오류를 미래로 미룬다. 수천 개 레거시 테이블이 있는 DB는 HA 도입 날에야 위반을 발견할 수 있다. 신규 DB, 업그레이드 DB, 복원 DB의 기본 정책도 구분하지 않는다.

### 왜 중요한가
장기 사용자는 오래된 애플리케이션 DDL과 신규 도구를 함께 쓴다. 지연 실패는 원인 배포와 장애 시점이 멀어져 추적 비용이 크다. 안전한 전환에는 사전 재고 조사와 단계적 강제 정책이 필요하다.

### 재현 또는 구체적 예제

```sql
-- 5년 전 도구가 옵션 없이 생성
CREATE TABLE legacy_event (event_text VARCHAR(1000));
-- 현재 HA 도입
-- cubrid hb start
```

기본 ON과 RK 없음 때문에 시작이 막힌다. 기대 결과는 업그레이드 당시부터 지속 경고와 readiness 보고서로 발견하는 것이다.

### 권고안
호환 모드와 HA-ready 엄격 모드를 분리한다. 업그레이드 시 전체 inventory와 영향 보고서를 만들고, 경고→배포 차단→강제 정책의 단계적 도입 일정을 제공한다. 신규 HA 대상 DB에서는 키 없는 기본 ON CREATE를 즉시 거부한다.

### 검증 방법
1만 개 혼합 레거시 테이블을 가진 DB를 업그레이드하고 사전 검사 시간·누락률을 측정한다. 기존 DDL이 어떤 경고를 받는지, 엄격 모드 전환 전에 모든 위반이 수정되는지 확인한다.

## [USER-10Y-06] 새 SQL 문법의 정규 출력과 round-trip 규칙이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절의 `REPLICATION={ON|OFF}` 문법과 2-3절 `SHOW CREATE TABLE`
- 사실/추론 구분: 확인된 사실 — 허용 위치·중복 지정·정규 표기·도구 왕복 보존 규칙이 없다
- 영향 대상: 장기 사용자, 스키마 비교·마이그레이션 도구, 백업 자동화

### 문제
문서는 한 가지 문법 예시만 제시한다. 옵션 중복, 대소문자, 다른 CREATE 옵션과 순서, `CREATE TABLE AS SELECT`, 파티션 등 기존 변형과의 결합 규칙이 없다. `SHOW CREATE TABLE` 출력이 다시 실행 가능한지도 보장하지 않는다.

### 왜 중요한가
장기 운영에서는 사람이 아닌 도구가 DDL을 읽고 재생성한다. 입력은 허용됐지만 출력에서 옵션이 사라지거나 순서가 달라 parser가 실패하면 schema diff와 재해 복구가 깨진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (id INT PRIMARY KEY)
  REUSE_OID, COLLATE utf8_bin, REPLICATION ON;
SHOW CREATE TABLE t;
```

출력 DDL을 빈 DB에 실행했을 때 같은 ON과 RK 후보를 재현해야 한다. `REPLICATION ON REPLICATION OFF` 같은 중복은 명확히 거부해야 한다.

### 권고안
문법 도표에 옵션 위치, 기본값, 중복·상충 오류와 기존 CREATE 변형별 지원 범위를 추가한다. 정규 출력은 파서가 재수용하며 dump→load→dump 결과가 의미상 같다는 round-trip 계약을 둔다.

### 검증 방법
기존 CREATE 문법 변형과 새 옵션을 조합한 parser 테스트를 수행한다. `SHOW CREATE TABLE` 출력을 새 DB에 반복 적용하고 ON/OFF, 제약, 활성 RK가 동일한지 비교한다.

## [USER-10Y-07] 복합 ALTER의 부분 실패와 크래시 복구가 정의되지 않는다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 DROP+ADD 키 전환
- 사실/추론 구분: 확인이 필요한 질문 — 검증·카탈로그 변경·로그 기록 중 크래시 때 원자성이 보장되는지 없다
- 영향 대상: 장기 사용자, 복제 정합성, 장애 복구

### 문제
하나의 ALTER로 키를 교체하라는 안내만 있고 새 제약 검증 실패, 디스크 부족, 서버 크래시, replica 적용 실패 시 상태가 없다. source는 새 키, replica는 옛 키로 남는 split-schema 가능성을 배제하지 않는다.

### 왜 중요한가
원자성은 단순 SQL 트랜잭션 성공 여부를 넘어 crash recovery와 복제 재적용까지 유지돼야 한다. 마지막 RK가 사라진 중간 상태가 복구 후 보이면 DML 적용이 중단된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (
  id INT CONSTRAINT pk_customer PRIMARY KEY,
  email VARCHAR(100)
) REPLICATION = ON;
INSERT INTO customer VALUES (1,'dup@x'),(2,'dup@x');

ALTER TABLE customer DROP CONSTRAINT pk_customer,
  ADD CONSTRAINT uq_customer_email UNIQUE(email);
```

중복으로 ADD가 실패하거나 DROP 로그 뒤 서버가 크래시한다고 가정한다. 기대 결과는 양 노드 모두 옛 PK/RK를 유지하거나 모두 새 키로 커밋하는 것뿐이다.

### 권고안
사전 유효성 검사, 원자적 카탈로그 변경, WAL/복제 로그 순서, crash redo/undo, replica 재적용의 상태 머신을 규정한다. 부분 상태는 관찰 불가이며 재시작 후 자동 수렴해야 한다. 실패 후 사후 조회와 안전한 재시도 계약을 제공한다.

### 검증 방법
검증, 인덱스 생성, 카탈로그 커밋, 로그 전송, replica 적용 각 지점에 crash를 주입한다. 재시작을 반복해 스키마/RK/데이터가 한 커밋 상태로 수렴하고 같은 로그 재적용이 중복 효과를 만들지 않는지 확인한다.

## [USER-10Y-08] 지원 DDL 상태 전이가 장기 스키마 진화를 포괄하지 않는다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 제한된 PK/UK 추가·삭제 예시와 “다른 후보가 있으면 모든 DDL 허용”
- 사실/추론 구분: 확인된 사실 — rename, 타입·collation·NOT NULL 변경, 복합 키 재정렬 등은 없다
- 영향 대상: 장기 사용자, 스키마 마이그레이션, 복제 정합성

### 문제
실제 10년 스키마는 컬럼 rename, 정수 폭 확대, 문자셋·collation 변경, 복합 키 재구성, 제약 rename을 겪는다. 다른 후보가 있으면 “모든 DDL”이 허용된다는 문장은 로그 호환성을 보장하지 못한다.

### 왜 중요한가
키는 제약 이름뿐 아니라 컬럼 ID·순서·타입·비교 규칙으로 이루어진다. 이 중 하나가 바뀌면 옛 로그 값의 해석이 달라질 수 있다. 장기 지원하려면 모든 전이를 허용·온라인 전환·점검 중단·영구 금지로 분류해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE shipment (
  tenant INT NOT NULL,
  tracking VARCHAR(30) NOT NULL,
  legacy_id INT NOT NULL UNIQUE,
  CONSTRAINT uq_tracking UNIQUE(tenant, tracking)
) REPLICATION = ON;

ALTER TABLE shipment ALTER COLUMN tracking VARCHAR(500);
ALTER TABLE shipment ALTER COLUMN tenant DROP NOT NULL;
ALTER TABLE shipment RENAME COLUMN legacy_id AS old_id;
```

각 DDL 후 후보 자격과 활성 RK 세대가 어떻게 되는지 없다.

### 권고안
활성 RK/비활성 후보/마지막 후보 × 제약·컬럼 변경 × 모드의 상태 전이 표를 규범화한다. 타입 호환성, collation, 복합 순서, rename의 ID 보존 여부와 롤백을 포함하고 버전 추가 시 표를 호환성 계약으로 관리한다.

### 검증 방법
표의 모든 셀을 데이터 규모와 타입별로 자동 시험한다. 업그레이드 전후 같은 DDL 결과가 유지되는지, 달라질 경우 명시된 버전 오류나 migration 경고가 나오는지 검증한다.

## [USER-10Y-09] 장기 트랜잭션과 복제 지연 중 RK 전환의 순서가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 DDL 복제와 운영 중 ALTER 허용
- 사실/추론 구분: 확인이 필요한 질문 — 장기 DML, DDL 잠금, schema epoch, 적용 순서가 정의되지 않는다
- 영향 대상: 장기 사용자, 애플리케이션, 복제 정합성

### 문제
키 변경 전에 시작한 트랜잭션이 변경 후 커밋할 수 있는지, DDL이 얼마나 기다리는지, replica lag가 큰 경우 옛 로그를 어느 스키마로 적용하는지 없다. 짧은 기능 시험으로는 드러나지 않는 운영 경계다.

### 왜 중요한가
배치 작업은 수시간 열린 트랜잭션을 가질 수 있다. DDL이 이를 무기한 기다리면 서비스가 멈추고, 기다리지 않고 키를 바꾸면 옛 로그 적용이 실패할 수 있다. timeout과 재시도도 사용자 계약이어야 한다.

### 재현 또는 구체적 예제

```sql
-- 세션 A: 대량 배치, 아직 COMMIT 전
UPDATE ledger SET status='CLOSED' WHERE business_date='2026-08-21';
-- 세션 B
ALTER TABLE ledger DROP PRIMARY KEY,
  ADD CONSTRAINT pk_ledger_ref PRIMARY KEY(reference_no);
```

replica가 30분 지연된 상태에서 세션 A가 DDL 후 커밋하는 최악 순서를 가정한다. 기대 동작은 대기·거부·세대 로그 중 하나로 명확해야 한다.

### 권고안
DDL 직렬화, 선행/후속 트랜잭션 경계, schema epoch 보존 기간과 lag 한계를 정의한다. 사전 명령으로 차단할 장기 트랜잭션과 예상 대기를 보여 주고 timeout은 전체 롤백과 재시도 가능 코드를 제공한다.

### 검증 방법
1초~수시간 모사 장기 트랜잭션과 다양한 lag에서 전환한다. 커밋 순서를 바꾸고 DDL timeout·취소·재시작을 시험하여 데이터 누락, 교착, 무한 대기, 세대 조기 삭제가 없는지 확인한다.

## [USER-10Y-10] 키 전환 중 failover의 최악 상태가 정의되지 않는다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 운영 중 키 변경과 6절의 failover 언급
- 사실/추론 구분: 확인이 필요한 질문 — DDL 전송·적용 중 승격 허용 조건과 old/new RK 복구 방식이 없다
- 영향 대상: 장기 사용자, 재해 복구, 데이터 정합성

### 문제
source가 새 RK를 커밋했지만 replica는 DDL을 절반 적용했거나 아직 받지 못한 시점에 source가 영구 손실될 수 있다. 새 primary가 옛 스키마로 계속 쓰는지, 승격을 거부하는지, DDL을 복구하는지 없다.

### 왜 중요한가
장애는 안전한 작업 창을 기다리지 않는다. 최악 상태에서 자동 failover가 가용성을 위해 정합성을 희생하면 복구가 더 어려워진다. 사용자는 RTO와 데이터 안전 중 제품이 무엇을 선택하는지 알아야 한다.

### 재현 또는 구체적 예제

```text
1. A가 PK(id)→UK(email) 전환 커밋
2. DDL 로그는 B에 도착했으나 새 인덱스 검증 중
3. A 스토리지 영구 장애
4. B 자동 승격 시도
```

기대 결과 후보는 B 승격 차단, DDL 복구 완료 후 승격, 옛 세대로 롤백 중 하나다. 원문은 선택하지 않는다.

### 권고안
RK 전환 상태별 failover 상태 머신과 승격 안전 조건을 명시한다. `PREPARED/COMMITTED/APPLIED` 같은 세대 상태, fencing, 재실행·롤백 가능성을 정의하고 자동 승격이 안전하지 않을 때 명확히 중단한다. 수동 복구 runbook도 제공한다.

### 검증 방법
DDL 로그 생성·전송·인덱스 생성·카탈로그 적용 각 지점에서 primary를 강제 종료한다. standby 승격 결과와 복구 시간을 측정하고, 최종 스키마·데이터·로그가 단일 세대로 수렴하는지 확인한다.

## [USER-10Y-11] HA 시작 검사와 노드 재가입 사이의 경쟁 조건이 빠졌다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절의 HA 실행 시 검사와 single에서 수정 후 재시작
- 사실/추론 구분: 확인된 사실 — 검사 스냅샷, DDL 차단, 복수 노드 검증, 재가입 조건이 없다
- 영향 대상: 장기 사용자, HA 자동화, 가용성

### 문제
HA 시작 검사가 source 한 곳만 보는지, 모든 노드 카탈로그를 비교하는지 없다. 검사와 활성화 사이에 DDL이 들어오거나 오래된 노드가 재가입하면 통과한 조건이 즉시 깨질 수 있다.

### 왜 중요한가
검사는 상태가 고정된 동안만 의미가 있다. 오래 격리된 노드가 옛 PK 정의로 돌아오면 현재 클러스터와 로그를 해석하지 못할 수 있다. 재가입은 단순 프로세스 시작이 아니라 세대 동기화 검증이어야 한다.

### 재현 또는 구체적 예제

```text
1. readiness 검사가 모든 ON 테이블의 RK를 확인
2. 검사 직후 다른 세션이 마지막 UK 삭제 시도
3. 오래된 standby C가 옛 카탈로그로 재가입
4. HA 활성화
```

기대 결과는 2가 전환 잠금 때문에 대기·거부되고, C는 스키마/RK 세대 동기화 전 로그 적용이나 승격 대상이 되지 않는 것이다.

### 권고안
일관된 카탈로그 스냅샷과 전환 잠금으로 readiness와 활성화를 원자적으로 연결한다. 재가입 시 버전, 로그 범위, 스키마/RK 세대, 데이터 기준점을 확인하고 불일치 노드는 재구축 절차로 보낸다.

### 검증 방법
검사 중 DDL 경쟁과 서로 다른 세대의 세 번째 노드 재가입을 반복한다. 위반 상태가 활성 클러스터에 들어오지 않고 출력이 정확한 객체와 수정 절차를 제공하는지 확인한다.

## [USER-10Y-12] RK 값 변경과 복합 문자열 키의 장기 비용 계약이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 1절의 PK/NOT NULL UK 자동 선택; DML로 RK 값 변경 및 키 크기 제한 없음
- 사실/추론 구분: 확인이 필요한 질문 — old/new 키 로그 이미지, 지원 크기와 성능 한계가 없다
- 영향 대상: 장기 사용자, 복제 정합성, 용량 계획, 애플리케이션

### 문제
활성 RK 컬럼 값 자체를 바꾸면 기존 행을 old 값으로 찾아야 할 가능성이 있지만 문서에 없다. 수백 바이트 복합 UK도 자동 선택될 수 있는데 로그 증가와 적용 지연에 대한 경고·한계가 없다.

### 왜 중요한가
새 값만 기록하면 replica에는 아직 새 주소가 없어 행을 찾지 못한다. old/new를 모두 기록하면 로그 크기가 증가한다. 데이터량이 매년 커지면 초기에는 괜찮던 복합 키가 장기적으로 네트워크와 보관 비용을 지배할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE catalog_item (
  tenant VARCHAR(100) NOT NULL,
  external_code VARCHAR(500) NOT NULL,
  body VARCHAR(2000),
  CONSTRAINT uq_item UNIQUE(tenant, external_code)
) REPLICATION = ON;

UPDATE catalog_item SET external_code='NEW' 
WHERE tenant='A' AND external_code='OLD';
```

기대 결과는 old 키로 한 행을 찾아 new 키로 바꾸고 중복 충돌 시 양 노드에서 전체 롤백하는 것이다.

### 권고안
old/new 이미지와 적용 순서, 최대 컬럼 수·바이트·지원 타입·collation을 정의한다. RK별 예상 로그 바이트와 경고를 조회하게 하고, 처리량·lag·로그 보존 비용의 지원 목표를 공개한다.

### 검증 방법
정수 PK와 2·4·8개 문자열 복합 UK에서 키 UPDATE·DELETE를 장기간 부하로 실행한다. 로그량, CPU, 네트워크, p95 lag, 복구 시간을 비교하고 키 교환·중복 충돌의 정합성을 검증한다.

## [USER-10Y-13] FK 그래프와 연쇄 동작이 ON/OFF 경계를 안전하게 다루지 못한다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식→OFF 부모 금지와 단순 CREATE/ALTER 예시
- 사실/추론 구분: 확인된 사실 — 반대 방향, 다단계·순환 FK, CASCADE/SET NULL, 옵션 변경 전파가 없다
- 영향 대상: 장기 사용자, 복잡한 스키마, 데이터 정합성

### 문제
오래된 DB는 수백 테이블의 FK 그래프와 연쇄 동작을 가진다. 직접 부모만 검사하면 중간 VIEW가 아니라 FK의 조부모, 순환 관계, OFF 자식의 CASCADE를 놓칠 수 있다. 기존 그래프에서 한 테이블을 OFF로 바꿀 때 영향 범위가 없다.

### 왜 중요한가
한 부모 DELETE가 여러 단계 자식을 삭제할 수 있다. 경로 중 OFF 테이블이 있으면 노드마다 파생 DML이 달라진다. 직접 관계만 안전해도 전체 트랜잭션 결과가 같다는 보장은 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (id INT PRIMARY KEY) REPLICATION = ON;
CREATE TABLE orders (
  id INT PRIMARY KEY, customer_id INT,
  FOREIGN KEY(customer_id) REFERENCES customer(id) ON DELETE CASCADE
) REPLICATION = ON;
CREATE TABLE local_note (
  id INT PRIMARY KEY, order_id INT,
  FOREIGN KEY(order_id) REFERENCES orders(id) ON DELETE CASCADE
) REPLICATION = OFF;
```

customer 삭제가 local_note까지 이어질 때 양 노드의 결과는 다를 수 있다. orders 또는 customer를 OFF로 바꾸는 ALTER의 처리도 없다.

### 권고안
FK 전체 그래프를 대상으로 부모/자식 ON/OFF와 referential action을 검증한다. CREATE/ALTER 시 영향 경로를 출력하고 금지 전이는 원자적으로 거부한다. 허용된 로컬 연쇄 동작은 노드별 차이를 명시하고 failback 정책과 연결한다.

### 검증 방법
다단계·분기·순환 FK 그래프에서 CASCADE/SET NULL/RESTRICT와 ON/OFF 전환을 시험한다. failover 후 모든 허용 경로의 제약 유효성과 예상 로컬 차이를 검사한다.

## [USER-10Y-14] OFF 의존 VIEW가 보안·정산 결과를 바꿀 위험을 과소평가한다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 6절의 VIEW 사용 제약 없음과 결과 불일치 면책
- 사실/추론 구분: 확인된 사실 — 쿼리 실행 가능성과 결과 정합성을 구분하지 않고 위험 VIEW 탐지 방법이 없다
- 영향 대상: 장기 사용자, 보안, 정산·보고서, 애플리케이션

### 문제
“제약이 없다”는 표현은 VIEW가 장애 조치 뒤에도 안전하다는 인상을 준다. OFF 테이블이 권한 필터, 가격표, 집계 기준에 쓰이면 결과 감소뿐 아니라 과다 노출과 잘못된 금액이 가능하다. 중첩 VIEW 의존성도 보이지 않는다.

### 왜 중요한가
VIEW 쿼리는 오류 없이 실행되므로 잘못된 결과가 오랫동안 발견되지 않을 수 있다. 장기 사용자에게는 문법적 가용성보다 결과의 의미와 감사 가능성이 중요하다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE orders (id INT PRIMARY KEY, region VARCHAR(10), amount INT) REPLICATION=ON;
CREATE TABLE local_acl (region VARCHAR(10) PRIMARY KEY) REPLICATION=OFF;
CREATE VIEW allowed_orders AS
  SELECT o.* FROM orders o WHERE NOT EXISTS (
    SELECT 1 FROM local_acl a WHERE a.region=o.region
  );
```

standby의 local_acl이 비어 있으면 failover 후 모든 주문이 노출될 수 있다. 단순 INNER JOIN의 빈 결과보다 더 위험하다.

### 권고안
문구를 “실행 가능하지만 결과 동등성은 보장하지 않음”으로 고친다. 직접·간접 OFF 의존 VIEW를 카탈로그와 readiness 보고서에 표시하고 보안·정산 태그가 있는 VIEW는 생성·전환을 차단하거나 명시 승인하게 한다.

### 검증 방법
INNER/LEFT/NOT EXISTS, 집계, 3단계 중첩 VIEW로 failover 전후 행 노출과 합계를 비교한다. 의존성 검사가 모두 탐지하고 승인 없는 위험 VIEW를 정책대로 거부하는지 확인한다.

## [USER-10Y-15] `fail_count`는 현재 위험과 과거 누적을 구분하지 못한다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체; 복제 실패의 지표 정의·노출·보존이 없음
- 사실/추론 구분: 확인된 사실 — 핵심 장애 징후인 `fail_count`의 사용자 계약이 없다
- 영향 대상: 장기 사용자, SRE, 감사, 장애 조치 승인

### 문제
누적 숫자 하나라면 같은 로그의 반복 재시도, 서로 다른 행 실패, 이미 해결된 과거 오류를 구분할 수 없다. 재시작·업그레이드 뒤 초기화 여부와 메트릭 버전 호환성도 없다.

### 왜 중요한가
failover 직전에는 현재 미해결 적용 오류가 있는지가 중요하다. 감사에는 과거 누적 이력이 필요하다. 두 목적을 섞으면 경보 피로 또는 위험한 정상 판단이 생긴다.

### 재현 또는 구체적 예제

```text
로그 L1이 100회 재시도되어 실패
로그 L2~L11이 각각 1회 실패
재시작 후 L1은 해결, L2~L11은 미해결
```

단일 `fail_count=110` 또는 재시작 후 0만으로 현재 위험을 알 수 없다.

### 권고안
누적 실패 이벤트, 고유 실패 로그, 현재 미해결 수, 가장 오래된 실패 시각과 backlog를 분리한다. 테이블·오류·RK 세대·로그 위치를 연결하고 보존·초기화·버전 변경 정책, 경보와 failover 차단 기준을 공개한다.

### 검증 방법
중복 재시도와 독립 실패를 혼합하고 재시작·업그레이드·복구한다. 각 지표가 정의대로 유지되며 현재 미해결 상태와 감사 이력을 모두 재구성할 수 있는지 확인한다.

## [USER-10Y-16] 데이터 교정의 정답·감사·재실행 모델이 없다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4·6절의 불일치 허용과 7절의 스키마 수정만 안내
- 사실/추론 구분: 확인된 사실 — 기존 데이터 차이를 어느 노드 기준으로 어떻게 교정하는지 없다
- 영향 대상: 장기 사용자, 데이터 소유자, 감사, 복제 정합성

### 문제
불일치를 발견해도 source가 항상 정답인지, failover 이력이 있으면 어느 시점이 정답인지 결정할 규칙이 없다. 온라인 쓰기 중 비교, 교정 DML의 재복제, 작업 중단 후 재실행, 수정 감사도 없다.

### 왜 중요한가
잘못된 사본으로 정상 데이터를 덮으면 복구 도구가 데이터 손실 도구가 된다. 금융·감사 데이터는 누가 어떤 근거로 어느 값을 선택했는지 보존해야 한다. 작업은 네트워크 실패 후 안전하게 재개돼야 한다.

### 재현 또는 구체적 예제
과거 failover 때문에 A에는 balance=100, B에는 balance=90이고, 외부 원장에는 110이라고 가정한다.

```sql
SELECT id, balance FROM account WHERE id=1;
```

현재 primary만 정답으로 택하면 두 값 모두 잘못될 수 있다. 기대 결과는 데이터 소유자의 승인과 변경 전후 증거를 남기는 것이다.

### 권고안
일관된 스냅샷, 정답 소스 선택, 외부 기준 확인, 쓰기 충돌 검출, 멱등 작업 ID, checkpoint, 변경 전후 감사, 승인·롤백 절차를 제품 runbook으로 제공한다. 불일치가 남으면 planned failover를 막는다.

### 검증 방법
행 누락·값 차이·양 노드 독립 변경을 만들고 교정 중 DML·네트워크 단절·프로세스 종료를 주입한다. 재개 후 최신 변경 손실 없이 수렴하고 감사 기록으로 모든 결정이 설명되는지 확인한다.

## [USER-10Y-17] unload/load의 상충 기본값은 대규모 이관을 위험하게 한다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 값이 없으면 ON, 9절 5항은 포함하지 않는 테이블은 OFF
- 사실/추론 구분: 확인된 사실 — 복제 필드가 없는 동일 입력에 반대 결과를 요구한다
- 영향 대상: 장기 사용자, 업그레이드·다운그레이드, 재해 복구

### 문제
구버전 파일의 무표기 테이블이 ON인지 OFF인지 결정되지 않았다. ON은 키 없는 테이블 때문에 HA 시작을 막고, OFF는 중요 데이터를 복제하지 않는다. 둘 다 자동 적용하기 위험하다.

### 왜 중요한가
대규모 이관은 수천 객체를 한 번에 바꾼다. load 성공만 확인하면 잘못된 데이터 보호 등급을 놓칠 수 있다. 이후 failover에서야 차이를 발견하면 원본 파일과 운영 변경을 다시 합치기 어렵다.

### 재현 또는 구체적 예제

```sql
-- 구버전 unload에 옵션 없이 존재
CREATE TABLE customer (id INT PRIMARY KEY);
CREATE TABLE raw_event (payload VARCHAR(1000));
```

모두 ON이면 raw_event가 readiness를 실패시키고, 모두 OFF이면 customer 데이터가 replica에 없다.

### 권고안
상충 문장을 정책 결정으로 해결한다. 무표기는 기본 자동 변환 대신 `--default-replication=ON|OFF|ERROR`와 table mapping 파일을 요구하고, dry-run에서 RK·FK·VIEW 영향과 예상 ON/OFF를 보고한다. 원본 메타데이터와 결정 기록을 보존한다.

### 검증 방법
여러 버전의 파일과 필드 없음/ON/OFF, RK/FK/VIEW 조합을 이관한다. dry-run과 실제 결과, readiness, failover 데이터가 일치하고 취소 후 원래 환경으로 되돌릴 수 있는지 검증한다.

## [USER-10Y-18] 롤링 업그레이드·다운그레이드와 성능 지원 수명이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 하위 버전 unload만 언급; 혼합 버전 노드·롤백·성능 기준 없음
- 사실/추론 구분: 확인이 필요한 질문 — 구버전 노드의 새 로그 해석과 기능 사용 시점이 정의되지 않는다
- 영향 대상: 장기 HA 사용자, 릴리스 관리자, 용량 계획

### 문제
한 노드씩 업그레이드할 때 새 `REPLICATION` DDL을 사용할 수 있는지, 구버전으로 롤백하면 메타데이터를 잃는지 없다. 복합 UK가 RK가 되며 늘어나는 로그량과 지연의 지원 기준도 없다.

### 왜 중요한가
혼합 버전에서 구버전 replica가 새 DDL을 무시하면 split-schema가 된다. 업그레이드 후 성능이 나빠져 롤백하려 해도 새 카탈로그를 구버전이 못 읽으면 복구 경로가 사라진다.

### 재현 또는 구체적 예제

```text
1. B를 신버전으로 업그레이드, A는 구버전 primary
2. B를 primary로 승격
3. REPLICATION=OFF 테이블과 긴 복합 UK 테이블 생성
4. 성능 문제로 A 버전으로 롤백 시도
```

각 단계의 허용 여부와 데이터 보존 결과가 없다.

### 권고안
N/N-1 capability 행렬, 기능 활성화 gate, 로그·카탈로그 최소 버전, 롤백 가능 지점을 정의한다. 비호환 노드가 있으면 새 DDL을 선제 거부한다. 키 크기별 TPS·로그량·p95 lag·recovery time의 지원 목표와 회귀 한계를 공개한다.

### 검증 방법
N/N-1 양방향 primary/replica, 중간 failover, 기능 사용 전후 롤백을 시험한다. 정수 PK와 긴 복합 UK 부하에서 기준 버전 대비 성능과 복구 시간을 측정하고 지원 한계를 넘으면 기능 활성화를 막는다.

## [USER-10Y-19] 예제가 규범 시험과 오류 계약으로 사용할 수 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~5절의 `OK`/`ERROR`, `...`, 후행 쉼표, 이름 없는 제약
- 사실/추론 구분: 확인된 사실 — 다수 예제는 독립 실행 불가하고 오류 코드·사후 상태가 없다
- 영향 대상: 장기 사용자, 자동화, 회귀 시험, 고객 지원

### 문제
문서 예제가 구현 수용 시험으로 쓰이지 못한다. 같은 `ERROR`가 마지막 RK 제거, 모드 제한, FK 위반을 모두 가리키고 실패 후 부분 변경 여부를 알려 주지 않는다. 장기 자동화가 메시지 문자열에 의존하게 된다.

### 왜 중요한가
안정된 오류 코드는 버전이 바뀌어도 도구가 재시도·중단·수정 안내를 결정하는 계약이다. 실행 가능한 예제는 문서와 구현이 어긋나는 것을 조기에 발견한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE tbl DROP CONSTRAINT ...,
  ADD CONSTRAINT ...;
ALTER TABLE local_tbl REPLICATION=ON;
```

첫 문장은 실행할 수 없고 둘째는 단순 ERROR만 예상한다. 원자성, SQLSTATE, 해결법을 검증할 수 없다.

### 권고안
각 예제를 setup/action/assert/cleanup으로 작성하고 모드, 활성 RK, 완전한 제약 이름, 오류 코드, 재시도 가능성, 사후 스키마를 넣는다. 문서 코드 블록을 지원 버전마다 CI에서 실행해 호환 계약으로 관리한다.

### 검증 방법
빈 DB에서 모든 예제를 자동 실행하고 출력·카탈로그·데이터를 assertion과 비교한다. 업그레이드 전후 안정된 오류 코드가 유지되며 자동화가 원인별로 올바르게 분기하는지 확인한다.

## [USER-10Y-20] 용어·상충 문장·오탈자를 관리할 변경 거버넌스가 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 5-1절 `CRATE TABLE`, 7절 “파일 리스트”, 8·9절 load 상충, single/SA/HA 전환 표현
- 사실/추론 구분: 확인된 사실 — 단순 오탈자와 정책 상충이 섞여 있으며 표준 용어와 결정 이력이 없다
- 영향 대상: 장기 사용자, 지원·교육·번역, 제품 유지보수

### 문제
`CRATE`, “재시작해아한다” 같은 철자 문제 외에 load 기본값과 모드 정의처럼 구현을 바꾸는 상충이 있다. 모두 단순 문서 교정으로 처리하면 실제 제품 정책이 어느 쪽인지 기록되지 않는다.

### 왜 중요한가
문서는 수년간 여러 버전과 번역본으로 복제된다. 정책 변경 이유와 적용 버전이 없으면 오래된 자동화와 새 서버의 결과가 달라져도 사용자가 원인을 찾지 못한다. HA 시작과 failover를 같은 “전환”으로 부르면 runbook도 잘못 적용된다.

### 재현 또는 구체적 예제

```text
non-HA server 실행 / standalone(SA) 작업 / HA 최초 시작 /
planned switchover / unplanned failover / failback
```

이 사건들은 잠금·복구·허용 SQL이 다르지만 원문에서 명확히 분리되지 않는다.

### 권고안
표준 용어집과 규범 문장 소유자를 지정하고, 상충은 decision record와 적용 버전·호환 영향으로 해결한다. SQL·오류 코드·모드 용어를 린트하고 문서 변경 시 구현 시험과 release note를 함께 요구한다. 오탈자는 즉시 교정하되 정책 변경과 구분한다.

### 검증 방법
문서 린트로 금지 용어·오탈자·상충 기본값을 검사한다. 각 버전 문서의 정책 표를 diff하고, 장기 사용자가 여섯 운영 사건에 맞는 runbook과 지원 버전을 정확히 찾을 수 있는지 사용성 시험한다.

## [USER-10Y-21] 복제 보호 수준 변경에 직무 분리와 정책 잠금이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-2절은 사용자가 ON/OFF를 변경한다고만 하고 권한·승인을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 장기 고객의 보안 거버넌스, 업무 원장, 감사

### 문제
테이블 owner, migration 계정, HA 운영자 중 누가 OFF와 RK 변경을 할 수 있는지 없다. 실행자와 승인자 분리, 핵심 테이블 정책 잠금, 비상 해제 절차도 미정이다.

### 왜 중요한가
OFF는 데이터 보호 등급을 낮추는 작업이다. 일반 ALTER 권한으로 가능하면 애플리케이션 팀이 DB 운영 승인 없이 failover 결과를 바꿀 수 있어 규제·감사 경계를 깨뜨린다.

### 재현 또는 구체적 예제
```sql
-- release 계정이 일반 ALTER 권한만 가졌다고 가정
ALTER TABLE settlement_ledger REPLICATION=OFF;
```
성공한다면 정산 원장이 standby에 남지 않는다. 권한 오류라면 어떤 역할과 승인 절차가 필요한지 알아야 한다.

### 권고안
조회·CREATE 지정·ON→OFF·OFF→ON·RK 변경을 별도 권한으로 나누고 critical table policy lock, two-person approval와 break-glass 감사를 지원한다.

### 검증 방법
역할별 계정과 정상·비상 승인 경로를 시험한다. 우회 불가, 감사 연계, 비상 권한 만료가 정책과 일치하는지 확인한다.

## [USER-10Y-22] 파티션의 상태 상속과 전역 유일성 계약이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1~4절은 일반 테이블만 설명하고 파티션 객체는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 대규모 장기 보관 데이터, 파티션 운영, 정합성

### 문제
대상 버전이 파티션을 지원한다면 ON/OFF와 RK가 부모/자식 중 어디에 귀속되는지, local unique key가 전체 RK가 되는지, attach/detach/exchange에서 정책이 유지되는지 없다.

### 왜 중요한가
수년치 데이터는 기간 파티션으로 관리될 수 있다. 한 파티션만 OFF이거나 파티션별 같은 id가 있으면 특정 기간 누락 또는 잘못된 행 적용이 발생한다.

### 재현 또는 구체적 예제
```sql
-- 실제 문법은 대상 CUBRID 버전 확인 필요
CREATE TABLE audit_event (event_month INT, id INT, payload VARCHAR(1000),
 PRIMARY KEY(event_month,id)) REPLICATION=ON;
```
오래된 파티션 교환과 신규 파티션 추가 때 상태·키가 무엇인지 없다.

### 권고안
지원 범위, global/local uniqueness, 상태 상속, 모든 파티션 DDL의 atomicity·failover 결과를 규정하고 파티션별 상태 조회를 제공한다.

### 검증 방법
다년치 파티션 추가·교환·분할 중 DML/failover를 수행한다. 모든 파티션 RK와 checksum이 계약대로인지 확인한다.

## [USER-10Y-23] bulk·TRUNCATE·직접 적재의 데이터 보호 등급이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 DDL/DML과 loaddb만 다루며 운영 중 대량 적재는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 대규모 이관, ETL, RPO

### 문제
bulk utility, `TRUNCATE`, direct-path에 해당하는 지원 기능이 row log를 생성하는지, ON/OFF를 따르는지, batch 중단 후 resume와 failover 경계가 없다.

### 왜 중요한가
대량 경로가 로그를 우회하면 ON 보장이 깨지고, 전량 logging은 로그 보관과 lag SLO를 압도할 수 있다. 장기 고객은 작업 전 데이터 보호 등급을 알아야 한다.

### 재현 또는 구체적 예제
5억 행 테이블을 TRUNCATE한 뒤 bulk reload 중 60%에서 source가 장애 난다. 새 primary가 이전 전체, 빈 테이블, 60% 중 무엇을 갖는지 없다.

### 권고안
도구별 HA-safe/conditional/unsupported 등급, logging·batch commit·resume token·필요 공간과 failover 금지 구간을 명시한다.

### 검증 방법
각 경로를 중단·재시작·failover하고 batch ID와 checksum, log량을 검증한다. 보호 등급과 실제 결과가 일치해야 한다.

## [USER-10Y-24] 온라인 RK 구축의 장기 SLO와 중단·재개 계약이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 3·4절은 키 추가를 해결책으로 제시하지만 대형 online 변경은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 24×7 서비스, 수십억 행 데이터, change window

### 문제
online index build 지원, delta catch-up, pause/resume, 최대 lock·lag·temporary space와 취소 후 cleanup이 없다.

### 왜 중요한가
수십억 행에 UK를 추가하는 동안 쓰기가 계속되면 변경분을 따로 따라잡아야 한다. 처리량이 부족하면 작업이 끝나지 않고 failover 준비도 악화된다.

### 재현 또는 구체적 예제
초당 3만 쓰기 중 20억 행 customer email UK를 구축한다. replica lag가 1시간을 넘을 때 자동 throttle, pause 또는 abort 중 어떤 동작인지 없다.

### 권고안
지원 online phase, progress/backlog, resource budget, SLO 기반 throttle, resumable 여부와 cutover/rollback 조건을 제품 계약으로 정한다.

### 검증 방법
실제 규모를 축소한 비례 부하에서 write rate를 변화시키고 pause/crash/restart를 주입한다. SLO와 복구 가능성을 확인한다.

## [USER-10Y-25] 병렬 apply의 성능 향상과 RK DDL 순서 보장의 교환 조건이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 DDL/DML 복제를 설명하지만 병렬 apply는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 고처리량 고객, apply lag, 데이터 정합성

### 문제
병렬 apply 지원 시 RK DDL이 전역/테이블 장벽인지, worker drain 동안 lag가 얼마나 늘 수 있는지, barrier timeout 시 무엇을 하는지 없다.

### 왜 중요한가
옛 키 UPDATE보다 새 RK DDL이 먼저 적용되면 행을 못 찾는다. 모든 worker를 멈추면 정확하지만 대형 transaction 때문에 장시간 정지할 수 있다.

### 재현 또는 구체적 예제
T1 id UPDATE, T2 id→email switch, T3 email UPDATE가 순서대로 commit되지만 worker는 T2를 먼저 끝낸다. 결과는 serial commit과 같아야 한다.

### 권고안
병렬 지원 범위, table/global barrier, drain timeout, lag SLO와 실패 시 promotion 차단을 명시한다.

### 검증 방법
worker 수와 transaction 시간을 무작위화해 serial reference와 checksum을 비교하고 barrier 중 lag를 측정한다.

## [USER-10Y-26] PITR과 로그 보관이 RK 변경 이력을 함께 보존한다는 보장이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 논리 unload/load만 다루고 PITR·로그 retention은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 재해 복구, 법정 보존, RPO/RTO

### 문제
PITR 지원 시 backup manifest가 RK version을 담는지, DDL과 후속 DML을 같은 기간 보관하는지, 중간 DDL만 만료되면 recovery가 차단되는지 없다.

### 왜 중요한가
id→email 변경 기록 없이 email DML만 재생할 수 없다. 복구가 성공으로 끝나도 목표 시점과 다른 데이터라면 더 위험하다.

### 재현 또는 구체적 예제
01시 backup, 02시 RK switch, 03시 DML, 04시 사고 후 03:30 복구를 한다. 02시 DDL이 없으면 03시 로그 해석이 불가능하다.

### 권고안
manifest의 schema/RK version, 공동 retention floor, required-log dry-run과 gap 시 새 baseline/full restore 조건을 명시한다.

### 검증 방법
여러 목표 시점 restore와 중간 DDL log 제거를 시험한다. 정상은 checksum 일치, gap은 부분 복구 없이 명확히 중단해야 한다.

## [USER-10Y-27] 물리 스토리지 snapshot의 일관성 보장 범위가 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load만 설명하고 storage snapshot은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: cloud·SAN backup 사용자, 재해 복구

### 문제
filesystem/storage snapshot을 지원하는지, data/catalog/log volume을 원자적으로 잡아야 하는지, standby snapshot 시 apply를 멈춰야 하는지 없다.

### 왜 중요한가
RK metadata는 새 상태인데 index page는 옛 상태인 snapshot을 복원하면 DB는 열려도 DML 적용이 실패할 수 있다.

### 재현 또는 구체적 예제
email UK build와 RK pointer switch 사이에 data와 log volume을 서로 다른 초에 snapshot한다. restore가 안전한지 없다.

### 권고안
지원 snapshot 유형, checkpoint/quiesce/freeze 순서, atomic volume group, standby apply pause와 restore validation을 정의한다.

### 검증 방법
RK DDL 각 phase의 crash/application-consistent snapshot을 복원해 catalog/index/log와 후속 apply를 검증한다.

## [USER-10Y-28] network partition에서 고객에게 보이는 안전 상태와 fencing 계약이 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4·7절은 정상 HA와 failover만 설명하고 split-brain은 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 고객 서비스, 단일 writer, 데이터 복구

### 문제
분할 중 한쪽 write/DDL을 막는지, 사용자가 read-only/degraded를 어떻게 확인하는지, 강제 작업 후 재결합 계약이 없다.

### 왜 중요한가
양쪽이 서로 다른 RK/ON-OFF를 쓰면 자동 병합할 수 없다. 연결 성공만으로 정상으로 보이면 고객은 계속 업무 데이터를 생성한다.

### 재현 또는 구체적 예제
노드 A는 orders OFF, B는 RK switch를 수행한 뒤 각각 주문을 생성한다. 재결합 시 어느 history가 권위인지 없다.

### 권고안
quorum/fencing token, 분할 중 허용 읽기·쓰기·DDL, 사용자 상태 코드, 권위 노드 결정과 반대 노드 rebuild를 명시한다.

### 검증 방법
client/heartbeat/replication network 단절 조합에서 양쪽 업무를 시도한다. 한쪽이 차단되고 상태가 명확히 노출되는지 본다.

## [USER-10Y-29] 다중 standby와 원격 DR에서 승격 후보의 RK 안전 조건이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 master/slave 한 쌍만 가정한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 엔터프라이즈 다중 노드, 원격 DR, 승격 정책

### 문제
대상 제품이 다중 standby/cascade를 지원한다면 일부 노드만 새 RK DDL을 적용했을 때 승격 후보를 어떻게 고르는지 없다.

### 왜 중요한가
lag가 가장 작은 노드라도 schema/RK version이 맞지 않으면 안전하지 않다. 원격 DR은 로그 보관·네트워크 지연 때문에 오래된 version일 수 있다.

### 재현 또는 구체적 예제
source→local standby→remote DR 중 local까지만 RK switch가 적용된 뒤 source와 local이 함께 장애 난다. remote 승격 허용 여부와 RPO가 없다.

### 권고안
지원 topology, node별 schema/RK version·barrier LSA, promotion eligibility와 full resync 조건을 규정한다.

### 검증 방법
각 hop을 지연·중단하고 다중 장애를 주입한다. 안전한 노드만 승격되고 재편입 후 전체 checksum이 같아지는지 확인한다.

## [USER-10Y-30] RK 지원 타입·collation의 버전 간 의미 변화 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 PK/NOT NULL UK만 규정하고 타입·비교 의미는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 다국어 데이터, JSON/LOB/실수 키, 장기 업그레이드

### 문제
floating, LOB, JSON 등 지원 타입, 최대 키 크기, collation version과 업그레이드 시 비교 의미 변화가 없다.

### 왜 중요한가
기존에 서로 다른 문자열이 새 collation에서 같아지면 UK rebuild가 실패한다. 큰/비결정적 타입은 로그 비용과 노드별 비교 결과를 바꿀 수 있다.

### 재현 또는 구체적 예제
```sql
CREATE TABLE identity (
  external_value DOUBLE NOT NULL UNIQUE,
  label VARCHAR(4000)
) REPLICATION=ON;
```
이 UK가 RK가 되는지와 버전 간 DOUBLE/문자 비교 안정성이 없다.

### 권고안
지원 타입·bytes·collation version 행렬, 비지원 오류와 upgrade 재검증 절차를 제공하고 immutable surrogate key를 권장한다.

### 검증 방법
경계값·다국어 corpus를 old/new version에서 비교해 uniqueness와 apply 결과를 확인한다.

## [USER-10Y-31] 기능 capability·라이선스·클러스터 활성화 조건이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 문서 전체가 기능이 항상 동일하게 활성화됐다고 가정한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 장기 고객 계약, edition, 배포 자동화

### 문제
버전·edition·license·feature flag에 차이가 있는지, 노드별 capability가 다를 때 HA가 시작되는지 없다. 차이가 없다면 그 사실도 계약으로 명시해야 한다.

### 왜 중요한가
source는 새 DDL을 허용하지만 standby가 기능을 모르면 apply가 중단된다. 구매/업그레이드 계획도 사용 가능 범위를 알아야 한다.

### 재현 또는 구체적 예제
source flag ON, standby OFF에서 `ALTER TABLE cache REPLICATION=OFF`를 실행한다고 하자. DDL 전 사전 차단이 필요한데 규칙이 없다.

### 권고안
capability matrix, cluster-wide enable gate, license 만료·설정 불일치 동작과 사전 진단을 제공한다.

### 검증 방법
지원·불일치 조합에서 HA start/DDL/failover를 시험한다. 부분 적용 전에 차단되는지 확인한다.

## [USER-10Y-32] 파생·임시·시스템 객체의 장기 정책 범위가 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 2-1·7절은 모든 테이블처럼 표현하며 객체 유형별 예외는 누락한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 도구·임시 작업, schema lifecycle, HA 검사

### 문제
대상 버전의 `CREATE LIKE/AS SELECT`, 임시 table, system/tool 내부 table이 상태를 상속하는지, 기본 ON과 HA 검사 대상인지 없다.

### 왜 중요한가
임시 객체가 HA 시작을 막거나 OFF 원본 복사본이 기본 ON이 되면 수년에 걸친 자동화가 환경별로 달라진다.

### 재현 또는 구체적 예제
```sql
-- 정확한 지원 문법은 확인 필요
CREATE TABLE archive LIKE orders;
```
archive의 제약·ON/OFF와 RK, 임시 staging의 검사 포함 여부가 불명확하다.

### 권고안
지원 객체/파생 문법별 상속·기본값·복제·검사 범위를 표로 고정하고 unknown 도구에는 명시 옵션을 요구한다.

### 검증 방법
지원 객체와 파생 생성 round-trip을 old/new version에서 실행한다. 상태가 보존되고 예외 객체가 정확히 검사되는지 확인한다.

## [USER-10Y-33] 반복 실패 노드의 지원 상태와 고객 통지 기준이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 전체에 반복 apply 실패·재시작·격리와 고객 통지가 없음
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 장기 고객 운영, 지원 SLA, promotion readiness

### 문제
같은 오류의 retry budget, node quarantine, promotion eligibility, support escalation과 고객에게 degraded 상태를 알릴 기준이 없다.

### 왜 중요한가
프로세스가 살아 있어도 한 로그에서 멈춰 있으면 실질적인 HA가 아니다. 단순 restart로 알람이 사라지면 고객은 보호가 복구됐다고 오해한다.

### 재현 또는 구체적 예제
row-not-found가 1시간 반복되고 apply restart 후 다시 같은 LSA에서 멈춘다. 서비스는 계속되지만 standby는 승격 불가다.

### 권고안
오류별 retry/backoff, fatal barrier, quarantine와 `promotion_ready` 상태, SLA별 통지·지원 escalation·resync 조건을 명시한다.

### 검증 방법
일시/영구 오류와 restart를 주입한다. 상태·경보·지원 통지가 기준대로 변하고 resync 후에만 정상으로 돌아오는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 13개
- 최종 리뷰 항목 수: 33개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·bulk/online DDL·병렬 apply·PITR·물리 snapshot·다중 standby·파생/임시 객체 지원 여부와 정확한 문법, RK 지원 타입/collation version, 실제 fencing·capability·라이선스·고객 통지 구현
