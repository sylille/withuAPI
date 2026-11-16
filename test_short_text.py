# -*- coding: utf-8 -*-
"""
v0.3.12 확인 (2026-11-16 앱팀 확인 결과, 6학년 2반 통제집단 방 d736204b…, 11/12 10:50~11:05)
  is_attack 20건 중 18건이 'ㅇㅇ'(9건)·'왜'·'ㄴ'·'절대'·'없겠지'·'안양하세요' 같은 짧은 글자. 근거는 모두 msg=0.50 ctx=1.00 → cb=0.72.
  실제 거친 말 '입 ㄷㅊ'(0.86, weak_target)·'ㅗㅗ'(0.87, low_confidence)는 빠졌고, '싫음 ㄲㅈ'(0.94)를 말한 6219가 피해자로 기록됨.
  원인: 모듈 A가 짧은 글자에 0.50 언저리(모름)를 주는데 공격 기준이 '0.50 이상'. 가짜 공격이 역할 판정을 뒤집었다.
  고침: withu/short_text.py 짧은 글자 가드 (모듈 A 점수 보정, 긴 메시지는 그대로).

  방 원본이 없어 2번은 보고 내용으로 다시 꾸민 대화다 (누가 어떤 말을 했는지는 추정). 원본을 받으면 그대로 돌려 볼 것.

    python test_short_text.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import short_text as S
from withu import target_resolver as T
from withu.ensemble import Ensemble

fails = 0


def check(name, cond, info=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name:52s} {info}")
    fails += 0 if cond else 1


# --------------------------------------------------------------------------- 1
print("1) 짧은 글자 가드 (텍스트, 모델 점수 -> 기대)")
CASES = [
    # 보고된 짧은 글자: 0.50 -> 내림
    ("ㅇㅇ", 0.50, "down"), ("왜", 0.50, "down"), ("ㄴ", 0.50, "down"), ("절대", 0.50, "down"),
    ("없겠지", 0.50, "down"), ("안양하세요", 0.50, "down"),
    # 흔한 변형
    ("ㅇㅇㅇㅇ", 0.53, "down"), ("응ㅋㅋ", 0.55, "down"), ("왜??", 0.58, "down"), ("ㅋㅋㅋㅋ", 0.70, "down"),
    ("??", 0.51, "down"), ("ㅇㅋ", 0.62, "down"), ("뭐야 ㅋㅋ", 0.60, "down"), ("ㅗㅜㅑ", 0.55, "down"),
    ("넹~", 0.90, "down"),                       # 맞장구 목록과 똑같은 말은 점수가 높아도 내림
    # 실제 거친 말: 점수가 높으면 그대로, 낮으면 올림
    ("입 ㄷㅊ", 0.86, "same"), ("ㅗㅗ", 0.87, "same"), ("싫음 ㄲㅈ", 0.94, "same"),
    ("바보", 0.55, "up"), ("꺼져", 0.52, "up"), ("저리가", 0.51, "up"), ("닥쳐", 0.49, "up"),
    # 뜻이 갈리는 말: 혼자면 내림, 2인칭과 함께면 올림
    ("ㅁㅊ", 0.55, "down"), ("ㅈㄴ", 0.50, "down"), ("미친", 0.55, "down"), ("짜증나", 0.52, "down"),
    ("너 싫어", 0.50, "up"), ("너 진짜 싫어", 0.55, "up"), ("니 미쳤냐", 0.40, "up"), ("아니 싫어", 0.52, "down"),
    # 모델이 확신하는 짧은 말: 그대로
    ("뭐래 너", 0.85, "same"), ("안양하세요", 0.68, "down"),
    # 기준 아래: 그대로
    ("ㅇㅇ", 0.30, "same"), ("왜", 0.49, "same"),
    # 긴 메시지: 그대로 (가드 대상 아님)
    ("오늘 학교 끝나고 같이 놀이터 갈 사람", 0.52, "same"),
    # 초성 욕설을 모델이 놓침: 올림
    ("ㅅㅂ", 0.20, "up"), ("ㄲㅈ", 0.40, "up"), ("ㅗ", 0.10, "up"), ("입 ㄷㅊ", 0.30, "up"),
    # 뜻이 갈리는 초성은 올리지 않음
    ("ㅁㅊ", 0.20, "same"), ("ㅈㄴ", 0.20, "same"),
]
for text, sc, exp in CASES:
    adj, why = S.short_guard(text, sc)
    ok = {"down": adj < S.TOX_THRESHOLD <= sc, "same": adj == sc, "up": adj >= S.JAMO_FLOOR > sc}[exp]
    check(f"{text!r} {sc:.2f} -> {exp}", ok, f"-> {adj:.2f} {why or ''}")

# --------------------------------------------------------------------------- 1b
print("\n1b) 실서버 모듈 A 점수 (2026-11-16 check_short_scores.py): 욕설만 0.50 이상, 나머지는 모두 미만")
REAL = {"ㅇㅇ": .5018, "ㅇㅇㅇ": .2242, "왜": .5036, "ㄴ": .5005, "ㄴㄴ": .4985, "절대": .5033, "없겠지": .5001,
        "안양하세요": .6824, "안녕": .4865, "ㅎㅇ": .2292, "응": .4937, "어": .4997, "네": .4921, "넹": .2698, "ㅇㅋ": .5077,
        "오키": .4998, "ㅋㅋ": .4939, "ㅋㅋㅋㅋ": .4959, "ㅎㅎ": .4893, "ㅠㅠ": .4864, "?": .4986, "??": .4955, "헐": .5051,
        "대박": .4906, "진짜": .4868, "ㄹㅇ": .4949, "ㅇㅈ": .4898, "몰라": .4877, "뭐": .4940, "뭐야": .4878, "아니": .4918,
        "그래": .4991, "맞아": .4918, "나도": .4857, "ㄱㄱ": .4919, "ㅂㅂ": .3848, "잘가": .4901, "고마워": .4874,
        "미안": .5075, "ㅗㅜㅑ": .0908, "ㄷㄷ": .4871, "학교": .4880, "숙제": .4165, "배고파": .3807, "졸려": .3647,
        "ㅁㅊ": .5003, "ㅈㄴ": .5022}
REAL_BAD = {"입 ㄷㅊ": .6708, "ㅗㅗ": .7677, "ㅗ": .5008, "싫음 ㄲㅈ": .8939, "ㄲㅈ": .3780, "ㅅㅂ": .5138, "ㅂㅅ": .5115,
            "ㅈㄹ": .5158, "꺼져": .4935, "닥쳐": .4906, "바보": .4942, "찐따": .5054, "너 싫어": .5029}
bad_ok = [t for t, sc in REAL_BAD.items() if S.short_guard(t, sc)[0] >= S.TOX_THRESHOLD]
ok_ok = [t for t, sc in REAL.items() if S.short_guard(t, sc)[0] < S.TOX_THRESHOLD]
check(f"욕설 {len(REAL_BAD)}개 모두 공격", len(bad_ok) == len(REAL_BAD),
      f"놓침: {[t for t in REAL_BAD if t not in bad_ok]}")
check(f"그 밖의 {len(REAL)}개 모두 공격 아님", len(ok_ok) == len(REAL),
      f"공격으로 셈: {[t for t in REAL if t not in ok_ok]}")

# --------------------------------------------------------------------------- 2
print("\n2) 보고된 방을 다시 꾸민 대화: 가드 끄면 증상 재현, 켜면 짧은 글자는 공격이 아님")
A, B, C = "6219", "6220", "6221"
MODEL = {"ㅇㅇ": 0.50, "왜": 0.50, "ㄴ": 0.50, "절대": 0.50, "없겠지": 0.50, "안양하세요": 0.50,
         "입 ㄷㅊ": 0.86, "ㅗㅗ": 0.87, "싫음 ㄲㅈ": 0.94}
CONVO = [(C, "안양하세요"), (B, "ㅇㅇ"), (A, "너 뭐함"), (B, "왜"), (A, "입 ㄷㅊ"), (B, "ㅇㅇ"), (B, "ㄴ"),
         (C, "ㅋㅋ 뭐야"), (B, "ㅇㅇ"), (A, "ㅗㅗ"), (B, "ㅇㅇ"), (B, "절대"), (C, "그만해"), (B, "ㅇㅇ"),
         (A, "숙제 했어?"), (B, "ㅇㅇ"), (B, "없겠지"), (A, "싫음 ㄲㅈ"), (B, "ㅇㅇ"), (B, "ㅇㅇ"), (B, "ㅇㅇ")]
P = [{"participant_code": c, "display_name": c} for c in (A, B, C)]


def run(rid, guard_on):
    S.ENABLE = guard_on
    T.HISTORY.clear(rid); T.ROSTERS.clear()
    E = Ensemble(lambda t: MODEL.get(t, 0.05), lambda texts, speakers=None: 1.0)
    hist, rows = [], []
    for i, (who, text) in enumerate(CONVO):
        new = {"participant_code": who, "text": text, "message_id": f"m{i}"}
        r = E.analyze({"room_id": rid, "context": hist[-10:], "new_message": new, "participants": P})
        a = r["attribution"]
        rows.append((who, text, r["cb_score"], r["evidence"], a["is_bullying"], a["aggressors"], a["victim"],
                     a["drop_reason"], f"m{i}" in (a.get("attack_message_ids") or [])))
        hist.append(new)
    S.ENABLE = True
    return rows


def show(rows):
    for who, text, cb, ev, bully, aggr, vic, drop, counted in rows:
        print(f"      {who} {text:8s} cb={cb:.2f} {'공격' if counted else '    '} bully={bully!s:5} "
              f"aggr={aggr} victim={vic} drop={drop}   [{ev}]")


SHORT = {"ㅇㅇ", "왜", "ㄴ", "절대", "없겠지", "안양하세요"}
before = run("before", False)
print("   가드 끔 (v0.3.11과 같음)")
show(before)
short_hi = [r for r in before if r[1] in SHORT and r[2] >= 0.5]
check("가드 끔: 짧은 글자가 0.50 이상 (증상 재현)", len(short_hi) == sum(1 for r in before if r[1] in SHORT),
      f"{len(short_hi)}건, 예 cb={short_hi[0][2] if short_hi else '-'}")
check("가드 끔: 6220이 가해자로 잡힘 (증상 재현)", any(B in (r[5] or []) for r in before))

after = run("after", True)
print("   가드 켬 (v0.3.12)")
show(after)
check("가드 켬: 짧은 글자 점수 모두 0.50 미만", all(r[2] < 0.5 for r in after if r[1] in SHORT))
check("가드 켬: 짧은 글자가 공격으로 세어지지 않음", not any(r[8] for r in after if r[1] in SHORT))
check("가드 켬: 6220은 가해자가 아님", not any(B in (r[5] or []) for r in after))
check("가드 켬: '싫음 ㄲㅈ'를 말한 6219는 피해자가 아님", not any(r[6] == A for r in after if r[4]))
check("가드 켬: 거친 말 3개는 점수 그대로", all(r[2] >= 0.86 for r in after if r[1] in ("입 ㄷㅊ", "ㅗㅗ", "싫음 ㄲㅈ")))
check("가드 켬: 근거에 보정 사유가 남음", all("short_" in r[3] for r in after if r[1] in SHORT))

print("\nALL PASS" if not fails else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
