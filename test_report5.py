# -*- coding: utf-8 -*-
"""
v0.3.9 확인 (2026-10-30 앱팀 확인 결과)
  1. 가해자 말에 답장한 '니가 잘못한거잖아'가 [피해자/비판] 동조로 나옴 -> 답장 속 2인칭 비판은 답장 대상을 향한 것으로 고친다
  2. 전송 전 호출 9건 중 2건이 규칙(시간 초과) -> LLM을 모델 추론보다 먼저 출발, 출력 줄이기, 연결 유지·미리 깨우기

    python test_report5.py               # 모델·LLM 없이
    python test_report5.py --live 10     # 실서버에서: 실제 LLM 응답 시간과 답장 판정을 10번씩 잰다 (API 키 필요)
    python test_report5.py --live 10 --models claude-sonnet-4-6,claude-haiku-4-5   # 모델별로 비교

대사는 앱팀 보고에 인용된 줄과, 같은 짜임으로 새로 쓴 가상의 줄이다.
"""
import os, sys, time, statistics
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu import phase4_bystander as P
from withu.bystander import BystanderTracker

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


PARTS = {"P01": "태민", "P02": "건우", "P03": "현우", "P04": "서아"}
CTX = [("P01", "건우 너 진짜 왜 그러냐", "a1"), ("P02", "내가 뭘", "a2"),
       ("P01", "아 또 예민하게 받아들이네", "a3"), ("P02", "그만해", "a4"),
       ("P03", "아 배고프다", "a5")]


def room(classify, rid="r"):
    T.ROSTERS.clear()
    tr = BystanderTracker(classify=classify)
    plist = [{"participant_code": c, "display_name": n} for c, n in PARTS.items()]
    T.ROSTERS.update(rid, plist)
    t = time.time()
    msgs = [{"participant_code": c, "text": x, "message_id": m, "timestamp": t} for c, x, m in CTX]
    first = msgs[0]
    tr.on_analyze({"room_id": rid, "new_message": first, "context": [], "participants": plist},
                  {"attribution": {"is_bullying": True, "aggressors": ["P01"], "victim": "P02", "victim_reason": "name_mention"}},
                  [{"message_id": "a1", "speaker": "P01", "ts": t, "cb": 0.9}])
    return tr, msgs, plist


def body(msgs, plist, text, reply_to=None, mid="x", rid="r"):
    return {"room_id": rid, "context": msgs, "participants": plist,
            "new_message": {"participant_code": "P04", "text": text, "message_id": mid,
                            "timestamp": time.time(), "reply_to_message_id": reply_to}}


def app_classify(ctx, spk, txt, reply=None):          # app.py의 _classify와 같은 모양
    label, why = P.classify_bystander(ctx, spk, txt, reply=reply)
    return None if str(why).startswith("(error") else (label, why)


if "--live" not in sys.argv:
    J = lambda t, s, l: '{"target":"%s","stance":"%s","label":"%s","reason":"x"}' % (t, s, l)
    A, V = ("P01(가해자)", "아 또 예민하게 받아들이네"), ("P02(피해자)", "그만해")

    print("1) 답장 속 2인칭 비판은 답장 대상을 향한 것 (LLM이 target을 잘못 잡아도)")
    lab, why = P.parse_label(J("피해자", "비판", "동조"), "니가 잘못한거잖아", A)
    check("가해자에게 답장 + LLM [피해자/비판] 동조 -> 방어", lab == "방어", why)
    check("근거에 고친 이유가 남음", "답장 대상이 가해자" in why, why)
    lab, why = P.parse_label(J("피해자", "비판", "동조"), "니가 잘못한거잖아", V)
    check("피해자에게 답장 -> 동조 그대로", lab == "동조", why)
    lab, _ = P.parse_label(J("피해자", "비판", "동조"), "니가 잘못한거잖아", None)
    check("답장 아님 -> LLM 판정 그대로", lab == "동조")
    lab, _ = P.parse_label(J("피해자", "조롱", "동조"), "ㅋㅋㅋ", A)
    check("가해자에게 단 웃음은 건드리지 않음 (동조)", lab == "동조")
    lab, _ = P.parse_label(J("가해자", "지지", "동조"), "ㄹㅇ 니 말이 맞음", A)
    check("가해자에게 단 호응(지지)은 건드리지 않음 (동조)", lab == "동조")
    lab, _ = P.parse_label(J("피해자", "비판", "동조"), "P02(피해자) 니가 먼저 그랬잖아", A)
    check("본문에 다른 아이가 나오면 건드리지 않음", lab == "동조")
    lab, _ = P.parse_label(J("가해자", "비판", "방어"), "너무 심하잖아", V)
    check("'너무'는 2인칭이 아님 (피해자 답장이어도 방어 그대로)", lab == "방어")
    user = P.build_user_prompt([("P01(가해자)", "a")], "P04(주변인)", "니가 잘못한거잖아", A)
    check("프롬프트 대상 발화 줄에 누구에게 단 답장인지", "[대상 발화] P04(주변인) → P01(가해자)에게 답장: 니가 잘못한거잖아" in user, user)

    print("\n2) 서버 전체 흐름: LLM이 늘 [피해자/비판] 동조라고 답해도")
    real_call = P.call_llm
    P.call_llm = lambda system, user, max_tokens=None: J("피해자", "비판", "동조")
    try:
        tr, msgs, pl = room(app_classify)
        p = tr.preview(body(msgs, pl, "니가 잘못한거잖아", reply_to="a3"), timeout=2)
        check("가해자(a3)에게 답장 -> preview 방어", p["label"] == "방어", str(p))
        tr, msgs, pl = room(app_classify)
        p = tr.preview(body(msgs, pl, "니가 잘못한거잖아", reply_to="a4"), timeout=2)
        check("피해자(a4)에게 답장 -> preview 동조", p["label"] == "동조", str(p))
        tr, msgs, pl = room(app_classify)
        p = tr.preview(body(msgs, pl, "니가 잘못한거잖아"), timeout=2)
        check("답장 없이 -> LLM 판정 그대로 (동조)", p["label"] == "동조", str(p))
    finally:
        P.call_llm = real_call

    print("\n3) LLM을 모델 추론보다 먼저 출발: 아이가 기다리는 상한은 그대로, LLM은 먼저 출발")
    slow = lambda *a, **k: (time.sleep(0.6), ("방어", "[가해자/비판] 느린 LLM"))[1]
    tr, msgs, pl = room(slow)
    t0 = time.time()
    p = tr.preview(body(msgs, pl, "그만해"), timeout=0.3)
    check("예전 방식(추론 뒤 출발, 예산 0.3초) -> 규칙(시간 초과)", p["source"] == "규칙(시간 초과)", str(p))
    tr, msgs, pl = room(slow)
    h = tr.preview_begin(body(msgs, pl, "그만해", mid="y"))
    time.sleep(0.4)                                    # 모델 추론이라고 치고
    w0 = time.time()
    p = tr.preview_end(h, timeout=0.3)
    waited = time.time() - w0
    check("먼저 출발(추론 0.4초 + 예산 0.3초) -> LLM", p["source"] == "LLM", str(p))
    check("추론 뒤 더 기다린 시간 ≤ 예산", waited <= 0.35 and tr.last_preview_wait_ms <= 350, f"{waited:.2f}s")
    st = tr.on_analyze(body(msgs, pl, "그만해", mid="y") | {"track_bystander": True},
                       {"attribution": {"is_bullying": False}}, [{"message_id": "y", "speaker": "P04", "ts": time.time(), "cb": 0.1}])
    me = next(b for b in st["bystanders"] if b["participant_code"] == "P04")
    check("전송 후 호출이 같은 판정을 씀 (방어)", me["behavior"] == "방어", str(me["behavior"]))
    tr, msgs, pl = room(slow)
    check("가해자 메시지는 미리 판정하지 않음", tr.preview_begin({**body(msgs, pl, "ㅋㅋ"),
          "new_message": {"participant_code": "P01", "text": "ㅋㅋ"}}) is None)
    check("preview_end(None) -> None", tr.preview_end(None) is None)
    check("열린 사건 확인", tr.has_open_incident("r") and not tr.has_open_incident("없는방"))

    print("\n4) 미리 깨우기: 오래 쉬었을 때만, 1토큰")
    calls = []
    P.call_llm = lambda system, user, max_tokens=None: calls.append(max_tokens) or "ok"
    try:
        P._last_call, P.WARM_SEC = 0.0, 45
        check("오래 쉬었으면 깨움", P.warm() is True and calls == [1], str(calls))
        P._last_call = time.time()                     # (가짜 call_llm은 시각을 남기지 않으므로 직접)
        check("방금 불렀으면 안 깨움", P.warm() is False and len(calls) == 1)
        P.WARM_SEC = 0
        P._last_call = 0.0
        check("BYSTANDER_LLM_WARM_SEC=0이면 끔", P.warm() is False and len(calls) == 1)
    finally:
        P.call_llm, P.WARM_SEC = real_call, 45

    print("\n5) API 클라이언트가 연결을 오래 붙잡아 둔다 (SDK 기본 5초 -> 120초)")
    for name in ("openai", "anthropic"):
        try:
            mod = __import__(name)
        except ImportError:
            print(f"   ({name} 미설치, 건너뜀)")
            continue
        hc = P._http_client(mod)
        exp = getattr(getattr(hc, "_transport", None), "_pool", None)
        exp = getattr(exp, "_keepalive_expiry", None)
        check(f"{name}: keepalive_expiry = {P.KEEPALIVE_SEC:g}초", hc is not None and exp == P.KEEPALIVE_SEC, str(exp))

    print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
    sys.exit(1 if fails else 0)

# ---------------------------------------------------------------- 실서버: 실제 LLM 응답 시간
n = int(sys.argv[sys.argv.index("--live") + 1]) if len(sys.argv) > sys.argv.index("--live") + 1 else 10
models = sys.argv[sys.argv.index("--models") + 1].split(",") if "--models" in sys.argv else [P.MODEL]
budget = float(os.environ.get("BYSTANDER_PREVIEW_TIMEOUT_SEC", 1.5))
CASES = [("가해자에게 답장 '니가 잘못한거잖아'", "니가 잘못한거잖아", "a3", "방어"),
         ("피해자에게 답장 '니가 잘못한거잖아'", "니가 잘못한거잖아", "a4", "동조"),
         ("답장 없이 'ㅋㅋㅋ 인정'", "ㅋㅋㅋ 인정", None, "동조")]


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


for model in models:
    P.MODEL, P._client = model, None
    print(f"\n=== provider={P.PROVIDER} model={model}  max_tokens={P.MAX_TOKENS} keepalive={P.KEEPALIVE_SEC:g}s  (예산 {budget:g}초)")
    P.classify_bystander([("P01(가해자)", "a")], "P04(주변인)", "흠", retries=0)     # 첫 연결은 재지 않는다
    for desc, text, rto, want in CASES:
        cap = []
        tr, msgs, pl = room(lambda c, s, t, reply=None: cap.append((c, s, t, reply)) or ("비해당", "x"))
        tr.preview(body(msgs, pl, text, reply_to=rto), timeout=2)
        c, s, t, reply = cap[-1]
        ms, got = [], {}
        for _ in range(n):
            t0 = time.time()
            lab, why = P.classify_bystander(c, s, t, reply=reply, retries=0)
            ms.append(int((time.time() - t0) * 1000))
            got[lab] = got.get(lab, 0) + 1
        ok = sum(m <= budget * 1000 for m in ms)
        print(f"[{'OK ' if set(got) == {want} else 'BAD'}] {desc}: {got} (기대 {want})  "
              f"중앙 {int(statistics.median(ms))}ms, p90 {q(ms, .9)}ms, 최대 {max(ms)}ms, 예산 안 {ok}/{n}\n      근거: {why}")
    # 쉬었다가 부르면(연결이 식으면) 얼마나 느려지는지
    cold, warm_ms = [], []
    for _ in range(min(n, 4)):
        time.sleep(8)                     # 예전 SDK 기본(5초)이면 여기서 연결이 끊긴다
        t0 = time.time(); P.classify_bystander(c, s, t, reply=reply, retries=0); cold.append(int((time.time() - t0) * 1000))
        t0 = time.time(); P.classify_bystander(c, s, t, reply=reply, retries=0); warm_ms.append(int((time.time() - t0) * 1000))
    print(f"   8초 쉰 뒤 첫 호출 {cold} ms / 바로 다음 호출 {warm_ms} ms")
