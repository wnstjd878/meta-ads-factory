"""
== 운영 맥락 ==
실행 시점: factory.py 2단계
입력: out/plan.json 의 image_prompt, OPENAI_API_KEY (.env)
출력: out/images/*.png
외부 의존: 콘텐츠 생성 서비스 (장당 요금 발생)
의도적 미구현:
  - 브라우저 조종(로그인된 ChatGPT 화면 누르기) 방식. 무료지만 잘 깨져서
    직접 호출로 갔다. 다시 만들려면 강의 대본 B-1 참고. 재구현 금지.
재시작 정책: 한 장 실패하면 그 장만 건너뛰고 계속. 전부 실패하면 멈춤.
마지막 점검: 2026-07-09

돈 주의: 이 단계는 콘텐츠 한 장마다 요금이 나간다. MAX_IMAGES 로 상한을 건다.
"""

import base64
import os
from pathlib import Path

import requests

MAX_IMAGES = 8  # 한 번에 이 장수를 넘겨 만들지 않는다. 요금 폭주 방지.
ENDPOINT = "https://api.openai.com/v1/images/generations"
MODEL = "gpt-image-2"   # 2026-07 기준 최신. 한글 오타가 확 줄었다.
#       모델 목록 확인: GET https://api.openai.com/v1/models
#       구형(gpt-image-1)은 손글씨 서브 문구에 오타를 냈다.
SIZE = "1024x1024"  # 정사각형. 피드에서 안 잘린다.


def _key() -> str:
    k = os.environ.get("OPENAI_API_KEY")
    if not k:
        raise RuntimeError("OPENAI_API_KEY 가 없다. .env 에 넣어라.")
    return k


def run(plan: dict, out_dir: Path) -> list[dict]:
    copies = plan["copies"]
    if len(copies) > MAX_IMAGES:
        raise RuntimeError(
            f"콘텐츠 {len(copies)}장을 만들려 한다. 상한 {MAX_IMAGES}장.\n"
            f"요금이 나가는 단계다. 늘리려면 image.py MAX_IMAGES 를 고칠 것."
        )

    img_dir = out_dir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    made, failed = [], []
    for c in copies:
        no = c["no"]
        try:
            png = _generate(c["image_prompt"])
        except Exception as e:
            failed.append((no, str(e)[:200]))
            continue

        path = img_dir / f"{no:02d}.png"
        path.write_bytes(png)
        made.append({**c, "image_path": str(path)})

    if not made:
        raise RuntimeError(f"콘텐츠를 한 장도 못 만들었다. 첫 실패: {failed[:1]}")

    for no, why in failed:
        print(f"  [건너뜀] {no}번 콘텐츠 실패: {why}")

    return made


def _generate(prompt: str) -> bytes:
    r = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {_key()}"},
        json={"model": MODEL, "prompt": prompt, "size": SIZE, "n": 1},
        timeout=300,
    )
    if not r.ok:
        raise RuntimeError(f"콘텐츠 생성 실패 {r.status_code}: {r.text[:300]}")

    data = r.json()["data"][0]
    if "b64_json" in data:
        return base64.b64decode(data["b64_json"])
    return requests.get(data["url"], timeout=120).content
