# -*- coding: utf-8 -*-
"""
WithU Talk — Module D: 주변인 발화 분류기 (방어 / 동조 / 방관 / 비해당), server version.

Same design as the Phase 4 notebook (rubric + few-shot + JSON output + robust parsing),
but packaged as a module so app.py can import it:

    from .phase4_bystander import classify_bystander
    label, reason = classify_bystander(context_turns, speaker, text)

Differences from the notebook, on purpose:
  * Few-shot examples are SYNTHETIC (written from the 4장 표3 definitions), not rows from the
    labeled KakaoTalk corpus -> no real children's names/utterances are sent to OpenAI, and
    the server does not need the .xlsx.
  * Context speakers may carry role tags from the 방관 tracker, e.g. "P11(가해자)".

Env (provider is picked automatically from whichever key is set; Anthropic wins if both):
  ANTHROPIC_API_KEY  -> Claude  (bystander_meta.json: the notebook eval used claude-sonnet-4-6)
  OPENAI_API_KEY     -> OpenAI
  BYSTANDER_LLM_PROVIDER  force "anthropic" or "openai"
  BYSTANDER_LLM_MODEL     override the model (default: claude-sonnet-4-6 / gpt-4o-mini)
  BYSTANDER_LLM_TIMEOUT   seconds per call (default 6)
  BYSTANDER_LLM_RETRIES   extra attempts after a failure (default 1)

v0.3.3: 실패하면 빨리 끝낸다. 예전에는 실패할 때마다 1.5·3·4.5초를 쉬어 한 번에 9초가 걸렸고,
        실패 사실이 어디에도 남지 않았다. 이제 마지막 오류를 STATUS에 남기고(/health에서 보임) 로그에 찍는다.
"""
from __future__ import annotations
import json
import os
import re
import time

LABELS = ["방어", "동조", "방관", "비해당"]
PROVIDER = os.environ.get("BYSTANDER_LLM_PROVIDER") or (
    "anthropic" if os.environ.get("ANTHROPIC_API_KEY") else "openai")
MODEL = os.environ.get("BYSTANDER_LLM_MODEL") or os.environ.get("OPENAI_MODEL") if PROVIDER == "openai" \
    else os.environ.get("BYSTANDER_LLM_MODEL")
MODEL = MODEL or ("claude-sonnet-4-6" if PROVIDER == "anthropic" else "gpt-4o-mini")
TIMEOUT = float(os.environ.get("BYSTANDER_LLM_TIMEOUT", 6))
RETRIES = int(os.environ.get("BYSTANDER_LLM_RETRIES", 1))
# 마지막 호출 결과. app.py의 /health가 그대로 보여 준다.
STATUS = {"state": "unknown", "error": None, "ok": 0, "failed": 0, "last_ms": None}

RUBRIC = """너는 초등학생 단체 채팅방에서 '사이버불링이 진행 중인 상황'의 주변인(가해자·피해자가 아닌 참여자) 반응을 분류한다.
맥락의 발화자 이름 뒤 괄호는 역할이다: (가해자), (피해자), (주변인).
분류 라벨:
- 방어: 가해 중단 요구, 피해자 지지·위로·편들기, 항의, 어른에게 알리기, 괴롭힘을 멈추기 위한 화제 전환 (예: "그만해", "괜찮아?", "선생님께 말하자")
- 동조: 가해 발화에 대한 웃음·호응·동의·강화, 가해 표현 따라하기, 피해자 비난 (예: "ㅋㅋㅋ", "ㅇㅈ", "맞아", "예민하네")
- 방관: 상황을 보고도 개입 없이 사이버불링과 무관한 이야기로 넘어감
- 비해당: 주변인 반응으로 보기 어려움 (상황을 묻기만 하는 질문 등)
핵심 규칙:
1) 같은 말이라도 '누구의 발화에 반응하는가'에 따라 라벨이 달라진다. 피해자를 향한 조롱에 웃으면 동조, 가해자를 저지하면 방어.
2) 중단을 요구하면서 가해자에게 긍정적 반응을 함께 보이면("그만해 ㅋㅋ 근데 웃기긴 하다") 방어가 아니라 동조다.
3) 피해자에게 참으라고 하거나 피해자 탓을 하면 방어가 아니다."""

# synthetic exemplars (no real data): (context, speaker, target_text, label)
SHOTS = [
    ([("P11(가해자)", "지우 너 진짜 냄새나"), ("지우(피해자)", "왜 그래...")], "P05(주변인)", "그만해 너무 심하잖아", "방어"),
    ([("P11(가해자)", "쟤랑 아무도 놀지 마 ㅋㅋ")], "P07(주변인)", "지우야 괜찮아? 신경 쓰지 마", "방어"),
    ([("P11(가해자)", "돼지야 꺼져"), ("P03(주변인)", "ㅋㅋㅋ")], "P05(주변인)", "이 얘기는 여기까지 하자", "방어"),
    ([("P11(가해자)", "너 같은 애는 나가라")], "P08(주변인)", "이거 선생님한테 말할 거야", "방어"),
    ([("P11(가해자)", "지우 같은 애랑 누가 놀아")], "P03(주변인)", "ㅋㅋㅋㅋ 인정", "동조"),
    ([("P11(가해자)", "역겨우니까 나가라")], "P09(주변인)", "ㄹㅇ 나가라", "동조"),
    ([("P11(가해자)", "냄새나 진짜"), ("지우(피해자)", "그만하라고...")], "P04(주변인)", "예민하네 ㅋㅋ", "동조"),
    ([("P11(가해자)", "쟤 또 이상한 소리 한다")], "P06(주변인)", "그만해 ㅋㅋ 근데 웃기긴 하다", "동조"),
    ([("P11(가해자)", "지우 꺼져"), ("지우(피해자)", "ㅠㅠ")], "P02(주변인)", "오늘 숙제 뭐였지?", "방관"),
    ([("P11(가해자)", "너 진짜 짜증나")], "P10(주변인)", "나 학원 간다~", "방관"),
    ([("P11(가해자)", "너 진짜 답답하다")], "P12(주변인)", "무슨 일이야?", "비해당"),
]


def _render_ctx(ctx) -> str:
    return "\n".join(f"  {s}: {t}" for s, t in ctx) or "  (직전 맥락 없음)"


def build_user_prompt(context, speaker, target_text) -> str:
    parts = ["# 예시"]
    for c, s, t, lab in SHOTS:
        parts.append(f"[맥락]\n{_render_ctx(c)}\n[대상 발화] {s}: {t}\n[정답] {lab}")
    parts += ["# 분류할 항목",
              f"[맥락]\n{_render_ctx(context)}\n[대상 발화] {speaker}: {target_text}",
              '\nJSON만 출력(설명 금지): {"label":"방어|동조|방관|비해당","reason":"한 문장 근거"}']
    return "\n\n".join(parts)


_client = None
def call_llm(system: str, user: str) -> str:
    global _client
    if PROVIDER == "anthropic":
        if _client is None:
            from anthropic import Anthropic    # reads ANTHROPIC_API_KEY
            _client = Anthropic(timeout=TIMEOUT, max_retries=0)
        msg = _client.messages.create(model=MODEL, max_tokens=300, system=system,
                                      messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if _client is None:
        from openai import OpenAI              # reads OPENAI_API_KEY
        _client = OpenAI(timeout=TIMEOUT, max_retries=0)
    r = _client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
    return r.choices[0].message.content or ""


def parse_label(txt: str):
    m = re.search(r"\{.*\}", txt or "", re.DOTALL)
    if m:
        try:
            d = json.loads(m.group(0))
            if d.get("label") in LABELS:
                return d["label"], d.get("reason", "")
        except Exception:
            pass
    for lab in LABELS:                     # fallback: first label mentioned
        if lab in (txt or ""):
            return lab, "(parsed from text)"
    return "비해당", "(unparseable)"


def classify_bystander(context, speaker, target_text, retries: int = None):
    """context: [(speaker, text), ...] oldest->newest. Returns (label, reason).
    Never raises: on failure returns ('비해당', '(error: ...)'). 호출한 쪽은 reason이 '(error'로 시작하면
    LLM이 답하지 못한 것으로 보고 키워드 규칙으로 대신 판정한다 (bystander.py)."""
    retries = RETRIES if retries is None else retries
    user = build_user_prompt(context, speaker, target_text)
    last = None
    t0 = time.time()
    for i in range(retries + 1):
        try:
            out = parse_label(call_llm(RUBRIC, user))
            STATUS.update(state="ok", error=None, ok=STATUS["ok"] + 1, last_ms=int((time.time() - t0) * 1000))
            return out
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(0.3)
    err = f"{type(last).__name__}: {last}"[:300]
    if STATUS["error"] != err:                       # 같은 오류는 한 번만 찍는다
        print(f"[bystander] !! LLM 호출 실패 ({PROVIDER}/{MODEL}): {err}", flush=True)
    STATUS.update(state="error", error=err, failed=STATUS["failed"] + 1, last_ms=int((time.time() - t0) * 1000))
    return "비해당", f"(error: {err})"


# ---------------------------------------------------------------- v0.3.4: 배제 발화 확인 (C1)
EXCL_RUBRIC = """너는 초등학생 단체 채팅방의 한 메시지가 '특정 아이를 의도적으로 따돌리는 말'인지 판단한다.
규칙이 먼저 "이름 + 빼다·부르지 마·말하지 마" 같은 표현을 찾아 넘겨준 메시지다. 네가 할 일은 정당한 경우를 걸러 내는 것이다.
라벨:
- 배제: 그 아이를 놀이·모임·채팅방에서 빼려 하거나, 끼워 주지 말자·말 걸지 말자고 하거나, 그 아이만 빼고 방을 만들려는 말
- 정당: 따돌림이 아닌 경우
  1) 생일파티·선물·깜짝 이벤트처럼 당사자에게 잠시 비밀로 해야 하는 준비
  2) 조별 과제·학원 반·학생회처럼 정해진 구성원만 들어가는 방이나 활동 (그 아이가 원래 그 구성원이 아님)
  3) 그 아이가 스스로 빠지겠다고 했거나, 아파서·바빠서 못 오는 것을 전하는 말
  4) 도배·욕설 등 규칙 위반 때문에 관리 목적으로 내보내는 경우
  5) "○○ 빼고 다 왔어?"처럼 사실을 묻거나 전하는 말
맥락에 정당한 이유가 보이지 않으면 배제로 본다.
주의: "○○는 빼고 방 만들자"는 그 자체로는 배제지만, 바로 앞 맥락이 그 아이의 생일·선물·전학 선물·깜짝 이벤트 준비라면 정당이다.
표현이 아니라 '왜 빼는가'로 판단한다."""

EXCL_SHOTS = [
    ([("P1", "이번 주말에 놀이공원 가자"), ("P2", "좋아 누구누구 가")], "P1", "민서는 빼고 가자", "배제"),
    ([("P1", "걔 오면 재미없어")], "P2", "ㅇㅇ 민서 부르지 마", "배제"),
    ([("P1", "토요일이 민서 생일이래"), ("P2", "선물 뭐 사지")], "P1", "민서한테는 말하지 마 깜짝 파티 할 거야", "정당"),
    ([("P1", "과학 조별 과제 우리 조 방 만들자")], "P2", "민서는 다른 조니까 빼고 초대해", "정당"),
    ([("P1", "다들 운동장으로 와")], "P2", "민서 빼고 다 왔어?", "정당"),
    ([("P1", "민서 오늘 아파서 못 온대")], "P2", "그럼 민서는 빼고 하자 다음에 같이 하고", "정당"),
    ([("P1", "우리끼리 방 새로 만들까")], "P2", "민서 없는 방으로 만들자 걔 짜증나", "배제"),
    ([("P1", "민서 다음 주에 전학 간대"), ("P2", "롤링페이퍼 써 주자")], "P1", "민서는 빼고 방 만들자 몰래 준비하게", "정당"),
    ([("P1", "민서 생일 선물 같이 살 사람"), ("P2", "나")], "P2", "민서는 빼고 방 만들자", "정당"),
]


def judge_exclusion(context, speaker, target_text, retries: int = None):
    """배제 발화 규칙에 걸린 메시지를 확인한다. Returns True(배제) | False(정당한 목적) | None(LLM이 답하지 못함).
    None이면 호출한 쪽(target_resolver)은 규칙대로 센다."""
    retries = RETRIES if retries is None else retries
    parts = ["# 예시"]
    for c, s, t, lab in EXCL_SHOTS:
        parts.append(f"[맥락]\n{_render_ctx(c)}\n[대상 발화] {s}: {t}\n[정답] {lab}")
    parts += ["# 판단할 항목", f"[맥락]\n{_render_ctx(context)}\n[대상 발화] {speaker}: {target_text}",
              '\nJSON만 출력(설명 금지): {"label":"배제|정당","reason":"한 문장 근거"}']
    user = "\n\n".join(parts)
    last = None
    for i in range(retries + 1):
        try:
            txt = call_llm(EXCL_RUBRIC, user)
            STATUS.update(state="ok", error=None, ok=STATUS["ok"] + 1)
            m = re.search(r"\{.*\}", txt or "", re.DOTALL)
            label = None
            if m:
                try:
                    label = json.loads(m.group(0)).get("label")
                except Exception:
                    label = None
            if label not in ("배제", "정당"):
                label = "정당" if "정당" in (txt or "") and "배제" not in (txt or "") else ("배제" if "배제" in (txt or "") else None)
            return None if label is None else (label == "배제")
        except Exception as e:
            last = e
            if i < retries:
                time.sleep(0.3)
    err = f"{type(last).__name__}: {last}"[:300]
    if STATUS["error"] != err:
        print(f"[exclusion] !! LLM 호출 실패 ({PROVIDER}/{MODEL}): {err}", flush=True)
    STATUS.update(state="error", error=err, failed=STATUS["failed"] + 1)
    return None


def self_check():
    """서버 시작 때 한 번 불러 LLM이 실제로 답하는지 확인한다. 결과는 STATUS에 남는다."""
    lab, why = classify_bystander([("P11(가해자)", "너 진짜 냄새나 꺼져")], "P05(주변인)", "야 그만해", retries=0)
    ok = not str(why).startswith("(error")
    print(f"[bystander] LLM 확인: {'정상' if ok else '실패'} ({PROVIDER}/{MODEL}) -> {lab} {'' if ok else why}", flush=True)
    return ok


if __name__ == "__main__":             # quick live check:  python -m withu.phase4_bystander
    tests = [
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져")], "P05(주변인)", "ㅋㅋㅋ 맞아"),
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져"), ("하늘(피해자)", "왜 그래..")], "P06(주변인)", "야 그만해"),
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져")], "P07(주변인)", "너네 내일 소풍 가?"),
    ]
    print("provider:", PROVIDER, "| model:", MODEL)
    for c, s, t in tests:
        print(f"{t!r:20} ->", classify_bystander(c, s, t))
