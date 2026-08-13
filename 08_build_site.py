"""
Fairfield Dynasty League -- Build Publishable Site
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01, 02, 03, 04, 06, 07, and 09 first -- this is the final step)

What this does:
  Turns data/value_board_FINAL.csv and data/pick_values.csv into a
  ready-to-publish website: a site/ folder containing index.html (the
  value board), trade.html (the trade builder), players_data.js, and
  picks_data.js. Point GitHub Pages at the site/ folder and this becomes
  the live, shareable link the whole league uses.

  This is the same site every league member has been using -- this script
  just automates the "turn today's data into a website" step so it can
  run unattended on a schedule instead of you rebuilding it by hand.

BEFORE RUNNING:
  Run 01, 02, 03, 04, 06, 07, and 09 first, in that order.
  Needs template.html AND trade_template.html to exist in the same
  folder as this script.
"""

import csv
import json
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
SITE_DIR = SCRIPT_DIR / "site"
TEMPLATE_PATH = SCRIPT_DIR / "template.html"
TRADE_TEMPLATE_PATH = SCRIPT_DIR / "trade_template.html"


def num(v):
    try:
        return round(float(v), 2)
    except (ValueError, TypeError):
        return None


def main():
    final_csv = DATA_DIR / "value_board_FINAL.csv"
    if not final_csv.exists():
        raise SystemExit(f"Missing {final_csv} -- run 07_build_final_value_board.py first.")
    if not TEMPLATE_PATH.exists():
        raise SystemExit(f"Missing {TEMPLATE_PATH} -- template.html must sit next to this script.")

    print("Reading final value board...")
    with open(final_csv, "r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))

    players = []
    for r in rows:
        players.append({
            "n": r["player_name"],
            "p": r["position"],
            "t": r["nfl_team"] or "FA",
            "ft": r["fairfield_team"],
            "prod": num(r["vorp"]),           # Value Over Replacement, not raw weighted_value --
                                                # this is what makes production cross-position fair.
            "age": num(r["age"]),
            "dur": num(r["avg_games_played"]),
            "con": num(r["weekly_consistency_cv"]),  # coefficient of variation, not raw stdev
            "affg": num(r["actual_fairfield_ppg"]),
            "tor": int(r["team_off_rank"]) if r["team_off_rank"] else None,
            # position-specific context (shown in the expanded card, not scored):
            "ts": num(r.get("target_share")),               # WR/TE
            "wopr": num(r.get("wopr")),                      # WR/TE
            "pyg": num(r.get("passing_yards_per_game")),     # QB
            "pepa": num(r.get("passing_epa_per_game")),      # QB
            "cpg": num(r.get("carries_per_game")),           # RB
            "ryg": num(r.get("rushing_yards_per_game")),     # RB
        })

    SITE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Writing players_data.js ({len(players)} players)...")
    data_js = "const PLAYERS = " + json.dumps(players, separators=(",", ":")) + ";"
    with open(SITE_DIR / "players_data.js", "w", encoding="utf-8") as f:
        f.write(data_js)

    print("Copying template.html -> site/index.html...")
    shutil.copy(TEMPLATE_PATH, SITE_DIR / "index.html")

    # ------------------------------------------------------------
    # Trade builder page (optional -- only built if the pick values
    # and trade template both exist, so this script still works fine
    # before the trade tool is added to a repo)
    # ------------------------------------------------------------
    pick_csv = DATA_DIR / "pick_values.csv"
    if pick_csv.exists() and TRADE_TEMPLATE_PATH.exists():
        print("Reading pick values...")
        with open(pick_csv, "r", encoding="utf-8", newline="") as f:
            pick_rows = list(csv.DictReader(f))

        picks = []
        for r in pick_rows:
            picks.append({
                "season": r["season"],
                "round": int(r["round"]),
                "label": r["label"],
                "value": num(r["value"]),
                "team": r["current_team"],      # who currently owns/controls this pick
                "orig": r["original_team"],     # whose real draft slot sets its value
                "basis": r["basis"],
                "yrs": int(r["years_out"]),
            })

        print(f"Writing picks_data.js ({len(picks)} picks)...")
        picks_js = "const PICKS = " + json.dumps(picks, separators=(",", ":")) + ";"
        with open(SITE_DIR / "picks_data.js", "w", encoding="utf-8") as f:
            f.write(picks_js)

        print("Copying trade_template.html -> site/trade.html...")
        shutil.copy(TRADE_TEMPLATE_PATH, SITE_DIR / "trade.html")
    else:
        print("Skipping trade builder page (pick_values.csv or trade_template.html not found yet).")

    print(f"\nDone. Site ready in {SITE_DIR}")
    print("If running locally, open site/index.html in a browser to preview.")
    print("In automation, this folder gets published directly to GitHub Pages.")


if __name__ == "__main__":
    main()
