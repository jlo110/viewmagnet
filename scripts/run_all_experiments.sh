#!/bin/bash
# Run all experiments sequentially

cd "$(dirname "$0")/.."
source venv312/bin/activate

# Clear previous results
rm -f data/cache/results.txt

echo "=============================================="
echo "🚀 RUNNING ALL EXPERIMENTS"
echo "=============================================="
echo ""

# Experiment 1 first (generates cached data)
echo "▶️ Running Experiment 1: LightGBM Baseline..."
python scripts/exp1_baseline.py
echo ""

# Run rest in sequence
echo "▶️ Running Experiment 2: Neural Network..."
python scripts/exp2_neural_net.py
echo ""

echo "▶️ Running Experiment 3: LightGBM Tuned..."
python scripts/exp3_lgbm_tuned.py
echo ""

echo "▶️ Running Experiment 4: Deep MLP..."
python scripts/exp4_deep_mlp.py
echo ""

echo "▶️ Running Experiment 5: XGBoost..."
python scripts/exp5_xgboost.py
echo ""

echo "▶️ Running Experiment 6: Large Embeddings..."
python scripts/exp6_large_embeddings.py
echo ""

echo "=============================================="
echo "📊 ALL RESULTS"
echo "=============================================="
cat data/cache/results.txt
echo ""
echo "✅ All experiments complete!"




