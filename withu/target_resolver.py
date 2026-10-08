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

v0.3.4 — 배제 탐지 1단계 (4장 표의 포함·제외 사례 기준. 로그 기반 응답 고립 분석은 아직 없음)
  C1 발화 확인: 배제 발화 규칙에 걸린 메시지를 LLM에 한 번 물어 정당한 목적(깜짝 파티, 목적이 정해진 방,
     규칙 위반에 따른 관리)이면 공격으로 세지 않는다. set_exclusion_judge()로 연결하며, LLM이 없거나 답하지
     못하면 규칙 그대로 센다. 전송 후 호출의 새 메시지에만 묻고 결과는 메시지별로 기억한다.
  C2 방 구조: 방 A의 명단에서 한두 명만 빠진 방 B가 있으면 B를 A의 '부분 방'으로 연결한다. B에서는 빠진 아이의
     이름도 찾는다 (앱이 그 아이를 B의 participants에 넣지 않아도 된다). 방이 따로 있다는 것만으로는 사건이
     아니고, 그 방에서 빠진 아이를 향한 공격·배제 발화가 있어야 한다. WITHU_ENABLE_SUBROOM=0 으로 끈다.

v0.3.5 — 앱팀 3차 보고(재현 요청 순서 JSON 9편) 반영
  (1) 2인칭 지목(direct_address): 아이들은 "야" / "니가 뭔 상관인데" / 욕설처럼 한 말을 여러 줄로 끊어 보낸다. 가해자가
      이어서 보낸 줄 묶음에 공격이 있고 2인칭(너·니·넌·니가)이 있으면, 그 묶음 바로 앞에서 말한 아이(가해자·맞장구친 아이 제외)를
      지목한 것으로 본다. 이름이 한 번도 안 나오고 피해자의 항의가 목록에 없는 말이어도 사건이 열린다 (사용성 평가 대본).
      묶음 앞에서 말한 아이가 여럿이면 항의한 아이를 먼저 본다 (맞장구쳤거나 스스로 공격한 아이는 뒤로).
      조건: 가해자의 공격 2개 이상 + 지목 묶음 안에 공격 1개 이상 + 그 묶음 뒤 10개 안에 그 아이가 항의
            + 다른 후보와 2배 이상 차이. 공격에서 이름으로 불린 아이가 따로 있으면 쓰지 않는다 (말리다 되받은 주변인일 수 있다).
      strong(= confirmed): 지목 묶음 안의 공격 2개 이상 + 그 아이의 분명한 항의 1번 이상.
  (2) 지목된 아이의 "너무한 거 아니야?"는 말리기가 아니라 본인의 항의로 센다. "왜 급발진?"은 약한 항의.
      항의가 '가해자의 말 뒤 3개 안'인지 볼 때 본인이 이어서 보낸 줄은 건너뛴다 (4줄로 나눠 항의하면 4번째 줄이 빠지던 문제).
  (3) 배제 발화가 가리킨 아이가 있어도 다른 후보를 지우지 않는다. 예전에는 배제 표현 한 번에 후보가 그 아이 하나로 줄어,
      이름으로 여러 번 지목되고 항의도 한 피해자가 밀려났다 (추수검사 1: "지민이는 끼지 마" 한 줄에 다솜 -> 지민).
  (4) "○○는 끼지 마"는 방금 끼어들어 말린 아이에게 하면 '참견하지 마'이지 배제가 아니다. 그 아이가 바로 앞 5개 안에서
      항의·말리기를 했거나 다른 아이의 공격 바로 뒤에 말했으면 배제 발화로 세지 않는다. cb_type에도 '배제'가 붙지 않는다.
      "나도 할래" 뒤의 "○○는 끼지 마", "끼지 마 우리끼리 할 거야"는 그대로 배제다.
  (5) 배제를 이어 가는 말: 이름 있는 배제 발화 뒤 8개 안에서 "방 새로 파서 정하자", "걔 오면 재미없어",
      "들키면 피곤해", "우리끼리 가자"처럼 따로 모이기·숨기기·오지 못하게 하기를 말하면 같은 아이를 향한 배제 발화로 센다.
      배제 발화를 한 아이나 그 아이에게 맞장구친("ㅇㅇ", "ㅋㅋ", "나 감") 아이가 한 말만 센다.
      욕설이 없어 모듈 A 점수가 낮은 공동 가해자(사후 2 수아, 추수 2 서연)가 '동조한 주변인'으로 나오던 문제.
  (6) 말리던 아이를 막는 말: "○○는 빠져", "○○아 그냥 놔둬"처럼 방금 끼어들어 말린 아이의 이름 + 참견 막는 표현은
      그 아이를 지목한 것으로 세지 않는다 (욕설이 섞인 "○○는 빠져 찐따"는 지목이다). 그 아이가 다른 근거(다른 공격에서의 지목·본인의 항의)로도 표적이면 지목으로 센다.
  (7) 반응만으로 정한 피해자(repeated_target·direct_address)는 마지막 말이 최근 15개 안에 있어야 한다. 대화 앞부분에서
      "뭐야", "ㅋㅋ"라고 했을 뿐인 아이가 나중에 시작된 공격의 임시 피해자로 잡히던 문제 (사용성 평가 대본의 도윤).
  (8) "그건 좀;;"은 말리기, "ㅇㅇ"는 맞장구, "그런 식으로 말하지 마"·"그렇게 말하지 마"는 분명한 항의로 본다.
      "걔한테"만으로는 말리기가 아니다 ("걔한테 들키면 피곤해").

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
# v0.3.4
ENABLE_SUBROOM         = os.environ.get("WITHU_ENABLE_SUBROOM", "1") != "0"        # 부분 방 연결 (C2)
SUBROOM_MAX_MISSING    = _env("WITHU_SUBROOM_MAX_MISSING", 2, int)                 # 부분 방에서 빠진 아이 수의 상한
SUBROOM_MIN_MEMBERS    = _env("WITHU_SUBROOM_MIN_MEMBERS", 3, int)                 # 부분 방의 최소 인원 (1:1 대화는 제외)
ENABLE_EXCLUSION_LLM   = os.environ.get("WITHU_EXCLUSION_LLM", "1") != "0"         # 배제 발화를 LLM으로 확인 (C1)
# v0.3.5
PROTESTER_MAX_PRIOR    = _env("WITHU_PROTESTER_MAX_PRIOR", 1, int)   # 항의한 아이 보호: 그 전에 본인의 '공격'(점수 기준)이 이 수보다 적어야 함 (1 = 한 번도 없어야 함)
REPEAT_RECENCY         = _env("WITHU_REPEAT_RECENCY", 15, int)                    # 반복 표적·2인칭 지목: 그 아이의 마지막 말이 이 안에 있어야 함 (0 = 끔)
ENABLE_ADDRESS         = os.environ.get("WITHU_ENABLE_ADDRESS", "1") != "0"        # 2인칭 지목
W_ADDRESS              = _env("WITHU_ADDRESS_WEIGHT", 3.0)                         # 지목 묶음 1개의 점수 (이름 지목과 같음)
ADDRESS_LOOKBACK       = _env("WITHU_ADDRESS_LOOKBACK", 6, int)                    # 묶음 앞 몇 메시지까지 상대를 찾나
ADDRESS_REPLY_SPAN     = _env("WITHU_ADDRESS_REPLY_SPAN", 10, int)                 # 지목 묶음 뒤 몇 메시지 안의 항의를 그 묶음에 대한 것으로 보나
ADDRESS_MIN_ATTACKS    = _env("WITHU_ADDRESS_MIN_ATTACKS", 1, int)                 # 열림: 지목 묶음 안의 공격 수 (+ 가해자의 공격 2개 이상, 그 아이의 항의 1번)
ADDRESS_STRONG_ATTACKS = _env("WITHU_ADDRESS_STRONG_ATTACKS", 2, int)              # strong: 지목 묶음 안의 공격 수 (+ 그 아이의 분명한 항의 1번)
EXCL_FOLLOW_SPAN       = _env("WITHU_EXCL_FOLLOW_SPAN", 8, int)                    # 배제 발화 뒤 몇 메시지까지 이어 가는 말로 보나
BUTT_OUT_SPAN          = _env("WITHU_BUTT_OUT_SPAN", 5, int)                       # "끼지 마": 그 아이가 이 안에서 말했으면 참견 막기
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
_PARTICLE = (r"(?:이?(?:한테|에게|랑|하고|보고|의|가|는|은|을|를|도|만|야|아|님|씨|쌤)(?:는|도|만)?|이)?"
             )   # v0.3.4: 겹친 조사도 허용 (도현이한테는, 하늘이만, 민준한테도)


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
    """방별 명단. v0.3.4: 다른 방의 명단에서 한두 명만 빠진 방은 '부분 방'으로 연결해, 빠진 아이의 이름도 찾는다."""

    def __init__(self):
        self._lock = threading.Lock()
        self._rooms: dict[str, dict[str, "re.Pattern"]] = {}
        self._parent: dict[str, Optional[str]] = {}          # 부분 방 -> 원래 방 (연결을 다시 계산할 때 비운다)

    def update(self, room_id, participants) -> None:
        table = {}
        for p in participants:
            code = _get(p, "participant_code")
            if not code:
                continue
            table[code] = name_pattern(name_tokens(_get(p, "display_name") or "", _get(p, "aliases") or []))
        with self._lock:
            if set(self._rooms.get(room_id, {})) != set(table):
                self._parent.clear()                         # 구성원이 바뀌면 연결을 다시 계산한다
            self._rooms[room_id] = table

    def _find_parent(self, room_id) -> Optional[str]:
        """이 방의 명단을 모두 포함하고 한두 명만 더 있는 방. 여럿이면 빠진 아이가 가장 적은 방."""
        if room_id in self._parent:
            return self._parent[room_id]
        mine = set(self._rooms.get(room_id, {}))
        best, best_missing = None, None
        if ENABLE_SUBROOM and len(mine) >= SUBROOM_MIN_MEMBERS:
            for other, table in self._rooms.items():
                missing = len(set(table) - mine)
                if other != room_id and mine < set(table) and missing <= SUBROOM_MAX_MISSING \
                        and (best_missing is None or missing < best_missing):
                    best, best_missing = other, missing
        self._parent[room_id] = best
        return best

    def absent(self, room_id) -> dict:
        """이 방이 부분 방이면: 원래 방에는 있고 이 방에는 없는 아이들 {code: 이름 패턴}. 아니면 {}."""
        with self._lock:
            parent = self._find_parent(room_id)
            if parent is None:
                return {}
            mine = self._rooms.get(room_id, {})
            return {c: pat for c, pat in self._rooms[parent].items() if c not in mine}

    def parent(self, room_id) -> Optional[str]:
        with self._lock:
            return self._find_parent(room_id)

    def members(self, room_id) -> set:
        with self._lock:
            return set(self._rooms.get(room_id, {}))

    def get(self, room_id) -> dict[str, "re.Pattern"]:
        """이름을 찾을 대상: 이 방의 명단 + (부분 방이면) 빠진 아이들."""
        with self._lock:
            table = dict(self._rooms.get(room_id, {}))
        table.update(self.absent(room_id))
        return table

    def clear(self):
        with self._lock:
            self._rooms.clear(); self._parent.clear()


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

    def tail(self, room_id, n: int) -> list[dict]:
        """방 기록의 마지막 n개 (읽기만)."""
        with self._lock:
            return list(self._rooms.get(room_id, ()))[-n:]

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
    # v0.3.5: "그런 식으로 말하지 마", "그렇게 말하지 마" (그냥 '말하지 마'는 가해자도 쓰므로 넣지 않는다)
    r"|(?:그런\s*식으로|그딴\s*식으로|이런\s*식으로|그렇게|함부로)\s*(?:말|얘기)\s*하지\s*(?:마|말라|말아|말랬)"
    r"|(?:나한테|나만|내가)[^.?!\n]{0,8}(?:너무하|너무\s*한\s*[거것]|너무\s*심|심하잖|심한\s*거)"      # "나한테 너무한 거 아니야?"
    r"|(?:하나도\s*)?안\s*(?:귀여|귀엽|웃[기겨])|웃기지\s*않|귀엽지\s*않|안\s*웃긴"
    r"|싫어(?![하해])|싫거든|싫단\s*말|싫음|싫다고|하기\s*싫"
    r"|왜\s*(?:계속\s*|자꾸\s*|맨날\s*)?나만|왜\s*(?:계속\s*|자꾸\s*)?나한테|나한테\s*왜|내가\s*(?:뭘|왜)|내가\s*뭐\s*(?:했|잘못)")
# 약한 신호: 속상함·사과·호소. 가해자 쪽도 흔히 쓰는 말이라 항의로는 세되 '분명한 항의'로는 보지 않는다
_PROTEST_SOFT = re.compile(
    r"왜\s*그래|왜\s*그러|왜\s*(?:갑자기\s*)?급발진"          # v0.3.5: "왜 급발진?"
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
    r"싸우지\s*마|그만\s*싸워|싸움|진정|너무\s*심|심했|심하잖|심한\s*거|너무하|너무\s*한\s*[거것]|얘들아|애들아|니네|너네|너희"
    # v0.3.5: "그건 좀;;", "그건 좀 아니지" (가벼운 반대도 말리기). 뒤에 다른 말이 이어지면 아니다 ("그건 좀 이따 하자")
    r"|그건\s*좀\s*(?:[;.…~?!ㅠㅜ\s]*$|아니[지잖야]|아닌\s*[것거듯]|심하|심한|그렇[지잖])"
    r"|(?:걔|쟤|얘)한테\s*(?:왜|그러지|그만|뭐라|좀|너무)|[가-힣]{2,4}(?:이|)한테\s*(?:왜|그러지|그만|뭐라)"   # v0.3.5: '걔한테'만으로는 말리기가 아니다 ("걔한테 들키면 피곤해")
    # v0.3.3: 남의 일로 말하는 표현 (3인칭·당위·청유)
    r"|본인(?:이|은|도|한테)|(?:걔|쟤|얘)(?:가|는|도)\s*싫|싫어하잖|싫다잖|싫대|싫다는데|싫다고\s*하잖|싫다\s*하잖"
    r"|그만해야|하지\s*말아야|지워야|지워\s*줘라|사과해|사과\s*하[라자]|그러면\s*안\s*[되돼]|그러는\s*거\s*아니"
    r"|아닌\s*[것거]\s*같|그만하자|하지\s*말자|보내지\s*말자|올리지\s*말자")
_FIRST_PERSON = re.compile(r"(?<![가-힣])(?:나만|나한테|나를|나도|내가|내\s|나\s|날\s|저한테)")
_DISMISS = re.compile(
    r"장난인데|장난이잖|장난\s*(?:인|이)\s*거|장난도\s*못|농담인데|웃자고"
    r"|왜\s*화\s*[내냄났남]|화났어\s*\?|화났냐|삐[졌짐쳤지]|예민|오바|진지충|진지\s*빨"
    r"|뭘\s*그런\s*걸|그걸\s*가지고|별것도\s*아닌|찡찡|징징")
_AGREE = re.compile(r"(?<![ㄱ-ㅎ])ㅇㅇ(?![ㄱ-ㅎ])|ㅇㅈ|인정|팩트|ㄹㅇ|레알|맞아|맞네|맞는\s*말|그니까|그러니까|그러게|그치(?!만)|내\s*말이|동의|ㄱㅇㄷ|개웃|웃기|웃겨")
# v0.3.3: 그 자리에 없는/말하지 않는 아이를 남처럼 부르는 말 ("걔 또 그러네"). 1인칭이 같이 있으면 본인 이야기로 본다.
_THIRD_PERSON = re.compile(r"(?<![가-힣])(?:걔|쟤|얘|그\s*애|저\s*애)(?:는|가|도|랑|한테|를|네|\s|$)")
# v0.3.3: 배제 표현. 명단의 이름(말한 아이 본인 제외)과 같은 메시지에 있을 때만 공격으로 센다.
_EXCLUDE = re.compile(
    r"빼자|뺄까|빼\s*버리|빼야|빼고(?:\s*\S+){0,2}?\s*(?:하자|놀자|가자|만들자|만들까|만들어|파자|할래|할까|모이자|초대|우리끼리)"
    r"|(?:은|는)\s*빼고|빼고\s*[ㅋㅎ~!.\s]*$"
    r"|부르지\s*마|부르지\s*말자|초대\s*하지\s*마|초대\s*하지\s*말자|끼워\s*주지\s*마|껴\s*주지\s*마|안\s*끼워|끼지\s*마"
    r"|(?:랑|이랑|하고)\s*(?:놀지|말하지|얘기하지)\s*(?:마|말자)|말\s*걸지\s*(?:마|말자)|상대\s*하지\s*(?:마|말자)"
    r"|한테(?:는|도)?\s*(?:절대\s*|아직\s*|일단\s*)?(?:말하지|알리지|얘기하지)\s*(?:마|말자)"
    r"|없는\s*(?:방|단톡|톡방)|무시\s*하자|무시해\s*버려|투명\s*인간")
# v0.3.5: "끼지 마"는 방금 말한 아이에게 하면 '참견하지 마'다 (모임에서 빼는 말이 아님)
_BUTT_OUT = re.compile(r"끼지\s*마|끼어들지\s*마")
# v0.3.5: 말리던 아이를 막는 말 ("○○는 빠져", "○○아 그냥 놔둬"). 방금 말한 아이의 이름과 같이 나오면 그 아이는
# 표적이 아니라 말리던 주변인이다. 다만 그 아이가 다른 근거(다른 공격에서의 지목·본인의 항의)로도 표적이면 지목으로 센다.
_SILENCE = re.compile(r"빠져(?:라|[\s!.~ㅋㅎ;]|$)|빠지라|빠지든|끼지\s*마|끼어들지\s*마|놔\s*둬|냅\s*둬|내버려\s*둬|가만히\s*있어|상관\s*(?:하지\s*)?마|신경\s*꺼"
                      r"|나서지\s*마|참견\s*(?:하지\s*)?마|왜\s*(?:갑자기\s*)?(?:진지|선생님|편들)|편\s*들지\s*마")
# v0.3.5: 배제를 이어 가는 말. 이름 있는 배제 발화 뒤(EXCL_FOLLOW_SPAN 안)에 나올 때만 같은 아이를 향한 배제 발화로 센다.
_EXCL_FOLLOW = re.compile(
    r"새\s*(?:방|단톡|톡방)|방\s*(?:새로\s*|따로\s*)?(?:파[서자]|만들(?:자|까|어서|게|래))|따로\s*(?:방|얘기|정하|놀|하자|만나|가자|모이)|우리끼리"   # 따로 모이기
    r"|들키면|몰래|비밀로|말하지\s*마|알리지\s*마|알려\s*줄\s*필요\s*없|왜\s*알려\s*줘야"                                      # 숨기기
    r"|(?:걔|쟤|얘)(?:가)?\s*오면|(?:걔|쟤|얘)(?:는|랑은?)?\s*(?:빼(?:고|자|야|버려)|안\s*불러|부르지\s*(?:마|말))")              # 오지 못하게 하기
# v0.3.5: 말리기 표현 가운데 당사자도 쓰는 말 (지목된 아이가 하면 본인의 항의)
_OWN_OBJECT = re.compile(r"너무하|너무\s*한\s*[거것]|너무\s*심|심하잖|심한\s*거|심했")
# v0.3.5: 배제하자는 말에 따라가는 말 ("나 감", "나도 갈래")
_JOIN = re.compile(r"^\s*(?:나|저)\s*(?:도\s*)?(?:감|갈래|간다|갈게|갈거|할래|낄래)|^\s*(?:ㄱㄱ|콜|좋아|ㅇㅋ)")
# v0.3.5: 2인칭. '너무', '너희/너네/니네'(여럿), '아니/뭐니'(어미)는 아니다.
_SECOND = re.compile(
    r"(?<![가-힣])(?:"
    r"너(?:는|도|만|가|를|랑|이랑|하고|한테는?|한테도|보고|처럼|같은|같이|때문에?|나|야|의|부터|밖에|따위)?(?![가-힣])"   # 너, 너는, 너한테 (너무·너구리·너튜브 아님)
    r"|(?:넌|널)(?![가-힣])|니가|네가"
    r"|니(?:는|도|한테|때문에?|탓)?(?![가-힣]))")


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


# ------------------------------------------------- C1: 배제 발화 확인 (LLM) ---
_JUDGE = None                      # judge(context_turns, speaker, text) -> True(배제) | False(정당한 목적) | None(모름)
_JUDGED: dict = {}                 # (room, message key) -> True/False
_JUDGED_MAX = 20_000


def set_exclusion_judge(fn) -> None:
    """app.py가 LLM이 켜져 있을 때 연결한다. None이면 규칙만 쓴다."""
    global _JUDGE
    _JUDGE = fn


def _judge_key(room_id, it) -> tuple:
    return (room_id, it.get("mid") or (it.get("speaker"), (it.get("text") or "").strip()))


def exclusion_verdict(room_id, it, context: list, ask: bool) -> Optional[bool]:
    """규칙에 걸린 배제 발화가 정말 배제인지. 기억해 둔 답이 있으면 그것을, 없고 ask=True면 LLM에 한 번 묻는다.
    None = 모름 (LLM 없음·실패·아직 안 물음) -> 호출한 쪽은 규칙대로 센다."""
    if not (ENABLE_EXCLUSION_LLM and _JUDGE is not None):
        return None
    key = _judge_key(room_id, it)
    if key in _JUDGED:
        return _JUDGED[key]
    if not ask:
        return None
    try:
        v = _JUDGE([(o["speaker"], o.get("text") or "") for o in context], it["speaker"], it.get("text") or "")
    except Exception as e:                                   # 판정이 LLM 때문에 깨지면 안 된다
        print("[exclusion] judge error:", e)
        v = None
    if v is not None:
        if len(_JUDGED) >= _JUDGED_MAX:
            _JUDGED.clear()
        _JUDGED[key] = bool(v)
    return v


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


def _intervened(items: list, i: int, targets, span: int = None) -> bool:
    """i번째 메시지 앞(span 안)에서 targets 가운데 한 아이가 '끼어들어 말린' 것인가.
    그 아이의 마지막 말이 항의·말리기 표현이거나, 다른 아이의 공격(점수 기준·욕설) 바로 뒤(3개 안)에 한 말이면 그렇다.
    놀이에 끼워 달라는 말("나도 할래") 뒤의 "○○는 끼지 마"는 여기에 해당하지 않는다 (그건 배제다)."""
    span = BUTT_OUT_SPAN if span is None else span
    for j in range(i - 1, max(-1, i - 1 - span), -1):
        o = items[j]
        who = o.get("speaker")
        if who not in targets:
            continue
        st = o.get("st") or stance(o.get("text"))
        if st in ("protest", "defend"):
            return True
        return any(p.get("speaker") != who and (float(p.get("cb") or 0.0) >= TOX_THRESHOLD
                                                or (p.get("st") or stance(p.get("text"))) == "hostile")
                   for p in items[max(0, j - REPEAT_REPLY_SPAN):j])
    return False


def _butt_out(text: str, targets, items: list, i: int) -> bool:
    """"○○는 끼지 마"가 가리킨 아이가 바로 앞에서 끼어들어 말리고 있었으면 '참견하지 마'다 (배제 아님)."""
    text = text or ""
    if not _BUTT_OUT.search(text) or _EXCL_FOLLOW.search(text) or any(h in text for h in _HOSTILE):
        return False                                  # "끼지 마 우리끼리 할 거야"는 배제다
    m = _EXCLUDE.search(text)
    if m and not _BUTT_OUT.fullmatch(m.group(0).strip()):
        return False                                  # 같은 메시지에 다른 배제 표현이 먼저 있으면 배제로 본다
    return _intervened(items, i, targets)


def prepare(items: list[dict], pseudo: bool = True, roster: Optional[dict] = None, *,
            room_id=None, ask_last: bool = False) -> list[dict]:
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
    # (a)의 기준은 WITHU_PROTESTER_MAX_PRIOR로 늦출 수 있다 (2 = 점수 높은 말 한 줄까지는 봐줌).
    if ENABLE_PROTESTER_GUARD and ENABLE_RESIST_GUARD:
        hostile = {d["speaker"] for d in out if d["st"] == "hostile"}
        posted_img = {d["speaker"] for d in out if d.get("img")}
        attacked: Counter = Counter()   # 지금까지 한 공격(점수 기준) 수
        protected: set = set()
        for i, d in enumerate(out):
            who = d["speaker"]
            cb = float(d.get("cb") or 0.0)
            if d["st"] == "protest":
                if _PROTEST_HARD.search(d.get("text") or "") and attacked[who] < PROTESTER_MAX_PRIOR and who not in hostile \
                        and who not in posted_img and any(
                        o["speaker"] != who and (o.get("img") or float(o.get("cb") or 0.0) >= TOX_THRESHOLD)
                        for o in out[max(0, i - REPEAT_REPLY_SPAN):i]):
                    protected.add(who)
            elif cb >= TOX_THRESHOLD:
                if d["st"] == "neutral" and who in protected:
                    d["cb_raw"], d["cb"], d["note"] = cb, min(cb, RESIST_CAP), "protester_guard"
                    d["st"] = "protest"
                else:
                    attacked[who] += 1
    if not (pseudo and ENABLE_PSEUDO):
        return out

    n = len(out)
    last_excl = None                      # (index, [지목된 코드]) — 바로 앞의 배제 발화 (이름 없이 이어 받은 것 포함)
    last_named = None                     # (index, [지목된 코드]) — 바로 앞의 '이름 있는' 배제 발화
    # 배제 발화를 한 아이들과, 그 아이의 말 바로 뒤(3개 안)에 맞장구치거나 "나 감"이라고 한 아이들 (같은 편).
    # 방 기록 전체에서 미리 찾는다: 배제 발화보다 먼저 맞장구친 아이도 같은 편이다.
    excluders: set = set()
    sided: set = set()
    if ENABLE_EXCLUSION_RULE and roster:
        excluders = {d["speaker"] for d in out if d["st"] not in ("protest", "defend") and _EXCLUDE.search(d.get("text") or "")
                     and _excl_target(d.get("text"), roster, skip=(d["speaker"],))}
        for i, d in enumerate(out):
            if excluders and d["speaker"] not in excluders and (d["st"] == "agree" or _JOIN.search(d.get("text") or "")) \
                    and any(o["speaker"] in excluders for o in out[max(0, i - REPEAT_REPLY_SPAN):i]):
                sided.add(d["speaker"])
    for i, d in enumerate(out):
        who = d["speaker"]
        text = d.get("text") or ""
        # v0.3.3 배제 발화: 이름 + 배제 표현. 이름 없이 "걔 빼자"로 이어 받으면 같은 아이를 가리킨 것으로 본다.
        # v0.3.5 배제를 이어 가는 말("새 방 만들자", "들키면 피곤해")도 앞선 배제 발화의 아이를 가리킨 것으로 본다.
        is_excl = bool(_EXCLUDE.search(text))
        # 이어 가는 말은 이름 있는 배제 발화에서 8개 안, 배제 발화를 했거나 그 아이에게 맞장구친 아이가 한 말만 센다.
        # 말리는 아이의 "왜 우리끼리만 해"나 상관없는 아이의 "방 만들었어"를 배제로 세지 않고, 끝없이 이어지지도 않는다.
        is_follow = bool(not is_excl and last_named and i - last_named[0] <= EXCL_FOLLOW_SPAN
                         and who not in last_named[1] and (who in excluders or who in sided)
                         and _EXCL_FOLLOW.search(text) and not _named(text, roster, skip=(who,)))
        if ENABLE_EXCLUSION_RULE and roster and d["st"] not in ("protest", "defend") and (is_excl or is_follow):
            named = _excl_target(text, roster, skip=(who,)) if is_excl else []
            if named and _butt_out(text, named, out, i):
                named, d["note"] = [], "butt_out"     # 방금 말한 아이에게 "끼지 마" = 참견 막기. 배제 발화가 아니다
            elif not named and is_follow:
                named = [c for c in last_named[1] if c != who]
            elif not named and last_excl and i - last_excl[0] <= REPEAT_REPLY_SPAN:
                named = [c for c in last_excl[1] if c != who]
            # C1: 깜짝 파티 준비처럼 정당한 목적이면 공격으로 세지 않는다. 새 메시지(마지막)만 LLM에 묻는다
            if named and is_excl and exclusion_verdict(room_id, d, out[max(0, i - 6):i], ask_last and i == n - 1) is False:
                d["note"] = "exclusion_cleared"
                continue
            if named:
                d["excl"] = named
                last_excl = (i, named)
                if is_excl and _excl_target(text, roster, skip=(who,)):
                    last_named = (i, named)
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


def _after_aggressor(items, j, aset) -> bool:
    """j번째 메시지가 '가해자의 말 뒤 3개 안'인가. 본인이 이어서 보낸 줄은 건너뛰고 센다
    (항의를 4줄로 나눠 보내면 4번째 줄이 빠지던 문제, v0.3.5)."""
    who = items[j]["speaker"]
    k = j
    while k > 0 and items[k - 1]["speaker"] == who:
        k -= 1
    return any(o["speaker"] in aset for o in items[max(0, k - REPEAT_REPLY_SPAN):k])


def _is_ally_talk(o, roster, aset) -> bool:
    """가해자 편의 말(맞장구·웃음·무마)이거나 남 얘기를 하는 말 = 그 아이는 지금 공격받는 쪽이 아니다."""
    text = o.get("text") or ""
    if o["st"] in ("agree", "dismiss", "hostile") or is_playful(text):
        return True
    return bool((_THIRD_PERSON.search(text) or _named(text, roster, skip=aset | {o["speaker"]}))
                and not _FIRST_PERSON.search(text))


def is_own_objection(it, roster, aset) -> bool:
    """말리기 표현("너무한 거 아니야?", "그건 좀 심하잖아")이지만 남의 일을 말하는 것이 아닌 말.
    2인칭으로 지목된 아이가 하면 본인의 항의다. "○○한테 그러지 마", "걔가 싫다잖아"는 남을 말리는 말."""
    text = it.get("text") or ""
    if it.get("st") != "defend" or not _OWN_OBJECT.search(text):
        return False
    return not (_THIRD_PERSON.search(text) or "한테" in text or _named(text, roster, skip=aset | {it["speaker"]}))


def address_runs(items, aset, roster, pref=None) -> list:
    """2인칭 지목 (v0.3.5). 가해자가 이어서 보낸 줄 묶음에 공격이 있고 2인칭(너·니·넌·니가)이 있으면,
    그 묶음 바로 앞에서 말한 아이를 지목한 것으로 본다. [(지목된 아이, [묶음 안의 공격 위치], 묶음의 끝 위치)]
    묶음 안에서 다른 아이의 이름을 부르면 이름 지목이 맡으므로 여기서는 세지 않는다."""
    out = []
    if not ENABLE_ADDRESS:
        return out
    n, i = len(items), 0
    while i < n:
        who = items[i]["speaker"]
        j = i
        while j + 1 < n and items[j + 1]["speaker"] == who:
            j += 1
        run = items[i:j + 1]
        attacks = [i + k for k, o in enumerate(run) if (o.get("cb") or 0) >= TOX_THRESHOLD]
        if who in aset and attacks and any(_SECOND.search(o.get("text") or "") for o in run) \
                and not any(_named(o.get("text"), roster, skip=aset) or o.get("excl") for o in run):
            best = None                               # (반응 근거, -거리)
            for k in range(i - 1, max(-1, i - 1 - ADDRESS_LOOKBACK), -1):
                o = items[k]
                if o["speaker"] in aset or _is_ally_talk(o, roster, aset):
                    continue
                key = ((pref or {}).get(o["speaker"], 0), k)
                if best is None or key > best[0]:
                    best = (key, o["speaker"])
            if best is not None:
                out.append((best[1], attacks, j))
        i = j + 1
    return out


def resolve_target(items, roster, meta_by_mid) -> Optional[dict]:
    """
    피해자 후보마다 신호를 합산해 한 명을 고른다 (기록 전체 기준).
      explicit : 공격 메시지가 답장(reply_to)으로 가리킨 메시지의 발신자      × 6
      mention  : 공격 메시지에 이름(display_name/aliases)이 나온 횟수        × 3  (배제 발화가 가리킨 아이 포함)
      address  : 가해자의 공격 묶음이 2인칭으로 그 아이를 향한 횟수            × 3  (v0.3.5, address_runs)
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

    def evidence(own: dict):
        """항의·반응 근거. own = {2인칭으로 지목된 아이: [지목 묶음의 끝 위치]}.
        이 아이가 묶음 뒤(ADDRESS_REPLY_SPAN 안)에 한 "너무한 거 아니야?"는 말리기가 아니라 본인의 항의다."""
        def own_obj(it):
            return it["speaker"] in own and _near(it["_i"], own[it["speaker"]]) and is_own_objection(it, roster, aset)
        # ---- 1) 항의 메시지: 가해자의 말(공격으로 세어지지 않은 말 포함) 뒤 3개 안에서 가해자가 아닌 아이가 한 항의
        prot_msgs: dict = {}                                         # code -> [메시지 위치]
        for j in range(first_attack + 1, n):
            it = items[j]
            if it["speaker"] in aset or not (it["st"] == "protest" or own_obj(it)):
                continue
            if _after_aggressor(items, j, aset):
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
        nhard = Counter({c: sum(1 for j in v if items[j].get("note") == "protester_guard" or own_obj(items[j])
                                or _PROTEST_HARD.search(items[j].get("text") or "")) for c, v in prot_msgs.items()})

        # ---- 2) 가해자의 공격마다: 바로 뒤(3메시지 안)의 반응
        weak, ally, answered = {}, {}, {}
        for i, it in enumerate(items):
            if (it.get("cb") or 0) < TOX_THRESHOLD or it["speaker"] not in aset:
                continue
            for j in range(i + 1, min(n, i + 1 + REPEAT_REPLY_SPAN)):
                o = items[j]
                s = o["speaker"]
                if s in aset:
                    continue
                st = o["st"]
                if (st == "protest" or own_obj(o)) and s not in mediators:
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
        hard_idx = {c: [j for j in v if items[j].get("note") == "protester_guard" or own_obj(items[j])
                        or _PROTEST_HARD.search(items[j].get("text") or "")] for c, v in prot_msgs.items()}
        return nprot, nhard, nweak, nally, Counter({k: len(v) for k, v in ally.items()}), prot_msgs, hard_idx

    _near = lambda j, ends: any(e < j <= e + ADDRESS_REPLY_SPAN for e in ends)
    items = [{**it, "_i": i} for i, it in enumerate(items)]
    nprot, nhard, nweak, nally, nally_raw, prot_msgs, hard_idx = evidence({})

    # ---- 0) 2인칭 지목 (v0.3.5): 가해자의 공격 묶음이 "너/니가"로 향한 아이.
    #         묶음 앞에서 말한 아이가 여럿이면 지금까지 반응 근거가 가장 많은 아이, 같으면 가장 가까운 아이.
    address, addr_attacks, addr_ends = Counter(), Counter(), {}
    #         항의한 아이를 먼저 보고, 맞장구쳤거나 스스로 공격한 아이는 뒤로 미룬다.
    pref = Counter({c: 2 * nprot[c] + nweak[c] - 2 * nally_raw[c] - 2 * aggr.get(c, 0)
                    for c in set(nprot) | set(nweak) | set(nally_raw) | set(aggr)})
    for code, attacks, end in address_runs(items, aset, roster, pref):
        address[code] += 1
        addr_attacks[code] += len(attacks)
        addr_ends.setdefault(code, []).append(end)
    if address:
        nprot, nhard, nweak, nally, nally_raw, prot_msgs, hard_idx = evidence(addr_ends)
    # 그 묶음 바로 뒤(ADDRESS_REPLY_SPAN 안)에 한 항의만 지목의 근거로 쓴다 (방 기록의 먼 앞뒤를 잇지 않는다)
    near_prot = Counter({c: sum(1 for j in prot_msgs.get(c, []) if _near(j, addr_ends[c])) for c in address})
    near_hard = Counter({c: sum(1 for j in hard_idx.get(c, []) if _near(j, addr_ends[c])) for c in address})

    # ---- 3) 공격 메시지마다: 답장·이름 지목
    explicit, mention, soft, excl_target, silenced = Counter(), Counter(), Counter(), Counter(), Counter()
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
        hush = bool(_SILENCE.search(text)) and not excl and it["st"] != "hostile"
        for code in set(_named(text, roster, skip=aset)) | excl:
            if hush and _intervened(items, i, (code,)):
                silenced[code] += 1                   # 방금 끼어들어 말린 아이에게 "빠져", "놔둬" = 말리던 아이를 막는 말
            else:
                mention[code] += 1
        for code in excl:
            excl_target[code] += 1
    # 반응 수 = 항의 + 그 밖의 반응 − 맞장구. 0 이하면 반응만으로는 피해자 후보가 아니다 (이름·답장 지목은 유효)
    nrep = Counter({c: nprot[c] + nweak[c] - nally[c] for c in set(nprot) | set(nweak)})
    nrep = Counter({c: v for c, v in nrep.items() if v > 0})
    # 지목은 그 아이가 항의했을 때만 근거로 쓴다. 가해자와 말을 주고받은 아이가 말리던 주변인일 수도 있기 때문이다
    # ("○○한테 그러지 마"라고 한 아이에게 가해자가 "넌 저걸 믿어?"라고 하는 경우). 맞장구가 더 많은 아이도 뺀다.
    address = Counter({c: v for c, v in address.items() if near_prot[c] >= 1 and nally_raw[c] <= nprot[c] + nweak[c]})
    # 공격에서 이름으로 불린 아이가 따로 있으면, 이름 없이 2인칭으로만 지목된 아이는 말리다가 되받은 주변인일 수 있다
    # ("하늘이 진짜 냄새나" / "야 그만해" / "넌 뭔데 닥쳐"). 이때는 2인칭 지목을 근거로 쓰지 않는다.
    pointed = {c for c in set(explicit) | set(mention) if explicit[c] or mention[c]}
    address = Counter({c: v for c, v in address.items() if c in pointed or not pointed})
    addr_attacks = Counter({c: v for c, v in addr_attacks.items() if c in address})
    for c, v in silenced.items():                     # 다른 근거로도 표적인 아이에게 한 "넌 빠져"는 지목으로 센다
        if explicit[c] or mention[c] or address[c] or nprot[c]:
            mention[c] += v
    cands = set(explicit) | set(mention) | set(nrep) | set(address)
    # 답장·배제 발화로 지목된 아이가 있으면, 공격 뒤에 평범하게 말했을 뿐인 아이는 후보에서 뺀다.
    # v0.3.5: 공격에서 이름으로 불렸거나 2인칭으로 지목된 아이는 남겨 점수로 겨룬다. 예전에는 후보가 배제 표현이
    # 가리킨 아이 하나로 줄어, 이미 여러 번 지목되고 항의한 피해자가 밀려났다. 항의만 한 아이는 예전처럼 뺀다
    # (배제당하는 아이는 말이 없고, 옆에서 "그만해"라고 한 아이는 말리는 주변인이다).
    # (그냥 이름이 불린 것만으로는 다른 후보를 빼지 않는다. 같은 편을 부르는 경우가 많아서 점수로 겨룬다.)
    backed = {c for c in cands if explicit[c] or excl_target[c] or (BACKED_BY_PROTEST and nprot[c])}
    if backed and PREFER_BACKED:
        cands = {c for c in cands if c in backed or mention[c] or address[c]}
    if not cands:
        return None
    score = {c: W_EXPLICIT_T * explicit[c] + W_MENTION_T * mention[c] + W_ADDRESS * address[c] + W_SOFT_MENTION * soft[c]
                + (max(0.0, W_PROTEST_REPLY * nprot[c] + W_REPLY_T * (nweak[c] - nally[c])) if c in nrep else 0.0)
             for c in cands}
    # 점수가 같으면 더 강한 근거(답장 > 배제 발화 > 이름 > 2인칭 > 항의) 순, 그래도 같으면 코드 순 (실행마다 같게)
    victim = max(score, key=lambda c: (score[c], explicit[c], excl_target[c], mention[c], address[c], nprot[c], str(c)))
    top_attacks = max(aggr.values())
    if explicit[victim]:
        reason = "explicit_target"
    elif mention[victim]:
        reason = "name_mention"
        if top_attacks < NAME_MIN_ATTACKS and nrep[victim] == 0:
            return _fail(aggressors, victim, reason, "name_single_attack")
    else:
        second = sorted(score.values(), reverse=True)[1] if len(score) > 1 else 0.0
        clear = not second or score[victim] >= REPEAT_SEPARATION * second
        # v0.3.5: 이름·답장 없이 반응만으로 정한 피해자는 '지금' 대화에 있어야 한다. 한참 전에 몇 마디 한 아이가
        # 나중에 시작된 공격의 피해자로 잡히던 문제 (사용성 평가 대본: 앞부분에서 "뭐야", "ㅋㅋ"라고 한 도윤).
        if REPEAT_RECENCY and not any(o["speaker"] == victim for o in items[-REPEAT_RECENCY:]):
            return _fail(aggressors, victim, "repeated_target", "stale_target")
        # 2인칭 지목: 이름 지목보다 조건이 좁다. 앞에서 말한 아이를 '추정'한 것이라, 그 아이를 향한 공격이 2개 이상이고
        # 그 아이가 항의했고, 다른 후보와 2배 이상 벌어져야 한다 (여럿이 빠르게 말하는 방에서 엉뚱한 아이를 막는다).
        if address[victim] and addr_attacks[victim] >= ADDRESS_MIN_ATTACKS and top_attacks >= NAME_MIN_ATTACKS and clear:
            reason = "direct_address"
        else:                                         # 지목 조건에 못 미치면 예전처럼 반복 표적 조건으로 본다
            reason = "repeated_target"
            if not ENABLE_REPEAT:
                return None
            if top_attacks < REPEAT_MIN_ATTACKS:
                return _fail(aggressors, victim, reason, "not_repeated")
            if nrep[victim] < REPEAT_MIN_REPLIES or nprot[victim] < REPEAT_MIN_PROTEST:
                return _fail(aggressors, victim, reason, "no_victim_response")
            if not clear:
                return _fail(aggressors, victim, reason, "ambiguous_target")
    out = _judge(items, aggressors, aggr, victim, reason, score, dominance_mode="set")
    out["victim_support"] = _support(reason, victim, nhard)
    if out["victim_support"] == "weak" and addr_attacks[victim] >= ADDRESS_STRONG_ATTACKS and near_hard[victim] >= 1 \
            and all(addr_attacks[c] * 2 <= addr_attacks[victim] for c in addr_attacks if c != victim):
        out["victim_support"] = "strong"        # v0.3.5: 2인칭으로 향한 공격 2개 이상 + 본인의 분명한 항의
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
                and _after_aggressor(items, j, aset):
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
    hist = prepare(hist_raw, roster=roster, room_id=room_id, ask_last=bool(commit))
    absent = set(ROSTERS.absent(room_id)) if room_id is not None else set()
    if base["is_bullying"]:
        aggr = base["attr"].aggressors
        nprot = protest_counts(hist, aggr)
        return {**base, "target_source": "window", "attack_mids": _attack_mids(guarded, aggr),
                "victim_support": _support(base["attr"].victim_reason, base["attr"].victim, nprot),
                "victim_protests": nprot[base["attr"].victim]}

    meta_by_mid = {it["mid"]: it for it in hist if it.get("mid")}
    r = resolve_target(hist, roster, meta_by_mid)
    if r and r["is_bullying"]:
        notes = {it["note"] for it in hist if it.get("note") in
                 ("exclusion_talk", "image_then_protest", "dismissal_after_protest")
                 and it["speaker"] in set(r["attr"].aggressors)}
        victim = r["attr"].victim
        if victim in absent:
            notes.add("subroom")                      # 피해자가 이 방에는 없고 원래 방에만 있다 (C2)
        return {**r, "target_source": "room_history" if len(hist) > len(window) else "window",
                "attack_mids": _attack_mids(hist, r["attr"].aggressors),
                "attack_notes": sorted(notes),
                "victim_in_room": victim in ROSTERS.members(room_id) if room_id is not None else True,
                "parent_room_id": ROSTERS.parent(room_id) if victim in absent else None}
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


def message_flags(text: str, speaker: Optional[str] = None, room_id=None, mid=None) -> dict:
    """전송 전 경고(cb_score)용: 이 메시지 하나의 성격과 배제 발화 여부. 방 기록은 바꾸지 않는다."""
    ctx = _CTX.get()
    room_id = room_id if room_id is not None else ctx.get("room_id")
    roster = ROSTERS.get(room_id) if room_id is not None else {}
    st = stance(text)
    excl = []
    if ENABLE_EXCLUSION_RULE and st not in ("protest", "defend") and _EXCLUDE.search(text or ""):
        excl = _excl_target(text, roster, skip=(speaker,))
        if excl:
            # v0.3.5: 방금 끼어들어 말린 아이에게 한 "끼지 마" = 참견 막기. prepare()와 같은 범위를 본다:
            # 방 기록의 끝(이 메시지가 이미 들어가 있으면 그 앞까지), 기록이 없으면 요청의 context.
            before = HISTORY.tail(room_id, BUTT_OUT_SPAN + REPEAT_REPLY_SPAN + 1) if room_id is not None else []
            if before and ((mid and before[-1].get("mid") == mid) or
                           (not mid and before[-1].get("speaker") == speaker and (before[-1].get("text") or "") == (text or ""))):
                before = before[:-1]
            if not before:
                before = [{"speaker": m.get("speaker"), "text": m.get("text")} for m in (ctx.get("messages") or [])[:-1]]
            if _butt_out(text, excl, before, len(before)):
                excl = []
        if excl and exclusion_verdict(room_id, {"mid": mid, "speaker": speaker, "text": text}, [], False) is False:
            excl = []                                  # LLM이 정당한 목적으로 본 메시지
    return {"stance": st, "exclusion_targets": excl}
