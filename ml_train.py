"""
⚡ ML Phase 2: XGBoost Training on 4H FVG Dataset v2
=====================================================
Multi-asset dataset → XGBoost (강화 정규화) → AUC + 상위 확률 구간 평가

변경점 v2:
- Feature 20→15 (is_trending, gap_atr_ratio, trend_48bars, impulse_purity, hour_of_day 제거)
- max_depth 3→2, min_child_weight 5→10, reg_lambda 3→5
- 상위 확률 20% 구간 실제 승률 평가 추가
- Expanding CV에서 fold 0 제외 (과적합 의심)
- asset별 성과 분석

사용법:
  python ml_train.py
"""

import pandas as pd
import numpy as np
from xgboost import XGBClassifier
from sklearn.metrics import roc_auc_score, accuracy_score, confusion_matrix

# ═══════════════════════════════════════
# Config
# ═══════════════════════════════════════

DATASET_PATH = "ml_fvg_dataset.csv"
TARGET_RR = "15"  # label_rr15 (RR 1.5)

# 15 features (제거: is_trending, gap_atr_ratio, trend_48bars, impulse_purity, hour_of_day)
FEATURE_COLS = [
    "gap_pct", "swing_count",
    "dist_to_swing_high_pct", "dist_to_swing_low_pct", "higher_tf_trend",
    "rsi_14", "rsi_delta_16bars", "bb_position", "vol_ratio", "vol_surge_15m",
    "prev_fvg_same_dir_dist", "prev_fvg_filled",
    "consecutive_dir_bars", "day_of_week",
    "atr_percentile",
]

LABEL_COL = f"label_rr{TARGET_RR}"

# Regularized XGBoost params
XGB_PARAMS = dict(
    n_estimators=200,
    max_depth=2,
    learning_rate=0.03,
    subsample=0.7,
    colsample_bytree=0.7,
    min_child_weight=10,
    reg_alpha=2.0,
    reg_lambda=5.0,
    eval_metric="auc",
    random_state=42,
    verbosity=0,
)


def load_data():
    """CSV 로드 + timeout 제외"""
    df = pd.read_csv(DATASET_PATH)
    print(f"📥 로드: {len(df)}행")

    # timeout (label=-1) 제외
    before = len(df)
    df = df[df[LABEL_COL] != -1].copy()
    print(f"   timeout 제외: {before} → {len(df)}행")

    # feature 존재 확인
    missing = [c for c in FEATURE_COLS if c not in df.columns]
    if missing:
        print(f"   ⚠️ 누락 feature: {missing}")
        for c in missing:
            FEATURE_COLS.remove(c)

    return df


def top_quantile_analysis(y_true, y_proba, quantiles=[0.2, 0.3, 0.5]):
    """상위 확률 구간별 실제 승률 분석"""
    results = []
    for q in quantiles:
        threshold = np.quantile(y_proba, 1 - q)
        mask = y_proba >= threshold
        n = mask.sum()
        if n == 0:
            continue
        wr = y_true[mask].mean() * 100
        results.append((q, threshold, n, wr))
    return results


def train_holdout(df: pd.DataFrame):
    """70/15/15 holdout split 학습 + 평가"""
    print(f"\n{'═' * 60}")
    print(f"  📊 Holdout Split (train/val/test)")
    print(f"{'═' * 60}")

    train = df[df["split"] == "train"]
    val = df[df["split"] == "val"]
    test = df[df["split"] == "test"]
    print(f"   train: {len(train)} | val: {len(val)} | test: {len(test)}")

    X_train, y_train = train[FEATURE_COLS], train[LABEL_COL]
    X_val, y_val = val[FEATURE_COLS], val[LABEL_COL]
    X_test, y_test = test[FEATURE_COLS], test[LABEL_COL]

    model = XGBClassifier(**XGB_PARAMS)
    model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

    # Evaluate
    for name, X, y in [("train", X_train, y_train),
                       ("val", X_val, y_val),
                       ("test", X_test, y_test)]:
        if len(y.unique()) < 2:
            print(f"\n   {name}: 단일 클래스 — AUC 계산 불가")
            continue
        proba = model.predict_proba(X)[:, 1]
        preds = model.predict(X)
        auc = roc_auc_score(y, proba)
        acc = accuracy_score(y, preds)
        print(f"\n   [{name}] AUC={auc:.4f}  Acc={acc:.4f}  (n={len(y)})")
        if name in ("val", "test"):
            cm = confusion_matrix(y, preds)
            print(f"   Confusion: TN={cm[0][0]} FP={cm[0][1]} FN={cm[1][0]} TP={cm[1][1]}")

    # Top quantile analysis on test
    if len(y_test.unique()) >= 2:
        test_proba = model.predict_proba(X_test)[:, 1]
        base_wr = y_test.mean() * 100
        print(f"\n{'─' * 60}")
        print(f"  🎯 상위 확률 구간 승률 (test, baseline={base_wr:.1f}%)")
        print(f"{'─' * 60}")
        tqa = top_quantile_analysis(y_test.values, test_proba)
        for q, thresh, n, wr in tqa:
            delta = wr - base_wr
            marker = " ✅" if delta > 10 else ""
            print(f"   상위 {q*100:.0f}% (n={n}, thresh≥{thresh:.3f}): "
                  f"승률 {wr:.1f}% (Δ{delta:+.1f}%){marker}")

    # Feature importance
    print(f"\n{'─' * 60}")
    print("  🔑 Feature Importance (gain)")
    print(f"{'─' * 60}")
    importances = model.feature_importances_
    feat_imp = sorted(zip(FEATURE_COLS, importances), key=lambda x: -x[1])
    max_imp = max(importances) if max(importances) > 0 else 1
    for fname, imp in feat_imp:
        bar = "█" * int(imp / max_imp * 20)
        print(f"   {fname:28s} {imp:.4f}  {bar}")

    return model


def train_expanding_cv(df: pd.DataFrame):
    """Expanding window CV (fold 0 제외 — 과적합 의심)"""
    print(f"\n{'═' * 60}")
    print(f"  📊 Expanding Window CV (fold 1-3, fold 0 제외)")
    print(f"{'═' * 60}")

    fold_aucs = []
    fold_top20_wrs = []

    for fold in range(1, 4):  # fold 0 제외
        train_mask = (df["fold_id"] == -1) | (df["fold_id"] < fold)
        test_mask = df["fold_id"] == fold

        train_df = df[train_mask]
        test_df = df[test_mask]

        if len(test_df) < 5 or len(train_df) < 20:
            print(f"   fold {fold}: 데이터 부족")
            continue

        X_train, y_train = train_df[FEATURE_COLS], train_df[LABEL_COL]
        X_test, y_test = test_df[FEATURE_COLS], test_df[LABEL_COL]

        if len(y_test.unique()) < 2:
            print(f"   fold {fold}: 단일 클래스 — skip")
            continue

        model = XGBClassifier(**XGB_PARAMS)
        model.fit(X_train, y_train, verbose=False)

        proba = model.predict_proba(X_test)[:, 1]
        auc = roc_auc_score(y_test, proba)
        acc = accuracy_score(y_test, model.predict(X_test))
        fold_aucs.append(auc)

        base_wr = y_test.mean() * 100

        # Top 30% win rate (상위 20%는 n이 너무 작을 수 있으므로 30%)
        tqa = top_quantile_analysis(y_test.values, proba, [0.3])
        top_wr_str = ""
        if tqa:
            _, _, n_top, wr_top = tqa[0]
            fold_top20_wrs.append(wr_top)
            top_wr_str = f"  top30%={wr_top:.0f}%(n={n_top})"

        print(f"   fold {fold}: AUC={auc:.4f}  Acc={acc:.4f}  "
              f"base_wr={base_wr:.1f}%{top_wr_str}  "
              f"(train={len(train_df)}, test={len(test_df)})")

    if fold_aucs:
        mean_auc = np.mean(fold_aucs)
        std_auc = np.std(fold_aucs)
        print(f"\n   평균 AUC (fold 1-3): {mean_auc:.4f} ± {std_auc:.4f}")

        if fold_top20_wrs:
            mean_top = np.mean(fold_top20_wrs)
            print(f"   평균 상위30% 승률: {mean_top:.1f}%")

        if mean_auc > 0.60:
            print("   ✅ AUC > 0.60 — 실전 가능성 높음")
        elif mean_auc > 0.55:
            print("   ✅ AUC > 0.55 — edge 존재 가능성 있음")
        elif mean_auc > 0.52:
            print("   ⚠️ AUC 0.52~0.55 — 약한 신호")
        else:
            print("   ❌ AUC ≤ 0.52 — edge 미발견")


def asset_analysis(df: pd.DataFrame):
    """자산별 성과 분석"""
    if "asset" not in df.columns:
        return
    print(f"\n{'═' * 60}")
    print(f"  📊 자산별 분석")
    print(f"{'═' * 60}")
    for asset in sorted(df["asset"].unique()):
        sub = df[df["asset"] == asset]
        n = len(sub)
        wr = sub[LABEL_COL].mean() * 100
        print(f"   {asset:12s}  n={n:4d}  baseline 승률={wr:.1f}%")


def main():
    print("""
    ╔══════════════════════════════════════════════════════════╗
    ║  ⚡ ML Phase 2: XGBoost Training v2                     ║
    ║  Multi-asset, 15 features, 강화 정규화                    ║
    ╚══════════════════════════════════════════════════════════╝
    """)

    df = load_data()

    base_wr = df[LABEL_COL].mean() * 100
    print(f"\n   Baseline 승률 (RR 1.5): {base_wr:.1f}%")
    print(f"   Features: {len(FEATURE_COLS)}개")
    print(f"   Feature당 샘플: {len(df)/len(FEATURE_COLS):.1f}개")
    print(f"   목표: fold 1-3 평균 AUC > 0.60 + 상위 구간 승률 > 65%")

    asset_analysis(df)

    model = train_holdout(df)
    train_expanding_cv(df)

    print(f"\n{'═' * 60}")
    print("  📋 판단 기준")
    print(f"{'═' * 60}")
    print("  1. fold 1-3 평균 AUC > 0.60 → Phase 3 진행")
    print("  2. 상위 30% 구간 승률 > 65% → 선택적 매매 edge 존재")
    print("  3. train AUC - test AUC < 0.15 → 과적합 통제 양호")
    print(f"{'═' * 60}")


if __name__ == "__main__":
    main()
