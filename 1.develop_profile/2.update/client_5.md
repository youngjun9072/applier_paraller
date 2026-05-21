# Develop Profile — UPDATE / Client 5

방식: prepare-execute 1 (autocommit off → prepare → start time → execute → end time → commit)

---

## Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl4 | 03:16:07.611 PM | 03:16:57.618 PM | 50.007 |
| tbl3 | 03:16:07.615 PM | 03:16:57.168 PM | 49.553 |
| tbl5 | 03:16:07.630 PM | 03:16:56.813 PM | 49.183 |
| tbl1 | 03:16:07.639 PM | 03:16:57.618 PM | 49.979 |
| tbl2 | 03:16:07.652 PM | 03:16:56.492 PM | 48.840 |

## Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl2 | 03:16:56.566 PM | 03:16:59.911 PM | 3.345 |
| tbl5 | 03:16:59.919 PM | 03:17:02.793 PM | 2.874 |
| tbl3 | 03:17:02.802 PM | 03:17:05.742 PM | 2.940 |
| tbl1 | 03:17:05.750 PM | 03:17:11.594 PM | 5.844 |
| tbl4 | 03:17:08.687 PM | 03:17:11.594 PM | 2.907 |

---

## 종합 지표

| 지표 | 값 |
|---|---|
| 마스터 최빠 시작 | 03:16:07.611 PM (tbl4) |
| 마스터 최늦 종료 | 03:16:57.618 PM (tbl4, tbl1) |
| 마스터 전체 수행 시간 | 50.007 s |
| 슬레이브 최빠 시작 | 03:16:56.566 PM (tbl2) |
| 슬레이브 최늦 종료 | 03:17:11.594 PM (tbl1, tbl4) |
| 슬레이브 전체 수행 시간 | 15.028 s |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 1.052 |
| Master end → Slave end   | 13.976 |
