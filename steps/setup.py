"""
== 운영 맥락 ==
실행 시점: factory.py 2단계(--setup)
입력: 이미지 해시(또는 영상 번호 + 썸네일) + 카피, config.json
출력: 소재 1개 + 111 캠페인(캠페인 1 / 광고세트 1 / 광고 1) 을 소재마다
외부 의존: graph.facebook.com (토큰). guards.py 를 반드시 경유
의도적 미구현:
  - 광고 켜기. 사람이 광고 관리자에서 켠다. 재구현 금지.
  - ABO 승격, CBO 생성. 111 테스트 통과 후 사람이 판단한다(강의 5강 규칙).
  - 관심사 타겟팅. 넓은 지역 타겟만. 가짜 관심사 ID 를 넣으면 거부된다.
재시작 정책: 캠페인 하나 실패하면 그 소재만 건너뛰고 다음 소재로.
마지막 점검: 2026-07-09

만들고 나서 반드시 다시 조회해 일시중지인지 확인한다(meta.verify_paused).
만들었다는 응답만 믿으면 안 된다.
"""

import json

import meta

# 강의 5강: 새 소재는 111(1캠페인 1광고세트 1광고)로 시작한다.
OBJECTIVE = "OUTCOME_LEADS"
OPTIMIZATION_GOAL = "OFFSITE_CONVERSIONS"
BILLING_EVENT = "IMPRESSIONS"


def run(uploaded: list[dict], config: dict, batch_tag: str) -> list[dict]:
    results = []
    for item in uploaded:
        try:
            results.append(_one(item, config, batch_tag))
        except Exception as e:
            print(f"  [건너뜀] {item['no']}번 세팅 실패: {str(e)[:300]}")

    if not results:
        raise RuntimeError("캠페인을 하나도 못 만들었다.")
    return results


def _story_spec(item: dict, config: dict) -> dict:
    """이미지 광고와 영상 광고는 소재 모양이 다르다.

    이미지: link_data + image_hash
    영상  : video_data + video_id + 썸네일(image_url)
    """
    cta = {
        "type": config.get("cta_type", "SIGN_UP"),
        "value": {"link": config["link_url"]},
    }

    if item.get("video_id"):
        return {
            "page_id": config["page_id"],
            "video_data": {
                "video_id": item["video_id"],
                "image_url": item["thumb_url"],
                "message": item["hook"],
                "title": item["sub"],
                "call_to_action": cta,
            },
        }

    return {
        "page_id": config["page_id"],
        "link_data": {
            "link": config["link_url"],
            "image_hash": item["image_hash"],
            "message": item["hook"],
            "name": item["sub"],
            "call_to_action": cta,
        },
    }


def _one(item: dict, config: dict, batch_tag: str) -> dict:
    no = item["no"]
    kind = "영상" if item.get("video_id") else item["format"]
    name = f"[{batch_tag}] {no:02d}_{kind}"

    creative = meta.call(
        "POST",
        meta.account_path("adcreatives"),
        {
            "name": f"{name}_소재",
            "object_story_spec": json.dumps(_story_spec(item, config), ensure_ascii=False),
        },
    )

    campaign = meta.call(
        "POST",
        meta.account_path("campaigns"),
        {
            "name": name,
            "objective": OBJECTIVE,
            "buying_type": "AUCTION",
            "special_ad_categories": "[]",
            # 예산을 광고세트에 건다(ABO). 캠페인이 예산을 나눠주지 않는다.
            # 111 테스트는 소재마다 예산을 따로 봐야 하므로 캠페인 예산을 쓰지 않는다.
            # 메타가 이 값을 명시하라고 요구한다(2026-07 기준).
            "is_adset_budget_sharing_enabled": "false",
        },
    )
    meta.verify_paused(campaign["id"])

    adset = meta.call(
        "POST",
        meta.account_path("adsets"),
        {
            "name": f"{name}_세트",
            "campaign_id": campaign["id"],
            "daily_budget": config["daily_budget_cents"],
            "billing_event": BILLING_EVENT,
            "optimization_goal": OPTIMIZATION_GOAL,
            # 자동 입찰. 입찰가를 우리가 정하지 않는다.
            # 이걸 안 적으면 메타가 "입찰 금액을 달라"며 거부한다(2026-07 기준).
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
            "promoted_object": json.dumps(
                {"pixel_id": config["pixel_id"], "custom_event_type": config["event_type"]}
            ),
            "targeting": json.dumps({"geo_locations": {"countries": [config["country"]]}}),
        },
    )
    meta.verify_paused(adset["id"])

    ad = meta.call(
        "POST",
        meta.account_path("ads"),
        {
            "name": f"{name}_광고",
            "adset_id": adset["id"],
            "creative": json.dumps({"creative_id": creative["id"]}),
        },
    )
    meta.verify_paused(ad["id"])

    print(f"  [세팅] {name}  캠페인 {campaign['id']}  (일시중지 확인됨)")
    return {
        "no": no,
        "name": name,
        "hook": item["hook"],
        "campaign_id": campaign["id"],
        "adset_id": adset["id"],
        "ad_id": ad["id"],
        # 보고서에 미리보기로 띄울 것. 영상이면 썸네일 주소.
        "image_path": item.get("image_path") or item.get("thumb_url", ""),
        "is_video": bool(item.get("video_id")),
    }
