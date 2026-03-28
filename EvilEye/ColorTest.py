"""
Color Rush – Evil Eye LED hardware.

Each wall lights exactly five buttons (one color each) and leaves five dark.
A target palette color is chosen each round. Rounds alternate:
  • Press round — first press on the target color scores.
  • Avoid round — first press on any other *lit* color scores; target is forbidden.
Auto-refresh uses a deadline that resets to the full interval on each correct score.
The interval shortens a little after every layout change (timer or score round).
First team to 20 points wins and ends the game.

Run:  python ColorTest.py
"""

import os, sys, random, threading, time
import tkinter as tk

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from Controller import LightService, load_config, save_config


class MirroringLightService(LightService):
    """Send each LED frame to the configured device and, when that is not loopback,
    also to 127.0.0.1 so EvilEye Simulator on the same PC receives the same packets
    (hardware IP in eye_ctrl_config.json does not need to match the sim).
    """

    _LOCAL_TARGETS = frozenset({"127.0.0.1", "localhost"})

    def _do_send_sequence(self, ip, frame_data):
        super()._do_send_sequence(ip, frame_data)
        if not ip:
            return
        if str(ip).strip().lower() in self._LOCAL_TARGETS:
            return
        super()._do_send_sequence("127.0.0.1", frame_data)


MAX_TEAMS = 4
MIN_TEAMS = 2
EYE_LED   = 0
BUTTON_SLOTS = list(range(1, 11))  # 5 lit + 5 off per wall; colors only on lit LEDs

# Starting auto-refresh interval (seconds); shrinks each round by RAMP_DEC until MIN_REFRESH_SEC
AUTO_REFRESH_SEC = {"easy": 10.0, "medium": 6, "hard": 5.0}
MIN_REFRESH_SEC = 3
RAMP_DEC = 0.1
WIN_SCORE = 10

# Base wall maps (2-team 1-wall variant built dynamically)
WALL_MAP = {
    2: {0: [1, 2], 1: [3, 4]},          # 2 walls each (default)
    3: {0: [1],    1: [2],    2: [3, 4]},
    4: {0: [1],    1: [2],    2: [3],    3: [4]},
}
WALL_MAP_2_ONE = {0: [1], 1: [2]}        # 2 teams, 1 wall each

TEAM_COLORS_RGB = [(255,60,0),(0,100,255),(0,210,60),(200,0,200)]
TEAM_HEX        = ["#ff3c00","#0064ff","#00d23c","#c800c8"]
TEAM_NAMES_DEF  = ["TEAM A","TEAM B","TEAM C","TEAM D"]

# Fixed 5-color palette (indices 0..4); five random LEDs per wall get one color each.
PALETTE_5 = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 120, 255),
    (255, 200, 0),
    (200, 0, 255),
]
PALETTE_NAMES = ["RED", "GREEN", "BLUE", "YELLOW", "MAGENTA"]
PALETTE_HEX   = ["#ff0000", "#00ff00", "#0078ff", "#ffc800", "#c800ff"]

RED   = (255, 0, 0)
GREEN = (0, 255, 0)
OFF   = (0, 0, 0)

S_SETUP = "setup"
S_PLAY  = "playing"
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
class ColorRushGame:
    def __init__(self, service: LightService, on_event):
        self._svc    = service
        self._notify = on_event
        self._lock   = threading.Lock()
        self._stop   = threading.Event()

        self.num_teams  = 2
        self.team_names = list(TEAM_NAMES_DEF)
        self.wall_map   = dict(WALL_MAP[2])

        self.state                 = S_SETUP
        self.scores                = [0] * MAX_TEAMS
        self.target_palette_idx    = 0
        self.must_press_target     = True
        self._phase_idx            = 0
        self.wall_led_to_palette   = {}
        self.wall_led_rgb          = {}
        self._round_busy           = False
        self.difficulty            = "medium"
        self._timer_thr            = None
        self._ramp_rounds         = 0
        self._refresh_deadline    = 0.0

    def _interval_for_ramp(self):
        with self._lock:
            base = AUTO_REFRESH_SEC.get(self.difficulty, 5.5)
            return max(MIN_REFRESH_SEC, base - RAMP_DEC * self._ramp_rounds)

    def _arm_refresh_deadline_only(self):
        with self._lock:
            if self.state != S_PLAY:
                return
            base = AUTO_REFRESH_SEC.get(self.difficulty, 5.5)
            iv = max(MIN_REFRESH_SEC, base - RAMP_DEC * self._ramp_rounds)
            self._refresh_deadline = time.monotonic() + iv

    def start_game(self, num_teams, team_names=None, two_wall=True, difficulty="medium"):
        self.stop_game()
        self.num_teams = max(MIN_TEAMS, min(MAX_TEAMS, num_teams))
        if team_names:
            for i, n in enumerate(team_names[:MAX_TEAMS]):
                self.team_names[i] = n.strip() or TEAM_NAMES_DEF[i]

        if self.num_teams == 2:
            self.wall_map = dict(WALL_MAP[2]) if two_wall else dict(WALL_MAP_2_ONE)
        else:
            self.wall_map = dict(WALL_MAP[self.num_teams])

        self.difficulty = difficulty if difficulty in AUTO_REFRESH_SEC else "medium"
        self.scores = [0] * MAX_TEAMS
        self._phase_idx = 0
        self._ramp_rounds = 0
        self.state  = S_PLAY
        self._stop.clear()
        self._new_round(notify_start=True)
        self._timer_thr = threading.Thread(target=self._auto_refresh_loop, daemon=True)
        self._timer_thr.start()

    def stop_game(self):
        self._stop.set()
        if self._timer_thr and self._timer_thr.is_alive():
            self._timer_thr.join(timeout=3.0)
        self._timer_thr = None
        self._svc.all_off()
        self.state = S_SETUP
        self.wall_led_to_palette.clear()
        self.wall_led_rgb.clear()

    def handle_button(self, ch, led, is_triggered, is_disconnected):
        if not is_triggered or self.state != S_PLAY:
            return
        with self._lock:
            if self._round_busy:
                return
        if led not in BUTTON_SLOTS:
            return
        if ch not in self._all_walls():
            return
        key = (ch, led)
        if key not in self.wall_led_to_palette:
            return
        pal_idx = self.wall_led_to_palette[key]
        team = self._team_for_wall(ch)
        if team is None or team >= self.num_teams:
            return

        tgt = self.target_palette_idx
        press_mode = self.must_press_target
        wrong = (pal_idx == tgt) != press_mode
        if wrong:
            threading.Thread(
                target=self._flash_wrong, args=(ch, led), daemon=True
            ).start()
            self._notify("wrong_touch", {
                "team": team,
                "name": self.team_names[team],
                "target_name": PALETTE_NAMES[tgt],
                "must_press": press_mode,
            })
            return

        with self._lock:
            if self._round_busy:
                return
            self.scores[team] += 1
            sc = list(self.scores[: self.num_teams])
            won = self.scores[team] >= WIN_SCORE
            if won:
                self.state = S_OVER
            else:
                self._round_busy = True

        if won:
            self._notify("game_over", {
                "team": team,
                "name": self.team_names[team],
                "scores": sc,
                "goal": WIN_SCORE,
            })
            threading.Thread(
                target=self._win_sequence, args=(team,), daemon=True
            ).start()
            return

        self._arm_refresh_deadline_only()
        self._notify("point", {
            "team": team,
            "name": self.team_names[team],
            "scores": sc,
            "next_refresh_sec": self._interval_for_ramp(),
        })
        threading.Thread(
            target=self._celebrate_and_new_round, args=(team,), daemon=True
        ).start()

    def _all_walls(self):
        seen = set()
        for ws in self.wall_map.values():
            for w in ws:
                seen.add(w)
        return sorted(seen)

    def _walls(self, team):
        return self.wall_map.get(team, [team + 1])

    def _team_for_wall(self, ch):
        for t in range(self.num_teams):
            if ch in self.wall_map.get(t, []):
                return t
        return None

    def _show_eyes(self):
        for t in range(self.num_teams):
            r, g, b = TEAM_COLORS_RGB[t]
            for w in self._walls(t):
                self._svc.set_led(w, EYE_LED, r // 4, g // 4, b // 4)

    def _new_round(self, notify_start=False):
        if self._stop.is_set() or self.state != S_PLAY:
            with self._lock:
                self._round_busy = False
            return
        self.must_press_target = (self._phase_idx % 2 == 0)
        self._phase_idx += 1
        self.target_palette_idx = random.randrange(len(PALETTE_5))
        self.wall_led_to_palette.clear()
        self.wall_led_rgb.clear()

        for w in self._all_walls():
            lit = random.sample(BUTTON_SLOTS, len(PALETTE_5))
            perm = list(range(len(PALETTE_5)))
            random.shuffle(perm)
            for led in BUTTON_SLOTS:
                self._svc.set_led(w, led, *OFF)
            for i, led in enumerate(lit):
                pal_idx = perm[i]
                rgb = PALETTE_5[pal_idx]
                self.wall_led_to_palette[(w, led)] = pal_idx
                self.wall_led_rgb[(w, led)] = rgb
                self._svc.set_led(w, led, *rgb)

        self._show_eyes()
        ti = self.target_palette_idx
        iv = self._interval_for_ramp()
        payload = {
            "target_idx": ti,
            "target_name": PALETTE_NAMES[ti],
            "target_rgb": PALETTE_5[ti],
            "target_hex": PALETTE_HEX[ti],
            "must_press": self.must_press_target,
            "scores": list(self.scores[: self.num_teams]),
            "refresh_sec": iv,
            "goal": WIN_SCORE,
        }
        if notify_start:
            payload["team_names"] = list(self.team_names[: self.num_teams])
            self._notify("game_start", payload)
        else:
            self._notify("new_round", payload)
        with self._lock:
            self._round_busy = False
            self._refresh_deadline = time.monotonic() + iv
            self._ramp_rounds += 1

    def _flash_wrong(self, ch, led):
        if self._stop.is_set():
            return
        prev = self.wall_led_rgb.get((ch, led), OFF)
        try:
            self._svc.set_led(ch, led, *RED)
            time.sleep(0.12)
            if not self._stop.is_set():
                self._svc.set_led(ch, led, *prev)
        except Exception:
            pass

    def _celebrate_and_new_round(self, team):
        if self._stop.is_set():
            return
        walls = self._walls(team)
        tr, tg, tb = TEAM_COLORS_RGB[team]
        try:
            for w in walls:
                for led in BUTTON_SLOTS:
                    self._svc.set_led(w, led, *GREEN)
                self._svc.set_led(w, EYE_LED, tr, tg, tb)
            time.sleep(0.45)
        except Exception:
            pass
        if not self._stop.is_set():
            self._new_round(notify_start=False)

    def _win_sequence(self, team):
        if self._stop.is_set():
            return
        walls = self._all_walls()
        tr, tg, tb = TEAM_COLORS_RGB[team]
        try:
            for w in walls:
                for led in BUTTON_SLOTS:
                    self._svc.set_led(w, led, *GREEN)
                self._svc.set_led(w, EYE_LED, tr, tg, tb)
            time.sleep(0.85)
        except Exception:
            pass
        if not self._stop.is_set():
            self.stop_game()

    def _auto_refresh_loop(self):
        while not self._stop.is_set():
            with self._lock:
                if self.state != S_PLAY:
                    time.sleep(0.1)
                    continue

            while not self._stop.is_set():
                now = time.monotonic()
                with self._lock:
                    if self.state != S_PLAY:
                        break
                    deadline = self._refresh_deadline
                    busy = self._round_busy
                if busy:
                    time.sleep(0.05)
                    continue
                if now >= deadline:
                    break
                time.sleep(min(0.05, max(0.001, deadline - now)))

            if self._stop.is_set():
                return
            with self._lock:
                if self.state != S_PLAY or self._round_busy:
                    continue
                # Correct score may have extended _refresh_deadline after we passed an old target
                if time.monotonic() < self._refresh_deadline:
                    continue
            self._new_round(notify_start=False)


# ─────────────────────────────────────────────────────────────────────────────
# Application
# ─────────────────────────────────────────────────────────────────────────────
class ColorRushApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Color Rush – Evil Eye")
        self.configure(bg=BG_DARK)
        self.minsize(520, 420)
        self.bind("<F11>", lambda e: self.attributes(
            "-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self._cfg     = load_config()
        self._service = MirroringLightService()
        self._service.on_status = lambda m: self.after(
            0, lambda msg=m: self._set_status(msg))

        ip = (self._cfg.get("device_ip") or "").strip() or "127.0.0.1"
        udp = int(self._cfg.get("udp_port", 4626))
        recv = int(self._cfg.get("receiver_port", 7800))
        self._service.set_device(ip, udp)
        self._service.set_recv_port(recv)
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
        self._service.start_receiver()
        self._service.start_polling()

        self._game = ColorRushGame(self._service, self._on_game_event)
        self._service.on_button_state = self._game.handle_button

        self._v_players     = tk.IntVar(value=2)
        self._v_difficulty  = tk.StringVar(value="medium")
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

        mid = tk.Frame(f, bg=BG_DARK)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        mid.grid_rowconfigure(0, weight=1)
        mid.grid_columnconfigure(0, weight=1)
        col = tk.Frame(mid, bg=BG_DARK)
        col.grid(row=0, column=0)

        tk.Label(col, text="COLOR RUSH", bg=BG_DARK, fg="#ff3c00",
                 font=("Consolas", 36, "bold")).pack(anchor=tk.CENTER, pady=(0, 4))


        tk.Label(col, text="NUMBER OF PLAYERS", bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).pack(anchor=tk.CENTER, pady=(6, 4))
        r = tk.Frame(col, bg=BG_DARK)
        r.pack(anchor=tk.CENTER, pady=(0, 20))
        for n in range(2, 5):
            _seg_btn(r, str(n), self._v_players, n,
                     active_bg=TEAM_HEX[n-2], width=5, height=2,
                     font=("Consolas", 18, "bold")).pack(side=tk.LEFT, padx=8)

        tk.Label(col, text="DIFFICULTY", bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 9, "bold")).pack(anchor=tk.CENTER, pady=(6, 4))
        dr = tk.Frame(col, bg=BG_DARK)
        dr.pack(anchor=tk.CENTER, pady=(0, 16))
        for key, label, c in [
            ("easy", "EASY", "#00c832"),
            ("medium", "MEDIUM", "#ffd700"),
            ("hard", "HARD", "#ff3c00"),
        ]:
            _seg_btn(dr, label, self._v_difficulty, key,
                     active_bg=c, width=11, height=2,
                     font=FONT_XS).pack(side=tk.LEFT, padx=6)


    # ─────────────────────────────────────────────────────────────────────────
    # GAME SCREEN
    # ─────────────────────────────────────────────────────────────────────────
    def _build_game(self):
        f = self._frame_game

        btm = tk.Frame(f, bg=BG_MID)
        btm.pack(side=tk.BOTTOM, fill=tk.X)
        btm_btns = tk.Frame(btm, bg=BG_MID)
        btm_btns.pack(pady=(10, 4))
        _make_lbl_btn(btm_btns, "⚙ Setup", self._go_setup,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=6)
        _make_lbl_btn(btm_btns, "⏹ Stop", self._stop_game,
                      bg="#333", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#555").pack(side=tk.LEFT, padx=4)
        _make_lbl_btn(btm_btns, "↺ Restart", self._restart_game,
                      bg="#335533", padx=14, pady=6,
                      font=FONT_XS, hover_bg="#447744").pack(side=tk.LEFT, padx=6)
        self._game_status = tk.Label(btm, text="", bg=BG_MID, fg=FG_DIM, font=FONT_XS)
        self._game_status.pack(pady=(0, 8))

        sb_wrap = tk.Frame(f, bg=BG_MID)
        sb_wrap.pack(fill=tk.X, pady=(0, 4))
        self._score_bar = tk.Frame(sb_wrap, bg=BG_MID)
        self._score_bar.pack(anchor=tk.CENTER)
        self._score_panels = []
        for i in range(MAX_TEAMS):
            pf = tk.Frame(self._score_bar, bg=BG_PANEL, padx=12, pady=8,
                          highlightthickness=0)
            nl = tk.Label(pf, text=TEAM_NAMES_DEF[i], bg=BG_PANEL,
                          fg=TEAM_HEX[i], font=("Consolas", 10, "bold"))
            nl.pack()
            sl = tk.Label(pf, text="0 pts", bg=BG_PANEL, fg=FG_MAIN,
                          font=("Consolas", 18, "bold"))
            sl.pack()
            self._score_panels.append((pf, nl, sl))

        main = tk.Frame(f, bg=BG_DARK)
        main.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        main.grid_rowconfigure(0, weight=1)
        main.grid_columnconfigure(0, weight=1)
        ccol = tk.Frame(main, bg=BG_DARK)
        ccol.grid(row=0, column=0)

        self._lbl_team = tk.Label(ccol, text="", bg=BG_DARK, fg=FG_MAIN,
                                  font=("Consolas", 22, "bold"))
        self._lbl_team.pack(anchor=tk.CENTER, pady=(4, 2))

        center = tk.Frame(ccol, bg=BG_DARK)
        center.pack(anchor=tk.CENTER)
        self._lbl_mode_banner = tk.Label(
            center, text="", bg=BG_DARK, fg=FG_GOLD,
            font=("Consolas", 14, "bold"))
        self._lbl_mode_banner.pack(anchor=tk.CENTER, pady=(0, 6))
        self._swatch = tk.Frame(center, width=100, height=100, bg="#333333")
        self._swatch.pack(anchor=tk.CENTER)
        self._swatch.pack_propagate(False)
        self._lbl_avoid = tk.Label(center, text="—", bg=BG_DARK, fg=FG_MAIN,
                                   font=("Consolas", 28, "bold"))
        self._lbl_avoid.pack(anchor=tk.CENTER, pady=(10, 4))
        self._lbl_targets = tk.Label(
            center,
            text="Five random buttons light (one color each); five stay dark · unlit presses ignored",
            bg=BG_DARK, fg=FG_DIM, font=("Consolas", 11), wraplength=520,
            justify=tk.CENTER)
        self._lbl_targets.pack(anchor=tk.CENTER, pady=(8, 0))

        pal_row = tk.Frame(center, bg=BG_DARK)
        pal_row.pack(anchor=tk.CENTER, pady=(12, 0))
        for i, hx in enumerate(PALETTE_HEX):
            tk.Label(pal_row, text="  ", bg=hx, width=3, height=1,
                     relief="solid", borderwidth=1).pack(side=tk.LEFT, padx=3)
        tk.Label(center, text=" ".join(PALETTE_NAMES), bg=BG_DARK, fg=FG_DIM,
                 font=("Consolas", 8)).pack(anchor=tk.CENTER, pady=(4, 0))

    # ── Updates ───────────────────────────────────────────────────────────────
    def _update_panels(self, scores, num_teams, highlight=-1):
        for pf, *_ in self._score_panels:
            pf.pack_forget()
        for i in range(num_teams):
            pf, nl, sl = self._score_panels[i]
            nl.configure(text=self._game.team_names[i], fg=TEAM_HEX[i])
            sl.configure(text=f"{scores[i]} pt{'s' if scores[i] != 1 else ''}")
            pf.configure(
                highlightbackground=TEAM_HEX[i] if i == highlight else "#333",
                highlightthickness=3 if i == highlight else 0,
            )
            pf.pack(side=tk.LEFT, padx=6, pady=6)

    def _set_target_ui(self, name, hex_color, must_press):
        self._swatch.configure(bg=hex_color)
        self._lbl_avoid.configure(text=name.upper(), fg=hex_color)
        self._lbl_mode_banner.configure(
            text="PRESS this color" if must_press else "DO NOT press this color",
            fg=FG_GREEN if must_press else FG_RED,
        )

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "game_start":
            self._lbl_team.configure(text="Color Rush", fg=FG_GOLD)

            self._set_target_ui(
                data["target_name"], data["target_hex"], data.get("must_press", True))
            self._update_panels(data["scores"], self._game.num_teams, highlight=-1)

        elif event == "new_round":
            self._set_target_ui(
                data["target_name"], data["target_hex"], data.get("must_press", True))
            self._update_panels(data["scores"], self._game.num_teams, highlight=-1)

        elif event == "point":
            self._lbl_team.configure(
                text=f"+1  {data['name']}", fg=TEAM_HEX[data["team"]])
            self._update_panels(data["scores"], self._game.num_teams,
                                highlight=data["team"])

        elif event == "game_over":
            self._lbl_team.configure(
                text=f"🏆  {data['name']}  wins!",
                fg=TEAM_HEX[data["team"]])
            self._update_panels(data["scores"], self._game.num_teams,
                                highlight=data["team"])

    # ── Controls ──────────────────────────────────────────────────────────────
    def _apply_network_from_config(self):
        ip = (self._cfg.get("device_ip") or "").strip() or "127.0.0.1"
        try:
            udp = int(self._cfg.get("udp_port", 4626))
            recv = int(self._cfg.get("receiver_port", 7800))
        except (TypeError, ValueError):
            udp, recv = 4626, 7800
        prev_recv = self._service._recv_port
        if recv != prev_recv:
            self._service.stop_receiver()
        self._service.set_device(ip, udp)
        self._service.set_recv_port(recv)
        if recv != prev_recv:
            self._service.start_receiver()
        self._set_status(f"{ip}:{udp}  ·  listen {recv}")

    def _start_game(self):
        self._cfg = load_config()
        self._apply_network_from_config()
        settings = dict(
            num_teams=self._v_players.get(),
            team_names=list(TEAM_NAMES_DEF),
            two_wall=True,
            difficulty=self._v_difficulty.get(),
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
        self._swatch.configure(bg="#333333")
        self._lbl_avoid.configure(text="—", fg=FG_MAIN)
        self._lbl_mode_banner.configure(text="", fg=FG_DIM)
        n = s["num_teams"]
        self._update_panels([0] * n, n, highlight=-1)
        self._show_game()

    def _stop_game(self):
        self._game.stop_game()

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
    ColorRushApp().mainloop()