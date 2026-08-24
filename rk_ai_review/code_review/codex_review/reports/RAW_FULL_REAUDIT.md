# CBRD-26246 raw 전수 재조사 작업표

> 이 파일은 작업 중 감사표다. 기존 187개 관찰과 최종 16개를 정답으로 전제하지 않는다.
> 최종보고서는 전체 조사와 판정이 끝난 뒤에만 갱신한다.

## 세션 재개 체크포인트

- 마지막 갱신: 2026-08-24 (Asia/Seoul)
- 전체 진행: **100% 완료**
- source 상태: `/home/youngjun/Workspace/claude` detached HEAD, 작업 시작 시 clean
- review 상태: 재감사 산출물과 독립형 `최종보고서.md` 작성 및 QA 완료.

### 완료된 범위

1. `merge-base → feature` 기준 35개 변경 파일의 모든 diff hunk를 1차 검토했다.
2. `develop → feature` 직접 diff가 develop의 191개 후속 commit을 역변경처럼 섞는다는 점을 확인했다.
   따라서 feature 귀속은 반드시 `merge-base → feature`, 후속 해결 여부는 `merge-base → develop`로 분리한다.
3. parser/DDL/catalog/DML log/apply/HA start의 핵심 함수와 자료구조를 1차 연결했다.
4. failover·failback·restart·rejoin 운영 상태 전이의 주요 진입 함수를 식별했다.
5. 기존 CR-02의 정확한 실행 흐름을 정정했다. client와 slave가 서로 다른 predicate를 호출하는 문제가
   아니라, mixed-null composite UNIQUE가 DDL/rkcheck를 통과한 뒤 master runtime에서 RK를 찾지 못해
   log 자체를 만들지 않는 경로다. 따라서 applier는 호출되지 않는다.
6. `heap_is_replication_class` 관련 항목은 사용자 요청대로 `heap_get_class_repl_on` 교체를 가정하며
   재감사 후보와 최종 문서에서 제외한다.
7. NEW-001의 CREATE 주장은 기각하고 ALTER VCLASS metadata 허용 문제로 범위를 축소했다.
8. CR-02~05·12·13·16·17의 2차 판정을 아래 재검증 표에 기록했다. CR-17은 public header 설치
   경로를 확인해 오분석으로 확정했고, CR-05는 실제 노드 간 index 순서 분기 경로가 없어 입증 보류다.
9. CR-04는 filtered UNIQUE의 INSERT/DELETE log 누락뿐 아니라 UPDATE가 존재하지 않는 filtered key로
   log를 만들 수 있는 경로까지 확인했다.
10. 운영 상태 전이를 2차 판정했다. heartbeat의 단순 자동 재시작과 failback은 독립 결함으로 확정하지
    않았고, promotion 문제는 CR-06/07처럼 invalid RK catalog를 실제로 만드는 선행 결함과 결합될 때만
    데이터 손실 경로가 성립한다고 범위를 좁혔다.
11. 진단·성능 후보를 다시 확인했다. `rkcheck`의 NULL `FILE *` 사용은 확정 후보, 분 단위 결과 파일
    덮어쓰기는 운영 정책 후보, OFF class의 RK 후보별 class-record 반복 조회는 현재 HEAD에도 남은
    성능 후보로 판정했다. 사용자가 제외하도록 한 helper 교체 여부 자체와는 별개다.
12. 공통 조상을 기준으로 feature와 develop을 분리 비교했다. CR-12는 rollback 부재가 develop에도
    있었고 feature가 rkcheck라는 추가 실패 지점을 만든 `develop 기존/feature 악화`로 정정했다.
    나머지 강한 RK·SBR·진단 축은 feature 신규 또는 feature 신규 상호작용으로 판정했다.
13. GitHub closed-PR 목록을 2026-08-24에 다시 확인하고 로컬 공식 remote commit graph와 대조했다.
    #7370은 closed/unmerged, #6908·#7697은 merged이며 현재 feature HEAD가 결과 commit을 포함한다.
    #7697은 helper 오류전파 문제만 해결했고 OFF class 반복 조회 성능 후보는 현재 HEAD에 잔존한다.
14. `reports/E2E_FINDING_WORKSHEETS.md`를 만들고 CR-02, CR-03, CR-04의 INSERT/DELETE·UPDATE,
    CR-06, CR-07, CR-09에 대해 최소 상태·입력·master/log/applier/slave 순서·대조 조건을 고정했다.
    특히 CR-02는 applier 불일치가 아니라 master 무로그임을 문서 자체만으로 확인할 수 있게 했다.
15. E2E 작업표를 CR-10~15, NEW-004, NEW-008까지 확장하고 조건부·오분석·운영 권고도 삭제하지 않고
    분리했다. `RAW_187_REAUDIT_MAP.md`에는 20개 페르소나 187개 원문을 새 판정 축으로 연결하고,
    각 직군이 최대 50건 전에 후보가 소진되어 종료됐음을 명시했다.
16. 20개 페르소나 원문 각각의 첫머리에 전수 재감사 알림을 넣었다. 최초 의견은 보존하되 CR-02·05·08·
    12·13·16·17의 정정 상태, 최신 E2E 문서 우선순위, 해당 페르소나의 실제 발견 수와
    `더 이상 발견되지 않음` 종료를 개별 파일만 읽어도 알 수 있다.
17. `CANDIDATE_AUDIT.md`의 기존 16건 전제를 폐기하고 재집계했다. 확정 feature 결함 10건, 조건부 2건,
    develop 기존/feature 악화 1건, 운영 권고 1건으로 분리했으며 입증 보류·오분석·후속 해결 항목은
    원문을 지우지 않고 보존표에 남겼다.
18. `최종보고서.md`를 독립형 재감사 결과로 교체하고 기능 목적·방법·수량과 확정 10건의 최소 입력,
    실제 코드/출처 포함 의사 흐름, master/log/applier/slave 결과, develop 대조, 권고를 작성했다.
19. 최종보고서에 조건부 CR-13/15, develop 기존 CR-12, 운영 권고 OPS-01, 비채택 근거와
    failover/failback/restart 상태표, 수정 우선순위와 E2E 수용 기준까지 추가했다.
20. 작업지시에 E2E·운영·helper 교체 가정·원문 보존 조건을 반영하고 `README.md`에 최종본 우선의
    문서 동선을 만들었다. clangd 표적 검사를 재실행해 결과와 한계를 최종보고서에 기록했다.
21. 최종보고서와 핵심 보조 문서의 ID·수량·Markdown fence·상대 링크·오래된 16건 표현을 점검했다.
    16건 언급은 모두 “기존 결과가 왜 바뀌었는지” 설명하는 문맥뿐이며 최신 결론은 확정 10건으로
    일치한다. feature source의 detached HEAD와 clean 상태도 다시 확인했다.
22. 최종 재독에서 CR-15의 함수 출처가 잘못 적힌 두 곳을 실제 정의인
    `src/query/execute_schema.c:9818-9840`으로 바로잡았다. 확정 finding heading 10개, 페르소나 알림
    20개, feature coverage 35개 파일, 빈 산출물 0개와 source clean 상태를 최종 확인했다.
23. 팀 공유용 재독을 수행했다. 상위 `README.md`와 `최종보고서.md`만 공유 대상으로 지정하고
    `작업지시.md`와 `reports/`는 내부 감사 자료로 분류했다. 최종본의 로컬 경로·내부 LSP 로그를 줄이고,
    CR-04/06/07의 SQL 선행 조건과 constraint 이름, CR-09의 실제 multi-table grammar 근거를 보강했다.

### 완료 후 남은 제한

- 두 노드 HA 환경에서 SQL fixture를 실제 수행하는 동적 재현은 이번 정적 코드 리뷰에 포함하지 않았다.
- CR-09의 구체 parser fixture와 PERF-01 wall-clock benchmark는 수정 PR의 회귀 테스트로 남겼다.

### 재개 시 금지할 지름길

- 기존 16건을 정답으로 놓고 신규 후보만 추가하지 않는다.
- 코드에 `rkcheck` 호출이 없다는 사실만으로 HA 결함을 확정하지 않는다.
- master와 applier가 같은 server predicate를 쓰는지 확인하지 않고 client/server 차이를 데이터 오적용으로
  일반화하지 않는다.
- 키워드 검색 결과만으로 확정하지 않고 실제 caller/callee와 SERVER/CS/SA mode를 대조한다.
- develop 기존 문제와 후속 PR 해결 항목은 삭제하지 않고 상태를 표시한다.

## 조사 기준

- 대상: `/home/youngjun/Workspace/claude@9e094324b8ef`
- 비교: `upstream/develop@5b9c0d8155f8`
- 공통 조상: `b646647eca4236057ea7c3c28960e61c53b0c209`
- 범위: 공통 조상 대비 feature 고유 변경 35개 파일, `+1,444/-57`, 모든 diff hunk와 영향 caller/callee
- 삼자 비교: `merge-base → feature`로 feature가 실제 추가한 코드를 식별하고,
  `merge-base → develop`로 분기 뒤 develop 변경을 식별한다. `develop → feature`
  직접 diff에 보이는 역방향 차이는 삭제하지 않고 `develop 후속 변경 미반영`으로 표시한다.
- 기존 raw: 20개 페르소나 보고서의 187개 관찰을 seed로 사용
- 탐색 상한: 기존 작업지시와 동일하게 페르소나별 최대 50건, 전체 이론상 최대 1,000건
- 조기 종료: 50건 전에 해당 페르소나 관점에서 근거 있는 후보가 소진되면 `더 이상 발견되지 않음`과 마지막으로 확인한 coverage를 기록
- 종료 조건: 미검토 hunk, 미추적 symbol, 호출 경로 미완성 후보, 비교 미완성 후보가 모두 0건

## 후보 판정에 필요한 증거

각 raw 후보에는 아래 항목을 모두 채운다.

1. 해당 분기에 진입하는 최소 내부 상태
2. 필요한 schema·data·HA 조건
3. master → replication log → applylogdb → slave server 실행 순서
4. 결함이 발생하는 최소 SQL 또는 의사 입력
5. 문제가 발생하지 않는 대조 조건
6. `upstream/develop` 비교
7. 관련 PR 및 현재 HEAD 잔존 여부
8. `확정`, `재현 확인`, `조건부`, `오분석`, `비회귀`, `후속 해결` 중 판정

HA 관련 후보는 추가로 다음 운영 상태 전이를 모두 대조한다.

- 최초 start와 정상 stop
- failover와 standby → ACTIVE 승격
- failback/switchover와 기존 master의 재합류
- 장애 후 server/copylogdb/applylogdb restart
- 다중 DB 중간 실패와 부분 기동 rollback
- 반복 start/stop, stale PID와 heartbeat registration
- log gap·schema/RK readiness, write fencing과 rejoin

## 변경 파일 coverage

| 영역 | 파일 | 상태 |
|---|---|---|
| message | `msg/en_US.utf8/cubrid.msg` | 1차 검토 완료 |
| message | `msg/en_US.utf8/utils.msg` | 1차 검토 완료 |
| message | `msg/ko_KR.utf8/cubrid.msg` | 1차 검토 완료 |
| message | `msg/ko_KR.utf8/utils.msg` | 1차 검토 완료 |
| base | `src/base/error_code.h` | 1차 검토 완료 |
| base | `src/base/object_representation_sr.c` | 1차 검토 완료 |
| base | `src/base/object_representation_sr.h` | 1차 검토 완료 |
| utility | `src/executables/checksumdb.c` | 1차 검토 완료 |
| utility | `src/executables/unload_schema.c` | 1차 검토 완료 |
| utility | `src/executables/util_admin.c` | 1차 검토 완료 |
| utility | `src/executables/util_cs.c` | 1차 검토 완료 |
| utility | `src/executables/util_service.c` | 1차 검토 완료 + 운영 caller 추적 중 |
| utility | `src/executables/utility.h` | 1차 검토 완료 |
| object | `src/object/class_object.c` | 1차 검토 완료 |
| object | `src/object/class_object.h` | 1차 검토 완료 |
| object | `src/object/object_printer.cpp` | 1차 검토 완료 |
| object | `src/object/schema_manager.c` | 1차 검토 완료 |
| object | `src/object/schema_manager.h` | 1차 검토 완료 |
| catalog | `src/object/schema_system_catalog_install.cpp` | 1차 검토 완료 |
| catalog | `src/object/schema_system_catalog_install_query_spec.cpp` | 1차 검토 완료 |
| object | `src/object/schema_template.c` | 1차 검토 완료 |
| parser | `src/parser/csql_grammar.y` | 1차 검토 완료 |
| parser | `src/parser/csql_lexer.l` | 1차 검토 완료 |
| parser | `src/parser/parse_tree.h` | 1차 검토 완료 |
| parser | `src/parser/parse_tree_cl.c` | 1차 검토 완료 |
| parser | `src/parser/semantic_check.c` | 1차 검토 완료 |
| query | `src/query/execute_schema.c` | 1차 검토 완료 + E2E 추적 중 |
| query | `src/query/execute_schema.h` | 1차 검토 완료 |
| query | `src/query/execute_statement.c` | 1차 검토 완료 + E2E 추적 중 |
| query | `src/query/parallel/px_worker_manager.cpp` | 1차 검토 완료 |
| storage | `src/storage/btree.c` | 1차 검토 완료 + E2E 추적 중 |
| storage | `src/storage/btree.h` | 1차 검토 완료 |
| storage | `src/storage/heap_file.c` | 1차 검토 완료 |
| storage | `src/storage/heap_file.h` | 1차 검토 완료 |
| transaction | `src/transaction/locator_sr.c` | 1차 검토 완료 + E2E 추적 중 |

## 신규 발굴 후보

전체 호출 경로가 검증되기 전에는 후보를 삭제하지 않는다.

| 임시 ID | 주장 | 최초 발견 위치 | 상태 |
|---|---|---|---|
| NEW-001 | 최초의 `CREATE VCLASS ... REPLICATION=OFF` 주장은 오분석이다. 해당 `create_stmt`는 `of_class_table_type`을 사용해 `CLASS|TABLE`만 받는다. 그러나 `ALTER [VIEW|VCLASS] ... REPLICATION`은 `opt_class_type`과 공용 `alter_clause_list`를 통해 파싱되고 `pt_check_alter()`가 `PT_CHANGE_REPLICATION`을 class-only로 제한하지 않아, HA disabled 환경에서 VCLASS에도 data-replication flag를 저장할 수 있다. VCLASS는 rkcheck와 row replication 대상에서 제외되므로 현재 입증된 영향은 무의미한 metadata 허용과 향후 의미 충돌이다. | `csql_grammar.y:2565-2603,3533-3595,4169-4201,5777-5871,8883-8891`, `semantic_check.c:4785-4920`, `execute_schema.c:11720-11819` | CREATE 주장 기각; ALTER metadata 품질 후보로 축소 |
| NEW-002 | heartbeat가 장애 프로세스를 `execv()`로 자동 재시작하는 경로에는 `rkcheck`가 없다. 최초 start를 통과한 동일 catalog라면 문제가 없다는 대조 조건이 있으므로, crash/recovery 중 catalog 불일치 또는 검사 우회 DDL 뒤에만 독립 결함인지 CR-13과 중복인지 판정한다. | `master_heartbeat.c:3071-3193`, `util_service.c:3949-3980` | 독립 후보 기각; invalid catalog 선행 시 CR-13의 재시작 증폭 조건으로 병합 |
| NEW-003 | failback/switchover의 ACTIVE↔STANDBY 상태 전이는 log-applier 상태와 client drain은 확인하지만 RK/FK 구조를 재검사하지 않는다. CR-13의 promotion gate 누락에 포함할지, 재합류 노드의 별도 readiness/fencing 문제인지 판정한다. | `server_support.c:1657-1735,1885-1967`, `master_heartbeat.c:3791-3839,4356-4503` | 독립 후보 기각; 기존 client fencing/drain 존재, invalid catalog가 있을 때만 CR-13에 병합 |
| NEW-004 | `rkcheck` 결과 파일명이 분 단위라 같은 DB에서 1분 안에 재시도하면 `fopen(..., "w")`가 직전 장애 증거를 덮어쓴다. 반복 start/recovery 때 진단 보존 요구와 제품의 기존 utility 파일 정책을 대조한다. | `util_cs.c:2839-2863` | 코드 사실 확정; 운영 진단 보존 정책 후보(기능 정합성 finding과 분리) |
| NEW-005 | 선언부에는 정의되지 않는 `get_print_flags()`가 남고 실제 함수는 `get_repl_check_flags()`다. 빌드 차단 여부보다 신규 utility의 미사용 정적 선언과 리뷰되지 않은 잔재인지 확인한다. | `util_cs.c:187,2866` | 기능 후보 기각; 미사용 static 선언인 품질 정리 항목 |
| NEW-006 | heartbeat start는 아직 따라잡지 못한 로컬 catalog에 `rkcheck`를 먼저 실행하고, 성공해야 copylogdb/applylogdb를 시작한다. 오래된 backup/장애 시점에는 RK 위반 상태지만 뒤쪽 DDL log가 RK를 복구하는 경우 apply가 그 log까지 갈 기회를 얻지 못해 기동이 자기 봉쇄될 수 있다. 반대로 검사 후 적용되는 DDL은 최초 검사 snapshot 밖이다. | `util_service.c:3949-3980`, `util_cs.c:3310-3358` | restore/rejoin 최소 상태·기존 HA 운용 절차 확인 중 |
| NEW-007 | 검사는 ON class가 OFF class를 참조하는 FK만 거부하고 OFF child→ON parent는 허용한다. ON parent의 `ON DELETE CASCADE`를 master에서 실행하면 OFF child의 파생 delete 자체는 로그가 억제되지만, slave가 parent delete를 force할 때 `locator_check_primary_key_delete()`의 CASCADE 분기는 log-applier도 실행하므로 OFF child가 간접 삭제된다. 무결성은 유지되지만 “OFF 데이터는 복제하지 않는다”는 문구와 실제 cascade 의미가 충돌한다. ON child일 때는 child log가 parent log보다 먼저 기록되어 slave의 이중 삭제를 피하는 대조 순서도 확인했다. | `execute_schema.c:9782-9802,9861-9879`, `locator_sr.c:4248-4277,4427-4470,8002-8055` | 코드 결함보다 미정 운영 계약인지 판정 중 |
| NEW-008 | INSERT/DELETE index loop는 각 RK 후보 안에서 class record를 fetch한다. ON class는 첫 성공 후보 뒤 멈추지만 OFF class는 `replicated`가 끝까지 false라서 NN UNIQUE 후보마다 같은 class catalog page를 다시 읽는다. UPDATE도 교체 예정 helper를 같은 후보 조건 안에 그대로 둘 경우 동일하다. OFF bulk DML의 index 수 비례 catalog fetch/lock 비용을 측정한다. | `locator_sr.c:7861-8057,8425-8433`, `heap_file.c:11075-11115` | 현재 HEAD 실행 경로 확인; Low 성능 후보 유지(호출 횟수 계측은 미완료) |

## 운영 상태 전이 1차 호출 그래프 판정

| 전이 | 실제 호출과 검사 | 현재 판정 |
|---|---|---|
| 정상 최초 start | `us_hb_server_start()` → `us_hb_process_rkcheck()` → copylogdb → applylogdb | 신규 gate는 있으나 중간 실패 rollback이 없어 기존 CR-12는 유지 |
| 동일 상태의 server crash/restart | heartbeat의 `hb_resource_job_proc_start()`가 저장된 argv로 곧바로 `execv()` | 이전 start 이후 catalog가 동일하면 재검사 불필요하므로 누락 자체는 결함 아님. 독립 후보는 기각하고 검사 우회 DDL·복구 불일치가 있을 때만 CR-13의 증폭 조건으로 기록 |
| standby → ACTIVE failover | heartbeat가 `SERVER_CHANGE_HA_MODE`를 보내고 server는 `TO_BE_ACTIVE`; 기존 `css_check_ha_log_applier_done()` 뒤 ACTIVE/write enable | log-applier 완료 gate는 이미 존재한다. CR-07의 standalone DROP INDEX로 invalid RK schema가 양 노드에 적용된 뒤 master DML log가 생성되지 않으면 applier는 여전히 done일 수 있다. 이 선행 경로에 한해 CR-13 유지 |
| ACTIVE → STANDBY failback | `TO_BE_STANDBY`에서 신규 client를 차단하고 기존 client drain 후 STANDBY | 기존 client fencing이 존재하고 RK feature가 새로 깨뜨린 직접 경로가 없어 독립 후보 기각. invalid catalog 재합류 영향은 CR-13에 병합 |
| 오래된 backup의 rejoin | server를 먼저 연 뒤 현재 local catalog를 rkcheck하고, 통과해야 copy/apply 시작 | 뒤쪽 DDL log가 위반을 고칠 수 있는 snapshot에서는 자동 start가 막히는 NEW-006 조건 존재; 수동 copy/apply 우회 가능 여부와 공식 절차 확인 필요 |
| 다중 DB start 중 하나 실패 | 앞선 DB server들이 이미 시작된 뒤 다음 DB의 rkcheck에서 중단 | 선행 상태를 되돌리지 않으므로 CR-12의 다중 DB 사례로 유지 |
| 반복 rkcheck/start | 결과 파일명이 분 단위이고 `"w"`로 연다 | 1분 내 재시도 시 직전 진단 덮어쓰기 NEW-004 |
| OFF child → ON parent CASCADE | master의 OFF child row log는 억제되지만 slave parent apply가 cascade 자체를 다시 수행 | 정합성 결함은 확인되지 않음. OFF가 직접 log만 금지하는지 모든 간접 변화를 금지하는지 정책 표시 필요 |

## develop 삼자 비교 2차 판정

`develop..feature` 직접 diff의 역방향 잡음을 피하기 위해 아래 판정은 공통 조상 기준의 두 diff와 각
revision의 함수 본문을 함께 비교했다.

| 후보 축 | `merge-base → feature` | `merge-base → develop` | 귀속 판정 |
|---|---|---|---|
| CR-02/03 RK 후보 판정 | PK 외 UNIQUE 계열을 RK로 확장하면서 client ANY/type-family와 server ALL/type-set이 갈라짐 | RK predicate와 class replication option 없음; PK 하나만 사용 | feature 신규 |
| CR-04 filtered/online UNIQUE | server RK 후보에 UNIQUE를 추가했으나 filter/status를 후보 자격에 반영하지 않음 | PK-only라 filtered UNIQUE를 replication identity로 선택하지 않음 | feature 신규 |
| CR-06/07 RK 제거 DDL | UK도 마지막 RK가 될 수 있어 신규 final validator를 추가했으나 multi-clause head와 DROP INDEX 경로 누락 | class별 ON/OFF와 UK-RK invariant 자체가 없음 | feature 신규 |
| CR-09/10 mixed SBR | class별 ON/OFF와 #6908의 SBR 판정이 결합 | class별 OFF가 없어 동일한 비복제 write/read source 조건이 없음 | feature 신규 상호작용 |
| CR-11 TRUNCATE | 기존 PK 검사 대신 `classobj_find_cons_replication_key()`로 확장했지만 OFF flag는 확인하지 않음 | `truncate_need_repl_log()`는 이미 존재하고 PK table을 SBR 처리하지만 OFF 상태가 없음 | 기존 함수의 feature 신규 상호작용 |
| CR-12 start rollback | server start 뒤 신규 rkcheck failure point 추가 | server start 뒤 copy/apply 실패를 rollback하지 않는 구조가 이미 동일 | **develop 기존/feature 악화**. 삭제하지 않고 표시하며 순수 신규 결함 집계와 분리 |
| CR-13 invalid RK promotion | CR-06/07과 UK-RK 확장으로 log가 사라질 수 있는 선행 상태가 새로 생김 | PK invariant에서 같은 feature 경로 없음 | feature 신규, 선행 결함 의존 |
| CR-14/15, NEW-004 rkcheck 진단 | utility와 결과 파일 신규 | rkcheck utility 없음 | feature 신규 |
| NEW-008 반복 class fetch | 다수 RK 후보 loop 내부에서 class record fetch; OFF면 break되지 않음 | PK-only이며 class별 OFF 판정 자체가 없음 | feature 신규 성능 회귀 |

## 기존 통합 후보 재검증 판정표

이 표는 이전 최종보고서의 16건을 그대로 유지하기 위한 표가 아니다. 반증 또는 더 정확한 실행 경로가
확인되는 즉시 갱신한다.

| 기존 ID | 현재 판정 | 재검증 근거 |
|---|---|---|
| CR-02 | 강한 후보 유지, 설명 정정 | DDL/rkcheck의 ANY-NOT-NULL composite UNIQUE 승인은 통과하지만 master와 slave server가 공통으로 사용하는 ALL-NOT-NULL runtime predicate는 RK를 찾지 못한다. master가 log를 생성하지 않으므로 applier는 호출되지 않는다. |
| CR-03 | 강한 후보 유지 | client unique-family는 REVERSE UNIQUE를 포함하지만 `or_is_replication_candidate_key()`는 `BTREE_UNIQUE`와 PK만 허용한다. CR-02와 같은 master log 미생성 증상이지만 type 집합이라는 독립 수정점이다. |
| CR-04 | 강한 후보 유지, UPDATE 영향 보강 | INSERT/DELETE는 filtered predicate가 false면 `locator_sr.c:7861-7875`에서 replication block 전에 continue해 log가 없다. UPDATE는 `8428-8433`에서 RK index를 먼저 고른 뒤 false/false가 `8474-8480`에서 continue해도 선택값이 남고, `8782-8817`에서 filtered index에 존재하지 않는 old key로 update log를 만들어 slave unique lookup 실패가 가능하다. online-building status도 candidate predicate가 확인하지 않는다. |
| CR-05 | 입증 보류 | log는 RK constraint identity를 싣지 않고 source/applier가 각자 첫 후보를 고르는 것은 사실이다. 그러나 같은 HA DDL stream에서 class representation index 순서가 실제로 달라지는 최소 경로는 아직 입증되지 않았다. TODO는 설계 위험의 증거이지 데이터 오적용의 증거가 아니므로 mismatch 경로가 없으면 조건부/기각한다. |
| CR-06 | 강한 후보 유지 | multi ALTER loop의 현재 절은 `crt_clause`/`alter_code`인데 `execute_schema.c:2051`만 head `alter->info.alter.code`를 검사한다. 첫 절이 comment/rename이고 뒤 절이 마지막 RK DROP이면 final `check_ha_repl_constraint()`가 실행되지 않는다. 첫 절이 관련 절이면 같은 최종 schema가 거부되는 순서 의존성도 대조 조건이다. |
| CR-07 | 강한 후보 유지, 범위 확대 | `IS_REPL_CONSTRAINT_RELATED_ALTER`가 CHANGE/MODIFY와 `PT_DROP_INDEX_CLAUSE`를 빠뜨린다. 더 직접적으로 standalone `DROP [UNIQUE] INDEX ... ON table`은 `do_drop_index()` → `create_or_drop_index_helper(...DO_INDEX_DROP)` 뒤 RK final check가 전혀 없다. 마지막 NN UNIQUE를 제거해 ON table을 RK 없이 만들 수 있다. |
| CR-08 | 오분석/CR-02 종속 | promotion code의 attribute UNIQUE flag와 property가 다르게 보이지만 runtime constraint와 RK 검사는 property에서 재구성된 list를 사용한다. ON root에는 promotion 전 유효 RK가 필요하고 PK/UNIQUE property가 promoted class에 남는다. mixed-null composite만으로 invalid가 되는 경우는 이미 CR-02의 잘못된 승인에 의존하며 독립 promotion 결함을 입증하지 못했다. |
| CR-09 | 강한 후보 유지 | `is_data_repl_log_enabled()`는 multi-table UPDATE/DELETE의 수정 target 중 **하나라도** ON이면 true다. 그러면 `do_statement()`가 transaction 전체 RBR을 억제하고 성공 후 원본 SQL 전체를 하나의 SBR로 기록한다. slave는 SQL을 다시 실행하므로 같은 문장에 포함된 OFF target 변경도 적용된다. |
| CR-10 | 강한 후보 유지 | INSERT는 target만, UPDATE/DELETE는 write target만 검사하고 읽기 source는 의도적으로 제외한다. ON target의 `/*+ USE_SBR */ INSERT ... SELECT` 또는 UPDATE가 OFF source 값에 의존하면 master와 slave가 각자의 비복제 데이터를 읽어 다른 결과를 만든다. OFF source가 양 노드에서 같으면 문제가 없는 대조 조건이다. |
| CR-11 | 강한 후보 유지 | TRUNCATE는 statement replication 대상이고 `truncate_need_repl_log()`가 class ON/OFF flag 없이 RK 존재만 검사한다. OFF+PK/NN-UNIQUE table은 원본 TRUNCATE SQL이 기록되어 slave에서도 실행된다. RK가 없으면 우연히 log가 생기지 않는 것이 대조 조건이다. |
| CR-12 | 강한 후보 유지 | `us_hb_process_start()`가 모든 server를 먼저 시작하고 rkcheck/copy/apply 실패 시 pid 배열만 파기한다. 이미 시작한 server를 stop하거나 앞서 시작한 DB를 rollback하는 호출이 없다. |
| CR-13 | 선행 결함 의존 후보 | promotion에는 기존 log-applier-done gate가 있다. 다만 CR-06/07로 invalid DDL이 양 노드에 적용된 뒤 master DML log가 누락돼도 standby log-applier는 done이 될 수 있다. 이 상태에서 promotion rkcheck가 없어 write-enable 되는 경로를 E2E로 묶어 판정한다. 단순한 “rkcheck 호출 없음” 주장은 폐기한다. |
| CR-14 | 강한 후보 유지 | `open_violation_list_file()`의 `fopen(..., "w")` 결과를 검사하지 않고 `PRINT_SECTION_TITLE(fp, ...)`와 `fprintf(fp, ...)`에 전달한다. log directory 권한·공간·FD 고갈로 open이 실패하면 위반 여부를 보고하기 전에 NULL stream을 사용한다. |
| CR-15 | 조건부 후보 | FK 진단이 참조 class의 PK를 찾은 뒤 `pk_c->name`을 사용하지만 NULL 방어가 없다. 정상 DDL로 생성된 FK에는 PK가 있어 대조 조건이 성립하므로, 손상·legacy catalog를 진단하려는 rkcheck의 방어성 문제로만 유지한다. |
| CR-16 | 사용자 요청에 따라 제외 | 모든 `heap_is_replication_class`가 error-returning `heap_get_class_repl_on`로 교체됐다고 가정한다. 이 변경 자체와 관련된 리뷰는 최종 산출물에서 제거한다. |
| CR-17 | 오분석 | 신규 `-1375~-1378` 상수는 `src/base/error_code.h`에 있고 `dbi.h`/`dbi_compat.h`가 이 헤더를 include한다. `cubrid/CMakeLists.txt:788-793`도 같은 헤더를 public include directory에 설치한다. 별도 `include/error_code.h`가 없다는 사실은 API 누락이 아니다. 최종 finding에서 제거하되 오분석 기록은 보존한다. |

## 수량

- 기존 raw seed: 187
- 신규 raw 후보: 8
- 페르소나별 상한: 50
- 1차 검토 완료 파일: 35/35
- 2차 판정 완료 축: parser/DDL/DML 10개, HA 운영 4개, 진단·성능 5개
- 최종 finding 수: 미확정(기존 16개를 상한이나 정답으로 사용하지 않음)
