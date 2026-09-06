# CUBRID 기능 구현 적합성 기반 스펙 필터링 작업 기록

- 작성일: 2026-08-23
- 리뷰 대상: 새로 추가할 HA 복제 키 기능의 사용자 스펙과 기존 스펙 리뷰
- 구현 근거 저장소: `/home/youngjun/Workspace/cubrid-cbrd26246`
- 기준 브랜치: `feature/CBRD-26246-develop`
- 검토 대상: `reports/CONSOLIDATED_FINDINGS.md`의 CF-01~CF-30
- 보존 원칙: 기존 스펙 리뷰와 원시 리뷰는 삭제하거나 덮어쓰지 않는다.

## 목적

이 작업은 코드 리뷰가 아니다. 코드 확인 전에 작성된 새 기능 스펙 리뷰를 현재 CUBRID 구현과 대조해, CUBRID가 지원하지 않는 기능이나 다른 내부 구조를 전제로 한 내용을 걸러내는 스펙 리뷰 후속 단계다. 부적합 내용도 삭제하지 않고 `CUBRID 비적용`으로 표시하며, 핵심 위험은 맞지만 용어나 해결책이 다르면 `표현 수정 후 유지`로 표시한다.

## 사용한 개발자 페르소나

- DBMS 엔진 개발자: HA log applier, transaction log, catalog/DDL, parser, recovery 및 객체 기능 범위
- DB 사용 애플리케이션 개발자: SQL/metadata 표면, CCI/JDBC, dump/load와 도구 호환성

PM, DBA, 최종 사용자 페르소나는 이번 스펙 적합성 판정에 사용하지 않는다. 기존에 그 관점으로 작성된 내용은 보존하고 개발자 관점에서 CUBRID 구현 근거를 추가한다.

## 기준 ref 기록

- 기능 브랜치 HEAD: `44468ed7329c3898b509af890c24b1c79091c589`
- develop 기준: `23789cbfa78087a9edaae126b605495525b4d40d`
- 핵심 기능 commit: `8bb304290` (`[CBRD-26246] Add HA replication option support`)
- 후속 수정: `44468ed73` (`[CBRD-26589] SBR 로그 복제 버그 수정 및 checksumdb 수정`)
- 별도 worktree: `/home/youngjun/Workspace/cubrid-cbrd26246`

기존 `/home/youngjun/Workspace/cubrid`의 develop 작업 트리는 건드리지 않는다. 이전 develop-only 판정은 `reports/CUBRID_FIT_FILTER.md`에 이력으로 보존하고, 최종 기능 대조 결과는 `reports/CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md`에 기록한다.

## LSP 사용

- `/usr/bin/clangd` 20.1.8
- 저장소 루트 `compile_commands.json`은 `build_preset_debug/compile_commands.json`을 가리킨다.
- 컴파일 DB는 1,186개 항목이며 2026-08-23 확인 시 1,179개 소스 경로가 유효하다.
- feature worktree 경로로 source/include를 재지정한 compile DB를 사용한다. build directory와 생성 header는 develop debug build 기준이므로 LSP는 정의·참조 탐색 보조로 사용하고 최종 판정은 feature diff와 실제 source를 함께 확인한다.
- `src/base/object_representation_sr.c`의 SA_MODE/C++17 compile command 로딩과 AST 분석 시작을 확인했다. 대형 translation unit의 `clangd --check`는 45초 제한에서 종료했으며 표시된 오류는 macro 영역의 refactoring-tweak 충돌이었다.

검색으로 관련 심볼을 찾은 뒤 LSP가 사용하는 compile command와 실제 선언·호출 관계를 함께 확인한다. 기존 clangd 경고나 refactoring tweak 실패는 새 기능 스펙의 결함으로 집계하지 않는다.

## 판정 규칙

1. `확정`: 기능 코드도 해당 문제를 막지 못한다. 구현 결함 또는 확정된 스펙 개정 요구로 승격한다.
2. `기각`: 기능 코드가 이미 처리해 원래 전제가 성립하지 않는다.
3. `폐기`: 존재하지 않는 기능이나 다른 DBMS 구조를 전제로 해 CUBRID에 맞지 않는다. 원문은 이력으로 보존한다.
4. `판정불가`: 정적 분석만으로 결론을 낼 수 없어 구체적인 런타임 시험이 필요하다.
5. `코드무관`: 문서 모순, 운영 정책, 제품 범위 등 코드 대조로 확정할 성격이 아니다.

심각도는 기존 값을 자동 승계하지 않는다. CUBRID 적합성 판정 뒤 필요한 경우 별도로 재평가한다.

## 산출 방식

최종 결과는 `reports/CODEX_SPEC_REVIEW_CUBRID_FIT_FILTER_FEATURE.md`에 CF-01부터 CF-30까지 기록한다. 각 항목은 원래 제목과 요지를 보존하고 다음을 포함한다.

- 판정
- CUBRID 구현 근거
- CUBRID에 맞게 유지하거나 수정할 스펙 리뷰 내용
- 비적용이면 비적용 이유와 재검토 조건
- 확인 한계
