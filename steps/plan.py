"""
== 운영 맥락 ==
실행 시점: factory.py 1단계
입력: 상품 설명, BEP, 타겟 (config.json)
출력: out/plan.json  (카피 + 이미지 지시문 N개)
외부 의존: claude 실행 파일 (구독 로그인). ~/.claude/skills/meta-ads-ops/SKILL.md
의도적 미구현:
  - 그림 생성 서비스로 카피를 만들지 않는다. 스킬 규칙이 클로드에 있다.
  - 카피 20개 전부 지시문화하지 않는다. 스킬대로 상위 6개만.
재시작 정책: 실패 시 멈춤. 결과가 비면 다음 단계로 넘기지 않는다.
마지막 점검: 2026-07-09
"""

import json
import subprocess
from pathlib import Path

PROMPT = """메타 광고 스킬(meta-ads-ops)의 /소재생성 규칙을 그대로 따라라.

상품/서비스: {product}
가격 또는 계약단가: {price}
구매자: {buyer}
사용자: {user}
손익분기 결과당 비용(BEP): {bep}

스킬 규칙대로 커뮤니티에서 고객 언어를 수집하고, 카피 20개를 만들고,
5항목 체크리스트로 검수한 뒤, 그중 가장 좋은 {n}개를 골라 이미지 지시문을
만들어라.

통계 숫자는 수집한 글에 실제로 있던 것만 쓴다. 없으면 숫자를 빼라.

마지막에 아래 형태의 JSON 하나만 출력해라. 설명 문장을 붙이지 마라.

**copies 배열에는 이미지 지시문을 만든 {n}개만 넣어라.**
지시문 없는 나머지 카피는 배열에 넣지 마라. 다섯 항목이 모두 채워져야 한다.

{{
  "copies": [
    {{
      "no": 1,
      "hook": "후킹 한 줄",
      "sub": "서브 한 줄",
      "cta": "버튼에 들어갈 문구",
      "format": "감성 상황 사진형",
      "image_prompt": "그림 생성 도구에 그대로 붙여넣을 지시문 전문. 줄바꿈 포함."
    }}
  ]
}}
"""


def run(config: dict, out_dir: Path, n_images: int = 6) -> dict:
    prompt = PROMPT.format(
        product=config["product"],
        price=config["price"],
        buyer=config["buyer"],
        user=config["user"],
        bep=config["bep"],
        n=n_images,
    )

    proc = subprocess.run(
        ["claude", "-p", prompt, "--output-format", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=1800,
    )

    # 원본을 먼저 남긴다. 형식이 어긋나 멈췄을 때 무엇이 왔는지 봐야 한다.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "plan_raw.txt").write_text(proc.stdout or "(빈 출력)", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"소재 기획 실패\n{proc.stderr[:800]}")

    plan = _extract_json(proc.stdout)
    raw_copies = plan.get("copies", [])
    if not raw_copies:
        raise RuntimeError("카피가 하나도 안 나왔다. out/plan_raw.txt 를 볼 것.")

    # 지시문이 붙은 것만 쓴다. 카피만 있고 지시문이 없는 항목은 그림을 못 만든다.
    copies = [c for c in raw_copies if c.get("image_prompt")]
    dropped = len(raw_copies) - len(copies)
    if dropped:
        print(f"      지시문 없는 카피 {dropped}개는 건너뜁니다.")

    if not copies:
        raise RuntimeError(
            f"카피 {len(raw_copies)}개가 왔지만 이미지 지시문이 하나도 없다.\n"
            f"out/plan_raw.txt 를 볼 것."
        )

    copies = copies[:n_images]
    plan = {"copies": copies}

    path = out_dir / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan


def _extract_json(stdout: str) -> dict:
    """claude -p --output-format json 은 바깥을 한 번 감싼다.

    바깥 껍질을 벗기고, 그 안 본문에서 다시 우리 JSON 을 찾는다.
    """
    try:
        outer = json.loads(stdout)
        text = outer.get("result", stdout) if isinstance(outer, dict) else stdout
    except json.JSONDecodeError:
        text = stdout

    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"결과에서 JSON 을 못 찾았다:\n{text[:500]}")
    return json.loads(text[start : end + 1])
