"""발행 전 codex 검토 묶음 — 초안 글과 프롬프트, 그리고 근거를 꺼낼 공개 커밋.

묶음에는 **글과 프롬프트만** 담는다. 근거 데이터는 이미 main 에 커밋돼 있으므로(수집 커밋) 비공개 검토
워크플로가 `data_commit` 에서 직접 꺼낸다 — 발행 뒤 검토(`review_gate.review_one`)가 발행 커밋에서
꺼내는 것과 같은 방식이다. 그래서 작업 폴더의 근거가 그 커밋과 다르면(손댄 데이터) 묶지 않는다.
"""
import datetime as dt
import hashlib
import json
import os
import re
import secrets
import subprocess

import review_gate as gate

POST_PATH = {'us': 'posts/{date}.html', 'kr': 'kr/posts/{date}.html'}
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class BundleError(Exception):
    """묶을 수 없다 — 발행 전 검토 없이 발행으로 넘어간다(이유는 메시지)."""


def request_id(section, date):
    return f'{section}-{date}-{secrets.token_hex(6)}'


def _sha256(b):
    return hashlib.sha256(b).hexdigest()


def _git(root, *args):
    out = subprocess.run(['git', '-C', root, *args], capture_output=True, text=True)
    if out.returncode:
        raise BundleError(f'git {" ".join(args[:2])} 실패: {out.stderr.strip()[-200:]}')
    return out.stdout.strip()


NOTES_LINE = ('\n작성자가 읽은 리서치 노트: `research_notes.md` — 뉴스 원인·컨센서스·발언의 정본이다. 근거 데이터에 '
              '없는 원인·보도 설명은 여기서 찾고, 여기에도 없을 때만 「근거 없는 단정」으로 지적한다.\n')


# 발행 전에 **고치는** 문체 지적은 번역투와 용어뿐이다(2026-11-07 「번역투 고치는것만」, 2026-11-18 명료성으로 넓힘 —
# 설계 `../design-clarity-review.md`). 확신도 두 분류와 「논리·사실관계 의심」은 문체가 아니라 정확성 몫이다
# (`split.ROUTES`). 「문장 구조」「지시 대상 불명확」은 발행 전 편집 계약(STYLE_CLOSE §13 — 문장을 쪼개거나 뜻을
# 더하지 않는다)으로 풀 수 없어 **기록만** 한다. 반복·끊긴 흐름은 여전히 묻지 않는다. 발행 뒤 검토의 프롬프트는 그대로다.
PREPUB_KINDS = ('판단 세기 흐림', '원문에 없는 관계', '논리·사실관계 의심',
                '번역투', '용어', '문장 구조', '지시 대상 불명확')
RECORD_ONLY_MAX = 5   # `split.RECORD_MAX` 와 같다(시험이 본다) — 여기서 split 을 끌어오지 않는다
PREPUB_STYLE_PROMPT = """

**문체 지적(지적만 — 고친 문장을 쓰지 않는다).** 위 검토와 별도로, 이 글을 PM 이 읽는 데스크 문서로 본다.
기준은 하나다: **독자가 문장을 읽고 무엇이 발생했으며 작성자가 어떤 판단을 내렸는지 이해할 수 있는가.**
문장 표본은 `.claude/agents/STYLE_EXEMPLARS.md`(읽기만). 분류는 {kinds} 일곱뿐이고, 아래 세 묶음의 순서로 적는다.

① 내용이 의심되는 곳 — ①과 ②를 합쳐 **최대 {n}건**.
「판단 세기 흐림」은 판단·전망의 세기가 근거보다 강하거나 흐린 곳, 「원문에 없는 관계」는 근거가 말하지 않는
인과·대조를 문장이 만든 곳이다. 「논리·사실관계 의심」은 뜻을 알 수 없는 까닭이 표현이 아니라 내용인 곳이다 —
앞뒤 문장·표·근거 데이터와 방향이 어긋나 보인다(예: 「오늘의 장」에서 동일가중과 시가총액가중 지수의 차이를 푼
말이 근거 데이터의 차이 수치·지수 방향과 반대다). **표현 문제인지 내용 문제인지 헷갈리면 이 분류 하나로만 적는다.**

② 낱말만 바꾸면 풀리는 곳.
「번역투」는 한 문장 안에서 낱말·어순만 바꿔 고칠 수 있는 번역한 말의 흔적이다. 「용어」는 자료의 필드·판정
이름, 그 자리에서 지은 비유, 직역한 낱말이 설명 없이 쓰여 뜻을 알 수 없는 곳이다. 금융에서 통용되는 전문 용어는
고르지 않는다.

③ 낱말만으로는 풀리지 않는 곳 — 따로 **최대 {record}건**. 발행 전에는 고치지 않고 기록만 한다.
「문장 구조」는 한 문장에 판단·근거·조건이 얽혀 무엇이 일어났고 무엇을 판단했는지 가를 수 없는 곳,
「지시 대상 불명확」은 「이 차이」「그 흐름」처럼 가리키는 말의 대상이 글에 없는 곳이다. **대상이 무엇일지
짐작해 적지 않는다** — 「대상 불명확」이라고만 적는다.

**분류마다 하나씩 채우지 않는다** — 해당하는 곳이 없는 분류는 비우고, 한 분류에 해당하는 곳이 여럿이면 뜻이 가장
안 전해지는 것부터 여럿 적는다.
「용어」「문장 구조」「지시 대상 불명확」은 **인용 뒤 문제 설명의 맨 앞에**(인용 안이 아니다) 독자가 알 수 없는 것을
표식 하나로 적는다: `(가)` 무엇이 일어났는지 · `(나)` 작성자가 어떤 판단을 내렸는지 · `(다)` 그 말이 무엇을 가리키는지.
인용은 **글에 있는 글자 그대로**, 그 문장에만 있는 대목을 고른다. 고친 문장·대안 문장은 쓰지 않는다 —
고칠 방향 한 줄만. 문장을 지우거나 옮겨야 풀리는 반복·흐름 문제는 고르지 않는다.
답의 **맨 끝**에 `{head}` 한 줄을 쓰고, 그 아래 한 줄에 하나씩
`- [분류] 「문장 인용 40자 이내」 — 문제 / 고칠 방향` 꼴로 적는다(표식이 붙는 분류는
`- [용어] 「문장 인용」 — (가) 문제 / 고칠 방향`). 없으면 그 아래에 `없음` 한 줄.
이 부분은 사실 오류 목록과 섞지 않는다.
"""


def prompt(section, post_path, notes=False):
    """발행 뒤 검토와 같은 사실 검토 + 발행 전 문체 지적(확신도·번역투·명료성). 리서치 노트가 있으면 그 자리를 알린다."""
    body = gate.PROMPT.format(post=post_path, market=gate.MARKET_NAME.get(section, section),
                              datadir=gate.SNAPSHOT[section])
    if notes:
        body += NOTES_LINE
    return body + PREPUB_STYLE_PROMPT.format(
        n=gate.STYLE_FINDINGS_MAX, record=RECORD_ONLY_MAX, kinds='·'.join(f'「{k}」' for k in PREPUB_KINDS),
        head=gate.STYLE_FINDINGS_HEAD)


def build(root, section, date, html_path, out_dir, rid=None, notes_path=None):
    """→ manifest dict. `out_dir` 에 manifest.json·post.html·prompt.txt(·research_notes.md)를 쓴다.

    `notes_path` 는 작성자가 읽은 워크스페이스의 `research_notes.md` — 검토자가 같은 근거를 보게 한다(codex 구현 #2).
    """
    if section not in POST_PATH or not DATE.match(date or ''):
        raise BundleError(f'모르는 시장이나 날짜: {section} {date}')
    data_dir = gate.SNAPSHOT[section]
    commit = _git(root, 'rev-parse', 'HEAD')
    if _git(root, 'status', '--porcelain', '--', data_dir):
        raise BundleError(f'{data_dir} 가 HEAD 와 다르다 — 근거를 커밋에서 꺼낼 수 없다')
    post_path = POST_PATH[section].format(date=date)
    with open(html_path, encoding='utf-8') as fh:
        html = fh.read()
    os.makedirs(out_dir, exist_ok=True)
    post = os.path.join(out_dir, 'post.html')
    with open(post, 'w', encoding='utf-8') as fh:
        fh.write(html)
    gate._drop_contested(post)   # 발행 뒤 검토와 같게 — 쟁점 섹션은 별도 검증을 거친 생성물
    entries = [('post.html', open(post, 'rb').read(), False),
               ('prompt.txt', prompt(section, post_path, notes=bool(notes_path)).encode('utf-8'), True)]
    if notes_path:
        with open(notes_path, 'rb') as fh:
            entries.append(('research_notes.md', fh.read(), True))
    files = {}
    for name, data, write in entries:
        if write:
            with open(os.path.join(out_dir, name), 'wb') as fh:
                fh.write(data)
        files[name] = _sha256(data)
    with open(html_path, 'rb') as fh:
        source_sha = _sha256(fh.read())
    manifest = {'request_id': rid or request_id(section, date), 'section': section, 'date': date,
                'post_path': post_path, 'data_commit': commit, 'files': files,
                'source_html_sha256': source_sha,
                'created_at': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}
    with open(os.path.join(out_dir, 'manifest.json'), 'w', encoding='utf-8') as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    return manifest
