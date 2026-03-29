"""
Evil Eye Light Controller – Python/Tkinter port of the WPF LightControlApp.

Communicates with the Evil Eye hardware (or its simulator) using the same
UDP protocol as the original C# application.

Ports used:
  Send light commands → device UDP :4626
  Receive button events ← device UDP :7800
"""

import json
import os
import queue
import socket
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from datetime import datetime
import struct

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────
CONFIG_FILE        = os.path.join(os.path.dirname(__file__), "eye_ctrl_config.json")
LED_MAP_FILE       = os.path.join(os.path.dirname(__file__), "eye_led_map.json")
UDP_DEVICE_PORT    = 4626   # send light commands to device
UDP_RECEIVER_PORT  = 7800   # listen for button events from device
NUM_CHANNELS       = 4
LEDS_PER_CHANNEL   = 11     # 0 = Eye, 1-10 = Buttons
FRAME_DATA_LEN     = LEDS_PER_CHANNEL * NUM_CHANNELS * 3   # 132 bytes


def _default_led_map() -> dict:
    ident = list(range(LEDS_PER_CHANNEL))
    return {
        "logical_wall_to_physical_wall": {
            str(ch): ch for ch in range(1, NUM_CHANNELS + 1)
        },
        "logical_led_to_physical_led": {
            str(ch): ident[:] for ch in range(1, NUM_CHANNELS + 1)
        },
    }


def _sanitize_led_map(data: dict | None) -> dict:
    out = _default_led_map()
    if not isinstance(data, dict):
        return out

    wall_map = data.get("logical_wall_to_physical_wall", {})
    led_map = data.get("logical_led_to_physical_led", {})

    for ch in range(1, NUM_CHANNELS + 1):
        key = str(ch)

        try:
            phys_wall = int(wall_map.get(key, ch))
        except (TypeError, ValueError):
            phys_wall = ch
        if 1 <= phys_wall <= NUM_CHANNELS:
            out["logical_wall_to_physical_wall"][key] = phys_wall

        raw = led_map.get(key, list(range(LEDS_PER_CHANNEL)))
        if isinstance(raw, list) and len(raw) == LEDS_PER_CHANNEL:
            cleaned = []
            ok = True
            for v in raw:
                try:
                    iv = int(v)
                except (TypeError, ValueError):
                    ok = False
                    break
                if not (0 <= iv < LEDS_PER_CHANNEL):
                    ok = False
                    break
                cleaned.append(iv)
            if ok and sorted(cleaned) == list(range(LEDS_PER_CHANNEL)):
                out["logical_led_to_physical_led"][key] = cleaned

    return out


def load_led_map() -> dict:
    try:
        with open(LED_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return _default_led_map()
    return _sanitize_led_map(data)


def build_input_inverse_led_map(led_map: dict) -> dict:
    inv = {}
    wall_map = led_map["logical_wall_to_physical_wall"]
    led_remap = led_map["logical_led_to_physical_led"]

    for logical_ch in range(1, NUM_CHANNELS + 1):
        key = str(logical_ch)
        physical_ch = int(wall_map.get(key, logical_ch))
        remap = led_remap.get(key, list(range(LEDS_PER_CHANNEL)))
        for logical_led in range(LEDS_PER_CHANNEL):
            physical_led = int(remap[logical_led])
            inv[(physical_ch, physical_led)] = (logical_ch, logical_led)
    return inv


def map_logical_to_physical(led_map: dict, ch: int, led: int) -> tuple[int, int]:
    key = str(ch)
    phys_wall = int(led_map["logical_wall_to_physical_wall"].get(key, ch))
    remap = led_map["logical_led_to_physical_led"].get(key, list(range(LEDS_PER_CHANNEL)))
    phys_led = int(remap[led])
    return phys_wall, phys_led


def map_physical_to_logical(inv_map: dict, ch: int, led: int) -> tuple[int, int]:
    return inv_map.get((ch, led), (ch, led))

UDP_DEVICE_PORT    = 4626   # send light commands to device
UDP_RECEIVER_PORT  = 7800   # listen for button events from device
NUM_CHANNELS       = 4
LEDS_PER_CHANNEL   = 11     # 0 = Eye, 1-10 = Buttons
FRAME_DATA_LEN     = LEDS_PER_CHANNEL * NUM_CHANNELS * 3   # 132 bytes

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


# ─────────────────────────────────────────────────────────────────────────────
# Protocol helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_checksum_send(data: bytes | bytearray) -> int:
    """PASSWORD_ARRAY indexed checksum used when SENDING to the device."""
    idx = sum(data) & 0xFF
    return PASSWORD_ARRAY[idx] if idx < len(PASSWORD_ARRAY) else 0


def build_command_packet(data_id: int, msg_loc: int, payload: bytes, seq: int) -> bytes:
    """Build a 0x75 command packet compatible with the C# BuildCommandPacket."""
    import random
    rand1 = random.randint(0, 127)
    rand2 = random.randint(0, 127)

    internal = bytes([
        0x02,
        0x00,                               # masterControlNum
        0x00,                               # currentPacketNum
        (data_id >> 8) & 0xFF, data_id & 0xFF,
        (msg_loc >> 8) & 0xFF, msg_loc & 0xFF,
        (len(payload) >> 8) & 0xFF, len(payload) & 0xFF,
    ]) + payload

    hdr = bytes([
        0x75, rand1, rand2,
        (len(internal) >> 8) & 0xFF, len(internal) & 0xFF,
    ])
    pkt = bytearray(hdr + internal)
    # Override bytes 10-11 with sequence number (same quirk as C# code)
    pkt[10] = (seq >> 8) & 0xFF
    pkt[11] = seq & 0xFF
    pkt.append(calc_checksum_send(pkt))
    return bytes(pkt)


def build_start_packet(seq: int) -> bytes:
    import random
    pkt = bytearray([
        0x75,
        random.randint(0, 127), random.randint(0, 127),
        0x00, 0x08,
        0x02, 0x00, 0x00,
        0x33, 0x44,
        (seq >> 8) & 0xFF, seq & 0xFF,
        0x00, 0x00,
    ])
    pkt.append(calc_checksum_send(pkt))
    return bytes(pkt)


def build_end_packet(seq: int) -> bytes:
    import random
    pkt = bytearray([
        0x75,
        random.randint(0, 127), random.randint(0, 127),
        0x00, 0x08,
        0x02, 0x00, 0x00,
        0x55, 0x66,
        (seq >> 8) & 0xFF, seq & 0xFF,
        0x00, 0x00,
    ])
    pkt.append(calc_checksum_send(pkt))
    return bytes(pkt)


def build_fff0_packet(seq: int) -> bytes:
    num_leds = LEDS_PER_CHANNEL
    payload = bytearray()
    for _ in range(NUM_CHANNELS):
        payload += bytes([(num_leds >> 8) & 0xFF, num_leds & 0xFF])
    pkt = build_command_packet(0x8877, 0xFFF0, bytes(payload), seq)
    # Re-insert correct seq in bytes 10-11 (already done in build_command_packet)
    return pkt


def logical_rgb_to_wire_grb(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Logical red/green/blue → three frame bytes in hardware GRB order (wiki §2)."""
    return (g & 0xFF, r & 0xFF, b & 0xFF)


def build_frame_data(led_states: dict) -> bytes:
    """
    led_states: {(channel 1-4, led 0-10): (r, g, b)} — logical RGB in application code.

    Wire format: per-channel sequential GRB.
    Each channel occupies LEDS_PER_CHANNEL*3 = 33 consecutive bytes:
      Ch1: bytes  0-32   [G_led0, R_led0, B_led0, G_led1, ...]
      Ch2: bytes 33-65
      Ch3: bytes 66-98
      Ch4: bytes 99-131
    """
    frame = bytearray(FRAME_DATA_LEN)
    for (ch, led), (r, g, b) in led_states.items():
        ch_idx = ch - 1
        if 0 <= ch_idx < NUM_CHANNELS and 0 <= led < LEDS_PER_CHANNEL:
            w0, w1, w2 = logical_rgb_to_wire_grb(r, g, b)
            base = ch_idx * LEDS_PER_CHANNEL * 3 + led * 3
            frame[base]     = w0
            frame[base + 1] = w1
            frame[base + 2] = w2
    return bytes(frame)


# ─────────────────────────────────────────────────────────────────────────────
# Network Service
# ─────────────────────────────────────────────────────────────────────────────
class LightService:
    def __init__(self):
        self._device_ip   = None
        self._device_port = 4626
        self._recv_port   = 7800
        self._seq         = 0
        self._led_states  = {}        # physical (channel, led) -> (r, g, b)
        self._lock        = threading.Lock()

        self._led_map = load_led_map()
        self._led_map_inv = build_input_inverse_led_map(self._led_map)

        # ── Sender ────────────────────────────────────────────────────────────
        self._send_q      = queue.Queue(maxsize=4)
        self._sender_stop = threading.Event()
        self._sender_thr  = threading.Thread(target=self._sender_loop, daemon=True)
        self._sender_thr.start()

        # ── Poller ────────────────────────────────────────────────────────────
        self._poll_rate   = 100
        self._polling     = False
        self._poll_stop   = threading.Event()
        self._poll_thr    = None

        # ── Receiver ──────────────────────────────────────────────────────────
        self._recv_sock   = None
        self._recv_thr    = None
        self._recv_running = False
        self._bind_ip     = "0.0.0.0"

        # Track previous button states in LOGICAL coordinates
        self._prev_btn    = {}   # (logical_ch, logical_led) -> (is_triggered, is_disconnected)

        self.on_button_event  = None
        self.on_status        = None
        self.on_button_state  = None

    def reload_led_map(self):
        self._led_map = load_led_map()
        self._led_map_inv = build_input_inverse_led_map(self._led_map)
        self._log("LED map reloaded")

    def _map_out(self, ch: int, led: int) -> tuple[int, int]:
        return map_logical_to_physical(self._led_map, ch, led)

    def _map_in(self, ch: int, led: int) -> tuple[int, int]:
        return map_physical_to_logical(self._led_map_inv, ch, led)

    def set_led(self, channel, led, r, g, b):
        phys_ch, phys_led = self._map_out(channel, led)
        with self._lock:
            if r == g == b == 0:
                self._led_states.pop((phys_ch, phys_led), None)
            else:
                self._led_states[(phys_ch, phys_led)] = (r, g, b)
        self._enqueue_frame()

    def set_all(self, r, g, b):
        mapped = {}
        for ch in range(1, NUM_CHANNELS + 1):
            for led in range(LEDS_PER_CHANNEL):
                phys_ch, phys_led = self._map_out(ch, led)
                if r == g == b == 0:
                    continue
                mapped[(phys_ch, phys_led)] = (r, g, b)
        with self._lock:
            self._led_states = mapped
        self._enqueue_frame()

    def _recv_loop(self):
        EXPECTED = 687
        while self._recv_running:
            try:
                data, addr = self._recv_sock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception:
                break

            if len(data) != EXPECTED or data[0] != 0x88:
                continue
            if sum(data[:-1]) & 0xFF != data[-1]:
                continue

            grouped = {}  # logical_ch -> {"triggered": [...], "disconnected": [...]}

            for physical_ch in range(1, NUM_CHANNELS + 1):
                base = 2 + (physical_ch - 1) * 171
                for physical_led in range(LEDS_PER_CHANNEL):
                    val = data[base + 1 + physical_led]
                    is_trig = val == 0xCC
                    is_disc = val == 0x10

                    logical_ch, logical_led = self._map_in(physical_ch, physical_led)
                    prev = self._prev_btn.get((logical_ch, logical_led))
                    new = (is_trig, is_disc)

                    if prev != new:
                        self._prev_btn[(logical_ch, logical_led)] = new
                        if self.on_button_state:
                            self.on_button_state(logical_ch, logical_led, is_trig, is_disc)

                    bucket = grouped.setdefault(
                        logical_ch, {"triggered": [], "disconnected": []}
                    )
                    if is_trig:
                        bucket["triggered"].append(logical_led)
                    elif is_disc:
                        bucket["disconnected"].append(logical_led)

            for logical_ch, bucket in grouped.items():
                if (bucket["triggered"] or bucket["disconnected"]) and self.on_button_event:
                    self.on_button_event(
                        logical_ch,
                        bucket["triggered"],
                        bucket["disconnected"],
                        addr[0],
                    )

    # ── Discovery ─────────────────────────────────────────────────────────────
    def discover(self, iface_ip: str, callback):
        """Async discovery; calls callback(list_of_device_dicts)."""
        threading.Thread(target=self._discover_thread, args=(iface_ip, callback), daemon=True).start()

    def _discover_thread(self, iface_ip, callback):
        import random
        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        payload = bytes([0x0A, 0x02, 0x4B, 0x58, 0x2D, 0x48, 0x43, 0x30, 0x34, 0x03, 0x00, 0x00, 0xFF, 0xFF, 0x00, 0x00, 0x00, 0x14])
        pkt = bytearray([0x67, rand1, rand2, len(payload)] + list(payload))
        idx = sum(pkt) & 0xFF
        pkt.append(PASSWORD_ARRAY[idx] if idx < len(PASSWORD_ARRAY) else 0)

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, True)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, True)
        sock.settimeout(0.5)
        self._log(f"Binding discovery on {iface_ip}:{self._recv_port}")
        try:
            sock.bind((iface_ip, self._recv_port))
        except Exception as e:
            self._log(f"Discovery bind error: {e}")
            sock.close()
            callback([])
            return

        # Calculate broadcast
        try:
            import ipaddress, netifaces
            # fallback: just broadcast
        except:
            pass
        # Simple approach: broadcast on 255.255.255.255
        self._log(f"Sending discovery to 255.255.255.255:4626")
        try:
            sock.sendto(bytes(pkt), ("255.255.255.255", 4626))
        except Exception as e:
            self._log(f"Discovery send error: {e}")

        devices = []
        deadline = time.time() + 5
        while time.time() < deadline:
            try:
                data, addr = sock.recvfrom(256)
                if len(data) >= 30 and data[0] == 0x68 and data[1] == rand1 and data[2] == rand2:
                    model = data[6:13].rstrip(b'\x00').decode('ascii', errors='replace')
                    dev_type = data[20]
                    info = {"ip": addr[0], "name": f"{model} (HC0{dev_type})"}
                    if not any(d["ip"] == addr[0] for d in devices):
                        devices.append(info)
                        self._log(f"Discovered: {info['name']} @ {info['ip']}")
            except socket.timeout:
                continue
        sock.close()

        if not devices:
            devices.append({"ip": "169.254.15.67", "name": "Default (not discovered)"})
        callback(devices)


# ─────────────────────────────────────────────────────────────────────────────
# Config persistence
# ─────────────────────────────────────────────────────────────────────────────
DEFAULT_CONFIG = {
    "device_ip": "",
    "udp_port": 4626,
    "receiver_port": 7800,
    "polling_rate_ms": 100,
    "auto_connect": True, # This is effectively replaced by auto_start_receiver and auto_start_streaming
    "auto_start_receiver": True,
    "auto_start_streaming": False, # New option
    "log_events": True,
}


def receiver_bind_ip_from_config(cfg: dict) -> str:
    """Local address for button UDP receiver (games + Controller).

    If eye_ctrl_config.json sets receiver_bind_ip, that wins (use 0.0.0.0 for all
    interfaces / broadcast). Otherwise virtual_iface_ip, then 0.0.0.0.
    """
    if "receiver_bind_ip" in cfg:
        r = (cfg.get("receiver_bind_ip") or "").strip()
        if r:
            return r
    v = (cfg.get("virtual_iface_ip") or "").strip()
    if v:
        return v
    return "0.0.0.0"


def load_config():
    try:
        with open(CONFIG_FILE) as f:
            cfg = json.load(f)
        return {**DEFAULT_CONFIG, **cfg}
    except:
        return dict(DEFAULT_CONFIG)


def save_config(cfg):
    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(cfg, f, indent=2)
    except Exception as e:
        print(f"Error saving config: {e}")



# ─────────────────────────────────────────────────────────────────────────────
# Colour helper
# ─────────────────────────────────────────────────────────────────────────────
def rgb_hex(r, g, b):
    return f"#{r:02x}{g:02x}{b:02x}"


def contrasting_text(r, g, b):
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if lum > 128 else "white"


# ─────────────────────────────────────────────────────────────────────────────
# Main Application Window
# ─────────────────────────────────────────────────────────────────────────────
class LightControlApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Evil Eye – Light Controller")
        self.configure(bg="#1a1a1a")
        self.minsize(900, 700)

        self._service   = LightService()
        self._cfg       = load_config()
        self._polling   = False
        self._receiving = False
        self._light_on_trigger = False
        # (channel, led) -> (r, g, b)  – current local LED state shown in the grid
        self._grid_colors = {}
        # channel -> (canvas, oval_id)  for round eye widgets
        self._eye_ovals = {}

        self._service.on_status       = self._on_status
        self._service.on_button_event = self._on_button_event
        self._service.on_button_state = self._on_button_state

        if self._cfg.get("device_ip"):
            self._service.set_device(self._cfg["device_ip"], self._cfg.get("udp_port", 4626))
        
        self._service.set_recv_port(self._cfg.get("receiver_port", 7800))
        self._service.set_bind_ip(receiver_bind_ip_from_config(self._cfg))
            
        self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))

        self._build_ui()

        # Auto-start based on config
        if self._cfg.get("auto_start_streaming", False):
            self.after(500, self._toggle_connect)

    # ── Status callback (called from background thread) ──────────────────────
    def _on_status(self, msg):
        self.after(0, lambda: self._log(msg))

    def _update_iface_list(self):
        ips = ["0.0.0.0", "127.0.0.1"]
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        if addr.address not in ips:
                            ips.append(addr.address)
        except: pass
        self._iface_combo['values'] = ips

    def _on_iface_change(self, event=None):
        new_ip = self._iface_var.get()
        self._cfg["virtual_iface_ip"] = new_ip
        save_config(self._cfg)
        self._service.set_bind_ip(new_ip)
        self._log(f"Interface changed to {new_ip}")


    def _on_button_event(self, ch, triggered, disconnected, src_ip):
        ts = datetime.now().strftime("%H:%M:%S")
        parts = []
        if triggered:    parts.append(f"triggered={triggered}")
        if disconnected: parts.append(f"disconnected={disconnected}")
        line = f"[{ts}] Wall {ch}: {', '.join(parts)}  (from {src_ip})\n"
        self.after(0, lambda: self._append_event(line))

    def _on_button_state(self, ch, led, is_triggered, is_disconnected):
        """Called from receiver thread ONLY when state changes."""
        if is_triggered:
            status = "triggered"
        elif is_disconnected:
            status = "disconnected"
        else:
            status = "idle"

        self.after(0, lambda: self._update_button_status(ch, led, status))

        # Light-on-trigger: set LED on press, clear on release
        if self._light_on_trigger:
            if is_triggered:
                r, g, b = self._get_rgb()
                self._service.set_led(ch, led, r, g, b)
                self.after(0, lambda c=ch, l=led, rv=r, gv=g, bv=b:
                           self._set_btn_color(c, l, rv, gv, bv))
            elif not is_disconnected:  # released back to idle
                self._service.set_led(ch, led, 0, 0, 0)
                self.after(0, lambda c=ch, l=led: self._set_btn_color(c, l, 0, 0, 0))

    # ── UI Build ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("Dark.TFrame", background="#1a1a1a")

        # ── Top toolbar ──
        toolbar = tk.Frame(self, bg="#2a2a2a", height=44)
        toolbar.pack(fill=tk.X)

        self._btn_config   = self._tb_btn(toolbar, "⚙ Config",            self._open_config)
        self._btn_connect  = self._tb_btn(toolbar, "▶ START STREAM",      self._toggle_connect)
        self._btn_lw_trig  = self._tb_btn(toolbar, "💡 Light On Trigger",   self._toggle_light_on_trigger, bg="#555")
        self._btn_all_off  = self._tb_btn(toolbar, "⬛ All Off",           self._all_off, bg="#333")

        # Network Interface Selector
        tk.Label(toolbar, text="Net Interface:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self._iface_var = tk.StringVar(value=self._cfg.get("virtual_iface_ip", "0.0.0.0"))
        self._iface_combo = ttk.Combobox(toolbar, textvariable=self._iface_var, width=15, state="readonly")
        self._iface_combo.pack(side=tk.LEFT, padx=5, pady=8)
        self._update_iface_list()
        self._iface_combo.bind("<<ComboboxSelected>>", self._on_iface_change)

        self.bind("<F11>", lambda e: self.attributes("-fullscreen", not self.attributes("-fullscreen")))
        self.bind("<Escape>", lambda e: self.attributes("-fullscreen", False))

        self._lbl_device = tk.Label(toolbar, text="No device", bg="#2a2a2a", fg="#aaa", font=("Consolas", 9))
        self._lbl_device.pack(side=tk.RIGHT, padx=10)

        # ── Notebook (tabs) ──
        nb = ttk.Notebook(self)
        nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        tab_ctrl = tk.Frame(nb, bg="#1a1a1a")
        tab_log  = tk.Frame(nb, bg="#111")
        nb.add(tab_ctrl, text=" 🎛 LED Control ")
        nb.add(tab_log,  text=" 📋 Events Log  ")

        self._build_control_tab(tab_ctrl)
        self._build_log_tab(tab_log)

        # ── Status bar ──
        sb = tk.Frame(self, bg="#111", height=22)
        sb.pack(fill=tk.X, side=tk.BOTTOM)
        self._status_lbl = tk.Label(sb, text="Ready", bg="#111", fg="#0f0", font=("Consolas", 8), anchor="w")
        self._status_lbl.pack(fill=tk.X, padx=6)

    def _tb_btn(self, parent, text, cmd, bg="#444"):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=bg, fg="white", font=("Consolas", 9, "bold"),
                      relief="flat", padx=10, pady=8, cursor="hand2",
                      activebackground="#666", activeforeground="white")
        b.pack(side=tk.LEFT, padx=2, pady=4)
        return b

    def _build_control_tab(self, parent):
        # ── Left: colour picker + quick presets ──
        left = tk.Frame(parent, bg="#222", width=220)
        left.pack(side=tk.LEFT, fill=tk.Y, padx=(8, 4), pady=8)
        left.pack_propagate(False)

        tk.Label(left, text="COLOUR PICKER", bg="#222", fg="#ff4444",
                 font=("Consolas", 10, "bold")).pack(pady=(10, 4))

        self._preview = tk.Canvas(left, width=180, height=60, bg="black",
                                  highlightthickness=2, highlightbackground="#444")
        self._preview.pack(pady=4)
        self._preview_rect = self._preview.create_rectangle(2, 2, 178, 58, fill="black", outline="")

        for label, var_name, row_col in [("R", "_sv_r", "#ff5555"),
                                          ("G", "_sv_g", "#55ff55"),
                                          ("B", "_sv_b", "#5555ff")]:
            f = tk.Frame(left, bg="#222")
            f.pack(fill=tk.X, padx=8, pady=2)
            tk.Label(f, text=label, bg="#222", fg=row_col, font=("Consolas", 9, "bold"), width=2).pack(side=tk.LEFT)
            sv = tk.StringVar(value="0")
            setattr(self, var_name, sv)
            sld = tk.Scale(f, from_=0, to=255, orient=tk.HORIZONTAL, variable=sv,
                           bg="#222", fg=row_col, troughcolor="#333",
                           highlightthickness=0, sliderlength=14, command=lambda _: self._update_preview())
            sld.pack(side=tk.LEFT, fill=tk.X, expand=True)
            ent = tk.Entry(f, textvariable=sv, width=4, bg="#111", fg="white",
                           font=("Consolas", 9), insertbackground="white")
            ent.pack(side=tk.LEFT, padx=(2, 0))

        tk.Label(left, text="QUICK PRESETS", bg="#222", fg="#888",
                 font=("Consolas", 8, "bold")).pack(pady=(14, 4))

        presets = [
            ("■ Red",    255,   0,   0, "#ff2222"),
            ("■ Green",    0, 255,   0, "#22ff22"),
            ("■ Blue",     0,   0, 255, "#2222ff"),
            ("■ White",  255, 255, 255, "#eeeeee"),
            ("■ Yellow", 255, 255,   0, "#ffff22"),
            ("■ Purple", 128,   0, 128, "#cc44cc"),
        ]
        for txt, r, g, b, col in presets:
            self._preset_btn(left, txt, r, g, b, col)

        tk.Label(left, text="ALL WALLS", bg="#222", fg="#888",
                 font=("Consolas", 8, "bold")).pack(pady=(14, 4))
        tk.Button(left, text="Set All to Colour", command=self._all_on,
                  bg="#335", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=8, pady=6, cursor="hand2").pack(fill=tk.X, padx=8, pady=2)
        tk.Button(left, text="⬛ All Off", command=self._all_off,
                  bg="#333", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=8, pady=6, cursor="hand2").pack(fill=tk.X, padx=8, pady=2)

        # ── Right: LED grid ──
        right = tk.Frame(parent, bg="#1a1a1a")
        right.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=8)

        self._led_buttons = {}   # (ch, led) -> tk.Button
        self._led_status  = {}   # (ch, led) -> status label

        walls_frame = tk.Frame(right, bg="#1a1a1a")
        walls_frame.pack(fill=tk.BOTH, expand=True)
        walls_frame.grid_rowconfigure(0, weight=1)
        walls_frame.grid_rowconfigure(1, weight=1)
        walls_frame.grid_columnconfigure(0, weight=1)
        walls_frame.grid_columnconfigure(1, weight=1)

        for ch in range(1, NUM_CHANNELS + 1):
            row = (ch - 1) // 2
            col = (ch - 1) % 2

            wf = tk.LabelFrame(walls_frame, text=f" WALL {ch} ",
                                bg="#1a1a1a", fg="#ff4444",
                                font=("Consolas", 11, "bold"),
                                padx=10, pady=10, borderwidth=2, relief="groove")
            wf.grid(row=row, column=col, padx=10, pady=10, sticky="nsew")

            # Eye — circular Canvas
            e_frame = tk.Frame(wf, bg="#1a1a1a")
            e_frame.pack(fill=tk.X, pady=4)

            eye_cv = tk.Canvas(e_frame, width=60, height=60,
                               bg="#1a1a1a", highlightthickness=0)
            eye_cv.pack(side=tk.LEFT, padx=4)
            eye_oval = eye_cv.create_oval(3, 3, 57, 57,
                                          fill="#111", outline="#ff0000", width=3)
            eye_cv.bind("<Button-1>", lambda e, c=ch: self._on_led_click(c, 0))
            self._eye_ovals[ch] = (eye_cv, eye_oval)

            eye_info = tk.Frame(e_frame, bg="#1a1a1a")
            eye_info.pack(side=tk.LEFT, padx=4)
            tk.Label(eye_info, text="\U0001f441 EYE", bg="#1a1a1a", fg="white",
                     font=("Consolas", 9, "bold")).pack(anchor="w")
            eye_st = tk.Label(eye_info, text="idle", bg="#1a1a1a", fg="#555",
                              font=("Consolas", 7), width=9, anchor="w")
            eye_st.pack(anchor="w")
            self._led_status[(ch, 0)] = eye_st

            # Buttons 1-10 in 2 rows × 5 cols  (each cell = button + status label)
            bf = tk.Frame(wf, bg="#1a1a1a")
            bf.pack(fill=tk.BOTH, expand=True)
            for r_i in range(2): bf.grid_rowconfigure(r_i, weight=1)
            for c_i in range(5): bf.grid_columnconfigure(c_i, weight=1)
            for i in range(1, 11):
                r = (i - 1) // 5
                c2 = (i - 1) % 5
                cell = tk.Frame(bf, bg="#1a1a1a")
                cell.grid(row=r, column=c2, padx=2, pady=2, sticky="nsew")
                btn = tk.Button(
                    cell, text=str(i), width=4, height=2,
                    bg="#111", fg="#555", font=("Consolas", 9, "bold"),
                    relief="flat", cursor="hand2",
                    command=lambda ch_=ch, idx=i: self._on_led_click(ch_, idx)
                )
                btn.pack(fill=tk.BOTH, expand=True)
                lbl = tk.Label(cell, text="idle", bg="#1a1a1a", fg="#555",
                               font=("Consolas", 7), width=9, anchor="w")
                lbl.pack()
                self._led_buttons[(ch, i)] = btn
                self._led_status[(ch, i)]  = lbl

    def _preset_btn(self, parent, text, r, g, b, fg_col):
        def apply():
            self._sv_r.set(str(r))
            self._sv_g.set(str(g))
            self._sv_b.set(str(b))
            self._update_preview()
        tk.Button(parent, text=text, command=apply,
                  bg="#1a1a1a", fg=fg_col, font=("Consolas", 9),
                  relief="flat", padx=6, pady=3, cursor="hand2",
                  anchor="w").pack(fill=tk.X, padx=8, pady=1)

    def _build_log_tab(self, parent):
        tk.Label(parent, text="BUTTON EVENTS", bg="#111", fg="#888",
                 font=("Consolas", 9, "bold")).pack(fill=tk.X, padx=4, pady=2)

        self._events_text = scrolledtext.ScrolledText(
            parent, bg="#0a0a0a", fg="#00ff88",
            font=("Consolas", 9), state="disabled", borderwidth=0
        )
        self._events_text.pack(fill=tk.BOTH, expand=True, padx=4, pady=(0, 4))

        tk.Button(parent, text="Clear", command=self._clear_events,
                  bg="#333", fg="white", font=("Consolas", 9),
                  relief="flat", padx=10, pady=4).pack(pady=4)

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _get_rgb(self):
        try:
            r = max(0, min(255, int(self._sv_r.get())))
            g = max(0, min(255, int(self._sv_g.get())))
            b = max(0, min(255, int(self._sv_b.get())))
        except:
            r, g, b = 0, 0, 0
        return r, g, b

    def _update_preview(self):
        r, g, b = self._get_rgb()
        col = rgb_hex(r, g, b)
        self._preview.itemconfig(self._preview_rect, fill=col)

    def _on_led_click(self, channel, led):
        r, g, b = self._get_rgb()
        self._service.set_led(channel, led, r, g, b)
        self._set_btn_color(channel, led, r, g, b)
        self._log(f"Set Wall {channel}, LED {led} → RGB({r},{g},{b})")

    def _set_btn_color(self, ch, led, r, g, b):
        self._grid_colors[(ch, led)] = (r, g, b)
        if led == 0:  # Eye — update canvas oval
            if ch in self._eye_ovals:
                cv, oval_id = self._eye_ovals[ch]
                fill    = f"#{r:02x}{g:02x}{b:02x}" if (r or g or b) else "#111"
                outline = fill if (r or g or b) else "#ff0000"
                cv.itemconfig(oval_id, fill=fill, outline=outline)
        else:
            if (ch, led) not in self._led_buttons:
                return
            btn = self._led_buttons[(ch, led)]
            if r == g == b == 0:
                btn.configure(bg="#111", fg="#555")
            else:
                hex_c = rgb_hex(r, g, b)
                btn.configure(bg=hex_c, fg=contrasting_text(r, g, b))

    def _update_button_status(self, ch, led, status):
        st_map = {"triggered": ("triggered", "#00ff00"),
                  "disconnected": ("disc.",     "#ff4444"),
                  "idle":         ("idle",       "#555")}
        text, fg = st_map.get(status, ("idle", "#555"))

        if led == 0:  # Eye — update oval outline colour
            if ch in self._eye_ovals:
                cv, oval_id = self._eye_ovals[ch]
                if status == "triggered":
                    cv.itemconfig(oval_id, outline="#00ff00")
                elif status == "disconnected":
                    cv.itemconfig(oval_id, outline="#ff4444")
                else:
                    r, g, b = self._grid_colors.get((ch, 0), (0, 0, 0))
                    cv.itemconfig(oval_id,
                                  outline="#ff0000" if not (r or g or b)
                                          else f"#{r:02x}{g:02x}{b:02x}")
        else:  # Regular button — highlight border & add T marker
            if (ch, led) in self._led_buttons:
                btn = self._led_buttons[(ch, led)]
                if status == "triggered":
                    btn.configure(text=f"{led} [T]", highlightbackground="#00ff00", highlightthickness=2)
                elif status == "disconnected":
                    btn.configure(text=f"{led} [X]", highlightbackground="#ff4444", highlightthickness=2)
                else:
                    btn.configure(text=str(led), highlightthickness=0)

        # Update status label for all LEDs
        if (ch, led) in self._led_status and self._led_status[(ch, led)]:
            self._led_status[(ch, led)].configure(text=text, fg=fg)

    def _all_on(self):
        r, g, b = self._get_rgb()
        self._service.set_all(r, g, b)
        for ch in range(1, NUM_CHANNELS + 1):
            for led in range(LEDS_PER_CHANNEL):
                self._set_btn_color(ch, led, r, g, b)
        self._log(f"All lights → RGB({r},{g},{b})")

    def _all_off(self):
        self._service.all_off()
        for ch in range(1, NUM_CHANNELS + 1):
            for led in range(LEDS_PER_CHANNEL):
                self._set_btn_color(ch, led, 0, 0, 0)
        self._log("All lights off")

    def _toggle_connect(self):
        """Start/stop both the receiver AND polling together."""
        connected = self._receiving or self._polling
        if connected:
            self._service.stop_receiver()
            self._service.stop_polling()
            self._receiving = False
            self._polling   = False
            self._btn_connect.configure(text="▶ START STREAM", bg="green")
            self._log("Disconnected (receiver + polling stopped)")
        else:
            if not self._cfg.get("device_ip"):
                messagebox.showwarning("No Device", "Set a device IP in Config first.")
                return
            self._service.set_poll_rate(self._cfg.get("polling_rate_ms", 100))
            self._service.start_receiver()
            self._service.start_polling()
            self._receiving = True
            self._polling   = True
            self._btn_connect.configure(text="🛑 STOP STREAM", bg="red")
            self._log("Connected: polling + receiver active")

    def _toggle_light_on_trigger(self):
        self._light_on_trigger = not self._light_on_trigger
        if self._light_on_trigger:
            self._btn_lw_trig.configure(bg="#4a4", text="💡 Light On Trigger: ON")
            self._service.all_off()
            for ch in range(1, NUM_CHANNELS + 1):
                for led in range(LEDS_PER_CHANNEL):
                    self._set_btn_color(ch, led, 0, 0, 0)
        else:
            self._btn_lw_trig.configure(bg="#555", text="💡 Light On Trigger")

    def _open_config(self):
        ConfigDialog(self, self._cfg, self._service, self._on_config_saved)

    def _on_config_saved(self, new_cfg):
        self._cfg = new_cfg
        save_config(new_cfg)
        if new_cfg.get("device_ip"):
            self._service.set_device(new_cfg["device_ip"], new_cfg.get("udp_port", 4626))
            self._lbl_device.configure(text=f"Device: {new_cfg['device_ip']}", fg="#0f0")
        self._service.set_recv_port(new_cfg.get("receiver_port", 7800))
        self._service.set_bind_ip(receiver_bind_ip_from_config(new_cfg))
        self._service.set_poll_rate(new_cfg.get("polling_rate_ms", 100))
        self._service.reload_led_map()
        self._log("Configuration saved")

    def _log(self, msg):
        ts = datetime.now().strftime("%H:%M:%S")
        self._status_lbl.configure(text=f"[{ts}] {msg}")

    def _append_event(self, line):
        self._events_text.configure(state="normal")
        self._events_text.insert(tk.END, line)
        self._events_text.see(tk.END)
        self._events_text.configure(state="disabled")

    def _clear_events(self):
        self._events_text.configure(state="normal")
        self._events_text.delete("1.0", tk.END)
        self._events_text.configure(state="disabled")

    def destroy(self):
        self._service.stop_polling()
        self._service.stop_receiver()
        super().destroy()



# ─────────────────────────────────────────────────────────────────────────────
# Configuration Dialog
# ─────────────────────────────────────────────────────────────────────────────
class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, cfg, service, on_save):
        super().__init__(parent)
        self.title("Configuration")
        self.configure(bg="#1a1a1a")
        self.resizable(False, False)
        self.grab_set()

        self._cfg     = dict(cfg)
        self._service = service
        self._on_save = on_save

        self._sv_auto_stream = tk.BooleanVar(value=cfg.get("auto_start_streaming", False))

        self._build()

    def _build(self):
        pad = dict(padx=10, pady=4, sticky="we")

        # ── Network ──
        self._section("Network Settings")
        self._field("Device IP:", self._sv_ip, row=1)
        self._field("UDP Port (send):", self._sv_udp, row=2)
        self._field("UDP Port (recv):", self._sv_recv, row=3)
        self._field("Polling Rate (ms):", self._sv_poll, row=4)

        tk.Button(self, text="🎲 Randomize Ports", command=self._randomize,
                  bg="#444", fg="white", font=("Consolas", 8),
                  relief="flat").grid(row=2, column=2, rowspan=2, padx=4, pady=4, sticky="nsew")

        tk.Checkbutton(self, text="Auto-start stream & receiver on launch",
                       variable=self._sv_auto_stream,
                       bg="#1a1a1a", fg="white", selectcolor="#333",
                       activebackground="#1a1a1a", activeforeground="white",
                       font=("Consolas", 9)).grid(row=5, column=0, columnspan=3, padx=10, pady=4, sticky="w")

        # ── Network interfaces list ──
        self._section("Network Interfaces", row=6)

        self._iface_list = tk.Listbox(self, bg="#111", fg="#0f0", font=("Consolas", 8),
                                       height=5, selectbackground="#336")
        self._iface_list.grid(row=7, column=0, columnspan=2, padx=10, pady=4, sticky="we")
        self._load_interfaces()

        tk.Button(self, text="Refresh", command=self._load_interfaces,
                  bg="#333", fg="white", font=("Consolas", 8),
                  relief="flat", padx=8, pady=4).grid(row=7, column=2, padx=4, pady=4, sticky="we")

        # ── Discovery ──
        self._section("Device Discovery", row=8)
        self._discovered_lbl = tk.Label(self, text="", bg="#1a1a1a", fg="#aaa",
                                         font=("Consolas", 8))
        self._discovered_lbl.grid(row=9, column=0, columnspan=2, padx=10, pady=2, sticky="w")

        tk.Button(self, text="🔍 Discover Devices", command=self._discover,
                  bg="#224", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=10, pady=6, cursor="hand2").grid(
                      row=9, column=2, padx=4, pady=4, sticky="we")

        self._status_lbl = tk.Label(self, text="", bg="#1a1a1a", fg="#888", font=("Consolas", 8))
        self._status_lbl.grid(row=10, column=0, columnspan=3, padx=10, pady=2, sticky="w")

        # ── Buttons ──
        btn_frame = tk.Frame(self, bg="#1a1a1a")
        btn_frame.grid(row=11, column=0, columnspan=3, pady=12)

        tk.Button(btn_frame, text="💾 Save", command=self._save,
                  bg="#226", fg="white", font=("Consolas", 9, "bold"),
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side=tk.LEFT, padx=6)
        tk.Button(btn_frame, text="Cancel", command=self.destroy,
                  bg="#333", fg="white", font=("Consolas", 9),
                  relief="flat", padx=16, pady=6, cursor="hand2").pack(side=tk.LEFT, padx=6)

    def _section(self, title, row=0):
        if not hasattr(self, "_row"):
            self._row = 0
        tk.Label(self, text=title, bg="#2a2a2a", fg="#ff8844",
                 font=("Consolas", 9, "bold"), anchor="w").grid(
                     row=row, column=0, columnspan=3, padx=8, pady=(8, 0), sticky="we")

    def _field(self, label, sv, row):
        tk.Label(self, text=label, bg="#1a1a1a", fg="#aaa",
                 font=("Consolas", 9)).grid(row=row, column=0, padx=10, pady=3, sticky="e")
        tk.Entry(self, textvariable=sv, bg="#111", fg="white",
                 font=("Consolas", 9), insertbackground="white",
                 width=20).grid(row=row, column=1, padx=4, pady=3, sticky="we")

    def _load_interfaces(self):
        self._iface_list.delete(0, tk.END)
        import socket as _s
        try:
            import psutil
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == _s.AF_INET:
                        self._iface_list.insert(tk.END, f"{iface}: {addr.address}")
        except ImportError:
            # Fallback without psutil
            hostname = _s.gethostname()
            for ip in _s.getaddrinfo(hostname, None):
                if ip[0] == _s.AF_INET:
                    self._iface_list.insert(tk.END, f"?: {ip[4][0]}")

    def _discover(self):
        sel = self._iface_list.curselection()
        if not sel:
            messagebox.showwarning("Interface Required",
                                   "Select a network interface first.", parent=self)
            return
        item = self._iface_list.get(sel[0])
        iface_ip = item.split(":")[-1].strip()
        self._status_lbl.configure(text=f"Discovering on {iface_ip}…")

        def done(devices):
            if devices:
                first_ip = devices[0]["ip"]
                names    = "\n".join(f"  {d['name']} @ {d['ip']}" for d in devices)
                self.after(0, lambda: self._sv_ip.set(first_ip))
                self.after(0, lambda: self._discovered_lbl.configure(
                    text=f"Found {len(devices)} device(s)", fg="#0f0"))
                self.after(0, lambda: messagebox.showinfo("Discovered", names, parent=self))
            else:
                self.after(0, lambda: self._discovered_lbl.configure(
                    text="No devices found", fg="#f44"))
            self.after(0, lambda: self._status_lbl.configure(text=""))

        self._service.discover(iface_ip, done)

    def _randomize(self):
        import random
        self._sv_udp.set(str(random.randint(1024, 65535)))
        self._sv_recv.set(str(random.randint(1024, 65535)))

    def _save(self):
        self._cfg["device_ip"]          = self._sv_ip.get().strip()
        self._cfg["udp_port"]           = int(self._sv_udp.get() or 4626)
        self._cfg["receiver_port"]      = int(self._sv_recv.get() or 7800)
        self._cfg["polling_rate_ms"]    = max(10, int(self._sv_poll.get() or 100))
        self._cfg["auto_start_streaming"] = self._sv_auto_stream.get()
        self._on_save(self._cfg)
        self.destroy()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app = LightControlApp()
    app.mainloop()
