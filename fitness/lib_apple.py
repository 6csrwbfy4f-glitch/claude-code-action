"""Gemeinsame Bausteine: Apple-Health-Extrakt laden, Naechte bilden,
Tageswerte ableiten. Keine Daten in dieser Datei - nur Rechenwege."""
import gzip
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta

WATCH_PREFIX = "Apple"  # sourceName beginnt mit "Apple" + NBSP + "Watch"
FMT = "%Y-%m-%d %H:%M:%S %z"
NIGHT_GAP = timedelta(hours=1)
SPLIT_MERGE_GAP = timedelta(hours=4)   # geteilte Nacht: Luecke < 4 h, beide Teile vor 10 Uhr
FULL_NIGHT_S = 4 * 3600                # unter 4 h Schlaf = keine volle Nacht
ASLEEP = ("AsleepDeep", "AsleepCore", "AsleepREM", "AsleepUnspecified")


def P(s):
    return datetime.strptime(s, FMT)


def load(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def watch_source(d):
    """Die Quelle der Uhr: die Schlafquelle mit den meisten Naechten."""
    return max(d["sleep_nights_by_source"],
               key=lambda s: len(d["sleep_nights_by_source"][s]))


def _block(segs):
    secs = defaultdict(float)
    for s in segs:
        v = s["value"].replace("HKCategoryValueSleepAnalysis", "")
        secs[v] += (P(s["endDate"]) - P(s["startDate"])).total_seconds()
    start = min(P(s["startDate"]) for s in segs)
    end = max(P(s["endDate"]) for s in segs)
    asleep = sum(secs.get(k, 0) for k in ASLEEP)
    return {"start": start, "end": end, "night_of": end.date().isoformat(),
            "span_s": (end - start).total_seconds(), "secs": dict(secs),
            "asleep_s": asleep, "segments": segs}


def nights(d, src):
    """Abschnitte -> Bloecke (Luecke > 1 h trennt), geteilte Naechte
    zusammenfuehren, dann klassifizieren: full / short_night / nap."""
    segs = sorted((s for n in d["sleep_nights_by_source"][src] for s in n["segments"]),
                  key=lambda s: s["startDate"])
    blocks, cur, cur_end = [], [], None
    for s in segs:
        st, en = P(s["startDate"]), P(s["endDate"])
        if cur and st - cur_end > NIGHT_GAP:
            blocks.append(cur)
            cur, cur_end = [], None
        cur.append(s)
        cur_end = en if cur_end is None else max(cur_end, en)
    if cur:
        blocks.append(cur)
    blocks = [_block(b) for b in blocks]

    merged = []
    for b in blocks:
        if merged:
            a = merged[-1]
            if (b["start"] - a["end"] < SPLIT_MERGE_GAP
                    and a["end"].hour < 10 and b["start"].hour < 10
                    and a["start"].date() <= b["start"].date()):
                nb = _block(a["segments"] + b["segments"])
                nb["merged_split"] = True
                merged[-1] = nb
                continue
        merged.append(b)

    for b in merged:
        if b["asleep_s"] >= FULL_NIGHT_S:
            b["kind"] = "full"
        elif 10 <= b["start"].hour < 19:
            b["kind"] = "nap"
        else:
            b["kind"] = "short_night"
    return merged


def records(d, typ, src):
    return [r for r in d["records"].get(typ, []) if r.get("sourceName") == src]


def hrv_per_night(d, src, nts):
    """Mittel aller SDNN-Messungen, deren startDate im Schlaffenster liegt."""
    hrv = sorted(((P(r["startDate"]), float(r["value"])) for r in
                  records(d, "HKQuantityTypeIdentifierHeartRateVariabilitySDNN", src)))
    out = {}
    for n in nts:
        if n["kind"] != "full":
            continue
        vals = [v for t, v in hrv if n["start"] <= t <= n["end"]]
        if vals:
            out[n["night_of"]] = {"value": sum(vals) / len(vals), "n_samples": len(vals)}
    return out


def rhr_per_day(d, src):
    """Ein Ruhepuls pro Tag (Datum von startDate). Mehrere Eintraege am
    selben Tag: der zuletzt erzeugte (creationDate) gilt."""
    by = {}
    for r in records(d, "HKQuantityTypeIdentifierRestingHeartRate", src):
        day = r["startDate"][:10]
        if day not in by or r["creationDate"] > by[day]["creationDate"]:
            by[day] = r
    return {k: float(v["value"]) for k, v in by.items()}


# ---- Statistik ----
def mean(xs):
    return sum(xs) / len(xs)


def sd(xs):
    """Stichproben-Standardabweichung (n-1)."""
    m = mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def pct(xs, p):
    """Perzentil mit linearer Interpolation (wie numpy 'linear')."""
    s = sorted(xs)
    k = (len(s) - 1) * p / 100
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def window(series, end_date, days):
    """Werte aus den `days` Tagen VOR end_date (end_date selbst ausgeschlossen)."""
    start = end_date - timedelta(days=days)
    return [v for k, v in series.items()
            if start <= datetime.fromisoformat(k).date() < end_date]
