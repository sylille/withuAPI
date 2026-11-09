# -*- coding: utf-8 -*-
"""
v0.3.11 동시 접속 부하 확인 (2026-11-09 사전검사: 한 반이 동시에 검사하자 응답이 0.4초 -> 14~17초)

한 반이 모둠별 방에서 동시에 대본을 진행하는 상황을 흉내 낸다. 메시지 하나마다 앱처럼
전송 전 호출(track_bystander=false) -> 전송 후 호출(true) 두 번을 보낸다.
요청은 정해진 시각에 보낸다 (앞 요청의 응답을 기다리지 않는다) -> 실제 교실처럼 서버가 밀리면 줄이 길어진다.

    python test_load.py --base http://<서버>:8000 --key $WITHU_API_KEY                 # 초당 6건, 60초
    python test_load.py --base http://127.0.0.1:8000 --key $WITHU_API_KEY --rps 6 --secs 90 --rooms 7

**검사 중인 반이 없을 때만 돌리세요.** 실서버에 부하를 주고, 가상의 방(load-...)에 사건을 엽니다.
결과: 응답 시간 중앙값·95%·최대, 2초·28초를 넘긴 비율, 그리고 끝난 뒤 /health의 analyze_ms·inference.
표준 라이브러리만 사용. 대사는 가상의 문장이다.
"""
import argparse, json, statistics, threading, time, urllib.request
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

ap = argparse.ArgumentParser()
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default=None)
ap.add_argument("--rps", type=float, default=6.0, help="초당 요청 수 (전송 전·후 호출을 모두 셈)")
ap.add_argument("--secs", type=float, default=60.0)
ap.add_argument("--rooms", type=int, default=7, help="동시에 진행하는 방 수 (모둠 수)")
ap.add_argument("--timeout", type=float, default=28.0, help="앱이 기다리는 시간과 같게")
args = ap.parse_args()
RUN = str(int(time.time()))

KIDS = [("P01", "태민"), ("P02", "건우"), ("P03", "현우"), ("P04", "서아")]
LINES = [("P01", "건우 너 진짜 왜 그러냐"), ("P02", "내가 뭘"), ("P01", "아 또 예민하게 받아들이네"),
         ("P03", "ㅋㅋㅋ"), ("P01", "건우 진짜 짜증나 너랑 안 놀아"), ("P02", "그만해"),
         ("P04", "야 그만해 건우한테 왜 그래"), ("P03", "아 배고프다"), ("P01", "건우 찐따 같아"),
         ("P04", "건우야 괜찮아?"), ("P03", "오늘 숙제 뭐였지"), ("P02", "...")]


def call(path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(args.base.rstrip("/") + path, data=data, method="POST" if data else "GET",
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    if args.key:
        req.add_header("X-API-Key", args.key)
    with urllib.request.urlopen(req, timeout=args.timeout) as r:
        return json.loads(r.read().decode())


class Room:
    def __init__(self, i):
        self.rid = f"load-{RUN}-{i}"
        self.i = 0
        self.ctx = []
        self.lock = threading.Lock()

    def next_message(self):
        with self.lock:
            spk, text = LINES[self.i % len(LINES)]
            n = self.i
            self.i += 1
        m = {"participant_code": spk, "text": text if n < len(LINES) else f"{text} {n}",
             "message_id": f"{self.rid}-m{n}",
             "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds")}
        return m

    def body(self, m, track):
        with self.lock:
            ctx = list(self.ctx[-10:])
        return {"room_id": self.rid, "context": ctx, "new_message": m, "track_bystander": track,
                "participants": [{"participant_code": c, "display_name": n} for c, n in KIDS]}

    def sent(self, m):
        with self.lock:
            self.ctx.append(m)


res = []            # (kind, ms or None, err)
res_lock = threading.Lock()


def one(room, m, track):
    t0 = time.time()
    try:
        call("/analyze", room.body(m, track))
        r = ("post" if track else "pre", int((time.time() - t0) * 1000), None)
    except Exception as e:
        r = ("post" if track else "pre", None, f"{type(e).__name__}: {e}"[:80])
    with res_lock:
        res.append(r)


def message_flow(room):
    m = room.next_message()
    one(room, m, False)
    room.sent(m)
    one(room, m, True)


print(f"health 전: {call('/health')}")
rooms = [Room(i) for i in range(args.rooms)]
msgs_per_sec = args.rps / 2                      # 메시지 하나 = 요청 두 번
n_msgs = int(args.secs * msgs_per_sec)
print(f"방 {args.rooms}개, 메시지 {n_msgs}개 (요청 {2 * n_msgs}건, 초당 {args.rps:g}건), 대기 상한 {args.timeout:g}초")
pool = ThreadPoolExecutor(max_workers=200)
start = time.time()
for k in range(n_msgs):
    target = start + k / msgs_per_sec
    d = target - time.time()
    if d > 0:
        time.sleep(d)
    pool.submit(message_flow, rooms[k % len(rooms)])
pool.shutdown(wait=True)

ok = [ms for _, ms, e in res if ms is not None]
errs = [e for _, ms, e in res if ms is None]
print(f"\n요청 {len(res)}건, 성공 {len(ok)}, 실패·시간 초과 {len(errs)} ({100 * len(errs) / max(1, len(res)):.0f}%)")
if ok:
    q = sorted(ok)
    p = lambda x: q[min(len(q) - 1, int(x * len(q)))]
    print(f"응답 ms: 중앙값 {p(0.5)}, 95% {p(0.95)}, 최대 {q[-1]}, 평균 {int(statistics.mean(q))}")
    print(f"2초 넘김 {100 * sum(1 for x in ok if x > 2000) / len(res):.0f}%")
    for kind in ("pre", "post"):
        k = sorted(ms for kk, ms, e in res if kk == kind and ms is not None)
        if k:
            print(f"  {kind:4s}: 중앙값 {k[len(k) // 2]}ms, 95% {k[min(len(k) - 1, int(0.95 * len(k)))]}ms")
if errs:
    print("실패 예:", errs[:3])
print(f"\nhealth 후: {json.dumps(call('/health'), ensure_ascii=False)}")
