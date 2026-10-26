#!/usr/bin/env python3
"""project.json 을 엔트리 블록 규칙대로 실행해 보는 간이 시뮬레이터 (테스트용).

엔트리(entrylabs/entryjs)의 블록 func 동작을 옮겨 왔다.
- 블록의 파라미터 값은 모두 먼저 계산한다 (Scope.getParams 와 같음).
- 문자/숫자 비교, 더하기 등은 자바스크립트의 형 변환 규칙을 따른다.
- 리스트 범위를 벗어나거나 substring 범위가 잘못되면 엔트리처럼 오류를 낸다.
- 실시간 리스트는 여러 실행(세션)이 함께 쓰는 server 딕셔너리에 저장한다.
- 메시지 '보내고 기다리기'는 받는 스크립트를 끝까지 실행한 뒤 돌아온다.
"""
import datetime
import json
import math
import random
import re
from decimal import Decimal


class EntryError(Exception):
    """엔트리에서 '블록 오류'로 작품이 멈추는 상황."""


class EndOfInput(Exception):
    """시뮬레이션용 입력이 다 떨어짐 (사용자가 창을 닫은 것으로 본다)."""


class BreakLoop(Exception):
    pass


# ------------------------------------------------------------ JS 형 변환
_JS_WS = " \t\n\r\x0b\x0c ﻿  "
_DEC = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$")
_PF = re.compile(r"^[+-]?(Infinity|(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?)")


def js_number(v):
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip(_JS_WS)
    if s == "":
        return 0.0
    if re.match(r"^0[xX][0-9a-fA-F]+$", s):
        return float(int(s, 16))
    if re.match(r"^0[oO][0-7]+$", s):
        return float(int(s[2:], 8))
    if re.match(r"^0[bB][01]+$", s):
        return float(int(s[2:], 2))
    if s in ("Infinity", "+Infinity"):
        return math.inf
    if s == "-Infinity":
        return -math.inf
    if _DEC.match(s):
        return float(s)
    return math.nan


def js_parse_float(v):
    s = js_str(v).lstrip(_JS_WS)
    m = _PF.match(s)
    if not m:
        return math.nan
    t = m.group(0)
    if t.lstrip("+-") == "Infinity":
        return -math.inf if t.startswith("-") else math.inf
    return float(t)


def js_str(v):
    if v is None:
        return "undefined"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if math.isnan(v):
            return "NaN"
        if math.isinf(v):
            return "Infinity" if v > 0 else "-Infinity"
        if v == int(v) and abs(v) < 1e21:
            return str(int(v))
        r = repr(v)
        if "e" in r:
            mant, exp = r.split("e")
            return f"{mant}e{'+' if int(exp) > 0 else '-'}{abs(int(exp))}"
        return r
    return str(v)


def is_number(v):  # Entry.Utils.isNumber
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return True
    return isinstance(v, str) and re.match(r"^-?\d+\.?\d*(?:[eE][+-]?\d+)?$", v) is not None


def truthy_boolean_value(v):  # Scope.getBooleanValue
    if v is None:
        return False
    n = js_number(v)
    return True if math.isnan(n) else bool(n)


def js_truthy(v):  # Boolean(v)
    if isinstance(v, str):
        return v != ""
    if isinstance(v, float):
        return not (v == 0 or math.isnan(v))
    return bool(v)


def compare_operand(v):
    if isinstance(v, str) and len(v):
        n = js_number(v)
        if not math.isnan(n):
            return n
    return v


def js_strict_equal(a, b):
    num = (int, float)
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, num) and isinstance(b, num):
        return float(a) == float(b)
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    return False


def js_relational(a, b, op):
    if isinstance(a, str) and isinstance(b, str):
        x, y = a, b
    else:
        x, y = js_number(a), js_number(b)
        if math.isnan(x) or math.isnan(y):
            return False
    return {"GREATER": x > y, "LESS": x < y, "GREATER_OR_EQUAL": x >= y, "LESS_OR_EQUAL": x <= y}[op]


def js_loose_not_equal(a, b):
    if isinstance(a, str) and isinstance(b, str):
        return a != b
    x, y = js_number(a), js_number(b)
    return not (x == y)


def to_num(d):
    f = float(d)
    return int(f) if f == int(f) and abs(f) < 2 ** 53 else f


# ------------------------------------------------------------ 실행기
class Session:
    def __init__(self, project, server=None, username=None, nickname=None, inputs=(),
                 seed=0, now=datetime.datetime(2026, 10, 26, 14, 5), translator=None):
        self.p = project
        self.server = server
        self.username = username
        self.nickname = nickname
        self.inputs = list(inputs)
        self.rng = random.Random(seed)
        self.now = now
        self.translator = translator or (lambda src, text, dst: f"<{dst}:{text}>")
        self.vars, self.var_names, self.lists, self.list_names = {}, {}, {}, {}
        for v in project["variables"]:
            if v["variableType"] == "list":
                data = [d["data"] for d in v["array"]]
                if v.get("isRealTime") and server is not None:
                    server.setdefault(v["id"], data)
                    self.lists[v["id"]] = server[v["id"]]
                else:
                    self.lists[v["id"]] = list(data)
                self.list_names[v["name"]] = v["id"]
            else:
                self.vars[v["id"]] = v["value"]
                self.var_names[v["name"]] = v["id"]
        self.handlers, self.starts = {}, []
        self.dialog = None
        self.dialog_log = []
        self.answer = ""
        self.transcript = []  # 대화창에 들어간 모든 줄 (화면에는 마지막 9줄만 남음)
        self.chat_id = self.list_names.get("대화창")
        self.steps = 0
        for o in project["objects"]:
            for thread in json.loads(o["script"]):
                head = thread[0]
                if head["type"] == "when_run_button_click":
                    self.starts.append(thread[1:])
                elif head["type"] == "when_message_cast":
                    self.handlers.setdefault(head["params"][1], []).append(thread[1:])

    # 편의 접근자
    def var(self, name):
        return self.vars[self.var_names[name]]

    def lst(self, name):
        return self.lists[self.list_names[name]]

    def run(self):
        try:
            for t in self.starts:
                self.exec_seq(t)
        except EndOfInput:
            pass
        return self

    # -------------------------------------------------- 명령 블록
    def exec_seq(self, seq):
        for b in seq:
            self.exec_block(b)

    def exec_block(self, b):
        self.steps += 1
        if self.steps > 5_000_000:
            raise EntryError("너무 오래 실행됨 (무한 반복?)")
        t, p = b["type"], b["params"]
        st = b.get("statements", [])
        if t == "_if":
            if truthy_boolean_value(self.ev(p[0])):
                self.exec_seq(st[0])
            return
        if t == "if_else":
            self.exec_seq(st[0] if truthy_boolean_value(self.ev(p[0])) else st[1])
            return
        if t == "repeat_basic":
            n = js_parse_float(self.ev(p[0]))
            n = 0 if math.isnan(n) else n
            if n < 0:
                raise EntryError("repeat count < 0")
            try:
                for _ in range(int(math.floor(n))):
                    self.exec_seq(st[0])
            except BreakLoop:
                pass
            return
        if t == "repeat_inf":
            try:
                while True:
                    self.exec_seq(st[0])
                    self.steps += 1
                    if self.steps > 5_000_000:
                        raise EntryError("무한 반복")
            except BreakLoop:
                pass
            return
        if t == "repeat_while_true":
            try:
                while True:
                    v = truthy_boolean_value(self.ev(p[0]))
                    if p[1] == "until":
                        v = not v
                    if not v:
                        break
                    self.exec_seq(st[0])
                    self.steps += 1
                    if self.steps > 5_000_000:
                        raise EntryError("무한 반복")
            except BreakLoop:
                pass
            return
        if t == "stop_repeat":
            raise BreakLoop()
        if t == "message_cast_wait":
            if p[0] not in [m["id"] for m in self.p["messages"]]:
                raise EntryError("no such message")
            for h in self.handlers.get(p[0], []):
                try:
                    self.exec_seq(h)
                except BreakLoop:
                    pass
            return
        vals = [self.ev(x) if isinstance(x, dict) else x for x in p]
        if t == "set_variable":
            self.vars[self.need_var(vals[0])] = vals[1]
        elif t == "change_variable":
            vid = self.need_var(vals[0])
            cur, val = self.vars[vid], vals[1]
            if is_number(val) and is_number(cur):
                fixed = max(self.float_points(val), self.float_points(cur))
                s = Decimal(js_str(js_number(val))) + Decimal(js_str(js_number(cur)))
                self.vars[vid] = f"{float(s):.{fixed}f}"
            else:
                self.vars[vid] = js_str(cur) + js_str(val)
        elif t == "add_value_to_list":
            arr = self.need_list(vals[1])
            arr.append(vals[0])
            if vals[1] == self.chat_id:
                self.transcript.append(js_str(vals[0]))
            if len(arr) > 5000:
                del arr[0]
        elif t == "remove_value_from_list":
            arr = self.need_list(vals[1])
            idx = vals[0]
            if not is_number(idx) or js_number(idx) > len(arr):
                raise EntryError("can not remove value from array")
            i = js_number(idx)
            if i != int(i) or i < 1:
                raise EntryError("bad index (JS splice 의 이상 동작)")
            del arr[int(i) - 1]
        elif t == "change_value_list_index":
            arr = self.need_list(vals[0])
            idx = vals[1]
            if not is_number(idx) or js_number(idx) > len(arr):
                raise EntryError("can not insert value to array")
            i = js_number(idx)
            if i != int(i) or i < 1:
                raise EntryError("bad index")
            arr[int(i) - 1] = vals[2]
        elif t in ("show_list", "hide_list", "set_visible_answer", "wait_second"):
            pass
        elif t == "dialog":
            msg = vals[0]
            self.dialog = "    " if msg == "" else js_str(msg)
            self.dialog_log.append(self.dialog)
        elif t == "remove_dialog":
            self.dialog = None
        elif t == "ask_and_wait":
            if vals[0] in (None, ""):
                raise EntryError("message can not be empty")
            if not self.inputs:
                raise EndOfInput()
            self.answer = self.inputs.pop(0)
            self.dialog = None
        else:
            raise EntryError(f"시뮬레이터가 모르는 명령 블록: {t}")

    @staticmethod
    def float_points(v):
        s = js_str(v)
        return min(len(s) - s.index(".") - 1, 20) if "." in s else 0

    def need_var(self, vid):
        if vid not in self.vars:
            raise EntryError(f"없는 변수 {vid}")
        return vid

    def need_list(self, lid):
        if lid not in self.lists:
            raise EntryError(f"없는 리스트 {lid}")
        return self.lists[lid]

    # -------------------------------------------------- 값 블록
    def ev(self, b):
        t, p = b["type"], b["params"]
        if t in ("text", "number"):
            return p[0] if p else ""
        if t == "True":
            return True
        if t == "False":
            return False
        vals = [self.ev(x) if isinstance(x, dict) else x for x in p]
        S = js_str
        if t == "get_variable":
            return self.vars[self.need_var(vals[0])]
        if t == "get_canvas_input_value":
            return self.answer
        if t == "value_of_index_from_list":
            arr = self.need_list(vals[1])
            idx = vals[3]
            if not is_number(idx) or js_number(idx) > len(arr):
                raise EntryError("can not get value from array")
            i = js_number(idx)
            if i != int(i) or i < 1:
                raise EntryError("bad index")
            return arr[int(i) - 1]
        if t == "length_of_list":
            return len(self.need_list(vals[1]))
        if t == "is_included_in_list":
            return any(S(x) == S(vals[3]) for x in self.need_list(vals[1]))
        if t == "boolean_basic_operator":
            a, op, c = compare_operand(vals[0]), vals[1], compare_operand(vals[2])
            if op == "EQUAL":
                return js_strict_equal(a, c)
            if op == "NOT_EQUAL":
                return js_loose_not_equal(a, c)
            return js_relational(a, c, op)
        if t == "boolean_and_or":
            a, c = js_truthy(vals[0]), js_truthy(vals[2])
            return (a and c) if vals[1] == "AND" else (a or c)
        if t == "boolean_not":
            return not truthy_boolean_value(vals[1])
        if t == "calc_basic":
            a, op, c = vals
            if op == "PLUS":
                if is_number(a) and is_number(c):
                    return to_num(Decimal(S(js_number(a))) + Decimal(S(js_number(c))))
                return S(a if not is_number(a) else js_parse_float(a)) + S(c if not is_number(c) else js_parse_float(c))
            x, y = js_parse_float(a), js_parse_float(c)
            x = 0.0 if math.isnan(x) or x == 0 else x
            y = 0.0 if math.isnan(y) or y == 0 else y
            if op == "MINUS":
                return to_num(Decimal(S(x)) - Decimal(S(y)))
            if op == "MULTI":
                return to_num(Decimal(S(x)) * Decimal(S(y)))
            if y == 0:
                return math.inf if x > 0 else (-math.inf if x < 0 else math.nan)
            return to_num(Decimal(S(x)) / Decimal(S(y)))
        if t == "calc_rand":
            lo, hi = sorted([js_number(vals[1]), js_number(vals[3])])
            return self.rng.randint(int(lo), int(hi))
        if t == "get_date":
            k = vals[1]
            n = self.now
            return {"YEAR": n.year, "MONTH": n.month, "DAY": n.day, "HOUR": n.hour, "MINUTE": n.minute,
                    "DAY_OF_WEEK": (n.weekday() + 1) % 7}.get(k, n.second)
        if t == "get_user_name":
            return self.username if self.username is not None else " "
        if t == "get_nickname":
            return self.nickname if self.nickname is not None else " "
        if t == "length_of_string":
            return len(S(vals[1]))
        if t == "reverse_of_string":
            return S(vals[1])[::-1]
        if t == "combine_something":
            return S(vals[1]) + S(vals[3])
        if t == "char_at":
            s, i = S(vals[1]), js_parse_float(vals[3])
            i = (0 if math.isnan(i) else i) - 1
            if i < 0 or i > len(s) - 1:
                raise EntryError("char_at 범위 오류")
            return s[int(i)]
        if t == "substring":
            s = S(vals[1])
            a = js_parse_float(vals[3])
            c = js_parse_float(vals[5])
            a = (0 if math.isnan(a) else a) - 1
            c = (0 if math.isnan(c) else c) - 1
            n = len(s) - 1
            if a < 0 or c < 0 or a > n or c > n:
                raise EntryError(f"substring 범위 오류: {s!r} {a + 1}..{c + 1}")
            return s[int(min(a, c)):int(max(a, c)) + 1]
        if t == "index_of_string":
            return S(vals[1]).find(S(vals[3])) + 1
        if t == "replace_string":
            old = S(vals[3])
            if old == "":
                raise EntryError("시뮬레이터: 빈 문자열 바꾸기는 지원하지 않음")
            return S(vals[1]).replace(old, S(vals[5]))
        if t == "count_match_string":
            target = S(vals[2])
            return len(S(vals[0]).split(target)) - 1 if target else len(S(vals[0]))
        if t == "change_string_case":
            s = S(vals[1])
            return s.lower() if vals[3] == "toLowerCase" else s.upper()
        if t == "get_translated_string":
            text = S(vals[1])
            if not text.strip():
                return "번역할 문장을 입력해주세요"
            return text if vals[0] == vals[2] else self.translator(vals[0], text, vals[2])
        raise EntryError(f"시뮬레이터가 모르는 값 블록: {t}")


if __name__ == "__main__":
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    project = json.load(open(os.path.join(here, "project.json"), encoding="utf-8"))
    server = {}
    user = sys.argv[1] if len(sys.argv) > 1 else "tester"
    print(f"[{user}] 으로 대화합니다. 빈 줄을 입력하면 끝.")
    lines = []
    while True:
        try:
            line = input("> ")
        except EOFError:
            break
        if not line:
            break
        lines.append(line)
    s = Session(project, server, username=user, nickname=user, inputs=lines).run()
    print("\n".join(s.lst("대화창")))
