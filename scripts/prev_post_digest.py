#!/usr/bin/env python3
"""직전 발행본 요약 — 작성자·수집 담당이 글 전체 대신 이 파일을 읽는다(`common/prev_post.py`).

  prev_post_digest.py --market us|kr --date D --repo <레포 클론> --out <workspace>/prev_post.html

마지막 줄 `prev_post: ok|full|bootstrap <path> <date> <commit> (N B)` exit 0, `prev_post: error …` exit 2.
error 는 bootstrap 이 아니다 — 파일을 남기지 않는다.
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from common import prev_post  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument('--market', required=True, choices=('us', 'kr'))
    p.add_argument('--date', required=True)
    p.add_argument('--repo', default='.')
    p.add_argument('--out', required=True)
    a = p.parse_args(argv)
    code, line = prev_post.run(a.market, a.date, a.repo, a.out)
    print(line)
    return code


if __name__ == '__main__':
    sys.exit(main())
