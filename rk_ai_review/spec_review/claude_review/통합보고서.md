# CUBRID HA 복제 개선 스펙 — 통합 리뷰 보고서

## 개요

대상 문서는 `user_spec_extracted.md`, 즉 CUBRID HA 복제의 **복제 키(RK)** 자동 선택과 테이블 단위 **REPLICATION 옵션(ON/OFF)** 을 규정하는 스펙이다. 이 스펙이 풀려는 문제(PK 없는 테이블 때문에 복제가 조용히 누락되어 마스터·슬레이브 데이터가 어긋나는 실제 장애)와 큰 방향(PostgreSQL의 REPLICA IDENTITY 개념 일부 채용 + REPLICATION 테이블 옵션)은 타당하다. 그러나 문서를 실제 운영 시나리오와 인접 기능에 대입하면 컨셉·구현·문서 세 층위 모두에서 릴리스를 막는 결함이 드러난다.

이 보고서의 모든 이슈는 **CBRD-26246 구현 코드(`feature/CBRD-26246-develop` @44468ed73, 2026-08-23 기준)** 와 실제로 대조되었다. 각 이슈에는 그 대조 결과를 다음 다섯 등급으로 붙였다. **확정**(코드가 지적을 뒷받침, 미구현 구멍 실재) · **기각**(코드가 이미 처리, 지적 전제가 성립하지 않음) · **코드무관**(순수 문서 결함이라 코드 대조 대상 아님) · **판정불가**(런타임 검증 필요) · **비적용**(CUBRID 구조상 전제 자체가 성립 불가 — 부록으로 이관). 전체 판정 집계는 확정 18 · 기각 15 · 코드무관 30 · 판정불가 2 · 비적용 3이다. 이 코드 대조 판정이 각 지적의 신뢰도 근거다.

### 릴리스 판정 — 불가 (NEEDS_FIX)

핵심 근거는 넷이다.

1. **핵심 개념이 비결정적이다.** RK 자동 선택 규칙이 "ex.(예를 들어) …" 수준의 예시로만 적혀 있고, 코드는 조회 불가능한 내부 인덱스 배열 순서로 RK를 고른다. 마스터가 정한 RK를 슬레이브가 재계산 없이 쓰도록 하는 아키텍처가 미구현이며, 코드 주석의 TODO가 이 교체 필요성을 스스로 명시한다.
2. **핵심 목표를 지키는 방어망에 구멍이 있다.** FK 참조 대상이 복제 제외로 넘어가 failover 후 참조 데이터가 사라지는 것이 이 기능의 출발점인데, 정면 경로(`ALTER … REPLICATION=OFF`)는 HA 운영 중 전면 차단되어 막히지만, **RENAME(그림자 스왑)** 경로는 재검증이 없어 같은 장애가 재현된다.
3. **안전장치가 도는 시점이 좁다.** §7 검사(코드의 rkcheck)는 `cubrid hb start`에서만 돌고, 실제로 마스터가 바뀌는 **failover/switchover/failback** 에는 재검증이 없다. 운영 중 RK를 잃은 테이블이 있으면 승격 직후 무검증으로 쓰기를 받는다.
4. **문서 내부 모순과 마이그레이션 공백.** §8과 §9가 "표시 없는 테이블의 기본값"을 각각 ON/OFF로 정반대로 규정한다(코드는 ON으로 확정 구현 — §9가 오기). in-place 업그레이드·롤링 업그레이드·다운그레이드 카탈로그 마이그레이션 서술이 비어 있다.

특히 위 1·3은 문서 교정만으로는 해소되지 않는 컨셉·구현 차원의 결함이다. 현재 문서로는 QA 테스트케이스 작성도, 구현 완료 판정도, 사용자 매뉴얼화도 불가능하다.

---

## 용어

- **RK (Replication Key, 복제 키)**: 슬레이브에서 어떤 행을 갱신·삭제할지 식별하는 키. 엔진이 PK 또는 NOT NULL UNIQUE(UK) 중 하나를 자동 선택한다.
- **RK 후보**: RK가 될 자격이 있는 PK/UK 제약. 코드 기준으로는 "PK, 또는 구성 컬럼이 NOT NULL인 UNIQUE".
- **REPLICATION 옵션**: 테이블 단위로 복제 대상(ON)/제외(OFF)를 정하는 옵션. 클래스 단위 단일 플래그(`SM_CLASSFLAG_DATA_REPLICATION_OFF`)로 저장된다.
- **applylogdb**: 슬레이브가 복제 로그를 실제로 반영하는 모듈.
- **rkcheck**: 스펙 §7의 "HA 기동 시 제약 검사"를 구현한 유틸리티. `cubrid rkcheck <db>` 독립 실행 또는 `cubrid hb start` 시 자동 호출되어 전 클래스를 순회하고, 위반 시 로그 디렉토리에 `<db>_rkcheck_YYYYMMDD_HHMM.list` 파일을 남기고 기동을 중단한다.
- **HA / CS / SA 모드**: HA는 복제 클러스터 운영 모드, CS는 클라이언트-서버, SA는 standalone(오프라인 단독). 코드에서 REPLICATION 옵션 변경과 RK 검사는 `HA_DISABLED()` 계열 판정으로 SA/단일 모드에서만 다르게 동작한다. (스펙은 §9에서 SA를 정의 없이 처음 쓰므로 §1에 이 세 모드 관계를 명시해야 한다.)

---

## 치명 (Critical) — 릴리스 차단

### 1. RK 자동 선택 규칙이 비결정적 (원 C-1)

스펙 §1은 "UK가 여러 개면 큐브리드 엔진이 이 중 하나를 선택한다(ex. 테이블 내에 명시된 순서 중 가장 빠른 순서)"라고만 적는다. `ex.`가 확정 규칙인지 예시인지 불명확하고, "명시된 순서"가 (a) CREATE TABLE 텍스트 순서, (b) 카탈로그 내부 생성 순번, (c) 컬럼 선언 순서 중 무엇인지 정의가 없다. 세 해석은 ALTER로 UK를 추가·삭제·재생성하면 서로 다른 결과를 낸다. 나아가 마스터와 슬레이브가 각자 카탈로그를 보고 RK를 재계산하면 두 노드가 서로 다른 컬럼을 RK로 고를 수 있고(split-brain), **unload→load 왕복만으로도(ALTER 없이) 원본과 복원본이 다른 RK를 고를 수 있다** — 자동 선택 규칙이 unload 스키마 파일의 제약 나열 순서에 의존하는데 그 순서 보장이 없기 때문이다.

- **관련 스펙**: §1, §8
- **예제**
  ```sql
  CREATE TABLE t (a INT NOT NULL UNIQUE, b INT NOT NULL UNIQUE);  -- 텍스트 순서면 RK=a
  ALTER TABLE t DROP CONSTRAINT u_t_a;      -- a의 UK 제거
  ALTER TABLE t ADD CONSTRAINT UNIQUE(a);   -- a의 UK 재생성(카탈로그상 b보다 나중)
  -- 이제 RK는 a인가 b인가? 기준 정의에 따라 갈린다. 사용자는 아무것도 "바꾸지" 않았다.
  ```
- **시나리오**: 마스터·슬레이브가 각자 재계산하면, 위 조작 후 마스터는 여전히 a를, 슬레이브는 생성 순번이 뒤바뀌어 b를 RK로 고를 수 있다. 이후 마스터의 `UPDATE t SET c=… WHERE a=1` 로그가 슬레이브에 오면 슬레이브는 b를 식별자로 기대해 대상 행을 못 찾고, 조용히 건너뛰거나 fail_count가 오른다. 마스터·슬레이브가 서서히 어긋나고, 정작 이 스펙이 없애려던 "조용한 복제 누락"이 RK 선택 규칙 자체에서 재발한다.
- **코드 대조 — 확정**: RK 선택은 스펙의 'ex. 명시된 순서'가 아니라 '클래스표현 인덱스 배열 순서(PK 패밀리 먼저, 그다음 UNIQUE 프로퍼티 저장순)에서 첫 복제 후보'라는 내부 규칙이며, 조회 불가·sticky 불변식 없음. 마스터는 키 값만 실어 보내고 슬레이브는 `btree_get_rkey_btid`로 자기 카탈로그에서 RK를 독립 재계산한다. `object_representation_sr.c:4692`의 TODO가 '인덱스 의존 방식을 마스터에서 RK 이름을 받는 방식으로 교체 필요'라고 명시 — 아래 권고가 미구현임을 코드가 확인한다. (근거: `src/base/object_representation_sr.c:4692`, `src/storage/btree.c:8285-8298`, `src/base/object_representation_sr.c:2322-2328`, 슬레이브 재계산 `src/transaction/locator_sr.c:6848`)
- **권고**: 선택 기준을 "제약이 카탈로그에 생성된 순번(단조 증가 ID) 오름차순" 같은 조회 가능한 단일 규칙으로 명문화하고, "한번 선택된 RK는 명시적 DDL 없이는 재선택되지 않는다(sticky)"는 불변식을 추가. 마스터가 결정한 RK를 DDL 복제 로그에 실어 슬레이브가 재계산하지 않고 그대로 사용하도록 아키텍처를 확정. 이것이 이 스펙의 가장 뿌리에 있는 결함으로, 다른 여러 이슈의 원인이다.

### 2. RK 자격을 조용히 잃는 "열거되지 않은 경로" (원 C-9)

§4-2는 UK를 RK로 쓸 때 "UNIQUE 제약 삭제"와 "컬럼 삭제"만 막는다. 그런데 RK 자격은 "NOT NULL UNIQUE"이므로, UNIQUE는 그대로 두고 `MODIFY COLUMN a INT NULL`로 NOT NULL만 풀어도 자격이 사라진다. RK 컬럼 타입을 `INT → BIGINT`로 바꾸는 흔한 작업(정확히 원래 배경 버그인 "PK 컬럼 속성 변경"과 같은 유형)도 §4-2에 없다. 열거식 차단이라 우회로가 남고, "HA 복제 대상은 항상 RK를 가진다"는 §1 불변식이 실제로는 보장되지 않는다.

- **관련 스펙**: §4-2
- **예제**
  ```sql
  CREATE TABLE tbl(a INT, b INT NOT NULL UNIQUE);  -- RK=b
  ALTER TABLE tbl MODIFY COLUMN b INT NULL;        -- UNIQUE 유지, NOT NULL만 제거
  -- 어느 규칙에도 안 걸림. b는 RK 자격 상실 → 운영 중 RK 없는 복제 테이블 발생
  ```
- **시나리오**: NOT NULL만 푼 뒤 다른 후보가 없으면 RK가 0개가 되지만, §7 검사는 HA 기동 시점에만 돌므로 재시작 전까지 감지되지 않는다. 이후 이 테이블 변경이 슬레이브에 반영되지 않거나 다음 재시작에서 갑자기 기동이 거부된다. 배경 장애였던 "PK 컬럼 속성 변경으로 인한 복제 누락"이 다른 경로로 재발한다.
- **코드 대조 — 확정**: RK 재검사 게이트 `IS_REPL_CONSTRAINT_RELATED_ALTER`는 `PT_ADD_ATTR_MTHD`/`PT_DROP_ATTR_MTHD`/`PT_DROP_CONSTRAINT`/`PT_DROP_PRIMARY_CLAUSE`만 트리거하고, MODIFY/CHANGE COLUMN 경로(`PT_CHANGE_ATTR`)는 목록에 없어 NOT NULL 해제나 타입 변경 시 `check_ha_repl_constraint`가 호출되지 않는다. 게다가 게이트가 첫 절(`alter->info.alter.code`)만 보므로 후순위 절의 제약 변경도 누락될 수 있다. (근거: `src/query/execute_schema.c:109-114`(매크로), `:2020`(PT_CHANGE_ATTR), `:2051`(게이트))
- **권고**: "RK 자격에 영향을 주는 모든 DDL 경로(제약 삭제·컬럼 삭제·NOT NULL 해제·타입 변경 등)를 전수 조사해 §4-2에 포함하고, 열거되지 않은 경로는 기본 차단"을 원칙으로 선언.

### 3. 부분 NOT NULL 복합 UK가 RK로 선택되면 행 유일 식별 불가 (원 2C-4)

스펙의 UK 예시는 모두 단일 컬럼이다. 복합 UNIQUE에서 일부 컬럼만 NOT NULL이면(SQL 관례상 NULL은 서로 다른 값 취급), 같은 값 조합의 행이 여러 개 공존할 수 있어 RK로 쓸 수 없다. "NOT NULL UNIQUE"가 "구성 컬럼 전부 NOT NULL"인지 "하나라도 NOT NULL"인지 스펙에 정의가 없다. 이슈 2(RK 자격 상실)와 층위가 다른, **후보 자격 판정 기준의 정합성** 문제다.

- **관련 스펙**: §1 "Not Null Unique Key" 정의, §4-2
- **예제**
  ```sql
  CREATE TABLE t3 (x INT NOT NULL, y INT, UNIQUE (x, y));  -- y는 NULL 허용
  INSERT INTO t3 VALUES (1, NULL);
  INSERT INTO t3 VALUES (1, NULL);   -- 위반 아님 → (x=1,y=NULL) 행이 둘
  -- 이 UK가 RK면 "x=1 AND y IS NULL" 조건이 두 행에 매치
  ```
- **시나리오**: 마스터에 (1, NULL) 행이 둘 공존하고 그중 하나를 UPDATE/DELETE 하면, 슬레이브 applylogdb가 두 행을 함께 잡아 오적용하거나 적용 실패(fail_count 증가)로 이어진다. 사용자는 표준 SQL대로 유효한 데이터를 넣었을 뿐이라 스펙만 봐서는 위험을 알 수 없다.
- **코드 대조 — 확정**: `sm_has_non_null_attribute`는 구성 컬럼 중 '하나라도' NOT NULL이면 1을 반환하고, `IS_HA_REPLICATION_KEY_CONSTRAINT`가 이를 UNIQUE 계열 판정에 그대로 사용한다. '구성 컬럼 전부 NOT NULL' 검사가 없어 부분 NOT NULL 복합 UK가 RK 자격을 얻는다. (근거: `src/object/schema_manager.c:16114-16130`, `src/object/class_object.c:95-98`)
- **권고**: "복합 UK가 RK 후보가 되려면 구성 컬럼 전부가 개별적으로 NOT NULL이어야 한다"를 §1에 명시, §4-2 후보 판정에서 부분 NOT NULL 복합 UK 제외, 복합 UK 예시 최소 1개 추가.

### 4. FK 참조 부모 테이블의 사후 REPLICATION=OFF 전환 미차단 (원 C-2)

이 기능의 존재 이유(도입부: orders는 복제되는데 참조 대상 customers가 복제 제외라 failover 후 FK가 깨짐)를 스펙이 스스로 뚫을 수 있는 지점이다. §5는 FK를 생성/추가하는 시점에만 참조 대상의 복제 여부를 검사한다. §2-2는 "OFF→ON 전환 금지"라는 한 방향만 규정하고, 반대 방향인 "이미 FK로 참조받는 ON 테이블을 OFF로 내리는 것"에는 규칙이 없다. 같은 결과는 **RENAME TABLE(그림자 스왑)** 과 **트리거로 구현한 참조 무결성** 으로도 도달한다 — §5가 선언적 FOREIGN KEY만 검사하므로 트리거 기반 참조는 방어망 밖이다(RENAME 경로의 코드 대조는 이슈 16 참조). 규제(PII 국외반출 제한)로 부모를 OFF로 둬야 하는 요구와 §5의 강제가 정면 충돌한다는 지적도 있다.

- **관련 스펙**: §2-2, §4, §5
- **예제**
  ```sql
  CREATE TABLE customers(customer_id INT PRIMARY KEY, country INT);   -- REPLICATION=ON
  CREATE TABLE orders(order_id INT PRIMARY KEY, customer_id INT,
    CONSTRAINT fk FOREIGN KEY(customer_id) REFERENCES customers(customer_id));
  ALTER TABLE customers REPLICATION=OFF;   -- 스펙에 막는 규칙 없음 → OK로 읽힘
  -- 이 순간부터 orders(ON)만 복제, customers(OFF) 미복제 → failover 후 도입부 장애 재현
  ```
- **코드 대조 — 기각**: `ALTER … REPLICATION` 변경은 `do_alter_change_replication`이 `!HA_DISABLED()`이면 방향 불문 `ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED`로 전면 차단한다. 따라서 '예시6대로 HA 운영 중 `ALTER customers REPLICATION=OFF` 통과'라는 전제는 성립하지 않는다. reverse-FK 무검사 자체는 사실이나, OFF 전환은 단일 모드에서만 가능하고 그 위반은 HA 기동 시 rkcheck 전 클래스 순회가 잡는다. (근거: `src/query/execute_schema.c:11740-11745`; 순회 `src/executables/util_cs.c:3322,3349`) — 즉 정면 ALTER 경로는 막혀 있으나, 재검증 없는 RENAME 경로(이슈 16)는 확정 구멍이므로 FK 불변식 재설계는 여전히 필요하다.
- **권고**: FK 불변식을 "생성 시점 검사"가 아니라 "항상 유지되는 불변식"으로 재정의하고, ALTER·RENAME·트리거 경로까지 대칭으로 방어. 특히 RENAME 시 §5·§7과 동일한 정합성 재검증을 트리거.

### 5. 현재 RK가 무엇인지 조회할 방법이 없다 (원 C-3)

`show create table`과 `select * from db_class`는 REPLICATION ON/OFF만 보여줄 뿐, PK/UK가 여럿일 때 엔진이 실제로 무엇을 RK로 골랐는지는 출력하지 않는다. RK는 사용자가 수정할 수 없고 자동으로 바뀔 수도 있는 값인데(이슈 1) 결과를 확인할 수단이 없다. 그 결과 사용자는 §4-2 제약(RK로 쓰이는 UK는 삭제 불가 등)에 걸릴지를 **DDL을 실행해 에러가 나야만** 알게 된다. 더구나 "현재 값"뿐 아니라 "변경 이력(언제, 무엇에서 무엇으로)"도 남지 않고, 표준 JDBC/ORM 경로로는 애초에 조회할 수 없다(도구 생태계 각도는 이슈 20 참조). 장애 디버깅·배포 사전검증·스키마 감사가 모두 이 정보에 의존한다.

- **관련 스펙**: §2-3 (예시 8·9)
- **예제**
  ```sql
  CREATE TABLE t(a INT NOT NULL UNIQUE, b INT NOT NULL UNIQUE);  -- PK 없음, UK 2개
  show create table t;     -- 'REPLICATION ON'만. a와 b 중 무엇이 RK인지 안 나옴
  select * from db_class where class_name='t';   -- replication: ON 만 있음
  ```
- **코드 대조 — 확정**: `show create table`은 REPLICATION=ON/OFF만 출력(`object_printer.cpp` describe_class), `db_class` 뷰는 boolean `is_replication_class`(YES/NO)만 추가. PK/UK 여러 개일 때 실제 고른 RK 제약명·컬럼을 노출하는 카탈로그/뷰는 없다. (근거: `src/object/object_printer.cpp:1134+`, `src/object/schema_system_catalog_install_query_spec.cpp`)
- **권고**: `db_class`(또는 신규 시스템 뷰 `db_replication_key`)에 RK 제약명·컬럼 목록·RK 후보 개수 컬럼을 추가하고, `show create table` 출력에도 `REPLICATION ON (RK: pk_t_a)` 형태로 표기. 가능하면 RK 변경 이력도 남긴다.

### 6. §7 위반 리포트("파일 리스트")의 정체·포맷·exit code (원 C-4)

스펙 §7은 "제약사항 위반 시 에러와 함께 파일 리스트를 출력한다"고만 적는다. "파일"이 위반 테이블 목록인지 OS 경로인지 로그 파일인지 불명확하고(CUBRID에서 위반 단위는 테이블이지 파일이 아님), 출력 매체·위반 사유 구분(RK 없음 vs FK)·개수 제한·exit code가 정의되지 않았다. 추가로 실패 후 DB가 어떤 상태로 남는지, 위반이 클라이언트 화면 밖 서버 에러 로그에도 남는지, 위반 유형별 해결 절차가 나뉘는지도 없다.

- **관련 스펙**: §7
- **예제**
  ```bash
  $ cubrid hb start testdb
  ERROR: replication constraint violation
  tbl_a
  tbl_b
  $ echo $?   # 0인가 1인가? 스펙 미정의면 HA가 안 떴는데 트래픽이 전환되는 사고 가능
  ```
- **코드 대조 — 기각**: 스펙의 '파일 리스트'는 로그 디렉토리의 `<db>_rkcheck_YYYYMMDD_HHMM.list` 파일로 구현됨 — RK/FK 섹션 분리, 위반 테이블명 나열, HOW TO FIX 포함, stdout에는 카운트, 위반 시 -1378 반환 + `hb start` 중단(트래픽 전환 방지). 정체·포맷·매체·RK/FK 구분·실패 신호가 모두 코드에 정의됨. (exit code가 음수 에러 상수 그대로라 `EXIT_FAILURE` 정규화 여부만 사소한 코드리뷰 여지.) (근거: `src/executables/util_cs.c:3267`(rkcheck), `:2856`, `:2903`, `:3365`, `:3387-3388`; `src/base/error_code.h:1771`(-1378); `src/executables/util_service.c:3969`) — 코드는 스펙을 초과하나, 스펙 문서 자체는 여전히 이 출력 계약을 명문화해야 한다.
- **권고**: "파일 리스트"→"위반 테이블 목록(스키마.테이블명 + 위반 사유 코드)"으로 정정하고, 기계 판독 가능한 포맷·실패 시 비정상 exit code·실패 후 DB 상태를 스펙에 명시.

### 7. Failover / switchover / failback가 §7 검증을 우회한다 (원 2C-2)

§7 검사는 "HA 실행 시"(=`cubrid hb start`)에만 걸린다. 그런데 실제로 마스터가 바뀌는 가장 흔한 사건은 재기동이 아니라 **failover**(슬레이브가 마스터로 승격)이며, 이는 `hb start`가 아니라 이미 떠 있는 프로세스의 역할 전환이라 §7이 재실행되지 않는다. 운영 중 어떤 경로로든(예: 이슈 2의 NOT NULL 해제) RK를 잃은 테이블이 있으면, failover 직후 새 마스터가 검증 없이 쓰기를 받아 배경 버그가 즉시 재현된다. 장애 복구된 구 마스터가 재합류하는 **failback** 시 여러 번 바뀐 RK 이력을 순서대로 재생하는지도 미정의다.

- **관련 스펙**: §7, §1(HA 모드 정의)
- **시나리오**
  ```
  정상 HA 운영 중 order_items가 RK 후보를 모두 잃음(§7은 시작 시점에만 검사)
  → 마스터 하드웨어 장애 → 슬레이브 승격(hb start 아님, §7 미적용)
  → 새 마스터가 RK 없는 상태로 쓰기 수신 → 복제 누락 + fail_count 재현
  ```
- **코드 대조 — 확정**: rkcheck가 `cubrid hb start` CLI 경로에서만 실행되고, 실제 마스터가 바뀌는 failover/switchover/failback(하트비트 역할 전환) 경로에는 재검증 코드가 전혀 없다. 전 트리 grep 결과 rkcheck/check_repl_constraint/check_ha_repl_constraint 참조가 `util_cs.c`·`util_service.c`(CLI start)·`execute_schema.c`(DDL 시점, HA_DISABLED 가드)에만 존재하고 heartbeat/승격 경로엔 전무. (근거: `src/executables/util_service.c:3969`)
- **권고**: §7 검증 대상을 "마스터 역할을 맡는 모든 시점(failover·switchover·failback 포함)"으로 확장. 승격 전 검증 실패 시 그 노드로의 승격 거부 또는 즉시 경고. failback catch-up 시 RK 전환 로그를 중간 상태 건너뛰지 않고 순서대로 재생.

### 8. §8 vs §9 기본값 정면 모순 (원 C-5)

- §8: "복제 여부를 저장하는 변수가 설정되어 있지 않다면 **복제 대상(Default)**으로 간주" + "하위 버전 unload 파일은 load 시 **모두 복제 테이블로** 설정"
- §9: "UNLOADDB 시 … 이를 포함하지 않는 테이블은 **모두 복제 제외 테이블**이다"

같은 조건에 정반대 결과다. 이 한 곳 때문에 구버전→신버전 업그레이드 결과가 "전부 복제됨" 또는 "전부 복제 안 됨"으로 갈리며, 둘 다 이 기능이 막으려던 사고와 같은 종류다.

- **관련 스펙**: §8, §9
- **코드 대조 — 코드무관**: 자기모순은 순수 문서 결함이라 코드 대조로 해소 불가. 다만 코드는 default=ON으로 확정 구현(REPLICATION 절 미지정 시 `IS_CREATE_STMT_SET_REPL_OPTION`이 ON 반환, bare `REPLICATION`도 ON)하므로 **§8이 맞고 §9의 '모두 복제 제외'가 오기**다. 또 신버전 unloaddb는 항상 REPLICATION=ON/OFF를 명시 출력하므로 '미표시' 케이스는 구버전 파일에만 발생한다. (근거: `src/query/execute_schema.c:96-97`; `src/parser/csql_grammar.y:19990`; `src/executables/unload_schema.c:1796-1800`)
- **권고**: §9를 ON으로 통일하고, "기본값 정책"을 §1의 표 하나에만 정의한 뒤 §8/§9는 참조만 하도록 단일 출처화.

### 9. 기존 클러스터 업그레이드 / 롤링 업그레이드 / 카탈로그 마이그레이션 경로 부재 (원 C-6)

스펙은 "기능이 켜진 뒤"만 기술하고 도입 과도기를 다루지 않는다. (a) in-place 업그레이드 시 `db_class`에 새로 생기는 replication 컬럼을 무엇으로 채우는지, (b) 롤링 업그레이드에서 신버전 마스터가 만든 `REPLICATION=OFF` DDL을 구버전 슬레이브가 어떻게 파싱하는지(파싱 실패 → fail_count 증가 = 원래 버그 재발), (c) 업그레이드 직후 RK 없는 테이블 때문에 `cubrid hb start`가 기동을 거부하기 전에 **사전에** 점검할 방법이 있는지가 비어 있다.

- **관련 스펙**: 스펙 전체(특히 §7, §8)
- **시나리오**
  ```
  1. 구버전 HA 운영 중, orders는 PK 없이 운영(구버전은 허용, 복제만 누락)
  2. 신버전 바이너리로 교체 후 cubrid hb start
  3. §7 규칙에 걸려 HA 기동 거부 → 이미 서비스 중단된 뒤에야 문제를 앎
  ```
- **코드 대조 — 기각(부분)**: 이슈 핵심 통증인 'HA 기동 전 사전 점검 도구 없음'은 rkcheck(`cubrid rkcheck <db>` / `cubrid hb rkcheck`)로 반박됨 — 스테이징에 마이그레이션을 적용한 뒤 운영 전에 RK 없는 복제 테이블을 잡을 수 있다. 다만 (a) in-place 카탈로그 마이그레이션·(b) 롤링 업그레이드 호환 정책은 이 커밋에 미구현이며, 이는 스펙 업그레이드 절 부재라는 문서성 갭이다. (근거: `src/executables/util_admin.c:1023`; `src/executables/util_cs.c:3267`; `src/executables/util_service.c:3194/5042`)
- **권고**: 업그레이드 전용 절 신설 — in-place 시 카탈로그 마이그레이션 규칙("기존 테이블은 모두 ON으로 간주"), 롤링 업그레이드 호환 정책(또는 "마스터/슬레이브 동시 교체 필수" 명시), HA 기동 전 사전 점검 절차(rkcheck)를 문서화.

### 10. 복합 ALTER(예시 13)의 원자성·중간 상태·동시 DML 처리 (원 C-7)

예시 13(`DROP CONSTRAINT PRIMARY KEY, ADD CONSTRAINT PRIMARY KEY(a)`)은 "OK"만 보여준다. 그런데 이 문장이 원자적인지, DROP 후 ADD 사이에 "RK 0개" 상태를 거치는지, 그 찰나에 동시 세션 DML이 어느 RK 기준으로 기록되는지, ADD 실패 시 DROP까지 롤백되는지가 전혀 없다. 절 단위 순차 검증이라면 DROP 직후 RK 0개가 되어 예시 13은 항상 실패해야 하는데 스펙은 OK라고 한다 — "문장 전체 최종 상태 기준 검증 + 원자성"을 전제해야만 예시 13이 성립하는데, 그 전제가 문서에 없다. 두 개의 독립 트랜잭션이 각자 "다른 후보 있음"으로 통과하지만 합쳐지면 RK 0개가 되는 TOCTOU 경쟁, 단일 ALTER의 암묵적 다단계 내부 구현이 RK 0개 구간을 거치는 경우도 같은 뿌리다.

- **관련 스펙**: §2-2 예시 7, §4-2 예시 13
- **코드 대조 — 기각**: 다중 절 ALTER는 MULTIPLE_ALTER 세이브포인트로 감싸(`:1844`) 실패 시 전체 롤백하고(`:2080`), RK 제약 검사는 모든 절 처리가 끝난 뒤 최종 상태 기준으로 1회 수행(`:2051-2068`)하므로 DROP PK + ADD PK(a)는 중간 RK 0개 상태로 실패하지 않고 최종 상태로 검증된다. 원자성·롤백·최종상태검증이 구현되어 예시 13의 모순이 해소됨(스펙 문서만 미기술). (근거: `src/query/execute_schema.c:1844,2051-2068,2080`)
- **권고**: "쉼표로 연결된 다중 ALTER 절은 하나의 원자적 트랜잭션·단일 복제 로그 레코드로 처리하며, 최종 상태 기준으로 RK 제약을 검증하고, 일부 절 실패 시 전체 롤백한다. RK 변경 DDL은 테이블 배타 스키마 잠금을 잡아 동시 DML을 대기시킨다"를 §4-2에 명시(코드 동작을 스펙에 반영).

### 11. RK 전환 DDL과 복제 로그의 순서·정합성 (원 C-8)

복제 로그는 커밋 순서(LSA)대로 슬레이브에 적용되는데, RK를 바꾸는 DDL이 커밋되기 전 옛 RK 기준으로 기록된 DML 로그가 큐에 남아 있을 수 있다. DDL이 먼저 적용되어 슬레이브 카탈로그의 RK가 바뀐 뒤 옛 RK 기준 로그가 도착하면 applylogdb가 어떤 컬럼으로 대상 행을 찾을지 정의가 없다. 복제 로그가 RK를 컬럼 참조로만 담는지, 값 스냅샷·스키마 버전 태그를 함께 담는지도 불명확하다.

- **관련 스펙**: §4-2, 복제 로그 포맷
- **예제**
  ```
  T1(마스터): UPDATE tbl SET c=100 WHERE a=5;   -- RK=a 기준 로그
  T2(마스터): ALTER … RK를 a→a2로 교체
  슬레이브: (1) ALTER 먼저 적용(RK=a2) → (2) "a=5" UPDATE 뒤늦게 도착 → 어떻게 처리?
  ```
- **코드 대조 — 기각**: 슬레이브는 LOG COMMIT 시점에 커밋(LSA)순으로 단일 스레드 직렬 적용하므로 나중 커밋 T2가 먼저 커밋 T1보다 먼저 적용되는 재정렬 자체가 발생하지 않는다. 또한 복제 로그는 RK 컬럼 참조가 아니라 갱신 전 RK 값 스냅샷(`repl_old_key`)을 담는다. 배리어 우려는 커밋순 직렬 적용으로 이미 충족된다(병렬 적용은 본 브랜치 밖). (근거: `src/transaction/log_applier.c:2880-2886,5788`; `src/transaction/locator_sr.c:8757-8783`)
- **권고**: 문서에는 "복제 로그는 커밋(LSA) 순으로 직렬 적용되며 갱신 전 RK 값 스냅샷을 담는다"는 현재 보장을 명시. 병렬 적용을 도입하는 후속 설계에서는 RK 변경 DDL을 배리어로 취급하고 RK 스키마 버전을 로그에 함께 기록하는 규칙을 다시 세울 것.

### 12. REPLICATION=OFF 테이블의 DDL 복제 실패가 fail_count를 새 경로로 재현 (원 2C-6)

§1의 면책은 "데이터 불일치"에 대한 것이고, §4는 "DDL은 REPLICATION 여부와 무관하게 항상 복제·적용되어야 한다"고 한다. 그런데 OFF 테이블은 슬레이브 데이터가 마스터와 다른 것이 허용된 상태이므로, 그 어긋난 데이터 위에서 제약 추가 DDL을 실행하면 마스터에선 성공한 DDL이 슬레이브에선 실패한다 = applylogdb 실패, fail_count 증가, HA 정지. 이 스펙이 새로 만든 OFF 기능 자체가 원래 고치려던 버그의 새 발생 경로다.

- **관련 스펙**: §4(DDL은 항상 복제), §1(OFF 데이터 불일치 면책)
- **예제**
  ```sql
  -- customers: REPLICATION=OFF, 슬레이브는 OFF 전환 시점 스냅샷(country 중복 잔존)
  ALTER TABLE customers ADD CONSTRAINT UNIQUE(country);  -- 마스터 성공(중복 없음)
  -- §4대로 슬레이브 재생 → 슬레이브엔 country 중복 → UNIQUE 위반 실패 → fail_count↑
  ```
- **코드 대조 — 확정**: DML 복제는 `heap_is_replication_class`로 OFF 테이블을 skip하지만, DDL(SBR) 복제 경로는 테이블 REPLICATION 여부와 무관하게 무조건 복제·재실행한다. OFF 테이블 DDL 적용 실패를 격리/무시하는 경로가 코드에 없어 fail_count 증가·HA 정지를 막지 못한다. (근거: `src/query/execute_statement.c:16514-16517`, `:395`)
- **권고**: OFF 테이블에 대한 DDL 적용 실패 시의 동작을 정의(그 테이블에 한해 DDL 실패를 격리/무시하는 모드 등)하거나, "OFF 테이블도 DDL 실패는 여전히 HA를 정지시킨다"는 위험을 명시하고 운영 가이드 제공.

### 13. loaddb의 "스키마→데이터→인덱스" 단계적 파이프라인 × §4-1 (원 2C-3)

unloaddb/loaddb는 성능을 위해 (1) 제약 없는 빈 테이블 생성 → (2) 인덱스 없이 대량 적재 → (3) 이후 PK/UK·인덱스 추가 순으로 스키마를 재현한다. (1)단계는 정확히 "RK 후보가 하나도 없는 테이블"이다. §4-1("HA 모드에서 RK 없는 복제 테이블 생성 금지")을 그대로 적용하면 이 표준 복원 절차가 1단계에서 막히고, 반대로 loaddb가 파서를 거치지 않아 검증을 건너뛰면 csql로는 못 만드는 "RK 없는 복제 테이블"을 심는 뒷문이 된다.

- **관련 스펙**: §8, §4-1
- **코드 대조 — 기각**: 코드가 loaddb×HA 상호작용을 명시 처리한다. 갈래 A(HA 중 복원 불가) 기각 — SA-mode에서 ha_mode가 off로 강제돼 CREATE 시점 RK 검사가 no-op이므로 표준 단계 복원이 오프라인으로 완주한다. 갈래 B(살아있는 HA에 조용히 심는 뒷문) 기각 — CS-mode+HA는 스키마 로딩 자체를 막고 SA-mode는 라이브 HA가 아니다. 잔여(스키마-only/부분 로드로 RK 없는 ON 테이블이 무경고 생성)는 §7 rkcheck가 백스톱. (근거: `src/loaddb/load_db.c:191-204`; `src/base/system_parameter.c:10070-10075`; `src/query/execute_schema.c:9861-9871`)
- **권고**: 문서에는 loaddb가 §4-1과 동일 검증 경로/오프라인 처리를 공유함을 §8에 명시하고, RK 후보 없는 ON 테이블을 만났을 때의 처리(실패/경고/OFF 강등)를 규정.

### 14. TDE 암호화 테이블 × RK/복제 로그 상호작용 (원 2C-7)

`db_class`에 `tde_algorithm`이 이미 있는데도 본문은 TDE를 한 마디도 안 한다. 두 갈래 위험이 겹친다. **(정합성)** 마스터/슬레이브가 서로 다른 TDE 키를 쓰면 슬레이브가 RK 값으로 행을 찾지 못하거나 적용 실패. **(보안)** RK 값·복제 로그가 평문으로 실리면, 디스크는 암호화했는데 복제 로그 파일과 네트워크 전송 구간에서 평문이 새어 TDE 도입 취지가 무력화된다.

- **관련 스펙**: §2-3 예시 9의 `tde_algorithm` 필드, §1
- **예제**
  ```sql
  CREATE TABLE payment_cards (card_number CHAR(16) NOT NULL UNIQUE, holder VARCHAR(50))
    /* TDE 적용 */ REPLICATION=ON;   -- RK = card_number(암호화 대상)
  -- 복제 로그에 card_number가 평문인가 암호문인가? 슬레이브 키가 다르면 매칭되는가?
  ```
- **코드 대조 — 판정불가(런타임 필요)**: 정합성 갈래는 전제가 약하다 — TDE는 페이지 단위 투명 암호화라 행 매칭은 복호된 인메모리 값으로 수행되고 키는 노드별 로컬이 정상이다. 보안 갈래는 replication-log TDE가 `UNSTABLE_TDE_FOR_REPLICATION_LOG` 매크로 뒤에 컴파일아웃되어 정적으로 평문 노출을 확정할 수 없다. (근거: `src/transaction/log_applier.c:1047-1057`; 기능 커밋 8bb304290에 TDE×복제 처리 코드 전무) **필요한 확인**: 2노드 HA + TDE 암호화 REPLICATION=ON 테이블(노드별 TDE 키 분리)에서 (a) DML이 정상 복제·매칭되는지, (b) 슬레이브로 전송·적재된 복제 로그 파일·네트워크 캡처에 RK 값이 평문으로 남는지.
- **권고**: 복제 로그가 논리(평문) 레벨에서 생성됨을 명시하고 마스터/슬레이브 TDE 키 공유·로테이션 정책, 전송 구간 암호화(TLS 등) 강제 여부를 규정. 불가하면 "TDE 테이블 복제는 이번 릴리스 검증 범위 밖"이라고 최소한 스코프 선언.

---

## 중요 (Major)

### 15. 뷰(§6)와 FK(§5)의 검증 강도 불일치 — VIEW는 경고조차 없음 (원 M-2)

동일한 근본 위험("복제 제외 테이블의 부재 데이터에 의존")인데 FK는 생성 시점 하드 에러로 막고, VIEW는 아무 검사 없이 통과시킨 뒤 "책임지지 않는다"로 끝낸다. VIEW는 SQL 에러도 없이 failover 후 "조용히 축소된 결과"(예: LEFT JOIN에서 country가 전부 NULL)를 반환해 오히려 더 위험하다 — 리포팅·대시보드가 잘못된 숫자를 보여준다.

- **관련 스펙**: §5, §6
- **코드 대조 — 확정**: CREATE VIEW(`PT_VCLASS`) 경로에는 복제 검사 호출이 전혀 없다(`check_ha_repl_constraint`는 `PT_CLASS` 브랜치에서만 호출). HA 기동 rkcheck도 vclass를 명시적으로 skip한다(CBRD-26607). REPLICATION=OFF 테이블을 참조하는 뷰는 생성/기동 어느 시점에도 경고·에러가 없다. (근거: `src/query/execute_schema.c:10188-10209,10267-10274`; `src/executables/util_cs.c:2943`)
- **권고**: 최소한 `CREATE/ALTER VIEW` 시 복제 제외 테이블 참조를 감지해 WARNING 출력. FK와 정책 차이가 의도라면 근거를 문서화.

### 16. LIKE / CTAS / RENAME(그림자 스왑)에서 REPLICATION·RK 승계 미정의 + §5 우회 (원 2M-6)

`CREATE TABLE … LIKE`/`AS SELECT` 사본이 원본의 REPLICATION을 상속하는지가 스펙에 없다. 더 심각한 것은 **RENAME 기반 그림자 스왑**(무중단 스키마 변경의 표준 기법): OFF로 만든 그림자 테이블을 운영 이름으로 RENAME하면 REPLICATION=OFF가 그대로 승계되어 조용히 복제가 끊기거나, RENAME이 §5 FK 검증을 재실행하지 않아 이슈 4의 "복제 대상이 복제 제외를 참조" 상황이 ALTER 없이 재현된다.

- **관련 스펙**: §2-1, §5
- **시나리오**: 그림자 테이블 orders_new(REPLICATION=OFF)에 데이터를 채운 뒤 운영 이름 orders로 RENAME → orders가 OFF를 승계해 복제가 조용히 끊기고, 애플리케이션은 평소처럼 쓰지만 슬레이브에 반영되지 않다가 failover 후 스왑 이후 주문이 통째로 사라진 것을 발견.
- **코드 대조 — 확정(RENAME) / 기각(LIKE·CTAS)**: 순수 RENAME은 `alter.code=PT_RENAME_ENTITY`인데 `IS_REPL_CONSTRAINT_RELATED_ALTER`에 이 코드가 없어 `check_ha_repl_constraint` 재검증이 실행되지 않는다 → 그림자 스왑이 DDL 시점 재검증 없이 통과(HA 기동 rkcheck까지 미탐). 단 LIKE는 원본 REPLICATION 상속이 구현됐고(`:10258-10261`), CTAS 기본 ON은 RK 검사(`:10267`)로 RK 없는 복제 대상 생성을 차단하므로 이 둘은 기각. (근거: `src/query/execute_schema.c:109-114, 2051-2059`)
- **권고**: LIKE/CTAS/RENAME의 REPLICATION·RK 승계 규칙을 명문화하고, RENAME 시 §5·§7과 동일한 FK/REPLICATION 정합성 재검증을 트리거.

### 17. 온라인/비활성/필터/함수 기반 UNIQUE 인덱스가 RK 후보 판정을 흔든다 (원 2M-8)

RK 후보를 "카탈로그에 UNIQUE가 있는가"로만 판정하면: 온라인 빌드 중(유일성 검증 미완)인 UK를 근거로 진짜 RK를 지우는 DDL이 통과했다가 빌드 실패 시 RK 0개; soft-delete용 필터드 부분 UNIQUE(`WHERE deleted_at IS NULL`)는 삭제된 행끼리 값 중복 가능한데 표면상 "NOT NULL UNIQUE" 충족; 함수 기반 UNIQUE(`LOWER(email)`)는 로그에 원본값/계산값 중 무엇을 실을지 미정의.

- **관련 스펙**: §1, §4-2
- **코드 대조 — 확정**: RK 후보 판정이 `type==PK` 또는 `type==UNIQUE + 전 컬럼 NOT NULL`만 검사하고, `OR_INDEX`의 `filter_predicate`(필터/부분 UNIQUE)·`func_index_info`(함수기반)·인덱스 빌드 상태를 전혀 확인하지 않는다. 필터/함수 기반 UNIQUE가 NOT NULL이면 그대로 RK 후보로 인정된다. (근거: `src/base/object_representation_sr.c:4694-4722`, `..._sr.h:187-188`)
- **권고**: RK 후보를 "빌드 완료·검증 끝난, 필터 없는, 실제 저장 컬럼 값 기반 완전 UNIQUE"로 한정. 온라인 빌드 중 UK를 근거로 한 RK 제거 DDL은 대기/거부.

### 18. ADD PRIMARY KEY 한 줄이 무경고로 RK를 UK→PK로 재할당 (원 2M-12)

UK가 RK인 테이블에 PK를 추가하면(예시 14: OK) §1의 "PK 우선" 규칙에 의해 RK가 즉시 새 PK로 조용히 넘어간다. "사용자는 RK를 직접 수정할 수 없다"는 §4-2 원칙이 무색해지고, 로그 볼륨(단일→복합)도 변하며 email 기준 외부 연동이 조용히 깨질 수 있다.

- **관련 스펙**: §1(PK 우선), §4-2 예시 14
- **코드 대조 — 확정**: 인덱스 배열이 PK 패밀리를 UNIQUE보다 먼저 채우고 RK 선택은 배열 순 첫 후보를 취하므로 PK가 실질 우선. NOT NULL UNIQUE가 RK이던 테이블에 ADD PRIMARY KEY 하면 classrepr 재구성 시 RK가 조용히 새 PK로 넘어간다. RK 변경을 알리는 NOTICE/WARNING은 전무(추가된 메시지는 에러 1375~1377뿐). (근거: `src/base/object_representation_sr.c:2322-2328`, `src/storage/btree.c:8285-8298`)
- **권고**: PK 추가로 RK가 대체되면 무경고 OK 대신 "RK가 X에서 Y로 변경됨" NOTICE/WARNING을 반환하도록 §4-2에 명시.

### 19. §4-2 "복제키 후보" 용어 미정의 + "모든 DDL 허용"이 예시 12와 모순 (원 M-1)

§1은 단수 "복제 키"만 설명하다가 §4-2에서 갑자기 "복제키 후보"를 정의 없이 쓴다. "후보 = PK 하나 + 모든 UK"인지 "현재 RK를 제외한 나머지"인지 불명확해 카운팅 로직을 구현할 수 없다. 본문 "다른 복제키 후보가 함께 존재한다면 모든 DDL은 허용된다"와 예시 12("PK가 복제키면 무조건 삭제 불가")가 PK+UK 공존 테이블에서 정반대 결론을 낸다.

- **관련 스펙**: §4-2
- **코드 대조 — 코드무관**: 용어 미정의·본문vs예시12 모순은 스펙 문서 결함이라 코드 대조로 해소 불가. 참고로 코드는 구체 규칙을 구현(`IS_HA_REPLICATION_KEY_CONSTRAINT` = PK 또는 NOT NULL UNIQUE 존재)하며, 다른 RK 후보가 있으면 DROP PK를 허용해 본문 해석을 따르므로 예시 12와 배치된다. (근거: `src/object/class_object.c:95-98,2279-2290`)
- **권고**: §1에 "복제키 후보"를 정식 정의하고, "검증은 문장 전체 적용 후 최종 상태 기준"임을 명시, 예시 11~16 각각에 "이 테이블은 후보 N개" 전제를 표기.

### 20. 도구 생태계(표준 메타데이터·JDBC·ORM·스키마 diff)에 RK·REPLICATION 미노출 (원 2M-5)

조회 수단이 CUBRID 전용(`show create table`, `db_class`)뿐이라 표준 경로로는 안 보인다. 결과: Liquibase/Flyway 스키마 diff가 REPLICATION 차이를 못 잡아 드리프트 사각지대; ORM 자동 스키마 동기화(`hbm2ddl=update`)가 REPLICATION 옵션을 몰라 DBA가 건 OFF를 배포마다 조용히 ON으로 되돌림; jOOQ/MyBatis Generator가 표준 `DatabaseMetaData`로는 RK를 알 수 없음. 이슈 5(사람이 조회 불가)와 달리 여기는 **도구가 자동으로 소비하는 경로**의 부재다.

- **관련 스펙**: §2-3
- **시나리오**: DBA가 규제상 customers를 REPLICATION=OFF로 둠 → 다음 배포에서 ORM이 옵션 생략 CREATE/ALTER를 내면 기본값 ON으로 되돌아감 → 표준 diff·JDBC 메타데이터로는 보이지 않아 감지 실패 → 슬레이브로 내보내면 안 되는 데이터가 규제를 위반한 채 복제.
- **코드 대조 — 확정**: REPLICATION 노출은 CUBRID 전용 표면 2곳뿐(SHOW CREATE TABLE, `db_class.is_replication_class`). JDBC DatabaseMetaData를 받치는 CCI/CAS schema-info 레이어(`src/broker/`)는 기능 커밋이 한 파일도 변경하지 않아 표준 경로로는 보이지 않고, RK는 어디에도 노출되지 않는다. 옵션 생략 시 기본 ON이라 ORM 재생성의 조용한 OFF→ON 되돌림 경로도 실재. (근거: `object_printer.cpp` describe_class; `schema_system_catalog_install.cpp:1313`; `csql_grammar.y:19990`)
- **권고**: REPLICATION·RK를 표준 메타데이터 뷰/JDBC 확장에 노출. REPLICATION 걸린 테이블은 ORM 자동 동기화·자동 롤백 대상에서 제외하도록 가이드. `show create table` 출력 포맷 변경을 "인터페이스 변경"으로 릴리스 노트에 명시.

### 21. REPLICATION 변경 권한·감사(audit) 모델 전무 (원 2M-1)

`ALTER TABLE … REPLICATION=OFF`를 누가 실행할 수 있는지 스펙에 한 줄도 없다. 일반 ALTER 권한(테이블 소유자)만으로 가능하다면 애플리케이션 계정이 승인 없이 DR 보장 범위를 바꾸고 다른 테이블의 FK 무결성(이슈 4)까지 흔들 수 있다. 부작용이 즉시 안 보이고(다음 failover까지) 변경 이력을 조회할 표준 수단도 없어, 금융·의료 컴플라이언스 심사에서 바로 걸린다.

- **관련 스펙**: §2-2, 예시 9의 `owner_name`
- **코드 대조 — 확정**: `do_alter_change_replication`에는 REPLICATION 전용 권한 검사도, 변경 이력 감사 로그도 없다 — 일반 ALTER 권한만으로 SA 모드에서 변경 가능. 단 중요한 완화: `!HA_DISABLED()` 게이트로 HA 운영 중에는 변경이 거부되므로, app_user가 HA 가동 중 즉시 마스터 복제 범위를 바꾸는 온라인 시나리오는 불가. 거버넌스 공백(권한 분리·감사)은 유효. (근거: `src/query/execute_schema.c:11730-11840`)
- **권고**: REPLICATION 변경을 일반 ALTER와 분리된 권한(DBA 또는 신규 REPLICATION 권한)으로 제한하거나 최소한 변경 이력(계정·시각·이전/이후 값)을 감사 로그·카탈로그에 기록.

### 22. 다단계/자기참조/순환 FK, 복합키 RK, FK-UK 겸용 컬럼의 검증 규칙 부재 (원 M-8)

§5는 "직접 참조 1단계"만 다룬다. A→B→C 체인에서 C가 OFF일 때 전이 검사하는지, 자기참조(`employee.manager_id→employee`)나 순환 FK를 어떻게 다루는지 없다. FK이면서 동시에 유일 UK인 컬럼 삭제 시 예시 22(허용)와 예시 15(금지)의 우선순위도 미정.

- **관련 스펙**: §5, §4-2
- **코드 대조 — 기각**: FK 참조 검사(`check_ha_repl_fk_ref_all_replicated`)는 테이블별 직접 엣지 검사이고, HA 기동 rkcheck가 전 클래스 순회하므로 A→B→C 체인도 각 엣지가 개별 검사돼 전이 재귀 불필요·자기참조도 정상 처리. RK-UK 겸용 컬럼 삭제는 `PT_DROP_ATTR_MTHD`가 게이트에 포함돼 삭제 후 RK 재검사로 우선순위 해소. (근거: `src/query/execute_schema.c:9789-9800,109-114,2051`; `src/executables/util_cs.c:3322,3349`)
- **권고**: 코드가 처리하는 재귀 검사 범위·자기참조/순환 처리·다중역할 컬럼 우선순위를 스펙에 명문화하고 각 예제 추가.

### 23. FK 참조 액션(ON DELETE/UPDATE CASCADE 등)의 복제 처리 미정의 (원 2M-7)

부모 삭제·갱신이 CASCADE로 자식에 연쇄 DML을 일으킬 때, 복제 로그에 (a) 부모 변경 1건만 남고 슬레이브가 자신의 CASCADE로 재현하는지, (b) 마스터가 자식 변경까지 개별 행 로그로 펼쳐 보내는지 미정의. (a)면 슬레이브 제약이 어긋나 있을 때 불일치.

- **관련 스펙**: §5 (CASCADE/SET NULL 언급 없음)
- **코드 대조 — 기각**: 과거 '순서 보존 로직이 PK 전용'이라는 흔적은 이 커밋에서 `rk_btid_index`로 일반화되어(PK/UK 불문 현재 RK) 해소됨. CASCADE 연쇄 DML은 행 기반으로 각 행이 개별 복제되어 슬레이브가 cascade를 재실행하지 않는다(스펙의 (b) 동작이 실제). (근거: `src/transaction/locator_sr.c:8273,8421-8425,8731,8748,8042`)
- **권고**: 참조 액션 연쇄 DML은 마스터에서 개별 행 로그로 펼쳐 전달하고 슬레이브는 재실행하지 않음을 §5에 명시(코드 동작 반영).

### 24. collation 차이·변경이 RK 유일성·행 매칭을 흔든다 (이견 있음) (원 2M-11)

대소문자 무시 collation에서 `'ABC'`와 `'abc'`는 같은 값 → UK가 이 둘을 충돌로 볼 수 있고, RK 컬럼의 COLLATE를 사후 변경하면 기존 데이터가 새 규칙으로는 중복이 되어 유일성 전제가 깨진다는 지적. 반면 다수 페르소나는 "UNIQUE 제약 자체가 그 collation으로 유일성을 강제하고 DDL이 항상 복제되므로 실질 파손 경로가 없다"며 명시 제외했다.

- **관련 스펙**: §1, 예시 8 `COLLATE`
- **코드 대조 — 기각**: applylogdb 행 매칭은 RK 인덱스의 `btree_find_unique`로 이뤄져 컬럼 collation을 그대로 따르고, UNIQUE 제약이 해당 collation으로 유일성을 강제하며, collation 포함 스키마/DDL은 항상 복제되어 마스터·슬레이브 collation이 동일하게 유지된다 — '무영향' 제외 근거가 코드로 확인됨. (근거: `src/object/object_accessor.c:4215`; `src/object/class_object.h:312`)
- **권고**: 논쟁 종결을 위해 "RK 컬럼 COLLATE 변경 시 유일성 재검증"과 "applylogdb 매칭이 컬럼 collation을 따름"을 스펙에 못박아 둘 것.

### 25. 에러 메시지가 대부분 "ERROR"만 — 실제 문구·에러 코드 없음 (원 M-6)

예시 11만 실제 메시지를 보여주고 예시 5·10·12·15·16·18·22·23은 "ERROR"만 적혀 있다. 사용자는 무엇을 검색해야 할지 모르고, 자동화 파이프라인은 "RK 위반"과 "문법 오류"를 구분할 코드가 없다.

- **관련 스펙**: §4-2, §5 예시 다수
- **코드 대조 — 기각**: 코드는 이미 -1375~-1378 고유 에러코드 + 서술 메시지(RK 필요/옵션변경 금지/FK OFF 참조/HA 기동 위반건수)를 부여하며 `check_ha_repl_constraint`가 이를 raise한다. 자동화가 문법 오류와 구분 가능 — '구분할 코드가 없다'는 전제는 구현이 스펙을 초과해 성립하지 않음. (근거: `msg/en_US.utf8/cubrid.msg:1478-1484`; `src/base/error_code.h:1768-1771`)
- **권고**: 예시를 실제 문구로 통일하는 잔여 문서 개선. 모든 예시를 예시 11 수준으로.

### 26. 복제 제외 테이블 전수 조회 수단 + 업그레이드 후 대량 위반 일괄정비 도구 (원 M-7)

`show create table`/`db_class`는 테이블 하나씩만 조회한다는 우려. 구버전 백업 load 시 전 테이블이 ON으로 잡혀 HA 기동 시 수십~수백 개가 한꺼번에 위반될 때 일괄 정비 도구·목록이 필요하다.

- **관련 스펙**: §2-3, §7, §8
- **코드 대조 — 기각(부분)**: `db_class.is_replication_class` 컬럼으로 전 테이블 SQL 필터 조회가 가능하고, rkcheck가 전 클래스를 순회해 위반 목록 파일을 출력한다 — '전수 조회/위반 목록 수단 없음' 주장 반박. 잔여: 자동 일괄 정비(fix) 유틸은 없고 rkcheck는 리포트만 함. (근거: `schema_system_catalog_install_query_spec.cpp`; `src/executables/util_cs.c:2895-2945`)
- **권고**: 전수 조회 뷰·rkcheck 리포트는 이미 존재함을 문서화하고, RK 없는 ON 테이블 일괄 처리 유틸을 로드맵에 검토.

### 27. 개발/스테이징(싱글)에서 통과한 DDL이 운영(HA)에서만 실패 — dry-run 부재 (원 M-4)

§3은 싱글 모드에 RK 제약이 "없다"고 하고, 검사는 §7(HA 기동 시점)에만 걸린다. CI가 싱글 스테이징에서 통과시킨 마이그레이션이 운영 HA 배포 시점에 처음 실패한다(dev/prod parity 붕괴).

- **관련 스펙**: §3, §4, §7
- **예제**
  ```sql
  -- 로컬/스테이징(싱글): ALTER TABLE customers DROP CONSTRAINT u_customers_email;  → OK
  -- 운영(HA): 같은 문장 → ERROR (email UK가 유일 RK였다면, 예시 15)
  ```
- **코드 대조 — 기각**: 싱글 모드가 RK 검사를 건너뛴다는 전제는 코드로 확인되나(`HA_DISABLED` 가드, parity 갭 실재), 이슈가 요구한 사전점검(dry-run) 도구는 rkcheck로 존재 — 스테이징 DB에 마이그레이션 적용 후 `cubrid rkcheck`로 운영 전에 잡을 수 있다. '도구 부재' 주장이 거짓이라 기각. (근거: `src/query/execute_schema.c:9863`; `src/executables/util_cs.c:3267` + `util_admin.c:1023`)
- **권고**: 문서에 "싱글 통과 ≠ HA 통과"와 rkcheck를 사전점검 절차로 명시.

### 28. REPLICATION=OFF↔ON 전환 시 슬레이브 데이터 처리·재동기화 방침 없음 (원 M-5)

(a) ON→OFF 전환 시 슬레이브에 이미 쌓인 데이터가 삭제되는지 "박제된 옛 스냅샷"으로 남는지 없음(stale read 위험). (b) OFF→ON은 HA 중 금지인데, 그렇다면 그동안 마스터에만 쌓인 데이터를 슬레이브에 어떻게 최초 동기화하는지 절차가 없다. (c) 금지 근거가 명시되지 않아 의도된 제약인지 불명. RK 위반 하나를 고치려 HA 전체를 내려야 하는지, 문제 테이블만 OFF로 임시 격리 가능한지 §7이 대안을 안내하지 않는다는 지적도 있다.

- **관련 스펙**: §2-2, §4
- **예제**
  ```sql
  ALTER TABLE big_orders REPLICATION=OFF;  -- 한 달간 500만건 INSERT (슬레이브 미반영)
  ALTER TABLE big_orders REPLICATION=ON;   -- 예시5: HA에서 ERROR. 과거분은 영영 갭?
  ```
- **코드 대조 — 코드무관**: 전환 시 데이터 처리·재동기화 절차·금지 근거 문서화는 스펙/운영 문서가 채울 사항. 참고로 코드상 HA 중에는 OFF→ON뿐 아니라 ON→OFF까지 전면 금지되어, 'HA 중 전환 시나리오'는 이 경로로 발생하지 않음(전환은 HA 해제 상태에서만). (근거: `src/query/execute_schema.c:11740-11745`)
- **권고**: 전환 시 슬레이브 데이터 처리(유지/TRUNCATE)를 명시, OFF→ON 재동기화 공식 절차 제공, 금지 근거와 "문제 테이블만 격리" 가능 여부를 문서화.

### 29. REPLICATION=OFF의 로그 계층(마스터 생성 skip vs 슬레이브 필터) 미정의 (원 2M-2)

OFF 차단이 (a) 마스터가 애초에 복제 로그를 안 만드는지, (b) 로그는 다 만들되 전송 전 필터인지, (c) 슬레이브 적용 단계에서 버리는지 스펙에 없다. 사용자에게 보이는 결과는 같지만 네트워크 대역폭·슬레이브 디스크·복제 지연이 크게 갈린다.

- **관련 스펙**: §1, §4
- **코드 대조 — 기각**: 코드가 계층을 (a) 마스터 생성 skip으로 확정한다 — OFF 테이블은 마스터가 REPL 로그 레코드 생성 자체를 하지 않으며 슬레이브 필터가 아니다. 다만 copylogdb는 WAL 전체를 전송하므로 실제 대역폭 절감은 REPL 레코드/슬레이브 적용분에 한정되어 이슈의 '100배' 프레이밍은 부정확. (근거: `src/transaction/locator_sr.c:8041-8047,8421-8425`; `src/storage/heap_file.c:11075`)
- **권고**: OFF 테이블 변경분이 어디서 제외되는지(마스터 REPL 로그 생성 skip)와 copylogdb의 WAL 전송 특성을 §1/§4에 명시.

### 30. §7 검사 blast radius — 전체 vs 부분 기동, DB단위 vs 그룹, 검증 비용 (원 2M-3)

(1) 위반 발견 시 클러스터 전체가 안 뜨는지 위반 테이블만 제외하는지, (2) 한 서버의 여러 DB 중 하나만 위반해도 그룹 전체가 막히는지, (3) 수천~수만 테이블 전수 스캔이 failover 시간(RTO)에 얼마나 붙는지가 미정의.

- **관련 스펙**: §7
- **코드 대조 — 기각**: blast radius가 코드로 명확히 정의됨 — 위반 1건→해당 DB rkcheck 실패→`hb start` 전체 중단(all-or-nothing), 한 DB 실패가 그룹 전체 차단. 비용은 `hb start` 시 전 클래스 스캔(failover엔 미실행, 이슈 7 참조). (근거: `src/executables/util_service.c:3194,3969-3973`; `src/executables/util_cs.c:3387`)
- **권고**: 코드가 정한 실패 상태·적용 단위(all-or-nothing, DB별)·성능 특성을 스펙에 명시. 노드 간 카탈로그 불일치를 에러로 보고하는 정책도 명문화.

### 31. 물리 백업(backupdb/restoredb)·PITR와 REPLICATION 미정의 (원 2M-4)

실무 DR은 논리 백업(§8의 unloaddb)보다 물리 백업이 훨씬 흔한데 스펙이 침묵한다. PITR은 옛 시점의 REPLICATION 카탈로그 상태를 되살려 현재 클러스터와 어긋날 수 있고, 슬레이브에서 백업을 뜨면 OFF 테이블은 항상 빈 채로 백업된다.

- **관련 스펙**: §8 (unloaddb/loaddb만 다룸)
- **코드 대조 — 코드무관**: 물리 백업·PITR는 스펙에 없는 문서 스코프 이슈. 본 커밋은 백업/복원 코드를 손대지 않고, REPLICATION 값은 `_db_class` 카탈로그 SM_CLASS 플래그라 물리 백업은 페이지 단위로 그대로 보존하고 PITR은 카탈로그 DDL을 재생해 복원한다. (근거: 8bb304290 --stat; `src/object/class_object.h:312`)
- **권고**: §8을 "논리 백업 / 물리 백업"으로 나눠 각각의 REPLICATION·RK 저장·복원·마이그레이션 규칙을 명시. PITR 복구 후 REPLICATION 전수 점검을 절차화.

### 32. 여러 문장 DDL을 한 트랜잭션으로 묶었을 때 부분 실패·롤백 미정의 (원 2M-9)

마이그레이션 파일이 별도 문장 여러 개를 묶고 실행하다 중간 문장이 RK 위반으로 실패하는 경우. DDL이 암묵적 커밋이면 앞 문장은 확정되어 롤백해도 안 되돌아가고, 도구가 기록한 상태와 실제 DB가 어긋난다. (이슈 10의 "한 문장 안 다중 절"과 달리 "별도 문장 여러 개"다.)

- **관련 스펙**: §2, §4-2
- **코드 대조 — 코드무관**: 단일 문장 내 다중 절·엔진 내부 다단계는 세이브포인트로 원자 처리되고 각 문장은 최종 상태 RK 검사로 RK 0개 커밋을 막는다. 여러 '별도 문장'의 부분 실패·롤백은 클라이언트 autocommit 설정에 좌우되는 기존 CUBRID 트랜잭션 의미로 본 기능이 바꾼 게 아니다. (근거: `src/query/execute_schema.c:1844,2051-2068`)
- **권고**: DDL의 커밋 모델(암묵 커밋/트랜잭션 포함 여부)과 "RK 후보 판정은 문장 실행 전/후 최종 상태 기준"임을 스펙에 명시.

### 33. PostgreSQL REPLICA IDENTITY 대비 사용자 명시 지정·FULL 폴백 없음 (원 M-3)

PostgreSQL은 `DEFAULT`/`USING INDEX`/`FULL`/`NOTHING` 네 모드를 제공하는데, 이 스펙은 "엔진 자동 선택"만 채용하고 사용자 지정 수단을 뺐다. UK가 여럿일 때 안정적 키를 강제할 방법이 없고, PK/UK가 없으면 FULL 같은 "느려도 복제는 됨" 폴백 없이 오직 "복제 포기(OFF)"뿐이다.

- **관련 스펙**: 배경, §1
- **코드 대조 — 코드무관**: 문법상 REPLICATION은 ON/OFF 두 값뿐이며 USING INDEX 상당 구문이나 FULL 폴백은 없다(RK는 PK>UK 자동선택). 이는 의도적 설계 선택에 대한 로드맵·경쟁 포지셔닝 권고이지 코드 결함이 아니다. (근거: `src/parser/csql_grammar.y:19890-19998`)
- **권고**: 로드맵에 명시 지정 문법(`REPLICATION KEY USING (...)`) 검토를 명기하고, 이번 릴리스에서 폴백을 뺀 설계 근거를 스펙에 한 문단 추가.

### 34. 멀티 슬레이브·체인 복제 확장성 — 테이블 전역 플래그의 한계 (원 M-9)

REPLICATION은 테이블당 값 하나인 전역 속성이라 "슬레이브 A(DR)에는 전체, 슬레이브 B(분석용)에는 PII 제외" 같은 슬레이브별 차등 복제를 표현할 수 없다.

- **관련 스펙**: 컨셉 전체
- **코드 대조 — 코드무관**: 클래스 단위 단일 비트라 슬레이브별 차등 복제를 표현 못 하는 것은 코드상 사실이나, 스펙이 요구한 기능이 아니며 권고 자체가 'out-of-scope 명시'라는 문서 조치. (근거: `src/object/class_object.h:312`)
- **권고**: "이번 범위는 테이블 단위 전역 복제 여부만이며 슬레이브별 차등·컬럼 단위 필터는 out of scope"라고 스코프를 명시.

### 35. REPLICATION 옵션 변경의 락·성능 영향, in-place 여부 미정의 (원 M-10)

`ALTER TABLE … REPLICATION=OFF`가 메타데이터 전용 O(1)인지, 대용량 테이블에서 락을 얼마나 오래 잡는지 없다.

- **관련 스펙**: §2-2, §4
- **코드 대조 — 코드무관**: 옵션 변경은 `sm_set_class_flag` 메타데이터 전용 플래그 플립이며 heap 재구성·행 스캔이 없다(사실상 O(1)). 클래스 배타락만 잡는다. '대용량에서 락을 오래 잡는다'는 함의는 성립하지 않는다. (근거: `src/query/execute_schema.c:11730-11840`)
- **권고**: 옵션 변경이 메타데이터 전용임을 스펙에 명시.

### 36. RK 추가의 실제 비용 — 중복 데이터 정리·대용량 인덱스 락·클라이언트 타임아웃 (원 2M-14)

스펙은 "RK 없으면 ALTER로 추가하면 된다"고 한 줄로 넘기지만, PK 없이 오래 운영된 테이블엔 중복값이 쌓여 UNIQUE 추가가 실패하고, 수천만 건 테이블의 인덱스 생성은 장시간 락·JDBC socketTimeout 초과를 부른다.

- **관련 스펙**: §3, §7, §9
- **코드 대조 — 코드무관**: 중복 정리 선행·대용량 인덱스 락·타임아웃은 UNIQUE/PK 추가의 표준 CUBRID DDL 비용으로 본 기능이 새로 만든 동작이 아니다. 스펙에 비용 경고와 온라인 인덱스 지원 여부를 명시하라는 문서 개정 사안. (근거: 코드무관)
- **권고**: §7/§9에 "RK 추가는 데이터 정리 선행이 필요할 수 있고 테이블 크기에 비례하는 무거운 DDL"임을 경고. 사전 점검 시 위반 테이블 행 수 규모 제공, 온라인 인덱스 생성 지원 여부 명시.

### 37. 릴리스 거버넌스 메타데이터 부재 (버전·에디션·성숙도·백포트·킬스위치·다운그레이드) (원 2M-13)

적용 최소 버전·에디션(오픈소스/상용) 미표기, 성숙도 등급(GA/Beta) 미정, 배경 버그의 백포트 정책 부재, 문제 발생 시 검증을 한시 완화할 킬스위치·다운그레이드 경로 부재가 한 다발로 묶인다.

- **관련 스펙**: 문서 전체
- **코드 대조 — 코드무관**: 순수 릴리스 거버넌스 메타데이터. 킬스위치(RK 검증 한시 완화 파라미터)는 커밋에 없으나 스펙이 요구한 항목이 아니라 리뷰의 기능 권고. (근거: 코드무관)
- **권고**: 문서 서두에 적용 버전/에디션/타깃 릴리스/성숙도 등급을 명시. 카탈로그 스키마 변경과 다운그레이드 호환성, RK 검증 킬스위치 시스템 파라미터를 최소 한 릴리스 제공 검토.

---

## 보통 (Minor)

- **38. 예시 SQL trailing comma 문법 오류 (예시 2, 20, 23)** (원 N-1) — 예제가 실행 불가라 "RK 에러"인지 "문법 오류"인지 구분 못 함. **코드무관**: trailing comma는 실제 문법 오류가 맞다(`csql_grammar.y:9817-9828`에 trailing comma 생산규칙 없음). 전 예제를 실제 csql로 검증할 것.
- **39. 예시 7 "…" 템플릿 실행 불가 + 예시 13과 중복** (원 N-2) — **코드무관**(순수 문서 품질). 구체 SQL로 대체하거나 예시 13 참조.
- **40. 예시 10 테이블명 `repl_table_with_rk`가 내용(RK 없음)과 반대 + 예시 1과 이름 충돌** (원 N-3) — **코드무관**. 순차 실행 시 "이미 존재" 에러로 인과 뒤바뀜.
- **41. 예시 19/21 FK 자동 명명 규칙 미문서화** (원 N-4) — **코드무관**: 자동명명은 `fk_`+클래스명+`_`+컬럼명 규칙이라 `fk_new_orders_customer_id`는 규칙상 정확(`schema_manager.c:14414-14575`). 규칙을 스펙에 적을 것.
- **42. 예시 16 DROP INDEX가 UNIQUE/일반 인덱스 구분 없음** (원 N-5) — **코드무관**: 코드는 인덱스 종류가 아니라 연산 후 RK 후보 잔존 여부로만 판정하므로 일반 인덱스 DROP은 절대 막히지 않음. '일반 인덱스까지 차단' 오해는 문서 명확화 대상.
- **43. 예시 8 출력에 REUSE_OID/COLLATE 등 무관 키워드 각주 없음** (원 N-6) — **코드무관**(문서 가독성).
- **44. REPLICATION 표기 3종 혼용 + OFF일 때 `show create table` 예시 없음** (원 N-7) — **코드무관**: 실제 출력은 등호 포함 `REPLICATION=ON`이라 예시 8의 `REPLICATION ON`이 오히려 실동작과 불일치(`object_printer.cpp:1138-1144`). 표기 통일·OFF 예시 추가.
- **45. 컬럼 단위 복제 제외(PII 마스킹) 요구 미지원** (원 N-8) — **코드무관**: 복제 플래그가 테이블 단위라 미지원이 설계상 사실. out-of-scope 스코프 선언.
- **46. 읽기/쓰기 분리 아키텍처에서 OFF 테이블이 슬레이브로 라우팅되면 조용히 빈 결과** (원 N-9) — **코드무관**: OFF의 정의된 동작의 정상 귀결이자 애플리케이션 라우팅 문제. 운영 가이드로 안내.
- **47. FK 강제복제가 정적 코드 테이블 OFF 설계를 봉쇄** (원 N-10) — **코드무관**: `check_ha_repl_fk_ref_all_replicated`로 의도적으로 강제되는 무결성 우선 설계 트레이드오프. (상충 의견은 아래 참조.)
- **48. unload 파일 포맷 미명세 + 구버전 파서 전방호환** (원 N-12) — **코드무관(단 실재 갭)**: 포맷은 클래스별 CREATE TABLE 인라인 `REPLICATION=ON/OFF` 절(COLLATE 뒤·ENCRYPT 앞), 항상 명시(`unload_schema.c:1796-1800`). 다만 신규 문법 토큰에 버전 가드가 없어 구버전 loaddb가 신버전 unload 파일을 파싱하면 구문오류 — 실재하는 다운그레이드/전방호환 갭이니 포맷·버전정책을 스펙에 명시.
- **49. 클래스 상속(UNDER)과 REPLICATION/RK 상속 규칙 부재** (원 2m-1) — **확정**: `do_create_entity`의 is_replication_on이 create_like 소스이거나 옵션(미지정 시 default ON)로만 결정되고 super_class 플래그를 참조하지 않아, 부모 OFF + 자식 옵션 생략 시 자식이 default ON이 되는 반쪽 상태가 코드상 가능(`execute_schema.c:10258-10264`). 상속/독립 규칙 명시 또는 out-of-scope 선언.
- **50. 다중 스키마 FK 검증·소유자 교차 영향** (원 2m-3) — **확정(소유자 교차만)**: 동명이표는 FK가 OID 기반이라 비쟁점이나, 테이블을 OFF로 바꿀 때 `do_alter_change_replication`이 역방향(누가 나를 참조)·소유자 권한 경계를 전혀 보지 않고, `PT_CHANGE_REPLICATION`이 게이트에 없어 제약 재검증조차 트리거되지 않음(`execute_schema.c:11730,106-111`). alice가 자기 테이블을 OFF로 바꿔 bob의 FK를 깨는 교차 영향의 권한 경계 필요.
- **51. TRUNCATE 등 DDL/DML 경계 SQL의 분류 미정의** (원 2m-4) — **확정**: `truncate_need_repl_log`가 RK 존재(`classobj_find_cons_replication_key`)만 확인하고 `SM_CLASSFLAG_DATA_REPLICATION_OFF`는 확인하지 않아, REPLICATION=OFF 테이블이라도 PK/RK가 있으면 TRUNCATE는 복제 로그를 남긴다 — TRUNCATE가 REPLICATION 옵션을 따르지 않고 'RK 있으면 복제'로 취급됨(`execute_statement.c:376,16673`). 분류 명문화 필요.
- **52. DB/세션 레벨 REPLICATION 기본값 부재** (원 2m-7) — **확정**: 테이블 단위 옵션만 있고 DB/세션 기본값 메커니즘이 없어, 스키마 전체를 OFF로 두려면 테이블마다 명시해야 하고 하나 빠뜨리면 조용히 ON(`csql_grammar.y` opt_replication_option 기본 1, `execute_schema.c:95`). DB/세션 레벨 기본값 검토.
- **53. 카탈로그 컬럼 추가 하위호환** (원 2m-8) — **확정**: 신규 컬럼 is_replication_class가 db_class 뷰의 끝이 아니라 is_system_class와 tde_algorithm 사이 중간에 삽입되어 이후 컬럼 위치가 밀린다(`schema_system_catalog_install.cpp:1313`). `SELECT *` 위치기반 파싱 레거시/구버전 드라이버가 깨질 수 있음 — '항상 끝에 추가' 원칙 준수하도록 재배치.
- **54. VIEW/시스템 클래스의 db_class.replication 값 처리** (원 2m-6) — **기각**: §7 순회(rkcheck)는 시스템 클래스·VCLASS·비복제 클래스를 명시적으로 skip해 사용자 복제 테이블로 한정(`util_cs.c` `db_is_system_class || is_vclass>0 || !sm_is_replication_class → continue`). db_class 뷰가 VIEW에 'YES'로 표기되는 문서 뉘앙스만 남음.
- **55. 정합성 점검 오탐 + 슬레이브 백업 시 OFF 테이블 빈값** (원 2m-5) — **코드무관**: OFF 테이블이 슬레이브에서 구조적으로 빈 상태가 되는 것은 설계상 귀결. 운영 가이드·알람 조정 사안.
- **56. 기존 HA 설정파일 메커니즘과의 관계 / 레거시 우회 이중적용** (원 2m-2) — **코드무관**: `cubrid_ha.conf`류와 새 SQL 옵션의 우선순위, 레거시 트리거/섀도 우회의 이중 반영은 운영·마이그레이션 문서 사안.
- **57. 국제화 영문 용어 매핑** (원 2m-9) — **코드무관**: "복제 대상/제외 테이블", "복제키 후보"의 공식 영문 역어 미확정 + "REPLICATION" 옵션명이 HA 복제 기능 전체와 겹쳐 진단·검색 혼란. 용어집·번역 사안.
- **58. 문서 구조 결함** (원 2m-10) — **코드무관**: 예시 번호 누락, DROP CONSTRAINT PRIMARY KEY 표기 모호, BNF 표기 설명 부재, §간 시점 표현 불일치 등 문서를 QA·매뉴얼로 옮길 때 색인·검증을 막는 구조적 흠.

---

## 사소 (Trivial)

- **59. §5-1 제목 오타 "CRATE TABLE" + §7 "재시작해아한다" 등 오탈자** (원 T-1) — **코드무관**(문법 키워드는 CREATE로 정상). SQL 키워드 오타는 문서 검색에도 지장.
- **60. §9 "SA" 모드가 정의 없이 처음 등장, §1의 "HA 아니면 싱글" 이분법과 충돌** (원 T-2) — **코드무관**: SA는 CUBRID의 standalone(SA_MODE) 실제 실행 모드. §1에서 HA/CS/SA 관계를 정의할 것.
- **61. §1 첫 문장 주술 비문 + §4-2 비문** (원 T-3) — **코드무관**(문장 다듬기).
- **62. §8 "RK를 할당한다" vs §1 "선택된다" 용어 불일치** (원 T-4) — **코드무관**: 코드상 RK는 기존 PK/NOT NULL UNIQUE 중 선택. "할당"이 없던 키를 새로 만든다는 오해 유발 → 용어 통일.
- **63. REPLICATION 예약어 승격 시 기존 `replication` 컬럼명 충돌** (원 T-5) — **확정**: lexer가 replication을 전용 REPLICATION 토큰으로 반환하는데 문법의 비예약(identifier) 목록에 REPLICATION을 추가하지 않아(같이 추가된 이웃 키워드 DISK_SIZE·REVERSE는 있음) 예약어가 됨 → 기존 replication 컬럼/테이블명을 따옴표 없이 못 씀(`csql_lexer.l`; `csql_grammar.y:20646-20905`). identifier 규칙에 추가 필요.
- **64. "복제 테이블 / 복제 대상 테이블 / 복제키 후보 / 복제키" 용어 혼용, 용어집 부재** (원 T-6) — **코드무관**. §1에 용어집 신설.

---

## 스펙 절(§1~§9)별 이슈 맵

| 절 | 몰린 이슈 | 대표 지적 |
|---|---|---|
| **§1 제약사항** | RK 선택 비결정성(1), 부분 NOT NULL 복합 UK(3), 온라인/필터 UNIQUE 후보(17), ADD PK 재할당(18), "복제키 후보" 미정의(19), TDE(14), 모드 이분법 vs SA(60), 첫 문장 비문(61), 용어집 부재(64) | 가장 많은 개념 결함 집중. RK 결정 규칙·후보 판정 기준·용어를 여기서 확정 |
| **§2 SQL 변경** | trailing comma(38), 예시 7 템플릿(39), 표기 혼용(44), 예약어 충돌(63), LIKE/CTAS/RENAME 승계(16), 권한·감사(21) | 예제 품질 + 승계/거버넌스 |
| **§2-3 조회** | RK 미노출(5), 도구 생태계 미노출(20), 전수 조회/일괄정비(26), REUSE_OID 각주(43), OFF 출력 예시 없음(44) | 조회로 관측성을 확보하지 못하는 게 핵심 |
| **§3 Single 제약** | dev/prod parity(27), RK 추가 비용(36) | 싱글↔HA 경계 서술 부족 |
| **§4 HA 제약(운영중)** | FK OFF 전환(4), 복합 ALTER 원자성(10), 후보 카운팅(19), NOT NULL 해제·타입변경(2), OFF DDL fail_count(12), OFF 로그 계층(29), 다중 문장 롤백(32) | 운영 중 위반을 만드는 DDL을 막지 못하는 구멍 다수 |
| **§5 외래키** | FK OFF 전환(4), RENAME 우회(16), 다단계/자기참조/순환(22), CASCADE 처리(23), VIEW와 강도 불일치(15), 정적 코드테이블 봉쇄(47) | 핵심 목표절인데 생성 시점만 방어 |
| **§6 뷰** | 조용한 불일치·경고 부재(15) | "책임지지 않는다"만 있고 사전 신호 없음 |
| **§7 HA 전환** | "파일 리스트"(6), failover 우회(7), blast radius(30), 대량 위반 처리(26), 사전점검(27) | 장애 대응·자동화의 진입점, 검증 시점이 좁음 |
| **§8 UNLOADDB/LOADDB** | §9와 기본값 모순(8), loaddb 파이프라인(13), 물리 백업·PITR(31), 파일 포맷·다운그레이드(48), 업그레이드 경로(9) | 마이그레이션 경로의 공백 집중 |
| **§9 SUMMARY** | §8과 모순(8), SA 등장(60), OFF→ON 제약·FK 조건 누락 | 요약이 본문과 어긋나 오도 |

---

## 상충 의견 (리뷰어끼리 반대 방향)

1. **REPLICATION 기본값 ON vs OFF**: RK 없는 테이블은 기본 OFF(또는 CREATE 시 경고)로 하여 "나중에 HA에서 터지는 지뢰"를 없애자는 쪽 vs 기본 OFF는 하위 호환(구버전은 사실상 전부 복제)을 깨므로 ON 유지 + 운영 가이드 보완 쪽. "안전한 기본값" vs "하위 호환"의 미해결 트레이드오프. (코드는 ON으로 구현.)
2. **FK-복제 결합을 느슨하게 vs 엄격하게**: 정적 코드 테이블을 OFF로 두고도 FK를 걸도록 예외 옵션(`NOT ENFORCED ON SLAVE` 류)을 달라는 완화 요구(이슈 47) vs ALTER/RENAME 경로까지 막아 FK-복제 불변식을 강화하라는 다수(이슈 4). 같은 §5를 두고 한쪽은 열자, 다른 쪽은 잠그자.
3. **§8 기본값 중 어느 것이 오기인가**: 다수는 §8(ON)이 맞고 §9(OFF)가 오기로 봄(코드가 확인). 소수는 "unload 시 OFF, load 시 ON"의 의도된 비대칭일 가능성을 배제 못 한다며 유보.
4. **MySQL식 전 컬럼 폴백(FULL) 부활 여부**: "느려도 복제는 됨" 선택지를 로드맵에 남기라는 부분 복원 제안 vs 성능상 명시적 배제라는 스펙 배경. 설계 결정 자체에 대한 방향 이견.

---

## 부록 A — 코드 대조로 성립하지 않는 것으로 확인된 지적 (비적용)

아래 세 지적은 CUBRID 구조상 전제 자체가 성립하지 않아 본문에서 제외한다(원문은 이력 보존용으로 남김).

- **파티션 테이블에서 파티션-로컬 UNIQUE가 RK로 뽑혀 행 유일 식별이 깨진다** (원 2C-1). CUBRID는 파티션 테이블의 모든 UNIQUE/PK에 파티션 키 컬럼 포함을 강제하고(미포함 시 ER_SM_INVALID_UNIQUE_IDX_PARTITION), PK는 항상 global이라 RK 후보는 언제나 전역 유일. '같은 값이 다른 파티션에 공존'이라는 전제가 성립하지 않으며 예시의 `sales`는 생성 자체가 거부된다. (근거: `src/object/schema_manager.c:11258-11278`; `cubrid.msg:1242` err 1169) — 단, 스펙에 파티션을 "지원" 또는 "out-of-scope"로 명시하라는 문서 권고는 유효.
- **RK 컬럼 값 자체를 바꾸는 순수 UPDATE의 old-key/new-key 로그 처리 미정의** (원 2C-5). 전제('복제 로그가 변경 후 행 이미지만 담아 갱신 후 값으로 대상을 찾는다')가 실제와 다르다. UPDATE 복제는 갱신 전 RK 값(old_key)을 search key로 기록하고 슬레이브는 옛 키로 행을 찾아 새 이미지를 적용하므로 customer_id 5→9001 UPDATE도 마스터=슬레이브=9001로 일치. 무성 skip/오매칭 없음. (근거: `src/transaction/locator_sr.c:8757-8783,8809,8820`; `src/transaction/log_applier.c:4936`)
- **멀티프로세스 카탈로그 캐시 전파 지연으로 옛 RK로 로그 기록** (원 2M-10). 복제 로그의 RK 판정은 전적으로 서버측 현재 클래스 표현에서 이뤄져 클라이언트/CAS 로컬 스키마 캐시와 무관하고, RK 변경 DDL은 클래스 X-lock으로 동시 DML을 직렬화한다. '캐시 전파 지연' 전제가 실제 동작과 다르다. (근거: `src/transaction/locator_sr.c:8420-8425`; `src/query/execute_schema.c:11777`)

---

## 부록 B — 런타임 확인 필요 항목 (판정불가)

- **TDE 암호화 테이블 × RK/복제 로그** (이슈 14, 원 2C-7). 2노드 HA + TDE 암호화 REPLICATION=ON 테이블(노드별 TDE 키 분리)에서 (a) DML이 정상 복제·매칭되는지(정합성), (b) 슬레이브로 전송·적재된 복제 로그 파일·네트워크 캡처에 RK 값이 평문으로 남는지(보안). replication-log TDE가 `UNSTABLE_TDE_FOR_REPLICATION_LOG` 매크로 뒤에 컴파일아웃되어 정적으로는 확정 불가.
- **DROP TABLE 후 동일명 REPLICATION=ON 재생성으로 OFF→ON 금지 우회** (원 N-11, 판정불가). ALTER OFF→ON은 HA에서 차단되지만 HA 모드 CREATE REPLICATION=ON은 RK/FK 검사만 통과하면 허용되고 이전 DROP과 연계하는 코드가 없어 기계적 우회가 코드상 가능. **확인**: HA 2노드에서 OFF 테이블 DROP 후 동일명 REPLICATION=ON 재생성 → 슬레이브에 동일 빈 ON 테이블이 생성되고 이후 DML이 정상 복제되는지, 과거 데이터 공백이 생기는지. (근거: `src/query/execute_schema.c:11740,10267-10274`)

---

## 개정 우선순위 로드맵

### Phase 0 — 즉시 (문서 교정, 반나절)
- §8/§9 기본값 모순을 ON으로 확정하고 §1에 "기본값 정책" 표를 만들어 단일 출처화 (이슈 8).
- 전 SQL 예제를 실제 csql로 실행·검증해 trailing comma 등 문법 오류 제거, 예시 7 구체화, 예시 10 테이블명 정정 (38~40).
- 맞춤법·용어 통일 1회 (59, 64). §1에 용어집(RK / RK 후보 / 복제 테이블=복제 대상 테이블 / HA·CS·SA) 신설 (60, 64).

### Phase 1 — 컨셉 확정 (설계 재검토, 릴리스 게이트)
- **RK 선택 규칙을 확정 알고리즘으로 명문화** + "마스터가 정해 로그로 전파, 슬레이브 재계산 금지" + sticky 불변식 (이슈 1). 다른 모든 이슈의 뿌리.
- **FK 불변식을 대칭으로 재설계** — ALTER·RENAME·트리거 경로, 다단계·자기참조·순환까지 (4, 16, 22). 상충 의견 2를 여기서 결론.
- **Failover/switchover/failback 시 §7 재검증** — 검증 시점을 "마스터가 되는 모든 순간"으로 확장 (7).
- **RK 자격 상실 경로 전수 차단** + 부분 NOT NULL 복합 UK·필터/함수/온라인 인덱스 후보 판정 정비 (2, 3, 17).
- **복합 ALTER 원자성·검증 시점(문장 최종 상태)·동시성 락**을 스펙에 반영 (10, 19, 32).
- **복제 로그의 커밋순 직렬 적용·old-key 스냅샷 보장을 명문화**하고 향후 병렬 적용 시 배리어·RK 스키마 버전 규칙을 예고 (11).
- **TDE × RK/복제**(정합성·보안) 규정 또는 스코프 선언 (14) — 런타임 확인(부록 B) 후 확정.
- **loaddb 파이프라인 × §4-1** 검증 경로 공유·OFF 강등 규칙 명시 (13).

### Phase 2 — 운영·관측성
- RK·복제 상태 조회 카탈로그 뷰 신설 + 변경 이력 (5), 표준 메타데이터/JDBC 노출·ORM 되돌림 차단 (20).
- §7 출력 포맷·사유 코드·exit code·blast radius·사전점검(rkcheck)을 스펙에 정의 (6, 30, 27).
- OFF 테이블 DDL 실패 격리 정책 (12), OFF 로그 계층 명시 (29).
- REPLICATION 변경 권한·감사 모델 (21), 소유자 교차 영향 권한 경계 (50).
- OFF↔ON 전환 시 데이터 처리·재동기화 절차·금지 근거 (28), VIEW 참조 경고 (15).
- 에러 메시지 예시 통일 (25), ADD PK RK 재할당 NOTICE (18), TRUNCATE 분류 명문화 (51).

### Phase 3 — 마이그레이션·확장성·스코프
- 업그레이드 전용 절: in-place 카탈로그 마이그레이션, 롤링 업그레이드 호환 정책(또는 동시교체 강제), 다운그레이드, unload 파일 포맷·버전 가드 (9, 48).
- 물리 백업(backupdb/restoredb)·PITR 절차 (31), 릴리스 거버넌스 메타데이터·킬스위치·다운그레이드 (37), 카탈로그 컬럼 배치 하위호환 (53).
- 스코프 명시: 파티션·클래스 상속(UNDER)·트리거·SERIAL·멀티슬레이브·컬럼 단위 필터·DB/세션 기본값을 "지원" 또는 "out of scope"로 못박기 (34, 45, 49, 52, 부록 A 파티션).
- 경쟁 포지셔닝 근거(성능 벤치, REPLICA IDENTITY 비교표)와 사용자 명시 RK 지정 로드맵 (33), RK 추가 비용 경고·온라인 인덱스 (36). 상충 의견 1·4를 여기서 명문화.
