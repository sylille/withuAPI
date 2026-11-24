# -*- coding: utf-8 -*-
"""
v0.3.14 추론 속도 재기 (서버에서, 검사 중인 반이 없을 때). uvicorn을 띄우지 않고 모델만 직접 돌린다.

    cd ~/Downloads && source ~/python313_env/bin/activate
    python bench_infer.py                     # 하나씩 vs 묶음 속도, 묶음 점수가 하나씩과 같은지
    python bench_infer.py --quant             # + int8로 줄였을 때 속도와 점수 차이 (WITHU_QUANT=int8을 켤지 판단용)
    python bench_infer.py --texts 문장.txt     # 한 줄에 한 문장. 정답 코퍼스 문장을 넣으면 int8 비교가 더 믿을 만하다

출력
  - 모듈 A(메시지)·B(문맥 창)의 한 개당 ms: 하나씩 돌릴 때, 4·8·16개 묶음일 때
  - 묶음 점수와 하나씩 점수의 최대 차이 (1e-4보다 작아야 정상), 0.5/0.75/0.85 경계를 넘나든 개수 (0이어야 정상)
  - 대략 감당할 수 있는 대본 줄 수 (초당)
서버가 돌고 있어도 실행은 되지만 CPU를 나눠 써서 숫자가 나빠진다. 가능하면 서버를 잠시 멈추고 재세요.
"""
import argparse, os, statistics, sys, time

ap = argparse.ArgumentParser()
ap.add_argument("--texts", default=None, help="한 줄에 한 문장 (없으면 내장 예문)")
ap.add_argument("--quant", action="store_true", help="int8 모델과 점수·속도 비교")
ap.add_argument("--reps", type=int, default=3)
args = ap.parse_args()

os.environ["WITHU_BATCH"] = "0"            # 추론 스레드를 띄우지 않고 함수만 쓴다
from withu import models
from withu.models import _render_window

BUILTIN = ["건우 너 진짜 왜 그러냐", "내가 뭘", "아 또 예민하게 받아들이네", "ㅋㅋㅋ", "건우 진짜 짜증나 너랑 안 놀아",
           "그만해", "야 그만해 건우한테 왜 그래", "아 배고프다", "건우 찐따 같아", "건우야 괜찮아?", "오늘 숙제 뭐였지",
           "...", "ㅇㅇ", "왜", "꺼져", "닥쳐", "너 때문에 다 망했잖아", "우리 내일 몇 시에 만나?", "네 잘못이 아니야",
           "하지 말라고", "선생님한테 말할 거야", "그거 재밌었어 ㅋㅋ", "누가 쟤랑 놀아줌?", "빼고 가자", "나도 같이 하자",
           "사진 봤어?", "오늘 급식 맛있었어", "너 진짜 웃기다", "그만 좀 해 제발", "괜찮아 신경 쓰지 마",
           "쟤 또 저런다", "아무도 너 안 좋아해", "응 알겠어", "학원 끝나고 갈게", "그게 무슨 말이야"]
texts = BUILTIN
if args.texts:
    texts = [l.strip() for l in open(args.texts, encoding="utf-8") if l.strip()]
texts = texts[:200]
windows = [_render_window(texts[i:i + 6], [f"P{(i + k) % 4}" for k in range(6)]) for i in range(0, max(1, len(texts) - 5))]
windows = windows[:60]


def load(quant):
    models.QUANT = "int8" if quant else ""
    m = models.load_message_scorer()
    c = models.load_context_scorer()
    return m.fwd_batch, c.fwd_batch


def per_item_ms(fwd, xs, b):
    """b개씩 묶어 xs 전체를 reps번 돌린 한 개당 ms (중앙값)."""
    fwd(xs[:b])                            # 첫 호출 준비
    runs = []
    for _ in range(args.reps):
        t0 = time.perf_counter()
        for i in range(0, len(xs), b):
            fwd(xs[i:i + b])
        runs.append((time.perf_counter() - t0) * 1000 / len(xs))
    return statistics.median(runs)


def compare(name, single, other, label):
    d = max(abs(a - b) for a, b in zip(single, other))
    flips = sum(1 for a, b in zip(single, other) for th in (0.5, 0.75, 0.85) if (a >= th) != (b >= th))
    print(f"  {name}: {label} 최대 점수 차이 {d:.2e}, 경계(0.5/0.75/0.85) 넘나듦 {flips}건 / {len(single)}개")
    return d, flips


import torch
print(f"torch {torch.__version__}, 스레드 {torch.get_num_threads()}, CPU {os.cpu_count()}개, 문장 {len(texts)}개, 문맥 창 {len(windows)}개")
fm, fc = load(False)

print("\n[1] 한 개당 추론 시간 (ms)")
res = {}
for name, fwd, xs in (("모듈 A 메시지", fm, texts), ("모듈 B 문맥 창", fc, windows)):
    row = {b: per_item_ms(fwd, xs, b) for b in (1, 4, 8, 16)}
    res[name] = row
    print(f"  {name}: " + ", ".join(f"{b}개 묶음 {v:.1f}" for b, v in row.items())
          + f"  -> 16개 묶음이 하나씩보다 {row[1] / row[16]:.1f}배 빠름")

print("\n[2] 묶음 점수 = 하나씩 점수인가")
sm = [fm([t])[0] for t in texts]
sc = [fc([w])[0] for w in windows]
ok = True
for name, fwd, xs, single in (("모듈 A", fm, texts, sm), ("모듈 B", fc, windows, sc)):
    batched = []
    for i in range(0, len(xs), 16):
        batched += fwd(xs[i:i + 16])
    d, flips = compare(name, single, batched, "16개 묶음")
    ok = ok and d < 1e-4 and flips == 0
print("  -> " + ("같음 (묶음 추론을 켜도 판정은 바뀌지 않음)" if ok else "차이가 큼! WITHU_BATCH=0으로 돌리고 이 출력을 공유해 주세요"))

frac = sum(1 for v in sm if v >= 0.5) / len(sm)
a1, b1 = res["모듈 A 메시지"][1], res["모듈 B 문맥 창"][1]
a8, b8 = res["모듈 A 메시지"][8], res["모듈 B 문맥 창"][8]
print("\n[3] 대본 한 줄(전송 전·후 호출 = 새 메시지 1개 + 문맥 창 1개)에 드는 추론 시간")
print(f"  v0.3.13 (하나씩, 문맥 늘 계산): {a1 + b1:.0f}ms -> 초당 약 {1000 / (a1 + b1):.1f}줄")
print(f"  v0.3.14 (묶음, 메시지 0.5 이상일 때만 문맥 [이 예문에서 {100 * frac:.0f}%]): "
      f"{a8 + frac * b8:.0f}ms -> 초당 약 {1000 / (a8 + frac * b8):.1f}줄 (줄이 쌓일 때 기준)")
print("  (한 반 27명이 4~5초마다 한 줄 = 초당 약 6줄. Lightsail은 CPU를 오래 100% 쓰면 기본 성능으로 떨어지니 여유가 있어야 합니다)")

if args.quant:
    print("\n[4] int8 (WITHU_QUANT=int8)")
    qm, qc = load(True)
    for name, fwd, xs, single, base in (("모듈 A", qm, texts, sm, res["모듈 A 메시지"]), ("모듈 B", qc, windows, sc, res["모듈 B 문맥 창"])):
        q = []
        for i in range(0, len(xs), 16):
            q += fwd(xs[i:i + 16])
        compare(name, single, q, "int8")
        t8 = per_item_ms(fwd, xs, 8)
        print(f"     8개 묶음 한 개당 {t8:.1f}ms (fp32 {base[8]:.1f}ms, {base[8] / t8:.1f}배)")
    print("  경계를 넘나든 문장이 있으면 int8은 켜지 마세요 (정답 코퍼스 재검증 없이 판정이 바뀝니다).")
