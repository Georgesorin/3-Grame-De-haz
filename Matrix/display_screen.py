"""
display_screen.py  —  Monitorul de setup și HUD (Interactiv + Sunet)
────────────────────────────────────────────────────────────
"""

import tkinter as tk
import math, time, threading, random
import os

# ── Palette ───────────────────────────────────────────────────────────────────
BG_DARK  = "#060d1a"
BG_PANEL = "#0a1628"
BG_CARD  = "#0d1f3a"
C_CYAN   = "#00f5dc"
C_GOLD   = "#ffc837"
C_RED    = "#ff3232"
C_BLUE   = "#4abeff"
C_GREEN  = "#39ff14"
C_MID    = "#6a9ab8"
C_DIM    = "#2a4a6a"
C_BRIGHT = "#e8f4f8"

PLAYER_COLORS = ["#00f5dc","#ffc837","#c864ff","#39ff14",
                 "#ff6432","#4abeff","#ff3296","#96ff32"]
DIFF_COLORS   = {"Easy":C_GREEN,"Normal":C_GOLD,"Hard":C_RED,"Insane":"#c864ff"}
FT = "Courier New"

class DisplayScreen:
    def __init__(self, master, monitor_offset_x=0, fullscreen=False, on_config_confirmed=None):
        self._master = master 
        self._offset_x   = monitor_offset_x
        self._fullscreen = fullscreen
        self._on_confirm = on_config_confirmed or (lambda n, d: None)

        self._root = self._canvas = None
        self._ready = threading.Event()
        self._lock  = threading.Lock()

        self._state       = "lobby"
        self._anim_t      = 0.0
        self._num_players = 2 
        self._difficulty  = "Normal"
        self._tut_page    = 0
        self._hud         = {}
        self._final       = []

        self._particles = [self._new_particle() for _ in range(50)]

        self._tut = [
            ("CE FACI?",
             "Colectezi comori 💎 pe o harta cu apa si insule.\n"
             "Evita serpii rosii care te urmaresc!"),
            ("CUM INTERACTIONEZI?",
             "Calca pe tile-urile de pe podea pentru a te misca.\n"
             "Power-up-uri: ❄ Freeze serpii, 🛡 Shield contra lovituri."),
            ("CUM CASTIGI?",
             "Colecteaza comori pana completezi wave-ul.\n"
             "Echipa cu cele mai multe puncte la final castiga!"),
        ]

    def set_state(self, state: str):
        with self._lock:
            self._state = state

    def update(self, hud: dict):
        with self._lock:
            self._hud = dict(hud)
            if hud.get("game_over") and self._state == "playing":
                self._state = "gameover"
                self._final = list(hud.get("players", []))

    def run(self):
        self._root = tk.Toplevel(self._master) 
        self._root.title("Matrix — Display Screen")
        self._root.configure(bg=BG_DARK)
        if self._fullscreen:
            self._root.attributes("-fullscreen", True)
        else:
            self._root.geometry(f"1280x720+{self._offset_x}+0")
        
        self._canvas = tk.Canvas(self._root, bg=BG_DARK, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._canvas.bind("<Button-1>", self._on_click)

        self._ready.set()
        self._loop()

    def _loop(self):
        self._anim_t += 0.04
        for p in self._particles:
            p["y"] -= p["vy"]
            if p["y"] < -0.02: p["y"] = 1.02; p["x"] = random.uniform(0, 1)

        with self._lock:
            state = self._state
            hud   = dict(self._hud)

        c = self._canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W > 10 and H > 10:
            t = self._anim_t
            self._bg(c, W, H, t)
            if   state == "lobby":    self._draw_lobby(c, W, H, t)
            elif state == "playing":  self._draw_playing(c, W, H, t, hud)
            elif state == "gameover": self._draw_gameover(c, W, H, t)

        self._root.after(50, self._loop)

    def _bg(self, c, W, H, t):
        for i in range(14):
            y0, y1 = i * H // 14, (i+1) * H // 14
            v = max(0, min(15, int(6 + 5 * math.sin(t*0.25 + i*0.4))))
            c.create_rectangle(0, y0, W, y1, fill=f"#{v:02x}{v+3:02x}{v+10:02x}", outline="")
        for p in self._particles:
            px, py, s = int(p["x"]*W), int(p["y"]*H), p["size"]
            c.create_oval(px-s, py-s, px+s, py+s, fill=p["color"], outline="")

    def _draw_lobby(self, c, W, H, t):
        c.create_rectangle(0, 0, W, 82, fill=BG_PANEL, outline="")
        sz = int(42 + 4*math.sin(t*1.5))
        c.create_text(W//2, 44, text="⬡  MATRIX ROOM  ⬡", font=(FT, sz, "bold"), fill=C_CYAN)

        center_x = W // 2
        self._sec_title(c, center_x, 120, "ALEGE DIFICULTATEA", t)
        
        diffs = ["Easy", "Normal", "Hard", "Insane"]
        bw, bh = 240, 50
        gap = 10
        start_y = 150

        for i, d in enumerate(diffs):
            dy0 = start_y + i * (bh + gap)
            act = (d == self._difficulty)
            dc  = DIFF_COLORS[d]
            c.create_rectangle(center_x - bw//2, dy0, center_x + bw//2, dy0 + bh,
                               fill=BG_CARD, outline=dc, width=3 if act else 1,
                               tags=f"diff_{d}")
            c.create_text(center_x, dy0 + bh//2, text=d.upper(),
                          font=(FT, 16, "bold"), fill=C_BRIGHT if act else dc,
                          tags=f"diff_{d}")

        ty = 420
        c.create_text(W//2, ty, text=self._tut[self._tut_page][1],
                      font=(FT, 14), fill=C_MID, justify="center", width=W-100)

        bsx, bsy = W//2, H - 100
        c.create_rectangle(bsx-150, bsy-30, bsx+150, bsy+30, fill=C_GREEN, tags="start_btn")
        c.create_text(bsx, bsy, text="▶ START JOC", font=(FT, 20, "bold"), fill="black", tags="start_btn")

    def _draw_playing(self, c, W, H, t, hud):
        players = hud.get("players", [])
        level   = hud.get("level", 1)
        wgems   = hud.get("wave_gems", 0)
        wneed   = hud.get("wave_need", 10) or 10
        msg     = hud.get("hud_msg", "")
        
        # Header Simplu
        c.create_rectangle(0, 0, W, 68, fill=BG_PANEL, outline="")
        c.create_text(W//2, 34, text=f"LEVEL {level}", font=(FT, 28, "bold"), fill=C_GOLD)

        # Player Info (Scor si Vieti)
        for i, p in enumerate(players):
            px = 150 + i * (W // 2)
            pcol = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            c.create_text(px, 120, text=f"PLAYER {i+1}", font=(FT, 18, "bold"), fill=pcol)
            c.create_text(px, 160, text=f"SCOR: {p.get('score', 0)}", font=(FT, 24, "bold"), fill=C_BRIGHT)
            c.create_text(px, 200, text="♥" * p.get('lives', 0), font=(FT, 24), fill=C_RED)

        # Progress Bar
        bar_w, bar_h = W * 0.7, 30
        bar_x, bar_y = (W - bar_w) // 2, H - 150
        pct = min(1.0, wgems / wneed)
        c.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h, outline=C_MID)
        c.create_rectangle(bar_x, bar_y, bar_x + int(bar_w * pct), bar_y + bar_h, fill=C_CYAN)
        c.create_text(W//2, bar_y - 20, text=f"PROGRES: {wgems}/{wneed}", font=(FT, 12), fill=C_MID)

        if msg:
            c.create_text(W//2, H//2, text=msg, font=(FT, 40, "bold"), fill=C_GOLD)

    def _draw_gameover(self, c, W, H, t):
        c.create_rectangle(0,0,W,H,fill=BG_DARK)
        c.create_text(W//2, H//2 - 100, text="GAME OVER", font=(FT, 60, "bold"), fill=C_RED)
        if self._final:
            for i, p in enumerate(sorted(self._final, key=lambda x: x.get('score', 0), reverse=True)):
                txt = f"PLAYER {p.get('id', i)+1}: {p.get('score', 0)} PUNCTE"
                c.create_text(W//2, H//2 + i*40, text=txt, font=(FT, 20), fill=C_BRIGHT)
        c.create_rectangle(W//2-230, H-100, W//2-20, H-50, fill=C_BLUE, tags="restart_btn")
        c.create_text(W//2-125, H-75, text="↺ JOC NOU", font=(FT, 18, "bold"), fill="white", tags="restart_btn")
        c.create_rectangle(W//2+20, H-100, W//2+230, H-50, fill=C_MID, tags="settings_btn")
        c.create_text(W//2+125, H-75, text="⚙ SETARI", font=(FT, 18, "bold"), fill="white", tags="settings_btn")

    def _on_click(self, event):
        item = self._canvas.find_closest(event.x, event.y)
        tags = self._canvas.gettags(item) if item else ()
        with self._lock:
            if self._state == "lobby":
                for tag in tags:
                    if tag.startswith("diff_"): self._difficulty = tag[5:]
                    elif tag == "start_btn":
                        self._on_confirm(2, self._difficulty)
                        self._state = "playing"
            elif self._state == "gameover":
                if "restart_btn" in tags:
                    self._state = "lobby"
                    self._on_confirm(-1, "restart")
                elif "settings_btn" in tags:
                    self._state = "lobby"
                    self._on_confirm(-1, "back_to_settings")

    def _sec_title(self, c, cx, y, text, t):
        v = int(180+60*abs(math.sin(t*1.2)))
        c.create_text(cx, y, text=text, font=(FT,14,"bold"), fill=f"#{v:02x}{v:02x}ff")

    def _new_particle(self):
        return {"x": random.random(), "y": random.random(), "vy": random.uniform(0.0003, 0.001),
                "size": random.uniform(1, 2.5), "color": random.choice([C_CYAN, C_BLUE, C_GOLD, "#ffffff"])}

# ── SCORE SCREEN (ecranul din interior) ──────────────────────────────────────

class ScoreScreen:
    """Ecran separat afisat in sala — arata scorul, nivelul si vietile in timp real."""

    def __init__(self, master, monitor_offset_x=0, fullscreen=False):
        self._master     = master
        self._offset_x   = monitor_offset_x
        self._fullscreen = fullscreen
        self._lock       = threading.Lock()
        self._hud        = {}
        self._state      = "idle"   # idle | playing | gameover
        self._anim_t     = 0.0
        self._root = self._canvas = None

    def set_state(self, state: str):
        with self._lock:
            self._state = state

    def update(self, hud: dict):
        with self._lock:
            self._hud = dict(hud)
            if hud.get("game_over") and self._state == "playing":
                self._state = "gameover"

    def run(self):
        self._root = tk.Toplevel(self._master)
        self._root.title("Matrix — Score")
        self._root.configure(bg=BG_DARK)
        if self._fullscreen:
            self._root.attributes("-fullscreen", True)
        else:
            self._root.geometry(f"1280x720+{self._offset_x}+0")
        self._canvas = tk.Canvas(self._root, bg=BG_DARK, highlightthickness=0)
        self._canvas.pack(fill=tk.BOTH, expand=True)
        self._loop()

    def _loop(self):
        self._anim_t += 0.04
        with self._lock:
            state = self._state
            hud   = dict(self._hud)
        c = self._canvas
        c.delete("all")
        W, H = c.winfo_width(), c.winfo_height()
        if W > 10 and H > 10:
            t = self._anim_t
            for i in range(14):
                y0, y1 = i * H // 14, (i+1) * H // 14
                v = max(0, min(15, int(6 + 5 * math.sin(t*0.25 + i*0.4))))
                c.create_rectangle(0, y0, W, y1, fill=f"#{v:02x}{v+3:02x}{v+10:02x}", outline="")
            if   state == "playing":  self._draw_hud(c, W, H, t, hud)
            elif state == "gameover": self._draw_gameover(c, W, H, t, hud)
            else:
                sz = int(42 + 4*math.sin(t*1.5))
                c.create_text(W//2, H//2, text="⬡  MATRIX ROOM  ⬡",
                              font=(FT, sz, "bold"), fill=C_CYAN)
        self._root.after(50, self._loop)

    def _draw_hud(self, c, W, H, t, hud):
        players = hud.get("players", [])
        level   = hud.get("level", 1)
        wgems   = hud.get("wave_gems", 0)
        wneed   = hud.get("wave_need", 10) or 10
        msg     = hud.get("hud_msg", "")
        frozen  = hud.get("frozen", False)

        # Level header
        c.create_rectangle(0, 0, W, 110, fill=BG_PANEL, outline="")
        c.create_text(W//2, 55, text=f"LEVEL  {level}",
                      font=(FT, 56, "bold"), fill=C_GOLD)

        # Players — scor mare, inimi
        n = max(len(players), 1)
        col_w = W // n
        for i, p in enumerate(players):
            cx = col_w * i + col_w // 2
            pcol = PLAYER_COLORS[i % len(PLAYER_COLORS)]
            c.create_text(cx, 155, text=f"PLAYER {i+1}",
                          font=(FT, 22, "bold"), fill=pcol)
            c.create_text(cx, 250, text=str(p.get("score", 0)),
                          font=(FT, 80, "bold"), fill=C_BRIGHT)
            c.create_text(cx, 340, text="♥" * p.get("lives", 0),
                          font=(FT, 34), fill=C_RED)

        # Progress bar
        bar_w = int(W * 0.80)
        bar_h = 38
        bar_x = (W - bar_w) // 2
        bar_y = H - 160
        pct   = min(1.0, wgems / wneed)
        c.create_rectangle(bar_x, bar_y, bar_x + bar_w, bar_y + bar_h,
                           outline=C_MID, width=2, fill="")
        if pct > 0:
            c.create_rectangle(bar_x, bar_y, bar_x + int(bar_w * pct), bar_y + bar_h,
                               fill=C_CYAN, outline="")
        c.create_text(W//2, bar_y - 22,
                      text=f"COMORI: {wgems} / {wneed}", font=(FT, 16), fill=C_MID)

        if frozen:
            c.create_text(W//2, H - 95, text="❄  FREEZE ACTIV  ❄",
                          font=(FT, 22, "bold"), fill="#4abeff")
        if msg:
            sz = int(52 + 6 * abs(math.sin(t * 8)))
            c.create_text(W//2, H // 2 + 20, text=msg,
                          font=(FT, sz, "bold"), fill=C_GOLD)

    def _draw_gameover(self, c, W, H, t, hud):
        v = int(80 + 60 * abs(math.sin(t * 1.5)))
        c.create_text(W//2, H//2 - 80, text="GAME OVER",
                      font=(FT, 80, "bold"), fill=f"#ff{v:02x}{v:02x}")
        players = hud.get("players", [])
        if players:
            ranked = sorted(players, key=lambda p: p.get("score", 0), reverse=True)
            for i, p in enumerate(ranked):
                col = PLAYER_COLORS[(p.get("id", i)) % len(PLAYER_COLORS)]
                c.create_text(W//2, H//2 + 30 + i*52,
                              text=f"#{i+1}  PLAYER {p.get('id',i)+1}  —  {p.get('score',0)} PTS",
                              font=(FT, 28, "bold"), fill=col)


def launch_score_screen(master, monitor_offset_x=0, fullscreen=False):
    screen = ScoreScreen(master, monitor_offset_x, fullscreen)
    master.after(0, screen.run)
    return screen


# ── FUNCTIA PLAY_SOUND ──
def play_sound(path: str):
    """Play a sound file (full path, MP3 or WAV) in a background thread."""
    import threading
    def _play():
        try:
            import pygame.mixer as mx
            if not mx.get_init():
                mx.init(frequency=44100, size=-16, channels=2, buffer=512)
            if os.path.exists(path):
                mx.Sound(path).play()
        except Exception as e:
            print(f"[sound] {e}")
    threading.Thread(target=_play, daemon=True).start()

def launch_display_screen(master, monitor_offset_x=0, fullscreen=False, on_config_confirmed=None):
    screen = DisplayScreen(master, monitor_offset_x, fullscreen, on_config_confirmed)
    screen.run()
    return screen