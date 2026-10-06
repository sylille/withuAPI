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
_PROTEST = re.compile(
    r"(?<![가-힣ㄱ-ㅎ])하지\s*(?:마|말라|말아|말랬)"          # 하지마, 하지 말라고  (말하지마·'하지 말고'는 아님)
    r"|그만\s*(?:해|하|좀|둬|두)|그만\s*[!.~]*\s*$"
    r"|지워|지우라|삭제\s*해|내려\s*(?:줘|달|주)|올리지\s*마|찍지\s*마|보내지\s*마|퍼뜨리지\s*마|캡처\s*하지\s*마"
    r"|왜\s*(?:계속\s*|자꾸\s*|맨날\s*)?나만|왜\s*(?:계속\s*|자꾸\s*)?나한테|나한테\s*왜|내가\s*(?:뭘|왜)|내가\s*뭐\s*(?:했|잘못)"
    r"|왜\s*그래|왜\s*그러"
    r"|싫다고|하기\s*싫|기분\s*나[빠쁘]|속상|상처|억울|창피|무서|괴롭"
    r"|ㅠ|ㅜ|흑흑|제발|선생님|쌤한테|신고|미안|잘못했|죄송")
# 남의 일을 말리는 말 (주변인의 방어). 1인칭 표현이 같이 있으면 본인의 항의로 본다.
_MEDIATE = re.compile(
    r"싸우지\s*마|그만\s*싸워|싸움|진정|너무\s*심|심했|심하잖|심한\s*거|너무하|얘들아|애들아|니네|너네|너희"
    r"|걔한테|쟤한테|[가-힣]{2,4}(?:이|)한테\s*(?:왜|그러지|그만|뭐라)")
_FIRST_PERSON = re.compile(r"(?<![가-힣])(?:나만|나한테|나를|나도|내가|내\s|나\s|날\s|저한테)")
_DISMISS = re.compile(
    r"장난인데|장난이잖|장난\s*(?:인|이)\s*거|장난도\s*못|농담인데|웃자고"
    r"|왜\s*화\s*[내냄났남]|화났어\s*\?|화났냐|삐[졌짐쳤지]|예민|오바|진지충|진지\s*빨"
    r"|뭘\s*그런\s*걸|그걸\s*가지고|별것도\s*아닌|찡찡|징징")
_AGREE = re.compile(r"ㅇㅈ|인정|팩트|ㄹㅇ|레알|맞아|맞네|맞는\s*말|그니까|그러니까|내\s*말이|동의|ㄱㅇㄷ|개웃|웃기|웃겨")


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


def prepare(items: list[dict], pseudo: bool = True) -> list[dict]:
    """성격 표시 + 저항 가드 + (선택) 무마 발화·이미지를 공격으로 표시. 원본은 건드리지 않는다."""
    out = []
    for it in items:
        d = dict(it)
        d["st"] = stance(d.get("text"))
        cb = float(d.get("cb") or 0.0)
        if ENABLE_RESIST_GUARD and d["st"] in ("protest", "defend") and cb >= TOX_THRESHOLD:
            d["cb_raw"], d["cb"], d["note"] = cb, min(cb, RESIST_CAP), "resistance_guard"
        out.append(d)
    if not (pseudo and ENABLE_PSEUDO):
        return out
    n = len(out)
    for i, d in enumerate(out):
        if float(d.get("cb") or 0.0) >= TOX_THRESHOLD:
            continue
        who = d["speaker"]
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
    피해자 후보마다 세 신호를 합산해 한 명을 고른다 (기록 전체 기준).
      explicit : 공격 메시지가 답장(reply_to)으로 가리킨 메시지의 발신자      × 6
      mention  : 공격 메시지에 이름(display_name/aliases)이 나온 횟수        × 3
      reply    : 공격 바로 뒤(3메시지 안)에 반응한 공격 수                    × 2
                 '저항' 반응은 × 3, 맞장구·웃음은 × −2 (가해자 편으로 봄)
    이름이 나왔다고 무조건 피해자가 아니다 ("우웅아 쟤 봐 ㅋㅋ 역겨워"는 같은 편을 부른 것).
    그래서 반응 패턴과 합산하고, 가장 강한 근거를 victim_reason으로 돌려준다.
    """
    aggressors, aggr = _aggressors(items)
    if not aggressors:
        return None
    aset = set(aggressors)
    explicit, mention, reply, weak, ally = Counter(), Counter(), {}, {}, {}
    items = [it if "st" in it else {**it, "st": stance(it.get("text"))} for it in items]
    for i, it in enumerate(items):
        if (it.get("cb") or 0) < TOX_THRESHOLD:
            continue
        rt = it.get("reply_to")
        if rt and rt in meta_by_mid:
            tgt = meta_by_mid[rt].get("speaker")
            if tgt and tgt not in aset:
                explicit[tgt] += 1
        text = it.get("text") or ""
        for code, pat in roster.items():
            if code not in aset and pat is not None and pat.search(text):
                mention[code] += 1
        if it["speaker"] in aset:
            for j in range(i + 1, min(len(items), i + 1 + REPEAT_REPLY_SPAN)):
                s = items[j]["speaker"]
                if s in aset:
                    continue
                st = items[j]["st"]
                if st == "protest":
                    reply.setdefault(s, set()).add(i)
                elif st in ("agree", "dismiss") or is_playful(items[j].get("text")):
                    ally.setdefault(s, set()).add(i)         # 공격에 맞장구 = 가해자 편
                elif st == "defend":
                    continue                                 # 말리는 말 = 주변인의 방어. 피해자 근거로 세지 않음
                else:
                    weak.setdefault(s, set()).add(i)
    nprot = Counter({k: len(v) for k, v in reply.items()})
    nweak = Counter({k: len(v - reply.get(k, set())) for k, v in weak.items()})
    nally = Counter({k: len(v - reply.get(k, set()) - weak.get(k, set())) for k, v in ally.items()})
    # 반응 수 = 저항 + 그 밖의 반응 − 맞장구. 0 이하면 반응만으로는 피해자 후보가 아니다 (이름·답장 지목은 유효)
    nrep = Counter({c: nprot[c] + nweak[c] - nally[c] for c in set(nprot) | set(nweak)})
    nrep = Counter({c: n for c, n in nrep.items() if n > 0})
    cands = set(explicit) | set(mention) | set(nrep)
    if not cands:
        return None
    score = {c: W_EXPLICIT_T * explicit[c] + W_MENTION_T * mention[c]
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
    # 근거가 강한가: 답장·이름으로 지목됐거나, 그 아이가 직접 2번 이상 항의했다
    out["victim_support"] = "strong" if reason in STRONG_REASONS or nprot[victim] >= 2 else "weak"
    return out


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

    # 기존 판정에도 저항 가드는 적용한다 (항의가 공격으로 세어져 방향이 뒤집히지 않게)
    guarded = prepare(window, pseudo=False)
    base = _orig_evaluate_window(guarded, module_b_window) if module_b_window is not None \
        else _orig_evaluate_window(guarded)
    hist = HISTORY.merged(room_id, window, commit) if room_id is not None else window
    if base["is_bullying"]:
        return {**base, "target_source": "window", "attack_mids": _attack_mids(guarded, base["attr"].aggressors),
                "victim_support": "strong" if base["attr"].victim_reason in STRONG_REASONS else "weak"}

    hist = prepare(hist)
    meta_by_mid = {it["mid"]: it for it in hist if it.get("mid")}
    r = resolve_target(hist, roster, meta_by_mid)
    if r and r["is_bullying"]:
        return {**r, "target_source": "room_history" if len(hist) > len(window) else "window",
                "attack_mids": _attack_mids(hist, r["attr"].aggressors)}
    detail = [f"{r['attr'].victim_reason}:{r['drop_reason']}"] if r else []
    return {**base, "target_source": "window", "drop_detail": detail}
