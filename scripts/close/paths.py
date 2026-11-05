"""중간산물 자리 — 마감 전 문장·판정·감사 기록은 레포 밖 `$CLOSE_DIR` 에만 쓴다(v4.1 G·v4.2 #7)."""

import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG = os.path.join(REPO, 'config', 'style_close.json')


class PathError(Exception):
    pass


def _inside(path, root):
    path, root = os.path.realpath(path), os.path.realpath(root)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def check_out(path, close_dir=None, repo=REPO):
    """쓰기 경로 검사. 레포 안이면, `close_dir`(또는 $CLOSE_DIR)이 있는데 그 밖이면 PathError."""
    close_dir = close_dir or os.environ.get('CLOSE_DIR')
    if _inside(path, repo):
        raise PathError('레포 안에는 쓰지 않는다: %s' % path)
    if close_dir:
        if _inside(close_dir, repo):
            raise PathError('CLOSE_DIR 이 레포 안이다: %s' % close_dir)
        if not _inside(path, close_dir):
            raise PathError('CLOSE_DIR 밖에는 쓰지 않는다: %s' % path)
    return path


def enabled(config=CONFIG):
    """킬 스위치 — 파일이 없거나 깨졌거나 값이 true 가 아니면 꺼짐."""
    try:
        with open(config, encoding='utf-8') as fh:
            return json.load(fh).get('enabled') is True
    except (OSError, ValueError, AttributeError):
        return False


def write_atomic(path, data):
    """`<path>.tmp` 에 쓰고 os.replace — 부분 쓰기가 남지 않는다."""
    tmp = path + '.tmp'
    mode = 'wb' if isinstance(data, bytes) else 'w'
    kw = {} if isinstance(data, bytes) else {'encoding': 'utf-8'}
    with open(tmp, mode, **kw) as fh:
        fh.write(data)
    os.replace(tmp, path)
