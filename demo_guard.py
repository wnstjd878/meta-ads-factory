"""
== 운영 맥락 ==
실행 시점: 강의 촬영 6절(안전장치) 시연 때만. 사람이 직접.
입력: 없음 (가짜 호출을 일부러 만들어 가드에 넣어본다)
출력: 막혔다는 한 줄 메시지들. 광고 계정은 안 건드린다.
외부 의존: guards.py 만.
의도적 미구현:
  - 실제 메타 호출. 이 파일은 가드 검사만 시연한다. 계정을 안 만진다.
재시작 정책: 없음. 여러 번 돌려도 같은 화면.
마지막 점검: 2026-07-11

왜 있나:
  대본 6절은 `python -c "from guards import guard; ..."` 로 시연하는데,
  그렇게 돌리면 GuardError 위에 파이썬 Traceback 이 네다섯 줄 붙는다.
  시청자에겐 "안전장치가 막았다"가 아니라 "에러가 잔뜩 났다"로 보인다.
  그래서 Traceback 없이 "막힘: ..." 한 줄로 깔끔하게 보여준다.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from guards import guard, GuardError

BEP_CENTS = 1300  # 손익분기 $13. 상한 = 13 x 7 = $91

# (설명, 메서드, 경로, 본문) — 전부 막혀야 하는 위험한 호출
CASES = [
    ("켜진 채로 캠페인 생성", "POST", "act_123/campaigns",
     {"name": "x", "status": "ACTIVE"}),
    ("하루 예산을 상한 위로", "POST", "act_123/adsets",
     {"daily_budget": 10000}),          # $100 > 상한 $91
    ("총액 예산 사용", "POST", "act_123/adsets",
     {"lifetime_budget": 50000}),
    ("기존 광고를 삭제", "DELETE", "act_123/ads/999", None),
    ("허용 목록에 없는 곳 호출", "POST", "act_123/adaccounts", {"x": 1}),
]

# 이건 통과해야 하는 정상 호출 (꺼진 상태가 자동으로 박힘)
OK_CASE = ("정상: 캠페인 생성", "POST", "act_123/campaigns",
           {"name": "정상 캠페인", "daily_budget": 2000})


def main() -> None:
    print("안전장치 시연. 위험한 호출은 막고, 정상 호출만 통과시킨다.\n")

    print("[막아야 하는 것]")
    for desc, method, path, payload in CASES:
        try:
            guard(method, path, payload, BEP_CENTS)
            print(f"  뚫림!! {desc} — 이건 막혔어야 한다. 코드를 확인하라.")
        except GuardError as e:
            first = str(e).splitlines()[0]
            print(f"  막힘  {desc}\n        → {first}")

    print("\n[통과해야 하는 것]")
    desc, method, path, payload = OK_CASE
    out = guard(method, path, payload, BEP_CENTS)
    print(f"  통과  {desc}")
    print(f"        → 보낼 본문에 status={out.get('status')} 가 자동으로 박혔다")

    print("\n메타를 부르는 통로는 코드 안에 하나뿐이고, 반드시 이 검사를 지난다.")


if __name__ == "__main__":
    main()
