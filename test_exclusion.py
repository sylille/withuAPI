# -*- coding: utf-8 -*-
"""
v0.3.4 확인: 배제 탐지 1단계 — C1 발화 확인(LLM)과 C2 방 구조(부분 방). 모델·LLM 없이 실행된다.

    python test_exclusion.py          # withu 폴더가 있는 곳에서

모듈 A 점수와 LLM의 답은 대본에 적은 값이다 (실제 모델·LLM이 아님). 대사는 모두 가상이다.
"""
import os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble

fails = 0
CODE = {n: f"S{i+1:02d}" for i, n in enumerate(["지민", "수아", "민재", "도현", "하늘", "가온", "나래", "다솜"])}   # 아이마다 코드는 방이 달라도 같다
NAME = {c: n for n, c in CODE.items()}


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


def roster(names):
    return [{"participant_code": CODE[n], "display_name": n} for n in names]


def open_room(room, names):
    """앱이 그 방에서 메시지를 한 번이라도 보내면 서버가 명단을 알게 된다."""
    T.ROSTERS.update(room, roster(names))


def play(room, names, lines, tracker=None):
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = tracker or BystanderTracker()
    T.HISTORY.clear(room)
    plist = roster(names)
    sent, log, t = [], [], 3000.0
    for k, (who, text, cb) in enumerate(lines):
        score[text] = cb
        t += 4
        new = {"participant_code": CODE[who], "text": text, "message_id": f"{room}_{k+1}", "timestamp": t}
        for track in (False, True):                                   # 앱처럼 전송 전 -> 전송 후
            body = {"room_id": room, "context": sent[-7:], "new_message": new, "participants": plist, "track_bystander": track}
            T.set_request_context(NS(room_id=room, context=body["context"], new_message=new, participants=plist,
                                     has_image=False, track_bystander=track))
            res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": m["timestamp"],
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [new]]
        tr.on_analyze(body, res, wins, now=t)
        a = res["attribution"]
        log.append(NS(k=k + 1, who=who, text=text, bully=a["is_bullying"], aggr=sorted(NAME[x] for x in a["aggressors"]),
                      victim=NAME.get(a["victim"]), why=a["victim_reason"], typ=res["cb_type"], notes=a["attack_notes"],
                      in_room=a["victim_in_room"], parent=a["parent_room_id"]))
        sent.append(new)
    st = tr.state(room)
    if st:
        st["aggressors"] = sorted(NAME[x] for x in st["aggressors"]); st["victim"] = NAME.get(st["victim"])
    return st, log


def show(log, st):
    for r in log:
        if r.bully:
            print(f"      {r.k:2d} {r.who} 「{r.text}」 -> 가해 {r.aggr} 피해 {r.victim} ({r.why}) {r.notes} 방에 있음={r.in_room}")
    print("      최종:", f"가해 {st['aggressors']} / 피해 {st['victim']} ({st['victim_status']})" if st else "사건 없음")


GOSSIP = [("지민", "도현이 또 숙제 안 해옴", .30), ("수아", "걔 원래 그래", .10), ("지민", "도현이 진짜 짜증나", .80),
          ("수아", "ㅇㅈ", .05), ("민재", "오늘 급식 뭐야", .05), ("지민", "도현이 오면 분위기 망함", .65), ("수아", "그니까 ㅋㅋ", .05)]

# ------------------------------------------------------------------------------------------------ C2
print("C2) 방 구조 — 반 방에서 한 명만 빠진 방에서 그 아이를 험담")
T.ROSTERS.clear()
open_room("class", ["지민", "수아", "민재", "도현"])
st, log = play("sub", ["지민", "수아", "민재"], GOSSIP)                    # 이 방의 participants에는 도현이 없다
show(log, st)
check("부분 방으로 연결됨 (원래 방 = class, 빠진 아이 = 도현)", T.ROSTERS.parent("sub") == "class" and set(T.ROSTERS.absent("sub")) == {CODE["도현"]})
check("participants에 없어도 도현이 피해자로 잡힘", bool(st) and st["victim"] == "도현" and st["aggressors"] == ["지민"], str(st and (st["aggressors"], st["victim"])))
last = next((r for r in reversed(log) if r.bully), None)
check("응답에 방에 없는 피해자라는 표시 (victim_in_room=false, subroom, parent_room_id)",
      bool(last) and last.in_room is False and "subroom" in last.notes and last.parent == "class", str(last and (last.in_room, last.notes, last.parent)))
check("같은 편 수아가 피해자로 잡히지 않음", all(r.victim != "수아" for r in log if r.bully))

T.ROSTERS.clear()
st, log = play("alone", ["지민", "수아", "민재"], GOSSIP)                  # 원래 방을 서버가 모르면
check("원래 방이 없으면 연결하지 않음 (0.3.3과 같음: 사건 없음)", st is None and T.ROSTERS.parent("alone") is None)

T.ROSTERS.clear()
open_room("class", ["지민", "수아", "민재", "도현", "하늘", "가온", "나래", "다솜"])
open_room("trio", ["지민", "수아", "민재"])                              # 5명이 빠진 방 = 그냥 친한 셋
open_room("dm", ["지민", "수아"])
open_room("big", ["지민", "수아", "민재", "하늘", "가온", "나래", "다솜"])   # 도현만 빠진 방
check("여럿이 빠진 방, 2명 방은 연결하지 않음", T.ROSTERS.parent("trio") is None and T.ROSTERS.parent("dm") is None)
check("한 명만 빠진 방은 연결함", T.ROSTERS.parent("big") == "class" and set(T.ROSTERS.absent("big")) == {CODE["도현"]})
st, log = play("big", ["지민", "수아", "민재", "하늘", "가온", "나래", "다솜"],
               [("지민", "수학 숙제 몇 쪽이야", .05), ("하늘", "32쪽", .05), ("가온", "도현이는 학원 갔대", .05), ("나래", "ㅇㅋ", .05)])
check("부분 방이어도 공격·배제 발화가 없으면 사건 아님", st is None)
open_room("big", ["지민", "수아", "민재", "하늘", "가온", "나래", "다솜", "도현"])      # 도현이 초대됨
check("빠졌던 아이가 들어오면 연결이 풀림", T.ROSTERS.parent("big") is None)

# ------------------------------------------------------------------------------------------------ C1
print("\nC1) 발화 확인 — 규칙에 걸린 배제 발화를 LLM이 확인")
PARTY = [("지민", "토요일이 도현이 생일이래", .05), ("수아", "선물 뭐 사지", .05), ("지민", "도현이는 빼고 방 만들자", .10),
         ("수아", "ㅇㅋ 도현이한테는 말하지 마", .10), ("민재", "깜짝 파티 좋다", .05)]
MEAN = [("지민", "주말에 놀러 가자", .05), ("수아", "좋아", .05), ("지민", "도현이는 빼고 가자", .10),
        ("수아", "ㅇㅋ 도현이 부르지 마", .10), ("민재", "왜?", .05), ("지민", "도현이랑 놀지 마 다들", .10),
        ("수아", "도현이는 빼고 방 만들자", .10)]
asked = []
def judge(answer):
    def fn(ctx, spk, text):
        asked.append((spk, text, len(ctx)))
        return answer
    return fn

T.ROSTERS.clear(); T._JUDGED.clear(); asked.clear(); T.set_exclusion_judge(judge(False))
st, log = play("party", ["지민", "수아", "민재", "도현"], PARTY)
check("LLM이 '정당'(깜짝 파티)이라고 하면 사건이 열리지 않음", st is None, str(st))
check("전송 후 응답의 cb_type에 '배제'가 붙지 않음", all("배제" not in r.typ for r in log), str([(r.text, r.typ) for r in log if "배제" in r.typ]))
check("LLM은 규칙에 걸린 메시지에만, 메시지당 한 번, 전송 후 호출에서만 불림", [t for _, t, _ in asked] == ["도현이는 빼고 방 만들자", "ㅇㅋ 도현이한테는 말하지 마"], str(asked))
check("LLM에 직전 맥락이 넘어감", all(n >= 2 for _, _, n in asked), str(asked))

T.ROSTERS.clear(); T._JUDGED.clear(); asked.clear(); T.set_exclusion_judge(judge(True))
st, log = play("mean", ["지민", "수아", "민재", "도현"], MEAN)
show(log, st)
check("LLM이 '배제'라고 하면 사건이 열림 (가해 지민·수아 / 피해 도현)", bool(st) and st["victim"] == "도현" and st["aggressors"] == ["수아", "지민"], str(st and (st["aggressors"], st["victim"])))
check("cb_type에 '배제'", any("배제" in r.typ for r in log))

T.ROSTERS.clear(); T._JUDGED.clear(); asked.clear(); T.set_exclusion_judge(judge(None))
st, log = play("down", ["지민", "수아", "민재", "도현"], MEAN)
check("LLM이 답하지 못하면 규칙대로 셈 (0.3.3과 같음)", bool(st) and st["victim"] == "도현")
def boom(ctx, spk, text): raise RuntimeError("timeout")
T.ROSTERS.clear(); T._JUDGED.clear(); T.set_exclusion_judge(boom)
st, log = play("boom", ["지민", "수아", "민재", "도현"], MEAN)
check("LLM 오류가 판정을 깨뜨리지 않음", bool(st) and st["victim"] == "도현")
T.set_exclusion_judge(None)

# ------------------------------------------------------------------------------------------------ C1 + C2
print("\nC1+C2) 부분 방에서의 깜짝 파티 준비는 사건 아님, 따돌림은 사건")
T.ROSTERS.clear(); T._JUDGED.clear(); T.set_exclusion_judge(judge(False))
open_room("class", ["지민", "수아", "민재", "도현"])
st, log = play("sub_party", ["지민", "수아", "민재"], [("지민", "토요일이 도현이 생일이래", .05), ("수아", "선물 뭐 사지", .05),
                                                   ("지민", "도현이한테는 말하지 마", .10), ("수아", "도현이는 빼고 모이자", .10)])
check("도현만 빠진 방에서 생일 준비 -> 사건 없음", st is None, str(st))
T._JUDGED.clear(); T.set_exclusion_judge(judge(True))
st, log = play("sub_mean", ["지민", "수아", "민재"], [("지민", "이 방은 도현이 없는 방임", .10), ("수아", "ㅋㅋ 좋다", .05),
                                                  ("지민", "도현이한테는 말하지 마", .10), ("수아", "도현이는 빼고 놀자", .10)])
show(log, st)
check("도현만 빠진 방에서 따돌림 -> 사건, 피해 도현 (방에 없음)", bool(st) and st["victim"] == "도현" and log[-1].in_room is False)
T.set_exclusion_judge(None)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
