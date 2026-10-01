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
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Optional

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

    def role_of(self, code: Optional[str]) -> Optional[str]:
        if code is None: return None
        if code in self.aggressors: return "가해자"
        if code == self.victim:     return "피해자"
        return "주변인"

    def to_dict(self) -> dict:
        return {"incident_id": self.incident_id, "room_id": self.room_id, "active": not self.closed,
                "aggressors": sorted(self.aggressors), "victim": self.victim,
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
                anchors = [w for w in window if w["speaker"] in aggr and (w.get("cb") or 0) >= TOX_THRESHOLD]
                if anchors:
                    a_first = min(w["ts"] for w in anchors)
                    a_last = max(w["ts"] for w in anchors)
                    if inc is None:
                        inc = Incident(uuid.uuid4().hex[:12], room, set(aggr), attr.get("victim"), a_first, a_last)
                        self.incidents[inc.incident_id] = inc
                        self.active_by_room[room] = inc.incident_id
                        self._queue(room, inc, None, "incident_open", now,
                                    {"aggressors": sorted(aggr), "victim": inc.victim})
                    else:
                        inc.aggressors |= aggr
                        inc.victim = inc.victim or attr.get("victim")
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
            if inc is not None and not inc.closed and inc.role_of(speaker) == "주변인":
                self.last_seen[(room, speaker)] = max(self.last_seen.get((room, speaker), 0), t_msg)
                b = self._by(inc, speaker)
                if b.stage == "unseen" and t_msg >= inc.first_anchor_ts:
                    self._expose(inc, b, t_msg, now)           # posting in the room = present
                if b.stage != "unseen":
                    if new.get("is_defense_action"):
                        self._defend(inc, b, now, "방어 기능 메시지")
                    else:
                        label = result.get("bystander_behavior") or self._classify(inc, req, speaker)
                        self._apply_label(inc, b, label, now)
            return inc.to_dict() if inc else None

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

    def _apply_label(self, inc: Incident, b: Bystander, label: Optional[str], now: float):
        if label == "방어":
            self._defend(inc, b, now, "발화(391)")
        elif label == "동조":
            self._join(inc, b, now, "발화(391)", cancellable=False)
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

    def _classify(self, inc: Incident, req: dict, speaker: str) -> Optional[str]:
        ctx = req.get("context", [])[-CONTEXT_TURNS:]
        tag = lambda c: f"{c}({inc.role_of(c)})"
        turns = [(tag(m["participant_code"]), m.get("text", "")) for m in ctx]
        text = req["new_message"].get("text", "")
        if self.classify is not None:
            try:
                return self.classify(turns, tag(speaker), text)
            except Exception as e:
                print("[bystander] classifier error:", e)
                return None
        # heuristic fallback (no LLM): conservative
        if _DEFEND_RE.search(text):
            return "방어"
        prev = ctx[-1]["participant_code"] if ctx else None
        if _AGREE_RE.search(text) and prev in inc.aggressors:
            return "동조"
        return "비해당"          # no change; the silence timer keeps running

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
