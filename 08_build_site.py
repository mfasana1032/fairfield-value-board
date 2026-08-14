"""
Fairfield Dynasty League -- Build Publishable Site
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01, 02, 03, 04, 06, 07, and 09 first -- this is the final step)

What this does:
  Turns data/value_board_FINAL.csv and data/pick_values.csv into a
  ready-to-publish website: a site/ folder containing index.html (value
  board + trade builder, toggled with a tab -- one page, no navigation
  between them), players_data.js, and picks_data.js. Point GitHub Pages
  at the site/ folder and this becomes the live, shareable link the
  whole league uses.

  This is the same site every league member has been using -- this script
  just automates the "turn today's data into a website" step so it can
  run unattended on a schedule instead of you rebuilding it by hand.

BEFORE RUNNING:
  Run 01, 02, 03, 04, 06, 07, and 09 first, in that order.
  Needs template.html to exist in the same folder as this script.
"""

import csv
import json
from datetime import datetime, timezone
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

    # Clean up stale files from earlier versions of this pipeline that this
    # script no longer produces (e.g. the old separate trade.html, before
    # the trade builder was merged into index.html as a tab). Without this,
    # an old file can keep sitting live on the server forever, since Pages
    # just serves whatever's already there -- this script only ever ADDED
    # files before, never removed ones it stopped generating.
    stale_files = ["trade.html"]
    for name in stale_files:
        stale_path = SITE_DIR / name
        if stale_path.exists():
            stale_path.unlink()
            print(f"Removed stale {name} (no longer used -- merged into index.html).")

    print(f"Writing players_data.js ({len(players)} players)...")
    data_js = "const PLAYERS = " + json.dumps(players, separators=(",", ":")) + ";"
    with open(SITE_DIR / "players_data.js", "w", encoding="utf-8") as f:
        f.write(data_js)

    # ------------------------------------------------------------
    # Copy the template, but tag the data script references with a
    # version string unique to THIS run. Browsers cache a file like
    # "picks_data.js" aggressively and can keep reusing an old copy
    # even after the real one on the server changes -- happened for
    # real during testing. Requesting "picks_data.js?v=<timestamp>"
    # instead means every weekly deploy is a genuinely new URL as far
    # as the browser is concerned, so there's no stale copy to ever
    # accidentally serve. No manual cache-clearing ever needed again.
    # ------------------------------------------------------------
    version_tag = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    print(f"Copying template.html -> site/index.html (cache-busted as v={version_tag})...")
    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        html = f.read()
    html = html.replace('src="players_data.js"', f'src="players_data.js?v={version_tag}"')
    html = html.replace('src="picks_data.js"', f'src="picks_data.js?v={version_tag}"')
    with open(SITE_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html)

    # ------------------------------------------------------------
    # Pick values (optional -- the trade builder tab just shows an
    # empty pick list if this isn't available yet; nothing breaks)
    # ------------------------------------------------------------
    pick_csv = DATA_DIR / "pick_values.csv"
    if pick_csv.exists():
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
    else:
        print("No pick_values.csv found yet -- trade builder's pick picker will be empty "
              "until 09_build_pick_values.py has been run.")
        with open(SITE_DIR / "picks_data.js", "w", encoding="utf-8") as f:
            f.write("const PICKS = [];")

    print(f"\nDone. Site ready in {SITE_DIR}")
    print("If running locally, open site/index.html in a browser to preview.")
    print("In automation, this folder gets published directly to GitHub Pages.")


if __name__ == "__main__":
    main()
