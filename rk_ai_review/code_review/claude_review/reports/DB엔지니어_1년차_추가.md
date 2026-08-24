# CUBRID RK/REPLICATION 기능 코드 리뷰 — DB 엔지니어 1년차 (3차 전수 재수색)

> **기준**: `734f4959d` (merge-base `b646647ec` ... HEAD, 35파일 +1,444/−57)
> **범위**: 1·2차 리포트(`DB엔지니어_1년차.md`, 문제 1~18)와 기존 병합 이슈 67건(K-1~K-69, K2-1~K2-3)이 아직 다루지 않은 파일/함수를 우선순위로 잡아 diff 35개 파일 전체를 다시 훑었다.
> **문제 번호는 기존 리포트(1~18)에 이어 19번부터 시작한다.**

## 재수색 방법

1. `git diff b646647ec...HEAD --stat`로 35개 파일 전체 목록을 뽑고, 기존 리포트·기존 67건이 다룬 파일(execute_schema.c, util_cs.c, object_representation_sr.c, schema_manager.c, class_object.c/h, execute_statement.c, object_printer.cpp, unload_schema.c, csql_grammar.y, semantic_check.c, btree.c/h, util_service.c, schema_template.c, utility.h, locator_sr.c, heap_file.c, schema_system_catalog_install*.cpp, msg 파일들)를 표시했다.
2. **아직 아무 리포트도 다루지 않은 파일**부터 우선 Read로 diff를 직접 읽었다: `checksumdb.c`, `util_admin.c`, `px_worker_manager.cpp`, `error_code.h`, `parse_tree_cl.c`, `csql_lexer.l`, `parse_tree.h`.
3. 이미 다룬 파일들도 diff 전체를 다시 Read해, 기존 문서가 인용한 코드 조각 "바깥"에 새로운 로직이 있는지 확인했다(예: `locator_sr.c`의 `locator_update_index()` 전체, `class_object.c`의 `classobj_copy_pk_and_uk_notnull_constraints()` 전체, `execute_statement.c`의 `is_data_repl_log_enabled()` 전체).
4. 발견한 후보는 반드시 dedup_existing.json(67건) 및 자체 1~18번과 "같은 뿌리(같은 함수/같은 안티패턴)"인지 대조해, 같으면 폐기하고 다른 각도로 취급하지 않았다.

**중요 가정 준수**: 작업지시서 §7 지시대로, `locator_update_index()`(`locator_sr.c:8430`)에 남아있는 옛 `heap_is_replication_class()` 호출(assert(false) 없이 bool만 반환 — KILL QUERY 무시 버그의 잔존 경로)은 발견했으나 **지적하지 않았다.** 이는 커밋 `60648d919` 기준으로 수정 완료된 것으로 간주하라는 명시적 지시에 따른 것이다.

---

## 문제 19 — [중요] checksumdb가 복제 로그 억제 해제(RPC) 실패를 체크섬 계산 자체의 실패로 오판해, 성공한 청크까지 통째로 버리고 해당 테이블 점검을 조기 중단한다

**위치**: `src/executables/checksumdb.c:1727-1763` (`chksum_calculate_checksum`), 호출자 `checksumdb.c:2005-2019` (`chksum_start`의 청크 순회 루프)

**로직 설명**: `checksumdb`는 각 테이블을 청크 단위로 순회하며 체크섬을 계산한다. `chksum_calculate_checksum()`은 한 청크를 처리할 때:

```c
error = db_set_suppress_repl_on_transaction (true);   /* RBR 억제 ON — 서버로 네트워크 요청 */
if (error != NO_ERROR) { ... return error; }

res = db_execute (query, &query_result, &query_error);   /* 실제 체크섬 계산 쿼리 실행 */

/* resume row-based replication right after the local execution; keep its result as the error baseline,
 * an actual execution failure below supersedes it */
error = db_set_suppress_repl_on_transaction (false);      /* RBR 억제 OFF — 다시 네트워크 요청 */

if (res >= 0)
  {
    db_query_end (query_result);
    res = chksum_update_master_checksum (parser, table_name, chunk_id);   /* 계산 결과를 마스터 체크섬 테이블에 기록 */
    if (res < 0) { error = res; }
  }
else
  {
    ... er_set (...); error = res;
  }

return error;
```

`db_set_suppress_repl_on_transaction()`은 `CS_MODE`에서 `net_client_request()`를 통해 **서버로 RPC를 보내는 함수**다(`src/communication/network_interface_cl.c:2653`, `log_set_suppress_repl_on_transaction()`). 즉 순수 로컬 플래그 설정이 아니라 네트워크 왕복이 필요한 호출이며, 연결 문제·타임아웃 등으로 실패할 수 있다.

주석("keep its result as the error baseline, an actual execution failure below supersedes it")이 의도한 바는 "이후 `db_execute`나 `chksum_update_master_checksum`이 실패하면 그 값으로 `error`를 덮어써야 한다"는 것인데, 실제 코드는 그 반대의 결함도 갖는다: **`db_execute`와 `chksum_update_master_checksum`이 모두 성공(`res >= 0`)한 정상 케이스에서, `error`는 `db_set_suppress_repl_on_transaction(false)`가 반환한 값 그대로 함수 반환값이 된다.** 이 RPC가 실패해 `error != NO_ERROR`가 되면, 체크섬 계산과 마스터 테이블 기록이 모두 성공했음에도 `chksum_calculate_checksum()`은 실패를 반환한다.

호출자 `chksum_start()`는 이 반환값을 다음과 같이 처리한다(`checksumdb.c:2005-2019`):

```c
error = chksum_calculate_checksum (parser, class_oidp, table_name, attributes, lower_bound, chunk_id, chksum_arg->chunk_size);
if (error != NO_ERROR)
  {
    (void) db_abort_transaction ();     /* 방금 저장한 체크섬 계산 결과까지 롤백됨 */
    if (error != ER_INTERRUPTED)
      {
        break;                          /* 이 테이블에 대한 청크 순회를 여기서 중단 */
      }
    ...
  }
```

즉 이 RPC 하나가 실패하면 (1) `db_abort_transaction()`으로 방금 정상 계산·기록된 체크섬까지 롤백되어 버려지고, (2) `ER_INTERRUPTED`가 아닌 한 해당 테이블의 나머지 청크 처리가 그 자리에서 `break`되어 **더 이상 진행되지 않는다.**

**PR 히스토리 근거**: 이 `db_set_suppress_repl_on_transaction()` 패턴은 `#6908`(SBR/checksumdb 버그 수정, 이 기능 diff의 일부)에서 처음 도입됐다. 같은 PR이 손댄 `execute_statement.c`의 원조 호출부(`:3772`)는 정반대로 더 방어적으로 짜여 있다 — 그쪽은 `suppress_repl_error`를 별도 변수에 받아 `repl_error == NO_ERROR` 조건에 넣고, 최종적으로 `repl_error != NO_ERROR`일 때만 `error`를 덮어쓴다(그 결과 원본 쪽은 반대로 "억제 해제 실패 시 스키마 복제 로그 자체를 조용히 건너뛰고도 에러를 보고하지 않는" 문제가 있지만, 적어도 **이미 성공한 작업 결과를 실패로 뒤집지는 않는다**). checksumdb.c의 이번 신규 코드는 이 원조 패턴보다 더 단순하게(무조건 대입) 작성되면서, "이미 성공한 케이스"를 보호하는 조건 검사가 빠졌다.

**문제 시나리오**: 대량 테이블에 대해 `checksumdb`를 오래 실행하는 동안(청크가 수백~수천 개일 수 있음) 네트워크 순간 단절이나 서버 과부하로 이 억제-해제 RPC 왕복 중 하나가 실패하면:
- 방금 정확히 계산되어 마스터 체크섬 테이블에 기록됐던 결과가 롤백으로 사라지고,
- 해당 테이블의 나머지 청크는 아예 검사되지 않은 채 `checksumdb`가 그 테이블을 "실패"로 보고하며 넘어간다.
- 운영자가 보는 것은 "체크섬 계산 실패"라는 에러뿐이라, 실제로는 계산 자체는 문제없이 끝났고 단지 뒤처리 RPC 하나가 흔들렸을 뿐이라는 사실을 알 수 없다. 대량 스키마에서 이 도구를 정기적으로 돌려 마스터/슬레이브 정합성을 감시하는 운영 환경에서는, 이런 오탐이 반복되면 "체크섬 불일치 알람"과 "일시적 RPC 실패로 인한 조기 중단"을 구분할 수 없어 checksumdb 결과 자체에 대한 신뢰가 떨어진다.

**제안**: `execute_statement.c`의 기존 패턴처럼, `db_set_suppress_repl_on_transaction(false)`의 반환값은 `res >= 0 && chksum_update_master_checksum(...) >= 0`인 성공 경로에서는 `error`에 반영하지 않거나(로그만 남기고 무시), 최소한 "계산은 성공했지만 억제 해제에 실패했다"를 구분할 수 있는 별도 반환 경로/로그를 추가해 `chksum_start()`가 불필요하게 `db_abort_transaction()` + `break`하지 않도록 한다.

---

## 조사 종료 선언

**신규 발굴**: 1건 (문제 19).

**훑은 범위와 판단 근거**:
- **완전히 새로 연 파일** — `checksumdb.c`(신규 발견 1건 도출), `util_admin.c`(rkcheck용 `UTIL_MAP`/`GETOPT_LONG` 엔트리 추가뿐, 기존 옵션 문자열·짧은 옵션과 충돌 없음을 확인 — 문제 없음), `px_worker_manager.cpp`(빈 줄 1개 추가뿐), `error_code.h`(에러코드 4개 신설 + `ER_LAST_ERROR` 갱신, 값 중복·누락 없음 확인), `parse_tree_cl.c`(`PT_TABLE_OPTION_REPLICATION` print case 추가, 다른 옵션과 동일 패턴), `csql_lexer.l`(REPLICATION 키워드 추가, 기존 토큰과 충돌 없음). 이 6개 파일에서는 문제 19 외에 근거 있는 결함을 찾지 못했다.
- **재확인한 기존 커버 파일** — `locator_sr.c`(`locator_update_index()` 전체를 다시 읽고 §7 가정에 따라 잔존 `heap_is_replication_class` 호출은 의도적으로 미지적), `class_object.c`(`classobj_copy_pk_and_uk_notnull_constraints()`를 라인 단위로 검증 — `SM_IS_CONSTRAINT_UNIQUE_FAMILY`가 PK를 포함함을 `class_object.h:111-115`로 확인했고, 링크드리스트 역순 삽입은 이후 소비처가 존재 여부만 검사하므로 실질적 결함 아님으로 판단 — K-24와 같은 뿌리), `execute_statement.c`(`is_data_repl_log_enabled`/`spec_has_replication_class`/`pt_spec_repl_class_walk` 전체 — K2-1과 같은 뿌리), `csql_grammar.y`/`semantic_check.c`(REPLICATION 절 중복 처리 확인 — K-20과 같은 뿌리), `util_service.c`(`us_hb_process_rkcheck` 전체 — K-28/K-30/K-44/K-65와 같은 뿌리), `schema_manager.c`, `object_representation_sr.c`, `btree.c/h`, `schema_system_catalog_install*.cpp`, `object_printer.cpp`, `unload_schema.c`, `heap_file.c/h`, `utility.h`, `error_code.h`/`cubrid.msg` — 모두 재검증 결과 기존 K-리스트 또는 1~18번 문제와 위치·원인이 동일함을 확인하고 신규로 세지 않았다.

**더 찾지 않은 근거**: 35개 파일 전체 diff(+1,444/−57)를 라인 단위로 다시 훑었고, 신규 함수·신규 분기 중 기존 67건 + 1~18번이 다루지 않은 코드는 `checksumdb.c`의 억제-해제 RPC 처리 하나뿐이었다. 나머지는 표현·위치만 다를 뿐 이미 등록된 안티패턴(assert(false)+false 삼킴, 인덱스 순회 반복 호출, 위치 하드코딩 등)의 반복이거나, 작업지시서가 수정 완료로 간주하라고 명시한 잔존 호출이었다. 이 시점에서 추가로 시간을 들여도 근거 없는 표현 트집 외에 새 발견이 나올 가능성이 낮다고 판단해, 잔여 쿼터(33건)를 채우지 않고 1건에서 조사를 마친다.

---

## 심각도별 집계 (이번 라운드 신규분)

| 심각도 | 건수 | 문제 번호 |
|---|---|---|
| 중요 | 1 | 19 |
| **신규 합계** | **1** | |

**누적(1~2차 17건 + 3차 1건) = 18건.**
