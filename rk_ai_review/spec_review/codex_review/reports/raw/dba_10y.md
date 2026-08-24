# DB 엔지니어/DBA / 10년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 장기 운영 불변식, 무중단 변경과 롤링 업그레이드, 최악 장애에서의 복구 가능성, 대규모 데이터·조직의 감사 및 자동화 관점에서 검토했다.
- 확인하지 못한 전제: 실제 로그 레코드와 카탈로그 버전, DDL 트랜잭션 모델, 복제 적용기의 재시도·격리 정책, `fail_count` 구현, 백업 및 PITR 지원 범위, 공식 혼합 버전 정책은 원문만으로 확인할 수 없다.

## 컨셉·문제 정의·대안 (3개)

## [DBA-10년차-01] RK 존재만으로는 복제의 행 식별 불변식이 완성되지 않는다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절은 ON 테이블에 PK 또는 NOT NULL UK 중 하나의 RK가 필요하다고 하고, 4절은 운영 중 후보가 하나 이상 남도록 제한한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 복제 정합성, DBA, 장애 복구

### 문제
문서는 현재 스키마에 RK가 존재한다는 정적 조건만 보장한다. 이미 만들어진 로그를 해석하는 동안 해당 RK의 정의와 비교 의미가 보존된다는 시간축 불변식은 없다. 이름, 타입, collation, 구성 컬럼 또는 선택 RK가 바뀌면 “후보가 하나 있다”와 “과거 로그로 같은 행을 찾을 수 있다”는 서로 다른 조건이다.

### 왜 중요한가
복제 지연은 정상 운영에서도 발생한다. source는 새 키로 넘어갔지만 standby는 구 키를 쓰는 로그를 아직 처리할 수 있다. 구 정의가 사라지면 유일한 현재 키가 있어도 과거 UPDATE/DELETE가 적용되지 않는다.

### 재현 또는 구체적 예제
standby 적용을 중지한 뒤 구 RK를 사용하는 DML을 쌓고 RK를 교체한다.

```sql
CREATE TABLE ledger (
  id BIGINT PRIMARY KEY,
  external_ref VARCHAR(80) NOT NULL UNIQUE,
  amount NUMERIC(18,2)
) REPLICATION = ON;
UPDATE ledger SET amount=1200 WHERE id=42;
ALTER TABLE ledger DROP PRIMARY KEY;
```

PK가 제거된 뒤 UK가 현재 RK가 되더라도 앞선 로그가 `id=42`를 요구할 수 있다. 기대 결과는 구 로그의 적용이 끝날 때까지 구 RK 의미를 유지하거나, 로그 자체가 독립적으로 행을 식별하게 하는 것이다.

### 권고안
“각 미적용 DML 로그는 생성 당시의 RK 버전으로 정확히 한 행을 식별할 수 있다”를 핵심 불변식으로 명시한다. 로그에 RK 버전·구 키 값을 기록하고, 구 버전의 안전한 폐기 조건을 모든 standby의 적용 위치와 연결한다.

### 검증 방법
복제 지연 시간을 0초부터 수 시간까지 바꾸며 키 이름·타입·구성을 변경한다. 모든 과거 로그 적용 완료 후 양 노드의 행 체크섬과 `fail_count`가 일치하는지 확인한다.

## [DBA-10년차-02] 후보 자동 선택은 운영 제어권과 장기 안정성을 약화한다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절은 PK 우선, PK가 없으면 여러 NOT NULL UK 중 엔진이 하나를 선택한다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 성능, 장기 호환성

### 문제
DBA가 RK를 직접 지정하거나 고정하는 방법이 없다. 엔진 버전, 카탈로그 재구축, unload/load가 선택 순서를 바꾸면 같은 스키마에서 RK가 달라질 수 있다. 짧은 정수 UK 대신 긴 복합 문자열 UK가 선택돼 로그와 인덱스 비용이 급증할 수도 있다.

### 왜 중요한가
RK는 단순한 내부 최적화가 아니라 로그 형식, 성능, 복구 가능성을 좌우한다. 장기 운영에서는 우연한 선언 순서를 시스템 계약으로 쓰기보다 의도를 영속적으로 기록해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE subscriber (
  tenant_id INT NOT NULL,
  local_id BIGINT NOT NULL UNIQUE,
  country VARCHAR(40) NOT NULL,
  email VARCHAR(320) NOT NULL,
  UNIQUE(country, email)
) REPLICATION = ON;
```

`local_id`와 `(country,email)` 모두 후보다. 후자가 선택되면 UPDATE마다 훨씬 큰 키를 기록할 수 있지만 어떤 키가 선택되고 영구 고정되는지 알 수 없다.

### 권고안
명시적 `REPLICATION KEY (local_id)` 또는 제약 이름 지정 문법을 제공하고, 자동 선택은 신규 사용 편의용 기본값으로만 둔다. 선택 결과를 카탈로그에 영속화하고 변경을 별도 감사 가능한 DDL로 처리한다.

### 검증 방법
동일 스키마를 생성 순서 변경, 재시작, unload/load, 메이저 버전 업그레이드로 반복 생성한다. 명시 RK는 항상 동일하고 자동 선택은 문서화된 규칙대로 결정되는지 검사한다.

## [DBA-10년차-03] OFF는 복제 정책이 아니라 데이터 소유권 모델로 정의해야 한다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절·6절은 OFF 데이터 불일치를 책임지지 않으며 DDL만 복제한다고 한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, 애플리케이션, failover, 규제·감사

### 문제
OFF를 단순히 “DML을 보내지 않음”으로 정의해 노드별 데이터의 소유자, 수명 주기, 백업, 보안 삭제, 승격 후 처리 책임이 비어 있다. DDL이 모든 노드에 있으므로 사용자는 테이블을 HA 보호 대상으로 오인하기 쉽다.

### 왜 중요한가
노드 로컬 데이터는 failover 시 사라지는 임시 데이터인지, 각 노드가 독립적으로 보존해야 하는 데이터인지에 따라 운영 절차가 완전히 다르다. 개인정보가 OFF 테이블에 있으면 복제는 안 돼도 각 노드 백업과 삭제 의무는 남는다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE local_session (
  token VARCHAR(100) PRIMARY KEY,
  user_id BIGINT,
  expires_at DATETIME
) REPLICATION = OFF;
INSERT INTO local_session VALUES ('T1', 7, DATETIME '2026-08-23 00:00:00');
```

failover 후 `T1`이 없어져도 정상인지, failback하면 다시 나타나도 되는지, backup에 포함되는지 알 수 없다.

### 권고안
OFF 테이블을 node-local 데이터로 명시하고 허용 용도와 금지 용도를 정한다. failover 시 초기화·재구축·폐기 중 하나의 정책을 테이블 속성으로 선택하게 하며 백업·감사 동작도 연결한다.

### 검증 방법
OFF 테이블에 데이터를 넣고 failover/failback, 전체 백업/복원, 노드 교체를 수행한다. 문서화된 수명 주기와 실제 행 존재 여부가 일치하는지 확인한다.

## 용어·기본값·사용자 계약 (2개)

## [DBA-10년차-04] ON/OFF와 “복제 가능·복제 중·정지” 상태가 혼합되어 있다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 1절은 HA 실행 여부를 `cubrid hb start`로 정의하고 2절은 ON을 복제 테이블이라고 부르며 3절은 single/SA를 함께 언급한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 자동화 도구, 사용자

### 문제
ON은 정책 속성인지 현재 복제 상태인지 구분되지 않는다. single에서 ON 테이블은 실제로 복제되지 않지만 “복제 테이블”이라고 불린다. HA 프로세스가 실행 중이나 apply가 중지된 상태도 표현할 수 없다.

### 왜 중요한가
구성 의도와 실행 상태를 같은 단어로 부르면 모니터링이 거짓 정상 상태를 낼 수 있다. ON이더라도 standby 연결 끊김이나 apply 정지로 보호되지 않을 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE payment (id BIGINT PRIMARY KEY, amount INT) REPLICATION = ON;
SELECT class_name, replication FROM db_class WHERE class_name='payment';
```

single, HA 정상, HA apply 정지 세 환경 모두 `ON`일 수 있다. 기대 계약은 정책 `configured=ON`과 실행 상태 `ACTIVE/LAGGING/STOPPED`를 별도로 보여 주는 것이다.

### 권고안
`REPLICATION`은 테이블의 정책임을 명시하고, 클러스터 모드·노드 역할·전송/apply 상태를 별도 용어와 조회 항목으로 정의한다. single, SA, HA의 정확한 범위와 상태 전이를 표로 제공한다.

### 검증 방법
서비스 시작, apply 일시정지, 네트워크 단절, 재개 순서로 상태를 바꾸고 정책 값은 유지되며 런타임 상태만 정확히 변하는지 확인한다.

## [DBA-10년차-05] 생략 시 ON이라는 계약에 업그레이드 기준 시점이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 2-1절은 생략 시 ON이며, 8절은 구버전 파일의 누락 필드를 ON으로 보고, 9절 요약은 누락 시 OFF라고 상충되게 적는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 기존 고객, DBA, HA 기동

### 문제
새 CREATE의 기본값, 기존 카탈로그 마이그레이션 기본값, 구버전 unload 파일의 기본값이 구분되지 않았다. 특히 8절과 9절은 반대 결과를 규정한다.

### 왜 중요한가
같은 “값 없음”이라도 신규 SQL 생략, 오래된 메타데이터, 손상된 파일은 다른 상황이다. 무조건 ON이면 HA 시작 실패가 발생하고, 무조건 OFF이면 보호되어야 할 데이터가 조용히 미복제될 수 있다.

### 재현 또는 구체적 예제

```sql
-- 구버전에서 생성되어 새 속성이 없는 테이블
CREATE TABLE historical_order (id BIGINT PRIMARY KEY, amount INT);
-- 업그레이드 또는 loaddb 후
SELECT replication FROM db_class WHERE class_name='historical_order';
```

업그레이드 경로와 load 경로에서 같은 값이 나와야 하는지조차 정의되지 않았다.

### 권고안
신규 생성, in-place catalog upgrade, legacy load 세 경우를 분리해 정책을 결정한다. 모호한 입력은 명령 옵션으로 명시하게 하고 변환 보고서와 rollback 가능한 사전 검사를 제공한다. 8절과 9절 충돌은 공개 전 해소한다.

### 검증 방법
PK 있음/없음과 legacy/new 형식을 조합한 migration matrix를 만든다. 각 경로의 값, 경고, HA 시작 여부가 정책표와 일치하는지 확인한다.

## SQL 문법과 상태 전이 (3개)

## [DBA-10년차-06] ON에서 OFF로 바꾸는 순간의 일관성 경계가 정의되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절은 HA 중 `ALTER TABLE ... REPLICATION=OFF`를 허용하고 4절은 OFF의 DML만 복제하지 않는다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, DBA, 애플리케이션

### 문제
ALTER 커밋 전후의 동시 DML 중 어디까지 전달되는지, standby가 OFF 전환 DDL보다 앞선 DML을 모두 적용한 뒤 멈추는지 없다. 전환 직전 backlog가 버려지면 문서가 말하지 않은 시점부터 불일치한다.

### 왜 중요한가
정책 전환에는 명확한 cutover 지점이 필요하다. 그 지점이 없으면 장애 조사 때 어느 트랜잭션까지 standby에 존재해야 하는지 증명할 수 없다.

### 재현 또는 구체적 예제

```sql
-- 세션 A
UPDATE inventory SET qty=qty-1 WHERE id=1;
COMMIT;
-- 세션 B, 거의 동시에
ALTER TABLE inventory REPLICATION=OFF;
-- 세션 C
UPDATE inventory SET qty=qty-1 WHERE id=1;
COMMIT;
```

기대 결과는 A는 반드시 적용되고 C는 반드시 제외되며, ALTER 로그가 둘의 경계를 형성하는 것이다. 현재 문서에는 경계가 없다.

### 권고안
OFF 전환을 로그 순서상의 barrier로 정의하고 barrier 이전 DML이 모든 필수 standby에 적용됐는지 선택적으로 대기하는 `DRAIN` 동작을 제공한다. 즉시 전환 시 남은 backlog 처리 규칙도 명시한다.

### 검증 방법
대량 backlog와 동시 DML 중 ON→OFF를 반복한다. 전환 LSA를 기록하고 그 이전 로그는 모두 존재하며 이후 로그는 모두 제외되는지 행 단위로 검사한다.

## [DBA-10년차-07] HA에서 OFF→ON 금지는 재가입·초기 동기화 절차를 막는다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-2절과 4절은 HA 실행 중 OFF 테이블을 ON으로 변경할 수 없다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 가용성, 대형 테이블 운영

### 문제
정책 자체는 안전하지만 유일한 가이드가 single로 내린 뒤 변경하는 것이라면 클러스터 전체 중단을 요구할 수 있다. OFF 기간 동안 벌어진 데이터 차이를 어떤 snapshot으로 채우고 어느 로그 위치부터 가입할지도 없다.

### 왜 중요한가
수 TB 테이블을 ON으로 되돌릴 때 단순 ALTER만으로는 기존 행이 standby에 생기지 않는다. 초기 복사와 이후 변경 포착을 연결하지 않으면 복사 도중 변경이 누락된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE archive (id BIGINT PRIMARY KEY, body VARCHAR(4000)) REPLICATION=OFF;
-- source에 10억 행이 축적된 뒤
ALTER TABLE archive REPLICATION=ON;
```

HA에서는 거부되지만 single로 전환 후 성공했을 때 standby 기존 데이터가 어떻게 채워지는지 불명확하다.

### 권고안
온라인 재가입 기능이 범위 밖이면 전체 중지, consistent backup/restore, ON 변경, 검증, HA 재시작 순서를 명시한다. 장기적으로 snapshot copy와 change capture를 결합한 온라인 절차를 설계한다.

### 검증 방법
쓰기 부하가 있는 대형 OFF 테이블을 문서 절차로 ON 전환한다. 기준 snapshot 이후 DML까지 포함해 체크섬이 같고 failover 읽기가 완전한지 확인한다.

## [DBA-10년차-08] 복합 ALTER의 실행 계획과 rollback 보장이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13은 키 DROP과 ADD를 한 SQL로 수행하면 된다고 한다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 복제 정합성, 장기 복구

### 문제
새 키 사전 검증, 인덱스 구축, 구 키 제거, 카탈로그와 로그 커밋 순서가 없다. ADD가 데이터 중복이나 디스크 부족으로 실패하거나 서버가 죽었을 때 구 키가 복구되는지 알 수 없다.

### 왜 중요한가
대형 테이블의 인덱스 구축은 수 시간 걸릴 수 있으며 장애 가능성이 현실적이다. 중간 상태에서 RK가 0개거나 노드별로 다른 키가 되면 쓰기를 안전하게 계속할 수 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE device (id BIGINT PRIMARY KEY, serial VARCHAR(100), state INT) REPLICATION=ON;
INSERT INTO device VALUES (1,'DUP',0),(2,'DUP',0);
ALTER TABLE device DROP PRIMARY KEY,
  ADD CONSTRAINT uk_device_serial UNIQUE(serial);
```

새 UK가 실패할 때 기대 결과는 구 PK/RK가 완전 보존되는 것이다. 디스크 full 또는 crash도 동일한 원자성을 보여야 한다.

### 권고안
검증·shadow index 구축 후 단일 commit으로 RK 포인터를 교체하고, 구 버전 로그 drain 전에는 구 인덱스를 폐기하지 않는 상태 기계를 명시한다. 각 단계의 재시작 복구 동작과 진행률 조회를 제공한다.

### 검증 방법
검증, 구축 50%, 카탈로그 교체 직전·직후에 장애를 주입한다. 재시작할 때 상태가 구 또는 신 중 하나로 수렴하고 데이터 변경이 계속 정확히 복제되는지 확인한다.

## HA·DDL/DML·failover 시나리오 (3개)

## [DBA-10년차-09] RK DDL과 DML의 전역 순서가 다중 standby에서 보장되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 모든 DDL이 standby로 복제된다고 하지만 DDL과 DML의 로그 순서·동시성을 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, 다중 standby, DBA

### 문제
각 standby가 서로 다른 지연 상태일 때 DDL과 DML을 동일한 직렬 순서로 적용하는지 없다. 병렬 apply가 있다면 동일 테이블 내 barrier가 필요하고, 지연 standby도 구 RK 메타데이터를 보존해야 한다.

### 왜 중요한가
한 standby는 최신인데 재해복구용 standby는 하루 늦을 수 있다. 빠른 노드를 기준으로 구 키를 폐기하면 느린 노드는 과거 로그를 더 이상 해석하지 못한다.

### 재현 또는 구체적 예제

```sql
UPDATE customer SET name='A' WHERE id=10;
ALTER TABLE customer DROP PRIMARY KEY,
  ADD CONSTRAINT uk_customer_email UNIQUE(email);
UPDATE customer SET name='B' WHERE email='a@example.com';
```

세 로그가 모든 standby에서 이 순서로 처리돼야 한다. 둘째 standby가 첫 UPDATE 이전에서 재개할 때도 구 RK가 필요하다.

### 권고안
테이블별 DDL barrier, RK schema epoch, 모든 등록 standby의 low-water mark를 정의한다. standby가 보존 한계를 넘게 지연되면 자동 재가입이 필요하다는 상태로 격리하고 경고한다.

### 검증 방법
standby 2개를 서로 다른 위치에서 정지하고 병렬 apply를 켠 채 위 작업을 실행한다. 재개 후 양 standby의 로그 순서, RK epoch, 데이터 checksum이 source와 같은지 확인한다.

## [DBA-10년차-10] 네트워크 분할과 양쪽 쓰기 후 병합 정책이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4~7절은 단일 master/slave 흐름과 failover만 설명하며 split-brain 또는 이전 master 재가입을 다루지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 데이터 정합성, failback

### 문제
네트워크 분할로 양 노드가 쓰기를 받으면 같은 RK에 서로 다른 값이 생길 수 있다. 이전 primary가 돌아왔을 때 어느 쪽이 권위 있는지, 자동 로그 재적용을 금지하는지 없다.

### 왜 중요한가
RK는 행을 찾을 뿐 충돌을 해결하지 않는다. 같은 계좌의 잔액이 양쪽에서 바뀌면 단순 재적용은 한쪽 변경을 덮어쓰거나 유일성 오류를 일으킨다.

### 재현 또는 구체적 예제

```sql
-- 분할 중 노드 A
UPDATE account SET balance=900 WHERE id=10;
-- 동시에 승격된 노드 B
UPDATE account SET balance=800 WHERE id=10;
```

네트워크 복구 후 두 변경의 결합 결과를 자동 결정할 수 없다. 기대 결과는 fencing으로 양쪽 쓰기를 예방하고, 실패하면 자동 재가입을 막아 수동 복구 대상으로 표시하는 것이다.

### 권고안
primary fencing 조건, epoch/term 검증, stale primary 쓰기 거부, 재가입 전 divergence 검사를 명시한다. 분기 발생 시 보존·비교·업무 소유자 결정·재동기화 runbook을 제공한다.

### 검증 방법
네트워크 분할과 강제 승격을 재현해 이전 primary 쓰기가 차단되는지 확인한다. fencing 실패를 시험한 경우 재연결 시 자동 apply가 아닌 격리와 명확한 진단이 발생하는지 검사한다.

## [DBA-10년차-11] failover 직전 커밋의 내구성 수준과 승격 기준이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5~7절은 failover 후 데이터 사용을 논하지만 커밋 확인과 standby 적용 위치의 관계를 정의하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 애플리케이션, DBA, 데이터 손실 허용치

### 문제
source가 COMMIT 성공을 반환한 직후 장애가 나면 새 primary에 그 트랜잭션이 반드시 있는지 없다. RK 변경 DDL이 커밋됐지만 DML은 미전송인 경우 같은 혼합 상태도 다뤄지지 않는다.

### 왜 중요한가
HA의 데이터 손실 허용치(RPO)를 알아야 금융·주문 시스템에서 사용할 수 있다. 비동기라면 일부 손실 가능성을 명시하고 승격 전 어느 로그 위치까지 기다릴지 결정해야 한다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE payment SET status='PAID' WHERE id=500;
COMMIT;
-- 클라이언트가 성공을 받은 직후 source 전원 차단 및 failover
```

새 primary가 `PAID`를 반환하는지 보장 범위가 없다. 기대 결과는 복제 모드별 RPO와 승격 시 데이터 유실 경고가 명확한 것이다.

### 권고안
commit acknowledgment 조건, 전송·flush·apply의 차이, 자동 승격 가능한 최소 위치를 정의한다. 데이터 손실 가능성이 있으면 마지막 안전 LSA와 유실 예상 범위를 운영자에게 표시한다.

### 검증 방법
commit 처리의 여러 지점에서 장애를 주입하고 새 primary 결과를 기록한다. 각 동기화 모드의 문서화된 RPO를 벗어난 성공 커밋 손실이 없는지 확인한다.

## 데이터 정합성·키·FK·VIEW (3개)

## [DBA-10년차-12] collation과 타입 변환이 RK 동일성을 깨뜨릴 수 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 NOT NULL UK를 RK로 인정하고 4-2절은 다른 후보가 있으면 모든 DDL을 허용한다고 하지만 타입·collation 변경은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 복제 정합성, DBA, 국제화 데이터

### 문제
문자열의 유일성과 비교 결과는 collation에 따라 달라질 수 있다. RK 컬럼 타입·길이·collation을 변경하면 source와 standby의 버전 또는 적용 시점 차이로 동일 값 비교가 달라질 수 있다.

### 왜 중요한가
예를 들어 대소문자를 같게 보는 규칙에서는 `A`와 `a`가 충돌하지만 구분하는 규칙에서는 서로 다른 행이다. 노드가 다르게 판단하면 UPDATE가 0행 또는 다른 행에 적용된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE login_name (
  name VARCHAR(100) NOT NULL UNIQUE,
  profile VARCHAR(100)
) REPLICATION=ON;
ALTER TABLE login_name CHANGE name name VARCHAR(200) COLLATE utf8_bin;
```

변경 전 collation과 `utf8_bin`의 유일성 의미가 다를 때 기존 값 검증, 과거 로그 비교 규칙, 혼합 버전 결과가 불명확하다.

### 권고안
RK 컬럼의 타입, charset, collation 변경을 별도 위험 DDL로 분류한다. 기존 값 전수 검증, schema epoch barrier, 모든 노드 동일 비교 라이브러리 확인 없이는 거부한다.

### 검증 방법
대소문자, 악센트, 다중 바이트 경계값을 넣고 collation/type 변경 전후 UPDATE·DELETE를 수행한다. 모든 노드가 같은 행 수와 키 충돌 결과를 내는지 확인한다.

## [DBA-10년차-13] FK 제약은 직접 참조만이 아니라 전체 그래프로 검증해야 한다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절과 7절은 ON 자식이 참조하는 테이블도 ON이어야 한다고 하지만 다단계·순환 FK와 전환 순서는 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 참조 무결성, DBA, HA 시작

### 문제
수백 테이블의 FK 그래프에서 한 중간 부모가 OFF가 되면 여러 하위 테이블이 간접 영향을 받을 수 있다. 순환 FK, self-reference, `ON DELETE/UPDATE CASCADE`와 ON→OFF 전환의 원자적 검증도 없다.

### 왜 중요한가
FK는 테이블 하나만 보고 안전성을 판단할 수 없다. 연쇄 동작은 여러 테이블을 바꾸므로 그래프 일부만 복제하면 standby 적용이 실패하거나 failover 후 고아 행이 생긴다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE orders (id INT PRIMARY KEY, customer_id INT,
  FOREIGN KEY(customer_id) REFERENCES customer(id)) REPLICATION=ON;
CREATE TABLE shipment (id INT PRIMARY KEY, order_id INT,
  FOREIGN KEY(order_id) REFERENCES orders(id)) REPLICATION=ON;
ALTER TABLE customer REPLICATION=OFF;
```

직접 자식 `orders`뿐 아니라 전체 의존 그래프를 고려해 ALTER가 거부돼야 한다. 현재 문서에는 ALTER 시점의 검증 범위가 명확하지 않다.

### 권고안
CREATE, ALTER, HA 시작에서 동일한 FK 그래프 검증기를 사용한다. 모든 ON 자식에서 도달하는 부모가 ON이어야 한다는 불변식과 CASCADE 조합별 정책, 위반 경로 전체 출력 형식을 규정한다.

### 검증 방법
체인, 다이아몬드, 순환, self-FK를 만들고 각 노드를 OFF로 전환한다. 안전하지 않은 모든 경로가 탐지되며 부분 DDL이 남지 않는지 확인한다.

## [DBA-10년차-14] VIEW 불일치 면책 대신 의존성 기반 승격 차단 정책이 필요하다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 6절은 OFF 테이블을 포함한 VIEW의 failover 결과 불일치를 복제 모듈이 책임지지 않는다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 사용자, 보고·의사결정 시스템

### 문제
VIEW는 중첩될 수 있고 업무상 중요한 보고서·권한 뷰의 기반이 된다. 단순 면책은 어떤 서비스가 불완전해지는지 운영자가 승격 전에 판단하도록 돕지 않는다.

### 왜 중요한가
OFF 테이블과 직접 JOIN하지 않아도 중첩 VIEW나 함수가 간접 참조할 수 있다. failover 후 오류 없이 다른 합계를 반환하면 탐지보다 잘못된 의사결정이 먼저 일어난다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE sales (id INT PRIMARY KEY, amount INT) REPLICATION=ON;
CREATE TABLE local_rate (id INT PRIMARY KEY, rate NUMERIC(8,4)) REPLICATION=OFF;
CREATE VIEW converted_sales AS
  SELECT s.id, s.amount*r.rate AS total FROM sales s JOIN local_rate r ON r.id=1;
CREATE VIEW daily_dashboard AS SELECT SUM(total) total FROM converted_sales;
```

standby의 `local_rate`가 없거나 다르면 `daily_dashboard`도 달라진다. 원문은 간접 의존성 표시나 승격 전 경고를 요구하지 않는다.

### 권고안
카탈로그 의존성 그래프에서 OFF에 도달하는 모든 VIEW를 표시하고 중요도 태그를 지원한다. 중요 VIEW가 영향받으면 자동 승격을 차단하거나 명시적 승인과 재구축 hook을 요구한다.

### 검증 방법
직접·3단계 중첩 VIEW를 만들고 OFF 상태를 변경한다. 영향 목록이 전이적으로 갱신되고 failover 도구가 설정된 정책대로 경고 또는 차단하는지 확인한다.

## 운영·오류·관측 가능성 (2개)

## [DBA-10년차-15] `fail_count`는 누적 숫자가 아니라 복구 상태 기계와 연결돼야 한다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체는 일반적인 `ERROR`만 제시하며 적용 실패, 재시도, 격리, `fail_count`와 데이터 상태의 관계를 정의하지 않는다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 모니터링, 복제 정합성

### 문제
카운터 하나로는 동일 로그의 반복 실패 1건과 서로 다른 1만 건 실패를 구분할 수 없다. 실패 후 다음 로그를 계속 적용하는지, 테이블만 격리하는지, 전체 apply를 멈추는지도 없다.

### 왜 중요한가
행 하나를 건너뛴 채 계속 진행하면 시스템은 가용해 보여도 데이터가 영구 분기한다. 반대로 모든 오류에 전체 apply를 멈추면 작은 문제 하나가 큰 장애가 된다. 운영자는 상태와 선택 결과를 알아야 한다.

### 재현 또는 구체적 예제

```sql
UPDATE inventory SET qty=5 WHERE id=100;
UPDATE inventory SET qty=6 WHERE id=101;
```

standby에 `id=100`이 없다고 가정한다. 첫 로그 실패 뒤 둘째 로그를 적용하는지, 첫 로그 재시도마다 카운터가 증가하는지 불명확하다.

### 권고안
오류 이벤트 ID, 원본 LSA, DB/테이블/RK, 최초·최근 시각, 재시도 횟수, 차단된 후속 범위를 기록한다. 상태를 `HEALTHY/RETRYING/QUARANTINED/STOPPED/REPAIRED`로 정의하고 카운터 초기화와 데이터 복구를 분리한다.

### 검증 방법
0행, 복수 행, UK 충돌, DDL 불일치를 주입한다. 각 오류가 고유 사건으로 기록되고 재시작 후 보존되며, 복구 전에는 정상 상태로 돌아가지 않는지 확인한다.

## [DBA-10년차-16] 불일치 검출·수리·감사 증적의 운영 인터페이스가 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4절과 6절은 데이터 불일치를 허용하거나 면책하고 7절은 스키마 조건만 검사한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 감사, 재해복구, 기존 고객

### 문제
기존 PK 변경 결함으로 이미 생긴 불일치를 이 기능이 발견하거나 고치지 않는다. 대형 테이블을 일관된 snapshot에서 비교하는 방법, 잘못된 노드 판단, 수리 중 쓰기 처리, 감사 기록이 없다.

### 왜 중요한가
새 보호 규칙이 배포돼도 과거 손상은 남는다. 검증 없이 standby를 승격하면 잠복 불일치가 실제 서비스 데이터가 된다. 단순 행 수 비교는 값 차이나 상쇄된 추가·누락을 찾지 못한다.

### 재현 또는 구체적 예제

```sql
-- source: (1,100), (2,200)
-- standby: (1,90), (3,210)으로 의도적으로 분기
SELECT MOD(id,1000) bucket, COUNT(*), SUM(amount)
FROM account GROUP BY MOD(id,1000);
```

두 노드의 전체 행 수와 총합이 우연히 같을 수도 있으므로 강한 범위 checksum과 상세 비교가 필요하다.

### 권고안
동일 snapshot LSA 기준의 범위 checksum, 차이 행 추출, 권위 노드 선택, 온라인 repair 또는 재-seed, 사후 재검증 절차를 제품 기능 또는 공식 runbook으로 제공한다. 누가 무엇을 고쳤는지 감사 로그를 남긴다.

### 검증 방법
누락·추가·값 변경·키 변경을 섞어 주입하고 대형 테이블에서 도구를 실행한다. 모든 차이를 검출하고 repair 뒤 강한 checksum이 일치하며 변경 이력이 보존되는지 확인한다.

## 호환성·백업/복원·성능·시험 (2개)

## [DBA-10년차-17] 롤링 업그레이드의 기능 협상과 되돌리기 경계가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절은 새 SQL·카탈로그 속성을, 8절은 새 unload 필드를 도입하지만 혼합 버전 HA를 설명하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 가용성, 업그레이드·다운그레이드

### 문제
신버전 source가 새 DDL 또는 RK 버전 로그를 만들면 구버전 standby가 해석할 수 있는지 없다. 한번 새 문법을 사용한 뒤 구버전으로 failback하거나 downgrade할 수 있는 경계도 없다.

### 왜 중요한가
롤링 업그레이드 중에는 버전이 섞인다. 읽을 수 없는 로그를 생성한 뒤에야 실패하면 standby가 복구 불가능하게 뒤처지고 롤백 경로까지 사라질 수 있다.

### 재현 또는 구체적 예제

```sql
-- 신버전 source, 구버전 standby인 기간
ALTER TABLE audit REPLICATION=OFF;
ALTER TABLE customer DROP PRIMARY KEY,
  ADD CONSTRAINT uk_customer_email UNIQUE(email);
```

두 DDL을 구버전이 거부·무시·오해하는지 불명확하다. 기대 결과는 클러스터 capability가 부족하면 source에서 실행 전 차단하는 것이다.

### 권고안
로그·카탈로그 feature version과 노드 capability 협상을 정의한다. 업그레이드 순서, 새 기능 활성화 gate, point-of-no-return, downgrade 전 검사, 구버전 standby 재-seed 조건을 표로 제공한다.

### 검증 방법
지원하는 모든 인접 버전 쌍에서 양방향 역할 조합으로 DDL/DML/backup/failover/failback을 수행한다. 미지원 기능은 로그 생성 전에 안정적으로 거부되는지 확인한다.

## [DBA-10년차-18] 백업·PITR·load에서 RK 세대와 적용 위치 보존 규칙이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load 시 ON/OFF만 저장하고 자동 RK 할당을 말하지만 백업, 시점 복구, RK 선택 보존은 없다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 재해복구, 백업·복원

### 문제
load가 RK를 다시 자동 선택하면 원본과 다른 RK가 될 수 있다. 물리 백업 복원 또는 PITR가 RK 교체 DDL의 중간 시점을 만나면 카탈로그·인덱스·로그 epoch를 함께 복구해야 하지만 규칙이 없다.

### 왜 중요한가
복원은 데이터만 되살리는 작업이 아니다. 이후 로그를 이어 적용하려면 복원 시점의 행 식별 규칙도 정확히 같아야 한다. 그렇지 않으면 recovery가 성공처럼 끝나도 데이터가 어긋날 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE person (
  email VARCHAR(100) NOT NULL UNIQUE,
  phone VARCHAR(30) NOT NULL UNIQUE
) REPLICATION=ON;
-- backup 후 RK 후보 생성 순서가 달라지는 unload/load 수행
```

복원 후 다른 UK가 RK가 되면 백업 이후 로그 적용 가능 여부가 불명확하다.

### 권고안
논리 dump에 ON/OFF뿐 아니라 선택 RK의 안정 식별자·컬럼 순서·schema epoch를 저장한다. 물리 백업/PITR는 카탈로그, 인덱스, 로그 위치를 원자 snapshot으로 복구하고 호환되지 않는 로그 연계를 거부한다.

### 검증 방법
RK 변경 직전·진행 중·직후 백업을 만들고 각 시점으로 PITR한다. 이어지는 DML 로그가 정확히 적용되고 원본과 RK 및 checksum이 같은지 확인한다.

## 문서 품질·예제·오탈자 (2개)

## [DBA-10년차-19] 오류 예제가 오류 계약과 자동화에 사용할 정보를 제공하지 않는다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2절·4절·5절의 다수 예제는 결과를 `ERROR` 또는 `OK`로만 표시하고 7절은 “파일 리스트”를 출력한다고 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 운영 자동화, 지원 조직

### 문제
오류 코드, SQLSTATE, 실패 객체, 위반 이유, 재시도 가능 여부가 없다. “파일 리스트”는 위반 대상이 테이블인데 무엇을 뜻하는지도 부정확하다.

### 왜 중요한가
대규모 운영은 메시지 문자열이 아니라 안정된 코드와 구조화된 필드로 자동 대응한다. 같은 `ERROR`라도 문법 오류, RK 부재, 잠금 타임아웃, 혼합 버전 불가는 조치가 다르다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY;
ALTER TABLE local_cache REPLICATION=ON;
```

HA에서 둘 다 `ERROR`일 수 있지만 첫째는 마지막 RK 제거, 둘째는 운영 중 OFF→ON 금지다. 자동화는 두 결과를 구별할 수 있어야 한다.

### 권고안
각 실패에 안정된 오류 코드, SQLSTATE, `owner.table`, 제약 이름, 현재/필요 RK, 모드, 권장 조치를 정의한다. HA 사전 검사에는 전체 위반 목록을 기계 판독 가능한 JSON 또는 고정 컬럼 형식으로 제공한다.

### 검증 방법
모든 실패 예제를 실행해 오류 코드의 유일성과 안정성을 확인한다. 메시지 언어를 바꿔도 자동화가 코드와 필드만으로 정확한 조치 분기를 하는지 시험한다.

## [DBA-10년차-20] 문서의 상충·오탈자와 실행 불가능 예제가 규범성을 훼손한다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 5-1절의 `CRATE TABLE`, 2-1절·5절 일부 SQL의 마지막 쉼표, 7절의 오탈자, 8절과 9절의 load 기본 처리 상충, Single/SA 용어 혼용.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 구현자, QA, DBA, 기술지원

### 문제
스펙은 구현과 시험의 공통 기준이어야 하지만 현재는 문법 오류와 서로 반대인 요구가 함께 있다. 여러 예제의 `ERROR`가 기능 규칙 때문인지 잘못된 SQL 때문인지 분리되지 않는다.

### 왜 중요한가
규범 문서가 모호하면 개발팀과 QA가 서로 다른 정답으로 구현·검증한다. 출시 후 고객 데이터에 영향을 주는 기본값을 문서 해석으로 결정하게 해서는 안 된다.

### 재현 또는 구체적 예제

```sql
-- 원문 예시 23과 같은 불필요한 마지막 쉼표
CREATE TABLE new_orders (
  order_id INT PRIMARY KEY,
);
```

이 SQL은 FK 정책에 도달하기 전에 문법 오류가 날 수 있다. 또 필드 없는 load는 8절에서는 ON, 9절에서는 OFF가 되어 하나의 예상 결과를 만들 수 없다.

### 권고안
규범 요구(`MUST/SHALL`), 설명, 비규범 예제를 구분한다. 모드별 상태 전이표와 오류표를 단일 출처로 두고 요약은 이를 참조하게 한다. 모든 SQL을 CI에서 실제 파싱·실행하며 `CRATE`, “재시작해아한다” 등을 교정한다.

### 검증 방법
문서 lint로 용어·요구 ID·상충을 검사하고 모든 코드 블록을 지정 버전 CUBRID에서 실행한다. 각 예제가 명시한 모드와 결과를 재현하며 상충 요구가 0건인지 독립 리뷰한다.

## [DBA-10년차-21] 복제 보호 등급을 바꿀 권한과 역할 분리가 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-1~2-2절은 사용자가 `REPLICATION=ON|OFF`를 생성·변경할 수 있다고 하지만 권한 모델은 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 보안 관리자, 애플리케이션 소유자, 재해복구 범위

### 문제
일반 ALTER 권한만 가진 계정이 ON을 OFF로 바꿀 수 있는지, 테이블 owner와 DBA 중 누가 승인하는지 없다. 기존 배포 계정이 새 옵션을 자동으로 사용할 수 있다면 의도치 않게 복제 보호를 해제할 수 있다.

### 왜 중요한가
ON→OFF는 컬럼 추가보다 위험이 크다. SQL은 정상 완료되지만 이후 데이터는 standby에 없으므로 사고가 failover 때 드러난다. 최소 권한과 이중 승인 없이 운영 실수나 계정 탈취가 데이터 보호 정책을 바꿀 수 있다.

### 재현 또는 구체적 예제

```sql
-- deploy_user는 orders의 일반 ALTER 권한만 보유한다고 가정
ALTER TABLE orders REPLICATION=OFF;
INSERT INTO orders VALUES (10001, 7000);
```

첫 명령의 허용 여부와 필요한 별도 권한이 정의되어야 한다.

### 권고안
CREATE 설정, ON→OFF, OFF→ON, 활성 RK에 영향을 주는 DDL을 권한 행렬로 구분한다. 보호 수준을 낮추는 작업에는 별도 `ALTER REPLICATION` 시스템 권한 또는 DBA 승인 정책을 요구하고 권한 위임·회수 절차를 문서화한다.

### 검증 방법
DBA, owner, ALTER-only, DML-only 계정으로 각 전이를 실행한다. 허용되지 않은 시도는 카탈로그·로그·데이터를 변경하지 않고 안정된 권한 오류를 반환하는지 확인한다.

## [DBA-10년차-22] RK와 REPLICATION 변경의 감사 타임라인이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-2절의 정책·키 변경과 2-3절의 현재 값 조회; 변경 이력은 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 감사, 사고 조사, 데이터 재동기화 범위

### 문제
현재 ON만 보고 과거에 잠시 OFF였는지, 활성 RK가 언제 바뀌었는지 알 수 없다. 사용자 DDL과 엔진 자동 재선택도 구분할 수 없다.

### 왜 중요한가
복제 누락 범위를 찾으려면 변경의 시작·종료 LSA와 수행 계정을 알아야 한다. 이력이 없으면 전체 테이블을 재동기화해야 하거나 원인을 증명하지 못한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer REPLICATION=OFF;
-- 여러 DML 수행 뒤
ALTER TABLE customer REPLICATION=ON;
```

현재 상태는 ON이지만 OFF 구간의 행은 standby에 없을 수 있다.

### 권고안
성공·실패·롤백된 정책/RK 변경에 이전값, 새값, 계정, client, transaction/LSA, 시각, 이유를 감사 이벤트로 남긴다. 보존 기간과 변경 불가능성, 조회 권한을 정의한다.

### 검증 방법
여러 계정과 도구로 전이를 반복한 뒤 감사 기록만으로 설정 타임라인과 잠재 누락 LSA 범위를 재구성한다. 재시작·백업 복원 뒤 보존 정책도 확인한다.

## [DBA-10년차-23] 파티션 테이블의 전역 유일성과 설정 상속 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 2-3절 `db_class` 출력에는 `partitioned`가 있지만 1~9절에 파티션 RK 규칙은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 파티션 제약과 DDL 지원 범위는 확인 필요
- 영향 대상: 대형 테이블 DBA, 복제 정합성, 파티션 운영 자동화

### 문제
부모와 개별 파티션 중 어디에 ON/OFF와 RK가 저장되는지, UK가 파티션 내부에서만 유일해도 RK가 될 수 있는지, 파티션 ADD/SPLIT/MERGE/EXCHANGE에 설정이 어떻게 전파되는지 없다.

### 왜 중요한가
서로 다른 파티션에 같은 키 값이 존재하면 로그가 partition identity 없이 정확한 행을 찾지 못할 수 있다. 파티션 교환은 대량 행을 DDL 하나로 옮기므로 일반 DML과 다른 복제 경계가 필요하다.

### 재현 또는 구체적 예제

```sql
-- 실제 파티션 문법은 해당 버전에서 확인 필요
CREATE TABLE sales (
  month_id INT NOT NULL,
  sale_id BIGINT NOT NULL,
  amount INT,
  UNIQUE(month_id, sale_id)
) REPLICATION=ON PARTITION BY RANGE(month_id) (...);
```

새 파티션이 자동 ON인지와 전역 RK가 `(month_id,sale_id)`인지 명확해야 한다.

### 권고안
지원 파티션 기능을 확인해 설정 저장 단위, global/local uniqueness, partition ID 로그 포함 여부, 각 파티션 DDL의 데이터·로그·잠금 결과를 상태표로 제공한다.

### 검증 방법
동일 키 값의 파티션 경계 사례와 모든 지원 파티션 DDL 중 DML·failover를 수행한다. 양 노드의 파티션 경계, 설정, 데이터 checksum이 같은지 확인한다.

## [DBA-10년차-24] UNIQUE 제약과 물리 인덱스 유지보수의 경계가 모호하다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절은 NOT NULL UK를 후보로 규정하지만 4-2절 예시 16은 `DROP INDEX`를 마지막 후보 삭제로 설명
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 인덱스 유지보수, optimizer, 복제 정합성

### 문제
독립 unique index가 RK 후보인지, UNIQUE constraint의 backing index만 후보인지 없다. 활성 RK 인덱스를 online rebuild, rename 또는 재작성하는 동안 논리 RK가 유지되는지도 설명하지 않는다.

### 왜 중요한가
DBA는 단편화와 성능 문제로 인덱스를 정기 재구축한다. 논리 제약이 유효해도 물리 인덱스 교체 중 복제 적용기의 행 검색 경로가 사라지면 apply가 중단될 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (id INT NOT NULL, v INT);
CREATE UNIQUE INDEX ux_t_id ON t(id);
ALTER TABLE t REPLICATION=ON;
DROP INDEX ux_t_id ON t;
```

각 명령의 후보 판단과 오류가 원문만으로는 결정되지 않는다.

### 권고안
RK 자격을 논리 constraint 기준인지 unique index 기준인지 확정한다. backing index rebuild/rename/drop, shadow index 교체와 통계 갱신 동안의 RK 가용성·잠금·apply 동작을 별도 운영 절차로 정한다.

### 검증 방법
PK backing index, UNIQUE constraint index, 독립 unique/non-unique index를 대상으로 rebuild·rename·drop을 수행한다. 동시 apply와 failover에서도 활성 RK가 정확히 한 행을 찾는지 확인한다.

## [DBA-10년차-25] 테이블·컬럼·제약 rename 후 과거 로그의 객체 연결이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 제약 ADD/DROP만 다루며 rename 상태 전이는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 복제 로그가 이름과 내부 ID 중 무엇을 참조하는지 확인 필요
- 영향 대상: 스키마 DBA, 복제 적용기, 감사·모니터링

### 문제
활성 RK 제약이나 구성 컬럼 이름을 바꿀 때 지연된 로그가 새 이름을 찾는지, 내부 identity가 보존되는지 없다. 테이블 rename 뒤 과거 오류·감사 이력이 같은 객체에 연결되는지도 불분명하다.

### 왜 중요한가
이름은 운영 중 변경 가능한 표시다. 이름을 row identity로 쓰면 정상적인 rename이 과거 로그 적용을 깨뜨리고 모니터링 이력을 분리한다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer RENAME COLUMN customer_id AS id;
ALTER TABLE customer RENAME CONSTRAINT pk_customer AS pk_customer_id;
```

rename 전 `customer_id=10` 로그가 지연돼 있다면 rename 후에도 같은 컬럼 ID로 적용돼야 한다.

### 권고안
지원 rename별 table/column/constraint ID 보존, schema epoch, 과거 로그와 감사 표시 이름을 정의한다. 내부 ID가 바뀌는 작업은 일반 rename이 아닌 원자적 RK 전환으로 처리한다.

### 검증 방법
apply를 중단하고 옛 이름 DML을 쌓은 뒤 각 rename을 수행한다. 재개 후 데이터, 객체 ID, 오류·감사 이력이 같은 객체로 연결되는지 확인한다.

## [DBA-10년차-26] ON/OFF 혼합 트랜잭션의 축소된 원자성 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절은 ON DML만 복제한다고 하지만 한 트랜잭션이 ON/OFF 양쪽을 변경하는 경우는 없음
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션, 트랜잭션 정합성, failover

### 문제
source에서 하나의 원자 커밋이 replica에서는 ON 부분만 남는다. 직접 DML뿐 아니라 trigger·procedure·FK 연쇄 동작으로 OFF 변경이 발생하는 경우도 동일한지 없다.

### 왜 중요한가
업무 불변식이 두 테이블에 걸쳐 있으면 failover 후 절반만 존재한다. 사용자는 OFF 불일치 면책만으로 트랜잭션 의미까지 축소된다는 사실을 알아채기 어렵다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE account SET balance=balance-100 WHERE id=1; -- ON
INSERT INTO local_outbox VALUES (51,'receipt');    -- OFF
COMMIT;
```

failover 뒤 잔액 차감은 있지만 outbox 작업은 없을 수 있다.

### 권고안
혼합 트랜잭션을 금지, 경고, 부분 복제 지원 중 하나로 결정한다. 허용한다면 replica 원자성 범위를 ON 변경으로 정의하고 의존 테이블·trigger를 사전 탐지하는 점검 기능을 제공한다.

### 검증 방법
직접·간접 혼합 DML을 commit/rollback/crash하고 failover한다. 문서의 원자성 범위대로 데이터가 남으며 위반 불변식을 readiness나 영향 분석이 탐지하는지 확인한다.

## [DBA-10년차-27] TRUNCATE와 고속 적재 경로의 ON/OFF 분류가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 DDL 전부와 ON “데이터”만 복제한다고 하지만 경계 명령은 분류하지 않음
- 사실/추론 구분: 확인이 필요한 질문 — `TRUNCATE`, loaddb 이외 bulk loader, `INSERT SELECT`의 실제 로그 경로는 확인 필요
- 영향 대상: 대량 이관 DBA, 로컬 데이터, 복제 정합성

### 문제
TRUNCATE가 DDL이면 OFF 테이블의 node-local 행도 모든 노드에서 삭제될 수 있고, DML이면 전송되지 않을 수 있다. 고속 load가 일반 row log를 우회한다면 ON 대상 데이터가 누락될 수 있다.

### 왜 중요한가
한 명령이 수억 행에 영향을 주므로 경계가 틀리면 대규모 불일치가 된다. 일반 INSERT 시험만으로 bulk path를 검증할 수 없다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache; -- OFF
INSERT INTO target_on SELECT * FROM staging_off;
```

첫 명령의 노드별 삭제 범위와 둘째의 결과 행 복제 여부가 정의되어야 한다.

### 권고안
TRUNCATE, bulk import, `INSERT SELECT`, direct path 등 지원 명령을 DDL/DML/특수 로그로 분류하고 ON/OFF source·target별 결과를 표로 제공한다. 고속 경로도 commit/RK 불변식을 우회하지 못하게 한다.

### 검증 방법
각 경로를 ON/OFF 조합에서 commit·rollback·crash하고 failover한다. 행 수·checksum과 OFF 로컬 행 보존이 명세와 같은지 확인한다.

## [DBA-10년차-28] RK 값 UPDATE의 old/new key 적용 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4-2절은 RK 제약 DDL을 다루지만 활성 RK 컬럼의 DML 변경은 없음
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 복제 정합성, 애플리케이션, DBA

### 문제
활성 RK 값을 변경하면 replica에는 아직 새 key 행이 없으므로 old key로 찾아야 할 수 있다. 로그가 old/new 중 무엇을 담는지, 같은 트랜잭션에서 두 행의 키를 교환할 때 순서를 어떻게 처리하는지 없다.

### 왜 중요한가
새 key만으로 검색하면 0행이고, 중간 unique 검사 순서가 다르면 source는 성공한 키 교환이 replica에서는 충돌할 수 있다. 제약 DDL을 제한해도 일상 DML로 문제가 발생한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parcel (
  tracking VARCHAR(50) NOT NULL UNIQUE,
  state VARCHAR(20)
) REPLICATION=ON;
UPDATE parcel SET tracking='NEW' WHERE tracking='OLD';
```

replica는 OLD로 한 행을 찾아 NEW로 바꾸고 중복 시 source와 같은 단위로 rollback해야 한다.

### 권고안
RK UPDATE 로그의 old key, new row/key image, 검색·유일성 검사·commit 순서를 정의한다. 복합 키 일부 변경, key swap, 재적용 멱등성도 포함한다.

### 검증 방법
단일·복합 RK 변경, 두 행 swap, 중복 충돌, rollback, 로그 중복 적용을 시험한다. 최종 행 수·키·`fail_count`가 양 노드에서 같은지 확인한다.

## [DBA-10년차-29] RK 후보 타입의 지원·금지 목록과 비교 안정성이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 NOT NULL UK면 RK 후보라고 일반화하고 타입 제한은 없음
- 사실/추론 구분: 확인이 필요한 질문 — floating, LOB, JSON, 객체형, 암호화 컬럼 등이 UNIQUE/RK로 실제 허용되는지는 버전 확인 필요
- 영향 대상: 데이터 모델링, 복제 로그 크기, 국제화, 업그레이드

### 문제
값의 바이트 표현이나 비교 의미가 버전·플랫폼에 따라 달라질 수 있는 타입을 RK로 허용할지 없다. 매우 긴 값은 로그와 인덱스 비용을 급증시키고, 비결정 비교는 다른 행을 찾을 수 있다.

### 왜 중요한가
“UNIQUE이면 안전”은 유일성 제약 생성 가능성과 복제용 안정 식별자 적합성을 혼동한다. RK는 직렬화, 비교, 버전 호환성까지 안정적이어야 한다.

### 재현 또는 구체적 예제

```sql
-- 실제 UNIQUE 지원 타입은 확인 필요
CREATE TABLE sample (
  external_value DOUBLE NOT NULL UNIQUE,
  payload VARCHAR(1000)
) REPLICATION=ON;
```

NaN, -0/+0, 정밀도 경계 값을 source/replica가 동일하게 찾는지 계약이 없다.

### 권고안
허용·금지 타입, 최대 RK 컬럼 수·바이트, collation·timezone·정밀도 조건을 공개한다. 위험 타입은 생성 시 거부하고 기존 DB 업그레이드에는 영향 목록과 대체 키 가이드를 제공한다.

### 검증 방법
지원 타입별 경계값을 직렬화·복제하고 서로 다른 지원 플랫폼·인접 버전에서 비교한다. 동일한 unique 충돌과 행 검색 결과를 내는지 확인한다.

## [DBA-10년차-30] 임시·시스템·세션 범위 객체의 검사 범위가 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문은 모든 “테이블”을 대상으로 표현하고 `db_class` 예시에는 system class 정보가 있지만 객체별 예외는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 temporary/global temporary/system object 지원과 사용자 변경 가능 범위 확인 필요
- 영향 대상: 관리 도구, 애플리케이션, HA readiness

### 문제
임시 테이블에 기본 ON을 적용하는지, RK가 없으면 HA에서 생성을 막는지, 시스템 테이블이 readiness에 포함되는지 없다. 세션 종료로 사라지는 객체가 HA 시작을 차단하면 운영 혼란이 생긴다.

### 왜 중요한가
비영구 객체와 영구 업무 테이블은 복구 목표가 다르다. 같은 규칙을 기계적으로 적용하면 불필요한 차단 또는 관리 데이터 누락이 발생한다.

### 재현 또는 구체적 예제

```sql
-- 실제 문법은 버전 확인 필요
CREATE TEMPORARY TABLE session_buffer (v INT) REPLICATION=ON;
```

옵션 자체 금지, RK 검사 면제, 일반 규칙 적용 중 무엇인지 정해야 한다.

### 권고안
일반·파티션·임시·시스템·가상 객체별 문법, 기본값, HA 검사, DDL/DML 복제, 백업 범위를 표로 제공한다. 미지원 조합은 구체 오류로 거부한다.

### 검증 방법
지원 객체 종류에 생략/ON/OFF와 RK 유무를 조합한다. 생성·세션 종료·HA 시작·failover·백업 결과가 범위표와 같은지 확인한다.

## [DBA-10년차-31] CTAS·LIKE·clone 경로가 설정을 보존하는지 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 일반 CREATE만 설명하며 테이블 복사 계열 SQL은 없음
- 사실/추론 구분: 확인이 필요한 질문 — `CREATE TABLE AS SELECT`, `LIKE`, clone 계열의 실제 지원 문법과 복사 범위는 확인 필요
- 영향 대상: 이관 DBA, schema tooling, HA 준비

### 문제
원본을 복사할 때 데이터만 복사되고 PK/UK가 빠지지만 REPLICATION은 기본 ON이 될 수 있다. 반대로 OFF가 조용히 ON으로 바뀌면 staging 데이터가 새로 복제된다.

### 왜 중요한가
운영자는 복사 SQL을 원본과 같은 보호 정책으로 오해하기 쉽다. 대량 작업 뒤 HA 시작 실패 또는 예상 밖 로그량이 발생할 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer_copy AS SELECT * FROM customer;
-- 실제 지원 시
CREATE TABLE customer_copy LIKE customer;
```

제약, ON/OFF, 활성 RK의 상속 여부가 문법별로 정해져야 한다.

### 권고안
지원 복사·clone 경로를 목록화해 스키마, 데이터, 제약, REPLICATION, 활성 RK의 복사 여부를 표로 만든다. 생략이 위험한 경우 명시 옵션 또는 경고를 요구한다.

### 검증 방법
ON/OFF × PK/UK/키 없음 원본을 각 방식으로 복사하고 새 객체의 카탈로그·데이터·readiness·복제 로그량을 비교한다.

## [DBA-10년차-32] OFF 데이터 백업의 노드 귀속과 복원 충돌 정책이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 1절·4절은 OFF 데이터가 노드마다 다를 수 있다고 하지만 8절은 논리 unload의 설정만 설명
- 사실/추론 구분: 확인이 필요한 질문 — standby에서 OFF 데이터 백업 가능 여부와 전체 백업의 node identity 저장은 확인 필요
- 영향 대상: 백업 DBA, 개인정보 관리, failback, 재해복구

### 문제
A와 B의 OFF 데이터가 다를 때 각 노드 백업을 어느 역할의 노드에 복원해야 하는지, B 백업을 A에 복원하면 로컬 데이터가 덮이는지 없다. 클러스터 전체 백업에서 OFF 사본을 하나만 보존할지도 불분명하다.

### 왜 중요한가
OFF는 복제되지 않아도 백업·보존·삭제 의무가 사라지지 않는다. node identity 없이 복원하면 오래된 session이나 작업 큐가 다른 노드에서 되살아날 수 있다.

### 재현 또는 구체적 예제

```text
A local_job: id 1,2
B local_job: id 3,4
A와 B에서 각각 full backup 후 B 장비를 A 백업으로 재구축
```

B가 1,2를 가져야 하는지 비워야 하는지 정책이 필요하다.

### 권고안
백업 세트에 cluster/node identity와 OFF table manifest를 기록한다. restore 시 동일 노드 복원, 폐기, merge 금지, 명시 import 중 하나를 선택하게 하고 개인정보 삭제·보존 정책과 연결한다.

### 검증 방법
노드별로 다른 OFF 행을 가진 백업을 교차 복원한다. 경고·차단·선택 결과가 정책과 같고 ON 데이터 복원과 혼동되지 않는지 확인한다.

## [DBA-10년차-33] standby 재구축 시 snapshot과 RK backlog 연결 절차가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절은 HA 시작 검사만, 8절은 unload/load만 다루며 손상 standby re-seed 절차는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 공식 standby 재구축 방식과 snapshot/log 연계 기능은 확인 필요
- 영향 대상: DBA, 복구 시간, 대형 데이터베이스

### 문제
불일치나 디스크 손상으로 standby를 다시 만들 때 어느 snapshot을 사용하고 어느 LSA부터 로그를 적용하는지, snapshot 중 RK 전환을 어떻게 처리하는지 없다.

### 왜 중요한가
수 TB 복사는 오래 걸린다. 복사 도중 키가 바뀌면 snapshot의 옛 카탈로그와 catch-up 로그의 새 세대를 모두 필요로 한다. 시작 LSA가 잘못되면 누락 또는 중복 적용이 생긴다.

### 재현 또는 구체적 예제

```text
T1: generation 5 snapshot 시작
T2: 대량 DML
T3: RK generation 6 전환
T4: snapshot copy 종료 후 standby catch-up
```

재구축 노드가 T1 기준 데이터와 T2~T4 로그를 정확히 연결해야 한다.

### 권고안
consistent snapshot LSA, 필요한 모든 RK epoch, catch-up retention 예약, 최종 checksum, 승격 eligibility를 포함한 공식 re-seed runbook을 제공한다. 예상 시간·공간과 중단 후 resume를 정의한다.

### 검증 방법
대형 부하와 여러 RK 전환 중 standby를 재구축하고 복사·catch-up 각 지점에서 중단한다. 재개 후 source와 checksum·schema epoch가 같고 승격 전 검증이 완료되는지 확인한다.

## [DBA-10년차-34] HA readiness 검사의 대규모 실행 비용과 일관성 경계가 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 7절은 HA 실행 시 전체 RK/FK 검사를 요구하지만 검사 snapshot, DDL 차단, 진행률, 비용은 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: 대규모 DBA, RTO, 배포 자동화

### 문제
수만 테이블과 큰 FK 그래프에서 검사가 얼마나 걸리는지, 첫 오류만 찾는지, 검사 중 DDL이 상태를 바꿀 수 있는지 없다. 장애 복구 중 예상 밖 장시간 검사는 RTO를 위반한다.

### 왜 중요한가
사전 검사는 통과와 활성화 사이 스키마가 바뀌지 않아야 유효하다. 모든 위반을 한 번에 찾지 못하면 수정·재시작을 반복하게 된다.

### 재현 또는 구체적 예제

```text
테이블 50,000개, FK 100,000개
검사 중 다른 세션이 마지막 UK 삭제 시도
위반 객체 5,000개 존재
```

진행률, memory 상한, 취소, 전체 출력과 DDL 경쟁 결과가 필요하다.

### 권고안
읽기 전용 dry-run과 시작 시 동일 검증기를 제공하고 일관된 catalog snapshot/transition lock으로 활성화를 연결한다. 병렬 검사, 자원 상한, 진행률, pagination·구조화 출력과 성능 목표를 정한다.

### 검증 방법
규모별 synthetic schema에서 시간·CPU·메모리·lock을 측정하고 검사 중 DDL을 경쟁시킨다. 모든 위반이 누락 없이 출력되고 통과 후 위반 상태가 활성화되지 않는지 확인한다.

## [DBA-10년차-35] schema diff와 관리 도구의 round-trip 계약이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-3절은 csql과 `db_class` 조회만 제공하며 드라이버·migration·schema diff 지원은 없음
- 사실/추론 구분: 확인이 필요한 질문 — JDBC/CCI 메타데이터와 각 관리 도구의 확장 계획은 확인 필요
- 영향 대상: DBA 자동화, CI/CD, schema drift 관리

### 문제
도구가 OFF 속성을 읽지 못하면 export/import 때 옵션을 생략해 기본 ON으로 바꿀 수 있다. 활성 RK 자동 선택 결과를 노출하지 않으면 diff가 실제 위험 변경을 놓치거나 매번 거짓 차이를 낼 수 있다.

### 왜 중요한가
대규모 조직은 DDL을 사람이 직접 실행하지 않고 desired schema와 실제 schema를 비교해 배포한다. round-trip이 깨지면 환경별 보호 정책이 조용히 달라진다.

### 재현 또는 구체적 예제

```text
1. 관리 도구가 local_cache(OFF)를 introspect
2. DR 연습 DB에 동일 schema 생성
3. REPLICATION 속성을 모르면 옵션 생략
4. 기본 ON과 RK 검사로 다른 결과
```

### 권고안
지원 드라이버·API별 ON/OFF, 활성 RK, 후보, generation 노출과 최소 버전을 정의한다. schema export→import→diff가 의미상 동일하다는 수용 시험과 구버전 도구의 명시 경고를 제공한다.

### 검증 방법
지원 csql/JDBC/CCI/관리 도구 경로로 다양한 테이블을 round-trip한다. 설정·제약·활성 RK 의미가 보존되고 구버전 도구가 조용히 기본값을 적용하지 않는지 확인한다.

## [DBA-10년차-36] cross-owner FK와 소유권 이전의 복제 정책이 없다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문 5절은 참조 테이블의 ON 여부만 검사하고 owner·권한·schema 경계는 없음
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 schema/owner 참조 및 소유권 변경 지원 문법은 버전 확인 필요
- 영향 대상: 다중 애플리케이션 DBA, 보안 경계, FK 정합성

### 문제
서로 다른 owner의 테이블이 FK로 연결될 때 한 팀이 자기 부모 테이블을 OFF로 바꾸거나 소유권을 이전하면 다른 팀의 ON 자식이 영향을 받는다. 누가 승인하고 오류에 어느 의존성을 노출할지 없다.

### 왜 중요한가
공유 DB에서 테이블 owner는 조직 경계다. 로컬 권한만 보고 ALTER를 허용하면 다른 서비스의 failover 안전성을 깨뜨릴 수 있고, 오류가 타 owner 객체명을 과도하게 노출할 수도 있다.

### 재현 또는 구체적 예제

```sql
-- app_a.customer를 app_b.orders가 참조한다고 가정
ALTER TABLE app_a.customer REPLICATION=OFF;
```

app_a 권한만으로 실행 가능한지, app_b 의존성 때문에 거부되는지 정의가 필요하다.

### 권고안
cross-owner dependency 변경의 승인·권한 행렬과 소유권 이전 시 재검증을 정의한다. 오류는 권한 범위 내에서 필요한 객체·담당 owner·요청 절차를 제공하고 감사 이벤트를 남긴다.

### 검증 방법
서로 다른 owner·role의 FK 그래프를 만들고 REPLICATION 변경, 소유권 이전, 권한 회수를 수행한다. 안전하지 않은 전이가 원자적으로 거부되고 정보 노출과 감사 기록이 정책에 맞는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 16개
- 최종 리뷰 항목 수: 36개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·temporary table·CTAS/LIKE·rename·bulk path 지원 문법, UNIQUE constraint와 index의 내부 결합, trigger/procedure 파생 DML, JDBC/CCI 및 관리 도구 메타데이터 확장, cross-owner 객체 권한, 물리 백업의 node identity와 공식 standby re-seed 구현은 코드·공식 제품 자료 확인이 필요하다.
