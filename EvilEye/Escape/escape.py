#!/usr/bin/env python3
"""
EvilEye Escape Room
===================
4 walls · 1 eye (LED 0) + 10 buttons (LED 1-10) per wall

Four stage types:
  stage_audio_riddle  – play a riddle audio, wait for one specific button press
  stage_morse         – flash the whole room as Morse code (. short / - long)
  stage_color_sync    – all 4 walls must press blue → yellow → red in sync
  stage_final_pattern – players enter the secret pattern they collected from hints

After each stage a visual hint is shown on the walls (the fragment of the
final pattern revealed so far).  Players must remember these hints – they
are NOT repeated.

To configure the game, scroll to run_escape_room() at the bottom.
No command-line arguments are used; everything is a named parameter.
"""

import os
import queue
import random
import socket
import threading
import time
import ctypes

# ──────────────────────────────────────────────────────────────────────────────
# Hardware constants
# ──────────────────────────────────────────────────────────────────────────────
NUM_CHANNELS     = 4
LEDS_PER_CHANNEL = 11        # 0 = Eye, 1-10 = Buttons
FRAME_DATA_LEN   = LEDS_PER_CHANNEL * NUM_CHANNELS * 3   # 132 bytes

_PASSWORD = [
    35,63,187,69,107,178,92,76,39,69,205,37,223,255,165,231,
    16,220,99,61,25,203,203,155,107,30,92,144,218,194,226,88,
    196,190,67,195,159,185,209,24,163,65,25,172,126,63,224,61,
    160,80,125,91,239,144,25,141,183,204,171,188,255,162,104,225,
    186,91,232,3,100,208,49,211,37,192,20,99,27,92,147,152,
    86,177,53,153,94,177,200,33,175,195,15,228,247,18,244,150,
    165,229,212,96,84,200,168,191,38,112,171,116,121,186,147,203,
    30,118,115,159,238,139,60,57,235,213,159,198,160,50,97,201,
    253,242,240,77,102,12,183,235,243,247,75,90,13,236,56,133,
    150,128,138,190,140,13,213,18,7,117,255,45,69,214,179,50,
    28,66,123,239,190,73,142,218,253,5,212,174,152,75,226,226,
    172,78,35,93,250,238,19,32,247,223,89,123,86,138,150,146,
    214,192,93,152,156,211,67,51,195,165,66,10,10,31,1,198,
    234,135,34,128,208,200,213,169,238,74,221,208,104,170,166,36,
    76,177,196,3,141,167,127,56,177,203,45,107,46,82,217,139,
    168,45,198,6,43,11,57,88,182,84,189,29,35,143,138,171,
]

# ──────────────────────────────────────────────────────────────────────────────
# Protocol helpers  (identical to fire.py / Controller.py)
# ──────────────────────────────────────────────────────────────────────────────

def _cksum(data):
    idx = sum(data) & 0xFF
    return _PASSWORD[idx] if idx < len(_PASSWORD) else 0

def _build_start(seq):
    p = bytearray([0x75, random.randint(0, 127), random.randint(0, 127),
                   0x00, 0x08, 0x02, 0x00, 0x00, 0x33, 0x44,
                   (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x00])
    p.append(_cksum(p))
    return bytes(p)

def _build_end(seq):
    p = bytearray([0x75, random.randint(0, 127), random.randint(0, 127),
                   0x00, 0x08, 0x02, 0x00, 0x00, 0x55, 0x66,
                   (seq >> 8) & 0xFF, seq & 0xFF, 0x00, 0x00])
    p.append(_cksum(p))
    return bytes(p)

def _build_fff0(seq):
    pay = bytearray()
    for _ in range(NUM_CHANNELS):
        pay += bytes([(LEDS_PER_CHANNEL >> 8) & 0xFF, LEDS_PER_CHANNEL & 0xFF])
    internal = bytes([0x02, 0x00, 0x00, 0x88, 0x77, 0xFF, 0xF0,
                      (len(pay) >> 8) & 0xFF, len(pay) & 0xFF]) + pay
    hdr = bytes([0x75, random.randint(0, 127), random.randint(0, 127),
                 (len(internal) >> 8) & 0xFF, len(internal) & 0xFF])
    p = bytearray(hdr + internal)
    p[10] = (seq >> 8) & 0xFF
    p[11] = seq & 0xFF
    p.append(_cksum(p))
    return bytes(p)

def _build_cmd(seq, data_id, msg_loc, payload):
    internal = bytes([0x02, 0x00, 0x00,
                      (data_id >> 8) & 0xFF, data_id & 0xFF,
                      (msg_loc >> 8) & 0xFF, msg_loc & 0xFF,
                      (len(payload) >> 8) & 0xFF, len(payload) & 0xFF]) + payload
    hdr = bytes([0x75, random.randint(0, 127), random.randint(0, 127),
                 (len(internal) >> 8) & 0xFF, len(internal) & 0xFF])
    p = bytearray(hdr + internal)
    p[10] = (seq >> 8) & 0xFF
    p[11] = seq & 0xFF
    p.append(_cksum(p))
    return bytes(p)

def _make_frame(led_states):
    """led_states: {(wall 1-4, led 0-10): (r, g, b)}"""
    frame = bytearray(FRAME_DATA_LEN)
    for (ch, led), (r, g, b) in led_states.items():
        ci = ch - 1
        if 0 <= ci < NUM_CHANNELS and 0 <= led < LEDS_PER_CHANNEL:
            frame[led * 12 + ci]       = g
            frame[led * 12 + 4 + ci]   = r
            frame[led * 12 + 8 + ci]   = b
    return bytes(frame)

# ──────────────────────────────────────────────────────────────────────────────
# Audio helpers  (Windows MCI – no extra packages needed)
# ──────────────────────────────────────────────────────────────────────────────
try:
    _winmm = ctypes.windll.winmm
except Exception:
    _winmm = None

_BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
_MCI_ALIAS = "escape_snd"

def _mci(cmd):
    if _winmm:
        buf = ctypes.create_unicode_buffer(512)
        _winmm.mciSendStringW(cmd, buf, 512, None)
        return buf.value.strip()
    return ""

def _stop_audio():
    try:
        _mci(f"stop {_MCI_ALIAS}")
        _mci(f"close {_MCI_ALIAS}")
    except Exception:
        pass

def play_audio_blocking(path):
    """Play an audio file and block until it finishes."""
    if not path or not os.path.exists(path):
        print(f"[audio] file not found: {path}")
        time.sleep(1.0)
        return
    if _winmm:
        try:
            _stop_audio()
            _mci(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}')
            _mci(f"play {_MCI_ALIAS} from 0")
            while _mci(f"status {_MCI_ALIAS} mode").lower() == "playing":
                time.sleep(0.05)
            _stop_audio()
            return
        except Exception as e:
            print(f"[audio] MCI error: {e}")
    time.sleep(2.0)

def play_audio_nonblocking(path):
    """Start audio playback without waiting for it to finish."""
    if not path or not os.path.exists(path):
        print(f"[audio] file not found: {path}")
        return
    if _winmm:
        try:
            _stop_audio()
            _mci(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}')
            _mci(f"play {_MCI_ALIAS} from 0")
        except Exception as e:
            print(f"[audio] MCI error: {e}")

# ──────────────────────────────────────────────────────────────────────────────
# EscapeRoom  –  hardware interface
# ──────────────────────────────────────────────────────────────────────────────

class EscapeRoom:
    """
    Manages UDP communication with the Evil Eye hardware.
    LED state is set via set_led / set_all / helpers, then flushed to the device.
    Button presses arrive via a callback registered with set_button_callback().
    The callback is called from a background thread – keep it non-blocking.
    """

    def __init__(self,
                 device_ip = "255.255.255.255",
                 send_port = 4626,
                 recv_port = 7800):
        self.device_ip = device_ip
        self.send_port = send_port
        self.recv_port = recv_port

        self._seq      = 0
        self._leds     = {}            # (wall, led) -> (r, g, b)
        self._lock     = threading.Lock()
        self._prev_btn = {}
        self._btn_cb   = None          # callable(wall, button) – set per stage

        self._ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ssock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._rsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._rsock.settimeout(0.1)
        try:
            self._rsock.bind(("0.0.0.0", self.recv_port))
            print(f"[escape] listening for buttons on :{self.recv_port}")
        except Exception as e:
            print(f"[escape] bind error: {e}")

        threading.Thread(target=self._recv_loop, daemon=True).start()

    # ── LED setters ───────────────────────────────────────────────────────────

    def set_led(self, wall, led, r, g, b):
        """Set one LED.  wall=1-4, led=0(eye) or 1-10(button)."""
        with self._lock:
            if r == g == b == 0:
                self._leds.pop((wall, led), None)
            else:
                self._leds[(wall, led)] = (r, g, b)

    def set_all(self, r, g, b):
        """Set every LED on every wall (eyes + buttons)."""
        with self._lock:
            self._leds.clear()
            if r or g or b:
                for ch in range(1, NUM_CHANNELS + 1):
                    for led in range(LEDS_PER_CHANNEL):
                        self._leds[(ch, led)] = (r, g, b)

    def set_all_eyes(self, r, g, b):
        """Set the eye (led 0) on all 4 walls."""
        with self._lock:
            for ch in range(1, NUM_CHANNELS + 1):
                key = (ch, 0)
                if r == g == b == 0:
                    self._leds.pop(key, None)
                else:
                    self._leds[key] = (r, g, b)

    def set_all_buttons(self, r, g, b):
        """Set all 10 buttons (led 1-10) on all 4 walls."""
        with self._lock:
            for ch in range(1, NUM_CHANNELS + 1):
                for led in range(1, LEDS_PER_CHANNEL):
                    key = (ch, led)
                    if r == g == b == 0:
                        self._leds.pop(key, None)
                    else:
                        self._leds[key] = (r, g, b)

    # ── Send ─────────────────────────────────────────────────────────────────

    def flush(self):
        """Transmit the current LED state to the device."""
        with self._lock:
            states = dict(self._leds)
        frame = _make_frame(states)
        self._seq = (self._seq + 1) & 0xFFFF
        seq = self._seq
        ep  = (self.device_ip, self.send_port)
        try:
            self._ssock.sendto(_build_start(seq), ep);  time.sleep(0.005)
            self._ssock.sendto(_build_fff0(seq),  ep);  time.sleep(0.005)
            self._ssock.sendto(_build_cmd(seq, 0x8877, 0x0000, frame), ep)
            time.sleep(0.005)
            self._ssock.sendto(_build_end(seq), ep)
        except Exception as e:
            print(f"[escape] send error: {e}")

    def all_off(self):
        self.set_all(0, 0, 0)
        self.flush()

    def flash_all(self, r, g, b,
                  on_seconds  = 0.35,
                  off_seconds = 0.15,
                  count       = 4):
        """Flash every LED on/off `count` times."""
        for _ in range(count):
            self.set_all(r, g, b);  self.flush();  time.sleep(on_seconds)
            self.all_off();                        time.sleep(off_seconds)

    # ── Button receive ────────────────────────────────────────────────────────

    def set_button_callback(self, fn):
        """
        Register fn(wall, button) to be called on every button-down event.
        Pass None to unregister.  Keep the callback non-blocking.
        """
        self._btn_cb = fn

    def _recv_loop(self):
        EXPECTED = 687
        while True:
            try:
                data, _ = self._rsock.recvfrom(1024)
            except socket.timeout:
                continue
            except Exception:
                break
            if len(data) != EXPECTED or data[0] != 0x88:
                continue
            if sum(data[:-1]) & 0xFF != data[-1]:
                continue
            for ch in range(1, 5):
                base = 2 + (ch - 1) * 171
                for idx in range(LEDS_PER_CHANNEL):
                    trig = (data[base + 1 + idx] == 0xCC)
                    key  = (ch, idx)
                    if trig and not self._prev_btn.get(key, False):
                        cb = self._btn_cb
                        if cb:
                            try:
                                cb(ch, idx)
                            except Exception:
                                pass
                    self._prev_btn[key] = trig

    # ── Hint reveal ───────────────────────────────────────────────────────────

    def reveal_hint(self, hint_steps, show_seconds = 5.0):
        """
        Flash the partial pattern hint on the walls so players can memorise it.
        hint_steps: list of {"wall": int, "button": int, "color": (r,g,b)}
        The hint is shown once for show_seconds, then the room goes dark.
        """
        print(f"\n[HINT] Revealing {len(hint_steps)} step(s):")
        for i, s in enumerate(hint_steps):
            print(f"  {i+1}. Wall {s['wall']}, Button {s['button']}, "
                  f"Color {s['color']}")
        self.all_off()
        for step in hint_steps:
            self.set_led(step["wall"], step["button"], *step["color"])
        self.flush()
        time.sleep(show_seconds)
        self.all_off()


# ──────────────────────────────────────────────────────────────────────────────
# Stage 1 – Audio Riddle
# ──────────────────────────────────────────────────────────────────────────────

def stage_audio_riddle(
    room,

    # ── Audio ───────────────────────────────────────────────────────────────
    audio_file      = "",        # path to the riddle MP3 / WAV

    # ── Correct answer ───────────────────────────────────────────────────────
    answer_wall     = 2,         # wall that must press  (1-4)
    answer_button   = 3,         # button that must press (0=eye, 1-10=button)

    # ── Idle lighting while waiting for the answer ────────────────────────────
    idle_eye_color  = (30, 0, 60),    # dim purple on all eyes
    idle_btn_color  = (15, 15, 15),   # very dim white on all buttons

    # ── Press feedback ────────────────────────────────────────────────────────
    correct_color   = (0, 220, 0),    # full-room flash on correct answer
    wrong_color     = (180, 0, 0),    # full-room flash on wrong answer
    allow_retries   = True,           # if False the first press ends the stage

    # ── Hint fragment revealed after solving ──────────────────────────────────
    hint_steps      = [],        # list of {"wall":, "button":, "color":}
    hint_duration   = 5.0,       # seconds the hint is displayed
):
    """
    Play a riddle audio file, then wait for players to press the correct
    button on the correct wall.  Wrong presses flash red and reset.
    """
    print(f"\n{'='*60}")
    print(f"[STAGE] Audio Riddle  →  Wall {answer_wall}, Button {answer_button}")
    print(f"{'='*60}")

    press_q = queue.Queue()

    def _set_idle():
        room.all_off()
        room.set_all_eyes(*idle_eye_color)
        room.set_all_buttons(*idle_btn_color)
        room.flush()

    _set_idle()

    if audio_file:
        play_audio_blocking(audio_file)
    else:
        print("[stage] No audio_file set – skipping audio.")
        time.sleep(1.0)

    room.set_button_callback(lambda w, b: press_q.put((w, b)))
    print("[stage] Waiting for correct button press…")

    while True:
        try:
            wall, button = press_q.get(timeout=0.3)
        except queue.Empty:
            continue

        if wall == answer_wall and button == answer_button:
            room.set_button_callback(None)
            print(f"[stage] Correct!  Wall {wall}, Button {button}")
            room.flash_all(*correct_color, on_seconds=0.4, off_seconds=0.1, count=4)
            break

        if not allow_retries:
            room.set_button_callback(None)
            print(f"[stage] Wrong press and no retries.  Wall {wall}, Button {button}")
            room.flash_all(*wrong_color, on_seconds=0.4, off_seconds=0.1, count=3)
            break

        print(f"[stage] Wrong press: Wall {wall}, Button {button}")
        room.set_all(*wrong_color);  room.flush();  time.sleep(0.35)
        _set_idle()

    if hint_steps:
        room.reveal_hint(hint_steps, show_seconds=hint_duration)
    room.all_off()


# ──────────────────────────────────────────────────────────────────────────────
# Stage 2 – Morse Code
# ──────────────────────────────────────────────────────────────────────────────

_MORSE_TABLE = {
    'A': '.-',   'B': '-...', 'C': '-.-.', 'D': '-..',  'E': '.',
    'F': '..-.', 'G': '--.',  'H': '....', 'I': '..',   'J': '.---',
    'K': '-.-',  'L': '.-..', 'M': '--',   'N': '-.',   'O': '---',
    'P': '.--.', 'Q': '--.-', 'R': '.-.',  'S': '...',  'T': '-',
    'U': '..-',  'V': '...-', 'W': '.--',  'X': '-..-', 'Y': '-.--',
    'Z': '--..',
    '0': '-----', '1': '.----', '2': '..---', '3': '...--', '4': '....-',
    '5': '.....', '6': '-....', '7': '--...', '8': '---..', '9': '----.',
}


def stage_morse(
    room,

    # ── Text to transmit ─────────────────────────────────────────────────────
    text             = "SOS",    # plain text; spaces = word gaps

    # ── Symbol durations (seconds) ────────────────────────────────────────────
    dot_duration     = 0.30,     # how long the room lights up for a dot (.)
    dash_duration    = 0.90,     # how long the room lights up for a dash (-)
    symbol_gap       = 0.30,     # dark pause between symbols inside one letter
    letter_gap       = 0.90,     # dark pause between letters in the same word
    word_gap         = 1.80,     # dark pause between words

    # ── Colors ────────────────────────────────────────────────────────────────
    dot_color        = (255, 255, 255),   # white  for dots
    dash_color       = (255, 180,   0),   # amber  for dashes

    # ── What gets lit during each flash ───────────────────────────────────────
    light_eyes       = True,     # include the eye LEDs in the flash
    light_buttons    = True,     # include the 10 button LEDs in the flash

    # ── Repetitions ──────────────────────────────────────────────────────────
    repeat_count     = 3,        # how many times the full message is sent
    repeat_gap       = 3.0,      # seconds of darkness between repetitions

    # ── Hint fragment revealed after the stage ────────────────────────────────
    hint_steps       = [],
    hint_duration    = 5.0,
):
    """
    Flash the entire room as Morse code.  All 4 walls flash simultaneously.
    Dot  = short bright flash.
    Dash = longer bright flash (different colour).
    Gaps between symbols, letters and words produce darkness.
    """
    text_upper = text.upper().strip()
    print(f"\n{'='*60}")
    print(f"[STAGE] Morse Code  →  '{text_upper}'  (×{repeat_count})")
    print(f"{'='*60}")

    def _flash(color, duration):
        if light_buttons:
            room.set_all_buttons(*color)
        if light_eyes:
            room.set_all_eyes(*color)
        room.flush()
        time.sleep(duration)
        room.all_off()

    def _send_once():
        words = text_upper.split()
        for wi, word in enumerate(words):
            letters = [ch for ch in word if ch in _MORSE_TABLE]
            for li, char in enumerate(letters):
                symbols = _MORSE_TABLE[char]
                for si, sym in enumerate(symbols):
                    if sym == '.':
                        print('.', end='', flush=True)
                        _flash(dot_color, dot_duration)
                    else:
                        print('-', end='', flush=True)
                        _flash(dash_color, dash_duration)
                    if si < len(symbols) - 1:
                        time.sleep(symbol_gap)
                if li < len(letters) - 1:
                    print(' ', end='', flush=True)
                    time.sleep(letter_gap)
            if wi < len(words) - 1:
                print(' / ', end='', flush=True)
                time.sleep(word_gap)
        print()

    room.all_off()
    for rep in range(repeat_count):
        print(f"[morse] Repetition {rep + 1}/{repeat_count}:  ", end='')
        _send_once()
        if rep < repeat_count - 1:
            time.sleep(repeat_gap)

    room.all_off()

    if hint_steps:
        room.reveal_hint(hint_steps, show_seconds=hint_duration)
    room.all_off()


# ──────────────────────────────────────────────────────────────────────────────
# Stage 3 – Color Sync
# ──────────────────────────────────────────────────────────────────────────────

def stage_color_sync(
    room,

    # ── Audio hint ───────────────────────────────────────────────────────────
    audio_file           = "",    # riddle explaining the color order

    # ── Color sequence players must press ─────────────────────────────────────
    color_order          = ["blue", "yellow", "red"],

    # ── RGB values for each color name ────────────────────────────────────────
    color_rgb            = {
        "blue":   (0,   80, 255),
        "yellow": (255, 200,   0),
        "red":    (220,   0,   0),
    },

    # ── Which button numbers (1-10) show each color on every wall ─────────────
    # Change the lists to rearrange which buttons are which color.
    button_layout        = {
        "blue":   [1, 2, 3],       # buttons 1-3  on every wall = blue
        "yellow": [4, 5, 6],       # buttons 4-6               = yellow
        "red":    [7, 8, 9, 10],   # buttons 7-10              = red
    },

    # ── Synchronisation tolerance ─────────────────────────────────────────────
    # All 4 walls must press the current colour within this many seconds of
    # each other.  If a wall is too early its press is discarded (stale).
    sync_window          = 3.0,

    # ── Feedback ─────────────────────────────────────────────────────────────
    phase_correct_color  = (0, 220, 100),   # brief flash when a phase is cleared
    wrong_press_color    = (200, 0, 0),     # brief flash on wrong-colour press

    # ── Hint fragment revealed after all phases ────────────────────────────────
    hint_steps           = [],
    hint_duration        = 5.0,
):
    """
    Buttons on every wall show a mix of blue / yellow / red.
    Players must press the correct colour in order (blue → yellow → red):
      • All 4 walls press a blue button (within sync_window of each other)
      • All 4 walls press a yellow button
      • All 4 walls press a red button
    A wrong-colour press resets the current phase.
    """
    print(f"\n{'='*60}")
    print(f"[STAGE] Color Sync  →  {' → '.join(c.upper() for c in color_order)}")
    print(f"{'='*60}")

    # Map button index → color name  (same mapping on every wall)
    btn_to_color = {}
    for color_name, buttons in button_layout.items():
        for b in buttons:
            btn_to_color[b] = color_name

    def _show_colors():
        """Paint every wall with the mixed colour layout."""
        room.all_off()
        for ch in range(1, NUM_CHANNELS + 1):
            for color_name, buttons in button_layout.items():
                r, g, b = color_rgb[color_name]
                for btn in buttons:
                    room.set_led(ch, btn, r, g, b)
        room.flush()

    if audio_file:
        _show_colors()
        play_audio_blocking(audio_file)
    else:
        time.sleep(0.5)

    _show_colors()

    # ── Run each colour phase ─────────────────────────────────────────────────
    for phase_idx, target_color in enumerate(color_order):
        print(f"\n[sync] Phase {phase_idx + 1}/{len(color_order)}"
              f"  →  press {target_color.upper()}")

        press_q     = queue.Queue()
        phase_presses = {}   # wall -> timestamp of valid press

        room.set_button_callback(lambda w, b: press_q.put((w, b, time.time())))
        phase_done = False

        while not phase_done:
            try:
                wall, button, ts = press_q.get(timeout=0.3)
            except queue.Empty:
                continue

            if button == 0:
                continue   # ignore eye presses in this stage

            pressed_color = btn_to_color.get(button)

            if pressed_color != target_color:
                print(f"  [sync] Wall {wall} pressed wrong color"
                      f" ({pressed_color}) – resetting phase")
                phase_presses.clear()
                room.set_all(*wrong_press_color);  room.flush()
                time.sleep(0.25)
                _show_colors()
                continue

            # Correct colour – record and check sync window
            phase_presses[wall] = ts
            cutoff = ts - sync_window
            stale  = [w for w, t in phase_presses.items() if t < cutoff]
            for w in stale:
                del phase_presses[w]

            print(f"  [sync] Wall {wall} pressed {target_color.upper()}"
                  f"  ({len(phase_presses)}/{NUM_CHANNELS} walls)")

            if len(phase_presses) == NUM_CHANNELS:
                phase_done = True

        room.set_button_callback(None)
        print(f"  [sync] Phase {phase_idx + 1} cleared!")
        room.flash_all(*phase_correct_color, on_seconds=0.3, off_seconds=0.1, count=3)
        time.sleep(0.4)
        _show_colors()

    print("\n[sync] All color phases complete!")
    room.flash_all(0, 220, 100, on_seconds=0.5, off_seconds=0.15, count=5)

    if hint_steps:
        room.reveal_hint(hint_steps, show_seconds=hint_duration)
    room.all_off()


# ──────────────────────────────────────────────────────────────────────────────
# Stage 4 – Final Pattern
# ──────────────────────────────────────────────────────────────────────────────

def stage_final_pattern(
    room,

    # ── The secret pattern ────────────────────────────────────────────────────
    # Each entry is one step.  Players press them in this exact order.
    # "color" is shown on that LED as an indicator when the step is active
    # (optional visual help – remove the color or set it to (0,0,0) to hide).
    pattern          = [
        {"wall": 1, "button": 0, "color": (255,   0,   0)},   # wall 1 eye  → red
        {"wall": 3, "button": 7, "color": (255, 200,   0)},   # wall 3 btn7 → yellow
        {"wall": 2, "button": 5, "color": (  0,  80, 255)},   # wall 2 btn5 → blue
    ],

    # ── Idle room state ────────────────────────────────────────────────────────
    idle_eye_color   = (40, 0, 60),    # dim purple eyes between presses
    idle_btn_color   = (12, 12, 12),   # very dim buttons

    # ── Step indicator ────────────────────────────────────────────────────────
    # While waiting for step N, the expected button glows with its pattern color.
    show_next_hint   = True,           # set False to require players to remember

    # ── Press feedback ────────────────────────────────────────────────────────
    correct_color    = (0, 230, 80),   # flash on the correct LED
    wrong_color      = (200, 0, 0),    # full-room flash on wrong press
    step_hold_time   = 0.6,            # seconds to show the correct-step glow
    wrong_hold_time  = 0.8,            # seconds to show the wrong-press flash

    # ── Timeout ───────────────────────────────────────────────────────────────
    timeout_seconds  = 120,
):
    """
    Players enter the final pattern in sequence from memory (using the hints
    they collected during the earlier stages).
    Correct press → brief green glow on that LED, advance to next step.
    Wrong press   → red full-room flash, reset to step 0.
    All steps done → victory celebration.
    """
    print(f"\n{'='*60}")
    print(f"[STAGE] Final Pattern  ({len(pattern)} steps, timeout {timeout_seconds}s)")
    for i, s in enumerate(pattern):
        print(f"  Step {i + 1}: Wall {s['wall']}, Button {s['button']}"
              f", Color {s['color']}")
    print(f"{'='*60}")

    press_q   = queue.Queue()
    step_ref  = [0]          # current expected step index (mutable list trick)
    solved_ev = threading.Event()

    def _set_idle():
        room.all_off()
        room.set_all_eyes(*idle_eye_color)
        room.set_all_buttons(*idle_btn_color)
        if show_next_hint and step_ref[0] < len(pattern):
            nxt = pattern[step_ref[0]]
            room.set_led(nxt["wall"], nxt["button"], *nxt["color"])
        room.flush()

    _set_idle()

    room.set_button_callback(lambda w, b: press_q.put((w, b)))
    print("[pattern] Waiting for the sequence…")

    deadline = time.time() + timeout_seconds
    while not solved_ev.is_set():
        remaining = deadline - time.time()
        if remaining <= 0:
            break
        try:
            wall, button = press_q.get(timeout=min(0.3, remaining))
        except queue.Empty:
            continue

        step     = step_ref[0]
        expected = pattern[step]

        if wall == expected["wall"] and button == expected["button"]:
            print(f"  [pattern] Step {step + 1}/{len(pattern)} correct ✓")
            room.set_led(wall, button, *correct_color)
            room.flush()
            time.sleep(step_hold_time)

            step_ref[0] += 1
            if step_ref[0] == len(pattern):
                solved_ev.set()
            else:
                _set_idle()
        else:
            print(f"  [pattern] Wrong!  Got Wall {wall} Btn {button},"
                  f" expected Wall {expected['wall']} Btn {expected['button']}")
            room.set_all(*wrong_color);  room.flush()
            time.sleep(wrong_hold_time)
            step_ref[0] = 0
            _set_idle()

    room.set_button_callback(None)

    if solved_ev.is_set():
        print("\n★  ESCAPE ROOM SOLVED!  ★")
        _victory_celebration(room)
    else:
        print("\n[pattern] Timeout – game over.")
        room.flash_all(200, 0, 0, on_seconds=0.5, off_seconds=0.2, count=4)
        room.all_off()


def _victory_celebration(room):
    """Rainbow sweep + sustained white pulse."""
    rainbow = [
        (255, 0,   0),
        (255, 120, 0),
        (255, 220, 0),
        (0,   200, 0),
        (0,   80, 255),
        (140, 0,  220),
        (255, 255, 255),
    ]
    for color in rainbow:
        room.set_all(*color);  room.flush();  time.sleep(0.2)
    for _ in range(8):
        room.set_all(255, 255, 255);  room.flush();  time.sleep(0.35)
        room.all_off();                               time.sleep(0.15)
    room.all_off()


# ──────────────────────────────────────────────────────────────────────────────
# Main – edit everything here to configure your escape room
# ──────────────────────────────────────────────────────────────────────────────

def run_escape_room():

    room = EscapeRoom(
        device_ip = "255.255.255.255",   # broadcast; or set the device's IP
        send_port = 4626,
        recv_port = 7800,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # STAGE 1 – Audio riddle
    #
    # Example riddle (record this as riddle1.mp3):
    #   "The eye sees all, but watches from one wall only.
    #    Find the wall where the shadows meet.
    #    Press the fourth button on the second wall."
    # ═══════════════════════════════════════════════════════════════════════════
    stage_audio_riddle(
        room           = room,
        audio_file     = os.path.join(_BASE_DIR, "sounds", "riddle1.mp3"),

        answer_wall    = 2,    # ← CHANGE: which wall must answer (1-4)
        answer_button  = 4,    # ← CHANGE: which button (0=eye, 1-10)

        idle_eye_color = (30, 0, 60),
        idle_btn_color = (15, 15, 15),
        correct_color  = (0, 220, 0),
        wrong_color    = (180, 0, 0),
        allow_retries  = True,

        hint_steps = [
            # First fragment of the final pattern revealed after this stage:
            {"wall": 1, "button": 0, "color": (255, 0, 0)},   # wall 1 eye = RED
        ],
        hint_duration = 5.0,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # STAGE 2 – Morse code
    #
    # The room flashes the Morse for "SOS".  The message can encode a clue
    # (e.g. "B5" → button 5, or any word the players need to decode).
    # ═══════════════════════════════════════════════════════════════════════════
    stage_morse(
        room           = room,
        text           = "SOS",   # ← CHANGE: text to transmit

        dot_duration   = 0.30,
        dash_duration  = 0.90,
        symbol_gap     = 0.30,
        letter_gap     = 0.90,
        word_gap       = 1.80,

        dot_color      = (255, 255, 255),   # white for dot
        dash_color     = (255, 180,   0),   # amber for dash

        light_eyes     = True,
        light_buttons  = True,

        repeat_count   = 3,
        repeat_gap     = 3.0,

        hint_steps = [
            # Both fragments revealed so far:
            {"wall": 1, "button": 0, "color": (255,   0,   0)},  # wall 1 eye  = red  (repeat)
            {"wall": 3, "button": 7, "color": (255, 200,   0)},  # wall 3 btn7 = yellow (NEW)
        ],
        hint_duration = 5.0,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # STAGE 3 – Color sync
    #
    # Example riddle audio (record as color_sync.mp3):
    #   "Divided you are nothing.  United you shall pass.
    #    Sky first, then sand, then fire.
    #    Together – press your colors in order."
    # ═══════════════════════════════════════════════════════════════════════════
    stage_color_sync(
        room                = room,
        audio_file          = os.path.join(_BASE_DIR, "sounds", "color_sync.mp3"),

        color_order         = ["blue", "yellow", "red"],   # ← CHANGE order if needed

        color_rgb           = {
            "blue":   (  0,  80, 255),
            "yellow": (255, 200,   0),
            "red":    (220,   0,   0),
        },

        button_layout       = {
            "blue":   [1, 2, 3],      # ← CHANGE: which button numbers = blue
            "yellow": [4, 5, 6],      # ← CHANGE: which button numbers = yellow
            "red":    [7, 8, 9, 10],  # ← CHANGE: which button numbers = red
        },

        sync_window         = 3.0,    # ← CHANGE: seconds tolerance for "simultaneous"

        phase_correct_color = (0, 220, 100),
        wrong_press_color   = (200, 0, 0),

        hint_steps = [
            # All three fragments revealed:
            {"wall": 1, "button": 0, "color": (255,   0,   0)},  # red    (repeat)
            {"wall": 3, "button": 7, "color": (255, 200,   0)},  # yellow (repeat)
            {"wall": 2, "button": 5, "color": (  0,  80, 255)},  # blue   (NEW)
        ],
        hint_duration = 5.0,
    )

    # ═══════════════════════════════════════════════════════════════════════════
    # FINAL – Pattern validation
    #
    # Players enter the three steps they memorised from the hints above.
    # ═══════════════════════════════════════════════════════════════════════════
    stage_final_pattern(
        room             = room,

        # ← CHANGE: must match exactly what was shown in the hints above
        pattern = [
            {"wall": 1, "button": 0, "color": (255,   0,   0)},  # wall 1 eye  → red
            {"wall": 3, "button": 7, "color": (255, 200,   0)},  # wall 3 btn7 → yellow
            {"wall": 2, "button": 5, "color": (  0,  80, 255)},  # wall 2 btn5 → blue
        ],

        idle_eye_color  = (40, 0, 60),
        idle_btn_color  = (12, 12, 12),
        show_next_hint  = True,   # set False to hide the next-step indicator

        correct_color   = (0, 230, 80),
        wrong_color     = (200, 0, 0),
        step_hold_time  = 0.6,
        wrong_hold_time = 0.8,
        timeout_seconds = 120,
    )


if __name__ == "__main__":
    run_escape_room()
