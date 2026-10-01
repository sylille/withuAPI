"""WithU Talk — AI inference server (AI 추론 서버).

Run (ONE worker — the 방관 tracker keeps state in memory):
    cd ~/Downloads
    uvicorn withu.app:app --host 0.0.0.0 --port 8000 --workers 1

The WithU backend POSTs a message + recent context to /analyze and gets back a
cyberbullying judgment. v0.3.0 adds the 방관행동 판정부:
    /analyze (track_bystander=true)  -> opens/extends incidents, judges bystanders who talk
    POST /bystander/events           -> read / leave / reaction / defense events from the app
    GET  /bystander/actions          -> 30 s / 60 s nudges, summary, badge, choices to show
"""
import os
import time
from functools import lru_cache

from fastapi import FastAPI

from .schemas import AnalyzeRequest, AnalyzeResponse
from .ensemble import Ensemble
from .check_chat_excel import prosocial_guard
from .bystander_api import router as bystander_router, tracker
from .target_resolver import set_request_context 
from . import models

app = FastAPI(title="WithU Talk AI 추론 서버", version="0.3.0")
app.include_router(bystander_router)
_ensemble: Ensemble | None = None


def _load_classify_bystander():
    """Module D: withu/phase4_bystander.py (must sit next to this app.py)."""
    from .phase4_bystander import classify_bystander, PROVIDER, MODEL
    print(f"[bystander] Module D loaded: {PROVIDER} / {MODEL}")
    return classify_bystander


def build_ensemble() -> Ensemble:
    """Load real modules. Override pieces via env for staged rollout."""
    # cached so /analyze and the bystander window scoring don't run the model twice per message
    message_scorer = lru_cache(maxsize=50_000)(models.load_message_scorer())
    context_scorer = models.load_context_scorer()

    bystander_fn = None
    if os.environ.get("ENABLE_BYSTANDER") == "1":
        classify_bystander = _load_classify_bystander()
        bystander_fn = models.load_bystander_fn(classify_bystander)
        # the 방관 tracker uses the same LLM for bystanders' own messages (방어/동조/무관 대화)
        tracker.set_classifier(lambda ctx, spk, txt: classify_bystander(ctx, spk, txt)[0])
    # without ENABLE_BYSTANDER the tracker falls back to a conservative keyword heuristic

    return Ensemble(
        message_scorer=message_scorer,
        context_scorer=context_scorer,
        exclusion_scorer=models.exclusion_stub,   # Module C stub until live logs exist
        bystander_fn=bystander_fn,
        suspect=float(os.environ.get("SUSPECT_THRESHOLD", 0.75)),
        confirm=float(os.environ.get("CONFIRM_THRESHOLD", 0.85)),
    )


def _window_scores(req: dict) -> list:
    """Per-message score (after prosocial guard) for context + new message -> anchor messages."""
    now = time.time()
    out = []
    for m in req.get("context", []) + [req["new_message"]]:
        raw = float(_ensemble.message_scorer(m.get("text") or ""))
        cb, _, _ = prosocial_guard(m.get("text") or "", raw,
                                   is_defense_action=bool(m.get("is_defense_action", False)))
        out.append({"message_id": m.get("message_id"), "speaker": m["participant_code"],
                    "ts": _ts_or(m.get("timestamp"), now), "cb": cb})
    return out


def _ts_or(v, default):
    from .bystander import _ts
    return _ts(v, default)


@app.on_event("startup")
def _startup():
    global _ensemble
    _ensemble = build_ensemble()
    tracker.start_background(interval=1.0)     # fires the 30 s / 60 s timers


@app.get("/health")
def health():
    return {"status": "ok", "ensemble_ready": _ensemble is not None,
            "bystander_tracker": tracker._thread is not None and tracker._thread.is_alive()}


@app.post("/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest):
    set_request_context(req)
    body = req.model_dump()
    result = _ensemble.analyze(body)
    if req.track_bystander:
        try:
            state = tracker.on_analyze(body, result, _window_scores(body))
        except Exception as e:                   # never break /analyze because of the tracker
            print("[bystander] on_analyze error:", e)
            state = None
        if state:
            result["incident_id"] = state["incident_id"]
            result["bystander_state"] = state
            me = next((b for b in state["bystanders"]
                       if b["participant_code"] == req.new_message.participant_code), None)
            if me and me["behavior"]:
                result["bystander_behavior"] = me["behavior"]
    return AnalyzeResponse(**result)