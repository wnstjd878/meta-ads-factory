"""
== 운영 맥락 ==
실행 시점: factory.py 1단계(기획) 와 2단계(지시문) 에서 나눠 불린다.
입력: prompts/기획_*.md (전자책 PART 7 원문), config.json, out/refs_analysis.json
출력: out/plan.json  (카피 18종) / out/기획안.html (사람이 보는 표)
      고른 번호만 image_prompt 를 채워 다시 out/plan.json
외부 의존: claude 실행 파일 (구독 로그인), skill/SKILL.md
의도적 미구현:
  - prompts/*.md 원문을 코드가 고치지 않는다. 실전에서 성과가 검증된 자산이라
    한 글자도 안 건드린다. 입력값과 출력 형식 지시는 원문 "뒤에 붙인다".
    원문을 손보고 싶으면 그 md 파일을 사람이 직접 고칠 것.
  - 카피 18종 전부를 지시문으로 만들지 않는다. 사람이 고른 것만 만든다.
    (안 고른 것까지 만들면 그림 요금이 그만큼 나간다)
  - 기획안을 사람이 안 보고 그림으로 넘어가는 한 방 실행. 만들지 말 것.
재시작 정책: 실패 시 멈춤. 결과가 비면 다음 단계로 넘기지 않는다.
마지막 점검: 2026-07-22
"""

import json
import os
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROMPT_DIR = ROOT / "prompts"
DEFAULT_PROMPT = "포맷집중형"

# 원문 md 에서 "입력 데이터" 안내가 시작되는 줄. 여기서부터는 빈 양식이라
# 잘라내고, 대신 config.json 값으로 채운 입력 블록을 붙인다.
INPUT_HEADING = re.compile(r"^#+\s*\[?입력 데이터")

# 원문 뒤에 붙이는 출력 형식 지시. 원문은 사람이 읽는 표를 내놓는데,
# 그림·업로드 단계가 읽으려면 기계가 읽는 형태가 하나 더 필요하다.
JSON_TAIL = """
---

# [출력 형식 추가 지시]
위 기획안을 사람이 읽을 수 있게 빠짐없이 출력해라.
그리고 맨 마지막에, 단일 이미지 광고 18종만 담은 JSON 하나를 덧붙여라.
캐러셀은 JSON 에 넣지 마라. 사람이 읽는 본문에는 그대로 두어라.

{{
  "copies": [
    {{
      "no": 1,
      "group": "카테고리 이름",
      "hook": "메인 카피",
      "sub": "서브 카피",
      "cta": "버튼에 들어갈 문구",
      "visual": "비주얼 가이드"
    }}
  ]
}}

no 는 1부터 18까지 차례로 매겨라. 줄바꿈은 \\n 으로 쓴다.
JSON 뒤에는 아무 문장도 붙이지 마라.
"""

IMAGE_PROMPT_TASK = """아래는 메타 광고 소재 제작 규칙이다.

--- 규칙 시작 ---
{skill}
--- 규칙 끝 ---

이 규칙의 [공통 품질 규칙] 과 [디자인 톤] 을 그대로 지켜서,
아래 카피 {n}개에 대한 이미지 생성 지시문을 만들어라.

{copies}

지킬 것:
- 카피 문구는 바꾸지 마라. 위에 적힌 그대로 그림에 들어가야 한다.
- 소재마다 디자인 톤을 다르게 배분해라. 한 톤으로 몰지 마라.
- 각 지시문 첫 줄에 어떤 톤인지 밝혀라.
- 지시문 끝에 "지킬 것" 4줄을 붙여라.

마지막에 아래 JSON 하나만 출력해라. 설명 문장을 붙이지 마라.

{{
  "prompts": [
    {{"no": 1, "image_prompt": "그림 생성 도구에 그대로 넣을 지시문 전문"}}
  ]
}}
"""


def run_plan(config: dict, out_dir: Path) -> dict:
    """1단계. 기획안만 만든다. 그림을 안 그리므로 그림 요금이 안 나간다."""
    name = config.get("plan_prompt", DEFAULT_PROMPT)
    body = _load_prompt(name)
    prompt = body + _input_block(name, config) + _load_refs_block(out_dir) + JSON_TAIL

    text = _ask_claude(prompt, out_dir, "plan_raw.txt")
    plan = _extract_json(text)

    copies = plan.get("copies", [])
    if not copies:
        raise RuntimeError("기획안이 하나도 안 나왔다. out/plan_raw.txt 를 볼 것.")

    for i, c in enumerate(copies, 1):
        c.setdefault("no", i)

    plan = {"prompt_name": name, "copies": copies}
    _save(plan, out_dir)
    _write_view(plan, config, out_dir)
    return plan


def make_image_prompts(config: dict, out_dir: Path, picks: list[int]) -> dict:
    """2단계 앞부분. 사람이 고른 번호만 그림 지시문을 만든다.

    picks 가 비면 전부. 이미 지시문이 있는 번호는 다시 만들지 않는다
    (사람이 카피를 고쳤으면 그 번호의 image_prompt 를 지우면 다시 만든다).
    """
    plan = load(out_dir)
    by_no = {c["no"]: c for c in plan["copies"]}

    if picks:
        unknown = [n for n in picks if n not in by_no]
        if unknown:
            raise RuntimeError(
                f"기획안에 없는 번호다: {unknown}\n"
                f"있는 번호: {min(by_no)} ~ {max(by_no)}"
            )
        targets = [by_no[n] for n in picks]
    else:
        targets = plan["copies"]

    todo = [c for c in targets if not c.get("image_prompt")]
    if todo:
        listing = "\n\n".join(
            f"[{c['no']}번]\n메인: {c.get('hook','')}\n"
            f"서브: {c.get('sub','')}\n버튼: {c.get('cta','')}\n"
            f"비주얼 가이드: {c.get('visual','')}"
            for c in todo
        )
        prompt = IMAGE_PROMPT_TASK.format(
            skill=_load_skill(), n=len(todo), copies=listing
        )
        text = _ask_claude(prompt, out_dir, "prompt_raw.txt")
        made = {p["no"]: p["image_prompt"] for p in _extract_json(text).get("prompts", [])}

        missing = [c["no"] for c in todo if c["no"] not in made]
        if missing:
            raise RuntimeError(
                f"지시문이 안 나온 번호가 있다: {missing}\n"
                f"out/prompt_raw.txt 를 볼 것."
            )
        for c in todo:
            c["image_prompt"] = made[c["no"]]
        _save(plan, out_dir)

    return {"copies": [by_no[c["no"]] for c in targets]}


def load(out_dir: Path) -> dict:
    path = out_dir / "plan.json"
    if not path.exists():
        raise RuntimeError(
            "out/plan.json 이 없다. 기획안부터 만들어라:\n"
            "  python factory.py --plan"
        )
    return json.loads(path.read_text(encoding="utf-8"))


def run(config: dict, out_dir: Path, n_images: int = 6) -> dict:
    """옛 흐름(기획과 그림을 한 번에). 스케줄러 자동 실행이 이걸 쓴다.

    사람이 기획안을 고칠 틈이 없으므로, 손으로 할 때는 --plan 을 쓸 것.
    """
    plan = run_plan(config, out_dir)
    picks = [c["no"] for c in plan["copies"]][:n_images]
    return make_image_prompts(config, out_dir, picks)


def _ask_claude(prompt: str, out_dir: Path, raw_name: str) -> str:
    # 카피는 클로드가 짠다. 기본 모델의 사용 한도가 차면(429) 기획이 통째로
    # 막힌다. 그때 PLAN_MODEL 환경변수로 다른 모델을 고른다. 예: PLAN_MODEL=opus
    cmd = ["claude", "-p", prompt, "--output-format", "json"]
    model = os.environ.get("PLAN_MODEL", "").strip()
    if model:
        cmd[1:1] = ["--model", model]

    proc = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", timeout=1800
    )

    # 원본을 먼저 남긴다. 형식이 어긋나 멈췄을 때 무엇이 왔는지 봐야 한다.
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / raw_name).write_text(proc.stdout or "(빈 출력)", encoding="utf-8")

    if proc.returncode != 0:
        raise RuntimeError(f"클로드 호출 실패\n{proc.stderr[:800]}")
    return proc.stdout


def _load_prompt(name: str) -> str:
    """전자책 PART 7 프롬프트 원문을 읽어온다. 입력 양식 앞까지만 쓴다."""
    path = PROMPT_DIR / f"기획_{name}.md"
    if not path.exists():
        have = ", ".join(sorted(p.stem.replace("기획_", "") for p in PROMPT_DIR.glob("기획_*.md")))
        raise RuntimeError(f"{path.name} 이 없다. 쓸 수 있는 것: {have}")

    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if INPUT_HEADING.match(line.strip()):
            return "\n".join(lines[:i]).rstrip() + "\n"
    return "\n".join(lines).rstrip() + "\n"


def _input_block(name: str, config: dict) -> str:
    """원문의 빈 입력 양식 자리에, config.json 값을 채워 넣는다."""
    raw = _load_raw_data(config)
    if name == "타겟집중형":
        return f"""
---

# [입력 데이터 (Input Data)]
1. 자사 상품명: {config['product']}
2. 핵심 USP 및 파격적 편익: {config.get('differentiator') or '(자료에서 도출할 것)'}
3. 타겟 핵심 상황: {config.get('situation') or '(비움. 자료를 바탕으로 직접 추출할 것)'}
4. [데이터칸] 분석용 데이터:
가격 또는 계약단가: {config['price']}
돈 내는 사람: {config['buyer']}
실제 쓰는 사람: {config['user']}
{raw}
"""
    return f"""
---

# [입력 데이터 (Input Data)]
1. 기본 정보 (요약본)
- 상품/서비스 명 : {config['product']}
- 상품의 기술적 특징/스펙 : {config.get('features') or '(자료에서 도출할 것)'}
- 업체 철학 및 차별점 : {config.get('differentiator') or '(자료에서 도출할 것)'}
- 타겟이 겪는 문제 상황/결핍 : {config.get('pain') or '(자료에서 도출할 것)'}
- 가격 또는 계약단가 : {config['price']}
- 돈 내는 사람 : {config['buyer']}
- 실제 쓰는 사람 : {config['user']}
2. 원본 데이터 (Raw Data)
{raw}
"""


def _load_raw_data(config: dict) -> str:
    """상세페이지·리뷰 같은 원본 자료. config 의 raw_data_file 로 넘긴다.

    없으면 커뮤니티에서 고객 언어를 직접 모으라고 지시한다(스킬 1단계와 같다).
    """
    name = config.get("raw_data_file")
    if name:
        path = ROOT / name
        if not path.exists():
            raise RuntimeError(f"config 의 raw_data_file 이 없다: {path}")
        return path.read_text(encoding="utf-8")
    return (
        "(붙여넣은 원본 자료 없음. 커뮤니티·후기에서 이 타겟이 실제로 쓰는 표현과\n"
        "반복되는 불만·욕구를 먼저 조사한 뒤, 그 표현을 근거로 기획해라.\n"
        "조사한 글에 실제로 있던 숫자만 쓰고, 없는 숫자를 지어내지 마라.)"
    )


def _load_skill() -> str:
    path = ROOT / "skill" / "SKILL.md"
    if not path.exists():
        raise RuntimeError(f"{path} 가 없다. 이미지 규격을 읽을 수 없다.")
    return path.read_text(encoding="utf-8")


def _save(plan: dict, out_dir: Path) -> None:
    (out_dir / "plan.json").write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _write_view(plan: dict, config: dict, out_dir: Path) -> None:
    """사람이 보는 기획안 표. 코드 파일을 눈으로 읽게 하지 않는다."""
    rows = []
    for c in plan["copies"]:
        rows.append(
            "<tr>"
            f"<td class=no>{c.get('no','')}</td>"
            f"<td class=g>{_esc(c.get('group',''))}</td>"
            f"<td class=hook>{_esc(c.get('hook',''))}</td>"
            f"<td>{_esc(c.get('sub',''))}</td>"
            f"<td class=cta>{_esc(c.get('cta',''))}</td>"
            f"<td class=v>{_esc(c.get('visual',''))}</td>"
            "</tr>"
        )

    html = f"""<!doctype html><html lang=ko><head><meta charset=utf-8>
<title>기획안 - {_esc(config.get('product',''))}</title>
<style>
 body{{font-family:'Pretendard','맑은 고딕',sans-serif;margin:40px auto;max-width:1100px;
      color:#111;line-height:1.5}}
 h1{{font-size:22px;margin:0 0 6px}}
 .sub{{color:#666;font-size:13px;margin-bottom:22px}}
 .how{{background:#f6f7f9;border-left:3px solid #1a2b5f;padding:14px 18px;
       font-size:14px;margin-bottom:26px}}
 .how b{{color:#1a2b5f}}
 table{{border-collapse:collapse;width:100%;font-size:14px}}
 th{{background:#1a2b5f;color:#fff;padding:10px;text-align:left;font-weight:600}}
 td{{border-bottom:1px solid #e5e7eb;padding:11px 10px;vertical-align:top}}
 tr:hover td{{background:#fafbfc}}
 .no{{width:38px;color:#888;text-align:center}}
 .g{{width:96px;color:#1a2b5f;font-size:13px}}
 .hook{{font-weight:600;width:24%}}
 .cta{{width:12%;color:#c0392b;font-size:13px}}
 .v{{width:20%;color:#666;font-size:13px}}
</style></head><body>
<h1>소재 기획안 &mdash; {_esc(config.get('product',''))}</h1>
<div class=sub>{_esc(plan.get('prompt_name',''))} 기획 · 카피 {len(plan['copies'])}개</div>
<div class=how>
 <b>여기서 멈춥니다.</b> 아직 그림은 안 그렸고 요금도 거의 안 나갔습니다.<br>
 표를 보고 고칠 것을 클로드에게 말로 알려주세요.
 "3번 후킹 더 세게", "7번 빼고 5번 톤으로 두 개 더" 처럼 말하면 됩니다.<br>
 다 골랐으면 <b>"1, 4, 9번 그림 뽑아줘"</b> 라고 말하세요. 고른 번호만 그립니다.
</div>
<table>
<tr><th>번호</th><th>카테고리</th><th>메인 카피</th><th>서브 카피</th><th>버튼</th><th>비주얼 가이드</th></tr>
{''.join(rows)}
</table>
</body></html>"""
    (out_dir / "기획안.html").write_text(html, encoding="utf-8")


def _esc(s) -> str:
    s = "" if s is None else str(s)
    return (
        s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace("\n", "<br>")
    )


def _load_refs_block(out_dir: Path) -> str:
    """레퍼런스 해부 결과가 있으면 카피 기획에 넣을 지시 블록을 만든다.

    refs_analysis.json 은 factory.py --benchmark 가 만든다. 없으면 빈 문자열이라
    기존 동작 그대로다(하위호환).
    """
    path = out_dir / "refs_analysis.json"
    if not path.exists():
        return ""
    try:
        refs = json.loads(path.read_text(encoding="utf-8")).get("refs", [])
    except (json.JSONDecodeError, OSError):
        return ""
    if not refs:
        return ""

    lines = [
        "",
        "아래는 사용자가 고른 '잘 되는 참고 광고'들의 구조 분석이다.",
        "공통 성공 구조(세계관·타겟·문제·해결·카피 논리·소구·시선 흐름·타겟 언어)를",
        "이번 카피 기획에 반영해라. 단 문구를 베끼지 마라 — 이식 가능한 구조만 가져와라.",
        "벤치마크는 따라하기가 아니다.",
    ]
    for i, r in enumerate(refs, 1):
        lines.append(f"[참고 광고 {i}: {r.get('file', '')}]")
        lines.append(json.dumps(r.get("analysis", {}), ensure_ascii=False))
    return "\n".join(lines)


def _extract_json(stdout: str) -> dict:
    """claude -p --output-format json 은 바깥을 한 번 감싼다.

    바깥 껍질을 벗기고, 그 안 본문에서 다시 우리 JSON 을 찾는다.
    본문에 표와 설명이 길게 붙어 나오므로, 뒤에서부터 여는 괄호를 찾아
    실제로 파싱되는 덩어리를 집는다.
    """
    try:
        outer = json.loads(stdout)
        text = outer.get("result", stdout) if isinstance(outer, dict) else stdout
    except json.JSONDecodeError:
        text = stdout

    end = text.rfind("}")
    if end == -1:
        raise RuntimeError(f"결과에서 JSON 을 못 찾았다:\n{text[:500]}")

    # 본문 안에 중괄호가 여럿 섞여 있어도, 마지막 JSON 덩어리만 골라낸다.
    for start in _brace_starts(text, end):
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("copies" in data or "prompts" in data):
            return data

    raise RuntimeError(f"결과의 JSON 을 읽지 못했다:\n{text[-500:]}")


def _brace_starts(text: str, end: int):
    """마지막 '}' 앞의 '{' 위치를 뒤에서부터 훑는다."""
    i = end
    while True:
        i = text.rfind("{", 0, i)
        if i == -1:
            return
        yield i
