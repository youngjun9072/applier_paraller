# DB를 사용하는 애플리케이션 개발자 / 1년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-22
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: ORM과 스키마 마이그레이션을 처음 사용하는 개발자가 배포 순서, SQL 오류, 복제 지연 및 failover 뒤 애플리케이션 동작을 이해하고 안전하게 대응할 수 있는지를 중점 검토했다.
- 확인하지 못한 전제: 지원 ORM·드라이버 목록, 실제 SQL 문법과 오류 코드, 복제 로그의 RK 형식, DDL 트랜잭션·잠금 동작, `fail_count` 정의, 혼합 버전 HA 지원 범위는 원문만으로 확인하지 못했다. 구현 동작은 단정하지 않고 필요한 계약 또는 검증 질문으로 표시했다.

## [APPDEV-1Y-01] RK가 있어도 기존 변경 누락이 왜 사라지는지 설명되지 않는다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절의 RK 필수 규칙과 4-2절의 키 변경 허용
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 애플리케이션 개발자, 복제 정합성, 사용자 데이터

### 문제
문서는 PK 또는 `NOT NULL UK` 중 하나를 RK로 선택한다고 하지만, 앱의 UPDATE 로그가 옛 RK를 사용한 뒤 스키마가 새 RK로 바뀌는 상황을 어떻게 안전하게 처리하는지 설명하지 않는다. “후보가 하나 이상 있다”는 조건만으로는 로그와 키 정의가 같다는 보장이 아니다.

### 왜 중요한가
애플리케이션 개발자는 ORM이 UPDATE를 성공시켰으면 standby에도 같은 값이 있다고 기대한다. 옛 로그를 새 키로 찾지 못하면 앱은 성공 응답을 보냈지만 failover 후 값이 되돌아온 것처럼 보일 수 있다.

### 재현 또는 구체적 예제
`account(id PK, email NOT NULL UNIQUE, balance)`에서 API A가 `UPDATE account SET balance=900 WHERE id=10;`을 커밋한다. 배포 B가 RK를 id에서 email로 교체한다. replica 적용이 늦으면 A의 로그를 어느 키로 찾는지 없다. 기대 결과는 정확히 한 행이 양쪽에서 900이다.

### 권고안
DML 로그 생성 당시 RK와 DDL 순서를 보존하는 규칙을 입문 그림으로 설명한다. 앱 관점의 수용 기준을 “성공 응답한 DML은 허용된 RK 변경과 failover 뒤에도 동일하게 조회됨”으로 정한다.

### 검증 방법
복제 지연 상태에서 API 쓰기와 RK 마이그레이션을 순서별로 실행하고 failover한다. API 응답, 양 노드 값, `fail_count`가 기대와 같은지 확인한다.

## [APPDEV-1Y-02] PK 없는 ORM 모델을 어떻게 마이그레이션할지 선택 기준이 없다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 2-1·3·7절의 RK 없는 ON 테이블과 HA 시작 실패
- 사실/추론 구분: 확인된 사실
- 영향 대상: ORM 입문자, 기존 애플리케이션, 배포 담당자

### 문제
ORM이 만든 PK 없는 조인·로그·스테이징 테이블에 PK 추가, NOT NULL UK 추가, OFF 설정 중 무엇을 선택해야 하는지 없다. 모든 컬럼으로 행을 찾는 방식과 비교한 정확성·성능 차이도 문서에 없다.

### 왜 중요한가
새 PK를 추가하면 ORM 엔티티와 직렬화 값이 바뀔 수 있고, UK는 기존 중복/NULL 때문에 실패할 수 있다. OFF는 코드 변경은 적지만 failover 후 데이터가 사라질 수 있다. 입문자는 가장 쉬운 OFF를 무심코 고를 수 있다.

### 재현 또는 구체적 예제
ORM이 `tag_map(post_id, tag_id)`를 PK 없이 만들었고 중복 행도 허용했다고 하자. `(post_id,tag_id)` UK 추가는 중복 데이터 때문에 실패한다. surrogate `id` PK 추가는 모델 변경이 필요하다. OFF는 failover 후 태그 연결이 없어진다.

### 권고안
모델 유형별 결정표, 중복/NULL 확인 SQL, ORM 엔티티 수정 예, 안전한 백필 순서를 제공한다. 모든 컬럼 RK 비지원 이유와 OFF가 적합한 데이터 범위도 설명한다.

### 검증 방법
PK 없음·중복·NULL 모델을 샘플 ORM 프로젝트에 만들고 가이드대로 변환한다. 마이그레이션 성공, CRUD와 failover 후 데이터 보존 여부를 확인한다.

## [APPDEV-1Y-03] REPLICATION=OFF가 앱 기능을 부분적으로 망가뜨릴 수 있다는 계약이 부족하다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1·4·6절의 OFF 데이터 불일치 면책
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 기능, API 사용자, 데이터 정합성

### 문제
OFF는 DDL은 전달하지만 DML은 전달하지 않는 것으로 읽히는데, failover 후 조회·쓰기·ON 복귀 결과가 없다. “책임지지 않는다”는 문장만으로 어떤 앱 테이블에 사용해도 되는지 판단하기 어렵다.

### 왜 중요한가
DB 테이블은 여러 API가 함께 사용한다. 개발자가 캐시라고 생각해 OFF로 바꿨지만 로그인 세션, 권한, 작업 큐처럼 재생성이 어려운 데이터라면 장애 조치 뒤 기능 일부만 조용히 실패할 수 있다.

### 재현 또는 구체적 예제
`password_reset_token(id PK, token) OFF`에 source에서 토큰을 저장하고 failover한다. 테이블 DDL은 있어도 행이 없으면 사용자는 유효한 링크로 비밀번호를 바꾸지 못한다. 앱은 “잘못된 토큰”을 반환해 DB 문제를 숨긴다.

### 권고안
OFF 테이블의 CRUD와 failover 결과를 표로 적고 캐시·재계산 가능 데이터만 권장한다. 애플리케이션 오류로 나타나는 예와 재동기화/재생성 방법을 제공한다.

### 검증 방법
OFF 테이블을 사용하는 읽기·쓰기 API를 만든 뒤 failover한다. 문서가 예고한 오류/빈 결과가 발생하고 복구 절차 후 기능이 정상화되는지 확인한다.

## [APPDEV-1Y-04] 후보 키와 실제 RK를 구분하지 않아 ORM 마이그레이션 영향을 알 수 없다

- 분류: 모호성
- 심각도: Blocker
- 근거 위치: 원문 1절의 PK 우선·여러 UK 중 엔진 선택과 2-3절의 ON/OFF 조회만 제공
- 사실/추론 구분: 확인된 사실
- 영향 대상: ORM 개발자, 마이그레이션 도구, 복제 정합성

### 문제
여러 UK 중 실제 선택된 RK를 조회할 수 없고 “명시 순서가 빠른 것”도 예시일 뿐이다. ORM은 제약 생성 순서나 자동 이름을 버전마다 달리 만들 수 있어 엔진 선택을 개발자가 예측하기 어렵다.

### 왜 중요한가
앱 개발자가 불필요해 보이는 UK를 삭제했는데 실제 RK였다면 배포가 실패하거나 RK가 바뀔 수 있다. source/replica가 다른 후보를 고르면 성공한 UPDATE가 적용되지 않을 위험도 있다.

### 재현 또는 구체적 예제
`User(email UNIQUE NOT NULL, username UNIQUE NOT NULL)` 모델의 마이그레이션 생성 순서가 개발과 운영에서 다르다고 하자. 실제 RK가 email인지 username인지 조회할 수 없고 재시작 뒤 유지되는지도 없다.

### 권고안
후보와 선택 RK를 별도 정의하고 결정적인 우선순위를 확정한다. 실제 RK 제약명·컬럼을 조회하는 SQL과 ORM 배포 전 검사 예를 제공한다.

### 검증 방법
제약 순서를 바꾼 두 스키마를 만들고 source/replica·재시작·dump/load 전후 RK를 조회한다. 결과가 규칙대로 동일한지 확인한다.

## [APPDEV-1Y-05] 기본 ON과 single·SA·HA 차이가 개발/운영 불일치를 만든다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절의 기본 ON, 1·3·9절의 모드 설명
- 사실/추론 구분: 확인된 사실
- 영향 대상: 개발 환경, CI, HA 운영 배포

### 문제
옵션을 생략하면 ON인데 RK 없는 테이블은 single에서 성공하고 HA에서 실패한다. 1절은 HA 이외 모두 single이라 하고 9절은 SA를 별도 표기한다. 개발자가 로컬에서 통과한 마이그레이션이 운영에서만 실패할 수 있다.

### 왜 중요한가
초기 개발자는 로컬 DB 결과를 운영에도 그대로 기대한다. 배포 중 DDL 실패가 나면 새 앱 코드와 옛 스키마가 함께 실행되어 서비스 오류가 날 수 있다.

### 재현 또는 구체적 예제
ORM migration이 `CREATE TABLE import_stage(raw VARCHAR(1000));`를 생성한다. local single과 CI에서는 성공하지만 HA 운영에서는 기본 ON+RK 없음으로 ERROR가 날 수 있다. SA 결과도 불명확하다.

### 권고안
모드별 CREATE/ALTER 결과 표와 현재 모드 확인 명령을 제공한다. CI에서 HA 제약을 검사하는 dry-run과 single 생성 시 향후 HA 불가 경고를 제공한다.

### 검증 방법
같은 migration을 single·SA·HA에서 실행한다. 문서 표와 결과가 같고 CI 사전 검사에서 운영 실패를 배포 전에 탐지하는지 확인한다.

## [APPDEV-1Y-06] ORM이 새 REPLICATION 문법을 생성·보존하는 방법이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2절의 CREATE/ALTER 새 옵션과 2-3절의 조회 예
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ORM·schema diff 사용자, 자동 마이그레이션

### 문제
지원 ORM과 드라이버가 `REPLICATION`을 모델 메타데이터로 인식하는지, schema introspection과 diff에서 보존하는지 없다. 모르는 옵션이면 ORM이 테이블을 다시 만들거나 매번 차이로 판단할 수 있다.

### 왜 중요한가
ORM 마이그레이션은 DB 스키마를 읽어 모델과 비교한다. 새 속성을 읽지 못하면 OFF 테이블을 ON 기본값으로 재생성해 데이터 보호 정책이 바뀌거나, 반대로 무한 변경 migration을 만들 수 있다.

### 재현 또는 구체적 예제
수동으로 `CREATE TABLE cache(id INT PRIMARY KEY) REPLICATION=OFF;`를 만든 뒤 ORM의 schema-diff를 실행한다. 도구가 OFF를 모르면 `REPLICATION`을 제거한 CREATE로 테이블 교체할 수 있다.

### 권고안
지원 ORM/드라이버 버전, introspection 필드, migration API와 raw SQL 대안을 문서화한다. `SHOW CREATE TABLE` round-trip에서 ON/OFF가 보존되는 샘플을 제공한다.

### 검증 방법
지원 대상으로 선언한 ORM에서 introspect→diff→apply를 수행한다. 변경 없는 스키마에 migration이 생기지 않고 OFF/ON이 보존되는지 확인한다.

## [APPDEV-1Y-07] RK 후보 변경과 컬럼 변경의 상태 전이가 앱 코드 관점에서 빠졌다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 단일 PK/UK 추가·삭제 예
- 사실/추론 구분: 확인된 사실
- 영향 대상: 엔티티 모델, 스키마 migration, 복제 정합성

### 문제
복합 키, 컬럼 rename, 타입·길이 변경, `NOT NULL` 제거, 키 구성 열 삭제와 후보 교체의 허용 규칙이 없다. ORM이 흔히 만드는 “새 컬럼 추가→백필→NOT NULL→UK” 단계가 HA에서 어떻게 동작하는지도 없다.

### 왜 중요한가
새 email2 열은 백필 전 NULL이므로 바로 RK 후보가 아니다. 배포 순서를 틀리면 DDL이 실패하거나 키가 없는 중간 상태가 된다. 앱 코드가 새/옛 컬럼을 동시에 지원해야 하는 기간도 필요하다.

### 재현 또는 구체적 예제
`user(id PK, email)`을 `login_email` UK RK로 옮길 때 migration은 열 추가(NULL)→데이터 복사→NOT NULL→UNIQUE→옛 PK 제거 순서다. 각 단계에서 실제 RK와 HA 허용 여부가 없다.

### 권고안
PK/UK 추가·삭제, 복합 키, rename·type·NULL 변경의 상태표와 단계적 앱 배포 예를 제공한다. 각 단계의 RK, 허용 모드, 오류와 rollback을 표시한다.

### 검증 방법
두 버전 앱이 동시에 동작하는 상태에서 샘플 migration을 단계별 실행한다. 모든 단계에서 구/신 앱 CRUD와 양 노드 RK·데이터가 정상인지 확인한다.

## [APPDEV-1Y-08] 한 ALTER에서 키 교체 실패 시 migration rollback 계약이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 DROP+ADD
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: migration runner, 배포 파이프라인, 데이터 정합성

### 문제
옛 키 삭제와 새 키 추가를 한 SQL로 권장하지만 새 키가 중복 때문에 실패할 때 전체 취소되는지 없다. ORM migration runner가 transaction 안에서 실행해도 DB DDL이 같은 원자성을 갖는지 알 수 없다.

### 왜 중요한가
ADD 실패 뒤 DROP만 남으면 앱의 `findById`나 외래키가 깨지고 HA도 불가능해질 수 있다. migration 도구가 실패로 표시해도 DB가 부분 변경됐다면 단순 재시도로 복구되지 않는다.

### 재현 또는 구체적 예제
중복 email이 있는 `users(id PK, email NOT NULL)`에 `DROP pk_users, ADD uq_email UNIQUE(email)`을 한 ALTER로 수행한다. 기대 결과는 전체 실패와 id PK/RK 유지다. replica에서만 실패해도 양 노드가 같아야 한다.

### 권고안
DDL 원자성, transaction 지원, lock, 실패 상태와 안전한 down migration을 명시한다. 실행 가능한 완전한 up/down 예와 사전 중복 검사 쿼리를 제공한다.

### 검증 방법
정상·중복·replica 오류 조건에서 migration을 실행하고 rollback/retry한다. 제약, RK, ORM CRUD가 변경 전 또는 변경 후의 완전한 상태인지 확인한다.

## [APPDEV-1Y-09] 앱 요청과 RK DDL이 동시에 실행될 때 오류·재시도 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 DDL 복제와 운영 중 RK 변경
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 온라인 API, transaction 처리, 복제 정합성

### 문제
배포 DDL 중 실행 중인 INSERT/UPDATE/DELETE가 대기, 성공, 실패 중 무엇인지 없다. DDL 전 시작해 후에 커밋하는 transaction이 옛/새 RK 중 무엇을 쓰는지도 없다.

### 왜 중요한가
앱은 일시적 DB 오류는 재시도할 수 있지만 영구적 schema 오류는 재시도하면 안 된다. 오류 코드와 transaction 결과가 없으면 중복 주문이나 사용자에게 거짓 성공을 만들 수 있다.

### 재현 또는 구체적 예제
API A가 `UPDATE account SET balance=balance-100 WHERE id=10` 후 커밋 전이다. 배포 B가 RK를 email로 바꾼다. 기대 동작은 B가 기다리거나 A/B 중 하나가 명확한 재시도 가능 오류로 rollback되는 것이다.

### 권고안
DDL lock과 진행 중/신규 DML 처리, transaction commit 결과, 오류 코드와 retryable 여부를 정의한다. 앱의 지수 backoff와 idempotency key 예를 포함한다.

### 검증 방법
두 세션의 시작·커밋 순서를 바꾸며 네 DML을 실행한다. API 응답, rollback, 재시도 후 중복 여부와 양 노드 데이터가 문서대로인지 확인한다.

## [APPDEV-1Y-10] RK 변경 중 failover 시 앱이 어떤 스키마를 보게 되는지 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 RK 변경과 7절의 HA 전환
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 앱 배포, connection pool, failover 가용성

### 문제
source는 새 RK/컬럼인데 replica는 옛 스키마인 시점에 failover하면 새 앱 코드가 어느 스키마를 만나는지 없다. 승격 전 DDL 동기화를 보장하는지도 알 수 없다.

### 왜 중요한가
connection pool이 새 primary로 자동 연결돼도 스키마가 옛 버전이면 “column not found”나 제약 차이로 요청이 실패한다. 데이터가 있어도 앱은 서비스할 수 없다.

### 재현 또는 구체적 예제
새 앱이 `login_email`을 읽도록 배포하고 열/RK DDL을 실행한 직후 source가 장애 난다. replica에 DDL이 미적용이면 새 앱 쿼리가 실패한다. 기대 결과는 승격 대기/차단 또는 구·신 앱 호환 절차다.

### 권고안
승격 전 schema/RK 버전 일치 조건과 앱이 조회할 DB schema version을 제공한다. expand–migrate–contract 배포와 failover 가능한 단계 표시를 문서화한다.

### 검증 방법
DDL 적용 전후 단계에서 장애를 주입하고 connection pool을 전환한다. 구·신 앱 요청 결과와 승격 차단이 규칙에 맞는지 확인한다.

## [APPDEV-1Y-11] OFF 전환 후 failover에서 앱 캐시·큐 재구축 흐름이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 2-2절의 ON→OFF 허용·OFF→ON 금지와 4절의 데이터 불일치
- 사실/추론 구분: 확인된 사실
- 영향 대상: 캐시·작업 큐 애플리케이션, failover 복구

### 문제
OFF를 앱의 재생성 데이터에 쓴다고 해도 failover 후 언제 누가 재구축하는지, 재구축 전 API가 어떤 결과를 내야 하는지 없다. 실수로 OFF한 뒤 ON 복귀 절차도 없다.

### 왜 중요한가
빈 캐시는 다시 채울 수 있지만 빈 작업 큐는 업무 손실일 수 있다. 앱이 자동 재생성 중 요청을 받으면 잘못된 빈 응답이나 과부하를 낼 수 있다.

### 재현 또는 구체적 예제
`product_search_cache OFF`가 failover 후 비었다. 앱이 모든 상품을 DB 원장에서 한꺼번에 재생성하면 새 primary에 부하가 몰린다. 준비 전 검색 API가 0건을 반환하는지 503을 반환하는지 없다.

### 권고안
OFF 사용 유형, failover hook, readiness 차단, 점진 재구축과 ON 복귀 절차를 제공한다. 앱이 OFF 의존 기능을 선언하고 모니터링할 방법도 정의한다.

### 검증 방법
OFF 캐시를 비운 상태로 failover하고 앱 readiness·재구축·API 응답을 관찰한다. 잘못된 정상 응답 없이 제한 시간 내 복구되는지 확인한다.

## [APPDEV-1Y-12] 복합 키와 키 값 UPDATE가 ORM 엔티티 식별과 충돌할 수 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절의 PK/UK 규칙과 4-2절의 단일 컬럼 예시
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: ORM identity map, 복합 키 모델, 복제 정합성

### 문제
복합 PK/UK가 RK 후보인지, RK 값을 UPDATE할 때 이전 값과 새 값 중 무엇으로 replica 행을 찾는지 없다. ORM도 엔티티 PK 변경을 특별 취급하므로 DB와 앱 양쪽 식별이 어긋날 수 있다.

### 왜 중요한가
복합 키는 두 값이 함께 있어야 한 행을 찾는다. 새 값으로 replica를 찾으면 아직 행이 없어 apply 실패가 난다. ORM 캐시에는 옛 키와 새 키의 객체가 동시에 남을 수도 있다.

### 재현 또는 구체적 예제
`OrderLine(order_id,line_no)` 복합 PK에서 `(100,1)`을 `(100,2)`로 바꾼다. 앱 세션은 옛 객체를 캐시하고 replica에는 옛 키만 있다. 기대 동작은 이전 키로 찾아 새 키를 원자 적용하고 앱에는 refresh 지침을 주는 것이다.

### 권고안
복합 키 지원 범위, NULL·타입·rename 규칙과 before/after 키 적용 방식을 설명한다. ORM에서는 PK 변경 대신 새 행 생성+옛 행 삭제 등 권장 패턴을 명시한다.

### 검증 방법
복합 키 엔티티를 생성·조회한 세션에서 키를 변경하고 cache clear 전후를 본다. failover 후 한 행만 존재하며 ORM 조회와 DB 값이 같은지 확인한다.

## [APPDEV-1Y-13] FK와 CASCADE에서 OFF 테이블이 앱 transaction을 깨뜨리는 경우가 빠졌다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식이 참조하는 부모도 ON이어야 한다는 규칙
- 사실/추론 구분: 확인된 사실
- 영향 대상: 도메인 모델, FK transaction, failover

### 문제
FK 생성 예만 있고 기존 부모를 OFF로 바꾸는 경우, OFF 자식→ON 부모, `ON DELETE/UPDATE CASCADE` 동작이 없다. ORM cascade와 DB cascade를 함께 쓰는 앱의 결과도 예측할 수 없다.

### 왜 중요한가
DB cascade가 자식 로그를 만들고 ORM도 자식을 삭제하면 중복 동작이 생길 수 있다. 부모 DML이 복제되지 않는데 자식만 복제되면 failover 후 관계가 달라진다.

### 재현 또는 구체적 예제
`customers ON`–`orders ON` FK가 `ON DELETE CASCADE`이고 ORM도 주문 삭제를 cascade한다. 부모를 OFF로 바꾼 뒤 고객 삭제 시 source와 replica에서 부모/자식이 각각 어떻게 남는지 없다.

### 권고안
부모·자식 ON/OFF 네 조합과 DB cascade 옵션의 결과를 표로 정한다. 위험한 상태 전환은 거부하고 ORM cascade와 함께 쓸 때의 권장 설정을 제공한다.

### 검증 방법
각 조합에서 ORM transaction으로 생성·삭제·rollback하고 failover한다. 부모/자식 수와 오류가 규칙대로인지 확인한다.

## [APPDEV-1Y-14] OFF 테이블을 참조하는 VIEW가 앱에 조용한 오답을 준다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 6절의 VIEW 사용 제약 없음과 결과 불일치
- 사실/추론 구분: 확인된 사실
- 영향 대상: 조회 API, 리포트, 사용자 화면

### 문제
VIEW SQL은 failover 후 실행되지만 OFF 데이터가 없어 결과가 다르다. 문서는 이를 “제약 없음”이라고 표현해 앱 개발자가 정상 결과로 오해할 수 있다. 의존 VIEW를 찾는 방법도 없다.

### 왜 중요한가
예외가 발생하면 앱이 500 오류를 내고 감지할 수 있지만, 빈 목록이나 틀린 합계는 정상 200 응답으로 사용자에게 전달된다. 조용한 오답이 더 발견하기 어렵다.

### 재현 또는 구체적 예제
`orders ON`과 `discount OFF`를 조인한 `payable` VIEW를 API가 읽는다. source에서는 9,000원, failover 뒤 10,000원이거나 INNER JOIN이면 주문 0건이다. 앱은 둘 다 성공 응답한다.

### 권고안
“실행 가능하지만 결과 정합성 미보장”으로 고치고 OFF 의존 VIEW 생성 시 경고한다. 앱이 의존성을 조회해 startup/readiness에서 차단하는 예를 제공한다.

### 검증 방법
JOIN·집계·중첩 VIEW API를 failover 전후 호출한다. 의존성 경고가 모두 나오고 앱이 정해진 fallback/503을 반환하는지 확인한다.

## [APPDEV-1Y-15] ERROR 한 단어로는 앱과 migration runner가 대응할 수 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2·4·5절의 단순 `ERROR`, 7절의 파일 리스트
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 오류 처리, CI/CD, 사용자 지원

### 문제
문서에 오류 코드, SQLSTATE 여부, retryable 구분, 대상 테이블/제약이 없다. HA 시작의 “파일 리스트”도 앱/스크립트가 읽을 구조인지 불명확하다.

### 왜 중요한가
코드는 메시지 문자열 대신 안정된 오류 코드로 분기해야 한다. RK 없음은 migration 수정이 필요하고 lock timeout은 재시도할 수 있다. 둘을 구분하지 못하면 무한 재시도하거나 배포를 잘못 계속한다.

### 재현 또는 구체적 예제
앱 migration이 유일한 RK 삭제로 `ERROR`를 받는다. runner가 일시 오류로 보고 10회 재시도하면 서비스 잠금만 길어진다. 반대로 lock timeout을 영구 실패로 처리하면 배포가 불필요하게 중단된다.

### 권고안
오류별 코드/SQLSTATE, retryable 여부, transaction rollback 범위, 객체명과 사용자 조치를 표로 제공한다. HA dry-run은 JSON 등 구조화 출력을 지원한다.

### 검증 방법
RK 없음·모드 금지·중복·lock timeout·FK OFF 오류를 발생시킨다. 드라이버가 코드와 rollback 상태를 동일하게 전달하고 샘플 handler가 올바르게 분기하는지 확인한다.

## [APPDEV-1Y-16] fail_count와 기존 데이터 불일치를 앱에서 감지·복구할 방법이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체에서 `fail_count` 정의 및 기존 불일치 복구 부재
- 사실/추론 구분: 확인된 사실
- 영향 대상: 앱 모니터링, 데이터 검증, 고객지원

### 문제
`fail_count` 조회·증가·초기화 규칙과 영향 테이블 연결이 없다. 새 기능이 앞으로의 실패를 막아도 이미 누락된 앱 데이터는 그대로다. 앱 상태 점검에 사용할 지표도 없다.

### 왜 중요한가
source의 주문 상태가 PAID인데 replica는 PENDING이면 failover 후 결제가 되돌아간 것처럼 보인다. 카운터만 0으로 만들어도 데이터는 고쳐지지 않는다.

### 재현 또는 구체적 예제
source `orders(10,'PAID')`, replica `orders(10,'PENDING')`, `fail_count=3`에서 앱을 재배포한다. 새 UPDATE가 정상이어도 주문 10은 다르다. 어느 API 데이터를 재동기화할지 알 수 없다.

### 권고안
테이블·오류·LSA별 지표와 경보를 정의하고 ON 테이블 checksum, 영향 행 비교, 단방향 재동기화 절차를 제공한다. 앱 health endpoint가 사용할 최소 지표도 정한다.

### 검증 방법
행 누락·오래된 값과 OFF의 의도된 차이를 함께 만든다. 모니터가 비정상 차이만 탐지하고 복구 뒤 API 결과와 checksum이 같은지 확인한다.

## [APPDEV-1Y-17] unload/load 기본값 모순이 테스트 데이터와 운영 스키마를 다르게 만든다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 필드 없음=ON과 9절의 정보 없음=OFF
- 사실/추론 구분: 확인된 사실
- 영향 대상: 개발 DB 복원, 테스트 환경, 업그레이드

### 문제
구버전 unload 파일에 REPLICATION 정보가 없을 때 8절은 ON, 9절은 OFF라고 한다. 같은 dump로 만든 개발·운영 환경의 데이터 보호 동작을 예측할 수 없다. 실제 RK를 재선택하는지도 없다.

### 왜 중요한가
개발 DB가 OFF이고 운영은 ON이면 migration 테스트 결과가 달라질 수 있다. 반대로 운영 복원 시 OFF가 되면 failover 후 앱 데이터가 사라진다.

### 재현 또는 구체적 예제
구버전 PK 없는 `event_log` dump를 새 버전에 load한다. ON이면 HA 시작 실패, OFF이면 앱 이벤트가 replica에 없다. 두 결과 모두 배포 시험에 큰 영향을 준다.

### 권고안
정책을 하나로 통일하고 필드 없음은 명시 선택과 경고를 요구한다. load 결과에 테이블별 ON/OFF·RK·HA 가능 여부를 기계 판독 형식으로 출력한다.

### 검증 방법
구버전/신버전 dump를 개발·CI DB에 load한 뒤 schema diff와 CRUD/failover 테스트를 실행한다. 상태가 문서와 동일하게 보존되는지 확인한다.

## [APPDEV-1Y-18] 혼합 버전 배포와 ORM 회귀·부하 시험 범위가 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절의 새 SQL/카탈로그와 8절의 구버전 파일만 언급
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 롤링 배포, 드라이버·ORM, 앱 성능

### 문제
구버전 replica가 새 `REPLICATION` DDL을 처리하는지, 새/옛 앱과 DB 버전 조합이 지원되는지 없다. 복합 문자열 UK가 RK일 때 API 쓰기와 apply 지연 영향도 시험 기준이 없다.

### 왜 중요한가
앱과 DB는 보통 순차 배포된다. 중간 조합이 지원되지 않으면 무중단 배포가 깨진다. replica lag가 길어지면 failover 때 최근 성공 요청이 안 보일 수 있다.

### 재현 또는 구체적 예제
old replica를 둔 new source에 ORM이 `REPLICATION=OFF` 테이블을 생성한다. 동시에 3열 문자열 UK 테이블에 초당 5천 UPDATE를 보낸다. 구버전 parse 결과와 허용 lag가 없다.

### 권고안
DB·driver·ORM·앱 버전 호환 행렬, 업그레이드 순서와 혼합 기간 금지 migration을 명시한다. CRUD/transaction/schema diff/failover와 키 폭별 부하 시험 기준을 제공한다.

### 검증 방법
지원 행렬 각 조합에서 migration, CRUD, failover를 수행한다. 넓은 RK 부하에서 오류율과 p95 응답, apply lag가 합격 기준을 만족하는지 확인한다.

## [APPDEV-1Y-19] SQL 오탈자와 불완전한 예제가 초보 개발자의 학습을 막는다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2-1절 후행 쉼표, 2-2절 `...`, 5-1절 `CRATE TABLE`, 5-2절 예제
- 사실/추론 구분: 확인된 사실
- 영향 대상: 1년차 개발자, 테스트 작성자

### 문제
`CREATE TABLE ...(a INT,)`, `DROP CONSTRAINT ...`, `CRATE TABLE`과 제약 이름 없는 SQL이 있다. 오류 출력도 대부분 `ERROR`라 정책 실패와 문법 실패를 구분할 수 없다.

### 왜 중요한가
입문자는 예제를 복사해 migration을 만든다. parser 오류가 먼저 나면 HA 규칙을 시험하지 못하고, 잘못된 SQL을 ORM raw migration에 넣을 수 있다.

### 재현 또는 구체적 예제
예시 2의 `CREATE TABLE repl_table_without_rk(a INT,);`를 local single에서 실행해도 후행 쉼표로 실패할 수 있다. 문서가 말한 “single에서만 생성 가능”을 확인할 수 없다.

### 권고안
모든 예제를 실제 제약명과 완전한 setup/up/down SQL로 고친다. 모드, 기대 코드, 이유와 수정 예를 붙이고 문서 CI에서 코드 블록을 실행한다.

### 검증 방법
모든 SQL을 clean DB에서 자동 실행하고 예상 결과와 비교한다. 초보 개발자가 그대로 migration 파일로 옮겨도 성공하도록 수동 검토한다.

## [APPDEV-1Y-20] 앱과 DB를 함께 배포하는 전체 튜토리얼이 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 3·7·8·9절의 단편적인 전환·요약
- 사실/추론 구분: 확인된 사실
- 영향 대상: 1년차 앱 개발자, 배포 담당자, QA

### 문제
모델 변경, backward-compatible 앱 배포, 데이터 백필, RK 교체, HA 동기화 확인, 새 코드 활성화, failover, rollback이 하나의 흐름으로 연결되지 않는다.

### 왜 중요한가
DB migration과 앱 코드는 동시에 완벽히 교체되지 않는다. 옛 앱이 새 스키마를, 새 앱이 옛 스키마를 잠시 만날 수 있다. 실행 순서가 없으면 column not found, 중복 쓰기, 복제 누락이 생긴다.

### 재현 또는 구체적 예제
`users.id` PK에서 `login_email` RK로 옮긴다. 필요한 흐름은 nullable 열 추가→구·신 앱 dual-write→백필→NOT NULL+UK→실제 RK 확인→failover 시험→읽기 전환→옛 키 정리다. 원문은 DROP+ADD 한 줄만 준다.

### 권고안
expand–migrate–contract 튜토리얼을 ORM 모델, SQL, API 상태, 기대 출력, retry/rollback과 함께 제공한다. 각 단계에서 허용되는 failover와 완료 조건을 표시한다.

### 검증 방법
두 앱 버전을 동시에 띄우고 튜토리얼을 수행한다. 각 단계에서 CRUD, rollback, failover 후 데이터와 API가 정상이며 구·신 버전 모두 호환되는지 확인한다.

## [APPDEV-1Y-21] DDL 뒤 connection pool과 prepared statement 캐시 처리법이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 HA 운영 중 RK·컬럼 관련 DDL을 허용하지만 기존 연결과 실행 계획의 동작은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 드라이버와 서버가 기존 prepared statement를 자동 무효화하는지는 구현 확인 필요
- 영향 대상: 장시간 실행되는 앱, connection pool, ORM query cache

### 문제
앱 인스턴스가 옛 컬럼·제약 정보를 캐시한 채 DDL이 커밋되면 다음 요청이 오래된 prepared statement를 재사용할 수 있다. 자동 재준비, 오류 후 연결 폐기, transaction rollback 중 무엇이 필요한지 문서가 말하지 않는다.

### 왜 중요한가
배포 후 새 연결은 성공하지만 오래된 pool 연결만 실패하면 간헐적 오류가 된다. 초급 개발자는 같은 SQL이 어떤 요청에서는 되고 다른 요청에서는 안 되는 이유를 찾기 어렵다.

### 재현 또는 구체적 예제

```sql
-- 앱이 미리 prepare
UPDATE users SET name=? WHERE id=?;
-- 배포 중
ALTER TABLE users RENAME COLUMN id AS user_id;
```

옛 prepared statement 실행 시 자동 reprepare인지 명확한 stale-schema 오류인지 계약이 필요하다.

### 권고안
지원 driver별 schema DDL 후 prepared statement, ORM metadata cache, pool 연결의 동작을 정의한다. 안전한 배포 절차에 pool recycle 또는 특정 오류의 1회 reprepare를 넣고 transaction 중 자동 재시도 금지 조건을 설명한다.

### 검증 방법
여러 pool 연결에서 statement를 prepare한 뒤 rename·RK 전환을 수행한다. 새/옛 연결의 오류 코드, rollback, reprepare 후 결과와 중복 DML 여부를 확인한다.

## [APPDEV-1Y-22] client timeout 뒤 DDL 커밋 여부가 불명확할 때 재시도 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 2-2·4-2절의 ALTER 성공/실패 예시; 네트워크 단절과 응답 유실은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 서버 커밋 후 응답만 유실된 경우 동일 DDL 재실행 결과가 정의되지 않는다
- 영향 대상: migration runner, CI/CD, 스키마 정합성

### 문제
DDL이 서버에서 성공했지만 client가 timeout을 받으면 migration 도구는 실패로 기록한다. 그대로 재시도하면 이미 삭제한 제약 없음, 이미 존재하는 새 제약 등의 다른 오류가 발생할 수 있다.

### 왜 중요한가
timeout은 “실패했다”가 아니라 “결과를 모른다”일 수 있다. 결과 확인 없이 down migration이나 재실행을 하면 안전한 새 RK를 다시 제거할 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE customer DROP CONSTRAINT pk_customer,
  ADD CONSTRAINT uq_customer_email UNIQUE(email);
-- commit 직후 응답 전 네트워크 단절
```

앱은 timeout만 받지만 DB는 새 UK/RK일 수 있다.

### 권고안
DDL request ID 또는 migration version으로 결과를 조회하는 방법, 재실행의 idempotency 조건, 알 수 없는 결과에서 `SHOW CREATE TABLE`과 활성 RK를 확인하는 절차를 제공한다. blind retry를 금지한다.

### 검증 방법
DDL commit 직전·직후 응답 연결을 끊고 runner를 재시작한다. 상태 조회로 실제 커밋을 판별하고 동일 migration이 중복 변경 없이 완료되는지 확인한다.

## [APPDEV-1Y-23] 여러 앱 인스턴스의 동시 migration 실행을 막는 규칙이 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2·4절은 한 사용자의 DDL만 예시하며 여러 배포 프로세스의 동시 실행은 없음
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID DDL serialization과 migration advisory lock 지원 여부는 확인 필요
- 영향 대상: autoscaling 앱, 배포 파이프라인, 복제 정합성

### 문제
두 앱 인스턴스가 시작 시 같은 migration을 실행하거나 서로 다른 키 변경을 동시에 제출할 수 있다. 어느 DDL이 대기·실패하는지와 앱 수준 migration lock 권장법이 없다.

### 왜 중요한가
한 runner는 UK 추가, 다른 runner는 PK 삭제를 실행하면 각자 본 사전 상태와 실제 실행 상태가 달라진다. 오류가 나도 한쪽이 부분 성공했다고 오해할 수 있다.

### 재현 또는 구체적 예제

```text
runner A: ADD UNIQUE(email)
runner B: DROP PRIMARY KEY, ADD PRIMARY KEY(external_id)
두 runner가 동시에 시작
```

기대 결과는 클러스터 전체에서 migration owner 한 명만 실행하고 나머지는 대기 또는 종료하는 것이다.

### 권고안
권장 migration lock, lock owner·timeout·lease 만료, crash 후 회수 절차를 제공한다. DB가 advisory lock을 지원하지 않으면 단일 배포 job이나 version table의 원자 update 패턴을 설명한다.

### 검증 방법
앱 인스턴스 10개를 동시에 시작해 동일·상충 migration을 실행한다. DDL이 정확히 한 번 적용되고 나머지는 안정적으로 대기/종료하며 RK와 migration version이 일치하는지 확인한다.

## [APPDEV-1Y-24] 배포 계정이 REPLICATION을 변경할 최소 권한이 정의되지 않았다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절의 새 CREATE/ALTER 문법; 실행 주체와 권한 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: 애플리케이션 배포 계정, DBA, 보안팀

### 문제
일반 ALTER 권한이 ON→OFF까지 허용하는지, 별도 권한이 필요한지 없다. 앱 runtime 계정과 migration 계정을 분리해야 하는지도 설명하지 않는다.

### 왜 중요한가
runtime 앱이 SQL injection 또는 코드 결함으로 OFF 전환을 실행할 수 있다면 장애 조치 보호가 조용히 제거된다. 반대로 너무 강한 DBA 계정을 앱에 넣으면 피해 범위가 커진다.

### 재현 또는 구체적 예제

```sql
-- runtime_user로 실행 시도
ALTER TABLE orders REPLICATION=OFF;
```

기대 결과는 runtime 계정에 명확한 권한 오류가 나고 migration 전용 역할만 승인된 전이를 수행하는 것이다.

### 권고안
runtime, migration, owner, DBA 역할별 CREATE/ON→OFF/OFF→ON/RK DDL 권한표를 제공한다. 최소 권한 grant 예와 배포 완료 후 권한 회수, secret 분리 방법을 문서화한다.

### 검증 방법
역할별 계정으로 새 문법을 실행하고 허용 결과를 표와 비교한다. runtime credential 유출 모의 시험에서 설정을 바꾸거나 감사 기록을 지울 수 없는지 확인한다.

## [APPDEV-1Y-25] 앱 배포 ID와 RK 변경·복제 오류를 연결할 감사 정보가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-2절의 변경과 2-3절의 현재 설정 조회; 변경 이력·client 식별 정보는 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: 개발팀, 고객지원, incident 분석

### 문제
어느 앱 release나 migration 파일이 RK를 바꿨는지, 그 직후 어떤 `fail_count` 오류가 생겼는지 연결할 수 없다. 현재 스키마만 보면 이미 지나간 OFF 구간도 보이지 않는다.

### 왜 중요한가
사고 대응 시 앱 로그, 배포 기록, DB 로그의 시각만 수동 비교하면 시간이 오래 걸리고 clock 차이로 오판할 수 있다. 변경 transaction과 deployment ID가 직접 연결되어야 한다.

### 재현 또는 구체적 예제

```sql
/* deployment=release-2026.08.23 migration=V42 */
ALTER TABLE users DROP PRIMARY KEY,
  ADD CONSTRAINT uq_users_email UNIQUE(email);
```

이 메타데이터 또는 client application name이 감사 이벤트에 남는지 없다.

### 권고안
성공·실패 DDL 감사에 계정, application/client ID, migration version, transaction/LSA, 이전·새 RK를 기록한다. 앱 trace ID와 복제 오류 event ID를 상호 검색할 API를 제공한다.

### 검증 방법
서로 다른 release ID로 변경 후 오류를 주입한다. DB 감사와 앱 trace만으로 원인 migration, 영향 테이블, 로그 범위를 재구성할 수 있는지 확인한다.

## [APPDEV-1Y-26] 파티션 모델을 ORM으로 생성할 때 RK 범위가 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 2-3절의 `partitioned` 표시 외 파티션과 RK 규칙 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 CUBRID와 ORM의 파티션 DDL 지원 범위는 확인 필요
- 영향 대상: 대용량 앱, ORM migration, 데이터 라우팅

### 문제
파티션별로만 유일한 키가 RK 후보가 되는지, 부모 ON/OFF가 새 파티션에 상속되는지 없다. ORM이 새 월 파티션을 자동 생성하면 설정이 빠질 수 있다.

### 왜 중요한가
다른 파티션에 같은 id가 있으면 replica가 id만으로 한 행을 고를 수 없다. 월말 자동 생성이 잘못되면 운영에서만 새 파티션 DML이 실패한다.

### 재현 또는 구체적 예제

```sql
-- 실제 문법은 버전 확인 필요
CREATE TABLE event (
  event_month INT NOT NULL,
  event_id BIGINT NOT NULL,
  UNIQUE(event_month,event_id)
) REPLICATION=ON PARTITION BY RANGE(event_month) (...);
```

ORM model key가 `event_id`만이면 DB RK와 앱 identity도 다르다.

### 권고안
지원 파티션에서 전역/로컬 unique 조건, partition key 포함 의무, 설정 상속과 ADD/SPLIT/EXCHANGE 결과를 문서화한다. ORM 복합 key model과 월 파티션 migration 예를 제공한다.

### 검증 방법
ORM으로 파티션 추가와 경계 행 CRUD를 수행하고 failover한다. 앱 identity, 활성 RK, 양 노드 행이 같은지 확인한다.

## [APPDEV-1Y-27] ORM의 unique index와 UNIQUE 제약이 같은 RK 후보인지 없다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절은 Not Null UK, 4-2절 예시 16은 `DROP INDEX`를 후보 제거로 표현
- 사실/추론 구분: 확인된 사실
- 영향 대상: ORM schema generator, migration 도구, 복제 정합성

### 문제
일부 ORM annotation은 UNIQUE constraint 대신 unique index를 만든다. 둘이 모두 RK 후보인지, index name 변경·rebuild가 RK 변경인지 문서로 알 수 없다.

### 왜 중요한가
개발자는 모델의 `unique=true`가 충분하다고 생각할 수 있지만 실제 생성 객체가 후보가 아니면 HA 시작이 실패한다. 반대로 활성 RK index를 성능 migration이 삭제하면 복제가 중단될 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE user_alias (alias VARCHAR(100) NOT NULL);
CREATE UNIQUE INDEX ux_alias ON user_alias(alias);
ALTER TABLE user_alias REPLICATION=ON;
```

이 테이블이 RK를 가진 것으로 인정되는지 명확하지 않다.

### 권고안
논리 UNIQUE constraint와 unique index의 후보 자격을 분리 정의한다. 주요 ORM annotation이 생성하는 DDL 예, 후보 조회 결과, index rebuild/drop 제한을 제공한다.

### 검증 방법
ORM별 `unique=true`, table-level constraint, explicit index를 생성해 카탈로그 객체와 후보를 비교한다. schema diff/rebuild 뒤 RK가 안정적인지 확인한다.

## [APPDEV-1Y-28] CTAS·LIKE로 만든 테스트/작업 테이블의 기본값이 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절의 일반 CREATE만 설명; 복사 생성 문법 없음
- 사실/추론 구분: 확인이 필요한 질문 — 해당 CUBRID 버전의 CTAS/LIKE 지원 문법 확인 필요
- 영향 대상: 앱 batch, 테스트 fixture, migration

### 문제
원본 테이블을 복사할 때 PK/UK와 REPLICATION을 함께 복사하는지 없다. 데이터만 복사되고 기본 ON이면 RK 없는 테이블 생성이 모드별로 다르게 실패한다.

### 왜 중요한가
개발 환경에서는 성공한 임시 작업 테이블이 HA 운영에서 실패할 수 있다. OFF 원본을 복사했는데 기본 ON이면 예상 밖 복제 부하도 생긴다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE user_backup AS SELECT * FROM users;
-- 실제 지원 시
CREATE TABLE user_copy LIKE users;
```

두 결과의 제약·ON/OFF·활성 RK가 정해져야 한다.

### 권고안
지원 복사 문법별 데이터, 제약, REPLICATION, RK 상속 표를 제공한다. 모호한 기본값보다 명시 옵션을 권장하고 ORM raw migration 예를 추가한다.

### 검증 방법
ON/OFF와 키 있음/없음 원본을 각 방식으로 복사해 local single·HA 결과를 비교한다. 새 테이블의 설정과 failover 데이터가 표와 같은지 확인한다.

## [APPDEV-1Y-29] ON/OFF 테이블을 함께 수정하는 앱 transaction의 의미가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절의 ON 데이터만 복제; 혼합 transaction은 없음
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 서비스 transaction, outbox pattern, failover

### 문제
한 transaction이 ON 업무 행과 OFF cache/outbox를 함께 바꾸면 replica에는 일부만 남는다. ORM callback이나 DB trigger가 OFF 테이블을 간접 수정하는 경우도 개발자가 알아차리기 어렵다.

### 왜 중요한가
source에서는 두 변경이 함께 커밋됐지만 failover 후 하나만 존재해 앱 불변식이 깨진다. 특히 outbox가 OFF면 업무 변경은 반영됐지만 이벤트가 발행되지 않는다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE orders SET status='PAID' WHERE id=10; -- ON
INSERT INTO local_outbox VALUES (10,'ORDER_PAID'); -- OFF
COMMIT;
```

failover 후 재처리·중복 방지 의미가 달라진다.

### 권고안
혼합 transaction을 금지·경고·부분 복제 지원 중 하나로 정의한다. 앱 schema dependency 검사에서 transaction·trigger가 ON/OFF 경계를 넘는지 찾고 outbox 같은 내구 이벤트에는 OFF를 금지하는 가이드를 제공한다.

### 검증 방법
직접 DML, ORM callback, trigger로 혼합 변경을 commit/rollback하고 failover한다. 업무 행과 이벤트의 결과가 문서 계약과 같고 위험 pattern이 검사에서 탐지되는지 확인한다.

## [APPDEV-1Y-30] batch·bulk insert 경로가 일반 CRUD와 같은 복제를 보장하는지 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 일반 데이터 복제만 표현하며 batch API, bulk loader, `INSERT SELECT`, TRUNCATE 경계는 없음
- 사실/추론 구분: 확인이 필요한 질문 — driver batch와 bulk 경로의 실제 로그 방식은 구현 확인 필요
- 영향 대상: ETL, batch 앱, 대량 migration

### 문제
ORM `saveAll`, driver batch, direct load가 row별 RK 로그를 만들거나 동일 commit semantics를 갖는지 없다. TRUNCATE가 DDL로 분류되면 OFF 테이블도 모든 노드에서 지워질 가능성이 있다.

### 왜 중요한가
기능 시험은 단건 CRUD만 통과하기 쉽다. 운영 초기 적재는 수백만 행 batch를 사용하므로 별도 경로가 복제를 우회하면 대규모 누락이 생긴다.

### 재현 또는 구체적 예제

```sql
INSERT INTO target_on SELECT * FROM staging_off;
TRUNCATE TABLE local_cache;
```

첫 결과 행의 복제와 둘째 OFF 데이터의 노드별 결과가 정의돼야 한다.

### 권고안
지원 driver batch, bulk/import, `INSERT SELECT`, TRUNCATE를 ON/OFF별로 분류하고 transaction·오류·로그 크기 계약을 제공한다. batch 중 일부 row 실패의 rollback 범위도 명시한다.

### 검증 방법
각 경로로 정상·중복·부분 오류 데이터를 적재하고 rollback·crash·failover한다. 양 노드 행 수와 checksum, 앱이 받은 update count가 일치하는지 확인한다.

## [APPDEV-1Y-31] surrogate PK 추가 시 identity/sequence 값의 failover 계약이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 PK 없는 테이블에 RK 추가를 요구하지만 자동 증가 PK 생성·백필은 설명하지 않음
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID identity/sequence 문법과 HA 복제 동작은 버전 확인 필요
- 영향 대상: ORM 엔티티, generated key API, failover 후 INSERT

### 문제
PK 없는 모델을 고치기 위해 자동 증가 surrogate id를 추가할 수 있지만 기존 행 백필, sequence 현재값, failover 후 다음 값이 어떻게 보존되는지 없다.

### 왜 중요한가
standby의 generator가 뒤처지면 승격 후 이미 존재하는 id를 다시 발급해 INSERT가 실패하거나 다른 업무 행과 충돌한다. 앱은 driver의 generated key를 이미 사용자 응답에 반환했을 수 있다.

### 재현 또는 구체적 예제

```text
기존 100만 행에 id PK를 백필
source가 다음 id=1000001을 발급하고 commit
즉시 failover 후 새 primary가 다음 id 발급
```

새 값이 1000002 이상인지 계약이 필요하다.

### 권고안
지원 identity/sequence의 DDL, 기존 행 backfill, generator state 복제와 failover 충돌 방지 규칙을 문서화한다. ORM generated key 매핑과 단계적 migration 예를 제공한다.

### 검증 방법
대량 backfill 중 동시 INSERT와 failover를 반복한다. 반환된 generated key가 중복되지 않고 양 노드 데이터와 generator state가 규칙대로인지 확인한다.

## [APPDEV-1Y-32] COMMIT 성공 뒤 failover에서 read-your-write 보장 범위가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5~7절은 failover를 말하지만 commit acknowledgment와 replica 도달 시점은 없음
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: API 일관성, 사용자 경험, retry/idempotency

### 문제
앱이 COMMIT 성공을 받은 직후 primary가 죽으면 새 primary에서 같은 행을 반드시 볼 수 있는지 없다. 보장하지 않는다면 client retry가 중복 INSERT를 만들지 않도록 API 계약이 필요하다.

### 왜 중요한가
사용자는 성공 응답 뒤 데이터가 사라지면 다시 요청한다. 첫 요청이 나중에 복구되면 두 번 처리될 수 있다. RK 기능만으로 commit 내구성과 RPO를 해결하지 못한다.

### 재현 또는 구체적 예제

```sql
INSERT INTO payment(id, status) VALUES (500,'PAID');
COMMIT;
-- 성공 응답 직후 primary 전원 차단
```

새 primary 조회와 같은 idempotency key 재시도 결과가 정해져야 한다.

### 권고안
복제 모드별 RPO, commit ACK 조건, 자동 승격 최소 위치를 앱 관점으로 정의한다. idempotency key, unknown outcome 응답, 안전한 상태 조회·재시도 예제를 제공한다.

### 검증 방법
commit 처리 각 지점에 장애를 주입하고 API 응답·새 primary 데이터·재시도 결과를 기록한다. 약속한 read-your-write/RPO와 중복 방지가 충족되는지 확인한다.

## [APPDEV-1Y-33] failover 뒤 connection pool이 옛 primary에 쓰는 것을 막는 계약이 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문은 failover 후 새 노드 사용을 설명하지만 기존 연결·DNS·driver topology refresh·fencing은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 지원 driver의 failover와 stale connection 처리 방식은 확인 필요
- 영향 대상: connection pool, 앱 retry, split-brain 방지

### 문제
기존 pool 연결이 옛 primary에 남아 있고 새 연결은 새 primary로 향할 수 있다. 옛 노드가 read-only/fenced되지 않으면 같은 앱 인스턴스가 두 노드에 쓸 수 있다.

### 왜 중요한가
RK는 양쪽 쓰기 충돌을 해결하지 않는다. connection timeout 후 재시도도 첫 노드에서 성공했는지 모르면 중복 업무를 만들 수 있다.

### 재현 또는 구체적 예제

```text
pool connection C1→old primary A
failover 후 new connection C2→new primary B
C1과 C2에서 같은 order update 실행
```

기대 결과는 A가 즉시 쓰기를 거부하고 pool이 C1을 폐기하는 것이다.

### 권고안
지원 driver/pool별 topology refresh, validation query, stale connection 오류 코드, fencing과 retry 절차를 제공한다. transaction 결과 불명확 시 idempotency 확인 없이 자동 재시도하지 않게 한다.

### 검증 방법
긴 transaction과 idle pool 연결을 남긴 채 failover한다. 옛 연결 쓰기가 거부되고 새 연결 전환 시간, 오류 분류, 중복 DML이 합격 기준을 만족하는지 확인한다.

## [APPDEV-1Y-34] RK 후보로 사용할 수 있는 데이터 타입 제한이 없다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 1절은 NOT NULL UK를 일반적으로 후보라 설명하며 타입·크기 제한은 없음
- 사실/추론 구분: 확인이 필요한 질문 — floating, LOB, JSON, 암호화·생성 컬럼의 UNIQUE/RK 지원 여부는 버전 확인 필요
- 영향 대상: 앱 모델, serialization, migration

### 문제
ORM은 UUID 문자열, decimal, enum, JSON-derived 값 등 다양한 unique 컬럼을 만든다. UNIQUE를 만들 수 있어도 복제용 안정 key로 허용되는지, 최대 길이와 비교 규칙이 없다.

### 왜 중요한가
긴 key는 로그와 API 쓰기 지연을 키우고, 플랫폼별 표현이 다른 값은 다른 행을 찾을 수 있다. 배포 시점에야 거부되면 모델을 다시 설계해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE metric (
  metric_key VARCHAR(2000) NOT NULL UNIQUE,
  value DOUBLE
) REPLICATION=ON;
```

이 key의 허용 여부, 최대 bytes, collation 비용을 알 수 없다.

### 권고안
허용·금지 타입, 최대 RK bytes·컬럼 수, collation·정밀도 조건을 표로 제공한다. ORM 타입 매핑 예와 surrogate key 대안을 함께 제시한다.

### 검증 방법
지원 driver가 매핑하는 타입별 경계값과 최대 길이를 생성해 CRUD·failover·부하 시험을 한다. 생성 오류와 성능 경고가 문서 기준과 같은지 확인한다.

## [APPDEV-1Y-35] temporary table을 사용하는 테스트와 운영의 규칙이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문은 모든 테이블에 REPLICATION 기본 ON을 적용하는 듯하지만 임시·세션 객체는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 temporary table 지원과 문법은 확인 필요
- 영향 대상: 앱 session, batch, 테스트 fixture

### 문제
앱이 세션 임시 테이블을 만들 때 RK와 REPLICATION이 필요한지, HA에서 기본 ON 때문에 실패하는지 없다. local test DB는 성공하고 운영만 실패할 수 있다.

### 왜 중요한가
임시 데이터는 세션 종료 시 사라져 일반 failover 보호 대상과 목적이 다르다. 같은 규칙을 적용하면 불필요한 오류가 생기고 앱 startup이나 batch가 중단된다.

### 재현 또는 구체적 예제

```sql
-- 실제 문법은 버전 확인 필요
CREATE TEMPORARY TABLE batch_ids (id INT);
```

옵션 생략=ON인지, RK 없음이 허용되는지, failover 때 session 오류가 무엇인지 정해야 한다.

### 권고안
일반·temporary·global temporary·system object별 문법, 기본값, RK 검사와 failover 동작을 표로 제공한다. 앱이 연결 손실 후 임시 상태를 다시 만드는 예를 추가한다.

### 검증 방법
single·HA에서 session 임시 테이블을 만들고 transaction·connection pool·failover를 조합한다. 생성 결과와 재연결 후 앱 복구가 문서와 같은지 확인한다.

## [APPDEV-1Y-36] rename migration과 구·신 앱 동시 실행의 객체 identity 계약이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4-2절은 키 추가·삭제만 설명하며 table/column/constraint rename은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 과거 로그와 prepared SQL이 rename 후 내부 ID로 연결되는지는 확인 필요
- 영향 대상: 단계적 앱 배포, ORM metadata, 복제 정합성

### 문제
컬럼 rename은 옛 앱 SQL을 즉시 깨뜨릴 수 있고, 지연 DML 로그도 옛 이름을 담을 수 있다. alias나 호환 view를 지원하는지, 내부 column ID가 유지되는지 없다.

### 왜 중요한가
롤링 배포 중 구·신 앱은 동시에 요청을 처리한다. rename을 한 번에 실행하면 어느 한 버전이 `column not found`를 내며 failover가 겹치면 문제를 분리하기 어렵다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE users RENAME COLUMN email AS login_email;
```

구 앱은 email, 신 앱은 login_email을 사용한다. 지연된 email RK 로그와 두 앱 쿼리의 지원 기간이 정의돼야 한다.

### 권고안
rename의 내부 identity, 로그 epoch, prepared statement 오류와 지원 배포 pattern을 문서화한다. 입문자는 add→dual write/backfill→switch→drop 방식으로 rename을 대체하도록 완전한 예를 제공한다.

### 검증 방법
구·신 앱을 동시에 실행하고 apply를 지연한 채 rename 또는 호환 migration을 수행한다. 두 버전 CRUD, failover와 최종 데이터가 정상인지 확인한다.

## [APPDEV-1Y-37] cross-service FK에서 한 팀의 OFF 변경이 다른 팀을 깨뜨릴 수 있다

- 분류: 보안
- 심각도: Major
- 근거 위치: 원문 5절은 FK 부모도 ON이어야 한다고 하지만 owner·서비스 경계와 변경 승인 없음
- 사실/추론 구분: 확인이 필요한 질문 — cross-owner FK와 schema 권한 지원 범위는 버전 확인 필요
- 영향 대상: 여러 서비스 팀, 배포 권한, 참조 정합성

### 문제
서비스 A의 부모 테이블을 서비스 B의 ON 자식이 참조할 때 A 개발자가 자기 테이블을 OFF로 바꾸면 B 배포·failover가 깨질 수 있다. 의존 팀과 승인 절차가 없다.

### 왜 중요한가
DB 권한과 조직 책임이 다르면 한 팀은 전체 FK 그래프를 모른다. 오류가 단순 테이블명만 보여도 어느 팀에 문의할지 알 수 없다.

### 재현 또는 구체적 예제

```sql
-- app_b.orders가 app_a.customer를 참조한다고 가정
ALTER TABLE app_a.customer REPLICATION=OFF;
```

기존 FK 때문에 거부하고 영향 서비스·owner를 알려야 한다.

### 권고안
cross-owner dependency 조회, 변경 승인·권한, owner/contact metadata를 제공한다. migration dry-run이 모든 영향 FK와 팀을 출력하고 안전하지 않은 변경은 원자적으로 거부하게 한다.

### 검증 방법
여러 owner의 FK 그래프에서 각 팀 계정으로 ON/OFF 변경과 소유권 이전을 수행한다. 오류·승인·감사 정보가 정책과 맞고 다른 서비스 데이터가 변하지 않는지 확인한다.

## [APPDEV-1Y-38] tenant별 단계적 rollout에서 테이블 단위 옵션만으로 부족하다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2절은 테이블 전체 ON/OFF만 제공하며 tenant·shard·분산 객체 범위는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 제품의 shard/tenant 기능 지원은 확인 필요하며, 여기서는 앱이 같은 스키마에 tenant 데이터를 저장하는 경우를 검토한다
- 영향 대상: multi-tenant 앱, canary 배포, 데이터 보호

### 문제
한 테이블에 여러 tenant 행이 있으면 특정 tenant만 새 RK 정책을 canary로 적용할 수 없다. 앱 feature flag로 일부 요청만 새 key를 쓰면 DB 활성 RK는 테이블 전체에서 하나라 중간 상태가 생길 수 있다.

### 왜 중요한가
입문 개발자는 앱 flag가 DB migration도 안전하게 나눈다고 생각할 수 있다. 실제로 RK·제약 DDL은 모든 tenant 행을 검증하고 전체 테이블에 적용되어 큰 lock이나 중복 오류가 날 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE tenant_user (
  tenant_id INT NOT NULL,
  user_id BIGINT NOT NULL,
  email VARCHAR(100),
  UNIQUE(tenant_id,user_id)
) REPLICATION=ON;
```

tenant 1만 email key로 전환하려 해도 DB RK는 전체 행에 적용된다.

### 권고안
테이블 단위 정책임을 명확히 하고 tenant canary는 shadow column/constraint 사전 검증과 앱 dual-write까지만 사용하도록 가이드한다. 전체 전환 시 모든 tenant 중복·NULL 검사, lock·rollback과 완료 조건을 제공한다.

### 검증 방법
여러 tenant 중 일부에만 결함 데이터를 넣고 canary 앱을 배포한다. 사전 검사가 전체 테이블 위험을 찾고 DB 전환 전까지 옛/새 앱 CRUD가 안전한지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 18개
- 최종 리뷰 항목 수: 38개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 및 지원 driver/ORM의 prepared statement 무효화, migration lock, partition·temporary table·CTAS/LIKE·rename·bulk path 문법, unique index의 RK 자격, identity/sequence HA 동작, cross-owner 권한과 shard/tenant 기능은 코드와 공식 제품·도구 자료 확인이 필요하다.
