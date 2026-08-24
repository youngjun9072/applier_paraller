# CBRD-26246 관련 PR 히스토리

- 확인일: 2026-08-24
- GitHub query: `repo:CUBRID/cubrid assignee:youngjun9072 is:closed`
- 최종 코드 기준: official `upstream/feature/CBRD-26246-develop` @ `9e094324b`
- 비교 기준: official `upstream/develop` @ `5b9c0d815`

## 결론

RK 기능은 하나의 develop PR에서 점진적으로 만들어진 것이 아니다. #6394~#6943은
`feature/add-replication-option`을 base로 병합된 내부 누적 이력이고, #7370이 이를 최신 develop 위에
squash한 `8bb304290`을 제안했다. #7370 자체는 **closed, unmerged**지만 그 commit은 현재 공식 feature에
존재한다. 그 뒤 #6908이 `3b6ebd1a9`, #7697이 `9e094324b`로 공식 feature에 추가됐다.

따라서 `develop`에 동일 문제가 있었는지를 판단할 때 옛 feature PR의 merged 표시는 develop 반영을
뜻하지 않는다. 최종 판정은 반드시 `upstream/develop...9e094324b` 실제 diff로 한다.

2026-08-24에 GitHub의 동일 closed-PR query를 다시 열어 상태를 재확인했다. 목록에는 #7697과 #6908이
merged, #7370이 closed로 표시되며, 로컬 공식 remote의 feature HEAD도 각각의 결과 commit
`9e094324b`, `3b6ebd1a9`, `8bb304290`을 순서대로 포함한다. 따라서 아래 이력은 세션 중단 전 캐시가
아니라 현재 GitHub 목록과 로컬 commit graph를 다시 대조한 결과다.

## 기능 누적 PR

| PR | 병합일 | base | 역할 |
|---|---|---|---|
| [#6394](https://github.com/CUBRID/cubrid/pull/6394) | 2025-09-14 | feature/add-replication-option | CREATE TABLE REPLICATION 옵션 |
| [#6454](https://github.com/CUBRID/cubrid/pull/6454) | 2025-09-22 | feature/add-replication-option | replication option 처리 |
| [#6467](https://github.com/CUBRID/cubrid/pull/6467) | 2025-10-14 | feature/add-replication-option | class flag 기반 DML 복제 |
| [#6477](https://github.com/CUBRID/cubrid/pull/6477) | 2025-10-21 | feature/add-replication-option | HA constraint 보완 |
| [#6505](https://github.com/CUBRID/cubrid/pull/6505) | 2025-11-03 | feature/add-replication-option | CREATE TABLE FK 검사 |
| [#6570](https://github.com/CUBRID/cubrid/pull/6570) | 2025-11-03 | feature/add-replication-option | unload/loaddb 옵션 왕복 |
| [#6618](https://github.com/CUBRID/cubrid/pull/6618) | 2025-11-11 | feature/add-replication-option | ALTER RK 제거 제약 |
| [#6637](https://github.com/CUBRID/cubrid/pull/6637) | 2025-12-02 | feature/add-replication-option | multi ALTER PK 교체 |
| [#6552](https://github.com/CUBRID/cubrid/pull/6552) | 2025-12-14 | feature/add-replication-option | partition 옵션 상속/승격 |
| [#6739](https://github.com/CUBRID/cubrid/pull/6739) | 2026-01-21 | feature/add-replication-option | RK 제거 버그 수정/리팩터링 |
| [#6658](https://github.com/CUBRID/cubrid/pull/6658) | 2026-01-22 | feature/add-replication-option | HA 시작 rkcheck |
| [#6798](https://github.com/CUBRID/cubrid/pull/6798) | 2026-01-26 | feature/add-replication-option | PK 전용 제약 제거/UK RK |
| [#6814](https://github.com/CUBRID/cubrid/pull/6814) | 2026-02-02 | feature/add-replication-option | minor fixes |
| [#6826](https://github.com/CUBRID/cubrid/pull/6826) | 2026-02-09 | feature/add-replication-option | TRUNCATE 처리 |
| [#6934](https://github.com/CUBRID/cubrid/pull/6934) | 2026-03-31 | feature/add-replication-option | rkcheck multi db-host |
| [#6943](https://github.com/CUBRID/cubrid/pull/6943) | 2026-04-01 | feature/add-replication-option | CREATE TABLE LIKE 상속 |
| [#6939](https://github.com/CUBRID/cubrid/pull/6939) | 2026-04-01 | feature/add-replication-option | rkcheck VCLASS 제외 |

## 통합 및 후속 PR

- [#7370](https://github.com/CUBRID/cubrid/pull/7370): develop 위 squash 통합. 2026-07-01 closed,
  unmerged. 본문은 RK/FK 검사, rkcheck, DML, partition, unload 등 위 티켓을 하나로 합쳤다고 명시한다.
- [#6908](https://github.com/CUBRID/cubrid/pull/6908): SBR 대상 판정과 checksumdb RBR 억제 보완.
  현재 feature의 `3b6ebd1a9`로 반영됐다.
- [#7697](https://github.com/CUBRID/cubrid/pull/7697): server-side loaddb interrupt에서 class flag fetch
  오류를 삼키거나 assert하던 문제를 오류전파 API로 교체. 현재 HEAD `9e094324b`다.
- [#7612](https://github.com/CUBRID/cubrid/pull/7612): log applier error buffer overflow 수정이며 develop에 병합된
  인접 이력이다. RK feature diff 자체의 finding으로 세지 않는다.

## 리뷰 discussion에서 확인된 암묵지

#7370 inline review는 다음을 이미 지적했지만 PR이 닫힐 때 해결되지 않았고 최신 HEAD에도 남아 있다.

- [`do_alter`가 multi-clause loop 안에서 head node를 검사](https://github.com/CUBRID/cubrid/pull/7370#discussion_r3503435072)
- [`rkcheck` 출력 파일 open 실패 뒤 NULL stream 사용](https://github.com/CUBRID/cubrid/pull/7370#discussion_r3503435009)
- [FK 진단의 `pk_c` NULL 역참조](https://github.com/CUBRID/cubrid/pull/7370#discussion_r3503434957)
- [class flag 값 32 하드코딩](https://github.com/CUBRID/cubrid/pull/7370#discussion_r3503435143)
- [DML index loop의 class record 반복 fetch](https://github.com/CUBRID/cubrid/pull/7370#discussion_r3503435281)

마지막 항목은 #7697에서 오류를 삼키지 않고 `heap_get_class_repl_on()`의 반환값을 전달하도록 바뀌었지만,
현재 HEAD에서도 helper 호출은 RK 후보 loop 안에 있다. 따라서 **interrupt/error propagation 문제는
후속 해결**, **OFF class에서 후보 수만큼 class record를 다시 읽는 성능 문제는 잔존**으로 분리한다.
예전 리뷰 comment를 그대로 복사해 해결된 오류전파 문제까지 다시 보고하지 않는다.

## 테스트 이력 해석

#7370에는 cubrid-testcases #2985와 private-ex #3549 draft가 자동 생성됐지만 engine PR이 merge되지
않아 둘 다 close/delete됐다는 bot comment가 남아 있다. 이후 개별 PR 테스트가 있더라도 현재 통합
HEAD에 대한 공개 TC가 유지된다는 증거는 아니므로, 최종 보고서에서는 RK 후보 동등성, multi ALTER,
mixed ON/OFF SBR과 rkcheck fault를 별도 회귀 공백으로 기록한다.
