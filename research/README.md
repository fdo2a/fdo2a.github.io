# Research ledger

Internal research evidence for **new** US/KR reports. No historical post edits, fictitious hypotheses, seeded results, trade execution, or automatic claims of proven edge. A missing ledger is a valid empty bootstrap. `ledger.jsonl` and `evidence/` are created only when a real record is appended. Commit both together after review; `.lock` is merely a local advisory lock, not evidence.

## Commands (from site/)

```sh
python3 scripts/research_ledger.py template --kind hypothesis --market us > /tmp/hypothesis.json
# Fill every field from actual evidence; placeholders are not publishable.
python3 scripts/research_ledger.py append --input /tmp/hypothesis.json --root research/us
python3 scripts/research_ledger.py validate --root research/us
python3 scripts/research_ledger.py summary --root research/us --market us --start 2026-09-01 --end 2026-09-20 --as-of 2026-09-20T23:00:00+09:00 --out /tmp/research-summary.json
```

`template --kind review` and `template --kind cycle` expose the other input shapes. `--root` is required: use `research/us` for US and `research/kr` for KR (keep markets in their designated roots). `append` uses the actual UTC clock; there is no CLI clock override. `--as-of` is a read cutoff, not a way to backdate records. Library: `append_record(root, payload, now=None)`, `read_records(root)`, `summarize(root, market, start, end, as_of)`; `now` is for deterministic tests only. Errors return CLI exit 1; validation never silently skips bad lines.

## Input schema

All records are flat JSON objects. Unknown top-level keys are rejected. Required common fields:

| Field | Contract |
|---|---|
| `id` | Unique nonempty stable ID chosen by author; retrying identical input and source bytes returns the original record; changed input or evidence bytes under the same ID fails |
| `type` | `hypothesis`, `review`, or `cycle` |
| `market` | `us` or `kr` |
| `report_date` | ISO calendar date, no later than recording date in the market timezone (New York / Seoul) |
| `data_cutoff` | Timezone-qualified ISO timestamp, no later than recording time |
| `sources` | List of `{id,path,provenance,published_at,observed_at}`; hypothesis/review require at least one |

Source IDs must be unique per record. `path` is a local evidence file; `provenance` identifies its public URL or original source. `published_at <= observed_at <= data_cutoff`. Copy only the relevant publicly shareable evidence; **never snapshot credentials, secrets, account identifiers or private statements**. Redact private identifiers before supplying an artifact and describe that in provenance. API does not fetch URLs. Input paths resolve against the CLI working directory. The retry fingerprint includes source byte hashes and all source metadata but excludes local paths, so moving an unchanged source file preserves idempotency. Retry needs the source files to remain available; reading existing records uses the stored snapshots.

Append stores a byte-for-byte content-addressed evidence copy. In stored sources, `path` is replaced with `sha256` and `snapshot: "evidence/<sha256>"`. Generated top-level fields are `recorded_at`, `previous_hash`, `input_hash`, `hash`, and hypothesis-only `prospective`; supplying any of them fails. Every read verifies the chain, schema, timestamps, source bytes and references. Do not edit prior records; append a review or use a new hypothesis ID when changing a premise.

### Hypothesis

Required text: `title`, `question`, `observation`, `our_view`, `difference`, `mechanism`, `alternative`, `support`, `invalidation`. Separate the observed fact, interpretation, strongest competing explanation, and falsifier. `stage`: `observation|insight|idea|edge_candidate`. There is intentionally no `verified_edge` stage.

`expectation`: `{kind,description}` where kind is `unknown|survey|market_price|narrative`. A known baseline also requires `instrument`, `horizon`, `source_ids` referring to this record's sources. Do not equate survey consensus, OIS/futures pricing and press narrative. When unmeasured use `unknown` and explain the gap; a plausible story is not market consensus.

`test_start_at` and `deadline`: required timezone-qualified timestamps, with test start no later than deadline. The test start names the first future discriminating observation used to evaluate this hypothesis, not an arbitrary future date. Only `recorded_at < test_start_at <= deadline` is prospective; otherwise it is retrospective and excluded from prospective counts. An already observed event cannot be recast as a prediction by extending the deadline. A hypothesis motivated by that event may predict a later observation if its test start is honestly specified. This classification cannot independently prove honest preregistration; inspect the source/cutoff/event times. `execution_status`: `planned|watch|not_taken`, preserved in summaries even after failure. No actual P&L belongs on hypotheses.

For `idea|edge_candidate`, `trade` requires nonempty text `instrument`, `why_now`, `catalyst`, `horizon`, `risk_limit`, `exit`, `implementation`, `cost_assessment`. Explain the proposed exposure, pricing catalyst, implementation and relevant spread/slippage/financing/roll or carry costs. Keep the risk limit and exit separate from `invalidation`. Missing cost evidence must remain explicit uncertainty, never an invented estimate. Insight/observation do not require a trade.

Optional `event` records reproducible announcement evidence:

```json
{
  "name": "Actual event name",
  "scheduled_at": "2026-09-20T10:00:00Z",
  "expectations": [{"kind":"survey","instrument":"Actual measure","horizon":"Reference period","source_ids":["pre"],"observed_at":"2026-09-20T09:00:00Z","value":3.1,"unit":"percent"}],
  "actual": {"value":3.2,"unit":"percent","source_ids":["release"],"observed_at":"2026-09-20T10:00:00Z"},
  "reactions": [{"window":"immediate","instrument":"Actual instrument","start_at":"2026-09-20T10:00:00Z","end_at":"2026-09-20T10:30:00Z","before":4.1,"after":4.15,"unit":"percent","source_ids":["prices"]}],
  "missing": []
}
```

These numbers illustrate shape only; **do not append this example**. Expectations must precede the event and cannot cite a source observed later than the expectation. Actual observations and reaction intervals must fall between event time and cutoff. Values are optional, but supplied numeric values must be finite and have units; `before/after` must come together with the same unit. `window` is `immediate|close`. Incomplete expectations/actual/reactions require nonempty `missing` reasons. Never infer intraday or pre-event observations from one daily closing price. Different measures/units must not be subtracted as a surprise; the ledger does not compute surprises automatically.

### Review

`hypothesis_id` must reference a preceding hypothesis in the same market. `direction` and `mechanism` each take `supported|weakened|undecidable`, independently. `status` is `open|closed`; `rationale` is required, supported by new `sources`. Review `data_cutoff` must be at or after hypothesis registration. A correct direction does not establish a correct mechanism or profitable implementation.

Default `performance`: `{status:"unavailable",reason:"Actual reason"}`. Unknown costs or absent realized-performance evidence remain unavailable. For prospective hypotheses with externally measured, comparable results only, `status:"verified"` requires:

- `basis`, `unit`, `benchmark_name`, `cost_basis`, and `source_ids` for the supporting artifact;
- `start_at < end_at <= data_cutoff`, with the start at or after the original recording time;
- finite numbers `gross`, `costs`, `net`, `benchmark` in the same unit, on the same capital basis and interval; nonnegative costs, with `net = gross - costs`.

Here `verified` labels an author's externally evidenced measurement, **not independent verification by the program**. The program cannot establish that a source proves a return or that all costs were included; reviewers must inspect the snapshot. Benchmark matching and cost completeness require human judgment. No backtest, actual transaction, excess-return average or validated edge is manufactured. Prospective and retrospective records remain separate in the output.

### Cycle

Required `central_questions`: one or two nonempty questions; `candidate_ids`: zero to two existing same-market hypothesis IDs; `reviewed_ids`: existing same-market review IDs; `unresolved`: `[{hypothesis_id,reason}]`. With no candidates, `no_candidate_reason` is mandatory. Every same-date hypothesis must appear in `candidate_ids`, and every same-date hypothesis’s latest review must appear in `reviewed_ids`, including closed failures. Reviews from another report date or superseded reviews cannot satisfy a cycle. A replacement cycle can use a new ID and include the same complete same-date records. Every still-open hypothesis must be covered by a current candidate, cited review or explicit unresolved reason; no daily idea quota. `reviewed_ids` holds **review record IDs**, not hypothesis IDs. Stale citations are rejected; use an unresolved reason when there is no fresh review. The cycle data cutoff is its information cutoff, so hypotheses/reviews may be registered later than that cutoff but before the cycle; their own evidence cutoffs remain enforced.

## Summary interpretation

Output: `market,start,end,as_of,counts,hypotheses,cycles`. Counts: `total,prospective,retrospective,open,overdue`. Rows contain `id,title,stage,report_date,recorded_at,deadline,prospective,execution_status,status,overdue,direction,mechanism,performance,latest_review_id`. Missing reviews show `not_reviewed` and unavailable performance. Latest status is determined only from records at or before `as_of`.

The cohort includes hypotheses **recorded** during the requested calendar interval, hypotheses reviewed during it, and earlier still-open hypotheses. Thus failures, nonexecuted ideas and carry-over questions do not disappear. Dates for recording/review cohorts are UTC; report dates are separately preserved. Closed older hypotheses outside the interval are not included. All earlier open rows are carried even if not overdue. End date cannot exceed the UTC date of `as_of`. No observation after the as-of time affects the view, although integrity checking still validates the complete stored ledger.

A local hash chain detects accidental changes and evidence corruption. It is **not an external timestamp or tamper-proof audit**: someone controlling the repository can rewrite the entire chain or delete a suffix. Commit evidence and ledger together, retain Git history, and use independent timestamps if external proof of preregistration is required. Shared read locks and exclusive append locks prevent readers seeing a partially written line and serialize local appends, not writes from other machines; merge ledger histories deliberately rather than auto-concatenating.
