"""번역투 점검 — 걸 것만 걸고, 작성자가 다듬지 않을 곳은 건드리지 않으며, 글은 바꾸지 않는가."""

import os
import sys

import pytest

from us.translationese import find, flag

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import scan_translationese as scan  # noqa: E402


def _names(text):
    return [h.name for h in find(text)]


def _swap(text, i=1):
    h = find(text)[0]
    return text[:h.start] + h.options[i - 1][1] + text[h.end:]


@pytest.mark.parametrize('text, name', [
    ('헬스케어 업종의 상대 강세에 대한 판단은 미룬다.', '에 대한'),
    ('관세에 대해 말을 아꼈다.', '에 대한'),
    ('52주 고점과의 거리는 1.29%다.', '조사 결합'),
    ('AI 관련 산업으로의 자금 집중이 이어졌다.', '조사 결합'),
    ('미국에서의 수요가 컸다.', '조사 결합'),
    ('정부는 다음 달부터의 감세 계획을 논의한다.', '조사 결합'),
    ('투자에 있어서 중요한 것은 금리다.', '에 있어서'),
    ('판단하는 데 있어 중요한 것은 금리다.', '데 있어'),
    ('수입 물가를 통해 일본 물가를 밀어 올린다.', '를 통해'),
    ('계획이 검토되어졌다.', '이중 피동'),
    ('처리되어질 예정이다.', '이중 피동'),
    ('회사는 높은 점유율을 가지고 있다.', '가지고 있다'),
    ('법안을 심사하는 중이다.', '하는 중이다'),
    ('법안을 검토하고 있는 중이다.', '하는 중이다'),
])
def test_패턴을_잡는다(text, name):
    assert name in _names(text)


@pytest.mark.parametrize('text', [
    '밴드 하단에서 3% 남짓 위에 있어, 레벨을 함께 본다.',   # 「에 있어」 = 존재
    '범위 가운데 있어 판단을 미룬다.',
    '기업별 실적에 따라 주가가 차별화될 것으로 본다.',      # 인과 표지 — 일부러 뺐다
    '급락에 따른 반발 매수가 들어왔다.',
    '금리 인상으로 인한 부담이 커졌다.',
    '반등은 이어질 것으로 보인다.',                       # 한계 표지 — 일부러 뺐다
    '정부에 의해 발표됐다.',                             # 국소적인 고칠 꼴이 없다
    '계좌를 통한 청약이 허용됐다.',
    '은행은 계좌를 여는 중이다.',                         # 어간 복원(열고)은 귀띔 못 함
    '대한항공이 3% 올랐다.',                             # 고유명사 속 「대한」
    '성과의 배경은 수요다.',                             # 「성과」의 과
    '결과의 해석이 갈렸다.',
    '의장은 “시장과의 소통을 늘리겠다”고 말했다.',          # 인용 안
    '그는 「물가에 대한 경계」를 강조했다.',
    '그는 &quot;물가에 대한 경계&quot;를 강조했다.',
    '그는 &#34;실적에 대한 우려가 남았다.&#34;라고 말했다.',
    '그는 &#x201c;실적에 대한 우려&#x201d;를 말했다.',
    '그는 &apos;실적에 대한 우려&apos;를 말했다.',
    "그는 'AI에 대한 기대'를 말했다.",
])
def test_오탐하지_않는다(text):
    assert _names(text) == []


@pytest.mark.parametrize('text, i, want', [
    ('상대 강세에 대한 판단은 미룬다.', 1, '상대 강세 판단은 미룬다.'),
    ('상대 강세에 대한 판단은 미룬다.', 2, '상대 강세 관련 판단은 미룬다.'),
    ('52주 고점과의 거리', 1, '52주 고점과 거리'),
    ('산업으로의 자금 집중', 1, '산업으로 자금 집중'),
    ('투자에 있어서 중요한', 1, '투자에서 중요한'),
    ('판단하는 데 있어서 중요한', 1, '판단하는 데 중요한'),
    ('수입 물가를 통해 밀어 올린다', 1, '수입 물가로 밀어 올린다'),
    ('채권 시장을 통하여 번졌다', 1, '채권 시장으로 번졌다'),
    ('계획이 검토되어졌다.', 1, '계획이 검토됐다.'),
    ('검토되어진 계획', 1, '검토된 계획'),
    ('처리되어질 예정', 1, '처리될 예정'),
    ('점유율을 가지고 있다.', 1, '점유율이 있다.'),
    ('기회를 가지고 있다.', 1, '기회가 있다.'),
    ('법안을 심사하는 중이다.', 1, '법안을 심사하고 있다.'),
    ('법안을 검토하고 있는 중이다.', 1, '법안을 검토하고 있다.'),
])
def test_귀띔은_걸린_구간만_바꾼_꼴이다(text, i, want):
    assert _swap(text, i) == want


def test_격을_정할_수_없는_자리는_귀띔_없이_건다():
    assert find('투자자는 실적에 대해 안도했다.')[0].options == []
    assert find('API를 통해 받았다.')[0].options == []


HTML = ('<html><body><p>나스닥은 1.2% 올랐다.</p>\n'
        '<p>상대 강세에 대한 판단은 미룬다. 52주 고점과의\n거리는 <strong>1.29%</strong>다.</p>\n'
        '<table><tr><td><p>표 안 강세에 대한 판단</p></td></tr></table>\n'
        '<section data-editor-note="1"><p>노트의 강세에 대한 말</p></section>\n'
        '<section><p>앞 문단이다.</p><section data-contested="1"><p>실적에 대한 우려가 남았다.</p>'
        '</section></section>\n'
        '<section><SECTION DATA-CONTESTED><p>대문자 쟁점에 대한 문단.</p></SECTION></section>\n'
        '<p class="news-head">기사 제목에 대한 문장.</p>\n'
        '<p class="sub">캡션에 대한 문장.</p>\n'
        '<ul><li><p>목록에 대한 문장.</p></li></ul>\n'
        '<blockquote><p>인용에 대한 문장.</p></blockquote>\n'
        '<p>그는 <q>실적에 대한 우려</q>를 말했다.</p>\n'
        '</body></html>')


def test_flag_는_작성자가_다듬을_문단만_고른다():
    flagged = flag(HTML)
    assert list(flagged) == ['P002']
    assert [h.name for h in flagged['P002']] == ['에 대한', '조사 결합']


def test_못_닫힌_보호_구역은_문서_끝까지_걸지_않는다():
    html = '<p>앞 강세에 대한 판단.</p><section data-contested="1"><p>뒤 강세에 대한 판단.</p>'
    assert list(flag(html)) == ['P001']


def test_중첩된_쟁점_분석은_prose_swap_도_뽑지_않는다():
    from us.prose_swap import extract
    _, side = extract(HTML)
    assert all('실적에 대한 우려가 남았다' not in v['inner'] for v in side['items'].values())


def test_scan_은_문장과_귀띔을_찍고_글은_바꾸지_않는다(tmp_path, capsys):
    post = tmp_path / 'brief.html'
    post.write_text(HTML, encoding='utf-8')
    assert scan.main([str(post)]) == 0
    out = capsys.readouterr().out
    assert '「에 대한」 상대 강세에 대한 판단은 미룬다.' in out
    assert '귀띔(삭제): 상대 강세 판단은 미룬다.' in out
    assert out.strip().endswith('translationese: flagged 2')
    assert post.read_text(encoding='utf-8') == HTML


def test_scan_은_무슨_일이_있어도_0으로_끝난다(tmp_path, capsys):
    assert scan.main([str(tmp_path / 'none.html')]) == 0
    assert scan.main([]) == 0
    clean = tmp_path / 'clean.html'
    clean.write_text('<p>나스닥은 1.2% 올랐다.</p>', encoding='utf-8')
    assert scan.main([str(clean)]) == 0
    assert capsys.readouterr().out.strip().endswith('translationese: flagged 0')


# ── 구현 검토(2026-11-05 codex) ─────────────────────────────────────────────

@pytest.mark.parametrize('text', [
    '그는 &ldquo;실적에 대한 우려&#8221;를 말했다.',          # 이름 엔티티 + 숫자 엔티티를 섞었다
    '그는 &#0034;실적에 대한 우려&#0034;를 말했다.',          # 앞자리 0
    '그는 “실적에 대한 우려&rdquo;를 말했다.',                # 글자 + 엔티티
    '그는 &#X201C;실적에 대한 우려&#x201D;를 말했다.',
])
def test_따옴표는_표기가_섞여도_인용으로_본다(text):
    assert _names(text) == []


def test_따옴표_정규화는_위치를_옮기지_않는다():
    text = '그는 &ldquo;실적&rdquo;을 말했다. 강세에 대한 판단이다.'
    h = find(text)[0]
    assert text[h.start:h.end] == '에 대한'


@pytest.mark.parametrize('text, name', [
    ('실적에 대해서는 말을 아꼈다.', '에 대한'),
    ('관세에 대해선 말을 아꼈다.', '에 대한'),
    ('실적에 대해서도 말을 아꼈다.', '에 대한'),
    ('은행을 통해서 공급했다.', '를 통해'),
])
def test_보조사가_붙은_꼴도_잡는다(text, name):
    assert name in _names(text)


@pytest.mark.parametrize('text', ['내과의 진료가 늘었다.', '치과의 수요가 늘었다.', '대한항공이 올랐다.'])
def test_과로_끝나는_명사는_조사가_아니다(text):
    assert _names(text) == []


@pytest.mark.parametrize('inner', [
    '<span class="sub">실적에 대한 우려</span>',
    '<span data-summary>실적에 대한 우려</span>',
    '<span DATA-CONTESTED>실적에 대한 우려</span>',
    '<span class="muted">실적에 대한 우려',                    # 못 닫히면 문단 끝까지
])
def test_문단_안의_보호_요소도_걸지_않는다(inner):
    assert flag('<p>본문이다. %s</p>' % inner) == {}


def test_문단_안_보호_요소_밖은_그대로_건다():
    flagged = flag('<p>강세에 대한 판단이다. <span class="sub">캡션에 대한 말</span></p>')
    assert [h.text for h in flagged['P001']] == ['에 대한']


def test_줄_구분자가_보호_구간_위치를_틀리게_하지_않는다():
    html = '<div>앞 ' + 'X' * 100 + '</div>\n<blockquote><p>실적에 대한 우려</p></blockquote>'
    assert flag(html) == {}


def test_scan_은_출력_인코딩이_깨져도_0으로_끝난다(tmp_path, monkeypatch):
    import io
    post = tmp_path / 'p.html'
    post.write_text('<p>실적에 대한 우려다.</p>', encoding='utf-8')
    raw = io.BytesIO()
    monkeypatch.setattr(sys, 'stdout', io.TextIOWrapper(raw, encoding='ascii'))
    assert scan.main([str(post)]) == 0
    assert scan.main([]) == 0
    sys.stdout.flush()
    assert b'translationese: flagged' in raw.getvalue()


# ── 재검토(2026-11-05 codex 2차) ────────────────────────────────────────────

@pytest.mark.parametrize('text', [
    '&QUOT;실적에 대한 우려&QUOT;',
    '&quot;실적에 대한 우려&QUOT;',
])
def test_대문자_quot_엔티티도_인용이다(text):
    assert _names(text) == []


def test_속성값에_꺾쇠가_있는_q_도_인용이다():
    assert flag('<p>그는 <q title="2 > 1">실적에 대한 우려</q>를 말했다.</p>') == {}


def test_scan_은_파이프가_닫혀도_0으로_끝난다(tmp_path):
    import subprocess
    post = tmp_path / 'p.html'
    post.write_text('<p>실적에 대한 우려다.</p>' * 200, encoding='utf-8')
    r, w = os.pipe()
    os.close(r)
    script = os.path.join(os.path.dirname(scan.__file__), 'scan_translationese.py')
    proc = subprocess.run([sys.executable, script, str(post)], stdout=w, stderr=subprocess.PIPE)
    os.close(w)
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
