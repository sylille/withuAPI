# -*- coding: utf-8 -*-
"""
target_resolver.py — 피해자(표적) 식별 보강 (v0.3.2)

문제
  기존 name_mention은 *발화자 ID* 문자열을 공격 메시지 본문에서 찾는다.
  카카오톡 엑셀(검증 코퍼스)에서는 발화자 ID가 닉네임이라 의미가 있었지만,
  실서버에서는 발화자 ID가 participant_code(C013)라 아이들이 이 코드를 칠 일이 없다.
  게다가 앱이 보내는 창은 5~10개라, 이름 없이 열리는 경로(turn_adjacency)는
  "공격 6개 이상" 조건 때문에 사실상 열리지 않는다.

보강 (기존 evaluate_window가 False일 때만 시도. 기존에 열리던 경우는 그대로)
  1. 대화방 기록 — 서버가 방마다 최근 메시지를 쌓아 둔다(기본 60개·20분). 창(5~10개)이 아니라
     기록 전체를 본다. 전송 전 호출(track_bystander=false)은 기록에 넣지 않는다.
  2. 피해자 후보 점수 = 답장 지목×6 + 이름 지목×3 + 공격 직후 반응×2
     - 답장 지목: Message.reply_to_message_id 가 가리키는 메시지의 발신자 (앱에 답장 기능이 있을 때)
     - 이름 지목: participants[].display_name / aliases 를 공격 메시지에서 찾음.
                  창에서 말하지 않은 아이도 지목 가능. 2글자 이름은 조사 경계를 확인(하니 ≠ 하니까)
     - 공격 직후 반응: 공격 뒤 3메시지 안에 그 아이가 말함. 웃음만(ㅋㅋ, 인정)은 장난으로 보고 제외
  3. 근거별 조건
     - explicit_target : 바로 판정
     - name_mention    : 가해자 공격 ≥2, 또는 지목된 아이가 반응
     - repeated_target : 가해자 1명 공격 ≥4, 같은 아이 반응 ≥2, 2위 후보보다 2배 이상
  4. 마지막에 서버의 judge_event()를 그대로 통과해야 한다 (신뢰도·가해 집중도·비대칭).
     피해자도 같이 욕하면 mutual_banter로 걸러진다. 가해 집중도는 '가해자 무리' 기준이라
     여럿이 한 명을 괴롭히는 경우도 잡힌다.

v0.3.2 — 방향(누가 누구를) 오류 수정
  v0.3.1의 repeated_target은 "공격 직후에 말한 아이"를 피해자로 봤다. 그래서
    (a) 공격에 맞장구친 같은 편 아이가 피해자로 잡히고,
    (b) "하지 말라고" 같은 피해자의 항의가 공격으로 세어져 가해자·피해자가 뒤바뀌었다.
  이제 메시지마다 성격(stance)을 본다.
    protest  저항·호소  하지마, 그만해, 지워줘, 왜 나만, ㅠㅠ      -> 피해자 근거. 공격으로 세지 않음(저항 가드)
    agree    맞장구      ㅇㅈ, 팩트, ㄹㅇ, 맞아, ㅋㅋ                -> 가해자 편. 피해자 후보에서 뺌
    dismiss  무마        장난인데, 왜 화냄, 예민하네               -> 바로 앞에 다른 아이의 항의가 있으면 공격으로 셈
    defend   말리기      그만 싸워, 너무 심하잖아, 얘들아 진정해   -> 주변인의 방어. 공격으로도 피해자 근거로도 세지 않음
    neutral  그 밖
  repeated_target의 '반응 수'는 이제 (저항 + 그 밖의 반응 − 맞장구)로 센다. 맞장구가 더 많은 아이는
  반응만으로는 피해자가 되지 않는다. 검증 코퍼스에서 피해자 반응의 88%는 저항 표현이 없는 평범한
  말이라, 저항 표현을 필수로 하지는 않았다 (필수로 하려면 WITHU_REPEAT_MIN_PROTEST=1 이상).
  이미지 메시지(has_image) 뒤에 다른 아이가 항의하면 그 이미지도 공격으로 센다.

v0.3.3 — 앱팀 2차 보고(사후·추수검사 대본 8편, 사용성 평가 대본) 반영
  (1) 항의 표현 보강: 저장하지 마, 놀리지 마, 안 귀여워, 웃기지 않아, 싫어 …
  (2) 항의한 아이 보호(protester guard): 이미 항의한 적이 있고 욕설·비하 낱말을 쓴 적이 없는 아이의 말은
      모듈 A 점수가 높아도 공격으로 세지 않고 항의로 본다. 목록에 없는 항의("하나도 안 귀여워")가
      공격으로 세어져 피해자가 가해자로 바뀌던 문제를 막는다.
  (3) 항의한 아이가 둘 이상이면 먼저, 더 많이 항의한 아이가 피해자다. 나머지의 항의는 말리기(defend)로 본다.
      "본인이 싫으면 그만해야지", "서아가 싫다잖아" 같은 3인칭 표현은 처음부터 말리기다.
  (4) victim_support=strong 은 '피해자 본인의 항의 메시지 2개 이상'으로 센다 (예전: 항의가 뒤따른 공격 2개 이상).
      항의 메시지는 가해자의 말(공격으로 세어지지 않은 말 포함) 뒤 3개 안에 있으면 센다.
  (5) 이름·답장으로 지목된 아이나 항의한 아이가 있으면, 공격 뒤에 평범하게 말했을 뿐인 아이는 피해자 후보에서 뺀다.
      다른 아이 이야기를 하는 말("걔 또 그러네", "도현이 진짜 왜 그래")은 피해자 근거로 세지 않는다.
  (6) 배제 발화 규칙: 명단의 이름 + 배제 표현("재희는 빼고", "도현이 부르지 마")은 공격으로 세고 그 아이를 지목한 것으로 본다.
      모듈 C(배제)가 꺼져 있어도 배제 대본에서 사건이 열린다. WITHU_ENABLE_EXCLUSION_RULE=0 으로 끈다.

연동
  schemas.py     : AnalyzeRequest에 participants, Message에 reply_to_message_id 추가
  app.py         : /analyze 첫 줄에 set_request_context(req)
  withu_analyze  : from .target_resolver import evaluate_window_v2 as evaluate_window
표준 라이브러리만 사용.
"""
from __future__ import annotations

import contextvars
import math
import os
import re
import threading
import time
from collections import Counter, deque
from types import SimpleNamespace
from typing import Any, Iterable, Optional

from .check_chat_excel import TOX_THRESHOLD, evaluate_window as _orig_evaluate_window, judge_event

try:  # same tunables as the server, if present
    from .check_chat_excel import MIN_AGGR_MSGS, SECONDARY_RATIO
except ImportError:  # pragma: no cover
    MIN_AGGR_MSGS, SECONDARY_RATIO = 2, 0.34

# ---------------------------------------------------------------- tunables ---
def _env(name, default, cast=float):
    try:
        return cast(os.environ.get(name, default))
    except ValueError:
        return default

HISTORY_MAX_MSGS   = _env("WITHU_HISTORY_MAX_MSGS", 60, int)    # 방별 기록 길이
HISTORY_MAX_SEC    = _env("WITHU_HISTORY_MAX_SEC", 1200)         # 기록 보존 (초)
REPEAT_MIN_ATTACKS = _env("WITHU_REPEAT_MIN_ATTACKS", 4, int)    # 가해자 1명의 공격 수
REPEAT_MIN_REPLIES = _env("WITHU_REPEAT_MIN_REPLIES", 2, int)    # 표적 아이의 반응 수
REPEAT_REPLY_SPAN  = _env("WITHU_REPEAT_REPLY_SPAN", 3, int)     # 공격 뒤 몇 메시지 안의 반응
REPEAT_SEPARATION  = _env("WITHU_REPEAT_SEPARATION", 2.0)        # 1위 반응 수 ≥ 2위 × 이 값
NAME_MIN_ATTACKS   = _env("WITHU_NAME_MIN_ATTACKS", 2, int)      # 이름 지목만으로 열리는 공격 수. 지목된 아이가 반응하면 1개로도 열림
ENABLE_REPEAT      = os.environ.get("WITHU_ENABLE_REPEAT", "1") != "0"
# v0.3.2
ENABLE_RESIST_GUARD = os.environ.get("WITHU_ENABLE_RESIST_GUARD", "1") != "0"  # 항의 발화를 공격으로 세지 않음
ENABLE_PSEUDO       = os.environ.get("WITHU_ENABLE_PSEUDO_ATTACK", "1") != "0" # 무마 발화·이미지를 공격으로 셈
RESIST_CAP          = _env("WITHU_RESIST_CAP", 0.30)        # 항의 발화의 점수 상한 (TOX_THRESHOLD 미만)
PSEUDO_CB           = _env("WITHU_PSEUDO_CB", 0.60)         # 무마 발화·이미지에 주는 점수
REPEAT_MIN_PROTEST  = _env("WITHU_REPEAT_MIN_PROTEST", 0, int)  # 반복 표적: 꼭 있어야 하는 '저항' 반응 수 (0 = 필수 아님)
W_PROTEST_REPLY     = _env("WITHU_PROTEST_REPLY_WEIGHT", 3.0)   # 저항 반응 1번의 점수 (그 밖의 반응은 2, 맞장구는 -2)
# v0.3.3
ENABLE_PROTESTER_GUARD = os.environ.get("WITHU_ENABLE_PROTESTER_GUARD", "1") != "0"  # 항의한 아이의 말은 공격으로 세지 않음
ENABLE_EXCLUSION_RULE  = os.environ.get("WITHU_ENABLE_EXCLUSION_RULE", "1") != "0"   # 이름 + 배제 표현을 공격으로 셈
STRONG_MIN_PROTESTS    = _env("WITHU_STRONG_MIN_PROTESTS", 2, int)   # victim_support=strong 에 필요한 본인 항의 메시지 수
W_SOFT_MENTION         = _env("WITHU_SOFT_MENTION_WEIGHT", 0.0)      # 공격이 아닌 말에서 제3자로 이름이 불린 경우 (기본 꺼짐: 코퍼스에서 오판이 늘었음)
PREFER_BACKED          = os.environ.get("WITHU_PREFER_BACKED", "1") != "0"      # 지목·항의 근거가 있는 후보를 먼저 봄
BACKED_BY_PROTEST      = os.environ.get("WITHU_BACKED_BY_PROTEST", "0") != "0"  # 항의한 아이도 '근거 있는 후보'로 침
PRIMARY_PROTESTER      = os.environ.get("WITHU_PRIMARY_PROTESTER", "1") != "0"  # 항의한 아이가 여럿이면 당사자 1명만
SKIP_THIRD_PERSON      = os.environ.get("WITHU_SKIP_THIRD_PERSON", "1") != "0"  # 남 얘기하는 반응은 피해자 근거에서 뺌

# ----------------------------------------------------- per-request context ---
_CTX: contextvars.ContextVar[dict] = contextvars.ContextVar("withu_target_ctx", default={})


def set_request_context(req: Any) -> None:
    """Call once at the top of the /analyze handler with the parsed request."""
    room_id = getattr(req, "room_id", None)
    parts = getattr(req, "participants", None) or []
    if parts:
        ROSTERS.update(room_id, parts)
    metas = [_msg_meta(m) for m in (getattr(req, "context", None) or [])]
    nm = getattr(req, "new_message", None)
    if nm is not None:
        meta = _msg_meta(nm)
        meta["img"] = meta["img"] or bool(getattr(req, "has_image", False))   # has_image는 new_message에 대한 값
        metas.append(meta)
    _CTX.set({
        "room_id": room_id,
        "commit": bool(getattr(req, "track_bystander", True)),
        "messages": metas,
    })


def _get(o, k, default=None):
    return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)


def _msg_meta(m) -> dict:
    return {"mid": _get(m, "message_id"), "reply_to": _get(m, "reply_to_message_id"),
            "speaker": _get(m, "participant_code"), "text": _get(m, "text") or "",
            "img": bool(_get(m, "has_image", False))}


# ------------------------------------------------------------------ roster ---
_TOK = re.compile(r"[가-힣A-Za-z0-9]+")
_SURNAMES = set("김이박최정강조윤장임한오서신권황안송류전홍고문양손배백허유남심노하곽성차주우구민진나지엄채원천방공현함변염여추도소석선설마길연위표명기반왕금옥육인맹제모탁국어은편용예경봉사부가복태목형피두감호계")
_STOP = {"너", "니", "나", "야", "우리", "진짜", "그냥", "ㅋㅋ"}
# 성을 떼면 흔한 낱말이 되는 경우는 떼지 않는다 (예: 노친구 -> 친구)
_COMMON_2 = {"친구", "사람", "학교", "선생", "엄마", "아빠", "동생", "언니", "오빠", "누나", "형아",
             "진짜", "정말", "하나", "우리", "너무", "그냥", "오늘", "내일", "다들", "모두", "바보",
             "공부", "숙제", "게임", "사랑", "행복", "최고", "대박", "인정", "가능", "시간", "생각"}


def name_tokens(display_name: str, aliases: Iterable[str] = ()) -> set[str]:
    """'김하늘' -> {'김하늘','하늘'}; '둠칫 야옹13' -> {'둠칫','야옹13','둠칫야옹13'}; + aliases."""
    out: set[str] = set()
    for raw in [display_name or "", *aliases]:
        raw = raw.strip()
        if not raw:
            continue
        out.add(re.sub(r"\s+", "", raw))
        out.update(_TOK.findall(raw))
        if re.fullmatch(r"[가-힣]{3}", raw) and raw[0] in _SURNAMES and raw[1:] not in _COMMON_2:
            out.add(raw[1:])                 # 성 뺀 이름: 김하늘 -> 하늘
    return {t for t in out if len(t) >= 2 and t not in _STOP}


# 2글자 이름은 다른 낱말 속에서 잘못 잡히기 쉽다 ("하니" in "하니까").
# 그래서 앞뒤가 한글이 아니어야 하고, 뒤에는 호격·조사만 허용한다: 하늘아, 하늘이가, 민준한테 …
_PARTICLE = r"(?:아|야|이|이가|이는|이도|이랑|이한테|이를|이야|가|는|은|을|를|도|랑|이랑|한테|에게|님|씨|쌤|아\s|야\s)?"


def name_pattern(tokens: set[str]):
    if not tokens:
        return None
    longs = sorted((re.escape(t) for t in tokens if len(t) >= 3), key=len, reverse=True)
    shorts = sorted(re.escape(t) for t in tokens if len(t) == 2)
    parts = []
    if longs:
        parts.append("(?:" + "|".join(longs) + ")")
    if shorts:
        parts.append("(?<![가-힣])(?:" + "|".join(shorts) + ")" + _PARTICLE + "(?![가-힣])")
    return re.compile("|".join(parts))


class _Rosters:
    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: dict[str, dict[str, "re.Pattern"]] = {}

    def update(self, room_id, participants) -> None:
        table = {}
        for p in participants:
            code = _get(p, "participant_code")
            if not code:
                continue
            table[code] = name_pattern(name_tokens(_get(p, "display_name") or "", _get(p, "aliases") or []))
        with self._lock:
            self._rooms[room_id] = table

    def get(self, room_id) -> dict[str, "re.Pattern"]:
        with self._lock:
            return dict(self._rooms.get(room_id, {}))


ROSTERS = _Rosters()

# ------------------------------------------------------------ room history ---
class _History:
    """Recent messages per room, merged from successive /analyze windows."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: dict[str, deque] = {}

    @staticmethod
    def _key(it):
        return (it.get("speaker"), (it.get("text") or "").strip())

    def merged(self, room_id, window: list[dict], commit: bool) -> list[dict]:
        now = time.time()
        with self._lock:
            hist = self._rooms.setdefault(room_id, deque(maxlen=HISTORY_MAX_MSGS))
            while hist and now - hist[0]["_t"] > HISTORY_MAX_SEC:
                hist.popleft()
            old = list(hist)
            new = self._new_part(old, window)
            stamped = [{**it, "_t": now} for it in new]
            if commit:
                hist.extend(stamped)
            return (old + stamped)[-HISTORY_MAX_MSGS:]

    def _new_part(self, old: list[dict], window: list[dict]) -> list[dict]:
        if not old:
            return list(window)
        ids = {it.get("mid") for it in old if it.get("mid")}
        if any(it.get("mid") for it in window):
            return [it for it in window if not it.get("mid") or it["mid"] not in ids]
        # no ids: largest k such that old[-k:] == window[:k]
        ok, wk = [self._key(x) for x in old], [self._key(x) for x in window]
        for k in range(min(len(ok), len(wk)), 0, -1):
            if ok[-k:] == wk[:k]:
                return list(window[k:])
        return list(window)

    def clear(self, room_id=None):
        with self._lock:
            self._rooms.clear() if room_id is None else self._rooms.pop(room_id, None)


HISTORY = _History()

# ------------------------------------------------------- response patterns ---
_PLAYFUL = re.compile(r"^[\sㅋㅎᄏᄒㄱㅇㄷㅈㄹ~!.?^]*(인정|ㅇㅈ|ㄹㅇ|ㄱㅇㄷ|개웃|웃기|ㅋㅋ|ᄏᄏ)?[\sㅋㅎᄏᄒ~!.?^]*$")
_DISTRESS = re.compile(
    r"왜\s*그래|왜그래|왜\s*저래|왜저럼|왜\s*나한테|나한테|내가\s*뭘|내가\s*왜|하지\s*마|그만|싫어|아파|속상|"
    r"울고|울어|눈물|ㅠ|ㅜ|흑|신고|선생님|쌤|미안|잘못했|제발|그러지\s*마|억울|기분\s*나빠|상처|무서|괴롭|짜증")


def is_playful(text: str) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(_PLAYFUL.fullmatch(t)) and not _DISTRESS.search(t)


# ------------------------------------------------------------------ stance ---
# 욕설·비하가 섞이면 항의로 보지 않는다 ("그만해 병신아"는 되받아치는 것, "ㅈㄹ하지 말고"는 공격).
_HOSTILE = ("시발", "씨발", "ㅅㅂ", "ㅆㅂ", "병신", "ㅂㅅ", "새끼", "ㅅㄲ", "지랄", "ㅈㄹ", "꺼져", "꺼지", "ㄲㅈ",
            "죽어", "죽을", "죽는", "죽인", "닥쳐", "닥치", "ㄷㅊ", "존나", "ㅈㄴ", "개새", "애미", "좆", "역겨", "역겁",
            "찐따", "냄새", "돼지", "못생", "쓰레기", "나가라", "한심", "멍청", "등신", "재수")
_LAUGH = re.compile(r"[ㅋᄏ]{2,}|[ㅎᄒ]{2,}|ㅋ\s*$")
# 분명한 항의: 그만하라·지우라는 요구, 싫다는 말, 왜 나한테 그러느냐는 말
_PROTEST_HARD = re.compile(
    r"(?<![가-힣ㄱ-ㅎ])하지\s*(?:마|말라|말아|말랬)"          # 하지마, 하지 말라고  (말하지마·'하지 말고'는 아님)
    r"|그만\s*(?:해|하|좀|둬|두)|그만\s*[!.~]*\s*$"
    r"|지워|지우라|삭제\s*해|내려\s*(?:줘|달|주)|올리지\s*마|찍지\s*마|보내지\s*마|퍼뜨리지\s*마|캡처\s*하지\s*마"
    # v0.3.3: '○○하지 마' (말하지 마·부르지 마는 가해자도 쓰므로 넣지 않는다)
    r"|(?:저장|공유|캡[처쳐]|전달|유포|복사|편집|합성)\s*하지\s*(?:마|말라|말아|말랬)"
    r"|(?:놀리|웃|비웃|퍼\s*가|퍼\s*나르|돌리|보여\s*주|따라\s*하|건드리|괴롭히)지\s*(?:마|말라|말아|말랬)"
    r"|(?:하나도\s*)?안\s*(?:귀여|귀엽|웃[기겨])|웃기지\s*않|귀엽지\s*않|안\s*웃긴"
    r"|싫어(?![하해])|싫거든|싫단\s*말|싫음|싫다고|하기\s*싫"
    r"|왜\s*(?:계속\s*|자꾸\s*|맨날\s*)?나만|왜\s*(?:계속\s*|자꾸\s*)?나한테|나한테\s*왜|내가\s*(?:뭘|왜)|내가\s*뭐\s*(?:했|잘못)")
# 약한 신호: 속상함·사과·호소. 가해자 쪽도 흔히 쓰는 말이라 항의로는 세되 '분명한 항의'로는 보지 않는다
_PROTEST_SOFT = re.compile(
    r"왜\s*그래|왜\s*그러"
    r"|기분\s*나[빠쁘]|속상|상처|억울|창피|무서|괴롭"
    r"|ㅠ|ㅜ|흑흑|제발|선생님|쌤한테|신고|미안|잘못했|죄송")


class _Either:
    """_PROTEST.search(t) — 분명한 항의 또는 약한 신호."""
    @staticmethod
    def search(t):
        return _PROTEST_HARD.search(t) or _PROTEST_SOFT.search(t)


_PROTEST = _Either()


def is_hard_protest(text: str) -> bool:
    return stance(text) == "protest" and bool(_PROTEST_HARD.search(text or ""))


# 남의 일을 말리는 말 (주변인의 방어). 1인칭 표현이 같이 있으면 본인의 항의로 본다.
_MEDIATE = re.compile(
    r"싸우지\s*마|그만\s*싸워|싸움|진정|너무\s*심|심했|심하잖|심한\s*거|너무하|얘들아|애들아|니네|너네|너희"
    r"|걔한테|쟤한테|[가-힣]{2,4}(?:이|)한테\s*(?:왜|그러지|그만|뭐라)"
    # v0.3.3: 남의 일로 말하는 표현 (3인칭·당위·청유)
    r"|본인(?:이|은|도|한테)|(?:걔|쟤|얘)(?:가|는|도)\s*싫|싫어하잖|싫다잖|싫대|싫다는데|싫다고\s*하잖|싫다\s*하잖"
    r"|그만해야|하지\s*말아야|지워야|지워\s*줘라|사과해|사과\s*하[라자]|그러면\s*안\s*[되돼]|그러는\s*거\s*아니"
    r"|아닌\s*[것거]\s*같|그만하자|하지\s*말자|보내지\s*말자|올리지\s*말자")
_FIRST_PERSON = re.compile(r"(?<![가-힣])(?:나만|나한테|나를|나도|내가|내\s|나\s|날\s|저한테)")
_DISMISS = re.compile(
    r"장난인데|장난이잖|장난\s*(?:인|이)\s*거|장난도\s*못|농담인데|웃자고"
    r"|왜\s*화\s*[내냄났남]|화났어\s*\?|화났냐|삐[졌짐쳤지]|예민|오바|진지충|진지\s*빨"
    r"|뭘\s*그런\s*걸|그걸\s*가지고|별것도\s*아닌|찡찡|징징")
_AGREE = re.compile(r"ㅇㅈ|인정|팩트|ㄹㅇ|레알|맞아|맞네|맞는\s*말|그니까|그러니까|그러게|그치(?!만)|내\s*말이|동의|ㄱㅇㄷ|개웃|웃기|웃겨")
# v0.3.3: 그 자리에 없는/말하지 않는 아이를 남처럼 부르는 말 ("걔 또 그러네"). 1인칭이 같이 있으면 본인 이야기로 본다.
_THIRD_PERSON = re.compile(r"(?<![가-힣])(?:걔|쟤|얘|그\s*애|저\s*애)(?:는|가|도|랑|한테|를|네|\s|$)")
# v0.3.3: 배제 표현. 명단의 이름(말한 아이 본인 제외)과 같은 메시지에 있을 때만 공격으로 센다.
_EXCLUDE = re.compile(
    r"빼자|뺄까|빼\s*버리|빼야|빼고(?:\s*\S+){0,2}?\s*(?:하자|놀자|가자|만들자|만들까|만들어|파자|할래|할까|모이자|초대|우리끼리)"
    r"|(?:은|는)\s*빼고|빼고\s*[ㅋㅎ~!.\s]*$"
    r"|부르지\s*마|부르지\s*말자|초대\s*하지\s*마|초대\s*하지\s*말자|끼워\s*주지\s*마|껴\s*주지\s*마|안\s*끼워|끼지\s*마"
    r"|(?:랑|이랑|하고)\s*(?:놀지|말하지|얘기하지)\s*(?:마|말자)|말\s*걸지\s*(?:마|말자)|상대\s*하지\s*(?:마|말자)"
    r"|한테(?:는|도)?\s*(?:말하지|알리지)\s*(?:마|말자)|없는\s*(?:방|단톡|톡방)|무시\s*하자|무시해\s*버려|투명\s*인간")


def stance(text: str) -> str:
    """'protest' | 'defend' | 'dismiss' | 'agree' | 'hostile' | 'neutral' — 메시지의 성격 (점수와 무관, 낱말 규칙)."""
    t = (text or "").strip()
    if not t:
        return "neutral"
    if any(h in t for h in _HOSTILE):
        return "hostile"
    if _DISMISS.search(t):
        return "dismiss"
    laugh = bool(_LAUGH.search(t))
    if _MEDIATE.search(t) and not _FIRST_PERSON.search(t):
        return "neutral" if laugh else "defend"
    if _PROTEST.search(t):
        return "neutral" if laugh else "protest"     # "아 하지마 ㅋㅋㅋ"는 장난일 수 있어 근거로 쓰지 않음
    if _AGREE.search(t) or laugh or is_playful(t):
        return "agree"
    return "neutral"


def _named(text: str, roster: Optional[dict], skip=()) -> list:
    """명단에서 이 메시지에 이름이 나온 아이들의 코드."""
    if not roster or not text:
        return []
    return [c for c, pat in roster.items() if c not in skip and pat is not None and pat.search(text)]


def _excl_target(text: str, roster: Optional[dict], skip=()) -> list:
    """배제 표현이 가리키는 아이: 표현 바로 앞에서 불린 이름 하나 ("지민아 도현이는 빼고 하자" -> 도현). 없으면 뒤의 이름."""
    m = _EXCLUDE.search(text or "")
    if not m or not roster:
        return []
    before, after = [], []
    for c, pat in roster.items():
        if c in skip or pat is None:
            continue
        for nm in pat.finditer(text):
            (before if nm.start() <= m.start() else after).append((nm.start(), c))
    if before:
        return [max(before)[1]]
    return [min(after)[1]] if after else []


def prepare(items: list[dict], pseudo: bool = True, roster: Optional[dict] = None) -> list[dict]:
    """성격 표시 + 저항 가드 + 항의한 아이 보호 + (선택) 무마 발화·이미지·배제 발화를 공격으로 표시.
    원본은 건드리지 않는다. 낮추는 가드는 항상, 올리는 표시는 pseudo=True 일 때만 적용한다."""
    out = []
    for it in items:
        d = dict(it)
        d["st"] = stance(d.get("text"))
        cb = float(d.get("cb") or 0.0)
        if ENABLE_RESIST_GUARD and d["st"] in ("protest", "defend") and cb >= TOX_THRESHOLD:
            d["cb_raw"], d["cb"], d["note"] = cb, min(cb, RESIST_CAP), "resistance_guard"
        out.append(d)

    # v0.3.3 항의한 아이 보호: 이미 항의했고 욕설·비하 낱말을 쓴 적 없는 아이의 '그 밖의 말'은
    # 점수가 높아도 공격이 아니라 항의로 본다 ("하나도 안 귀여워", "웃기지 않아" 처럼 목록에 없는 항의).
    # 조건이 좁다: 그 아이의 첫 항의가 (a) 본인이 공격하기 전이고 (b) 다른 아이의 공격·이미지 바로 뒤(3개 안)여야 한다.
    # 가해자도 "그만해"라고 말하기 때문에, 먼저 공격한 아이나 아무 일 없이 "하지마"라고 한 아이는 보호하지 않는다.
    if ENABLE_PROTESTER_GUARD and ENABLE_RESIST_GUARD:
        hostile = {d["speaker"] for d in out if d["st"] == "hostile"}
        posted_img = {d["speaker"] for d in out if d.get("img")}
        attacked: set = set()           # 지금까지 공격(점수 기준)을 한 아이
        protected: set = set()
        for i, d in enumerate(out):
            who = d["speaker"]
            cb = float(d.get("cb") or 0.0)
            if d["st"] == "protest":
                if _PROTEST_HARD.search(d.get("text") or "") and who not in attacked and who not in hostile \
                        and who not in posted_img and any(
                        o["speaker"] != who and (o.get("img") or float(o.get("cb") or 0.0) >= TOX_THRESHOLD)
                        for o in out[max(0, i - REPEAT_REPLY_SPAN):i]):
                    protected.add(who)
            elif cb >= TOX_THRESHOLD:
                if d["st"] == "neutral" and who in protected:
                    d["cb_raw"], d["cb"], d["note"] = cb, min(cb, RESIST_CAP), "protester_guard"
                    d["st"] = "protest"
                else:
                    attacked.add(who)
    if not (pseudo and ENABLE_PSEUDO):
        return out

    n = len(out)
    last_excl = None                      # (index, [지목된 코드]) — 바로 앞의 이름 있는 배제 발화
    for i, d in enumerate(out):
        who = d["speaker"]
        # v0.3.3 배제 발화: 이름 + 배제 표현. 이름 없이 "걔 빼자"로 이어 받으면 같은 아이를 가리킨 것으로 본다.
        if ENABLE_EXCLUSION_RULE and roster and d["st"] not in ("protest", "defend") \
                and _EXCLUDE.search(d.get("text") or ""):
            named = _excl_target(d.get("text"), roster, skip=(who,))
            if not named and last_excl and i - last_excl[0] <= REPEAT_REPLY_SPAN:
                named = list(last_excl[1])
            if named:
                d["excl"] = named
                last_excl = (i, named)
                if float(d.get("cb") or 0.0) < TOX_THRESHOLD:
                    d["cb_raw"], d["cb"], d["note"] = d.get("cb"), PSEUDO_CB, "exclusion_talk"
                continue
        if float(d.get("cb") or 0.0) >= TOX_THRESHOLD:
            continue
        if d["st"] == "dismiss" and any(o["st"] in ("protest", "defend") and o["speaker"] != who
                                        for o in out[max(0, i - REPEAT_REPLY_SPAN):i]):
            d["cb_raw"], d["cb"], d["note"] = d.get("cb"), PSEUDO_CB, "dismissal_after_protest"
        elif d.get("img") and any(o["st"] == "protest" and o["speaker"] != who
                                  for o in out[i + 1:min(n, i + 1 + REPEAT_REPLY_SPAN)]):
            d["cb_raw"], d["cb"], d["note"] = d.get("cb"), PSEUDO_CB, "image_then_protest"
    return out


# ------------------------------------------------------------- attribution ---
def _aggressors(items):
    aggr = Counter(it["speaker"] for it in items if (it.get("cb") or 0) >= TOX_THRESHOLD)
    if not aggr:
        return [], aggr
    top_s, top_c = aggr.most_common(1)[0]
    keep = max(MIN_AGGR_MSGS, math.ceil(top_c * SECONDARY_RATIO))
    return ([s for s, c in aggr.items() if c >= keep] or [top_s]), aggr


def _sep(values: list[float]) -> float:
    v = sorted(values, reverse=True)
    if not v or v[0] <= 0:
        return 0.0
    return 1.0 if len(v) == 1 else (v[0] - v[1]) / v[0]


def _judge(items, aggressors, aggr, victim, reason, victim_scores, dominance_mode="top"):
    counts = sorted(aggr.values(), reverse=True)
    total, top = sum(counts), (counts[0] if counts else 0)
    agg_sep = 1.0 if len(counts) == 1 else (counts[0] - counts[1]) / counts[0]
    conf = round(0.5 * agg_sep + 0.5 * _sep(list(victim_scores.values())), 3)
    if dominance_mode == "set":   # group bullying: share of all attacks made by the aggressor group
        dom = round(sum(aggr[a] for a in aggressors) / total, 3) if total else 0.0
        conf = round(0.5 + 0.5 * _sep(list(victim_scores.values())), 3)
    else:
        dom = round(top / total, 3) if total else 0.0
    va = aggr.get(victim, 0)
    ok, drop = judge_event(aggressors, victim, reason, conf, dom, va, top, total)
    attr = SimpleNamespace(aggressors=aggressors, victim=victim, victim_reason=reason,
                           confidence=conf, per_speaker={})
    return {"attr": attr, "is_bullying": ok, "drop_reason": drop, "dominance": dom, "victim_aggr": va}


W_EXPLICIT_T, W_MENTION_T, W_REPLY_T = 6.0, 3.0, 2.0


def resolve_target(items, roster, meta_by_mid) -> Optional[dict]:
    """
    피해자 후보마다 신호를 합산해 한 명을 고른다 (기록 전체 기준).
      explicit : 공격 메시지가 답장(reply_to)으로 가리킨 메시지의 발신자      × 6
      mention  : 공격 메시지에 이름(display_name/aliases)이 나온 횟수        × 3  (배제 발화가 가리킨 아이 포함)
      protest  : 가해자의 말 뒤(3메시지 안)에 그 아이가 항의한 메시지 수      × 3
      reply    : 공격 바로 뒤(3메시지 안)에 평범하게 반응한 공격 수            × 2,  맞장구·웃음은 × −2 (가해자 편)
      soft     : 공격이 아닌 말에서 제3자로 이름이 불린 횟수                  × 1.5 ("서아가 싫다잖아", "도현이 또 그러네")
    이름이 나왔다고 무조건 피해자가 아니다 ("우웅아 쟤 봐 ㅋㅋ 역겨워"는 같은 편을 부른 것).
    그래서 반응 패턴과 합산하고, 가장 강한 근거를 victim_reason으로 돌려준다.
    """
    aggressors, aggr = _aggressors(items)
    if not aggressors:
        return None
    aset = set(aggressors)
    items = [it if "st" in it else {**it, "st": stance(it.get("text"))} for it in items]
    n = len(items)
    first_attack = next((i for i, it in enumerate(items)
                         if it["speaker"] in aset and (it.get("cb") or 0) >= TOX_THRESHOLD), n)

    # ---- 1) 항의 메시지: 가해자의 말(공격으로 세어지지 않은 말 포함) 뒤 3개 안에서 가해자가 아닌 아이가 한 항의
    prot_msgs: dict = {}                                         # code -> [메시지 위치]
    for j in range(first_attack + 1, n):
        it = items[j]
        if it["st"] != "protest" or it["speaker"] in aset:
            continue
        if any(o["speaker"] in aset for o in items[max(0, j - REPEAT_REPLY_SPAN):j]):
            prot_msgs.setdefault(it["speaker"], []).append(j)
    # 항의한 아이가 둘 이상이면: 먼저, 더 많이 항의한 아이가 당사자다. 나머지의 항의는 말리기로 본다.
    mediators: set = set()
    if PRIMARY_PROTESTER and len(prot_msgs) > 1:
        primary = max(prot_msgs, key=lambda c: (len(prot_msgs[c]), -prot_msgs[c][0]))
        for c, idx in prot_msgs.items():
            if c == primary:
                continue
            if len(prot_msgs[primary]) >= 2 * len(idx) or \
                    (len(prot_msgs[primary]) > len(idx) and prot_msgs[primary][0] < idx[0]):
                mediators.add(c)
    for c in mediators:
        prot_msgs.pop(c)
    nprot = Counter({c: len(v) for c, v in prot_msgs.items()})
    nhard = Counter({c: sum(1 for j in v if items[j].get("note") == "protester_guard"
                            or _PROTEST_HARD.search(items[j].get("text") or "")) for c, v in prot_msgs.items()})

    # ---- 2) 공격 메시지마다: 답장·이름 지목, 그리고 바로 뒤의 반응
    explicit, mention, soft, excl_target = Counter(), Counter(), Counter(), Counter()
    weak, ally, answered = {}, {}, {}
    for i, it in enumerate(items):
        text = it.get("text") or ""
        is_attack = (it.get("cb") or 0) >= TOX_THRESHOLD
        if not is_attack:
            # 공격이 아닌 말에서 제3자로 이름이 불림 (말리는 말, 맞장구, 남 얘기). 본인·가해자 이름은 제외
            if i > first_attack and it["st"] in ("defend", "agree", "neutral") and not _FIRST_PERSON.search(text):
                for code in _named(text, roster, skip=aset | {it["speaker"]}):
                    soft[code] += 1
            continue
        rt = it.get("reply_to")
        if rt and rt in meta_by_mid:
            tgt = meta_by_mid[rt].get("speaker")
            if tgt and tgt not in aset:
                explicit[tgt] += 1
        excl = {c for c in (it.get("excl") or []) if c not in aset}
        for code in set(_named(text, roster, skip=aset)) | excl:
            mention[code] += 1
        for code in excl:
            excl_target[code] += 1
        if it["speaker"] in aset:
            for j in range(i + 1, min(n, i + 1 + REPEAT_REPLY_SPAN)):
                o = items[j]
                s = o["speaker"]
                if s in aset:
                    continue
                st = o["st"]
                if st == "protest" and s not in mediators:
                    answered.setdefault(s, set()).add(i)         # 항의는 위에서 메시지 수로 셌다
                elif st in ("agree", "dismiss") or is_playful(o.get("text")):
                    ally.setdefault(s, set()).add(i)             # 공격에 맞장구 = 가해자 편
                elif st in ("defend", "protest"):
                    continue                                     # 말리는 말 = 주변인의 방어. 피해자 근거로 세지 않음
                elif SKIP_THIRD_PERSON and (_THIRD_PERSON.search(o.get("text") or "") or _named(o.get("text"), roster, skip=aset | {s})) \
                        and not _FIRST_PERSON.search(o.get("text") or ""):
                    continue                                     # 다른 아이 이야기를 하는 말 = 본인이 표적이 아님
                else:
                    weak.setdefault(s, set()).add(i)
    nweak = Counter({k: len(v - answered.get(k, set())) for k, v in weak.items()})
    nally = Counter({k: len(v - answered.get(k, set()) - weak.get(k, set())) for k, v in ally.items()})
    # 반응 수 = 항의 + 그 밖의 반응 − 맞장구. 0 이하면 반응만으로는 피해자 후보가 아니다 (이름·답장 지목은 유효)
    nrep = Counter({c: nprot[c] + nweak[c] - nally[c] for c in set(nprot) | set(nweak)})
    nrep = Counter({c: v for c, v in nrep.items() if v > 0})
    cands = set(explicit) | set(mention) | set(nrep)
    # 지목됐거나 항의한 아이가 있으면, 공격 뒤에 평범하게 말했을 뿐인 아이는 후보에서 뺀다
    # (그냥 이름이 불린 것만으로는 빼지 않는다. 같은 편을 부르는 경우가 많아서 점수로 겨룬다.)
    backed = {c for c in cands if explicit[c] or excl_target[c] or (BACKED_BY_PROTEST and nprot[c])}
    if backed and PREFER_BACKED:
        cands = backed
    if not cands:
        return None
    score = {c: W_EXPLICIT_T * explicit[c] + W_MENTION_T * mention[c] + W_SOFT_MENTION * soft[c]
                + (max(0.0, W_PROTEST_REPLY * nprot[c] + W_REPLY_T * (nweak[c] - nally[c])) if c in nrep else 0.0)
             for c in cands}
    victim = max(score, key=score.get)
    top_attacks = max(aggr.values())
    if explicit[victim]:
        reason = "explicit_target"
    elif mention[victim]:
        reason = "name_mention"
        if top_attacks < NAME_MIN_ATTACKS and nrep[victim] == 0:
            return _fail(aggressors, victim, reason, "name_single_attack")
    else:
        reason = "repeated_target"
        if not ENABLE_REPEAT:
            return None
        if top_attacks < REPEAT_MIN_ATTACKS:
            return _fail(aggressors, victim, reason, "not_repeated")
        if nrep[victim] < REPEAT_MIN_REPLIES or nprot[victim] < REPEAT_MIN_PROTEST:
            return _fail(aggressors, victim, reason, "no_victim_response")
        second = sorted(score.values(), reverse=True)[1] if len(score) > 1 else 0.0
        if second and score[victim] < REPEAT_SEPARATION * second:
            return _fail(aggressors, victim, reason, "ambiguous_target")
    out = _judge(items, aggressors, aggr, victim, reason, score, dominance_mode="set")
    out["victim_support"] = _support(reason, victim, nhard)
    out["victim_protests"] = nhard[victim]
    return out


def _support(reason, victim, nprot) -> str:
    """근거가 강한가: 답장·이름으로 지목됐거나, 그 아이가 직접 2번 이상 분명하게 항의했고 그만큼 항의한 다른 아이가 없다."""
    if reason in STRONG_REASONS:
        return "strong"
    others = max((v for c, v in nprot.items() if c != victim), default=0)
    return "strong" if nprot[victim] >= STRONG_MIN_PROTESTS and others * 2 <= nprot[victim] else "weak"


def protest_counts(items, aggressors) -> Counter:
    """가해자가 정해져 있을 때, 가해자의 말 뒤 3개 안에서 다른 아이들이 한 '분명한 항의' 메시지 수 (말리기로 본 항의는 제외)."""
    r = Counter()
    aset = set(aggressors or [])
    first = {}
    seen_aggr = False
    for j, it in enumerate(items):
        if it["speaker"] in aset:
            seen_aggr = seen_aggr or (it.get("cb") or 0) >= TOX_THRESHOLD
            continue
        if seen_aggr and it.get("st") == "protest" and (it.get("note") == "protester_guard"
                                                        or _PROTEST_HARD.search(it.get("text") or "")) \
                and any(o["speaker"] in aset
                                                             for o in items[max(0, j - REPEAT_REPLY_SPAN):j]):
            r[it["speaker"]] += 1
            first.setdefault(it["speaker"], j)
    if PRIMARY_PROTESTER and len(r) > 1:
        primary = max(r, key=lambda c: (r[c], -first[c]))
        for c in [c for c in r if c != primary]:
            if r[primary] >= 2 * r[c] or (r[primary] > r[c] and first[primary] < first[c]):
                del r[c]
    return r


STRONG_REASONS = ("explicit_target", "name_mention")


def _fail(aggressors, victim, reason, drop):
    return {"attr": SimpleNamespace(aggressors=aggressors, victim=victim, victim_reason=reason,
                                    confidence=0.0, per_speaker={}),
            "is_bullying": False, "drop_reason": drop, "dominance": 0.0, "victim_aggr": 0}


def _attack_mids(items, aggressors) -> list:
    """서버가 공격으로 센 메시지의 message_id (가해자 발화만). 방관 판정부가 사건 메시지를 찾는 데 쓴다."""
    aset = set(aggressors or [])
    return [it["mid"] for it in items
            if it.get("mid") and it["speaker"] in aset and float(it.get("cb") or 0.0) >= TOX_THRESHOLD]


# --------------------------------------------------------------- public API ---
def evaluate_window_v2(window: list[dict], module_b_window=None, *, room_id=None,
                       participants=None, commit: Optional[bool] = None) -> dict:
    """Drop-in for check_chat_excel.evaluate_window. Same return shape, plus 'target_source'."""
    ctx = _CTX.get()
    room_id = room_id if room_id is not None else ctx.get("room_id")
    commit = ctx.get("commit", True) if commit is None else commit
    if participants:
        ROSTERS.update(room_id, participants)
    roster = ROSTERS.get(room_id)

    # attach message ids / reply_to from the request, when the window lines up with it
    metas = ctx.get("messages") or []
    window = [dict(it) for it in window]
    if len(metas) == len(window):
        for it, m in zip(window, metas):
            it.setdefault("mid", m["mid"])
            it.setdefault("reply_to", m["reply_to"])
            if m.get("img"):
                it["img"] = True

    hist_raw = HISTORY.merged(room_id, window, commit) if room_id is not None else window
    # 가드(항의·말리기·항의한 아이 보호)는 방 기록 전체를 보고 정한다. 창(5~10개)만 보면 앞서 한 항의가 안 보인다.
    guarded = _window_part(prepare(hist_raw, pseudo=False, roster=roster), window) \
        or prepare(window, pseudo=False, roster=roster)
    base = _orig_evaluate_window(guarded, module_b_window) if module_b_window is not None \
        else _orig_evaluate_window(guarded)
    hist = prepare(hist_raw, roster=roster)
    if base["is_bullying"]:
        aggr = base["attr"].aggressors
        nprot = protest_counts(hist, aggr)
        return {**base, "target_source": "window", "attack_mids": _attack_mids(guarded, aggr),
                "victim_support": _support(base["attr"].victim_reason, base["attr"].victim, nprot),
                "victim_protests": nprot[base["attr"].victim]}

    meta_by_mid = {it["mid"]: it for it in hist if it.get("mid")}
    r = resolve_target(hist, roster, meta_by_mid)
    if r and r["is_bullying"]:
        return {**r, "target_source": "room_history" if len(hist) > len(window) else "window",
                "attack_mids": _attack_mids(hist, r["attr"].aggressors),
                "attack_notes": sorted({it["note"] for it in hist if it.get("note") in
                                        ("exclusion_talk", "image_then_protest", "dismissal_after_protest")
                                        and it["speaker"] in set(r["attr"].aggressors)})}
    detail = [f"{r['attr'].victim_reason}:{r['drop_reason']}"] if r else []
    return {**base, "target_source": "window", "drop_detail": detail}


def _window_part(prepared_hist: list[dict], window: list[dict]) -> Optional[list]:
    """방 기록 전체로 가드를 적용한 결과에서 이번 창에 해당하는 메시지들을 창의 순서대로 꺼낸다. 못 맞추면 None."""
    if len(prepared_hist) < len(window):
        return None
    if window and all(it.get("mid") for it in window):
        by_mid = {it["mid"]: it for it in prepared_hist if it.get("mid")}
        return [by_mid[it["mid"]] for it in window] if all(it["mid"] in by_mid for it in window) else None
    tail = prepared_hist[len(prepared_hist) - len(window):]
    same = all(a["speaker"] == b["speaker"] and (a.get("text") or "") == (b.get("text") or "")
               for a, b in zip(tail, window))
    return tail if same else None


def message_flags(text: str, speaker: Optional[str] = None, room_id=None) -> dict:
    """전송 전 경고(cb_score)용: 이 메시지 하나의 성격과 배제 발화 여부. 방 기록은 바꾸지 않는다."""
    room_id = room_id if room_id is not None else _CTX.get().get("room_id")
    roster = ROSTERS.get(room_id) if room_id is not None else {}
    st = stance(text)
    excl = []
    if ENABLE_EXCLUSION_RULE and st not in ("protest", "defend") and _EXCLUDE.search(text or ""):
        excl = _excl_target(text, roster, skip=(speaker,))
    return {"stance": st, "exclusion_targets": excl}
