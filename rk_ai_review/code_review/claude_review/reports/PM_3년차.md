# PM 3년차 코드 리뷰 — RK/REPLICATION 기능 (feature/CBRD-26246-develop)

> **2차 재리뷰 (2026-08-23, 기준 커밋 `734f4959d`)** — upstream 동기화로 브랜치가
> `44468ed73` + `#7678`(`3b6ebd1a9`, SBR/checksumdb 수정 재적용) + `#7697`(`9e094324b`,
> 인터럽트 assert 근본 수정)까지 확장됐다. 새 diff 범위는 merge-base `b646647ec`...HEAD
> (35파일, +1,444/−57). 1차 리포트의 문제 16건을 새 HEAD 코드에서 한 줄씩 재확인해
> 위치를 갱신했고, 새 diff(특히 #7678/#7697 델타)에서 추가 문제를 찾았으나 억지로 채우지
> 않았다.

## 페르소나 소개

3년차 프로덕트 매니저다. 개발자는 아니지만 요구사항 문서(스펙)와 실제 코드가 어긋나는 지점, 릴리스로 나갈 때 사용자가 마주치는 에러 메시지·유틸리티 출력의 품질, 예전 버전과의 호환성(카탈로그 컬럼, unload/loaddb 포맷, 기존 DDL 동작), 그리고 TODO나 복붙 잔재 같은 "아직 안 끝난 흔적"을 찾는 일을 한다. 이번 리뷰에서는 코드를 한 줄씩 손으로 따라가며(정의 점프·호출부 확인), PR 히스토리에 기록된 논의(암묵지)와 스펙 필터링에서 이미 확정된 18건을 출발점 삼아, 실제 코드가 그 논의와 결정을 얼마나 충실히 반영했는지 검증했다.

## 총평 (2차 재리뷰)

1차 리포트의 문제 16건 중 **15건이 새 HEAD에서도 그대로 재현**되고, **1건(문제 12, 리뷰 범위에 무관한 파일이 섞이는 문제)만 이번 diff 범위 재정의(merge-base 사용)로 해소**됐다. 새로 유입된 #7678(SBR/checksumdb 재작업)과 #7697(복제 클래스 조회 인터럽트 근본 수정)은 코드를 직접 열어 확인한 결과 둘 다 매우 꼼꼼하게 마무리되어 있었다 — 특히 #7697은 1차 리포트의 문제 5("에러를 삼키는 bool 반환 패턴")가 정확히 지적했던 `heap_is_replication_class()` 자체의 설계 결함을 `heap_get_class_repl_on()`(에러코드 반환 + out-parameter)으로 근본 교체하고 호출부(`locator_add_or_remove_index_internal()`)에서 에러를 정상적으로 트랜잭션 abort로 전파하도록 고쳐, 실제 코드에서 정상 동작을 직접 확인했다. 다만 **바로 같은 에픽의 이웃 코드(`execute_statement.c`의 `is_replication_class()`)는 여전히 같은 결함을 반복**하고 있어(문제 5), "옆 코드까지는 교훈이 전파되지 않았다"는 1차 리포트의 지적이 2차에서도 그대로 유효하다.

새 diff와 동기화 델타(#7678/#7697)를 별도로 훑었으나, 이미 매우 깊게 리뷰된 코드(PR #6908는 4개월간 리뷰, gdb 재현·재검증까지 거침; #7697도 실측 데이터로 근본 원인을 증명하고 근본 수정)라 이번에 새로 지적할 만한 결함은 찾지 못했다. 신규 발굴 없이 재검증만으로 리포트를 갱신한다.

---

## 문제 1. [치명] rkcheck 유틸리티가 위반 목록 파일 오픈 실패를 검사하지 않아 HA 기동 크래시 가능

**위치**: `src/executables/util_cs.c:2856-2863`(`open_violation_list_file`), `:3320`(`fp = open_violation_list_file(...)`), `:3332`(`PRINT_SECTION_TITLE(fp, ...)` 등 이후 모든 `fp` 사용부)

**로직 설명**: `rkcheck()`는 서버 접속(`db_restart`) 성공 후 `fp = open_violation_list_file(...)`로 위반 목록 파일을 연다. 이 함수는 `envvar_logdir_file()`로 로그 디렉터리 경로를 만들고 `fopen(file_path, "w")`의 결과를 그대로 리턴한다. 이후 `rkcheck()` 본문은 `fp`가 NULL인지 한 번도 검사하지 않고 바로 `PRINT_SECTION_TITLE(fp, ...)`(내부적으로 `fprintf(fp, ...)`), `check_repl_constraint_violations(classes, fp, check_rk_constraint, ...)` (내부의 `check_rk_constraint()`가 다시 `fprintf(fp, ...)`)를 호출한다. 새 HEAD에서도 이 흐름은 동일하다.

**문제 시나리오**: `$CUBRID/log` 디렉터리가 없거나, 디스크가 꽉 찼거나, 권한 문제로 `fopen`이 실패하면 `fp == NULL`인 채로 이후 모든 `fprintf(fp, ...)` 호출이 정의되지 않은 동작(전형적으로 세그폴트)을 일으킨다. 이 함수는 `cubrid hb start` 시 `us_hb_process_rkcheck()`(`util_service.c`)가 **자동으로** 호출한다(PR #6658). 즉 관리자가 rkcheck를 직접 실행할 때뿐 아니라, HA 기동 절차 자체가 로그 디렉터리 문제 하나로 크래시로 끝날 수 있다.

**제안**: `fp == NULL`이면 `db_shutdown()` 후 명확한 에러 메시지("로그 디렉터리에 위반 목록 파일을 생성할 수 없습니다")와 함께 조기 종료.

---

## 문제 2. [치명] 다중 절 ALTER TABLE에서 HA 복제키 재검사 게이트가 "맨 앞 절"의 코드만 확인함

**위치**: `src/query/execute_schema.c:2051`(`do_alter()` 내부 `if (!need_check_repl_constraint && IS_REPL_CONSTRAINT_RELATED_ALTER (alter->info.alter.code))`), 매크로 정의는 `:109-114`

**로직 설명**: `do_alter()`는 한 ALTER TABLE 문에 여러 절(clause)이 나열된 경우 `for (crt_clause = alter; ...; crt_clause = crt_clause->next)`로 절을 하나씩 순회하며 처리한다(PR #6637이 HA 제약 검사를 절 단위가 아니라 문장 단위로 옮기며 이 구조를 만들었다). 각 절을 처리한 직후 "이 절이 복제키에 영향을 주는 종류인가"를 판단해 `need_check_repl_constraint` 플래그를 세우는데, 그 판단식이 `crt_clause->info.alter.code`(지금 막 처리한 절의 코드)가 아니라 **`alter->info.alter.code`**를 본다. `alter`는 반복문 내내 값이 바뀌지 않는, 절 리스트의 첫 번째 노드다. 즉 이 판단은 반복문이 몇 바퀴를 돌든 항상 "첫 번째 절이 무엇이었는가"만 확인하고, 지금 실제로 실행한 절이 무엇인지는 전혀 보지 않는다. 새 HEAD에서도 이 로직은 그대로다(줄 번호만 2047→2051로 이동).

**문제 시나리오**: `ALTER TABLE t CHANGE COLUMN c c INT, DROP PRIMARY KEY;` 를 실행하면 첫 절의 코드는 `PT_CHANGE_ATTR`이고, 이 값은 `IS_REPL_CONSTRAINT_RELATED_ALTER` 매크로 목록(`PT_ADD_ATTR_MTHD`, `PT_DROP_ATTR_MTHD`, `PT_DROP_CONSTRAINT`, `PT_DROP_PRIMARY_CLAUSE`)에 없다. 두 번째 절(`DROP PRIMARY KEY`, 코드 `PT_DROP_PRIMARY_CLAUSE`)이 실제로 실행되어 PK가 삭제되어도, 판단식은 여전히 첫 절의 코드(`PT_CHANGE_ATTR`)만 보므로 `need_check_repl_constraint`는 끝까지 `false`로 남는다. 결과적으로 `do_alter()` 끝의 `check_ha_repl_constraint()` 호출 자체가 스킵되어, HA 모드에서 유일한 RK였던 PK가 제거된 테이블이 아무 에러 없이 만들어진다.

PR #6637이 검증한 예시(`DROP PRIMARY KEY, ADD PRIMARY KEY(...)`)는 공교롭게 DROP이 **첫 절**이라 `PT_DROP_PRIMARY_CLAUSE`가 곧바로 게이트를 열기 때문에 이 버그가 드러나지 않았다. 절 순서가 바뀌거나 앞에 다른 절이 끼면 즉시 재현된다.

**제안**: 판단식을 `crt_clause->info.alter.code`로 수정. 부수적으로 매크로 목록에 `PT_CHANGE_ATTR`(MODIFY/CHANGE COLUMN으로 NOT NULL 해제 등)도 추가.

---

## 문제 3. [중요] `CREATE TABLE ... LIKE ...`에 REPLICATION 옵션을 명시해도 에러 없이 조용히 무시됨

**위치**: `src/query/execute_schema.c:10258-10265`(`do_create_entity()`), `src/parser/semantic_check.c:8506-8514`(`pt_check_create_entity()`의 `PT_TABLE_OPTION_REPLICATION` 분기)

**로직 설명**: `do_create_entity()`는 `create_like`가 참이면 `is_replication_on = !(source_class->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF);`로 **무조건 원본 테이블의 플래그를 그대로 사용**하고, `else` 분기(일반 생성)에서만 사용자가 입력한 `tbl_opt_replication`을 읽는다. 즉 `create_like`가 참이면 사용자가 `REPLICATION=OFF`를 문장에 명시했는지 여부 자체를 코드가 확인하지 않는다. 한편 `semantic_check.c`의 `PT_TABLE_OPTION_REPLICATION` 분기는 REPLICATION 옵션이 **중복 명시**됐는지만 검사하고, `create_like`와의 조합은 전혀 검사하지 않는다. 새 HEAD에서도 동일하다.

**문제 시나리오**: PR #6943 리뷰 논의(pr_히스토리.md ④)에는 "REPLICATION 옵션과 LIKE를 동시에 명시하면 에러라는 규칙도 이때 PR 본문에서 확정됐다"고 명시되어 있다. 그러나 실제로 `CREATE TABLE t2 LIKE t1 REPLICATION=OFF;`를 실행하면 에러가 나지 않고, `t1`의 REPLICATION 값이 그대로 `t2`에 적용되며 사용자가 쓴 `REPLICATION=OFF`는 아무 경고 없이 버려진다.

**제안**: `create_like`이면서 `tbl_opt_replication != NULL`인 경우 `semantic_check.c`에서 명시적으로 에러 처리하거나, 최소한 원본과 일치하지 않을 때 경고를 남긴다.

---

## 문제 4. [중요] `or_class_is_replication_on()`이 클래스 플래그 값을 매직넘버로 하드코딩

**위치**: `src/base/object_representation_sr.c:781-792`

**로직 설명**: 이 함수는 클래스 레코드에서 읽은 `flags` 정수와 `int replication_off_flag = 32;`를 비트 AND해 복제 여부를 판정한다. 주석에는 `/* SM_CLASSFLAG_REPLICATION_OFF = 32 */`라고 적혀 있지만, 실제 이 값을 정의하는 이름은 `class_object.h`의 `SM_CLASSFLAG_DATA_REPLICATION_OFF`다(PR #6477에서 이미 한 번 리네이밍됨). `src/base`는 `src/object`(class_object.h가 속한 상위 모듈)에 의존할 수 없는 레이어링 제약 때문에, 실제 enum 심볼을 쓰지 못하고 그 값을 숫자로 복제해 넣은 것으로 보인다. 바로 위 줄에 `/* TODO: Consider adding a replication flag to HEAP_CLASSREPR_ENTRY ... (EPIC CBRD-26096) */`라는 주석으로 이 상태가 임시방편임을 스스로 인정하고 있다. 새 HEAD에서도 변화 없음.

**문제 시나리오**: 지금 당장은 32라는 값이 실제 enum과 일치해 동작에 문제가 없다. 그러나 이 값은 `heap_get_class_repl_on()`(#7697에서 근본 수정된 함수)을 거쳐 모든 INSERT/UPDATE/DELETE의 복제 여부 판정에 쓰이는 핵심 경로다. 앞으로 `SM_CLASSFLAG_*` enum에 새 플래그가 추가되거나 순서가 바뀌면, 이 매직넘버만 갱신을 놓쳐도 컴파일 에러 없이 복제 여부 판정이 조용히 틀어진다.

**제안**: `src/base` 쪽에 플래그 비트 값을 전용 헤더 상수로 명시적으로 선언하고 `class_object.h`의 정의와 `static_assert`로 값 일치를 강제하거나, 최소한 두 정의가 나란히 있다는 사실을 상호 참조 주석으로 남긴다.

---

## 문제 5. [중요] `is_replication_class()`가 조회 실패를 삼키는 bool 반환 패턴을 반복함 (#7697 교훈 미전파 — 2차에서도 유효)

**위치**: `src/query/execute_statement.c:3200-3218`

**로직 설명**: `is_replication_class(const char *classname)`는 `db_find_class(classname)`이 NULL을 반환하면 `assert(false); return false;`로 처리한다. 이 함수는 (2차 재리뷰 시점 기준) `spec_has_replication_class()` → `is_data_repl_log_enabled()`를 거쳐, INSERT/UPDATE/DELETE에서 SBR(구문 기반 복제) 로그를 남길지 결정하는 데 쓰인다(PR #6908, #7678에서 derived vclass 대응까지 포함해 재작업됨).

**문제 시나리오**: #7697은 정확히 이 패턴의 위험을 근본 수정한 PR이다 — `heap_is_replication_class()`가 실패를 `false`로 뭉개서 `KILL QUERY`가 무시되는 크래시로 이어졌고, 반환 타입을 `bool`에서 `int`(에러코드) + out-parameter로 근본 교체했다(실제로 새 `heap_get_class_repl_on()` 구현과 `locator_add_or_remove_index_internal()` 호출부를 직접 확인해, 에러가 `goto error`로 정상 전파됨을 검증했다). 그런데 같은 에픽의 같은 시기에 추가된 `execute_statement.c`의 이 함수는 여전히 예전 방식(에러를 `false`로 감춤)을 쓰고 있다. `assert(false)`는 release 빌드에서는 제거되어(`NDEBUG`) 조용히 `false`를 반환하고 넘어간다. `db_find_class`가 일시적으로 실패하는 경로가 실제로 발생하면, 그 SBR 문장은 복제 대상이 아니라고 잘못 판단되어 복제 로그 자체가 만들어지지 않고 넘어간다 — 슬레이브와 데이터가 조용히 벌어지는, #7697이 고치려 했던 것과 같은 계열의 문제다.

**제안**: 최소한 실패 시 `false`로 조용히 넘기지 말고 에러를 상위로 전파하거나, 왜 이 경로는 안전한지(예: 세만틱 체크를 이미 통과한 이후라 NULL이 될 수 없다는 근거) 주석으로 명시한다.

---

## 문제 6. [중요] REPLICATION이 비예약어(identifier) 목록에서 빠져 기존 컬럼/테이블명과 충돌 (T-5 재확인)

**위치**: `src/parser/csql_grammar.y:20646`(`identifier` 규칙), 대조 라인 `:20755`(DISK_SIZE), `:20883`(REVERSE)

**로직 설명**: `csql_lexer.l`은 `replication`을 대소문자 구분 없이 전용 토큰 `REPLICATION`으로 인식하도록 새로 추가했다(PR #6394). `csql_grammar.y`의 `identifier` 규칙은 예약어처럼 보이지만 실제로는 컬럼/테이블명으로도 써야 하는 토큰들을 나열해 두는 곳인데, 여기서 직접 grep으로 대조한 결과 같은 시기에 추가된 이웃 키워드 `DISK_SIZE`(:20755), 기존 키워드 `REVERSE`(:20883)는 이 목록에 있지만 `REPLICATION`은 없다. 새 HEAD에서도 `REPLICATION` 토큰은 `identifier` 규칙, `opt_replication_option` 등 문법 처리부에만 쓰이고 비예약어 허용 목록에는 들어있지 않다.

**문제 시나리오**: 이 기능이 배포되기 전부터 컬럼명이나 테이블명으로 `replication`을 쓰던 고객이 업그레이드하면, `SELECT replication FROM t` 같은 기존 쿼리가 문법 에러로 깨진다.

**제안**: `identifier` 규칙에 `REPLICATION` 추가.

---

## 문제 7. [중요] rkcheck/applyinfo의 호스트명 버퍼 오버플로우 위험이 TODO로만 남아 미해결

**위치**: `src/executables/util_cs.c:3299`(`rkcheck()`의 `tmp_database_name` 처리), `:4095-4097`(`applyinfo()`의 `local_database_name` 처리)

**로직 설명**: `rkcheck()`는 `char tmp_database_name[CUB_MAXHOSTNAMELEN];`(256바이트)에 `snprintf(...)`로 DB명+`"@localhost"`를 담는다. 바로 위에 `/* TODO: Handle truncation explicitly here; keep this in sync with applyinfo() local_database_name build path. */`라는 주석이 있다. `applyinfo()`는 같은 조합을 `strcpy`/`strcat`으로 만드는데, 이번 diff는 그 위에 `/* TODO: Replace strcpy/strcat with bounded formatting ... */` 주석만 새로 얹었을 뿐 실제 수정은 하지 않았다. 새 HEAD에서도 두 TODO 모두 그대로 남아 있다.

**문제 시나리오**: PR #6934에서 vimkim이 "**MAJOR**: 버퍼(256)가 최대 길이 DB 이름(255자)+`@localhost`(10자)를 모두 담기엔 부족할 수 있다"고 이미 지적했고, 저자도 "마이너한 리뷰라 바로 머지, 버퍼 크기 이슈는 TODO로 남긴다"고 명시했던 사안이다. `rkcheck()`는 `snprintf`라 최소한 크래시 대신 잘림(truncation)으로 끝나지만, `applyinfo()`의 `strcpy`/`strcat`는 여전히 경계 검사가 없어 253자 이상 길이의 DB 이름을 등록하면 스택 버퍼 오버플로우가 발생할 수 있는 구조다.

**제안**: 최소한 `applyinfo()`도 `snprintf`로 교체해 크래시를 방지한다.

---

## 문제 8. [보통] rkcheck에서 `check_database_name()` 실패 시 에러 메시지 없이 조용히 종료 (PR #6934 MINOR 재발)

**위치**: `src/executables/util_cs.c:3304-3308`

**로직 설명**: `rkcheck()`는 `db_restart()` 실패 시에는 `PRINT_AND_LOG_ERR_MSG("%s: %s\n", arg->command_name, db_error_string(3))`로 명확한 메시지를 남기지만, 바로 앞의 `check_database_name(database_name)` 실패 시에는 `err = ER_FAILED; goto end2;`만 하고 아무 메시지도 남기지 않는다. 새 HEAD에서도 동일.

**문제 시나리오**: PR #6934에서 이미 "`check_database_name` 실패 시 `er_set()`이 호출되지 않아 `db_error_string()`이 빈 문자열을 반환한다"는 MINOR 지적이 있었다. 사용자가 `rkcheck`에 잘못된 형식의 DB 이름을 넘기면 종료 코드만 실패이고 화면에는 아무 설명도 뜨지 않는다.

**제안**: 이 분기에도 `PRINT_AND_LOG_ERR_MSG`로 "잘못된 데이터베이스 이름" 메시지를 직접 추가.

---

## 문제 9. [보통] checksumdb에서 복제 억제 해제(`suppress_repl...(false)`) 실패가 에러 컨텍스트 없이 반환됨 (#7678 재작업 이후에도 유효)

**위치**: `src/executables/checksumdb.c:1727-1762`(`chksum_calculate_checksum()`)

**로직 설명**: `db_set_suppress_repl_on_transaction(true)` 실패 시에는 `er_set(...)`으로 상세 메시지를 남기고 리턴한다(#7678에서 "Per review, ... 반환값이 무시되고 있었다"며 이 `true` 경로를 고쳤다). 반대로 `db_execute()` 직후의 `error = db_set_suppress_repl_on_transaction(false);`(:1741)는 반환값을 `error`에 담기만 하고 `er_set()`을 호출하지 않는다. 이후 `res >= 0`(즉 `db_execute` 자체는 성공)이고 `chksum_update_master_checksum()`도 성공(`res >= 0`)이면, `error`는 이 `suppress(false)` 호출의 반환값을 그대로 유지한 채 함수가 끝난다. #7678로 브랜치가 갱신된 뒤에도 이 `false` 경로만은 그대로 남아 있음을 새 HEAD에서 확인했다.

**문제 시나리오**: `db_execute`와 `chksum_update_master_checksum`이 둘 다 성공했는데 `db_set_suppress_repl_on_transaction(false)`만 실패하는 드문 경우, 호출자는 0이 아닌 에러 코드를 받지만 그 에러에 대응하는 `er_set()` 메시지가 없어 `db_error_string()`으로 원인을 알 수 없다. 커밋 메시지 자체가 이 문제를 고치려 한 시도(true 경로)인데, `false` 쪽 실패 경로에는 여전히 `er_set()`이 없어 절반만 고쳐졌다.

**제안**: `false` 호출 실패 시에도 `er_set()`으로 컨텍스트를 남긴다.

---

## 문제 10. [보통] `do_alter_change_replication()`이 COMMENT 변경용 세이브포인트 이름을 그대로 재사용

**위치**: `src/query/execute_schema.c:11747, 11823` (`UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT` 사용), 원래 정의/용도는 `:11465`(`do_alter_change_tbl_comment()`)

**로직 설명**: `UNIQUE_SAVEPOINT_CHANGE_TBL_COMMENT`는 `"cHANGEtBLcOMMENT"`라는 리터럴 이름의 세이브포인트로, 원래 `do_alter_change_tbl_comment()`(COMMENT 변경 전용)가 쓰던 것이다. 새로 추가된 `do_alter_change_replication()`이 자기 전용 세이브포인트 이름을 새로 만들지 않고 이 이름을 그대로 복사해 썼다. 새 HEAD에서도 동일.

**문제 시나리오**: `ALTER TABLE t COMMENT='x', REPLICATION=OFF;`처럼 한 문장에 두 절이 같이 오면 동일 트랜잭션 안에 동일한 이름의 세이브포인트가 두 번 생성된다. 트랜잭션 로그/락 대기 진단 시 "cHANGEtBLcOMMENT"라는 이름만 보고는 그것이 코멘트 변경 때문인지 복제 옵션 변경 때문인지 구분할 수 없어 장애 분석 시 혼선을 유발한다.

**제안**: `UNIQUE_SAVEPOINT_CHANGE_REPLICATION` 같은 전용 상수를 새로 정의.

---

## 문제 11. [보통] TRUNCATE 복제 로그 생성이 REPLICATION=OFF 여부를 확인하지 않음 (2m-4 재확인)

**위치**: `src/query/execute_statement.c:341-380` (`truncate_need_repl_log()`, RK 검사는 `:376-379`)

**로직 설명**: 기존에는 `classobj_find_cons_primary_key(class_->constraints)`로 PK 유무만 봤던 것을(PR #6826), `classobj_find_cons_replication_key(class_->constraints)`로 바꿔 PK 또는 NOT NULL UNIQUE(RK)까지 인정하도록 확장했다. 그런데 이 함수 어디에도 `class_->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF` 검사가 없다 — RK 유무만 보고 바로 `return true`(복제 로그 필요)한다. 새 HEAD에서도 변화 없음.

**문제 시나리오**: `REPLICATION=OFF`로 명시적으로 복제 제외 처리한 테이블이라도 RK(PK 또는 NOT NULL UNIQUE)만 있으면 `TRUNCATE`가 복제 로그를 만든다. 반면 같은 테이블에 대한 일반 INSERT/UPDATE/DELETE는 `heap_get_class_repl_on()`으로 REPLICATION 플래그를 확인해 복제하지 않는다. 즉 "REPLICATION=OFF인데 TRUNCATE만 복제되는" 진입점별 불일치가 남아 있다.

**제안**: RK 검사 앞에 `!(class_->flags & SM_CLASSFLAG_DATA_REPLICATION_OFF)` 조건 추가.

---

## 문제 13. [보통] 파티션 승격 시 NOT NULL UNIQUE 보존 여부가 제약 단위가 아니라 테이블 단위로 판단됨

**위치**: `src/query/execute_schema.c:7837-7975` (`has_notnull_unique_constraints()`, `do_promote_partition()`)

**로직 설명**: PR #6552/EPIC 요구사항은 "파티션을 일반 테이블로 승격할 때 부모의 PK/NOT NULL UNIQUE 속성을 보존해야 한다"는 것이다. 구현은 클래스의 속성들을 순회하며 `has_notnull_unique`라는 **테이블 전체에 대해 하나뿐인 불리언**을 세우고, 이 값 하나로 `ctemplate->properties`에서 `SM_PROPERTY_UNIQUE`/`SM_PROPERTY_REVERSE_UNIQUE` 전체를 지울지 말지를 결정한다. PK 자체(`SM_PROPERTY_PRIMARY_KEY`)는 이제 아예 건드리지 않아 항상 보존된다. 새 HEAD에서도 변화 없음.

**문제 시나리오**: 파티션 테이블에 PK 하나와, RK 후보와 무관한 별도의 "NOT NULL + UNIQUE" 제약이 같이 있는 경우, PK가 이미 RK 자격을 갖추고 있어 그 별도 UNIQUE 제약은 승격 후에도 굳이 보존할 필요가 없는데, `has_notnull_unique`가 그 별도 제약 때문에 `true`가 되어 UNIQUE 계열 프로퍼티 전체가 "지우지 않음"으로 분류된다. 파티션+복합 유니크 조합은 실제 운영에서 흔치 않아 발견 난이도가 높은 종류의 문제다.

**제안**: 승격 로직이 "RK로 인정되는 제약만 선택적으로 보존"하려는 것인지, 아니면 "NOT NULL UNIQUE가 하나라도 있으면 전부 보존"이 의도된 단순화인지 설계 의도를 문서화하고, 전자라면 제약별로 분리해서 처리한다.

---

## 문제 14. [보통] `ER_HA_REPLICATION_KEY_REQUIRED` 국문 메시지가 ALTER TABLE 상황에서도 "테이블 생성 시"로 고정 표기됨

**위치**: `msg/ko_KR.utf8/cubrid.msg:1477`("HA 복제 제약 위반: 테이블 생성 시 복제 후보 키...가 필요합니다"), `msg/en_US.utf8/cubrid.msg:1478`(영문판, 상황 특정 없음), 사용처는 `src/query/execute_schema.c` — `check_ha_repl_constraint()`가 `do_create_entity()`(:10269)와 `do_alter()`(:2068) 양쪽에서 모두 호출됨

**로직 설명**: `ER_HA_REPLICATION_KEY_REQUIRED`는 `check_ha_repl_constraint()` 한 곳에서만 발생하고, 이 함수는 CREATE TABLE 검증과 ALTER TABLE(다중 절 처리 후) 검증 양쪽에서 공용으로 쓰인다. 그런데 국문 메시지는 "테이블 생성 시"라고 상황을 특정해 못박아 놓았다. 영문 메시지는 "A replication key candidate ... is required in HA mode"로 상황을 특정하지 않아 이 문제가 없다. 새 HEAD에서도 동일.

**문제 시나리오**: 한국어 로케일 사용자가 `ALTER TABLE t DROP PRIMARY KEY;`처럼 ALTER TABLE 도중 이 에러를 만나면, 메시지는 "테이블 생성 시"라고 안내하므로 지금 자신이 하고 있는 ALTER 작업과 무관한 상황을 설명하는 것처럼 읽혀 혼란을 준다.

**제안**: 국문 메시지에서 "테이블 생성 시"를 빼고 영문과 동일하게 "HA 모드에서는"으로 일반화.

---

## 문제 15. [사소] 신규 utils.msg 사용법 메시지에 trailing whitespace + 파일 끝 개행 누락 (en/ko 동일)

**위치**: `msg/en_US.utf8/utils.msg:1382`, `msg/ko_KR.utf8/utils.msg:1362` (`$set 61 MSGCAT_UTIL_SET_RKCHECK` 블록 마지막 줄)

**로직 설명**: rkcheck 사용법 메시지 블록이 `-f, --fk-check ...` 줄 다음에 공백 4칸만 있는 줄로 끝나고, 파일 끝에 개행 문자가 없다(`git diff`가 `\ No newline at end of file`로 표시). 영어판과 한국어판 양쪽에 동일하게 나타난다. 새 HEAD에서도 그대로다.

**문제 시나리오**: 즉각적인 기능 오류는 아니지만, 릴리스로 나가는 메시지 카탈로그 파일에 불필요한 공백과 개행 누락이 그대로 커밋된 것은 코드 정리(clean-up) 단계가 생략됐다는 신호다.

**제안**: trailing whitespace 제거, 파일 끝 개행 추가.

---

## 문제 16. [사소] util_cs.c의 `PRINT_MESSAGE` 매크로에 불필요한 trailing backslash

**위치**: `src/executables/util_cs.c:106-110`

**로직 설명**: 같은 블록에 새로 추가된 세 매크로 중 `PRINT_SECTION_TITLE`, `PRINT_BLANK_LINE`은 `} while (0)` 뒤에 아무 것도 없이 끝나는데, `PRINT_MESSAGE`만 `} while (0)` 뒤에 의미 없는 backslash가 남아 있다. 새 HEAD에서도 동일.

**문제 시나리오**: 매크로 정의가 다음 빈 줄까지 이어지는 형태가 되어 당장 컴파일 에러는 아니지만, 세 매크로가 나란히 있는데 하나만 형태가 다른 것은 복붙 후 정리를 안 했다는 흔적이고, 이후 이 매크로 바로 뒤에 코드를 추가하는 사람이 실수할 여지를 만든다.

**제안**: 줄 끝 backslash 제거.

---

## 재검증으로 해소된 문제

### (구)문제 12. 리뷰 대상 diff에 REPLICATION 기능과 무관한 별개 PR 변경분이 섞여 있음 — **해소**

1차 리포트는 작업지시서가 "develop(`23789cbfa`) 대비 추가된 40개 파일"을 리뷰 범위로 지정한 탓에, 브랜치 동기화 과정에서 딸려 들어온 무관 파일 4개(`src/base/memory_cwrapper.h`, `src/storage/page_buffer.c`, `src/transaction/log_manager.c`, `src/transaction/log_page_buffer.c` — 별도 PR #7340/#7196 소관)가 리뷰 범위에 섞여 있음을 지적했다.

2차 재리뷰는 diff 범위를 **merge-base(upstream/develop) `b646647ec`...HEAD**로 재정의했고, 이 기준으로는 위 4개 파일 모두 diff에 나타나지 않음을 직접 확인했다(`git diff b646647ec...HEAD -- <4개 파일>`이 빈 출력). 즉 이번 재리뷰의 범위 재정의 자체가 1차 지적의 원인을 제거했으므로, 이 문제는 코드가 고쳐진 것은 아니지만 **리뷰 절차상 해소**된 것으로 분류하고 리포트에서 제외한다.

---

## 조사 종료 선언 (2차)

1차 리포트의 16건 문제를 모두 새 HEAD(`734f4959d`)에서 직접 코드를 열어 재확인했다: 15건은 관련 함수·조건식이 한 글자도 바뀌지 않고 그대로 남아 있음을 확인했고(위치만 일부 갱신), 1건(구 문제 12)은 diff 범위 재정의로 해소됐다.

동기화 델타(#7678 `3b6ebd1a9`, #7697 `9e094324b`)가 새로 넣은 코드 — `is_data_repl_log_enabled()`/`spec_has_replication_class()`/`get_spec_classname()`/`pt_spec_repl_class_walk()`(derived vclass 대응), `heap_get_class_repl_on()`과 그 호출부(`locator_add_or_remove_index_internal()`), `chksum_calculate_checksum()`의 에러 처리 재작업 — 을 각각 직접 읽고 콜체인을 따라갔다. 이 두 PR은 pr_히스토리.md에 기록된 대로 이미 매우 깊은 리뷰(gdb 재현·재검증, 실측 데이터 기반 근본원인 증명)를 거쳤고, 실제로 코드 품질이 그 수준에 부합함을 확인했다 — 특히 #7697의 에러 전파 경로는 정확히 설계된 대로 동작한다.

이 두 델타와 전체 diff(35파일) 범위 안에서 새로운 결함을 찾으려 시도했으나, 문제 5(같은 결함 패턴이 옆 함수에 반복)와 문제 9(같은 함수의 절반만 고쳐진 에러 처리)를 제외하면 추가로 제시할 만한 신규 문제는 발견하지 못했다. `class_object.c`의 `classobj_copy_pk_and_uk_notnull_constraints()`(PK/UK 속성 복사, PR #6552/8bb304290 기원) 같은 후보도 열어봤으나, 이는 1차 리뷰 대상 코드에 이미 포함돼 있었고 이번 델타가 만든 문제가 아니며 확증까지 이르지 못해 신규 지적으로 올리지 않았다.

50건을 채우기 위한 추가 조사는 이번에도 하지 않았다 — "억지 지적 금지" 원칙에 따라 신규 발굴 0건으로 재리뷰를 종료한다.

---

## 심각도별 집계 (2차 재리뷰, 번호는 1차 유지)

| 심각도 | 건수 | 번호 |
|---|---:|---|
| 치명 | 2 | 1, 2 |
| 중요 | 5 | 3, 4, 5, 6, 7 |
| 보통 | 6 | 8, 9, 10, 11, 13, 14 |
| 사소 | 2 | 15, 16 |
| **합계** | **15** | |

(※ 구 문제 12는 해소되어 번호가 비어 있다 — 아래 "재검증 요약" 참조.)

## 재검증 요약

- **유지(15건)**: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 13, 14, 15, 16 — 모두 새 HEAD에서 관련 코드를 직접 열람해 로직이 그대로임을 확인.
- **해소(1건)**: 문제 12 — diff 범위가 merge-base `b646647ec` 기준으로 재정의되면서 무관 파일 4개가 diff에서 사라져 리뷰 절차상 해소.
- **폐기(0건)**: 없음. 재검증 결과 오판으로 판명된 1차 지적은 없었다.
- **신규(0건)**: 동기화 델타(#7678/#7697)와 전체 diff를 재조사했으나, 억지 지적 금지 원칙에 따라 추가하지 않음.
