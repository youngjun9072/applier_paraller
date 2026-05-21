# Applier Paraller — 진행 리포트

## 1. Develop Profile

> 상세: [`1.develop_profile/`](1.develop_profile/)

### 1.1 목적

병렬화 적용 이전(develop 브랜치) 상태의 동작 특성과 복제 시간을 기준선(baseline)으로 측정한다.
이후 병렬화 버전의 성능을 비교하기 위한 기준이 된다.

### 1.2 측정 (슬레이브 복제 시간, Release 모드)

- 대상: tbl1 ~ tbl10
- 측정값: 테이블별 슬레이브 적용 시작/종료 시각

| 지표 | 값 |
|------|----|
| 슬레이브 복제 시간 (전체) | **29.42초** (03:41:52.833 → 03:42:22.249) |
| 테이블별 평균 수행 시간 | **5.97초** (총 Duration 합 59.71초 / 10) |

> raw 데이터: [`1.develop_profile/README.md`](1.develop_profile/README.md)

### 1.3 특성

- **테이블들이 거의 순차적으로 시작**됨 — 한 테이블이 끝나가는 시점에 다음 테이블이 시작 (병렬성 없음).
- **그러나 전체 수행 시간은 짧다 (29.42초)** — 직렬 처리임에도 테이블당 처리 자체가 빠르고(평균 5.97초) 오버헤드가 적음.
- 이 값이 이후 병렬화 버전이 넘어야 할 **성능 기준선**.

## 2. Design

> 상세: [`2.design/poc_design.md`](2.design/poc_design.md)

### 2.1 목적

- 현재 `applylogdb`는 순차 처리 구조라, 마스터의 병렬 작업이 증가할수록 슬레이브 반영 지연이 누적됨.
- 가장 큰 비용은 슬레이브로의 item flush 단계.
- 따라서 **병렬화로 복제 지연을 줄이는 것**이 PoC 목표.

### 2.2 PoC 대상 시나리오

- 마스터에서 다량의 Insert.
- Long transaction 중심.
- 테이블 10개 × 10만 건 Insert, 10만 건이 단일 트랜잭션.
- SBR 등 그 외 시나리오는 일단 제외.

### 2.3 병렬화 원칙

- 마스터 커밋 순서 ≠ 슬레이브 apply 완료 순서여도 허용 (dependency 판별은 PoC 범위 외).
- 단, **커밋 단위는 보장**. Long transaction은 1회 commit.
- 처리 단위는 **item이 아니라 transaction**.
- PoC이므로 최소 구현 + 일부 하드코딩 허용.

### 2.4 처리 흐름 요약

1. LogReader가 log volume에서 replication log 읽기.
2. `LA_ITEM` 생성 → transaction별 `LA_APPLY` 구성.
3. Long transaction은 head + metadata만 유지.
4. commit log 감지 시 transaction 확정 → worker 큐에 등록.
5. 다수 ApplyWorker가 큐에서 꺼내 병렬 apply.
6. 일반 tx: item을 순차 처리 → workspace 적재 → flush/commit.
7. Long tx: log range 재탐색 → workspace 재구성 → flush/commit.
8. statement-based item은 worker가 직접 슬레이브에 실행.
9. worker는 완료 결과 + `last_completed_lsa` 보고.
10. LogReader가 결과 수집 → global `committed_lsa` 갱신 → `_db_ha_apply_info` 갱신 → item reclaim.

### 2.5 PoC 범위 제외 항목

- transaction 간 dependency 판별.
- 정교한 병렬 스케줄링.
- 정교한 오류 복구.
- insert 외 연산 위주 시나리오(SBR 등).

### 2.6 TODO / 리스크

- 파일 동시 접근 시 I/O 병목 가능.
- 캐시 & 버퍼 페이지 참조 시 lock 필요할 수 있음.

## 3. Dev Log

> 상세: [`3.dev_log/`](3.dev_log/)

### Step 1. 병렬화 개발 로그

> 기간: 2026-04-15 ~ 2026-04-30 · 브랜치: `feature/parallel_applylogdb_poc` (vs `develop`) · 변경 규모: 46개 파일, +4,038 / −907 · 항목별 상세는 [`3.dev_log/`](3.dev_log/) 참고.

기존 단일 흐름이던 `applylogdb`를 LogReader와 다수의 ApplyWorker로 쪼개는 구조 개편을 PoC 수준으로 진행했다. transaction 단위 worker 큐를 도입해 commit log 감지 시점에 dispatch 하도록 만들고, worker 완료 보고 경로를 reader의 dispatch 경로와 분리해 서로 막지 않도록 했다.

병렬 동작의 핵심은 worker 간 공유 상태를 좁히는 일이었다. 따라서 error context, client session, client transaction, worker-local 상태 순으로 격리 범위를 단계적으로 넓혔다. 이 과정에서 단일 스레드 가정으로 묶여 있던 전역 변수들(`locator_Keep` cache, 일부 client 전역, scratch 버퍼)을 thread-local 저장소로 옮기고, multi-connection 클라이언트를 활성화해 worker마다 슬레이브에 독립 세션을 갖도록 했다. worker 동시 출발 시 드러난 초기화 race는 startup 직렬화 가드로 막았고, 다수 worker가 마스터에 별도 applier처럼 보이지 않도록 HA state notification은 worker 세션에서 차단했다.

처리량 측면에서는 worker 수를 1 → 2 → 4 → 10 으로 단계적으로 확장했고, dispatch-order FIFO를 도입했다. 결과 수집은 out-of-order 를 허용하되, 외부 노출 LSA는 reader가 커밋 LSA 기준 in-order 로만 갱신하도록 retire order를 보존했다. long transaction 처리에서는 SYSOP_END 등 sysop record 처리를 commit dispatch 시점으로 미루어 중간 이벤트가 worker 분기에 끼어들지 않게 했다.

운영 관점에서는 TLS 확장과 worker 증가로 인한 VSZ 급증을 완화하기 위해 `max_mem_size` 하한을 임시로 끌어올렸고, 병렬 동작을 정량 관찰하기 위해 reader/worker 처리량, 큐 깊이, flush·statement 컨텍스트, cache buffer, timing breakdown 등 다층 계측 로그를 매크로 게이트로 묶어 추가했다.

## 4. 병렬화 증명 (Proof)

> 상세: [`4.parallelization_proof/`](4.parallelization_proof/)

### 4.1 목적

- 섹션 3에서 구현한 병렬화 구조가 **실제로 병렬 수행되는지**, 그리고 **성능 향상이 발생하는지**를 측정으로 확인.
- 기능 검증이 아닌 **정량 검증**이 목적.

### 4.2 측정 시나리오

- 대상: tbl1 ~ tbl10 (10개 테이블) 동시 부하
- 측정 항목: 테이블별 시작/종료 시각 → 마스터·슬레이브·전체 복제 시간 도출
- 기준 산식:
  - **마스터 복제 시간** = 마스터 최초 Start → 마스터 최종 End
  - **슬레이브 복제 시간** = 슬레이브 최초 Start → 슬레이브 최종 End
  - **전체 복제 시간** = 마스터 최초 Start → 슬레이브 최종 End

### 4.3 결과 (csql 테스트, Release 모드)

| 지표 | 값 |
|------|----|
| 마스터 복제 시간 | 57.86초 |
| 슬레이브 복제 시간 | **49.53초** |
| 전체 복제 시간 | 104.78초 |

> Debug 모드 결과 및 raw 데이터: [`4.parallelization_proof/csql_test/csql_test_result.md`](4.parallelization_proof/csql_test/csql_test_result.md)

### 4.4 baseline 대비 비교

| 항목 | Baseline (섹션 1, 직렬) | 병렬화 버전 (섹션 4) | 변화 |
|------|------------------------|---------------------|------|
| 병렬 동작 | 없음 (순차 시작) | **있음** (동시 시작 확인) | 구조 달성 |
| 슬레이브 복제 시간 | 29.42초 | 49.53초 | **약 1.68배 증가** |

### 4.5 관찰

- **병렬 수행 자체는 정상 동작 확인** — 마스터/슬레이브 모두 다수 테이블의 시작 시각이 거의 동시에 찍힘 (수십 ms 내), 워커들이 직렬 대기 없이 함께 출발함. 섹션 1의 직렬 시작 패턴과 명확히 대비됨.
- **그러나 복제 시간은 오히려 늘어남** — baseline 29.42초 → 병렬 49.53초. 병렬 구조 도입이 곧 단축으로 이어지지 않았고, 가장 느린 테이블이 전체 종료 시점을 결정하며 꼬리가 길게 형성되어 직렬 baseline보다 더 오래 걸림.
- → **"병렬은 보이지만 빨라지지 않았다"** — 어디선가 직렬 병목이 존재한다는 강력한 신호.

### 4.6 다음 액션

- 병목 위치 식별을 위해 **워커 수를 변경하며 재측정** 예정.
- 워커 수 ↔ 전체 복제 시간 관계를 보고, 병렬화 효과가 포화되는 지점 / 직렬 병목 후보 식별.

## 5. 병목 분석 (Bottleneck Analysis)  *— 진행 중 (WIP)*

> 상세: [`5.bottleneck_analysis/`](5.bottleneck_analysis/)

### 5.1 목적

섹션 4에서 확인한 *"병렬은 보이지만 빨라지지 않는다"* 의 원인이
- (가) 직렬 병목인지,
- (나) 병렬화가 제대로 동작하지 않아서인지

를 가리고, 병목이라면 어느 지점인지를 좁힌다.

### 5.2 1단계 — csql 부하 테스트 (활성 워커 수 변경)

**왜 이 측정인가**: "병렬은 보이지만 빨라지지 않는다"의 원인 후보 중 *슬레이브 쪽 동시 쓰기 부하가 병목인지* 를 먼저 가리기 위해, **활성화된 워커 수만 바꿔서** 슬레이브 쪽 실제 쓰기 부하를 제어한 비교 측정을 수행.

- 변수: `worker_1` (1개만 활성) vs `worker_10` (10개 모두 활성)
- 공통: 워크로드(tbl1~tbl10, 각 10만 건 / 단일 트랜잭션), Release 빌드, csql 부하
- "활성화" 정의: `repl obj 생성 + flush` 수행 여부 → 활성 워커만 슬레이브로 실제 저장 요청 발생

| 항목 | worker_1 (활성 1) | worker_10 (활성 10) |
|------|-------------------|---------------------|
| 슬레이브 복제 시간 | **8.99초** | 59.17초 |
| 전체 복제 시간 | 85.07초 | 113.31초 |

→ **1차 결론**: 병렬화는 정상 동작하지만, **슬레이브 측 동시 쓰기 경합이 직렬 병목**으로 작용 (슬레이브 시간 약 **6.6배 증가**).

### 5.3 2단계 — perf 프로파일링 (슬레이브 응답 경로)

**왜 이 측정인가 / 왜 perf인가**: 1차에서 병목이 *슬레이브 쪽 쓰기 경합* 으로 좁혀졌으므로, 이제는 **워커의 처리 시간이 어디서 소비되는지를 함수/콜스택 단위로** 가려야 함. 시간이
- 클라이언트 측 CPU(repl obj 생성, batch 구성 등),
- 송신(`send`),
- 슬레이브 응답 대기(`recv`)

중 어느 쪽에 머무는지를 확인하려면 콜스택 기반 프로파일링이 가장 적합하므로 `perf`로 슬레이브 측 applier 워커 프로세스를 측정.

| 지표 | worker_1 (tbl2) | worker_10 평균 | 비율 |
|------|-----------------|----------------|------|
| `la_flush_repl_items` 누적 | 3.335 s | 45.81 s | × 13.7 |
| `recv` self (응답 대기) | 2.940 s (88.2%) | 45.286 s (**98.9%**) | × 15.4 |
| 서버 `xlocator_repl_force` per-call | 114 µs | 2,577 µs | **× 22.5** |

→ **2차 결론**: 시간 거의 전부가 `recv`(응답 대기)에 머물러 있고, 서버 측 `xlocator_repl_force` per-call이 22.5배 증가 → 슬레이브 측 경합의 실체는 구체적으로 **`xlocator_repl_force` 경로의 동시 호출 경합**.

### 5.4 3단계 — 슬레이브 서버 측 perf 프로파일링

> 상세: [`5.bottleneck_analysis/3.server_perf_test/`](5.bottleneck_analysis/3.server_perf_test/) (콜체인, 가설 매칭, 선결 검증 raw 데이터)

**왜 이 측정인가**: 2차 결론으로 `xlocator_repl_force` 경합이 좁혀졌으나, **서버 내부의 어느 함수/락에서 시간이 소비되는지**는 applier 측 perf만으로는 식별 불가. 슬레이브 서버 프로세스에 대한 perf로 의심 지점을 직접 검증.

#### 선결 검증 — 서버가 실제로 병렬 처리하는가

의심 지점 검증 전에 *서버가 다수 워커 요청을 실제로 병렬 처리하고 있는지* 부터 확인 (직렬화 설계라면 경합 분석 자체가 무의미).

`slocator_repl_force` 를 호출한 서버 TID 분포 측정:
- 총 호출 수 **170,001** = 10 트랜잭션 × 17,000 (applier 측과 일치 → 누락 없음)
- 유니크 TID **19개** (기대치 10의 약 2배)
- 호출이 여러 TID에 분산되었으나, **분포가 매우 불균등** (최상위 17k vs 최하위 2k, 약 8배 격차)

→ **서버는 직렬화가 아니라 병렬로 동작 중 → 선결 검증 통과**. 의심 지점 분석은 유효.

**서버 측 매핑 구조 (회의로 확정, 디버그 로그 검증)**:
- 클라이언트 연결은 워커가 아닌 **"코어"(논리 단위)** 에 매핑됨.
- **1 코어 = 6 워커 (실제 스레드) 풀**. 클라이언트 리퀘스트는 매핑된 코어 내 가용 워커에 할당.
- → **1 클라이언트 : 1 코어 : 6 워커 풀** 구조. (10 클라이언트 → 코어 10개 → 이론 최대 60 TID, 실제 19 TID = 코어당 평균 약 1.9 워커 사용)
- 워커 할당은 요청 도착 타이밍·워커 상태에 의존하는 우연성 → 분배 불균형은 **별도 분석 필요** 항목으로 분리.

#### 의심 지점

- **H1 — WAL 버퍼 포화 시 워커가 1 ms 씩 잠드는 코드** (CPU on)
- **H2 — 모든 로그 기록이 통과하는 단일 mutex (`prior_lsa_mutex`)** (CPU off)
- **H3 — 인덱스 페이지가 분할될 때** (CPU off)

#### 결과 (가설 매칭)

| ID | 매칭 함수 inclusive % | 트리 등장 |
|----|------------------------|-----------|
| H1 `thread_sleep` | 0.00% | ✗ (비활성) |
| H2 `__lll_lock_wait` / `prior_lsa_next_record_internal` / `futex_wait` | **21.21% (on-CPU), 97.21% (off-CPU)** | ✓ 다수 위치 |
| H3 `pgbuf_block_bcb` / `pgbuf_lock_page` | 0.04% | ✗ (비활성) |

핵심 관찰:
- H2 단독 지목 — heap·btree·tran stats 모든 로깅 경로가 동일 `prior_lsa_mutex`로 수렴.
- **락 자체보다 "락 안의 LZ4 압축"이 본질** — `prior_lsa_alloc_and_copy_crumbs → log_zip → LZ4_compress` (11.03%)가 critical section 내부에서 실행되어 락 보유 시간을 늘림. per-call 22배 폭증의 메커니즘.

→ **3차 결론**: 병목의 실체는 **`prior_lsa_mutex` contention (H2)**, 본질은 **락 안에서 수행되는 LZ4 압축이 락 보유 시간을 늘리는 것**.

### 5.5 다음 단계 (진행 중)

> 결과 정리 위치: [`5.bottleneck_analysis/`](5.bottleneck_analysis/) 하위에 후속 검증용 디렉토리(예: `4.compression_poc/`, `5.mutex_event_trace/` 등) 신설 예정.

3차 결론(H2)에 따른 완화 방안 검토 및 검증:

- **(우선) 압축을 critical section 밖으로 이동** — `log_zip / LZ4_compress`를 mutex 보유 전후로 분리하는 PoC 적용 → recv self 단축 여부로 인과 검증.
- (보조) `perf lock` / `perf trace -e syscalls:sys_enter_futex` 로 `prior_lsa_mutex` 경합 이벤트 직접 카운트 → 가설 못박기.
- H2 완화 이후 **2차 병목 후보(`lock_object` lock-free hashmap, 10.92%)** 가 다음 핫스팟으로 부상하는지 재측정.

## 6. Parallelization Profile

> 상세: [`6.parallelization_profile/`](6.parallelization_profile/)

### 6.1 목적

- 섹션 1(`1.develop_profile`)과 동일 워크로드(테이블 10개 × 10만 건, **10 클라이언트** 동시 부하)를 병렬화 적용 빌드에서 재측정.
- 1:1 매칭 데이터셋은 [`1.develop_profile/1.insert/client_10.md`](1.develop_profile/1.insert/client_10.md), [`1.develop_profile/2.update/client_10.md`](1.develop_profile/2.update/client_10.md).

### 6.2 환경

- 빌드: `CUBRID-11.5.0.2197-72099e6-Linux.x86_64`
- 공통 설정: `double_write_buffer_size=0`, `data_buffer_size=5G`, `log_buffer_size=5G`, `log_volume_size=1G`, `checkpoint_interval=30min`
- 사전 처리: `;checkpoint`, `addvoldb` (데이터 100GB + temp)

### 6.3 INSERT — 10 클라이언트 매칭 비교

**전체 지표 (Develop vs Parallel)**

| 지표 | Develop (client_10) | Parallel | 변화 |
|---|---|---|---|
| 마스터 전체 수행 시간 | 48.681 s | 61.665 s | **+26.7%** |
| 슬레이브 전체 수행 시간 | 29.416 s | **16.428 s** | **−44.2%** |

원본 데이터셋:

- Develop: [`1.develop_profile/1.insert/client_10.md`](1.develop_profile/1.insert/client_10.md)
- Parallel: [`6.parallelization_profile/1.insert_csql/result.md`](6.parallelization_profile/1.insert_csql/result.md)

### 6.4 UPDATE — 10 클라이언트 매칭 비교

**전체 지표 (Develop vs Parallel)**

| 지표 | Develop (client_10) | Parallel | 변화 |
|---|---|---|---|
| 마스터 전체 수행 시간 | 54.932 s | 64.006 s | **+16.5%** |
| 슬레이브 전체 수행 시간 | 29.147 s | **13.713 s** | **−53.0%** |

원본 데이터셋:

- Develop: [`1.develop_profile/2.update/client_10.md`](1.develop_profile/2.update/client_10.md)
- Parallel: [`6.parallelization_profile/2.update_csql/result.md`](6.parallelization_profile/2.update_csql/result.md)

### 6.5 요약

- **슬레이브 복제 시간이 INSERT/UPDATE 모두 단축** (−44%, −53%) — 병렬화가 전체 종료 시점을 줄이는 효과를 정량 확인.
- **마스터 전체 수행 시간은 +17~27% 증가** — 다수 클라이언트가 동시에 마스터에 부하를 줄 때 단일 마스터 자원 경합으로 처리 시간이 늘어나는 효과 동반.
- 테이블 개별 수행 시간은 원본 raw 파일 참조 (위 링크). 본 보고서에서는 **전체 복제 시간 비교**에 집중.

## 9. TODO

> 상세: [`9.todo/`](9.todo/)

- [`poc_design_comparison/`](9.todo/poc_design_comparison/) — PoC 디자인 문서와 실제 구현 차이 비교
- [`cs_lib_comparison/`](9.todo/cs_lib_comparison/) — cs_lib 비교
