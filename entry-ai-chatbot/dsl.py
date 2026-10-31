"""엔트리 블록을 파이썬으로 조립하는 작은 DSL.

블록 이름과 파라미터 순서는 entrylabs/entryjs 의 src/playground/blocks/*.js 정의를 따른다.
변수·리스트·신호는 이름으로 부르면 처음 쓸 때 id 가 정해진다.
"""
import json
import random

_rng = random.Random(20261026)
_used_ids = set()


def gen_id():
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        s = _rng.choice(chars[:26]) + "".join(_rng.choice(chars) for _ in range(3))
        if s not in _used_ids:
            _used_ids.add(s)
            return s


class Registry(dict):
    """이름 → id. 처음 보는 이름이면 새 id 를 만든다."""

    def __missing__(self, name):
        self[name] = gen_id()
        return self[name]


VARS = Registry()
LISTS = Registry()
MSGS = Registry()


_placed = set()


def _place(b):
    """블록을 한 자리에 넣는다. 이미 다른 자리에 들어간 블록 객체면 복사본을 넣는다."""
    if not isinstance(b, dict):
        return b
    if id(b) in _placed:
        b = fresh(b)
    _placed.add(id(b))
    return b


def blk(type_, params=None, statements=None):
    return {"id": gen_id(), "type": type_, "params": [_place(p) for p in params or []],
            "statements": [[_place(x) for x in st] for st in statements or []]}


def fresh(b):
    """블록 b 를 id 만 새로 매겨 복사한다 (같은 블록 객체를 여러 곳에 넣으면 id 가 겹친다)."""
    if not isinstance(b, dict):
        return b
    return {**b, "id": gen_id(), "params": [fresh(p) for p in b["params"]],
            "statements": [[fresh(x) for x in st] for st in b["statements"]]}


def w(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return blk("number", [str(v)])
    if isinstance(v, str):
        return blk("text", [v])
    raise TypeError(v)


# ---------------------------------------------------------------- 값 블록
def V(name): return blk("get_variable", [VARS[name], None])
def item(lst, i): return blk("value_of_index_from_list", [None, LISTS[lst], None, w(i), None])
def llen(lst): return blk("length_of_list", [None, LISTS[lst], None])
def included(lst, v): return blk("is_included_in_list", [None, LISTS[lst], None, w(v), None])
def cmp(a, op, b): return blk("boolean_basic_operator", [w(a), op, w(b)])
def eq(a, b): return cmp(a, "EQUAL", b)
def gt(a, b): return cmp(a, "GREATER", b)
def lt(a, b): return cmp(a, "LESS", b)
def NOT(a): return blk("boolean_not", [None, a, None])


def AND(*conds):
    out = conds[-1]
    for c in reversed(conds[:-1]):
        out = blk("boolean_and_or", [c, "AND", out])
    return out


def OR(*conds):
    out = conds[-1]
    for c in reversed(conds[:-1]):
        out = blk("boolean_and_or", [c, "OR", out])
    return out


def calc(a, op, b): return blk("calc_basic", [w(a), op, w(b)])
def plus(a, b): return calc(a, "PLUS", b)
def minus(a, b): return calc(a, "MINUS", b)
def rand(a, b): return blk("calc_rand", [None, w(a), None, w(b), None])
def mod(a, b): return blk("quotient_and_mod", [None, w(a), None, w(b), None, "MOD"])
def quot(a, b): return blk("quotient_and_mod", [None, w(a), None, w(b), None, "QUOTIENT"])


def join(*parts):
    out = w(parts[-1])
    for p in reversed(parts[:-1]):
        out = blk("combine_something", [None, w(p), None, out, None])
    return out


def slen(s): return blk("length_of_string", [None, w(s), None])
def sub(s, a, b): return blk("substring", [None, w(s), None, w(a), None, w(b), None])
def find(s, t): return blk("index_of_string", [None, w(s), None, w(t), None])
def repl(s, old, new): return blk("replace_string", [None, w(s), None, w(old), None, w(new), None])
def lower(s): return blk("change_string_case", [None, w(s), None, "toLowerCase", None])
def reverse(s): return blk("reverse_of_string", [None, w(s), None])
def charat(s, i): return blk("char_at", [None, w(s), None, w(i), None])
def count(s, t): return blk("count_match_string", [w(s), None, w(t), None])
def date(kind): return blk("get_date", [None, kind, None])
def username(): return blk("get_user_name", [])
def nickname(): return blk("get_nickname", [])
def answer(): return blk("get_canvas_input_value", [None])
def translate(src, text, dst): return blk("get_translated_string", [src, w(text), dst])
def color(hex_): return blk("text_color", [hex_])
def contains(s, t): return gt(find(s, t), 0)
def starts(s, t): return eq(find(s, t), 1)
def empty(s): return eq(slen(s), 0)
def pick(lst): return item(lst, rand(1, llen(lst)))


# ---------------------------------------------------------------- 명령 블록
def setv(name, v): return blk("set_variable", [VARS[name], w(v), None])
def chg(name, v): return blk("change_variable", [VARS[name], w(v), None])
def append(lst, v): return blk("add_value_to_list", [w(v), LISTS[lst], None])
def remove(lst, i): return blk("remove_value_from_list", [w(i), LISTS[lst], None])
def setitem(lst, i, v): return blk("change_value_list_index", [LISTS[lst], w(i), w(v), None])
def clear(lst): return REPEAT(llen(lst), remove(lst, 1))


def clear_many(lists, unroll=8):
    """여러 리스트를 한꺼번에 비운다. 엔트리에는 리스트 비우기 블록이 없어서 한 항목씩 지워야 하는데,
    (부스트 모드가 아니면) 반복 한 바퀴가 한 프레임이므로 한 바퀴에 리스트마다 unroll 개씩 지운다."""
    return UNTIL(AND(*[eq(llen(l), 0) for l in lists]) if len(lists) > 1 else eq(llen(lists[0]), 0),
                 *[IF(gt(llen(l), 0), remove(l, 1)) for _ in range(unroll) for l in lists])
def IF(cond, *body): return blk("_if", [cond, None], [list(body)])
def IFELSE(cond, then, els): return blk("if_else", [cond, None, None], [list(then), list(els)])
def REPEAT(n, *body): return blk("repeat_basic", [w(n), None], [list(body)])
def FOREVER(*body): return blk("repeat_inf", [None], [list(body)])
def UNTIL(cond, *body): return blk("repeat_while_true", [cond, "until", None], [list(body)])
def BREAK(): return blk("stop_repeat", [None])
def WAIT(sec): return blk("wait_second", [w(sec), None])
def CALL(msg): return blk("message_cast_wait", [MSGS[msg], None])
def CAST(msg): return blk("message_cast", [MSGS[msg], None])
def UNSAY(): return blk("remove_dialog", [None])
def ASK(v): return blk("ask_and_wait", [w(v), None])
def HIDE_ANSWER(): return blk("set_visible_answer", ["HIDE", None])
def SHOW(): return blk("show", [None])
def HIDE(): return blk("hide", [None])
def WRITE(v): return blk("text_write", [w(v), None])
def BG(hex_): return blk("text_change_bg_color", [color(hex_), None])
def FG(hex_): return blk("text_change_font_color", [color(hex_), None])
def WHEN_START(*body): return [blk("when_run_button_click", [None]), *body]
def WHEN_MSG(msg, *body): return [blk("when_message_cast", [None, MSGS[msg]]), *body]
def WHEN_CLICK(*body): return [blk("when_object_click", [None]), *body]
def WHEN_KEY(code, *body): return [blk("when_some_key_pressed", [None, str(code)]), *body]
def KEY_DOWN(code): return blk("is_press_some_key", [str(code), None])  # 그 키를 누르고 있는가?
def SHAPE(picture_id): return blk("change_to_some_shape", [blk("get_pictures", [picture_id]), None])


def ELIF_CHAIN(*pairs, otherwise=()):
    """[(조건, [블록…]), …] → 만일/아니면 블록을 겹쳐 만든 if-elif-else."""
    cond, body = pairs[-1]
    out = IFELSE(cond, list(body), list(otherwise)) if otherwise else IF(cond, *body)
    for cond, body in reversed(pairs[:-1]):
        out = IFELSE(cond, list(body), [out])
    return out


def SCAN(lst, body, unroll, k="k"):
    """리스트 lst 를 k = 1, 2, … 로 훑으며 body() 가 만든 블록을 실행한다.

    엔트리는 (부스트 모드가 아니면) 반복 한 바퀴마다 한 프레임을 쉬므로
    한 바퀴에 unroll 개씩 검사한다. body 안의 '반복 중단하기'는 이 반복 전체를 멈춘다.
    """
    steps = []
    for _ in range(unroll):
        steps += [IF(NOT(gt(V(k), llen(lst))), *body()), chg(k, 1)]
    return [setv(k, 1), UNTIL(gt(V(k), llen(lst)), *steps)]


def walk_blocks(project):
    """프로젝트 안의 모든 블록을 (오브젝트, 블록) 으로 돌려준다."""
    def walk(b):
        yield b
        for p in b["params"]:
            if isinstance(p, dict):
                yield from walk(p)
        for st in b.get("statements", []):
            for x in st:
                yield from walk(x)

    for o in project["objects"]:
        for thread in json.loads(o["script"]):
            for b in thread:
                for x in walk(b):
                    yield o, x
    for f in project.get("functions", []):
        for thread in json.loads(f["content"]):
            for b in thread:
                for x in walk(b):
                    yield f, x


# ---------------------------------------------------------------- 함수
FUNCS = []
LOOP_TYPES = {"repeat_basic", "repeat_inf", "repeat_while_true", "message_cast_wait", "wait_second",
              "ask_and_wait", "append_row_to_table"}


class Func:
    """엔트리 함수 하나.

    value=True 이면 '값을 돌려주는 함수'(function_create_value). 값 함수는 반복 없이 한 번에 끝나야 한다:
    반복이 있으면 엔트리가 다음 프레임에 이어서 돌리는데, 그 사이 같은 값 함수가 또 불리면 전역 변수를 함께 쓰게 된다.
    counters 는 함수의 지역 변수 (엔트리 지역 변수는 빈 문자열을 0 으로 돌려주므로 숫자 세기에만 쓴다).
    """

    def __init__(self, title, params=(), value=False, counters=()):
        self.id = gen_id()
        self.title = title
        self.value = value
        self.params = list(params)
        self.ptype = {p: f"stringParam_{gen_id()}" for p in self.params}
        self.locals = {c: f"{self.id}_{gen_id()}" for c in counters}
        self.body = None
        self.ret = None
        FUNCS.append(self)

    # 함수 안에서 쓰는 블록
    def p(self, name):
        return blk(self.ptype[name], [])

    def get(self, name):
        return blk("get_func_variable", [self.locals[name], None])

    def set(self, name, v):
        return blk("set_func_variable", [self.locals[name], w(v), None])

    def inc(self, name, n=1):
        return self.set(name, plus(self.get(name), n))

    # 부르는 블록
    def __call__(self, *args):
        assert len(args) == len(self.params), (self.title, args)
        params = [w(a) for a in args]
        if not self.value:
            params.append(None)
        return blk(f"func_{self.id}", params)

    def define(self, *body, ret=None):
        assert (ret is not None) == self.value, self.title
        if self.value:
            normal_calls = {f"func_{f.id}" for f in FUNCS if not f.value}
            bad = [b["type"] for b in _walk_list(body) if b["type"] in LOOP_TYPES | normal_calls]
            assert not bad, f"값 함수 '{self.title}' 안에 반복/기다리기/보통 함수가 있음: {bad}"
        self.body = list(body)
        self.ret = ret
        return self

    def to_json(self):
        assert self.body is not None, f"함수 '{self.title}' 를 정의하지 않음"
        fields = [("label", self.title)]
        for p in self.params:
            if len(self.params) > 1:
                fields.append(("label", f"{p}:"))
            fields.append(("string", p))

        def chain(i):
            if i == len(fields):
                return None
            kind, val = fields[i]
            if kind == "label":
                return {"id": gen_id(), "type": "function_field_label", "params": [val, chain(i + 1)], "statements": []}
            param = {"id": gen_id(), "type": self.ptype[val], "params": [], "statements": []}
            return {"id": gen_id(), "type": "function_field_string", "params": [param, chain(i + 1)], "statements": []}

        if self.value:
            head = {"id": gen_id(), "type": "function_create_value",
                    "params": [chain(0), None, None, _place(w(self.ret))], "statements": [self.body]}
        else:
            head = {"id": gen_id(), "type": "function_create", "params": [chain(0), None], "statements": [self.body]}
        head["x"], head["y"] = 40, 40
        return {
            "id": self.id,
            "type": "value" if self.value else "normal",
            "content": json.dumps([[head]], ensure_ascii=False),
            "useLocalVariables": bool(self.locals),
            "localVariables": [{"name": n, "value": 0, "id": lid} for n, lid in self.locals.items()],
        }


def _walk_list(blocks):
    for b in blocks:
        yield b
        for p in b["params"]:
            if isinstance(p, dict):
                yield from _walk_list([p])
        for st in b.get("statements", []):
            yield from _walk_list(st)


# ---------------------------------------------------------------- 테이블
TABLES = Registry()


def tcount(table): return blk("get_table_count", [TABLES[table], "ROW"])                # 머리글 줄까지 센 줄 수
def tget(table, row, col): return blk("get_value_from_table", [TABLES[table], w(row), w(col)])  # row 1 = 머리글
def tlookup(table, col, value, ret): return blk("get_value_v_lookup", [TABLES[table], w(col), w(value), w(ret)])
def TAPPEND(table): return blk("append_row_to_table", [TABLES[table], "ROW", None])
def TSET(table, row, col, value): return blk("set_value_from_table", [TABLES[table], w(row), w(col), w(value), None])
def TDELETE(table, row): return blk("delete_row_from_table", [TABLES[table], w(row), "ROW", None])
def TOPEN(table): return blk("open_table", [TABLES[table], None])


def has_key(table, value):
    """테이블 첫 칸에 value 가 있는지 (VLOOKUP 으로 첫 칸을 다시 꺼내 비교)."""
    return eq(tlookup(table, 1, value, 1), value)
