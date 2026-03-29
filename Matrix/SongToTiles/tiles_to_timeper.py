import json

# --- Setează aici path-ul fișierului de intrare și ieșire ---
input_path = "./Matrix/songs/song.json"
output_path = "./Matrix/songs/compressed_tiles.json"

# --- Citește JSON-ul original ---
with open(input_path, "r") as f:
    data = json.load(f)

tiles = data["tiles"]
compressed_tiles = []

# --- Pas 1: combinăm secvențele consecutive cu același row ---
i = 0
while i < len(tiles):
    current_row = tiles[i]["row"]
    start_t = tiles[i]["t"]

    j = i + 1
    while j < len(tiles) and tiles[j]["row"] == current_row:
        j += 1

    # width calculat din t următor minus t curent
    if j < len(tiles):
        width = tiles[j]["t"] - start_t
    else:
        width = tiles[i]["width"]  # ultima secvență, păstrăm width original

    compressed_tiles.append({
        "t": start_t,
        "row": current_row,
        "width": width
    })

    i = j

# --- Pas 2: procesare width, t și reguli pentru width < 1 ---
processed_tiles = []
previous_t = 0
i = 0

while i < len(compressed_tiles):
    tile = compressed_tiles[i].copy()
    width = round(tile["width"])  # rotunjim width

    # Tile-uri cu width < 1
    if width < 1:
        small_group = []
        while i < len(compressed_tiles) and round(compressed_tiles[i]["width"]) < 1:
            small_group.append(compressed_tiles[i].copy())
            i += 1

        j = 0
        while j < len(small_group):
            group_t = previous_t
            count = min(2, len(small_group) - j)  # maxim 2 row-uri la acelasi timp
            for k in range(count):
                processed_tiles.append({
                    "t": group_t,
                    "row": small_group[j + k]["row"],
                    "width": 1
                })
            previous_t += 1
            j += count
        continue  # mergem la următoarea secvență

    # Tile-uri cu width >= 1
    tile["t"] = previous_t
    tile["width"] = width
    processed_tiles.append(tile)
    previous_t += width
    i += 1

# --- Salvare JSON final ---
processed_data = {
    "format": data.get("format", 1),
    "comment": data.get("comment", ""),
    "tiles": processed_tiles
}

with open(output_path, "w") as f:
    json.dump(processed_data, f, indent=2)

print(f"JSON final procesat și salvat în: {output_path}")