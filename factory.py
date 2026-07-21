"""
== 운영 맥락 ==
실행 시점: 사람이 직접. 두 번에 나눠 친다.
  1) python factory.py --images 6      기획 + 콘텐츠 -> out/images/ 에 저장하고 멈춤
     (여기서 사람이 콘텐츠를 눈으로 본다. 마음에 안 드는 건 파일을 지운다)
  2) python factory.py --setup         남은 소재만 광고 계정에 올리고 111 캠페인
입력: config.json, .env
     out/videos/NN.mp4 (선택) — ad-video 로 만든 영상. NN 은 카피 번호
출력: out/images/*.png, out/plan.json, out/results.json, out/보고서.html
외부 의존: claude 실행 파일, 콘텐츠 생성 서비스, graph.facebook.com
의도적 미구현:
  - 콘텐츠를 뽑자마자 바로 세팅하는 한 방 실행. 콘텐츠는 확률이라 사람이 봐야 한다.
    한 번에 돌리고 싶어도 만들지 말 것. 이 두 단계 구조가 안전장치다.
  - 영상 생성. 영상은 ad-video(Mac, Remotion)가 만든다. 여기는 올리고 세팅만.
  - 영상 광고 문구 생성. plan.json 의 카피(후킹/서브/버튼)를 그대로 쓴다.
  - 광고 켜기. 사람이 켠다. 재구현 금지.
  - 텔레그램·메일 알림. 결과는 보고서.html 을 연다. 열쇠를 더 늘리지 않는다.
  - 자동 재시도. 중복 캠페인이 생기므로 실패하면 그 자리에서 멈춘다.
  - 성과 판정(/판정). 그건 Cowork 스킬에서 사람이 본다.
재시작 정책: 1단계 결과가 out/ 에 남는다. 2단계만 다시 돌릴 수 있다.
마지막 점검: 2026-07-09

돈이 나가는 경로:
  1) 콘텐츠 생성: 장당 요금. image.py MAX_IMAGES 로 상한.
  2) 광고 집행: 만들기만 하고 켜지 않으므로 0원. guards.py 가 켜진 생성을 막는다.
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from steps import plan as step_plan
from steps import image as step_image
from steps import upload as step_upload
from steps import setup as step_setup
from steps import report as step_report
from steps import benchmark as step_benchmark

ROOT = Path(__file__).parent
OUT = ROOT / "out"
IMG = OUT / "images"
VID = OUT / "videos"   # ad-video 로 만든 mp4 를 여기 넣는다
REFS = ROOT / "refs"   # 잘 되는 참고 광고 이미지를 여기 넣는다 (--benchmark 가 뜯어봄)


def load_env() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        raise RuntimeError(".env 가 없다. .env.example 을 보고 만들어라.")
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def check_config(config: dict) -> None:
    """세팅 단계에서 필요한 값이 빠졌는지 미리 본다.

    콘텐츠를 다 만들고 나서 "페이지 ID 가 없다"로 멈추면 요금만 나간다.
    """
    required = ["product", "price", "buyer", "user", "bep", "bep_cents",
                "page_id", "link_url", "pixel_id", "event_type",
                "country", "daily_budget_cents"]
    missing = [k for k in required if not config.get(k)]
    if missing:
        raise RuntimeError(f"config.json 에 빠진 값: {', '.join(missing)}")

    # 손익분기를 meta.py 가 예산 상한 검사에 쓰도록 넘겨준다.
    # (예전엔 .env 의 BEP_CENTS 였지만, 상품마다 다르므로 config 로 옮겼다.)
    os.environ["BEP_CENTS"] = str(config["bep_cents"])

    bep_cents = int(config["bep_cents"])
    if config["daily_budget_cents"] > bep_cents * 7:
        raise RuntimeError(
            f"하루 예산 {config['daily_budget_cents']/100:.2f} 가 "
            f"상한 {bep_cents*7/100:.2f} 를 넘는다. config.json 을 고쳐라."
        )


def run_benchmark() -> None:
    """0단계. refs/ 의 참고 광고를 4축7키로 뜯어본다. 콘텐츠·계정을 안 건드린다."""
    REFS.mkdir(exist_ok=True)
    print("\n[레퍼런스 해부] refs/ 의 참고 광고를 뜯어본다 (계정·요금 무관)")
    data = step_benchmark.run(REFS, OUT)
    n = len(data.get("refs", []))
    if n == 0:
        print(f"\n  refs/ 에 이미지가 없다:\n  {REFS}")
        print("  잘 된다고 보는 광고 이미지(png/jpg)를 넣고 다시 실행해라.")
        return
    print(f"\n  참고 광고 {n}개 해부 완료 -> out/refs_analysis.json")
    print("  이제 메뉴에서 1번(카피+콘텐츠)을 고르면 이 구조가 카피에 반영된다.")


def make_images(config: dict, n_images: int) -> None:
    """1단계. 기획하고 콘텐츠를 뽑아 폴더에 저장하고 멈춘다."""
    if (OUT / "refs_analysis.json").exists():
        print("[레퍼런스] out/refs_analysis.json 을 카피 기획에 반영한다.")
    print("\n[1/2] 소재 기획")
    plan = step_plan.run(config, OUT, n_images=n_images)
    print(f"      카피 {len(plan['copies'])}개 + 이미지 지시문")

    print("\n[2/2] 콘텐츠 생성 (요금 발생)")
    made = step_image.run(plan, OUT)
    print(f"      {len(made)}장 완성")

    print(f"\n콘텐츠를 폴더에서 눈으로 확인해라:\n  {IMG}")
    print("\n마음에 안 드는 콘텐츠는 그 PNG 파일을 지워라. 남은 것만 광고가 된다.")
    print("확인이 끝나면 메뉴에서 2번(광고 만들기)을 고른다.")


def load_checked() -> tuple[list[dict], list[dict]]:
    """2단계. 사람이 확인하고 남겨둔 콘텐츠와 영상을 가져온다.

    파일을 지운 소재는 자동으로 빠진다. 그게 검수다.

    영상은 밖에서 만들어(ad-video) out/videos/01.mp4 처럼 넣어둔다.
    파일 이름의 번호가 plan.json 의 카피 번호와 맞아야 문구가 붙는다.
    """
    plan_path = OUT / "plan.json"
    if not plan_path.exists():
        raise RuntimeError(
            "out/plan.json 이 없다. 먼저 카피와 콘텐츠부터 만들어라:\n"
            "  python factory.py --images 6"
        )

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    images, videos, dropped = [], [], []

    for c in plan["copies"]:
        png = IMG / f"{c['no']:02d}.png"
        mp4 = VID / f"{c['no']:02d}.mp4"
        if mp4.exists():
            videos.append({**c, "video_path": str(mp4)})
        elif png.exists():
            images.append({**c, "image_path": str(png)})
        else:
            dropped.append(c["no"])

    if dropped:
        nums = ", ".join(f"{n:02d}" for n in sorted(dropped))
        print(f"  지운 소재 {len(dropped)}개는 건너뜁니다: {nums}")

    # 카피 없는 영상이 폴더에 있으면 알려준다. 문구 없이는 광고를 못 만든다.
    if VID.exists():
        known = {f"{c['no']:02d}" for c in plan["copies"]}
        orphans = [p.name for p in VID.glob("*.mp4") if p.stem not in known]
        if orphans:
            print(f"  카피가 없는 영상은 건너뜁니다: {', '.join(orphans)}")
            print("  (파일 이름을 plan.json 의 카피 번호에 맞춰라. 예: 01.mp4)")

    if not images and not videos:
        raise RuntimeError(
            f"{IMG} 와 {VID} 에 쓸 소재가 하나도 없다.\n"
            "전부 지웠거나 아직 안 만들었다. 다시 만들려면:\n"
            "  python factory.py --images 6"
        )
    return images, videos


def setup_ads(config: dict, tag: str) -> None:
    """2단계. 사람이 통과시킨 콘텐츠와 영상으로 광고를 만든다."""
    images, videos = load_checked()
    print(f"\n사람이 통과시킨 소재: 콘텐츠 {len(images)}장, 영상 {len(videos)}개")

    uploaded = []

    if images:
        print("\n[1/3] 메타에 이미지 올리기")
        uploaded += step_upload.run(images)

    if videos:
        print("\n[1/3] 메타에 영상 올리기 (인코딩 대기로 몇 분 걸린다)")
        uploaded += step_upload.run_videos(videos)

    print("\n[2/3] 111 캠페인 만들기 (전부 일시중지)")
    results = step_setup.run(uploaded, config, tag)
    (OUT / "results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print("\n[3/3] 보고서")
    account_name = config.get("account_name", "광고 계정")
    report_path = step_report.run(results, account_name, OUT, tag)

    print(f"\n끝. {len(results)}개 만들었고 전부 꺼져 있다. 지출 0원.")
    print(f"보고서: {report_path}")
    print("광고 관리자에서 켤 것만 켜라.")


def _interactive_choose(args) -> bool:
    """아무것도 안 붙이고 그냥 실행하면 뜨는 번호 메뉴.

    영어 플래그(--benchmark 등)를 몰라도 번호만 고르면 된다.
    고른 대로 args 를 채워서 돌려준다. 잘못 고르면 False.
    """
    print("\n무엇을 할까요?")
    print("  0. 참고 광고 분석 (refs 폴더)")
    print("  1. 카피 + 콘텐츠 뽑기")
    print("  2. 광고 만들기 (꺼진 채로)")
    choice = input("번호: ").strip()

    if choice == "0":
        args.benchmark = True
    elif choice == "1":
        n = input("몇 장 뽑을까요? (엔터 = 6) ").strip()
        args.images = int(n) if n.isdigit() and int(n) > 0 else 6
    elif choice == "2":
        tag = input("이름표를 붙일까요? (엔터 = 자동) ").strip()
        args.setup = True
        if tag:
            args.tag = tag
    else:
        print("0, 1, 2 중에서 골라라.")
        return False
    return True


def main() -> None:
    ap = argparse.ArgumentParser(
        description="소재 공장. 콘텐츠를 뽑아 두고, 사람이 본 뒤, 광고로 만든다."
    )
    ap.add_argument("--benchmark", action="store_true",
                    help="0단계. refs/ 의 참고 광고를 4축7키로 뜯어본다.")
    ap.add_argument("--setup", action="store_true",
                    help="2단계. 폴더에 남은 콘텐츠로 광고를 만든다.")
    ap.add_argument("--images", type=int, default=6, help="1단계에서 만들 콘텐츠 장수")
    ap.add_argument("--tag", default="자동", help="캠페인 이름 앞에 붙일 표시")
    args = ap.parse_args()

    load_env()
    OUT.mkdir(exist_ok=True)

    # 아무 플래그 없이 그냥 실행하면 번호 메뉴를 띄운다.
    # 자동 실행(스케줄러)은 아래 플래그를 그대로 쓴다.
    if len(sys.argv) == 1:
        if not _interactive_choose(args):
            return

    if args.benchmark:
        run_benchmark()
        return

    config = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    check_config(config)

    if args.setup:
        setup_ads(config, args.tag)
    else:
        make_images(config, args.images)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n멈춤: {e}", file=sys.stderr)
        sys.exit(1)
