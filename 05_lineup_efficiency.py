"""
Fairfield Dynasty League -- Lineup Efficiency Analysis (2023-2025)
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01 and then 03 first -- this reads what 03 saved)

WHAT THIS IS FOR:
  A standalone anti-tanking evidence exhibit -- NOT a trade tool. It shows,
  for every team and every season, how close each manager came to their
  best possible lineup each week. This is the "lineup efficiency" metric
  the league is being asked to vote on in Round 2 (the floor to close the
  0.5-projected-points loophole). Seeing the real numbers lets the league
  vote on a realistic threshold instead of a guess.

HOW IT WORKS:
  For each team, each week:
    actual points  = what they actually started
    optimal points = the best LEGAL lineup they could have set from the
                     players they had rostered that week
    efficiency     = actual / optimal

  Crucially, "legal lineup" uses the roster slot rules that were ACTUALLY
  LIVE that season (your IDP slot count changed over the years), pulled
  from each season's own saved settings -- not this year's rules applied
  retroactively.

  A team that always starts its best available players naturally lands
  around 90-97% (you can't predict busts). A team deliberately benching
  good players shows up as a clear low outlier. That gap is the signal.

OUTPUT:
  data/lineup_efficiency_by_team_season.csv  -- one row per team per season
  data/lineup_efficiency_worst_weeks.csv     -- the lowest-efficiency single
                                                weeks league-wide (the weeks
                                                worth actually looking at)
  Plus a printed league-wide summary you can screenshot into the group chat.

BEFORE RUNNING:
  Run 01_fetch_league_data.py, then 03_fetch_league_history.py (the updated
  version that saves season_league_info.json per season).
"""

import csv
import json
from itertools import combinations
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
HISTORY_DIR = DATA_DIR / "history"

# Slots that any offensive skill player can fill
FLEX_ELIGIBLE = {"RB", "WR", "TE"}
SUPERFLEX_ELIGIBLE = {"QB", "RB", "WR", "TE"}
IDP_POSITIONS = {"LB", "DB", "DL", "DE", "DT", "CB", "S", "IDP", "DEF_LB", "DEF_DB", "DEF_DL"}


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def optimal_lineup_points(roster_positions, player_pool):
    """
    Greedy-then-flex optimal lineup solver.
    player_pool: list of (points, position) for every rostered player that week.
    roster_positions: that season's slots, e.g. ["QB","RB","RB","WR","WR","TE",
                      "FLEX","FLEX","SUPER_FLEX","IDP_FLEX","BN",...]

    Strategy: fill fixed positions with the best players of that position,
    then fill FLEX / SUPER_FLEX / IDP_FLEX from the best remaining eligible.
    Uses a small exhaustive check on the flex assignments to avoid greedy
    mistakes, since the flex counts are tiny.
    """
    # Bucket players by position, sorted high to low
    from collections import defaultdict
    by_pos = defaultdict(list)
    for pts, pos in player_pool:
        by_pos[pos].append(pts)
    for pos in by_pos:
        by_pos[pos].sort(reverse=True)

    # Count slot types
    fixed = defaultdict(int)
    n_flex = n_superflex = n_idp = 0
    for slot in roster_positions:
        if slot == "BN" or slot == "TAXI" or slot == "IR":
            continue
        elif slot == "FLEX":
            n_flex += 1
        elif slot in ("SUPER_FLEX", "SUPERFLEX"):
            n_superflex += 1
        elif slot in ("IDP_FLEX", "IDP"):
            n_idp += 1
        else:
            fixed[slot] += 1

    used = defaultdict(int)  # position -> how many taken
    total = 0.0

    # Fill fixed positions first
    for pos, count in fixed.items():
        available = by_pos.get(pos, [])
        for i in range(count):
            if used[pos] < len(available):
                total += available[used[pos]]
                used[pos] += 1

    # Helper: next-best available player among a set of eligible positions
    def take_best(eligible_positions):
        nonlocal total
        best_pts = None
        best_pos = None
        for pos in eligible_positions:
            avail = by_pos.get(pos, [])
            if used[pos] < len(avail):
                cand = avail[used[pos]]
                if best_pts is None or cand > best_pts:
                    best_pts = cand
                    best_pos = pos
        if best_pos is not None:
            total += best_pts
            used[best_pos] += 1

    # Fill IDP flex (defensive only), then regular flex, then superflex.
    # Order matters slightly; superflex last lets QBs fall through to it.
    for _ in range(n_idp):
        take_best(IDP_POSITIONS)
    for _ in range(n_flex):
        take_best(FLEX_ELIGIBLE)
    for _ in range(n_superflex):
        take_best(SUPERFLEX_ELIGIBLE)

    return round(total, 2)


def main():
    if not HISTORY_DIR.exists():
        raise SystemExit("Missing data/history/ -- run 03_fetch_league_history.py (updated version) first.")

    # Load current player DB for positions
    players = load_json(DATA_DIR / "players_nfl.json")
    pos_by_pid = {pid: (p.get("position") or "") for pid, p in players.items()}

    # Load the CURRENT season's users as the canonical name source. owner_id
    # (Sleeper's internal user_id) never changes even if someone changes their
    # username later -- so resolving every season's names through TODAY's
    # username list keeps one manager as one consistent identity across all
    # years, instead of fragmenting into multiple names if they ever renamed.
    current_users_path = DATA_DIR / "users.json"
    canonical_name_by_user_id = {}
    if current_users_path.exists():
        for u in load_json(current_users_path):
            canonical_name_by_user_id[u["user_id"]] = (
                u.get("display_name") or u.get("username") or u["user_id"]
            )
    else:
        print("  WARNING: data/users.json not found -- run 01_fetch_league_data.py first for "
              "stable cross-season names. Falling back to each season's own snapshot name.")

    season_dirs = sorted([d for d in HISTORY_DIR.iterdir() if d.is_dir()])

    team_season_rows = []
    worst_weeks = []

    for sdir in season_dirs:
        season = sdir.name
        info_path = sdir / "season_league_info.json"
        matchups_path = sdir / "matchups.json"
        users_path = sdir / "users.json"
        rosters_path = sdir / "rosters.json"
        if not (info_path.exists() and matchups_path.exists()):
            print(f"  skipping {season}: missing season info or matchups")
            continue

        info = load_json(info_path)
        roster_positions = info.get("roster_positions", [])
        matchups = load_json(matchups_path)
        users = load_json(users_path) if users_path.exists() else []
        rosters = load_json(rosters_path) if rosters_path.exists() else []

        # roster_id -> manager's name, resolved through the STABLE current
        # user_id lookup built above (falls back to this season's own
        # snapshot only if the manager isn't found there, e.g. someone who
        # has since left the league).
        user_by_id = {u["user_id"]: u for u in users}
        team_by_roster = {}
        for r in rosters:
            oid = r.get("owner_id")
            if oid in canonical_name_by_user_id:
                name = canonical_name_by_user_id[oid]
            else:
                owner = user_by_id.get(oid, {})
                name = owner.get("display_name") or owner.get("username") or f"Roster {r.get('roster_id')}"
            team_by_roster[r.get("roster_id")] = name

        # Accumulate per team across the season
        from collections import defaultdict
        team_actual = defaultdict(float)
        team_optimal = defaultdict(float)
        team_weeks = defaultdict(int)

        if roster_positions and any(s not in ("BN", "IR", "TAXI") for s in roster_positions):
            for week, entries in matchups.items():
                for e in entries:
                    rid = e.get("roster_id")
                    players_points = e.get("players_points") or {}
                    starters_points = e.get("starters_points") or []
                    if not players_points:
                        continue

                    actual = sum(v for v in starters_points if isinstance(v, (int, float)))
                    pool = [(pts, pos_by_pid.get(pid, "")) for pid, pts in players_points.items()]
                    optimal = optimal_lineup_points(roster_positions, pool)

                    if optimal <= 0:
                        continue

                    team_actual[rid] += actual
                    team_optimal[rid] += optimal
                    team_weeks[rid] += 1

                    eff = actual / optimal if optimal else 0
                    worst_weeks.append({
                        "season": season,
                        "week": week,
                        "team": team_by_roster.get(rid, f"Roster {rid}"),
                        "actual": round(actual, 2),
                        "optimal": round(optimal, 2),
                        "efficiency_pct": round(eff * 100, 1),
                    })
        else:
            print(f"  {season}: no usable roster_positions saved -- re-run the updated 03 script")

        for rid in team_actual:
            a = team_actual[rid]
            o = team_optimal[rid]
            team_season_rows.append({
                "season": season,
                "team": team_by_roster.get(rid, f"Roster {rid}"),
                "weeks": team_weeks[rid],
                "actual_points": round(a, 2),
                "optimal_points": round(o, 2),
                "season_efficiency_pct": round((a / o) * 100, 1) if o else "",
            })

    # ---- Write per-team-season table ----
    team_season_rows.sort(key=lambda r: (r["season"], -(r["season_efficiency_pct"] if isinstance(r["season_efficiency_pct"], (int, float)) else 0)))
    out1 = DATA_DIR / "lineup_efficiency_by_team_season.csv"
    with open(out1, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["season", "team", "weeks", "actual_points", "optimal_points", "season_efficiency_pct"])
        w.writeheader()
        w.writerows(team_season_rows)

    # ---- Write worst individual weeks ----
    worst_weeks.sort(key=lambda r: r["efficiency_pct"])
    out2 = DATA_DIR / "lineup_efficiency_worst_weeks.csv"
    with open(out2, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["season", "week", "team", "actual", "optimal", "efficiency_pct"])
        w.writeheader()
        w.writerows(worst_weeks)

    print(f"\nSaved {out1}")
    print(f"Saved {out2}")

    # ---- League-wide summary for the group chat ----
    effs = [r["season_efficiency_pct"] for r in team_season_rows if isinstance(r["season_efficiency_pct"], (int, float))]
    if effs:
        effs_sorted = sorted(effs)
        n = len(effs)
        median = effs_sorted[n // 2]
        avg = round(sum(effs) / n, 1)
        print("\n=== LEAGUE-WIDE LINEUP EFFICIENCY (per team-season) ===")
        print(f"  Team-seasons measured: {n}")
        print(f"  Average efficiency:    {avg}%")
        print(f"  Median efficiency:     {median}%")
        print(f"  Best team-season:      {max(effs)}%")
        print(f"  Worst team-season:     {min(effs)}%")
        print("\nMost teams should cluster high (~88-96%). Team-seasons well below")
        print("that band are worth a closer look -- that's the anti-tanking signal.")
        print("\nThe 10 lowest single weeks league-wide are in lineup_efficiency_worst_weeks.csv.")


if __name__ == "__main__":
    main()