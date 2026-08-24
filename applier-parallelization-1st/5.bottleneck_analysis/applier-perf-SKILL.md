---
name: applier-perf
description: CUBRID applylogdb + cub_server 두 프로세스에 on-CPU + off-CPU + futex perf record와 thread count 모니터를 백그라운드로 띄우고, 사용자가 "종료"라고 말할 때까지 캡처한다. 결과는 KST 타임스탬프 디렉토리에 저장하고, slocator_repl_force TID 분포 + off-CPU wait 함수 + futex stack lock 함수까지 자동 요약. 트리거: "applier-perf", "applier perf", "perf 측정 시작" (CUBRID 맥락에서).
---

# applier-perf

CUBRID 병렬 `applylogdb` PoC 분석용 perf 캡처 스킬. 대상은 `applylogdb`(`cub_admin applylogdb ...`)와 짝이 되는 `cub_server` 두 프로세스만.

## 동작 절차 (Claude가 따를 순서)

### Step 1. PID 단일 매칭 + 환경변수 등록

기본 DB 이름은 `testdb`. 인자로 다른 이름 받으면 그것 사용 (`applier-perf <dbname>`).

```bash
DB_NAME="${1:-testdb}"

apply_matches=$(pgrep -f "applylogdb.*${DB_NAME}@")
apply_count=$(printf "%s\n" "$apply_matches" | grep -c .)
server_matches=$(pgrep -f "cub_server ${DB_NAME}\b")
server_count=$(printf "%s\n" "$server_matches" | grep -c .)

if [ "$apply_count" -ne 1 ] || [ "$server_count" -ne 1 ]; then
  echo "ERROR: single-match policy violated"
  echo "  applylogdb matches ($apply_count):"; pgrep -af "applylogdb" | sed 's/^/    /'
  echo "  cub_server matches ($server_count):"; pgrep -af "cub_server" | sed 's/^/    /'
  exit 1
fi

export APPLY_PID="$apply_matches"
export SERVER_PID="$server_matches"
echo "APPLY_PID=$APPLY_PID  SERVER_PID=$SERVER_PID  DB=$DB_NAME"
```

두 PID가 모두 단일 매치되어야 다음 step 진행. 실패 시 멈추고 사용자에게 알림.

### Step 2. 출력 디렉토리 생성 (KST 타임스탬프)

```bash
TS=$(TZ=Asia/Seoul date +%Y%m%d-%H%M%S)
export OUTDIR="$(pwd)/perf-runs/${TS}"
mkdir -p "$OUTDIR"
echo "OUTDIR=$OUTDIR"
```

`./perf-runs/YYYYMMDD-HHMMSS/` (KST) 형태. cwd 기준.

### Step 3. perf record (on-CPU + off-CPU + futex) + thread monitor 백그라운드 동시 실행

`Agent` (executor) 네 개를 **동시에** spawn하여 각각 nohup 프로세스 띄우고 PID만 반환받는다. 본 세션에서 검증된 패턴.

#### 3-a. on-CPU perf record 에이전트 prompt (정확히 이대로)

```
nohup perf record -F 999 -g --call-graph dwarf \
  -p $SERVER_PID,$APPLY_PID \
  -o $OUTDIR/oncpu.data \
  > $OUTDIR/oncpu.log 2>&1 &
ONCPU_PID=$!
disown $ONCPU_PID 2>/dev/null
echo "ONCPU_PID=$ONCPU_PID"
sleep 2
ps -p $ONCPU_PID -o pid,stat,etime,cmd
cat $OUTDIR/oncpu.log
ls -la $OUTDIR/oncpu.data
```

보고 받을 항목: `ONCPU_PID`, ps STAT(살아있는지), oncpu.log 내용, oncpu.data 크기.

#### 3-b. off-CPU perf record 에이전트 prompt (정확히 이대로)

`sched:sched_switch` tracepoint로 어디서 멈춰 기다리는지 stack 캡처. on-CPU와 같은 워크로드 윈도우를 봐야 비율 비교가 의미 있으므로 **동시** 실행.

```
nohup perf record -e sched:sched_switch --call-graph dwarf \
  -p $SERVER_PID,$APPLY_PID \
  -o $OUTDIR/offcpu.data \
  > $OUTDIR/offcpu.log 2>&1 &
OFFCPU_PID=$!
disown $OFFCPU_PID 2>/dev/null
echo "OFFCPU_PID=$OFFCPU_PID"
sleep 2
ps -p $OFFCPU_PID -o pid,stat,etime,cmd
cat $OUTDIR/offcpu.log
ls -la $OUTDIR/offcpu.data
```

보고 받을 항목: `OFFCPU_PID`, ps STAT, offcpu.log 내용, offcpu.data 크기.
`offcpu.log` 에 `Permission denied` / `EACCES` 보이면 `perf_event_paranoid` 가 tracepoint 를 막은 것 (`<= 1` 필요). 사용자에게 알리고 sudo 또는 sysctl 변경 요청.

#### 3-c. futex perf record 에이전트 prompt (정확히 이대로)

`syscalls:sys_enter_futex,syscalls:sys_exit_futex` 로 futex 진입/탈출 stack 캡처. off-CPU 가 lock-wait 인지 sleep 인지 가르는 결정타 — stack 안에 `prior_lsa_mutex` / `pthread_mutex_lock` 보이면 mutex contention 확정.

```
nohup perf record -e syscalls:sys_enter_futex,syscalls:sys_exit_futex \
  --call-graph dwarf \
  -p $SERVER_PID,$APPLY_PID \
  -o $OUTDIR/futex.data \
  > $OUTDIR/futex.log 2>&1 &
FUTEX_PID=$!
disown $FUTEX_PID 2>/dev/null
echo "FUTEX_PID=$FUTEX_PID"
sleep 2
ps -p $FUTEX_PID -o pid,stat,etime,cmd
cat $OUTDIR/futex.log
ls -la $OUTDIR/futex.data
```

보고 받을 항목: `FUTEX_PID`, ps STAT, futex.log 내용, futex.data 크기.
futex syscall 은 contention 심하면 이벤트 폭주 → `futex.data` 가 분 단위로 GB 급일 수 있음. 캡처 시간 너무 길면 디스크 주의.
`Permission denied` / `EACCES` 면 off-CPU 와 같은 paranoid 이슈.

#### 3-d. thread monitor 에이전트 prompt (정확히 이대로)

```
LOGFILE="$OUTDIR/thread_counts.log"
{
  echo "# applylogdb thread count monitor"
  echo "# APPLY_PID=$APPLY_PID  started=$(TZ=Asia/Seoul date '+%Y-%m-%d %H:%M:%S KST')"
  echo "# columns: timestamp_kst<TAB>thread_count<TAB>thread_names_uniq_count"
} > "$LOGFILE"

nohup bash -c '
  APPLY_PID='"$APPLY_PID"'
  LOGFILE='"$LOGFILE"'
  while kill -0 $APPLY_PID 2>/dev/null; do
    ts=$(TZ=Asia/Seoul date "+%Y-%m-%d %H:%M:%S")
    cnt=$(ls /proc/$APPLY_PID/task 2>/dev/null | wc -l)
    uniq_names=$(for t in /proc/$APPLY_PID/task/*/comm; do cat "$t" 2>/dev/null; done | sort -u | wc -l)
    printf "%s\t%s\t%s\n" "$ts" "$cnt" "$uniq_names" >> "$LOGFILE"
    sleep 1
  done
  echo "# process gone at $(TZ=Asia/Seoul date \"+%Y-%m-%d %H:%M:%S KST\")" >> "$LOGFILE"
' > /dev/null 2>&1 &
MON_PID=$!
disown $MON_PID 2>/dev/null
echo "MON_PID=$MON_PID"
sleep 2
ps -p $MON_PID -o pid,stat,etime,cmd
head -5 "$LOGFILE"
```

보고 받을 항목: `MON_PID`, ps STAT, logfile 첫 5줄.

### Step 4. 상태 보고 + 대기 안내

사용자에게 다음 형식으로 보고 후 **대기**:

```
OUTDIR     = <경로>
ONCPU_PID  = <pid>  →  oncpu.data, oncpu.log
OFFCPU_PID = <pid>  →  offcpu.data, offcpu.log
FUTEX_PID  = <pid>  →  futex.data, futex.log
MON_PID    = <pid>  →  thread_counts.log
APPLY_PID  = <pid>
SERVER_PID = <pid>
```

안내 문구:
- "워크로드 시작하셔도 됩니다."
- "충분히 캡처됐다 싶으면 '종료'라고 말씀해 주세요."
- "thread 수 펴지는 거 실시간 보려면: `tail -f $OUTDIR/thread_counts.log`"

### Step 5. 사용자 "종료" 시 정리

```bash
kill -INT "$ONCPU_PID"  2>&1
kill -INT "$OFFCPU_PID" 2>&1
kill -INT "$FUTEX_PID"  2>&1
kill        "$MON_PID"   2>&1
sleep 2
ps -p "$ONCPU_PID"  -o pid,stat,etime,cmd 2>&1
ps -p "$OFFCPU_PID" -o pid,stat,etime,cmd 2>&1
ps -p "$FUTEX_PID"  -o pid,stat,etime,cmd 2>&1
ps -p "$MON_PID"    -o pid,stat,etime,cmd 2>&1
cat "$OUTDIR/oncpu.log"
cat "$OUTDIR/offcpu.log"
cat "$OUTDIR/futex.log"
ls -la "$OUTDIR"/*.data
```

`applylogdb`가 측정 도중 죽었을 수 있으니 (이전 세션 경험) `thread_counts.log` 마지막 줄에 `# process gone` 있는지 함께 확인.

### Step 6. 자동 요약

```bash
for tag in oncpu offcpu futex ; do
  perf script -i "$OUTDIR/${tag}.data" > "$OUTDIR/${tag}.script" 2>/dev/null
  echo "$tag script lines: $(wc -l < "$OUTDIR/${tag}.script")"
done

for tag in oncpu offcpu futex ; do
  echo "=== ${tag^^}: slocator_repl_force / xlocator_repl_force 포함 sample TID 분포 ==="
  awk 'BEGIN{RS=""; FS="\n"} /slocator_repl_force|xlocator_repl_force/ {split($1, a, " "); print a[1], a[2]}' "$OUTDIR/${tag}.script" \
    | sort | uniq -c | sort -rn | head -30
done

echo "=== ON-CPU: 전체 sample 분포 top 30 (comm + TID) ==="
grep -E '^[a-zA-Z_].* [0-9]+ +[0-9]+\.[0-9]+:' "$OUTDIR/oncpu.script" \
  | awk '{print $1, $2}' | sort | uniq -c | sort -rn | head -30

echo "=== OFF-CPU: 가장 자주 멈춘 함수 top 20 (sched_switch 시점 stack frames) ==="
grep -hE '^\s+[0-9a-f]+\s' "$OUTDIR/offcpu.script" \
  | awk '{print $2}' | sort | uniq -c | sort -rn | head -20

echo "=== OFF-CPU: slocator_repl_force 가지 안의 wait 함수 top 20 ==="
awk '
  /^$/ { if (in_stack && has_sflush) printf "%s", stack;
         stack=""; in_stack=0; has_sflush=0; next }
  /slocator_repl_force|xlocator_repl_force/ { has_sflush=1 }
  { stack = stack $0 "\n"; in_stack=1 }
' "$OUTDIR/offcpu.script" \
  | grep -E '^\s+[0-9a-f]+\s' | awk '{print $2}' \
  | sort | uniq -c | sort -rn | head -20

echo "=== FUTEX: 전체 stack 안 함수 top 20 (lock owner 검출) ==="
grep -hE '^\s+[0-9a-f]+\s' "$OUTDIR/futex.script" \
  | awk '{print $2}' | sort | uniq -c | sort -rn | head -20

echo "=== FUTEX: slocator_repl_force 가지 안 함수 top 20 (prior_lsa_mutex 확정 단서) ==="
awk '
  /^$/ { if (in_stack && has_sflush) printf "%s", stack;
         stack=""; in_stack=0; has_sflush=0; next }
  /slocator_repl_force|xlocator_repl_force/ { has_sflush=1 }
  { stack = stack $0 "\n"; in_stack=1 }
' "$OUTDIR/futex.script" \
  | grep -E '^\s+[0-9a-f]+\s' | awk '{print $2}' \
  | sort | uniq -c | sort -rn | head -20

echo "=== applylogdb thread count 변화 ==="
awk 'NR>3 {print $3}' "$OUTDIR/thread_counts.log" | sort | uniq -c | sort -rn
echo "applylogdb thread peak: $(awk 'NR>3 {print $3}' "$OUTDIR/thread_counts.log" | sort -n | tail -1)"
```

## 산출물 (OUTDIR 안)

| 파일 | 내용 |
|---|---|
| `oncpu.data` | on-CPU perf raw capture (`-F 999`) |
| `oncpu.script` | on-CPU perf script 텍스트 변환 |
| `oncpu.log` | on-CPU perf record stderr (samples 수 / 에러) |
| `offcpu.data` | off-CPU perf raw capture (`sched:sched_switch`) |
| `offcpu.script` | off-CPU perf script 텍스트 변환 |
| `offcpu.log` | off-CPU perf record stderr |
| `futex.data` | futex perf raw capture (`syscalls:sys_{enter,exit}_futex`) |
| `futex.script` | futex perf script 텍스트 변환 |
| `futex.log` | futex perf record stderr |
| `thread_counts.log` | applylogdb 매초 thread count + unique name 수 |

## 전제 / 주의

- 같은 user UID 프로세스 attach만 검증됨 (paranoid=2 OK, sudo 불필요). 다른 UID면 perf record가 `-EACCES`로 실패 → 그때 사용자에게 sudo 필요 알림.
- **off-CPU (`sched:sched_switch`) 와 futex (`syscalls:sys_*_futex`) tracepoint 는 `perf_event_paranoid <= 1` 필요**. paranoid=2 환경에선 on-CPU 만 성공하고 off-CPU / futex 는 `EACCES` 로 떨어진다. 그 경우:
  - 임시로 `sudo sysctl kernel.perf_event_paranoid=1` 권장, 또는
  - off-CPU / futex 만 `sudo` 로 띄우는 변형 사용.
- `perf_event_paranoid >= 3` 환경에선 일반 user attach 불가. 환경 확인 권장.
- DB 인스턴스 여러 개 떠있을 때는 인자로 DB 이름 명시 (`applier-perf <dbname>`).
- 종료 후 OUTDIR 사이즈 큼 (수백 MB ~ 수 GB; **futex 트랙이 가장 큼** — contention 심하면 분당 GB 급) — 분석 끝나면 user가 정리.
- thread_counts.log 마지막 줄 `# process gone` 발견 시 applylogdb가 측정 중 종료된 것 → 캡처 데이터 신뢰성 재검토.
- on-CPU / off-CPU / futex 세 트랙은 **동시** 캡처여야 같은 워크로드 윈도우의 비율 비교가 의미 있음 (off-CPU vs futex 매핑이 핵심). 따로 잡지 말 것.

## 트리거 키워드

- `applier-perf` / `applier perf`
- `applylogdb perf`
- `cubrid perf 측정` (CUBRID 맥락에서만)
