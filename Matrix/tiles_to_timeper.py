"""
tiles_to_runs.py

Converts a tiles JSON (t, row, width) into a runs JSON (t, row, time_period).
Consecutive tiles with the same row are merged into one run.

Usage:
    python tiles_to_runs.py input.json output.json
"""

import json
import sys


def tiles_to_runs(tiles):
    if not tiles:
        return []

    runs = []
    run_row   = tiles[0]["row"]
    run_start = tiles[0]["t"]

    for i in range(1, len(tiles)):
        t   = tiles[i]["t"]
        row = tiles[i]["row"]

        if row != run_row:
            runs.append({
                "t":           round(run_start, 3),
                "row":         run_row,
                "time_period": round(t - run_start, 3)
            })
            run_row   = row
            run_start = t

    # close last run — estimate end time from average tile spacing
    avg = (tiles[-1]["t"] - tiles[0]["t"]) / max(len(tiles) - 1, 1)
    runs.append({
        "t":           round(run_start, 3),
        "row":         run_row,
        "time_period": round(tiles[-1]["t"] - run_start + avg, 3)
    })

    return runs


def main():
    if len(sys.argv) < 3:
        print("Usage: python tiles_to_runs.py input.json output.json")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        data = json.load(f)

    runs = tiles_to_runs(data["tiles"])

    result = {
        "format":  2,
        "comment": "t = start time (seconds). time_period = duration of this row being active.",
        "runs":    runs
    }

    with open(sys.argv[2], "w") as f:
        json.dump(result, f, indent=2)

    print(f"{len(data['tiles'])} tiles → {len(runs)} runs saved to {sys.argv[2]}")
    for r in runs[:6]:
        print(f"  t={r['t']:.2f}s  row={r['row']}  for {r['time_period']:.2f}s")
    if len(runs) > 6:
        print(f"  ... and {len(runs) - 6} more")


if __name__ == "__main__":
    main()