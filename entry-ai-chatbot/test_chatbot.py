#!/usr/bin/env python3
"""엔트리 AI 챗봇 작품 검사.

1) 구조 검사: 모든 블록이 entryjs 의 블록 정의(파라미터 개수·종류·드롭다운 값)와 맞는지
2) .ent 압축 파일 검사
3) 시뮬레이션: 여러 사용자가 번갈아 쓰는 상황, 기록·기억 저장, 오류 없는지 (무작위 입력 포함)

실행:  python3 test_chatbot.py
"""
import io
import json
import os
import random
import tarfile
import unittest

from simulate import EntryError, Session

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT = json.load(open(os.path.join(HERE, "project.json"), encoding="utf-8"))

B, I, T, L, TI = "Block", "Indicator", "Text", "LineBreak", "TextInput"
COMPARE = ["EQUAL", "NOT_EQUAL", "GREATER", "LESS", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"]
LANGS = ["ko", "en", "ja", "zh-CN", "zh-TW", "es", "fr", "de", "ru", "pt", "th", "vi", "id", "hi"]

# entrylabs/entryjs (e01b81b, 2026-09) src/playground/blocks 의 params 정의를 옮긴 것.
# ("D", [값...]) = Dropdown, ("DD", 메뉴) = DropdownDynamic
SCHEMA = {
    "when_run_button_click": ([I], 0),
    "when_message_cast": ([I, ("DD", "messages")], 0),
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
    "show_list": ([("DD", "lists"), I], 0),
    "boolean_basic_operator": ([B, ("D", COMPARE), B], 0),
    "boolean_and_or": ([B, ("D", ["AND", "OR"]), B], 0),
    "boolean_not": ([T, B, T], 0),
    "calc_basic": ([B, ("D", ["PLUS", "MINUS", "MULTI", "DIVIDE"]), B], 0),
    "calc_rand": ([T, B, T, B, T], 0),
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
    "dialog": ([B, ("D", ["speak", "think", "yell"]), I], 0),
    "remove_dialog": ([I], 0),
    "get_translated_string": ([("D", LANGS), B, ("DD", "translate")], 0),
    "text": ([TI], 0),
    "number": ([TI], 0),
}
VALUE_BLOCKS = {
    "get_canvas_input_value", "get_variable", "value_of_index_from_list", "length_of_list",
    "boolean_basic_operator", "boolean_and_or", "boolean_not", "calc_basic", "calc_rand", "get_date",
    "get_user_name", "get_nickname", "length_of_string", "reverse_of_string", "combine_something",
    "char_at", "substring", "count_match_string", "index_of_string", "replace_string",
    "change_string_case", "get_translated_string", "text", "number",
}
EVENT_BLOCKS = {"when_run_button_click", "when_message_cast"}


def threads():
    for o in PROJECT["objects"]:
        for t in json.loads(o["script"]):
            yield o, t


def walk(block, fn, depth=0):
    fn(block, depth)
    for p in block["params"]:
        if isinstance(p, dict):
            walk(p, fn, depth + 1)
    for st in block.get("statements", []):
        for b in st:
            walk(b, fn, depth)


def ids_of(kind):
    if kind == "variables":
        return {v["id"] for v in PROJECT["variables"] if v["variableType"] != "list"}
    if kind == "lists":
        return {v["id"] for v in PROJECT["variables"] if v["variableType"] == "list"}
    return {m["id"] for m in PROJECT["messages"]}


class StructureTest(unittest.TestCase):
    def test_blocks_match_entry_schema(self):
        seen_ids = set()
        problems = []

        def check(b, _depth):
            t = b["type"]
            if b["id"] in seen_ids:
                problems.append(f"중복 id {b['id']}")
            seen_ids.add(b["id"])
            if t not in SCHEMA:
                problems.append(f"모르는 블록 {t}")
                return
            kinds, n_st = SCHEMA[t]
            params = b["params"]
            if t in ("text", "number"):
                if len(params) != 1 or not isinstance(params[0], str):
                    problems.append(f"{t} 값이 문자열이 아님: {params}")
                return
            if len(params) > len(kinds):
                problems.append(f"{t} 파라미터가 너무 많음 {len(params)} > {len(kinds)}")
            for i, p in enumerate(params):
                k = kinds[i]
                if k == B:
                    if p is not None and not (isinstance(p, dict) and p["type"] in VALUE_BLOCKS):
                        problems.append(f"{t}[{i}] 값 블록 자리에 {p!r}")
                elif isinstance(k, tuple) and k[0] == "D":
                    if p not in k[1]:
                        problems.append(f"{t}[{i}] 드롭다운 값 {p!r}")
                elif isinstance(k, tuple) and k[0] == "DD":
                    if k[1] == "translate":
                        if p not in LANGS:
                            problems.append(f"{t}[{i}] 번역 언어 {p!r}")
                    elif p not in ids_of(k[1]):
                        problems.append(f"{t}[{i}] 없는 {k[1]} id {p!r}")
                elif p is not None:
                    problems.append(f"{t}[{i}] ({k}) 자리에 {p!r}")
            if len(b.get("statements", [])) != n_st:
                problems.append(f"{t} statements 개수 {len(b.get('statements', []))} != {n_st}")

        for _o, t in threads():
            self.assertIn(t[0]["type"], EVENT_BLOCKS)
            for i, b in enumerate(t):
                if i > 0:
                    self.assertNotIn(b["type"], VALUE_BLOCKS | EVENT_BLOCKS, b["type"])
                walk(b, check)
                for st_blocks in [s for b2 in [b] for s in b2.get("statements", [])]:
                    for sb in st_blocks:
                        self.assertNotIn(sb["type"], VALUE_BLOCKS | EVENT_BLOCKS)
        self.assertEqual(problems, [])

    def test_statement_blocks_never_value_blocks(self):
        def check(b, _d):
            for st in b.get("statements", []):
                for sb in st:
                    self.assertNotIn(sb["type"], VALUE_BLOCKS | EVENT_BLOCKS)
        for _o, t in threads():
            for b in t:
                walk(b, check)

    def test_every_message_has_handler(self):
        handled = {t[0]["params"][1] for _o, t in threads() if t[0]["type"] == "when_message_cast"}
        self.assertEqual(handled, ids_of("messages"))

    def test_project_fields(self):
        p = PROJECT
        self.assertEqual(p["aiUtilizeBlocks"], ["translate"])
        types = {o["objectType"] for o in p["objects"]}
        self.assertEqual(types, {"textBox"})
        rt = [v["name"] for v in p["variables"] if v.get("isRealTime")]
        self.assertEqual(sorted(rt), ["기억저장소", "대화기록"])
        names = [v["name"] for v in p["variables"]]
        self.assertEqual(len(names), len(set(names)), "변수/리스트 이름 중복")
        kw = [v for v in p["variables"] if v["name"] == "키워드"][0]["array"]
        ans = [v for v in p["variables"] if v["name"] == "키워드답변"][0]["array"]
        self.assertEqual(len(kw), len(ans))
        for k in kw:
            self.assertTrue(k["data"] and k["data"] == k["data"].lower() and " " not in k["data"])

    def test_ent_archive(self):
        with tarfile.open(os.path.join(HERE, "entry-ai-chatbot.ent"), "r:gz") as tar:
            self.assertIn("temp/project.json", tar.getnames())
            data = json.load(io.TextIOWrapper(tar.extractfile("temp/project.json"), encoding="utf-8"))
        self.assertEqual(data, PROJECT)


def flat(text):
    """대화창은 줄을 나눠 보여 주므로, 공백·줄바꿈을 모두 지우고 비교한다."""
    return "".join(text.split())


def said(s):
    return flat("".join(s.transcript))


def session(server, user, inputs, nick=None, seed=0):
    return Session(PROJECT, server, username=user, nickname=nick or user, inputs=inputs, seed=seed).run()


class ConversationTest(unittest.TestCase):
    def test_memory_and_history_persist_per_user(self):
        server = {}
        s1 = session(server, "minsu01", ["안녕", "기억해: 내 생일 = 3월 14일", "내 생일이 언제야?"], nick="민수")
        self.assertEqual(s1.transcript[-1], "봇: 3월 14일")
        # 다른 사용자는 민수의 기억을 모른다
        s2 = session(server, "jiyoung", ["내 생일이 언제야?", "기억 목록"], nick="지영")
        joined2 = said(s2)
        self.assertNotIn("3월14일", joined2)
        self.assertIn(flat("아직 가르쳐 준 게 없어요"), joined2)
        self.assertNotIn("지난대화", joined2)
        # 민수가 다시 오면 기록과 기억이 남아 있다
        s3 = session(server, "minsu01", ["내 생일 알아?"], nick="민수")
        joined3 = said(s3)
        self.assertIn("지난대화", joined3)
        self.assertIn(flat("다시 만나서 반가워요"), joined3)
        self.assertIn(flat("나: 기억해: 내 생일 = 3월 14일"), joined3)
        self.assertEqual(s3.transcript[-1], "봇: 3월 14일")
        # 서버에는 사용자마다 한 칸씩
        hist = server[s3.list_names["대화기록"]]
        mem = server[s3.list_names["기억저장소"]]
        self.assertEqual(sorted(x.split("|")[0] for x in hist), ["jiyoung", "minsu01"])
        self.assertEqual(sorted(x.split("|")[0] for x in mem), ["jiyoung", "minsu01"])
        self.assertIn("minsu01|내 생일=3월 14일¶", mem)

    def test_prefix_ids_do_not_collide(self):
        server = {}
        session(server, "ab", ["기억해: 색 = 빨강"])
        s = session(server, "a", ["색 알려줘", "기억 목록"])
        self.assertIn(flat("아직 가르쳐 준 게 없어요"), said(s))
        s = session(server, "abc", ["기억 목록"])
        self.assertIn(flat("아직 가르쳐 준 게 없어요"), said(s))
        s = session(server, "ab", ["색 알려줘"])
        self.assertEqual(s.transcript[-1], "봇: 빨강")

    def test_guest_mode_saves_nothing(self):
        server = {}
        s = session(server, None, ["안녕", "기억해: 비밀 = 123", "비밀"])
        joined = said(s)
        self.assertIn(flat("로그인하지 않아서"), joined)
        self.assertIn(flat("이번 실행에서만 기억해요"), joined)
        self.assertEqual(s.transcript[-1], "봇: 123")
        for arr in server.values():
            self.assertEqual(arr, [])

    def test_new_chat_and_forget(self):
        server = {}
        session(server, "u1", ["기억해: 강아지 이름 = 초코", "안녕"])
        s = session(server, "u1", ["새 대화"])
        hist = server[s.list_names["대화기록"]]
        self.assertEqual(hist, ["u1|봇: 대화 기록을 모두 지웠어요. 새로 시작해요! (가르쳐 준 기억은 그대로예요.)¶"])
        s = session(server, "u1", ["강아지 이름 뭐야", "잊어줘: 강아지 이름", "강아지 이름 뭐야", "잊어줘: 없는거"])
        self.assertIn("봇: 초코", s.transcript)
        self.assertIn(flat("'강아지 이름'에 대한 기억을 지웠어요."), said(s))
        self.assertIn(flat("'없는거'(이)라는 기억은 없어요."), said(s))
        self.assertEqual(said(s).count("봇:초코"), 1)
        self.assertEqual(server[s.list_names["기억저장소"]], ["u1|"])

    def test_teach_update_and_limits(self):
        server = {}
        inputs = [f"기억해: 질문{i} = 답{i}" for i in range(35)] + ["기억해: 질문34 = 바뀐답", "질문34"]
        s = session(server, "u", inputs)
        self.assertEqual(len(s.lst("내질문")), 30)
        self.assertEqual(s.lst("내질문")[0], "질문5")
        self.assertEqual(s.transcript[-1], "봇: 바뀐답")
        blob = server[s.list_names["기억저장소"]][0]
        self.assertEqual(blob.count("¶"), 30)
        # 잘못된 형식
        s = session(server, "u", ["기억해: 그냥", "기억해: = 답만", "기억해: 질문만 =", "기억해:"])
        self.assertEqual(said(s).count(flat("봇: 이렇게 입력해 주세요 → 기억해: 질문 = 답")), 4)

    def test_history_is_trimmed(self):
        server = {}
        long = "가" * 300
        s = session(server, "u", [f"메시지 {i}" for i in range(40)] + [long, "줄¶바꿈 시도"])
        blob = server[s.list_names["대화기록"]][0]
        self.assertTrue(blob.startswith("u|"))
        self.assertEqual(blob.count("¶"), 30)
        self.assertIn("¶나: " + "가" * 117 + "…¶", blob)
        self.assertIn("나: 줄 바꿈 시도", blob)
        self.assertLessEqual(len(s.lst("대화창")), 9)

    def test_calculator_and_commands(self):
        cases = {
            "계산: 12*3": "12*3 = 36", "계산: 1.5 + 2": "1.5+2 = 3.5", "계산: 10/4": "10/4 = 2.5",
            "계산: 10 x 3": "10*3 = 30", "계산: 8÷2": "8/2 = 4", "계산: 3--2": "3--2 = 5",
            "계산: -3+4": "-3+4 = 1", "계산: 5/0": "0으로는 나눌 수 없어요.",
        }
        server = {}
        for q, a in cases.items():
            s = session(server, "c", [q])
            self.assertEqual(s.transcript[-1], "봇: " + a, q)
        for bad in ["계산: abc+1", "계산: 2*3+4", "계산: +", "계산: 7", "계산:"]:
            s = session(server, "c", [bad])
            self.assertIn(flat("식을 이해하지 못했어요"), said(s), bad)

    def test_translate_commands(self):
        s = session({}, "t", ["번역: 안녕하세요", "한국어로: hello", "영어로:", "번역 : 반가워"])
        joined = said(s)
        self.assertIn(flat("영어로는 이렇게 말해요 → <en:안녕하세요>"), joined)
        self.assertIn(flat("한국어로는 이렇게 말해요 → <ko:hello>"), joined)
        self.assertIn(flat("번역할 문장도 같이"), joined)
        self.assertIn("<en:반가워>", joined)

    def test_exit_command(self):
        s = session({}, "e", ["종료", "이건 안 읽힘"])
        self.assertIn(flat("대화를 마칠게요"), said(s))
        self.assertEqual(s.inputs, ["이건 안 읽힘"])
        self.assertEqual(s.dialog_log[-1], "다음에 또 만나요!")

    def test_save_failure_is_reported(self):
        class Rejecting(list):
            def append(self, x):
                pass

        class Server(dict):
            def setdefault(self, k, v):
                return super().setdefault(k, Rejecting(v))

        server = Server()
        s = session(server, "x", ["기억해: a = b", "a"])
        joined = said(s)
        self.assertIn(flat("저장 서버에 연결하지 못해서"), joined)
        self.assertIn(flat("이번 실행에서만 기억해요"), joined)
        self.assertEqual(s.transcript[-1], "봇: b")

    def test_random_inputs_never_crash(self):
        rng = random.Random(7)
        pieces = ["안녕", "기억해:", "잊어줘:", "번역:", "계산:", "=", ":", "¶", "|", " ", "  ", "1", "0", "-", "+",
                  "*", "/", "x", "가나다", "abc", "ㅋㅋ", "도움말", "기억 목록", "새 대화", "몇 시", "오늘 며칠",
                  "{이름}", "…", "😀", "a" * 50, "한국어로:", "?"]
        server = {}
        users = ["u1", "u2", "user_3", "4"]
        for n in range(150):
            inputs = ["".join(rng.choice(pieces) for _ in range(rng.randint(0, 6))) for _ in range(rng.randint(1, 8))]
            user = rng.choice(users + [None])
            try:
                s = session(server, user, inputs, seed=n)
            except EntryError as e:
                self.fail(f"입력 {inputs!r} (사용자 {user}) 에서 블록 오류: {e}")
            self.assertLessEqual(len(s.lst("대화창")), 9)
        hist = server[s.list_names["대화기록"]]
        mem = server[s.list_names["기억저장소"]]
        self.assertEqual(sorted(x.split("|")[0] for x in hist), sorted(users))
        self.assertEqual(sorted(x.split("|")[0] for x in mem), sorted(users))
        for item in hist:
            self.assertLessEqual(item.count("¶"), 30)


if __name__ == "__main__":
    unittest.main(verbosity=2)
