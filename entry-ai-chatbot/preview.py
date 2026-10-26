#!/usr/bin/env python3
"""시뮬레이터로 대화를 돌린 뒤, 글상자들의 상태(위치·정렬·색·글자)를 그대로 그려 preview.png 를 만든다.

엔트리 화면을 캡처한 것이 아니라 project.json 의 글상자 설정으로 다시 그린 '미리보기'다.
(글꼴은 저장소에 있는 나눔스퀘어로 대신한다. 입력창 모양은 엔트리 것과 비슷하게만 그린다.)

필요: node + playwright (이 작업 환경에는 설치되어 있음)
사용법: python3 preview.py  →  preview.png
"""
import html
import json
import os
import re
import subprocess
import tempfile

from simulate import Session

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1.6  # 무대 480×270 을 몇 배로 그릴지


def font_faces():
    """저장소의 index.html 에 들어 있는 나눔스퀘어 @font-face 를 가져온다."""
    path = os.path.join(HERE, "..", "index.html")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return ""
    return "\n".join(re.findall(r"@font-face\s*\{[^}]*\}", src))


def stage_html(session, caption, show_input=True):
    parts = []
    objects = session.p["objects"]
    for z, o in enumerate(objects):
        st = session.objs[o["id"]]
        if not st["visible"]:
            continue
        e = st["entity"]
        size = e["fontSize"] * S
        bold = "bold" in e["font"]
        weight = 800 if ("jalnan" in e["font"] or bold) else 400
        bg = st["bg"] if (st["bg"] or "").startswith("#") else "transparent"
        text = html.escape(st["text"])
        style = (f"position:absolute;z-index:{len(objects) - z};color:{st['fg']};background:{bg};"
                 f"font-size:{size:.1f}px;font-weight:{weight};white-space:pre;")
        if e["lineBreak"]:
            w, h = e["width"] * S, e["height"] * S
            left, top = (240 + e["x"]) * S - w / 2, (135 - e["y"]) * S - h / 2
            align = ["center", "left", "right"][e["textAlign"]]
            style += f"left:{left:.1f}px;top:{top:.1f}px;width:{w:.1f}px;height:{h:.1f}px;text-align:{align};"
        else:
            h = e["height"] * S
            left, top = (240 + e["x"]) * S, (135 - e["y"]) * S - h / 2
            shift = ["-50%", "0", "-100%"][e["textAlign"]]
            style += (f"left:{left:.1f}px;top:{top:.1f}px;height:{h:.1f}px;line-height:{h:.1f}px;"
                      f"transform:translateX({shift});")
        parts.append(f'<div style="{style}">{text}</div>')
    if show_input:
        # 엔트리 입력창: 캔버스(640×360) 기준 x=15, y=275, 너비 520 + 안쪽 여백
        k = 0.75 * S
        parts.append(f'<div class="input" style="left:{15 * k:.1f}px;top:{275 * k:.1f}px;width:{550 * k:.1f}px;'
                     f'height:{52 * k:.1f}px;border-radius:{10 * k:.1f}px"></div>'
                     f'<div class="submit" style="left:{(15 + 556) * k:.1f}px;top:{279 * k:.1f}px;'
                     f'width:{44 * k:.1f}px;height:{44 * k:.1f}px"></div>')
    return (f'<figure><div class="stage" style="width:{480 * S}px;height:{270 * S}px">{"".join(parts)}</div>'
            f'<figcaption>{html.escape(caption)}</figcaption></figure>')


def page(stages):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
body {{ margin:0; padding:24px; background:#E2E8F0; font-family:"NanumSquare","WenQuanYi Zen Hei",sans-serif;
        display:flex; flex-wrap:wrap; gap:24px; }}
.stage {{ position:relative; overflow:hidden; background:#FFFFFF; border-radius:10px;
          box-shadow:0 4px 18px rgba(15,23,42,.18); font-family:"NanumSquare","WenQuanYi Zen Hei",sans-serif; }}
.input {{ position:absolute; z-index:99; border:2px solid #e2e2e2; background:#fff; box-sizing:border-box; }}
.submit {{ position:absolute; z-index:99; border-radius:50%; background:#4f80ff; }}
figure {{ margin:0; }}
figcaption {{ margin-top:8px; color:#334155; font-size:15px; }}
</style></head><body>{''.join(stages)}</body></html>"""


def main():
    project = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))
    server = {}
    first = Session(project, server, username="minsu01", nickname="민수", seed=3, inputs=[
        "오늘 시험 망쳤어", "수학", "나 고양이 키워", "나비",
    ]).run()
    again = Session(project, server, username="minsu01", nickname="민수", seed=4, inputs=[
        "나비가 요즘 밥을 안 먹어",
    ]).run()
    stages = [stage_html(first, "① 처음 대화: 공감하고, 되묻고, 들은 걸 기억해요"),
              stage_html(again, "② 다시 접속: 지난 대화를 보여 주고, 기억한 '나비'를 알아봐요")]
    with tempfile.TemporaryDirectory() as tmp:
        page_path = os.path.join(tmp, "preview.html")
        open(page_path, "w", encoding="utf-8").write(page(stages))
        out = os.path.join(HERE, "preview.png")
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            "const p = await b.newPage({ viewport: { width: 1640, height: 520 }, deviceScaleFactor: 1.5 });"
            f"await p.goto('file://{page_path}'); await p.waitForTimeout(400);"
            f"await p.screenshot({{ path: '{out}', fullPage: true }}); await b.close(); }})();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
