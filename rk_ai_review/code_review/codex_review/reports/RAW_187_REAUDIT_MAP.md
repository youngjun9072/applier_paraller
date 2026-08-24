# 기존 187개 관찰 전수 재감사 매핑

이 문서는 기존 20개 페르소나 보고서의 187개 관찰을 삭제하지 않으면서, E2E 재검증 결과가 무엇으로
바뀌었는지 찾기 위한 색인이다. 187은 독립 결함 수가 아니라 같은 코드가 직군·경력별 영향으로 반복된
관찰 수다. 원문은 각 페르소나 파일에 그대로 남기고 최종 판정은 아래 root-cause 축으로 연결한다.

## 전수 범위와 종료 기록

| 직군 | 1년차 | 3년차 | 5년차 | 10년차 | 합계 | 재탐색 종료 |
|---|---:|---:|---:|---:|---:|---|
| PM | 10 | 10 | 9 | 9 | 38 | 최대 50건 전에 실행 근거 있는 독립 후보 소진 — 더 이상 발견되지 않음 |
| DB 엔지니어 | 10 | 10 | 9 | 10 | 39 | 최대 50건 전에 운영 상태 전이 후보 소진 — 더 이상 발견되지 않음 |
| 사용자 | 8 | 8 | 8 | 7 | 31 | 최대 50건 전에 사용자 재현 가능 후보 소진 — 더 이상 발견되지 않음 |
| 응용 개발자 | 8 | 9 | 8 | 9 | 34 | 최대 50건 전에 SQL/API 경계 후보 소진 — 더 이상 발견되지 않음 |
| DB 엔진 개발자 | 10 | 12 | 10 | 13 | 45 | 최대 50건 전에 35개 diff hunk·caller/callee 후보 소진 — 더 이상 발견되지 않음 |
| 합계 | 46 | 49 | 44 | 48 | **187** | 페르소나당 50은 탐색 상한이며 발견 수를 채우기 위한 목표가 아님 |

## E2E 재감사 뒤 root-cause 상태

| 매핑 축 | 기존 raw에서 반복된 관점 | 재감사 상태 | 최종 취급 |
|---|---|---|---|
| CR-02 | composite UK, rkcheck 통과, DML/apply 불일치 | master runtime에서 log 자체가 없음을 확인 | 확정 High; 실행 설명 정정 |
| CR-03 | reverse UNIQUE | client/server type 집합 불일치 확인 | 확정 High |
| CR-04 | filtered/function/online UNIQUE | filtered INSERT/DELETE 무로그와 UPDATE invalid lookup 확인; function은 별도 입증 안 됨 | filtered/status만 확정 High, function 일반화 제외 |
| CR-05 | source/applier first candidate | payload identity 부재는 사실이나 node order divergence의 도달 가능한 최소 상태 미입증 | 입증 보류; 최종 확정 수에서 제외 |
| CR-06 | multi ALTER | 현재 clause 대신 head code 사용 확인 | 확정 High |
| CR-07 | CHANGE/MODIFY/DROP coverage | standalone DROP INDEX 무검사 경로까지 확인 | 확정 High |
| CR-08 | partition promotion | runtime constraint가 property에서 복원되어 독립 실패 경로 없음 | 오분석/CR-02 종속; 삭제하지 않고 표시 |
| CR-09 | mixed ON/OFF write target SBR | ANY-ON 뒤 SQL 전체 replay 확인 | 확정 High |
| CR-10 | OFF read source SBR | node-local source 재평가 확인 | 확정 High |
| CR-11 | OFF TRUNCATE | RK만 검사하고 ON/OFF 미검사 확인 | 확정 High |
| CR-12 | partial HA start | rollback 부재 확인, 동일 구조는 develop에도 존재 | develop 기존/feature 악화로 보존 |
| CR-13 | failover/failback/restart readiness | 단순 rkcheck 부재 주장은 기각; CR-06/07→무로그→applier done→promotion 연쇄만 성립 | 선행 결함 의존 조건부 High |
| CR-14 | rkcheck fopen | NULL stream 사용 확인 | 확정 High |
| CR-15 | FK diagnostic PK NULL | 정상 DDL에서는 불가, 손상·legacy catalog에서 가능 | 조건부 Medium |
| CR-16 | helper 교체 | 사용자 지시에 따라 교체 완료를 가정 | 최종 문서에서 제외 |
| CR-17 | public error constant | 설치되는 `error_code.h`를 public headers가 include | 오분석; 삭제하지 않고 표시 |
| NEW-001 | VCLASS flag | ALTER metadata만 허용, row failure 없음 | 정책/품질 |
| NEW-002/003 | restart/failback | 정상 catalog 대조 조건과 기존 fencing 존재 | CR-13에 병합 |
| NEW-004 | rkcheck 결과 덮어쓰기 | 분 단위 이름+`w` 확인 | 운영 권고 Low |
| NEW-005 | 잘못 남은 prototype | runtime caller 없음 | 품질 정리 |
| NEW-006 | stale backup start self-block | 가능한 조건이나 공식 rejoin/readiness 계약 확인 필요 | 정책/조건부 |
| NEW-007 | OFF child cascade | slave cascade가 실행되어 정합성 유지 | 정책 의미 확인 |
| NEW-008 | OFF class 반복 fetch | 현재 HEAD에도 helper가 후보 loop 안에 있음 | Low 성능 후보 |

## 기존 raw를 읽을 때 반드시 적용할 정정

1. `client와 applier가 다른 RK를 골라 CR-02가 발생한다`는 문장은 폐기한다. applier는 호출되지 않는다.
2. CR-05의 “두 노드 index order가 다르다”는 예시는 재현 전제가 입증되지 않았으므로 확정 사실이 아니다.
3. CR-08 partition metadata 손상 주장은 독립 결함으로 사용하지 않는다.
4. CR-12를 feature에만 새로 생긴 rollback 결함이라고 쓰지 않는다. develop 기존 구조를 feature가 악화했다.
5. CR-13을 `promotion에 rkcheck가 없다` 한 문장으로 설명하지 않는다. 선행 invalid DDL과 무로그 DML이
   모두 필요하다.
6. CR-16은 사용자 가정에 따라 제거한다.
7. CR-17은 public API 누락이 아니므로 오분석이다.
8. #7697은 error propagation을 해결했지만 OFF class의 후보별 반복 fetch까지 해결하지 않았다.

## 상세 증거 연결

- 확정·조건부 후보의 최소 입력과 실행 순서: [E2E_FINDING_WORKSHEETS.md](E2E_FINDING_WORKSHEETS.md)
- 공통 조상/develop/feature 비교와 진행 기록: [RAW_FULL_REAUDIT.md](RAW_FULL_REAUDIT.md)
- PR별 도입·후속 해결 정보: [PR_HISTORY.md](PR_HISTORY.md)
- 최종 채택/비채택 집계: [CANDIDATE_AUDIT.md](CANDIDATE_AUDIT.md)에 반영 완료했다.
