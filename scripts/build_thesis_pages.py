#!/usr/bin/env python3
"""Build /thesis/ from authored prose + the committed data snapshot.

  python3 scripts/build_thesis_pages.py

Prose comes from scripts/thesis/content.py, numbers from thesis/data/watch.json, grades
and changelog from thesis/data/thesis_state.json. Nothing here invents a figure — that is
the whole point, and the publish gate compares numeric tokens against HEAD to enforce it.

Design: docs/superpowers/specs/2026-08-24-thesis-watch-design.md
"""

import argparse
import html as _html
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thesis import content as C          # noqa: E402
from thesis import render as R           # noqa: E402

OUT = Path('thesis')
DATA = OUT / 'data'

STYLE = '''  :root {
    --toss-blue: #0064FF; --blue-bg: #E8F2FF; --blue-deep: #003EA8;
    --text: #191F28; --text-2: #4E5968; --text-3: #8B95A1;
    --bg: #F2F4F6; --border: #E5E8EB; --border-subtle: #F2F4F6;
    --hold: #0F7B4F; --hold-bg: #E4F5EC;
    --watch: #A8700B; --watch-bg: #FDF2DC;
    --trim: #B4530C; --trim-bg: #FDEBDD;
    --kill: #C13126; --kill-bg: #FDE8E6;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg);
    font-family: 'Toss Product Sans', Pretendard, -apple-system, 'Apple SD Gothic Neo', 'Noto Sans KR', sans-serif;
    letter-spacing: -0.01em; color: var(--text); word-break: keep-all;
  }
  .wrap { max-width: 720px; margin: 0 auto; padding: 28px 18px 60px; }
  header.site { display: flex; align-items: baseline; gap: 10px; padding: 4px 2px 6px; flex-wrap: wrap; }
  header.site .brand { font-size: 24px; font-weight: 800; color: var(--toss-blue); letter-spacing: -0.025em; }
  header.site .desc { font-size: 12px; color: var(--text-3); font-weight: 600; }
  .menubar { display: flex; gap: 2px; flex-wrap: wrap; padding: 0 2px;
             border-bottom: 1px solid var(--border); margin: 0 0 18px; }
  .menubar a { font-size: 13px; font-weight: 700; color: var(--text-3); text-decoration: none;
               padding: 9px 13px; border-bottom: 2px solid transparent; margin-bottom: -1px;
               white-space: nowrap; transition: color 100ms ease, border-color 100ms ease; }
  .menubar a:hover { color: var(--text-2); }
  .menubar a[aria-current="page"] { color: var(--toss-blue); border-bottom-color: var(--toss-blue); }
  @media (max-width: 420px) { .menubar a { padding: 9px 9px; font-size: 12.5px; } }
  .intro { background: var(--blue-bg); border-radius: 14px; padding: 16px 18px; margin: 14px 0 22px;
           font-size: 13px; line-height: 1.65; font-weight: 600; color: var(--text); }
  .intro .small { display: block; margin-top: 6px; font-size: 11px; font-weight: 600; color: var(--blue-deep); }
  h2.list-title { font-size: 15px; font-weight: 800; margin: 26px 0 10px; display: flex; align-items: center; gap: 8px; }
  h2.list-title::before { content: ''; width: 6px; height: 16px; border-radius: 3px; background: var(--toss-blue); }
  .badge { font-size: 11px; font-weight: 800; border-radius: 9999px; padding: 3px 10px; white-space: nowrap; }
  .g-hold { background: var(--hold-bg); color: var(--hold); }
  .g-watch { background: var(--watch-bg); color: var(--watch); }
  .g-trim { background: var(--trim-bg); color: var(--trim); }
  .g-kill { background: var(--kill-bg); color: var(--kill); }
  .cards { display: flex; flex-direction: column; gap: 8px; }
  a.card { display: block; background: #fff; border: 1px solid var(--border-subtle); border-radius: 14px;
           padding: 15px 16px; text-decoration: none; color: var(--text); transition: border-color 100ms ease; }
  a.card:hover { border-color: var(--toss-blue); }
  .card-head { display: flex; align-items: center; gap: 10px; }
  .card-head b { font-size: 14.5px; font-weight: 800; }
  .card-px { font-size: 20px; font-weight: 800; margin-top: 6px; letter-spacing: -0.02em; }
  .card-sub { font-size: 12px; color: var(--text-2); margin-top: 3px; line-height: 1.5; }
  .card-since { font-size: 11px; color: var(--text-3); margin-top: 5px; font-weight: 600; }
  .panel { background: #fff; border: 1px solid var(--border-subtle); border-radius: 14px;
           padding: 18px 20px; margin-bottom: 10px; }
  .panel h3 { font-size: 14px; font-weight: 800; margin: 0 0 10px; }
  .panel .lead, .panel p { font-size: 13.5px; line-height: 1.7; color: var(--text); margin: 0 0 10px; }
  .panel p:last-child { margin-bottom: 0; }
  .panel ul { margin: 0; padding-left: 18px; display: flex; flex-direction: column; gap: 7px;
              font-size: 13.5px; line-height: 1.65; }
  .panel li::marker { color: var(--text-3); }
  .muted { color: var(--text-3); }
  .caveat { font-size: 12px; line-height: 1.6; color: var(--text-2); background: var(--bg);
            border-radius: 10px; padding: 11px 13px; margin-top: 12px; }
  .warn { font-size: 12.5px; line-height: 1.65; color: var(--text); background: var(--kill-bg);
          border-radius: 10px; padding: 12px 14px; margin: 0 0 12px; }
  .note { font-size: 12.5px; line-height: 1.6; color: var(--text-2); border-left: 3px solid var(--border);
          padding-left: 11px; margin-top: 10px; }
  .p-kill { border-color: #F5D9D6; }
  .p-kill h3 { color: var(--kill); }
  .kv { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1px;
        background: var(--border-subtle); border-radius: 10px; overflow: hidden; margin-top: 4px; }
  .kv > div { background: #fff; padding: 10px 12px; display: flex; justify-content: space-between;
              align-items: baseline; gap: 10px; }
  .kv span { font-size: 11.5px; color: var(--text-3); font-weight: 600; }
  .kv b { font-size: 13.5px; font-weight: 800; font-variant-numeric: tabular-nums; white-space: nowrap; }
  .tbl-scroll { overflow-x: auto; border-radius: 10px; border: 1px solid var(--border-subtle); }
  table { width: 100%; border-collapse: collapse; font-size: 13px; min-width: 380px; background: #fff; }
  th, td { padding: 9px 12px; text-align: right; border-bottom: 1px solid var(--border-subtle); white-space: nowrap; }
  th:first-child, td:first-child { text-align: left; }
  thead th { font-size: 11px; font-weight: 700; color: var(--text-3); background: var(--bg); }
  td.n { font-variant-numeric: tabular-nums; }
  tbody tr:last-child td { border-bottom: 0; }
  tr.hi td { background: var(--blue-bg); font-weight: 800; }
  ol.log { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
  ol.log li { border-left: 3px solid var(--border); padding: 2px 0 2px 13px; }
  ol.log h4 { font-size: 13.5px; font-weight: 800; margin: 0 0 5px; }
  ol.log .meta { display: flex; gap: 6px; align-items: center; flex-wrap: wrap; margin-bottom: 5px; }
  ol.log .date { font-size: 11px; font-weight: 700; color: var(--text-3); font-variant-numeric: tabular-nums; }
  ol.log div[data-part] { font-size: 12.5px; line-height: 1.65; color: var(--text-2); margin-top: 3px; }
  ol.log cite { font-style: normal; color: var(--text-3); font-size: 11.5px; }
  footer { margin-top: 32px; padding-top: 14px; border-top: 1px solid var(--border);
           font-size: 10.5px; font-weight: 600; color: var(--text-3); line-height: 1.6; }
  footer a { color: #8B95A1; }'''

ADSENSE = ('<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js'
           '?client=ca-pub-9240461016907498" crossorigin="anonymous"></script>')

FOOTER = '''  <footer>
    데이터: Yahoo Finance. 각 사 공시·IR·실적자료를 1차 출처로 삼으며, 언론 보도는 추론으로 분리해 표기합니다.<br>
    본 자료는 투자 판단 보조용 정리로, 특정 종목의 매수·매도 권유가 아닙니다. 적정가치는 명시된 가정 위에서 도출한 모델 추정치이며 목표주가가 아닙니다.<br>
    <a href="{root}about.html">소개</a> · <a href="{root}privacy.html">개인정보처리방침</a>
  </footer>'''


def menubar(current, root):
    """좌측 상단 메뉴바. 세 카테고리는 index.html·kr/index.html과 문구·순서가 같아야 한다."""
    items = [('미국 시장', root or './', 'us'), ('한국 시장', f'{root}kr/', 'kr'),
             ('메모리 thesis', f'{root}thesis/', 'thesis')]
    links = '\n'.join(
        f'    <a href="{href}"{" aria-current=\"page\"" if key == current else ""}>{label}</a>'
        for label, href, key in items)
    return f'  <nav class="menubar">\n{links}\n  </nav>'


def shell(title, description, canonical, body, current, root, ld):
    return f'''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{_html.escape(description, quote=True)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="website">
<meta property="og:title" content="{_html.escape(title, quote=True)}">
<meta property="og:description" content="{_html.escape(description, quote=True)}">
<meta property="og:url" content="{canonical}">
<meta property="og:locale" content="ko_KR">
<script type="application/ld+json">
{json.dumps(ld, ensure_ascii=False)}
</script>
<title>{_html.escape(title)}</title>
<style>
{STYLE}
</style>
{ADSENSE}
</head>
<body>
<div class="wrap">
{menubar(current, root)}
  <header class="site">
    <span class="brand">메모리 thesis</span>
    <span class="desc">감시 기준표</span>
  </header>
{body}
{FOOTER.format(root=root)}
</div>
</body>
</html>
'''


def panel(label, items, extra_class='', note=None, warning=None):
    body = ''
    if warning:
        body += f'    <p class="warn">{warning}</p>\n'
    if isinstance(items, str):
        body += f'    <p>{items}</p>\n'
    else:
        lis = '\n'.join(f'      <li>{i}</li>' for i in items)
        body += f'    <ul>\n{lis}\n    </ul>\n'
    if note:
        body += f'    <p class="note">{note}</p>\n'
    return (f'  <div class="panel {extra_class}">\n    <h3>{label}</h3>\n{body}  </div>')


def changelog(entries):
    if not entries:
        return ('  <div class="panel">\n    <h3>변경 이력</h3>\n'
                '    <ol class="log" data-block="changelog"></ol>\n'
                '    <p class="muted" style="font-size:12.5px;margin-top:8px">'
                '아직 기록된 변화가 없습니다.</p>\n  </div>')
    items = []
    for e in entries:
        if e.get('signal') == 'init':
            items.append(
                f'      <li data-date="{e["date"]}" data-signal="init">\n'
                f'        <div class="meta"><span class="date">{e["date"]}</span></div>\n'
                f'        <h4>{e["title"]}</h4>\n      </li>')
            continue
        cls = R.GRADE_CLASS.get(e['signal'], 'g-hold')
        parts = '\n'.join(
            f'        <div data-part="{k}">{e[k]}</div>'
            for k in ('fact', 'inference', 'delta', 'next') if e.get(k))
        items.append(
            f'      <li data-date="{e["date"]}" data-signal="{e["signal"]}" '
            f'data-stance="{e["stance"]}">\n'
            f'        <div class="meta"><span class="date">{e["date"]}</span>'
            f'<span class="badge {cls}">{e["signal"]}</span>'
            f'<span class="badge g-hold">{e["stance"]}</span></div>\n'
            f'        <h4>{e["title"]}</h4>\n{parts}\n      </li>')
    joined = '\n'.join(items)
    return ('  <div class="panel">\n    <h3>변경 이력</h3>\n'
            f'    <ol class="log" data-block="changelog">\n{joined}\n    </ol>\n  </div>')


def build_ticker(symbol, row, book, as_of):
    spec = C.TICKERS[symbol]
    grade = book.get('grade', '홀딩 강화')
    cls = R.GRADE_CLASS.get(grade, 'g-hold')

    blocks = [
        f'  <article data-ticker="{symbol}" data-grade="{grade}" '
        f'data-since="{book.get("grade_since", as_of)}">',
        '  <div class="intro">',
        f'    <span class="badge {cls}">{grade}</span> '
        f'&nbsp;{spec["code"]} · 등급 유지 {book.get("grade_since", as_of)}부터',
        f'    <span class="small">{spec["what"]}</span>',
        '  </div>',
        changelog(book.get('changelog', [])),
        '  <h2 class="list-title">투자 thesis</h2>',
        '  <section data-block="thesis">',
    ]

    thesis_body = '\n'.join(f'    <p>{p}</p>' for p in spec['thesis'])
    warn = (f'    <p class="warn">{spec["thesis_warning"]}</p>\n'
            if spec.get('thesis_warning') else '')
    blocks.append(f'  <div class="panel">\n{warn}{thesis_body}\n  </div>')

    for key in ('metrics', 'catalysts', 'risks'):
        blocks.append(panel(C.LABELS[key], spec[key]))
    blocks.append(panel(C.LABELS['kill'], spec['kill'], extra_class='p-kill',
                        note=spec.get('kill_note')))
    for key in ('noise', 'earnings', 'valuation_basis'):
        blocks.append(panel(C.LABELS[key], spec[key]))
    blocks.append('  </section>')

    blocks.append('  <h2 class="list-title">수치와 밸류에이션</h2>')
    blocks.append('  <div class="panel">' + R.snapshot_block(row, as_of) + '</div>')
    blocks.append('  <div class="panel">' + R.valuation_block(row, as_of) + '</div>')

    blocks.append('  <h2 class="list-title">한 줄 결론</h2>')
    blocks.append(panel('요약', spec['bottom_line']))
    blocks.append('  </article>')

    body = '\n'.join(blocks)
    title = f'{spec["name"]} 투자 thesis 감시 기준표 | 메모리 thesis'
    desc = (f'{spec["name"]}({spec["code"]}) 투자 thesis, 핵심 지표, 촉매, 리스크, '
            f'kill condition, 실적 체크포인트, 밸류에이션 기준을 정리한 감시 기준표.')
    ld = {'@context': 'https://schema.org', '@type': 'Article',
          'headline': f'{spec["name"]} 투자 thesis 감시 기준표',
          'url': f'https://fdo2a.github.io/thesis/{spec["slug"]}.html',
          'dateModified': as_of, 'inLanguage': 'ko'}
    return shell(title, desc, f'https://fdo2a.github.io/thesis/{spec["slug"]}.html',
                 body, 'thesis', '../', ld)


def build_index(watch, state, as_of):
    cards = '\n'.join(
        R.ticker_card(s, watch['tickers'][s], state.get(s, {}),
                      f'{C.TICKERS[s]["slug"]}.html')
        for s in C.TICKERS if s in watch['tickers'])

    cycle = '\n'.join(f'    <p>{p}</p>' for p in C.CYCLE['body'])
    feed = []
    for symbol, book in state.items():
        for e in book.get('changelog', []):
            if e.get('signal') == 'init':
                continue
            feed.append((e['date'], C.TICKERS[symbol]['name'], e))
    feed.sort(reverse=True)

    if feed:
        items = '\n'.join(
            f'      <li><span class="date">{d}</span> '
            f'<span class="badge {R.GRADE_CLASS.get(e["signal"], "g-hold")}">{e["signal"]}</span> '
            f'<b>{name}</b> — {e["title"]}</li>' for d, name, e in feed[:12])
        recent = ('  <h2 class="list-title">최근 변화</h2>\n'
                  f'  <div class="panel">\n    <ol class="log">\n{items}\n    </ol>\n  </div>')
    else:
        recent = ('  <h2 class="list-title">최근 변화</h2>\n'
                  '  <div class="panel">\n    <p class="muted">기록된 변화가 없습니다. '
                  '변화가 없는 날은 아무것도 올라오지 않습니다.</p>\n  </div>')

    protocol = (
        '  <h2 class="list-title">감시 프로토콜</h2>\n'
        + panel('알림 대상', C.PROTOCOL['alert']) + '\n'
        + panel('알리지 않는 것', C.PROTOCOL['mute']) + '\n'
        + panel('판정 규칙', C.PROTOCOL['rules']))

    body = f'''  <div class="intro">
    개별 종목을 계속 들고 갈 때 필요한 건 뉴스 요약이 아니라 <b>분류</b>입니다.
    들어온 사건이 처음 그 종목을 본 이유를 강화하는지·약화하는지·깨는지만 판정하고,
    판정이 바뀔 때만 기록합니다.
    <span class="small">기준일 {as_of} · 변화가 없는 날은 아무것도 올라오지 않습니다</span>
  </div>
  <h2 class="list-title">감시 중인 종목</h2>
  <div class="cards">
{cards}
  </div>
  <h2 class="list-title">{C.CYCLE['title']}</h2>
  <div class="panel">
{cycle}
  </div>
{recent}
{protocol}'''

    ld = {'@context': 'https://schema.org', '@type': 'CollectionPage',
          'name': '메모리 thesis 감시 기준표',
          'url': 'https://fdo2a.github.io/thesis/', 'inLanguage': 'ko'}
    return shell('종목 투자 thesis 감시 기준표 | 삼성전자·SK하이닉스·Micron',
                 '삼성전자·SK하이닉스·Micron의 투자 thesis, 핵심 지표, kill condition, '
                 '밸류에이션 기준을 정리하고 thesis를 흔드는 변화만 기록하는 감시 기준표.',
                 'https://fdo2a.github.io/thesis/', body, 'thesis', '../', ld)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--data', default=str(DATA))
    ap.add_argument('--out', default=str(OUT))
    args = ap.parse_args()

    data, out = Path(args.data), Path(args.out)
    watch = json.loads((data / 'watch.json').read_text(encoding='utf-8'))
    state_path = data / 'thesis_state.json'
    state = (json.loads(state_path.read_text(encoding='utf-8')).get('tickers', {})
             if state_path.exists() else {})
    as_of = watch['as_of']

    out.mkdir(parents=True, exist_ok=True)
    written = []
    for symbol, spec in C.TICKERS.items():
        row = watch['tickers'].get(symbol)
        if not row:
            print(f'  watch.json에 {symbol} 없음 — 건너뜀', file=sys.stderr)
            continue
        path = out / f'{spec["slug"]}.html'
        path.write_text(build_ticker(symbol, row, state.get(symbol, {}), as_of),
                        encoding='utf-8')
        written.append(str(path))

    (out / 'index.html').write_text(build_index(watch, state, as_of), encoding='utf-8')
    written.append(str(out / 'index.html'))

    (out / 'index.json').write_text(json.dumps({
        'updated': as_of,
        'tickers': [{
            'symbol': s, 'name': C.TICKERS[s]['name'], 'slug': C.TICKERS[s]['slug'],
            'grade': state.get(s, {}).get('grade', '홀딩 강화'),
            'grade_since': state.get(s, {}).get('grade_since', as_of),
            'url': f'https://fdo2a.github.io/thesis/{C.TICKERS[s]["slug"]}.html',
        } for s in C.TICKERS if s in watch['tickers']],
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    written.append(str(out / 'index.json'))

    for w in written:
        print(f'  wrote {w}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
