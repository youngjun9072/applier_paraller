# DB 엔지니어/DBA / 5년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 실제 HA 운영에서 사전 점검, 온라인 DDL, 잠금·성능, 장애 조치와 원복, 관측, 불일치 탐지·교정, 백업·복원 및 자동화가 안전하게 수행되는지를 중점 검토했다.
- 확인하지 못한 전제: 실제 CUBRID 복제 로그의 RK 저장 형식, DDL 트랜잭션·잠금 구현, `fail_count`의 공식 증가·초기화 규칙, 물리 백업과 unload 파일의 버전 호환 범위, 혼합 버전 HA 지원 범위는 원문만으로 확인할 수 없다. 아래 구현 관련 내용은 요구할 운영 계약 또는 검증 질문으로 구분했다.

## [DBA-5Y-01] “유효한 RK가 하나 존재”하는 것만으로 변경 누락 방지가 증명되지 않는다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 RK 필수 규칙과 4-2절의 대체 후보가 있으면 DDL 허용
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, 복제 정합성, 장애 조치 운영

### 문제
문서는 PK 또는 `NOT NULL UK`가 계속 하나 이상 있으면 안전하다고 전제한다. 그러나 운영 중 DML이 기록될 때 사용한 RK와 replica가 적용할 때 선택한 RK가 같은지, 로그가 키 정의 버전을 포함하는지 설명하지 않는다. 후보의 존재와 과거 로그를 정확히 적용하는 능력은 별개다.

### 왜 중요한가
UPDATE 로그가 `id=10`을 행 식별자로 담았는데 replica가 이미 `email`을 RK로 전환했다면 행을 못 찾을 수 있다. 그러면 원래 해결하려던 적용 누락과 `fail_count` 증가가 다시 발생한다. DBA는 DDL을 허용하기 전에 대기 로그가 어떤 키를 쓰는지 확인할 수 있어야 한다.

### 재현 또는 구체적 예제
`account(id PRIMARY KEY, email VARCHAR(100) NOT NULL UNIQUE, balance INT)`에서 replica apply를 정지한다. source에서 `UPDATE account SET balance=90 WHERE id=10;` 후 PK를 email로 교체하고 apply를 재개한다. 기대 결과는 DML과 DDL이 source 커밋 순서대로 적용되고 정확히 한 행이 90이 되는 것이다. 문서에는 옛 DML 로그를 어느 RK로 찾는지 없다.

### 권고안
“DML 로그는 생성 당시 RK 식별자·구성 컬럼·이전 값을 포함하며 관련 DDL과 동일한 순서로 적용한다”와 같은 불변식을 명시한다. 구현이 다르면 안전을 보장하는 실제 규칙과 대기 로그가 있을 때 DDL을 대기/거부하는 조건을 적는다.

### 검증 방법
PK→UK, UK→PK, UK1→UK2마다 apply 지연 후 DML–DDL–DML을 수행한다. 양 노드의 행별 checksum, apply 로그와 `fail_count`를 비교해 누락·중복이 0인지 확인한다.

## [DBA-5Y-02] 모든 컬럼 식별 방식과 RK 방식의 운영 비용 비교가 없다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 1절의 PK/NOT NULL UK만 RK로 선택하는 정책
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 대형 테이블 DBA, 용량·성능 계획 담당자

### 문제
PK 없는 테이블을 모든 컬럼으로 찾는 대안을 배제한 이유와 RK 추가 비용이 문서에 없다. RK를 위해 대형 테이블에 UK를 생성하면 중복 검사, 전체 스캔, 정렬, 디스크 임시 공간과 장시간 잠금이 발생할 수 있다. `REPLICATION=OFF`는 성능 대안이지만 데이터 보호를 포기한다.

### 왜 중요한가
DBA에게 가장 위험한 순간은 기능 활성화보다 기존 수억 행 테이블을 HA 적합 상태로 바꾸는 과정이다. “인덱스가 있으므로 빠르다”는 결론만으로는 필요한 점검 시간, 임시 공간, 쓰기 지연을 산정할 수 없다.

### 재현 또는 구체적 예제
PK가 없는 5억 행 `click_log(event_time, user_id, url VARCHAR(2000))`에 `event_id BIGINT NOT NULL UNIQUE`를 추가하고 채운다고 하자. 모든 컬럼 비교는 복제 apply가 비싸고 중복 행을 구별하지 못할 수 있다. 반면 UK 추가는 백필과 인덱스 구축 중 운영 I/O를 크게 늘린다. OFF로 설정하면 failover 후 신규 로그가 없다.

### 권고안
세 대안의 정합성, DDL 소요, 로그 크기, apply 검색 비용, 장애 조치 결과를 비교한 의사결정표를 추가한다. 온라인/오프라인 마이그레이션 지원 여부와 용량 산정식, 권장 유지보수 창을 제시한다.

### 검증 방법
1천만 행 대표 테이블에 정수 PK, 복합 문자열 UK, 키 없음 조건을 만든다. 인덱스 구축 시간·잠금·임시 공간과 초당 DML/apply 처리량을 측정해 문서의 운영 기준과 대조한다.

## [DBA-5Y-03] REPLICATION=OFF를 다시 동기화하는 생명주기 설계가 없다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1·4·6절의 OFF 데이터 불일치 면책과 2-2절의 HA 중 OFF→ON 금지
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 백업·복구, failback 운영

### 문제
ON→OFF는 HA 중 허용하지만 OFF 테이블의 데이터 보존 기간, standby 데이터 정리 여부, 재동기화 후 ON 복귀 절차가 없다. “책임지지 않는다”는 문구는 운영 생명주기를 대신할 수 없다.

### 왜 중요한가
OFF 테이블은 source와 replica가 서로 다른 두 데이터 세트가 된다. failover 뒤 옛 source가 돌아오면 어느 쪽을 정답으로 삼을지 결정해야 하며, 잘못 합치면 중복 또는 유실이 생긴다. 테이블 하나를 ON으로 되돌리려고 전체 HA를 중단하는 비용도 알아야 한다.

### 재현 또는 구체적 예제
`job_queue(id PK, state) ON`을 OFF로 바꾼 뒤 source에는 작업 101~200이 쌓인다. failover하면 새 primary에는 1~100만 있을 수 있고 별도 작업이 201부터 생성된다. 두 노드를 failback할 때 단순 양방향 병합은 같은 id의 다른 작업을 충돌시킨다.

### 권고안
OFF 전환 경계, standby의 기존 행 유지/삭제 정책, failover 후 권위 노드, 테이블 단위 재동기화, ON 복귀 조건을 runbook으로 정한다. 업무 원장·큐·감사 테이블에는 OFF를 금지하거나 강한 경고를 제공한다.

### 검증 방법
ON→OFF 후 양 노드에 의도적으로 다른 데이터를 만들고 failover/failback한다. 문서 절차만으로 권위 데이터 선택, 복사, 검증, ON 전환을 수행해 최종 checksum이 같고 새 DML이 정상 복제되는지 확인한다.

## [DBA-5Y-04] 실제 RK를 조회·감사할 수 없어 여러 UK 선택을 운영에서 검증할 수 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 1절의 PK 우선·여러 UK 중 엔진 선택과 2-3절의 REPLICATION ON/OFF 조회만 제공
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 감사 담당자, source/replica 정합성

### 문제
`SHOW CREATE TABLE`과 `db_class` 예시는 복제 여부만 보여 주며 선택된 RK, 후보 목록, 선택 이유를 보여 주지 않는다. 여러 UK 중 “명시 순서가 빠른 것”도 예시에 불과해 결정성·재시작 지속성이 보장되지 않는다.

### 왜 중요한가
DBA는 변경 전에 현재 사용 중인 키를 알아야 삭제 위험을 판단한다. source와 replica가 다른 UK를 선택하면 동일 DML을 서로 다르게 해석할 수 있다. 카탈로그 순서는 dump/load나 업그레이드에서 바뀔 수 있으므로 이름만 보고 추측하면 안 된다.

### 재현 또는 구체적 예제
`member(email NOT NULL UNIQUE, phone NOT NULL UNIQUE)`를 두 노드에 만들고 제약 생성 순서를 다르게 만든 뒤 HA에 편입한다고 하자. 실제 RK가 email인지 phone인지 조회할 방법이 없다. 재시작과 unload/load 뒤 선택이 바뀌는지도 확인할 수 없다.

### 권고안
테이블별 `replication=ON/OFF`, 선택 RK 제약 ID·이름·컬럼 순서, 후보와 부적격 이유를 구조화된 뷰에서 제공한다. 선택 규칙은 영구적이고 결정적인 규범으로 정하고 RK 변경은 감사 로그와 모니터링 이벤트를 남긴다.

### 검증 방법
PK 및 여러 UK 조합을 생성하고 source/replica, 재시작, rename, unload/load 전후에 관리 뷰를 조회한다. 실제 RK가 동일하고 변경 이벤트가 남으며 자동 점검 쿼리로 차이를 탐지할 수 있는지 확인한다.

## [DBA-5Y-05] 기본 ON이 HA 준비가 안 된 테이블을 조용히 누적시킨다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절의 생략 시 ON, 3·7절의 RK 없는 ON 테이블은 HA 시작 실패
- 사실/추론 구분: 확인된 사실
- 영향 대상: 기존 DB DBA, CI/CD, HA 전환 작업

### 문제
single/SA에서 기존 SQL로 키 없는 테이블을 만들면 자동 ON이지만 즉시 실패하지 않고 향후 HA 시작만 막는다. 어느 시점부터 경고하는지, 기존 DB를 업그레이드할 때 카탈로그가 어떻게 채워지는지 없다.

### 왜 중요한가
임시·스테이징 테이블 하나가 전체 클러스터 시작을 막으면 유지보수 시간이 늘어난다. 생성과 실패가 멀리 떨어져 있어 원인 추적도 어렵다. 기본값 변경은 자동화 스크립트와 구버전 운영 절차에 직접 영향을 준다.

### 재현 또는 구체적 예제
매일 배치가 `CREATE TABLE load_tmp(batch_no INT, payload VARCHAR(4000));`를 생성한다. 새 버전 single에서 모두 ON으로 누적된 뒤 주말에 HA를 켜면 수십 개 테이블 때문에 시작 실패한다. DBA는 사전에 목록과 권장 조치를 받아야 한다.

### 권고안
업그레이드·생성 시 RK 없는 ON 테이블을 경고하고 읽기 전용 사전 진단 명령을 제공한다. 결과에는 owner/table/행 수/후보 키/권장 `ALTER`를 포함한다. 기존 객체의 초기 ON/OFF 정책과 기본 ON 선택 이유를 릴리스 문서에 명시한다.

### 검증 방법
구버전 스키마와 옵션 생략 DDL을 새 버전에서 재현한다. 업그레이드 보고서, 생성 경고, HA dry-run 목록이 빠짐없이 나오고 수정 후 경고가 사라지는지 확인한다.

## [DBA-5Y-06] single·SA·HA별 DDL 허용 행렬과 모드 판정 방법이 없다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 1절의 hb start 외 모두 single, 3절의 Single, 9절의 single과 SA 병기
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 변경 자동화, 장애 대응자

### 문제
문서가 single과 SA를 같은 것으로 보기도 하고 별도로 쓰기도 한다. heartbeat가 시작됐지만 replica가 연결되지 않은 상태, maintenance 모드 등에서 `ALTER REPLICATION`과 RK DDL이 어떤 규칙을 따르는지 알 수 없다.

### 왜 중요한가
같은 SQL이 모드에 따라 성공/실패하면 변경 계획에 정확한 사전 조건이 필요하다. 운영자가 HA를 멈췄다고 생각했으나 엔진은 HA 제약을 유지하면 긴급 변경이 실패하고, 반대면 보호 장치 없이 위험 DDL이 실행될 수 있다.

### 재현 또는 구체적 예제
`ALTER TABLE stage REPLICATION=ON;`을 server mode, SA mode, `cubrid hb stop` 직후, replica disconnected 상태에서 각각 수행한다. 문서상 HA에서는 ERROR지만 나머지 상태의 경계가 명확하지 않다.

### 권고안
공식 모드 정의와 확인 명령을 제공하고 CREATE ON/OFF, OFF→ON, ON→OFF, RK 추가·삭제·교체, FK 변경의 허용 행렬을 작성한다. 각 실패에 안정된 오류 코드와 필요한 모드 전환 절차를 연결한다.

### 검증 방법
행렬의 각 셀을 자동화 테스트로 실행해 기대 성공/실패와 오류가 일치하는지 본다. heartbeat 상태를 중간에 바꾸는 경계 시험에서도 보호 규칙이 우회되지 않는지 확인한다.

## [DBA-5Y-07] RK 후보의 모든 속성 변경 상태 전이가 빠져 있다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 단일 PK/UK 추가·삭제 중심 제한
- 사실/추론 구분: 확인된 사실
- 영향 대상: 온라인 스키마 변경 DBA, 복제 정합성

### 문제
복합 PK/UK의 일부 열 변경, 컬럼 rename, 타입·길이·collation 변경, `NOT NULL` 제거, 제약 rename, 파티션 관련 변경을 다루지 않는다. “다른 후보가 있으면 모든 DDL 허용”은 모든 후보가 한 번에 자격을 잃는 복합 ALTER도 허용하는지 모호하다.

### 왜 중요한가
RK는 UNIQUE 제약만 남아 있다고 유효한 것이 아니다. 모든 구성 열이 NOT NULL이어야 하며 데이터 비교 의미도 유지되어야 한다. 타입 변환 실패나 NULL 허용은 replica가 행을 유일하게 찾지 못하게 할 수 있다.

### 재현 또는 구체적 예제
`shipment(tenant_id INT NOT NULL, tracking_no VARCHAR(40) NOT NULL, UNIQUE(tenant_id,tracking_no))`의 유일한 후보에 `ALTER TABLE shipment MODIFY tracking_no VARCHAR(80);`, rename, `DROP NOT NULL`을 차례로 시도한다. 마지막 SQL은 대체 후보가 없으면 반드시 원자적으로 거부돼야 하지만 문서에 없다.

### 권고안
PK/UK와 구성 열에 가능한 DDL을 상태 전이 표로 작성한다. 각 행에 HA 허용 여부, 사전 데이터 검사, lock 수준, RK 전후 값, 로그 처리, 실패 rollback과 오류 코드를 넣는다.

### 검증 방법
단일·복합 후보에 표의 모든 DDL을 실행하고 성공 뒤 source/replica RK와 스키마를 비교한다. 실패 뒤에는 제약·컬럼·데이터가 전혀 바뀌지 않았는지 검사한다.

## [DBA-5Y-08] 복합 ALTER의 원자성·잠금·실패 복구 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 DROP+ADD 권장
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 대형 테이블, 복제 가용성

### 문제
기존 키 삭제와 새 키 추가를 한 SQL로 수행하면 안전하다고 암시하지만, ADD용 중복 스캔 중 잠금, 실패 시 DROP rollback, replica 부분 적용, 취소 동작을 규정하지 않는다.

### 왜 중요한가
새 UK 생성은 전체 데이터를 검사할 수 있다. 수억 행에서 장시간 DML을 막거나 복제 지연을 키울 수 있고, 중복 한 건 때문에 ADD가 실패할 수 있다. 이때 옛 RK만 삭제되면 테이블은 복제 불가능해진다.

### 재현 또는 구체적 예제
`users(id PK, email NOT NULL)`에 중복 email이 있는 상태에서 `ALTER TABLE users DROP CONSTRAINT pk_users, ADD CONSTRAINT uq_users_email UNIQUE(email);`을 실행한다. 기대 동작은 사전 검증 실패로 전체 ALTER가 취소되고 id RK가 유지되는 것이다. apply 중 replica 디스크 부족도 같은 원자성을 가져야 한다.

### 권고안
새 후보 검증·구축 후 단일 커밋 지점에서 RK를 교체하는 순서, lock 종류와 timeout, 양 노드 원자성, 취소·재시도 절차를 명시한다. 보장할 수 없다면 운영 중 복합 교체를 금지하고 오프라인 runbook을 제공한다.

### 검증 방법
정상, 중복, lock timeout, replica 공간 부족, 프로세스 crash를 각 단계에 주입한다. 모든 실패에서 이전 RK와 DML 가용성이 유지되고 부분 인덱스·부분 DDL이 남지 않는지 확인한다.

## [DBA-5Y-09] DDL과 장기 DML 트랜잭션의 직렬화 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 모든 DDL 복제와 운영 중 RK 변경 허용
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 24×7 운영 DBA, 애플리케이션, 복제 정합성

### 문제
RK 변경 DDL이 진행 중인 DML을 대기시키는지, DDL 전 시작해 DDL 후 커밋한 트랜잭션이 어느 RK를 쓰는지, replica에서 같은 순서를 어떻게 보장하는지 없다.

### 왜 중요한가
트랜잭션 시작 순서와 커밋 순서는 다를 수 있다. 옛 스키마를 본 UPDATE가 새 RK 전환 뒤 커밋하면 로그와 카탈로그 버전이 어긋날 수 있다. 장기 배치가 있는 환경에서는 흔한 운영 조건이다.

### 재현 또는 구체적 예제
세션 A가 `UPDATE account SET balance=balance-1 WHERE id=10;` 후 커밋하지 않는다. 세션 B가 RK를 id에서 email로 교체하고, 그 뒤 A가 커밋한다. 기대 동작은 B가 A를 기다리거나 A를 명확한 오류로 중단하는 것이다. 양 노드 적용 순서도 같아야 한다.

### 권고안
DDL lock 획득 시점, 기존 트랜잭션 drain 정책, 신규 DML 차단, timeout·deadlock 오류, DML 로그의 schema/RK 버전을 문서화한다. DBA가 대기 세션과 예상 영향 시간을 조회하는 명령을 제시한다.

### 검증 방법
짧은·장기 DML, prepared transaction에 해당하는 지원 상태, DDL을 다양한 시작/커밋 순서로 교차한다. 대기/오류가 규칙과 같고 최종 checksum과 `fail_count`가 정상인지 본다.

## [DBA-5Y-10] RK DDL 적용 도중 failover의 승격 차단 조건이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 운영 중 키 교체와 7절의 HA 시작 전 검사
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 장애 대응 DBA, 자동 failover, 데이터 정합성

### 문제
source에서 RK DDL이 커밋됐지만 standby가 아직 적용하지 않은 때 장애가 나면 standby의 RK가 옛 상태다. 자동 승격이 이를 감지해 막는지, 로그를 끝까지 적용한 후 승격하는지 없다.

### 왜 중요한가
새 primary가 옛 RK로 쓰기를 시작하면 복구된 노드의 새 RK와 호환되지 않을 수 있다. 이후 failback에서 서로 다른 로그 의미를 합쳐야 하므로 단순 재시작으로 복구할 수 없는 장애가 된다.

### 재현 또는 구체적 예제
RK 교체 직후 replica apply를 정지하고 source를 강제 종료한다. replica가 옛 RK인 상태에서 승격 요청을 받는다. 기대 결과는 DDL LSA 적용 완료 또는 명시적 관리자 승인 전 승격 거부이며, 현재 문서는 결과가 없다.

### 권고안
승격 사전 조건에 카탈로그/RK 버전과 필수 DDL LSA 일치를 넣는다. 계획 switchover와 강제 failover의 절차, 강제 시 예상 데이터 손실과 재구축 요구를 명시한다.

### 검증 방법
DDL 로그 생성 전, 전송 후, 적용 중, 적용 후 각 지점에서 장애를 주입한다. 자동/수동 승격이 안전 조건을 지키고 승격 뒤 새 DML과 복구 노드 재편입이 정상인지 확인한다.

## [DBA-5Y-11] ON→OFF 전환 경계와 failback 시 권위 데이터가 정의되지 않았다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2-2절의 HA 중 ON→OFF 허용과 4절의 DML만 미복제
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DBA, failover/failback, 데이터 정합성

### 문제
이미 복제 큐에 있는 DML을 OFF DDL 전후 어디까지 적용하는지 없다. OFF 이후 failover한 새 primary와 복구된 옛 primary 양쪽에 서로 다른 행이 있을 때 failback 기준도 없다.

### 왜 중요한가
전환 경계가 명확해야 어느 LSA까지 두 노드가 같다고 말할 수 있다. 그렇지 않으면 checksum 차이가 정상적인 OFF 결과인지 apply 누락인지 분류할 수 없고, 옛 primary를 재사용하다 오래된 데이터가 다시 서비스될 수 있다.

### 재현 또는 구체적 예제
`cache ON`의 INSERT 1~100 중 replica가 80까지 적용했을 때 OFF로 바꾸고 101을 넣는다. replica가 81~100을 적용하는지 폐기하는지 불명확하다. failover 후 102를 넣고 failback할 때 101과 102 중 무엇을 유지할지도 없다.

### 권고안
OFF DDL 커밋 LSA 이전 DML은 전부 적용하고 이후 DML은 로그 대상에서 제외한다는 식의 컷오버 계약을 정한다. OFF 테이블은 failback 전 폐기·재생성 또는 권위 노드에서 단방향 동기화하도록 절차화한다.

### 검증 방법
인위적 apply 지연에서 ON→OFF와 전후 번호 DML을 실행한다. 각 노드의 최종 집합과 로그 LSA를 확인하고, failover/failback runbook으로 오래된 데이터가 재등장하지 않는지 시험한다.

## [DBA-5Y-12] 복합·가변 길이 RK의 로그·인덱스 비용과 값 변경 규칙이 없다

- 분류: 성능
- 심각도: Major
- 근거 위치: 원문 1절의 PK/NOT NULL UK 일반 규칙과 4-2절의 단일 컬럼 예시
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 성능 DBA, 복합 키 사용자, 복제 지연 모니터링

### 문제
복합 UK의 지원 한계, 최대 키 크기와 타입, 문자열 collation, RK 값을 UPDATE할 때 이전/새 값 사용 규칙이 없다. 넓은 UK는 정수 PK보다 로그량, 네트워크, 인덱스 비교 CPU를 크게 늘릴 수 있다.

### 왜 중요한가
RK는 모든 UPDATE/DELETE의 대상 행을 찾는 데 쓰인다. 3개 문자열 열을 매번 전송·비교하면 source 처리량은 같아 보여도 replica apply 지연이 누적될 수 있다. 키 값 변경 시 새 값으로 찾으면 기존 행을 발견할 수 없다.

### 재현 또는 구체적 예제
`inventory(region VARCHAR(100), warehouse VARCHAR(100), sku VARCHAR(500), qty INT, UNIQUE(region,warehouse,sku))`에서 이 UK가 RK다. 초당 5천 건 qty UPDATE와 sku 변경을 수행한다. 기대 동작은 이전 복합 키로 행을 찾고 새 키를 원자 반영하며, 로그 크기·지연 한도가 문서화되는 것이다.

### 권고안
지원 타입·열 수·바이트 한도와 collation 조건을 명시한다. RK UPDATE의 before/after 로그 규칙, 예상 로그 증폭과 권장 키 설계, apply 지연 경보 기준을 제공한다.

### 검증 방법
정수 단일 PK와 1/3열 문자열 UK를 동일 DML 부하로 비교한다. 로그 bytes/transaction, CPU, apply TPS, lag와 RK 값 변경 정확성을 측정해 수용 한도를 검증한다.

## [DBA-5Y-13] FK의 상태 변경과 연쇄 동작이 OFF 정책을 우회할 수 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식이 참조하는 부모도 ON이어야 한다는 규칙
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, FK 정합성, 장애 조치

### 문제
FK 생성 시 부모 상태만 검사하며, 기존 FK의 부모를 ON→OFF로 바꾸는 경우와 `ON DELETE/UPDATE CASCADE`, SET NULL 동작을 다루지 않는다. OFF 자식이 ON 부모를 참조하는 반대 방향 정책도 없다.

### 왜 중요한가
부모 DML이 복제되지 않는데 자식 연쇄 DML만 전달되거나, replica에서 연쇄가 다시 실행되면 누락·중복이 발생할 수 있다. FK는 생성 시점뿐 아니라 양쪽 테이블 상태가 변할 때마다 불변식을 유지해야 한다.

### 재현 또는 구체적 예제
`customers ON`과 `orders ON` 사이에 `ON DELETE CASCADE` FK가 있다. 부모를 OFF로 변경한 뒤 source에서 고객을 삭제하면 주문도 삭제된다. replica에 부모 삭제 로그가 없을 때 자식 삭제가 별도 로그로 오는지, 전환 자체가 거부되는지 문서에 없다.

### 권고안
부모/자식 ON·OFF 조합별 CREATE FK, ALTER 상태, DROP, CASCADE/SET NULL/RESTRICT 표를 제공한다. 위험 조합을 만드는 ON→OFF는 원자적으로 거부하고 시작 전 검사뿐 아니라 DDL 시점에도 검증한다.

### 검증 방법
4개 상태 조합과 각 referential action에서 INSERT/UPDATE/DELETE, 상태 전환, failover를 실행한다. 제약 오류와 양 노드 데이터가 명시 규칙과 일치하는지 확인한다.

## [DBA-5Y-14] OFF 테이블 의존 VIEW의 위험을 탐지·목록화할 방법이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 6절의 VIEW 사용 제약 없음과 결과 불일치 면책
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 조회 서비스, 리포팅 시스템

### 문제
VIEW DDL이 replica에 존재해도 OFF 테이블 데이터가 없으면 결과가 달라진다. 문서는 이를 허용하지만 어떤 VIEW가 직접·간접 의존하는지 조회하거나 failover 전에 경고하는 방법이 없다.

### 왜 중요한가
SQL 오류가 아니라 정상적인 빈 결과나 다른 합계가 나오므로 모니터링이 놓치기 쉽다. 중첩 VIEW에서는 DBA가 정의문을 수동 검색해도 간접 의존성을 빠뜨릴 수 있다.

### 재현 또는 구체적 예제
`orders ON`, `local_discount OFF`를 조인한 `v_payable`과 이를 집계한 `v_daily_sales`를 만든다. source 합계가 900만원인데 failover 후 1,000만원이 될 수 있다. 두 번째 VIEW만 보는 운영자는 OFF 의존성을 알기 어렵다.

### 권고안
OFF 테이블에 의존하는 VIEW·중첩 VIEW를 재귀 조회하는 카탈로그 쿼리/관리 명령을 제공한다. 생성·상태 전환·failover 사전 점검 때 경고하고, 중요 VIEW는 OFF 의존을 정책적으로 금지할 수 있게 한다.

### 검증 방법
직접 조인, 2단계 중첩, UNION, 집계 VIEW를 구성한다. 의존성 보고서가 모두 찾아내고 source/replica 샘플 결과 차이와 경고가 연결되는지 확인한다.

## [DBA-5Y-15] HA 사전 검사가 일관된 시점과 자동화 가능한 출력을 보장하지 않는다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절의 시작 시 제약 검사와 “에러와 함께 파일 리스트”
- 사실/추론 구분: 확인된 사실
- 영향 대상: HA 시작 담당자, 자동화, 대규모 DB

### 문제
검사가 카탈로그의 한 시점 snapshot을 보는지, 검사와 시작 사이 DDL을 막는지, 모든 위반을 모으는지 없다. “파일 리스트”는 테이블/제약 목록인지 불명확하고 오류 코드·구조화 출력도 없다.

### 왜 중요한가
검사 도중 상태가 바뀌면 통과 직후 무효 상태로 HA가 시작될 수 있다. 첫 오류만 출력하면 수천 테이블에서 수정–재시작을 반복한다. 스크립트는 자연어 메시지 대신 안정된 필드가 필요하다.

### 재현 또는 구체적 예제
RK 없는 `stage_a`, `stage_b`, OFF 부모를 참조하는 `orders`를 만든다. 검사 중 다른 세션이 stage_a PK를 추가하고 stage_b를 OFF로 바꾼다. 기대 결과는 하나의 일관된 버전 기준 보고서와 owner/table/constraint/사유/권장 조치 전체 목록이다.

### 권고안
별도 dry-run 명령, snapshot 또는 DDL fence, 검사 결과의 schema version/token을 정의한다. JSON/표 형식으로 모든 위반과 안정된 오류 코드를 출력하고 실제 시작 직전 같은 token이 유효한지 재확인한다. 1만 테이블 성능 목표도 정한다.

### 검증 방법
동시 DDL을 주입하며 반복 검사해 결과가 한 시점으로 일관적인지 본다. 1만 테이블·다수 FK에서 시간/메모리를 측정하고 JSON을 운영 스크립트가 정확히 파싱하는지 확인한다.

## [DBA-5Y-16] fail_count와 기존 불일치에 대한 관측·교정 절차가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체에서 `fail_count` 정의와 불일치 복구 절차 부재, 4·6절의 불일치 허용
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, NOC, 고객지원, 데이터 정합성

### 문제
`fail_count`의 단위, 증가 이벤트, 리셋, 보존 기간, 테이블·LSA 연계가 없다. 새 정책은 향후 오류를 막더라도 과거에 이미 빠진 행을 찾거나 고치지 않는다. OFF로 예상된 차이와 비정상 누락을 구별하는 방법도 없다.

### 왜 중요한가
카운터가 0이라고 데이터가 같은 것은 아니다. 한 번 누락된 잔액은 apply가 정상화돼도 계속 틀리다. 반대로 OFF 테이블의 차이는 의도된 것이므로 전체 DB checksum만 비교하면 항상 경보가 난다.

### 재현 또는 구체적 예제
source `account(10,900)`, replica `account(10,1000)`, `fail_count=5` 상태에서 업그레이드한다. 이후 카운터가 늘지 않아도 불일치는 남는다. `cache OFF`의 정상 차이는 검사에서 제외해야 하지만 현재 기준이 없다.

### 권고안
테이블·오류 코드·첫/마지막 LSA별 실패 지표와 경보 기준을 정의한다. ON 테이블만 대상으로 row count/checksum/샘플 상세 비교, 영향 LSA 추적, 테이블 단위 재동기화, 검증 후 승인 리셋 runbook을 제공한다.

### 검증 방법
행 누락, 중복, 잘못된 값, DDL apply 실패를 주입하고 OFF 차이도 함께 만든다. 모니터가 비정상 차이만 찾아 원인 로그에 연결하고 runbook 후 checksum 일치와 정상 카운터 상태가 되는지 확인한다.

## [DBA-5Y-17] unload/load 기본값 모순과 백업 복원 시 RK 보존 규칙이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 필드 없음=ON, 9절 요약의 필드 없음=OFF
- 사실/추론 구분: 확인된 사실
- 영향 대상: 백업·복원 DBA, 재해 복구, 업그레이드

### 문제
구버전 unload 파일의 동일 입력을 8절은 ON, 9절은 OFF로 정의한다. 또한 선택된 RK 자체를 보존하는지 load 시 다시 선택하는지, 물리 백업/시점 복구에서는 어떤지 없다.

### 왜 중요한가
ON이면 키 없는 테이블 때문에 HA가 시작되지 않고 OFF이면 업무 DML이 보호되지 않는다. 여러 UK에서 load가 다른 RK를 고르면 복원 시점 이후 로그 적용과 맞지 않을 수도 있다. 복구 작업은 시간이 촉박해 추측이 허용되지 않는다.

### 재현 또는 구체적 예제
구버전의 키 없는 `legacy_log`와 UK 두 개인 `member`를 unload한다. 새 버전에서 load했을 때 legacy_log의 ON/OFF가 상충하며 member의 실제 RK가 복원 전과 같은지 알 수 없다. 이어 archived log를 적용할 때 위험하다.

### 권고안
모순을 하나의 정책으로 통일하고 필드 없음은 명시 override 또는 강한 경고를 요구한다. unload에 replication 상태와 영구 RK ID/컬럼을 저장하고 load 보고서에 결정 결과를 출력한다. 논리·물리 백업, PITR별 보존 규칙을 구분한다.

### 검증 방법
구/신버전 unload, 물리 백업, archived log 복구를 각각 수행한다. ON/OFF와 RK가 정책대로 보존되고 restore 후 HA dry-run 및 후속 로그 적용이 성공하는지 확인한다.

## [DBA-5Y-18] 롤링 업그레이드·혼합 버전과 성능 회귀 시험 기준이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절의 새 문법·카탈로그, 8절의 구버전 파일만 언급
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 무중단 업그레이드 DBA, 용량 계획, 복제 가용성

### 문제
구버전 노드가 `REPLICATION` DDL과 RK 메타데이터를 이해하는지, 어떤 순서로 노드를 올려야 하는지 없다. 넓은 UK를 RK로 쓸 때 로그량과 apply lag 회귀에 대한 합격 기준도 없다.

### 왜 중요한가
구버전 replica가 새 DDL parse에 실패하거나 옵션을 무시하면 복제가 중단되거나 OFF 데이터가 뜻밖에 복제될 수 있다. 기능이 정확해도 apply 처리량이 source 쓰기량보다 낮으면 lag가 계속 늘어 실질적으로 HA가 아니다.

### 재현 또는 구체적 예제
old replica를 둔 채 source만 new로 올려 `CREATE TABLE cache(id INT) REPLICATION=OFF;`와 RK 교체를 실행한다. 이어 단일 정수 PK 대비 3열 문자열 UK로 초당 1만 UPDATE를 발생시킨다. 혼합 버전 동작과 허용 lag 모두 불명확하다.

### 권고안
지원 버전 행렬, 업그레이드·downgrade 순서, 혼합 기간 새 기능 차단 정책을 명시한다. 대표 키 폭별 로그 증폭, apply TPS, p95 lag, DDL lock 시간의 출시 한도를 정한다.

### 검증 방법
old/new 양방향 조합에서 DDL/DML/failover를 시험하고 미지원 동작이 사전에 차단되는지 본다. 좁은·넓은 RK 부하를 장시간 실행해 처리량이 유입률 이상이며 lag와 자원 사용이 한도 내인지 확인한다.

## [DBA-5Y-19] 오류 예제와 SQL 오탈자가 운영 절차로 사용할 수 없는 수준이다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2·4·5절의 `ERROR`만 있는 예제, 예시 2의 후행 쉼표, “CRATE TABLE”, 불완전한 제약 SQL
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 자동화 개발자, 지원팀

### 문제
여러 예제가 실제 제약 이름 없이 `...`를 사용하고 실패 결과도 `ERROR`뿐이다. `CREATE TABLE ... (a INT,)`, `CRATE TABLE`, FK DROP/ADD 문법 등 복사 실행하기 어려운 부분이 있다. 정책 검증 전에 parser 오류가 날 수 있다.

### 왜 중요한가
DBA runbook과 자동화는 오류 코드로 “중복 데이터”, “유일한 RK 삭제”, “HA 모드 금지”를 구분한다. 단순 ERROR는 재시도 가능 여부도 판단하지 못한다. 잘못된 예제는 긴급 작업에서 더 큰 변경 사고를 만든다.

### 재현 또는 구체적 예제
예시 2 `CREATE TABLE repl_table_without_rk(a INT,);`를 실행하면 후행 쉼표로 문법 오류가 먼저 날 수 있어 의도한 single 성공/HA 거부를 검증하지 못한다. 예시 7의 `DROP CONSTRAINT ...`도 실행할 수 없다.

### 권고안
모든 예제를 실제 CUBRID 문법과 명명된 제약으로 완성하고 초기 상태·모드·기대 코드·전체 메시지·복구 SQL을 넣는다. 코드 블록을 문서 CI에서 자동 실행한다.

### 검증 방법
문서 SQL을 추출해 깨끗한 single/SA/HA DB에서 순서대로 실행한다. 예상 성공/실패 및 오류 코드가 실제와 일치하지 않으면 문서 빌드를 실패시킨다.

## [DBA-5Y-20] HA 전환부터 failback까지 이어지는 실행 가능한 runbook이 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 3·7·8·9절의 단편적 전환·복원 설명
- 사실/추론 구분: 확인된 사실
- 영향 대상: DBA, 변경 승인자, 장애 대응 조직

### 문제
기존 single DB 인벤토리, OFF 분류 승인, RK 구축, 사전 검사, 초기 동기화, lag 확인, failover, 데이터 검증, failback과 rollback이 하나의 절차로 연결되지 않는다. 각 단계의 중단 조건과 예상 소요도 없다.

### 왜 중요한가
운영 변경은 개별 SQL이 성공하는 것으로 끝나지 않는다. 어떤 단계에서 실패했을 때 이전 서비스 상태로 돌아갈 수 있어야 하고, 데이터가 같다는 증거를 남겨야 한다. 분산된 설명은 담당자별 해석 차이를 만든다.

### 재현 또는 구체적 예제
1억 행 `account(id PK)`와 키 없는 `stage`, OFF 후보 `cache`가 있는 single DB를 HA로 바꾼다. DBA는 객체 분류→UK/PK 구축 영향 측정→OFF 승인→backup→HA dry-run→초기 sync→checksum→switchover→failback 순서를 알아야 한다. 현재 문서에는 전체 예와 rollback 지점이 없다.

### 권고안
사전 조건, 명령, 기대 출력, 소요·잠금, 승인자, 성공/중단 기준, rollback을 포함한 단계별 runbook을 추가한다. planned switchover와 emergency failover를 분리하고 작업 증적으로 RK/ON 목록, LSA, lag, checksum을 보존한다.

### 검증 방법
문서를 보지 못한 다른 DBA가 runbook만으로 staging DB를 전환하고 의도적 UK 중복·apply 지연·failover를 처리하게 한다. 별도 구두 안내 없이 원복과 최종 checksum 일치까지 완료하는지 확인한다.

## [DBA-5Y-21] 복제 정책 변경에 직무 분리와 보호 잠금이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-2절은 ON/OFF 변경을 허용하지만 권한·승인 정책은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DBA, 보안 운영, 업무 데이터 보호

### 문제
일반 ALTER 권한, 테이블 owner, DBA 중 누가 ON→OFF와 RK 변경을 수행할 수 있는지 없다. 변경 실행자와 승인자를 분리하는 방법이나 중요 테이블의 정책 잠금도 정의되지 않았다.

### 왜 중요한가
OFF는 failover 데이터 보호 수준을 낮춘다. 애플리케이션 배포 계정이 성능 문제를 해결하려고 OFF로 바꾸면 기술적으로 성공해도 조직의 데이터 보호 승인을 우회한다.

### 재현 또는 구체적 예제
```sql
-- 일반 ALTER 권한만 가진 release_user라고 가정
ALTER TABLE payment_ledger REPLICATION=OFF;
```
성공 여부와 별도 권한이 불명확하다. 성공한다면 다음 failover에서 결제 원장 DML이 없을 수 있다.

### 권고안
상태 조회·CREATE 지정·ON→OFF·OFF→ON·RK 변경 권한을 분리하고 업무 중요도별 policy lock과 two-person approval hook을 제공한다. 권한 오류는 안정된 코드로 남긴다.

### 검증 방법
owner, schema migration, HA operator, auditor 역할 계정으로 모든 명령을 수행한다. 승인 행렬과 우회 방지, rollback 시 권한 검사가 일치하는지 본다.

## [DBA-5Y-22] RK·ON/OFF 변경의 감사 체인과 증적 보존 계약이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절은 현재 상태만 조회하며 변경 이력은 누락
- 사실/추론 구분: 확인된 사실
- 영향 대상: 사고 대응, 감사, 규제 데이터 운영

### 문제
actor, old/new 상태, 선택 RK, DDL transaction, source node, 승인 ticket을 연결하는 이력이 없다. 실패·rollback된 시도와 자동 재선택도 기록 대상인지 미정이다.

### 왜 중요한가
현재 OFF만 봐서는 의도된 캐시 정책인지 사고인지 판별할 수 없다. 오래된 사고는 DB 로그가 순환된 뒤 증거가 사라질 수 있어 외부 보존 정책이 필요하다.

### 재현 또는 구체적 예제
월요일 `orders`가 OFF가 되고 금요일 failover에서 4일치 주문이 없다. 현재 카탈로그만으로 변경 사용자·DDL·승인 이유를 재구성할 수 없다.

### 권고안
tamper-evident 감사 이벤트에 actor/time/database/object/old-new/RK/transaction/LSA/result를 남긴다. 보존·접근 통제와 SIEM export 스키마를 정의한다.

### 검증 방법
성공·실패·rollback·crash된 변경을 실행하고 감사 이벤트의 완전성·순서·외부 전송을 확인한다. 일반 DBA가 기록을 수정할 수 없는지도 본다.

## [DBA-5Y-23] 파티션의 RK 유일성 범위와 상태 상속이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 1~4절은 일반 테이블만 다루고 파티션 상호작용은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 대용량 DBA, 파티션 유지보수, 복제 정합성

### 문제
대상 CUBRID 버전이 파티션을 지원한다면 ON/OFF가 부모/자식 중 어디에 저장되는지, local unique key가 전체 RK가 될 수 있는지, attach/detach/exchange 시 상태가 어떻게 전이되는지 없다.

### 왜 중요한가
파티션별 동일 id가 가능하면 RK `id`만으로 전체 행을 찾을 수 없다. 새 파티션이 OFF 또는 RK 없음으로 들어오면 특정 기간 데이터만 누락되는 조용한 사고가 생긴다.

### 재현 또는 구체적 예제
```sql
-- 정확한 파티션 문법은 대상 버전 확인 필요
CREATE TABLE sales (dt DATE, id INT, amount INT,
 PRIMARY KEY(dt,id)) REPLICATION=ON;
```
월별 파티션 교환 중 기존 데이터와 상태가 원자적으로 전달되는지 불명확하다.

### 권고안
지원 범위, global/local uniqueness, 상태 상속과 모든 파티션 DDL의 전이·잠금·로그 규칙을 명시한다. 사전 검사는 파티션별 위반을 펼쳐 보여 줘야 한다.

### 검증 방법
경계 양쪽 중복 키와 attach/detach/exchange/split을 실행한다. apply 지연과 failover 후 모든 파티션 checksum 및 선택 RK를 검사한다.

## [DBA-5Y-24] 온라인 RK 구축의 resource budget과 재개 가능성이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 3·4절은 키 추가를 해결책으로 제시하지만 online DDL 운영 계약은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 24×7 서비스, 대형 테이블, 용량 계획

### 문제
online index build 지원 여부, snapshot 일관성, delta catch-up, 진행률, pause/resume, cancel cleanup과 source/standby 자원 예산이 없다.

### 왜 중요한가
수억 행 UK를 만들며 계속 들어오는 DML을 별도 반영해야 한다. delta가 build 속도보다 빨리 늘면 끝나지 않고 log/temporary disk를 고갈시킬 수 있다.

### 재현 또는 구체적 예제
`customer` 10억 행에 email UK를 초당 2만 쓰기 중 추가한다. build 80%에 replica lag와 임시 공간이 임계치를 넘을 때 pause/abort 후 재개 가능한지 없다.

### 권고안
작업 전 space/IO/log 산정, 최대 lock·lag, progress와 delta backlog, 자동 throttle/pause, resumable 여부와 abort cleanup을 정의한다.

### 검증 방법
쓰기율을 build 처리율 위아래로 바꾸며 pause/resume/crash를 주입한다. SLO, 공간 한도, 재개 후 RK·데이터 일치를 검증한다.

## [DBA-5Y-25] bulk load·TRUNCATE·직접 적재 경로의 HA 안전 등급이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 DDL/DML과 loaddb만 설명하며 운영 중 대량 경로는 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 데이터 이관, 배치, 로그·apply 용량

### 문제
지원 bulk utility, 대량 INSERT, `TRUNCATE`, direct-path에 해당하는 기능이 row log를 생성하는지, ON/OFF를 따르는지, 부분 실패를 어떻게 복구하는지 없다.

### 왜 중요한가
로그 우회는 조용한 누락을 만들고, 전량 row logging은 수 TB 로그와 장기 lag를 만들 수 있다. 대량 적재 도중 failover하면 어느 batch까지 유효한지 알아야 한다.

### 재현 또는 구체적 예제
```sql
TRUNCATE TABLE event_stage;
-- 지원 bulk 도구로 5억 행 적재
```
TRUNCATE와 data batch가 독립 commit인지, replica가 동일 경계까지 적용하는지 없다.

### 권고안
모든 적재 경로를 HA-safe/conditional/unsupported로 분류하고 log mode, batch atomicity, resume token, space와 failover 제한을 정한다.

### 검증 방법
ON/OFF에서 각 경로를 정상·중단·재시작하고 중간 failover한다. batch ID, row checksum과 로그 보관량이 계약과 같은지 본다.

## [DBA-5Y-26] 병렬 apply에서 schema barrier와 worker drain 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 순차적으로 읽히는 DDL/DML만 설명하고 병렬 apply는 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 고처리량 HA, apply scheduler, 데이터 정합성

### 문제
병렬 apply 지원 시 RK DDL 앞 worker를 모두 drain하는지, DDL 뒤 descriptor cache를 동시에 바꾸는지, unrelated table만 계속 적용할 수 있는지 없다.

### 왜 중요한가
옛 id RK DML worker보다 email RK DDL worker가 먼저 끝나면 옛 로그를 새 descriptor로 해석해 실패한다. 전역 barrier는 안전하지만 처리량과 lag에 영향을 준다.

### 재현 또는 구체적 예제
T1 id 기반 UPDATE, T2 id→email switch, T3 email 기반 UPDATE가 commit된다. worker 실행 순서 T2→T1→T3도 최종 결과가 serial commit 순서와 같아야 한다.

### 권고안
지원 여부와 table/global barrier 범위, worker drain, cache invalidation, timeout/failure 시 상태를 정의한다. barrier latency를 metric으로 노출한다.

### 검증 방법
worker 수·transaction 시간을 무작위화하고 여러 테이블 DML을 섞는다. serial reference checksum과 처리량/lag를 비교한다.

## [DBA-5Y-27] PITR과 로그 보관 정책이 RK DDL 연속성을 보장하지 않는다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 unload/load만 다루며 PITR과 archived log 보관은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 재해 복구, backup governance, RPO

### 문제
PITR 지원 구성에서 backup manifest가 선택 RK/version을 담는지, DDL과 후속 DML 로그를 같은 retention으로 보존하는지, DDL log만 만료될 때 동작이 없다.

### 왜 중요한가
backup 이후 id→email 변경 record가 없고 email DML만 남으면 복구 노드는 로그를 해석할 수 없다. 부분 적용을 허용하면 목표 시점이 아닌 DB가 조용히 만들어진다.

### 재현 또는 구체적 예제
01:00 backup, 02:00 RK switch, 03:00 DML, 04:00 사고 후 03:30 PITR을 한다. 02:00 DDL이 retention에서 빠졌다면 recovery는 반드시 중단돼야 한다.

### 권고안
manifest의 schema/RK version, DDL/DML 공동 retention floor, required-log 계산과 새 baseline 요구를 정의한다. 복구 전 dry-run으로 gap을 검사한다.

### 검증 방법
RK 변경 전 backup과 이후 logs로 여러 시점을 복원한다. 중간 DDL 제거 시 명확히 차단하고 정상 경로는 checksum·RK가 원본과 같은지 확인한다.

## [DBA-5Y-28] 스토리지 snapshot의 crash consistency와 복제 위치가 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 논리 unload/load만 설명하고 물리 snapshot은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 스토리지 백업, 재해 복구, cloud 운영

### 문제
filesystem/storage snapshot을 지원 백업으로 인정하는지, data/catalog/log를 어떤 순서로 freeze해야 하는지, source·standby 중 어디서 떠야 하는지 없다.

### 왜 중요한가
RK catalog switch와 data/index page가 다른 시점으로 snapshot되면 복원 후 catalog는 새 RK인데 index는 옛 상태일 수 있다. standby snapshot은 apply 중간 상태일 수도 있다.

### 재현 또는 구체적 예제
email RK index build와 metadata switch 사이에 volume snapshot을 뜬다. data volume과 log volume snapshot 시각이 다르면 restore 시 어떤 recovery가 가능한지 없다.

### 권고안
지원/비지원 snapshot 유형, quiesce/checkpoint/freeze 순서, atomic volume group 요구, standby apply pause와 restore validation을 명시한다.

### 검증 방법
RK DDL 각 phase에서 crash-consistent/application-consistent snapshot을 복원한다. catalog/index/log 일치와 후속 apply 가능성을 확인한다.

## [DBA-5Y-29] 자원 고갈로 replica DDL만 실패한 상태의 승격 차단이 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4-2절은 성공/ERROR만 제시하고 disk full·memory pressure는 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: replica apply, capacity, failover

### 문제
source DDL 성공 후 replica index build가 disk full/OOM이면 부분 schema, retry, 후속 apply와 승격 동작이 없다.

### 왜 중요한가
replica가 옛 RK인 채 새 RK DML을 받으면 오류가 누적된다. 자동 failover가 이 노드를 승격하면 더 복구하기 어려운 schema split이 생긴다.

### 재현 또는 구체적 예제
replica email UK build 95%에서 disk full, source는 switch 완료 후 email UPDATE를 기록하고 곧 장애 난다. replica는 승격 불가 상태여야 한다.

### 권고안
양 노드 capacity precheck/reservation, schema DDL fatal barrier, incomplete artifact cleanup, node health의 `promotion_eligible=false`와 resync 기준을 정의한다.

### 검증 방법
build·switch·cleanup 각 단계에 disk full/OOM을 주입한다. 후속 apply·승격 차단과 복구 후 eligibility 회복을 확인한다.

## [DBA-5Y-30] 네트워크 분할에서 RK·OFF DDL을 막을 fencing 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4·7절은 정상 source/replica와 failover만 설명
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: HA quorum, split-brain, 데이터 복구

### 문제
network partition으로 양쪽 쓰기가 가능한 상태에서 각 노드가 다른 RK/ON-OFF DDL을 수행할 수 있는지 없다. 재연결 시 schema merge는 일반 row conflict보다 복잡하다.

### 왜 중요한가
한쪽은 OFF라 로그를 만들지 않고 다른 쪽은 다른 RK를 쓰면 양방향 replay로 합칠 근거가 사라진다. 단일 writer 보장이 핵심 선행 조건이다.

### 재현 또는 구체적 예제
노드 A는 `orders OFF`+주문101, B는 email RK+주문102를 수행한다. 두 schema/data history를 자동 결합할 안전 규칙이 없다.

### 권고안
quorum·STONITH/fencing token을 promotion과 위험 DDL 전 필수로 검증한다. split-brain 탐지 시 write/DDL freeze, 권위 노드 결정, 반대 노드 full rebuild 절차를 정한다.

### 검증 방법
heartbeat·client·replication network를 조합해 단절한다. 양쪽 쓰기가 차단되고 재결합 후 하나의 권위 history로 복구되는지 시험한다.

## [DBA-5Y-31] 반복 실패의 retry budget·quarantine·경보 억제 정책이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 전체에 fail_count 이후 retry와 격리 동작이 없음
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: apply 안정성, NOC, 자원 소비

### 문제
영구 row-not-found와 일시 I/O를 같은 방식으로 재시도하는지, restart 후 budget이 초기화되는지, alert storm을 어떻게 막는지 없다.

### 왜 중요한가
무한 retry는 CPU/log를 소모하고 알람 수천 건으로 첫 원인을 가린다. skip은 데이터 불일치를 확정하므로 허용해서는 안 된다.

### 재현 또는 구체적 예제
한 UPDATE가 영구 실패해 초당 100회 재시도되고 apply restart마다 counter가 리셋된다고 가정한다. 후속 transaction은 진행하지 못하고 NOC는 반복 알람만 받는다.

### 권고안
error class별 retry budget/backoff, first-cause aggregation, fatal barrier와 quarantine, operator acknowledgement·resync 후 해제를 정의한다.

### 검증 방법
일시/영구 오류와 restart를 조합한다. 일시 오류는 복구되고 영구 오류는 skip 없이 격리되며 경보가 원인별로 집계되는지 확인한다.

## [DBA-5Y-32] 다중 standby·cascade topology의 RK 일치 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 전체는 master와 slave 한 쌍만 가정
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 다중 노드 HA, DR site, 승격 순서

### 문제
대상 CUBRID가 다중 standby나 cascading 구성을 지원한다면 DDL barrier가 모든 노드에 적용돼야 하는지, 일부 노드 지연 중 승격 후보를 어떻게 고르는지 없다.

### 왜 중요한가
standby A는 새 RK, B는 옛 RK일 수 있다. source 장애 시 단순 lag가 작은 노드가 아니라 schema/RK version이 안전한 노드를 골라야 한다.

### 재현 또는 구체적 예제
source→standby A→DR B cascade에서 RK DDL은 A까지 적용됐고 B는 지연됐다. source와 A가 함께 장애면 B를 승격 가능한지, full resync가 필요한지 없다.

### 권고안
지원 topology, node별 schema/RK version·barrier LSA, promotion eligibility와 전체/부분 quorum 정책을 명시한다.

### 검증 방법
각 hop을 지연·중단하고 RK DDL/failover를 수행한다. 안전한 version 노드만 승격되고 재편입 후 모든 노드 checksum이 같아지는지 확인한다.

## [DBA-5Y-33] index rebuild·rename·통계 작업과 RK의 논리 ID 관계가 없다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 4-2절은 DROP INDEX만 다루고 정기 유지보수는 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 인덱스 유지보수, optimizer, 대기 로그

### 문제
rebuild/reorganize, 제약 rename, 통계 갱신으로 물리 index ID나 access path가 바뀔 때 RK가 유지되는지 없다.

### 왜 중요한가
RK가 물리 ID 또는 optimizer 선택에 결합되면 정상 유지보수만으로 대기 로그를 해석하지 못할 수 있다. 통계 기반 선택은 재현성도 없다.

### 재현 또는 구체적 예제
email UK RK의 index를 online rebuild하고 constraint rename한 뒤 rebuild 전 DML을 apply한다. 논리 RK가 같다면 정상이어야 한다.

### 권고안
RK를 영구 logical constraint ID에 연결하고 optimizer와 분리한다. 유지보수 작업별 ID/descriptor·barrier·lock 변화를 문서화한다.

### 검증 방법
모든 지원 유지보수 작업 전후 선택 RK와 대기 log apply를 비교한다. restart/restore 뒤도 ID가 계약대로 유지되는지 본다.

## [DBA-5Y-34] 운영 자동화를 위한 stable metadata API와 대량 진단이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-3절의 csql 예와 7절의 파일 리스트만 제공
- 사실/추론 구분: 확인된 사실
- 영향 대상: fleet automation, CMDB, 대규모 schema

### 문제
ON/OFF·선택 RK·후보·위반·promotion eligibility를 machine-readable하게 조회할 안정된 API가 없다. `select *`와 자연어 오류는 버전·locale 변화에 취약하다.

### 왜 중요한가
수백 DB와 수만 table을 수동 점검할 수 없다. pagination과 snapshot token이 없으면 조회 도중 DDL로 결과가 섞일 수 있다.

### 재현 또는 구체적 예제
fleet scanner가 1만 table 중 RK 없음 5개와 OFF 의존 VIEW 20개를 찾아야 한다. 현재 출력만으로는 열 순서와 메시지를 파싱해야 한다.

### 권고안
versioned JSON/catalog API에 object ID/type, state, selected RK/version, candidates, violation code와 snapshot token을 제공한다. pagination과 권한도 정의한다.

### 검증 방법
locale·버전을 바꾸고 1만 객체를 pagination 조회한다. 누락/중복 없이 같은 진단을 내며 schema change 시 stale token이 감지되는지 확인한다.

## [DBA-5Y-35] feature activation 이후 downgrade 가능한 경계가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 old unload 입력만 다루며 신기능 사용 후 구버전 원복은 누락
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 릴리스 rollback, catalog/log 호환성, 지원 조직

### 문제
새 catalog field나 RK log format을 사용한 뒤 binary downgrade가 가능한지, feature flag가 cluster-wide인지, 되돌릴 수 없는 첫 operation이 무엇인지 없다.

### 왜 중요한가
upgrade 장애 때 binary만 되돌렸는데 old engine이 OFF를 무시하거나 새 log를 못 읽으면 복제가 조용히 깨진다. 업그레이드 성공/실패 판단 전에 rollback window를 알아야 한다.

### 재현 또는 구체적 예제
new version에서 OFF DDL과 PK→UK switch를 실행한 뒤 성능 문제로 old binary로 원복한다. old catalog reader와 standby가 이 상태를 처리할 수 있는지 없다.

### 권고안
capability negotiation, cluster-wide enable gate, irreversible epoch와 downgrade 전환 도구를 정의한다. epoch 이후에는 full backup/resync 또는 downgrade 차단을 명시한다.

### 검증 방법
신기능 미사용·OFF 사용·RK 변경 각 시점에서 downgrade rehearsal을 한다. 지원 경로는 상태 보존, 미지원 경로는 실행 전 차단되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 15개
- 최종 리뷰 항목 수: 35개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·online DDL·bulk/direct load·병렬 apply·PITR·다중 standby 지원 여부와 정확한 문법, 실제 권한·감사·fencing·metadata API, 물리 snapshot 지원 범위, 엔진 코드와 자원/성능 수치
