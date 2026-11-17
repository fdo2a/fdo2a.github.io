# Telegram notes in the Japan daily close brief — 「증권사 견해·시장 의견」 (2026-11-15, built 11-16)

User request (2026-11-14): 「이 채널(t.me/aethersemiconductor)에 일본 관련 글도 많이 올라오는데 일본 글에도 이 내용들이
들어가도록 해」. Direction confirmed twice (11-15, 11-16): a 「증권사 견해·시장 의견」 section in the **Japan daily**
(`/japan/daily/<S>.html`) right after 「일본 경제 뉴스」, this one channel only, written as hearsay, collected
inside the Japan daily collection as a non-blocking step. Not the weekly; not as the cause of a mover; no other
channel.

Standing user decisions: Telegram ToS risk accepted; a published page never contains 「텔레그램」, a channel
name or t.me; post text is never committed (summaries only, tests use synthetic sentences); no per-channel
minimum; no count cap on what a post may quote.

Builds on `docs/superpowers/specs/2026-11-12-telegram-news-posts.md` (`common/telegram.py`, `tg_summary.py`,
`fetch_telegram.py`, `tg_news.py`, `common/telegram_gate.py` layout 'news').

## Why this shape

Four codex design rounds (findings 15 → 12 → 8 → 5; **no DESIGN OK was obtained** — round 4 had no blocker and
its five findings are all in the design below). Implementation review round 1 (11-17): six findings, see
「Implementation review」 at the end. Rounds 1-2 kept finding holes in one thing: a read position
(cursor) kept between runs plus rules for when the file stops changing. The design that survived has **no
cursor and no state carried between sessions** — the posts of session S are a function of S alone, and one
`usable` flag, written in the single final save, decides everything downstream. Round 3 found that anything
depending on publication history can change after the fact, so the window is the session calendar and the
publish step pins the bytes its gate saw.

## Measurements (channel fetched 2026-11-14; raw text stayed outside the repo)

- 11/07-11/14: 243 posts; hand-read 7 clearly about Japan + 2 borderline. The rule below finds those 9 and no
  others (**in-sample** — tuned on these posts). About one a day.
- A naive regex (일본|니케이|엔 …) hit 11, 7 wrongly: 「일은」, brokers as note authors, 「니케이」 as the outlet of a
  non-Japan story, a passing 「일본」.
- 11/06 bulk re-upload: 2,037 posts in 3 hours, 1,744 opening with their original date (「🗓 2026.08.05 원문」,
  「↪️ … 에서 전달 · 2026.08.21」); none of the recent posts do. Rule hits in the dump: 131 marked, 24 unmarked
  (continuation messages — a long note is split, and only the head carries the date). With the stale and
  burst rules the 11/06 session gets 0 candidates.
- Volume by original date (95 days, 8/2-11/5): 129 hits, 1.4/day, max 8 in a day, 18 in any 6 days.
- Most Japan posts are relayed foreign-broker notes with no link; the title line starts 「JP모건) …」
  「모건스탠리) …」「닛케이) …」. Prefixes seen across all 2,280 posts: JP모건 175, Citi 168, BofA 21, 블룸버그 16 …
- Also found on the real posts: the channel's own notice (「… pinned «…»」) and its name 「일본&미국」 matched the
  country rule; 40- and 63-character remarks matched a company name. Both are filtered now.
- A real collector run (11/16, Monday window = 3 days + the 12 h margin): 5 pages, 15 s, floor reached.
- Published dailies (14, 10/27-11/16): all pass the changed gate with no file. With a synthetic usable file
  whose notes say **exactly** what three of that day's published articles say, 11 of 14 failed on the writer's
  own sentences until the 「an article of the day says it」 rule (§C) — the prose of a Japan daily is
  written from the news file.
- Typesetting: the section survives `apply_readability`; `check_readability --strict` and `check_style` pass;
  390 px and 1280 px keep `scrollWidth == viewport`.

## A. Collection — a separate jp path

`scripts/common/tg_jp.py` (pure rules) + `scripts/fetch_telegram_jp.py` (CLI). Reuses `read_channel`, `curl_get`,
`fetch_origin`, `carry_summaries`, `_save` from `fetch_telegram.py`, the helpers of `common/telegram.py`,
`tg_summary.summarize` and `skip_reason` (moved to `common/tg_use.py`, re-exported by `tg_news.py`). It does not
go through `collect()`, `frozen()`, `previous_file()`, `with_run_cursors()`, `classify_post()` or `select()`.
The one edit to shared collection code: `read_channel(..., track_reached=True)` adds `st['reached']` — true
only when a post below the floor was actually seen (a page with no `before` link is the channel's first post
or a link the parser no longer recognises; not told apart, so neither counts). Off by default, so US/KR files
keep exactly their keys.

1. **Channel**: `JP_CHANNEL = 'aethersemiconductor'`.
2. **Japan relevance** `jp_basis(text)`: `'keyword'` when a Japanese market word (`JP_MARKET`: 일본은행, BOJ, 일본
   증시, 닛케이 225/지수/평균, TOPIX, JGB, 일본 국채, 엔화·엔저·엔고, 달러/엔, 엔 캐리 …), a ticker (`6857.T`, `8035 JP`)
   or a listed company (`JP_NAMES`, ~120 names in Korean and English) starts within the first 160 characters,
   or market words occur 3+ times; `'country'` when 「일본」 (not 일본은행, not the channel's 「일본&미국」) opens the
   post and occurs twice. Not listed on purpose: bare 「닛케이」 (the newspaper) and brokers/banks (they author
   the notes). A Korean name must start a word and must not run on into a listed other word (`디스코(?!드|텍…)`)
   — a blocklist of compounds, so every particle form matches.
3. **Item**: the US/KR fields plus `note_date` (the leading date marker) and `relay_firm` — the title line's
   leading 「이름)」 looked up in `RELAY_FIRMS` (variants → one name; ambiguous short forms MS/GS/DB left out).
   The same prefix naming an outlet becomes `source` (`basis: 'credit'`).
4. **Window** `(floor, ceiling]` = 16:30 JST of `--prev` to 16:30 JST of S — the session calendar only, so it
   cannot change after the fact, consecutive windows neither overlap nor leave a gap, and a note cannot be
   offered twice. A session that was never published takes its notes with it (the daily has no backfill).
   The reader goes 12 h below the floor so the burst guard sees a re-upload that straddles it; the window is
   applied afterwards as `floor < dt <= ceiling`.
5. **Left out before a summary is asked for** (`build_items`, the US/KR rule reused): a post linking an
   article whose own date is more than `fetch_telegram.STALE_DAYS` before the window floor
   (`stats.stale_dropped`) — a new post about old news is not that day's note.
5a. **Left out, in this order**: outside the window; a remark (US/KR chatter rule, a service line, or under 80
   characters with no link); a stale note (`note_date` more than 2 days before the JST day the post was
   made — not before S: a note dated Friday and forwarded on Saturday is Monday's); the burst (when 20+ posts
   read carry a stale date, everything from the first of them to 120 s after the last, marked or not); not
   about Japan; a second post linking the same original. Counts in `stats`.
6. **No editorial cap.** Safety valve `JP_VALVE = 40` (keyword before country, then score); `stats.valve_dropped`.
7. **Summaries**: carried by id only from **this session's** earlier, non-usable file; then `news_use` /
   `news_skip` by `skip_reason()` (`dup_url` against `japan/data/news/daily/<S>.json`).
8. **One save, at the end.** `usable: true` only when the run started at or after the ceiling, the channel
   status is `ok` and `reached`, and the summariser was not stopped (no client / auth failure). A single failed
   item does not spoil the file; a day with nothing is usable. Otherwise `unusable_why` says why and the
   collector exits 1 (the step is `continue-on-error`).
9. **Refusals** (exit 0, nothing touched): the file is already usable; the session is published. Nothing is
   carried to a later session — what was not summarised by publication is dropped.
10. **Publish pin**: `publish_japan_daily.py`, before it writes anything, reads the collector's file once; if
    usable it re-runs the Japan daily gate on the placed post against that content and writes those bytes to
    `japan/data/telegram/published/<S>.json` (section or not — the whole-page checks used it). Not usable →
    gate without a file, nothing pinned. Gate failure → **exit 3**, nothing written. `build_japan_daily.
    telegram_path()`: published session → the pin or absent; unpublished → the collector's file.
11. **Workflow** `collect-japan-daily.yml`: step 「Fetch Telegram notes」 after 「Collect」, before 「Commit data」,
    `continue-on-error`, `timeout-minutes: 6`, the news step's WIF variables; the commit step stages
    `japan/data/telegram/*.json` on its own line (not `.tmp`, not `published/`). Same job because runs are
    serialised (`concurrency`) and the routine never writes that path. The step's tests live in
    `scripts/common/tests`; `scripts/japan/tests` (run before 「Collect」) import no third-party module for this.

## B. Page

Optional, at most one, directly after `news`:
`<section class="card" data-section="views" data-tg-section><h2>증권사 견해·시장 의견</h2><p><span data-tg="…">…</span></p>…</section>`.
One item = one paragraph = one span, ≤300 characters, no linking text. `daily_render.OPTIONAL`, `validate_body`.

## C. Gate

`telegram_gate.check(layout='jp')` = the news-layout rules with:
- `views_node()` — one HTMLParser pass with source offsets decides what the section is; any other element with
  `data-tg`, `data-tg-section` or `data-section="views"` is a violation;
- an opinion with no outlet needs the hearsay frame (`RELAY_WORDS` — a bare 「평가했다」 is a direct statement);
- a `RELAY_FIRMS` name in the paragraph is the item's `relay_firm` or stands in its summary;
- 엔 amounts are figures with a unit; every date token is a part of the note's own date or stands in the
  summary, and a note dated before the session names its day;
- **outside the section**: nothing is left out of the comparison (`data-contested`, a stored summary in its
  block: all ordinary text). A sentence overlapping a Telegram summary ≥0.7 fails **unless an article of the
  day's news file** (`_jp_articles`: every item whose summary is publishable) overlaps it at least as much —
  a sentence closer to the note than to every article is the note's.
  - History of this rule. Design round 2 #3 removed every 「an article says the same」 exemption. The sweep
    over the published dailies showed the cost (11 of 14 fail on the writer's own prose), so it came back as
    「an article **the page carries**」 — placed in the news section or cited by a mover paragraph.
    Implementation review rounds 1-4 then found a counterexample to every way of reading 「carries」 from the
    page: `data-cite` on a `<P>` the daily gate does not read, a hidden ancestor, a hidden child,
    `<div hidden/>`, a `<p>` inside the citing `<p>`. One finding five times: the exemption depended on
    markup the writer controls. Now it depends on none — only on the collector's news file, which the writer
    is handed whole (mover causes already come from any item of it).
  - What that widens, measured on the 14 published dailies: 121 articles in the files against 94 placed on
    the pages (about 2 more a day). An unrelated article does not vouch by accident: of 840 summary
    sentences, the best overlap with any **other** article of the day has median 0.23, p90 0.46, and reaches
    0.7 in 10 — every one a second article on the same event (the same Nikkei close, the same GDP release).
- word rules cover the whole page, the news section included (the message says when the hit is there), **with
  or without a file** (`word_violations`).
- the item rules run on the paragraphs `views_node` returned, not on a second regex reading; when the two
  readings list different ids the page fails.

`daily_gate.check(..., tg=None)`: with no usable file any marker is a violation; the word rules still run. With a file the section's span is cut from the snapshot-number
scan and the prose checks **only** when `views_node` returns it and it equals, character for character, what
the gate's own `_SEC` pattern sees right after the news section. Existing hole closed on the way: only the
`data-mover` paragraphs that were collected and checked are cut from the invented-number scan; one anywhere
else is a violation.

## D. Routine, writer, review

`diag` prints `견해·의견 후보 N건` only for a usable file; the orchestrator hands the file over only when N ≥ 1.
A violation of the section goes back to the writer once (first return only); after that `tg_news.py strip`
(either marker, body or page) and every gate again. Last step: the orchestrator reads the printed
문단/요약 pairs and deletes a paragraph whose meaning differs. STEP 4 stages the pin on its own conditional
line; exit 3 → strip, gates, publish once more. Review: `kinds.optional_evidence()` adds the pin to what
`review_gate._period_evidence` extracts; 「근거 없음」 is still judged on `kinds.evidence()` alone.

## What it gives up (on purpose)

- A file that turns usable after `diag` is not picked up: the routine does not pull between `diag` and the
  publish commit, so writer, gates and pin read one state of the working tree.
- A channel younger than the read floor never yields a usable file (`reached` needs a post below the floor).

- A note posted after 16:30 JST appears the next session, with its date.
- Notes of an unpublished session, and notes not summarised by publication, are dropped.
- A continuation message of a long note is caught only if it names a Japanese company or market itself.
- A company missing from `JP_NAMES` is missed unless a market word or 「일본」 carries the post.
- A post about a broker's own results (미즈호 FG) is missed.
- Two bulk re-uploads inside one read would take every post between them (first stale mark to the last).
- A sentence that says the opposite of its summary with the same words passes the code; the routine reads the
  pairs.

## Implementation review (codex, 2026-11-17)

Round 1, six findings, five taken and one in part:
1. `<span data-tg>` with no value: the shape parser accepted it, the regex reader did not see it, so no item
   rule ran while the section was exempt from the number scan → empty ids rejected, item rules run on
   `views_node`'s paragraphs, the two readings must agree.
2. `<P data-mover="fake" data-cite="n1">` carried an article into the overlap exemption without being a mover
   the daily gate reads → first narrowed to the gate's own mover set, then removed with the rest (round 4).
3. A page with no `before` link counted as 「read to the floor」 → `reached` needs a post below the floor.
4. (in part) 「a file that appears after STEP 3 blocks a page without the section」 — the working tree does not
   change without a pull and the routine has none there; made explicit in the orchestrator, no new machinery.
5. `items: [null]` in a usable file crashed `diag` → such a file is not usable.
6. The word rule did not run without a file → it runs always (US/KR do the same; all 14 published dailies
   still pass).

Round 2: findings 1, 3, 5, 6 closed, 4 judged sufficient; one new MAJOR (a mover paragraph inside
`<div hidden>` still carried its article). Round 3: a hidden child did the same; two minors taken (「엔화약세」
refused by a lookahead that never helped on the 2,280 real posts; the stale-article drop was not in this
spec). Round 4: `<div hidden/>` and a `<p>` inside the citing `<p>`. After round 4 the page-reading was
removed instead of patched a fourth time — see §C 「History of this rule」; `_Summaries`, `_mover_cites` and
`check(cites=)` are gone. `_Views` (the section itself) now reads `<div hidden/>` as an open tag.
Round 5: the news-file rule judged acceptable; one MAJOR — `<br>` between every few words cut a copied
sentence into fragments too short to compare → for layout 'jp' `<br>`/`<wbr>` are spaces, not sentence ends
(US/KR keep their reading). **Where this check stops**: it compares running text as sentences. A sentence
rebuilt on purpose — split over separate blocks, padded with filler, or simply paraphrased — is not caught
by any overlap measure; those are for the routine's reading of the pairs and the post-publish review.
Round 6: **IMPL OK**, two minors — the words are now also banned in attribute values for layout 'jp' (a
description meta is published text; `data-tg` ids excepted); not taken: dropping stale articles before the
40-item valve (the valve bounds how many originals are fetched, and a window has never held more than 8
candidates).
Not taken: making `common.movers.check` (shared with US/KR, unchanged here) refuse a mover paragraph hidden
by an ancestor, and the same `<x hidden/>` reading in the US/KR news layout — existing behaviour of code this
feature does not change.

## First real run (2026-11-17)

Collection: 48 posts read down to the floor, `usable: true`, 0 candidates (34 in the window: 7 remarks,
27 not about Japan — re-read by hand, one mentions Kioxia once at character 831, outside the 160-char head).
The daily was published without the section and the daily word rule did not block it. The path with a real
summary, a section and a pin holding items has still not run.
Found: the routine committed the pin in a commit of its own 9 seconds after the post. Why is a guess — the old
STEP 4.3 had the pin on a second `git add` line inside a long paragraph, guarded by `[ -e …/$S.json ]`: either
the line was skipped or it ran with `$S` unset in that shell and skipped silently. The post-publish review
extracts evidence from the commit that introduced the post (`review_gate.publish_commit`), so a pin committed
later is absent for it. For this run that costs nothing (no section, a pin with zero items). In general a
review without the pin still runs the word rules but cannot compare body sentences with the summaries, and a
page with the section fails for missing evidence (`check_japan_daily.py`, `daily_gate._views`; read from the
code, not from a run). Fix: STEP 4.3 is now one `git add` command whose
`$(ls -d japan/data/telegram/published 2>/dev/null)` stages the pin directory (no dependence on `$S`), then the
commit, then one check before every push: `git status --porcelain` of that directory plus the Telegram paths
of `HEAD` (`git show --name-only`: the commit's changed paths, not its tree) must print nothing — no usable
file that day — or exactly the session's pin, which is a new file whenever 4.2 wrote it — a `??` line means the pin was left out (amend,
only while `HEAD` is the unpushed post commit; never a second commit), anything else stops the run. A failed
line stops the sequence. Run in a scratch repository: no pin, pin, pin left out of the add, pin with `$S`
empty, a stray file of another day in the directory. codex review of this change (3 rounds, round 3 IMPL OK — it accepted the 「not taken」 below): round 1 —
directory-wide add can carry unrelated files (taken as the check above, the add stays `$S`-independent), a
failed commit followed by the amend (taken), 「harmless」 overstated (taken), the 4.4 wording (taken). Round 2 —
the check after a rebase without conflicts (taken: 4.4 repeats guard and check after any rebase), the note
not saying the check reads changed paths (taken). Not taken: 「a pin for S already on origin/main makes the
check stop a correct post, or lets a stale pin through」 — only `publish_japan_daily.py` writes that path, it
refuses a published session, and under 4.3 the pin leaves the clone only inside the commit that adds the post,
so origin/main cannot hold a pin for a session whose post it lacks (the `cat-file` guard stops the run when it
has the post). Not done:
a mechanical check in code — the routine can still skip a line it is told to run.

## Not doing

Weekly; notes as the cause of a move; other channels; raw text in the repo; a per-day minimum; the stale-date
rule for US/KR (the same weakness exists there); carrying a note to a later session. The Japanese edition
`/ja/` needs nothing — its extractor walks published HTML generically.
