"""
Chase Game - Pac-Man-style survival on water with islands.
Complet separat de GUI. Primeste un callback pentru frame si tile triggers.
"""

import random
import time
import math

# ── Board dimensions ───────────────────────────────────────────────────────────
BOARD_WIDTH  = 16
BOARD_HEIGHT = 32

# ── Palette ────────────────────────────────────────────────────────────────────
CHASE_WATER          = (5,   42,  95)
CHASE_SHOAL          = (35,  105, 125)
CHASE_ISLAND_COAST   = (15,  50,  10)
CHASE_ISLAND_MID     = (8,   28,  6)
CHASE_ISLAND_INLAND  = (3,   14,  3)
CHASE_TREASURE       = (255, 200, 55)
CHASE_PLAYER         = (0,   245, 220)
CHASE_PLAYER_SHIELD  = (70,  190, 255)
CHASE_ENEMY_HEAD     = (255, 50,  50)
CHASE_ENEMY_BODY     = (180, 20,  30)
CHASE_PU_FREEZE      = (0, 0, 80)
CHASE_PU_SLOW        = (255, 140, 60)
CHASE_PU_SHIELD      = (255, 255, 140)
BLACK                = (0,   0,   0)

# ── 3×5 pixel font (uppercase + digits + punctuation) ─────────────────────────
PIXEL_FONT = {
    'A': [[0,1,0],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'B': [[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,1,0]],
    'C': [[0,1,1],[1,0,0],[1,0,0],[1,0,0],[0,1,1]],
    'D': [[1,1,0],[1,0,1],[1,0,1],[1,0,1],[1,1,0]],
    'E': [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,1,1]],
    'F': [[1,1,1],[1,0,0],[1,1,0],[1,0,0],[1,0,0]],
    'G': [[0,1,1],[1,0,0],[1,0,1],[1,0,1],[0,1,1]],
    'H': [[1,0,1],[1,0,1],[1,1,1],[1,0,1],[1,0,1]],
    'I': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[1,1,1]],
    'J': [[1,1,1],[0,0,1],[0,0,1],[1,0,1],[0,1,0]],
    'K': [[1,0,1],[1,1,0],[1,0,0],[1,1,0],[1,0,1]],
    'L': [[1,0,0],[1,0,0],[1,0,0],[1,0,0],[1,1,1]],
    'M': [[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'N': [[1,0,1],[1,1,1],[1,0,1],[1,0,1],[1,0,1]],
    'O': [[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    'P': [[1,1,0],[1,0,1],[1,1,0],[1,0,0],[1,0,0]],
    'Q': [[0,1,0],[1,0,1],[1,0,1],[1,1,1],[0,1,1]],
    'R': [[1,1,0],[1,0,1],[1,1,0],[1,0,1],[1,0,1]],
    'S': [[0,1,1],[1,0,0],[0,1,0],[0,0,1],[1,1,0]],
    'T': [[1,1,1],[0,1,0],[0,1,0],[0,1,0],[0,1,0]],
    'U': [[1,0,1],[1,0,1],[1,0,1],[1,0,1],[0,1,1]],
    'V': [[1,0,1],[1,0,1],[1,0,1],[0,1,0],[0,1,0]],
    'W': [[1,0,1],[1,0,1],[1,1,1],[1,1,1],[1,0,1]],
    'X': [[1,0,1],[1,0,1],[0,1,0],[1,0,1],[1,0,1]],
    'Y': [[1,0,1],[1,0,1],[0,1,0],[0,1,0],[0,1,0]],
    'Z': [[1,1,1],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    '0': [[0,1,0],[1,0,1],[1,0,1],[1,0,1],[0,1,0]],
    '1': [[0,1,0],[1,1,0],[0,1,0],[0,1,0],[1,1,1]],
    '2': [[1,1,0],[0,0,1],[0,1,0],[1,0,0],[1,1,1]],
    '3': [[1,1,0],[0,0,1],[0,1,0],[0,0,1],[1,1,0]],
    '4': [[1,0,1],[1,0,1],[1,1,1],[0,0,1],[0,0,1]],
    '5': [[1,1,1],[1,0,0],[1,1,0],[0,0,1],[1,1,0]],
    '6': [[0,1,1],[1,0,0],[1,1,0],[1,0,1],[0,1,0]],
    '7': [[1,1,1],[0,0,1],[0,1,0],[0,1,0],[0,1,0]],
    '8': [[0,1,0],[1,0,1],[0,1,0],[1,0,1],[0,1,0]],
    '9': [[0,1,0],[1,0,1],[0,1,1],[0,0,1],[0,1,0]],
    ' ': [[0,0,0],[0,0,0],[0,0,0],[0,0,0],[0,0,0]],
    '!': [[0,1,0],[0,1,0],[0,1,0],[0,0,0],[0,1,0]],
    '-': [[0,0,0],[0,0,0],[1,1,1],[0,0,0],[0,0,0]],
}

# ── Start / restart zone: circle at bottom-centre of the 16×32 board ──────────
_START_CX, _START_CY, _START_R = 8, 28, 3.5
_START_ZONE = frozenset(
    (x, y)
    for x in range(BOARD_WIDTH)
    for y in range(BOARD_HEIGHT)
    if math.sqrt((x - _START_CX) ** 2 + (y - _START_CY) ** 2) <= _START_R
)

# ── Home island sits inside the start zone so players begin there ────────────────
_HOME_ISLAND = frozenset(
    (x, y) for x in range(6, 10) for y in range(25, 29)
)

# ── Rotated text helpers (glyph rows → X axis, cols → Y axis, scale=1) ─────────
_ROT_SCALE = 1


def _text_rot_height(text: str, scale: int = _ROT_SCALE) -> int:
    """Y-span (pixels) of one rotated word at given scale."""
    char_w = 3 * scale
    gap    = scale
    return max(0, len(text) * (char_w + gap) - gap)


def _draw_text_rot(frame: dict, text: str, y_off: int, color: tuple,
                   scale: int = _ROT_SCALE):
    """Paint text rotated 90°: glyph rows → X axis, glyph cols → Y axis.
    Readable when standing at the short (16 px) end looking along depth."""
    char_h = 5 * scale        # letter height across X
    char_w = 3 * scale        # letter depth along  Y
    gap    = scale
    x_off  = (BOARD_WIDTH - char_h) // 2   # centre in X
    cy = y_off
    for ch in text.upper():
        glyph = PIXEL_FONT.get(ch, PIXEL_FONT[' '])
        for row_i, bits in enumerate(glyph):    # row → X  (row 0 = letter top → large X)
            for col_i, bit in enumerate(bits):  # col → Y
                if bit:
                    for sr in range(scale):
                        # Flip row direction so letter tops face large-X (correct upright view)
                        bx = x_off + (4 - row_i) * scale + sr
                        if not (0 <= bx < BOARD_WIDTH):
                            continue
                        for sc in range(scale):
                            by = cy + col_i * scale + sc
                            if 0 <= by < BOARD_HEIGHT:
                                frame[(bx, by)] = color
        cy += char_w + gap


def _noise(x: int, y: int, tick: int) -> float:
    """Deterministic 0-1 noise without consuming random state."""
    return ((x * 17 + y * 31 + tick * 137) % 256) / 255.0


def _vscroll_y(block_height: int, elapsed: float, speed: float = 5.0) -> int:
    """Y-offset for a block that enters from the bottom and scrolls upward, looping."""
    total = BOARD_HEIGHT + block_height
    return int(BOARD_HEIGHT - (elapsed * speed) % total)


def _ocean_bg(frame: dict, t: float, base_b: int = 30, sparkle_thresh: float = 0.91):
    """Fill frame with animated deep-ocean background + bioluminescent sparkles."""
    tick = int(t * 22)
    for y in range(BOARD_HEIGHT):
        for x in range(BOARD_WIDTH):
            w1 = 0.5 + 0.5 * math.sin(t * 1.3 + x * 0.55 + y * 0.28)
            w2 = 0.5 + 0.5 * math.cos(t * 0.85 - x * 0.42 + y * 0.32)
            ripple = (w1 + w2) * 0.5
            r = int(ripple * 6)
            g = int(8  + ripple * 38)
            b = int(base_b + ripple * 75)
            n = _noise(x, y, tick)
            if n > sparkle_thresh:
                sp = int((n - sparkle_thresh) / (1 - sparkle_thresh) * 220)
                r  = min(255, r + sp // 5)
                g  = min(255, g + sp // 2)
                b  = min(255, b + sp)
            frame[(x, y)] = (r, g, b)


def _draw_start_circle(frame: dict, t: float, base_color=(0, 200, 60), draw_r: float = 2.0):
    """Render a small pulsing circle at the start zone centre."""
    glow  = draw_r + 0.8
    pulse = 0.55 + 0.45 * math.sin(t * 3.2)
    tick  = int(t * 18)
    for x in range(BOARD_WIDTH):
        for y in range(BOARD_HEIGHT):
            dist = math.sqrt((x - _START_CX) ** 2 + (y - _START_CY) ** 2)
            if dist <= glow:
                if dist <= draw_r:
                    core = (1.0 - dist / max(draw_r, 0.01)) ** 0.6
                    n    = _noise(x, y, tick)
                    br   = int(base_color[0] * (0.6 + core * 0.4) * pulse)
                    bg   = int(base_color[1] * (0.5 + core * 0.5) * pulse + core * 80)
                    bb   = int(base_color[2] * (0.5 + core * 0.5) * pulse)
                    if n > 0.88:
                        bg = min(255, bg + 60)
                    frame[(x, y)] = (min(255, br), min(255, bg), min(255, bb))
                else:
                    fade = max(0.0, 1.0 - (dist - draw_r) / 0.8)
                    bg   = int(base_color[1] * fade * pulse * 0.7)
                    frame[(x, y)] = (0, bg, int(bg * 0.2))


class ChaseGame:
    """
    Logica completa a jocului Chase, independenta de orice GUI/tkinter.

    Utilizare:
        game = ChaseGame(num_players=2)
        game.start()               # → attract screen

        frame = game.get_frame(time_counter)   # {(x,y): (r,g,b)}
        game.on_tile_pressed(x, y, player_id=0)
        info  = game.get_hud_info()

    State machine:
        idle → attract → playing ↔ (level flash) → game_over_anim → restart_prompt
                 ↑                                                         |
                 └─────────────────────────────────────────────────────────┘
    """

    def __init__(self, num_players: int = 1, on_game_event=None,
                 difficulty_params: dict = None):
        self.num_players   = max(1, min(4, num_players))
        self.on_game_event = on_game_event or (lambda *_: None)

        dp = difficulty_params or {}
        self._base_period   = dp.get("base_period", 0.18)
        self._start_lives   = dp.get("lives", 3)
        self._snakes_bonus  = dp.get("snakes_bonus", 0)

        self._game_state      = "idle"
        self._anim_start      = 0.0
        self._level_flash_end = 0.0   # timestamp when level-up white flash ends

        self._running    = False
        self._start_time = 0.0

        self._reset_state(full_restart=True)

    # ── Public API ─────────────────────────────────────────────────────────────

    def start(self):
        """Begin the attract screen; step on the start circle to launch the game."""
        self._game_state = "attract"
        self._anim_start = time.time()
        self._running    = False

    def stop(self):
        self._running    = False
        self._game_state = "idle"

    def is_running(self) -> bool:
        return self._game_state != "idle"

    def on_tile_pressed(self, x: int, y: int, player_id: int = 0):
        gs = self._game_state

        if gs in ("attract", "restart_prompt"):
            if (x, y) in _START_ZONE:
                self._begin_full_restart()
            return

        if gs != "playing" or not self._running:
            return
        if player_id >= self.num_players:
            return

        if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
            self._players[player_id]["pos"] = (x, y)

    def on_key_direction(self, player_id: int, dx: int, dy: int):
        if self._game_state != "playing" or not self._running:
            return
        if player_id >= self.num_players:
            return
        if self._players[player_id]["move_cooldown"] > 0:
            self._players[player_id]["move_cooldown"] -= 1
            return
        self._try_move_player(player_id, dx, dy)
        self._players[player_id]["move_cooldown"] = max(1, 3 - min(2, self._level // 4))

    def get_frame(self, time_counter: int) -> dict:
        now = time.time()
        gs  = self._game_state

        if gs == "idle":
            return self._frame_idle(now)
        if gs == "attract":
            return self._frame_attract(now)
        if gs == "level_intro":
            return self._frame_level_intro(now)
        if gs == "playing":
            if not self._running:
                return self._frame_idle(now)
            self._tick(now)
            frame = self._build_frame(now, time_counter)
            self._overlay_hud(frame)
            return frame
        if gs == "game_over_anim":
            return self._frame_game_over_anim(now)
        if gs == "restart_prompt":
            return self._frame_restart_prompt(now)

        return self._frame_idle(now)

    def get_hud_info(self) -> dict:
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
            "game_over":   self._game_state in ("game_over_anim", "restart_prompt"),
            "treasures":   len(self._treasures),
            "elapsed":     time.time() - self._start_time,
            "num_snakes":  len(self._snakes),
            "difficulty":  self._difficulty_label,
        }

    # ── LED screen frames ──────────────────────────────────────────────────────

    def _frame_idle(self, now: float) -> dict:
        """Very dim breathing animation so the floor is never dead-black."""
        frame = {}
        t = now
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                w = 0.5 + 0.5 * math.sin(t * 0.4 + x * 0.25 + y * 0.15)
                v = int(w * 5)
                frame[(x, y)] = (0, v, v * 2)
        return frame

    def _frame_attract(self, now: float) -> dict:
        """Attract lobby: ocean + sliding 'START / GAME' + glowing start circle."""
        frame = {}
        t     = now - self._anim_start
        _ocean_bg(frame, t, base_b=25)
        w_start = _text_rot_height("START")   # 19 px at scale=1
        gap     = 2
        w_game  = _text_rot_height("GAME")    # 15 px
        blk_h   = w_start + gap + w_game      # 36 px
        y0      = _vscroll_y(blk_h, t, 4.0)  # slow slide — both words pass through together
        _draw_text_rot(frame, "START", y0,               (0, 245, 220))
        _draw_text_rot(frame, "GAME",  y0 + w_start + gap, (0, 185, 255))
        _draw_start_circle(frame, t)
        return frame

    def _frame_level_intro(self, now: float) -> dict:
        """Flashy RGB interference hype screen, then transition to playing."""
        DURATION = 2.4
        elapsed  = now - self._anim_start
        if elapsed >= DURATION:
            self._game_state = "playing"
            self._running    = True
            self._start_time = now
        frame = {}
        t = elapsed

        # Fast-moving full-spectrum interference background
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                ph   = x * 0.9 + y * 0.45 + t * 14
                ph2  = x * 0.35 - y * 0.7  + t * 9
                mod  = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(ph2))
                r = int((127 + 127 * math.sin(ph))         * mod * 0.75)
                g = int((127 + 127 * math.sin(ph + 2.094)) * mod * 0.75)
                b = int((127 + 127 * math.sin(ph + 4.189)) * mod * 0.75)
                frame[(x, y)] = (max(0, min(255, r)),
                                 max(0, min(255, g)),
                                 max(0, min(255, b)))

        lvl_str = str(self._level)
        lh_lvl  = _text_rot_height("LEVEL")
        lh_num  = _text_rot_height(lvl_str)
        gap     = 3
        blk_h   = lh_lvl + gap + lh_num
        y0      = max(1, (BOARD_HEIGHT - blk_h) // 2)
        _draw_text_rot(frame, "LEVEL", y0,                BLACK)
        _draw_text_rot(frame, lvl_str, y0 + lh_lvl + gap, BLACK)
        return frame

    def _frame_game_over_anim(self, now: float) -> dict:
        """Purple/magenta degradé wave → 'GAME / OVER' rotated scroll → restart prompt."""
        PHASE_WAVE = 3.0
        PHASE_END  = 8.5

        elapsed = now - self._anim_start
        frame   = {}

        if elapsed >= PHASE_END:
            self._game_state = "restart_prompt"
            self._anim_start = now
            return self._frame_restart_prompt(now)

        if elapsed < PHASE_WAVE:
            # Smooth purple/magenta degradé wave
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    ph = elapsed * 1.1 + x * 0.38 + y * 0.19
                    r  = int(70 + 65 * math.sin(ph))
                    g  = int(0  + 18 * math.sin(ph + 1.05))
                    b  = int(55 + 55 * math.sin(ph + 2.09))
                    frame[(x, y)] = (max(0, r), max(0, g), max(0, b))
        else:
            # Dark bg, then rotated "GAME / OVER" scroll
            t2 = elapsed - PHASE_WAVE
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    ph = t2 * 0.5 + x * 0.25 + y * 0.12
                    v  = int(10 + 10 * math.sin(ph))
                    frame[(x, y)] = (max(0, v), 0, max(0, v // 2))
            w_h   = _text_rot_height("GAME")
            gap   = 8
            blk_h = w_h + gap + w_h
            y0    = _vscroll_y(blk_h, t2, 5.5)
            _draw_text_rot(frame, "GAME", y0,             (210, 60,  200))
            _draw_text_rot(frame, "OVER", y0 + w_h + gap, (180, 80,  255))

        return frame

    def _frame_restart_prompt(self, now: float) -> dict:
        """Restart screen: dark ocean + rotated scroll 'PLAY / REDO' + glow circle."""
        frame = {}
        t     = now - self._anim_start
        _ocean_bg(frame, t, base_b=15, sparkle_thresh=0.94)
        for k, (r, g, b) in frame.items():
            frame[k] = (min(255, r + 12), g, b)
        w_h   = _text_rot_height("PLAY")
        gap   = 8
        blk_h = w_h + gap + w_h
        y0    = _vscroll_y(blk_h, t)
        _draw_text_rot(frame, "PLAY", y0,             (255, 210, 40))
        _draw_text_rot(frame, "REDO", y0 + w_h + gap, (255, 140,  0))
        _draw_start_circle(frame, t, base_color=(60, 200, 20))
        return frame

    # ── HUD overlay (centred lives row per player) ────────────────────────────

    def _overlay_hud(self, frame: dict):
        for p_idx, p in enumerate(self._players):
            y = p_idx   # one row per player at the top
            total = self._start_lives
            # 1 px per life, 1 px gap between → strip width = 2*total - 1
            strip_w = total + (total - 1)
            x_start = (BOARD_WIDTH - strip_w) // 2
            for l in range(total):
                x = x_start + l * 2
                if 0 <= x < BOARD_WIDTH:
                    alive = l < p["lives"]
                    frame[(x, y)] = (200, 25, 25) if alive else (35, 8, 8)

    # ── State-machine helpers ──────────────────────────────────────────────────

    def _begin_full_restart(self):
        self._reset_state(full_restart=True)
        self._running    = False
        self._game_state = "level_intro"
        self._anim_start = time.time()
        self.on_game_event("level_up", {"level": self._level})

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
        touches_water    = False
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

    def _spawn_snakes(self, water: set):
        """Spawn fresh snakes into the current water cells, keeping existing ones cleared first."""
        snake_len  = max(3, 4 - min(1, (self._level - 1) // 3))
        num_snakes = min(5, 2 + self._level // 2 + self._snakes_bonus)
        occupied   = {p["pos"] for p in self._players}
        for _ in range(num_snakes):
            spawns = [
                c for c in water
                if c not in occupied
                and all(abs(c[0]-p["pos"][0]) + abs(c[1]-p["pos"][1]) > 8
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
                cand  = [pt for pt in neigh
                         if pt in water and pt not in cells and pt not in occupied]
                if not cand:
                    break
                nxt = random.choice(cand)
                cells.append(nxt)
                cur = nxt
            for c in cells:
                occupied.add(c)
            self._snakes.append({"cells": cells})

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
            self._level             = 1
            self._wave_gems         = 0
            self._difficulty_label  = "Normal"
            self._players = [
                {"lives": self._start_lives, "shields": 0, "score": 0,
                 "pos": (0, 0), "move_cooldown": 0}
                for _ in range(self.num_players)
            ]

        self._islands           = set()
        self._shoal_cells       = set()
        self._sea_cells         = set()
        self._treasures         = set()
        self._powerups          = {}
        self._snakes            = []
        self._freeze_until      = 0.0
        self._slow_until        = 0.0
        self._hud_msg           = ""
        self._hud_until         = 0.0
        self._snake_step_at     = 0.0
        self._next_jewel_spawn  = 0.0
        self._level_flash_end   = 0.0
        self._treasure_cap      = 7
        self._wave_need         = 8 + self._level * 2

        self._random_islands(
            num_blobs=random.randint(4, 7),
            min_cells=3, max_cells=7,
        )
        # Always guarantee the home island near the start zone
        self._islands |= _HOME_ISLAND
        self._rebuild_shoal()

        water = self._water_cells()
        if len(water) < 40:
            self._islands.clear()
            self._islands |= _HOME_ISLAND
            self._rebuild_shoal()
            water = self._water_cells()

        # Spawn players: home island first, then any island, then safe water
        used        = set()
        home_list   = sorted(_HOME_ISLAND)
        island_rest = [c for c in sorted(self._islands) if c not in _HOME_ISLAND]
        water_list  = sorted(water)
        random.shuffle(home_list)
        random.shuffle(island_rest)
        safe_water  = [c for c in water_list if c in _START_ZONE or c[1] > 22]

        for p in self._players:
            for pool in (home_list, island_rest, safe_water, water_list):
                choices = [c for c in pool if c not in used]
                if choices:
                    p["pos"] = choices[0]
                    used.add(choices[0])
                    break

        self._treasure_cap = max(6, min(11, 6 + self._level // 3))
        self._wave_need    = 8 + self._level * 2

        self._snakes = []
        self._spawn_snakes(water)

        for _ in range(max(4, min(self._treasure_cap, 7))):
            p = self._random_jewel_cell()
            if p:
                self._treasures.add(p)

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
        """Move player; islands are passable (safe refuge from snakes)."""
        p  = self._players[player_id]
        px, py = p["pos"]
        nx, ny = px + dx, py + dy
        if 0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT:
            p["pos"] = (nx, ny)

    def _maintain_jewels(self, now: float):
        if len(self._treasures) >= self._treasure_cap or now < self._next_jewel_spawn:
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

        for sn in self._snakes:
            cells = sn["cells"]
            if not cells:
                continue
            occupied_others = set()
            for other in self._snakes:
                if other is not sn:
                    for c in other["cells"][:-1]:
                        occupied_others.add(c)

            body_no_tail = set(cells[:-1])
            tail = cells[-1]
            hx, hy = cells[0]

            # Chase nearest player not on an island (islands = safe zones)
            hunted = sorted(
                [(abs(hx-p["pos"][0]) + abs(hy-p["pos"][1]), p["pos"])
                 for p in self._players
                 if p["pos"] not in self._islands],
            )
            target = hunted[0][1] if hunted else None

            candidates = []
            for dx, dy in ((-1,0),(1,0),(0,-1),(0,1)):
                nx, ny = hx+dx, hy+dy
                if not (0 <= nx < BOARD_WIDTH and 0 <= ny < BOARD_HEIGHT):
                    continue
                if (nx, ny) in self._islands:
                    continue   # snakes cannot enter islands
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

            # Treasures only collectable in water (not on island)
            if pos in self._treasures and pos not in self._islands:
                self._treasures.discard(pos)
                self._sea_cells.add(pos)
                self._wave_gems += 1
                p["score"] += 10
                self.on_game_event("treasure", {"player": player_id})
                if self._wave_gems >= self._wave_need:
                    self._level += 1
                    self._wave_gems = 0
                    self._hud_msg   = f"NIV {self._level}!"
                    self._hud_until = now + 2.0
                    self.on_game_event("level_up", {"level": self._level})
                    self._reset_state(full_restart=False)
                    self._running    = False
                    self._game_state = "level_intro"
                    self._anim_start = now
                    return

            # Power-ups
            if pos in self._powerups and pos not in self._islands:
                kind = self._powerups.pop(pos)
                self._sea_cells.add(pos)
                if kind == "freeze":
                    self._freeze_until = now + 10.0
                    self._hud_msg = "FREEZE!"
                elif kind == "slow":
                    self._slow_until = now + 7.0
                    self._hud_msg = "SLOW!"
                elif kind == "shield":
                    p["shields"] += 1
                    self._hud_msg = "SHIELD+"
                self._hud_until = now + 2.8
                self.on_game_event("pickup", {"kind": kind, "player": player_id})

            # Snake collision — only when player is in water (island = sanctuary)
            if pos in self._islands:
                continue
            hit = any(pos in sn["cells"] for sn in self._snakes)
            if hit:
                if p["shields"] > 0:
                    p["shields"] -= 1
                    self._hud_msg   = "Shield absorbit!"
                    self._hud_until = now + 1.0
                    bx, by = pos
                    push = [(bx+dx, by+dy) for dx, dy in ((0,1),(0,-1),(1,0),(-1,0))
                            if 0 <= bx+dx < BOARD_WIDTH and 0 <= by+dy < BOARD_HEIGHT]
                    if push:
                        p["pos"] = random.choice(push)
                else:
                    death_pos = pos
                    p["lives"] -= 1
                    lost = min(8, 3 + self._level)
                    pool = list(self._treasures)
                    random.shuffle(pool)
                    for t in pool[:lost]:
                        self._treasures.discard(t)
                    self._hud_msg   = f"P{player_id+1} lovit! -{lost} comori"
                    self._hud_until = now + 1.5
                    self.on_game_event("hit", {"player": player_id, "lives": p["lives"]})
                    # Rerandomize all islands — death island is guaranteed, rest are fresh
                    dx0, dy0 = death_pos
                    death_island = frozenset(
                        (ix, iy)
                        for ix in range(max(0, dx0-1), min(BOARD_WIDTH,  dx0+2))
                        for iy in range(max(0, dy0-1), min(BOARD_HEIGHT, dy0+2))
                    )
                    self._random_islands(
                        num_blobs=random.randint(4, 7),
                        min_cells=3, max_cells=7,
                    )
                    self._islands |= death_island
                    self._islands |= _HOME_ISLAND
                    self._rebuild_shoal()
                    # Respawn snakes so they don't get stuck on new islands
                    self._snakes = []
                    self._spawn_snakes(self._water_cells())
                    # Respawn player on the fresh death island
                    p["pos"] = random.choice(list(death_island))
                    if p["lives"] <= 0:
                        self._hud_msg   = "GAME OVER"
                        self._hud_until = now + 999
                        self.on_game_event("game_over", {"player": player_id})
                        self._running    = False
                        self._game_state = "game_over_anim"
                        self._anim_start = now
                        return

    # ── Internal: rendering ────────────────────────────────────────────────────

    def _build_frame(self, now: float, time_counter: int) -> dict:
        frame = {}

        # Animated water / shoal / island background
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                if (x, y) in self._islands:
                    frame[(x, y)] = self._island_pixel_color(x, y)
                elif (x, y) in self._shoal_cells:
                    # Shoal: lighter, animated
                    w = 0.5 + 0.5 * math.sin(now * 1.6 + x * 0.5 + y * 0.35)
                    frame[(x, y)] = (
                        int(25 + w * 22),
                        int(85 + w * 32),
                        int(112 + w * 28),
                    )
                else:
                    # Deep water: layered ripple
                    w1 = 0.5 + 0.5 * math.sin(now * 1.9 + x * 0.6 + y * 0.30)
                    w2 = 0.5 + 0.5 * math.cos(now * 1.3 - x * 0.4 + y * 0.45)
                    rp = (w1 + w2) * 0.5
                    frame[(x, y)] = (
                        int(3  + rp * 12),
                        int(35 + rp * 35),
                        int(88 + rp * 65),
                    )

        # Level-up white flash overlay
        if now < self._level_flash_end:
            fade = (self._level_flash_end - now) / 0.7
            fv   = int(fade * 210)
            for k, (r, g, b) in frame.items():
                frame[k] = (min(255, r + fv), min(255, g + fv), min(255, b + fv))

        # Treasures
        for t in self._treasures:
            frame[t] = CHASE_TREASURE

        # Power-ups
        for pos, pk in self._powerups.items():
            frame[pos] = {
                "freeze": CHASE_PU_FREEZE,
                "slow":   CHASE_PU_SLOW,
                "shield": CHASE_PU_SHIELD,
            }.get(pk, CHASE_PU_FREEZE)

        # Snakes
        for sn in self._snakes:
            for i, c in enumerate(sn["cells"]):
                frame[c] = CHASE_ENEMY_HEAD if i == 0 else CHASE_ENEMY_BODY

        # Players
        PLAYER_COLORS = [CHASE_PLAYER, (255, 200, 50), (200, 100, 255), (50, 255, 100)]
        for i, p in enumerate(self._players):
            pulse = int(40 + 35 * math.sin(time_counter * 0.35 + i * 1.5))
            base  = CHASE_PLAYER_SHIELD if p["shields"] > 0 else PLAYER_COLORS[i % len(PLAYER_COLORS)]
            frame[p["pos"]] = (
                min(255, base[0] + pulse // 6),
                min(255, base[1]),
                min(255, base[2]),
            )

        # Freeze border — flickers faster as it nears expiry
        if now < self._freeze_until:
            remaining = self._freeze_until - now
            if remaining > 3.0:
                show = True
            else:
                # ramps from 2 Hz → 10 Hz in the last 3 seconds
                freq = 2.0 + (3.0 - remaining) * (8.0 / 3.0)
                show = int(now * freq * 2) % 2 == 0
            if show:
                edge = CHASE_PU_FREEZE
                for x in range(BOARD_WIDTH):
                    frame[(x, 0)]              = edge
                    frame[(x, BOARD_HEIGHT-1)] = edge
                for y in range(BOARD_HEIGHT):
                    frame[(0, y)]              = edge
                    frame[(BOARD_WIDTH-1, y)]  = edge

        return frame
