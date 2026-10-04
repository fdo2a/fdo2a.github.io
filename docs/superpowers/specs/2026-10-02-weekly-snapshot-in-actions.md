# 주간 스냅샷 수집을 Actions 로 (2026-10-02)

## 발견

일본 주간 루틴을 등록하며 점검 런을 돌렸다(2026-10-02 04:56Z, 루틴 환경 env_01GenHSEFjQj7TfbJrxtcbfT).
Yahoo 차트 API·MOF jgbcme.csv·MOF week.csv·CFTC Socrata·FRED CSV 다섯 곳 모두 `curl` 000(연결 실패),
`import yfinance` 실패. WEEKLY STEP 4-0 과 JAPAN STEP 1 은 루틴 안에서 `collect_weekly_data.py` 를 돌리게 돼
있었으므로 US 주간(토)과 일본 주간(일)은 클라우드에서 한 번도 성공할 수 없는 구조였다. W39 스냅샷은 로컬에서 받았고,
9/26 W39 루틴은 그 전에 한도로 죽어 드러나지 않았다. 일간은 이미 「Actions 수집·커밋 → 루틴은 읽기」다.

## 구조

- `.github/workflows/collect-weekly-data.yml` — 예약(토 12:00·일 08:00 KST) + `workflow_dispatch(key, end, dry_run)`.
  키·종료일 기본값은 **달력**(`routine_due.py week-key`·`week-end`)이다 — 데이터가 지난주에 머문 토요일에
  지난주 키를 받지 않게(설계 검토 #2). `data/weekly_ext/<KEY>.json` 의 **주인은 이 워크플로 하나**다. 원격 판의
  `generated` 가 더 늦으면 커밋하지 않는다 — 밀린 예약 실행이 새 스냅샷을 되돌리지 않게(#3).
- `scripts/ci/snapshot_ready.py us|japan --key --end` — READY / STALE. 키·종료일 일치, 그 시장이 쓰는 소스만의
  `fetch_status`(일본 판별은 `japan.core._japan_source`), 일본은 도쿄 금요일분(닛케이)과 그 전 영업일분(JGB 10년 — MOF 는 다음 영업일 공표, 2026-10-04 수정)까지 —
  종료일 +2일 이후 받은 스냅샷이면 도쿄 휴장으로 보고 사흘 봐준다(#4·#5).
- 오케스트레이터는 받지 않는다: READY 면 그대로, STALE 이면 워크플로를 key/end 로 띄우고 `wait_run.sh` 로
  기다린 뒤(2 면 한 번 더) `git pull` 하고 다시 판정, 그래도 STALE 이면 알리고 끝낸다. 주간은 이 단계를 STEP 3
  앞(작업 트리를 바꾸기 전)으로 옮겼다(#1). 발행 커밋에 스냅샷을 넣지 않는다.

## 설계 검토(codex, 2026-10-02) — 7건 수용

1 pull 위치(STEP 3 앞으로) · 2 예약 키는 달력 · 3 스냅샷 소유권 하나 + 늦은 실행 덮어쓰기 방지 · 4 일본 완결성은
마지막 관측일로 · 5 대기 결과별 처리, 시장별 소스만 · 6 워크플로에 pytest 설치·일본 테스트 · 7 문서는 규칙 10 과 잎사귀 한 줄.
