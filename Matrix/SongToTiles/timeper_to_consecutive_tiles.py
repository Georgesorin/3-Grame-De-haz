import json
import os

SCROLL_SPEED = 7 # coloane/secundă — trebuie să fie același ca în Piano_Tiles_Game.py
GAP = 0.3         # secunde de pauză între grupuri de tile-uri

INPUT_FILE  = os.path.join(os.path.dirname(__file__), "..", "songs", "compressed_tiles.json")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "songs", "consecutive_tiles.json")

with open(INPUT_FILE, encoding="utf-8") as f:
    data = json.load(f)

tiles = data["tiles"]

# Sortează după t original, apoi după row (pentru tile-uri cu același t)
tiles.sort(key=lambda x: (x["t"], x["row"]))

# Grupează tile-urile care au același t original (apar simultan)
from itertools import groupby

groups = []
for t_orig, group in groupby(tiles, key=lambda x: x["t"]):
    groups.append(list(group))

# Recalculează t-urile: fiecare grup apare imediat după ce ultimul tile din grupul precedent
# a plecat de la spawn (x=BOARD_WIDTH), adică t_nou = t_prev + max_width_prev / SCROLL_SPEED
new_tiles = []
current_t = 0.0

for i, group in enumerate(groups):
    for tile in group:
        new_tiles.append({
            "t": round(current_t, 4),
            "row": tile["row"],
            "width": tile["width"]
        })
    # Avansează t cu lățimea maximă din grup (tile-ul cel mai lat dictează când "se eliberează" spațiul)
    max_width = max(tile["width"] for tile in group)
    current_t += max_width / SCROLL_SPEED + GAP

output = {
    "format": 1,
    "comment": "t recalculat pentru tile-uri consecutive cu gap. SCROLL_SPEED=" + str(SCROLL_SPEED) + " GAP=" + str(GAP),
    "tiles": new_tiles
}

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
    json.dump(output, f, indent=2)

print(f"Generat {len(new_tiles)} tile-uri in '{OUTPUT_FILE}'")
print(f"Durata totala: {round(current_t, 2)}s")
