# DBMS를 개발하는 엔진 개발자 / 1년차 관점 리뷰

- 대상 문서: ../../../user_spec/user_spec.html
- 리뷰 날짜: 2026-08-23
- 리뷰 항목 수: 20
- 검토한 원문 범위: 1~9 전체
- 역할상 중점: 카탈로그·복제 로그·DDL 처리의 기초 이해 가능성, 결정적인 RK 선택, 명확한 불변식, 실패 후 상태, 구현을 시험으로 옮길 수 있는 예제
- 확인하지 못한 전제: 실제 CUBRID 소스 코드의 카탈로그 구조, 복제 로그 레코드, parser/DDL 함수, 캐시 무효화, `fail_count` 구현, 오류 코드는 확인하지 않았다. 따라서 제안한 내부 필드와 상태 이름은 구현 요구 예시이며 현재 구현 사실이 아니다.

## [DBDEV-1Y-01] “RK가 하나 있음”만으로 변경 누락 방지를 설명할 수 없다

- 분류: 컨셉
- 심각도: Blocker
- 근거 위치: 원문 1절의 HA에서 RK 필수 규칙과 4-2절의 운영 중 RK 변경
- 사실/추론 구분: 문서에서 도출한 추론 — RK 존재는 필요 조건이지만 로그 생성 때의 키 정의와 적용 때의 키 정의가 같다는 보장은 없다
- 영향 대상: 엔진 개발자, 복제 정합성, 테스트 개발자

### 문제
문서는 ON 테이블에 RK 후보를 남기면 문제를 막을 수 있는 것처럼 설명한다. 그러나 UPDATE 로그가 옛 PK 값으로 만들어진 뒤 카탈로그가 새 PK로 바뀌면, replica 적용기는 옛 값을 어떤 컬럼으로 해석해야 하는지 모를 수 있다.

### 왜 중요한가
RK는 행 주소이고 복제 로그는 그 주소를 전달하는 봉투다. 새 주소가 항상 존재해도 봉투가 어느 주소 체계를 사용했는지 표시하지 않으면 배달할 수 없다. 입문 개발자는 “후보 개수 검사”와 “로그-스키마 버전 연결”이 별도 문제임을 알아야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE account (
  id INT PRIMARY KEY,
  email VARCHAR(100) NOT NULL UNIQUE,
  balance INT
) REPLICATION = ON;

UPDATE account SET balance=400 WHERE id=10;
ALTER TABLE account DROP PRIMARY KEY,
  ADD CONSTRAINT pk_account_email PRIMARY KEY(email);
```

UPDATE 로그가 `id=10`을 담고 DDL 뒤 적용기가 `email`만 본다면 행 검색이 실패한다. 기대 결과는 로그가 전환 전 RK 세대를 식별하거나 DDL/DML 순서가 옛 로그 적용을 보장하는 것이다.

### 권고안
핵심 불변식을 명시한다: 각 DML 로그는 생성 시 활성 RK의 테이블 ID, 제약/컬럼 ID, 순서, 스키마 세대를 식별하고, 적용기는 그 세대 정의가 유효한 동안 로그를 처리한다. 또는 DDL이 모든 옛 로그 적용 완료를 기다리는 등 대체 보장을 정한다.

### 검증 방법
UPDATE 로그 생성 후 적용을 멈추고 PK→PK, PK→UK 전환을 수행한 뒤 적용을 재개한다. 로그가 올바른 행을 찾고 최종 데이터가 같으며 키 전환 때문에 `fail_count`가 증가하지 않는지 확인한다.

## [DBDEV-1Y-02] 여러 UK 중 선택 알고리즘이 결정적인 함수가 아니다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 1절의 “엔진이 선택(ex. 테이블 명시 순서 중 빠른 순서)”
- 사실/추론 구분: 확인된 사실 — `ex.`는 예시이며 동일 입력에 항상 동일 출력을 내는 규칙이 확정되지 않았다
- 영향 대상: 엔진 개발자, source/replica, 백업·복원

### 문제
개발자가 어떤 UK를 고를지 구현할 기준이 없다. 카탈로그 조회 순서, 제약 이름 순서, 생성 순서 중 무엇을 사용하느냐에 따라 결과가 달라진다. DB 재시작이나 unload/load 후 저장 순서가 바뀌면 RK도 바뀔 수 있다.

### 왜 중요한가
결정적 함수는 같은 입력이면 언제나 같은 결과를 낸다. source와 replica가 다른 UK를 선택하면 동일 로그를 다른 컬럼 값으로 해석한다. 단순히 두 키 모두 UNIQUE라는 사실로 해결되지 않는다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE employee (
  employee_no INT NOT NULL CONSTRAINT uq_no UNIQUE,
  email VARCHAR(100) NOT NULL CONSTRAINT uq_email UNIQUE
) REPLICATION = ON;
```

카탈로그 스캔이 노드 A에서는 `uq_no`, B에서는 `uq_email`을 먼저 반환한다고 가정한다. 기대 결과는 스캔 순서와 무관하게 같은 제약 ID 규칙으로 하나를 고르는 것이다.

### 권고안
PK 우선 이후의 전체 정렬 키를 규범으로 정한다. 영구 제약 ID를 저장하거나 명시적 컬럼 ID 목록을 활성 RK로 카탈로그에 기록한다. 후보 추가 시 자동 변경 여부와 재선택 시점을 상태 전이로 명시한다.

### 검증 방법
제약 생성 순서, 이름, 카탈로그 물리 순서를 바꾼 동일 논리 스키마를 여러 노드에 만든다. 재시작·복원 후 활성 RK가 동일하고 동일 DML 로그를 성공적으로 적용하는지 시험한다.

## [DBDEV-1Y-03] OFF 테이블의 DDL·DML 로그 경계가 구현 수준에서 모호하다

- 분류: 컨셉
- 심각도: Critical
- 근거 위치: 원문 1절·4절의 모든 DDL 복제, ON 데이터만 복제, OFF 불일치 허용
- 사실/추론 구분: 확인이 필요한 질문 — OFF DML 로그를 생성하지 않는지, 생성 후 필터링하는지, 트랜잭션에 ON/OFF가 섞일 때 원자성이 어떻게 되는지 없다
- 영향 대상: 복제 모듈, 트랜잭션 엔진, 데이터 정합성

### 문제
“DDL은 모두, 데이터는 ON만 복제”라는 사용자 설명만으로 로그 계층의 책임을 정할 수 없다. 한 트랜잭션이 ON 테이블과 OFF 테이블을 함께 수정할 때 일부 DML만 전송하면 replica에서는 원래 트랜잭션과 다른 효과가 난다.

### 왜 중요한가
트랜잭션은 여러 변경을 하나의 성공/실패 단위로 묶는다. 일부 로그를 버리면 ON 행이 OFF 행을 전제로 한 값을 가질 수 있다. 적용기는 건너뛴 로그도 커밋 순서와 체크섬 계산에 어떻게 반영할지 알아야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE total (id INT PRIMARY KEY, amount INT) REPLICATION=ON;
CREATE TABLE local_event (id INT PRIMARY KEY, amount INT) REPLICATION=OFF;

-- 하나의 트랜잭션
INSERT INTO local_event VALUES (1, 100);
UPDATE total SET amount=amount+100 WHERE id=1;
COMMIT;
```

replica에는 total UPDATE만 적용된다. 이것이 의도된 부분 복제인지, 트랜잭션 메타데이터는 어떻게 유지하는지 문서에 없다.

### 권고안
로그 생성, 전송, 적용 중 어느 단계가 OFF DML을 제외하는지 정의한다. 혼합 트랜잭션의 커밋 ID·순서·오류 처리와 FK/trigger 파생 DML도 명시한다. OFF 필터링은 데이터 정합성 보장을 약화한다는 사용자 계약과 연결한다.

### 검증 방법
ON/OFF 테이블을 같은 트랜잭션에서 INSERT/UPDATE/DELETE하고 rollback·commit·crash를 조합한다. replica 로그 스트림의 순서가 끊기지 않고 ON 결과가 문서 규칙대로 한 번만 적용되는지 확인한다.

## [DBDEV-1Y-04] RK 후보와 활성 RK를 저장할 카탈로그 모델이 없다

- 분류: 누락
- 심각도: Major
- 근거 위치: 원문 1절의 후보 선택, 2-3절의 `db_class.replication`, 4-2절의 활성 키 수정 제한
- 사실/추론 구분: 확인된 사실 — ON/OFF 컬럼 예시만 있고 활성 제약·컬럼·세대를 저장하거나 조회할 정의가 없다
- 영향 대상: 카탈로그 개발자, 복제 적용기, 사용자 조회

### 문제
입문 개발자는 `replication` boolean만 추가하면 되는지, 활성 RK도 저장해야 하는지 판단하기 어렵다. 후보는 PK/UK 제약에서 계산할 수 있지만 활성 선택과 과거 세대를 매번 재계산하면 결정성 문제가 생긴다.

### 왜 중요한가
카탈로그는 DB가 재시작해도 유지되는 스키마 정보다. 활성 RK를 저장하지 않으면 캐시 재구성마다 다른 선택이 가능하다. 로그 적용에는 현재뿐 아니라 전환 직전 세대가 필요할 수 있다.

### 재현 또는 구체적 예제

```text
db_class: replication=ON
db_constraint: uq_no, uq_email
필요한 질문: active_rk는 어느 제약인가? generation은 몇인가?
```

원문 조회만으로 두 질문에 답할 수 없다.

### 권고안
논리 모델을 문서에 추가한다. 예: table ID, replication 상태, active RK constraint ID, ordered column IDs, generation, valid-from/to log position. 후보 계산 규칙과 활성 선택 저장 규칙, rename/drop 때 참조 갱신을 설명한다.

### 검증 방법
create, rename, add/drop constraint, restart, backup/restore마다 카탈로그 불변식을 검사한다. 활성 ID가 존재하는 제약을 가리키고 모든 구성 컬럼이 NOT NULL이며 ON 테이블에 유효 세대가 정확히 하나인지 확인한다.

## [DBDEV-1Y-05] 모드와 기본값을 parser·semantic check 어디서 처리할지 불명확하다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 1절의 hb start 외 single, 2-1절 기본 ON, 3절 single, 9절 single/SA
- 사실/추론 구분: 확인된 사실 — single과 SA 용어가 일관되지 않고 생성 시점과 HA 시작 시점의 검사가 나뉜다
- 영향 대상: parser/DDL 개발자, HA 제어 코드, 테스트 개발자

### 문제
옵션 생략을 parser가 ON으로 AST에 넣는지, 카탈로그 기본값으로 처리하는지 없다. RK 없는 ON 테이블은 single에서 허용하므로 DDL semantic check가 현재 모드를 알아야 하는지, HA 시작 검사만 담당하는지 구분이 필요하다.

### 왜 중요한가
검사 위치가 다르면 같은 SQL이 csql, load, 복구 로그 재생에서 서로 다른 결과를 낼 수 있다. SA와 server 모드를 잘못 판정하면 복원 중 DDL이 거부되거나 위험한 테이블이 허용된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE no_key (v INT); -- 옵션 생략
```

single에서는 카탈로그에 명시적 ON이 저장돼야 하는지, load 재생에서는 어떤 모드 검사를 하는지 명확하지 않다.

### 권고안
모드 용어와 상태 소유 모듈을 정의한다. 문법 기본값, 카탈로그 저장값, DDL semantic validation, HA readiness validation을 단계별로 분리하고 CREATE/ALTER/load/recovery 경로가 공통 검증 함수를 쓰도록 요구한다.

### 검증 방법
동일 SQL을 server non-HA, SA, HA, load, crash recovery 경로에서 실행한다. 허용 결과와 저장된 ON/OFF가 모드 행렬과 같고 우회 경로가 없는지 확인한다.

## [DBDEV-1Y-06] REPLICATION 문법의 AST와 정규 출력 계약이 부족하다

- 분류: 정확성
- 심각도: Major
- 근거 위치: 원문 2절의 CREATE/ALTER 옵션과 2-3절 `SHOW CREATE TABLE`
- 사실/추론 구분: 확인된 사실 — 중복 옵션, 허용 위치, 기존 옵션과 조합, 정규 출력 규칙이 없다
- 영향 대상: parser 개발자, DDL 생성기, unload/load

### 문제
문법 예시만 있어 `REPLICATION ON`과 `REPLICATION=ON`을 모두 허용하는지, 옵션 중복은 어떤 오류인지 알 수 없다. `SHOW CREATE TABLE` 출력이 parser로 다시 들어가 같은 AST가 되는지도 요구되지 않는다.

### 왜 중요한가
AST는 SQL 문장의 구조화된 표현이다. 입력과 출력 규칙이 없으면 parser, printer, dump 도구가 서로 다른 문법을 만들 수 있다. round-trip 실패는 복원 실패로 이어진다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE t (id INT PRIMARY KEY)
  REUSE_OID, COLLATE utf8_bin, REPLICATION ON;
CREATE TABLE bad (id INT PRIMARY KEY)
  REPLICATION ON REPLICATION OFF;
```

첫 문장은 정규 출력돼 재실행 가능해야 하고, 둘째는 안정된 중복 옵션 오류가 나야 한다.

### 권고안
EBNF 또는 동등한 문법을 추가하고 AST 필드, 생략 기본값, 중복·상충 오류, 기존 CREATE 변형별 지원을 정의한다. printer는 정규 표기 하나를 내고 parse→print→parse의 의미가 같아야 한다.

### 검증 방법
대소문자·공백·등호·옵션 순서 조합을 parser 단위 시험한다. `SHOW CREATE TABLE`과 unload DDL을 다시 parse하여 ON/OFF와 모든 기존 옵션이 동일한 AST인지 비교한다.

## [DBDEV-1Y-07] 하나의 ALTER 안에서 DROP+ADD를 검사하는 순서가 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 2-2절 예시 7과 4-2절 예시 13의 복합 ALTER 허용
- 사실/추론 구분: 확인이 필요한 질문 — 각 절을 순차 검사하는지 최종 스키마를 먼저 검사하는지, 실패 시 전체 롤백되는지 없다
- 영향 대상: DDL 개발자, 카탈로그, 복제 정합성

### 문제
`DROP old, ADD new`를 첫 절부터 검사하면 중간에 후보 0개라 잘못 거부할 수 있다. 반대로 최종 상태만 보고 실행하다 ADD가 중복 때문에 실패하면 DROP만 남지 않도록 전체를 롤백해야 한다.

### 왜 중요한가
DDL 계획 단계와 실행 단계를 구분해야 한다. 계획 단계에서는 모든 하위 연산을 적용한 가상 최종 스키마를 검사하고, 실행은 원자적으로 커밋해야 한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE c (
  id INT CONSTRAINT pk_c PRIMARY KEY,
  email VARCHAR(100)
) REPLICATION=ON;
INSERT INTO c VALUES (1,'x'),(2,'x');
ALTER TABLE c DROP CONSTRAINT pk_c,
  ADD CONSTRAINT uq_c_email UNIQUE(email);
```

새 UK 검증은 실패한다. 기대 결과는 PK/RK가 그대로이며 부분 카탈로그·인덱스가 남지 않는 것이다.

### 권고안
복합 ALTER 전체를 하나의 schema transformation으로 만들고 최종 후보·중복·NULL을 사전 검증한다. 인덱스 생성, 카탈로그 갱신, 로그 기록의 undo/redo 규칙과 replica 원자 적용을 명시한다.

### 검증 방법
중복, NULL, 디스크 부족, 인덱스 생성 취소, 로그 기록 전후 crash를 주입한다. 재시작 뒤 옛 상태 또는 새 상태 하나만 존재하고 중간 객체가 없는지 검사한다.

## [DBDEV-1Y-08] 키 컬럼 속성 변경의 semantic check 표가 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 제한된 ADD/DROP 예시와 “다른 후보가 있으면 모든 DDL 허용”
- 사실/추론 구분: 확인된 사실 — rename, 타입, NOT NULL, collation, 복합 키 변경 규칙이 없다
- 영향 대상: DDL 개발자, 테스트 개발자, 복제 적용기

### 문제
개발자가 마지막 UK의 `NOT NULL` 제거, 활성 RK 컬럼 타입 변경, 제약 rename을 허용할지 결정할 기준이 없다. 다른 후보가 있어도 활성 RK 전환을 먼저 해야 하는지 명확하지 않다.

### 왜 중요한가
RK 후보 자격은 제약뿐 아니라 컬럼 속성에 의존한다. 문자 비교 규칙이나 타입이 바뀌면 옛 로그 값의 직렬화와 비교도 달라진다. 누락된 검사는 데이터 적용 오류가 된다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE device (
  serial VARCHAR(30) NOT NULL UNIQUE,
  legacy_id INT NOT NULL UNIQUE
) REPLICATION=ON;
ALTER TABLE device ALTER COLUMN serial DROP NOT NULL;
ALTER TABLE device RENAME COLUMN legacy_id AS old_id;
```

활성 RK가 serial인지 legacy_id인지에 따라 필요한 전환이 다르다.

### 권고안
활성 RK/비활성 후보/마지막 후보 × add/drop/rename/type/collation/NOT NULL 변경의 허용 표를 만든다. 각 셀에 사전 조건, 최종 활성 RK, schema generation 증가, 오류 코드를 정의한다.

### 검증 방법
표를 데이터 기반 단위 시험으로 구현한다. 단일·복합, 숫자·문자열 키에서 모든 전이를 실행하고 최종 카탈로그 불변식과 replica 스키마를 비교한다.

## [DBDEV-1Y-09] DDL/DML 로그의 전역 적용 순서와 schema generation이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 모든 DDL 복제와 운영 중 DML 가능
- 사실/추론 구분: 확인이 필요한 질문 — 커밋 순서, 로그 레코드가 참조하는 스키마 세대, 지연 적용 규칙이 없다
- 영향 대상: 로그 생성기, 복제 적용기, 복제 정합성

### 문제
DDL과 DML이 서로 다른 로그 종류나 큐를 사용한다면 replica에서 커밋 순서가 뒤집힐 수 있다. DML 레코드에 schema generation이 없으면 적용기가 현재 카탈로그로 옛 로그를 해석할 수 있다.

### 왜 중요한가
같은 트랜잭션 순서를 모든 노드가 보존해야 같은 상태가 된다. generation은 “이 로그를 만들 때 사용한 스키마 버전 번호”다. 번호가 있으면 적용 전에 올바른 DDL까지 처리됐는지 검사할 수 있다.

### 재현 또는 구체적 예제

```text
LSA 100: UPDATE by RK(id), generation 5
LSA 101: ALTER RK id→email, generation 6
LSA 102: UPDATE by RK(email), generation 6
```

적용 순서는 100→101→102여야 한다. 101이 먼저 적용되면 100을 옛 세대로 해석할 방법이 필요하다.

### 권고안
DDL/DML의 총 커밋 순서와 generation 필드를 명시한다. 적용기는 예상 generation 불일치 시 조용히 추측하지 말고 대기·재시도 또는 명확한 오류를 내야 한다. 옛 세대 정의의 보존·정리 조건도 정한다.

### 검증 방법
복제 큐 지연과 재정렬을 의도적으로 발생시키고 LSA 100~102를 적용한다. 순서가 보정되거나 안전하게 중단되고 잘못된 행에는 적용되지 않는지 확인한다.

## [DBDEV-1Y-10] RK 변경 후 카탈로그 캐시 무효화와 crash recovery가 빠졌다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 4-2절의 운영 중 키 전환; 캐시·재시작 동작 없음
- 사실/추론 구분: 확인이 필요한 질문 — 세션·적용기 캐시가 새 RK를 언제 다시 읽는지, crash 뒤 선택을 어떻게 복구하는지 없다
- 영향 대상: 카탈로그 캐시, 복제 적용기, 세션 실행기

### 문제
엔진은 성능을 위해 테이블과 인덱스 정보를 메모리에 캐시할 수 있다. DDL 뒤 일부 스레드가 옛 활성 RK를 계속 사용하면 같은 노드 안에서도 서로 다른 로그를 만들 수 있다. 크래시 뒤 카탈로그와 로그 중 어느 상태로 복구하는지도 없다.

### 왜 중요한가
디스크 카탈로그만 정확해도 메모리 캐시가 오래되면 오류가 난다. 캐시 무효화는 DDL 커밋과 같은 경계에 묶여 모든 reader가 old 또는 new 중 하나를 보게 해야 한다.

### 재현 또는 구체적 예제

```text
세션 A가 table descriptor generation 5를 캐시
세션 B가 RK 변경을 generation 6으로 커밋
세션 A가 다시 UPDATE 로그 생성
```

세션 A는 generation 6을 다시 읽거나 명확히 재시도해야 한다.

### 권고안
DDL 커밋 시 table descriptor, constraint/index cache, replication apply cache의 무효화 순서를 정의한다. descriptor에 generation을 두고 stale 사용을 검사한다. crash redo/undo 후 캐시를 디스크의 커밋 상태에서 재구성한다.

### 검증 방법
여러 세션이 descriptor를 캐시한 상태에서 RK를 반복 변경한다. DDL 커밋 경계와 crash 직후 DML을 실행해 모든 로그 generation과 활성 RK가 카탈로그와 같은지 확인한다.

## [DBDEV-1Y-11] HA readiness 검사는 TOCTOU를 막는 불변식이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 7절의 HA 실행 시 RK/FK 검사
- 사실/추론 구분: 확인된 사실 — 검사와 HA 활성화 사이 DDL 차단, 일관된 스냅샷, 모든 노드 비교가 없다
- 영향 대상: HA 제어 코드, DDL 엔진, 운영 자동화

### 문제
검사할 때는 정상이어도 활성화 직전에 마지막 UK가 삭제될 수 있다. 이를 TOCTOU, 즉 “검사한 시점과 사용한 시점 사이 상태 변화” 문제라고 한다. 파일 리스트라는 출력도 구현 대상 객체를 특정하지 못한다.

### 왜 중요한가
검사가 원자적이지 않으면 통과 결과를 신뢰할 수 없다. HA 시작 후 위반 테이블을 발견하면 복제 적용이 이미 시작되어 복구가 더 어렵다.

### 재현 또는 구체적 예제

```text
1. readiness가 table t의 UK를 확인
2. 다른 세션이 UK 삭제를 커밋
3. HA가 ON 상태로 전환
```

기대 결과는 2가 전환 잠금에 막히거나 검사가 재시도되어 3이 실패하는 것이다.

### 권고안
일관된 카탈로그 스냅샷과 HA transition lock으로 검사와 활성화를 묶는다. 검사 대상은 모든 ON 테이블, 활성 RK 불변식, FK 그래프, 노드별 schema generation으로 정한다. 구조화된 객체 오류 목록을 반환한다.

### 검증 방법
readiness 각 테이블 검사 지점에 동시 CREATE/ALTER/DROP을 주입한다. 위반 상태로 HA가 활성화되지 않고 deadlock 없이 명확한 재시도 또는 오류가 발생하는지 확인한다.

## [DBDEV-1Y-12] 복합 RK의 직렬화·NULL·collation 규칙이 없다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절의 NOT NULL UK 후보 규칙; 복합·타입별 로그 형식 없음
- 사실/추론 구분: 확인이 필요한 질문 — 복합 UK 지원, 컬럼 순서, 값 경계, NULL 표현과 문자열 비교 규칙이 없다
- 영향 대상: 로그 포맷, 복제 적용기, 인덱스 검색

### 문제
여러 컬럼 값을 단순 연결하면 `(1,23)`과 `(12,3)`을 구분하지 못할 수 있다. 문자열 길이, 문자셋, collation, NULL 표시를 로그가 정확히 보존해야 한다. 모든 구성 컬럼이 NOT NULL인지도 명시적 예제가 없다.

### 왜 중요한가
직렬화는 여러 값을 바이트로 바꾸는 규칙이다. source와 replica가 똑같이 해석하지 않으면 다른 인덱스 범위를 찾는다. 길이와 타입 태그가 있어야 값 경계를 안전하게 구분한다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE pair_key (
  a INT NOT NULL,
  b VARCHAR(20) NOT NULL,
  CONSTRAINT uq_pair UNIQUE(a,b)
) REPLICATION=ON;
```

행 `(1,'23')`과 `(12,'3')`, 다국어 문자열, 빈 문자열을 로그로 보내도 서로 구분되어야 한다.

### 권고안
RK 로그 인코딩의 컬럼 수·순서·타입 OID·길이·값·collation/schema generation을 정의한다. 지원/비지원 타입, 최대 크기, 모든 복합 컬럼 NOT NULL 조건을 명시한다.

### 검증 방법
경계가 모호한 숫자·문자열, 빈 값, 최대 길이, 다국어, 복합 2~8컬럼을 round-trip 직렬화한다. source에서 만든 바이트를 replica가 같은 값과 인덱스 키로 복원하는지 property test를 수행한다.

## [DBDEV-1Y-13] 활성 RK 값 UPDATE에 old/new 이미지 규칙이 없다

- 분류: 누락
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 RK 제약 DDL만 설명; RK 컬럼 DML 없음
- 사실/추론 구분: 확인이 필요한 질문 — 적용 대상 검색에 이전 값과 새 값 중 무엇을 사용하는지 없다
- 영향 대상: 로그 생성기, 적용기, 데이터 정합성

### 문제
RK 값 자체를 UPDATE하면 replica에는 아직 새 값의 행이 없다. 로그가 새 값만 담으면 대상 행을 찾지 못한다. old 값으로 찾은 뒤 new 값을 저장해야 할 수 있지만 중복 충돌과 rollback 규칙도 필요하다.

### 왜 중요한가
UPDATE에는 “찾을 주소”와 “저장할 새 주소”가 모두 필요하다. 둘을 구분하지 않으면 키 변경 DML이 누락되거나 다른 행에 적용될 수 있다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE parcel (
  tracking VARCHAR(50) NOT NULL UNIQUE,
  status VARCHAR(20)
) REPLICATION=ON;
UPDATE parcel SET tracking='NEW' WHERE tracking='OLD';
```

replica는 `OLD`로 행을 찾고 `NEW`로 바꿔야 한다. NEW가 이미 존재하면 source와 replica가 모두 같은 트랜잭션 실패를 가져야 한다.

### 권고안
RK UPDATE 로그에 old key와 new row/key 이미지를 구분해 정의한다. old key 검색, row identity 검증, new unique 검사, 원자 update 순서와 재적용 멱등성을 명시한다.

### 검증 방법
단일·복합 RK 값 변경, 두 행 키 교환, 중복 충돌, rollback, 같은 로그 두 번 적용을 시험한다. 최종 행 수와 키가 같고 중복 효과나 `fail_count` 증가가 없는지 확인한다.

## [DBDEV-1Y-14] FK와 VIEW 의존성 검사가 어느 엔진 계층 책임인지 없다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 5절의 FK 제약, 6절의 OFF 포함 VIEW 결과 불일치
- 사실/추론 구분: 확인된 사실 — 직접 FK 일부만 규정하며 CASCADE, 기존 옵션 변경, 중첩 VIEW 의존성 갱신은 없다
- 영향 대상: DDL semantic checker, dependency catalog, 복제 모듈

### 문제
ON 자식→OFF 부모 CREATE는 막아야 하지만 부모를 나중에 OFF로 바꾸는 ALTER도 같은 검사를 재사용해야 한다. CASCADE 파생 DML과 OFF 자식 조합, OFF 테이블을 간접 참조하는 중첩 VIEW도 의존성 그래프가 필요하다.

### 왜 중요한가
의존성 검사가 SQL 문장별로 흩어지면 한 경로가 검사를 우회한다. 공통 그래프와 불변식이 있어야 CREATE FK, ALTER REPLICATION, DROP, load 모두 같은 결과를 낸다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE p (id INT PRIMARY KEY) REPLICATION=ON;
CREATE TABLE c (
  id INT PRIMARY KEY, pid INT,
  FOREIGN KEY(pid) REFERENCES p(id) ON DELETE CASCADE
) REPLICATION=ON;
ALTER TABLE p REPLICATION=OFF;
```

기존 ON 자식 때문에 ALTER가 거부돼야 하는지 명확히 정해야 한다. VIEW가 c를 거쳐 p를 참조하는 경우도 영향 목록이 필요하다.

### 권고안
dependency catalog 기반 공통 검증 API를 정의한다. 부모/자식 ON/OFF 2×2, referential action, CREATE/ALTER/load, 직접·간접 VIEW를 상태표로 만들고 파생 DML의 복제 여부를 명시한다.

### 검증 방법
다단계·순환 FK와 3단계 VIEW를 만들고 각 객체를 ON↔OFF 변경한다. 모든 진입 경로가 같은 오류를 내고 dependency cache가 DDL 뒤 정확히 무효화되는지 확인한다.

## [DBDEV-1Y-15] `fail_count`의 증가 위치와 오류 분류가 정의되지 않는다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 전체; 복제 오류·불일치는 다루지만 `fail_count` 규칙 없음
- 사실/추론 구분: 확인된 사실 — 카운터 단위, 재시도 중복, 초기화, 테이블·로그 연결 정보가 없다
- 영향 대상: 복제 적용기 개발자, 운영자, 테스트 개발자

### 문제
개발자가 적용 함수 호출 실패마다 증가시킬지, 고유 로그 레코드마다 한 번 증가시킬지 알 수 없다. 일시적 lock timeout과 데이터 없음 같은 영구 오류를 같은 방식으로 세면 운영자가 상태를 오해한다.

### 왜 중요한가
같은 로그를 100회 재시도해 100으로 만들면 실제 손상 행 수와 다르다. 반대로 재시작 때 0으로 만들면 미해결 장애가 숨는다. 코드 경로와 사용자 의미가 일치해야 한다.

### 재현 또는 구체적 예제

```text
LSA 500의 row-not-found를 10회 재시도
LSA 501의 lock timeout은 다음 시도에 성공
```

누적 이벤트, 고유 실패, 현재 미해결 값이 각각 무엇인지 정의가 필요하다.

### 권고안
고유 failure ID를 DB/table/LSA/error/RK generation으로 정의하고 누적 시도 수와 현재 미해결 수를 분리한다. 증가·해소·보존·재시작 규칙, 오류 분류와 metric/event 출력 위치를 명시한다.

### 검증 방법
row-not-found, duplicate, generation mismatch, lock timeout을 주입하고 재시도·재시작한다. 각 카운터와 이벤트가 정의대로 변화하고 오류에서 대상 로그와 테이블을 추적할 수 있는지 확인한다.

## [DBDEV-1Y-16] 불일치 탐지와 repair의 멱등성 요구가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 4절·6절의 불일치 가능성, 7절의 스키마 수정만 안내
- 사실/추론 구분: 확인된 사실 — 기존 행 차이를 찾거나 교정하는 구현·도구 계약이 없다
- 영향 대상: 엔진 도구 개발자, 복제 정합성, DBA

### 문제
새 제약은 과거 누락을 고치지 않는다. 비교 도구가 일관된 스냅샷을 사용하지 않거나 repair를 두 번 실행했을 때 결과가 달라지면 더 큰 오류를 만들 수 있다.

### 왜 중요한가
멱등성은 같은 작업을 여러 번 실행해도 결과가 한 번 실행한 것과 같은 성질이다. 네트워크 장애 뒤 repair를 재시도할 수 있으려면 작업 ID와 진행 지점이 필요하다.

### 재현 또는 구체적 예제
source에는 `(id=1,v=100)`, replica에는 `(id=1,v=90)`이 있고 비교 중 source가 110으로 바뀐다고 가정한다. 오래된 결과로 100을 쓰면 최신 값을 잃는다.

### 권고안
RK 범위별 일관된 snapshot/checksum, 차이 행 증거, source-of-truth 승인, change conflict 검출, idempotent repair ID와 checkpoint를 정의한다. repair DML의 일반 복제 경로 통과 여부도 명시한다.

### 검증 방법
비교·repair 중 동시 DML, 중단, 중복 실행을 주입한다. 최신 커밋을 잃지 않고 최종 체크섬이 같으며 같은 repair ID 재실행이 추가 변경을 만들지 않는지 확인한다.

## [DBDEV-1Y-17] unload/load 기본값 상충과 포맷 버전이 구현을 막는다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절은 복제 값 없으면 ON, 9절 5항은 없으면 OFF
- 사실/추론 구분: 확인된 사실 — 동일한 무표기 입력에 반대 결과를 요구하며 포맷 버전·필드 문법도 없다
- 영향 대상: unload/load 개발자, 업그레이드, 데이터 정합성

### 문제
개발자가 어느 기본값을 구현해도 한 절을 위반한다. 새 필드의 이름·버전·unknown value 처리, 구버전 parser가 새 필드를 만났을 때의 동작도 없다.

### 왜 중요한가
dump 포맷은 버전 사이 계약이다. 구버전 파일의 무표기를 잘못 해석하면 수천 테이블의 ON/OFF가 뒤집힌다. 신버전 파일을 구버전에 넣을 때 조용히 옵션을 무시하면 더 위험하다.

### 재현 또는 구체적 예제

```text
format_version=old
table customer: replication field absent, PK present
table raw_log: replication field absent, RK absent
```

둘 다 ON 또는 OFF로 자동 처리하는 것은 각각 위험이 있다.

### 권고안
상충 정책을 먼저 결정하고 dump 포맷 버전, 필드 문법, required/optional, unknown 처리와 downgrade 규칙을 명시한다. 무표기는 명시적 load 기본 옵션 또는 ERROR를 요구하고 dry-run 결과를 제공한다.

### 검증 방법
old/new/미래 unknown 버전 파일과 필드 없음/ON/OFF를 교차 load한다. parser가 조용히 잘못 해석하지 않고 dry-run·카탈로그·readiness 결과가 같은지 확인한다.

## [DBDEV-1Y-18] 혼합 버전 로그·카탈로그와 성능 회귀 시험이 없다

- 분류: 호환성
- 심각도: Blocker
- 근거 위치: 원문 8절의 하위 버전 unload 언급; 롤링 업그레이드와 프로토콜·성능 기준 없음
- 사실/추론 구분: 확인이 필요한 질문 — 구버전 적용기가 새 DDL/RK 로그를 해석할 수 있는지 없다
- 영향 대상: 복제 프로토콜 개발자, 릴리스 엔지니어, 사용자

### 문제
신버전 primary가 generation과 REPLICATION 메타데이터를 로그에 추가하면 구버전 replica의 decoder 동작을 정해야 한다. 무시, 오류, 연결 거부 중 계약이 없다. 복합 UK 로그로 커지는 비용도 시험 기준이 없다.

### 왜 중요한가
unknown 필드를 잘못 건너뛰면 조용한 데이터 손상이 가능하다. 명확히 연결을 거부하는 편이 가용성은 낮아도 안전할 수 있다. 버전 협상과 성능 한계는 출시 전에 시험해야 한다.

### 재현 또는 구체적 예제

```text
primary N: DDL record version 2, active_rk_generation=6
replica N-1: decoder supports record version 1 only
```

replica가 v2를 v1처럼 읽어서는 안 된다.

### 권고안
로그·카탈로그 format version과 capability handshake를 정의한다. 비호환 노드가 있으면 새 기능 DDL을 거부하거나 replica 연결을 안전하게 중단한다. 정수 PK와 긴 복합 UK의 로그 크기·TPS·lag 회귀 목표를 둔다.

### 검증 방법
N/N-1 양방향 primary/replica와 중간 failover·rollback을 시험한다. unknown record가 명확한 오류로 처리되고 데이터에 적용되지 않는지 확인한다. 키 크기별 부하에서 지원 한계를 측정한다.

## [DBDEV-1Y-19] 예제가 단위·통합 시험으로 변환될 만큼 구체적이지 않다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 2~5절의 `ERROR`/`OK`, `...`, 후행 쉼표, 초기 상태 생략
- 사실/추론 구분: 확인된 사실 — 예제 대부분에 완전한 setup, 오류 코드, 사후 카탈로그와 데이터가 없다
- 영향 대상: 1년차 개발자, QA, 회귀 시험

### 문제
예시 7은 제약 이름과 컬럼이 `...`이고, 여러 CREATE에는 후행 쉼표가 있다. `ERROR`만으로 parser 오류, semantic 오류, replica 적용 오류를 구분할 수 없다.

### 왜 중요한가
신입 개발자는 사용자 스펙 예제를 첫 테스트로 옮긴다. 기대 상태가 없으면 SQL 반환 코드만 확인하고 부분 카탈로그 변경이나 데이터 차이를 놓칠 수 있다.

### 재현 또는 구체적 예제

```sql
ALTER TABLE tbl DROP CONSTRAINT ...,
  ADD CONSTRAINT ...;
```

이 문장으로는 입력 AST, 예상 활성 RK, 실패 injection, 사후 assertion을 만들 수 없다.

### 권고안
모든 예제를 setup/action/assert/cleanup으로 고친다. 모드, 초기 후보·활성 RK, 완전한 SQL, 오류 코드, 최종 카탈로그 generation, 양 노드 데이터를 포함한다. 문서 코드 블록을 CI에서 실행한다.

### 검증 방법
1년차 개발자가 각 예제를 parser 단위, DDL 통합, HA 복제 시험으로 변환하게 한다. 요구사항 질문 없이 expected 결과를 작성할 수 있고 CI 실행 결과와 문서가 일치하는지 확인한다.

## [DBDEV-1Y-20] 용어·오탈자·상충 문장이 구현 책임을 혼동시킨다

- 분류: 문서 품질
- 심각도: Major
- 근거 위치: 원문 5-1절 `CRATE TABLE`, 7절 “파일 리스트”, 8·9절 기본값 상충, single/SA/HA 표현
- 사실/추론 구분: 확인된 사실 — 오탈자와 정책 충돌이 섞여 있으며 “HA 전환”의 사건 범위가 모호하다
- 영향 대상: 엔진 개발자, HA 개발자, 문서·테스트 담당자

### 문제
단순 철자 오류는 고치면 되지만 ON/OFF 기본값 상충은 제품 결정을 필요로 한다. “HA 전환”이 최초 시작인지 failover인지에 따라 검사를 넣을 코드 경로가 달라진다. “파일 리스트”도 파일 시스템 경로인지 위반 테이블 목록인지 알 수 없다.

### 왜 중요한가
용어가 모호하면 parser, HA controller, replication applier가 서로 책임이라고 생각해 검사가 빠지거나 중복된다. 오류를 늦게 발견할수록 rollback하기 어렵다.

### 재현 또는 구체적 예제

```text
non-HA server start / standalone(SA) / HA cluster start /
planned switchover / unplanned failover / failback
```

각 사건은 다른 상태 전이와 검사 함수를 가져야 하지만 원문은 충분히 분리하지 않는다.

### 권고안
표준 용어집과 모듈 책임 표를 추가한다. 오탈자는 교정하고, 정책 상충은 decision record로 결정한 뒤 적용 버전과 테스트를 연결한다. 각 규범 문장에 담당 컴포넌트와 수용 시험 ID를 역참조한다.

### 검증 방법
요구사항 추적표에서 모든 규칙이 parser/DDL/catalog/log/applier/HA control 중 하나 이상의 구현과 시험에 연결되는지 확인한다. 용어 린트와 상충 기본값 검사를 문서 CI에 추가한다.

## [DBDEV-1Y-21] 복제 정책을 바꿀 권한의 검사 지점이 없다

- 분류: 보안
- 심각도: Critical
- 근거 위치: 원문 2-2절의 `ALTER TABLE ... REPLICATION`과 4절의 운영 중 DDL 허용 규칙
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 현재 권한 체계에서 이 옵션을 누가 바꿀 수 있고 어느 계층이 검사하는지 원문만으로 확인할 수 없다
- 영향 대상: 엔진 개발자, DBA, 복제 정합성, 보안 담당자

### 문제
`REPLICATION=OFF`는 단순 표시 변경이 아니라 이후 DML을 standby에 보내지 않는 정책 변경이다. 그러나 테이블 소유자, 일반 `ALTER` 권한 보유자, DBA 중 누가 이를 실행할 수 있는지와 parser·DDL executor·HA 모듈 중 어디서 권한을 검사할지가 없다.

### 왜 중요한가
권한이 너무 넓으면 스키마를 조금 수정할 수 있는 계정이 복제를 끄고 장애 조치 후 데이터 손실처럼 보이는 불일치를 만들 수 있다. 반대로 검사 위치가 여러 곳이면 일반 DDL은 통과하고 복제 정책만 부분 적용되는 버그가 생길 수 있다.

### 재현 또는 구체적 예제

```sql
-- app_owner가 테이블을 만들고 deployer에게 ALTER 권한만 줬다고 가정한다.
ALTER TABLE payment REPLICATION=OFF;
UPDATE payment SET status='PAID' WHERE payment_id=10;
```

`deployer`의 첫 문장이 허용되는지, 거부된다면 어떤 권한 오류인지가 정의되지 않았다. 허용되면 두 번째 변경은 replica에 없을 수 있다.

### 권고안
복제 정책 변경에 필요한 전용 권한 또는 관리자 권한을 명시하고 DDL 실행 전 한 지점에서 검사한다. 실패 시 카탈로그와 로그가 전혀 바뀌지 않아야 하며, 내부 재적용 계정에는 별도의 검증된 경로를 둔다.

### 검증 방법
소유자, `ALTER`만 가진 사용자, 읽기 전용 사용자, DBA, replication applier 계정별 허용표를 시험한다. 거부된 문장 전후로 카탈로그 값, DDL 로그 수, 양 노드 데이터를 비교해 부작용이 없음을 확인한다.

## [DBDEV-1Y-22] 감사 기록과 정책 변경의 원자적 관계가 정의되지 않았다

- 분류: 운영성
- 심각도: Major
- 근거 위치: 원문 2-2절의 ON/OFF 변경과 6절의 OFF 테이블 불일치 책임 제외
- 사실/추론 구분: 확인이 필요한 질문 — 복제 정책 변경을 남기는 감사 기능과 트랜잭션 관계를 원문에서 확인할 수 없다
- 영향 대상: 엔진 개발자, DBA, 보안 감사, 장애 분석

### 문제
누가 언제 어떤 테이블을 ON에서 OFF로 바꿨는지, 실패한 시도도 기록하는지, 감사 기록이 DDL commit과 함께 확정되는지 명세가 없다.

### 왜 중요한가
failover 뒤 행이 없을 때 운영자는 정상적인 OFF 정책인지 복제 결함인지 구분해야 한다. 카탈로그만 보면 과거 상태는 사라진다. 감사 기록이 DDL보다 먼저 또는 늦게 저장되면 크래시 시 실제 상태와 기록이 반대가 될 수 있다.

### 재현 또는 구체적 예제

```text
T1: user=deploy, table=orders, ON -> OFF 요청
T2: 카탈로그 갱신 직후 프로세스 강제 종료
T3: 재시작 후 orders=OFF, 감사 이벤트 없음
```

이 상태에서는 의도적 변경임을 증명하기 어렵다. 반대인 `orders=ON`인데 성공 감사만 남는 경우도 피해야 한다.

### 권고안
감사 이벤트에 사용자, 세션, 테이블의 안정 ID, 이전/새 값, commit 식별자, 성공/실패와 오류 코드를 둔다. 성공 이벤트는 DDL commit과 원자적으로 확정하거나 WAL에서 결정적으로 재구성하도록 한다.

### 검증 방법
권한 실패, semantic 실패, commit 전·후 crash를 각각 주입한다. 복구된 카탈로그 상태와 감사 성공 이벤트가 항상 일치하고 실패 시도는 성공 이벤트와 구분되는지 확인한다.

## [DBDEV-1Y-23] 파티션 테이블에서 RK와 REPLICATION 소유 주체가 불명확하다

- 분류: 누락
- 심각도: Critical
- 근거 위치: 원문 2-3절 `db_class` 예시에 `partitioned` 속성이 있으나 1~9절에 파티션별 규칙이 없음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 CUBRID 버전의 파티션 DDL 지원 범위와 전역 유일성 보장은 구현 확인이 필요하다
- 영향 대상: 엔진 개발자, 파티션 테이블 사용자, 복제 정합성

### 문제
부모 테이블과 각 파티션 중 누가 REPLICATION 값과 활성 RK를 소유하는지, 파티션 키 이동과 분할·병합 때 같은 RK 세대를 유지하는지가 없다. UK가 각 파티션 안에서만 유일하다면 전체 테이블의 행 주소가 되지 못할 수도 있다.

### 왜 중요한가
예를 들어 `id=7`이 두 파티션에 존재할 수 있으면 로그에 `id=7`만 기록해서는 어느 행인지 찾을 수 없다. 파티션 ID를 주소에 넣거나 전체 범위 유일성을 보장해야 한다.

### 재현 또는 구체적 예제

```sql
-- 실제 지원 문법은 확인 필요
CREATE TABLE event_log(id INT NOT NULL, event_day DATE NOT NULL,
  UNIQUE(id)) REPLICATION=ON
  PARTITION BY RANGE(event_day) (...);
UPDATE event_log SET event_day=DATE '2027-01-01' WHERE id=7;
```

행이 다른 파티션으로 이동할 때 로그가 기존 파티션, 새 파티션, 논리 테이블 중 무엇을 식별하는지 불명확하다.

### 권고안
지원 대상 파티션 DDL을 먼저 확정하고 논리 테이블 ID, 물리 파티션 ID, RK 유일성 범위를 명시한다. 전역 유일성이 없으면 ON을 거부하거나 파티션 식별자를 로그 키에 포함한다.

### 검증 방법
대상 버전에서 지원 문법을 확인한 뒤 파티션 생성, attach/detach 또는 이에 대응하는 DDL, split/merge, 키 변경으로 파티션 이동을 시험한다. 동일 값 후보가 있어도 정확히 한 행만 변경되는지 확인한다.

## [DBDEV-1Y-24] TRUNCATE와 대량 적재 경로가 REPLICATION 정책을 우회할 수 있다

- 분류: 정확성
- 심각도: Critical
- 근거 위치: 원문 1절은 데이터 변경 복제를 설명하지만 4절은 일반 DDL을 포괄적으로 허용하고 특수 데이터 경로를 구분하지 않음
- 사실/추론 구분: 확인이 필요한 질문 — `TRUNCATE`, `loaddb` 및 대량 적재가 일반 행 DML과 같은 복제 훅을 쓰는지는 구현 확인이 필요하다
- 영향 대상: 엔진 개발자, 복제 정합성, 복원 담당자

### 문제
행별 INSERT/DELETE가 아닌 `TRUNCATE`나 bulk load가 DDL 로그인지 DML 로그인지, ON/OFF를 어느 시점 값으로 판단하는지 없다. 일반 DML 경로에만 RK 검사를 넣으면 특수 경로가 우회할 수 있다.

### 왜 중요한가
대량 작업은 수백만 행을 한 번에 바꾼다. 한 경로가 누락되면 `fail_count` 한 건이 아니라 테이블 전체가 달라질 수 있다. RK가 필요한 행별 적용과 테이블 단위 명령 적용도 구현 방식이 다르다.

### 재현 또는 구체적 예제

```sql
CREATE TABLE stage_data(id INT PRIMARY KEY, v INT) REPLICATION=ON;
-- 100만 행 적재 후
TRUNCATE TABLE stage_data;
```

기대 결과는 ON 테이블의 replica도 비워지는 것이다. 원문은 명령 로그, 행별 로그, 비지원 중 어느 계약인지 말하지 않는다.

### 권고안
데이터를 바꾸는 모든 진입점을 목록화하고 ON/OFF, RK, 트랜잭션, crash 규칙을 표로 만든다. 지원하지 않는 경로는 실행 전에 명확히 거부하고 부분 적재를 남기지 않는다.

### 검증 방법
일반 DML, `TRUNCATE`, `loaddb`, 지원되는 bulk API를 같은 초기 데이터에 적용한다. commit·rollback·중간 crash 후 양 노드의 행 수와 checksum, 복제 로그 종류를 비교한다.

## [DBDEV-1Y-25] 병렬 apply에서 DDL 장벽을 세우는 규칙이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 모든 DDL 복제와 4-2절의 운영 중 RK 변경 허용
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID의 실제 apply 병렬성은 확인 필요하지만, 병렬 또는 비동기 처리 시 필요한 순서 규칙이 문서에 없다
- 영향 대상: 복제 적용기 개발자, 복제 정합성, 성능 시험 담당자

### 문제
여러 worker가 DML을 적용할 수 있다면 RK 변경 DDL 전의 작업을 모두 끝내고 캐시를 비운 뒤 다음 DML을 시작하는 장벽이 필요하다. 원문은 로그의 전체 순서만 암시할 뿐 worker drain 규칙은 없다.

### 왜 중요한가
로그 번호가 순서대로 읽혀도 실제 실행 완료 순서는 다를 수 있다. DDL 뒤 DML worker가 먼저 끝나거나 옛 DML이 새 카탈로그로 실행되면 잘못된 행 검색 또는 적용 실패가 발생한다.

### 재현 또는 구체적 예제

```text
LSN 100 worker A: UPDATE id=10 (오래 걸림, old RK)
LSN 101 DDL worker: PK(id) -> UK(email)
LSN 102 worker B: UPDATE email='a@x' (new RK)
```

DDL worker가 A보다 먼저 commit하면 A가 옛 RK 정의를 잃을 수 있다.

### 권고안
RK/REPLICATION 관련 DDL을 schema barrier로 정의한다. barrier 전 worker를 drain하고 DDL commit·캐시 무효화 후 새 세대 worker를 연다. 실패 시 barrier 위치부터 재시작 가능한 체크포인트를 기록한다.

### 검증 방법
worker A를 의도적으로 정지한 상태에서 DDL과 후속 DML을 공급한다. DDL이 대기하고, 재시작 후에도 각 세대의 순서와 최종 데이터가 보존되는지 worker 수 1과 여러 개에서 비교한다.

## [DBDEV-1Y-26] 시점 복구가 참조하는 RK 메타데이터의 보존 기간이 없다

- 분류: 호환성
- 심각도: Critical
- 근거 위치: 원문 8절은 unload/load만 설명하며 로그 기반 시점 복구와 옛 RK 정의 보존은 다루지 않음
- 사실/추론 구분: 확인이 필요한 질문 — 대상 버전의 PITR 기능과 복제 로그 보관 구조는 구현 및 운영 문서 확인이 필요하다
- 영향 대상: 복구 엔진 개발자, DBA, 데이터 정합성

### 문제
백업 시점 이후 RK가 여러 번 바뀌면 시점 복구는 옛 DML 로그를 당시 키 정의로 해석해야 한다. 그러나 삭제된 제약과 RK generation을 언제 정리할 수 있는지 기준이 없다.

### 왜 중요한가
현재 카탈로그만 백업하고 옛 로그만 오래 보존하면, 로그는 있어도 행 주소의 뜻을 잃어 복구할 수 없다. 이는 백업 성공 표시와 실제 복구 가능성이 다른 상태다.

### 재현 또는 구체적 예제

```text
00:00 full backup: RK=id, generation 1
01:00 ALTER: RK=email, generation 2
02:00 ALTER: RK=account_no, generation 3
03:00 target recovery time: 01:30
```

복구기는 generation 1과 2 정의 및 전환 장벽을 모두 필요로 하지만 보존 계약이 없다.

### 권고안
백업 manifest에 카탈로그/로그 포맷과 필요한 RK generation 범위를 기록한다. 가장 오래된 복구 가능 시점보다 오래된 정의만 정리하며, 필요한 로그나 메타데이터가 없으면 복구 시작 전에 진단한다.

### 검증 방법
두 번 이상 RK를 바꾸고 각 전후 시점으로 복구한다. old/new 키 값 자체도 UPDATE한 데이터를 포함해 목표 시점 결과와 checksum이 일치하는지 확인하고, generation 하나를 제거했을 때 사전 오류가 나는지 시험한다.

## [DBDEV-1Y-27] 디스크 full에서 DDL·로그·카탈로그의 부분 성공 규칙이 없다

- 분류: 운영성
- 심각도: Blocker
- 근거 위치: 원문 4-2절의 운영 중 키 전환과 7절의 HA 검사; 리소스 고갈 시 동작은 없음
- 사실/추론 구분: 문서에서 도출한 추론 — 여러 영속 객체를 갱신하는 기능에는 저장 실패 지점별 원자성 정의가 필요하다
- 영향 대상: 스토리지 엔진 개발자, 복제 정합성, 장애 복구 담당자

### 문제
RK 전환은 제약/인덱스, 활성 RK 카탈로그, DDL 로그, 복제 체크포인트를 갱신할 수 있다. 디스크 공간 부족이 그 사이 발생했을 때 전부 rollback되는지, commit 후 로그 flush 실패면 노드를 중단하는지 없다.

### 왜 중요한가
메모리에서는 새 RK인데 durable log에는 옛 RK이면 재시작 전후 동작이 달라진다. primary가 성공을 반환한 뒤 replica에 전달할 로그가 없다면 조용한 불일치가 된다.

### 재현 또는 구체적 예제

```text
1. PK(id)에서 UK(email)로 전환 시작
2. 새 인덱스 작성 성공
3. 카탈로그 page 기록 성공
4. DDL WAL flush에서 ENOSPC 발생
5. 프로세스 재시작
```

성공/실패 응답과 재시작 후 활성 RK가 무엇이어야 하는지 정의되지 않았다.

### 권고안
각 영속화 단계의 write-ahead 순서와 commit point를 명시한다. commit 전 실패는 전부 rollback하고, commit 내구성을 보장할 수 없는 primary는 쓰기 성공을 반환하지 말며 승격 가능 상태에서도 제외한다.

### 검증 방법
인덱스 작성, 카탈로그 기록, WAL append/flush, 체크포인트 단계마다 ENOSPC와 I/O 오류를 주입한다. 응답, 재시작 후 카탈로그, 로그 재적용, 승격 가능 여부, 양 노드 데이터가 정의된 상태인지 확인한다.

## [DBDEV-1Y-28] 네트워크 분할 중 복제 정책 DDL을 막을 fencing 기준이 없다

- 분류: 정확성
- 심각도: Blocker
- 근거 위치: 원문 4절의 HA 운영 중 DDL과 7절의 HA 전환 검사
- 사실/추론 구분: 확인이 필요한 질문 — CUBRID HA의 현재 primary fencing·epoch 구현은 확인하지 못했으며 원문에도 조건이 없다
- 영향 대상: HA 제어기 개발자, 엔진 개발자, 복제 정합성

### 문제
네트워크 분할로 두 노드가 자신을 primary라고 판단하는 split-brain 상황에서 서로 다른 RK 변경이 성공하면 로그 세대가 갈라진다. “HA 모드에서 허용”만으로는 쓰기 권한을 가진 단일 epoch를 보장하지 않는다.

### 왜 중요한가
양쪽에서 같은 테이블을 다른 키로 바꾸면 연결 복구 후 단순 로그 재생으로 합칠 수 없다. 어느 DDL이 정당한지 판단할 공통 epoch가 없기 때문이다.

### 재현 또는 구체적 예제

```text
network partition 발생
node A: ALTER t DROP PK, ADD UNIQUE(email)
node B: ALTER t DROP PK, ADD UNIQUE(phone)
A와 B 모두 사용자에게 성공 반환
```

재연결 시 활성 RK와 뒤따른 DML 로그 해석이 충돌한다.

### 권고안
복제 정책/RK DDL은 유효한 primary lease 또는 fencing epoch를 가진 노드에서만 commit하도록 한다. epoch를 DDL 로그와 카탈로그에 넣고 오래된 epoch의 DDL/DML 적용을 거부한다.

### 검증 방법
DDL 직전·commit 중·직후 네트워크를 분리하고 양 노드에 쓰기를 시도한다. 한쪽만 성공하며, 재연결 후 오래된 epoch 로그가 명확히 격리되고 자동 병합되지 않는지 확인한다.

## [DBDEV-1Y-29] 반복 적용 실패를 격리하는 영속 상태가 없다

- 분류: 운영성
- 심각도: Critical
- 근거 위치: 원문 1절의 `fail_count` 증가 문제와 4절의 DDL/DML 복제
- 사실/추론 구분: 문서에서 도출한 추론 — 카운터 증가 방지만으로는 동일 로그가 재시작마다 반복 실패하는 문제를 해결하지 못한다
- 영향 대상: 복제 적용기 개발자, DBA, replica 가용성

### 문제
한 레코드가 RK 불일치로 실패할 때 재시도 횟수, backoff, 격리 위치, 이후 로그 진행 가능 여부와 이 상태의 재시작 보존이 없다. 기존 15번의 카운터 정의와 별개로 적용기 생명주기 계약이 필요하다.

### 왜 중요한가
무한 즉시 재시도는 CPU와 로그를 소모하고 replica lag를 계속 늘린다. 반대로 조용히 건너뛰면 데이터가 달라진다. 메모리에만 실패 상태를 두면 재시작할 때 같은 폭주가 반복된다.

### 재현 또는 구체적 예제

```text
LSN 500: UPDATE, rk=(id=10), 대상 행 없음
applier 재시도 1000회 -> 프로세스 재시작 -> 다시 1000회
LSN 501 이후는 적용 여부 불명
```

오류 한 건이 전체 replica를 멈출지, 격리 후 불건전 상태로 진행할지 정책이 없다.

### 권고안
오류 종류별 재시도 가능 여부와 한도를 정한다. 비재시도 오류는 LSN, 테이블 ID, RK generation, 오류 코드를 durable quarantine에 기록하고 replica를 승격 불가로 표시한다. 임의 skip은 관리자 승인과 감사 기록 없이는 금지한다.

### 검증 방법
행 없음, 일시 I/O 오류, schema generation 없음 오류를 만들어 재시도 횟수와 backoff를 확인한다. 적용기를 재시작해도 격리 상태와 승격 금지가 유지되고 후속 처리 정책이 동일한지 검증한다.

## [DBDEV-1Y-30] 제약 이름과 물리 인덱스 변경이 논리 RK를 바꾸는지 불명확하다

- 분류: 모호성
- 심각도: Major
- 근거 위치: 원문 1절의 엔진 RK 선택과 4-2절의 RK 후보 DDL 규칙
- 사실/추론 구분: 문서에서 도출한 추론 — 사용자 제약, 물리 인덱스, 논리 RK 정체성을 구분하는 규칙이 없다
- 영향 대상: 카탈로그·인덱스 개발자, 복제 적용기, 관리 도구 개발자

### 문제
같은 컬럼과 유일성 의미를 유지한 채 제약 이름만 바꾸거나 인덱스를 rebuild할 때 새 RK generation이 생기는지 알 수 없다. 반대로 이름이 같아도 컬럼·collation이 바뀌면 같은 RK로 취급해서는 안 된다.

### 왜 중요한가
복제 로그가 바뀌기 쉬운 제약 이름이나 물리 index ID를 주소로 쓰면 무해한 유지보수도 schema barrier와 옛 메타데이터 보존을 유발한다. 의미가 바뀐 키를 같은 ID로 재사용하면 더 위험하다.

### 재현 또는 구체적 예제

```sql
-- 실제 rename/rebuild 문법 지원 여부는 확인 필요
ALTER TABLE customer RENAME CONSTRAINT uk_email TO uk_customer_email;
-- 이후 동일 (email) UNIQUE 인덱스를 재구축
UPDATE customer SET name='Kim' WHERE email='a@example.com';
```

논리 키는 계속 `email`이지만 물리 객체 식별자는 바뀔 수 있다. 로그 세대 변경 여부가 정의되지 않았다.

### 권고안
논리 RK ID를 제약 이름과 물리 index ID에서 분리한다. 컬럼의 안정 ID·순서, 타입, collation, NULL/유일성 의미가 같으면 논리 ID를 유지하고, 이 의미가 바뀔 때만 새 generation을 발급하도록 규칙을 명시한다.

### 검증 방법
대상 버전에서 지원되는 rename/rebuild/통계 갱신 절차를 확인한다. 각 작업 전후 논리 RK ID와 generation, 물리 index ID, 생성된 DDL 장벽 수를 조회하고 후속 DML이 같은 행에 적용되는지 확인한다.

# 추가 조사 종료 기록

- 추가 조사 목표: 최대 30개
- 실제 추가 항목 수: 10개
- 최종 리뷰 항목 수: 30개
- 30개를 채우지 않은 경우의 사유: 가치 있는 독립 쟁점을 더 찾지 못했으며, 기존 항목의 반복이나 근거 없는 추측으로 수량을 채우지 않음
- 추가 조사에서 확인하지 못한 영역: 대상 CUBRID 버전의 파티션·온라인 DDL·병렬 apply·PITR·bulk API·제약 rename/rebuild 실제 지원 범위, 현재 권한/감사 체계, HA fencing/epoch 구현, 로그·카탈로그 내부 구조는 소스와 공식 운영 문서를 확인하지 못했다.
