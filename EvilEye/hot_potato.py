"""
hot_potato.py – Hot Potato Team Game for Evil Eye LED hardware.

Mechanics
─────────
• 2-minute game clock.
• Hot potato (one red LED) appears on the current holder's wall(s).
• Holder has 5–10 s to press it → +1 pt, potato passes to a random other team.
• Fail to press in time → −1 pt, potato passes anyway.
• LEDs flicker faster as the game clock runs down (< 30 s).
• When time's up, whoever holds the potato loses HALF their score.

Wall assignment
───────────────
• 2 teams  → A: walls 1+2,  B: walls 3+4
• 3 teams  → A: wall 1,     B: wall 2,  C: walls 3+4
• 4 teams  → A: wall 1,     B: wall 2,  C: wall 3,  D: wall 4

Run:  python hot_potato.py

LED colours in code are logical (R, G, B). UDP frames use GRB via Controller.logical_rgb_to_wire_grb.
"""

import os
import sys
import math
import random
import threading
import time
import tkinter as tk

# ── Import LightService from sibling Controller.py ───────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import (
    LightService,
    load_config,
    logical_rgb_to_wire_grb,
    receiver_bind_ip_from_config,
    save_config,
    NUM_CHANNELS,
    LEDS_PER_CHANNEL,
)

assert logical_rgb_to_wire_grb(1, 2, 3) == (2, 1, 3)

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
MAX_TEAMS    = 4
MIN_TEAMS    = 2
EYE_LED      = 0
BUTTONS      = list(range(1, 11))     # LED indices 1-10
GAME_SECONDS = 120                    # 2-minute game

# Wall channels per team index, per num_teams
WALL_MAP = {
    2: {0: [1, 2], 1: [3, 4]},
    3: {0: [1],    1: [2],    2: [3, 4]},
    4: {0: [1],    1: [2],    2: [3],    3: [4]},
}

# Logical RGB; LightService encodes GRB on the wire.
TEAM_COLORS_RGB = [
    (255,  60,   0),   # A – orange-red
    (  0, 100, 255),   # B – blue
    (  0, 210,  60),   # C – green
    (200,   0, 200),   # D – purple
]
TEAM_HEX = ["#ff3c00", "#0064ff", "#00d23c", "#c800c8"]
TEAM_NAMES_DEFAULT = ["TEAM A", "TEAM B", "TEAM C", "TEAM D"]

# Number of buttons that must be pressed to pass the potato
TOUCHES_NEEDED = {"easy": 1, "medium": 2, "hard": 3}

# Logical RGB for set_led(...)
RED    = (255,   0,   0)
GREEN  = (  0, 255,   0)
YELLOW = (255, 200,   0)
WHITE  = (255, 255, 255)
OFF    = (  0,   0,   0)

# Game states
S_SETUP   = "setup"
S_ACTIVE  = "active"
S_GAMEOVER = "gameover"

# ─────────────────────────────────────────────────────────────────────────────
# UI colour / font constants
# ─────────────────────────────────────────────────────────────────────────────
BG_DARK  = "#0f0f0f"
BG_MID   = "#1e1e1e"
BG_PANEL = "#252525"
FG_MAIN  = "#f0f0f0"
FG_DIM   = "#555555"
FG_GREEN = "#00ff88"
FG_RED   = "#ff4444"
FG_GOLD  = "#ffd700"

FONT_SM = ("Consolas", 12, "bold")
FONT_XS = ("Consolas", 10)


# ─────────────────────────────────────────────────────────────────────────────
# UI helpers  (Label-based buttons work on macOS where tk.Button ignores bg)
# ─────────────────────────────────────────────────────────────────────────────
def _make_lbl_btn(parent, text, command, bg, fg=FG_MAIN, **kw):
    hover_bg = kw.pop("hover_bg", "#555")
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=kw.pop("font", FONT_SM),
                   padx=kw.pop("padx", 20), pady=kw.pop("pady", 10),
                   cursor="hand2", **kw)
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>",    lambda e: lbl.configure(bg=hover_bg))
    lbl.bind("<Leave>",    lambda e: lbl.configure(bg=bg))
    return lbl


def _seg_btn(parent, text, var, value, **kw):
    active_bg   = kw.get("active_bg", "#ff3c00")
    inactive_bg = "#383838"

    lbl = tk.Label(parent, text=text,
                   bg=inactive_bg, fg=FG_MAIN,
                   font=kw.get("font", FONT_SM),
                   width=kw.get("width", 6),
                   height=kw.get("height", 1),
                   cursor="hand2")

    def _refresh(*_):
        lbl.configure(bg=active_bg if var.get() == value else inactive_bg)

    lbl.bind("<Button-1>", lambda e: var.set(value))
    lbl.bind("<Enter>", lambda e: lbl.configure(
        bg=active_bg if var.get() == value else "#4a4a4a"))
    lbl.bind("<Leave>", lambda e: _refresh())
    var.trace_add("write", _refresh)
    _refresh()
    return lbl


# ─────────────────────────────────────────────────────────────────────────────
# Game Engine
# ─────────────────────────────────────────────────────────────────────────────
class HotPotatoGame:
    """
    State machine that runs in a background thread.
    All UI feedback via on_event(name, dict) – marshalled to main thread by caller.
    set_led(..., r, g, b) is logical RGB; frames use GRB (build_frame_data).
    """

    def __init__(self, service: LightService, on_event):
        self._svc    = service
        self._notify = on_event
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thr    = None

        # Config
        self.num_teams  = 2
        self.difficulty = "medium"
        self.team_names = list(TEAM_NAMES_DEFAULT)

        # Runtime
        self.state           = S_SETUP
        self.scores          = [0] * MAX_TEAMS
        self.potato_team     = 0          # index of team currently holding potato
        self.potato_positions = []        # [(ch, led), …] all lit buttons
        self.game_left        = GAME_SECONDS
        self._remaining       = []        # positions not yet pressed

    # ── Public API ────────────────────────────────────────────────────────────
    def start_game(self, num_teams, difficulty="medium", team_names=None):
        self.stop_game()
        self.num_teams   = max(MIN_TEAMS, min(MAX_TEAMS, num_teams))
        self.difficulty  = difficulty
        if team_names:
            for i, n in enumerate(team_names[:MAX_TEAMS]):
                self.team_names[i] = n.strip() or TEAM_NAMES_DEFAULT[i]
        self.scores           = [0] * MAX_TEAMS
        self.potato_team      = random.randint(0, self.num_teams - 1)
        self.potato_positions = []
        self.game_left        = GAME_SECONDS
        self._remaining       = []
        self.state            = S_ACTIVE

        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop_game(self):
        self._stop.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        self._svc.all_off()
        self.state = S_SETUP

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        """Receiver thread → called on every state change."""
        if not is_triggered or self.state != S_ACTIVE:
            return
        walls = WALL_MAP[self.num_teams].get(self.potato_team, [])
        if ch not in walls:
            return
        with self._lock:
            if (ch, led) in self._remaining:
                self._remaining.remove((ch, led))
                self._svc.set_led(ch, led, *GREEN)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _walls(self, team):
        return WALL_MAP[self.num_teams].get(team, [team + 1])

    def _spawn_potato(self):
        """Spawn N red buttons on the holder's wall based on difficulty."""
        walls = self._walls(self.potato_team)
        ch    = random.choice(walls)
        n     = TOUCHES_NEEDED[self.difficulty]
        leds  = random.sample(BUTTONS, n)
        self.potato_positions = [(ch, l) for l in leds]
        with self._lock:
            self._remaining = list(self.potato_positions)
        for (c, l) in self.potato_positions:
            self._svc.set_led(c, l, *RED)
        r, g, b = TEAM_COLORS_RGB[self.potato_team]
        for w in walls:
            self._svc.set_led(w, EYE_LED, r, g, b)

    def _clear_potato(self):
        for (c, l) in self.potato_positions:
            self._svc.set_led(c, l, *OFF)
        walls = self._walls(self.potato_team)
        for w in walls:
            self._svc.set_led(w, EYE_LED, *OFF)
        self.potato_positions = []
        with self._lock:
            self._remaining = []

    def _set_potato_color(self, r, g, b):
        with self._lock:
            positions = list(self._remaining)
        for (c, l) in positions:
            self._svc.set_led(c, l, r, g, b)

    def _flash_pass(self, hit: bool):
        """Brief visual feedback on the potato wall after press / timeout."""
        walls = self._walls(self.potato_team)
        color = GREEN if hit else RED
        for w in walls:
            for led in BUTTONS:
                self._svc.set_led(w, led, *color)
        time.sleep(0.4)
        for w in walls:
            for led in BUTTONS:
                self._svc.set_led(w, led, *OFF)
        time.sleep(0.15)

    # ── Main loop ─────────────────────────────────────────────────────────────
    def _loop(self):
        game_end = time.time() + GAME_SECONDS

        self._notify("game_started", {
            "scores": list(self.scores[:self.num_teams]),
            "names":  list(self.team_names[:self.num_teams]),
        })

        while not self._stop.is_set():
            now = time.time()
            self.game_left = max(0.0, game_end - now)

            if self.game_left <= 0:
                break

            # ── Spawn potato for current holder ───────────────────────────────
            self._spawn_potato()
            turn_time = random.uniform(5.0, 10.0)
            deadline  = now + turn_time

            self._notify("potato_moved", {
                "team":      self.potato_team,
                "name":      self.team_names[self.potato_team],
                "color":     TEAM_HEX[self.potato_team],
                "turn_time": turn_time,
                "touches":   TOUCHES_NEEDED[self.difficulty],
                "scores":    list(self.scores[:self.num_teams]),
                "game_left": self.game_left,
            })

            # ── Tick until all pressed or turn expires ────────────────────────
            pressed = False
            while not self._stop.is_set():
                now            = time.time()
                self.game_left = max(0.0, game_end - now)
                turn_left      = max(0.0, deadline - now)

                with self._lock:
                    remaining_count = len(self._remaining)

                # ── Flicker unpressed buttons ─────────────────────────────────
                if self.game_left < 30:
                    rate  = 2.0 + (30 - self.game_left) * 0.4   # 2–14 Hz
                    phase = (now * rate) % 1.0
                    self._set_potato_color(*(RED if phase < 0.5 else OFF))
                elif turn_left < 2.0:
                    phase = (now * 5) % 1.0
                    self._set_potato_color(*(RED if phase < 0.5 else YELLOW))
                else:
                    self._set_potato_color(*RED)

                self._notify("tick", {
                    "game_left": self.game_left,
                    "turn_left": turn_left,
                    "remaining": remaining_count,
                    "team":      self.potato_team,
                    "scores":    list(self.scores[:self.num_teams]),
                })

                if remaining_count == 0:
                    pressed = True
                    break
                if turn_left <= 0 or self.game_left <= 0:
                    break

                time.sleep(0.05)

            # ── Resolve turn ──────────────────────────────────────────────────
            self._clear_potato()

            if pressed:
                self.scores[self.potato_team] = max(0, self.scores[self.potato_team] + 1)
                self._flash_pass(hit=True)
                result = "passed"
            else:
                self.scores[self.potato_team] = max(0, self.scores[self.potato_team] - 1)
                self._flash_pass(hit=False)
                result = "timeout"

            self._notify("turn_result", {
                "team":   self.potato_team,
                "name":   self.team_names[self.potato_team],
                "result": result,
                "scores": list(self.scores[:self.num_teams]),
            })

            if self.game_left <= 0:
                break

            # Pass potato to a random different team
            others = [t for t in range(self.num_teams) if t != self.potato_team]
            self.potato_team = random.choice(others)
            time.sleep(0.1)

        # ── Game over ─────────────────────────────────────────────────────────
        if not self._stop.is_set():
            self._do_game_over()

    def _do_game_over(self):
        holder = self.potato_team
        penalty = self.scores[holder] // 2
        self.scores[holder] = self.scores[holder] - penalty

        winner = max(range(self.num_teams), key=lambda i: self.scores[i])

        # Strobe winner's walls, flash loser's walls red
        ch_win  = self._walls(winner)
        ch_lose = self._walls(holder)
        w_rgb   = TEAM_COLORS_RGB[winner]

        for _ in range(5):
            if self._stop.is_set(): break
            for w in ch_win:
                for led in range(LEDS_PER_CHANNEL):
                    self._svc.set_led(w, led, *w_rgb)
            time.sleep(0.3)
            self._svc.all_off()
            time.sleep(0.2)
        for w in ch_win:
            for led in range(LEDS_PER_CHANNEL):
                self._svc.set_led(w, led, *w_rgb)

        self._notify("game_over", {
            "winner":  winner,
            "holder":  holder,
            "penalty": penalty,
            "w_name":  self.team_names[winner],
            "h_name":  self.team_names[holder],
            "scores":  list(self.scores[:self.num_teams]),
        })
        self.state = S_GAMEOVER


# ─────────────────────────────────────────────────────────────────────────────
# Main Application
# ─────────────────────────────────────────────────────────────────────────────
class HotPotatoApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Hot Potato – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(860, 640)
        self.bind("<F11>", lambda e: self.attributes("-fullscreen",
                                                      not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        # ── Service ────────────────────────────────────────────────────────────
        self._cfg     = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1")
        if ip:
            self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._service.set_recv_port(self._cfg.get("receiver_port", 7800))
        self._service.set_bind_ip(receiver_bind_ip_from_config(self._cfg))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        # ── Game ───────────────────────────────────────────────────────────────
        self._game = HotPotatoGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        # ── Setup vars ────────────────────────────────────────────────────────
        self._v_teams      = tk.IntVar(value=2)
        self._v_difficulty = tk.StringVar(value="medium")
        self._v_team_names = [tk.StringVar(value=TEAM_NAMES_DEFAULT[i]) for i in range(MAX_TEAMS)]
        self._v_device_ip  = tk.StringVar(value=ip or "127.0.0.1")

        # ── Screens ───────────────────────────────────────────────────────────
        self._frame_setup = tk.Frame(self, bg=BG_DARK)
        self._frame_game  = tk.Frame(self, bg=BG_DARK)
        for frm in (self._frame_setup, self._frame_game):
            frm.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_setup_screen()
        self._build_game_screen()
        self._show_setup()

    # ── Screen switching ──────────────────────────────────────────────────────
    def _show_setup(self): self._frame_setup.lift()
    def _show_game(self):  self._frame_game.lift()

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_setup_screen(self):
        f = self._frame_setup

        # Bottom elements first so they're never hidden by expanding content
        self._status_lbl = tk.Label(f, text="Ready", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        _make_lbl_btn(f, "▶   START GAME", self._start_game,
                      bg="#ff3c00", fg="white",
                      font=("Consolas", 20, "bold"),
                      padx=50, pady=18,
                      hover_bg="#cc3000").pack(side=tk.BOTTOM, pady=(6, 6))

        # Title
        tk.Label(f, text="HOT POTATO", bg=BG_DARK, fg="#ff3c00",
                 font=("Consolas", 36, "bold")).pack(pady=(20, 2))
        tk.Label(f, text="Team Mode · Evil Eye  ·  2 min game", bg=BG_DARK, fg=FG_DIM,
                 font=FONT_SM).pack(pady=(0, 10))

        # Scrollable content area
        content = tk.Frame(f, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)

        row = 0

        # ── Number of teams ───────────────────────────────────────────────────
        self._setup_lbl(content, "NUMBER OF TEAMS", row); row += 1
        r = tk.Frame(content, bg=BG_DARK)
        r.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        for n in range(2, 5):
            _seg_btn(r, str(n), self._v_teams, n,
                     active_bg=TEAM_HEX[n - 2], width=5, height=2,
                     font=("Consolas", 18, "bold")).pack(side=tk.LEFT, padx=6)

        # Wall layout info (dynamic)
        self._lbl_wall_info = tk.Label(content, text="", bg=BG_DARK, fg=FG_DIM,
                                       font=("Consolas", 9))
        self._lbl_wall_info.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        self._v_teams.trace_add("write", self._refresh_wall_info)
        self._refresh_wall_info()

        # ── Team names ────────────────────────────────────────────────────────
        self._setup_lbl(content, "TEAM NAMES", row); row += 1
        names_frame = tk.Frame(content, bg=BG_DARK)
        names_frame.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        self._name_entries = []
        for i in range(MAX_TEAMS):
            col = TEAM_HEX[i]
            tk.Label(names_frame, text=f"{chr(65+i)}:", bg=BG_DARK, fg=col,
                     font=FONT_SM).grid(row=i // 2, column=(i % 2) * 2,
                                        padx=(10, 4), pady=4, sticky="e")
            e = tk.Entry(names_frame, textvariable=self._v_team_names[i],
                         width=12, bg=BG_PANEL, fg=FG_MAIN,
                         font=("Consolas", 13), insertbackground="white",
                         relief="flat", highlightthickness=1,
                         highlightbackground=col, highlightcolor=col)
            e.grid(row=i // 2, column=(i % 2) * 2 + 1, padx=(0, 20), pady=4)
            self._name_entries.append(e)

        # ── Difficulty ────────────────────────────────────────────────────────
        self._setup_lbl(content, "DIFFICULTY  (buttons to press per turn)", row); row += 1
        diff_row = tk.Frame(content, bg=BG_DARK)
        diff_row.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        for key, label, col, hint in [
            ("easy",   "EASY\n1 button",   "#00c832", ""),
            ("medium", "MEDIUM\n2 buttons","#ffd700", ""),
            ("hard",   "HARD\n3 buttons",  "#ff3c00", ""),
        ]:
            _seg_btn(diff_row, label, self._v_difficulty, key,
                     active_bg=col, width=10, height=2,
                     font=("Consolas", 10, "bold")).pack(side=tk.LEFT, padx=6)

        # ── Device IP ─────────────────────────────────────────────────────────
        self._setup_lbl(content, "DEVICE IP", row); row += 1
        ip_row = tk.Frame(content, bg=BG_DARK)
        ip_row.grid(row=row, column=0, columnspan=2, pady=(0, 14)); row += 1
        tk.Entry(ip_row, textvariable=self._v_device_ip,
                 width=20, bg=BG_PANEL, fg=FG_MAIN,
                 font=("Consolas", 13), insertbackground="white",
                 relief="flat", highlightthickness=1,
                 highlightbackground="#444").pack(side=tk.LEFT, padx=6)
        _make_lbl_btn(ip_row, "APPLY", self._apply_ip,
                      bg="#444", padx=12, pady=5,
                      font=FONT_XS, hover_bg="#666").pack(side=tk.LEFT, padx=4)

    def _setup_lbl(self, parent, text, row):
        tk.Label(parent, text=text, bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).grid(
            row=row, column=0, columnspan=2, pady=(6, 2))

    def _refresh_wall_info(self, *_):
        n = self._v_teams.get()
        mapping = WALL_MAP.get(n, {})
        parts = []
        for t, walls in sorted(mapping.items()):
            wstr = "+".join(f"Wall{w}" for w in walls)
            parts.append(f"{TEAM_NAMES_DEFAULT[t][:6]}→{wstr}")
        self._lbl_wall_info.configure(text="  |  ".join(parts))

    # ─────────────────────────────────────────────────────────────────────────
    # GAME SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_game_screen(self):
        f = self._frame_game

        # Bottom toolbar (pack first)
        btm = tk.Frame(f, bg=BG_MID, pady=8)
        btm.pack(side=tk.BOTTOM, fill=tk.X)
        _make_lbl_btn(btm, "⚙ Setup", self._go_setup,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=8)
        _make_lbl_btn(btm, "⏹ Stop", self._stop_game,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=4)
        self._game_status = tk.Label(btm, text="", bg=BG_MID, fg=FG_DIM, font=FONT_XS)
        self._game_status.pack(side=tk.RIGHT, padx=12)

        # ── Score bar ─────────────────────────────────────────────────────────
        self._score_bar = tk.Frame(f, bg=BG_MID)
        self._score_bar.pack(fill=tk.X, pady=(0, 4))
        self._score_panels = []
        for i in range(MAX_TEAMS):
            pf = tk.Frame(self._score_bar, bg=BG_PANEL, padx=16, pady=6,
                          highlightthickness=0)
            nl = tk.Label(pf, text=TEAM_NAMES_DEFAULT[i], bg=BG_PANEL,
                          fg=TEAM_HEX[i], font=("Consolas", 10, "bold"))
            nl.pack()
            sl = tk.Label(pf, text="0", bg=BG_PANEL, fg=FG_MAIN,
                          font=("Consolas", 20, "bold"))
            sl.pack()
            self._score_panels.append((pf, nl, sl))

        # ── Potato holder banner ───────────────────────────────────────────────
        self._lbl_holder = tk.Label(f, text="", bg=BG_DARK, fg=FG_MAIN,
                                    font=("Consolas", 26, "bold"))
        self._lbl_holder.pack(pady=(8, 2))

        self._lbl_action = tk.Label(f, text="", bg=BG_DARK, fg=FG_DIM,
                                    font=("Consolas", 13))
        self._lbl_action.pack()

        # ── Game clock ────────────────────────────────────────────────────────
        clock_frame = tk.Frame(f, bg=BG_DARK)
        clock_frame.pack(expand=True)

        self._lbl_clock = tk.Label(clock_frame, text="2:00", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 72, "bold"))
        self._lbl_clock.pack()

        self._lbl_turn = tk.Label(clock_frame, text="", bg=BG_DARK, fg=FG_DIM,
                                  font=("Consolas", 14))
        self._lbl_turn.pack(pady=(0, 8))

        # ── Turn timer bar (dots) ─────────────────────────────────────────────
        self._turn_bar = tk.Canvas(f, bg=BG_PANEL, height=10,
                                   highlightthickness=0)
        self._turn_bar.pack(fill=tk.X, padx=60, pady=(0, 12))
        self._turn_bar_pct = 1.0
        self._turn_bar_max = 10.0

    # ── Score bar update ──────────────────────────────────────────────────────
    def _update_scores(self, scores, num_teams, potato_team):
        for i, (pf, nl, sl) in enumerate(self._score_panels):
            pf.pack_forget()
        for i in range(num_teams):
            pf, nl, sl = self._score_panels[i]
            nl.configure(text=self._game.team_names[i], fg=TEAM_HEX[i])
            sl.configure(text=str(scores[i]))
            is_holder = (i == potato_team)
            pf.configure(
                bg=BG_PANEL,
                highlightbackground=TEAM_HEX[i] if is_holder else "#333",
                highlightthickness=3 if is_holder else 0,
                highlightcolor=TEAM_HEX[i],
            )
            pf.pack(side=tk.LEFT, padx=6, pady=6, expand=True)

    def _update_turn_bar(self, turn_left, turn_max):
        pct = max(0.0, turn_left / turn_max)
        w   = self._turn_bar.winfo_width() or 600
        self._turn_bar.delete("all")
        self._turn_bar.create_rectangle(0, 0, w, 10, fill=BG_PANEL, outline="")
        bw = int(w * pct)
        if bw > 0:
            col = FG_GREEN if pct > 0.5 else (FG_GOLD if pct > 0.25 else FG_RED)
            self._turn_bar.create_rectangle(0, 0, bw, 10, fill=col, outline="")

    # ── Game event dispatcher ─────────────────────────────────────────────────
    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "game_started":
            self._turn_bar_max = 10.0
            self._update_scores(data["scores"], self._game.num_teams, self._game.potato_team)
            self._lbl_action.configure(text="Game starting…", fg=FG_DIM)

        elif event == "potato_moved":
            self._turn_bar_max = data["turn_time"]
            n = data["touches"]
            self._lbl_holder.configure(
                text=f"🥔  {data['name']}  has the potato",
                fg=data["color"])
            self._lbl_action.configure(
                text=f"Press {'all ' + str(n) + ' red buttons' if n > 1 else 'the red button'} to pass!",
                fg=FG_MAIN)
            self._update_scores(data["scores"], self._game.num_teams, data["team"])

        elif event == "tick":
            gl  = data["game_left"]
            tl  = data.get("turn_left", 0)
            rem = data.get("remaining", 0)
            mm, ss = divmod(int(gl), 60)
            self._lbl_clock.configure(
                text=f"{mm}:{ss:02d}",
                fg=(FG_MAIN if gl > 60 else FG_GOLD if gl > 30 else FG_RED))
            turn_txt = f"Turn: {tl:.1f}s"
            if rem > 0:
                turn_txt += f"  ·  {rem} press{'es' if rem != 1 else ''} left"
            self._lbl_turn.configure(
                text=turn_txt,
                fg=(FG_GREEN if tl > 3 else FG_GOLD if tl > 1 else FG_RED))
            self._update_turn_bar(tl, self._turn_bar_max)

        elif event == "turn_result":
            if data["result"] == "passed":
                self._lbl_action.configure(text=f"✔ Passed!  +1 pt", fg=FG_GREEN)
            else:
                self._lbl_action.configure(
                    text=f"✖ {data['name']} timed out  −1 pt", fg=FG_RED)
            self._update_scores(data["scores"], self._game.num_teams,
                                self._game.potato_team)

        elif event == "game_over":
            mm, ss = 0, 0
            self._lbl_clock.configure(text="0:00", fg=FG_RED)
            self._lbl_turn.configure(text="")
            self._lbl_holder.configure(
                text=f"🏆  {data['w_name']}  wins!",
                fg=TEAM_HEX[data["winner"]])
            penalty_msg = (
                f"🥔 {data['h_name']} held the potato → −{data['penalty']} pts"
                if data["penalty"] > 0 else
                f"🥔 {data['h_name']} held the potato (0 pts, no penalty)"
            )
            self._lbl_action.configure(text=penalty_msg, fg=FG_GOLD)
            self._update_scores(data["scores"], self._game.num_teams, data["holder"])
            self._update_turn_bar(0, 1)

    # ── Controls ──────────────────────────────────────────────────────────────
    def _apply_ip(self):
        ip = self._v_device_ip.get().strip()
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start_game(self):
        self._apply_ip()
        names = [v.get() for v in self._v_team_names]
        self._game.start_game(
            num_teams=self._v_teams.get(),
            difficulty=self._v_difficulty.get(),
            team_names=names,
        )
        self._lbl_clock.configure(text="2:00", fg=FG_MAIN)
        self._lbl_holder.configure(text="", fg=FG_MAIN)
        self._lbl_action.configure(text="", fg=FG_DIM)
        self._lbl_turn.configure(text="")
        self._update_scores([0] * self._v_teams.get(),
                            self._v_teams.get(), -1)
        self._show_game()

    def _stop_game(self):
        self._game.stop_game()
        self._lbl_action.configure(text="Game stopped.", fg=FG_DIM)
        self._lbl_turn.configure(text="")

    def _go_setup(self):
        self._game.stop_game()
        self._show_setup()

    def _set_status(self, msg):
        try:
            self._status_lbl.configure(text=msg)
            self._game_status.configure(text=msg)
        except tk.TclError:
            pass


# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    HotPotatoApp().mainloop()
