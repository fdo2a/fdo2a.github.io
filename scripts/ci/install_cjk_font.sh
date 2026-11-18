#!/usr/bin/env bash
# 차트 라벨용 CJK 글꼴(fonts-noto-cjk)을 깐다 — 수집 워크플로 공용.
#
# 왜 있는가 — apt 미러의 이름 풀이가 몇십 분씩 끊긴다. 2026-11-11 KR 수집 15:53·16:29 UTC 두 실행이
# 모두 이 단계에서 죽었다(`Temporary failure resolving 'azure.archive.ubuntu.com'`, 실행 43052915321·
# 43058770735). 그래서 (1) 받은 .deb 를 캐시 폴더에 남겨 두고(워크플로의 actions/cache 가 실행 사이에
# 보존한다) 다음부터는 네트워크 없이 깔고, (2) 캐시가 없으면 apt 를 몇 번 다시 해 본다.
# 끝내 못 깔면 실패로 끝낸다 — 글꼴 없는 차트는 한글이 네모로 그려져 발행된다(막는 범위는 예전과 같다).
#
# 쓰는 법: bash scripts/ci/install_cjk_font.sh <캐시 폴더>
set -uo pipefail

dir="${1:?캐시 폴더가 필요하다}"
tries="${FONT_RETRIES:-3}"
sleep_unit="${FONT_RETRY_SLEEP:-30}"
read -r -a apt_get <<< "${APT_GET:-sudo apt-get}"   # 시험이 가짜 명령으로 바꿔 끼운다
read -r -a dpkg <<< "${DPKG:-sudo dpkg}"
pkg=fonts-noto-cjk

mkdir -p "$dir"

if compgen -G "$dir/${pkg}_*.deb" > /dev/null; then
  if "${dpkg[@]}" -i "$dir"/*.deb; then
    echo "글꼴: 캐시에서 깔았다"
    exit 0
  fi
  echo "::warning::캐시한 글꼴 패키지를 깔지 못했다 — 지우고 apt 로 다시 받는다"
  rm -f "$dir"/*.deb
fi

# apt 의 보관 폴더를 따로 둔다 — root 가 만드는 lock·partial 은 캐시가 읽지 못해 저장이 실패한다.
# 깐 뒤 .deb 만 캐시 폴더로 옮겨 적는다(이 사용자 소유).
stage="$(mktemp -d)"
mkdir -p "$stage/partial"
opts=(-o Acquire::Retries=3 -o "Dir::Cache::archives=$stage")
for i in $(seq 1 "$tries"); do
  if "${apt_get[@]}" "${opts[@]}" update -qq && "${apt_get[@]}" "${opts[@]}" install -y -qq "$pkg"; then
    cp "$stage"/*.deb "$dir"/ 2> /dev/null || echo "::warning::받은 글꼴 패키지가 없어 캐시를 채우지 못했다"
    echo "글꼴: apt 로 깔았다(${i}번째)"
    exit 0
  fi
  if [ "$i" -lt "$tries" ]; then
    echo "::warning::글꼴 설치 ${i}번째 실패 — $((sleep_unit * i))초 뒤 다시"
    sleep $((sleep_unit * i))
  fi
done
echo "::error::글꼴 설치 ${tries}번 모두 실패 — apt 미러 연결을 확인한다"
exit 1
