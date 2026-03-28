import tkinter as tk
from tkinter import ttk
import socket
import threading
import time
import json
import os
import psutil
from datetime import datetime

# --- Configuration ---
_CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eye_sim_config.json")

def _load_config():
    defaults = {
        "send_port": 7800,
        "recv_port": 4626,
        "device_ip": "255.255.255.255",
        "last_used_ports": []
    }
    try:
        if os.path.exists(_CFG_FILE):
            with open(_CFG_FILE, encoding="utf-8") as f:
                data = json.load(f)
                defaults.update(data)
        return defaults
    except:
        return defaults

def _save_config(config):
    try:
        with open(_CFG_FILE, 'w', encoding="utf-8") as f:
            json.dump(config, f, indent=4)
    except:
        pass

CONFIG = _load_config()

NUM_CHANNELS     = 4
LEDS_PER_CHANNEL = 11          # 0 = Eye, 1-10 = Buttons
LED_TIMEOUT_SEC  = 3.0

PASSWORD_ARRAY = [
    35, 63, 187, 69, 107, 178, 92, 76, 39, 69, 205, 37, 223, 255, 165, 231,
    16, 220, 99, 61, 25, 203, 203, 155, 107, 30, 92, 144, 218, 194, 226, 88,
    196, 190, 67, 195, 159, 185, 209, 24, 163, 65, 25, 172, 126, 63, 224, 61,
    160, 80, 125, 91, 239, 144, 25, 141, 183, 204, 171, 188, 255, 162, 104, 225,
    186, 91, 232, 3, 100, 208, 49, 211, 37, 192, 20, 99, 27, 92, 147, 152,
    86, 177, 53, 153, 94, 177, 200, 33, 175, 195, 15, 228, 247, 18, 244, 150,
    165, 229, 212, 96, 84, 200, 168, 191, 38, 112, 171, 116, 121, 186, 147, 203,
    30, 118, 115, 159, 238, 139, 60, 57, 235, 213, 159, 198, 160, 50, 97, 201,
    253, 242, 240, 77, 102, 12, 183, 235, 243, 247, 75, 90, 13, 236, 56, 133,
    150, 128, 138, 190, 140, 13, 213, 18, 7, 117, 255, 45, 69, 214, 179, 50,
    28, 66, 123, 239, 190, 73, 142, 218, 253, 5, 212, 174, 152, 75, 226, 226,
    172, 78, 35, 93, 250, 238, 19, 32, 247, 223, 89, 123, 86, 138, 150, 146,
    214, 192, 93, 152, 156, 211, 67, 51, 195, 165, 66, 10, 10, 31, 1, 198,
    234, 135, 34, 128, 208, 200, 213, 169, 238, 74, 221, 208, 104, 170, 166, 36,
    76, 177, 196, 3, 141, 167, 127, 56, 177, 203, 45, 107, 46, 82, 217, 139,
    168, 45, 198, 6, 43, 11, 57, 88, 182, 84, 189, 29, 35, 143, 138, 171,
]

class WallCanvas(tk.Canvas):
    LAYOUT_ROWS = 3
    LAYOUT_COLS = 5

    def __init__(self, parent, channel, on_press, on_release, **kwargs):
        super().__init__(parent, bg="#111", highlightthickness=0, **kwargs)
        self._ch = channel
        self._on_press = on_press
        self._on_rel = on_release
        self._colors = [(0, 0, 0)] * LEDS_PER_CHANNEL
        self._items = {}
        self.bind("<Configure>", self._redraw)
        self.bind("<ButtonPress-1>", self._click_press)
        self.bind("<ButtonRelease-1>", self._click_release)

    def set_color(self, index, r, g, b):
        self._colors[index] = (r, g, b)
        self._apply_color(index)

    def _apply_color(self, index):
        if index not in self._items: return
        iid = self._items[index]
        r, g, b = self._colors[index]
        fill = f"#{r:02x}{g:02x}{b:02x}" if (r or g or b) else ("black" if index == 0 else "#0a0a0a")
        self.itemconfig(iid, fill=fill)
        if index == 0:
            outline = fill if (r or g or b) else "#ff0000"
            self.itemconfig(iid, outline=outline)

    def _cell_rect(self, idx, w, h, pad):
        cell_w = (w - 2 * pad) / self.LAYOUT_COLS
        cell_h = (h - 2 * pad) / self.LAYOUT_ROWS
        if idx == 0:
            cx, cy = w / 2, pad + cell_h * 0.5
            r = min(cell_w, cell_h) * 0.38
            return (cx - r, cy - r, cx + r, cy + r)
        else:
            btn = idx - 1
            row, col = btn // 5 + 1, btn % 5
            x1 = pad + col * cell_w + cell_w * 0.08
            y1 = pad + row * cell_h + cell_h * 0.08
            return (x1, y1, x1 + cell_w * 0.84, y1 + cell_h * 0.84)

    def _redraw(self, event=None):
        self.delete("all")
        self._items.clear()
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10: return
        pad = max(6, min(w, h) * 0.04)
        cell_w, cell_h = (w - 2 * pad) / self.LAYOUT_COLS, (h - 2 * pad) / self.LAYOUT_ROWS
        font_size = max(7, int(min(cell_w, cell_h) * 0.25))

        x1, y1, x2, y2 = self._cell_rect(0, w, h, pad)
        halo = max(4, (x2 - x1) * 0.12)
        self.create_oval(x1 - halo, y1 - halo, x2 + halo, y2 + halo, fill="#111", outline="#333", width=1)
        self._items[0] = self.create_oval(x1, y1, x2, y2, fill="black", outline="#ff0000", width=max(2, halo * 0.5))
        self.create_text(w / 2, y2 + max(4, halo), text="THE EYE", fill="#555", font=("Consolas", font_size - 1))

        for i in range(1, 11):
            x1, y1, x2, y2 = self._cell_rect(i, w, h, pad)
            self._items[i] = self.create_rectangle(x1, y1, x2, y2, fill="#0a0a0a", outline="#333", width=max(1, int((x2 - x1) * 0.04)))
            self.create_text((x1 + x2) / 2, (y1 + y2) / 2, text=str(i), fill="#444", font=("Consolas", font_size, "bold"))
            self._apply_color(i)
        self._apply_color(0)

    def _hit_test(self, x, y):
        w, h = self.winfo_width(), self.winfo_height()
        pad = max(6, min(w, h) * 0.04)
        for idx in range(LEDS_PER_CHANNEL):
            x1, y1, x2, y2 = self._cell_rect(idx, w, h, pad)
            if x1 <= x <= x2 and y1 <= y <= y2: return idx
        return None

    def _click_press(self, event):
        idx = self._hit_test(event.x, event.y)
        if idx is not None: self._on_press(self._ch, idx)

    def _click_release(self, event):
        idx = self._hit_test(event.x, event.y)
        if idx is not None: self._on_rel(self._ch, idx)

class EvilEyeSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Evil Eye Simulator (4 Walls)")
        self.root.configure(bg="#1a1a1a")

        self.led_timestamps = {(c, l): 0 for c in range(1, 5) for l in range(LEDS_PER_CHANNEL)}
        self.pressed_leds = set()
        self._press_lock = threading.Lock()
        self._running = True
        self._pkt_count = 0
        self._bind_ip = "0.0.0.0"
        
        self.listen_port = CONFIG.get("recv_port", 4626)
        self.send_port = CONFIG.get("send_port", 7800)

        self._wall_canvases = {}
        self._build_ui()
        self._setup_network()

        threading.Thread(target=self._network_loop, daemon=True).start()
        threading.Thread(target=self._timeout_loop, daemon=True).start()

        self.log(f"Listening on UDP :{self.listen_port}")
        self.log(f"Triggers → UDP :{self.send_port}")

    def log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        if hasattr(self, "_log_text"):
            self._log_text.configure(state="normal")
            self._log_text.insert(tk.END, f"[{ts}] {msg}\n")
            self._log_text.see(tk.END)
            self._log_text.configure(state="disabled")

    def _build_ui(self):
        bar = tk.Frame(self.root, bg="#2a2a2a")
        bar.pack(side=tk.TOP, fill=tk.X)
        
        self.lbl_rx = tk.Label(bar, text="● RX", bg="#2a2a2a", fg="#555", font=("Consolas", 10, "bold"))
        self.lbl_rx.pack(side=tk.LEFT, padx=5, pady=6)
        self.lbl_stats = tk.Label(bar, text="Packets: 0", bg="#2a2a2a", fg="#00ff00", font=("Consolas", 9, "bold"))
        self.lbl_stats.pack(side=tk.LEFT, padx=10, pady=6)

        tk.Label(bar, text="Net:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self._iface_var = tk.StringVar(value=self._bind_ip)
        self._iface_combo = ttk.Combobox(bar, textvariable=self._iface_var, width=15, state="readonly")
        self._iface_combo.pack(side=tk.LEFT, padx=5)
        self._update_iface_list()
        self._iface_combo.bind("<<ComboboxSelected>>", self._on_iface_change)

        tk.Label(bar, text="Port IN:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self.port_in_var = tk.StringVar(value=str(self.listen_port))
        tk.Entry(bar, textvariable=self.port_in_var, width=6, bg="#111", fg="#0f0", font=("Consolas", 9)).pack(side=tk.LEFT, padx=2)
        tk.Button(bar, text="🎲", command=self.randomize_port, bg="#444", fg="white", font=("Consolas", 8), relief="flat").pack(side=tk.LEFT, padx=2)

        tk.Label(bar, text="Port OUT:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self.port_out_var = tk.StringVar(value=str(self.send_port))
        tk.Entry(bar, textvariable=self.port_out_var, width=6, bg="#111", fg="#0f0", font=("Consolas", 9)).pack(side=tk.LEFT, padx=2)

        tk.Label(bar, text="F11: Fullscreen | ESC: Exit", bg="#2a2a2a", fg="#777", font=("Consolas", 8)).pack(side=tk.RIGHT, padx=10)

        pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a", sashwidth=5)
        pane.pack(fill=tk.BOTH, expand=True)

        left = tk.Frame(pane, bg="#1a1a1a")
        pane.add(left, stretch="always")
        for ch in range(1, 5):
            row, col = (ch - 1) // 2, (ch - 1) % 2
            left.grid_rowconfigure(row, weight=1)
            left.grid_columnconfigure(col, weight=1)
            wf = tk.LabelFrame(left, text=f" WALL {ch} ", bg="#1a1a1a", fg="#ff4444", font=("Consolas", 11, "bold"), borderwidth=2, relief="groove")
            wf.grid(row=row, column=col, padx=8, pady=8, sticky="nsew")
            wf.grid_rowconfigure(0, weight=1)
            wf.grid_columnconfigure(0, weight=1)
            cv = WallCanvas(wf, ch, self._on_press, self._on_release)
            cv.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
            self._wall_canvases[ch] = cv

        right = tk.Frame(pane, bg="#111", width=260)
        pane.add(right, stretch="never")
        tk.Label(right, text="NETWORK LOGS", bg="#222", fg="white", font=("Consolas", 9, "bold")).pack(fill=tk.X)
        self._log_text = tk.Text(right, bg="#0a0a0a", fg="#00ff00", font=("Consolas", 8), state="disabled", borderwidth=0)
        self._log_text.pack(fill=tk.BOTH, expand=True)

        self.root.bind("<F11>", self._toggle_fullscreen)
        self.root.bind("<Escape>", self._exit_fullscreen)

    def _toggle_fullscreen(self, event=None):
        self.root.attributes("-fullscreen", not self.root.attributes("-fullscreen"))
    def _exit_fullscreen(self, event=None):
        self.root.attributes("-fullscreen", False)

    def _on_press(self, channel, index):
        with self._press_lock: self.pressed_leds.add((channel, index))
        self.log(f"Press: Wall {channel}, LED {index}")
        self._send_trigger_packet()

    def _on_release(self, channel, index):
        with self._press_lock: self.pressed_leds.discard((channel, index))
        self.log(f"Release: Wall {channel}, LED {index}")
        self._send_trigger_packet()

    def _on_iface_change(self, event=None):
        new_ip = self._iface_var.get()
        if new_ip != self._bind_ip:
            self._bind_ip = new_ip
            self._setup_network()

    def randomize_port(self):
        import random
        new_in = random.randint(1024, 65535)
        new_out = random.randint(1024, 65535)
        self.port_in_var.set(str(new_in))
        self.port_out_var.set(str(new_out))
        self.apply_ports()

    def apply_ports(self, event=None):
        try:
            self.listen_port, self.send_port = int(self.port_in_var.get()), int(self.port_out_var.get())
            CONFIG.update({"recv_port": self.listen_port, "send_port": self.send_port})
            _save_config(CONFIG)
            self._setup_network()
        except: pass

    def _update_iface_list(self):
        ips = ["0.0.0.0", "127.0.0.1"]
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address not in ips: ips.append(addr.address)
        except: pass
        self._iface_combo['values'] = ips

    def _setup_network(self):
        for s in ['_sock_listen', '_sock_send']:
            if hasattr(self, s):
                try: getattr(self, s).close()
                except: pass
        self._sock_listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock_listen.settimeout(0.5)
        try: self._sock_listen.bind((self._bind_ip, self.listen_port))
        except: pass
        self._sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        try: self._sock_send.bind((self._bind_ip, 0))
        except: pass

    def _network_loop(self):
        while self._running:
            try: data, addr = self._sock_listen.recvfrom(2048)
            except: continue
            self.root.after(0, self.flash_rx)
            self._pkt_count += 1
            if self._pkt_count % 10 == 0:
                self.log(f"Received light data packet {self._pkt_count}")
                self.root.after(0, lambda: self.lbl_stats.config(text=f"Packets: {self._pkt_count}"))
            if data[0] == 0x67: self._handle_discovery(addr, data)
            elif data[0] == 0x75 and self._handle_control(data): self._send_trigger_packet()

    def _handle_discovery(self, addr, data):
        resp = bytearray(32)
        resp[0], resp[1], resp[2] = 0x68, data[1] if len(data)>1 else 0, data[2] if len(data)>2 else 0
        resp[6:13], resp[13:19], resp[20] = b"KX-HC04", b"\x00\x11\x22\x33\x44\x55", 0x04
        try: self._sock_send.sendto(bytes(resp), addr)
        except: pass

    def flash_rx(self):
        self.lbl_rx.config(fg="#0f0")
        self.root.after(50, lambda: self.lbl_rx.config(fg="#555"))

    def _handle_control(self, data):
        payload = data[5:]
        if len(payload) < 9: return False
        data_id, msg_loc = (payload[3] << 8) | payload[4], (payload[5] << 8) | payload[6]
        if data_id == 0x8877 and msg_loc != 0xFFF0:
            self._update_leds(payload[9:])
            return True
        return False

    def _update_leds(self, frame_data):
        now = time.time()
        for led_idx in range(min(len(frame_data) // 12, LEDS_PER_CHANNEL)):
            for ch_idx in range(NUM_CHANNELS):
                offset = led_idx * 12 + ch_idx
                if offset + 8 < len(frame_data):
                    g, r, b = frame_data[offset], frame_data[offset + 4], frame_data[offset + 8]
                    if r or g or b: self.led_timestamps[(ch_idx+1, led_idx)] = now
                    self.root.after(0, lambda c=ch_idx+1, i=led_idx, clr=(r,g,b): self._set_led(c, i, clr))

    def _timeout_loop(self):
        while self._running:
            time.sleep(1.0)
            now = time.time()
            for (ch, idx), ts in list(self.led_timestamps.items()):
                if ts != 0 and (now - ts) > LED_TIMEOUT_SEC:
                    self.led_timestamps[(ch, idx)] = 0
                    self.root.after(0, lambda c=ch, i=idx: self._set_led(c, i, (0, 0, 0)))

    def _set_led(self, channel, index, color):
        if channel in self._wall_canvases: self._wall_canvases[channel].set_color(index, *color)

    def _send_trigger_packet(self):
        pkt = bytearray(687)
        pkt[0], pkt[1] = 0x88, 0x01
        with self._press_lock: snapshot = set(self.pressed_leds)
        for ch, idx in snapshot:
            if 1 <= ch <= 4 and 0 <= idx < 11: pkt[2 + (ch-1)*171 + 1 + idx] = 0xCC
        pkt[-1] = sum(pkt[:-1]) & 0xFF
        for addr in [("127.0.0.1", self.send_port), ("255.255.255.255", self.send_port)]:
            try: self._sock_send.sendto(bytes(pkt), addr)
            except: pass

if __name__ == "__main__":
    root = tk.Tk()
    root.geometry("900x620")
    sim = EvilEyeSimulator(root)
    root.mainloop()
