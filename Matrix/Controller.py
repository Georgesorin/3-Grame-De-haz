import tkinter as tk
from tkinter import colorchooser, ttk
import socket
import threading
import time
import random
import struct
import psutil
import math
import colorsys
import os
import json
from matrix_font import FONT_5x7
from small_font import FONT_3x5

# --- Constants ---
UDP_SEND_IP = "255.255.255.255"
# SEND_PORT is now dynamic from CONFIG
# RECV_PORT is now dynamic from CONFIG
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
FRAME_DATA_LENGTH = NUM_CHANNELS * LEDS_PER_CHANNEL * 3

BOARD_WIDTH = 16
BOARD_HEIGHT = 32 # Full Matrix

_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrix_ctrl_config.json")

def _load_config():
    defaults = {
        "device_ip": "255.255.255.255",
        "send_port": 4626,
        "recv_port": 7800,
        "auto_start_streaming": False,
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

# Colors
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)
GREEN = (0, 255, 0)
BLUE = (0, 0, 255)
YELLOW = (255, 255, 0)
CYAN = (0, 255, 255)
MAGENTA = (255, 0, 255)
ORANGE = (255, 165, 0)

class NetworkManager:
    def __init__(self):
        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.running = True
        self.sequence_number = 0
        self.bind_ip = "0.0.0.0"
        self.target_ip = CONFIG.get("device_ip", "255.255.255.255")
        self.send_port = CONFIG.get("send_port", 4626)
        
        # Priority: Auto-detecting 169.254 (for hardware)

    def _auto_bind(self):
        # Auto-Bind Logic
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET and addr.address.startswith("169.254"):
                        self.set_interface(addr.address)
                        return
        except: pass

    def set_interface(self, ip):
        if self.bind_ip == ip: return
        self.bind_ip = ip
        print(f"Binding Network to {self.bind_ip}")
        try:
            self.sock_send.close()
            self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if self.bind_ip != "0.0.0.0":
                self.sock_send.bind((self.bind_ip, 0))
        except Exception as e:
            print(f"Error binding port: {e}")

    def discover(self, iface_ip, target_port, callback):
        def _thread():
            import time
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            sock.settimeout(0.5)
            try:
                sock.bind((iface_ip, 0))
            except:
                sock.close()
                callback([])
                return
            
            sock.sendto(b'y', ("255.255.255.255", target_port))
            
            devices = []
            deadline = time.time() + 3
            while time.time() < deadline:
                try:
                    data, addr = sock.recvfrom(1024)
                    if data == b'y':
                        if addr[0] not in [d['ip'] for d in devices]:
                            devices.append({"ip": addr[0], "name": f"Matrix Device @ {addr[0]}"})
                except socket.timeout:
                    continue
                except: break
            sock.close()
            callback(devices)

        threading.Thread(target=_thread, daemon=True).start()

    def send_packet(self, frame_data):
        # Protocol v11 Implementation
        self.sequence_number = (self.sequence_number + 1) & 0xFFFF
        if self.sequence_number == 0: self.sequence_number = 1
        
        target_ip = self.target_ip
        port = self.send_port
        
        # --- 1. Start Packet ---
        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        start_packet = bytearray([
            0x75, rand1, rand2, 0x00, 0x08, 
            0x02, 0x00, 0x00, 0x33, 0x44,   
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00 
        ])
        start_packet.append(0x0E) # Force Checksum
        start_packet.append(0x00) 
        try: 
            self.sock_send.sendto(start_packet, (target_ip, port))
            self.sock_send.sendto(start_packet, ("127.0.0.1", port))
        except: pass

        # --- 2. FFF0 Packet ---
        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        
        fff0_payload = bytearray()
        for _ in range(NUM_CHANNELS):
            fff0_payload += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])

        fff0_internal = bytearray([
            0x02, 0x00, 0x00, 
            0x88, 0x77, 
            0xFF, 0xF0, 
            (len(fff0_payload) >> 8) & 0xFF, (len(fff0_payload) & 0xFF)
        ]) + fff0_payload
        
        fff0_len = len(fff0_internal) - 1
        
        fff0_packet = bytearray([
            0x75, rand1, rand2, 
            (fff0_len >> 8) & 0xFF, (fff0_len & 0xFF)
        ]) + fff0_internal
        fff0_packet.append(0x1E) # Force Checksum
        fff0_packet.append(0x00) 
        
        try: 
            self.sock_send.sendto(fff0_packet, (target_ip, port))
            self.sock_send.sendto(fff0_packet, ("127.0.0.1", port))
        except: pass
        
        # --- 3. Data Packets ---
        chunk_size = 984 
        data_packet_index = 1
        
        for i in range(0, len(frame_data), chunk_size):
            rand1 = random.randint(0, 127)
            rand2 = random.randint(0, 127)

            chunk = frame_data[i:i+chunk_size]
            
            internal_data = bytearray([
                0x02, 0x00, 0x00, 
                0x88, 0x77, 
                (data_packet_index >> 8) & 0xFF, (data_packet_index & 0xFF), 
                (len(chunk) >> 8) & 0xFF, (len(chunk) & 0xFF) 
            ])
            internal_data += chunk
            
            payload_len = len(internal_data) - 1 
            
            packet = bytearray([
                0x75, rand1, rand2,
                (payload_len >> 8) & 0xFF, (payload_len & 0xFF)
            ]) + internal_data
            
            if len(chunk) == 984:
                packet.append(0x1E) 
            else:
                packet.append(0x36) 
                
            packet.append(0x00)
            
            try: 
                self.sock_send.sendto(packet, (target_ip, port))
                self.sock_send.sendto(packet, ("127.0.0.1", port))
            except: pass
            
            data_packet_index += 1
            time.sleep(0.002) # Faster for GUI

        # --- 4. End Packet ---
        rand1 = random.randint(0, 127)
        rand2 = random.randint(0, 127)
        end_packet = bytearray([
            0x75, rand1, rand2, 0x00, 0x08,
            0x02, 0x00, 0x00, 0x55, 0x66,
            (self.sequence_number >> 8) & 0xFF,
            self.sequence_number & 0xFF,
            0x00, 0x00, 0x00 
        ])
        end_packet.append(0x0E) 
        end_packet.append(0x00) 
        try: 
            self.sock_send.sendto(end_packet, (target_ip, port))
            self.sock_send.sendto(end_packet, ("127.0.0.1", port))
        except: pass

class MatrixGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Matrix GUI Controller (16x32)")
        self.root.configure(bg="#1a1a1a")
        
        self.grid_width = BOARD_WIDTH
        self.grid_height = BOARD_HEIGHT
        
        self.current_color = RED
        self.is_sending = False
        self.cell_size = 20 # Initial user default
        self.animation_mode = "Manual"
        self.time_counter = 0

        # Grid State: (x, y) -> Color
        self.grid_data = {} 
        for y in range(self.grid_height):
            for x in range(self.grid_width):
                self.grid_data[(x, y)] = BLACK

        # Setup Network
        self.network = NetworkManager()
        self.send_lock = threading.Lock()
        
        # Trigger States: dict mapping (ch, led) to bool
        self.trigger_states = {}
        
        # Initialize port variables BEFORE binding
        self.port_out_var = tk.StringVar(value=str(CONFIG.get("send_port", 4626)))
        self.port_in_var = tk.StringVar(value=str(CONFIG.get("recv_port", 7800)))

        self.receiver_running = True
        self.sock_recv = None
        self._bind_receiver()
        threading.Thread(target=self.receiver_loop, daemon=True).start()
        
        # --- UI Layout ---
        main_frame = tk.Frame(root, bg="#1a1a1a")
        main_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        if CONFIG.get("auto_start_streaming", False):
            self.root.after(1000, self.toggle_sending)
        
        # Canvas
        self.canvas = tk.Canvas(main_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.canvas.bind("<B1-Motion>", self.paint)
        self.canvas.bind("<Button-1>", self.paint)
        self.canvas.bind("<Configure>", self.on_resize)
        
        # Controls
        control_frame = tk.Frame(root, width=200, bg="#222")
        control_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=10, pady=10)
        
        tk.Label(control_frame, text="TOOLS", bg="#222", fg="#888", font=("Consolas", 10, "bold")).pack(pady=5)
        
        # Config Button at top
        tk.Button(control_frame, text="⚙ Config", command=self._open_config, bg="#444", fg="white", font=("Consolas", 9, "bold"), relief="flat").pack(fill=tk.X, pady=5, padx=5)

        self.btn_send = tk.Button(control_frame, text="START STREAM", command=self.toggle_sending, bg="green", fg="white", font=("Consolas", 10, "bold"), relief="flat")
        self.btn_send.pack(fill=tk.X, pady=5, padx=5)
        
        tk.Button(control_frame, text="Clear Board", command=self.clear_board, bg="#444", fg="white", font=("Consolas", 9), relief="flat").pack(fill=tk.X, pady=5, padx=5)
        
        # Animation Controls
        tk.Label(control_frame, text="ANIMATION MODE", bg="#222", fg="#888", font=("Consolas", 10, "bold")).pack(pady=5)
        self.anim_var = tk.StringVar(value="Manual")
        self.anim_combo = ttk.Combobox(control_frame, textvariable=self.anim_var)
        self.anim_combo['values'] = ("Manual", "Rainbow Wave", "Pulse", "Matrix Rain", "Sparkle", "Text", "Scrolling Text")
        self.anim_combo.pack(fill=tk.X, pady=5, padx=5)
        self.anim_combo.bind("<<ComboboxSelected>>", self.on_anim_change)
        
        # Text Controls
        text_frame = tk.LabelFrame(control_frame, text=" Text Settings ", bg="#222", fg="#aaa", font=("Consolas", 9, "bold"))
        text_frame.pack(fill=tk.X, pady=5, padx=5)
        
        self.text_var = tk.StringVar(value="HELLO")
        tk.Entry(text_frame, textvariable=self.text_var, bg="#111", fg="#0f0", font=("Consolas", 9), insertbackground="white").pack(fill=tk.X, padx=5, pady=5)
        
        spin_frame = tk.Frame(text_frame, bg="#222")
        spin_frame.pack(fill=tk.X, padx=5)
        tk.Label(spin_frame, text="X:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_x = tk.Spinbox(spin_frame, from_=-100, to=BOARD_WIDTH, width=4)
        self.text_x.pack(side=tk.LEFT, padx=(0, 5))
        
        tk.Label(spin_frame, text="Y:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_y = tk.Spinbox(spin_frame, from_=-100, to=BOARD_HEIGHT, width=4)
        self.text_y.pack(side=tk.LEFT)
        
        rot_frame = tk.Frame(text_frame, bg="#222")
        rot_frame.pack(fill=tk.X, pady=5, padx=5)
        tk.Label(rot_frame, text="Rot:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_rot = ttk.Combobox(rot_frame, values=("0", "90", "180", "270"), width=4)
        self.text_rot.set("0")
        self.text_rot.pack(side=tk.LEFT, padx=(0, 4))

        tk.Label(rot_frame, text="Size:", bg="#222", fg="#aaa", font=("Consolas", 8)).pack(side=tk.LEFT)
        self.text_size = tk.Spinbox(rot_frame, from_=1, to=10, width=3)
        self.text_size.pack(side=tk.LEFT)

        tk.Label(control_frame, text="COLORS", bg="#222", fg="#888", font=("Consolas", 10, "bold")).pack(pady=(10, 2))
        
        # Custom Color Button
        self.btn_custom = tk.Button(control_frame, text="Pick Custom Color", command=self.pick_color, bg="#444", fg="white", font=("Consolas", 9), relief="flat")
        self.btn_custom.pack(fill=tk.X, pady=2, padx=5)
        
        colors_frame = tk.Frame(control_frame, bg="#222")
        colors_frame.pack(fill=tk.X, padx=5)
        
        colors = [
            ("Red", RED), ("Green", GREEN), ("Blue", BLUE),
            ("Yellow", YELLOW), ("Cyan", CYAN), ("Magenta", MAGENTA),
            ("Orange", ORANGE), ("White", WHITE), ("OFF", BLACK)
        ]
        
        for i, (name, col) in enumerate(colors):
            btn = tk.Button(colors_frame, text=name, command=lambda c=col: self.set_color(c), font=("Consolas", 8, "bold"), relief="flat")
            fg = "black" if sum(col) > 300 else "white" 
            hex_col = self.rgb_to_hex(col)
            if name == "OFF": hex_col = "#111"
            btn.configure(bg=hex_col, fg=fg)
            btn.grid(row=i//2, column=i%2, sticky="ew", padx=1, pady=1)
            
        colors_frame.grid_columnconfigure(0, weight=1)
        colors_frame.grid_columnconfigure(1, weight=1)

        self.lbl_net_status = tk.Label(control_frame, text=f"Target: {self.network.target_ip}\nPort OUT:{self.network.send_port} | IN:{CONFIG.get('recv_port')}", bg="#222", fg="#66aa66", font=("Consolas", 8), justify=tk.LEFT)
        self.lbl_net_status.pack(pady=10)

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
        
        self.port_out_var.set(str(CONFIG["send_port"]))
        self.port_in_var.set(str(CONFIG["recv_port"]))
        
        self._bind_receiver()
        self.lbl_net_status.config(text=f"Target: {self.network.target_ip}\nPort OUT:{self.network.send_port} | IN:{CONFIG.get('recv_port')}")
        print(f"Matrix_GUI: Config updated.")

    def _bind_receiver(self):
        p_in = int(self.port_in_var.get())
        try: self.sock_recv.close()
        except: pass
        self.sock_recv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_recv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_recv.settimeout(0.5)
        try:
            self.sock_recv.bind(("0.0.0.0", p_in))
            print(f"Matrix_GUI: Trigger receiver bound to port {p_in}")
        except Exception as e:
            print(f"Matrix_GUI: Failed to bind trigger receiver to {p_in}: {e}")

    def receiver_loop(self):
        while self.receiver_running:
            try:
                data, addr = self.sock_recv.recvfrom(2048)
                if len(data) >= 1373 and data[0] == 0x88:
                    changed = False
                    for ch in range(8):
                        base = 2 + ch * 171
                        for led in range(64):
                            state = (data[base + 1 + led] == 0xCC)
                            if self.trigger_states.get((ch, led), False) != state:
                                self.trigger_states[(ch, led)] = state
                                changed = True
                                print(f"Matrix_GUI PARSED trigger change: ch={ch}, led={led}, state={state}")
                    if changed:
                        self.root.after(0, self.draw_grid)
                elif data[0] == 0x88:
                    print(f"Matrix_GUI DROPPED 0x88 packet because len was only {len(data)}")
            except socket.timeout:
                continue
            except Exception as e:
                print(f"Receiver error: {e}")

    def _update_iface_list(self):
        ips = ["0.0.0.0", "127.0.0.1"]
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        if addr.address not in ips:
                            ips.append(addr.address)
        except: pass
        self.iface_combo['values'] = ips

    def on_anim_change(self, event):
        self.animation_mode = self.anim_var.get()
        print(f"Animation Mode: {self.animation_mode}")

    def rgb_to_hex(self, rgb):
        return "#%02x%02x%02x" % rgb

    def pick_color(self):
        color = colorchooser.askcolor(title="Choose Color")
        if color[0]: # If a color was selected (not None)
            rgb = (int(color[0][0]), int(color[0][1]), int(color[0][2]))
            self.set_color(rgb)
            # Update button visual
            self.btn_custom.config(bg=color[1], fg="black" if sum(rgb) > 300 else "white")

    def set_color(self, color):
        self.current_color = color

    def clear_board(self):
        for k in self.grid_data:
            self.grid_data[k] = BLACK
        self.draw_grid()
    
    def on_resize(self, event):
        w = event.width
        h = event.height
        
        # Calculate max cell size that fits
        cell_w = w / self.grid_width
        cell_h = h / self.grid_height
        self.cell_size = min(cell_w, cell_h)
        self.draw_grid()

    def paint(self, event):
        if self.animation_mode != "Manual": return
        x = int(event.x // self.cell_size)
        y = int(event.y // self.cell_size)
        
        if 0 <= x < self.grid_width and 0 <= y < self.grid_height:
            self.grid_data[(x, y)] = self.current_color
            self.draw_cell(x, y, self.current_color)

    def draw_cell(self, x, y, color):
        x1 = x * self.cell_size
        y1 = y * self.cell_size
        x2 = x1 + self.cell_size
        y2 = y1 + self.cell_size
        hex_col = self.rgb_to_hex(color)
        
        ch = y // 4
        row_in_channel = y % 4
        led = (row_in_channel * 16 + x) if row_in_channel % 2 == 0 else (row_in_channel * 16 + (15 - x))
        is_triggered = self.trigger_states.get((ch, led), False)

        self.canvas.create_rectangle(x1, y1, x2, y2, fill=hex_col, outline="white" if is_triggered else "gray", width=2 if is_triggered else 1)
        if is_triggered:
            lum = 0.299*color[0] + 0.587*color[1] + 0.114*color[2]
            t_col = "black" if lum > 128 else "white"
            self.canvas.create_text(x1 + self.cell_size/2, y1 + self.cell_size/2, text="T", fill=t_col, font=("Consolas", int(self.cell_size*0.6) or 8, "bold"))

    def draw_grid(self):
        self.canvas.delete("all")
        for y in range(self.grid_height):
            for x in range(self.grid_width):
                self.draw_cell(x, y, self.grid_data[(x, y)])

    def toggle_sending(self):
        self.is_sending = not self.is_sending
        if self.is_sending:
            self.btn_send.config(text="STOP STREAM", bg="red")
            t = threading.Thread(target=self.sending_loop)
            t.daemon = True
            t.start()
        else:
            self.btn_send.config(text="START STREAM", bg="green")

    def set_led(self, buffer, x, y, color):
        # Mapping Logic
        if x < 0 or x >= 16: return
        channel = y // 4
        if channel >= 8: return
        row_in_channel = y % 4
        
        # Zig-Zag logic derived from Tetris_Game
        if row_in_channel % 2 == 0: led_index = row_in_channel * 16 + x
        else: led_index = row_in_channel * 16 + (15 - x)
        
        block_size = NUM_CHANNELS * 3
        offset = led_index * block_size + channel
        
        if offset + NUM_CHANNELS*2 < len(buffer):
            buffer[offset] = color[1] # Green/Red Swap
            buffer[offset + NUM_CHANNELS] = color[0] # Green/Red Swap
            buffer[offset + NUM_CHANNELS*2] = color[2]

    def render_frame(self):
        buffer = bytearray(FRAME_DATA_LENGTH)
        
        if self.animation_mode == "Manual":
            current_grid = self.grid_data
        else:
            current_grid = self.generate_animation_frame()

        for (x, y), color in current_grid.items():
            self.set_led(buffer, x, y, color)
        
        # Update UI sometimes (optional, heavy for 20FPS but good for debug)
        # To avoid lag, maybe only update UI every 5 frames?
        if self.animation_mode != "Manual":
            self.grid_data = current_grid 
            if self.time_counter % 2 == 0: 
                 self.root.after(0, self.draw_grid) # update UI in main thread

        return buffer

    def generate_animation_frame(self):
        frame_grid = {}
        t = self.time_counter * 0.1
        
        if self.animation_mode == "Rainbow Wave":
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    hue = (x * 0.05 + y * 0.05 + t * 0.2) % 1.0
                    r, g, b = colorsys.hsv_to_rgb(hue, 1.0, 1.0)
                    frame_grid[(x, y)] = (int(r * 255), int(g * 255), int(b * 255))
        
        elif self.animation_mode == "Pulse":
            val = (math.sin(t) + 1) / 2 # 0 to 1
            r = int(self.current_color[0] * val)
            g = int(self.current_color[1] * val)
            b = int(self.current_color[2] * val)
            col = (r, g, b)
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    frame_grid[(x, y)] = col
                    
        elif self.animation_mode == "Matrix Rain":
             # Initialize drops if needed
            if not hasattr(self, 'rain_drops'):
                self.rain_drops = [random.randint(-10, 0) for _ in range(BOARD_WIDTH)]
            
            # Fade existing
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    prev = self.grid_data.get((x, y), BLACK)
                    # Dim by 20%
                    frame_grid[(x, y)] = (0, max(0, prev[1] - 30), 0)

            # Update drops
            for x in range(BOARD_WIDTH):
                if random.random() < 0.05: # Random spawn
                    self.rain_drops[x] = 0
                
                head_y = self.rain_drops[x]
                if 0 <= head_y < BOARD_HEIGHT:
                    frame_grid[(x, head_y)] = (0, 255, 0) # Bright Green Head
                
                if head_y < BOARD_HEIGHT + 5:
                    self.rain_drops[x] += 1
                else:
                     self.rain_drops[x] = random.randint(-15, -1)
        
        elif self.animation_mode == "Sparkle":
             for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                     # Fade
                    prev = self.grid_data.get((x, y), BLACK)
                    frame_grid[(x, y)] = (max(0, prev[0]-25), max(0, prev[1]-25), max(0, prev[2]-25))
            
             for _ in range(5):
                 rx = random.randint(0, BOARD_WIDTH-1)
                 ry = random.randint(0, BOARD_HEIGHT-1)
                 frame_grid[(rx, ry)] = (255, 255, 255)

        elif self.animation_mode in ["Text", "Scrolling Text"]:
            text_str = self.text_var.get()
            try:
                rot = int(self.text_rot.get())
            except ValueError:
                rot = 0
                
            for y in range(BOARD_HEIGHT):
                for x in range(BOARD_WIDTH):
                    frame_grid[(x, y)] = BLACK
                    
            if self.animation_mode == "Scrolling Text":
                text_width = len(text_str) * 6
                speed = 1.0 
                screen_len = BOARD_WIDTH if rot in (0, 180) else BOARD_HEIGHT
                total_scroll = max(1, text_width + screen_len)
                vx_offset = screen_len - (int(self.time_counter * speed) % total_scroll)
            else:
                try:
                    vx_offset = int(self.text_x.get())
                except ValueError:
                    vx_offset = 0

            try:
                start_vy = int(self.text_y.get())
            except ValueError:
                start_vy = 0
                
            try:
                scale_input = int(self.text_size.get())
            except ValueError:
                scale_input = 1
                
            if scale_input == 1:
                cur_font = FONT_3x5
                char_w = 3
                char_h = 5
                render_scale = 1
            else:
                cur_font = FONT_5x7
                char_w = 5
                char_h = 7
                render_scale = scale_input - 1
                
            for char_idx, char in enumerate(text_str):
                char_data = cur_font.get(char, cur_font.get('?', [0]*char_w))
                for col_idx, col_byte in enumerate(char_data):
                    for sx in range(render_scale):
                        vx = vx_offset + (char_idx * (char_w + 1) * render_scale) + (col_idx * render_scale) + sx
                        for row_idx in range(char_h):
                            if (col_byte >> row_idx) & 1:
                                for sy in range(render_scale):
                                    vy = start_vy + (row_idx * render_scale) + sy
                                    
                                    if rot == 0:
                                        px, py = vx, vy
                                    elif rot == 90:
                                        px, py = BOARD_WIDTH - 1 - vy, vx
                                    elif rot == 180:
                                        px, py = BOARD_WIDTH - 1 - vx, BOARD_HEIGHT - 1 - vy
                                    elif rot == 270:
                                        px, py = vy, BOARD_HEIGHT - 1 - vx
                                    else:
                                        px, py = vx, vy
                                        
                                    if 0 <= px < BOARD_WIDTH and 0 <= py < BOARD_HEIGHT:
                                        frame_grid[(px, py)] = self.current_color

        else: # Fallback
            return self.grid_data

        return frame_grid

    def sending_loop(self):
        while self.is_sending:
            frame = self.render_frame()
            self.network.send_packet(frame)
            self.time_counter += 1
            time.sleep(0.05) # ~20 FPS

class ConfigDialog(tk.Toplevel):
    def __init__(self, parent, cfg, on_save):
        super().__init__(parent)
        self.title("Matrix Network Configuration")
        self.configure(bg="#1a1a1a")
        self.resizable(False, False)
        self.grab_set()

        self.cfg = dict(cfg)
        self.on_save = on_save

        self.sv_ip   = tk.StringVar(value=cfg.get("device_ip", "255.255.255.255"))
        self.sv_send = tk.StringVar(value=str(cfg.get("send_port", 4626)))
        self.sv_recv = tk.StringVar(value=str(cfg.get("recv_port", 7800)))
        self.sv_auto_stream = tk.BooleanVar(value=cfg.get("auto_start_streaming", False))
        self.sv_iface = tk.StringVar(value="0.0.0.0")

        self._build()

    def _build(self):
        pad = {'padx': 15, 'pady': 5, 'sticky': "we"}
        
        tk.Label(self, text="NETWORK SETTINGS", bg="#2a2a2a", fg="#ff8844", font=("Consolas", 10, "bold")).grid(row=0, column=0, columnspan=3, padx=10, pady=(10, 5), sticky="we")

        # Fields
        self._field("Target IP:", self.sv_ip, 1)
        self._field("Port OUT (Send):", self.sv_send, 2)
        self._field("Port IN (Recv):", self.sv_recv, 3)

        tk.Button(self, text="🎲 Randomize Ports", command=self._randomize, bg="#444", fg="white", font=("Consolas", 8), relief="flat").grid(row=2, column=2, rowspan=2, padx=10, pady=5, sticky="nsew")

        tk.Checkbutton(self, text="Auto-start stream on launch",
                       variable=self.sv_auto_stream,
                       bg="#1a1a1a", fg="white", selectcolor="#333",
                       activebackground="#1a1a1a", activeforeground="white",
                       font=("Consolas", 9)).grid(row=4, column=0, columnspan=3, padx=10, pady=4, sticky="w")

        # Discovery
        tk.Label(self, text="DEVICE DISCOVERY", bg="#2a2a2a", fg="#ff8844", font=("Consolas", 10, "bold")).grid(row=4, column=0, columnspan=3, padx=10, pady=(15, 5), sticky="we")
        self.lbl_disc = tk.Label(self, text="Ready to scan...", bg="#1a1a1a", fg="#888", font=("Consolas", 8))
        self.lbl_disc.grid(row=5, column=0, columnspan=2, padx=15, pady=5, sticky="w")
        
        tk.Button(self, text="🔍 Discover", command=self._discover, bg="#224", fg="white", font=("Consolas", 9, "bold"), relief="flat").grid(row=5, column=2, padx=10, pady=5, sticky="we")

        # Interface
        tk.Label(self, text="LOCAL INTERFACE", bg="#2a2a2a", fg="#ff8844", font=("Consolas", 10, "bold")).grid(row=6, column=0, columnspan=3, padx=10, pady=(15, 5), sticky="we")
        
        self.iface_combo = ttk.Combobox(self, textvariable=self.sv_iface, state="readonly")
        self.iface_combo.grid(row=7, column=0, columnspan=2, padx=15, pady=5, sticky="we")
        self._load_interfaces()
        
        tk.Button(self, text="Refresh", command=self._load_interfaces, bg="#333", fg="white", font=("Consolas", 8), relief="flat").grid(row=7, column=2, padx=10, pady=5, sticky="we")

        # Buttons
        btn_frame = tk.Frame(self, bg="#1a1a1a")
        btn_frame.grid(row=8, column=0, columnspan=3, pady=15)
        
        tk.Button(btn_frame, text="💾 Save", command=self._save, bg="#226", fg="white", font=("Consolas", 9, "bold"), relief="flat", padx=15, pady=6).pack(side=tk.LEFT, padx=5)
        tk.Button(btn_frame, text="Cancel", command=self.destroy, bg="#333", fg="white", font=("Consolas", 9), relief="flat", padx=15, pady=6).pack(side=tk.LEFT, padx=5)

    def _field(self, label, sv, row):
        tk.Label(self, text=label, bg="#1a1a1a", fg="#aaa", font=("Consolas", 9)).grid(row=row, column=0, padx=15, pady=3, sticky="e")
        tk.Entry(self, textvariable=sv, bg="#111", fg="white", font=("Consolas", 9), insertbackground="white", width=20).grid(row=row, column=1, padx=5, pady=3, sticky="we")

    def _load_interfaces(self):
        ips = ["0.0.0.0", "127.0.0.1"]
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        if addr.address not in ips: ips.append(addr.address)
        except: pass
        self.iface_combo['values'] = ips
        if not self.sv_iface.get() in ips: self.sv_iface.set("0.0.0.0")

    def _randomize(self):
        self.sv_send.set(str(random.randint(1024, 65535)))
        self.sv_recv.set(str(random.randint(1024, 65535)))

    def _discover(self):
        from tkinter import messagebox
        iface = self.sv_iface.get()
        try:
            port = int(self.sv_send.get())
        except: port = 4626
        
        self.lbl_disc.config(text="Scanning...", fg="#ffaa00")
        
        # Access Controller app through parent
        # But ConfigDialog doesn't have a direct reference to the MatrixGUI app instance
        # Let's pass it in or find it.
        # For simplicity, we can instantiate a temporary NetworkManager or just use socket directly in _thread.
        # I already implemented discover() in NetworkManager, but I need an instance.
        
        from tkinter import messagebox
        
        def callback(devices):
            if devices:
                names = "\n".join([f"{d['name']}" for d in devices])
                self.sv_ip.set(devices[0]['ip'])
                self.lbl_disc.config(text=f"Found {len(devices)} device(s)", fg="#00ff00")
                messagebox.showinfo("Discovered", f"Found devices:\n{names}")
            else:
                self.lbl_disc.config(text="No devices found", fg="#ff4444")
        
        # We need a NetworkManager instance. We can create a temp one.
        temp_net = NetworkManager()
        temp_net.discover(iface, port, callback)

    def _save(self):
        try:
            self.cfg["device_ip"] = self.sv_ip.get().strip()
            self.cfg["send_port"] = int(self.sv_send.get())
            self.cfg["recv_port"] = int(self.sv_recv.get())
            self.cfg["auto_start_streaming"] = self.sv_auto_stream.get()
            self.cfg["bind_ip"] = self.sv_iface.get()
            self.on_save(self.cfg)
            self.destroy()
        except ValueError:
            pass

if __name__ == "__main__":
    root = tk.Tk()
    app = MatrixGUI(root)
    root.mainloop()
