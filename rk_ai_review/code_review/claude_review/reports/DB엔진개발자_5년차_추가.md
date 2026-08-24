# RK/REPLICATION 코드 리뷰 — DB엔진 개발자 5년차 관점 (3차 전수 재수색)

> **3차 전수 재수색 (기준 HEAD `734f4959d`, feature/CBRD-26246-develop)**
> merge-base(upstream/develop) `b646647ec` 대비 35파일(+1,444/−57) 전체를 재수색했다.
> 기존 리포트(`DB엔진개발자_5년차.md`)의 유지 문제 16건과 이미 병합된 67건(dedup_existing.json, K-1~K-69·K2-1~3)을
> 출발점으로 삼아, **그 뿌리와 겹치지 않는 신규 결함**만 추가 발굴한다.
> 잔여 쿼터 = 50 − 16 = 34. 결과: **신규 1건 추가**, 나머지는 근거 있는 신규 결함을 찾지 못해 종료 선언.
>
> 문제 번호는 기존 리포트(문제 2~19)에 이어서 **문제 20**부터 매긴다.

---

## 수색 방법과 커버리지

`git diff b646647ec...HEAD --stat`의 35파일을 파일별로 diff를 읽고, 기존 리포트·67건이
아직 안 훑은 파일/함수를 우선으로 로직을 따라갔다. LSP 대신 정의 점프는 grep/sed로 콜체인을 직접
확인했다(호출부·피호출부 실체 확인, 키워드 매칭만으로는 지적하지 않음). 파일별 커버리지:

- **execute_schema.c(+405)**: `do_alter` 다중절 게이트·최종 재검사(K-1/K-17·기존 #2/#10), `IS_REPL_CONSTRAINT_RELATED_ALTER` 누락(K-6/#11), `do_alter_change_replication` 세이브포인트 재사용·FK 미재검증(K-9/K-54), `check_ha_repl_constraint`/`check_ha_repl_fk_ref_all_replicated`/`log_ha_repl_fk_ref_all_replicated`(K-4/K-25/K-57·#14), `do_promote_partition`/`has_notnull_unique_constraints`(K-14/K-51), `do_create_entity` LIKE·CTAS(K-21/K-69·#9). → 모두 기존.
- **execute_statement.c(+156)**: `truncate_need_repl_log`(K-32·#7), `is_replication_class` assert 삼킴(K-8/K-15·#18), `is_data_repl_log_enabled`·`spec_has_replication_class`·`pt_spec_repl_class_walk`(K-48/K-52/K2-1/K2-3·#8), `is_stmt_based_repl_type`(MERGE 미포함=문제 아님 확인). → 모두 기존.
- **object_representation_sr.c(+62)**: `or_class_is_replication_on` 매직 32(K-10·#13), `or_is_replication_candidate_key` 필터/함수/역UNIQUE 미검사(K-5/K-26·#4). → 기존. **단, `or_class_flags`의 링키지는 신규(아래 문제 20).**
- **class_object.c(+106)**: `IS_HA_REPLICATION_KEY_CONSTRAINT` 매크로(K-5·#3), `classobj_copy_pk_and_uk_notnull_constraints`의 범용 경로 부작용(K-24), `classobj_find_cons_replication_key`/`classobj_has_class_repl_key_constraint`. → 기존.
- **util_cs.c(+326)**: rkcheck 본체 — NULL fp(K-2·#5), 버퍼(K-13), 종료코드 절단(K-40), 중복 순회(K-41), 부분결과(K-46), 클래스명 미로깅(K-47), 파일명(K-62/K-63), 사용법 메시지(K-60/K-65). → 모두 기존.
- **util_service.c(+76)**: `us_hb_process_rkcheck` 타임아웃 없음(K-28), 서버 선기동(K-30), 첫 실패 break(K-44), 승격 우회(K-55). → 기존.
- **btree.c/.h, locator_sr.c, heap_file.c/.h**: `btree_get_rkey_btid`(K-56/K-58·#4), `heap_get_class_repl_on` 및 `locator_add_or_remove_index_internal` 재구조화(K-8/K2-2), `locator_update_index`의 잔존 `heap_is_replication_class` 호출은 **작업지시서 §7에 따라 수정 완료 간주·지적 제외**. → 신규 없음.
- **checksumdb.c(+23)**: `db_set_suppress_repl_on_transaction(true/false)` 캡처·전파(#15 해소 근거) 재확인. resume 실패를 성공 실행에도 error로 반환하는 부분은 "억제 플래그 복구 실패 시 트랜잭션을 실패시키는" 방어로 해석 가능 → 결함 아님. → 신규 없음.
- **unload_schema.c(+9), object_printer.cpp(+10)**: REPLICATION 출력 — 버전가드/조회실패/표기/VIEW(K-27/K-45/K-50/K-68·#12 인접). → 기존.
- **schema_manager.c(+20)**: `sm_is_replication_class` assert 삼킴(K-7). → 기존.
- **schema_template.c(+29)**: `find_index_catalog_class` 데드코드(K-33). → 기존.
- **schema_system_catalog_install*.cpp**: `is_replication_class` 컬럼 중간 삽입·포맷 vararg 위치매칭(K-19/K-42·#12). → 기존.
- **csql_grammar.y(+51), csql_lexer.l, parse_tree*.**: REPLICATION 비예약어 누락(K-11·#19), ALTER 중복/혼합 절 세만틱(K-20), `class_replication_spec`/`opt_replication_option`. → 기존.
- **utility.h(+20), util_admin.c(+14)**: `UTIL_INDEX`에 RKCHECK 중간 삽입(K-61·#16), rkcheck 옵션맵. `RKCHECK_MSG_USAGE=60`↔`$set 61` 정합 확인. → 기존/문제 아님.
- **error_code.h(+7), msg/*.msg**: 신규 에러코드 -1375~-1378과 메시지 en/ko 짝 존재·인자수 정합(1375/1376/1377=0인자, 1378=`%1$d`,`%2$s` 2인자, 사용처 er_set 인자수 일치) 확인. 1375 메시지 문구(K-23), 사용법 형식(K-60)은 기존. → 신규 없음.
- **px_worker_manager.cpp**: 빈 줄 1줄 추가(무의미). → 신규 없음.

---

## 문제 20
**[심각도: 사소] 신규 헬퍼 `or_class_flags()`가 프로토타입 없는 비-static 외부 심볼로 노출된다**

- 위치: `src/base/object_representation_sr.c:771` (`void or_class_flags (RECDES *, int *)` 정의)

로직 설명: 이번 diff는 서버 측에서 클래스 레코드의 flags를 뽑는 헬퍼 `or_class_flags()`를 새로 추가했고, 바로 아래 `or_class_is_replication_on()`(:783)이 이를 호출한다. `or_class_is_replication_on()`은 `object_representation_sr.h:244`에 `extern`으로 선언됐지만, `or_class_flags()`는 **어떤 헤더에도 선언이 없고 정의도 `static`이 아니다**(grep 결과 헤더 0건, 호출부는 동일 TU의 `or_class_is_replication_on` 단 한 곳뿐). 같은 파일의 형제 헬퍼 `or_class_hfid`/`or_class_tde_algorithm`은 모두 헤더에 `extern` 선언을 갖는 반면, `or_class_flags`만 선언 없이 전역 링키지로 남았다.

문제 시나리오: (1) 다른 번역 단위가 실수로 `or_class_flags`라는 같은 이름의 심볼을 정의하면 링크 시점에 중복 정의로 충돌하거나, 반대로 이 이름을 우연히 참조하면 프로토타입이 없어 암시적 선언/인자 불일치가 잡히지 않는다. (2) `-Wmissing-prototypes` 계열 경고를 켠 빌드에서는 경고(환경에 따라 `-Werror`면 빌드 실패)를 유발한다. 즉 파일 내부 전용 헬퍼가 의도치 않게 전역 API 표면으로 새어 나간 것으로, 링크·유지보수 관점의 잠재 위험이다.

제안: 파일 내부에서만 쓰이므로 `static void or_class_flags (...)`로 바꾸는 것이 맞다. 만약 다른 곳에서 재사용할 의도라면 형제 함수들처럼 `object_representation_sr.h`에 `extern` 프로토타입을 추가해야 한다.

근거·연관: 이 결함은 "신규 헬퍼의 static/링키지 누락" 패턴으로, 이미 병합 리스트에 동일 유형이 두 건 있다(K-36 `execute_schema.c`의 static 불일치, K2-3 `execute_statement.c`의 `is_data_repl_log_enabled` 링키지 애매). 다만 본 건은 **loc(파일·함수)가 완전히 다른 별개 함수**이므로 중복이 아니라 같은 유형의 새 인스턴스다. #6908 리뷰에서 vimkim이 정확히 이 부류(dead 선언·`static` 누락·반환타입 혼용)를 diff까지 제시하며 지적했던 전례가 있어, 팀 기준에서도 보고 가치가 있는 지적이다.

---

## 조사 종료 선언

**잔여 쿼터 34건 중 근거 있는 신규 결함은 1건(문제 20)만 발굴하고 종료한다.**

판단 근거:
- 35파일 전체를 파일별로 diff를 읽고 콜체인을 확인했으나, 실질 변경이 있는 모든 함수는 이미 기존 리포트 16건 또는 병합된 67건(K-리스트)이 **loc·원인 기준으로 이미 덮고 있었다.** 각 파일의 대응 관계는 위 "커버리지"에 명시했다.
- 정확성에 직접 영향을 주는 핵심 결함군(다중절 ALTER 게이트 오참조 K-1/#2, 부분 NOT NULL UNIQUE RK 오인 K-5/#3, 서버 RK 후보의 필터·함수·역UNIQUE 미검사 K-5/K-26/#4, rkcheck NULL fp 크래시 K-2/#5, FK PK NULL 역참조 K-4/#14, assert(false)+false 안티패턴 확산 K-7/K-8/K-15)은 **이미 발굴되어 있고, 이들의 수정·런타임 검증이 신규 정적 발굴보다 우선**이다.
- 새로 눈에 들어온 후보 몇 건(checksumdb resume-error 반환, `us_hb_process_rkcheck`의 `PRM_ID_HA_MODE_FOR_SA_UTILS_ONLY` 전역 잔존, `alter_clause_for_alter_list`의 replication 절 code 덮어쓰기)은 각각 **정상 방어로 해석 가능**하거나(전자·후자는 트랜잭션/노드 처리 맥락에서 무해), **이미 K-20이 같은 뿌리(중복/혼합 REPLICATION 절 세만틱 부재)를 덮고 있어** 신규로 세지 않았다.

억지로 쿼터를 채우기보다, 확인된 유지 16건 + 신규 1건(문제 20)으로 마감하는 것이 리포트 신뢰도에 부합한다고 판단한다.

### 심각도별 집계 (3차, 유지 16 + 신규 1)

| 심각도 | 유지 | 신규 | 계 |
|---|---|---|---|
| 치명 | 0 | 0 | 0 |
| 중요 | 4 (2,3,4,5) | 0 | 4 |
| 보통 | 6 (7,8,9,10,11,12) | 0 | 6 |
| 사소 | 6 (13,14,16,17,18,19) | 1 (20) | 7 |
| **계** | **16** | **1** | **17** |
