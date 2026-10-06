# -*- coding: utf-8 -*-
"""
대본(요청 순서 JSON)을 실서버에 그대로 다시 보내고, 줄마다의 판정과 최종 사건을 보여 준다. 표준 라이브러리만 사용.

    python test_scripts_live.py 사후1.json 사후2.json ...            # http://127.0.0.1:8000
    python test_scripts_live.py --base https://xxx.trycloudflare.com *.json

JSON 형식 (둘 중 하나)
  1) /analyze 요청 본문을 보낸 순서대로 담은 배열:            [ {room_id, context, new_message, participants, ...}, ... ]
  2) 기대값을 함께 적은 객체:   { "name": "사후검사 1", "expected": {"aggressors": ["P01","P02"], "victim": "P03"},
                                 "requests": [ ...위와 같은 배열... ] }
     expected가 "사건 없음"이면 {"incident": false}.

서버는 방마다 기록을 기억하므로, 실행할 때마다 room_id 뒤에 실행 번호를 붙여 새 방으로 보낸다.
"""
import argparse, json, sys, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="+")
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default=None)
ap.add_argument("--quiet", action="store_true", help="줄마다의 판정은 생략하고 최종 결과만")
args = ap.parse_args()
RUN = str(int(time.time()))


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(args.base.rstrip("/") + path, data=data, method=method,
                                 headers={"Content-Type": "application/json; charset=utf-8"})
    if args.key:
        req.add_header("X-API-Key", args.key)
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read().decode())


fails = total = 0
for path in args.files:
    doc = json.load(open(path, encoding="utf-8"))
    reqs = doc if isinstance(doc, list) else doc.get("requests", [])
    exp = {} if isinstance(doc, list) else (doc.get("expected") or {})
    title = path if isinstance(doc, list) else doc.get("name", path)
    names = {}
    print(f"\n■ {title}  ({len(reqs)}줄)")
    room = None
    for k, body in enumerate(reqs, 1):
        body = dict(body)
        room = f"{body['room_id']}_{RUN}"
        body["room_id"] = room
        for p in body.get("participants") or []:
            names[p["participant_code"]] = p.get("display_name") or p["participant_code"]
        nm = lambda c: names.get(c, c)
        r = call("POST", "/analyze", body)
        a = r.get("attribution") or {}
        if not args.quiet and body.get("track_bystander", True):
            new = body["new_message"]
            verdict = (f"가해 {[nm(x) for x in a.get('aggressors') or []]} 피해 {nm(a.get('victim'))} "
                       f"({a.get('victim_reason')}, {a.get('victim_support')})") if a.get("is_bullying") \
                else f"- ({a.get('drop_reason') or '공격 없음'})"
            print(f"  {k:2d} {nm(new['participant_code'])} 「{new.get('text', '')}」 cb={r.get('cb_score')} {r.get('cb_type')} → {verdict}"
                  + (f" | 주변인 판정 {r['bystander_behavior']}" if r.get("bystander_behavior") else ""))
    if room is None:
        continue
    st = call("GET", "/bystander/state?room_id=" + urllib.parse.quote(room)).get("incident")
    nm = lambda c: names.get(c, c)
    if st:
        print(f"  최종: 가해 {[nm(x) for x in st['aggressors']]} / 피해 {nm(st['victim'])} "
              f"({st.get('victim_reason')}, {st.get('victim_status')}) / 이전 피해자 {[nm(x) for x in st.get('previous_victims', [])]}"
              f" / 공격 {st['n_attack_messages']}줄")
        print(f"  주변인: {[(nm(b['participant_code']), b['stage'], b['behavior']) for b in st['bystanders']]}")
    else:
        print("  최종: 사건 없음")
    if exp:
        total += 1
        if exp.get("incident") is False:
            ok = st is None
        else:
            ok = bool(st) and st["victim"] == exp.get("victim") \
                and sorted(st["aggressors"]) == sorted(exp.get("aggressors") or [])
        fails += 0 if ok else 1
        print(f"  [{'맞음' if ok else '틀림'}] 기대: " + ("사건 없음" if exp.get("incident") is False
              else f"가해 {[nm(x) for x in exp.get('aggressors') or []]} / 피해 {nm(exp.get('victim'))}"))

if total:
    print(f"\n{total - fails}/{total} 편 일치")
sys.exit(1 if fails else 0)
