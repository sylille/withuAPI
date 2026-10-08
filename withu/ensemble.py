"""Ensemble: combine module scores → cb_score, apply the .75 / .85 gates.

The Ensemble takes *callables*, not model objects, so it can be unit-tested with mocks
and so real models load lazily in app startup. Module contracts:

  message_scorer(text: str)                      -> float 0..1   (Phase 1)
  context_scorer(window_texts: list[str])        -> float 0..1   (Phase 2)
  exclusion_scorer(logs: dict)                    -> float 0..1   (Phase 3, optional/stub)
  bystander_fn(context, speaker, text, logs)      -> dict{'behavior',...} (Phase 4, optional)
"""
import inspect
import os
import re
from typing import Callable, List, Optional, Dict
from .check_chat_excel import prosocial_guard, TOX_THRESHOLD
from .target_resolver import evaluate_window_v2 as evaluate_window
from .target_resolver import message_flags, RESIST_CAP, PSEUDO_CB

# v0.3.3 -----------------------------------------------------------------------------------------
# 점수 합치는 방법. "gated"(기본): cb_score는 '이 메시지'의 점수다. 맥락 점수(모듈 B)는 창 전체에 대한 값이라
#   메시지 자체가 공격일 가능성이 반 이상(모듈 A >= 0.5)일 때만 가중 평균으로 점수를 올린다.
#   예전 방식("max_of")은 맥락 점수 하나만 높아도 그 창의 모든 메시지(피해자의 말 포함)가 언어적 폭력이 됐다.
COMBINE_MODE   = os.environ.get("WITHU_COMBINE_MODE", "gated")
# 모듈 B는 6개짜리 창으로 학습했다. 메시지가 이보다 적으면 점수를 믿을 수 없어 계산하지 않는다 (첫 메시지 0.998 문제).
CTX_MIN_WINDOW = int(os.environ.get("WITHU_CTX_MIN_WINDOW", 4))
CTX_WINDOW     = int(os.environ.get("WITHU_CTX_WINDOW", 6))          # 모듈 B에 넘기는 최근 메시지 수
CTX_SPEAKERS   = os.environ.get("WITHU_CTX_SPEAKERS", "1") != "0"    # 학습 때처럼 발화자를 A/B/C로 구분해 넘김
IMAGE_TEXT     = "사진"                                               # 본문 없는 이미지를 모듈 B에 넘길 때 쓰는 말
_IMAGE_ONLY    = re.compile(r"^\s*[\[(<]?\s*(?:사진|이미지|그림|photo|image)\s*[\])>]?\s*$", re.I)


def is_blank(text) -> bool:
    """본문이 없거나 이미지 자리표시("[사진]")뿐인 메시지. 모듈 A에 넘기지 않는다 (점수 0)."""
    t = (text or "").strip()
    return not t or bool(_IMAGE_ONLY.match(t))


class Ensemble:
    def __init__(self,
                 message_scorer: Callable[[str], float],
                 context_scorer: Callable[[List[str]], float],
                 exclusion_scorer: Optional[Callable[[dict], float]] = None,
                 bystander_fn: Optional[Callable] = None,
                 weights: Optional[Dict[str, float]] = None,
                 combine_mode: Optional[str] = None,
                 suspect: float = 0.75,
                 confirm: float = 0.85):
        self.message_scorer = message_scorer
        self.context_scorer = context_scorer
        self.exclusion_scorer = exclusion_scorer
        self.bystander_fn = bystander_fn
        # weights over AVAILABLE modules; renormalized per request (missing modules dropped)
        self.weights = weights or {"message": 0.5, "context": 0.4, "exclusion": 0.1}
        # how to fuse module scores. TUNE THIS on labeled full conversations:
        #   "weighted" : weighted average (smooth, but dilutes a single strong signal)
        #   "noisy_or" : 1-Π(1-s)   (fires if ANY module is high; can over-trigger)
        #   "max_of"   : max(weighted_avg, strongest single module)  (v0.3.2까지의 기본값)
        #   "gated"    : 메시지 점수가 기준. 맥락은 메시지가 0.5 이상일 때만 올림  ← v0.3.3 기본값
        self.combine_mode = combine_mode or COMBINE_MODE
        try:      # 맥락 채점기가 (texts, speakers)를 받는지. 예전 채점기·테스트용 람다는 texts만 받는다
            self._ctx_takes_speakers = len(inspect.signature(context_scorer).parameters) >= 2
        except (TypeError, ValueError):
            self._ctx_takes_speakers = False
        self.suspect = suspect
        self.confirm = confirm

    def score_message(self, text) -> float:
        """모듈 A. 본문이 없는 메시지(이미지 등)는 모델에 넘기지 않고 0점."""
        return 0.0 if is_blank(text) else float(self.message_scorer(text))

    def score_context(self, msgs: List[dict]) -> Optional[float]:
        """모듈 B. 메시지가 CTX_MIN_WINDOW개보다 적으면 None (판단 보류)."""
        if len(msgs) < CTX_MIN_WINDOW:
            return None
        msgs = msgs[-CTX_WINDOW:]
        texts = [IMAGE_TEXT if is_blank(m.get("text")) else m["text"] for m in msgs]
        if self._ctx_takes_speakers and CTX_SPEAKERS:
            return float(self.context_scorer(texts, [m.get("participant_code") for m in msgs]))
        return float(self.context_scorer(texts))

    def _combine(self, scores: Dict[str, Optional[float]]) -> float:
        present = {k: v for k, v in scores.items() if v is not None and k in self.weights}
        if not present:
            return 0.0
        wsum = sum(self.weights[k] for k in present)
        weighted = sum(self.weights[k] * present[k] for k in present) / wsum
        if self.combine_mode == "gated":
            m = present.get("message", 0.0)
            return max(m, weighted) if m >= TOX_THRESHOLD else m
        if self.combine_mode == "weighted":
            return weighted
        if self.combine_mode == "noisy_or":
            prod = 1.0
            for v in present.values():
                prod *= (1.0 - v)
            return 1.0 - prod
        # "max_of": don't let a strong single module (e.g. clear exclusion, or one
        # unambiguously toxic message) be washed out by calm signals elsewhere.
        return max(weighted, max(present.values()))

    def analyze(self, req: dict) -> dict:
        ctx: List[dict] = req.get("context", [])
        new = req["new_message"]
        new_text = new.get("text") or ""
        is_def = bool(new.get("is_defense_action", False))              # NEW
        track = bool(req.get("track_bystander", True))

        m_score = self.score_message(new_text)
        c_score = self.score_context(ctx + [new])
        e_score = None
        if self.exclusion_scorer is not None and req.get("logs"):
            e_score = float(self.exclusion_scorer(req["logs"]))
        scores = {"message": m_score, "context": c_score, "exclusion": e_score}
        cb_score = self._combine(scores)

        # NEW: prosocial guard on the new message → fixes the comfort-message FP (Bug 1)
        cb_score, suppressed, guard_reason = prosocial_guard(
            new_text, cb_score, is_defense_action=is_def)
        # v0.3.3: 항의·말리기("하지 말라고", "그만해")도 점수가 높게 나오지만 공격이 아니다 → 전송 전 경고를 띄우지 않는다
        flags = message_flags(new_text, new.get("participant_code"), req.get("room_id"))
        if not suppressed and flags["stance"] in ("protest", "defend") and cb_score >= TOX_THRESHOLD:
            cb_score, suppressed, guard_reason = min(cb_score, RESIST_CAP), True, "resistance"

        types = []
        if not suppressed and cb_score >= self.suspect: types.append("언어적 폭력")
        if not suppressed and e_score is not None and e_score >= self.suspect: types.append("배제")
        # v0.3.3: 이름 + 배제 표현("○○는 빼고 하자"). 낱말 규칙이며 cb_score에는 넣지 않는다
        if not suppressed and flags["exclusion_targets"] and "배제" not in types:
            types.append("배제")
            scores["exclusion"] = e_score = max(e_score or 0.0, PSEUDO_CB)
        cb_type = "·".join(types) if types else "비해당"

        # NEW: per-message attribution over the window → 가해자/피해자 + targeting-aware verdict
        items = []
        for m in ctx + [new]:
            a = self.score_message(m.get("text"))
            cb_m, _, _ = prosocial_guard(m.get("text") or "", a,
                                         is_defense_action=bool(m.get("is_defense_action", False)))
            items.append({"speaker": m["participant_code"], "text": m.get("text") or "",
                          "cb": cb_m, "dis": None})
        verdict = evaluate_window(items)
        attr = verdict["attr"]

        # CHANGED: full intervention now requires a high score AND a real target (fixes Bug 2)
        if cb_score >= self.confirm and verdict["is_bullying"]:
            level, need = "confirm", True
        elif cb_score >= self.suspect:
            level, need = "suspect", False       # aggressor-facing pre-send warning, unchanged
        else:
            level, need = "none", False

        # v0.3.3: LLM(모듈 D)은 전송 전 호출(track_bystander=false)에서는 절대 부르지 않는다.
        # 실서버(app.py)는 bystander_fn을 넘기지 않고, 사건이 열린 방의 주변인 발화만 방관 판정부가 판정한다.
        bystander = None
        if track and level != "none" and self.bystander_fn is not None:
            ctx_turns = [(m["participant_code"], m.get("text") or "") for m in ctx]
            try:
                bystander = self.bystander_fn(ctx_turns, new["participant_code"],
                                              new_text, req.get("logs")).get("behavior")
            except Exception:
                bystander = None

        evidence = (f"msg={m_score:.2f} ctx=" + ("-" if c_score is None else f"{c_score:.2f}")
                    + (f" excl={e_score:.2f}" if e_score is not None else "")
                    + f" → cb={cb_score:.2f} [{level}]")

        return {"room_id": req.get("room_id", ""),
                "cb_score": round(cb_score, 4), "cb_type": cb_type,
                "intervention_level": level, "intervention_needed": need,
                "attribution": {                                          # NEW block
                    "is_bullying": verdict["is_bullying"],
                    "aggressors": attr.aggressors,        # 가해자
                    "victim": attr.victim,                # 피해자
                    "victim_reason": attr.victim_reason,
                    "confidence": attr.confidence,
                    "drop_reason": verdict["drop_reason"],
                    # v0.3.2: 서버가 공격으로 센 메시지 (무마 발화·이미지 포함) -> 방관 판정부의 사건 메시지
                    "attack_message_ids": verdict.get("attack_mids", []),
                    # v0.3.2: strong = 답장·이름 지목 또는 본인의 항의 2번 이상, weak = 반응 패턴뿐
                    "victim_support": verdict.get("victim_support", "weak"),
                    # v0.3.3: 피해자 본인의 분명한 항의 메시지 수, 공격으로 센 근거(배제 발화·이미지·무마)
                    "victim_protests": verdict.get("victim_protests", 0),
                    "attack_notes": verdict.get("attack_notes", [])},
                "suppressed": suppressed, "guard_reason": guard_reason,   # NEW
                "bystander_behavior": bystander,
                "module_scores": {"message": round(m_score, 4),
                                  "context": (round(c_score, 4) if c_score is not None else None),
                                  "exclusion": (round(e_score, 4) if e_score is not None else None)},
                "evidence": evidence}
