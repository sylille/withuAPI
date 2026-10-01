# -*- coding: utf-8 -*-
"""
Live end-to-end test of the running WithU server (Modules A/B + guard + attribution + gate
+ Module D + 방관 tracker).  Stdlib only.

    cd ~/Downloads
    python test_live_server.py                       # server on 127.0.0.1:8000, default 30/60 s timers (~70 s)
    python test_live_server.py --t1 5 --t2 10        # if the server was started with BYSTANDER_T1_SEC=5 BYSTANDER_T2_SEC=10
    python test_live_server.py --base https://xxx.trycloudflare.com --key $WITHU_API_KEY

HARD checks = deterministic logic (must pass).  SOFT checks = depend on model/LLM judgement
(a WARN means "look at it", not necessarily a bug).
"""
import argparse, json, sys, time, urllib.request, urllib.error

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default=None, help="X-API-Key if the server requires one")
ap.add_argument("--t1", type=float, default=30)
ap.add_argument("--t2", type=float, default=60)
args = ap.parse_args()

RUN = str(int(time.time()))
ROOM = f"test_room_{RUN}"
results = []            # (level, name, ok, detail)
ALL_ACTIONS = []        # every action seen, from any response


def call(method, path, body=None):
    url = args.base.rstrip("/") + path
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if args.key:
        req.add_header("X-API-Key", args.key)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        print(f"\n!! {method} {path} -> HTTP {e.code}: {e.read().decode('utf-8')[:500]}")
        raise
    ALL_ACTIONS.extend(out.get("actions", []) if isinstance(out, dict) else [])
    return out


def check(level, name, ok, detail=""):
    results.append((level, name, bool(ok), detail))
    tag = "PASS" if ok else ("FAIL" if level == "HARD" else "WARN")
    print(f"  [{tag}] {name}" + (f"  — {detail}" if detail and not ok else ""))


def msg(code, text, mid, **kw):
    return {"participant_code": code, "text": text, "message_id": mid, **kw}


CTX = {}
def analyze(room, code, text, mid, track=True, **kw):
    ctx = CTX.setdefault(room, [])
    body = {"room_id": room, "context": ctx[-8:], "new_message": msg(code, text, mid, **kw),
            "track_bystander": track}
    r = call("POST", "/analyze", body)
    ctx.append({"participant_code": code, "text": text, "message_id": mid})
    return r


def event(code, typ, **kw):
    return call("POST", "/bystander/events", {"room_id": ROOM, "participant_code": code, "type": typ, **kw})


def poll():
    return call("GET", f"/bystander/actions?room_id={ROOM}")


def state_of(code):
    st = call("GET", f"/bystander/state?room_id={ROOM}&participant_code={code}")["incident"]
    return (st or {}).get("bystanders", [{}])[0] if st and st.get("bystanders") else {}


def got_action(code, action):
    return any(a.get("participant_code") == code and a.get("action") == action for a in ALL_ACTIONS)


print(f"server: {args.base}   room: {ROOM}   timers: T1={args.t1}s T2={args.t2}s\n")

# --------------------------------------------------------------------------- 1
print("1) health")
h = call("GET", "/health")
check("HARD", "ensemble_ready", h.get("ensemble_ready"), h)
check("HARD", "bystander_tracker running", h.get("bystander_tracker"), h)

# --------------------------------------------------------------------------- 2
print("\n2) Modules A/B + prosocial guard (message level)")
r = analyze(f"calm_{RUN}", "P01", "오늘 급식 뭐야?", "c1")
check("SOFT", "normal chat -> low score", r["cb_score"] < 0.5, f"cb={r['cb_score']}")
check("HARD", "normal chat -> no incident", r.get("incident_id") is None)
r = analyze(f"calm_{RUN}", "P02", "네 잘못이 아니야.", "c2", is_defense_action=True)
check("HARD", "comfort msg with is_defense_action -> cb 0", r["cb_score"] == 0.0, f"cb={r['cb_score']}")
check("HARD", "guard_reason = defense_action", r.get("guard_reason") == "defense_action", r.get("guard_reason"))
r = analyze(f"calm_{RUN}", "P02", "네 잘못이 아니야.", "c3")
print(f"      (no flag) '네 잘못이 아니야.' -> cb={r['cb_score']} suppressed={r.get('suppressed')} guard={r.get('guard_reason')}")
check("SOFT", "comfort msg without flag capped <= 0.30", r["cb_score"] <= 0.30, f"cb={r['cb_score']}")

# --------------------------------------------------------------------------- 3
print("\n3) event gate: mutual banter should NOT open an incident")
B = f"banter_{RUN}"
for i, (c, t) in enumerate([("P21", "ㅅㅂ 그걸 왜 지냐"), ("P22", "너나 잘해 존나 못하면서"),
                            ("P21", "닥쳐 병신아"), ("P22", "ㅂㅅ아 너 때문이잖아"),
                            ("P23", "둘다 그만 ㅋㅋ"), ("P21", "존나 억울하네")]):
    r = analyze(B, c, t, f"b{i}")
a = r.get("attribution") or {}
print(f"      attribution: is_bullying={a.get('is_bullying')} aggr={a.get('aggressors')} "
      f"victim={a.get('victim')} drop={a.get('drop_reason')}")
check("SOFT", "banter -> is_bullying false", a.get("is_bullying") is False, a.get("drop_reason"))

# --------------------------------------------------------------------------- 4
print("\n4) real attack -> incident opens")
analyze(ROOM, "P11", "하늘 너 진짜 냄새나 꺼져", "m1")
analyze(ROOM, "하늘", "왜 그래...", "m2")
analyze(ROOM, "P11", "하늘 같은 애는 역겨우니까 나가라", "m3")
r = analyze(ROOM, "P11", "하늘 돼지야 진짜 병신같아", "m4")
a = r.get("attribution") or {}
print(f"      attribution: is_bullying={a.get('is_bullying')} aggr={a.get('aggressors')} victim={a.get('victim')} "
      f"via={a.get('victim_reason')} conf={a.get('confidence')} drop={a.get('drop_reason')}")
check("HARD", "incident opened", r.get("incident_id"),
      "is_bullying stayed false — see drop_reason above (model scores may be below 0.5)")
if not r.get("incident_id"):
    print("\nCannot continue the bystander tests without an incident. Stopping.")
    sys.exit(1)
check("HARD", "aggressor = P11", "P11" in (a.get("aggressors") or []))
check("HARD", "victim = 하늘", a.get("victim") == "하늘")

# --------------------------------------------------------------------------- 5
print("\n5) bystanders read the attack")
for c in ["P05", "P06", "P07", "P08", "P09", "P10", "P12", "P14"]:
    event(c, "read", message_id="m4")
check("HARD", "P05 is observing after read", state_of("P05").get("stage") == "observing", state_of("P05"))
event("P99", "leave")                               # never read -> never judged
check("HARD", "never-read member not judged", state_of("P99").get("stage") in (None, "unseen"), state_of("P99"))

# --------------------------------------------------------------------------- 6
print("\n6) Module D on bystander messages (LLM — soft)")
for code, text, want, mid in [("P06", "야 그만해 하지마 너무 심하잖아", {"방어"}, "m5"),
                              ("P07", "ㅋㅋㅋㅋ 인정", {"동조"}, "m6"),
                              ("P08", "근데 내일 소풍 가?", {"방관", "비해당", None}, "m7")]:
    r = analyze(ROOM, code, text, mid)
    got = r.get("bystander_behavior")
    s = state_of(code)
    print(f"      {code} '{text}' -> {got}  (stage={s.get('stage')}, last={s.get('history', [{}])[-1].get('event') if s.get('history') else None})")
    check("SOFT", f"{code} judged {'/'.join(x for x in want if x)}", got in want, f"got {got}")

# --------------------------------------------------------------------------- 7
print("\n7) reaction buttons (rules — hard)")
event("P12", "reaction", target_message_id="m2", reaction="empathy")           # victim's msg
check("HARD", "empathy on victim msg -> 방어", state_of("P12").get("behavior") == "방어", state_of("P12"))
event("P10", "reaction", target_message_id="m3", reaction="laugh")             # aggressor's msg
check("HARD", "laugh on aggressor msg -> 동조", state_of("P10").get("behavior") == "동조", state_of("P10"))
event("P10", "reaction_cancel")
s = state_of("P10")
check("HARD", "cancel within 10 s -> 동조 removed", s.get("behavior") is None and s.get("stage") == "observing", s)

# --------------------------------------------------------------------------- 8
print("\n8) leave / crash / re-entry / late witness")
event("P09", "leave", normal=True)
s = state_of("P09")
check("HARD", "normal leave -> 방관(채팅방 나가기)", s.get("subtype") == "채팅방 나가기" and s.get("badge"), s)
check("HARD", "badge action sent", got_action("P09", "badge"))
event("P09", "join")
check("HARD", "re-entry -> choices", got_action("P09", "choices"))
event("P14", "leave", normal=False)
check("HARD", "crash leave -> NOT 방관", state_of("P14").get("behavior") is None, state_of("P14"))
event("P13", "room_open", unread_count=40)
check("HARD", "40 unread on open -> summary first", got_action("P13", "summary"))

# --------------------------------------------------------------------------- 9
print(f"\n9) silence timers for P05 (waiting ~{int(args.t2) + 3}s)")
time.sleep(args.t1 + 2); poll()
check("HARD", f"1차 알림 after T1 ({args.t1:g}s)", got_action("P05", "nudge_1"), state_of("P05"))
time.sleep(max(0, args.t2 - args.t1) + 1); poll()
s = state_of("P05")
check("HARD", f"2차 알림 after T2 ({args.t2:g}s)", got_action("P05", "nudge_2"), s)
check("HARD", "P05 = 방관(침묵) confirmed", s.get("stage") == "confirmed" and s.get("subtype") == "침묵", s)
check("HARD", "max 2 nudges", s.get("nudges", 0) <= 2, s.get("nudges"))

# --------------------------------------------------------------------------- 10
print("\n10) P05 finally defends via chatbot")
event("P05", "defense_action", kind="comfort_dm")
s = state_of("P05")
check("HARD", "P05 -> 방어", s.get("behavior") == "방어", s)
check("HARD", "방관→방어 transition logged", any("방관→방어" in h.get("event", "") for h in s.get("history", [])))
check("HARD", "positive_feedback sent", got_action("P05", "positive_feedback"))

# --------------------------------------------------------------------------- summary
print("\n" + "=" * 70)
st = call("GET", f"/bystander/state?room_id={ROOM}")["incident"]
print(f"incident {st['incident_id']}  aggressors={st['aggressors']} victim={st['victim']} attacks={st['n_attack_messages']}")
for b in st["bystanders"]:
    print(f"  {b['participant_code']:4} stage={b['stage']:10} behavior={str(b['behavior']):5} "
          f"subtype={str(b['subtype']):8} nudges={b['nudges']}")
hard_fail = [r for r in results if r[0] == "HARD" and not r[2]]
soft_warn = [r for r in results if r[0] == "SOFT" and not r[2]]
print(f"\nHARD: {sum(1 for r in results if r[0]=='HARD' and r[2])}/{sum(1 for r in results if r[0]=='HARD')} passed"
      f"   SOFT: {sum(1 for r in results if r[0]=='SOFT' and r[2])}/{sum(1 for r in results if r[0]=='SOFT')} as expected")
for r in hard_fail: print("  FAIL:", r[1], "|", r[3])
for r in soft_warn: print("  WARN:", r[1], "|", r[3])
sys.exit(1 if hard_fail else 0)
