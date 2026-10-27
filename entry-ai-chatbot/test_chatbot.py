#!/usr/bin/env python3
"""엔트리 AI 챗봇 '엔봇' 작품 검사.

1) 구조: 모든 블록(함수 정의·호출, 테이블 블록 포함)이 entryjs 정의(파라미터 개수·종류·드롭다운 값)와 맞는지,
   id 가 겹치지 않는지, 값 함수에 반복이 없는지, 테이블 데이터에 빈 칸·겹치는 키가 없는지
2) .ent 압축 파일
3) 화면: 말풍선 글상자 상태
4) 대화: 되받기·공감·이어 묻기, 이야기 속 사실 기억, 모르는 것 배우기, 다시 접속했을 때 이어 가기,
   사용자별 저장, 대화기록표(검색·통계·다시 채우기), 개인정보·위기 대응, 명령어, 무작위 입력에서 블록 오류가 없는지

실행:  python3 test_chatbot.py
"""
import io
import json
import os
import random
import re
import tarfile
import unittest

import data as D
from build_project import LOG_FIELDS, MAX_HISTORY_LINES, MAX_LINE_LEN, MAX_RECORDS
from dsl import walk_blocks
from simulate import EntryError, Session

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))

B, I, T, L, TI, C = "Block", "Indicator", "Text", "LineBreak", "TextInput", "Color"
COMPARE = ["EQUAL", "NOT_EQUAL", "GREATER", "LESS", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"]
LANGS = ["ko", "en", "ja", "zh-CN", "zh-TW", "es", "fr", "de", "ru", "pt", "th", "vi", "id", "hi"]

# entrylabs/entryjs (e01b81b, 2026-09) src/playground 의 블록 params 정의를 옮긴 것.
# ("D", [값…]) = Dropdown, ("DD", 메뉴) = DropdownDynamic
SCHEMA = {
    "when_run_button_click": ([I], 0),
    "when_message_cast": ([I, ("DD", "messages")], 0),
    "message_cast": ([("DD", "messages"), I], 0),
    "message_cast_wait": ([("DD", "messages"), I], 0),
    "_if": ([B, I], 1),
    "if_else": ([B, I, L], 2),
    "repeat_basic": ([B, I], 1),
    "repeat_inf": ([I, B], 1),
    "repeat_while_true": ([B, ("D", ["until", "while"]), I], 1),
    "stop_repeat": ([I], 0),
    "wait_second": ([B, I], 0),
    "ask_and_wait": ([B, I], 0),
    "get_canvas_input_value": ([T], 0),
    "set_visible_answer": ([("D", ["SHOW", "HIDE"]), I], 0),
    "get_variable": ([("DD", "variables"), T], 0),
    "set_variable": ([("DD", "variables"), B, I], 0),
    "change_variable": ([("DD", "variables"), B, I], 0),
    "value_of_index_from_list": ([T, ("DD", "lists"), T, B, T], 0),
    "add_value_to_list": ([B, ("DD", "lists"), I], 0),
    "remove_value_from_list": ([B, ("DD", "lists"), I], 0),
    "change_value_list_index": ([("DD", "lists"), B, B, I], 0),
    "length_of_list": ([T, ("DD", "lists"), T], 0),
    "is_included_in_list": ([T, ("DD", "lists"), T, B, T], 0),
    "boolean_basic_operator": ([B, ("D", COMPARE), B], 0),
    "boolean_and_or": ([B, ("D", ["AND", "OR"]), B], 0),
    "boolean_not": ([T, B, T], 0),
    "calc_basic": ([B, ("D", ["PLUS", "MINUS", "MULTI", "DIVIDE"]), B], 0),
    "calc_rand": ([T, B, T, B, T], 0),
    "quotient_and_mod": ([T, B, T, B, T, ("D", ["QUOTIENT", "MOD"])], 0),
    "get_date": ([T, ("D", ["YEAR", "MONTH", "DAY", "DAY_OF_WEEK", "HOUR", "MINUTE", "SECOND"]), T], 0),
    "get_user_name": ([], 0),
    "get_nickname": ([], 0),
    "length_of_string": ([T, B, T], 0),
    "reverse_of_string": ([T, B, T], 0),
    "combine_something": ([T, B, T, B, T], 0),
    "char_at": ([T, B, T, B, T], 0),
    "substring": ([T, B, T, B, T, B, T], 0),
    "count_match_string": ([B, T, B, T], 0),
    "index_of_string": ([T, B, T, B, T], 0),
    "replace_string": ([T, B, T, B, T, B, T], 0),
    "change_string_case": ([T, B, T, ("D", ["toUpperCase", "toLowerCase"]), T], 0),
    "remove_dialog": ([I], 0),
    "show": ([I], 0),
    "hide": ([I], 0),
    "text_write": ([B, I], 0),
    "text_change_bg_color": ([B, I], 0),
    "text_change_font_color": ([B, I], 0),
    "text_color": ([C], 0),
    "get_translated_string": ([("D", LANGS), B, ("DD", "translate")], 0),
    "text": ([TI], 0),
    "number": ([TI], 0),
    # 데이터 분석(테이블) 블록 — src/playground/blocks/block_analysis.js
    "append_row_to_table": ([("DD", "tables"), ("D", ["ROW"]), I], 0),
    "delete_row_from_table": ([("DD", "tables"), B, ("D", ["ROW"]), I], 0),
    "set_value_from_table": ([("DD", "tables"), B, B, B, I], 0),
    "get_table_count": ([("DD", "tables"), ("D", ["ROW", "COL"])], 0),
    "get_value_from_table": ([("DD", "tables"), B, B], 0),
    "get_value_v_lookup": ([("DD", "tables"), B, B, B], 0),
    "open_table": ([("DD", "tables"), I], 0),
    # 함수 블록 — src/playground/blocks/block_func.js, src/class/function.js
    "function_create": ([("P",), I], 1),
    "function_create_value": ([("P",), I, L, B], 1),
    "get_func_variable": ([("DD", "locals"), T], 0),
    "set_func_variable": ([("DD", "locals"), B, I], 0),
}
VALUE_BLOCKS = {
    "get_canvas_input_value", "get_variable", "value_of_index_from_list", "length_of_list", "is_included_in_list",
    "boolean_basic_operator", "boolean_and_or", "boolean_not", "calc_basic", "calc_rand", "quotient_and_mod",
    "get_date", "get_user_name", "get_nickname", "length_of_string", "reverse_of_string", "combine_something",
    "char_at", "substring", "count_match_string", "index_of_string", "replace_string", "change_string_case",
    "get_translated_string", "text", "number", "text_color",
    "get_table_count", "get_value_from_table", "get_value_v_lookup", "get_func_variable",
}
EVENT_BLOCKS = {"when_run_button_click", "when_message_cast", "function_create", "function_create_value"}
FUNCTIONS = {f["id"]: f for f in PROJECT["functions"]}


def func_fields(f):
    """함수 정의 블록의 이름표/문자 매개변수 사슬 → [(종류, 값)]"""
    head = json.loads(f["content"])[0][0]
    out, b = [], head["params"][0]
    while b:
        out.append(("label", b["params"][0]) if b["type"] == "function_field_label" else ("string", b["params"][0]["type"]))
        b = b["params"][1]
    return head, out


def is_value_block(p):
    t = p["type"]
    if t.startswith("func_"):
        return FUNCTIONS[t[5:]]["type"] == "value"
    return t in VALUE_BLOCKS or t.startswith("stringParam_")


def ids_of(kind, owner=None):
    if kind == "tables":
        return {t["id"] for t in PROJECT["tables"]}
    if kind == "locals":
        return {v["id"] for v in owner.get("localVariables", [])}
    if kind == "variables":
        return {v["id"] for v in PROJECT["variables"] if v["variableType"] != "list"}
    if kind == "lists":
        return {v["id"] for v in PROJECT["variables"] if v["variableType"] == "list"}
    return {m["id"] for m in PROJECT["messages"]}


def list_data(name):
    return [d["data"] for v in PROJECT["variables"] if v["name"] == name for d in v["array"]]


class StructureTest(unittest.TestCase):
    def test_blocks_match_entry_schema(self):
        seen, problems = set(), []
        for owner, b in walk_blocks(PROJECT):
            t = b["type"]
            if b["id"] in seen:
                problems.append(f"중복 id {b['id']}")
            seen.add(b["id"])
            if t.startswith("func_"):
                # 함수 호출: 문자 매개변수마다 값 블록 하나, 일반 함수는 끝에 Indicator(None)
                f = FUNCTIONS.get(t[5:])
                if f is None:
                    problems.append(f"없는 함수 {t}")
                    continue
                n = sum(1 for k, _ in func_fields(f)[1] if k == "string")
                want = n + (f["type"] == "normal")
                if len(b["params"]) != want or any(not (isinstance(p, dict) and is_value_block(p))
                                                    for p in b["params"][:n]):
                    problems.append(f"{t} 매개변수 {b['params']}")
                if f["type"] == "normal" and b["params"][-1] is not None:
                    problems.append(f"{t} 끝 Indicator")
                continue
            if t.startswith("stringParam_"):
                fields = func_fields(owner)[1] if "content" in owner else []
                if ("string", t) not in fields or b["params"]:
                    problems.append(f"함수 밖이나 다른 함수에서 쓴 매개변수 {t}")
                continue
            if t in ("function_field_label", "function_field_string"):
                ok = (isinstance(b["params"][0], str) if t == "function_field_label"
                      else b["params"][0]["type"].startswith("stringParam_"))
                nxt = b["params"][1]
                if not ok or len(b["params"]) != 2 or not (nxt is None or nxt["type"].startswith("function_field_")):
                    problems.append(f"{t} 모양 {b['params']}")
                continue
            if t not in SCHEMA:
                problems.append(f"모르는 블록 {t}")
                continue
            kinds, n_st = SCHEMA[t]
            params = b["params"]
            if t in ("text", "number"):
                if len(params) != 1 or not isinstance(params[0], str):
                    problems.append(f"{t} 값이 문자열이 아님: {params}")
                continue
            if t == "text_color":
                if not re.match(r"^#[0-9A-Fa-f]{6}$", str(params[0])):
                    problems.append(f"색 값 {params}")
                continue
            if len(params) > len(kinds):
                problems.append(f"{t} 파라미터가 너무 많음 {len(params)} > {len(kinds)}")
            for i, p in enumerate(params):
                k = kinds[i]
                if k == B:
                    if p is not None and not (isinstance(p, dict) and is_value_block(p)):
                        problems.append(f"{t}[{i}] 값 블록 자리에 {p!r}")
                elif k == ("P",):
                    if not (isinstance(p, dict) and p["type"] == "function_field_label"):
                        problems.append(f"{t}[{i}] 함수 이름표 자리에 {p!r}")
                elif isinstance(k, tuple) and k[0] == "D":
                    if p not in k[1]:
                        problems.append(f"{t}[{i}] 드롭다운 값 {p!r}")
                elif isinstance(k, tuple) and k[0] == "DD":
                    if k[1] == "translate":
                        if p not in LANGS:
                            problems.append(f"{t}[{i}] 번역 언어 {p!r}")
                    elif p not in ids_of(k[1], owner):
                        problems.append(f"{t}[{i}] 없는 {k[1]} id {p!r}")
                elif p is not None:
                    problems.append(f"{t}[{i}] ({k}) 자리에 {p!r}")
            if len(b.get("statements", [])) != n_st:
                problems.append(f"{t} statements 개수 {len(b.get('statements', []))} != {n_st}")
            for st in b.get("statements", []):
                for sb in st:
                    if sb["type"] in EVENT_BLOCKS or is_value_block(sb):
                        problems.append(f"{t} 안에 문장이 아닌 블록 {sb['type']}")
        self.assertEqual(problems[:20], [])

    def test_threads_start_with_events(self):
        for o in PROJECT["objects"]:
            for t in json.loads(o["script"]):
                self.assertIn(t[0]["type"], EVENT_BLOCKS)
                for b in t[1:]:
                    self.assertNotIn(b["type"], VALUE_BLOCKS | EVENT_BLOCKS)

    def test_every_message_has_handler(self):
        handled = {t[0]["params"][1] for o in PROJECT["objects"] for t in json.loads(o["script"])
                   if t[0]["type"] == "when_message_cast"}
        self.assertEqual(handled, ids_of("messages"))

    def test_project_fields(self):
        p = PROJECT
        self.assertEqual(p["aiUtilizeBlocks"], ["translate"])
        self.assertEqual({o["objectType"] for o in p["objects"]}, {"textBox"})
        rt = [v["name"] for v in p["variables"] if v.get("isRealTime")]
        self.assertEqual(sorted(rt), ["기억저장소", "대화기록"])
        names = [v["name"] for v in p["variables"]]
        self.assertEqual(len(names), len(set(names)), "변수/리스트 이름 중복")
        for name in ["불용어", "조사목록", "뒤집는말"]:
            self.assertTrue(list_data(name) and all(list_data(name)), name)

    def test_knowledge_lists(self):
        """지식은 테이블이 아니라 리스트에 넣는다 (엔트리 웹에서 .ent 를 불러오면 테이블은 빠진다)."""
        keys, values = list_data("지식키"), list_data("지식값")
        self.assertEqual(len(keys), len(values))
        self.assertGreater(len(keys), 1000)
        self.assertEqual(len(keys), len(set(keys)))
        # 이진 탐색을 하므로 자바스크립트 글자 비교(UTF-16 코드 단위) 순서로 정렬돼 있어야 한다
        self.assertEqual(keys, sorted(keys, key=lambda k: k.encode("utf-16-be")))
        rows = {}
        for k, v in zip(keys, values):
            kind, word = k.split("|", 1)
            self.assertIn(kind, {"주", "뜻", "말", "감"})
            # 엔트리 비교 블록은 숫자처럼 보이는 글을 숫자로 바꿔 비교한다 — 키는 숫자처럼 보이면 안 된다
            self.assertFalse(re.fullmatch(r"\s*-?[0-9.]+\s*", word), k)
            self.assertTrue(str(v).strip(), k)  # 빈 값이면 '없음'과 구별이 안 된다
            rows.setdefault(kind, []).append((word, v))
        for word, _ in rows["뜻"] + rows["말"]:
            self.assertTrue(word == word.lower() and " " not in word, word)
        for word, answers in rows["말"]:
            # 대답이 여러 개면 ' | ' 로 나눠 둔다. 말 속 조각을 찾는 방식이라 키워드는 2~10글자
            self.assertTrue(2 <= len(word) <= 10, word)
            self.assertTrue(all(a.strip() for a in answers.split(" | ")), word)
        for word, score in rows["감"]:
            self.assertTrue(re.fullmatch(r"-?[1-9]", score), (word, score))
        self.assertEqual(len(list_data("먼저-키")), len(list_data("먼저-질문")))

    def test_knowledge_search_finds_every_key(self):
        s = Session(PROJECT, {}, username="k", nickname="k", inputs=[])
        fid = next(f["id"] for f in PROJECT["functions"] if func_fields(f)[1][0][1] == "지식 찾기")
        for k, v in zip(list_data("지식키"), list_data("지식값")):
            kind, word = k.split("|", 1)
            self.assertEqual(str(s.call_function(fid, [kind, word])), str(v), k)
        for kind, word in [("주", "없는낱말"), ("뜻", ""), ("말", "가"), ("감", "zzzz"), ("주", "0")]:
            self.assertEqual(s.call_function(fid, [kind, word]), "", (kind, word))

    def test_tables(self):
        # 엔트리 저장 형식 (DataTableSource.toJSON): data 는 {key, value}, origin 은 원본 줄
        self.assertEqual([t["name"] for t in PROJECT["tables"]], ["대화기록표"])
        t = PROJECT["tables"][0]
        self.assertEqual(t["fields"], LOG_FIELDS)
        self.assertEqual([r["value"] for r in t["data"]], t["origin"])
        self.assertFalse(any("_" in r["key"] for r in t["data"]))  # dmetTable 은 '_' 로 줄 키와 칸을 나눈다
        # 빈 표는 엔트리 화면에서 만들 수 없는 모양이라 안내 줄 하나를 넣어 둔다
        self.assertEqual(len(t["origin"]), 1)
        self.assertTrue(all(str(c).strip() for c in t["origin"][0]))

    def test_table_blocks_only_in_two_functions(self):
        """테이블 블록은 '기록표 맞추기', '기록표 열기' 안에만 있다. 기록표를 켜지 않으면 실행되지 않는다."""
        names = {t["id"]: t["name"] for t in PROJECT["tables"]}
        found = []
        for owner, b in walk_blocks(PROJECT):
            if b["params"] and isinstance(b["params"][0], str) and b["params"][0] in names:
                self.assertIn("content", owner, f"오브젝트 스크립트에 테이블 블록 {b['type']}")
                found.append(func_fields(owner)[1][0][1])
        self.assertEqual(sorted(set(found)), ["기록표 맞추기", "기록표 열기"])
        self.assertLessEqual(len(found), 5)

    def test_functions(self):
        calls = {b["type"][5:] for _o, b in walk_blocks(PROJECT) if b["type"].startswith("func_")}
        for f in PROJECT["functions"]:
            head, fields = func_fields(f)
            self.assertEqual(len(json.loads(f["content"])), 1, "함수 안에 떨어진 블록 묶음")
            self.assertEqual(head["type"], "function_create_value" if f["type"] == "value" else "function_create")
            self.assertEqual(fields[0][0], "label")
            self.assertIn(f["id"], calls, f"쓰지 않는 함수 {fields[0][1]}")
            self.assertEqual(f["useLocalVariables"], bool(f["localVariables"]))
            for v in f["localVariables"]:
                self.assertTrue(v["id"].startswith(f["id"] + "_"), v)
            if f["type"] == "value":
                # 몸통이 빈 값 함수는 엔트리에서 정의 블록 자체를 실행하느라 한 프레임 늦게(Promise로) 값을 준다
                self.assertTrue(head["statements"][0], f"몸통이 빈 값 함수 {fields[0][1]}")
                # 값 함수 안에서 반복·기다리기를 쓰면 여러 프레임에 걸쳐 돌아 값이 늦게(Promise로) 나온다
                types = {b["type"] for o, b in walk_blocks(PROJECT) if o is f}
                self.assertFalse(types & {"repeat_basic", "repeat_inf", "repeat_while_true", "wait_second",
                                          "ask_and_wait", "message_cast_wait", "append_row_to_table"}, fields[0][1])
                normal = {g["id"] for g in PROJECT["functions"] if g["type"] == "normal"}
                self.assertFalse({t[5:] for t in types if t.startswith("func_")} & normal, fields[0][1])
        self.assertGreaterEqual(len(PROJECT["functions"]), 30)

    def test_ent_archive(self):
        with tarfile.open(os.path.join(HERE, "entry-ai-chatbot.ent"), "r:gz") as tar:
            self.assertIn("temp/project.json", tar.getnames())
            data = json.load(io.TextIOWrapper(tar.extractfile("temp/project.json"), encoding="utf-8"))
        self.assertEqual(data, PROJECT)

    def test_batchim_tables(self):
        self.assertEqual(len(D.NO_BATCHIM), 19 * 21 + 4)
        self.assertIn("가", D.NO_BATCHIM)
        self.assertNotIn("각", D.NO_BATCHIM)
        self.assertIn("했", D.SSANG_SIOT)
        self.assertIn("일", D.RIEUL)


# ------------------------------------------------------------------ 대화 도우미
def chat(server, user, inputs, nick="민수", seed=0):
    return Session(PROJECT, server, username=user, nickname=nick, inputs=inputs, seed=seed).run()


def flat(text):
    return "".join(text.split())


def bot_replies(s):
    """사용자 말 다음에 나온 봇 대답들 (환영 인사 제외)."""
    lines = s.transcript_lines()
    # 다시 접속하면 지난 대화가 먼저 나오므로, '이어서' 표시 뒤부터 센다
    resume = [i for i, (tag, text, _) in enumerate(lines) if tag == "알림" and text.strip().startswith("── 이어서")]
    if resume:
        lines = lines[resume[-1] + 1:]
    out = []
    for i, (tag, text, _) in enumerate(lines):
        if tag == "나" and i + 1 < len(lines) and lines[i + 1][0] == "봇":
            out.append(lines[i + 1][1])
    return out


def memory(s):
    return dict(zip(s.lst("내질문"), s.lst("내답변")))


class ScreenTest(unittest.TestCase):
    def test_bubbles(self):
        s = chat({}, "ui", ["안녕", "오늘 시험 망쳤어", "수학", "나 고양이 키워"])
        rows = s.screen()
        self.assertGreater(len(rows), 3)
        self.assertLessEqual(len(rows), 9)
        for text, side, bg, fg in rows:
            if side == "me":
                self.assertEqual((bg.upper(), fg.upper()), ("#4F46E5", "#FFFFFF"))
            elif not text.strip().startswith("──"):
                self.assertEqual(bg.upper(), "#FFFFFF")
        self.assertEqual(rows[-1][1], "bot")
        for k in range(1, 10):
            self.assertFalse(s.obj(f"봇칸{k}")["visible"] and s.obj(f"나칸{k}")["visible"])
        self.assertEqual(s.obj("상태")["text"], "● 민수님과 대화 중")
        self.assertIsNone(s.obj("엔봇")["dialog"], "묻기 말풍선은 지워져야 함")

    def test_thinking_row_removed(self):
        s = chat({}, "ui2", ["안녕"])
        self.assertNotIn("생각", s.lst("화면종류"))


class ConversationTest(unittest.TestCase):
    def test_reflects_and_follows_up(self):
        s = chat({}, "a", ["오늘 시험 망쳤어", "나 고양이 키워", "엄마랑 싸웠어", "오늘 축구해서 이겼어"])
        r = bot_replies(s)
        self.assertIn("시험 망쳤군요", r[0])
        self.assertIn("고양이 이름이 뭐예요?", r[1])
        self.assertIn("엄마랑 싸웠군요", r[2])
        self.assertIn("축구해서 이겼군요", r[3])
        self.assertTrue(r[3].endswith("?"), r[3])  # 이어서 되묻는다

    def test_no_canned_fallback(self):
        rng = random.Random(1)
        words = ["오늘", "친구", "학교", "게임", "피곤해", "재밌었어", "봤어", "갔어", "엄마", "숙제", "그냥", "ㅋㅋ"]
        inputs = [" ".join(rng.choice(words) for _ in range(rng.randint(1, 4))) for _ in range(40)]
        s = chat({}, "b", inputs)
        for reply in bot_replies(s):
            self.assertNotIn("이야기를 듣는 건 언제나 즐거워요", reply)
            self.assertNotIn("다시 한번 말해 줄래요", reply)

    def test_learns_facts_from_story_and_recalls_next_visit(self):
        server = {}
        s = chat(server, "c", ["나 고양이 키워", "나비", "내 생일은 3월 14일이야", "나는 피자를 좋아해", "나 12살이야"])
        mem = memory(s)
        self.assertEqual(mem["내 고양이 이름"], "F:나비")
        self.assertEqual(mem["내 생일"], "F:3월 14일")
        self.assertEqual(mem["내가 좋아하는 것"], "F:피자")
        self.assertEqual(mem["내 나이"], "F:12살")
        r = bot_replies(s)
        self.assertIn("민수님의 고양이 이름은 나비군요", r[1])
        self.assertIn("3월 14일이군요", r[2])
        # 다시 접속
        s2 = chat(server, "c", ["내 생일 언제라고 했지?", "내가 뭐 좋아한다고 했지?", "몇 살이라고 했지?",
                                "나비가 요즘 밥을 안 먹어"])
        lines = s2.transcript_lines()
        self.assertTrue(any(t.startswith("── 지난 대화") for _, t, _ in lines))
        r2 = bot_replies(s2)
        self.assertIn("3월 14일", r2[0])
        self.assertIn("피자", r2[1])
        self.assertIn("12살", r2[2])
        self.assertTrue(r2[3].startswith("민수님의 고양이 나비 말이죠?"), r2[3])

    def test_welcome_back_remembers_topic_and_mood(self):
        server = {}
        chat(server, "d", ["오늘 시험 망쳤어"])
        s = chat(server, "d", [])
        welcome = [t for tag, t, _ in s.transcript_lines() if tag == "봇"][-1]
        self.assertIn("시험", welcome)
        self.assertTrue(any(w in welcome for w in ["지난번", "저번"]), welcome)
        server = {}
        chat(server, "e", ["아 진짜 짜증나"])
        s = chat(server, "e", [])
        welcome = [t for tag, t, _ in s.transcript_lines() if tag == "봇"][-1]
        self.assertIn(welcome.replace("민수", "{이름}"), [t.replace(" [기분]", "") for t in D.PHRASES["말-환영기분"]])

    def test_learns_unknown_words_and_questions(self):
        server = {}
        s = chat(server, "f", ["블랙홀이 뭐야?", "양자컴퓨터가 뭐야?", "양자의 원리로 계산하는 컴퓨터야",
                               "우리 학교 이름이 뭐게?", "한빛초등학교야"])
        r = bot_replies(s)
        self.assertTrue(r[0].startswith("블랙홀은 중력이"))
        self.assertIn("양자컴퓨터", r[1])
        self.assertIn("양자컴퓨터는 양자의 원리로 계산하는 컴퓨터군요", r[2])
        self.assertIn(r[3], D.PHRASES["말-모르는질문"])
        s = chat(server, "f", ["양자컴퓨터 알아?", "우리 학교 이름이 뭐게?"])
        r = bot_replies(s)
        self.assertIn("양자컴퓨터는 양자의 원리로 계산하는 컴퓨터", r[0])
        self.assertEqual(r[1], "한빛초등학교야")

    def test_does_not_ask_known_things(self):
        s = chat({}, "g", ["나 고양이 키워", "나비", "고양이 귀엽지"])
        self.assertNotIn("고양이 이름이 뭐예요", bot_replies(s)[2])

    def test_ignores_non_answers(self):
        s = chat({}, "h", ["나 고양이 키워", "몰라", "음 그냥"])
        self.assertNotIn("내 고양이 이름", memory(s))

    def test_josa(self):
        s = chat({}, "i", ["내 꿈은 의사야", "내 별명은 곰돌이야", "내 동네는 서울숲이야"])
        r = bot_replies(s)
        self.assertIn("민수님의 꿈은 의사군요", r[0])
        self.assertIn("민수님의 별명은 곰돌이군요", r[1])
        self.assertIn("민수님의 동네는 서울숲이군요", r[2])

    def test_name(self):
        server = {}
        s = chat(server, "j", ["내 이름은 지호야", "내 이름 뭐라고?"])
        r = bot_replies(s)
        self.assertIn("지호님이라고 부를게요", r[0])
        self.assertEqual(r[1], "지호님이잖아요! 잘 기억하고 있어요.")
        s = chat(server, "j", [])
        self.assertEqual(s.obj("상태")["text"], "● 지호님과 대화 중")


class StorageTest(unittest.TestCase):
    def test_users_are_separate(self):
        server = {}
        chat(server, "minsu01", ["내 생일은 3월 14일이야"])
        s = chat(server, "jiyoung", ["내 생일 언제라고 했지?", "기억 목록"], nick="지영")
        self.assertNotIn("3월14일", flat(" ".join(bot_replies(s))))
        hist = server[s.list_names["대화기록"]]
        mem = server[s.list_names["기억저장소"]]
        self.assertEqual(sorted(x.split("|")[0] for x in hist), ["jiyoung", "minsu01"])
        self.assertEqual(sorted(x.split("|")[0] for x in mem), ["jiyoung", "minsu01"])

    def test_prefix_ids_do_not_collide(self):
        server = {}
        chat(server, "ab", ["기억해: 색 = 빨강"])
        s = chat(server, "a", ["기억 목록"])
        self.assertIn("아직 기억하고 있는 게 없어요", bot_replies(s)[0])
        s = chat(server, "ab", ["색 알려줘"])
        self.assertEqual(bot_replies(s)[0], "빨강")

    def test_guest_mode_saves_nothing(self):
        server = {}
        s = Session(PROJECT, server, username=None, nickname=None, inputs=["안녕", "기억해: 비밀 = 123", "비밀"]).run()
        self.assertIn("로그인하면 우리 대화를 기억할 수 있어요", s.transcript_lines()[0][1])
        self.assertEqual(bot_replies(s)[-1], "123")
        for arr in server.values():
            self.assertEqual(arr, [])

    def test_history_is_trimmed(self):
        server = {}
        s = chat(server, "u", [f"메시지 {i}" for i in range(25)] + ["가" * 300])
        blob = server[s.list_names["대화기록"]][0]
        self.assertTrue(blob.startswith("u|"))
        self.assertEqual(blob.count("¶"), MAX_HISTORY_LINES)
        line = [x for x in blob.split("¶") if x.startswith("나|") and x.endswith("…")]
        self.assertEqual(len(line), 1)
        self.assertEqual(len(line[0]), MAX_LINE_LEN + 1)

    def test_new_chat_and_forget(self):
        server = {}
        chat(server, "k", ["내 생일은 3월 14일이야", "안녕"])
        s = chat(server, "k", ["새 대화", "잊어줘: 내 생일", "잊어줘: 없는거", "기억 목록"])
        r = bot_replies(s)
        self.assertIn("대화 기록을 지웠어요", r[0])
        self.assertIn("기억을 지웠어요", r[1])
        self.assertIn("기억은 없어요", r[2])
        self.assertNotIn("내 생일", memory(s))
        hist = server[s.list_names["대화기록"]][0]
        self.assertNotIn("안녕", hist)

    def test_save_failure_is_reported(self):
        class Rejecting(list):
            def append(self, x):
                pass

        class Server(dict):
            def setdefault(self, k, v):
                return super().setdefault(k, Rejecting(v))

        s = chat(Server(), "x", ["기억해: a = b", "a"])
        self.assertIn("저장 서버에 연결하지 못해서", " ".join(t for _, t, _ in s.transcript_lines()))
        self.assertEqual(bot_replies(s)[-1], "b")


class CommandTest(unittest.TestCase):
    def test_calculator(self):
        cases = {"계산: 12*3": "12*3 = 36", "계산: 1.5 + 2": "1.5+2 = 3.5", "계산: 10/4": "10/4 = 2.5",
                 "계산: 10 x 3": "10*3 = 30", "계산: 3--2": "3--2 = 5", "계산: -3+4": "-3+4 = 1",
                 "계산: 5/0": "0으로는 나눌 수 없어요."}
        s = chat({}, "m", list(cases))
        self.assertEqual(bot_replies(s), list(cases.values()))

    def test_translate_help_time(self):
        s = chat({}, "n", ["번역: 안녕하세요", "한국어로: hello", "도움말", "몇 시야?", "종료", "안 읽힘"])
        r = bot_replies(s)
        self.assertIn("<en:안녕하세요>", r[0])
        self.assertIn("<ko:hello>", r[1])
        self.assertIn("편하게 이야기해 보세요", r[2])
        self.assertEqual(r[3], "지금은 14시 5분이에요.")
        self.assertIn("즐거웠어요, 민수님", r[4])
        self.assertEqual(s.inputs, ["안 읽힘"])
        self.assertEqual(s.obj("상태")["text"], "● 대화 종료")


def without_tables(project):
    """엔트리 웹에서 .ent 를 불러오면 테이블이 빠진다 — 그 상태의 작품."""
    return dict(project, tables=[])


def records(s):
    """기록 리스트 → [번호, 날짜, 시각, 누가, 주제, 감정, 내용] 줄들"""
    cols = [s.lst(f"기록-{c}") for c in LOG_FIELDS]
    return [[c[i] for c in cols] for i in range(len(cols[-1]))]


def as_text(rows):
    """테이블은 숫자처럼 보이는 값을 숫자로 바꿔 담으므로 글자로 맞춰 비교한다."""
    return [[str(c) for c in r] for r in rows]


class RecordTest(unittest.TestCase):
    """대화 기록: 리스트 '기록-…' (날짜·시각·누가·주제·감정·내용) + 켜면 대화기록표(엔트리 테이블)"""

    def test_every_line_is_recorded(self):
        s = chat({}, "r1", ["오늘 시험 망쳤어", "고마워"])
        rows = records(s)
        self.assertEqual([str(r[0]) for r in rows], ["1", "2", "3", "4"])
        self.assertEqual([r[3] for r in rows], ["나", "봇", "나", "봇"])
        self.assertEqual(rows[0][4], "시험")
        self.assertLess(float(rows[0][5]), 0)
        self.assertEqual(rows[1][5], "-")
        self.assertEqual(rows[0][6], "오늘 시험 망쳤어")
        self.assertTrue(re.fullmatch(r"\d{4}-\d\d-\d\d", rows[0][1]), rows[0][1])
        self.assertTrue(re.fullmatch(r"\d\d:\d\d", rows[0][2]), rows[0][2])
        for r in rows:
            self.assertTrue(all(str(c) != "" for c in r), r)

    def test_records_are_rebuilt_from_server_on_next_visit(self):
        server = {}
        first = chat(server, "r2", ["나 고양이 키워", "나비", "오늘 학교에서 발표했어"])
        again = chat(server, "r2", [])
        self.assertEqual(records(again), records(first))
        self.assertEqual(records(again)[4][4], "발표")  # '발표했어' 에서 주제 낱말을 찾는다

    def test_old_history_format_is_read(self):
        server = {}
        list_id = next(v["id"] for v in PROJECT["variables"] if v["name"] == "대화기록")
        server[list_id] = ["r3|나: 안녕¶봇: 반가워요¶"]
        s = chat(server, "r3", [])
        self.assertEqual([(r[3], r[6]) for r in records(s)], [("나", "안녕"), ("봇", "반가워요")])

    def test_search_stats_and_text_view(self):
        s = chat({}, "r4", ["나 고양이 키워", "나비", "나비가 밥을 안 먹어", "기록 검색: 나비", "기록 통계", "기록표"])
        r = bot_replies(s)
        self.assertIn("'나비' 기록을", r[3])
        # 최근 기록부터 보여 준다
        self.assertLess(r[3].index("나: 나비가 밥을 안 먹어"), r[3].index("나: 나비", r[3].index("나: 나비가") + 1))
        self.assertTrue(r[3].endswith("나: 나비"), r[3])
        self.assertIn("민수님 4줄", r[4])
        self.assertIn("엔봇 4줄", r[4])
        self.assertIn("제일 많이 나온 주제: 고양이", r[4])
        # 기록표를 켜지 않았으면 테이블 대신 글로 최근 기록을 보여 준다
        self.assertEqual(s.opened_tables, [])
        self.assertIn("최근 대화 기록이에요. (모두 10줄)", r[5])
        self.assertIn("기록표 켜기", r[5])
        s = chat({}, "r5", ["기록 검색: 없는말"])
        self.assertIn("기록은 없어요", bot_replies(s)[0])

    def test_new_chat_clears_records(self):
        s = chat({}, "r6", ["안녕", "오늘 재밌었어", "새 대화"])
        self.assertEqual([r[6] for r in records(s)], ["새 대화", records(s)[1][6]])
        self.assertEqual(len(records(s)), 2)

    def test_works_when_tables_are_missing(self):
        """엔트리 웹에서 불러와 테이블이 빠져도 기록표를 켜기 전에는 테이블 블록을 쓰지 않는다."""
        project = without_tables(PROJECT)
        inputs = ["안녕", "오늘 시험 망쳤어", "수학", "나 고양이 키워", "나비", "블랙홀이 뭐야?", "수수께끼", "ㅋㅋ",
                  "기록표", "기록 검색: 나비", "기록 통계", "기억 목록", "새 대화", "기록표 끄기", "도움말", "?"]
        server = {}
        Session(project, server, username="t1", nickname="민수", inputs=inputs).run()
        Session(project, server, username="t1", nickname="민수", inputs=["안녕", "기록표"]).run()
        Session(project, {}, username=None, nickname=None, inputs=inputs).run()
        with self.assertRaises(EntryError):  # 켜면 테이블이 있어야 한다
            Session(project, {}, username="t2", nickname="민수", inputs=["기록표 켜기", "안녕"]).run()

    def test_table_mirrors_records_when_turned_on(self):
        s = chat({}, "r7", ["안녕", "기록표 켜기", "나 고양이 키워", "나비", "기록표"])
        table = s.table("대화기록표")["rows"]
        self.assertEqual(as_text(table), as_text(records(s)[:len(table)]))
        self.assertEqual([r[0] for r in table], list(range(1, len(table) + 1)))
        self.assertGreaterEqual(len(table), 8)  # '기록표' 명령 앞까지
        self.assertEqual(s.opened_tables, ["대화기록표"])
        self.assertIn("대화 기록표를 열었어요", bot_replies(s)[-1])
        # 안내 줄은 지워진다
        self.assertNotIn("안내", [r[3] for r in table])

    def test_table_keeps_up_when_old_records_are_trimmed(self):
        inputs = ["기록표 켜기"] + [f"메시지 {i}" for i in range(MAX_RECORDS // 2 + 5)] + ["새 대화", "안녕"]
        s = chat({}, "r8", inputs[:-2])
        self.assertEqual(len(records(s)), MAX_RECORDS)
        self.assertEqual(as_text(s.table("대화기록표")["rows"]), as_text(records(s)))
        self.assertEqual(str(records(s)[0][0]), "13")  # 번호는 지워진 줄 다음부터 이어진다
        s = chat({}, "r9", inputs)
        self.assertEqual(as_text(s.table("대화기록표")["rows"]), as_text(records(s)))
        self.assertEqual([str(r[0]) for r in records(s)], ["1", "2", "3", "4"])


class SafetyTest(unittest.TestCase):
    def test_private_info_is_not_remembered_or_logged(self):
        server = {}
        s = chat(server, "p1", ["내 비밀번호는 abc123이야", "기억해: 비번 = 1234", "내 전화번호는 010-1234-5678"])
        for reply in bot_replies(s):
            self.assertIn(reply.replace("민수", "{이름}"), D.PHRASES["말-개인정보"])
        everything = json.dumps([server, records(s), memory(s)], ensure_ascii=False)
        for secret in ["abc123", "1234", "5678"]:
            self.assertNotIn(secret, everything)
        self.assertIn("🔒", records(s)[0][6])

    def test_crisis_gets_help_numbers(self):
        s = chat({}, "p2", ["요즘 너무 힘들어서 죽고 싶어"])
        reply = bot_replies(s)[0]
        self.assertIn("1388", reply)
        self.assertIn("109", reply)


class RobustnessTest(unittest.TestCase):
    def test_random_inputs_never_crash(self):
        rng = random.Random(7)
        pieces = ["안녕", "기억해:", "잊어줘:", "번역:", "계산:", "=", ":", "¶", "|", " ", "1", "0", "-", "+", "?",
                  "가나다", "abc", "ㅋㅋ", "도움말", "기억 목록", "새 대화", "몇 시", "{이름}", "[사실:x]", "…", "😀",
                  "내", "내 ", "나는", "좋아해", "싫어", "이야", "했어", "봤어", "뭐야", "이름은", "살", "12살",
                  "고양이", "시험", "때문에", "해서", "몰라", "응", "너는", "a" * 40]
        server = {}
        users = ["u1", "u2", "user_3", "4"]
        worst = 0
        for n in range(120):
            inputs = ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(1, 7))]
            user = rng.choice(users + [None])
            try:
                s = Session(PROJECT, server, username=user, nickname=user, inputs=inputs, seed=n).run()
            except EntryError as e:
                self.fail(f"입력 {inputs!r} (사용자 {user}) 에서 블록 오류: {e}")
            self.assertLessEqual(len(s.lst("화면글")), 9)
            self.assertEqual(len(s.lst("내질문")), len(s.lst("내답변")))
            worst = max([worst] + s.turn_frames[1:])
        self.assertLess(worst, 400, "부스트 모드 없이 한 번 대답하는 데 너무 오래 걸림")
        for item in server[s.list_names["대화기록"]]:
            self.assertLessEqual(item.count("¶"), MAX_HISTORY_LINES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
