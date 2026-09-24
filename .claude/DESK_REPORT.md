# Editorial mandate — market coverage and decision research

Read before collecting, writing or reviewing a new US/KR daily, weekly or monthly
report. The reader is a hedge-fund manager. The report serves as their S&T sales
and research team: explain the market, identify consequential differences in
expectations, and connect supported analysis to possible investment decisions.
This mandate applies to future reports only. Keep published reports unchanged.
China retains its separate economic-learning curriculum; shared prose rules still
apply. US and KR prose uses the `-다` register throughout (2026-09-24), including
news summaries; the shell declares `<body data-register="da">` and `check_style.py`
blocks mixed endings, rhetorical Q&A, workflow vocabulary and 「국채 급등」. Memory thesis pages follow the memory branch below and retain their deterministic generation/state contract.

## Roles and scope

- **Market coverage:** give a reliable account of prices, intraday development,
  breadth/participation as actually measured, macro releases, policy, company and
  industry news. Preserve the existing asset coverage, tables, source conventions
  and conditional sections. A quiet asset can be concise; a missing quote remains
  missing. The reader must still be able to reconstruct the session.
- **Research:** explain what changed, the supporting evidence, the market's measured
  expectation where available, our interpretation, and the strongest supported
  alternative. Identify which observation would distinguish the explanations.
- **Sales:** select what matters to the reader and translate research into a usable
  question or conditional idea: why now, relevant instrument, catalyst, horizon,
  practical limitations and reasons to wait. This is an editorial role, not a claim
  of access to customer orders, dealer inventory, live executable quotes or a
  real sales desk. Attribute public flow data and distinguish turnover from flows.
- **Manager:** owns the investment decision. No actual holdings, mandate, leverage,
  liquidity budget, hedges, risk limits or portfolio weights have been supplied.
  Until supplied, frame asset-level views and conditional ideas, with a horizon
  justified by the catalyst. Do not invent the reader's exposure or assume that
  an idea is suitable for their portfolio. No automatic order or portfolio update.

## Daily reading path

Use the existing section sequence, headings needed by gates, and HTML markers.
Reorganize the purpose and content within them; do not add a second report beside
all the old sections. The four functions below are not four mandatory new cards.

| Existing location | Editorial responsibility |
|---|---|
| Headline | The defining market development and why it matters; no invented portfolio impact |
| 전략 코멘트 | The current decision brief, before the detailed tables |
| 오늘의 장 and asset/flow/news/macro/industry sections | The session record and evidence behind that brief, including material facts outside its central thesis |
| 시장 판단과 복기 | What changed in prior hypotheses, what remains unresolved, and the next distinguishing observation |

In `전략 코멘트`, retain four connected paragraphs and the existing `data-lede`
order. `event`: the consequential development. `meaning`: the interpretation and
its relation to observed expectations, including any evidence gap. `action`: the
conditional investment implication and horizon; observation, waiting for evidence
or no new idea are valid outcomes. `invalidation`: what would change our view.
These are paragraph functions, not repeated visible labels. Expansion/maintenance/
reduction may describe a conditional exposure choice only when its reference is
explicit; do not require such a declaration every day or imply a position exists.

Keep the broad market account even when one or two questions deserve deeper work.
Give each fact a main home. The opening states its significance briefly; the asset
section supplies prices and supporting detail; the closing review records changes
to prior reasoning. Repetition is justified only by a new comparison or implication.
Do not replace actual news summaries with opinions, shrink their existing required
coverage, or repeat a full idea in every asset section.

## From observation to a useful idea

Use the stages and evidence contract in `.claude/RESEARCH_WORKFLOW.md`. A record can
remain an observation or insight. For each material candidate, research must let
an editor answer these questions; they need not appear as a fixed list in the report:

1. What changed versus the prior session, release vintage or original hypothesis?
   Keep the comparison date, instrument and horizon aligned.
2. What does the market appear to expect, and what evidence supports that reading?
   Survey consensus, market-implied pricing and press narrative are different.
   When no priced expectation can be established, say the expectation gap is unknown.
3. Where does our interpretation differ, and what could we be missing? An unusual
   price move alone does not establish mispricing or a profitable disagreement.
4. What catalyst could change that pricing, over what horizon, and what evidence
   would support or refute the explanation? Separate a thesis falsifier from an
   exposure's practical exit/risk limit.
5. How might the view be expressed, and why use that instrument? Compare directional,
   relative-value or hedging expressions only when they help and evidence allows.
   Consider basis risk, liquidity, spread/slippage, carry, roll and financing as
   relevant. Unavailable inputs limit the idea; they are not zero costs. Do not
   invent fair values, hedge ratios, payoff numbers, probabilities or target prices.
6. What changes the decision now? State whether this is worth investigating,
   conditional on a named observation, already sufficiently reflected in price,
   or unsupported. Explain why no action may be preferable. No daily trade quota.

Separate fact from interpretation in natural prose and place uncertainty beside
the claim it qualifies. Scenarios use observable conditions and consequences; assign
probabilities only when a sourced method supports them. Distinguish directional
correctness, explanatory correctness and net investment results in all reviews.

## Handoff — collector to writer to editor

Before writing, keep the existing `research_notes.md` market material and add a
`운용 판단 브리핑` section. The collector supplies:

- the day's broad coverage and data gaps, plus one or two central research questions;
- the observation, dated expectation evidence (or unknown), interpretation,
  alternative, catalyst/horizon and falsifier for each question;
- potential investment relevance and expression only as far as evidence supports,
  with execution limitations and any missing reader constraints;
- links to the canonical input fields, saved evidence and hypothesis/review IDs;
- prior-view changes and all unresolved items required by the research cycle.

Use the existing `학습·복기` handoff for calculation provenance and previous-question
history; reference it rather than duplicating its contents. The writer turns this
packet into connected prose and retains the cycle/hypothesis markers. The editor
checks that the opening's implications have evidence in the body and that the
closing review agrees with the verified ledger. Filenames, internal IDs and QA
steps belong in the handoff, not the reader's prose.

## Weekly and monthly

Maintain the period's market narrative, performance tables and material days. Use
only published daily reports, stored evidence and the verified ledger as specified
in `.claude/RESEARCH_WORKFLOW.md`; do not introduce new research or prices to make
a retrospective idea look timely. Earlier interpretations can be revised openly
when later evidence in the period changes them; preserve what was known at the time.

**Weekly:** synthesize the key market changes, deepen one or two consequential
questions, compare what we expected with what occurred, and carry forward the
conditions that matter for the next period. Include failures and non-reactions.
**Monthly:** explain the regime and cross-asset story, then examine which reasoning
worked or failed under which conditions. Separate untested, retrospective and
prospective cases and measured net performance. Choose what to retain, revise or
abandon. Counts and correct directions alone never establish an investment edge.

## Editorial acceptance before publication

Apply this alongside source/layout/style gates and the research checks. This is a
human semantic review, not a claim that markers or word counts validate reasoning.
A draft is ready only when all applicable checks below pass:

- The session/period can be understood from its coverage; the main thesis has not
  displaced important contradictory or unrelated market developments.
- The opening identifies the consequential change and a supported decision
  implication; it can honestly conclude that further evidence is needed.
- Market expectations and our interpretation are distinguishable, with the main
  alternative or the evidence gap and a useful next observation.
- An offered idea includes instrument, rationale, horizon/catalyst and relevant
  implementation limitations. A missing input is disclosed at the affected claim.
- Prior judgments are compared fairly; failures, unresolved questions and deliberate
  nonexecution survive. All visible research references match the verified cycle.
- No claim assumes access to private flows or the reader's holdings. Numbers and
  causal certainty survive editing. Prose reads as an analytical report, with
  short contextual definitions when useful and no compulsory lessons or exercises.

Repair failed items before applying the existing final publication gates. Do not
publish a daily idea merely to fill a section; do not remove source or research
checks to obtain a smoother narrative.

## Memory thesis — stock-specific decision research

Apply this mandate to Samsung Electronics, SK hynix and Micron on their next normal
page generation. `.claude/THESIS_ORCHESTRATOR.md` and `scripts/thesis/CLAUDE.md`
retain the source, numeric, state-transition and no-trigger silence contracts.
Existing published HTML and historical data are not rewritten for this migration.

The sector overview supplies common demand/supply and cycle context; each company
page explains its own hypothesis, supporting metrics, alternative risks, catalysts
and falsifiers. Present valuation as model assumptions with sensitivity, not a
measured market-implied expectation or a promised return. EPS consensus is an
analyst estimate, not proof of what the share price discounts. If expectations or
execution inputs are unavailable, identify the gap and the next evidence needed.

Existing grades are the research system's assessment of the thesis, not a statement
that the reader owns the stock or should trade. Keep their stored vocabulary and
transition rules; explain this distinction next to the decision view. Do not map
another sector's stock to a memory thesis or borrow its catalysts.

Review the existing state/changelog and open questions rather than create a second
US/KR ledger for the same company. New events should explain which original premise
they support or weaken, their source/observation date, and what remains unresolved.
The generator must expose the decision framing in actual output, not only in these
instructions. Change prose in generator sources, render test fixtures in temporary
folders, and leave existing pages untouched until normal generation. Ordinary
price refresh and an analytical thesis revision remain different operations.
