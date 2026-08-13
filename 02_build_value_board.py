"""
Fairfield Dynasty League -- Multi-Year Value Board (2023-2025)
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(same folder as 01_fetch_league_data.py -- run that one first)

What this does:
  Computes every rostered player's ACTUAL fantasy production for each of
  the 2023, 2024, and 2025 NFL regular seasons, using YOUR league's exact
  scoring_settings -- then builds one recency-weighted value score per
  player so recent play counts more than old play.

  Uses POINTS PER GAME as the base unit, not raw season totals, so an
  injury-shortened season doesn't unfairly tank a good player's value.

  This is PRODUCTION-based, not a forward-looking projection. It answers
  "how much has this guy actually produced, in OUR scoring, and how
  recently" -- a legitimate, verifiable foundation for a value board.
  True 2026 dynasty value (age, draft capital, situation change) is a
  separate, harder problem for later.

IMPORTANT CAVEAT:
  The season-stats endpoint this uses is NOT officially documented by
  Sleeper -- only confirmed by community reverse-engineering. It could
  error, or return a shape slightly different than expected. If it errors
  out, copy the exact output and send it back.

BEFORE RUNNING:
  Run 01_fetch_league_data.py first -- this script reads the files it
  saved (league_info.json, players_nfl.json, roster_board.json) instead
  of re-fetching them.
"""

import csv
import json
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent / "data"
BASE = "https://api.sleeper.app/v1"
SEASON_TYPE = "regular"

# ============================================================
# CONFIG -- adjust freely
# ============================================================
# Seasons tracked are computed dynamically from the league's current season
# (read from data/league_info.json, saved by 01) rather than hardcoded, so
# this automatically shifts forward once the 2026 season starts -- no code
# edits needed as seasons pass. Tracks the current season + 2 prior years.

def get_seasons():
    league_info_path = DATA_DIR / "league_info.json"
    if not league_info_path.exists():
        raise SystemExit("Missing data/league_info.json -- run 01_fetch_league_data.py first.")
    with open(league_info_path, "r", encoding="utf-8") as f:
        league = json.load(f)
    current = int(league["season"])
    return [str(current), str(current - 1), str(current - 2)]

SEASONS = get_seasons()
CURRENT_SEASON = SEASONS[0]

# How much each season counts toward the final weighted value.
# If a player is missing a year (rookie, didn't exist in the league yet),
# their available years are automatically re-normalized to sum to 1.0 --
# a rookie with only the most recent season's data just gets 100% weight
# on that one year.
YEAR_WEIGHTS = {
    SEASONS[0]: 0.5,
    SEASONS[1]: 0.3,
    SEASONS[2]: 0.2,
}


def load_json(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise SystemExit(
            f"Missing {filename} in {DATA_DIR}.\n"
            f"Run 01_fetch_league_data.py first -- this script builds on its output."
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_json(url):
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Request failed: {url}\nHTTP {resp.status_code} -- {resp.text[:500]}")
    return resp.json()


def compute_points(stat_line, scoring):
    """Apply the league's scoring_settings to one player's raw season stat line."""
    if not stat_line:
        return None
    total = 0.0
    for stat_key, amount in stat_line.items():
        weight = scoring.get(stat_key)
        if weight:
            total += weight * amount
    return round(total, 2)


def main():
    print("Loading league scoring settings...")
    league = load_json("league_info.json")
    scoring = league["scoring_settings"]

    print("Loading player database...")
    players = load_json("players_nfl.json")

    print("Loading your current rosters...")
    roster_rows = load_json("roster_board.json")
    rostered_ids = sorted({r["player_id"] for r in roster_rows})
    team_by_player = {r["player_id"]: r["team_name"] for r in roster_rows}
    print(f"  {len(rostered_ids)} rostered players to score")

    # ------------------------------------------------------------
    # Fetch all three seasons up front
    # ------------------------------------------------------------
    season_stats = {}
    for season in SEASONS:
        print(f"Fetching {season} {SEASON_TYPE}-season stats for all NFL players...")
        url = f"{BASE}/stats/nfl/{SEASON_TYPE}/{season}"
        try:
            season_stats[season] = fetch_json(url)
            print(f"  got stats for {len(season_stats[season])} players")
        except RuntimeError as e:
            if season == CURRENT_SEASON:
                print(f"  no data yet for {season} (season likely hasn't started/has no games played yet) -- skipping")
                season_stats[season] = {}
            else:
                print("\n--- FETCH FAILED ---")
                print(str(e))
                print(f"\nThis was fetching {season} -- send this exact error back and it can likely be fixed quickly.")
                raise SystemExit(1)

    # ------------------------------------------------------------
    # Score every rostered player, every season
    # ------------------------------------------------------------
    print("Applying your league's scoring settings across all three seasons...")
    rows = []
    for pid in rostered_ids:
        p = players.get(pid, {})
        row = {
            "player_name": p.get("full_name") or pid,
            "position": p.get("position", ""),
            "nfl_team": p.get("team", "") or "FA",
            "fairfield_team": team_by_player.get(pid, ""),
            "player_id": pid,
        }

        available_ppg = {}  # season -> ppg, only for seasons with real data
        for season in SEASONS:
            stat_line = season_stats[season].get(pid)
            pts = compute_points(stat_line, scoring)
            gp = (stat_line or {}).get("gp")
            ppg = round(pts / gp, 2) if (pts is not None and gp) else None

            row[f"pts_{season}"] = pts if pts is not None else ""
            row[f"gp_{season}"] = gp if gp is not None else ""
            row[f"ppg_{season}"] = ppg if ppg is not None else ""

            if ppg is not None:
                available_ppg[season] = ppg

        # Recency-weighted composite, re-normalized to whichever years exist
        if available_ppg:
            weight_sum = sum(YEAR_WEIGHTS[s] for s in available_ppg)
            weighted_value = sum(
                available_ppg[s] * (YEAR_WEIGHTS[s] / weight_sum) for s in available_ppg
            )
            n_years = len(available_ppg)

            # Small-sample confidence discount. A player with only one season
            # of data is a much shakier read than one with three, so we gently
            # shrink thin-sample production toward a low baseline rather than
            # trusting a single year at full face value. 3 years = full trust
            # (no discount); 2 years = mild; 1 year = larger. This keeps a
            # genuinely great rookie ranked well, but stops a middling rookie
            # season from being treated as equal to a proven multi-year track
            # record.
            CONFIDENCE = {1: 0.75, 2: 0.90, 3: 1.00}
            conf = CONFIDENCE.get(n_years, 1.00)
            SHRINK_BASELINE = 4.0  # a low PPG anchor to pull thin samples toward
            weighted_value = SHRINK_BASELINE + (weighted_value - SHRINK_BASELINE) * conf

            row["weighted_value"] = round(weighted_value, 2)
            row["years_of_data"] = n_years
        else:
            row["weighted_value"] = ""
            row["years_of_data"] = 0

        rows.append(row)

    rows.sort(key=lambda r: r["weighted_value"] if r["weighted_value"] != "" else -9999, reverse=True)

    fieldnames = ["player_name", "position", "nfl_team", "fairfield_team", "weighted_value", "years_of_data"]
    for season in SEASONS:
        fieldnames += [f"ppg_{season}", f"pts_{season}", f"gp_{season}"]
    fieldnames.append("player_id")

    out_path = DATA_DIR / "value_board_2023_2025.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    no_data = [r["player_name"] for r in rows if r["years_of_data"] == 0]
    print(f"\nSaved {out_path}")
    print(f"Ranked {len(rows) - len(no_data)} of {len(rows)} rostered players with at least one season of data.")
    if no_data:
        print(f"\n{len(no_data)} players had no data in any of {SEASONS} (likely true rookies, or a name/ID mismatch):")
        for name in no_data[:20]:
            print("  -", name)
        if len(no_data) > 20:
            print(f"  ... and {len(no_data) - 20} more")


if __name__ == "__main__":
    main()
