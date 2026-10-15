# -*- coding: utf-8 -*-
"""
v0.3.6 확인: 같은 반이지만 방에 없는 아이 (classmates). 모델·LLM 없이 실행된다.

    python test_classmates.py          # withu 폴더가 있는 곳에서

모듈 A 점수는 대본에 적은 값이다 (실제 모델이 아님). 이름과 대사는 모두 가상이다.
요청은 실제 서버처럼 schemas.AnalyzeRequest로 한 번 검사한 뒤 넘긴다 (classmates 필드가 버려지지 않는지).
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from types import SimpleNamespace as NS
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble
from withu.schemas import AnalyzeRequest

fails = 0
KIDS = ["지민", "수아", "민재", "박서윤", "도현", "김하늘", "박하늘"]
CODE = {n: f"K{i+1:02d}" for i, n in enumerate(KIDS)}
NAME = {c: n for n, c in CODE.items()}


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


def plist(names, nick=None):
    nick = nick or {}
    return [{"participant_code": CODE[n], "display_name": nick.get(n, n)} for n in names]


def play(room, members, lines, classmates=None, nick=None, clear=True):
    """members: 방 구성원(participants). classmates: 학급 구성원 전체(없으면 보내지 않음)."""
    if clear:
        T.HISTORY.clear(room); T.ROSTERS.clear(); T._JUDGED.clear()
    score = {}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = BystanderTracker()
    parts = plist(members, nick)
    mates = plist(classmates, nick) if classmates is not None else []
    sent, log, t = [], [], 5000.0
    for k, (who, text, cb) in enumerate(lines):
        score[text] = cb
        t += 4
        new = {"participant_code": CODE[who], "text": text, "message_id": f"{room}_{k+1}", "timestamp": str(t)}
        for track in (False, True):                                   # 앱처럼 전송 전 -> 전송 후
            body = {"room_id": room, "context": sent[-7:], "new_message": new, "participants": parts,
                    "classmates": mates, "track_bystander": track}
            req = AnalyzeRequest(**body)
            T.set_request_context(req)
            body = req.model_dump()
            res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": float(m["timestamp"]),
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [body["new_message"]]]
        tr.on_analyze(body, res, wins, now=t)
        a = res["attribution"]
        log.append(NS(k=k + 1, who=who, text=text, bully=a["is_bullying"], aggr=sorted(NAME[x] for x in a["aggressors"]),
                      victim=NAME.get(a["victim"]), why=a["victim_reason"], drop=a["drop_reason"], typ=res["cb_type"],
                      notes=a["attack_notes"], in_room=a["victim_in_room"], parent=a["parent_room_id"]))
        sent.append(new)
    st = tr.state(room)
    if st:
        st["aggressors"] = sorted(NAME[x] for x in st["aggressors"]); st["victim"] = NAME.get(st["victim"])
    return st, log


def first_open(log):
    return next((r for r in log if r.bully), None)


ROOM = ["지민", "수아", "민재"]
CLASS = ROOM + ["박서윤", "도현"]

print("1) 방에 없는 같은 반 아이를 뒤에서 욕함 (반복)")
GOSSIP = [("지민", "박서윤 진짜 짜증나!!", .80), ("수아", "ㅋㅋ", .05), ("민재", "숙제 다 했어?", .05),
          ("지민", "박서윤 진짜 짜증나!!", .80), ("수아", "ㅇㅈ", .05)]
st, log = play("r1", ROOM, GOSSIP, classmates=CLASS)
r = first_open(log)
check("사건이 열림, 가해 지민 -> 피해 박서윤", bool(st) and st["victim"] == "박서윤" and st["aggressors"] == ["지민"],
      str(st and (st["aggressors"], st["victim"])))
check("두 번째 험담에서 열림 (첫 번째에서는 안 열림)", bool(r) and r.k == 4, str(r and r.k))
check("첫 번째 험담에서는 열리지 않음", log[0].bully is False, str((log[0].bully, log[0].drop)))
check("응답: victim_in_room=false, attack_notes=absent_classmate, parent_room_id=null",
      bool(r) and r.in_room is False and r.notes == ["absent_classmate"] and r.parent is None,
      str(r and (r.in_room, r.notes, r.parent)))
check("맞장구친 수아는 피해자가 아님", all(x.victim != "수아" for x in log if x.bully))

print("\n2) 험담이 한 번뿐이면 열지 않음")
st, log = play("r2", ROOM, [("지민", "박서윤 진짜 짜증나!!", .80), ("수아", "ㅋㅋ", .05), ("민재", "숙제 다 했어?", .05),
                            ("지민", "아 진짜 짜증나", .80), ("수아", "왜", .05)], classmates=CLASS)
check("이름이 나온 공격 1개 + 이름 없는 공격 1개 -> 사건 없음", st is None and not any(x.bully for x in log),
      str([(x.k, x.victim, x.drop) for x in log]))

print("\n3) 학급 명단을 보내지 않으면 예전과 같음")
st, log = play("r3", ROOM, GOSSIP, classmates=None)
check("classmates 없음 -> 사건 없음 (0.3.5와 같음)", st is None)

print("\n4) 방 구성원은 그대로")
st, log = play("r4", ROOM, [("지민", "수아 진짜 짜증나", .80), ("수아", "왜 나한테 그래", .05), ("지민", "수아 꺼져", .85),
                            ("수아", "하지 마", .05)], classmates=CLASS)
r = first_open(log)
check("방에 있는 수아가 피해자, victim_in_room=true, absent_classmate 없음",
      bool(r) and r.victim == "수아" and r.in_room is True and "absent_classmate" not in r.notes,
      str(r and (r.victim, r.in_room, r.notes)))

print("\n5) 이름 조각이 겹치면 방 구성원 쪽으로")
st, log = play("r5", ["지민", "수아", "김하늘"], [("지민", "하늘이 진짜 짜증나", .80), ("수아", "ㅋㅋ", .05),
                                                   ("지민", "하늘이 오면 분위기 망함", .70)],
               classmates=["지민", "수아", "김하늘", "박하늘"])
check("'하늘이'는 방에 있는 김하늘 (같은 반 박하늘 아님)", bool(st) and st["victim"] == "김하늘", str(st and st["victim"]))
check("박하늘의 성 포함 이름은 그대로 찾음", set(T.ROSTERS.absent("r5")) == {CODE["박하늘"]}
      and T.ROSTERS.absent("r5")[CODE["박하늘"]].search("박하늘 짜증나") is not None
      and T.ROSTERS.absent("r5")[CODE["박하늘"]].search("하늘이 짜증나") is None)

print("\n6) 학급 구성이 바뀌면 다음 요청부터 반영")
st, log = play("r6", ROOM, GOSSIP[:3], classmates=CLASS)
st, log = play("r6", ROOM, [("지민", "박서윤 진짜 짜증나!!!", .80), ("수아", "ㄹㅇ", .05)],
               classmates=ROOM + ["도현"], clear=False)                 # 박서윤 전학: 앱이 새 명단을 보냄
check("명단에서 빠진 아이는 더 찾지 않음", CODE["박서윤"] not in T.ROSTERS.absent("r6") and not any(x.bully for x in log),
      str(list(T.ROSTERS.absent("r6"))))
st, log = play("r6b", ROOM, GOSSIP[:3], classmates=CLASS)
st, log = play("r6b", ROOM, [("민재", "내일 봐", .05)], classmates=[], clear=False)   # 빈 목록 = 보내지 않은 것으로 보고 이전 명단 유지
check("빈 classmates는 이전 명단 유지", CODE["박서윤"] in T.ROSTERS.absent("r6b"))

print("\n7) participants를 빠뜨려도 방에서 말한 아이는 '방에 있는 아이'")
st, log = play("r7", [], [("지민", "수아 진짜 짜증나", .80), ("수아", "왜 나한테 그래", .05), ("지민", "수아 꺼져", .85),
                          ("수아", "하지 마", .05)], classmates=CLASS)
r = first_open(log)
check("말한 수아는 victim_in_room=true", bool(r) and r.victim == "수아" and r.in_room is True, str(r and (r.victim, r.in_room)))

print("\n8) 방에 없는 아이를 빼자는 말 (배제)")
MEAN = [("지민", "주말에 놀러 가자", .05), ("수아", "좋아", .05), ("지민", "도현이는 빼고 가자", .10),
        ("수아", "ㅇㅋ 도현이 부르지 마", .10), ("민재", "왜?", .05), ("지민", "도현이랑 놀지 마 다들", .10),
        ("수아", "도현이는 빼고 방 만들자", .10)]                     # test_exclusion.py의 대본 (도현이 이 방에 없음)
T.set_exclusion_judge(lambda ctx, spk, text: None)                    # LLM이 답하지 못한 경우 = 규칙대로
st, log = play("r8", ROOM, MEAN, classmates=CLASS)
check("배제 발화가 cb_type에 '배제'로 표시됨", "배제" in log[2].typ, log[2].typ)
r = first_open(log)
check("사건, 가해 지민·수아 / 피해 도현 (방에 없음, absent_classmate)",
      bool(st) and st["victim"] == "도현" and st["aggressors"] == ["수아", "지민"] and r.in_room is False and "absent_classmate" in r.notes,
      str(st and (st["aggressors"], st["victim"], r and r.notes)))

print("\n9) 끄기: WITHU_ENABLE_CLASSMATES=0")
T.ENABLE_CLASSMATES = False
st, log = play("r9", ROOM, GOSSIP, classmates=CLASS)
check("끄면 사건 없음", st is None)
T.ENABLE_CLASSMATES = True

print("\nALL PASS" if not fails else f"\n{fails} FAIL")
sys.exit(1 if fails else 0)
