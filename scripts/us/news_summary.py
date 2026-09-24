"""기사 본문 -> 한국어 300자 요약. GitHub Actions 수집 잡에서만 돈다 (2026-09-24).

**왜 여기서 요약하나.** 뉴스 다이제스트는 9/19 에 만들어졌지만 한 번도 발행되지 않았다.
본문은 Actions 러너에서만 받아진다 — 클라우드 루틴 환경은 CNBC·Yahoo 에 403 이고,
WebFetch 도구도 CNBC 에 403 이다(2026-09-24 실측). 그런데 본문은 상업 저작물이라 공개
레포에 커밋할 수 없어서, 루틴의 작성 담당은 요약할 재료를 한 번도 갖지 못했다. 루틴이
본문을 다시 받으려다 실패하면 `body_chars` 가 0 이 되고, 게이트는 「본문 없음 → 섹션
면제」로 통과시켰다.

그래서 본문이 있는 곳에서 요약까지 끝내고, **우리가 쓴 요약만** 커밋한다. 원문 문장을
옮기지 않게 지시하므로 저작권 문제도 없다.

모델은 `NEWS_SUMMARY_MODEL`(기본 Haiku 4.5 — 2026-09-24 사용자 선택).

**자격 증명은 Workload Identity Federation 이다** (2026-09-24 사용자 선택). 레포에 정적 키를
두지 않고, GitHub Actions 가 발급하는 OIDC 토큰을 Anthropic 토큰으로 교환한다. GitHub 토큰은
약 5분 뒤 만료되고 **한 번만 교환할 수 있다**(`jti`). 그래서 토큰 파일을 미리 써 두지 않고
`github_oidc_token` 을 SDK 에 **공급자 함수로** 넘긴다 — SDK 가 교환(첫 요청·만료 전 갱신)할
때마다 이 함수를 불러 새 토큰을 받는다(anthropic 1.8.0 소스로 확인: `IdentityTokenProvider
= Callable[[], str]`, 교환마다 재호출). 필요한 값은 레포 Variables 의
`ANTHROPIC_FEDERATION_RULE_ID`·`ANTHROPIC_ORGANIZATION_ID`·`ANTHROPIC_SERVICE_ACCOUNT_ID`
`ANTHROPIC_WORKSPACE_ID` 와 Actions 가 주는 `ACTIONS_ID_TOKEN_REQUEST_URL/TOKEN`. 워크스페이스
ID 는 SDK 가 선택 인자로 받지만 **빠지면 교환이 401 이다** — 규칙이 워크스페이스 하나여도(2026-09-24 실측).
로컬에서는 `ANTHROPIC_API_KEY` 로도 돈다.

자격 증명이 없거나 호출이 실패하면 그 기사에 `summary_ko` 가 없을 뿐이다 — 게이트는
요약 없는 기사를 쓸 수 없게 막고, 그날 뉴스 섹션은 빠진다. **어떤 실패도 예외로 새지
않는다** — 새면 수집분 저장까지 날아간다(2026-09-24 구현 검토 #2).
"""

import base64
import json
import os
import re
import urllib.parse
import urllib.request

try:                        # Actions 에서만 설치한다(워크플로). 로컬 테스트는 가짜 클라이언트.
    import anthropic as _sdk
except ImportError:         # pragma: no cover - 환경에 따라
    _sdk = None

DEFAULT_MODEL = 'claude-haiku-4-5'
AUDIENCE = 'https://api.anthropic.com'

# 게이트의 요약 분량 띠(news_gate.MIN_CHARS·MAX_CHARS = 240·420, **공백 제외**)보다 안쪽을
# 겨눈다 — 작성 담당이 문장을 다듬어도 띠 밖으로 나가지 않게. 세는 방식도 게이트와 같다.
TARGET_MIN, TARGET_MAX = 270, 370
BAND_MIN, BAND_MAX = 250, 400
MAX_BODY_CHARS = 12000

SYSTEM = (
    '당신은 한국어 경제 뉴스 요약가입니다. 영어 기사 본문을 받아 한국 독자용 요약 한 '
    '문단을 씁니다.\n'
    f'- 분량은 공백을 뺀 글자 수로 {TARGET_MIN}~{TARGET_MAX}자입니다'
    f'(공백 포함 약 {TARGET_MIN * 5 // 4}~{TARGET_MAX * 5 // 4}자).\n'
    '- 누가 무엇을 했는지, 핵심 수치와 날짜, 그 사건이 왜 중요한지를 기사에 적힌 '
    '범위에서만 씁니다. 기사에 없는 전망·해석·시장 영향은 덧붙이지 않습니다.\n'
    '- 원문 문장을 그대로 번역해 이어 붙이지 말고 자기 문장으로 다시 씁니다. 직접 '
    '인용은 꼭 필요할 때 짧게 한 번까지입니다.\n'
    '- 존댓말(~습니다)로 쓰고, 제목·머리말·목록·따옴표 없이 요약 문단만 출력합니다.'
)

# 국내 기사(KR 뉴스, `fetch_kr_news.py`). 원문이 이미 한국어라 **옮겨 적기가 가장 쉬운 실패다** —
# 기사 문장을 이어 붙인 요약은 공개 레포에 원문 일부를 커밋하는 것과 같다. 그래서 「자기
# 문장으로」를 번역 기사보다 세게 말한다. 나머지 계약(분량·사실 범위·문체)은 SYSTEM 과 같다.
SYSTEM_KO_SOURCE = (
    '당신은 한국어 경제 뉴스 요약가입니다. 국내 언론의 한국어 기사 본문을 받아 증권 '
    '운용자용 요약 한 문단을 씁니다.\n'
    f'- 분량은 공백을 뺀 글자 수로 {TARGET_MIN}~{TARGET_MAX}자입니다'
    f'(공백 포함 약 {TARGET_MIN * 5 // 4}~{TARGET_MAX * 5 // 4}자).\n'
    '- 누가 무엇을 했는지, 핵심 수치와 날짜, 그 사건이 왜 중요한지를 기사에 적힌 '
    '범위에서만 씁니다. 기사에 없는 전망·해석·시장 영향은 덧붙이지 않습니다.\n'
    '- 기사 문장을 그대로 옮기거나 어미만 바꿔 이어 붙이지 않습니다. 내용을 소화해 '
    '문장 구조부터 새로 씁니다. 직접 인용은 꼭 필요할 때 짧게 한 번까지입니다.\n'
    '- 기자 이름·매체 홍보·광고 문구는 쓰지 않습니다.\n'
    '- 존댓말(~습니다)로 쓰고, 제목·머리말·목록·따옴표 없이 요약 문단만 출력합니다.'
)

_WIF_VARS = ('ANTHROPIC_FEDERATION_RULE_ID', 'ANTHROPIC_ORGANIZATION_ID',
             'ANTHROPIC_SERVICE_ACCOUNT_ID')
_GHA_VARS = ('ACTIONS_ID_TOKEN_REQUEST_URL', 'ACTIONS_ID_TOKEN_REQUEST_TOKEN')
_AUTH_ERRORS = ('AuthenticationError', 'PermissionDeniedError',
                'WorkloadIdentityError', 'IdentityTokenFileError')
# 조직 ID 는 **접두사 없는 UUID** 다(SDK docstring: "organizations do not use tagged IDs").
# 2026-09-24 첫 실행이 다른 형식으로 교환 400 「organization_id: must be…」에 막혔다 —
# 교환 전에 걸러 로그에 어느 칸이 틀렸는지 적는다.
_UUID = re.compile(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}')


# ── 자격 증명 ────────────────────────────────────────────────────────────
def credential_source(env=None):
    """'api_key' · 'wif' · None — SDK 우선순위처럼 키가 먼저다. 빈 문자열은 없는 것으로 본다."""
    env = os.environ if env is None else env
    if env.get('ANTHROPIC_API_KEY'):
        return 'api_key'
    if all(env.get(k) for k in _WIF_VARS + _GHA_VARS):
        return 'wif'
    return None


def _v(env, key):
    """Variables 칸에 붙여 넣다 딸려 온 공백·줄바꿈을 걷는다."""
    return (env.get(key) or '').strip()


def _shape(value):
    """공개 로그에 값 전체를 찍지 않고 형식만 보인다."""
    return f"'{value[:4]}…' {len(value)}자" if value else '빈 값'


def wif_config_problems(env=None):
    """교환을 보내기 전에 알 수 있는 WIF 설정 오류 — 형식이 문서로 확정된 칸만 본다."""
    env = os.environ if env is None else env
    problems = []
    org = _v(env, 'ANTHROPIC_ORGANIZATION_ID')
    if not _UUID.fullmatch(org):
        problems.append(f'ANTHROPIC_ORGANIZATION_ID 는 접두사 없는 UUID'
                        f'(xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx)여야 한다 — 받은 값 {_shape(org)}')
    # 접두사는 서버 응답으로 확인(2026-09-24): 「not a well-formed fdrl_ tagged ID」·
    # 「service_account_id: does not have prefix `svac_`」. 앞뒤 공백 하나로도 같은 400 이 난다.
    for key, prefix in (('ANTHROPIC_FEDERATION_RULE_ID', 'fdrl_'),
                        ('ANTHROPIC_SERVICE_ACCOUNT_ID', 'svac_')):
        value = _v(env, key)
        if not value.startswith(prefix):
            problems.append(f"{key} 는 '{prefix}…' 로 시작해야 한다 — 받은 값 {_shape(value)}")
    # 에러 문구는 「규칙이 워크스페이스 여러 개면」이라 하지만, 하나여도 없으면 401 이었다
    # (2026-09-24 — Default 하나에 걸린 규칙, 넣자마자 18/18 요약).
    ws = _v(env, 'ANTHROPIC_WORKSPACE_ID')
    if not ws:
        problems.append('ANTHROPIC_WORKSPACE_ID 가 없다 — 규칙이 워크스페이스 하나여도 교환이 401 이다')
    elif ws != 'default' and not ws.startswith('wrkspc_'):
        problems.append(f"ANTHROPIC_WORKSPACE_ID 는 'wrkspc_…' 또는 'default' 여야 한다 — "
                        f'받은 값 {_shape(ws)}')
    return problems


# 교환이 401 이면 규칙과 토큰 중 어느 칸이 어긋났는지가 문제다 — 마지막으로 받은 토큰의
# **대조용 클레임만** 기억했다가 로그에 찍는다(2026-09-24 두 번째 실행: 401 「Ensure your
# federation rule matches your identity token」). 서명·jti 는 남기지 않는다.
DIAG_CLAIMS = ('iss', 'aud', 'sub', 'repository_owner', 'ref', 'event_name')
last_claims = {}


def token_claims(jwt):
    """JWT 페이로드에서 대조용 클레임만. 서명은 검증하지 않는다 — 진단용이다."""
    try:
        payload = jwt.split('.')[1]
        data = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    except Exception:
        return {}
    return {k: data[k] for k in DIAG_CLAIMS if k in data}


def github_oidc_token(env=None, opener=urllib.request.urlopen):
    """GitHub Actions OIDC 토큰을 **매번 새로** 받는다. 실패하면 예외를 올린다."""
    env = os.environ if env is None else env
    url, bearer = env['ACTIONS_ID_TOKEN_REQUEST_URL'], env['ACTIONS_ID_TOKEN_REQUEST_TOKEN']
    sep = '&' if '?' in url else '?'      # Actions 의 URL 에는 이미 ?api-version= 이 붙어 있다
    req = urllib.request.Request(f'{url}{sep}audience={urllib.parse.quote(AUDIENCE, safe="")}',
                                 headers={'Authorization': f'Bearer {bearer}'})
    with opener(req, timeout=20) as r:
        token = json.loads(r.read().decode('utf-8'))['value']
    last_claims.clear()
    last_claims.update(token_claims(token))
    return token


def make_client(env=None, sdk=None):
    """자격 증명에 맞는 클라이언트. 자격 증명이나 SDK 가 없으면 None."""
    env = os.environ if env is None else env
    sdk = sdk or _sdk
    source = credential_source(env)
    if source is None or sdk is None:
        return None
    if source == 'api_key':
        return sdk.Anthropic(max_retries=3, timeout=60.0)
    creds = sdk.WorkloadIdentityCredentials(
        identity_token_provider=lambda: github_oidc_token(env),
        federation_rule_id=_v(env, 'ANTHROPIC_FEDERATION_RULE_ID'),
        organization_id=_v(env, 'ANTHROPIC_ORGANIZATION_ID'),
        service_account_id=_v(env, 'ANTHROPIC_SERVICE_ACCOUNT_ID'),
        workspace_id=_v(env, 'ANTHROPIC_WORKSPACE_ID') or None)
    return sdk.Anthropic(credentials=creds, max_retries=3, timeout=60.0)


def is_auth_failure(e):
    """전 건 공통으로 멈춰야 하는 실패 — 키 거부·권한 없음·토큰 교환 실패."""
    return getattr(e, 'status_code', None) in (401, 403) or type(e).__name__ in _AUTH_ERRORS


def describe(e):
    code = getattr(e, 'status_code', None)
    if code:
        return f'API {code}'
    if type(e).__name__ in ('APIConnectionError', 'APITimeoutError'):
        return 'API 연결 실패'
    return type(e).__name__


# ── 요약 ─────────────────────────────────────────────────────────────────
def _prompt(item, body):
    return (f"제목: {item.get('title') or ''}\n"
            f"매체: {item.get('source') or ''} · {item.get('published') or ''}\n\n"
            f"본문:\n{body[:MAX_BODY_CHARS]}")


def _text(response):
    return ''.join(b.text for b in response.content if b.type == 'text').strip()


def chars(text):
    """공백을 뺀 글자 수 — news_gate 가 블록 분량을 재는 방식."""
    return len(re.sub(r'\s+', '', text or ''))


def in_band(text):
    return BAND_MIN <= chars(text) <= BAND_MAX


def summarize_one(client, model, item, body, system=None):
    """(요약, 사유). 분량이 벗어나면 한 번만 고쳐 쓰게 한다. 인증 실패는 예외로 올린다."""
    messages = [{'role': 'user', 'content': _prompt(item, body)}]
    text = ''
    try:
        for _ in range(2):
            response = client.messages.create(model=model, max_tokens=1024,
                                              system=system or SYSTEM,
                                              messages=messages)
            if response.stop_reason == 'refusal':
                return None, '모델 거절'
            text = _text(response)
            if in_band(text):
                return text, None
            messages += [{'role': 'assistant', 'content': text},
                         {'role': 'user', 'content':
                          f'지금 공백 제외 {chars(text)}자입니다. 공백 제외 '
                          f'{TARGET_MIN}~{TARGET_MAX}자로 다시 써 주세요. 요약 문단만 '
                          f'출력합니다.'}]
        return None, f'분량 벗어남 {chars(text)}자'
    except Exception as e:                  # SDK 예외 계층을 가리지 않는다 — 새면 저장이 날아간다
        if is_auth_failure(e):
            raise
        return None, describe(e)


def summarize_items(items, bodydir, model=None, client=None, log=print, system=None):
    """본문 파일이 있는 기사마다 `summary_ko` 를 채운다. 제자리 수정, 성공 건수 반환.

    어떤 실패도 예외로 내보내지 않는다 — 호출자는 이 뒤에 수집분을 다시 저장한다.
    """
    todo = [it for it in items if it.get('body_chars') and it.get('body_file')]
    if not todo:
        return 0

    def mark_all(note):
        for it in todo:
            if not it.get('summary_ko'):
                it['summary_note'] = note

    if client is None:
        if credential_source() == 'wif' and wif_config_problems():
            mark_all('WIF 설정 형식 오류')
            for p in wif_config_problems():
                log(f'  요약 건너뜀 — {p}')
            return 0
        try:
            client = make_client()
        except Exception as e:              # 잘못된 설정값으로 생성자부터 실패하는 경우
            mark_all(f'클라이언트 생성 실패 {type(e).__name__}')
            log(f'  요약 건너뜀 — 클라이언트 생성 실패 ({type(e).__name__})')
            return 0
        if client is None:
            why = 'anthropic 패키지 없음' if credential_source() else '자격 증명 없음'
            mark_all(why)
            log(f'  요약 건너뜀 — {why} (WIF 변수 또는 ANTHROPIC_API_KEY)')
            return 0
    model = model or os.environ.get('NEWS_SUMMARY_MODEL') or DEFAULT_MODEL

    done = 0
    for it in todo:
        try:
            with open(os.path.join(bodydir, it['body_file']), encoding='utf-8') as fh:
                body = fh.read()
        except OSError as e:
            it['summary_note'] = f'본문 파일 없음 {type(e).__name__}'
            continue
        try:
            text, why = summarize_one(client, model, it, body, system=system)
        except Exception as e:              # 인증 실패 — 남은 건도 같은 벽에 부딪힌다
            mark_all(f'인증 실패 {type(e).__name__}')
            log(f'  요약 중단 — 인증 실패 ({type(e).__name__}: {str(e)[:400]}) '
                f'— WIF 는 Console 「인증 기록」에서 사유를 본다')
            if last_claims:
                log('  GitHub 토큰 클레임 (Console 규칙의 발급자·대상·주체 접두사·클레임과 '
                    '한 글자씩 대조): ' + json.dumps(last_claims, ensure_ascii=False))
            return done
        if text:
            it['summary_ko'], it['summary_model'] = text, model
            it.pop('summary_note', None)
            done += 1
            log(f"  요약 {chars(text)}자  {(it.get('title') or '')[:50]}")
        else:
            it['summary_note'] = why
            log(f"  요약 실패({why})  {(it.get('title') or '')[:50]}")
    return done
