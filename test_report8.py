# -*- coding: utf-8 -*-
"""
v0.3.16 확인: 앱팀이 11/25 16:00~16:10에 테스트 서버에서 다시 돌린 사후검사2·4 기록을 그대로 재생한다.
모델·LLM 없이 실행된다.

    python test_report8.py

0.3.15의 test_report7은 보고에 인용된 대사 외에는 가상으로 채운 대본이라, 실제 대본에서 두 증상이 남은 것을 잡지 못했다.
이 테스트는 실제 대사·순서·참여자 코드(V-SRC-…)와 그때 기록된 모듈 A 점수를 쓴다.

1) 사후검사2 — "나쁜 새끼들", "지민아 조용히 좀 해"가 공격으로 세어져 예슬(C001)이 공동 가해자가 되고 선택지가 사라짐.
   원인: 지민의 공격("맨날 저래서 짜증남", "말하면 또 삐질걸")에 도현 이름이 없어, 바로 앞 화자(예슬의 "먼데")를
   향한 공격으로 잡혔다. 그래서 '다른 아이를 공격하던 가해자에게 한 말' 조건이 성립하지 않았다.
   이제 이름 없이 남 얘기하듯 한 공격은 방에서 이야기되던 아이(이름이 나왔고 말하지 않은 아이)를 향한 것으로 본다.
2) 사후검사4 — "소희야"가 동조로 나오고 전송 전 동조 경고가 뜸.
   원인: 이름을 '코드(역할)'로 바꾼 뒤 지우는 패턴이 하이픈 없는 코드(P01)만 알아, "V-SRC-"가 남아 이름만 부른 말로 보지 못했다.
   LLM 라벨은 그날 실서버 응답([피해자/욕설] 동조)을 그대로 흉내 낸다.
"""
import os, sys
from types import SimpleNamespace as NS
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T
from withu.bystander import BystanderTracker
from withu.ensemble import Ensemble
from withu.phase4_bystander import parse_label, content_of

fails = 0
CHILD = "C001"


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


# 사후검사 2. 배제 (room eb554012-a3c6-496a-a97a-0485fe401341, 단계 시작 2026-11-25 16:01:24 KST)
S2_PARTS = [('C001', '김철수'), ('V-SRC-1BEC6F4693', '지민'), ('V-SRC-20F8F4DAEE', '도현'), ('V-SRC-3353FF8101', '수아'), ('V-SRC-F12A15053F', '민재')]
S2 = [  # (코드, 본문, 모듈 A 점수, 단계 시작 뒤 초, '다른 이야기 꺼내기' 선택)
    ('V-SRC-1BEC6F4693', '야 도현이 오늘 쉬는 시간에 봤냐', 0.22, 0.0, False),
    ('V-SRC-1BEC6F4693', '또 우리 얘기하는데 갑자기 끼어듦 ㅋ', 0.33, 3.0, False),
    ('V-SRC-3353FF8101', '나도 봄 ㅋㅋ', 0.09, 7.0, False),
    ('V-SRC-3353FF8101', '진짜 눈치 없음', 0.4, 12.0, False),
    ('V-SRC-F12A15053F', '그랬어?', 0.32, 16.0, False),
    ('C001', '먼데', 0.49, 20.0, False),
    ('V-SRC-1BEC6F4693', '맨날 저래서 짜증남', 0.56, 20.0, False),
    ('V-SRC-3353FF8101', '말도 재미없고 분위기만 깨잖아', 0.42, 24.0, False),
    ('V-SRC-1BEC6F4693', 'ㄹㅇ 관종 같음', 0.3, 28.0, False),
    ('V-SRC-3353FF8101', '자기가 인기 많은 줄 아는 듯', 0.42, 31.0, False),
    ('C001', '도현이한테 왜구래', 0.31, 31.7, False),
    ('V-SRC-F12A15053F', '그건 좀;;', 0.3, 34.0, False),
    ('C001', '도현이가 먼절못이 잇냐', 0.25, 36.4, False),
    ('V-SRC-1BEC6F4693', '왜? 사실인데', 0.35, 39.0, False),
    ('C001', '나쁜 새끼들', 0.85, 40.4, False),
    ('V-SRC-3353FF8101', '도현이 앞에서는 다들 말 못 하잖아 ㅋㅋ', 0.19, 44.0, False),
    ('V-SRC-1BEC6F4693', '말하면 또 삐질걸', 0.54, 49.0, False),
    ('C001', '도현이 쉬는 시간이 못봄', 0.23, 50.3, False),
    ('V-SRC-3353FF8101', 'ㅇㅇ 바로 피해자인 척함', 0.42, 54.0, False),
    ('V-SRC-1BEC6F4693', '이번 토요일에 떡볶이 먹으러 갈 사람', 0.07, 57.0, False),
    ('C001', '지민아 조용히 좀 해', 0.67, 59.6, False),
    ('V-SRC-1BEC6F4693', '도현이 빼고', 0.33, 63.0, False),
    ('V-SRC-3353FF8101', '나 감', 0.5, 66.0, False),
    ('V-SRC-3353FF8101', '걔 오면 또 분위기 이상해짐', 0.69, 70.0, False),
    ('V-SRC-F12A15053F', '도현이한테는', 0.29, 75.0, False),
    ('V-SRC-F12A15053F', '뭐라고 말해?', 0.44, 81.0, False),
    ('V-SRC-1BEC6F4693', '말하지 마', 0.3, 84.0, False),
    ('V-SRC-1BEC6F4693', '우리가 왜 알려줘야 됨?', 0.37, 89.0, False),
    ('V-SRC-3353FF8101', '새 방 만들어서 거기서 정하자', 0.3, 93.0, False),
    ('V-SRC-1BEC6F4693', 'ㅇㅇ 도현이 없는 방', 0.31, 98.0, False),
    ('C001', '야르\\', 0.3, 100.0, False),
    ('V-SRC-F12A15053F', '흠', 0.49, 104.0, False),
    ('V-SRC-3353FF8101', '걔한테 들키면 귀찮아짐', 0.27, 109.0, False),
    ('V-SRC-1BEC6F4693', '그냥 우리끼리 놀자', 0.3, 114.0, False),
    ('V-SRC-3353FF8101', '도현이는 절대 부르지 마', 0.28, 120.0, False),
]
# 사후검사 4. 언어적 폭력 및 배제 (room 1c57b9c2-34e5-4b4d-9fb3-c16baff72768, 단계 시작 2026-11-25 16:06:55 KST)
S4_PARTS = [('C001', '김철수'), ('V-SRC-64364923F5', '소희'), ('V-SRC-9A7842F1A3', '다은'), ('V-SRC-CAFD36E087', '서준'), ('V-SRC-F12A15053F', '민재')]
S4 = [  # (코드, 본문, 모듈 A 점수, 단계 시작 뒤 초, '다른 이야기 꺼내기' 선택)
    ('V-SRC-F12A15053F', '우리 반 벼룩시장 역할 정해야 함', 0.18, 0.0, False),
    ('V-SRC-CAFD36E087', 'ㅇㅇ 빨리 정하자', 0.17, 4.0, False),
    ('V-SRC-64364923F5', '나는 물건 소개 카드 만들면 좋을 것 같아', 0.11, 9.0, False),
    ('V-SRC-64364923F5', '그림도 같이 넣으면 보기 좋을 듯', 0.11, 14.0, False),
    ('V-SRC-F12A15053F', '또 쓸데없는 거 하자고 하네', 0.34, 19.0, False),
    ('V-SRC-CAFD36E087', 'ㅋㅋ 소희 아이디어는 맨날 촌스러움', 0.38, 24.0, False),
    ('V-SRC-64364923F5', '왜 그렇게 말해?', 0.35, 29.0, False),
    ('V-SRC-64364923F5', '그냥 의견 낸 거잖아', 0.13, 33.0, False),
    ('V-SRC-F12A15053F', '별로니까 별로라고 하지', 0.4, 38.0, False),
    ('V-SRC-CAFD36E087', 'ㄹㅇ', 0.49, 42.0, False),
    ('V-SRC-CAFD36E087', '시간 남아돌면 그거 하자 ㅋㅋ', 0.3, 47.0, False),
    ('V-SRC-64364923F5', '그런 식으로 비웃지 마', 0.28, 52.0, False),
    ('V-SRC-64364923F5', '기분 나빠', 0.3, 56.0, False),
    ('V-SRC-F12A15053F', '아 또 기분 나쁘대', 0.35, 61.0, False),
    ('V-SRC-CAFD36E087', '진짜 맨날 예민함', 0.4, 65.0, False),
    ('V-SRC-9A7842F1A3', '다른 의견도 같이 들어보고 정하면 되잖아', 0.06, 71.0, False),
    ('V-SRC-F12A15053F', '다은아 그냥 놔둬', 0.25, 76.0, False),
    ('V-SRC-F12A15053F', '소희랑 하면 말만 길어짐', 0.77, 80.0, False),
    ('V-SRC-CAFD36E087', '맞아', 0.49, 85.0, False),
    ('V-SRC-CAFD36E087', '지난번에도 얘 때문에 준비 늦었잖아', 0.46, 89.0, False),
    ('V-SRC-64364923F5', '그때 나만 늦은 거 아니잖아', 0.36, 94.0, False),
    ('C001', '두둥실', 0.17, 94.3, False),
    ('V-SRC-F12A15053F', '아무튼 이번엔 우리가 정할게', 0.22, 99.0, False),
    ('C001', '아닌대', 0.31, 100.7, False),
    ('V-SRC-64364923F5', '나도 같은 모둠인데 왜 너희끼리 정해?', 0.29, 104.0, False),
    ('V-SRC-CAFD36E087', '그러니까 그냥 듣고 있어', 0.14, 109.0, False),
    ('C001', '[사진]', 0.0, 111.4, False),
    ('V-SRC-CAFD36E087', '중요한 건 우리가 할게', 0.46, 113.0, False),
    ('C001', '히힝 ㅠ', 0.09, 115.7, False),
    ('V-SRC-64364923F5', '나도 할 수 있어', 0.14, 118.0, False),
    ('C001', '야르', 0.23, 119.6, False),
    ('V-SRC-F12A15053F', '아니 넌 안 해도 돼', 0.64, 122.0, False),
    ('V-SRC-F12A15053F', '괜히 또 이상하게 만들지 말고', 0.38, 126.0, False),
    ('V-SRC-CAFD36E087', 'ㅋㅋㅋ', 0.49, 131.0, False),
    ('C001', '속상한 사람 있을 듯. \n그만하고 딴 얘기 하자', 0.35, 134.5, True),
    ('V-SRC-CAFD36E087', '소희는 당일에 물건이나 옮겨', 0.73, 135.0, False),
    ('V-SRC-64364923F5', '그건 너무하잖아', 0.42, 140.0, False),
    ('V-SRC-64364923F5', '나도 준비하고 싶어', 0.16, 144.0, False),
    ('V-SRC-F12A15053F', '싫으면 다른 모둠 가든가', 0.42, 149.0, False),
    ('V-SRC-CAFD36E087', '맞아', 0.49, 153.0, False),
    ('V-SRC-CAFD36E087', '새 방 만들어서 우리끼리 정하자', 0.37, 158.0, False),
    ('C001', '소희 즐', 0.36, 162.0, False),
    ('V-SRC-9A7842F1A3', '소희 빼고 만드는 건 아닌 것 같은데', 0.19, 163.0, False),
    ('V-SRC-F12A15053F', '왜?', 0.31, 168.0, False),
    ('C001', '소희야', 0.34, 171.8, False),
    ('V-SRC-F12A15053F', '얘랑 하면 답답하니까 그러는 거잖아', 0.51, 172.0, False),
    ('C001', '괜찮아?', 0.33, 174.9, False),
    ('V-SRC-CAFD36E087', '소희 없는 방 만들게', 0.47, 177.0, False),
    ('V-SRC-64364923F5', '진짜 속상해', 0.09, 182.0, False),
    ('V-SRC-64364923F5', '왜 나만 빼?', 0.48, 186.0, False),
    ('C001', '소희 없는 방 같은거', 0.22, 190.7, False),
    ('V-SRC-F12A15053F', '너 때문이라는 생각은 안 함?', 0.49, 191.0, False),
    ('C001', '만들지마', 0.37, 192.3, False),
    ('V-SRC-CAFD36E087', '이제 그만 말해', 0.48, 196.0, False),
    ('C001', '알겠어?', 0.43, 196.4, False),
    ('V-SRC-CAFD36E087', '우리끼리 따로 얘기하자', 0.35, 201.0, False),
    ('C001', '소희한테 사과해', 0.28, 204.3, False),
]


ANS = lambda tg, st, lab: f'{{"target":"{tg}","stance":"{st}","label":"{lab}","reason":"x"}}'


def fake_llm(turns, speaker, text, reply=None):
    """그날 실서버 LLM 응답을 흉내 낸다. 서버의 사후 보정(parse_label)은 실제 코드 그대로 거친다."""
    if text.endswith("(피해자)야"):
        out = ANS("피해자", "욕설", "동조")          # 11/25 "소희야": [피해자/욕설] 피해자 공격적 발언
    elif text.endswith("(피해자) 즐"):
        out = ANS("피해자", "욕설", "동조")          # "소희 즐": 0.3.15에서 고친 대로 동조
    else:
        out = ANS("없음", "중립", "비해당")
    return parse_label(out, text, reply)


def play(room, parts, lines, win=8):
    """앱처럼 보낸다: 아이(C001) 메시지는 전송 전 호출(track_bystander=false) 뒤 전송 후 호출. 직전 7개를 context로."""
    score = {t: sc for _, t, sc, _, _ in lines}
    ens = Ensemble(message_scorer=lambda t: score.get(t, 0.05), context_scorer=lambda w: 0.0)
    tr = BystanderTracker(classify=fake_llm)
    T.HISTORY.clear(room); T.ROSTERS.clear()
    plist = [{"participant_code": c, "display_name": n} for c, n in parts]
    sent, log, t0 = [], [], 1764054000.0
    for k, (who, text, _, sec, is_def) in enumerate(lines):
        new = {"participant_code": who, "text": text, "message_id": f"{room}_{k + 1}", "timestamp": t0 + sec}
        if is_def:
            new["is_defense_action"] = True
        body = {"room_id": room, "context": sent[-(win - 1):], "new_message": new, "participants": plist,
                "has_image": text == "[사진]", "track_bystander": True}
        preview = None
        if who == CHILD:
            pre = dict(body, track_bystander=False)
            preview = tr.preview(pre, now=t0 + sec - 0.5, timeout=5)
        T.set_request_context(NS(**body))
        res = ens.analyze(body)
        wins = [{"message_id": m["message_id"], "speaker": m["participant_code"], "ts": m["timestamp"],
                 "cb": score.get(m["text"], 0.05)} for m in body["context"] + [new]]
        st = tr.on_analyze(body, res, wins, now=t0 + sec)
        me = next((b for b in (st or {}).get("bystanders", []) if b["participant_code"] == who), None)
        a = res["attribution"]
        log.append(NS(k=k + 1, who=who, text=text, mid=new["message_id"], bully=a["is_bullying"],
                      aggr=sorted(a["aggressors"]), victim=a["victim"], attack_ids=a["attack_message_ids"],
                      cb=res["cb_score"], typ=res["cb_type"], sup=res["suppressed"], guard=res["guard_reason"],
                      behavior=me and me["behavior"], hist=[e["event"] for e in (me or {}).get("history", [])],
                      preview=preview and preview["label"]))
        sent.append(new)
    return tr.state(room), log


def row(log, text):
    return next(r for r in log if r.text == text)


J, D, S, M = "V-SRC-1BEC6F4693", "V-SRC-20F8F4DAEE", "V-SRC-3353FF8101", "V-SRC-F12A15053F"     # 지민 도현 수아 민재
SH, DE, SJ = "V-SRC-64364923F5", "V-SRC-9A7842F1A3", "V-SRC-CAFD36E087"                         # 소희 다은 서준

# ------------------------------------------------------------------------------------------------ 1
print("1) 사후검사2 — 지민을 나무란 예슬(C001)이 공동 가해자로 잡히던 문제 (실제 기록)")
st, log = play("r8a", S2_PARTS, S2)
mine = {r.mid for r in log if r.who == CHILD}
check("어느 판정에서도 C001이 aggressors에 없음", all(CHILD not in r.aggr for r in log),
      str([(r.k, r.text, r.aggr) for r in log if CHILD in r.aggr][:3]))
check("C001의 메시지가 attack_message_ids에 들어가지 않음", all(not (set(r.attack_ids) & mine) for r in log),
      str([(r.k, sorted(set(r.attack_ids) & mine)) for r in log if set(r.attack_ids) & mine][:3]))
r = row(log, "도현이 빼고")
check("'도현이 빼고' 판정: 가해 지민만 / 피해 도현", r.bully and r.aggr == [J] and r.victim == D, str(vars(r)))
r = row(log, "ㅇㅇ 바로 피해자인 척함")
check("'바로 피해자인 척함' 판정에 C001이 없음 (0.3.15에서는 aggressors=[C001])", CHILD not in r.aggr, str(r.aggr))
check("최종 사건: C001은 주변인 (선택지가 보임)",
      bool(st) and CHILD not in st["aggressors"] and CHILD in [b["participant_code"] for b in st["bystanders"]],
      str(st and (st["aggressors"], [b["participant_code"] for b in st["bystanders"]])))
check("최종 사건 가해자는 대본대로 지민·수아", bool(st) and set(st["aggressors"]) == {J, S}, str(st and st["aggressors"]))
r = row(log, "나쁜 새끼들")
check("'나쁜 새끼들'은 그대로 언어적 폭력 (전송 전 욕설 경고 유지)", r.typ == "언어적 폭력" and not r.sup, f"{r.typ} {r.cb} {r.guard}")
r = row(log, "지민아 조용히 좀 해")
check("'지민아 조용히 좀 해'는 suppressed, guard_reason=counter_aggressor",
      r.sup and r.guard == "counter_aggressor" and r.typ == "비해당", f"{r.typ} {r.cb} {r.sup} {r.guard}")

# ------------------------------------------------------------------------------------------------ 2
print("\n2) 이야기되던 아이를 가해자의 대상으로 보는 규칙이 우회로가 되지 않는지")
# 2-1 이야기되던 아이 본인이 되받아친 욕은 예전처럼 공격 (가드가 붙지 않음)
def notes(parts, lines):
    T.ROSTERS.clear()
    code = {p: f"P{i + 1:02d}" for i, p in enumerate(parts)}
    T.ROSTERS.update("n", [{"participant_code": c, "display_name": p} for p, c in code.items()])
    items = [{"speaker": code[w], "text": t, "cb": cb} for w, t, cb in lines]
    return {t: d.get("note") for (w, t, cb), d in zip(lines, T.prepare(items, roster=T.ROSTERS.get("n"), room_id="n"))}
A = [("지민", "야 예슬이 오늘 봤냐", .10), ("수아", "ㅋㅋ 봄", .05), ("지민", "맨날 저래서 짜증남", .60),
     ("예슬", "너네 나쁜 새끼들", .90)]
check("이야기되던 예슬 본인의 '너네 나쁜 새끼들'은 공격으로 셈", notes(["지민", "수아", "예슬"], A)["너네 나쁜 새끼들"] is None,
      str(notes(["지민", "수아", "예슬"], A)))
# 2-2 이름이 나온 아이가 그 뒤 말했으면(그 아이에게 하는 말일 수 있음) 이야기되던 아이로 보지 않는다
B = [("지민", "도현이 뭐함", .10), ("도현", "나 숙제", .05), ("예슬", "ㅇㅇ", .05), ("지민", "맨날 저래서 짜증남", .60),
     ("예슬", "나쁜 새끼들", .90)]
check("이름이 나온 도현이 그 뒤 말했으면 대상으로 보지 않음 → 예슬의 욕은 공격으로 셈",
      notes(["지민", "도현", "예슬"], B)["나쁜 새끼들"] is None, str(notes(["지민", "도현", "예슬"], B)))
# 2-3 2인칭 공격("너 맨날 저래")은 바로 앞 화자를 향한다
C = [("지민", "도현이 오늘 봤냐", .10), ("예슬", "먼데", .40), ("지민", "너 맨날 저래서 짜증남", .70), ("예슬", "나쁜 새끼들", .90)]
check("2인칭 공격 뒤 되받아친 예슬의 욕은 공격으로 셈 (서로 욕하는 대화)",
      notes(["지민", "도현", "예슬"], C)["나쁜 새끼들"] is None, str(notes(["지민", "도현", "예슬"], C)))

# ------------------------------------------------------------------------------------------------ 3
print("\n3) 사후검사4 — '소희야'가 동조로 나오던 문제 (실제 기록, 실제 코드 V-SRC-…)")
st, log = play("r8b", S4_PARTS, S4)
check("어느 판정에서도 C001이 aggressors에 없음", all(CHILD not in r.aggr for r in log))
check("최종 사건: 가해 서준·민재 / 피해 소희", bool(st) and set(st["aggressors"]) == {SJ, M} and st["victim"] == SH,
      str(st and (st["aggressors"], st["victim"])))
r = row(log, "소희야")
prev = next(x for x in reversed(log[:r.k - 1]) if x.who == CHILD)
added = r.hist[len(prev.hist):] if r.hist[:len(prev.hist)] == prev.hist else r.hist[-2:]
check("'소희야' 전송 전 판정이 동조가 아님 (경고 없음)", r.preview != "동조", str(r.preview))
check("'소희야'로 새 동조 기록이 생기지 않음 (0.3.15: '동조: 발화(LLM)')", not any(e.startswith("동조") for e in added), str(added))
# bystander_behavior는 이 아이의 마지막 판정(바로 앞 '소희 즐'의 동조)을 그대로 돌려준다
r = row(log, "소희 즐")
check("'소희 즐'은 0.3.15대로 동조", r.preview == "동조" and r.behavior == "동조", f"{r.preview} {r.behavior}")
check("하이픈 있는 코드를 이름으로 지움", content_of(f"{SH}(피해자)야") == "" and content_of(f"{SH}(피해자) 즐") == "즐",
      repr(content_of(f"{SH}(피해자)야")))
for text, lab in [(f"{SH}(피해자)야", "방어"), (f"{SH}(피해자)야", "동조")]:
    got, why = parse_label(ANS("피해자", "지지" if lab == "방어" else "욕설", lab), text)
    check(f"'{text}' {lab} -> 비해당", got == "비해당", f"{got} {why}")
got, _ = parse_label(ANS("피해자", "지지", "방어"), f"{SH}(피해자)야 ㅠㅠ")
check("'소희야 ㅠㅠ'는 LLM 판정(방어) 그대로", got == "방어", got)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
