from __future__ import annotations

import json
import os
import random
import socket
import pygame
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

# Import 5×7 pixel font from parent Matrix directory
_MATRIX_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _MATRIX_DIR not in sys.path:
    sys.path.insert(0, _MATRIX_DIR)
try:
    from matrix_font import FONT_5x7 as _FONT_5x7  # type: ignore
except ImportError:
    _FONT_5x7 = {}

_SOUNDS_DIR = os.path.join(_MATRIX_DIR, "sounds")


def _hsv_to_rgb(h: float, s: float, v: float) -> Tuple[int, int, int]:
    if s == 0.0:
        iv = int(v * 255)
        return iv, iv, iv
    i = int(h * 6)
    f = h * 6 - i
    p, q, t_v = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    i %= 6
    rgb = [(v, t_v, p), (q, v, p), (p, v, t_v), (p, q, v), (t_v, p, v), (v, p, q)][i]
    return int(rgb[0] * 255), int(rgb[1] * 255), int(rgb[2] * 255)


def _play_sound_async(filename: str, delay: float = 0.0) -> None:
    """Play a sound file from the sounds directory in a background thread."""
    path = os.path.join(_SOUNDS_DIR, filename)
    def _run():
        try:
            if delay > 0:
                time.sleep(delay)
            if not os.path.exists(path):
                print(f"[sound] not found: {path}")
                return
            snd = pygame.mixer.Sound(path)
            snd.play()
            time.sleep(snd.get_length() + 0.3)  # keep alive until done
        except Exception as e:
            print(f"[sound] {e}")
    threading.Thread(target=_run, daemon=True).start()


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano_tiles_config.json")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_config() -> dict:
    defaults = {
        "device_ip": "255.255.255.255",
        "send_port": 4627,
        "recv_port": 7801,
        "bind_ip": "0.0.0.0",
        "chart_file": "piano_tiles_chart.json",
        "scoreboard_host": "127.0.0.1",
        "scoreboard_udp_port": 7810,
    }
    try:
        if os.path.exists(_CFG_FILE):
            with open(_CFG_FILE, encoding="utf-8") as f:
                return {**defaults, **json.load(f)}
    except OSError:
        pass
    return defaults


CONFIG = _load_config()

UDP_SEND_IP = CONFIG.get("device_ip", "255.255.255.255")
UDP_SEND_PORT = int(CONFIG.get("send_port", 4627))
UDP_LISTEN_PORT = int(CONFIG.get("recv_port", 7801))
SCOREBOARD_HOST = str(CONFIG.get("scoreboard_host", "127.0.0.1"))
SCOREBOARD_UDP_PORT = int(CONFIG.get("scoreboard_udp_port", 7810))

# ---------------------------------------------------------------------------
# Matrix geometry (same wire protocol as Tetris_Game)
# ---------------------------------------------------------------------------
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16

LANE_HEIGHT = 6
# Two full-width gray rows between each player's color band; single gray row at top (y=0) and bottom (y=31).
BETWEEN_PLAYER_GRAY_ROWS = 2
NUM_PLAYER_SLOTS = 4

SAFE_X0, SAFE_X1 = 0, 1
# Two columns: each lane row shows one palette color (stacked vertically), like a row-based keyboard.
KEY_STACK_X0, KEY_STACK_X1 = 2, 2
# Single column where scrolling tiles must align for scoring (divider before the track).
TARGET_STRIP_X = 8
RIGHT_GRAY_X = 8
TRACK_X0, TRACK_X1 = 3, 15

TOP_EDGE_ROW = 0
BOTTOM_EDGE_ROW = 31

BLACK = (0, 0, 0)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
MAGENTA = (255, 0, 255)
ORANGE = (255, 140, 0)
GRAY = (55, 55, 55)
GRAY_BRIGHT = (90, 90, 90)

TARGET_PALETTE: Tuple[Tuple[int, int, int], ...] = (
    RED,
    GREEN,
    BLUE,
    YELLOW,
    MAGENTA,
    ORANGE,
)

ROW_NAME_TO_INDEX = {
    "red": 0,
    "green": 1,
    "blue": 2,
    "yellow": 3,
    "magenta": 4,
    "orange": 5,
}

TILE_MIN_WIDTH = 1
TILE_MAX_WIDTH = 10
# width >= this: score every tick while key held and tile overlaps key column; else one tap score.
LONG_TILE_THRESHOLD = 4
SCROLL_SPEED = 10
SPAWN_MIN_INTERVAL = 0.45
SPAWN_MAX_INTERVAL = 1.15
TAP_SCORE = 25
WIDE_TILE_SCORE = 100
# Wide tiles: points per second while pressed and overlapping the key stack (tuned ~ like old one-shot wide).
WIDE_TILE_HOLD_SCORE_PER_SEC = WIDE_TILE_SCORE * SCROLL_SPEED / float(LONG_TILE_THRESHOLD)
COMBO_MAX = 8
_ID_COUNTER = 0


def _next_tile_id() -> int:
    global _ID_COUNTER
    _ID_COUNTER += 1
    return _ID_COUNTER


def _chart_path_from_config() -> str:
    name = CONFIG.get("chart_file") or "piano_tiles_chart.json"
    path = name if os.path.isabs(name) else os.path.join(_SCRIPT_DIR, name)
    return path


def _parse_row_field(raw) -> int:
    if isinstance(raw, int):
        r = raw
    elif isinstance(raw, str):
        key = raw.strip().lower()
        if key not in ROW_NAME_TO_INDEX:
            raise ValueError(f"unknown row/color name: {raw!r}")
        r = ROW_NAME_TO_INDEX[key]
    else:
        raise TypeError(f"row must be int or str, got {type(raw).__name__}")
    if r < 0 or r >= LANE_HEIGHT:
        raise ValueError(f"row out of range 0..{LANE_HEIGHT - 1}: {r}")
    return r


@dataclass(frozen=True)
class ChartEvent:
    """One spawn wave: same note for every active player at time t (seconds from round start)."""

    t: float
    row: int
    width: int


def read_song_title_from_chart(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return ""
    if not isinstance(data, dict):
        return ""
    for key in ("songName", "song", "title", "name"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def load_song_catalog_entries(catalog_path: str) -> List[Tuple[str, str]]:
    """Resolve songs from piano_tiles_chart.json (manifest or legacy single chart).

    Returns list of (absolute_chart_path, display_title). Paths in manifest are
    relative to the catalog file's directory.
    """
    catalog_path = os.path.abspath(catalog_path)
    base_dir = os.path.dirname(catalog_path)
    try:
        with open(catalog_path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if not isinstance(data, dict):
        return []

    songs = data.get("songs")
    if isinstance(songs, list) and songs:
        out: List[Tuple[str, str]] = []
        for item in songs:
            if not isinstance(item, dict):
                continue
            rel = item.get("file") or item.get("path") or item.get("chart")
            if not isinstance(rel, str) or not rel.strip():
                continue
            rel = rel.strip().replace("\\", "/")
            chart_path = rel if os.path.isabs(rel) else os.path.normpath(os.path.join(base_dir, rel))
            if os.path.abspath(chart_path) == catalog_path:
                continue
            if not os.path.isfile(chart_path):
                continue
            title = None
            for key in ("songName", "song", "title", "name", "label"):
                v = item.get(key)
                if isinstance(v, str) and v.strip():
                    title = v.strip()
                    break
            if not title:
                title = read_song_title_from_chart(chart_path)
            if not title:
                title = os.path.basename(chart_path)
            out.append((chart_path, title.strip()))
        return out

    if isinstance(data.get("tiles"), list):
        title = read_song_title_from_chart(catalog_path)
        if not title:
            sn = data.get("songName")
            title = sn.strip() if isinstance(sn, str) and sn.strip() else os.path.basename(catalog_path)
        return [(catalog_path, title)]

    return []


def load_chart_sequence(path: str) -> List[ChartEvent]:
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return []
    raw_tiles = data.get("tiles")
    if not isinstance(raw_tiles, list):
        return []
    events: List[ChartEvent] = []
    for item in raw_tiles:
        if not isinstance(item, dict):
            continue
        t_val = item.get("t", item.get("at", item.get("time")))
        if t_val is None:
            continue
        try:
            t = float(t_val)
        except (TypeError, ValueError):
            continue
        if "row" not in item:
            continue
        try:
            row = _parse_row_field(item["row"])
        except (ValueError, TypeError):
            continue
        w_raw = item.get("width", item.get("w", TILE_MIN_WIDTH))
        try:
            w = int(w_raw)
        except (TypeError, ValueError):
            continue
        w = max(TILE_MIN_WIDTH, min(TILE_MAX_WIDTH, w))
        events.append(ChartEvent(t=t, row=row, width=w))
    events.sort(key=lambda e: e.t)
    return events


def lane_band_top(slot: int) -> int:
    return 1 + slot * (LANE_HEIGHT + BETWEEN_PLAYER_GRAY_ROWS)


def lane_world_y(slot: int, row_in_lane: int) -> int:
    return lane_band_top(slot) + row_in_lane


def led_ch_index_to_board_xy(ch: int, led_idx: int) -> Tuple[int, int]:
    """Map (channel, led 0..63) to 16×32 board (x, y); matches Simulator and set_led."""
    row_in_channel = led_idx // 16
    col_raw = led_idx % 16
    if row_in_channel % 2 == 0:
        x = col_raw
    else:
        x = 15 - col_raw
    y = ch * 4 + row_in_channel
    return x, y


@dataclass
class MovingTile:
    slot: int
    row_in_lane: int
    x: float
    width: int
    color: Tuple[int, int, int]
    id: int = field(default_factory=_next_tile_id)
    tap_awarded: bool = False

    def int_left(self) -> int:
        return int(self.x)

    def target_column_x(self) -> int:
        return TARGET_STRIP_X

    def overlaps_target_strip(self) -> bool:
        cx = self.target_column_x()
        left = self.int_left()
        right = left + self.width - 1
        return not (left > cx or right < cx)

    def overlaps_key_stack(self) -> bool:
        """True when the scrolling tile covers the lane key column(s) (KEY_STACK_X0..KEY_STACK_X1)."""
        left = self.int_left()
        right = left + self.width - 1
        return not (right < KEY_STACK_X0 or left > KEY_STACK_X1)

    def fully_past_target(self) -> bool:
        cx = self.target_column_x()
        return self.int_left() + self.width - 1 < cx


@dataclass
class PlayerState:
    slot: int
    score: int = 0
    # Successful-note streak; next hit multiplier is min(combo + 1, COMBO_MAX). Reset to 0 on miss.
    combo: int = 0


@dataclass
class PianoTilesGame:
    running: bool = True
    state: str = "LOBBY"
    num_players: int = 1

    tiles: List[MovingTile] = field(default_factory=list)
    players: List[PlayerState] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock)

    button_states: List[bool] = field(default_factory=lambda: [False] * 64)
    prev_button_states: List[bool] = field(default_factory=lambda: [False] * 64)
    # (x, y) cells pressed this frame, all channels — so simulator clicks on keys score correctly.
    pressed_xy: Set[Tuple[int, int]] = field(default_factory=set)

    next_spawn_time: float = field(default_factory=time.time)
    last_tick: float = field(default_factory=time.time)

    chart_events: List[ChartEvent] = field(default_factory=list)
    chart_next_index: int = 0
    chart_origin_time: float = 0.0
    _paused_at: float = 0.0
    chart_song_title: str = ""
    _last_scoreboard_broadcast: float = 0.0
    _song_end_message_printed: bool = False
    # When set, chart JSON for gameplay (overrides config chart_file).
    chart_file_override: Optional[str] = None
    # Title from piano_tiles_chart.json manifest (songs[].songName); wins over leaf chart file.
    chart_title_override: Optional[str] = None
    countdown_start: float = 0.0
    music_file: str = ""
    victory_start: float = 0.0
    winner_slot: int = 0
    _victory_sounds_done: Set[int] = field(default_factory=set)

    def _active_chart_path(self) -> str:
        if self.chart_file_override:
            return self.chart_file_override
        return _chart_path_from_config()

    def _resolve_chart_song_title(self) -> str:
        if self.chart_title_override and str(self.chart_title_override).strip():
            return str(self.chart_title_override).strip()
        return read_song_title_from_chart(self._active_chart_path())

    def refresh_song_title_from_chart(self) -> None:
        self.chart_song_title = self._resolve_chart_song_title()

    def _reload_chart(self) -> None:
        path = self._active_chart_path()
        self.chart_events = load_chart_sequence(path)
        self.chart_song_title = self._resolve_chart_song_title()

    @staticmethod
    def _combo_multiplier(combo_streak: int) -> int:
        return min(combo_streak + 1, COMBO_MAX)

    def scoreboard_payload(self, t: float) -> dict:
        with self.lock:
            return {
                "song": self.chart_song_title,
                "state": self.state,
                "num_players": self.num_players,
                "combo_max": COMBO_MAX,
                "players": [
                    {
                        "slot": p.slot,
                        "score": p.score,
                        "combo": p.combo,
                        "combo_mult_next": self._combo_multiplier(p.combo),
                    }
                    for p in self.players
                ],
                "updated": t,
            }

    def maybe_broadcast_scoreboard(
        self, sock: Optional[socket.socket], now: Optional[float] = None, min_interval: float = 0.1
    ) -> None:
        if sock is None:
            return
        t = time.time() if now is None else now
        if t - self._last_scoreboard_broadcast < min_interval:
            return
        self._last_scoreboard_broadcast = t
        payload = self.scoreboard_payload(t)
        try:
            data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
            if len(data) < 60000:
                sock.sendto(data, (SCOREBOARD_HOST, SCOREBOARD_UDP_PORT))
        except OSError:
            pass

    def setup_players(self, count: int) -> None:
        count = max(1, min(4, count))
        self.num_players = count
        self.players = [PlayerState(slot=i) for i in range(count)]

    def start_game(self, count: int) -> None:
        with self.lock:
            self.setup_players(count)
            self.tiles.clear()
            self._reload_chart()
            self.chart_next_index = 0
            self._song_end_message_printed = False
            self.countdown_start = time.time()
            self._victory_sounds_done = set()
            self.state = "COUNTDOWN"
            _play_sound_async("3 2 1 0 Countdown With Sound Effect  No Copyright  Ready To Use.mp3", delay=1.0)

    def reset(self) -> None:
        with self.lock:
            self.tiles.clear()
            self.chart_next_index = 0
            self.chart_origin_time = time.time()
            self.next_spawn_time = time.time()
            self.last_tick = time.time()
            if self.num_players < 1:
                self.setup_players(1)

    def map_button_to_color_pad(self, led_idx: int) -> Optional[Tuple[int, int]]:
        if led_idx >= 64:
            return None
        row_in_channel = led_idx // 16
        col_raw = led_idx % 16
        x = col_raw if row_in_channel % 2 == 0 else 15 - col_raw
        y_rel = row_in_channel
        if y_rel not in (1, 2):
            return None
        slot = x // 4
        lx = x % 4
        if lx > 2:
            return None
        if y_rel == 1:
            return (slot, lx)
        return (slot, lx + 3)

    def pad_pressed(self, slot: int, color_row: int) -> bool:
        if slot < 0 or slot >= self.num_players:
            return False
        wy = lane_world_y(slot, color_row)
        for x in range(KEY_STACK_X0, KEY_STACK_X1 + 1):
            if (x, wy) in self.pressed_xy:
                return True
        for i in range(64):
            m = self.map_button_to_color_pad(i)
            if m == (slot, color_row) and self.button_states[i]:
                return True
        return False

    def _random_spawn_delay(self) -> float:
        return random.uniform(SPAWN_MIN_INTERVAL, SPAWN_MAX_INTERVAL)

    def _spawn_tile(self) -> None:
        if self.num_players < 1:
            return
        slot = random.randrange(self.num_players)
        row = random.randrange(LANE_HEIGHT)
        color = TARGET_PALETTE[row]
        w = random.randint(TILE_MIN_WIDTH, TILE_MAX_WIDTH)
        self.tiles.append(
            MovingTile(
                slot=slot,
                row_in_lane=row,
                x=float(BOARD_WIDTH),
                width=w,
                color=color,
            )
        )

    def _spawn_chart_wave(self, ev: ChartEvent) -> None:
        if self.num_players < 1:
            return
        color = TARGET_PALETTE[ev.row]
        x0 = float(BOARD_WIDTH)
        for slot in range(self.num_players):
            self.tiles.append(
                MovingTile(
                    slot=slot,
                    row_in_lane=ev.row,
                    x=x0,
                    width=ev.width,
                    color=color,
                )
            )

    def _apply_scoring(self, dt: float) -> None:
        for t in self.tiles:
            if t.slot >= self.num_players:
                continue
            if not t.overlaps_key_stack():
                continue
            expected = TARGET_PALETTE[t.row_in_lane]
            if t.color != expected:
                continue
            if not self.pad_pressed(t.slot, t.row_in_lane):
                continue
            p = self.players[t.slot]
            if t.width >= LONG_TILE_THRESHOLD:
                mult = self._combo_multiplier(p.combo)
                if not t.tap_awarded:
                    p.combo += 1
                    t.tap_awarded = True
                gain = round(WIDE_TILE_HOLD_SCORE_PER_SEC * mult * dt)
                if gain < 1:
                    gain = 1
                p.score += gain
            else:
                if t.tap_awarded:
                    continue
                mult = self._combo_multiplier(p.combo)
                p.score += TAP_SCORE * mult
                p.combo += 1
                t.tap_awarded = True

    def _tile_missed_reset_combo(self, t: MovingTile) -> None:
        if t.slot < 0 or t.slot >= self.num_players:
            return
        if t.color != TARGET_PALETTE[t.row_in_lane]:
            return
        if t.tap_awarded:
            return
        self.players[t.slot].combo = 0

    def tick(self) -> None:
        with self.lock:
            if self.state == "COUNTDOWN":
                if time.time() - self.countdown_start >= 4.0:
                    self.chart_origin_time = time.time()
                    self.next_spawn_time   = time.time()
                    self.last_tick         = time.time()
                    self.state = "PLAYING"
                    if self.music_file:
                        try:
                            pygame.mixer.music.load(self.music_file)
                            pygame.mixer.music.play(0)
                        except Exception:
                            pass
                return
            if self.state == "VICTORY_ANIM":
                elapsed = time.time() - self.victory_start
                # Phase 1 start (~2.5s): drum roll for suspense
                if elapsed >= 2.5 and 1 not in self._victory_sounds_done:
                    self._victory_sounds_done.add(1)
                    _play_sound_async("drum_roll.mp3")
                # Phase 3 start (~7.5s): victory fanfare
                if elapsed >= 7.5 and 3 not in self._victory_sounds_done:
                    self._victory_sounds_done.add(3)
                    _play_sound_async("Victory Sound Effect.mp3")
                if elapsed >= 11.0:
                    self.state = "ENDED"
                return
            if self.state != "PLAYING":
                return

            now = time.time()
            dt = now - self.last_tick
            self.last_tick = now

            if self.chart_events:
                elapsed = now - self.chart_origin_time
                while self.chart_next_index < len(self.chart_events):
                    ev = self.chart_events[self.chart_next_index]
                    if ev.t > elapsed:
                        break
                    self._spawn_chart_wave(ev)
                    self.chart_next_index += 1
            elif now >= self.next_spawn_time:
                self._spawn_tile()
                self.next_spawn_time = now + self._random_spawn_delay()

            step = SCROLL_SPEED * dt
            for t in self.tiles:
                t.x -= step

            self._apply_scoring(dt)

            survivors: List[MovingTile] = []
            for t in self.tiles:
                still_on_board = not t.fully_past_target() or t.x > -t.width
                if still_on_board:
                    survivors.append(t)
                else:
                    self._tile_missed_reset_combo(t)
            self.tiles = survivors

            if (
                len(self.chart_events) > 0
                and self.chart_next_index >= len(self.chart_events)
                and not self.tiles
            ):
                self.state = "VICTORY_ANIM"
                self.victory_start = time.time()
                self._victory_sounds_done = set()
                try:
                    pygame.mixer.music.stop()
                except Exception:
                    pass
                if self.players:
                    self.winner_slot = max(self.players, key=lambda p: p.score).slot
                else:
                    self.winner_slot = 0
                if not self._song_end_message_printed:
                    self._song_end_message_printed = True
                    print(f"\nSong finished! Winner: Player {self.winner_slot + 1}")

            for i in range(64):
                self.prev_button_states[i] = self.button_states[i]

    def set_led(self, buffer: bytearray, x: int, y: int, color: Tuple[int, int, int]) -> None:
        if x < 0 or x >= 16 or y < 0 or y >= 32:
            return
        channel = y // 4
        if channel >= 8:
            return
        row_in_channel = y % 4
        if row_in_channel % 2 == 0:
            led_index = row_in_channel * 16 + x
        else:
            led_index = row_in_channel * 16 + (15 - x)
        block_size = NUM_CHANNELS * 3
        offset = led_index * block_size + channel
        if offset + NUM_CHANNELS * 2 < len(buffer):
            buffer[offset] = color[1]
            buffer[offset + NUM_CHANNELS] = color[0]
            buffer[offset + NUM_CHANNELS * 2] = color[2]

    def _draw_lane_background(self, buffer: bytearray, slot: int, active: bool) -> None:
        top = lane_band_top(slot)
        for r in range(LANE_HEIGHT):
            wy = top + r
            for x in range(SAFE_X0, SAFE_X1 + 1):
                self.set_led(buffer, x, wy, GRAY_BRIGHT if active else GRAY)
            c = TARGET_PALETTE[r]
            if not active:
                c = tuple(v // 4 for v in c)
            else:
                c = tuple(min(255, v + 40) for v in c)
            for x in range(KEY_STACK_X0, KEY_STACK_X1 + 1):
                self.set_led(buffer, x, wy, c)
            for x in range(TRACK_X0, TRACK_X1 + 1):
                self.set_led(buffer, x, wy, BLACK)

    def _draw_dividers(self, buffer: bytearray) -> None:
        for x in range(BOARD_WIDTH):
            self.set_led(buffer, x, TOP_EDGE_ROW, GRAY)
        for s in range(NUM_PLAYER_SLOTS - 1):
            y0 = lane_band_top(s) + LANE_HEIGHT
            for k in range(BETWEEN_PLAYER_GRAY_ROWS):
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, y0 + k, GRAY)
        for x in range(BOARD_WIDTH):
            self.set_led(buffer, x, BOTTOM_EDGE_ROW, GRAY)

    def _draw_tiles(self, buffer: bytearray) -> None:
        for t in self.tiles:
            wy = lane_world_y(t.slot, t.row_in_lane)
            left = t.int_left()
            for dx in range(t.width):
                x = left + dx
                if TRACK_X0 <= x <= TRACK_X1:
                    self.set_led(buffer, x, wy, t.color)

    def _draw_text_rot(self, buffer: bytearray, text: str, y0: int,
                       color: Tuple[int, int, int], scale: int = 1) -> int:
        """Draw text rotated 90°: FONT_5x7 col→Y axis, row→X axis.
        Readable from the short (X) end. Returns y after last character."""
        # 7-row glyph spans 7*scale pixels in X, centered on the 16-wide board
        x_off = (BOARD_WIDTH - 7 * scale) // 2
        cy = y0
        for ch in text.upper():
            cols = _FONT_5x7.get(ch) or _FONT_5x7.get(' ', [0] * 5)
            for ci, col_byte in enumerate(cols):
                for row in range(7):
                    if col_byte & (1 << row):
                        for sr in range(scale):
                            for sc in range(scale):
                                # row 0 (top) → large X (flipped like chase_game)
                                bx = x_off + (6 - row) * scale + sr
                                by = cy + ci * scale + sc
                                self.set_led(buffer, bx, by, color)
            cy += (len(cols) + 1) * scale
        return cy

    def _render_countdown(self, buffer: bytearray) -> None:
        elapsed = time.time() - self.countdown_start
        W, H = 16, 32
        # Phase 0 (0-1s): full-board color pulse
        if elapsed < 1.0:
            t = elapsed
            pulse = int(120 + 80 * abs(((t * 3) % 2) - 1))
            colors = [(pulse, 0, pulse), (0, pulse, pulse), (pulse, pulse, 0)]
            col = colors[int(t * 3) % len(colors)]
            for y in range(H):
                for x in range(W):
                    self.set_led(buffer, x, y, col)
            return
        # Phases 1-3 (1-4s): big digits 3 / 2 / 1  — rotated: col→Y, row→X
        # Each digit bitmap: 7 rows × 5 cols (row-major list of 5-element lists)
        _DIGITS = {
            '3': [[1,1,1,1,0],[0,0,0,1,0],[0,0,0,1,0],[0,1,1,1,0],[0,0,0,1,0],[0,0,0,1,0],[1,1,1,1,0]],
            '2': [[1,1,1,1,0],[0,0,0,1,0],[0,0,0,1,0],[0,1,1,1,0],[1,0,0,0,0],[1,0,0,0,0],[1,1,1,1,0]],
            '1': [[0,1,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,0,1,0,0],[0,1,1,1,0]],
        }
        digit_map = {1.0: ('3', (255, 80, 80)), 2.0: ('2', (255, 220, 0)), 3.0: ('1', (0, 255, 120))}
        digit, color = '3', (255, 80, 80)
        for threshold, (d, c) in sorted(digit_map.items()):
            if elapsed >= threshold:
                digit, color = d, c
        scale = 2
        glyph = _DIGITS[digit]
        # Rotated: rows span X (7*scale), cols span Y (5*scale)
        x_span = 7 * scale
        y_span = 5 * scale
        x_off = (W - x_span) // 2
        y_off = (H - y_span) // 2
        for row_i, row in enumerate(glyph):
            for col_i, bit in enumerate(row):
                if bit:
                    for sr in range(scale):
                        for sc in range(scale):
                            bx = x_off + (6 - row_i) * scale + sr
                            by = y_off + col_i * scale + sc
                            self.set_led(buffer, bx, by, color)

    def _render_victory_anim(self, buffer: bytearray) -> None:
        elapsed = time.time() - self.victory_start
        W, H = 16, 32

        PLAYER_COLORS = [
            (255, 80,  80),
            (80,  200, 255),
            (80,  255, 120),
            (255, 220, 60),
        ]
        win_color = PLAYER_COLORS[self.winner_slot % len(PLAYER_COLORS)]
        # char width along Y per character at scale=1: (5+1)=6 px
        CHAR_STEP = 6

        # ── Phase 0 (0–2s): "NICE!" static, centered, sparkle bg ─────────
        if elapsed < 2.0:
            t = elapsed
            bg = int(20 + 15 * abs(((t * 1.5) % 2) - 1))
            for y in range(H):
                for x in range(W):
                    self.set_led(buffer, x, y, (0, bg, 0))
            rng = random.Random(int(t * 12))
            for _ in range(14):
                sx = rng.randint(0, W - 1)
                sy = rng.randint(0, H - 1)
                br = rng.randint(80, 255)
                self.set_led(buffer, sx, sy, (br, br, br))
            # "NICE!" = 5 chars * 6 = 30 px, centered in H=32 → y_start=1
            self._draw_text_rot(buffer, "NICE!", (H - 5 * CHAR_STEP) // 2,
                                (255, 255, 255))
            return

        # ── Phase 1 (2–5s): "WINNER" scrolls from bottom, rainbow bg ─────
        if elapsed < 5.0:
            t = elapsed - 2.0
            for y in range(H):
                for x in range(W):
                    hue = (x / W + y / H + t * 0.4) % 1.0
                    self.set_led(buffer, x, y, _hsv_to_rgb(hue, 1.0, 0.35))
            # "WINNER" = 6 chars * 6 = 36 px; scroll from y=32 toward y=0
            scroll_y = H - int(t * 14)   # 14 px/s
            self._draw_text_rot(buffer, "WINNER", scroll_y, (255, 255, 255))
            return

        # ── Phase 2 (5–7.5s): ripple circles ─────────────────────────────
        if elapsed < 7.5:
            t = elapsed - 5.0
            cx_f, cy_f = W / 2.0, H / 2.0
            for y in range(H):
                for x in range(W):
                    dist = ((x - cx_f) ** 2 + (y - cy_f) ** 2) ** 0.5
                    wave = 0.0
                    for speed, _ in ((6.0, 0.0), (9.0, 0.33), (12.0, 0.66)):
                        phase = (dist - t * speed) * 0.35
                        wave += 1.0 if (phase % 1.0) < 0.5 else 0.0
                    brightness = min(1.0, wave / 3.0)
                    hue = (dist / 20.0 + t * 0.25) % 1.0
                    self.set_led(buffer, x, y, _hsv_to_rgb(hue, 1.0, brightness))
            return

        # ── Phase 3 (7.5–11s): big "P<N>" + "CONGRATS" scrolling ────────
        t = elapsed - 7.5
        flash = int(t * 5) % 2 == 0
        dim_bg = tuple(v // 5 for v in win_color)
        for y in range(H):
            for x in range(W):
                self.set_led(buffer, x, y, dim_bg if flash else (0, 0, 0))
        # "P1" at scale=2: 2 chars * 12 = 24 px, centered → y_start=4
        txt_col = (255, 255, 255) if flash else win_color
        player_str = f"P{self.winner_slot + 1}"
        self._draw_text_rot(buffer, player_str, (H - len(player_str) * 12) // 2,
                            txt_col, scale=2)
        # "CONGRATS" scrolls up from bottom
        cg_y = H - int(t * 16)
        self._draw_text_rot(buffer, "CONGRATS", cg_y, (255, 220, 60))

    def render(self) -> bytearray:
        buffer = bytearray(FRAME_DATA_LENGTH)
        with self.lock:
            for y in range(32):
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, y, BLACK)

            if self.state == "LOBBY":
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, 14, GRAY_BRIGHT)
                return buffer

            if self.state == "COUNTDOWN":
                self._render_countdown(buffer)
                return buffer

            if self.state == "VICTORY_ANIM":
                self._render_victory_anim(buffer)
                return buffer

            self._draw_dividers(buffer)
            for slot in range(NUM_PLAYER_SLOTS):
                self._draw_lane_background(buffer, slot, slot < self.num_players)
            self._draw_tiles(buffer)
        return buffer


class NetworkManager:
    def __init__(self, game: PianoTilesGame) -> None:
        self.game = game
        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_scoreboard = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.running = True
        self.sequence_number = 0

        bind_ip = CONFIG.get("bind_ip", "0.0.0.0")
        if bind_ip != "0.0.0.0":
            try:
                self.sock_send.bind((bind_ip, 0))
            except OSError as e:
                print(f"Warning: could not bind send socket to {bind_ip}: {e}")

        try:
            self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock_recv.bind(("0.0.0.0", UDP_LISTEN_PORT))
        except OSError as e:
            print(f"Critical: could not bind receive socket to port {UDP_LISTEN_PORT}: {e}")
            self.running = False

    def send_loop(self) -> None:
        while self.running:
            frame = self.game.render()
            self.game.maybe_broadcast_scoreboard(self.sock_scoreboard)
            self._send_packet(frame)
            time.sleep(0.05)

    def _send_packet(self, frame_data: bytearray) -> None:
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0:
            self.sequence_number = 1

        target_ip = UDP_SEND_IP
        port = UDP_SEND_PORT

        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        start_packet = bytearray(
            [
                0x75,
                rand1,
                rand2,
                0x00,
                0x08,
                0x02,
                0x00,
                0x00,
                0x33,
                0x44,
                (self.sequence_number >> 8) & 0xFF,
                self.sequence_number & 0xFF,
                0x00,
                0x00,
                0x00,
            ]
        )
        start_packet.append(0x0E)
        start_packet.append(0x00)
        for addr in (target_ip, "127.0.0.1"):
            try:
                self.sock_send.sendto(start_packet, (addr, port))
            except OSError:
                pass

        fff0_payload = bytearray()
        for _ in range(NUM_CHANNELS):
            fff0_payload += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])

        fff0_internal = (
            bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0, (len(fff0_payload) >> 8) & 0xFF, len(fff0_payload) & 0xFF])
            + fff0_payload
        )
        fff0_len = len(fff0_internal) - 1
        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        fff0_packet = bytearray([0x75, rand1, rand2, (fff0_len >> 8) & 0xFF, fff0_len & 0xFF]) + fff0_internal
        fff0_packet.append(0x1E)
        fff0_packet.append(0x00)
        for addr in (target_ip, "127.0.0.1"):
            try:
                self.sock_send.sendto(fff0_packet, (addr, port))
            except OSError:
                pass

        chunk_size = 984
        data_packet_index = 1
        for i in range(0, len(frame_data), chunk_size):
            rand1 = random.randint(0, 127)
            rand2 = random.randint(0, 127)
            chunk = frame_data[i : i + chunk_size]
            internal_data = bytearray(
                [
                    0x02,
                    0x00,
                    0x00,
                    (0x8877 >> 8) & 0xFF,
                    0x8877 & 0xFF,
                    (data_packet_index >> 8) & 0xFF,
                    data_packet_index & 0xFF,
                    (len(chunk) >> 8) & 0xFF,
                    len(chunk) & 0xFF,
                ]
            )
            internal_data += chunk
            payload_len = len(internal_data) - 1
            packet = bytearray([0x75, rand1, rand2, (payload_len >> 8) & 0xFF, payload_len & 0xFF]) + internal_data
            packet.append(0x1E if len(chunk) == 984 else 0x36)
            packet.append(0x00)
            for addr in (target_ip, "127.0.0.1"):
                try:
                    self.sock_send.sendto(packet, (addr, port))
                except OSError:
                    pass
            data_packet_index += 1
            time.sleep(0.005)

        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        end_packet = bytearray(
            [
                0x75,
                rand1,
                rand2,
                0x00,
                0x08,
                0x02,
                0x00,
                0x00,
                0x55,
                0x66,
                (self.sequence_number >> 8) & 0xFF,
                self.sequence_number & 0xFF,
                0x00,
                0x00,
                0x00,
            ]
        )
        end_packet.append(0x0E)
        end_packet.append(0x00)
        for addr in (target_ip, "127.0.0.1"):
            try:
                self.sock_send.sendto(end_packet, (addr, port))
            except OSError:
                pass

    def recv_loop(self) -> None:
        while self.running:
            try:
                data, _ = self.sock_recv.recvfrom(2048)
                if len(data) >= 1373 and data[0] == 0x88:
                    pressed_xy: Set[Tuple[int, int]] = set()
                    for ch in range(8):
                        base = 2 + ch * 171 + 1
                        if base + 64 > len(data):
                            break
                        for led_idx in range(64):
                            if data[base + led_idx] == 0xCC:
                                x, y = led_ch_index_to_board_xy(ch, led_idx)
                                if 0 <= x < BOARD_WIDTH and 0 <= y < 32:
                                    pressed_xy.add((x, y))
                    offset = 2 + (7 * 171) + 1
                    with self.game.lock:
                        self.game.pressed_xy = pressed_xy
                        for led_idx in range(64):
                            if offset + led_idx < len(data):
                                self.game.button_states[led_idx] = data[offset + led_idx] == 0xCC
                            else:
                                self.game.button_states[led_idx] = False
            except OSError:
                pass

    def start_bg(self) -> None:
        threading.Thread(target=self.send_loop, daemon=True).start()
        threading.Thread(target=self.recv_loop, daemon=True).start()


def _game_loop(game: PianoTilesGame) -> None:
    while game.running:
        game.tick()
        time.sleep(0.016)


def _read_nav_key() -> str:
    """Return up, down, enter, or quit (Esc / q). W/S work as up/down."""
    if sys.platform == "win32":
        import msvcrt

        while True:
            c = msvcrt.getch()
            if c in (b"\r", b"\n"):
                return "enter"
            if c == b"\x1b":
                return "quit"
            if c in (b"q", b"Q"):
                return "quit"
            if c in (b"w", b"W"):
                return "up"
            if c in (b"s", b"S"):
                return "down"
            if c in (b"\xe0", b"\x00"):
                c2 = msvcrt.getch()
                if c2 == b"H":
                    return "up"
                if c2 == b"P":
                    return "down"
    else:
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in "\r\n":
                    return "enter"
                if ch in ("q", "Q"):
                    return "quit"
                if ch in ("w", "W"):
                    return "up"
                if ch in ("s", "S"):
                    return "down"
                if ch == "\x1b":
                    nxt = sys.stdin.read(1)
                    if nxt == "[":
                        c3 = sys.stdin.read(1)
                        if c3 == "A":
                            return "up"
                        if c3 == "B":
                            return "down"
                    return "quit"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _stdout_supports_ansi_redraw() -> bool:
    if not sys.stdout.isatty():
        return False
    if sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            STD_OUTPUT_HANDLE = -11
            ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
            h = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(h, ctypes.byref(mode)):
                return False
            new_mode = mode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
            if not kernel32.SetConsoleMode(h, new_mode):
                return False
        except (AttributeError, OSError, TypeError):
            return False
    return True


def _print_menu_block(title: str, options: List[str], idx: int) -> int:
    """Draw the menu; return how many lines were printed (for cursor rewind)."""
    n = 0
    print(title)
    n += 1
    print("Press : ↑ / ↓  to navigate")
    n += 1
    print()
    n += 1
    for i, opt in enumerate(options):
        prefix = " > " if i == idx else "   "
        print(f"{prefix}{opt}")
        n += 1
    return n


def read_command_line(prompt: str) -> str:
    """Read one command at the prompt. Lone q/Q or Esc quits without Enter."""
    if not sys.stdin.isatty():
        return input(prompt).strip()

    sys.stdout.write(prompt)
    sys.stdout.flush()
    buf: List[str] = []

    if sys.platform == "win32":
        import msvcrt

        while True:
            c = msvcrt.getch()
            if c in (b"\r", b"\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(buf).strip()
            if c == b"\x1b" and not buf:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "q"
            if c in (b"q", b"Q") and not buf:
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "q"
            if c == b"\x03":
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "q"
            if c in (b"\x08", b"\x7f"):
                if buf:
                    buf.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            if c in (b"\xe0", b"\x00"):
                msvcrt.getch()
                continue
            if len(c) == 1 and 32 <= c[0] <= 126:
                ch = chr(c[0])
                buf.append(ch)
                sys.stdout.write(ch)
                sys.stdout.flush()
                continue
    else:
        import select
        import termios
        import tty

        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            while True:
                ch = sys.stdin.read(1)
                if ch in "\r\n":
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "".join(buf).strip()
                if ch == "\x1b":
                    if select.select([sys.stdin], [], [], 0.02)[0]:
                        ch2 = sys.stdin.read(1)
                        if ch2 == "[":
                            sys.stdin.read(1)
                            continue
                    if not buf:
                        sys.stdout.write("\n")
                        sys.stdout.flush()
                        return "q"
                    continue
                if ch in ("q", "Q") and not buf:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "q"
                if ch == "\x03":
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return "q"
                if ch in ("\x08", "\x7f"):
                    if buf:
                        buf.pop()
                        sys.stdout.write("\b \b")
                        sys.stdout.flush()
                    continue
                if 32 <= ord(ch) <= 126:
                    buf.append(ch)
                    sys.stdout.write(ch)
                    sys.stdout.flush()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)

    return "".join(buf).strip()


def terminal_menu_select(title: str, options: List[str]) -> int:
    if not options:
        raise ValueError("empty menu")
    use_ansi = _stdout_supports_ansi_redraw()
    idx = 0
    prev_lines = 0
    first_draw = True
    while True:
        if not first_draw and use_ansi:
            sys.stdout.write(f"\033[{prev_lines}A\033[J")
            sys.stdout.flush()
        elif not first_draw:
            print("─" * 48)
        prev_lines = _print_menu_block(title, options, idx)
        first_draw = False
        sys.stdout.flush()
        key = _read_nav_key()
        if key == "up":
            idx = (idx - 1) % len(options)
        elif key == "down":
            idx = (idx + 1) % len(options)
        elif key == "enter":
            return idx
        elif key == "quit":
            raise KeyboardInterrupt


class LobbyPanel:
    """Tkinter lobby window: select players + song, then start."""

    def __init__(self, game: PianoTilesGame, song_entries: list, root) -> None:
        import tkinter as tk
        from tkinter import font as tkfont
        self.game = game
        self.song_entries = song_entries
        self.root = root

        BG     = "#0d1117"
        MUTED  = "#8b949e"
        TEXT   = "#c9d1d9"
        ACCENT = "#58a6ff"

        self.win = tk.Toplevel(root)
        self.win.title("Piano Tiles — Lobby")
        self.win.configure(bg=BG)
        self.win.resizable(False, False)

        hdr   = tkfont.Font(family="Segoe UI", size=22, weight="bold")
        lbl   = tkfont.Font(family="Segoe UI", size=11)
        btn_f = tkfont.Font(family="Segoe UI", size=13, weight="bold")

        tk.Label(self.win, text="🎹  PIANO TILES", font=hdr, fg=ACCENT, bg=BG).pack(pady=(20, 6))
        tk.Label(self.win, text="Choose options then press START", font=lbl, fg=MUTED, bg=BG).pack(pady=(0, 16))

        # Players
        tk.Label(self.win, text="Players", font=lbl, fg=TEXT, bg=BG).pack()
        self.var_players = tk.StringVar(value="1")
        pf = tk.Frame(self.win, bg=BG)
        pf.pack(pady=4)
        for n in (1, 2, 3, 4):
            tk.Radiobutton(pf, text=f"{n}P", variable=self.var_players, value=str(n),
                           font=lbl, fg=TEXT, bg=BG, selectcolor=BG,
                           activebackground=BG, activeforeground=ACCENT).pack(side="left", padx=8)

        # Song
        tk.Label(self.win, text="Song", font=lbl, fg=TEXT, bg=BG).pack(pady=(12, 0))
        self.var_song = tk.StringVar(value="0")
        sf = tk.Frame(self.win, bg=BG)
        sf.pack(pady=4)
        for i, (_, title) in enumerate(song_entries):
            tk.Radiobutton(sf, text=title, variable=self.var_song, value=str(i),
                           font=lbl, fg=TEXT, bg=BG, selectcolor=BG,
                           activebackground=BG, activeforeground=ACCENT).pack(anchor="w", padx=16)

        self._status_lbl = tk.Label(self.win, text="", font=lbl, fg=ACCENT, bg=BG)
        self._status_lbl.pack(pady=(12, 4))

        self.btn_start = tk.Button(self.win, text="▶  START", font=btn_f,
                                   bg=ACCENT, fg="#0d1117", relief="flat",
                                   padx=20, pady=8, command=self._start)
        self.btn_start.pack(pady=(4, 20))

        self.win.after(100, self._tick)

    def _start(self) -> None:
        n = int(self.var_players.get())
        si = int(self.var_song.get())
        chart, title = self.song_entries[si]
        self.game.chart_file_override  = chart
        self.game.chart_title_override = title
        self.game.music_file = chart.replace(".json", ".mp3")
        self.game.start_game(n)
        self.btn_start.config(state="disabled")

    def _tick(self) -> None:
        import tkinter as tk
        with self.game.lock:
            state    = self.game.state
            cd_start = self.game.countdown_start
        if state == "COUNTDOWN":
            elapsed = time.time() - cd_start
            remaining = max(0, 4.0 - elapsed)
            if elapsed < 1.0:
                self._status_lbl.config(text="GET READY!")
            else:
                self._status_lbl.config(text=f"The song starts in:  {int(remaining) + 1}")
        elif state == "PLAYING":
            self._status_lbl.config(text="♪ Playing!")
            self.btn_start.config(state="normal")
        elif state in ("ENDED", "VICTORY_ANIM"):
            self._status_lbl.config(text="Song finished!")
            self.btn_start.config(state="normal")
        else:
            self._status_lbl.config(text="")
        self.win.after(100, self._tick)


def main() -> None:
    import tkinter as tk
    import platform

    catalog_path = _chart_path_from_config()
    song_entries = load_song_catalog_entries(catalog_path)
    if not song_entries:
        print("No songs found in", catalog_path)
        return

    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    pygame.mixer.set_num_channels(16)

    game = PianoTilesGame()
    game.music_file = os.path.join(_SCRIPT_DIR, "song_charts", "test.mp3")
    game.state = "LOBBY"

    net = NetworkManager(game)
    net.start_bg()
    threading.Thread(target=_game_loop, args=(game,), daemon=True).start()

    root = tk.Tk()
    root.withdraw()

    try:
        import piano_tiles_scoreboard as _sb
        _sb.ScoreboardApp(master=root)
    except Exception as e:
        print(f"[scoreboard] Could not launch scoreboard window: {e}")

    LobbyPanel(game, song_entries, root)

    def console_loop():
        try:
            while game.running:
                cmd = read_command_line("> ").strip().lower()
                if cmd in ("quit", "exit", "q"):
                    game.running = False
                    root.quit()
                    break
                elif cmd == "scores":
                    with game.lock:
                        for p in game.players:
                            m = PianoTilesGame._combo_multiplier(p.combo)
                            print(f"  Player {p.slot + 1}: score={p.score}  combo={p.combo}  next×{m}")
                elif cmd == "reset":
                    game.reset()
                    print("Tiles cleared.")
                elif cmd:
                    print("Unknown command.")
        except KeyboardInterrupt:
            game.running = False
            root.quit()

    if platform.system() != "Darwin":
        threading.Thread(target=console_loop, daemon=True).start()

    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass

    game.running = False
    net.running = False
    print("Exiting.")


if __name__ == "__main__":
    main()
