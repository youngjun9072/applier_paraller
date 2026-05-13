# cs_lib (`feature/parallel_applylogdb`) vs PoC (`feature/parallel_applylogdb_poc`) 비교

> 주제: **transaction id (tran_index) 부여 방식**
> 기준 커밋: mine `7cf20e2d6` · other `1c3610d20` · merge-base `948cb3a58`
> 작성일: 2026-05-13

## 결론 요약

- 두 브랜치 모두 develop으로부터 분기된 별도의 병렬 applylogdb 작업이지만, **`log_applier.c`/`log_applier.h` 자체는 두 브랜치가 동일**하다. 즉 worker dispatch / queue / retire 로직은 같다.
- 차이는 거의 전부 **하위 client 인프라(boot/connection/object)** 에서 발생한다. 핵심은 상대 브랜치(`feature/parallel_applylogdb`)의 `bfabd3c3f [CBRD-26484][POC] Support for parallel execution of applylogdb` 커밋으로, **worker(sub client)에게 어떤 tran_index 를 부여할지 명시적으로 선택하는 부팅 경로**를 새로 만든다.
- 내 PoC는 worker마다 multi-connection 세션을 띄워 implicit 하게 새 tran_index를 받게 한 반면, 상대 측은 `new_transaction` 플래그로 **(a) sub마다 독립 tran_index** 또는 **(b) main의 tran_index 공유** 두 모드를 런타임에 고를 수 있게 한다. 내 PoC에는 이 "shared tran_index" 모드 자체가 없다.

## 상대 브랜치에만 있는 코드 (transaction id 관점)

### 1. `boot_restart_client_sub` / `boot_finalize_client_sub` 신규 추가

- **위치**: `src/transaction/boot_cl.c` (대규모 추가, +321 라인), 헤더는 `boot_cl.h`.
- **요지**: sub client(= worker 클라이언트)를 위한 별도 진입점.  `new_transaction` 인자로 **독립 tran_index 등록** vs **메인 tran_index 공유**를 선택.
- **코드 발췌**:
  ```c
  #if defined(CS_MODE) && defined(MULTI_CONN_TO_A_SERVER)
  int
  boot_restart_client_sub (int sub_index, bool new_transaction)
  {
      ...
      if (!new_transaction)
        {
          // 메인 클라이언트가 받은 tran_index 를 그대로 사용
          error_code = net_client_sub_init ();
          if (error_code == NO_ERROR)
            error_code = boot_client (g_main_tran_info.tran_index,
                                      g_main_tran_info.tran_wait_msecs,
                                      g_main_tran_info.tran_isolation);
          return error_code;
        }
      // new_transaction == true → 서버에 새 tran_index 등록
      tran_index = boot_register_client (&client_credential, ...);
      ...
  }
  ```
- **함께 추가되는 전역**: `g_main_tran_info`(struct: `tran_index`, `tran_wait_msecs`, `tran_isolation`) — 메인 클라이언트가 부팅할 때 캐시, sub에서 shared 모드일 때 재사용.
- **모드 일관성 가드**: 디버그 빌드에서 첫 호출의 `new_transaction` 값을 static 으로 기억하고 이후 호출이 다른 값이면 `assert(false)`. 즉 **세션 단위로 모드가 단일하도록 강제**.
- **sub 식별**: `program_name` 끝에 `(sub_index+1)` 을 붙여 마스터에서 sub session 을 구분.

### 2. `g_main_tran_info` 전역 도입과 메인 부팅 경로 훅

- **위치**: `boot_cl.c` 의 메인 `boot_restart_client()` 흐름.
- **요지**: 메인 클라이언트가 받은 tran_index/wait_msecs/isolation 을 전역에 저장하여 이후 sub 가 "공유 모드" 로 동작할 때 그대로 재사용.
- **코드 발췌**:
  ```c
  boot_client (tran_index, tran_lock_wait_msecs, tran_isolation);
  g_main_tran_info.tran_index = tran_index;
  ```
- **PoC 부재 사유 추정**: 내 PoC 는 worker 마다 multi-connection 세션을 따로 띄우는 방식만 채택했고, "공유 tran_index 모드" 자체가 설계 옵션으로 들어와 있지 않음.

### 3. `MULTI_CONN_TO_A_SERVER` 사용 방향이 반대

- 상대 브랜치 최신 헤드(`17a661256 disable MULTI_CONN_TO_A_SERVER`) 는 매크로를 **비활성화**.
- 내 PoC(`04.multi-connection-client`) 는 이 매크로를 **활성화**해서 worker 마다 별도 connection 으로 동작.
- 즉 상대 브랜치는 추후 multi-conn 의존을 줄이고 boot_restart_client_sub 의 **공유 모드 경로**를 활용하려는 흐름.

### 4. 기타 보조 코드 (전부 같은 커밋 bfabd3c3f 내)

- `work_space.c/.h`: workspace 사용량 / 정합성 관련 일부 변경 (sub 세션이 workspace 를 공유할 때를 위한 사전 조정으로 보임).
- `object_template.c`, `set_object.c`, `schema_manager.c`, `object_domain.c` 등 object/schema 계열에 sub 세션 환경에서의 동작을 가다듬는 변경.
- `network_interface_cl.c`, `client_support.cpp`, `db_multi_threads_connections.h`: sub 세션 RPC/연결 보조.

이들은 모두 transaction id 부여 자체보다는, **공유 tran_index 모드에서 sub 가 안전하게 동작하기 위한 주변 정합성 작업**으로 묶인다.

## (참고) 그 외 눈에 띄는 차이

- `1d0c04208 [CBRD-26062] SIGUSR1-triggered memory dump of logwr_Gl/la_Info` — applylogdb 디버그 보조. 트랜잭션 id 와 무관.
- `d4d38bff7 add CUB_THREAD_LOCAL to net_Server_name` — TLS 추가. 내 PoC 의 `08.isolate-worker-state` 흐름과 부분 중복.
- `33304dcec remove db_share_same_transaction_mode variable` — 이름은 transaction mode 이지만 실제로 transaction id 부여 로직과는 무관한 정리 커밋.

## 다음 액션 권장

- 상대 브랜치 CBRD-26484 의 `boot_restart_client_sub(sub_index, new_transaction)` API를 PoC에 도입할지 결정 — 특히 **공유 tran_index 모드**가 운영상 의미 있는지(예: 모든 worker가 같은 서버 transaction 에 묶이는 경우의 read view / lock 비용) 검토.
- 내 PoC가 `MULTI_CONN_TO_A_SERVER` 를 켠 채 worker 마다 독립 세션을 띄우는 방식은 사실상 상대의 `new_transaction=true` 모드와 동등. 단, **independent 모드만 갖고 있음**을 명시.
- `g_main_tran_info` 와 동등한 메인 tran 상태 캐시를 PoC 에 두지 않은 점은 향후 main↔sub 동기화가 필요할 때 약점이 될 수 있으므로 메모.
