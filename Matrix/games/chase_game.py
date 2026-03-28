"""
Chase Game - Pac-Man-style survival on water with islands.
Complet separat de GUI. Primeste un callback pentru frame si tile triggers.
"""

import random
import time
import math

# ── Board dimensions (trebuie sa coincida cu Controller) ──────────────────────
BOARD_WIDTH  = 16
BOARD_HEIGHT = 32

# ── Palette ───────────────────────────────────────────────────────────────────
CHASE_WATER          = (5,   42,  95)
CHASE_SHOAL          = (35,  105, 125)
CHASE_ISLAND_COAST   = (130, 168, 88)
CHASE_ISLAND_MID     = (52,  128, 62)
CHASE_ISLAND_INLAND  = (28,  88,  48)
CHASE_TREASURE       = (255, 200, 55)
CHASE_PLAYER         = (0,   245, 220)
CHASE_PLAYER_SHIELD  = (70,  190, 255)
CHASE_ENEMY_HEAD     = (255, 50,  50)
CHASE_ENEMY_BODY     = (180, 20,  30)
CHASE_PU_FREEZE      = (170, 230, 255)
CHASE_PU_SLOW        = (255, 140, 60)
CHASE_PU_SHIELD      = (255, 255, 140)
BLACK                = (0,   0,   0)


class ChaseGame:
    """
    Logica completa a jocului Chase, independenta de orice GUI/tkinter.

    Utilizare:
        game = ChaseGame(num_players=2)
        game.start()

        # in loop-ul de trimitere:
        frame = game.get_frame(time_counter)   # dict {(x,y): (r,g,b)}

        # cand un tile e apasat (din receiver_loop):
        game.on_tile_pressed(x, y, player_id=0)

        # starea pentru al doilea ecran:
        info = game.get_hud_info()
    """

    def __init__(self, num_players: int = 1, on_game_event=None,
                 difficulty_params: dict = None):
        """
        num_players      : 1–4 jucatori
        on_game_event    : callable(event_name, data)
        difficulty_params: dict cu 'base_period', 'lives', 'snakes_bonus'
        """
        self.num_players   = max(1, min(4, num_players))
        self.on_game_event = on_game_event or (lambda e, d: None)

        dp = difficulty_params or {}
        self._base_period   = dp.get("base_period", 0.055)
        self._start_lives   = dp.get("lives", 3)
        self._snakes_bonus  = dp.get("snakes_bonus", 0)

        self._running = False
        self._start_time = 0.0
        self._reset_state(full_restart=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        self._running    = True
        self._start_time = time.time()
        self._reset_state(full_restart=True)

    def stop(self):
        self._running = False

    def is_running(self) -> bool:
        return self._running

    def on_tile_pressed(self, x: int, y: int, player_id: int = 0):
        """Apelat din receiver_loop cand un tile fizic e apasat."""
        if not self._running or player_id >= self.num_players:
            return
        # Miscam jucatorul spre tile-ul apasat (un pas in directia corecta)
        px, py = self._players[player_id]["pos"]
        dx = (1 if x > px else -1 if x < px else 0)
        dy = (1 if y > py else -1 if y < py else 0)
        # Mutam doar pe o axa odata (prioritate X)
        if dx != 0:
            self._try_move_player(player_id, dx, 0)
        elif dy != 0:
            self._try_move_player(player_id, 0, dy)

    def on_key_direction(self, player_id: int, dx: int, dy: int):
        """Apelat din tastatura (Chase Mode cu sageti)."""
        if not self._running or player_id >= self.num_players:
            return
        if self._players[player_id]["move_cooldown"] > 0:
            self._players[player_id]["move_cooldown"] -= 1
            return
        self._try_move_player(player_id, dx, dy)
        level = self._level
        self._players[player_id]["move_cooldown"] = max(1, 3 - min(2, level // 4))

    def get_frame(self, time_counter: int) -> dict:
        """
        Ruleaza un tick de logica si returneaza frame-ul curent.
        Apelat din sending_loop (~20fps).
        """
        if not self._running:
            return {(x, y): BLACK for y in range(BOARD_HEIGHT) for x in range(BOARD_WIDTH)}

        now = time.time()
        self._tick(now)
        return self._build_frame(now, time_counter)

    def get_hud_info(self) -> dict:
        """
        Date pentru al doilea monitor.
        Returneaza un dict cu tot ce ai nevoie sa afisezi.
        """
        players_info = []
        for i, p in enumerate(self._players):
            players_info.append({
                "id":      i,
                "lives":   p["lives"],
                "shields": p["shields"],
                "score":   p["score"],
                "pos":     p["pos"],
            })

        frozen = time.time() < self._freeze_until
        slowed = time.time() < self._slow_until

        return {
            "level":       self._level,
            "wave_gems":   self._wave_gems,
            "wave_need":   self._wave_need,
            "hud_msg":     self._hud_msg,
            "players":     players_info,
            "frozen":      frozen,
            "slowed":      slowed,
            "game_over":   not self._running,
            "treasures":   len(self._treasures),
            "elapsed":     time.time() - self._start_time,
            "num_snakes":  len(self._snakes),
            "difficulty":  self._difficulty_label,
        }

    # ── Internal: island helpers ───────────────────────────────────────────────

    def _water_cells(self):
        all_c = {(x, y) for y in range(BOARD_HEIGHT) for x in range(BOARD_WIDTH)}
        return all_c - self._islands

    def _rebuild_shoal(self):
        self._shoal_cells.clear()
        for ix, iy in self._islands:
            for dx, dy in ((0,1),(0,-1),(1,0),(-1,0)):
                nx, ny = ix+dx, iy+dy
                if 0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT and (nx,ny) not in self._islands:
                    self._shoal_cells.add((nx, ny))

    def _island_pixel_color(self, x, y):
        touches_water  = False
        island_neighbors = 0
        for dx, dy in ((0,1),(0,-1),(1,0),(-1,0)):
            nx, ny = x+dx, y+dy
            if not (0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT):
                touches_water = True
                continue
            if (nx, ny) in self._islands:
                island_neighbors += 1
            else:
                touches_water = True
        if touches_water:
            return CHASE_ISLAND_COAST
        if island_neighbors >= 3:
            return CHASE_ISLAND_INLAND
        return CHASE_ISLAND_MID

    def _random_islands(self, num_blobs, min_cells, max_cells):
        self._islands.clear()
        water = {(x,y) for y in range(BOARD_HEIGHT) for x in range(BOARD_WIDTH)}
        placed, attempts = 0, 0
        while placed < num_blobs and attempts < 200:
            attempts += 1
            cx, cy = random.randint(2, BOARD_WIDTH-3), random.randint(3, BOARD_HEIGHT-4)
            n = random.randint(min_cells, max_cells)
            blob = {(cx, cy)}
            frontier = [(cx, cy)]
            while len(blob) < n and frontier:
                bx, by = random.choice(frontier)
                for dx, dy in ((0,1),(0,-1),(1,0),(-1,0)):
                    nx, ny = bx+dx, by+dy
                    if 0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT and (nx,ny) not in blob:
                        if random.random() < 0.55:
                            blob.add((nx, ny))
                            frontier.append((nx, ny))
            if blob <= water:
                self._islands |= blob
                placed += 1
        self._rebuild_shoal()

    def _island_touch_count(self, x, y):
        return sum(
            1 for dx, dy in ((0,1),(0,-1),(1,0),(-1,0))
            if 0 <= x+dx < BOARD_WIDTH and 0 <= y+dy < BOARD_HEIGHT
            and (x+dx, y+dy) in self._islands
        )

    def _water_openness(self, x, y):
        return sum(
            1 for dx, dy in ((0,1),(0,-1),(1,0),(-1,0))
            if 0 <= x+dx < BOARD_WIDTH and 0 <= y+dy < BOARD_HEIGHT
            and (x+dx, y+dy) not in self._islands
        )

    def _snake_occupied(self):
        blocked = set()
        for sn in self._snakes:
            for c in sn["cells"][:-1]:
                blocked.add(c)
        return blocked

    def _random_jewel_cell(self):
        water   = self._water_cells()
        blocked = (self._snake_occupied()
                   | {p["pos"] for p in self._players}
                   | set(self._powerups.keys())
                   | self._treasures)
        deep = [c for c in water if c not in self._shoal_cells and c not in blocked]
        if len(deep) < 6:
            deep = [c for c in water if c not in blocked]
        return random.choice(deep) if deep else None

    def _random_empty_cell(self):
        water   = self._water_cells()
        blocked = (self._snake_occupied()
                   | {p["pos"] for p in self._players}
                   | self._treasures
                   | set(self._powerups.keys()))
        opts = [c for c in water if c not in blocked]
        return random.choice(opts) if opts else None

    # ── Internal: game state ───────────────────────────────────────────────────

    def _reset_state(self, full_restart=False):
        if full_restart:
            self._level    = 1
            self._wave_gems = 0
            self._difficulty_label = "Normal"
            self._players = [
                {"lives": self._start_lives, "shields": 0, "score": 0,
                 "pos": (0, 0), "move_cooldown": 0}
                for _ in range(self.num_players)
            ]

        self._islands      = set()
        self._shoal_cells  = set()
        self._sea_cells    = set()
        self._treasures    = set()
        self._powerups     = {}   # (x,y) -> 'freeze'|'slow'|'shield'
        self._snakes       = []
        self._freeze_until = 0.0
        self._slow_until   = 0.0
        self._hud_msg      = ""
        self._hud_until    = 0.0
        self._snake_step_at      = 0.0
        self._next_jewel_spawn   = 0.0
        self._treasure_cap = 7
        self._wave_need    = 8 + self._level * 2

        # Genereaza insula
        self._random_islands(
            num_blobs=random.randint(4, 7),
            min_cells=3, max_cells=7,
        )
        water = self._water_cells()
        if len(water) < 40:
            self._islands.clear()
            self._rebuild_shoal()
            water = self._water_cells()

        # Pozitioneaza jucatorii departe unii de altii
        water_list = sorted(water)
        random.shuffle(water_list)
        for i, p in enumerate(self._players):
            p["pos"] = water_list[i % len(water_list)]

        self._treasure_cap = max(6, min(11, 6 + self._level // 3))
        self._wave_need    = 8 + self._level * 2

        # Serpi
        snake_len  = max(3, 4 - min(1, (self._level - 1) // 3))
        num_snakes = min(5, 2 + self._level // 2 + self._snakes_bonus)
        occupied   = {p["pos"] for p in self._players}
        for _ in range(num_snakes):
            spawns = [
                c for c in water
                if c not in occupied
                and all(abs(c[0]-p["pos"][0]) + abs(c[1]-p["pos"][1]) > 10
                        for p in self._players)
            ]
            if not spawns:
                spawns = [c for c in water if c not in occupied]
            if not spawns:
                break
            head  = random.choice(spawns)
            cells = [head]
            cur   = head
            for _ in range(snake_len - 1):
                neigh = [(cur[0]+d[0], cur[1]+d[1]) for d in ((0,1),(0,-1),(1,0),(-1,0))]
                cand  = [p for p in neigh if p in water and p not in cells and p not in occupied]
                if not cand:
                    break
                nxt = random.choice(cand)
                cells.append(nxt)
                cur = nxt
            for c in cells:
                occupied.add(c)
            self._snakes.append({"cells": cells})

        # Comori initiale
        n_spawn = max(4, min(self._treasure_cap, 7))
        for _ in range(n_spawn):
            p = self._random_jewel_cell()
            if p:
                self._treasures.add(p)

        # Power-up-uri
        for ptype in ("freeze", "shield"):
            cell = self._random_empty_cell()
            if cell:
                self._powerups[cell] = ptype

        self._hud_msg   = "Colecteaza comorile!"
        self._hud_until = time.time() + 2.5
        self._next_jewel_spawn = time.time() + 0.7

    # ── Internal: per-tick logic ───────────────────────────────────────────────

    def _tick(self, now: float):
        self._step_snakes(now)
        self._check_pickups_and_hits(now)
        self._maintain_jewels(now)

    def _try_move_player(self, player_id: int, dx: int, dy: int):
        p  = self._players[player_id]
        px, py = p["pos"]
        nx, ny = px + dx, py + dy
        if not (0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT):
            return
        if (nx, ny) in self._islands:
            return
        p["pos"] = (nx, ny)

    def _maintain_jewels(self, now: float):
        if len(self._treasures) >= self._treasure_cap:
            return
        if now < self._next_jewel_spawn:
            return
        self._next_jewel_spawn = now + random.uniform(1.6, 3.4)
        p = self._random_jewel_cell()
        if p:
            self._treasures.add(p)

    def _step_snakes(self, now: float):
        if now < self._freeze_until:
            return
        period = self._base_period
        if now < self._slow_until:
            period *= 1.75
        period *= max(0.6, 1.0 - min(0.4, (self._level - 1) * 0.045))
        if now < self._snake_step_at:
            return
        self._snake_step_at = now + period

        player_positions = {p["pos"] for p in self._players}

        for sn in self._snakes:
            cells = sn["cells"]
            if not cells:
                continue
            occupied_others = set()
            for other in self._snakes:
                if other is sn:
                    continue
                for c in other["cells"][:-1]:
                    occupied_others.add(c)

            body_no_tail = set(cells[:-1])
            tail = cells[-1]
            hx, hy = cells[0]

            # Gasim tinta: jucatorul cel mai aproape care nu e in shoal
            hunted = [(abs(hx-p["pos"][0]) + abs(hy-p["pos"][1]), p["pos"])
                      for p in self._players
                      if p["pos"] not in self._shoal_cells]
            target = hunted[0][1] if hunted else None

            candidates = []
            for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                nx, ny = hx+dx, hy+dy
                if not (0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT):
                    continue
                if (nx, ny) in self._islands:
                    continue
                if (nx, ny) in occupied_others:
                    continue
                if (nx, ny) in body_no_tail and (nx, ny) != tail:
                    continue
                score = 0.0
                if target:
                    score -= abs(nx - target[0]) + abs(ny - target[1])
                score += self._water_openness(nx, ny) * 0.5
                score -= self._island_touch_count(nx, ny) * 1.2
                candidates.append((score, (nx, ny)))

            if not candidates:
                for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                    nx, ny = hx+dx, hy+dy
                    if not (0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT):
                        continue
                    if (nx, ny) in self._islands:
                        continue
                    if (nx, ny) in body_no_tail and (nx, ny) != tail:
                        continue
                    candidates.append((0.0, (nx, ny)))
            if not candidates:
                continue

            candidates.sort(key=lambda t: -t[0])
            sn["cells"] = [candidates[0][1]] + cells[:-1]

    def _check_pickups_and_hits(self, now: float):
        for player_id, p in enumerate(self._players):
            pos = p["pos"]

            # Comori
            if pos in self._treasures:
                self._treasures.discard(pos)
                self._sea_cells.add(pos)
                self._wave_gems += 1
                p["score"] += 10
                if self._wave_gems >= self._wave_need:
                    self._level += 1
                    self._wave_gems = 0
                    self._hud_msg   = f"NIV {self._level}!"
                    self._hud_until = now + 2.0
                    self.on_game_event("level_up", {"level": self._level})
                    self._reset_state(full_restart=False)
                    return

            # Power-up-uri
            if pos in self._powerups:
                kind = self._powerups.pop(pos)
                self._sea_cells.add(pos)
                if kind == "freeze":
                    self._freeze_until = now + 10.0
                    self._hud_msg = "❄ FREEZE!"
                elif kind == "slow":
                    self._slow_until = now + 7.0
                    self._hud_msg = "🐢 SLOW!"
                elif kind == "shield":
                    p["shields"] += 1
                    self._hud_msg = "🛡 SHIELD+"
                self._hud_until = now + 2.8
                self.on_game_event("pickup", {"kind": kind, "player": player_id})

            # Coliziune cu serpi
            hit = any(pos in sn["cells"] for sn in self._snakes)
            if hit:
                if p["shields"] > 0:
                    p["shields"] -= 1
                    self._hud_msg   = "Shield absorbit!"
                    self._hud_until = now + 1.0
                    # Impinge jucatorul in afara sarpelui
                    bx, by = pos
                    push = [(bx+dx, by+dy) for dx, dy in ((0,1),(0,-1),(1,0),(-1,0))
                            if 0 <= bx+dx < BOARD_WIDTH and 0 <= by+dy < BOARD_HEIGHT
                            and (bx+dx, by+dy) not in self._islands]
                    if push:
                        p["pos"] = random.choice(push)
                else:
                    p["lives"] -= 1
                    lost = min(8, 3 + self._level)
                    pool = list(self._treasures)
                    random.shuffle(pool)
                    for t in pool[:lost]:
                        self._treasures.discard(t)
                    self._hud_msg   = f"P{player_id+1} lovit! -{lost} comori"
                    self._hud_until = now + 1.5
                    self.on_game_event("hit", {"player": player_id, "lives": p["lives"]})
                    water = self._water_cells()
                    safe  = [c for c in water
                             if all(abs(c[0]-sn["cells"][0][0]) + abs(c[1]-sn["cells"][0][1]) > 4
                                    for sn in self._snakes if sn["cells"])]
                    p["pos"] = random.choice(safe if safe else list(water))

                    if p["lives"] <= 0:
                        self._hud_msg   = "GAME OVER"
                        self._hud_until = now + 999
                        self.on_game_event("game_over", {"player": player_id})
                        self._running = False

    # ── Internal: rendering ────────────────────────────────────────────────────

    def _build_frame(self, now: float, time_counter: int) -> dict:
        frame = {}

        # Fundalul
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                if (x, y) in self._islands:
                    frame[(x, y)] = self._island_pixel_color(x, y)
                elif (x, y) in self._shoal_cells:
                    frame[(x, y)] = CHASE_SHOAL
                else:
                    frame[(x, y)] = CHASE_WATER

        # Comori
        for t in self._treasures:
            frame[t] = CHASE_TREASURE

        # Power-up-uri
        for pos, pk in self._powerups.items():
            frame[pos] = {
                "freeze": CHASE_PU_FREEZE,
                "slow":   CHASE_PU_SLOW,
                "shield": CHASE_PU_SHIELD,
            }.get(pk, CHASE_PU_FREEZE)

        # Serpi
        for sn in self._snakes:
            for i, c in enumerate(sn["cells"]):
                frame[c] = CHASE_ENEMY_HEAD if i == 0 else CHASE_ENEMY_BODY

        # Jucatori (puls diferit per jucator)
        PLAYER_COLORS = [CHASE_PLAYER, (255, 200, 50), (200, 100, 255), (50, 255, 100)]
        for i, p in enumerate(self._players):
            pulse = int(40 + 35 * math.sin(time_counter * 0.35 + i * 1.5))
            base  = CHASE_PLAYER_SHIELD if p["shields"] > 0 else PLAYER_COLORS[i % len(PLAYER_COLORS)]
            frame[p["pos"]] = (
                min(255, base[0] + pulse // 6),
                min(255, base[1]),
                min(255, base[2]),
            )

        # Border freeze
        if now < self._freeze_until:
            edge = (120, 200, 255)
            for x in range(BOARD_WIDTH):
                frame[(x, 0)]               = edge
                frame[(x, BOARD_HEIGHT-1)]  = edge
            for y in range(BOARD_HEIGHT):
                frame[(0, y)]               = edge
                frame[(BOARD_WIDTH-1, y)]   = edge

        return frame