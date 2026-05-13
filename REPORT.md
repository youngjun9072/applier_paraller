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
