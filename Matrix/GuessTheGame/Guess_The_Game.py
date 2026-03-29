from __future__ import annotations

import importlib
import json
import math
import os
import random
import re
import socket
import threading
import time
import tkinter as tk
from tkinter import font as tkfont
from typing import Dict, List, Optional, Set, Tuple

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_CFG_FILE = os.path.join(_SCRIPT_DIR, "guess_the_game_config.json")


def _load_config() -> dict:
    defaults = {
        "device_ip": "255.255.255.255",
        "send_port": 4627,
        "recv_port": 7802,
        "bind_ip": "0.0.0.0",
        "scoreboard_host": "127.0.0.1",
        "scoreboard_udp_port": 7812,
        "words_file": "words.json",
        "round_start_value": 100,
        "award_decay_per_wrong": 20,
        "min_award_on_correct": 15,
        "wrong_guess_penalty": 8,
        "win_score": 500,
        "background_music": "song/background.mp3",
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
UDP_LISTEN_PORT = int(CONFIG.get("recv_port", 7802))
SCOREBOARD_HOST = str(CONFIG.get("scoreboard_host", "127.0.0.1"))
SCOREBOARD_UDP_PORT = int(CONFIG.get("scoreboard_udp_port", 7812))

ROUND_START = int(CONFIG.get("round_start_value", 100))
AWARD_DECAY = int(CONFIG.get("award_decay_per_wrong", 20))
MIN_AWARD = int(CONFIG.get("min_award_on_correct", 15))
WRONG_PENALTY = int(CONFIG.get("wrong_guess_penalty", 10))
WIN_SCORE = int(CONFIG.get("win_score", 500))

# ---------------------------------------------------------------------------
# Matrix geometry (same wire protocol as Piano_Tiles / Tetris)
# ---------------------------------------------------------------------------
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BLACK = (0, 0, 0)
GRAY = (55, 55, 55)
GRAY_BRIGHT = (90, 90, 90)
SPLIT_LINE = (120, 120, 140)
DRAW_INK = (255, 255, 255)
# First/last inner rows: color pickers (below top border y=0, above bottom border y=31).
PALETTE_ROW_TOP = 1
PALETTE_ROW_BOTTOM = 30
# Eight swatches × 2 columns across full width x=0..15 (flush with side margins).
PALETTE_COLORS: List[Tuple[int, int, int]] = [
    (255, 45, 45),
    (45, 255, 65),
    (55, 110, 255),
    (255, 220, 55),
    (230, 55, 255),
    (55, 240, 255),
    (255, 140, 40),
    (255, 255, 255),
]
RESET_MARKER_RED = (255, 0, 0)
# 2×2 touch targets: same vertical “slots” as before (mid mat / mid each half), flush right (x=13–14).
# 2 players: one reset clears the whole canvas. 4 players: top / bottom halves each have a reset.
RESET_2P_CELLS = frozenset({(13, 15), (14, 15), (13, 16), (14, 16)})
RESET_4P_TOP_CELLS = frozenset({(13, 7), (14, 7), (13, 8), (14, 8)})
RESET_4P_BOTTOM_CELLS = frozenset({(13, 22), (14, 22), (13, 23), (14, 23)})


def led_ch_index_to_board_xy(ch: int, led_idx: int) -> Tuple[int, int]:
    row_in_channel = led_idx // 16
    col_raw = led_idx % 16
    if row_in_channel % 2 == 0:
        x = col_raw
    else:
        x = 15 - col_raw
    y = ch * 4 + row_in_channel
    return x, y


def load_words(path: str) -> List[str]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError, TypeError):
        return []
    if isinstance(data, dict) and isinstance(data.get("words"), list):
        out = [str(w).strip() for w in data["words"] if str(w).strip()]
        return out
    if isinstance(data, list):
        return [str(w).strip() for w in data if str(w).strip()]
    return []


def _words_path() -> str:
    name = CONFIG.get("words_file") or "words.json"
    return name if os.path.isabs(name) else os.path.join(_SCRIPT_DIR, name)


def normalize_guess(s: str) -> str:
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _center_window_on_screen(win: tk.Misc, width: int, height: int) -> None:
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def _blend_rgb(a: Tuple[int, int, int], b: Tuple[int, int, int], t: float) -> Tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return (
        int(a[0] + (b[0] - a[0]) * t),
        int(a[1] + (b[1] - a[1]) * t),
        int(a[2] + (b[2] - a[2]) * t),
    )


def _rgb_hex(rgb: Tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _resolve_music_path(raw: Optional[str]) -> Optional[str]:
    if not raw or not str(raw).strip():
        return None
    p = str(raw).strip()
    if os.path.isabs(p):
        return p if os.path.isfile(p) else None
    cand = os.path.join(_SCRIPT_DIR, p)
    return cand if os.path.isfile(cand) else None


def _pygame_mixer():
    """Load pygame.mixer via importlib so we do not rely on `pygame.mixer` on the root package.

    Some installs expose a minimal top-level `pygame` without a `mixer` attribute; the submodule
    `pygame.mixer` is still the real module and provides `.music`.
    """
    return importlib.import_module("pygame.mixer")


def start_background_music() -> None:
    path = _resolve_music_path(CONFIG.get("background_music"))
    if not path:
        return
    try:
        mixer = _pygame_mixer()
        if mixer.get_init() is None:
            mixer.pre_init(44100, -16, 2, 1024)
            mixer.init()
        mixer.music.load(path)
        mixer.music.play(-1)
    except Exception as e:
        print(f"Background music could not start: {e}")
        print("Tip: reinstall audio-capable pygame, e.g.  pip install pygame-ce  or  pip install --force-reinstall pygame")


def stop_background_music() -> None:
    try:
        mixer = _pygame_mixer()
        if mixer.get_init() is not None:
            mixer.music.stop()
    except Exception:
        pass


class GuessTheGame:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.running = True
        self.state = "LOBBY"
        self.num_players = 2
        self.button_states = [False] * 64
        self.pressed_xy: Set[Tuple[int, int]] = set()
        self.words_pool = load_words(_words_path())
        if not self.words_pool:
            self.words_pool = ["star", "moon", "heart", "smile"]
        self._word_order: List[str] = []
        self.current_word = ""
        self.team_scores = [0, 0]
        self.potential_award = [ROUND_START, ROUND_START]
        self.active_guess_team: Optional[int] = None
        self.canvas: Dict[Tuple[int, int], Tuple[int, int, int]] = {}
        self.team_draw_colors: List[Tuple[int, int, int]] = [DRAW_INK, DRAW_INK]
        self._prev_pressed_xy: Set[Tuple[int, int]] = set()
        self._last_scoreboard_broadcast = 0.0
        self._reset_corner_prev: Dict[str, bool] = {"tl": False, "br": False}
        self.winner_team: Optional[int] = None

    def drawing_allowed(self) -> bool:
        return self.active_guess_team is None

    def setup_players(self, count: int) -> None:
        if count not in (1, 2, 4):
            count = 2
        self.num_players = count

    def _shuffle_words(self) -> None:
        self._word_order = list(self.words_pool)
        random.shuffle(self._word_order)

    def _next_word(self) -> None:
        if not self._word_order:
            self._shuffle_words()
        self.current_word = self._word_order.pop(0)
        self.potential_award[0] = ROUND_START
        self.potential_award[1] = ROUND_START
        self.canvas.clear()
        self._prev_pressed_xy = set(self.pressed_xy)

    def start_game(self, count: int) -> None:
        with self.lock:
            self.setup_players(count)
            self.team_scores = [0, 0]
            self.potential_award = [ROUND_START, ROUND_START]
            self.winner_team = None
            self._shuffle_words()
            self._next_word()
            self.active_guess_team = None
            self.state = "PLAYING"
        start_background_music()

    def play_again(self) -> None:
        """New match after game over; same player count, scores reset."""
        with self.lock:
            if self.state != "GAME_OVER":
                return
            self.team_scores = [0, 0]
            self.potential_award = [ROUND_START, ROUND_START]
            self.winner_team = None
            self.active_guess_team = None
            self._shuffle_words()
            self._next_word()
            self.state = "PLAYING"
        start_background_music()

    def return_to_lobby(self) -> None:
        with self.lock:
            self.state = "LOBBY"
            self.team_scores = [0, 0]
            self.potential_award = [ROUND_START, ROUND_START]
            self.current_word = ""
            self.winner_team = None
            self.active_guess_team = None
            self.canvas.clear()
            self._prev_pressed_xy = set(self.pressed_xy)
        stop_background_music()

    def new_word_manual(self) -> None:
        with self.lock:
            if self.state != "PLAYING":
                return
            self._next_word()
            self.active_guess_team = None

    def set_manual_draw_word(self, raw: str) -> str:
        """Host sets the word shown to drawers; clears the mat. Not allowed while a guess is armed."""
        text = (raw or "").strip()
        if not text:
            return "Type a word, then Send."
        with self.lock:
            if self.state != "PLAYING":
                return "Press Start in the Keyboard window first."
            if self.active_guess_team is not None:
                return "A team is guessing — submit a guess with Enter/Send or type unlock in the console."
            self.current_word = text
            self.canvas.clear()
            self._prev_pressed_xy = set(self.pressed_xy)
        return "Word sent to drawers."

    def gui_clear_canvas(self, half: Optional[str] = None) -> None:
        """Clear drawing from the GUI. half: 'top' | 'bottom' for 4p; ignored for 2p (full clear)."""
        with self.lock:
            if self.state != "PLAYING":
                return
            if self.num_players == 2:
                self.canvas.clear()
            elif half == "top":
                x0, x1, y0, y1 = self._drawable_bounds("top")
                self._clear_canvas_in_bounds(x0, x1, y0, y1)
            elif half == "bottom":
                x0, x1, y0, y1 = self._drawable_bounds("bottom")
                self._clear_canvas_in_bounds(x0, x1, y0, y1)
            self._prev_pressed_xy = set(self.pressed_xy)

    def arm_guess(self, team: int) -> None:
        team = 1 if team == 1 else 2
        with self.lock:
            if self.state != "PLAYING":
                return
            self.active_guess_team = team

    def cancel_guess(self) -> None:
        with self.lock:
            self.active_guess_team = None

    def submit_guess(self, raw_text: str) -> str:
        """Process guess for armed team. Returns a short status message."""
        text = normalize_guess(raw_text)
        with self.lock:
            if self.state != "PLAYING":
                return "Not playing."
            team = self.active_guess_team
            if team is None:
                return "Press Guess Team 1 or 2 first."
            if not text:
                return "Type your guess, then press Enter."
            target = normalize_guess(self.current_word)
            idx = team - 1
            self.active_guess_team = None
            if text == target:
                gain = max(MIN_AWARD, self.potential_award[idx])
                self.team_scores[idx] += gain
                if self.team_scores[idx] >= WIN_SCORE:
                    self.winner_team = team
                    self.state = "GAME_OVER"
                    stop_background_music()
                    return (
                        f"Team {team} wins! {self.team_scores[idx]} pts (goal {WIN_SCORE}). Game over!"
                    )
                msg = f"Team {team} correct! +{gain} pts. New word."
                self._next_word()
                return msg
            self.team_scores[idx] = max(0, self.team_scores[idx] - WRONG_PENALTY)
            self.potential_award[idx] = max(MIN_AWARD, self.potential_award[idx] - AWARD_DECAY)
            return (
                f"Team {team} wrong. -{WRONG_PENALTY} pts; "
                f"Drawing unlocked."
            )

    def scoreboard_payload(self, t: float) -> dict:
        with self.lock:
            return {
                "game": "guess_the_game",
                "state": self.state,
                "num_players": self.num_players,
                "team_scores": list(self.team_scores),
                "potential_award": list(self.potential_award),
                "drawing_locked": not self.drawing_allowed(),
                "armed_team": self.active_guess_team,
                "winner_team": self.winner_team,
                "win_score": WIN_SCORE,
                "updated": t,
            }

    def maybe_broadcast_scoreboard(
        self, sock: Optional[socket.socket], now: Optional[float] = None, min_interval: float = 0.12
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

    def _drawable_bounds(self, side: str) -> Tuple[int, int, int, int]:
        """Returns x0, x1, y0, y1 inclusive. For 2 players, `side` is ignored (full inner mat).

        For 4 players the mat is split horizontally: Team 1 draws on top, Team 2 on bottom,
        with two divider rows in the middle (y=15–16, not drawable).
        """
        if self.num_players <= 2:
            return 1, 14, 2, 29
        if side == "top":
            return 1, 14, 2, 14
        return 1, 14, 17, 29

    @staticmethod
    def _zone_fired(pressed: Set[Tuple[int, int]], cells: frozenset) -> bool:
        return any(c in pressed for c in cells)

    def _clear_canvas_in_bounds(self, x0: int, x1: int, y0: int, y1: int) -> None:
        for k in list(self.canvas.keys()):
            x, y = k
            if x0 <= x <= x1 and y0 <= y <= y1:
                del self.canvas[k]

    def _process_reset_corners(self) -> None:
        """Rising-edge press on red 2×2 markers (right side) clears drawing (full mat in 2p; top/bottom in 4p)."""
        if self.state != "PLAYING":
            self._reset_corner_prev = {"tl": False, "br": False}
            return

        if self.num_players <= 2:
            tl_now = self._zone_fired(self.pressed_xy, RESET_2P_CELLS)
            br_now = False
        else:
            tl_now = self._zone_fired(self.pressed_xy, RESET_4P_TOP_CELLS)
            br_now = self._zone_fired(self.pressed_xy, RESET_4P_BOTTOM_CELLS)

        if not self.drawing_allowed():
            self._reset_corner_prev["tl"] = tl_now
            self._reset_corner_prev["br"] = br_now
            return

        if tl_now and not self._reset_corner_prev["tl"]:
            if self.num_players <= 2:
                self.canvas.clear()
            else:
                tx0, tx1, ty0, ty1 = self._drawable_bounds("top")
                self._clear_canvas_in_bounds(tx0, tx1, ty0, ty1)
            self._prev_pressed_xy = set(self.pressed_xy)

        if self.num_players >= 4 and br_now and not self._reset_corner_prev["br"]:
            bx0, bx1, by0, by1 = self._drawable_bounds("bottom")
            self._clear_canvas_in_bounds(bx0, bx1, by0, by1)
            self._prev_pressed_xy = set(self.pressed_xy)

        self._reset_corner_prev["tl"] = tl_now
        self._reset_corner_prev["br"] = br_now

    def _is_reset_marker_cell(self, x: int, y: int) -> bool:
        if self.num_players <= 2:
            return (x, y) in RESET_2P_CELLS
        return (x, y) in RESET_4P_TOP_CELLS or (x, y) in RESET_4P_BOTTOM_CELLS

    def _paint_forbidden_row(self, y: int) -> bool:
        return y in (PALETTE_ROW_TOP, PALETTE_ROW_BOTTOM)

    def _cell_allows_paint(self, x: int, y: int) -> bool:
        if self._is_reset_marker_cell(x, y):
            return False
        if self._paint_forbidden_row(y):
            return False
        if self.num_players <= 2:
            x0, x1, y0, y1 = self._drawable_bounds("top")
            return x0 <= x <= x1 and y0 <= y <= y1
        tx0, tx1, ty0, ty1 = self._drawable_bounds("top")
        bx0, bx1, by0, by1 = self._drawable_bounds("bottom")
        return (tx0 <= x <= tx1 and ty0 <= y <= ty1) or (bx0 <= x <= bx1 and by0 <= y <= by1)

    def _team_index_for_stroke(self, x: int, y: int) -> int:
        if self.num_players == 1:
            return 0
        if self.num_players == 4:
            tx0, tx1, ty0, ty1 = self._drawable_bounds("top")
            if tx0 <= x <= tx1 and ty0 <= y <= ty1:
                return 0
            return 1
        return 0 if y <= 15 else 1

    @staticmethod
    def _palette_color_index(x: int) -> int:
        if x < 0 or x >= BOARD_WIDTH:
            return 0
        return min(x // 2, len(PALETTE_COLORS) - 1)

    def _paint_palette_rows(self, buffer: bytearray) -> None:
        for x in range(BOARD_WIDTH):
            rgb = PALETTE_COLORS[self._palette_color_index(x)]
            self.set_led(buffer, x, PALETTE_ROW_TOP, rgb)
            self.set_led(buffer, x, PALETTE_ROW_BOTTOM, rgb)

    def _apply_drawing(self) -> None:
        if not self.drawing_allowed() or self.state != "PLAYING":
            self._prev_pressed_xy = set(self.pressed_xy)
            return
        rising = self.pressed_xy - self._prev_pressed_xy
        for x, y in rising:
            if y == PALETTE_ROW_TOP and 0 <= x < BOARD_WIDTH:
                self.team_draw_colors[0] = PALETTE_COLORS[self._palette_color_index(x)]
                continue
            if y == PALETTE_ROW_BOTTOM and 0 <= x < BOARD_WIDTH:
                if self.num_players == 1:
                    self.team_draw_colors[0] = PALETTE_COLORS[self._palette_color_index(x)]
                elif self.num_players >= 2:
                    self.team_draw_colors[1] = PALETTE_COLORS[self._palette_color_index(x)]
                continue
            if not self._cell_allows_paint(x, y):
                continue
            if (x, y) in self.canvas:
                del self.canvas[(x, y)]
            else:
                ti = self._team_index_for_stroke(x, y)
                self.canvas[(x, y)] = self.team_draw_colors[ti]
        self._prev_pressed_xy = set(self.pressed_xy)

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

            if self.state == "GAME_OVER":
                gold = (255, 210, 72)
                dim = (35, 40, 55)
                for y in range(32):
                    for x in range(BOARD_WIDTH):
                        self.set_led(buffer, x, y, dim)
                for x in range(BOARD_WIDTH):
                    self.set_led(buffer, x, 0, gold)
                    self.set_led(buffer, x, 31, gold)
                for y in range(32):
                    self.set_led(buffer, 0, y, gold)
                    self.set_led(buffer, 15, y, gold)
                wt = self.winner_team
                if wt == 1:
                    for x in range(1, 15):
                        for y in range(2, 15):
                            self.set_led(buffer, x, y, (60, 180, 90))
                elif wt == 2:
                    for x in range(1, 15):
                        for y in range(17, 30):
                            self.set_led(buffer, x, y, (70, 130, 220))
                return buffer

            self._process_reset_corners()
            self._apply_drawing()

            for (x, y), rgb in self.canvas.items():
                self.set_led(buffer, x, y, rgb)

            for x in range(BOARD_WIDTH):
                self.set_led(buffer, x, 0, GRAY)
                self.set_led(buffer, x, 31, GRAY)
            for y in range(32):
                self.set_led(buffer, 0, y, GRAY)
                self.set_led(buffer, 15, y, GRAY)

            self._paint_palette_rows(buffer)

            if self.num_players == 4:
                for x in range(1, 15):
                    self.set_led(buffer, x, 15, SPLIT_LINE)
                    self.set_led(buffer, x, 16, SPLIT_LINE)

            if self.num_players <= 2:
                for x, y in RESET_2P_CELLS:
                    self.set_led(buffer, x, y, RESET_MARKER_RED)
            else:
                for x, y in RESET_4P_TOP_CELLS:
                    self.set_led(buffer, x, y, RESET_MARKER_RED)
                for x, y in RESET_4P_BOTTOM_CELLS:
                    self.set_led(buffer, x, y, RESET_MARKER_RED)

        return buffer


class NetworkManager:
    def __init__(self, game: GuessTheGame) -> None:
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


class DualUI:
    def __init__(self, game: GuessTheGame, root: tk.Tk) -> None:
        self.game = game
        self.root = root
        root.title("GuessTheGame")
        root.withdraw()

        word_font = tkfont.Font(family="Segoe UI", size=52, weight="bold")
        small = tkfont.Font(family="Segoe UI", size=11)
        hdr_font = tkfont.Font(family="Segoe UI", size=13, weight="bold")
        self._font_ui = tkfont.Font(family="Segoe UI", size=10)
        self._font_ui_sm = tkfont.Font(family="Segoe UI", size=9)
        self._font_section = tkfont.Font(family="Segoe UI", size=10, weight="bold")

        self.win_word = tk.Toplevel(root)
        self.win_word.title("GuessTheGame — Word (for drawers)")
        self.win_word.minsize(560, 360)
        self.win_word.configure(bg="#0d1117")

        w_bg = "#0d1117"
        w_outer = tk.Frame(self.win_word, bg=w_bg)
        w_outer.pack(fill=tk.BOTH, expand=True)
        for i in (0, 2):
            w_outer.rowconfigure(i, weight=1)
            w_outer.columnconfigure(i, weight=1)
        w_inner = tk.Frame(w_outer, bg=w_bg)
        w_inner.grid(row=1, column=1, sticky="")

        tk.Label(
            w_inner,
            text="Draw this word on the mat:",
            font=small,
            fg="#8b949e",
            bg=w_bg,
        ).pack(pady=(8, 10))

        self.lbl_word = tk.Label(
            w_inner,
            text="—",
            font=word_font,
            fg="#58a6ff",
            bg=w_bg,
            wraplength=640,
            justify=tk.CENTER,
        )
        self.lbl_word.pack(pady=(4, 8))

        tk.Label(
            w_inner,
            text="Top/bottom rows: pick team color. Tap a lit tile again to erase. Red squares on the right clear drawing.",
            font=small,
            fg="#f85149",
            bg=w_bg,
            wraplength=640,
            justify=tk.CENTER,
        ).pack(pady=(8, 4))

        self.lbl_word_guess_alert = tk.Label(
            w_inner,
            text="",
            font=small,
            fg="#f85149",
            bg=w_bg,
            wraplength=640,
            justify=tk.CENTER,
        )
        self.lbl_word_guess_alert.pack(pady=(4, 8))

        tk.Label(w_inner, text="Scores", font=hdr_font, fg="#8b949e", bg=w_bg).pack(pady=(8, 4))
        self.lbl_word_scores = tk.Label(w_inner, text="", font=small, fg="#c9d1d9", bg=w_bg, justify=tk.CENTER)
        self.lbl_word_scores.pack(pady=(0, 16))

        # Keyboard / host window — GitHub-style dark panels
        KEY_BG = "#0d1117"
        KEY_MAIN = "#161b22"
        KEY_CARD = "#21262d"
        KEY_BORDER = "#30363d"
        KEY_MUTED = "#8b949e"
        KEY_TEXT = "#c9d1d9"
        KEY_WARN = "#d29922"
        KEY_DIS_FG = "#8b949e"  # keep disabled controls readable on Windows dark UIs

        self.win_key = tk.Toplevel(root)
        self.win_key.title("GuessTheGame — Keyboard")
        self.win_key.minsize(680, 540)
        self.win_key.configure(bg=KEY_BG)

        key_outer = tk.Frame(self.win_key, bg=KEY_BG)
        key_outer.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        for i in (0, 2):
            key_outer.rowconfigure(i, weight=1)
            key_outer.columnconfigure(i, weight=1)
        key_mid = tk.Frame(key_outer, bg=KEY_BG)
        key_mid.grid(row=1, column=1, sticky="")

        row_ui = tk.Frame(key_mid, bg=KEY_BG)
        row_ui.pack()

        main_k = tk.Frame(row_ui, bg=KEY_MAIN, highlightbackground=KEY_BORDER, highlightthickness=1)
        main_k.pack(side=tk.LEFT, padx=(0, 12))

        inner = tk.Frame(main_k, bg=KEY_MAIN)
        inner.pack(fill=tk.BOTH, expand=True, padx=20, pady=18)

        tk.Label(
            inner,
            text="Keyboard & host",
            font=hdr_font,
            fg="#f0f6fc",
            bg=KEY_MAIN,
            anchor=tk.CENTER,
        ).pack(fill=tk.X, pady=(0, 4))
        tk.Label(
            inner,
            text="Guessing, manual word, and mat controls",
            font=self._font_ui_sm,
            fg=KEY_MUTED,
            bg=KEY_MAIN,
            anchor=tk.CENTER,
        ).pack(fill=tk.X, pady=(0, 16))

        setup_card = tk.Frame(inner, bg=KEY_CARD, highlightbackground=KEY_BORDER, highlightthickness=1, padx=14, pady=12)
        setup_card.pack(fill=tk.X, pady=(0, 14))
        tk.Label(setup_card, text="SETUP", font=self._font_section, fg=KEY_MUTED, bg=KEY_CARD, anchor=tk.CENTER).pack(
            fill=tk.X, pady=(0, 8)
        )

        start_wrap = tk.Frame(setup_card, bg=KEY_CARD)
        start_wrap.pack()
        start_row = tk.Frame(start_wrap, bg=KEY_CARD)
        start_row.pack()
        self.var_players = tk.IntVar(value=2)
        rb_kw = {
            "bg": KEY_CARD,
            "fg": KEY_TEXT,
            "selectcolor": "#484f58",
            "activebackground": KEY_CARD,
            "font": self._font_ui,
            "highlightthickness": 0,
        }
        self.rb_1p = tk.Radiobutton(start_row, text="1 player", variable=self.var_players, value=1, **rb_kw)
        self.rb_1p.pack(side=tk.LEFT, padx=(0, 20))
        self.rb_2p = tk.Radiobutton(start_row, text="2 players", variable=self.var_players, value=2, **rb_kw)
        self.rb_2p.pack(side=tk.LEFT, padx=(0, 20))
        self.rb_4p = tk.Radiobutton(start_row, text="4 players", variable=self.var_players, value=4, **rb_kw)
        self.rb_4p.pack(side=tk.LEFT, padx=(0, 24))
        self.btn_start = tk.Button(
            start_row,
            text="Start game",
            font=self._font_ui,
            command=self._ui_start_game,
            bg="#238636",
            fg="#ffffff",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            disabledforeground=KEY_DIS_FG,
            relief=tk.FLAT,
            bd=0,
            padx=20,
            pady=10,
            cursor="hand2",
        )
        self.btn_start.pack(side=tk.LEFT)

        tk.Label(
            inner,
            text="Enter — submit a guess (arm Team 1 or 2 first).\n"
            "Send word — puts what you typed on the drawer screen (no team armed).\n"
            "Skip word — new random word and clear the mat.",
            font=self._font_ui_sm,
            fg=KEY_MUTED,
            bg=KEY_MAIN,
            justify=tk.CENTER,
        ).pack(fill=tk.X, pady=(0, 10))

        self.status_frame = tk.Frame(inner, bg=KEY_CARD, highlightbackground=KEY_BORDER, highlightthickness=1)
        self.status_frame.pack(fill=tk.X, pady=(0, 16))
        self.status = tk.Label(
            self.status_frame,
            text="Choose player count, then Start game.",
            font=self._font_ui,
            fg=KEY_WARN,
            bg=KEY_CARD,
            anchor=tk.CENTER,
            justify=tk.CENTER,
            padx=14,
            pady=12,
            wraplength=480,
        )
        self.status.pack(fill=tk.X)

        tk.Label(inner, text="Choose the team to guess", font=self._font_section, fg=KEY_MUTED, bg=KEY_MAIN, anchor=tk.CENTER).pack(
            fill=tk.X, pady=(0, 8)
        )
        team_wrap = tk.Frame(inner, bg=KEY_MAIN)
        team_wrap.pack(pady=(0, 10))
        team_row = tk.Frame(team_wrap, bg=KEY_MAIN)
        team_row.pack()
        btn_team_kw = dict(
            font=self._font_ui,
            relief=tk.FLAT,
            bd=0,
            padx=18,
            pady=10,
            cursor="hand2",
            activeforeground="#ffffff",
            disabledforeground=KEY_DIS_FG,
        )
        self.btn_guess_t1 = tk.Button(
            team_row,
            text="Team 1",
            command=lambda: self._arm(1),
            bg="#238636",
            fg="#ffffff",
            activebackground="#2ea043",
            **btn_team_kw,
        )
        self.btn_guess_t1.pack(side=tk.LEFT, padx=(0, 10))
        self.btn_guess_t2 = tk.Button(
            team_row,
            text="Team 2",
            command=lambda: self._arm(2),
            bg="#1f6feb",
            fg="#ffffff",
            activebackground="#388bfd",
            **btn_team_kw,
        )
        self._sync_team2_button_visibility()

        tk.Label(inner, text="Word", font=self._font_ui_sm, fg=KEY_MUTED, bg=KEY_MAIN, anchor=tk.CENTER).pack(
            fill=tk.X, pady=(0, 6)
        )
        self.entry = tk.Entry(
            inner,
            font=("Segoe UI", 16),
            bg=KEY_BG,
            fg="#f0f6fc",
            insertbackground="#58a6ff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=KEY_BORDER,
            highlightcolor="#58a6ff",
        )
        self.entry.pack(fill=tk.X, pady=(0, 12), ipady=10)
        self.entry.bind("<Return>", lambda e: self._submit())

        btn_wrap = tk.Frame(inner, bg=KEY_MAIN)
        btn_wrap.pack(pady=(0, 18))
        btn_row = tk.Frame(btn_wrap, bg=KEY_MAIN)
        btn_row.pack()
        btn_sec_kw = dict(
            font=self._font_ui,
            relief=tk.FLAT,
            bd=0,
            padx=16,
            pady=9,
            cursor="hand2",
            bg="#30363d",
            fg=KEY_TEXT,
            activebackground="#484f58",
            activeforeground=KEY_TEXT,
            disabledforeground=KEY_DIS_FG,
        )
        self.btn_enter = tk.Button(btn_row, text="Guess the typed word", width=16, command=self._submit, **btn_sec_kw)
        self.btn_enter.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_send = tk.Button(
            btn_row,
            text="Send a custom word",
            width=16,
            command=self._send_manual_word_ui,
            **btn_sec_kw,
        )
        self.btn_send.pack(side=tk.LEFT, padx=(0, 8))
        self.btn_skip = tk.Button(
            btn_row,
            text="Skip word",
            width=12,
            command=self._skip_word,
            bg="#21262d",
            fg="#db6d28",
            activebackground="#30363d",
            activeforeground="#e0823d",
            disabledforeground=KEY_DIS_FG,
            font=self._font_ui,
            relief=tk.FLAT,
            bd=0,
            padx=14,
            pady=9,
            cursor="hand2",
        )
        self.btn_skip.pack(side=tk.LEFT)

        scores_card = tk.Frame(inner, bg=KEY_CARD, highlightbackground=KEY_BORDER, highlightthickness=1, padx=14, pady=12)
        scores_card.pack(fill=tk.X, pady=(4, 0))
        tk.Label(scores_card, text="SCORES", font=self._font_section, fg=KEY_MUTED, bg=KEY_CARD, anchor=tk.CENTER).pack(
            fill=tk.X, pady=(0, 6)
        )
        self.lbl_scores = tk.Label(
            scores_card, text="", font=small, fg=KEY_TEXT, bg=KEY_CARD, anchor=tk.CENTER, justify=tk.CENTER
        )
        self.lbl_scores.pack()

        sep = tk.Frame(row_ui, width=1, bg=KEY_BORDER)
        sep.pack(side=tk.LEFT, fill=tk.Y, pady=4)
        sidebar = tk.Frame(row_ui, bg=KEY_CARD, highlightbackground=KEY_BORDER, highlightthickness=1, padx=14, pady=14)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, pady=4)
        tk.Label(sidebar, text="MAT", font=self._font_section, fg=KEY_MUTED, bg=KEY_CARD, anchor=tk.CENTER).pack(
            fill=tk.X, pady=(0, 4)
        )
        tk.Label(
            sidebar,
            text="Clear drawing\n(same as red pads)",
            font=self._font_ui_sm,
            fg=KEY_MUTED,
            bg=KEY_CARD,
            justify=tk.CENTER,
        ).pack(pady=(0, 12))
        sb_btn_kw = {
            "width": 12,
            "font": self._font_ui,
            "bg": "#30363d",
            "fg": KEY_TEXT,
            "activebackground": "#484f58",
            "activeforeground": KEY_TEXT,
            "disabledforeground": KEY_DIS_FG,
            "relief": tk.FLAT,
            "bd": 0,
            "padx": 8,
            "pady": 10,
            "cursor": "hand2",
        }
        self.btn_reset_full = tk.Button(sidebar, text="Clear mat", command=lambda: self._gui_reset(None), **sb_btn_kw)
        self.btn_reset_top = tk.Button(sidebar, text="Clear top", command=lambda: self._gui_reset("top"), **sb_btn_kw)
        self.btn_reset_bottom = tk.Button(sidebar, text="Clear bottom", command=lambda: self._gui_reset("bottom"), **sb_btn_kw)

        for w in (self.entry, self.btn_enter, self.btn_send, self.btn_skip, self.btn_guess_t1, self.btn_guess_t2):
            w.config(state=tk.DISABLED)

        _center_window_on_screen(self.win_word, 720, 420)
        self.win_word.update_idletasks()
        kw, kh = 760, 580
        sw = self.win_key.winfo_screenwidth()
        sh = self.win_key.winfo_screenheight()
        kx = max(0, (sw - kw) // 2)
        ky = self.win_word.winfo_y() + self.win_word.winfo_height() + 12
        if ky + kh > sh - 32:
            ky = max(32, sh - kh - 32)
        self.win_key.geometry(f"{kw}x{kh}+{kx}+{ky}")

        self._score_fg_idle = KEY_TEXT
        self._status_border_idle = KEY_BORDER
        self._anim_after_id: Optional[str] = None
        self._word_phase = 0.0
        self._guess_phase = 0.0
        self._ui_score_prev: Tuple[int, int] = (0, 0)
        self._score_flash_until = 0.0
        self._status_glow_until = 0.0
        self._game_over_popup_shown = False

        self.win_word.protocol("WM_DELETE_WINDOW", self._quit)
        self.win_key.protocol("WM_DELETE_WINDOW", self._quit)
        self._sync_reset_sidebar()
        self._tick()
        self._schedule_ui_anim()

    def _schedule_ui_anim(self) -> None:
        self._anim_after_id = self.root.after(45, self._ui_anim_tick)

    def _pulse_status_border(self, duration: float = 0.65) -> None:
        self._status_glow_until = max(self._status_glow_until, time.monotonic() + duration)

    def _ui_anim_tick(self) -> None:
        if not self.root.winfo_exists():
            return
        try:
            if not self.win_word.winfo_exists() or not self.win_key.winfo_exists():
                return
        except tk.TclError:
            return

        self._word_phase += 0.055
        self._guess_phase += 0.11
        now = time.monotonic()

        with self.game.lock:
            playing = self.game.state == "PLAYING"
            game_over = self.game.state == "GAME_OVER"
            cw = self.game.current_word
            armed = self.game.active_guess_team

        try:
            if game_over:
                wv = (math.sin(self._word_phase * 0.75) + 1.0) * 0.5
                rgb = _blend_rgb((0xFF, 0xD7, 0x00), (0xFF, 0x8C, 0x42), wv)
                self.lbl_word.config(fg=_rgb_hex(rgb))
            elif playing and cw:
                w = (math.sin(self._word_phase) + 1.0) * 0.5
                rgb = _blend_rgb((0x3D, 0x8B, 0xFF), (0xA5, 0xE0, 0xFF), w)
                self.lbl_word.config(fg=_rgb_hex(rgb))
            else:
                w = (math.sin(self._word_phase * 0.45) + 1.0) * 0.5
                rgb = _blend_rgb((0x5C, 0x64, 0x6E), (0x9A, 0xA3, 0xAF), w)
                self.lbl_word.config(fg=_rgb_hex(rgb))

            alert_txt = self.lbl_word_guess_alert.cget("text")
            if armed is not None and alert_txt:
                g = (math.sin(self._guess_phase * 2.1) + 1.0) * 0.5
                rgb = _blend_rgb((0xDA, 0x36, 0x33), (0xFF, 0x8B, 0x87), g)
                self.lbl_word_guess_alert.config(fg=_rgb_hex(rgb))

            if now < self._score_flash_until:
                dur = 1.05
                p = min(1.0, (self._score_flash_until - now) / dur)
                rgb = _blend_rgb((0xC9, 0xD1, 0xD9), (0xFF, 0xC2, 0x6B), p)
                fg = _rgb_hex(rgb)
                self.lbl_scores.config(fg=fg)
                self.lbl_word_scores.config(fg=fg)
            else:
                self.lbl_scores.config(fg=self._score_fg_idle)
                self.lbl_word_scores.config(fg=self._score_fg_idle)

            if now < self._status_glow_until:
                u = min(1.0, (self._status_glow_until - now) / 0.65)
                brd = _blend_rgb((0x30, 0x36, 0x3D), (0x58, 0xA6, 0xFF), u)
                self.status_frame.config(highlightbackground=_rgb_hex(brd), highlightthickness=2)
            else:
                self.status_frame.config(highlightbackground=self._status_border_idle, highlightthickness=1)
        except tk.TclError:
            pass

        self._schedule_ui_anim()

    def _ui_start_game(self) -> None:
        n = int(self.var_players.get())
        if n not in (1, 2, 4):
            n = 2
        self.game.start_game(n)
        self.status.config(text=f"Game on — {n} player{'s' if n > 1 else ''}.")
        self._pulse_status_border()

    def _send_manual_word_ui(self) -> None:
        """Push the typed text to the drawer word (host); does not submit a team guess."""
        msg = self.game.set_manual_draw_word(self.entry.get())
        self.entry.delete(0, tk.END)
        self.status.config(text=msg)
        self._pulse_status_border()

    def _skip_word(self) -> None:
        with self.game.lock:
            if self.game.state != "PLAYING":
                return
        self.game.new_word_manual()
        self.status.config(text="Skipped to next word.")
        self._pulse_status_border()

    def _gui_reset(self, half: Optional[str]) -> None:
        with self.game.lock:
            playing = self.game.state == "PLAYING"
            n = self.game.num_players
        if not playing:
            self.status.config(text="Start the game first.")
            self._pulse_status_border(0.35)
            return
        self.game.gui_clear_canvas(half)
        if n == 2 or half is None:
            self.status.config(text="Mat cleared.")
        else:
            self.status.config(text=f"{half.title()} half cleared.")
        self._pulse_status_border()

    def _sync_reset_sidebar(self) -> None:
        self.btn_reset_full.pack_forget()
        self.btn_reset_top.pack_forget()
        self.btn_reset_bottom.pack_forget()
        with self.game.lock:
            playing = self.game.state == "PLAYING"
            n = self.game.num_players
        if not playing:
            return
        if n <= 2:
            self.btn_reset_full.pack(fill=tk.X, pady=4)
        else:
            self.btn_reset_top.pack(fill=tk.X, pady=4)
            self.btn_reset_bottom.pack(fill=tk.X, pady=4)

    def _sync_start_row(self) -> None:
        with self.game.lock:
            st = self.game.state
        s = tk.NORMAL if st == "LOBBY" else tk.DISABLED
        self.btn_start.config(state=s)
        self.rb_1p.config(state=s)
        self.rb_2p.config(state=s)
        self.rb_4p.config(state=s)

    def _arm(self, team: int) -> None:
        with self.game.lock:
            if self.game.active_guess_team is not None:
                return
        self.game.arm_guess(team)
        self.entry.delete(0, tk.END)
        self.entry.focus_set()
        self._sync_team2_button_visibility()
        self._sync_guess_buttons()
        self.status.config(text=f"Team {team} is guessing — type and press Enter to submit.")
        self._pulse_status_border(0.8)

    def _sync_team2_button_visibility(self) -> None:
        with self.game.lock:
            want_team2 = self.game.num_players >= 4
        try:
            team2_packed = bool(self.btn_guess_t2.pack_info())
        except tk.TclError:
            team2_packed = False
        if want_team2 and not team2_packed:
            self.btn_guess_t2.pack(side=tk.LEFT, padx=6)
        elif not want_team2 and team2_packed:
            self.btn_guess_t2.pack_forget()

    def _sync_guess_buttons(self) -> None:
        with self.game.lock:
            playing = self.game.state == "PLAYING"
            armed = self.game.active_guess_team
            two_player = self.game.num_players < 4
        if not playing:
            self.btn_guess_t1.config(state=tk.DISABLED)
            self.btn_guess_t2.config(state=tk.DISABLED)
            return
        if two_player:
            self.btn_guess_t1.config(state=tk.NORMAL)
            self.btn_guess_t2.config(state=tk.DISABLED)
            return
        if armed is None:
            self.btn_guess_t1.config(state=tk.NORMAL)
            self.btn_guess_t2.config(state=tk.NORMAL)
        elif armed == 1:
            self.btn_guess_t1.config(state=tk.NORMAL)
            self.btn_guess_t2.config(state=tk.DISABLED)
        else:
            self.btn_guess_t1.config(state=tk.DISABLED)
            self.btn_guess_t2.config(state=tk.NORMAL)

    def _submit(self) -> None:
        text = self.entry.get()
        msg = self.game.submit_guess(text)
        self.entry.delete(0, tk.END)
        self.status.config(text=msg)
        self._sync_guess_buttons()
        self._pulse_status_border()

    def _open_game_over_dialog(self) -> None:
        if not self.root.winfo_exists():
            return
        with self.game.lock:
            if self.game.state != "GAME_OVER":
                return
            wt = self.game.winner_team
            s1, s2 = self.game.team_scores
        dlg = tk.Toplevel(self.root)
        dlg.title("Game over — GuessTheGame")
        dlg.configure(bg="#0d1117")
        dlg.transient(self.win_key)
        dlg.grab_set()
        dlg.resizable(False, False)
        title_font = tkfont.Font(family="Segoe UI", size=26, weight="bold")
        tk.Label(
            dlg,
            text=f"Team {wt} wins!" if wt else "Game over",
            font=title_font,
            fg="#58a6ff",
            bg="#0d1117",
        ).pack(pady=(28, 6))
        tk.Label(
            dlg,
            text=f"Reached {WIN_SCORE} points.",
            font=("Segoe UI", 11),
            fg="#8b949e",
            bg="#0d1117",
        ).pack()
        tk.Label(
            dlg,
            text=f"Final scores  ·  Team 1: {s1}    Team 2: {s2}",
            font=("Segoe UI", 12),
            fg="#c9d1d9",
            bg="#0d1117",
        ).pack(pady=(18, 28))
        row = tk.Frame(dlg, bg="#0d1117")
        row.pack(pady=(0, 28))
        tk.Button(
            row,
            text="Play again",
            font=("Segoe UI", 11),
            bg="#238636",
            fg="white",
            padx=18,
            pady=10,
            cursor="hand2",
            command=lambda: self._game_over_play_again(dlg),
        ).pack(side=tk.LEFT, padx=6)
        tk.Button(
            row,
            text="Main menu",
            font=("Segoe UI", 11),
            bg="#30363d",
            fg="#f0f6fc",
            padx=18,
            pady=10,
            cursor="hand2",
            command=lambda: self._game_over_main_menu(dlg),
        ).pack(side=tk.LEFT, padx=6)
        dlg.protocol("WM_DELETE_WINDOW", lambda: self._game_over_main_menu(dlg))
        _center_window_on_screen(dlg, 440, 280)

    def _game_over_play_again(self, dlg: tk.Toplevel) -> None:
        try:
            dlg.grab_release()
            dlg.destroy()
        except tk.TclError:
            pass
        self._game_over_popup_shown = False
        self.game.play_again()
        self.status.config(text="New match — same player count.")
        self._pulse_status_border()

    def _game_over_main_menu(self, dlg: tk.Toplevel) -> None:
        try:
            dlg.grab_release()
            dlg.destroy()
        except tk.TclError:
            pass
        self._game_over_popup_shown = False
        self.game.return_to_lobby()
        self.status.config(text="Choose player count, then Start game.")

    def _quit(self) -> None:
        if self._anim_after_id is not None:
            try:
                self.root.after_cancel(self._anim_after_id)
            except tk.TclError:
                pass
            self._anim_after_id = None
        stop_background_music()
        self.game.running = False
        self.root.quit()

    def _tick(self) -> None:
        if not self.root.winfo_exists():
            return
        with self.game.lock:
            playing = self.game.state == "PLAYING"
            game_over = self.game.state == "GAME_OVER"
            w = self.game.current_word if playing else "—"
            s1, s2 = self.game.team_scores
            armed = self.game.active_guess_team
            winner = self.game.winner_team
        if (s1, s2) != self._ui_score_prev:
            self._ui_score_prev = (s1, s2)
            self._score_flash_until = time.monotonic() + 1.05
        if game_over and winner:
            self.lbl_word.config(text=f"TEAM {winner} WINS!")
        else:
            self.lbl_word.config(
                text=w.upper() if w != "—" else "Choose players in Keyboard window, then Start game",
            )
        if armed is not None:
            self.lbl_word_guess_alert.config(
                text=f"A team is guessing — stop! (Team {armed})",
            )
        else:
            self.lbl_word_guess_alert.config(text="")
        score_line = f"Team 1: {s1}    Team 2: {s2}"
        self.lbl_scores.config(text=score_line)
        self.lbl_word_scores.config(text=score_line)
        self._sync_team2_button_visibility()
        self._sync_guess_buttons()
        self._sync_start_row()
        self._sync_reset_sidebar()
        if game_over:
            if not self._game_over_popup_shown:
                self._game_over_popup_shown = True
                self.root.after(80, self._open_game_over_dialog)
        else:
            self._game_over_popup_shown = False
        st = tk.NORMAL if playing else tk.DISABLED
        self.entry.config(state=st)
        self.btn_enter.config(state=st)
        self.btn_skip.config(state=st)
        # Manual "Send word" only when no team is guessing; guesses use Enter.
        send_st = tk.DISABLED if not playing or armed is not None else tk.NORMAL
        self.btn_send.config(state=send_st)
        self.root.after(120, self._tick)


def read_command_line(prompt: str) -> str:
    return input(prompt).strip()


def main() -> None:
    print("GuessTheGame — matrix draw + dual-screen guess")
    print(f"UDP recv port {UDP_LISTEN_PORT} (mat input; Simulator fans out to 7801+7802 by default)")
    print("Start the round from the Keyboard window (2 / 4 players + Start).")
    print("Optional console: start 2 | start 4 | next | scores | unlock | quit")

    game = GuessTheGame()

    net = NetworkManager(game)
    net.start_bg()

    root = tk.Tk()
    DualUI(game, root)

    def console_loop() -> None:
        time.sleep(0.4)
        while game.running:
            try:
                cmd = read_command_line("> ").strip().lower()
            except EOFError:
                break
            if cmd in ("quit", "exit", "q"):
                game.running = False
                root.after(0, root.quit)
                break
            if cmd.startswith("start"):
                parts = cmd.split()
                try:
                    n = int(parts[1]) if len(parts) > 1 else 2
                    if n not in (2, 4):
                        print("Use 2 or 4 players.")
                    else:
                        game.start_game(n)
                        print(f"Started with {n} players. New word drawn.")
                except (IndexError, ValueError):
                    print("Usage: start 2  or  start 4")
            elif cmd == "next":
                game.new_word_manual()
                print("Skipped to next word; canvas cleared.")
            elif cmd == "scores":
                with game.lock:
                    print(f"  Team 1: {game.team_scores[0]}   Team 2: {game.team_scores[1]}")
            elif cmd == "unlock":
                game.cancel_guess()
                print("Drawing force-unlocked.")
            elif cmd:
                print("Unknown command.")

    import platform
    if platform.system() != "Darwin":
        # On macOS, blocking input() in a thread crashes Tcl's notifier
        threading.Thread(target=console_loop, daemon=True).start()

    try:
        root.mainloop()
    finally:
        net.running = False
        print("Exiting.")


if __name__ == "__main__":
    main()
