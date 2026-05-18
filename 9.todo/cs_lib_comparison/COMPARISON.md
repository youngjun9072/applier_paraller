# cs_lib (`feature/parallel_applylogdb`) vs PoC (`feature/parallel_applylogdb_poc`) 비교

> 주제: **transaction id (tran_index) 부여 방식**
> 기준 코드: `/home/youngjun/cubrid` 의 `feature/parallel_applylogdb` 현재 HEAD (`1c3610d20`) 와 PoC 브랜치 `feature/parallel_applylogdb_poc`.
> 작성일: 2026-05-13
> 재작성 메모: 직전 버전은 POC 초기 커밋 `bfabd3c3f` 의 함수 시그니처(`boot_restart_client_sub(int sub_index, bool new_transaction)`)와 그 위의 추론(`g_main_tran_info` 공유 모드 등)을 그대로 인용했음. 그 시점에는 사실이었으나 **이후 두 차례 리팩터로 시그니처와 동작이 모두 바뀌었으므로** 현 HEAD 기준으로 다시 작성하고, 과거 분석이 어디까지 유효했는지 시간순으로 명시한다.

## 0. 시그니처 변천사 (왜 이전 분석이 어긋났는지)

상대 브랜치의 `boot_restart_client_sub` 는 세 단계로 모양이 바뀌었다.

| 커밋 | 시그니처 | 핵심 |
|---|---|---|
| `bfabd3c3f` [CBRD-26484][POC] | `int boot_restart_client_sub(int sub_index, bool new_transaction)` | sub 측에서 `sub_index`/`new_transaction` 을 직접 받음. `new_transaction=false` 이면 `g_main_tran_info` 에 캐시된 main 의 tran 정보를 그대로 써서 **공유 tran_index 모드** 진입. (필자의 이전 분석은 이 시점 기준이었다.) |
| `a615224c0` add db_restart_sub(), db_shutdown_sub() | `int boot_restart_client_sub(BOOT_CLIENT_CREDENTIAL *, bool share_tran_id)` | sub_index 처리(프로그램 이름 합성, credential 복사)는 새 wrapper `db_restart_sub(int sub_index)` 로 이동. boot 레이어는 credential 포인터만 받게 됨. |
| `33304dcec` remove db_share_same_transaction_mode variable (**현재 HEAD에 포함**) | `int boot_restart_client_sub(BOOT_CLIENT_CREDENTIAL * client_credential)` | `share_tran_id` 파라미터·`db_share_same_transaction_mode` 전역·`g_main_tran_info` 공유 모드 코드 경로가 전부 제거됨. **남은 경로는 "독립 tran_index" 한 가지뿐.** |
| `17a661256` disable MULTI_CONN_TO_A_SERVER (현재 HEAD에 포함) | (시그니처 변경 없음) | `CMakeLists.txt:596` 의 `add_definitions(-DMULTI_CONN_TO_A_SERVER)` 가 주석 처리됨. 이 기능군 전체가 **빌드 단계에서 꺼져 있음**. |

따라서 현 HEAD 기준 결론은 이전 분석과 두 가지 점에서 다르다.

- "두 모드(독립/공유 tran_index)를 런타임에 선택" 이라는 서술은 **더 이상 코드와 일치하지 않는다**. 공유 모드는 코드와 함께 제거됨.
- 게다가 `MULTI_CONN_TO_A_SERVER` 가 꺼져 있어서, 남은 독립 모드 경로조차 현재 빌드에는 포함되지 않는다.

## 1. 현재 HEAD 기준 실제 구조

### 1.1 함수 시그니처 (코드 인용)

- `src/transaction/boot_cl.h:69` — `extern int boot_restart_client_sub (BOOT_CLIENT_CREDENTIAL * client_credential);`
- `src/transaction/boot_cl.h:70` — `extern void boot_finalize_client_sub ();`
- `src/transaction/boot_cl.c:1348` — `boot_restart_client_sub (BOOT_CLIENT_CREDENTIAL * client_credential)`
- `src/transaction/boot_cl.c:1554` — `boot_finalize_client_sub ()`
- 두 심볼 모두 `#if defined(CS_MODE) && defined(MULTI_CONN_TO_A_SERVER)` 가드 안에 있음 (`boot_cl.c:1345`, `boot_cl.c:1597`).

### 1.2 sub 클라이언트 부팅 흐름

`boot_restart_client_sub` 본체에서 실제로 일어나는 일 (boot_cl.c:1348 이하):

1. `BOOT_IS_CLIENT_RESTARTED()` 면 `boot_shutdown_client(true)` 로 정리 후 진행.
2. `er_clear()` → READ_ONLY_MODE/READ_ONLY 클라이언트 타입이면 `db_disable_modification()`.
3. `net_client_sub_init()` — sub 전용 네트워크 초기화. 실패 시 즉시 리턴.
4. `ws_init(true)` — workspace 를 sub 모드로 초기화.
5. `tran_isolation = TRAN_DEFAULT_ISOLATION_LEVEL ()`, `tran_lock_wait_msecs = TRAN_LOCK_INFINITE_WAIT` 로 고정.
6. `boot_register_client(client_credential, ...)` 호출 → **항상 새 tran_index 등록**. (NULL_TRAN_INDEX 면 에러로 점프)
   - 클라→서버 사슬: `boot_cl.c:1430-1431` `boot_register_client(...)` → RPC → `boot_sr.c:3141` `xboot_register_client(...)` → `boot_sr.c:3217-3219` `logtb_assign_tran_index(thread_p, NULL_TRANID, TRAN_ACTIVE, client_credential, ...)`.
   - **이 시점까지는 “증가”가 일어나지 않는다.** `xboot_register_client` 와 `logtb_assign_tran_index` 는 위임 + 임계영역(`TR_TABLE_CS_ENTER/EXIT`) 만 담당.
   - 진짜 발급은 한 단계 더 안쪽: `logtb_assign_tran_index` (`log_tran_table.c:800-830`) → `logtb_allocate_tran_index` (`log_tran_table.c:927-1023`).
     - `logtb_allocate_tran_index` 가 `log_Gl.trantable.all_tdes[]` 를 `hint_free_index` 부터 라운드로빈 스캔해 `trid == NULL_TRANID` 인 슬롯을 찾는다 (`log_tran_table.c:970-981`).
     - 슬롯 확보 후 `log_Gl.trantable.hint_free_index = (tran_index + 1) % NUM_TOTAL_TRAN_INDICES` 로 다음 검색 시작점을 갱신하고 (`log_tran_table.c:985`), `logtb_increment_number_of_assigned_tran_indices()` 로 할당 카운터를 올린다 (`log_tran_table.c:987`).
     - 인자 `trid == NULL_TRANID` 이므로 `logtb_get_new_tran_id(thread_p, tdes)` 호출 (`log_tran_table.c:1000-1004`).
   - **새 TRANID 의 실제 “증가”는 `logtb_get_new_tran_id` (`log_tran_table.c:1745`) 안에서 일어난다.**
     - `HAVE_ATOMIC_BUILTINS` 빌드: `next_trid = trid + 1` 후 `ATOMIC_CAS_32 (&log_Gl.hdr.next_trid, trid, next_trid)` 루프 (`log_tran_table.c:1752-1766`). 오버플로(`next_trid < 0`) 시 `LOG_SYSTEM_TRANID + 1` 로 되감음.
     - 그 외 빌드: `TR_TABLE_CS` 보호 하에 단순 `tdes->trid = log_Gl.hdr.next_trid++` (`log_tran_table.c:1773-1786`).
   - 따라서 두 개의 “ID” 가 분리돼 있다:
     - `tran_index` — 트랜잭션 디스크립터 테이블 슬롯 인덱스. 재사용 가능. (`logtb_allocate_tran_index` 가 잡음)
     - `trid` (TRANID) — `log_Gl.hdr.next_trid` 전역을 모노토닉 +1 하여 발급되는 진짜 트랜잭션 식별자. (`logtb_get_new_tran_id` 가 잡음)
   - 클라이언트가 접속할 때 “새 트랜잭션 ID 가 부여된다” 의 의미는 이 두 가지가 한 사이클에 함께 일어난다는 것. `boot_register_client` 의 반환값으로 클라이언트에 노출되는 건 `tran_index` 뿐이고, TRANID 는 서버 측 `tdes->trid` 에 박혀 사용된다.
   - 즉 현 HEAD 의 sub 클라이언트는 부팅마다 서버에 자기 자신의 트랜잭션을 새로 등록(슬롯 할당 + 새 TRANID 발급)하며, 이전 버전에 있던 "main tran 을 공유" 우회 경로는 존재하지 않는다.
7. `boot_client(tran_index, ...)` 로 클라이언트 모듈 활성화 — 위에서 받은 새 tran_index 를 sub 측 thread-local 상태에 설치.
8. `sm_init(..., true)` 로 schema manager 를 sub 모드로 초기화, `au_init()`/`au_start()`.
9. `g_db_restart_client_sub_mutex` (boot_cl.c:1346) 를 잡고 `db_find_or_create_session(...)` 호출. 코멘트에 따르면 “시스템 파라미터 전역에 대한 thread-safe 처리가 끝나기 전까지 동시성을 막기 위한 잠금”.
10. `tran_commit(false)` 후 `reset_isolation_and_wait_times()`.

즉 현 HEAD의 sub 부팅은 항상 **(a) 별도 네트워크 sub 채널 + (b) sub 모드 workspace + (c) 서버에 새 tran_index 등록 + (d) session 생성** 이라는 단일 시나리오만 따른다.

### 1.3 main↔sub 사이의 상태 공유

이전 버전에서 `g_main_tran_info` 가 했던 역할(메인 tran 정보 캐시) 은 제거됐다. 다만 다음 두 가지는 남아 있다.

- `src/compat/db_admin.c:135` — `static BOOT_CLIENT_CREDENTIAL gv_client_credential;` (POC 시점에는 boot_cl.c 에 있었고, 리팩터 과정에서 이 파일로 이동).
- `src/compat/db_admin.c:137-138` — `static std::atomic<bool> g_ready_to_sub = false;` (sub 진입 게이트).

채워지는 시점: main `db_restart` 가 `boot_restart_client` 성공 직후 (`db_admin.c:977-980`)

```c
#if defined(CS_MODE) && defined(MULTI_CONN_TO_A_SERVER)
  gv_client_credential = client_credential;
  (void) g_ready_to_sub.store (true, std::memory_order_release);
#endif
```

소비되는 시점: `db_restart_sub(int sub_index)` (`db_admin.c:994` 이하)

```c
if (g_ready_to_sub.load (std::memory_order_acquire) == false)
  return ER_FAILED;

snprintf (program_name, sizeof (program_name), "%s(%d)",
          gv_client_credential.get_program_name (), sub_index + 1);
client_credential = gv_client_credential;
client_credential.program_name = program_name;

error = au_login (client_credential.get_db_user (), client_credential.get_db_password (), false);
...
error = boot_restart_client_sub (&client_credential);
```

요약: `sub_index` 의 의미는 “마스터에서 sub 세션을 구분하기 위한 `program_name` suffix 용 일련번호” 그 이상도 이하도 아니다. tran_index 부여 자체는 `boot_register_client` 가 새로 발급하므로 sub_index 와 직접 연결되지 않는다.

### 1.4 종료 경로

- `db_admin.c:1113` — `db_shutdown_sub()`: `db_end_session()` → `boot_finalize_client_sub()` → `au_ctx_destructor()` 순.
- `boot_cl.c:1554` — `boot_finalize_client_sub()`: `net_client_sub_final()` → `tran_free_savepoint_list()` → `au_final()` → `sm_final()` → `ws_final(true)` → `boot_client(NULL_TRAN_INDEX, ...)` → `boot_Server_credential` 의 동적 문자열 해제. (`tr_final()`, `es_final()`, `tp_final()`, `locator_free_areas()`, `sysprm_final()`, `perfmon_finalize()`, `area_final()`, `msgcat_final()`, `er_final()`, `lang_final()`, `tz_unload()` 는 의도적으로 호출되지 않고 주석 처리됨 — main 과 공유되는 프로세스 전역 자원이라는 뜻.)

### 1.5 빌드 가드 상태

`CMakeLists.txt:596`:

```cmake
#add_definitions(-DMULTI_CONN_TO_A_SERVER)
```

즉 현재 HEAD 빌드에는 `boot_restart_client_sub` / `boot_finalize_client_sub` / `db_restart_sub` / `db_shutdown_sub` 가 **링크되지 않는다**. 동일 커밋(`17a661256`) 에서 `src/object/transform.h` 의 `MULTITHREADED_MODE` 가드도 정리됐다.

## 2. PoC 와의 비교

`log_applier.c` / `log_applier.h` 자체는 두 브랜치가 동일하다 (worker dispatch / queue / retire 로직 공유). 차이는 sub 클라이언트 부팅 인프라에 한정된다.

### 2.1 PoC 측 접근

PoC 의 `04.multi-connection-client` ~ `08.isolate-worker-state` 단계 (3.dev_log 참조) 는 다음 방향으로 구성되어 있다.

- `MULTI_CONN_TO_A_SERVER` 를 **켠 상태**로 사용.
- worker 마다 multi-connection 세션을 직접 띄우고, 그 결과로 worker 별로 **독립 tran_index** 가 자연스럽게 잡힘.
- TLS 도입(`08`, `13`, `15` 단계) 으로 client 전역의 worker 간 격리 범위를 점진적으로 넓힘.

### 2.2 cs_lib HEAD 측 접근

- `boot_restart_client_sub(BOOT_CLIENT_CREDENTIAL *)` 단일 진입점 + `db_restart_sub(int sub_index)` wrapper 로 캡슐화.
- sub 마다 항상 `boot_register_client` 로 **독립 tran_index** 등록 — 모드 선택지 없음.
- 단, 현 HEAD 에서는 빌드 단계에서 매크로가 꺼져 있어 위 경로가 활성화되지 않는다.

### 2.3 두 접근의 실질 차이

| 항목 | PoC | cs_lib HEAD |
|---|---|---|
| sub 측 tran_index 부여 | worker 가 직접 multi-conn 으로 새 세션 → 새 tran_index | wrapper(`db_restart_sub`) 가 credential 합성 후 `boot_restart_client_sub` → `boot_register_client` 새 tran_index |
| 공유 tran_index 모드 | 없음 | 없음 (`33304dcec` 에서 제거됨) |
| `MULTI_CONN_TO_A_SERVER` | 활성 | **비활성 (`17a661256`)** |
| main 자격 증명 캐시 | 없음 (worker 가 자체 connect 경로 사용) | `gv_client_credential` + `g_ready_to_sub` (`db_admin.c:134-138`) |
| sub 진입점 분리 | 없음 (apply worker 가 client API 직접 호출) | `db_restart_sub` / `db_shutdown_sub` 라는 명시적 외부 API (`dbi.h:77`, `dbi.h:97`) |
| session 생성 동시성 보호 | 해당 없음 | `g_db_restart_client_sub_mutex` 로 `db_find_or_create_session` 직렬화 (`boot_cl.c:1346,1494-1496`) |

본질적으로는 **양쪽 다 “worker 마다 독립 tran_index” 로 수렴**하며, 차이는 그 경로를 어디서 어떻게 만들어 주느냐다. 이전 분석이 강조했던 "공유 tran_index 모드" 라는 제3의 모드는 현 HEAD에 존재하지 않는다.

## 3. 다음 액션 권장 (수정판)

- “공유 tran_index 모드를 PoC 에 도입할지 결정” 항목은 **드롭**. 상대 브랜치도 그 옵션을 버렸으므로 더 이상 의사결정 대상이 아님.
- 대신 결정해야 할 것: PoC 의 worker-자체 multi-conn 방식을 유지할지, 아니면 cs_lib 측처럼 **`db_restart_sub(int sub_index)` 라는 외부 API 형태로 sub 부팅을 캡슐화**할지 (관심사 분리, 종료 경로의 “process-shared 자원은 건드리지 않는다”는 정책을 명시적으로 가져갈 수 있다는 장점).
- `MULTI_CONN_TO_A_SERVER` 가 cs_lib HEAD 에서 꺼져 있다는 사실은 PoC 입장에서 중요한 신호: 상대 측이 이 매크로 의존을 줄이는 방향으로 움직이는 중이므로, PoC 가 매크로를 켠 상태에서만 의미를 갖는다면 **장기적으로 정합성 비용**이 발생할 수 있다.
- session 동시성 보호(`g_db_restart_client_sub_mutex`) 가 cs_lib 측에 추가됐다는 점은, 같은 종류의 race 가 PoC 의 worker 동시 startup 에도 잠재한다는 의미. PoC `06.fix-session-isolation` / `16.guard-client-globals` 가 다룬 영역과 겹치므로 교차 점검 가치 있음.

## 부록 A. 이전 버전(잘못된 분석) 의 해당 서술과 대응

| 이전 서술 | 현재 코드 상태 |
|---|---|
| “`boot_restart_client_sub(int sub_index, bool new_transaction)` 가 두 모드를 런타임에 선택” | 시그니처는 `(BOOT_CLIENT_CREDENTIAL *)`. 모드 선택 자체가 제거됨. |
| “`g_main_tran_info` 가 main tran 정보를 캐시해 sub 가 공유 모드에서 재사용” | `g_main_tran_info` 는 boot_cl.c 에서 제거됨 (33304dcec). |
| “디버그 빌드에서 `is_multi_tran` static 으로 모드 일관성 강제” | 해당 가드 코드도 함께 제거됨. |
| “`program_name(sub_index+1)` 합성과 `gv_client_credential` 캡처는 boot 레이어에서 수행” | 합성은 `db_admin.c:db_restart_sub` 로 이동, `gv_client_credential` 도 `db_admin.c` 로 이동. boot 레이어는 credential 포인터만 받음. |

이전 서술의 출처는 모두 POC 초기 커밋 `bfabd3c3f` 의 코드였고, 그 시점에서는 사실이었다. 다만 그 사실이 더 이상 HEAD에 유지되지 않는다는 점을 반영하지 못한 채 “현 상태” 처럼 단정한 것이 직전 문서의 결함이었다.
