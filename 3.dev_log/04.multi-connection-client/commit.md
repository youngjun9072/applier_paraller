# 04.multi-connection-client

- commit: `711338055`
- date: 2026-04-15 05:10:05 +0000

## Message

```
Enable multi-connection client support in CS and SA builds

Enable MULTI_CONN_TO_A_SERVER for client-side builds used by the applylogdb PoC.

- add MULTI_CONN_TO_A_SERVER to cubridcs compile definitions
- add MULTI_CONN_TO_A_SERVER to cubridsa compile definitions
- activate thread-local client_support instances through existing CUB_THREAD_LOCAL paths
- prepare the client connection layer for per-thread multi-connection experiments

```

## Review

- `cubridcs`와 `cubridsa`에만 `MULTI_CONN_TO_A_SERVER`를 추가했지만 util/broker/cm_common 등 동일 라이브러리를 링크하는 다른 타겟에는 미적용 — TLS/non-TLS ABI 불일치 위험. 05에서 `COMMON_DEFS`로 통합 적용하여 해결.
- 빌드 define만 변경, 동작 변화는 link 시 결정되므로 이 커밋 단독으로는 런타임 효과 없음.

## TODO

- (none)
