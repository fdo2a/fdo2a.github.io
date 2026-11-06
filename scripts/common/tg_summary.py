"""Korean summaries for Telegram items (2026-11-06). Runs in the collection job only.

- report  : the linked ARTICLE body, with the news collector's own prompts and band
            (us.news_summary.summarize_one) — attribution then rests on the article itself.
- view/opinion: the post text, short band. The writer of the post stays the owner of every
            forecast; nothing the post does not say is added; no sentence is copied.
Never raises; every item ends with summary_ko or summary_note. Bodies are never logged.
"""
import os
import re
from difflib import SequenceMatcher

from us import news_summary as ns

BAND = (60, 260)              # chars without spaces, for short posts
COPY_LIMIT = 0.8              # share of the summary that may match the source verbatim

_RULES = (
    '- 원문 문장을 그대로 옮기거나 어미만 바꿔 이어 붙이지 않습니다. 내용을 소화해 문장 구조부터 새로 씁니다.\n'
    '- 원문에 없는 수치·사실·전망·해석은 덧붙이지 않습니다. 수치는 원문에 적힌 그대로만 씁니다.\n'
    '- 날수는 숫자로 씁니다(「이틀 연속」→「2일 연속」). 「하루」는 그대로 둡니다.\n'
    '- 평서문(~다)으로, 제목·머리말·목록·따옴표·채널 이름·해시태그·링크 없이 한 문단만 출력합니다.\n'
    f'- 분량은 공백을 뺀 글자 수로 {BAND[0]}~{BAND[1]}자입니다.'
)
SYSTEM_VIEW = (
    '당신은 증권사 리서치 메모를 요약하는 한국어 편집자입니다. 애널리스트가 짧게 올린 시황·전략 메모를 받아 '
    '그 애널리스트의 판단과 근거를 한 문단으로 정리합니다.\n'
    '- 판단·전망은 모두 필자의 견해로 씁니다(「필자는 …로 본다」 「…라고 진단했다」). 단정형 사실로 옮기지 않습니다.\n'
    + _RULES)
SYSTEM_OPINION = (
    '당신은 시장 속보·논평을 요약하는 한국어 편집자입니다. 짧은 시장 소식이나 의견 글을 받아 '
    '무엇이 전해졌고 어떤 시각이 제시됐는지를 한 문단으로 정리합니다.\n'
    '- 글쓴이의 해석·전망은 「…라는 시각」 「…라는 의견」처럼 견해로 남깁니다. 확인된 사실처럼 단정하지 않습니다.\n'
    + _RULES)


def copied_share(summary, source):
    a, b = re.sub(r'\s+', '', summary or ''), re.sub(r'\s+', '', source or '')
    if not a or not b:
        return 0.0
    blocks = SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks()
    return sum(m.size for m in blocks if m.size >= 8) / len(a)


def _short(client, model, item, body):
    system = SYSTEM_VIEW if item['kind'] == 'view' else SYSTEM_OPINION
    messages = [{'role': 'user', 'content': f'원문:\n{body[:4000]}'}]
    text = ''
    for _ in range(2):
        extra = {'output_config': {'effort': ns.EFFORT_MODELS[model]}} if model in ns.EFFORT_MODELS else {}
        r = client.messages.create(model=model, max_tokens=ns.MAX_TOKENS, system=system,
                                   messages=messages, **extra)
        if r.stop_reason in ('refusal', 'max_tokens'):
            return None, '모델 거절' if r.stop_reason == 'refusal' else '출력 잘림'
        text = ns._text(r)
        problem = ns.summary_problem(text)
        if problem is None and BAND[0] <= ns.chars(text) <= BAND[1]:
            return text, None
        messages += [{'role': 'assistant', 'content': r.content},
                     {'role': 'user', 'content': f'공백 제외 {BAND[0]}~{BAND[1]}자, 한 문단으로 다시 써 주세요.'}]
    return None, ns.summary_problem(text) or f'분량 벗어남 {ns.chars(text)}자'


def summarize(items, bodies, client=None, model=None, log=print):
    """items: dicts with id/kind; bodies: id -> source text (article body for report, post text
    otherwise). Fills summary_ko / summary_note in place. Returns (done, failed)."""
    todo = [it for it in items if not it.get('summary_ko')]
    if not todo:
        return 0, 0
    if client is None:
        try:
            if ns.credential_source() == 'wif' and ns.wif_config_problems():
                raise RuntimeError('WIF 설정 형식 오류')
            client = ns.make_client()
            if client is None:
                raise RuntimeError('자격 증명 없음')
        except Exception as e:                       # noqa: BLE001
            for it in todo:
                it['summary_note'] = f'요약 클라이언트 없음 {type(e).__name__}'
            log(f'  텔레그램 요약 건너뜀 — {type(e).__name__}')
            return 0, len(todo)
    model = model or os.environ.get('NEWS_SUMMARY_MODEL') or ns.DEFAULT_MODEL
    done = failed = 0
    for it in todo:
        body = bodies.get(it['id']) or ''
        if not body.strip():
            it['summary_note'] = '본문 없음'
            failed += 1
            continue
        try:
            if it['kind'] == 'report':
                ko = bool(re.search(r'[가-힣]', body[:400]))
                text, why = ns.summarize_one(client, model, {'title': '', 'source': it['source'].get('name') or ''},
                                             body, system=ns.SYSTEM_KO_SOURCE if ko else None)
            else:
                text, why = _short(client, model, it, body)
        except Exception as e:                       # noqa: BLE001 — auth failure stops the rest
            if ns.is_auth_failure(e):
                for x in todo:
                    if not x.get('summary_ko'):
                        x['summary_note'] = f'인증 실패 {type(e).__name__}'
                log(f'  텔레그램 요약 중단 — 인증 실패 {type(e).__name__}')
                return done, len(todo) - done
            text, why = None, ns.describe(e)
        if text and copied_share(text, body) > COPY_LIMIT:
            text, why = None, '원문 복제'
        if text:
            it['summary_ko'] = text
            it.pop('summary_note', None)
            done += 1
        else:
            it['summary_note'] = why or '요약 실패'
            failed += 1
    return done, failed
