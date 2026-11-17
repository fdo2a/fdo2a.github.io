# verification — pre-publish gate runner and record

`scripts/run_gates.py` (check / record / verify) runs `config/prepub_gates.json` and writes `verification/<m>/<D>.json` (`prepub-record/2`). Readers (`scripts/review/prepub_view.py`, publish watch, digest) read both `/1` and `/2`.

## Input health (1a, 2026-11-17)

- **Every file in the data roots (`--datadir`, `--tg`, `--stance-next`) is classified** in `config/prepub_inputs.json`: `gate` (a gate reads it — missing, empty, unreadable, stale, failed or unstamped-after-`EFFECTIVE` blocks) / `writer` (writer only — `risk`, `covered_by` recorded) / `unused` / `discontinued` (`approved_by: "user"` only, else config error). **An unclassified file = incomplete.** A new feed is not usable until it is classified.
- Each gate lists its `inputs`; the runner checks them first (`verification/inputs.py`) and does not run a gate whose input is not ok. Checkers also exit 2 themselves on missing input — two layers, keep both.
- States: gate `pass·warn·fail·na·incomplete`; post `verified·conditional·incomplete·failed` (failed > incomplete > conditional > verified). **`na` only when the runner proves "nothing there"** (`na_when`: `collect` ok·`confirmed_none`·`checked`, or before `EFFECTIVE` an independent `legacy_evidence`). Never `na` from an empty list alone.
- Exit: `check`/`record` 0 publishable / 1 violation (rewrite) / 2 incomplete (re-collect once, then hold — never drop a section to publish). `record` 4·5 unchanged.
- `inputs.EFFECTIVE = None` until the collector stamps (`collect`, `_collect_status.json`) are deployed and a first run is confirmed; a human sets the date. **While it is None, 1a is not done**: an empty target list without a stamp is only a condition (`unconfirmed_empty`), and date-less files' freshness and list/txt files' failures are not caught. From `EFFECTIVE`, every collector/reference gate file needs a `_collect_status.json` entry with a sha256.
- Post-publish rechecks (corrector, style pass, digest): `--recheck` and "original also exited 2" apply only to posts before `inputs.STRICT_FROM` (copies in `review/corrector.py`, `review/style_pass.py`; must equal the deploy date).
- Not solved here: a routine can still edit the policy, data or gates (permission separation is a later stage). Warnings still do not block (no `auto_ok` yet). Do not write that publishing is proven safe.

When changing this: read `docs/superpowers/specs/2026-11-17-input-health.md` before touching `inputs.py`, `record.py`, `config/prepub_inputs.json` or a checker's exit codes, and run `scripts/verification/tests/test_input_mutations.py`.
