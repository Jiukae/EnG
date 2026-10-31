#!/usr/bin/env python3
"""시뮬레이터로 대화를 돌린 뒤, 글상자·그림 오브젝트의 상태(위치·정렬·색·글자·모양)를 그대로 그려 preview.png 를 만든다.

엔트리 화면을 캡처한 것이 아니라 project.json 의 오브젝트 설정으로 다시 그린 '미리보기'다.
(글꼴은 저장소에 있는 나눔스퀘어로 대신한다. 아래 입력창은 작품 속 글상자다 — 엔트리 '묻고 기다리기' 는 쓰지 않는다.)

필요: node + playwright (이 작업 환경에는 설치되어 있음)
사용법: python3 preview.py  →  preview.png
"""
import base64
import html
import json
import os
import re
import subprocess
import tempfile

from simulate import Session, keys_for

HERE = os.path.dirname(os.path.abspath(__file__))
S = 1.6  # 무대 480×270 을 몇 배로 그릴지


def picture_src(name):
    """모양 이름 → assets/<이름>.png 를 data: 주소로"""
    with open(os.path.join(HERE, "assets", f"{name}.png"), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def font_faces():
    """저장소의 index.html 에 들어 있는 나눔스퀘어 @font-face 를 가져온다."""
    path = os.path.join(HERE, "..", "index.html")
    try:
        src = open(path, encoding="utf-8").read()
    except OSError:
        return ""
    return "\n".join(re.findall(r"@font-face\s*\{[^}]*\}", src))


def stage_html(session, caption):
    parts = []
    objects = session.p["objects"]
    for z, o in enumerate(objects):
        st = session.objs[o["id"]]
        if not st["visible"]:
            continue
        e = st["entity"]
        if st["pictures"]:   # 그림 오브젝트: 가운데가 (x, y)
            name = next(p["name"] for p in st["pictures"] if p["id"] == st["picture"])
            w, h = e["width"] * e["scaleX"] * S, e["height"] * e["scaleY"] * S
            left, top = (240 + e["x"]) * S - w / 2, (135 - e["y"]) * S - h / 2
            parts.append(f'<img src="{picture_src(name)}" style="position:absolute;z-index:{len(objects) - z};'
                         f'left:{left:.1f}px;top:{top:.1f}px;width:{w:.1f}px;height:{h:.1f}px">')
            continue
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
            style += (f"left:{left:.1f}px;top:{top:.1f}px;width:{w:.1f}px;height:{h:.1f}px;text-align:{align};"
                      f"line-height:1.25;overflow:hidden;")
            if e["height"] <= 30:   # 낮은 칸(버튼·대화 칸)은 글을 세로 가운데에
                style += "display:flex;flex-direction:column;justify-content:center;"
        else:
            h = e["height"] * S
            left, top = (240 + e["x"]) * S, (135 - e["y"]) * S - h / 2
            shift = ["-50%", "0", "-100%"][e["textAlign"]]
            style += (f"left:{left:.1f}px;top:{top:.1f}px;height:{h:.1f}px;line-height:{h:.1f}px;"
                      f"transform:translateX({shift});")
        parts.append(f'<div style="{style}">{text}</div>')
    return (f'<figure><div class="stage" style="width:{480 * S}px;height:{270 * S}px">{"".join(parts)}</div>'
            f'<figcaption>{html.escape(caption)}</figcaption></figure>')


def page(stages):
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
body {{ margin:0; padding:24px; background:#E2E8F0; font-family:"NanumSquare","WenQuanYi Zen Hei",sans-serif;
        display:flex; flex-wrap:wrap; gap:24px; }}
.stage {{ position:relative; overflow:hidden; background:#FFFFFF; border-radius:10px;
          box-shadow:0 4px 18px rgba(15,23,42,.18); font-family:"NanumSquare","WenQuanYi Zen Hei",sans-serif; }}
figure {{ margin:0; }}
figcaption {{ margin-top:8px; color:#334155; font-size:15px; }}
</style></head><body>{''.join(stages)}</body></html>"""


def main():
    project = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))
    server = {}
    user = dict(username="minsu01", nickname="민수")
    cover = Session(project, {}, **user)   # ▶ 시작 전
    Session(project, server, **user, seed=2, inputs=["오늘 수학 시험 망쳤어", ("click", "저장1")]).run()
    first = Session(project, server, **user, seed=3, inputs=[
        ("click", "새대화버튼"), "나 고양이 키워", "나비", ("click", "저장1"),
        ("keys", [(c, sh) for c, sh, _ in keys_for("나비는 생선을 좋아하")]),   # 치는 중 (Enter 전)
    ]).run()
    again = Session(project, server, **user, seed=4, inputs=[
        "나비가 요즘 밥을 안 먹어", ("click", "대화칸2"),
    ]).run()
    stages = [stage_html(cover, "① 멈춰 있을 때: 표지 (▶ 시작하면 바로 사라지고 챗봇이 시작돼요)"),
              stage_html(first, "② 아래 입력창에 키보드로 바로 입력 — 한글 조합 중 · Enter ⏎ 로 보내기"),
              stage_html(again, "③ 다시 접속: 저장한 대화들이 왼쪽에 — 칸을 누르면 그 대화로 바뀌어요")]
    with tempfile.TemporaryDirectory() as tmp:
        page_path = os.path.join(tmp, "preview.html")
        open(page_path, "w", encoding="utf-8").write(page(stages))
        out = os.path.join(HERE, "preview.png")
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            "const p = await b.newPage({ viewport: { width: 1640, height: 900 }, deviceScaleFactor: 1.5 });"
            f"await p.goto('file://{page_path}'); await p.waitForTimeout(400);"
            f"await p.screenshot({{ path: '{out}', fullPage: true }}); await b.close(); }})();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
