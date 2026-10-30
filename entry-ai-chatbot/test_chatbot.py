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
import csv
import datetime
import io
import json
import os
import random
import re
import tarfile
import unittest

import data as D
from build_project import (LOG_FIELDS, MAX_CONVS, MAX_DIARY, MAX_HISTORY_LINES, MAX_LINE_LEN, MAX_RECORDS, SLOT_BG,
                           SLOT_SEL_BG, dueum_pairs)
from dsl import walk_blocks
from simulate import EndOfInput, EntryError, Session

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))

B, I, T, L, TI, C = "Block", "Indicator", "Text", "LineBreak", "TextInput", "Color"
COMPARE = ["EQUAL", "NOT_EQUAL", "GREATER", "LESS", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"]
LANGS = ["ko", "en", "ja", "zh-CN", "zh-TW", "es", "fr", "de", "ru", "pt", "th", "vi", "id", "hi"]

# entrylabs/entryjs (e01b81b, 2026-09) src/playground 의 블록 params 정의를 옮긴 것.
# ("D", [값…]) = Dropdown, ("DD", 메뉴) = DropdownDynamic
SCHEMA = {
    "when_run_button_click": ([I], 0),
    "when_object_click": ([I], 0),
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
    # src/playground/blocks/block_looks.js, src/playground/block_entry.js
    "change_to_some_shape": ([B, I], 0),
    "get_pictures": ([("DD", "pictures")], 0),
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
    "get_translated_string", "text", "number", "text_color", "get_pictures",
    "get_table_count", "get_value_from_table", "get_value_v_lookup", "get_func_variable",
}
EVENT_BLOCKS = {"when_run_button_click", "when_object_click", "when_message_cast", "function_create",
                "function_create_value"}
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
    if kind == "pictures":
        return {pic["id"] for pic in owner.get("sprite", {}).get("pictures", [])}
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
        self.assertEqual({o["objectType"] for o in p["objects"]}, {"textBox", "sprite"})
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
            self.assertIn(kind, {"주", "뜻", "말", "감", "두"})
            # 엔트리 비교 블록은 숫자처럼 보이는 글을 숫자로 바꿔 비교한다 — 키는 숫자처럼 보이면 안 된다
            self.assertFalse(re.fullmatch(r"\s*-?[0-9.]+\s*", word), k)
            self.assertTrue(str(v).strip(), k)  # 빈 값이면 '없음'과 구별이 안 된다
            rows.setdefault(kind, []).append((word, v))
        for word, _ in rows["뜻"] + rows["말"]:
            self.assertTrue(word == word.lower() and " " not in word, word)
        for word, answers in rows["말"]:
            # 대답이 여러 개면 ' | ' 로 나눠 둔다. 말 속 조각을 찾는 방식이라 키워드는 2~10글자
            # (한 글자 말 '헐', 'ㅋ' 은 말 전체가 그 글자일 때만 찾는다)
            self.assertTrue(1 <= len(word) <= 10, word)
            self.assertTrue(all(a.strip() for a in answers.split(" | ")), word)
        for word, score in rows["감"]:
            self.assertTrue(re.fullmatch(r"-?[1-9]", score), (word, score))
        # 두음법칙: 한 글자 → 한 글자 ('력' → '역', '녀' → '여', '라' → '나')
        dueum = dict(rows["두"])
        self.assertEqual((dueum["력"], dueum["녀"], dueum["라"], dueum["룡"]), ("역", "여", "나", "용"))
        self.assertTrue(all(len(a) == 1 and len(b) == 1 for a, b in rows["두"]))
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
            names = tar.getnames()
            self.assertIn("temp/project.json", names)
            data = json.load(io.TextIOWrapper(tar.extractfile("temp/project.json"), encoding="utf-8"))
            # 그림 모양마다 그림 파일과 작은 그림 파일이 fileurl / thumbUrl 자리에 PNG 로 들어 있다
            for o in PROJECT["objects"]:
                for pic in o["sprite"]["pictures"]:
                    for url in (pic["fileurl"], pic["thumbUrl"]):
                        self.assertIn(url, names)
                        self.assertEqual(tar.extractfile(url).read(8), b"\x89PNG\r\n\x1a\n")
            for name in names:  # 파일이 든 폴더도 모두 들어 있다
                if "/" in name:
                    self.assertIn(name.rsplit("/", 1)[0], names)
        self.assertEqual(data, PROJECT)

    def test_batchim_tables(self):
        self.assertEqual(len(D.NO_BATCHIM), 19 * 21 + 4)
        self.assertIn("가", D.NO_BATCHIM)
        self.assertNotIn("각", D.NO_BATCHIM)
        self.assertIn("했", D.SSANG_SIOT)
        self.assertIn("일", D.RIEUL)


# ------------------------------------------------------------------ 대화 도우미
def chat(server, user, inputs, nick="민수", seed=0, save=False):
    """대화를 돌린다. save=True 면 마지막에 /save 해서 다음 접속 때 이어지게 한다."""
    inputs = list(inputs) + (["/save"] if save else [])
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
        self.assertEqual(s.obj("상태")["text"], "● 민수님 · 저장 안 됨")  # /save 전
        self.assertIsNone(s.obj("엔봇")["dialog"], "묻기 말풍선은 지워져야 함")
        self.assertEqual(chat({}, "ui3", ["안녕"], save=True).obj("상태")["text"], "● 민수님과 대화 중")

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
        s = chat(server, "c", ["나 고양이 키워", "나비", "내 생일은 3월 14일이야", "나는 피자를 좋아해", "나 12살이야"], save=True)
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
        chat(server, "d", ["오늘 시험 망쳤어"], save=True)
        s = chat(server, "d", [])
        welcome = [t for tag, t, _ in s.transcript_lines() if tag == "봇"][-1]
        # 그 주제로 마지막에 한 말을 꺼내고, 그때 속상해했으니 괜찮아졌는지 묻는다
        self.assertEqual(welcome, "민수님, 다시 왔군요! 아까 “오늘 시험 망쳤어”라고 했었죠. 그 뒤로 좀 괜찮아졌어요?")
        server = {}
        chat(server, "e", ["아 진짜 짜증나"], save=True)
        s = chat(server, "e", [])
        welcome = [t for tag, t, _ in s.transcript_lines() if tag == "봇"][-1]
        self.assertIn(welcome.replace("민수", "{이름}"), [t.replace(" [기분]", "") for t in D.PHRASES["말-환영기분"]])

    def test_learns_unknown_words_and_questions(self):
        server = {}
        s = chat(server, "f", ["블랙홀이 뭐야?", "양자컴퓨터가 뭐야?", "양자의 원리로 계산하는 컴퓨터야",
                               "우리 학교 이름이 뭐게?", "한빛초등학교야"], save=True)
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
        s = chat(server, "j", ["내 이름은 지호야", "내 이름 뭐라고?"], save=True)
        r = bot_replies(s)
        self.assertIn("지호님이라고 부를게요", r[0])
        self.assertEqual(r[1], "지호님이잖아요! 잘 기억하고 있어요.")
        s = chat(server, "j", [])
        self.assertEqual(s.obj("상태")["text"], "● 지호님과 대화 중")


class StorageTest(unittest.TestCase):
    def test_users_are_separate(self):
        server = {}
        chat(server, "minsu01", ["내 생일은 3월 14일이야"], save=True)
        s = chat(server, "jiyoung", ["내 생일 언제라고 했지?", "기억 목록"], nick="지영", save=True)
        self.assertNotIn("3월14일", flat(" ".join(bot_replies(s))))
        hist = server[s.list_names["대화기록"]]
        mem = server[s.list_names["기억저장소"]]
        self.assertEqual(sorted(x.split("|")[0] for x in hist), ["jiyoung", "minsu01"])
        self.assertEqual(sorted(x.split("|")[0] for x in mem), ["jiyoung", "minsu01"])

    def test_prefix_ids_do_not_collide(self):
        server = {}
        chat(server, "ab", ["기억해: 색 = 빨강"], save=True)
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
        s = chat(server, "u", [f"메시지 {i}" for i in range(25)] + ["가" * 300], save=True)
        blob = server[s.list_names["대화기록"]][0]
        self.assertTrue(blob.startswith("u|#대화¶"))  # 대화마다 '#대화' 줄로 시작한다
        self.assertEqual(blob.count("¶"), MAX_HISTORY_LINES + 1)
        line = [x for x in blob.split("¶") if x.startswith("나|") and x.endswith("…")]
        self.assertEqual(len(line), 1)
        self.assertEqual(len(line[0]), MAX_LINE_LEN + 1)

    def test_saved_only_with_save_command(self):
        server = {}
        s = chat(server, "s1", ["내 생일은 3월 14일이야", "안녕"])
        self.assertEqual(server[s.list_names["대화기록"]], ["s1|"])  # 칸만 있고 내용은 없다
        self.assertEqual(server[s.list_names["기억저장소"]], ["s1|"])
        s = chat(server, "s1", ["내 생일 언제라고 했지?"])
        self.assertIn("아직", bot_replies(s)[0])
        self.assertNotIn("3월 14일", bot_replies(s)[0])
        s = chat(server, "s1", ["내 생일은 3월 14일이야", "/save"])
        self.assertEqual(bot_replies(s)[1], "저장했어요! 💾 다음에 들어와도 지금까지의 대화와 기억이 이어져요.")
        self.assertIn("3월 14일", bot_replies(chat(server, "s1", ["내 생일 언제라고 했지?"]))[0])
        # 다른 말로도 저장, 로그인하지 않으면 저장할 수 없다고 알려 준다
        self.assertIn("저장했어요", bot_replies(chat({}, "s2", ["저장"]))[0])
        s = Session(PROJECT, {}, username=None, nickname=None, inputs=["/save"]).run()
        self.assertIn("로그인했을 때만", bot_replies(s)[0])

    def test_end_asks_to_save_first(self):
        s = chat({}, "s3", ["안녕", "종료", "종료", "남는 말"])
        r = bot_replies(s)
        self.assertIn("아직 저장하지 않은 대화가 1개 있어요", r[1])
        self.assertIn("즐거웠어요", r[2])
        self.assertEqual(s.inputs, ["남는 말"])
        s = chat({}, "s4", ["안녕", "/save", "종료", "남는 말"])
        self.assertIn("즐거웠어요", bot_replies(s)[2])  # 저장했으면 바로 끝낸다
        s = chat({}, "s5", ["안녕", "종료", "고마워", "종료"])
        self.assertIn("아직 저장하지 않은 대화가", bot_replies(s)[3])  # 다른 말을 했으면 다시 묻는다

    def test_new_clear_and_forget(self):
        server = {}
        chat(server, "k", ["내 생일은 3월 14일이야", "나 고양이 키워", "나비", "안녕"], save=True)
        s = chat(server, "k", ["끝말잇기", "/new", "잊어줘: 내 생일", "잊어줘: 없는거", "기억 목록"])
        lines = [(tag, t) for tag, t, _ in s.transcript_lines()]
        i = lines.index(("나", "/new"))
        self.assertEqual(lines[i + 1:i + 3], [("알림", "── 새 대화 ──"), ("봇", "새 대화를 시작해요! 오늘은 무슨 이야기를 해 볼까요?")])
        self.assertFalse(any("끝말잇기" in row for row in s.lst("화면글")))  # 화면은 새로
        r = bot_replies(s)[1:]  # (끝말잇기 대답 다음부터: '/new' 대답은 알림 줄 뒤에 있다)
        self.assertEqual(s.var("끝말"), "")  # 놀이도 새로
        self.assertNotIn("/new", [x[6] for x in records(s)])  # '/new' 는 새 대화에 남기지 않는다
        convs = s.lst("대화-내용")  # 지난 대화는 지우지 않고 왼쪽 '대화 기록'에 남는다
        self.assertEqual(len(convs), 2)
        self.assertIn("|안녕¶", convs[0])
        self.assertIn("|끝말잇기¶", convs[0])
        self.assertNotIn("끝말잇기", convs[1])
        self.assertIn("기억을 지웠어요", r[0])
        self.assertIn("기억은 없어요", r[1])
        self.assertNotIn("내 생일", memory(s))
        # /clear: 기록만 지우고 기억은 남긴다 (저장하면 서버 기록도 비워진다)
        s = chat(server, "k", ["/clear", "기억 목록", "/save"])
        self.assertIn("이 대화의 기록을 지웠어요", bot_replies(s)[0])
        self.assertIn("내 고양이", bot_replies(s)[1])
        self.assertNotIn("안녕", server[s.list_names["대화기록"]][0])
        # /clear all: 기억과 지난 이야기까지
        s = chat(server, "k", ["/clear all", "기억 목록", "지난번에 무슨 얘기 했지?"])
        r = bot_replies(s)
        self.assertIn("모두 지웠어요", r[0])
        self.assertIn("아직 기억하고 있는 게 없어요", r[1])
        self.assertIn("아직 기억나는 지난 이야기가 없어요", r[2])
        # 저장하지 않았으니 다음에 오면 그대로다
        self.assertIn("내 고양이", bot_replies(chat(server, "k", ["기억 목록"]))[0])

    def test_save_failure_is_reported(self):
        class Rejecting(list):
            def append(self, x):
                pass

        class Server(dict):
            def setdefault(self, k, v):
                return super().setdefault(k, Rejecting(v))

        s = chat(Server(), "x", ["기억해: a = b", "a", "/save"])
        self.assertIn("저장 서버에 연결하지 못해서", " ".join(t for _, t, _ in s.transcript_lines()))
        self.assertEqual(bot_replies(s)[1], "b")
        self.assertIn("저장 서버에 연결하지 못해서 지금은 저장할 수 없어요", bot_replies(s)[2])


def click(name):
    return ("click", name)


def slots(s):
    """왼쪽 '대화 기록'에 보이는 칸: [(제목, 날짜, 지금 보는 대화인지, 저장 아이콘 모양)] (위에서부터)"""
    out = []
    for k in range(1, MAX_CONVS + 1):
        o = s.obj(f"대화칸{k}")
        if not o["visible"]:
            continue
        assert s.obj(f"저장{k}")["visible"], "칸이 보이면 저장 아이콘도 보여야 함"
        title, date = o["text"].split("\n")
        out.append((title.strip(), date.strip(), o["bg"].upper() == SLOT_SEL_BG.upper(), s.shape(f"저장{k}")))
    return out


def notices(s):
    """알림 줄을 모두 이은 글 (연달아 나온 알림은 한 줄로 합쳐지므로)"""
    return " ".join(t for tag, t, _ in s.transcript_lines() if tag == "알림")


class CoverTest(unittest.TestCase):
    def test_cover_until_start_clicked(self):
        s = Session(PROJECT, {}, username="c1", nickname="민수", inputs=["안녕"], autostart=False).run()
        self.assertTrue(s.obj("표지")["visible"])
        self.assertTrue(s.obj("시작하기")["visible"])
        self.assertEqual(s.dialog_log, [])   # 시작하기를 누르기 전에는 묻지 않는다
        self.assertEqual(s.inputs, ["안녕"])
        self.assertEqual(s.shape("표지"), "표지")
        self.assertFalse(s.obj("대화칸1")["visible"])
        with self.assertRaises(EndOfInput):  # 누르면 바로 대화가 시작되고, 입력이 떨어질 때까지 이어진다
            s.click("시작하기")
        self.assertFalse(s.obj("표지")["visible"])
        self.assertFalse(s.obj("시작하기")["visible"])
        self.assertTrue(bot_replies(s))
        self.assertFalse(s.click("시작하기"), "숨은 버튼은 눌리지 않음")

    def test_cover_is_top_and_has_images(self):
        objs = PROJECT["objects"]
        self.assertEqual([o["name"] for o in objs[:2]], ["시작하기", "표지"])  # 맨 앞(맨 위)에 그려진다
        for o in objs:
            if o["objectType"] != "sprite":
                continue
            for pic in o["sprite"]["pictures"]:
                fid = pic["filename"]
                self.assertEqual(pic["fileurl"], f"temp/{fid[:2]}/{fid[2:4]}/image/{fid}.png")
                self.assertEqual(pic["thumbUrl"], f"temp/{fid[:2]}/{fid[2:4]}/thumb/{fid}.png")
        cover = next(o for o in objs if o["name"] == "표지")
        e = cover["entity"]
        self.assertEqual((e["width"] * e["scaleX"], e["height"] * e["scaleY"]), (480, 270))  # 무대를 꽉 채운다


class SidebarTest(unittest.TestCase):
    def test_new_chat_and_titles(self):
        s = chat({}, "sb1", ["오늘 시험 망쳤어", "수학", "/new", "나 고양이 키워"])
        self.assertEqual(slots(s), [("나 고양이 키워", "10/26", True, "저장하기"),
                                    ("오늘 시험 망쳤어", "10/26", False, "저장하기")])
        self.assertEqual(s.obj("대화칸2")["bg"].upper(), SLOT_BG.upper())
        self.assertEqual(s.var("현재대화"), 2)
        self.assertIn("|나 고양이 키워¶", s.lst("대화-내용")[1])
        self.assertNotIn("시험", s.lst("대화-내용")[1])
        # '＋ 새 대화' 버튼도 같은 일을 한다. 가장 최근 대화가 비어 있으면 새로 만들지 않는다
        s = chat({}, "sb2", ["안녕", click("새대화버튼"), click("새대화버튼"), "나 축구 좋아해"])
        self.assertEqual([x[0] for x in slots(s)], ["나 축구 좋아해", "안녕"])
        lines = [(tag, t) for tag, t, _ in s.transcript_lines()]
        self.assertIn(("봇", "새 대화를 시작해요! 오늘은 무슨 이야기를 해 볼까요?"), lines)
        self.assertEqual(len(s.lst("대화-내용")), 2)

    def test_title_is_shortened(self):
        s = chat({}, "sb3", ["우리 강아지가 오늘 산책하다가 넘어졌어"])
        self.assertEqual(slots(s)[0][0], "우리 강아지가 …")

    def test_save_icon_saves_that_conversation(self):
        server = {}
        s = chat(server, "sv", ["오늘 시험 망쳤어", "/new", "나 고양이 키워", click("저장2")])
        self.assertIn("💾 '오늘 시험 망쳤어' 대화를 저장했어요.", notices(s))
        self.assertEqual([x[3] for x in slots(s)], ["저장하기", "저장됨"])
        self.assertEqual(s.obj("상태")["text"], "● 민수님 · 저장 안 됨")  # 지금 보는 대화는 아직
        blob = server[s.list_names["대화기록"]][0]
        self.assertIn("시험", blob)
        self.assertNotIn("고양이", blob)  # 저장한 대화만 서버에 간다
        self.assertEqual(blob.count("#대화¶"), 1)
        # 저장한 뒤에 더 이야기하면 다시 '저장하기' 모양
        s = chat(server, "sv2", ["안녕", click("저장1"), "오늘 뭐 할까?"])
        self.assertEqual(slots(s)[0][3], "저장하기")
        self.assertEqual(s.obj("상태")["text"], "● 민수님 · 저장 안 됨")
        s = chat(server, "sv3", ["안녕", click("저장1")])
        self.assertEqual(slots(s)[0][3], "저장됨")
        self.assertEqual(s.obj("상태")["text"], "● 민수님과 대화 중")

    def test_saved_conversations_come_back(self):
        server = {}
        chat(server, "back", ["오늘 시험 망쳤어", click("저장1"), "/new", "나 고양이 키워", "나비", click("저장1"),
                              "/new", "저장 안 할 대화"])
        s = chat(server, "back", [])
        self.assertEqual(slots(s), [("나 고양이 키워", "10/26", True, "저장됨"),
                                    ("오늘 시험 망쳤어", "10/26", False, "저장됨")])
        shown = [t for tag, t, _ in s.transcript_lines()]
        self.assertIn("나 고양이 키워", shown)      # 가장 최근 대화를 펼쳐 보여 준다
        self.assertNotIn("오늘 시험 망쳤어", shown)
        self.assertEqual(s.obj("상태")["text"], "● 민수님과 대화 중")
        self.assertIn("내 고양이 이름", memory(s))

    def test_switch_conversation(self):
        server = {}
        s = chat(server, "sw", ["오늘 시험 망쳤어", "/new", "나 고양이 키워", click("대화칸2"), "다음엔 잘 볼 거야"])
        self.assertEqual(s.var("현재대화"), 1)
        self.assertEqual([x[2] for x in slots(s)], [False, True])
        convs = s.lst("대화-내용")
        self.assertIn("|다음엔 잘 볼 거야¶", convs[0])   # 고른 대화에 이어서 남는다
        self.assertNotIn("다음엔", convs[1])
        self.assertIn("|나 고양이 키워¶", convs[1])
        self.assertEqual([x[6] for x in records(s) if x[3] == "나"], ["오늘 시험 망쳤어", "다음엔 잘 볼 거야"])
        screen = [t.strip() for t, *_ in s.screen()]
        self.assertIn("오늘 시험 망쳤어", screen)
        self.assertNotIn("나 고양이 키워", screen)
        # 지금 보고 있는 칸이나 빈 칸을 누르면 아무 일도 없다
        s = chat({}, "sw2", ["안녕", click("대화칸1"), click("대화칸3"), "반가워"])
        self.assertEqual(len(s.lst("대화-내용")), 1)
        self.assertEqual(bot_replies(s)[1:], bot_replies(chat({}, "sw2", ["안녕", "반가워"]))[1:])

    def test_at_most_five_conversations(self):
        inputs = []
        for i in range(MAX_CONVS + 1):
            inputs += [f"대화 {i + 1}번", "/new"]
        s = chat({}, "many", inputs)
        self.assertEqual(len(s.lst("대화-내용")), MAX_CONVS)
        self.assertIn("가장 오래된 대화는 목록에서 뺐어요.", notices(s))
        self.assertEqual([x[0] for x in slots(s)], ["새 대화", "대화 6번", "대화 5번", "대화 4번", "대화 3번"])

    def test_guest_cannot_save(self):
        server = {}
        s = Session(PROJECT, server, username=None, nickname=None, inputs=["안녕", click("저장1"), "/new", "반가워"]).run()
        self.assertIn("💾 저장은 로그인했을 때만 할 수 있어요.", notices(s))
        self.assertEqual(len(slots(s)), 2)
        for arr in server.values():
            self.assertEqual(arr, [])

    def test_old_format_is_one_conversation(self):
        server = {}
        s = Session(PROJECT, server, username="old", nickname="민수", inputs=[]).run()
        server[s.list_names["대화기록"]][:] = ["old|나|2026-10-20|10:00|-|0|예전 형식 대화¶봇|2026-10-20|10:00|-|-|그렇군요¶"]
        s = chat(server, "old", [])
        self.assertEqual(slots(s), [("예전 형식 대화", "10/20", True, "저장됨")])
        self.assertIn("예전 형식 대화", [t for _, t, _ in s.transcript_lines()])

    def test_end_counts_unsaved_conversations(self):
        s = chat({}, "end", ["안녕", "/new", "반가워", "종료"])
        self.assertIn("아직 저장하지 않은 대화가 2개 있어요", bot_replies(s)[-1])

    def test_clicks_are_quick(self):
        s = chat({}, "fast", ["오늘 시험 망쳤어", "/new", "나 고양이 키워", click("대화칸2"), click("저장1"),
                             click("새대화버튼"), "안녕"])
        self.assertEqual(len(s.click_frames), 3)
        self.assertLess(max(s.click_frames), 120, s.click_frames)


class CommandTest(unittest.TestCase):
    def test_calculator(self):
        cases = {"계산: 12*3": "12*3 = 36", "계산: 1.5 + 2": "1.5+2 = 3.5", "계산: 10/4": "10/4 = 2.5",
                 "계산: 10 x 3": "10*3 = 30", "계산: 3--2": "3--2 = 5", "계산: -3+4": "-3+4 = 1",
                 "계산: 5/0": "0으로는 나눌 수 없어요."}
        s = chat({}, "m", list(cases))
        self.assertEqual(bot_replies(s), list(cases.values()))

    def test_translate_help_time(self):
        s = chat({}, "n", ["번역: 안녕하세요", "한국어로: hello", "도움말", "몇 시야?", "/save", "종료", "안 읽힘"])
        r = bot_replies(s)
        self.assertIn("<en:안녕하세요>", r[0])
        self.assertIn("<ko:hello>", r[1])
        self.assertIn("편하게 이야기해 보세요", r[2])
        self.assertEqual(r[3], "지금은 14시 5분이에요.")
        self.assertIn("즐거웠어요, 민수님", r[5])
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
        first = chat(server, "r2", ["나 고양이 키워", "나비", "오늘 학교에서 발표했어"], save=True)
        again = chat(server, "r2", [])
        self.assertEqual(records(again), records(first))  # ('/save' 한 줄과 그 대답까지 저장된다)
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

    def test_clear_empties_records(self):
        s = chat({}, "r6", ["안녕", "오늘 재밌었어", "/clear"])
        self.assertEqual([r[6] for r in records(s)], ["/clear", records(s)[1][6]])
        self.assertEqual(len(records(s)), 2)

    def test_works_when_tables_are_missing(self):
        """엔트리 웹에서 불러와 테이블이 빠져도 기록표를 켜기 전에는 테이블 블록을 쓰지 않는다."""
        project = without_tables(PROJECT)
        inputs = ["안녕", "오늘 시험 망쳤어", "수학", "나 고양이 키워", "나비", "블랙홀이 뭐야?", "수수께끼", "ㅋㅋ",
                  "기록표", "기록 검색: 나비", "기록 통계", "기억 목록", "/new", "/clear", "/save", "/clear all",
                  "기록표 끄기", "도움말", "?",
                  "반말 써", "끝말잇기", "기차", "그만", "가위바위보", "보", "그만", "3 곱하기 4는?", "디데이",
                  "방금 내가 뭐라고 했어?", "존댓말 써", "야르", "ㅎㅇ", "헐", "킹받네", "ㅇㅇ", "지난번에 무슨 얘기 했지?",
                  "저번에 시험 얘기 했었나?"]
        server = {}
        Session(project, server, username="t1", nickname="민수", inputs=inputs + ["/save"]).run()
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
        inputs = ["기록표 켜기"] + [f"메시지 {i}" for i in range(MAX_RECORDS // 2 + 5)] + ["/clear", "안녕"]
        s = chat({}, "r8", inputs[:-2])
        self.assertEqual(len(records(s)), MAX_RECORDS)
        self.assertEqual(as_text(s.table("대화기록표")["rows"]), as_text(records(s)))
        self.assertEqual(str(records(s)[0][0]), "13")  # 번호는 지워진 줄 다음부터 이어진다
        s = chat({}, "r9", inputs)
        self.assertEqual(as_text(s.table("대화기록표")["rows"]), as_text(records(s)))
        self.assertEqual([str(r[0]) for r in records(s)], ["1", "2", "3", "4"])


# ------------------------------------------------------------------ 더 똑똑해진 기능
class Feed:
    """입력을 하나씩 내주는 목록. 함수가 들어 있으면 그때의 세션 상태를 바꾸고 입력을 돌려준다."""
    def __init__(self, items):
        self.items, self.session = list(items), None

    def __bool__(self):
        return bool(self.items)

    def __len__(self):
        return len(self.items)

    def pop(self, i):
        x = self.items.pop(i)
        return x(self.session) if callable(x) else x


def play(inputs, server=None, user="g", seed=0, **kw):
    feed = Feed(inputs)
    s = Session(PROJECT, {} if server is None else server, username=user, nickname="민수", inputs=[], seed=seed, **kw)
    s.inputs, feed.session = feed, s
    return s.run()


def set_vars(text, **values):
    def f(s):
        for name, v in values.items():
            s.vars[s.var_names[name]] = v
        return text
    return f


def style_function():
    return next(f["id"] for f in PROJECT["functions"] if func_fields(f)[1][0][1] == "반말로 바꾸기")


HONORIFIC = re.compile(r"니다|세요|에요|예요|해요|어요|아요|군요|죠[.!?]| 저는| 제가")


class BanmalTest(unittest.TestCase):
    def test_banmal_on_off_and_saved(self):
        server = {}
        s = chat(server, "b1", ["반말 써", "안녕", "오늘 너무 피곤해", "고마워", "반말해"], save=True)
        r = bot_replies(s)
        self.assertEqual(r[0], "좋아! 이제부터 편하게 말할게. 다시 존댓말이 좋으면 '존댓말 써'라고 해 줘.")
        for reply in r[1:]:
            self.assertNotRegex(reply, HONORIFIC)
            self.assertNotIn("님", reply)
        self.assertIn("민수야", r[1])
        self.assertIn("벌써 편하게", r[4])
        # 다음에 와도 반말 (말투도 기억한다)
        s = chat(server, "b1", ["안녕", "존댓말 써", "안녕"])
        self.assertNotRegex(s.transcript_lines()[-5][1], HONORIFIC)  # 환영 인사
        r = bot_replies(s)
        self.assertNotRegex(r[0], HONORIFIC)
        self.assertIn("존댓말로 말할게요", r[1])
        self.assertIn("민수님", r[2])
        self.assertEqual(chat(server, "b1", ["존대해 줘"]).var("말투"), "존댓말")

    def test_every_way_to_ask(self):
        for text in ["반말 써", "반말로 해", "반말해도 돼", "말 놓을게", "편하게 말해 줘", "친구처럼 말해"]:
            self.assertEqual(chat({}, "b2", [text]).var("말투"), "반말", text)
        for text in ["존댓말 써", "반말 하지 마", "높임말로 해 줘"]:
            self.assertEqual(chat({}, "b3", ["반말 써", text]).var("말투"), "존댓말", text)

    def test_conversion(self):
        s = Session(PROJECT, {}, username="b", nickname="민수", inputs=[]).run()
        s.vars[s.var_names["호칭"]] = "민수"
        fid = style_function()
        cases = {
            "안녕하세요, 민수님! 저는 엔봇이에요.": "안녕, 민수야! 나는 엔봇이야.",
            "숙제 다 했어요? 대단해요! 이제 푹 쉬어요.": "숙제 다 했어? 대단해! 이제 푹 쉬어.",
            "제 이름은 엔봇이에요. 제가 기억할게요!": "내 이름은 엔봇이야. 내가 기억할게!",
            "민수님은 어떤 음식을 좋아해요?": "민수는 어떤 음식을 좋아해?",
            "천만에요! 잘 자요, 민수님.": "천만에! 잘 자, 민수.",
            "네, 알겠습니다. 감사합니다!": "응, 알겠어. 고마워!",
        }
        for src, want in cases.items():
            self.assertEqual(s.call_function(fid, [src]), want)
        # 엔봇이 하는 모든 말을 반말로 바꿔 봐도 높임말이 남지 않는다
        texts = [t for v in D.PHRASES.values() for t in v]
        for name in os.listdir(os.path.join(HERE, "knowledge")):
            with open(os.path.join(HERE, "knowledge", name), encoding="utf-8") as f:
                texts += [c for row in csv.reader(f) for c in row[1:] if re.search("[가-힣]", c)]
        for t in texts:
            out = s.call_function(fid, [t.replace("{이름}", "민수")])
            self.assertNotRegex(out, HONORIFIC, t)


class SmartTest(unittest.TestCase):
    def test_math_in_words(self):
        cases = {"12 곱하기 3은?": "12*3 = 36이에요!", "100 나누기 4는 얼마야": "100/4 = 25예요!",
                 "3+5는?": "3+5 = 8이에요!", "7 빼기 10은": "7-10 = -3이에요!", "5 나누기 0은?": "0으로는 나눌 수 없어요."}
        self.assertEqual(bot_replies(chat({}, "s1", list(cases))), list(cases.values()))

    def test_choose(self):
        cases = {"짜장면이랑 짬뽕 중에 뭐 먹을까": {"짜장면", "짬뽕"}, "피자 아니면 치킨?": {"피자", "치킨"},
                 "사과, 배, 귤 중에 골라줘": {"사과", "배", "귤"}, "축구 vs 야구": {"축구", "야구"}}
        for seed in range(6):
            for (text, options), reply in zip(cases.items(), bot_replies(chat({}, "s2", list(cases), seed=seed))):
                picked = [o for o in options if re.search(f"(^|[ !…]){o}[!에]", reply)]
                self.assertEqual(len(picked), 1, (text, reply))

    def test_dice_coin_and_numbers(self):
        for seed in range(5):
            r = bot_replies(chat({}, "s3", ["주사위 굴려줘", "동전 던져줘", "1부터 6까지 랜덤", "10에서 20 사이 숫자 골라줘",
                                            "랜덤 숫자"], seed=seed))
            self.assertIn(int(re.search(r"(\d)[이가] 나왔어요", r[0]).group(1)), range(1, 7))
            self.assertRegex(r[1], "^🪙 휙~ [앞뒷]면이 나왔어요!$")
            self.assertIn(int(re.search(r"🎲 (\d+)!", r[2]).group(1)), range(1, 7))
            self.assertIn(int(re.search(r"🎲 (\d+)!", r[3]).group(1)), range(10, 21))
            self.assertIn(int(re.search(r"🎲 (\d+)!", r[4]).group(1)), range(1, 101))

    def test_times_table(self):
        r = bot_replies(chat({}, "s4", ["구구단 7단", "9단 알려줘", "구구단"]))
        self.assertTrue(r[0].startswith("7단이에요! 7×1=7 · 7×2=14"))
        self.assertTrue(r[0].endswith("7×9=63"))
        self.assertIn("9×9=81", r[1])
        self.assertRegex(r[2], r"^[2-9]단이에요!")

    def test_recall_what_was_said(self):
        r = bot_replies(chat({}, "s5", ["구구단 3단", "방금 내가 뭐라고 했어?", "네가 방금 뭐라고 했어?"]))
        self.assertEqual(r[1], "방금 “구구단 3단”이라고 했어요.")
        self.assertEqual(r[2], "제가 방금 이렇게 말했어요. “방금 “구구단 3단”이라고 했어요.”")
        # 반말일 때도 따옴표 속 말은 그대로
        r = bot_replies(chat({}, "s6", ["안녕하세요", "반말 써", "방금 내가 뭐라고 했지?", "네가 방금 뭐라고 했어?"]))
        self.assertEqual(r[2], "방금 “반말 써”라고 했어.")
        self.assertEqual(r[3], "내가 방금 이렇게 말했어. “방금 “반말 써”라고 했어.”")

    def test_dates(self):
        # 시뮬레이터의 오늘은 2026년 10월 26일 월요일
        r = bot_replies(chat({}, "s7", ["크리스마스까지 며칠 남았어?", "12월 3일까지 며칠 남았어?", "1월 1일까지 며칠?",
                                        "어린이날 언제야?", "모레는 무슨 요일이야?", "어제는 며칠이었어?",
                                        "2월 30일까지 며칠?", "디데이", "내 생일까지 며칠 남았어?", "4월 1일이야",
                                        "내 생일은 3월 14일이야", "내 생일까지 며칠 남았어?"]))
        self.assertEqual(r[0], "크리스마스까지 60일 남았어요! (12월 25일)")
        self.assertEqual(r[1], "12월 3일까지 38일 남았어요!")
        self.assertEqual(r[2], "1월 1일까지 67일 남았어요!")
        self.assertEqual(r[3], "어린이날까지 191일 남았어요! (5월 5일)")
        self.assertEqual(r[4], "모레는 10월 28일 수요일이에요.")
        self.assertEqual(r[5], "어제는 10월 25일 일요일이에요.")
        self.assertIn("달력에 없어요", r[6])
        self.assertTrue(r[7].startswith("다가오는 날은 할로윈이에요! 5일 남았어요. (10월 31일)"))
        self.assertIn("생일이 언제예요?", r[8])
        self.assertEqual(r[11], "민수님 생일까지 139일 남았어요! (3월 14일)")

    def test_dates_across_month_and_year(self):
        def reply(now, text):
            return bot_replies(Session(PROJECT, {}, username="d", nickname="민수", inputs=[text], now=now).run())[0]
        import datetime
        self.assertEqual(reply(datetime.datetime(2026, 12, 31, 9), "내일 무슨 요일이야?"), "내일은 1월 1일 금요일이에요.")
        self.assertEqual(reply(datetime.datetime(2028, 2, 28, 9), "내일 며칠이야?"), "내일은 2월 29일 화요일이에요.")
        self.assertEqual(reply(datetime.datetime(2027, 3, 1, 9), "어제 며칠이야?"), "어제는 2월 28일 일요일이에요.")
        self.assertEqual(reply(datetime.datetime(2026, 12, 31, 9), "새해까지 며칠 남았어?"), "새해까지 1일 남았어요! (1월 1일)")
        self.assertEqual(reply(datetime.datetime(2026, 12, 25, 9), "크리스마스까지 며칠?"), "오늘이 바로 크리스마스예요! 🎉")


def next_letters(reply):
    m = re.search(r"'(.)'(?: 또는 '(.)')?(?:으로|로) 시작하는 말", reply)
    return {c for c in m.groups() if c} if m else set()


class WordChainTest(unittest.TestCase):
    words = list_data("끝말단어")

    def word_for(self, letters, used=()):
        return next((w for w in self.words if w[0] in letters and w not in used), None)

    def test_play_several_rounds(self):
        used = set()

        def answer(s):
            last = [t for tag, t, _ in s.transcript_lines() if tag == "봇"][-1]
            if not next_letters(last):  # 엔봇이 졌으면 끝
                return "그만"
            word = self.word_for(next_letters(last), used | set(s.lst("쓴말")))
            if word is None:  # 이을 낱말을 모르면 진다
                return "그만"
            used.add(word)
            return word
        s = play(["끝말잇기"] + [answer] * 6 + ["그만"], seed=4)
        r = bot_replies(s)
        self.assertTrue(r[0].startswith("좋아요, 끝말잇기! 제가 먼저 할게요."))
        mine = [t for tag, t, _ in s.transcript_lines() if tag == "나"][1:7]
        for word, reply in zip(mine, r[1:7]):
            if "이겼어요" in reply:  # 엔봇이 이을 말을 못 찾으면 진다
                self.assertIn(f"'{word[-1]}'", reply)
                break
            bot_word = reply.split("!")[0]
            self.assertIn(bot_word, self.words)
            dueum = dict(dueum_pairs()).get(word[-1])
            self.assertIn(bot_word[0], {word[-1], dueum})
            self.assertNotIn(bot_word, mine)
        self.assertIn(r[-1].replace("민수", "{이름}"), D.PHRASES["말-끝말짐"] + ["오늘 이야기 즐거웠어요, {이름}님! 다시 이야기하려면 시작 버튼을 눌러 주세요."])
        if not any("시작하는 말이 생각 안 나요" in reply for reply in r):
            self.assertEqual(str(s.var("대화중")), "1")  # 놀이 중의 '그만' 은 놀이만 멈춘다

    def test_rules(self):
        s = play(["끝말잇기", set_vars("사과", 끝말="전"), "사과", "전기", "가", set_vars("역사", 끝말="력"),
                  set_vars("성냥", 끝말="성"), "그만"])
        r = bot_replies(s)
        self.assertEqual(r[1], "앗, '사과'는 '전'으로 시작하지 않아요! 다시 해 볼래요?")
        self.assertEqual(r[2], r[1])  # 같은 말을 또 해도 놀이는 그대로
        self.assertRegex(r[3], "^기[가-힣]*! 이번엔 ")
        self.assertEqual(r[4], "두 글자 이상인 낱말로 말해 주세요!")
        self.assertRegex(r[5], "^사[가-힣]*! 이번엔 ")  # 두음법칙: '력' 차례에 '역사'
        self.assertEqual(r[6], "으… '냥'으로 시작하는 말이 생각 안 나요. 민수님이 이겼어요! 🎉")
        self.assertTrue(r[7].startswith("아직 저장하지 않은 대화가"), r[7])  # 놀이가 끝난 뒤의 '그만' 은 끝내기

    def test_hint_mentions_dueum(self):
        # 엔봇이 고를 낱말이 모두 두음법칙 글자('력', '녀'…)로 끝나는 첫 글자를 찾아서 그 글자로 끝나는 말을 한다
        dueum = dict(dueum_pairs())
        first = next(c for c in sorted({w[0] for w in self.words})
                     if all(w[-1] in dueum for w in self.words if w[0] == c))
        r = bot_replies(play(["끝말잇기", set_vars("가" + first, 끝말="가")]))
        last = r[-1].split("!")[0][-1]
        self.assertEqual(next_letters(r[-1]), {last, dueum[last]})
        self.assertIn(f"'{last}' 또는 '{dueum[last]}'", r[-1])

    def test_used_word(self):
        def repeat_bot_word(s):
            word = s.lst("쓴말")[0]
            s.vars[s.var_names["끝말"]] = word[0]
            return word
        s = play(["끝말잇기", repeat_bot_word])
        self.assertTrue(bot_replies(s)[-1].endswith("이미 나온 말이에요! 다른 말은 없을까요?"))

    def test_sentence_leaves_the_game(self):
        s = play(["끝말잇기", "오늘 학교에서 축구했어"])
        self.assertNotIn("시작하지 않아요", bot_replies(s)[-1])
        self.assertNotEqual(s.var("대기질문"), "끝말잇기")


class RockPaperScissorsTest(unittest.TestCase):
    def test_rounds_and_score(self):
        for seed in range(4):
            s = play(["가위바위보", "가위", "바위", "보", "✊", "그만", "안녕"], seed=seed)
            r = bot_replies(s)
            self.assertIn("하나를 내 주세요", r[0])
            me = bot = 0
            for mine, reply in zip([1, 2, 3, 2], r[1:5]):
                m = re.match(r"저는 (가위|바위|보)! (.*) \(민수님 (\d+) : 엔봇 (\d+)\) 또 내 주세요!$", reply)
                self.assertTrue(m, reply)
                theirs = ["가위", "바위", "보"].index(m.group(1)) + 1
                result = (mine - theirs) % 3
                me, bot = me + (result == 1), bot + (result == 2)
                self.assertEqual((int(m.group(3)), int(m.group(4))), (me, bot))
                self.assertIn({0: "비겼어요", 1: "민수님이 이겼어요", 2: "제가 이겼어요"}[result], m.group(2))
            self.assertTrue(r[5].startswith(f"가위바위보 끝! 민수님 {me} : 엔봇 {bot}."))
            self.assertEqual(str(s.var("대화중")), "1")
            self.assertNotIn("가위바위보 끝", r[6])

    def test_other_talk_leaves_the_game(self):
        r = bot_replies(chat({}, "rps", ["가위바위보", "오늘 너무 피곤해"]))
        self.assertNotIn("저는", r[1])


# ------------------------------------------------------------------ 신조어 · 초성체
def slang_rows():
    with open(os.path.join(HERE, "knowledge", "표-신조어.csv"), encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


def slang_options(piece):
    """신조어 표에서 찾을 말이 piece 인 줄의 대답들 ({이름} 채우고 [표시] 뗀 모양)."""
    answers = next(r[3] for r in slang_rows() if r[1] == piece)
    return [re.sub(r" ?\[[^\]]*\]$", "", a.strip()).replace("{이름}", "민수") for a in answers.split(" | ")]


class SlangTest(unittest.TestCase):
    def test_replies(self):
        for text, piece in [("야르", "야르"), ("야르~~", "야르"), ("ㅎㅇ", "ㅎㅇ"), ("킹받네", "킹받"), ("어쩔티비", "어쩔티비"),
                            ("ㅂㅇ", "ㅂㅇ"), ("헐", "헐"), ("헐!!", "헐"), ("ㅋ", "ㅋ"), ("중꺾마", "중꺾마"),
                            ("럭키비키", "럭키비키"), ("ㅅㅂ", "ㅅㅂ"), ("오히려 좋아", "오히려좋아"), ("ㄹㅇ", "ㄹㅇ")]:
            for seed in range(2):
                reply = bot_replies(chat({}, "sl", [text], seed=seed))[0]
                self.assertIn(reply, slang_options(piece), text)

    def test_meanings(self):
        rows = {r[0]: r[2] for r in slang_rows()}
        r = bot_replies(chat({}, "sl2", ["야르가 뭐야?", "킹받다가 뭐야?", "ㅎㅇ가 뭐야?", "어쩔티비가 뭐야?"]))
        self.assertEqual(r[0], "야르는 " + rows["야르"])
        self.assertEqual(r[1], "킹받다는 " + rows["킹받다"])
        self.assertEqual(r[2], "ㅎㅇ는 " + rows["ㅎㅇ"])
        self.assertEqual(r[3], "어쩔티비는 " + rows["어쩔티비"])

    def test_feelings_in_sentences(self):
        s = chat({}, "sl3", ["오늘 학교에서 친구가 놀려서 진짜 킹받았어"])
        self.assertLess(int(s.var("감정점수")), 0)
        self.assertTrue(bot_replies(s)[0].startswith("오늘 학교에서 친구가 놀려서 진짜 킹받았군요."))
        for text in ["오늘 축구 개웃겼어", "시험 잘 봤어", "완전 핵꿀잼이었어"]:
            self.assertGreater(int(chat({}, "sl4", [text]).var("감정점수")), 0, text)

    def test_not_saved_as_answer(self):
        """엔봇이 물어본 것('롤모델이 누구예요?')에 신조어·초성체로 대답하면 기억하지 않는다."""
        for text in ["어쩔티비", "ㅇㅇ", "ㅋㅋㅋ", "야르"]:
            s = play([set_vars(text, 대기질문="사실:내 롤모델")])
            self.assertNotIn("내 롤모델", memory(s), text)
        s = play([set_vars("민수가 롤모델이야", 대기질문="사실:내 롤모델")])  # 보통 대답은 그대로 기억
        self.assertNotIn("내 롤모델", [k for k in memory(s) if memory(s)[k] == "F:ㅇㅇ"])

    def test_chosung_yes_and_banmal_mode(self):
        # '오늘 기분 어때요?' 에 'ㅇㅇ' (= 응)
        for seed in range(3):
            r = bot_replies(chat({}, "sl5", ["안녕", "ㅇㅇ"], seed=seed))
            self.assertIn(r[1], [p.replace(" [이야기]", "") for p in D.PHRASES["말-기분응"]])
        # '더 들려줄래요?' 에 'ㅇㅇ'
        r = bot_replies(play(["ㅋㅋ", "ㅇㅇ"]))
        self.assertIn(r[1], [p.split(" [")[0] for p in D.PHRASES["말-응대답"]])
        self.assertEqual(chat({}, "sl6", ["반모"]).var("말투"), "반말")
        self.assertEqual(chat({}, "sl7", ["반모가 뭐야?"]).var("말투"), "존댓말")


# ------------------------------------------------------------------ 지난 이야기 (예전 대화 참고)
def visit(server, inputs, day, seed=0):
    """그날 접속해서 이야기하고 /save 한다."""
    now = datetime.datetime(2026, 10, 26, 14, 5) + datetime.timedelta(days=day)
    return Session(PROJECT, server, username="past", nickname="민수", inputs=list(inputs) + ["/save"], seed=seed,
                   now=now).run()


def welcome_of(s):
    lines = s.transcript_lines()
    start = max([i for i, (_, t, _) in enumerate(lines) if "이어서" in t] + [-1]) + 1
    return next(t for tag, t, _ in lines[start:] if tag == "봇")


class PastTalkTest(unittest.TestCase):
    def test_links_same_topic_across_days(self):
        server = {}
        s = visit(server, ["오늘 수학 시험 망쳤어", "나 강아지 키워"], 0)
        self.assertEqual(s.lst("이야기주제"), ["시험", "강아지"])
        # 다음 날: 마지막 주제로 한 말을 꺼내 인사하고, 시험 이야기가 나오면 그때 기분과 견준다
        s = visit(server, ["시험 결과 나왔는데 생각보다 잘 봤어", "시험 진짜 다행이야", "강아지랑 산책했는데 너무 좋았어"], 1)
        self.assertEqual(welcome_of(s), "민수님, 다시 왔군요! 어제 “나 강아지 키워”라고 했었죠. 그 뒤로 어떻게 됐어요?")
        r = bot_replies(s)
        self.assertTrue(r[0].startswith("어제는 “오늘 수학 시험 망쳤어”라고 하면서 속상해했는데, 이번엔 기분이 좋아 보여서 다행이에요! "),
                        r[0])
        self.assertFalse(r[1].startswith("어제"), r[1])  # 같은 대화에서는 한 번만
        s = visit(server, ["시험 또 망했어", "시험 너무 싫어"], 3)
        self.assertTrue(welcome_of(s).startswith("민수님, 다시 왔군요! 2일 전에 “강아지랑 산책했는데 너무 좋았어”라고 했었죠. 요즘도"))
        r = bot_replies(s)
        self.assertTrue(r[0].startswith("2일 전에는 “시험 진짜 다행이야”라고 하면서 즐거워했는데, 이번엔 속상한 일이 있었군요. "),
                        r[0])
        s = visit(server, [], 20)
        self.assertEqual(welcome_of(s), "민수님, 다시 왔군요! 지난번(10월 29일)에 “시험 너무 싫어”라고 했었죠. 그 뒤로 좀 괜찮아졌어요?")

    def test_same_feeling_and_banmal(self):
        server = {}
        visit(server, ["강아지가 아파서 걱정돼"], 0)
        visit(server, ["반말 써", "오늘 학교 재밌었어"], 1)
        s = visit(server, ["강아지가 아직도 아파서 슬퍼"], 2)
        reply = bot_replies(s)[0]
        # 따옴표 속 내 말은 반말로 바꾸지 않는다
        self.assertTrue(reply.startswith("2일 전에도 “강아지가 아파서 걱정돼”라고 하면서 힘들어했지… "), reply)

    def test_ask_about_past(self):
        server = {}
        r = bot_replies(visit(server, ["지난번에 무슨 얘기 했지?"], 0))
        self.assertIn("아직 기억나는 지난 이야기가 없어요", r[0])
        visit(server, ["오늘 수학 시험 망쳤어", "나 강아지 키워", "강아지랑 산책해서 너무 좋았어"], 0)
        r = bot_replies(visit(server, ["지난번에 무슨 얘기 했지?", "저번에 시험 얘기 했었나?", "예전에 축구 얘기 했었나?"], 2))
        self.assertEqual(r[0].split(" · ")[0], "기억나요! 최근에 나눈 이야기예요.")
        self.assertIn("· 10월 26일 산책: “강아지랑 산책해서 너무 좋았어”", r[0])
        self.assertIn("· 10월 26일 시험: “오늘 수학 시험 망쳤어”", r[0])
        self.assertEqual(r[1], "2일 전에 시험 이야기를 할 때 “오늘 수학 시험 망쳤어”라고 했어요.")
        self.assertTrue(r[2].startswith("축구는 기억에 없어요. 최근에는 이런 이야기를 했어요."), r[2])
        # 기억 목록에도 보인다
        self.assertIn("· 지난 이야기: 시험, 강아지, 산책", bot_replies(visit(server, ["기억 목록"], 2))[0])

    def test_quiet_talk_brings_back_old_topic(self):
        found = False
        for seed in range(8):
            server = {}
            visit(server, ["오늘 수학 시험 망쳤어", "나 강아지 키워", "강아지랑 산책해서 너무 좋았어"], 0)
            replies = bot_replies(visit(server, ["음", "음…", "흠"], 1, seed=seed))
            found = found or any("그러고 보니 어제 " in r and "그 뒤로 어떻게 됐어요?" in r for r in replies)
        self.assertTrue(found)

    def test_saved_trimmed_and_private(self):
        server = {}
        with open(os.path.join(HERE, "knowledge", "표-주제.csv"), encoding="utf-8") as f:
            topics = [r[0] for r in csv.reader(f)][1:]
        topics = [t for t in topics if re.fullmatch("[가-힣]{2,4}", t)][:MAX_DIARY + 3]
        s = visit(server, [f"{t} 때문에 너무 신났어" for t in topics] + ["내 비밀번호는 1234야"], 0)
        self.assertEqual(s.lst("이야기주제"), [t for t in topics if t in s.lst("이야기주제")])
        self.assertEqual(len(s.lst("이야기주제")), MAX_DIARY)
        s2 = visit(server, [], 1)
        self.assertEqual(s2.lst("이야기주제"), s.lst("이야기주제"))
        self.assertEqual(s2.lst("이야기값"), s.lst("이야기값"))
        self.assertNotIn("1234", json.dumps(server, ensure_ascii=False))

    def test_bad_saved_lines_are_skipped(self):
        server = {}
        visit(server, ["오늘 수학 시험 망쳤어"], 0)
        mem = server[next(v["id"] for v in PROJECT["variables"] if v["name"] == "기억저장소")]
        i = next(i for i, x in enumerate(mem) if x.startswith("past|"))
        mem[i] += "@=x¶@고장=2026|1¶@축구=2026-10-26/1/좋아¶@수학=2026-10-26|2|재밌어¶"
        s = visit(server, ["수학 진짜 재밌었어"], 1)
        self.assertEqual(s.lst("이야기주제")[:2], ["시험", "수학"])
        self.assertTrue(bot_replies(s)[0].startswith("어제도 수학 이야기를 했었죠! 그때 “재밌어”라고 했어요. "), bot_replies(s)[0])


# ------------------------------------------------------------------ 단어 뜻
def definition_rows():
    with open(os.path.join(HERE, "knowledge", "표-단어뜻.csv"), encoding="utf-8") as f:
        return list(csv.reader(f))[1:]


class DefinitionTest(unittest.TestCase):
    def test_many_definitions(self):
        rows = definition_rows()
        self.assertGreaterEqual(len(rows), 1700)
        self.assertEqual(len(rows), len({r[0] for r in rows}))
        for word, meaning, category in rows:
            self.assertTrue(meaning.strip() and category.strip(), word)
            self.assertNotRegex(meaning, r"[\[\]|¤¶]", word)  # 템플릿 기호와 저장 구분 기호는 쓰지 않는다

    def test_every_word_alone_gets_its_meaning(self):
        """'장영실'처럼 낱말 하나만 말해도 뜻을 알려 준다 (일상 대화 키워드·명령·신조어는 그쪽 대답)."""
        talk = {k.split("|", 1)[1] for k in list_data("지식키") if k.startswith("말|")}
        skip = talk | set(list_data("신조어목록")) | {"통계", "구구단", "존댓말", "높임말", "비밀번호"}
        rows = [r for r in definition_rows() if r[0] not in skip and "{" not in r[1]]
        self.assertGreater(len(rows), 1650)
        wrong = []
        for i in range(0, len(rows), 40):
            chunk = rows[i:i + 40]
            # (엔봇이 바로 앞에서 물어본 게 없을 때 — 물어봤으면 낱말 하나도 그 대답으로 받는다)
            s = play([set_vars(r[0], 대기질문="") for r in chunk], seed=i)
            for (word, meaning, _), reply in zip(chunk, bot_replies(s)):
                if not (reply.startswith(word) and meaning in reply):
                    wrong.append((word, reply))
        self.assertEqual(wrong, [])

    def test_alone_with_josa_marks_and_banmal(self):
        r = bot_replies(chat({}, "w1", ["장영실", "블랙홀!", "광합성?", "원숭이", "울릉도", "민주주의"]))
        self.assertEqual(r[0], "장영실은 조선 세종 때의 과학자예요. 해시계, 물시계, 측우기를 만들었어요.")
        self.assertTrue(r[1].startswith("블랙홀은 "))
        self.assertTrue(r[2].startswith("광합성은 "))
        self.assertTrue(r[3].startswith("원숭이는 손발로"))   # '원숭이' 를 '원숭'+'이' 로 자르지 않는다
        self.assertTrue(r[4].startswith("울릉도는 동해에"))
        self.assertTrue(r[5].startswith("민주주의는 "))
        r = bot_replies(chat({}, "w2", ["반말 써", "개미", "메아리가 뭐야?"]))
        self.assertTrue(r[1].startswith("개미는 "), r[1])
        self.assertNotRegex(r[1], HONORIFIC)
        self.assertEqual(r[2], "메아리는 산이나 벽에 부딪힌 소리가 되돌아와 다시 들리는 거야.")

    def test_topic_word_gets_follow_up_but_not_a_fact_question(self):
        topics = dict((k.split("|", 1)[1], v) for k, v in zip(list_data("지식키"), list_data("지식값")) if k.startswith("주|"))
        s = chat({}, "w3", ["학교"])
        meaning = dict((r[0], r[1]) for r in definition_rows())["학교"]
        self.assertEqual(bot_replies(s)[0], f"학교는 {meaning} " + topics["학교"].split(" [")[0])
        # '고양이 이름이 뭐예요? [사실:…]' 처럼 내 것을 묻는 질문은 붙이지 않아서, 다음 말이 이름으로 기억되지 않는다
        s = chat({}, "w4", ["고양이", "축구"])
        self.assertNotEqual(s.var("대기질문")[:3], "사실:")
        self.assertNotIn("내 고양이 이름", memory(s))
        self.assertTrue(bot_replies(s)[1].startswith("축구는 "))

    def test_one_word_answer_to_a_question_is_an_answer(self):
        # '어떤 과목 시험이었어요? [이야기]' 에 '수학' → 뜻이 아니라 대답으로 받는다
        r = bot_replies(chat({}, "w9", ["오늘 시험 망쳤어", "수학"]))
        self.assertFalse(r[1].startswith("수학은 "), r[1])
        self.assertIn("수학", r[1])
        # '왜 그랬어요? [이유]' 에 낱말 하나 → 이유로 받는다
        r = bot_replies(play([set_vars("숙제", 대기질문="이유")]))
        self.assertFalse(r[0].startswith("숙제는 "), r[0])
        # 물어본 게 이야기여도 주제가 아닌 낱말은 뜻을 알려 준다
        r = bot_replies(play([set_vars("장영실", 대기질문="이야기")]))
        self.assertTrue(r[0].startswith("장영실은 "), r[0])
        # '오늘 하루는 어땠어요? [기분]' 에 '행복' → 기분 대답, '장영실' → 뜻
        r = bot_replies(play([set_vars("행복", 대기질문="기분"), set_vars("장영실", 대기질문="기분")]))
        self.assertFalse(r[0].startswith("행복은 "), r[0])
        self.assertTrue(r[1].startswith("장영실은 "), r[1])

    def test_answers_and_memory_come_first(self):
        # 엔봇이 물어본 것의 대답이면 기억한다
        s = play([set_vars("고양이", 대기질문="사실:내가 좋아하는 동물")])
        self.assertEqual(memory(s).get("내가 좋아하는 동물"), "F:고양이")
        # 기억해 둔 이름 '나비' 는 곤충 나비가 아니라 내 고양이
        r = bot_replies(chat({}, "w5", ["나 고양이 키워", "나비", "나비"]))
        self.assertTrue(r[2].startswith("민수님의 고양이 나비 말이죠?"), r[2])
        # 일상 대화 키워드와 똑같은 말은 그 대답
        self.assertIn("정답은", bot_replies(chat({}, "w6", ["수수께끼"]))[0])

    def test_questions_about_meaning(self):
        r = bot_replies(chat({}, "w7", ["이순신 장군이 누구야?", "광합성에 대해 알려줘", "설명문이 뭐야?", "울릉도는 뭐야?"]))
        self.assertTrue(r[0].startswith("이순신은 "))
        self.assertTrue(r[1].startswith("광합성은 "))
        self.assertTrue(r[2].startswith("설명문은 "))
        self.assertTrue(r[3].startswith("울릉도는 "))
        # 내 일을 묻는 말에는 사전 뜻을 말하지 않는다
        for text in ["오늘 학교에서 뭐 배웠는지 알아?", "내 친구 알아?"]:
            self.assertFalse(bot_replies(chat({}, "w8", [text]))[0].startswith(("학교는", "친구는")), text)


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
                  "고양이", "시험", "때문에", "해서", "몰라", "응", "너는", "a" * 40, "반말 써", "존댓말", "끝말잇기",
                  "가위바위보", "보", "그만", "주사위", "동전 던져", "중에", "아니면", "vs", "곱하기", "나누기", "부터",
                  "까지", "에서", "사이", "며칠", "월", "일", "디데이", "방금", "뭐라고", "구구단", "단", "내일", "¤",
                  "야르", "ㅎㅇ", "ㅋ", "헐", "개", "킹받", "@", "지난번", "무슨얘기", "저번에", "기억나", "잘", "반모"]
        buttons = ["새대화버튼", "대화칸1", "대화칸2", "대화칸5", "저장1", "저장2", "저장3"]
        server = {}
        users = ["u1", "u2", "user_3", "4"]
        worst = 0
        for n in range(120):
            inputs = ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(1, 7))]
            for _ in range(rng.randint(0, 3)):
                inputs.insert(rng.randint(0, len(inputs)), click(rng.choice(buttons)))
            user = rng.choice(users + [None])
            try:
                s = Session(PROJECT, server, username=user, nickname=user, inputs=inputs, seed=n).run()
            except EntryError as e:
                self.fail(f"입력 {inputs!r} (사용자 {user}) 에서 블록 오류: {e}")
            self.assertLessEqual(len(s.lst("화면글")), 9)
            self.assertEqual(len(s.lst("내질문")), len(s.lst("내답변")))
            self.assertLessEqual(len(s.lst("대화-내용")), MAX_CONVS)
            self.assertEqual(len(s.lst("대화-내용")), len(s.lst("대화-저장본")))
            worst = max([worst] + s.turn_frames[1:] + s.click_frames)
        self.assertLess(worst, 400, "부스트 모드 없이 한 번 대답하는 데 너무 오래 걸림")
        for item in server[s.list_names["대화기록"]]:
            convs = item.split("#대화¶")[1:]
            self.assertLessEqual(len(convs), MAX_CONVS)
            for c in convs:
                self.assertLessEqual(c.count("¶"), MAX_HISTORY_LINES)


if __name__ == "__main__":
    unittest.main(verbosity=2)
