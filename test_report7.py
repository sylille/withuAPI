# -*- coding: utf-8 -*-
"""
v0.3.15 확인: 앱팀 사후검사 보고(2026-11-25). 모델·LLM 없이 실행된다.

    python test_report7.py

1) 사후검사2 — 가해자(지민)를 나무란 주변인(예슬)이 공동 가해자로 잡히던 문제
   "나쁜 새끼들", "지민아 조용히 좀 해"가 공격으로 세어져 예슬이 attribution.aggressors와 attack_message_ids에 들어갔다.
   이제 역할 판정에서는 공격으로 세지 않는다. 메시지 점수는 그대로라 "나쁜 새끼들"은 여전히 언어적 폭력(전송 전 경고)이다.
2) 같은 낱말이 진짜 공격일 때는 그대로 공격인지 (우회되지 않는지)
3) 사후검사4·1 — "소희 즐", "소희야", "야르", "겅우", "얄."이 방어로 나오던 문제 (LLM 라벨을 서버가 고침)

모듈 A 점수는 대본에 적은 값을 쓴다 (실제 모델 점수가 아님). 보고에 인용된 대사 외에는 가상으로 채운 것이다.
"""
import os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble
from withu.phase4_bystander import parse_label, SYSTEM

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


def play(room, parts, lines, win=8):
    """lines: [(이름, 본문, 모듈A 점수)]. 앱처럼 직전 7개를 context로 보낸다. -> (최종 상태, 줄마다 결과, 이름->코드)"""
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = BystanderTracker(classify=None)
    T.HISTORY.clear(room); T.ROSTERS.clear()
    code = {p: f"P{i+1:02d}" for i, p in enumerate(parts)}
    name = {c: p for p, c in code.items()}
    plist = [{"participant_code": c, "display_name": p} for p, c in code.items()]
    sent, log, t = [], [], 3000.0
    for k, (who_n, text, cb) in enumerate(lines):
        who = code[who_n]
        score[text] = cb
        t += 4
        new = {"participant_code": who, "text": text, "message_id": f"{room}_{k+1}", "timestamp": t}
        body = {"room_id": room, "context": sent[-(win - 1):], "new_message": new, "participants": plist,
                "has_image": False, "track_bystander": True}
        T.set_request_context(NS(room_id=room, context=body["context"], new_message=new, participants=plist,
                                 has_image=False, track_bystander=True))
        res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": m["timestamp"],
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [new]]
        tr.on_analyze(body, res, wins, now=t)
        a = res["attribution"]
        log.append(NS(k=k + 1, who=who_n, text=text, mid=new["message_id"], bully=a["is_bullying"],
                      aggr=sorted(name[x] for x in a["aggressors"]), victim=name.get(a["victim"]),
                      attack_ids=a["attack_message_ids"], cb=res["cb_score"], typ=res["cb_type"],
                      guard=res["guard_reason"]))
        sent.append(new)
    st = tr.state(room)
    if st:
        st["aggressors"] = sorted(name[x] for x in st["aggressors"])
        st["victim"] = name.get(st["victim"])
        st["bystanders"] = [name[b["participant_code"]] for b in st["bystanders"]]
    return st, log


def notes(parts, lines):
    """역할 판정 전처리(prepare)가 메시지마다 붙인 가드 표시 {본문: note}."""
    T.ROSTERS.clear()
    code = {p: f"P{i+1:02d}" for i, p in enumerate(parts)}
    T.ROSTERS.update("n", [{"participant_code": c, "display_name": p} for p, c in code.items()])
    items = [{"speaker": code[w], "text": t, "cb": cb} for w, t, cb in lines]
    return {t: d.get("note") for (w, t, cb), d in zip(lines, T.prepare(items, roster=T.ROSTERS.get("n"), room_id="n"))}


def row(log, text):
    return next(r for r in log if r.text == text)


# ------------------------------------------------------------------------------------------------ 1
print("1) 사후검사2 — 가해자를 나무란 주변인이 공동 가해자로 잡히던 문제")
S2 = [("지민", "도현이 또 숙제 안 해옴", .55), ("수아", "ㄹㅇ 맨날 그럼", .10), ("지민", "걔 진짜 짜증나", .70),
      ("예슬", "나쁜 새끼들", .90), ("수아", "맞아", .05), ("예슬", "지민아 조용히 좀 해", .70),
      ("민재", "오늘 급식 뭐야", .05), ("지민", "도현이 빼고", .60), ("수아", "ㅇㅈ 걔 빼자", .30),
      ("지민", "걔 오면 분위기 망함", .65)]
st, log = play("r7a", ["지민", "수아", "예슬", "민재", "도현"], S2)
yes_ids = {r.mid for r in log if r.who == "예슬"}
check("어느 판정에서도 예슬이 가해자로 나오지 않음", all("예슬" not in r.aggr for r in log),
      str([(r.k, r.aggr) for r in log if "예슬" in r.aggr]))
check("예슬의 메시지가 attack_message_ids에 들어가지 않음", all(not (set(r.attack_ids) & yes_ids) for r in log))
check("'도현이 빼고' 판정: 가해 지민 / 피해 도현", row(log, "도현이 빼고").bully and row(log, "도현이 빼고").aggr == ["지민"]
      and row(log, "도현이 빼고").victim == "도현", str(vars(row(log, "도현이 빼고"))))
check("최종 사건에서 예슬은 주변인 (선택지가 보임)", bool(st) and st["aggressors"] == ["지민"] and "예슬" in st["bystanders"],
      str(st and (st["aggressors"], st["bystanders"])))
r = row(log, "나쁜 새끼들")
check("'나쁜 새끼들'은 메시지 점수 그대로 — 언어적 폭력 (욕설 경고는 유지)", r.typ == "언어적 폭력" and r.cb == 0.9, f"{r.typ} {r.cb}")
r = row(log, "지민아 조용히 좀 해")
check("'지민아 조용히 좀 해'는 경고 없음 (guard_reason=counter_aggressor)",
      r.typ == "비해당" and r.guard == "counter_aggressor", f"{r.typ} {r.cb} {r.guard}")

# ------------------------------------------------------------------------------------------------ 2
print("\n2) 같은 말이 진짜 공격이면 그대로 공격 (우회되지 않음)")
# 2-1 가해자가 먼저 말하지 않았으면 "○○들" 욕은 그냥 공격이다
A = [("도윤", "야 새끼들아", .90), ("서연", "뭐야", .05), ("도윤", "나쁜 새끼들", .90), ("하준", "왜 그래", .05),
     ("도윤", "서연 진짜 짜증나", .80), ("서연", "하지 마", .70)]
st, log = play("r7b", ["도윤", "서연", "하준"], A)
check("가해자가 없을 때의 '○○들' 욕은 공격 (도윤 = 가해자)", any(r.bully and r.aggr == ["도윤"] for r in log),
      str([(r.k, r.bully, r.aggr, r.victim) for r in log]))
# 2-2 가해자 편(맞장구친 아이)의 욕은 보호하지 않는다
B = [("지민", "도현이 진짜 짜증나", .80), ("수아", "ㅇㅈ", .05), ("지민", "도현이 빼고 놀자", .60),
     ("수아", "지민아 새끼들 다 빼버려", .85), ("지민", "도현 꺼져", .90)]
check("맞장구친 수아의 '지민아 새끼들 다 빼버려'는 공격으로 셈 (가드가 붙지 않음)",
      notes(["지민", "수아", "도현"], B)["지민아 새끼들 다 빼버려"] is None, str(notes(["지민", "수아", "도현"], B)))
# 2-3 웃음이 섞인 욕은 보호하지 않는다
C = [("지민", "도현이 진짜 짜증나", .80), ("예슬", "ㅋㅋㅋ 나쁜 새끼들", .85), ("지민", "도현이 빼고 하자", .60),
     ("예슬", "지민아 ㅋㅋ 꺼져", .85), ("지민", "도현 꺼져", .90)]
st, log = play("r7d", ["지민", "예슬", "도현"], C)
check("웃음 섞인 욕은 공격으로 셈 (예슬 = 공동 가해자)", any("예슬" in r.aggr for r in log if r.bully),
      str([(r.k, r.bully, r.aggr) for r in log]))
# 2-4 피해자 이름이 들어간 말은 보호하지 않는다
D = [("지민", "도현이 진짜 짜증나", .80), ("예슬", "지민아 도현이 새끼 맞지", .85), ("지민", "도현이 빼고 하자", .60),
     ("예슬", "도현 꺼져", .90), ("지민", "도현 꺼져", .90)]
st, log = play("r7e", ["지민", "예슬", "도현"], D)
check("피해자 이름이 나온 욕은 공격으로 셈 (예슬 = 공동 가해자)", any("예슬" in r.aggr for r in log if r.bully),
      str([(r.k, r.bully, r.aggr) for r in log]))
# 2-5 피해자 본인이 되받아친 욕은 예전처럼 센다 (서로 욕하는 대화 판정은 그대로)
E = [("지민", "도현 너 진짜 짜증나", .80), ("도현", "지민 너 나쁜 새끼야", .90), ("지민", "도현 꺼져", .90),
     ("도현", "지민 니가 꺼져", .90), ("지민", "도현 역겨워", .90), ("도현", "지민 너나 역겹지", .90)]
st, log = play("r7f", ["지민", "도현", "하준"], E)
check("피해자 본인이 되받아친 욕은 예전처럼 공격으로 셈 (도현도 가해자 → 서로 욕하는 대화로 사건이 닫힘)",
      all(v is None for v in notes(["지민", "도현", "하준"], E).values()) and "도현" in log[-1].aggr and not log[-1].bully,
      str([(r.k, r.bully, r.aggr, r.victim) for r in log]))
# 2-6 한 번 다른 아이를 공격한 주변인은 보호가 끝난다
F = [("지민", "도현이 진짜 짜증나", .80), ("예슬", "지민아 조용히 좀 해", .70), ("예슬", "도현 너도 꺼져", .90),
     ("예슬", "지민 나쁜 새끼", .90), ("지민", "도현이 빼고 하자", .60), ("예슬", "도현 진짜 별로", .80)]
st, log = play("r7g", ["지민", "예슬", "도현"], F)
check("피해자를 공격한 뒤의 예슬은 보호하지 않음 (예슬 = 공동 가해자)", any("예슬" in r.aggr for r in log if r.bully),
      str([(r.k, r.bully, r.aggr) for r in log]))

# ------------------------------------------------------------------------------------------------ 3
print("\n3) 주변인 발화: LLM이 방어라고 해도 서버가 고치는 경우")
ANS = lambda tg, st, lab: f'{{"target":"{tg}","stance":"{st}","label":"{lab}","reason":"x"}}'
for text, tg, st_, want in [("P12(피해자) 즐", "피해자", "지지", "비해당"), ("P12(피해자)야", "피해자", "지지", "비해당"),
                            ("야르", "없음", "중립", "비해당"), ("겅우", "없음", "중립", "비해당"), ("얄.", "없음", "중립", "비해당")]:
    lab, why = parse_label(ANS(tg, st_, "방어"), text)
    check(f"'{text}' 방어 -> {want}", lab == want, f"{lab} {why}")
lab, _ = parse_label(ANS("피해자", "욕설", "동조"), "P12(피해자) 즐")
check("'P12(피해자) 즐' 동조는 그대로 (피해자 공격)", lab == "동조", lab)
lab, _ = parse_label(ANS("피해자", "중립", "동조"), "P12(피해자)야")
check("'P12(피해자)야' 동조 -> 비해당 (이름만 부름)", lab == "비해당", lab)
for text in ["그만!", "멈춰", "P11(가해자) 그만해", "P11(가해자) 뭐래", "P12(피해자) 괜찮아?", "P11(가해자) 이상해",
             "P12(피해자) 불쌍해", "선생님한테 말하자", "P12(피해자)야 ㅠㅠ", "즐거운 얘기 하자"]:
    lab, why = parse_label(ANS("가해자", "비판", "방어"), text)
    check(f"'{text}' 방어는 그대로", lab == "방어", f"{lab} {why}")
check("루브릭에 '이름만 부른 말'·'즐' 기준이 들어감", "이름만 부른 말" in SYSTEM and '"즐"' in SYSTEM)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
