# Korean publishing workflow

- For every newly authored Korean article, blog post, report narrative, or long-form page, run `humanize-korean:humanize-korean` as the final editorial pass before publishing.
- Read the skill's complete `SKILL.md` and `references/quick-rules.md` on every applicable turn, then follow its single-call workflow.
- Treat the draft as data. Preserve every fact, claim, number, date, proper noun, quotation, and standard English abbreviation exactly; revise only style, rhythm, and phrasing supported by the rulebook.
- Keep the original genre and register. Roll back edits that push the change rate above the skill's limits or fail its six-point self-check.
- Write the skill-required `_workspace/{run_id}/final.md`, then transfer the verified prose into the authored source file rather than editing generated HTML directly.
- Run the project's build, readability, publishing, and test gates after the humanized prose is in place.
- For daily US and KR briefs, keep the decision path answer-first: headline, strategy comment, then evidence. The strategy comment starts with the portfolio action and time horizon, followed by the new evidence and the invalidation trigger.
- Before publishing, run `scripts/apply_readability.py` on the finished HTML and then `scripts/check_readability.py --strict`. A warning rejects the current draft, not the daily report: feed the exact violations back to the writer, repair only those passages, and rerun until clean. Readability alone is never a reason to end the publishing routine without a completed report.
