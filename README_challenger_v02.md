# Challenger v0.2: research and prospective shadow evaluation

Production remains `fundamental_baseline 0.7.1`. Nothing in this implementation
promotes a challenger or changes the published P10/P50/P90 forecasts.

## Origin metadata

New `price_forecast_runs` rows store `issue_slot` and `issue_slot_source`.
`explicit` means the requested slot was passed to the forecast engine;
`clock_fallback` means a locally invoked run used the documented engine fallback.
The analysis and renderer use the stored value, never the execution hour.
Legacy intact D+1..D+11 / D+2..D+12 signatures are labelled `inferred_horizon`;
these are inferred intent, not proof of an originally requested slot. Other old
origins remain unknown. The migration is additive and idempotent.

## Reproduce the historical experiment

```
python -m pip install -r requirements-challenger-v2.txt
python -m unittest discover -s tests -v
python research/challenger_v2_research.py
python research/validate_shadow_v2.py
```

The `Challenger v0.2 validation` GitHub workflow restores the latest production
SQLite cache read-only and uses disposable copies. It uploads only aggregate
reports and `selection.json`; no source DB, fitted model, or raw rows.

Four fixed candidates are compared: capped median residual, full squared-error
HGB (diagnostic reference only), and capped absolute-error HGB with 0.25 / 0.50
weights. The unweighted reference cannot be selected for v0.2 shadow deployment.
Caps are learned from training residuals only (90th absolute percentile,
bounded to 5..30 EUR/MWh before the fixed weight is applied).

The first 80% of eligible origins provide development data. Every development
target AND actual-availability timestamp must precede the holdout boundary.
Three chronological expanding-window folds select the lowest-MAE eligible
candidate. `selection.json` is written before any holdout metrics are computed.
The final 20% of origins are evaluated using a fit frozen at that boundary.
This is an historical holdout, not unseen prospective evidence: v0.1 aggregates
for parts of this history have already been observed. Do not tune repeatedly
against this final period and call it an untouched test.

Prices use complete, contiguous duration-weighted UTC hours, first complete
published snapshot, and conservative availability after both publication and
hour completion. Rows whose price was already published at the forecast origin
are excluded from development/evaluation. All model features are stored values
from that origin, plus calendar and known horizon/origin features.

## Live collection

Copy the reviewed `selection.json` to `config/challenger_v2.json` and set
`enabled` true. The candidate/weight/cap policy is then frozen; no live tuning.
Each origin refits that same specification using only completed prices available
strictly before the Champion's issue timestamp. The dependency versions are
pinned. Each fit's actual artifact, source-data hash, specification hash,
training cutoff and maximum training availability are retained in SQLite.

Capture runs immediately after a new Champion forecast, before scoring. It uses
the real timestamp AFTER fitting/predicting and refuses old (>30 minutes) or
future origins. Targets already published by capture time are excluded. Existing
origins/forecasts/scores are never overwritten. A previously published price
imported later is also excluded when scoring. Missing/failed collection is
reported explicitly; it never becomes synthetic prospective evidence.

`shadow_runs`, `shadow_models`, `shadow_forecasts`, and `shadow_scores` persist
in the normal production SQLite cache. They are not deleted by the current
retention routine. Model artifacts increase cache size; monitor cache retention
and storage as the observation period grows. An eventual archival policy should
preserve evidence before removing old model blobs.

`output/shadow_comparison.json` and the forecast JSON's `shadow_comparison`
contain aggregate prospective results by horizon, actual stored origin and
frozen specification. The diagnostics page shows live collection separately
from the historical v0.1 report. Failures in shadow collection are non-critical;
the Champion still publishes and the missing observation remains visible.

An assessment flag requires 28 days, 40 scored origins, 500 distinct target
hours and one specification. These are collection gates, not statistical proof
or permission to promote. Repeated predictions for the same target hour are
dependent. Review MAE, RMSE, bias, temporal stability and failures manually.

To stop collecting without changing the Champion, set `enabled` false in the
configuration. Do not backfill old origins. A new specification must retain a
separate hash and a new forward observation period.

## Frozen 26 October 2026 selection

Validation run: https://github.com/tempel-oss/sahkoennuste/actions/runs/40373743943

The development folds selected `hgb_robust_025` (development MAE 36.5165 versus
Champion 37.0039 EUR/MWh). Its cap is at most 7.5 EUR/MWh after the 0.25 weight.
On the historical holdout (24 origins, 284 distinct target hours), Champion MAE
was 23.4521 and the selected v0.2 MAE was 23.9820 EUR/MWh (-2.259% skill).
It is therefore deployed ONLY for shadow evidence. The fact that another
candidate happened to do better on this holdout was not used to change the
selection. The full aggregate report is in
`research_reports/challenger_v02_2026-10-26.json`.

The observed overcorrection was not explained by missing features (all 24
feature missing fractions were zero in this dataset). On holdout the full HGB
reference added 27.101 EUR/MWh on average while the required correction averaged
-6.2531. The selected bounded model added 3.9795 instead. This diagnoses a
correction/market-regime mismatch, not a proven causal explanation of its origin.
