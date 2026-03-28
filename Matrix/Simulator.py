import tkinter as tk
from tkinter import scrolledtext
import socket
import threading
import time
import struct
import psutil
import json
import os
from datetime import datetime
from tkinter import ttk

# --- Configuration ---
_CFG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "matrix_sim_config.json")

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
VIRTUAL_IP = CONFIG.get("virtual_iface_ip", "")

BOARD_WIDTH = 16
BOARD_HEIGHT = 32
NUM_CHANNELS = 8
LEDS_PER_CHANNEL = 64
PIXEL_TIMEOUT = 3.0 # Seconds

# --- Simulator Class ---
class MatrixSimulator:
    def __init__(self, root):
        self.root = root
        self.root.title("Matrix Simulator (16x32)")
        self.root.configure(bg="#1a1a1a")

        self.cell_size = 20
        self.fullscreen = False
        
        # Grid Data: (x, y) -> Color (R, G, B)
        self.grid_data = {}
        self.pixel_timestamps = {}
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                self.grid_data[(x, y)] = (0, 0, 0)
                self.pixel_timestamps[(x, y)] = 0

        # State
        self.running = True
        self.packet_count = 0
        self.frame_buffer = bytearray(NUM_CHANNELS * LEDS_PER_CHANNEL * 3)
        self.bind_ip = "0.0.0.0"
        
        # Ports
        self.listen_port = CONFIG.get("recv_port", 4626)
        self.send_port = CONFIG.get("send_port", 7800)

        # Button states for input
        self.pressed_leds = set()
        self.current_pressed_pos = None

        # UI Setup
        self.create_widgets()
        
        # Network Setup
        self.setup_network()
        
        # Threads
        self.net_thread = threading.Thread(target=self.network_loop, daemon=True)
        self.net_thread.start()
        
        self.timeout_thread = threading.Thread(target=self.timeout_loop, daemon=True)
        self.timeout_thread.start()
        
        # UI Update Loop for stats
        self.update_stats()

    def log(self, msg):
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        self.log_area.configure(state='normal')
        self.log_area.insert(tk.END, f"[{timestamp}] {msg}\n")
        self.log_area.see(tk.END)
        self.log_area.configure(state='disabled')

    def create_widgets(self):
        # Top Control bar
        control_frame = tk.Frame(self.root, bg="#2a2a2a")
        control_frame.pack(side=tk.TOP, fill=tk.X)
        
        # RX Indicator
        self.lbl_rx = tk.Label(control_frame, text="● RX", bg="#2a2a2a", fg="#555", font=("Consolas", 10, "bold"))
        self.lbl_rx.pack(side=tk.LEFT, padx=5, pady=6)

        self.lbl_stats = tk.Label(control_frame, text="Packets: 0 | Ready", bg="#2a2a2a", fg="#00FF00", font=("Consolas", 9, "bold"))
        self.lbl_stats.pack(side=tk.LEFT, padx=10, pady=6)
        
        tk.Label(control_frame, text="Net:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self.iface_var = tk.StringVar(value=self.bind_ip)
        self.iface_combo = ttk.Combobox(control_frame, textvariable=self.iface_var, width=15, state="readonly")
        self.iface_combo.pack(side=tk.LEFT, padx=5)
        self._update_iface_list()
        self.iface_combo.bind("<<ComboboxSelected>>", self._on_interface_change)

        # Port Settings
        tk.Label(control_frame, text="Port IN:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self.port_in_var = tk.StringVar(value=str(self.listen_port))
        self.ent_port_in = tk.Entry(control_frame, textvariable=self.port_in_var, width=6, bg="#111", fg="#0f0", font=("Consolas", 9))
        self.ent_port_in.pack(side=tk.LEFT, padx=2)
        self.ent_port_in.bind("<FocusOut>", self.apply_ports)
        self.ent_port_in.bind("<Return>", self.apply_ports)

        tk.Button(control_frame, text="🎲", command=self.randomize_port, bg="#444", fg="white", font=("Consolas", 8), relief="flat").pack(side=tk.LEFT, padx=2)

        tk.Label(control_frame, text="Port OUT:", bg="#2a2a2a", fg="#888", font=("Consolas", 8)).pack(side=tk.LEFT, padx=(10, 2))
        self.port_out_var = tk.StringVar(value=str(self.send_port))
        self.ent_port_out = tk.Entry(control_frame, textvariable=self.port_out_var, width=6, bg="#111", fg="#0f0", font=("Consolas", 9))
        self.ent_port_out.pack(side=tk.LEFT, padx=2)
        self.ent_port_out.bind("<FocusOut>", self.apply_ports)
        self.ent_port_out.bind("<Return>", self.apply_ports)

        tk.Label(control_frame, text="F11: Fullscreen | ESC: Exit", bg="#2a2a2a", fg="#aaa", font=("Consolas", 8)).pack(side=tk.RIGHT, padx=10)

        # Main horizontal split
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, bg="#1a1a1a", sashwidth=4, sashpad=0)
        main_pane.pack(fill=tk.BOTH, expand=True)

        # Left: Canvas
        self.canvas = tk.Canvas(main_pane, bg="black", highlightthickness=0)
        main_pane.add(self.canvas, stretch="always")

        # Right: Log Area
        log_frame = tk.Frame(main_pane, bg="#222", width=300)
        main_pane.add(log_frame, stretch="never")
        
        tk.Label(log_frame, text="NETWORK LOGS", bg="#444", fg="white", font=("Consolas", 9, "bold")).pack(fill=tk.X)
        self.log_area = scrolledtext.ScrolledText(log_frame, bg="#111", fg="#00FF00", font=("Consolas", 8), state='disabled', borderwidth=0)
        self.log_area.pack(fill=tk.BOTH, expand=True)

        # Bindings
        self.root.bind("<f>", self.toggle_fullscreen)
        self.root.bind("<F11>", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.exit_fullscreen)
        self.canvas.bind("<ButtonPress-1>", self.on_press)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<B1-Motion>", self.on_motion)
        self.root.bind("<Configure>", self.on_resize)

    def _update_iface_list(self):
        ips = ["0.0.0.0"]
        try:
            for iface, addrs in psutil.net_if_addrs().items():
                for addr in addrs:
                    if addr.family == socket.AF_INET:
                        ips.append(addr.address)
        except: pass
        self.iface_combo['values'] = ips

    def _on_interface_change(self, event=None):
        new_ip = self.iface_var.get()
        if new_ip == self.bind_ip: return
        self.log(f"Switching interface to {new_ip}...")
        self.bind_ip = new_ip
        self.setup_network()

    def randomize_port(self):
        import random
        new_in = random.randint(1024, 65535)
        new_out = random.randint(1024, 65535)
        self.port_in_var.set(str(new_in))
        self.port_out_var.set(str(new_out))
        self.apply_ports()

    def apply_ports(self, event=None):
        try:
            p_in = int(self.port_in_var.get())
            p_out = int(self.port_out_var.get())
            if p_in < 1024 or p_in > 65535 or p_out < 1024 or p_out > 65535:
                raise ValueError
            if p_in == self.listen_port and p_out == self.send_port:
                return
            
            self.listen_port = p_in
            self.send_port = p_out
            self.log(f"Ports updated -> IN:{self.listen_port}, OUT:{self.send_port}")
            
            # Save to config
            CONFIG["recv_port"] = self.listen_port
            CONFIG["send_port"] = self.send_port
            _save_config(CONFIG)
            
            self.setup_network()
        except:
            self.port_in_var.set(str(self.listen_port))
            self.port_out_var.set(str(self.send_port))

    def setup_network(self):
        # Close old sockets if they exist
        if hasattr(self, 'sock_listen'):
            try: self.sock_listen.close()
            except: pass
        if hasattr(self, 'sock_send'):
            try: self.sock_send.close()
            except: pass

        self.sock_listen = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_listen.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock_listen.settimeout(0.5)
        try:
            self.sock_listen.bind((self.bind_ip, self.listen_port))
            self.log(f"Listening on {self.bind_ip}:{self.listen_port}")
        except Exception as e:
            self.log(f"Error binding listen port {self.listen_port}: {e}")

        self.sock_send = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock_send.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        
        # Use a specific source IP for sending if bound to a specific interface
        try: 
            self.sock_send.bind((self.bind_ip, 0))
            self.log(f"Sender bound to {self.bind_ip}")
        except: 
            try: self.sock_send.bind(("0.0.0.0", 0))
            except: pass

    def draw_grid(self):
        self.canvas.delete("all")
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        if w < 10 or h < 10:
             w = BOARD_WIDTH * self.cell_size
             h = BOARD_HEIGHT * self.cell_size
             
        cell_w = w / BOARD_WIDTH
        cell_h = h / BOARD_HEIGHT
        self.cell_size = min(cell_w, cell_h)
        
        offset_x = (w - (self.cell_size * BOARD_WIDTH)) / 2
        offset_y = (h - (self.cell_size * BOARD_HEIGHT)) / 2

        self.rects = {}
        self.trigger_texts = {}
        for y in range(BOARD_HEIGHT):
            for x in range(BOARD_WIDTH):
                x1 = offset_x + x * self.cell_size
                y1 = offset_y + y * self.cell_size
                x2 = x1 + self.cell_size
                y2 = y1 + self.cell_size
                
                ch, led = self._xy_to_ch_led(x, y)
                is_triggered = (ch, led) in self.pressed_leds
                
                color = self.grid_data[(x, y)]
                hex_col = "#%02x%02x%02x" % color
                
                # Outline white if triggered, dark grey otherwise
                self.rects[(x, y)] = self.canvas.create_rectangle(
                    x1, y1, x2, y2, fill=hex_col, outline="white" if is_triggered else "#222222", width=2 if is_triggered else 1
                )
                
                if is_triggered:
                    lum = 0.299*color[0] + 0.587*color[1] + 0.114*color[2]
                    t_col = "black" if lum > 128 else "white"
                    self.trigger_texts[(x, y)] = self.canvas.create_text(
                        x1 + self.cell_size/2, y1 + self.cell_size/2, text="T", fill=t_col, font=("Consolas", int(self.cell_size*0.6) or 8, "bold")
                    )

    def on_resize(self, event):
        self.draw_grid()

    def update_pixel(self, x, y, r, g, b, timestamp=None):
        if (x, y) in self.rects:
            color = (r, g, b)
            if timestamp is not None: self.pixel_timestamps[(x, y)] = timestamp
            
            # Recheck trigger state for this pixel
            ch, led = self._xy_to_ch_led(x, y)
            is_triggered = (ch, led) in self.pressed_leds
            
            # Update grid data and visual
            self.grid_data[(x, y)] = color
            hex_col = "#%02x%02x%02x" % color
            
            self.canvas.itemconfig(self.rects[(x, y)], fill=hex_col, outline="white" if is_triggered else "#222222", width=2 if is_triggered else 1)
            
            # Handle T text
            if is_triggered:
                lum = 0.299*color[0] + 0.587*color[1] + 0.114*color[2]
                t_col = "black" if lum > 128 else "white"
                
                if (x, y) in self.trigger_texts:
                    self.canvas.itemconfig(self.trigger_texts[(x, y)], fill=t_col)
                    self.canvas.tag_raise(self.trigger_texts[(x, y)])
                else:
                    x1 = self.canvas.coords(self.rects[(x, y)])[0]
                    y1 = self.canvas.coords(self.rects[(x, y)])[1]
                    self.trigger_texts[(x, y)] = self.canvas.create_text(
                        x1 + self.cell_size/2, y1 + self.cell_size/2, text="T", fill=t_col, font=("Consolas", int(self.cell_size*0.6) or 8, "bold")
                    )
            elif (x, y) in self.trigger_texts:
                self.canvas.delete(self.trigger_texts[(x, y)])
                del self.trigger_texts[(x, y)]

    def flash_rx(self):
        self.lbl_rx.config(fg="#0f0")
        if hasattr(self, '_rx_timer'): self.root.after_cancel(self._rx_timer)
        self._rx_timer = self.root.after(50, lambda: self.lbl_rx.config(fg="#555"))

    def update_stats(self):
        if self.running:
            self.lbl_stats.config(text=f"Packets: {self.packet_count}")
            self.root.after(500, self.update_stats)

    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)
        self.root.update()
        self.draw_grid()

    def exit_fullscreen(self, event=None):
        if self.fullscreen:
            self.fullscreen = False
            self.root.attributes("-fullscreen", False)
            self.root.update()
            self.draw_grid()

    def _get_button_pos(self, event):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        offset_x = (w - (self.cell_size * BOARD_WIDTH)) / 2
        offset_y = (h - (self.cell_size * BOARD_HEIGHT)) / 2
        rel_x, rel_y = event.x - offset_x, event.y - offset_y
        x, y = int(rel_x // self.cell_size), int(rel_y // self.cell_size)

        if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
            return x, y
        return None, None

    def _xy_to_ch_led(self, x, y):
        ch = y // 4
        row_in_channel = y % 4
        led = (row_in_channel * 16 + x) if row_in_channel % 2 == 0 else (row_in_channel * 16 + (15 - x))
        return ch, led

    def on_press(self, event):
        x, y = self._get_button_pos(event)
        if x is not None:
            self.current_pressed_pos = (x, y)
            ch, led = self._xy_to_ch_led(x, y)
            self.pressed_leds.add((ch, led))
            self.update_pixel(x, y, *self.grid_data[(x, y)]) # Force visual update
            self.log(f"Input Trigger Pressed: Row {y}, Col {x}")
            self.send_input_packet()

    def on_motion(self, event):
        x, y = self._get_button_pos(event)
        if (x, y) != getattr(self, 'current_pressed_pos', None):
            # Release previous
            if getattr(self, 'current_pressed_pos', None) is not None:
                old_x, old_y = self.current_pressed_pos
                old_ch, old_led = self._xy_to_ch_led(old_x, old_y)
                self.pressed_leds.discard((old_ch, old_led))
            
            # Press new
            self.current_pressed_pos = (x, y) if x is not None else None
            if x is not None:
                ch, led = self._xy_to_ch_led(x, y)
                self.pressed_leds.add((ch, led))
                self.update_pixel(x, y, *self.grid_data[(x, y)]) # Force visual update
                self.log(f"Input Trigger Swiped To: Row {y}, Col {x}")
            
            self.send_input_packet()

    def on_release(self, event):
        if getattr(self, 'current_pressed_pos', None) is not None:
            x, y = self.current_pressed_pos
            ch, led = self._xy_to_ch_led(x, y)
            self.pressed_leds.discard((ch, led))
            self.update_pixel(x, y, *self.grid_data[(x, y)]) # Force visual update
            self.log(f"Input Trigger Released: Row {y}, Col {x}")
            self.current_pressed_pos = None
            self.send_input_packet()

    def send_input_packet(self):
        pkt = bytearray(1373)
        pkt[0] = 0x88
        pkt[1] = 0x01
        
        has_triggers = False
        for ch in range(8):
            base = 2 + ch * 171
            pkt[base] = 0x00
            for idx in range(64):
                if (ch, idx) in self.pressed_leds:
                    pkt[base + 1 + idx] = 0xCC
                    has_triggers = True
                else:
                    pkt[base + 1 + idx] = 0x00
                    
        if has_triggers:
            print(f"Simulator SENDING 1373-byte packet with ACTIVE triggers: {self.pressed_leds}")
            
        pkt[-1] = sum(pkt[:-1]) & 0xFF
        
        # To hit all targets without broadcasts, we spray to localhost + broadcast
        # Using the configurable self.send_port
        targets = [("127.0.0.1", self.send_port), ("255.255.255.255", self.send_port)]
        
        for addr in targets:
            try:
                self.sock_send.sendto(pkt, addr)
            except:
                pass
        
        try:
            if getattr(self, "bind_ip", None) and self.bind_ip not in ["0.0.0.0", "127.0.0.1"]:
                parts = self.bind_ip.split('.')
                bcast = f"{parts[0]}.{parts[1]}.{parts[2]}.255"
                self.sock_send.sendto(pkt, (bcast, self.send_port))
            else:
                self.sock_send.sendto(pkt, ("255.255.255.255", self.send_port))
        except: pass

    def network_loop(self):
        while self.running:
            try:
                data, addr = self.sock_listen.recvfrom(2048)
                if not data: continue
                self.packet_count += 1
                
                if data == b'y' or data[0] == 0x67: # Discovery (support both 'y' and 0x67 pings)
                    self.log(f"Discovery Ping from {addr}")
                    self.sock_send.sendto(b'y', addr)
                    self.log(f"Sent 'y' response to {addr}")
                    continue
                
                if data[0] == 0x75 and len(data) >= 10:
                    cmd_type = struct.unpack(">H", data[8:10])[0]
                    if cmd_type == 0x8877: # Data
                        self.root.after(0, self.flash_rx)
                        pkt_idx = struct.unpack(">H", data[10:12])[0]
                        chunk = data[14:-2]
                        base_offset = (pkt_idx - 1) * 984
                        for i in range(len(chunk)):
                            if base_offset + i < len(self.frame_buffer):
                                self.frame_buffer[base_offset + i] = chunk[i]
                    elif cmd_type == 0x5566: # End Frame
                        # self.log("End Frame Received")
                        self.root.after(0, self.refresh_from_buffer)
                    elif cmd_type == 0x3344: # Start Frame
                        self.log(f"Frame Start from {addr[0]}")
                        self.frame_buffer = bytearray(len(self.frame_buffer))
            except: pass

    def timeout_loop(self):
        while self.running:
            time.sleep(1.0)
            now = time.time()
            to_clear = []
            for pos, ts in self.pixel_timestamps.items():
                if ts != 0 and (now - ts) > PIXEL_TIMEOUT:
                    if self.grid_data[pos] != (0, 0, 0):
                        to_clear.append(pos)
            if to_clear:
                self.root.after(0, lambda: self.clear_pixels(to_clear))

    def clear_pixels(self, pixels):
        for pos in pixels:
            # self.log(f"Pixel Timeout: {pos}")
            self.update_pixel(pos[0], pos[1], 0, 0, 0, timestamp=0)

    def refresh_from_buffer(self):
        now = time.time()
        # Default to Swapped (GRB) as it matches Hardware/Matrix_GUI
        for led_pos in range(LEDS_PER_CHANNEL):
            for channel in range(NUM_CHANNELS):
                offset = led_pos * 24 + channel
                c1 = self.frame_buffer[offset]
                c2 = self.frame_buffer[offset + 8]
                c3 = self.frame_buffer[offset + 16]
                
                row = led_pos // 16
                x = (led_pos % 16) if row % 2 == 0 else (15 - (led_pos % 16))
                y = channel * 4 + row
                
                r, g, b = c2, c1, c3 # Swapped G, R, B
                
                if 0 <= x < BOARD_WIDTH and 0 <= y < BOARD_HEIGHT:
                    self.update_pixel(x, y, r, g, b, timestamp=now if (r or g or b) else 0)

if __name__ == "__main__":
    root = tk.Tk()
    sim = MatrixSimulator(root)
    root.mainloop()
    sim.running = False
