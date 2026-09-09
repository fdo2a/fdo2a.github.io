# US/KR — learning to read markets

Read this before researching, writing, or reviewing either daily brief. The reader
is a trader aspirant, especially in Rates/FICC. Teach them to explain a price
move, distinguish evidence from inference, and test their explanation next time.
Keep the existing market coverage, section order, numeric sources, and gates.
This contract adds learning to the reports; it does not change portfolio rules.

## Activation — first publication on 2026-09-11 KST

The new research handoff, learning section and its editorial presence check start
at US `report_date >= 2026-09-10` and KR `report_date >= 2026-09-11`. These are
market-session dates, not the machine's run date. This activation rule governs
the learning-section entries and handoff pointers in both writers and runbooks.
For earlier sessions, keep the existing report structure and skip the new
learning handoff/block/presence check. Do not republish an existing post to add
learning. Evidence discipline applies whenever writing new prose. The first
eligible issue bootstraps if its predecessor has no learning question.

## Research handoff

Add `학습·복기` to `research_notes.md` before handing it to the writer:

1. **Previous question.** Read the latest committed same-market daily post whose
   filename date is strictly earlier than `report_date` (`posts/` for US,
   `kr/posts/` for KR). Record its path, date, learning question, original test
   condition and deadline. Use its learning block only, not the editor's personal
   note. If it has no learning block, bootstrap; do not invent a previous question.
2. **One case.** Choose a material move or a useful non-reaction in today's data.
   Record the observation, one explanatory hypothesis, a plausible alternative
   where supported, and the evidence that could distinguish them. An unknown
   cause is a valid lesson; never manufacture a competing explanation.
3. **One calculation, when supported.** Reuse an existing calculated field first.
   Otherwise run simple arithmetic in Python using canonical input values: e.g.
   `(long yield - short yield) * 100` in bp when inputs are in percent, or
   `change in long yield - change in short yield` when changes are already bp.
   Record input file/fields, values, units, both dates, formula, executable command
   and result. Check that dates, tenor definitions and comparison windows match.
   Writer copies this checked result; this is the narrow numeric-source exception
   for the learning block and the KR rates section’s specified spreads, not
   permission to calculate portfolio performance.
   Missing inputs → conceptual exercise without a numerical answer. No invented
   market quotes, notionals, DV01, hedge ratios or P&L examples.
4. **Next test.** Name one observable condition, the instrument/series to watch,
   and a next-session or named-event horizon. Event dates/times need a source and
   timezone. State what would support or weaken the hypothesis; avoid arbitrary
   price targets. Record source URLs and observation times for research evidence.

Keep canonical prices in their existing data files. This handoff supplements
them with explanation and reproducible learning arithmetic, not a second price
feed. Research missing conceptual context from primary institutional sources;
the writer uses the handoff and does not start a second research pass.

## Market roles

- **US:** global price formation. Connect the release's consensus and actual
  (including revisions) to policy repricing and relative tenor moves. Distinguish
  pre-event expectations, observed immediate reaction and close. If only daily
  yields exist, discuss close-to-close changes, not an invented intraday response.
  FedWatch probabilities and OIS-implied paths are distinct measures: identify the
  instrument and horizon, and compare only like-for-like observations.
- **KR:** transmission and local differences. Connect the preceding completed US
  session to Korean yields, FX and equities, then examine domestic policy or
  supply/flow evidence for divergence. Label both session dates; overnight
  transmission is not a synchronous correlation. Reuse available 3Y/10Y yields
  and AA- spread first. 5Y/30Y, bond futures and foreign futures flow are future
  collection priorities; IRS/OIS and FX swaps follow after sources are verified.
  Use them as observations only when canonical inputs exist. Do not replace
  missing bond flow with equity flow or FX hedging costs with spot FX.

Cross-market references use only sessions completed before this report's data
cutoff. An older other-market post must carry its actual date; no later report or
event outcome may be used to make an earlier prediction look informed.

## Evidence discipline — applies throughout the report

- State **observation → possible mechanism → distinguishing evidence**. Reserve
  causal conclusions for supporting evidence. Temporal coincidence alone is not
  attribution. If a section asks for a cause but it is unverified, state the
  limitation and the next check instead of asserting a cause.
- A bond yield minus the current policy rate is not the amount of policy hikes
  priced in. Separate expected future short rates from term/liquidity premia;
  policy-pricing claims require an appropriate market measure and source.
- A stable credit spread or CD fixing does not prove a supply-driven Treasury
  move or unchanged policy expectations. A yield rise does not identify the
  seller, and foreign equity buying does not establish foreign bond selling.
- Investor categories and program-trading categories overlap; compare like
  universes and cutoffs. Their aggregate differences do not reveal proprietary
  trading, client motives, hedging or asset rotation. Gross turnover is activity,
  not net inflow. An empty detected-turn list does not prove monotonic flow.
- Preserve provisional/final labels when comparing closing observations. A
  pending final figure remains provisional even after regular trading ends.
- Lagged real yields, breakevens, credit spreads or term-premium estimates explain
  their own observation window, not today's new shock. Nominal-minus-real yield
  is inflation compensation, also affected by risk/liquidity premia; explain this
  qualification when using the familiar label `기대인플레` to teach the concept.

## Writer output

Explain the day's relevant concept briefly where it first helps the price story.
Use one or two concepts at most; do not append a glossary to every section.
Strategy comments describe the report's model view and its invalidation, not an
instruction to copy trades. Keep the existing stance vocabulary and markers.

Append one `<section class="card" data-learning="daily">` with the heading
`오늘의 학습과 복기` after the existing final content section and before the
disclaimer. Use 3–4 short paragraphs, roughly 350–650 Korean characters excluding
the calculation, with ordinary headings/captions rather than another dashboard:

- **지난 질문 복기:** cite the previous issue date and link, preserve its question
  and test condition, then compare available observations: supported, weakened,
  or still undecidable. A price direction alone does not prove the mechanism.
  If the event is pending/data unavailable, retain the original question, date
  and condition in the next-test paragraph; keep at most one open question.
  Bootstrap skips this paragraph. Never call the previous issue “yesterday”
  across holidays or missing issues, or rewrite its original hypothesis.
- **오늘의 개념:** explain one concept through today's observed move. Quiet days
  may revisit an unresolved case; no obligation to invent a new lesson.
- **직접 확인:** pose the short exercise and give the checked formula/result in
  a separate paragraph or caption, with units and source date. The calculation
  is allowed only through the research handoff above. Otherwise ask a qualitative
  question and provide the reasoning; no empty numeric slots.
- **다음 확인:** state the single hypothesis/test/horizon from the handoff, with
  an original question date so unresolved questions survive successive issues.

Use existing CSS and keep market coverage dominant. No learning-only stance
changes, no new portfolio, no customer-flow fiction, and no compulsory daily
VaR/stop-loss display without an actual model and inputs.

## Editorial check before publishing

After drafting and again after prose editing, verify: learning block present;
previous question/date/condition copied accurately or genuine bootstrap;
every calculation reproducible with aligned inputs; inference and unknowns
clearly distinguished; one next check retained; no future information; all
portfolio numbers still from `portfolio.json`. Check causal claims in the body
as well as the learning block. Repair the affected paragraphs when this check
fails. This is an editorial check, not a newly implemented automated gate;
run the existing publish gates in their usual order as well.
