"""Die Formeln aus Schritt 5, so wie sie auf der Seite stehen.
Keine Daten in dieser Datei - nur Rechenwege."""
import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import datetime, timedelta

from lib_apple import P, mean, pct

LIFE_LOAD = 4.0          # "das Leben neben dem Training"
ANCHOR_MIN = 60.0
SPIKE_BPM = 15           # Ausreisser: mehr als 15 bpm ueber dem lokalen Median
SPIKE_WIN = 5            # Nachbarn je Seite fuer den lokalen Median
MAX_FILL_MIN = 3         # Minutenluecken bis 3 min werden linear gefuellt
BASE_NEED_H = 8.0


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------- Puls ----------
def hr_series(d):
    """Alle Pulsmessungen (alle Quellen, es war immer nur ein Geraet aktiv),
    sortiert: [(datetime, bpm)]."""
    return sorted((P(r["startDate"]), float(r["value"]))
                  for r in d["records"].get("HKQuantityTypeIdentifierHeartRate", []))


def despike(samples):
    """Entfernt Einzelausreisser: Wert > lokaler Median + 15 bpm.
    Gibt (bereinigt, entfernt) zurueck."""
    keep, drop = [], []
    vals = [v for _, v in samples]
    for i, (t, v) in enumerate(samples):
        nb = vals[max(0, i - SPIKE_WIN):i] + vals[i + 1:i + 1 + SPIKE_WIN]
        if len(nb) >= 3 and v > sorted(nb)[len(nb) // 2] + SPIKE_BPM:
            drop.append((t, v))
        else:
            keep.append((t, v))
    return keep, drop


def window_samples(hr, start, end):
    times = [t for t, _ in hr]  # Aufrufer cachen das, s. Workouts
    return hr[bisect_left(times, start):bisect_right(times, end)]


def per_minute(samples, start, end):
    """Minutenmittel; Luecken bis MAX_FILL_MIN linear gefuellt, laengere
    bleiben leer. Gibt Liste (minute_index, bpm) und Abdeckung zurueck."""
    n = max(1, int(math.ceil((end - start).total_seconds() / 60)))
    acc = defaultdict(list)
    for t, v in samples:
        i = int((t - start).total_seconds() // 60)
        if 0 <= i < n:
            acc[i].append(v)
    pts = sorted((i, sum(v) / len(v)) for i, v in acc.items())
    out = list(pts)
    for (i0, v0), (i1, v1) in zip(pts, pts[1:]):
        if 1 < i1 - i0 <= MAX_FILL_MIN + 1:
            for k in range(i0 + 1, i1):
                out.append((k, v0 + (v1 - v0) * (k - i0) / (i1 - i0)))
    out.sort()
    return out, len(out) / n


def trimp_exp(minutes, rest, hrmax):
    """TRIMPexp: Summe ueber Minuten von x * 0,64 * e^(1,92 x),
    x = (Puls - Ruhepuls) / (Maxpuls - Ruhepuls), x auf [0, 1] begrenzt."""
    tot = 0.0
    for _, bpm in minutes:
        x = clamp((bpm - rest) / (hrmax - rest), 0.0, 1.0)
        tot += x * 0.64 * math.exp(1.92 * x)
    return tot


# ---------- Belastung ----------
def strain(day_load, anchor):
    """belastung = min(21, 21 * ln(1 + last/12) / ln(1 + anker/12)).
    Gibt auch den ungedeckelten Wert zurueck - greift die Deckelung,
    ist der Anker falsch."""
    raw = 21 * math.log(1 + day_load / 12) / math.log(1 + anchor / 12)
    return min(21.0, raw), raw


def strain_band(s):
    if s < 10:
        return "leicht"
    if s < 14:
        return "moderat"
    if s < 18:
        return "hoch"
    return "alles gegeben"


def anchor_from(loads_with_activity):
    """95. Perzentil der Tageslast an Tagen MIT Aktivitaet, mindestens 60."""
    p95 = pct(loads_with_activity, 95)
    return max(ANCHOR_MIN, p95), p95


# ---------- Schlaf ----------
def f_strain(strain_yesterday):
    """1,7 / (1 + e^((17 - belastung_gestern) / 3,5)) in Stunden."""
    return 1.7 / (1 + math.exp((17 - strain_yesterday) / 3.5))


def deficit(prev_asleep_h):
    """min(0,35 * Summe der Fehlstunden ggue. 8 h ueber die letzten 3 Naechte, 1,5)."""
    miss = sum(max(0.0, BASE_NEED_H - h) for h in prev_asleep_h)
    return min(0.35 * miss, 1.5), miss


# ---------- Erholung ----------
def recovery(hrv, hrv_m, hrv_s, rhr, rhr_m, rhr_s, sleep_perf_pct):
    """0,50 * hrv_wert + 0,25 * rhr_wert + 0,25 * schlaf_wert;
    fehlt ein Eingang, wird sein Gewicht anteilig verteilt."""
    parts = {}
    if hrv is not None:
        z = (hrv - hrv_m) / hrv_s
        parts["hrv"] = (0.50, clamp(50 + 20 * z, 0, 100), z)
    if rhr is not None:
        z = (rhr - rhr_m) / rhr_s
        parts["rhr"] = (0.25, clamp(50 - 20 * z, 0, 100), z)
    if sleep_perf_pct is not None:
        parts["sleep"] = (0.25, min(100.0, sleep_perf_pct), None)
    wsum = sum(w for w, _, _ in parts.values())
    used = {k: (w / wsum, v, z) for k, (w, v, z) in parts.items()}
    return sum(w * v for w, v, _ in used.values()), used


def recovery_band(r):
    if r >= 67:
        return "gruen"
    if r >= 34:
        return "gelb"
    return "rot"


TARGET = {"gruen": (14.0, 18.0), "gelb": (9.0, 13.5), "rot": (0.0, 8.0)}
