"""
Fairfield Dynasty League -- Pull Real League History (2023-2025)
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(same folder as the other scripts -- run 01_fetch_league_data.py first)

What this does:
  Sleeper links each season's league to the one before it via
  "previous_league_id". This walks that chain backward from your current
  (2026) league to your 2023 startup season, and for each season along the
  way pulls:
    - that season's own league settings (to know how many weeks it ran)
    - that season's rosters and users (team names change year to year)
    - every week's real matchups, which include Sleeper's own computed
      fantasy score for every rostered player, every week -- the actual
      numbers your league saw in real time, not a recalculation.

  Saves everything to data/history/<season>/ as JSON, plus one combined
  file: actual_points_by_player.json -- every player's real, total
  Fairfield-league points and weeks-rostered across all seasons found.

BEFORE RUNNING:
  Run 01_fetch_league_data.py first if you haven't -- this reads
  data/league_info.json to find the starting point.
"""

import json
import time
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent / "data"
HISTORY_DIR = DATA_DIR / "history"
BASE = "https://api.sleeper.app/v1"

MIN_SEASON = "2023"   # don't walk back further than the league's actual startup year
MAX_WEEK_TRY = 17     # upper bound on weeks to try fetching per season


def fetch_json(url):
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code} -- {resp.text[:300]}"
    return resp.json(), None


def save_json(obj, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)


def walk_league_chain(start_league_id):
    """Return a list of league info dicts, most recent first, back to MIN_SEASON."""
    chain = []
    current_id = start_league_id
    seen = set()
    while current_id and current_id not in seen:
        seen.add(current_id)
        league, err = fetch_json(f"{BASE}/league/{current_id}")
        if err or not league:
            print(f"  stopped chain walk at league {current_id}: {err}")
            break
        chain.append(league)
        season = league.get("season", "")
        print(f"  found season {season}  (league_id {current_id})")
        if season and season <= MIN_SEASON:
            break
        current_id = league.get("previous_league_id")
    return chain


def main():
    league_info_path = DATA_DIR / "league_info.json"
    if not league_info_path.exists():
        raise SystemExit("Missing data/league_info.json -- run 01_fetch_league_data.py first.")
    with open(league_info_path, "r", encoding="utf-8") as f:
        current_league = json.load(f)

    print("Walking the league history chain backward via previous_league_id...")
    chain = walk_league_chain(current_league["league_id"])
    print(f"\nFound {len(chain)} seasons: {[l.get('season') for l in chain]}")

    # player_id -> {"total_points": float, "weeks_rostered": int, "by_season": {season: pts}}
    actual_points = {}

    for league in chain:
        season = league.get("season")
        league_id = league.get("league_id")
        settings = league.get("settings", {})
        # Regular season + playoffs both count real production -- try a safe upper bound of weeks.
        playoff_start = settings.get("playoff_week_start") or 15
        playoff_teams = settings.get("playoff_teams") or 0
        # rough estimate of how many playoff rounds are needed
        import math
        playoff_rounds = math.ceil(math.log2(playoff_teams)) if playoff_teams > 1 else 0
        last_week_guess = min(playoff_start + playoff_rounds, MAX_WEEK_TRY)

        print(f"\n=== Season {season} (league_id {league_id}) ===")
        season_dir = HISTORY_DIR / str(season)

        # Save this season's own settings + roster_positions -- the IDP slot count
        # and scoring changed year to year, so optimal-lineup math must use the
        # rules that were actually live that season, not this year's rules.
        save_json({
            "season": season,
            "league_id": league_id,
            "roster_positions": league.get("roster_positions", []),
            "scoring_settings": league.get("scoring_settings", {}),
            "settings": settings,
        }, season_dir / "season_league_info.json")

        print("  fetching rosters and users for this season...")
        rosters, err1 = fetch_json(f"{BASE}/league/{league_id}/rosters")
        users, err2 = fetch_json(f"{BASE}/league/{league_id}/users")
        if err1 or err2:
            print(f"  WARNING: could not get rosters/users for {season}: {err1 or err2}")
            rosters, users = rosters or [], users or []
        save_json(rosters, season_dir / "rosters.json")
        save_json(users, season_dir / "users.json")

        print(f"  fetching matchups for weeks 1-{last_week_guess}...")
        season_matchup_data = {}
        weeks_found = 0
        for week in range(1, last_week_guess + 1):
            matchups, err = fetch_json(f"{BASE}/league/{league_id}/matchups/{week}")
            if err or not matchups:
                continue
            weeks_found += 1
            season_matchup_data[str(week)] = matchups

            for roster_entry in matchups:
                players_points = roster_entry.get("players_points") or {}
                for pid, pts in players_points.items():
                    if pid not in actual_points:
                        actual_points[pid] = {"total_points": 0.0, "weeks_rostered": 0, "by_season": {}}
                    actual_points[pid]["total_points"] += pts
                    actual_points[pid]["weeks_rostered"] += 1
                    actual_points[pid]["by_season"][season] = round(
                        actual_points[pid]["by_season"].get(season, 0.0) + pts, 2
                    )
            time.sleep(0.05)  # be polite to the API

        print(f"  got real matchup data for {weeks_found} weeks")
        save_json(season_matchup_data, season_dir / "matchups.json")

    for pid in actual_points:
        actual_points[pid]["total_points"] = round(actual_points[pid]["total_points"], 2)

    out_path = DATA_DIR / "actual_points_by_player.json"
    save_json(actual_points, out_path)
    print(f"\nSaved {out_path}")
    print(f"Real in-league data found for {len(actual_points)} unique players across {len(chain)} seasons.")


if __name__ == "__main__":
    main()