"""수집 워크플로의 글꼴 설치 — apt 미러 이름 풀이가 끊겨도(2026-11-11 KR 두 실행) 캐시로 깔고, 없으면 다시 해 본다."""
import os
import subprocess
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / 'ci' / 'install_cjk_font.sh'

# 가짜 apt-get: FAIL_LEFT 파일의 수만큼 실패하고, 그 뒤 install 에서 Dir::Cache::archives 폴더에 .deb 를 남긴다
FAKE_APT = r'''#!/usr/bin/env bash
echo "apt $*" >> "$LOG"
left=$(cat "$FAIL_LEFT")
if [ "$left" -gt 0 ]; then echo $((left - 1)) > "$FAIL_LEFT"; echo "Temporary failure resolving" >&2; exit 100; fi
for a in "$@"; do case "$a" in Dir::Cache::archives=*) arch="${a#Dir::Cache::archives=}";; esac; done
touch "$arch/lock"   # 진짜 apt 처럼 root 소유 lock 을 남긴다
case " $* " in *" install "*) touch "$arch/fonts-noto-cjk_20230817_all.deb";; esac
exit 0
'''
FAKE_DPKG = '#!/usr/bin/env bash\necho "dpkg $*" >> "$LOG"\nexit "${DPKG_EXIT:-0}"\n'


def _world(tmp_path, fails=0):
    bin_ = tmp_path / 'bin'
    bin_.mkdir()
    for name, body in (('apt-get', FAKE_APT), ('dpkg', FAKE_DPKG)):
        (bin_ / name).write_text(body)
        (bin_ / name).chmod(0o755)
    (tmp_path / 'fail_left').write_text(str(fails))
    return tmp_path / 'cache'


def _run(tmp_path, cache, **env):
    e = dict(os.environ, APT_GET=str(tmp_path / 'bin' / 'apt-get'), DPKG=str(tmp_path / 'bin' / 'dpkg'),
             LOG=str(tmp_path / 'log'), FAIL_LEFT=str(tmp_path / 'fail_left'), FONT_RETRY_SLEEP='0', TMPDIR=str(tmp_path), **env)
    r = subprocess.run(['bash', str(SCRIPT), str(cache)], env=e, capture_output=True, text=True)
    log = (tmp_path / 'log').read_text().splitlines() if (tmp_path / 'log').exists() else []
    return r, log


def test_first_run_installs_with_apt_and_leaves_deb_in_cache(tmp_path):
    cache = _world(tmp_path)
    r, log = _run(tmp_path, cache)
    assert r.returncode == 0, r.stderr
    assert any(x.startswith('apt ') and ' install ' in f' {x} ' and 'fonts-noto-cjk' in x for x in log)
    assert sorted(p.name for p in cache.iterdir()) == ['fonts-noto-cjk_20230817_all.deb']   # lock·partial 은 캐시 밖


def test_cached_deb_installs_without_network(tmp_path):
    cache = _world(tmp_path, fails=99)          # 네트워크가 죽어 있어도
    cache.mkdir()
    (cache / 'fonts-noto-cjk_20230817_all.deb').write_text('x')
    r, log = _run(tmp_path, cache)
    assert r.returncode == 0, r.stderr
    assert log == [f'dpkg -i {cache}/fonts-noto-cjk_20230817_all.deb']


def test_dns_failure_is_retried(tmp_path):
    cache = _world(tmp_path, fails=2)
    r, log = _run(tmp_path, cache)
    assert r.returncode == 0, r.stderr
    assert '2번째 실패' in r.stdout and '3번째' in r.stdout


def test_gives_up_after_the_last_try(tmp_path):
    cache = _world(tmp_path, fails=99)
    r, log = _run(tmp_path, cache)
    assert r.returncode == 1
    assert sum(' update ' in f' {x} ' for x in log) == 3      # 기본 3번
    assert '::error::' in r.stdout


def test_broken_cache_falls_back_to_apt(tmp_path):
    cache = _world(tmp_path)
    cache.mkdir()
    (cache / 'fonts-noto-cjk_old_all.deb').write_text('x')
    r, log = _run(tmp_path, cache, DPKG_EXIT='1')
    assert r.returncode == 0, r.stderr
    assert log[0].startswith('dpkg -i') and any(' install ' in f' {x} ' for x in log[1:])
    assert not (cache / 'fonts-noto-cjk_old_all.deb').exists()
