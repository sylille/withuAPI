# -*- coding: utf-8 -*-
"""
대본(요청 순서 JSON)을 실서버에 그대로 다시 보내고, 줄마다의 판정과 최종 사건을 보여 준다. 표준 라이브러리만 사용.

    python test_scripts_live.py 01_usability_1_verbal.json 02_post_1_verbal.json ...   # http://127.0.0.1:8000
    python test_scripts_live.py --base https://xxx.trycloudflare.com *.json
    python test_scripts_live.py --quiet --save-scores scores.json *.json               # 최종 결과만 + 모듈 A 점수 저장

JSON 형식 (셋 중 하나)
  1) /analyze 요청 본문을 보낸 순서대로 담은 배열:            [ {room_id, context, new_message, participants, ...}, ... ]
  2) 기대값을 함께 적은 객체:   { "name": "사후검사 1", "expected": {"aggressors": ["P01","P02"], "victim": "P03"},
                                 "requests": [ ...위와 같은 배열... ] }
     expected가 "사건 없음"이면 {"incident": false}.
  3) 앱팀 재현 파일 (v0.3.5):   { "title": ..., "script_roles": {"가해": [이름], "피해": [이름], "동조"/"주변인": [이름]},
                                 "characters": [{display_name, participant_code, role}],
                                 "requests": [ {"line", "offset_seconds", "speaker", "body": {요청 본문}} ] }
     기대값은 script_roles에서 만든다. 가해자는 대본의 '가해'와 같아야 하고, 피해자는 '피해'이며 confirmed여야 한다.

서버는 방마다 기록을 기억하므로, 실행할 때마다 room_id 뒤에 실행 번호를 붙여 새 방으로 보낸다.
--save-scores: 줄마다의 모듈 A 점수(module_scores.message)를 {대본 제목: [[줄, 말한 아이, 본문, 점수], ...]}로 저장한다.
               서버 없이 판정 규칙만 다시 돌려 볼 때 쓴다 (대본 본문이 들어 있으니 공개 저장소에는 올리지 않는다).
"""
import argparse, json, sys, time, urllib.parse, urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("files", nargs="+")
ap.add_argument("--base", default="http://127.0.0.1:8000")
ap.add_argument("--key", default=None)
ap.add_argument("--quiet", action="store_true", help="줄마다의 판정은 생략하고 최종 결과만")
ap.add_argument("--save-scores", default=None, metavar="FILE", help="줄마다의 모듈 A 점수를 JSON으로 저장")
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


def load(path):
    """-> (제목, [요청 본문], 기대값 dict, {code: 이름})"""
    doc = json.load(open(path, encoding="utf-8"))
    if isinstance(doc, list):
        return path, doc, {}, {}
    names = {c["participant_code"]: c.get("display_name") or c["participant_code"] for c in doc.get("characters") or []}
    reqs = [r["body"] if isinstance(r, dict) and "body" in r else r for r in doc.get("requests", [])]
    exp = doc.get("expected") or {}
    roles = doc.get("script_roles")
    if roles and not exp:                      # 앱팀 재현 파일: 이름 -> 코드
        code = {v: k for k, v in names.items()}
        unknown = [n for k in ("가해", "피해", "동조") for n in roles.get(k, []) if n not in code]
        if unknown:
            print(f"  ! {path}: script_roles의 이름 {unknown}이(가) characters의 display_name에 없습니다 (기대값을 맞출 수 없음)")
        if roles.get("피해"):
            exp = {"aggressors": [code.get(n, n) for n in roles.get("가해", [])],
                   "victim": code.get(roles["피해"][0], roles["피해"][0]),
                   "allies": [code.get(n, n) for n in roles.get("동조", [])],     # 가해자로 나와도 따로 표시만 한다
                   "confirmed": True}
        elif not roles.get("가해"):
            exp = {"incident": False}             # 가해·피해가 없는 대본 = 사건이 열리면 안 됨
    return doc.get("title") or doc.get("name") or path, reqs, exp, names


health = call("GET", "/health")
print(f"서버 {args.base}  version {health.get('version')}  bystander_llm {health.get('bystander_llm')}")
fails = total = 0
scores = {}
for path in args.files:
    title, reqs, exp, names = load(path)
    nm = lambda c: names.get(c, c)
    print(f"\n■ {title}  ({len(reqs)}줄)")
    room, opened_at, confirmed_at, seen_victims = None, None, None, []
    rows = scores.setdefault(title, [])
    for k, body in enumerate(reqs, 1):
        body = dict(body)
        room = f"{body['room_id']}_{RUN}"
        body["room_id"] = room
        for p in body.get("participants") or []:
            names.setdefault(p["participant_code"], p.get("display_name") or p["participant_code"])
        r = call("POST", "/analyze", body)
        a = r.get("attribution") or {}
        new = body["new_message"]
        if body.get("track_bystander", True):       # 전송 전 호출(같은 줄을 한 번 더 보낸 것)은 점수 표에 넣지 않는다
            rows.append([k, nm(new["participant_code"]), new.get("text", ""), (r.get("module_scores") or {}).get("message")])
        st = r.get("bystander_state")
        if st:
            opened_at = opened_at or k
            if st["victim"] not in [v for v, _ in seen_victims]:
                seen_victims.append((st["victim"], k))
            if st.get("victim_status") == "confirmed" and confirmed_at is None:
                confirmed_at = k
        if not args.quiet and body.get("track_bystander", True):
            verdict = (f"가해 {[nm(x) for x in a.get('aggressors') or []]} 피해 {nm(a.get('victim'))} "
                       f"({a.get('victim_reason')}, {a.get('victim_support')})") if a.get("is_bullying") \
                else f"- ({a.get('drop_reason') or '공격 없음'})"
            print(f"  {k:2d} {nm(new['participant_code'])} 「{new.get('text', '')}」 m={(r.get('module_scores') or {}).get('message')} {r.get('cb_type')} → {verdict}"
                  + (f" | 사건 피해 {nm(st['victim'])}({st['victim_status']})" if st else "")
                  + (f" | 주변인 판정 {r['bystander_behavior']}" if r.get("bystander_behavior") else ""))
    if room is None:
        continue
    st = call("GET", "/bystander/state?room_id=" + urllib.parse.quote(room)).get("incident")
    if st:
        print(f"  최종: 가해 {[nm(x) for x in st['aggressors']]} / 피해 {nm(st['victim'])} "
              f"({st.get('victim_reason')}, {st.get('victim_status')}) / 이전 피해자 {[nm(x) for x in st.get('previous_victims', [])]}"
              f" / 공격 {st['n_attack_messages']}줄")
        print(f"  주변인: {[(nm(b['participant_code']), b['stage'], b['behavior']) for b in st['bystanders']]}")
        print(f"  사건이 열린 줄 {opened_at}, confirmed가 된 줄 {confirmed_at}, 피해자로 잡힌 순서 {[(nm(v), k) for v, k in seen_victims]}")
    else:
        print("  최종: 사건 없음")
    if exp:
        total += 1
        if exp.get("incident") is False:
            ok = st is None
        else:
            ok = bool(st) and st["victim"] == exp.get("victim") \
                and sorted(st["aggressors"]) == sorted(exp.get("aggressors") or []) \
                and (not exp.get("confirmed") or st.get("victim_status") == "confirmed")
        notes = []
        if st and exp.get("incident") is not False:
            extra = sorted(set(st["aggressors"]) - set(exp.get("aggressors") or []))
            missing = sorted(set(exp.get("aggressors") or []) - set(st["aggressors"]))
            if extra:
                notes.append("대본에 없는 가해자 " + str([nm(x) + ("(대본상 동조)" if x in exp.get("allies", []) else "") for x in extra]))
            if missing:
                notes.append("빠진 가해자 " + str([nm(x) for x in missing]))
            if len(seen_victims) > 1:
                notes.append("피해자가 도중에 바뀜")
        fails += 0 if ok else 1
        print(f"  [{'맞음' if ok else '틀림'}] 기대: " + ("사건 없음" if exp.get("incident") is False
              else f"가해 {[nm(x) for x in exp.get('aggressors') or []]} / 피해 {nm(exp.get('victim'))}"
                   + (" (confirmed)" if exp.get("confirmed") else "")) + ("   ※ " + ", ".join(notes) if notes else ""))

if args.save_scores:
    json.dump(scores, open(args.save_scores, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"\n모듈 A 점수 저장: {args.save_scores}")
if total:
    print(f"\n{total - fails}/{total} 편 일치")
sys.exit(1 if fails else 0)
