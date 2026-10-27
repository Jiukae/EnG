#!/usr/bin/env python3
"""작품 대표 이미지(썸네일) thumbnail.png 를 16:9 (1280×720) 로 만든다.

오른쪽 대화는 지어낸 문장이 아니라 시뮬레이터로 작품을 실제로 돌려 나온 대화다.
필요: node + playwright (이 작업 환경에는 설치되어 있음)
사용법: python3 thumbnail.py  →  thumbnail.png
"""
import html
import json
import os
import subprocess
import tempfile

from preview import font_faces
from simulate import Session

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1280, 720

ROBOT = """<svg viewBox="0 0 120 120" width="132" height="132" aria-hidden="true">
  <line x1="60" y1="10" x2="60" y2="26" stroke="#FDE68A" stroke-width="6" stroke-linecap="round"/>
  <circle cx="60" cy="10" r="8" fill="#FDE68A"/>
  <rect x="14" y="26" width="92" height="78" rx="26" fill="#FFFFFF"/>
  <rect x="26" y="42" width="68" height="40" rx="18" fill="#312E81"/>
  <circle cx="45" cy="60" r="7" fill="#A5F3FC"/>
  <circle cx="75" cy="60" r="7" fill="#A5F3FC"/>
  <path d="M48 92 Q60 100 72 92" stroke="#6366F1" stroke-width="5" fill="none" stroke-linecap="round"/>
  <rect x="2" y="52" width="12" height="26" rx="6" fill="#C7D2FE"/>
  <rect x="106" y="52" width="12" height="26" rx="6" fill="#C7D2FE"/>
</svg>"""


def conversation():
    s = Session(json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8")), {},
                username="minsu01", nickname="민수", seed=2,
                inputs=["오늘 시험 망쳤어", "나 고양이 키워", "나비"]).run()
    return [(tag, text) for tag, text, _ in s.transcript_lines()[1:] if tag in ("나", "봇")]


def page(lines):
    bubbles = "".join(
        f'<div class="row {"me" if tag == "나" else "bot"}"><div class="bubble">{html.escape(text)}</div></div>'
        for tag, text in lines)
    chips = "".join(f'<span class="chip"><b>{icon}</b>{html.escape(text)}</span>' for icon, text in [
        ("💬", "공감하고 되묻는 대화"), ("🧠", "나를 기억해요"), ("📋", "대화 기록 정리"), ("🔒", "개인정보 보호")])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
* {{ box-sizing: border-box; margin: 0; }}
body {{ width: {W}px; height: {H}px; overflow: hidden; font-family: "NanumSquare", "Noto Color Emoji", sans-serif; }}
.stage {{ position: relative; width: {W}px; height: {H}px; padding: 64px 72px;
          background: radial-gradient(circle at 18% 20%, #6D5DF6 0%, #4F46E5 38%, #3730A3 100%);
          display: flex; align-items: center; gap: 56px; color: #FFFFFF; }}
.stage::before {{ content: ""; position: absolute; inset: 0;
                  background-image: radial-gradient(rgba(255,255,255,.10) 2px, transparent 2px);
                  background-size: 28px 28px; }}
.left {{ position: relative; flex: 1 1 0; }}
.brand {{ display: flex; align-items: center; gap: 22px; }}
h1 {{ font-size: 124px; font-weight: 900; letter-spacing: -2px; line-height: 1; }}
.sub {{ margin-top: 22px; font-size: 40px; font-weight: 800; color: #E0E7FF; }}
.tag {{ margin-top: 14px; font-size: 25px; font-weight: 400; color: #C7D2FE; }}
.chips {{ margin-top: 36px; display: flex; flex-wrap: wrap; gap: 12px; max-width: 560px; }}
.chip {{ display: inline-flex; align-items: center; gap: 10px; padding: 12px 20px; border-radius: 999px;
         background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.28);
         font-size: 23px; font-weight: 700; color: #FFFFFF; }}
.chip b {{ font-family: "Noto Color Emoji"; font-weight: 400; }}
.made {{ margin-top: 34px; font-size: 20px; color: #A5B4FC; }}
.made strong {{ color: #FDE68A; font-weight: 800; }}
.card {{ position: relative; flex: 0 0 480px; height: 592px; border-radius: 34px; background: #F1F5F9;
         box-shadow: 0 30px 60px rgba(15, 12, 60, .45); overflow: hidden; display: flex; flex-direction: column; }}
.head {{ display: flex; align-items: center; gap: 12px; padding: 20px 26px; background: #FFFFFF;
         border-bottom: 1px solid #E2E8F0; color: #1E293B; font-size: 24px; font-weight: 800; }}
.dot {{ width: 12px; height: 12px; border-radius: 50%; background: #34D399; }}
.head small {{ margin-left: auto; font-size: 17px; font-weight: 400; color: #64748B; }}
.chat {{ flex: 1; min-height: 0; padding: 18px 22px 14px; display: flex; flex-direction: column;
         justify-content: flex-end; gap: 10px; }}
.row {{ display: flex; }}
.row.me {{ justify-content: flex-end; }}
.bubble {{ max-width: 84%; padding: 11px 17px; font-size: 20px; line-height: 1.42; border-radius: 22px;
           word-break: keep-all; }}
.bot .bubble {{ background: #FFFFFF; color: #1E293B; border-bottom-left-radius: 6px;
                box-shadow: 0 2px 6px rgba(15, 23, 42, .08); }}
.me .bubble {{ background: #4F46E5; color: #FFFFFF; border-bottom-right-radius: 6px; font-weight: 700; }}
.input {{ flex: 0 0 auto; margin: 0 22px 20px; height: 52px; border-radius: 27px; background: #FFFFFF; border: 2px solid #E2E8F0;
          display: flex; align-items: center; padding: 0 8px 0 22px; color: #94A3B8; font-size: 19px; }}
.input span {{ margin-left: auto; width: 40px; height: 40px; border-radius: 50%; background: #4F46E5; }}
</style></head><body><div class="stage">
  <div class="left">
    <div class="brand">{ROBOT}<h1>엔봇</h1></div>
    <div class="sub">기억하는 AI 친구</div>
    <div class="tag">이야기를 듣고, 공감하고, 다음에도 기억해요</div>
    <div class="chips">{chips}</div>
    <div class="made"><strong>엔트리</strong> 블록 코딩으로 만든 챗봇</div>
  </div>
  <div class="card">
    <div class="head"><span class="dot"></span>엔봇<small>민수님과 대화 중</small></div>
    <div class="chat">{bubbles}</div>
    <div class="input">메시지를 입력하세요<span></span></div>
  </div>
</div></body></html>"""


def main():
    out = os.path.join(HERE, "thumbnail.png")
    with tempfile.TemporaryDirectory() as tmp:
        page_path = os.path.join(tmp, "thumbnail.html")
        open(page_path, "w", encoding="utf-8").write(page(conversation()))
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            f"const p = await b.newPage({{ viewport: {{ width: {W}, height: {H} }}, deviceScaleFactor: 1 }});"
            f"await p.goto('file://{page_path}'); await p.waitForTimeout(500);"
            f"await p.screenshot({{ path: '{out}' }}); await b.close(); }})();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
