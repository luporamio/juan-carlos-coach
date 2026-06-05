#!/usr/bin/env python3
"""
generate_comments.py — Juan Carlos commenta le sessioni non ancora annotate.
Legge data.json, confronta con coaching.json, chiama Claude API per i gap.
Salva i nuovi commenti in coaching.json.
"""

import json
import os
import sys
import time
import anthropic
from datetime import datetime

SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
DATA_FILE    = os.path.join(SCRIPT_DIR, "data.json")
COACHING_FILE = os.path.join(SCRIPT_DIR, "coaching.json")

MAX_TO_COMMENT = 30   # quante sessioni nuove processare per run
MODEL          = "claude-haiku-4-5-20251001"

RUN_TYPES = {"Run", "VirtualRun"}

JUAN_CARLOS_SYSTEM = """Sei Juan Carlos. Coach di functional fitness e preparatore atletico specializzato in Hyrox e Spartan Race.

Il tuo atleta: Mattia Bonetti, 36 anni, 83-84kg, 178cm. Ex rugbista (16 anni). Si allena 3-4x/settimana.
Ha smesso di fumare il 13/05/2026. FC riposo ~55 bpm post-allenamento.
Obiettivi: Spartan Race 10km Misano 18 sett 2026, HYROX Mixed Doubles Milano 5-6 dic 2026 con Vittoria (target sub 1:10).
PR HYROX: 1:19:57 (Rimini Wellness, 30 mag 2026).

Dati di riferimento corsa:
- Passo Z2: 5:45-6:05/km con FC < 150 bpm
- Passo Z3: 5:15-5:40/km con FC 150-162 bpm
- Passo gara: < 5:10/km
- FC media tipica: 150-162 bpm (ancora alta per easy run)

Il tuo stile:
- Diretto. Poche parole. Niente incoraggiamento vuoto.
- Se va bene: dillo con una frase secca.
- Se va male: dillo chiaramente con la correzione specifica.
- Max 3 frasi. Niente elenchi puntati.
- Qualche parola spagnola nei momenti giusti, senza esagerare.
- MAI usare il trattino em (—). Usa punto, virgola o parentesi.
- Rispondi SOLO con il commento, nessun prefisso."""


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def already_commented(existing_comments, date, act_type):
    return any(c["date"] == date and c["type"] == act_type for c in existing_comments)


def fmt_duration(sec):
    h = sec // 3600
    m = (sec % 3600) // 60
    s = sec % 60
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def fmt_pace(pace_sec):
    if not pace_sec:
        return None
    return f"{pace_sec // 60}:{pace_sec % 60:02d}/km"


def build_prompt(activity):
    t = activity.get("type", "")
    name = activity.get("name", "")
    date = activity.get("date", "")
    km = activity.get("distance_km", 0)
    dur = activity.get("duration_sec", 0)
    hr_avg = activity.get("hr_avg")
    hr_max = activity.get("hr_max")
    pace = activity.get("pace")
    elev = activity.get("elevation", 0)

    parts = [f"Data: {date}", f"Tipo: {t}", f"Nome Strava: {name}"]
    if km > 0:
        parts.append(f"Distanza: {km} km")
    if dur > 0:
        parts.append(f"Durata: {fmt_duration(dur)}")
    if pace:
        parts.append(f"Passo medio: {pace}")
    if hr_avg:
        parts.append(f"FC media: {hr_avg} bpm")
    if hr_max:
        parts.append(f"FC max: {hr_max} bpm")
    if elev > 0:
        parts.append(f"Dislivello: +{elev}m")

    return (
        "Commenta questa sessione di Mattia in 2-3 frasi secche nel tuo stile Juan Carlos. "
        "Includi anche il rating da 1 a 5 (intero) separato su una riga finale nel formato RATING:N\n\n"
        + "\n".join(parts)
    )


def parse_response(text):
    lines = text.strip().splitlines()
    rating = 3
    comment_lines = []
    for line in lines:
        if line.strip().startswith("RATING:"):
            try:
                rating = int(line.strip().split(":")[1].strip())
                rating = max(1, min(5, rating))
            except Exception:
                pass
        else:
            comment_lines.append(line)
    comment = " ".join(l.strip() for l in comment_lines if l.strip())
    return comment, rating


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("ERRORE: ANTHROPIC_API_KEY non trovata.")
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)

    data     = load_json(DATA_FILE)
    coaching = load_json(COACHING_FILE)
    existing = coaching.get("session_comments", [])

    activities = data.get("recent_activities", [])

    to_comment = [
        a for a in activities
        if not already_commented(existing, a["date"], a["type"])
        and a.get("duration_sec", 0) > 300
    ][:MAX_TO_COMMENT]

    if not to_comment:
        print("Nessuna nuova sessione da commentare.")
        return

    print(f"Sessioni da commentare: {len(to_comment)}")
    new_comments = []

    for a in to_comment:
        prompt = build_prompt(a)
        try:
            resp = client.messages.create(
                model=MODEL,
                max_tokens=200,
                system=JUAN_CARLOS_SYSTEM,
                messages=[{"role": "user", "content": prompt}]
            )
            text = resp.content[0].text
            comment, rating = parse_response(text)
            new_comments.append({
                "date":         a["date"],
                "type":         a["type"],
                "rating":       rating,
                "juan_comment": comment,
            })
            print(f"  [{a['date']}] {a['type']} → {rating}★ OK")
            time.sleep(0.3)
        except Exception as e:
            print(f"  [{a['date']}] {a['type']} → ERRORE: {e}")

    if new_comments:
        coaching["session_comments"] = existing + new_comments
        coaching["session_comments"].sort(key=lambda c: c["date"], reverse=True)
        save_json(COACHING_FILE, coaching)
        print(f"\nSalvati {len(new_comments)} nuovi commenti in coaching.json")


if __name__ == "__main__":
    main()