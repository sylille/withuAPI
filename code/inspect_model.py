# -*- coding: utf-8 -*-
"""
RUN THIS FIRST on the server, before wiring anything.
It confirms your copied folder is loadable and prints the label map so you know
which output index means "violence" (positive_label for load_classifier).

    python inspect_model.py /path/to/your/moduleA_checkpoint
"""
import sys, os

def main(model_dir):
    print("dir:", model_dir)
    if not os.path.isdir(model_dir):
        print("  !! not a directory. Point this at the folder that CONTAINS config.json.")
        return
    files = sorted(os.listdir(model_dir))
    print("  files:", files)
    need_weights = any(f.startswith(("model.safetensors", "pytorch_model")) for f in files)
    has_config   = "config.json" in files
    has_tok      = any(f in files for f in
                       ("tokenizer_config.json", "vocab.txt", "tokenizer.json", "spm.model"))
    print(f"  config.json={has_config}  weights={need_weights}  tokenizer_files={has_tok}")
    if not has_config or not need_weights:
        print("  !! Missing config.json or weights. If you copied a parent folder, point at the")
        print("     specific checkpoint-XXXX subfolder. If you copied a checkpoint, it should be OK.")
    if not has_tok:
        print("  note: no tokenizer files here -> pass base_tokenizer='beomi/KcELECTRA-base'")

    from transformers import AutoModelForSequenceClassification
    model = AutoModelForSequenceClassification.from_pretrained(model_dir)
    print("  id2label:", dict(model.config.id2label))
    print("  -> set positive_label to the index/label that means violence/hate above.")

    # quick smoke test if tokenizer is present
    if has_tok:
        import torch, torch.nn.functional as F
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained(model_dir)
        for t in ["너 진짜 역겹다 꺼져", "네 잘못이 아니야", "안녕 오늘 뭐해?"]:
            enc = tok(t, return_tensors="pt", truncation=True, max_length=256)
            with torch.no_grad():
                p = F.softmax(model(**enc).logits, dim=-1)[0].tolist()
            print(f"    {t!r:24} probs={[round(x,3) for x in p]}")
        print("  -> the aggressive line should put high prob on your violence index.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("usage: python inspect_model.py /path/to/checkpoint"); sys.exit(1)
    main(sys.argv[1])
