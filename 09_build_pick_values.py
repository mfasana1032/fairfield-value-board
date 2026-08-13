"""
Fairfield Dynasty League -- Draft Pick Values
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01_fetch_league_data.py first -- this reads files it already saved)

WHAT THIS PRODUCES:
  data/pick_values.csv -- one row per real, currently-owned draft pick
  across your league (this year through 3 years out), each with:
    - who currently owns it (after accounting for past trades)
    - which team's original pick it is
    - a real basis for its value (see tiers below)
    - a value score, on roughly the same 0-100 scale as player dynasty
      scores, so picks and players can be summed in a trade

HOW EACH PICK GETS ITS VALUE -- HONEST TIERS, NOT ONE FORMULA FOR EVERYTHING:

  TIER 1 -- This year's draft, order already locked (real fact):
    Sleeper's draft object has a real draft_order once your league sets
    it (which happens right after the championship game, before the
    draft event itself). If it's set, this script uses the EXACT real
    slot -- not a projection.

  TIER 2 -- Next year's draft, season already underway (real standings):
    Once real games have been played this season, this uses ACTUAL
    current standings (worst record = earlier projected pick -- the
    common default; adjust WORST_RECORD_PICKS_FIRST below once your
    league formally locks its real mechanism, since that survey item
    isn't decided yet). Labeled "projected" since the season isn't over.

  TIER 3 -- Next year's draft, season hasn't started yet:
    No real standings exist -- generic round value, no team attached,
    labeled "standing TBD."

  TIER 4 -- Two or more years out:
    ALWAYS generic, never team-adjusted. Dynasty rosters fully turn over
    in that time, so pretending to know a team's future standing that
    far out would be fabrication, not analysis.

  ALL TIERS: the value itself comes from a documented, adjustable curve
  (PICK_VALUE_CURVE below) built to match the real, well-established
  shape every dynasty analyst agrees on (steep drop through round 1,
  lower flatter round 2, low round 3+, future years discounted) --
  NOT copied from any specific site's proprietary numbers, since no
  clean public numeric table exists to honestly cite. Adjust freely.
  Every pick's value can also be manually overridden in the trade tool
  itself -- this script just sets a reasonable, transparent default.

BEFORE RUNNING:
  Run 01_fetch_league_data.py first.
"""

import csv
import json
import math
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"

N_TEAMS = 12
N_ROUNDS = 4  # matches your league's rookie draft rounds -- adjust if this changes
YEARS_OUT_TRACKED = 3  # this year + 2 future years

# Whether worse records pick earlier next year (the common default).
# Flip if your league formally locks a different mechanism.
WORST_RECORD_PICKS_FIRST = True

# ============================================================
# PICK VALUE CURVE -- documented, adjustable
# ============================================================
# Anchor points, hand-picked to match the real shape every dynasty
# source agrees on: pick 1.01 is valuable but still below a PROVEN
# elite player (consistent with the same "unproven sample" discount
# philosophy used for rookie production elsewhere in this pipeline);
# value drops steeply through round 1, more gently after.
PICK_1_01_VALUE = 58.0      # best pick in the draft
ROUND_2_START_VALUE = 22.0  # first pick of round 2
FLOOR_VALUE = 4.0           # last pick of the draft floor

# Future-year discount: a pick further out is worth less than the same
# slot THIS year (uncertainty + delayed payoff -- a real, standard
# dynasty principle, not invented). Applied per additional year out.
FUTURE_YEAR_DISCOUNT = 0.85


def pick_curve_value(overall_pick_no, total_picks):
    """
    Smooth exponential decay from PICK_1_01_VALUE down toward FLOOR_VALUE,
    passing near ROUND_2_START_VALUE at the start of round 2. Formula-based
    so every slot has a defensible, non-arbitrary value relative to its
    neighbors, not hand-typed per pick.
    """
    if overall_pick_no <= 1:
        return PICK_1_01_VALUE
    r2_start_pick = N_TEAMS + 1  # first pick of round 2
    if overall_pick_no <= r2_start_pick:
        # decay from pick 1 to end of round 1, hitting ~ROUND_2_START_VALUE by r2_start_pick
        decay = math.log(PICK_1_01_VALUE / ROUND_2_START_VALUE) / (r2_start_pick - 1)
        return round(PICK_1_01_VALUE * math.exp(-decay * (overall_pick_no - 1)), 1)
    else:
        # gentler decay from round 2 start down to the floor at the last pick
        remaining = total_picks - r2_start_pick
        decay = math.log(ROUND_2_START_VALUE / FLOOR_VALUE) / max(remaining, 1)
        return round(ROUND_2_START_VALUE * math.exp(-decay * (overall_pick_no - r2_start_pick)), 1)


def generic_round_value(round_no, total_picks):
    """Average value across a round, used when we don't know the real slot."""
    start = (round_no - 1) * N_TEAMS + 1
    end = round_no * N_TEAMS
    vals = [pick_curve_value(p, total_picks) for p in range(start, end + 1)]
    return round(sum(vals) / len(vals), 1)


def load_json(name):
    with open(DATA_DIR / name, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    league = load_json("league_info.json")
    rosters = load_json("rosters.json")
    users = load_json("users.json")
    traded_picks = load_json("traded_picks.json")
    drafts = load_json("drafts.json")

    current_season = int(league["season"])
    total_picks = N_TEAMS * N_ROUNDS

    user_by_id = {u["user_id"]: u for u in users}
    team_name_by_owner = {
        u["user_id"]: (u.get("display_name") or u.get("username") or u["user_id"])
        for u in users
    }
    roster_by_id = {r["roster_id"]: r for r in rosters}
    owner_by_roster = {r["roster_id"]: r.get("owner_id") for r in rosters}

    # ------------------------------------------------------------
    # Has the season actually started? Check both the league status AND
    # whether any real games have been played -- belt and suspenders,
    # since a status string alone could be stale or ambiguous.
    # ------------------------------------------------------------
    status = league.get("status", "")
    any_games_played = any(
        (r.get("settings", {}).get("wins", 0) +
         r.get("settings", {}).get("losses", 0) +
         r.get("settings", {}).get("ties", 0)) > 0
        for r in rosters
    )
    season_started = status not in ("pre_draft", "drafting") and any_games_played
    print(f"League status: '{status}' | any games played: {any_games_played} "
          f"-> season_started = {season_started}")

    # ------------------------------------------------------------
    # TIER 1: this year's draft order, if it's already locked
    # ------------------------------------------------------------
    this_year_draft = None
    for d in drafts:
        if str(d.get("season")) == str(current_season):
            this_year_draft = d
            break
    draft_order = (this_year_draft or {}).get("draft_order") or {}
    this_year_order_locked = bool(draft_order)
    print(f"This year's ({current_season}) draft order locked: {this_year_order_locked}")

    # ------------------------------------------------------------
    # TIER 2 basis: current standings (only meaningful if season started)
    # ------------------------------------------------------------
    def win_pct(r):
        s = r.get("settings", {})
        g = s.get("wins", 0) + s.get("losses", 0) + s.get("ties", 0)
        if g == 0:
            return 0.5
        return (s.get("wins", 0) + 0.5 * s.get("ties", 0)) / g

    standings_order = sorted(rosters, key=win_pct, reverse=not WORST_RECORD_PICKS_FIRST)
    # standings_order[0] picks 1st next year if WORST_RECORD_PICKS_FIRST
    projected_slot_by_roster = {
        r["roster_id"]: i + 1 for i, r in enumerate(standings_order)
    }

    # ------------------------------------------------------------
    # Figure out current ownership of every real pick across tracked years,
    # accounting for past trades (traded_picks.json).
    # ------------------------------------------------------------
    # Default: every team owns its own original picks every tracked year/round
    pick_owner = {}  # (season, round, original_roster_id) -> current_roster_id
    for season_offset in range(YEARS_OUT_TRACKED):
        season = current_season + season_offset
        for rnd in range(1, N_ROUNDS + 1):
            for r in rosters:
                pick_owner[(season, rnd, r["roster_id"])] = r["roster_id"]

    for tp in traded_picks:
        key = (int(tp["season"]), tp["round"], tp["roster_id"])
        if key in pick_owner:
            pick_owner[key] = tp["owner_id"]

    # ------------------------------------------------------------
    # Build the output: one row per real, currently-tracked pick
    # ------------------------------------------------------------
    rows = []
    for season_offset in range(YEARS_OUT_TRACKED):
        season = current_season + season_offset
        years_out = season_offset  # 0 = this year

        for rnd in range(1, N_ROUNDS + 1):
            for r in rosters:
                orig_roster_id = r["roster_id"]
                orig_owner_id = owner_by_roster[orig_roster_id]
                orig_team = team_name_by_owner.get(orig_owner_id, f"Roster {orig_roster_id}")

                current_roster_id = pick_owner[(season, rnd, orig_roster_id)]
                current_owner_id = owner_by_roster.get(current_roster_id)
                current_team = team_name_by_owner.get(current_owner_id, f"Roster {current_roster_id}")

                # Determine value + basis based on tier
                if years_out == 0 and this_year_order_locked:
                    slot = draft_order.get(orig_owner_id)
                    if slot:
                        overall = (rnd - 1) * N_TEAMS + slot
                        value = pick_curve_value(overall, total_picks)
                        basis = "real_draft_order"
                        label = f"{season} Round {rnd}, Pick {slot} ({orig_team}'s)"
                    else:
                        value = generic_round_value(rnd, total_picks)
                        basis = "generic_missing_slot"
                        label = f"{season} Round {rnd} ({orig_team}'s)"
                elif years_out == 0 or (years_out == 1 and season_started):
                    slot = projected_slot_by_roster.get(orig_roster_id)
                    overall = (rnd - 1) * N_TEAMS + slot
                    value = pick_curve_value(overall, total_picks)
                    basis = "projected_current_standing"
                    label = f"{season} Round {rnd}, proj. pick {slot} ({orig_team}'s)"
                else:
                    value = generic_round_value(rnd, total_picks)
                    basis = "generic_standing_tbd" if years_out <= 1 else "generic_future"
                    label = f"{season} Round {rnd} ({orig_team}'s)"

                # Future-year discount (applies on top of the base value)
                value = round(value * (FUTURE_YEAR_DISCOUNT ** years_out), 1)

                rows.append({
                    "season": season,
                    "round": rnd,
                    "original_team": orig_team,
                    "current_team": current_team,
                    "label": label,
                    "value": value,
                    "basis": basis,
                    "years_out": years_out,
                })

    out_path = DATA_DIR / "pick_values.csv"
    fieldnames = ["season", "round", "original_team", "current_team", "label", "value", "basis", "years_out"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nSaved {out_path} -- {len(rows)} picks across {YEARS_OUT_TRACKED} tracked years.")
    basis_counts = {}
    for r in rows:
        basis_counts[r["basis"]] = basis_counts.get(r["basis"], 0) + 1
    print("Value basis breakdown:", basis_counts)


if __name__ == "__main__":
    main()