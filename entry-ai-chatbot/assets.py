#!/usr/bin/env python3
"""작품 속 그림을 만든다 (assets/*.png). 모두 직접 그린 그림이다.

  표지.png        첫 화면 (대표 이미지와 같은 디자인, 960×540 → 무대에서 0.5배)
  시작하기.png    표지 위 '시작하기' 버튼 (480×136 → 0.25배)
  저장하기.png    왼쪽 대화 칸의 저장 아이콘: 아직 저장 안 됨 (64×64 → 0.25배)
  저장됨.png      저장 아이콘: 저장됨
  썸네일/*.png    엔트리 오브젝트 목록에 보이는 작은 그림

필요: node + playwright, Pillow
사용법: python3 assets.py
"""
import os
import subprocess
import tempfile

from PIL import Image

from preview import font_faces
from thumbnail import H, W, page as cover_page

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "assets")

START_BUTTON = """<div class="btn"><span class="play"><svg viewBox="0 0 24 24" width="40" height="40">
  <path d="M8 5.5 L19 12 L8 18.5 Z" fill="#FFFFFF" stroke="#FFFFFF" stroke-width="2.4" stroke-linejoin="round"/>
</svg></span>시작하기</div>"""


def disk(body, label, shutter, badge):
    """플로피 디스크 모양 저장 아이콘 (64×64). badge 는 오른쪽 위 작은 표시."""
    return f"""<svg viewBox="0 0 64 64" width="64" height="64" xmlns="http://www.w3.org/2000/svg">
  <path d="M12 8 H44 L54 18 V50 Q54 56 48 56 H16 Q10 56 10 50 V14 Q10 8 16 8 Z" fill="{body}"/>
  <rect x="19" y="8" width="20" height="13" rx="2" fill="{shutter}"/>
  <rect x="32" y="10.5" width="4" height="8" rx="1" fill="{body}"/>
  <rect x="17" y="33" width="30" height="17" rx="3" fill="{label}"/>
  <rect x="21" y="38" width="22" height="2.6" rx="1.3" fill="{body}" opacity=".45"/>
  <rect x="21" y="43.5" width="15" height="2.6" rx="1.3" fill="{body}" opacity=".45"/>
  {badge}
</svg>"""


ICONS = {
    # 아직 저장 안 됨: 흰 디스크 + 노란 점
    "저장하기": disk("#E0E7FF", "#FFFFFF", "#818CF8",
                     '<circle cx="51" cy="13" r="10" fill="#1E1B4B"/><circle cx="51" cy="13" r="7" fill="#FBBF24"/>'),
    # 저장됨: 초록 디스크 + 체크
    "저장됨": disk("#6EE7B7", "#ECFDF5", "#10B981",
                   '<circle cx="50" cy="14" r="11" fill="#1E1B4B"/><circle cx="50" cy="14" r="8.5" fill="#10B981"/>'
                   '<path d="M45.5 14.2 L48.8 17.4 L54.6 11" stroke="#FFFFFF" stroke-width="2.6" fill="none" '
                   'stroke-linecap="round" stroke-linejoin="round"/>'),
}


def shot(html, out, width, height, scale=1.0, transparent=False):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "page.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(html)
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            f"const p = await b.newPage({{ viewport: {{ width: {width}, height: {height} }}, deviceScaleFactor: {scale} }});"
            f"await p.goto('file://{path}'); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(200);"
            f"await p.screenshot({{ path: '{out}', omitBackground: {'true' if transparent else 'false'} }});"
            "await b.close(); })();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


def small_page(body, width, height, css=""):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
* {{ box-sizing: border-box; margin: 0; }}
html, body {{ width: {width}px; height: {height}px; background: transparent; overflow: hidden; }}
body {{ display: flex; align-items: center; justify-content: center; font-family: "NanumSquare", sans-serif; }}
{css}
</style></head><body>{body}</body></html>"""


def main():
    os.makedirs(os.path.join(OUT, "썸네일"), exist_ok=True)
    shot(cover_page(cover=True), os.path.join(OUT, "표지.png"), W, H, scale=0.75)
    shot(small_page(START_BUTTON, 240, 68, """
.btn {{ display: flex; align-items: center; gap: 14px; height: 52px; padding: 0 30px 0 8px; border-radius: 26px;
        background: #FFFFFF; color: #4338CA; font-size: 27px; font-weight: 900; letter-spacing: -.5px;
        box-shadow: 0 6px 14px rgba(11, 9, 48, .35); }}
.play {{ display: flex; align-items: center; justify-content: center; width: 38px; height: 38px; border-radius: 50%;
         background: #4F46E5; }}
.play svg {{ width: 22px; height: 22px; margin-left: 3px; }}
""".replace("{{", "{").replace("}}", "}")), os.path.join(OUT, "시작하기.png"), 240, 68, scale=2, transparent=True)
    for name, svg in ICONS.items():
        shot(small_page(svg, 64, 64), os.path.join(OUT, f"{name}.png"), 64, 64, transparent=True)
    for name in ["표지", "시작하기", *ICONS]:
        im = Image.open(os.path.join(OUT, f"{name}.png"))
        im.thumbnail((96, 96))
        im.save(os.path.join(OUT, "썸네일", f"{name}.png"))


if __name__ == "__main__":
    main()
