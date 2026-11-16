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
    # 실제 거친 말: 그대로
    ("입 ㄷㅊ", 0.86, "same"), ("ㅗㅗ", 0.87, "same"), ("싫음 ㄲㅈ", 0.94, "same"), ("ㅁㅊ", 0.55, "same"),
    ("바보", 0.55, "same"), ("너 진짜 싫어", 0.55, "same"), ("꺼져", 0.52, "same"), ("저리가", 0.51, "same"),
    # 모델이 확신하는 짧은 말: 그대로
    ("뭐래 너", 0.80, "same"),
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
