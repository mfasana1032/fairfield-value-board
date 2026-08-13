"""
Fairfield Dynasty League -- Sleeper Data Extraction
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football

What this does:
  1. Pulls your league's scoring settings, roster settings, rosters, and users
     from Sleeper's public API (no login needed).
  2. Pulls the full player database (cached locally -- Sleeper's own docs ask
     that you not call this more than once a day, it's ~5MB).
  3. Pulls traded picks and draft history.
  4. Builds a readable "current rosters" CSV with real player names instead
     of Sleeper's internal player IDs.
  5. Saves everything into a /data folder next to this script.

This is step 1 only -- getting real data on disk. Once you've run this,
send me a couple of the output files (roster_board.csv and league_info.json
are the two I actually need) and I'll help build the scoring-based value
calculations on top of real data instead of guessing at structure.

BEFORE RUNNING:
  1. Install the one dependency this needs:
       pip install requests
  2. Find your league ID. Open your league in the Sleeper app or at
     sleeper.com -- the URL looks like:
       https://sleeper.com/leagues/<LEAGUE_ID>/team
     Copy the long number and paste it into LEAGUE_ID below.
  3. Run it:
       python 01_fetch_league_data.py
"""

import csv
import json
import time
from pathlib import Path

import requests

# ============================================================
# CONFIG -- fill this in before running
# ============================================================
LEAGUE_ID = "1365149429065072640"

# Files get saved in a "data" folder created next to this script,
# wherever you run it from.
DATA_DIR = Path(__file__).resolve().parent / "data"

BASE = "https://api.sleeper.app/v1"


def fetch_json(url, retries=3, pause=1.5):
    """GET a URL and return parsed JSON, retrying a couple times on failure."""
    last_err = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=20)
            if resp.status_code == 200:
                return resp.json()
            last_err = f"HTTP {resp.status_code}"
        except requests.RequestException as e:
            last_err = str(e)
        time.sleep(pause)
    raise RuntimeError(f"Failed to fetch {url} -- {last_err}")


def save_json(obj, filename):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=2)
    print(f"  saved {path.name}  ({path.stat().st_size:,} bytes)")
    return path


def load_cached_players():
    """
    The full player list is ~5MB and Sleeper's docs ask you not to fetch
    it more than once a day. This caches it locally and only re-downloads
    if the cache is missing or older than 24 hours.
    """
    cache_path = DATA_DIR / "players_nfl.json"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 24:
            print(f"  using cached players_nfl.json ({age_hours:.1f}h old)")
            with open(cache_path, "r", encoding="utf-8") as f:
                return json.load(f)
    print("  downloading full player database (~5MB, may take a few seconds)...")
    players = fetch_json(f"{BASE}/players/nfl")
    save_json(players, "players_nfl.json")
    return players


def main():
    if LEAGUE_ID == "PASTE_YOUR_LEAGUE_ID_HERE":
        raise SystemExit(
            "Set LEAGUE_ID at the top of this script before running.\n"
            "Find it in your league URL: https://sleeper.com/leagues/<LEAGUE_ID>/team"
        )

    print("Fetching league info (includes scoring_settings and roster_positions)...")
    league = fetch_json(f"{BASE}/league/{LEAGUE_ID}")
    save_json(league, "league_info.json")

    print("Fetching rosters...")
    rosters = fetch_json(f"{BASE}/league/{LEAGUE_ID}/rosters")
    save_json(rosters, "rosters.json")

    print("Fetching users...")
    users = fetch_json(f"{BASE}/league/{LEAGUE_ID}/users")
    save_json(users, "users.json")

    print("Fetching traded picks...")
    traded_picks = fetch_json(f"{BASE}/league/{LEAGUE_ID}/traded_picks")
    save_json(traded_picks, "traded_picks.json")

    print("Fetching draft history...")
    drafts = fetch_json(f"{BASE}/league/{LEAGUE_ID}/drafts")
    save_json(drafts, "drafts.json")

    print("Loading player database (cached, only re-downloads once a day)...")
    players = load_cached_players()

    # ------------------------------------------------------------
    # Build a readable roster board: team name -> players on that roster
    # ------------------------------------------------------------
    print("Building readable roster board...")
    user_by_id = {u["user_id"]: u for u in users}

    roster_rows = []
    for r in rosters:
        owner_id = r.get("owner_id")
        user = user_by_id.get(owner_id, {})
        # Use the manager's Sleeper username, not their team nickname --
        # nicknames get changed season to season, which makes tracking one
        # manager across years confusing. Roster.owner_id always resolves
        # to exactly one primary user even on co-owned teams, so this
        # naturally picks one person's name without extra logic.
        team_name = (
            user.get("display_name")
            or user.get("username")
            or f"Roster {r['roster_id']}"
        )
        starters = set(r.get("starters") or [])
        for pid in (r.get("players") or []):
            p = players.get(pid, {})
            roster_rows.append({
                "team_name": team_name,
                "player_name": p.get("full_name") or pid,
                "position": p.get("position", ""),
                "nfl_team": p.get("team", "") or "FA",
                "is_starter": pid in starters,
                "player_id": pid,
            })

    save_json(roster_rows, "roster_board.json")

    csv_path = DATA_DIR / "roster_board.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["team_name", "player_name", "position", "nfl_team", "is_starter", "player_id"],
        )
        writer.writeheader()
        writer.writerows(roster_rows)
    print(f"  saved {csv_path.name}")

    print("\nDone. Files are in:", DATA_DIR)
    print("Scoring settings for the value board live in league_info.json -> 'scoring_settings'.")
    print("Send me roster_board.csv and league_info.json next and we'll build the value calculations.")


if __name__ == "__main__":
    main()