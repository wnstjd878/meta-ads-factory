"""
== 운영 맥락 ==
실행 시점: 사람이 한 번. 토큰을 새로 넣었을 때, 촬영 직전 리허설 때.
입력: .env
출력: 화면에 통과/실패. 시험 이미지 한 장이 광고 계정에 올라감.
외부 의존: graph.facebook.com
의도적 미구현:
  - 올린 시험 이미지 자동 삭제. 이미지는 지출도 노출도 없어 그냥 둬도 된다.
  - 캠페인 생성. 여기서는 이미지 올리기만 본다.
재시작 정책: 없음. 여러 번 돌려도 같은 이미지는 해시가 같아 중복이 안 생긴다.
마지막 점검: 2026-07-09

왜 있나:
  소재 공장 전체를 돌리기 전에, 이미지 올리기만 따로 확인한다.
  이게 안 되면 나머지가 전부 무의미하다. 그림 생성 요금도 안 쓰고,
  캠페인도 안 만들고, 딱 이 한 가지만 본다.

토큰은 절대 화면에 찍지 않는다.
"""

import os
import struct
import sys
import zlib
from pathlib import Path

import requests

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def make_png(size: int = 600, rgb: tuple = (230, 57, 70)) -> bytes:
    """단색 정사각형 PNG 를 만든다. 외부 라이브러리 없이."""
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def step(n: int, title: str) -> None:
    print(f"\n[{n}] {title}")


def main() -> None:
    load_env()
    token = os.environ.get("META_ADS_TOKEN", "")
    if not token:
        print("META_ADS_TOKEN 이 비어 있습니다. .env 를 확인하세요.")
        sys.exit(1)

    ver = os.environ.get("META_API_VERSION", "v21.0")
    base = f"https://graph.facebook.com/{ver}"
    acc = os.environ["META_AD_ACCOUNT_ID"]

    # 1. 토큰이 살아 있는지, 권한이 맞는지
    step(1, "토큰 권한 확인")
    r = requests.get(f"{base}/debug_token",
                     params={"input_token": token, "access_token": token}, timeout=30)
    if not r.ok:
        print(f"  실패: 토큰이 거부됐습니다 ({r.status_code}). 다시 발급하세요.")
        sys.exit(1)

    d = r.json().get("data", {})
    scopes = set(d.get("scopes", []))
    print(f"  유효: {d.get('is_valid')}")
    print(f"  유형: {d.get('type')}")
    exp = d.get("expires_at", 0)
    print(f"  만료: {'없음 (영구)' if exp == 0 else exp}")
    print(f"  권한: {', '.join(sorted(scopes)) or '(없음)'}")

    need = {"ads_management", "ads_read"}
    missing = need - scopes
    if missing:
        print(f"\n  실패: 권한이 모자랍니다 -> {', '.join(missing)}")
        print("  business.facebook.com 에서 그 권한을 체크해 새 토큰을 만드세요.")
        sys.exit(1)

    # 2. 광고 계정에 닿는지
    step(2, "광고 계정 접근")
    r = requests.get(f"{base}/act_{acc}",
                     params={"fields": "name,currency,account_status", "access_token": token},
                     timeout=30)
    if not r.ok:
        print(f"  실패: {r.text.replace(token, '<가림>')[:300]}")
        print("  시스템 사용자에게 이 계정의 '전체 관리' 권한을 줬는지 확인하세요.")
        sys.exit(1)
    a = r.json()
    print(f"  {a.get('name')} / {a.get('currency')} / 상태 {a.get('account_status')}")

    # 3. 급소. 이미지를 올려 해시를 받는다.
    step(3, "이미지 올리기 (오늘의 급소)")
    png = make_png()
    print(f"  시험 이미지 {len(png):,} bytes 를 만들었습니다.")

    r = requests.post(
        f"{base}/act_{acc}/adimages",
        data={"access_token": token},
        files={"filename": ("factory_test.png", png, "image/png")},
        timeout=120,
    )
    if not r.ok:
        print(f"\n  실패: {r.text.replace(token, '<가림>')[:500]}")
        print("\n  여기서 막히면 소재 공장이 성립하지 않습니다.")
        sys.exit(1)

    images = r.json().get("images", {})
    if not images:
        print(f"  실패: 응답에 이미지가 없습니다. {r.json()}")
        sys.exit(1)

    for name, info in images.items():
        print(f"  올라감: {name}")
        print(f"  이미지 해시: {info['hash']}")
        # 다음 확인(check_setup.py)이 이어받아 쓴다.
        hash_file = ROOT / "out" / "시험이미지해시.txt"
        hash_file.parent.mkdir(parents=True, exist_ok=True)
        hash_file.write_text(info["hash"], encoding="utf-8")

    print("\n통과. 이미지 올리기가 됩니다. 소재 공장을 돌려도 됩니다.")
    print("올린 시험 이미지는 지출도 노출도 없습니다. 광고 관리자 > 자산 > 이미지 에서 볼 수 있습니다.")
    print("\n다음: python check_setup.py")


if __name__ == "__main__":
    main()
