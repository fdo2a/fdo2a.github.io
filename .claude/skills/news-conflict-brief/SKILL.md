---
name: news-conflict-brief
description: Local chat procedure for researching one news topic the user names — keep only claims that conflict across articles (with source and one-line evidence), rate each claim (speaker type, real data, credibility), compress into one essence structure / ≤3 variables / mechanism / 3 memory points, and end with three worry tiers. Use when the user asks in a local session for news research, issue comparison, conflicting claims or the 「본질」 of a topic. The published reports get the same analysis automatically from the contested pipeline — do not use this skill inside routines.
---

# News conflict brief (local sessions)

The published version of this method is the **contested analysis** pipeline; its contract
(claim grounding, credibility rubric, worry tiers, gate) lives in
`docs/superpowers/specs/2026-10-21-contested-analysis-design.md`. Follow the same output
shape and rules here; the only differences are listed below.

- **Sources**: repo data first (`data/news/`, `data/contested/`), then web search. 6–10
  articles from at least three kinds of outlet (wire, regional, market, official).
- **Tables**: conflict table (쟁점 | 주장 | 출처 | 근거 1줄) with common content removed;
  evaluation table (주장 | 발언 주체 | 실물 데이터 | 신빙성) using the spec's rubric —
  article-reported evidence caps at 중간; 높음 only when you checked the data yourself.
- **Essence**: ① one sentence ② ≤3 variables, each with an observable indicator
  ③ conditional mechanism ④ exactly 3 memory points. No claim lists, no article
  summaries, no "A or B", no forecasts — only "if condition X, direction Y".
- **Worry tiers**: most / worry-but-no-panic / practically unlikely. "Unlikely" must name the
  condition it would need and the current observation pointing the other way.
- Answer in the chat style of `../COLLABORATION.md` (ranges with `-`), not the desk register.
  Mark guesses as guesses; no personalized investment advice.
