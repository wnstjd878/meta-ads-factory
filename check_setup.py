"""
== 운영 맥락 ==
실행 시점: 사람이 한 번. check_upload.py 를 통과한 뒤. 촬영 리허설.
입력: .env, config.json, out/시험이미지해시.txt (check_upload.py 가 남긴 것)
출력: 광고 계정에 소재 1 + 캠페인 1 + 광고세트 1 + 광고 1 (전부 일시중지)
외부 의존: graph.facebook.com
의도적 미구현:
  - 만든 것 자동 삭제. 우리 코드는 삭제를 막는다(guards.py). 사람이 광고 관리자에서.
  - 그림 생성. 이미 올라간 시험 이미지를 쓴다. 요금 0원.
재시작 정책: 없음. 돌릴 때마다 새로 만들어진다. 확인 뒤 손으로 지운다.
마지막 점검: 2026-07-09

무엇을 보는가:
  1. 가드가 실제 호출에서도 예산을 막는가 (책상 위 시험이 아니라 진짜 호출)
  2. 111 구조가 만들어지는가
  3. 만든 뒤 다시 조회했을 때 정말 꺼져 있는가
"""

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import meta
from guards import GuardError
from steps import setup as step_setup

HASH_FILE = ROOT / "out" / "시험이미지해시.txt"


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load_test_hash() -> str:
    if not HASH_FILE.exists():
        print("시험 이미지가 없습니다. 먼저 이걸 돌리세요:")
        print("  python check_upload.py")
        sys.exit(1)
    return HASH_FILE.read_text(encoding="utf-8").strip()


def main() -> None:
    load_env()
    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))

    for key in ("page_id", "link_url", "pixel_id"):
        if not config.get(key):
            print(f"config.json 의 {key} 가 비어 있습니다. 채우고 다시 오세요.")
            sys.exit(1)

    print("\n[1] 가드가 진짜 호출에서도 막는가")
    try:
        meta.call("POST", meta.account_path("adsets"),
                  {"name": "이건 만들어지면 안 된다", "daily_budget": 10_000_000})
        print("  !! 실패: 예산 상한을 넘겼는데 통과했다. 가드가 뚫렸다.")
        sys.exit(1)
    except GuardError as e:
        print(f"  막힘: {str(e).splitlines()[0]}")

    try:
        meta.call("POST", meta.account_path("campaigns"),
                  {"name": "이것도 안 된다", "objective": "OUTCOME_TRAFFIC",
                   "buying_type": "AUCTION", "status": "ACTIVE"})
        print("  !! 실패: 켜진 캠페인이 통과했다.")
        sys.exit(1)
    except GuardError as e:
        print(f"  막힘: {str(e).splitlines()[0]}")

    print("\n[2] 111 구조 만들기 (요금 0원, 이미 올라간 시험 이미지 사용)")
    uploaded = [{
        "no": 99,
        "hook": "검증용 소재입니다. 켜지 마세요.",
        "sub": "이 캠페인은 리허설로 만든 것입니다.",
        "format": "검증용",
        "image_hash": load_test_hash(),
        "image_path": "(없음)",
    }]

    results = step_setup.run(uploaded, config, "검증")

    print("\n[3] 만든 것 (전부 꺼져 있음을 다시 조회해 확인함)")
    for r in results:
        print(f"  캠페인   {r['campaign_id']}")
        print(f"  광고세트 {r['adset_id']}")
        print(f"  광고     {r['ad_id']}")

    print("\n통과. 소재 공장 전체가 성립한다.")
    print("\n광고 관리자에서 [검증] 으로 시작하는 캠페인을 지우세요.")


if __name__ == "__main__":
    main()
