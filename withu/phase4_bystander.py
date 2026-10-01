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
  BYSTANDER_LLM_TIMEOUT   seconds per call (default 10)
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
TIMEOUT = float(os.environ.get("BYSTANDER_LLM_TIMEOUT", 10))

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
            _client = Anthropic(timeout=TIMEOUT)
        msg = _client.messages.create(model=MODEL, max_tokens=300, system=system,
                                      messages=[{"role": "user", "content": user}])
        return "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if _client is None:
        from openai import OpenAI              # reads OPENAI_API_KEY
        _client = OpenAI(timeout=TIMEOUT)
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


def classify_bystander(context, speaker, target_text, retries: int = 2):
    """context: [(speaker, text), ...] oldest->newest. Returns (label, reason).
    Never raises: on repeated failure returns ('비해당', '(error: ...)') so nothing is triggered."""
    user = build_user_prompt(context, speaker, target_text)
    last = None
    for i in range(retries + 1):
        try:
            return parse_label(call_llm(RUBRIC, user))
        except Exception as e:
            last = e
            time.sleep(1.5 * (i + 1))
    return "비해당", f"(error: {last})"


if __name__ == "__main__":             # quick live check:  python -m withu.phase4_bystander
    tests = [
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져")], "P05(주변인)", "ㅋㅋㅋ 맞아"),
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져"), ("하늘(피해자)", "왜 그래..")], "P06(주변인)", "야 그만해"),
        ([("P11(가해자)", "하늘 너 진짜 냄새나 꺼져")], "P07(주변인)", "너네 내일 소풍 가?"),
    ]
    print("provider:", PROVIDER, "| model:", MODEL)
    for c, s, t in tests:
        print(f"{t!r:20} ->", classify_bystander(c, s, t))
