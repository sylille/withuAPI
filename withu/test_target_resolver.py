# -*- coding: utf-8 -*-
"""Unit tests for withu/target_resolver.py — no models needed.  python tests/test_target_resolver.py"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from withu import target_resolver as T

P = [{"participant_code": "C013", "display_name": "하늘"},
     {"participant_code": "C011", "display_name": "내가최고다"},
     {"participant_code": "C020", "display_name": "김민준"},
     {"participant_code": "C030", "display_name": "별이", "aliases": ["별"]}]
TOX, OK = 0.95, 0.05
fails = 0


def W(*rows):
    return [dict(speaker=s, text=t, cb=c) for s, t, c in rows]


def check(name, cond, r):
    global fails
    a = r["attr"]
    print(f"[{'PASS' if cond else 'FAIL'}] {name:46s} bully={r['is_bullying']!s:5} victim={a.victim} "
          f"via={a.victim_reason} drop={r['drop_reason']} {r.get('drop_detail', '')}")
    fails += 0 if cond else 1


def stream(room, conv, win=6, parts=P):
    T.HISTORY.clear(room); T.ROSTERS.clear()
    out = []
    for k in range(1, len(conv) + 1):
        out.append(T.evaluate_window_v2(W(*conv[max(0, k - win):k]), room_id=room, participants=parts))
    return out


# 1. old behaviour kept: code in the text
r = T.evaluate_window_v2(W(("C011", "C013 너 진짜 냄새나 꺼져", TOX), ("C013", "왜 그래...", OK)), room_id="a", participants=P)
check("code mention still opens", r["is_bullying"] and r["attr"].victim == "C013", r)

# 2. display name + victim answers -> opens on the first attack
r = T.evaluate_window_v2(W(("C011", "하늘 너 진짜 냄새나 꺼져", TOX), ("C013", "왜 그래...", OK)), room_id="b", participants=P)
check("display name + victim reply", r["is_bullying"] and r["attr"].victim == "C013", r)

# 3. display name, single attack, no reply yet -> waits
T.HISTORY.clear("c")
r = T.evaluate_window_v2(W(("C030", "오늘 숙제 뭐야", OK), ("C011", "하늘이 진짜 냄새나 꺼져", TOX)), room_id="c", participants=P)
check("one named attack, no reply -> not yet", not r["is_bullying"], r)
# ...second attack on a silent victim -> opens
r = T.evaluate_window_v2(W(("C030", "오늘 숙제 뭐야", OK), ("C011", "하늘이 진짜 냄새나 꺼져", TOX),
                           ("C011", "하늘아 나가라", TOX)), room_id="c", participants=P)
check("two named attacks, silent victim", r["is_bullying"] and r["attr"].victim == "C013", r)

# 4. given name from a 3-char real name
out = stream("d", [("C011", "민준아 너 진짜 찐따같아 꺼져", TOX), ("C020", "왜 나한테 그래", OK)])
check("김민준 -> 민준아", out[-1]["is_bullying"] and out[-1]["attr"].victim == "C020", out[-1])

# 5. 2-char name inside another word is NOT a mention
out = stream("e", [("C011", "하늘색 옷 입은 애 역겨워", TOX), ("C030", "누구?", OK)])
check("하늘색 is not 하늘", out[-1]["attr"].victim != "C013", out[-1])

# 6. repeated attacks, no names, victim keeps answering -> opens
conv = [("C013", "나 왔어", OK), ("C011", "너 진짜 냄새나", TOX), ("C013", "왜 그래", OK), ("C030", "ㅋㅋ", OK),
        ("C011", "꺼져 역겨워", TOX), ("C013", "내가 뭘 했는데", OK), ("C011", "나가라 그냥", TOX),
        ("C013", "하지마 ㅠㅠ", OK), ("C011", "말하지마 냄새나", TOX)]
out = stream("f", conv, win=5)
first = next((i for i, r in enumerate(out) if r["is_bullying"]), None)
check("repeated, no names (opens at 4th attack)", first == 8 and out[-1]["attr"].victim == "C013", out[-1])
check("... reason repeated_target", out[-1]["attr"].victim_reason == "repeated_target", out[-1])
check("... not opened after only 3 attacks", not out[7]["is_bullying"], out[7])

# 7. same pattern but the 'victim' only laughs -> banter, no incident
conv = [("C011", "야 꺼져 ㅋㅋ", TOX), ("C013", "ㅋㅋㅋㅋ", OK), ("C011", "병신아 ㅋㅋ", TOX), ("C013", "ㅋㅋㅋㅋㅋ 인정", OK),
        ("C011", "역겨워 ㅋㅋ", TOX), ("C013", "ㅋㅋㅋ", OK), ("C011", "꺼져라", TOX), ("C013", "ㅎㅎ", OK)]
out = stream("g", conv, win=5)
check("laughing along -> no incident", not any(r["is_bullying"] for r in out), out[-1])

# 8. mutual swearing -> no incident
conv = [("C011", "야 꺼져", TOX), ("C013", "니가 꺼져 병신아", TOX), ("C011", "역겨워", TOX), ("C013", "너나 역겹지", TOX),
        ("C011", "나가라", TOX), ("C013", "왜 내가 나가 니가 나가", 0.6), ("C011", "꺼져", TOX), ("C013", "너나 꺼져", TOX)]
out = stream("h", conv, win=5)
check("mutual swearing -> no incident", not any(r["is_bullying"] for r in out), out[-1])

# 9. group bullying: two aggressors, one victim who answers
conv = [("C011", "너 진짜 냄새나", TOX), ("C013", "왜 그래", OK), ("C020", "ㄹㅇ 역겨워 꺼져", TOX), ("C013", "그만해", OK),
        ("C011", "나가라", TOX), ("C013", "내가 뭘", OK), ("C020", "꺼지라고", TOX), ("C011", "냄새나 꺼져", TOX),
        ("C013", "선생님한테 말할거야", OK), ("C020", "찐따 꺼져", TOX), ("C011", "꺼져 진짜", TOX), ("C013", "하지마 ㅠ", OK)]
out = stream("i", conv, win=6)
check("group bullying (2 aggressors)", out[-1]["is_bullying"] and out[-1]["attr"].victim == "C013"
      and set(out[-1]["attr"].aggressors) == {"C011", "C020"}, out[-1])

# 10. pre-send call (commit=False) does not enter room history
T.HISTORY.clear("j")
T.evaluate_window_v2(W(("C011", "너 꺼져", TOX)), room_id="j", commit=False)
check("pre-send not stored", len(T.HISTORY._rooms.get("j", [])) == 0, {"attr": T.SimpleNamespace(victim=None, victim_reason=""), "is_bullying": False, "drop_reason": ""})

# 11. reply_to (explicit target) through request context
class Req:  # minimal stand-in for the pydantic request
    room_id = "k"; track_bystander = True; participants = P
    context = [{"participant_code": "C013", "text": "나 그림 그렸어", "message_id": "m1"}]
    new_message = {"participant_code": "C011", "text": "그게 그림이냐 쓰레기네 꺼져", "message_id": "m2", "reply_to_message_id": "m1"}
T.HISTORY.clear("k"); T.set_request_context(Req)
r = T.evaluate_window_v2(W(("C013", "나 그림 그렸어", OK), ("C011", "그게 그림이냐 쓰레기네 꺼져", TOX)))
check("reply_to -> explicit_target", r["is_bullying"] and r["attr"].victim_reason == "explicit_target" and r["attr"].victim == "C013", r)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
