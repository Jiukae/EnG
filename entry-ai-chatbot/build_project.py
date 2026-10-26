#!/usr/bin/env python3
"""엔트리(playentry.org)용 'AI 챗봇' 작품 파일(.ent)을 만든다.

.ent 파일은 temp/project.json 하나를 담은 tar.gz 압축 파일이다
(entrylabs/entry-offline 의 MainUtils.saveProject 와 같은 구조).
블록 이름과 파라미터 순서는 entrylabs/entryjs 의 블록 정의
(src/playground/blocks/*.js)를 그대로 따른다.

사용법:  python3 build_project.py   →  entry-ai-chatbot.ent, project.json 생성
"""
import io
import json
import os
import random
import tarfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_ENT = os.path.join(HERE, "entry-ai-chatbot.ent")
OUT_JSON = os.path.join(HERE, "project.json")

SEP = "¶"               # 저장 문자열 안에서 줄을 나누는 기호
CHUNK = 24              # 대화창 한 줄에 넣을 최대 글자 수
CHAT_LINES = 9          # 대화창에 보이는 줄 수 (리스트 높이 198 → 9줄)
MAX_HISTORY_LINES = 30  # 사용자마다 서버에 남기는 대화 줄 수
MAX_LINE_LEN = 120      # 서버에 남기는 한 줄의 최대 길이
MAX_MEMORIES = 30       # 사용자마다 기억하는 지식 수

_rng = random.Random(20261026)
_used_ids = set()


def gen_id():
    chars = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        s = _rng.choice(chars[:26]) + "".join(_rng.choice(chars) for _ in range(3))
        if s not in _used_ids:
            _used_ids.add(s)
            return s


# ---------------------------------------------------------------- 이름 → id
VARS = {}
LISTS = {}
MSGS = {}


def declare(table, names):
    for n in names:
        table[n] = gen_id()


declare(VARS, [
    "아이디", "닉네임", "호칭", "접두어", "로그인", "저장가능", "대화중", "처리됨",
    "메시지", "정리메시지", "답변", "명령", "내용", "질문", "가르칠답",
    "위치", "k", "공백정리", "남은문자열", "줄", "추가줄", "임시",
    "기록블롭", "기억블롭", "기록위치", "기억위치", "확인", "찾은번호",
    "저장할줄", "출력문자열", "출력남은", "출력줄", "출력위치", "조각", "첫조각", "끊을위치",
    "최장길이", "비교어", "식", "연산위치", "연산자", "왼쪽수", "오른쪽수", "결과",
])
declare(LISTS, [
    "대화창", "키워드", "키워드답변", "모르는답변", "요일", "후보답변", "내질문", "내답변",
    "대화기록", "기억저장소",
])
declare(MSGS, [
    "채팅에 출력", "사용자 데이터 불러오기", "기록 위치 찾기", "기억 위치 찾기",
    "기록에 추가", "기록 저장", "기억 저장", "답변 만들기", "공백 정리", "계산하기",
])


# ---------------------------------------------------------------- 블록 DSL
def blk(type_, params=None, statements=None):
    return {"id": gen_id(), "type": type_, "params": params or [], "statements": statements or []}


def w(v):
    if isinstance(v, dict):
        return v
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return blk("number", [str(v)])
    if isinstance(v, str):
        return blk("text", [v])
    raise TypeError(v)


# 값 블록
def V(name): return blk("get_variable", [VARS[name], None])
def item(lst, i): return blk("value_of_index_from_list", [None, LISTS[lst], None, w(i), None])
def llen(lst): return blk("length_of_list", [None, LISTS[lst], None])
def cmp(a, op, b): return blk("boolean_basic_operator", [w(a), op, w(b)])
def eq(a, b): return cmp(a, "EQUAL", b)
def gt(a, b): return cmp(a, "GREATER", b)
def lt(a, b): return cmp(a, "LESS", b)
def AND(a, b): return blk("boolean_and_or", [a, "AND", b])
def NOT(a): return blk("boolean_not", [None, a, None])


def OR(*conds):
    out = conds[-1]
    for c in reversed(conds[:-1]):
        out = blk("boolean_and_or", [c, "OR", out])
    return out


def calc(a, op, b): return blk("calc_basic", [w(a), op, w(b)])
def plus(a, b): return calc(a, "PLUS", b)
def minus(a, b): return calc(a, "MINUS", b)
def times(a, b): return calc(a, "MULTI", b)
def div(a, b): return calc(a, "DIVIDE", b)
def rand(a, b): return blk("calc_rand", [None, w(a), None, w(b), None])


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
def contains(s, t): return gt(find(s, t), 0)


# 명령 블록
def setv(name, v): return blk("set_variable", [VARS[name], w(v), None])
def chg(name, v): return blk("change_variable", [VARS[name], w(v), None])
def append(lst, v): return blk("add_value_to_list", [w(v), LISTS[lst], None])
def remove(lst, i): return blk("remove_value_from_list", [w(i), LISTS[lst], None])
def setitem(lst, i, v): return blk("change_value_list_index", [LISTS[lst], w(i), w(v), None])
def show_list(lst): return blk("show_list", [LISTS[lst], None])
def clear(lst): return REPEAT(llen(lst), remove(lst, 1))
def IF(cond, *body): return blk("_if", [cond, None], [list(body)])
def IFELSE(cond, then, els): return blk("if_else", [cond, None, None], [list(then), list(els)])
def REPEAT(n, *body): return blk("repeat_basic", [w(n), None], [list(body)])
def FOREVER(*body): return blk("repeat_inf", [None], [list(body)])
def UNTIL(cond, *body): return blk("repeat_while_true", [cond, "until", None], [list(body)])
def BREAK(): return blk("stop_repeat", [None])
def WAIT(sec): return blk("wait_second", [w(sec), None])
def CALL(msg): return blk("message_cast_wait", [MSGS[msg], None])
def SAY(v): return blk("dialog", [w(v), "speak", None])
def UNSAY(): return blk("remove_dialog", [None])
def ASK(v): return blk("ask_and_wait", [w(v), None])
def HIDE_ANSWER(): return blk("set_visible_answer", ["HIDE", None])
def WHEN_START(*body): return [blk("when_run_button_click", [None]), *body]
def WHEN_MSG(msg, *body): return [blk("when_message_cast", [None, MSGS[msg]]), *body]


def PRINT(text):
    """대화창에 text 를 출력한다 (¶ 는 줄바꿈)."""
    return [setv("출력문자열", text), CALL("채팅에 출력")]


def TRIM_INTO(dst, src):
    """src 값의 앞뒤 공백을 지워 변수 dst 에 넣는다."""
    return [setv("공백정리", src), CALL("공백 정리"), setv(dst, V("공백정리"))]


def BRANCH(cond, *body):
    """아직 답이 정해지지 않았고 cond 가 참이면 body 를 실행한다."""
    return IF(eq(V("처리됨"), 0), IF(cond, *body, setv("처리됨", 1)))


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


def SCAN(lst, body, unroll):
    """리스트 lst 의 항목을 k = 1, 2, … 로 훑으며 body(항목 번호 블록 만드는 함수)를 실행한다.

    엔트리는 (부스트 모드가 아니면) 반복 한 바퀴마다 한 프레임을 쉬므로,
    한 바퀴에 unroll 개씩 검사해서 기다리는 시간을 줄인다.
    body 안의 '반복 중단하기'는 이 반복 전체를 멈춘다.
    """
    steps = []
    for _ in range(unroll):
        steps += [IF(NOT(gt(V("k"), llen(lst))), *body()), chg("k", 1)]
    return [setv("k", 1), UNTIL(gt(V("k"), llen(lst)), *steps)]


def FIND_SLOT(lst, pos_var):
    """서버 리스트 lst 에서 '아이디|' 로 시작하는 항목 번호를 pos_var 에 넣는다 (없으면 0)."""
    return [
        setv(pos_var, 0),
        *SCAN(lst, lambda: [IF(eq(find(item(lst, V("k")), V("접두어")), 1), setv(pos_var, V("k")), BREAK())], 8),
    ]


def SAVE_SLOT(lst, pos_var, finder_msg, blob_var):
    """내 항목이 맞는지 확인한 뒤 서버 리스트의 내 칸을 '아이디|' + blob 으로 바꾼다."""
    return IF(eq(V("저장가능"), 1),
              setv("확인", 0),
              IF(gt(V(pos_var), 0),
                 IF(NOT(gt(V(pos_var), llen(lst))),
                    IF(eq(find(item(lst, V(pos_var)), V("접두어")), 1), setv("확인", 1)))),
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


# ---------------------------------------------------------------- 대화 데이터
HELP = SEP.join([
    "제가 할 수 있는 일이에요.",
    "· 그냥 대화하기 (인사, 기분, 취미…)",
    "· 기억해: 질문 = 답  → 나만의 지식 가르치기",
    "· 잊어줘: 질문  → 가르친 것 지우기",
    "· 기억 목록  → 가르친 것 모두 보기",
    "· 번역: 문장  → 영어로 번역 (파파고 AI)",
    "· 한국어로: sentence  → 한국어로 번역",
    "· 계산: 12*3  → 사칙연산",
    "· 몇 시야? / 오늘 며칠이야?",
    "· 새 대화  → 내 대화 기록 지우기",
    "· 종료  → 대화 끝내기",
])
TEACH_FORMAT = "이렇게 입력해 주세요 → 기억해: 질문 = 답 (예: 기억해: 내 생일 = 5월 5일)"

# (키워드, 답변). 키워드는 공백 없이 소문자로 쓴다. 같은 키워드를 여러 줄 쓰면 그중 하나를 골라 답한다.
KNOWLEDGE = [
    ("안녕", "안녕하세요, {이름}님! 오늘 하루는 어땠어요?"),
    ("안녕", "반가워요, {이름}님! 무엇이든 말 걸어 주세요."),
    ("하이", "하이~ 반가워요, {이름}님!"),
    ("hello", "Hello, {이름}! 영어로 인사해 주셨네요. 반가워요!"),
    ("반가", "저도 정말 반가워요!"),
    ("누구야", "저는 엔트리 블록 코딩으로 만든 AI 챗봇이에요. 대화를 사용자마다 따로 기억해요."),
    ("너는누구", "저는 엔트리 블록 코딩으로 만든 AI 챗봇이에요. 대화를 사용자마다 따로 기억해요."),
    ("이름이뭐", "제 이름은 '엔봇'이에요. 엔트리 AI 챗봇을 줄인 이름이죠!"),
    ("너이름", "제 이름은 '엔봇'이에요. 엔트리 AI 챗봇을 줄인 이름이죠!"),
    ("내이름", "{이름}님이잖아요! 엔트리 계정의 닉네임으로 알아봤어요."),
    ("나는누구", "{이름}님이잖아요! 엔트리 계정의 닉네임으로 알아봤어요."),
    ("고마워", "천만에요! 언제든 도와드릴게요."),
    ("고맙", "천만에요! 언제든 도와드릴게요."),
    ("감사", "별말씀을요. 도움이 되어 기뻐요!"),
    ("미안", "괜찮아요! 마음 쓰지 마세요."),
    ("사랑", "저도 {이름}님과 이야기하는 게 정말 좋아요!"),
    ("심심", "그럼 '계산: 123*45'나 '번역: 오늘 정말 즐거워'를 입력해 볼래요?"),
    ("심심", "재미있는 사실 하나! 문어는 심장이 3개래요."),
    ("재미있는", "꿀은 잘 상하지 않아서, 수천 년 전 꿀도 먹을 수 있었대요!"),
    ("재밌는", "기린은 하루에 30분 정도밖에 안 잔대요."),
    ("상식", "번개는 태양 표면보다 몇 배나 뜨겁대요!"),
    ("농담", "왕이 넘어지면? 킹콩! ㅎㅎ"),
    ("농담", "바나나가 웃으면? 바나나킥!"),
    ("웃긴", "세상에서 가장 뜨거운 과일은? 천도복숭아!"),
    ("기분좋", "와, 좋은 일이 있었나 봐요! 무슨 일인지 들려주세요."),
    ("행복", "{이름}님이 행복하다니 저도 기뻐요!"),
    ("신나", "신나는 일이 있었군요! 저도 덩달아 신나요."),
    ("슬퍼", "많이 속상했겠어요. 제가 이야기 들어 드릴게요. 무슨 일이 있었어요?"),
    ("슬프", "많이 속상했겠어요. 제가 이야기 들어 드릴게요. 무슨 일이 있었어요?"),
    ("우울", "그럴 땐 좋아하는 노래를 듣거나 잠깐 산책해 보는 건 어때요?"),
    ("속상", "속상한 마음, 이야기해 줘서 고마워요. 천천히 말해 주세요."),
    ("힘들", "오늘 정말 수고 많았어요. 잠깐 쉬어 가도 괜찮아요."),
    ("피곤", "피곤할 땐 물 한 잔 마시고 기지개를 쭉 켜 보세요!"),
    ("배고", "맛있는 걸 먹을 시간이네요! 뭐 먹고 싶어요?"),
    ("졸려", "푹 자는 것도 정말 중요해요. 좋은 꿈 꾸세요!"),
    ("날씨", "저는 창밖을 볼 수 없어서 날씨는 잘 몰라요. 대신 '몇 시야?'는 알려 드릴 수 있어요!"),
    ("코딩", "코딩은 큰 문제를 작은 단계로 나눠서 해결하는 거예요. 저도 엔트리 블록으로 만들어졌어요!"),
    ("프로그래밍", "프로그래밍은 컴퓨터에게 일을 시키는 방법이에요. 엔트리로 시작하면 쉬워요!"),
    ("엔트리", "엔트리는 블록 코딩으로 누구나 작품을 만들고 공유할 수 있는 곳이에요."),
    ("인공지능", "인공지능은 데이터에서 규칙을 배워 판단하는 기술이에요. 저는 키워드와 {이름}님이 가르쳐 준 지식으로 대답해요."),
    ("ai", "저는 엔트리로 만든 AI 챗봇이에요. '기억해: 질문 = 답'으로 저를 더 똑똑하게 만들어 주세요!"),
    ("gpt", "ChatGPT만큼 똑똑하진 않지만, 저는 {이름}님만의 대화와 지식을 따로 기억해요!"),
    ("공부", "공부할 땐 25분 집중하고 5분 쉬는 방법을 추천해요!"),
    ("숙제", "숙제는 미루지 않는 게 최고예요! 같이 힘내요."),
    ("시험", "시험 잘 보길 응원해요! 충분히 잘 해낼 거예요."),
    ("수학", "수학 문제라면 '계산: 3+4'처럼 입력해 보세요."),
    ("영어", "영어 문장이 궁금하면 '번역: 하고 싶은 말'처럼 입력해 보세요."),
    ("노래", "음악 좋아하시는군요! 요즘 즐겨 듣는 노래가 뭐예요?"),
    ("음악", "음악 좋아하시는군요! 요즘 즐겨 듣는 노래가 뭐예요?"),
    ("게임", "게임 좋아해요? 엔트리로 직접 게임을 만들어 보는 것도 정말 재밌어요!"),
    ("색깔", "저는 엔트리를 닮은 초록색과 하늘색을 좋아해요."),
    ("몇살", "저는 이 작품이 만들어진 날 태어났어요. 아직 아기 챗봇이에요!"),
    ("나이", "저는 이 작품이 만들어진 날 태어났어요. 아직 아기 챗봇이에요!"),
    ("취미", "제 취미는 {이름}님과 대화하기예요! '기억해: 내 취미 = 축구'처럼 알려 주세요."),
    ("바보", "앗, 아직 배우는 중이라 그래요. '기억해: 질문 = 답'으로 가르쳐 주세요!"),
    ("잘자", "잘 자요, {이름}님! 다음에 또 이야기해요."),
    ("뭐해", "{이름}님 말을 기다리고 있었어요!"),
    ("응원", "{이름}님은 할 수 있어요! 화이팅!"),
    ("화이팅", "화이팅! {이름}님을 응원해요!"),
    ("파이팅", "파이팅! {이름}님을 응원해요!"),
    ("ㅋㅋ", "재밌었나 봐요! ㅎㅎ"),
    ("ㅠㅠ", "울지 마요… 제가 옆에 있을게요."),
]
FALLBACK = [
    "음… 그건 아직 잘 모르겠어요. '기억해: 질문 = 답'으로 가르쳐 주면 기억할게요!",
    "흥미로운 이야기네요! 조금 더 자세히 말해 줄래요?",
    "제가 아직 배우는 중이라 대답하기 어려워요. '도움말'을 입력해 보세요.",
    "그렇군요! {이름}님 이야기를 듣는 건 언제나 즐거워요.",
]
WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"]


# ---------------------------------------------------------------- 스크립트
def main_script():
    return WHEN_START(
        HIDE_ANSWER(),
        show_list("대화창"),
        clear("대화창"), clear("후보답변"), clear("내질문"), clear("내답변"),
        setv("아이디", username()),
        setv("닉네임", nickname()),
        setv("기록블롭", ""), setv("기억블롭", ""), setv("기록위치", 0), setv("기억위치", 0),
        IFELSE(eq(slen(repl(V("아이디"), " ", "")), 0),
               [setv("로그인", 0), setv("저장가능", 0), setv("호칭", "방문자"),
                *PRINT(f"봇: 안녕하세요! 저는 엔트리 AI 챗봇 '엔봇'이에요.{SEP}"
                       "봇: 로그인하지 않아서 이번 대화는 저장되지 않아요.")],
               [setv("로그인", 1), setv("저장가능", 1),
                setv("호칭", V("닉네임")),
                IF(eq(slen(repl(V("호칭"), " ", "")), 0), setv("호칭", V("아이디"))),
                setv("접두어", join(V("아이디"), "|")),
                SAY("기록을 불러오는 중…"),
                CALL("사용자 데이터 불러오기"),
                UNSAY(),
                IFELSE(gt(slen(V("기록블롭")), 0),
                       [*PRINT(join("봇: ", V("호칭"), "님, 다시 만나서 반가워요! 지난 대화를 기억하고 있어요."))],
                       [*PRINT(join("봇: 안녕하세요, ", V("호칭"),
                                    "님! 저는 엔트리 AI 챗봇 '엔봇'이에요. 우리 대화는 ",
                                    V("호칭"), "님 계정 몫으로 따로 저장돼요."))]),
                IF(eq(V("저장가능"), 0),
                   *PRINT("봇: (저장 서버에 연결하지 못해서 이번 대화는 저장되지 않아요.)"))]),
        *PRINT("봇: '도움말'을 입력하면 제가 할 수 있는 일을 알려 드려요."),
        setv("대화중", 1),
        UNTIL(eq(V("대화중"), 0),
              ASK("메시지를 입력하세요"),
              *TRIM_INTO("메시지", repl(answer(), SEP, " ")),
              IF(gt(slen(V("메시지")), 0),
                 *PRINT(join("나: ", V("메시지"))),
                 setv("저장할줄", join("나: ", V("메시지"))), CALL("기록에 추가"),
                 SAY("생각 중…"),
                 CALL("답변 만들기"),
                 UNSAY(),
                 setv("답변", repl(V("답변"), "{이름}", V("호칭"))),
                 *PRINT(join("봇: ", V("답변"))),
                 setv("저장할줄", join("봇: ", repl(V("답변"), SEP, " / "))), CALL("기록에 추가"),
                 CALL("기록 저장"))),
        SAY("다음에 또 만나요!"),
    )


def print_script():
    # 출력문자열을 ¶ 기준으로 줄을 나누고, 긴 줄은 CHUNK 글자씩 잘라 대화창에 넣는다.
    # 대화창은 최근 CHAT_LINES 줄만 남겨서 항상 마지막 대화가 보이게 한다.
    return WHEN_MSG(
        "채팅에 출력",
        setv("출력남은", V("출력문자열")),
        UNTIL(eq(slen(V("출력남은")), 0),
              *SPLIT_LINE("출력남은", "출력줄", "출력위치"),
              setv("첫조각", 1),
              UNTIL(eq(slen(V("출력줄")), 0),
                    IFELSE(gt(slen(V("출력줄")), CHUNK),
                           [setv("조각", sub(V("출력줄"), 1, CHUNK)),
                            # 조각의 마지막 공백이 뒤쪽 절반 안에 있으면 그 공백에서 줄을 바꾼다.
                            setv("끊을위치", find(reverse(V("조각")), " ")),
                            IFELSE(AND(gt(V("끊을위치"), 0), lt(V("끊을위치"), CHUNK // 2 + 1)),
                                   [setv("조각", sub(V("출력줄"), 1, minus(CHUNK, V("끊을위치")))),
                                    setv("출력줄", sub(V("출력줄"), minus(CHUNK + 2, V("끊을위치")), slen(V("출력줄"))))],
                                   [setv("출력줄", sub(V("출력줄"), CHUNK + 1, slen(V("출력줄"))))])],
                           [setv("조각", V("출력줄")), setv("출력줄", "")]),
                    IF(eq(V("첫조각"), 0), setv("조각", join("    ", V("조각")))),
                    setv("첫조각", 0),
                    append("대화창", V("조각")),
                    IF(gt(llen("대화창"), CHAT_LINES), remove("대화창", 1)))),
    )


def trim_script():
    s = "공백정리"
    return WHEN_MSG(
        "공백 정리",
        FOREVER(
            IF(eq(slen(V(s)), 0), BREAK()),
            IF(NOT(eq(find(charat(V(s), 1), " "), 1)), BREAK()),
            IFELSE(eq(slen(V(s)), 1), [setv(s, "")], [setv(s, sub(V(s), 2, slen(V(s))))])),
        FOREVER(
            IF(eq(slen(V(s)), 0), BREAK()),
            IF(NOT(eq(find(charat(V(s), slen(V(s))), " "), 1)), BREAK()),
            IFELSE(eq(slen(V(s)), 1), [setv(s, "")], [setv(s, sub(V(s), 1, minus(slen(V(s)), 1)))])),
    )


def load_script():
    return WHEN_MSG(
        "사용자 데이터 불러오기",
        *ENSURE_SLOT("대화기록", "기록위치", "기록 위치 찾기"),
        *ENSURE_SLOT("기억저장소", "기억위치", "기억 위치 찾기"),
        IF(OR(eq(V("기록위치"), 0), eq(V("기억위치"), 0)), setv("저장가능", 0)),
        *LOAD_BLOB("대화기록", "기록위치", "기록블롭"),
        *LOAD_BLOB("기억저장소", "기억위치", "기억블롭"),
        # 기억블롭 "질문=답¶질문=답¶" → 내질문 / 내답변 리스트
        setv("남은문자열", V("기억블롭")),
        UNTIL(eq(slen(V("남은문자열")), 0),
              *SPLIT_LINE("남은문자열", "줄", "위치"),
              setv("위치", find(V("줄"), "=")),
              IF(gt(V("위치"), 1),
                 IF(lt(V("위치"), slen(V("줄"))),
                    append("내질문", sub(V("줄"), 1, minus(V("위치"), 1))),
                    append("내답변", sub(V("줄"), plus(V("위치"), 1), slen(V("줄"))))))),
        IF(gt(slen(V("기록블롭")), 0),
           *PRINT(join(f"── 지난 대화 ──{SEP}", V("기록블롭"), "── 이어서 대화해요 ──"))),
    )


def find_scripts():
    return [
        WHEN_MSG("기록 위치 찾기", *FIND_SLOT("대화기록", "기록위치")),
        WHEN_MSG("기억 위치 찾기", *FIND_SLOT("기억저장소", "기억위치")),
    ]


def history_scripts():
    return [
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
            setv("k", 1),
            REPEAT(llen("내질문"),
                   setv("기억블롭", join(V("기억블롭"), item("내질문", V("k")), "=", item("내답변", V("k")), SEP)),
                   chg("k", 1)),
            SAVE_SLOT("기억저장소", "기억위치", "기억 위치 찾기", "기억블롭")),
    ]


def find_question_index():
    """내질문 리스트에서 '질문' 과 똑같은 항목 번호를 찾은번호에 넣는다."""
    return [
        setv("찾은번호", 0),
        *SCAN("내질문", lambda: [IF(eq(item("내질문", V("k")), V("질문")), setv("찾은번호", V("k")), BREAK())], 5),
    ]


def reply_script():
    teach = [
        setv("위치", find(V("내용"), "=")),
        IFELSE(AND(gt(V("위치"), 1), lt(V("위치"), slen(V("내용")))),
               [*TRIM_INTO("질문", sub(V("내용"), 1, minus(V("위치"), 1))),
                *TRIM_INTO("가르칠답", sub(V("내용"), plus(V("위치"), 1), slen(V("내용")))),
                IFELSE(OR(eq(slen(V("질문")), 0), eq(slen(V("가르칠답")), 0)),
                       [setv("답변", TEACH_FORMAT)],
                       [IF(gt(slen(V("질문")), 40), setv("질문", sub(V("질문"), 1, 40))),
                        IF(gt(slen(V("가르칠답")), 100), setv("가르칠답", sub(V("가르칠답"), 1, 100))),
                        *find_question_index(),
                        IFELSE(gt(V("찾은번호"), 0),
                               [setitem("내답변", V("찾은번호"), V("가르칠답"))],
                               [append("내질문", V("질문")), append("내답변", V("가르칠답")),
                                IF(gt(llen("내질문"), MAX_MEMORIES), remove("내질문", 1), remove("내답변", 1))]),
                        setv("답변", join("알겠어요! 앞으로 '", V("질문"), "'(이)라고 물으면 '",
                                          V("가르칠답"), "'(이)라고 답할게요.")),
                        IFELSE(eq(V("저장가능"), 1),
                               [CALL("기억 저장")],
                               [setv("답변", join(V("답변"), " (저장되지 않는 상태라 이번 실행에서만 기억해요.)"))])])],
               [setv("답변", TEACH_FORMAT)]),
    ]
    forget = [
        IFELSE(eq(slen(V("내용")), 0),
               [setv("답변", "이렇게 입력해 주세요 → 잊어줘: 질문")],
               [setv("질문", V("내용")),
                *find_question_index(),
                IFELSE(gt(V("찾은번호"), 0),
                       [remove("내질문", V("찾은번호")), remove("내답변", V("찾은번호")),
                        setv("답변", join("'", V("내용"), "'에 대한 기억을 지웠어요.")),
                        IF(eq(V("저장가능"), 1), CALL("기억 저장"))],
                       [setv("답변", join("'", V("내용"), "'(이)라는 기억은 없어요. '기억 목록'으로 확인해 보세요."))])]),
    ]
    memory_list = [
        IFELSE(eq(llen("내질문"), 0),
               [setv("답변", "아직 가르쳐 준 게 없어요. 예) 기억해: 내 생일 = 5월 5일")],
               [setv("답변", join("기억하고 있는 것 ", llen("내질문"), "개예요.")),
                setv("k", 1),
                REPEAT(llen("내질문"),
                       setv("답변", join(V("답변"), f"{SEP}· ", item("내질문", V("k")), " → ", item("내답변", V("k")))),
                       chg("k", 1))]),
    ]
    memory_match = IF(
        eq(V("처리됨"), 0),
        setv("최장길이", 0),
        *SCAN("내질문", lambda: [
            setv("비교어", repl(lower(item("내질문", V("k"))), " ", "")),
            IF(gt(slen(V("비교어")), V("최장길이")),
               IF(contains(V("정리메시지"), V("비교어")),
                  setv("최장길이", slen(V("비교어"))),
                  setv("답변", item("내답변", V("k")))))], 5),
        IF(gt(V("최장길이"), 0), setv("처리됨", 1)),
    )
    keyword_match = IF(
        eq(V("처리됨"), 0),
        clear("후보답변"),
        *SCAN("키워드", lambda: [
            IF(contains(V("정리메시지"), item("키워드", V("k"))), append("후보답변", item("키워드답변", V("k"))))], 8),
        IF(gt(llen("후보답변"), 0),
           setv("답변", item("후보답변", rand(1, llen("후보답변")))),
           setv("처리됨", 1)),
    )
    return WHEN_MSG(
        "답변 만들기",
        setv("답변", ""),
        setv("처리됨", 0),
        setv("정리메시지", repl(lower(V("메시지")), " ", "")),
        # "명령: 내용" 형태 나누기
        setv("명령", ""), setv("내용", ""),
        setv("위치", find(V("메시지"), ":")),
        IF(gt(V("위치"), 1),
           setv("명령", repl(sub(V("메시지"), 1, minus(V("위치"), 1)), " ", "")),
           IF(lt(V("위치"), slen(V("메시지"))),
              *TRIM_INTO("내용", sub(V("메시지"), plus(V("위치"), 1), slen(V("메시지")))))),
        BRANCH(OR(eq(find(V("정리메시지"), "도움말"), 1), eq(V("정리메시지"), "help"), eq(V("정리메시지"), "?")), setv("답변", HELP)),
        BRANCH(OR(eq(V("명령"), "기억해"), eq(V("명령"), "가르치기"), eq(V("명령"), "기억")), *teach),
        BRANCH(OR(eq(V("명령"), "잊어줘"), eq(V("명령"), "잊어"), eq(V("명령"), "삭제")), *forget),
        BRANCH(OR(eq(V("명령"), "번역"), eq(V("명령"), "영어로"), eq(V("명령"), "영어")),
               IFELSE(eq(slen(V("내용")), 0),
                      [setv("답변", "번역할 문장도 같이 입력해 주세요. 예) 번역: 오늘 날씨가 좋아요")],
                      [setv("답변", join("영어로는 이렇게 말해요 → ", translate("ko", V("내용"), "en")))])),
        BRANCH(OR(eq(V("명령"), "한국어로"), eq(V("명령"), "한글로"), eq(V("명령"), "한국어")),
               IFELSE(eq(slen(V("내용")), 0),
                      [setv("답변", "번역할 영어 문장도 같이 입력해 주세요. 예) 한국어로: Nice to meet you")],
                      [setv("답변", join("한국어로는 이렇게 말해요 → ", translate("en", V("내용"), "ko")))])),
        BRANCH(OR(eq(V("명령"), "계산"), eq(V("명령"), "계산해줘"), eq(V("명령"), "계산해")),
               setv("식", repl(repl(repl(repl(V("내용"), " ", ""), "×", "*"), "÷", "/"), "x", "*")),
               CALL("계산하기"),
               setv("답변", V("결과"))),
        BRANCH(OR(eq(V("정리메시지"), "기억목록"), eq(V("정리메시지"), "내기억"), eq(V("정리메시지"), "기억보기")), *memory_list),
        BRANCH(OR(eq(V("정리메시지"), "새대화"), eq(V("정리메시지"), "초기화"), eq(V("정리메시지"), "기록삭제")),
               setv("기록블롭", ""),
               clear("대화창"),
               setv("답변", "대화 기록을 모두 지웠어요. 새로 시작해요! (가르쳐 준 기억은 그대로예요.)")),
        BRANCH(OR(eq(V("정리메시지"), "종료"), eq(V("정리메시지"), "그만"), eq(V("정리메시지"), "끝"), eq(V("정리메시지"), "bye")),
               setv("대화중", 0),
               setv("답변", "대화를 마칠게요. 오늘도 즐거웠어요, {이름}님! 다시 이야기하려면 시작 버튼을 눌러 주세요.")),
        memory_match,
        BRANCH(OR(contains(V("정리메시지"), "몇시"), contains(V("정리메시지"), "지금시간"), contains(V("정리메시지"), "현재시간")),
               setv("답변", join("지금은 ", date("HOUR"), "시 ", date("MINUTE"), "분이에요."))),
        BRANCH(OR(contains(V("정리메시지"), "며칠"), contains(V("정리메시지"), "날짜"), contains(V("정리메시지"), "요일"), contains(V("정리메시지"), "몇월")),
               setv("답변", join("오늘은 ", date("YEAR"), "년 ", date("MONTH"), "월 ", date("DAY"), "일 ",
                                 item("요일", plus(date("DAY_OF_WEEK"), 1)), "요일이에요."))),
        keyword_match,
        IF(eq(V("처리됨"), 0),
           setv("답변", item("모르는답변", rand(1, llen("모르는답변")))),
           setv("처리됨", 1)),
    )


def calc_script():
    ops = [("+", "PLUS"), ("*", "MULTI"), ("/", "DIVIDE")]
    find_op = []
    for sym, _ in ops:
        find_op.append(IF(eq(V("연산위치"), 0),
                          setv("연산위치", find(V("식"), sym)),
                          IF(gt(V("연산위치"), 0), setv("연산자", sym))))
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
    """작업창에서 블록 묶음이 차지할 높이를 대강 계산한다."""
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


def variable(name, value=0):
    return {"name": name, "id": VARS[name], "visible": False, "value": value, "variableType": "variable",
            "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 0, "y": 0}


def lst(name, data=(), visible=False, realtime=False, x=0, y=0, width=100, height=120):
    return {"name": name, "id": LISTS[name], "visible": visible, "value": 0, "variableType": "list",
            "isCloud": False, "isRealTime": realtime, "cloudDate": False, "object": None,
            "x": x, "y": y, "width": width, "height": height,
            "array": [{"data": d} for d in data]}


def text_object(oid, name, text, x, y, font, colour, bg, script, scene_id, width, height):
    return {
        "id": oid, "name": name, "text": text, "objectType": "textBox", "rotateMethod": "free",
        "scene": scene_id, "lock": False, "script": json.dumps(script, ensure_ascii=False),
        "sprite": {"pictures": [], "sounds": []},
        "entity": {
            "x": x, "y": y, "regX": width / 2, "regY": height / 2, "scaleX": 1, "scaleY": 1,
            "rotation": 0, "direction": 90, "width": width, "height": height, "font": font,
            "visible": True, "colour": colour, "text": text, "textAlign": 0, "lineBreak": False,
            "bgColor": bg, "underLine": False, "strike": False, "fontSize": int(font.split("px")[0].split()[-1]),
        },
    }


def build():
    scene_id = gen_id()
    timer_id, answer_id = gen_id(), gen_id()
    bot_script = place([
        main_script(), reply_script(), print_script(), load_script(), *find_scripts(),
        *history_scripts(), trim_script(), calc_script(),
    ])
    variables = [
        {"name": "초시계", "id": timer_id, "visible": False, "value": "0", "variableType": "timer",
         "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 134, "y": -70, "array": []},
        {"name": "대답", "id": answer_id, "visible": False, "value": "0", "variableType": "answer",
         "isCloud": False, "isRealTime": False, "cloudDate": False, "object": None, "x": 150, "y": -100, "array": []},
        *[variable(n, "" if n not in ("k",) else 1) for n in VARS],
        lst("대화창", visible=True, x=-232, y=-102, width=360, height=198),
        lst("키워드", [k for k, _ in KNOWLEDGE]),
        lst("키워드답변", [a for _, a in KNOWLEDGE]),
        lst("모르는답변", FALLBACK),
        lst("요일", WEEKDAYS),
        lst("후보답변"), lst("내질문"), lst("내답변"),
        lst("대화기록", realtime=True),
        lst("기억저장소", realtime=True),
    ]
    objects = [
        text_object(gen_id(), "챗봇", "AI 엔봇", 180, -40, "bold 22px Nanum Gothic", "#ffffff", "#4f80ff",
                    bot_script, scene_id, 100, 34),
        text_object(gen_id(), "제목", "엔트리 AI 챗봇 · 대화는 계정마다 따로 저장돼요", 0, 120,
                    "bold 14px Nanum Gothic", "#333333", "#ffffff", [], scene_id, 340, 22),
    ]
    return {
        "name": "엔트리 AI 챗봇",
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


def check_unique_ids(project):
    """같은 블록 객체를 두 곳에 넣으면 id 가 겹친다. 엔트리는 블록 id 로 값을 캐시하므로 막아 둔다."""
    seen = set()

    def walk(b):
        assert b["id"] not in seen, f"블록 id 중복: {b['id']} ({b['type']})"
        seen.add(b["id"])
        for p in b["params"]:
            if isinstance(p, dict):
                walk(p)
        for st in b["statements"]:
            for x in st:
                walk(x)

    for o in project["objects"]:
        for thread in json.loads(o["script"]):
            for b in thread:
                walk(b)


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
    check_unique_ids(project)
    with open(OUT_JSON, "w", encoding="utf-8") as fp:
        json.dump(project, fp, ensure_ascii=False, indent=1)
    write_ent(project, OUT_ENT)
    n_blocks = sum(json.dumps(o["script"]).count('\\"type\\"') for o in project["objects"])
    print(f"wrote {OUT_ENT} and {OUT_JSON} ({n_blocks} blocks)")
