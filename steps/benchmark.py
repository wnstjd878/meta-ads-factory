"""
== 운영 맥락 ==
실행 시점: factory.py --benchmark (그림 뽑기 전 0단계)
입력: refs/ 폴더의 참고 광고 이미지(png/jpg/webp), OPENAI_API_KEY (.env)
출력: out/refs_analysis.json  (참고 광고별 4축7키 해부)
외부 의존: OpenAI vision (이미지 이해). 그림 생성과 같은 열쇠를 쓴다 = 열쇠 안 늘어남.
의도적 미구현:
  - 광고 라이브러리 자동 수집(Apify). 사람이 refs/ 에 직접 넣는다. 슈퍼애드엔 있지만
    강의는 열쇠를 안 늘리려고 파일 방식으로 간다. 재구현하려면 super-ad apify_benchmark.ts.
  - 성과 수치 기반 판정. 외부 참고 광고라 수치를 모른다. 구조만 뜯는다.
분석 스키마 출처: super-ad app/lib/gemini.ts VISION_PROMPT (옵시디언 벤치마킹 v2.2 4축7키).
재시작 정책: 한 장 실패하면 그 장만 건너뛰고 계속. 전부 실패하면 빈 결과.
마지막 점검: 2026-07-19

돈 주의: 이미지 이해는 그림 생성보다 훨씬 싸지만 장당 소액 요금이 난다.
"""

import base64
import json
import os
from pathlib import Path

import requests

MODEL = os.environ.get("VISION_MODEL", "gpt-4o")  # 이미지 이해용. 그림 생성 열쇠 재사용.
ENDPOINT = "https://api.openai.com/v1/chat/completions"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}

# 슈퍼애드 4축7키를 정적 참고 광고용으로 옮긴 것. 성과 수치·영상 필드는 뺐다.
VISION_PROMPT = """당신은 잘 되는 광고를 뜯어보는 크리에이티브 디렉터입니다.
주어지는 광고 이미지 한 장의 성공 구조를 분석해, 아래 JSON 만 출력하세요.
다른 말은 쓰지 마세요.

출력 JSON 스키마
{
  "worldview": "이 광고가 펼쳐지는 세계관 또는 상황. 등장인물·장소·시점·톤을 한 문장으로.",
  "target_persona": "광고가 노리는 페르소나. 연령·성별·라이프스타일·구매 동기를 1~2문장으로 구체적으로.",
  "problem": "광고가 다루는 페인 포인트. 보는 사람이 '나도 그래' 하고 공감할 구체 장면. 추상어 금지.",
  "solution": "광고가 제시하는 해결 방식. 무엇이 어떻게 다른지 1~2문장.",
  "copy_role": "메인 카피가 하는 역할. 1~2개 + 1줄 사유. [질문형/도발형/공감형/약속형/사회적증거형/손실회피형/호기심형/직설형/스토리형]",
  "copy_logic": {
    "main_throws": "메인 카피가 무엇을 던지는가. 1줄",
    "sub_answers": "서브 카피가 그 직후 의문에 어떻게 답하는가. 1줄. 없으면 '없음'"
  },
  "gaze_flow": "시선 시작점에서 이동 경로. 1줄.",
  "copy_visual_fit": "카피와 비주얼의 정합성. [일치/불일치/보완] 중 택1 + 사유 1줄",
  "appeal_type": "주요 소구 방식. 1~2개. [기능/감성/사회적증거/손실회피/호기심/권위/희소성] + 근거 1줄",
  "design_sensitivity": "타겟이 반응할 비주얼 세계관 1줄. 톤·무드·색감·레이아웃.",
  "target_language": ["타겟이 실제 쓰는 표현 3~5개"],
  "copy_on_media": { "main": "이미지에 박힌 메인 카피", "sub": "서브 카피", "cta": "버튼 문구" },
  "first_impression": "0.5초 안에 스크롤을 멈출 요소 한 가지.",
  "hook_pattern": "후킹 패턴. [질문형/충격수치/상식파괴/대비/공감유도] 등 + 1줄.",
  "why_it_works": "이 광고가 왜 먹히는지 한 문장. 구조 관점에서.",
  "transferable": "이 광고에서 내 광고로 이식할 수 있는 조각 1~2개. 문구가 아니라 구조."
}

벤치마크는 따라하기가 아닙니다. 문구를 베끼지 말고 성공 구조만 뽑으세요.
모든 값은 한국어. 마크다운 별표·줄표는 쓰지 마세요."""


def _key() -> str:
    k = os.environ.get("OPENAI_API_KEY")
    if not k:
        raise RuntimeError("OPENAI_API_KEY 가 없다. .env 에 넣어라.")
    return k


def run(refs_dir: Path, out_dir: Path) -> dict:
    if not refs_dir.exists():
        refs_dir.mkdir(parents=True, exist_ok=True)
    images = sorted(p for p in refs_dir.iterdir()
                    if p.is_file() and p.suffix.lower() in ALLOWED_EXT)

    results = []
    for p in images:
        try:
            analysis = _analyze(p)
        except Exception as e:
            print(f"  [건너뜀] {p.name}: {str(e)[:200]}")
            continue
        results.append({"file": p.name, "analysis": analysis})
        print(f"  [해부] {p.name}")

    data = {"refs": results}
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "refs_analysis.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return data


def _analyze(path: Path) -> dict:
    b64 = base64.b64encode(path.read_bytes()).decode()
    ext = path.suffix.lower().lstrip(".")
    mime = "jpeg" if ext == "jpg" else ext
    r = requests.post(
        ENDPOINT,
        headers={"Authorization": f"Bearer {_key()}"},
        json={
            "model": MODEL,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/{mime};base64,{b64}"}},
                ],
            }],
            "temperature": 0.2,
        },
        timeout=180,
    )
    if not r.ok:
        raise RuntimeError(f"이미지 이해 실패 {r.status_code}: {r.text[:300]}")

    text = r.json()["choices"][0]["message"]["content"]
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise RuntimeError(f"결과에서 JSON 을 못 찾았다: {text[:300]}")
    return json.loads(text[start : end + 1])
