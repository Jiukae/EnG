#!/usr/bin/env python3
"""엔트리(playentry.org)용 'AI 챗봇 엔봇' 작품 파일(.ent)을 만든다.

.ent 파일은 temp/project.json 하나를 담은 tar.gz 압축 파일이다
(entrylabs/entry-offline 의 MainUtils.saveProject 와 같은 구조).

엔봇이 대답을 만드는 순서 (신호 '답변 만들기')
  1. 문장 분석: 낱말로 나누고 조사를 떼서 주제·질문 여부·감정 점수·되받을 말(서술)을 찾는다
  2. 명령(도움말, 기억해:, 번역: …) 처리
  3. 직전에 엔봇이 물어본 것(대화 상태)에 대한 대답이면 그 내용을 기억한다
  4. "내 생일은 3월 14일이야", "나 축구 좋아해" 같은 말에서 사실을 뽑아 기억한다
  5. 기억에서 찾기 → 단어 뜻 → 일상 대화 → 모르는 단어 배우기
  6. 감정(공감) → 주제(이어서 묻기) → 되받기 → 모르는 질문 배우기 → 엔봇이 먼저 묻기

사용법:  python3 build_project.py   →  entry-ai-chatbot.ent, project.json 생성
"""
import io
import json
import os
import re
import tarfile
import time

import data as D
from dsl import (AND, ASK, BG, BREAK, CALL, CAST, ELIF_CHAIN, FG, FOREVER, HIDE, HIDE_ANSWER, IF, IFELSE, calc, fresh,
                 LISTS, MSGS, NOT, OR, REPEAT, SCAN, SHOW, UNSAY, UNTIL, V, VARS, WAIT, WHEN_MSG, WHEN_START,
                 WRITE, answer, append, charat, chg, clear, contains, count, date, empty, eq, find, gen_id, gt,
                 included, item, join, llen, lower, lt, minus, mod, nickname, pick, plus, rand, remove, repl, reverse,
                 setitem, setv, slen, starts, sub, translate, username, walk_blocks)

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ENT = os.path.join(HERE, "entry-ai-chatbot.ent")
OUT_JSON = os.path.join(HERE, "project.json")

SEP = "¶"               # 저장 문자열 안에서 줄을 나누는 기호
CHUNK = 24              # 말풍선 한 줄의 최대 글자 수
ROWS = 9                # 화면에 보이는 말풍선 줄 수
MAX_HISTORY_LINES = 30  # 사용자마다 서버에 남기는 대화 줄 수
MAX_LINE_LEN = 120      # 서버에 남기는 한 줄의 최대 길이
MAX_MEMORIES = 50       # 사용자마다 기억하는 것의 수

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


# ---------------------------------------------------------------- 자주 쓰는 블록 묶음
def PRINT(text, kind):
    """대화창에 text 를 kind(봇/나/알림/기록) 말풍선으로 출력한다 (¶ 는 줄바꿈)."""
    return [setv("출력문자열", text), setv("출력종류", kind), CALL("채팅에 출력")]


def STATUS(text):
    return [setv("상태글", text), CALL("상태 표시")]


def TRIM_INTO(dst, src):
    """src 값의 앞뒤 공백을 지워 변수 dst 에 넣는다."""
    return [setv("공백정리", src), CALL("공백 정리"), setv(dst, V("공백정리"))]


def BRANCH(cond, *body, guard=None):
    """아직 답이 정해지지 않았고 cond 가 참이면 body 를 실행한다.
    guard 는 cond 를 계산하기 전에 확인할 조건 (엔트리는 조건 블록 안을 모두 먼저 계산하므로
    리스트 범위를 벗어나는 계산을 막을 때 쓴다)."""
    inner = IF(cond, *body, setv("처리됨", 1))
    if guard is not None:
        inner = IF(guard, inner)
    return IF(eq(V("처리됨"), 0), inner)


def SPLIT_LINE(rest, line, pos):
    """변수 rest 에서 ¶ 앞까지를 꺼내 변수 line 에 넣고, rest 에서는 지운다."""
    return [
        setv(pos, find(V(rest), SEP)),
        IFELSE(eq(V(pos), 0),
               [setv(line, V(rest)), setv(rest, "")],
               [IFELSE(gt(V(pos), 1), [setv(line, sub(V(rest), 1, minus(V(pos), 1)))], [setv(line, "")]),
                IFELSE(lt(V(pos), slen(V(rest))),
                       [setv(rest, sub(V(rest), plus(V(pos), 1), slen(V(rest))))],
                       [setv(rest, "")])]),
    ]


def CUT_TAIL(var, n):
    """변수 var 의 뒤 n 글자를 지운다 (길이가 n 이하이면 빈 문자열). n 은 숫자 또는 값 블록."""
    return IFELSE(gt(slen(V(var)), n), [setv(var, sub(V(var), 1, minus(slen(V(var)), n)))], [setv(var, "")])


def CUT_HEAD(var, n):
    """변수 var 의 앞 n 글자를 지운다. n 은 숫자 또는 값 블록."""
    start = plus(n, 1) if isinstance(n, dict) else n + 1
    return IFELSE(gt(slen(V(var)), n), [setv(var, sub(V(var), start, slen(V(var))))], [setv(var, "")])


def ends(var, suffix):
    """변수 var 가 suffix 로 끝나는지 (길이가 모자라면 거짓). 범위 오류가 나지 않게 앞에 공백을 붙여 본다."""
    n = len(suffix)
    return eq(sub(join("    ", V(var)), minus(plus(slen(V(var)), 4), n - 1), plus(slen(V(var)), 4)), suffix)


def FIND_INDEX(lst, value, out, k):
    """리스트 lst 에서 value 와 같은 항목 번호를 out 에 넣는다 (없으면 0)."""
    return [setv(out, 0), *SCAN(lst, lambda: [IF(eq(item(lst, V(k)), fresh(value)), setv(out, V(k)), BREAK())], 6, k=k)]


# ---------------------------------------------------------------- 서버 저장 (실시간 리스트)
def FIND_SLOT(lst, pos_var):
    """서버 리스트 lst 에서 '아이디|' 로 시작하는 항목 번호를 pos_var 에 넣는다 (없으면 0)."""
    return [setv(pos_var, 0),
            *SCAN(lst, lambda: [IF(starts(item(lst, V("칸k")), V("접두어")), setv(pos_var, V("칸k")), BREAK())],
                  8, k="칸k")]


def SAVE_SLOT(lst, pos_var, finder_msg, blob_var):
    """내 항목이 맞는지 확인한 뒤 서버 리스트의 내 칸을 '아이디|' + blob 으로 바꾼다."""
    return IF(eq(V("저장가능"), 1),
              setv("확인", 0),
              IF(gt(V(pos_var), 0),
                 IF(NOT(gt(V(pos_var), llen(lst))),
                    IF(starts(item(lst, V(pos_var)), V("접두어")), setv("확인", 1)))),
              IF(eq(V("확인"), 0),
                 CALL(finder_msg),
                 IF(gt(V(pos_var), 0), setv("확인", 1))),
              IF(eq(V("확인"), 1), setitem(lst, V(pos_var), join(V("접두어"), V(blob_var)))))


def ENSURE_SLOT(lst, pos_var, finder_msg):
    """내 칸이 없으면 새로 만들고, 서버 반영을 기다렸다가 다시 찾는다."""
    return [
        CALL(finder_msg),
        IF(eq(V(pos_var), 0),
           append(lst, V("접두어")),
           WAIT(1),
           CALL(finder_msg),
           IF(eq(V(pos_var), 0), WAIT(2), CALL(finder_msg))),
    ]


def LOAD_BLOB(lst, pos_var, blob_var):
    return [
        setv(blob_var, ""),
        IF(gt(V(pos_var), 0),
           setv("임시", item(lst, V(pos_var))),
           IF(gt(slen(V("임시")), slen(V("접두어"))),
              setv(blob_var, sub(V("임시"), plus(slen(V("접두어")), 1), slen(V("임시")))))),
    ]


# ---------------------------------------------------------------- 화면 (글상자)
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


def print_script():
    """출력문자열을 줄(¶)과 길이(CHUNK, 띄어쓰기 기준)로 나눠 말풍선 줄로 쌓는다. 최근 ROWS 줄만 남긴다."""
    return WHEN_MSG(
        "채팅에 출력",
        setv("출력남은", V("출력문자열")),
        UNTIL(empty(V("출력남은")),
              *SPLIT_LINE("출력남은", "출력줄", "출력위치"),
              setv("줄종류", V("출력종류")),
              IF(eq(V("출력종류"), "기록"),
                 ELIF_CHAIN((starts(V("출력줄"), "나: "), [setv("줄종류", "나"), CUT_HEAD("출력줄", 3)]),
                            (starts(V("출력줄"), "봇: "), [setv("줄종류", "봇"), CUT_HEAD("출력줄", 3)]),
                            otherwise=[setv("줄종류", "알림")])),
              UNTIL(empty(V("출력줄")),
                    IFELSE(gt(slen(V("출력줄")), CHUNK),
                           [setv("조각", sub(V("출력줄"), 1, CHUNK)),
                            # 조각의 마지막 공백이 뒤쪽 절반 안에 있으면 그 공백에서 줄을 바꾼다.
                            setv("끊을위치", find(reverse(V("조각")), " ")),
                            IFELSE(AND(gt(V("끊을위치"), 0), lt(V("끊을위치"), CHUNK // 2 + 1)),
                                   [setv("조각", sub(V("출력줄"), 1, minus(CHUNK, V("끊을위치")))),
                                    setv("출력줄", sub(V("출력줄"), minus(CHUNK + 2, V("끊을위치")), slen(V("출력줄"))))],
                                   [setv("출력줄", sub(V("출력줄"), CHUNK + 1, slen(V("출력줄"))))])],
                           [setv("조각", V("출력줄")), setv("출력줄", "")]),
                    append("화면글", V("조각")),
                    append("화면종류", V("줄종류")),
                    IF(gt(llen("화면글"), ROWS), remove("화면글", 1), remove("화면종류", 1)))),
        CALL("화면 그리기"),
    )


def thinking_scripts():
    return [
        WHEN_MSG("생각 표시",
                 append("화면글", "엔봇이 생각하는 중…"), append("화면종류", "생각"),
                 IF(gt(llen("화면글"), ROWS), remove("화면글", 1), remove("화면종류", 1)),
                 CALL("화면 그리기")),
        WHEN_MSG("생각 지우기",
                 IF(gt(llen("화면종류"), 0),
                    IF(eq(item("화면종류", llen("화면종류")), "생각"),
                       remove("화면글", llen("화면글")), remove("화면종류", llen("화면종류"))))),
        # '묻고 기다리기' 가 띄우는 말풍선은 지운다 (입력 안내는 글상자로 보여 준다)
        WHEN_MSG("말풍선 지우기", UNSAY()),
    ]


# ---------------------------------------------------------------- 메인
def main_script():
    return WHEN_START(
        HIDE_ANSWER(),
        clear("화면글"), clear("화면종류"), clear("후보답변"), clear("내질문"), clear("내답변"),
        clear("단어들"), clear("원단어들"),
        CALL("화면 그리기"),
        *STATUS("● 연결 중…"),
        setv("아이디", username()),
        setv("닉네임", nickname()),
        setv("기록블롭", ""), setv("기억블롭", ""), setv("기록위치", 0), setv("기억위치", 0),
        setv("대기질문", ""), setv("최근주제", ""), setv("지난기분", ""), setv("직전기분", ""), setv("기억변경", 0),
        setv("지난답변", ""),
        setv("주제", ""), setv("단어", ""), setv("키표시", ""), setv("값", ""),
        IFELSE(eq(slen(repl(V("아이디"), " ", "")), 0),
               [setv("로그인", 0), setv("저장가능", 0), setv("호칭", "방문자"),
                setv("템플릿", pick("말-환영손님"))],
               [setv("로그인", 1), setv("저장가능", 1),
                setv("호칭", V("닉네임")),
                IF(eq(slen(repl(V("호칭"), " ", "")), 0), setv("호칭", V("아이디"))),
                setv("접두어", join(V("아이디"), "|")),
                *STATUS("● 기억을 불러오는 중…"),
                CALL("사용자 데이터 불러오기"),
                ELIF_CHAIN(
                    (AND(empty(V("기록블롭")), eq(llen("내질문"), 0)), [setv("템플릿", pick("말-환영처음"))]),
                    (gt(slen(V("최근주제")), 0), [setv("주제", V("최근주제")), setv("템플릿", pick("말-환영주제"))]),
                    (eq(V("지난기분"), "나쁨"), [setv("템플릿", pick("말-환영기분"))]),
                    otherwise=[setv("템플릿", pick("말-환영"))]),
                IF(eq(V("저장가능"), 0),
                   *PRINT("저장 서버에 연결하지 못해서 이번 대화는 저장되지 않아요.", "알림"))]),
        setv("이번대기", ""),
        CALL("템플릿 채우기"),
        setv("대기질문", V("이번대기")),
        *PRINT(V("템플릿"), "봇"),
        *STATUS(join("● ", V("호칭"), "님과 대화 중")),
        setv("대화중", 1),
        UNTIL(eq(V("대화중"), 0),
              CAST("말풍선 지우기"),
              ASK("메시지를 입력하세요"),
              # 저장 형식과 템플릿 기호를 깨뜨리는 글자는 바꿔 둔다
              *TRIM_INTO("메시지", repl(repl(repl(repl(repl(answer(), SEP, " "), "[", "("), "]", ")"), "{", "("), "}", ")")),
              IF(gt(slen(V("메시지")), 0),
                 *PRINT(V("메시지"), "나"),
                 setv("저장할줄", join("나: ", V("메시지"))), CALL("기록에 추가"),
                 *STATUS("● 생각하는 중…"),
                 CALL("생각 표시"),
                 CALL("답변 만들기"),
                 CALL("생각 지우기"),
                 *PRINT(V("답변"), "봇"),
                 setv("저장할줄", join("봇: ", repl(V("답변"), SEP, " / "))), CALL("기록에 추가"),
                 CALL("기록 저장"),
                 IF(eq(V("기억변경"), 1), CALL("기억 저장"), setv("기억변경", 0)),
                 *STATUS(join("● ", V("호칭"), "님과 대화 중")))),
        *STATUS("● 대화 종료"),
    )


def trim_script():
    s = "공백정리"
    return WHEN_MSG(
        "공백 정리",
        FOREVER(
            IF(empty(V(s)), BREAK()),
            IF(NOT(eq(find(charat(V(s), 1), " "), 1)), BREAK()),
            CUT_HEAD(s, 1)),
        FOREVER(
            IF(empty(V(s)), BREAK()),
            IF(NOT(eq(find(charat(V(s), slen(V(s))), " "), 1)), BREAK()),
            CUT_TAIL(s, 1)),
    )


def load_script():
    return WHEN_MSG(
        "사용자 데이터 불러오기",
        *ENSURE_SLOT("대화기록", "기록위치", "기록 위치 찾기"),
        *ENSURE_SLOT("기억저장소", "기억위치", "기억 위치 찾기"),
        IF(OR(eq(V("기록위치"), 0), eq(V("기억위치"), 0)), setv("저장가능", 0)),
        *LOAD_BLOB("대화기록", "기록위치", "기록블롭"),
        *LOAD_BLOB("기억저장소", "기억위치", "기억블롭"),
        # 기억블롭 "키=값¶키=값¶" → 내질문 / 내답변 리스트
        setv("남은문자열", V("기억블롭")),
        UNTIL(empty(V("남은문자열")),
              *SPLIT_LINE("남은문자열", "줄", "위치"),
              setv("위치", find(V("줄"), "=")),
              IF(gt(V("위치"), 1),
                 IF(lt(V("위치"), slen(V("줄"))),
                    append("내질문", sub(V("줄"), 1, minus(V("위치"), 1))),
                    append("내답변", sub(V("줄"), plus(V("위치"), 1), slen(V("줄"))))))),
        # 지난번 대화 상태
        *SCAN("내질문", lambda: [
            ELIF_CHAIN((eq(item("내질문", V("불러k")), "#최근주제"), [setv("최근주제", item("내답변", V("불러k")))]),
                       (eq(item("내질문", V("불러k")), "#기분"), [setv("지난기분", item("내답변", V("불러k")))]),
                       (eq(item("내질문", V("불러k")), "내 이름"),
                        [setv("임시", item("내답변", V("불러k"))),
                         IF(starts(V("임시"), "F:"), CUT_HEAD("임시", 2), setv("호칭", V("임시")))]))], 3, k="불러k"),
        IF(gt(slen(V("기록블롭")), 0),
           *PRINT(join(f"── 지난 대화 ──{SEP}", V("기록블롭"), "── 이어서 이야기해요 ──"), "기록")),
    )


def storage_scripts():
    return [
        WHEN_MSG("기록 위치 찾기", *FIND_SLOT("대화기록", "기록위치")),
        WHEN_MSG("기억에서 찾기", *FIND_INDEX("내질문", V("찾을키"), "찾은키번호", "찾기k")),
        WHEN_MSG("기억 위치 찾기", *FIND_SLOT("기억저장소", "기억위치")),
        WHEN_MSG(
            "기록에 추가",
            setv("추가줄", V("저장할줄")),
            IF(gt(slen(V("추가줄")), MAX_LINE_LEN), setv("추가줄", join(sub(V("추가줄"), 1, MAX_LINE_LEN), "…"))),
            setv("기록블롭", join(V("기록블롭"), V("추가줄"), SEP)),
            UNTIL(lt(count(V("기록블롭"), SEP), MAX_HISTORY_LINES + 1),
                  setv("위치", find(V("기록블롭"), SEP)),
                  setv("기록블롭", sub(V("기록블롭"), plus(V("위치"), 1), slen(V("기록블롭")))))),
        WHEN_MSG("기록 저장", SAVE_SLOT("대화기록", "기록위치", "기록 위치 찾기", "기록블롭")),
        WHEN_MSG(
            "기억 저장",
            setv("기억블롭", ""),
            setv("묶음k", 1),
            REPEAT(llen("내질문"),
                   setv("기억블롭", join(V("기억블롭"), item("내질문", V("묶음k")), "=", item("내답변", V("묶음k")), SEP)),
                   chg("묶음k", 1)),
            SAVE_SLOT("기억저장소", "기억위치", "기억 위치 찾기", "기억블롭")),
        # 키 + 저장값 → 내 기억에 넣기 (같은 키가 있으면 바꾼다)
        WHEN_MSG(
            "사실 저장",
            setv("키", repl(V("키"), "=", " ")),
            setv("찾을키", V("키")), CALL("기억에서 찾기"), setv("저장번호", V("찾은키번호")),
            IFELSE(gt(V("저장번호"), 0),
                   [setitem("내답변", V("저장번호"), V("저장값"))],
                   [append("내질문", V("키")), append("내답변", V("저장값")),
                    IF(gt(llen("내질문"), MAX_MEMORIES), remove("내질문", 1), remove("내답변", 1))]),
            setv("기억변경", 1)),
        # 키 → 템플릿 (기억하고 있으면 대답, 모르면 물어보기)
        WHEN_MSG(
            "기억 꺼내기",
            setv("찾을키", V("키")), CALL("기억에서 찾기"), setv("꺼낸번호", V("찾은키번호")),
            CALL("키표시 만들기"),
            IFELSE(gt(V("꺼낸번호"), 0),
                   [setv("값", item("내답변", V("꺼낸번호"))),
                    IF(starts(V("값"), "F:"), CUT_HEAD("값", 2)),
                    IFELSE(eq(V("키"), "내 이름"), [setv("템플릿", pick("말-이름기억"))], [setv("템플릿", pick("말-기억답"))])],
                   [setv("템플릿", pick("말-모름내것")), setv("이번대기", join("사실:", V("키")))])),
        WHEN_MSG(
            "키표시 만들기",
            ELIF_CHAIN(
                (AND(starts(V("키"), "내가 "), gt(slen(V("키")), 3)),
                 [setv("키표시", join(V("호칭"), "님이 ", sub(V("키"), 4, slen(V("키")))))]),
                (AND(starts(V("키"), "내 "), gt(slen(V("키")), 2)),
                 [setv("키표시", join(V("호칭"), "님의 ", sub(V("키"), 3, slen(V("키")))))]),
                otherwise=[setv("키표시", V("키"))])),
    ]


# ---------------------------------------------------------------- 조사 · 템플릿
def josa_script():
    """조사단어 + 조사종류 → 조사결과 (받침에 맞춰 은/는, 이/가 … 를 붙인다)."""
    pairs = [IF(eq(V("조사종류"), kind),
                IFELSE(eq(V("받침"), 1), [setv("조사결과", join(V("조사단어"), a))], [setv("조사결과", join(V("조사단어"), b))]))
             for kind, (a, b) in D.JOSA.items()]
    return WHEN_MSG(
        "조사 붙이기",
        setv("조사결과", V("조사단어")),
        IF(gt(slen(V("조사단어")), 0),
           setv("조사끝", lower(charat(V("조사단어"), slen(V("조사단어"))))),
           setv("받침", 0),
           # 한글 음절(과 숫자)은 받침 없는 글자 모음에 없으면 받침이 있다
           IF(AND(NOT(lt(V("조사끝"), "가")), NOT(gt(V("조사끝"), "힣"))),
              IF(eq(find(V("글자-받침없음"), V("조사끝")), 0), setv("받침", 1))),
           IF(contains(D.LATIN_BATCHIM, V("조사끝")), setv("받침", 1)),
           IF(eq(V("조사종류"), "으로"), IF(contains(V("글자-ㄹ받침"), V("조사끝")), setv("받침", 0))),
           *pairs),
    )


def template_slots():
    """모든 문구에서 쓰인 {슬롯조사} 조합을 모은다."""
    texts = [t for _, t in D.TOPICS] + [t for _, t in D.INTENTS] + [t for _, t in D.DEFINITIONS]
    texts += [t for v in D.PHRASES.values() for t in v] + [t for _, t in D.STARTERS] + ["{단어은} "]
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


def template_script():
    combos, plain = template_slots()
    josa_steps = [IF(contains(V("템플릿"), "{" + base + kind + "}"),
                     setv("조사단어", V(D.SLOT_BASES[base])), setv("조사종류", kind), CALL("조사 붙이기"),
                     setv("템플릿", repl(V("템플릿"), "{" + base + kind + "}", V("조사결과"))))
                  for base, kind in combos]
    plain_steps = [IF(contains(V("템플릿"), "{" + base + "}"),
                      setv("템플릿", repl(V("템플릿"), "{" + base + "}", V(D.SLOT_BASES[base]))))
                   for base in plain]
    return WHEN_MSG(
        "템플릿 채우기",
        # [대기] 표시 → 이번대기, 문장에서는 지운다
        IF(contains(V("템플릿"), "["),
           setv("괄호A", find(V("템플릿"), "[")),
           setv("괄호B", find(V("템플릿"), "]")),
           IF(gt(V("괄호B"), plus(V("괄호A"), 1)),
              setv("이번대기", sub(V("템플릿"), plus(V("괄호A"), 1), minus(V("괄호B"), 1))),
              setv("임시", ""),
              IF(gt(V("괄호A"), 1), setv("임시", sub(V("템플릿"), 1, minus(V("괄호A"), 1)))),
              IF(lt(V("괄호B"), slen(V("템플릿"))),
                 setv("임시", join(V("임시"), sub(V("템플릿"), plus(V("괄호B"), 1), slen(V("템플릿")))))),
              *TRIM_INTO("템플릿", V("임시")))),
        *josa_steps,
        *plain_steps,
    )


# ---------------------------------------------------------------- 문장 분석
def analyze_script():
    m = lambda: V("정리메시지")
    q_cue = OR(contains(V("메시지"), "?"), *[contains(m(), c) for c in D.QUESTION_CUES])
    endings = "|" + "|".join(D.QUESTION_ENDINGS) + "|"
    cue_in = lambda var: OR(*[contains(V(var), c) for c in ["뭐", "뭔", "무엇", "알아", "알려", "설명", "누구", "어때", "?"]])
    verb = lambda: setv("서술종류", "동사")
    reflect = ELIF_CHAIN(
        (AND(eq(V("서끝2"), "어요"), contains(V("글자-ㅆ받침"), V("서앞2"))),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 2)), "군요")), verb()]),
        (AND(contains("어아다", V("서끝1")), contains(V("글자-ㅆ받침"), V("서앞1")), NOT(eq(V("서앞1"), "겠"))),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 1)), "군요")), verb()]),
        (OR(eq(V("서끝2"), "싶어"), eq(V("서끝2"), "싶다")),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 1)), "군요")), verb()]),
        (AND(eq(V("서끝2"), "에요"), eq(V("서앞2"), "이")),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 3)), "이군요"))]),
        (eq(V("서끝2"), "이야"), [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 2)), "이군요"))]),
        (eq(V("서끝2"), "예요"), [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 2)), "군요"))]),
        (AND(eq(V("서끝1"), "야"), contains(V("글자-받침없음"), V("서앞1")), NOT(contains("해가와봐돼줘서려니", V("서앞1")))),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 1)), "군요"))]),
        (AND(eq(V("서끝1"), "해"), included("형용사", sub(V("마지막절"), minus(V("서L"), 2), minus(V("서L"), 1)))),
         [setv("서술", join(sub(V("마지막절"), 1, minus(V("서L"), 1)), "하군요")), verb()]),
    )
    pronouns = ELIF_CHAIN(*[(AND(starts(V("서술"), p), gt(slen(V("서술")), len(p))),
                             [setv("서술", sub(V("서술"), len(p) + 1, slen(V("서술"))))])
                            for p in ["나는 ", "저는 ", "내가 ", "제가 ", "나 ", "난 ", "저 ", "전 ", "응 ", "어 ", "네 ",
                                      "음 ", "아 ", "근데 ", "그리고 "]])
    return WHEN_MSG(
        "문장 분석",
        setv("정리메시지", repl(lower(V("메시지")), " ", "")),
        # 끝의 문장 부호 · ㅋㅋ · ㅠㅠ 떼기
        setv("문장", V("메시지")),
        FOREVER(
            IF(empty(V("문장")), BREAK()),
            IF(eq(find("?!.~ㅋㅎㅠㅜ;,^", charat(V("문장"), slen(V("문장")))), 0), BREAK()),
            CUT_TAIL("문장", 1)),
        *TRIM_INTO("문장", V("문장")),
        # 질문인지
        setv("질문여부", 0),
        IF(q_cue, setv("질문여부", 1)),
        IF(gt(slen(V("문장")), 0), IF(contains("냐까", charat(V("문장"), slen(V("문장")))), setv("질문여부", 1))),
        IF(gt(slen(V("문장")), 1),
           IF(contains(endings, join("|", sub(V("문장"), minus(slen(V("문장")), 1), slen(V("문장"))), "|")),
              setv("질문여부", 1))),
        setv("뜻질문", 0),
        IF(OR(*[contains(m(), c) for c in D.DEFINITION_CUES]), setv("뜻질문", 1)),
        # 감정 점수
        setv("감정점수", 0),
        *SCAN("긍정어", lambda: [IF(contains(m(), item("긍정어", V("감정k"))), chg("감정점수", 1))], 6, k="감정k"),
        *SCAN("부정어", lambda: [IF(contains(m(), item("부정어", V("감정k"))), chg("감정점수", -1))], 6, k="감정k"),
        # 낱말 나누기 (원단어들) + 조사 떼기 (단어들)
        clear("원단어들"), clear("단어들"),
        setv("분석남은", join(V("문장"), " ")),
        UNTIL(empty(V("분석남은")),
              setv("분석위치", find(V("분석남은"), " ")),
              IF(gt(V("분석위치"), 1),
                 setv("단어원형", sub(V("분석남은"), 1, minus(V("분석위치"), 1))),
                 setv("단어원형", repl(repl(repl(repl(V("단어원형"), ",", ""), "'", ""), '"', ""), "…", "")),
                 IF(gt(slen(V("단어원형")), 0),
                    CALL("조사 떼기"),
                    append("원단어들", V("단어원형")),
                    append("단어들", V("어간")))),
              IFELSE(lt(V("분석위치"), slen(V("분석남은"))),
                     [setv("분석남은", sub(V("분석남은"), plus(V("분석위치"), 1), slen(V("분석남은"))))],
                     [setv("분석남은", "")])),
        # 주제(아는 주제 낱말 중 마지막 것), 후보주제(조사가 붙어 있던 첫 낱말), 단어(질문의 대상)
        setv("주제", ""), setv("후보주제", ""), setv("단어", ""), setv("내용어수", 0),
        setv("분석k", 1),
        REPEAT(llen("단어들"),
               setv("어간임시", item("단어들", V("분석k"))),
               IF(included("주제목록", V("어간임시")), setv("주제", V("어간임시"))),
               IF(AND(empty(V("후보주제")), gt(slen(V("어간임시")), 1)),
                  IF(NOT(included("불용어", V("어간임시"))),
                     IF(NOT(eq(item("원단어들", V("분석k")), V("어간임시"))), setv("후보주제", V("어간임시"))))),
               IF(gt(slen(V("어간임시")), 0),
                  IF(NOT(included("불용어", V("어간임시"))),
                     IF(NOT(cue_in("어간임시")),
                        chg("내용어수", 1),
                        IF(empty(V("단어")), setv("단어", V("어간임시")))))),
               chg("분석k", 1)),
        # 띄어 쓰지 않은 경우: 메시지 안에 들어 있는 가장 긴 주제
        IF(empty(V("주제")),
           setv("주제길이", 1),
           *SCAN("주제목록", lambda: [
               IF(gt(slen(item("주제목록", V("분석k"))), V("주제길이")),
                  IF(contains(m(), item("주제목록", V("분석k"))),
                     setv("주제", item("주제목록", V("분석k"))), setv("주제길이", slen(V("주제")))))], 8, k="분석k")),
        # 되받을 말: "시험 망쳤어" → "시험 망쳤군요" (여러 문장이면 마지막 문장만)
        setv("서술", ""), setv("서끝1", ""), setv("서술종류", ""),
        setv("마지막절", reverse(repl(repl(repl(V("문장"), "!", "|"), ".", "|"), "?", "|"))),
        IF(gt(find(V("마지막절"), "|"), 1),
           setv("마지막절", sub(V("마지막절"), 1, minus(find(V("마지막절"), "|"), 1)))),
        setv("마지막절", reverse(V("마지막절"))),
        *TRIM_INTO("마지막절", V("마지막절")),
        IF(AND(eq(V("질문여부"), 0), gt(slen(V("마지막절")), 2), lt(slen(V("마지막절")), 31)),
           setv("서L", slen(V("마지막절"))),
           setv("서끝1", charat(V("마지막절"), V("서L"))),
           setv("서앞1", charat(V("마지막절"), minus(V("서L"), 1))),
           setv("서끝2", sub(V("마지막절"), minus(V("서L"), 1), V("서L"))),
           setv("서앞2", charat(V("마지막절"), minus(V("서L"), 2))),
           reflect,
           IF(gt(slen(V("서술")), 0),
              pronouns,
              setv("서술", repl(repl(join(" ", V("서술")), " 내 ", " {이름}님 "), " 제 ", " {이름}님 ")),
              CUT_HEAD("서술", 1))),
    )


def strip_josa_script():
    """단어원형 → 어간 (뒤에 붙은 조사를 뗀다. 아는 주제 낱말은 그대로 둔다)."""
    w_ = lambda: V("단어원형")
    L = lambda: V("떼기길이")
    return WHEN_MSG(
        "조사 떼기",
        setv("어간", w_()),
        setv("떼기길이", slen(w_())),
        IF(NOT(included("주제목록", w_())),
           setv("떼기완료", 0),
           IF(gt(L(), 3),
              IF(included("조사목록", sub(w_(), minus(L(), 2), L())),
                 setv("어간", sub(w_(), 1, minus(L(), 3))), setv("떼기완료", 1))),
           IF(AND(eq(V("떼기완료"), 0), gt(L(), 2)),
              IF(included("조사목록", sub(w_(), minus(L(), 1), L())),
                 setv("어간", sub(w_(), 1, minus(L(), 2))), setv("떼기완료", 1))),
           IF(AND(eq(V("떼기완료"), 0), gt(L(), 1)),
              IF(included("조사목록", charat(w_(), L())),
                 setv("어간", sub(w_(), 1, minus(L(), 1)))))),
    )


def clean_value_script():
    """값(사용자 대답)에서 앞의 군말과 끝의 '이야/예요/입니다…' 를 떼어 낸다."""
    tails = ["이랍니다", "입니다", "이에요", "이예요", "예요", "이야", "이요", "이지", "이다", "이라고", "라고", "잖아",
             "야", "요", "임", "지"]
    heads = ["음… ", "음 ", "그건 ", "그거 ", "아 ", "어 ", "흠 ", "글쎄 ", "그냥 ", "딱히 ", "음.. "]
    padded = lambda: join("    ", V("값"))
    tail = lambda n: sub(padded(), minus(plus(slen(V("값")), 4), n - 1), plus(slen(V("값")), 4))
    return WHEN_MSG(
        "값 다듬기",
        *TRIM_INTO("값", V("값")),
        *[IF(starts(V("값"), h), CUT_HEAD("값", len(h))) for h in heads],
        *[setv(f"값끝{n}", tail(n)) for n in range(1, 5)],
        ELIF_CHAIN(*[(AND(eq(V(f"값끝{len(t)}"), t), gt(slen(V("값")), len(t))), [CUT_TAIL("값", len(t))])
                     for t in tails]),
        *TRIM_INTO("값", V("값")),
    )


# ---------------------------------------------------------------- 이야기 속 사실 찾기
def facts_script():
    """질문이 아닌 말에서 '내 X는 Y', 이름, 좋아하는 것/싫어하는 것, 나이를 찾아 기억한다."""
    raw = lambda i: item("원단어들", i)
    stem = lambda i: item("단어들", i)
    my = lambda: OR(eq(raw(1), "내"), eq(raw(1), "제"), eq(raw(1), "나의"), eq(raw(1), "내가"), eq(raw(1), "제가"))

    def like_rule(trigger_words, key, phrase):
        """좋아해/싫어해 낱말 앞의 가장 가까운 '불용어 아닌 낱말'을 대상으로 기억한다."""
        has = OR(*[contains(V("정리메시지"), t) for t in trigger_words])
        return IF(eq(V("사실찾음"), 0), IF(AND(has, NOT(contains(V("정리메시지"), "안" + trigger_words[0][:2]))),
            setv("동사번호", 0),
            *SCAN("원단어들", lambda: [IF(OR(*[starts(raw(V("사실k")), t[:2]) for t in trigger_words]),
                                         setv("동사번호", V("사실k")), BREAK())], 4, k="사실k"),
            setv("단어", ""),
            setv("거꼴", 0),
            IF(gt(V("동사번호"), 1), IF(OR(eq(raw(minus(V("동사번호"), 1)), "거"), eq(raw(minus(V("동사번호"), 1)), "것")),
                                       setv("거꼴", 1))),
            IFELSE(eq(V("거꼴"), 1),
                   # "그림 그리는 거" 처럼 '~하는 거' 는 앞의 말을 통째로
                   [setv("사실j", 1), IF(included("불용어", raw(1)), setv("사실j", 2)),
                    REPEAT(minus(V("동사번호"), V("사실j")),
                           setv("단어", join(V("단어"), " ", raw(V("사실j")))), chg("사실j", 1)),
                    *TRIM_INTO("단어", V("단어"))],
                   [setv("사실j", minus(V("동사번호"), 1)),
                    UNTIL(lt(V("사실j"), 1),
                          IF(NOT(included("불용어", stem(V("사실j")))),
                             IF(gt(slen(stem(V("사실j"))), 0), setv("단어", stem(V("사실j"))), BREAK())),
                          chg("사실j", -1))]),
            IF(gt(slen(V("단어")), 0),
               setv("키", key),
               setv("찾을키", V("키")), CALL("기억에서 찾기"), setv("사실번호", V("찾은키번호")),
               setv("값", V("단어")),
               IF(gt(V("사실번호"), 0),
                  setv("임시", item("내답변", V("사실번호"))),
                  IF(starts(V("임시"), "F:"), CUT_HEAD("임시", 2)),
                  IFELSE(contains(V("임시"), V("단어")), [setv("값", V("임시"))],
                         [setv("값", join(V("임시"), ", ", V("단어")))]),
                  IF(gt(slen(V("값")), 60), setv("값", V("단어")))),
               setv("저장값", join("F:", V("값"))), CALL("사실 저장"),
               setv("템플릿", pick(phrase)),
               IF(included("주제목록", V("단어")),
                  setv("주제", V("단어")), CALL("주제질문 찾기"),
                  setv("템플릿", join(V("템플릿"), " ", V("주제질문")))),
               setv("사실찾음", 1))))

    return WHEN_MSG(
        "사실 찾기",
        setv("사실찾음", 0),
        # 내 이름은 X
        IF(gt(llen("원단어들"), 2),
           IF(AND(my(), OR(eq(raw(2), "이름은"), eq(raw(2), "이름이"))),
              setv("값", ""),
              setv("사실j", 3),
              REPEAT(minus(llen("원단어들"), 2),
                     setv("값", join(V("값"), " ", raw(V("사실j")))), chg("사실j", 1)),
              CALL("값 다듬기"),
              IF(AND(gt(slen(V("값")), 0), lt(slen(V("값")), 16)),
                 setv("키", "내 이름"), setv("저장값", join("F:", V("값"))), CALL("사실 저장"),
                 setv("호칭", V("값")),
                 setv("템플릿", pick("말-이름저장")),
                 setv("사실찾음", 1)))),
        # 내 X는 Y
        IF(eq(V("사실찾음"), 0), IF(gt(llen("원단어들"), 2), IF(my(),
           setv("끝번호", 0),
           setv("사실j", 2),
           REPEAT(minus(llen("원단어들"), 2),
                  IF(AND(gt(slen(raw(V("사실j"))), 1), contains("은는", charat(raw(V("사실j")), slen(raw(V("사실j")))))),
                     setv("끝번호", V("사실j")), BREAK()),
                  chg("사실j", 1)),
           IF(gt(V("끝번호"), 1),
              setv("키", "내"), IF(OR(eq(raw(1), "내가"), eq(raw(1), "제가")), setv("키", "내가")),
              setv("사실j", 2),
              REPEAT(minus(V("끝번호"), 1), setv("키", join(V("키"), " ", stem(V("사실j")))), chg("사실j", 1)),
              setv("값", ""), setv("사실j", plus(V("끝번호"), 1)),
              REPEAT(minus(llen("원단어들"), V("끝번호")),
                     setv("값", join(V("값"), " ", raw(V("사실j")))), chg("사실j", 1)),
              CALL("값 다듬기"),
              IF(AND(gt(slen(V("값")), 0), lt(slen(V("값")), 41)),
                 setv("저장값", join("F:", V("값"))), CALL("사실 저장"),
                 CALL("키표시 만들기"),
                 setv("템플릿", pick("말-사실저장")),
                 setv("사실찾음", 1)))))),
        like_rule(["좋아해", "좋아함", "좋아한다", "좋아하거든", "좋아하는데"], "내가 좋아하는 것", "말-좋아저장"),
        like_rule(["싫어해", "싫어함", "싫어한다", "싫어하거든", "싫어하는데"], "내가 싫어하는 것", "말-싫어저장"),
        # N살
        IF(eq(V("사실찾음"), 0),
           *SCAN("원단어들", lambda: [
               setv("임시", raw(V("사실k"))),
               IF(gt(find(V("임시"), "살"), 1),
                  setv("임시", sub(V("임시"), 1, minus(find(V("임시"), "살"), 1))),
                  IF(eq(V("임시"), minus(V("임시"), 0)),
                     setv("키", "내 나이"), setv("값", join(V("임시"), "살")),
                     setv("저장값", join("F:", V("값"))), CALL("사실 저장"),
                     setv("템플릿", pick("말-나이저장")), setv("사실찾음", 1), BREAK()))], 4, k="사실k")),
    )


def topic_question_script():
    return WHEN_MSG(
        "주제질문 찾기",
        *FIND_INDEX("주제목록", V("주제"), "주제번호", "주제k"),
        setv("주제질문", ""), setv("주제질문대체", 0),
        IF(gt(V("주제번호"), 0), setv("주제질문", item("주제질문목록", V("주제번호")))),
        # 이미 알고 있는 걸 묻는 질문이면 다른 말로 바꾼다
        IF(contains(V("주제질문"), "[사실:"),
           setv("괄호A", find(V("주제질문"), "[사실:")), setv("괄호B", find(V("주제질문"), "]")),
           IF(gt(V("괄호B"), plus(V("괄호A"), 4)),
              IF(included("내질문", sub(V("주제질문"), plus(V("괄호A"), 4), minus(V("괄호B"), 1))),
                 setv("주제질문", pick("말-주제더")), setv("주제질문대체", 1)))),
    )


def connect_script():
    """말 속에 내가 기억하는 값(예: 고양이 이름 '나비')이 있으면 알아보고 앞에 붙일 말을 만든다."""
    return WHEN_MSG(
        "기억 연결",
        setv("아는이름", ""), setv("아는키", ""), setv("연결말", ""),
        *SCAN("내답변", lambda: [
            setv("연결값", item("내답변", V("연결k"))),
            IF(starts(V("연결값"), "F:"),
               CUT_HEAD("연결값", 2),
               IF(AND(gt(slen(V("연결값")), 0), included("단어들", V("연결값"))),
                  setv("아는이름", V("연결값")), setv("아는키", item("내질문", V("연결k"))), BREAK()))], 4, k="연결k"),
        IF(gt(slen(V("아는이름")), 0),
           IFELSE(AND(starts(V("아는키"), "내 "), ends("아는키", " 이름"), gt(slen(V("아는키")), 5)),
                  [setv("연결대상", sub(V("아는키"), 3, minus(slen(V("아는키")), 3))),
                   setv("연결말", join("{이름}님의 ", V("연결대상"), " ", V("아는이름"), " 말이죠? ")),
                   IF(included("주제목록", V("연결대상")), setv("주제", V("연결대상")))],
                  [setv("키", V("아는키")), CALL("키표시 만들기"),
                   setv("조사단어", V("키표시")), setv("조사종류", "이잖아요"), CALL("조사 붙이기"),
                   setv("연결말", join(V("아는이름"), "! ", V("조사결과"), ". "))])),
    )


def starter_script():
    """아직 모르는 것 하나를 골라 템플릿 뒤에 질문으로 붙인다."""
    return WHEN_MSG(
        "질문 고르기",
        setv("시작번호", rand(1, llen("시작키"))),
        setv("시작찾음", 0),
        REPEAT(llen("시작키"),
               IF(NOT(included("내질문", item("시작키", V("시작번호")))),
                  setv("템플릿", join(V("템플릿"), " ", item("시작질문", V("시작번호")))),
                  setv("이번대기", join("사실:", item("시작키", V("시작번호")))),
                  setv("시작찾음", 1), BREAK()),
               setv("시작번호", plus(mod(V("시작번호"), llen("시작키")), 1))),
        IF(eq(V("시작찾음"), 0), setv("템플릿", join(V("템플릿"), " ", pick("말-이야기거리")))),
    )


# ---------------------------------------------------------------- 답변 만들기
HELP = SEP.join([
    "편하게 이야기해 보세요! 저는 이렇게 생각해요.",
    "· 문장에서 주제와 감정을 찾아 공감하고 되물어요",
    "· '내 생일은 3월 14일이야', '나 축구 좋아해' 같은 말을 기억해요",
    "· 모르는 건 물어보고, 알려 주면 배워요",
    "· 다시 오면 지난 이야기를 이어 가요",
    "명령어: 기억 목록 · 나에 대해 알아? · 잊어줘: 내 생일",
    "번역: 문장 · 한국어로: sentence · 계산: 12*3",
    "몇 시야? · 새 대화 · 종료",
])
TEACH_FORMAT = "이렇게 입력해 주세요 → 기억해: 질문 = 답 (예: 기억해: 내 별명 = 꼬마)"


def reply_script():
    m = lambda: V("정리메시지")
    cmd = lambda *names: OR(*[eq(V("명령"), n) for n in names])
    is_q = lambda: eq(V("질문여부"), 1)
    not_q = lambda: eq(V("질문여부"), 0)

    teach = [
        setv("위치", find(V("내용"), "=")),
        IFELSE(AND(gt(V("위치"), 1), lt(V("위치"), slen(V("내용")))),
               [*TRIM_INTO("키", sub(V("내용"), 1, minus(V("위치"), 1))),
                *TRIM_INTO("저장값", sub(V("내용"), plus(V("위치"), 1), slen(V("내용")))),
                IFELSE(OR(empty(V("키")), empty(V("저장값"))),
                       [setv("답변", TEACH_FORMAT)],
                       [IF(gt(slen(V("키")), 40), setv("키", sub(V("키"), 1, 40))),
                        IF(gt(slen(V("저장값")), 100), setv("저장값", sub(V("저장값"), 1, 100))),
                        CALL("사실 저장"),
                        setv("답변", join("알겠어요! 앞으로 '", V("키"), "'(이)라고 물으면 '",
                                          V("저장값"), "'(이)라고 답할게요.")),
                        IF(eq(V("저장가능"), 0),
                           setv("답변", join(V("답변"), " (저장되지 않는 상태라 이번 실행에서만 기억해요.)")))])],
               [setv("답변", TEACH_FORMAT)]),
    ]
    forget = [
        IFELSE(empty(V("내용")),
               [setv("답변", "이렇게 입력해 주세요 → 잊어줘: 내 생일")],
               [setv("찾을키", V("내용")), CALL("기억에서 찾기"), setv("찾은번호", V("찾은키번호")),
                IFELSE(gt(V("찾은번호"), 0),
                       [remove("내질문", V("찾은번호")), remove("내답변", V("찾은번호")), setv("기억변경", 1),
                        setv("답변", join("'", V("내용"), "'에 대한 기억을 지웠어요."))],
                       [setv("답변", join("'", V("내용"), "'(이)라는 기억은 없어요. '기억 목록'으로 확인해 보세요."))])]),
    ]
    shown_key = lambda i: item("내질문", i)
    memory_list = [
        setv("답변", ""), setv("요약수", 0),
        *SCAN("내질문", lambda: [IF(NOT(starts(shown_key(V("답k")), "#")),
                                   setv("값", item("내답변", V("답k"))), IF(starts(V("값"), "F:"), CUT_HEAD("값", 2)),
                                   setv("답변", join(V("답변"), SEP, "· ", shown_key(V("답k")), " → ", V("값"))),
                                   chg("요약수", 1))], 3, k="답k"),
        IFELSE(eq(V("요약수"), 0),
               [setv("답변", "아직 기억하고 있는 게 없어요. 이야기를 들려주면 하나씩 기억할게요!")],
               [setv("답변", join("기억하고 있는 것 ", V("요약수"), "개예요.", V("답변")))]),
    ]
    about_me = [
        setv("템플릿", "제가 기억하는 {이름}님은요:"), setv("요약수", 0),
        *SCAN("내질문", lambda: [IF(AND(starts(item("내답변", V("답k")), "F:"), lt(V("요약수"), 6)),
                                   setv("키", item("내질문", V("답k"))), setv("값", item("내답변", V("답k"))),
                                   CUT_HEAD("값", 2),
                                   IF(starts(V("키"), "내가 "), CUT_HEAD("키", 3)),
                                   IF(starts(V("키"), "내 "), CUT_HEAD("키", 2)),
                                   setv("템플릿", join(V("템플릿"), SEP, "· ", V("키"), " → ", V("값"))),
                                   chg("요약수", 1))], 3, k="답k"),
        IF(eq(V("요약수"), 0),
           setv("템플릿", "아직 {이름}님에 대해 아는 게 많지 않아요. 이야기를 들려주면 하나씩 기억할게요! [이야기]")),
    ]
    # 기억에서 찾기: 기억해:로 가르친 것은 어디에 들어 있든, 이야기에서 배운 사실(F:)은
    # '내 X' 처럼 띄어 쓴 키면 문장 안에, 한 낱말 키면 낱말로 들어 있을 때만 찾는다.
    memory_match = [
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
    ]
    def_cue = lambda: eq(V("뜻질문"), 1)
    intent_match = [
        clear("후보답변"), setv("최장길이", 0),
        *SCAN("의도키워드", lambda: [
            IF(contains(m(), item("의도키워드", V("답k"))),
               IF(NOT(lt(slen(item("의도키워드", V("답k"))), V("최장길이"))),
                  IF(gt(slen(item("의도키워드", V("답k"))), V("최장길이")),
                     clear("후보답변"), setv("최장길이", slen(item("의도키워드", V("답k"))))),
                  append("후보답변", item("의도답변", V("답k")))))], 6, k="답k"),
    ]
    feeling = lambda neg: [
        setv("연결허용", 1),
        ELIF_CHAIN((gt(slen(V("서술")), 0),
                    [setv("템플릿", join(V("서술"), ". ", pick("말-공감부정뒤" if neg else "말-공감긍정뒤")))]),
                   (gt(slen(V("주제")), 0), [setv("템플릿", pick("말-공감부정주제" if neg else "말-공감긍정주제"))]),
                   otherwise=[setv("템플릿", pick("말-공감부정" if neg else "말-공감긍정"))]),
        CALL("주제질문 찾기"),
        IFELSE(AND(gt(slen(V("주제질문")), 0), eq(rand(1, 2), 1), *([eq(V("주제질문대체"), 0)] if neg else [])),
               [setv("템플릿", join(V("템플릿"), " ", V("주제질문")))],
               [setv("템플릿", join(V("템플릿"), " ", pick("말-이어묻기부정" if neg else "말-이어묻기긍정")))]),
        setv("새기분", "나쁨" if neg else "좋음"),
    ]
    worry = [
        setv("연결허용", 1),
        IFELSE(gt(slen(V("주제")), 0), [setv("템플릿", pick("말-걱정주제"))], [setv("템플릿", pick("말-걱정"))]),
        setv("템플릿", join(V("템플릿"), " ", pick("말-이어묻기걱정"))),
        setv("새기분", "나쁨"),
    ]

    return WHEN_MSG(
        "답변 만들기",
        setv("답변", ""), setv("템플릿", ""), setv("처리됨", 0), setv("이번대기", ""), setv("새기분", ""),
        setv("지난대기", V("대기질문")), setv("대기질문", ""),
        clear("후보답변"),
        CALL("문장 분석"),
        setv("연결허용", 0),
        CALL("기억 연결"),
        # "명령: 내용" 나누기
        setv("명령", ""), setv("내용", ""),
        setv("위치", find(V("메시지"), ":")),
        IF(gt(V("위치"), 1),
           setv("명령", repl(sub(V("메시지"), 1, minus(V("위치"), 1)), " ", "")),
           IF(lt(V("위치"), slen(V("메시지"))),
              *TRIM_INTO("내용", sub(V("메시지"), plus(V("위치"), 1), slen(V("메시지")))))),
        # ---- 명령
        BRANCH(OR(starts(m(), "도움말"), eq(m(), "help"), eq(m(), "?")), setv("답변", HELP)),
        BRANCH(cmd("기억해", "가르치기", "기억"), *teach),
        BRANCH(cmd("잊어줘", "잊어", "삭제"), *forget),
        BRANCH(cmd("번역", "영어로", "영어"),
               IFELSE(empty(V("내용")),
                      [setv("답변", "번역할 문장도 같이 입력해 주세요. 예) 번역: 오늘 날씨가 좋아요")],
                      [setv("답변", join("영어로는 이렇게 말해요 → ", translate("ko", V("내용"), "en")))])),
        BRANCH(cmd("한국어로", "한글로", "한국어"),
               IFELSE(empty(V("내용")),
                      [setv("답변", "번역할 영어 문장도 같이 입력해 주세요. 예) 한국어로: Nice to meet you")],
                      [setv("답변", join("한국어로는 이렇게 말해요 → ", translate("en", V("내용"), "ko")))])),
        BRANCH(cmd("계산", "계산해줘", "계산해"),
               setv("식", repl(repl(repl(repl(V("내용"), " ", ""), "×", "*"), "÷", "/"), "x", "*")),
               CALL("계산하기"),
               setv("답변", V("결과"))),
        BRANCH(OR(eq(m(), "기억목록"), eq(m(), "기억보기")), *memory_list),
        BRANCH(OR(eq(m(), "새대화"), eq(m(), "초기화"), eq(m(), "기록삭제")),
               setv("기록블롭", ""),
               clear("화면글"), clear("화면종류"),
               setv("답변", "대화 기록을 지웠어요. 새로 시작해요! (기억하고 있는 건 그대로예요.)")),
        BRANCH(OR(eq(m(), "종료"), eq(m(), "그만"), eq(m(), "끝"), eq(m(), "bye")),
               setv("대화중", 0),
               setv("템플릿", "오늘 이야기 즐거웠어요, {이름}님! 다시 이야기하려면 시작 버튼을 눌러 주세요.")),
        # ---- 직전에 내가 물어본 것에 대한 대답이면 기억한다
        BRANCH(AND(starts(V("지난대기"), "사실:"), not_q(), empty(V("명령")), lt(slen(V("문장")), 26),
                   lt(llen("원단어들"), 5), NOT(eq(V("서술종류"), "동사")),
                   NOT(OR(*[contains(m(), w_) for w_ in D.SOCIAL]))),
               setv("키", sub(join(V("지난대기"), " "), 4, slen(V("지난대기")))),
               IFELSE(OR(*[contains(m(), d) for d in D.DONT_KNOW]),
                      [setv("템플릿", pick("말-몰라"))],
                      [setv("값", V("문장")),
                       # "이름은 초코야" 처럼 키의 낱말을 다시 말하면 떼어 낸다
                       IF(gt(llen("원단어들"), 1),
                          IF(AND(contains("은는이가", charat(item("원단어들", 1), slen(item("원단어들", 1)))),
                                 contains(V("키"), item("단어들", 1))),
                             CUT_HEAD("값", slen(item("원단어들", 1))))),
                       CALL("값 다듬기"),
                       IFELSE(OR(empty(V("값")), included("모름말", V("값"))),
                              [setv("템플릿", pick("말-몰라"))],
                              [setv("저장값", join("F:", V("값"))), CALL("사실 저장"), CALL("키표시 만들기"),
                               IF(eq(V("키"), "내 이름"), setv("호칭", V("값"))),
                               IFELSE(starts(V("키"), "내"), [setv("템플릿", pick("말-사실저장"))],
                                      [setv("템플릿", pick("말-새지식"))])])])),
        BRANCH(AND(starts(V("지난대기"), "답:"), not_q(), empty(V("명령"))),
               setv("키", sub(join(V("지난대기"), " "), 3, slen(V("지난대기")))),
               setv("저장값", V("메시지")), CALL("사실 저장"),
               setv("템플릿", pick("말-질문배움"))),
        # ---- 이야기 속 사실 기억하기
        IF(eq(V("처리됨"), 0), IF(AND(not_q(), empty(V("명령"))),
                                CALL("사실 찾기"),
                                IF(eq(V("사실찾음"), 1), setv("처리됨", 1)))),
        # ---- 기억에서 찾기
        *memory_match,
        # 이야기에서 배운 사실(F:)은 질문일 때만 꺼내고, 기억해:로 가르친 답은 그대로 말한다
        setv("기억응답", 0),
        IF(gt(V("찾은번호"), 0),
           IFELSE(starts(item("내답변", V("찾은번호")), "F:"),
                  [IF(is_q(), setv("기억응답", 1))], [setv("기억응답", 2)])),
        BRANCH(eq(V("기억응답"), 1), setv("키", item("내질문", V("찾은번호"))), CALL("기억 꺼내기")),
        BRANCH(eq(V("기억응답"), 2), setv("답변", item("내답변", V("찾은번호")))),
        BRANCH(AND(is_q(), contains(m(), "이름"),
                   OR(starts(m(), "이름"), *[eq(item("원단어들", 1), y) for y in D.YOU_WORDS], starts(m(), "네이름"))),
               setv("템플릿", pick("말-봇이름")), guard=gt(llen("원단어들"), 0)),
        *[BRANCH(contains(m(), cue),
                 setv("키", key), CALL("기억 꺼내기"),
                 *([IF(eq(V("꺼낸번호"), 0), setv("템플릿", pick("말-내이름")), setv("이번대기", ""))] if key == "내 이름" else []),
                 guard=AND(is_q(), OR(contains(m(), "라고했"), contains(m(), "기억"), starts(m(), "내"), starts(m(), "나"),
                                      starts(m(), "제")),
                           NOT(OR(starts(m(), "너"), starts(m(), "넌"), starts(m(), "니")))))
          for cue, key in D.RECALL_ALIASES],
        BRANCH(AND(is_q(), contains(m(), "좋아"), OR(starts(m(), "내가"), starts(m(), "나뭐"), starts(m(), "난뭐"))),
               setv("키", "내가 좋아하는 것"), CALL("기억 꺼내기")),
        BRANCH(AND(is_q(), contains(m(), "싫어"), OR(starts(m(), "내가"), starts(m(), "나뭐"), starts(m(), "난뭐"))),
               setv("키", "내가 싫어하는 것"), CALL("기억 꺼내기")),
        BRANCH(OR(contains(m(), "나에대해"), contains(m(), "나에관해"), contains(m(), "나를기억"), contains(m(), "나기억해"),
                  contains(m(), "내정보")), *about_me),
        BRANCH(AND(OR(eq(item("원단어들", 1), "내"), eq(item("원단어들", 1), "제"), eq(item("원단어들", 1), "나의")),
                   NOT(included("불용어", item("단어들", 2)))),
               setv("키", join("내 ", item("단어들", 2))), CALL("기억 꺼내기"),
               guard=AND(is_q(), gt(llen("원단어들"), 1))),
        # ---- 단어 뜻
        BRANCH(AND(is_q(), def_cue(), included("정의단어", lower(V("단어")))),
               *FIND_INDEX("정의단어", lower(V("단어")), "정의번호", "답k"),
               setv("템플릿", join("{단어은} ", item("정의설명", V("정의번호"))))),
        # ---- 시간 · 날짜
        BRANCH(OR(contains(m(), "몇시"), contains(m(), "지금시간"), contains(m(), "현재시간")),
               setv("답변", join("지금은 ", date("HOUR"), "시 ", date("MINUTE"), "분이에요."))),
        BRANCH(OR(contains(m(), "며칠"), contains(m(), "날짜"), contains(m(), "무슨요일"), contains(m(), "몇월")),
               setv("답변", join("오늘은 ", date("YEAR"), "년 ", date("MONTH"), "월 ", date("DAY"), "일 ",
                                 item("요일", plus(date("DAY_OF_WEEK"), 1)), "요일이에요."))),
        # ---- 일상 대화 (질문이거나, 짧거나, 주제·감정이 없는 말일 때)
        IF(eq(V("처리됨"), 0), IF(OR(is_q(), lt(slen(m()), 9), AND(empty(V("주제")), eq(V("감정점수"), 0))),
                                *intent_match)),
        BRANCH(gt(llen("후보답변"), 0), setv("템플릿", pick("후보답변")),
               guard=OR(is_q(), lt(slen(m()), 9), AND(empty(V("주제")), eq(V("감정점수"), 0)))),
        # ---- 나(엔봇)에 대한 질문
        BRANCH(AND(is_q(), OR(*[eq(item("원단어들", 1), y) for y in D.YOU_WORDS])),
               setv("템플릿", pick("말-너질문")), guard=gt(llen("원단어들"), 0)),
        # ---- 모르는 단어는 물어보고 배운다 (낱말 하나에 대한 질문일 때)
        BRANCH(AND(is_q(), def_cue(), gt(slen(V("단어")), 0), eq(V("내용어수"), 1)),
               setv("템플릿", pick("말-모르는단어")), setv("이번대기", join("사실:", V("단어")))),
        # ---- 정보를 묻는 질문인데 모르면 답을 배운다 ("우리 학교 이름이 뭐게?")
        BRANCH(AND(is_q(), OR(*[contains(m(), c) for c in D.INFO_CUES]), lt(slen(V("문장")), 41)),
               setv("템플릿", pick("말-모르는질문")), setv("이번대기", join("답:", V("문장")))),
        # ---- 감정에 공감하기
        BRANCH(AND(not_q(), OR(*[contains(m(), wd) for wd in D.WORRY])), *worry),
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
              AND(eq(V("직전기분"), "나쁨"), OR(ends("문장", "다고"), ends("문장", "라고"))),
              AND(eq(V("직전기분"), "나쁨"), gt(slen(V("서술")), 0), NOT(gt(V("감정점수"), 0)),
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
        BRANCH(AND(not_q(), lt(V("감정점수"), 0)), *feeling(True)),
        BRANCH(AND(not_q(), gt(V("감정점수"), 0)), *feeling(False)),
        BRANCH(AND(eq(V("지난대기"), "기분"), not_q(), lt(slen(V("문장")), 9), empty(V("주제")), empty(V("서술"))),
               IFELSE(included("예말", m()), [setv("템플릿", pick("말-기분응"))], [setv("템플릿", pick("말-기분보통"))])),
        BRANCH(AND(is_q(), OR(ends("문장", "할까"), ends("문장", "될까"), ends("문장", "갈까"), ends("문장", "까요"))),
               setv("템플릿", pick("말-고민질문"))),
        # ---- 주제 이어 가기 / 되받기
        BRANCH(gt(slen(V("주제")), 0),
               CALL("주제질문 찾기"),
               setv("연결허용", 1),
               IFELSE(gt(slen(V("서술")), 0), [setv("템플릿", join(V("서술"), "!"))], [setv("템플릿", pick("말-주제반응"))]),
               setv("템플릿", join(V("템플릿"), " ", V("주제질문")))),
        BRANCH(gt(slen(V("서술")), 0), setv("연결허용", 1), setv("템플릿", join(V("서술"), "! ", pick("말-되묻기")))),
        # ---- 모르는 질문은 답을 배운다
        BRANCH(is_q(),
               setv("템플릿", pick("말-모르는질문")),
               IF(lt(slen(V("문장")), 41), setv("이번대기", join("답:", V("문장"))))),
        # ---- 짧은 대답 ("양념", "건축") 은 받아 주고 이어 간다
        setv("짧은값", ""),
        IF(eq(V("처리됨"), 0), setv("값", V("문장")), CALL("값 다듬기"), setv("짧은값", V("값"))),
        BRANCH(AND(OR(eq(V("지난대기"), "이야기"), eq(V("지난대기"), "이유"), eq(V("지난대기"), "기분")), not_q(),
                   gt(slen(V("짧은값")), 0), lt(slen(V("짧은값")), 13), NOT(included("모름말", V("짧은값")))),
               setv("단어", V("짧은값")), setv("연결허용", 1), setv("템플릿", pick("말-짧은대답")),
               IF(eq(rand(1, 2), 1), CALL("질문 고르기"))),
        # ---- 이야기를 들어 주고, 대화가 끊기면 먼저 묻기
        BRANCH(OR(eq(V("지난대기"), "이유"), eq(V("지난대기"), "이야기")),
               setv("연결허용", 1), setv("템플릿", pick("말-들어줌")),
               IF(eq(rand(1, 2), 1), CALL("질문 고르기"))),
        BRANCH(gt(slen(V("후보주제")), 1), setv("단어", V("후보주제")), setv("템플릿", pick("말-후보반응"))),
        BRANCH(eq(V("직전기분"), "나쁨"), setv("템플릿", pick("말-위로마무리"))),
        BRANCH(eq(1, 1), setv("템플릿", pick("말-맞장구")), CALL("질문 고르기")),
        # ---- 마무리: 템플릿 → 답변, 대화 상태 저장
        IF(AND(eq(V("연결허용"), 1), gt(slen(V("연결말")), 0), gt(slen(V("템플릿")), 0)),
           setv("템플릿", join(V("연결말"), V("템플릿")))),
        IF(gt(slen(V("템플릿")), 0), CALL("템플릿 채우기"), setv("답변", V("템플릿"))),
        IF(empty(V("답변")), setv("답변", "음… 다시 한번 말해 줄래요?")),
        # 바로 전과 똑같은 대답은 하지 않는다
        IF(eq(V("답변"), V("지난답변")),
           setv("이번대기", ""), setv("템플릿", pick("말-맞장구")), CALL("질문 고르기"), CALL("템플릿 채우기"),
           setv("답변", V("템플릿"))),
        setv("지난답변", V("답변")),
        setv("직전기분", V("새기분")),
        setv("대기질문", V("이번대기")),
        IF(AND(eq(V("연결허용"), 1), gt(slen(V("주제")), 0), NOT(eq(V("주제"), V("최근주제")))),
           setv("최근주제", V("주제")), setv("키", "#최근주제"), setv("저장값", V("주제")), CALL("사실 저장")),
        IF(AND(gt(slen(V("새기분")), 0), NOT(eq(V("새기분"), V("지난기분")))),
           setv("지난기분", V("새기분")), setv("키", "#기분"), setv("저장값", V("새기분")), CALL("사실 저장")),
    )


def calc_script():
    ops = [("+", "PLUS"), ("*", "MULTI"), ("/", "DIVIDE")]
    find_op = [IF(eq(V("연산위치"), 0),
                  setv("연산위치", find(V("식"), sym)),
                  IF(gt(V("연산위치"), 0), setv("연산자", sym)))
               for sym, _ in ops]
    # 빼기는 맨 앞의 음수 부호를 건너뛰고 찾는다.
    find_op.append(IF(eq(V("연산위치"), 0),
                      IF(gt(slen(V("식")), 1),
                         setv("연산위치", find(sub(V("식"), 2, slen(V("식"))), "-")),
                         IF(gt(V("연산위치"), 0), setv("연산위치", plus(V("연산위치"), 1)), setv("연산자", "-")))))
    compute = []
    for sym, op in ops + [("-", "MINUS")]:
        body = [setv("결과", join(V("식"), " = ", calc(V("왼쪽수"), op, V("오른쪽수"))))]
        if sym == "/":
            body = [IFELSE(eq(V("오른쪽수"), 0), [setv("결과", "0으로는 나눌 수 없어요.")], body)]
        compute.append(IF(eq(V("연산자"), sym), *body))
    return WHEN_MSG(
        "계산하기",
        setv("결과", "식을 이해하지 못했어요. 예) 계산: 12*3  (+, -, *, / 중 하나만 써 주세요)"),
        setv("연산위치", 0), setv("연산자", ""),
        *find_op,
        IF(AND(gt(V("연산위치"), 1), lt(V("연산위치"), slen(V("식")))),
           setv("왼쪽수", sub(V("식"), 1, minus(V("연산위치"), 1))),
           setv("오른쪽수", sub(V("식"), plus(V("연산위치"), 1), slen(V("식")))),
           # 숫자인지 확인: 숫자 문자열만 '자기 자신 - 0' 과 같다.
           IF(AND(eq(V("왼쪽수"), minus(V("왼쪽수"), 0)), eq(V("오른쪽수"), minus(V("오른쪽수"), 0))),
              *compute)),
    )


# ---------------------------------------------------------------- 프로젝트 조립
def est_height(b):
    h = 32
    for st in b["statements"]:
        h += 24 + sum(est_height(x) for x in st)
    return h


def place(threads):
    """스레드를 작업창에 위에서 아래로, 겹치지 않게 늘어놓는다."""
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


def text_box(name, text, x, y, size, colour, bg="transparent", align=0, bold=False, font=FONT, script=(),
             width=100, height=None, line_break=False, visible=True, scene_id=None):
    height = height or size + 6
    font_str = f"{'bold ' if bold else ''}{size}px {font}"
    return {
        "id": gen_id(), "name": name, "text": text, "objectType": "textBox", "rotateMethod": "free",
        "scene": scene_id, "lock": True, "script": json.dumps(place(list(script)), ensure_ascii=False),
        "sprite": {"pictures": [], "sounds": []},
        "entity": {
            "x": x, "y": y, "regX": 0, "regY": 0, "scaleX": 1, "scaleY": 1, "rotation": 0, "direction": 90,
            "width": width, "height": height, "font": font_str, "visible": visible, "colour": colour,
            "text": text, "textAlign": align, "lineBreak": line_break, "bgColor": bg,
            "underLine": False, "strike": False, "fontSize": size,
        },
    }


def build():
    scene_id = gen_id()
    bot_rows, me_rows, status_script = ui_scripts()
    main = main_script()
    # 시작할 때 채워 두는 글자 모음 변수
    main[1:1] = [setv("글자-받침없음", D.NO_BATCHIM), setv("글자-ㄹ받침", D.RIEUL), setv("글자-ㅆ받침", D.SSANG_SIOT)]
    engine_scripts = [main, print_script(), *thinking_scripts()]
    # 블록이 많아 엔트리 작업창이 무거워지지 않도록 '두뇌' 오브젝트 셋으로 나눈다 (모두 숨김)
    brains = [
        ("두뇌1 문장 분석", [analyze_script(), strip_josa_script(), connect_script()]),
        ("두뇌2 대답 만들기", [reply_script(), template_script(), josa_script(), topic_question_script(),
                          starter_script(), calc_script()]),
        ("두뇌3 기억", [facts_script(), clean_value_script(), load_script(), *storage_scripts(), trim_script()]),
    ]

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
        *[text_box(name, name, 0, 0, 12, "#000000", script=scripts, visible=False, scene_id=scene_id)
          for name, scripts in brains],
    ]

    lists = [
        lst("화면글"), lst("화면종류"), lst("단어들"), lst("원단어들"), lst("후보답변"), lst("내질문"), lst("내답변"),
        lst("주제목록", [t for t, _ in D.TOPICS]), lst("주제질문목록", [q for _, q in D.TOPICS]),
        lst("정의단어", [k for k, _ in D.DEFINITIONS]), lst("정의설명", [v for _, v in D.DEFINITIONS]),
        lst("의도키워드", [k for k, _ in D.INTENTS]), lst("의도답변", [v for _, v in D.INTENTS]),
        lst("긍정어", D.POSITIVE), lst("부정어", D.NEGATIVE), lst("불용어", D.STOPWORDS),
        lst("조사목록", D.JOSA_SUFFIXES), lst("형용사", D.ADJ_STEMS), lst("요일", D.WEEKDAYS),
        lst("시작키", [k for k, _ in D.STARTERS]), lst("시작질문", [q for _, q in D.STARTERS]),
        lst("예말", D.YES_WORDS), lst("모름말", D.NON_ANSWERS),
        *[lst(name, phrases) for name, phrases in D.PHRASES.items()],
        lst("대화기록", realtime=True), lst("기억저장소", realtime=True),
    ]
    unknown = set(LISTS) - {l["name"] for l in lists}
    assert not unknown, f"만들지 않은 리스트를 블록에서 씀: {unknown}"
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
        "functions": [],
        "tables": [],
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
    handled = {json.loads(o["script"])[i][0]["params"][1]
               for o in project["objects"] for i, t in enumerate(json.loads(o["script"]))
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
    print(f"wrote {OUT_ENT} and {OUT_JSON} ({n_blocks} blocks, {len(project['objects'])} objects)")
