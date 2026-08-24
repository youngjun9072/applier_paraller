# CUBRID HA 복제 키 확장 — 코드 비참조 컨셉 유효성 리뷰

> 이 문서는 기능 코드를 보지 않고 스펙 자체가 완전하고 일관된 제품 계약인지 검토한 결과다. 현재 구현이 어떤 문제를 이미 처리하는지는 판정 기준으로 사용하지 않았다. 따라서 이 문서의 쟁점이 코드에 구현되어 있더라도 쟁점이 잘못 제기된 것은 아니며, 그 구현이 아래 계약과 수용 기준을 충족하는지는 별도의 코드 대조 문서인 [CUBRID_FIT_FILTER_FEATURE.md](CUBRID_FIT_FILTER_FEATURE.md)에서 확인해야 한다.

- 검토 대상: CUBRID HA의 Replication Key(RK)와 테이블별 `REPLICATION=ON|OFF` 도입 스펙
- 입력: 원 스펙 전체와 20개 역할·연차별 raw 리뷰 691건
- 통합 방식: 표현이 아니라 같은 실패 원인과 필요한 결정이 같은 의견을 하나로 묶었다.
- 결과: 691건을 누락·중복 없이 30개 컨셉 쟁점으로 통합했다. 30개는 “원래 의견이 30개뿐”이라는 뜻이 아니다.
- 문서 목적: 이 파일만 읽어도 기능의 목적, 사용자에게 보이는 동작, 쟁점의 이유와 필요한 결정을 이해하게 하는 것

## 1. 이 피처가 하려는 일

기존 CUBRID HA는 복제 대상 행을 찾는 데 Primary Key(PK)를 사용한다. HA 운영 중 PK 또는 PK 컬럼의 속성이 바뀌면, 변경 전에 만들어진 로그와 변경 후 스키마가 서로 다른 방식으로 행을 식별할 수 있다. 그 결과 standby에서 행을 찾지 못해 `applylogdb` 오류와 `fail_count` 증가가 발생하거나, 더 나쁘게는 master와 standby의 데이터가 조용히 달라질 수 있다.

제안 피처는 이 문제를 다음 두 개념으로 풀려고 한다.

1. **Replication Key(RK)**: 복제기가 UPDATE/DELETE 대상 행을 찾는 논리적 키다. PK가 있으면 PK를 사용하고, PK가 없으면 `NOT NULL UNIQUE` 제약 중 하나를 엔진이 선택한다. 따라서 PK를 바꾸더라도 다른 유효 후보가 있으면 복제를 유지할 수 있게 한다.
2. **테이블별 복제 정책**: `CREATE TABLE`과 `ALTER TABLE`에 `REPLICATION=ON|OFF`를 추가한다. ON 테이블의 DML은 복제하고 OFF 테이블의 DML은 복제하지 않는다. DDL은 ON/OFF와 무관하게 복제한다.

스펙이 의도한 사용자 흐름은 다음과 같다.

- 옵션을 생략한 테이블은 기본적으로 ON이다.
- single mode에서는 ON이면서 RK가 없는 테이블도 만들 수 있으나, HA로 전환하기 전에 RK를 추가하거나 OFF로 바꿔야 한다.
- HA mode에서는 ON 테이블에 항상 한 개 이상의 RK 후보가 있어야 한다.
- 현재 유일한 RK를 없애는 DDL은 거부한다. 한 SQL 안에서 기존 키를 제거하고 새 키를 추가하는 복합 ALTER는 허용하려 한다.
- ON 테이블의 FK가 OFF 테이블을 참조하면 failover 뒤 참조 데이터가 사라질 수 있으므로 이를 제한하려 한다.
- HA 시작 시 RK 누락과 잘못된 FK 관계를 검사하고, 문제가 있는 객체를 알려 주려 한다.
- unload/load와 `SHOW CREATE TABLE`, catalog 조회에서도 복제 정책을 보존·노출하려 한다.

방향 자체는 타당하다. PK 변경 때문에 복제 행 식별자가 사라지는 문제를 “항상 유효한 대체 키를 둔다”는 방식으로 줄이고, 복제할 수 없는 테이블을 명시적으로 제외하는 것은 기존의 암묵적 실패보다 낫다. 다만 현재 스펙은 **현재 시점에 후보 키가 존재하는가**를 주로 설명할 뿐, 로그 생성부터 DDL, 장애, 복구, 승격까지 시간에 따라 RK의 의미가 어떻게 유지되는지를 충분히 정의하지 않는다. 또한 OFF는 단순한 성능 옵션이 아니라 failover 시 데이터가 사라질 수 있는 데이터 생명주기 정책인데, 그 책임 경계가 약하다.

## 2. 이 문서의 판정 원칙

- **컨셉 유효**: 특정 코드 구현과 무관하게 제품 계약에 반드시 답이 필요한 문제다.
- **컨셉 유효, 정책 선택 필요**: 문제는 실제지만 유일한 정답은 없다. 지원·금지·경고·자동화 중 제품이 하나를 선택해 명시해야 한다.
- **범위 조건부 유효**: partition, CDC 같은 기능이 실제 지원 범위에 포함될 때만 필수다. 제외한다면 “지원하지 않는다”는 명시와 사전 차단이 답이 된다.
- 심각도는 구현 난도가 아니라 계약 부재가 데이터 오적용·복구 불능·운영 중단으로 이어질 가능성을 뜻한다.
- “기능 코드가 이미 처리한다”는 컨셉 기각 사유가 아니다. 그것은 구현 상태에 대한 답이며, 이 문서에서는 스펙에 그 보장이 적혀 있고 시험 가능한지만 본다.

## 3. 먼저 확정해야 할 핵심 불변식

30개 쟁점은 결국 다음 다섯 문장으로 수렴한다.

1. ON 테이블에서 생성된 모든 미적용 DML은 **로그 생성 당시의 RK 의미**로 정확히 한 행을 찾아야 한다.
2. RK 교체는 old 또는 new 상태 중 하나로만 관찰되어야 하며, crash 뒤에도 중간 상태가 남아서는 안 된다.
3. 승격 가능한 노드는 필요한 schema epoch와 commit LSN을 모두 적용했고 데이터가 일치해야 한다.
4. OFF로 제외된 데이터는 자동으로 되살아나거나 병합된다고 가정하지 않으며, ON 재편입에는 명시적 동기화와 검증이 필요하다.
5. 지원하지 않는 상태·객체·경로는 손상을 만든 뒤 실패하는 대신 실행 또는 HA 진입 전에 거부되어야 한다.

이 다섯 문장이 스펙의 규범 문장과 자동화된 시험으로 연결되지 않으면, 개별 SQL 예제만 늘려도 기능의 안전성을 증명할 수 없다.

---

## 4. 691개 raw 의견의 주제별 종합

### CF-01. 로그가 어느 RK 세대의 것인지 식별할 수 있어야 한다

- 심각도: **Blocker**
- 종합한 raw: 26건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 엔진 개발자는 “현재 RK가 존재한다”는 catalog 검사만으로 과거 로그를 해석할 수 없다고 지적했다. DBA는 standby 지연·재시작·backup 복원 뒤에도 이전 키 정의가 필요하다고 보았고, 애플리케이션 개발자와 사용자는 성공한 UPDATE가 failover 뒤 사라지거나 다른 행에 적용되는 상황을 우려했다. PM 관점에서는 후보 키 보유가 아니라 “모든 미적용 변경이 생성 당시 의미로 정확히 한 행을 찾는다”가 기능의 실제 안전 약속이어야 한다는 결론이 나온다.

예를 들어 RK가 `id`일 때 생성된 UPDATE 로그가 아직 standby에 남아 있는데 primary가 RK를 `email`로 바꾸면, 적용기는 로그 안의 값을 어느 인덱스로 찾아야 하는지 알아야 한다. 현재 catalog만 보면 `email`로 찾다가 행을 놓치거나 우연히 다른 행을 찾을 수 있다. 따라서 table의 안정 ID, 논리 RK ID, 단조 증가 generation/epoch, old key 값과 schema barrier가 로그 또는 그와 동등한 영속 정보로 연결되어야 한다. 이전 세대 metadata는 모든 replica와 PITR 보존 구간이 지난 뒤에만 폐기할 수 있다.

**스펙이 결정할 것:** epoch 발급 시점, DML에 기록할 identity 정보, 이전 generation 보존 기간, 누락된 generation을 만났을 때의 격리·중단 동작.

**수용 기준:** old RK DML을 지연시킨 상태에서 RK 교체, 새 DML, crash/restart, backup 복원을 조합해도 각 변경이 정확히 한 행에 한 번만 적용되고 source/standby checksum이 같아야 한다.

### CF-02. 여러 후보 중 RK 선택은 결정적이고 영속적이어야 한다

- 심각도: **Critical**
- 종합한 raw: 46건
- 판정: **컨셉 유효, 정책 선택 필요**

**raw 의견의 종합:** 초급 사용자와 앱 개발자는 “엔진이 하나를 선택한다”만으로 현재 어떤 키가 쓰이는지 예측할 수 없다고 지적했다. DBA는 dump/load, constraint rename, restore 후 선택이 달라질 위험을 들었고, 엔진 개발자는 catalog scan 순서 같은 구현 세부가 영구 로그 호환 계약이 되어서는 안 된다고 보았다. PM 의견은 자동 선택의 편의와 운영 예측 가능성을 함께 제공하려면 선택 결과를 조회하고 고정할 방법이 필요하다는 쪽으로 모인다.

`UNIQUE(email)`과 `UNIQUE(account_no)`가 있을 때 선언 순서, constraint 이름, 물리 index ID, catalog 저장 순서 중 무엇이 우선인지 명시되지 않으면 노드·버전·복원 경로에 따라 선택이 달라질 수 있다. 권장 컨셉은 생성 시 결정적 규칙으로 한 번 선택한 뒤 stable logical ID로 영속하고, 사용자가 명시적으로 변경하지 않는 한 재계산하지 않는 것이다. 사용자 지정 RK를 지원하지 않겠다면 그 결정도 가능하지만, 현재 선택·후보·선택 이유와 다음 DDL 후 예상 결과는 조회 가능해야 한다.

**스펙이 결정할 것:** PK 우선 이후 UK 정렬 규칙, 선택 결과의 영속 여부, 사용자 명시 지정 지원 여부, rename/rebuild/restore/upgrade 때 동일성 규칙, 현재와 후보를 보여 주는 metadata API.

**수용 기준:** constraint 생성 순서·이름·catalog layout·restart·dump/load·upgrade를 바꿔도 의미상 같은 스키마는 같은 logical RK를 선택해야 하며, 바뀐다면 명시적 세대 전환으로 관찰되어야 한다.

### CF-03. `REPLICATION=OFF`는 데이터 생명주기 정책으로 정의해야 한다

- 심각도: **Critical**
- 종합한 raw: 27건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 사용자는 OFF를 단순히 “복제하지 않음”으로 이해하기 쉽지만, 앱 개발자는 failover 뒤 그 테이블 데이터가 없거나 오래된 상태에서 서비스되는 의미를 물었다. DBA는 어느 노드가 권위 사본인지, failback과 재가입 때 무엇을 버릴지, OFF→ON 때 어떻게 초기 동기화할지를 요구했다. PM과 엔진 관점에서는 OFF 기간의 서로 다른 로컬 쓰기는 일반적으로 자동 병합할 수 없으므로 전환 경계와 금지 상태가 제품 계약이어야 한다.

예를 들어 primary A에서 `orders`를 OFF로 바꾸고 100행을 쓴 뒤 B로 failover하면, B에는 DDL만 있고 그 100행은 없을 수 있다. 이후 A가 돌아왔을 때 A 데이터를 다시 사용하면 B에서 생긴 변경과 충돌하고, B를 권위로 삼으면 A의 100행은 버려진다. “OFF로 인한 불일치는 책임지지 않는다”는 문구만으로는 어떤 동작이 안전한지 알 수 없다. OFF 전환의 cutover LSN, 데이터 귀속, 승격 시 처리, 재가입, 폐기, OFF→ON의 full copy/resync 절차를 정의해야 한다.

**스펙이 결정할 것:** OFF 데이터가 node-local인지, failover 후 접근 가능성, OFF 전환 이전 데이터 처리, ON 재편입 허용 조건, 승인·검증·rollback 절차.

**수용 기준:** 명시적 resync 없이 OFF→ON 또는 불완전 사본의 승격이 되지 않아야 하며, 운영자는 전환 LSN과 어느 사본이 권위인지 확인할 수 있어야 한다.

### CF-04. 기본 ON과 single→HA readiness는 하나의 원자적 검사여야 한다

- 심각도: **Critical**
- 종합한 raw: 39건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자와 사용자는 single mode에서 정상 배포된 무키 테이블 때문에 훗날 HA 시작이 실패하는 늦은 오류를 문제로 보았다. DBA는 오류가 DB 전체·노드·클러스터 중 무엇을 막는지와 수정 목록을 요구했고, 엔진 개발자는 검사 도중 DDL이 바뀌면 통과 직후 위반 상태가 될 수 있다고 지적했다. PM 의견은 기본 ON이 안전한 기본값인지, 기존 사용자에게 지나치게 큰 마이그레이션 부담인지 측정해야 한다는 문제까지 포함한다.

스펙에는 모드별로 CREATE/ALTER/HA start가 어떤 상태를 허용하는지 완전한 행렬이 필요하다. HA start 검사는 catalog의 한 epoch를 기준으로 모든 ON 테이블의 RK와 FK 의존성을 검사하고, 성공한 epoch가 runtime admission과 연결되어야 한다. 검사 이후 같은 객체를 깨는 DDL이 동시에 commit할 수 있다면 검사는 의미가 없다. 또한 위반 하나만 출력하고 반복 실행하게 하지 말고 전체 객체, 위반 이유, 가능한 수정 방법을 구조화된 형식으로 제공해야 한다.

**스펙이 결정할 것:** 기본값의 적용 대상(신규 SQL·legacy catalog·dump 각각), HA 시작 차단 범위, 검사 snapshot과 동시 DDL 잠금, 경고만 가능한 상태.

**수용 기준:** 동시 DDL 중에도 단일 catalog 시점으로 판정하고, 위반이 남은 부분 시작은 없으며, 한 번의 검사로 모든 위반과 수정 경로를 알 수 있어야 한다.

### CF-05. SQL 문법과 metadata 왕복 계약이 필요하다

- 심각도: **Major**
- 종합한 raw: 13건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 사용자는 옵션을 어디에 쓰고 어떤 오류가 나는지, 앱 개발자는 schema migration 도구가 상태를 보존하는지, DBA는 `SHOW CREATE TABLE`과 unload/load가 같은 정책을 재생하는지 물었다. 엔진 개발자는 parser 기본값, catalog 표현, printer 출력이 따로 정의되면 서로 drift한다고 지적했다.

현재 예제만으로는 옵션 위치, 대소문자, 중복 지정, `ON`/`OFF` 외 값, 생략, ALTER 반복 실행, 임시·상속·partition table 문법을 판단하기 어렵다. 스펙에는 BNF 또는 동등한 grammar, 금지 예, locale과 무관한 오류 코드, catalog column의 타입과 null 의미, canonical `SHOW CREATE TABLE` 출력이 있어야 한다. 특히 parse→print→parse와 dump→load 뒤 정책 및 RK metadata가 보존되어야 한다.

**스펙이 결정할 것:** 정규 문법, 생략과 NULL의 의미, 중복 옵션 처리, canonical 출력, 공개 catalog/API의 안정성.

**수용 기준:** 지원되는 모든 생성·변경 형태에서 SQL과 metadata를 왕복한 결과가 원래 policy와 logical RK를 그대로 보존해야 하고, 잘못된 입력은 안정 오류 코드로 실행 전에 거부되어야 한다.

### CF-06. RK 교체는 원자적이고 crash-safe한 상태 전이여야 한다

- 심각도: **Blocker**
- 종합한 raw: 51건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자는 한 문장의 복합 ALTER가 진짜 전부 성공하거나 전부 실패하는지 물었다. DBA는 대형 index build의 취소·재개와 disk full을, 엔진 개발자는 constraint/catalog/index/WAL이 각각 갱신되는 중간 crash와 redo/undo를 집중적으로 지적했다. PM·사용자 의견도 “OK”가 반환되면 HA 전체에서 어느 상태가 보장되는지가 필요하다는 데 모였다.

PK 제거와 새 UK 추가는 parser 수준에서 한 문장이어도 내부적으로 검증, index build, catalog publish, WAL flush, replica 적용, old metadata 정리의 긴 과정이다. 중간 실패 뒤 후보 0개, catalog는 new인데 index는 old, source만 new 같은 상태가 남아서는 안 된다. `prepare → build → validate → publish → commit → cleanup` 같은 상태 모델과 각 단계의 lock, cancel, retry, redo/undo 의미가 필요하다. 새 키가 준비되기 전에 old 키를 해제해서도 안 된다.

**스펙이 결정할 것:** 사용자에게 보이는 commit 지점, online/offline 여부, 단계별 durable state, cancel/resume, replica에서의 동일한 atomicity, 실패 후 자동·수동 복구.

**수용 기준:** 모든 단계에 crash·OOM·ENOSPC를 주입한 뒤 재시작해도 전부 old 또는 전부 new 상태만 남고, 유효 RK가 끊기는 순간이 없어야 한다.

### CF-07. RK DDL과 동시 DML·장기 transaction의 직렬화 규칙이 필요하다

- 심각도: **Blocker**
- 종합한 raw: 26건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 애플리케이션 개발자는 migration 중 기존 connection과 transaction이 계속 쓰면 어떤 키로 로그가 만들어지는지 물었다. DBA는 장기 transaction 때문에 DDL이 무기한 대기하거나 서비스가 멈추는 문제를, 엔진 개발자는 schema epoch pinning, worker drain, metadata GC 조건을 제기했다. 사용자는 timeout 뒤 DDL을 다시 실행해도 안전한지 알아야 한다고 보았다.

old RK를 본 transaction T1이 열린 상태에서 새 RK DDL T2가 commit하고, new RK를 본 T3가 쓰면 로그 순서와 schema 의미가 섞일 수 있다. 안전한 설계는 이 세 작업이 모든 노드에서 하나의 직렬 순서로 귀결되도록 해야 한다. 이를 위해 schema epoch lock 또는 MVCC 규칙, DDL admission, 기존 transaction drain, timeout·cancel·resume, old epoch 보존 상한을 정해야 한다. 단순히 “후보가 하나 이상이면 DDL 허용”만으로는 이 시간축 문제를 해결하지 못한다.

**스펙이 결정할 것:** DDL이 기다리는지 DML을 막는지, 기존 transaction의 epoch, 장기 transaction timeout, 온라인 index build 중 변경 포착, 중단 후 재개 의미.

**수용 기준:** old transaction·RK 교체·new transaction을 임의 순서와 지연으로 실행해도 모든 노드의 최종 상태가 허용된 하나의 직렬 실행과 같아야 한다.

### CF-08. 승격 조건은 RK epoch와 data LSN을 함께 보장해야 한다

- 심각도: **Blocker**
- 종합한 raw: 35건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 사용자는 DDL 성공 직후 장애가 나도 새 schema와 직전 쓰기가 남는지 물었다. 앱 개발자는 client가 받은 commit 성공의 의미와 재시도 기준을, DBA는 승격 전 readiness와 RPO를 요구했다. 엔진 개발자는 standby의 schema epoch만 최신이거나 data LSN만 최신인 반쪽 상태를 막는 promotion gate와 stale client fencing을 지적했다.

예를 들어 source가 RK 변경 DDL의 성공을 반환했지만 standby는 그 직전 LSN까지만 적용한 상태에서 source가 죽을 수 있다. standby가 old schema로 승격되면 이후 로그 해석이 틀리고, schema만 적용했지만 DML이 덜 왔다면 성공한 쓰기가 사라진다. 승격 조건은 “프로세스가 살아 있음”이 아니라 필요한 RK epoch, applied/committed LSN, apply health, 미해결 quarantine가 모두 기준을 만족하는지로 정의해야 한다. old primary와 client의 쓰기는 새 writer epoch/fencing token으로 차단해야 한다.

**스펙이 결정할 것:** sync/async별 commit RPO, promotion target LSN·epoch, 자동 승격 금지 조건, 강제 승격 시 데이터 손실 표시, client 재연결·재시도 계약.

**수용 기준:** DDL과 DML의 모든 commit 경계에서 장애를 주입했을 때 불완전 노드는 자동 승격되지 않고, 승인된 노드는 약속한 RPO 범위와 schema/data checksum을 만족해야 한다.

### CF-09. RK 값의 비교·인코딩과 RK 자체 UPDATE 의미를 정해야 한다

- 심각도: **Critical**
- 종합한 raw: 33건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자와 사용자는 email 같은 자연키를 바꾸는 UPDATE가 가능한지, 복합키의 일부만 바뀌면 어떤 값을 쓰는지 물었다. DBA는 collation·timezone·locale 변경을, 엔진 개발자는 canonical byte encoding, NULL·길이·지원 타입과 before/after image를 지적했다. 성능 의견은 넓은 문자열 키가 로그와 lookup 비용을 키운다는 점까지 연결된다.

RK가 UPDATE되는 행을 새 값으로 찾으면 아직 새 값이 존재하지 않으므로 old 행을 못 찾는다. 따라서 적용 대상을 찾는 before-key와 적용 후의 after-key를 구분해야 한다. 복합 RK의 컬럼 순서, 문자열 collation, numeric normalization, timezone, precision, 최대 byte 크기, 허용하지 않는 타입이 source와 standby에서 동일한 비교 결과를 만들어야 한다. collation 자체를 바꾸는 DDL은 RK generation 변경으로 취급할지 금지할지도 필요하다.

**스펙이 결정할 것:** 후보 가능 타입, NULL·부분 index·함수 index 허용 여부, canonical encoding, 최대 크기, before/after image, collation/type 변경 절차.

**수용 기준:** locale·경계값·복합키 일부 변경·타입 변환·RK 자체 UPDATE를 조합해도 source와 standby가 같은 한 행을 선택하고 같은 최종 값을 가져야 한다.

### CF-10. FK·trigger·cascade와 ON/OFF 혼합 transaction의 의미를 정해야 한다

- 심각도: **Critical**
- 종합한 raw: 34건
- 판정: **컨셉 유효, 정책 선택 필요**

**raw 의견의 종합:** 앱 개발자는 한 transaction이 ON과 OFF를 함께 쓰거나 trigger가 다른 테이블을 쓰는 경우 원래 업무 원자성이 유지되는지 물었다. DBA와 사용자는 FK의 네 조합(ON→ON, ON→OFF, OFF→ON, OFF→OFF)과 cascade 결과를 요구했다. 엔진 개발자는 source에서 실행된 파생 DML을 로그로 보내는지, standby에서 trigger를 다시 실행하는지에 따라 중복 또는 누락이 생긴다고 지적했다.

`orders(ON)` INSERT가 trigger로 `audit(OFF)`와 `stock(ON)`을 갱신하면 source의 한 commit 중 무엇이 standby에 나타나는지 명확해야 한다. row change를 모두 기록하면서 standby에서 trigger도 실행하면 두 번 반영될 수 있고, 원문 SQL만 재생하면서 OFF 데이터를 참조하면 다른 결과가 날 수 있다. ON/OFF 혼합 transaction은 의도적으로 replica 관점의 atomicity를 깨므로 지원, 금지, 경고 또는 strict mode 중 정책 선택이 필요하다. FK 방향만 검사해서는 trigger·procedure·cascade·deferred constraint를 포괄하지 못한다.

**스펙이 결정할 것:** 파생 DML provenance, trigger 재실행 여부, 혼합 transaction 정책, FK 네 조합과 cascade, rollback과 retry의 exactly-once 의미.

**수용 기준:** 중첩 trigger·cascade·rollback·retry를 포함한 허용 transaction이 standby에 계약대로 정확히 한 번 반영되고, 허용하지 않는 조합은 commit 전에 명확히 거부되어야 한다.

### CF-11. OFF 데이터에 의존하는 VIEW와 파생 객체의 위험을 노출해야 한다

- 심각도: **Major**
- 종합한 raw: 17건
- 판정: **컨셉 유효, 정책 선택 필요**

**raw 의견의 종합:** 사용자는 query가 오류 없이 다른 결과를 반환하는 것이 단순한 “책임지지 않음”보다 위험하다고 보았다. 앱 개발자는 ON/OFF join, materialized 결과와 procedure를, DBA는 failover 전에 영향 객체를 찾는 방법과 승격 차단을 요구했다. 엔진 개발자는 직접 의존성뿐 아니라 다단계 view와 동적 SQL을 어디까지 추적할지 경계를 정해야 한다고 지적했다.

ON `orders`와 OFF `customers`를 join한 view는 primary에서는 정상 결과를 내지만 failover 뒤 0건 또는 다른 집계를 정상 응답으로 돌려줄 수 있다. 이는 명백한 오류보다 탐지하기 어렵다. 모든 결과를 동일하게 만들 수 없다면 catalog 의존 그래프로 영향 객체를 보여 주고, 중요 객체는 OFF 전환 또는 승격을 막는 strict 정책을 제공해야 한다. 추적할 수 없는 동적 의존성은 그 한계와 사용자 점검 책임을 명시해야 한다.

**스펙이 결정할 것:** 검사할 객체 종류, 직접·간접 의존성 범위, 경고/금지 수준, runtime 표시, 동적 SQL과 외부 프로그램의 책임 경계.

**수용 기준:** 직접 및 다단계 의존 객체가 사전 진단에 나타나고, failover 뒤 결과 차이 가능성과 영향을 받은 원본 OFF 테이블을 사용자가 추적할 수 있어야 한다.

### CF-12. `fail_count`가 아니라 복제 정상성을 설명하는 상태 모델이 필요하다

- 심각도: **Major**
- 종합한 raw: 26건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 초급 사용자는 `fail_count=0`이면 정상인지 묻고, 앱 개발자는 자동화가 어떤 오류를 재시도할지 알아야 한다고 보았다. DBA는 lag, last success, 실패 table/LSN, quarantine와 재시작 후 진단 보존을 요구했다. 엔진 개발자는 configured policy, HA eligibility, selected RK, runtime apply state가 서로 다른 축인데 한 상태처럼 취급되고 있다고 지적했다.

applier가 한 시간 멈춰 있으면 오류가 한 번도 발생하지 않아 `fail_count=0`일 수 있지만 정상 replica가 아니다. 반대로 일시 오류가 해결되어 현재 정상이어도 누적 count는 남을 수 있다. policy(ON/OFF), eligibility(VALID/NO_RK/FK 위반), selected RK/epoch, runtime state(APPLYING/LAGGING/QUARANTINED), applied LSN, last success, 안정 오류 코드를 분리해야 한다. metric label에는 고카디널리티 키 값을 넣지 않아야 한다.

**스펙이 결정할 것:** 상태와 전이, count 증가·초기화 단위, transient/permanent 분류, 격리 해제 권한, CLI/API/metric의 공통 필드.

**수용 기준:** 정상·지연·중지·재시도·영구 실패를 공개 API만으로 구별할 수 있고, 재시작·failover 뒤에도 원인과 영향 LSN/table을 잃지 않아야 한다.

### CF-13. 피처 도입 전 데이터 불일치를 탐지하고 수리하는 절차가 필요하다

- 심각도: **Critical**
- 종합한 raw: 21건
- 판정: **컨셉 유효**

**raw 의견의 종합:** DBA는 새 규칙이 과거 복제 누락을 자동으로 고치지 않는다고 지적했다. 사용자는 RK readiness 검사를 통과했다는 사실을 데이터 일치 보장으로 오해할 수 있고, 엔진 개발자는 catalog 일치와 row 일치를 별도 검증해야 한다고 보았다. PM 의견은 기존 고객이 기능을 켜기 전에 필요한 migration 단계와 실패 시 지원 경로가 제품 범위에 포함되어야 한다는 것이다.

source에만 `id=10` 행이 남아 있어도 양쪽 catalog에 유효 RK가 있으면 정적 검사는 통과한다. 그 standby를 승격하면 과거 결함이 새로운 정상 데이터가 된다. 도입 전 또는 재가입 전에 schema/RK epoch 비교, row count와 chunk checksum, 누락·추가·값 차이 분류, 권위 사본 선택, idempotent repair, 최종 검증이 필요하다. 자동 덮어쓰기는 정상적인 node-local OFF 데이터까지 훼손할 수 있으므로 승인 경계가 중요하다.

**스펙이 결정할 것:** 검증 범위와 비용, online 검사 허용 여부, 차이의 권위 결정, 자동/수동 수리, 쓰기 차단과 재가입 조건.

**수용 기준:** 누락·추가·상이한 값·catalog 손상을 구분해 찾고, 승인 없이 데이터를 덮지 않으며, 수리 후 schema와 data checksum이 일치해야 한다.

### CF-14. unload/load의 기본값·버전·부분 실패 계약을 하나로 통일해야 한다

- 심각도: **Critical**
- 종합한 raw: 16건
- 판정: **컨셉 유효이며 스펙 내부 모순 확인**

**raw 의견의 종합:** 여러 역할이 원 스펙 8절의 “옵션이 없으면 ON”과 9절 요약의 “옵션이 없는 기존 테이블은 OFF”를 직접적인 모순으로 확인했다. 사용자는 어느 결과가 안전한지 예측할 수 없고, DBA는 100개 중 51번째 table에서 load가 실패한 뒤 재실행할 때 중복·부분 정책이 남는 문제를 제기했다. 엔진 개발자는 legacy dump의 필드 부재와 신규 SQL 옵션 생략을 같은 NULL로 처리하지 말아야 한다고 보았다.

신규 CREATE, legacy catalog open, legacy dump load, 신버전 dump load는 출처가 다르므로 각각 versioned migration 규칙이 필요하다. dump manifest에 format version, table policy, RK logical metadata와 지원 capability를 기록하고, 실제 쓰기 전에 전체 preflight를 수행해야 한다. load가 부분 진행된다면 객체별 idempotent checkpoint와 재개·rollback 의미가 있어야 한다.

**스펙이 결정할 것:** 모순된 기본값의 단일 결론, legacy 입력의 정책, manifest와 version, preflight 범위, 부분 실패 시 atomicity와 재개.

**수용 기준:** 신·구 dump를 반복 load해도 동일한 schema/policy/RK 결과가 나오고, 의미를 결정할 수 없는 입력은 객체를 쓰기 전에 명확히 거부해야 한다.

### CF-15. backup·snapshot·PITR은 데이터와 RK 세대를 같은 시점으로 보존해야 한다

- 심각도: **Critical**
- 종합한 raw: 15건
- 판정: **컨셉 유효**

**raw 의견의 종합:** DBA는 backup page, catalog, archive log가 서로 다른 시점이면 복원 후 RK 의미를 잃는다고 지적했다. 엔진 개발자는 old generation metadata의 보존 horizon이 replica 지연뿐 아니라 backup/PITR 보존 기간에도 묶여야 한다고 보았다. 사용자와 PM은 “복원 성공”이 DB open 성공인지 목표 시점의 데이터 정합성인지 구별해야 한다고 요구했다.

00시에 RK=`id`인 backup을 만들고 01시에 RK=`email`로 바꾼 뒤 01:30으로 PITR하려면, backup의 old catalog와 이후 DDL/DML 로그, 두 RK generation을 모두 해석할 수 있어야 한다. page는 old인데 catalog만 new이거나 필요한 epoch metadata가 GC되면 로그가 있어도 복구할 수 없다. backup manifest에 format, base LSN, schema/RK epoch 범위, 필요한 archive 구간을 기록해야 한다.

**스펙이 결정할 것:** consistent snapshot 경계, epoch metadata 보존 horizon, 증분 backup 관계, 복원 preflight, 지원되지 않는 목표 시점의 오류.

**수용 기준:** 여러 RK 전환 전·중·후 목표 시점으로 복구했을 때 예상 checksum이 나오며, 필수 log/epoch가 없으면 복구를 시작하기 전에 실패해야 한다.

### CF-16. 혼합 버전과 기능 활성화에는 capability handshake와 downgrade fence가 필요하다

- 심각도: **Critical**
- 종합한 raw: 27건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자와 사용자는 rolling upgrade 중 서비스가 가능한지를 물었다. DBA는 N/N-1 노드 혼합, rollback과 failover 순서를 요구했고, 엔진 개발자는 구버전이 새 catalog field나 log record를 무시하면 조용한 손상이 발생할 수 있다고 경고했다. PM 관점에서는 binary 배포와 기능 활성화를 분리하고 되돌릴 수 없는 시점을 운영자가 알아야 한다.

새 RK epoch log를 이해하지 못하는 N-1 standby에 보내는 것은 단순 호환 오류가 아니라 데이터 정합성 문제다. 노드별 capability를 협상하고, 모든 필수 노드가 이해할 때까지 새 record 생성을 막는 activation gate가 필요하다. catalog backfill, activation epoch, mixed-version에서 허용할 DDL/DML, downgrade 불가 지점과 재설치가 아닌 데이터 rollback 절차를 명시해야 한다.

**스펙이 결정할 것:** 지원 버전 행렬, handshake 실패 동작, 활성화 순서, mixed mode 제약, downgrade fence, feature를 끈 뒤 남는 metadata.

**수용 기준:** N/N-1 rolling upgrade·rollback·failover의 모든 지원 순서에서 미지원 record가 묵살되지 않고 사전에 차단되며, 지원 순서는 같은 데이터를 유지해야 한다.

### CF-17. 넓은 RK와 온라인 구축의 성능·용량 한계를 제품 계약으로 둬야 한다

- 심각도: **Major**
- 종합한 raw: 8건
- 판정: **컨셉 유효, 수치 결정 필요**

**raw 의견의 종합:** DBA와 엔진 개발자는 복합 문자열 UK가 index 크기, WAL, network, apply lookup, backup 보존량을 크게 늘린다고 지적했다. PM과 사용자는 “문법상 가능”한 키가 실제 운영에서는 HA lag와 장애 복구 시간을 감당하지 못할 수 있으므로 사전 비용 예측과 명시적 한계가 필요하다고 보았다.

1억 행에 `VARCHAR(255)` 네 개로 된 UK를 온라인 생성하면 scan·sort·index build뿐 아니라 이후 모든 UPDATE/DELETE 로그의 크기가 늘 수 있다. 구현이 동작한다는 사실과 운영 가능한 SLO는 다르다. 후보 RK 최대 byte, column 수, 지원 타입, 예상 추가 disk/WAL/network, build 중 throttle와 pause/cancel/resume, replica lag 임계치를 정의해야 한다.

**스펙이 결정할 것:** hard limit와 권고 limit, 비용 추정 API, resource reserve, online/offline 기준, SLO 초과 시 자동 throttle/중단.

**수용 기준:** 대표 데이터 크기와 최악 허용 키로 부하 시험해 공개 SLO를 만족하고, resource 부족은 기존 RK를 훼손하지 않는 checkpoint에서 안전하게 중단되어야 한다.

### CF-18. 실행 가능한 예제·안정 오류·전체 운영 runbook이 필요하다

- 심각도: **Major**
- 종합한 raw: 42건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 초급 사용자와 개발자는 현재 예제의 생략 기호, 불완전 constraint 이름, `OK/ERROR`만으로는 재현하거나 자동화할 수 없다고 지적했다. DBA는 생성부터 migration, HA 시작, failover, 수리, rollback까지 이어지는 runbook을 요구했다. 엔진 개발자는 번역된 오류 문자열이 아니라 stable code와 상태 assertion이 필요하다고 보았다.

예제는 setup, 실행 SQL, 예상 오류 코드와 파라미터, 사후 catalog 상태, cleanup까지 그대로 실행 가능해야 한다. 특히 RK 교체 실패 뒤 어느 키가 남는지, HA readiness 오류를 어떻게 고치는지, OFF→ON을 왜 직접 허용하지 않는지 설명해야 한다. 오류는 syntax, policy violation, transient resource, permanent corruption을 구분해 자동화가 올바르게 대응하게 해야 한다.

**스펙이 결정할 것:** 오류 code taxonomy, 메시지 필드, 예제의 지원 버전, migration/failover/recovery 절차와 rollback 기준.

**수용 기준:** 모든 code block이 문서 CI에서 실행되고, 처음 사용하는 운영자도 오류 원인·대상 객체·수정 방법·사후 상태를 이 문서만으로 찾을 수 있어야 한다.

### CF-19. 복제 정책 변경은 전용 권한과 원자적 감사 기록이 필요하다

- 심각도: **Critical**
- 종합한 raw: 27건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자는 일반 migration 계정이 실수로 중요한 table을 OFF로 만들 수 있다고 지적했다. DBA와 사용자는 누가 언제 어떤 이유로 데이터 보호를 바꿨는지 감사해야 한다고 보았고, 엔진 개발자는 catalog commit은 성공했는데 audit만 유실되거나 그 반대인 crash 경계를 문제 삼았다. PM 관점에서는 고위험 table을 조직 정책으로 잠그는 기능도 필요하다.

`ALTER TABLE` 권한이 있다는 이유만으로 복제 보호를 끄거나 RK 세대를 바꿀 수 있게 할지는 별도 결정이다. 전용 privilege, 역할별 허용 행렬, protected table lock 또는 승인 절차, actor·object·old/new policy·RK ID·commit ID를 담은 audit event가 필요하다. 감사 기록은 실제 durable catalog state와 일대일이어야 한다.

**스펙이 결정할 것:** 최소 권한, owner/DBA/deployer 역할, 보호 잠금, 감사 보존·조회, 실패/rollback event.

**수용 기준:** 전용 권한 없는 계정의 고위험 변경은 모두 거부되고, 성공한 각 변경에는 정확히 하나의 durable audit event가 있으며 rollback 상태와 모순되지 않아야 한다.

### CF-20. partition·상속·sharding에서 RK의 유일성 범위와 정책 소유자를 정해야 한다

- 심각도: **Critical**
- 종합한 raw: 21건
- 판정: **범위 조건부 유효**

**raw 의견의 종합:** 앱 개발자와 사용자는 parent에서 ON으로 만든 정책이 child/partition에 상속되는지 물었다. DBA는 attach/detach와 row 이동 중 HA 안전성을, 엔진 개발자는 partition-local unique key가 table 전체에서 행 하나를 식별하지 못할 수 있다고 지적했다. PM 의견은 지원하지 않는 객체라면 조용히 허용하지 말고 범위 밖으로 명시해야 한다는 것이다.

두 월별 partition에 각각 `id=7`이 가능하면 `id`만으로는 어느 행을 변경할지 알 수 없다. global uniqueness를 요구하거나 RK에 partition stable ID를 포함해야 한다. parent와 child 중 누가 REPLICATION policy 및 logical RK를 소유하는지, attach/detach/exchange/split/merge와 partition 간 UPDATE가 어떤 세대 전환을 만드는지도 필요하다. CUBRID에서 특정 기능을 지원하지 않는다면 이 쟁점은 삭제할 것이 아니라 “해당 객체는 RK 기능 비지원이며 생성/전환을 사전 거부”로 닫아야 한다.

**스펙이 결정할 것:** 지원 객체 행렬, global/local uniqueness, policy 상속·override, partition 이동 로그, topology 변경의 atomicity.

**수용 기준:** 모든 지원 partition DDL과 row 이동 뒤 DML이 정확히 한 행을 찾고 모든 노드 metadata가 같아야 하며, 비지원 조합은 실행 전에 안정 오류로 차단되어야 한다.

### CF-21. TRUNCATE·bulk·CTAS·clone 등 모든 변경 경로가 같은 정책을 거쳐야 한다

- 심각도: **Critical**
- 종합한 raw: 33건
- 판정: **범위 조건부 유효**

**raw 의견의 종합:** 사용자는 일반 INSERT/UPDATE 외 작업도 ON/OFF 규칙을 따르는지 물었다. 앱 개발자는 ORM bulk와 `CREATE TABLE AS SELECT`, DBA는 TRUNCATE·load·clone·rename·partition exchange를 제기했다. 엔진 개발자는 행별 DML 경로만 validator와 log encoder를 사용하면 다른 실행 경로가 정책을 우회한다고 보았다.

ON 원본에서 `CREATE TABLE ... LIKE`로 clone을 만들 때 policy가 복사되는지, CTAS 결과가 기본 ON인지, TRUNCATE가 DDL로 모든 노드에 적용되는지 또는 데이터 변경으로 OFF에서 제외되는지가 필요하다. bulk loader, direct path, system catalog operation, temporary table, serial/LOB 같은 특수 객체도 공통 policy와 crash 규칙을 사용해야 한다. 모든 기능을 지원할 필요는 없지만 각 진입점은 “동일 계약으로 지원” 또는 “실행 전 거부” 중 하나여야 한다.

**스펙이 결정할 것:** DDL/DML 분류, policy 상속, log record 형태, transaction/crash 의미, 지원 객체·명령 전체 행렬.

**수용 기준:** 일반·bulk·특수 경로가 명세대로 같은 최종 checksum을 만들거나 사전에 거부되고, 어떤 경로도 ON 테이블의 RK 검증과 OFF 정책을 우회하지 않아야 한다.

### CF-22. 병렬 적용·재전송·로그 보관이 schema barrier를 깨지 않아야 한다

- 심각도: **Critical**
- 종합한 raw: 14건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 엔진 개발자는 병렬 worker에서 old DML, RK DDL, new DML의 완료 순서가 역전되는 문제와 old epoch metadata의 조기 GC를 집중적으로 제기했다. DBA와 앱 개발자는 재시작·network 재전송으로 같은 로그가 중복 적용되는 경우를, PM은 장기 보관 로그와 codec version의 호환성을 요구했다.

LSN 100의 old-RK UPDATE가 worker A에서 느리게 실행되는 동안 101의 RK DDL과 102의 new-RK UPDATE가 다른 worker에서 끝나면, 단순 LSN 공급 순서만으로는 안전하지 않다. DDL 전 worker drain 또는 동등한 schema barrier, 모든 소비자가 지난 global safe point, epoch metadata와 log의 보존 연계가 필요하다. 재전송·recovery replay에는 idempotence key와 record checksum이 있어 중복 가시성을 막아야 한다.

**스펙이 결정할 것:** worker dependency와 barrier, apply 완료의 정의, safe point 계산, log/metadata GC, codec version, duplicate replay 규칙.

**수용 기준:** 지연·재정렬·중복·worker crash·전체 재시작을 조합해도 commit 순서와 exactly-once 가시성이 유지되고 필요한 epoch가 적용 전에 삭제되지 않아야 한다.

### CF-23. resource 고갈·손상·반복 오류에서 안전하게 멈추는 상태가 필요하다

- 심각도: **Blocker**
- 종합한 raw: 12건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 초급 개발자와 사용자는 disk full이나 OOM 때 SQL 성공 여부를 신뢰할 수 있는지 물었다. DBA는 같은 apply 오류의 무한 retry와 lag 폭증을, 엔진 개발자는 catalog write·index build·WAL flush 사이 실패와 손상 record를 문제 삼았다. 공통 결론은 가용성을 위해 계속 시도하는 것보다 손상을 확산하지 않는 durable quarantine가 먼저라는 것이다.

catalog에는 새 RK가 기록됐지만 WAL flush가 ENOSPC로 실패하면 commit 성공을 반환해서는 안 된다. apply할 수 없는 record를 무한 재시도하면 CPU·log·disk를 고갈시키고 다른 table까지 막을 수 있다. 단계별 failure matrix, emergency WAL reserve, bounded retry와 backoff, transient/permanent 분류, 영속 quarantine, 해당 node의 promotion 금지가 필요하다. 수동 skip은 데이터 손실과 승인자를 기록해야 한다.

**스펙이 결정할 것:** 각 실패점의 rollback/roll-forward, retry budget, 격리 단위, 승격 금지, 운영자 수리·skip 절차.

**수용 기준:** OOM·ENOSPC·I/O error·손상 record를 주입해도 부분 성공이 없고, 비재시도 오류는 재시작 뒤에도 격리되며 그 노드는 검증 전 승격되지 않아야 한다.

### CF-24. network partition과 split-brain을 단일 writer fencing으로 막아야 한다

- 심각도: **Blocker**
- 종합한 raw: 12건
- 판정: **컨셉 유효**

**raw 의견의 종합:** DBA와 엔진 개발자는 분할된 두 primary가 서로 다른 RK DDL과 DML을 받아들이면 두 history를 자동 병합할 수 없다고 지적했다. 앱 개발자와 사용자는 장애 뒤 old connection이 살아서 stale primary에 계속 쓰는 경우를 물었다. PM 의견은 multi-standby·cascade 구성에서도 승격 권한과 지원 topology를 명시해야 한다는 것이다.

network partition 중 A는 RK를 `email`, B는 `phone`으로 바꾸고 각각 쓰기를 받을 수 있다. 연결이 복구되어도 어느 DDL이 정당한지, 같은 업무 row의 어느 값이 권위인지 기술적으로 자동 결정할 수 없다. cluster의 단일 writer lease/epoch를 catalog, log record, promotion, client session token에 연결하고, 오래된 epoch의 write와 log를 차단해야 한다. quorum 밖 강제 승격은 데이터 손실 가능성과 재가입 금지를 명시해야 한다.

**스펙이 결정할 것:** writer 선출과 lease, fencing token 발급·검사, 지원 topology, 강제 승격, split-brain 후 수동 reconciliation.

**수용 기준:** network partition에서 오직 한 writer epoch만 commit할 수 있고 stale client/log는 거부되며, divergent node는 자동 재가입하지 않아야 한다.

### CF-25. 자연키 RK가 로그와 telemetry에서 개인정보를 노출하지 않아야 한다

- 심각도: **Major**
- 종합한 raw: 10건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 앱 개발자와 사용자는 PK 대신 email·전화번호가 RK가 되면 row-not-found 오류와 trace에 값이 찍힐 수 있다고 지적했다. DBA는 support bundle, quarantine file, log 보존과 접근 권한을, 엔진 개발자는 metric label cardinality 폭증을 문제 삼았다. PM은 개인정보 처리와 진단 가능성 사이의 기본 정책을 요구했다.

RK before-image는 적용에 필요할 수 있지만 일반 운영 log에 원문을 출력할 필요는 없다. 기본은 redaction 또는 keyed hash와 table/log/epoch 식별 정보만 제공하고, 원문 reveal은 별도 privilege·감사·짧은 보존 기간을 적용해야 한다. metric label에는 개별 RK 값을 쓰지 않고 제한된 오류 code와 table 단위 count를 사용해야 한다. archive/WAL 자체의 암호화와 접근은 기존 보안 정책과 연결해야 한다.

**스펙이 결정할 것:** 어느 저장소에 원문이 필요한지, masking/hash 방식, privileged reveal, retention/encryption, support export 정책.

**수용 기준:** 일반 log·metric·trace·support bundle에 RK 원문이 없고, 승인된 제한 경로의 조회만 감사 가능하게 허용되어야 한다.

### CF-26. ORM·driver·schema diff·cache·CDC가 새 metadata와 epoch를 이해해야 한다

- 심각도: **Major**
- 종합한 raw: 15건
- 판정: **범위 조건부 유효**

**raw 의견의 종합:** 앱 개발자는 기존 connection pool의 prepared statement와 ORM schema migration이 RK 변경 뒤 어떻게 동작하는지 물었다. DBA는 schema diff가 알 수 없는 `REPLICATION` 절을 지우는 위험을, 엔진 개발자는 plan/cache invalidation과 CDC event key 변경을 지적했다. PM은 어떤 tool/version을 공식 지원하는지가 공개 범위여야 한다고 보았다.

RK 변경 후에도 old prepared plan이나 cached metadata가 쓰이면 잘못된 제약 판정 또는 retry가 발생할 수 있다. schema introspection API는 policy, selected logical RK와 epoch를 안정적으로 제공하고 DDL commit 시 cache invalidation signal을 보내야 한다. CDC consumer에는 key schema 변경 event와 호환 전략이 필요하다. 모든 제3자 도구를 책임질 수는 없지만 공식 driver/tool의 지원 버전과 unknown metadata 보존 규칙은 정해야 한다.

**스펙이 결정할 것:** 공개 metadata API, invalidation, stale statement 오류/retry, CDC schema evolution, 공식 지원 tool matrix.

**수용 기준:** 지원 ORM/driver의 introspect→diff→apply와 rolling application 시험에서 policy가 유실되지 않고, stale cache는 잘못 실행되지 않으며 명확히 갱신 또는 재시도되어야 한다.

### CF-27. 논리 RK의 동일성을 constraint 이름과 물리 index에서 분리해야 한다

- 심각도: **Major**
- 종합한 raw: 7건
- 판정: **컨셉 유효**

**raw 의견의 종합:** DBA는 UNIQUE index rename/rebuild가 RK 교체로 취급되는지 물었다. 앱 개발자는 단순 schema rename 때문에 연결과 CDC key가 바뀌는 문제를, 엔진 개발자는 optimizer가 다른 access path를 선택하더라도 논리적 행 식별은 같아야 한다고 보았다. PM 의견은 사용자가 “의미 변경”과 “물리 유지보수”를 구별할 수 있어야 한다는 것이다.

`UNIQUE(email)`의 이름을 바꾸거나 물리 index를 online rebuild해도 컬럼, 순서, 비교 의미가 같다면 logical RK는 그대로여야 한다. 반대로 collation·컬럼 구성·NULL 규칙이 바뀌면 이름이 같아도 새 generation이다. logical RK ID와 physical index mapping을 분리하고 mapping 교체를 원자적으로 수행해야 한다. optimizer가 index를 쓰지 못할 때 fallback을 허용하더라도 정확성은 동일해야 한다.

**스펙이 결정할 것:** logical identity 구성 요소, 의미 보존 DDL 목록, generation 증가 조건, physical mapping 교체와 fallback.

**수용 기준:** rename/rebuild 같은 의미 불변 작업은 logical ID를 유지하고, 의미 변경만 새 generation을 만들며, 어느 access path에서도 동일한 한 행을 찾아야 한다.

### CF-28. 제품 목표·대안·지원 범위와 성공 지표를 먼저 명확히 해야 한다

- 심각도: **Major**
- 종합한 raw: 25건
- 판정: **컨셉 유효, 제품 결정 필요**

**raw 의견의 종합:** PM은 어떤 고객 문제를 얼마나 줄이면 성공인지 측정할 KPI가 없다고 지적했다. 사용자와 앱 개발자는 자연스러운 PK/NOT NULL UK가 없는 heap table이 OFF로 밀려 failover 보호를 잃을 수 있다고 보았다. DBA와 엔진 개발자는 MySQL식 전체 컬럼, 명시 RK, synthetic key, table OFF, 기능 비지원 같은 대안을 성능·호환성·안전성으로 비교해야 한다고 요구했다.

“기존 PK 변경 누락을 막는다”는 목표는 타당하지만 지원 대상과 비목표가 불명확하다. 예를 들어 중복 허용 heap table, nullable unique, partition-local key, 매우 넓은 자연키를 어떻게 처리할지에 따라 실제 schema 지원률이 달라진다. 자동 UK 선택이 명시 지정보다 좋은 이유, OFF를 안전한 예외로 볼 수 있는 workload, PostgreSQL 컨셉에서 가져오지 않는 부분을 문서화해야 한다.

**스펙이 결정할 것:** target workload, 지원/비지원 schema matrix, 대안 선택 근거, data loss·availability·performance KPI, 출시 gate.

**수용 기준:** 대표 고객 schema의 지원률, 복제 누락 0건, 성능 overhead와 migration 실패율을 측정할 수 있고, 미지원 workload는 도입 전에 식별되어야 한다.

### CF-29. table 단위 정책으로 표현할 수 없는 tenant·보존 요구의 경계를 정해야 한다

- 심각도: **Major**
- 종합한 raw: 3건
- 판정: **범위 조건부 유효**

**raw 의견의 종합:** 주로 애플리케이션 개발자들이 공유 table 안의 tenant마다 RPO나 복제 금지 요구가 다르면 table 단위 ON/OFF로 표현할 수 없다고 지적했다. 또한 OFF가 된 각 node의 사본도 개인정보 삭제·법적 보존 대상인데 중앙 복제 관리 밖에서 빠질 수 있다는 우려가 있었다.

한 `orders` table에서 tenant A는 RPO 0을, tenant B는 지역 밖 복제 금지를 요구한다면 단일 ON/OFF는 두 요구를 동시에 만족하지 못한다. 이 피처가 row/tenant 단위 정책을 제공해야 한다는 뜻은 아니다. 지원 granularity가 table임을 명시하고, 표현 불가능한 배치는 사전 거부 또는 schema 분리를 안내해야 한다. OFF 사본의 backup·삭제·node 폐기 증적도 데이터 거버넌스 범위에 남는다.

**스펙이 결정할 것:** 정책 granularity, edition/topology별 차이, OFF 데이터의 보존·삭제 책임, deprecation과 장기 지원.

**수용 기준:** 표현 불가능한 tenant 배치를 안전하다고 오인시키지 않고, OFF 사본도 조직의 보존·삭제·폐기 증적에서 추적할 수 있어야 한다.

### CF-30. 30개 계약을 상태 모델과 자동 시험에 연결해야 한다

- 심각도: **Major**
- 종합한 raw: 10건
- 판정: **컨셉 유효**

**raw 의견의 종합:** 엔진 개발자는 mode, 후보 수, DDL/DML 순서, crash, version, topology의 조합이 너무 커 예제 기반 시험만으로 부족하다고 지적했다. 앱 개발자와 사용자는 문서 문장이 실제 보장인지 확인할 traceability를, PM은 출시 판정을 위한 coverage와 oracle을 요구했다. 공통 결론은 row count 하나가 아니라 schema epoch·data checksum·commit 결과를 함께 비교하는 불변식 기반 시험이 필요하다는 것이다.

상태 모델은 최소한 single/HA, policy ON/OFF, 후보 0/1/N, old/new epoch, transaction, apply lag, failover, backup, version을 포함해야 한다. property-based sequence 생성과 fault injection으로 드문 interleaving을 탐색하고, 각 규범 문장을 test ID로 연결해야 한다. oracle은 “명령이 성공했다”가 아니라 정확히 한 행 적용, 허용된 RPO, 양 노드 schema/data 일치, 안전한 거부 상태를 판정해야 한다.

**스펙이 결정할 것:** normative requirement ID, 상태와 전이, test matrix 우선순위, checksum/oracle, 장기·장애 시험의 출시 gate.

**수용 기준:** 이 문서의 핵심 불변식과 각 CF의 수용 기준이 자동 시험에 연결되고, 생성된 상태 전이와 fault injection에서 데이터 오적용·조용한 divergence가 없어야 한다.

---

## 5. 컨셉 차원의 최종 결론

### 기능 방향에 대한 결론

RK를 PK에서 `PK 또는 NOT NULL UNIQUE`로 확장하는 방향은 기존 PK 변경 시 복제 누락 문제를 줄이는 유효한 접근이다. `REPLICATION=OFF`를 명시적으로 도입하는 것도 복제 불가능한 테이블을 암묵적으로 놓치는 것보다 낫다. 따라서 기능의 기본 문제 정의와 해결 방향을 폐기할 이유는 없다.

그러나 스펙의 중심을 “현재 후보 키가 하나 이상 있는지 검사한다”에서 “로그가 생성된 시점부터 적용·장애·복구가 끝날 때까지 동일한 행 식별 의미를 보존한다”로 바꿔야 한다. RK는 단순히 선택된 UNIQUE index가 아니라 **세대를 갖는 논리적 복제 프로토콜 객체**여야 한다. 마찬가지로 OFF는 boolean 최적화 옵션이 아니라 **failover 때 데이터 손실을 의도적으로 허용하는 생명주기 정책**으로 다뤄야 한다.

### 출시 전에 반드시 닫아야 하는 질문

1. DML 로그는 어떤 table/RK/generation과 before-key를 영속하는가?
2. 여러 UK 중 선택 결과는 어떻게 결정·저장·조회되고 언제 바뀌는가?
3. RK 교체의 commit 지점과 동시 transaction, crash recovery 규칙은 무엇인가?
4. standby가 어떤 epoch·LSN·health일 때 승격 가능한가?
5. OFF 기간 데이터의 권위 사본은 어디이며 OFF→ON·failback·재가입은 어떻게 하는가?
6. trigger/FK/cascade/혼합 transaction과 특수 DML 경로는 무엇을 복제하는가?
7. upgrade·backup·PITR이 old RK generation을 언제까지 보존하는가?
8. 지원하지 않는 객체·키 타입·도구·topology는 무엇이며 어디서 사전 차단하는가?
9. 운영자는 policy, eligibility, selected RK, epoch, lag, quarantine를 어떻게 구별하는가?
10. 위 답을 어떤 자동 시험과 checksum oracle로 증명하는가?

이 질문에 규범적 답과 시험 가능한 수용 기준이 마련되기 전에는 문법과 happy path가 구현되어 있어도 전체 기능 계약이 완성되었다고 보기 어렵다.

## 6. 코드 대조 결과와 함께 읽는 법

이 문서와 구현 필터는 서로 대체하지 않는다.

- **이 문서:** 그 문제가 제품 컨셉상 왜 필요한지, 스펙이 무엇을 약속해야 하는지 판단한다.
- **`CUBRID_FIT_FILTER_FEATURE.md`:** 현재 feature 코드가 해당 경로를 구현했는지, develop에도 있던 기존 문제인지, CUBRID 범위 밖인지 판단한다.

따라서 코드 필터에서 `기각` 또는 `폐기`로 표시된 항목도 다음 두 경우를 구별해야 한다.

- 코드가 이미 안전하게 처리함: 컨셉 요구는 유효하며 구현 근거와 regression test로 닫을 수 있다.
- 제품 범위에서 명시적으로 지원하지 않음: 컨셉 쟁점은 조건부 유효하며 스펙의 비지원 선언과 사전 차단으로 닫을 수 있다.

“코드에서 찾지 못했다” 또는 “현재 코드가 처리한다”만으로 스펙의 계약 문장을 제거하면, 사용자는 보장된 동작과 우연한 구현을 구별할 수 없고 이후 refactoring에서 보장이 사라져도 알 수 없다.

## 7. raw 추적성

- raw 문서: `raw/*.md` 20개
- raw heading: 691개
- 고유 raw ID: 691개
- CF-01~CF-30에 주 배정된 ID: 691개
- 미배정·중복 배정: 0개

각 CF의 정확한 raw ID 전수 목록과 원본 파일별 ID는 [CONSOLIDATED_FINDINGS.md](CONSOLIDATED_FINDINGS.md)에 보존되어 있다. 이 문서는 그 문장들을 단순 축약한 것이 아니라, 같은 원인을 말한 개발자·DBA·PM·사용자 관점의 공통점과 서로 다른 영향 범위를 사람이 읽을 수 있는 하나의 설명으로 재구성한 것이다. 상세 원문 감사가 필요할 때만 raw 및 통합본으로 내려가면 되며, 기능 의도와 컨셉 문제를 이해하기 위해 다른 문서를 먼저 읽을 필요는 없다.
