# Applylogdb 병렬화 PoC 작업 재설계

## 목적

1. 현재 applylogdb 는 순차적인 처리를 수행하고있다. 이러한 처리방식은 마스터에서 다수의 클라이언트가 병렬의 작업을 수행할 경우, 그리고 마스터에서 병렬로 처리하는 연산의 수가 증가할수록 슬레이브에 모든 데이터가 반영되기까지 지연이 증가하게된다. 
2. applylogdb를 통해 로그를 복제하는 과정에서 가장 많은 수행시간을 처리하는 작업은 아이템을 슬레이브 서버로 플러시하는 과정이다
3. 위 두가지 요인은 applylogdb에서 복제를 지연시키는 요인이므로 병렬화를통해 성능 향상시킴을 목적으로한다.

### PoC 대상

- 마스터에서 다량의 Insert
- Long transaction
- 테이블 총 10개, 테이블 당 10만건 Insert, 10만건은 하나의 트랜잭션
- 이외의 시나리오는 일단 고려 안함(sbr)

## 병렬화

마스터의 커밋 순서와 슬레이브의 apply 완료 순서가 완전히 동일할 필요는 없다.

dependency가 있는 작업에 대해서는 마스터의 커밋 순서와 슬레이브의 반영 순서를 고려하지 않는다.

단, 커밋의 단위는 보장해야하므로 poc 대상 Long transaction 에서 commit은 한번만 발생하도록한다.

본 문서에서 트랜잭션은 마스터의 복제 로그에서 하나의 commit 단위로 식별되는 작업 단위를 의미한다.

### 기본 원칙

- PoC 이므로 가장 간단한 구현을 한다. 일부는 하드코딩이나 임시 주석을 허용한다.
- PoC 단계에서는 insert 연산만 대상으로 하며, 작은 transaction과 long transaction을 모두 포함한다.
- 단, 주요 시나리오는 long transaction이다.
- 처리 단위는 transaction이다.
- transaction 간 dependency 판별은 이번 PoC 범위에 포함하지 않는다.
- 향후 실제 구현에서도 복제 데이터는 마스터에서 transaction boundary 기준으로 묶어 전달하는 구조를 전제로 한다.
- transaction 간 dependency 판별, 병렬 스케줄링, 정교한 오류 복구는 이번 PoC 범위에서 제외한다.

## 모듈

병렬화를 위한 모듈은 LogReader(Reader)와 ApplyWorker(Worker)로 나뉜다.

### LogReader

- Active/Archive에서 복제 로그를 읽는다.
- LA_ITEM을 생성하고, transaction 단위로 item을 묶는다.
- commit log를 만나면 해당 transaction의 apply 단위를 확정한다.
- 확정된 transaction을 worker 작업 큐에 등록한다.
- 등록된 transaction 상태는 apply 완료 전까지 worker가 참조할 수 있어야 한다.
- long transaction일 경우 전체 item list를 계속 유지하지 않고, anchor item(head)과 필요한 log range metadata를 유지한다.
- worker 완료 결과를 수집한다.
- commit LSA 순서 기준으로 전역 완료 여부를 판정한다.
- 전역 완료가 확인된 transaction에 대해서 global committed_lsa를 갱신한다.
- _db_ha_apply_info 갱신 및 reclaim 가능한 transaction 정리를 수행한다.

### ApplyWorker

- 전달받은 transaction을 slave에 반영한다.
- worker는 설정 파라미터에 따라 N개 생성되며, 서로 병렬로 apply를 수행할 수 있다.
- 각 worker는 개별 작업 큐, worker-local workspace, 슬레이브 서버와 연결된 개별 세션을 가진다.
- row item은 worker-local workspace에 적재한 뒤 flush한다.
- statement/DDL은 슬레이브 서버로 직접 실행한다.
- flush 및 commit은 worker 단위로 독립 수행한다.
- transaction 처리 성공 시 완료 상태와 last_completed_lsa를 LogReader에 보고한다.
- long transaction일 경우 log range를 순차 재탐색하여 replication item을 재구성하고, 이를 worker-local workspace에 적재하여 flush/commit 한다

## 설계

AS-IS

```bash
+----------------------+
| ApplyLog Main        |
+----------------------+
| data                 |
| - LA_ITEM            |
| - LA_APPLY           |
| - final_lsa          |
| - committed_lsa      |
| - workspace          |
| function             |
| - read active/arv log|
| - decode log record  |
| - build LA_ITEM      |
| - build LA_APPLY     |
| - process repl items |
| - flush row items    |
| - execute stmt       |
|   directly           |
| - commit             |
| - update             |
|   _db_ha_apply_info  |
+----------+-----------+
           |
           v
    Slave DB / Server

```

TO-BE

```bash
     +----------------------------+
     |         LogReader          |
     +----------------------------+
     | data                       |
     | - LA_ITEM                  |
     | - LA_APPLY                 |
     | - final_lsa                |
     | - committed_lsa            |
     | function                   |
     | - read active/arv log      |
     | - build LA_ITEM            |
     | - build LA_APPLY           |
     | - detect long trans        |
     | - enqueue committed tx     |
     | - collect results          |
     | - update apply info        |
     | - reclaim items            |
     +-------------+--------------+
                   |
                   | enqueue committed tx
                   v

  +----------------------+  +----------------------+       +----------------------+
  |       Worker 0       |  |       Worker 1       |  ...  |       Worker N       |
  +----------------------+  +----------------------+       +----------------------+
  | data                 |  | data                 |       | data                 |
  | - queue              |  | - queue              |       | - queue              |
  | - session            |  | - session            |       | - session            |
  | - workspace          |  | - workspace          |       | - workspace          |
  | function             |  | function             |       | function             |
  | - process repl items |  | - process repl items |       | - process repl items |
  | - flush row items    |  | - flush row items    |       | - flush row items    |
  | - execute stmt       |  | - execute stmt       |       | - execute stmt       |
  |   directly           |  |   directly           |       |   directly           |
  | - commit             |  | - commit             |       | - commit             |
  | - report completed   |  | - report completed   |       | - report completed   |
  |   lsa                |  |   lsa                |       |   lsa                |
  +----------+-----------+  +----------+-----------+       +----------+-----------+
             |                         |                                |
             +-------------------------+--------------------------------+
                                       |
                                       v
                              Slave DB / Server
```

## 중요 원칙

- 처리 단위는 item이 아니라 transaction이다.
- 각 worker는 자신의 처리 흐름에서 queue -> flush -> commit 순서를 지킨다.
- global committed_lsa와 _db_ha_apply_info는 LogReader가 관리한다.
- worker는 transaction apply, flush, commit을 수행하고 완료 결과를 LogReader에 보고한다.
- item reclaim은 worker가 직접 수행하지 않고, LogReader가 완료 결과를 수집한 뒤 정리한다.
- long transaction은 전체 item list를 계속 유지하지 않고, anchor item과 필요한 log metadata를 유지한 뒤 worker가 재구성한다.

## 요구사항

- LogReader는 로그 파일에서 replication log를 읽어 LA_ITEM을 생성하고 transaction 단위로 LA_APPLY를 구성한다.
- LogReader가 관리하는 transaction 상태는 apply 완료 전까지 worker가 참조할 수 있어야 한다.
- LogReader는 commit log를 만나면 해당 transaction을 committed transaction으로 확정하고 worker queue에 등록한다.
- worker는 자신의 작업 큐에서 transaction을 꺼내 해당 apply 상태를 참조하여 slave apply를 수행한다.
- insert item은 worker-local workspace에 추가한다.
- statement-based replication item은 worker가 슬레이브 서버에 직접 요청한다.
- ws_Repl_objs와 ws_Repl_error_link는 전역 변수를 제거하고 worker별로 분리한다.
- flush 및 commit은 worker 단위로 수행하며, flush threshold와 commit interval도 worker별로 관리한다.
- worker는 transaction 처리 성공 시 완료 상태와 last_completed_lsa를 LogReader에 보고한다.
- LogReader는 worker 완료 결과를 수집하고 global committed_lsa를 갱신한다.
- LogReader는 committed_lsa 갱신 시점에 _db_ha_apply_info를 업데이트한다.
- LogReader는 완료가 확정된 transaction의 item list를 정리하고 reclaim 한다.
- long transaction일 경우 LogReader는 head와 log range metadata를 유지하고, worker는 이를 기준으로 로그를 재탐색하여 item을 재구성할 수 있어야 한다.
- worker 개수는 파라미터로 설정 가능해야 하며, 설정된 개수만큼 병렬 apply worker를 생성할 수 있어야 한다.

## 처리 흐름

1. LogReader가 log volume에서 replication log를 읽는다.
2. LogReader가 LA_ITEM을 생성하여 transaction별 LA_APPLY를 구성한다.
3. long transaction인 경우 LogReader는 head와 필요한 metadata만 유지한다.
4. LogReader가 commit log를 만나면 해당 transaction을 committed transaction으로 확정한다.
5. LogReader가 해당 transaction을 worker의 작업 큐에 등록한다.
6. 설정된 개수만큼 생성된 ApplyWorker가 각자의 작업 큐에서 transaction을 꺼내 병렬 처리한다.
7. 일반 transaction인 경우 worker는 item list를 순차 처리하여 worker-local workspace에 적재하고 flush/commit 한다.
8. long transaction인 경우 worker는 log range를 재탐색하여 replication item을 재구성하고, 이를 worker-local workspace에 적재하여 flush/commit 한다.
9. statement-based replication item은 worker가 직접 슬레이브 서버에 실행 요청한다.
10. worker는 transaction 처리 성공 시 완료 상태와 last_completed_lsa를 LogReader에 보고한다.
11. LogReader는 worker 완료 결과를 수집하고 global committed_lsa를 갱신한다.
12. LogReader는 _db_ha_apply_info를 업데이트한다.
13. LogReader는 완료가 확정된 transaction의 item을 정리하고 reclaim 한다.

### 변수 정리

**Reader-owned**

| 변수/자료구조 | 사유 |
| --- | --- |
| la_Info.final_lsa | 현재 로그를 읽고 전진하는 Reader 진행 위치이므로 Reader가 단독 소유하는 편이 자연스럽다 |
| la_Info.append_lsa | active log header 기준으로 Reader가 진행 가능 범위를 판단할 때 사용한다 |
| la_Info.eof_lsa | EOF 판단용 Reader 상태이다 |
| la_Info.act_log | active log file/header/descriptor 상태는 Reader가 관리하는 것이 자연스럽다 |
| la_Info.arv_log | archive log file/header/descriptor 상태는 Reader가 관리하는 것이 자연스럽다 |
| la_Info.cache_pb | 로그 페이지 cache는 Reader가 로그를 읽는 동안 사용하는 상태이다 |
| la_Info.log_data | 로그 읽기용 scratch buffer이다 |
| la_Info.log_path_lockf_vdes | applylog 중복 실행 방지용 파일 락으로 중앙 주체가 관리해야 한다 |
| la_Info.db_lockf_vdes | DB lock은 Reader가 중앙에서 관리하는 편이 안전하다 |
| la_Info.last_deleted_archive_num | archive 삭제 진행 상태는 Reader 흐름에 속한다 |
| la_Info.last_time_archive_deleted | archive 삭제 주기 상태는 Reader 흐름에 속한다 |
| la_Info.is_apply_info_updated | apply info 갱신 시점을 Reader가 책임지면 가장 단순하다 |
| la_slave_db_name | 초기화 후 읽기 전용 설정값이다 |
| la_peer_host | 초기화 후 읽기 전용 설정값이다 |

**Shared with lock**

| 변수/자료구조 | 사유 |
| --- | --- |
| la_Info.repl_lists | Reader가 생성하고 Worker가 참조하며 완료 후 정리도 필요하므로 공유 자원이다 |
| LA_APPLY | transaction apply 단위로 Reader와 Worker가 함께 접근한다 |
| LA_ITEM | transaction 내부 item 리스트를 Reader와 Worker가 함께 참조할 수 있다 |
| la_Info.repl_cnt | repl_lists의 capacity 메타데이터이므로 공유 registry의 일부다 |
| la_Info.cur_repl | repl_lists 인덱스 관리 상태이므로 공유 registry의 일부다 |
| la_Info.committed_lsa | 전역 완료 기준이므로 여러 worker 완료 결과를 반영할 때 보호가 필요하다 |
| la_Info.required_lsa | reclaim 가능 범위 계산에 쓰이는 전역 상태이다 |
| la_Info.commit_head / la_Info.commit_tail | 현재 구조는 단일 commit queue이므로 병렬 구조에서 공유한다면 보호가 필요하다 |
| la_applier_need_shutdown | Reader/Worker/종료 경로가 함께 보는 종료 플래그이다 |
| la_applier_shutdown_by_signal | signal 종료 상태를 여러 실행 흐름이 함께 본다 |

**Worker-local**

| 변수/자료구조 | 사유 |
| --- | --- |
| la_Info.rec_type | row decode 과정에서 덮어쓰는 scratch buffer이므로 worker별 분리가 필요하다 |
| la_Info.undo_unzip_ptr | unzip scratch buffer이므로 worker별 분리가 필요하다 |
| la_Info.redo_unzip_ptr | unzip scratch buffer이므로 worker별 분리가 필요하다 |
| LA_RECDES_POOL la_recdes_pool | next_idx를 증가시키는 mutable pool이므로 worker별 분리가 필요하다 |
| la_Info.num_unflushed | flush threshold는 worker workspace 기준으로 관리해야 한다 |
| la_Info.committed_rep_lsa | replication item 반영 위치는 worker별 관리가 더 자연스럽다 |
| la_Info.last_committed_lsa | 기존 단일 흐름용 비교 기준이라 worker별 상태로 나누는 편이 안전하다 |
| la_Info.last_committed_rep_lsa | 기존 단일 흐름용 비교 기준이라 worker별 상태로 나누는 편이 안전하다 |
| la_Info.total_rows | 처리량 기준은 worker별로 관리하는 것이 적절하다 |
| la_Info.prev_total_rows | 처리량 비교 기준은 worker별로 관리하는 것이 적절하다 |
| la_Info.log_record_time | worker가 처리 중인 transaction 시간 기준으로 쓰인다 |
| la_Info.log_commit_time | worker commit 시점 기준으로 관리하는 편이 자연스럽다 |
| la_Info.insert_counter | worker별 apply 통계이다 |
| la_Info.update_counter | worker별 apply 통계이다 |
| la_Info.delete_counter | worker별 apply 통계이다 |
| la_Info.schema_counter | worker별 apply 통계이다 |
| la_Info.commit_counter | worker별 apply 통계이다 |
| la_Info.fail_counter | worker별 apply 통계이다 |
| la_Info.status | 기존 단일 흐름 가정 상태값이라 worker별로 나누는 편이 안전하다 |
| ws_Repl_objs | row replication object queue는 반드시 worker별 workspace로 분리해야 한다 |
| ws_Repl_error_link | flush 오류 정보는 worker별로 분리해야 한다 |
| LOCATOR_MFLUSH_CACHE | flush 시점에만 쓰는 임시 패킹 버퍼로 worker 내부 지역 자료구조에 해당한다 |
| la_cache_buffer_replace(): static last | cache replacement cursor는 공유보다 worker별 상태가 적절하다 |
| la_apply_repl_log(): static total_repl_items | page buffer release cadence는 worker별로 달라져야 한다 |
| la_commit_transaction(): static last_time | ws cull 주기는 worker별 commit 흐름에 종속된다 |
| la_commit_transaction(): static last_applied_item | ws cull 기준 처리량은 worker별로 관리해야 한다 |
| la_check_time_commit(): static ha_mode | parameter cache이지만 worker별 보관이 단순하다 |
| la_init(): static start_vsize | 메모리 기준치는 worker별 또는 역할별로 분리하는 편이 낫다 |
| la_get_adaptive_time_commit_interval(): static delay_hist_idx | commit interval 조정 상태는 worker별로 분리해야 한다 |
| la_delay_replica(): static ha_mode | parameter cache이다 |
| la_delay_replica(): static replica_delay | parameter cache이다 |
| la_delay_replica(): static replica_time_bound | parameter cache이다 |
| la_enable_sql_logging | 설정값이지만 worker가 독립적으로 참조하는 로컬 설정으로 두는 편이 단순하다 |

---

## Appendix

### Parameter

- 워커의 수는 설정 파일에서 설정할 수 있으며, 설정 파일과 형식은 다음과 같다.
    - cubrid_ha.conf
    
    ```bash
    ha_worker=[n] #default = 1
    ```
    

### long transaction 처리 순서

LogReader 는 아이템이 일정 개수를 넘어가면 long transaction 으로 처리한다. 기존에는 head를 제외한 모든 item을 해제하고, long transaction으로 표시한다. 그리고 재시작할 첫 아이템(head)와 재 탐색시 종료 lsa(last_lsa)를 저장한다. 이 정보는 apply 단계에서 아이템을 다시 읽는 범위로 사용되며, 다시 읽은 아이템은 workspace에 등록한다. 기존에는 과정이 하나의 순차적인 로직으로 처리된다. 

병렬화에서는 방법은 동일하지만 역할이 분리된다. LogReader는 아이템 해제, long transaction 마킹, 다시 탐색할 범위 설정을 수행한 후 ApplyWorker에게 트랜잭션 id를 전달한다. ApplyWorker는 apply단계에서 long transaction 플래그를 만나면 파일로부터 로그를 읽어 workspace에 추가한다.

AS-IS

```bash
Long Transaction

AS-IS

ApplyLog Main:
  build item list until threshold
             -> free all except head
             -> mark long transaction
             -> keep head + last_lsa
             -> head -> apply
                     -> read next item from log
                     -> apply sequentially
                     -> flush/commit

-------------------------------------
LogReader
  -> la_apply_log_file()
     -> la_log_record_process()
        -> la_get_page_buffer()
        -> LOG_GET_LOG_RECORD_HEADER()
        -> la_set_repl_log()
           -> la_make_repl_item()
              -> la_log_copy_fromlog()
              -> or_unpack_int()
              -> or_unpack_string()
              -> db_make_string()
           -> la_add_repl_item()
        -> la_add_node_into_la_commit_list()

  -> long transaction prepare
     -> la_free_all_repl_items_except_head()
     -> apply->is_long_trans = true
     -> keep apply->head + apply->last_lsa

```

TO-BE

```sql
LogReader:
  build item list until threshold
             -> free all except head
             -> mark long transaction
             -> keep head + last_lsa
             -> register transaction

ApplyWorker:
  head -> apply
       -> read next item from log
       -> workspace enqueue
       -> flush/commit

--------------
ApplyWorker
  -> la_apply_commit_list()
     -> la_apply_repl_log()
        -> la_get_next_repl_item_from_list()
        -> la_get_next_repl_item_from_log()
           -> la_get_page()
           -> LOG_GET_LOG_RECORD_HEADER()
           -> la_make_repl_item()

        -> la_apply_insert_log() / la_apply_update_log() / la_apply_delete_log()
           -> la_get_page()
           -> la_get_recdes()
           -> db_find_class()
           -> la_repl_add_object()
           -> la_flush_repl_items()
              -> locator_repl_flush_all()
                 -> net_client_request_3_data(NET_SERVER_LC_FORCE)

        -> la_apply_statement_log()
           -> la_flush_repl_items(true)
              -> locator_repl_flush_all()
                 -> net_client_request_3_data(NET_SERVER_LC_FORCE)
           -> la_update_query_execute()
              -> db_execute()
                 -> net_client_request_with_callback(NET_SERVER_QM_QUERY_EXECUTE)

  -> la_log_commit()
     -> la_flush_repl_items(true)
        -> locator_repl_flush_all()
           -> net_client_request_3_data(NET_SERVER_LC_FORCE)
     -> la_update_ha_last_applied_info()
        -> db_execute_with_values()
           -> net_client_request_with_callback(NET_SERVER_QM_QUERY_EXECUTE)
     -> la_commit_transaction()
        -> db_commit_transaction()
           -> net_client_request(NET_SERVER_TM_SERVER_COMMIT)
```

### 변수 정리

**전체 리스트**

- src/transaction/log_applier.c
    - LA_INFO la_Info
        - applylogdb의 핵심 전역 상태 구조체
        - 로그 읽기 위치, transaction registry, flush/commit 상태, apply 통계, log header 상태 등을 한 곳에 모아 관리한다.
    - LA_RECDES_POOL la_recdes_pool
        - row replication 처리 시 RECDES를 재사용하기 위한 풀
        - insert/update item을 decode할 때 record buffer를 반복 할당하지 않도록 한다.
    - la_applier_need_shutdown
        - applylog 전체 종료 요청 플래그
        - 메인 루프, 에러 경로, signal 처리에서 종료 여부를 판단할 때 사용된다.
    - la_applier_shutdown_by_signal
        - signal에 의해 종료되었는지 나타내는 상태 플래그
        - 종료 원인을 구분하기 위해 사용된다.
    - la_slave_db_name
        - apply 대상 slave DB 이름
        - 락 파일, 로그 파일 경로, 상태 메시지 등에 사용된다.
    - la_peer_host
        - peer host 식별 문자열
        - 상태 메시지나 HA 관련 로그 출력에 사용된다.
    - la_enable_sql_logging
        - SQL logging 활성화 여부
        - row/statement replication 처리 시 SQL log 파일 기록 여부를 제어한다.
- LA_INFO 내부 주요 항목
    - LSA/progress
        - final_lsa
            - 현재 읽고 처리 중인 로그 위치
            - LogReader의 실제 진행 포인터 역할을 한다.
        - committed_lsa
            - 마지막으로 commit 처리된 commit log LSA
            - apply progress의 전역 완료 기준으로 사용된다.
        - committed_rep_lsa
            - 마지막으로 반영 완료된 replication log LSA
            - row/statement replication item 반영 기준 위치를 나타낸다.
        - last_committed_lsa
            - applylog 시작 시점의 committed commit log LSA
            - 새로 처리한 transaction과 기존 완료 범위를 구분할 때 사용된다.
        - last_committed_rep_lsa
            - applylog 시작 시점의 committed replication log LSA
            - replication item 처리 시 기존 완료 범위와 비교하는 기준이다.
        - append_lsa
            - active log header의 append 위치
            - 아직 append되지 않은 영역을 읽지 않도록 판단하는 데 사용된다.
        - eof_lsa
            - active log header의 EOF 위치
            - 로그 끝 도달 여부 판단에 사용된다.
        - required_lsa
            - 아직 apply가 끝나지 않은 transaction 중 가장 이른 시작 위치
            - reclaim 가능 범위 계산의 기준이 된다.
    - transaction/item registry
        - repl_lists
            - transaction별 LA_APPLY 엔트리 배열
            - transaction 단위 apply 상태를 저장하는 핵심 registry 역할을 한다.
        - repl_cnt
            - repl_lists 배열 총 크기
            - registry capacity 관리용 메타데이터이다.
        - cur_repl
            - 현재 사용 중인 repl_lists 엔트리 개수 또는 인덱스
            - 새 transaction 등록 시 사용된다.
        - commit_head
            - commit queue의 head
            - commit log를 만난 transaction의 apply 대기 순서를 관리한다.
        - commit_tail
            - commit queue의 tail
            - 새 commit 엔트리를 뒤에 붙일 때 사용된다.
    - apply counters / apply info
        - total_rows
            - apply된 전체 row 수 누적값
            - commit 판단 및 통계 출력에 사용된다.
        - prev_total_rows
            - 이전 commit/check 시점의 row 수
            - 변화량 계산에 사용된다.
        - log_record_time
            - 마지막 commit log record의 시각
            - delay 계산과 adaptive commit interval 조정에 사용된다.
        - insert_counter
            - insert 적용 건수 누적값
        - update_counter
            - update 적용 건수 누적값
        - delete_counter
            - delete 적용 건수 누적값
        - schema_counter
            - schema/DDL 관련 적용 건수 누적값
        - commit_counter
            - commit 처리 건수 누적값
        - fail_counter
            - apply 실패 건수 누적값
        - log_commit_time
            - 마지막 로그 commit 반영 시각
            - _db_ha_apply_info 갱신 시 사용된다.
        - status
            - applylog의 busy/idle 상태
            - _db_ha_apply_info.status에 반영되는 상태값이다.
        - is_apply_info_updated
            - _db_ha_apply_info가 부분적으로 갱신되었는지 여부
            - 추가 commit/update가 필요한지 판단하는 플래그이다.
        - num_unflushed
            - 아직 flush되지 않은 replication object 수
            - flush threshold 판단에 사용된다.
    - log/page/cache/decode
        - act_log
            - active log 파일 정보
            - 경로, file descriptor, header page, page size 등을 포함한다.
        - arv_log
            - archive log 파일 정보
            - archive 번호, 파일 descriptor, header 등을 관리한다.
        - cache_pb
            - log page cache
            - 읽은 로그 페이지를 캐싱해 반복 접근 비용을 줄인다.
        - log_data
            - 로그 페이지 읽기용 임시 buffer
            - archive/active log fetch 과정에서 사용된다.
        - rec_type
            - record type decode용 임시 buffer
            - RECDES type 복원 시 사용된다.
        - undo_unzip_ptr
            - undo log unzip buffer
            - 압축된 undo image 해제에 사용된다.
        - redo_unzip_ptr
            - redo log unzip buffer
            - 압축된 redo image 해제에 사용된다.
    - file/lock/state
        - log_path_lockf_vdes
            - log path에 대한 파일 락 descriptor
            - applylog 중복 실행 방지에 사용된다.
        - db_lockf_vdes
            - DB name lock descriptor
            - slave DB에 대한 apply ownership 제어에 사용된다.
        - apply_state
            - applylog 상태값
            - WORKING, DONE, RECOVERING 등의 상태 전이에 사용된다.
        - last_server_state
            - 마지막으로 관찰한 master HA state
            - 상태 변화 감지에 사용된다.
        - is_end_of_record
            - 현재 읽은 위치가 end-of-record에 도달했는지 표시
            - log page 재fetch나 상태 전이에 사용된다.
        - is_role_changed
            - HA role 변화 감지 플래그
            - role change 시 락 해제/상태 변경에 사용된다.
- src/object/work_space.c
    - ws_Repl_objs
        - row replication object를 flush 전에 임시로 저장하는 전역 리스트
        - ws_add_to_repl_obj_list()로 추가되고, locator_repl_flush_all()에서 소비된다.
    - ws_Repl_error_link
        - flush 중 발생한 object별 오류를 저장하는 전역 링크드 리스트
        - 부분 flush 실패 시 에러 복구/로그 출력에 사용된다.
- src/transaction/locator_cl.c
    - LOCATOR_MFLUSH_CACHE
        - flush 시점에 replication object를 서버 전송용 copy area로 패킹하는 임시 구조체
        - locator_repl_flush_all() 내부에서 생성되고, locator_repl_mflush()/locator_repl_mflush_force()에서 사용된다.
        - 지속 상태가 아니라 flush 단위의 일시적 버퍼이다.
- 함수 내부 static
    - la_cache_buffer_replace(): static unsigned int last
        - page buffer replacement를 위한 마지막 선택 위치
        - cache replacement cursor 역할을 한다.
    - la_apply_repl_log(): static unsigned int total_repl_items
        - 지금까지 처리한 replication item 수 누적값
        - 일정 건수마다 page buffer release 여부를 결정하는 데 사용된다.
    - la_commit_transaction(): static int last_time
        - 마지막 ws cull 시각
        - workspace 정리 주기 계산에 사용된다.
    - la_commit_transaction(): static unsigned long long last_applied_item
        - 마지막 ws cull 시점의 처리 건수
        - workspace 정리 주기 계산에 사용된다.
    - la_check_time_commit(): static int ha_mode
        - HA mode parameter cache
        - 반복 parameter 조회를 줄이기 위한 내부 캐시이다.
    - la_init(): static unsigned long start_vsize
        - 시작 시 메모리 사용량 기준값
        - 메모리 증가량 판단 기준으로 사용된다.
    - la_get_adaptive_time_commit_interval(): static int delay_hist_idx
        - delay history ring buffer 인덱스
        - adaptive commit interval 계산에 사용된다.
    - la_delay_replica(): static int ha_mode
        - replica delay 처리용 HA mode cache
    - la_delay_replica(): static int replica_delay
        - replica delay 값 cache
    - la_delay_replica(): static time_t replica_time_bound
        - replica time bound 값 cache

## TODO

- 파일 동시 접근 시 I/O 병목이 발생할 수 있음
- 캐시 & 버퍼에있는 페이지를 참조할 때 lock이 필요할 수 있음
