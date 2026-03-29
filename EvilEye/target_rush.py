"""
target_rush.py – Target Rush Team Game for Evil Eye LED hardware.

Mechanics
─────────
• Turn-based: teams take turns pressing lit red targets on their own wall(s).
• Press all targets before the timer → no life lost, difficulty increases.
• Fail → lose 1 life (shown as ● dots).  3 lives per team.
• Last team with lives remaining wins.
• Difficulty increases as total hits grow: more simultaneous targets, less time.

Wall assignment
───────────────
• 2 teams  → option: 1 wall each  OR  2 walls each (A:1+2 / B:3+4)
• 3 teams  → A: wall 1,  B: wall 2,  C: walls 3+4
• 4 teams  → one wall each

Run:  python target_rush.py
"""

import os, sys, random, threading, time
import tkinter as tk

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import LightService, load_config, save_config, LEDS_PER_CHANNEL

MAX_TEAMS = 4
MIN_TEAMS = 2
EYE_LED   = 0
BUTTONS   = list(range(1, 11))
LIVES     = 3

# Base wall maps (2-team 1-wall variant built dynamically)
WALL_MAP = {
    2: {0: [1, 2], 1: [3, 4]},          # 2 walls each (default)
    3: {0: [1],    1: [2],    2: [3, 4]},
    4: {0: [1],    1: [2],    2: [3],    3: [4]},
}
WALL_MAP_2_ONE = {0: [1], 1: [2]}        # 2 teams, 1 wall each

DIFF_PRESETS = {
    "easy":   {"start_targets": 1, "start_time": 5.0, "min_time": 2.5, "step_hits": 6, "max_targets": 2},
    "medium": {"start_targets": 1, "start_time": 3.5, "min_time": 1.5, "step_hits": 4, "max_targets": 3},
    "hard":   {"start_targets": 2, "start_time": 2.5, "min_time": 1.0, "step_hits": 3, "max_targets": 3},
}

TEAM_COLORS_RGB = [(255,60,0),(0,100,255),(0,210,60),(200,0,200)]
TEAM_HEX        = ["#ff3c00","#0064ff","#00d23c","#c800c8"]
TEAM_NAMES_DEF  = ["TEAM A","TEAM B","TEAM C","TEAM D"]

RED   = (255,0,0)
GREEN = (0,255,0)
OFF   = (0,0,0)

S_SETUP = "setup"
S_TRANS = "transition"
S_PLAY  = "playing"
S_HIT   = "hit"
S_MISS  = "miss"
S_OVER  = "gameover"

# ── UI colours / fonts ────────────────────────────────────────────────────────
BG_DARK  = "#0f0f0f"
BG_MID   = "#1e1e1e"
BG_PANEL = "#252525"
FG_MAIN  = "#f0f0f0"
FG_DIM   = "#555555"
FG_GREEN = "#00ff88"
FG_RED   = "#ff4444"
FG_GOLD  = "#ffd700"
FONT_SM  = ("Consolas", 12, "bold")
FONT_XS  = ("Consolas", 10)


def _make_lbl_btn(parent, text, command, bg, fg=FG_MAIN, **kw):
    hover = kw.pop("hover_bg", "#555")
    lbl = tk.Label(parent, text=text, bg=bg, fg=fg,
                   font=kw.pop("font", FONT_SM),
                   padx=kw.pop("padx", 20), pady=kw.pop("pady", 10),
                   cursor="hand2", **kw)
    lbl.bind("<Button-1>", lambda e: command())
    lbl.bind("<Enter>",    lambda e: lbl.configure(bg=hover))
    lbl.bind("<Leave>",    lambda e: lbl.configure(bg=bg))
    return lbl


def _seg_btn(parent, text, var, value, **kw):
    active_bg = kw.get("active_bg", "#ff3c00")
    lbl = tk.Label(parent, text=text, bg="#383838", fg=FG_MAIN,
                   font=kw.get("font", FONT_SM),
                   width=kw.get("width", 6), height=kw.get("height", 1),
                   cursor="hand2")

    def _refresh(*_):
        lbl.configure(bg=active_bg if var.get() == value else "#383838")

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
class TargetRushGame:
    def __init__(self, service: LightService, on_event):
        self._svc    = service
        self._notify = on_event
        self._lock   = threading.Lock()
        self._stop   = threading.Event()
        self._thr    = None

        self.num_teams   = 2
        self.difficulty  = "medium"
        self.team_names  = list(TEAM_NAMES_DEF)
        self.wall_map    = dict(WALL_MAP[2])

        self.state       = S_SETUP
        self.lives       = [LIVES] * MAX_TEAMS   # remaining lives per team
        self.scores      = [0] * MAX_TEAMS       # successful hits (display only)
        self.active_team = 0
        self.targets     = []
        self.time_left   = 0.0
        self.total_hits  = 0

    # ── Public ────────────────────────────────────────────────────────────────
    def start_game(self, num_teams, difficulty, team_names=None, two_wall=True):
        self.stop_game()
        self.num_teams   = max(MIN_TEAMS, min(MAX_TEAMS, num_teams))
        self.difficulty  = difficulty
        if team_names:
            for i, n in enumerate(team_names[:MAX_TEAMS]):
                self.team_names[i] = n.strip() or TEAM_NAMES_DEF[i]

        if self.num_teams == 2:
            self.wall_map = dict(WALL_MAP[2]) if two_wall else dict(WALL_MAP_2_ONE)
        else:
            self.wall_map = dict(WALL_MAP[self.num_teams])

        self.lives       = [LIVES] * MAX_TEAMS
        self.scores      = [0] * MAX_TEAMS
        self.active_team = 0
        self.total_hits  = 0
        self.targets     = []
        self.state       = S_TRANS

        self._stop.clear()
        self._thr = threading.Thread(target=self._loop, daemon=True)
        self._thr.start()

    def stop_game(self):
        self._stop.set()
        if self._thr and self._thr.is_alive():
            self._thr.join(timeout=2.0)
        self._svc.all_off()
        self.state   = S_SETUP
        self.targets = []

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        if not is_triggered or self.state != S_PLAY:
            return
        walls = self.wall_map.get(self.active_team, [])
        if ch not in walls:
            return
        with self._lock:
            if (ch, led) in self.targets:
                self.targets.remove((ch, led))
                self._svc.set_led(ch, led, *GREEN)
                self._notify("hit_partial", {"remaining": len(self.targets)})

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _active_teams(self):
        return [t for t in range(self.num_teams) if self.lives[t] > 0]

    def _next_team(self, from_team):
        t = from_team
        for _ in range(self.num_teams):
            t = (t + 1) % self.num_teams
            if self.lives[t] > 0:
                return t
        return from_team

    def _walls(self, team):
        return self.wall_map.get(team, [team + 1])

    def _spawn_targets(self):
        preset = DIFF_PRESETS[self.difficulty]
        steps  = self.total_hits // preset["step_hits"]
        n      = min(preset["max_targets"], preset["start_targets"] + steps)
        walls  = self._walls(self.active_team)
        chosen = []
        per_wall = max(1, n // len(walls))
        for w in walls:
            leds = random.sample(BUTTONS, min(per_wall, len(BUTTONS)))
            for led in leds:
                chosen.append((w, led))
            if len(chosen) >= n:
                break
        with self._lock:
            self.targets = chosen[:n]
        for (c, l) in self.targets:
            self._svc.set_led(c, l, *RED)

    def _show_eyes(self):
        for t in range(self.num_teams):
            r, g, b = TEAM_COLORS_RGB[t]
            for w in self._walls(t):
                if self.lives[t] == 0:
                    self._svc.set_led(w, EYE_LED, *OFF)
                elif t == self.active_team:
                    self._svc.set_led(w, EYE_LED, r, g, b)
                else:
                    self._svc.set_led(w, EYE_LED, r//5, g//5, b//5)

    def _level(self):
        return self.total_hits // DIFF_PRESETS[self.difficulty]["step_hits"] + 1

    # ── State machine ─────────────────────────────────────────────────────────
    def _loop(self):
        while not self._stop.is_set():
            if   self.state == S_TRANS: self._do_transition()
            elif self.state == S_PLAY:  self._do_playing()
            elif self.state == S_HIT:   self._do_hit()
            elif self.state == S_MISS:  self._do_miss()
            elif self.state == S_OVER:  self._do_over(); break
            else: break

    def _do_transition(self):
        team  = self.active_team
        walls = self._walls(team)
        t_rgb = TEAM_COLORS_RGB[team]
        self._show_eyes()
        for _ in range(3):
            if self._stop.is_set(): return
            for w in walls:
                self._svc.set_led(w, EYE_LED, *t_rgb)
            time.sleep(0.22)
            for w in walls:
                self._svc.set_led(w, EYE_LED, *OFF)
            time.sleep(0.18)
        for w in walls:
            self._svc.set_led(w, EYE_LED, *t_rgb)
        self._notify("team_turn", {
            "team":   team,
            "name":   self.team_names[team],
            "color":  TEAM_HEX[team],
            "lives":  list(self.lives[:self.num_teams]),
            "scores": list(self.scores[:self.num_teams]),
            "level":  self._level(),
        })
        time.sleep(0.4)
        self._spawn_targets()
        self.state = S_PLAY

    def _do_playing(self):
        preset     = DIFF_PRESETS[self.difficulty]
        steps      = self.total_hits // preset["step_hits"]
        time_limit = max(preset["min_time"], preset["start_time"] - steps * 0.3)
        deadline   = time.time() + time_limit
        self._notify("round_start", {
            "time_limit": time_limit,
            "n_targets":  len(self.targets),
            "level":      self._level(),
        })
        while not self._stop.is_set():
            self.time_left = max(0.0, deadline - time.time())
            with self._lock:
                remaining = len(self.targets)
            self._notify("tick", {"time_left": self.time_left, "remaining": remaining})
            if remaining == 0:
                self.state = S_HIT; return
            if self.time_left <= 0:
                self.state = S_MISS; return
            time.sleep(0.05)

    def _do_hit(self):
        team  = self.active_team
        walls = self._walls(team)
        self.scores[team] += 1
        self.total_hits   += 1
        for w in walls:
            for led in BUTTONS:
                self._svc.set_led(w, led, *GREEN)
            self._svc.set_led(w, EYE_LED, *TEAM_COLORS_RGB[team])
        self._notify("hit", {
            "team":   team,
            "name":   self.team_names[team],
            "lives":  list(self.lives[:self.num_teams]),
            "scores": list(self.scores[:self.num_teams]),
            "level":  self._level(),
        })
        time.sleep(0.9)
        for w in walls:
            for led in BUTTONS:
                self._svc.set_led(w, led, *OFF)
        self.active_team = self._next_team(team)
        self.state       = S_TRANS

    def _do_miss(self):
        team  = self.active_team
        walls = self._walls(team)
        with self._lock:
            missed = list(self.targets)
        for _ in range(4):
            if self._stop.is_set(): break
            for (tc, tl) in missed:
                self._svc.set_led(tc, tl, *RED)
            time.sleep(0.12)
            for (tc, tl) in missed:
                self._svc.set_led(tc, tl, *OFF)
            time.sleep(0.10)
        for w in walls:
            for led in BUTTONS:
                self._svc.set_led(w, led, *OFF)
        self.lives[team] = max(0, self.lives[team] - 1)
        with self._lock:
            self.targets = []

        eliminated = (self.lives[team] == 0)
        if eliminated:
            for w in walls:
                self._svc.set_led(w, EYE_LED, *OFF)

        self._notify("miss", {
            "team":       team,
            "name":       self.team_names[team],
            "lives":      list(self.lives[:self.num_teams]),
            "scores":     list(self.scores[:self.num_teams]),
            "eliminated": eliminated,
        })
        time.sleep(0.5)

        active = self._active_teams()
        if len(active) <= 1:
            self.state = S_OVER
            return
        self.active_team = self._next_team(team)
        self.state       = S_TRANS

    def _do_over(self):
        active = self._active_teams()
        winner = active[0] if active else max(range(self.num_teams),
                                              key=lambda i: self.lives[i])
        walls = self._walls(winner)
        w_rgb = TEAM_COLORS_RGB[winner]
        for _ in range(6):
            if self._stop.is_set(): break
            for w in walls:
                for led in range(LEDS_PER_CHANNEL):
                    self._svc.set_led(w, led, *w_rgb)
            time.sleep(0.28)
            self._svc.all_off()
            time.sleep(0.18)
        for w in walls:
            for led in range(LEDS_PER_CHANNEL):
                self._svc.set_led(w, led, *w_rgb)
        self._notify("game_over", {
            "winner": winner,
            "name":   self.team_names[winner],
            "lives":  list(self.lives[:self.num_teams]),
            "scores": list(self.scores[:self.num_teams]),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────
def _lives_str(n):
    return "●" * n + "○" * (LIVES - n)


class TargetRushApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Target Rush – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(860, 640)
        self.bind("<F11>", lambda e: self.attributes(
            "-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self._cfg     = load_config()
        self._service = LightService()
        self._service.on_status = lambda m: self.after(
            0, lambda msg=m: self._set_status(msg))

        ip = self._cfg.get("device_ip", "127.0.0.1")
        if ip:
            self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._service.set_recv_port(self._cfg.get("receiver_port", 7800))
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        self._game = TargetRushGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        self._v_teams      = tk.IntVar(value=2)
        self._v_difficulty = tk.StringVar(value="medium")
        self._v_two_wall   = tk.BooleanVar(value=True)   # 2-team layout
        self._v_team_names = [tk.StringVar(value=TEAM_NAMES_DEF[i]) for i in range(MAX_TEAMS)]
        self._v_device_ip  = tk.StringVar(value=ip or "127.0.0.1")
        self._turn_time_max = 5.0
        # Store last-used settings for restart
        self._last_settings = None

        self._frame_setup = tk.Frame(self, bg=BG_DARK)
        self._frame_game  = tk.Frame(self, bg=BG_DARK)
        for frm in (self._frame_setup, self._frame_game):
            frm.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_setup()
        self._build_game()
        self._show_setup()

    def _show_setup(self): self._frame_setup.lift()
    def _show_game(self):  self._frame_game.lift()

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────────────────────
    def _build_setup(self):
        f = self._frame_setup

        self._status_lbl = tk.Label(f, text="Ready", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        _make_lbl_btn(f, "▶   START GAME", self._start_game,
                      bg="#ff3c00", fg="white",
                      font=("Consolas", 20, "bold"),
                      padx=50, pady=18,
                      hover_bg="#cc3000").pack(side=tk.BOTTOM, pady=(6, 6))

        tk.Label(f, text="TARGET RUSH", bg=BG_DARK, fg="#ff3c00",
                 font=("Consolas", 36, "bold")).pack(pady=(20, 2))
        tk.Label(f, text="Turn-Based · 3 Lives · Last Team Standing",
                 bg=BG_DARK, fg=FG_DIM, font=FONT_SM).pack(pady=(0, 10))

        content = tk.Frame(f, bg=BG_DARK)
        content.pack(fill=tk.BOTH, expand=True)
        row = 0

        # Teams
        self._slbl(content, "NUMBER OF TEAMS", row); row += 1
        r = tk.Frame(content, bg=BG_DARK)
        r.grid(row=row, column=0, columnspan=2, pady=(0, 4)); row += 1
        for n in range(2, 5):
            _seg_btn(r, str(n), self._v_teams, n,
                     active_bg=TEAM_HEX[n-2], width=5, height=2,
                     font=("Consolas", 18, "bold")).pack(side=tk.LEFT, padx=6)

        # 2-team wall layout toggle (only visible when 2 teams selected)
        self._wall_frame = tk.Frame(content, bg=BG_DARK)
        self._wall_frame.grid(row=row, column=0, columnspan=2, pady=(0, 4)); row += 1
        tk.Label(self._wall_frame, text="2-TEAM LAYOUT", bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).pack()
        wall_row = tk.Frame(self._wall_frame, bg=BG_DARK)
        wall_row.pack()
        _seg_btn(wall_row, "1 wall each\n(Wall 1 / 2)", self._v_two_wall, False,
                 active_bg="#555", width=14, height=2, font=FONT_XS).pack(side=tk.LEFT, padx=4)
        _seg_btn(wall_row, "2 walls each\n(1+2 / 3+4)", self._v_two_wall, True,
                 active_bg="#555", width=14, height=2, font=FONT_XS).pack(side=tk.LEFT, padx=4)

        # Wall info label
        self._lbl_walls = tk.Label(content, text="", bg=BG_DARK, fg=FG_DIM,
                                   font=("Consolas", 9))
        self._lbl_walls.grid(row=row, column=0, columnspan=2, pady=(2, 10)); row += 1
        self._v_teams.trace_add("write", self._refresh_walls)
        self._v_two_wall.trace_add("write", self._refresh_walls)
        self._refresh_walls()

        # Difficulty
        self._slbl(content, "DIFFICULTY", row); row += 1
        dr = tk.Frame(content, bg=BG_DARK)
        dr.grid(row=row, column=0, columnspan=2, pady=(0, 10)); row += 1
        for key, label, col in [("easy","EASY","#00c832"),
                                  ("medium","MEDIUM","#ffd700"),
                                  ("hard","HARD","#ff3c00")]:
            _seg_btn(dr, label, self._v_difficulty, key,
                     active_bg=col, width=9, height=2,
                     font=FONT_SM).pack(side=tk.LEFT, padx=6)

        # Team names
        self._slbl(content, "TEAM NAMES", row); row += 1
        nf = tk.Frame(content, bg=BG_DARK)
        nf.grid(row=row, column=0, columnspan=2, pady=(0, 10)); row += 1
        for i in range(MAX_TEAMS):
            col = TEAM_HEX[i]
            tk.Label(nf, text=f"{chr(65+i)}:", bg=BG_DARK, fg=col,
                     font=FONT_SM).grid(row=i//2, column=(i%2)*2,
                                        padx=(10,4), pady=4, sticky="e")
            e = tk.Entry(nf, textvariable=self._v_team_names[i],
                         width=12, bg=BG_PANEL, fg=FG_MAIN,
                         font=("Consolas", 13), insertbackground="white",
                         relief="flat", highlightthickness=1,
                         highlightbackground=col, highlightcolor=col)
            e.grid(row=i//2, column=(i%2)*2+1, padx=(0,20), pady=4)

        # Device IP
        self._slbl(content, "DEVICE IP", row); row += 1
        ip_row = tk.Frame(content, bg=BG_DARK)
        ip_row.grid(row=row, column=0, columnspan=2, pady=(0, 10))
        tk.Entry(ip_row, textvariable=self._v_device_ip,
                 width=20, bg=BG_PANEL, fg=FG_MAIN,
                 font=("Consolas", 13), insertbackground="white",
                 relief="flat", highlightthickness=1,
                 highlightbackground="#444").pack(side=tk.LEFT, padx=6)
        _make_lbl_btn(ip_row, "APPLY", self._apply_ip,
                      bg="#444", padx=12, pady=5,
                      font=FONT_XS, hover_bg="#666").pack(side=tk.LEFT, padx=4)

    def _slbl(self, parent, text, row):
        tk.Label(parent, text=text, bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).grid(
            row=row, column=0, columnspan=2, pady=(6, 2))

    def _refresh_walls(self, *_):
        n = self._v_teams.get()
        if n == 2:
            wmap = WALL_MAP[2] if self._v_two_wall.get() else WALL_MAP_2_ONE
            self._wall_frame.grid()
        else:
            wmap = WALL_MAP.get(n, {})
            self._wall_frame.grid_remove()
        parts = [f"{TEAM_NAMES_DEF[t][:6]}→{'+'.join(f'W{w}' for w in ws)}"
                 for t, ws in sorted(wmap.items())]
        self._lbl_walls.configure(text="  |  ".join(parts))

    # ─────────────────────────────────────────────────────────────────────────
    # GAME SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_game(self):
        f = self._frame_game

        # Bottom toolbar
        btm = tk.Frame(f, bg=BG_MID, pady=8)
        btm.pack(side=tk.BOTTOM, fill=tk.X)
        _make_lbl_btn(btm, "⚙ Setup", self._go_setup,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=8)
        _make_lbl_btn(btm, "⏹ Stop", self._stop_game,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=4)
        _make_lbl_btn(btm, "↺ Restart", self._restart_game,
                      bg="#335533", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#447744").pack(side=tk.LEFT, padx=4)
        self._game_status = tk.Label(btm, text="", bg=BG_MID, fg=FG_DIM, font=FONT_XS)
        self._game_status.pack(side=tk.RIGHT, padx=12)

        # Score / lives bar
        self._score_bar = tk.Frame(f, bg=BG_MID)
        self._score_bar.pack(fill=tk.X, pady=(0, 4))
        self._score_panels = []
        for i in range(MAX_TEAMS):
            pf = tk.Frame(self._score_bar, bg=BG_PANEL, padx=12, pady=6,
                          highlightthickness=0)
            nl = tk.Label(pf, text=TEAM_NAMES_DEF[i], bg=BG_PANEL,
                          fg=TEAM_HEX[i], font=("Consolas", 10, "bold"))
            nl.pack()
            ll = tk.Label(pf, text=_lives_str(LIVES), bg=BG_PANEL,
                          fg=FG_GREEN, font=("Consolas", 14, "bold"))
            ll.pack()
            sl = tk.Label(pf, text="0 hits", bg=BG_PANEL, fg=FG_DIM,
                          font=("Consolas", 9))
            sl.pack()
            self._score_panels.append((pf, nl, ll, sl))

        # Active team banner
        self._lbl_team = tk.Label(f, text="", bg=BG_DARK, fg=FG_MAIN,
                                  font=("Consolas", 26, "bold"))
        self._lbl_team.pack(pady=(8, 2))
        self._lbl_action = tk.Label(f, text="", bg=BG_DARK, fg=FG_DIM,
                                    font=("Consolas", 13))
        self._lbl_action.pack()

        # Timer
        center = tk.Frame(f, bg=BG_DARK)
        center.pack(expand=True)
        self._lbl_timer = tk.Label(center, text="", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 80, "bold"))
        self._lbl_timer.pack()
        self._lbl_targets = tk.Label(center, text="", bg=BG_DARK, fg=FG_DIM,
                                     font=("Consolas", 13))
        self._lbl_targets.pack()

        # Level bar
        lbar = tk.Frame(f, bg=BG_DARK, pady=8)
        lbar.pack(fill=tk.X, padx=60)
        hdr = tk.Frame(lbar, bg=BG_DARK)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="LEVEL", bg=BG_DARK, fg=FG_DIM, font=FONT_XS).pack(side=tk.LEFT)
        self._lbl_level = tk.Label(hdr, text="1", bg=BG_DARK, fg=FG_GOLD,
                                   font=("Consolas", 11, "bold"))
        self._lbl_level.pack(side=tk.LEFT, padx=8)
        self._lbl_diff = tk.Label(hdr, text="MEDIUM", bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._lbl_diff.pack(side=tk.RIGHT)
        self._level_bar = tk.Canvas(lbar, bg=BG_PANEL, height=12, highlightthickness=0)
        self._level_bar.pack(fill=tk.X, pady=(4, 0))

    # ── Updates ───────────────────────────────────────────────────────────────
    def _update_panels(self, lives, scores, num_teams, active):
        for pf, *_ in self._score_panels:
            pf.pack_forget()
        for i in range(num_teams):
            pf, nl, ll, sl = self._score_panels[i]
            nl.configure(text=self._game.team_names[i], fg=TEAM_HEX[i])
            ll.configure(
                text=_lives_str(lives[i]),
                fg=(FG_RED if lives[i] <= 1 else FG_GREEN if lives[i] == LIVES else FG_GOLD))
            sl.configure(text=f"{scores[i]} hit{'s' if scores[i] != 1 else ''}")
            pf.configure(
                highlightbackground=TEAM_HEX[i] if i == active else "#333",
                highlightthickness=3 if i == active else 0,
            )
            pf.pack(side=tk.LEFT, padx=6, pady=6, expand=True)

    def _update_level_bar(self, level, total_hits, difficulty):
        preset  = DIFF_PRESETS[difficulty]
        pct     = (total_hits % preset["step_hits"]) / preset["step_hits"]
        lvl_pct = min(1.0, (level - 1) / 8)
        r = int(lvl_pct * 255); g = int(200 - lvl_pct * 155)
        fill = f"#{r:02x}{g:02x}00"
        self._lbl_level.configure(text=str(level))
        self._lbl_diff.configure(text=difficulty.upper())
        w = self._level_bar.winfo_width() or 600
        self._level_bar.delete("all")
        self._level_bar.create_rectangle(0, 0, w, 12, fill=BG_PANEL, outline="")
        bw = int(w * pct)
        if bw > 0:
            self._level_bar.create_rectangle(0, 0, bw, 12, fill=fill, outline="")

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "team_turn":
            self._lbl_team.configure(text=f"▶  {data['name']}", fg=data["color"])
            self._lbl_action.configure(text="Get ready…", fg=FG_DIM)
            self._lbl_timer.configure(text="")
            self._lbl_targets.configure(text="")
            self._update_panels(data["lives"], data["scores"],
                                self._game.num_teams, data["team"])
            self._update_level_bar(data["level"], self._game.total_hits,
                                   self._game.difficulty)

        elif event == "round_start":
            self._turn_time_max = data["time_limit"]
            n = data["n_targets"]
            self._lbl_action.configure(
                text=f"Press {'all buttons' if n > 1 else 'the button'}!", fg=FG_MAIN)
            self._lbl_targets.configure(text=f"{n} target{'s' if n>1 else ''}")
            self._update_level_bar(data["level"], self._game.total_hits,
                                   self._game.difficulty)

        elif event == "tick":
            t = data["time_left"]
            self._lbl_timer.configure(
                text=f"{t:.1f}",
                fg=(FG_GREEN if t > 2.0 else FG_GOLD if t > 1.0 else FG_RED))
            rem = data["remaining"]
            self._lbl_targets.configure(
                text=f"{rem} target{'s' if rem!=1 else ''} remaining")

        elif event == "hit_partial":
            rem = data["remaining"]
            self._lbl_targets.configure(
                text=f"{rem} target{'s' if rem!=1 else ''} remaining")

        elif event == "hit":
            self._lbl_action.configure(text="✔  All targets hit!", fg=FG_GREEN)
            self._lbl_timer.configure(text="", fg=FG_MAIN)
            self._lbl_targets.configure(text="")
            self._update_panels(data["lives"], data["scores"],
                                self._game.num_teams, data["team"])
            self._update_level_bar(data["level"], self._game.total_hits,
                                   self._game.difficulty)

        elif event == "miss":
            name = data["name"]
            lives_left = data["lives"][data["team"]]
            suffix = "  ☠ ELIMINATED!" if data["eliminated"] else f"  {_lives_str(lives_left)} left"
            self._lbl_action.configure(
                text=f"✖  {name} missed!{suffix}", fg=FG_RED)
            self._lbl_timer.configure(text="×", fg=FG_RED)
            self._lbl_targets.configure(text="")
            self._update_panels(data["lives"], data["scores"],
                                self._game.num_teams, self._game.active_team)

        elif event == "game_over":
            self._lbl_team.configure(
                text=f"🏆  {data['name']}  wins!", fg=TEAM_HEX[data["winner"]])
            self._lbl_action.configure(text="Game Over!", fg=FG_GOLD)
            self._lbl_timer.configure(text="")
            self._update_panels(data["lives"], data["scores"],
                                self._game.num_teams, data["winner"])

    # ── Controls ──────────────────────────────────────────────────────────────
    def _apply_ip(self):
        ip = self._v_device_ip.get().strip()
        self._service.set_device(ip, self._cfg.get("udp_port", 4626))
        self._cfg["device_ip"] = ip
        save_config(self._cfg)
        self._set_status(f"Device → {ip}")

    def _start_game(self):
        self._apply_ip()
        settings = dict(
            num_teams=self._v_teams.get(),
            difficulty=self._v_difficulty.get(),
            team_names=[v.get() for v in self._v_team_names],
            two_wall=self._v_two_wall.get(),
        )
        self._last_settings = settings
        self._launch(settings)

    def _restart_game(self):
        if self._last_settings:
            self._game.stop_game()
            self._launch(self._last_settings)
        else:
            self._start_game()

    def _launch(self, s):
        self._game.start_game(**s)
        self._lbl_team.configure(text="", fg=FG_MAIN)
        self._lbl_action.configure(text="", fg=FG_DIM)
        self._lbl_timer.configure(text="")
        self._lbl_targets.configure(text="")
        n = s["num_teams"]
        self._update_panels([LIVES]*n, [0]*n, n, -1)
        self._update_level_bar(1, 0, s["difficulty"])
        self._show_game()

    def _stop_game(self):
        self._game.stop_game()
        self._lbl_action.configure(text="Game stopped.", fg=FG_DIM)
        self._lbl_timer.configure(text="")

    def _go_setup(self):
        self._game.stop_game()
        self._show_setup()

    def _set_status(self, msg):
        try:
            self._status_lbl.configure(text=msg)
            self._game_status.configure(text=msg)
        except tk.TclError:
            pass


if __name__ == "__main__":
    TargetRushApp().mainloop()
