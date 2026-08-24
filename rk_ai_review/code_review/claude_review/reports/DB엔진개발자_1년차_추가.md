# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 1년차 (3차 전수 재수색, 기준 734f4959d)

## 머리말

3차 전수 재수색 라운드다. 기준 HEAD `734f4959d`, diff 범위 `b646647ec...HEAD`(35파일 +1,444/−57).
기존 리포트(`DB엔진개발자_1년차.md`)의 유지 문제 21건(문제 2~11, 13~23)과, 20 페르소나 병합본
67건(`dedup_existing.json`, K-1~K-69·K2-1~K2-3)을 **같은 뿌리면 신규로 세지 않는다**는 규칙 아래,
그 88건이 아직 다루지 않은 파일·함수를 우선으로 재수색했다.

- **재수색 방법**: `git diff --stat`로 35파일 전체 목록을 뽑고, 기존 88건이 손대지 않은 파일부터
  (parse_tree.h/parse_tree_cl.c, error_code.h, util_admin.c, px_worker_manager.cpp, csql_lexer.l,
  object_representation_sr.h, schema_manager.c/h, schema_template.c 등) diff를 Read로 정독하고
  호출·피호출 로직을 따라가 검증했다. 본 리포는 읽기 전용으로만 다뤘다.
- **§7 가정 준수**: `locator_update_index()`의 옛 `heap_is_replication_class` 잔존 호출
  (locator_sr.c:8428, `&&` 사슬 안)은 `60648d919`로 수정 완료된 것으로 간주하여 지적하지 않는다.
- **번호 규칙**: 기존 리포트 마지막 번호(23)에 이어 24부터 붙인다.

3차에서 새로 확인한 유효 결함은 **3건(문제 24~26)**이다. diff의 나머지 영역은 88건이 이미
촘촘히 덮고 있어, 잔여 쿼터(50−21=29)를 억지로 채우지 않고 커버리지 근거와 함께 종료를 선언한다.

---

## 문제 24

**[심각도: 보통] REPLICATION 테이블 옵션의 출력이 ON/OFF가 아니라 원시 정수(0/1)로 찍혀, 재파싱 시 문법 오류가 된다**

**위치**: `src/parser/parse_tree_cl.c:8041-8043` (`pt_print_table_option`),
대조 `src/parser/csql_grammar.y:19887-20001`(`class_replication_spec`/`opt_replication_option`)

**로직 설명**: 파서는 `REPLICATION [=] {ON|OFF}`를 `class_replication_spec`에서 **PT_VALUE(정수)**
노드로 만든다 — `node->type_enum = PT_TYPE_INTEGER; node->info.value.data_value.i = $3;`로
ON=1, OFF=0을 담는다(csql_grammar.y:19893-19899, `opt_replication_option`). 이 값을 다시 텍스트로
찍는 `pt_print_table_option`의 새 분기는
```c
case PT_TABLE_OPTION_REPLICATION:
  q = pt_append_nulstring (parser, q, "replication = ");
  break;
```
접두사 `"replication = "`만 붙이고, 값 출력은 함수 하단의 공통 `else` 경로
(`r1 = pt_print_bytes_l (parser, p->info.table_option.val)`, :8071)로 흘러간다. 그 결과 정수
리터럴 `"1"`/`"0"`이 그대로 이어 붙어 **`replication = 1`** 또는 **`replication = 0`**이 출력된다.
바로 위 ENCRYPT 옵션은 같은 "정수를 담는" 구조인데도 `PT_TABLE_OPTION_ENCRYPT` 전용 분기
(:8060-8069)에서 `tde_get_algorithm_name()`으로 정수를 알고리즘 이름 텍스트로 되돌린다.
REPLICATION에는 이에 대응하는 "정수→ON/OFF" 역변환 분기가 빠졌다.

**문제 시나리오**:
- 확실한 경로: `pt_check_create_entity()`의 REPLICATION 중복-옵션 검사가 오류 메시지를
  `parser_print_tree (parser, tbl_opt)`로 만든다(semantic_check.c:8508 부근). 사용자가
  `CREATE TABLE t(...) REPLICATION=ON, REPLICATION=OFF`를 치면 "duplicate table option:
  **replication = 1**"처럼 문법에 없는 형태로 표기된다.
- 위험 경로: `pt_print_table_option`은 파스 트리를 SQL 텍스트로 복원하는 범용 프린터다. 이 경로로
  `CREATE/ALTER ... REPLICATION=OFF`가 재구성돼 재파싱되면, 문법의 `opt_replication_option`은
  ON/OFF/공백만 받으므로 `replication = 0`은 **문법 오류**가 된다. (ENCRYPT가 굳이 이름으로
  역변환하는 이유가 바로 이 왕복 안전성이다.)

**제안**: ENCRYPT 분기와 동일하게 REPLICATION 전용 값 출력 분기를 추가해 정수 1/0을
`"ON"`/`"OFF"`(또는 `"on"`/`"off"`) 문자열로 되돌려 찍어야 한다. (기존 88건에 parse_tree_cl.c
프린터 관련 지적 없음 — 신규)

---

## 문제 25

**[심각도: 사소] 신규 서버측 or_* 선언의 스토리지-클래스/헤더 노출이 이웃과 불일치**

**위치**: `src/base/object_representation_sr.h:282`(`or_is_replication_candidate_key` 선언),
`src/base/object_representation_sr.c:770-777`(`or_class_flags` 정의)

**로직 설명**: 같은 헤더에 추가된 `or_class_is_replication_on`은 이웃 프로토타입들과 똑같이
`extern bool or_class_is_replication_on (RECDES *);`로 선언됐다(:244). 그런데 파일 끝에 추가된
`or_is_replication_candidate_key`는 **`extern` 없이** `bool or_is_replication_candidate_key (const OR_INDEX *);`
로만 선언돼(:282) 주변 규약과 어긋난다. 또한 `or_is_replication_candidate_key`를 뒷받침하는
헬퍼 `or_class_flags()`(object_representation_sr.c:770)는 `static`도 아니고 헤더 선언도 없이
파일 내부(`or_class_is_replication_on`)에서만 쓰인다 — 파일 로컬로 쓸 거면 `static`이어야 하고,
공개할 거면 헤더에 선언해야 하는데 둘 다 아니다.

**문제 시나리오**: C++로 컴파일되므로 당장 링크는 되지만, `or_class_flags`는 다른 번역단위에서
암묵적으로 참조할 수 없고(선언 부재) 파일 밖 노출 의도도 불명확해, 읽는 사람이 "이게 공개 API인가
내부 헬퍼인가"를 판단하기 어렵다. `extern` 누락은 헤더 전체의 일관성을 깨 정적 분석·독해를 방해한다.

**제안**: `or_is_replication_candidate_key` 선언에 `extern`을 붙여 이웃과 통일하고,
`or_class_flags`는 (a) 파일 로컬이면 `static`으로, (b) 공개면 헤더에 `extern`으로 선언해 의도를
명확히 해야 한다. (K2-3는 execute_statement.c의 `is_data_repl_log_enabled` 링키지 건으로 파일·함수가
다름 — 본 건은 object_representation_sr 계열 신규)

---

## 문제 26

**[심각도: 사소] `do_create_entity`의 REPLICATION=OFF 분기만 `goto error_exit` 대신 `break`라, 앞서 `do_flush_class_mop`가 켜져 있으면 `assert(error==NO_ERROR)`에 걸린다**

**위치**: `src/query/execute_schema.c:10275-10284`(REPLICATION=OFF 분기),
대조 `:10267-10274`(REPLICATION=ON 분기), 후속 검사 `:10349-10360`

**로직 설명**: 같은 REPLICATION 블록에서 두 분기의 실패 처리가 다르다.
```c
if (is_replication_on)
  { error = check_ha_repl_constraint (class_obj);
    if (error != NO_ERROR) { goto error_exit; } }   /* ON: 즉시 롤백 경로로 */
else
  { error = sm_set_class_flag (class_obj, SM_CLASSFLAG_DATA_REPLICATION_OFF, TRUE);
    if (error != NO_ERROR) { break; }               /* OFF: switch만 탈출 */
    do_flush_class_mop = true; }
```
`break`는 `switch (entity_type)`만 벗어나며, 그 뒤 공통 후처리는
```c
if (do_flush_class_mop == true) { assert (error == NO_ERROR); ... locator_flush_class(...); }
if (error != NO_ERROR) { goto error_exit; }
```
이다(:10349-10360). 문제는 `do_flush_class_mop`가 **이 지점 이전에 이미 true로 켜질 수 있다**는 것
이다 — 예: `REUSE_OID` 처리가 성공하면 :10254에서 `do_flush_class_mop = true`가 된다.

**문제 시나리오**: `CREATE TABLE t(...) REUSE_OID, REPLICATION=OFF`에서 REUSE_OID 플래그 설정이
성공(→ `do_flush_class_mop=true`)한 뒤, REPLICATION_OFF용 `sm_set_class_flag`가 실패(권한/템플릿
페치 실패 등)하면 `break`로 빠져나온다. 그러면 `error != NO_ERROR`인 채로
`if (do_flush_class_mop == true) { assert (error == NO_ERROR); ... }`에 도달해 **디버그 빌드에서
assert 중단**, 릴리스에서는 곧이어 `error = locator_flush_class(...)`가 원래 오류를 덮어써
원인이 가려진다. REPLICATION=ON 분기는 `goto error_exit`로 이 함정을 피하는데, OFF 분기만
`break`라 대칭이 깨져 있다(같은 기능 블록 내 비일관).

**제안**: OFF 분기의 실패도 ON 분기처럼 `goto error_exit`로 보내면(또는 최소한 실패 시
`do_flush_class_mop`를 다시 false로) assert 함정과 오류 마스킹을 피할 수 있다. (encrypt/collation도
`break` 관습을 따르지만, 이 신규 블록은 바로 옆 형제 분기와 처리 방식이 엇갈린다는 점에서 신규 지적)

---

## 조사 종료 선언

3차 전수 재수색을 여기서 마친다. **잔여 쿼터(29)를 다 채우지 못했고, 근거 있는 신규 결함
3건(문제 24~26)만 추가한 뒤 종료한다** — 억지 지적을 피한 정상 종료다.

### 이번에 훑은 영역과 판단 근거

- **parse_tree.h / parse_tree_cl.c**(88건 미커버): `PT_TABLE_OPTION_REPLICATION`(끝 추가, 안전),
  `PT_CHANGE_REPLICATION`(PT_ALTER_CODE 중간 삽입 — 직렬화·배열첨자로 안 쓰여 무해), 프린터 값
  출력 결함 1건 발굴(문제 24).
- **error_code.h / cubrid.msg**(88건 부분 커버): 신규 -1375~-1378 정의·메시지 인자 수를 사용처와
  대조. `ER_HA_REPLICATION_CONSTRAINT_VIOLATION`(1378, `%1$d`+`%2$s`)는 util_cs.c:3388
  `er_set(..., 2, count, file)`와 인자 수·타입이 일치 — 문제 없음. `dbi_compat.h`는 애초에
  `ER_` 코드 미러가 아님(정의 0건)이라 "6군데 규칙"의 미러 누락은 성립하지 않음 — 지적 제외.
- **object_representation_sr.c/.h**: `or_is_replication_candidate_key`·`or_class_is_replication_on`
  로직 정독. 판정 정의 불일치(전부 NOT NULL vs 하나라도)는 K-5/문제 4, REVERSE_UNIQUE·필터인덱스
  구분은 K-5/K-26, 매직넘버 32는 K-10/문제 9로 이미 커버 — 중복 회피. `extern`/헤더 노출
  불일치만 신규(문제 25).
- **schema_manager.c / schema_template.c**: `sm_is_replication_class` assert(false)=K-7,
  `find_index_catalog_class` dead code=K-33로 커버. `db_make_string`은 복사 없이 포인터만
  담으므로 누수 아님(확인) — 지적 제외.
- **class_object.c**: `classobj_copy_pk_and_uk_notnull_constraints`가 `SM_IS_CONSTRAINT_UNIQUE_FAMILY`
  (PK 포함, class_object.h:112-114 확인)로 PK도 복사함을 검증 — "PK 누락"은 오판이라 제외.
  범용 attribute-copy 경로 부작용은 K-24, PK 미감지 promote는 K-51로 커버.
- **execute_schema.c**: `check_ha_repl_constraint`/FK 검증(pk_c NULL 역참조=K-4/문제5,
  참조클래스 fetch 오판=K-57), `do_alter` 게이트 첫 절만=K-1/문제2, MODIFY 누락=K-6/문제3,
  savepoint 이름 재사용=K-9/문제15, do_alter_change_replication -1376 모순=K-31 — 전부 커버.
  `do_alter`의 이른 `return NO_ERROR`(:2065)는 성공 경로라 savepoint가 커밋 시 자연 해소되어
  누수 아님(확인) — 제외. 생성 경로 실패처리 비대칭만 신규(문제 26).
- **execute_statement.c(SBR)**: `is_replication_class` assert(false)=K-15/문제23,
  이름 재조회=K-48, 혼합 ON/OFF 멀티테이블=K-52, USE_SBR OFF-소스 참조=K2-1,
  링키지=K2-3, TRUNCATE OFF 무시=K-32/문제10로 커버. `is_data_repl_log_enabled` default:true는
  기존 동작 유지(회귀 아님, 확인) — 제외.
- **locator_sr.c**: INSERT/DELETE `replicated` 플래그 + OFF 시 반복 `heap_get_class_repl_on`은
  K2-2로 커버. UPDATE 경로의 `heap_is_replication_class` 잔존은 §7 가정으로 지적 금지.
- **util_service.c / util_cs.c / util_admin.c / utility.h**: rkcheck 첫 실패 break=K-44,
  타임아웃 부재=K-28, 기동 순서=K-30, NULL FILE* fprintf=K-2/문제6, 종료코드·파일명·버퍼
  트렁케이션=K-13/K-38~K-48, enum 중간삽입=K-61/문제21, usage 메시지 형식=K-60/문제20으로 커버.
  `us_hb_process_rkcheck`의 `PRM_ID_HA_MODE_FOR_SA_UTILS_ONLY` 미복원은 단명 admin 프로세스라
  실害 없음 — 제외.
- **object_printer.cpp / unload_schema.c**: 뷰 REPLICATION 출력=K-68/문제22, fetch 실패 OFF
  오표시=K-29/K-45, '=' 표기=K-50, 구버전 loaddb=K-27로 커버.
- **checksumdb.c**: suppress-repl 브래킷은 `db_execute` 뒤 무조건 false로 해제되어 플래그 잔류
  없음(확인), API 실패는 CHECK_CONNECT_ERROR에서만이라 실질 미발현 — 문제23 논의와 동일 결론으로
  제외.
- **px_worker_manager.cpp / csql_lexer.l**: 각각 빈 줄 1개 추가, REPLICATION 토큰 추가(비예약어
  누락은 K-11/문제7로 커버) — 신규 결함 없음.

정합성의 최종 확인(마스터/슬레이브 실제 어긋남, DDL 스키마 복제의 pt_print 사용 여부)은 정적
분석 범위를 넘어 런타임/HA 테스트가 필요하다 — 문제 24의 왕복 재파싱 파급은 코드 근거까지만
확정하고 재현은 QA로 넘긴다.

### 심각도별 신규 집계 (3차)

| 심각도 | 개수 | 문제 번호 |
|---|---:|---|
| 치명 | 0 | — |
| 중요 | 0 | — |
| 보통 | 1 | 24 |
| 사소 | 2 | 25, 26 |
| **신규 계** | **3** | |
