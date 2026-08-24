# PM 3년차 코드 리뷰 — 3차 전수 재수색 (기준 `734f4959d`)

> **3차 전수 재수색** — 2차 리포트(`PM_3년차.md`, 문제 1~16, 구 문제 12는 해소되어 유효 15건)에
> 이어, 병합 리포트에 이미 반영된 67건(K-1~K-69 중 유효분 + K2-1~K2-3, `dedup_existing.json`)과
> 겹치지 않는 신규 문제를 찾기 위해 diff 35개 파일 전체를 다시 훑었다. 문제 번호는 기존 리포트
> 이어서 17번부터 시작할 예정이었으나, **신규 발굴 0건**으로 번호 부여 없이 종료한다.

## 수색 방법

`git -C /home/youngjun/Workspace/cubrid diff b646647ec...HEAD --stat`로 35개 파일 목록을 뽑아,
기존 리포트(15건)와 `dedup_existing.json`(67건)의 `loc` 필드가 **아직 건드리지 않은 파일**부터
우선순위를 두고 순서대로 Read + git diff로 로직을 직접 열람했다.

### 1순위 — 기존 리포트·dedup 67건 모두 loc이 없는 파일 (전량 diff 직독)

| 파일 | 변경 규모 | 확인 결과 |
|---|---|---|
| `src/executables/util_admin.c` | +14 | `ua_Rkcheck_Option_Map`/`ua_Rkcheck_Option` 신규 등록. `need_args_num=1`은 `OPTION_STRING_TABLE` 1개(DB명)와 일치 — `util_support.c:328-364`의 `need_args_num` 체크 로직과 대조해 정상. 문제 없음. |
| `src/query/parallel/px_worker_manager.cpp` | +1 | 빈 줄 추가뿐(공백 포맷팅). 문제 없음. |
| `src/parser/parse_tree_cl.c` | +3 | `pt_print_table_option()`에 `PT_TABLE_OPTION_REPLICATION` case 추가 — 기존 `ENCRYPT` case와 동일 패턴, 정상. |
| `src/parser/csql_lexer.l` | +5(-1) | `REPLICATION` 키워드 토큰 인식 추가. 인접 `DISK_SIZE` 규칙의 trailing 공백만 우발적으로 정렬됨(기능 영향 없음). |
| `src/base/error_code.h` | +7(-2) | `ER_HA_REPLICATION_KEY_REQUIRED`(-1375) 외 3개 신규 에러코드, `ER_LAST_ERROR`를 -1379로 재조정. 번호 충돌·중복 없음 확인. |
| `src/base/object_representation_sr.h` | +2 | `or_class_is_replication_on`/`or_is_replication_candidate_key` 전방선언 추가. 후자에 `extern` 키워드가 빠져 있으나(다른 선언들과 스타일 불일치) C에서 함수 선언의 기본 링키지는 external이라 실질적 차이 없음 — 근거 부족으로 미채택. |
| `src/object/class_object.h` | +3 | `SM_CLASSFLAG_DATA_REPLICATION_OFF` 플래그, `classobj_has_class_repl_key_constraint`/`classobj_find_cons_replication_key` 선언 추가. 선언-정의 일치 확인(`class_object.c`). |
| `src/object/schema_manager.h` | +1 | `sm_is_replication_class` 선언 추가, 정의와 시그니처 일치. |
| `src/query/execute_schema.h` | +1 | `log_ha_repl_fk_ref_all_replicated` 선언 추가 — 이미 dedup K-25(중복 구현)로 다뤄진 함수의 헤더 노출일 뿐, 신규 결함 없음. |
| `src/storage/btree.h` | 1줄 rename | `btree_get_pkey_btid`→`btree_get_rkey_btid` 시그니처 변경. 호출부(`locator_sr.c:6845`, `btree.c:8264`)와 일치 확인. 내부 로직(첫 매치 break)은 이미 K-58로 다뤄짐. |
| `src/storage/heap_file.h` | +1 | `heap_get_class_repl_on` 선언 추가, 정의(`heap_file.c`)·호출부(`locator_sr.c`)와 일치. |

### 2순위 — 기존 항목이 있지만 로직을 처음부터 재추적한 파일

- `src/transaction/locator_sr.c` (전체 47줄 diff): `locator_add_or_remove_index_internal()`의
  `replicated` 플래그 도입부, `locator_update_index()`의 `pk_btid_index`→`rk_btid_index` 리네이밍을
  라인 단위로 재확인했다. **`locator_update_index()`의 `heap_is_replication_class()` 잔존 호출은
  작업지시서 §7 가정에 따라 지적하지 않았다.** 그 외 `locator_add_or_remove_index_internal()`의
  `!replicated` 게이트는 `repl_on == false`일 때 매 RK후보 인덱스마다 `heap_get_class_repl_on()`을
  다시 호출하는 구조인데, 이는 dedup K2-2와 동일한 원인(인덱스 루프 안에서 클래스 조회 반복)이라
  신규로 세지 않았다.
- `src/query/execute_statement.c`의 `#7678` 델타 전체(`is_replication_class`,
  `get_spec_classname`, `pt_spec_repl_class_walk`, `spec_has_replication_class`,
  `is_data_repl_log_enabled`, 총 ~155줄)를 처음부터 다시 읽었다. `is_data_repl_log_enabled()`의
  `switch`문에 `PT_MERGE` case가 없어 `default: return true`로 떨어지는 것을 확인했으나,
  `is_stmt_based_repl_type()`(같은 파일 393-426행)을 LSP로 역추적한 결과 PT_MERGE는애초에
  이 함수가 true를 반환하는 대상이 아니어서(DDL·PT_DROP_VARIABLE·USE_SBR 힌트 붙은
  INSERT/UPDATE/DELETE만 해당) `is_data_repl_log_enabled()`의 `default` 분기에 MERGE가 도달할
  경로 자체가 없다 — 실제 결함으로 이어지지 않아 기각.
- `src/object/class_object.c` 전체 106줄: 신규 `classobj_copy_pk_and_uk_notnull_constraints()`가
  제약을 연결리스트 맨 앞에 계속 prepend해 원본 `src->constraints` 순서와 반대 순서로
  `dest->constraints`를 구성하는 것을 발견했으나, 이 함수가 삽입된 지점(`classobj_init_attribute`)
  자체의 파급 범위 문제는 이미 K-24로 다뤄지고 있고, 순서 역전이 실제 RK 선택(`btree.c`의
  배열 인덱스 기반, K-58)에 영향을 준다는 근거를 코드에서 찾지 못해(별개의 SM_CONSTRAINT
  연결리스트이지 BTREE 인덱스 배열이 아님) 채택하지 않았다.
- `src/parser/csql_grammar.y` 전체 51줄: `class_replication_spec`가
  `alter_clause_for_alter_list`에 추가되며 `alter_node->info.alter.code != PT_CHANGE_REPLICATION`
  로 자기 자신의 목표 코드와 비교하는 가드를 사용한다(이웃 `class_comment_spec`은
  `!= PT_CHANGE_COLUMN_COMMENT`처럼 다른 충돌 코드와 비교하는 패턴). 복붙 과정에서 비교 대상이
  의미 없이 자기 참조로 바뀐 것으로 보이나, 이 축약(reduce) 규칙이 한 클래스당 한 번만 실행되는
  문법 구조상 실제 동작 차이를 만드는 시나리오를 찾지 못해(가능성만으로는 채택 기준 미달)
  근거 부족으로 기각.
- `src/executables/checksumdb.c`(+23), `src/executables/util_service.c`(+76): 신규
  `us_hb_process_rkcheck()`, `db_set_suppress_repl_on_transaction` 감싸기 코드를 라인 단위로
  재확인했으나 기존 문제 9(checksumdb 에러 컨텍스트 누락), K-28/K-44/K-55(rkcheck 타임아웃·순서·
  failover 우회) 이상의 새 결함은 없었다.
- `msg/*.msg` 4개 파일: 신규 에러 메시지 1375~1378의 문구를 en/ko 대조했다. 1375 국문 메시지의
  "테이블 생성 시" 고정 표기는 기존 문제 14(K-23)와 동일 건. 그 외 메시지는 en/ko 의미 일치,
  포맷 스트링(`%1$d`, `%2$s`) 개수·순서 일치 확인. utils.msg의 trailing whitespace/개행 누락은
  기존 문제 15(K-60)와 동일.

## 결론

35개 파일 전체를 대상으로, 특히 기존 두 리포트(15건 + 67건)의 `loc`이 닿지 않은 11개 파일은
전량 diff를 직접 읽고, 이미 다뤄진 파일 중 로직이 복잡한 6개 파일(`locator_sr.c`,
`execute_statement.c`, `class_object.c`, `csql_grammar.y`, `checksumdb.c`, `util_service.c`)은
호출 체인을 재추적했다. 그 결과 확증 가능한 신규 결함을 찾지 못했다 — 발견한 후보들(제약 리스트
순서 역전, MERGE 분기 부재, 문법 가드 자기참조)은 모두 실제 파급 경로를 추적한 결과 결함으로
이어지지 않거나(MERGE), 근거가 간접적이라 "억지 지적 금지" 원칙에 따라 제외했다.

**잔여 쿼터(35건, 50−15)를 채우지 못하고 종료한다.** 이는 정상적인 결과다 — 1차·2차에 걸쳐
이미 20개 페르소나가 이 diff를 반복 수색했고, 그 병합 결과 67건이 이미 확정되어 있어, 3차
시점에는 남은 표면적이 매우 좁다.

## 조사 종료 선언 (3차)

- **신규 발굴**: 0건
- **훑은 영역**: diff 35개 파일 전체(`--stat` 기준), 그중 기존 리포트·dedup 67건이 loc으로
  전혀 언급하지 않은 11개 파일은 전량 Read, 나머지 24개 파일 중 로직이 새로 추가된 구간은
  git diff로 재대조.
- **판단 근거**: 후보 3건(제약 복사 순서 역전 / MERGE 문 분기 부재 / grammar 가드 자기참조)을
  실제 호출 체인·조건 분기까지 추적했으나 관찰 가능한 결함으로 이어지지 않거나 기존 항목과
  원인이 같아 신규로 세지 않았다.
