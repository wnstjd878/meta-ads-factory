"""
== 운영 맥락 ==
실행 시점: factory.py 3단계
입력: 2단계가 만든 PNG 경로
출력: 이미지 해시 (메타가 발급하는 긴 문자열)
외부 의존: graph.facebook.com/act_xxx/adimages (시스템 사용자 토큰 필요)
의도적 미구현:
  - 공식 연결(MCP)로 올리기. 그 도구가 아예 없다("not yet supported").
    그래서 이 프로젝트가 토큰을 쓴다. 나중에 메타가 열어주면 여기를 갈아끼운다.
재시작 정책: 실패 시 그 장만 건너뜀. 이미 올라간 이미지는 해시가 같아 중복 안 생김.
마지막 점검: 2026-07-09

이 단계가 소재 공장의 급소다. 여기가 막히면 뒤가 전부 무의미하다.
"""

from pathlib import Path

import meta


def run(made: list[dict]) -> list[dict]:
    out = []
    for item in made:
        path = Path(item["image_path"])
        with path.open("rb") as f:
            res = meta.call(
                "POST",
                meta.account_path("adimages"),
                payload={},
                files={"filename": (path.name, f, "image/png")},
            )

        image_hash = _extract_hash(res, path.name)
        out.append({**item, "image_hash": image_hash})
        print(f"  [올림] {path.name} -> {image_hash[:12]}...")

    return out


def run_videos(made: list[dict]) -> list[dict]:
    """영상을 올린다. 이미지와 다른 점 두 가지.

    1. 올린 뒤 메타가 인코딩을 끝낼 때까지 기다려야 한다(몇 분).
    2. 썸네일이 필요하다. 메타가 만들어준 것을 그대로 쓴다.
    """
    out = []
    for item in made:
        path = Path(item["video_path"])
        print(f"  [올리는 중] {path.name} ({path.stat().st_size / 1_000_000:.1f} MB)")

        with path.open("rb") as f:
            res = meta.call(
                "POST",
                meta.account_path("advideos"),
                payload={"name": path.stem},
                files={"source": (path.name, f, "video/mp4")},
            )

        video_id = res.get("id")
        if not video_id:
            raise RuntimeError(f"영상 번호를 못 받았다: {res}")

        thumb_url = meta.wait_video_ready(video_id)
        out.append({**item, "video_id": video_id, "thumb_url": thumb_url})
        print(f"  [올림] {path.name} -> 영상 {video_id}")

    return out


def _extract_hash(res: dict, filename: str) -> str:
    """메타 응답 모양: {"images": {"파일명": {"hash": "...", "url": "..."}}}"""
    images = res.get("images") or {}
    if filename in images:
        return images[filename]["hash"]
    # 파일명이 바뀌어 돌아오는 경우가 있어 첫 항목을 쓴다.
    for v in images.values():
        if "hash" in v:
            return v["hash"]
    raise RuntimeError(f"이미지 해시를 못 받았다: {res}")
