#!/usr/bin/env python3
"""Baut die selbsttragende HTML-Seite aus dem Apple-Health-Extrakt.

    python3 build_page.py health_extract.json.gz --out out/bilanz.html [--today 2026-11-16]

Ohne --today gilt der Tag der juengsten Ruhepuls-Messung im Export.
Alle Daten werden in die Datei eingebettet; kein Netz, keine Pakete."""
import argparse
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib_apple import load  # noqa: E402
from compute import compute  # noqa: E402

COLORS = {"bg": "#0A0A0A", "card": "#161616", "t1": "#F2F2F2", "t2": "#B4B4B4", "t3": "#969696"}


def lum(hexc):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hexc[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * ch(r) + 0.7152 * ch(g) + 0.0722 * ch(b)


def contrast(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


FORMULAS = """ERHOLUNG, 0 bis 100 Prozent

  hrv_z = (hrv_letzte_nacht - hrv_mittel) / hrv_streuung
  rhr_z = (ruhepuls_heute - rhr_mittel) / rhr_streuung

  hrv_wert    = begrenze(50 + 20 * hrv_z, 0, 100)     mehr HRV ist besser
  rhr_wert    = begrenze(50 - 20 * rhr_z, 0, 100)     weniger Ruhepuls ist besser
  schlaf_wert = min(100, schlafleistung_prozent)      aus dem Schlafblock unten

  erholung = 0,50 * hrv_wert + 0,25 * rhr_wert + 0,25 * schlaf_wert

Bänder: 67 bis 100 grün, 34 bis 66 gelb, 0 bis 33 rot.

BELASTUNG, 0 bis 21

  tageslast = Summe aller activityTrainingLoad des Tages + 4,0
              (die 4,0 sind das Leben neben dem Training)

  anker     = 95. Perzentil der Tageslast über die Tage MIT Aktivität
              der letzten 90 Tage, mindestens aber 60

  belastung = min(21, 21 * ln(1 + tageslast / 12) / ln(1 + anker / 12))

Bänder: 0 bis 9 leicht, 10 bis 13 moderat, 14 bis 17 hoch, 18 bis 21 alles gegeben.

  puls_anteil = (puls - ruhepuls) / (maxpuls - ruhepuls)
  trimp       = Summe über die Minuten von
                puls_anteil * 0,64 * e^(1,92 * puls_anteil)

SCHLAFBEDARF

  bedarf = grundbedarf + f(belastung) + defizit - nickerchen

  grundbedarf = 8 Stunden 0 Minuten.
  f(belastung) = 1,7 / (1 + e^((17 - belastung_gestern) / 3,5))   in Stunden
  defizit      = min(0,35 * Summe der Fehlstunden gegenüber dem Grundbedarf
                     über die letzten 3 Nächte, 1,5 Stunden)

  schlafleistung = geschlafen / bedarf

BELASTUNGSZIEL AUS DER ERHOLUNG

  Erholung 67 bis 100 Prozent, grün   Zielbelastung 14,0 bis 18,0
  Erholung 34 bis 66 Prozent, gelb    Zielbelastung  9,0 bis 13,5
  Erholung  0 bis 33 Prozent, rot     Zielbelastung  0   bis  8,0"""

DEVIATIONS = [
    "Anker: statt 95. Perzentil die höchste Tageslast der letzten 90 Tage (Mindestwert 60). "
    "Das 95. Perzentil legt per Definition rund 5 % der Aktivitätstage über den Anker und damit über 21 – "
    "bei dir waren es 3 Tage. Entschieden am 16.11.2026.",
    "Tageslast: Apple liefert keine activityTrainingLoad. An ihrer Stelle steht TRIMPexp aus der Pulskurve "
    "(Minutenmittel, Lücken bis 3 min linear gefüllt; überlappende Workouts zählen einmal).",
    "HRV-Basislinie: nur Nächte ab dem Uhrwechsel am 26.09.2026. Die neue Uhr misst rund 85 Werte pro Nacht "
    "statt 3–4; die Streuung beider Reihen ist nicht vergleichbar.",
    "HRV der Nacht: Mittel aller SDNN-Messungen, deren Beginn zwischen Einschlafen und Aufwachen liegt.",
    "Bandgrenzen der Belastung: unter 10 leicht, unter 14 moderat, unter 18 hoch, ab 18 alles gegeben "
    "(die Vorgabe lässt die Lücken 9–10, 13–14, 17–18 offen).",
    "Nickerchen: Schlafblöcke unter 4 h, die zwischen 10 und 19 Uhr beginnen. Kürzere Blöcke in der Nacht "
    "sind kurze Nächte: Sie zählen als Schlaf der Nacht, gehen aber nicht in die Basislinie.",
]

HTML = r"""<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Bilanz</title>
<style>
:root{
  --bg:#0A0A0A; --card:#161616; --t1:#F2F2F2; --t2:#B4B4B4; --t3:#969696;
  --line:rgba(255,255,255,.11); --green:#3FBF6A; --yellow:#E0B23C; --red:#E05555;
  --accent:#D97757; --g1:#E6E6E6; --g2:#A0A0A0; --g3:#6A6A6A; --g4:#3C3C3C;
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--bg);color:var(--t1);
  font-family:system-ui,"Helvetica Neue",Arial,sans-serif;font-size:15px;line-height:1.45}
.col{max-width:520px;margin:0 auto;padding:16px 16px 48px}
.num{font-variant-numeric:tabular-nums;letter-spacing:-.03em;font-weight:600}
.cap{font-size:11px;text-transform:uppercase;letter-spacing:.16em;color:var(--t3)}
.t2{color:var(--t2)} .t3{color:var(--t3)}
header{display:flex;align-items:center;justify-content:space-between;gap:8px}
.mark{width:22px;height:22px;border-radius:50%;border:1px solid var(--line);
  display:grid;place-items:center;flex:none}
.mark i{width:6px;height:6px;border-radius:50%;background:var(--t3)}
.pill{appearance:none;-webkit-appearance:none;background:var(--card);color:var(--t1);
  border:1px solid var(--line);border-radius:999px;padding:6px 14px;font:inherit;
  font-size:13px;font-weight:600;text-align:center;cursor:pointer}
.src{font-size:10px;text-transform:uppercase;letter-spacing:.14em;color:var(--t3);
  text-align:right;max-width:120px;line-height:1.3}
.wordmark{text-align:center;font-size:11px;letter-spacing:.5em;text-transform:uppercase;
  color:var(--t2);margin:22px 0 10px;padding-left:.5em}
svg text{font-family:system-ui,"Helvetica Neue",Arial,sans-serif}
.rings{display:block;width:100%;height:auto;margin:6px 0 14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;margin:12px 0}
h2{margin:30px 0 4px;font-weight:600}
.verdict{font-size:18px;font-weight:700;margin:0 0 6px}
.row{display:flex;justify-content:space-between;align-items:baseline;gap:12px;
  padding:9px 0;border-top:1px solid var(--line)}
.row:first-child{border-top:0}
.row .l{color:var(--t2)}
.row .num{white-space:nowrap}
.sub{font-size:12px;color:var(--t3);margin-top:2px}
.input{padding:10px 0;border-top:1px solid var(--line)}
.input:first-child{border-top:0}
.input .head{display:flex;justify-content:space-between;align-items:baseline}
.bar{display:flex;height:12px;border-radius:999px;overflow:hidden;margin:12px 0 10px}
.legend{display:grid;grid-template-columns:1fr 1fr;gap:4px 16px;font-size:13px}
.sw{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;vertical-align:0}
.note{font-size:12px;color:var(--t3);margin-top:10px}
pre{white-space:pre-wrap;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:11.5px;
  color:var(--t2);margin:0;line-height:1.5}
ul{margin:6px 0 0;padding-left:18px} li{margin:3px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
td,th{padding:6px 0;border-top:1px solid var(--line);text-align:left;font-weight:400}
th{color:var(--t3);font-size:11px;text-transform:uppercase;letter-spacing:.12em;border-top:0}
td.r,th.r{text-align:right}
.chart{display:block;width:100%;height:auto}
</style>
</head>
<body>
<div class="col">
  <header>
    <div class="mark" aria-hidden="true"><i></i></div>
    <select class="pill" id="date" aria-label="Datum wählen"></select>
    <div class="src" id="src"></div>
  </header>
  <div class="wordmark">Bilanz</div>
  <svg class="rings" id="rings" viewBox="0 0 300 102" role="img" aria-label="Sleep, Recovery, Strain"></svg>

  <div class="card" id="finding"></div>

  <h2 class="cap">Mein Tag</h2>
  <div class="card" id="day"></div>

  <h2 class="cap">Recovery</h2>
  <div class="card" id="recovery"></div>

  <h2 class="cap">Sleep</h2>
  <div class="card" id="sleep"></div>

  <h2 class="cap">Strain</h2>
  <div class="card" id="strain"></div>

  <h2 class="cap">Richtung</h2>
  <div class="card" id="direction"></div>

  <h2 class="cap">Ehrlichkeitscheck</h2>
  <div class="card" id="checks"></div>
  <div class="card"><div class="cap" style="margin-bottom:10px">Formeln, wörtlich</div><pre id="formulas"></pre></div>
  <div class="card" id="deviations"></div>
  <div class="card" id="contrast"></div>
  <div class="card" id="notreplace"></div>
</div>

<script type="application/json" id="data">__DATA__</script>
<script>
"use strict";
const D = JSON.parse(document.getElementById("data").textContent);
const $ = id => document.getElementById(id);
const esc = s => String(s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const f = (x, d = 1) => x == null ? "–" : Number(x).toFixed(d).replace(".", ",").replace("-", "−");
const sg = (x, d = 2) => x == null ? "–" : (x >= 0 ? "+" : "") + f(x, d);
const hm = h => { if (h == null) return "–"; const neg = h < 0; h = Math.abs(h);
  let H = Math.floor(h), M = Math.round((h - H) * 60); if (M === 60) { H++; M = 0; }
  return (neg ? "−" : "") + H + ":" + String(M).padStart(2, "0") + " h"; };
const WD = ["So","Mo","Di","Mi","Do","Fr","Sa"];
const dlabel = s => { const [y,m,d] = s.split("-").map(Number); const t = new Date(y, m-1, d);
  return WD[t.getDay()] + ", " + String(d).padStart(2,"0") + "." + String(m).padStart(2,"0") + "." + y; };
const short = s => s.slice(8,10) + "." + s.slice(5,7) + ".";
const BAND = {gruen:{word:"Grün", c:"var(--green)", long:"Grün – gute Erholung"},
              gelb:{word:"Gelb", c:"var(--yellow)", long:"Gelb – mittlere Erholung"},
              rot:{word:"Rot", c:"var(--red)", long:"Rot – geringe Erholung"}};
const row = (l, r, sub) => `<div class="row"><div><div class="l">${l}</div>${sub ? `<div class="sub">${sub}</div>` : ""}</div><div class="num">${r}</div></div>`;

$("src").textContent = "Apple Watch · Export " + short(D.today);
$("formulas").textContent = D.formulas;

const dates = Object.keys(D.days).filter(k => k >= D.show_from).sort();
const sel = $("date");
for (const k of dates.slice().reverse()) { const o = document.createElement("option");
  o.value = k; o.textContent = dlabel(k); sel.appendChild(o); }
sel.value = D.today;
sel.addEventListener("change", () => render(sel.value));

function rings(day) {
  // Masse aus dem Durchmesser: Ringmitten 100 auseinander, Durchmesser 0,72 davon.
  const c = 100, Dm = 0.72 * c, sw = 0.065 * Dm, r = (Dm - sw) / 2;
  const C = 2 * Math.PI * r;                       // echte Pfadlaenge
  const fs = 0.32 * Dm, ls = 0.12 * Dm, gap = 0.14 * Dm, cy = 3 + Dm / 2;
  const sl = day.sleep.perf, rc = day.recovery, st = day.strain.value;
  const items = [
    {x: 50,  frac: sl == null ? 0 : Math.min(sl, 100) / 100, col: "var(--accent)",
     val: sl == null ? "–" : Math.round(Math.min(sl, 100)), unit: sl == null ? "" : "%", name: "Sleep"},
    {x: 150, frac: rc / 100, col: BAND[day.band].c, val: Math.round(rc), unit: "%", name: "Recovery"},
    {x: 250, frac: st / 21, col: "var(--accent)", val: f(st, 1), unit: "", name: "Strain"},
  ];
  $("rings").innerHTML = items.map(i => `
    <circle cx="${i.x}" cy="${cy}" r="${r}" fill="none" stroke="rgba(255,255,255,.11)" stroke-width="${sw}"/>
    <circle cx="${i.x}" cy="${cy}" r="${r}" fill="none" stroke="${i.col}" stroke-width="${sw}"
      stroke-linecap="${i.frac >= 1 ? "butt" : "round"}" stroke-dasharray="${C}" stroke-dashoffset="${C * (1 - Math.max(0, Math.min(1, i.frac)))}"
      transform="rotate(-90 ${i.x} ${cy})"/>
    <text x="${i.x}" y="${cy}" text-anchor="middle" dominant-baseline="central" fill="#F2F2F2"
      font-size="${fs}" font-weight="600" letter-spacing="-0.03em">${i.val}<tspan font-size="${fs * 0.45}" dx="1">${i.unit}</tspan></text>
    <text x="${i.x}" y="${cy + Dm / 2 + gap}" text-anchor="middle" dominant-baseline="hanging" fill="#969696"
      font-size="${ls}" letter-spacing="0.19em" style="text-transform:uppercase">${i.name.toUpperCase()}</text>`).join("");
}

function finding(day) {
  const b = BAND[day.band], [lo, hi] = day.target, s = day.strain.value, isToday = day.date === D.today;
  const where = {darunter: "darunter", "darüber": "darüber", drin: "im Zielband"}[day.strain.in_target];
  const sp = day.sleep;
  let t = `<p class="verdict">${b.long}</p><p class="t2" style="margin:0">`;
  t += `Deine Recovery liegt bei ${Math.round(day.recovery)} %, im ${b.word.toLowerCase()}en Band. Daraus folgt ein Strain-Ziel von ${f(lo)} bis ${f(hi)}. `;
  t += isToday ? `Bis zum Stand des Exports stehst du bei ${f(s)}, also ${where} – der Tag läuft noch. `
               : `Du lagst bei ${f(s)}, also ${where}. `;
  if (sp.asleep_h != null)
    t += `Von deinem Schlafbedarf von ${hm(sp.need_h)} hast du ${hm(sp.asleep_h)} bekommen, ${Math.round(sp.perf)} %.`;
  else t += `Für diese Nacht hat die Uhr keinen Schlaf aufgezeichnet.`;
  $("finding").innerHTML = t + "</p>";
}

function myday(day) {
  const w = day.strain.workouts;
  let h = "";
  if (!w.length) h += `<div class="row"><div class="l">Keine Einheit aufgezeichnet</div><div></div></div>`;
  for (const x of w) {
    const pts = x.trimp == null ? "keine Pulsdaten" : f(x.trimp, 1) + " Pkt";
    h += row(`${esc(x.type)} <span class="t3">· ${x.start}</span>`,
      `${x.min} min · ${x.avg_hr == null ? "–" : x.avg_hr + " bpm"} · ${pts}`,
      x.coverage && x.coverage < 0.8 ? `Puls nur für ${Math.round(x.coverage * 100)} % der Minuten vorhanden` : (x.trimp == null ? esc(x.source) + " – zählt als 0, nicht als Ruhe" : ""));
  }
  h += row("Tageslast", f(day.strain.load, 1), "TRIMPexp der Einheiten + 4,0 für das Leben daneben");
  h += row("Anker", f(day.strain.anchor, 1), "höchste Tageslast der 90 Tage bis zu diesem Tag = Strain 21");
  if (w.length > 1 && Math.abs(w.reduce((a, x) => a + (x.trimp || 0), 0) + 4 - day.strain.load) > 0.5) h += `<div class="note">Überlappende Einheiten zählen in der Tageslast nur einmal; deshalb kann die Summe der Einzelpunkte größer sein.</div>`;
  $("day").innerHTML = h;
}

function strip(key, val, max, labelFn, day) {
  const ks = Object.keys(D.days).sort(), i = ks.indexOf(day.date), win = ks.slice(Math.max(0, i - 6), i + 1);
  const W = 480, H = 110, bw = 44, gap = (W - 7 * bw) / 6, base = 82;
  let s = "";
  win.forEach((k, j) => {
    const v = val(D.days[k]), x = j * (bw + gap), h = v == null ? 0 : Math.max(2, v / max * 72);
    s += `<rect x="${x}" y="${base - h}" width="${bw}" height="${h}" rx="4" fill="${k === day.date ? "var(--accent)" : "#3C3C3C"}"/>`;
    s += `<text x="${x + bw/2}" y="${base - h - 6}" text-anchor="middle" fill="#B4B4B4" font-size="12" font-weight="600" letter-spacing="-0.03em">${v == null ? "–" : labelFn(v)}</text>`;
    s += `<text x="${x + bw/2}" y="${base + 14}" text-anchor="middle" fill="#969696" font-size="11">${short(k)}</text>`;
    if (key === "strain") s += `<text x="${x + bw/2}" y="${base + 27}" text-anchor="middle" fill="#969696" font-size="10">${{darunter:"unter",drin:"im Ziel","darüber":"über"}[D.days[k].strain.in_target]}</text>`;
  });
  return `<svg class="chart" viewBox="0 -4 ${W} ${H + 10}" role="img" aria-label="Sieben Tage">${s}</svg>`;
}

function recoveryCard(day) {
  const I = day.inputs, w = x => x ? Math.round(x * 100) + " %" : "–";
  const used = [I.hrv.w, I.rhr.w, I.sleep.w];
  let h = "";
  const hd = I.hrv, rd = I.rhr;
  h += `<div class="input"><div class="head"><span class="l t2">HRV (SDNN)</span><span class="num">${hd.raw == null ? "fehlt" : f(hd.raw, 1) + " ms"}</span></div>
    <div class="sub">Basis ${f(hd.mean, 1)} ± ${f(hd.sd, 1)} ms aus ${hd.n} Nächten${hd.n < 14 ? " (dünn – springt noch)" : ""} · z ${sg(hd.z)} · Wert ${f(hd.score, 0)} · Gewicht ${w(hd.w)}${hd.drift.drift ? " · Wanderung: 14-Tage-Fenster benutzt" : ""}${hd.kind === "short_night" ? " · aus einer kurzen Nacht" : ""}</div></div>`;
  h += `<div class="input"><div class="head"><span class="l t2">Ruhepuls</span><span class="num">${rd.raw == null ? "fehlt" : f(rd.raw, 0) + " bpm"}</span></div>
    <div class="sub">Basis ${f(rd.mean, 1)} ± ${f(rd.sd, 1)} bpm aus ${rd.n} Tagen · z ${sg(rd.z)} · Wert ${f(rd.score, 0)} · Gewicht ${w(rd.w)}${rd.drift.drift ? " · Wanderung: 14-Tage-Fenster benutzt" : ""}</div></div>`;
  h += `<div class="input"><div class="head"><span class="l t2">Schlafleistung</span><span class="num">${I.sleep.raw == null ? "fehlt" : f(I.sleep.raw, 0) + " %"}</span></div>
    <div class="sub">Wert ${f(I.sleep.score, 0)} · Gewicht ${w(I.sleep.w)}</div></div>`;
  const standard = Math.abs(used[0] - .5) < 1e-9 && Math.abs(used[1] - .25) < 1e-9 && Math.abs(used[2] - .25) < 1e-9;
  h += `<div class="note">${standard ? "Gewichtung wie in der Formel: 50 / 25 / 25." : "Ein Eingang fehlt – sein Gewicht ist anteilig verteilt. Benutzt: HRV " + w(used[0]) + ", Ruhepuls " + w(used[1]) + ", Schlaf " + w(used[2]) + "."}
    Atemfrequenz, Sauerstoffsättigung und Hauttemperatur liegen im Export vor, gehören aber nicht zur Formel und bleiben draußen.</div>`;
  h += `<div class="cap" style="margin:16px 0 4px">Recovery · 7 Tage</div>` + strip("recovery", d => d.recovery, 100, v => Math.round(v), day);
  $("recovery").innerHTML = h;
}

function sleepCard(day) {
  const s = day.sleep;
  let h = "";
  h += row("Grundbedarf", hm(s.base_h), "fest gesetzt – anpassbar in metrics.py (BASE_NEED_H)");
  h += row("Strain von gestern", "+ " + hm(s.f_strain_h), `Strain gestern ${f(s.strain_yesterday)} → 1,7 / (1 + e^((17 − ${f(s.strain_yesterday)}) / 3,5))`);
  h += row("Defizit", "+ " + hm(s.deficit_h), `${hm(s.missing_h)} Fehlzeit gegen 8 h aus ${s.prev_nights} der letzten 3 Nächte × 0,35, höchstens 1:30 h`);
  if (s.nap_h > 0) h += row("Nickerchen gestern", "− " + hm(s.nap_h));
  h += row("<b style='color:var(--t1)'>Bedarf</b>", hm(s.need_h));
  if (s.asleep_h == null) { h += `<div class="note">Keine Nacht aufgezeichnet.</div>`; $("sleep").innerHTML = h; return; }
  h += row("Geschlafen", hm(s.asleep_h), `${s.start}–${s.end}${s.kind === "short_night" ? " · kurze Nacht (unter 4 h)" : ""}`);
  const p = s.phases_min, tot = p.deep + p.core + p.rem + p.awake + p.unspec;
  const parts = [["Tief", p.deep, "var(--g1)"], ["Leicht (Core)", p.core, "var(--g2)"], ["REM", p.rem, "var(--g3)"], ["Wach", p.awake, "var(--g4)"]];
  h += `<div class="bar">` + parts.map(x => `<span style="width:${x[1] / tot * 100}%;background:${x[2]}"></span>`).join("") +
       (p.unspec ? `<span style="width:${p.unspec / tot * 100}%;background:transparent;border:1px dashed #6A6A6A"></span>` : "") + `</div>`;
  h += `<div class="legend">` + parts.map(x => `<div><span class="sw" style="background:${x[2]}"></span>${x[0]} <span class="num t2">${f(x[1] / tot * 100, 0)} %</span></div>`).join("") + `</div>`;
  if (p.unspec) h += `<div class="note">${Math.round(p.unspec)} min Schlaf ohne Phasenzuordnung (gestrichelt).</div>`;
  h += `<div style="margin-top:12px">` + row("Zeit im Bett (geschätzt)", hm(s.span_h), "Spanne erster bis letzter Schlafabschnitt – die Uhr schreibt kein „InBed“, die Zeit vor dem Einschlafen fehlt") +
       row("Zeit im Schlaf", hm(s.asleep_h)) + row("Effizienz (geschätzt, eher zu hoch)", f(s.asleep_h / s.span_h * 100, 0) + " %") + `</div>`;
  $("sleep").innerHTML = h;
}

function strainCard(day) {
  const [lo, hi] = day.target, s = day.strain;
  let h = row("Strain", f(s.value, 1) + " / 21", "Band: " + s.band);
  h += row("Zielband aus Recovery", f(lo) + " – " + f(hi));
  h += row("Im Zielband?", {darunter: "nein, darunter", drin: "ja", "darüber": "nein, darüber"}[s.in_target] + (day.date === D.today ? " (Tag läuft)" : ""));
  h += `<div class="cap" style="margin:16px 0 4px">Strain · 7 Tage</div>` + strip("strain", d => d.strain.value, 21, v => f(v, 1), day);
  $("strain").innerHTML = h;
}

function line(pts, unit, dec, label) {
  const W = 480, H = 120, px = 8, py = 14, xs = pts.map(p => Date.parse(p.x)), ys = pts.map(p => p.y);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y0 = Math.min(...ys), y1 = Math.max(...ys);
  const X = x => px + (x - x0) / (x1 - x0 || 1) * (W - 2 * px), Y = y => py + (1 - (y - y0) / (y1 - y0 || 1)) * (H - 2 * py);
  const d = pts.map((p, i) => (i ? "L" : "M") + X(xs[i]).toFixed(1) + " " + Y(p.y).toFixed(1)).join(" ");
  const last = pts[pts.length - 1];
  return `<svg class="chart" viewBox="0 0 ${W} ${H + 18}" role="img" aria-label="${label}">
    <line x1="${px}" x2="${W - px}" y1="${Y(y1)}" y2="${Y(y1)}" stroke="rgba(255,255,255,.11)"/>
    <line x1="${px}" x2="${W - px}" y1="${Y(y0)}" y2="${Y(y0)}" stroke="rgba(255,255,255,.11)"/>
    <text x="${W - px}" y="${Y(y1) - 4}" text-anchor="end" fill="#969696" font-size="11">${f(y1, dec)} ${unit}</text>
    <text x="${W - px}" y="${Y(y0) + 13}" text-anchor="end" fill="#969696" font-size="11">${f(y0, dec)} ${unit}</text>
    <path d="${d}" fill="none" stroke="#B4B4B4" stroke-width="1.5" stroke-linejoin="round"/>
    <circle cx="${X(xs[xs.length - 1])}" cy="${Y(last.y)}" r="3.5" fill="var(--accent)"/>
    <text x="${px}" y="${H + 14}" fill="#969696" font-size="11">${short(pts[0].x)}${pts[0].x.slice(2,4)}</text>
    <text x="${W - px}" y="${H + 14}" text-anchor="end" fill="#969696" font-size="11">${short(last.x)}${last.x.slice(2,4)}</text></svg>`;
}

function direction() {
  const r = D.direction;
  const dir = (v, eps, up, down, flat) => Math.abs(v) < eps ? flat : (v > 0 ? up : down);
  let h = `<p class="t2" style="margin:0 0 6px">Apple liefert kein Fitnessalter über Monate. Deshalb steht hier keine Tempo-Zahl, sondern die Richtung der drei Größen, die ein Fitnessalter bewegen. Eine Steigung ohne Reihe ist keine Steigung.</p>`;
  h += `<div class="cap" style="margin-top:14px">Ruhepuls · Monatsmittel</div>` + line(r.rhr, "bpm", 1, "Ruhepuls");
  h += `<p class="t2" style="margin:4px 0 0">${dir(r.rhr_slope, .1, "Steigt", "Sinkt", "Etwa flach")}: ${sg(r.rhr_slope)} bpm pro Monat über den ganzen Zeitraum, ${sg(r.rhr_slope_pre)} bis zum Uhrwechsel am ${short(D.watch_switch)} Die Senkung fällt mit dem Gerätewechsel zusammen – Training und Gerät lassen sich hier nicht trennen.</p>`;
  h += `<div class="cap" style="margin-top:18px">Trainingsminuten · pro Woche</div>` + line(r.ex, "min", 0, "Trainingsminuten");
  h += `<p class="t2" style="margin:4px 0 0">${dir(r.ex_slope, 5, "Steigt", "Sinkt", "Etwa flach")}: ${sg(r.ex_slope, 0)} min pro Woche je Monat (lineare Steigung, ${r.ex.length} volle Wochen, Median ${f(r.ex_median, 0)} min). Gemessen sind Apples „Trainingsminuten“ ab zügiger Bewegung – nicht streng intensive Minuten.</p>`;
  h += `<div class="cap" style="margin-top:18px">VO2max · Schätzung der Uhr</div>` + line(r.vo2, "ml/kg/min", 1, "VO2max");
  h += `<p class="t2" style="margin:4px 0 0">${dir(r.vo2_slope, .1, "Steigt", "Sinkt", "Etwa flach")} über den ganzen Zeitraum (${sg(r.vo2_slope, 2)} pro Monat); der letzte Wert ${f(r.vo2[r.vo2.length - 1].y, 1)} ist der höchste der Reihe.</p>`;
  h += `<div class="note">Das ist kein Labor, keine Zellalterung und kein Anbieter-Modell – nur die Richtung von drei Messreihen deiner Uhr. Ein BMI fließt hier nicht ein.</div>`;
  $("direction").innerHTML = h;
}

function checks() {
  const c = D.checks;
  const li = a => "<ul>" + a.map(x => `<li>${x}</li>`).join("") + "</ul>";
  let h = "";
  h += `<div class="cap">1 · Phasensummen gegen Schlafspanne</div>` + li(c.phase_check.map(p => `${short(p.night)}${p.night.slice(2,4)}: Phasen ${f(p.sum_min, 1)} min, Spanne ${f(p.span_min, 1)} min, Differenz ${f(p.diff_min, 1)} min`).concat([`Über alle ${c.phase_total} vollen Nächte: ${c.phase_exact} auf die Minute gleich. Apple hat kein dailySleepDTO; geprüft ist die Summe der Abschnitte gegen Einschlafen bis Aufwachen.`]));
  h += `<div class="cap" style="margin-top:14px">2 · Spannweite der Phasen (${c.staged_nights} volle Nächte, Anteil am Schlaf)</div>` + li([`Tiefschlaf ${f(c.deep_range[0], 1)} % bis ${f(c.deep_range[1], 1)} %`, `REM ${f(c.rem_range[0], 1)} % bis ${f(c.rem_range[1], 1)} %`]);
  h += `<div class="cap" style="margin-top:14px">3 · Anzahlen unter den Basislinien</div>` + li([`HRV: ${c.n_hrv} Nächte (ab Uhrwechsel ${short(D.watch_switch)})`, `Ruhepuls: ${c.n_rhr} Tage (letzte 30)`, `Schlaf: ${c.n_sleep} volle Nächte · Median ${hm(c.sleep_median_h)}, 75. Perzentil ${hm(c.sleep_p75_h)}`]);
  h += `<div class="cap" style="margin-top:14px">4 · Aktivität ohne Pulsdaten (90 Tage)</div>` + li(c.no_hr.length ? c.no_hr.map(x => `${short(x.date)} ${esc(x.type)}, ${x.min} min (${esc(x.source)}) – zählt 0`) : ["keine"]);
  const b = c.bands;
  h += `<div class="cap" style="margin-top:14px">5 · Belastung über 90 Tage</div>` + li([`leicht ${b["leicht"]} · moderat ${b["moderat"]} · hoch ${b["hoch"]} · alles gegeben ${b["alles gegeben"]}`, `über 21: ${c.over21.length ? c.over21.join(", ") : "kein Tag"}`, `Anker ${f(c.anchor, 1)} vom ${short(c.anchor_day)} · ${c.act_days} Tage mit Aktivität · Maximalpuls ${f(c.hrmax, 0)} bpm (${c.hrmax_at}), ${c.spikes_in_workouts} Ausreißer in Workouts entfernt`]);
  h += `<div class="cap" style="margin-top:14px">6 · Fitnessalter-Boden</div>` + li(["entfällt – Apple liefert keine Fitnessalter-Reihe, deshalb gibt es auch kein Tempo."]);
  h += `<div class="cap" style="margin-top:14px">7 · Tage ohne aufgezeichnete Aktivität</div>` + li([`${c.no_act} von 90 Tagen. Davon ohne jede Pulsmessung (Uhr nicht getragen): ${c.no_act_no_hr.length ? c.no_act_no_hr.map(short).join(", ") : "keine"}.`, "Fehlende Aufzeichnung ist nicht Ruhe: Was ohne Uhr passiert, macht den Tag zu niedrig, nicht niedrig."]);
  $("checks").innerHTML = h;
  $("deviations").innerHTML = `<div class="cap" style="margin-bottom:6px">Abweichungen von der Formel – und warum</div>` + li(D.deviations.map(esc));
  $("contrast").innerHTML = `<div class="cap" style="margin-bottom:6px">Kontrast, gerechnet (WCAG)</div><table><tr><th>Text</th><th>Grund</th><th class="r">Verhältnis</th></tr>` +
    D.contrast.map(x => `<tr><td><span class="sw" style="background:${x.fg}"></span>${x.fg}</td><td>${x.bg}</td><td class="r num">${f(x.ratio, 2)} : 1</td></tr>`).join("") + `</table>`;
  $("notreplace").innerHTML = `<div class="cap" style="margin-bottom:6px">Was das nicht ersetzt</div>` + li([
    "Ein eigenes Band am Oberarm oder Finger misst den Puls durchgehend und sauberer als ein Handgelenk unter einem Uhrenarmband. Trägst du die Uhr nachts nicht, gibt es nichts von alledem.",
    "Die Richtung ist kein biologisches Alter. Wer aus einem Handgelenk ein biologisches Alter verkauft, verkauft ein Modell.",
    "Schlafphasen sind auf jedem verkauften Gerät geschätzt. Niemand an deinem Handgelenk liest Hirnströme – die Spannweite oben ist der Blick auf diese Schätzung.",
    "Diese Formeln sind eigene. Die Bausteine sind belegt (Borg-Skala 0–21, TRIMPexp nach Banister), die Zusammensetzung ist eine begründete Nachbildung. Niemand kann behaupten, es sei dieselbe Zahl wie bei einem Hersteller."]);
}

function render(k) {
  const day = D.days[k];
  rings(day); finding(day); myday(day); recoveryCard(day); sleepCard(day); strainCard(day);
}
render(D.today); direction(); checks();
</script>
</body>
</html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("extract")
    ap.add_argument("--out", default="out/bilanz.html")
    ap.add_argument("--today")
    a = ap.parse_args()
    d = load(a.extract)
    if a.today:
        today = date.fromisoformat(a.today)
    else:
        rhr = d["records"].get("HKQuantityTypeIdentifierRestingHeartRate", [])
        today = date.fromisoformat(max(r["startDate"][:10] for r in rhr))
    r = compute(d, today)
    r["formulas"] = FORMULAS
    r["deviations"] = DEVIATIONS
    r["contrast"] = [{"fg": COLORS[t], "bg": COLORS[b], "ratio": round(contrast(COLORS[t], COLORS[b]), 2)}
                     for b in ("bg", "card") for t in ("t1", "t2", "t3")]
    low = [x for x in r["contrast"] if x["ratio"] < 4.5]
    if low:
        sys.exit(f"Kontrast unter 4,5:1: {low}")
    blob = json.dumps(r, ensure_ascii=False, default=str).replace("</", "<\\/")
    os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(HTML.replace("__DATA__", blob))
    print(f"Geschrieben: {a.out} ({os.path.getsize(a.out) / 1024:.0f} KB), Stand {today}")
    for x in r["contrast"]:
        print(f"  Kontrast {x['fg']} auf {x['bg']}: {x['ratio']:.2f}:1")


if __name__ == "__main__":
    main()
