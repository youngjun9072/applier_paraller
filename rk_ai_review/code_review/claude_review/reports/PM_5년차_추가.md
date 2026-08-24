# CUBRID RK/REPLICATION 기능 코드 리뷰 — PM (5년차) 3차 전수 재수색

> **3차 전수 재수색** — 기준 `734f4959d` (diff 범위 `b646647ec...HEAD`, 35파일 +1,444/−57)
> 기존 리포트(`PM_5년차.md`, 문제 1~14, 11건)와 병합 완료된 전체 67건(`dedup_existing.json`)이
> 아직 다루지 않은 파일/영역을 우선순위로 재수색했다. 잔여 쿼터 = 50 − 11 = 39건이나,
> 근거 있는 신규 문제만 보고한다(작업지시서 §4 규칙 1).

## 수색 방법

1. `git diff b646647ec...HEAD --stat`로 35개 파일 전체 목록을 다시 뽑고, 기존 리포트(11건)와
   dedup 67건이 짚은 위치(loc)를 파일 단위로 대조해 **아직 언급되지 않은 파일**을 추렸다:
   `error_code.h`, `object_representation_sr.h`, `class_object.h`, `schema_manager.h`,
   `execute_schema.h`, `btree.h`, `heap_file.h`, `csql_lexer.l`, `parse_tree.h`,
   `parse_tree_cl.c`, `util_admin.c`, `px_worker_manager.cpp`.
2. 이 파일들의 실제 diff(`git diff` 전체 hunk)를 Read로 읽고, 헤더 선언과 실제 구현부/호출부를
   grep+Read로 대조해 시그니처 불일치·미완성 케이스가 있는지 확인했다.
3. `parse_tree.h`에 새로 추가된 `PT_CHANGE_REPLICATION`/`replication.tbl_replication` 유니온
   멤버가 파서 트리 워커·프린터 전 구간에서 일관되게 처리되는지 LSP 없이 grep으로 전수
   추적했다(`pt_apply_alter`, `pt_print_alter_one_clause`, `csql_grammar.y`, `execute_schema.c`,
   `semantic_check.c` 5곳 모두 대조).
4. `checksumdb.c`, `msg/*.msg`(1376~1378 신규 메시지 3종)도 재확인했으나 기존 문제 5·13과
   동일한 뿌리이거나 EN/KO 메시지가 서로 일치해 신규 사항 없음을 확인했다.

---

## 신규 문제

### 문제 15 — [심각도: 보통] `ALTER TABLE ... REPLICATION` 절이 트리 재출력(unparse) 경로에서 조용히 누락된다 — 형제 절(OWNER/COMMENT/COLLATION)과 구현 완성도가 불일치

**위치**: `src/parser/parse_tree_cl.c:5784-5920`(`pt_print_alter_one_clause()`의 `switch (p->info.alter.code)`),
비교 대상 `src/parser/parse_tree.h:1299`(`PT_CHANGE_REPLICATION` 열거값 추가),
`:1888-1891`(`alter_clause.replication.tbl_replication` 유니온 멤버 추가),
`src/parser/csql_grammar.y:5862-5871`(파서가 `alter_node->info.alter.code = PT_CHANGE_REPLICATION`을
설정하고 `tbl_replication`을 채우는 지점).

**로직 설명**: 이번 기능이 `ALTER TABLE t REPLICATION={ON|OFF};` 절을 파싱해 `PT_ALTER` 노드에
`PT_CHANGE_REPLICATION`이라는 새 `alter.code`와 `alter_clause.replication.tbl_replication`이라는
새 유니온 멤버를 채운다. 이 값을 소비하는 실행 경로(`execute_schema.c:2033`,`:11738`)는 정상
연결돼 있음을 확인했다.

문제는 **파스 트리를 다시 SQL 텍스트로 되돌리는(unparse) 경로**다. CUBRID 파서는 `PT_NODE`를
문자열로 되돌리는 함수 포인터 테이블(`pt_print_func_array[PT_ALTER] = pt_print_alter`, 5308번 줄)을
가지고 있고, 실제 절별 텍스트 조립은 `pt_print_alter_one_clause()`의 `switch`문이 담당한다.
같은 시기에 추가된 형제 절들은 전부 이 switch에 케이스가 있다:

```c
case PT_CHANGE_OWNER:          /* :5788 */
case PT_CHANGE_TABLE_COMMENT:  /* :5793 — " comment = " 출력 */
case PT_CHANGE_COLLATION:      /* :5798 */
```

그런데 `PT_CHANGE_REPLICATION`은 이 switch 어디에도 없다(5784~5920 전체를 grep+Read로 확인,
`default: break;`로 빠진다). 반면 **CREATE TABLE 쪽 옵션 프린터**(`pt_print_table_option()`,
`parse_tree_cl.c:8038-8041`)에는 이번 기능이 정확히 대칭 케이스를 추가해 놓았다:

```c
case PT_TABLE_OPTION_REPLICATION:
  q = pt_append_nulstring (parser, q, "replication = ");
  break;
```

즉 "CREATE TABLE ... REPLICATION"은 재출력 가능하지만, "ALTER TABLE ... REPLICATION"은
재출력 시 그 절 자체가 통째로 사라진다 — 같은 기능의 두 진입점(CREATE/ALTER) 중 하나만
프린터 구현을 완성한 전형적인 누락 패턴이다(PR 히스토리에서 반복적으로 나타난 "한 진입점만
확장되고 다른 진입점은 누락" 패턴, 예: `#6826`의 TRUNCATE 케이스와 동일 성격).

**영향 범위 확인**: 실제 HA 복제 텍스트 전송 경로(`do_replicate_statement()`,
`execute_statement.c:16502` 이하)는 `parser_print_tree()` 재구성 텍스트가 아니라
`statement->sql_user_text`(사용자가 입력한 원문 그대로)를 사용함을 확인했다 — 따라서 **슬레이브로
전송되는 DDL 복제 자체는 이 결함의 영향을 받지 않는다**. 다만 `parser_print_tree()`/
`pt_print_alter`는 범용 unparse 유틸리티로, 트리 기반으로 SQL을 재구성해야 하는 다른 모든
소비처(예: 파서 회귀 테스트의 round-trip 검증, 에러/디버그 진단 시 statement 재구성 덤프,
향후 이 경로를 재사용할 트리거·마이그레이션 도구)에서 `ALTER TABLE t REPLICATION=OFF;`를
파싱했다가 다시 출력하면 `REPLICATION` 절이 빠진 `ALTER TABLE t;`가 나온다.

**문제 시나리오**: 파서 unparse 결과를 신뢰하는 임의의 후속 도구나 회귀 테스트가 이 절을
포함한 ALTER 문을 파싱 후 재출력하면, 조용히 절 하나가 사라진 상태로 진행된다 —
`REPLICATION=OFF`로 바꾸려던 의도가 텍스트상 소실되어, 이 텍스트를 다시 파싱/실행하는
경로가 있다면 옵션 변경이 반영되지 않는다.

**제안**: `pt_print_alter_one_clause()`의 switch에 `PT_CHANGE_REPLICATION` 케이스를 추가해
`alter_clause.replication.tbl_replication` 값을 " replication = on/off" 형태로 출력하도록
`PT_CHANGE_TABLE_COMMENT` 케이스(5793-5797)와 대칭으로 구현한다.

---

## 조사 종료 선언 (3차)

이번 3차 재수색에서 다음 영역을 커버했다:

1. 기존 리포트(1~14)와 dedup 67건이 위치(loc)로 짚지 않은 나머지 diff 파일 12개
   (`error_code.h`, `object_representation_sr.h`, `class_object.h`, `schema_manager.h`,
   `execute_schema.h`, `btree.h`, `heap_file.h`, `csql_lexer.l`, `parse_tree.h`,
   `parse_tree_cl.c`, `util_admin.c`, `px_worker_manager.cpp`)를 전량 Read로 diff 대조했다.
   대부분은 이미 구현된 기능(예: `heap_get_class_repl_on`, `sm_is_replication_class`,
   `classobj_find_cons_replication_key`)의 헤더 선언 추가일 뿐이라 실질적 결함이 없었다.
2. `parse_tree.h`가 도입한 `PT_CHANGE_REPLICATION`/`tbl_replication` 유니온 멤버를 grep으로
   전수 추적(파서 생성 지점 → 실행 소비 지점 → 프린터)해, 프린터 쪽 누락(문제 15)을 찾아냈다.
3. `checksumdb.c`(신규 23줄)와 신규 에러 메시지 3종(1376~1378, EN/KO)을 재확인했으나
   기존 문제 5·13과 동일 뿌리이거나 이미 로케일 일치가 확인되어 신규 사항이 없었다.
4. `util_admin.c`의 `rkcheck` 옵션 맵 추가는 `util_service.c`의 기존 패턴(`memmon` 등)과
   완전히 동일한 구조로, 별도 결함을 찾지 못했다.

이 이상으로 억지로 쿼터(39건)를 채우기 위한 지적(변수명 취향, 공백 등 스타일 트집)은
배제한다. 잔여 쿼터를 다 채우지 못했지만, 이는 1·2차에서 이미 20개 파일 이상을 깊게
훑었고 dedup 67건이 대부분의 핵심 결함을 포섭했기 때문으로 판단한다 — 정상적인 종료다.

---

## 심각도별 집계 (3차 신규분)

| 심각도 | 건수 | 문제 번호 |
|---|---:|---|
| 보통 | 1 | 15 |
| **합계** | **1** | |

## 누적 요약

| 차수 | 신규 문제 수 | 누적 |
|---|---:|---:|
| 1차 | 12 | 12 |
| 2차 | 유지 9 + 해소 3 + 신규 2 | 11 |
| 3차 | 신규 1 | 12 |
