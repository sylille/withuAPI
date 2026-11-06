# -*- coding: utf-8 -*-
"""
v0.3.10 확인 (2026-11-06 앱팀 확인 결과)
  맥락에 공격이 6개 이상 쌓인 뒤 '이영희 진짜 짜증나'처럼 이름으로 지목하면, 피해자가 이름 지목(C003)이 아니라
  공격 바로 뒤에 말린 아이(C001, turn_adjacency, weak)로 나옴.
  원인: 창 판정(check_chat_excel.attribute)은 이름을 참가자 코드로만 찾아 표시 이름을 못 보고, 공격 6개 이상이면
  '가까이서 말한 아이'로 먼저 열려 이름 지목 판정(resolve_target)까지 가지 않았다.
  고침: 창 판정이 turn_adjacency로만 열렸으면 resolve_target을 먼저 보고, 그쪽이 열리면 그 결과를 쓴다.

    python test_report6.py
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import target_resolver as T

fails = 0
P = [{"participant_code": "C001", "display_name": "김철수"},
     {"participant_code": "C002", "display_name": "박민수"},
     {"participant_code": "C003", "display_name": "이영희"}]
TOX, OK = 0.95, 0.05
CTX = [("C003", "오늘 체육 시간 재밌었다 ㅋㅋ", OK), ("C002", "ㅋㅋ 너 진짜 바보냐 꺼져라", TOX),
       ("C001", "박민수 그만해", OK), ("C001", "오늘 날씨 좋다", OK), ("C001", "얘들아 그만하자", OK),
       ("C002", "이영희 진짜 짜증나", TOX), ("C002", "이영희 너 바보냐 꺼져라", TOX),
       ("C002", "이영희는 빼고 놀자", TOX), ("C002", "이영희 진짜 짜증나", TOX), ("C002", "이영희 너 바보냐 꺼져라", TOX)]
NEW = [("C002", "이영희 진짜 짜증나", TOX), ("C002", "이영희 너 바보냐 꺼져라", TOX),
       ("C002", "이영희 맨날 왜 그래 진짜 싫어", TOX)]


def check(name, cond, r):
    global fails
    a = r["attr"]
    print(f"[{'PASS' if cond else 'FAIL'}] {name:44s} bully={r['is_bullying']!s:5} victim={a.victim} "
          f"via={a.victim_reason} support={r.get('victim_support')}")
    fails += 0 if cond else 1


def stream(rid, ctx, cap=None):
    T.HISTORY.clear(rid); T.ROSTERS.clear()
    hist, out = list(ctx), []
    for new in NEW:
        rows = (hist[-cap:] if cap else hist) + [new]
        out.append(T.evaluate_window_v2([dict(speaker=s, text=t, cb=c) for s, t, c in rows],
                                        room_id=rid, participants=P))
        hist.append(new)
    return out


print("1) 맥락 있음: 세 번 모두 이름 지목된 C003")
for k, r in enumerate(stream("a", CTX)):
    check(f"맥락 전체 #{k + 1}", r["is_bullying"] and r["attr"].victim == "C003"
          and r["attr"].victim_reason == "name_mention" and r["victim_support"] == "strong", r)
for k, r in enumerate(stream("b", CTX, cap=10)):
    check(f"맥락 10개 #{k + 1}", r["is_bullying"] and r["attr"].victim == "C003"
          and r["attr"].victim_reason == "name_mention", r)

print("2) 맥락 없음: 예전과 같음 (첫 번째는 기다리고, 두 번째부터 C003)")
out = stream("c", [])
check("첫 공격 하나만으로는 열지 않음", not out[0]["is_bullying"], out[0])
check("두 번째부터 C003", out[1]["is_bullying"] and out[1]["attr"].victim == "C003", out[1])

print("3) 이름이 안 나오는 대화는 예전처럼 반응한 아이가 피해자")
NONAME = [("C003", "나 왔어", OK)] + [("C002", "진짜 바보냐 꺼져라", TOX), ("C003", "왜 그래", OK)] * 3 \
         + [("C002", "진짜 바보냐 꺼져라", TOX)] * 3
T.HISTORY.clear("d"); T.ROSTERS.clear()
r = T.evaluate_window_v2([dict(speaker=s, text=t, cb=c) for s, t, c in NONAME], room_id="d", participants=P)
check("이름 없는 공격 6개 -> 반응한 C003", r["is_bullying"] and r["attr"].victim == "C003", r)

print("\nALL PASS" if fails == 0 else f"\n{fails} FAILED")
sys.exit(1 if fails else 0)
