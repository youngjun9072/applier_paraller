# Develop Profile — UPDATE / Client 1

`develop` 브랜치(병렬화 미적용) 단일 클라이언트 UPDATE 측정 결과. 3가지 SQL 작성 방식별로 기록 (UPDATE에는 INSERT…SELECT 변형 없음).

---

## 1. 일반 (normal)

> prepare-execute 와의 비교 기준이 되는 일반 쿼리문. 단순 비교 기록용.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 07:11:35.310 AM | 07:12:16.167 AM | 40.857 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 07:12:16.501 AM | 07:12:19.101 AM | 2.600 |

---

## 2. prepare-execute 1

> autocommit off → prepare → start time → execute → end time → commit. 이후 클라이언트 증가 실험의 기본 방식.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:59:32.861 PM | 03:00:14.586 PM | 41.725 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 03:00:14.724 PM | 03:00:17.598 PM | 2.874 |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 0.138 |
| Master end → Slave end   | 3.012 |

---

## 3. prepare-execute 2

> autocommit off → prepare → commit → start time → execute → end time → commit. prepare 후 commit이 영향을 주는지 확인용.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:22:19.183 PM | 02:23:00.626 PM | 41.443 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:23:00.766 PM | 02:23:03.360 PM | 2.594 |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 0.140 |
| Master end → Slave end   | 2.734 |
