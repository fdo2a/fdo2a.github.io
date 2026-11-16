"""시험이 쓰는 실물 목록 — 레포의 대상 글 전부(git 이 추적하는 html)."""
import functools
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET_DIRS = ("posts", "news", "weekly", "japan/daily", "japan/posts")


@functools.lru_cache(maxsize=None)
def target_paths():
    out = subprocess.run(["git", "ls-files", *TARGET_DIRS], cwd=ROOT,
                         capture_output=True, text=True, check=True).stdout
    return tuple(p for p in out.split() if p.endswith(".html"))


@functools.lru_cache(maxsize=None)
def read(path):
    """바이트 그대로 — 줄바꿈 변환 없이 읽는다."""
    return (ROOT / path).read_bytes().decode("utf-8")
