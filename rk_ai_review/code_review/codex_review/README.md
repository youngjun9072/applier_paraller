# CBRD-26246 코드 리뷰 문서 안내

## 팀 공유 묶음

팀에는 아래 두 파일만 공유하면 된다.

1. **[CODEX_CODE_REVIEW_FINAL.md](CODEX_CODE_REVIEW_FINAL.md)** — 실제 리뷰 본문
2. **이 README** — 문서 범위 안내

`작업지시.md`와 `reports/` 전체는 재검증·이력 추적용 내부 자료다. 팀원이 finding의 판정 근거를
감사하거나 재현 테스트를 작성할 때만 전달한다.

## 파일별 역할

| 파일 | 역할 | 읽는 경우 |
|---|---|---|
| `CODEX_CODE_REVIEW_FINAL.md` | 독립형 최종 코드 리뷰 | 항상 먼저 읽음 |
| `작업지시.md` | 대상 branch, 페르소나, LSP, 필터링·보존 규칙 | 내부 감사용, 일반 공유 제외 |
| `reports/E2E_FINDING_WORKSHEETS.md` | 후보별 최소 입력과 master/log/applier/slave 상세 | 특정 finding을 재현·테스트할 때 |
| `reports/CANDIDATE_AUDIT.md` | 확정/조건부/develop 기존/기각 수량과 근거 | 왜 16건이 10건으로 바뀌었는지 확인할 때 |
| `reports/RAW_187_REAUDIT_MAP.md` | 기존 187개 관찰의 최신 판정 색인 | raw 의견의 정정 상태를 찾을 때 |
| `reports/PR_HISTORY.md` | 관련 closed PR과 후속 해결 이력 | 설계·리뷰 암묵지를 확인할 때 |
| `reports/RAW_FULL_REAUDIT.md` | 세션 재개 체크포인트, 35개 파일 coverage | 조사 진행과 삼자 비교를 감사할 때 |
| `reports/<페르소나>_<연차>.md` | 20개 관점의 최초 raw 의견 | 직군별 영향 원문이 필요할 때 |

개별 페르소나 문서는 최초 의견을 보존하므로 본문에 오분석된 설명도 남아 있다. 각 파일 첫머리의
2026-08-24 재감사 알림과 `RAW_187_REAUDIT_MAP.md` 판정을 우선한다.
