# -*- coding: utf-8 -*-
"""
v0.3.2 확인: 피해자 갱신(bystander.py)과 방향 판정(target_resolver.py). 모델 없이 실행된다.

    cd ~/Downloads && python withu/test_victim_direction.py

/analyze와 같은 순서(set_request_context -> Ensemble.analyze -> tracker.on_analyze)로 대본을 한 줄씩 보낸다.
모듈 A 점수는 대본에 적은 값을 쓴다 (실제 모델 점수가 아님). 1·2번은 앱팀 보고에 나온 판정 순서를 그대로 넣은 것이고,
3~6번 대본은 보고된 대사 일부에 가상의 앞부분을 붙인 것이다. 실제 사후·추수검사 대본으로는 test_scripts_live.py를 쓴다.
"""
import os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    fails += 0 if cond else 1


# ----------------------------------------------------------------------------- 1·2. 판정부만 (보고된 판정 순서)
def feed(tr, room, verdicts):
    """verdicts: [(speaker, aggressors, victim, reason)] — /analyze가 is_bullying=true로 돌려준 판정들"""
    t = 1000.0
    for k, (spk, aggr, vic, why) in enumerate(verdicts):
        t += 5
        win = [{"message_id": f"{room}{k}", "speaker": spk, "ts": t, "cb": 0.9}]
        tr.on_analyze({"room_id": room, "new_message": {"participant_code": spk, "text": "x"}, "context": []},
                      {"attribution": {"is_bullying": True, "aggressors": aggr, "victim": vic, "victim_reason": why}},
                      win, now=t)
    return tr.state(room), tr.drain(room, now=t)


print("1) 사후검사 1 — 보고된 판정 순서 그대로 (22번: 피해자 현우, 23번부터: 건우)")
st, acts = feed(BystanderTracker(), "r1", [
    ("태민", ["태민"], "현우", "repeated_target"),
    ("현우", ["태민", "현우"], "건우", "repeated_target"),
    ("현우", ["태민", "현우"], "건우", "name_mention"),
    ("태민", ["태민", "현우"], "건우", "name_mention")])
ups = [a for a in acts if a["action"] == "incident_update"]
check("최종 피해자 = 건우", st["victim"] == "건우", f"victim={st['victim']}")
check("가해자 = 태민·현우 (현우는 피해자에서 가해자로)", st["aggressors"] == ["태민", "현우"], str(st["aggressors"]))
check("건우는 주변인 목록에 없음", all(b["participant_code"] != "건우" for b in st["bystanders"]))
check("incident_update(victim_changed) 1번", [a["payload"].get("change") for a in ups].count("victim_changed") == 1,
      str([a["payload"] for a in ups]))
check("이름 지목 뒤 victim_status=confirmed", st["victim_status"] == "confirmed", st["victim_status"])

print("\n2) 약한 근거 한 번으로는 피해자가 바뀌지 않음 / 가해자·피해자 겹침 없음")
st, acts = feed(BystanderTracker(), "r2", [
    ("A", ["A"], "V", "name_mention"), ("A", ["A"], "X", "repeated_target"), ("A", ["A"], "V", "name_mention")])
check("이름으로 잡힌 피해자는 반응 근거 1번에 안 바뀜", st["victim"] == "V", st["victim"])
st, acts = feed(BystanderTracker(), "r3", [
    ("A", ["A"], "V", "repeated_target"), ("A", ["A"], "X", "repeated_target"), ("A", ["A"], "X", "repeated_target")])
check("같은 세기 근거는 2번 연속이면 바뀜", st["victim"] == "X" and st["previous_victims"] == ["V"], str(st))
st, acts = feed(BystanderTracker(), "r4", [
    ("민준", ["민준"], "태호", "repeated_target"), ("태호", ["태호"], "민준", "repeated_target")])
check("뒤바뀐 사건이 바로 고쳐짐 (가해 태호 / 피해 민준)", st["victim"] == "민준" and st["aggressors"] == ["태호"], str(st["aggressors"]) + " / " + str(st["victim"]))


# ----------------------------------------------------------------------------- 3~6. 대본 재생 (전체 경로)
def play(room, parts, lines, win=8):
    """lines: [(이름, 본문, 모듈A 점수[, has_image])]. 앱처럼 직전 7개를 context로 보낸다."""
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = BystanderTracker()
    T.HISTORY.clear(room)
    code = {p: f"P{i+1:02d}" for i, p in enumerate(parts)}        # 앱처럼 코드와 화면 이름을 따로 보낸다
    name = {c: p for p, c in code.items()}
    plist = [{"participant_code": c, "display_name": p} for p, c in code.items()]
    sent, log, t = [], [], 2000.0
    for k, row in enumerate(lines):
        who, text, cb = code[row[0]], row[1], row[2]
        img = len(row) > 3 and row[3]
        score[text] = cb
        t += 4
        new = {"participant_code": who, "text": text, "message_id": f"{room}_{k+1}", "timestamp": t}
        body = {"room_id": room, "context": sent[-(win - 1):], "new_message": new, "participants": plist,
                "has_image": bool(img), "track_bystander": True}
        T.set_request_context(NS(room_id=room, context=body["context"], new_message=new, participants=plist,
                                 has_image=bool(img), track_bystander=True))
        res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": m["timestamp"],
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [new]]
        tr.on_analyze(body, res, wins, now=t)
        a = res["attribution"]
        log.append((k + 1, name[who], text, a["is_bullying"], sorted(name[x] for x in a["aggressors"]),
                    name.get(a["victim"]), a["victim_reason"]))
        sent.append(new)
    st = tr.state(room)
    if st:                                    # 읽기 쉽게 코드를 이름으로 바꿔 돌려준다
        st["aggressors"] = sorted(name[x] for x in st["aggressors"])
        st["victim"] = name.get(st["victim"])
        for b_ in st["bystanders"]:
            b_["participant_code"] = name[b_["participant_code"]]
    return st, tr.drain(room, now=t), log


def show(log, st):
    for k, who, text, b, ag, v, why in log:
        if b:
            print(f"      {k:2d} {who} 「{text}」 -> 가해 {ag} 피해 {v} ({why})")
    if st:
        print(f"      최종: 가해 {st['aggressors']} / 피해 {st['victim']} ({st['victim_reason']}, {st['victim_status']})"
              f" / 주변인 {[(b['participant_code'], b['behavior']) for b in st['bystanders']]}")
    else:
        print("      최종: 사건 없음")


print("\n3) 언어적 폭력 — 같은 편이 맞장구 (22~36번은 보고된 대사, 1~21번은 가상)")
S1 = [("소연", "영상 편집 누가 했어?", .05), ("건우", "내가 했는데", .05), ("태민", "이게 뭐냐 진짜", .55),
      ("현우", "ㄹㅇ", .05), ("태민", "자막 다 틀렸잖아", .30), ("현우", "ㅇㅈ ㅋㅋ", .05), ("건우", "시간이 없었어", .05),
      ("태민", "변명하지 마라", .60), ("현우", "그니까", .05), ("소연", "다시 하면 되지", .05),
      ("태민", "아 답답해 죽겠네", .55), ("현우", "팩트", .05), ("현우", "다시 만들어야 할 듯", .20),
      ("태민", "발표 내일인데", .10), ("현우", "맞아 큰일남", .05), ("건우", "알았어", .05),
      ("태민", "알긴 뭘 알아", .50), ("현우", "ㅋㅋㅋ", .05), ("소연", "그만 싸워", .05), ("현우", "이건 좀 심했음", .30),
      ("건우", "미안", .05),
      ("태민", "개짜증나네", .90), ("현우", "ㅈㄹ하지 말고 다시 만들어", .90), ("소연", "얘들아", .05),
      ("태민", "발표 망함", .20), ("현우", "어떡하냐", .10), ("소연", "일단 진정해", .05),
      ("현우", "건우한테 맡기면 또 이럼", .70), ("건우", "왜 계속 나만 탓해", .55), ("태민", "니가 못했으니까", .70),
      ("현우", "ㅋㅋ 팩트", .10), ("건우", "진짜 그만하라고", .60), ("태민", "싫은데?", .40),
      ("태민", "영상 이상하면 다 니 탓임", .80), ("현우", "ㅇㅈ", .05), ("현우", "건우 때문에 망하겠네 ㅋㅋ", .80)]
st, acts, log = play("s1", ["태민", "현우", "건우", "소연"], S1)
show(log, st)
check("어느 판정에서도 현우가 피해자로 나오지 않음", all(v != "현우" for *_, b, ag, v, why in log if b))
check("건우의 항의가 공격으로 세어지지 않음 (건우는 가해자 아님)", all("건우" not in ag for *_, b, ag, v, why in log if b))
check("최종 사건: 가해 태민·현우 / 피해 건우", bool(st) and st["victim"] == "건우" and st["aggressors"] == ["태민", "현우"])
check("건우는 주변인(방어)으로 분류되지 않음", bool(st) and all(b["participant_code"] != "건우" for b in st["bystanders"]))

print("\n4) 배제 — 피해자가 방에 없고 같은 편이 맞장구 (가상 대본)")
S2 = [("지민", "도현이 또 숙제 안 해옴", .55), ("수아", "ㄹㅇ 맨날 그럼", .10), ("지민", "걔 진짜 짜증나", .70),
      ("수아", "맞아", .05), ("민재", "오늘 급식 뭐야", .05), ("지민", "도현이 빼고 하자", .60), ("수아", "ㅇㅈ 걔 빼자", .30),
      ("지민", "걔 오면 분위기 망함", .65), ("수아", "그니까 ㅋㅋ", .05), ("지민", "도현이는 부르지 마", .60), ("수아", "ㅇㅋ", .05)]
st, acts, log = play("s2a", ["지민", "수아", "민재", "도현"], S2)
show(log, st)
check("명단에 도현이 있으면: 피해자 = 도현, 수아 아님", bool(st) and st["victim"] == "도현")
st, acts, log = play("s2b", ["지민", "수아", "민재"], S2)
show(log, st)
check("명단에 도현이 없으면: 수아를 피해자로 잡지 않음", all(v != "수아" for *_, b, ag, v, why in log if b))

print("\n5) 시각적 폭력 — 피해자가 항의하고 가해자가 무마 (보고된 대사 3개 + 가상)")
S3 = [("유진", "", .05, True), ("하준", "ㅋㅋㅋㅋ 뭐야 이거", .05), ("서아", "야 그거 지워줘", .60),
      ("유진", "왜 ㅋㅋ 잘 나왔는데", .10), ("서아", "하지 말라고", .90), ("유진", "장난인데 왜 화냄?", .20),
      ("하준", "ㅋㅋㅋ 개웃겨", .10), ("서아", "지워 달라고", .80), ("유진", "예민하네", .30),
      ("지민", "유진아 그만해", .40), ("유진", "", .05, True), ("서아", "진짜 하지 마 제발", .85),
      ("유진", "장난이잖아 ㅋㅋ", .20), ("서아", "선생님한테 말할 거야", .30)]
st, acts, log = play("s3", ["유진", "서아", "지민", "하준"], S3)
show(log, st)
check("서아(피해자)가 가해자로 잡히지 않음", all("서아" not in ag for *_, b, ag, v, why in log if b))
check("유진(가해자)이 피해자로 잡히지 않음", all(v != "유진" for *_, b, ag, v, why in log if b))
check("사건이 열리면 가해 유진 / 피해 서아", (not st) or (st["aggressors"] == ["유진"] and st["victim"] == "서아"),
      "열림" if st else "안 열림")

print("\n6) 되돌아가지 않는지 — 서로 욕하는 장난, 같이 웃는 장난은 여전히 사건 아님")
S4 = [("A", "야 꺼져 ㅋㅋ", .95), ("B", "ㅋㅋㅋㅋ", .05), ("A", "병신아 ㅋㅋ", .95), ("B", "ㅋㅋㅋㅋㅋ 인정", .05),
      ("A", "역겨워 ㅋㅋ", .95), ("B", "아 하지마 ㅋㅋㅋ", .05), ("A", "꺼져라", .95), ("B", "ㅎㅎ", .05)]
st, acts, log = play("s4", ["A", "B"], S4)
check("같이 웃는 장난 -> 사건 없음", st is None)
S5 = [("A", "야 꺼져", .95), ("B", "니가 꺼져 병신아", .95), ("A", "역겨워", .95), ("B", "너나 역겹지", .95),
      ("A", "나가라", .95), ("B", "그만해 병신아", .95), ("A", "꺼져", .95), ("B", "너나 꺼져", .95)]
st, acts, log = play("s5", ["A", "B"], S5)
check("서로 욕하는 대화 -> 사건 없음", st is None)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
