#!/usr/bin/env python3
"""Zieht aus einem Apple-Health-Export nur die Datensaetze, die fuer
Recovery, Strain und Sleep gebraucht werden, und schreibt sie gzip-komprimiert
als JSON. Liest die export.xml streamend (iterparse), nie als Ganzes.

Aufruf:
    python3 extract_apple_health.py export.zip            # oder .../export.xml
    python3 extract_apple_health.py export.zip --days 400 --out health_extract.json.gz

Nur Standardbibliothek. Schreibt nichts ausser der Ausgabedatei.
Jeder Datensatz wird VOLLSTAENDIG gespeichert (alle Attribute, alle
MetadataEntry, alle Kind-Elemente), nicht nur die Felder, die wir kennen.
"""
import argparse
import gzip
import json
import sys
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import xml.etree.ElementTree as ET

# Typen, die wir behalten. Alles andere wird beim Lesen verworfen.
KEEP = {
    "HKCategoryTypeIdentifierSleepAnalysis",
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN",
    "HKQuantityTypeIdentifierRestingHeartRate",
    "HKQuantityTypeIdentifierVO2Max",
    # Fuer TRIMPexp (Last aus der Pulskurve) und den Maximalpuls:
    "HKQuantityTypeIdentifierHeartRate",
    # Fuer "intensive Minuten pro Woche" im Richtungs-Bildschirm:
    "HKQuantityTypeIdentifierAppleExerciseTime",
    # Nur um in Schritt 3 sagen zu koennen, ob sie da sind:
    "HKQuantityTypeIdentifierRespiratoryRate",
    "HKQuantityTypeIdentifierOxygenSaturation",
    "HKQuantityTypeIdentifierAppleSleepingWristTemperature",
}
# Pulssamples sind zahlreich - nur fuer diesen juengeren Zeitraum behalten.
HR_DAYS = 120
NIGHT_GAP = timedelta(hours=1)  # Luecke > 1 h beendet eine Nacht

FMT = "%Y-%m-%d %H:%M:%S %z"


def parse_ts(s):
    return datetime.strptime(s, FMT)


def elem_to_dict(e):
    """Element vollstaendig: Attribute + Kinder (rekursiv)."""
    d = dict(e.attrib)
    meta = {}
    children = defaultdict(list)
    for c in e:
        if c.tag == "MetadataEntry":
            meta[c.get("key")] = c.get("value")
        else:
            children[c.tag].append(elem_to_dict(c))
    if meta:
        d["metadata"] = meta
    for tag, items in children.items():
        d[tag] = items
    return d


def open_xml(path):
    if zipfile.is_zipfile(path):
        z = zipfile.ZipFile(path)
        names = [n for n in z.namelist()
                 if n.endswith("/export.xml") or n == "export.xml"]
        if not names:
            sys.exit("In der ZIP liegt keine export.xml.")
        return z.open(names[0])
    return open(path, "rb")


def group_nights(segments):
    """Schlafabschnitte EINER Quelle zu Naechten gruppieren."""
    segs = sorted(segments, key=lambda s: s["startDate"])
    nights, cur, cur_end = [], [], None
    for s in segs:
        st, en = parse_ts(s["startDate"]), parse_ts(s["endDate"])
        if cur and st - cur_end > NIGHT_GAP:
            nights.append(cur)
            cur, cur_end = [], None
        cur.append(s)
        cur_end = en if cur_end is None else max(cur_end, en)
    if cur:
        nights.append(cur)

    out = []
    for n in nights:
        secs = defaultdict(float)
        for s in n:
            v = s["value"].replace("HKCategoryValueSleepAnalysis", "")
            secs[v] += (parse_ts(s["endDate"]) - parse_ts(s["startDate"])).total_seconds()
        start = min(parse_ts(s["startDate"]) for s in n)
        end = max(parse_ts(s["endDate"]) for s in n)
        out.append({
            # Die Nacht gehoert zum Morgen, an dem man aufwacht.
            "night_of": end.date().isoformat(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "span_seconds": (end - start).total_seconds(),
            "seconds_by_value": dict(secs),  # Rohwerte, InBed getrennt
            "segments": n,                   # alle Abschnitte vollstaendig
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export", help="export.zip oder export.xml")
    ap.add_argument("--days", type=int, default=400,
                    help="wie weit zurueck (Standard 400 Tage)")
    ap.add_argument("--out", default="health_extract.json.gz")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=a.days)
    hr_cutoff = now - timedelta(days=HR_DAYS)

    records = defaultdict(list)
    workouts = []
    me = {}
    seen_types = defaultdict(int)  # alle Typen in der Datei, auch verworfene

    f = open_xml(a.export)
    ctx = ET.iterparse(f, events=("start", "end"))
    _, root = next(ctx)
    depth = 0
    for ev, e in ctx:
        if ev == "start":
            depth += 1
            continue
        depth -= 1
        if depth != 0:          # Kind-Elemente erst mit dem Elternteil verarbeiten
            continue
        tag = e.tag
        if tag == "Record":
            t = e.get("type")
            seen_types[t] += 1
            if t in KEEP:
                st = parse_ts(e.get("startDate"))
                lim = hr_cutoff if t.endswith("HeartRate") and "Resting" not in t else cutoff
                if st >= lim:
                    records[t].append(elem_to_dict(e))
        elif tag == "Workout":
            seen_types["Workout"] += 1
            if parse_ts(e.get("startDate")) >= cutoff:
                workouts.append(elem_to_dict(e))
        elif tag == "Me":
            me = dict(e.attrib)
        e.clear()
        root.clear()            # verarbeitete Elemente sofort freigeben
    f.close()

    sleep = records.pop("HKCategoryTypeIdentifierSleepAnalysis", [])
    by_source = defaultdict(list)
    for s in sleep:
        by_source[s.get("sourceName", "?")].append(s)
    nights = {src: group_nights(segs) for src, segs in by_source.items()}

    out = {
        "meta": {
            "created": now.isoformat(),
            "days": a.days,
            "heart_rate_days": HR_DAYS,
            "types_in_file": dict(sorted(seen_types.items())),
        },
        "me": me,
        "sleep_nights_by_source": nights,
        "records": records,
        "workouts": workouts,
    }
    with gzip.open(a.out, "wt", encoding="utf-8") as g:
        json.dump(out, g, ensure_ascii=False)

    # Kurzbericht: Zeitraum und die drei getrennten Anzahlen
    def days(t):
        return {r["startDate"][:10] for r in records.get(t, [])}
    hrv = days("HKQuantityTypeIdentifierHeartRateVariabilitySDNN")
    rhr = days("HKQuantityTypeIdentifierRestingHeartRate")
    staged = {"AsleepDeep", "AsleepCore", "AsleepREM"}
    print(f"Geschrieben: {a.out}")
    for src, ns in nights.items():
        with_stages = [n for n in ns if staged & set(n["seconds_by_value"])]
        if ns:
            print(f"Schlafquelle {src!r}: {len(ns)} Naechte "
                  f"({ns[0]['night_of']} bis {ns[-1]['night_of']}), "
                  f"davon {len(with_stages)} mit Phasen")
    print(f"Tage mit HRV:       {len(hrv)}")
    print(f"Tage mit Ruhepuls:  {len(rhr)}")
    print(f"Workouts:           {len(workouts)}")
    print(f"Pulssamples ({HR_DAYS} T): {len(records.get('HKQuantityTypeIdentifierHeartRate', []))}")


if __name__ == "__main__":
    main()
