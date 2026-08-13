"""
Fairfield Dynasty League -- FINAL Value Board
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01, 02, 03, 04, and 06 first -- this merges all of their outputs)

WHAT THIS PRODUCES:
  data/value_board_FINAL.csv -- one row per rostered player with:

  REAL, VISIBLE SIGNALS (no hidden math, just data):
    - weighted_value        : NFL production 2023-2025, recomputed under
                               YOUR current scoring, recency-weighted PPG
    - actual_fairfield_ppg  : real in-league PPG from your league's actual
                               history (script 03/04)
    - age                   : real age, computed from real birth date
    - avg_games_played      : durability across the seasons we have data for
    - weekly_consistency    : lower = more boom/bust, higher = more stable
                               week to week (from real weekly Fairfield
                               scoring history)
    - target_share / air_yards_share / wopr / epa_per_game :
                               real usage and efficiency context from
                               nflverse (2025, or most recent season played)
    - team_off_rank / team_off_epa_per_game :
                               how good the player's CURRENT NFL offense
                               is, for context -- shown, not silently
                               folded into any score
    - fairfield_team        : who currently rosters this player

  ONE COMPOSITE SCORE ("dynasty_score"):
    Built ONLY from the four core, defensible dynasty inputs -- production,
    age, durability, consistency. Team/usage context columns above are
    deliberately NOT part of this score (there's no honest way to say how
    many points a "good offense" is worth -- see conversation notes). The
    weights are a plain config block below, not hidden -- change them and
    rerun to see the board reorder.

    Three preset lenses are included because a contender and a rebuilder
    should NOT value the same player the same way:
      - "balanced"  : default, no strong lean
      - "contender" : production matters most, age barely matters
      - "rebuild"   : age/youth matters a lot, current production less so
    Change LENS below and rerun -- nothing here is picked FOR you.

BEFORE RUNNING:
  Run scripts 01, 02, 03, 04, and 06 first, in that order.
"""

import csv
import json
import re
import statistics
import unicodedata
from datetime import date
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"
NFLVERSE_DIR = DATA_DIR / "nflverse"
HISTORY_DIR = DATA_DIR / "history"

# ============================================================
# CONFIG -- change freely, then rerun
# ============================================================
LENS = "balanced"   # "balanced" | "contender" | "rebuild"

WEIGHT_PRESETS = {
    # production, age (youth), durability, consistency -- must sum to 1.0
    "balanced":  {"production": 0.50, "age": 0.20, "durability": 0.15, "consistency": 0.15},
    "contender": {"production": 0.65, "age": 0.05, "durability": 0.15, "consistency": 0.15},
    "rebuild":   {"production": 0.30, "age": 0.40, "durability": 0.15, "consistency": 0.15},
}

AGE_REFERENCE_DATE = date(2026, 9, 1)  # roughly the 2026 season start

# Known Sleeper-name -> nflverse-name mismatches that can't be solved by
# accent-stripping or suffix-trimming alone -- real nicknames vs. formal
# names. Add to this list if a future season surfaces more (the script
# will print any unmatched names so new ones are easy to spot).
NAME_ALIASES = {
    "cam ward": "cameron ward",
    "kenny gainwell": "kenneth gainwell",
    "foyesade oluokun": "foye oluokun",
}


def strip_accents(text):
    """Turn 'Estimé' into 'Estime', 'Núñez' into 'Nunez', etc."""
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def normalize_name(name):
    name = strip_accents(name).lower().strip()
    name = re.sub(r"[.']", "", name)
    name = re.sub(r"\s+(jr|sr|ii|iii|iv|v)\.?$", "", name)
    name = re.sub(r"[-\s]+", " ", name)
    name = NAME_ALIASES.get(name, name)
    return name.strip()


def load_csv(path):
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def min_max_normalize(values_by_id, invert=False):
    """Map raw values to 0-100 within the given pool. None values stay None."""
    real_vals = [v for v in values_by_id.values() if v is not None]
    if not real_vals:
        return {k: None for k in values_by_id}
    lo, hi = min(real_vals), max(real_vals)
    span = (hi - lo) or 1.0
    out = {}
    for k, v in values_by_id.items():
        if v is None:
            out[k] = None
        else:
            score = (v - lo) / span * 100
            out[k] = round(100 - score if invert else score, 1)
    return out


# IDP positions collapse into one "IDP" group; everyone else stays their own.
IDP_POSITIONS = {"LB", "DB", "DL", "DE", "DT", "CB", "S"}

def position_group(pos):
    return "IDP" if pos in IDP_POSITIONS else (pos or "UNK")


def normalize_within_position(board, value_getter, invert=False):
    """
    Normalize a metric to 0-100 SEPARATELY within each position group, so a
    running back is scored against other running backs, a QB against QBs, etc.
    Returns {player_id: score_or_None}. A player alone in his group (or whose
    group has no spread) lands at 50 -- a neutral middle -- rather than a
    misleading 100 or 0.
    """
    # bucket player_ids by position group
    groups = {}
    for r in board:
        grp = position_group(r["position"])
        groups.setdefault(grp, []).append(r)

    out = {}
    for grp, rows in groups.items():
        vals_by_id = {r["player_id"]: value_getter(r) for r in rows}
        real_vals = [v for v in vals_by_id.values() if v is not None]
        if len(real_vals) < 2 or (max(real_vals) - min(real_vals)) == 0:
            # not enough spread to rank meaningfully within this group
            for pid, v in vals_by_id.items():
                out[pid] = 50.0 if v is not None else None
        else:
            out.update(min_max_normalize(vals_by_id, invert=invert))
    return out


def compute_weekly_consistency():
    """
    stdev of a player's weekly ACTUAL Fairfield points, across all weeks
    found in the saved league history (script 03's matchups.json files).
    Lower stdev = more consistent. Returns {player_id: stdev_or_None}.
    """
    weekly_points = {}  # player_id -> list of weekly points
    if not HISTORY_DIR.exists():
        return {}
    for season_dir in HISTORY_DIR.iterdir():
        if not season_dir.is_dir():
            continue
        matchups_path = season_dir / "matchups.json"
        if not matchups_path.exists():
            continue
        matchups = load_json(matchups_path)
        for week, entries in matchups.items():
            for e in entries:
                players_points = e.get("players_points") or {}
                for pid, pts in players_points.items():
                    weekly_points.setdefault(pid, []).append(pts)

    out = {}
    for pid, pts_list in weekly_points.items():
        if len(pts_list) >= 4:  # need a reasonable sample to say anything about consistency
            out[pid] = round(statistics.stdev(pts_list), 2)
        else:
            out[pid] = None
    return out


def main():
    if LENS not in WEIGHT_PRESETS:
        raise SystemExit(f"LENS must be one of {list(WEIGHT_PRESETS)} -- got '{LENS}'")
    weights = WEIGHT_PRESETS[LENS]
    if abs(sum(weights.values()) - 1.0) > 0.001:
        raise SystemExit(f"Weights for '{LENS}' must sum to 1.0 -- currently sum to {sum(weights.values())}")

    print(f"Using lens: {LENS}  {weights}")

    print("Loading combined value board (production + real in-league history)...")
    board = load_csv(DATA_DIR / "value_board_combined.csv")

    print("Loading nflverse player context...")
    player_ctx_rows = load_csv(NFLVERSE_DIR / "player_context_by_season.csv")
    # name -> {season -> row}, so we can prefer the most recent season with data
    player_ctx_by_name = {}
    for row in player_ctx_rows:
        key = normalize_name(row["player_name"])
        player_ctx_by_name.setdefault(key, {})[row["season"]] = row

    print("Loading nflverse team context...")
    team_ctx_rows = load_csv(NFLVERSE_DIR / "team_context_by_season.csv")
    team_ctx_2025 = {row["team"]: row for row in team_ctx_rows if row["season"] == "2025"}

    print("Loading nflverse player bio (age, draft info)...")
    bio_rows = load_csv(NFLVERSE_DIR / "players_bio.csv")
    bio_by_name = {normalize_name(r["display_name"]): r for r in bio_rows if r.get("display_name")}

    print("Computing weekly consistency from real league history...")
    consistency_by_pid = compute_weekly_consistency()

    # ------------------------------------------------------------
    # Merge everything onto the board
    # ------------------------------------------------------------
    unmatched_player_ctx = []
    unmatched_bio = []
    unmatched_team_ctx = []

    for row in board:
        norm_name = normalize_name(row["player_name"])

        # --- player usage/efficiency context: prefer most recent season available ---
        ctx_by_season = player_ctx_by_name.get(norm_name, {})
        ctx = None
        used_season = ""
        for season in ("2025", "2024", "2023"):
            if season in ctx_by_season:
                ctx = ctx_by_season[season]
                used_season = season
                break
        if ctx:
            row["target_share"] = ctx["target_share"]
            row["air_yards_share"] = ctx["air_yards_share"]
            row["wopr"] = ctx["wopr"]
            row["epa_per_game"] = round(
                to_float(ctx["receiving_epa_per_game"] or 0) +
                to_float(ctx["rushing_epa_per_game"] or 0) +
                to_float(ctx["passing_epa_per_game"] or 0), 3
            )
            row["context_season"] = used_season
        else:
            row["target_share"] = row["air_yards_share"] = row["wopr"] = row["epa_per_game"] = ""
            row["context_season"] = ""
            if row["position"] not in ("LB", "DB", "DL", "DE", "DT", "CB"):  # IDPs expected to miss offense context
                unmatched_player_ctx.append(row["player_name"])

        # --- team context: player's CURRENT team, most recent season ---
        team_row = team_ctx_2025.get(row.get("nfl_team", ""))
        if team_row:
            row["team_off_rank"] = team_row["off_rank"]
            row["team_off_epa_per_game"] = team_row["off_epa_per_game"]
        else:
            row["team_off_rank"] = row["team_off_epa_per_game"] = ""
            if row.get("nfl_team") and row["nfl_team"] != "FA":
                unmatched_team_ctx.append(f"{row['player_name']} ({row['nfl_team']})")

        # --- age ---
        bio = bio_by_name.get(norm_name)
        if bio and bio.get("birth_date"):
            try:
                y, m, d = (int(x) for x in bio["birth_date"].split("-"))
                bday = date(y, m, d)
                age = (AGE_REFERENCE_DATE - bday).days / 365.25
                row["age"] = round(age, 1)
            except (ValueError, TypeError):
                row["age"] = ""
                unmatched_bio.append(row["player_name"])
        else:
            row["age"] = ""
            unmatched_bio.append(row["player_name"])

        # --- durability: average games played across seasons with data ---
        gp_vals = [to_float(row.get(f"gp_{s}")) for s in ("2023", "2024", "2025")]
        gp_vals = [g for g in gp_vals if g is not None and g > 0]
        row["avg_games_played"] = round(sum(gp_vals) / len(gp_vals), 1) if gp_vals else ""

        # --- consistency ---
        stdev = consistency_by_pid.get(row["player_id"])
        row["weekly_consistency_stdev"] = stdev if stdev is not None else ""

    # ------------------------------------------------------------
    # Composite dynasty_score -- ONLY from production/age/durability/consistency,
    # each normalized WITHIN position group (RB vs RB, QB vs QB, WR vs WR,
    # TE vs TE, IDP as one group) so bars mean "how good for his position".
    # ------------------------------------------------------------
    print("Computing composite dynasty_score (scored within position groups)...")
    prod_scores = normalize_within_position(board, lambda r: to_float(r.get("weighted_value")))
    youth_scores = normalize_within_position(board, lambda r: to_float(r.get("age")), invert=True)
    dur_scores = normalize_within_position(board, lambda r: to_float(r.get("avg_games_played")))
    con_scores = normalize_within_position(board, lambda r: to_float(r.get("weekly_consistency_stdev")), invert=True)

    for row in board:
        pid = row["player_id"]
        parts = {
            "production": prod_scores.get(pid),
            "age": youth_scores.get(pid),
            "durability": dur_scores.get(pid),
            "consistency": con_scores.get(pid),
        }
        if any(v is None for v in parts.values()):
            row["dynasty_score"] = ""
            row["dynasty_score_note"] = "insufficient data for one or more components"
        else:
            score = sum(parts[k] * weights[k] for k in parts)
            row["dynasty_score"] = round(score, 1)
            row["dynasty_score_note"] = ""

    board.sort(key=lambda r: r["dynasty_score"] if r["dynasty_score"] != "" else -1, reverse=True)

    # ------------------------------------------------------------
    # Write final CSV
    # ------------------------------------------------------------
    fieldnames = list(board[0].keys())
    out_path = DATA_DIR / "value_board_FINAL.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(board)

    print(f"\nSaved {out_path}")
    print(f"Lens used: {LENS} -- change LENS at the top of this script and rerun to see it differently.")
    scored = sum(1 for r in board if r["dynasty_score"] != "")
    print(f"{scored} of {len(board)} players got a full dynasty_score.")
    print(f"({len(board) - scored} were missing age, production, durability, or consistency data --")
    print(" shown in the CSV with their available columns filled in, just no composite score.)")

    if unmatched_player_ctx:
        print(f"\n{len(unmatched_player_ctx)} offensive players had no nflverse usage data found "
              f"(likely missed the season entirely -- injury, or a name-matching miss):")
        for n in sorted(set(unmatched_player_ctx))[:20]:
            print("  -", n)
    if unmatched_bio:
        print(f"\n{len(set(unmatched_bio))} players had no age/bio data found:")
        for n in sorted(set(unmatched_bio))[:20]:
            print("  -", n)


if __name__ == "__main__":
    main()
