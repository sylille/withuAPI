"""v0.3.12 짧은 글자 가드 (모듈 A 점수 보정).

2026-11-12 6학년 2반(통제집단) 방에서 'ㅇㅇ'(9건)·'왜'·'ㄴ'·'절대'·'없겠지'·'안양하세요' 같은 짧은 글자가
모듈 A에서 0.50 언저리 점수를 받았다. 모델이 '모르겠다'는 뜻인데, 공격 기준이 '0.50 이상'이라 공격으로 세어졌다.
이 가짜 공격이 쌓이면서 가해자·피해자가 뒤바뀌고, 실제 거친 말('입 ㄷㅊ', 'ㅗㅗ')이 사건에서 빠졌다.

규칙 (짧은 메시지에만 적용, 긴 메시지는 손대지 않는다):
  1. 욕설·비하 표현이 있으면 낮추지 않는다. 짧은 초성 욕설(ㄲㅈ, ㄷㅊ, ㅅㅂ, ㅗ 등)은 모델이 놓쳐도 JAMO_FLOOR까지 올린다.
  2. 맞장구·인사·되묻기("ㅇㅇ", "응", "왜", "ㅋㅋ", "?")와 똑같은 말이면 SHORT_CAP으로 내린다.
  3. 그 밖의 짧은 말은 점수가 0.50 ~ SHORT_UNSURE_HI 사이(모델이 확신 없음)일 때만 SHORT_CAP으로 내린다.
     모델이 확신하는 짧은 공격("너 싫어" 0.9)은 그대로 둔다.

공개된 '짧은 채팅 표현' 표준 사전은 없어서, 아래 목록은 초등학생 단톡방에서 흔한 표현으로 직접 만든 것이다.
목록을 늘릴 때는 FILLERS / HOSTILE_* 에 더하고 test_short_text.py에 한 줄씩 넣는다.
환경 변수: WITHU_SHORT_GUARD=0 이면 끈다 (예전과 같은 점수).
"""
import os
import re
import unicodedata

try:
    from .check_chat_excel import TOX_THRESHOLD
except ImportError:                          # check_chat_excel.py를 스크립트로 바로 실행할 때
    from check_chat_excel import TOX_THRESHOLD


def _env(name, default, cast=float):
    v = os.environ.get(name)
    return cast(v) if v not in (None, "") else default


ENABLE          = os.environ.get("WITHU_SHORT_GUARD", "1") != "0"
SHORT_MAX_SYL   = _env("WITHU_SHORT_MAX_SYL", 5, int)    # 글자(음절·영문) 수가 이 이하면 '짧은 메시지'
SHORT_UNSURE_HI = _env("WITHU_SHORT_UNSURE_HI", 0.65)    # 짧은 말에서 이 점수 미만이면 모델이 확신 없는 것으로 본다
SHORT_CAP       = _env("WITHU_SHORT_CAP", 0.30)          # 내릴 때의 점수 (TOX_THRESHOLD 미만)
JAMO_FLOOR      = _env("WITHU_JAMO_FLOOR", 0.70)         # 짧은 초성 욕설의 최소 점수. 전송 전 경고(0.75)보다 낮게 둔다
ENABLE_FLOOR    = os.environ.get("WITHU_JAMO_FLOOR_ON", "1") != "0"

# --- 욕설·비하 -------------------------------------------------------------------------------------
# 초성 욕설 (분명한 것만): 짧은 메시지에서 모델이 놓치면 JAMO_FLOOR까지 올린다.
HOSTILE_JAMO_STRONG = ("ㅅㅂ", "ㅆㅂ", "ㅂㅅ", "ㅄ", "ㄲㅈ", "ㄷㅊ", "ㅈㄹ", "ㅈㄲ", "ㅅㄲ", "ㄴㄱㅁ", "ㄴㅇㅁ", "ㄷㅈ")
# 뜻이 갈리는 초성 ('ㅁㅊ' = 미쳤다(감탄)일 때도, 'ㅈㄴ' = 강조): 낮추지만 않는다.
HOSTILE_JAMO_WEAK = ("ㅁㅊ", "ㅈㄴ", "ㅉㅉ", "ㅂㄷ")
# 낱말 (일부만 있어도). 낮추지 않는 용도라 넓게 잡는다.
HOSTILE_WORDS = (
    "시발", "씨발", "시바", "씨바", "병신", "븅신", "빙신", "새끼", "색기", "지랄", "꺼져", "꺼지", "꺼저", "닥쳐", "닥치",
    "입닥", "죽어", "죽을", "죽인", "뒤져", "뒤질", "디져", "존나", "졸라", "개새", "개같", "개빡", "애미", "느금", "좆", "엿",
    "역겨", "역겁", "찐따", "냄새", "돼지", "못생", "쓰레기", "나가", "빠져", "한심", "멍청", "등신", "바보", "또라이",
    "미친", "미쳤", "노답", "극혐", "혐오", "관종", "짜져", "재수없", "꼴보기", "짜증", "싫", "저리가", "왕따",
)
_ONLY_FINGER = re.compile(r"ㅗ+")                         # 'ㅗ', 'ㅗㅗ' (가운뎃손가락). 'ㅗㅜㅑ'(감탄)는 아님

# --- 맞장구·인사·되묻기 (같은 글자 반복은 하나로 줄여 비교: 'ㅇㅇㅇ' -> 'ㅇ', '응응' -> '응') -----------------
FILLERS = {
    # 초성
    "ㅇ", "ㄴ", "ㄱ", "ㅇㅋ", "ㅇㅋㅇㅋ", "ㅎㅇ", "ㅂ", "ㅂㅇ", "ㅃㅇ", "ㄱㅅ", "ㄳ", "ㅈㅅ", "ㅊㅋ", "ㄹㅇ", "ㅇㅈ", "ㄷ",
    "ㅁㄹ", "ㅇㄷ", "ㅇㅎ", "ㅅㄱ", "ㄱㄷ", "ㅇㄱㄹㅇ", "ㄴㄴ", "ㄱㄱ", "ㅎㄹ", "ㅇㄴ", "ㄱㄴ", "ㄴㅇ", "ㅇㅇ",
    # 대답·맞장구
    "응", "웅", "엉", "어", "예", "네", "넹", "넵", "녜", "내", "옹", "오", "오키", "오케이", "오케", "아", "아하", "아항",
    "헐", "헉", "와", "우와", "대박", "굿", "굳", "좋아", "조아", "좋다", "그래", "그랭", "그럼", "그치", "그니까",
    "맞아", "마자", "맞지", "인정", "진짜", "레알", "리얼", "정말", "당연", "당연하지", "물론", "그렇지", "그런가",
    "그렇구나", "그렇군", "그래서", "근데", "그런데", "그리고", "아니", "아니야", "아님", "아닌데", "아니요", "절대",
    "알겠어", "알았어", "알겠습니다", "알겠어요", "알았다", "오키도키", "나도", "저도", "너도", "난", "나는",
    # 되묻기
    "왜", "왜요", "뭐", "뭐야", "뭔데", "뭐지", "머", "모", "뭐임", "누구", "언제", "어디", "어케", "어떻게", "몰라", "몰랑",
    "모름", "글쎄", "아마", "뭐함", "머함", "모함", "뭐해", "머해", "뭐하냐",
    # 인사·감사·사과
    "안녕", "안뇽", "안녕하세요", "하이", "하잉", "바이", "잘가", "잘자", "고마워", "고마웡", "감사", "감사합니다",
    "미안", "미안해", "쏘리", "잠깐", "잠만", "잠시만", "빨리", "ㄱㄱㄱ",
    # 영문
    "ok", "okay", "yes", "no", "hi", "bye", "lol", "gg",
}
# 비교 전에 지우는 것: 웃음·울음 초성(ㅋ ㅎ ㅠ ㅜ ㅡ), 문장부호, 이모지·기호, 공백
_STRIP = re.compile(r"[ㅋㅎㅠㅜㅡ]+|[^\wㄱ-ㅎㅏ-ㅣ가-힣]+|_")
_SYL = re.compile(r"[가-힣A-Za-z0-9]")
_JAMO_RUN = re.compile(r"[ㄱ-ㅎㅏ-ㅣ]+")


def _norm(text: str) -> str:
    t = unicodedata.normalize("NFC", text or "").lower()
    return re.sub(r"\s+", " ", t).strip()


def _squeeze(s: str) -> str:
    """같은 글자 반복을 하나로 ('ㅇㅇㅇ' -> 'ㅇ')."""
    return re.sub(r"(.)\1+", r"\1", s)


def _filler_key(t: str) -> str:
    return _squeeze(_STRIP.sub("", t))


_FILLER_KEYS = {_squeeze(f) for f in FILLERS}


def syllables(text: str) -> int:
    return len(_SYL.findall(_norm(text)))


def hostile(text: str) -> str:
    """'strong' | 'weak' | '' — 욕설·비하 표현이 있는가."""
    t = _norm(text)
    compact = t.replace(" ", "")
    runs = _JAMO_RUN.findall(t)
    if any(_ONLY_FINGER.fullmatch(r) for r in runs) or any(j in compact for j in HOSTILE_JAMO_STRONG):
        return "strong"
    if any(j in compact for j in HOSTILE_JAMO_WEAK) or any(w in compact for w in HOSTILE_WORDS):
        return "weak"
    return ""


def is_filler(text: str) -> bool:
    """맞장구·인사·되묻기·웃음·문장부호뿐인 메시지인가. 웃음만('ㅋㅋㅋ')·물음표만('??')도 해당."""
    t = _norm(text)
    if not t or hostile(t):
        return False
    return _filler_key(t) in _FILLER_KEYS or _filler_key(t) == ""


def short_guard(text: str, score: float):
    """(점수, 사유) — 사유: 'short_filler' | 'short_unsure' | 'jamo_profanity' | None (그대로)."""
    if not ENABLE or not (text or "").strip():
        return score, None
    if syllables(text) > SHORT_MAX_SYL:
        return score, None
    h = hostile(text)
    if h:
        if h == "strong" and ENABLE_FLOOR and score < JAMO_FLOOR:
            return JAMO_FLOOR, "jamo_profanity"
        return score, None
    if score < TOX_THRESHOLD:
        return score, None
    if is_filler(text):
        return min(score, SHORT_CAP), "short_filler"
    if score < SHORT_UNSURE_HI:
        return min(score, SHORT_CAP), "short_unsure"
    return score, None
