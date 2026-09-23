"""Actions 에서 기사 본문을 한국어 요약으로 — scripts/us/news_summary.py."""
import types

from us import news_summary as NS

GOOD = '가' * 300


class Client:
    def __init__(self, replies, stop='end_turn'):
        self.replies, self.calls, self.stop = list(replies), [], stop
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        text = self.replies.pop(0)
        return types.SimpleNamespace(
            stop_reason=self.stop,
            content=[types.SimpleNamespace(type='text', text=text)])


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


WIF = {'ANTHROPIC_FEDERATION_RULE_ID': 'fdrl_1', 'ANTHROPIC_ORGANIZATION_ID': 'org',
       'ANTHROPIC_SERVICE_ACCOUNT_ID': 'svac_1',
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
        ('fdrl_1', 'org', 'svac_1')
    assert kw['workspace_id'] is None            # 빈 문자열을 넘기지 않는다
    # 1회용 토큰 — 교환할 때마다 새로 받아야 한다
    assert kw['identity_token_provider']() == 'jwt1'
    assert kw['identity_token_provider']() == 'jwt2'


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


def test_a_401_stops_and_a_529_skips_only_that_article(tmp_path):
    its = items(tmp_path, 2)
    c = Raising(Boom(status_code=529))
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls) == 2 and all(it['summary_note'] == 'API 529' for it in its)
    its = items(tmp_path, 2)
    c = Raising(Boom(status_code=401))
    NS.summarize_items(its, str(tmp_path), model='m', client=c, log=lambda *_: None)
    assert len(c.calls) == 1
