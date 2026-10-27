"""Actions 에서 기사 본문을 한국어 요약으로 — scripts/us/news_summary.py."""
import types

from us import news_summary as NS

GOOD = '가' * 300


class Client:
    def __init__(self, replies, stop='end_turn'):
        self.replies, self.calls, self.stop = list(replies), [], stop
        self.messages = self

    def create(self, **kw):
        # 호출 시점의 메시지를 복사해 둔다 — 재작성 턴이 같은 리스트에 덧붙여도 첫 호출 기록이 바뀌지 않게
        self.calls.append(dict(kw, messages=list(kw['messages'])))
        text = self.replies.pop(0)
        return types.SimpleNamespace(
            stop_reason=self.stop,
            content=[types.SimpleNamespace(type='thinking', thinking='', signature='sig'),
                     types.SimpleNamespace(type='text', text=text)])


def items(tmp_path, n=1):
    out = []
    for i in range(n):
        name = f'{i:02d}-macro.txt'
        (tmp_path / name).write_text('Fed body ' * 100, encoding='utf-8')
        out.append({'title': f'T{i}', 'source': 'CNBC', 'body_chars': 900, 'body_file': name})
    return out


def test_a_summary_in_band_is_stored_with_its_model(tmp_path):
    its = items(tmp_path)
    assert NS.summarize_items(its, str(tmp_path), model='m', client=Client([GOOD]),
                              log=lambda *_: None) == 1
    assert its[0]['summary_ko'] == GOOD and its[0]['summary_model'] == 'm'


def test_the_body_and_title_reach_the_model(tmp_path):
    c = Client([GOOD])
    NS.summarize_items(items(tmp_path), str(tmp_path), model='m', client=c, log=lambda *_: None)
    content = c.calls[0]['messages'][0]['content']
    assert 'T0' in content and 'Fed body' in content
    assert '기사에 없는' in c.calls[0]['system']


def test_an_out_of_band_summary_gets_one_rewrite(tmp_path):
    its = items(tmp_path)
    c = Client(['짧다', GOOD])
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls) == 2 and its[0]['summary_ko'] == GOOD


def test_the_default_model_is_haiku_5_5(tmp_path, monkeypatch):
    monkeypatch.delenv('NEWS_SUMMARY_MODEL', raising=False)
    its, c = items(tmp_path), Client([GOOD])
    NS.summarize_items(its, str(tmp_path), client=c, log=lambda *_: None)
    assert c.calls[0]['model'] == 'claude-haiku-5-5' == its[0]['summary_model']


def test_haiku_5_5_gets_low_effort_and_room_for_thinking(tmp_path):
    c = Client([GOOD])
    NS.summarize_items(items(tmp_path), str(tmp_path), model='claude-haiku-5-5', client=c,
                       log=lambda *_: None)
    assert c.calls[0]['output_config'] == {'effort': 'low'}
    assert c.calls[0]['max_tokens'] >= 4096


def test_other_models_get_no_effort(tmp_path):
    # Haiku 4.5·Sonnet 4.5 는 effort 를 받지 않는다 — Variable 로 롤백하면 전 기사가 400 이 된다
    for model in ('claude-haiku-4-5', 'claude-sonnet-4-5'):
        c = Client([GOOD])
        NS.summarize_items(items(tmp_path), str(tmp_path), model=model, client=c,
                           log=lambda *_: None)
        assert 'output_config' not in c.calls[0]


def test_a_truncated_reply_is_not_stored_even_in_band(tmp_path):
    its, c = items(tmp_path), Client([GOOD], stop='max_tokens')
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert 'summary_ko' not in its[0] and its[0]['summary_note'] == '출력 잘림'
    assert len(c.calls) == 1


def test_the_rewrite_turn_keeps_the_whole_reply(tmp_path):
    c = Client(['짧다', GOOD])
    NS.summarize_items(items(tmp_path), str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls[0]['messages']) == 1
    prior = c.calls[1]['messages'][1]
    assert prior['role'] == 'assistant'
    assert [b.type for b in prior['content']] == ['thinking', 'text']


def test_two_misses_leave_no_summary_and_a_reason(tmp_path):
    its = items(tmp_path)
    NS.summarize_items(its, str(tmp_path), model='m', client=Client(['짧다', '또 짧다']),
                       log=lambda *_: None)
    assert 'summary_ko' not in its[0] and '분량' in its[0]['summary_note']


def test_a_refusal_is_not_stored(tmp_path):
    its = items(tmp_path)
    NS.summarize_items(its, str(tmp_path), model='m', client=Client([GOOD], stop='refusal'),
                       log=lambda *_: None)
    assert 'summary_ko' not in its[0] and its[0]['summary_note'] == '모델 거절'


def test_articles_without_a_body_are_not_sent(tmp_path):
    its = [{'title': 'x', 'body_chars': 0, 'body_file': None}]
    c = Client([])
    assert NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None) == 0
    assert c.calls == []


def test_no_credentials_marks_every_article_and_calls_nothing(tmp_path, monkeypatch):
    for k in ('ANTHROPIC_API_KEY', *NS._WIF_VARS):
        monkeypatch.delenv(k, raising=False)
    its = items(tmp_path, 2)
    assert NS.summarize_items(its, str(tmp_path), log=lambda *_: None) == 0
    assert all(it['summary_note'] == '자격 증명 없음' for it in its)


WIF = {'ANTHROPIC_FEDERATION_RULE_ID': 'fdrl_1', 'ANTHROPIC_ORGANIZATION_ID': '0f3c9a52-7d1e-4b8a-9c2d-5e6f7a8b9c0d',
       'ANTHROPIC_SERVICE_ACCOUNT_ID': 'svac_1', 'ANTHROPIC_WORKSPACE_ID': 'wrkspc_1',
       'ACTIONS_ID_TOKEN_REQUEST_URL': 'https://gh/token?api-version=2.0',
       'ACTIONS_ID_TOKEN_REQUEST_TOKEN': 'req-tok'}


def test_credential_source_follows_sdk_precedence():
    assert NS.credential_source({}) is None
    assert NS.credential_source(WIF) == 'wif'
    assert NS.credential_source(dict(WIF, ANTHROPIC_API_KEY='k')) == 'api_key'
    # 워크플로 변수가 비어 있으면 빈 문자열로 온다 — 설정된 것으로 치지 않는다
    assert NS.credential_source(dict(WIF, ANTHROPIC_FEDERATION_RULE_ID='')) is None
    # Actions 밖이면 OIDC 토큰을 받을 곳이 없다
    assert NS.credential_source({k: v for k, v in WIF.items()
                                 if not k.startswith('ACTIONS_')}) is None


class _Resp:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def test_oidc_token_is_requested_with_the_anthropic_audience():
    seen = {}

    def opener(req, timeout):
        seen['url'], seen['auth'] = req.full_url, req.get_header('Authorization')
        return _Resp(b'{"value": "jwt-abc"}')

    assert NS.github_oidc_token(WIF, opener=opener) == 'jwt-abc'
    assert seen['url'] == 'https://gh/token?api-version=2.0&audience=https%3A%2F%2Fapi.anthropic.com'
    assert seen['auth'] == 'Bearer req-tok'


class FakeSDK:
    """anthropic 모듈 흉내 — 생성자에 넘긴 값을 기록한다."""
    def __init__(self):
        self.creds = None

    def WorkloadIdentityCredentials(self, **kw):
        self.creds = kw
        return ('creds', kw)

    def Anthropic(self, **kw):
        return kw


def test_wif_client_gets_a_provider_that_fetches_a_fresh_token_each_time(monkeypatch):
    calls = []
    monkeypatch.setattr(NS, 'github_oidc_token', lambda env=None: calls.append(1) or f'jwt{len(calls)}')
    sdk = FakeSDK()
    client = NS.make_client(dict(WIF, ANTHROPIC_WORKSPACE_ID=''), sdk=sdk)
    assert client['credentials'][0] == 'creds'
    kw = sdk.creds
    assert (kw['federation_rule_id'], kw['organization_id'], kw['service_account_id']) == \
        ('fdrl_1', '0f3c9a52-7d1e-4b8a-9c2d-5e6f7a8b9c0d', 'svac_1')
    assert kw['workspace_id'] is None            # 빈 문자열을 넘기지 않는다
    # 1회용 토큰 — 교환할 때마다 새로 받아야 한다
    assert kw['identity_token_provider']() == 'jwt1'
    assert kw['identity_token_provider']() == 'jwt2'


def test_pasted_whitespace_is_stripped_before_the_exchange(monkeypatch):
    sdk = FakeSDK()
    NS.make_client(dict(WIF, ANTHROPIC_ORGANIZATION_ID=' ' + WIF['ANTHROPIC_ORGANIZATION_ID'] + '\n',
                        ANTHROPIC_SERVICE_ACCOUNT_ID='svac_1 '), sdk=sdk)
    assert sdk.creds['organization_id'] == WIF['ANTHROPIC_ORGANIZATION_ID']
    assert sdk.creds['service_account_id'] == 'svac_1'


def test_wif_id_shapes_are_checked_before_the_exchange():
    assert NS.wif_config_problems(WIF) == []
    assert NS.wif_config_problems(dict(WIF, ANTHROPIC_WORKSPACE_ID='default')) == []
    # 2026-09-24 첫 실행: 교환 400 「organization_id: must be…」
    for bad in ('org_01ABC', 'My Org', ''):
        (p,) = NS.wif_config_problems(dict(WIF, ANTHROPIC_ORGANIZATION_ID=bad))
        assert 'ANTHROPIC_ORGANIZATION_ID' in p
    # 붙여 넣기 공백은 문제로 치지 않는다 — make_client 가 걷어 낸다
    assert NS.wif_config_problems(dict(WIF, ANTHROPIC_ORGANIZATION_ID=WIF['ANTHROPIC_ORGANIZATION_ID'] + '\n')) == []
    (p,) = NS.wif_config_problems(dict(WIF, ANTHROPIC_FEDERATION_RULE_ID='rule-1'))
    assert 'ANTHROPIC_FEDERATION_RULE_ID' in p
    (p,) = NS.wif_config_problems(dict(WIF, ANTHROPIC_SERVICE_ACCOUNT_ID='sa_1'))
    assert 'ANTHROPIC_SERVICE_ACCOUNT_ID' in p
    (p,) = NS.wif_config_problems(dict(WIF, ANTHROPIC_WORKSPACE_ID='Default Workspace'))
    assert 'ANTHROPIC_WORKSPACE_ID' in p
    # 2026-09-24: 규칙이 Default 워크스페이스 하나뿐인데도 워크스페이스 ID 없이 교환하면 401
    for missing in ('', '  '):
        (p,) = NS.wif_config_problems(dict(WIF, ANTHROPIC_WORKSPACE_ID=missing))
        assert 'ANTHROPIC_WORKSPACE_ID' in p
    env = dict(WIF)
    del env['ANTHROPIC_WORKSPACE_ID']
    (p,) = NS.wif_config_problems(env)
    assert 'ANTHROPIC_WORKSPACE_ID' in p


def test_a_malformed_org_id_skips_without_calling_the_api(tmp_path, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    for k, v in dict(WIF, ANTHROPIC_ORGANIZATION_ID='org_01ABCDEF').items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(NS, 'make_client', lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    logs, its = [], items(tmp_path, 2)
    assert NS.summarize_items(its, str(tmp_path), log=logs.append) == 0
    assert all(it['summary_note'] == 'WIF 설정 형식 오류' for it in its)
    assert any("'org_…' 12자" in line for line in logs)   # 값 전체는 공개 로그에 찍지 않는다


def test_no_sdk_or_no_credentials_means_no_client():
    assert NS.make_client({}, sdk=FakeSDK()) is None


class Boom(Exception):
    def __init__(self, name='x', status_code=None):
        super().__init__(name)
        self.status_code = status_code


class Raising(Client):
    def __init__(self, exc):
        super().__init__([])
        self.exc = exc

    def create(self, **kw):
        self.calls.append(kw)
        raise self.exc


def test_a_token_exchange_failure_stops_quietly_instead_of_raising(tmp_path):
    WorkloadIdentityError = type('WorkloadIdentityError', (Exception,), {})
    its = items(tmp_path, 3)
    c = Raising(WorkloadIdentityError('Token exchange failed (HTTP 401)'))
    assert NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None) == 0
    assert len(c.calls) == 1                      # 같은 벽에 세 번 부딪히지 않는다
    assert all('인증 실패' in it['summary_note'] for it in its)


def _jwt(claims):
    import base64
    import json
    b = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip('=')
    return f"{b({'alg': 'RS256'})}.{b(claims)}.sig"


def test_the_token_claims_are_logged_when_the_exchange_is_refused(tmp_path, monkeypatch):
    claims = {'iss': 'https://token.actions.githubusercontent.com', 'aud': 'https://api.anthropic.com',
              'sub': 'repo:fdo2a/fdo2a.github.io:ref:refs/heads/main', 'ref': 'refs/heads/main',
              'repository_owner': 'fdo2a', 'jti': 'secret-ish', 'run_id': '1'}
    NS.github_oidc_token(WIF, opener=lambda req, timeout: _Resp(
        ('{"value": "%s"}' % _jwt(claims)).encode()))
    assert NS.last_claims == {k: claims[k] for k in ('iss', 'aud', 'sub', 'ref', 'repository_owner')}
    WorkloadIdentityError = type('WorkloadIdentityError', (Exception,), {})
    logs = []
    NS.summarize_items(items(tmp_path), str(tmp_path), model='m',
                       client=Raising(WorkloadIdentityError('HTTP 401')), log=logs.append)
    assert any('refs/heads/main' in line and 'jti' not in line for line in logs)


def test_a_malformed_token_yields_no_claims():
    assert NS.token_claims('not-a-jwt') == {}


def test_a_401_stops_and_a_529_skips_only_that_article(tmp_path):
    its = items(tmp_path, 2)
    c = Raising(Boom(status_code=529))
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls) == 2 and all(it['summary_note'] == 'API 529' for it in its)
    its = items(tmp_path, 2)
    c = Raising(Boom(status_code=401))
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls) == 1


def test_a_caller_can_swap_the_system_prompt_for_korean_sources(tmp_path):
    # KR 뉴스(fetch_kr_news.py)는 한국어 원문이라 「옮겨 적지 말라」를 세게 말하는 지시문을 쓴다
    client = Client([GOOD, GOOD])
    its = items(tmp_path, 2)
    assert NS.summarize_items(its[:1], str(tmp_path), client=client, log=lambda m: None) == 1
    assert NS.summarize_items(its[1:], str(tmp_path), client=client, log=lambda m: None,
                              system=NS.SYSTEM_KO_SOURCE) == 1
    assert client.calls[0]['system'] == NS.SYSTEM
    assert client.calls[1]['system'] == NS.SYSTEM_KO_SOURCE
    assert '그대로 옮기거나' in NS.SYSTEM_KO_SOURCE


def test_both_prompts_ask_for_the_desk_register():
    """US·KR 발행본은 -다 로 고정했다(2026-09-24). 요약이 -습니다 면 뉴스 섹션만 다른 목소리가 된다."""
    for system in (NS.SYSTEM, NS.SYSTEM_KO_SOURCE):
        assert '(~다)' in system
        assert '존댓말' not in system
        assert '운용자' in system


JA = 'あ' * 300


def test_a_japanese_summary_is_rewritten_in_korean(tmp_path):
    """일본어 기사를 일본어로 요약해 오는 일이 있었다(2026-10-14 일본 수집분 4건, US 10/13·15·16)."""
    its, c = items(tmp_path), Client([JA, GOOD])
    assert NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None) == 1
    assert its[0]['summary_ko'] == GOOD and '한국어' in c.calls[1]['messages'][-1]['content']


def test_a_summary_that_stays_japanese_is_refused(tmp_path):
    its = items(tmp_path)
    assert NS.summarize_items(its, str(tmp_path), model='m', client=Client([JA, JA]),
                              log=lambda *_: None) == 0
    assert 'summary_ko' not in its[0] and its[0]['summary_note'] == '한국어 아님'


def test_is_korean():
    assert NS.is_korean('일본은행 총재가 16일 CPI 2% 목표에 가까워졌다고 말했다.')
    assert not NS.is_korean('日銀の植田総裁は16日、基調物価について述べた。')
    assert not NS.is_korean('')
    # 한국어 문장에 일본어 조각이 섞인 것(2026-10-18 일본 수집분 12건)
    assert not NS.is_korean('IMF는 13일 영국에 재정적자 削減 계획을 착실히 이행하라고 요구했다.')
    assert not NS.is_korean('东证 성장시장... 아니, 다시 정리합니다. 도쿄증권거래소 그로스 시장 지수가 급락했다.')


# ── 실을 수 있는 요약인가 (2026-10-18 게이트 방어) ─────────────────────
OK = '일본은행 총재가 16일 물가 목표에 가까워졌다고 말했다. ' * 8


def test_summary_problem_passes_a_clean_paragraph():
    assert NS.summary_problem(OK) is None
    # 문장 사이 단일 개행은 줄 접기다 — 확장기는 한 <p> 로 넣는다
    assert NS.summary_problem(OK.replace('. ', '.\n', 1)) is None


def test_summary_problem_names_every_cjk_range():
    # 반각 가나·가나 확장·확장 B 한자·보충 호환 한자·일본어 구두점(codex 설계 검토 #1)
    for frag in ('削減', '差し迫った', 'ニッセイ', 'ｾｲ', 'ㇰ', '\U0001B000', '\U00020000', '\U0002F800',
                 '神', '㐀', '令和8年産', '々', '。', '、'):
        p = NS.summary_problem(OK + frag + ' 했다.')
        assert p and '가나·한자' in p, frag
    assert '削減' in NS.summary_problem('재정적자 削減 계획을 이행한다. ' + OK)
    # 「」 와 전각 ％ 는 한국어에도 쓴다
    assert NS.summary_problem('총재는 「물가가 오른다」고 말했다. ' + OK) is None


def test_summary_problem_rejects_two_paragraphs_and_self_corrections():
    assert '문단' in NS.summary_problem('리슈몽, 데비어스 인수 협의 중…관계자 전언\n\n' + OK)
    for s in ('도쿄 성장시장... 아니, 다시 정리합니다. ' + OK,
              OK + '아니，다시 쓰겠습니다.',                  # 전각 쉼표(#7)
              OK + '아니​, 다시 정리합니다.',            # 폭 없는 공백(#7)
              OK + '다시 써 보겠습니다.',
              OK + '다시 요약하겠습니다.'):
        assert '정정' in (NS.summary_problem(s) or ''), s
    # 기사 속 인용은 모델의 정정이 아니다(#9) — -다 형 기사 문장도 그대로 둔다(#8 일부 기각)
    for s in (OK + '장관은 “자료를 다시 정리하겠습니다”라고 말했다.',
              OK + '장관은 자료를 다시 정리하겠습니다라고 말했다.',
              OK + '정부는 지침을 다시 정리한다.',
              OK + '그는 미국은 아니다, 다시 말해 유럽의 문제라고 했다.'):
        assert NS.summary_problem(s) is None, s


def test_summary_problem_keeps_the_language_rule():
    assert NS.summary_problem('') and NS.summary_problem(None)
    assert '한국어' in NS.summary_problem('The Bank of Japan held rates steady on Thursday. ' * 5)
    assert NS.usable_summary(OK) and not NS.usable_summary('東証')


def test_a_two_paragraph_summary_is_rewritten(tmp_path):
    its = items(tmp_path)
    c = Client(['제목 머리말\n\n' + GOOD, GOOD])
    assert NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None) == 1
    assert its[0]['summary_ko'] == GOOD and '문단 하나' in c.calls[1]['messages'][-1]['content']


def test_a_summary_that_keeps_correcting_itself_is_refused(tmp_path):
    its = items(tmp_path)
    bad = '아니, 다시 정리합니다. ' + GOOD
    assert NS.summarize_items(its, str(tmp_path), model='m', client=Client([bad, bad]),
                              log=lambda *_: None) == 0
    assert 'summary_ko' not in its[0] and '정정' in its[0]['summary_note']


def test_codex_implementation_review_bypasses():
    # #1 기사 속 인용 — 마침표 뒤 닫는 따옴표, 「아니, 다시 …」 인용
    for s in (OK + '장관은 “아니, 다시 정리하겠습니다”라고 말했다.',
              OK + '장관은 “자료를 다시 정리하겠습니다.”라고 말했다.'):
        assert NS.summary_problem(s) is None, s
    # 재검토 #6 — 여는 따옴표 없이 닫는 따옴표만 붙인 것은 인용이 아니다
    for s in (OK + '아니, 다시 정리합니다.”', OK + "아니, 다시 정리합니다.'", OK + '다시 요약하겠습니다」'):
        assert '정정' in (NS.summary_problem(s) or ''), s
    assert NS.summary_problem(OK + '그는 「아니, 다시 쓰겠습니다」고 했다.') is None
    assert NS.summary_problem(OK + "그는 '다시 정리하겠습니다'라고 했다.") is None
    # #2 CRLF 빈 줄
    assert '문단' in NS.summary_problem('제목\r\n\r\n' + OK)
    assert '문단' in NS.summary_problem('제목\r\r' + OK)
    # #3 호환 문자·확장 H·가나 확장 B
    for frag in ('㍿', '㋐', '\U00031350', '\U0001AFF0'):
        assert '가나·한자' in (NS.summary_problem(OK + frag) or ''), repr(frag)
        assert not NS.is_korean(OK + frag)
    # #4 보이지 않는 서식 문자
    for s in (OK + '다시⁣정리합니다.', OK + '다시­정리합니다.'):
        assert '정정' in (NS.summary_problem(s) or ''), repr(s)


def test_the_final_refusal_names_the_specific_problem(tmp_path):
    its = items(tmp_path)
    bad = GOOD + '削減'
    assert NS.summarize_items(its, str(tmp_path), model='m', client=Client([bad, bad]),
                              log=lambda *_: None) == 0
    assert its[0]['summary_note'] == '가나·한자 「削減」'


# ── 막힘 승격: Haiku 2회(작성+고쳐 쓰기)가 검사에 걸리면 Sonnet 1회 (2026-10-27) ──
HAIKU, SONNET = 'claude-haiku-5-5', 'claude-sonnet-5-5'


import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_escalation_budget(monkeypatch):
    monkeypatch.setattr(NS, '_escalations', 0)
    monkeypatch.setattr(NS, '_escalate_off', False)


class ByModel(Client):
    """모델별 응답 목록. 항목은 글, (stop_reason, 글), 또는 예외."""
    def __init__(self, **replies):
        super().__init__([])
        self.by = {m.replace('_', '-'): list(r) for m, r in replies.items()}

    def create(self, **kw):
        self.calls.append(dict(kw, messages=list(kw['messages'])))
        r = self.by[kw['model']].pop(0)
        if isinstance(r, Exception):
            raise r
        stop, text = r if isinstance(r, tuple) else ('end_turn', r)
        return types.SimpleNamespace(stop_reason=stop, content=[types.SimpleNamespace(type='text', text=text)])


def models(c):
    return [x['model'] for x in c.calls]


def test_haiku_failing_twice_escalates_once_to_sonnet(tmp_path):
    its = items(tmp_path)
    c = ByModel(claude_haiku_5_5=['짧다', '또 짧다'], claude_sonnet_5_5=[GOOD])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 1
    assert models(c) == [HAIKU, HAIKU, SONNET]
    assert its[0]['summary_ko'] == GOOD and its[0]['summary_model'] == SONNET
    assert len(c.calls[2]['messages']) == 1          # 새로 시작한다 — Haiku 의 실패 이력을 넘기지 않는다


def test_sonnet_also_failing_stops_after_three_calls(tmp_path):
    its = items(tmp_path)
    c = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=['짧다'])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 0
    assert models(c) == [HAIKU, HAIKU, SONNET] and 'summary_ko' not in its[0]
    assert '분량' in its[0]['summary_note']


def test_refusal_truncation_and_api_errors_do_not_escalate(tmp_path):
    for first in (('refusal', GOOD), ('max_tokens', GOOD), Boom(status_code=529)):
        its = items(tmp_path)
        c = ByModel(claude_haiku_5_5=[first], claude_sonnet_5_5=[GOOD])
        NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None)
        assert models(c) == [HAIKU] and 'summary_ko' not in its[0]


def test_a_refusal_or_truncation_on_the_escalated_call_is_final(tmp_path):
    for stop in ('refusal', 'max_tokens'):
        its = items(tmp_path)
        c = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=[(stop, GOOD)])
        NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None)
        assert models(c) == [HAIKU, HAIKU, SONNET] and 'summary_ko' not in its[0]


def test_an_auth_failure_during_escalation_stops_the_rest(tmp_path):
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=[Boom(status_code=401)])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 0
    assert models(c) == [HAIKU, HAIKU, SONNET]
    assert all('인증 실패' in it['summary_note'] for it in its)


def test_the_next_article_starts_on_haiku_again(tmp_path):
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=['짧다', '짧다', GOOD], claude_sonnet_5_5=[GOOD])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 2
    assert models(c) == [HAIKU, HAIKU, SONNET, HAIKU]
    assert [it['summary_model'] for it in its] == [SONNET, HAIKU]


def test_escalation_keeps_the_callers_system_prompt_and_effort(tmp_path):
    c = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=[GOOD])
    NS.summarize_items(items(tmp_path), str(tmp_path), model=HAIKU, client=c, log=lambda *_: None,
                       system='KO-SOURCE')
    assert c.calls[2]['system'] == 'KO-SOURCE'
    assert c.calls[2]['output_config'] == {'effort': 'low'}


def test_only_a_haiku_base_escalates(tmp_path):
    for base in (SONNET, 'claude-opus-5-5', 'm'):
        c = ByModel(**{base.replace('-', '_'): ['짧다', '짧다']})
        NS.summarize_items(items(tmp_path), str(tmp_path), model=base, client=c, log=lambda *_: None)
        assert models(c) == [base, base]


def test_escalations_per_run_are_capped(tmp_path, monkeypatch):
    monkeypatch.setattr(NS, 'ESCALATE_CAP', 1)
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=['짧다'] * 4, claude_sonnet_5_5=[GOOD, GOOD])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 1
    assert models(c) == [HAIKU, HAIKU, SONNET, HAIKU, HAIKU]
    assert 'summary_ko' not in its[1] and '분량' in its[1]['summary_note']


def test_the_cap_is_shared_across_calls_in_one_run(tmp_path, monkeypatch):
    # 뉴스 → 칼럼, 날짜 → 다음 날짜처럼 같은 실행이 여러 번 부른다
    monkeypatch.setattr(NS, 'ESCALATE_CAP', 1)
    c = ByModel(claude_haiku_5_5=['짧다'] * 4, claude_sonnet_5_5=[GOOD, GOOD])
    NS.summarize_items(items(tmp_path), str(tmp_path), model=HAIKU, client=c, log=lambda *_: None)
    its = items(tmp_path)
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 0
    assert models(c) == [HAIKU, HAIKU, SONNET, HAIKU, HAIKU]


def test_a_403_on_the_escalated_model_only_turns_escalation_off(tmp_path):
    its = items(tmp_path, 3)
    c = ByModel(claude_haiku_5_5=['짧다', '짧다', GOOD, '짧다', '짧다'],
                claude_sonnet_5_5=[Boom(status_code=403)])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 1
    assert models(c) == [HAIKU, HAIKU, SONNET, HAIKU, HAIKU, HAIKU]
    assert its[0]['summary_note'] == '승격 모델 권한 없음 API 403'
    assert its[1]['summary_model'] == HAIKU and '분량' in its[2]['summary_note']


def test_a_failure_on_the_second_haiku_call_does_not_escalate(tmp_path):
    for second in (('refusal', GOOD), ('max_tokens', GOOD), Boom(status_code=529)):
        its = items(tmp_path)
        c = ByModel(claude_haiku_5_5=['짧다', second], claude_sonnet_5_5=[GOOD])
        NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None)
        assert models(c) == [HAIKU, HAIKU] and 'summary_ko' not in its[0]


def test_a_non_auth_error_on_sonnet_skips_only_that_article(tmp_path):
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=['짧다', '짧다', GOOD], claude_sonnet_5_5=[Boom(status_code=529)])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 1
    assert its[0]['summary_note'] == 'API 529' and its[1]['summary_ko'] == GOOD


def test_a_failed_escalation_still_spends_the_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(NS, 'ESCALATE_CAP', 1)
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=['짧다'] * 4, claude_sonnet_5_5=['짧다'])
    NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None)
    assert models(c) == [HAIKU, HAIKU, SONNET, HAIKU, HAIKU]


def test_articles_done_before_an_auth_stop_keep_their_summary(tmp_path):
    its = items(tmp_path, 2)
    c = ByModel(claude_haiku_5_5=[GOOD, '짧다', '짧다'], claude_sonnet_5_5=[Boom(status_code=401)])
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=c, log=lambda *_: None) == 1
    assert its[0]['summary_ko'] == GOOD and '인증 실패' in its[1]['summary_note']


def test_new_run_gives_an_independent_run_its_own_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(NS, 'ESCALATE_CAP', 1)
    a = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=[Boom(status_code=403)])
    NS.summarize_items(items(tmp_path), str(tmp_path), model=HAIKU, client=a, log=lambda *_: None)
    assert NS._escalate_off and NS._escalations == 1
    NS.new_run()
    b = ByModel(claude_haiku_5_5=['짧다', '짧다'], claude_sonnet_5_5=[GOOD])
    its = items(tmp_path)
    assert NS.summarize_items(its, str(tmp_path), model=HAIKU, client=b, log=lambda *_: None) == 1
    assert models(b) == [HAIKU, HAIKU, SONNET]


def test_every_collector_main_starts_a_new_run():
    import inspect
    import fetch_japan_news, fetch_kr_news, fetch_news
    for mod in (fetch_news, fetch_kr_news, fetch_japan_news):
        lines = inspect.getsource(mod.main).splitlines()[1:]
        assert lines[0].strip().startswith('new_run()'), mod.__name__
