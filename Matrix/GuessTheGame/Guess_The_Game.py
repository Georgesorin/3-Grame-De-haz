from __future__ import annotations

import json
import os
import random
import re
import socket
import sys
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
RESET_MARKER_RED = (255, 0, 0)
# 2×2 touch targets inside the drawable area (not on the gray border).
RESET_TOPLEFT_CELLS = frozenset({(1, 2), (2, 2), (1, 3), (2, 3)})
RESET_BOTTOMRIGHT_CELLS = frozenset({(13, 28), (14, 28), (13, 29), (14, 29)})


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
        self._last_scoreboard_broadcast = 0.0
        self._reset_corner_prev: Dict[str, bool] = {"tl": False, "br": False}

    def drawing_allowed(self) -> bool:
        return self.active_guess_team is None

    def setup_players(self, count: int) -> None:
        if count not in (2, 4):
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

    def start_game(self, count: int) -> None:
        with self.lock:
            self.setup_players(count)
            self._shuffle_words()
            self._next_word()
            self.active_guess_team = None
            self.state = "PLAYING"

    def new_word_manual(self) -> None:
        with self.lock:
            if self.state != "PLAYING":
                return
            self._next_word()
            self.active_guess_team = None

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
        with two divider rows in the middle (not drawable).
        """
        if self.num_players == 2:
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
        """Rising-edge press on red 2×2 markers clears that side’s drawing (or all in 2-player)."""
        if self.state != "PLAYING":
            self._reset_corner_prev = {"tl": False, "br": False}
            return

        tl_now = self._zone_fired(self.pressed_xy, RESET_TOPLEFT_CELLS)
        br_now = self._zone_fired(self.pressed_xy, RESET_BOTTOMRIGHT_CELLS)

        if not self.drawing_allowed():
            self._reset_corner_prev["tl"] = tl_now
            self._reset_corner_prev["br"] = br_now
            return

        if tl_now and not self._reset_corner_prev["tl"]:
            if self.num_players == 2:
                self.canvas.clear()
            else:
                tx0, tx1, ty0, ty1 = self._drawable_bounds("top")
                self._clear_canvas_in_bounds(tx0, tx1, ty0, ty1)

        if self.num_players >= 4 and br_now and not self._reset_corner_prev["br"]:
            bx0, bx1, by0, by1 = self._drawable_bounds("bottom")
            self._clear_canvas_in_bounds(bx0, bx1, by0, by1)

        self._reset_corner_prev["tl"] = tl_now
        self._reset_corner_prev["br"] = br_now

    def _is_reset_marker_cell(self, x: int, y: int) -> bool:
        if (x, y) in RESET_TOPLEFT_CELLS:
            return True
        if self.num_players >= 4 and (x, y) in RESET_BOTTOMRIGHT_CELLS:
            return True
        return False

    def _apply_drawing(self) -> None:
        if not self.drawing_allowed() or self.state != "PLAYING":
            return
        for x, y in self.pressed_xy:
            if self._is_reset_marker_cell(x, y):
                continue
            if self.num_players == 2:
                x0, x1, y0, y1 = self._drawable_bounds("top")
                if x0 <= x <= x1 and y0 <= y <= y1:
                    self.canvas[(x, y)] = DRAW_INK
            else:
                tx0, tx1, ty0, ty1 = self._drawable_bounds("top")
                bx0, bx1, by0, by1 = self._drawable_bounds("bottom")
                if tx0 <= x <= tx1 and ty0 <= y <= ty1:
                    self.canvas[(x, y)] = DRAW_INK
                elif bx0 <= x <= bx1 and by0 <= y <= by1:
                    self.canvas[(x, y)] = DRAW_INK

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

            if self.num_players == 4:
                for x in range(1, 15):
                    self.set_led(buffer, x, 15, SPLIT_LINE)
                    self.set_led(buffer, x, 16, SPLIT_LINE)

            for x, y in RESET_TOPLEFT_CELLS:
                self.set_led(buffer, x, y, RESET_MARKER_RED)
            if self.num_players >= 4:
                for x, y in RESET_BOTTOMRIGHT_CELLS:
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

        word_font = tkfont.Font(size=52, weight="bold")
        small = tkfont.Font(size=12)
        hdr_font = tkfont.Font(size=14, weight="bold")

        self.win_word = tk.Toplevel(root)
        self.win_word.title("GuessTheGame — Word (for drawers)")
        self.win_word.geometry("720x380+80+80")
        self.win_word.configure(bg="#0d1117")

        tk.Label(
            self.win_word,
            text="Draw this word on the mat:",
            font=small,
            fg="#8b949e",
            bg="#0d1117",
        ).pack(pady=(24, 8))

        self.lbl_word = tk.Label(
            self.win_word,
            text="—",
            font=word_font,
            fg="#58a6ff",
            bg="#0d1117",
            wraplength=680,
        )
        self.lbl_word.pack(expand=True)

        tk.Label(
            self.win_word,
            text="Step on the red to clear your canvas",
            font=small,
            fg="#f85149",
            bg="#0d1117",
            wraplength=680,
        ).pack(pady=(8, 4))

        self.lbl_word_guess_alert = tk.Label(
            self.win_word,
            text="",
            font=small,
            fg="#f85149",
            bg="#0d1117",
            wraplength=680,
        )
        self.lbl_word_guess_alert.pack(pady=(4, 8))

        tk.Label(self.win_word, text="Scores", font=hdr_font, fg="#8b949e", bg="#0d1117").pack(pady=(8, 4))
        self.lbl_word_scores = tk.Label(self.win_word, text="", font=small, fg="#c9d1d9", bg="#0d1117")
        self.lbl_word_scores.pack(pady=(0, 20))

        self.win_key = tk.Toplevel(root)
        self.win_key.title("GuessTheGame — Keyboard")
        self.win_key.geometry("520x420+100+440")
        self.win_key.configure(bg="#161b22")

        tk.Label(
            self.win_key,
            text="Guessers: press your team button, type the word, then Enter (keyboard or button).",
            font=small,
            fg="#c9d1d9",
            bg="#161b22",
            wraplength=480,
        ).pack(pady=(16, 8))

        self.status = tk.Label(self.win_key, text="", font=small, fg="#f0883e", bg="#161b22")
        self.status.pack(pady=(0, 12))

        team_row = tk.Frame(self.win_key, bg="#161b22")
        team_row.pack(pady=4)
        self.btn_guess_t1 = tk.Button(
            team_row,
            text="Guess Team 1",
            width=14,
            command=lambda: self._arm(1),
            bg="#238636",
            fg="white",
            activebackground="#2ea043",
        )
        self.btn_guess_t1.pack(side=tk.LEFT, padx=6)
        self.btn_guess_t2 = tk.Button(
            team_row,
            text="Guess Team 2",
            width=14,
            command=lambda: self._arm(2),
            bg="#1f6feb",
            fg="white",
            activebackground="#388bfd",
        )
        self._sync_team2_button_visibility()

        self.entry = tk.Entry(self.win_key, font=("Segoe UI", 18), width=28, bg="#0d1117", fg="#f0f6fc", insertbackground="white")
        self.entry.pack(pady=12, ipady=6)
        self.entry.bind("<Return>", lambda e: self._submit())

        btn_row = tk.Frame(self.win_key, bg="#161b22")
        btn_row.pack(pady=8)
        tk.Button(
            btn_row,
            text="Enter",
            width=10,
            command=self._submit,
            bg="#21262d",
            fg="#f0f6fc",
        ).pack()

        tk.Label(self.win_key, text="Scores", font=hdr_font, fg="#f0f6fc", bg="#161b22").pack(pady=(16, 4))
        self.lbl_scores = tk.Label(self.win_key, text="", font=small, fg="#c9d1d9", bg="#161b22")
        self.lbl_scores.pack()

        self.win_word.protocol("WM_DELETE_WINDOW", self._quit)
        self.win_key.protocol("WM_DELETE_WINDOW", self._quit)
        self._tick()

    def _arm(self, team: int) -> None:
        with self.game.lock:
            if self.game.active_guess_team is not None:
                return
        self.game.arm_guess(team)
        self.entry.delete(0, tk.END)
        self.entry.focus_set()
        self._sync_team2_button_visibility()
        self._sync_guess_buttons()
        self.status.config(text=f"Team {team} is guessing — type and press Enter.")

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
            armed = self.game.active_guess_team
            two_player = self.game.num_players < 4
        if two_player:
            self.btn_guess_t1.config(state=tk.NORMAL)
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

    def _quit(self) -> None:
        self.game.running = False
        self.root.quit()

    def _tick(self) -> None:
        if not self.root.winfo_exists():
            return
        with self.game.lock:
            w = self.game.current_word if self.game.state == "PLAYING" else "—"
            s1, s2 = self.game.team_scores
            armed = self.game.active_guess_team
        self.lbl_word.config(text=w.upper() if w != "—" else "Start from console: start 2  or  start 4")
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
        self.root.after(120, self._tick)


def _read_nav_key() -> str:
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
                    return "quit"
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
    return "quit"


def _print_menu_block(title: str, options: List[str], idx: int) -> int:
    n = 0
    print(title)
    n += 1
    print("Press : ↑ / ↓  then Enter")
    n += 1
    print()
    n += 1
    for i, opt in enumerate(options):
        prefix = " > " if i == idx else "   "
        print(f"{prefix}{opt}")
        n += 1
    return n


def terminal_menu_select(title: str, options: List[str]) -> int:
    if not options:
        raise ValueError("empty menu")
    idx = 0
    while True:
        _print_menu_block(title, options, idx)
        key = _read_nav_key()
        if key == "up":
            idx = (idx - 1) % len(options)
        elif key == "down":
            idx = (idx + 1) % len(options)
        elif key == "enter":
            return idx
        elif key == "quit":
            raise KeyboardInterrupt


def read_command_line(prompt: str) -> str:
    return input(prompt).strip()


def main() -> None:
    print("GuessTheGame — matrix draw + dual-screen guess")
    print(f"UDP recv port {UDP_LISTEN_PORT} (mat input; Simulator fans out to 7801+7802 by default)")
    print("Commands: start 2 | start 4 | next | scores | unlock | quit")
    try:
        pi = terminal_menu_select(
            "Players",
            [
                "2 players (1 mat drawer + 1 keyboard)",
                "4 players (2 drawers: top/bottom split + 2 keyboard)",
            ],
        )
        num_players = 2 if pi == 0 else 4
    except KeyboardInterrupt:
        print("\nCancelled.")
        return

    game = GuessTheGame()
    game.start_game(num_players)

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

    threading.Thread(target=console_loop, daemon=True).start()

    try:
        root.mainloop()
    finally:
        net.running = False
        print("Exiting.")


if __name__ == "__main__":
    main()
