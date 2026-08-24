# Develop Profile — INSERT / Client 5

방식: prepare-execute 1 (autocommit off → prepare → start time → execute → end time → commit)

---

## Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl5 | 03:15:09.726 PM | 03:15:50.648 PM | 40.922 |
| tbl3 | 03:15:09.727 PM | 03:15:51.641 PM | 41.914 |
| tbl4 | 03:15:09.728 PM | 03:15:51.543 PM | 41.815 |
| tbl2 | 03:15:09.730 PM | 03:15:50.706 PM | 40.976 |
| tbl1 | 03:15:09.730 PM | 03:15:52.017 PM | 42.287 |

## Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl5 | 03:15:50.737 PM | 03:15:58.039 PM | 7.302 |
| tbl2 | 03:15:53.543 PM | 03:15:58.074 PM | 4.531 |
| tbl4 | 03:15:58.086 PM | 03:16:05.094 PM | 7.008 |
| tbl3 | 03:16:02.528 PM | 03:16:05.095 PM | 2.567 |
| tbl1 | 03:16:05.107 PM | 03:16:07.454 PM | 2.347 |

---

## 종합 지표

| 지표 | 값 |
|---|---|
| 마스터 최빠 시작 | 03:15:09.726 PM (tbl5) |
| 마스터 최늦 종료 | 03:15:52.017 PM (tbl1) |
| 마스터 전체 수행 시간 | 42.291 s |
| 슬레이브 최빠 시작 | 03:15:50.737 PM (tbl5) |
| 슬레이브 최늦 종료 | 03:16:07.454 PM (tbl1) |
| 슬레이브 전체 수행 시간 | 16.717 s |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 1.280 |
| Master end → Slave end   | 15.437 |
