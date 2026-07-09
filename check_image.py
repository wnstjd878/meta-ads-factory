"""
== 운영 맥락 ==
실행 시점: 사람이 한 번. 그림 생성 열쇠를 넣은 뒤. 촬영 리허설.
입력: .env 의 OPENAI_API_KEY
출력: out/images/시험.png 한 장
외부 의존: 그림 생성 서비스 (한 장 요금)
의도적 미구현:
  - 여러 장 생성. 한 장으로 지시문이 먹히는지만 본다. 요금을 아낀다.
재시작 정책: 없음.
마지막 점검: 2026-07-09

무엇을 보는가:
  본편에서 표를 복사해 붙였더니 그림 도구가 신문 지면을 그렸다. 세로로 길고,
  본문 글자가 빽빽하고, 버튼이 잘렸다. 스킬에 넣은 지시문 규격이 그걸
  잡았는지 확인한다. 같은 카피, 다른 지시문.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

from steps import image as step_image

# 스킬 /소재생성 이 만들어내는 형태의 지시문. 본편에서 문제가 됐던 그 카피.
PROMPT = """정사각형 1:1 광고 이미지. 모바일에서 볼 것.

화면 위 절반: "본사 말만 믿었다가 / 2년째 원금도 못 뽑았습니다"
두 줄로, 아주 큰 글씨. 화면 폭을 꽉 채운다.
그 아래 한 줄 작게: "상권분석부터 다시 시작하는 공간사업"
화면 아래: 버튼 하나. 안에 "무료 상권진단 신청". 잘리지 않게 여백을 둔다.

사진: 불 꺼진 가게 안에서 고개 숙인 40대 사장. 어두운 톤.
색: 배경 짙은 남색, 강조색 빨강 한 가지만.

지킬 것:
- 글자는 위 세 덩어리가 전부다. 기사 본문 같은 잔글씨를 넣지 마라.
- 한글 맞춤법 정확히. 글자가 깨지면 다시 그려라.
- 실제 브랜드 로고, 실존 인물 얼굴을 넣지 마라.
- 날짜, 기자 이름, 신문사 이름 같은 가짜 정보를 넣지 마라.
"""


def load_env() -> None:
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_env()
    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY 가 비어 있습니다.")
        sys.exit(1)

    print(f"그림 한 장을 뽑습니다. 모델 {step_image.MODEL}, 크기 {step_image.SIZE}")
    print("요금이 나갑니다.\n")

    try:
        png = step_image._generate(PROMPT)
    except Exception as e:
        print(f"실패: {e}")
        print("\n조직 인증을 요구하면 image.py 의 MODEL 을 'dall-e-3' 로 바꿔 다시 시도하세요.")
        sys.exit(1)

    out = ROOT / "out" / "images"
    out.mkdir(parents=True, exist_ok=True)
    path = out / "시험.png"
    path.write_bytes(png)

    print(f"만들어졌습니다: {path}")
    print(f"크기 {len(png):,} bytes")
    print("\n볼 것 네 가지:")
    print("  1. 정사각형인가 (세로로 길면 피드에서 잘림)")
    print("  2. 글자 덩어리가 셋뿐인가 (후킹, 서브, 버튼)")
    print("  3. 기사 본문 같은 잔글씨가 없는가")
    print("  4. 가짜 날짜·기자명·신문사명이 없는가")


if __name__ == "__main__":
    main()
