"""일본 일간 v2 회귀 — 옛 스냅샷(schema 없음)의 표·조립·게이트 출력이 변경 전과 바이트로 같다 (설계 §11-11).

기대 해시는 v2 변경 전 코드(origin/main 97721936)로 11/04·11/18 발행 스냅샷을 렌더해 잰 값이다.
"""
import glob
import hashlib
import json
import os

import pytest

from japan import daily_gate as G
from japan import daily_news_gate as NG
from japan import daily_render as R

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
GOLDEN = {
    '2026-11-04': {'indices': 'a55327c930cf8fa9b808c70ac0fb497fe97298feeb79a3c77fd7b1eb7578fab4',
                   'sectors': 'abbd27071265093bb884f972f802fd1ec273c5a3919f88adf431838adea045b1',
                   'jgb': '49a92f1c41afabe05bb336132b658452218992d5dc75233b9a72e7f12939d1cc',
                   'fx': 'a79000727623aff1ddc664255a054ae914450ceffeb532d19ab27c25c0f6ac10',
                   'macro': 'd29e49ee4f0b2039d3d1a19141f3b83d0cc4748a7a828db67d44a6fe8b286445',
                   'next': '8ff3f8661f700dee51a6eacdbf060df15ffc270ac8fd6c53d47f71723bcb30b4',
                   'assemble': '00cecbeffe5b1d5be8d14d0f5373bfda0486bdb6e812fd851ce93f03964b6d69'},
    '2026-11-18': {'indices': '6d74d00abde9a83fd0afa4840c99d87cd17c5ba98d8eff6bd5956da1fef76a71',
                   'sectors': '2cee9db6464a458d5be24e52fbb9cc6d7a87c9df631ea06aa29de89a05f14214',
                   'jgb': '5e56a48b83d4859245acbc5f3964e76caf752665a1174d93f4be9c2514c2ed56',
                   'fx': '893a77de078b6cdcae15df03fd79ef2f3baa4c010f746953c7bbaf042cb667ec',
                   'macro': '52b952ef64b632a5d006cd4a8fedc10c62d2d707fa5123e9a424a0962580c045',
                   'next': '1bac6efb9742389901ead784592f4f3f3b1b14ffdd18660ea68b74126eeb3f05',
                   'assemble': '1c8e8814a854b529e123261a1f06c7f31585af6be365f3a96b1bd5b0020162f1'},
}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _snap(s):
    with open(os.path.join(ROOT, 'japan', 'data', 'daily', f'{s}.json'), encoding='utf-8') as fh:
        return json.load(fh)


@pytest.mark.parametrize('session', sorted(GOLDEN))
def test_old_snapshot_render_and_assemble_byte_identical(session):
    snap = _snap(session)
    assert 'schema' not in snap
    got = {k: _h(v) for k, v in R.render_tables(snap).items()}
    parts = ['<section class="card headline-card"><h1>제목</h1><p>요약</p></section>']
    for sec in R.order(snap['calendar'].get('event_day')):
        tables = ''.join(f'<!--T:{x}-->' for x in R.PLACEHOLDERS.get(sec, ()))
        parts.append(f'<section class="card" data-section="{sec}"><h2>{R.TITLES[sec]}</h2><p>본문.</p>{tables}</section>')
    got['assemble'] = _h(R.assemble('\n'.join(parts), {'title': 't', 'summary': 's'}, snap))
    assert got == GOLDEN[session]


def _published():
    return sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(ROOT, 'japan', 'daily', '2026-*.html')))


@pytest.mark.parametrize('session', _published())
def test_every_published_post_still_passes_both_gates(session):
    """발행본 16편: 일간 게이트·뉴스 게이트 위반 0(변경 전 실측과 같다)."""
    import sys
    sys.path.insert(0, os.path.join(ROOT, 'scripts'))
    from build_japan_daily import load_telegram, news_path
    snap = _snap(session)
    with open(os.path.join(ROOT, 'japan', 'daily', f'{session}.html'), encoding='utf-8') as fh:
        html = fh.read()
    np = news_path(ROOT, session)
    news = json.loads(np.read_text(encoding='utf-8')) if np.exists() else None
    tg, _ = load_telegram(ROOT, session)
    assert G.check(html, snap, session, filename=f'{session}.html', news=news, tg=tg, pairs=[]) == []
    if news:
        assert NG.check(html, news, session) == []
