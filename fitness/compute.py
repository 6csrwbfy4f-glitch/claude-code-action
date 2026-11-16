"""Rechnet aus dem Apple-Health-Extrakt alle Werte fuer die Seite
(Schritte 4, 5 und 7). Liefert ein dict, das build_page.py einbettet.
Keine Daten in dieser Datei - nur Rechenwege."""
import math
import random
from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from lib_apple import (P, hrv_per_night, mean, nights, pct, records,
                       rhr_per_day, sd, watch_source)
from metrics import (BASE_NEED_H, LIFE_LOAD, ANCHOR_MIN, TARGET, deficit,
                     despike, f_strain, hr_series, per_minute, recovery,
                     recovery_band, strain, strain_band, trimp_exp)

# Entscheidungen aus dem Gespraech (stehen so auch auf der Seite)
WATCH_SWITCH = date(2026, 9, 26)   # HRV-Basislinie erst ab der neuen Uhr
STRAIN_DAYS = 90
SHOW_DAYS = 31                     # so viele Tage lassen sich zurueckblaettern
DRIFT_FRAC = 0.5

TYPE_DE = {
    "TraditionalStrengthTraining": "Krafttraining", "Walking": "Gehen",
    "Cycling": "Radfahren", "StairClimbing": "Treppensteigen",
    "Squash": "Squash", "Running": "Laufen", "Soccer": "Fußball",
    "Elliptical": "Crosstrainer", "MixedCardio": "Gemischtes Cardio",
    "UnderwaterDiving": "Tauchen", "Swimming": "Schwimmen",
    "HighIntensityIntervalTraining": "HIIT", "Yoga": "Yoga",
}


def wtype(w):
    t = w["workoutActivityType"].replace("HKWorkoutActivityType", "")
    return TYPE_DE.get(t, t)


def merge_iv(iv):
    iv = sorted(iv)
    m = [list(iv[0])]
    for a, b in iv[1:]:
        if a <= m[-1][1]:
            m[-1][1] = max(m[-1][1], b)
        else:
            m.append([a, b])
    return m


def baseline(series, end, days, since=None):
    """Werte aus den `days` Tagen vor `end` (end ausgeschlossen)."""
    lo = end - timedelta(days=days)
    if since:
        lo = max(lo, since)
    return [v for k, v in series.items() if lo <= date.fromisoformat(k) < end]


def drift_pick(series, end, long_vals, since=None):
    """30- gegen 14-Tage-Fenster; weichen sie > 0,5 SD ab, gilt das kurze."""
    v30 = baseline(series, end, 30, since)
    v14 = baseline(series, end, 14, since)
    info = {"m30": mean(v30) if v30 else None, "m14": mean(v14) if v14 else None,
            "n30": len(v30), "n14": len(v14)}
    drift = (len(v30) >= 3 and len(v14) >= 3
             and abs(info["m30"] - info["m14"]) > DRIFT_FRAC * sd(v30))
    info["drift"] = bool(drift)
    use = v14 if drift else long_vals
    info["window"] = "14 Tage" if drift else None
    return use, info


def compute(d, today):
    src = watch_source(d)
    nts = nights(d, src)
    hrv_all = hrv_per_night(d, src, nts)
    hrv_val = {k: v["value"] for k, v in hrv_all.items()}
    hrv_full_new = {k: v["value"] for k, v in hrv_all.items()
                    if v["kind"] == "full" and date.fromisoformat(k) >= WATCH_SWITCH}
    rhr = rhr_per_day(d, src)

    # Haupt-Schlafblock je Datum (laengster, kein Nickerchen); Nickerchen je Tag
    main = {}
    for n in nts:
        if n["kind"] == "nap":
            continue
        if n["night_of"] not in main or n["asleep_s"] > main[n["night_of"]]["asleep_s"]:
            main[n["night_of"]] = n
    naps = defaultdict(list)
    for n in nts:
        if n["kind"] == "nap":
            naps[n["start"].date().isoformat()].append(n)

    # ---- Puls, Workouts, Last ----
    hr = hr_series(d)
    hr_first = hr[0][0].date()
    clean, dropped = despike(hr)
    ts = [t for t, _ in clean]
    in_w = lambda a, b: clean[bisect_left(ts, a):bisect_right(ts, b)]
    work_all = [w for w in d["workouts"] if P(w["startDate"]).date() >= hr_first]
    hrmax_pts = [(v, t) for w in work_all for t, v in in_w(P(w["startDate"]), P(w["endDate"]))]
    HRMAX, hrmax_t = max(hrmax_pts)
    raw_ts = [t for t, _ in hr]
    raw_max = max(v for w in work_all for _, v in
                  hr[bisect_left(raw_ts, P(w["startDate"])):bisect_right(raw_ts, P(w["endDate"]))])
    spikes_in_w = sum(1 for t, _ in dropped
                      if any(P(w["startDate"]) <= t <= P(w["endDate"]) for w in work_all))

    first_show = today - timedelta(days=SHOW_DAYS - 1)
    first_calc = first_show - timedelta(days=STRAIN_DAYS + 8)
    rhr30 = lambda D: baseline(rhr, D, 30)

    wk_by_day = defaultdict(list)
    for w in d["workouts"]:
        st, en = P(w["startDate"]), P(w["endDate"])
        if st.date() < first_calc or st.date() > today:
            continue
        day = st.date().isoformat()
        rest = rhr.get(day) or (mean(rhr30(st.date())) if rhr30(st.date()) else 60.0)
        s = in_w(st, en)
        mins, cov = per_minute(s, st, en)
        wk_by_day[day].append({
            "type": wtype(w), "start": st.strftime("%H:%M"),
            "min": round((en - st).total_seconds() / 60),
            "avg_hr": round(mean([v for _, v in s])) if s else None,
            "trimp": round(trimp_exp(mins, rest, HRMAX), 1) if s else None,
            "coverage": round(cov, 2) if s else 0,
            "source": w.get("sourceName", ""), "_iv": (st, en), "_rest": rest,
        })
    load = {}
    for day, ws in wk_by_day.items():
        rest = ws[0]["_rest"]
        tot = 0.0
        for a, b in merge_iv([w["_iv"] for w in ws]):
            tot += trimp_exp(per_minute(in_w(a, b), a, b)[0], rest, HRMAX)
        load[day] = tot
        for w in ws:
            w.pop("_iv"), w.pop("_rest")

    def day_load(Ds):
        return load.get(Ds, 0.0) + LIFE_LOAD

    def anchor_at(D):
        days = [(D - timedelta(days=i)).isoformat() for i in range(STRAIN_DAYS)]
        act = [day_load(x) for x in days if x in wk_by_day]
        return max(ANCHOR_MIN, max(act)) if act else ANCHOR_MIN, len(act)

    def strain_at(D):
        Ds = D.isoformat()
        anc, _ = anchor_at(D)
        s, raw = strain(day_load(Ds), anc)
        return s, raw, anc

    # ---- Tage ----
    days_out = {}
    D = first_show - timedelta(days=6)
    while D <= today:
        Ds = D.isoformat()
        Y = (D - timedelta(days=1)).isoformat()
        n = main.get(Ds)
        prevs = [main[x]["asleep_s"] / 3600 for x in
                 ((D - timedelta(days=k)).isoformat() for k in (1, 2, 3)) if x in main]
        sy, _, _ = strain_at(D - timedelta(days=1))
        fs = f_strain(sy)
        de, miss = deficit(prevs)
        nap_h = sum(x["asleep_s"] for x in naps.get(Y, [])) / 3600
        need = BASE_NEED_H + fs + de - nap_h
        asleep = n["asleep_s"] / 3600 if n else None
        perf = asleep / need * 100 if asleep else None

        long_hrv = baseline(hrv_full_new, D, 10_000, WATCH_SWITCH)
        hv, hinfo = drift_pick(hrv_full_new, D, long_hrv, WATCH_SWITCH)
        long_rhr = rhr30(D)
        rv, rinfo = drift_pick(rhr, D, long_rhr)
        hm, hs = (mean(hv), sd(hv)) if len(hv) >= 3 else (None, None)
        rm, rs = (mean(rv), sd(rv)) if len(rv) >= 3 else (None, None)
        hrv_today = hrv_val.get(Ds) if hm else None
        rhr_today = rhr.get(Ds) if rm else None
        rec, used = recovery(hrv_today, hm, hs, rhr_today, rm, rs, perf)
        band = recovery_band(round(rec))
        lo, hi = TARGET[band]
        s, raw, anc = strain_at(D)

        phases = None
        if n:
            sec = n["secs"]
            phases = {k: sec.get(v, 0) / 60 for k, v in
                      (("deep", "AsleepDeep"), ("core", "AsleepCore"),
                       ("rem", "AsleepREM"), ("awake", "Awake"),
                       ("unspec", "AsleepUnspecified"))}
        days_out[Ds] = {
            "date": Ds,
            "recovery": round(rec, 1), "band": band, "target": [lo, hi],
            "inputs": {
                "hrv": {"raw": hrv_today, "mean": hm, "sd": hs, "n": len(hv),
                        "z": used.get("hrv", (0, 0, None))[2],
                        "score": used.get("hrv", (0, None))[1],
                        "w": used.get("hrv", (0,))[0], "drift": hinfo,
                        "kind": hrv_all.get(Ds, {}).get("kind")},
                "rhr": {"raw": rhr_today, "mean": rm, "sd": rs, "n": len(rv),
                        "z": used.get("rhr", (0, 0, None))[2],
                        "score": used.get("rhr", (0, None))[1],
                        "w": used.get("rhr", (0,))[0], "drift": rinfo},
                "sleep": {"raw": perf, "score": used.get("sleep", (0, None))[1],
                          "w": used.get("sleep", (0,))[0]},
            },
            "sleep": {
                "need_h": need, "base_h": BASE_NEED_H, "f_strain_h": fs,
                "strain_yesterday": sy, "deficit_h": de, "missing_h": miss,
                "prev_nights": len(prevs), "nap_h": nap_h,
                "asleep_h": asleep, "perf": perf,
                "kind": n["kind"] if n else None,
                "start": n["start"].strftime("%H:%M") if n else None,
                "end": n["end"].strftime("%H:%M") if n else None,
                "span_h": n["span_s"] / 3600 if n else None,
                "phases_min": phases,
            },
            "strain": {"value": s, "raw": raw, "anchor": anc,
                       "load": day_load(Ds), "band": strain_band(s),
                       "workouts": wk_by_day.get(Ds, []),
                       "in_target": "darunter" if s < lo else ("darüber" if s > hi else "drin")},
        }
        D += timedelta(days=1)

    # ---- Richtung ----
    month_rhr = defaultdict(list)
    for k, v in rhr.items():
        month_rhr[k[:7]].append(v)
    rhr_line = [{"x": k + "-15", "y": round(mean(v), 1), "n": len(v)} for k, v in sorted(month_rhr.items())]
    ex = defaultdict(float)
    for r in records(d, "HKQuantityTypeIdentifierAppleExerciseTime", src):
        ex[r["startDate"][:10]] += float(r["value"])
    wk, wkd = defaultdict(float), defaultdict(int)
    for k, v in ex.items():
        y, w, _ = date.fromisoformat(k).isocalendar()
        wk[(y, w)] += v
        wkd[(y, w)] += 1
    ex_line = [{"x": date.fromisocalendar(y, w, 1).isoformat(), "y": round(wk[(y, w)]),
                "days": wkd[(y, w)]}
               for y, w in sorted(wk) if wkd[(y, w)] >= 6]  # nur volle Wochen
    vo2 = sorted((r["startDate"][:10], float(r["value"]))
                 for r in records(d, "HKQuantityTypeIdentifierVO2Max", src))
    vo2_line = [{"x": k, "y": v} for k, v in vo2]

    def slope_per_month(pts):
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        mx, my = mean(xs), mean(ys)
        return sum((x - mx) * (y - my) for x, y in pts) / sum((x - mx) ** 2 for x in xs) * 30

    d0 = date.fromisoformat(min(rhr))
    rhr_slope = slope_per_month([((date.fromisoformat(k) - d0).days, v) for k, v in rhr.items()])
    rhr_slope_pre = slope_per_month([((date.fromisoformat(k) - d0).days, v)
                                     for k, v in rhr.items() if date.fromisoformat(k) < WATCH_SWITCH])
    ex_slope = slope_per_month([((date.fromisoformat(p["x"]) - d0).days, p["y"]) for p in ex_line])
    vo2_slope = slope_per_month([((date.fromisoformat(k) - d0).days, v) for k, v in vo2])

    # ---- Ehrlichkeitscheck (Schritt 7) ----
    full = [n for n in nts if n["kind"] == "full"]
    rng = random.Random(7)
    sample = rng.sample(full, 3)
    phase_check = []
    for n in sample:
        s = sum(n["secs"].values())
        phase_check.append({"night": n["night_of"], "sum_min": round(s / 60, 1),
                            "span_min": round(n["span_s"] / 60, 1),
                            "diff_min": round((n["span_s"] - s) / 60, 1)})
    exact = sum(1 for n in full if abs(n["span_s"] - sum(n["secs"].values())) < 60)
    staged = [n for n in full if n["secs"].get("AsleepDeep") is not None]
    deep_pct = [n["secs"].get("AsleepDeep", 0) / n["asleep_s"] * 100 for n in staged]
    rem_pct = [n["secs"].get("AsleepREM", 0) / n["asleep_s"] * 100 for n in staged]

    win = [(today - timedelta(days=i)).isoformat() for i in range(STRAIN_DAYS)][::-1]
    anc_today, act_days = anchor_at(today)
    bands = Counter(strain_band(strain(day_load(x), anc_today)[0]) for x in win)
    over21 = [x for x in win if strain(day_load(x), anc_today)[1] > 21]
    no_hr = [{"date": x, "type": w["type"], "min": w["min"], "source": w["source"]}
             for x in win for w in wk_by_day.get(x, []) if w["avg_hr"] is None]
    hr_days = {t.date().isoformat() for t, _ in hr}
    no_act = [x for x in win if x not in wk_by_day]
    no_act_no_hr = [x for x in no_act if x not in hr_days]

    sleep_full_h = [n["asleep_s"] / 3600 for n in full if date.fromisoformat(n["night_of"]) < today]
    checks = {
        "phase_check": phase_check, "phase_exact": exact, "phase_total": len(full),
        "deep_range": [min(deep_pct), max(deep_pct)], "rem_range": [min(rem_pct), max(rem_pct)],
        "staged_nights": len(staged),
        "n_hrv": len(baseline(hrv_full_new, today, 10_000, WATCH_SWITCH)),
        "n_rhr": len(rhr30(today)), "n_sleep": len(sleep_full_h),
        "sleep_median_h": pct(sleep_full_h, 50), "sleep_p75_h": pct(sleep_full_h, 75),
        "no_hr": no_hr,
        "bands": {k: bands.get(k, 0) for k in ("leicht", "moderat", "hoch", "alles gegeben")},
        "over21": over21, "anchor": anc_today, "act_days": act_days,
        "anchor_day": max((x for x in win if x in wk_by_day), key=day_load),
        "no_act": len(no_act), "no_act_no_hr": no_act_no_hr,
        "hrmax": HRMAX, "hrmax_at": hrmax_t.strftime("%d.%m.%Y %H:%M"), "hrmax_raw": raw_max,
        "spikes": len(dropped), "spikes_in_workouts": spikes_in_w,
        "hr_first": hr_first.isoformat(),
        "nights_kinds": dict(Counter(n["kind"] for n in nts)),
        "merged_splits": sum(1 for n in nts if n.get("merged_split")),
    }

    me = d.get("me", {})
    return {
        "today": today.isoformat(),
        "source": src.replace("\xa0", " "),
        "export_created": d["meta"]["created"],
        "watch_switch": WATCH_SWITCH.isoformat(),
        "days": days_out,
        "show_from": first_show.isoformat(),
        "direction": {
            "rhr": rhr_line, "ex": ex_line, "vo2": vo2_line,
            "rhr_slope": rhr_slope, "rhr_slope_pre": rhr_slope_pre,
            "ex_slope": ex_slope, "vo2_slope": vo2_slope,
            "ex_median": pct([p["y"] for p in ex_line], 50),
        },
        "checks": checks,
        "sex": me.get("HKCharacteristicTypeIdentifierBiologicalSex", ""),
    }
