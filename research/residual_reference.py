from __future__ import annotations

from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import argparse
import html
import json
import math
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if SRC.is_dir():
    sys.path.insert(0, str(SRC))

try:
    import numpy as np
    import pandas as pd
except ImportError as exc:
    raise SystemExit(
        "[VIRHE] pandas/numpy puuttuu. Asenna requirements-v1.5.txt ensin."
    ) from exc

try:
    import sklearn
    from sklearn.compose import TransformedTargetRegressor
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.impute import SimpleImputer
    from sklearn.metrics import mean_absolute_error, mean_squared_error, median_absolute_error
    from sklearn.pipeline import Pipeline
    import joblib
except ImportError as exc:
    raise SystemExit(
        '[VIRHE] scikit-learn puuttuu.\n'
        'Asenna se komennolla:\n'
        r'.\.venv\Scripts\python.exe -m pip install "scikit-learn>=1.5"'
    ) from exc

HELSINKI = ZoneInfo("Europe/Helsinki")
MODEL_NAME = "residual_hgb"
MODEL_VERSION = "0.1"
MODEL_LABEL = f"{MODEL_NAME} {MODEL_VERSION}"

ML_DIR = ROOT / "data" / "ml"
MATRIX_PATH = ML_DIR / "training_matrix.csv"
OUT_DIR = ML_DIR / "challenger_residual_hgb_v1"
HISTORICAL_PATH = ROOT / "data" / "processed" / "v1_5_8" / "horizon_asof_dual_d2_d12.parquet"

BASE_FEATURES = [
    "p50_eur_mwh",
    "p10_eur_mwh",
    "p90_eur_mwh",
    "baseline_eur_mwh",
    "load_est_mw",
    "wind_est_mw",
    "solar_est_mw",
    "net_load_est_mw",
    "horizon_days",
    "forecast_spread_eur_mwh",
    "p50_vs_simple_baseline_eur_mwh",
    "wind_share_of_load",
    "solar_share_of_load",
    "net_load_share_of_load",
    "target_hour_sin",
    "target_hour_cos",
    "target_dow_sin",
    "target_dow_cos",
    "target_doy_sin",
    "target_doy_cos",
    "target_is_weekend",
    "issue_slot_afternoon",
    "lead_hours",
]

REQUIRED = [
    "forecast_run_id",
    "issue_time",
    "target_time",
    "horizon_days",
    "p50_eur_mwh",
    "actual_eur_mwh",
]


def _metric_dict(actual, pred):
    actual = np.asarray(actual, dtype=float)
    pred = np.asarray(pred, dtype=float)
    err = pred - actual
    return {
        "n": int(len(actual)),
        "mae_eur_mwh": round(float(mean_absolute_error(actual, pred)), 3),
        "rmse_eur_mwh": round(float(mean_squared_error(actual, pred) ** 0.5), 3),
        "median_ae_eur_mwh": round(float(median_absolute_error(actual, pred)), 3),
        "bias_eur_mwh": round(float(np.mean(err)), 3),
    }


def _comparison(actual, champion, challenger):
    c = _metric_dict(actual, champion)
    m = _metric_dict(actual, challenger)
    skill = None
    if c["mae_eur_mwh"] and c["mae_eur_mwh"] > 1e-12:
        skill = 100.0 * (c["mae_eur_mwh"] - m["mae_eur_mwh"]) / c["mae_eur_mwh"]
    return {
        "n": c["n"],
        "champion": c,
        "challenger": m,
        "mae_skill_pct": None if skill is None else round(float(skill), 2),
    }


def _make_pipeline():
    # Fixed hyperparameters on purpose: first challenger is a clean benchmark,
    # not a tuned winner. This reduces overfitting risk.
    return Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", HistGradientBoostingRegressor(
            loss="squared_error",
            learning_rate=0.05,
            max_iter=250,
            max_leaf_nodes=15,
            min_samples_leaf=30,
            l2_regularization=1.0,
            random_state=42,
        )),
    ])


def _rebuild_training_matrix():
    try:
        from electricity_forecaster.forecast_quality import build_training_matrix
    except Exception as exc:
        print("[VAROITUS] ML-matriisia ei voitu rakentaa uudelleen:", exc)
        return
    print("=== BUILD TRAINING MATRIX ===")
    build_training_matrix()


def _load_matrix(path: Path) -> pd.DataFrame:
    if not path.is_file():
        raise FileNotFoundError(
            f"ML training matrix puuttuu: {path}\n"
            "Aja ensin tuotantoputki tai scripts/build_ml_readiness.py."
        )
    df = pd.read_csv(path)
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError("Training matrixista puuttuu: " + ", ".join(missing))

    df["issue_time"] = pd.to_datetime(df["issue_time"], utc=True, errors="coerce")
    df["target_time"] = pd.to_datetime(df["target_time"], utc=True, errors="coerce")

    numeric = [
        "horizon_days", "p50_eur_mwh", "p10_eur_mwh", "p90_eur_mwh",
        "baseline_eur_mwh", "load_est_mw", "wind_est_mw", "solar_est_mw",
        "net_load_est_mw", "actual_eur_mwh",
    ]
    for c in numeric:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    df = df.dropna(subset=[
        "forecast_run_id", "issue_time", "target_time",
        "horizon_days", "p50_eur_mwh", "actual_eur_mwh",
    ]).copy()

    # Residual target is exactly the production Champion error:
    # actual - fundamental_baseline P50.
    df["residual_target_eur_mwh"] = df["actual_eur_mwh"] - df["p50_eur_mwh"]

    local_target = df["target_time"].dt.tz_convert(HELSINKI)
    local_issue = df["issue_time"].dt.tz_convert(HELSINKI)

    hour = local_target.dt.hour.astype(float)
    dow = local_target.dt.dayofweek.astype(float)
    doy = local_target.dt.dayofyear.astype(float)

    df["target_hour_sin"] = np.sin(2 * np.pi * hour / 24.0)
    df["target_hour_cos"] = np.cos(2 * np.pi * hour / 24.0)
    df["target_dow_sin"] = np.sin(2 * np.pi * dow / 7.0)
    df["target_dow_cos"] = np.cos(2 * np.pi * dow / 7.0)
    df["target_doy_sin"] = np.sin(2 * np.pi * doy / 365.25)
    df["target_doy_cos"] = np.cos(2 * np.pi * doy / 365.25)
    df["target_is_weekend"] = (dow >= 5).astype(int)
    df["issue_slot"] = np.where(local_issue.dt.hour < 12, "morning", "afternoon")
    df["issue_slot_afternoon"] = (df["issue_slot"] == "afternoon").astype(int)
    df["lead_hours"] = (
        (df["target_time"] - df["issue_time"]) / pd.Timedelta(hours=1)
    ).astype(float)

    if {"p90_eur_mwh", "p10_eur_mwh"}.issubset(df.columns):
        df["forecast_spread_eur_mwh"] = df["p90_eur_mwh"] - df["p10_eur_mwh"]
    else:
        df["forecast_spread_eur_mwh"] = np.nan

    if "baseline_eur_mwh" in df.columns:
        df["p50_vs_simple_baseline_eur_mwh"] = df["p50_eur_mwh"] - df["baseline_eur_mwh"]
    else:
        df["p50_vs_simple_baseline_eur_mwh"] = np.nan

    load = df.get("load_est_mw", pd.Series(np.nan, index=df.index)).astype(float)
    safe_load = load.where(load.abs() > 1e-9)
    df["wind_share_of_load"] = df.get("wind_est_mw", np.nan) / safe_load
    df["solar_share_of_load"] = df.get("solar_est_mw", np.nan) / safe_load
    df["net_load_share_of_load"] = df.get("net_load_est_mw", np.nan) / safe_load

    for c in BASE_FEATURES:
        if c not in df.columns:
            df[c] = np.nan

    return df.sort_values(["issue_time", "target_time"]).reset_index(drop=True)


def _historical_audit():
    info = {
        "path": str(HISTORICAL_PATH.relative_to(ROOT)),
        "exists": HISTORICAL_PATH.is_file(),
        "used_for_residual_training": False,
        "reason": (
            "The dual-origin historical dataset is leakage-safe, but it does not contain "
            "the production fundamental_baseline 0.7.1 P50 forecast for each historical issue. "
            "Therefore it cannot supply the exact residual target actual-minus-production-P50."
        ),
    }
    if not HISTORICAL_PATH.is_file():
        return info
    try:
        import pyarrow.parquet as pq
        pf = pq.ParquetFile(HISTORICAL_PATH)
        info["rows"] = int(pf.metadata.num_rows)
        info["columns"] = list(pf.schema.names)
    except Exception as exc:
        info["audit_error"] = str(exc)
    return info


def _fold_blocks(runs: pd.DataFrame, folds: int, min_train_runs: int):
    runs = runs.sort_values("issue_time").reset_index(drop=True)
    n = len(runs)
    if n < min_train_runs + 2:
        raise RuntimeError(
            f"Liian vähän pisteytettyjä ennusteajoja walk-forwardiin: {n}. "
            f"Tarvitaan vähintään {min_train_runs + 2}."
        )
    start = max(min_train_runs, n // 2)
    remaining = runs.iloc[start:].copy()
    nfold = min(folds, len(remaining))
    if nfold < 1:
        raise RuntimeError("Walk-forward-testijaksoa ei syntynyt.")
    return [remaining.iloc[idx].copy() for idx in np.array_split(np.arange(len(remaining)), nfold) if len(idx)]


def _walk_forward(df: pd.DataFrame, folds: int, min_train_runs: int):
    runs = (
        df[["forecast_run_id", "issue_time"]]
        .drop_duplicates()
        .sort_values("issue_time")
        .reset_index(drop=True)
    )
    blocks = _fold_blocks(runs, folds, min_train_runs)

    pred_parts = []
    fold_reports = []

    for i, block in enumerate(blocks, start=1):
        test_run_ids = set(block["forecast_run_id"])
        test = df[df["forecast_run_id"].isin(test_run_ids)].copy()
        test_start = test["issue_time"].min()

        # Purge rule:
        # Training row must come from an earlier forecast run AND its target hour
        # must be before the test issue time. This is deliberately conservative and
        # prevents future realized prices from leaking into an earlier simulated fit.
        train = df[
            (df["issue_time"] < test_start) &
            (df["target_time"] < test_start)
        ].copy()

        train_runs = train["forecast_run_id"].nunique()
        if len(train) < 200 or train_runs < 5:
            print(f"[OHITETTU] fold {i}: liian vähän puhdasta train-dataa ({len(train)} riviä, {train_runs} ajoa)")
            continue

        pipe = _make_pipeline()
        pipe.fit(train[BASE_FEATURES], train["residual_target_eur_mwh"])

        residual_pred = pipe.predict(test[BASE_FEATURES])
        test["residual_pred_eur_mwh"] = residual_pred
        test["challenger_p50_eur_mwh"] = test["p50_eur_mwh"] + residual_pred
        test["fold"] = i

        rep = _comparison(
            test["actual_eur_mwh"],
            test["p50_eur_mwh"],
            test["challenger_p50_eur_mwh"],
        )
        rep.update({
            "fold": i,
            "train_rows": int(len(train)),
            "train_runs": int(train_runs),
            "test_rows": int(len(test)),
            "test_runs": int(test["forecast_run_id"].nunique()),
            "test_issue_start": test["issue_time"].min().isoformat(),
            "test_issue_end": test["issue_time"].max().isoformat(),
        })
        fold_reports.append(rep)
        pred_parts.append(test)

        print(
            f"[FOLD {i}] train {len(train):,} rows / {train_runs} runs | "
            f"test {len(test):,} rows | "
            f"Champion MAE {rep['champion']['mae_eur_mwh']:.3f} | "
            f"Challenger MAE {rep['challenger']['mae_eur_mwh']:.3f} | "
            f"skill {rep['mae_skill_pct']:+.2f}%"
        )

    if not pred_parts:
        raise RuntimeError("Yhtään kelvollista walk-forward-foldia ei syntynyt.")

    oof = pd.concat(pred_parts, ignore_index=True).sort_values(
        ["issue_time", "target_time"]
    ).reset_index(drop=True)
    return oof, fold_reports


def _group_reports(oof: pd.DataFrame):
    overall = _comparison(
        oof["actual_eur_mwh"],
        oof["p50_eur_mwh"],
        oof["challenger_p50_eur_mwh"],
    )

    by_horizon = {}
    for h, g in oof.groupby("horizon_days"):
        by_horizon[str(int(h))] = _comparison(
            g["actual_eur_mwh"], g["p50_eur_mwh"], g["challenger_p50_eur_mwh"]
        )

    by_slot = {}
    for slot, g in oof.groupby("issue_slot"):
        by_slot[str(slot)] = _comparison(
            g["actual_eur_mwh"], g["p50_eur_mwh"], g["challenger_p50_eur_mwh"]
        )

    return overall, by_horizon, by_slot


def _fit_final(df: pd.DataFrame, out_dir: Path):
    pipe = _make_pipeline()
    pipe.fit(df[BASE_FEATURES], df["residual_target_eur_mwh"])
    model_path = out_dir / "model.joblib"
    joblib.dump({
        "pipeline": pipe,
        "features": BASE_FEATURES,
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "trained_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }, model_path)
    return model_path


def _fmt(v, digits=2):
    if v is None:
        return "—"
    return f"{float(v):.{digits}f}"


def _report_html(report):
    overall = report["walk_forward"]["overall"]
    hrows = []
    for h, r in sorted(report["walk_forward"]["by_horizon"].items(), key=lambda x: int(x[0])):
        hrows.append(
            "<tr>"
            f"<td>D+{html.escape(h)}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{_fmt(r['champion']['mae_eur_mwh'])}</td>"
            f"<td>{_fmt(r['challenger']['mae_eur_mwh'])}</td>"
            f"<td>{_fmt(r['mae_skill_pct'])}%</td>"
            "</tr>"
        )
    srows = []
    for slot, r in report["walk_forward"]["by_slot"].items():
        srows.append(
            "<tr>"
            f"<td>{html.escape(slot)}</td>"
            f"<td>{r['n']}</td>"
            f"<td>{_fmt(r['champion']['mae_eur_mwh'])}</td>"
            f"<td>{_fmt(r['challenger']['mae_eur_mwh'])}</td>"
            f"<td>{_fmt(r['mae_skill_pct'])}%</td>"
            "</tr>"
        )

    skill = overall["mae_skill_pct"]
    tone = "#15803d" if skill is not None and skill > 0 else "#b91c1c"
    hist = report["historical_dataset"]
    hist_text = (
        f"{hist.get('rows', '—'):,} riviä" if isinstance(hist.get("rows"), int)
        else "ei paikallisesti saatavilla"
    )

    return f"""<!doctype html>
<html lang="fi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Residual Challenger v1</title>
<style>
body{{font-family:system-ui,-apple-system,Segoe UI,sans-serif;background:#eef4fb;color:#152238;margin:0}}
main{{max-width:980px;margin:auto;padding:28px 18px}}
.hero{{background:linear-gradient(120deg,#092f76,#2563eb,#0ea5e9);color:white;border-radius:20px;padding:24px}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin:16px 0}}
.card{{background:white;border:1px solid #dce5f1;border-radius:16px;padding:16px;box-shadow:0 10px 28px rgba(30,64,120,.08)}}
.big{{font-size:2rem;font-weight:800}} small{{color:#64748b}}
table{{width:100%;border-collapse:collapse;background:white;border-radius:16px;overflow:hidden}}
th,td{{padding:10px;border-bottom:1px solid #e7edf5;text-align:left}}
th{{background:#f7f9fc;color:#64748b}}
.good{{color:#15803d}} .bad{{color:#b91c1c}}
.note{{background:#fff7ed;border:1px solid #fed7aa;border-radius:14px;padding:14px}}
@media(max-width:700px){{.grid{{grid-template-columns:1fr}}}}
</style></head><body><main>
<div class="hero">
<h1 style="margin:0">Residual Challenger v1</h1>
<p>Shadow-only · Champion fundamental_baseline 0.7.1 + ML-residualikorjaus</p>
</div>
<div class="grid">
<div class="card"><small>Champion MAE</small><div class="big">{_fmt(overall['champion']['mae_eur_mwh'])}</div><small>EUR/MWh</small></div>
<div class="card"><small>Challenger MAE</small><div class="big">{_fmt(overall['challenger']['mae_eur_mwh'])}</div><small>EUR/MWh</small></div>
<div class="card"><small>MAE skill</small><div class="big" style="color:{tone}">{_fmt(skill)}%</div><small>positiivinen = Challenger parempi</small></div>
</div>
<div class="card">
<h2>Walk-forward horisonteittain</h2>
<table><thead><tr><th>Horisontti</th><th>n</th><th>Champion MAE</th><th>Challenger MAE</th><th>Skill</th></tr></thead>
<tbody>{''.join(hrows)}</tbody></table>
</div>
<div class="card" style="margin-top:16px">
<h2>Aamu vs iltapäivä</h2>
<table><thead><tr><th>Slot</th><th>n</th><th>Champion MAE</th><th>Challenger MAE</th><th>Skill</th></tr></thead>
<tbody>{''.join(srows)}</tbody></table>
</div>
<div class="note" style="margin-top:16px">
<b>Ei tuotantoon automaattisesti.</b> Tämä malli on Challenger/shadow-malli. Championia ei vaihdeta tämän ajon perusteella.
Historiallinen dual-origin-aineisto: {hist_text}. Sitä ei käytetä vielä residual-targettiin, koska siinä ei ole historiallisen tuotanto-Championin P50-arvoa joka issue-hetkelle.
</div>
</main></body></html>"""


def main():
    ap = argparse.ArgumentParser(description="First residual ML Challenger with purged walk-forward")
    ap.add_argument("--matrix", default=str(MATRIX_PATH))
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--min-train-runs", type=int, default=8)
    ap.add_argument("--no-rebuild-matrix", action="store_true")
    args = ap.parse_args()

    print("=== ELECTRICITY FORECASTER: RESIDUAL CHALLENGER v1 ===")
    print("Champion: fundamental_baseline 0.7.1")
    print(f"Challenger: {MODEL_LABEL}")
    print("Mode: SHADOW ONLY")
    print()

    if not args.no_rebuild_matrix:
        _rebuild_training_matrix()

    matrix_path = Path(args.matrix)
    if not matrix_path.is_absolute():
        matrix_path = ROOT / matrix_path

    df = _load_matrix(matrix_path)
    print(f"Scored rows: {len(df):,}")
    print(f"Scored forecast runs: {df['forecast_run_id'].nunique():,}")
    print(f"Issue range: {df['issue_time'].min()} ... {df['issue_time'].max()}")
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=== PURGED WALK-FORWARD ===")
    oof, fold_reports = _walk_forward(df, args.folds, args.min_train_runs)
    overall, by_horizon, by_slot = _group_reports(oof)

    print()
    print("=== OVERALL RESULT ===")
    print("Champion MAE:", overall["champion"]["mae_eur_mwh"], "EUR/MWh")
    print("Challenger MAE:", overall["challenger"]["mae_eur_mwh"], "EUR/MWh")
    print("MAE skill:", overall["mae_skill_pct"], "%")
    print("Champion bias:", overall["champion"]["bias_eur_mwh"], "EUR/MWh")
    print("Challenger bias:", overall["challenger"]["bias_eur_mwh"], "EUR/MWh")

    pred_cols = [
        "fold", "forecast_run_id", "issue_time", "issue_slot", "target_time",
        "horizon_days", "p50_eur_mwh", "actual_eur_mwh",
        "residual_target_eur_mwh", "residual_pred_eur_mwh",
        "challenger_p50_eur_mwh",
    ]
    oof[pred_cols].to_csv(OUT_DIR / "walk_forward_predictions.csv", index=False)

    historical = _historical_audit()
    model_path = _fit_final(df, OUT_DIR)

    report = {
        "schema_version": "1.0",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "status": "shadow_only",
        "champion": {
            "model_name": "fundamental_baseline",
            "model_version": "0.7.1",
        },
        "challenger": {
            "model_name": MODEL_NAME,
            "model_version": MODEL_VERSION,
            "algorithm": "sklearn HistGradientBoostingRegressor",
            "target": "actual_eur_mwh - champion_p50_eur_mwh",
            "formula": "challenger_p50 = champion_p50 + predicted_residual",
            "features": BASE_FEATURES,
            "sklearn_version": sklearn.__version__,
        },
        "data": {
            "matrix_path": str(matrix_path),
            "rows": int(len(df)),
            "forecast_runs": int(df["forecast_run_id"].nunique()),
            "issue_start": df["issue_time"].min().isoformat(),
            "issue_end": df["issue_time"].max().isoformat(),
        },
        "leakage_controls": {
            "walk_forward": "chronological expanding-window",
            "purge_rule": "train issue_time < test_start AND train target_time < test_start",
            "realized_target_used_as_feature": False,
            "forecast_error_used_as_feature": False,
        },
        "walk_forward": {
            "folds": fold_reports,
            "overall": overall,
            "by_horizon": by_horizon,
            "by_slot": by_slot,
        },
        "historical_dataset": historical,
        "promotion": {
            "automatic": False,
            "recommended_next_step": "Run in shadow mode and accumulate live Champion-vs-Challenger evidence before any promotion.",
        },
        "artifacts": {
            "model": str(model_path.relative_to(ROOT)),
            "predictions": str((OUT_DIR / "walk_forward_predictions.csv").relative_to(ROOT)),
            "report_json": str((OUT_DIR / "report.json").relative_to(ROOT)),
            "report_html": str((OUT_DIR / "report.html").relative_to(ROOT)),
        },
    }

    (OUT_DIR / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "report.html").write_text(_report_html(report), encoding="utf-8")

    metadata = {
        "model_name": MODEL_NAME,
        "model_version": MODEL_VERSION,
        "role": "challenger",
        "status": "shadow_only",
        "trained_at_utc": report["generated_at_utc"],
        "feature_count": len(BASE_FEATURES),
        "training_rows": int(len(df)),
        "training_runs": int(df["forecast_run_id"].nunique()),
        "walk_forward_mae_skill_pct": overall["mae_skill_pct"],
    }
    (OUT_DIR / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print()
    print("=== ARTIFACTS ===")
    print("Model:", model_path)
    print("Report:", OUT_DIR / "report.json")
    print("HTML:", OUT_DIR / "report.html")
    print("Predictions:", OUT_DIR / "walk_forward_predictions.csv")
    print()
    print("VALMIS. Championia EI muutettu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
