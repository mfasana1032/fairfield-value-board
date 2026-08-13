"""
Fairfield Dynasty League -- Combined Value Board
Run this from: C:\\Users\\micha\\OneDrive\\Python\\Rndom\\Fantasy Football
(run 01, 02, and 03 first -- this merges their outputs)

What this does:
  Combines two different, honest signals into one CSV per player:

  1. weighted_value -- real NFL production (2023-2025), recalculated
     under your CURRENT scoring settings. Normalized, apples-to-apples,
     answers "how good is this guy in the abstract, under today's rules."

  2. actual_fairfield_points / actual_fairfield_ppg -- Sleeper's own
     real, recorded fantasy scores from your league's actual history,
     under whatever scoring was live at the time (including old 2-IDP
     scoring in earlier seasons). Answers "what did this guy actually
     produce for a Fairfield manager, for real."

  These will NOT always agree, and that's useful information, not an
  error -- a player who scores high on #1 but low on #2 might be someone
  who was only recently added to a roster, or who benefited a lot from
  scoring that no longer exists (e.g., a 2-IDP-era linebacker).

BEFORE RUNNING:
  Run 01_fetch_league_data.py, then 02_build_value_board.py, then
  03_fetch_league_history.py, in that order.
"""

import csv
import json
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent / "data"


def load_json(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise SystemExit(f"Missing {filename} in {DATA_DIR}. Run the earlier scripts first.")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        raise SystemExit(f"Missing {filename} in {DATA_DIR}. Run 02_build_value_board.py first.")
    with open(path, "r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def main():
    print("Loading NFL-recomputed value board (script 02 output)...")
    nfl_rows = load_csv("value_board_2023_2025.csv")

    print("Loading real in-league history (script 03 output)...")
    actual_points = load_json("actual_points_by_player.json")

    print("Merging...")
    fieldnames = list(nfl_rows[0].keys()) if nfl_rows else []
    extra_fields = ["actual_fairfield_points", "actual_fairfield_ppg", "weeks_rostered_fairfield"]
    fieldnames += [f for f in extra_fields if f not in fieldnames]

    for row in nfl_rows:
        pid = row["player_id"]
        real = actual_points.get(pid)
        if real:
            weeks = real.get("weeks_rostered", 0)
            total = real.get("total_points", 0.0)
            row["actual_fairfield_points"] = total
            row["actual_fairfield_ppg"] = round(total / weeks, 2) if weeks else ""
            row["weeks_rostered_fairfield"] = weeks
        else:
            row["actual_fairfield_points"] = ""
            row["actual_fairfield_ppg"] = ""
            row["weeks_rostered_fairfield"] = 0

    # Sort by the NFL-recomputed weighted value by default -- change the key
    # below to "actual_fairfield_ppg" if you'd rather sort by real in-league history.
    def sort_key(r):
        v = r.get("weighted_value")
        try:
            return float(v)
        except (TypeError, ValueError):
            return -9999

    nfl_rows.sort(key=sort_key, reverse=True)

    out_path = DATA_DIR / "value_board_combined.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(nfl_rows)

    matched = sum(1 for r in nfl_rows if r["actual_fairfield_points"] != "")
    print(f"\nSaved {out_path}")
    print(f"{matched} of {len(nfl_rows)} rostered players had real in-league history found.")
    print("Players with no in-league history are likely recent waiver adds or trade acquisitions")
    print("who haven't actually played a game on a Fairfield roster yet.")


if __name__ == "__main__":
    main()