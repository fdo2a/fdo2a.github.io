# 중국 경제 학습 리포트 — 주간 파이프라인

토요일 11:00 KST 실행 (트리거 `trig_01FC8hN3FGpYpXCRwr9rfuxH`, cron `0 2 * * 6`, sonnet-5).
수집은 `collect-china-data.yml` 이 평일 06:00 UTC 에 돌린다.
한 주에 강의 한 편을 발행한다.

**이 파이프라인은 시황 리포트가 아니다.** 그날의 가격을 좇는 대신 중국 경제가 굴러가는 방식을
한 편에 하나씩 뜯어본다. 시황 이야기가 본문의 25%를 넘으면 게이트가 발행을 막는다.

---

## STEP 0 — 데이터 신선도와 멱등 가드

**순서가 중요하다.** 멱등 가드를 먼저 걸면 낡은 데이터를 보고 「이미 발행됨」으로 끝낸다
(2026-08-28·09-02 전례).

1. `china/data/releases/index.json` 의 `generated` 를 본다. 오늘(KST) 이전이면 수집을
   **한 번만** 직접 돌린다:

   ```bash
   gh workflow run collect-china-data.yml
   RUN=$(gh run list --workflow=collect-china-data.yml --limit 1 --json databaseId -q '.[0].databaseId')
   gh run watch "$RUN" --exit-status
   ```

   `--exit-status` 가 없으면 실패한 수집이 성공으로 읽혀 낡은 데이터로 발행한다.
   **끝나면 `git pull --rebase` 로 그 커밋을 받아 오고 `generated` 를 다시 본다** —
   워크플로가 성공해도 로컬에는 아직 옛 파일이 있다. 여전히 이르면 발행하지 않는다.

2. **tier 1 릴리스 실패를 확인한다.** `index.json` 에 `tier: 1` 이면서 `fetch_status != "ok"`
   인 항목이 있으면 **발행하지 않는다.** `invalid` 는 HTTP 200 을 받았지만 본문이 그
   릴리스가 아니었다는 뜻이다(WAF 안내문·오류 페이지) — 실패와 같이 취급한다.
   이건 「그 주에 발표가 없었다」와 다른 상황이고,
   구분하지 못하면 수집 장애가 조용한 무발표로 위장된다. 게이트도 같은 것을 본다.

4. 이번 주 키를 구한다 — `python3 -c "import sys; sys.path.insert(0,'scripts'); from china.state import week_key; from datetime import date; print(week_key(date.today()))"`.
   **ISO week-year 를 쓴다**(달력 연도가 아니다 — 2027-01-01 은 2026-W53).

5. **이제** 멱등 가드: `china/posts/<주차키>.html` 이 이미 있으면 종료.

## STEP 1 — 무엇을 쓸 것인가 (기계가 정한다)

```bash
python3 - <<'PY'
import json, sys; sys.path.insert(0, 'scripts')
from china import syllabus as S, state as ST
syl = S.load(json.load(open('china/data/syllabus.json')))
st = json.load(open('china/data/curriculum_state.json'))
print('이번 강의:', syl.next_lesson(ST.completed_ids(st)))
print('되짚기 대상:', ST.revisit_target(st))
PY
```

**둘 다 고르지 않는다.** 다음 강의는 실라버스 order 와 완료 목록이, 되짚기 대상은 「가장 오래
안 본 강의」가 정한다. 다른 것을 쓰면 게이트가 막는다.

`next_lesson` 이 `None` 이면 실라버스가 소진된 것이다. **발행하지 말고 사람에게 보고한다** —
draft 승격은 사람이 커밋으로 한다.

## STEP 2 — 리서치

읽을 것은 레포 안에 이미 있다. **웹 검색으로 수치를 새로 모으지 않는다.**

- `china/data/syllabus.json` 의 그 강의 항목 — 특히 `notes`(사실 정정 메모)와 `core_question`
- `china/data/releases/*.txt` — 릴리스 **원문**. 헤드라인 숫자 너머의 구성·기여도·일회성 요인이
  여기 있다. 이것을 읽는 것이 이 파이프라인의 리서치다
- `china/data/manifest.json` — 인용 가능한 헤드라인 지표
- `china/data/markets.json` — 시세 (상한 안에서만)
- 되짚기 대상 강의의 발행본과 `claims`

강의 주제 자체의 배경(제도·역사·최근 정책)은 웹 리서치로 보강해도 된다. **수치만은 수집
파일에서 온다.**

## STEP 3 — 작성

`china-report-writer` 서브에이전트에 위임한다. Agent 도구가 없으면
`.claude/agents/china-report-writer.md` 를 읽어 직접 수행한다.

산출: `china/posts/<주차키>.html`

## STEP 4 — 조판

```bash
python3 scripts/apply_readability.py
```

조판이 검사보다 **먼저**다.

## STEP 5 — AI 티 제거

US·KR 과 동일. `scripts/humanize_prose.py` 로 `extract` → 윤문 → `finalize`.
전부 통과했을 때만 원본이 바뀐다.

## STEP 6 — 게이트

```bash
python3 scripts/check_china.py china/posts/<주차키>.html
python3 scripts/check_readability.py --strict china/posts/<주차키>.html
python3 scripts/check_style.py china/posts/<주차키>.html
```

하나라도 실패하면 **고쳐서 다시 돌린다.** 게이트를 우회하지 않는다.

## STEP 7 — 상태 전이와 발행 (한 커밋)

**여기가 트랜잭션 경계다.** 게이트가 전부 통과한 뒤에만 상태를 옮긴다 — 발행이 실패했는데
진도만 앞서 나가면 그 강의는 영영 빈칸으로 남는다.

1. **읽은 판의 해시를 STEP 1 에서 미리 잡아 둔다** — `ST.state_hash(st)`.
2. 커밋 직전에 `git pull --rebase` 하고 **세 가지를 다시 본다**: 그 주차 포스트가 이미
   원격에 있는가(있으면 종료) · `curriculum_state.json` 의 해시가 STEP 1 때와 같은가
   (다르면 다른 실행이 앞서 간 것이므로 종료) · `next_lesson` 이 여전히 같은 강의인가.
3. 상태를 계산한다. **STEP 1 에서 얻은 값을 그대로 넣는다** — 아래는 형태만 보여 준다:

```bash
LESSON=A01 WEEK=2026-W37 REVISIT= BASE_HASH=<STEP 1 해시> python3 - <<'PY'
import json, sys; sys.path.insert(0, 'scripts')
from china import state as ST
import os
st = json.load(open('china/data/curriculum_state.json'))
if ST.state_hash(st) != os.environ['BASE_HASH']:
    sys.exit('상태가 그 사이 바뀌었다 — 발행을 멈춘다')
nxt = ST.advance(st, lesson=os.environ['LESSON'], week=os.environ['WEEK'],
                 revisited=os.environ['REVISIT'] or None,
                 claims=json.load(open('claims.json')))
json.dump(nxt, open('china/data/curriculum_state.json', 'w'),
          ensure_ascii=False, indent=1)
PY
```

   `advance()` 는 순수하고 멱등하다 — 같은 주로 두 번 불러도 진도가 두 칸 밀리지 않고,
   같은 주에 다른 강의를 실으려 하면 거부한다. 되짚기 대상이 큐 지목과 다르면 거부한다.

4. `china/posts.json` 에 항목 추가 (`{key, lesson, title, headline}`), `sitemap.xml` 갱신.
5. **포스트·상태·목록·sitemap 을 한 커밋에** 넣고 push.

```bash
git add china/posts/<주차키>.html china/data/curriculum_state.json china/posts.json sitemap.xml
bash scripts/ci/push_with_retry.sh "china: <주차키> <강의 id>"
```

**push 가 거절돼 rebase 로 다시 밀렸다면 CAS 를 다시 확인한다.** `push_with_retry.sh` 는
push 거절만 재시도하고 **상태 비교는 하지 않는다** — 그 사이 다른 실행이 같은 주차를
발행했으면 두 전이가 겹친다. 재시도 뒤 `china/posts/<주차키>.html` 이 원격 이력에 두 번
들어갔거나 `curriculum_state.json` 의 `last_published_week` 가 기대와 다르면 **되돌리고
다시 시작한다**(force push 하지 않는다).

## 하지 않는 것

- **Notion 발행하지 않는다** (2026-08-18 지시 — 블로그 한 채널)
- **종목 판정하지 않는다** — thesis 파이프라인의 일
- **당파 논평하지 않는다** — 사실 → 전달 경로 → 다음 일정
- **발표가 없는 주에 지표 섹션을 채우지 않는다** — 없으면 없다고 쓴다

설계: `docs/superpowers/specs/2026-09-05-china-learning-report-design.md`
