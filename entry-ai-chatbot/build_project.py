#!/usr/bin/env python3
"""엔트리(playentry.org)용 'AI 챗봇 엔봇' 작품 파일(.ent)을 만든다.

.ent 파일은 temp/project.json 하나를 담은 tar.gz 압축 파일이다
(entrylabs/entry-offline 의 MainUtils.saveProject 와 같은 구조).

구성
- 함수: 엔봇의 생각은 모두 엔트리 '함수'로 만든다. 값을 돌려주는 함수(조사 붙이기, 앞뒤 공백 지우기 …)는
  반복 없이 한 번에 끝나서 대답이 빨라지고, 같은 블록 묶음을 여러 번 쓰지 않아도 된다.
- 테이블: 지식(주제, 단어 뜻, 일상 대화, 감정어, 먼저 물을 질문)은 knowledge/*.csv 를 테이블로 넣고
  'VLOOKUP' 블록으로 한 번에 찾는다. 대화는 '대화기록표' 테이블에 날짜·시각·누가·주제·감정·내용으로 쌓는다.
- 사용자별 저장: 엔트리 테이블은 정지하면 처음 내용으로 돌아가고 서버에 저장되지 않으므로,
  사용자별 기록은 실시간 리스트(대화기록, 기억저장소)에 저장하고, 시작할 때 대화기록표로 다시 펼친다.

엔봇이 대답을 만드는 순서 (함수 '답변 만들기')
  문장 분석 → 명령 → 직전에 물어본 것의 대답 → 이야기 속 사실 → 기억 → 단어 뜻·일상 대화·모르는 것 배우기
  → 감정(공감) → 주제 → 되받기 → 모르는 질문 배우기 → 엔봇이 먼저 묻기

사용법:  python3 build_project.py   →  entry-ai-chatbot.ent, project.json 생성
"""
import csv
import io
import json
import os
import re
import tarfile
import time

import data as D
from dsl import (AND, ASK, BG, BREAK, CAST, ELIF_CHAIN, FG, FUNCS, HIDE, HIDE_ANSWER, IF, IFELSE, LISTS, MSGS,
                 NOT, OR, REPEAT, SCAN, SHOW, TABLES, TAPPEND, TDELETE, TOPEN, TSET, UNSAY, UNTIL, V, VARS, WAIT,
                 WHEN_MSG, WHEN_START, WRITE, Func, answer, append, calc, charat, chg, clear, contains, count, date,
                 empty, eq, find, gen_id, gt, included, item, join, llen, lower, lt, minus, nickname,
                 pick, plus, rand, remove, repl, reverse, setitem, setv, slen, starts, sub, tcount, tget, tlookup,
                 translate, username, walk_blocks)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ENT = os.path.join(HERE, "entry-ai-chatbot.ent")
OUT_JSON = os.path.join(HERE, "project.json")
KNOWLEDGE = os.path.join(HERE, "knowledge")

SEP = "¶"               # 저장 문자열 안에서 줄을 나누는 기호
CHUNK = 24              # 말풍선 한 줄의 최대 글자 수
ROWS = 9                # 화면에 보이는 말풍선 줄 수
SHOW_HISTORY = 8        # 다시 접속했을 때 화면에 보여 줄 지난 대화 줄 수
MAX_HISTORY_LINES = 40  # 사용자마다 서버에 남기는 대화 줄 수
MAX_LINE_LEN = 140      # 서버에 남기는 한 줄의 최대 길이 (날짜·시각·주제·감정 포함)
MAX_MEMORIES = 50       # 사용자마다 기억하는 것의 수

# 대화기록표 칸 번호
C_NO, C_DATE, C_TIME, C_WHO, C_TOPIC, C_FEEL, C_TEXT = range(1, 8)
LOG_FIELDS = ["번호", "날짜", "시각", "누가", "주제", "감정", "내용"]

# ---------------------------------------------------------------- 디자인
FONT = "NanumSquareRound"
HEADER_BG = "#4F46E5"
CHAT_BG = "#F1F5F9"
BOT_BG, BOT_FG = "#FFFFFF", "#1E293B"
ME_BG, ME_FG = "#4F46E5", "#FFFFFF"
NOTICE_FG = "#94A3B8"
THINK_FG = "#6366F1"
ROW_TOP, ROW_STEP, ROW_H = 98, 17, 17
LEFT_X, RIGHT_X = -228, 228


def read_csv(name):
    with open(os.path.join(KNOWLEDGE, f"{name}.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    return rows[0], [r for r in rows[1:] if r and r[0].strip()]


# knowledge/<테이블 이름>.csv — 엔트리 테이블 탭에서 그대로 올릴 수 있는 파일
T_TOPIC, T_DEF, T_TALK, T_FEEL, T_ASK, T_LOG = "표-주제", "표-단어뜻", "표-일상대화", "표-감정어", "표-먼저묻기", "대화기록표"
KNOW = {name: read_csv(name) for name in [T_TOPIC, T_DEF, T_TALK, T_FEEL, T_ASK, T_LOG]}
TABLE_ROWS = {name: rows for name, (_fields, rows) in KNOW.items()}
assert KNOW[T_LOG][0] == LOG_FIELDS

# ================================================================ 함수 선언
# 값 함수 (반복 없이 바로 값을 돌려준다)
TRIM = Func("앞뒤 공백 지우기", ["글"], value=True)
HEAD = Func("앞 글자 떼기", ["글", "개수"], value=True)
TAIL = Func("뒤 글자 떼기", ["글", "개수"], value=True)
END = Func("끝 글자", ["글", "개수"], value=True)
PAD2 = Func("두 자리 숫자", ["수"], value=True)
JOSA = Func("조사 붙이기", ["낱말", "조사"], value=True)
STEM = Func("조사 떼기", ["낱말"], value=True)
CLEAN = Func("대답 다듬기", ["글"], value=True)
KEYSHOW = Func("키 보여 주기", ["키"], value=True)
TOPICQ = Func("주제 질문", ["주제"], value=True)
FILL = Func("문장 완성", ["틀"], value=True)
CALC = Func("계산", ["식"], value=True)
# 보통 함수
PRINT = Func("말풍선 출력", ["글", "종류"])
STATUS = Func("상태 표시", ["글"])
ANALYZE = Func("문장 분석")
CONNECT = Func("기억 연결")
FACTS = Func("사실 찾기")
SAVEFACT = Func("사실 저장", ["키", "값"])
FINDMEM = Func("기억에서 찾기", ["키"], counters=["k"])
RECALL = Func("기억 꺼내기", ["키"])
STARTER = Func("먼저 물을 질문 붙이기")
REPLY = Func("답변 만들기")
R_CMD = Func("대답: 명령")
R_PENDING = Func("대답: 물어본 것의 대답")
R_MEMORY = Func("대답: 기억")
R_TALK = Func("대답: 뜻과 일상 대화")
R_FEEL = Func("대답: 감정과 주제")
R_LAST = Func("대답: 이어 가기")
LOG = Func("기록하기", ["누가", "내용"])
LOGROW = Func("기록표에 줄 넣기", ["날짜", "시각", "누가", "주제", "감정", "내용"])
PARSELINE = Func("기록 줄 풀기", ["줄"])
SAVELOG = Func("기록 저장")
SAVEMEM = Func("기억 저장")
SLOT_LOG = Func("내 기록 칸 찾기")
SLOT_MEM = Func("내 기억 칸 찾기")
LOAD = Func("데이터 불러오기", counters=["줄번호"])
SEARCH = Func("기록 검색", ["낱말"], counters=["찾은수"])
STATS = Func("기록 통계", counters=["내말", "봇말", "좋음", "나쁨", "보통", "오늘"])
CLEARLOG = Func("기록표 비우기")

# ================================================================ 테이블 창구 함수
# 테이블 블록은 이 함수들 안에만 둔다. 엔트리 웹에서 .ent 를 불러올 때 테이블이 빠지면
# knowledge/*.csv 를 테이블로 올린 뒤, 이 함수들 안의 테이블 칸(▼)만 다시 고르면 된다.
FIND_IN = {
    T_TOPIC: Func("주제표 찾기", ["낱말", "칸"], value=True),
    T_DEF: Func("뜻표 찾기", ["낱말", "칸"], value=True),
    T_TALK: Func("일상표 찾기", ["낱말", "칸"], value=True),
    T_FEEL: Func("감정표 찾기", ["낱말", "칸"], value=True),
}
ASK_COUNT = Func("질문표 줄 수", value=True)
ASK_GET = Func("질문표 칸", ["줄", "칸"], value=True)
LOG_COUNT = Func("기록표 줄 수", value=True)
LOG_GET = Func("기록표 칸", ["줄", "칸"], value=True)
LOG_SET = Func("기록표 칸 바꾸기", ["줄", "칸", "값"])
LOG_ADD = Func("기록표 줄 더하기")
LOG_DEL = Func("기록표 줄 지우기", ["줄"])
LOG_OPEN = Func("기록표 열기")
for _t, _f in FIND_IN.items():
    # VLOOKUP: 첫 칸이 낱말인 줄의 '칸' 번째 값 (없으면 빈 값)
    _f.define(setv("표값", tlookup(_t, 1, _f.p("낱말"), _f.p("칸"))), ret=V("표값"))
ASK_COUNT.define(setv("표값", tcount(T_ASK)), ret=V("표값"))
ASK_GET.define(setv("표값", tget(T_ASK, ASK_GET.p("줄"), ASK_GET.p("칸"))), ret=V("표값"))
LOG_COUNT.define(setv("표값", tcount(T_LOG)), ret=V("표값"))
LOG_GET.define(setv("표값", tget(T_LOG, LOG_GET.p("줄"), LOG_GET.p("칸"))), ret=V("표값"))
LOG_SET.define(TSET(T_LOG, LOG_SET.p("줄"), LOG_SET.p("칸"), LOG_SET.p("값")))
LOG_ADD.define(TAPPEND(T_LOG))
LOG_DEL.define(TDELETE(T_LOG, LOG_DEL.p("줄")))
LOG_OPEN.define(TOPEN(T_LOG))


def lookup(table, value, col):
    return FIND_IN[table](value, col)


def has(table, value):
    """테이블 첫 칸에 value 가 있는지 (찾은 첫 칸을 다시 꺼내 비교)."""
    return eq(lookup(table, value, 1), value)


def BRANCH(cond, *body, guard=None):
    """아직 답이 정해지지 않았고 cond 가 참이면 body 를 실행한다.
    guard 는 cond 를 계산하기 전에 확인할 조건 (엔트리는 조건 블록 안을 모두 먼저 계산하므로
    리스트 범위를 벗어나는 계산을 막을 때 쓴다)."""
    inner = IF(cond, *body, setv("처리됨", 1))
    if guard is not None:
        inner = IF(guard, inner)
    return IF(eq(V("처리됨"), 0), inner)


def ends(value, suffix):
    return eq(END(value, len(suffix)), suffix)


def ends_space(value):
    # " " 와 같은지 비교하면 "0" 도 같다고 나오므로(엔트리는 숫자로 바꿔 비교) 위치 찾기로 확인한다
    return eq(find(END(value, 1), " "), 1)


def SPLIT_LINE(rest, line, pos, sep=SEP):
    """변수 rest 에서 sep 앞까지를 꺼내 변수 line 에 넣고, rest 에서는 지운다."""
    return [
        setv(pos, find(V(rest), sep)),
        IFELSE(eq(V(pos), 0),
               [setv(line, V(rest)), setv(rest, "")],
               [IFELSE(gt(V(pos), 1), [setv(line, sub(V(rest), 1, minus(V(pos), 1)))], [setv(line, "")]),
                setv(rest, HEAD(V(rest), V(pos)))]),
    ]


def TODAY():
    return join(date("YEAR"), "-", PAD2(date("MONTH")), "-", PAD2(date("DAY")))


def NOW():
    return join(PAD2(date("HOUR")), ":", PAD2(date("MINUTE")))


# ================================================================ 값 함수 정의
TRIM.define(
    # 겹친 공백을 하나로 줄인 뒤 앞뒤 한 칸씩 지운다 (반복 블록 없이)
    setv("공백글", repl(repl(repl(TRIM.p("글"), "  ", " "), "  ", " "), "  ", " ")),
    IF(eq(find(V("공백글"), " "), 1), setv("공백글", HEAD(V("공백글"), 1))),
    IF(ends_space(V("공백글")), setv("공백글", TAIL(V("공백글"), 1))),
    ret=V("공백글"))
HEAD.define(
    IFELSE(gt(slen(HEAD.p("글")), HEAD.p("개수")),
           [setv("자른글", sub(HEAD.p("글"), plus(HEAD.p("개수"), 1), slen(HEAD.p("글"))))],
           [setv("자른글", "")]),
    ret=V("자른글"))
TAIL.define(
    IFELSE(gt(slen(TAIL.p("글")), TAIL.p("개수")),
           [setv("자른글", sub(TAIL.p("글"), 1, minus(slen(TAIL.p("글")), TAIL.p("개수"))))],
           [setv("자른글", "")]),
    ret=V("자른글"))
# 엔트리에서 몸통이 빈 값 함수는 한 프레임 늦게(비동기로) 값을 돌려주므로, 몸통에 블록을 하나 둔다.
END.define(
    setv("끝조각", sub(join("    ", END.p("글")), minus(plus(slen(END.p("글")), 4), minus(END.p("개수"), 1)),
                       plus(slen(END.p("글")), 4))),
    ret=V("끝조각"))
PAD2.define(
    IFELSE(lt(PAD2.p("수"), 10), [setv("두자리", join("0", PAD2.p("수")))], [setv("두자리", PAD2.p("수"))]),
    ret=V("두자리"))

JOSA.define(
    setv("조사결과", JOSA.p("낱말")),
    IF(gt(slen(JOSA.p("낱말")), 0),
       setv("조사끝", lower(charat(JOSA.p("낱말"), slen(JOSA.p("낱말"))))),
       setv("받침", 0),
       # 한글 음절(과 숫자)은 받침 없는 글자 모음에 없으면 받침이 있다
       IF(AND(NOT(lt(V("조사끝"), "가")), NOT(gt(V("조사끝"), "힣"))),
          IF(eq(find(V("글자-받침없음"), V("조사끝")), 0), setv("받침", 1))),
       IF(contains(D.LATIN_BATCHIM, V("조사끝")), setv("받침", 1)),
       IF(eq(JOSA.p("조사"), "으로"), IF(contains(V("글자-ㄹ받침"), V("조사끝")), setv("받침", 0))),
       *[IF(eq(JOSA.p("조사"), kind),
            IFELSE(eq(V("받침"), 1), [setv("조사결과", join(JOSA.p("낱말"), a))],
                   [setv("조사결과", join(JOSA.p("낱말"), b))]))
         for kind, (a, b) in D.JOSA.items()]),
    ret=V("조사결과"))

STEM.define(
    # 뒤에 붙은 조사를 뗀다. 아는 주제 낱말(고양이 등)은 그대로 둔다.
    setv("어간", STEM.p("낱말")),
    setv("떼기길이", slen(STEM.p("낱말"))),
    IF(NOT(has(T_TOPIC, STEM.p("낱말"))),
       setv("떼기완료", 0),
       IF(gt(V("떼기길이"), 3),
          IF(included("조사목록", END(STEM.p("낱말"), 3)),
             setv("어간", TAIL(STEM.p("낱말"), 3)), setv("떼기완료", 1))),
       IF(AND(eq(V("떼기완료"), 0), gt(V("떼기길이"), 2)),
          IF(included("조사목록", END(STEM.p("낱말"), 2)),
             setv("어간", TAIL(STEM.p("낱말"), 2)), setv("떼기완료", 1))),
       # 한 글자 조사는 남는 말이 한 글자일 때 아는 주제 낱말인 경우만 뗀다 ('책이' → 책, '오이' → 오이)
       IF(AND(eq(V("떼기완료"), 0), gt(V("떼기길이"), 1)),
          IF(included("조사목록", END(STEM.p("낱말"), 1)),
             IF(OR(gt(V("떼기길이"), 2), has(T_TOPIC, TAIL(STEM.p("낱말"), 1))),
                setv("어간", TAIL(STEM.p("낱말"), 1)))))),
    # '발표했어', '축구하러' 처럼 아는 주제 낱말 뒤에 '하다·이다'가 붙은 말이면 주제 낱말만 남긴다 (긴 꼬리부터)
    *[IF(eq(V("어간"), STEM.p("낱말")), IF(gt(V("떼기길이"), n), IF(included("주제뒤말", END(STEM.p("낱말"), n)),
         IF(has(T_TOPIC, TAIL(STEM.p("낱말"), n)), setv("어간", TAIL(STEM.p("낱말"), n))))))
      for n in sorted({len(t) for t in D.HA_TAILS}, reverse=True)],
    ret=V("어간"))

_TAILS = ["이랍니다", "입니다", "이에요", "이예요", "예요", "이야", "이요", "이지", "이다", "이라고", "라고", "잖아",
          "야", "요"]
_HEADS = ["음… ", "음 ", "그건 ", "그거 ", "아 ", "어 ", "흠 ", "글쎄 ", "그냥 ", "딱히 ", "음.. "]
CLEAN.define(
    # 대답에서 앞의 군말과 끝의 '이야/예요/입니다…' 를 떼어 낸다.
    setv("다듬글", TRIM(CLEAN.p("글"))),
    *[IF(starts(V("다듬글"), h), setv("다듬글", HEAD(V("다듬글"), len(h)))) for h in _HEADS],
    # 끝말 목록에 있는 꼬리를 긴 것부터 하나만 뗀다
    setv("다듬완료", 0),
    *[IF(eq(V("다듬완료"), 0), IF(gt(slen(V("다듬글")), n), IF(included("끝말목록", END(V("다듬글"), n)),
         setv("다듬글", TAIL(V("다듬글"), n)), setv("다듬완료", 1))))
      for n in sorted({len(t) for t in _TAILS}, reverse=True)],
    ret=TRIM(V("다듬글")))

KEYSHOW.define(
    ELIF_CHAIN(
        (AND(starts(KEYSHOW.p("키"), "내가 "), gt(slen(KEYSHOW.p("키")), 3)),
         [setv("키표시", join(V("호칭"), "님이 ", HEAD(KEYSHOW.p("키"), 3)))]),
        (AND(starts(KEYSHOW.p("키"), "내 "), gt(slen(KEYSHOW.p("키")), 2)),
         [setv("키표시", join(V("호칭"), "님의 ", HEAD(KEYSHOW.p("키"), 2)))]),
        otherwise=[setv("키표시", KEYSHOW.p("키"))]),
    ret=V("키표시"))

TOPICQ.define(
    setv("주제질문", ""), setv("주제질문대체", 0),
    IF(gt(slen(TOPICQ.p("주제")), 0),
       IF(has(T_TOPIC, TOPICQ.p("주제")), setv("주제질문", lookup(T_TOPIC, TOPICQ.p("주제"), 2)))),
    # 이미 알고 있는 걸 묻는 질문이면 다른 말로 바꾼다
    IF(contains(V("주제질문"), "[사실:"),
       setv("괄호A", find(V("주제질문"), "[사실:")), setv("괄호B", find(V("주제질문"), "]")),
       IF(gt(V("괄호B"), plus(V("괄호A"), 4)),
          IF(included("내질문", sub(V("주제질문"), plus(V("괄호A"), 4), minus(V("괄호B"), 1))),
             setv("주제질문", pick("말-주제더")), setv("주제질문대체", 1)))),
    ret=V("주제질문"))


def template_slots():
    """모든 문구에서 쓰인 {슬롯조사} 조합을 모은다."""
    texts = [t for v in D.PHRASES.values() for t in v] + ["{단어은} ", "제가 기억하는 {이름}님은요:",
                                                          "오늘 이야기 즐거웠어요, {이름}님!"]
    for name in [T_TOPIC, T_DEF, T_TALK, T_ASK]:
        texts += [r[1] for r in KNOW[name][1]]
    combos, plain = set(), set()
    for t in texts:
        for m in re.findall(r"\{([^{}]+)\}", t):
            base = next((b for b in sorted(D.SLOT_BASES, key=len, reverse=True) if m.startswith(b)), None)
            if base is None:
                raise ValueError(f"모르는 슬롯 {{{m}}} in {t}")
            kind = m[len(base):]
            if kind:
                if kind not in D.JOSA:
                    raise ValueError(f"모르는 조사 {kind} in {t}")
                combos.add((base, kind))
            else:
                plain.add(base)
    return sorted(combos), sorted(plain | set(D.SLOT_BASES))


_combos, _plain = template_slots()
FILL.define(
    setv("틀", FILL.p("틀")),
    # [대기] 표시 → 이번대기, 문장에서는 지운다
    IF(contains(V("틀"), "["),
       setv("괄호A", find(V("틀"), "[")),
       setv("괄호B", find(V("틀"), "]")),
       IF(gt(V("괄호B"), plus(V("괄호A"), 1)),
          setv("이번대기", sub(V("틀"), plus(V("괄호A"), 1), minus(V("괄호B"), 1))),
          setv("틀", TRIM(join(TAIL(V("틀"), minus(plus(slen(V("틀")), 1), V("괄호A"))), HEAD(V("틀"), V("괄호B"))))))),
    *[IF(contains(V("틀"), "{" + base + kind + "}"),
         setv("틀", repl(V("틀"), "{" + base + kind + "}", JOSA(V(D.SLOT_BASES[base]), kind))))
      for base, kind in _combos],
    *[IF(contains(V("틀"), "{" + base + "}"), setv("틀", repl(V("틀"), "{" + base + "}", V(D.SLOT_BASES[base]))))
      for base in _plain],
    ret=V("틀"))

_ops = [("+", "PLUS"), ("*", "MULTI"), ("/", "DIVIDE")]
_compute = []
for _sym, _op in _ops + [("-", "MINUS")]:
    _body = [setv("결과", join(V("식"), " = ", calc(V("왼쪽수"), _op, V("오른쪽수"))))]
    if _sym == "/":
        _body = [IFELSE(eq(V("오른쪽수"), 0), [setv("결과", "0으로는 나눌 수 없어요.")], _body)]
    _compute.append(IF(eq(V("연산자"), _sym), *_body))
CALC.define(
    setv("식", repl(repl(repl(repl(CALC.p("식"), " ", ""), "×", "*"), "÷", "/"), "x", "*")),
    setv("결과", "식을 이해하지 못했어요. 예) 계산: 12*3  (+, -, *, / 중 하나만 써 주세요)"),
    setv("연산위치", 0), setv("연산자", ""),
    *[IF(eq(V("연산위치"), 0), setv("연산위치", find(V("식"), sym)), IF(gt(V("연산위치"), 0), setv("연산자", sym)))
      for sym, _ in _ops],
    # 빼기는 맨 앞의 음수 부호를 건너뛰고 찾는다.
    IF(eq(V("연산위치"), 0),
       IF(gt(slen(V("식")), 1),
          setv("연산위치", find(HEAD(V("식"), 1), "-")),
          IF(gt(V("연산위치"), 0), setv("연산위치", plus(V("연산위치"), 1)), setv("연산자", "-")))),
    IF(AND(gt(V("연산위치"), 1), lt(V("연산위치"), slen(V("식")))),
       setv("왼쪽수", sub(V("식"), 1, minus(V("연산위치"), 1))),
       setv("오른쪽수", HEAD(V("식"), V("연산위치"))),
       # 숫자인지 확인: 숫자 문자열만 '자기 자신 - 0' 과 같다.
       IF(AND(eq(V("왼쪽수"), minus(V("왼쪽수"), 0)), eq(V("오른쪽수"), minus(V("오른쪽수"), 0))), *_compute)),
    ret=V("결과"))

# ================================================================ 화면
PRINT.define(
    # 글을 줄(¶)과 길이(CHUNK, 띄어쓰기 기준)로 나눠 말풍선 줄로 쌓는다. 최근 ROWS 줄만 남긴다.
    setv("출력남은", PRINT.p("글")),
    UNTIL(empty(V("출력남은")),
          *SPLIT_LINE("출력남은", "출력줄", "출력위치"),
          UNTIL(empty(V("출력줄")),
                IFELSE(gt(slen(V("출력줄")), CHUNK),
                       [setv("조각", sub(V("출력줄"), 1, CHUNK)),
                        # 조각의 마지막 공백이 뒤쪽 절반 안에 있으면 그 공백에서 줄을 바꾼다.
                        setv("끊을위치", find(reverse(V("조각")), " ")),
                        IFELSE(AND(gt(V("끊을위치"), 0), lt(V("끊을위치"), CHUNK // 2 + 1)),
                               [setv("조각", sub(V("출력줄"), 1, minus(CHUNK, V("끊을위치")))),
                                setv("출력줄", HEAD(V("출력줄"), minus(CHUNK + 1, V("끊을위치"))))],
                               [setv("출력줄", HEAD(V("출력줄"), CHUNK))])],
                       [setv("조각", V("출력줄")), setv("출력줄", "")]),
                append("화면글", V("조각")),
                append("화면종류", PRINT.p("종류")),
                IF(gt(llen("화면글"), ROWS), remove("화면글", 1), remove("화면종류", 1)))),
    CAST("화면 그리기"),
)
STATUS.define(setv("상태글", STATUS.p("글")), CAST("상태 표시"))


def ui_scripts():
    """말풍선 줄 오브젝트(봇칸/나칸)마다 붙는 '화면 그리기' 스크립트."""
    bot, me = {}, {}
    for k in range(1, ROWS + 1):
        kind = lambda: item("화면종류", k)
        bot[k] = [WHEN_MSG(
            "화면 그리기",
            IFELSE(gt(k, llen("화면종류")), [HIDE()],
                   [IFELSE(eq(kind(), "나"), [HIDE()],
                           [ELIF_CHAIN(
                               (eq(kind(), "봇"), [WRITE(join("  ", item("화면글", k), "  ")), BG(BOT_BG), FG(BOT_FG)]),
                               (eq(kind(), "생각"), [WRITE(join("  ", item("화면글", k))), BG(CHAT_BG), FG(THINK_FG)]),
                               otherwise=[WRITE(join("  ", item("화면글", k))), BG(CHAT_BG), FG(NOTICE_FG)]),
                            SHOW()])]))]
        me[k] = [WHEN_MSG(
            "화면 그리기",
            IFELSE(gt(k, llen("화면종류")), [HIDE()],
                   [IFELSE(eq(kind(), "나"), [WRITE(join("  ", item("화면글", k), "  ")), SHOW()], [HIDE()])]))]
    status = [WHEN_MSG("상태 표시", WRITE(V("상태글")))]
    return bot, me, status


# ================================================================ 문장 분석
_q_endings = "|" + "|".join(D.QUESTION_ENDINGS) + "|"
_cue_in = lambda v: OR(*[contains(v, c) for c in ["뭐", "뭔", "무엇", "알아", "알려", "설명", "누구", "어때", "?"]])
_verb = lambda: setv("서술종류", "동사")
_L = lambda: V("서L")
_reflect = ELIF_CHAIN(
    (AND(eq(V("서끝2"), "어요"), contains(V("글자-ㅆ받침"), V("서앞2"))),
     [setv("서술", join(TAIL(V("마지막절"), 2), "군요")), _verb()]),
    (AND(contains("어아다", V("서끝1")), contains(V("글자-ㅆ받침"), V("서앞1")), NOT(eq(V("서앞1"), "겠"))),
     [setv("서술", join(TAIL(V("마지막절"), 1), "군요")), _verb()]),
    (OR(eq(V("서끝2"), "싶어"), eq(V("서끝2"), "싶다")), [setv("서술", join(TAIL(V("마지막절"), 1), "군요")), _verb()]),
    (AND(eq(V("서끝2"), "에요"), eq(V("서앞2"), "이")), [setv("서술", join(TAIL(V("마지막절"), 3), "이군요"))]),
    (eq(V("서끝2"), "이야"), [setv("서술", join(TAIL(V("마지막절"), 2), "이군요"))]),
    (eq(V("서끝2"), "예요"), [setv("서술", join(TAIL(V("마지막절"), 2), "군요"))]),
    (AND(eq(V("서끝1"), "야"), contains(V("글자-받침없음"), V("서앞1")), NOT(contains("해가와봐돼줘서려니", V("서앞1")))),
     [setv("서술", join(TAIL(V("마지막절"), 1), "군요"))]),
    (AND(eq(V("서끝1"), "해"), included("형용사", sub(V("마지막절"), minus(_L(), 2), minus(_L(), 1)))),
     [setv("서술", join(TAIL(V("마지막절"), 1), "하군요")), _verb()]),
)
_pronouns = ELIF_CHAIN(*[(AND(starts(V("서술"), p), gt(slen(V("서술")), len(p))), [setv("서술", HEAD(V("서술"), len(p)))])
                         for p in ["나는 ", "저는 ", "내가 ", "제가 ", "나 ", "난 ", "저 ", "전 ", "응 ", "어 ", "네 ",
                                   "음 ", "아 ", "근데 ", "그리고 "]])
_m = lambda: V("정리메시지")


FEEL = Func("감정 점수 찾기", ["낱말"], value=True)


def _feel_lookup(length):
    """낱말 앞부분(length 글자, None 이면 낱말 전체)이 감정어 테이블에 있으면 점수를 가져온다."""
    piece = V("감정낱말") if length is None else sub(V("감정낱말"), 1, length)
    guard = gt(slen(V("감정낱말")), length - 1) if length else gt(slen(V("감정낱말")), 0)
    return IF(eq(V("낱말점수"), 0), IF(guard,
              setv("감정후보", piece),
              IF(has(T_FEEL, V("감정후보")), setv("낱말점수", lookup(T_FEEL, V("감정후보"), 2)))))


def FIND_PIECE(table, text, found, found_len, k, max_pos=30):
    """글 text 의 조각(긴 것부터)을 table 첫 열에서 VLOOKUP 으로 찾아, 가장 긴 것을 found 에 넣는다.
    테이블을 처음부터 끝까지 훑지 않으므로 데이터가 늘어나도 빠르기가 그대로다 (글자 수만큼만 돈다)."""
    lengths = {len(r[0]) for r in TABLE_ROWS[table]}
    return [
        setv(found, ""), setv(found_len, 1), setv(k, 1),
        setv("훑을수", minus(slen(text), 1)), IF(gt(V("훑을수"), max_pos), setv("훑을수", max_pos)),
        REPEAT(V("훑을수"),
               *[IF(gt(n, V(found_len)), IF(NOT(gt(plus(V(k), n - 1), slen(text))),
                    setv("조각", sub(text, V(k), plus(V(k), n - 1))),
                    IF(has(table, V("조각")), setv(found, V("조각")), setv(found_len, n))))
                 for n in sorted((x for x in lengths if x >= 2), reverse=True)],
               chg(k, 1)),
    ]


FEEL.define(
    # 낱말 전체 → 앞 4·3·2 글자 순서로 감정어 테이블에서 찾는다
    setv("감정낱말", FEEL.p("낱말")), setv("낱말점수", 0),
    _feel_lookup(None), _feel_lookup(4), _feel_lookup(3), _feel_lookup(2),
    ret=V("낱말점수"))

ANALYZE.define(
    setv("정리메시지", repl(lower(V("메시지")), " ", "")),
    # 끝의 문장 부호 · ㅋㅋ · ㅠㅠ 떼기 (최대 6글자)
    setv("문장", V("메시지")),
    *[IF(gt(slen(V("문장")), 0), IF(gt(find("?!.~ㅋㅎㅠㅜ;,^", charat(V("문장"), slen(V("문장")))), 0),
                                    setv("문장", TAIL(V("문장"), 1)))) for _ in range(6)],
    setv("문장", TRIM(V("문장"))),
    # 질문인지
    setv("질문여부", 0),
    IF(OR(contains(V("메시지"), "?"), *[contains(_m(), c) for c in D.QUESTION_CUES]), setv("질문여부", 1)),
    IF(contains("냐까", END(V("문장"), 1)), setv("질문여부", 1)),
    IF(contains(_q_endings, join("|", END(V("문장"), 2), "|")), setv("질문여부", 1)),
    setv("뜻질문", 0),
    IF(OR(*[contains(_m(), c) for c in D.DEFINITION_CUES]), setv("뜻질문", 1)),
    # 낱말 나누기 (원단어들) + 조사 떼기 (단어들) + 감정 점수 (감정어 테이블)
    clear("원단어들"), clear("단어들"),
    setv("감정점수", 0), setv("이전낱말", ""),
    setv("분석남은", join(V("문장"), " ")),
    UNTIL(empty(V("분석남은")),
          setv("분석위치", find(V("분석남은"), " ")),
          IF(gt(V("분석위치"), 1),
             setv("단어원형", sub(V("분석남은"), 1, minus(V("분석위치"), 1))),
             setv("단어원형", repl(repl(repl(repl(V("단어원형"), ",", ""), "'", ""), '"', ""), "…", "")),
             IF(gt(slen(V("단어원형")), 0),
                append("원단어들", V("단어원형")),
                append("단어들", STEM(V("단어원형"))),
                # 감정: 낱말 전체 → 앞 4·3·2 글자 순서로 감정어 테이블에서 찾고, 앞 낱말이 '안/못'이면 뒤집는다
                setv("낱말점수", FEEL(lower(V("단어원형")))),
                IF(included("뒤집는말", V("이전낱말")), setv("낱말점수", minus(0, V("낱말점수")))),
                # '안 먹어' 처럼 띄어 쓴 부정은 붙여서 다시 찾아본다 (감정어 테이블의 '안먹')
                IF(AND(included("뒤집는말", V("이전낱말")), eq(V("낱말점수"), 0)),
                   setv("낱말점수", FEEL(lower(join(V("이전낱말"), V("단어원형")))))),
                # '못 자', '못 갔어' 처럼 감정어가 아니어도 '못' 뒤의 말은 조금 아쉬운 말로 본다
                IF(AND(eq(V("이전낱말"), "못"), eq(V("낱말점수"), 0)), setv("낱말점수", -1)),
                chg("감정점수", V("낱말점수")),
                setv("이전낱말", V("단어원형")))),
          setv("분석남은", HEAD(V("분석남은"), V("분석위치")))),
    # 주제(아는 주제 낱말 중 마지막 것), 후보주제(조사가 붙어 있던 첫 낱말), 단어(질문의 대상)
    setv("주제", ""), setv("후보주제", ""), setv("단어", ""), setv("내용어수", 0),
    setv("분석k", 1),
    REPEAT(llen("단어들"),
           setv("어간임시", item("단어들", V("분석k"))),
           IF(has(T_TOPIC, V("어간임시")), setv("주제", V("어간임시"))),
           IF(AND(empty(V("후보주제")), gt(slen(V("어간임시")), 1)),
              IF(NOT(included("불용어", V("어간임시"))),
                 IF(NOT(eq(item("원단어들", V("분석k")), V("어간임시"))), setv("후보주제", V("어간임시"))))),
           IF(gt(slen(V("어간임시")), 0),
              IF(NOT(included("불용어", V("어간임시"))),
                 IF(NOT(_cue_in(V("어간임시"))),
                    chg("내용어수", 1),
                    IF(empty(V("단어")), setv("단어", V("어간임시")))))),
           chg("분석k", 1)),
    # 띄어 쓰지 않은 한 덩어리 말이면 그 안에 들어 있는 가장 긴 주제를 찾는다
    IF(AND(empty(V("주제")), eq(llen("원단어들"), 1), gt(slen(_m()), 3)),
       *FIND_PIECE(T_TOPIC, _m(), "주제", "주제길이", "분석k")),
    # 되받을 말: "시험 망쳤어" → "시험 망쳤군요" (여러 문장이면 마지막 문장만)
    setv("서술", ""), setv("서끝1", ""), setv("서술종류", ""),
    setv("마지막절", reverse(repl(repl(repl(V("문장"), "!", "|"), ".", "|"), "?", "|"))),
    IF(gt(find(V("마지막절"), "|"), 1), setv("마지막절", sub(V("마지막절"), 1, minus(find(V("마지막절"), "|"), 1)))),
    setv("마지막절", TRIM(reverse(V("마지막절")))),
    IF(AND(eq(V("질문여부"), 0), gt(slen(V("마지막절")), 2), lt(slen(V("마지막절")), 31)),
       setv("서L", slen(V("마지막절"))),
       setv("서끝1", END(V("마지막절"), 1)),
       setv("서앞1", charat(V("마지막절"), minus(_L(), 1))),
       setv("서끝2", END(V("마지막절"), 2)),
       setv("서앞2", charat(V("마지막절"), minus(_L(), 2))),
       _reflect,
       IF(gt(slen(V("서술")), 0),
          _pronouns,
          setv("서술", HEAD(repl(repl(join(" ", V("서술")), " 내 ", " {이름}님 "), " 제 ", " {이름}님 "), 1)))),
)


# ================================================================ 기억
def LSCAN(fn, k, lst, body, unroll=6):
    """함수 지역 변수 k 로 리스트를 1, 2, … 훑는다 (한 바퀴에 unroll 개씩)."""
    steps = []
    for _ in range(unroll):
        steps += [IF(NOT(gt(fn.get(k), llen(lst))), *body()), fn.inc(k)]
    return [fn.set(k, 1), UNTIL(gt(fn.get(k), llen(lst)), *steps)]


FINDMEM.define(
    setv("찾은키번호", 0),
    *LSCAN(FINDMEM, "k", "내질문", lambda: [
        IF(eq(item("내질문", FINDMEM.get("k")), FINDMEM.p("키")), setv("찾은키번호", FINDMEM.get("k")), BREAK())]),
)
SAVEFACT.define(
    setv("저장키", repl(SAVEFACT.p("키"), "=", " ")),
    FINDMEM(V("저장키")),
    IFELSE(gt(V("찾은키번호"), 0),
           [setitem("내답변", V("찾은키번호"), SAVEFACT.p("값"))],
           [append("내질문", V("저장키")), append("내답변", SAVEFACT.p("값")),
            IF(gt(llen("내질문"), MAX_MEMORIES), remove("내질문", 1), remove("내답변", 1))]),
    setv("기억변경", 1),
)
RECALL.define(
    # 키 → 템플릿 (기억하고 있으면 대답, 모르면 물어보기)
    setv("꺼낼키", RECALL.p("키")),
    FINDMEM(V("꺼낼키")),
    setv("꺼낸번호", V("찾은키번호")),
    setv("키표시", KEYSHOW(V("꺼낼키"))),
    IFELSE(gt(V("꺼낸번호"), 0),
           [setv("값", item("내답변", V("꺼낸번호"))),
            IF(starts(V("값"), "F:"), setv("값", HEAD(V("값"), 2))),
            IFELSE(eq(V("꺼낼키"), "내 이름"), [setv("템플릿", pick("말-이름기억"))], [setv("템플릿", pick("말-기억답"))])],
           [setv("템플릿", pick("말-모름내것")), setv("이번대기", join("사실:", V("꺼낼키")))]),
)
CONNECT.define(
    # 말 속에 내가 기억하는 값(예: 고양이 이름 '나비')이 있으면 알아보고 앞에 붙일 말을 만든다.
    setv("아는이름", ""), setv("아는키", ""), setv("연결말", ""),
    *SCAN("내답변", lambda: [
        setv("연결값", item("내답변", V("연결k"))),
        IF(starts(V("연결값"), "F:"),
           setv("연결값", HEAD(V("연결값"), 2)),
           IF(AND(gt(slen(V("연결값")), 0), included("단어들", V("연결값"))),
              setv("아는이름", V("연결값")), setv("아는키", item("내질문", V("연결k"))), BREAK()))], 4, k="연결k"),
    IF(gt(slen(V("아는이름")), 0),
       IFELSE(AND(starts(V("아는키"), "내 "), ends(V("아는키"), " 이름"), gt(slen(V("아는키")), 5)),
              [setv("연결대상", TAIL(HEAD(V("아는키"), 2), 3)),
               setv("연결말", join("{이름}님의 ", V("연결대상"), " ", V("아는이름"), " 말이죠? ")),
               IF(has(T_TOPIC, V("연결대상")), setv("주제", V("연결대상")))],
              [setv("연결말", join(V("아는이름"), "! ", JOSA(KEYSHOW(V("아는키")), "이잖아요"), ". "))])),
)


LIKE = Func("좋아하는 것 찾기", ["말"])
LIKE.define(
    # '말' 은 '좋아' 또는 '싫어'. '좋아해/싫어해' 앞의 말을 대상으로 기억한다 ('그림 그리는 거' 처럼 '~거' 면 앞말 통째로).
    IF(AND(OR(*[contains(V("정리메시지"), join(LIKE.p("말"), t)) for t in ["해", "함", "한다", "하거든", "하는데"]]),
           NOT(contains(V("정리메시지"), join("안", LIKE.p("말"))))),
       setv("동사번호", 0),
       *SCAN("원단어들", lambda: [IF(starts(item("원단어들", V("사실k")), LIKE.p("말")),
                                    setv("동사번호", V("사실k")), BREAK())], 4, k="사실k"),
       setv("단어", ""), setv("거꼴", 0),
       IF(gt(V("동사번호"), 1), IF(OR(eq(item("원단어들", minus(V("동사번호"), 1)), "거"),
                                     eq(item("원단어들", minus(V("동사번호"), 1)), "것")), setv("거꼴", 1))),
       IFELSE(eq(V("거꼴"), 1),
              [setv("사실j", 1), IF(included("불용어", item("원단어들", 1)), setv("사실j", 2)),
               REPEAT(minus(V("동사번호"), V("사실j")),
                      setv("단어", join(V("단어"), " ", item("원단어들", V("사실j")))), chg("사실j", 1)),
               setv("단어", TRIM(V("단어")))],
              [setv("사실j", minus(V("동사번호"), 1)),
               UNTIL(lt(V("사실j"), 1),
                     IF(NOT(included("불용어", item("단어들", V("사실j")))),
                        IF(gt(slen(item("단어들", V("사실j"))), 0), setv("단어", item("단어들", V("사실j"))), BREAK())),
                     chg("사실j", -1))]),
       IF(gt(slen(V("단어")), 0),
          setv("좋아키", join("내가 ", LIKE.p("말"), "하는 것")),
          FINDMEM(V("좋아키")),
          setv("값", V("단어")),
          IF(gt(V("찾은키번호"), 0),
             setv("임시", item("내답변", V("찾은키번호"))),
             IF(starts(V("임시"), "F:"), setv("임시", HEAD(V("임시"), 2))),
             IFELSE(contains(V("임시"), V("단어")), [setv("값", V("임시"))], [setv("값", join(V("임시"), ", ", V("단어")))]),
             IF(gt(slen(V("값")), 60), setv("값", V("단어")))),
          SAVEFACT(V("좋아키"), join("F:", V("값"))),
          IFELSE(eq(LIKE.p("말"), "좋아"), [setv("템플릿", pick("말-좋아저장"))], [setv("템플릿", pick("말-싫어저장"))]),
          IF(has(T_TOPIC, V("단어")), setv("주제", V("단어")), setv("템플릿", join(V("템플릿"), " ", TOPICQ(V("단어"))))),
          setv("사실찾음", 1))),
)


_raw = lambda i: item("원단어들", i)
_stem = lambda i: item("단어들", i)
_my = lambda: OR(eq(_raw(1), "내"), eq(_raw(1), "제"), eq(_raw(1), "나의"), eq(_raw(1), "내가"), eq(_raw(1), "제가"))
FACTS.define(
    # 질문이 아닌 말에서 '내 X는 Y', 이름, 좋아하는 것/싫어하는 것, 나이를 찾아 기억한다.
    setv("사실찾음", 0),
    IF(gt(llen("원단어들"), 2),
       IF(AND(_my(), OR(eq(_raw(2), "이름은"), eq(_raw(2), "이름이"))),
          setv("값", ""), setv("사실j", 3),
          REPEAT(minus(llen("원단어들"), 2), setv("값", join(V("값"), " ", _raw(V("사실j")))), chg("사실j", 1)),
          setv("값", CLEAN(V("값"))),
          IF(AND(gt(slen(V("값")), 0), lt(slen(V("값")), 16)),
             SAVEFACT("내 이름", join("F:", V("값"))),
             setv("호칭", V("값")),
             setv("템플릿", pick("말-이름저장")),
             setv("사실찾음", 1)))),
    IF(eq(V("사실찾음"), 0), IF(gt(llen("원단어들"), 2), IF(_my(),
       setv("끝번호", 0), setv("사실j", 2),
       REPEAT(minus(llen("원단어들"), 2),
              IF(AND(gt(slen(_raw(V("사실j"))), 1), contains("은는", END(_raw(V("사실j")), 1))),
                 setv("끝번호", V("사실j")), BREAK()),
              chg("사실j", 1)),
       IF(gt(V("끝번호"), 1),
          setv("키", "내"), IF(OR(eq(_raw(1), "내가"), eq(_raw(1), "제가")), setv("키", "내가")),
          setv("사실j", 2),
          REPEAT(minus(V("끝번호"), 1), setv("키", join(V("키"), " ", _stem(V("사실j")))), chg("사실j", 1)),
          setv("값", ""), setv("사실j", plus(V("끝번호"), 1)),
          REPEAT(minus(llen("원단어들"), V("끝번호")), setv("값", join(V("값"), " ", _raw(V("사실j")))), chg("사실j", 1)),
          setv("값", CLEAN(V("값"))),
          IF(AND(gt(slen(V("값")), 0), lt(slen(V("값")), 41)),
             SAVEFACT(V("키"), join("F:", V("값"))),
             setv("키표시", KEYSHOW(V("키"))),
             setv("템플릿", pick("말-사실저장")),
             setv("사실찾음", 1)))))),
    IF(eq(V("사실찾음"), 0), LIKE("좋아")),
    IF(eq(V("사실찾음"), 0), LIKE("싫어")),
    IF(eq(V("사실찾음"), 0),
       *SCAN("원단어들", lambda: [
           setv("임시", _raw(V("사실k"))),
           IF(gt(find(V("임시"), "살"), 1),
              setv("임시", sub(V("임시"), 1, minus(find(V("임시"), "살"), 1))),
              IF(eq(V("임시"), minus(V("임시"), 0)),
                 setv("값", join(V("임시"), "살")),
                 SAVEFACT("내 나이", join("F:", V("값"))),
                 setv("템플릿", pick("말-나이저장")), setv("사실찾음", 1), BREAK()))], 4, k="사실k")),
)

STARTER.define(
    # 아직 모르는 것 하나를 골라 템플릿 뒤에 질문으로 붙인다 (먼저묻기 테이블에서 몇 번 골라 본다).
    setv("시작찾음", 0),
    *[IF(eq(V("시작찾음"), 0),
         setv("시작번호", rand(2, ASK_COUNT())),
         IF(NOT(included("내질문", ASK_GET(V("시작번호"), 1))),
            setv("템플릿", join(V("템플릿"), " ", ASK_GET(V("시작번호"), 2))),
            setv("이번대기", join("사실:", ASK_GET(V("시작번호"), 1))),
            setv("시작찾음", 1))) for _ in range(5)],
    IF(eq(V("시작찾음"), 0), setv("템플릿", join(V("템플릿"), " ", pick("말-이야기거리")))),
)

# ================================================================ 대답
HELP = SEP.join([
    "편하게 이야기해 보세요! 저는 이렇게 생각해요.",
    "· 문장에서 주제와 감정을 찾아 공감하고 되물어요",
    "· '내 생일은 3월 14일이야', '나 축구 좋아해' 같은 말을 기억해요",
    "· 모르는 건 물어보고, 알려 주면 배워요",
    "명령어: 기억 목록 · 나에 대해 알아? · 잊어줘: 내 생일",
    "기록표 · 기록 검색: 고양이 · 기록 통계",
    "번역: 문장 · 한국어로: sentence · 계산: 12*3",
    "몇 시야? · 새 대화 · 종료",
])
TEACH_FORMAT = "이렇게 입력해 주세요 → 기억해: 질문 = 답 (예: 기억해: 내 별명 = 꼬마)"
m = lambda: V("정리메시지")
cmd = lambda *names: OR(*[eq(V("명령"), n) for n in names])
is_q = lambda: eq(V("질문여부"), 1)
not_q = lambda: eq(V("질문여부"), 0)
undone = lambda: eq(V("처리됨"), 0)

sensitive = lambda v: OR(*[contains(v, w_) for w_ in D.SENSITIVE])
R_CMD.define(
    # 위기 신호는 무엇보다 먼저 받아 준다
    BRANCH(OR(*[contains(m(), w_) for w_ in D.CRISIS]), setv("템플릿", pick("말-위기")), setv("새기분", "나쁨")),
    BRANCH(OR(starts(m(), "도움말"), eq(m(), "help"), eq(m(), "?")), setv("답변", HELP)),
    BRANCH(cmd("기억해", "가르치기", "기억"),
           setv("위치", find(V("내용"), "=")),
           IFELSE(AND(gt(V("위치"), 1), lt(V("위치"), slen(V("내용")))),
                  [setv("키", TRIM(sub(V("내용"), 1, minus(V("위치"), 1)))),
                   setv("저장값", TRIM(HEAD(V("내용"), V("위치")))),
                   IFELSE(OR(empty(V("키")), empty(V("저장값"))),
                          [setv("답변", TEACH_FORMAT)],
                          [IFELSE(sensitive(lower(repl(V("내용"), " ", ""))),
                                  [setv("템플릿", pick("말-개인정보")), setv("기록가림", 1)],
                          [IF(gt(slen(V("키")), 40), setv("키", sub(V("키"), 1, 40))),
                           IF(gt(slen(V("저장값")), 100), setv("저장값", sub(V("저장값"), 1, 100))),
                           SAVEFACT(V("키"), V("저장값")),
                           setv("답변", join("알겠어요! 앞으로 '", V("키"), "'(이)라고 물으면 '", V("저장값"), "'(이)라고 답할게요.")),
                           IF(eq(V("저장가능"), 0),
                              setv("답변", join(V("답변"), " (저장되지 않는 상태라 이번 실행에서만 기억해요.)")))])])],
                  [setv("답변", TEACH_FORMAT)])),
    BRANCH(cmd("잊어줘", "잊어", "삭제"),
           IFELSE(empty(V("내용")),
                  [setv("답변", "이렇게 입력해 주세요 → 잊어줘: 내 생일")],
                  [FINDMEM(V("내용")),
                   IFELSE(gt(V("찾은키번호"), 0),
                          [remove("내질문", V("찾은키번호")), remove("내답변", V("찾은키번호")), setv("기억변경", 1),
                           setv("답변", join("'", V("내용"), "'에 대한 기억을 지웠어요."))],
                          [setv("답변", join("'", V("내용"), "'(이)라는 기억은 없어요. '기억 목록'으로 확인해 보세요."))])])),
    BRANCH(cmd("번역", "영어로", "영어"),
           IFELSE(empty(V("내용")),
                  [setv("답변", "번역할 문장도 같이 입력해 주세요. 예) 번역: 오늘 날씨가 좋아요")],
                  [setv("답변", join("영어로는 이렇게 말해요 → ", translate("ko", V("내용"), "en")))])),
    BRANCH(cmd("한국어로", "한글로", "한국어"),
           IFELSE(empty(V("내용")),
                  [setv("답변", "번역할 영어 문장도 같이 입력해 주세요. 예) 한국어로: Nice to meet you")],
                  [setv("답변", join("한국어로는 이렇게 말해요 → ", translate("en", V("내용"), "ko")))])),
    BRANCH(cmd("계산", "계산해줘", "계산해"), setv("답변", CALC(V("내용")))),
    BRANCH(cmd("기록검색", "검색", "기록찾기"), SEARCH(V("내용"))),
    BRANCH(OR(eq(m(), "기록통계"), eq(m(), "대화통계"), eq(m(), "통계"), eq(m(), "오늘대화")), STATS()),
    BRANCH(OR(eq(m(), "기록표"), eq(m(), "기록보기"), eq(m(), "대화기록"), eq(m(), "기록표보기")),
           LOG_OPEN(),
           setv("답변", join("대화 기록표를 열었어요. 모두 ", minus(LOG_COUNT(), 1),
                             "줄이에요. 날짜·시각·누가·주제·감정·내용이 정리돼 있어요. 창을 닫으면 이어서 이야기해요."))),
    BRANCH(OR(eq(m(), "기억목록"), eq(m(), "기억보기")),
           setv("답변", ""), setv("요약수", 0),
           *SCAN("내질문", lambda: [IF(NOT(starts(item("내질문", V("답k")), "#")),
                                      setv("값", item("내답변", V("답k"))), IF(starts(V("값"), "F:"), setv("값", HEAD(V("값"), 2))),
                                      setv("답변", join(V("답변"), SEP, "· ", item("내질문", V("답k")), " → ", V("값"))),
                                      chg("요약수", 1))], 3, k="답k"),
           IFELSE(eq(V("요약수"), 0),
                  [setv("답변", "아직 기억하고 있는 게 없어요. 이야기를 들려주면 하나씩 기억할게요!")],
                  [setv("답변", join("기억하고 있는 것 ", V("요약수"), "개예요.", V("답변")))])),
    BRANCH(OR(eq(m(), "새대화"), eq(m(), "초기화"), eq(m(), "기록삭제")),
           setv("기록블롭", ""), clear("화면글"), clear("화면종류"), CLEARLOG(),
           setv("답변", "대화 기록을 지웠어요. 새로 시작해요! (기억하고 있는 건 그대로예요.)")),
    BRANCH(OR(eq(m(), "종료"), eq(m(), "그만"), eq(m(), "끝"), eq(m(), "bye")),
           setv("대화중", 0),
           setv("템플릿", "오늘 이야기 즐거웠어요, {이름}님! 다시 이야기하려면 시작 버튼을 눌러 주세요.")),
)

R_PENDING.define(
    # 비밀번호·전화번호 같은 개인정보는 기억하지 않는다
    BRANCH(AND(not_q(), sensitive(m())), setv("템플릿", pick("말-개인정보")), setv("기록가림", 1)),
    # 직전에 내가 물어본 것에 대한 대답이면 기억한다
    BRANCH(AND(starts(V("지난대기"), "사실:"), not_q(), empty(V("명령")), lt(slen(V("문장")), 26),
               lt(llen("원단어들"), 5), NOT(eq(V("서술종류"), "동사")),
               NOT(OR(*[contains(m(), w_) for w_ in D.SOCIAL]))),
           setv("키", HEAD(V("지난대기"), 3)),
           IFELSE(OR(*[contains(m(), d) for d in D.DONT_KNOW]),
                  [setv("템플릿", pick("말-몰라"))],
                  [setv("값", V("문장")),
                   # "이름은 초코야" 처럼 키의 낱말을 다시 말하면 떼어 낸다
                   IF(gt(llen("원단어들"), 1),
                      IF(AND(contains("은는이가", END(item("원단어들", 1), 1)), contains(V("키"), item("단어들", 1))),
                         setv("값", HEAD(V("값"), slen(item("원단어들", 1)))))),
                   setv("값", CLEAN(V("값"))),
                   IFELSE(OR(empty(V("값")), included("모름말", V("값"))),
                          [setv("템플릿", pick("말-몰라"))],
                          [SAVEFACT(V("키"), join("F:", V("값"))), setv("키표시", KEYSHOW(V("키"))),
                           IF(eq(V("키"), "내 이름"), setv("호칭", V("값"))),
                           IFELSE(starts(V("키"), "내"), [setv("템플릿", pick("말-사실저장"))],
                                  [setv("템플릿", pick("말-새지식"))])])])),
    BRANCH(AND(starts(V("지난대기"), "답:"), not_q(), empty(V("명령"))),
           SAVEFACT(HEAD(V("지난대기"), 2), V("메시지")),
           setv("템플릿", pick("말-질문배움"))),
    # 이야기 속 사실 기억하기
    IF(undone(), IF(AND(not_q(), empty(V("명령"))), FACTS(), IF(eq(V("사실찾음"), 1), setv("처리됨", 1)))),
)

R_MEMORY.define(IF(undone(),
    # 기억해:로 가르친 것은 문장 어디에 있든, 이야기에서 배운 사실(F:)은 '내 X'처럼 띄어 쓴 키면 문장 안에,
    # 한 낱말 키면 낱말로 들어 있을 때만 찾는다.
    setv("찾은번호", 0), setv("최장길이", 0),
    *SCAN("내질문", lambda: [
        setv("기억키", item("내질문", V("답k"))),
        setv("비교어", repl(lower(V("기억키")), " ", "")),
        IF(AND(gt(slen(V("비교어")), V("최장길이")), NOT(starts(V("비교어"), "#"))),
           setv("일치", 0),
           IFELSE(OR(NOT(starts(item("내답변", V("답k")), "F:")), contains(V("기억키"), " ")),
                  [IF(contains(m(), V("비교어")), setv("일치", 1))],
                  [IF(OR(included("단어들", V("기억키")), included("단어들", V("비교어"))), setv("일치", 1))]),
           IF(eq(V("일치"), 1), setv("최장길이", slen(V("비교어"))), setv("찾은번호", V("답k"))))], 4, k="답k"),
    setv("기억응답", 0),
    IF(gt(V("찾은번호"), 0),
       IFELSE(starts(item("내답변", V("찾은번호")), "F:"), [IF(is_q(), setv("기억응답", 1))], [setv("기억응답", 2)])),
    BRANCH(eq(V("기억응답"), 1), RECALL(item("내질문", V("찾은번호")))),
    BRANCH(eq(V("기억응답"), 2), setv("답변", item("내답변", V("찾은번호")))),
    BRANCH(AND(is_q(), contains(m(), "이름"),
               OR(starts(m(), "이름"), *[eq(item("원단어들", 1), y) for y in D.YOU_WORDS], starts(m(), "네이름"))),
           setv("템플릿", pick("말-봇이름")), guard=gt(llen("원단어들"), 0)),
    # "내 생일 언제라고 했지?", "몇 살이라고 했지?" — 나에 대해 묻는 질문인지 한 번만 따진다
    setv("내것질문", 0),
    IF(AND(is_q(), OR(contains(m(), "라고했"), contains(m(), "기억"), starts(m(), "내"), starts(m(), "나"),
                      starts(m(), "제")),
           NOT(OR(starts(m(), "너"), starts(m(), "넌"), starts(m(), "니")))), setv("내것질문", 1)),
    *[BRANCH(contains(m(), cue),
             RECALL(key),
             *([IF(eq(V("꺼낸번호"), 0), setv("템플릿", pick("말-내이름")), setv("이번대기", ""))] if key == "내 이름" else []),
             guard=eq(V("내것질문"), 1))
      for cue, key in D.RECALL_ALIASES],
    BRANCH(AND(is_q(), contains(m(), "좋아"), OR(starts(m(), "내가"), starts(m(), "나뭐"), starts(m(), "난뭐"))),
           RECALL("내가 좋아하는 것")),
    BRANCH(AND(is_q(), contains(m(), "싫어"), OR(starts(m(), "내가"), starts(m(), "나뭐"), starts(m(), "난뭐"))),
           RECALL("내가 싫어하는 것")),
    BRANCH(OR(contains(m(), "나에대해"), contains(m(), "나에관해"), contains(m(), "나를기억"), contains(m(), "나기억해"),
              contains(m(), "내정보")),
           setv("템플릿", "제가 기억하는 {이름}님은요:"), setv("요약수", 0),
           *SCAN("내질문", lambda: [IF(AND(starts(item("내답변", V("답k")), "F:"), lt(V("요약수"), 6)),
                                      setv("키", item("내질문", V("답k"))), setv("값", HEAD(item("내답변", V("답k")), 2)),
                                      IF(starts(V("키"), "내가 "), setv("키", HEAD(V("키"), 3))),
                                      IF(starts(V("키"), "내 "), setv("키", HEAD(V("키"), 2))),
                                      setv("템플릿", join(V("템플릿"), SEP, "· ", V("키"), " → ", V("값"))),
                                      chg("요약수", 1))], 3, k="답k"),
           IF(eq(V("요약수"), 0),
              setv("템플릿", "아직 {이름}님에 대해 아는 게 많지 않아요. 이야기를 들려주면 하나씩 기억할게요! [이야기]"))),
    BRANCH(AND(OR(eq(item("원단어들", 1), "내"), eq(item("원단어들", 1), "제"), eq(item("원단어들", 1), "나의")),
               NOT(included("불용어", item("단어들", 2)))),
           RECALL(join("내 ", item("단어들", 2))),
           guard=AND(is_q(), gt(llen("원단어들"), 1))),
))

_talk_guard = lambda: OR(is_q(), lt(slen(m()), 9), AND(empty(V("주제")), eq(V("감정점수"), 0)))
R_TALK.define(IF(undone(),
    # 단어 뜻 (단어뜻 테이블에서 VLOOKUP)
    BRANCH(AND(is_q(), eq(V("뜻질문"), 1), gt(slen(V("단어")), 0), has(T_DEF, lower(V("단어")))),
           setv("템플릿", join("{단어은} ", lookup(T_DEF, lower(V("단어")), 2)))),
    BRANCH(OR(contains(m(), "몇시"), contains(m(), "지금시간"), contains(m(), "현재시간")),
           setv("답변", join("지금은 ", date("HOUR"), "시 ", date("MINUTE"), "분이에요."))),
    BRANCH(OR(contains(m(), "며칠"), contains(m(), "날짜"), contains(m(), "무슨요일"), contains(m(), "몇월")),
           setv("답변", join("오늘은 ", date("YEAR"), "년 ", date("MONTH"), "월 ", date("DAY"), "일 ",
                             item("요일", plus(date("DAY_OF_WEEK"), 1)), "요일이에요."))),
    # 일상 대화 (질문이거나, 짧거나, 주제·감정이 없는 말일 때) — 말 속에서 가장 긴 키워드를 찾아
    # 그 줄의 대답들('|' 로 나눠 둔 것) 중에서 고른다
    IF(undone(), IF(_talk_guard(),
       *FIND_PIECE(T_TALK, m(), "찾은말", "최장길이", "답k"),
       IF(gt(slen(V("찾은말")), 0),
          setv("남은답", join(lookup(T_TALK, V("찾은말"), 2), " | ")),
          UNTIL(empty(V("남은답")),
                setv("답위치", find(V("남은답"), " | ")),
                append("후보답변", TRIM(sub(V("남은답"), 1, minus(V("답위치"), 1)))),
                setv("남은답", HEAD(V("남은답"), plus(V("답위치"), 2))))))),
    BRANCH(gt(llen("후보답변"), 0), setv("템플릿", pick("후보답변"))),
    BRANCH(AND(is_q(), OR(*[eq(item("원단어들", 1), y) for y in D.YOU_WORDS])),
           setv("템플릿", pick("말-너질문")), guard=gt(llen("원단어들"), 0)),
    # 모르는 단어는 물어보고 배운다 (낱말 하나에 대한 질문일 때)
    BRANCH(AND(is_q(), eq(V("뜻질문"), 1), gt(slen(V("단어")), 0), eq(V("내용어수"), 1)),
           setv("템플릿", pick("말-모르는단어")), setv("이번대기", join("사실:", V("단어")))),
    # 정보를 묻는 질문인데 모르면 답을 배운다 ("우리 학교 이름이 뭐게?")
    BRANCH(AND(is_q(), OR(*[contains(m(), c) for c in D.INFO_CUES]), lt(slen(V("문장")), 41)),
           setv("템플릿", pick("말-모르는질문")), setv("이번대기", join("답:", V("문장")))),
))


def _feeling(neg):
    return [
        setv("연결허용", 1),
        ELIF_CHAIN((gt(slen(V("서술")), 0),
                    [setv("템플릿", join(V("서술"), ". ", pick("말-공감부정뒤" if neg else "말-공감긍정뒤")))]),
                   (gt(slen(V("주제")), 0), [setv("템플릿", pick("말-공감부정주제" if neg else "말-공감긍정주제"))]),
                   otherwise=[setv("템플릿", pick("말-공감부정" if neg else "말-공감긍정"))]),
        setv("주제질문", TOPICQ(V("주제"))),
        IFELSE(AND(gt(slen(V("주제질문")), 0), eq(rand(1, 2), 1), *([eq(V("주제질문대체"), 0)] if neg else [])),
               [setv("템플릿", join(V("템플릿"), " ", V("주제질문")))],
               [setv("템플릿", join(V("템플릿"), " ", pick("말-이어묻기부정" if neg else "말-이어묻기긍정")))]),
        setv("새기분", "나쁨" if neg else "좋음"),
    ]


R_FEEL.define(IF(undone(),
    BRANCH(AND(not_q(), OR(*[contains(m(), wd) for wd in D.WORRY])),
           setv("연결허용", 1),
           IFELSE(gt(slen(V("주제")), 0), [setv("템플릿", pick("말-걱정주제"))], [setv("템플릿", pick("말-걱정"))]),
           setv("템플릿", join(V("템플릿"), " ", pick("말-이어묻기걱정"))),
           setv("새기분", "걱정")),
    # 걱정하던 일이 무엇인지 말해 주면 그 일을 응원한다
    BRANCH(AND(not_q(), eq(V("직전기분"), "걱정"), gt(slen(V("주제")), 0), NOT(gt(V("감정점수"), 0))),
           setv("연결허용", 1),
           setv("템플릿", join(pick("말-걱정주제"), " ", pick("말-응원"))),
           setv("새기분", "걱정")),
    BRANCH(AND(not_q(), OR(*[contains(m(), d) for d in D.DONT_KNOW]), lt(slen(m()), 10)),
           setv("템플릿", pick("말-모르겠어"))),
    # 기분을 물었는데 좋다고 하면
    BRANCH(AND(eq(V("지난대기"), "기분"), not_q(),
               OR(gt(V("감정점수"), 0), *[starts(m(), y) for y in ["응", "웅", "네", "괜찮", "좋아", "ㅇㅇ"]]),
               NOT(lt(V("감정점수"), 0)), empty(V("서술")), empty(V("주제"))),
           setv("템플릿", pick("말-기분응")), setv("새기분", "좋음")),
    # 이유를 말해 주는 중이면 앞의 이야기와 이어서 받아 준다
    setv("이유모드", 0),
    IF(AND(NOT(gt(V("감정점수"), 0)), OR(eq(V("지난대기"), "이유"), contains(m(), "때문"), eq(V("서끝1"), "서"),
          AND(eq(V("직전기분"), "나쁨"), OR(ends(V("문장"), "다고"), ends(V("문장"), "라고"))),
          AND(eq(V("직전기분"), "나쁨"), gt(slen(V("서술")), 0),
              OR(eq(V("지난대기"), "기분"), eq(V("지난대기"), "이야기"))))),
       setv("이유모드", 1)),
    BRANCH(AND(not_q(), eq(V("이유모드"), 1), OR(gt(slen(V("서술")), 0), gt(slen(V("주제")), 0))),
           setv("연결허용", 1),
           IFELSE(gt(slen(V("서술")), 0), [setv("템플릿", join(V("서술"), "."))], [setv("템플릿", pick("말-이유주제"))]),
           IFELSE(AND(NOT(gt(V("감정점수"), 0)), OR(eq(V("직전기분"), "나쁨"), lt(V("감정점수"), 0))),
                  [setv("템플릿", join(V("템플릿"), " ", pick("말-이유부정뒤"), " ", pick("말-위로"))), setv("새기분", "나쁨")],
                  [IFELSE(gt(V("감정점수"), 0), [setv("템플릿", join(V("템플릿"), " ", pick("말-이유긍정뒤")))],
                          [setv("템플릿", join(V("템플릿"), " ", pick("말-들어줌")))]),
                   setv("템플릿", join(V("템플릿"), " ", pick("말-이유이어")))])),
    BRANCH(AND(not_q(), lt(V("감정점수"), 0)), *_feeling(True)),
    BRANCH(AND(not_q(), gt(V("감정점수"), 0)), *_feeling(False)),
    BRANCH(AND(eq(V("지난대기"), "기분"), not_q(), lt(slen(V("문장")), 9), empty(V("주제")), empty(V("서술"))),
           IFELSE(included("예말", m()), [setv("템플릿", pick("말-기분응"))], [setv("템플릿", pick("말-기분보통"))])),
    BRANCH(AND(is_q(), OR(ends(V("문장"), "할까"), ends(V("문장"), "될까"), ends(V("문장"), "갈까"), ends(V("문장"), "까요"))),
           setv("템플릿", pick("말-고민질문"))),
    # 주제 이어 가기 / 되받기
    BRANCH(gt(slen(V("주제")), 0),
           setv("연결허용", 1),
           IFELSE(gt(slen(V("서술")), 0), [setv("템플릿", join(V("서술"), "!"))], [setv("템플릿", pick("말-주제반응"))]),
           setv("템플릿", join(V("템플릿"), " ", TOPICQ(V("주제"))))),
    BRANCH(gt(slen(V("서술")), 0), setv("연결허용", 1), setv("템플릿", join(V("서술"), "! ", pick("말-되묻기")))),
))

R_LAST.define(IF(undone(),
    # 모르는 질문은 답을 배운다
    BRANCH(is_q(),
           setv("템플릿", pick("말-모르는질문")),
           IF(lt(slen(V("문장")), 41), setv("이번대기", join("답:", V("문장"))))),
    # 짧은 대답 ("양념", "건축") 은 받아 주고 이어 간다
    setv("짧은값", ""),
    IF(undone(), setv("짧은값", CLEAN(V("문장")))),
    BRANCH(AND(OR(eq(V("지난대기"), "이야기"), eq(V("지난대기"), "이유"), eq(V("지난대기"), "기분")), not_q(),
               gt(slen(V("짧은값")), 0), lt(slen(V("짧은값")), 13), NOT(included("모름말", V("짧은값")))),
           setv("단어", V("짧은값")), setv("연결허용", 1), setv("템플릿", pick("말-짧은대답")),
           IF(eq(rand(1, 2), 1), STARTER())),
    BRANCH(OR(eq(V("지난대기"), "이유"), eq(V("지난대기"), "이야기")),
           setv("연결허용", 1), setv("템플릿", pick("말-들어줌")),
           IF(eq(rand(1, 2), 1), STARTER())),
    BRANCH(gt(slen(V("후보주제")), 1), setv("단어", V("후보주제")), setv("템플릿", pick("말-후보반응"))),
    BRANCH(eq(V("직전기분"), "나쁨"), setv("템플릿", pick("말-위로마무리"))),
    BRANCH(eq(1, 1), setv("템플릿", pick("말-맞장구")), STARTER()),
))

REPLY.define(
    setv("답변", ""), setv("템플릿", ""), setv("처리됨", 0), setv("이번대기", ""), setv("새기분", ""), setv("기록가림", 0),
    setv("지난대기", V("대기질문")), setv("대기질문", ""),
    clear("후보답변"),
    ANALYZE(),
    setv("연결허용", 0),
    CONNECT(),
    # "명령: 내용" 나누기
    setv("명령", ""), setv("내용", ""),
    setv("위치", find(V("메시지"), ":")),
    IF(gt(V("위치"), 1),
       setv("명령", repl(sub(V("메시지"), 1, minus(V("위치"), 1)), " ", "")),
       setv("내용", TRIM(HEAD(V("메시지"), V("위치"))))),
    R_CMD(), R_PENDING(), R_MEMORY(), R_TALK(), R_FEEL(), R_LAST(),
    # 마무리: 템플릿 → 답변, 대화 상태 저장
    IF(AND(eq(V("연결허용"), 1), gt(slen(V("연결말")), 0), gt(slen(V("템플릿")), 0)),
       setv("템플릿", join(V("연결말"), V("템플릿")))),
    IF(gt(slen(V("템플릿")), 0), setv("답변", FILL(V("템플릿")))),
    IF(empty(V("답변")), setv("답변", "음… 다시 한번 말해 줄래요?")),
    # 바로 전과 똑같은 대답은 하지 않는다
    IF(eq(V("답변"), V("지난답변")),
       setv("이번대기", ""), setv("템플릿", pick("말-맞장구")), STARTER(), setv("답변", FILL(V("템플릿")))),
    setv("지난답변", V("답변")),
    setv("직전기분", V("새기분")),
    setv("대기질문", V("이번대기")),
    IF(AND(eq(V("연결허용"), 1), gt(slen(V("주제")), 0), NOT(eq(V("주제"), V("최근주제")))),
       setv("최근주제", V("주제")), SAVEFACT("#최근주제", V("주제"))),
    IF(AND(gt(slen(V("새기분")), 0), NOT(eq(V("새기분"), V("지난기분")))),
       setv("지난기분", V("새기분")), SAVEFACT("#기분", V("새기분"))),
)

# ================================================================ 대화기록표 (테이블)
_dash = lambda v: v  # 빈 칸은 '-' 로 넣는다 (엔트리 테이블은 빈 칸을 '없음'으로 보고 다시 못 바꾼다)
LOGROW.define(
    LOG_ADD(),
    setv("기록행", LOG_COUNT()),
    LOG_SET(V("기록행"), C_NO, minus(V("기록행"), 1)),
    *[IFELSE(empty(LOGROW.p(name)), [LOG_SET(V("기록행"), col, "-")], [LOG_SET(V("기록행"), col, LOGROW.p(name))])
      for name, col in [("날짜", C_DATE), ("시각", C_TIME), ("누가", C_WHO), ("주제", C_TOPIC), ("감정", C_FEEL),
                        ("내용", C_TEXT)]],
)
LOG.define(
    # 한 줄을 '누가|날짜|시각|주제|감정|내용' 으로 서버용 기록에 붙이고, 대화기록표에도 넣는다.
    setv("기록내용", repl(repl(LOG.p("내용"), SEP, " / "), "|", "/")),
    IFELSE(eq(LOG.p("누가"), "나"), [setv("기록감정", V("감정점수"))], [setv("기록감정", "-")]),
    IFELSE(gt(slen(V("주제")), 0), [setv("기록주제", V("주제"))], [setv("기록주제", "-")]),
    setv("기록날짜", TODAY()), setv("기록시각", NOW()),
    setv("추가줄", join(LOG.p("누가"), "|", V("기록날짜"), "|", V("기록시각"), "|", V("기록주제"), "|", V("기록감정"), "|",
                      V("기록내용"))),
    IF(gt(slen(V("추가줄")), MAX_LINE_LEN), setv("추가줄", join(sub(V("추가줄"), 1, MAX_LINE_LEN), "…"))),
    setv("기록블롭", join(V("기록블롭"), V("추가줄"), SEP)),
    UNTIL(lt(count(V("기록블롭"), SEP), MAX_HISTORY_LINES + 1),
          setv("위치", find(V("기록블롭"), SEP)), setv("기록블롭", HEAD(V("기록블롭"), V("위치")))),
    LOGROW(V("기록날짜"), V("기록시각"), LOG.p("누가"), V("기록주제"), V("기록감정"), V("기록내용")),
)
PARSELINE.define(
    # 서버 기록 한 줄 → 줄누가·줄날짜·줄시각·줄주제·줄감정·줄내용 (예전 형식 '나: 내용' 도 읽는다)
    setv("줄남은", PARSELINE.p("줄")),
    IFELSE(contains(V("줄남은"), "|"),
           [*[x for var in ["줄누가", "줄날짜", "줄시각", "줄주제", "줄감정"]
              for x in SPLIT_LINE("줄남은", var, "줄위치", sep="|")],
            setv("줄내용", V("줄남은"))],
           [IFELSE(starts(V("줄남은"), "나: "), [setv("줄누가", "나")], [setv("줄누가", "봇")]),
            setv("줄내용", HEAD(V("줄남은"), 3)),
            setv("줄날짜", "-"), setv("줄시각", "-"), setv("줄주제", "-"), setv("줄감정", "-")]),
)
CLEARLOG.define(UNTIL(lt(LOG_COUNT(), 2), *[IF(gt(LOG_COUNT(), 1), LOG_DEL(2)) for _ in range(5)]))

_row = lambda col: LOG_GET(V("검색k"), col)
SEARCH.define(
    IFELSE(empty(SEARCH.p("낱말")),
           [setv("답변", "이렇게 입력해 주세요 → 기록 검색: 고양이")],
           [setv("검색결과", ""), SEARCH.set("찾은수", 0),
            setv("검색k", LOG_COUNT()),
            # 최근 기록부터 거꾸로 훑는다
            UNTIL(lt(V("검색k"), 2), *[x for _ in range(3) for x in [
                IF(NOT(lt(V("검색k"), 2)),
                   IF(contains(_row(C_TEXT), SEARCH.p("낱말")),
                      SEARCH.inc("찾은수"),
                      IF(lt(SEARCH.get("찾은수"), 6),
                         setv("검색결과", join(V("검색결과"), SEP, "· ", HEAD(_row(C_DATE), 5), " ", _row(C_TIME), " ",
                                               _row(C_WHO), ": ", _row(C_TEXT)))))),
                chg("검색k", -1)]]),
            IFELSE(eq(SEARCH.get("찾은수"), 0),
                   [setv("답변", join("'", SEARCH.p("낱말"), "'(이)라는 말이 들어간 기록은 없어요."))],
                   [setv("답변", join("'", SEARCH.p("낱말"), "' 기록을 ", SEARCH.get("찾은수"), "개 찾았어요. (최근 것부터 5개까지)",
                                      V("검색결과")))])]),
)

_srow = lambda col: LOG_GET(V("통계k"), col)
STATS.define(
    setv("통계주제글", ""), clear("통계주제"), setv("오늘날짜", TODAY()),
    setv("통계k", 2),
    UNTIL(gt(V("통계k"), LOG_COUNT()), *[x for _ in range(3) for x in [
        IF(NOT(gt(V("통계k"), LOG_COUNT())),
           IFELSE(eq(_srow(C_WHO), "나"),
                  [STATS.inc("내말"),
                   ELIF_CHAIN((gt(_srow(C_FEEL), 0), [STATS.inc("좋음")]), (lt(_srow(C_FEEL), 0), [STATS.inc("나쁨")]),
                              otherwise=[STATS.inc("보통")]),
                   IF(eq(_srow(C_DATE), V("오늘날짜")), STATS.inc("오늘")),
                   IF(NOT(eq(_srow(C_TOPIC), "-")),
                      setv("통계주제글", join(V("통계주제글"), "|", _srow(C_TOPIC), "|")),
                      IF(NOT(included("통계주제", _srow(C_TOPIC))), append("통계주제", _srow(C_TOPIC))))],
                  [STATS.inc("봇말")])),
        chg("통계k", 1)]]),
    # 가장 많이 나온 주제
    setv("최다주제", ""), setv("최다수", 0), setv("통계j", 1),
    REPEAT(llen("통계주제"),
           setv("주제수", count(V("통계주제글"), join("|", item("통계주제", V("통계j")), "|"))),
           IF(gt(V("주제수"), V("최다수")), setv("최다수", V("주제수")), setv("최다주제", item("통계주제", V("통계j")))),
           chg("통계j", 1)),
    setv("답변", join("대화 기록 통계예요.", SEP, "· 모두 ", minus(LOG_COUNT(), 1), "줄 (", V("호칭"), "님 ",
                      STATS.get("내말"), "줄 · 엔봇 ", STATS.get("봇말"), "줄)", SEP, "· 오늘 ", V("호칭"), "님이 한 말: ",
                      STATS.get("오늘"), "줄", SEP, "· 기분: 좋음 ", STATS.get("좋음"), " · 보통 ", STATS.get("보통"),
                      " · 나쁨 ", STATS.get("나쁨"))),
    IF(gt(V("최다수"), 0),
       setv("답변", join(V("답변"), SEP, "· 제일 많이 나온 주제: ", V("최다주제"), " (", V("최다수"), "번)"))),
    setv("답변", join(V("답변"), SEP, "'기록표'라고 하면 표로 볼 수 있어요.")),
)


# ================================================================ 서버 저장 (실시간 리스트)
def _find_slot(lst, pos_var):
    return [setv(pos_var, 0),
            *SCAN(lst, lambda: [IF(starts(item(lst, V("칸k")), V("접두어")), setv(pos_var, V("칸k")), BREAK())],
                  8, k="칸k")]


def _save_slot(lst, pos_var, finder, blob_var):
    """내 칸이 맞는지 확인한 뒤 서버 리스트의 내 칸을 '아이디|' + blob 으로 바꾼다."""
    return IF(eq(V("저장가능"), 1),
              setv("확인", 0),
              IF(gt(V(pos_var), 0),
                 IF(NOT(gt(V(pos_var), llen(lst))), IF(starts(item(lst, V(pos_var)), V("접두어")), setv("확인", 1)))),
              IF(eq(V("확인"), 0), finder(), IF(gt(V(pos_var), 0), setv("확인", 1))),
              IF(eq(V("확인"), 1), setitem(lst, V(pos_var), join(V("접두어"), V(blob_var)))))


def _ensure_slot(lst, pos_var, finder):
    """내 칸이 없으면 새로 만들고, 서버 반영을 기다렸다가 다시 찾는다."""
    return [finder(),
            IF(eq(V(pos_var), 0), append(lst, V("접두어")), WAIT(1), finder(), IF(eq(V(pos_var), 0), WAIT(2), finder()))]


def _load_blob(lst, pos_var, blob_var):
    return [setv(blob_var, ""),
            IF(gt(V(pos_var), 0), setv(blob_var, HEAD(item(lst, V(pos_var)), slen(V("접두어")))))]


SLOT_LOG.define(*_find_slot("대화기록", "기록위치"))
SLOT_MEM.define(*_find_slot("기억저장소", "기억위치"))
SAVELOG.define(_save_slot("대화기록", "기록위치", SLOT_LOG, "기록블롭"))
SAVEMEM.define(
    setv("기억블롭", ""), setv("묶음k", 1),
    REPEAT(llen("내질문"),
           setv("기억블롭", join(V("기억블롭"), item("내질문", V("묶음k")), "=", item("내답변", V("묶음k")), SEP)),
           chg("묶음k", 1)),
    _save_slot("기억저장소", "기억위치", SLOT_MEM, "기억블롭"),
)
LOAD.define(
    *_ensure_slot("대화기록", "기록위치", SLOT_LOG),
    *_ensure_slot("기억저장소", "기억위치", SLOT_MEM),
    IF(OR(eq(V("기록위치"), 0), eq(V("기억위치"), 0)), setv("저장가능", 0)),
    *_load_blob("대화기록", "기록위치", "기록블롭"),
    *_load_blob("기억저장소", "기억위치", "기억블롭"),
    # 기억블롭 "키=값¶키=값¶" → 내질문 / 내답변 리스트
    setv("남은문자열", V("기억블롭")),
    UNTIL(empty(V("남은문자열")),
          *SPLIT_LINE("남은문자열", "줄", "위치"),
          setv("위치", find(V("줄"), "=")),
          IF(gt(V("위치"), 1), IF(lt(V("위치"), slen(V("줄"))),
                                 append("내질문", sub(V("줄"), 1, minus(V("위치"), 1))),
                                 append("내답변", HEAD(V("줄"), V("위치")))))),
    # 지난번 대화 상태
    *SCAN("내질문", lambda: [
        ELIF_CHAIN((eq(item("내질문", V("불러k")), "#최근주제"), [setv("최근주제", item("내답변", V("불러k")))]),
                   (eq(item("내질문", V("불러k")), "#기분"), [setv("지난기분", item("내답변", V("불러k")))]),
                   (eq(item("내질문", V("불러k")), "내 이름"),
                    [IF(starts(item("내답변", V("불러k")), "F:"), setv("호칭", HEAD(item("내답변", V("불러k")), 2)))]))],
          3, k="불러k"),
    # 지난 대화 → 대화기록표에 펼치고, 마지막 몇 줄은 말풍선으로 보여 준다
    setv("전체줄수", count(V("기록블롭"), SEP)),
    IF(gt(V("전체줄수"), 0), PRINT("── 지난 대화 ──", "알림")),
    setv("남은문자열", V("기록블롭")),
    LOAD.set("줄번호", 0),
    UNTIL(empty(V("남은문자열")),
          *SPLIT_LINE("남은문자열", "줄", "위치"),
          LOAD.inc("줄번호"),
          IF(gt(slen(V("줄")), 0),
             PARSELINE(V("줄")),
             LOGROW(V("줄날짜"), V("줄시각"), V("줄누가"), V("줄주제"), V("줄감정"), V("줄내용")),
             IF(gt(LOAD.get("줄번호"), minus(V("전체줄수"), SHOW_HISTORY)), PRINT(V("줄내용"), V("줄누가"))))),
    IF(gt(V("전체줄수"), 0), PRINT("── 이어서 이야기해요 ──", "알림")),
)


# ================================================================ 메인
def main_script():
    clean_input = repl(repl(repl(repl(repl(repl(answer(), SEP, " "), "[", "("), "]", ")"), "{", "("), "}", ")"), "|", "/")
    return WHEN_START(
        setv("글자-받침없음", D.NO_BATCHIM), setv("글자-ㄹ받침", D.RIEUL), setv("글자-ㅆ받침", D.SSANG_SIOT),
        HIDE_ANSWER(),
        clear("화면글"), clear("화면종류"), clear("후보답변"), clear("내질문"), clear("내답변"),
        clear("단어들"), clear("원단어들"),
        CLEARLOG(),
        CAST("화면 그리기"),
        STATUS("● 연결 중…"),
        setv("아이디", username()),
        setv("닉네임", nickname()),
        setv("기록블롭", ""), setv("기억블롭", ""), setv("기록위치", 0), setv("기억위치", 0),
        setv("대기질문", ""), setv("최근주제", ""), setv("지난기분", ""), setv("직전기분", ""), setv("기억변경", 0),
        setv("지난답변", ""), setv("주제", ""), setv("단어", ""), setv("키표시", ""), setv("값", ""), setv("감정점수", 0),
        IFELSE(eq(slen(repl(V("아이디"), " ", "")), 0),
               [setv("로그인", 0), setv("저장가능", 0), setv("호칭", "방문자"), setv("템플릿", pick("말-환영손님"))],
               [setv("로그인", 1), setv("저장가능", 1),
                setv("호칭", V("닉네임")),
                IF(eq(slen(repl(V("호칭"), " ", "")), 0), setv("호칭", V("아이디"))),
                setv("접두어", join(V("아이디"), "|")),
                STATUS("● 기억을 불러오는 중…"),
                LOAD(),
                ELIF_CHAIN(
                    (AND(empty(V("기록블롭")), eq(llen("내질문"), 0)), [setv("템플릿", pick("말-환영처음"))]),
                    (gt(slen(V("최근주제")), 0), [setv("주제", V("최근주제")), setv("템플릿", pick("말-환영주제"))]),
                    (eq(V("지난기분"), "나쁨"), [setv("템플릿", pick("말-환영기분"))]),
                    otherwise=[setv("템플릿", pick("말-환영"))]),
                IF(eq(V("저장가능"), 0), PRINT("저장 서버에 연결하지 못해서 이번 대화는 저장되지 않아요.", "알림"))]),
        setv("이번대기", ""),
        setv("답변", FILL(V("템플릿"))),
        setv("대기질문", V("이번대기")),
        PRINT(V("답변"), "봇"),
        STATUS(join("● ", V("호칭"), "님과 대화 중")),
        setv("대화중", 1),
        UNTIL(eq(V("대화중"), 0),
              CAST("말풍선 지우기"),
              ASK("메시지를 입력하세요"),
              # 저장 형식과 템플릿 기호를 깨뜨리는 글자는 바꿔 둔다
              setv("메시지", TRIM(clean_input)),
              IF(gt(slen(V("메시지")), 0),
                 PRINT(V("메시지"), "나"),
                 STATUS("● 생각하는 중…"),
                 append("화면글", "엔봇이 생각하는 중…"), append("화면종류", "생각"),
                 IF(gt(llen("화면글"), ROWS), remove("화면글", 1), remove("화면종류", 1)),
                 CAST("화면 그리기"),
                 REPLY(),
                 # ('새 대화' 는 화면을 비우므로 줄이 남아 있을 때만 '생각 중' 줄을 지운다)
                 IF(gt(llen("화면종류"), 0), IF(eq(item("화면종류", llen("화면종류")), "생각"),
                    remove("화면글", llen("화면글")), remove("화면종류", llen("화면종류")))),
                 # 개인정보가 담긴 말은 서버 기록과 기록표에 남기지 않는다
                 IFELSE(eq(V("기록가림"), 1), [LOG("나", "🔒 (개인정보라서 기록하지 않았어요)")], [LOG("나", V("메시지"))]),
                 PRINT(V("답변"), "봇"),
                 LOG("봇", V("답변")),
                 SAVELOG(),
                 IF(eq(V("기억변경"), 1), SAVEMEM(), setv("기억변경", 0)),
                 STATUS(join("● ", V("호칭"), "님과 대화 중")))),
        STATUS("● 대화 종료"),
    )


# ================================================================ 프로젝트 조립
def est_height(b):
    h = 32
    for st in b["statements"]:
        h += 24 + sum(est_height(x) for x in st)
    return h


def place(threads):
    y = 50
    for t in threads:
        t[0]["x"], t[0]["y"] = 40, y
        y += 40 + sum(est_height(b) for b in t) + 120
    return threads


def variable(name, value=""):
    return {"name": name, "id": VARS[name], "visible": False, "value": value, "variableType": "variable",
            "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 0, "y": 0}


def lst(name, data=(), realtime=False):
    return {"name": name, "id": LISTS[name], "visible": False, "value": 0, "variableType": "list",
            "isCloud": False, "isRealTime": realtime, "cloudDate": False, "object": None,
            "x": 0, "y": 0, "width": 100, "height": 120, "array": [{"data": d} for d in data]}


def table(name, fields, rows):
    """엔트리가 작품을 저장할 때 쓰는 모양 그대로 만든다 (DataTableSource.toJSON):
    data 는 {key, value} 줄, origin 은 정지했을 때 되돌아갈 원본 줄."""
    rows = [list(r) for r in rows]
    return {
        "id": TABLES[name], "name": name, "fields": list(fields),
        "data": [{"key": f"{TABLES[name]}r{i}", "value": r} for i, r in enumerate(rows, 1)],
        "origin": rows, "chart": [], "object": None, "isCloud": False, "cloudDate": None,
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
    }



def text_box(name, text, x, y, size, colour, bg="transparent", align=0, bold=False, font=FONT, script=(),
             width=100, height=None, line_break=False, visible=True, scene_id=None):
    height = height or size + 6
    return {
        "id": gen_id(), "name": name, "text": text, "objectType": "textBox", "rotateMethod": "free",
        "scene": scene_id, "lock": True, "script": json.dumps(place(list(script)), ensure_ascii=False),
        "sprite": {"pictures": [], "sounds": []},
        "entity": {
            "x": x, "y": y, "regX": 0, "regY": 0, "scaleX": 1, "scaleY": 1, "rotation": 0, "direction": 90,
            "width": width, "height": height, "font": f"{'bold ' if bold else ''}{size}px {font}", "visible": visible,
            "colour": colour, "text": text, "textAlign": align, "lineBreak": line_break, "bgColor": bg,
            "underLine": False, "strike": False, "fontSize": size,
        },
    }


def build():
    scene_id = gen_id()
    bot_rows, me_rows, status_script = ui_scripts()
    engine_scripts = [main_script(), WHEN_MSG("말풍선 지우기", UNSAY())]
    objects = [
        text_box("상태", "● 연결 중…", 228, 121, 11, "#A7F3D0", align=2, script=status_script, scene_id=scene_id),
        text_box("제목", "🤖 엔봇", LEFT_X, 121, 16, "#FFFFFF", align=1, font="yg-jalnan", scene_id=scene_id),
        text_box("부제", "기억하는 AI 친구", -160, 120, 11, "#C7D2FE", align=1, scene_id=scene_id),
        text_box("헤더", " ", 0, 121, 12, "#FFFFFF", bg=HEADER_BG, width=480, height=28, line_break=True,
                 scene_id=scene_id),
    ]
    for k in range(1, ROWS + 1):
        y = ROW_TOP - (k - 1) * ROW_STEP
        objects.append(text_box(f"나칸{k}", " ", RIGHT_X, y, 12, ME_FG, bg=ME_BG, align=2, height=ROW_H,
                                script=me_rows[k], visible=False, scene_id=scene_id))
        objects.append(text_box(f"봇칸{k}", " ", LEFT_X, y, 12, BOT_FG, bg=BOT_BG, align=1, height=ROW_H,
                                script=bot_rows[k], visible=False, scene_id=scene_id))
    objects += [
        text_box("엔봇", "메시지를 입력하고 Enter ⏎   ·   '도움말' 로 사용법 보기", 0, -60, 10, NOTICE_FG,
                 script=engine_scripts, scene_id=scene_id),
        text_box("대화배경", " ", 0, 28.5, 12, CHAT_BG, bg=CHAT_BG, width=480, height=157, line_break=True,
                 scene_id=scene_id),
    ]

    tables = [
        table(T_TOPIC, *KNOW[T_TOPIC]),
        table(T_DEF, *KNOW[T_DEF]),
        table(T_TALK, *KNOW[T_TALK]),
        table(T_FEEL, KNOW[T_FEEL][0], [(w_, int(s)) for w_, s in KNOW[T_FEEL][1]]),
        table(T_ASK, *KNOW[T_ASK]),
        # 대화기록표는 실행하면 맨 먼저 비우지만, 빈 표(데이터 0줄)는 엔트리 화면에서 만들 수 없는 모양이라
        # 안내 줄 하나를 넣어 둔다. (정지하면 테이블은 이 상태로 돌아간다)
        table(T_LOG, LOG_FIELDS, [[int(r[0])] + r[1:] for r in KNOW[T_LOG][1]]),
    ]
    unknown = set(TABLES) - {t["name"] for t in tables}
    assert not unknown, f"만들지 않은 테이블을 블록에서 씀: {unknown}"
    lists = [
        lst("화면글"), lst("화면종류"), lst("단어들"), lst("원단어들"), lst("후보답변"), lst("내질문"), lst("내답변"),
        lst("통계주제"),
        lst("불용어", D.STOPWORDS), lst("조사목록", D.JOSA_SUFFIXES), lst("형용사", D.ADJ_STEMS), lst("요일", D.WEEKDAYS),
        lst("예말", D.YES_WORDS), lst("모름말", D.NON_ANSWERS), lst("뒤집는말", D.NEGATORS),
        lst("주제뒤말", D.HA_TAILS), lst("끝말목록", _TAILS),
        *[lst(name, phrases) for name, phrases in D.PHRASES.items()],
        lst("대화기록", realtime=True), lst("기억저장소", realtime=True),
    ]
    unknown = set(LISTS) - {l["name"] for l in lists}
    assert not unknown, f"만들지 않은 리스트를 블록에서 씀: {unknown}"
    functions = [f.to_json() for f in FUNCS]
    variables = [
        {"name": "초시계", "id": gen_id(), "visible": False, "value": "0", "variableType": "timer",
         "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 134, "y": -70},
        {"name": "대답", "id": gen_id(), "visible": False, "value": "0", "variableType": "answer",
         "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 150, "y": -100},
        *[variable(n) for n in VARS],
        *lists,
    ]
    return {
        "name": "엔트리 AI 챗봇 엔봇",
        "objects": objects,
        "scenes": [{"name": "장면 1", "id": scene_id}],
        "variables": variables,
        "messages": [{"id": mid, "name": n} for n, mid in MSGS.items()],
        "functions": functions,
        "tables": tables,
        "speed": 60,
        "expansionBlocks": [],
        "aiUtilizeBlocks": ["translate"],
        "hardwareLiteBlocks": [],
        "externalModules": [],
        "externalModulesLite": [],
    }


def check_project(project):
    """같은 블록 객체를 두 곳에 넣으면 id 가 겹친다. 엔트리는 블록 id 로 값을 캐시하므로 막아 둔다."""
    seen = set()
    for _o, b in walk_blocks(project):
        assert b["id"] not in seen, f"블록 id 중복: {b['id']} ({b['type']})"
        seen.add(b["id"])
    handled = {t[0]["params"][1] for o in project["objects"] for t in json.loads(o["script"])
               if t[0]["type"] == "when_message_cast"}
    missing = [n for n, mid in MSGS.items() if mid not in handled]
    assert not missing, f"받는 스크립트가 없는 신호: {missing}"
    return len(seen)


def write_ent(project, path):
    data = json.dumps(project, ensure_ascii=False).encode("utf-8")
    mtime = int(time.time())
    with tarfile.open(path, "w:gz", format=tarfile.USTAR_FORMAT) as tar:
        d = tarfile.TarInfo("temp")
        d.type, d.mode, d.mtime = tarfile.DIRTYPE, 0o755, mtime
        tar.addfile(d)
        f = tarfile.TarInfo("temp/project.json")
        f.size, f.mode, f.mtime = len(data), 0o644, mtime
        tar.addfile(f, io.BytesIO(data))


if __name__ == "__main__":
    project = build()
    n_blocks = check_project(project)
    with open(OUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(project, fp, ensure_ascii=False, indent=1)
    write_ent(project, OUT_ENT)
    print(f"wrote {OUT_ENT} and {OUT_JSON} ({n_blocks} blocks, {len(project['objects'])} objects, "
          f"{len(project['functions'])} functions, {len(project['tables'])} tables)")
