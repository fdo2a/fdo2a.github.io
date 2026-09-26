# 일본 시장 주간 — 오케스트레이터 (일요일)

일요일 10:00 KST 에 한 편을 발행한다(루틴은 사용자가 초안을 확인한 뒤 등록). 재무성 증권투자(목)와 CFTC(금 공개, 화요일 기준)가 모두 들어온 뒤다. US·KR 주간 루틴(토)과 5시간 한도 창을 나누지 않으려고 날을 뗐다. 웹 검색은 하지 않는다.

## STEP 0 — 기간 키와 오늘

```bash
TZ=Asia/Seoul date +%F > /tmp/japan-today && cat /tmp/japan-today
python3 -c "import datetime as d;t=d.date.fromisoformat(open('/tmp/japan-today').read().strip());y,w,_=(t-d.timedelta(days=2)).isocalendar();print(f'{y}-W{w:02d}')"
```

두 번째 값이 `<KEY>`(그 주 금요일이 속한 ISO 주)다. `japan/posts/<KEY>.html` 이 이미 있으면 끝낸다 — **이 가드는 수집 뒤에 둔다**(STEP 1 이 끝난 다음 다시 확인).

## STEP 1 — 스냅샷과 진단

```bash
python3 scripts/collect_weekly_data.py --key <KEY> --end <그 주 금요일>
python3 scripts/build_japan_weekly.py diag --key <KEY>
```

US 주간이 토요일에 같은 키로 스냅샷을 이미 만들었어도 **다시 받는다** — 토요일 새벽에는 도쿄 금요일 종가와 MOF 커브 금요일분이 비어 있다(2026-09-26 실측). 실패 소스가 남으면 한 번만 재시도하고, 그래도 남으면 발행하지 않고 PushNotification 으로 알린다.

## STEP 2 — 작성과 조립

`japan-report-writer` 를 **동기**로 부른다. 넘기는 것은 경로뿐이다(`japan/data/<KEY>.json`, `<KEY>.news.json`) — 오케스트레이터가 데이터·지시문을 다시 읽지 않는다.

```bash
python3 scripts/build_japan_weekly.py assemble --key <KEY> \
  --body japan_<KEY>.body.html --meta japan_<KEY>.meta.json --out japan_<KEY>.html
```

## STEP 3 — 게이트 (순서대로, 전부 exit 0)

```bash
python3 scripts/apply_readability.py $(pwd)/japan_<KEY>.html
python3 scripts/check_japan.py --html japan_<KEY>.html --key <KEY>
python3 scripts/check_readability.py --strict $(pwd)/japan_<KEY>.html
python3 scripts/check_style.py $(pwd)/japan_<KEY>.html
```

위반은 목록 그대로 writer 에게 돌려준다. AI 티 제거는 US 주간 STEP 4-b 와 같은 `humanize_prose.py finalize` 관문을 지난다(`--gate` 에 위 셋).

## STEP 4 — 발행

`japan/posts/<KEY>.html` 로 옮기고 `japan/posts.json` 맨 앞에 `{key, title, headline, start_date, end_date}` 를 넣는다. 스냅샷·진단·뉴스 파일과 함께 **한 커밋**으로 `bash scripts/ci/push_with_retry.sh`. PushNotification 으로 URL 을 보낸다.
