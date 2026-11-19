"""수집 워크플로의 글꼴 설치 — apt 미러 이름 풀이가 잠깐 끊겨도(2026-11-11 KR 두 실행) 다시 해 본다."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'ci' / 'install_cjk_font.sh'

# 가짜 apt-get: FAIL_LEFT 파일의 수만큼 실패하고, 그 뒤로는 성공한다(FAIL_ONLY 를 주면 그 하위 명령만 실패)
FAKE_APT = r'''#!/usr/bin/env bash
echo "apt $*" >> "$LOG"
left=$(cat "$FAIL_LEFT")
if [ -n "${FAIL_ONLY:-}" ]; then case " $* " in *" $FAIL_ONLY "*) ;; *) left=0;; esac; fi
if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$FAIL_LEFT"; echo "Temporary failure resolving" >&2; exit 100; fi
exit 0
'''


FAKE_SLEEP = '#!/usr/bin/env bash\necho "sleep $*" >> "$LOG"\n'


def _run(tmp_path, fails=0, **env):
    # 가짜 명령은 PATH 맨 앞 폴더에 둔다 — 스크립트의 실제 기다림(30·60초)도 가짜 sleep 이 받아 적는다.
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for name, body in (('apt-get', FAKE_APT), ('sleep', FAKE_SLEEP)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    (tmp_path / 'fail_left').write_text(str(fails))
    base = {k: v for k, v in os.environ.items() if k not in ('FONT_RETRIES', 'FONT_RETRY_SLEEP', 'FAIL_ONLY')}
    e = dict(base, PATH=f"{bin_}{os.pathsep}{base['PATH']}", APT_GET='apt-get', LOG=str(tmp_path / 'log'),
             FAIL_LEFT=str(tmp_path / 'fail_left'), **env)
    r = subprocess.run(['bash', str(SCRIPT)], env=e, capture_output=True, text=True)
    log = (tmp_path / 'log').read_text().splitlines() if (tmp_path / 'log').exists() else []
    return r, [x for x in log if x.startswith('apt ')], [x for x in log if x.startswith('sleep ')]


def _is(x, verb):
    return f' {verb} ' in f' {x} '


def _order(tmp_path):
    """apt 호출과 기다림이 일어난 순서 — 기다림이 시도 사이에 있는지 본다."""
    out = []
    for x in (tmp_path / 'log').read_text().splitlines():
        out.append(x if x.startswith('sleep ') else next(v for v in ('update', 'install') if _is(x, v)))
    return out


def test_healthy_mirror_installs_on_the_first_try(tmp_path):
    r, log, naps = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    assert len(log) == 2 and _is(log[0], 'update')
    assert _is(log[1], 'install') and log[1].endswith(' fonts-noto-cjk')
    assert '1번째' in r.stdout and '::warning::' not in r.stdout and naps == []


def test_dns_failure_is_retried(tmp_path):
    r, log, naps = _run(tmp_path, fails=2)
    assert r.returncode == 0, r.stderr
    assert '2번째 실패' in r.stdout and '3번째' in r.stdout
    assert sum(_is(x, 'update') for x in log) == 3 and sum(_is(x, 'install') for x in log) == 1
    assert _order(tmp_path) == ['update', 'sleep 30', 'update', 'sleep 60', 'update', 'install']


def test_install_failure_after_update_starts_again_from_update(tmp_path):
    r, log, naps = _run(tmp_path, fails=1, FAIL_ONLY='install')
    assert r.returncode == 0, r.stderr
    assert _order(tmp_path) == ['update', 'install', 'sleep 30', 'update', 'install']


def test_gives_up_after_the_last_try(tmp_path):
    r, log, naps = _run(tmp_path, fails=99)
    assert r.returncode == 1
    assert sum(_is(x, 'update') for x in log) == 3      # 기본 3번
    assert not any(_is(x, 'install') for x in log)
    assert '::error::' in r.stdout
    assert _order(tmp_path) == ['update', 'sleep 30', 'update', 'sleep 60', 'update']   # 마지막 실패 뒤에는 기다리지 않는다


def test_retry_count_is_configurable(tmp_path):
    r, log, naps = _run(tmp_path, fails=99, FONT_RETRIES='2', FONT_RETRY_SLEEP='5')
    assert r.returncode == 1 and sum(_is(x, 'update') for x in log) == 2 and naps == ['sleep 5']
