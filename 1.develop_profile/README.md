# Develop Profile

병렬화 적용 이전(`develop` 브랜치) 기준선(baseline) 측정 결과.
연산(INSERT / UPDATE) × 클라이언트 수(1 / 5 / 10 / 20)로 분류해 저장한다.

기본 측정 방식: **prepare-execute 1** (autocommit off → prepare → start time → execute → end time → commit).
1 클라이언트만 4가지 변형(normal / prepare-execute 1 / prepare-execute 2 / INSERT…SELECT) 포함.

---

## INSERT

| Client 수 | 파일 |
|---|---|
| 1  | [1.insert/client_1.md](1.insert/client_1.md) |
| 5  | [1.insert/client_5.md](1.insert/client_5.md) |
| 10 | [1.insert/client_10.md](1.insert/client_10.md) |
| 20 | [1.insert/client_20.md](1.insert/client_20.md) |

## UPDATE

| Client 수 | 파일 |
|---|---|
| 1  | [2.update/client_1.md](2.update/client_1.md) |
| 5  | [2.update/client_5.md](2.update/client_5.md) |
| 10 | [2.update/client_10.md](2.update/client_10.md) |
| 20 | [2.update/client_20.md](2.update/client_20.md) |

---

## 10-client 재실험 (new)

| 워크로드 | 파일 |
|---|---|
| INSERT | [3.new_client10_insert/result.md](3.new_client10_insert/result.md) |
| UPDATE | [4.new_client10_update/result.md](4.new_client10_update/result.md) |

### 재실험 사유

이전 10-client 측정(`1.insert/client_10.md`, `2.update/client_10.md`)은 다음 순서로 시간이 측정되어 **duration 안에 commit 시간이 포함**되고, 직후 **불필요한 두 번째 commit** 까지 수행하고 있었음.

```sql
-- Before: 이전 develop 측정
SELECT SYSDATETIME();              -- 시작 타임스탬프

INSERT INTO tbl VALUES (1, ...);
INSERT INTO tbl VALUES (2, ...);
...
INSERT INTO tbl VALUES (100000, ...);

COMMIT;                            -- 1차 커밋
SELECT SYSDATETIME();              -- 종료 타임스탬프 (commit 뒤)
COMMIT;                            -- 2차 커밋 (중복)
```

병렬화 빌드(`6.parallelization_profile/`)는 **prepare-execute 1** 방식(autocommit off → prepare → **start** → execute → **end** → commit)으로 측정되어 정의가 어긋났음. 동일한 정의로 비교하기 위해 develop 쪽 10-client 만 동일 방식으로 재실험.

```sql
-- After: new_client10_*/result.md
;autocommit off

SELECT SYSDATETIME();              -- 시작 타임스탬프

INSERT INTO tbl VALUES (1, ...);
INSERT INTO tbl VALUES (2, ...);
...
INSERT INTO tbl VALUES (100000, ...);

SELECT SYSDATETIME();              -- 종료 타임스탬프 (commit 직전)
COMMIT;                            -- 1회
```

---

## 요약 (TODO)

연산별·클라이언트 수별 마스터 / 슬레이브 수행시간과 시작·종료 딜레이를 한 표로 정리 예정.
