#!/usr/bin/env python3
"""Ein Befehl fuer jeden Morgen: neuesten Apple-Health-Export finden,
bei Bedarf neu extrahieren, Seite neu bauen.

    python3 update.py ~/Bilanz

Erwartet im Ordner: die Skripte dieses Verzeichnisses und eine oder mehrere
Export-ZIPs (Export.zip, export.zip, ...). Ist die neueste ZIP juenger als
health_extract.json.gz, wird neu extrahiert; danach immer neu gebaut.
Schreibt ein Protokoll nach bilanz.log. Liest und schreibt nur in diesem Ordner.
"""
import glob
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))


def log(folder, msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(os.path.join(folder, "bilanz.log"), "a", encoding="utf-8") as f:
        f.write(line + "\n")


def main():
    folder = os.path.abspath(os.path.expanduser(sys.argv[1] if len(sys.argv) > 1 else HERE))
    extract = os.path.join(folder, "health_extract.json.gz")
    zips = [z for z in glob.glob(os.path.join(folder, "*.zip"))
            if "export" in os.path.basename(z).lower()]
    newest = max(zips, key=os.path.getmtime) if zips else None

    if newest and (not os.path.exists(extract)
                   or os.path.getmtime(newest) > os.path.getmtime(extract)):
        log(folder, f"Neuer Export: {os.path.basename(newest)} - extrahiere")
        tmp = extract + ".tmp"   # altes Extrakt bleibt, bis das neue fertig ist
        subprocess.run([sys.executable, os.path.join(HERE, "extract_apple_health.py"),
                        newest, "--out", tmp], check=True)
        os.replace(tmp, extract)
    elif not os.path.exists(extract):
        log(folder, "Kein Export und kein Extrakt gefunden - nichts zu tun")
        return 1
    else:
        log(folder, "Kein neuerer Export - baue aus dem vorhandenen Extrakt")

    out = os.path.join(folder, "bilanz.html")
    subprocess.run([sys.executable, os.path.join(HERE, "build_page.py"),
                    extract, "--out", out], check=True)
    log(folder, f"Seite gebaut: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
