# DBMS를 개발하는 엔진 개발자 / 5년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-23
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: RK 카탈로그·로그 표현, 동시 DDL/DML, 캐시 무효화, crash recovery와 로그 재적용, 부분 실패, failover 및 넓은 키의 성능 상호작용을 중점 검토했다.
- 확인하지 못한 전제: CUBRID 저장소 구현 파일·함수·테스트, 실제 log record와 catalog schema, MVCC/DDL lock 규칙, `fail_count` 구현, 복제 프로토콜 버전은 제공되지 않아 확인하지 못했다. 따라서 구현 사실은 단정하지 않고 스펙에 필요한 불변식과 검증 항목으로 적었다.

## [DBDEV-5Y-01] RK 자격만 정의하고 DML 로그가 참조할 RK 버전을 정의하지 않았다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 PK/UK RK 규칙과 4-2절의 RK 교체 허용
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: 복제 로그, apply 엔진, 데이터 정합성

### 문제
스펙은 현재 카탈로그에 RK 후보가 있으면 된다고 하지만, 각 DML record가 어느 시점의 RK 정의를 사용해 만들어졌는지 식별하는 방법이 없다. 제약 이름만으로는 rename/drop/recreate와 같은 이름 재사용도 구분하지 못한다.

### 왜 중요한가
로그는 나중에, 다른 노드와 다른 프로세스에서 읽힌다. record가 `id=10`을 담았는데 apply 시 실제 RK가 email이면 행을 못 찾는다. “키 하나 존재”와 “로그가 해석 가능”은 다른 불변식이다.

### 재현 또는 구체적 예제
`account(id PK,email NOT NULL UNIQUE,balance)`에 UPDATE(id=10), id PK drop+email PK add, UPDATE(email='a@x')를 기록하고 apply를 지연한다. 첫 UPDATE에는 옛 RK ID/version, 두 번째에는 새 RK ID/version이 필요하다. 원문은 이를 정하지 않는다.

### 권고안
영구 constraint/RK ID와 monotonically increasing schema/RK version을 카탈로그 및 DML/DDL log record에 정의한다. apply는 정확한 버전의 key descriptor를 사용하고 없으면 조용히 건너뛰지 말고 복제를 정지해야 한다.

### 검증 방법
제약 rename/drop/recreate와 DML을 섞어 log dump를 확인한다. 각 record가 기대 RK version을 갖고 지연 apply 후 행 checksum 및 `fail_count`가 정상인지 검증한다.

## [DBDEV-5Y-02] 모든 컬럼 식별 대안을 배제한 정확성·비용 모델이 스펙에 없다

- 분류: 컨셉
- 심각도: Major
- 근거 위치: 원문 1절의 PK 또는 NOT NULL UK만 선택
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: 엔진 설계, 키 없는 테이블, 성능 시험

### 문제
모든 컬럼 before-image로 행을 찾는 대안과 RK 방식의 비교가 없다. RK만 허용하는 이유가 정확성인지 로그 크기인지 apply index lookup 성능인지 분리되지 않아 구현 수용 기준을 만들기 어렵다.

### 왜 중요한가
모든 컬럼 방식은 중복 행을 구별하지 못하고 NULL/LOB/collation 처리도 복잡하지만 일부 테이블은 복제할 수 있다. RK 방식은 정확한 index probe가 가능하나 대형 UK 구축과 mutable key before-image 비용이 있다.

### 재현 또는 구체적 예제
`event(ts,message,payload)`에 동일 행 두 개가 있다. 모든 컬럼으로 DELETE 대상을 찾으면 두 행 중 어느 것을 지울지 모호하다. `event_id BIGINT PK`는 명확하지만 5억 행 백필 비용이 든다. OFF는 DML 자체를 보내지 않는다.

### 권고안
대안별 row uniqueness, NULL/LOB 지원, log bytes, lookup complexity, migration 비용을 명시하고 RK 정책의 선택 근거와 비지원 범위를 확정한다.

### 검증 방법
중복·NULL·LOB와 정수/복합 문자열 RK workload를 구현 prototype으로 비교한다. 정확성 및 log/apply 성능 수치가 문서의 결정 근거를 지지하는지 확인한다.

## [DBDEV-5Y-03] REPLICATION OFF의 로그 필터 경계와 상태 머신이 정의되지 않았다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1·4절의 DDL은 모두 복제, OFF DML은 제외
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log writer, apply engine, failover 데이터

### 문제
ON→OFF DDL의 commit 이전에 생성되고 이후 커밋한 DML, commit 이전 대기 로그, rollback된 전환을 어느 상태로 필터링하는지 없다. log 생성 시점과 commit 시점 중 어느 시점의 replication flag를 보는지도 미정이다.

### 왜 중요한가
source와 replica가 서로 다른 컷오버를 사용하면 마지막으로 공통인 행 집합을 알 수 없다. 트랜잭션이 rollback됐는데 DML만 제외되거나 반대로 OFF 이후 DML이 전송되면 상태 머신이 깨진다.

### 재현 또는 구체적 예제
T1이 ON 상태에서 INSERT 81을 시작하고, T2가 OFF DDL을 커밋한 뒤 T1이 커밋한다. INSERT 81을 복제하는지 명시돼야 한다. DDL rollback과 crash recovery에서도 같은 결론이어야 한다.

### 권고안
replication flag를 transaction-visible schema version에 묶고 DDL commit LSA 기준으로 필터 정책을 규정한다. ON/OFF 전환 record와 이전 DML drain, rollback/redo 상태를 명시한다.

### 검증 방법
ON→OFF와 DML 시작/commit 순서를 전부 교차하고 각 log record와 replica 결과를 검사한다. crash/rollback 뒤에도 동일한 truth table을 만족하는지 확인한다.

## [DBDEV-5Y-04] 여러 UK 선택 규칙이 결정적이지 않고 선택 RK를 관측할 수 없다

- 분류: 모호성
- 심각도: Blocker
- 근거 위치: 원문 1절의 PK 우선·여러 UK 중 엔진 선택 예시와 2-3절 조회
- 사실/추론 구분: 확인된 사실
- 영향 대상: catalog, source/replica, restart·restore

### 문제
PK 우선 외 여러 UK는 “명시 순서가 빠른 것”을 예시로만 든다. catalog scan order, object OID, constraint name 중 무엇을 사용하는지, 선택이 영구 저장되는지 없다. 조회 예도 ON/OFF만 보여 준다.

### 왜 중요한가
동일 logical schema라도 source/replica의 internal OID와 생성 순서가 다를 수 있다. 각 노드가 독립 선택하면 다른 RK가 되고 restart/load 후 바뀔 수도 있다.

### 재현 또는 구체적 예제
`member(email UK,phone UK)` 제약을 source와 replica에서 반대 순서로 생성한 뒤 HA 편입한다. 한쪽 email, 다른 쪽 phone이면 email 기반 DML record를 phone descriptor로 해석할 위험이 있다.

### 권고안
source가 선택한 영구 RK ID를 DDL로 복제하고 replica는 재선택하지 않도록 한다. deterministic tie-breaker와 지속 범위를 명시하며 selected/candidate RK를 catalog view에 노출한다.

### 검증 방법
내부 OID·생성 순서가 다른 동일 schema, restart, dump/load에서 RK ID를 비교한다. 불일치 노드의 HA 시작이 차단되는지도 확인한다.

## [DBDEV-5Y-05] 기본 ON과 모드 판정의 단일 source of truth가 없다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 2-1절의 기본 ON, 1·3·9절의 single/SA/HA 표현
- 사실/추론 구분: 확인된 사실
- 영향 대상: parser, catalog 초기화, DDL validation

### 문제
1절은 heartbeat 외 모두 single이라 하고 9절은 SA를 별도 모드로 쓴다. parser default가 ON을 catalog에 명시 저장하는지 implicit 상태로 남기는지, upgrade된 기존 class에 어떤 값을 부여하는지 없다.

### 왜 중요한가
모드 판단이 parser, schema manager, HA manager에 중복되면 경계 시 서로 다른 검증을 할 수 있다. implicit default는 다음 버전에서 기본값이 바뀔 때 기존 객체 의미를 바꿀 수 있다.

### 재현 또는 구체적 예제
옵션 없이 키 없는 `stage`를 single에서 만들고 heartbeat를 시작하는 순간 동시에 ALTER OFF를 실행한다. 검증 모듈들이 다른 모드를 보면 HA 시작과 ALTER가 함께 성공해 검사되지 않은 상태가 될 수 있다.

### 권고안
공식 engine mode enum과 전이 lock을 정의하고 catalog에는 생성 시 resolved ON/OFF를 영구 저장한다. 기존 object upgrade mapping과 모든 DDL의 mode matrix를 명시한다.

### 검증 방법
heartbeat start/stop과 CREATE/ALTER를 race시키고 catalog/HA state를 확인한다. 어떤 interleaving에서도 HA ON 테이블 불변식이 깨지지 않는지 검증한다.

## [DBDEV-5Y-06] REPLICATION DDL의 catalog·cache·log 갱신 원자성이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2절의 CREATE/ALTER 옵션과 2-3절 조회
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: schema manager, plan cache, log writer, apply

### 문제
ON/OFF 변경이 catalog row, in-memory class descriptor, statement/plan cache, replication filter와 DDL log를 어떤 순서로 갱신하는지 없다. 일부만 성공하거나 오래된 cache가 남는 경우를 다루지 않는다.

### 왜 중요한가
catalog는 OFF인데 log writer cache는 ON이면 DML이 계속 복제되고 반대면 누락된다. prepared statement가 옛 descriptor를 잡고 있으면 DDL commit 뒤에도 다른 정책을 적용할 수 있다.

### 재현 또는 구체적 예제
세션 A가 `UPDATE t ...` prepared plan을 보유하고 세션 B가 `ALTER TABLE t REPLICATION=OFF`를 커밋한다. A 재실행이 stale ON cache로 로그를 생성하는지 불명확하다.

### 권고안
catalog update와 DDL log commit을 하나의 transaction으로 묶고 versioned descriptor/cache invalidation protocol을 정의한다. stale version DML은 recompile·wait·error 중 하나로 처리한다.

### 검증 방법
prepared statement, plan cache, schema cache를 유지한 여러 세션에서 ON/OFF를 반복한다. crash 지점별 catalog, cache 재구축과 log filter가 같은 version인지 확인한다.

## [DBDEV-5Y-07] RK 후보 속성 변경의 완전한 validation 그래프가 없다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 단일 PK/UK 추가·삭제 예
- 사실/추론 구분: 확인된 사실
- 영향 대상: DDL validator, index manager, replication descriptor

### 문제
복합 키 일부 열, rename, type/length/collation, `NOT NULL` 제거, 제약 rename, index rebuild와 여러 후보 동시 변경이 빠졌다. 단순한 “후보 개수” 검사는 DDL 후 자격까지 계산하지 못할 수 있다.

### 왜 중요한가
복합 UK 중 한 열이 nullable이 되면 제약이 존재해도 RK 후보가 아니다. collation 변경은 기존 distinct 값을 equal로 만들 수 있고 descriptor serialization도 달라진다.

### 재현 또는 구체적 예제
`shipment(tenant INT NOT NULL, tracking VARCHAR(40) NOT NULL, UNIQUE(tenant,tracking))`에 tracking NULL 허용+다른 UK 삭제를 한 ALTER로 요청한다. 변경 후 후보는 0인데 개별 operation 순서 검사로는 통과할 수 있다.

### 권고안
ALTER 전체를 가상 post-schema에 적용한 뒤 최종 RK 자격을 검증한다. 모든 구성 열의 nullability/type/collation과 index 상태를 포함한 transition matrix 및 dependency graph를 정의한다.

### 검증 방법
복합 ALTER operation 순서를 permutation으로 생성해 property test한다. 성공 결과는 항상 유효 RK가 있고 실패는 catalog/index가 원상태인지 확인한다.

## [DBDEV-5Y-08] DROP+ADD 키 교체의 다단계 실패와 crash recovery 설계가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: DDL executor, index build, recovery, replica apply

### 문제
복합 ALTER를 원자적으로 보이게 하지만 새 index build, uniqueness validation, catalog switch, old index drop 단계와 각 crash/실패의 undo/redo를 정의하지 않는다.

### 왜 중요한가
ADD가 중복·disk full로 실패했는데 old PK가 이미 삭제되면 RK가 0개다. source commit 후 replica 실패도 schema split을 만든다. recovery가 index와 catalog를 다른 단계로 복구하면 재시작 후 더 위험하다.

### 재현 또는 구체적 예제
`users(id PK,email)`에 중복 email이 있는 상태로 id DROP+email UK ADD를 실행한다. index build 50%, catalog switch 직전/직후, old index drop 후 각각 crash를 주입한다.

### 권고안
build new→validate→atomic metadata/RK pointer switch→deferred old drop 순서를 정의한다. WAL redo/undo record, incomplete build cleanup, replica failure policy를 명시한다.

### 검증 방법
각 phase에 duplicate, out-of-space, kill -9를 주입한다. restart 후 old 또는 new 중 완전한 하나의 RK만 존재하고 DML/log apply가 가능한지 확인한다.

## [DBDEV-5Y-09] MVCC transaction과 RK DDL 사이의 schema-version pinning이 정의되지 않았다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 운영 중 DDL과 DML
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: transaction manager, lock manager, log generator

### 문제
DDL 전 시작해 후 커밋하는 transaction이 어느 RK descriptor를 pin하는지, DDL이 active transaction을 drain하는지, stale transaction의 commit을 거부하는지 없다.

### 왜 중요한가
row version과 schema version을 함께 관리하지 않으면 DML은 옛 key value를 읽고 log writer는 새 descriptor를 사용할 수 있다. deadlock/timeout 뒤 부분 로그가 남지 않아야 한다.

### 재현 또는 구체적 예제
T1이 id=10 UPDATE 후 대기하고 T2가 id→email RK switch를 요청한다. T2 선커밋 뒤 T1 커밋, T1 선커밋, T2 timeout 세 interleaving을 모두 정의해야 한다.

### 권고안
transaction별 schema/RK version pin, DDL fence와 lock order를 정의한다. 허용 interleaving, wait/abort 정책, error code와 log generation point를 상태도로 명시한다.

### 검증 방법
deterministic scheduler로 모든 commit/abort interleaving과 deadlock victim을 탐색한다. 최종 schema/data/log 순서가 serial history 하나와 동등한지 확인한다.

## [DBDEV-5Y-10] crash recovery와 로그 재적용의 멱등성 규칙이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4절의 DDL/DML 복제와 7절의 HA 전환
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: recovery manager, apply restart, 데이터 중복

### 문제
apply가 DML을 반영한 뒤 progress LSA 저장 전에 crash하면 같은 record를 다시 읽을 수 있다. RK 값 UPDATE, DELETE, DDL switch가 재적용될 때 already-applied 상태를 어떻게 인식하는지 없다.

### 왜 중요한가
단순 `balance=balance-100` 같은 논리 연산이 두 번 적용되면 데이터가 달라진다. DELETE 재적용이 “행 없음”으로 `fail_count`를 늘리면 정상 recovery가 오류로 오인된다.

### 재현 또는 구체적 예제
replica가 `UPDATE account SET balance=900 WHERE id=10`을 적용하고 checkpoint 전 crash한다. restart 후 record를 다시 읽을 때 no-op인지 다시 적용인지, RK가 email로 바뀐 뒤면 어떻게 판별하는지 없다.

### 권고안
transaction/record identity와 apply progress의 atomicity, redo idempotence, duplicate DDL/DML 처리와 row-not-found 분류를 정의한다. recovery용 before/after key와 commit marker를 포함한다.

### 검증 방법
각 record 적용 직전·row 변경 후·progress 기록 전후 crash를 반복한다. 재시작 횟수와 무관하게 최종 checksum과 `fail_count`가 같아야 한다.

## [DBDEV-5Y-11] replica 부분 DDL 실패 후 failover/failback 상태가 정의되지 않았다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 RK DDL과 7절의 시작 전 검사
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: apply manager, HA coordinator, 승격 안전성

### 문제
source는 RK switch를 commit했으나 replica가 disk full, duplicate, internal error로 apply하지 못한 상태에서 replication과 승격을 어떻게 처리하는지 없다. 실패 노드의 자동 재시도와 quarantine 조건도 없다.

### 왜 중요한가
옛 RK replica가 승격돼 쓰기를 시작하면 복구된 새 RK 노드와 로그가 호환되지 않는다. `fail_count`만 늘리고 다음 record를 계속 적용하면 schema-dependent DML이 연쇄 실패한다.

### 재현 또는 구체적 예제
source가 email UK를 RK로 전환하고 replica index build가 disk full로 실패한다. 다음 email 기반 UPDATE와 source 장애가 이어진다. 기대 동작은 apply/승격을 차단하고 명확한 rebuild 상태로 전환하는 것이다.

### 권고안
schema/RK DDL 실패를 fatal replication barrier로 정의하고 후속 record apply와 승격을 막는다. 재시도 가능/불가 taxonomy, node quarantine, full resync 조건을 명시한다.

### 검증 방법
replica에 duplicate, disk full, injected internal error를 만든다. barrier 뒤 DML이 건너뛰지 않고 승격도 거부되며 복구/resync 후 정상 재개하는지 확인한다.

## [DBDEV-5Y-12] 복합·가변 RK encoding과 mutable key lookup 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절의 PK/UK 규칙과 단일 열 중심 예시
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: log serialization, index lookup, collation, 성능

### 문제
복합 컬럼 순서, NULL 표현, type/collation version, 최대 serialized bytes, RK 값 UPDATE의 before/after image가 정의되지 않았다. 플랫폼/버전별 encoding이 달라질 수 있다.

### 왜 중요한가
복합 키는 경계 없이 값을 이어 붙이면 `(1,23)`과 `(12,3)`을 구분하지 못한다. mutable key는 새 값으로는 replica의 옛 행을 찾을 수 없다. 문자열 collation 차이는 동일성 결과를 바꾼다.

### 재현 또는 구체적 예제
`line(order_id INT,line_no INT,sku VARCHAR, PK(order_id,line_no))`에서 `(1,23)`과 `(12,3)`을 넣고 `(1,23)`→`(1,24)`로 바꾼다. record는 typed length-delimited old/new key를 가져야 한다.

### 권고안
canonical versioned encoding, 컬럼 ID/순서/type/collation, size limit과 before-key lookup/after-key write를 규정한다. unsupported type은 후보에서 제외하고 이유를 조회 가능하게 한다.

### 검증 방법
경계값, 다국어 collation, 복합 key collision corpus와 fuzzing을 수행한다. old/new decoder 간 round-trip 및 mutable update 결과를 비교한다.

## [DBDEV-5Y-13] FK 연쇄 동작의 로그 생성 위치와 ON/OFF 의존 불변식이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 5절의 ON 자식→ON 부모 규칙
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: FK executor, cascade logging, apply order

### 문제
`ON DELETE/UPDATE CASCADE`, SET NULL이 source에서 자식 DML record를 만드는지 replica가 FK로 재실행하는지 없다. 기존 FK 부모를 OFF로 바꾸는 전이, 다단계/순환 의존도 빠졌다.

### 왜 중요한가
source가 cascade 자식 로그를 만들고 replica도 부모 apply로 cascade하면 두 번 적용된다. 부모 OFF로 부모 record가 없고 자식만 오는 반대 경우도 참조 상태가 달라진다.

### 재현 또는 구체적 예제
`tenant→customer→orders`가 CASCADE이고 모두 ON이다. customer를 OFF로 바꾸고 tenant를 삭제한다. 부모/자식 record 집합과 apply 순서가 정해지지 않으면 노드별 남은 행이 다르다.

### 권고안
cascade를 source-expanded row records 또는 replica re-execution 중 하나로 정하고 중복 방지한다. FK 전체 dependency graph에 대한 ON/OFF validation과 topological apply/순환 처리 규칙을 정의한다.

### 검증 방법
각 referential action, 3단계와 순환 그래프에서 DML log를 검사한다. apply 재시작과 failover 후 모든 FK와 row count가 일치해야 한다.

## [DBDEV-5Y-14] OFF 의존 VIEW의 plan cache와 의존성 무효화가 고려되지 않았다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 6절의 모든 VIEW DDL 복제와 결과 불일치 허용
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: view dependency catalog, plan cache, query 결과

### 문제
VIEW DDL 복제만 언급하고 underlying table ON/OFF 변경 시 dependency metadata와 cached plan을 어떻게 무효화하는지 없다. 중첩 VIEW의 위험 표시도 없다.

### 왜 중요한가
ON/OFF가 물리 query plan을 바꾸지 않더라도 결과 보장 수준은 바뀐다. 관리 도구가 의존성을 오래 캐시하면 failover 위험 목록에서 VIEW가 빠질 수 있고 schema rename과 함께 stale plan 오류도 날 수 있다.

### 재현 또는 구체적 예제
`orders ON`과 `discount ON`을 조인한 `v_payable` plan을 cache한 뒤 discount를 OFF로 바꾸고 중첩 `v_daily`를 조회한다. 의존 catalog와 위험 flag가 즉시 갱신돼야 한다.

### 권고안
ON/OFF를 schema dependency version에 포함하고 직접/간접 VIEW dependency를 재계산·노출한다. failover precheck가 OFF-dependent VIEW를 보고하도록 정의한다.

### 검증 방법
중첩 VIEW, prepared plan, table rename와 ON/OFF를 교차한다. cache invalidation 및 의존성 보고가 즉시 정확하고 crash recovery 후에도 유지되는지 확인한다.

## [DBDEV-5Y-15] HA 시작 검사의 snapshot·복잡도·경합 계약이 없다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문 7절의 RK/FK 검사와 파일 리스트 출력
- 사실/추론 구분: 확인된 사실
- 영향 대상: HA manager, catalog scan, 대형 schema

### 문제
검사가 일관된 catalog snapshot을 사용하는지, 동시 DDL을 막는지, 전체 graph scan의 시간/메모리 복잡도와 timeout이 없다. 검사 결과와 HA enable 사이 TOCTOU(time-of-check/time-of-use)도 열려 있다.

### 왜 중요한가
검사 뒤 DDL이 상태를 바꾸면 통과한 결과가 무효다. 수십만 class/FK에서 무제한 scan은 HA 시작을 장시간 지연시키며 lock으로 서비스도 막을 수 있다.

### 재현 또는 구체적 예제
10만 테이블과 20만 FK를 검사하는 동안 다른 세션이 마지막 RK를 삭제한다. snapshot 없이 부분적으로 전/후 상태를 읽으면 위반을 놓칠 수 있다.

### 권고안
catalog snapshot version과 HA mode transition write fence를 정의한다. O(classes+constraints) 목표, 메모리/timeout, 전체 위반 구조화 출력 및 stale token 재검사를 명시한다.

### 검증 방법
대규모 synthetic catalog에서 동시 DDL을 발생시키며 검사한다. 한 snapshot 기준 완전성, 시작 원자성, latency/memory 한도를 측정한다.

## [DBDEV-5Y-16] fail_count가 오류 원인과 recovery action을 구분하지 않는다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 전체에서 `fail_count` 정의·노출·복구 부재
- 사실/추론 구분: 확인된 사실
- 영향 대상: apply observability, 자동 복구, 데이터 교정

### 문제
row-not-found, duplicate, schema version 없음, DDL fatal, 일시 I/O와 정상 duplicate replay를 같은 카운터로 셀지 없다. table, transaction, LSA, RK version correlation도 없다.

### 왜 중요한가
일시 오류는 재시도할 수 있지만 schema DDL 실패 후 계속 진행하면 정합성이 악화된다. 카운터가 줄지 않아도 이미 누락된 행은 남는다. 원인별 자동 조치가 필요하다.

### 재현 또는 구체적 예제
email RK descriptor 없음으로 UPDATE 100건이 실패하고 `fail_count=100`이 된다. 단순 카운터만으로 첫 DDL barrier와 영향 행을 찾을 수 없으며 카운터 reset은 데이터를 고치지 않는다.

### 권고안
stable error taxonomy, table/tx/LSA/RK version, retry count와 first-cause를 metric/event로 노출한다. fatal barrier, retry backoff, checksum/resync 후 승인 reset을 정의한다.

### 검증 방법
각 오류를 fault injection하고 metric cardinality·상관관계를 확인한다. 복구 절차가 영향 row를 교정한 뒤에만 정상 상태로 전환되는지 검증한다.

## [DBDEV-5Y-17] unload/load의 상충 기본값과 RK metadata versioning이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 필드 없음=ON과 9절의 정보 없음=OFF
- 사실/추론 구분: 확인된 사실
- 영향 대상: schema serializer, logical backup, recovery

### 문제
동일한 legacy input을 본문은 ON, 요약은 OFF로 정의한다. unload가 selected RK ID/descriptor를 저장하는지 load가 후보에서 재선택하는지, unknown future field를 old loader가 어떻게 처리하는지도 없다.

### 왜 중요한가
재선택된 RK가 archived log의 RK와 다르면 PITR 후 로그를 해석하지 못한다. 조용한 ON/OFF default는 HA 시작 실패 또는 미복제라는 정반대 위험을 만든다.

### 재현 또는 구체적 예제
필드 없는 `legacy_event`와 email/phone UK인 `member`를 unload/load하고 백업 이후 로그를 적용한다. legacy 상태와 member RK 연속성이 모두 불명확하다.

### 권고안
versioned manifest에 resolved ON/OFF, permanent RK ID와 descriptor version을 저장한다. legacy missing field 정책을 하나로 통일하고 unknown version은 경고/명시 override 없이 조용히 처리하지 않는다.

### 검증 방법
old/new/future-field fixture로 round-trip 및 archived log apply를 수행한다. 상태·RK ID와 최종 checksum이 원본과 같은지 확인한다.

## [DBDEV-5Y-18] 혼합 버전 프로토콜과 성능 회귀 시험 기준이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2절의 새 DDL/catalog와 8절의 파일 호환만 언급
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: replication protocol, rolling upgrade, capacity

### 문제
old node가 새 RK version/ON-OFF DDL record를 decode할 수 있는지, capability negotiation과 feature activation epoch가 없다. 복합 문자열 RK의 log amplification, index probe와 cache 비용 기준도 없다.

### 왜 중요한가
old replica가 새 record를 skip하면 조용한 불일치, reject하면 apply 중단이다. 좁은 정수 PK 대비 넓은 UK는 log/network/CPU를 늘려 지속 lag를 만들 수 있다.

### 재현 또는 구체적 예제
old replica를 둔 new source에서 OFF CREATE, RK switch, 3열 VARCHAR UK로 초당 1만 UPDATE를 실행한다. decode 결과와 허용 apply lag가 없다.

### 권고안
protocol version negotiation, supported matrix, feature gate와 downgrade barrier를 정의한다. key 폭별 bytes/record, apply TPS, cache memory와 p95 lag 수용 기준을 둔다.

### 검증 방법
old/new 양방향 mixed cluster에서 record별 decode, restart, failover를 시험한다. 장시간 부하에서 apply throughput이 ingest 이상이고 resource/lag가 한도 내인지 본다.

## [DBDEV-5Y-19] 예제 문법과 오류 출력이 parser·semantic 테스트 기준이 될 수 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2·4·5절의 후행 쉼표, `...`, 단순 ERROR, `CRATE TABLE`
- 사실/추론 구분: 확인된 사실
- 영향 대상: parser, DDL validator, 회귀 테스트

### 문제
`CREATE TABLE(a INT,)`, 불완전 `DROP CONSTRAINT ...`, 제약명 없는 SQL과 오탈자가 있다. 오류도 parser/semantic/mode/RK 위반을 구분하지 않는 `ERROR`다.

### 왜 중요한가
스펙 예제는 parser grammar와 semantic validation 순서의 실행 가능한 oracle이어야 한다. 문법 오류가 먼저 나면 RK 규칙을 검증한 것으로 착각할 수 있다.

### 재현 또는 구체적 예제
키 없는 HA CREATE 예제가 후행 쉼표로 parser에서 실패하면 기대한 RK_MISSING 오류가 아니다. 유일 RK DROP과 FK OFF도 서로 다른 error code가 필요하다.

### 권고안
모든 예제를 완전한 schema/constraint name, mode, expected SQLSTATE/error code로 고친다. parse success 후 semantic failure가 일어나는 정확한 validation order도 명시한다.

### 검증 방법
문서 code block을 parser/engine integration test로 자동 실행한다. 기대 phase와 code가 실제 결과와 일치할 때만 문서 빌드를 통과시킨다.

## [DBDEV-5Y-20] 기능 상호작용을 포괄하는 상태·fault 테스트 명세가 없다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 1~9절의 단편적 성공/오류 예제와 SUMMARY
- 사실/추론 구분: 확인된 사실
- 영향 대상: 엔진 QA, 복제·DDL·recovery 유지보수

### 문제
정상 SQL 예는 있지만 ON/OFF×RK 유형×모드×DDL/DML 순서×crash phase×version 조합의 시험 행렬이 없다. 각 기능을 단독 시험하면 교차 결함을 놓친다.

### 왜 중요한가
이번 문제는 PK DDL과 HA apply의 상호작용에서 발생했다. 같은 유형의 결함은 cache, FK cascade, unload/load, rolling upgrade 경계에서 다시 나타난다. 회귀 suite가 불변식을 직접 검증해야 한다.

### 재현 또는 구체적 예제
`account(id PK,email UK)`에서 DML–RK switch–OFF–failover–restart–ON 복귀를 수행하고 각 commit 전후 crash를 주입한다. 단일 예제에는 없는 여러 state가 연결된다.

### 권고안
모델 기반 state machine과 fault matrix를 스펙 부록으로 만든다. 모든 성공 상태는 ON 테이블 valid RK와 checksum 일치, 모든 실패는 원자 rollback 또는 fatal barrier를 수용 기준으로 둔다.

### 검증 방법
state-machine/property test로 무작위 operation과 crash를 장시간 생성한다. reference model과 catalog/log/data/fail_count를 매 단계 비교하고 최소 재현을 자동 저장한다.

## [DBDEV-5Y-21] OFF 테이블의 데이터 의존 DDL은 노드마다 성공 결과가 다를 수 있다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 OFF DML은 복제하지 않지만 모든 DDL은 replica에 적용한다고 규정
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: DDL apply, OFF 로컬 데이터, schema 정합성

### 문제
OFF 테이블 데이터는 노드마다 다르므로 `ADD UNIQUE`, `SET NOT NULL`, 타입 변환처럼 기존 행을 검증·재작성하는 DDL은 source에서 성공하고 replica에서 실패할 수 있다. 원문은 OFF 테이블에 대부분 DDL을 허용하지만 이 근본 충돌을 다루지 않는다.

### 왜 중요한가
DDL 복제는 같은 입력 스키마가 아니라 서로 다른 데이터에 같은 연산을 실행한다. source에 중복이 없어 UK 추가가 성공해도 replica의 로컬 중복 때문에 실패하면 schema가 갈라지고 후속 DDL도 적용할 수 없다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE local_code (code INT, value INT) REPLICATION=OFF;
-- source: code 1,2 / replica local data: code 1,1이라고 가정
ALTER TABLE local_code ADD CONSTRAINT uq_local_code UNIQUE(code);
```

source는 성공하지만 replica는 중복 오류가 가능하다.

### 권고안
OFF 테이블 DDL을 metadata-only와 data-dependent/rewrite로 분류한다. 후자는 HA 중 금지하거나 모든 노드 사전 검증+prepare 후 원자 commit하는 protocol을 요구한다. 실패 노드는 승격 불가 barrier로 전환한다.

### 검증 방법
노드별로 중복·NULL·변환 실패 값을 다르게 만든 뒤 UNIQUE, NOT NULL, type change를 복제한다. 허용 정책대로 선제 거부되거나 모든 노드가 같은 schema로 commit하는지 확인한다.

## [DBDEV-5Y-22] 파티션 객체의 RK identity와 DDL 상태 머신이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 2-3절 `db_class` 예시에 `partitioned`가 있으나 파티션 규칙 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 global/local index와 파티션 DDL 지원 범위는 코드 확인 필요
- 영향 대상: catalog, partition manager, log apply, 데이터 정합성

### 문제
부모/파티션 중 어디에 replication flag와 RK descriptor를 저장하는지, local UK가 전역 row identity가 될 수 있는지, partition ADD/SPLIT/MERGE/EXCHANGE가 RK version을 어떻게 바꾸는지 없다.

### 왜 중요한가
다른 파티션에 같은 key가 있으면 table ID+key만으로 행을 찾지 못한다. exchange는 데이터 이동을 DDL로 표현하므로 row log 없이 양 노드가 같은 데이터를 갖는다는 보장이 필요하다.

### 재현 또는 구체적 예제

```sql
-- 실제 문법은 버전 확인 필요
CREATE TABLE sales (
  month_id INT NOT NULL,
  id BIGINT NOT NULL,
  UNIQUE(month_id,id)
) REPLICATION=ON PARTITION BY RANGE(month_id) (...);
```

RK encoding에 partition identity 또는 partition key가 필요한지 정의되지 않았다.

### 권고안
parent/child catalog ownership, global uniqueness, partition ID/key encoding, 각 partition DDL의 epoch/barrier/rollback을 규정한다. 미지원 조합은 semantic validation에서 거부한다.

### 검증 방법
동일 local key를 여러 파티션에 넣고 모든 지원 partition DDL과 동시 DML·crash를 실행한다. 양 노드의 partition map, descriptor, checksum이 동일한지 확인한다.

## [DBDEV-5Y-23] UNIQUE constraint와 unique index의 RK 자격 모델이 일관되지 않다

- 분류: 모호성
- 심각도: Critical
- 근거 위치: 원문 1절은 Not Null UK를 후보로 설명하지만 4-2절 예시 16은 `DROP INDEX`를 마지막 후보 제거로 취급
- 사실/추론 구분: 확인된 사실
- 영향 대상: constraint manager, index manager, catalog, apply lookup

### 문제
독립 unique index가 후보인지, constraint-owned backing index만 후보인지, backing index rebuild 중 논리 RK가 유효한지 없다. index 객체와 constraint 객체의 lifetime을 혼동한다.

### 왜 중요한가
apply lookup은 물리 index가 필요할 수 있지만 RK identity는 논리 제약에 묶어야 restart/rebuild에도 안정적이다. shadow rebuild 중 두 index가 있거나 잠시 old index가 사라지는 상태를 정의해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (id INT NOT NULL, v INT);
CREATE UNIQUE INDEX ux_t_id ON t(id);
ALTER TABLE t REPLICATION=ON;
```

이 index만으로 RK 후보가 되는지 불명확하다.

### 권고안
logical RK constraint ID와 physical lookup index ID를 분리한다. unique index 단독 자격, backing index ownership, rebuild/swap/drop의 descriptor 갱신과 apply fallback을 상태도로 정의한다.

### 검증 방법
PK/UK backing index, 독립 unique index, shadow rebuild를 조합해 candidate 계산과 lookup을 검사한다. 각 phase crash 후 logical RK와 usable physical index가 일치하는지 확인한다.

## [DBDEV-5Y-24] CTAS·LIKE 경로가 REPLICATION과 RK catalog를 어떻게 초기화하는지 없다

- 분류: 호환성
- 심각도: Major
- 근거 위치: 원문 2-1절은 일반 CREATE만 규정하며 table-copy 계열 생성은 없음
- 사실/추론 구분: 확인이 필요한 질문 — CTAS/LIKE의 실제 지원 문법은 버전 확인 필요
- 영향 대상: parser, schema copier, catalog initializer, HA validation

### 문제
복사 생성 경로가 일반 CREATE validator를 우회하면 옵션 생략 기본 ON, 제약 복사, active RK 계산이 서로 다르게 처리될 수 있다. source object의 active RK ID를 그대로 복사하면 다른 table을 가리키는 잘못된 참조가 된다.

### 왜 중요한가
schema clone은 별도 내부 함수로 구현될 수 있다. 신규 필드 초기화를 놓치면 NULL/garbage replication state 또는 key 없는 ON table이 생긴다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE customer_copy AS SELECT * FROM customer;
-- 실제 지원 시
CREATE TABLE customer_copy LIKE customer;
```

두 경로의 constraint, resolved ON/OFF, 새 RK ID 생성 규칙이 필요하다.

### 권고안
모든 object creation path가 공통 catalog initializer와 post-schema RK validator를 사용하게 한다. 상속할 logical 속성과 새로 발급할 object ID를 표로 정의한다.

### 검증 방법
ON/OFF × PK/UK/key 없음 원본을 모든 copy path로 생성하고 catalog invariant를 검사한다. crash recovery와 dump/load round-trip도 포함한다.

## [DBDEV-5Y-25] ON/OFF 혼합 transaction의 commit record와 부분 복제 의미가 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 4절의 ON DML만 복제; 한 transaction의 다중 테이블 변경은 없음
- 사실/추론 구분: 문서에서 도출한 추론
- 영향 대상: transaction log, replication filter, apply atomicity

### 문제
하나의 transaction에서 ON/OFF row record가 섞이면 filter가 OFF record만 제거한 뒤 commit record를 어떻게 구성하는지 없다. transaction checksum, record count, savepoint와 rollback-to-savepoint 의미도 달라질 수 있다.

### 왜 중요한가
replica에서 원본 transaction의 부분집합을 원자 적용해야 한다. filter가 commit 이후 record를 제거하면 checksum/offset이 깨지고, filter가 log generation 단계에 있으면 recovery log와 replication log 의미가 달라진다.

### 재현 또는 구체적 예제

```sql
BEGIN;
UPDATE account SET balance=balance-100 WHERE id=1; -- ON
INSERT INTO local_outbox VALUES (1,'event');       -- OFF
SAVEPOINT s;
UPDATE account SET state='DONE' WHERE id=1;        -- ON
COMMIT;
```

replica transaction record 집합과 atomic commit을 정의해야 한다.

### 권고안
filter phase, replicated transaction ID, filtered record bitmap/count, savepoint/rollback와 commit checksum 규칙을 명시한다. replica에서는 ON subset 전체가 한 번에 commit되도록 한다.

### 검증 방법
ON/OFF record 순서, savepoint, partial rollback, crash를 생성하고 raw log와 apply transaction을 검사한다. ON subset이 정확히 한 번 원자 적용되는지 확인한다.

## [DBDEV-5Y-26] trigger·procedure 파생 DML의 복제 책임이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문은 직접 DML과 FK만 다루며 trigger/stored procedure의 파생 변경은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 trigger/procedure 지원과 현재 logging 방식은 코드 확인 필요
- 영향 대상: execution engine, log writer, apply, ON/OFF 경계

### 문제
source trigger가 만든 row DML을 log에 확장해서 기록하는지, replica가 원문 DML을 실행하며 trigger를 다시 실행하는지 없다. 둘 다 하면 중복, 둘 다 안 하면 누락이다. trigger가 OFF table을 변경하면 혼합 정책도 적용된다.

### 왜 중요한가
사용자 SQL 한 줄이 여러 테이블을 바꿀 수 있어 direct statement 기준 filter로는 충분하지 않다. trigger definition이 노드마다 같아도 OFF local data를 읽으면 결과가 다를 수 있다.

### 재현 또는 구체적 예제

```sql
-- 실제 trigger 문법은 버전 확인 필요
-- orders INSERT가 audit_on과 cache_off를 함께 갱신한다고 가정
INSERT INTO orders VALUES (10,'NEW');
```

세 테이블 record 집합과 replica trigger 실행 여부가 명확해야 한다.

### 권고안
source-expanded row logging 또는 deterministic replica re-execution 중 하나를 기능별로 확정하고 중복 방지한다. trigger가 ON/OFF 경계를 넘거나 local data를 읽는 경우 생성 경고/금지 정책을 정의한다.

### 검증 방법
BEFORE/AFTER, 다단계 trigger와 ON/OFF 조합을 만들고 raw log를 검사한다. restart·reapply·failover 후 row count와 side effect가 한 번만 발생하는지 확인한다.

## [DBDEV-5Y-27] TRUNCATE·bulk load·INSERT SELECT의 특수 로그 경로가 빠졌다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 DDL 전체와 ON 데이터 복제를 구분하지만 경계 명령은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 각 명령의 실제 분류와 direct-path logging 구현은 확인 필요
- 영향 대상: bulk executor, log manager, OFF local data, recovery

### 문제
TRUNCATE가 DDL record면 OFF local data도 모든 노드에서 제거될 수 있다. direct load가 row log를 생략하거나 page-level log를 쓰면 RK apply 경로와 다른 correctness 조건을 가진다.

### 왜 중요한가
대량 경로는 성능을 위해 일반 executor를 우회하기 쉽다. 신규 filter/check가 모든 진입점을 덮지 않으면 단건 test는 통과해도 운영 적재가 누락된다.

### 재현 또는 구체적 예제

```sql
TRUNCATE TABLE local_cache; -- OFF
INSERT INTO target_on SELECT * FROM staging_off;
```

각 명령의 log record, rollback, failover 결과를 정의해야 한다.

### 권고안
지원 bulk/direct path 목록과 DDL/DML/physical log 분류를 작성한다. ON/OFF filtering, transaction commit, RK metadata, crash redo와 replica apply를 경로별로 규정한다.

### 검증 방법
각 경로에 duplicate·disk full·crash를 주입하고 raw/recovery/replication log를 비교한다. 최종 checksum과 OFF local-data 정책이 일치하는지 확인한다.

## [DBDEV-5Y-28] identity·sequence state의 HA 전환 불변식이 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문은 PK/RK 추가를 요구하지만 자동 생성 키와 generator state는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 identity/serial/sequence 기능과 복제 방식은 확인 필요
- 영향 대상: sequence manager, generated PK, failover INSERT

### 문제
키 없는 기존 table에 surrogate PK를 추가할 때 기존 행 backfill과 generator current/cache state를 어떻게 맞추는지 없다. sequence cache가 노드별이면 failover 후 이미 사용한 값을 다시 발급할 수 있다.

### 왜 중요한가
RK가 유일해야 하는데 generator 중복은 즉시 INSERT 실패나 다른 row identity 충돌을 만든다. cache된 미사용 범위를 건너뛰는 것은 허용할 수 있지만 재사용은 안 된다.

### 재현 또는 구체적 예제

```text
source가 id=1000을 commit하고 1001~1100을 memory cache
standby는 durable value=900인 상태에서 승격
```

다음 발급 값과 중복 방지 규칙이 필요하다.

### 권고안
generator state의 durable/replicated watermark, cache allocation epoch, failover fencing, backfill 후 `max(id)` 조정과 rollback을 정의한다. gap 허용과 reuse 금지를 명시한다.

### 검증 방법
cache allocation·commit·flush 각 지점에서 crash/failover하고 병렬 INSERT를 수행한다. 발급 key가 중복되지 않고 RK index와 generator watermark가 일치하는지 확인한다.

## [DBDEV-5Y-29] temporary·system 객체가 공통 RK validator를 우회하거나 오염시킬 수 있다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문은 모든 table을 일반화하고 `db_class` 예시에 system class가 있으나 객체 범위는 없음
- 사실/추론 구분: 확인이 필요한 질문 — temporary/global temporary/system object 지원·catalog 표현은 코드 확인 필요
- 영향 대상: parser, catalog, HA startup scan, session lifecycle

### 문제
session-local table을 global catalog RK 검사에 넣으면 HA 시작을 불필요하게 막을 수 있다. 반대로 durable internal table을 제외하면 시스템 상태가 failover에서 달라질 수 있다.

### 왜 중요한가
객체 종류마다 storage와 lifetime이 다르다. 일반 table validator를 그대로 적용하거나 완전히 우회하면 잘못된 default·NULL catalog field가 생긴다.

### 재현 또는 구체적 예제

```sql
-- 실제 문법은 버전 확인 필요
CREATE TEMPORARY TABLE tmp_ids (id INT);
```

resolved replication state 저장 위치와 HA scan 포함 여부가 필요하다.

### 권고안
object type별 grammar, catalog field applicability, RK validation, log/backup/startup-scan 범위를 정의한다. 공통 API는 `NOT_APPLICABLE`을 명시적으로 처리해 implicit ON과 구분한다.

### 검증 방법
지원 object type을 생성·drop·session 종료·crash하고 catalog migration과 HA scan을 실행한다. orphan field와 잘못된 blocker가 없는지 확인한다.

## [DBDEV-5Y-30] REPLICATION DDL authorization check의 시점과 복제 적용 예외가 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2절의 사용자 DDL; 권한과 replica apply context는 없음
- 사실/추론 구분: 확인이 필요한 질문 — 현재 DDL privilege 검사와 replication apply principal은 코드 확인 필요
- 영향 대상: authorization engine, DDL executor, replica apply

### 문제
source user는 권한이 있어도 replica에는 동일 user/role이 없거나 권한 상태가 다를 수 있다. replica가 source DDL을 일반 사용자 권한으로 재검사하면 apply 실패하고, 모든 내부 apply를 무조건 신뢰하면 조작된 로그에 취약하다.

### 왜 중요한가
권한 검사는 source statement 수락 시 한 번, replica에서는 인증된 replication record와 object identity 검증으로 처리하는 등 명확한 trust boundary가 필요하다.

### 재현 또는 구체적 예제

```sql
GRANT ALTER ON orders TO migrator;
ALTER TABLE orders REPLICATION=OFF;
```

source와 replica role catalog가 일시적으로 다를 때 DDL 적용 결과가 같아야 한다.

### 권고안
별도 `ALTER REPLICATION` privilege, source authorization commit, authenticated apply principal과 record integrity 검사를 정의한다. 권한 없는 source DDL은 로그를 만들지 않고, replica는 사용자 privilege drift 때문에 거부하지 않게 한다.

### 검증 방법
source/replica role 상태를 다르게 하고 정상·위조 DDL record를 적용한다. 정상 승인 record만 적용되고 권한 없는 요청과 무결성 실패 record는 원자적으로 거부되는지 확인한다.

## [DBDEV-5Y-31] 감사 event와 DDL transaction의 atomicity가 없다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-2절의 상태 변경과 2-3절의 현재 조회; audit event 없음
- 사실/추론 구분: 확인된 사실
- 영향 대상: audit subsystem, incident 분석, compliance

### 문제
ON/OFF·RK 변경이 성공했는데 audit가 유실되거나 rollback됐는데 성공 event가 남으면 보호 상태 timeline을 재구성할 수 없다. 엔진 자동 RK 재선택도 사용자 DDL과 구분돼야 한다.

### 왜 중요한가
복제 누락 범위는 state transition LSA와 직접 연결된다. 비동기 일반 로그만 쓰면 crash에서 catalog와 audit가 서로 다른 commit 상태가 될 수 있다.

### 재현 또는 구체적 예제

```text
catalog switch commit → audit enqueue → crash
```

restart 후 active RK는 새 값인데 audit가 없을 수 있다.

### 권고안
audit record를 DDL transaction/LSA와 원자 연결하거나 recovery에서 결정적으로 재구성한다. old/new state, actor, source/automatic reason, object IDs와 generation을 포함한다.

### 검증 방법
authorization, catalog update, commit, audit flush 각 지점에 crash를 주입한다. committed transition마다 정확히 한 event가 있고 rollback에는 성공 event가 없는지 확인한다.

## [DBDEV-5Y-32] parallel apply worker 사이 DDL barrier의 범위가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절은 DDL/DML 복제를 말하지만 병렬 apply와 ordering은 없음
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID apply 병렬성 지원 여부와 scheduler 구조는 코드 확인 필요
- 영향 대상: apply scheduler, throughput, schema 정합성

### 문제
여러 worker가 같은 table 또는 FK 관련 table의 DML을 처리하는 동안 RK DDL을 적용하면 일부 worker가 old descriptor, 일부가 new descriptor를 사용할 수 있다. global barrier는 안전하지만 성능을 크게 낮춘다.

### 왜 중요한가
barrier scope를 table, dependency graph, database 중 어디까지 잡는지가 correctness와 throughput을 결정한다. barrier ACK 전 descriptor를 폐기해서는 안 된다.

### 재현 또는 구체적 예제

```text
W1: t old-RK UPDATE 적용 중
W2: t new-RK 이후 UPDATE queue
W3: t의 FK child DML 적용 중
DDL worker: t RK switch
```

허용 순서와 worker drain 범위가 필요하다.

### 권고안
commit LSA 기반 table/dependency barrier, worker epoch pin과 acknowledgment, descriptor reclamation low-water mark를 정의한다. 안전한 최소 scope와 fallback global barrier를 명시한다.

### 검증 방법
worker 수·queue skew를 바꾸고 barrier 전후 DML을 deterministic scheduler로 재배열한다. serial reference와 checksum이 같고 deadlock·starvation이 없는지 확인한다.

## [DBDEV-5Y-33] RK log compression과 checksum의 version 계약이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 1절의 RK 도입과 8절 파일 호환; 로그 압축·무결성은 없음
- 사실/추론 구분: 확인이 필요한 질문 — 현재 log compression/checksum 기능은 코드 확인 필요
- 영향 대상: log format, network, archive, mixed version

### 문제
복합 문자열 RK가 로그를 키우면 prefix/dictionary compression을 도입할 가능성이 있다. codec version, dictionary reset, checksum 범위가 없으면 restart나 mixed node가 값을 잘못 복원할 수 있다.

### 왜 중요한가
키 bytes 한 비트 손상은 다른 행 조회 또는 row-not-found를 만든다. decoder가 오류를 탐지하지 못하고 잘못된 key를 적용하는 것이 명시적 중단보다 위험하다.

### 재현 또는 구체적 예제

```text
record v2: table-id + rk-generation + compressed old-key + checksum
old decoder: v1만 지원
```

old decoder가 payload를 v1로 오해하지 않아야 한다.

### 권고안
versioned length-delimited record, codec negotiation, uncompressed canonical checksum, dictionary lifecycle과 unknown-version hard failure를 규정한다. archive/replay decoder도 동일 계약을 사용한다.

### 검증 방법
codec version·dictionary boundary·restart를 교차하고 bit flip/truncation을 주입한다. corruption이 row lookup 전에 탐지되고 mixed decoder가 안전하게 거부하는지 확인한다.

## [DBDEV-5Y-34] 손상·악성 RK record에 대한 방어적 decode 한계가 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문은 정상 SQL 예제만 제공하고 비정상 로그 길이·컬럼 수·type mismatch는 없음
- 사실/추론 구분: 확인이 필요한 질문 — replication channel 인증과 decoder validation은 구현 확인 필요
- 영향 대상: apply process 안정성, 메모리 안전, 가용성

### 문제
로그의 key length, column count, type OID가 catalog descriptor와 다를 때 apply가 얼마나 메모리를 할당하고 어떻게 실패하는지 없다. corrupt archive나 공격자가 조작한 channel record가 crash·과다 할당을 만들 수 있다.

### 왜 중요한가
apply는 신뢰도가 높은 내부 입력을 처리해도 disk/network corruption을 만나며, 로그 parser는 엄격한 경계 검사가 필요하다. 프로세스 crash 반복은 HA를 사용할 수 없게 한다.

### 재현 또는 구체적 예제

```text
RK column_count=2, descriptor=1
encoded_length=4GB, 실제 payload=20 bytes
unknown type_oid
```

모두 bounded error로 처리되어야 한다.

### 권고안
최대 record/key/column 크기, overflow-safe length check, descriptor 일치, checksum/MAC와 error quarantine을 정의한다. malformed record는 process crash 없이 fatal barrier와 진단 event로 전환한다.

### 검증 방법
fuzzing과 corpus mutation으로 길이·type·중첩 encoding을 변조한다. sanitizer 환경에서 crash/OOM이 없고 잘못된 row 변경 없이 안정된 오류를 내는지 확인한다.

## [DBDEV-5Y-35] 민감한 RK 값의 로그·진단 노출 정책이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 1절은 email 같은 NOT NULL UK도 RK가 될 수 있고 2-3절 예시에는 TDE 속성이 보이지만 복제 로그·오류의 값 보호는 없음
- 사실/추론 구분: 확인이 필요한 질문 — TDE와 network/archive encryption의 실제 범위는 확인 필요
- 영향 대상: 개인정보, log archive, 진단·지원 bundle

### 문제
PK가 없으면 email, 전화번호 같은 개인정보 UK가 활성 RK가 될 수 있다. before/after key가 로그, `fail_count` event, support dump에 평문으로 노출될 수 있다.

### 왜 중요한가
테이블 TDE가 data page만 암호화하고 replication/archive/진단 로그를 보호하지 않는다면 데이터 보호 경계가 넓어진다. 장기 보관 로그의 접근 통제와 삭제 의무도 생긴다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE member (
  email VARCHAR(200) NOT NULL UNIQUE,
  name VARCHAR(100)
) REPLICATION=ON;
UPDATE member SET name='Kim' WHERE email='person@example.com';
```

email이 어떤 로그와 오류 출력에 나타나는지 계약이 필요하다.

### 권고안
transport/archive encryption, key management, diagnostic redaction/hash, role-based access와 retention을 정의한다. 로그 내부에 원값이 필요하면 UI/metric에서는 기본 마스킹하고 support export에 별도 승인을 요구한다.

### 검증 방법
민감 RK DML과 오류를 생성해 data/replication/archive/error/support 파일을 검색한다. 권한 없는 사용자에게 평문이 노출되지 않고 복구·apply 기능은 유지되는지 확인한다.

## [DBDEV-5Y-36] apply row lookup과 optimizer/index 상태의 결합이 정의되지 않았다

- 분류: 성능
- 심각도: Critical
- 근거 위치: 원문은 RK로 행을 찾는다고 하지만 lookup이 일반 optimizer를 쓰는지 전용 index probe인지 없음
- 사실/추론 구분: 확인이 필요한 질문
- 영향 대상: apply performance, index manager, optimizer cache

### 문제
apply가 일반 SQL plan을 만들면 stale statistics·plan cache·index visibility가 lookup 성능과 correctness에 영향을 줄 수 있다. 전용 probe라면 backing index 교체 중 handle pinning과 fallback이 필요하다.

### 왜 중요한가
RK lookup이 table scan으로 떨어지면 넓은 테이블에서 apply lag가 폭증한다. rebuild 중 old index handle이 해제되면 use-after-free나 lookup 실패 같은 구현 결함도 가능하다.

### 재현 또는 구체적 예제

```text
active RK logical ID=7
physical index old=101, shadow=102
apply worker는 index 101 handle 보유
atomic swap 후 old drop
```

worker pin 해제 전 101을 폐기해서는 안 된다.

### 권고안
apply lookup API, required unique index state, descriptor/index handle lifetime, shadow swap와 no-scan 정책을 정의한다. scan fallback을 허용하면 row-count/timeout 한계와 경보를 둔다.

### 검증 방법
통계 갱신, index invisible/rebuild/swap/drop과 고부하 apply를 교차한다. lookup plan/probe, latency, handle lifetime과 최종 row correctness를 확인한다.

## [DBDEV-5Y-37] 기존 catalog backfill과 upgrade rollback의 원자성이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 2-3절의 새 `replication` 필드와 RK 선택, 8절의 legacy load만 설명
- 사실/추론 구분: 확인이 필요한 질문 — in-place catalog upgrade 경로와 old binary reader 동작은 확인 필요
- 영향 대상: catalog migration, upgrade/downgrade, crash recovery

### 문제
기존 수많은 class에 resolved ON/OFF와 active RK ID/version을 언제 backfill하는지, 중간 crash 후 resume하는지 없다. old binary가 새 catalog field나 version을 읽을 수 있는지도 정의되지 않는다.

### 왜 중요한가
catalog migration이 절반만 끝나면 일부 table은 implicit, 일부는 explicit state가 된다. HA startup과 DDL validator가 다른 해석을 할 수 있고 downgrade가 catalog를 열지 못할 수 있다.

### 재현 또는 구체적 예제

```text
100,000 class 중 50,000개 backfill 후 crash
재시작 binary는 new 또는 old 버전일 수 있음
```

resume/rollback과 feature activation 경계가 필요하다.

### 권고안
catalog format version, idempotent batch migration, per-object migrated marker와 final activation transaction을 정의한다. feature gate 전 old semantics를 유지하고 point-of-no-return·downgrade 검사와 백업 요구를 명시한다.

### 검증 방법
각 backfill batch와 activation commit 지점에 crash를 주입하고 new/old binary 재시작을 시험한다. duplicate RK ID나 mixed semantics 없이 resume 또는 명확히 rollback되는지 확인한다.

## [DBDEV-5Y-38] 생성·표현식 컬럼 UK의 결정성과 dependency invalidation이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 모든 NOT NULL UK를 후보로 일반화하며 생성/표현식 기반 key는 없음
- 사실/추론 구분: 확인이 필요한 질문 — generated column/function-based index 지원 여부와 문법은 버전 확인 필요
- 영향 대상: expression evaluator, catalog dependency, replication encoding

### 문제
RK가 함수나 생성 컬럼 값에 의존하면 함수 버전, collation, timezone, session setting이 노드마다 달라 결과가 다를 수 있다. 기반 컬럼 변경과 함수 교체 시 후보 자격·descriptor invalidation도 필요하다.

### 왜 중요한가
RK는 동일 input에서 항상 같은 key를 만들어야 한다. 비결정 함수나 환경 의존 표현식이면 source와 replica가 다른 index key를 계산해 행을 못 찾는다.

### 재현 또는 구체적 예제

```sql
-- 실제 지원 문법은 확인 필요
CREATE TABLE person (
  email VARCHAR(200) NOT NULL,
  normalized_email VARCHAR(200) AS (LOWER(email)) UNIQUE
) REPLICATION=ON;
```

LOWER의 locale/version이 다를 때 동일성 결과가 달라질 수 있다.

### 권고안
RK 후보 생성식은 immutable/deterministic 함수와 versioned collation만 허용하거나 전부 금지한다. expression dependency와 function/collation version을 descriptor에 넣고 변경 시 RK transition barrier를 적용한다.

### 검증 방법
locale·timezone·함수 버전이 다른 노드와 expression 변경을 시험한다. candidate validation이 비결정식을 거부하고 허용식은 동일 key bytes와 lookup 결과를 만드는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 18개
- 최종 리뷰 항목 수: 38개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: CUBRID의 OFF 테이블 data-dependent DDL apply 방식, partition·CTAS/LIKE·temporary table·trigger/procedure·bulk path·identity/sequence·generated column 지원, logical constraint와 physical index 내부 모델, 병렬 apply scheduler, 로그 압축·무결성·TDE 보호 범위, authorization/audit transaction, catalog upgrade 코드 경로는 저장소와 공식 설계 자료 확인이 필요하다.
