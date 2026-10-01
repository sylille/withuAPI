# -*- coding: utf-8 -*-
"""
실서버 확인: 이름 매칭(participants)과 반복 표적(repeated_target).  표준 라이브러리만 사용.

    cd ~/Downloads
    python test_target_live.py                         # http://127.0.0.1:8000
    python test_target_live.py --base https://xxx.trycloudflare.com
"""
import argparse, json, time, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default=None)
args = ap.parse_args()
RUN = str(int(time.time()))
PARTS = [{"participant_code": "C013", "display_name": "하늘"},
         {"participant_code": "C011", "display_name": "내가최고다"},
         {"participant_code": "C020", "display_name": "김민준"},
         {"participant_code": "C030", "display_name": "별이"}]
fails = 0


def analyze(room, ctx, new, parts=PARTS, track=True):
    body = {"room_id": room, "context": ctx, "new_message": new, "participants": parts, "track_bystander": track}
    req = urllib.request.Request(args.base.rstrip("/") + "/analyze", data=json.dumps(body, ensure_ascii=False).encode(),
                                 method="POST", headers={"Content-Type": "application/json; charset=utf-8"})
    if args.key:
        req.add_header("X-API-Key", args.key)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def play(room, lines, win=8):
    """send a conversation one message at a time, like the app does after each send"""
    msgs, out = [], []
    for k, (who, text) in enumerate(lines):
        m = {"participant_code": who, "text": text, "message_id": f"{room}_m{k}"}
        out.append(analyze(room, msgs[-(win - 1):], m))
        msgs.append(m)
    return out


def show(name, ok, r):
    global fails
    a = r.get("attribution") or {}
    print(f"[{'PASS' if ok else 'FAIL'}] {name:42s} is_bullying={a.get('is_bullying')} victim={a.get('victim')} "
          f"via={a.get('victim_reason')} drop={a.get('drop_reason')}  cb={r.get('cb_score')}")
    fails += 0 if ok else 1


print("server:", args.base)
# 1. 이름 + 피해자 반응
out = play(f"tl_name_{RUN}", [("C011", "하늘 너 진짜 냄새나 꺼져"), ("C013", "왜 그래...")])
show("display name + reply", out[-1]["attribution"]["is_bullying"] and out[-1]["attribution"]["victim"] == "C013", out[-1])

# 2. 이름 없음, 반복 공격 + 같은 아이 반응
out = play(f"tl_rep_{RUN}", [("C013", "나 왔어"), ("C011", "너 진짜 냄새나 꺼져"), ("C013", "왜 그래"),
                             ("C011", "역겨우니까 나가라"), ("C013", "내가 뭘 했는데"), ("C011", "병신아 꺼지라고"),
                             ("C013", "하지마 ㅠㅠ"), ("C011", "말하지마 냄새나니까 꺼져"), ("C013", "선생님한테 말할거야")])
first = next((i for i, r in enumerate(out) if r["attribution"]["is_bullying"]), None)
print("      opened at message #", first, "| cb per message:", [round(r["cb_score"], 2) for r in out])
show("repeated, no names", first is not None and out[-1]["attribution"]["victim"] == "C013", out[-1])

# 3. 같이 웃는 장난 -> 열리면 안 됨
out = play(f"tl_ban_{RUN}", [("C011", "야 꺼져 ㅋㅋ"), ("C013", "ㅋㅋㅋㅋ"), ("C011", "병신아 ㅋㅋ"), ("C013", "ㅋㅋㅋㅋㅋ 인정"),
                             ("C011", "역겨워 ㅋㅋ"), ("C013", "ㅋㅋㅋ"), ("C011", "꺼져라 ㅋㅋ"), ("C013", "ㅎㅎ")])
show("laughing along -> no incident", not any(r["attribution"]["is_bullying"] for r in out), out[-1])

print("\nALL PASS" if not fails else f"\n{fails} FAILED — 위 cb 값이 0.5 아래면 모델 점수 문제, 위면 출력을 보내 주세요")
