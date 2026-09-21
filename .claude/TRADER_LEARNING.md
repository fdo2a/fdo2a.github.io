# Evidence and review — US/KR reports

Read `.claude/DESK_REPORT.md` first for the PM-facing market coverage and sales/research mandate. This document owns evidence discipline, calculation provenance and the closing review. `.claude/RESEARCH_WORKFLOW.md` owns the append-only record and publication checks. Keep existing market coverage and source/gate contracts.

**KR reader, from 2026-09-22 (user instruction).** The KR evening brief writes for a
hedge fund manager, not a trader aspirant; the desk supplies judgment material and
the reader decides. That changes who the prose addresses, not the evidence rules
below — hypothesis, plausible alternative, distinguishing evidence and the next
test apply unchanged, and they now also carry the KR judgment ledger
(`kr_stance.json`). The learning section stays. US is unchanged: its reader is
still the individual named in `brief-report-writer.md`. Where this file says
"trader aspirant", read "hedge fund manager" for KR only.

## Activation — first publication on 2026-09-11 KST

The original research handoff, closing review and presence check start
at US `report_date >= 2026-09-10` and KR `report_date >= 2026-09-11`. These are
market-session dates, not the machine's run date. This activation rule governs
the review-section entries and handoff pointers in both writers and runbooks.
For earlier sessions, keep the existing report structure and skip the new
review handoff/block/presence check. Do not republish an existing post to add
review material. Evidence discipline applies whenever writing new prose. The first
eligible issue bootstraps if its predecessor has no learning question.

## Research handoff

Add `학습·복기` to `research_notes.md` before handing it to the writer:

1. **Previous question.** Read the latest committed same-market daily post whose
   filename date is strictly earlier than `report_date` (`posts/` for US,
   `kr/posts/` for KR). Record its path, date, learning question, original test
   condition and deadline. Use its learning block only, not the editor's personal
   note. If it has no learning block, bootstrap; do not invent a previous question.
2. **Material question.** Choose a material move or a useful non-reaction in today's data.
   Record the observation, one explanatory hypothesis, a plausible alternative
   where supported, and the evidence that could distinguish them. An unknown
   cause is a valid research outcome; never manufacture a competing explanation.
3. **One calculation, when supported.** Reuse an existing calculated field first.
   Otherwise run simple arithmetic in Python using canonical input values: e.g.
   `(long yield - short yield) * 100` in bp when inputs are in percent, or
   `change in long yield - change in short yield` when changes are already bp.
   Record input file/fields, values, units, both dates, formula, executable command
   and result. Check that dates, tenor definitions and comparison windows match.
   Writer copies this checked result; this is the narrow numeric-source exception
   for the learning block and the KR rates section’s specified spreads, not
   permission to calculate portfolio performance.
   Missing inputs → qualitative reasoning with the missing evidence stated. No invented
   market quotes, notionals, DV01, hedge ratios or P&L examples.
4. **Next test.** Name one observable condition, the instrument/series to watch,
   and a next-session or named-event horizon. Event dates/times need a source and
   timezone. State what would support or weaken the hypothesis; avoid arbitrary
   price targets. Record source URLs and observation times for research evidence.

Keep canonical prices in their existing data files. This handoff supplements
them with explanation and reproducible analytical arithmetic, not a second price
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

- Check **observation, possible mechanism and distinguishing evidence** across
  the explanation, without repeating this sequence in every paragraph. Reserve
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
  qualification when using the familiar label `기대인플레` to explain the interpretation.

## Writer output

Follow the daily reading path in `DESK_REPORT.md`. Explain a concept briefly where
it helps assess the evidence; no daily concept or exercise quota. Reproducible
calculations belong in the handoff and appear in prose only when they resolve a
material question. Strategy comments give the current interpretation, conditional
investment relevance and falsifier; the closing section reviews prior reasoning.

Append one `<section class="card" data-learning="daily">` with the heading
`시장 판단과 복기` after the existing final content section and before the disclaimer.
The legacy `data-learning` attribute is retained for compatibility. Add the cycle
and hypothesis attributes from `RESEARCH_WORKFLOW.md`. Use connected prose:

- Compare the prior hypothesis, original observation window and condition with new
  evidence. Link its original issue with its actual date; distinguish support,
  weakening and undecidable outcomes. Direction alone does not prove mechanism.
- Explain changes to the interpretation and the strongest unresolved alternative.
  Do not repeat the opening's complete market summary or reprint an entire idea.
- Retain every open ledger question and its next distinguishing observation or
  original deadline. Unchanged items can be brief. Include today's closed failures
  and reviewed nonexecution; a bootstrap honestly has no prior view to evaluate.

Definitions and methodology are subordinate to the decision question. Calculations
still require the research handoff and aligned canonical inputs. No invented
portfolio, customer flow, hedge ratio, VaR or compulsory risk-limit number.

## Editorial check before publishing

After drafting and again after prose editing, apply `DESK_REPORT.md`'s acceptance
checks. Verify the review block and cycle markers; previous question/date/condition
accurate or genuine bootstrap; calculations reproducible with aligned inputs;
causal uncertainty preserved; unresolved questions carried; no future information;
market numbers from canonical collected inputs. Review causal claims throughout
the report. Repair failed paragraphs, then run existing gates plus the research
checks. Automated reference matching complements, but cannot replace, semantic review.
