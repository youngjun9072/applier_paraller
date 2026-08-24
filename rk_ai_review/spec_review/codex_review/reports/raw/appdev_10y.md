# DB를 사용하는 애플리케이션 개발자 / 10년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-23
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 장기 데이터 계약, 무중단·롤링 배포, 최악 장애에서의 앱 동작, 복구 가능성, 프로토콜·도구 호환성과 여러 버전에 걸친 지원 수명을 중점 검토했다.
- 확인하지 못한 전제: CUBRID 로그/카탈로그 버전 형식, DDL 원자성과 잠금 구현, 실제 오류 코드와 `fail_count` 정의, 드라이버·ORM 지원 범위, 혼합 버전 HA 및 downgrade 정책은 원문만으로 확인하지 못했다. 아래 구현 관련 사항은 제품이 보장해야 할 계약 또는 검증 질문이다.

## [APPDEV-10Y-01] RK 존재 조건만 있고 로그부터 failover까지 유지할 시스템 불변식이 없다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 RK 필수 조건과 4-2절의 대체 후보가 있으면 DDL 허용
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 장기 운영 애플리케이션, 복제 정합성, 장애 복구

### 문제
문서는 어느 시점에도 후보가 하나 이상 있으면 안전하다고 전제하지만, DML 생성 당시 RK와 replica 적용 당시 정의의 연결, DDL과 DML의 전역 순서, crash 재적용 시 같은 키 선택이라는 불변식을 명시하지 않는다.

### 왜 중요한가
키가 “현재 존재”하는 것과 과거 로그가 해석 가능하다는 것은 다르다. 옛 로그가 `id=10`을 담고 replica가 email RK로 바뀌면 행을 못 찾는다. 이는 앱이 성공 응답한 변경이 failover 뒤 사라지는 데이터 계약 위반이다.

### 재현 또는 구체적 예제
`account(id PK, email NOT NULL UNIQUE, balance)`에서 UPDATE(id=10), PK→email RK DDL, UPDATE(email='a@x')를 커밋한 뒤 replica를 DDL 전·후 각 지점에서 crash/restart한다. 모든 재생 경로에서 최종 balance가 같아야 하나 원문은 어떤 RK 버전으로 찾는지 없다.

### 권고안
로그 생성·전송·적용·재적용·승격 전 과정의 불변식을 규범 문장으로 추가한다. 최소한 DML에 생성 당시 RK 식별자/이전 값이 연결되고 DDL과 같은 커밋 순서로 적용되며, 미해석 로그가 있으면 승격을 막아야 한다.

### 검증 방법
PK↔UK와 UK1→UK2마다 DML/DDL 경계 전후 crash, 재시작, 중복 로그 재적용을 주입한다. 앱 성공 이력과 최종 행 checksum이 항상 일치하고 `fail_count`가 늘지 않는지 확인한다.

## [APPDEV-10Y-02] 엔진 자동 RK 선택은 장기 데이터 계약과 변경 통제에 부족하다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절의 PK 우선·여러 UK 중 엔진 선택
- 사실/추론 구분: 확인된 사실
- 영향 대상: 도메인 모델, 스키마 거버넌스, 다년간 운영 앱

### 문제
여러 UK 중 엔진이 자동 선택하며 사용자가 직접 RK를 지정할 수 없다. 어떤 키가 안정적·불변인지 아는 주체는 앱 도메인인데, 선언 순서 같은 물리적 세부사항이 복제 계약을 결정할 수 있다. 사용자 지정 RK 대안과 비지원 이유도 없다.

### 왜 중요한가
email은 유일하지만 변경 가능하고 내부 id는 불변일 수 있다. 엔진이 email을 선택하면 모든 email 변경 로그가 넓어지고, 장기적으로 email 정책 변경이 RK 변경을 강제한다. 자동 선택은 ORM이 DDL을 재정렬할 때도 흔들릴 수 있다.

### 재현 또는 구체적 예제
PK가 없는 `customer(external_id NOT NULL UNIQUE, email NOT NULL UNIQUE)`에서 external_id는 계약상 불변이고 email은 변경 가능하다. 엔진이 email을 고르면 앱의 일상 UPDATE가 RK UPDATE가 된다. 개발자는 더 적합한 external_id를 선택할 방법이 없다.

### 권고안
결정적 기본 선택 외에 명시적 RK 선택/고정 기능 또는 선택 힌트를 검토한다. 제공하지 않으면 설계 이유, 선택 지속성, 변경 가능한 자연키를 피하는 가이드를 적고 실제 RK를 배포 승인 항목으로 노출한다.

### 검증 방법
불변/가변 UK가 함께 있는 모델로 장기 변경 시뮬레이션을 한다. RK 선택·고정·변경 감사가 정책대로 작동하고 ORM DDL 재정렬에도 의도치 않게 바뀌지 않는지 확인한다.

## [APPDEV-10Y-03] OFF는 테이블 단위 데이터 소유권 분리를 만들지만 복구 모델이 없다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1·4·6절의 OFF 데이터 불일치 허용과 면책
- 사실/추론 구분: 확인된 사실
- 영향 대상: 앱 데이터 소유권, failover/failback, 지원 조직

### 문제
OFF는 각 노드가 같은 DDL에 서로 다른 데이터를 갖게 만드는 기능이다. 그러나 권위 노드, 데이터 수명, failover 후 재생성, 옛 primary 재편입, ON 복귀 시 충돌 해결을 정의하지 않는다.

### 왜 중요한가
이것은 단순 복제 설정이 아니라 데이터 소유권 계약이다. 두 노드에서 같은 PK로 다른 값이 생성되면 나중에 자동 병합할 수 없다. 앱이 캐시·세션·큐 중 어떤 의미로 사용하는지에 따라 복구 방식도 다르다.

### 재현 또는 구체적 예제
`job_queue(id PK) OFF`에서 옛 primary는 101번 작업, failover된 새 primary는 101번에 다른 작업을 만든다. failback 때 어느 101을 유지할지 없다. 둘 다 실행하면 업무가 중복되고 하나를 버리면 손실이다.

### 권고안
OFF를 재생성 가능 파생 데이터로 제한하거나 데이터 유형별 권위·폐기·재구축 계약을 요구한다. failover/failback 전 OFF 테이블을 자동 목록화하고, 재편입 시 truncate/reseed 또는 단방향 동기화 정책을 명시한다.

### 검증 방법
OFF 테이블에 동일 키 충돌과 서로 다른 DML을 만든 뒤 failover/failback한다. 공식 절차가 모호한 병합 없이 정해진 권위 데이터를 복원하고 앱 중복 처리를 방지하는지 확인한다.

## [APPDEV-10Y-04] 후보·선택 RK의 결정성, 영속성, 조회 계약이 버전 수명을 견디지 못한다

- 분류: 모호성
- 심각도: Blocker
- 근거 위치: 원문 1절의 선택 우선순위 예시와 2-3절의 ON/OFF만 조회
- 사실/추론 구분: 확인된 사실
- 영향 대상: 배포 검증, source/replica 정합성, 업그레이드

### 문제
PK 우선은 명확하지만 여러 UK의 선택은 예시일 뿐이며 재시작, 제약 rename, unload/load, 카탈로그 재구축, 버전 변경에서 유지되는지 없다. 선택된 RK를 식별하는 관리 API도 없다.

### 왜 중요한가
장기 지원 기간에는 ORM과 DB 버전이 여러 번 바뀐다. 카탈로그 열 순서가 달라져 RK가 바뀌면 대기 로그와 충돌할 수 있다. 애플리케이션 배포는 현재 RK를 확인하지 못한 채 위험 제약을 삭제할 수 있다.

### 재현 또는 구체적 예제
`member(email UK, phone UK)`를 unload/load하면서 제약 생성 순서가 바뀐다고 하자. 이전 로그는 email RK이고 복원 DB가 phone을 선택하면 archived log 적용 결과가 불명확하다.

### 권고안
영구 RK ID, 선택 알고리즘 버전과 source/replica 일치 조건을 정의한다. 실제 RK·후보·부적격 이유를 안정된 catalog/API로 제공하고 변경은 감사 이벤트와 schema version 증가를 일으키게 한다.

### 검증 방법
재시작, rename, dump/load, 물리 복원, old/new upgrade 전후에 RK API를 비교한다. 규칙에 따른 변경 외에는 ID가 유지되고 미일치 노드의 HA 편입이 차단되는지 본다.

## [APPDEV-10Y-05] 기본 ON과 single·SA·HA 계약 변화에 버전 전환 정책이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절의 기본 ON과 1·3·9절의 모드 표현
- 사실/추론 구분: 확인된 사실
- 영향 대상: 기존 앱, CI/CD, 장기 지원 버전 사용자

### 문제
기존 옵션 없는 CREATE가 ON이 되고 키 없는 테이블은 local single에서 성공하지만 HA 배포/시작에서 실패한다. 1절은 HA 외 모두 single이라 하고 9절은 SA를 별도 모드로 쓴다. 기존 객체의 업그레이드 초기값도 없다.

### 왜 중요한가
같은 migration이 환경별로 다른 결과를 내면 무중단 배포가 불가능하다. 기능 플래그나 호환 기간 없이 기본 계약을 바꾸면 구버전 앱이 새 DB에서 예기치 않게 HA 시작을 막을 수 있다.

### 재현 또는 구체적 예제
구버전 앱이 매 배포 `CREATE TABLE build_stage(raw VARCHAR(1000));`를 실행한다. new single에서는 ON으로 성공하지만 production HA에서는 실패한다. old DB에서 존재하던 build_stage가 upgrade 후 ON/OFF 중 무엇인지도 없다.

### 권고안
모드 정의·확인 명령과 SQL 허용 행렬을 제공한다. 기존 객체 초기화, deprecation 경고, compatibility mode, 기능 활성화 시점을 버전별로 정의하고 CI dry-run을 지원한다.

### 검증 방법
old schema/old app, old schema/new app, new schema/old app 조합을 single·SA·HA에서 실행한다. 계약된 기간 동안 무수정 호환 또는 명확한 사전 차단이 되는지 확인한다.

## [APPDEV-10Y-06] 새 SQL 속성의 round-trip과 도구 호환 계약이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절의 CREATE/ALTER 문법과 2-3절 조회 예
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ORM, schema diff, migration generator, 백업 도구

### 문제
`REPLICATION`의 공식 grammar, 다른 옵션과 순서, `SHOW CREATE` round-trip, 모르는 구버전 도구의 처리 정책이 없다. ORM introspection이 속성을 보존할 수 있는 표준 카탈로그 필드도 계약되지 않았다.

### 왜 중요한가
schema-as-code 도구가 OFF를 모르면 테이블 재생성 시 기본 ON으로 바꾸거나 매 실행마다 잘못된 diff를 만든다. 수년에 걸친 자동화에서는 사람이 모든 DDL을 검토한다고 가정할 수 없다.

### 재현 또는 구체적 예제
`cache REPLICATION=OFF`를 introspect해 ORM migration을 재생성하고 새 DB에 적용한다. 생성 SQL에서 OFF가 빠지면 테스트는 통과해도 failover 데이터 계약이 달라진다.

### 권고안
grammar와 canonical 출력, catalog API, tool capability negotiation을 정의한다. 지원 ORM/driver 버전과 미지원 도구의 raw SQL/검증 hook을 제공하고 상태 누락 시 조용한 기본값 대신 오류를 검토한다.

### 검증 방법
CREATE→introspect→generate→recreate를 반복하고 ON/OFF 및 실제 RK가 보존되는지 본다. old tool이 새 속성을 만날 때 계약대로 경고/차단하는지 확인한다.

## [APPDEV-10Y-07] RK 변경 상태표가 타입·collation·rename·NULL과 복합 키를 포함하지 않는다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 단일 PK/UK 추가·삭제 예
- 사실/추론 구분: 확인된 사실
- 영향 대상: 장기 스키마 진화, 다국어 앱, 복제 정합성

### 문제
컬럼 rename, widening/narrowing, collation 변경, `NOT NULL` 제거, 복합 키 일부 교체, 제약 rename, 여러 후보 동시 변경의 전이가 없다. “다른 후보가 있으면 모든 DDL 허용”은 전체 후보를 동시에 무효화하는 SQL도 포함하는지 모호하다.

### 왜 중요한가
문자열 비교 규칙이 바뀌면 이전에는 다른 두 값이 같아져 UNIQUE 구축이 실패할 수 있다. NULL 허용은 RK 자격을 잃게 한다. 장기 앱은 이런 변경을 피할 수 없으므로 정확한 online 경로가 필요하다.

### 재현 또는 구체적 예제
`tenant_user(tenant_id INT NOT NULL, login VARCHAR(50) NOT NULL, UNIQUE(tenant_id,login))`에서 login을 VARCHAR(100)·새 collation으로 바꾸고 rename한다. 데이터 충돌, RK ID 유지, old app 쿼리 결과가 모두 불명확하다.

### 권고안
모든 키/컬럼 DDL의 전이 표에 모드, 사전 데이터 검사, lock, RK 전후, 로그 호환, rollback을 적는다. expand–backfill–validate–switch–contract 단계와 각 단계의 구/신 앱 호환성을 제공한다.

### 검증 방법
단일·복합 숫자/문자 키에서 표의 변경을 실행하고 old/new 앱을 동시에 구동한다. 성공·실패 후 양 노드 스키마, RK와 CRUD가 완전한 상태인지 확인한다.

## [APPDEV-10Y-08] 복합 ALTER 원자성만으로는 무중단 배포 안전성이 확보되지 않는다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 DROP+ADD
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: zero-downtime migration, 대형 테이블, rollback

### 문제
한 SQL로 옛 키를 삭제하고 새 키를 추가하라고 하지만 새 인덱스 구축 시간, DML lock, replica apply 실패, 앱 버전 호환, rollback 가능성을 정의하지 않는다. SQL 원자성만 있어도 장시간 정지는 남는다.

### 왜 중요한가
수억 행 UK 검증은 오래 걸리고 중복 한 건으로 실패한다. source 성공 뒤 replica 디스크 부족으로 실패하면 schema split이 생길 수 있다. 옛 앱이 PK를 참조하면 성공한 교체도 장애가 된다.

### 재현 또는 구체적 예제
5억 행 `users(id PK,email)`에서 email 중복을 정리하지 않고 DROP PK+ADD UK를 실행한다. DDL이 20분 잠그거나 replica에서 공간 부족으로 실패할 수 있다. 앱의 `findById(id)`도 동시에 배포돼야 한다.

### 권고안
새 후보를 online 구축·검증한 뒤 짧은 원자 switch를 제공하고 옛 키는 호환 기간 유지하도록 안내한다. 양 노드 실패 원자성, lock budget, abort, down migration과 재시도 조건을 명시한다.

### 검증 방법
대형 부하에서 중복, lock timeout, replica disk full, process crash를 주입한다. 요청 오류율·lock 시간과 양 노드 상태가 한도를 만족하고 rollback 후 old app가 정상인지 확인한다.

## [APPDEV-10Y-09] 장기 트랜잭션과 DDL의 직렬화·재시도 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 운영 중 DDL/DML 복제
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 결제·배치 트랜잭션, retry 정책, 복제 정합성

### 문제
DDL 전 시작해 DDL 후 커밋하는 트랜잭션이 어느 schema/RK 버전을 쓰는지 없다. 신규 DML 차단, 기존 transaction drain, timeout/deadlock, commit 결과와 retryability도 미정이다.

### 왜 중요한가
앱은 네트워크 단절로 commit 결과를 모를 수도 있다. DDL과 겹친 결제를 무조건 재시도하면 이중 청구되고 재시도하지 않으면 누락될 수 있다. 오류 코드와 idempotency 계약이 필요하다.

### 재현 또는 구체적 예제
결제 A가 id RK로 balance를 차감하고 응답 전에 연결이 끊긴다. 동시에 B가 email RK로 교체한다. A가 source에서 커밋됐는지와 replica에 어느 키로 적용되는지가 불명확하면 재시도 판단이 불가능하다.

### 권고안
DDL fence, transaction drain, schema version pinning, commit-unknown 처리와 오류별 retryable 속성을 정의한다. 앱에는 idempotency key와 결과 조회 API 패턴을 권장한다.

### 검증 방법
DDL과 장기 transaction을 교차하고 commit 직전/후 연결을 끊는다. idempotent 재시도 후 업무 이벤트가 정확히 한 번 반영되고 failover 뒤도 같은지 확인한다.

## [APPDEV-10Y-10] 최악 장애에서 승격·재승격 가능한 상태 집합이 정의되지 않았다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 RK 변경과 7절의 HA 전환 검사
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 자동 failover, 앱 connection routing, 재해 복구

### 문제
RK DDL이 생성·전송·적용되는 각 단계에서 source와 replica가 연속으로 장애 날 때 어떤 노드를 승격할 수 있는지 없다. DDL apply 중 crash, 강제 failover 뒤 old primary 재편입, failback 기준도 없다.

### 왜 중요한가
최악 장애는 정상 순서를 깨뜨린다. 새 primary가 옛 RK로 쓰기 시작한 뒤 새 RK인 노드가 다시 승격되면 로그 의미가 갈라질 수 있다. connection router가 접속에 성공해도 앱 데이터는 안전하지 않다.

### 재현 또는 구체적 예제
source가 id→email RK DDL을 커밋하고 replica가 절반 적용 중 source 장애, replica 승격 직후 replica도 장애, old source 복구 순으로 진행한다. 어느 노드가 권위인지와 RPO가 없다.

### 권고안
RK/schema version과 적용 LSA별 승격 가능 상태도를 제공한다. 불일치 시 자동 승격을 차단하고 강제 절차, 데이터 손실 범위, full rebuild 조건과 앱 write fencing token을 정의한다.

### 검증 방법
각 로그 단계와 두 노드 연속 장애를 fault injection한다. split-brain 쓰기가 차단되고 선택 노드의 version/LSA가 증명되며 복구 후 앱 데이터 checksum이 일치하는지 확인한다.

## [APPDEV-10Y-11] ON→OFF 컷오버와 재가입 프로토콜이 없어 장기적으로 되돌릴 수 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2-2절의 HA 중 ON→OFF 허용·OFF→ON 금지
- 사실/추론 구분: 확인된 사실
- 영향 대상: 기능 플래그, failover/failback, 데이터 재동기화

### 문제
OFF DDL 이전 대기 DML이 어디까지 적용되는지, OFF 상태 데이터가 언제 폐기되는지, ON으로 복귀할 때 baseline과 증분을 어떻게 맞추는지 없다. 설정 변경이 사실상 비가역적이다.

### 왜 중요한가
장기 운영에서는 일시적 비용 절감을 위해 OFF했다가 정책을 되돌릴 수 있어야 한다. 명확한 컷오버 LSA가 없으면 노드 차이가 정상 OFF인지 비정상 누락인지 판단할 수 없다.

### 재현 또는 구체적 예제
replica가 이벤트 80까지 적용한 상태에서 ON→OFF 후 source가 81~100을 기록하고 failover된 노드가 101~120을 만든다. ON 복귀 때 어느 세트를 기준으로 할지 없다.

### 권고안
OFF 커밋 LSA 이전 로그의 완전 적용, 이후 로그 제외를 계약하고 상태 전환을 감사한다. 권위 snapshot→검증→증분 catch-up→짧은 write fence→ON의 테이블 단위 rejoin 프로토콜을 제공한다.

### 검증 방법
apply 지연, failover와 양쪽 쓰기를 포함해 OFF lifecycle을 실행한다. 공식 rejoin 후 1~120 중 정책상 권위 행만 존재하고 새 쓰기가 정상 복제되는지 확인한다.

## [APPDEV-10Y-12] 가변 복합 RK는 앱 식별자 안정성과 성능 SLO를 동시에 위협한다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 1절의 PK/NOT NULL UK 규칙과 단일 열 중심 예시
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: API 식별자, ORM cache, 복제 지연, 비용

### 문제
복합 키 지원 한계, 가변 문자열·collation 의미, 키 값 UPDATE의 before/after 규칙, 로그·인덱스 비용이 없다. 자연키를 RK로 고르면 앱의 흔한 프로필 변경이 복제 식별자 변경이 된다.

### 왜 중요한가
3개 긴 문자열은 정수 id보다 로그와 비교 비용이 크다. replica lag가 쓰기 유입보다 빨리 증가하면 failover RPO가 악화된다. ORM identity map도 PK 변경을 안정적으로 처리하지 못할 수 있다.

### 재현 또는 구체적 예제
`inventory(region VARCHAR(100),warehouse VARCHAR(100),sku VARCHAR(500), UNIQUE(...))`를 RK로 초당 1만 qty UPDATE하고 sku도 변경한다. replica에는 옛 sku만 있으므로 before key가 필요하며 로그 크기 제한도 고려해야 한다.

### 권고안
지원 타입/열/바이트 한도, before/after 적용, immutable surrogate key 권장 기준을 명시한다. 키 형태별 로그 증폭·apply TPS·lag SLO와 앱 cache refresh 패턴을 제공한다.

### 검증 방법
정수 PK와 1/3열 문자열 UK로 동일 API 부하를 장시간 실행한다. 로그 bytes, 응답 지연, apply lag와 키 변경 정확성이 수용 기준 내인지 확인한다.

## [APPDEV-10Y-13] FK 규칙이 전체 의존 그래프·CASCADE·상태 전환을 보존하지 못한다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식이 참조하는 부모도 ON이어야 한다는 규칙
- 사실/추론 구분: 확인된 사실
- 영향 대상: 도메인 aggregate, ORM cascade, 데이터 정합성

### 문제
FK 생성 시 직접 부모만 다루며 기존 부모 ON→OFF, OFF 자식→ON 부모, 다단계·순환 FK, `ON DELETE/UPDATE CASCADE`와 SET NULL을 다루지 않는다. DDL 이후에도 그래프 불변식이 유지되는지 없다.

### 왜 중요한가
부모 DML이 복제되지 않고 자식 cascade만 복제되면 replica 관계가 달라진다. DB와 ORM이 동시에 cascade하면 중복 효과나 다른 순서가 생길 수 있다. 다단계 그래프는 한 테이블 전환이 여러 서비스를 깨뜨린다.

### 재현 또는 구체적 예제
`tenant ON → customer ON → order ON`이 CASCADE로 연결됐다. customer를 OFF로 바꾸고 tenant를 삭제하면 source와 replica에서 customer/order가 어떤 조합으로 남는지 없다. 순환 FK가 있으면 검사 순서도 중요하다.

### 권고안
전체 FK 의존 그래프에 대해 ON/OFF 불변식과 모든 referential action을 정의한다. 상태 전환은 영향 그래프를 사전 출력하고 위험 조합을 원자적으로 거부하며 ORM cascade 권장안을 제공한다.

### 검증 방법
2~3단계, 순환, 각 cascade 옵션 그래프에서 상태 전환과 DML/failover를 실행한다. 양 노드의 모든 참조 무결성과 ORM transaction 결과가 같아야 한다.

## [APPDEV-10Y-14] OFF 의존 VIEW는 API의 장기 의미론 버전을 깨뜨린다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절의 VIEW 제약 없음과 결과 불일치 면책
- 사실/추론 구분: 확인된 사실
- 영향 대상: 조회 API, 리포트 계약, downstream 소비자

### 문제
DDL이 존재하므로 VIEW를 쓸 수 있다고 하지만 failover 후 동일 쿼리가 다른 의미를 갖는다. 직접·간접 의존성, API fallback, 캐시 무효화와 데이터 freshness 표시가 없다.

### 왜 중요한가
API는 수년간 같은 응답 의미를 유지해야 한다. 오류가 아닌 200 빈 목록이나 다른 합계는 downstream이 정상 데이터로 저장한다. 복구 후에도 잘못된 캐시가 남을 수 있다.

### 재현 또는 구체적 예제
`orders ON`과 `discount OFF` 기반 `v_payable`을 청구 API가 읽고 결과를 캐시한다. failover 후 9,000원이 10,000원으로 바뀌고 캐시가 지속되면 DB 복구 뒤에도 오답이 제공된다.

### 권고안
OFF 의존 VIEW를 재귀 조회·경고하고 중요한 API에서는 금지할 수 있게 한다. failover 시 readiness, degraded 응답, freshness 메타데이터와 cache purge 계약을 제공한다.

### 검증 방법
중첩 VIEW와 캐시된 API를 failover/failback한다. 앱이 조용한 정상 응답 대신 정의한 degraded 동작을 하고 복구 뒤 캐시와 결과가 정상화되는지 확인한다.

## [APPDEV-10Y-15] HA 사전 검사가 배포 게이트로 사용할 만큼 원자적·구조화되지 않았다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 7절의 시작 시 검사와 “파일 리스트” 출력
- 사실/추론 구분: 확인된 사실
- 영향 대상: CI/CD, GitOps, 대규모 schema, 변경 승인

### 문제
검사가 한 schema snapshot을 보는지, 검사와 시작 사이 DDL을 막는지, 전체 위반을 반환하는지 없다. “파일 리스트”는 안정된 API가 아니며 비용·timeout·오류 코드도 없다.

### 왜 중요한가
자동 배포는 검사 결과를 기계적으로 판정해야 한다. 검사 직후 다른 migration이 실행되면 통과 token이 무효가 될 수 있다. 첫 오류만 주면 대규모 서비스에서 반복 배포가 필요하다.

### 재현 또는 구체적 예제
서비스 A는 RK 없는 `stage`, 서비스 B는 OFF 부모 FK를 동시에 배포한다. preflight 중 또 다른 DDL이 실행된다. 기대 결과는 같은 schema version 기준의 전체 owner/table/constraint/사유 목록과 시작 직전 재검증이다.

### 권고안
읽기 전용 dry-run API, schema version/token, snapshot 또는 DDL fence를 제공한다. JSON 결과에 모든 위반, 안정된 코드, 권장 조치와 비용 지표를 넣고 배포 gate 예를 제공한다.

### 검증 방법
동시 migration과 1만 테이블에서 preflight를 반복한다. 결과가 일관되고 CI가 위반을 정확히 차단하며 token이 stale이면 시작이 거부되는지 확인한다.

## [APPDEV-10Y-16] fail_count를 SLO와 데이터 복구로 연결하는 사고 대응 계약이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체에서 `fail_count` 정의 및 기존 불일치 복구 부재
- 사실/추론 구분: 확인된 사실
- 영향 대상: 앱 SRE, 고객지원, 데이터 정합성, 감사

### 문제
카운터의 단위·증가·보존·리셋, 테이블/transaction/LSA 연계와 경보 기준이 없다. 새 기능이 향후 실패를 막아도 기존 누락을 탐지·교정하지 않는다. OFF의 의도된 차이와 사고도 구별되지 않는다.

### 왜 중요한가
성공 응답을 보낸 결제가 standby에 없다면 가용성 문제가 아니라 데이터 사고다. 카운터가 안정돼도 오염은 남으며 지원팀은 영향 고객 목록과 복구 증거가 필요하다.

### 재현 또는 구체적 예제
source 주문 10은 PAID, replica는 PENDING이고 `fail_count=5`다. upgrade 후 카운터 증가가 0이어도 failover하면 고객 상태가 되돌아간다. OFF cache 차이는 경보에서 제외해야 한다.

### 권고안
오류 코드·table·LSA별 metric과 SLO, 자동 write/failover fence 임계값을 정의한다. ON 테이블 checksum, 영향 행 추출, 재동기화, 고객 영향 확인, 승인 리셋과 사후 감사 runbook을 제공한다.

### 검증 방법
누락·중복·오래된 값·DDL 실패와 정상 OFF 차이를 주입한다. 경보가 사고만 탐지하고 runbook 후 데이터·API·감사 증적이 완전한지 확인한다.

## [APPDEV-10Y-17] unload/load 모순과 PITR 이후 RK 연속성이 복구를 차단한다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 필드 없음=ON, 9절의 정보 없음=OFF
- 사실/추론 구분: 확인된 사실
- 영향 대상: 재해 복구, 논리·물리 백업, archived log 재생

### 문제
동일한 구버전 파일을 본문은 ON, 요약은 OFF로 정의한다. 선택된 RK와 선택 알고리즘 버전이 unload/물리 백업/PITR에서 보존되는지, 복원 뒤 과거 로그를 해석할 수 있는지도 없다.

### 왜 중요한가
ON이면 키 없는 테이블 때문에 HA 시작 실패, OFF이면 업무 데이터 미복제다. 복원 DB가 다른 UK를 RK로 선택하면 백업 이후 archived DML 로그를 잘못 적용할 수 있어 재해 복구 자체가 성립하지 않는다.

### 재현 또는 구체적 예제
구버전 키 없는 `legacy_log`와 UK 두 개인 `member`를 unload한 뒤 새 버전에 load하고 이후 로그를 적용한다. legacy ON/OFF가 상충하고 member의 옛 RK와 새 RK 일치도 보장되지 않는다.

### 권고안
모순을 제거하고 필드 없음은 명시 선택/경고로 처리한다. 상태와 영구 RK ID·알고리즘 버전을 backup manifest에 저장하고 논리·물리·PITR별 복원/검증·downgrade 조건을 명시한다.

### 검증 방법
old/new unload, full backup와 여러 시점 PITR 후 archived log를 적용한다. ON/OFF, RK, schema version과 최종 앱 checksum이 원본과 같은지 확인한다.

## [APPDEV-10Y-18] 롤링 업그레이드의 로그 프로토콜·기능 활성화·rollback 경계가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절의 새 문법/카탈로그와 8절의 파일 호환만 언급
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 무중단 업그레이드, mixed-version HA, 장기 지원

### 문제
구버전 노드가 새 DDL/RK 로그를 읽는지, 노드 업그레이드 순서, 새 기능을 활성화할 최소 버전, downgrade 불가 지점이 없다. 프로토콜 negotiation과 넓은 RK 성능 회귀 기준도 없다.

### 왜 중요한가
old replica가 `REPLICATION=OFF`를 무시하거나 parse 실패하면 schema split/apply 중단이 생긴다. 한 번 새 형식 로그가 생기면 binary downgrade가 과거 로그를 못 읽을 수 있다. 이는 서비스 중단 여부를 결정한다.

### 재현 또는 구체적 예제
old replica를 둔 new source에서 OFF CREATE와 PK→UK 변경을 실행한 뒤 new source 장애로 old replica를 승격한다. 동시에 복합 문자열 RK 부하로 lag가 증가한다. 지원 여부와 rollback 경계가 모두 없다.

### 권고안
버전·driver·ORM 호환 행렬, 노드 순서, capability negotiation, feature gate와 irreversible epoch를 정의한다. mixed-version failover와 키 폭별 장기 부하를 출시 필수 시험으로 둔다.

### 검증 방법
old/new 모든 방향에서 DDL/DML/restart/failover/downgrade를 시험한다. 미지원 작업은 사전 차단되고 지원 경로는 데이터 일치와 lag SLO를 만족하는지 확인한다.

## [APPDEV-10Y-19] 오류·SQL 예제가 지원 가능한 공개 계약 수준이 아니다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2·4·5절의 단순 ERROR, 후행 쉼표, 불완전 `...`, `CRATE TABLE`
- 사실/추론 구분: 확인된 사실
- 영향 대상: 앱 오류 처리, 자동화, 기술지원, 문서 유지보수

### 문제
오류 코드/SQLSTATE, retryable 여부, transaction rollback 범위 없이 `ERROR`만 제시한다. 예시에는 parser 오류를 내는 후행 쉼표, 불완전 제약명, 오탈자가 있다. 예제 번호와 실제 전제도 일관되지 않다.

### 왜 중요한가
장기 지원 앱은 메시지 문자열이 아니라 안정된 코드로 분기한다. lock timeout과 영구 RK 위반을 구분하지 못하면 무한 재시도 또는 불필요한 배포 중단이 난다. 잘못된 예제는 회귀 테스트 근거가 될 수 없다.

### 재현 또는 구체적 예제
유일한 RK 삭제와 lock timeout이 모두 `ERROR`라면 migration runner는 둘을 같은 정책으로 처리한다. 전자는 코드 수정이 필요하고 후자는 재시도 가능할 수 있다. `CREATE TABLE(a INT,)`는 RK 검사 전에 parser에서 실패한다.

### 권고안
버전 안정 오류 taxonomy, SQLSTATE, retryability, rollback·지원 수명을 정의한다. 모든 예제를 완전한 setup/up/down과 전체 출력으로 고치고 문서 CI에서 실제 실행한다.

### 검증 방법
모든 실패 유형을 driver 버전별로 발생시켜 코드·rollback 상태가 안정적인지 본다. 코드 블록 자동 실행과 링크된 app handler 테스트를 릴리스 gate로 둔다.

## [APPDEV-10Y-20] 기능의 도입부터 폐기까지 지원하는 수명주기 runbook이 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 3·7·8·9절의 단편적인 전환·복원·요약
- 사실/추론 구분: 확인된 사실
- 영향 대상: 장기 운영 앱 팀, 플랫폼 팀, 변경 승인자

### 문제
인벤토리, 데이터 정리, expand/contract 앱 배포, RK 전환, HA 검증, failover/failback, rollback, 백업 복원, 기능 deprecation이 하나의 장기 절차로 연결되지 않는다. 각 단계의 책임자와 증거도 없다.

### 왜 중요한가
애플리케이션과 DB는 같은 순간에 교체되지 않으며 여러 버전이 공존한다. 단계별 호환·중단 조건이 없으면 옛 앱이 새 스키마를 못 읽거나 새 앱이 failover된 옛 스키마를 만난다. 몇 년 뒤 담당자가 바뀌어도 복구 가능해야 한다.

### 재현 또는 구체적 예제
id PK에서 login_email RK로 옮길 때 nullable 열 추가→dual-write→백필→검증→NOT NULL UK→RK switch→failover drill→read 전환→옛 키 제거→downgrade 종료 선언이 필요하다. 원문은 DROP+ADD 한 줄만 제공한다.

### 권고안
버전 공존, 승인자, 관측 지표, 성공/중단·rollback 조건과 증거 보존을 포함한 수명주기 runbook을 작성한다. 기능 활성화, 안정화, 옛 계약 deprecation과 지원 종료 시점을 명시한다.

### 검증 방법
old/new 앱·DB를 함께 띄운 staging에서 runbook 전체를 수행하고 각 단계 failover와 rollback을 주입한다. 다른 팀이 구두 지원 없이 전환·복원하고 checksum과 API 계약을 증명할 수 있는지 확인한다.

## [APPDEV-10Y-21] REPLICATION 정책 변경 권한이 데이터 보호 거버넌스와 분리되어 있다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절은 사용자가 정책을 설정·변경한다고만 한다.
- 사실/추론 구분: 확인된 사실
- 영향 대상: 플랫폼 팀, 애플리케이션 owner, 감사·보안

### 문제
일반 schema ALTER와 ON→OFF가 같은 권한인지, domain owner 승인과 감사 이벤트가 있는지 없다.

### 왜 중요한가
OFF는 failover 보호를 낮춘다. 여러 팀이 한 DB를 쓰면 한 팀의 변경이 공통 RPO와 규제 준수를 깨뜨릴 수 있다.

### 재현 또는 구체적 예제

```sql
GRANT ALTER ON payment TO service_owner;
ALTER TABLE payment REPLICATION=OFF;
```

성공 여부와 policy approval이 미정이다.

### 권고안
정책 변경 privilege를 분리하고 owner·data class 기반 admission, two-person approval, immutable audit를 제공한다.

### 검증 방법
조직 역할별 허용 matrix와 audit export를 시험하고 무승인 OFF가 production gate를 통과하지 않는지 확인한다.

## [APPDEV-10Y-22] ON/OFF 혼합 트랜잭션은 서비스 불변식의 복제 경계를 깨뜨린다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절·4절은 테이블별로 DML을 선택 복제한다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: domain transaction, failover, 데이터 정합성

### 문제
source transaction이 ON과 OFF를 함께 commit하면 replica에는 부분 transaction만 나타날 수 있다.

### 왜 중요한가
업무 원자성은 DB transaction 단위로 설계된다. HA가 이를 잘라내면 회계·outbox·상태 machine이 failover 후 불완전하다.

### 재현 또는 구체적 예제

```sql
BEGIN;
INSERT INTO orders(id,status) VALUES (1,'PAID'); -- ON
INSERT INTO event_outbox(id,event) VALUES (1,'paid'); -- OFF
COMMIT;
```

새 primary에는 주문만 남을 수 있다.

### 권고안
strict HA profile에서 mixed-policy transaction을 금지하고 runtime에 touched table policy를 검사한다. 의도적 혼합은 별도 saga/rebuild 계약을 요구한다.

### 검증 방법
trigger·stored logic까지 포함한 transaction graph에서 위반을 탐지하고 commit/rollback/failover 결과를 검증한다.

## [APPDEV-10Y-23] 파티션·샤딩 키와 RK의 결합 계약이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 table만 다루며 2-3절에는 `partitioned` metadata가 보인다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 관련 객체와 분산 기능 지원 범위 확인 필요
- 영향 대상: 대규모 서비스, data routing, 복제 정합성

### 문제
RK가 partition/shard routing key를 포함해야 하는지, local UK를 global row identity로 쓸 수 있는지, 재배치 중 epoch가 어떻게 변하는지 없다.

### 왜 중요한가
같은 local key가 여러 partition에 있으면 key만으로 행을 확정하지 못한다. routing과 replication identity가 엇갈리면 다른 shard의 행을 찾을 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE tenant_event (
 tenant_id INT NOT NULL, local_id BIGINT NOT NULL,
 payload VARCHAR(1000), UNIQUE(tenant_id,local_id)
) REPLICATION=ON;
```

partition key가 tenant_id일 때 composite order와 global uniqueness 계약이 없다.

### 권고안
지원 topology별 RK에 포함해야 할 routing identity, repartition barrier, global/local uniqueness를 명시한다.

### 검증 방법
지원 partition move/split과 concurrent DML을 수행해 정확한 shard/row 적용과 failover를 검증한다.

## [APPDEV-10Y-24] trigger·cascade·procedure의 내부 DML provenance가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4~5절은 직접 DML과 FK 일부만 설명한다.
- 사실/추론 구분: 확인이 필요한 질문 — 관련 기능 지원과 현행 복제 방식 확인 필요
- 영향 대상: domain logic, log protocol, 애플리케이션

### 문제
서버 내부 DML이 ON/OFF 경계를 넘을 때 원본 결과를 기록할지 standby에서 logic을 재실행할지 없다.

### 왜 중요한가
logic version이 노드마다 다르면 재실행 결과도 다르다. row log와 재실행 중복은 이중 side effect를 만든다.

### 재현 또는 구체적 예제
orders ON insert가 audit OFF를 쓰는 trigger를 가진다고 하자.

```sql
INSERT INTO orders(id,status) VALUES (2,'NEW');
SELECT COUNT(*) FROM audit WHERE order_id=2;
```

failover result가 미정이다.

### 권고안
generated DML provenance, deterministic requirement, log/re-execution, trigger suppression과 version gate를 규정한다.

### 검증 방법
old/new trigger version과 ON/OFF/cascade 조합에서 실행 횟수와 row checksum을 비교한다.

## [APPDEV-10Y-25] bulk·TRUNCATE·CTAS가 transaction과 log pressure를 어떻게 만드는지 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문은 모든 DDL과 ON DML을 구분하지만 경계·대량 명령은 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: batch platform, replication capacity, OFF local data

### 문제
bulk API 일부 성공, TRUNCATE의 분류, CTAS 데이터 복제, backpressure와 cancel contract가 없다.

### 왜 중요한가
대량 작업 하나가 log retention과 replica lag SLO를 무너뜨리며 OFF local data를 뜻밖에 삭제할 수 있다.

### 재현 또는 구체적 예제

```sql
INSERT INTO archive SELECT * FROM orders;
TRUNCATE TABLE local_cache;
```

ON/OFF 결과와 log byte가 미정이다.

### 권고안
명령별 atomicity·logging·backpressure·throttle·cancel과 OFF 결과를 정의하고 capacity admission을 제공한다.

### 검증 방법
production 규모 bulk 중 network lag, cancel, unique error를 주입해 source/replica와 client count를 확인한다.

## [APPDEV-10Y-26] 다중 서비스의 schema ownership과 RK 변경 승인 경계가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문은 table 단위 변경만 설명하고 dependency owner는 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 마이크로서비스, platform governance, CI/CD

### 문제
한 table의 RK를 다른 서비스가 join·FK·CDC key로 사용할 수 있으나 변경 영향 owner를 찾는 방법이 없다.

### 왜 중요한가
DB DDL은 성공해도 downstream API와 event consumer가 깨질 수 있다. 공유 schema에서는 기술적 허용과 조직적 안전이 다르다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_customer_email UNIQUE(email);
```

orders service와 analytics consumer의 승인 필요 여부가 보이지 않는다.

### 권고안
table/RK owner와 consumer registry, dependency graph, change notification, compatibility approval을 migration gate에 연결한다.

### 검증 방법
여러 service fixture에서 RK change proposal이 모든 registered consumer test와 approval 없이는 배포되지 않는지 확인한다.

## [APPDEV-10Y-27] schema epoch가 prepared plan·ORM cache까지 전달되지 않는다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 온라인 RK 변경을 허용하지만 client cache는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: driver, connection pool, ORM, app fleet

### 문제
서버 catalog가 바뀌어도 오래된 prepared statement와 metadata cache가 구 column/RK 정의를 사용할 수 있다.

### 왜 중요한가
fleet 일부 connection만 실패하는 간헐 장애가 생기며 DDL 성공만으로 rollout readiness를 판단할 수 없다.

### 재현 또는 구체적 예제

```sql
PREPARE p FROM 'UPDATE customer SET name=? WHERE id=?';
ALTER TABLE customer RENAME COLUMN id AS customer_id;
EXECUTE p USING 'Kim',10;
```

rebind·error·pool recycle contract가 없다.

### 권고안
schema epoch를 driver-visible하게 하고 plan invalidation, retry-safe code, pool drain, ORM refresh 요구를 정의한다.

### 검증 방법
multi-version app fleet의 cached plan 중 DDL을 실행해 stale execution이 없고 정해진 recovery가 되는지 확인한다.

## [APPDEV-10Y-28] CDC event key와 RK evolution의 호환성 정책이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문은 HA RK만 다루고 외부 change consumer는 없다.
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID CDC 및 연동 제품 범위 확인 필요
- 영향 대상: event streaming, data platform, downstream services

### 문제
RK 전환이 CDC partition key·dedup key를 바꾸는지, OFF DML을 CDC가 받는지 없다.

### 왜 중요한가
event key가 바뀌면 per-entity order와 exactly-once approximation이 깨진다. consumer migration은 DB와 별도 수명주기를 가진다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE orders DROP PRIMARY KEY,
 ADD CONSTRAINT uk_external UNIQUE(external_id);
UPDATE orders SET status='PAID' WHERE id=10;
```

event key의 old/new schema가 없다.

### 권고안
HA RK와 CDC identity를 분리 또는 명시 연결하고 schema event, dual-key transition, consumer compatibility window를 정의한다.

### 검증 방법
지원 CDC pipeline에서 RK 전환 전후 ordering, duplicate, partition assignment와 consumer rollback을 검증한다.

## [APPDEV-10Y-29] client routing이 split-brain fencing을 보장할 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 failover 설명에는 old primary connection과 network partition이 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: driver, service mesh, connection pools, 데이터 정합성

### 문제
일부 pool이 old primary에 남고 다른 pool이 new primary로 가면 양쪽 write가 가능할 수 있다.

### 왜 중요한가
DNS/VIP 갱신보다 connection 수명이 길다. RK는 conflict resolution을 제공하지 않는다.

### 재현 또는 구체적 예제

```sql
-- old primary
UPDATE balance SET amount=90 WHERE id=1;
-- new primary
UPDATE balance SET amount=80 WHERE id=1;
```

stale write 거부가 필요하다.

### 권고안
server term fencing, driver role handshake, stale connection eviction, non-retryable stale-primary code와 divergence quarantine을 규정한다.

### 검증 방법
pool 일부를 old node에 고정한 failover test에서 old write가 모두 거부되고 재시도로 중복되지 않는지 확인한다.

## [APPDEV-10Y-30] commit 성공의 RPO와 read-after-write token이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 failover 결과는 최근 commit 가시성을 정의하지 않는다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 사용자 경험, API consistency, distributed workflow

### 문제
성공 응답 직후 failover하면 새 primary에 write가 있는지, app이 특정 log position까지 기다릴 수 있는지 없다.

### 왜 중요한가
이전 값을 읽으면 사용자 재시도·보상 transaction이 중복 side effect를 낸다.

### 재현 또는 구체적 예제

```sql
UPDATE profile SET nickname='neo' WHERE id=7;
COMMIT;
-- 즉시 failover 후 SELECT
```

`neo` 가시성 보장이 미정이다.

### 권고안
commit ack 단계, mode별 RPO, write LSA/token과 새 primary catch-up wait API를 정의한다.

### 검증 방법
commit pipeline 각 지점에 장애를 주입해 token wait, API response와 최종 side effect를 검증한다.

## [APPDEV-10Y-31] RK telemetry의 개인정보와 cardinality budget이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문은 오류 상세·관측 API에 RK 값을 어떻게 노출할지 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: observability platform, 개인정보, 비용

### 문제
email/전화 RK 원문을 trace label로 쓰면 개인정보 유출과 high-cardinality 비용을 동시에 만든다.

### 왜 중요한가
대규모 fleet에서는 metric cardinality가 폭증하고 log가 여러 지역으로 복제될 수 있다.

### 재현 또는 구체적 예제

```sql
UPDATE member SET state='A' WHERE email='person@example.com';
```

DB event와 app trace correlation 방식이 없다.

### 권고안
bounded event ID와 keyed hash를 사용하고 원문 key를 metric/trace label에서 금지한다. region·retention·break-glass access를 정한다.

### 검증 방법
대량 고유 RK 오류를 발생시켜 개인정보 scan, cardinality, storage cost와 correlation 성공률을 측정한다.

## [APPDEV-10Y-32] RK DDL의 자원 admission이 애플리케이션 보호 장치와 연결되지 않는다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 4-2절은 key 추가를 허용하지만 대형 작업 자원·진행·취소는 없다.
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: app SLO, connection pools, platform capacity

### 문제
index build가 CPU/disk/log를 고갈하면 pool saturation과 retry storm이 발생한다. DB와 app의 보호 장치가 별개다.

### 왜 중요한가
작은 migration이 전체 fleet 장애로 증폭될 수 있다. cancel 후 cleanup 동안도 부하가 지속될 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE order_10b ADD CONSTRAINT uk_external UNIQUE(external_id);
```

capacity와 traffic admission 기준이 없다.

### 권고안
DB preflight/throttle/progress와 app circuit breaker, pool 격리, retry budget, automated abort SLO를 하나의 runbook으로 연결한다.

### 검증 방법
production-sized load에서 migration 중 자원 고갈을 주입하고 p99·error·pool·lag가 abort 기준대로 제어되는지 본다.

## [APPDEV-10Y-33] replica topology와 retention 비용이 RK epoch 수명에 연결되지 않았다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절은 RK 변경을 허용하지만 다중/지연 replica와 log retention은 없다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: multi-region DR, 플랫폼 비용, 복구

### 문제
가장 느린 replica가 구 RK epoch와 log의 폐기 시점을 늦춘다. 지원 horizon과 re-seed 기준이 없다.

### 왜 중요한가
무한 보관은 비용·disk 위험이고 조기 폐기는 먼 지역 DR을 복구 불능으로 만든다.

### 재현 또는 구체적 예제
세 replica가 각각 0분, 1시간, 7일 지연된 상태에서 RK를 교체한다고 하자.

```sql
ALTER TABLE customer DROP PRIMARY KEY,
 ADD CONSTRAINT uk_email UNIQUE(email);
```

언제 구 epoch를 폐기할지 없다.

### 권고안
topology-aware low-water mark, retention budget, lag SLA, fence/re-seed state와 비용 예측을 제공한다.

### 검증 방법
replica별 lag을 달리해 epoch cleanup, disk 사용, replay와 re-seed 전환을 확인한다.

## [APPDEV-10Y-34] tenant별 RPO 요구를 table 단위 ON/OFF가 표현하지 못한다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문은 table 전체에 하나의 REPLICATION 정책을 둔다.
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: multi-tenant architecture, data governance

### 문제
shared table에서 tenant마다 복제·지역·보존 요구가 달라도 row별 정책은 없다.

### 왜 중요한가
정책 단위를 모르고 shared table을 쓰면 일부 tenant의 계약을 위반한다. table 분리는 FK·migration·query 비용을 만든다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE tenant_cache (
 tenant_id INT NOT NULL, cache_key VARCHAR(100) NOT NULL,
 value VARCHAR(1000), UNIQUE(tenant_id,cache_key)
) REPLICATION=OFF;
```

특정 tenant만 ON으로 할 수 없다.

### 권고안
정책 단위가 table임을 계약하고 tenant별 요구가 다를 때 table/schema 분리, routing, FK·migration tradeoff를 제공한다.

### 검증 방법
상이한 tenant RPO fixture를 설계 가이드로 구현하고 failover·삭제·복구가 각 계약과 맞는지 확인한다.

## [APPDEV-10Y-35] blue/green clone의 정책 checksum과 promotion gate가 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2·8절은 일반 CREATE와 unload/load만 다룬다.
- 사실/추론 구분: 확인이 필요한 질문 — 지원 clone/copy 방식 확인 필요
- 영향 대상: blue/green DB, disaster rehearsal, schema automation

### 문제
clone에서 ON/OFF, selected RK, epoch history가 빠지거나 재선택돼도 promotion 전 탐지하는 contract가 없다.

### 왜 중요한가
green이 다른 replication identity를 가지면 rehearsal 성능과 전환 후 로그 적용이 원본을 대표하지 않는다.

### 재현 또는 구체적 예제

```sql
SELECT class_name, replication FROM db_class ORDER BY class_name;
```

이 checksum은 selected RK/epoch를 포함하지 않아 충분하지 않다.

### 권고안
machine-readable schema+policy+RK manifest와 cryptographic checksum, clone round-trip, promotion gate를 제공한다.

### 검증 방법
복수 UK·OFF·FK·VIEW를 가진 blue DB를 green에 clone하고 manifest 일치 전에는 traffic promotion이 차단되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 15개
- 최종 리뷰 항목 수: 35개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID 파티션·샤딩·trigger·procedure·bulk·CDC·clone 기능의 실제 지원 범위, driver schema epoch·write token 지원 여부, topology별 RK/log retention 구현
