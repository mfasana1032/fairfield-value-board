"""
Fairfield Dynasty League -- Build Publishable Site
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01, 02, 03, 04, 06, and 07 first -- this is the final step)

What this does:
  Turns data/value_board_FINAL.csv into a ready-to-publish website: a
  site/ folder containing index.html + players_data.js. Point GitHub
  Pages (or Netlify, or any static host) at the site/ folder and this
  becomes the live, shareable link the whole league uses.

  This is the same site every league member has been using -- this script
  just automates the "turn today's data into a website" step so it can
  run unattended on a schedule instead of you rebuilding it by hand.

BEFORE RUNNING:
  Run 01, 02, 03, 04, 06, and 07 first, in that order.
  Needs template.html to exist in the same folder as this script.
"""

import csv
import json
import shutil
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
SITE_DIR = SCRIPT_DIR / "site"
TEMPLATE_PATH = SCRIPT_DIR / "template.html"


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
            "ts": num(r["target_share"]),
            "tor": int(r["team_off_rank"]) if r["team_off_rank"] else None,
            "toe": num(r["team_off_epa_per_game"]),
        })

    SITE_DIR.mkdir(parents=True, exist_ok=True)

    print(f"Writing players_data.js ({len(players)} players)...")
    data_js = "const PLAYERS = " + json.dumps(players, separators=(",", ":")) + ";"
    with open(SITE_DIR / "players_data.js", "w", encoding="utf-8") as f:
        f.write(data_js)

    print("Copying template.html -> site/index.html...")
    shutil.copy(TEMPLATE_PATH, SITE_DIR / "index.html")

    print(f"\nDone. Site ready in {SITE_DIR}")
    print("If running locally, open site/index.html in a browser to preview.")
    print("In automation, this folder gets published directly to GitHub Pages.")


if __name__ == "__main__":
    main()
