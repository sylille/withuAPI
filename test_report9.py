# -*- coding: utf-8 -*-
"""
v0.3.17 확인: 사후검사2를 '실제로 보인 순서'로 재생한다. 모델·LLM 없이 실행된다.

    python test_report9.py

test_report8의 S2는 앱팀이 보낸 JSON을 그대로 쓴 것인데, 그 JSON은 대본 줄을 '예정 시각' 순으로 정렬한 것이라
실제 순서와 달랐다 (앱팀 11/25 정정). 실제로는 대본 줄이 늦게 나가 아이(C001)의 메시지가 더 앞에 있었다:
  지민 "ㄹㅇ 관종 같음" → 수아 "자기가 인기 많은 줄 아는 듯" → 예슬 "도현이가 먼절못이 잇냐" → 민재 "그건 좀;;"
  → 예슬 "나쁜 새끼들"
"○○들" 바로 앞 3개(REPEAT_REPLY_SPAN)에 지민이 없어 '가해자를 향한 말' 보호가 걸리지 않았고, 예슬이 공격자로 세어졌다.
그 뒤로는 "한 번 공격한 아이"라 "지민아 조용히 좀 해"도 공격이 되어, "도현이 빼고"에서 aggressors=[지민, C001].

1) 앱팀이 보낸 실제 순서 재생 (withu_v0316_posttest_replay_2026-11-25, 3차 DEV 재생의 seq 순서)
2) 아이 메시지를 대본 줄 최대 3줄 앞까지 옮긴 모든 순서 (순서가 조금 달라도 같은 결과인지)
3) 넓힌 "○○들" 규칙이 우회로가 되지 않는지
"""
import io, contextlib, itertools, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_here = os.path.dirname(os.path.abspath(__file__))
with contextlib.redirect_stdout(io.StringIO()):     # test_report8의 대본·재생 도구만 가져온다
    exec(open(os.path.join(_here, "test_report8.py"), encoding="utf-8").read().split("# " + "-" * 96 + " 1")[0])
from withu import target_resolver as T

fails = 0


def check(name, cond, detail=""):
    global fails
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f"   {detail}" if detail and not cond else ""))
    fails += 0 if cond else 1


# ------------------------------------------------------------------------------------------------ 1
print("1) 사후검사2 — 앱팀이 정정한 실제 순서 (11/25 3차 재생 JSON의 seq 순서)")
ORDER = ['야 도현이 오늘 쉬는 시간에 봤냐', '또 우리 얘기하는데 갑자기 끼어듦 ㅋ', '나도 봄 ㅋㅋ', '진짜 눈치 없음', '그랬어?', '먼데',
         '맨날 저래서 짜증남', '말도 재미없고 분위기만 깨잖아', '도현이한테 왜구래', 'ㄹㅇ 관종 같음', '자기가 인기 많은 줄 아는 듯',
         '도현이가 먼절못이 잇냐', '그건 좀;;', '나쁜 새끼들', '왜? 사실인데', '도현이 앞에서는 다들 말 못 하잖아 ㅋㅋ',
         '도현이 쉬는 시간이 못봄', '말하면 또 삐질걸', 'ㅇㅇ 바로 피해자인 척함', '이번 토요일에 떡볶이 먹으러 갈 사람',
         '지민아 조용히 좀 해', '도현이 빼고']
_by = {l[1]: l for l in S2}
S2_REAL = [_by[t] for t in ORDER] + [l for l in S2 if l[1] not in ORDER]
assert sorted(S2_REAL) == sorted(S2)
st, log = play("r9a", S2_PARTS, S2_REAL)
mine = {r.mid for r in log if r.who == CHILD}
check("어느 판정에서도 C001이 aggressors에 없음", all(CHILD not in r.aggr for r in log),
      str([(r.k, r.text, r.aggr) for r in log if CHILD in r.aggr][:3]))
check("C001의 메시지가 attack_message_ids에 들어가지 않음", all(not (set(r.attack_ids) & mine) for r in log))
r = row(log, "도현이 빼고")
check("'도현이 빼고' 판정: 가해 지민만 / 피해 도현 (0.3.16: [지민, C001])", r.bully and r.aggr == [J] and r.victim == D, str(r.aggr))
check("최종 사건: C001은 주변인 (선택지가 보임), 가해자는 지민·수아",
      bool(st) and set(st["aggressors"]) == {J, S} and CHILD in [b["participant_code"] for b in st["bystanders"]],
      str(st and st["aggressors"]))
r = row(log, "나쁜 새끼들")
check("'나쁜 새끼들'은 그대로 언어적 폭력 (전송 전 욕설 경고 유지)", r.typ == "언어적 폭력" and not r.sup, f"{r.typ} {r.guard}")
r = row(log, "지민아 조용히 좀 해")
check("'지민아 조용히 좀 해'는 suppressed, guard_reason=counter_aggressor", r.sup and r.guard == "counter_aggressor",
      f"{r.typ} {r.sup} {r.guard}")

# ------------------------------------------------------------------------------------------------ 2
print("\n2) 아이 메시지가 대본 줄보다 조금 앞·뒤로 나간 모든 순서")
script = [l for l in S2 if l[0] != CHILD]
kids = [l for l in S2 if l[0] == CHILD]
base, n = [], 0
for l in S2:
    if l[0] == CHILD:
        base.append(n)
    else:
        n += 1


def build(pos):
    out, kj = [], 0
    for si in range(len(script) + 1):
        while kj < len(kids) and pos[kj] == si:
            out.append(kids[kj]); kj += 1
        if si < len(script):
            out.append(script[si])
    return out


def child_counted(lines):
    """역할 판정에서 C001의 말이 공격으로 세어지는가 (prepare만 돌린다)."""
    T.ROSTERS.clear()
    T.ROSTERS.update("sw", [{"participant_code": c, "display_name": nm} for c, nm in S2_PARTS])
    items = [{"speaker": w, "text": t, "cb": cb, "mid": f"m{k}"} for k, (w, t, cb, _, _) in enumerate(lines)]
    out = T.prepare(items, roster=T.ROSTERS.get("sw"), room_id="sw")
    return [d["text"] for d in out if d["speaker"] == CHILD and float(d.get("cb") or 0) >= T.TOX_THRESHOLD]


combos = [p for p in itertools.product(*[range(max(0, b - 3), b + 1) for b in base]) if list(p) == sorted(p)]
bad = [p for p in combos if child_counted(build(p))]
check(f"{len(combos)}가지 순서 모두 C001의 말을 공격으로 세지 않음 (0.3.16: 2400가지에서 셈)", not bad,
      f"{len(bad)}가지, 예: {[t for _, t, *_ in build(bad[0])][6:16]}" if bad else "")

# ------------------------------------------------------------------------------------------------ 3
print("\n3) 넓힌 '○○들' 규칙이 우회로가 되지 않는지")


def notes(parts, lines):
    T.ROSTERS.clear()
    code = {p: f"P{i + 1:02d}" for i, p in enumerate(parts)}
    T.ROSTERS.update("n", [{"participant_code": c, "display_name": p} for p, c in code.items()])
    items = [{"speaker": code[w], "text": t, "cb": cb} for w, t, cb in lines]
    return {t: d.get("note") for (w, t, cb), d in zip(lines, T.prepare(items, roster=T.ROSTERS.get("n"), room_id="n"))}


P = ["지민", "수아", "예슬", "민재", "도현", "하늘"]
LEAD = [("지민", "도현이 진짜 찐따 같음", .80), ("수아", "ㅇㅇ", .05), ("하늘", "오늘 숙제 뭐임", .05), ("민재", "몰라", .05),
        ("하늘", "수학인 듯", .05)]
got = notes(P, LEAD + [("예슬", "나쁜 새끼들", .90)])
check("가해자가 4~8개 앞에서 말했으면 '나쁜 새끼들'은 가해자를 향한 말 (0.3.16: 3개 안만)", got["나쁜 새끼들"] == "counter_aggressor", str(got))
got = notes(P, LEAD[:2] + [("도현", "왜 그래", .10)] + LEAD[2:] + [("예슬", "나쁜 새끼들", .90)])
check("그 사이 피해자(도현)가 말했으면 넓힌 규칙은 쓰지 않음 → 공격으로 셈", got["나쁜 새끼들"] is None, str(got))
got = notes(P, LEAD + [("도현", "너네 나쁜 새끼들", .90)])
check("피해자 본인의 '너네 나쁜 새끼들'은 공격으로 셈", got["너네 나쁜 새끼들"] is None, str(got))
got = notes(P, LEAD + [("예슬", "ㅋㅋㅋ 찐따들", .90)])
check("웃음이 섞인 '찐따들'은 공격으로 셈", got["ㅋㅋㅋ 찐따들"] is None, str(got))
got = notes(P, [("지민", "도현이 진짜 찐따 같음", .80), ("예슬", "ㅋㅋ 인정", .05)] + LEAD[2:] + [("예슬", "나쁜 새끼들", .90)])
check("가해자에게 맞장구쳤던 아이의 '나쁜 새끼들'은 공격으로 셈", got["나쁜 새끼들"] is None, str(got))
FAR = LEAD + [("하늘", "ㅇㅋ", .05), ("민재", "ㅇㅇ", .05), ("하늘", "내일 봐", .05), ("민재", "ㅂㅂ", .05)]
got = notes(P, FAR + [("예슬", "나쁜 새끼들", .90)])
check("가해자가 8개보다 앞에서 말했으면 쓰지 않음 → 공격으로 셈", got["나쁜 새끼들"] is None, str(got))
got = notes(P, LEAD + [("예슬", "도현이 같은 새끼들", .90)])
check("피해자 이름이 들어간 말은 공격으로 셈", got["도현이 같은 새끼들"] is None, str(got))

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
