"""Load the trained modules and expose them as the callables the Ensemble expects.

torch/transformers are imported lazily inside the loaders so this module (and the
schemas/ensemble) can be imported and unit-tested without a GPU.
"""
import json, os, re, threading, time
from collections import OrderedDict, deque
from concurrent.futures import Future
from pathlib import Path

PHASE1_DIR = Path("./models/stage2_domain_final")   # message toxicity
PHASE2_DIR = Path("./models/phase2_context")         # window context

# v0.3.11: 모델 추론은 한 번에 하나씩 (2026-11-09 사전검사: 한 반이 동시에 보내자 응답이 0.4초 -> 14~17초).
# FastAPI는 /analyze를 여러 스레드에서 동시에 돌리는데, torch는 추론 하나마다 CPU 코어를 전부 쓰려 해서
# 요청 여러 개가 같은 코어를 두고 다투면 모두 느려진다. 잠금으로 줄을 세우면 하나씩 빨리 끝난다.
# WITHU_TORCH_THREADS: 추론 하나가 쓸 스레드 수 (기본: CPU 코어 수). WITHU_INFER_LOCK=0이면 예전처럼 동시에.
INFER_LOCK = threading.Lock() if os.environ.get("WITHU_INFER_LOCK", "1") != "0" else None
INFER_STATS = {"calls": 0, "busy_ms": 0.0, "wait_ms_max": 0, "last_ms": None,   # /health에 보인다
               "items": 0, "queue_max": 0, "shed": 0}

# v0.3.14: 묶음 추론 (2026-11-23 부하테스트: 가상 아이 27명, 대본 초당 5~6줄 -> 1분 만에 응답 없음).
# 요청마다 따로 돌리던 추론을 추론 전용 스레드 하나가 모아서 한 번에 돌린다. 줄이 길어질수록 한 번에 더 많이 처리한다.
#   WITHU_BATCH=0                 예전처럼 하나씩 (v0.3.11 잠금)
#   WITHU_BATCH_MAX (16)          한 번에 돌리는 최대 개수
#   WITHU_QUEUE_DEADLINE_SEC (25) 요청이 도착한 뒤 이 시간이 지나도록 추론을 시작하지 못했으면 돌리지 않고 503.
#                                 앱은 28초에 포기하므로, 아무도 받지 않을 결과를 계산하느라 뒤 요청까지 밀리던 것을 막는다.
#   WITHU_QUANT=int8              모델을 int8로 줄여 CPU 추론을 빠르게 (기본은 끔. bench_infer.py --quant로 점수 차이를 먼저 확인)
BATCH = os.environ.get("WITHU_BATCH", "1") != "0"
BATCH_MAX = max(1, int(os.environ.get("WITHU_BATCH_MAX", 16)))
QUEUE_DEADLINE_SEC = float(os.environ.get("WITHU_QUEUE_DEADLINE_SEC", 25))
QUANT = os.environ.get("WITHU_QUANT", "").strip().lower()


class Overloaded(RuntimeError):
    """요청이 도착한 뒤 QUEUE_DEADLINE_SEC 안에 추론을 시작하지 못함 -> app.py가 503으로 돌려준다."""


_req = threading.local()


def set_deadline(t: float | None):
    """이 스레드에서 처리 중인 요청의 마감 시각 (app.py가 요청 도착 시각 + QUEUE_DEADLINE_SEC로 넣는다)."""
    _req.deadline = t


def _deadline():
    return getattr(_req, "deadline", None)


class InferenceWorker:
    """추론 전용 스레드 하나. 두 모델(A, B)의 요청을 모두 받아 모델별로 묶어 돌린다 (한 번에 한 묶음 -> 코어를 두고 다투지 않음)."""

    def __init__(self, batch_max: int = BATCH_MAX):
        self.batch_max = batch_max
        self.models = {}                       # key -> fwd_batch(list[str]) -> list[float]
        self._q = deque()
        self._cv = threading.Condition()
        self._thread = None

    def register(self, key: str, fwd_batch):
        self.models[key] = fwd_batch
        with self._cv:
            if self._thread is None:
                self._thread = threading.Thread(target=self._loop, name="withu-infer", daemon=True)
                self._thread.start()

    def depth(self) -> int:
        return len(self._q)

    def submit(self, key: str, text: str, deadline=None) -> Future:
        fut = Future()
        with self._cv:
            self._q.append((key, text, deadline, time.time(), fut))
            INFER_STATS["queue_max"] = max(INFER_STATS["queue_max"], len(self._q))
            self._cv.notify()
        return fut

    def _take(self):
        with self._cv:
            while not self._q:
                self._cv.wait()
            jobs = []
            while self._q and len(jobs) < self.batch_max:
                jobs.append(self._q.popleft())
            return jobs

    def _loop(self):
        while True:
            jobs = self._take()
            now = time.time()
            live = []
            for j in jobs:
                if j[2] is not None and now > j[2]:            # 마감이 지난 요청: 돌리지 않는다
                    INFER_STATS["shed"] += 1
                    j[4].set_exception(Overloaded("queue deadline passed"))
                else:
                    INFER_STATS["wait_ms_max"] = max(INFER_STATS["wait_ms_max"], int((now - j[3]) * 1000))
                    live.append(j)
            by_model = {}
            for j in live:
                by_model.setdefault(j[0], []).append(j)
            for key, group in by_model.items():
                self._run_group(key, group)

    def _run_group(self, key, group):
        fwd = self.models[key]
        texts = [j[1] for j in group]
        t0 = time.time()
        try:
            outs = fwd(texts)
            if len(outs) != len(texts):
                raise RuntimeError(f"fwd_batch returned {len(outs)} for {len(texts)}")
        except Exception as e:                 # 묶음이 실패하면 하나씩 다시 (한 메시지 때문에 다른 요청이 깨지지 않게)
            if len(group) > 1:
                print(f"[infer] batch of {len(group)} failed ({e}); retrying one by one", flush=True)
                for j in group:
                    self._run_group(key, [j])
            else:
                group[0][4].set_exception(e)
            return
        ms = (time.time() - t0) * 1000
        INFER_STATS["calls"] += 1
        INFER_STATS["items"] += len(group)
        INFER_STATS["busy_ms"] += ms
        INFER_STATS["last_ms"] = int(ms)
        for j, v in zip(group, outs):
            j[4].set_result(float(v))


WORKER = InferenceWorker()


class CachedScorer:
    """text -> 점수. 같은 글은 한 번만 돌린다 (전송 전·후 호출, 문맥 창의 지난 메시지).
    many(texts): 아직 점수가 없는 글을 한꺼번에 넣고 기다린다 (방의 첫 요청처럼 문맥이 처음 오는 경우)."""

    def __init__(self, key: str, fwd_batch, maxsize: int = 50_000):
        self.key, self.fwd_batch, self.maxsize = key, fwd_batch, maxsize
        self._cache = OrderedDict()
        self._inflight = {}
        self._lock = threading.Lock()
        if BATCH:
            WORKER.register(key, fwd_batch)

    def _get(self, text):
        with self._lock:
            if text in self._cache:
                self._cache.move_to_end(text)
                return True, self._cache[text]
        return False, None

    def _put(self, text, v):
        with self._lock:
            self._cache[text] = v
            self._cache.move_to_end(text)
            while len(self._cache) > self.maxsize:
                self._cache.popitem(last=False)

    def _start(self, text):
        """-> Future (이미 같은 글이 도는 중이면 그것)."""
        with self._lock:
            fut = self._inflight.get(text)
            if fut is not None:
                return fut
            fut = WORKER.submit(self.key, text, _deadline()) if BATCH else Future()
            self._inflight[text] = fut
        if not BATCH:                          # v0.3.11 방식: 잠금 안에서 바로 돌린다
            try:
                fut.set_result(float(_run(lambda: self.fwd_batch([text])[0])))
            except Exception as e:
                fut.set_exception(e)
        fut.add_done_callback(lambda f, t=text: self._done(t, f))
        return fut

    def _done(self, text, fut):
        with self._lock:
            if self._inflight.get(text) is fut:
                self._inflight.pop(text, None)
        if not fut.cancelled() and fut.exception() is None:
            self._put(text, fut.result())

    def __call__(self, text):
        hit, v = self._get(text)
        if hit:
            return v
        return self._start(text).result()

    def many(self, texts):
        futs = {}
        for t in texts:
            if t in futs:
                continue
            hit, _ = self._get(t)
            if not hit:
                futs[t] = self._start(t)
        for f in futs.values():
            f.result()                         # Overloaded 등은 그대로 올라간다


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
    tok, mdl, dev = _load(torch, model_dir)

    @torch.inference_mode()
    def fwd_batch(texts):
        enc = tok([t or "" for t in texts], return_tensors="pt", truncation=True, max_length=128,
                  padding=True).to(dev)
        return torch.softmax(mdl(**enc).logits, dim=-1)[:, 1].tolist()

    return CachedScorer("message", fwd_batch)


def _load(torch, model_dir):
    from transformers import AutoTokenizer, AutoModelForSequenceClassification
    tok = AutoTokenizer.from_pretrained(str(model_dir))
    mdl = AutoModelForSequenceClassification.from_pretrained(str(model_dir))
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    mdl = mdl.to(dev).eval()
    if QUANT == "int8" and dev == "cpu":       # v0.3.14: 선택. Linear 층만 int8 (정답 코퍼스로 점수 차이를 확인한 뒤 켠다)
        mdl = torch.ao.quantization.quantize_dynamic(mdl, {torch.nn.Linear}, dtype=torch.qint8)
        print(f"[models] {model_dir}: int8 dynamic quantization ON", flush=True)
    _set_threads(torch)
    return tok, mdl, dev


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
    tok, mdl, dev = _load(torch, model_dir)

    @torch.inference_mode()
    def fwd_batch(texts):
        enc = tok(list(texts), return_tensors="pt", truncation=True, max_length=256, padding=True).to(dev)
        return torch.softmax(mdl(**enc).logits, dim=-1)[:, 1].tolist()

    # v0.3.11: 전송 전·전송 후 호출은 같은 창을 보낸다 -> 같은 창은 한 번만 돌린다
    cached = CachedScorer("context", fwd_batch, maxsize=20_000)

    def score(window_texts, speakers=None) -> float:
        # v0.3.3: 학습 때와 같이 발화자를 A/B/C로 구분해 넘긴다 (예전에는 모두 "A:"로 들어갔다)
        return cached(_render_window(window_texts, speakers))
    score.fwd_batch = fwd_batch                # bench_infer.py용
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
