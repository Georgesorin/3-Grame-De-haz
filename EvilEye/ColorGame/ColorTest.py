
import os, sys, random, threading, time, math
import tkinter as tk

_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    import pygame as _pygame
except ImportError:
    _pygame = None

RULES_MP3 = os.path.join(_DIR, "sounds", "rules.mp3")
REITERATE_MP3 = os.path.join(_DIR, "sounds", "reiterate.mp3")
WON_MP3 = os.path.join(_DIR, "sounds", "won.mp3")


def _ensure_pygame_mixer():
    """
    Initialize pygame.mixer on the main thread before any worker plays audio.
    Returns True if the mixer is ready. On failure, logs to stderr.
    """
    if _pygame is None:
        return False
    try:
        if not _pygame.mixer.get_init():
            _pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            _pygame.mixer.set_num_channels(12)
        return True
    except Exception as e:
        print("Color Rush: pygame mixer init failed:", e, file=sys.stderr)
        return False


def _play_music_blocking(path, stop_event_callable):
    """
    Block until the given mp3 finishes or stop_event_callable() is true.
    Safe to call from a worker thread. No-op if pygame or file is missing.

    Uses mixer.Sound (not mixer.music): on Windows, music streams often fail
    when played from background threads; Sound matches palette clips and FIRE's behavior.
    """
    if _pygame is None:
        return
    if not path or not os.path.isfile(path):
        return
    try:
        if not _pygame.mixer.get_init():
            _pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            _pygame.mixer.set_num_channels(12)
    except Exception as e:
        print("Color Rush: mixer init (narration):", e, file=sys.stderr)
        return
    try:
        snd = _pygame.mixer.Sound(path)
        ch = _pygame.mixer.find_channel(True)
        if ch is None:
            ch = _pygame.mixer.Channel(0)
        ch.play(snd)
        while ch.get_busy():
            if stop_event_callable():
                ch.stop()
                return
            _pygame.time.wait(30)
    except Exception as e:
        print("Color Rush: narration playback:", e, file=sys.stderr)
# Controller.py lives in parent EvilEye/, not ColorGame/
_EVILEYE_ROOT = os.path.dirname(_DIR)
if _EVILEYE_ROOT not in sys.path:
    sys.path.insert(0, _EVILEYE_ROOT)

from Controller import LightService, load_config, logical_rgb_to_wire_grb, receiver_bind_ip_from_config

# Logical RGB in set_led / palette tuples → GRB in UDP frames (shared with Fire).
assert logical_rgb_to_wire_grb(1, 2, 3) == (2, 1, 3)


class MirroringLightService(LightService):
    """Send each LED frame to the configured device and, when that is not loopback,
    also to 127.0.0.1 so EvilEye Simulator on the same PC receives the same packets
    (hardware IP in eye_ctrl_config.json does not need to match the sim).

    set_led(..., r, g, b) is logical RGB; frames use GRB via build_frame_data /
    logical_rgb_to_wire_grb.
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
AUTO_REFRESH_SEC = {"easy": 6.0, "medium": 5, "hard": 4.0}
MIN_REFRESH_SEC = 1
RAMP_DEC = 0.2
WIN_SCORE = 20

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
# Tuples are logical (R, G, B). Frames use GRB (Controller.logical_rgb_to_wire_grb).
PALETTE_5 = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 120, 255),
    (255, 200, 0),
    (200, 0, 255),
]
PALETTE_NAMES = ["RED", "GREEN", "BLUE", "YELLOW", "MAGENTA"]
PALETTE_HEX   = ["#ff0000", "#00ff00", "#0078ff", "#ffc800", "#c800ff"]


def _palette_sound_path(pal_idx):
    if pal_idx < 0 or pal_idx >= len(PALETTE_NAMES):
        return ""
    name = PALETTE_NAMES[pal_idx]
    stem = "PURPLE" if name == "MAGENTA" else name
    return os.path.join(_DIR, "sounds", f"{stem}.mp3")


def _play_palette_sound_blocking(pal_idx, stop_event_callable):
    """Play one color clip from sounds/; block until finished or stop_event_callable()."""
    if _pygame is None:
        return
    path = _palette_sound_path(pal_idx)
    if not path or not os.path.isfile(path):
        return
    try:
        if not _pygame.mixer.get_init():
            _pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=1024)
            _pygame.mixer.set_num_channels(12)
        snd = _pygame.mixer.Sound(path)
        ch = _pygame.mixer.find_channel(True)
        if ch is None:
            ch = _pygame.mixer.Channel(0)
        ch.play(snd)
        while ch.get_busy():
            if stop_event_callable():
                ch.stop()
                return
            _pygame.time.wait(30)
    except Exception as e:
        print("Color Rush: palette sound:", e, file=sys.stderr)


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


def _hex_to_rgb(h):
    h = (h or "#000").lstrip("#")
    if len(h) != 6:
        return 0, 0, 0
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))


def _rgb_to_hex(r, g, b):
    return f"#{max(0, min(255, int(r))):02x}{max(0, min(255, int(g))):02x}{max(0, min(255, int(b))):02x}"


def _lerp_rgb(a, b, t):
    t = max(0.0, min(1.0, t))
    return tuple(x + (y - x) * t for x, y in zip(a, b))


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

    def _preface_audio_path(self):
        """
        Optional narration before layout (_phase_idx = completed rounds, before increment).
        rules.mp3 only before round 1; reiterate.mp3 before rounds 11, 21, 31, …
        """
        if self._phase_idx == 0:
            return RULES_MP3
        if self._phase_idx > 0 and self._phase_idx % 10 == 0:
            return REITERATE_MP3
        return None

    def _new_round(self, notify_start=False):
        if self._stop.is_set() or self.state != S_PLAY:
            with self._lock:
                self._round_busy = False
            return
        preface = self._preface_audio_path()
        if preface:
            with self._lock:
                self._round_busy = True
            threading.Thread(
                target=self._preface_then_new_round,
                args=(notify_start, preface),
                daemon=True,
            ).start()
            return
        self._new_round_after_rules(notify_start)

    def _preface_then_new_round(self, notify_start, audio_path):
        _play_music_blocking(audio_path, lambda: self._stop.is_set())
        if self._stop.is_set() or self.state != S_PLAY:
            with self._lock:
                self._round_busy = False
            return
        self._new_round_after_rules(notify_start)

    def _new_round_after_rules(self, notify_start=False):
        if self._stop.is_set() or self.state != S_PLAY:
            with self._lock:
                self._round_busy = False
            return
        with self._lock:
            self._round_busy = True

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
        _play_palette_sound_blocking(ti, self._stop.is_set)
        if self._stop.is_set():
            with self._lock:
                self._round_busy = False
            return
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
        music_thr = threading.Thread(
            target=_play_music_blocking,
            args=(WON_MP3, lambda: self._stop.is_set()),
            daemon=True,
        )
        music_thr.start()
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
        music_thr.join()
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
        self._audio_ok = _ensure_pygame_mixer()
        if _pygame is None:
            print(
                "Color Rush: pygame is not installed — sound is disabled. "
                "Fix: pip install pygame   (or run install_libraries.py)",
                file=sys.stderr,
            )
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
        self._service.set_bind_ip(receiver_bind_ip_from_config(self._cfg))
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

        self._ambient_phase = 0
        self._screen = "setup"
        self._swatch_target_hex = "#333333"
        self._swatch_breathe_hold = False
        self._hdr_pop_id = 0
        self._score_pop_id = 0
        self._victory_fx_id = 0
        self._pal_chips = []

        self._build_setup()
        self._build_game()
        self._scores_win = None
        self._build_scores_window()
        self._show_setup()
        self.protocol("WM_DELETE_WINDOW", self._on_app_close)
        self.after(60, self._ambient_tick)

    def _show_setup(self):
        self._screen = "setup"
        self._frame_setup.lift()

    def _show_game(self):
        self._screen = "game"
        self._frame_game.lift()

    def _ambient_tick(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        self._ambient_phase = (self._ambient_phase + 1) % 10_000
        ph = self._ambient_phase * 0.12

        if self._screen == "setup":
            t = 0.5 + 0.5 * math.sin(ph)
            c = _lerp_rgb(_hex_to_rgb("#cc2800"), _hex_to_rgb("#ff7a33"), t)
            try:
                self._setup_title.configure(fg=_rgb_to_hex(*c))
            except tk.TclError:
                pass
            try:
                sh = 0.5 + 0.5 * math.sin(ph * 1.7)
                g = _lerp_rgb(_hex_to_rgb("#cc3000"), _hex_to_rgb("#ff5533"), sh)
                self._setup_start_btn.configure(bg=_rgb_to_hex(*g))
            except tk.TclError:
                pass
            try:
                sb = 0.5 + 0.5 * math.sin(ph * 1.05 + 0.4)
                gc = _lerp_rgb(_hex_to_rgb("#444444"), _hex_to_rgb("#909090"), sb * 0.4)
                self._status_lbl.configure(fg=_rgb_to_hex(*gc))
            except tk.TclError:
                pass

        elif self._screen == "game":
            st = getattr(self._game, "state", S_SETUP)
            if st == S_PLAY and not self._swatch_breathe_hold:
                base = _hex_to_rgb(self._swatch_target_hex)
                if sum(base) > 40:
                    br = 0.5 + 0.5 * math.sin(ph * 2.1)
                    dim = tuple(x * 0.55 for x in base)
                    lit = tuple(min(255, x * 1.15 + 35) for x in base)
                    mix = _lerp_rgb(dim, lit, br)
                    try:
                        self._swatch.configure(bg=_rgb_to_hex(*mix))
                        edge = _lerp_rgb(_hex_to_rgb("#222"), base, 0.35 + 0.25 * br)
                        self._swatch_wrap.configure(highlightbackground=_rgb_to_hex(*edge))
                    except tk.TclError:
                        pass
            if self._pal_chips:
                i = self._ambient_phase % len(self._pal_chips)
                for j, lbl in enumerate(self._pal_chips):
                    try:
                        if j == i:
                            lbl.configure(relief="solid", borderwidth=2)
                        else:
                            lbl.configure(relief="solid", borderwidth=1)
                    except tk.TclError:
                        pass
            try:
                tb = 0.5 + 0.5 * math.sin(ph * 0.85)
                g = _lerp_rgb(_hex_to_rgb(FG_DIM), _hex_to_rgb("#707070"), tb * 0.45)
                self._lbl_targets.configure(fg=_rgb_to_hex(*g))
                pb = 0.5 + 0.5 * math.sin(ph * 0.65 + 1.1)
                g2 = _lerp_rgb(_hex_to_rgb(FG_DIM), _hex_to_rgb("#5a5a5a"), pb * 0.35)
                self._lbl_palette_names.configure(fg=_rgb_to_hex(*g2))
            except tk.TclError:
                pass

        self.after(90, self._ambient_tick)

    def _flash_swatch_pop(self, hex_color):
        self._swatch_breathe_hold = True
        seq = ["#ffffff", hex_color, "#f0f0f0", hex_color, hex_color]
        ms = [38, 42, 36, 48, 0]

        def step(i):
            if i >= len(seq):
                try:
                    self._swatch.configure(bg=hex_color)
                except tk.TclError:
                    pass
                self._swatch_breathe_hold = False
                return
            try:
                self._swatch.configure(bg=seq[i])
            except tk.TclError:
                self._swatch_breathe_hold = False
                return
            self.after(ms[i], lambda: step(i + 1))

        step(0)

    def _pop_team_header(self, big=True):
        self._hdr_pop_id += 1
        hid = self._hdr_pop_id
        sizes = (22, 26, 32, 28, 24, 22) if big else (22, 25, 24, 22)

        def step(i):
            if self._hdr_pop_id != hid or i >= len(sizes):
                try:
                    self._lbl_team.configure(font=("Consolas", 22, "bold"))
                except tk.TclError:
                    pass
                return
            try:
                self._lbl_team.configure(font=("Consolas", sizes[i], "bold"))
            except tk.TclError:
                return
            self.after(48, lambda: step(i + 1))

        step(0)

    def _pulse_score_panel(self, team_i):
        if team_i < 0 or team_i >= len(self._score_panels):
            return
        self._score_pop_id += 1
        pid = self._score_pop_id
        _, _, sl = self._score_panels[team_i]
        sizes = (18, 24, 30, 24, 18)

        def step(i):
            if self._score_pop_id != pid or i >= len(sizes):
                try:
                    sl.configure(font=("Consolas", 18, "bold"))
                except tk.TclError:
                    pass
                return
            try:
                sl.configure(font=("Consolas", sizes[i], "bold"))
            except tk.TclError:
                return
            self.after(50, lambda: step(i + 1))

        step(0)

    def _nudge_mode_banner(self, must_press):
        base = FG_GREEN if must_press else FG_RED
        hi = "#aaffcc" if must_press else "#ff8888"

        def flash(on):
            try:
                self._lbl_mode_banner.configure(fg=hi if on else base)
            except tk.TclError:
                return
            if on:
                self.after(70, lambda: flash(False))

        flash(True)

    def _run_victory_fx(self, team_hex):
        self._victory_fx_id += 1
        vid = self._victory_fx_id
        steps = 24

        def step(i):
            if self._victory_fx_id != vid:
                return
            if i >= steps:
                try:
                    self._lbl_team.configure(fg=team_hex)
                except tk.TclError:
                    pass
                return
            t = 0.5 + 0.5 * math.sin(i * 0.65)
            c = _lerp_rgb(_hex_to_rgb(team_hex), (255, 255, 220), t * 0.55)
            try:
                self._lbl_team.configure(fg=_rgb_to_hex(*c))
            except tk.TclError:
                return
            self.after(50, lambda: step(i + 1))

        step(0)

    # ─────────────────────────────────────────────────────────────────────────
    # SETUP
    # ─────────────────────────────────────────────────────────────────────────
    def _build_setup(self):
        f = self._frame_setup

        if _pygame is None:
            _st = "Ready · no pygame — pip install pygame (sound off)"
        elif not self._audio_ok:
            _st = "Ready · audio init failed — check output device / drivers"
        else:
            _st = "Ready"
        self._status_lbl = tk.Label(f, text=_st, bg=BG_DARK, fg=FG_DIM, font=FONT_XS)
        self._status_lbl.pack(side=tk.BOTTOM, pady=(0, 8))

        self._setup_start_btn = _make_lbl_btn(
            f,
            "▶   START GAME",
            self._start_game,
            bg="#ff3c00",
            fg="white",
            font=("Consolas", 20, "bold"),
            padx=50,
            pady=18,
            hover_bg="#cc3000",
        )
        self._setup_start_btn.pack(side=tk.BOTTOM, pady=(6, 6))

        mid = tk.Frame(f, bg=BG_DARK)
        mid.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        mid.grid_rowconfigure(0, weight=1)
        mid.grid_columnconfigure(0, weight=1)
        col = tk.Frame(mid, bg=BG_DARK)
        col.grid(row=0, column=0)

        self._setup_title = tk.Label(
            col,
            text="COLOR RUSH",
            bg=BG_DARK,
            fg="#ff3c00",
            font=("Consolas", 36, "bold"),
        )
        self._setup_title.pack(anchor=tk.CENTER, pady=(0, 4))


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
        self._swatch_wrap = tk.Frame(
            center, bg=BG_DARK, highlightthickness=2, highlightbackground="#333"
        )
        self._swatch_wrap.pack(anchor=tk.CENTER)
        self._swatch = tk.Frame(self._swatch_wrap, width=100, height=100, bg="#333333")
        self._swatch.pack(padx=8, pady=8)
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

        self._pal_chips = []
        pal_row = tk.Frame(center, bg=BG_DARK)
        pal_row.pack(anchor=tk.CENTER, pady=(12, 0))
        for hx in PALETTE_HEX:
            chip = tk.Label(
                pal_row,
                text="  ",
                bg=hx,
                width=3,
                height=1,
                relief="solid",
                borderwidth=1,
            )
            chip.pack(side=tk.LEFT, padx=3)
            self._pal_chips.append(chip)
        self._lbl_palette_names = tk.Label(
            center,
            text=" ".join(PALETTE_NAMES),
            bg=BG_DARK,
            fg=FG_DIM,
            font=("Consolas", 8),
        )
        self._lbl_palette_names.pack(anchor=tk.CENTER, pady=(4, 0))

    def _build_scores_window(self):
        w = tk.Toplevel(self)
        w.title("Color Rush – Scores")
        w.configure(bg=BG_DARK)
        w.minsize(320, 120)
        w.transient(self)

        def place_scores_window():
            try:
                self.update_idletasks()
                rx, ry = self.winfo_rootx(), self.winfo_rooty()
                rw = self.winfo_width()
                w.geometry(f"+{rx + rw + 12}+{ry}")
            except tk.TclError:
                pass

        place_scores_window()

        hdr = tk.Frame(w, bg=BG_MID, pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(
            hdr,
            text="Scores",
            bg=BG_MID,
            fg=FG_GOLD,
            font=("Consolas", 12, "bold"),
        ).pack()

        body = tk.Frame(w, bg=BG_DARK, padx=12, pady=12)
        body.pack(fill=tk.BOTH, expand=True)
        self._score_bar = tk.Frame(body, bg=BG_DARK)
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

        def on_scores_close():
            w.withdraw()

        w.protocol("WM_DELETE_WINDOW", on_scores_close)
        self._scores_win = w
        w.withdraw()

    def _scores_show(self):
        if self._scores_win is None:
            return
        try:
            self.update_idletasks()
            rx, ry = self.winfo_rootx(), self.winfo_rooty()
            rw = self.winfo_width()
            self._scores_win.geometry(f"+{rx + rw + 12}+{ry}")
            self._scores_win.deiconify()
            self._scores_win.lift()
        except tk.TclError:
            pass

    def _scores_hide(self):
        if self._scores_win is None:
            return
        try:
            self._scores_win.withdraw()
        except tk.TclError:
            pass

    def _on_app_close(self):
        try:
            if self._scores_win is not None:
                self._scores_win.destroy()
        except tk.TclError:
            pass
        self.destroy()

    # ── Updates ───────────────────────────────────────────────────────────────
    def _update_panels(self, scores, num_teams, highlight=-1, pulse_highlight=False):
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
        if pulse_highlight and highlight >= 0:
            self._pulse_score_panel(highlight)

    def _set_target_ui(self, name, hex_color, must_press):
        self._swatch_target_hex = hex_color
        self._lbl_avoid.configure(text=name.upper(), fg=hex_color)
        self._lbl_mode_banner.configure(
            text="PRESS this color" if must_press else "DO NOT press this color",
            fg=FG_GREEN if must_press else FG_RED,
        )
        self._flash_swatch_pop(hex_color)
        self._nudge_mode_banner(must_press)

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_game_event(self, event, data):
        self.after(0, lambda e=event, d=data: self._dispatch(e, d))

    def _dispatch(self, event, data):
        if event == "game_start":
            self._lbl_team.configure(text="Color Rush", fg=FG_GOLD)
            self._pop_team_header(big=False)

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
            self._pop_team_header(big=True)
            self._update_panels(
                data["scores"],
                self._game.num_teams,
                highlight=data["team"],
                pulse_highlight=True,
            )

        elif event == "game_over":
            th = TEAM_HEX[data["team"]]
            self._lbl_team.configure(text=f"🏆  {data['name']}  wins!", fg=th)
            self._run_victory_fx(th)
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
        bind = receiver_bind_ip_from_config(self._cfg)
        was_running = self._service._recv_running
        if was_running:
            self._service.stop_receiver()
        self._service.set_device(ip, udp)
        self._service.set_recv_port(recv)
        self._service.set_bind_ip(bind)
        if was_running:
            self._service.start_receiver()
        self._set_status(f"{ip}:{udp}  ·  recv {recv} @ {bind}")

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
        self._hdr_pop_id += 1
        self._score_pop_id += 1
        self._victory_fx_id += 1
        self._swatch_target_hex = "#333333"
        self._swatch_breathe_hold = False
        self._game.start_game(**s)
        self._lbl_team.configure(text="", fg=FG_MAIN, font=("Consolas", 22, "bold"))
        self._swatch.configure(bg="#333333")
        self._lbl_avoid.configure(text="—", fg=FG_MAIN)
        self._lbl_mode_banner.configure(text="", fg=FG_DIM)
        n = s["num_teams"]
        self._update_panels([0] * n, n, highlight=-1)
        self._scores_show()
        self._show_game()

    def _stop_game(self):
        self._hdr_pop_id += 1
        self._score_pop_id += 1
        self._victory_fx_id += 1
        self._game.stop_game()

    def _go_setup(self):
        self._hdr_pop_id += 1
        self._score_pop_id += 1
        self._victory_fx_id += 1
        self._game.stop_game()
        self._scores_hide()
        self._show_setup()

    def _set_status(self, msg):
        try:
            self._status_lbl.configure(text=msg)
            self._game_status.configure(text=msg)
        except tk.TclError:
            pass


if __name__ == "__main__":
    import evil_eye_network_setup

    evil_eye_network_setup.run_startup_discovery_and_save_config()
    ColorRushApp().mainloop()