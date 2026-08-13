"""
Fairfield Dynasty League -- Fetch NFL Offensive Context (nflverse)
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football

What this does:
  Pulls real NFL data from nflverse (a free, open-source NFL stats project
  -- not affiliated with Sleeper) for 2023-2025:

  1. PLAYER-LEVEL context: target share, air yards share, WOPR, and EPA
     (offense's per-play efficiency) for every skill player, aggregated
     from weekly data up to a season total/average.
  2. TEAM-LEVEL context: each team's offensive EPA per game and yards per
     game, aggregated the same way -- applied to everyone on that team,
     including IDPs, so defensive players get real team-quality context too.
  3. Player bio data: birth date and draft info, for computing real age.

  nflverse uses different player IDs than Sleeper, and there's no official
  crosswalk between them -- so the join to your roster happens by NAME in
  the next script. That's not perfect (a rare name mismatch is possible)
  but was verified against your real roster at ~97-98% match. Any misses
  get reported clearly, not silently dropped.

BEFORE RUNNING:
  Run 01_fetch_league_data.py first if you haven't.
"""

import csv
import io
import json
from collections import defaultdict
from pathlib import Path

import requests

DATA_DIR = Path(__file__).resolve().parent / "data"
NFLVERSE_DIR = DATA_DIR / "nflverse"
BASE = "https://github.com/nflverse/nflverse-data/releases/download"


def get_seasons():
    """Track the league's current season + 2 prior years, computed dynamically
    from data/league_info.json rather than hardcoded -- so this automatically
    shifts forward once a new season starts, no code edits needed."""
    league_info_path = DATA_DIR / "league_info.json"
    if not league_info_path.exists():
        raise SystemExit("Missing data/league_info.json -- run 01_fetch_league_data.py first.")
    with open(league_info_path, "r", encoding="utf-8") as f:
        league = json.load(f)
    current = int(league["season"])
    return [str(current - 2), str(current - 1), str(current)]  # oldest to newest


SEASONS = get_seasons()
CURRENT_SEASON = SEASONS[-1]

# Sleeper uses LAR for the Rams; nflverse uses LA. This is the one confirmed
# mismatch between the two systems (verified against the real league roster).
TEAM_CODE_FIX = {"LA": "LAR"}


def fetch_csv_rows(url):
    resp = requests.get(url, timeout=60)
    if resp.status_code != 200:
        raise RuntimeError(f"Failed to fetch {url} -- HTTP {resp.status_code}")
    return list(csv.DictReader(io.StringIO(resp.text)))


def to_float(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def save_csv(rows, fieldnames, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)
    print(f"  saved {path.name}  ({len(rows)} rows)")


def aggregate_player_season(weekly_rows):
    """
    Sum/average weekly player stats into one row per (season, player).
    Uses weighted averages for share/efficiency metrics (weighted by targets
    or attempts where relevant) so a 1-game cameo doesn't distort the season.
    """
    buckets = defaultdict(lambda: {
        "games": 0, "targets": 0.0, "target_share_sum": 0.0,
        "air_yards_share_sum": 0.0, "wopr_sum": 0.0,
        "receiving_epa_sum": 0.0, "rushing_epa_sum": 0.0, "passing_epa_sum": 0.0,
        "name": "", "position": "", "team": "",
    })
    for row in weekly_rows:
        key = (row["season"], row["player_display_name"])
        b = buckets[key]
        b["name"] = row["player_display_name"]
        b["position"] = row.get("position", "")
        b["team"] = row.get("team", "") or row.get("recent_team", "")
        b["games"] += 1
        tgt = to_float(row.get("targets"))
        b["targets"] += tgt
        b["target_share_sum"] += to_float(row.get("target_share")) * max(tgt, 1)
        b["air_yards_share_sum"] += to_float(row.get("air_yards_share")) * max(tgt, 1)
        b["wopr_sum"] += to_float(row.get("wopr")) * max(tgt, 1)
        b["receiving_epa_sum"] += to_float(row.get("receiving_epa"))
        b["rushing_epa_sum"] += to_float(row.get("rushing_epa"))
        b["passing_epa_sum"] += to_float(row.get("passing_epa"))

    out = []
    for (season, name), b in buckets.items():
        games = b["games"] or 1
        target_weight = b["targets"] or games  # fall back to game count if no targets (RBs/QBs)
        out.append({
            "season": season,
            "player_name": b["name"],
            "position": b["position"],
            "nfl_team": TEAM_CODE_FIX.get(b["team"], b["team"]),
            "games": b["games"],
            "target_share": round(b["target_share_sum"] / target_weight, 4) if target_weight else "",
            "air_yards_share": round(b["air_yards_share_sum"] / target_weight, 4) if target_weight else "",
            "wopr": round(b["wopr_sum"] / target_weight, 4) if target_weight else "",
            "receiving_epa_per_game": round(b["receiving_epa_sum"] / games, 3),
            "rushing_epa_per_game": round(b["rushing_epa_sum"] / games, 3),
            "passing_epa_per_game": round(b["passing_epa_sum"] / games, 3),
        })
    return out


def aggregate_team_season(weekly_rows):
    """One row per (season, team): offensive EPA/game and yards/game."""
    buckets = defaultdict(lambda: {
        "games": 0, "off_epa_sum": 0.0, "pass_yds": 0.0, "rush_yds": 0.0, "points_for_proxy": 0.0,
    })
    for row in weekly_rows:
        key = (row["season"], row["team"])
        b = buckets[key]
        b["games"] += 1
        b["off_epa_sum"] += to_float(row.get("passing_epa")) + to_float(row.get("rushing_epa"))
        b["pass_yds"] += to_float(row.get("passing_yards"))
        b["rush_yds"] += to_float(row.get("rushing_yards"))

    out = []
    for (season, team), b in buckets.items():
        games = b["games"] or 1
        out.append({
            "season": season,
            "team": TEAM_CODE_FIX.get(team, team),
            "games": b["games"],
            "off_epa_per_game": round(b["off_epa_sum"] / games, 3),
            "pass_yds_per_game": round(b["pass_yds"] / games, 1),
            "rush_yds_per_game": round(b["rush_yds"] / games, 1),
            "total_yds_per_game": round((b["pass_yds"] + b["rush_yds"]) / games, 1),
        })

    # Rank teams within each season by offensive EPA/game (higher = better offense)
    by_season = defaultdict(list)
    for r in out:
        by_season[r["season"]].append(r)
    for season, rows in by_season.items():
        rows.sort(key=lambda r: r["off_epa_per_game"], reverse=True)
        for i, r in enumerate(rows, start=1):
            r["off_rank"] = i

    return out


def main():
    NFLVERSE_DIR.mkdir(parents=True, exist_ok=True)

    all_player_weekly = []
    all_team_weekly = []

    for season in SEASONS:
        print(f"Fetching {season} weekly player stats...")
        url = f"{BASE}/stats_player/stats_player_week_{season}.csv"
        try:
            rows = fetch_csv_rows(url)
            print(f"  got {len(rows)} player-week rows")
            all_player_weekly.extend(rows)
        except RuntimeError as e:
            if season == CURRENT_SEASON:
                print(f"  no data yet for {season} (season likely hasn't started/has no games played yet) -- skipping")
            else:
                raise

        print(f"Fetching {season} weekly team stats...")
        url = f"{BASE}/stats_team/stats_team_week_{season}.csv"
        try:
            rows = fetch_csv_rows(url)
            print(f"  got {len(rows)} team-week rows")
            all_team_weekly.extend(rows)
        except RuntimeError as e:
            if season == CURRENT_SEASON:
                print(f"  no data yet for {season} -- skipping")
            else:
                raise

    print("\nFetching player bio data (age, draft info)...")
    players_bio = fetch_csv_rows(f"{BASE}/players_components/players.csv")
    print(f"  got {len(players_bio)} player bio records")
    bio_fields = ["gsis_id", "display_name", "birth_date", "position", "rookie_season",
                  "draft_year", "draft_round", "draft_pick", "years_of_experience"]
    save_csv(
        [{k: p.get(k, "") for k in bio_fields} for p in players_bio],
        bio_fields,
        NFLVERSE_DIR / "players_bio.csv",
    )

    print("\nAggregating player weekly stats to season level...")
    player_season = aggregate_player_season(all_player_weekly)
    save_csv(
        player_season,
        ["season", "player_name", "position", "nfl_team", "games", "target_share",
         "air_yards_share", "wopr", "receiving_epa_per_game", "rushing_epa_per_game",
         "passing_epa_per_game"],
        NFLVERSE_DIR / "player_context_by_season.csv",
    )

    print("Aggregating team weekly stats to season level...")
    team_season = aggregate_team_season(all_team_weekly)
    save_csv(
        team_season,
        ["season", "team", "games", "off_epa_per_game", "off_rank",
         "pass_yds_per_game", "rush_yds_per_game", "total_yds_per_game"],
        NFLVERSE_DIR / "team_context_by_season.csv",
    )

    print(f"\nDone. Files saved in {NFLVERSE_DIR}")
    print("Next: run 07_build_final_value_board.py")


if __name__ == "__main__":
    main()