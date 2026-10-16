# -*- coding: utf-8 -*-
"""
v0.3.7 확인: 전송 전 호출(track_bystander=false)에서 주변인 메시지의 판정을 미리 돌려준다. 모델 없이 실행된다.

    cd <withu 폴더를 담고 있는 폴더> && python test_preview.py

LLM은 가짜 함수로 대신한다 (지연 시간도 흉내 낸다). 실제 LLM 응답 시간은 실서버에서 확인해야 한다.
"""
import os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import bystander as B
from withu.bystander import BystanderTracker

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


AGREE = ("ㅋㅋ", "ㅇㅈ", "인정", "맞아", "냄새남")


class FakeLLM:
    """동조 표현이면 동조, '그만'이면 방어, 아니면 방관. delay초 기다린다. 부른 횟수를 센다."""
    def __init__(self, delay=0.0):
        self.delay, self.calls = delay, 0
        self.lock = threading.Lock()

    def __call__(self, ctx, spk, txt):
        with self.lock:
            self.calls += 1
        time.sleep(self.delay)
        if "그만" in txt: return "방어"
        if any(a in txt for a in AGREE): return "동조"
        return "방관"


CTX = [{"participant_code": "A", "text": "하늘 너 진짜 냄새나 꺼져", "message_id": "m1"},
       {"participant_code": "V", "text": "왜 그래...", "message_id": "m2"},
       {"participant_code": "A", "text": "냄새나니까 나가라", "message_id": "m3"}]


def opened(llm, room="r1"):
    tr = BystanderTracker(classify=llm)
    t = time.time()
    for k, m in enumerate([CTX[0], CTX[2]]):
        tr.on_analyze({"room_id": room, "new_message": dict(m, timestamp=t), "context": []},
                      {"attribution": {"is_bullying": True, "aggressors": ["A"], "victim": "V", "victim_reason": "name_mention"}},
                      [{"message_id": m["message_id"], "speaker": "A", "ts": t, "cb": 0.9}])
    return tr


def pre(tr, who, text, room="r1", ctx=CTX, timeout=None, **kw):
    return tr.preview({"room_id": room, "context": ctx,
                       "new_message": dict({"participant_code": who, "text": text}, **kw)}, timeout=timeout)


def post(tr, who, text, mid, room="r1", ctx=CTX):
    t = time.time()
    return tr.on_analyze({"room_id": room, "context": ctx,
                          "new_message": {"participant_code": who, "text": text, "message_id": mid, "timestamp": t}},
                         {"attribution": {"is_bullying": False}},
                         [{"message_id": mid, "speaker": who, "ts": t, "cb": 0.1}])


def behavior(tr, who, room="r1"):
    st = tr.state(room, who)
    return st["bystanders"][0]["behavior"] if st and st["bystanders"] else None


# ---------------------------------------------------------------------------------------- 1. 앱팀이 보고한 세 메시지
print("1) 사건이 열린 방에서 주변인의 동조 메시지 -> 전송 전 호출에서 '동조'")
llm = FakeLLM()
tr = opened(llm)
for i, txt in enumerate(["ㅋㅋㅋㅋ 인정", "ㅇㅈ", "맞아 하늘 냄새남 ㅋㅋ"]):
    p = pre(tr, f"B{i}", txt)
    check(f"'{txt}' -> 동조 (LLM)", p and p["label"] == "동조" and p["source"] == "LLM", str(p))
p = pre(tr, "B9", "그만해 너무 심하잖아")
check("'그만해 너무 심하잖아' -> 방어", p and p["label"] == "방어", str(p))

# ---------------------------------------------------------------------------------------- 2. 기록하지 않는다
print("\n2) 전송 전 호출은 아무것도 기록하지 않음")
st = tr.state("r1")
check("미리 판정한 아이들이 주변인 목록에 생기지 않음", st["bystanders"] == [], str([b["participant_code"] for b in st["bystanders"]]))
tr2 = opened(FakeLLM())
tr2.drain("r1")
pre(tr2, "B1", "ㅇㅈ")
check("미리 판정 뒤 대기 알림 0개", tr2.drain("r1") == [])

# ---------------------------------------------------------------------------------------- 3. 판정 대상이 아닌 경우
print("\n3) 판정 대상이 아니면 null")
check("사건이 없는 방 -> None", pre(tr, "B1", "ㅇㅈ", room="none") is None)
check("가해자의 메시지 -> None (가해자는 cb_score 경고)", pre(tr, "A", "ㅋㅋㅋ") is None)
check("피해자의 메시지 -> None", pre(tr, "V", "ㅋㅋ 그만") is None)
check("본문 없는 메시지(이미지) -> None", pre(tr, "B1", "") is None)
p = pre(tr, "B1", "괜찮아?", is_defense_action=True)
check("방어 기능 메시지 -> 방어 (LLM 안 부름)", p and p["label"] == "방어" and p["source"] == "방어 기능", str(p))

# ---------------------------------------------------------------------------------------- 4. 그래도 보내면 기록, LLM은 한 번만
print("\n4) 그래도 보내면 전송 후 호출이 같은 판정으로 기록 (LLM은 메시지당 한 번)")
llm = FakeLLM(delay=0.3)
tr = opened(llm)
p = pre(tr, "B1", "ㅋㅋㅋㅋ 인정")
n_after_pre = llm.calls
t0 = time.time(); post(tr, "B1", "ㅋㅋㅋㅋ 인정", "m4"); dt = time.time() - t0
check("전송 전 '동조'", p["label"] == "동조")
check("전송 후 기록도 '동조'", behavior(tr, "B1") == "동조", str(tr.state("r1", "B1")))
check("전송 후 호출은 LLM을 다시 부르지 않음", llm.calls == n_after_pre == 1, f"calls={llm.calls}")
check("전송 후 호출이 LLM을 기다리지 않아 빠름", dt < 0.1, f"{dt:.2f}s")
check("join_feedback 알림은 전송 후에만", any(a["action"] == "join_feedback" for a in tr.drain("r1")))

print("\n   보내지 않고 취소한 경우")
tr = opened(FakeLLM())
pre(tr, "B2", "ㅇㅈ")
check("취소하면(전송 후 호출 없음) 기록 없음", behavior(tr, "B2") is None)

print("\n   맥락이 달라지면 다시 판정")
llm = FakeLLM(); tr = opened(llm)
pre(tr, "B3", "ㅇㅈ")
post(tr, "B3", "ㅇㅈ", "m5", ctx=CTX + [{"participant_code": "C", "text": "뭐야", "message_id": "m4"}])
check("맥락이 다르면 전송 후 호출이 새로 판정 (calls=2)", llm.calls == 2 and behavior(tr, "B3") == "동조", f"calls={llm.calls}")

# ---------------------------------------------------------------------------------------- 5. 시간 예산
print("\n5) LLM이 느리면 시간 예산 안에 규칙으로 답하고, 전송 후 호출은 LLM 결과를 씀")
llm = FakeLLM(delay=1.0)
tr = opened(llm)
t0 = time.time(); p = pre(tr, "B4", "ㅋㅋㅋㅋ 인정", timeout=0.3); dt = time.time() - t0
check("0.3초 예산 -> 0.3초 남짓에 응답", dt < 0.45, f"{dt:.2f}s")
check("규칙 판정: 가해자 바로 뒤 'ㅋㅋㅋㅋ 인정' -> 동조", p["label"] == "동조" and p["source"] == "규칙(시간 초과)", str(p))
t0 = time.time(); post(tr, "B4", "ㅋㅋㅋㅋ 인정", "m6"); dt = time.time() - t0
check("전송 후 호출은 돌던 LLM을 기다려 그 결과로 기록 (LLM 한 번)", llm.calls == 1 and behavior(tr, "B4") == "동조"
      and any("LLM" in h["event"] for h in tr.state("r1", "B4")["bystanders"][0]["history"]), f"calls={llm.calls}")
check("남은 시간만 기다림 (<1초)", dt < 0.95, f"{dt:.2f}s")

print("\n   LLM이 없거나 실패하면 규칙")
tr = opened(None)
p = pre(tr, "B5", "ㅇㅈ")
check("LLM 없음 -> 규칙으로 즉시 동조", p["label"] == "동조" and p["source"] == "규칙", str(p))
tr = opened(lambda c, s, t: None)
p = pre(tr, "B5", "맞아 하늘 냄새남 ㅋㅋ")
check("LLM 실패(None) -> 규칙으로 동조", p["label"] == "동조" and p["source"] == "규칙", str(p))

# ---------------------------------------------------------------------------------------- 6. 잠금
print("\n6) 미리 판정 중에도 다른 방 요청이 막히지 않음")
tr = opened(FakeLLM(delay=1.0))
th = threading.Thread(target=lambda: pre(tr, "B6", "ㅇㅈ", timeout=2.0)); th.start(); time.sleep(0.1)
t0 = time.time(); tr.drain("other"); tr.tick(); waited = time.time() - t0
th.join()
check("LLM 대기 중 /bystander/actions·타이머 즉시 응답", waited < 0.1, f"{waited:.2f}s")

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
