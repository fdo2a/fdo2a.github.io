"""US 루틴은 수집 장부(`data/_collect_status.json`)를 자료 파일과 함께 작업 공간에 복사한다 (2026-11-22).

US 일간·뉴스 글의 검사는 `--datadir <workspace>` 로 돈다. 1a(`inputs.EFFECTIVE`)가 켜지면 수집 잡이 쓰는 gate 파일마다
**작업 공간의** `_collect_status.json` 항목(sha256·`run`)이 있어야 한다 — 장부를 복사하지 않으면 모든 수집 자료가
「수집 상태 표시 없음」(unstamped)이 되어 매일 글이 보류된다. 변이 시험(`realday.stamp`)은 장부를 작업 공간에 바로
써서 이 빠진 복사를 가리지 못했다(codex sol 3회차, 뉴스 도장 작업). KR 은 `--datadir kr/data` 를 그대로 읽어 장부가
이미 그 자리에 있다.

여기서 고정하는 것:
- 재현: 실제 발행일 작업 공간에서 장부만 빼면 켜진 상태에서 보류(장부 missing + 수집 자료 unstamped), 넣으면 발행 가능.
- us-news(같은 작업 공간)도 그날 뉴스 파일이 장부 없으면 unstamped.
- 장부의 세션·실행 ID 가 기록(`collect_run`)에 실리고 켜진 상태의 세션 검사를 받는다.
- 꺼진 지금: 장부가 있어도 없어도 검사 판정이 같다(복사는 지금 바로 운영에 들어간다).
- 오케스트레이터의 복사 자리마다(최초 복사·재수집 뒤·뉴스 이어 쓰기) 장부가 적혀 있다.
"""
import hashlib
import json
import os
import re
import shutil

import pytest

from verification import inputs as I
from verification import record as R1
from verification import record2 as R
from verification.tests import realday as RD

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
DAY = '2026-11-12'          # 입찰·유동성 발표·지표 원문이 있는 날 — gate 파일 종류가 가장 많다
LEDGER = I.STATUS_FILE


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


@pytest.fixture(scope='module')
def base(tmp_path_factory):
    b = str(tmp_path_factory.mktemp('ledger-copy'))
    return b, RD.restore(b, 'us', DAY)


@pytest.fixture(autouse=True)
def _off_by_default(monkeypatch):
    # 시험마다 스위치를 스스로 정한다 — 환경 변수 훅이 남아 있으면 「꺼진 상태」 시험이 켜진 채 돈다
    monkeypatch.delenv(I.TEST_ENV, raising=False)
    monkeypatch.setattr(I, 'EFFECTIVE', None)


def _ws(base, dest, stamped=True):
    """작업 공간 사본 + (stamped) 수집 잡이 남긴 모양의 장부 — `test_input_mutations._fresh` 와 같은 방식."""
    b, ctx0 = base
    c = {k: v for k, v in ctx0.items() if k != 'record'}
    for key in ('ws', 'side'):
        shutil.copytree(os.path.join(b, key), os.path.join(dest, key))
    c['datadir'] = os.path.join(dest, 'ws')
    if ctx0.get('tg'):
        c['tg'] = ctx0['tg'].replace(b, dest, 1)
    if stamped:
        RD.stamp(c, 'us', _pol(c))
        _stamp_news(c)
    return c


def _pol(ctx):
    cfgp = os.path.join(ctx['repo'], 'config', 'prepub_gates.json')
    return R.load_policy(R.load_config(cfgp), cfgp)


def _cfg(ctx, mod):
    return mod.load_config(os.path.join(ctx['repo'], 'config', 'prepub_gates.json'))


def _stamp_news(ctx):
    """us-news 의 gate 자료(`news/{D}.json`) — fetch_news.news_collect 가 collect 칸을 쓰고 장부 단계 news 가 run 을 정한다.
    us 일간에는 writer 자료라 `realday.stamp` 가 건드리지 않으므로 여기서 같은 모양으로 붙인다."""
    rel = f'news/{ctx["date"]}.json'
    p = os.path.join(ctx['datadir'], rel)
    with open(p, encoding='utf-8') as fh:
        obj = json.load(fh)
    obj['collect'] = dict(RD.STAMP, as_of=ctx['date'], empty='has_data')
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(obj, fh, ensure_ascii=False)
    with open(p, 'rb') as fh:
        raw = fh.read()
    lp = os.path.join(ctx['datadir'], LEDGER)
    with open(lp, encoding='utf-8') as fh:
        book = json.load(fh)
    book['files'][rel] = {'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw), 'run': 'kept'}
    with open(lp, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, ensure_ascii=False)


def _ledger_files(pol, health, market='us'):
    """적용일부터 장부 항목이 있어야 하는 gate 파일(수집기·참고 파일) 가운데 작업 공간에 있는 것."""
    files, _ = I.entries(pol, market)
    out = []
    for key, f in health['files'].items():
        if f['class'] != 'gate' or f['state'] == 'missing' or key == f'<datadir>/{LEDGER}':
            continue
        e = RD._entry(files, key, health_date(health))
        if e.get('produced_by', 'collector') in I.LEDGER_PRODUCERS:
            out.append(key)
    return out


def health_date(health):
    return health['_date']


def _assess(pol, market, ctx):
    h = I.assess(pol, market, ctx)
    h['_date'] = ctx['date']
    return h


# ── 재현 ──────────────────────────────────────────────────────────────────────────────────────

def test_without_the_copied_ledger_the_us_post_is_held_once_on(base, tmp_path, monkeypatch):
    c = _ws(base, str(tmp_path / 'a'))
    os.unlink(os.path.join(c['datadir'], LEDGER))           # 루틴이 장부를 복사하지 않은 작업 공간
    monkeypatch.setattr(I, 'EFFECTIVE', DAY)
    pol = _pol(c)
    h = _assess(pol, 'us', c)
    led = h['files'][f'<datadir>/{LEDGER}']
    assert led['state'] == 'missing' and led['blocking']
    collected = _ledger_files(pol, h)
    assert len(collected) >= 10                              # 시장·입찰·유동성·연준·지표 원문 …
    assert {k: h['files'][k]['state'] for k in collected} == {k: 'unstamped' for k in collected}
    res = R.run_gates(_cfg(c, R), 'us', c, policy=pol)
    assert not res['summary']['publish_ok'] and res['summary']['inputs']['blocking']


def test_with_the_copied_ledger_the_same_workspace_is_publishable_once_on(base, tmp_path, monkeypatch):
    c = _ws(base, str(tmp_path / 'b'))
    monkeypatch.setattr(I, 'EFFECTIVE', DAY)
    pol = _pol(c)
    h = _assess(pol, 'us', c)
    assert h['files'][f'<datadir>/{LEDGER}']['state'] == 'ok'
    bad = {k: f['state'] for k, f in h['files'].items() if f['class'] == 'gate' and f['state'] not in ('ok', 'missing')}
    assert bad == {}                                         # 해시 불일치·unstamped 없음(텔레그램 키 telegram/<D>.json 포함)
    res = R.run_gates(_cfg(c, R), 'us', c, policy=pol)
    assert res['summary']['publish_ok'], (res['summary']['blocking'], res['summary']['inputs'])


def test_us_news_reads_the_same_workspace_ledger(base, tmp_path, monkeypatch):
    c = _ws(base, str(tmp_path / 'c'))
    monkeypatch.setattr(I, 'EFFECTIVE', DAY)
    pol = _pol(c)
    key = f'<datadir>/news/{DAY}.json'
    assert _assess(pol, 'us-news', c)['files'][key]['state'] == 'ok'
    os.unlink(os.path.join(c['datadir'], LEDGER))
    assert _assess(pol, 'us-news', c)['files'][key]['state'] == 'unstamped'


# ── 같은 실행 결속 ───────────────────────────────────────────────────────────────────────────

def test_the_copied_ledger_binds_session_and_run(base, tmp_path, monkeypatch):
    c = _ws(base, str(tmp_path / 'd'))
    cr = R.collect_run(c['datadir'])
    assert cr['present'] and cr['readable'] and cr['run_id'] == 'fixture-run' and cr['report_date'] == DAY
    with open(os.path.join(c['datadir'], LEDGER), 'rb') as fh:
        assert cr['sha256'] == hashlib.sha256(fh.read()).hexdigest()
    # 다른 세션의 장부를 복사해 온 작업 공간은 켜진 상태에서 장부 자체가 stale — 오늘 입력을 그것으로 판정하지 않는다
    monkeypatch.setattr(I, 'EFFECTIVE', DAY)
    p = os.path.join(c['datadir'], LEDGER)
    with open(p, encoding='utf-8') as fh:
        book = json.load(fh)
    book['report_date'] = '2026-11-11'
    with open(p, 'w', encoding='utf-8') as fh:
        json.dump(book, fh, ensure_ascii=False)
    h = _assess(_pol(c), 'us', c)
    led = h['files'][f'<datadir>/{LEDGER}']
    assert led['state'] == 'stale' and led['blocking']
    # 실행 ID 가 없거나 빈 장부 — 어느 실행의 것인지 모른다
    for bad in ({k: v for k, v in book.items() if k != 'run_id'}, dict(book, run_id='')):
        bad = dict(bad, report_date=DAY)
        with open(p, 'w', encoding='utf-8') as fh:
            json.dump(bad, fh, ensure_ascii=False)
        led = _assess(_pol(c), 'us', c)['files'][f'<datadir>/{LEDGER}']
        assert led['blocking'] and led['state'] in ('stale', 'incomplete_fields'), (bad.get('run_id'), led['state'])


def _recorded_repo(c, tmp_path, mod, pol=None):
    """작업 공간 c 로 검사 → 기록 → 레포 사본의 index 에 올린다(루틴의 record 직후 모양). → (cfg, 기록, extra) — 레포 사본 경로는 c['repo']."""
    import subprocess
    repo = str(tmp_path / 'repo')
    shutil.copytree(c['repo'], repo, symlinks=True)
    c['html'] = c['html'].replace(c['repo'], repo, 1)
    c['repo'] = repo
    cfgp = os.path.join(repo, 'config', 'prepub_gates.json')
    cfg = mod.load_config(cfgp)
    res = mod.run_gates(cfg, 'us', c, policy=pol) if pol is not None else mod.run_gates(cfg, 'us', c)
    assert res['summary']['publish_ok'], res['summary']
    rec = mod.build_record(cfg, cfgp, 'us', c, res)
    out = os.path.join(repo, mod.record_path('us', DAY))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as fh:
        json.dump(rec, fh, ensure_ascii=False)
    subprocess.run(['git', '-C', repo, 'add', '-A'], check=True, capture_output=True)
    return cfg, rec, ({'tg': c['tg']} if c.get('tg') else None)


def test_once_on_verify_rejects_a_ledger_changed_after_record(base, tmp_path, monkeypatch):
    """켜진 뒤(2판 기록): 복사된 장부로 record 한 다음 장부의 실행 ID 나 바이트가 바뀌면 verify 가 「수집 실행이 다르다」로
    막는다(codex 구현 검토 2회차 #5 — `collect_run` 반환값만 보면 verify 의 대조가 빠져도 통과한다). 합성 레포의 같은
    시험은 `test_run_binding`; 여기는 실제 발행일 작업 공간에 복사된 장부다."""
    monkeypatch.setattr(I, 'EFFECTIVE', DAY)
    c = _ws(base, str(tmp_path / 'w'))
    cfg, rec, extra = _recorded_repo(c, tmp_path, R, _pol(c))
    assert rec['format'] == R.FORMAT and rec['collect_run']['run_id'] == 'fixture-run'
    lp = os.path.join(c['datadir'], LEDGER)
    with open(lp, 'rb') as fh:
        orig = fh.read()
    assert rec['collect_run']['sha256'] == hashlib.sha256(orig).hexdigest()

    def check():
        return R.verify(cfg, 'us', DAY, c['repo'], datadir=c['datadir'], extra=extra)

    code, why = check()
    assert code == 0, why                                       # record 전에 복사하고 그대로 두면 짝이 맞는다
    book = json.loads(orig)
    # ① 다른 실행의 장부(실행 ID 만 다름 — 재수집 뒤 장부만 새로 받은 꼴)
    with open(lp, 'w', encoding='utf-8') as fh:
        json.dump(dict(book, run_id='other-run'), fh, ensure_ascii=False)
    code, why = check()
    assert code == 1 and any('수집 실행이 다르다' in w and 'fixture-run' in w and 'other-run' in w for w in why), why
    # ② 같은 실행 ID, 바이트만 다름(항목 해시를 고쳐 맞춘 꼴)
    with open(lp, 'wb') as fh:
        fh.write(orig + b'\n')
    code, why = check()
    assert code == 1 and any('수집 실행이 다르다' in w and '장부 바이트가 다르다' in w for w in why), why
    # ③ 장부를 뺐다
    os.unlink(lp)
    code, why = check()
    assert code == 1 and any('수집 실행이 다르다' in w and '장부 없음' in w for w in why), why
    # 되돌리면 다시 짝이 맞는다 — 위 실패가 장부 때문이었다
    with open(lp, 'wb') as fh:
        fh.write(orig)
    code, why = check()
    assert code == 0, why


# ── 꺼진 지금: 복사가 판정을 바꾸지 않는다 ─────────────────────────────────────────────────────

def test_while_off_the_ledger_changes_no_verdict(base, tmp_path):
    assert not I.enforcing()
    out = []
    for name, keep in (('with', True), ('without', False)):
        c = _ws(base, str(tmp_path / name))
        if not keep:
            os.unlink(os.path.join(c['datadir'], LEDGER))
        res = R1.run_gates(_cfg(c, R1), 'us', c)
        out.append(({g['name']: g['status'] for g in res['gates']}, res['summary']['publish_ok']))
    assert out[0] == out[1] and out[0][1]


def test_while_off_a_ledger_copied_before_record_keeps_verify_matched(base, tmp_path):
    """꺼진 지금도 장부는 기록의 입력 목록(`inputs.files`)에 실린다 — 판정은 아니지만 verify 가 대조한다. 복사가 record
    전에 끝나 있으면 짝이 맞고, record 뒤에 장부를 빼거나 바꾸면 다른 입력 파일과 똑같이 「입력 데이터가 바뀌었다」(exit 1,
    다시 record)로 막힌다(codex 구현 검토 1회차 #3 — 그래서 오케스트레이터는 같은 때 복사하고 장부만 따로 건드리지 않는다)."""
    assert not I.enforcing()
    c = _ws(base, str(tmp_path / 'v'))
    cfg, rec, extra = _recorded_repo(c, tmp_path, R1)
    assert f'<datadir>/{LEDGER}' in {f['path'] for f in rec['inputs']['files']}
    lp = os.path.join(c['datadir'], LEDGER)
    with open(lp, 'rb') as fh:
        orig = fh.read()

    def check():
        return R1.verify(cfg, 'us', DAY, c['repo'], datadir=c['datadir'], extra=extra)

    def blocked():
        code, why = check()
        assert code == 1 and any('입력 데이터가 바뀌었다' in w and LEDGER in w for w in why), why

    code, why = check()
    assert code == 0, why
    os.unlink(lp)                                               # record 뒤에 장부를 뺐다
    blocked()
    with open(lp, 'wb') as fh:                                  # record 뒤에 장부 바이트만 바꿨다
        fh.write(orig + b'\n')
    blocked()
    with open(lp, 'wb') as fh:
        fh.write(orig)
    code, why = check()
    assert code == 0, why                                       # 되돌리면 다시 맞는다 — 위 실패는 장부 때문이었다


def test_while_off_a_ledger_added_after_record_is_blocked_by_verify(base, tmp_path):
    """장부 없이 record 한 뒤 장부를 넣는 쪽 — 기록에 없던 경로도 verify 가 본다(기록·지금 경로의 합집합 대조,
    codex 구현 검토 3회차 #5). 기록에 있던 경로만 비교하면 뒤늦게 들어온 장부가 그냥 통과한다."""
    assert not I.enforcing()
    c = _ws(base, str(tmp_path / 'n'))
    lp = os.path.join(c['datadir'], LEDGER)
    with open(lp, 'rb') as fh:
        orig = fh.read()
    os.unlink(lp)
    cfg, rec, extra = _recorded_repo(c, tmp_path, R1)
    assert f'<datadir>/{LEDGER}' not in {f['path'] for f in rec['inputs']['files']}
    code, why = R1.verify(cfg, 'us', DAY, c['repo'], datadir=c['datadir'], extra=extra)
    assert code == 0, why
    with open(lp, 'wb') as fh:
        fh.write(orig)
    code, why = R1.verify(cfg, 'us', DAY, c['repo'], datadir=c['datadir'], extra=extra)
    assert code == 1 and any('입력 데이터가 바뀌었다' in w and LEDGER in w for w in why), why


# ── 오케스트레이터 문구 ───────────────────────────────────────────────────────────────────────

ORCH = '.claude/ORCHESTRATOR.md'


def _step0_copy(text):
    m = re.search(r'\n2\. If it exists, .*?(?=\n3\. If `data/market_data\.json`)', text, re.S)
    assert m, 'STEP 0 의 복사 항목(2.)을 찾지 못했다'
    return m.group(0)


def test_orchestrator_copies_the_ledger_with_the_data_files():
    lines = [ln for ln in _step0_copy(read(ORCH)).split('\n') if ln.startswith('   - 수집 장부:')]
    assert len(lines) == 1, '2번 안의 「수집 장부」 항목이 하나여야 한다'
    s = lines[0]                                         # 2번의 다른 항목에 흩어진 문구로는 통과하지 않는다
    assert f'`data/{LEDGER}`' in s and f'`<workspace>/{LEDGER}`' in s
    assert f'rm -f <workspace>/{LEDGER}' in s            # 레포에 없으면 작업 공간의 옛 장부도 지운다
    assert '같은 pull 판에서, 같은 때' in s                 # 다른 판의 장부와 섞이지 않는다
    assert 'record 부터 마지막 verify 까지 장부를 넣거나 빼거나 바꾸지 않는다' in s


def test_orchestrator_recopies_after_recollection():
    text = read(ORCH)
    m = re.search(r'\n3\. If `data/market_data\.json`.*?(?=\n\*\*토큰 규율\*\*)', text, re.S)
    assert m
    paras = [ln for ln in m.group(0).split('\n') if '2번의 복사를 처음부터 다시' in ln]
    assert len(paras) == 1 and LEDGER in paras[0]        # 같은 문단에서 장부까지 다시 복사하라고 한다
    # 제 문단의 첫 문장이다 — 네이버 종가 대기 문단 같은 한 경우의 끝에 붙으면 그 경우에만 하는 일이 된다(5회차 #5)
    assert paras[0].startswith('   **재수집으로 새 판을 받았으면 2번의 복사를 처음부터 다시 한다** — 수집 장부(')


def test_orchestrator_realigns_the_ledger_after_the_collector_returns():
    """수집 담당 지시문(STEP 0)은 커밋된 완성본을 스스로 작업 공간에 복사한다 — 장부는 모른다(agents/ 문서에는 장부 이름을
    쓰지 않는다, `test_switch_off`). 닫는 자리는 오케스트레이터 STEP 1 의 수집 담당 복귀 뒤다(codex 구현 검토 5회차 #1·#2)."""
    text = read(ORCH)
    m = re.search(r'\n## STEP 1 — .*?(?=\n## STEP 2 — )', text, re.S)
    assert m, 'STEP 1 구역을 찾지 못했다'
    paras = [ln for ln in m.group(0).split('\n') if ln.startswith('**수집 담당이 돌아온 뒤')]
    assert len(paras) == 1, 'STEP 1 의 「수집 담당이 돌아온 뒤」 문단이 하나여야 한다'
    s = paras[0]
    # 레포 판을 복사한 것인지 **커밋 판**과 바이트로 가른다 — 작업 트리의 data/ 는 수집 담당이 레포 안에서 수집기를 돌리면
    # 새 자료로 덮여 옛 장부와 「같다」가 된다(codex 구현 검토 6회차 #2)
    assert ('`C=$(git -C <repo> rev-parse --verify HEAD) && '
            'git -C <repo> show "$C:data/market_data.json" | cmp -s - <workspace>/market_data.json`') in s
    assert 'cmp -s data/market_data.json' not in s
    assert 'pull 하지 않은 그대로' in s                                           # 같은 판
    assert (f'`git -C <repo> show "$C:data/{LEDGER}" > <workspace>/{LEDGER} 2>/dev/null '
            f'|| rm -f <workspace>/{LEDGER}`') in s                                # 장부도 같은 커밋에서
    assert '자료 파일은 다시 복사하지 않는다' in s                                 # 스스로 수집한 파일을 레포 판으로 덮지 않는다
    assert '다르면' in s and '장부를 복사하지도 고치지도 않는다' in s
    lines = m.group(0).split('\n')
    at = lines.index(s)
    launch = [i for i, ln in enumerate(lines) if ln.startswith('Launch the Agent tool with subagent_type "brief-data-collector"')]
    gate = [i for i, ln in enumerate(lines) if ln.startswith('Gate before proceeding:')]
    assert len(launch) == 1 and len(gate) == 1 and launch[0] < at < gate[0]     # 수집 담당 호출 뒤, 게이트 앞
    # 수집 담당 지시문에는 장부가 없다 — 이 문단이 그 빈자리를 닫는 유일한 곳이다
    assert LEDGER not in read('.claude/agents/brief-data-collector.md')


def test_orchestrator_news_resume_restores_the_ledger_from_the_publish_commit():
    text = read(ORCH)
    blocks = [b for b in re.findall(r'```bash\n(.*?)```', text, re.S) if '--diff-filter=A' in b and 'posts/$D.html' in b]
    assert len(blocks) == 1, '뉴스 이어 쓰기 복원 블록이 하나여야 한다'
    cmds = [ln.strip() for ln in blocks[0].split('\n')]
    # 줄 전체가 명령이어야 한다 — 주석 처리된 줄(`# git show …`)은 복사가 아니다(5회차 #5)
    assert f'git show "$C:data/{LEDGER}" > "$WS/{LEDGER}" 2>/dev/null || rm -f "$WS/{LEDGER}"' in cmds
    # 뉴스 파일과 장부가 같은 커밋($C)에서 나온다 — 한쪽만 HEAD 에서 꺼내면 장부의 해시와 어긋난다
    assert 'git show "$C:data/news/$D.json" > "$WS/news/$D.json" 2>/dev/null || rm -f "$WS/news/$D.json"' in cmds
    shows = [c for c in cmds if 'git show' in c and ':data/' in c and not c.startswith('#')]
    assert shows and all(c.startswith('git show "$C:data/') for c in shows), shows


def test_kr_reads_the_ledger_in_place():
    """KR 은 작업 공간에 자료를 복사하지 않는다 — 모든 run_gates 가 `--datadir kr/data` 를 그대로 읽는다."""
    text = read('.claude/KR_ORCHESTRATOR.md')
    calls = re.findall(r'run_gates\.py (?:check|record|verify)[^`\n]*', text)
    assert len(calls) >= 4                                   # check·record·verify(index)·verify(HEAD)
    # 인자 전체를 본다 — `kr/data-snapshot`·`kr/data/x` 같은 다른 폴더는 장부가 없는 자리다(codex 구현 검토 4회차 #5)
    assert [re.findall(r'--datadir(?:\s+|=)(\S+)', c) for c in calls] == [['kr/data']] * len(calls), calls
    gates = json.loads(read('config/prepub_gates.json'))
    assert 'kr-news' not in gates['markets']                 # KR 뉴스 글은 run_gates 기록 대상이 아니다
