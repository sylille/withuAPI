# -*- coding: utf-8 -*-
"""
v0.3.8 확인: 앱팀 사후검사 보고(2026-10-28) — 가해자를 반박한 말이 '동조'로, 중립적인 말이 preview에서 '동조'로 나온 건.

    python test_report4.py            # 모델·LLM 없이: LLM에 무엇이 넘어가는지, 근거가 남는지, 동조 보정이 도는지
    python test_report4.py --live 5   # 실서버에서: 실제 LLM으로 케이스마다 5번씩 판정해 분포를 본다 (API 키 필요)

대사는 앱팀 보고에 인용된 줄과, 같은 짜임으로 새로 쓴 가상의 줄이다.
"""
import os, sys, threading, time
from collections import Counter
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.phase4_bystander import parse_label

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


class Capture:
    """LLM 대신: 넘겨받은 인자를 적어 두고 정해 둔 답을 돌려준다."""
    def __init__(self, answer=("비해당", "가짜")):
        self.answer, self.calls = answer, []
        self.lock = threading.Lock()

    def __call__(self, ctx, spk, txt, reply=None):
        with self.lock:
            self.calls.append({"ctx": ctx, "spk": spk, "txt": txt, "reply": reply})
        return self.answer


def room(classify, aggr, victim, parts, ctx, rid="r"):
    """사건이 열린 방. parts: {코드: 닉네임}. ctx: [(코드, 본문, message_id)]"""
    T.ROSTERS.clear()
    tr = BystanderTracker(classify=classify)
    plist = [{"participant_code": c, "display_name": n} for c, n in parts.items()]
    T.ROSTERS.update(rid, plist)
    t = time.time()
    msgs = [{"participant_code": c, "text": x, "message_id": m, "timestamp": t} for c, x, m in ctx]
    first = next(m for m in msgs if m["participant_code"] == aggr)
    tr.on_analyze({"room_id": rid, "new_message": first, "context": [], "participants": plist},
                  {"attribution": {"is_bullying": True, "aggressors": [aggr], "victim": victim, "victim_reason": "name_mention"}},
                  [{"message_id": first["message_id"], "speaker": aggr, "ts": t, "cb": 0.9}])
    return tr, msgs, plist


def send(tr, msgs, plist, who, text, mid, reply_to=None, rid="r", preview=False):
    new = {"participant_code": who, "text": text, "message_id": mid, "timestamp": time.time(),
           "reply_to_message_id": reply_to}
    body = {"room_id": rid, "context": msgs, "new_message": new, "participants": plist}
    if preview:
        return tr.preview(body, timeout=2.0)
    tr.on_analyze(body, {"attribution": {"is_bullying": False}},
                  [{"message_id": mid, "speaker": who, "ts": new["timestamp"], "cb": 0.1}])
    return tr.state(rid, who)


# ---------------------------------------------------------------- 사후검사 1: 가해자에게 단 답장
PARTS1 = {"P01": "태민", "P02": "건우", "P03": "현우", "P04": "서아"}
CTX1 = [("P01", "건우 너 진짜 왜 그러냐", "a1"), ("P02", "내가 뭘", "a2"),
        ("P01", "아 또 예민하게 받아들이네", "a3"), ("P02", "그만해", "a4")]
# ---------------------------------------------------------------- 사후검사 3: 가해자 이름을 든 말
PARTS3 = {"P11": "유진", "P12": "소희", "P13": "지호"}
CTX3 = [("P11", "소희 이 사진 봐 ㅋㅋ", "b1"), ("P12", "올리지 마", "b2"), ("P13", "사진 지워줘", "b3")]
# ---------------------------------------------------------------- 사후검사 4: 화제를 돌린 뒤의 짧은 말
CTX4 = [("P11", "소희 진짜 이상해 ㅋㅋ", "c1"), ("P12", "ㅠㅠ", "c2"),
        ("P13", "속상한 사람 있을 듯. 그만하고 딴 얘기 하자", "c3")]

if "--live" not in sys.argv:
    print("1) 답장이면 답장 대상과 그 화자의 역할이 LLM에 넘어간다")
    cap = Capture()
    tr, msgs, pl = room(cap, "P01", "P02", PARTS1, CTX1)
    send(tr, msgs, pl, "P04", "니가 잘못한거잖아", "a5", reply_to="a3", preview=True)
    c = cap.calls[-1]
    check("reply = 태민(가해자)의 '아 또 예민하게 받아들이네'", c["reply"] == ("P01(가해자)", "아 또 예민하게 받아들이네"), str(c["reply"]))
    check("맥락의 이름도 코드(역할)로: '건우 너…' -> 'P02(피해자) 너…'",
          ("P01(가해자)", "P02(피해자) 너 진짜 왜 그러냐") in c["ctx"], str(c["ctx"][:1]))
    cap2 = Capture()
    tr2, msgs2, pl2 = room(cap2, "P01", "P02", PARTS1, CTX1)
    send(tr2, msgs2, pl2, "P04", "니가 잘못한거잖아", "a5", preview=True)
    check("답장이 아니면 reply 없음 (예전과 같은 입력)", cap2.calls[-1]["reply"] is None)
    check("답장 여부가 다르면 다른 판정으로 친다 (캐시 키가 다름)", len(cap.calls) == 1 and len(cap2.calls) == 1)

    print("\n2) 본문 속 아이 이름 -> 코드(역할), 조사는 남긴다")
    cap = Capture()
    tr, msgs, pl = room(cap, "P11", "P12", PARTS3, CTX3)
    send(tr, msgs, pl, "P13", "유진이 이상함", "b4", preview=True)
    check("'유진이 이상함' -> 'P11(가해자)이 이상함'", cap.calls[-1]["txt"] == "P11(가해자)이 이상함", cap.calls[-1]["txt"])
    send(tr, msgs, pl, "P13", "소희한테 사과해", "b5", preview=True)
    check("'소희한테 사과해' -> 'P12(피해자)한테 사과해'", cap.calls[-1]["txt"] == "P12(피해자)한테 사과해", cap.calls[-1]["txt"])
    send(tr, msgs, pl, "P13", "유진아 소희 그만 놀려", "b6", preview=True)
    check("이름 두 개 -> 둘 다 바뀜", cap.calls[-1]["txt"] == "P11(가해자)아 P12(피해자) 그만 놀려", cap.calls[-1]["txt"])
    check("아이 이름이 LLM으로 나가지 않음", not any(n in str(cap.calls) for n in PARTS3.values()))

    print("\n3) LLM이 가해자를 비판한 말에 '동조'를 붙이면 고친다 (4장 표3)")
    lab, why = parse_label('{"target":"가해자","stance":"비판","label":"동조","reason":"이상하다고 함"}')
    check("가해자/비판 + 동조 -> 방어", lab == "방어", why)
    lab, _ = parse_label('{"target":"없음","stance":"중립","label":"동조","reason":"x"}')
    check("대상 없음/중립 + 동조 -> 비해당", lab == "비해당")
    lab, _ = parse_label('{"target":"피해자","stance":"조롱","label":"동조","reason":"x"}')
    check("피해자/조롱 + 동조 -> 동조 그대로", lab == "동조")
    lab, _ = parse_label('{"target":"가해자","stance":"지지","label":"동조","reason":"x"}')
    check("가해자/지지 + 동조 -> 동조 그대로 ('그만해 ㅋㅋ 근데 웃기긴 하다')", lab == "동조")
    lab, _ = parse_label('{"label":"방어","reason":"x"}')
    check("target/stance 없는 예전 형식도 읽음", lab == "방어")

    print("\n3-1) 연구진 기준(10-29): 가해자에 대한 공개적 반대는 방어, 가해자에게 욕설은 방어 아님")
    for t in ("P11(가해자) 이상해", "P11(가해자) 그만해", "P11(가해자)이 뭐라는거야"):
        lab, why = parse_label('{"target":"가해자","stance":"비판","label":"방어","reason":"x"}', t)
        check(f"'{t}' 가해자/비판 -> 방어", lab == "방어", why)
    lab, why = parse_label('{"target":"가해자","stance":"조롱","label":"동조","reason":"x"}', "P11(가해자)이 뭐라는거야")
    check("가해자/조롱으로 와도 동조 아님 -> 방어", lab == "방어", why)
    for t in ("P11(가해자) 닥쳐 병신아", "그만해 이 새끼야", "P11(가해자) ㅅㅂ 그만하라고"):
        lab, why = parse_label('{"target":"가해자","stance":"비판","label":"방어","reason":"x"}', t)
        check(f"'{t}' LLM이 방어라 해도 욕설 -> 비해당", lab == "비해당", why)
    lab, why = parse_label('{"target":"가해자","stance":"욕설","label":"방어","reason":"x"}', "P11(가해자) 진짜 ㄲㅈ")
    check("stance=욕설 -> 비해당", lab == "비해당", why)
    lab, why = parse_label('{"target":"가해자","stance":"비판","label":"방어","reason":"x"}', "\'병신\'이라고 하지 마")
    check("욕을 옮겨 나무라는 말(\'병신\'이라고 하지 마) -> 방어 그대로", lab == "방어", why)

    print("\n4) 판정 근거가 남는다")
    cap = Capture(answer=("동조", "[피해자/조롱] 피해자를 비웃음"))
    tr, msgs, pl = room(cap, "P11", "P12", PARTS3, CTX4)
    p = send(tr, msgs, pl, "P13", "흠좀무", "c4", preview=True)
    check("preview 응답에 reason", p and p.get("reason") == "[피해자/조롱] 피해자를 비웃음", str(p))
    st = send(tr, msgs, pl, "P13", "흠좀무", "c4")
    hist = [h["event"] for h in st["bystanders"][0]["history"]]
    check("history: '동조: 발화(LLM)' 다음 줄에 '판정 근거: …'",
          "동조: 발화(LLM)" in hist and hist[hist.index("동조: 발화(LLM)") + 1].startswith("판정 근거: [피해자/조롱]"), str(hist))
    check("preview와 record가 같은 판정을 씀 (LLM 한 번)", len(cap.calls) == 1, f"calls={len(cap.calls)}")

    print("\n5) 시간 초과면 근거에 그렇게 적는다")
    slow = lambda *a, **k: (time.sleep(0.5), ("방어", "x"))[1]
    tr, msgs, pl = room(slow, "P11", "P12", PARTS3, CTX4)
    p = tr.preview({"room_id": "r", "context": msgs, "participants": pl,
                    "new_message": {"participant_code": "P13", "text": "흠좀무"}}, timeout=0.1)
    check("source=규칙(시간 초과), reason에 시간 초과", p["source"] == "규칙(시간 초과)" and "0.1초" in p["reason"], str(p))
    check("'흠좀무'는 규칙으로 비해당", p["label"] == "비해당", str(p))

    print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)

# ---------------------------------------------------------------- 실서버: 실제 LLM
from withu.phase4_bystander import classify_bystander, PROVIDER, MODEL
n = int(sys.argv[sys.argv.index("--live") + 1]) if len(sys.argv) > sys.argv.index("--live") + 1 else 5
CASES = [  # (설명, 방, 가해자, 피해자, 명단, 맥락, 말한 아이, 본문, 답장 대상, 기대)
    ("사후검사1 '니가 잘못한거잖아' (태민에게 답장)", "P01", "P02", PARTS1, CTX1, "P04", "니가 잘못한거잖아", "a3", {"방어"}),
    ("사후검사1 '태민아 그만해'", "P01", "P02", PARTS1, CTX1, "P04", "태민아 그만해", None, {"방어"}),
    ("사후검사3 '유진이 이상함'", "P11", "P12", PARTS3, CTX3, "P13", "유진이 이상함", None, {"방어"}),
    ("기준 '유진 이상해'", "P11", "P12", PARTS3, CTX3, "P13", "유진 이상해", None, {"방어"}),
    ("기준 '유진 그만해'", "P11", "P12", PARTS3, CTX3, "P13", "유진 그만해", None, {"방어"}),
    ("기준 '유진이 뭐라는거야'", "P11", "P12", PARTS3, CTX3, "P13", "유진이 뭐라는거야", None, {"방어"}),
    ("기준 '유진 닥쳐 병신아' (욕설)", "P11", "P12", PARTS3, CTX3, "P13", "유진 닥쳐 병신아", None, {"비해당"}),
    ("사후검사3 '사진 지워줘'", "P11", "P12", PARTS3, CTX3[:2], "P13", "사진 지워줘", None, {"방어"}),
    ("사후검사4 '흠좀무'", "P11", "P12", PARTS3, CTX4, "P13", "흠좀무", None, {"비해당", "방관"}),
    ("사후검사4 '흠 좀 무섭군'", "P11", "P12", PARTS3, CTX4, "P13", "흠 좀 무섭군", None, {"비해당", "방관", "방어"}),
    ("사후검사4 '배고프다'", "P11", "P12", PARTS3, CTX4, "P13", "배고프다", None, {"방관", "비해당"}),
    ("사후검사4 'ㅇㅋ'", "P11", "P12", PARTS3, CTX4, "P13", "ㅇㅋ", None, {"비해당", "방관"}),
    ("사후검사4 '소희 불쌍해'", "P11", "P12", PARTS3, CTX4, "P13", "소희 불쌍해", None, {"방어"}),
    ("사후검사4 '소희 그만 놀려'", "P11", "P12", PARTS3, CTX4, "P13", "소희 그만 놀려", None, {"방어"}),
    ("대조: 피해자에게 단 '니가 잘못한거잖아'", "P01", "P02", PARTS1, CTX1, "P04", "니가 잘못한거잖아", "a4", {"동조"}),
    ("대조: 가해자 뒤 'ㅋㅋㅋ 인정'", "P01", "P02", PARTS1, CTX1[:3], "P04", "ㅋㅋㅋ 인정", None, {"동조"}),
]
print(f"provider={PROVIDER} model={MODEL}  케이스마다 {n}번\n")
bad = 0
for desc, a, v, parts, ctx, who, text, rto, want in CASES:
    cap = Capture()
    tr, msgs, pl = room(cap, a, v, parts, ctx)
    send(tr, msgs, pl, who, text, "x", reply_to=rto, preview=True)
    c = cap.calls[-1]
    got, ms, why = Counter(), [], ""
    for _ in range(n):
        t0 = time.time()
        lab, why = classify_bystander(c["ctx"], c["spk"], c["txt"], reply=c["reply"])
        got[lab] += 1
        ms.append(int((time.time() - t0) * 1000))
    ok = set(got) <= want
    bad += 0 if ok else 1
    print(f"[{'OK ' if ok else 'BAD'}] {desc}: {dict(got)}  (기대 {'/'.join(sorted(want))}, "
          f"{min(ms)}~{max(ms)}ms)\n      근거: {why}")
print(f"\n{len(CASES) - bad}/{len(CASES)} 케이스가 기대와 같음")
sys.exit(1 if bad else 0)
