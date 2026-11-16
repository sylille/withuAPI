# -*- coding: utf-8 -*-
"""
v0.3.12 서버에서 실제 모듈 A로 짧은 글자 점수를 확인한다 (서버를 끄지 않아도 됨, ~/Downloads에서 실행).
  - raw: 모델 점수 그대로, adj: 짧은 글자 가드 뒤 점수
  - '!!' 표시: 분명한 욕설이 아닌데 가드 뒤에도 0.50 이상 -> FILLERS에 더하거나 WITHU_SHORT_UNSURE_HI를 올릴 후보
  - '??' 표시: 분명한 욕설인데 가드 뒤에도 0.50 미만

    python check_short_scores.py                 # 아래 목록
    python check_short_scores.py "ㅇㅇ" "왜" ...  # 직접 넣은 글자
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from withu import models, short_text as S

TEXTS = sys.argv[1:] or [
    "ㅇㅇ", "ㅇㅇㅇ", "왜", "ㄴ", "ㄴㄴ", "절대", "없겠지", "안양하세요", "안녕", "ㅎㅇ", "응", "어", "네", "넹", "ㅇㅋ", "오키",
    "ㅋㅋ", "ㅋㅋㅋㅋ", "ㅎㅎ", "ㅠㅠ", "?", "??", "헐", "대박", "진짜", "ㄹㅇ", "ㅇㅈ", "몰라", "뭐", "뭐야", "아니", "그래",
    "맞아", "나도", "ㄱㄱ", "ㅂㅂ", "잘가", "고마워", "미안", "ㅗㅜㅑ", "ㄷㄷ", "학교", "숙제", "배고파", "졸려",
    "입 ㄷㅊ", "ㅗㅗ", "ㅗ", "싫음 ㄲㅈ", "ㄲㅈ", "ㅅㅂ", "ㅂㅅ", "ㅈㄹ", "ㅁㅊ", "ㅈㄴ", "꺼져", "닥쳐", "바보", "찐따", "너 싫어", "미친", "짜증나", "니 미쳤냐", "꺼지라고", "저리가",
]
score = models.load_message_scorer()
print(f"SHORT_MAX_SYL={S.SHORT_MAX_SYL} UNSURE_HI={S.SHORT_UNSURE_HI} CAP={S.SHORT_CAP} JAMO_FLOOR={S.JAMO_FLOOR}\n")
for t in TEXTS:
    raw = score(t)
    adj, why = S.short_guard(t, raw)
    h = S.hostile(t)
    mark = "!!" if (h != "strong" and adj >= S.TOX_THRESHOLD) else ("??" if (h == "strong" and adj < S.TOX_THRESHOLD) else "  ")
    print(f"{mark} {t!r:14} raw={raw:.4f} adj={adj:.4f} {why or ''} {('욕설:' + h) if h else ''}")
