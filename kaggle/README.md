# Run the reach-CLIP fine-tune on Kaggle (free GPU)

Headless GPU training via the Kaggle CLI. Once authed, all steps are scriptable
from this repo.

## One-time auth (yours — I can't create your account)
1. kaggle.com → your avatar → **Settings** → **Create New API Token** → downloads `kaggle.json`.
2. `mkdir -p ~/.kaggle && mv ~/Downloads/kaggle.json ~/.kaggle/ && chmod 600 ~/.kaggle/kaggle.json`
3. **Verify your phone** on Kaggle (Settings → Phone) — required to enable a kernel's Internet,
   which we need to download thumbnails + CLIP weights.
4. `pip install kaggle`

## Fill in your username
Replace `USERNAME` in both `kaggle/data/dataset-metadata.json` and
`kaggle/kernel-metadata.json` with your Kaggle username (lowercase). Or run:
```
U=$(kaggle config view 2>/dev/null | sed -n 's/.*username: //p')   # your kaggle username
sed -i '' "s/USERNAME/$U/g" kaggle/data/dataset-metadata.json kaggle/kernel-metadata.json
```

## Push + run
```
# 1. upload the data + trainer as a private dataset
kaggle datasets create -p kaggle/data

# 2. push the kernel (starts the GPU run headless)
kaggle kernels push -p kaggle

# 3. watch it
kaggle kernels status  USERNAME/reach-clip-finetune

# 4. when complete, pull the model + logs
kaggle kernels output  USERNAME/reach-clip-finetune -p kaggle/out
kaggle kernels output  USERNAME/reach-clip-finetune --log
```

Output: `kaggle/out/reach_clip.pt` (best-val-AUC checkpoint) + the per-epoch
`val AUC` log. **Gate:** keep it only if val AUC beats the frozen baseline 0.615;
otherwise the frozen `data/models/reach_predictor.pkl` stays as fallback.

## A/B the bigger backbone (lever #3)
Uncomment the `--backbone openai/clip-vit-large-patch14` line in `kaggle/run.py`,
re-push as a separate kernel, compare val AUC. Bigger can overfit on this data
size — only adopt if it clearly wins.

## Notes
- Free quota: ~30 GPU-hours/week (T4). This job (CLIP-B/32, 40k rows, 6 epochs)
  is well under an hour.
- The kernel pip-installs transformers and downloads ~40k thumbnails on the box
  (a few min) before training.
