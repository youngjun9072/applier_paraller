# Worker 1 (활성화 워커 1개) — perf 측정 결과

- **활성화 워커: 1 / 비활성화 워커: 9** (활성 워커는 `worker_id = 2`)
- 빌드 모드: Release / 부하 도구: csql
- 워크로드: tbl1 ~ tbl10, 각 10만 건 Insert / 단일 트랜잭션
- 측정 대상: 슬레이브 노드 applier (활성 워커의 함수 호출 시간)

---

## 함수 호출 트리 (호출 깊이 순)

| 단계 (호출 깊이 순) | 호출 수 | 누적 시간 | avg / call | 모함수 안 비중 |
|----|----|----|----|----|
| `la_flush_repl_items` (worker entry) | 100,011 | 3.335 s | 33.3 µs | — |
| └ `locator_repl_mflush_force` | 17,001 | 3.186 s | 187.4 µs | 95.5 % of la_flush |
| &nbsp;&nbsp;└ `locator_repl_force` | 17,001 | 3.151 s | 185.3 µs | 98.9 % of mflush |
| &nbsp;&nbsp;&nbsp;&nbsp;└ `net_client_request_3_data_recv_copyarea` | 17,001 | 3.108 s | 182.8 µs | 98.7 % of force |
| &nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;└ `css_send_req_to_server_2_data` | 17,009 | 0.169 s | 9.9 µs | 5.4 % of recv |

---

## 관찰

- `la_flush_repl_items` 전체 누적 3.335s 중 약 **95.5%가 `locator_repl_mflush_force`** 에서 소비.
- 그 내부 `locator_repl_force` → `net_client_request_…recv_copyarea` 까지 누적 비중이 거의 100%에 가까움.
- 반면 실제 송신(`css_send_req_to_server_2_data`)은 0.169s로 매우 작음 → **시간 대부분이 슬레이브 측 응답 대기(recv)** 에 머물러 있음을 시사.
