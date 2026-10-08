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

app = FastAPI(title="WithU Talk AI 추론 서버", version="0.3.3")
_llm = None            # phase4_bystander 모듈 (ENABLE_BYSTANDER=1일 때)
app.include_router(bystander_router)
_ensemble: Ensemble | None = None


def _load_classify_bystander():
    """Module D: withu/phase4_bystander.py (must sit next to this app.py)."""
    global _llm
    from . import phase4_bystander as _llm
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
        # v0.3.3: LLM은 방관 판정부만 부른다 (사건이 열린 방에서 주변인이 말했을 때, 전송 후 호출에서만).
        # 예전에는 cb_score가 0.75 이상이면 전송 전 호출에서도, 가해자의 메시지에도 LLM을 불렀다.
        def _classify(ctx, spk, txt):
            label, why = classify_bystander(ctx, spk, txt)
            return None if str(why).startswith("(error") else label     # None -> 판정부가 키워드 규칙으로 대신 판정
        tracker.set_classifier(_classify)
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
        raw = _ensemble.score_message(m.get("text"))
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
    if _llm is not None:                       # LLM이 실제로 답하는지 한 번 확인 (시작을 막지 않게 따로 돌린다)
        import threading
        threading.Thread(target=_llm.self_check, name="llm-self-check", daemon=True).start()


@app.get("/health")
def health():
    out = {"status": "ok", "version": app.version, "ensemble_ready": _ensemble is not None,
           "bystander_tracker": tracker._thread is not None and tracker._thread.is_alive()}
    # v0.3.3: 모듈 D(LLM) 상태. "ok" | "error"(bystander_llm_error에 이유) | "unknown"(아직 호출 전) | "off"
    if _llm is None:
        out["bystander_llm"] = "off"
    else:
        out["bystander_llm"] = _llm.STATUS["state"]
        if _llm.STATUS["error"]:
            out["bystander_llm_error"] = _llm.STATUS["error"]
    return out


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