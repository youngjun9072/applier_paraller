# CUBRID 기능 브랜치 기준 새 기능 스펙 리뷰 필터링

- 작성일: 2026-08-23
- 원본 스펙 리뷰: [CONSOLIDATED_FINDINGS.md](CONSOLIDATED_FINDINGS.md)의 CF-01~CF-30
- 기능 브랜치: `feature/CBRD-26246-develop`
- 기능 HEAD: `44468ed7329c3898b509af890c24b1c79091c589`
- develop 기준: `23789cbfa78087a9edaae126b605495525b4d40d`
- 핵심 기능 commit: `8bb304290` (`[CBRD-26246] Add HA replication option support`)
- 대조 worktree: `/home/youngjun/Workspace/cubrid-cbrd26246`
- 관점: DBMS 엔진 개발자와 DB 사용 애플리케이션 개발자 직군만 사용
- 도구: feature diff, 실제 source/호출 경로, feature 경로로 재지정한 clangd compile DB

## 판정 원칙

기존 CF 본문과 원시 리뷰 691건은 삭제하지 않는다. 각 CF의 넓은 문제 제기 안에 맞는 주장과 틀린 주장이 섞였으면 대표 판정을 하나 부여하고, 기각·폐기할 하위 전제를 본문에 명시한다.

- `확정`: 기능 코드도 문제를 막지 못한다.
- `기각`: 기능 코드가 이미 처리한다.
- `폐기`: 전제 자체가 CUBRID 구조나 지원 범위에 맞지 않는다.
- `판정불가`: 정적 분석으로 결론을 낼 수 없어 런타임 시험이 필요하다.
- `코드무관`: 문서·운영·제품 정책 문제로 코드 결함 판정 대상이 아니다.

## 결과 요약

| 판정 | 수 | CF |
|---|---:|---|
| 확정 | 12 | CF-01, 02, 05, 07, 08, 09, 11, 19, 21, 25, 26, 27 |
| 기각 | 4 | CF-04, 06, 10, 12 |
| 폐기 | 4 | CF-20, 22, 24, 29 |
| 판정불가 | 1 | CF-23 |
| 코드무관 | 9 | CF-03, 13~18, 28, 30 |
| 합계 | 30 | CF-01~CF-30 |

`확정` 12건은 기존 CF 전체 문구를 그대로 코드 결함으로 승격한다는 뜻이 아니다. 아래에서 CUBRID 구현으로 확인된 좁은 결함만 승격하며, 함께 묶였던 과도한 generation·quorum·parallel apply·모든 ORM 지원 요구는 기각하거나 폐기한다.

## 항목별 판정

### CF-01 — RK 세대와 로그를 연결하는 핵심 불변식이 없다

- 판정: `확정`
- 확인된 문제: master는 복제 로그에 RK identity가 아니라 key 값만 넣고, replica는 자기 class representation에서 첫 RK 후보를 다시 선택한다. 코드에도 master에서 RK 이름을 받는 방식으로 바꿔야 한다는 TODO가 있다.
- 근거: `src/base/object_representation_sr.c:4692`, `src/storage/btree.c:8285-8298`, `src/transaction/locator_sr.c:6846-6858`.
- 필터링: CUBRID는 DDL/DML을 commit LSA 순서로 직렬 적용하므로 별도 epoch/generation 상태 머신이 반드시 필요하다는 주장은 기각한다. 확정 결함은 source와 replica가 동일한 논리 RK를 사용한다는 보장이 없다는 점이다.
- 조치: 선택된 constraint identity를 catalog/log에 안정적으로 연결하거나 replica가 master 선택을 그대로 사용하도록 스펙을 보완한다.

### CF-02 — RK 후보 선택과 논리 객체 정체성이 결정적이지 않다

- 판정: `확정`
- 확인된 문제: RK는 class representation의 index 배열에서 첫 후보를 고른다. PK property가 UNIQUE보다 먼저 구성되므로 PK 추가 시 RK가 조용히 바뀔 수 있고, 현재 RK 이름·컬럼을 SHOW CREATE나 `db_class`에서 조회할 수 없다.
- 근거: `src/object/class_object.c:82-98`, `src/storage/btree.c:8285-8298`, `src/object/object_printer.cpp:1137-1145`, `src/object/schema_system_catalog_install_query_spec.cpp:68-75`.
- 조치: deterministic selection, sticky 여부, PK 추가 시 전환 규칙과 활성 RK metadata를 스펙에 명시한다. 물리 `BTID`는 논리 identity로 사용하지 않는다.

### CF-03 — REPLICATION=OFF의 데이터 생명주기와 재편입 계약이 없다

- 판정: `코드무관`
- 구현 사실: HA 중에는 ON→OFF와 OFF→ON을 모두 거부하고, 변경은 HA disabled 상태에서 class flag를 바꾸는 metadata 작업이다.
- 근거: `src/query/execute_schema.c:11730-11826`.
- 필터링: HA 운영 중 online cutover, per-table authority와 자동 full-resync를 요구한 부분은 현재 설계 범위 밖이다. 다만 HA를 내린 상태의 전환 후 데이터 재동기화 절차와 금지 근거는 스펙·운영 문서에 남겨야 한다.

### CF-04 — 기본 ON과 모드별 readiness 검사가 불완전하다

- 판정: `기각`
- 구현 사실: `rkcheck`가 모든 user replication class를 순회해 RK/FK 위반을 파일과 오류 코드로 보고하며 `cubrid hb start`는 copylogdb/applylogdb 시작 전에 이 검사를 실행하고 실패 시 전체 시작을 중단한다.
- 근거: `src/executables/util_cs.c:2928-2950,3320-3393`, `src/executables/util_service.c:3194-3249,3963-3978`.
- 잔여: failover/switchover 재검사 누락은 CF-08에서 별도 확정한다. 별도 catalog epoch 요구는 CUBRID 구조에 맞지 않는다.

### CF-05 — SQL grammar·정규 출력·metadata 계약이 없다

- 판정: `확정`
- 구현된 부분: parser는 ON/OFF와 기본 ON을 처리하고 SHOW CREATE, `db_class.is_replication_class`, unloaddb가 canonical ON/OFF를 출력한다.
- 근거: `src/parser/csql_grammar.y:19891-19996`, `src/object/object_printer.cpp:1137-1145`, `src/object/schema_system_catalog_install_query_spec.cpp:68-75`, `src/executables/unload_schema.c:1794-1800`.
- 확인된 문제: 활성 RK identity는 metadata/API에 노출되지 않고 CCI/JDBC schema-info도 기능 commit에서 확장되지 않았다. `REPLICATION`은 lexer token으로 추가됐지만 일반 identifier 호환 처리가 없어 기존 이름 충돌 위험도 남는다.
- 조치: CF 범위를 “REPLICATION flag 왕복 부재”가 아니라 “활성 RK와 client metadata 부재 및 신규 keyword 호환성”으로 축소해 확정한다.

### CF-06 — 복합 ALTER와 RK DDL의 원자성·crash recovery가 없다

- 판정: `기각`
- 구현 사실: multiple ALTER는 system savepoint로 감싸고 모든 절 처리 후 최종 class 상태에서 RK/FK를 검사하며 실패 시 savepoint까지 rollback한다.
- 근거: `src/query/execute_schema.c:1838-1851,2059-2081`.
- 필터링: 별도 prepare/build/publish 상태 머신을 요구한 부분은 과도하다. ALTER 종류 누락으로 최종 검사가 실행되지 않는 문제는 원자성 문제가 아니라 CF-07/09의 validator coverage 결함으로 분리한다.

### CF-07 — DDL·DML 동시성, 장기 transaction과 온라인 구축 규칙이 없다

- 판정: `확정`
- 기각 부분: class write lock, multiple ALTER savepoint와 단일 log-applier commit 순서가 있어 별도 schema epoch/admission subsystem은 필요하지 않다.
- 확인된 문제: RK 후보 함수는 type, attribute 수와 NOT NULL만 보고 filter predicate, function index와 build/visibility 상태를 확인하지 않는다.
- 근거: `src/base/object_representation_sr.c:4694-4721`, `src/base/object_representation_sr.h`의 `OR_INDEX` 부가 정보, `src/query/execute_schema.c:1843-1851`.
- 조치: partial/function/online-building UNIQUE의 RK 자격을 명시하고 완전히 사용 가능한 index만 publish하도록 한다.

### CF-08 — RK 전환 중 failover의 promotion gate와 앱 보장이 없다

- 판정: `확정`
- 확인된 문제: RK/FK 검사는 `cubrid hb start`와 수동 `hb rkcheck`에만 연결된다. heartbeat의 failover/switchover/failback promotion 경로에는 동일한 검사 호출이 없다.
- 근거: `src/executables/util_service.c:3194-3249,3969,5041-5043`; `master_heartbeat.c`, `src/connection/`과 boot 경로에는 `rkcheck`/RK constraint 검사 참조가 없다.
- 필터링: generic LSA/apply-state promotion gate는 이미 존재하므로 새 client fencing token 요구는 폐기한다. 확정 결함은 promotion 전에 replication constraint 상태를 재검증하지 않는다는 점이다.

### CF-09 — 키 타입·collation·복합 값·old/new UPDATE 의미가 없다

- 판정: `확정`
- 확인된 문제: client-side RK 존재 검사는 복합 UNIQUE 컬럼 중 하나라도 NOT NULL이면 후보로 인정하지만 server-side DML 후보 함수는 모든 컬럼 NOT NULL을 요구한다. `(x NOT NULL, y NULL) UNIQUE`가 HA 검사를 통과한 뒤 실제 복제 key로 선택되지 않을 수 있다.
- 근거: `src/object/class_object.c:95-98`, `src/object/schema_manager.c:16108-16130`, `src/base/object_representation_sr.c:4712-4719`.
- 기각 부분: UPDATE는 old RK 값을 로그에 기록하고 replica도 그 값으로 조회한다(`src/transaction/locator_sr.c:8757-8821`). B-tree lookup은 schema collation을 사용하므로 일반적인 old/new·collation 오적용 전제는 성립하지 않는다.

### CF-10 — FK·trigger·cascade와 ON/OFF 혼합 transaction 계약이 없다

- 판정: `기각`
- 구현 사실: FK는 replication class마다 직접 참조 대상의 ON/OFF를 검사하고 `rkcheck`가 모든 class를 순회한다. DML replication log는 대상 class flag를 확인하며 cascade 결과도 일반 row replication 경로를 사용한다.
- 근거: `src/query/execute_schema.c:9783-9802,9861-9880`, `src/executables/util_cs.c:3322-3349`, `src/transaction/locator_sr.c:8041-8049,8421-8426`.
- 잔여: 동작을 스펙에 명문화하는 문서 보완은 가능하지만 새로운 provenance나 mixed-transaction protocol이 없다는 이유로 결함을 유지하지 않는다.

### CF-11 — OFF 의존 VIEW와 데이터 의존 객체가 정상처럼 다른 결과를 낸다

- 판정: `확정`
- 확인된 문제: CREATE VCLASS 경로는 replication constraint 검사를 호출하지 않으며 `rkcheck`도 VCLASS를 명시적으로 건너뛴다. OFF table을 직접·다단계 참조하는 VIEW는 생성과 HA 시작 어느 시점에도 진단되지 않는다.
- 근거: `src/query/execute_schema.c:10186-10211,10267-10274`, `src/executables/util_cs.c:2922-2945`.
- 필터링: materialized view나 CUBRID에 없는 객체까지 확장한 내용은 폐기한다. 확정 범위는 CUBRID VCLASS/VIEW dependency 진단이다.

### CF-12 — fail_count만으로 정상성과 영향 범위를 알 수 없다

- 판정: `기각`
- 구현 사실: `_db_ha_apply_info`는 fail counter 외에도 committed/rep/append/eof/final/required LSA, log record/commit/access time, 상태와 DML/schema/commit counter를 유지한다.
- 근거: `src/transaction/log_applier.c:393-416,1535-1559,1674-1684,7244-7277`.
- 필터링: “fail_count만 존재해 지연과 정지를 구분할 수 없다”는 전제는 틀렸다. 활성 RK와 오류별 class/key 노출 부족은 CF-02와 CF-25에서 좁혀 다룬다.

### CF-13 — 기존 불일치의 탐지·수리·재가입 절차가 없다

- 판정: `코드무관`
- 구현 사실: `checksumdb`가 이미 schema/row checksum과 resume 정보를 제공하고 후속 commit `44468ed73`도 checksum 방식을 수정한다.
- 필터링: 새 RK 기능이 과거 불일치를 자동 수리해야 한다는 요구는 기능 구현 결함으로 승격하지 않는다. checksumdb가 UK-only RK table을 올바르게 처리하는 회귀 시험과 승인형 repair/rebuild runbook은 운영 문서 과제로 남긴다.

### CF-14 — unloaddb/loaddb 기본값과 부분 실패 계약이 상충한다

- 판정: `코드무관`
- 구현 사실: 코드의 무표기 기본값은 ON이고 새 unloaddb는 모든 table에 ON/OFF를 명시한다. loaddb의 기존 line/statement resume 체계도 그대로 사용된다.
- 근거: `src/query/execute_schema.c:96-97`, `src/parser/csql_grammar.y:19990-19996`, `src/executables/unload_schema.c:1794-1800`.
- 조치: 스펙 9절의 무표기=OFF 문장을 ON으로 고치는 문서 결함이다. 새 manifest나 ledger 요구는 폐기한다.

### CF-15 — backup·snapshot·PITR이 RK 세대와 시점을 함께 보존하지 않는다

- 판정: `코드무관`
- 구현 사실: REPLICATION은 `SM_CLASSFLAG_DATA_REPLICATION_OFF` catalog flag이고 physical backup/PITR는 catalog page와 WAL을 보존한다. 기능 commit은 별도 out-of-band RK metadata를 만들지 않는다.
- 근거: `src/object/class_object.h:312`; 기능 diff에 backup/restore format 변경이 없다.
- 필터링: 별도 RK manifest·epoch range 요구는 현재 구현에 맞지 않는다. backup/restore 회귀 시험과 지원 절차 문서화만 남긴다.

### CF-16 — rolling upgrade·기능 활성화·downgrade 경계가 없다

- 판정: `코드무관`
- 구현 사실: 기능은 class flag, 새 grammar와 RK 선택 동작을 추가하지만 독립적인 feature negotiation protocol은 추가하지 않는다. CUBRID의 release/log compatibility 체계는 별도로 존재한다.
- 필터링: mixed-version HA와 downgrade 지원 여부는 릴리스 정책 결정이다. 지원한다고 결정할 경우에만 구버전 parser/catalog/log 적용 시험과 activation fence를 요구한다.

### CF-17 — 넓은 RK와 온라인 구축의 성능·용량 기준이 없다

- 판정: `코드무관`
- 구현 사실: 선택 UK는 기존 B-tree index와 DB_VALUE packing 경로를 재사용한다. 넓은 key의 index/log/network 비용은 존재하지만 새 shadow index나 online RK builder는 구현하지 않았다.
- 필터링: 자동 구축 throttle/resume 요구는 폐기하고, 기존 CUBRID index key 한계와 apply 성능 경고·시험을 스펙/성능 계획에 남긴다.

### CF-18 — 오류 계약·실행 예제·전체 runbook이 부족하다

- 판정: `코드무관`
- 구현 사실: 기능은 RK 필요, HA 중 option 변경 금지, FK 위반과 HA start 위반에 고유 `ER_*` 코드와 양 언어 message를 추가했다.
- 근거: `src/base/error_code.h`, `msg/en_US.utf8/cubrid.msg`, `msg/ko_KR.utf8/cubrid.msg`의 신규 HA replication 오류.
- 조치: 스펙의 `ERROR` placeholder, trailing comma, 불완전 DROP/ADD 예시를 실제 code/message와 실행 가능한 SQL로 고친다. 이는 구현 결함이 아닌 문서 개정이다.

### CF-19 — 복제 정책 변경의 최소 권한·감사 원자성이 없다

- 판정: `확정`
- 확인된 문제: `do_alter_change_replication()`은 HA disabled 여부와 일반 class write/ALTER 경로만 사용하며 REPLICATION 전용 권한 분리나 durable audit event를 추가하지 않는다.
- 근거: `src/query/execute_schema.c:11730-11826`; 기능 diff에 auth bit 또는 audit catalog 변경이 없다.
- 완화: HA 가동 중에는 방향과 관계없이 option 변경이 거부된다.
- 조치: 기존 ALTER 권한을 의도한 정책인지, DBA/system 전용인지 스펙에서 결정하고 변경 이력 요구도 명시한다. 무조건 새 privilege bit를 만들라는 요구로 단정하지 않는다.

### CF-20 — partition·상속·sharding의 유일성과 정책 상속이 없다

- 판정: `폐기`
- 폐기 이유: CUBRID는 partitioned class의 UNIQUE/PK에 partition key가 포함되도록 강제하므로 “서로 다른 partition에 같은 단일 RK 값” 예제가 생성 단계에서 거부된다. broker sharding과 engine partition을 같은 객체 모델로 보는 전제도 맞지 않는다.
- 근거: `src/object/schema_manager.c`의 partition unique constraint 검사와 `ER_SM_INVALID_UNIQUE_IDX_PARTITION`.
- 보존 범위: REPLICATION flag가 root/child partition에서 어떻게 보이는지 문서화하고 composite RK의 partition-key UPDATE 시험은 남긴다.

### CF-21 — TRUNCATE·bulk·CTAS·clone·특수 객체 경로가 정책을 우회한다

- 판정: `확정`
- 구현 사실: CREATE LIKE는 source REPLICATION flag를 상속하고 CTAS는 기본 ON과 RK 검사를 거친다. loaddb의 HA/SA 경계도 기존 경로에서 처리된다.
- 확인된 문제: `PT_RENAME_ENTITY`는 RK/FK 재검사 gate에 포함되지 않아 OFF table을 운영 이름으로 바꾸는 shadow swap이 DDL 시점 검사를 우회한다.
- 근거: `src/query/execute_schema.c:109-114,2051-2068,10258-10274`.
- 조치: rename/swap 후 대상 이름과 dependency graph를 재검사한다. 일반적인 “모든 특수 경로가 우회한다”는 문구는 제거한다.

### CF-22 — parallel apply·log 보관·codec의 장기 계약이 없다

- 판정: `폐기`
- 폐기 이유: 현재 applylogdb는 transaction/commit LSA 순으로 적용하며 parallel apply worker drain을 사용하지 않는다. duplicate skip, required/final LSA, archive 관리, page checksum과 release compatibility가 기존에 있다.
- 근거: `src/transaction/log_applier.c`의 `la_apply_repl_log()` 및 LSA state, `src/transaction/log_page_buffer.c`, `src/base/release_string.c`.
- 재검토 조건: 실제 parallel apply 또는 새 versioned RK payload를 도입할 때 schema barrier와 codec migration 요구를 다시 적용한다.

### CF-23 — resource 고갈·손상·반복 실패의 안전 상태가 없다

- 판정: `판정불가`
- 정적 확인: schema 변경은 기존 savepoint/WAL을 사용하고 applylogdb에는 ignore/retry/reconnect 경로가 있다. 따라서 “rollback 규칙 자체가 없다”는 주장은 약하다.
- 남은 위험: OFF table은 DML log 생성을 건너뛰지만 모든 DDL은 statement replication되므로 diverged replica에서 DDL apply 실패가 반복될 수 있다. ENOSPC/OOM/부분 flush와 retry 폭주 결과는 정적 분석만으로 최종 판정할 수 없다.
- 필요한 시험: OFF table을 의도적으로 diverge시킨 뒤 constraint DDL, apply 실패·재시작, ENOSPC/OOM fault injection을 수행해 fail counter, apply state, 재시도 상한과 승격 가능 여부를 확인한다.
- 근거: `src/query/execute_statement.c:393-399,16502-16517`, `src/transaction/log_applier.c`의 retry/partial flush 경로.

### CF-24 — network partition·split-brain·다중 topology의 fencing이 없다

- 판정: `폐기`
- 폐기 이유: CUBRID HA는 heartbeat/ping/priority와 server update gate로 split-brain을 다루며 active-active/multi-writer catalog lease model이 아니다. RK만을 위해 quorum, client token과 catalog fencing epoch를 요구하는 것은 기능 범위를 벗어난다.
- 근거: `src/executables/master_heartbeat.c`, `src/connection/server_support.c`의 HA state/update enable 전환.
- 보존 범위: RK DDL/DML이 기존 HA state gate를 우회하지 않는 시험은 남긴다.

### CF-25 — 진단 telemetry에 RK 개인정보가 노출된다

- 판정: `확정`
- 확인된 문제: applylogdb는 실패 key를 `db_sprint_value()`로 문자열화해 error/reconnect message와 SQL log에 넣는다. email/전화번호 UK가 RK가 되면 원문 개인정보가 기록될 수 있다.
- 근거: `src/transaction/log_applier.c:4791-4838`, `src/transaction/log_applier_sql_log.c`의 key WHERE 출력.
- 필터링: 입증되지 않은 metric label/trace/quarantine 주장은 제거한다. CUBRID error/apply SQL log의 기본 redaction 또는 opt-in 상세 로깅 정책만 확정 요구로 남긴다.

### CF-26 — ORM·driver·schema diff·cache·CDC 계약이 없다

- 판정: `확정`
- 확인된 문제: 기능 commit은 SHOW CREATE와 `db_class`만 확장하고 CCI/CAS schema-info, JDBC metadata와 CDC schema/key interface를 확장하지 않았다. 활성 RK도 공개되지 않는다.
- 근거: 기능 diff 34개 파일에 `src/broker/`와 CCI/JDBC metadata 변경이 없고, `src/object/object_printer.cpp`, `src/object/schema_system_catalog_install_query_spec.cpp`에는 ON/OFF만 추가됐다.
- 조치: 공식 지원 표면에 한해 catalog→CCI/JDBC/CDC metadata와 schema 재조회 동작을 명세한다. 모든 ORM 지원 보장은 제거한다.

### CF-27 — index rebuild·rename·optimizer와 논리 RK의 관계가 없다

- 판정: `확정`
- 확인된 문제: RK 선택은 논리적으로 영속된 identity가 아니라 class representation의 첫 physical candidate다. PK 추가나 index 순서 변화로 활성 RK가 무경고 변경되고 replica도 자기 BTID를 재계산한다.
- 근거: `src/object/class_object.c:82-98`, `src/storage/btree.c:8285-8298`, `src/base/object_representation_sr.c:4692`.
- 필터링: optimizer plan 결합 일반론은 제거한다. rebuild/PK 추가 전후 논리 RK 유지 여부, 새 BTID mapping과 사용자-visible change notification을 확정 요구로 남긴다.

### CF-28 — 제품 목표·대안·지원 범위·성공 지표가 없다

- 판정: `코드무관`
- 구현 사실: 기능은 PK 또는 all-NOT-NULL UNIQUE를 server candidate로 사용하고 무키 ON table을 HA에서 거부하며 OFF fallback을 제공한다.
- 필터링: 모든 컬럼 fallback, 무키 업무 table 지원률과 KPI는 제품 설계·기획 영역이다. 스펙에는 PK, 복합 UK, partition, partial/function index와 무키 table의 지원 matrix만 남긴다.

### CF-29 — tenant·법적 보존·장기 지원 정책이 없다

- 판정: `폐기`
- 폐기 이유: 기능은 class 단위 ON/OFF catalog flag이며 tenant row별 RPO, edition entitlement 또는 법적 보존 engine이 아니다.
- 근거: `src/object/class_object.h:312`, `src/object/schema_manager.c:3390-3402`.
- 재검토 조건: shared-table tenant별 replication/retention이나 edition 차등이 제품 범위에 들어올 때다.

### CF-30 — 상태 공간을 포괄하는 test oracle과 추적성이 없다

- 판정: `코드무관`
- 확인 사실: `develop..feature` diff에는 이 기능 전용 unit/integration test file이 포함되지 않는다. 다만 외부 `cubrid-testcases`의 존재 가능성 때문에 “자동 시험이 전혀 없다”고 단정하지 않는다.
- 조치: 확정 12건과 판정불가 CF-23을 parser/catalog/RK selection/DDL gate/rkcheck/failover/replication/apply/metadata 시험에 연결한다. 모든 문장을 자동화하기보다 정합성 불변식과 지원 matrix를 추적한다.

## 확정 이슈만 다시 모아보기

1. CF-01/02/27 — master·replica가 첫 physical candidate를 독립 재계산하고 활성 RK identity가 영속·노출되지 않는다.
2. CF-05/26 — REPLICATION flag 일부 표면은 구현됐지만 활성 RK와 CCI/JDBC/CDC metadata가 빠졌다.
3. CF-07 — partial/function/online-building UNIQUE를 RK 후보에서 제외하는 조건이 없다.
4. CF-08 — `rkcheck`가 HA start에는 있지만 promotion 경로에는 없다.
5. CF-09 — client의 복합 UK NOT NULL 검사가 “전부”가 아니라 “하나라도”로 구현됐다.
6. CF-11 — OFF table 의존 VCLASS/VIEW를 생성·기동 검사 모두 건너뛴다.
7. CF-19 — REPLICATION 변경의 전용 권한·감사 정책이 없다.
8. CF-21 — RENAME/shadow swap이 replication constraint 재검사를 우회한다.
9. CF-25 — apply/error SQL log가 RK 원문을 노출할 수 있다.

## 런타임 확인이 필요한 항목

- CF-23: diverged OFF table의 DDL apply 실패, 반복 retry, ENOSPC/OOM/부분 flush와 승격 상태.
- 별도 보안 시험 권고: TDE table의 replication log/network/file에 RK가 평문으로 남는지. 이 항목은 정적 코드만으로 확정하지 않았다.

## 확인 한계

- compile DB의 source/include는 feature worktree를 가리키지만 build directory와 생성 header는 develop debug build를 재사용한다.
- `cubrid-jdbc`는 이 worktree에서 초기화되지 않아 Java `DatabaseMetaData` 구현은 직접 추적하지 못했다.
- 외부 HA/SQL regression repository의 전체 시험 보유 여부는 이 저장소만으로 단정하지 않았다.
