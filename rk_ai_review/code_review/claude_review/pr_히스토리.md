# CUBRID REPLICATION 옵션 / RK(Replication Key) 기능 PR 히스토리

CBRD-26096 EPIC("HA 복제 시 PK 제약사항 제거")을 중심으로 진행된 REPLICATION 옵션 도입부터,
RK(Replication Key) 제약, rkcheck 유틸리티, 그 이후 버그픽스까지 21개 PR을 시간순(PR 번호 오름차순, #6394 → #7697)으로 정리한다.
입문자가 "왜 이렇게 설계했는지"를 따라갈 수 있도록, 각 PR마다 목적 → 핵심 변경 → 리뷰 논점(암묵지) → 후속 연결 순으로 기술한다.

---

## 전체 타임라인

| # | 티켓 | 제목 | 병합일 | 한줄 요약 |
|---|------|------|--------|-----------|
| [#6394](https://github.com/CUBRID/cubrid/pull/6394) | CBRD-26246 | CREATE TABLE 시 REPLICATION 옵션 추가 | 2025-09-14 | REPLICATION 옵션 문법(파서)만 우선 추가 |
| [#6454](https://github.com/CUBRID/cubrid/pull/6454) | CBRD-26250 | Replication option handling | 2025-09-22 | 옵션 저장(클래스 플래그)·조회(SHOW/db_class) 구현 |
| [#6467](https://github.com/CUBRID/cubrid/pull/6467) | CBRD-26251 | Replication flag 가 설정된 클래스의 DML복제 | 2025-10-14 | 플래그가 실제 DML 복제 여부에 반영되도록 연결, RK(PK 또는 UK) 개념 도입 |
| [#6477](https://github.com/CUBRID/cubrid/pull/6477) | CBRD-26270 | Fix ha constraint | 2025-10-21 | HA 모드에서 RK 없는 복제 테이블 생성 금지, ON/OFF 상호 전환 금지 |
| [#6505](https://github.com/CUBRID/cubrid/pull/6505) | CBRD-26256 | Support adding FK constraints on table creation | 2025-11-03 | FK 참조 시 복제 옵션 조합 제약 추가 |
| [#6570](https://github.com/CUBRID/cubrid/pull/6570) | CBRD-26272 | loaddb & unload 사용시 복제 옵션 출력 및 적용 | 2025-11-03 | unloaddb/loaddb에 REPLICATION 옵션 보존 |
| [#6552](https://github.com/CUBRID/cubrid/pull/6552) | CBRD-26271 | Partition 생성시 복제 옵션 상속 및 승격 시 컬럼 속성 상속 | 2025-12-14 | 파티션 자식 테이블의 복제 옵션·PK/UK 상속 |
| [#6618](https://github.com/CUBRID/cubrid/pull/6618) | CBRD-26273 | ALTER TABLE 로 복제 키 제거 시 제약사항 추가 | 2025-11-11 | RK 컬럼/제약 삭제 시 대체 RK 존재 여부 검사 |
| [#6637](https://github.com/CUBRID/cubrid/pull/6637) | CBRD-26274 | 멀티 ALTER TABLE 을 이용한 PK 변경 허용 | 2025-12-02 | HA 제약 검사 위치를 do_alter()로 이동해 DROP+ADD PK 허용 |
| [#6658](https://github.com/CUBRID/cubrid/pull/6658) | CBRD-26275 | ha 실행 시 RK 제약 조건 확인 | 2026-01-22 | rkcheck 유틸리티 신설(HA 기동 전 사전 점검) |
| [#6739](https://github.com/CUBRID/cubrid/pull/6739) | CBRD-26277 | RK 제거 시 제약사항 위반 버그 수정 및 리팩토링 | 2026-01-21 | FK ALTER 시 자기 테이블 검사 누락 수정 |
| [#6796](https://github.com/CUBRID/cubrid/pull/6796) | CBRD-26277 | Change error message | 2026-01-26 | FK 관련 에러 메시지 문구 정정 |
| [#6798](https://github.com/CUBRID/cubrid/pull/6798) | CBRD-26096 | HA 복제 시 PK제약사항 제거 (EPIC 통합 머지) | 2026-01-26 | feature 브랜치를 develop에 통합하는 대규모 병합 PR |
| [#6814](https://github.com/CUBRID/cubrid/pull/6814) | CBRD-26277 | Minor bug fixes | 2026-02-02 | db_class 표기 오류·에러코드 오표기 수정 |
| [#6826](https://github.com/CUBRID/cubrid/pull/6826) | CBRD-26534 | truncate bug fix | 2026-02-09 | TRUNCATE가 RK(PK/UK) 기준으로 복제되도록 수정 |
| [#6908](https://github.com/CUBRID/cubrid/pull/6908) | CBRD-26589 | SBR 복제 버그 + checksumdb 버그 수정 | 2026-07-23 | REPLICATION=OFF에서도 SBR이 복제되던 버그, checksumdb 중복 복제 버그 |
| [#6934](https://github.com/CUBRID/cubrid/pull/6934) | CBRD-26623 | database.txt 멀티호스트 시 rkcheck 실행 에러 수정 | 2026-03-31 | multi-host 환경에서 rkcheck 실행 에러 수정 |
| [#6939](https://github.com/CUBRID/cubrid/pull/6939) | CBRD-26607 | rkcheck 유틸리티에서 view class 예외 처리 | 2026-04-01 | VIEW(VCLASS)를 RK 검사 대상에서 제외 |
| [#6943](https://github.com/CUBRID/cubrid/pull/6943) | CBRD-26622 | CREATE TABLE ... LIKE ... 복제 옵션 누락 수정 | 2026-04-01 | LIKE 생성 시 원본의 복제 옵션 상속 안 되던 버그 수정 |
| [#7612](https://github.com/CUBRID/cubrid/pull/7612) | CBRD-27073 | Fix log applier error message buffer overflow | 2026-08-20 | 로그 어플라이어 에러 메시지 버퍼 오버플로우 수정 |
| [#7697](https://github.com/CUBRID/cubrid/pull/7697) | CBRD-27228 | Fix repl class interrupt assert | 2026-08-20 | 인터럽트로 인한 KILL QUERY 무시 버그(코어 원인) 근본 수정 |

---

## 기능 진화 요약

이 히스토리는 대략 다섯 단계로 흘러간다.

1. **REPLICATION 옵션 도입** (#6394, #6454) — 먼저 문법만 추가하고(#6394), 이어서 클래스 플래그로 저장·조회하는 기능을 붙였다(#6454). 하위 버전 호환을 위해 "복제 대상"을 양성 플래그가 아니라 "복제 제외만 표시하는 음성 플래그(NO_REPLICATION)"로 설계한 것이 이 단계의 핵심 결정이다.
2. **RK(Replication Key) 제약 확립** (#6467, #6477, #6505, #6552, #6618, #6637) — 옵션이 실제 DML 복제에 반영되도록 연결하면서 "PK뿐 아니라 NOT NULL UNIQUE도 복제 키가 될 수 있다"는 RK 개념이 생겼다(#6467). 이후 HA 모드에서 RK 없는 복제 테이블 생성 금지(#6477), FK 참조 조합 제약(#6505), 파티션 상속(#6552), RK 삭제 제약(#6618), 멀티 ALTER TABLE 허용을 위한 검사 위치 재배치(#6637)로 제약 규칙이 점점 촘촘해졌다.
3. **유틸리티화** (#6570, #6658) — unloaddb/loaddb에 옵션을 실어 나르고(#6570), HA 기동 전에 제약 위반을 사전 검사하는 rkcheck 유틸리티를 새로 만들었다(#6658). rkcheck는 이후 여러 버그(#6934, #6939)를 낳는 근원이 된다.
4. **EPIC 마무리 및 통합** (#6739, #6796, #6798, #6814) — FK 검사 누락, 에러 메시지 오류 등 자잘한 버그를 정리하고(#6739, #6796, #6814), feature 브랜치를 develop에 통합하는 대규모 머지가 이뤄졌다(#6798).
5. **실전 배치 후 버그픽스 흐름** (#6826, #6908, #6934, #6939, #6943, #7612, #7697) — 기능이 실제로 쓰이기 시작하면서 TRUNCATE, SBR, checksumdb, CREATE...LIKE, 멀티호스트, VIEW 등 앞 단계에서 미처 다루지 못한 진입점들의 버그가 하나씩 드러나 수정됐다. 특히 #7697은 #6467에서 심어진 설계 결함(에러를 삼키는 bool 반환 함수)이 거의 1년 가까이 잠복해 있다가 KILL QUERY 무시라는 심각한 문제로 이어져 근본 수정된, 이 히스토리 전체에서 가장 늦게 갚은 "기술 부채" 사례다.

---

## #6394 — [CBRD-26246] CREATE TABLE 시 REPLICATION 옵션 추가

**병합**: 2025-09-14

### ① 목적
PK 제약사항 정책 변경(RK 도입)을 위한 첫 단계로, `CREATE TABLE`/`ALTER TABLE`에 `REPLICATION` 옵션 문법만 우선 추가한다. 실제 저장·핸들링은 다음 이슈(#6454)로 미룬, 순수 파서 단계 작업이다.

### ② 핵심 변경
- `csql_lexer.l`에 `replication` 키워드를 대소문자 구분 없이 인식하도록 추가.
- `parse_tree.h`에 `PT_TABLE_OPTION_REPLICATION` 옵션 타입 추가.
- `semantic_check.c`의 `pt_check_create_entity()`에서 REPLICATION 옵션이 중복 명시됐는지 검사.
- `execute_schema.c`에 옵션 없을 때 기본값 ON 처리 로직.
- 하위 버전 호환을 위해, 새 컬럼이 없는 옛 데이터를 복원했을 때 모두 "복제 대상"이 되도록 `NO_REPLICATION` 플래그 방식을 채택(복제 제외 테이블만 별도 표시).

### ③ 리뷰 논점
hornetmj가 `ALTER TABLE tbl;`처럼 REPLICATION 옵션을 아예 생략했을 때 사용자가 성공/실패 중 무엇으로 받아들여야 하는지, 문법을 하나로 제한하는 게 낫지 않겠냐고 질문했다. 저자는 옵션 생략 시 기존과 동일하게 문법 에러가 난다고 답했고, 최종적으로는 `ENCRYPT`, `COMMENT` 등 기존 다른 테이블 옵션들과 마찬가지로 `REPLICATION`, `REPLICATION ON`, `REPLICATION=ON` 세 가지 표기를 모두 허용하는 현재 구현을 그대로 유지하기로 합의했다.

### ④ 후속 연결
저장/조회는 #6454, DML 복제 반영은 #6467에서 이어진다.

---

## #6454 — [CBRD-26250] Replication option handling

**병합**: 2025-09-22

### ① 목적
`CREATE TABLE`/`ALTER TABLE`에서 입력받은 REPLICATION 옵션을 실제로 저장하고, `SHOW CREATE TABLE`이나 `db_class.is_replication_class`로 조회할 수 있게 한다.

### ② 핵심 변경
- `sm_set_class_flag()`로 클래스에 `SM_CLASSFLAG_NO_REPLICATION` 플래그 설정/해제.
- `object_printer.cpp`의 `describe_class()`에서 이 플래그를 보고 `SHOW CREATE TABLE` 출력 여부 결정.
- 새 에러 코드 `ER_REPLICATION_CONSTRAINT`(-1368) 추가 — HA 모드에서 복제 옵션을 OFF→ON으로 바꾸는 것은 금지.

### ③ 리뷰 논점
PR 본문(Remarks)에 설계 대안이 명시돼 있다. 원래는 켜진 상태를 직접 표시하는 `SM_CLASSFLAG_REPLICATION`(양성 플래그) 방식이 고려됐으나, 하위 버전 백업 데이터에는 이 플래그 자체가 없어 복원 시 전부 "복제 제외"가 되어버리는 문제 때문에 기각됐다. 그래서 정반대로 "복제 제외 테이블만 표시"하는 음성 플래그(`NO_REPLICATION`) 방식을 채택했고, 이 결정은 이후 모든 PR의 전제가 된다. 실제 리뷰 코멘트는 다수 존재하나(hgryoo, hornetmj 등 커밋별 지적) 코멘트 본문 자체는 이 데이터에는 비어 있다.

### ④ 후속 연결
HA 모드에서의 RK 필수 제약은 #6477, FK 조합 제약은 #6505에서 이어진다.

---

## #6467 — [CBRD-26251] Replication flag 가 설정된 클래스의 DML복제

**병합**: 2025-10-14

### ① 목적
클래스에 복제 플래그가 설정되어 있을 때(`REPLICATION_OFF == false`), 실제 INSERT/UPDATE/DELETE를 슬레이브로 복제하도록 만든다. 지금까지는 옵션이 저장만 됐지 실제 동작에는 영향이 없었다.

### ② 핵심 변경
- `heap_is_replication_class()`, `or_class_is_replication_on()` 추가.
- INSERT/DELETE 경로인 `locator_add_or_remove_index_internal()`, UPDATE 경로인 `locator_update_index()`의 복제 로그 생성 조건에 위 함수들을 결합.
- 슬레이브 측 `locator_repl_prepare_force()`에서 기존에는 PK만 찾던 것을, PK 또는 UK(NOT NULL UNIQUE)를 모두 btree에서 찾을 수 있도록 확장. 이 개념 확장을 반영해 함수명도 `btree_get_pkey_btid` → `btree_get_rkey_btid`로 바꿨다 — 여기서 "RK(Replication Key)"라는 용어가 처음 등장한다.

### ③ 리뷰 논점
저자가 PR 본문(Remarks)에서 스스로 기술 부채를 명시했다: 복제 로그 생성 조건으로 쓰이는 `need_replication`, `heap_is_replication_class()`, `!replicated` 세 조건식이 서로 비슷하지만 다른 목적으로 쓰이고 있어 리팩토링이 필요하다고 밝혔다. 다만 이 이슈에서는 "옵션에 따른 DDL/DML 동작 여부"가 우선이라 판단해 리팩토링은 보류했다. 이 판단이 나중에 부채로 돌아온다(④ 참고).

### ④ 후속 연결
여기서 도입된 `heap_is_replication_class()`가 **bool만 반환하는 구조**라는 점이, 약 10개월 뒤 #7697에서 "인터럽트(KILL QUERY)로 인한 조회 실패를 그냥 false로 뭉개버려 트랜잭션 취소가 무시된다"는 심각한 버그의 근본 원인으로 밝혀진다.

---

## #6477 — [CBRD-26270] Fix ha constraint

**병합**: 2025-10-21

### ① 목적
누락된 사용자 스펙 두 가지를 보완한다: (1) HA 모드에서 복제 키가 없는 복제 테이블은 생성 금지, (2) HA 모드에서 `ALTER TABLE`로 REPLICATION ON↔OFF 상호 전환 금지.

### ② 핵심 변경
- `CREATE TABLE` 시 `IS_CREATE_OPT_REPLICATION_ON && !HA_DISABLED && !has_replication_key_constraint(class_obj)` 조건이면 에러.
- `ALTER TABLE`에서 REPLICATION 옵션을 바꾸려 하면 HA 모드일 때 그 자체를 에러 처리.
- 네이밍 리팩토링: `SM_CLASSFLAG_REPLICATION_OFF` → `SM_CLASSFLAG_REPLICATION_DATA_OFF`(데이터 복제라는 의미를 강조), `IS_REPLICATION_ON_OPT` → `IS_CREATE_OPT_REPLICATION_ON`, `IS_REPLICATION_ON_NODE` → `IS_ALTER_OPT_REPLICATION_ON`("옵션 혹은 노드를 본다"는 코드적 의미에서 "생성 시/수정 시 옵션을 본다"는 기능적 의미로 전환).

### ③ 리뷰 논점
PR 본문에 "리뷰 과정에서 누락되었던 코멘트가 있어 반영되었다"는 언급이 있다 — 즉 이전 PR(#6454)에서 나온 네이밍 관련 피드백이 여기서 뒤늦게 실제 코드에 반영된 것이다. 리뷰 자체는 커밋별로 여러 라운드가 있었으나 코멘트 본문은 비공개.

### ④ 후속 연결
여기서 확립된 `has_replication_key_constraint()` 요구사항이 이후 rkcheck 유틸리티(#6658)가 검사하는 규칙의 기반이 된다.

---

## #6505 — [CBRD-26256] Support adding FK constraints on table creation

**병합**: 2025-11-03

### ① 목적
FK를 사용할 때 복제 옵션 조합에 제약을 건다. 허용: 참조 테이블(ON)←FK 테이블(ON/OFF 무관), 참조 테이블(OFF)←FK 테이블(OFF). 금지: 참조 테이블(OFF)인데 FK 테이블이 ON인 경우(참조 대상이 복제되지 않는데 참조하는 쪽만 복제되면 슬레이브에서 참조 무결성이 깨지기 때문).

### ② 핵심 변경
- `CREATE TABLE` 시 (1) HA 모드 여부, (2) RK 존재 여부, (3) FK 포함 시 참조 대상의 복제 여부까지 3단계 검증을 하나로 묶은 `check_ha_repl_constraint()` 함수로 리팩토링(3번이 이번에 새로 추가된 부분).
- `ALTER TABLE`에서 FK 수정 시 호출되는 `do_alter_one_clause_with_template()`에도 1, 3번 검증 추가.

### ③ 리뷰 논점
hornetmj가 승인 코멘트에 "구두로 전달드렸던 수정 요청사항이라 커멘트 남기고 승인합니다"라고 적었다 — 즉 GitHub 코멘트 스레드에 전부 기록되지 않고 구두(회의)로 조율된 부분이 실제로 존재했다는 뜻이며, 이 관행은 이후 PR들(#6637, #6908)에서도 반복된다.

### ④ 후속 연결
이 함수가 "참조 대상 테이블"만 검사하고 "FK를 포함하는 테이블 자신"은 검사하지 않는 누락이 있었는데, 이는 #6739에서 버그로 발견되어 수정된다.

---

## #6570 — [CBRD-26272] loaddb & unload 사용시 복제 옵션 출력 및 적용

**병합**: 2025-11-03

### ① 목적
`unloaddb` 유틸리티로 스키마를 내보낼 때 REPLICATION 옵션도 함께 출력하고, `loaddb`로 다시 불러올 때 이 옵션이 새 데이터베이스에 반영되게 한다.

### ② 핵심 변경
- `unload_schema.c`의 `emit_schema()`에 `REPLICATION={ON|OFF}` 출력 코드 추가(예: `CREATE CLASS ... REPLICATION=ON, ...`).
- `loaddb`는 별도 코드 없이 이 구문을 그대로 실행하면 되므로 추가 구현 불필요.
- 옵션 정보가 없는 이전 버전 덤프 파일을 로드할 경우 자동으로 복제 ON으로 등록(#6454에서 정한 "기본값은 복제 대상" 원칙과 일관).

### ③ 리뷰 논점
코멘트 스레드는 존재하나 반려된 접근이나 특기할 논쟁은 없다. 리뷰어 다수가 무난히 승인.

### ④ 후속 연결
없음.

---

## #6552 — [CBRD-26271] Partition 생성시 복제 옵션 상속 및 승격 시 컬럼 속성 상속

**병합**: 2025-12-14 (리뷰 시작은 10월 말, 약 1.5개월 소요)

### ① 목적
파티션 테이블에서 HA를 정상적으로 쓰려면 두 가지가 보장돼야 한다: (1) 파티션 생성 시 자식 테이블이 부모의 복제 옵션을 그대로 물려받아야 하고, (2) 파티션을 일반 테이블로 "승격(promote)"할 때 자식이 부모의 PK/NOT NULL UNIQUE 같은 컬럼 속성을 물려받아야 한다(기존에는 상속되지 않아 PK가 없는 복제 테이블이 만들어지는 버그가 있었다).

### ② 핵심 변경
- `do_create_entity()` → `do_create_partition()` 흐름에서 자식 클래스 생성 전에 부모 클래스의 복제 옵션을 조회해 자식에 플래그로 설정.
- `do_promote_partition()`에서 컬럼 속성을 복사하는 로직을 추가하고, 기존에 있던 "컬럼 속성 및 제약 초기화" 루틴을 제거.

### ③ 리뷰 논점
저자가 스스로 우려한 부분을 실증적으로 검증한 사례가 인상적이다. constraint를 복제하는 과정에서 부모·자식이 동일한 `btid`(B-tree ID)를 공유하게 되는데, 이것이 안전한지 두 가지 방법으로 직접 확인했다: (1) `SHOW TRACE`로 파티션 자식 테이블에 PK/UK를 걸었을 때 인덱스 스캔이 정상적으로 잡히는지 확인, (2) gdb로 `btree_delete_index()`에 브레이크포인트를 걸어, 파티션 승격 시점에는 호출되지 않고 승격 이후 만들어진 일반 테이블을 삭제할 때만 호출됨을 확인. 리뷰 라운드가 많았지만 코멘트 본문은 비공개.

### ④ 후속 연결
없음. 파티션 케이스는 이후 별도로 재논의되지 않는다.

---

## #6618 — [CBRD-26273] ALTER TABLE 로 복제 키 제거 시 제약사항 추가

**병합**: 2025-11-11

### ① 목적
HA 환경에서 `ALTER TABLE`로 복제 키(RK) 컬럼 또는 제약을 삭제하려 할 때 제약을 건다: 다른 복제 후보 키가 남아 있으면 삭제 허용(그 키로 계속 복제), 남아 있지 않으면 삭제 금지.

### ② 핵심 변경
- #6505에서 FK 검증용으로 만든 `check_ha_repl_fk_ref_all_replicated()`를, 호출 로직이 동일하다는 이유로 범용 `check_ha_repl_constraint()`로 대체.

### ③ 리뷰 논점
코멘트가 짧고 반려된 내용이 없다. #6505에서 만든 리팩토링(공통 검증 함수)이 곧바로 재사용성을 인정받은 사례다.

### ④ 후속 연결
이 검사가 호출되는 **위치**(DROP PRIMARY KEY 직후 즉시 검사)가 문제가 되어, 멀티 `ALTER TABLE`로 PK를 교체하는 시나리오를 막아버리는 부작용이 생긴다 → #6637에서 검사 위치를 옮겨 해결.

---

## #6637 — [CBRD-26274] 멀티 ALTER TABLE 을 이용한 PK 변경 허용

**병합**: 2025-12-02 (리뷰 약 3주)

### ① 목적
한 `ALTER TABLE` 문에 여러 clause를 나열해 PK를 통째로 교체하는 패턴(`DROP PRIMARY KEY, ADD PRIMARY KEY(...)`)이 기존엔 막혀 있었다. `DROP PRIMARY KEY`를 처리한 직후 바로 "RK가 있는지" 검사하는 코드가 실행되어, 아직 새 PK를 추가하기 전 상태에서 에러가 났기 때문이다.

### ② 핵심 변경
- HA 제약 검사 호출 위치를, 개별 clause를 처리하는 `do_alter_one_clause_with_template()`에서 모든 clause를 다 처리한 뒤 호출되는 상위 함수 `do_alter()`로 이동.

### ③ 리뷰 논점
저자가 PR 본문에 두 가지 설계 고민을 직접 남겼다는 점이 특징적이다.
1. "ALTER TABLE과 무관한 작업에도 매번 이 검사 루틴이 실행되게 되지만, ALTER TABLE 자체가 빈번한 호출은 아니라 괜찮을 것"이라는 판단이 **주간 회의**에서 나왔다고 명시.
2. `check_ha_repl_constraint()`를 호출하려면 매번 `vclass()` 조회가 함께 일어나는데, 이를 `check_ha_repl_constraint_with_name(char *entity_name)` 같은 함수로 한 번 더 감쌀지 고민된다며 리뷰어들에게 직접 의견을 구했다 — 설계 대안이 리뷰 과정에서 열린 채로 논의된 사례.
Codex(자동 리뷰봇)도 이 PR에 코멘트를 남겼다.

### ④ 후속 연결
이 검사 위치 이동이 이후 최종 아키텍처로 정착되어 별도 후속 수정은 없다.

---

## #6658 — [CBRD-26275] ha 실행 시 RK 제약 조건 확인

**병합**: 2026-01-22 (리뷰 약 6주, 이 문서에서 가장 코멘트가 많은 PR)

### ① 목적
HA 하트비트 기동(`cubrid hb start`) 시점에 RK/FK 제약 위반을 사전에 잡아내는 `rkcheck` 유틸리티(`cub_admin rkcheck`)를 신설한다. 위반이 있으면 HA 자체를 기동하지 않도록 막는다.

### ② 핵심 변경
- `util_cs.c`에 약 292줄 규모의 신규 로직: 파라미터 확인 → 에러 로그 오픈 → 클래스 목록 조회 → 클래스별 attribute 순회 → 제약 확인 → 위반 시 로깅.
- `util_service.c`에서 `hb start` 시 자동으로 rkcheck를 호출하도록 연결.
- `-r`(RK 위반만 출력)/`-f`(FK 위반만 출력) 옵션 지원.
- 위반 발견 시 3중으로 출력: 터미널 요약, `.err` 에러 로그, `.list` 상세 파일(위반 목록 + "HOW TO FIX" 해결 가이드).

### ③ 리뷰 논점
코멘트 스레드가 50개 이상으로 이 문서에서 가장 깊다. 특히 hornetmj가 "위에 resolve 처리 되지 않았으나 접혀있어서 보이지 않는 부분이 있습니다. 같이 확인 부탁드립니다"라고 지적한 점이 눈에 띈다 — GitHub UI에서 리뷰 코멘트가 collapse(접힘)되어 실제로 놓칠 뻔한 사례로, 리뷰 프로세스 자체의 함정을 보여준다. hgryoo, vimkim, beyondykk9, H2SU, hyahong, InChiJun 등 다수 리뷰어가 참여했다.

### ④ 후속 연결
이 유틸리티가 실전에 배치되자마자 세부 버그들이 드러났다: 멀티호스트 환경 실행 에러(#6934), VCLASS(뷰) 처리 누락(#6939). "새로 만든 유틸리티는 완성 직후 바로 실전 버그가 드러난다"는 전형적 패턴을 보여준다.

---

## #6739 — [CBRD-26277] RK 제거 시 제약사항 위반 버그 수정 및 리팩토링

**병합**: 2026-01-21

### ① 목적
EPIC(CBRD-26096) 전반에서 드러난 버그 수정과 마이너 리팩토링을 묶은 정리성 PR.

### ② 핵심 변경
- `check_ha_repl_constraint()`가 FK `ALTER` 시 "참조 대상 테이블"만 검사하고 "FK를 포함하는 테이블 자신"은 검사하지 않던 누락을 수정(#6505에서 놓친 케이스).
- `er_set()` 호출 위치 수정.

### ③ 리뷰 논점
정상 케이스는 "대상(참조되는) 테이블의 복제 옵션이 OFF, FK를 가진(참조하는) 테이블의 복제 옵션이 ON"일 때만 에러라는 규칙을 재확인·명문화했다. FK 제약의 "참조 방향"과 "옵션 조합"에 대한 이해가 여러 PR(#6505→#6739→#6796)에 걸쳐 점진적으로 다듬어진 것을 보여준다.

### ④ 후속 연결
이때 수정한 에러 메시지 자체가 다시 틀려 있어 #6796에서 재수정된다.

---

## #6796 — [CBRD-26277] Change error message

**병합**: 2026-01-26

### ① 목적
#6739와 같은 티켓 번호 아래, FK 관련 에러 메시지의 문구 자체가 잘못돼 있던 것을 수정한다.

### ② 핵심 변경
- FK 관련 에러가 "복제 옵션이 서로 다르면 에러"라고 안내하고 있었지만, 실제 규칙은 "참조 대상의 복제 옵션이 OFF인 경우만 에러"이므로 메시지 문구를 정정.
- HA 실행 관련 에러 메시지에서 다른 에러들과 prefix를 통일하기 위해 "replication"이라는 단어를 제거.

### ③ 리뷰 논점
순수 문구 수정으로 리뷰가 빠르게 승인됐다.

### ④ 후속 연결
없음.

---

## #6798 — [CBRD-26096] HA 복제 시 PK제약사항 제거 (EPIC 통합 머지)

**병합**: 2026-01-26 (#6796과 같은 날)

### ① 목적
티켓 번호상으로는 EPIC 자체(CBRD-26096)를 가리키지만, 실제 diff를 보면 REPLICATION 옵션 feature 브랜치를 develop 기준선에 맞춰 병합하면서, 그 사이 develop에 쌓여 있던 무관한 변경들(CI 설정, 브로커 대규모 리팩토링, PL 엔진 등 100개 이상 파일)까지 함께 들어간 **통합 성격의 머지 PR**이다. `reviews` 필드가 비어 있어(리뷰 자체가 없음), 개별 코드 리뷰 대상이 아니라 브랜치 동기화 절차였음을 알 수 있다.

### ② 핵심 변경
REPLICATION 관련 실질 변경은 이미 #6394~#6796에 담겨 있고, 이 PR 자체는 그 결과물을 포함한 대규모 병합 커밋이다.

### ③ 리뷰 논점
리뷰 코멘트 없음. 팀 프로세스상 이 시점에 feature 브랜치 산출물을 develop 기준으로 정리·병합하는 절차로 보인다.

### ④ 후속 연결
이후 버그 수정들(#6814, #6826, #6908 등)은 이 통합 이후의 develop 기준선을 바탕으로 이어진다.

---

## #6814 — [CBRD-26277] Minor bug fixes

**병합**: 2026-02-02

### ① 목적
사소한 버그 두 건 수정: `db_class` 조회 시 복제 옵션이 잘못 표기되는 문제, HA 모드에서 `ALTER TABLE`로 복제 옵션 변경을 시도할 때 엉뚱한 에러가 표기되는 문제.

### ② 핵심 변경
- `db_class` 조회 시 `is_replication_class` 플래그 조회 연산 수정.
- 에러 코드를 `ER_HA_REPLICATION_KEY_REQUIRED`(RK가 없다는 뜻)에서 `ER_HA_REPLICATION_OPTION_CHANGE_NOT_ALLOWED`(옵션 변경 자체가 금지라는 뜻)로 교체 — 실제 상황을 정확히 반영하는 에러코드로 바꾼 것.

### ③ 리뷰 논점
빠르게 다수 승인, 반려 없음.

### ④ 후속 연결
없음.

---

## #6826 — [CBRD-26534] truncate bug fix

**병합**: 2026-02-09

### ① 목적
NOT NULL UNIQUE만 있고 PK는 없는 복제 테이블에서, `TRUNCATE`가 슬레이브에 반영되지 않는 버그를 고친다.

### ② 핵심 변경
- `do_replicate_statement()`가 `PT_TRUNCATE`를 처리할 때 `truncate_need_repl_log()`를 호출해 복제 로그 생성 여부를 판단하는데, 이 함수가 "PK 존재 여부"만 확인하던 것을 "RK(PK 또는 NOT NULL UNIQUE) 존재 여부"로 확장.

### ③ 리뷰 논점
이 버그는 #6467에서 도입된 "PK뿐 아니라 UK도 복제 키가 될 수 있다"는 RK 개념이, 일반 DML 경로에는 반영됐지만 `TRUNCATE`라는 별도 진입점에는 누락돼 있던 전형적 사례다. 기능이 여러 진입점(개별 DML vs TRUNCATE 같은 특수 구문)에 걸쳐 있을 때 확장이 고르게 적용되지 않고 일부만 남는 패턴을 보여준다.

### ④ 후속 연결
없음. 단발 수정으로 마무리.

---

## #6908 — [CBRD-26589] SBR 로그 복제 버그 수정 및 checksumdb 버그 수정

**PR 오픈**: 2026년 3월 / **병합**: 2026-07-23 (리뷰 기간 약 4개월, 이 문서에서 가장 논의가 깊은 PR)

### ① 목적
성격이 다른 두 버그를 연관성이 있다는 이유로 한 PR에 묶었다.
1. `REPLICATION=OFF`인 테이블인데도 SBR(Statement-Based Replication, `USE_SBR` 힌트) 구문은 무조건 복제되던 버그.
2. `checksumdb` 유틸리티(마스터-슬레이브 데이터 무결성 비교 도구)가 자신의 체크섬 계산 결과 자체를 복제해버려, 실제로는 데이터가 달라도 항상 "일치"로 보고되던 버그.

### ② 핵심 변경
- `is_data_repl_log_enabled()` 신규 함수를 만들어 `do_execute_statement()`/`do_execute()`에서 SBR 복제 여부를 클래스의 복제 플래그로 판단.
- `DELETE ... FROM t1 JOIN t2 ...` 같은 다중 테이블 구문은, 단순히 FROM에 나열된 첫 테이블이 아니라 **실제 삭제/수정 대상 테이블**(`PT_SPEC_FLAG_UPDATE`/`PT_SPEC_FLAG_DELETE` 플래그가 붙은 spec)을 기준으로 판정하도록 설계를 발전시킴.
- `checksumdb`는 자신이 실행하는 모든 쿼리에 `USE_SBR` 힌트를 붙이고, 기존에 직접 호출하던 `chksum_set_repl_info_and_demote_table_lock()`을 제거하는 대신, `db_execute()` 앞뒤로 `db_set_suppress_repl_on_transaction(true/false)`를 감싸 "복제 로그는 남기되, 마스터에서 재실행할 때는 중복 로그를 억제"하는 방식으로 정리.

### ③ 리뷰 논점
이 PR은 논점이 가장 풍부하다.
- 초기엔 lock demote 코드를 아예 제거했었으나, **팀 공유회의**에서 demote 자체는 필요하다는 의견이 나와 원래 컨셉(복제 정보 생성 + demote를 모두 유지)으로 되돌렸다 — 회의 결정이 코드에 반영된 사례.
- vimkim이 dead code(호출부가 사라진 `chksum_set_repl_info_and_demote_table_lock` 선언만 남음), `static` 누락, `bool`/`int` 반환 타입 혼용을 지적하며 직접 diff까지 제공했고, 저자가 그대로 반영했다.
- "MAJOR" 지적: `heap_is_replication_class()`가 btree 인덱스 순회 루프 안에서 매번 호출되어 불필요한 heap scan이 반복된다는 것(같은 `class_oid`에 대해서는 결과가 항상 동일하므로 루프 밖으로 빼야 한다는 제안).
- 가장 중요한 후반 논점: **derived updatable VCLASS**(예: `UNION ALL` 뷰)를 통해 UPDATE/DELETE할 때, 최상위 `entity_name`만 보고 복제 여부를 판단하면 실제 수정 대상(`flat_entity_list` 안의 진짜 테이블)을 놓쳐 복제 로그가 아예 생성되지 않는 치명적 버그가 발견됐다. 리뷰어가 gdb로 직접 재현해(`entity_name=NULL`, `flat_entity_list=dba.t1`인데 `is_data_repl_log_enabled=0`) 증명했고, 저자는 `PT_SPEC_FLAG_UPDATE`/`DELETE`가 붙은 spec을 순회하는 `spec_has_replication_class()` 방식으로 재수정한 뒤 동일하게 gdb로 재검증(콜스택 첨부)했다.
- `checksumdb`의 스키마 정의 테이블(`db_ha_checksum_schema`) INSERT에는 `USE_SBR` 힌트가 빠져 있다는 지적도 있었으나, 의도적인지 여부는 명확히 결론나지 않은 채로 남았다.

### ④ 후속 연결
이 PR이 다룬 `heap_is_replication_class()`의 "에러를 삼키는 bool 반환" 구조는, 이후 #7697에서 "KILL QUERY 무시" 크래시로 이어져 근본적으로 재설계된다.

---

## #6934 — [CBRD-26623] database.txt의 db-host에 여러 노드가 입력되어있을 시 rkcheck 유틸리티 실행 에러

**병합**: 2026-03-31

### ① 목적
`database.txt`의 `db-host`에 `master:slave`처럼 여러 호스트가 나열된 환경에서 `rkcheck` 유틸리티를 실행하면 "hostname이 명시되어야 한다"는 에러로 실패하는 버그를 수정한다.

### ② 핵심 변경
- `db_restart()` → `boot_restart_client()` 호출 전에, 데이터베이스 이름에 `@localhost`를 붙여서 explicit-host 코드 경로를 타도록 함(`util_cs.c`, 15줄 추가).

### ③ 리뷰 논점
vimkim이 매우 상세하게(심각도 태깅까지 포함) 리뷰했다.
- **MAJOR**: 버퍼(`CUB_MAXHOSTNAMELEN`=256)가 최대 길이 DB 이름(255자)+`"@localhost"`(10자)를 모두 담기엔 부족할 수 있다는 지적.
- **MINOR**: `check_database_name` 실패 시 `er_set()`이 호출되지 않아 `db_error_string()`이 빈 문자열을 반환한다는 지적.
- 확장 질문: "다른 admin 유틸리티(`checkdb`, `spacedb` 등 13개)도 같은 문제가 있는 것 아니냐"는 지적에는 "이 PR의 범위 밖"이라는 데 서로 동의했다.
- 저자는 불필요한 에러 출력 코드만 삭제하고, 버퍼 크기 이슈는 TODO로 남긴 채 "마이너한 리뷰라 바로 머지하겠다"고 처리했다 — 완벽한 해결보다 범위를 좁혀 빠르게 머지하는 실용적 판단.
- rkcheck의 위반 목록 파일명도 이때 호스트명을 포함하도록 변경됐다(`demodb@localhost_rkcheck_*.list`) — 여러 노드에 대해 rkcheck를 실행할 수 있으므로 로그 파일을 호스트별로 명확히 구분하기 위함.

### ④ 후속 연결
없음. 다만 버퍼 크기 이슈는 TODO로 남아 이 히스토리 시점까지 미해결 상태다.

---

## #6939 — [CBRD-26607] rkcheck 유틸리티에서 제약사항 확인할 때 view class 예외 처리

**병합**: 2026-04-01

### ① 목적
`rkcheck`가 VIEW(VCLASS)까지 RK 제약 검사 대상으로 삼아버려서, 애초에 PK/제약을 가질 수 없는 뷰 때문에 HA 기동 자체가 막히는 버그를 고친다.

### ② 핵심 변경
- `check_repl_constraint_violations()` 루프의 skip 조건에 `db_is_vclass(c->op)`를 추가해, VCLASS는 애초에 검사 대상에서 제외.

### ③ 리뷰 논점
vimkim이 `db_is_vclass()`가 "1(VCLASS)/0(아님)/음수(에러)"의 3상태를 반환하는데, C에서는 음수도 참(truthy)으로 평가되므로 "에러가 나면 VCLASS로 오판되어 그냥 skip된다"는 문제를 지적했다(코드베이스 내 `db_is_vclass` 호출 25곳 중 18곳이 이미 `> 0` 명시 비교를 쓰고 있다는 근거까지 제시하며 `CHANGES_REQUESTED`). 저자는 에러 처리 로직을 추가하고 위반 개수 변수를 파라미터로 주고받는 형태로 재수정했다. 이 PR부터 리뷰 코멘트에 "3개 병렬 서브에이전트(로직+LSP, C++ 안전성, PR 컨텍스트)를 투입한 자동 리뷰 보고서" 형식이 처음 등장하는데, 이 시점부터 팀이 AI 보조 코드 리뷰를 정식 프로세스로 쓰기 시작한 것으로 보인다.

### ④ 후속 연결
없음.

---

## #6943 — [CBRD-26622] CREATE TABLE ... LIKE ... 복제 옵션 누락 수정

**병합**: 2026-04-01 (#6939과 같은 날)

### ① 목적
`CREATE TABLE ... LIKE ...`로 원본과 동일한 스키마의 새 테이블을 만들 때, 원본의 REPLICATION 옵션이 무시되고 항상 ON으로 생성되는 버그를 고친다.

### ② 핵심 변경
- `do_create_entity()`에서 `create_like` 분기일 때는 원본 테이블(`source_class`)의 `SM_CLASSFLAG_DATA_REPLICATION_OFF` 플래그를 직접 읽어와 그대로 적용하고, 일반 생성일 때는 기존처럼 쿼리문에 명시된 옵션(또는 기본값)을 쓰도록 분기 추가.

### ③ 리뷰 논점
greptile(자동 리뷰봇)이 이전 커밋에서 "원본 클래스를 다시 `sm_find_class()`로 조회하면 NULL 역참조 위험이 있다"고 지적했고, 저자는 이미 확보돼 있던 `source_class->flags`에 직접 접근하는 방식으로 즉시 반영했다. 또한 REPLICATION 옵션과 LIKE를 동시에 명시하면 에러라는 규칙도 이때 PR 본문(Remarks)에서 확정됐다.

### ④ 후속 연결
없음.

---

## #7612 — [CBRD-27073] Fix log applier error message buffer overflow

**병합**: 2026-08-20

### ① 목적
RK 기능과 직접적인 로직 관계는 약하지만, 복제 로그 적용기(log applier)가 에러 메시지를 조립하는 경로에서 PK 값이 큰 경우 버퍼 오버플로우가 발생할 수 있는 문제를 고친다.

### ② 핵심 변경
- `log_applier.c`에서 `sprintf` → `snprintf`로 교체.
- 그래도 PK 값이 길면 메시지 자체가 잘려버릴 수 있어, 클래스명과 PK 값을 각각 16바이트까지만 출력하고 나머지는 `...`으로 표시하는 방식을 채택.

### ③ 리뷰 논점
저자가 PR 본문(Remarks)에 스스로 한계를 명시했다: "16글자가 아닌 16바이트라 한글의 경우 충분히 출력되지 않을 수 있다"고 인지하면서도, "코드의 수행 빈도 대비 작업 코드가 길어져" 다국어(멀티바이트) 대응까지는 반영하지 않기로 판단했다 — 완벽한 해법보다 실용적 트레이드오프를 택한 사례.

### ④ 후속 연결
없음.

---

## #7697 — [CBRD-27228] Fix repl class interrupt assert

**병합**: 2026-08-20 (#7612와 같은 날)

### ① 목적
shell debug 테스트 도중 발생하는 서버 코어(크래시)를 근본적으로 해결한다. 근본 원인은 #6467에서 도입된 `heap_is_replication_class()`가 **bool만 반환**하는 구조라서, `pgbuf_fix()`가 인터럽트(예: `KILL QUERY`)로 실패했을 때 이를 호출자에게 알리지 못하고 그냥 `false`(복제 대상 아님)로 처리해버리는 데 있었다. 이전에도 한 차례 "`ER_INTERRUPTED`일 때만 `assert`를 통과시키는" 방식으로 서버 abort는 막았었지만, 그건 근본 해결이 아니라 증상 완화였을 뿐 `KILL QUERY` 자체가 무시되는 문제는 그대로 남아 있었다.

### ② 핵심 변경
- 함수를 `heap_is_replication_class()` → `heap_get_class_replication()`으로 변경, 반환 타입을 `bool`에서 `int`(에러 코드)로 바꾸고 복제 여부는 out-parameter(`is_replication`)로 전달.
- 호출부 `locator_add_or_remove_index_internal()`에서 `error_code != NO_ERROR`이면 `goto error`로 실제 인터럽트를 트랜잭션에 전파하도록 수정.

### ③ 리뷰 논점
H2SU가 실측 데이터로 문제의 심각성을 직접 증명했다. PK와 인덱스 4개짜리 테이블에 `INSERT`를 실행하며 다른 세션에서 `KILL QUERY`를 보냈더니, "1 transaction killed"라는 응답에도 불구하고 실제로는 트랜잭션이 끝까지 실행되어 **커밋**돼버림을 확인했다. `KILL QUERY`는 인터럽트를 2회 전달하므로 1회만 유실되면 나머지로 취소가 되지만, 인덱스가 많을수록(=`heap_is_replication_class` 호출 기회가 많을수록) 2회 모두 유실될 확률이 올라간다는 것을 HA on/off·인덱스 유무 조합의 실측 표(예: 14회 시행 중 8회 유실)로 입증했다. 또한 이전 수정이 남긴 주석의 두 가지 전제("`pgbuf_fix`는 이후 페이지 fix를 모두 거부한다", "어차피 트랜잭션은 롤백된다")가 모두 사실과 다르다고 지적했다(`clear=true`라 다음 fix는 성공하고, 에러가 전파되지 않으므로 롤백도 보장되지 않는다) — 잘못된 가정이 담긴 주석이 코드보다 오래 살아남았던 사례.

### ④ 후속 연결
이 PR은 #6467에서 심어진 설계(에러를 삼키는 bool 반환 함수)의 결함이 거의 1년 가까이 잠복해 있다가, `KILL QUERY` 무시라는 심각한 문제로 표면화되어 마침내 근본 수정된 사례다. 이 히스토리 전체에서 가장 늦게 갚은 기술 부채라 할 수 있다.
