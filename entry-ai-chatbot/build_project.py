#!/usr/bin/env python3
"""엔트리(playentry.org)용 'AI 챗봇 엔봇' 작품 파일(.ent)을 만든다.

.ent 파일은 temp/project.json 하나를 담은 tar.gz 압축 파일이다
(entrylabs/entry-offline 의 MainUtils.saveProject 와 같은 구조).

구성
- 함수: 엔봇의 생각은 모두 엔트리 '함수'로 만든다. 값을 돌려주는 함수(조사 붙이기, 앞뒤 공백 지우기 …)는
  반복 없이 한 번에 끝나서 대답이 빨라지고, 같은 블록 묶음을 여러 번 쓰지 않아도 된다.
- 지식(주제, 단어 뜻, 일상 대화, 감정어, 먼저 물을 질문)은 knowledge/*.csv 를 정렬된 리스트로 넣고
  '지식 찾기' 함수가 이진 탐색으로 한 번에 찾는다. (엔트리 웹에서 .ent 를 불러오면 테이블은 빠지고
  리스트는 그대로 들어오기 때문에, 대화에 꼭 필요한 데이터는 리스트에 둔다.)
- 대화 기록은 리스트 '기록-…' 에 날짜·시각·누가·주제·감정·내용으로 쌓고, 검색·통계도 여기서 한다.
  '기록표 켜기' 를 하면 엔트리 테이블 '대화기록표' 에도 똑같이 맞춰 두고 표로 보여 준다.
- 사용자별 저장: 실시간 리스트(대화기록, 기억저장소)에 저장하고, 시작할 때 기록 리스트로 다시 펼친다.

엔봇이 대답을 만드는 순서 (함수 '답변 만들기')
  문장 분석 → 명령 → 직전에 물어본 것의 대답 → 이야기 속 사실 → 기억 → 단어 뜻·일상 대화·모르는 것 배우기
  → 감정(공감) → 주제 → 되받기 → 모르는 질문 배우기 → 엔봇이 먼저 묻기

사용법:  python3 build_project.py   →  entry-ai-chatbot.ent, project.json 생성
"""
import csv
import io
import json
import math
import os
import re
import tarfile
import time

import data as D
from dsl import (AND, ASK, BG, BREAK, CAST, ELIF_CHAIN, FG, FUNCS, HIDE, HIDE_ANSWER, IF, IFELSE, LISTS, MSGS,
                 NOT, OR, REPEAT, SCAN, SHOW, TABLES, TAPPEND, TDELETE, TOPEN, TSET, UNSAY, UNTIL, V, VARS, WAIT,
                 WHEN_MSG, WHEN_START, WRITE, Func, answer, append, calc, charat, chg, clear, contains, count, date,
                 empty, eq, find, gen_id, gt, included, item, join, llen, lower, lt, minus, mod, nickname, quot,
                 pick, plus, rand, remove, repl, reverse, setitem, setv, slen, starts, sub, tcount,
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
MAX_RECORDS = 200       # 기록 리스트(와 대화기록표)에 남기는 줄 수
MAX_DIARY = 20          # 사용자마다 기억하는 '지난 이야기' (주제별 날짜·감정·한 말) 수
DIARY_SUMMARY = 30      # 지난 이야기로 남기는 한 말의 최대 길이

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


# knowledge/<이름>.csv — 엔봇의 지식. 빌드할 때 리스트로 들어간다.
# (엔트리 웹에서 .ent 를 불러오면 테이블은 빠지고 리스트는 그대로 들어오므로, 대화에 꼭 필요한 지식은 리스트에 둔다)
T_TOPIC, T_DEF, T_TALK, T_FEEL, T_ASK, T_LOG = "표-주제", "표-단어뜻", "표-일상대화", "표-감정어", "표-먼저묻기", "대화기록표"
KNOW = {name: read_csv(name) for name in [T_TOPIC, T_DEF, T_TALK, T_FEEL, T_ASK, T_LOG]}
TABLE_ROWS = {name: rows for name, (_fields, rows) in KNOW.items()}
assert KNOW[T_LOG][0] == LOG_FIELDS
KIND = {T_TOPIC: "주", T_DEF: "뜻", T_TALK: "말", T_FEEL: "감"}  # 리스트 '지식키' 의 앞머리

# knowledge/표-신조어.csv — 신조어·초성체 ('야르', 'ㅎㅇ', '킹받다' …). 한 줄을 세 가지 지식으로 나눠 넣는다:
#   뜻 ('킹받다가 뭐야?') · 일상 대화 (말 속에 '킹받' 이 있으면 그 대답) · 감정어 ('킹받았어' → 점수)
T_SLANG = "표-신조어"
SLANG = read_csv(T_SLANG)[1]
SLANG_FORMS = []  # 신조어 꼴 (엔봇이 물어본 것의 대답으로 기억하지 않는다)
_defined = {r[0] for r in KNOW[T_DEF][1]}
for _word, _piece, _meaning, _answers, _score in SLANG:
    _forms = list(dict.fromkeys([_word.lower(), _piece.lower()]))
    SLANG_FORMS += _forms
    KNOW[T_DEF][1].extend([f, _meaning, "신조어"] for f in _forms if f not in _defined)  # 단어뜻에 이미 있으면 그쪽 뜻
    if _answers.strip():
        KNOW[T_TALK][1].append([_piece.lower(), _answers])
    if _score.strip():
        KNOW[T_FEEL][1].append([_piece.lower(), _score])


def dueum_pairs():
    """두음법칙: 끝말잇기에서 '력'으로 끝나면 '역'으로도 이을 수 있다. (ㄹ→ㅇ/ㄴ, ㄴ→ㅇ)"""
    pairs = []
    for jung in range(21):
        for jong in range(28):
            syl = lambda cho: chr(0xAC00 + (cho * 21 + jung) * 28 + jong)
            if jung in (2, 6, 7, 12, 17, 20):   # ㅑ ㅕ ㅖ ㅛ ㅠ ㅣ
                pairs.append((syl(5), syl(11)))  # ㄹ → ㅇ (력 → 역)
                if jung != 2:
                    pairs.append((syl(2), syl(11)))  # ㄴ → ㅇ (녀 → 여)
            else:
                pairs.append((syl(5), syl(2)))   # ㄹ → ㄴ (락 → 낙)
    return pairs


def knowledge_lists():
    """'주|학교' 같은 키를 자바스크립트 글자 순서(UTF-16)로 정렬한 지식키 / 지식값 리스트.
    '두|력' → '역' 처럼 두음법칙도 함께 넣는다."""
    items = [(f"{kind}|{r[0]}", r[1]) for table, kind in KIND.items() for r in KNOW[table][1]]
    items += [(f"두|{a}", b) for a, b in dueum_pairs()]
    items.sort(key=lambda kv: kv[0].encode("utf-16-be"))
    keys = [k for k, _ in items]
    assert len(keys) == len(set(keys)), "지식 키가 겹침"
    return keys, [v for _, v in items]


KNOW_KEYS, KNOW_VALUES = knowledge_lists()
SEARCH_STEPS = math.ceil(math.log2(len(KNOW_KEYS))) + 1  # 이진 탐색 단계 수


def banmal_static(text):
    """'반말로 바꾸기' 함수가 하는 일을 빌드할 때 그대로 해 본다 (호칭 규칙은 빼고)."""
    for a, b in D.BANMAL_RULES:
        text = text.replace(a, b)
    return text


def chain_words():
    """끝말잇기 낱말: 흔한 명사 + 주제·단어 뜻의 한글 낱말 (2~6글자), 자바스크립트 글자 순서로 정렬."""
    words = set(w for w in D.WORDCHAIN_NOUNS if len(w) >= 2)
    words |= {r[0] for t in (T_TOPIC, T_DEF) for r in KNOW[t][1]
              # ('킹받' 같은 신조어 조각과 '강감찬' 같은 사람 이름은 빼고)
              if re.fullmatch(r"[가-힣]{2,6}", r[0]) and r[-1] not in ("신조어", "인물", "역사")}
    # 반말로 바꿀 때 망가지는 낱말은 빼 둔다 ('담요!' → '담!')
    words = {w for w in words if banmal_static(f" {w}! ") == f" {w}! " and banmal_static(f" {w}. ") == f" {w}. "}
    words = sorted(words, key=lambda w: w.encode("utf-16-be"))
    dueum = dict(dueum_pairs())
    firsts = {w[0] for w in words}
    # 엔봇이 처음 꺼낼 낱말은 이어 말할 수 있는 것 (끝 글자로 시작하는 낱말이 있는 것)만
    starters = [w for w in words if w[-1] in firsts or dueum.get(w[-1]) in firsts]
    return words, starters


CHAIN_WORDS, CHAIN_STARTERS = chain_words()
CHAIN_STEPS = math.ceil(math.log2(len(CHAIN_WORDS) + 1)) + 1


def josa_static(word, kinds):
    """빌드할 때 이미 아는 낱말에 붙일 조사 (받침 있으면 kinds[0])."""
    last = word[-1]
    has_batchim = "가" <= last <= "힣" and (ord(last) - 0xAC00) % 28 != 0
    return word + (kinds[0] if has_batchim else kinds[1])

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
LOGROW = Func("기록 줄 넣기", ["날짜", "시각", "누가", "주제", "감정", "내용"])
PARSELINE = Func("기록 줄 풀기", ["줄"])
SAVELOG = Func("기록 저장")
SAVEMEM = Func("기억 저장")
SLOT_LOG = Func("내 기록 칸 찾기")
SLOT_MEM = Func("내 기억 칸 찾기")
LOAD = Func("데이터 불러오기", counters=["줄번호"])
SEARCH = Func("기록 검색", ["낱말"], counters=["찾은수"])
STATS = Func("기록 통계", counters=["내말", "봇말", "좋음", "나쁨", "보통", "오늘"])
CLEARLOG = Func("기록 비우기")
DIARY_FIND = Func("지난 이야기 찾기", ["주제"])
DIARY_GET = Func("지난 이야기 꺼내기", ["번호"])
DIARY_PUT = Func("지난 이야기 적기", ["주제", "점수", "요약"])

# ================================================================ 지식 찾기 · 대화기록표
KNOWLEDGE = Func("지식 찾기", ["종류", "낱말"], value=True)
RECVAL = Func("기록 칸 값", ["줄", "칸"], value=True)
TABLE_SYNC = Func("기록표 맞추기")
TABLE_OPEN = Func("기록표 열기")
# 정렬된 '지식키' 리스트에서 '종류|낱말' 을 이진 탐색으로 찾는다 (반복 블록 없이 펼쳐서 한 번에 계산된다)
KNOWLEDGE.define(
    setv("찾을키", join(KNOWLEDGE.p("종류"), "|", KNOWLEDGE.p("낱말"))),
    setv("아래", 1), setv("위", llen("지식키")),
    *[IF(lt(V("아래"), V("위")),
         setv("가운데", quot(plus(V("아래"), V("위")), 2)),
         IFELSE(lt(item("지식키", V("가운데")), V("찾을키")),
                [setv("아래", plus(V("가운데"), 1))], [setv("위", V("가운데"))]))
      for _ in range(SEARCH_STEPS)],
    setv("찾은지식", ""),
    IF(eq(item("지식키", V("아래")), V("찾을키")), setv("찾은지식", item("지식값", V("아래")))),
    ret=V("찾은지식"))

# 대화 기록은 리스트 '기록-…' 에 쌓는다. 칸 순서는 대화기록표와 같다 (1 번호, 2 날짜, … 7 내용)
REC = {C_NO: "기록-번호", C_DATE: "기록-날짜", C_TIME: "기록-시각", C_WHO: "기록-누가", C_TOPIC: "기록-주제", C_FEEL: "기록-감정",
       C_TEXT: "기록-내용"}
rec = lambda col, row: item(REC[col], row)
RECVAL.define(
    ELIF_CHAIN(*[(eq(RECVAL.p("칸"), col), [setv("기록칸값", rec(col, RECVAL.p("줄")))]) for col in REC if col != C_NO],
               otherwise=[setv("기록칸값", rec(C_NO, RECVAL.p("줄")))]),
    ret=V("기록칸값"))
# 테이블 블록은 아래 두 함수 안에만 있다 (모두 5개).
# 엔트리 웹에서 .ent 를 불러오면 테이블이 빠지므로, 기록표는 '기록표 켜기' 를 한 뒤에만 쓴다.
TABLE_SYNC.define(
    # 새로 채워야 하면(처음, 새 대화) 표를 모두 비우고, 기록 리스트에서 지운 오래된 줄은 표에서도 지운다
    IF(eq(V("표다시"), 1),
       setv("표지울줄", minus(tcount(T_LOG), 1)), setv("표에넣은", 0), setv("표다시", 0)),
    REPEAT(V("표지울줄"), TDELETE(T_LOG, 2)),
    setv("표지울줄", 0),
    # 아직 표에 없는 기록만 한 줄씩 더한다
    UNTIL(NOT(lt(V("표에넣은"), llen(REC[C_TEXT]))),
          chg("표에넣은", 1),
          TAPPEND(T_LOG),
          setv("표칸", 1),
          REPEAT(len(LOG_FIELDS),
                 TSET(T_LOG, plus(V("표에넣은"), 1), V("표칸"), RECVAL(V("표에넣은"), V("표칸"))),
                 chg("표칸", 1))),
)
TABLE_OPEN.define(TOPEN(T_LOG))


def lookup(table, value):
    """지식에서 value 의 값 (없으면 빈 글)."""
    return KNOWLEDGE(KIND[table], value)


def has(table, value):
    return NOT(empty(lookup(table, value)))


def lookup_kind(kind, value):
    return KNOWLEDGE(kind, value)


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
    # 뒤에 붙은 조사를 뗀다. 아는 주제 낱말(고양이 등)과 뜻을 아는 낱말(원숭이, 울릉도 등)은 그대로 둔다.
    setv("어간", STEM.p("낱말")),
    setv("떼기길이", slen(STEM.p("낱말"))),
    IF(NOT(OR(has(T_TOPIC, STEM.p("낱말")), has(T_DEF, lower(STEM.p("낱말"))))),
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
             IF(OR(gt(V("떼기길이"), 2), has(T_TOPIC, TAIL(STEM.p("낱말"), 1)), has(T_DEF, TAIL(STEM.p("낱말"), 1))),
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
       setv("주제질문", lookup(T_TOPIC, TOPICQ.p("주제")))),
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
              setv("감정값", lookup(T_FEEL, V("감정후보"))),
              IF(NOT(empty(V("감정값"))), setv("낱말점수", V("감정값")))))


def FIND_PIECE(table, text, found, found_len, k, max_pos=30):
    """글 text 의 조각(긴 것부터)을 지식에서 찾아, 가장 긴 것을 found 에 넣는다.
    지식을 처음부터 끝까지 훑지 않으므로 데이터가 늘어나도 빠르기가 그대로다 (글자 수만큼만 돈다)."""
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
    # 못 찾았고 '개웃겨', '핵좋아', '왕짜증' 처럼 힘주는 말이 앞에 붙었으면 떼고 한 번 더
    IF(AND(eq(V("낱말점수"), 0), gt(slen(V("감정낱말")), 2), gt(find(D.INTENSIFIERS, charat(V("감정낱말"), 1)), 0)),
       setv("감정낱말", HEAD(V("감정낱말"), 1)),
       _feel_lookup(None), _feel_lookup(4), _feel_lookup(3), _feel_lookup(2)),
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
    # 'ㅇㅇ', 'ㅋㅋ', '어쩔티비' 처럼 자음·모음으로 시작하거나 신조어 한 낱말인 말
    setv("신조어말", 0),
    IF(gt(slen(_m()), 0),
       IF(OR(gt(find(D.JAMO, charat(_m(), 1)), 0), included("신조어목록", lower(repl(V("문장"), " ", "")))),
          setv("신조어말", 1))),
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
                # '잘 봤어', '잘 풀렸어' 처럼 '잘' 과 띄어 쓴 말도 붙여서 찾아본다 (감정어 테이블의 '잘봤')
                IF(AND(eq(V("이전낱말"), "잘"), eq(V("낱말점수"), 0)),
                   setv("낱말점수", FEEL(lower(join("잘", V("단어원형")))))),
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
    # 아직 모르는 것 하나를 골라 템플릿 뒤에 질문으로 붙인다 (먼저 묻기 리스트에서 몇 번 골라 본다).
    setv("시작찾음", 0),
    *[IF(eq(V("시작찾음"), 0),
         setv("시작번호", rand(1, llen("먼저-키"))),
         IF(NOT(included("내질문", item("먼저-키", V("시작번호")))),
            setv("템플릿", join(V("템플릿"), " ", item("먼저-질문", V("시작번호")))),
            setv("이번대기", join("사실:", item("먼저-키", V("시작번호")))),
            setv("시작찾음", 1))) for _ in range(5)],
    IF(eq(V("시작찾음"), 0), setv("템플릿", join(V("템플릿"), " ", pick("말-이야기거리")))),
)

# ================================================================ 대답
HELP = SEP.join([
    "편하게 이야기해 보세요! 저는 이렇게 생각해요.",
    "· 문장에서 주제와 감정을 찾아 공감하고 되물어요",
    "· '내 생일은 3월 14일이야', '나 축구 좋아해' 같은 말을 기억해요",
    "· 모르는 건 물어보고, 알려 주면 배워요",
    "· '장영실'처럼 낱말만 말해도 뜻을 알려 줘요 (1,700여 개)",
    "명령어: 기억 목록 · 나에 대해 알아? · 잊어줘: 내 생일",
    "기록표 · 기록 검색: 고양이 · 기록 통계",
    "놀이: 끝말잇기 · 가위바위보 · 주사위 · 수수께끼 · 퀴즈",
    "3 더하기 5는? · 크리스마스까지 며칠? · 내일 무슨 요일?",
    "짜장면이랑 짬뽕 중에 뭐 먹을까? · 반말 써 / 존댓말 써",
    "지난번에 무슨 얘기 했지? · 야르 · ㅎㅇ · 킹받다가 뭐야?",
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
    # 비밀번호·전화번호 같은 개인정보는 기억하지 않는다
    BRANCH(AND(not_q(), sensitive(m())), setv("템플릿", pick("말-개인정보")), setv("기록가림", 1)),
    # 말투 바꾸기 ("반말 써", "존댓말 써")
    # ('반모가 뭐야?' 처럼 뜻을 묻는 말은 빼고)
    BRANCH(AND(OR(*[contains(m(), w_) for w_ in D.BANMAL_OFF]), NOT(AND(is_q(), eq(V("뜻질문"), 1)))),
           IFELSE(eq(V("말투"), "존댓말"), [setv("템플릿", "지금도 존댓말로 말하고 있어요! 😊")],
                  [setv("말투", "존댓말"), setv("말투변경", 1), setv("템플릿", pick("말-반말끄기"))])),
    BRANCH(AND(OR(*[contains(m(), w_) for w_ in D.BANMAL_ON]), NOT(AND(is_q(), eq(V("뜻질문"), 1)))),
           IFELSE(eq(V("말투"), "반말"), [setv("템플릿", "벌써 편하게 말하고 있어요! 😄")],
                  [setv("말투", "반말"), setv("말투변경", 1), setv("템플릿", pick("말-반말켜기"))])),
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
    BRANCH(cmd("기록검색", "검색", "기록찾기"), setv("말투제외", 1), SEARCH(V("내용"))),
    BRANCH(OR(eq(m(), "기록통계"), eq(m(), "대화통계"), eq(m(), "통계"), eq(m(), "오늘대화")), STATS()),
    BRANCH(OR(eq(m(), "기록표켜기"), eq(m(), "기록표연결"), eq(m(), "기록표켜줘")),
           setv("기록표연결", 1), setv("표다시", 1),
           setv("답변", "기록표를 켰어요. 이제 대화가 엔트리 테이블 '대화기록표'에도 한 줄씩 쌓여요. "
                      "(데이터 분석 꾸러미에 대화기록표가 연결돼 있어야 해요.)")),
    BRANCH(eq(m(), "기록표끄기"),
           setv("기록표연결", 0),
           setv("답변", "기록표를 껐어요. 대화 기록은 그대로 남아 있어서 검색과 통계는 계속 할 수 있어요.")),
    BRANCH(OR(eq(m(), "기록표"), eq(m(), "기록보기"), eq(m(), "대화기록"), eq(m(), "기록표보기")),
           IFELSE(eq(V("기록표연결"), 1),
                  [TABLE_SYNC(), TABLE_OPEN(),
                   setv("답변", join("대화 기록표를 열었어요. 모두 ", llen(REC[C_TEXT]),
                                     "줄이에요. 날짜·시각·누가·주제·감정·내용이 정리돼 있어요. 창을 닫으면 이어서 이야기해요."))],
                  [IFELSE(eq(llen(REC[C_TEXT]), 0),
                          [setv("답변", "아직 대화 기록이 없어요.")],
                          [setv("말투제외", 1),
                           setv("답변", join("최근 대화 기록이에요. (모두 ", llen(REC[C_TEXT]), "줄)")),
                           setv("보기k", minus(llen(REC[C_TEXT]), 7)), IF(lt(V("보기k"), 1), setv("보기k", 1)),
                           UNTIL(gt(V("보기k"), llen(REC[C_TEXT])),
                                 setv("답변", join(V("답변"), SEP, "· ", HEAD(rec(C_DATE, V("보기k")), 5), " ",
                                                   rec(C_TIME, V("보기k")), " ", rec(C_WHO, V("보기k")), ": ",
                                                   rec(C_TEXT, V("보기k")))),
                                 chg("보기k", 1)),
                           setv("답변", join(V("답변"), SEP, "엔트리 표로 보려면 '기록표 켜기'라고 말해 주세요."))])])),
    BRANCH(OR(eq(m(), "기억목록"), eq(m(), "기억보기")),
           setv("답변", ""), setv("요약수", 0), setv("말투제외", 1),
           *SCAN("내질문", lambda: [IF(NOT(starts(item("내질문", V("답k")), "#")),
                                      setv("값", item("내답변", V("답k"))), IF(starts(V("값"), "F:"), setv("값", HEAD(V("값"), 2))),
                                      setv("답변", join(V("답변"), SEP, "· ", item("내질문", V("답k")), " → ", V("값"))),
                                      chg("요약수", 1))], 3, k="답k"),
           IF(gt(llen("이야기주제"), 0),
              setv("지난주제들", ""),
              *SCAN("이야기주제", lambda: [setv("지난주제들", join(V("지난주제들"), ", ", item("이야기주제", V("답k"))))],
                    4, k="답k"),
              setv("답변", join(V("답변"), SEP, "· 지난 이야기: ", HEAD(V("지난주제들"), 2))), chg("요약수", 1)),
           IFELSE(eq(V("요약수"), 0),
                  [setv("답변", "아직 기억하고 있는 게 없어요. 이야기를 들려주면 하나씩 기억할게요!")],
                  [setv("답변", join("기억하고 있는 것 ", V("요약수"), "개예요.", V("답변")))])),
    BRANCH(OR(eq(m(), "새대화"), eq(m(), "초기화"), eq(m(), "기록삭제")),
           setv("기록블롭", ""), clear("화면글"), clear("화면종류"), CLEARLOG(),
           setv("답변", "대화 기록을 지웠어요. 새로 시작해요! (기억하고 있는 건 그대로예요.)")),
    BRANCH(OR(eq(m(), "종료"), eq(m(), "bye"),
              AND(OR(eq(m(), "그만"), eq(m(), "끝")),
                  NOT(OR(eq(V("지난대기"), "끝말잇기"), eq(V("지난대기"), "가위바위보"))))),
           setv("대화중", 0),
           setv("템플릿", "오늘 이야기 즐거웠어요, {이름}님! 다시 이야기하려면 시작 버튼을 눌러 주세요.")),
)

R_PENDING.define(
    # 직전에 내가 물어본 것에 대한 대답이면 기억한다
    BRANCH(AND(starts(V("지난대기"), "사실:"), not_q(), empty(V("명령")), lt(slen(V("문장")), 26),
               lt(llen("원단어들"), 5), NOT(eq(V("서술종류"), "동사")),
               NOT(OR(*[contains(m(), w_) for w_ in D.SOCIAL])), eq(V("신조어말"), 0)),
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
    BRANCH(eq(V("기억응답"), 2), setv("말투제외", 1), setv("답변", item("내답변", V("찾은번호")))),
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
_tok_i = lambda i: item("원단어들", i)
_STRONG_DEF_CUES = ["뭐야", "뭐예요", "뭐에요", "뭐지", "뭐냐", "뭔데", "뭔가요", "뭘까", "뭔지", "무엇", "이란", "란뭐", "에대해",
                    "누구야", "누구예요", "누구에요", "누구지", "누군지", "누구냐", "설명", "뜻"]
R_TALK.define(IF(undone(),
    # 뜻을 아는 낱말 찾기: 질문의 대상 낱말 → 앞의 세 낱말 (조사를 뗀 것, 그대로인 것)
    setv("뜻낱말", ""),
    IF(gt(slen(V("단어")), 0), IF(has(T_DEF, lower(V("단어"))), setv("뜻낱말", lower(V("단어"))))),
    *[IF(AND(empty(V("뜻낱말")), NOT(lt(llen("원단어들"), i))),
         setv("뜻후보", lower(STEM(_tok_i(i)))),
         IF(has(T_DEF, V("뜻후보")), setv("뜻낱말", V("뜻후보"))),
         IF(empty(V("뜻낱말")), IF(has(T_DEF, lower(_tok_i(i))), setv("뜻낱말", lower(_tok_i(i))))))
      for i in (1, 2, 3)],
    # 단어 뜻 ("블랙홀이 뭐야?") — '내 친구 알아?' 처럼 내 것을 묻는 말과 긴 문장은 빼고
    #   ('뭐야·누구야·에 대해' 같은 분명한 말이 있으면 낱말 둘까지, '알아?' 만 있으면 낱말 하나일 때만)
    BRANCH(AND(is_q(), eq(V("뜻질문"), 1), gt(slen(V("뜻낱말")), 0),
               OR(lt(V("내용어수"), 2), AND(lt(V("내용어수"), 3), OR(*[contains(m(), c) for c in _STRONG_DEF_CUES]))),
               NOT(contains(m(), "는지")),
               NOT(OR(starts(m(), "내"), starts(m(), "우리"), starts(m(), "제"), starts(m(), "나의")))),
           setv("단어", V("뜻낱말")),
           setv("템플릿", join("{단어은} ", lookup(T_DEF, V("뜻낱말"))))),
    # 낱말 하나만 말해도 ('장영실', '블랙홀!') 뜻을 알려 준다. 주제 낱말이면 이어서 묻는다.
    # (일상 대화 키워드와 똑같은 말 '수수께끼', 신조어 'ㅇㅇ', 기억해 둔 이름 '나비' 는 빼고)
    # 엔봇이 방금 물어본 것의 대답이면 뜻 대신 대답으로 받는다:
    #   '왜?' 에는 어떤 낱말이든, '어떤 과목이었어요?' 에는 '수학' 같은 주제 낱말, '기분 어때요?' 에는 '행복' 같은 감정 낱말
    BRANCH(AND(eq(llen("원단어들"), 1), gt(slen(V("뜻낱말")), 0),
               NOT(has(T_TALK, V("뜻낱말"))), empty(V("아는이름")), eq(V("신조어말"), 0),
               NOT(eq(V("지난대기"), "이유")),
               NOT(AND(eq(V("지난대기"), "이야기"), has(T_TOPIC, V("뜻낱말")))),
               NOT(AND(eq(V("지난대기"), "기분"), NOT(eq(V("감정점수"), 0))))),
           setv("단어", V("뜻낱말")),
           setv("템플릿", join("{단어은} ", lookup(T_DEF, V("뜻낱말")))),
           # (뜻만 물었는데 '고양이 이름이 뭐예요?' 처럼 내 것을 묻는 질문은 붙이지 않는다)
           IF(has(T_TOPIC, V("단어")),
              setv("주제", V("단어")), setv("주제질문", TOPICQ(V("단어"))),
              IF(NOT(contains(V("주제질문"), "[사실:")), setv("템플릿", join(V("템플릿"), " ", V("주제질문")))))),
    BRANCH(OR(contains(m(), "몇시"), contains(m(), "지금시간"), contains(m(), "현재시간")),
           setv("답변", join("지금은 ", date("HOUR"), "시 ", date("MINUTE"), "분이에요."))),
    BRANCH(OR(contains(m(), "며칠"), contains(m(), "날짜"), contains(m(), "무슨요일"), contains(m(), "몇월")),
           setv("답변", join("오늘은 ", date("YEAR"), "년 ", date("MONTH"), "월 ", date("DAY"), "일 ",
                             item("요일", plus(date("DAY_OF_WEEK"), 1)), "요일이에요."))),
    # 일상 대화 (질문이거나, 짧거나, 주제·감정이 없는 말일 때) — 말 속에서 가장 긴 키워드를 찾아
    # 그 줄의 대답들('|' 로 나눠 둔 것) 중에서 고른다
    IF(undone(), IF(_talk_guard(),
       *FIND_PIECE(T_TALK, m(), "찾은말", "최장길이", "답k"),
       # 한 글자 말 ('헐', 'ㅋ', '굿') 은 말 전체가 그 한 글자일 때만 ('헐!!' 도)
       setv("한글자말", m()),
       IF(gt(slen(V("한글자말")), 1), setv("한글자말", lower(repl(V("문장"), " ", "")))),
       IF(AND(empty(V("찾은말")), eq(slen(V("한글자말")), 1)),
          IF(has(T_TALK, V("한글자말")), setv("찾은말", V("한글자말")))),
       IF(gt(slen(V("찾은말")), 0),
          setv("남은답", join(lookup(T_TALK, V("찾은말")), " | ")),
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
    BRANCH(AND(OR(eq(V("지난대기"), "이야기"), eq(V("지난대기"), "이유")), included("예말", m())),
           setv("템플릿", pick("말-응대답"))),
    # 짧은 대답 ("양념", "건축") 은 받아 주고 이어 간다
    setv("짧은값", ""),
    IF(undone(), setv("짧은값", CLEAN(V("문장")))),
    BRANCH(AND(OR(eq(V("지난대기"), "이야기"), eq(V("지난대기"), "이유"), eq(V("지난대기"), "기분")), not_q(),
               gt(slen(V("짧은값")), 0), lt(slen(V("짧은값")), 13), NOT(included("모름말", V("짧은값"))),
               eq(V("신조어말"), 0)),
           setv("단어", V("짧은값")), setv("연결허용", 1), setv("템플릿", pick("말-짧은대답")),
           IF(eq(rand(1, 2), 1), STARTER())),
    BRANCH(OR(eq(V("지난대기"), "이유"), eq(V("지난대기"), "이야기")),
           setv("연결허용", 1), setv("템플릿", pick("말-들어줌")),
           IF(eq(rand(1, 2), 1), STARTER())),
    BRANCH(gt(slen(V("후보주제")), 1), setv("단어", V("후보주제")), setv("템플릿", pick("말-후보반응"))),
    BRANCH(eq(V("직전기분"), "나쁨"), setv("템플릿", pick("말-위로마무리"))),
    # 이번 대화에서 아직 안 나온 지난 이야기가 있으면 (반쯤은) 그 뒤로 어떻게 됐는지 묻는다
    setv("이야기번호", 0),
    IF(AND(undone(), eq(rand(1, 2), 1)),
       setv("지난k", llen("이야기주제")),
       UNTIL(OR(lt(V("지난k"), 1), gt(V("이야기번호"), 0)), *[x for _ in range(4) for x in [
           IF(AND(gt(V("지난k"), 0), eq(V("이야기번호"), 0)),
              IF(NOT(included("이번주제들", item("이야기주제", V("지난k")))), setv("이야기번호", V("지난k"))),
              chg("지난k", -1))]])),
    BRANCH(gt(V("이야기번호"), 0),
           DIARY_GET(V("이야기번호")),
           setv("주제", item("이야기주제", V("이야기번호"))), append("이번주제들", V("주제")),
           setv("템플릿", join(pick("말-맞장구"), " 그러고 보니 ", V("이야기때"), " ", V("주제"),
                               " 이야기를 했었죠. 그 뒤로 어떻게 됐어요? [이야기]"))),
    BRANCH(eq(1, 1), setv("템플릿", pick("말-맞장구")), STARTER()),
))

# ================================================================ 말투 (반말)
STYLE = Func("반말로 바꾸기", ["글"], value=True)


def _name_rule(suffix, after):
    """'{호칭}님' + suffix → 호칭에 알맞은 조사 (after 가 '' 면 이름만, '아!' 처럼 끝에 문장 부호가 붙을 수 있다)."""
    if after == "":
        to = V("호칭")
    elif after[-1] in "!,":
        to = join(JOSA(V("호칭"), after[:-1]), after[-1])
    else:
        to = JOSA(V("호칭"), after)
    return setv("말투글", repl(V("말투글"), join(V("호칭"), suffix), to))


STYLE.define(
    # 앞에 띄어쓰기를 하나 붙여 두고 (' 저는' 처럼 낱말 앞에서만 바꾸려고) 끝에 뗀다
    setv("말투글", join(" ", STYLE.p("글"))),
    # '민수님은' → '민수는', '민수님!' → '민수야!' (이름에 맞는 조사를 먼저 고른다)
    *[_name_rule(a, b) for a, b in D.BANMAL_NAME_RULES],
    # '이에요' → '이야', '줄래요' → '줄래' … (위에서부터 차례로)
    *[setv("말투글", repl(V("말투글"), a, b)) for a, b in D.BANMAL_RULES],
    ret=HEAD(V("말투글"), 1))

# ================================================================ 날짜 계산
LEAP = Func("윤년", ["해"], value=True)
MDAYS = Func("달의 날 수", ["해", "월"], value=True)
DOY = Func("한 해의 몇째 날", ["해", "월", "일"], value=True)
DAYS = Func("며칠 남았나", ["월", "일"], value=True)
SHIFTDATE = Func("날짜 옮기기", ["며칠"])
PARSEMD = Func("월일 읽기", ["글"])
LEAP.define(
    setv("윤", 0),
    IF(eq(mod(LEAP.p("해"), 4), 0), setv("윤", 1),
       IF(eq(mod(LEAP.p("해"), 100), 0), setv("윤", 0),
          IF(eq(mod(LEAP.p("해"), 400), 0), setv("윤", 1)))),
    ret=V("윤"))
MDAYS.define(
    setv("달날수", item("월일수", MDAYS.p("월"))),
    IF(eq(MDAYS.p("월"), 2), setv("달날수", plus(V("달날수"), LEAP(MDAYS.p("해"))))),
    ret=V("달날수"))
DOY.define(
    setv("몇째날", plus(item("월누적", DOY.p("월")), DOY.p("일"))),
    IF(gt(DOY.p("월"), 2), setv("몇째날", plus(V("몇째날"), LEAP(DOY.p("해"))))),
    ret=V("몇째날"))
DAYS.define(
    # 오늘부터 (올해 또는 내년) 월·일까지 남은 날
    setv("오늘째", DOY(date("YEAR"), date("MONTH"), date("DAY"))),
    setv("그날째", DOY(date("YEAR"), DAYS.p("월"), DAYS.p("일"))),
    IFELSE(NOT(lt(V("그날째"), V("오늘째"))),
           [setv("남은날", minus(V("그날째"), V("오늘째")))],
           [setv("남은날", plus(minus(plus(365, LEAP(date("YEAR"))), V("오늘째")),
                               DOY(plus(date("YEAR"), 1), DAYS.p("월"), DAYS.p("일"))))]),
    ret=V("남은날"))
SHIFTDATE.define(
    # 오늘에서 며칠 옮긴 날 → 옮긴월 · 옮긴일 · 옮긴요일
    setv("옮긴해", date("YEAR")), setv("옮긴월", date("MONTH")), setv("옮긴일", plus(date("DAY"), SHIFTDATE.p("며칠"))),
    IF(gt(V("옮긴일"), MDAYS(V("옮긴해"), V("옮긴월"))),
       setv("옮긴일", minus(V("옮긴일"), MDAYS(V("옮긴해"), V("옮긴월")))), chg("옮긴월", 1),
       IF(gt(V("옮긴월"), 12), setv("옮긴월", 1), chg("옮긴해", 1))),
    IF(lt(V("옮긴일"), 1),
       chg("옮긴월", -1),
       IF(lt(V("옮긴월"), 1), setv("옮긴월", 12), chg("옮긴해", -1)),
       setv("옮긴일", plus(V("옮긴일"), MDAYS(V("옮긴해"), V("옮긴월"))))),
    setv("옮긴요일", item("요일", plus(mod(plus(plus(date("DAY_OF_WEEK"), SHIFTDATE.p("며칠")), 7), 7), 1))),
)
_digits = "0123456789"
# '디데이' 에서 고를 날 (같은 날의 다른 이름은 하나만)
SPECIAL_NAMES = list(dict.fromkeys({(mo, dy): n for n, mo, dy in reversed(D.SPECIAL_DAYS)}.values()))
_numeric = lambda v: AND(gt(slen(v), 0), eq(v, minus(v, 0)))


def _read_number_before(text, pos, var):
    """text 의 pos 바로 앞 한두 글자 숫자를 var 에 넣는다 ('12월' → 12)."""
    return [setv(var, charat(text, minus(pos, 1))),
            IF(gt(pos, 2), IF(contains(_digits, charat(text, minus(pos, 2))),
                              setv(var, join(charat(text, minus(pos, 2)), V(var)))))]


PARSEMD.define(
    # 글 속의 'N월 N일' → 파싱월 · 파싱일 (없으면 0)
    setv("파싱월", 0), setv("파싱일", 0),
    setv("읽을글", repl(PARSEMD.p("글"), " ", "")),
    setv("월위치", find(V("읽을글"), "월")),
    IF(gt(V("월위치"), 1),
       *_read_number_before(V("읽을글"), V("월위치"), "읽은수"),
       IF(AND(_numeric(V("읽은수")), gt(V("읽은수"), 0), lt(V("읽은수"), 13)),
          setv("파싱월", minus(V("읽은수"), 0)),
          setv("월뒤", HEAD(V("읽을글"), V("월위치"))),
          setv("일위치", find(V("월뒤"), "일")),
          IF(gt(V("일위치"), 1),
             *_read_number_before(V("월뒤"), V("일위치"), "읽은수"),
             # (2월은 29일까지 받는다)
             setv("달끝", item("월일수", V("파싱월"))), IF(eq(V("파싱월"), 2), setv("달끝", 29)),
             IF(AND(_numeric(V("읽은수")), gt(V("읽은수"), 0), NOT(gt(V("읽은수"), V("달끝")))),
                setv("파싱일", minus(V("읽은수"), 0)))))),
    IF(eq(V("파싱일"), 0), setv("파싱월", 0)),
)

# ================================================================ 놀이 (끝말잇기 · 가위바위보)
WORD_FIND = Func("끝말 찾기", ["글자"], value=True)
CHAIN_TURN = Func("끝말잇기 받기")
RPS_TURN = Func("가위바위보 받기")
R_GAME = Func("대답: 놀이")
WORD_FIND.define(
    # 정렬된 '끝말단어' 에서 글자로 시작하는 첫 낱말 자리를 이진 탐색으로 찾고, 아직 안 쓴 낱말 하나를 고른다
    setv("끝글자", WORD_FIND.p("글자")),
    setv("아래", 1), setv("위", plus(llen("끝말단어"), 1)),
    *[IF(lt(V("아래"), V("위")),
         setv("가운데", quot(plus(V("아래"), V("위")), 2)),
         IFELSE(lt(item("끝말단어", V("가운데")), V("끝글자")),
                [setv("아래", plus(V("가운데"), 1))], [setv("위", V("가운데"))]))
      for _ in range(CHAIN_STEPS)],
    setv("끝찾음", ""), setv("끝무작위", rand(0, 3)),
    *[IF(eq(V("끝찾음"), ""), IF(NOT(gt(at, llen("끝말단어"))), IF(starts(item("끝말단어", at), V("끝글자")),
         IF(NOT(included("쓴말", item("끝말단어", at))), setv("끝찾음", item("끝말단어", at))))))
      for at in [plus(V("아래"), V("끝무작위")), V("아래"), *[plus(V("아래"), i) for i in range(1, 7)]]],
    ret=V("끝찾음"))
_after_quote = lambda word, kind: join("'", word, "'", HEAD(JOSA(word, kind), slen(word)))


def _chain_hint():
    """끝말 → 끝말안내 ('력' 이면 "'력' 또는 '역'으로", 두음법칙 글자도 알려 준다)"""
    return [setv("끝말안내", _after_quote(V("끝말"), "으로")),
            setv("끝말두음", lookup_kind("두", V("끝말"))),
            IF(gt(slen(V("끝말두음")), 0),
               setv("끝말안내", join("'", V("끝말"), "' 또는 ", _after_quote(V("끝말두음"), "으로"))))]


CHAIN_TURN.define(
    setv("받은말", V("문장")),
    setv("시작글자", charat(V("받은말"), 1)),
    setv("끝말두음", lookup_kind("두", V("끝말"))),
    ELIF_CHAIN(
        (lt(slen(V("받은말")), 2), [setv("템플릿", "두 글자 이상인 낱말로 말해 주세요! [끝말잇기]")]),
        (NOT(OR(eq(V("시작글자"), V("끝말")), AND(gt(slen(V("끝말두음")), 0), eq(V("시작글자"), V("끝말두음"))))),
         [*_chain_hint(),
          setv("템플릿", join("앗, ", _after_quote(V("받은말"), "은"), " ", V("끝말안내"),
                              " 시작하지 않아요! 다시 해 볼래요? [끝말잇기]"))]),
        (included("쓴말", V("받은말")),
         [setv("템플릿", join(_after_quote(V("받은말"), "은"), " 이미 나온 말이에요! 다른 말은 없을까요? [끝말잇기]"))]),
        otherwise=[
            append("쓴말", V("받은말")),
            setv("이을글자", END(V("받은말"), 1)),
            setv("엔봇말", WORD_FIND(V("이을글자"))),
            # 두음법칙: '력' 으로 못 이으면 '역' 으로
            IF(empty(V("엔봇말")),
               setv("이을두음", lookup_kind("두", V("이을글자"))),
               IF(gt(slen(V("이을두음")), 0), setv("엔봇말", WORD_FIND(V("이을두음"))))),
            IFELSE(empty(V("엔봇말")),
                   [setv("템플릿", join("으… ", _after_quote(V("이을글자"), "으로"),
                                        " 시작하는 말이 생각 안 나요. {이름}님이 이겼어요! 🎉"))],
                   [append("쓴말", V("엔봇말")), setv("끝말", END(V("엔봇말"), 1)), *_chain_hint(),
                    setv("템플릿", join(V("엔봇말"), "! 이번엔 ", V("끝말안내"), " 시작하는 말이에요. [끝말잇기]"))])]),
)
RPS_TURN.define(
    setv("내가위", 0),
    IF(OR(contains(m(), "가위"), eq(m(), "찌"), contains(m(), "✌")), setv("내가위", 1)),
    IF(OR(contains(m(), "바위"), contains(m(), "주먹"), eq(m(), "묵"), contains(m(), "✊")), setv("내가위", 2)),
    IF(OR(eq(m(), "보"), eq(m(), "보!"), eq(m(), "보."), contains(m(), "보자기"), eq(m(), "빠"), contains(m(), "✋"),
          contains(m(), "🖐")), setv("내가위", 3)),
    IF(gt(V("내가위"), 0),
       setv("봇가위", rand(1, 3)),
       # (내 것 - 엔봇 것) 을 3 으로 나눈 나머지: 0 비김, 1 내가 이김, 2 엔봇이 이김
       setv("가위결과", mod(plus(minus(V("내가위"), V("봇가위")), 3), 3)),
       ELIF_CHAIN(
           (eq(V("가위결과"), 0), [setv("템플릿", join("저는 ", item("가위바위보", V("봇가위")), "! 비겼어요."))]),
           (eq(V("가위결과"), 1), [chg("가위내점수", 1),
                                   setv("템플릿", join("저는 ", item("가위바위보", V("봇가위")), "! {이름}님이 이겼어요! 🎉"))]),
           otherwise=[chg("가위봇점수", 1),
                      setv("템플릿", join("저는 ", item("가위바위보", V("봇가위")), "! 제가 이겼어요 😆"))]),
       # 판이 끝나도 놀이는 이어진다 ('그만' 이라고 할 때까지)
       setv("템플릿", join(V("템플릿"), " ({이름}님 ", V("가위내점수"), " : 엔봇 ", V("가위봇점수"),
                           ") 또 내 주세요! [가위바위보]")),
       setv("처리됨", 1)),
)
R_GAME.define(
    # 끝말잇기 하는 중: 낱말 하나로 말하면 받는다 (문장으로 말하면 놀이를 멈추고 보통 대화로)
    IF(AND(undone(), eq(V("지난대기"), "끝말잇기")),
       IFELSE(OR(*[contains(m(), w_) for w_ in ["그만", "졌어", "항복", "몰라", "못하겠", "포기"]]),
              [setv("템플릿", pick("말-끝말짐")), setv("처리됨", 1)],
              [IF(eq(llen("원단어들"), 1), CHAIN_TURN(), setv("처리됨", 1))])),
    IF(AND(undone(), eq(V("지난대기"), "가위바위보"), NOT(contains(m(), "가위바위보"))),
       IFELSE(OR(*[contains(m(), w_) for w_ in ["그만", "안 할래", "안할래", "끝"]]),
              [setv("가위승자", "비겼어요!"),
               IF(gt(V("가위내점수"), V("가위봇점수")), setv("가위승자", "{이름}님이 이겼어요! 🏆")),
               IF(lt(V("가위내점수"), V("가위봇점수")), setv("가위승자", "제가 이겼네요! 😆")),
               setv("템플릿", join("가위바위보 끝! {이름}님 ", V("가위내점수"), " : 엔봇 ", V("가위봇점수"), ". ",
                                   V("가위승자"), " 재밌었어요.")),
               setv("처리됨", 1)],
              [RPS_TURN()])),
    BRANCH(AND(contains(m(), "끝말잇기"), eq(V("뜻질문"), 0)),
           clear("쓴말"),
           setv("엔봇말", item("끝말시작", rand(1, llen("끝말시작")))),
           append("쓴말", V("엔봇말")), setv("끝말", END(V("엔봇말"), 1)), *_chain_hint(),
           setv("템플릿", join("좋아요, 끝말잇기! 제가 먼저 할게요. ", V("엔봇말"), "! ", V("끝말안내"),
                               " 시작하는 말을 해 주세요. (그만하려면 '그만') [끝말잇기]"))),
    BRANCH(contains(m(), "가위바위보"), setv("가위내점수", 0), setv("가위봇점수", 0),
           setv("템플릿", "좋아요! 가위, 바위, 보! 하나를 내 주세요. ✊ ✌ ✋ (그만하려면 '그만') [가위바위보]")),
)

# ================================================================ 계산 · 고르기 · 날짜 · 방금 한 말
R_SMART = Func("대답: 계산·고르기·날짜")
_has_digit = lambda: OR(*[contains(m(), d) for d in _digits])
_MATH_WORDS = [("더하기", "+"), ("플러스", "+"), ("빼기", "-"), ("마이너스", "-"), ("곱하기", "*"), ("나누기", "/"),
               ("나눈", "/")]
_MATH_TAILS = ["는얼마야", "은얼마야", "는얼마예요", "은얼마예요", "는얼마", "은얼마", "얼마야", "얼마예요", "얼마",
               "는몇이야", "은몇이야", "몇이야", "몇이에요", "는몇", "은몇", "몇", "계산해줘", "계산해", "알려줘",
               "해줘", "이야", "야", "?", "=", "!", "는", "은", "요"]
_tok = lambda i: item("원단어들", i)
_CONJ = ["이랑", "하고", "이나", "랑", "와", "과"]
_bot_said = IFELSE(empty(V("보인답변")), [setv("답변", "아직 제가 한 말이 없어요.")],
                   [setv("인용글", V("보인답변")), setv("답변", "제가 방금 이렇게 말했어요. “¤”")])
R_SMART.define(
    # 방금 한 말 기억하기 ("내가 방금 뭐라고 했지?", "다시 말해 줘")
    BRANCH(AND(OR(*[contains(m(), w_) for w_ in ["방금", "아까", "조금전", "좀전"]]),
               OR(*[contains(m(), w_) for w_ in ["뭐라고", "뭐라했", "무슨말", "뭐라그랬", "뭐라말"]])),
           IFELSE(OR(starts(m(), "너"), starts(m(), "넌"), starts(m(), "니가"), starts(m(), "네가"), contains(m(), "엔봇")),
                  [_bot_said],
                  [setv("회상k", llen(REC[C_WHO])), setv("회상찾음", 0),
                   UNTIL(OR(lt(V("회상k"), 1), eq(V("회상찾음"), 1)),
                         IFELSE(eq(rec(C_WHO, V("회상k")), "나"), [setv("회상찾음", 1)], [chg("회상k", -1)])),
                   IFELSE(eq(V("회상찾음"), 1),
                          [setv("인용글", rec(C_TEXT, V("회상k"))),
                           setv("답변", join("방금 “¤”", HEAD(JOSA(V("인용글"), "이라고"), slen(V("인용글"))),
                                              " 했어요."))],
                          [setv("답변", "아직 아무 말도 안 했어요!")])])),
    BRANCH(OR(*[eq(m(), w_) for w_ in ["다시말해줘", "다시말해", "다시말해줄래?", "한번더말해줘", "뭐라고?", "뭐라고",
                                        "다시한번말해줘", "응?"]]),
           _bot_said),
    # D-day ("크리스마스까지 며칠 남았어?", "내 생일까지 며칠?", "12월 3일까지 며칠?")
    BRANCH(OR(eq(m(), "디데이"), eq(m(), "d-day"), eq(m(), "기념일"), eq(m(), "다가오는기념일")),
           setv("가까운날", 400),
           *[x for name, mo, dy in D.SPECIAL_DAYS if name in SPECIAL_NAMES for x in [
               setv("남은날", DAYS(mo, dy)),
               IF(lt(V("남은날"), V("가까운날")), setv("가까운날", V("남은날")), setv("디데이이름", name),
                  setv("파싱월", mo), setv("파싱일", dy))]],
           setv("답변", join("다가오는 날은 ", JOSA(V("디데이이름"), "이에요"), "! ", V("가까운날"), "일 남았어요. (",
                             V("파싱월"), "월 ", V("파싱일"), "일) 다른 날도 '어린이날까지 며칠?'처럼 물어보세요.")),
           IF(eq(V("가까운날"), 0), setv("답변", join("오늘이 바로 ", JOSA(V("디데이이름"), "이에요"), "! 🎉")))),
    IF(undone(), IF(OR(AND(contains(m(), "까지"), OR(*[contains(m(), w_) for w_ in ["며칠", "몇일", "얼마나", "남았",
                                                                                    "디데이", "d-day"]])),
                       AND(OR(*[contains(m(), name) for name, _, _ in D.SPECIAL_DAYS]),
                           OR(*[contains(m(), w_) for w_ in ["언제", "며칠", "몇일", "남았", "디데이", "d-day"]]))),
       setv("디데이이름", ""), setv("파싱월", 0), setv("파싱일", 0),
       ELIF_CHAIN(
           *[(contains(m(), name), [setv("디데이이름", name), setv("파싱월", mo), setv("파싱일", dy)])
             for name, mo, dy in D.SPECIAL_DAYS],
           (contains(m(), "생일"),
            [FINDMEM("내 생일"),
             IFELSE(gt(V("찾은키번호"), 0),
                    [setv("생일값", item("내답변", V("찾은키번호"))),
                     IF(starts(V("생일값"), "F:"), setv("생일값", HEAD(V("생일값"), 2))),
                     PARSEMD(V("생일값")),
                     IF(gt(V("파싱월"), 0), setv("디데이이름", join(V("호칭"), "님 생일")))],
                    [setv("템플릿", "아직 {이름}님 생일을 몰라요. 생일이 언제예요? [사실:내 생일]"), setv("처리됨", 1)])]),
           otherwise=[PARSEMD(m()),
                      IFELSE(gt(V("파싱월"), 0), [setv("디데이이름", join(V("파싱월"), "월 ", V("파싱일"), "일"))],
                             [IF(AND(contains(m(), "월"), contains(m(), "일"), _has_digit()),
                                 setv("답변", "음, 그런 날짜는 달력에 없어요! 🤔 날짜를 다시 확인해 줄래요?"),
                                 setv("처리됨", 1))])]),
       IF(AND(gt(slen(V("디데이이름")), 0), gt(V("파싱월"), 0)),
          setv("남은날", DAYS(V("파싱월"), V("파싱일"))),
          IFELSE(eq(V("남은날"), 0),
                 [setv("답변", join("오늘이 바로 ", JOSA(V("디데이이름"), "이에요"), "! 🎉"))],
                 [setv("답변", join(V("디데이이름"), "까지 ", V("남은날"), "일 남았어요!")),
                  IF(NOT(contains(V("디데이이름"), "월 ")),
                     setv("답변", join(V("답변"), " (", V("파싱월"), "월 ", V("파싱일"), "일)")))]),
          setv("처리됨", 1)))),
    # 내일·모레·어제 ("내일 무슨 요일이야?")
    IF(undone(), IF(AND(is_q(), OR(*[contains(m(), w_) for w_ in ["요일", "며칠", "몇일", "날짜", "몇월"]])),
       setv("날짜차", 0), setv("날말", ""),
       ELIF_CHAIN(*[(contains(m(), w_), [setv("날짜차", off), setv("날말", josa_static(w_, ("은", "는")))])
                    for w_, off in D.RELATIVE_DAYS]),
       IF(gt(slen(V("날말")), 0),
          SHIFTDATE(V("날짜차")),
          setv("답변", join(V("날말"), " ", V("옮긴월"), "월 ", V("옮긴일"), "일 ", V("옮긴요일"), "요일이에요.")),
          setv("처리됨", 1)))),
    # 말로 하는 계산 ("3 더하기 5는?", "12*3은?")
    IF(undone(), IF(AND(_has_digit(), OR(*[contains(m(), w_) for w_, _ in _MATH_WORDS],
                                         *[contains(m(), op) for op in ["+", "*", "/", "×", "÷"]],
                                         AND(is_q(), OR(contains(m(), "-"), contains(m(), "x"))))),
       setv("수식", m()),
       *[setv("수식", repl(V("수식"), a, b)) for a, b in _MATH_WORDS],
       *[setv("수식", repl(V("수식"), t, "")) for t in _MATH_TAILS],
       setv("계산결과", CALC(V("수식"))),
       IF(NOT(starts(V("계산결과"), "식을")),
          IFELSE(starts(V("계산결과"), "0으로"), [setv("답변", V("계산결과"))],
                 [setv("답변", join(JOSA(V("계산결과"), "이에요"), "!"))]),
          setv("처리됨", 1)))),
    # 고르기 ("짜장면이랑 짬뽕 중에 뭐 먹을까?", "영화 아니면 게임?")
    IF(undone(), IF(AND(OR(*[contains(m(), w_) for w_ in ["중에", "중엔", "중하나", "아니면", "vs"]]),
                        OR(is_q(), *[contains(m(), w_) for w_ in ["골라", "정해", "추천", "뭐가", "vs"]])),
       clear("선택지"), setv("선택위치", 0), setv("선택종류", ""),
       *SCAN("원단어들", lambda: [ELIF_CHAIN(
           (OR(starts(_tok(V("선택k")), "중에"), eq(_tok(V("선택k")), "중"), eq(_tok(V("선택k")), "중엔")),
            [setv("선택위치", V("선택k")), setv("선택종류", "중"), BREAK()]),
           (OR(eq(_tok(V("선택k")), "아니면"), eq(_tok(V("선택k")), "아님"), eq(lower(_tok(V("선택k"))), "vs")),
            [setv("선택위치", V("선택k")), setv("선택종류", "아니면"), BREAK()]))], 4, k="선택k"),
       IF(AND(eq(V("선택종류"), "중"), gt(V("선택위치"), 1)),
          IFELSE(contains(V("메시지"), ","),
                 # 쉼표로 늘어놓았으면 '중' 앞 낱말 모두
                 [setv("선택j", 1),
                  REPEAT(minus(V("선택위치"), 1),
                         IF(NOT(included("불용어", item("단어들", V("선택j")))), append("선택지", item("단어들", V("선택j")))),
                         chg("선택j", 1))],
                 # '이랑·하고·와…' 로 이어진 낱말들
                 [append("선택지", item("단어들", minus(V("선택위치"), 1))),
                  setv("선택j", minus(V("선택위치"), 2)), setv("선택이어짐", 1),
                  UNTIL(OR(lt(V("선택j"), 1), eq(V("선택이어짐"), 0)),
                        IFELSE(OR(*[ends(_tok(V("선택j")), c) for c in _CONJ]),
                               [append("선택지", item("단어들", V("선택j"))), chg("선택j", -1)],
                               [setv("선택이어짐", 0)]))])),
       IF(AND(eq(V("선택종류"), "아니면"), gt(V("선택위치"), 1), lt(V("선택위치"), llen("원단어들"))),
          setv("선택앞", minus(V("선택위치"), 1)),
          IF(gt(V("선택앞"), 1), IF(OR(*[ends(_tok(V("선택앞")), e) for e in ["까", "래", "지", "냐"]]), chg("선택앞", -1))),
          append("선택지", item("단어들", V("선택앞"))),
          append("선택지", item("단어들", plus(V("선택위치"), 1)))),
       IF(gt(llen("선택지"), 1),
          setv("단어", item("선택지", rand(1, llen("선택지")))),
          IF(gt(slen(V("단어")), 0), setv("템플릿", pick("말-고르기")), setv("처리됨", 1))))),
    # 주사위 · 동전 · 숫자 뽑기
    BRANCH(contains(m(), "주사위"),
           setv("주사위", rand(1, 6)), setv("답변", join("🎲 데굴데굴… ", JOSA(V("주사위"), "이"), " 나왔어요!"))),
    BRANCH(AND(contains(m(), "동전"), OR(*[contains(m(), w_) for w_ in ["던져", "던지", "앞뒤", "뒤집"]])),
           IFELSE(eq(rand(1, 2), 1), [setv("답변", "🪙 휙~ 앞면이 나왔어요!")], [setv("답변", "🪙 휙~ 뒷면이 나왔어요!")])),
    IF(undone(), IF(AND(OR(AND(contains(m(), "부터"), contains(m(), "까지")), AND(contains(m(), "에서"), contains(m(), "사이"))),
                        _has_digit(), OR(*[contains(m(), w_) for w_ in ["숫자", "랜덤", "아무", "골라", "뽑"]])),
       setv("범위시작", ""), setv("범위끝", ""),
       *SCAN("원단어들", lambda: [
           IF(AND(gt(slen(V("범위시작")), 0), empty(V("범위끝")), _numeric(_tok(V("범위k")))),
              setv("범위끝", _tok(V("범위k")))),
           IF(OR(ends(_tok(V("범위k")), "부터"), ends(_tok(V("범위k")), "에서")),
              setv("범위시작", TAIL(_tok(V("범위k")), 2))),
           IF(ends(_tok(V("범위k")), "까지"), setv("범위끝", TAIL(_tok(V("범위k")), 2)))], 4, k="범위k"),
       IF(AND(_numeric(V("범위시작")), _numeric(V("범위끝"))), IF(lt(V("범위시작"), V("범위끝")),
          setv("답변", join("🎲 ", rand(V("범위시작"), V("범위끝")), "! (", V("범위시작"), "부터 ", V("범위끝"),
                            " 사이에서 골랐어요)")),
          setv("처리됨", 1))))),
    BRANCH(OR(*[contains(m(), w_) for w_ in ["랜덤숫자", "아무숫자", "숫자하나", "숫자골라", "숫자뽑"]]),
           setv("답변", join("🎲 ", rand(1, 100), "! (1부터 100 사이에서 골랐어요)"))),
    # 구구단 ("구구단 7단")
    setv("구구단요청", 0),
    IF(contains(m(), "구구단"), setv("구구단요청", 1)),
    IF(AND(gt(llen("원단어들"), 0), lt(llen("원단어들"), 4)),
       IF(AND(ends(_tok(1), "단"), _numeric(TAIL(_tok(1), 1))), setv("구구단요청", 1))),
    BRANCH(eq(V("구구단요청"), 1),
           setv("단수", rand(2, 9)),
           *SCAN("원단어들", lambda: [IF(AND(ends(_tok(V("단k")), "단"), gt(slen(_tok(V("단k"))), 1)),
                                        IF(_numeric(TAIL(_tok(V("단k")), 1)), setv("단수", TAIL(_tok(V("단k")), 1))))],
                 4, k="단k"),
           setv("답변", join(V("단수"), "단이에요! ",
                             *[x for i in range(1, 10) for x in [V("단수"), "×", i, "=", calc(V("단수"), "MULTI", i),
                                                                  " · " if i < 9 else ""]]))),
)

# ================================================================ 지난 이야기 (예전 대화 참고)
# 주제마다 마지막으로 이야기한 날짜·감정 점수·한 말을 '이야기주제' / '이야기값'("2026-10-26|-2|수학 시험 망쳤어")에
# 적어 두고, 기억과 함께 서버에 저장한다 (기억블롭의 '@주제=값' 줄). 대화 기록(최근 40줄)보다 오래 남는다.
DIARY_FIND.define(
    setv("이야기번호", 0),
    *SCAN("이야기주제", lambda: [IF(eq(item("이야기주제", V("이야기k")), DIARY_FIND.p("주제")),
                                   setv("이야기번호", V("이야기k")), BREAK())], 4, k="이야기k"),
)
DIARY_GET.define(
    # 번호째 지난 이야기 → 이야기날짜 · 이야기월 · 이야기일 · 이야기점수 · 이야기요약 · 이야기때 ('아까', '어제', '3일 전에' …)
    setv("지난값", item("이야기값", DIARY_GET.p("번호"))),
    setv("이야기날짜", sub(V("지난값"), 1, 10)),
    setv("지난나머지", HEAD(V("지난값"), 11)),
    setv("지난위치", find(V("지난나머지"), "|")),
    setv("이야기점수", 0), setv("이야기요약", ""),
    IF(gt(V("지난위치"), 1),
       setv("이야기점수", sub(V("지난나머지"), 1, minus(V("지난위치"), 1))),
       setv("이야기요약", HEAD(V("지난나머지"), V("지난위치")))),
    setv("이야기월", minus(sub(V("이야기날짜"), 6, 7), 0)), setv("이야기일", minus(sub(V("이야기날짜"), 9, 10), 0)),
    setv("이야기조사", HEAD(JOSA(V("이야기요약"), "이라고"), slen(V("이야기요약")))),
    IFELSE(eq(V("이야기날짜"), TODAY()),
           [setv("이야기때", "아까")],
           [setv("이야기때", join("지난번(", V("이야기월"), "월 ", V("이야기일"), "일)에")),
            IF(eq(sub(V("이야기날짜"), 1, 4), date("YEAR")),
               setv("지난날수", minus(DOY(date("YEAR"), date("MONTH"), date("DAY")),
                                      DOY(date("YEAR"), V("이야기월"), V("이야기일")))),
               IF(eq(V("지난날수"), 1), setv("이야기때", "어제")),
               IF(AND(gt(V("지난날수"), 1), lt(V("지난날수"), 7)), setv("이야기때", join(V("지난날수"), "일 전에"))))]),
)
DIARY_PUT.define(
    # 같은 주제는 지우고 맨 뒤에 다시 적는다 (맨 뒤가 가장 최근)
    DIARY_FIND(DIARY_PUT.p("주제")),
    IF(gt(V("이야기번호"), 0), remove("이야기주제", V("이야기번호")), remove("이야기값", V("이야기번호"))),
    append("이야기주제", DIARY_PUT.p("주제")),
    append("이야기값", join(TODAY(), "|", DIARY_PUT.p("점수"), "|", DIARY_PUT.p("요약"))),
    IF(gt(llen("이야기주제"), MAX_DIARY), remove("이야기주제", 1), remove("이야기값", 1)),
    setv("기억변경", 1),
)


def _past_link():
    """지난번에도 같은 주제를 이야기했으면 대답 앞에 붙일 말 (그때와 지금의 기분을 견준다)."""
    said = lambda head, tail: join(V("이야기때"), head, "“¤”", V("이야기조사"), tail)
    return [
        setv("인용글", V("이야기요약")),
        ELIF_CHAIN(
            (empty(V("이야기요약")), [setv("연결말", join(V("이야기때"), "도 ", V("주제"), " 이야기를 했었죠! "))]),
            (AND(lt(V("이야기점수"), 0), gt(V("감정점수"), 0)),
             [setv("연결말", said("는 ", " 하면서 속상해했는데, 이번엔 기분이 좋아 보여서 다행이에요! "))]),
            (AND(lt(V("이야기점수"), 0), lt(V("감정점수"), 0)),
             [setv("연결말", said("도 ", " 하면서 힘들어했죠… "))]),
            (AND(gt(V("이야기점수"), 0), lt(V("감정점수"), 0)),
             [setv("연결말", said("는 ", " 하면서 즐거워했는데, 이번엔 속상한 일이 있었군요. "))]),
            otherwise=[setv("연결말", join(V("이야기때"), "도 ", V("주제"), " 이야기를 했었죠! 그때 “¤”",
                                           V("이야기조사"), " 했어요. "))]),
    ]


_PAST_WORDS = ["지난번", "저번", "예전", "옛날에", "지난대화", "전번", "지난주", "우리전에", "내가전에", "너랑전에"]
_PAST_ASK = ["무슨얘기", "무슨이야기", "뭔얘기", "뭐얘기", "뭘얘기", "무슨대화", "뭐라고했", "뭐라했", "무슨말했",
             "무슨말을했", "기억나", "얘기했", "이야기했", "대화했"]
R_PAST = Func("대답: 지난 이야기")
R_PAST.define(
    # "지난번에 무슨 얘기 했지?", "저번에 시험 얘기 했었나?" (생일·이름처럼 기억을 묻는 말은 '대답: 기억' 이 맡는다)
    BRANCH(AND(OR(*[contains(m(), w_) for w_ in _PAST_WORDS], starts(m(), "전에")),
               OR(*[contains(m(), w_) for w_ in _PAST_ASK]),
               NOT(OR(*[contains(m(), cue) for cue, _ in D.RECALL_ALIASES]))),
           setv("이야기번호", 0),
           IF(gt(slen(V("주제")), 0), DIARY_FIND(V("주제"))),
           IFELSE(gt(V("이야기번호"), 0),
                  [DIARY_GET(V("이야기번호")), setv("인용글", V("이야기요약")),
                   setv("답변", join(V("이야기때"), " ", V("주제"), " 이야기를 할 때 “¤”", V("이야기조사"), " 했어요."))],
                  [IFELSE(eq(llen("이야기주제"), 0),
                          [setv("답변", "아직 기억나는 지난 이야기가 없어요. 오늘 이야기를 들려주면 다음에 꼭 기억할게요!")],
                          [setv("인용글", ""), setv("지난k", llen("이야기주제")),
                           REPEAT(3, IF(gt(V("지난k"), 0),
                                        DIARY_GET(V("지난k")),
                                        setv("지난날", join(V("이야기월"), "월 ", V("이야기일"), "일")),
                                        IF(eq(V("이야기때"), "아까"), setv("지난날", "오늘")),
                                        setv("인용글", join(V("인용글"), SEP, "· ", V("지난날"), " ",
                                                            item("이야기주제", V("지난k")), ": “", V("이야기요약"), "”")),
                                        chg("지난k", -1))),
                           IFELSE(gt(slen(V("주제")), 0),
                                  [setv("답변", join(JOSA(V("주제"), "은"),
                                                     " 기억에 없어요. 최근에는 이런 이야기를 했어요.¤"))],
                                  [setv("답변", "기억나요! 최근에 나눈 이야기예요.¤")])])])),
)

REPLY.define(
    setv("답변", ""), setv("템플릿", ""), setv("처리됨", 0), setv("이번대기", ""), setv("새기분", ""), setv("기록가림", 0),
    setv("말투제외", 0), setv("말투변경", 0), setv("인용글", ""),
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
    # ('주사위 굴려줘' 같은 말이 엔봇이 물어본 것의 대답으로 기억되지 않게 계산·놀이를 먼저 본다)
    R_CMD(), R_GAME(), R_SMART(), R_PAST(), R_PENDING(), R_MEMORY(), R_TALK(), R_FEEL(), R_LAST(),
    # 예전 대화 참고: 이번 대화에서 처음 나온 주제를 지난번에도 이야기했으면 그때 한 말과 기분을 꺼낸다
    IF(AND(gt(slen(V("주제")), 0), NOT(included("이번주제들", V("주제")))),
       append("이번주제들", V("주제")),
       IF(AND(eq(V("연결허용"), 1), empty(V("연결말"))),
          DIARY_FIND(V("주제")),
          IF(gt(V("이야기번호"), 0), DIARY_GET(V("이야기번호")), *_past_link()))),
    # 마무리: 템플릿 → 답변, 대화 상태 저장
    IF(AND(eq(V("연결허용"), 1), gt(slen(V("연결말")), 0), gt(slen(V("템플릿")), 0)),
       setv("템플릿", join(V("연결말"), V("템플릿")))),
    IF(gt(slen(V("템플릿")), 0), setv("답변", FILL(V("템플릿")))),
    IF(empty(V("답변")), setv("답변", "음… 다시 한번 말해 줄래요?")),
    # 바로 전과 똑같은 대답은 하지 않는다
    IF(AND(eq(V("답변"), V("지난답변")), NOT(OR(eq(V("이번대기"), "끝말잇기"), eq(V("이번대기"), "가위바위보")))),
       setv("이번대기", ""), setv("템플릿", pick("말-맞장구")), STARTER(), setv("답변", FILL(V("템플릿")))),
    setv("지난답변", V("답변")),
    setv("직전기분", V("새기분")),
    setv("대기질문", V("이번대기")),
    IF(AND(eq(V("연결허용"), 1), gt(slen(V("주제")), 0), NOT(eq(V("주제"), V("최근주제")))),
       setv("최근주제", V("주제")), SAVEFACT("#최근주제", V("주제"))),
    IF(AND(gt(slen(V("새기분")), 0), NOT(eq(V("새기분"), V("지난기분")))),
       setv("지난기분", V("새기분")), SAVEFACT("#기분", V("새기분"))),
    IF(eq(V("말투변경"), 1), SAVEFACT("#말투", V("말투"))),
    # 주제가 있는 이야기면 '지난 이야기' 에 적어 둔다 (다음에 같은 주제가 나오면 꺼낸다)
    IF(AND(gt(slen(V("주제")), 0), eq(V("연결허용"), 1), not_q(), eq(V("기록가림"), 0)),
       setv("새요약", V("문장")), IF(empty(V("새요약")), setv("새요약", V("메시지"))),
       IF(gt(slen(V("새요약")), DIARY_SUMMARY), setv("새요약", join(sub(V("새요약"), 1, DIARY_SUMMARY), "…"))),
       DIARY_PUT(V("주제"), V("감정점수"), V("새요약"))),
)

# ================================================================ 대화 기록 (리스트 '기록-…')
LOGROW.define(
    # 번호는 오래된 줄을 지워도 바뀌지 않는 일련번호
    chg("기록번호", 1), append(REC[C_NO], V("기록번호")),
    # 빈 칸은 '-' 로 넣는다 (대화기록표로 옮길 때 엔트리 테이블은 빈 칸을 '없음'으로 보고 다시 못 바꾼다)
    *[IFELSE(empty(LOGROW.p(name)), [append(REC[col], "-")], [append(REC[col], LOGROW.p(name))])
      for name, col in [("날짜", C_DATE), ("시각", C_TIME), ("누가", C_WHO), ("주제", C_TOPIC), ("감정", C_FEEL),
                        ("내용", C_TEXT)]],
    # 오래된 줄은 지운다 (대화기록표에 이미 옮긴 줄이면 표에서도 맨 윗줄을 지우도록 표시)
    IF(gt(llen(REC[C_TEXT]), MAX_RECORDS),
       *[remove(REC[col], 1) for col in REC],
       IF(gt(V("표에넣은"), 0), chg("표에넣은", -1), chg("표지울줄", 1))),
)
LOG.define(
    # 한 줄을 '누가|날짜|시각|주제|감정|내용' 으로 서버용 기록에 붙이고, 기록 리스트에도 넣는다.
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
CLEARLOG.define(*[clear(REC[col]) for col in REC], setv("기록번호", 0), setv("표다시", 1))

_row = lambda col: rec(col, V("검색k"))
SEARCH.define(
    IFELSE(empty(SEARCH.p("낱말")),
           [setv("답변", "이렇게 입력해 주세요 → 기록 검색: 고양이")],
           [setv("검색결과", ""), SEARCH.set("찾은수", 0),
            setv("검색k", llen(REC[C_TEXT])),
            # 최근 기록부터 거꾸로 훑는다
            UNTIL(lt(V("검색k"), 1), *[x for _ in range(3) for x in [
                IF(NOT(lt(V("검색k"), 1)),
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

_srow = lambda col: rec(col, V("통계k"))
STATS.define(
    setv("통계주제글", ""), clear("통계주제"), setv("오늘날짜", TODAY()),
    setv("통계k", 1),
    UNTIL(gt(V("통계k"), llen(REC[C_TEXT])), *[x for _ in range(3) for x in [
        IF(NOT(gt(V("통계k"), llen(REC[C_TEXT]))),
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
    setv("답변", join("대화 기록 통계예요.", SEP, "· 모두 ", llen(REC[C_TEXT]), "줄 (", V("호칭"), "님 ",
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
    # 지난 이야기는 '@주제=값' 줄로
    setv("묶음k", 1),
    REPEAT(llen("이야기주제"),
           setv("기억블롭", join(V("기억블롭"), "@", item("이야기주제", V("묶음k")), "=", item("이야기값", V("묶음k")), SEP)),
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
             IFELSE(starts(V("줄"), "@"),
                    # 지난 이야기 ('@시험=2026-10-26|-2|…' — 모양이 맞을 때만)
                    [setv("지난값", HEAD(V("줄"), V("위치"))),
                     IF(AND(gt(V("위치"), 2), gt(slen(V("지난값")), 12)), IF(eq(charat(V("지난값"), 11), "|"),
                        append("이야기주제", sub(V("줄"), 2, minus(V("위치"), 1))), append("이야기값", V("지난값"))))],
                    [append("내질문", sub(V("줄"), 1, minus(V("위치"), 1))),
                     append("내답변", HEAD(V("줄"), V("위치")))])))),
    # 지난번 대화 상태
    *SCAN("내질문", lambda: [
        ELIF_CHAIN((eq(item("내질문", V("불러k")), "#최근주제"), [setv("최근주제", item("내답변", V("불러k")))]),
                   (eq(item("내질문", V("불러k")), "#기분"), [setv("지난기분", item("내답변", V("불러k")))]),
                   (eq(item("내질문", V("불러k")), "#말투"), [setv("말투", item("내답변", V("불러k")))]),
                   (eq(item("내질문", V("불러k")), "내 이름"),
                    [IF(starts(item("내답변", V("불러k")), "F:"), setv("호칭", HEAD(item("내답변", V("불러k")), 2)))]))],
          3, k="불러k"),
    # 지난 대화 → 기록 리스트에 펼치고, 마지막 몇 줄은 말풍선으로 보여 준다
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
    clean_input = repl(repl(repl(repl(repl(repl(repl(answer(), SEP, " "), "[", "("), "]", ")"), "{", "("), "}", ")"), "|", "/"),
                       "¤", " ")
    return WHEN_START(
        setv("글자-받침없음", D.NO_BATCHIM), setv("글자-ㄹ받침", D.RIEUL), setv("글자-ㅆ받침", D.SSANG_SIOT),
        HIDE_ANSWER(),
        clear("화면글"), clear("화면종류"), clear("후보답변"), clear("내질문"), clear("내답변"),
        clear("단어들"), clear("원단어들"),
        # 대화기록표(테이블)는 '기록표연결' 이 1 일 때만 쓴다 (값은 작품에 저장된 대로 둔다)
        setv("표에넣은", 0), setv("표지울줄", 0),
        CLEARLOG(),
        CAST("화면 그리기"),
        STATUS("● 연결 중…"),
        setv("아이디", username()),
        setv("닉네임", nickname()),
        setv("기록블롭", ""), setv("기억블롭", ""), setv("기록위치", 0), setv("기억위치", 0),
        setv("대기질문", ""), setv("최근주제", ""), setv("지난기분", ""), setv("직전기분", ""), setv("기억변경", 0),
        setv("지난답변", ""), setv("주제", ""), setv("단어", ""), setv("키표시", ""), setv("값", ""), setv("감정점수", 0),
        setv("말투", "존댓말"), setv("말투제외", 0), setv("끝말", ""), clear("쓴말"),
        setv("인용글", ""), clear("이야기주제"), clear("이야기값"), clear("이번주제들"),
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
                    (gt(slen(V("최근주제")), 0),
                     [setv("주제", V("최근주제")), append("이번주제들", V("주제")),
                      setv("템플릿", pick("말-환영주제")),
                      # 그 주제로 마지막에 한 말이 있으면 그 말을 꺼낸다
                      DIARY_FIND(V("주제")),
                      IF(gt(V("이야기번호"), 0), DIARY_GET(V("이야기번호")),
                         IF(gt(slen(V("이야기요약")), 0),
                            setv("인용글", V("이야기요약")),
                            setv("템플릿", join("{이름}님, 다시 왔군요! ", V("이야기때"), " “¤”", V("이야기조사"), " 했었죠. ")),
                            ELIF_CHAIN(
                                (lt(V("이야기점수"), 0), [setv("템플릿", join(V("템플릿"), "그 뒤로 좀 괜찮아졌어요? [기분]"))]),
                                (gt(V("이야기점수"), 0), [setv("템플릿", join(V("템플릿"), "요즘도 그래요? 😊 [이야기]"))]),
                                otherwise=[setv("템플릿", join(V("템플릿"), "그 뒤로 어떻게 됐어요? [이야기]"))])))]),
                    (eq(V("지난기분"), "나쁨"), [setv("템플릿", pick("말-환영기분"))]),
                    otherwise=[setv("템플릿", pick("말-환영"))]),
                IF(eq(V("저장가능"), 0), PRINT("저장 서버에 연결하지 못해서 이번 대화는 저장되지 않아요.", "알림"))]),
        setv("이번대기", ""),
        setv("답변", FILL(V("템플릿"))),
        IF(eq(V("말투"), "반말"), setv("답변", STYLE(V("답변")))),
        IF(gt(slen(V("인용글")), 0), setv("답변", repl(V("답변"), "¤", V("인용글")))),
        setv("대기질문", V("이번대기")),
        PRINT(V("답변"), "봇"),
        setv("보인답변", V("답변")),
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
                 # 반말로 해 달라고 했으면 엔봇의 말을 반말로 (사용자가 한 말을 그대로 보여 주는 대답은 빼고)
                 IF(AND(eq(V("말투"), "반말"), eq(V("말투제외"), 0)), setv("답변", STYLE(V("답변")))),
                 IF(gt(slen(V("인용글")), 0), setv("답변", repl(V("답변"), "¤", V("인용글")))),
                 setv("보인답변", V("답변")),
                 # 개인정보가 담긴 말은 서버 기록과 기록표에 남기지 않는다
                 IFELSE(eq(V("기록가림"), 1), [LOG("나", "🔒 (개인정보라서 기록하지 않았어요)")], [LOG("나", V("메시지"))]),
                 PRINT(V("답변"), "봇"),
                 LOG("봇", V("답변")),
                 IF(eq(V("기록표연결"), 1), TABLE_SYNC()),
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
        # 기록표를 켜면 맨 먼저 비우지만, 빈 표(데이터 0줄)는 엔트리 화면에서 만들 수 없는 모양이라
        # 안내 줄 하나를 넣어 둔다. (정지하면 테이블은 이 상태로 돌아간다)
        table(T_LOG, LOG_FIELDS, [[int(r[0])] + r[1:] for r in KNOW[T_LOG][1]]),
    ]
    unknown = set(TABLES) - {t["name"] for t in tables}
    assert not unknown, f"만들지 않은 테이블을 블록에서 씀: {unknown}"
    lists = [
        lst("화면글"), lst("화면종류"), lst("단어들"), lst("원단어들"), lst("후보답변"), lst("내질문"), lst("내답변"),
        lst("통계주제"), *[lst(name) for name in REC.values()],
        lst("지식키", KNOW_KEYS), lst("지식값", KNOW_VALUES),
        lst("먼저-키", [r[0] for r in KNOW[T_ASK][1]]), lst("먼저-질문", [r[1] for r in KNOW[T_ASK][1]]),
        lst("끝말단어", CHAIN_WORDS), lst("끝말시작", CHAIN_STARTERS), lst("쓴말"), lst("선택지"),
        lst("가위바위보", ["가위", "바위", "보"]),
        lst("월일수", D.MONTH_DAYS), lst("월누적", [sum(D.MONTH_DAYS[:i]) for i in range(12)]),
        lst("불용어", D.STOPWORDS), lst("조사목록", D.JOSA_SUFFIXES), lst("형용사", D.ADJ_STEMS), lst("요일", D.WEEKDAYS),
        lst("예말", D.YES_WORDS), lst("모름말", D.NON_ANSWERS), lst("뒤집는말", D.NEGATORS),
        lst("신조어목록", SLANG_FORMS), lst("이야기주제"), lst("이야기값"), lst("이번주제들"),
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
        *[variable(n, {"기록표연결": 0}.get(n, "")) for n in VARS],
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
