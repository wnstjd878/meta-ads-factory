"""
== 운영 맥락 ==
실행 시점: factory.py 각 단계에서 호출
입력: META_ADS_TOKEN, META_AD_ACCOUNT_ID, BEP_CENTS (.env)
출력: 메타 광고 계정에 이미지·소재·캠페인 생성
외부 의존: graph.facebook.com (시스템 사용자 토큰)
의도적 미구현:
  - 광고 켜기/끄기/삭제. guards.py 가 막는다. 재구현 금지.
  - 복제(copies) 호출. 예산 검사를 우회하므로 막았다.
재시작 정책: 실패하면 그 자리에서 멈춘다. 자동 재시도 없음(중복 생성 방지).
마지막 점검: 2026-07-09

토큰 주의:
  이 토큰은 광고 계정을 만질 수 있는 열쇠다. .env 에만 두고 채팅·코드·로그에
  절대 찍지 않는다. 노출되면 business.facebook.com 에서 즉시 폐기하고 재발급.
"""

import os
import requests

from guards import guard, GuardError

API_VERSION = os.environ.get("META_API_VERSION", "v21.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"


def _token() -> str:
    t = os.environ.get("META_ADS_TOKEN")
    if not t:
        raise RuntimeError(
            "META_ADS_TOKEN 이 없다. .env 에 넣어라.\n"
            "발급: business.facebook.com > 설정 > 사용자 > 시스템 사용자"
        )
    return t


def _bep_cents() -> int:
    raw = os.environ.get("BEP_CENTS")
    if not raw:
        raise RuntimeError("BEP_CENTS 가 없다. 손익분기 결과당 비용을 센트로. ($13 이면 1300)")
    return int(raw)


def _account() -> str:
    acc = os.environ.get("META_AD_ACCOUNT_ID")
    if not acc:
        raise RuntimeError("META_AD_ACCOUNT_ID 가 없다. 숫자만. (act_ 접두어 없이)")
    return f"act_{acc}"


def call(method: str, path: str, payload: dict | None = None, files: dict | None = None) -> dict:
    """메타를 부르는 유일한 통로. 반드시 가드를 지나간다.

    직접 requests.post 를 쓰지 마라. 가드를 우회하게 된다.
    """
    safe_payload = guard(method, path, payload, _bep_cents())

    url = f"{BASE}/{path.strip('/')}"
    data = dict(safe_payload)
    data["access_token"] = _token()

    if method.upper() == "GET":
        r = requests.get(url, params=data, timeout=60)
    else:
        r = requests.post(url, data=data, files=files, timeout=120)

    if not r.ok:
        # 토큰이 오류 메시지에 섞여 나오지 않게 잘라낸다.
        body = r.text.replace(_token(), "<토큰가림>")
        raise RuntimeError(f"메타 호출 실패 {r.status_code}\n{path}\n{body[:800]}")

    return r.json()


def account_path(suffix: str) -> str:
    return f"{_account()}/{suffix}"


def wait_video_ready(video_id: str, timeout_sec: int = 600) -> str:
    """영상은 올린 뒤 메타가 인코딩을 끝낼 때까지 기다려야 한다.

    준비되기 전에 소재를 만들면 거부당한다. 30초마다 물어본다.
    끝나면 메타가 만들어준 썸네일 주소를 돌려준다(광고 소재에 필요).
    """
    import time

    waited = 0
    while waited < timeout_sec:
        got = call("GET", video_id, {"fields": "status"})
        state = (got.get("status") or {}).get("video_status", "")

        if state == "ready":
            break
        if state == "error":
            raise RuntimeError(f"영상 처리 실패: {video_id} / {got}")

        print(f"  영상 처리 중... ({waited}초 경과)")
        time.sleep(30)
        waited += 30
    else:
        raise RuntimeError(
            f"영상 처리가 {timeout_sec}초 안에 안 끝났다: {video_id}\n"
            f"메타 쪽이 느린 것이니 잠시 뒤 --setup 을 다시 돌려라."
        )

    # 썸네일. 메타가 첫 프레임으로 만들어준다. 우리가 따로 뽑지 않는다.
    thumbs = call("GET", video_id, {"fields": "thumbnails"}).get("thumbnails", {})
    data = thumbs.get("data") or []
    if not data:
        raise RuntimeError(f"영상 썸네일을 못 받았다: {video_id}")

    preferred = next((t for t in data if t.get("is_preferred")), data[0])
    return preferred["uri"]


def verify_paused(entity_id: str) -> str:
    """만들고 나서 정말 꺼져 있는지 다시 물어본다.

    만들었다는 응답만 믿지 않는다. 켜진 채로 생기면 밤새 돈이 나간다.

    두 가지를 본다.
      status            우리가 설정한 상태. 반드시 PAUSED.
      effective_status  메타가 계산한 실제 상태. ACTIVE 가 아니면 된다.

    갓 만든 광고세트는 effective_status 가 잠시 IN_PROCESS 다. 켜진 게 아니라
    메타가 처리 중이라는 뜻이다. 그건 통과시킨다.
    """
    got = call("GET", entity_id, {"fields": "status,effective_status,name"})
    configured = got.get("status")
    effective = got.get("effective_status")

    if configured != "PAUSED":
        raise GuardError(
            f"만든 물건의 설정 상태가 PAUSED 가 아니다: {entity_id} = {configured}\n"
            f"지금 광고 관리자에서 직접 끄고, guards.py 를 점검할 것."
        )

    # 돈이 나가는 상태는 이것뿐이다. 나머지(IN_PROCESS, PENDING_REVIEW,
    # CAMPAIGN_PAUSED, ADSET_PAUSED 등)는 노출도 지출도 없다.
    if effective == "ACTIVE":
        raise GuardError(
            f"만든 물건이 켜져 있다: {entity_id} (설정은 PAUSED 인데 실제는 ACTIVE)\n"
            f"지금 광고 관리자에서 직접 끌 것."
        )

    return got.get("name", "")
