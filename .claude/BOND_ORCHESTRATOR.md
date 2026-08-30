# 글로벌 채권 EMP 일간 리포트 — 파이프라인

화~토 05:30 KST(겨울 06:30). 미국 채권시장이 닫힌 직후 그날의 글로벌 채권시장을
한 편으로 정리한다. **이 리포트의 독자는 채권 운용을 배우는 사람이다** — 판단을
과시하는 글이 아니라, 무엇을 어떤 순서로 보는지가 남는 글을 쓴다.

무게중심은 US 브리프와 같다. **시황이 판단보다 길어야 한다.** 게이트가 비율을 잰다.

---

## STEP 0 — 데이터 확인 (직접 시세 fetch 금지)

레포를 클론하고 `bond/data/`를 읽는다.

- `bond_market.json` — 6축 원자료. `complete`가 false면 `missing`을 보고하고 중단.
- `bond_metrics.json` — 「어제 대비」와 트리거 재료. **여기 값을 다시 계산하지 않는다.**
- `bond_stance.json` / `bond_stance_eval.json` — 전일 뷰와 오늘 허용 등급.
- `bond/data/history/bond_market.jsonl` — 원장.

`report_date`는 `bond_market.json`을 신뢰한다. 요일 산술로 도출하지 않는다.
데이터가 없거나 하루 이상 낡았으면 `gh workflow run collect-bond-data.yml -f force=true`로
수집을 먼저 돌리고, 그래도 안 되면 발행을 건너뛴다 — **없는 종가를 지어내지 않는다.**

## STEP 1 — 리서치 (수집 에이전트)

`bond-data-collector`가 웹에서 채워야 하는 것은 넷뿐이다. 나머지는 전부 데이터 파일에 있다.

1. 그날 채권시장을 움직인 사건 (중앙은행 발언, 국채 입찰, 지표 서프라이즈)
2. CME FedWatch 확률과 주요 중앙은행의 다음 회의 시장 기대
3. 비-FRED 지표의 컨센서스 (ISM·PMI·ADP 등)
4. 크게 움직인 축(§2 movers 상위)의 원인 — **그날 실제로 움직인 것만**

`bond_research.md`에 출처를 달아 적는다. **시세·스프레드·ETF 수치는 리서치 대상이 아니다.**

## STEP 2 — 작성

`bond-report-writer`가 `.claude/agents/bond-report-writer.md`를 따라 쓴다.
산출은 `bond/posts/<report_date>.html`.

기본 렌더는 `python3 scripts/build_bond_report.py`가 한다 — 산문은 빌더가 저작하고
숫자는 데이터에서 온다. writer 는 그날의 사건·원인 서술을 빌더가 남긴 자리에 얹는다.
**HTML 안에서 수치를 손으로 타이핑하지 않는다.**

## STEP 2.5 — AI 티 제거

US·KR과 같은 관문을 지난다. 원본을 손대지 않고 사본에서 윤문한 뒤
`scripts/humanize_prose.py finalize`가 전부 통과했을 때만 교체한다.

## STEP 3 — 발행 게이트

```
python3 scripts/apply_readability.py bond/posts/<date>.html
python3 scripts/check_bond.py       --html bond/posts/<date>.html
python3 scripts/check_readability.py --html bond/posts/<date>.html
python3 scripts/check_style.py            bond/posts/<date>.html
python3 -m pytest scripts/bond scripts/common -q
```

`check_style.py`는 `--html` 을 받지 않는다(경로만 받는다). `apply_readability.py`는
**조판 오버라이드를 먹이는 단계**라 검사 앞에 와야 한다 — 안 돌리면
`check_readability.py`가 「조판 오버라이드 미적용」으로 떨어진다.

게이트가 막는 것: 데이터에 없는 수치 · 통제 어휘 밖 등급 라벨 · 규율이 허용하지 않은
등급 · 하루 두 칸 이동 · 내부 파일명 노출 · 금지 어휘 · 위치 서술 표식 누락 ·
백분위 0회 · 무게중심 역전. **그리고 통제 입력 자체가 성립하지 않으면 닫힌다** —
`complete:false`, 파일 간 기준일 불일치, `allowed_grades` 부재는 전부 발행 중단 사유다.

게이트가 **못 막는 것**도 분명히 해 둔다. 수치 검사는 「이 값이 데이터 어딘가에서
나올 수 있는가」를 보지 그 값이 **그 문장의 지표에 속하는가**를 보지 않는다.
크기·자릿수가 어긋난 창작은 잡히지만 그럴듯한 값끼리의 뒤바뀜은 사람이 읽어야 잡힌다.

**위반은 그대로 writer 에게 돌려주고 다시 쓴다.** 게이트를 우회하지 않는다.

## STEP 4 — 승계 책 갱신

writer 가 등급을 움직였으면 `bond_stance.json`을 새 등급·`since`·논거·트리거로 갱신하고
`bond/data/history/bond_stance.jsonl`에 append 한다. **논거 문장에 수치를 손으로 적지
않는다** — 원장이 갱신되면 그 숫자만 뒤처진다(2026-08-31 실측: 발행본 §6은 0.1 백분위,
논거는 2.4 백분위였다). 값은 `bond_metrics.json`에서 포맷해 넣는다.

## STEP 5 — 발행

1. `bond/posts.json`에 `{date, slug, title, headline}` 한 줄 추가
2. `sitemap.xml`에 URL 추가
3. 커밋 후 push (`git pull --rebase --autostash` 먼저)
4. 푸시 알림

## 하지 않는 것

- Notion 발행 (US·KR과 함께 2026-08-18 중지)
- 시세 재수집 (STEP 0이 읽은 파일이 전부다)
- 데이터가 불완전한 날의 강행 발행
