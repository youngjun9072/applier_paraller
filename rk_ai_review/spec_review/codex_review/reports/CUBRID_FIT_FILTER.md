# CUBRID `develop` 기준 새 기능 스펙 리뷰 필터링

> **이전 기준 이력:** 이 문서는 기능 구현을 보기 전 로컬 `develop`만으로 작성한 1차 필터이며 최종 판정이 아니다. `feature/CBRD-26246-develop @44468ed73` 구현까지 대조한 최신 결과는 [CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md](CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md)를 사용한다. 아래 내용은 판정 변경 이력을 보존하기 위해 삭제하지 않았다.

- 작성일: 2026-08-23
- 원본: `CONSOLIDATED_FINDINGS.md`
- 리뷰 대상: 새로 추가할 HA 복제 키 기능의 사용자 스펙
- 구현 근거: `/home/youngjun/Workspace/cubrid` 로컬 `develop` (`23789cbfa78087a9edaae126b605495525b4d40d`)
- 보조 비교 ref: 로컬 `origin/develop` (`11f0140a984bbdc05f66ad5061f0ddf282e5a130`)
- 방법: 개발자 직군 페르소나만 사용하고 clangd compile DB로 관련 C/C++ translation unit을 해석한 뒤 CUBRID의 정의·호출 경로와 대조했다.

## 먼저 읽을 결론

이 문서는 코드 리뷰가 아니다. 기존 CUBRID 구현을 근거로 새 기능 스펙에 대한 기존 리뷰가 CUBRID에 맞는지 필터링한 결과다.

기존 30개 통합 결함과 그에 연결된 원시 리뷰 691건은 삭제하지 않았다. 각 통합 결함의 원래 제목과 문제의식을 남긴 채 CUBRID 적합성만 추가 판정한다. 일반적인 분산 DB 설계 권고가 CUBRID의 단일 log applier, statement replication, 기존 WAL/DDL 원자성, 지원 객체 범위와 맞지 않으면 `CUBRID 비적용`으로 표시하고 재검토 조건을 적는다.

현재 `develop`에는 사용자 스펙의 테이블별 `REPLICATION ON/OFF`와 UK 기반 RK 구현이 없다. 따라서 “현재 구현에 이미 버그가 있다”가 아니라 “새 기능 스펙이 반드시 답해야 할 요구”, “CUBRID 방식으로 고쳐야 할 요구”, “현재 제품 범위 밖 일반론”을 구분한다.

## 판정 요약

| 판정 | 수 | 항목 |
|---|---:|---|
| 유지 | 2 | CF-05, CF-18 |
| 표현 수정 후 유지 | 21 | CF-02, 04, 06, 07, 09~14, 17, 19~23, 25~28, 30 |
| CUBRID 비적용 | 4 | CF-03, CF-08, CF-24, CF-29 |
| 구현안 확정 후 판단 | 3 | CF-01, CF-15, CF-16 |

30개 중 원문 그대로 유지할 항목은 2개뿐이다. 21개는 핵심 문제를 남기되 CUBRID의 기존 기능과 용어에 맞춰 범위를 줄여야 하고, 4개는 현재 CUBRID/새 기능 범위에 맞지 않는다. 나머지 3개는 RK를 기존 statement replication·catalog·WAL에 통합할지 새 log format과 비동기 상태를 만들지 결정한 뒤 판정할 수 있다.

부분 비적용 내용도 있다. CF-11의 미지원 객체, CF-14의 신규 manifest/ledger 강제, CF-17의 자동 shadow-index 전제, CF-20의 sharding·일반 상속 혼합, CF-22의 parallel apply 전제, CF-26의 모든 ORM 지원, CF-27의 기본 비활성 rename은 각 본문에서 범위 밖으로 표시했다.

## 항목별 판정

### CF-01 — RK 세대와 로그를 연결하는 핵심 불변식이 없다

- 판정: `구현안 확정 후 판단`
- 기존 내용 보존: 온라인·비동기 RK 전환으로 old/new RK가 동시에 유효하다면 세대 불일치 위험은 그대로 유효하다.
- CUBRID 근거: 현재 데이터 복제 로그는 class name과 packed PK 값만 저장하고 RK/index ID나 generation은 저장하지 않는다(`src/transaction/replication.c`의 `repl_log_insert()`). UPDATE는 old PK를 기록하고 applier는 standby의 현재 PK B-tree를 조회한다(`src/transaction/locator_sr.c`의 `locator_update_index()`, `locator_repl_prepare_force()`). DDL은 `LOG_REPLICATION_STATEMENT`로 source commit 순서에 따라 적용된다.
- CUBRID식 수정: 동기식 RK 전환이라면 기존 class write lock, schema transaction과 statement replication 순서 안에서 선택 RK를 원자적으로 바꾸는 것으로 충분할 수 있다. 물리 `BTID`는 노드별 값이므로 논리 RK ID로 쓰지 않는다. 비동기 전환을 채택할 때만 로그 format의 RK identity/version 요구를 유지한다.

### CF-02 — RK 후보 선택과 논리 객체 정체성이 결정적이지 않다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: UNIQUE는 constraint name을 key로 class property에 저장한다(`src/object/class_object.c`의 `classobj_put_index()`). catalog iteration 순서나 물리 `BTID`는 안정적인 RK 정체성이 아니다.
- CUBRID식 수정: PK 우선, PK가 없으면 명시적인 안정 정렬 규칙으로 NOT NULL UNIQUE를 선택하고 선택된 constraint name을 class metadata에 영속화한다. 모든 DML에 별도 generation을 넣는 것은 CF-01의 구현 방식이 확정된 뒤 결정한다.

### CF-03 — REPLICATION=OFF의 데이터 생명주기와 재편입 계약이 없다

- 판정: `CUBRID 비적용`
- 기존 내용 보존: 원래 제기한 cutover LSN, 권위 사본, full resync 요구는 삭제하지 않는다.
- 비적용 이유: 스펙은 OFF 데이터 불일치를 명시적으로 책임 범위 밖으로 두고 HA 실행 중 OFF→ON도 금지한다. 현재 CUBRID의 `suppress_replication`은 transaction-wide 플래그일 뿐 per-table resync 체계가 아니다(`src/transaction/replication.c`, `src/transaction/log_impl.h`).
- 재검토 조건: HA 중 OFF→ON, OFF 테이블의 failover 데이터 보장 또는 자동 재편입을 제품 계약에 추가할 때 원래 요구를 다시 적용한다.

### CF-04 — 기본 ON과 모드별 readiness 검사가 불완전하다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: 현재 HA 기동과 update 허용은 `ha_mode` 및 server state 전환으로 처리하지만 RK/FK catalog readiness 검사는 없다(`src/transaction/boot_sr.c`, `src/connection/server_support.c`의 HA state 전환).
- CUBRID식 수정: 별도 catalog epoch subsystem을 전제하지 말고, 서버가 client update를 허용하기 전에 일관된 transaction/lock 범위에서 RK와 FK 위반 class를 전수 검사하고 구조화된 오류 목록을 반환하도록 요구한다.

### CF-05 — SQL grammar·정규 출력·metadata 계약이 없다

- 판정: `유지`
- CUBRID 근거: CREATE TABLE grammar, SHOW CREATE 출력, unload schema 출력은 각각 `src/parser/csql_grammar.y`, `src/object/object_printer.cpp`, `src/executables/unload_schema.c`의 별도 경로다.
- CUBRID식 요구: parse-tree option, `SM_CLASS` 영속 metadata, `_db_class`, SHOW CREATE와 unloaddb 출력이 동일한 의미를 왕복해야 한다. 중복 옵션은 semantic error로 처리하고 parse→print→parse 및 unload→load 시험을 둔다.

### CF-06 — 복합 ALTER와 RK DDL의 원자성·crash recovery가 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: schema 변경은 하나의 `SM_TEMPLATE`을 `sm_update_class()`로 반영하고 UNIQUE 변경 전에 system savepoint를 사용한다(`src/object/schema_manager.c`). 성공한 DDL은 같은 transaction의 statement replication log로 남는다(`src/query/execute_statement.c`).
- CUBRID식 수정: 별도 prepare/build/publish 상태 머신을 무조건 요구하지 않는다. DROP/ADD를 한 schema transaction에서 사전 검증하고 기존 WAL, system savepoint, abort/recovery를 사용해 crash 후 전부 old 또는 전부 new인지 시험한다.

### CF-07 — DDL·DML 동시성, 장기 transaction과 온라인 구축 규칙이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: schema update는 class 및 hierarchy write lock을 잡고 applier는 source commit 순서로 적용한다(`src/object/schema_manager.c`의 `update_class()`, `src/transaction/log_applier.c`).
- CUBRID식 수정: 독립적인 schema epoch/admission 체계를 전제하지 말고 기존 class lock과 transaction 경계의 대기·deadlock·timeout 동작을 명세한다. online UNIQUE index는 build 완료 전 RK 후보로 공개하지 않아야 하며 장기 DML과 build 완료 경계 시험은 유지한다.

### CF-08 — RK 전환 중 failover의 promotion gate와 앱 보장이 없다

- 판정: `CUBRID 비적용`
- 기존 내용 보존: RK metadata와 data readiness가 분리되는 구현에서는 원래 항목이 다시 유효하다.
- 비적용 이유: CUBRID는 모든 log applier가 `DONE`인지를 generic promotion/update-enable gate로 사용하고 committed LSA와 apply state를 durable하게 갱신한다(`src/connection/server_support.c`, `src/transaction/log_applier.c`). 동기식 RK DDL이 동일 replication stream을 따르면 RK 전용 epoch와 client fencing token은 중복이다.
- 재검토 조건: RK migration을 commit stream 밖에서 비동기로 수행할 때다.

### CF-09 — 키 타입·collation·복합 값·old/new UPDATE 의미가 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: UPDATE 복제는 before image인 old PK를 사용하고 복합 `MIDXKEY`의 domain을 B-tree domain으로 보정한다(`src/transaction/locator_sr.c`). 로그 직렬화는 `or_pack_mem_value()`를 사용한다(`src/transaction/replication.c`).
- CUBRID식 수정: 별도 canonical encoding을 새로 정의하기보다 선택 UK가 기존 DB_VALUE/B-tree domain과 old-key 경로를 재사용하도록 한다. RK 자체 UPDATE, 복합 UK, collation 변경과 기존 index key-size 경계 시험은 유지한다.

### CF-10 — FK·trigger·cascade와 ON/OFF 혼합 transaction 계약이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: trigger/cascade 결과는 일반 locator DML 경로에서 replication item이 되고 applier는 source transaction의 item을 commit 단위로 처리한다(`src/transaction/locator_sr.c`, `src/transaction/log_applier.c`).
- CUBRID식 수정: transaction-wide `suppress_replication`으로 ON/OFF를 구현하지 말고 각 `locator_insert/delete/update`의 `repl_log_insert()` 직전에 대상 class flag를 확인한다. ON child→OFF parent 차단, OFF 전환 시 역참조, trigger/cascade가 양쪽을 수정하는 시험을 남긴다.

### CF-11 — OFF 의존 VIEW와 데이터 의존 객체가 정상처럼 다른 결과를 낸다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: VIEW는 VCLASS이며 query spec 텍스트로 저장되고, parser에는 하위 VCLASS spec을 재파싱해 재귀 순회하는 경로가 있다(`src/object/class_object.h`의 `SM_QUERY_SPEC`, `src/parser/semantic_check.c`의 `pt_check_cyclic_reference_in_view_spec()`).
- CUBRID식 수정: “데이터 의존 객체 전반”을 OFF 테이블을 직접·다단계 참조하는 VCLASS/VIEW 진단으로 축소한다. 승격 차단은 기본 엔진 요구가 아니라 선택 관리 정책으로 둔다. materialized view 등 CUBRID에 없는 객체 전제는 `CUBRID 비적용`으로 보존한다.

### CF-12 — fail_count만으로 정상성과 영향 범위를 알 수 없다

- 판정: `표현 수정 후 유지`
- 사실 수정: “fail_count만 있다”는 현재 CUBRID와 맞지 않는다. `_db_ha_apply_info`에는 committed/rep/append/eof/final/required LSA, 시각, 상태와 DML/schema/commit/fail counter가 이미 있다(`src/transaction/log_applier.c`의 `LA_HA_APPLY_INFO`, `la_get_ha_apply_info()`; `src/object/schema_system_catalog_install.cpp`).
- CUBRID식 수정: 제목을 “기존 apply-info만으로 실패 class/RK/LSA와 retry 상태를 식별하기 어렵다”로 축소한다. 기존 진행·lag 정보는 재사용하고 bounded 실패 상세만 추가 검토한다.

### CF-13 — 기존 불일치의 탐지·수리·재가입 절차가 없다

- 판정: `표현 수정 후 유지`
- 사실 수정: CUBRID에는 schema/row checksum과 resume chunk 상태를 제공하는 `checksumdb`가 이미 있다(`src/executables/checksumdb.c`). 다만 PK가 없는 class는 대상에서 빠지고 자동 repair/rejoin은 제공하지 않는다.
- CUBRID식 수정: “탐지가 없다”를 “기존 checksumdb가 UK-only RK 테이블과 행 단위 수리를 포괄하지 않는다”로 고친다. checksum의 PK chunk 기준을 확정된 RK 추상화로 일반화하고 수리는 별도 승인형 절차로 둔다.

### CF-14 — unloaddb/loaddb 기본값과 부분 실패 계약이 상충한다

- 판정: `표현 수정 후 유지`
- 유지할 문제: 스펙 8절의 무표기=ON과 9절의 무표기=OFF 모순은 반드시 해결해야 한다.
- 사실 수정: loaddb는 statement 단위 periodic commit, 실패 line과 `-s file:line` 재시작을 이미 제공한다(`src/loaddb/load_db.c`). “재개 단위가 없다”는 표현은 맞지 않는다.
- CUBRID식 수정: unloaddb가 canonical ON/OFF를 명시하고 legacy 무표기 기본값 하나를 정한다. 새 manifest/idempotent ledger를 강제하지 말고 기존 line resume와 이미 commit된 DDL·data 처리 규칙을 연결한다.

### CF-15 — backup·snapshot·PITR이 RK 세대와 시점을 함께 보존하지 않는다

- 판정: `구현안 확정 후 판단`
- CUBRID 근거: physical backup은 catalog page를 함께 보존하고 header에 version, release, start/checkpoint LSA를 기록하며 PITR stop-at도 이미 있다(`src/storage/file_io.h`, `src/executables/util_sa.c`).
- CUBRID식 수정: RK metadata를 정상 catalog에 넣고 RK DDL을 기존 WAL에서 transactional redo하면 별도 RK manifest는 불필요하다. catalog 밖 metadata, 현재 catalog로 과거 log를 재해석하는 형식 또는 별도 generation GC를 선택할 때만 원래 manifest/epoch 보존 요구를 적용한다.

### CF-16 — rolling upgrade·기능 활성화·downgrade 경계가 없다

- 판정: `구현안 확정 후 판단`
- CUBRID 근거: network release/capability 확인과 log compatibility matrix는 이미 있다(`src/communication/network_cl.c`, `src/communication/network_interface_sr.cpp`, `src/base/release_string.c`). 새 RK record용 협상은 현재 없다.
- CUBRID식 수정: 기존 statement replication과 호환 catalog만 쓰고 혼합 버전 HA를 지원하지 않는다면 별도 capability protocol 요구는 과하다. 새 physical log record/catalog layout 또는 mixed-version 지원을 선택할 경우 activation/downgrade fence를 유지한다.

### CF-17 — 넓은 RK와 온라인 구축의 성능·용량 기준이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: replication log는 class name과 key `DB_VALUE`를 매 DML에 pack하고 applier가 이를 할당·unpack하므로 넓은 UK는 log/network/memory/lookup 비용을 늘린다(`src/transaction/replication.c`, `src/transaction/log_applier.c`). B-tree는 큰 키용 기존 overflow 처리가 있다(`src/storage/btree_load.h`).
- CUBRID식 수정: 임의의 새 최대폭보다 기존 index 허용 범위와 apply SLO를 기준으로 한다. 엔진이 shadow index를 자동 생성하지 않는다면 온라인 구축 throttle/cancel/resume 요구는 `CUBRID 비적용`으로 남긴다.

### CF-18 — 오류 계약·실행 예제·전체 runbook이 부족하다

- 판정: `유지`
- CUBRID 근거: CUBRID는 locale 문구와 분리된 음수 `ER_*` 오류 체계를 사용하며 HA apply도 operation별 오류 코드가 있다(`src/base/error_code.h`).
- CUBRID식 요구: 새 오류를 기존 `ER_*`, client 공개 헤더와 양 언어 message catalog에 연결한다. 모든 예제를 완전한 CUBRID SQL과 초기·사후 상태로 만들고 csql/loaddb/HA 전환 절차를 포함한다.

### CF-19 — 복제 정책 변경의 최소 권한·감사 원자성이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: 현재 권한에는 ALTER와 INDEX 등이 있지만 replication 전용 권한은 없다(`src/compat/dbtype_def.h`). schema 변경은 `AU_ALTER`, index는 `AU_INDEX`를 사용한다. csql 등의 DDL audit 파일은 DB catalog transaction과 같은 event store가 아니다.
- CUBRID식 수정: 먼저 REPLICATION 변경을 기존 ALTER로 둘지 DBA/system에 제한할지 결정한다. 무조건 새 권한 비트를 요구하지 않는다. 원자 감사가 제품 요구라면 commit/abort와 연결되는 기존 transaction/WAL 경로를 검토한다.

### CF-20 — partition·상속·sharding의 유일성과 정책 상속이 없다

- 판정: `표현 수정 후 유지` — sharding·일반 상속 전제는 `CUBRID 비적용`
- 사실 수정: CUBRID는 partition key가 모든 unique key에 포함되도록 검사하므로 “두 partition에 같은 단일 RK id” 예제는 성립하지 않는다(`src/object/schema_manager.c`, `ER_SM_INVALID_UNIQUE_IDX_PARTITION`). log applier도 partition-aware operation을 구성한다(`src/transaction/log_applier.c`).
- CUBRID식 수정: 예제를 composite RK `(id, partition_key)`의 partition-key UPDATE와 행 이동으로 바꾸고 REPLICATION/RK는 root table 소유, child partition 파생으로 명세한다. broker sharding을 engine partition과 동일시한 내용은 보존하되 비적용으로 표시한다.

### CF-21 — TRUNCATE·bulk·CTAS·clone·특수 객체 경로가 정책을 우회한다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: CTAS는 CREATE 뒤 실제 INSERT 경로로 변환되며 CREATE LIKE는 class/index 복사 경로를 사용한다(`src/query/execute_schema.c`). TRUNCATE는 delete 또는 heap destroy 경로를 선택하고(`src/object/schema_class_truncator.cpp`), loaddb는 HA에서 정확한 per-insert LSA를 위해 별도 insert path를 선택한다(`src/loaddb/load_server_loader.cpp`).
- CUBRID식 수정: “공통 validator 하나가 없다”를 결함으로 삼지 않는다. CTAS/LIKE/TRUNCATE, locator replication과 loaddb HA 분기별로 RK metadata 상속, log 생성과 rollback 결과를 표로 명세한다. `clone`은 CUBRID의 실제 CREATE LIKE/CTAS 용어로 바꾼다.

### CF-22 — parallel apply·log 보관·codec의 장기 계약이 없다

- 판정: `표현 수정 후 유지`
- 사실 수정: 현재 applylogdb는 LSA 기반 순차 적용이며 committed/required LSA, archive GC, duplicate skip, page checksum과 log compatibility matrix를 이미 갖는다(`src/transaction/log_applier.c`, `src/transaction/log_page_buffer.c`, `src/base/release_string.c`). “parallel worker drain과 codec 계약이 전혀 없다”는 표현은 현재 CUBRID에 맞지 않는다.
- CUBRID식 수정: 새 RK payload를 기존 `LOG_REPLICATION_DATA/STATEMENT`와 LSA 진행점에 통합하고 payload가 바뀌면 compatibility matrix를 갱신하도록 요구한다. parallel apply를 실제 구현할 때만 worker barrier/drain 부분을 재적용한다.

### CF-23 — resource 고갈·손상·반복 실패의 안전 상태가 없다

- 판정: `표현 수정 후 유지` — 기존 Blocker 범위 축소
- CUBRID 근거: applylogdb는 parameter 기반 ignore/retry와 partial flush/reconnect 경로를 제공하지만 retry 오류를 제한 없이 반복할 수 있고 durable per-item quarantine은 없다(`src/transaction/log_applier.c`의 `la_retry_on_error()`, `la_flush_repl_items()`). 반면 schema DDL은 기존 savepoint와 WAL/ARIES 복구를 사용한다.
- CUBRID식 수정: RK DDL에 별도 WAL reserve 체계를 요구하지 않는다. 기존 schema transaction을 재사용하고 apply 오류에 non-retry 분류, bounded retry와 HA apply state 연결이 필요한지만 새 기능 범위에서 검토한다.

### CF-24 — network partition·split-brain·다중 topology의 fencing이 없다

- 판정: `CUBRID 비적용`
- 기존 내용 보존: quorum/lease/fencing epoch 제안은 삭제하지 않고 현재 제품 범위 밖으로 표시한다.
- 비적용 이유: CUBRID HA는 heartbeat가 복수 master와 ping 결과를 감지해 failback을 예약하고 server state가 update enable/disable을 제어한다(`src/executables/master_heartbeat.c`, `src/connection/server_support.c`). RK만을 위해 별도의 catalog/client lease epoch를 도입하는 요구는 현재 HA 모델과 기능 범위를 넘는다.
- 재검토 조건: active-active/multi-writer를 지원하거나 RK 변경용 별도 writer/control plane을 만들 때다. 현재 스펙에는 RK DDL/DML이 기존 HA state gate를 우회하지 않는 시험만 남긴다.

### CF-25 — 진단 telemetry에 RK 개인정보가 노출된다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: applylogdb는 `db_sprint_value()`로 PK를 문자열화해 error/reconnect message와 SQL log에 기록한다(`src/transaction/log_applier.c`의 `la_flush_repl_items()`, `la_log_apply_error()`; `src/transaction/log_applier_sql_log.c`). email UK가 RK가 되면 실제 개인정보 노출 경로가 된다.
- CUBRID식 수정: 입증되지 않은 metric label/trace/quarantine 주장은 제거하고 “CUBRID apply/error/SQL log의 RK 원문 노출”로 좁힌다. 기본 redaction 또는 명시적 상세 로깅 정책을 스펙에 정한다.

### CF-26 — ORM·driver·schema diff·cache·CDC 계약이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: CCI/broker의 schema-info는 고정 protocol surface다(`cubrid-cci/src/cci/cas_cci.h`의 `T_CCI_SCH_TYPE`, `src/broker/cas_execute.c`의 `ux_schema_info()`). CDC는 JDBC가 미리 읽은 schema와 PK condition column에 의존한다(`src/transaction/log_manager.c`의 `cdc_check_if_schema_changed()`, `cdc_find_primary_key()`).
- CUBRID식 수정: catalog→CCI schema info→JDBC metadata/CDC schema 재조회까지 필드와 호환 동작을 명세한다. 모든 ORM·schema-diff 도구 지원 보장은 core 스펙에서 제외하고 공식 지원 대상으로 지정한 도구만 시험한다.
- 확인 한계: 이 checkout의 `cubrid-jdbc`는 미초기화 gitlink라 Java 구현은 직접 확인하지 못했다.

### CF-27 — index rebuild·rename·optimizer와 논리 RK의 관계가 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: constraint property는 이름과 물리 `BTID`를 함께 저장하고 index rebuild는 drop/create여서 BTID가 바뀔 수 있다(`src/object/class_object.h`, `src/query/execute_schema.c`의 `do_alter_index_rebuild()`). constraint rename은 현재 기본 compile command에서 활성화되지 않은 guard 아래 있다.
- CUBRID식 수정: RK 논리 동일성을 constraint type, ordered attribute IDs와 collation/prefix/filter/function 의미로 정의하고 BTID와 optimizer plan은 물리 mapping으로 둔다. rebuild 후 논리 RK 유지와 새 BTID 재결합은 시험하되 rename 요구는 기능이 활성화될 때만 적용한다.

### CF-28 — 제품 목표·대안·지원 범위·성공 지표가 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: 현재 locator와 CDC는 PK가 없으면 data replication을 생략하거나 PK condition column을 찾지 못한다(`src/transaction/locator_sr.c`, `src/transaction/log_manager.c`의 `cdc_find_primary_key()`). PK/UK/무키 처리 선택은 실제 HA·CDC 경로와 연결된다.
- CUBRID식 수정: 일반 제품 KPI 요구를 줄이고 PK, 지원 가능한 NOT NULL UNIQUE, 복합키, partition과 무키 table의 enable/reject/fallback matrix를 명세한다. 대표 schema 지원률은 제품 계획 부록으로 이동한다.

### CF-29 — tenant·법적 보존·장기 지원 정책이 없다

- 판정: `CUBRID 비적용`
- 기존 내용 보존: tenant별 RPO, edition과 법적 보존 요구는 삭제하지 않고 범위 밖으로 표시한다.
- 비적용 이유: 현재 HA filtering은 table-name include/exclude 설정이며 tenant row 정책, 법적 보존 또는 edition entitlement model이 아니다(`src/base/system_parameter.c`의 HA replication filter parameter, `src/transaction/log_applier.c`의 `la_need_filter_out()`).
- 재검토 조건: shared-table tenant별 replication/retention, edition 차등 또는 엔진 수준 보존 증적을 제품 범위에 추가할 때다. 현 스펙은 table/catalog granularity와 기존 HA filter의 상호작용만 명세한다.

### CF-30 — 상태 공간을 포괄하는 test oracle과 추적성이 없다

- 판정: `표현 수정 후 유지`
- CUBRID 근거: 저장소에는 unit test 틀과 `FI_TEST` 기반 crash fault injection이 있지만 이 checkout만으로 외부 HA regression corpus의 부재까지 단정할 수 없다(`unit_tests/`, `src/transaction/log_manager.c`, `src/transaction/log_2pc.c`).
- CUBRID식 수정: parser, catalog, replication log/apply, recovery, CCI/JDBC와 CDC 변경점별 test mapping을 만들고 기존 또는 새 fault point를 사용한다. “모든 문장 자동 시험” 대신 정합성 불변식과 지원 matrix 각 셀을 자동화하고 운영·문서 요구는 traceability로 검증한다.
