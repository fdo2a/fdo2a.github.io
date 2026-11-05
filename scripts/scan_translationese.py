#!/usr/bin/env python3
"""번역투 자리를 보여 준다 — 작성자 마감 점검(2026-10-22 사용자 지시).

  python3 scripts/scan_translationese.py <조립한 html>

걸린 자리마다 그 문장과 고칠 꼴의 귀띔을 찍는다. **글은 바꾸지 않는다** — 작성자가 자기 초안
(`.body.html`)에서 그 문장을 직접 고치고 다시 조립한다. 마지막 줄은 늘 `translationese: flagged N`
이고 종료 코드는 늘 0 이다 — 게이트가 아니다(문체 경고는 발행을 막지 않는다).
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from us.prose_swap import _MARK_RE, _eligible, _mask  # noqa: E402
from us.translationese import flag  # noqa: E402

_SENT_END = re.compile(r'(?<=[.!?])\s+')

GUIDE = """\
번역투 점검 — 걸린 문장만, 뜻을 그대로 두고 고친다. 귀띔은 힌트다. 맞는 꼴이 없거나 고치면
수식·시점·대상 관계가 흔들리면 그대로 둔다. 숫자·이름·방향·부정·인과·단서는 건드리지 않는다.
  「환율에 대한 시장의 우려」→「환율 시장의 우려」(×, 시장이 아니라 환율 시장이 걱정) → 「시장의 환율 우려」
  「앞으로의 감세 계획을 논의」→「앞으로 감세 계획을 논의」(×, 시점이 논의로 옮겨 감)
  「은행을 통해 공급」→「은행으로 공급」(×, 경로가 대상이 됨)
  「강세에 대한 판단은 미룬다」→「강세 판단은 미룬다」(○)
"""


def _sentence(text, start, end):
    a = max([m.end() for m in _SENT_END.finditer(text, 0, start)] or [0])
    m = _SENT_END.search(text, end)
    b = m.start() if m else len(text)
    return ' '.join(_MARK_RE.sub('', text[a:b]).split())


def report(html):
    """→ (찍을 글, 걸린 자리 수)."""
    flagged = flag(html)
    n = sum(len(v) for v in flagged.values())
    if not n:
        return '', 0
    masked = {pid: _mask(m.group(2))[0] for pid, m in _eligible(html)}
    out = [GUIDE]
    for pid, hits in flagged.items():
        text = masked[pid]
        for h in hits:
            out.append('- 「%s」 %s' % (' '.join(h.text.split()), _sentence(text, h.start, h.end)))
            for label, repl in h.options:
                swapped = text[:h.start] + repl + text[h.end:]
                out.append('    귀띔(%s): %s' % (label, _sentence(swapped, h.start, h.start + len(repl))))
    return '\n'.join(out), n


def _say(line):
    """출력이 깨져도(ASCII 터미널 등) 점검이 작성을 멈추지 않는다(codex 구현 검토 #3)."""
    try:
        print(line, flush=True)
    except Exception:
        try:
            enc = getattr(sys.stdout, 'encoding', None) or 'ascii'
            sys.stdout.write(line.encode(enc, 'backslashreplace').decode(enc) + '\n')
            sys.stdout.flush()
        except Exception:
            # 닫힌 파이프 — 남은 버퍼를 종료 때 다시 flush 하다 120 으로 끝나지 않게 stdout 을 버린다(codex 재검토 #3).
            try:
                devnull = os.open(os.devnull, os.O_WRONLY)
                os.dup2(devnull, sys.stdout.fileno())
            except Exception:
                pass


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 1:
        _say(__doc__)
        _say('translationese: flagged 0 (사용법)')
        return 0
    try:
        with open(argv[0], encoding='utf-8') as fh:
            text, n = report(fh.read())
    except Exception as exc:  # 점검의 실패가 작성을 멈추지 않는다
        _say('translationese: flagged 0 (점검 실패: %s)' % exc)
        return 0
    if text:
        _say(text)
    _say('translationese: flagged %d' % n)
    return 0


if __name__ == '__main__':
    sys.exit(main())
