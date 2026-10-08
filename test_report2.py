# -*- coding: utf-8 -*-
"""
v0.3.3 확인: 앱팀 2차 보고(2026-10-08)의 항목들. 모델 없이 실행된다.

    cd <withu 폴더를 담고 있는 폴더> && python withu/test_report2.py

모듈 A·B 점수는 대본에 적은 값을 쓴다 (실제 모델 점수가 아님). 대사는 보고에 인용된 것만 실제 대본의 대사이고
나머지는 가상으로 채운 것이다. 실제 대본 8편과 사용성 평가 대본은 test_scripts_live.py로 실서버에서 확인해야 한다.
"""
import os, sys, threading, time
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


def play(room, parts, lines, win=8, absent=(), classify=None, ctx_score=0.0):
    """lines: [(이름, 본문, 모듈A 점수[, has_image])]. 앱처럼 직전 7개를 context로 보낸다. absent: 명단에만 있는 아이."""
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: ctx_score)
    tr = BystanderTracker(classify=classify)
    T.HISTORY.clear(room)
    code = {p: f"P{i+1:02d}" for i, p in enumerate(list(parts) + list(absent))}
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
        log.append(NS(k=k + 1, who=name[who], text=text, bully=a["is_bullying"], aggr=sorted(name[x] for x in a["aggressors"]),
                      victim=name.get(a["victim"]), why=a["victim_reason"], support=a["victim_support"],
                      cb=res["cb_score"], typ=res["cb_type"]))
        sent.append(new)
    st = tr.state(room)
    if st:
        st["aggressors"] = sorted(name[x] for x in st["aggressors"])
        st["victim"] = name.get(st["victim"])
        st["previous_victims"] = [name.get(x) for x in st["previous_victims"]]
        for b_ in st["bystanders"]:
            b_["participant_code"] = name[b_["participant_code"]]
    return st, log


def show(log, st):
    for r in log:
        if r.bully:
            print(f"      {r.k:2d} {r.who} 「{r.text}」 -> 가해 {r.aggr} 피해 {r.victim} ({r.why}, {r.support})")
    if st:
        print(f"      최종: 가해 {st['aggressors']} / 피해 {st['victim']} ({st['victim_reason']}, {st['victim_status']})"
              f" / 이전 피해자 {st['previous_victims']} / 주변인 {[(b['participant_code'], b['behavior']) for b in st['bystanders']]}")
    else:
        print("      최종: 사건 없음")


# ------------------------------------------------------------------------------------------------ 4번
print("4) 사후검사 3 (시각적 폭력) — 목록에 없는 항의가 공격으로 세어져 서아가 가해자, 말린 지민이 피해자가 되던 문제")
S3 = [("유진", "", .05, True), ("하준", "ㅋㅋㅋㅋ 뭐야 이거", .05), ("서아", "야 그거 지워줘", .60),
      ("유진", "왜 ㅋㅋ 잘 나왔는데", .10), ("서아", "하지 말라고", .90), ("유진", "장난인데 왜 화냄?", .20),
      ("하준", "쫄았냐 ㅋㅋ", .30), ("서아", "하나도 안 귀여워", .85), ("유진", "예민하네", .30),
      ("지민", "야 진짜 다른 데 보내지 마", .40), ("하준", "내가 친구들 방에 보내줄까? ㅋㅋ", .30),
      ("서아", "웃기지 않아", .80), ("유진", "장난이잖아 ㅋㅋ", .20), ("지민", "그냥 지워", .30),
      ("서아", "진짜 싫어", .85), ("유진", "왜 이렇게 예민해", .30), ("지민", "본인이 싫으면 그만해야지", .55),
      ("서아", "제발 지워 줘", .70), ("유진", "싫은데?", .40)]
st, log = play("r4", ["유진", "서아", "지민", "하준"], S3)
show(log, st)
check("서아(피해자)가 어느 판정에서도 가해자로 잡히지 않음", all("서아" not in r.aggr for r in log if r.bully))
check("지민(말린 친구)이 어느 판정에서도 피해자로 잡히지 않음", all(r.victim != "지민" for r in log if r.bully))
check("최종 사건: 가해 유진 / 피해 서아", bool(st) and st["aggressors"] == ["유진"] and st["victim"] == "서아", str(st and (st["aggressors"], st["victim"])))
check("피해자가 한 번도 바뀌지 않음", bool(st) and st["previous_victims"] == [])
check("서아의 항의에는 전송 전 경고가 뜨지 않음 (cb_type 비해당)", all(r.typ == "비해당" for r in log if r.who == "서아"),
      str([(r.text, r.cb, r.typ) for r in log if r.who == "서아" and r.typ != "비해당"]))

# ------------------------------------------------------------------------------------------------ 7번
print("\n7) 추수검사 3 (시각적 폭력) — 피해자가 여러 번 항의해도 confirmed가 되지 않던 문제")
F3 = [("태호", "", .05, True), ("지아", "ㅋㅋㅋ 대박", .05), ("민준", "야 뭐야 지워", .50), ("태호", "잘 나왔는데 왜", .10),
      ("민준", "하지 말라고", .90), ("태호", "장난인데 왜 화냄?", .20), ("지아", "ㅋㅋㅋ 웃겨", .10),
      ("민준", "제발 지워", .60), ("태호", "예민하네", .30), ("민준", "저장하지 마", .70), ("태호", "이미 저장했는데 ㅋㅋ", .20),
      ("하은", "태호야 그만해", .30), ("민준", "하지 마", .85), ("태호", "장난이잖아", .20), ("민준", "진짜 싫어", .85)]
st, log = play("r7", ["태호", "민준", "지아", "하은"], F3)
show(log, st)
first = next((r.k for r in log if r.bully), None)
conf = next((r.k for r in log if r.bully and r.support == "strong"), None)
check("사건이 열림 (가해 태호 / 피해 민준)", bool(st) and st["aggressors"] == ["태호"] and st["victim"] == "민준")
check("민준이 2번 분명하게 항의한 뒤 confirmed", bool(st) and st["victim_status"] == "confirmed", f"열림 {first}번, strong {conf}번")
check("말린 하은이 피해자로 잡히지 않음", all(r.victim != "하은" for r in log if r.bully))

# ------------------------------------------------------------------------------------------------ 5번
print("\n5) 배제 — 방에 없는 피해자 (사후검사 2: 같은 편 수아가 피해자로 잡힘 / 추수검사 2: 사건이 열리지 않음)")
E2 = [("지민", "도현이 또 숙제 안 해옴", .30), ("수아", "걔 원래 그래", .10), ("지민", "우리끼리 방 새로 만들자", .10),
      ("수아", "어떻게 만들어", .05), ("지민", "도현이는 빼고 하자", .20), ("수아", "걔 빼자", .10), ("민재", "오늘 급식 뭐야", .05),
      ("지민", "걔 오면 분위기 망함", .65), ("수아", "근데 걔가 알면 어떡해", .10), ("지민", "도현이한테는 말하지 마", .55),
      ("수아", "알았어 비밀로 할게", .05), ("지민", "도현이 부르지 마 진짜", .40), ("수아", "나는 안 부를 거야", .05)]
st, log = play("r5a", ["지민", "수아", "민재"], E2, absent=["도현"])
show(log, st)
check("수아(같은 편)가 어느 판정에서도 피해자로 잡히지 않음", all(r.victim != "수아" for r in log if r.bully))
check("명단에 있는 도현이 피해자로 잡힘 (name_mention, confirmed)", bool(st) and st["victim"] == "도현" and st["victim_status"] == "confirmed",
      str(st and (st["victim"], st["victim_status"])))
check("배제 발화의 cb_type에 '배제'가 나옴", any("배제" in r.typ for r in log), str([(r.text, r.typ) for r in log][:6]))
F2 = [("도윤", "이번 조별 과제 누구랑 해", .05), ("서연", "우리 셋이 하자", .05), ("도윤", "재희는 빼고", .10), ("서연", "ㅇㅋ 재희는 빼고 하자", .10),
      ("지우", "왜?", .05), ("도윤", "걔랑 하면 맨날 늦어", .30), ("서연", "재희 없는 방 따로 만들까", .10), ("도윤", "ㅇㅇ 재희는 빼고 초대해", .10)]
st, log = play("r5b", ["도윤", "서연", "지우"], F2, absent=["재희"])
show(log, st)
check("모듈 A 점수가 모두 낮아도 사건이 열림 (가해 도윤·서연 / 피해 재희)",
      bool(st) and st["victim"] == "재희" and st["aggressors"] == ["도윤", "서연"], str(st and (st["aggressors"], st["victim"])))
st, log = play("r5c", ["도윤", "서연", "지우"], F2)                      # 명단에 재희가 없으면
check("명단에 없으면 사건이 열리지 않음 (같은 편을 피해자로 잡지 않음)", st is None)
OK2 = [("가", "민준이 빼고 다 왔어?", .05), ("나", "응 민준이만 안 옴", .05), ("가", "민준아 어디야", .05), ("민준", "가는 중", .05),
       ("나", "하늘이 생일 선물 뭐 살까", .05), ("가", "하늘이한테는 비밀이야", .05), ("나", "ㅇㅋ", .05)]
st, log = play("r5d", ["가", "나", "민준", "하늘"], OK2)
check("'민준이 빼고 다 왔어?', '하늘이한테는 비밀이야'는 사건 아님", st is None, str(st))

# ------------------------------------------------------------------------------------------------ 3번
print("\n3) 맥락 점수(모듈 B) — 대화가 짧을 때, 그리고 피해자의 평범한 말에 '언어적 폭력'이 붙던 문제")
calls = []
ens = Ensemble(message_scorer=lambda t: {"하지 말라고": .30, "오늘 급식 맛있었어": .02, "너 진짜 짜증나": .60}.get(t, .05),
               context_scorer=lambda w, spk=None: calls.append((list(w), spk)) or 0.998)
def one(text, ctx=(), img=False, track=False, who="P1"):
    new = {"participant_code": who, "text": text, "message_id": "x"}
    body = {"room_id": "r3", "context": list(ctx), "new_message": new, "has_image": img, "track_bystander": track}
    T.set_request_context(NS(room_id="r3", context=body["context"], new_message=new, participants=[], has_image=img, track_bystander=track))
    return ens.analyze(body)
r = one("하지 말라고")
check("방의 첫 메시지 '하지 말라고' -> 비해당, 맥락 점수는 계산하지 않음(null)", r["cb_type"] == "비해당" and r["module_scores"]["context"] is None, str(r["module_scores"]))
r = one("[사진]", img=True)
check("방의 첫 메시지 사진 -> 비해당, cb_score 0", r["cb_type"] == "비해당" and r["cb_score"] == 0.0, str(r["cb_score"]))
long_ctx = [{"participant_code": f"P{i%3+1}", "text": f"말 {i}", "message_id": f"c{i}"} for i in range(8)]
r = one("지금 너무 늦어서", ctx=long_ctx, who="P3")
check("맥락 0.998이어도 평범한 말('지금 너무 늦어서')은 비해당, cb_score는 메시지 점수 그대로",
      r["cb_type"] == "비해당" and r["cb_score"] == 0.05 and r["module_scores"]["context"] == 0.998, f"{r['cb_score']} {r['cb_type']}")
r = one("너 진짜 짜증나", ctx=long_ctx)
check("메시지 자체가 공격 쪽(0.60)이면 맥락이 점수를 올림 -> 언어적 폭력", r["cb_type"] == "언어적 폭력" and r["cb_score"] >= 0.75, str(r["cb_score"]))
check("모듈 B에 최근 6개만, 발화자를 구분해서 넘김", len(calls[-1][0]) == 6 and calls[-1][1] and len(set(calls[-1][1])) > 1, str(calls[-1]))

# ------------------------------------------------------------------------------------------------ 2번
print("\n2) 본문이 빈 메시지")
def strict_scorer(t):
    assert t and t.strip(), "모듈 A에 빈 본문이 들어옴"
    return 0.05
ens = Ensemble(message_scorer=strict_scorer, context_scorer=lambda w: (_ for _ in ()).throw(AssertionError("빈 본문")) if any(not x for x in w) else 0.0)
try:
    r = one("", ctx=[{"participant_code": "P2", "text": "", "message_id": "c1"}, {"participant_code": "P2", "text": None, "message_id": "c2"},
                     {"participant_code": "P1", "text": "뭐야", "message_id": "c3"}, {"participant_code": "P2", "text": "[사진]", "message_id": "c4"}], img=True)
    check("new_message와 context에 \"\"·null·\"[사진]\"이 있어도 오류 없이 판정", r["cb_score"] == 0.0 and r["cb_type"] == "비해당")
except Exception as e:
    check("빈 본문 처리", False, repr(e))

# ------------------------------------------------------------------------------------------------ 1번
print("\n1) 전송 전 호출에서는 LLM을 부르지 않음")
llm_calls = []
ens = Ensemble(message_scorer=lambda t: 0.95, context_scorer=lambda w: 0.0,
               bystander_fn=lambda c, s, t, logs=None: llm_calls.append(t) or {"behavior": "비해당"})
r = one("꺼져 진짜", track=False)
check("cb_score 0.95, track_bystander=false -> LLM 호출 0번", r["cb_score"] >= 0.75 and llm_calls == [], str(llm_calls))

# ------------------------------------------------------------------------------------------------ 6번
print("\n6) 주변인 발화 판정 — LLM이 답하지 못해도 판정이 남고, LLM을 기다리는 동안 서버가 멈추지 않음")
V4 = [("수빈", "하린 너 진짜 눈치 없다", .80), ("하린", "왜 그래", .10), ("예나", "하린이 빼고 방 만들자", .30),
      ("수빈", "하린이는 빼고 하자 짜증나", .85), ("준영", "하린이 빼고 만드는 건 아닌 것 같은데", .20), ("예나", "하린 진짜 답답해", .80),
      ("지호", "ㅋㅋㅋ 인정", .05)]
st, log = play("r6a", ["수빈", "하린", "예나", "준영", "지호"], V4, classify=lambda ctx, spk, txt: None)   # LLM이 매번 실패
show(log, st)
by = {b["participant_code"]: b for b in (st or {}).get("bystanders", [])}
check("LLM 실패 -> 규칙으로 판정: 준영 방어", by.get("준영", {}).get("behavior") == "방어", str(by.get("준영")))
check("LLM 실패 -> 규칙으로 판정: 지호 동조", by.get("지호", {}).get("behavior") == "동조", str(by.get("지호")))
check("history에 판정 출처가 남음 (발화(규칙))", any("규칙" in h["event"] for h in by.get("준영", {}).get("history", [])))
seen_roles = []
st, log = play("r6b", ["수빈", "하린", "예나", "준영", "지호"], V4,
               classify=lambda ctx, spk, txt: seen_roles.append((spk, [s for s, _ in ctx])) or ("방어" if "아닌 것" in txt else "동조"))
by = {b["participant_code"]: b for b in (st or {}).get("bystanders", [])}
check("LLM 정상 -> 준영 방어 / 지호 동조, history에 발화(LLM)", by.get("준영", {}).get("behavior") == "방어" and by.get("지호", {}).get("behavior") == "동조"
      and any("LLM" in h["event"] for h in by["준영"]["history"]))
check("LLM은 주변인 발화에만 불림 (가해자·피해자 메시지에는 안 불림)", bool(seen_roles) and all("주변인" in s for s, _ in seen_roles), str(seen_roles))
check("LLM에 역할 표시가 붙은 맥락이 넘어감", any("(가해자)" in x for _, c in seen_roles for x in c))

# 잠금: 느린 LLM이 도는 동안 다른 방의 조회가 막히지 않는다
tr = BystanderTracker(classify=lambda c, s, t: (time.sleep(1.0), "방어")[1])
def open_incident(room):
    for k, (who, cb) in enumerate([("A", .9), ("A", .9)]):
        tr.on_analyze({"room_id": room, "new_message": {"participant_code": who, "text": "x"}, "context": []},
                      {"attribution": {"is_bullying": True, "aggressors": ["A"], "victim": "V", "victim_reason": "name_mention"}},
                      [{"message_id": f"{room}{k}", "speaker": who, "ts": time.time(), "cb": cb}])
open_incident("slow")
th = threading.Thread(target=lambda: tr.on_analyze(
    {"room_id": "slow", "new_message": {"participant_code": "B", "text": "그만해"}, "context": []}, {"attribution": {}},
    [{"message_id": "sb", "speaker": "B", "ts": time.time(), "cb": 0.1}]))
th.start(); time.sleep(0.2)
t0 = time.time(); tr.drain("other"); tr.tick(); waited = time.time() - t0
th.join()
check("LLM 대기 중에도 /bystander/actions·타이머가 바로 응답", waited < 0.2, f"{waited:.2f}s")
check("기다린 뒤 판정은 정상 반영 (B 방어)", tr.state("slow", "B")["bystanders"][0]["behavior"] == "방어")

# ------------------------------------------------------------------------------------------------ 피해자 확정 뒤 흔들림
print("\n+) 확정된 피해자는 약한 근거 한 번으로 바뀌지 않음")
tr = BystanderTracker()
def feed(room, verdicts):
    t = 1000.0
    for k, (spk, aggr, vic, why, sup) in enumerate(verdicts):
        t += 5
        tr.on_analyze({"room_id": room, "new_message": {"participant_code": spk, "text": "x"}, "context": []},
                      {"attribution": {"is_bullying": True, "aggressors": aggr, "victim": vic, "victim_reason": why, "victim_support": sup}},
                      [{"message_id": f"{room}{k}", "speaker": spk, "ts": t, "cb": 0.9}], now=t)
    return tr.state(room)
st = feed("c1", [("유진", ["유진"], "서아", "repeated_target", "weak"), ("유진", ["유진"], "서아", "repeated_target", "strong"),
                 ("유진", ["유진", "서아"], "지민", "repeated_target", "weak")])
check("항의로 확정된 서아가 '가해자' 판정 한 번에 바뀌지 않음", st["victim"] == "서아" and st["victim_status"] == "confirmed", str((st["victim"], st["victim_status"])))
check("확정된 피해자는 가해자 목록에 들어가지 않음", "서아" not in st["aggressors"], str(st["aggressors"]))
st = feed("c2", [("민준", ["민준"], "태호", "repeated_target", "weak"), ("태호", ["태호"], "민준", "repeated_target", "weak")])
check("확정 전에는 뒤바뀐 사건이 바로 고쳐짐 (0.3.2 동작 유지)", st["victim"] == "민준" and st["aggressors"] == ["태호"])

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
