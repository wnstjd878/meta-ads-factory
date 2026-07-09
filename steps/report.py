"""
== 운영 맥락 ==
실행 시점: factory.py 5단계. 알림보다 먼저. 항상 만든다.
입력: 4단계 결과 (캠페인 번호, 카피, 그림 경로)
출력: out/보고서.html  (더블클릭하면 열림)
외부 의존: 없음. 열쇠도 인터넷도 필요 없다.
의도적 미구현:
  - 켜기 버튼. 광고 관리자에서 눈으로 보고 켠다.
  - 외부 폰트/이미지 불러오기. 인터넷 없이 열려야 한다. 그림은 파일 경로로 건다.
재시작 정책: 없음. 실패해도 앞 단계 결과는 남는다.
마지막 점검: 2026-07-09

왜 있나:
  새벽에 혼자 돌고 나면 아침에 뭘 봐야 하는지 알아야 한다. 이 파일이 그 창구다.
  알림 서비스를 붙이지 않은 이유: 열쇠를 하나 더 발급받게 만들면 그것 때문에
  포기하는 사람이 생긴다. 파일 하나 여는 게 낫다.
"""

from html import escape
from pathlib import Path

CSS = """
:root { --bg:#fff; --ink:#111; --dim:#6b6b6b; --line:#e4e4e4; --accent:#e63946; }
* { box-sizing: border-box; }
body { margin:0; padding:48px 24px; background:var(--bg); color:var(--ink);
  font-family:"Pretendard","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
  line-height:1.6; }
.wrap { max-width:960px; margin:0 auto; }
h1 { font-size:32px; letter-spacing:-0.02em; margin:0 0 6px; font-weight:800; }
.sub { color:var(--dim); font-size:15px; margin:0 0 8px; }
.warn { display:inline-block; margin:16px 0 40px; padding:10px 16px;
  border-left:4px solid var(--accent); background:#fdf2f3; font-weight:600; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(280px,1fr)); gap:28px; }
.card { border:1px solid var(--line); }
.card img { width:100%; display:block; background:#f5f5f5; }
.body { padding:16px 18px 20px; }
.no { font-size:13px; color:var(--accent); font-weight:800; letter-spacing:0.04em; }
.hook { font-size:17px; font-weight:700; margin:6px 0 10px; letter-spacing:-0.01em; }
.meta { font-size:12px; color:var(--dim); font-family:ui-monospace,Menlo,Consolas,monospace;
  word-break:break-all; }
.foot { margin-top:48px; padding-top:20px; border-top:1px solid var(--line);
  color:var(--dim); font-size:13px; }
"""


def run(results: list[dict], account_name: str, out_dir: Path, stamp: str) -> Path:
    cards = []
    for r in results:
        # 이미지는 내 컴퓨터 파일, 영상은 메타가 만들어준 썸네일 주소.
        src = r["image_path"]
        img = src if src.startswith("http") else Path(src).resolve().as_uri()
        badge = " · 영상" if r.get("is_video") else ""
        cards.append(f"""
    <div class="card">
      <img src="{img}" alt="">
      <div class="body">
        <div class="no">{r['no']:02d} · {escape(r['name'].split('_')[-1])}{badge}</div>
        <div class="hook">{escape(r['hook'])}</div>
        <div class="meta">캠페인 {r['campaign_id']}</div>
      </div>
    </div>""")

    html = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<title>새 소재 {len(results)}개 · {escape(account_name)}</title>
<style>{CSS}</style></head>
<body><div class="wrap">
  <h1>새 소재 {len(results)}개</h1>
  <p class="sub">{escape(account_name)} · {escape(stamp)}</p>
  <div class="warn">전부 꺼진 상태입니다. 지출 0원. 켤 것만 광고 관리자에서 켜세요.</div>
  <div class="grid">{''.join(cards)}
  </div>
  <p class="foot">
    그림이 이상하게 나온 건 켜지 마세요. 다시 뽑는 게 빠릅니다.<br>
    이 파일은 인터넷 없이도 열립니다. 그림은 out/images 폴더를 참조합니다.
  </p>
</div></body></html>"""

    path = out_dir / "보고서.html"
    path.write_text(html, encoding="utf-8")
    return path
