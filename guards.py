"""
== 운영 맥락 ==
실행 시점: factory.py 가 메타 호출을 할 때마다 반드시 경유 (직접 requests 금지)
입력: 호출 경로 + 본문
출력: 통과시키거나 즉시 멈춤
외부 의존: 없음 (순수 검사기)
의도적 미구현:
  - 광고 켜기(ACTIVE 전환) 기능. 사람이 광고 관리자에서 직접 켠다. 재구현 금지.
  - 삭제 기능. 잘못 지우면 복구 못 함. 재구현 금지.
재시작 정책: 없음 (라이브러리)
마지막 점검: 2026-07-09

왜 있나:
  메타 공식 연결(MCP)은 도구 자체가 일시중지로만 만들어준다. 그런데 우리는
  이미지 업로드 때문에 토큰으로 직접 호출한다. 토큰은 켜기·끄기·삭제·예산변경이
  전부 되는 열쇠라, 메타가 대신 막아주던 안전장치가 사라진다.
  그 안전장치를 여기서 코드로 다시 만든다. CLAUDE.md 9.2 결제 변경 차단과 같은 패턴.
"""

import re

# 광고 계정을 만지는 호출 중 이것만 허용한다.
ALLOWED_PATTERNS = (
    r"^act_\d+/adimages$",      # 이미지 올리기
    r"^act_\d+/advideos$",      # 영상 올리기
    r"^act_\d+/adcreatives$",   # 소재 만들기
    r"^act_\d+/campaigns$",     # 캠페인 만들기
    r"^act_\d+/adsets$",        # 광고세트 만들기
    r"^act_\d+/ads$",           # 광고 만들기
    r"^act_\d+/?$",             # 계정 조회
    r"^\d+/?$",                 # 개별 항목 조회
)

# 이 경로는 무슨 일이 있어도 막는다.
BLOCKED_PATTERNS = (
    (r"/copies$", "복제 호출은 예산 검사를 우회할 수 있다"),
)

# 본문에 이 값이 들어오면 막는다.
BLOCKED_FIELDS = {
    "status": ("ACTIVE", "ARCHIVED", "DELETED"),
    "effective_status": ("ACTIVE",),
    "configured_status": ("ACTIVE",),
}


class GuardError(RuntimeError):
    """가드가 막았을 때. 절대 except 로 삼키지 말 것."""


def check_path(method: str, path: str) -> None:
    """호출 경로가 허용 목록에 있는지 본다."""
    p = path.strip("/")

    for pattern, why in BLOCKED_PATTERNS:
        if re.search(pattern, p):
            raise GuardError(f"차단된 경로: {path} ({why})")

    if method.upper() == "GET":
        return  # 조회는 자유

    if method.upper() in ("DELETE", "PUT"):
        raise GuardError(f"{method} 는 쓰지 않는다. 삭제·수정은 사람이 광고 관리자에서.")

    if not any(re.search(pattern, p) for pattern in ALLOWED_PATTERNS):
        raise GuardError(
            f"허용 목록에 없는 경로: {path}\n"
            f"정말 필요하면 guards.py ALLOWED_PATTERNS 에 추가하고 그 이유를 주석으로 남길 것."
        )


def check_status(payload: dict) -> None:
    """만들어지는 물건이 켜진 상태로 생기지 않는지 본다."""
    if not isinstance(payload, dict):
        return
    for field, blocked_values in BLOCKED_FIELDS.items():
        value = payload.get(field)
        if value is None:
            continue
        if str(value).upper() in blocked_values:
            raise GuardError(
                f"{field}={value} 로 만들려 한다. 생성은 PAUSED 만 허용한다.\n"
                f"켜는 건 사람이 광고 관리자에서."
            )


def check_budget(payload: dict, bep_cents: int) -> None:
    """하루 예산이 손익분기의 7배를 넘지 않는지 본다.

    메타는 예산을 센트 단위 정수로 받는다. BEP $13 이면 bep_cents=1300.
    상한 = 1300 * 7 = 9100 센트 = $91.
    """
    if not isinstance(payload, dict):
        return

    cap = bep_cents * 7
    for field in ("daily_budget", "campaign_daily_budget"):
        raw = payload.get(field)
        if raw is None:
            continue
        try:
            value = int(raw)
        except (TypeError, ValueError):
            raise GuardError(f"{field} 가 숫자가 아니다: {raw!r}")
        if value > cap:
            raise GuardError(
                f"하루 예산 {value/100:.2f} 가 상한 {cap/100:.2f} 를 넘는다.\n"
                f"상한 = 손익분기 {bep_cents/100:.2f} x 7 (7일에 결과 50건 기준).\n"
                f"정말 늘리려면 사람이 광고 관리자에서."
            )

    # 총액 예산은 하루로 환산이 안 되니 아예 막는다.
    for field in ("lifetime_budget", "campaign_lifetime_budget"):
        if payload.get(field) is not None:
            raise GuardError(f"{field} 는 쓰지 않는다. 하루 예산만 쓴다(상한 검사가 되니까).")


def force_paused(payload: dict) -> dict:
    """만들 때 항상 일시중지를 박아 넣는다. 빠뜨릴 수 없게."""
    out = dict(payload)
    out["status"] = "PAUSED"
    return out


def guard(method: str, path: str, payload: dict | None, bep_cents: int) -> dict:
    """모든 메타 호출은 이 함수를 지나간다.

    통과하면 실제로 보낼 본문을 돌려준다. 막히면 GuardError 로 즉시 멈춘다.
    """
    check_path(method, path)

    if method.upper() == "GET" or payload is None:
        return payload or {}

    check_status(payload)
    check_budget(payload, bep_cents)

    # 캠페인·광고세트·광고를 만들 때만 일시중지를 박는다.
    # 이미지와 소재는 상태라는 개념이 없다.
    if re.search(r"/(campaigns|adsets|ads)$", path.strip("/")):
        return force_paused(payload)

    return dict(payload)
