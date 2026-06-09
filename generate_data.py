#!/usr/bin/env python3
"""
generate_data.py — genera dashboard/data.json con gli ultimi 90 giorni di attività Strava
e i dati Apple Health (health_reader.py).
Chiamato da strava_sync.py dopo ogni sync.
"""

import json
import os
import sys
import time
import requests
from datetime import datetime, timedelta
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Importa health_reader da COACH_ATLETICO
COACH_DIR = os.path.expanduser("~/MY_OS/AGENTI/COACH_ATLETICO")
if COACH_DIR not in sys.path:
    sys.path.insert(0, COACH_DIR)
TOKENS_FILE = os.path.join(
    os.path.expanduser("~/MY_OS/AGENTI/COACH_ATLETICO"),
    ".strava_tokens.json"
)
OUTPUT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data.json")

DAYS_BACK = 3650  # ~10 anni: prende tutto lo storico
RUN_TYPES = {"Run", "VirtualRun"}

GOALS = [
    {"name": "Spartan Race 10km", "location": "Misano", "date": "2026-09-18",
     "target": None, "icon": "mountain", "prep_start": "2026-06-01"},
    {"name": "Hyrox Mixed Doubles · Milano", "location": "Milano", "date": "2026-12-06",
     "target": "sub 1:10:00", "icon": "zap", "prep_start": "2026-06-01", "partner": "Vittoria"},
]

DAY_NAMES_IT = ["Lun", "Mar", "Mer", "Gio", "Ven", "Sab", "Dom"]
MONTH_NAMES_IT = ["Gen","Feb","Mar","Apr","Mag","Giu","Lug","Ago","Set","Ott","Nov","Dic"]


def load_tokens():
    # GitHub Actions: usa variabili d'ambiente
    if os.environ.get("STRAVA_CLIENT_ID"):
        return {
            "client_id": os.environ["STRAVA_CLIENT_ID"],
            "client_secret": os.environ["STRAVA_CLIENT_SECRET"],
            "refresh_token": os.environ["STRAVA_REFRESH_TOKEN"],
            "access_token": "",
            "expires_at": 0,
        }
    # Locale: usa file token
    if not os.path.exists(TOKENS_FILE):
        print("ERRORE: Token non trovati.")
        sys.exit(1)
    with open(TOKENS_FILE) as f:
        return json.load(f)


def refresh_if_needed(tokens):
    if tokens.get("access_token") and time.time() < tokens["expires_at"] - 300:
        return tokens
    resp = requests.post("https://www.strava.com/oauth/token", data={
        "client_id": tokens["client_id"],
        "client_secret": tokens["client_secret"],
        "refresh_token": tokens["refresh_token"],
        "grant_type": "refresh_token",
    })
    resp.raise_for_status()
    new = resp.json()
    tokens.update({
        "access_token": new["access_token"],
        "refresh_token": new["refresh_token"],
        "expires_at": new["expires_at"],
    })
    if not os.environ.get("STRAVA_CLIENT_ID") and os.path.exists(TOKENS_FILE):
        with open(TOKENS_FILE, "w") as f:
            json.dump(tokens, f, indent=2)
    return tokens


def fetch_all(access_token, after_ts):
    all_acts = []
    page = 1
    while True:
        resp = requests.get(
            "https://www.strava.com/api/v3/athlete/activities",
            headers={"Authorization": f"Bearer {access_token}"},
            params={"after": after_ts, "per_page": 50, "page": page}
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        all_acts.extend(batch)
        page += 1
    return all_acts


def pace_sec(speed_ms):
    if not speed_ms or speed_ms == 0:
        return None
    return round(1000 / speed_ms)


def format_pace(speed_ms):
    s = pace_sec(speed_ms)
    if not s:
        return None
    m, sec = divmod(s, 60)
    return f"{m}:{sec:02d}/km"


def hr_zone(hr):
    if hr is None:
        return None
    if hr < 115:   return "z1"
    elif hr < 145: return "z2"
    elif hr < 160: return "z3"
    elif hr < 175: return "z4"
    else:          return "z5"


def iso_week(date_str):
    d = datetime.fromisoformat(date_str[:10])
    return d.strftime("%Y-W%V")


def clean_activity(a):
    return {
        "date": a["start_date_local"][:10],
        "datetime": a["start_date_local"][:16],
        "type": a.get("type", ""),
        "name": a.get("name", ""),
        "distance_km": round(a.get("distance", 0) / 1000, 2),
        "duration_sec": a.get("moving_time", 0),
        "pace": format_pace(a.get("average_speed", 0)) if a.get("type") in RUN_TYPES else None,
        "pace_sec": pace_sec(a.get("average_speed", 0)) if a.get("type") in RUN_TYPES else None,
        "hr_avg": round(a["average_heartrate"]) if a.get("average_heartrate") else None,
        "hr_max": round(a["max_heartrate"]) if a.get("max_heartrate") else None,
        "elevation": int(a.get("total_elevation_gain", 0)),
        "suffer_score": a.get("suffer_score"),
    }


def compute_stats(acts, days):
    runs = [a for a in acts if a.get("type") in RUN_TYPES]
    total_km = sum(a.get("distance", 0) for a in runs) / 1000
    paces = [pace_sec(a.get("average_speed", 0)) for a in runs if pace_sec(a.get("average_speed", 0))]
    all_hrs = [a.get("average_heartrate") for a in acts if a.get("average_heartrate")]

    elevations = [a.get("total_elevation_gain", 0) or 0 for a in acts]
    total_elevation = int(sum(elevations))

    long_runs = [a for a in runs if a.get("distance", 0) > 5000]
    long_paces = [pace_sec(a.get("average_speed", 0)) for a in long_runs if pace_sec(a.get("average_speed", 0))]
    best_pace = min(long_paces) if long_paces else None

    distances = [a.get("distance", 0) for a in runs]
    longest_run = round(max(distances) / 1000, 1) if distances else 0.0

    return {
        "total_km": round(total_km, 1),
        "run_sessions": len(runs),
        "all_sessions": len(acts),
        "avg_pace": round(sum(paces) / len(paces)) if paces else None,
        "avg_hr": round(sum(all_hrs) / len(all_hrs)) if all_hrs else None,
        "total_elevation": total_elevation,
        "best_pace": best_pace,
        "longest_run": longest_run,
        "days": days,
    }


def compute_hr_zones(runs):
    zone_counts = defaultdict(int)
    total = 0
    for r in runs:
        z = hr_zone(r.get("average_heartrate"))
        if z:
            zone_counts[z] += 1
            total += 1
    return {z: round(zone_counts[z] / total * 100) if total else 0
            for z in ["z1", "z2", "z3", "z4", "z5"]}


def build_pace_trend(runs):
    trend = []
    for r in sorted(runs, key=lambda x: x["start_date"]):
        p = pace_sec(r.get("average_speed", 0))
        if not p:
            continue
        trend.append({
            "date": r["start_date_local"][:10],
            "pace_sec": p,
            "hr": round(r["average_heartrate"]) if r.get("average_heartrate") else None,
            "km": round(r.get("distance", 0) / 1000, 1),
        })
    return trend


def build_monthly_volume(runs):
    monthly = defaultdict(lambda: {"km": 0, "sessions": 0, "label": ""})
    for r in sorted(runs, key=lambda x: x["start_date"]):
        mk = r["start_date_local"][:7]
        monthly[mk]["km"] += r.get("distance", 0) / 1000
        monthly[mk]["sessions"] += 1
        d = datetime.fromisoformat(r["start_date_local"][:10])
        monthly[mk]["label"] = f"{MONTH_NAMES_IT[d.month - 1]} '{str(d.year)[2:]}"
    months = sorted(monthly.keys())[-24:]
    return [{"month": m, "label": monthly[m]["label"],
             "km": round(monthly[m]["km"], 1), "sessions": monthly[m]["sessions"]}
            for m in months]


def build_weekly_volume(runs):
    weekly = defaultdict(lambda: {"km": 0, "sessions": 0, "label": ""})
    for r in sorted(runs, key=lambda x: x["start_date"]):
        w = iso_week(r["start_date_local"])
        weekly[w]["km"] += r.get("distance", 0) / 1000
        weekly[w]["sessions"] += 1
        d = datetime.fromisoformat(r["start_date_local"][:10])
        monday = d - timedelta(days=d.weekday())
        weekly[w]["label"] = f"{monday.day} {MONTH_NAMES_IT[monday.month - 1]}"
    weeks = sorted(weekly.keys())[-52:]
    return [{"week": w, "label": weekly[w]["label"],
             "km": round(weekly[w]["km"], 1), "sessions": weekly[w]["sessions"]}
            for w in weeks]


def build_stats_by_type(activities):
    by_type = defaultdict(lambda: {"sessions": 0, "total_km": 0.0, "total_time_sec": 0, "total_elevation": 0})
    for a in activities:
        t = a.get("type", "Other")
        by_type[t]["sessions"] += 1
        by_type[t]["total_km"] += a.get("distance", 0) / 1000
        by_type[t]["total_time_sec"] += a.get("moving_time", 0)
        by_type[t]["total_elevation"] += int(a.get("total_elevation_gain", 0) or 0)
    result = {}
    for t, v in sorted(by_type.items(), key=lambda x: -x[1]["sessions"]):
        result[t] = {
            "sessions": v["sessions"],
            "total_km": round(v["total_km"], 1),
            "total_time_min": round(v["total_time_sec"] / 60),
            "total_elevation": v["total_elevation"],
        }
    return result


def build_current_week(activities):
    today = datetime.now().date()
    monday = today - timedelta(days=today.weekday())
    week_days = []
    acts_by_date = defaultdict(list)
    for a in activities:
        acts_by_date[a["start_date_local"][:10]].append(a)

    for i in range(7):
        d = monday + timedelta(days=i)
        date_str = d.strftime("%Y-%m-%d")
        day_acts = [clean_activity(a) for a in acts_by_date.get(date_str, [])]
        km = sum(a["distance_km"] for a in day_acts if a["distance_km"] > 0)
        week_days.append({
            "date": date_str,
            "day": DAY_NAMES_IT[i],
            "day_num": d.day,
            "month": MONTH_NAMES_IT[d.month - 1],
            "is_today": d == today,
            "is_past": d < today,
            "activities": day_acts,
            "total_km": round(km, 1),
            "session_count": len(day_acts),
        })
    return week_days


def build_data(activities):
    now = datetime.now()

    cutoffs = {
        "7d":   now - timedelta(days=7),
        "30d":  now - timedelta(days=30),
        "90d":  now - timedelta(days=90),
        "365d": now - timedelta(days=365),
    }

    def filter_acts(days_key):
        cutoff = cutoffs[days_key]
        return [a for a in activities
                if datetime.fromisoformat(a["start_date_local"][:19]) > cutoff]

    def filter_runs(days_key):
        cutoff = cutoffs[days_key]
        return [a for a in all_runs
                if datetime.fromisoformat(a["start_date_local"][:19]) > cutoff]

    all_clean = [clean_activity(a) for a in
                 sorted(activities, key=lambda x: x["start_date"], reverse=True)]

    all_runs = [a for a in activities if a.get("type") in RUN_TYPES]

    return {
        "athlete": {"name": "Mattia Bonetti", "total_activities": len(activities)},
        "goals": GOALS,
        "last_sync": now.strftime("%Y-%m-%d %H:%M"),
        "stats": {
            "7d":   compute_stats(filter_acts("7d"),   7),
            "30d":  compute_stats(filter_acts("30d"),  30),
            "90d":  compute_stats(filter_acts("90d"),  90),
            "365d": compute_stats(filter_acts("365d"), 365),
            "all":  compute_stats(activities, len(activities)),
        },
        "weekly_volume": build_weekly_volume(all_runs),
        "monthly_volume": build_monthly_volume(all_runs),
        "pace_trend": {
            "7d":   build_pace_trend(filter_runs("7d")),
            "30d":  build_pace_trend(filter_runs("30d")),
            "90d":  build_pace_trend(filter_runs("90d")),
            "365d": build_pace_trend(filter_runs("365d")),
            "all":  build_pace_trend(all_runs),
        },
        "hr_zones": {
            "7d":   compute_hr_zones(filter_runs("7d")),
            "30d":  compute_hr_zones(filter_runs("30d")),
            "90d":  compute_hr_zones(filter_runs("90d")),
            "365d": compute_hr_zones(filter_runs("365d")),
            "all":  compute_hr_zones(all_runs),
        },
        "stats_by_type": {
            "7d":   build_stats_by_type(filter_acts("7d")),
            "30d":  build_stats_by_type(filter_acts("30d")),
            "90d":  build_stats_by_type(filter_acts("90d")),
            "365d": build_stats_by_type(filter_acts("365d")),
            "all":  build_stats_by_type(activities),
        },
        "recent_activities": all_clean[:200],
        "current_week": build_current_week(activities),
    }


def build_health_data():
    try:
        from health_reader import read_health, recovery_score
        health = read_health(days=30)
        today = health.get("today", {})
        avg_rhr = health["summary_7d"].get("resting_hr_avg")
        score = recovery_score(today, avg_rhr)
        return {
            "today": today,
            "daily": health["daily"],
            "summary_7d": health["summary_7d"],
            "recovery_score": score,
        }
    except Exception as e:
        print(f"[health] Dati salute non disponibili: {e}")
        return {}


def main():
    tokens = load_tokens()
    tokens = refresh_if_needed(tokens)
    after_ts = int((datetime.now() - timedelta(days=DAYS_BACK)).timestamp())
    activities = fetch_all(tokens["access_token"], after_ts)
    data = build_data(activities)
    data["health"] = build_health_data()
    with open(OUTPUT_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Dashboard data generato: {OUTPUT_FILE} ({len(activities)} attività totali)")


if __name__ == "__main__":
    main()
