# -*- coding: utf-8 -*-
"""
WithU Talk — 방관행동 판정부 (Module 392).

What it does
------------
After /analyze confirms a cyberbullying incident (attribution.is_bullying == True), this
module follows every *bystander* (room member who is neither 가해자 nor 피해자) and decides,
over time, whether they 방어 / 동조 / 방관. 방관 cannot be seen in text, so it is decided from
events + time, always measured from the moment the child actually SAW the incident:

    S0 unseen ──read──▶ S1 observing ──T1(30s)──▶ S2 candidate ──T2(60s)──▶ S3 confirmed(침묵)
                           │  (1차 알림)                │ (2차 알림 + 선택지)
                           ├─ 방어 반응/선택 ─────────────┴──────────────▶ defended  (타이머 취소)
                           ├─ 동조 반응 ──────────────────────────────────▶ joined    (10초 내 취소 시 복귀)
                           ├─ 무관한 대화 ──▶ S2 즉시 (1차 알림)
                           └─ 정상 퇴장 ────▶ left(방관: 채팅방 나가기, 목록 배지) ──재입장──▶ 선택지 제공

Rules (from the 4장 labeling table + 1.5 spec):
  * 침묵            : no 방어/동조 within T2 (60 s) of exposure          -> 방관(침묵)
  * 채팅방 나가기    : normal leave after exposure, no 방어/동조 before it  -> 방관(채팅방 나가기)
                      (crash / network drop / kicked  -> NOT 방관)
  * 무관한 대화      : bystander's message classified as unrelated        -> 방관(무관 대화)
  * never exposed (did not read)                                           -> not judged
  * exposed long after the incident (or many unread)                       -> summary first

Design notes
------------
* Stdlib only. Thread-safe (one RLock). A daemon thread calls tick() every second so the
  30 s / 60 s nudges fire on time; the app/messenger server picks them up by polling
  GET /bystander/actions (or via an optional webhook).
* State is in memory -> run uvicorn with ONE worker; a restart forgets open incidents.
* Every public method takes an optional `now` so the whole thing is testable with a fake clock.

v0.3.2 — 피해자 갱신
------------------
사건이 열린 뒤에도 /analyze 판정을 따라 피해자를 고친다 (예전에는 처음 잡힌 피해자가 끝까지 남았다).
  * 지금 피해자가 가해자로 판정되면                      -> 바로 교체
  * 더 강한 근거(답장 > 이름 > 반응)로 다른 아이가 나오면  -> 바로 교체
  * 같은 세기의 근거면 2번 연속, 더 약한 근거면 3번 연속   -> 교체
교체되면 `incident_update` 알림이 나가고, 한 아이가 가해자이면서 피해자인 상태는 생기지 않는다.
피해자가 이름·답장으로 지목됐거나 본인이 2번 이상 항의했으면(attribution.victim_support=strong)
victim_status가 confirmed가 된다. 그 전까지는 provisional이다.

v0.3.3
------
  * 주변인 발화 판정(LLM)은 잠금 밖에서 한다. 예전에는 LLM을 기다리는 동안 모든 방의 요청과 타이머가 멈췄다.
  * LLM이 답하지 못하면(키 없음·시간 초과 등) 키워드 규칙으로 대신 판정하고, 어느 쪽으로 판정했는지 history에 남긴다.
  * 본인의 항의로 confirmed가 된 피해자는 이름으로 지목된 피해자와 같은 세기로 본다. 약한 근거 한 번으로는 바뀌지 않는다.

v0.3.5
------
  * victim_reason에 direct_address(2인칭 지목)가 더해졌다. 세기는 repeated_target과 같고, 본인의 분명한 항의가 더해지면
    (attribution.victim_support=strong) confirmed가 된다.

v0.3.7 — 전송 전 동조 미리 판정
------------------------------
  * preview(): 전송 전 호출(track_bystander=false)에서 "이 메시지를 보내면 방어·동조·방관 중 무엇으로 판정될지"를
    미리 돌려준다. 상태는 하나도 바꾸지 않는다 (노출·판정·알림·기록 없음).
  * 시간 예산(BYSTANDER_PREVIEW_TIMEOUT_SEC, 기본 1.5초) 안에 LLM이 답하지 못하면 키워드 규칙으로 답하고,
    LLM은 뒤에서 마저 돈다.
  * 같은 사건·같은 맥락·같은 본문의 판정은 잠시(BYSTANDER_PREVIEW_CACHE_SEC, 기본 120초) 기억했다가 전송 후 호출이
    그대로 쓴다. 경고와 기록이 같은 판정을 따르고, LLM도 메시지당 한 번만 부른다.

v0.3.8 — 누구를 향한 말인지 알려 준다 (2026-10-28 사후검사 보고)
--------------------------------------------------------------
  * 답장이면 답장 대상 메시지와 그 화자의 역할을 LLM에 같이 보낸다. 예전에는 reply_to_message_id를 쓰지 않아,
    가해자에게 단 "니가 잘못한거잖아"가 피해자 탓(4장 표3의 방어 제외 사례)으로 읽혀 동조가 되었다.
  * 맥락·답장·대상 발화 속 아이 이름을 "코드(역할)"로 바꿔 보낸다. 예전에는 맥락에 코드만 있고 본문에는 이름이 있어
    "유진이 이상함"의 유진이 가해자인지 LLM이 알 수 없었다. 아이 이름이 LLM으로 나가지 않는 효과도 있다.
  * LLM이 준 근거(reason)를 버리지 않는다: history("판정 근거: …"), 서버 로그, preview 응답(reason)에 남긴다.

v0.3.9 — 전송 전 판정을 빨리 (2026-10-30)
---------------------------------------
  * preview_begin()/preview_end(): app이 모델 추론 전에 LLM 판정을 출발시키고, 추론이 끝난 뒤 시간 예산만큼 기다린다.
    아이가 기다리는 시간의 상한은 그대로이고, LLM은 모델 추론 시간만큼 먼저 출발한다. preview()는 둘을 이어 부른다.
  * 답장 속 2인칭 비판은 답장 대상을 향한 것으로 고친다 (phase4_bystander.reply_target).
"""
from __future__ import annotations

import json
import os
import re
import hashlib
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

from .target_resolver import stance as _stance, ROSTERS as _ROSTERS, name_pattern as _name_pattern
from .target_resolver import _tokens_of

# ============================================================================
# CONFIG (override with env vars on the server)
# ============================================================================
T1_SEC                  = float(os.environ.get("BYSTANDER_T1_SEC", 30))    # observing -> candidate (1차 알림)
T2_SEC                  = float(os.environ.get("BYSTANDER_T2_SEC", 60))    # candidate -> confirmed (2차 알림 + 선택지)
MAX_NUDGES              = int(os.environ.get("BYSTANDER_MAX_NUDGES", 2))   # per incident per child
LATE_WITNESS_SEC        = float(os.environ.get("BYSTANDER_LATE_SEC", 600)) # first seen this long after -> summary first
SUMMARY_UNREAD_MIN      = int(os.environ.get("BYSTANDER_SUMMARY_UNREAD", 30))
REACTION_CANCEL_SEC     = float(os.environ.get("BYSTANDER_CANCEL_SEC", 10))
INCIDENT_IDLE_CLOSE_SEC = float(os.environ.get("BYSTANDER_IDLE_CLOSE_SEC", 1800))  # no new attack -> close
TOX_THRESHOLD           = 0.50   # same as check_chat_excel.TOX_THRESHOLD
UNRELATED_LABELS        = {"방관"}  # Module D labels treated as '무관 대화' (add "비해당" to be stricter)
CONTEXT_TURNS           = 6       # turns passed to the Module D classifier
# 피해자 근거의 세기 (클수록 강함)
VICTIM_RANK = {"explicit_target": 3, "name_mention": 2, "distress_signal": 1, "repeated_target": 1,
               "direct_address": 1,          # v0.3.5: 2인칭 지목 (이름은 안 나옴). 본인의 항의가 더해지면 confirmed
               "turn_adjacency": 0}
VICTIM_CONFIRM_RANK     = 2       # 이 세기 이상이면 confirmed (또는 attribution.victim_support == "strong")
VICTIM_SWITCH_SAME      = int(os.environ.get("BYSTANDER_VICTIM_SWITCH_SAME", 2))       # 같은 세기: 연속 판정 수
VICTIM_SWITCH_WEAKER    = int(os.environ.get("BYSTANDER_VICTIM_SWITCH_WEAKER", 3))     # 더 약한 세기: 연속 판정 수
PREVIEW_TIMEOUT_SEC     = float(os.environ.get("BYSTANDER_PREVIEW_TIMEOUT_SEC", 1.5))  # v0.3.7: 전송 전 판정 시간 예산
PREVIEW_CACHE_SEC       = float(os.environ.get("BYSTANDER_PREVIEW_CACHE_SEC", 120))    # v0.3.7: 판정 재사용 시간
JUDGE_LOG               = os.environ.get("BYSTANDER_JUDGE_LOG", "1") == "1"           # v0.3.8: 판정마다 서버 로그 한 줄

NUDGE_TEXT = {  # suggested copy; the app owns final wording
    "nudge_1": "가만히 있는다면 공격받는 친구가 힘들어 할거야.",
    "nudge_2": "다른 친구들은 이럴 때 나를 눌러보는 편이야.",
    "choices": "친구를 도와줄 방법을 골라볼까?",
    "positive_feedback": "친구를 도와줘서 고마워!",
    "join_feedback": "이 반응이 친구에게 상처가 될 수 있어. 취소할 수 있어.",
}

# reaction-button vocabulary -> polarity
_EMPATHY  = {"empathy", "공감", "sad", "슬퍼요", "hug", "안아줘요", "heart", "하트", "love"}
_POSITIVE = {"like", "좋아요", "thumbs_up", "check", "최고", "good", "ok"}
_LAUGH    = {"laugh", "웃겨요", "ㅋㅋ", "funny", "haha"}
_NEGATIVE = {"dislike", "싫어요", "thumbs_down", "angry", "화나요", "no"}

# heuristic fallback when no LLM classifier is configured (conservative on purpose)
_DEFEND_RE = re.compile(r"그만|하지\s*마|하지마|너무\s*하|심하|선생님|신고|괜찮아|힘내|네\s*편|잘못\s*이?\s*아니|탓\s*이?\s*아니")
_AGREE_RE  = re.compile(r"ㅋㅋ|ㅎㅎ|ㅇㅈ|인정|맞아|ㄹㅇ|레알|ㅇㅇ|웃기")


# ============================================================================
# helpers
# ============================================================================
def _ts(v, default: Optional[float] = None) -> float:
    """Accept epoch seconds, ISO-8601 string (Z ok) or None."""
    if v is None or v == "":
        return default if default is not None else time.time()
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s).timestamp()
    except ValueError:
        return default if default is not None else time.time()


def _iso(t: Optional[float]) -> Optional[str]:
    return None if t is None else datetime.fromtimestamp(t).isoformat(timespec="seconds")


def _polarity(reaction: str) -> str:
    r = (reaction or "").strip().lower()
    if r in _EMPATHY:  return "empathy"
    if r in _POSITIVE: return "positive"
    if r in _LAUGH:    return "laugh"
    if r in _NEGATIVE: return "negative"
    return "unknown"


def reaction_to_behavior(target_role: Optional[str], reaction: str) -> Optional[str]:
    """표3: 반응 대상 메시지 발신자의 역할 × 반응 극성 -> 방어 / 동조 / None."""
    p = _polarity(reaction)
    if target_role == "피해자":
        if p in ("empathy", "positive"): return "방어"
        if p in ("laugh", "negative"):   return "동조"
    elif target_role == "가해자":
        if p == "negative":               return "방어"
        if p in ("positive", "laugh"):    return "동조"
    return None


# ============================================================================
# state
# ============================================================================
@dataclass
class Bystander:
    code: str
    stage: str = "unseen"            # unseen|observing|candidate|confirmed|left|defended|joined|closed
    behavior: Optional[str] = None   # 방어|동조|방관
    subtype: Optional[str] = None    # 침묵|채팅방 나가기|무관 대화 (방관 only)
    exposed_at: Optional[float] = None
    decided_at: Optional[float] = None
    nudges: int = 0
    badge: bool = False              # left while 방관 -> show incident badge; choices on re-entry
    declined: bool = False           # pressed 거절 / "괴롭힘 아닌 것 같아" -> stop nudging
    was_bystanding: bool = False     # ever reached 방관 (for 방관→방어 transition)
    _undo: Optional[tuple] = None    # state before a cancellable 동조 reaction
    _undo_until: Optional[float] = None
    history: list = field(default_factory=list)

    def log(self, now: float, what: str):
        self.history.append({"t": _iso(now), "event": what})

    def to_dict(self) -> dict:
        return {"participant_code": self.code, "stage": self.stage, "behavior": self.behavior,
                "subtype": self.subtype, "exposed_at": _iso(self.exposed_at),
                "decided_at": _iso(self.decided_at), "nudges": self.nudges,
                "badge": self.badge, "declined": self.declined, "history": self.history[-10:]}


@dataclass
class Incident:
    incident_id: str
    room_id: str
    aggressors: set
    victim: Optional[str]
    first_anchor_ts: float
    last_anchor_ts: float
    anchor_ids: set = field(default_factory=set)
    n_anchor: int = 0
    closed: bool = False
    bystanders: dict = field(default_factory=dict)   # code -> Bystander
    victim_reason: Optional[str] = None      # 지금 피해자를 뒷받침한 가장 강한 근거
    victim_rank: int = 0
    victim_verdicts: int = 0                 # 지금 피해자를 가리킨 판정 수
    victim_confirmed: bool = False
    previous_victims: list = field(default_factory=list)
    _cand: Optional[str] = None              # 교체 후보
    _cand_streak: int = 0
    _cand_rank: int = 0
    _cand_reason: Optional[str] = None

    def role_of(self, code: Optional[str]) -> Optional[str]:
        if code is None: return None
        if code in self.aggressors: return "가해자"
        if code == self.victim:     return "피해자"
        return "주변인"

    def to_dict(self) -> dict:
        return {"incident_id": self.incident_id, "room_id": self.room_id, "active": not self.closed,
                "aggressors": sorted(self.aggressors), "victim": self.victim,
                "victim_reason": self.victim_reason,
                "victim_status": "confirmed" if self.victim_confirmed else "provisional",
                "previous_victims": list(self.previous_victims),
                "first_attack_at": _iso(self.first_anchor_ts), "last_attack_at": _iso(self.last_anchor_ts),
                "n_attack_messages": self.n_anchor,
                "bystanders": [b.to_dict() for b in self.bystanders.values()]}


# ============================================================================
# tracker
# ============================================================================
class BystanderTracker:
    def __init__(self, classify: Optional[Callable] = None, webhook: Optional[str] = None):
        """classify(context_turns, speaker, text) -> label ('방어'|'동조'|'방관'|'비해당')."""
        self.classify = classify
        self.webhook = webhook or os.environ.get("WITHU_ACTION_WEBHOOK") or None
        self._lock = threading.RLock()
        self.incidents: dict[str, Incident] = {}
        self.active_by_room: dict[str, str] = {}
        self.last_seen: dict[tuple, float] = {}          # (room, code) -> last read / open time
        self.msg_speaker: dict[tuple, str] = {}          # (room, message_id) -> speaker
        self._actions: dict[str, list] = {}              # room -> queued actions
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # v0.3.7: 발화 판정 공유 (전송 전 미리 판정 -> 전송 후 기록)
        self._pool = ThreadPoolExecutor(max_workers=int(os.environ.get("BYSTANDER_LLM_WORKERS", 8)),
                                        thread_name_prefix="bystander-llm")
        self._judged: dict = {}          # key -> (label, src, expires_at)
        self._inflight: dict = {}        # key -> Future
        self.last_preview_wait_ms: Optional[int] = None   # v0.3.9: 전송 전 호출이 LLM을 기다린 시간 (/health)

    def set_classifier(self, fn: Optional[Callable]):
        self.classify = fn

    # ------------------------------------------------------------------ public: /analyze hook
    def on_analyze(self, req: dict, result: dict, window: list, now: Optional[float] = None) -> Optional[dict]:
        """Call once per analysed message (async path).
        window: [{message_id, speaker, ts, cb}] for context + new message (cb after prosocial guard).
        Returns the room's incident snapshot (or None if no incident)."""
        room = req["room_id"]
        new = req["new_message"]
        speaker = new["participant_code"]
        t_msg = _ts(new.get("timestamp"), now)
        fixed_now = now is not None                    # 테스트용 가짜 시계
        now = now if now is not None else time.time()
        with self._lock:
            for w in window:
                if w.get("message_id"):
                    self.msg_speaker[(room, w["message_id"])] = w["speaker"]
            self._tick_locked(now)
            inc = self._active(room)
            attr = result.get("attribution") or {}

            # 1) create / extend the incident when the event gate says bullying
            if attr.get("is_bullying"):
                aggr = set(attr.get("aggressors") or [])
                if inc is not None:                 # v0.3.2: 피해자는 열린 뒤에도 판정을 따라 고친다
                    self._update_victim(room, inc, attr, aggr, now)
                    inc.aggressors |= (aggr - {inc.victim})      # 한 아이가 가해자이면서 피해자일 수 없다
                    for c in list(inc.bystanders):
                        if c in inc.aggressors or c == inc.victim:
                            inc.bystanders.pop(c)
                # 공격 메시지: 점수 기준 + 서버가 공격으로 본 메시지(무마 발화·이미지 포함, attack_message_ids)
                attack_ids = set(attr.get("attack_message_ids") or [])
                anchors = [w for w in window if w["speaker"] in aggr and
                           ((w.get("cb") or 0) >= TOX_THRESHOLD or (w.get("message_id") in attack_ids))]
                if anchors:
                    a_first = min(w["ts"] for w in anchors)
                    a_last = max(w["ts"] for w in anchors)
                    if inc is None:
                        inc = Incident(uuid.uuid4().hex[:12], room, set(aggr), attr.get("victim"), a_first, a_last)
                        inc.aggressors.discard(inc.victim)
                        self._note_victim(inc, attr)
                        self.incidents[inc.incident_id] = inc
                        self.active_by_room[room] = inc.incident_id
                        self._queue(room, inc, None, "incident_open", now, self._roles_payload(inc))
                    else:
                        inc.last_anchor_ts = max(inc.last_anchor_ts, a_last)
                    new_ids = {w.get("message_id") or f"{w['speaker']}@{w['ts']}" for w in anchors} - inc.anchor_ids
                    inc.anchor_ids |= new_ids
                    inc.n_anchor = len(inc.anchor_ids)
                    # anyone now known as 가해자/피해자 is not a bystander
                    for c in list(inc.bystanders):
                        if c in inc.aggressors or c == inc.victim:
                            inc.bystanders.pop(c)
                    # children who were already looking at the room when the attack landed
                    for (r, c), seen in list(self.last_seen.items()):
                        if r == room and seen >= inc.first_anchor_ts and inc.role_of(c) == "주변인":
                            b = self._by(inc, c)
                            if b.stage == "unseen":
                                self._expose(inc, b, seen, now)

            # 2) a bystander talking during an active incident
            pending = None
            if inc is not None and not inc.closed and inc.role_of(speaker) == "주변인":
                self.last_seen[(room, speaker)] = max(self.last_seen.get((room, speaker), 0), t_msg)
                b = self._by(inc, speaker)
                if b.stage == "unseen" and t_msg >= inc.first_anchor_ts:
                    self._expose(inc, b, t_msg, now)           # posting in the room = present
                if b.stage != "unseen":
                    if new.get("is_defense_action"):
                        self._defend(inc, b, now, "방어 기능 메시지")
                    elif result.get("bystander_behavior"):
                        self._apply_label(inc, b, result["bystander_behavior"], now, "391")
                    elif (new.get("text") or "").strip():           # 본문 없는 메시지(이미지)는 발화 판정을 하지 않는다
                        inputs = self._classify_inputs(inc, req, speaker)
                        pending = (inc.incident_id, inputs, self._judge_key(inc.incident_id, inputs))
            if pending is None:
                return inc.to_dict() if inc else None

        # 3) LLM 판정은 잠금 밖에서 (v0.3.3). 그동안 다른 방의 요청과 타이머는 계속 돈다.
        iid, inputs, key = pending
        t0 = time.time()
        label, src, reason = self._classify_shared(key, inputs)   # 전송 전에 미리 판정했으면 그 결과를 쓴다
        self._log_judgment("record", key, room, iid, new.get("message_id"), inputs, label, src, reason, t0)
        with self._lock:
            inc = self.incidents.get(iid)
            if inc is None:
                return None
            if not inc.closed and inc.role_of(speaker) == "주변인":      # 그 사이 역할이 바뀌었으면 적용하지 않는다
                b = self._by(inc, speaker)
                if b.stage != "unseen":
                    self._apply_label(inc, b, label, now if fixed_now else time.time(), src, reason)
            return inc.to_dict()

    # ------------------------------------------------------------------ public: 전송 전 미리 판정 (v0.3.7)
    def preview(self, req: dict, now: Optional[float] = None, timeout: Optional[float] = None) -> Optional[dict]:
        """전송 전 호출용. 이 메시지가 전송 후 호출에서 어떻게 판정될지 미리 돌려준다. 상태는 바꾸지 않는다.
        사건이 열린 방에서 주변인이 본문 있는 메시지를 보낼 때만 판정하고, 아니면 None.
        Returns {"label": 방어|동조|방관|비해당, "source": LLM|규칙|규칙(시간 초과)|방어 기능, "incident_id": ...,
                 "reason": 판정 근거 (v0.3.8)}."""
        return self.preview_end(self.preview_begin(req, now), timeout)

    def preview_begin(self, req: dict, now: Optional[float] = None) -> Optional[dict]:
        """v0.3.9: 판정할 메시지면 LLM 판정을 바로 시작해 두고 손잡이를 돌려준다 (기다리지 않는다).
        app은 이것을 모델 추론보다 먼저 불러, 모델이 도는 동안 LLM도 함께 돌게 한다. 판정 대상이 아니면 None."""
        room = req["room_id"]
        new = req["new_message"]
        speaker = new["participant_code"]
        text = (new.get("text") or "").strip()
        now = now if now is not None else time.time()
        with self._lock:
            inc = self._active(room)
            if inc is None or now - inc.last_anchor_ts >= INCIDENT_IDLE_CLOSE_SEC:   # 곧 닫힐 사건은 보지 않는다
                return None
            if inc.role_of(speaker) != "주변인":
                return None
            if new.get("is_defense_action"):
                return {"done": {"label": "방어", "source": "방어 기능", "incident_id": inc.incident_id,
                                 "reason": "방어 기능 메시지"}}
            if not text:
                return None
            inputs = self._classify_inputs(inc, req, speaker)
            key = self._judge_key(inc.incident_id, inputs)
            iid = inc.incident_id
        t0 = time.time()
        return {"key": key, "inputs": inputs, "iid": iid, "room": room, "mid": new.get("message_id"),
                "t0": t0, "job": self._classify_start(key, inputs)}

    def preview_end(self, h: Optional[dict], timeout: Optional[float] = None) -> Optional[dict]:
        """v0.3.9: preview_begin의 판정을 timeout초까지 기다린다. 시간 예산은 여기서부터 센다.
        (그래서 아이가 기다리는 시간의 상한은 예전과 같고, LLM은 모델 추론 시간만큼 먼저 출발한다.)"""
        if h is None:
            return None
        if "done" in h:
            return h["done"]
        timeout = PREVIEW_TIMEOUT_SEC if timeout is None else timeout
        w0 = time.time()
        job, inputs = h["job"], h["inputs"]
        try:
            label, src, reason = job if isinstance(job, tuple) else job.result(timeout=timeout)
        except _FutTimeout:                      # LLM은 뒤에서 마저 돌고, 끝나면 전송 후 호출이 그 결과를 쓴다
            label, src = self._heuristic(inputs[5], inputs[3]), "규칙(시간 초과)"
            reason = (f"LLM이 {timeout:g}초 안에 답하지 않아 키워드 규칙으로 판정 "
                      f"(LLM 출발 후 {int((time.time() - h['t0']) * 1000)}ms)")
        self.last_preview_wait_ms = int((time.time() - w0) * 1000)
        self._log_judgment("preview", h["key"], h["room"], h["iid"], h["mid"], inputs, label, src, reason, h["t0"])
        return {"label": label, "source": src, "incident_id": h["iid"], "reason": reason}

    def has_open_incident(self, room: str) -> bool:
        """v0.3.9: 이 방에 열린 사건이 있는가 (LLM 미리 깨우기 판단용)."""
        with self._lock:
            return self._active(room) is not None

    @staticmethod
    def _judge_key(iid: str, inputs: tuple) -> str:
        turns, tagged, text, _, reply, _raw = inputs
        raw = json.dumps([iid, turns, tagged, text.strip(), reply], ensure_ascii=False)
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def _classify_shared(self, key: str, inputs: tuple, timeout: Optional[float] = None) -> tuple:
        """같은 판정은 한 번만 돌린다. 끝난 LLM 판정은 PREVIEW_CACHE_SEC 동안 재사용, 도는 중이면 그것을 기다린다.
        timeout 안에 끝나지 않으면 concurrent.futures.TimeoutError (판정은 계속 돈다)."""
        job = self._classify_start(key, inputs)
        return job if isinstance(job, tuple) else job.result(timeout=timeout)

    def _classify_start(self, key: str, inputs: tuple):
        """-> 이미 끝난 판정 (label, src, reason) 또는 도는 중인 Future. 없으면 새로 시작한다."""
        now = time.time()
        with self._lock:
            for k in [k for k, v in self._judged.items() if v[3] <= now]:
                self._judged.pop(k, None)
            hit = self._judged.get(key)
            if hit:
                return hit[0], hit[1], hit[2]
            fut = self._inflight.get(key)
            if fut is None:
                fut = self._pool.submit(self._run_classifier, *inputs)
                self._inflight[key] = fut
                fut.add_done_callback(lambda f, k=key: self._remember_judgment(k, f))
        return fut

    def _remember_judgment(self, key: str, fut):
        with self._lock:
            self._inflight.pop(key, None)
            if fut.cancelled() or fut.exception() is not None:
                return
            label, src, reason = fut.result()
            if src == "LLM":                     # 규칙 판정은 기억하지 않는다 (다음 호출이 LLM을 다시 시도)
                self._judged[key] = (label, src, reason, time.time() + PREVIEW_CACHE_SEC)

    # ------------------------------------------------------------------ public: app events
    def on_event(self, ev: dict, now: Optional[float] = None) -> list:
        """ev: {room_id, participant_code, type, timestamp?, ...}. Returns actions drained for the room."""
        room, code, typ = ev["room_id"], ev["participant_code"], ev["type"]
        now = now if now is not None else time.time()
        t = _ts(ev.get("timestamp"), now)
        with self._lock:
            if typ in ("read", "room_open", "join"):
                self.last_seen[(room, code)] = max(self.last_seen.get((room, code), 0), t)
            self._tick_locked(now)
            inc = self._active(room)
            if inc is None or inc.role_of(code) != "주변인":
                return self._drain_locked(room)
            b = self._by(inc, code)

            if typ in ("read", "room_open", "join"):
                if b.stage == "unseen" and t >= inc.first_anchor_ts:
                    self._expose(inc, b, t, now, unread=ev.get("unread_count"))
                if b.badge:                                   # came back after leaving silently
                    b.badge = False
                    b.stage = "confirmed"
                    b.log(now, "재입장")
                    self._queue(room, inc, b, "choices", now)

            elif typ == "summary_shown":                      # delayed witness: clock starts now
                if b.stage in ("observing", "candidate"):
                    b.exposed_at = t
                    b.stage = "observing"
                    b.log(now, "요약 확인")

            elif typ == "reaction" and b.stage != "unseen":
                target = ev.get("target_participant_code") or self.msg_speaker.get((room, ev.get("target_message_id")))
                beh = reaction_to_behavior(inc.role_of(target), ev.get("reaction", ""))
                if beh == "방어":
                    self._defend(inc, b, now, f"반응 버튼({ev.get('reaction')}→{inc.role_of(target)})")
                elif beh == "동조":
                    self._join(inc, b, now, f"반응 버튼({ev.get('reaction')}→{inc.role_of(target)})", cancellable=True)

            elif typ == "reaction_cancel":
                if b.stage == "joined" and b._undo and b._undo_until and now <= b._undo_until:
                    b.stage, b.behavior, b.subtype = b._undo
                    b._undo = b._undo_until = None
                    b.log(now, "동조 반응 즉시 취소 → 동조 제외")

            elif typ == "defense_action" and b.stage != "unseen":
                self._defend(inc, b, now, f"방어 기능({ev.get('kind') or '선택'})")

            elif typ == "leave":
                if not ev.get("normal", True):
                    b.log(now, "비정상 종료(판정 제외)")
                elif b.stage in ("observing", "candidate", "confirmed"):
                    b.stage, b.behavior, b.subtype = "left", "방관", "채팅방 나가기"
                    b.decided_at, b.badge, b.was_bystanding = now, True, True
                    b.log(now, "방관: 채팅방 나가기")
                    self._queue(room, inc, b, "badge", now)

            elif typ in ("decline", "not_bullying"):
                b.declined = True
                if b.stage in ("observing", "candidate"):
                    b.stage = "closed"
                b.log(now, "개입 거절" if typ == "decline" else "사용자 판단: 괴롭힘 아님")

            return self._drain_locked(room)

    # ------------------------------------------------------------------ public: timers / queries
    def tick(self, now: Optional[float] = None):
        with self._lock:
            self._tick_locked(now if now is not None else time.time())

    def drain(self, room: str, now: Optional[float] = None) -> list:
        with self._lock:
            self._tick_locked(now if now is not None else time.time())
            return self._drain_locked(room)

    def state(self, room: str, code: Optional[str] = None) -> Optional[dict]:
        with self._lock:
            iid = self.active_by_room.get(room)
            inc = self.incidents.get(iid) if iid else None
            if inc is None:
                return None
            d = inc.to_dict()
            if code:
                d["bystanders"] = [x for x in d["bystanders"] if x["participant_code"] == code]
            return d

    def start_background(self, interval: float = 1.0):
        if self._thread and self._thread.is_alive():
            return
        def loop():
            while not self._stop.wait(interval):
                try:
                    self.tick()
                except Exception as e:                    # never let the timer thread die
                    print("[bystander] tick error:", e)
        self._thread = threading.Thread(target=loop, name="bystander-tick", daemon=True)
        self._thread.start()

    def stop_background(self):
        self._stop.set()

    # ------------------------------------------------------------------ internals
    @staticmethod
    def _roles_payload(inc: Incident, **extra) -> dict:
        return {"aggressors": sorted(inc.aggressors), "victim": inc.victim, "victim_reason": inc.victim_reason,
                "victim_status": "confirmed" if inc.victim_confirmed else "provisional", **extra}

    @staticmethod
    def _note_victim(inc: Incident, attr: dict) -> bool:
        """판정이 지금 피해자를 다시 가리켰다. 근거를 쌓고, 새로 confirmed가 되면 True."""
        reason = attr.get("victim_reason")
        rank = VICTIM_RANK.get(reason, 0)
        inc.victim_verdicts += 1
        if inc.victim_reason is None or rank > inc.victim_rank:
            inc.victim_reason, inc.victim_rank = reason, rank
        inc._cand, inc._cand_streak, inc._cand_rank, inc._cand_reason = None, 0, 0, None
        was = inc.victim_confirmed
        inc.victim_confirmed = was or inc.victim_rank >= VICTIM_CONFIRM_RANK \
            or attr.get("victim_support") == "strong"
        if inc.victim_confirmed:                       # 본인의 항의로 확정된 피해자도 이름 지목과 같은 세기
            inc.victim_rank = max(inc.victim_rank, VICTIM_CONFIRM_RANK)
        return inc.victim_confirmed and not was

    def _update_victim(self, room: str, inc: Incident, attr: dict, aggr: set, now: float):
        """Follow the latest /analyze verdict instead of freezing the first victim (v0.3.2)."""
        v = attr.get("victim")
        if not v:
            return
        if inc.victim is None:
            inc.victim = v
        if v == inc.victim:
            if self._note_victim(inc, attr):
                self._queue(room, inc, None, "incident_update", now,
                            self._roles_payload(inc, change="victim_confirmed"))
            return
        reason = attr.get("victim_reason")
        rank = VICTIM_RANK.get(reason, 0)
        if v == inc._cand:
            inc._cand_streak += 1
            if rank > inc._cand_rank:
                inc._cand_rank, inc._cand_reason = rank, reason
        else:
            inc._cand, inc._cand_streak, inc._cand_rank, inc._cand_reason = v, 1, rank, reason
        strong = attr.get("victim_support") == "strong"
        if strong:
            inc._cand_rank = max(inc._cand_rank, VICTIM_CONFIRM_RANK)
        # 지금 피해자가 가해자로 판정되면 바로 바꾸되, 이미 확정된 피해자는 그것만으로 바꾸지 않는다
        if (inc.victim in aggr and not inc.victim_confirmed) or inc._cand_rank > inc.victim_rank:
            need = 1
        elif inc._cand_rank == inc.victim_rank:
            need = VICTIM_SWITCH_SAME
        else:
            need = VICTIM_SWITCH_WEAKER
        if inc._cand_streak < need:
            return
        old, streak = inc.victim, inc._cand_streak
        inc.previous_victims.append(old)
        inc.victim, inc.victim_reason, inc.victim_rank = v, inc._cand_reason, inc._cand_rank
        inc.victim_verdicts = streak
        inc.victim_confirmed = inc.victim_rank >= VICTIM_CONFIRM_RANK or strong
        if inc.victim_confirmed:
            inc.victim_rank = max(inc.victim_rank, VICTIM_CONFIRM_RANK)
        inc._cand, inc._cand_streak, inc._cand_rank, inc._cand_reason = None, 0, 0, None
        inc.aggressors.discard(v)
        was_bystander = inc.bystanders.pop(v, None)
        self._queue(room, inc, None, "incident_update", now, self._roles_payload(
            inc, change="victim_changed", previous_victim=old,
            previous_victim_role="가해자" if old in (inc.aggressors | aggr) else "주변인",
            new_victim_was_bystander=was_bystander.behavior if was_bystander else None))

    def _active(self, room: str) -> Optional[Incident]:
        iid = self.active_by_room.get(room)
        inc = self.incidents.get(iid) if iid else None
        return inc if inc and not inc.closed else None

    def _by(self, inc: Incident, code: str) -> Bystander:
        if code not in inc.bystanders:
            inc.bystanders[code] = Bystander(code)
        return inc.bystanders[code]

    def _expose(self, inc: Incident, b: Bystander, t: float, now: float, unread: Optional[int] = None):
        b.exposed_at, b.stage = t, "observing"
        b.log(now, "노출(사건 메시지 확인)")
        late = (t - inc.last_anchor_ts) >= LATE_WITNESS_SEC or (unread is not None and unread >= SUMMARY_UNREAD_MIN)
        if late:
            b.log(now, "지연 목격 → 요약 제공")
            self._queue(inc.room_id, inc, b, "summary", now, {
                "aggressors": sorted(inc.aggressors), "victim": inc.victim,
                "n_attack_messages": inc.n_anchor,
                "first_attack_at": _iso(inc.first_anchor_ts), "last_attack_at": _iso(inc.last_anchor_ts)})

    def _tick_locked(self, now: float):
        for inc in list(self.incidents.values()):
            if inc.closed:
                continue
            if now - inc.last_anchor_ts >= INCIDENT_IDLE_CLOSE_SEC:
                inc.closed = True
                self.active_by_room.pop(inc.room_id, None)
                for b in inc.bystanders.values():
                    if b.stage in ("observing", "candidate"):
                        b.stage = "closed"
                        b.log(now, "사건 종료")
                continue
            for b in inc.bystanders.values():
                if b.declined or b.exposed_at is None:
                    continue
                if b._undo_until and now > b._undo_until:        # 동조 reaction no longer cancellable
                    b._undo = b._undo_until = None
                t1, t2 = b.exposed_at + T1_SEC, b.exposed_at + T2_SEC
                if b.stage == "observing" and t1 <= now < t2:
                    b.stage = "candidate"
                    b.log(now, "방관 후보(무반응 T1)")
                    self._nudge(inc, b, "nudge_1", now)
                elif b.stage in ("observing", "candidate") and now >= t2:
                    skipped_first = b.stage == "observing"          # clock jumped past both
                    b.stage, b.behavior = "confirmed", "방관"
                    b.subtype = b.subtype or "침묵"
                    b.decided_at, b.was_bystanding = now, True
                    b.log(now, f"방관 확정({b.subtype})")
                    if skipped_first:
                        b.log(now, "1차 알림 생략(지연 처리)")
                    self._nudge(inc, b, "nudge_2", now, {"choices": True})

    def _nudge(self, inc: Incident, b: Bystander, kind: str, now: float, payload: Optional[dict] = None):
        if b.nudges >= MAX_NUDGES or b.declined:
            b.log(now, f"{kind} 생략(최대 횟수/거절)")
            return
        b.nudges += 1
        self._queue(inc.room_id, inc, b, kind, now, payload)

    def _apply_label(self, inc: Incident, b: Bystander, label: Optional[str], now: float, src: str = "391",
                     reason: Optional[str] = None):
        """src: 'LLM' | '규칙'(LLM이 꺼져 있거나 답하지 못함) | '391'(/analyze가 준 값)
        reason: v0.3.8 판정 근거. 판정 기록 바로 다음 줄에 '판정 근거: …'로 남긴다."""
        n_before = len(b.history)
        self._apply_label_core(inc, b, label, now, src)
        if reason and len(b.history) > n_before:
            b.log(now, f"판정 근거: {str(reason)[:200]}")

    def _apply_label_core(self, inc: Incident, b: Bystander, label: Optional[str], now: float, src: str):
        if label == "방어":
            self._defend(inc, b, now, f"발화({src})")
        elif label == "동조":
            self._join(inc, b, now, f"발화({src})", cancellable=False)
        elif label not in UNRELATED_LABELS:
            note = f"발화 판정: {label or '없음'}({src})"            # 판정이 돌았다는 기록. 타이머는 그대로 돈다
            if not b.history or b.history[-1]["event"] != note:
                b.log(now, note)
        elif label in UNRELATED_LABELS:
            b.log(now, "무관한 대화")
            if b.stage == "observing":
                b.stage, b.behavior, b.subtype = "candidate", "방관", "무관 대화"
                self._nudge(inc, b, "nudge_1", now)
            elif b.stage in ("candidate", "confirmed") and b.subtype is None:
                b.behavior, b.subtype = "방관", "무관 대화"

    def _defend(self, inc: Incident, b: Bystander, now: float, source: str):
        if b.was_bystanding or b.behavior == "방관":
            b.log(now, "행동 전환: 방관→방어")
        if b.behavior == "동조":
            b.log(now, "행동 전환: 동조→방어")
        b.stage, b.behavior, b.subtype, b.decided_at = "defended", "방어", None, now
        b.badge, b._undo, b._undo_until = False, None, None
        b.log(now, f"방어: {source}")
        self._queue(inc.room_id, inc, b, "positive_feedback", now)

    def _join(self, inc: Incident, b: Bystander, now: float, source: str, cancellable: bool):
        if cancellable and b.stage != "joined":
            b._undo, b._undo_until = (b.stage, b.behavior, b.subtype), now + REACTION_CANCEL_SEC
        b.stage, b.behavior, b.subtype, b.decided_at = "joined", "동조", None, now
        b.log(now, f"동조: {source}")
        self._queue(inc.room_id, inc, b, "join_feedback", now, {"cancel_window_sec": REACTION_CANCEL_SEC if cancellable else 0})

    def _classify_inputs(self, inc: Incident, req: dict, speaker: str) -> tuple:
        """잠금 안에서: 판정에 필요한 것만 뽑아 둔다.
        -> (맥락 turns, 발화자 표시, 대상 발화, 바로 앞 상대가 가해자인지, 답장 대상 (표시, 본문) | None, 원문)
        v0.3.8: 본문 속 아이 이름은 '코드(역할)'로 바꾸고, 답장이면 답장 대상 메시지와 그 화자의 역할을 함께 넘긴다."""
        room = req["room_id"]
        full = req.get("context", [])
        ctx = full[-CONTEXT_TURNS:]
        tag = lambda c: f"{c}({inc.role_of(c)})"
        mask = self._name_masker(room, req, tag)
        turns = [(tag(m["participant_code"]), mask(m.get("text") or "")) for m in ctx]
        raw = req["new_message"].get("text") or ""
        reply, reply_code = None, None
        rid = req["new_message"].get("reply_to_message_id")
        if rid:
            m = next((m for m in reversed(full) if m.get("message_id") == rid), None)
            reply_code = m["participant_code"] if m else self.msg_speaker.get((room, rid))
            if reply_code:
                reply = (tag(reply_code), mask((m or {}).get("text") or "") if m else "(본문은 맥락 밖)")
        if reply_code is not None:                  # 답장이면 '바로 앞 상대'는 답장 대상의 화자다
            prev = reply_code if reply_code != speaker else None
        else:
            prev = next((m["participant_code"] for m in reversed(ctx) if m["participant_code"] != speaker), None)
        return turns, tag(speaker), mask(raw), prev in inc.aggressors, reply, raw

    @staticmethod
    def _name_masker(room: str, req: dict, tag: Callable) -> Callable:
        """본문 속 아이 이름 -> '코드(역할)'. 조사는 남긴다 ("유진이 이상함" -> "P03(가해자)이 이상함").
        명단은 이 요청의 participants·classmates, 없으면 이 방에서 전에 받은 명단."""
        toks = _ROSTERS.tokens(room)
        toks.update(_tokens_of(req.get("classmates") or []))
        toks.update(_tokens_of(req.get("participants") or []))
        table = []
        for code, ts in toks.items():
            pat = _name_pattern(ts)
            if pat is not None:
                table.append((code, pat, sorted(ts, key=len, reverse=True)))
        if not table:
            return lambda t: t

        def mask(text: str) -> str:
            if not text:
                return text
            for code, pat, ts in table:
                def sub(m, code=code, ts=ts):
                    s = m.group(0)
                    tok = next((t for t in ts if s.startswith(t)), "")
                    return tag(code) + s[len(tok):]
                text = pat.sub(sub, text)
            return text
        return mask

    def _run_classifier(self, turns, tagged_speaker, text, prev_is_aggressor, reply=None, raw_text=None) -> tuple:
        """잠금 밖에서: (label, 출처, 근거). LLM이 답하지 못하면(None·예외) 키워드 규칙으로 대신 판정한다.
        classify는 label 또는 (label, reason)을 돌려준다. 답장이 있으면 reply=(표시, 본문)을 키워드로 넘긴다."""
        if self.classify is not None:
            try:
                out = self.classify(turns, tagged_speaker, text, reply=reply) if reply else \
                    self.classify(turns, tagged_speaker, text)
                label, reason = (out if isinstance(out, tuple) else (out, None))
                if label:
                    return label, "LLM", reason
            except Exception as e:
                print("[bystander] classifier error:", e)
        return self._heuristic(raw_text if raw_text is not None else text, prev_is_aggressor), "규칙", "키워드 규칙"

    def _log_judgment(self, kind: str, key: str, room: str, iid: str, mid: Optional[str], inputs: tuple,
                      label: str, src: str, reason: Optional[str], t0: float):
        """v0.3.8: 판정 한 건 = 서버 로그 한 줄. preview와 record가 같은 key면 같은 판정을 쓴 것이다."""
        if not JUDGE_LOG:
            return
        reply = inputs[4]
        print(f"[bystander] judge {kind} key={key[:10]} room={room} incident={iid} msg={mid} "
              f"label={label} src={src} wait_ms={int((time.time() - t0) * 1000)} "
              f"text={inputs[2]!r} reply_to={reply[0] if reply else None} reason={reason}", flush=True)

    @staticmethod
    def _heuristic(text: str, prev_is_aggressor: bool) -> str:
        """LLM 없이: 보수적인 낱말 규칙. 말리거나 항의하는 말 -> 방어, 가해자 바로 뒤의 맞장구·웃음·무마 -> 동조."""
        st = _stance(text)
        if st in ("protest", "defend") or (st == "neutral" and _DEFEND_RE.search(text)):
            return "방어"
        if prev_is_aggressor and (st in ("agree", "dismiss") or _AGREE_RE.search(text)):
            return "동조"
        return "비해당"          # no change; the silence timer keeps running

    def _classify(self, inc: Incident, req: dict, speaker: str) -> Optional[str]:
        return self._run_classifier(*self._classify_inputs(inc, req, speaker))[0]

    def _queue(self, room: str, inc: Incident, b: Optional[Bystander], action: str, now: float,
               payload: Optional[dict] = None):
        a = {"action_id": uuid.uuid4().hex[:12], "room_id": room, "incident_id": inc.incident_id,
             "participant_code": b.code if b else None, "action": action,
             "text": NUDGE_TEXT.get(action), "created_at": _iso(now), "payload": payload or {}}
        if self.webhook:      # push mode: deliver once via webhook, nothing to poll
            threading.Thread(target=self._post_webhook, args=(a,), daemon=True).start()
        else:                 # poll mode: GET /bystander/actions or the /bystander/events response
            self._actions.setdefault(room, []).append(a)

    def _drain_locked(self, room: str) -> list:
        return self._actions.pop(room, [])

    def _post_webhook(self, a: dict):
        try:
            import urllib.request
            req = urllib.request.Request(self.webhook, data=json.dumps(a, ensure_ascii=False).encode("utf-8"),
                                         headers={"Content-Type": "application/json"}, method="POST")
            urllib.request.urlopen(req, timeout=5).read()
        except Exception as e:
            print("[bystander] webhook error:", e)
