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
