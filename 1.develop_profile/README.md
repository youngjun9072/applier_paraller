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

## 요약 (TODO)

연산별·클라이언트 수별 마스터 / 슬레이브 수행시간과 시작·종료 딜레이를 한 표로 정리 예정.
