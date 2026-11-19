#!/usr/bin/env bash
# 차트 라벨용 CJK 글꼴(fonts-noto-cjk)을 깐다 — 수집 워크플로 공용.
#
# 왜 있는가 — apt 미러의 이름 풀이가 가끔 끊긴다. 2026-11-11 KR 수집 15:53·16:29 UTC 두 실행이
# 이 단계에서 죽었다(`Temporary failure resolving 'azure.archive.ubuntu.com'`, 실행 43052915321·
# 43058770735). 그래서 apt 를 몇 번 다시 해 본다(기본 3번, 30·60초 간격).
# 한계 — 몇십 분씩 이어지는 장애는 이 재시도로 넘기지 못한다. 그때는 다음 예약 실행이 다시 시도한다.
# 받은 .deb 를 actions/cache 로 보존하는 안은 뺐다: 설치는 실행당 8초쯤이고, 캐시 열쇠·묵은 항목·
# 우분투 판 격리를 다루는 복잡함이 얻는 것보다 컸다(plans/2026-11-19-ci-tests.md).
# 끝내 못 깔면 실패로 끝낸다 — 글꼴 없는 차트는 한글이 네모로 그려져 발행된다(막는 범위는 예전과 같다).
#
# 쓰는 법: bash scripts/ci/install_cjk_font.sh
set -uo pipefail

tries="${FONT_RETRIES:-3}"
sleep_unit="${FONT_RETRY_SLEEP:-30}"
read -r -a apt_get <<< "${APT_GET:-sudo apt-get}"   # 빈칸으로 나눈다 — 시험은 PATH 의 가짜 apt-get 을 쓴다
pkg=fonts-noto-cjk

opts=(-o Acquire::Retries=3)
for i in $(seq 1 "$tries"); do
  if "${apt_get[@]}" "${opts[@]}" update -qq && "${apt_get[@]}" "${opts[@]}" install -y -qq "$pkg"; then
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
