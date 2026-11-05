# 설계 문서 안내

[`superpowers/specs/`](superpowers/specs/)에는 2026년 7월부터 쌓인 설계 문서가 날짜순으로 있습니다. 문서마다 무엇이 틀렸는지, 어떤 선택지를 놓고 무엇을 골랐는지, 무엇을 아직 못 막는지를 적었습니다. [`superpowers/plans/`](superpowers/plans/)는 그중 큰 작업의 실행 계획입니다.

전부 읽을 필요는 없습니다. 아래 16개부터 보면 검증 체계의 뼈대가 보입니다.

## 먼저 읽을 문서

**수치가 틀리지 않게**

| 문서 | 다루는 문제 |
|---|---|
| [원자재·환율 16:00 ET 컷](superpowers/specs/2026-10-14-close-cut-basis.md) | 가격은 시간외 거래가, 등락률은 결제가 대비 — 기준이 갈려 등락률이 최대 세 배 달라진 문제 |
| [FRED 공식 API 전환](superpowers/specs/2026-09-05-us-fred-api-design.md) | 비공식 경로가 403으로 막힌 두 번의 경험, 키 오류와 장애를 구분하는 법 |
| [섹터 성과표 시차](superpowers/specs/2026-10-13-sector-perf-staleness.md) | 다른 거래일의 섹터 표가 실리는 것을 막는 검사 |

**판단이 흔들리지 않게**

| 문서 | 다루는 문제 |
|---|---|
| [멀티에셋 스탠스 지속성](superpowers/specs/2026-08-17-us-multiasset-stance-persistence-design.md) | 자산별 판단이 하루 주가에 매일 뒤집힌 문제 (발단) |
| [매크로 논리 승계](superpowers/specs/2026-08-18-us-macro-logic-persistence-design.md) | 경기 국면은 새 지표 발표로만 움직인다는 규칙과 그 검사 |

**인용과 출처가 지어지지 않게**

| 문서 | 다루는 문제 |
|---|---|
| [연준 발언록](superpowers/specs/2026-09-02-us-fed-events-design.md) | 인용문을 수집한 원문과 글자 단위로 대조 |
| [출처 결속](superpowers/specs/2026-09-14-report-source-provenance-design.md) | 본문 링크가 그날 수집한 문서만 가리키게 하는 검사 |

**일본 시장**

| 문서 | 다루는 문제 |
|---|---|
| [일본 주간](superpowers/specs/2026-09-26-weekly-insight-and-japan-design.md) | 휴일 주에 금리차 변화가 「0」으로 나온 문제, 자금 흐름의 부호 |
| [일본 일간 국채 금리](superpowers/specs/2026-10-29-japan-daily-naver-jgb.md) | 정의가 다른 두 출처를 섞지 않는 대체 규칙 |

**메모리 반도체 3사**

| 문서 | 다루는 문제 |
|---|---|
| [종목 점검 설계](superpowers/specs/2026-08-24-thesis-watch-design.md) | 트리거 없이는 페이지를 못 바꾸게 한 구조, 등급 규율, 밸류에이션 기준선 |
| [조용한 날 판정](superpowers/specs/2026-09-24-thesis-quiet-prefilter.md) | 증명할 수 없으면 조용한 날이 아니다 — 리서치를 건너뛰는 조건 |
| [마이크론 SEC 공시](superpowers/specs/2026-10-17-sec-edgar-micron-feed.md) | DART와 같은 기준으로 미국 공시를 분류하는 법 |

**발행 후 검토**

| 문서 | 다루는 문제 |
|---|---|
| [발행 후 검토 게이트](superpowers/specs/2026-08-24-post-publish-review-gate-design.md) | 자동 발행 앞에 검토를 끼울 수 없어 발행 뒤로 옮긴 이유 |
| [로컬 검토 러너](superpowers/specs/2026-09-10-local-review-runner-design.md) | 검토가 중앙값 6일 밀린 것을 재고 자동화한 과정 |

**운영**

| 문서 | 다루는 문제 |
|---|---|
| [한도 해제 뒤 재시도](superpowers/specs/2026-09-27-routine-retry-after-limit.md) | 사용 한도로 중간에 죽은 루틴을 다시 띄우는 장치 |
| [모델 라우팅](superpowers/specs/2026-10-27-model-routing.md) | 작업별로 모델을 나눈 기준과 비용 |

## 문서를 읽는 법

- 파일명 앞의 날짜는 그 설계를 처음 쓴 날입니다. 뒤에 바뀐 내용은 같은 문서 아래쪽에 덧붙이거나 새 문서로 냈습니다.
- 설계는 바뀝니다. 예를 들어 자산별 스탠스 기록은 2026-09-19에 없앴고, 그 역할 일부는 매크로 국면 검사가 이어받았습니다. 지금 코드가 어떻게 도는지는 각 파이프라인의 [`scripts/us/CLAUDE.md`](../scripts/us/CLAUDE.md) · [`scripts/kr/CLAUDE.md`](../scripts/kr/CLAUDE.md)가 기준입니다.
- 문서 대부분이 한국어이고, 일부는 영어입니다.
