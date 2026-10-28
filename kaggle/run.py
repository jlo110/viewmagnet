# Kaggle kernel entry point for the reach-CLIP fine-tune (GPU, internet on).
import glob
import os
import subprocess
import sys

# Upgrade transformers AND huggingface_hub together — upgrading only transformers
# leaves Kaggle's older hub, which throws "client has been closed" on model load.
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-U",
                "transformers", "huggingface_hub",
                "scikit-learn", "pillow", "requests"], check=False)

# Robustly locate the attached dataset files (mount path can vary).
print("INPUT TREE:", os.listdir("/kaggle/input") if os.path.isdir("/kaggle/input") else "NO /kaggle/input")
trainer = glob.glob("/kaggle/input/**/finetune_reach_clip.py", recursive=True)
csv = glob.glob("/kaggle/input/**/reach_dataset.csv", recursive=True)
if not trainer or not csv:
    raise SystemExit(f"dataset not attached. trainer={trainer} csv={csv}")
print("found trainer:", trainer[0])
print("found csv    :", csv[0])

sys.argv = [
    "finetune_reach_clip.py",
    "--data", csv[0],
    "--limit", "8000",      # fast first run; the 40k download stalled the kernel
    "--epochs", "6",
    "--batch", "64",
    "--unfreeze-last", "3",
    "--out", "/kaggle/working/reach_clip.pt",
    # A/B (lever #3): uncomment for the larger backbone instead.
    # "--backbone", "openai/clip-vit-large-patch14",
]
exec(open(trainer[0]).read())
