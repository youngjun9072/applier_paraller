# Applier Paraller — 진행 리포트

## 1. Develop Profile

_(작성 예정)_

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

## 4. TODO

> 상세: [`4.todo/`](4.todo/)

- [`poc_design_comparison/`](4.todo/poc_design_comparison/) — PoC 디자인 문서와 실제 구현 차이 비교
- [`cs_lib_comparison/`](4.todo/cs_lib_comparison/) — cs_lib 비교
