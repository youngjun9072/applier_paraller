# CUBRID HA 복제 키 사용자 스펙 권고 변경안

> **후속 필터링 주의:** 아래 권고는 코드 확인 전 작성한 원안을 보존한 것이다. 실제 기능 구현에 맞는지와 과도한 요구 여부는 [CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md](CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md)의 CF별 판정을 먼저 적용한다.

## 1. 결론

현재 `user_spec.html`은 아이디어 설명 자료로는 유용하지만 구현·시험·사용자 공개의 규범 스펙으로 사용하기에는 부족하다. 특히 RK 교체 중 DDL/DML 순서, 활성 RK의 영속적 식별, ON/OFF 데이터 수명주기, crash/failover 복구, 구버전 load 기본값이 결정되기 전에는 구현을 확정하면 안 된다.

권고안은 문서를 “기능 설명”과 “반드시 지켜야 하는 동작 계약”으로 분리하는 것이다. 아래 `MUST`, `MUST NOT`, `SHOULD` 문장은 제안 규범이며 제품 책임자의 승인 전에는 현재 CUBRID 동작으로 간주하면 안 된다.

### 읽는 법과 현재 확인 범위

- **원문 확인**: 현재 스펙은 PK 우선, PK가 없으면 NOT NULL UK 중 하나를 엔진이 선택, 옵션 생략 시 ON, 모든 DDL 복제, ON 테이블의 데이터만 복제, HA active에서 OFF→ON 금지를 서술한다.
- **구현 미확인**: RK 세대, 논리 ID, old/new key image, barrier, 병렬 apply, PITR, 권한·감사 원자성은 원문으로 실제 구현 여부를 확인할 수 없다.
- **이 문서의 제안**: 아래 상태명, 조회 명령, 오류·권한, 상태 기계와 수용 기준은 승인 전까지 현재 제품 사실이 아니다.
- **지원 범위 확인 필요**: partition, CTAS/LIKE, temporary table, trigger/procedure, identity/sequence 등은 대상 CUBRID 버전의 실제 지원 여부와 문법을 확인한 뒤 `지원`, `미지원`, `해당 없음` 중 하나로 명시해야 한다.

## 2. 우선 수정해야 할 상충과 오류

### 2.1 구버전 unload/load 기본값 통일 — 출시 차단

현재 8절은 replication 정보가 없으면 ON이라고 하고 9절은 OFF라고 한다. 둘 중 하나를 암묵적으로 고르는 대신 다음처럼 바꿀 것을 권고한다.

> load 입력에 REPLICATION 정보가 없으면 도구는 `--missing-replication={on|off|error}` 정책을 요구한다. 무인 실행에서 옵션을 생략했을 때의 제품 기본값은 별도로 승인하고, load 시작 전에 객체별 예상 결과와 무키 ON 테이블 목록을 출력한다. load가 끝나면 실제 ON/OFF, 활성 RK 또는 위반 사유를 결과 보고서에 기록한다.

예:

```text
orders    requested=ON   rk=pk_orders       status=ready
audit_raw requested=ON   rk=<none>          status=ha-blocked
cache     requested=OFF  rk=<not-required>  status=local-only
```

### 2.2 실행 불가능한 SQL과 단순 ERROR 교체

- `CRATE TABLE`을 `CREATE TABLE`로 고친다.
- 예시 2의 후행 쉼표를 제거한다.
- `DROP CONSTRAINT ...`와 제약 이름을 실제 CUBRID 문법으로 완성한다.
- 모든 오류 예제에 실제 제품 오류 코드, SQLSTATE가 있다면 SQLSTATE, 객체·제약 이름, 수정 방법을 넣는다.
- 각 예제는 독립 실행 가능한 `CREATE → INSERT → ALTER → 조회` 순서로 만든다.

### 2.3 모드 용어 통일

`single`, `SA`, `HA 모드`, `cubrid hb start 실행 상태`를 하나의 표로 정의한다.

| 상태 | 서버/프로세스 조건 | 복제 연결 | RK 제약 검사 | 허용 SQL |
|---|---|---|---|---|
| SA | 제품 공식 정의 필요 | 없음 | 규칙 명시 | 규칙 명시 |
| non-HA server | 제품 공식 정의 필요 | 없음 | 규칙 명시 | 규칙 명시 |
| HA starting | 사전 검사 중 | 준비 중 | snapshot 기준 | DDL 차단 여부 명시 |
| HA active | primary/standby 구성 | 활성 | 지속 불변식 | 상태 전이 표 참조 |

## 3. 문서 앞부분에 추가할 핵심 불변식

다음 **제안 요구사항**을 1절 앞에 배치할 것을 권고한다. 제품 책임자가 승인하기 전에는 현재 구현의 보장으로 읽지 않는다.

1. 복제되는 모든 DML 로그는 기록 당시의 테이블과 RK 세대를 영구적으로 식별할 수 있어야 한다.
2. standby는 그 세대에 맞는 키 의미를 사용해야 한다. UPDATE/DELETE 대상 검색에는 생성 당시 old key가 필요하며, RK 값 자체가 바뀌는 UPDATE에는 필요한 new key도 함께 사용해 정확히 한 행을 찾거나 데이터를 변경하지 않고 구조화된 오류로 중단해야 한다.
3. RK 전환 중 어느 durable 상태에서도 “어느 세대인지 모르는 DML”과 “유효한 복구 경로가 없는 카탈로그”가 존재하면 안 된다.
4. 마스터와 모든 승격 가능 standby의 테이블 ID, 활성 RK 논리 ID, RK epoch는 승격 허용 상태에서 일치해야 한다.
5. 복합 DDL은 전부 성공하거나 이전 스키마·RK 상태로 전부 복구되어야 한다.
6. 지원되는 crash, retry, 로그 재적용에서 DML 누락과 잘못된 행 적용은 0건이어야 한다.
7. `REPLICATION=OFF`는 “복제를 잠시 정지”하는 상태가 아니라 해당 테이블 데이터가 노드 로컬일 수 있다는 데이터 보호 정책이다.

## 4. PK·UK·RK 용어와 선택 규칙 개정

### 4.1 서로 다른 개념을 분리

- **RK 후보**: RK 자격을 만족하는 PK 또는 모든 컬럼이 NOT NULL인 UK.
- **활성 RK**: 현재 새 DML 로그를 생성할 때 사용하는 하나의 후보.
- **RK 논리 ID**: 제약 이름이나 물리 인덱스 이름 변경과 독립적인 영속 식별자.
- **RK epoch**: 활성 RK의 직렬화·비교 의미가 바뀔 때 증가하는 세대.
- **RK 전환 상태**: `STABLE`, `PREPARING`, `SWITCHED`, `RETIRING`, `FAILED` 등으로 표현할 수 있는 상태 집합. 이 이름들은 제안 예시이며 현재 제품 상태명이 아니다.

### 4.2 자동 선택을 명확하게 제한

권고 규칙:

1. 테이블 생성 시 PK가 있으면 PK를 선택한다.
2. PK가 없고 후보 UK가 하나이면 그 UK를 선택한다.
3. UK가 여러 개면 결정적인 정렬 기준을 문서화하되, 선택 결과를 카탈로그에 영속화한다.
4. 이후 PK/UK가 추가돼도 활성 RK를 자동 변경하지 않는다.
5. 활성 RK 변경은 원자적 전환 상태 기계를 거치며 조회 가능해야 한다.

이 규칙은 “PK가 있으면 항상 즉시 PK로 돌아간다”는 재선택을 피한다. 자동 재선택은 복제 지연 중 과거 로그의 의미를 조용히 바꿀 수 있기 때문이다.

이 4~5번은 원문의 “PK가 존재한다면 PK가 복제 키”를 **최초 선택 규칙으로 재해석하는 제안**이다. 제품이 이 문장을 지속적인 우선순위로 유지하려면 PK 추가 시 자동 전환을 명시하고, 그 전환에도 6절의 barrier·epoch·복구 규칙을 동일하게 적용해야 한다. 두 정책을 동시에 규범으로 둘 수는 없다.

### 4.3 RK 적합성 표 추가

다음 항목마다 지원/금지/제한과 최대 크기를 명시한다.

- 단일·복합 키와 최대 컬럼 수
- 문자열과 collation
- 숫자·부동소수·날짜/시간대
- LOB, JSON, collection 등 큰/복합 타입
- 생성 컬럼·표현식 인덱스
- 타입 변경, collation 변경, NULL 가능 여부 변경
- RK 값 자체의 UPDATE

## 5. SQL 문법과 조회 기능 개정

### 5.1 REPLICATION은 정책이고 준비 상태는 별도로 조회

`REPLICATION ON`만 보고 실제 복제가 정상이라고 오해하지 않도록 다음 상태를 분리한다.

```text
policy: ON | OFF
readiness: READY | BLOCKED_NO_RK | BUILDING | ERROR
active_rk: logical id + columns
rk_epoch: integer
replica_state: node별 applied epoch/log position
```

### 5.2 구조화된 조회 예시 추가

개념 예시이며 실제 문법은 제품 규칙에 맞춰 확정한다.

```sql
SHOW REPLICATION STATUS FOR TABLE account;
```

```text
policy       ON
readiness    READY
active_rk    rk$104 (id)
rk_epoch     7
transition   STABLE
```

`SHOW CREATE TABLE`과 schema metadata API도 `REPLICATION`을 손실 없이 round-trip해야 한다.

### 5.3 권한 정의

- 조회 권한과 변경 권한을 분리한다.
- `REPLICATION=OFF`처럼 보호 수준을 낮추는 작업은 별도 권한을 요구한다.
- 정책/RK 변경은 요청자, 승인자, 객체, 이전·새 상태, epoch, 결과를 감사 기록에 남긴다.
- 감사 기록과 DDL 커밋의 성공/실패 관계를 원자적으로 정의한다.

## 6. RK 교체 상태 전이 추가

PK A에서 UK B로 바꾸는 권고 흐름은 다음과 같다.

1. **검증**: B가 NOT NULL·UNIQUE이고 지원 타입/크기인지 snapshot 기준으로 확인한다.
2. **준비**: 필요한 인덱스를 구축하고 필요한 WAL·임시 공간을 예약한다.
3. **barrier**: 기존 epoch DML의 커밋·로그 위치와 병렬 apply worker를 정렬한다.
4. **전환**: 새 epoch와 활성 RK 논리 ID를 하나의 durable 카탈로그 커밋으로 공개한다.
5. **전파**: 모든 승격 가능 standby가 전환 상태와 인덱스를 확인한다.
6. **퇴역**: 전역 safe point 이전에는 old RK epoch와 디코딩 정보를 삭제하지 않는다.

각 단계에 취소 가능 여부, crash 후 재개/rollback, failover 가능 여부, 진행률 조회, timeout 결과를 표로 적는다.

예:

| 상태 | 쓰기 | failover | cancel | crash 후 |
|---|---|---|---|---|
| PREPARING | 정책 필요 | old epoch로만 가능 | 가능 | 준비 재개/정리 |
| SWITCHING | barrier 규칙 | 차단 권고 | 불가 | commit record로 판정 |
| SWITCHED | new epoch | 준비된 노드만 | 해당 없음 | new epoch 복구 |
| RETIRING | 허용 | 가능 | 해당 없음 | safe point 재계산 |

## 7. DDL/DML 동시성과 로그 계약 추가

다음 예제를 규범 시험으로 문서에 넣는다.

```sql
CREATE TABLE account (
  id INTEGER PRIMARY KEY,
  email VARCHAR(255) NOT NULL UNIQUE,
  balance NUMERIC(15, 2) NOT NULL
) REPLICATION = ON;
```

이후 다음 순서마다 결과를 정의한다.

1. DML 시작 → RK ALTER 시작 → DML 커밋
2. RK ALTER 시작 → DML 시작 → ALTER 커밋
3. ALTER 로그 전송 후 apply 전 primary crash
4. standby가 오래 지연된 상태에서 old RK 값을 여러 번 UPDATE
5. 같은 로그 record의 중복 전송과 ack 손실

각 경우에 사용자 SQL의 성공/대기/실패, 로그가 가진 epoch와 old/new key, standby apply 결과, `fail_count`/quarantine 변화를 명시한다.

## 8. REPLICATION ON/OFF 데이터 수명주기 개정

### 8.1 상태 전이 표

| 전환 | HA active | 기존 standby 데이터 | 필요한 작업 | 완료 조건 |
|---|---|---|---|---|
| ON→OFF | 허용 여부 승인 필요 | 보존하되 stale 표시 권고 | cutover 위치 기록 | 새 DML 비복제 확인 |
| OFF→ON | 단순 변경 금지 권고 | 신뢰하지 않음 | full sync + delta + checksum | 모든 승격 노드 READY |
| OFF 유지 후 failover | 허용 | 노드 로컬 데이터 | 의존성·위험 표시 | 사용자 강제 승인 여부 |
| ON 유지 | 허용 | 동기화 대상 | 정상 복제 | lag/error 기준 만족 |

### 8.2 혼합 트랜잭션

ON과 OFF 테이블을 한 트랜잭션에서 변경할 때 standby에는 부분 효과만 남는다. 제품은 다음 중 하나를 명시적으로 선택해야 한다.

- 혼합 쓰기 트랜잭션을 거부한다.
- 경고 후 허용하고 failover 원자성이 보장되지 않음을 감사한다.
- OFF 데이터를 별도 메커니즘으로 보상한다.

조용히 허용하는 것은 권고하지 않는다.

## 9. FK, VIEW 및 파생 동작 개정

### 9.1 FK 행렬

부모/자식의 ON/OFF 네 조합과 CREATE, ALTER, ON↔OFF 전환을 표로 작성한다. 대상 버전에서 지원하는 기능에 한해 자기 참조, 다단계 그래프, cross-owner, partition, `CASCADE`, `SET NULL`, `RESTRICT`도 포함한다. 지원하지 않는 조합은 `미지원`으로 명시한다.

### 9.2 내부 DML provenance

대상 버전에서 trigger 또는 stored procedure를 지원하는 경우, trigger, procedure, FK cascade가 생성한 DML이 primary에서 이미 로그로 기록되는지 standby에서 다시 생성되는지를 명시해 중복 적용을 막는다.

### 9.3 VIEW 면책 교체

“책임지지 않는다”를 다음 사용자 기능으로 바꾼다.

- OFF 의존 객체 목록 조회
- failover 전 readiness 경고
- 중요 VIEW를 승격 차단 대상으로 표시하는 선택 기능
- failover 후 예상되는 빈 행/NULL/오류 예시

## 10. HA 시작·failover·재가입 규칙 개정

### 10.1 HA 시작 사전 검사

- 어떤 DB와 노드를 하나의 검사 단위로 보는지 정의한다.
- 검사 snapshot과 동시 DDL 사이 TOCTOU를 barrier로 막는다.
- 모든 위반을 한 번에 구조화된 형식으로 출력한다.
- 부분 시작이 가능하다면 실제 프로세스 상태와 정리 명령을 출력한다.
- 대규모 catalog 검사 비용, timeout, 진행률, 취소를 정의한다.

### 10.2 승격 가능 조건

standby는 최소한 다음 조건을 충족해야 한다.

- 활성 RK 논리 ID와 epoch가 primary의 승인된 durable 상태와 일치
- 해결되지 않은 RK DDL/카탈로그 오류 없음
- apply quarantine 없음 또는 승인된 강제 승격
- 필요한 OFF 의존성 위험이 정책에 따라 확인됨
- lag와 마지막 커밋 내구성이 정의된 RPO 기준 만족

### 10.3 split-brain과 재가입

quorum/fencing을 잃은 노드에서는 복제 정책 DDL을 거부한다. 서로 다른 RK epoch가 커밋된 두 노드를 자동 병합하지 않고, 권위 노드 선택과 재구축을 요구한다.

## 11. 관측성·오류·복구 절차 추가

`fail_count`만 제공하지 말고 다음을 노출한다.

- replica·DB·테이블·RK epoch별 마지막 성공 위치와 시각
- 오류 코드, 첫/마지막 실패, retry 횟수와 다음 시각
- 누락/충돌/디코딩/DDL 상태 불일치 등 오류 종류
- quarantine과 승격 가능 여부
- 값은 기본 마스킹한 진단 식별자
- 정상 상태 SLI: lag, pending records, schema/RK epoch 일치

문서에는 불일치 대응 runbook을 넣는다.

1. 쓰기 범위와 승격을 제한한다.
2. snapshot 기준으로 양 노드 checksum을 계산한다.
3. 영향 테이블·키 범위를 출력한다.
4. 권위 노드와 repair 방향을 승인한다.
5. version check를 포함한 멱등 repair를 실행한다.
6. 재검증하고 quarantine을 해제한다.
7. 모든 변경과 승인자를 감사 기록에 남긴다.

## 12. 백업·PITR·업그레이드 개정

backup/unload manifest에 다음을 함께 저장한다.

- 포맷 버전과 CUBRID 버전
- 테이블별 REPLICATION 정책
- 활성 RK 논리 ID, 구성 컬럼, 타입/collation, epoch
- 진행 중 RK 전환 상태
- 복제 로그 위치와 replica membership epoch
- 암호화된 로그가 있다면 키 ID와 보존 요구사항

PITR은 데이터뿐 아니라 해당 시점의 RK 카탈로그와 과거 로그 해석 정보를 함께 복구해야 한다. 롤링 업그레이드 중에는 모든 승격 가능 노드가 capability를 지원하기 전 새 DDL을 차단한다. 되돌릴 수 없는 카탈로그/log 기록이 생기는 시점을 downgrade horizon으로 표시한다.

## 13. 객체·명령 범위 표 추가

지원 여부를 확인한 뒤 다음 객체와 명령을 빠짐없이 표로 만든다. 지원하지 않는 기능은 `해당 없음`으로 표시하되 침묵하지 않는다.

- partition attach/detach/split/merge
- CTAS, LIKE, clone, rename
- temporary, system, tool-generated table
- TRUNCATE, bulk load, INSERT SELECT
- identity/sequence
- unique constraint와 unique index
- index rebuild/rename, constraint rename, 통계 갱신
- trigger, stored procedure, cascade
- cross-owner FK와 소유권 이전

## 14. 출시 수용 기준

다음 조건을 만족하기 전 공개하지 않을 것을 권고한다.

1. 구버전 load 기본값 상충이 해결됐다.
2. 활성 RK와 epoch를 모든 노드에서 조회할 수 있다.
3. 복합 ALTER의 실패·crash가 이전 상태로 복구된다.
4. DDL/DML 모든 순서 조합에서 누락·오적용 0건이다.
5. RK 전환 각 단계의 failover 시험이 통과한다.
6. duplicate/reordered replay가 멱등하다.
7. ON/OFF 전환과 OFF→ON bootstrap 결과가 checksum으로 검증된다.
8. FK/VIEW/trigger/cascade 의존성 시험이 통과한다.
9. mixed-version, backup/PITR, downgrade 시험이 승인됐다.
10. disk full, OOM, network partition, split-brain 시험에서 안전하게 차단·복구된다.
11. 권한과 감사 이벤트가 DDL 결과와 일치한다.
12. 오류 코드, 관리 API, runbook과 실행 가능한 사용자 예제가 제공된다.

## 15. 권장 문서 구조

1. 문제와 비목표
2. 용어 및 핵심 불변식
3. 지원 객체·타입·명령 범위
4. REPLICATION 정책과 데이터 수명주기
5. RK 후보·선택·조회·전환 상태
6. SQL 문법과 권한
7. 모드별 허용 상태표
8. DDL/DML 동시성 및 로그 순서
9. FK·VIEW·trigger·partition 상호작용
10. HA 시작·failover·failback·재가입
11. 오류·관측·불일치 repair
12. backup/unload/load/PITR
13. 업그레이드·혼합 버전·downgrade
14. 성능 한계와 용량 계획
15. 완전 실행 가능한 예제와 오류 코드
16. 규범 테스트 및 출시 수용 기준

이 구조를 사용하면 “사용자에게 보이는 동작”, “엔진이 지켜야 할 불변식”, “운영자가 확인하고 복구하는 방법”이 한 문서에서 서로 추적 가능해진다.

## 16. 주요 권고와 원시 리뷰 역참조

아래 ID는 `reports/raw/`에 실제 존재하는 원시 항목이다. 표는 모든 691건을 열거하는 목록이 아니라 주요 권고의 대표 근거다.

| 권고 절 | 대표 원시 리뷰 ID |
|---|---|
| 2. unload/load 상충과 실행 예제 | `PM-10Y-17`, `USER-1Y-17`, `DBDEV-1Y-19` |
| 3. RK 세대별 행 식별 불변식 | `PM-10Y-01`, `DBDEV-5Y-01`, `엔진개발자-10년차-01` |
| 4. 후보·활성 RK·타입 적합성 | `PM-10Y-04`, `USER-3Y-27`, `DBDEV-5Y-12` |
| 5. 조회·권한·감사 | `DBA-5Y-21`, `DBA-5Y-34`, `DBDEV-5Y-31` |
| 6~7. 전환 상태와 DDL/DML 순서 | `DBA-5Y-08`, `DBA-5Y-09`, `DBDEV-5Y-09` |
| 8. ON/OFF 생명주기와 혼합 트랜잭션 | `PM-5Y-37`, `DBA-10년차-06`, `DBDEV-5Y-25` |
| 9. FK·VIEW·파생 DML | `PM-10Y-14`, `DBDEV-5Y-13`, `엔진개발자-10년차-14` |
| 10. HA 시작·승격·split-brain | `PM-10Y-10`, `DBA-5Y-30`, `엔진개발자-10년차-11` |
| 11. 관측·불일치 repair | `DBA-10년차-15`, `DBA-10년차-16`, `엔진개발자-10년차-16` |
| 12. backup/PITR·혼합 버전 | `DBA-10년차-17`, `DBA-10년차-18`, `엔진개발자-10년차-18` |
| 13. 확장 객체·명령 범위 | `DBA-10년차-23`, `DBDEV-5Y-24`, `엔진개발자-10년차-22` |
| 14. 출시 수용 기준 | `PM-10Y-01`, `DBDEV-5Y-20`, `엔진개발자-10년차-34` |
