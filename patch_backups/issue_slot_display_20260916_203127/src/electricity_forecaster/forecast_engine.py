from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone, tzinfo
import json
import math
import statistics
import uuid

from .db import connect, init_db

class _HelsinkiTZ(tzinfo):
    """Europe/Helsinki without an external tzdata dependency.

    Finland uses EET (UTC+2) and EEST (UTC+3). EU daylight saving time
    starts at 01:00 UTC on the last Sunday of March and ends at 01:00 UTC
    on the last Sunday of October. This keeps the Windows Native package
    dependency-free even on Python installations that do not bundle IANA
    zoneinfo data.
    """

    @staticmethod
    def _last_sunday(year: int, month: int) -> date:
        if month == 12:
            first_next = date(year + 1, 1, 1)
        else:
            first_next = date(year, month + 1, 1)
        last = first_next - timedelta(days=1)
        return last - timedelta(days=(last.weekday() + 1) % 7)

    @classmethod
    def _utc_transitions(cls, year: int) -> tuple[datetime, datetime]:
        start_d = cls._last_sunday(year, 3)
        end_d = cls._last_sunday(year, 10)
        start = datetime.combine(start_d, time(1, 0), tzinfo=timezone.utc)
        end = datetime.combine(end_d, time(1, 0), tzinfo=timezone.utc)
        return start, end

    def fromutc(self, dt: datetime) -> datetime:
        if dt.tzinfo is not self:
            raise ValueError('fromutc: dt.tzinfo is not self')
        utc = dt.replace(tzinfo=timezone.utc)
        start, end = self._utc_transitions(utc.year)
        offset = timedelta(hours=3 if start <= utc < end else 2)
        local = (utc + offset).replace(tzinfo=self)
        # The hour 03:00-03:59 occurs twice when DST ends.
        if end <= utc < end + timedelta(hours=1):
            local = local.replace(fold=1)
        return local

    def dst(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        # Decide from local wall time. The forecast horizon is away from most
        # ambiguity, but fold handles the repeated autumn hour correctly.
        y = dt.year
        start_d = self._last_sunday(y, 3)
        end_d = self._last_sunday(y, 10)
        naive = dt.replace(tzinfo=None)
        start_local = datetime.combine(start_d, time(3, 0))
        end_local = datetime.combine(end_d, time(4, 0))
        if start_local <= naive < end_local:
            if naive.date() == end_d and time(3, 0) <= naive.time() < time(4, 0) and getattr(dt, 'fold', 0):
                return timedelta(0)
            return timedelta(hours=1)
        return timedelta(0)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        return timedelta(hours=2) + self.dst(dt)

    def tzname(self, dt: datetime | None) -> str:
        return 'EEST' if self.dst(dt) else 'EET'


HELSINKI = _HelsinkiTZ()
VAT = 0.255
MODEL_NAME = "fundamental_baseline"
MODEL_VERSION = "0.7.1"


def _parse_dt(s: str) -> datetime:
    s = str(s).strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_hour_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0, tzinfo=None).isoformat(timespec="seconds")


def _feature_dt(s: str) -> datetime:
    # features_hourly in v0.5/v0.6 are UTC hour strings without an explicit offset.
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _quantile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    a = sorted(values)
    j = (len(a) - 1) * p
    lo, hi = int(math.floor(j)), int(math.ceil(j))
    if lo == hi:
        return float(a[lo])
    return float(a[lo] * (hi - j) + a[hi] * (j - lo))


def _solve_linear(A: list[list[float]], b: list[float]) -> list[float] | None:
    n = len(b)
    M = [list(map(float, A[i])) + [float(b[i])] for i in range(n)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(M[r][col]))
        if abs(M[pivot][col]) < 1e-10:
            return None
        M[col], M[pivot] = M[pivot], M[col]
        div = M[col][col]
        M[col] = [x / div for x in M[col]]
        for r in range(n):
            if r == col:
                continue
            f = M[r][col]
            if f:
                M[r] = [M[r][k] - f * M[col][k] for k in range(n + 1)]
    return [M[i][-1] for i in range(n)]


def _ridge_fit(rows: list[tuple[list[float], float]], ridge: float = 1e-3) -> list[float] | None:
    if not rows:
        return None
    p = len(rows[0][0])
    xtx = [[0.0] * p for _ in range(p)]
    xty = [0.0] * p
    for x, y in rows:
        for i in range(p):
            xty[i] += x[i] * y
            for j in range(p):
                xtx[i][j] += x[i] * x[j]
    for i in range(p):
        xtx[i][i] += ridge
    return _solve_linear(xtx, xty)


def _linear_fit_xy(xs: list[float], ys: list[float]) -> tuple[float, float]:
    if len(xs) < 4 or len(xs) != len(ys):
        return 0.0, 1.0
    mx, my = statistics.mean(xs), statistics.mean(ys)
    var = sum((x - mx) ** 2 for x in xs)
    if var < 1e-9:
        return my, 0.0
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / var
    a = my - b * mx
    return a, b


def _wind_cf(v: float | None) -> float | None:
    if v is None:
        return None
    if v < 3:
        return 0.0
    if v < 12:
        return min(1.0, ((v - 3) / 9) ** 2.2)
    if v <= 25:
        return 1.0
    return 0.0


def _local_hour_shape(prices: list[tuple[datetime, float]]) -> tuple[dict[int, float], float]:
    if not prices:
        return {h: 0.0 for h in range(24)}, 50.0
    vals = [v for _, v in prices]
    mean = statistics.mean(vals)
    byh: dict[int, list[float]] = defaultdict(list)
    for dt, v in prices:
        byh[dt.astimezone(HELSINKI).hour].append(v)
    shape = {h: statistics.mean(byh[h]) - mean if byh[h] else 0.0 for h in range(24)}
    return shape, mean


def _best_3h(hour_rows: list[dict], key: str, cheapest: bool) -> str:
    if len(hour_rows) < 3:
        return "-"
    ordered = sorted(hour_rows, key=lambda r: r["local_dt"])
    best = None
    for i in range(len(ordered) - 2):
        chunk = ordered[i:i+3]
        # Require consecutive local clock hours in normal cases.
        score = statistics.mean(x[key] for x in chunk)
        if best is None or (score < best[0] if cheapest else score > best[0]):
            best = (score, chunk[0]["local_dt"], chunk[-1]["local_dt"] + timedelta(hours=1))
    if best is None:
        return "-"
    a, b = best[1], best[2]
    return f"{a:%H:%M}-{b:%H:%M}"


def _latest_actual(c, metric: str) -> float | None:
    row = c.execute("SELECT value FROM actuals WHERE metric=? ORDER BY valid_time DESC LIMIT 1", (metric,)).fetchone()
    return float(row[0]) if row else None


def _latest_prices(c) -> dict[tuple[str, datetime], float]:
    # Keep newest snapshot for each area/time.
    rows = c.execute("""
        SELECT mp.area, mp.valid_time, mp.price_eur_mwh, pr.issue_time
        FROM market_prices mp JOIN price_runs pr ON pr.run_id=mp.run_id
        ORDER BY pr.issue_time DESC
    """).fetchall()
    out: dict[tuple[str, datetime], float] = {}
    for area, t, v, _issue in rows:
        try:
            dt = _parse_dt(t)
        except Exception:
            continue
        k = (area, dt)
        if k not in out:
            out[k] = float(v)
    return out


def _calibrate_extended(features: dict[datetime, dict], wind_capacity: float | None, solar_capacity: float | None):
    # Load: transparent ridge model trained only on the current Fingrid forecast overlap.
    load_rows = []
    for dt, d in features.items():
        y = d.get("consumption_forecast_mw")
        temp = d.get("weather_load_temp_c")
        if y is None or temp is None:
            continue
        loc = dt.astimezone(HELSINKI)
        h = 2 * math.pi * loc.hour / 24.0
        x = [1.0, temp, math.sin(h), math.cos(h), 1.0 if loc.weekday() >= 5 else 0.0]
        load_rows.append((x, y))
    load_beta = _ridge_fit(load_rows, ridge=0.1)

    # Wind: map weather turbine proxy to the current Fingrid wind forecast.
    wx, wy = [], []
    for _dt, d in features.items():
        y = d.get("wind_forecast_mw")
        x = d.get("weather_wind_cf_proxy")
        if y is not None and x is not None:
            wx.append(float(x)); wy.append(float(y))
    wind_a, wind_b = _linear_fit_xy(wx, wy)
    if wind_capacity and wind_capacity > 0 and wx:
        # Prefer a capacity-aware slope if the raw fit is pathological.
        if wind_b <= 0 or wind_b > wind_capacity * 2:
            wind_a, wind_b = 0.0, wind_capacity

    # Solar: map radiation to current Fingrid solar forecast.
    sx, sy = [], []
    for _dt, d in features.items():
        y = d.get("solar_forecast_mw")
        x = d.get("weather_solar_wm2")
        if y is not None and x is not None:
            sx.append(float(x)); sy.append(float(y))
    solar_a, solar_b = _linear_fit_xy(sx, sy)
    if sx and solar_b < 0:
        solar_a, solar_b = 0.0, max(sy) / max(max(sx), 1.0)

    return load_beta, (wind_a, wind_b), (solar_a, solar_b)


def _extended_load(dt: datetime, d: dict, beta: list[float] | None, fallback: float) -> float:
    direct = d.get("consumption_forecast_mw") or d.get("consumption_forecast_daily_mw")
    if direct is not None:
        return float(direct)
    temp = d.get("weather_load_temp_c")
    if beta is None or temp is None:
        return fallback
    loc = dt.astimezone(HELSINKI)
    h = 2 * math.pi * loc.hour / 24.0
    x = [1.0, float(temp), math.sin(h), math.cos(h), 1.0 if loc.weekday() >= 5 else 0.0]
    return max(3500.0, min(16000.0, sum(a*b for a, b in zip(beta, x))))


def _extended_wind(d: dict, coeff: tuple[float, float], cap: float | None, scenario: str = "p50") -> float:
    direct = d.get("wind_forecast_mw") or d.get("wind_forecast_daily_mw")
    if direct is not None and scenario == "p50":
        return max(0.0, float(direct))
    metric = {"p10": "weather_wind_p10_ms", "p50": "weather_wind_p50_ms", "p90": "weather_wind_p90_ms"}.get(scenario)
    speed = d.get(metric) if metric else None
    if speed is None:
        speed = d.get("weather_wind100_ms")
    cf = _wind_cf(float(speed)) if speed is not None else d.get("weather_wind_cf_proxy")
    if cf is None:
        return max(0.0, float(direct or 0.0))
    a, b = coeff
    v = a + b * cf
    upper = float(cap) * 1.05 if cap and cap > 0 else 9000.0
    return max(0.0, min(upper, v))


def _extended_solar(d: dict, coeff: tuple[float, float], cap: float | None) -> float:
    direct = d.get("solar_forecast_mw") or d.get("solar_forecast_daily_mw")
    if direct is not None:
        return max(0.0, float(direct))
    rad = d.get("weather_solar_wm2")
    if rad is None:
        return 0.0
    a, b = coeff
    v = a + b * float(rad)
    upper = float(cap) * 1.05 if cap and cap > 0 else 2500.0
    return max(0.0, min(upper, v))


def make_forecast() -> tuple[str, int]:
    init_db()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    now_local = now_utc.astimezone(HELSINKI)
    run_id = now_utc.strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]

    with connect() as c:
        frow = c.execute("SELECT feature_run_id FROM feature_runs WHERE status='ok' ORDER BY created_at DESC LIMIT 1").fetchone()
        if not frow:
            raise RuntimeError("Yhdistettyja featureita ei loydy. Aja ensin 08_RAKENNA_FEATURET.bat.")
        feature_run_id = frow[0]
        features: dict[datetime, dict] = defaultdict(dict)
        for t, n, v in c.execute("SELECT valid_time,feature_name,value FROM features_hourly WHERE feature_run_id=?", (feature_run_id,)):
            try:
                dt = _feature_dt(t)
            except Exception:
                continue
            features[dt][n] = float(v)

        prices = _latest_prices(c)
        fi_prices = [(dt, v) for (area, dt), v in prices.items() if area == "FI"]
        if not fi_prices:
            raise RuntimeError("FI day-ahead -hintadata puuttuu. Aja ensin 11_HAE_HINTADATA.bat.")

        shape, published_mean = _local_hour_shape(fi_prices)
        # Prefer tomorrow's published FI average as the anchor, then today's, then all recent values.
        tomorrow = now_local.date() + timedelta(days=1)
        tomorrow_vals = [v for dt, v in fi_prices if dt.astimezone(HELSINKI).date() == tomorrow]
        today_vals = [v for dt, v in fi_prices if dt.astimezone(HELSINKI).date() == now_local.date()]
        anchor_price = statistics.mean(tomorrow_vals or today_vals or [v for _, v in fi_prices])

        # Neighbor market context from the newest published day(s).
        neighbor_areas = ["SE1", "SE2", "SE3", "SE4", "EE"]
        neighbor_vals = [v for (a, dt), v in prices.items() if a in neighbor_areas and dt.astimezone(HELSINKI).date() == tomorrow]
        neighbor_mean = statistics.mean(neighbor_vals) if neighbor_vals else anchor_price
        market_context = max(-15.0, min(15.0, 0.20 * (neighbor_mean - anchor_price)))

        wind_capacity = _latest_actual(c, "wind_capacity_mw")
        solar_capacity = _latest_actual(c, "solar_capacity_mw")
        load_beta, wind_coeff, solar_coeff = _calibrate_extended(features, wind_capacity, solar_capacity)

        direct_loads = [d["consumption_forecast_mw"] for d in features.values() if "consumption_forecast_mw" in d]
        load_fallback = statistics.mean(direct_loads) if direct_loads else 8500.0

        # Build all target hourly fundamentals first.
        hourly: list[dict] = []
        for day_h in range(2, 13):
            target_date = now_local.date() + timedelta(days=day_h)
            local_start = datetime.combine(target_date, time(0, 0), HELSINKI)
            local_end = local_start + timedelta(days=1)
            dt = local_start.astimezone(timezone.utc)
            while dt < local_end.astimezone(timezone.utc):
                # Match to nearest exact UTC feature hour.
                d = features.get(dt.replace(minute=0, second=0, microsecond=0), {})
                load = _extended_load(dt, d, load_beta, load_fallback)
                wind = _extended_wind(d, wind_coeff, wind_capacity, "p50")
                wind_low = _extended_wind(d, wind_coeff, wind_capacity, "p10")  # weaker wind
                wind_high = _extended_wind(d, wind_coeff, wind_capacity, "p90") # stronger wind
                solar = _extended_solar(d, solar_coeff, solar_capacity)
                net_load = load - wind - solar
                net_load_high_price = load - wind_low - solar
                net_load_low_price = load - wind_high - solar
                hourly.append({
                    "dt": dt, "local_dt": dt.astimezone(HELSINKI), "target_date": target_date,
                    "horizon": day_h, "features": d, "load": load, "wind": wind, "solar": solar,
                    "net_load": net_load, "net_load_high_price": net_load_high_price,
                    "net_load_low_price": net_load_low_price,
                })
                dt += timedelta(hours=1)

        # Anchor the residual sensitivity against D+2 if tomorrow features are unavailable.
        anchor_candidates = [r["net_load"] for r in hourly if r["horizon"] == 2]
        anchor_net = statistics.mean(anchor_candidates) if anchor_candidates else load_fallback
        all_nets = [r["net_load"] for r in hourly]
        net_q75 = _quantile(all_nets, 0.75) or anchor_net

        hourly_rows_db = []
        daily_rows_db = []
        daily_output = []
        for day_h in range(2, 13):
            rows = [r for r in hourly if r["horizon"] == day_h]
            for r in rows:
                loc = r["local_dt"]
                # Transparent v0.7 fundamental formula. Coefficients are engineering priors,
                # not learned historical coefficients; future versions replace them with Champion ML.
                net_delta = r["net_load"] - anchor_net
                scarcity = max(0.0, r["net_load"] - net_q75)
                weekend_adj = -2.0 if loc.weekday() >= 5 else 0.0
                p50 = anchor_price + shape.get(loc.hour, 0.0) + market_context + 0.0060 * net_delta + 0.0040 * scarcity + weekend_adj
                # Mild mean reversion of extreme published anchors on long horizons.
                revert = min(0.35, max(0.0, (day_h - 4) * 0.04))
                p50 = p50 * (1 - revert) + published_mean * revert
                p50 = max(-80.0, min(400.0, p50))

                # Weather-driven asymmetric bounds: less wind => high-price side.
                wind_up_effect = 0.0060 * max(0.0, r["net_load_high_price"] - r["net_load"])
                wind_down_effect = 0.0060 * max(0.0, r["net_load"] - r["net_load_low_price"])
                spread_ms = float(r["features"].get("weather_wind_uncertainty_ms", 0.0))
                horizon_sigma = 7.0 + 2.3 * max(0, day_h - 2)
                weather_sigma = 2.0 * spread_ms
                sigma = min(70.0, horizon_sigma + weather_sigma)
                p10 = p50 - 1.2816 * sigma - wind_down_effect
                p90 = p50 + 1.2816 * sigma + wind_up_effect
                baseline = anchor_price + shape.get(loc.hour, 0.0)
                r.update({"p10": p10, "p50": p50, "p90": p90, "baseline": baseline})
                hourly_rows_db.append((run_id, r["dt"].isoformat(), day_h, p10, p50, p90, baseline,
                                       r["load"], r["wind"], r["solar"], r["net_load"],
                                       json.dumps({"anchor_eur_mwh": anchor_price, "market_context": market_context,
                                                   "weather_wind_uncertainty_ms": spread_ms}, ensure_ascii=False)))

            p10d = statistics.mean(r["p10"] for r in rows)
            p50d = statistics.mean(r["p50"] for r in rows)
            p90d = statistics.mean(r["p90"] for r in rows)
            based = statistics.mean(r["baseline"] for r in rows)
            lo = min(r["p50"] for r in rows); hi = max(r["p50"] for r in rows)
            cheap = _best_3h(rows, "p50", True); expensive = _best_3h(rows, "p50", False)
            width = p90d - p10d
            risk = "matala" if width < 35 else "kohtalainen" if width < 65 else "korkea"
            avg_load = statistics.mean(r["load"] for r in rows)
            avg_wind = statistics.mean(r["wind"] for r in rows)
            avg_net = statistics.mean(r["net_load"] for r in rows)
            reason = {
                "anchor_eur_mwh": round(anchor_price, 2),
                "neighbor_context_eur_mwh": round(market_context, 2),
                "avg_load_mw": round(avg_load, 0),
                "avg_wind_mw": round(avg_wind, 0),
                "avg_net_load_mw": round(avg_net, 0),
                "method": "Fingrid direct D+2/D+3 where available; weather-calibrated extension thereafter"
            }
            target_date = rows[0]["target_date"].isoformat()
            daily_rows_db.append((run_id, target_date, day_h, p10d, p50d, p90d, based, lo, hi, cheap, expensive, risk, json.dumps(reason, ensure_ascii=False)))
            daily_output.append((target_date, day_h, p10d, p50d, p90d, cheap, expensive, risk))

        quality = "fundamental_v0.7_no_historical_training"
        c.execute("""INSERT INTO price_forecast_runs
                     (forecast_run_id,issue_time,model_name,model_version,feature_run_id,status,data_quality,notes)
                     VALUES (?,?,?,?,?,?,?,?)""",
                  (run_id, now_utc.isoformat(), MODEL_NAME, MODEL_VERSION, feature_run_id, "ok", quality,
                   "First archived fundamental forecast. Not a trained ML/Champion model."))
        c.executemany("""INSERT INTO price_forecasts_hourly
                         (forecast_run_id,target_time,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh,
                          load_est_mw,wind_est_mw,solar_est_mw,net_load_est_mw,drivers_json)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", hourly_rows_db)
        c.executemany("""INSERT INTO price_forecasts_daily
                         (forecast_run_id,target_date,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh,
                          min_p50_eur_mwh,max_p50_eur_mwh,cheapest_3h,expensive_3h,risk_level,drivers_json)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", daily_rows_db)

    print(f"[OK] Ennusteajo {run_id}: {len(hourly_rows_db)} tuntiennustetta, {len(daily_rows_db)} paivaennustetta")
    print("Malli: fundamental_baseline v0.7 - EI viela koulutettu ML/Champion-malli")
    return run_id, len(daily_rows_db)


def latest_daily_forecast() -> tuple[dict | None, list[dict]]:
    init_db()
    with connect() as c:
        rr = c.execute("""SELECT forecast_run_id,issue_time,model_name,model_version,data_quality,notes
                          FROM price_forecast_runs WHERE status='ok' ORDER BY issue_time DESC LIMIT 1""").fetchone()
        if not rr:
            return None, []
        meta = dict(zip(["run_id","issue_time","model_name","model_version","data_quality","notes"], rr))
        rows = []
        for x in c.execute("""SELECT target_date,horizon_days,p10_eur_mwh,p50_eur_mwh,p90_eur_mwh,baseline_eur_mwh,
                                     min_p50_eur_mwh,max_p50_eur_mwh,cheapest_3h,expensive_3h,risk_level,drivers_json
                              FROM price_forecasts_daily WHERE forecast_run_id=? ORDER BY horizon_days""", (rr[0],)):
            rows.append({
                "target_date": x[0], "horizon": x[1], "p10": x[2], "p50": x[3], "p90": x[4], "baseline": x[5],
                "min": x[6], "max": x[7], "cheap": x[8], "expensive": x[9], "risk": x[10],
                "drivers": json.loads(x[11]) if x[11] else {}
            })
        return meta, rows


def eur_mwh_to_ct_kwh_vat(x: float) -> float:
    return x * (1.0 + VAT) / 10.0
