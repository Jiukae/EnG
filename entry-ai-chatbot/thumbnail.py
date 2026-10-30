#!/usr/bin/env python3
"""작품 대표 이미지(썸네일) thumbnail.png 를 16:9 로 만든다.

글자는 '엔봇'과 '기억하는 AI 친구' 두 줄, 그림은 로봇 하나만 둔 단순한 디자인.
작품 목록에서 작게 보여도 알아보도록 큰 모양만 쓴다. 1280×720 으로 그리고 1.5배(1920×1080)로 저장한다.
필요: node + playwright (이 작업 환경에는 설치되어 있음)
사용법: python3 thumbnail.py  →  thumbnail.png
"""
import os
import subprocess
import tempfile

from preview import font_faces

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720
SCALE = 1.5

ROBOT = """<svg class="robot" viewBox="0 0 400 400" aria-hidden="true">
  <defs>
    <radialGradient id="halo" cx="50%" cy="50%" r="50%">
      <stop offset="0" stop-color="#A5B4FC" stop-opacity=".55"/>
      <stop offset="1" stop-color="#A5B4FC" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="head" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#FFFFFF"/>
      <stop offset="1" stop-color="#DDE3FF"/>
    </linearGradient>
    <linearGradient id="screen" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#2E2A78"/>
      <stop offset="1" stop-color="#17143F"/>
    </linearGradient>
    <radialGradient id="bulb" cx="40%" cy="35%" r="65%">
      <stop offset="0" stop-color="#FFFBEB"/>
      <stop offset="1" stop-color="#FBBF24"/>
    </radialGradient>
    <filter id="shadow" x="-30%" y="-30%" width="160%" height="170%">
      <feDropShadow dx="0" dy="22" stdDeviation="22" flood-color="#0B0930" flood-opacity=".45"/>
    </filter>
    <filter id="glow" filterUnits="userSpaceOnUse" x="0" y="0" width="400" height="400">
      <feGaussianBlur stdDeviation="7" result="b"/>
      <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
    </filter>
  </defs>
  <circle cx="200" cy="215" r="196" fill="url(#halo)"/>
  <rect x="191" y="46" width="18" height="52" rx="9" fill="#E0E7FF"/>
  <circle cx="200" cy="42" r="21" fill="url(#bulb)" filter="url(#glow)"/>
  <g filter="url(#shadow)">
    <rect x="30" y="172" width="40" height="96" rx="20" fill="#A5B4FC"/>
    <rect x="330" y="172" width="40" height="96" rx="20" fill="#A5B4FC"/>
    <rect x="58" y="88" width="284" height="262" rx="96" fill="url(#head)"/>
  </g>
  <rect x="94" y="138" width="212" height="160" rx="64" fill="url(#screen)"/>
  <path d="M118 176 Q136 150 172 146" stroke="#FFFFFF" stroke-opacity=".14" stroke-width="10" fill="none"
        stroke-linecap="round"/>
  <g filter="url(#glow)" fill="#67E8F9">
    <rect x="140" y="186" width="36" height="50" rx="18"/>
    <rect x="224" y="186" width="36" height="50" rx="18"/>
  </g>
  <circle cx="152" cy="200" r="6" fill="#FFFFFF"/>
  <circle cx="236" cy="200" r="6" fill="#FFFFFF"/>
  <ellipse cx="124" cy="256" rx="15" ry="9" fill="#F472B6" fill-opacity=".45"/>
  <ellipse cx="276" cy="256" rx="15" ry="9" fill="#F472B6" fill-opacity=".45"/>
  <path d="M180 260 Q200 276 220 260" stroke="#67E8F9" stroke-width="8" fill="none" stroke-linecap="round"
        filter="url(#glow)"/>
</svg>"""

BUBBLE = """<svg class="bubble" viewBox="0 0 190 130" aria-hidden="true">
  <defs>
    <filter id="bshadow" x="-20%" y="-20%" width="140%" height="160%">
      <feDropShadow dx="0" dy="10" stdDeviation="12" flood-color="#0B0930" flood-opacity=".35"/>
    </filter>
  </defs>
  <g filter="url(#bshadow)">
    <rect x="10" y="10" width="170" height="92" rx="46" fill="#FFFFFF"/>
    <path d="M128 96 L162 124 L150 92 Z" fill="#FFFFFF"/>
  </g>
  <circle cx="58" cy="56" r="11" fill="#6366F1"/>
  <circle cx="95" cy="56" r="11" fill="#818CF8"/>
  <circle cx="132" cy="56" r="11" fill="#A5B4FC"/>
</svg>"""


def page(cover=False):
    """cover=True 면 작품 첫 화면(표지)용: 글을 조금 위로 올려 '시작하기' 버튼 자리를 비운다."""
    top = "43%" if cover else "50%"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
* {{ box-sizing: border-box; margin: 0; }}
body {{ width: {W}px; height: {H}px; overflow: hidden; font-family: "NanumSquare", sans-serif; }}
.stage {{ position: relative; width: {W}px; height: {H}px; overflow: hidden;
          background: radial-gradient(900px 700px at 74% 52%, #6D6AF7 0%, #4F46E5 38%, #3730A3 68%, #1E1B4B 100%); }}
.text {{ position: absolute; left: 112px; top: {top}; transform: translateY(-54%); color: #FFFFFF; }}
h1 {{ font-size: 212px; font-weight: 900; letter-spacing: -8px; line-height: .95;
      text-shadow: 0 14px 40px rgba(11, 9, 48, .35); }}
p {{ margin-top: 34px; font-size: 54px; font-weight: 800; letter-spacing: -1px; color: #C7D2FE; }}
.robot {{ position: absolute; width: 520px; height: 520px; left: 690px; top: 132px; }}
.bubble {{ position: absolute; width: 190px; height: 130px; left: 642px; top: 92px; }}
</style></head><body><div class="stage">
  <div class="text"><h1>엔봇</h1><p>기억하는 AI 친구</p></div>
  {ROBOT}
  {BUBBLE}
</div></body></html>"""


def main():
    out = os.path.join(HERE, "thumbnail.png")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = os.path.join(tmp, "thumbnail.html")
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(page())
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            f"const p = await b.newPage({{ viewport: {{ width: {W}, height: {H} }}, deviceScaleFactor: {SCALE} }});"
            f"await p.goto('file://{page_path}'); await p.evaluate(() => document.fonts.ready);"
            f"await p.waitForTimeout(300); await p.screenshot({{ path: '{out}' }}); await b.close(); }})();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
