"""Load the trained modules and expose them as the callables the Ensemble expects.

torch/transformers are imported lazily inside the loaders so this module (and the
schemas/ensemble) can be imported and unit-tested without a GPU.
"""
import json, os, re, threading, time
from pathlib import Path
from functools import lru_cache

PHASE1_DIR = Path("./models/stage2_domain_final")   # message toxicity
PHASE2_DIR = Path("./models/phase2_context")         # window context

# v0.3.11: 모델 추론은 한 번에 하나씩 (2026-11-09 사전검사: 한 반이 동시에 보내자 응답이 0.4초 -> 14~17초).
# FastAPI는 /analyze를 여러 스레드에서 동시에 돌리는데, torch는 추론 하나마다 CPU 코어를 전부 쓰려 해서
# 요청 여러 개가 같은 코어를 두고 다투면 모두 느려진다. 잠금으로 줄을 세우면 하나씩 빨리 끝난다.
# WITHU_TORCH_THREADS: 추론 하나가 쓸 스레드 수 (기본: CPU 코어 수). WITHU_INFER_LOCK=0이면 예전처럼 동시에.
INFER_LOCK = threading.Lock() if os.environ.get("WITHU_INFER_LOCK", "1") != "0" else None
INFER_STATS = {"calls": 0, "busy_ms": 0.0, "wait_ms_max": 0, "last_ms": None}   # /health에 보인다


def _set_threads(torch):
    n = os.environ.get("WITHU_TORCH_THREADS")
    n = int(n) if n else (os.cpu_count() or 1)
    if torch.get_num_threads() != n:
        torch.set_num_threads(n)


def _run(fn):
    """잠금 안에서 fn()을 돌리고 시간을 STATS에 남긴다."""
    t0 = time.time()
    if INFER_LOCK is None:
        out = fn()
        t1 = t0
    else:
        with INFER_LOCK:
            t1 = time.time()
            out = fn()
    t2 = time.time()
    INFER_STATS["calls"] += 1
    INFER_STATS["busy_ms"] += (t2 - t1) * 1000
    INFER_STATS["last_ms"] = int((t2 - t1) * 1000)
    INFER_STATS["wait_ms_max"] = max(INFER_STATS["wait_ms_max"], int((t1 - t0) * 1000))
    return out


# ---------- Phase 1: message toxicity scorer ----------
def load_message_scorer(model_dir=PHASE1_DIR):
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tok = AutoTokenizer.from_pretrained(str(model_dir))
    mdl = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    mdl = mdl.to(dev).eval()
    _set_threads(torch)

    @torch.inference_mode()
    def _fwd(text):
        enc = tok(text or "", return_tensors="pt", truncation=True, max_length=128).to(dev)
        return float(torch.softmax(mdl(**enc).logits, dim=-1)[0, 1])

    def score(text: str) -> float:
        return _run(lambda: _fwd(text))
    return score


# ---------- Phase 2: window context scorer ----------
def _render_window(texts, speakers=None):
    if speakers is None:
        speakers = ["?"] * len(texts)
    seen, letters, parts = {}, "ABCDEFGH", []
    for s, t in zip(speakers, texts):
        s = str(s)
        if s not in seen: seen[s] = letters[len(seen) % len(letters)]
        parts.append(f"{seen[s]}: {t}")
    return " [TURN] ".join(parts)

def load_context_scorer(model_dir=PHASE2_DIR):
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tok = AutoTokenizer.from_pretrained(str(model_dir))
    mdl = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    mdl = mdl.to(dev).eval()
    _set_threads(torch)

    @torch.inference_mode()
    def _fwd(text):
        enc = tok(text, return_tensors="pt", truncation=True, max_length=256).to(dev)
        return float(torch.softmax(mdl(**enc).logits, dim=-1)[0, 1])

    # v0.3.11: 전송 전·전송 후 호출은 같은 창을 보낸다 -> 같은 창은 한 번만 돌린다
    @lru_cache(maxsize=20_000)
    def _cached(text):
        return _run(lambda: _fwd(text))

    def score(window_texts, speakers=None) -> float:
        # v0.3.3: 학습 때와 같이 발화자를 A/B/C로 구분해 넘긴다 (예전에는 모두 "A:"로 들어갔다)
        return _cached(_render_window(window_texts, speakers))
    return score


# ---------- Phase 4: bystander (LLM few-shot) ----------
def load_bystander_fn(classify_bystander):
    """Wrap your Phase-4 classify_bystander(context, speaker, text) into the ensemble contract."""
    def fn(context, speaker, text, logs=None):
        # 방관 log rule first (if metadata present)
        if logs:
            from_logs = logs.get("bystanding")
            if from_logs:
                return {"behavior": "방관", "reason": "log rule", "source": "logs"}
        lab, why = classify_bystander(context, speaker, text)
        return {"behavior": lab, "reason": why, "source": "llm"}
    return fn


# ---------- Phase 3: exclusion (배제) — STUB ----------
def exclusion_stub(logs: dict) -> float:
    """Placeholder for Module C. Wire this to real social-network / participation metrics
    from the live messenger (isolation index, response-rate asymmetry, read-no-response).
    Until then it can read a precomputed score if the app supplies one, else returns 0.
    """
    if not logs:
        return 0.0
    return float(logs.get("exclusion_score", 0.0))
