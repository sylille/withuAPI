# -*- coding: utf-8 -*-
"""v0.3.14 묶음 추론 오프라인 테스트 (모델·torch 없이). python test_batching.py

- 여러 스레드가 동시에 부르면 한 번에 묶여 돌고, 점수는 하나씩 부를 때와 같다
- 같은 글은 한 번만 돌린다 (캐시, 동시에 들어온 같은 글)
- many(): 아직 없는 글만 한꺼번에
- 묶음이 실패하면 하나씩 다시 -> 문제 있는 글 하나만 실패
- 마감이 지난 요청은 돌리지 않고 Overloaded
"""
import os, sys, threading, time
os.environ["WITHU_BATCH"] = "1"
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import models
from withu.models import CachedScorer, Overloaded, set_deadline

fails = []


def check(name, ok, info=""):
    print(("[PASS] " if ok else "[FAIL] ") + name + ("" if ok else f"   {info}"))
    if not ok:
        fails.append(name)


calls = []
gate = threading.Event()


def fwd(texts):
    calls.append(list(texts))
    gate.wait(2)                               # 첫 묶음이 도는 동안 나머지가 줄을 서게
    if any(t == "BAD" for t in texts):
        raise ValueError("bad text")
    return [len(t) / 100 for t in texts]


s = CachedScorer("t1", fwd)
out = {}
ths = [threading.Thread(target=lambda i=i: out.__setitem__(i, s(f"글{i:02d}"))) for i in range(20)]
for t in ths:
    t.start()
time.sleep(0.3)
gate.set()
for t in ths:
    t.join()
check("동시에 20개 -> 점수는 하나씩과 같음", all(abs(out[i] - len(f"글{i:02d}") / 100) < 1e-12 for i in range(20)), out)
check("묶여서 돌았다 (호출 수 < 20)", len(calls) < 20 and max(len(c) for c in calls) > 1, [len(c) for c in calls])
check("묶음 크기는 WITHU_BATCH_MAX 이하", max(len(c) for c in calls) <= models.BATCH_MAX, [len(c) for c in calls])

n = len(calls)
check("캐시: 같은 글은 다시 돌리지 않는다", s("글03") == out[3] and len(calls) == n)

calls.clear(); gate.clear()
res = []
ths = [threading.Thread(target=lambda: res.append(s("같은글"))) for _ in range(10)]
for t in ths:
    t.start()
time.sleep(0.2); gate.set()
for t in ths:
    t.join()
check("동시에 들어온 같은 글 10개 -> 한 번만", sum(c.count("같은글") for c in calls) == 1 and len(set(res)) == 1, calls)

calls.clear(); gate.set()
s.many(["글01", "새글1", "새글2", "새글1"])
check("many(): 없는 글만, 한꺼번에", calls == [["새글1", "새글2"]], calls)

calls.clear(); gate.clear()
got, errs = {}, {}
def run(t):
    try:
        got[t] = s(t)
    except Exception as e:
        errs[t] = e
ths = [threading.Thread(target=run, args=(t,)) for t in ("가가", "BAD", "나나나")]
for t in ths:
    t.start()
time.sleep(0.2); gate.set()
for t in ths:
    t.join()
check("묶음 실패 -> 하나씩 다시: 문제 글만 실패", set(got) == {"가가", "나나나"} and set(errs) == {"BAD"}, (got, errs))
check("실패한 글은 캐시에 남지 않는다", "BAD" not in s._cache)

# 마감
slow = threading.Event()
def fwd_slow(texts):
    slow.wait(3)
    return [0.1] * len(texts)
s2 = CachedScorer("t2", fwd_slow)
first = threading.Thread(target=lambda: s2("먼저"))       # 추론 스레드를 붙잡아 둔다
first.start(); time.sleep(0.2)
r = {}
def late():
    set_deadline(time.time() + 0.3)
    try:
        r["v"] = s2("늦은 글")
    except Overloaded:
        r["v"] = "overloaded"
    finally:
        set_deadline(None)
lt = threading.Thread(target=late); lt.start()
time.sleep(0.6); slow.set()
first.join(); lt.join()
check("마감이 지난 요청은 돌리지 않고 Overloaded", r.get("v") == "overloaded", r)
check("Overloaded는 캐시에 남지 않고 다음엔 다시 돈다", s2("늦은 글") == 0.1)
check("shed 횟수가 /health 통계에 잡힌다", models.INFER_STATS["shed"] >= 1, models.INFER_STATS)

print("\n" + ("ALL PASS" if not fails else f"{len(fails)} FAILED"))
sys.exit(1 if fails else 0)
