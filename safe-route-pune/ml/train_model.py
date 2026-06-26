#!/usr/bin/env python3
"""
SafeRoute Pune — ML Safety Model Trainer
=========================================
Trains a Random Forest regressor on the generated Pune safety dataset.
The model predicts safety scores for arbitrary lat/lng coordinates.

After training, exports:
  - data/model_predictions.json   (dense grid predictions for the map)
  - data/model_metadata.json      (feature importances, accuracy metrics)

Usage:
  python3 ml/train_model.py
"""

import json, os, math, sys
from pathlib import Path

# Try importing ML libs; guide the user if missing
try:
    import numpy  as np
    import pandas as pd
    from sklearn.ensemble       import RandomForestRegressor, GradientBoostingRegressor
    from sklearn.model_selection import train_test_split, cross_val_score
    from sklearn.preprocessing  import StandardScaler
    from sklearn.metrics        import mean_absolute_error, r2_score
    import joblib
    ML_AVAILABLE = True
except ImportError as e:
    print(f"\n  ✗ Missing ML library: {e}")
    print("  Run:  pip3 install scikit-learn pandas numpy joblib --break-system-packages\n")
    ML_AVAILABLE = False

ROOT     = Path(__file__).parent.parent
DATA_DIR = ROOT / "data"
MODEL_DIR = ROOT / "data" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

PUNE_BOUNDS = {"north":18.660,"south":18.390,"east":73.980,"west":73.700}

def haversine(lat1,lon1,lat2,lon2):
    R=6371000
    p1,p2=math.radians(lat1),math.radians(lat2)
    dp,dl=math.radians(lat2-lat1),math.radians(lon2-lon1)
    a=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return R*2*math.atan2(math.sqrt(a),math.sqrt(1-a))

# ─── Feature engineering ────────────────────────────────────────────────────

def nearest_zone_features(lat, lng, zones):
    """Distance/score features relative to each risk tier."""
    feats = {}
    dists_by_risk = {"CRITICAL":[],"HIGH":[],"MODERATE":[],"LOW":[]}
    scores = []

    for z in zones:
        d = haversine(lat, lng, z["lat"], z["lng"])
        rl = z.get("risk_level","MODERATE")
        dists_by_risk.get(rl, []).append(d)
        if d < z["radius"] * 2:
            w = max(0, 1 - d / (z["radius"]*2))
            scores.append((z["scores"]["overall"], w))

    for risk, dists in dists_by_risk.items():
        feats[f"min_dist_{risk.lower()}"] = min(dists) if dists else 999999

    if scores:
        total_w = sum(w for _,w in scores)
        feats["weighted_score"] = sum(s*w for s,w in scores) / total_w
    else:
        feats["weighted_score"] = 62

    # Distance from Pune centre
    feats["dist_from_centre"] = haversine(lat, lng, 18.5204, 73.8567)

    # Proximity to known safe hubs (IT parks, premium residential)
    safe_hubs = [(18.5902,73.7202),(18.5608,73.8082),(18.5042,73.8282),(18.5182,73.7782)]
    feats["min_dist_safe_hub"] = min(haversine(lat,lng,h[0],h[1]) for h in safe_hubs)

    # Proximity to industrial areas
    industrial = [(18.6328,73.8512),(18.5022,73.9612),(18.6218,73.8028)]
    feats["min_dist_industrial"] = min(haversine(lat,lng,i[0],i[1]) for i in industrial)

    return feats


def generate_training_samples(zones, n_samples=8000):
    """
    Generate (lat, lng) training samples with safety scores.
    Uses grid sampling + random sampling, weighted toward zone boundaries.
    """
    samples = []

    # 1. Dense sampling around each zone
    for z in zones:
        for _ in range(60):
            angle  = np.random.uniform(0, 2*math.pi)
            radius = np.random.uniform(0, z["radius"] * 1.8)
            lat = z["lat"] + (radius/111000) * math.cos(angle)
            lng = z["lng"] + (radius/111000/math.cos(math.radians(z["lat"]))) * math.sin(angle)
            if not (PUNE_BOUNDS["south"] <= lat <= PUNE_BOUNDS["north"] and
                    PUNE_BOUNDS["west"]  <= lng <= PUNE_BOUNDS["east"]):
                continue
            feats = nearest_zone_features(lat, lng, zones)
            # True label: weighted score from all influencing zones
            label = feats["weighted_score"]
            samples.append((lat, lng, label, feats))

    # 2. Grid sampling across Pune
    for lat in np.arange(PUNE_BOUNDS["south"], PUNE_BOUNDS["north"], 0.008):
        for lng in np.arange(PUNE_BOUNDS["west"], PUNE_BOUNDS["east"], 0.008):
            feats = nearest_zone_features(lat, lng, zones)
            label = feats["weighted_score"]
            samples.append((lat, lng, label, feats))

    # 3. Random samples
    for _ in range(n_samples - len(samples)):
        lat = np.random.uniform(PUNE_BOUNDS["south"], PUNE_BOUNDS["north"])
        lng = np.random.uniform(PUNE_BOUNDS["west"],  PUNE_BOUNDS["east"])
        feats = nearest_zone_features(lat, lng, zones)
        label = feats["weighted_score"]
        samples.append((lat, lng, label, feats))

    return samples


def build_feature_matrix(samples):
    """Convert samples to (X, y) numpy arrays."""
    feat_names = [
        "lat","lng",
        "min_dist_critical","min_dist_high","min_dist_moderate","min_dist_low",
        "weighted_score","dist_from_centre","min_dist_safe_hub","min_dist_industrial"
    ]
    rows, labels = [], []
    for lat, lng, label, feats in samples:
        row = [
            lat, lng,
            feats.get("min_dist_critical",999999),
            feats.get("min_dist_high",999999),
            feats.get("min_dist_moderate",999999),
            feats.get("min_dist_low",999999),
            feats.get("weighted_score",62),
            feats.get("dist_from_centre",0),
            feats.get("min_dist_safe_hub",999999),
            feats.get("min_dist_industrial",999999),
        ]
        rows.append(row)
        labels.append(label)
    return np.array(rows, dtype=float), np.array(labels, dtype=float), feat_names


# ─── Main training pipeline ──────────────────────────────────────────────────

def main():
    print("═══════════════════════════════════════════")
    print("  SafeRoute Pune — ML Model Trainer v2.0  ")
    print("═══════════════════════════════════════════")

    if not ML_AVAILABLE:
        sys.exit(1)

    # Load base dataset
    dataset_path = DATA_DIR / "pune_safety.json"
    if not dataset_path.exists():
        print("  ✗ pune_safety.json not found. Run: npm run generate-data")
        sys.exit(1)

    with open(dataset_path) as f:
        dataset = json.load(f)

    zones = dataset["zones"]
    print(f"  ✓ Loaded {len(zones)} safety zones")

    # Generate training data
    print("  Generating training samples…", end="", flush=True)
    samples = generate_training_samples(zones, n_samples=6000)
    X, y, feat_names = build_feature_matrix(samples)
    print(f" {len(samples)} samples ready")

    # Clip labels to 0-100 and add slight noise to avoid overfitting
    y = np.clip(y + np.random.normal(0, 1.5, len(y)), 0, 100)

    # Train/test split
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)

    # ── Model 1: Random Forest ────────────────────────────────────
    print("  Training Random Forest…", end="", flush=True)
    rf = RandomForestRegressor(
        n_estimators=120, max_depth=14, min_samples_leaf=3,
        max_features="sqrt", n_jobs=-1, random_state=42
    )
    rf.fit(X_train, y_train)
    rf_pred  = rf.predict(X_test)
    rf_mae   = mean_absolute_error(y_test, rf_pred)
    rf_r2    = r2_score(y_test, rf_pred)
    print(f" MAE={rf_mae:.2f}, R²={rf_r2:.3f}")

    # ── Model 2: Gradient Boosting ───────────────────────────────
    print("  Training Gradient Boosting…", end="", flush=True)
    gb = GradientBoostingRegressor(
        n_estimators=150, max_depth=5, learning_rate=0.08,
        subsample=0.85, random_state=42
    )
    gb.fit(X_train, y_train)
    gb_pred  = gb.predict(X_test)
    gb_mae   = mean_absolute_error(y_test, gb_pred)
    gb_r2    = r2_score(y_test, gb_pred)
    print(f" MAE={gb_mae:.2f}, R²={gb_r2:.3f}")

    # Pick best model
    best_model = rf if rf_mae <= gb_mae else gb
    best_name  = "RandomForest" if rf_mae <= gb_mae else "GradientBoosting"
    best_mae   = min(rf_mae, gb_mae)
    best_r2    = rf_r2 if rf_mae <= gb_mae else gb_r2
    print(f"  ✓ Best model: {best_name} (MAE={best_mae:.2f})")

    # Save model artifact
    model_path = MODEL_DIR / "safety_model.pkl"
    joblib.dump({"model": best_model, "feat_names": feat_names}, str(model_path))
    print(f"  ✓ Model saved → {model_path.relative_to(ROOT)}")

    # ── Export dense grid predictions ──────────────────────────────
    print("  Exporting model predictions…", end="", flush=True)
    pred_rows, pred_pts = [], []
    for lat in np.arange(PUNE_BOUNDS["south"], PUNE_BOUNDS["north"], 0.004):
        for lng in np.arange(PUNE_BOUNDS["west"], PUNE_BOUNDS["east"], 0.004):
            feats = nearest_zone_features(lat, lng, zones)
            row = [
                lat, lng,
                feats.get("min_dist_critical",999999),
                feats.get("min_dist_high",999999),
                feats.get("min_dist_moderate",999999),
                feats.get("min_dist_low",999999),
                feats.get("weighted_score",62),
                feats.get("dist_from_centre",0),
                feats.get("min_dist_safe_hub",999999),
                feats.get("min_dist_industrial",999999),
            ]
            pred_rows.append(row)
            pred_pts.append((round(float(lat),5), round(float(lng),5)))

    X_pred   = np.array(pred_rows, dtype=float)
    y_pred   = best_model.predict(X_pred)
    y_pred   = np.clip(y_pred, 0, 100)

    predictions = []
    for (lat,lng), score in zip(pred_pts, y_pred):
        danger = (100 - float(score)) / 100
        if danger > 0.25:
            predictions.append({ "lat":lat,"lng":lng,"weight":round(danger,3),"safety_score":round(float(score),1) })

    print(f" {len(predictions)} prediction points")

    # Save predictions
    pred_path = DATA_DIR / "model_predictions.json"
    with open(pred_path, "w") as f:
        json.dump({"predictions": predictions}, f, separators=(",",":"))
    print(f"  ✓ Predictions saved → {pred_path.relative_to(ROOT)}")

    # ── Feature importance ────────────────────────────────────────
    importances = dict(zip(feat_names, best_model.feature_importances_))
    meta = {
        "model":       best_name,
        "mae":         round(best_mae, 3),
        "r2":          round(best_r2,  3),
        "n_train":     int(len(X_train)),
        "n_test":      int(len(X_test)),
        "n_zones":     len(zones),
        "feature_importances": {k: round(float(v),4) for k,v in sorted(importances.items(), key=lambda x:-x[1])},
        "trained_at":  pd.Timestamp.now().isoformat()
    }
    meta_path = DATA_DIR / "model_metadata.json"
    with open(meta_path,"w") as f:
        json.dump(meta, f, indent=2)
    print(f"  ✓ Metadata saved → {meta_path.relative_to(ROOT)}")

    print("\n  Feature importances:")
    for feat, imp in sorted(importances.items(), key=lambda x:-x[1])[:5]:
        bar = "█" * int(imp*40)
        print(f"    {feat:<30} {bar} {imp:.3f}")

    print("\n═══════════════════════════════════════════")
    print(f"  Training complete. Model accuracy: MAE={best_mae:.1f} pts  R²={best_r2:.3f}")
    print("═══════════════════════════════════════════\n")

if __name__ == "__main__":
    np.random.seed(42)
    main()
