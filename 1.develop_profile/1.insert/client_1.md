# Develop Profile — INSERT / Client 1

`develop` 브랜치(병렬화 미적용) 단일 클라이언트 INSERT 측정 결과. 4가지 SQL 작성 방식별로 기록.

---

## 1. 일반 (normal)

> prepare-execute 와의 비교 기준이 되는 일반 쿼리문. 단순 비교 기록용.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 07:10:56.541 AM | 07:11:31.834 AM | 35.293 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 07:11:32.194 AM | 07:11:34.384 AM | 2.190 |

---

## 2. prepare-execute 1

> autocommit off → prepare → start time → execute → end time → commit. 이후 클라이언트 증가 실험의 기본 방식.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:58:55.380 PM | 02:59:30.082 PM | 34.702 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:59:30.239 PM | 02:59:32.737 PM | 2.498 |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 0.157 |
| Master end → Slave end   | 2.655 |

---

## 3. prepare-execute 2

> autocommit off → prepare → commit → start time → execute → end time → commit. prepare 후 commit이 영향을 주는지 확인용.

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:21:37.641 PM | 02:22:16.497 PM | 38.856 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:22:16.582 PM | 02:22:19.126 PM | 2.544 |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 0.085 |
| Master end → Slave end   | 2.544 |

---

## 4. INSERT … SELECT

### Master

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:23:03.694 PM | 02:23:05.534 PM | 1.840 |

### Slave

| Table | Start | End | Duration (s) |
|---|---|---|---|
| tbl1 | 02:23:05.860 PM | 02:23:08.973 PM | 3.113 |

### 딜레이

| 구간 | 값 (s) |
|---|---|
| Master end → Slave start | 0.326 |
| Master end → Slave end   | 3.439 |
