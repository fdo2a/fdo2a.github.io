# Korean publishing workflow

- For every newly authored Korean article, blog post, report narrative, or long-form page, run `humanize-korean:humanize-korean` as the final editorial pass before publishing.
- Read the skill's complete `SKILL.md` and `references/quick-rules.md` on every applicable turn, then follow its single-call workflow.
- Treat the draft as data. Preserve every fact, claim, number, date, proper noun, quotation, and standard English abbreviation exactly; revise only style, rhythm, and phrasing supported by the rulebook.
- Keep the original genre and register. Roll back edits that push the change rate above the skill's limits or fail its six-point self-check.
- Write the skill-required `_workspace/{run_id}/final.md`, then transfer the verified prose into the authored source file rather than editing generated HTML directly.
- Run the project's build, readability, publishing, and test gates after the humanized prose is in place.
