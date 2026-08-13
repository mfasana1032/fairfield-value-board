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
    # production > consistency > age > durability (durability kept low since it
    # partly overlaps consistency -- an injury-prone player already loses points
    # on consistency and production). Must sum to 1.0.
    "balanced":  {"production": 0.60, "consistency": 0.18, "age": 0.14, "durability": 0.08},
    "contender": {"production": 0.68, "consistency": 0.18, "age": 0.06, "durability": 0.08},
    "rebuild":   {"production": 0.42, "consistency": 0.14, "age": 0.36, "durability": 0.08},
}

AGE_REFERENCE_DATE = date(2026, 9, 1)  # roughly the 2026 season start

# ---- Youth curve --------------------------------------------------------
# Youth is NOT scored as a raw 0-100 linear scale, because that made the
# single youngest player a runaway 100 and turned "being 22 instead of 24"
# into a huge, football-irrelevant score swing. Instead, age maps to a
# youth score through an explicit curve tuned to the real age distribution
# (almost everyone is 22-33): young players cluster near the top with only
# small gaps between them, and the score only drops meaningfully as players
# age into real dynasty decline. Anchors are (age, youth_score); anything
# between anchors is linearly interpolated, and anything outside is clamped.
YOUTH_CURVE = [
    (22.0, 100.0),
    (24.0, 92.0),
    (25.0, 88.0),
    (27.0, 74.0),
    (28.0, 62.0),
    (29.0, 50.0),
    (30.0, 40.0),
    (31.0, 30.0),
    (32.0, 22.0),
    (34.0, 12.0),
    (37.0, 6.0),
]

def youth_score_from_age(age):
    """Map a real age to a 0-100 youth score via the YOUTH_CURVE (piecewise
    linear, clamped at both ends). Returns None if age is missing."""
    if age is None:
        return None
    lo_age, lo_score = YOUTH_CURVE[0]
    hi_age, hi_score = YOUTH_CURVE[-1]
    if age <= lo_age:
        return lo_score
    if age >= hi_age:
        return hi_score
    for (a1, s1), (a2, s2) in zip(YOUTH_CURVE, YOUTH_CURVE[1:]):
        if a1 <= age <= a2:
            frac = (age - a1) / (a2 - a1)
            return round(s1 + frac * (s2 - s1), 1)
    return hi_score


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


# ============================================================
# VALUE OVER REPLACEMENT (VORP) -- makes production genuinely
# comparable ACROSS positions, using real facts about your league's
# roster construction (12 teams, real starter slots) rather than an
# invented cross-position multiplier.
# ============================================================
N_TEAMS = 12
DEDICATED_SLOTS = {"QB": 1, "RB": 2, "WR": 2, "TE": 1, "IDP": 1}  # per team, from real roster_positions
N_FLEX = 2          # FLEX slots per team (RB/WR/TE eligible)
N_SUPERFLEX = 1     # SUPER_FLEX slots per team (QB/RB/WR/TE eligible)

# How flex slots get credited toward each position's real league-wide
# starter demand. This IS a documented assumption (there's no way to know
# in advance exactly how often a flex slot goes to an RB vs a WR vs a QB2)
# -- shown here rather than hidden, and easy to adjust if your league's
# actual flex usage looks different. Default reflects common usage: FLEX
# mostly goes to RB/WR, SUPER_FLEX mostly goes to a second QB.
FLEX_ALLOCATION = {
    "FLEX": {"RB": 0.45, "WR": 0.45, "TE": 0.10},
    "SUPER_FLEX": {"QB": 0.70, "RB": 0.15, "WR": 0.15},
}


def compute_replacement_ranks():
    """How many players at each position are 'realistically startable'
    league-wide, given real team count and real roster slots."""
    slots = {pos: count * N_TEAMS for pos, count in DEDICATED_SLOTS.items()}
    for pos, frac in FLEX_ALLOCATION["FLEX"].items():
        slots[pos] = slots.get(pos, 0) + frac * N_FLEX * N_TEAMS
    for pos, frac in FLEX_ALLOCATION["SUPER_FLEX"].items():
        slots[pos] = slots.get(pos, 0) + frac * N_SUPERFLEX * N_TEAMS
    return {pos: max(1, round(v)) for pos, v in slots.items()}


def compute_vorp(board):
    """
    Each player's production expressed as points above his position's real
    replacement level, instead of a percentile within his position. This is
    what makes the final score genuinely comparable ACROSS positions (a QB
    and a TE can be honestly compared) while still reflecting the true,
    structural scarcity of each position in YOUR league -- not an opinion.
    Returns {player_id: vorp_or_None}.
    """
    ranks = compute_replacement_ranks()
    by_group = {}
    for r in board:
        grp = position_group(r["position"])
        wv = to_float(r.get("weighted_value"))
        if wv is not None:
            by_group.setdefault(grp, []).append(wv)

    replacement_level = {}
    for grp, vals in by_group.items():
        vals_sorted = sorted(vals, reverse=True)
        n = ranks.get(grp, 12)
        idx = min(max(n, 1), len(vals_sorted)) - 1
        replacement_level[grp] = vals_sorted[idx] if vals_sorted else 0.0

    out = {}
    for r in board:
        wv = to_float(r.get("weighted_value"))
        if wv is None:
            out[r["player_id"]] = None
        else:
            grp = position_group(r["position"])
            out[r["player_id"]] = round(wv - replacement_level.get(grp, 0.0), 2)
    return out, replacement_level, ranks


def compute_weekly_consistency():
    """
    Coefficient of variation (stdev / mean) of a player's weekly ACTUAL
    Fairfield points, across all weeks found in the saved league history
    (script 03's matchups.json files). Using stdev/mean instead of raw
    stdev makes this fairly comparable ACROSS positions -- a QB who scores
    25 +/- 5 and a TE who scores 8 +/- 1.6 have the same relative
    consistency (20%), even though their raw point swings are very
    different sizes. Lower CoV = more consistent.

    Returns RAW cv here -- the small-sample confidence discount is applied
    later in main(), using years_of_data (the same signal already used for
    the production discount) rather than raw week count. A rookie's one
    season can easily span 16+ weeks, which would wrongly look like "full
    trust" by a week-count threshold -- years_of_data correctly still flags
    that as one season of unproven evidence.

    Returns {player_id: cv_or_None}.
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
        if len(pts_list) >= 4:
            mean = statistics.mean(pts_list)
            stdev = statistics.stdev(pts_list)
            out[pid] = round(stdev / mean, 3) if mean > 0.5 else None
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

    # Compute the same dynamic season window used by 02/06, so the season
    # column names checked below (gp_2025, gp_2024, etc.) and the nflverse
    # context lookup stay correct as seasons roll forward -- avoids the
    # exact hardcoded-year bug that bit the durability calc before this fix.
    with open(DATA_DIR / "league_info.json", "r", encoding="utf-8") as _f:
        _current_season = int(json.load(_f)["season"])
    SEASONS_DESC = [str(_current_season), str(_current_season - 1), str(_current_season - 2)]
    print(f"  season window: {SEASONS_DESC}")

    print("Loading combined value board (full league-wide production pool)...")
    full_pool = load_csv(DATA_DIR / "value_board_combined.csv")
    n_rostered = sum(1 for r in full_pool if r.get("fairfield_team"))
    print(f"  {len(full_pool)} players in the full pool ({n_rostered} currently on a Fairfield roster)")

    # Compute Value Over Replacement across the FULL pool, before filtering
    # down to just your roster -- the replacement level (waiver-wire floor)
    # at each position needs the wide pool to be accurate. See compute_vorp
    # for the full explanation.
    print("Computing replacement levels (Value Over Replacement) from the full pool...")
    vorp_by_pid, replacement_level, replacement_ranks = compute_vorp(full_pool)
    print(f"  replacement ranks used: {replacement_ranks}")
    print(f"  replacement level (PPG) by position: { {k: round(v, 1) for k, v in replacement_level.items()} }")

    # Now narrow down to what actually gets displayed: players currently
    # rostered by a Fairfield team. Everything below only touches this
    # smaller set -- the wide pool has done its job (setting an honest
    # replacement level) and isn't needed again.
    board = [r for r in full_pool if r.get("fairfield_team")]
    print(f"Narrowed to {len(board)} currently-rostered players for display.")

    print("Loading nflverse player context...")
    player_ctx_rows = load_csv(NFLVERSE_DIR / "player_context_by_season.csv")
    # name -> {season -> row}, so we can prefer the most recent season with data
    player_ctx_by_name = {}
    for row in player_ctx_rows:
        key = normalize_name(row["player_name"])
        player_ctx_by_name.setdefault(key, {})[row["season"]] = row

    print("Loading nflverse team context...")
    team_ctx_rows = load_csv(NFLVERSE_DIR / "team_context_by_season.csv")
    latest_team_season = max((r["season"] for r in team_ctx_rows), default=None)
    team_ctx_latest = {row["team"]: row for row in team_ctx_rows if row["season"] == latest_team_season}
    print(f"  using {latest_team_season} team context (most recent season available)")

    print("Loading nflverse player bio (age, draft info)...")
    bio_rows = load_csv(NFLVERSE_DIR / "players_bio.csv")
    bio_by_name = {normalize_name(r["display_name"]): r for r in bio_rows if r.get("display_name")}

    print("Computing weekly consistency from real league history...")
    consistency_by_pid = compute_weekly_consistency()

    # Same confidence philosophy as the production discount, applied to
    # consistency -- but MORE conservative for thin samples than production
    # is. This is a real statistical distinction, not an arbitrary choice:
    # a variance-based statistic (like CV) is inherently noisier to estimate
    # from a small sample than a simple average is, so 1 season of history
    # should earn less trust here than it does for raw production.
    CV_CONFIDENCE = {1: 0.40, 2: 0.75, 3: 1.00}
    _raw_cvs = [v for v in consistency_by_pid.values() if v is not None]
    pool_mean_cv = statistics.mean(_raw_cvs) if _raw_cvs else 1.0
    print(f"  pool-wide average CV (used as the shrinkage anchor): {pool_mean_cv:.3f}")

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
        for season in SEASONS_DESC:
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
        team_row = team_ctx_latest.get(row.get("nfl_team", ""))
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
        gp_vals = [to_float(row.get(f"gp_{s}")) for s in SEASONS_DESC]
        gp_vals = [g for g in gp_vals if g is not None and g > 0]
        row["avg_games_played"] = round(sum(gp_vals) / len(gp_vals), 1) if gp_vals else ""

        # --- consistency (coefficient of variation, scale-independent) ---
        # Small-sample discount uses YEARS OF DATA (years_of_data, already
        # computed for the production discount) rather than raw week count.
        # A rookie's single season can span 16+ weeks, which would wrongly
        # look like "enough evidence" by a week-count threshold -- but it's
        # still only one season of proof, exactly as unproven as his
        # one-year production number was before that discount existed.
        raw_cv = consistency_by_pid.get(row["player_id"])
        n_years_cv = int(row.get("years_of_data") or 0)
        if raw_cv is not None:
            cv_confidence = CV_CONFIDENCE.get(n_years_cv, 1.00)
            blended_cv = pool_mean_cv + (raw_cv - pool_mean_cv) * cv_confidence
            row["weekly_consistency_cv"] = round(blended_cv, 3)
        else:
            row["weekly_consistency_cv"] = ""

    # ------------------------------------------------------------
    # Composite dynasty_score -- ONE cross-position-comparable score, built
    # from real, honest inputs:
    #   - production: VALUE OVER REPLACEMENT (see compute_vorp) -- points
    #     above the real replacement level at that position in YOUR league,
    #     then normalized globally so a QB, RB, TE, and IDP are genuinely
    #     comparable on the same scale (not four separate percentile scales).
    #   - age: the absolute YOUTH_CURVE (already cross-position by design)
    #   - durability: games played, normalized globally (already a fair
    #     cross-position unit -- 15 of 17 games means the same thing at
    #     any position)
    #   - consistency: coefficient of variation, normalized globally (scale-
    #     independent, so a high-scoring QB and a low-scoring TE with the
    #     same RELATIVE week-to-week swing score the same)
    # This means the exact same number appears whether you're looking at
    # the ALL view or filtered to one position -- there is only one score.
    # ------------------------------------------------------------
    print("Computing composite dynasty_score (Value Over Replacement, cross-position)...")

    prod_scores = min_max_normalize(vorp_by_pid)
    dur_scores = min_max_normalize({r["player_id"]: to_float(r.get("avg_games_played")) for r in board})
    con_scores = min_max_normalize({r["player_id"]: to_float(r.get("weekly_consistency_cv")) for r in board}, invert=True)
    youth_scores = {r["player_id"]: youth_score_from_age(to_float(r.get("age"))) for r in board}

    for row in board:
        pid = row["player_id"]
        row["vorp"] = vorp_by_pid.get(pid) if vorp_by_pid.get(pid) is not None else ""
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
