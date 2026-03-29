"""
song_to_tiles.py
================
Pipeline complet: MIDI  →  song.json  →  compressed_tiles.json  →  consecutive_tiles.json

Etape:
  1. freq_to_tiles          — MIDI → note (freq, dur) → tiles brute  (song.json)
  2. tiles_to_timeper       — comprimă tile-uri consecutive cu același row  (compressed_tiles.json)
  3. timeper_to_consecutive — recalculează t-urile folosind SCROLL_SPEED     (consecutive_tiles.json)

Editează DOAR blocul de configurare de mai jos, apoi rulează:
    python song_to_tiles.py
"""

import json
import os

# ══════════════════════════════════════════════════════════════════════════════
#  CONFIGURARE  –  editează aici
# ══════════════════════════════════════════════════════════════════════════════

# ── Fișiere ───────────────────────────────────────────────────────────────────
MIDI_FILE   = r"C:\Users\bmdma\ledhack\3-Grame-De-haz\Matrix\songs\minune.mid"

SONGS_DIR   = os.path.join(os.path.dirname(__file__), "..", "songs")
OUT_STAGE1  = os.path.join(SONGS_DIR, "song.json")               # ieșire etapa 1
OUT_STAGE2  = os.path.join(SONGS_DIR, "compressed_tiles.json")   # ieșire etapa 2
OUT_STAGE3  = os.path.join(SONGS_DIR, "consecutive_tiles.json")  # ieșire etapa 3 (fișier final)

# ── Parametri etapa 1: MIDI → tiles brute ─────────────────────────────────────
NOTES_START   = 0       # sari primele N note din MIDI (0 = de la început)
NOTES_END     = None    # oprește la nota N (None = până la sfârșit)
NUM_ROWS      = 6       # numărul de rânduri din joc (0 – NUM_ROWS-1)
MIN_WIDTH     = 2       # lățimea minimă a unui tile
MAX_WIDTH     = 8       # lățimea maximă a unui tile
MIN_GAP       = 0.05    # pauză minimă (secunde) între tile-uri consecutive

# ── Parametri etapa 3: recalculare t-uri consecutive ──────────────────────────
SCROLL_SPEED  = 5      # coloane/secundă  —  trebuie să fie același ca în Piano_Tiles_Game.py
GAP           = 0.5   # secunde de pauză între grupuri de tile-uri

# ══════════════════════════════════════════════════════════════════════════════


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 1 – freq_to_tiles
# ─────────────────────────────────────────────────────────────────────────────

def freq_to_tiles(midi_file, out_file,
                  notes_start, notes_end,
                  num_rows, min_width, max_width, min_gap):
    """Citește MIDI, extrage note (freq, dur), le convertește în tiles și salvează JSON."""
    import mido

    mid   = mido.MidiFile(midi_file)
    tempo = 500000
    NOTE_TO_FREQ = {n: round(440 * 2 ** ((n - 69) / 12)) for n in range(128)}

    notes  = []
    active = {}

    for track in mid.tracks:
        elapsed = 0
        for msg in track:
            elapsed += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "set_tempo":
                tempo = msg.tempo
            if msg.type == "note_on" and msg.velocity > 0:
                active[msg.note] = elapsed
            if msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                if msg.note in active:
                    duration = elapsed - active.pop(msg.note)
                    notes.append((NOTE_TO_FREQ[msg.note], round(duration, 3)))

    # Slice configurabil
    notes = notes[notes_start:notes_end]
    print(f"  [1] note extrase: {len(notes)}")

    if not notes:
        raise ValueError("Nicio notă extrasă – verifică NOTES_START / NOTES_END.")

    freqs   = [f for f, d in notes]
    durs    = [d for f, d in notes]
    min_f   = min(freqs);  max_f   = max(freqs)
    min_dur = min(durs);   max_dur = max(durs)

    def _freq_to_row(freq):
        if min_f == max_f:
            return 0
        bucket = (max_f - min_f) / num_rows
        return min(int((freq - min_f) / bucket), num_rows - 1)

    def _dur_to_width(dur):
        if min_dur == max_dur:
            return min_width
        ratio = (dur - min_dur) / (max_dur - min_dur)
        return max(min_width, min(max_width, round(min_width + ratio * (max_width - min_width))))

    tiles  = []
    cursor = 0.0
    for freq, dur in notes:
        tiles.append({"t": round(cursor, 3), "row": _freq_to_row(freq), "width": _dur_to_width(dur)})
        cursor += dur + min_gap

    result = {
        "format": 1,
        "comment": (
            f"t=secunde de la start. row 0-{num_rows-1} mapat din range frecventa. "
            "width proportional cu durata notei."
        ),
        "tiles": tiles,
    }

    os.makedirs(os.path.dirname(out_file), exist_ok=True)
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  [1] {len(tiles)} tiles salvate → {out_file}")
    return tiles


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 2 – tiles_to_timeper
# ─────────────────────────────────────────────────────────────────────────────

def tiles_to_timeper(in_file, out_file):
    """Comprimă tile-urile consecutive cu același row și normalizează width-urile."""
    with open(in_file) as f:
        data = json.load(f)

    tiles = data["tiles"]

    # Pas 1 – combinăm secvențele consecutive cu același row
    compressed = []
    i = 0
    while i < len(tiles):
        current_row = tiles[i]["row"]
        start_t     = tiles[i]["t"]
        j = i + 1
        while j < len(tiles) and tiles[j]["row"] == current_row:
            j += 1
        width = tiles[j]["t"] - start_t if j < len(tiles) else tiles[i]["width"]
        compressed.append({"t": start_t, "row": current_row, "width": width})
        i = j

    print(f"  [2] dupa comprimare: {len(compressed)} tile-uri")

    # Pas 2 – procesare width, t și reguli pentru width < 1
    processed   = []
    previous_t  = 0
    i = 0
    while i < len(compressed):
        tile  = compressed[i].copy()
        width = round(tile["width"])

        if width < 1:
            small_group = []
            while i < len(compressed) and round(compressed[i]["width"]) < 1:
                small_group.append(compressed[i].copy())
                i += 1
            j = 0
            while j < len(small_group):
                count = min(2, len(small_group) - j)
                for k in range(count):
                    processed.append({"t": previous_t, "row": small_group[j + k]["row"], "width": 1})
                previous_t += 1
                j += count
            continue

        tile["t"]     = previous_t
        tile["width"] = width
        processed.append(tile)
        previous_t += width
        i += 1

    result = {
        "format":  data.get("format", 1),
        "comment": data.get("comment", ""),
        "tiles":   processed,
    }
    with open(out_file, "w") as f:
        json.dump(result, f, indent=2)

    print(f"  [2] {len(processed)} tiles salvate → {out_file}")
    return processed


# ─────────────────────────────────────────────────────────────────────────────
# Etapa 3 – timeper_to_consecutive_tiles
# ─────────────────────────────────────────────────────────────────────────────

def timeper_to_consecutive_tiles(in_file, out_file, scroll_speed, gap):
    """Recalculează t-urile astfel încât tile-urile să apară consecutiv la scroll_speed."""
    from itertools import groupby

    with open(in_file, encoding="utf-8") as f:
        data = json.load(f)

    tiles = sorted(data["tiles"], key=lambda x: (x["t"], x["row"]))

    groups = [list(g) for _, g in groupby(tiles, key=lambda x: x["t"])]

    new_tiles = []
    current_t = 0.0
    for group in groups:
        for tile in group:
            new_tiles.append({"t": round(current_t, 4), "row": tile["row"], "width": tile["width"]})
        max_width  = max(tile["width"] for tile in group)
        current_t += max_width / scroll_speed + gap

    output = {
        "format":  1,
        "comment": f"t recalculat pentru tile-uri consecutive. SCROLL_SPEED={scroll_speed} GAP={gap}",
        "tiles":   new_tiles,
    }
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2)

    print(f"  [3] {len(new_tiles)} tiles salvate → {out_file}")
    print(f"  [3] durata totala: {round(current_t, 2)}s")
    return new_tiles


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print(f"MIDI:         {MIDI_FILE}")
    print(f"Note slice:   [{NOTES_START} : {NOTES_END}]")
    print(f"Rows:         {NUM_ROWS}   MinW={MIN_WIDTH}  MaxW={MAX_WIDTH}  Gap={MIN_GAP}s")
    print(f"Scroll speed: {SCROLL_SPEED} col/s   Group gap: {GAP}s")
    print("=" * 60)

    print("\nEtapa 1 – MIDI → tiles brute")
    freq_to_tiles(
        midi_file   = MIDI_FILE,
        out_file    = OUT_STAGE1,
        notes_start = NOTES_START,
        notes_end   = NOTES_END,
        num_rows    = NUM_ROWS,
        min_width   = MIN_WIDTH,
        max_width   = MAX_WIDTH,
        min_gap     = MIN_GAP,
    )

    print("\nEtapa 2 – tiles brute → compressed")
    tiles_to_timeper(
        in_file  = OUT_STAGE1,
        out_file = OUT_STAGE2,
    )

    print("\nEtapa 3 – compressed → consecutive")
    timeper_to_consecutive_tiles(
        in_file      = OUT_STAGE2,
        out_file     = OUT_STAGE3,
        scroll_speed = SCROLL_SPEED,
        gap          = GAP,
    )

    print(f"\nDone! Fisierul final: {OUT_STAGE3}")
