#!/usr/bin/env python3
"""테스트를 실제로 돌리고, 결과를 그림 두 장으로 만든다.

test_results/테스트결과.png : test_chatbot.py 의 검사 76개를 기능별로 묶어 통과/실패를 보여 준다.
test_results/대화결과.png   : 새 기능을 시뮬레이터로 돌린 대화를 작품 화면 모양으로 다시 그린 것.

둘 다 실제 엔트리 화면이 아니라, 엔트리 블록 동작을 옮긴 시뮬레이터(simulate.py)로 얻은 결과다.
필요: node + playwright (이 작업 환경에는 설치되어 있음)
사용법: python3 test_report.py
"""
import datetime
import html
import json
import os
import subprocess
import tempfile
import time
import unittest

import test_chatbot
from preview import font_faces, page as stage_page, stage_html
from simulate import Session

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "test_results")

GROUPS = {
    "StructureTest": "작품 파일 구조", "ScreenTest": "화면 (글상자)", "ConversationTest": "대화와 생각하기",
    "StorageTest": "사용자별 저장", "CommandTest": "명령어", "RecordTest": "대화 기록 · 기록표",
    "BanmalTest": "반말 / 존댓말", "SmartTest": "계산 · 고르기 · 날짜", "WordChainTest": "끝말잇기",
    "RockPaperScissorsTest": "가위바위보", "SlangTest": "신조어 · 초성체", "PastTalkTest": "예전 대화 참고",
    "DefinitionTest": "단어 뜻 1,726개", "SafetyTest": "안전", "RobustnessTest": "아무 말에도 멈추지 않기",
}
LABELS = {
    "test_blocks_match_entry_schema": "모든 블록의 모양이 엔트리 블록 정의와 같아요",
    "test_threads_start_with_events": "모든 스크립트가 시작 블록으로 시작해요",
    "test_every_message_has_handler": "보내는 신호마다 받는 스크립트가 있어요",
    "test_project_fields": "작품 정보 · 변수 · 리스트 이름이 겹치지 않아요",
    "test_knowledge_lists": "지식 리스트가 글자 순서로 정렬돼 있어요",
    "test_knowledge_search_finds_every_key": "지식 3,511개를 이진 탐색으로 하나도 빠짐없이 찾아요",
    "test_tables": "대화기록표 테이블이 엔트리 저장 형식이에요",
    "test_table_blocks_only_in_two_functions": "테이블 블록은 기록표 함수 두 곳에만 있어요",
    "test_functions": "함수 61개가 엔트리 함수 형식이고 값 함수에 반복이 없어요",
    "test_ent_archive": ".ent 파일을 열면 project.json 이 들어 있어요",
    "test_batchim_tables": "받침 글자표가 맞아요",
    "test_bubbles": "말풍선 줄이 화면에 바르게 나와요",
    "test_thinking_row_removed": "'생각하는 중…' 줄이 대답 뒤에 사라져요",
    "test_reflects_and_follows_up": "내 말을 되받아 공감하고 되물어요",
    "test_no_canned_fallback": "뻔한 대답 하나만 되풀이하지 않아요",
    "test_learns_facts_from_story_and_recalls_next_visit": "이야기 속 사실을 기억했다가 다음에 떠올려요",
    "test_welcome_back_remembers_topic_and_mood": "다시 오면 지난 주제와 기분으로 인사해요",
    "test_learns_unknown_words_and_questions": "모르는 낱말과 질문은 물어보고 배워요",
    "test_does_not_ask_known_things": "이미 아는 것은 다시 묻지 않아요",
    "test_ignores_non_answers": "'몰라', '응' 같은 말은 대답으로 저장하지 않아요",
    "test_josa": "받침에 맞게 조사를 붙여요 (은/는, 이/가)",
    "test_name": "이름을 알려 주면 그 이름으로 불러요",
    "test_users_are_separate": "사용자마다 기억이 따로 저장돼요",
    "test_prefix_ids_do_not_collide": "비슷한 아이디끼리 섞이지 않아요",
    "test_guest_mode_saves_nothing": "로그인하지 않으면 저장하지 않아요",
    "test_history_is_trimmed": "서버에는 최근 대화 40줄만 남겨요",
    "test_saved_only_with_save_command": "/save 해야 다음에 들어와도 이어져요 (안 하면 남지 않아요)",
    "test_end_asks_to_save_first": "저장하지 않고 끝내려 하면 한 번 물어봐요",
    "test_new_clear_and_forget": "/new 새 대화 · /clear 기록 지우기 · /clear all · '잊어줘:'",
    "test_save_failure_is_reported": "저장에 실패하면 알려 줘요",
    "test_calculator": "'계산: 12*3' 이 맞게 계산해요",
    "test_translate_help_time": "번역 · 도움말 · 시각 · 종료",
    "test_every_line_is_recorded": "모든 말이 번호·날짜·시각·감정과 함께 기록돼요",
    "test_records_are_rebuilt_from_server_on_next_visit": "다시 오면 기록을 서버에서 되살려요",
    "test_old_history_format_is_read": "예전 저장 형식도 읽어요",
    "test_search_stats_and_text_view": "기록 검색 · 기록 통계 · 기록 보기",
    "test_clear_empties_records": "/clear 가 기록을 비워요",
    "test_works_when_tables_are_missing": "웹에서 불러와 테이블이 빠져도 오류 없이 돌아가요",
    "test_table_mirrors_records_when_turned_on": "기록표를 켜면 테이블에 똑같이 쌓여요",
    "test_table_keeps_up_when_old_records_are_trimmed": "오래된 줄을 지워도 기록표가 맞춰져요",
    "test_banmal_on_off_and_saved": "'반말 써' / '존댓말 써' 가 되고 다음에도 기억해요",
    "test_every_way_to_ask": "'반말해', '말 놓을게', '편하게 말해 줘' 도 알아들어요",
    "test_conversion": "엔봇이 하는 말과 뜻 풀이 4,400여 개를 반말로 바꿔도 높임말이 남지 않아요",
    "test_math_in_words": "'12 곱하기 3은?' 처럼 말로 계산해요",
    "test_choose": "'짜장면이랑 짬뽕 중에' 에서 하나를 골라요",
    "test_dice_coin_and_numbers": "주사위 · 동전 · 범위 안의 숫자",
    "test_times_table": "구구단 (7단, '9단 알려줘')",
    "test_recall_what_was_said": "'방금 내가 뭐라고 했어?' 에 그대로 대답해요",
    "test_dates": "디데이 · 생일까지 며칠 · 내일 무슨 요일",
    "test_dates_across_month_and_year": "달과 해가 바뀌고 윤년이어도 날짜가 맞아요",
    "test_play_several_rounds": "여러 번 주고받아도 규칙대로 이어요",
    "test_rules": "틀린 글자 · 한 글자 · 두음법칙 · 엔봇이 지는 경우",
    "test_hint_mentions_dueum": "'력' 또는 '역' 처럼 두음법칙 글자도 알려 줘요",
    "test_used_word": "이미 나온 말을 알아봐요",
    "test_sentence_leaves_the_game": "문장으로 말하면 놀이를 멈춰요",
    "test_rounds_and_score": "여러 판 하며 점수를 정확히 세요",
    "test_other_talk_leaves_the_game": "다른 이야기를 하면 놀이를 멈춰요",
    "test_replies": "야르 · ㅎㅇ · 킹받네 · 어쩔티비 · 헐 등에 알맞게 대답해요",
    "test_meanings": "'킹받다가 뭐야?' 처럼 신조어 뜻을 알려 줘요",
    "test_feelings_in_sentences": "'킹받았어', '개웃겼어', '잘 봤어' 의 감정을 알아채요",
    "test_not_saved_as_answer": "'어쩔티비', 'ㅇㅇ' 를 질문의 대답으로 저장하지 않아요",
    "test_chosung_yes_and_banmal_mode": "'ㅇㅇ' 는 '응', '반모' 는 반말 모드",
    "test_links_same_topic_across_days": "어제 한 말과 오늘 기분을 견줘서 대답해요",
    "test_same_feeling_and_banmal": "반말이어도 따옴표 속 내 말은 그대로예요",
    "test_ask_about_past": "'지난번에 무슨 얘기 했지?' 에 대답해요",
    "test_quiet_talk_brings_back_old_topic": "대화가 끊기면 지난 주제를 물어봐요",
    "test_saved_trimmed_and_private": "지난 이야기를 저장하고, 개인정보는 남기지 않아요",
    "test_bad_saved_lines_are_skipped": "망가진 저장 줄이 있어도 멈추지 않아요",
    "test_many_definitions": "단어 뜻이 1,700개가 넘고 겹치지 않아요",
    "test_every_word_alone_gets_its_meaning": "낱말 1,700여 개를 하나씩 말해도 모두 맞는 뜻이 나와요",
    "test_alone_with_josa_marks_and_banmal": "'장영실', '블랙홀!', '원숭이' 와 반말 모드",
    "test_topic_word_gets_follow_up_but_not_a_fact_question": "주제 낱말이면 뜻 다음에 이어 물어요",
    "test_one_word_answer_to_a_question_is_an_answer": "물어본 것에 낱말로 답하면 대답으로 받아요",
    "test_answers_and_memory_come_first": "기억한 이름 '나비', '수수께끼' 는 원래 대답",
    "test_questions_about_meaning": "'이순신 장군이 누구야?' 는 뜻, '내 친구 알아?' 는 아니에요",
    "test_private_info_is_not_remembered_or_logged": "비밀번호 · 전화번호는 기억하지도 기록하지도 않아요",
    "test_crisis_gets_help_numbers": "힘들다는 말에는 상담 전화(1388, 109)를 알려 줘요",
    "test_random_inputs_never_crash": "아무렇게나 섞은 말 120번에도 블록 오류가 없어요",
}


class Recorder(unittest.TestResult):
    def __init__(self):
        super().__init__()
        self.rows, self._start = [], 0

    def startTest(self, test):
        super().startTest(test)
        self._start = time.time()

    def _add(self, test, status, detail=""):
        self.rows.append((type(test).__name__, test._testMethodName, status, time.time() - self._start, detail))

    def addSuccess(self, test):
        super().addSuccess(test)
        self._add(test, "통과")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._add(test, "실패", str(err[1])[:200])

    def addError(self, test, err):
        super().addError(test, err)
        self._add(test, "오류", str(err[1])[:200])


def run_tests():
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_chatbot)
    result, start = Recorder(), time.time()
    suite.run(result)
    return result, time.time() - start


def screenshot(page_html, out, width, height=None):
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "page.html")
        with open(path, "w", encoding="utf-8") as f:
            f.write(page_html)
        viewport = f"{{ width: {width}, height: {height or 800} }}"
        script = (
            "const { chromium } = require('playwright');"
            "(async () => { const b = await chromium.launch();"
            f"const p = await b.newPage({{ viewport: {viewport}, deviceScaleFactor: 1.5 }});"
            f"await p.goto('file://{path}'); await p.evaluate(() => document.fonts.ready); await p.waitForTimeout(300);"
            f"await p.screenshot({{ path: '{out}', fullPage: true }}); await b.close(); }})();"
        )
        subprocess.run(["node", "-e", script], check=True)
    print("wrote", out)


def report_html(result, seconds):
    rows = result.rows
    passed = sum(r[2] == "통과" for r in rows)
    failed = len(rows) - passed
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=HERE, capture_output=True,
                            text=True).stdout.strip()
    cards = []
    for cls, title in GROUPS.items():
        mine = [r for r in rows if r[0] == cls]
        if not mine:
            continue
        ok = all(r[2] == "통과" for r in mine)
        items = "".join(
            f'<li class="{"ok" if st == "통과" else "bad"}"><span class="mark">{"✓" if st == "통과" else "✗"}</span>'
            f'<span class="label">{html.escape(LABELS.get(name, name))}'
            + (f'<br><small>{html.escape(detail)}</small>' if detail else "")
            + f'</span><span class="time">{sec:.1f}초</span></li>'
            for _, name, st, sec, detail in mine)
        cards.append(f'<section class="card"><h2>{html.escape(title)}'
                     f'<span class="count {"ok" if ok else "bad"}">{sum(r[2] == "통과" for r in mine)}/{len(mine)}</span>'
                     f'</h2><ul>{items}</ul></section>')
    missing = {r[0] for r in rows} - set(GROUPS)
    assert not missing, f"묶음 이름이 없는 테스트: {missing}"
    status = "모두 통과" if failed == 0 else f"{failed}개 실패"
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
{font_faces()}
* {{ box-sizing: border-box; margin: 0; }}
body {{ width: 1600px; padding: 40px; background: #EEF2FF; font-family: "NanumSquare", "WenQuanYi Zen Hei", sans-serif;
        color: #1E293B; }}
header {{ display: flex; align-items: center; gap: 28px; padding: 30px 36px; border-radius: 24px;
          background: {"#4F46E5" if failed == 0 else "#B91C1C"}; color: #FFFFFF; }}
.big {{ font-size: 64px; font-weight: 900; letter-spacing: -2px; }}
.sub {{ font-size: 22px; font-weight: 700; color: #E0E7FF; line-height: 1.6; }}
.sub code {{ font-family: monospace; background: rgba(255,255,255,.16); padding: 2px 8px; border-radius: 6px; }}
.grid {{ margin-top: 28px; columns: 3; column-gap: 22px; }}
.card {{ break-inside: avoid; margin-bottom: 22px; padding: 20px 22px; border-radius: 18px; background: #FFFFFF;
         box-shadow: 0 2px 10px rgba(30, 27, 75, .08); }}
h2 {{ display: flex; align-items: center; font-size: 22px; font-weight: 900; margin-bottom: 10px; }}
.count {{ margin-left: auto; font-size: 16px; padding: 4px 12px; border-radius: 999px; }}
.count.ok {{ background: #DCFCE7; color: #166534; }} .count.bad {{ background: #FEE2E2; color: #991B1B; }}
ul {{ list-style: none; padding: 0; }}
li {{ display: flex; gap: 10px; align-items: baseline; padding: 6px 0; border-top: 1px solid #F1F5F9;
      font-size: 17px; line-height: 1.45; }}
li:first-child {{ border-top: none; }}
.mark {{ flex: 0 0 22px; font-weight: 900; }} li.ok .mark {{ color: #16A34A; }} li.bad .mark {{ color: #DC2626; }}
.label {{ flex: 1; word-break: keep-all; }} small {{ color: #B91C1C; }}
.time {{ flex: 0 0 auto; color: #94A3B8; font-size: 14px; }}
footer {{ margin-top: 6px; color: #475569; font-size: 17px; line-height: 1.7; }}
</style></head><body>
<header><div class="big">{"✅" if failed == 0 else "❌"} {len(rows)}개 {status}</div>
<div class="sub">통과 {passed} · 실패 {failed} · 걸린 시간 {seconds:.0f}초<br>
{now} · 커밋 <code>{commit}</code> · <code>python3 test_chatbot.py</code></div></header>
<div class="grid">{"".join(cards)}</div>
<footer>엔트리 블록 동작(형 변환, 함수, 리스트, 테이블, 실시간 리스트, 글상자)을 옮긴 시뮬레이터 <b>simulate.py</b>로
작품 파일 <b>project.json</b>의 블록을 그대로 실행해서 검사한 결과예요. 실제 엔트리 사이트에서 돌린 것은 아니에요.</footer>
</body></html>"""


def conversation_stages():
    project = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))
    day = datetime.datetime(2026, 10, 26, 14, 5)
    run = lambda inputs, server=None, user="minsu01", seed=1, now=day: Session(
        project, {} if server is None else server, username=user, nickname="민수", inputs=inputs, seed=seed,
        now=now).run()
    stages = [
        stage_html(run(["장영실", "작심삼일"], user="w1"), "① 낱말만 말해도 뜻을 알려 줘요 (단어 뜻 1,726개)"),
        stage_html(run(["야르", "킹받다가 뭐야?"], user="w2"), "② 신조어 · 초성체에 반응하고 뜻도 알려 줘요"),
    ]
    server = {}
    run(["오늘 수학 시험 망쳤어", "나 강아지 키워"], server=server, user="w3")
    stages.append(stage_html(run(["시험 결과 나왔는데 생각보다 잘 봤어"], server=server, user="w3", seed=2,
                                 now=day + datetime.timedelta(days=1)),
                             "③ 다음 날: 어제 한 말과 오늘 기분을 견줘서 대답해요"))
    stages.append(stage_html(run(["반말 써", "가위바위보", "보"], user="w4", seed=4),
                             "④ '반말 써' 와 가위바위보"))
    return stage_page(stages)


def main():
    os.makedirs(OUT, exist_ok=True)
    result, seconds = run_tests()
    print(f"{result.testsRun}개 중 실패 {len(result.failures)} · 오류 {len(result.errors)} ({seconds:.0f}초)")
    screenshot(report_html(result, seconds), os.path.join(OUT, "테스트결과.png"), 1600)
    screenshot(conversation_stages(), os.path.join(OUT, "대화결과.png"), 1640, 520)


if __name__ == "__main__":
    main()
