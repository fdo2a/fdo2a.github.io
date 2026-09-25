# Research workflow — future reports

Read before researching, writing or reviewing a new US/KR daily, weekly or monthly
report. Read `.claude/DESK_REPORT.md` first for the market-coverage and PM-facing sales/research mandate. Use alongside `TRADER_LEARNING.md` (evidence discipline) and the common
writer (prose). Applies to newly authored reports after this change; **never
backfill hypotheses from outcomes or rewrite published reports to add these fields**.
This is research, not an order, portfolio or position-sizing system.

## What the research must answer

Choose one or two central questions before drafting. Broad market coverage remains,
but spend depth on the event or divergence that could change a decision. Initially
concentrate on US releases → policy pricing / yield curve, and US → KR rates / FX
transmission. Other topics need material evidence, not a daily idea quota.

Distinguish observation, insight, investment idea and edge candidate. Never promote
an interesting narrative to a proven edge. For each candidate, identify what price
appears to assume, why our interpretation differs, what could reveal the difference,
and what would falsify it. Unknown market expectations remain unknown. A correct
forecast already priced in may have no investment value.

Research fields are **internal checks, not a fixed paragraph template**. The report
should read as a connected explanation of the question, evidence and decision.
Place the relevant short definition beside the event; recurring theory and extended
limitations belong in learning/recap. Preserve uncertainty next to the affected claim.

## Evidence packet before writing

Use the real JSON shapes and commands in `research/README.md`. `sources` preserve
public evidence bytes, provenance, publication time and collection/observation time.
A source fetched today cannot establish that we knew it yesterday. `recorded_at` is
assigned by the command, not the author. Daily closes do not establish immediate
announcement reactions, and a market-price series is not a survey consensus.

When a release is central, populate the optional `event` packet:
- pre-release expectations: survey / market pricing / press narrative separately,
  exact instrument, reference period, unit and observation time;
- actual release including revisions and the relevant component; write the revision
  in `observation` and preserve its source instead of replacing the prior vintage;
- immediate and closing reactions with instrument and window; use existing canonical
  quotes or a verified source copied into the evidence packet;
- missing expectations, OIS, intraday quotes or components explicitly in `missing`.

Use the collector's public files first. The research step may retrieve a missing
public expectation or policy-pricing observation with source/time evidence; do not
change the canonical price table or invent an unavailable series. No new paid feed
or unsupervised intraday collector is introduced. If pre-event evidence wasn't saved,
explain the event retrospectively and register only the next genuinely future test.
Do not copy a post-event estimate into the pre-event slot.

For idea/edge-candidate records, explain the instrument, why now, catalyst/horizon,
implementation, possible gain/loss drivers and applicable spread, slippage, carry,
roll and financing costs in `trade`. `risk_limit`/`exit` govern the proposed exposure;
`invalidation` concerns the explanation. Do not invent prices, probabilities,
notionals, expected returns or execution data to complete an idea. An observation
or insight may stop short of a trade. Record nonexecution explicitly.

## Daily — register, revisit, write, check

Use separate roots to avoid US/KR publication branches appending the same file:
`research/us` and `research/kr`. Work from `site/`; scratch inputs and draft copies
live under `.research-drafts/<market>/<report_date>/` (ignored). `D` below is the
actual market report date, never today's machine date. `R` is the corresponding
research root. Commands use paths relative to the repo or absolute paths.

1. Read and validate `R`; a missing ledger bootstraps empty. Read all open hypotheses
   and their original deadlines/conditions. Preserve unresolved hypotheses rather
   than silently replacing yesterday's question with a new one.
2. Use `template --kind hypothesis|review|cycle --market us|kr` to prepare JSON.
   Register zero to two new hypotheses. Set `test_start_at` to the start of the predicted observation window and `deadline` to its end. Only `recorded_at < test_start_at <= deadline` is prospective; a future deadline alone does not make an already observed event a forecast. With zero, record
   the actual no-candidate reason in the cycle. Append reviews for changed evidence;
   for every other open question provide an `unresolved` reason. Do not manufacture
   an alternative: state the evidence gap in the required text field.
3. Append hypotheses, then reviews, then the cycle, in that order:

```sh
python3 scripts/research_ledger.py append --input <hypothesis-or-review.json> --root <R>
python3 scripts/research_ledger.py append --input <cycle.json> --root <R>
python3 scripts/research_ledger.py validate --root <R>
```

   Save the returned cycle ID. Pass the cycle, its referenced records and evidence
   to the writer. Preserve original records; a changed premise becomes a new ID
   referring to the old ID in its explanation. Resubmitting identical input is a
   retry, not a new forecast. Append-only records from failed publication attempts
   remain research history; they are not claims that a report was published.
4. In `시장 판단과 복기`, retain `data-learning="daily"` and add
   `data-research-cycle="<cycle-id>"` to the same section. Mark each candidate,
   reviewed or unresolved hypothesis discussion with `data-hypothesis="<id>"` on
   its paragraph. `reviewed_ids` in JSON contains review IDs; HTML uses the referenced
   hypothesis ID. Give unchanged open items a short continuation, not a fresh essay.
   With no candidate, explain the actual reason and the central question. Research
   stages/filenames/field names are not reader-facing labels.
5. Preserve the new draft before structural editing, then compare it with the edited
   draft. This comparison never reads or changes an old published post:

```sh
python3 scripts/check_research.py compare --before <draft-before.html> --after <draft-after.html> --out <editorial-review.json>
python3 scripts/check_research.py check --span daily --html <draft-after.html> --root <R> --market <us-or-kr> --date <D> --cycle <cycle-id>
```

   Read the repeated sentences/internal-note hits, then manually confirm that each
   paragraph adds information, the central question is answered, and causal links
   are supported. The metrics are advisory; they cannot judge semantic repetition
   or guarantee good prose. Preserve numbers/qualifiers through existing source
   checks. Run the research check again on the final humanized HTML; include that
   exact command as a `humanize_prose.py finalize --gate` entry.
6. Publish only after the existing gates and research check pass. Commit the ledger
   and `evidence/` for that market alongside the new post. Do not commit `.lock` or
   scratch files. A research-data error requires correction; lack of an investment
   idea is not an error. No order, portfolio update or new notification is implied.

Hash chains and locks detect local corruption/concurrent appends, not malicious
rewrites or independent-clock proof. Keep Git history. If another branch appended
records, preserve its chain and replay the uncommitted input through `append` after
updating; never concatenate chains or choose one side and lose records. Use the
existing publish retry procedure, and re-run all checks after reconciliation.

## Weekly — deepen the important questions

Read only the period's published reports, existing evidence and the ledger; no new
quote collection is required. Choose one or two consequential hypotheses, including
failures/non-reactions, and explain what changed in our interpretation. Do not turn
five daily summaries into five paragraphs or require a fresh trade idea.

Freeze `AS_OF` once at review start (real timezone-qualified time, not a future
cutoff). `START`/`END` are the aggregate's market-session dates. The summary's record
cohort uses UTC recording dates and carries older open items; label late-recorded
work as such, never shift its registration date to fit the period.

```sh
python3 scripts/research_ledger.py summary --root <R> --market <us-or-kr> --start <START> --end <END> --as-of <AS_OF> --out <research-summary.json>
python3 scripts/check_research.py render --root <R> --market <us-or-kr> --start <START> --end <END> --as-of <AS_OF> --out <research-summary.html>
```

Insert the generated section unchanged alongside the narrative recap. It is the
single source of displayed research counts/outcomes. It reports the cohort and
open/overdue items, not a win-rate or proof of alpha. Keep original title/claim
semantics when discussing evidence; do not import numbers from arbitrary ledger
text into unrelated market prose.

Run `check_period.py` with its normal arguments **plus**
`--research-root <R> --research-as-of <AS_OF> --market <us-or-kr>` before and after
humanization. It rebuilds the summary from the verified ledger and accepts its
numbers only inside the exact generated section; the rest of the report retains
normal price/number provenance. The generated section is excluded from prose
humanization by the humanizer's marker rule. Also run:

```sh
python3 scripts/check_research.py check --span weekly --html <draft.html> --root <R> --market <us-or-kr> --start <START> --end <END> --as-of <AS_OF>
```

If the ledger is empty, display that there are no records to evaluate. Never seed
old winning forecasts to make the scorecard look established.

## Monthly — evaluate the decision method

Use the same summary/check commands with `--span monthly` on the report check.
Group the reasoning in prose by recurring research question, not by winning ticker.
Assess direction, mechanism and implementation separately, include failures,
undecidable cases, overdue questions and ideas deliberately not executed.

Only use externally evidenced, comparable gross/cost/net/benchmark measurements
where the record contains the full basis and interval; missing costs or execution
leave performance unavailable. Inspect the evidence even when arithmetic validates.
Do not average incompatible units or describe a count of correct directions as
excess return. The generated section deliberately does not print return estimates.

Before calling a method repeatable, freeze its conditions and benchmark in a new
hypothesis's explanation, then evaluate later observations without changing those
conditions. A revised method gets a new ID/version in the title/explanation and a
new forward test; prior failures remain. Separate exploratory/backward-looking
cases from future tests, check regime dependence and relevant costs, and record
sample limitations. No automatic stage named “proven edge” exists. Decide which
question deserves further evidence, which to retain and which to abandon.
