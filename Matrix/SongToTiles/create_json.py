"""
midi_to_tiles.py
Converts a MIDI file into a tile JSON for the game.

Usage:
    pip install mido
    python midi_to_tiles.py song.mid output.json

How it works:
- Reads all note-on events from the MIDI file
- Uses each note's real onset time (in seconds) as the tile's "t"
- Splits the full MIDI pitch range (0–127) into 6 equal buckets → row 0–5
- Width is fixed at 3 (you can tweak WIDTH below)
"""

import json
import sys
import mido



# ── Config ────────────────────────────────────────────────────────────────────
WIDTH = 3          # default tile width for every tile
MIDI_MIN = 0       # lowest possible MIDI pitch
MIDI_MAX = 127     # highest possible MIDI pitch
NUM_ROWS = 6       # rows in the game (0 – 5)
# ─────────────────────────────────────────────────────────────────────────────


def pitch_to_row(pitch: int) -> int:
    """Map a MIDI pitch (0–127) to a row index (0–5) using equal-width buckets."""
    bucket_size = (MIDI_MAX - MIDI_MIN + 1) / NUM_ROWS
    row = int((pitch - MIDI_MIN) / bucket_size)
    return min(row, NUM_ROWS - 1)   # clamp to 5


def midi_to_tiles(midi_path: str) -> list[dict]:
    mid = mido.MidiFile(midi_path)

    tiles = []
    tempo = 500_000  # default: 120 BPM (microseconds per beat)

    for track in mid.tracks:
        elapsed_ticks = 0
        current_tempo = tempo

        for msg in track:
            elapsed_ticks += msg.time

            if msg.type == "set_tempo":
                current_tempo = msg.tempo

            if msg.type == "note_on" and msg.velocity > 0:
                # Convert ticks → seconds
                seconds = mido.tick2second(
                    elapsed_ticks, mid.ticks_per_beat, current_tempo
                )
                row = pitch_to_row(msg.note)
                tiles.append({"t": round(seconds, 3), "row": row, "width": WIDTH})

    # Sort by time (multiple tracks can interleave)
    tiles.sort(key=lambda x: x["t"])
    return tiles


def build_json(tiles: list[dict]) -> dict:
    return {
        "format": 1,
        "comment": (
            "t = seconds from round start. "
            "row 0–5 mapped from MIDI pitch range split into 6 equal buckets."
        ),
        "tiles": tiles,
    }


def main():
    if len(sys.argv) < 3:
        print("Usage: python midi_to_tiles.py <input.mid> <output.json>")
        sys.exit(1)

    midi_path = sys.argv[1]
    output_path = sys.argv[2]

    print(f"Reading {midi_path} ...")
    tiles = midi_to_tiles(midi_path)
    print(f"Found {len(tiles)} notes")

    data = build_json(tiles)

    with open(output_path, "w") as f:
        json.dump(data, f, indent=2)

    print(f"Saved → {output_path}")


if __name__ == "__main__":
    main()