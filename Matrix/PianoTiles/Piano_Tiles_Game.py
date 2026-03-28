from __future__ import annotations

import json
import os
import random
import sys
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "piano_tiles_config.json")
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_MATRIX_DIR = os.path.normpath(os.path.join(_SCRIPT_DIR, ".."))
if _MATRIX_DIR not in sys.path:
    sys.path.insert(0, _MATRIX_DIR)
try:
    from small_font import FONT_3x5
except ImportError:
    FONT_3x5 = None  # type: ignore[misc, assignment]


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
KEY_STACK_X0, KEY_STACK_X1 = 2, 3
# Single column where scrolling tiles must align for scoring (divider before the track).
TARGET_STRIP_X = 8
RIGHT_GRAY_X = 8
TRACK_X0, TRACK_X1 = 4, 15

TOP_EDGE_ROW = 0
BOTTOM_EDGE_ROW = 31

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
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
# width >= this: one constant score on hit; else single tap score on hit.
LONG_TILE_THRESHOLD = 4
SCROLL_SPEED = 4.5
SPAWN_MIN_INTERVAL = 0.45
SPAWN_MAX_INTERVAL = 1.15
TAP_SCORE = 25
WIDE_TILE_SCORE = 100
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

    def refresh_song_title_from_chart(self) -> None:
        self.chart_song_title = read_song_title_from_chart(_chart_path_from_config())

    def _reload_chart(self) -> None:
        path = _chart_path_from_config()
        self.chart_events = load_chart_sequence(path)
        self.chart_song_title = read_song_title_from_chart(path)

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
            self.chart_origin_time = time.time()
            self.next_spawn_time = time.time()
            self.last_tick = time.time()
            self.state = "PLAYING"

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

    def _apply_scoring(self, _dt: float) -> None:
        for t in self.tiles:
            if t.slot >= self.num_players:
                continue
            if not t.overlaps_target_strip():
                continue
            expected = TARGET_PALETTE[t.row_in_lane]
            if t.color != expected:
                continue
            if not self.pad_pressed(t.slot, t.row_in_lane):
                continue
            if t.tap_awarded:
                continue
            p = self.players[t.slot]
            mult = self._combo_multiplier(p.combo)
            if t.width >= LONG_TILE_THRESHOLD:
                p.score += WIDE_TILE_SCORE * mult
            else:
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

    def _draw_string_3x5(
        self,
        buffer: bytearray,
        text: str,
        x0: int,
        y0: int,
        color: Tuple[int, int, int],
    ) -> None:
        if FONT_3x5 is None:
            return
        x = x0
        for ch in text:
            cols = FONT_3x5.get(ch, FONT_3x5.get(" ", [0, 0, 0]))
            for col_idx, col_byte in enumerate(cols):
                px = x + col_idx
                if px < 0 or px >= BOARD_WIDTH:
                    continue
                for row_idx in range(5):
                    if (col_byte >> row_idx) & 1:
                        py = y0 + row_idx
                        if 0 <= py < 32:
                            self.set_led(buffer, px, py, color)
            x += 4

    def _draw_player_score_hud(self, buffer: bytearray) -> None:
        if FONT_3x5 is None:
            return
        for slot in range(self.num_players):
            if slot >= len(self.players):
                break
            score = max(0, min(9999, self.players[slot].score))
            text = f"{score:4d}"
            text_w = len(text) * 4 - 1
            x0 = max(TRACK_X0, BOARD_WIDTH - text_w)
            y0 = lane_band_top(slot)
            self._draw_string_3x5(buffer, text, x0, y0, WHITE)

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

            self._draw_dividers(buffer)
            for slot in range(NUM_PLAYER_SLOTS):
                self._draw_lane_background(buffer, slot, slot < self.num_players)
            self._draw_tiles(buffer)
            self._draw_player_score_hud(buffer)
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


def main() -> None:
    print("Piano Tiles (matrix) — UDP out:", UDP_SEND_PORT, " listen:", UDP_LISTEN_PORT)
    print("Simulator: Port IN (listen) =", UDP_SEND_PORT, " Port OUT (send) =", UDP_LISTEN_PORT)
    print(
        "Input: click the colored key columns (x=2–3) on each lane row in the simulator, "
        "or use physical foot pads on channel 7 (rows 29–30)."
    )
    chart_path = _chart_path_from_config()
    chart_n = len(load_chart_sequence(chart_path))
    print("Chart file:", chart_path, f"({chart_n} tile waves)" if chart_n else "(missing or empty — random spawn)")
    print("Commands: start <1-4> | scores | reset | pause | resume | quit")
    print(
        f"Scoreboard (UDP): python piano_tiles_scoreboard.py  — listen on port {SCOREBOARD_UDP_PORT}"
    )

    game = PianoTilesGame()
    game.state = "LOBBY"
    game.setup_players(1)
    game.refresh_song_title_from_chart()

    net = NetworkManager(game)
    net.start_bg()
    threading.Thread(target=_game_loop, args=(game,), daemon=True).start()

    try:
        while game.running:
            cmd = input("> ").strip().lower()
            if cmd in ("quit", "exit", "q"):
                game.running = False
                break
            if cmd.startswith("start"):
                parts = cmd.split()
                try:
                    n = int(parts[1]) if len(parts) > 1 else 1
                    game.start_game(n)
                    print(f"Started with {game.num_players} player(s).")
                except (IndexError, ValueError):
                    print("Usage: start <1-4>")
            elif cmd == "scores":
                with game.lock:
                    for p in game.players:
                        m = PianoTilesGame._combo_multiplier(p.combo)
                        print(f"  Player {p.slot + 1}: score={p.score}  combo={p.combo}  next×{m}")
            elif cmd == "reset":
                game.reset()
                print("Tiles cleared. Scores unchanged. Use 'start N' to reset players and scores.")
            elif cmd == "pause":
                with game.lock:
                    game.state = "PAUSED"
                    game._paused_at = time.time()
                print("Paused.")
            elif cmd == "resume":
                with game.lock:
                    pause_len = time.time() - game._paused_at
                    if game.chart_events:
                        game.chart_origin_time += pause_len
                    game.state = "PLAYING"
                    game.last_tick = time.time()
                print("Resumed.")
            elif cmd:
                print("Unknown command.")
    except KeyboardInterrupt:
        game.running = False

    net.running = False
    print("Exiting.")


if __name__ == "__main__":
    main()
