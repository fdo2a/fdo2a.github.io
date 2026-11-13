"""실행 목록 설정(`config/prepub_gates.json`)과 루틴 지시문이 한 목록을 가리키는지 (2026-11-08).

지시문에 등장하는 검사기 이름 전부가 아니라 **현재 실행 목록**을 본다 — 비활성 검사기는 이력으로 남아도 되지만
실행 목록에 들어 있으면 실패한다. 지시문의 발행 게이트 블록은 `run_gates.py check` 한 줄이어야 하고, 그 블록에서
검사기를 따로 부르면 목록이 다시 두 벌이 된다.
"""
import json
import os
import re

import pytest

from verification import record as R

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
CFG = os.path.join(ROOT, 'config', 'prepub_gates.json')


@pytest.fixture(scope='module')
def cfg():
    return R.load_config(CFG)


def read(rel):
    with open(os.path.join(ROOT, rel), encoding='utf-8') as fh:
        return fh.read()


def test_every_gate_runs_an_existing_check(cfg):
    for market, m in cfg['markets'].items():
        names = [g['name'] for g in m['gates']]
        assert len(names) == len(set(names)), market
        for g in m['gates']:
            assert g.get('kind') in R.KINDS, g['name']
            if g.get('builtin'):
                assert g['builtin'] == 'unconfirmed'
                continue
            script = g['argv'][0]
            assert os.path.isfile(os.path.join(ROOT, script)), script
            # 실행 목록은 읽기 전용 검사만 — 글을 고치는 apply_* 는 --check 일 때만
            if os.path.basename(script).startswith('apply_'):
                assert '--check' in g['argv'], g['name']


def test_disabled_gates_are_not_in_the_run_list(cfg):
    for market, rows in cfg['disabled'].items():
        run = {g['name'] for g in cfg['markets'][market]['gates']}
        for d in rows:
            assert d['name'] not in run, f'{market} {d["name"]} 은 비활성인데 실행 목록에 있다'
            assert d.get('since') and d.get('why')


def test_required_and_kinds_are_what_we_decided(cfg):
    us = {g['name']: g for g in cfg['markets']['us']['gates']}
    kr = {g['name']: g for g in cfg['markets']['kr']['gates']}
    assert us['check_numbers']['required'] and us['check_numbers']['kind'] == 'numbers' and us['check_numbers']['json']
    for m in (us, kr):
        # 가독성 fails 는 구조 오류(섹션 넘는 div·조판 미적용) — 필수(codex 구현 검토 #5). 경고는 막지 않는다
        assert m['check_readability']['required'] and m['check_readability']['kind'] == 'structure'
        assert m['check_fund'].get('effective') == {'module': 'fund.gate', 'attr': 'EFFECTIVE'}
        assert m['check_style']['required'] and m['check_style']['kind'] == 'format'
        assert m['unconfirmed']['required']
        assert m['check_research']['required']
    # KR 표 숫자 대조(2026-11-13) — 표 네 종만, 문장은 범위 밖. 날짜는 --date 로(초안 파일명에 날짜가 없을 수 있다)
    assert kr['check_numbers']['required'] and kr['check_numbers']['kind'] == 'numbers' and kr['check_numbers']['json']
    assert kr['check_numbers']['argv'][-4:] == ['--market', 'kr', '--date', '{date}']
    assert '--market' not in us['check_numbers']['argv']           # US 명령은 그대로
    assert cfg['markets']['kr']['post'] == 'kr/posts/{date}.html'


def _gate_block(text):
    """발행 게이트 블록 — `run_gates.py check` 가 든 bash 블록."""
    blocks = re.findall(r'```bash\n(.*?)```', text, re.S)
    hits = [b for b in blocks if 'run_gates.py check' in b]
    assert len(hits) == 1, '발행 게이트 블록이 하나여야 한다'
    return hits[0]


@pytest.mark.parametrize('doc,market', [('.claude/ORCHESTRATOR.md', 'us'), ('.claude/KR_ORCHESTRATOR.md', 'kr')])
def test_orchestrator_runs_the_single_list(doc, market):
    text = read(doc)
    block = _gate_block(text)
    assert f'--market {market}' in block
    assert not re.search(r'scripts/check_\w+\.py', block), '게이트 블록에서 검사기를 따로 부르면 목록이 두 벌이 된다'
    assert f'run_gates.py record --market {market}' in text
    assert f'run_gates.py verify --market {market}' in text and '--rev HEAD' in text and '--index' in text
    assert f'verification/{market}/' in text
    # verify 를 && 로 commit·push 에 이으면 exit 4(기록 기능 실패 때 허용) 에서 사슬이 멈춰 발행이 조용히 끊긴다
    assert not re.search(r'run_gates\.py verify[^`\n]*&&', text)
    assert text.count('--datadir') >= 3 and 'verify --market' in text
    assert re.search(r'verify --market ' + market + r'[^`]*--rev HEAD --datadir', text)
    # record 와 같은 입력 인자 — 안 주면 정상 발행이 record↔verify 를 맴돈다(codex 구현 검토 #4)
    for v in re.findall(r'run_gates\.py verify[^`]*', text):
        assert '--tg' in v, v
        if market == 'kr':
            assert '--stance-next' in v, v
    # 도구 오류(5)는 보류, 저장 실패(4)만 해시 대조와 함께 발행(#1·#3)
    assert re.search(r'exit 5[^\n]*커밋하지 않고', text)
    assert '--record-file' in text and '--expect-sha256' not in text


def test_style_close_b_includes_record_and_verify():
    text = read('.claude/STYLE_CLOSE.md')
    assert 'run_gates.py record' in text and 'run_gates.py verify' in text and '--rev HEAD' in text
