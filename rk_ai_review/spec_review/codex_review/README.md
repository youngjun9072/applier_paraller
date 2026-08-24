# Codex 스펙 리뷰 문서 안내

## 목적에 따라 먼저 볼 문서

코드를 보기 전에 이 피처가 무엇을 하려는지와 스펙 자체의 문제를 파악하려면 다음 문서만 읽으면 된다.

- [CONCEPT_VALIDITY_REVIEW.md](reports/CONCEPT_VALIDITY_REVIEW.md) — **코드 비참조 컨셉 리뷰 완결본**

이 문서는 기능 배경과 제안 동작을 먼저 설명한 뒤, 691개 raw 의견을 30개 주제로 종합해 실패 시나리오·필요한 정책 결정·수용 기준까지 풀어서 설명한다. 현재 코드가 처리한다는 이유로 컨셉 쟁점을 제거하지 않았다.

실제 CUBRID 기능 브랜치 코드와 대조한 구현 상태의 **최종 필터링본**은 다음 문서다.

- [CUBRID_FIT_FILTER_FEATURE.md](reports/CUBRID_FIT_FILTER_FEATURE.md)

이 문서는 CF-01~CF-30의 코드 근거와 확정·기각·폐기·판정불가·코드무관 판정을 확인할 때 사용한다.

- 확정: 12건
- 기각: 4건
- 폐기: 4건
- 판정불가: 1건
- 코드무관: 9건

`reports/CUBRID_FIT_FILTER.md`는 기능 구현 전 `develop`만 대조했던 과거 기록이므로 최종 판정에
사용하지 않는다.

## 권장 읽기 순서

1. [CONCEPT_VALIDITY_REVIEW.md](reports/CONCEPT_VALIDITY_REVIEW.md) — 기능 의도와 코드 비참조 컨셉 문제 완결본
2. [CUBRID_FIT_FILTER_FEATURE.md](reports/CUBRID_FIT_FILTER_FEATURE.md) — 현재 구현과 대조한 최종 필터링 판정
3. [CONSOLIDATED_FINDINGS.md](reports/CONSOLIDATED_FINDINGS.md) — 정확한 raw ID와 원래 CF 통합 기록 감사
4. 필요에 따라 권고안, 테스트, 미결 질문과 raw 문서를 확인

컨셉 타당성과 스펙 누락을 알고 싶으면 1번만, 현재 코드가 어디까지 처리하는지도 알고 싶으면 1번과 2번을 이어서 읽는다.

## 파일별 역할

### 루트 문서

| 파일 | 역할 | 사용 시점 |
|---|---|---|
| [README.md](README.md) | 문서 지도와 읽는 순서 | 처음 들어왔을 때 |
| [REVIEW_INSTRUCTIONS.md](REVIEW_INSTRUCTIONS.md) | 최초 스펙 리뷰 범위, 방법, 산출물 규칙 | 리뷰가 어떻게 수행됐는지 확인할 때 |
| [FILTERING_INSTRUCTIONS.md](FILTERING_INSTRUCTIONS.md) | 기능 브랜치·LSP·판정 기준 등 필터링 작업 기록 | 최종 판정 방법을 감사할 때 |

### reports 문서

| 파일 | 상태 | 역할 |
|---|---|---|
| [CONCEPT_VALIDITY_REVIEW.md](reports/CONCEPT_VALIDITY_REVIEW.md) | **컨셉 리뷰 완결본** | 코드 상태와 분리해 기능 목적부터 691개 raw 의견의 30개 통합 쟁점까지 독립적으로 설명 |
| [CUBRID_FIT_FILTER_FEATURE.md](reports/CUBRID_FIT_FILTER_FEATURE.md) | **최신·최종** | 기능 브랜치 `feature/CBRD-26246-develop` 기준 CF-01~CF-30 최종 판정과 코드 근거 |
| [CUBRID_FIT_FILTER.md](reports/CUBRID_FIT_FILTER.md) | **과거 이력** | 기능 코드를 보기 전 local develop만 기준으로 작성한 초기 필터링. 최종 판정용이 아님 |
| [REVIEW_SUMMARY.md](reports/REVIEW_SUMMARY.md) | 원본 리뷰 요약 | 최초 스펙 리뷰의 주요 결론, 심각도와 권고 방향 |
| [CONSOLIDATED_FINDINGS.md](reports/CONSOLIDATED_FINDINGS.md) | 원본 통합본 | 여러 리뷰 관점을 CF-01~CF-30으로 병합한 상세 문제 제기. 원문 보존용 |
| [RECOMMENDED_SPEC_CHANGES.md](reports/RECOMMENDED_SPEC_CHANGES.md) | 개정 제안 | 스펙에 추가·수정할 문구와 정책 제안. 최종 필터 판정과 함께 사용 |
| [TEST_SCENARIOS.md](reports/TEST_SCENARIOS.md) | 테스트 설계 | 스펙과 구현을 검증하기 위한 SQL·HA·장애 시나리오 |
| [OPEN_QUESTIONS.md](reports/OPEN_QUESTIONS.md) | 미결정 사항 | 코드만으로 결정할 수 없는 제품·운영·정책 질문 |
| [RAW_REVIEW_AUDIT.md](reports/RAW_REVIEW_AUDIT.md) | 감사 기록 | 원시 리뷰가 누락 없이 통합됐는지 확인한 추적성 자료 |

## 최신본과 이력 구분

```text
최초 스펙 리뷰
  └─ CONSOLIDATED_FINDINGS.md (CF-01~CF-30 원문)
       ├─ CONCEPT_VALIDITY_REVIEW.md (코드 비참조·사람이 독립적으로 읽는 완결본)
       ├─ REVIEW_SUMMARY.md
       ├─ RECOMMENDED_SPEC_CHANGES.md
       ├─ TEST_SCENARIOS.md
       └─ OPEN_QUESTIONS.md

코드 대조 필터링
  ├─ CUBRID_FIT_FILTER.md          (develop-only 과거 이력)
  └─ CUBRID_FIT_FILTER_FEATURE.md  (기능 브랜치 기준 최종본)
```

필터링 과정에서도 원래 스펙 리뷰 내용은 삭제하지 않았다. CUBRID에 맞지 않거나 코드 결함이 아닌
내용은 최종 필터링본에서 `기각`, `폐기`, `코드무관` 등으로 표시해 이력을 보존한다.
