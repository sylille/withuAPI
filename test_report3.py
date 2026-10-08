# -*- coding: utf-8 -*-
"""
v0.3.5 확인: 앱팀 3차 보고(2026-10-08, 재현 요청 순서 JSON 9편)의 항목들. 모델 없이 실행된다.

    python test_report3.py          # withu 폴더가 있는 곳에서

모듈 A 점수는 대본에 적은 값이다 (실제 모델 점수가 아님). 대사는 앱팀 보고에 인용된 여섯 줄만 실제 대본의 대사이고 나머지는
같은 짜임으로 새로 쓴 가상의 대사다 (검사 대본은 저장소에 넣지 않는다). 실제 대본 9편은 test_scripts_live.py로 실서버에서 확인한다.
"""
import os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


def play(room, parts, lines, win=11, silent=(), judge=None):
    """lines: [(이름, 본문, 모듈A 점수)]. 앱처럼 직전 10개를 context로 보낸다. silent: 명단에만 있고 말하지 않는 아이."""
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = BystanderTracker()
    T.HISTORY.clear(); T.ROSTERS.clear(); T._JUDGED.clear(); T.set_exclusion_judge(judge)
    code = {p: f"P{i+1:02d}" for i, p in enumerate(list(parts) + list(silent))}
    name = {c: p for p, c in code.items()}
    plist = [{"participant_code": c, "display_name": p} for p, c in code.items()]
    sent, log, t = [], [], 3000.0
    for k, (who, text, cb) in enumerate(lines):
        score[text] = cb
        t += 4
        new = {"participant_code": code[who], "text": text, "message_id": f"{room}_{k+1}", "timestamp": t}
        body = {"room_id": room, "context": sent[-(win - 1):], "new_message": new, "participants": plist,
                "has_image": False, "track_bystander": True}
        T.set_request_context(NS(room_id=room, context=body["context"], new_message=new, participants=plist,
                                 has_image=False, track_bystander=True))
        res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": m["timestamp"],
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [new]]
        st = tr.on_analyze(body, res, wins, now=t)
        a = res["attribution"]
        log.append(NS(k=k + 1, who=who, text=text, bully=a["is_bullying"], aggr=sorted(name[x] for x in a["aggressors"]),
                      victim=name.get(a["victim"]), why=a["victim_reason"], support=a["victim_support"], typ=res["cb_type"],
                      attack=new["message_id"] in a["attack_message_ids"], mid=new["message_id"], attack_ids=a["attack_message_ids"],
                      inc_victim=name.get(st["victim"]) if st else None, inc_status=st["victim_status"] if st else None))
        sent.append(new)
    st = tr.state(room)
    if st:
        st["aggressors"] = sorted(name[x] for x in st["aggressors"])
        st["victim"] = name.get(st["victim"])
        st["previous_victims"] = [name.get(x) for x in st["previous_victims"]]
        st["bystanders"] = {name[b["participant_code"]]: b["behavior"] for b in st["bystanders"]}
    T.set_exclusion_judge(None)
    return st, log


def show(log, st):
    for r in log:
        if r.bully:
            print(f"      {r.k:2d} {r.who} 「{r.text}」 -> 가해 {r.aggr} 피해 {r.victim} ({r.why}, {r.support})")
    print("      최종: " + (f"가해 {st['aggressors']} / 피해 {st['victim']} ({st['victim_reason']}, {st['victim_status']})"
                          f" / 이전 피해자 {st['previous_victims']} / 주변인 {st['bystanders']}" if st else "사건 없음"))


# ------------------------------------------------------------------------------------------------ 1번
print("1) 사용성 평가 — 이름이 안 나오고 피해자의 항의가 목록에 없는 말이라 사건이 열리지 않던 문제")
# 인용된 대사: 지랄이야(0.86), ㅇㅈ나대지마라 ㅈㅉ(0.93), 아니 갑자기, 왜 급발진?, 너무 한거 아니야?
U1 = [("수진", "아 진짜 존나 심심해", .92), ("도윤", "뭐래", .05), ("수진", "아무나 나와", .05), ("도윤", "ㅋ", .05),
      ("지아", "이제 늦었어", .05), ("지아", "다들 잘 시간이야", .05),
      ("수진", "야", .05), ("수진", "니가 뭔 상관인데", .30), ("수진", "지랄이야", .86), ("수진", "잠이나 쳐 자", .90),
      ("도윤", "ㅋㅋㅋ", .05), ("도윤", "지아는 범생이^^", .30), ("수진", "착한 척 쩐다", .30),
      ("지아", "아니 갑자기", .05), ("지아", "왜 급발진?", .05), ("지아", "한 마디 한 건데", .05), ("지아", "너무 한거 아니야?", .20),
      ("수진", "너 원래도", .05), ("수진", "별로였음", .30), ("수진", "설치지 마", .90), ("도윤", "ㅇㅈ나대지마라 ㅈㅉ", .93)]
st, log = play("u1", ["수진", "도윤", "지아"], U1, silent=["아동"])
show(log, st)
opened = next((r for r in log if r.inc_victim), None)
conf = next((r for r in log if r.inc_status == "confirmed"), None)
check("사건이 열림 (가해 수진 / 피해 지아)", bool(st) and st["aggressors"] == ["수진"] and st["victim"] == "지아", str(st))
check("근거는 2인칭 지목(direct_address)", bool(st) and st["victim_reason"] == "direct_address", str(st and st["victim_reason"]))
check("지아가 항의하기 시작한 줄('왜 급발진?')에서 열림", opened is not None and opened.text == "왜 급발진?", str(opened and opened.text))
check("'너무 한거 아니야?'에서 confirmed", conf is not None and conf.text == "너무 한거 아니야?" and conf.inc_victim == "지아", str(conf and conf.text))
check("도윤(동조)이 피해자로 잡히지 않음", all(r.inc_victim != "도윤" for r in log), str([r.k for r in log if r.inc_victim == "도윤"]))
check("도윤은 가해자가 아니라 동조한 주변인", bool(st) and st["bystanders"].get("도윤") == "동조", str(st and st["bystanders"]))
jiral = next(r.mid for r in log if r.text == "지랄이야")
check("사건이 열린 뒤 '지랄이야'가 attack_message_ids에 들어감", jiral in log[-1].attack_ids, str(log[-1].attack_ids))
check("지아의 항의에는 cb_type이 붙지 않음", all(r.typ == "비해당" for r in log if r.who == "지아"))

# 2인칭 지목이 엉뚱한 아이를 잡지 않는지
A1 = [("가", "아 존나 피곤해", .92), ("나", "ㅋㅋ 왜", .05), ("가", "너 숙제 했냐", .05), ("나", "아니", .05),
      ("가", "개망했네 진짜", .90), ("나", "나도", .05)]
st, log = play("a1", ["가", "나", "다"], A1)
check("혼잣말 욕 + '너 숙제 했냐' (공격 아님)는 사건 아님", st is None, str(st))
A2 = [("가", "너 진짜 못한다", .80), ("가", "니가 다 망쳤어", .85), ("나", "ㅋㅋㅋ 인정", .05), ("가", "한심하다", .80), ("나", "ㄹㅇ", .05)]
st, log = play("a2", ["가", "나", "다"], A2)
check("2인칭 공격이 있어도 맞장구만 친 아이는 피해자가 아님", st is None or st["victim"] != "나", str(st))
A3 = [("가", "야 다 뭐하냐", .05), ("나연", "게임", .05), ("다", "그만 좀 싸워", .05),
      ("가", "넌 좀 꺼져", .92), ("가", "니가 뭘 알아", .80), ("다", "나연이한테 그러지 마", .10), ("가", "너나 잘해", .70)]
st, log = play("a3", ["가", "나연", "다"], A3)
check("말리는 아이('○○한테 그러지 마')는 2인칭으로 지목돼도 confirmed 피해자가 아님",
      st is None or st["victim_status"] != "confirmed" or st["victim"] != "다", str(st))

# ------------------------------------------------------------------------------------------------ 2번
print("\n2) 추수검사 1 — 확정된 피해자(다솜)가 '지민이는 끼지 마' 한 줄에 지민으로 바뀌던 문제")
F1 = [("유나", "다솜아 있잖아", .05), ("유나", "너 발표 연습한 거 들어봤어", .10), ("채원", "나도 ㅋㅋ", .05),
      ("다솜", "열 번은 해 본 건데", .05), ("유나", "니 때문에 우리 조 다 망하겠다", .70), ("채원", "ㄹㅇ", .05),
      ("다솜", "그렇게 말하지 마", .60), ("채원", "다솜은 맨날 틀림", .80), ("다솜", "그만해", .70), ("다솜", "속상해", .30),
      ("유나", "왜 이렇게 예민해", .60), ("채원", "ㅈㄹ 말고 다시 해", .92),
      ("지민", "어디가 틀렸는지 알려 주면 되잖아", .05),
      ("유나", "지민이는 끼지 마", .60), ("유나", "얘가 틀려서 그러는 거야", .40), ("채원", "맞아", .05),
      ("채원", "다솜한테 말해도 소용없음", .60), ("다솜", "왜 나한테만 그래", .30), ("유나", "니가 제일 틀리니까", .70),
      ("다솜", "진짜 그만하라고", .70)]
st, log = play("f1", ["유나", "채원", "다솜", "지민"], F1, silent=["아동"])
show(log, st)
check("최종 사건: 가해 유나·채원 / 피해 다솜 (confirmed)",
      bool(st) and st["aggressors"] == ["유나", "채원"] and st["victim"] == "다솜" and st["victim_status"] == "confirmed", str(st))
check("피해자가 한 번도 바뀌지 않음", bool(st) and st["previous_victims"] == [], str(st and st["previous_victims"]))
check("어느 판정에서도 지민이 피해자로 나오지 않음", all(r.victim != "지민" for r in log if r.bully), str([r.k for r in log if r.bully and r.victim == "지민"]))
check("다솜이 주변인(방어)으로 바뀌지 않음", bool(st) and "다솜" not in st["bystanders"], str(st and st["bystanders"]))
check("'지민이는 끼지 마'에 cb_type '배제'가 붙지 않음", all("배제" not in r.typ for r in log if "끼지 마" in r.text),
      str([(r.text, r.typ) for r in log if "끼지 마" in r.text]))
check("'그렇게 말하지 마'는 항의 (점수가 높아도 공격으로 세지 않음)", all("다솜" not in r.aggr for r in log if r.bully))

# 같은 대본, 점수가 낮은 경우: '끼지 마'가 규칙으로 공격이 되어도 지민을 가리키지 않는다
F1_low = [(w, t, (c if c >= .9 else min(c, .3))) for w, t, c in F1]
st, log = play("f1b", ["유나", "채원", "다솜", "지민"], F1_low, silent=["아동"])
check("점수가 낮아도 지민이 피해자로 잡히지 않음", all(r.inc_victim != "지민" for r in log), str(st))

# '끼지 마'가 진짜 배제인 경우는 그대로 잡는다
X1 = [("가", "주말에 놀이공원 갈 사람", .05), ("나", "나", .05), ("가", "민서는 끼지 마 우리끼리 갈 거야", .10), ("나", "ㅇㅇ 민서는 빼고", .05),
      ("가", "민서는 부르지 마", .05)]
st, log = play("x1", ["가", "나", "다"], X1, silent=["민서"])
check("말하지 않은 아이에게 한 '○○는 끼지 마'는 배제 발화로 셈", bool(st) and st["victim"] == "민서", str(st))
check("  cb_type에 '배제'", any("배제" in r.typ for r in log if "끼지 마" in r.text))

# 배제 표현 한 번이 다른 후보를 지우지 않는다 (피해자가 따로 있고, 말리던 아이가 배제 표현으로 불린 경우)
X2 = [("가", "하늘이 진짜 못생겼다", .85), ("하늘", "하지 마", .40), ("가", "하늘이 냄새남", .85), ("하늘", "그만해", .40),
      ("다", "왜 그래 갑자기", .05), ("다", "놀이터나 가자", .05), ("나", "ㅋㅋ", .05), ("나", "근데 숙제 했어?", .05), ("나", "나 아직", .05),
      ("가", "다온이는 부르지 마", .10), ("가", "하늘이 너 진짜 싫어", .85)]
st, log = play("x2", ["가", "나", "하늘", "다온"], [(("다온" if w == "다" else w), t, c) for w, t, c in X2])
check("이름으로 지목되고 항의한 피해자(하늘)가 배제 표현 한 번에 밀려나지 않음", bool(st) and st["victim"] == "하늘" and st["previous_victims"] == [], str(st))

# ------------------------------------------------------------------------------------------------ 3번
print("\n3) 배제 대본의 공동 가해자 — 욕설 없이 배제를 이어 가는 아이가 '동조한 주변인'으로 나오던 문제")
E1 = [("지민", "도현이 아까 봤어?", .05), ("지민", "또 남 얘기에 끼어듦 ㅋ", .30), ("수아", "봤어 ㅋㅋ", .05), ("수아", "분위기 파악 못 함", .30),
      ("민재", "진짜?", .05), ("지민", "ㄹㅇ 관종", .92), ("민재", "그건 좀;;", .05), ("지민", "일요일에 자전거 타러 갈 사람", .05),
      ("지민", "도현이는 빼고", .05), ("수아", "나 갈래", .05), ("수아", "걔 오면 재미없어짐", .30),
      ("민재", "도현이한테는", .05), ("민재", "뭐라 그래?", .05), ("지민", "말하지 마", .20),
      ("수아", "방 새로 파서 거기서 정하자", .05), ("지민", "ㅇㅇ 도현이 없는 방으로", .05), ("민재", "음", .05),
      ("수아", "걔한테 들키면 피곤해", .05), ("지민", "우리끼리 가자", .05), ("수아", "도현이한테 절대 말하지 마", .05)]
st, log = play("e1", ["지민", "수아", "민재"], E1, silent=["도현", "아동"])
show(log, st)
check("최종 사건: 가해 지민·수아 / 피해 도현 (confirmed)",
      bool(st) and st["aggressors"] == ["수아", "지민"] and st["victim"] == "도현" and st["victim_status"] == "confirmed", str(st))
check("수아가 주변인 목록에 남지 않음", bool(st) and "수아" not in st["bystanders"], str(st and st["bystanders"]))
check("민재(주변인)는 가해자도 피해자도 아님", bool(st) and "민재" not in st["aggressors"] and all(r.inc_victim != "민재" for r in log))
check("'그건 좀;;'은 말리기, 'ㅇㅇ'는 맞장구", T.stance("그건 좀;;") == "defend" and T.stance("ㅇㅇ 바로 그럼") == "agree")
check("'걔한테 들키면 피곤해'는 말리기가 아님", T.stance("걔한테 들키면 피곤해") != "defend" and T.stance("걔한테 왜 그래") == "defend")
check("'○○한테 절대 말하지 마'도 배제 발화", T._EXCLUDE.search("하늘이한테 절대 말하지 마") is not None)

# 정당한 목적(LLM이 '정당'으로 본 배제 발화) 뒤의 "새 방 만들자"는 배제로 이어 세지 않는다
OK1 = [("가", "토요일이 민서 생일이래", .05), ("나", "선물 뭐 사지", .05), ("가", "민서한테는 말하지 마 깜짝 파티 할 거야", .05),
       ("나", "ㅇㅋ 방 새로 파서 정하자", .05), ("가", "우리끼리 몰래 준비하자", .05), ("나", "들키면 안 됨 ㅋㅋ", .05)]
st, log = play("ok1", ["가", "나", "다"], OK1, silent=["민서"], judge=lambda ctx, spk, txt: False)
check("깜짝 파티 준비(LLM: 정당) 뒤의 '방 새로 파자', '몰래'는 사건 아님", st is None, str(st))
OK2 = [("가", "오늘 뭐 하고 놀까", .05), ("나", "방 새로 파서 게임 얘기 하자", .05), ("가", "우리끼리 하자", .05), ("나", "몰래 가자 ㅋㅋ", .05)]
st, log = play("ok2", ["가", "나", "다"], OK2)
check("배제 발화 없이 '새 방', '우리끼리'만 있으면 사건 아님", st is None, str(st))

# ------------------------------------------------------------------------------------------------ 말리던 아이
print("\n+) 말리던 아이를 막는 말('○○는 빠져', '○○아 그냥 놔둬') — 그 아이는 피해자가 아니다")
D1 = [("태민", "건우는 진짜 손이 느림", .30), ("건우", "그만해", .30), ("태민", "개짜증나", .92), ("현우", "ㅈㄹ 말고 다시 해 와", .92),
      ("소연", "어디를 고치면 되는지만 말해", .05), ("태민", "소연이는 좀 빠져 있어", .90), ("태민", "얘가 못해서 그러는 거임", .30),
      ("건우", "왜 계속 나만 탓해", .20), ("태민", "니가 못했으니까", .30), ("현우", "건우 때문에 다 틀렸네 ㅋㅋ", .70)]
st, log = play("d1", ["태민", "현우", "건우", "소연"], D1)
show(log, st)
check("소연(말린 아이)이 어느 판정에서도 피해자가 아님", all(r.victim != "소연" for r in log if r.bully) and all(r.inc_victim != "소연" for r in log),
      str([(r.k, r.victim) for r in log if r.bully]))
check("최종 피해자는 건우", bool(st) and st["victim"] == "건우", str(st))
D2 = [("가", "너 진짜 답답하다", .80), ("나", "하지 마", .30), ("가", "넌 빠져", .85), ("가", "나은이는 빠져 진짜", .85), ("나", "그만하라고", .30)]
st, log = play("d2", ["가", "나은", "다"], [(("나은" if w == "나" else w), t, c) for w, t, c in D2])
check("피해자 본인에게 한 '○○는 빠져'는 지목으로 셈 (항의한 아이)", bool(st) and st["victim"] == "나은", str(st))

# ------------------------------------------------------------------------------------------------ 한참 전에 말한 아이
print("\n+) 한참 전에 몇 마디 한 아이가 나중에 시작된 공격의 피해자로 잡히지 않음")
S1 = ([("가", "아 존나 심심해", .92), ("나", "뭐야", .05), ("가", "개노잼", .90), ("나", "몰라", .05), ("가", "존나 할 거 없네", .92)]
      + [("가", "ㅎ", .05)] * 18 + [("다", "늦었으니까 자자", .05), ("가", "지랄", .90)])
st, log = play("s1", ["가", "나", "다"], S1)
check("앞부분에서만 말한 아이는 피해자로 잡히지 않음", all(r.inc_victim != "나" for r in log[-3:]) and all(r.victim != "나" for r in log[-2:] if r.bully), str(st))

# ------------------------------------------------------------------------------------------------ 새 규칙이 지나치지 않은지
print("\n+) 새 규칙의 경계 (다른 검토에서 나온 반례)")
# 배제당하는 아이는 말이 없고 옆에서 말린 아이가 여러 번 항의한 경우: 피해자는 배제당한 아이
G1 = [("가", "하늘이는 빼고 하자", .05), ("다", "그만해", .05), ("가", "하늘이 부르지 마", .05), ("다", "하지 마", .05),
      ("가", "하늘이 없는 방 만들자", .05), ("다", "그만하라고", .05), ("다", "하지 말라고", .05)]
st, log = play("g1", ["가", "나", "다"], G1, silent=["하늘"])
check("배제 발화가 가리킨 아이가 피해자, 말린 아이는 아님", bool(st) and st["victim"] == "하늘", str(st))
# 끼워 달라는 아이에게 한 "끼지 마"는 배제
G2 = [("가", "술래잡기 할 사람", .05), ("하늘", "나도 할래", .05), ("가", "하늘이는 끼지 마 우리끼리 할 거야", .05), ("나", "ㅇㅇ", .05), ("가", "하늘이는 빼고", .05)]
st, log = play("g2", ["가", "나", "하늘"], G2)
check("'나도 할래' 뒤의 '○○는 끼지 마 우리끼리 할 거야'는 배제", bool(st) and st["victim"] == "하늘"
      and any("배제" in r.typ for r in log if "끼지 마" in r.text), str(st))
G2b = [("가", "술래잡기 할 사람", .05), ("하늘", "나도 할래", .05), ("가", "하늘이는 끼지 마", .05), ("나", "ㅇㅇ", .05), ("가", "하늘이는 빼고 하자", .05)]
st, log = play("g2b", ["가", "나", "하늘"], G2b)
check("  공격이 없던 자리의 '○○는 끼지 마'도 배제", bool(st) and st["victim"] == "하늘", str(st))
# 욕설이 섞인 "○○는 빠져"는 지목
G3 = [("하늘", "나도 같이 가자", .05), ("가", "하늘이는 빠져 찐따", .90), ("하늘", "응..", .05), ("가", "하늘이 넌 빠져 냄새나", .90)]
st, log = play("g3", ["가", "나", "하늘"], G3)
check("욕설이 섞인 '○○는 빠져'는 그 아이를 지목한 것", bool(st) and st["victim"] == "하늘" and st["victim_reason"] == "name_mention", str(st))
# 배제를 이어 가는 말: 말리는 말·상관없는 말은 세지 않고, 끝없이 이어지지 않는다
G4 = [("가", "하늘이는 빼고 하자", .05), ("다", "왜 우리끼리만 해 하늘이도 부르자", .05), ("다", "몰래 그러는 거 치사해", .05), ("나", "게임방 만들었어 들어와", .05)]
st, log = play("g4", ["가", "나", "다"], G4, silent=["하늘"])
pr = T.prepare([{"speaker": w, "text": t, "cb": c} for w, t, c in G4], roster={w: T.name_pattern(T.name_tokens(w)) for w in ["가", "나", "다", "하늘"]})
check("말리는 아이의 '왜 우리끼리만 해', 상관없는 '방 만들었어'는 배제 발화가 아님", [d.get("note") for d in pr[1:]] == [None, None, None], str([d.get("note") for d in pr]))
G5 = [("가", "하늘이는 빼고 하자", .05), ("나", "ㅇㅇ", .05)] + [("나", "우리끼리 가자" if k % 8 == 7 else f"말 {k}", .05) for k in range(40)]
pr = T.prepare([{"speaker": w, "text": t, "cb": c} for w, t, c in G5], roster={w: T.name_pattern(T.name_tokens(w)) for w in ["가", "나", "하늘"]})
late = [i for i, d in enumerate(pr) if d.get("note") == "exclusion_talk" and i > 12]
check("이어 가는 말은 이름 있는 배제 발화에서 8개 안까지만", late == [], str(late))
# 넓어진 표현이 욕설을 가리지 않는다
for t in ["너 너무 하찮아", "그건 좀 니 얼굴이 문제", "니 얼굴 좀 그렇다", "급발진 하네 미친"]:
    check(f"'{t}'는 말리기·항의가 아님", T.stance(t) not in ("defend", "protest"), T.stance(t))
for t, want in [("너무 한거 아니야?", "defend"), ("그건 좀;;", "defend"), ("그건 좀 아니지", "defend"), ("왜 급발진?", "protest"),
                ("나한테 너무한 거 아니야?", "protest"), ("그건 좀 이따 하자", "neutral"), ("너무 하고 싶다", "neutral")]:
    check(f"'{t}' -> {want}", T.stance(t) == want, T.stance(t))
check("'나한테 너무한 거 아니야?'는 분명한 항의", T.is_hard_protest("나한테 너무한 거 아니야?"))
for t in ["너튜브에서 봤어", "너구리 귀엽다", "넌센스 퀴즈", "널뛰기 했어", "너무 웃겨", "너희 뭐해", "아니 그게", "뭐니 그게"]:
    check(f"2인칭 아님: '{t}'", not T._SECOND.search(t))
for t in ["너 원래도", "니가 뭔 상관인데", "넌 안 해도 돼", "다 니 탓이야", "너한테 말 안 했어", "니 차례 때문에", "너 때문이라는 생각은 안 해?"]:
    check(f"2인칭: '{t}'", bool(T._SECOND.search(t)))
# 말리다 되받은 주변인: 공격에서 이름으로 불린 아이가 따로 있으면 2인칭 지목을 쓰지 않는다
G7 = [("가", "하늘이 진짜 냄새나", .90), ("다", "야 그만해", .05), ("가", "넌 뭔데 닥쳐", .90), ("다", "그만하라고", .05)]
st, log = play("g7", ["가", "나", "다"], G7, silent=["하늘"])
check("말리다 '넌 뭔데'를 들은 아이가 2인칭 지목으로 피해자가 되지 않음",
      all(not (r.bully and r.victim == "다" and r.why == "direct_address") for r in log) and (st is None or st["victim"] != "다" or st["victim_status"] != "confirmed"),
      str([(r.k, r.victim, r.why) for r in log if r.bully]))
# 공격 하나로는 열리지 않는다
G8 = [("나", "나 왔어", .05), ("가", "너 진짜 냄새나", .90), ("나", "왜 그래", .05), ("나", "하지마", .05)]
st, log = play("g8", ["가", "나", "다"], G8)
check("2인칭 공격 1개 + 항의만으로는 사건이 열리지 않음", st is None, str(st))

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
