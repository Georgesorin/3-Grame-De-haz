"""
Controller.py  —  Matrix Room Controller
─────────────────────────────────────────
Structura:
  NetworkManager  – trimite/primeste UDP
  MatrixGUI       – fereastra principala + game loop
  ConfigDialog    – dialog setari retea

Jocurile sunt in games/  si sunt apelate din MatrixGUI.
Al doilea monitor e in display_screen.py.
"""

import tkinter as tk
from tkinter import colorchooser, ttk
import socket
import threading
import time
import random
import math
import colorsys
import os
import json
import psutil

from matrix_font import FONT_5x7
from small_font  import FONT_3x5
from games.chase_game    import ChaseGame, BOARD_WIDTH, BOARD_HEIGHT
from display_screen      import launch_display_screen

# ── Config ────────────────────────────────────────────────────────────────────
_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrix_ctrl_config.json")

def _load_config():
    defaults = {
        "device_ip":           "255.255.255.255",
        "send_port":           4626,
        "recv_port":           7800,
        "auto_start_streaming": False,
        "last_used_ports":     [],
        "bind_ip":             "0.0.0.0",
        "display_screen":      True,
        "monitor_offset_x":    1920,
    }
    try:
        if os.path.exists(_CFG_FILE):
            with open(_CFG_FILE, encoding="utf-8") as f:
                defaults.update(json.load(f))
        return defaults
    except:
        return defaults

def _save_config(cfg):
    try:
        with open(_CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
    except:
        pass

CONFIG = _load_config()

# ── Constants ─────────────────────────────────────────────────────────────────
NUM_CHANNELS      = 8
LEDS_PER_CHANNEL  = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BLACK   = (0,   0,   0)
WHITE   = (255, 255, 255)
RED     = (255, 0,   0)
GREEN   = (0,   255, 0)
BLUE    = (0,   0,   255)
YELLOW  = (255, 255, 0)
CYAN    = (0,   255, 255)
MAGENTA = (255, 0,   255)
ORANGE  = (255, 165, 0)


# ── NetworkManager ────────────────────────────────────────────────────────────
class NetworkManager:
    def __init__(self):
        self.sock_send      = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.running        = True
        self.sequence_number = 0
        self.bind_ip        = CONFIG.get("bind_ip", "0.0.0.0")
        self.target_ip      = CONFIG.get("device_ip", "255.255.255.255")
        self.send_port      = CONFIG.get("send_port", 4626)

    def set_interface(self, ip: str):
        if self.bind_ip == ip:
            return
        self.bind_ip = ip
        print(f"[NET] Binding to {self.bind_ip}")
        try:
            self.sock_send.close()
            self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if self.bind_ip != "0.0.0.0":
                self.sock_send.bind((self.bind_ip, 0))
        except Exception as e:
            print(f"[NET] Error binding: {e}")

    def send_packet(self, frame_data: dict):
        """
        Trimite un frame complet (dict {(x,y): (r,g,b)}) la device.
        """
        raw = self._build_raw(frame_data)
        self._send_raw(raw)

    def _set_pixel_raw(self, buf, x, y, r, g, b):
        channel = y // 4
        row     = y % 4
        idx     = (row * 16 + x) if row % 2 == 0 else (row * 16 + (15 - x))
        offset  = idx * 24 + channel
        if offset + 16 < len(buf):
            buf[offset]      = g   # GRB swap
            buf[offset + 8]  = r
            buf[offset + 16] = b

    def _build_raw(self, frame_data: dict) -> bytearray:
        buf = bytearray(FRAME_DATA_LENGTH)
        for (x, y), (r, g, b) in frame_data.items():
            if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
                self._set_pixel_raw(buf, x, y, r, g, b)
        return buf

    def _send_raw(self, raw: bytearray):
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0:
            self.sequence_number = 1

        target_ip = self.target_ip
        port      = self.send_port

        def _pkt(payload: bytearray, checksum_byte: int) -> bytearray:
            r1 = random.randint(0, 127)
            r2 = random.randint(0, 127)
            length = len(payload) - 1
            pkt = bytearray([0x75, r1, r2,
                              (length >> 8) & 0xFF, length & 0xFF])
            pkt += payload
            pkt.append(checksum_byte)
            pkt.append(0x00)
            return pkt

        def _send(pkt):
            try:
                self.sock_send.sendto(pkt, (target_ip, port))
                self.sock_send.sendto(pkt, ("127.0.0.1", port))
            except:
                pass

        # Start
        start_inner = bytearray([
            0x02, 0x00, 0x00, 0x33, 0x44,
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00,
        ])
        _send(_pkt(start_inner, 0x0E))

        # FFF0
        fff0_payload = bytearray()
        for _ in range(NUM_CHANNELS):
            fff0_payload += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])
        fff0_inner = bytearray([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0,
                                 (len(fff0_payload) >> 8) & 0xFF,
                                  len(fff0_payload) & 0xFF]) + fff0_payload
        _send(_pkt(fff0_inner, 0x1E))

        # Data chunks
        chunk_size = 984
        for idx, i in enumerate(range(0, len(raw), chunk_size), start=1):
            chunk = raw[i:i + chunk_size]
            inner = bytearray([0x02, 0x00, 0x00, 0x88, 0x77,
                                (idx >> 8) & 0xFF, idx & 0xFF,
                                (len(chunk) >> 8) & 0xFF, len(chunk) & 0xFF])
            inner += chunk
            cs = 0x1E if len(chunk) == 984 else 0x36
            _send(_pkt(inner, cs))
            time.sleep(0.002)

        # End
        end_inner = bytearray([
            0x02, 0x00, 0x00, 0x55, 0x66,
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00,
        ])
        _send(_pkt(end_inner, 0x0E))


# ── MatrixGUI ─────────────────────────────────────────────────────────────────
class MatrixGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.display_screen = None
        self.root.title("Matrix Room Controller")
        self.root.configure(bg="#1a1a1a")

        self.grid_width  = BOARD_WIDTH
        self.grid_height = BOARD_HEIGHT

        self.current_color   = RED
        self.is_sending      = False
        self.cell_size       = 20
        self.animation_mode  = "Manual"
        self.time_counter    = 0

        # Starea manuala a grid-ului
        self.grid_data = {(x, y): BLACK
                          for y in range(BOARD_HEIGHT)
                          for x in range(BOARD_WIDTH)}

        # Network
        self.network    = NetworkManager()
        self.send_lock  = threading.Lock()

        # Trigger states din podea: (ch, led) -> bool
        self.trigger_states = {}

        # ── Jocul activ ──────────────────────────────────────────────────────
        self.active_game: ChaseGame | None = None

        # ── Display screen (al doilea monitor) ───────────────────────────────
        self.root.after(0, self._init_display_screen)

        # Receiver
        self.port_out_var    = tk.StringVar(value=str(CONFIG.get("send_port", 4626)))
        self.port_in_var     = tk.StringVar(value=str(CONFIG.get("recv_port", 7800)))
        self.receiver_running = True
        self.sock_recv        = None
        self._bind_receiver()
        threading.Thread(target=self._receiver_loop, daemon=True).start()

        # UI
        self._build_ui()

        if CONFIG.get("auto_start_streaming", False):
            self.root.after(1000, self.toggle_sending)

    def _init_display_screen(self):
        try:
            # Trimite self.root ca prim argument
            self.display_screen = launch_display_screen(
                self.root, 
                monitor_offset_x=CONFIG.get("monitor_offset_x", 0),
                fullscreen=CONFIG.get("display_fullscreen", False),
                on_config_confirmed=self._on_lobby_start,
            )
            print("[DISPLAY] Second screen launched as Toplevel.")
        except Exception as e:
            print(f"[DISPLAY] Error: {e}")
    # ── UI ────────────────────────────────────────────────────────────────────


    def _build_ui(self):
        main_frame = tk.Frame(self.root, bg="#1a1a1a")
        main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(main_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<B1-Motion>", self._on_paint)
        self.canvas.bind("<Button-1>",  self._on_paint)
        self.canvas.bind("<Configure>", self._on_resize)

        ctrl = tk.Frame(self.root, width=210, bg="#222")
        ctrl.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)

        def _btn(parent, text, cmd, bg="#444"):
            return tk.Button(parent, text=text, command=cmd,
                             bg=bg, fg="white", font=("Consolas", 9, "bold"),
                             relief="flat")

        tk.Label(ctrl, text="MATRIX CONTROLLER", bg="#222", fg=ACCENT_COL,
                 font=("Consolas", 10, "bold")).pack(pady=(5, 3))

        _btn(ctrl, "⚙  Config",        self._open_config).pack(fill=tk.X, padx=5, pady=2)

        self.btn_send = _btn(ctrl, "▶  START STREAM", self.toggle_sending, bg="#1a5c1a")
        self.btn_send.pack(fill=tk.X, padx=5, pady=2)

        _btn(ctrl, "Clear Board", self.clear_board).pack(fill=tk.X, padx=5, pady=2)

        # Separator
        tk.Frame(ctrl, bg="#444", height=1).pack(fill=tk.X, padx=5, pady=6)

        # Animation mode
        tk.Label(ctrl, text="MODE", bg="#222", fg="#888",
                 font=("Consolas", 9, "bold")).pack()
        self.anim_var   = tk.StringVar(value="Manual")
        self.anim_combo = ttk.Combobox(ctrl, textvariable=self.anim_var, state="readonly")
        self.anim_combo["values"] = (
            "Manual", "Rainbow Wave", "Pulse", "Matrix Rain",
            "Sparkle", "Text", "Scrolling Text", "Chase Mode",
        )
        self.anim_combo.pack(fill=tk.X, padx=5, pady=3)
        self.anim_combo.bind("<<ComboboxSelected>>", self._on_anim_change)

        # Text settings
        txt_frame = tk.LabelFrame(ctrl, text=" Text ", bg="#222", fg="#aaa",
                                   font=("Consolas", 8, "bold"))
        txt_frame.pack(fill=tk.X, padx=5, pady=4)
        self.text_var = tk.StringVar(value="HELLO")
        tk.Entry(txt_frame, textvariable=self.text_var, bg="#111", fg="#0f0",
                 font=("Consolas", 9), insertbackground="white").pack(fill=tk.X, padx=4, pady=3)
        sf = tk.Frame(txt_frame, bg="#222")
        sf.pack(fill=tk.X, padx=4)
        for label, attr in [("X:", "text_x"), ("Y:", "text_y")]:
            tk.Label(sf, text=label, bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
            sb = tk.Spinbox(sf, from_=-100, to=max(BOARD_WIDTH, BOARD_HEIGHT), width=4)
            sb.pack(side=tk.LEFT, padx=(0, 4))
            setattr(self, attr, sb)
        rf = tk.Frame(txt_frame, bg="#222")
        rf.pack(fill=tk.X, padx=4, pady=3)
        tk.Label(rf, text="Rot:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_rot = ttk.Combobox(rf, values=("0","90","180","270"), width=4)
        self.text_rot.set("0")
        self.text_rot.pack(side=tk.LEFT, padx=(0,4))
        tk.Label(rf, text="Size:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_size = tk.Spinbox(rf, from_=1, to=10, width=3)
        self.text_size.pack(side=tk.LEFT)

        # Colors
        tk.Frame(ctrl, bg="#444", height=1).pack(fill=tk.X, padx=5, pady=6)
        tk.Label(ctrl, text="COLORS", bg="#222", fg="#888",
                 font=("Consolas", 9, "bold")).pack()
        self.btn_custom = _btn(ctrl, "Pick Color", self.pick_color)
        self.btn_custom.pack(fill=tk.X, padx=5, pady=2)

        cf = tk.Frame(ctrl, bg="#222")
        cf.pack(fill=tk.X, padx=5)
        palette = [("Red",RED),("Green",GREEN),("Blue",BLUE),
                   ("Yellow",YELLOW),("Cyan",CYAN),("Magenta",MAGENTA),
                   ("Orange",ORANGE),("White",WHITE),("OFF",BLACK)]
        for i, (name, col) in enumerate(palette):
            fg  = "black" if sum(col) > 300 else "white"
            hex_c = "#%02x%02x%02x" % col if name != "OFF" else "#111"
            tk.Button(cf, text=name, command=lambda c=col: self.set_color(c),
                      font=("Consolas", 8, "bold"), relief="flat",
                      bg=hex_c, fg=fg).grid(row=i//2, column=i%2, sticky="ew", padx=1, pady=1)
        cf.grid_columnconfigure(0, weight=1)
        cf.grid_columnconfigure(1, weight=1)

        # Chase: num players
        self._num_players_var = tk.IntVar(value=1)
        self._chase_frame = tk.LabelFrame(ctrl, text=" Chase Settings ",
                                           bg="#222", fg="#aaa", font=("Consolas", 8, "bold"))
        tk.Label(self._chase_frame, text="Nr. jucatori:", bg="#222", fg="#aaa",
                 font=("Consolas", 8)).pack(side=tk.LEFT, padx=4)
        tk.Spinbox(self._chase_frame, from_=1, to=4, width=3,
                   textvariable=self._num_players_var).pack(side=tk.LEFT)

        # Net status
        self.lbl_net = tk.Label(ctrl,
                                 text=f"→ {self.network.target_ip}:{self.network.send_port}",
                                 bg="#222", fg="#66aa66", font=("Consolas", 8))
        self.lbl_net.pack(pady=6)

    # ── Animation mode ────────────────────────────────────────────────────────

    def _on_anim_change(self, _event=None):
        prev = self.animation_mode
        self.animation_mode = self.anim_var.get()
        print(f"[MODE] {prev} → {self.animation_mode}")

        # Opreste jocul anterior
        if prev == "Chase Mode" and self.active_game:
            self.active_game.stop()
            self.active_game = None
            self._unbind_chase_keys()
            self._chase_frame.pack_forget()

        if self.animation_mode == "Chase Mode":
            n_players = self._num_players_var.get()
            self.active_game = ChaseGame(
                num_players=n_players,
                on_game_event=self._on_chase_event,
            )
            self.active_game.start()
            self._chase_frame.pack(fill=tk.X, padx=5, pady=4)
            self._bind_chase_keys()
            self.canvas.focus_set()
            if self.display_screen:
                self.display_screen.set_game("CHASE")

    def _on_lobby_start(self, num_players: int, difficulty: str):
        """Apelat din display_screen cand jucatorul apasa START sau RESTART."""
        if difficulty == "restart":
            self.root.after(0, self._stop_chase)
            return
        self.root.after(0, lambda: self._start_chase(difficulty))

    def _stop_chase(self):
        if self.active_game:
            self.active_game.stop()
            self.active_game = None
        if self.is_sending:
            self.toggle_sending()

    def _start_chase(self, difficulty: str):
        """Porneste Chase Mode cu configuratia primita din lobby."""
        self.anim_var.set("Chase Mode")
        if self.active_game:
            self.active_game.stop()
        diff_params = {
            "Easy":   {"base_period": 0.20,  "lives": 5, "snakes_bonus": -1},
            "Normal": {"base_period": 0.12,  "lives": 3, "snakes_bonus": 0},
            "Hard":   {"base_period": 0.07,  "lives": 2, "snakes_bonus": 1},
            "Insane": {"base_period": 0.04,  "lives": 1, "snakes_bonus": 2},
        }.get(difficulty, {})
        self.active_game = ChaseGame(
            on_game_event=self._on_chase_event,
            difficulty_params=diff_params,
        )
        self.active_game.start()
        self.animation_mode = "Chase Mode"
        self._bind_chase_keys()
        self._chase_frame.pack(fill=tk.X, padx=5, pady=4)
        self.canvas.focus_set()
        if self.display_screen:
            self.display_screen.set_state("playing")
        if not self.is_sending:
            self.toggle_sending()

    def _on_chase_event(self, event_name: str, data: dict):
        """Callback din ChaseGame — ruleaza pe game thread."""
        print(f"[GAME EVENT] {event_name}: {data}")
        import os
        from display_screen import play_sound
        _SOUNDS_DIR = os.path.join(os.path.dirname(__file__), "sounds")
        _SOUND_MAP = {
            "game_over": os.path.join(_SOUNDS_DIR, "SUPER MARIO - game over - sound effect.mp3"),
            "level_up":  os.path.join(_SOUNDS_DIR, "Achievement Sound Effect.mp3"),
            "treasure":  os.path.join(_SOUNDS_DIR, "coin.mp3"),
        }
        if event_name == "pickup" and data.get("kind") == "freeze":
            play_sound(os.path.join(_SOUNDS_DIR, "ice.mp3"))
        elif event_name in _SOUND_MAP:
            play_sound(_SOUND_MAP[event_name])

    # ── Chase key bindings ────────────────────────────────────────────────────

    def _bind_chase_keys(self):
        self._chase_keys: set = set()
        self.root.bind("<KeyPress>",   self._on_key_press)
        self.root.bind("<KeyRelease>", self._on_key_release)

    def _unbind_chase_keys(self):
        self._chase_keys = set()
        for seq in ("<KeyPress>", "<KeyRelease>"):
            try:
                self.root.unbind(seq)
            except:
                pass

    def _on_key_press(self, event):
        if self.animation_mode != "Chase Mode" or not self.active_game:
            return
        sym = event.keysym
        self._chase_keys.add(sym)
        DIR = {"Up":(0,-1),"w":(0,-1),"W":(0,-1),
               "Down":(0,1),"s":(0,1),"S":(0,1),
               "Left":(-1,0),"a":(-1,0),"A":(-1,0),
               "Right":(1,0),"d":(1,0),"D":(1,0)}
        if sym in DIR:
            dx, dy = DIR[sym]
            self.active_game.on_key_direction(player_id=0, dx=dx, dy=dy)

    def _on_key_release(self, event):
        self._chase_keys.discard(event.keysym)

    # ── Receiver ─────────────────────────────────────────────────────────────

    def _bind_receiver(self):
        try:
            if self.sock_recv:
                self.sock_recv.close()
        except:
            pass
        p_in = int(self.port_in_var.get())
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_recv.settimeout(0.5)
        try:
            self.sock_recv.bind(("0.0.0.0", p_in))
            print(f"[NET] Receiver bound to port {p_in}")
        except Exception as e:
            print(f"[NET] Cannot bind receiver to {p_in}: {e}")

    def _receiver_loop(self):
        while self.receiver_running:
            try:
                data, addr = self.sock_recv.recvfrom(4096)
                if len(data) >= 1373 and data[0] == 0x88:
                    self._parse_trigger_packet(data)
            except socket.timeout:
                continue
            except Exception as e:
                print(f"[RECV] Error: {e}")

    def _parse_trigger_packet(self, data: bytes):
        changed = False
        for ch in range(8):
            base = 2 + ch * 171
            for led in range(64):
                state = (data[base + 1 + led] == 0xCC)
                if self.trigger_states.get((ch, led), False) != state:
                    self.trigger_states[(ch, led)] = state
                    changed = True
                    if state:
                        # Calculeaza (x, y) din (ch, led)
                        row = led // 16
                        x   = (led % 16) if row % 2 == 0 else (15 - (led % 16))
                        y   = ch * 4 + row
                        self._on_tile_pressed(x, y)

        if changed:
            self.root.after(0, self.draw_grid)

    def _on_tile_pressed(self, x: int, y: int):
        """Apelat cand un tile fizic e apasat."""
        print(f"[TILE] Pressed ({x}, {y})")
        if self.animation_mode == "Chase Mode" and self.active_game:
            self.active_game.on_tile_pressed(x, y, player_id=0)

    # ── Render & send loop ────────────────────────────────────────────────────

    def _render_frame(self) -> dict:
        mode = self.animation_mode

        if mode == "Chase Mode" and self.active_game:
            frame = self.active_game.get_frame(self.time_counter)
            # Update al doilea monitor
            if self.display_screen:
                self.display_screen.update(self.active_game.get_hud_info())
            return frame

        if mode == "Manual":
            return dict(self.grid_data)

        # Animatii simple
        frame = {}
        tc    = self.time_counter

        if mode == "Rainbow Wave":
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    hue = (x / BOARD_WIDTH + y / BOARD_HEIGHT * 0.5 + tc * 0.01) % 1.0
                    r, g, b = [int(v * 255) for v in colorsys.hsv_to_rgb(hue, 1.0, 1.0)]
                    frame[(x, y)] = (r, g, b)

        elif mode == "Pulse":
            brightness = (math.sin(tc * 0.1) + 1) / 2
            col = tuple(int(c * brightness) for c in self.current_color)
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    frame[(x, y)] = col

        elif mode == "Matrix Rain":
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    val = int(abs(math.sin(tc * 0.05 + x * 0.7 + y * 0.3)) * 200)
                    frame[(x, y)] = (0, val, 0)

        elif mode == "Sparkle":
            frame = {k: BLACK for k in self.grid_data}
            for _ in range(8):
                rx = random.randint(0, BOARD_WIDTH - 1)
                ry = random.randint(0, BOARD_HEIGHT - 1)
                frame[(rx, ry)] = WHITE

        elif mode in ("Text", "Scrolling Text"):
            frame = self._render_text_frame()

        else:
            frame = dict(self.grid_data)

        return frame

    def _render_text_frame(self) -> dict:
        frame = {(x, y): BLACK for y in range(BOARD_HEIGHT) for x in range(BOARD_WIDTH)}
        text_str = self.text_var.get()
        try:
            rot = int(self.text_rot.get())
        except:
            rot = 0
        try:
            scale_input = int(self.text_size.get())
        except:
            scale_input = 1

        if scale_input == 1:
            cur_font = FONT_3x5
            char_w, char_h, render_scale = 3, 5, 1
        else:
            cur_font = FONT_5x7
            char_w, char_h = 5, 7
            render_scale = scale_input - 1

        try:
            start_vy = int(self.text_y.get())
        except:
            start_vy = 0

        if self.animation_mode == "Scrolling Text":
            text_width = len(text_str) * (char_w + 1) * render_scale
            screen_len = BOARD_WIDTH if rot in (0, 180) else BOARD_HEIGHT
            total_scroll = max(1, text_width + screen_len)
            vx_offset = screen_len - (int(self.time_counter * 1.0) % total_scroll)
        else:
            try:
                vx_offset = int(self.text_x.get())
            except:
                vx_offset = 0

        for char_idx, char in enumerate(text_str):
            char_data = cur_font.get(char, cur_font.get("?", [0] * char_w))
            for col_idx, col_byte in enumerate(char_data):
                for sx in range(render_scale):
                    vx = vx_offset + (char_idx * (char_w + 1) * render_scale) + (col_idx * render_scale) + sx
                    for row_idx in range(char_h):
                        if (col_byte >> row_idx) & 1:
                            for sy in range(render_scale):
                                vy = start_vy + row_idx * render_scale + sy
                                if rot == 0:
                                    px, py = vx, vy
                                elif rot == 90:
                                    px, py = BOARD_WIDTH - 1 - vy, vx
                                elif rot == 180:
                                    px, py = BOARD_WIDTH - 1 - vx, BOARD_HEIGHT - 1 - vy
                                else:
                                    px, py = vy, BOARD_HEIGHT - 1 - vx
                                if 0 <= px < BOARD_WIDTH and 0 <= py < BOARD_HEIGHT:
                                    frame[(px, py)] = self.current_color
        return frame

    def sending_loop(self):
        while self.is_sending:
            frame = self._render_frame()
            self.network.send_packet(frame)
            self.time_counter += 1
            time.sleep(0.05)   # ~20 FPS

    def toggle_sending(self):
        self.is_sending = not self.is_sending
        if self.is_sending:
            self.btn_send.config(text="■  STOP STREAM", bg="#5c1a1a")
            threading.Thread(target=self.sending_loop, daemon=True).start()
        else:
            self.btn_send.config(text="▶  START STREAM", bg="#1a5c1a")

    # ── Grid drawing (preview in controller window) ────────────────────────────

    def draw_grid(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10 or h < 10:
            return
        cs  = min(w / BOARD_WIDTH, h / BOARD_HEIGHT)
        ox  = (w - cs * BOARD_WIDTH)  / 2
        oy  = (h - cs * BOARD_HEIGHT) / 2

        src = self.grid_data
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                r, g, b = src.get((x, y), BLACK)
                col  = "#%02x%02x%02x" % (r, g, b)
                ch   = y // 4
                row  = y % 4
                led  = (row * 16 + x) if row % 2 == 0 else (row * 16 + (15 - x))
                trig = self.trigger_states.get((ch, led), False)
                self.canvas.create_rectangle(
                    ox + x * cs, oy + y * cs,
                    ox + (x+1)*cs, oy + (y+1)*cs,
                    fill=col,
                    outline="white" if trig else "#222",
                    width=2 if trig else 1,
                )

    def _on_resize(self, _event=None):
        self.draw_grid()

    def _on_paint(self, event):
        if self.animation_mode != "Manual":
            return
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        cs = min(w / BOARD_WIDTH, h / BOARD_HEIGHT)
        ox = (w - cs * BOARD_WIDTH)  / 2
        oy = (h - cs * BOARD_HEIGHT) / 2
        gx = int((event.x - ox) // cs)
        gy = int((event.y - oy) // cs)
        if 0 <= gx < BOARD_WIDTH and 0 <= gy < BOARD_HEIGHT:
            self.grid_data[(gx, gy)] = self.current_color
            self.draw_grid()

    # ── Utilities ─────────────────────────────────────────────────────────────

    def clear_board(self):
        for k in self.grid_data:
            self.grid_data[k] = BLACK
        self.draw_grid()

    def set_color(self, color):
        self.current_color = color

    def pick_color(self):
        result = colorchooser.askcolor(title="Choose Color")
        if result[0]:
            rgb = tuple(int(v) for v in result[0])
            self.set_color(rgb)
            self.btn_custom.config(
                bg=result[1],
                fg="black" if sum(rgb) > 300 else "white",
            )

    def rgb_to_hex(self, rgb):
        return "#%02x%02x%02x" % rgb

    # ── Config dialog ─────────────────────────────────────────────────────────

    def _open_config(self):
        ConfigDialog(self.root, CONFIG, self._on_config_saved)

    def _on_config_saved(self, new_cfg):
        global CONFIG
        CONFIG = new_cfg
        _save_config(CONFIG)
        self.network.target_ip = CONFIG["device_ip"]
        self.network.send_port = CONFIG["send_port"]
        if "bind_ip" in CONFIG:
            self.network.set_interface(CONFIG["bind_ip"])
        self._bind_receiver()
        self.lbl_net.config(text=f"→ {self.network.target_ip}:{self.network.send_port}")


# Accent color helper (used in _build_ui)
ACCENT_COL = "#00ccaa"


# ── Config Dialog ─────────────────────────────────────────────────────────────
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, cfg, on_save):
        super().__init__(parent)
        self.title("Matrix Network Config")
        self.configure(bg="#1a1a1a")
        self.resizable(False, False)
        self.grab_set()
        self.cfg     = dict(cfg)
        self.on_save = on_save

        self.sv_ip       = tk.StringVar(value=cfg.get("device_ip", "255.255.255.255"))
        self.sv_send     = tk.StringVar(value=str(cfg.get("send_port", 4626)))
        self.sv_recv     = tk.StringVar(value=str(cfg.get("recv_port", 7800)))
        self.sv_auto     = tk.BooleanVar(value=cfg.get("auto_start_streaming", False))
        self.sv_display  = tk.BooleanVar(value=cfg.get("display_screen", True))
        self.sv_offset   = tk.StringVar(value=str(cfg.get("monitor_offset_x", 1920)))
        self.sv_iface    = tk.StringVar(value=cfg.get("bind_ip", "0.0.0.0"))
        self._build()

    def _build(self):
        pad = dict(padx=15, pady=4, sticky="we")

        def _lbl(text, row):
            tk.Label(self, text=text, bg="#1a1a1a", fg="#aaa",
                     font=("Consolas", 9)).grid(row=row, column=0, **pad)

        def _ent(sv, row):
            tk.Entry(self, textvariable=sv, bg="#111", fg="white",
                     font=("Consolas", 9), insertbackground="white",
                     width=22).grid(row=row, column=1, padx=5, pady=4, sticky="we")

        tk.Label(self, text="NETWORK", bg="#2a2a2a", fg="#ff8844",
                 font=("Consolas", 10, "bold")).grid(row=0, column=0, columnspan=2,
                                                      padx=10, pady=(10,4), sticky="we")
        _lbl("Target IP:",      1); _ent(self.sv_ip,   1)
        _lbl("Port OUT (send):", 2); _ent(self.sv_send, 2)
        _lbl("Port IN (recv):",  3); _ent(self.sv_recv, 3)

        tk.Checkbutton(self, text="Auto-start stream on launch",
                       variable=self.sv_auto, bg="#1a1a1a", fg="white",
                       selectcolor="#333", activebackground="#1a1a1a",
                       activeforeground="white",
                       font=("Consolas", 9)).grid(row=4, column=0, columnspan=2,
                                                    padx=10, pady=4, sticky="w")

        tk.Label(self, text="DISPLAY SCREEN", bg="#2a2a2a", fg="#ff8844",
                 font=("Consolas", 10, "bold")).grid(row=5, column=0, columnspan=2,
                                                      padx=10, pady=(10,4), sticky="we")
        tk.Checkbutton(self, text="Enable second monitor",
                       variable=self.sv_display, bg="#1a1a1a", fg="white",
                       selectcolor="#333", activebackground="#1a1a1a",
                       activeforeground="white",
                       font=("Consolas", 9)).grid(row=6, column=0, columnspan=2,
                                                    padx=10, pady=2, sticky="w")
        _lbl("Monitor X offset:", 7); _ent(self.sv_offset, 7)

        tk.Label(self, text="INTERFACE", bg="#2a2a2a", fg="#ff8844",
                 font=("Consolas", 10, "bold")).grid(row=8, column=0, columnspan=2,
                                                      padx=10, pady=(10,4), sticky="we")
        ips = ["0.0.0.0", "127.0.0.1"]
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address not in ips:
                        ips.append(addr.address)
        except:
            pass
        combo = ttk.Combobox(self, textvariable=self.sv_iface, values=ips, state="readonly")
        combo.grid(row=9, column=0, columnspan=2, padx=15, pady=4, sticky="we")

        bf = tk.Frame(self, bg="#1a1a1a")
        bf.grid(row=10, column=0, columnspan=2, pady=12)
        tk.Button(bf, text="💾 Save", command=self._save,
                  bg="#226", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=15, pady=6).pack(side=tk.LEFT, padx=5)
        tk.Button(bf, text="Cancel", command=self.destroy,
                  bg="#333", fg="white", font=("Consolas", 9),
                  relief="flat", padx=15, pady=6).pack(side=tk.LEFT, padx=5)

    def _save(self):
        try:
            self.cfg["device_ip"]            = self.sv_ip.get().strip()
            self.cfg["send_port"]            = int(self.sv_send.get())
            self.cfg["recv_port"]            = int(self.sv_recv.get())
            self.cfg["auto_start_streaming"] = self.sv_auto.get()
            self.cfg["display_screen"]       = self.sv_display.get()
            self.cfg["monitor_offset_x"]     = int(self.sv_offset.get())
            self.cfg["bind_ip"]              = self.sv_iface.get()
            self.on_save(self.cfg)
            self.destroy()
        except ValueError:
            pass


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    root = tk.Tk()
    app  = MatrixGUI(root)
    root.mainloop()