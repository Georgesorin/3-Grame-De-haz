#!/usr/bin/env python3

import json
import os, socket, sys, threading, time, random, queue, math, wave, ctypes
import tkinter as tk
from tkinter import scrolledtext
from datetime import datetime

# ─────────────────────────────────────────────────────────────────────────────
# Protocol
# ─────────────────────────────────────────────────────────────────────────────
NUM_CHANNELS      = 4
LEDS_PER_CHANNEL  = 11
FRAME_DATA_LEN    = LEDS_PER_CHANNEL * NUM_CHANNELS * 3
_DEFAULT_SEND_PORT = 4626
_DEFAULT_RECV_PORT = 7800

_EYE_CFG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "eye_ctrl_config.json")
)


def _load_eye_ctrl_config():
    """Load EvilEye/eye_ctrl_config.json (same file as Controller / Color Rush)."""
    defaults = {
        "device_ip": "",
        "udp_port": _DEFAULT_SEND_PORT,
        "receiver_port": _DEFAULT_RECV_PORT,
    }
    try:
        with open(_EYE_CFG_PATH, encoding="utf-8") as f:
            user = json.load(f)
        if isinstance(user, dict):
            defaults.update(user)
    except Exception:
        pass
    return defaults


def _receiver_bind_ip_from_cfg(cfg):
    """Same rules as Controller.receiver_bind_ip_from_config (no Controller import)."""
    if "receiver_bind_ip" in cfg:
        r = (cfg.get("receiver_bind_ip") or "").strip()
        if r:
            return r
    v = (cfg.get("virtual_iface_ip") or "").strip()
    if v:
        return v
    return "0.0.0.0"


def _fire_network_from_cfg(cfg):
    """device_ip, send_port, recv_port, recv_bind_ip for FireGame."""
    ip = (cfg.get("device_ip") or "").strip() or "255.255.255.255"
    try:
        udp = int(cfg.get("udp_port", _DEFAULT_SEND_PORT))
    except (TypeError, ValueError):
        udp = _DEFAULT_SEND_PORT
    try:
        recv = int(cfg.get("receiver_port", _DEFAULT_RECV_PORT))
    except (TypeError, ValueError):
        recv = _DEFAULT_RECV_PORT
    bind = _receiver_bind_ip_from_cfg(cfg)
    return ip, udp, recv, bind

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

def _cksum(data):
    idx = sum(data) & 0xFF
    return _PASSWORD[idx] if idx < len(_PASSWORD) else 0

def _build_start(seq):
    p = bytearray([0x75,random.randint(0,127),random.randint(0,127),
                   0x00,0x08,0x02,0x00,0x00,0x33,0x44,
                   (seq>>8)&0xFF,seq&0xFF,0x00,0x00])
    p.append(_cksum(p)); return bytes(p)

def _build_end(seq):
    p = bytearray([0x75,random.randint(0,127),random.randint(0,127),
                   0x00,0x08,0x02,0x00,0x00,0x55,0x66,
                   (seq>>8)&0xFF,seq&0xFF,0x00,0x00])
    p.append(_cksum(p)); return bytes(p)

def _build_fff0(seq):
    pay = bytearray()
    for _ in range(NUM_CHANNELS):
        pay += bytes([(LEDS_PER_CHANNEL>>8)&0xFF,LEDS_PER_CHANNEL&0xFF])
    internal = bytes([0x02,0x00,0x00,0x88,0x77,0xFF,0xF0,
                      (len(pay)>>8)&0xFF,len(pay)&0xFF]) + pay
    hdr = bytes([0x75,random.randint(0,127),random.randint(0,127),
                 (len(internal)>>8)&0xFF,len(internal)&0xFF])
    p = bytearray(hdr + internal)
    p[10]=(seq>>8)&0xFF; p[11]=seq&0xFF
    p.append(_cksum(p)); return bytes(p)

def _build_cmd(seq, data_id, msg_loc, payload):
    internal = bytes([0x02,0x00,0x00,
                      (data_id>>8)&0xFF,data_id&0xFF,
                      (msg_loc>>8)&0xFF,msg_loc&0xFF,
                      (len(payload)>>8)&0xFF,len(payload)&0xFF]) + payload
    hdr = bytes([0x75,random.randint(0,127),random.randint(0,127),
                 (len(internal)>>8)&0xFF,len(internal)&0xFF])
    p = bytearray(hdr + internal)
    p[10]=(seq>>8)&0xFF; p[11]=seq&0xFF
    p.append(_cksum(p)); return bytes(p)

def _logical_rgb_to_wire_grb(r, g, b):
    """Same mapping as Controller.logical_rgb_to_wire_grb — logical RGB → GRB wire bytes."""
    return (g & 0xFF, r & 0xFF, b & 0xFF)


def _make_frame(led_states):
    """132-byte Evil Eye frame: logical (r,g,b) per LED → GRB on the wire (Evil_Eye_Wiki §2)."""
    frame = bytearray(FRAME_DATA_LEN)
    for (ch,led),(r,g,b) in led_states.items():
        ci = ch - 1
        if 0 <= ci < NUM_CHANNELS and 0 <= led < LEDS_PER_CHANNEL:
            w0, w1, w2 = _logical_rgb_to_wire_grb(r, g, b)
            frame[led*12+ci]   = w0
            frame[led*12+4+ci] = w1
            frame[led*12+8+ci] = w2
    return bytes(frame)

# ─────────────────────────────────────────────────────────────────────────────
# Sound configuration  ← edit these to tune behaviour
# ─────────────────────────────────────────────────────────────────────────────
_BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
_SOUNDS_DIR = os.path.join(_BASE_DIR, "sounds")
_RULES_MP3  = os.path.join(_SOUNDS_DIR, "rules.mp3")
_BOOM       = os.path.join(_BASE_DIR, "_boom.wav")
_FAIL       = os.path.join(_BASE_DIR, "_fail.wav")

# Timing (seconds)
LIGHT_START_DELAY = 1.0   # after sound starts  → white buttons turn ON
LIGHT_END_DELAY   = 1.0   # after sound ends    → white buttons turn OFF
ROUND_PAUSE       = 2.0   # pause after lights off before next sound starts
PRE_GAME_PAUSE    = 2.0   # pause after GO sound before first round
PRE_SOUND_DELAY   = 2.0   # silence before each game sound (builds tension)

# Folder weights – higher number = picked more often
# 'fire' → is_fire=True (correct press = point); all others → is_fire=False (pressing = fail)
FOLDER_WEIGHTS = {
    'fire':       2,
    'very_close': 5,
    'funny':      2,
    'random':     1,
}
MAX_NO_FIRE_STREAK = 5    # force 'fire' folder if not picked in this many consecutive plays

# ─────────────────────────────────────────────────────────────────────────────
# Windows MCI audio + sound file scanning
# ─────────────────────────────────────────────────────────────────────────────
try:
    _winmm = ctypes.windll.winmm
except Exception:
    _winmm = None

_MCI_ALIAS = "firegame_snd"

def _mci(cmd):
    if _winmm:
        buf = ctypes.create_unicode_buffer(512)
        _winmm.mciSendStringW(cmd, buf, 512, None)
        return buf.value.strip()
    return ""

def _scan_sounds():
    result = {}
    if not os.path.isdir(_SOUNDS_DIR):
        return result
    for folder in list(FOLDER_WEIGHTS.keys()) + ['ready']:
        fpath = os.path.join(_SOUNDS_DIR, folder)
        if os.path.isdir(fpath):
            files = sorted([
                os.path.join(fpath, f) for f in os.listdir(fpath)
                if f.lower().endswith(('.mp3', '.wav', '.ogg'))
            ])
            if files:
                result[folder] = files
    return result

_SOUND_FILES = _scan_sounds()
print(f"[sounds] loaded: { {k: len(v) for k, v in _SOUND_FILES.items()} }")

# ─────────────────────────────────────────────────────────────────────────────
# Sound effects  (generated at startup, cached as WAV files)
# ─────────────────────────────────────────────────────────────────────────────

def _save_wav(path, data, rate=44100):
    with wave.open(path, 'w') as f:
        f.setnchannels(1); f.setsampwidth(1)
        f.setframerate(rate); f.writeframes(bytes(data))

def _gen_boom():
    rate, n = 44100, int(44100 * 1.0)
    out = bytearray()
    for i in range(n):
        t = i / rate
        d = math.exp(-4.0 * t)
        v = d * (0.55*math.sin(2*math.pi*55*t) +
                 0.30*math.sin(2*math.pi*110*t) +
                 0.10*math.sin(2*math.pi*28*t*(1+0.4*t)))
        # Sharp transient crack at start
        if t < 0.025:
            v += (1 - t/0.025) * 0.45 * (random.random()*2 - 1)
        out.append(max(0, min(255, int((v*0.75+1)*127.5))))
    return out

def _gen_fail():
    # Classic descending "wa-wa-wa-waaaa"
    rate = 44100
    notes = [(523,0.20),(415,0.20),(330,0.20),(220,0.65)]
    out = bytearray()
    for freq, dur in notes:
        n = int(rate * dur)
        for i in range(n):
            t = i / rate
            rel = t / dur
            fade = 1.0 if rel < 0.55 else (1-(rel-0.55)/0.45)**0.6
            v = fade * 0.55 * (
                math.sin(2*math.pi*freq*t) +
                0.35*math.sin(4*math.pi*freq*t) +
                0.10*math.sin(6*math.pi*freq*t)
            )
            # Trombone wah modulation
            v *= 1 + 0.35*math.sin(2*math.pi*7*t)
            out.append(max(0, min(255, int((v*0.60+1)*127.5))))
    return out

def _init_sounds():
    try:
        if not os.path.exists(_BOOM): _save_wav(_BOOM, _gen_boom())
        if not os.path.exists(_FAIL): _save_wav(_FAIL, _gen_fail())
    except Exception as e:
        print(f"[SFX] generation error: {e}")

def _play(path):
    def _t():
        try:
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        except Exception:
            pass
    threading.Thread(target=_t, daemon=True).start()

_init_sounds()

# ─────────────────────────────────────────────────────────────────────────────
# MP3 / audio playback helpers  (Windows MCI – no extra packages needed)
# ─────────────────────────────────────────────────────────────────────────────
def _stop_mp3():
    """Stop and close the main audio channel immediately."""
    if _winmm:
        try:
            _mci(f'stop {_MCI_ALIAS}')
            _mci(f'close {_MCI_ALIAS}')
        except Exception:
            pass

def _play_mp3_blocking(path):
    """Play audio file and block until it finishes."""
    if _winmm:
        try:
            _stop_mp3()
            _mci(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}')
            _mci(f'play {_MCI_ALIAS} from 0')
            while _mci(f'status {_MCI_ALIAS} mode').lower() == 'playing':
                time.sleep(0.05)
            _stop_mp3()
            return
        except Exception as e:
            print(f"[sound] MCI blocking error: {e}")
    time.sleep(2.5)

def _play_mp3_start(path):
    """Start playing audio non-blocking. Returns (start_time, estimated_duration)."""
    dur = 2.5
    if _winmm:
        try:
            _stop_mp3()
            _mci(f'open "{path}" type mpegvideo alias {_MCI_ALIAS}')
            _mci(f'set {_MCI_ALIAS} time format milliseconds')
            ms = _mci(f'status {_MCI_ALIAS} length')
            if ms:
                dur = int(ms) / 1000.0
            _mci(f'play {_MCI_ALIAS} from 0')
        except Exception as e:
            print(f"[sound] MCI start error: {e}")
    return time.time(), dur

def _mp3_still_playing():
    """True if main audio is currently playing."""
    if _winmm:
        try:
            return _mci(f'status {_MCI_ALIAS} mode').lower() == 'playing'
        except Exception:
            pass
    return False

# ─────────────────────────────────────────────────────────────────────────────
# TTS engine  (single thread, varied voices per word)
# ─────────────────────────────────────────────────────────────────────────────
class _TTS:
    def __init__(self, base_rate=165):
        self._q         = queue.Queue()
        self._base_rate = base_rate
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()

    def _speak_ps(self, word):
        import subprocess
        safe = word.replace('"', '')
        subprocess.run(
            ['powershell', '-Command',
             f'Add-Type -AssemblyName System.Speech; '
             f'$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; '
             f'$s.Rate=2; $s.Speak("{safe}")'],
            timeout=10, capture_output=True
        )

    def _run(self):
        engine, voices = None, []
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.setProperty('rate', self._base_rate)
            vlist  = engine.getProperty('voices')
            voices = [v.id for v in vlist] if vlist else []
        except Exception:
            engine = None

        while True:
            item = self._q.get()
            if item is None:
                break
            word, ev, vary = item
            try:
                if engine:
                    if vary and voices:
                        # Randomise voice AND pace for maximum surprise
                        engine.setProperty('voice', random.choice(voices))
                        engine.setProperty('rate', random.randint(125, 215))
                    else:
                        if voices:
                            engine.setProperty('voice', voices[0])
                        engine.setProperty('rate', self._base_rate)
                    engine.say(word)
                    engine.runAndWait()
                else:
                    self._speak_ps(word)
            except Exception:
                try:    self._speak_ps(word)
                except Exception: pass
            if ev:
                ev.set()

    def speak(self, word, block=True, vary=False):
        ev = threading.Event() if block else None
        self._q.put((word, ev, vary))
        if block and ev:
            ev.wait(timeout=12)

    def stop(self):
        self._q.put(None)

_EYE = 0

_PCOL     = {1:(255,80,0), 2:(0,120,255), 3:(200,0,200), 4:(0,200,80)}
_PCOL_HEX = {k:"#%02x%02x%02x"%v for k,v in _PCOL.items()}

def _is_junk_sound_filename(word):
    """True for auto-generated / download-site clip names we should not show in UI or log."""
    if not word:
        return False
    w = word.lower()
    return "ttsmp3.com" in w or "voicetext_" in w


def _word_for_display(word):
    if _is_junk_sound_filename(word):
        return "· listen ·"
    return word


def _word_for_log(word):
    if _is_junk_sound_filename(word):
        return "audio cue"
    return word

# ─────────────────────────────────────────────────────────────────────────────
# Game
# ─────────────────────────────────────────────────────────────────────────────
class FireGame:
    def __init__(self, device_ip="255.255.255.255",
                 send_port=_DEFAULT_SEND_PORT,
                 recv_port=_DEFAULT_RECV_PORT,
                 recv_bind_ip="0.0.0.0",
                 on_event=None):
        self.device_ip      = device_ip
        self.send_port      = send_port
        self.recv_port      = recv_port
        self.recv_bind_ip   = recv_bind_ip
        self.on_event       = on_event

        self._seq           = 0
        self._led           = {}
        self._led_lock      = threading.Lock()
        self._running       = False
        self._prev_btn      = {}

        self.scores         = {p: 0 for p in range(1, 5)}
        self.round_num      = 0
        self.total_rounds   = 10
        self.active_players = [1, 2, 3, 4]

        self._react_open    = False
        self._fire_color    = None
        self._cur_lit       = {}
        self._react_ev      = threading.Event()
        self._react_winner  = None
        self._no_fire_streak = 0

        self._tts = _TTS()

        self._ssock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._ssock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        self._rsock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._rsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._rsock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self._rsock.settimeout(0.2)
        bind_host = (recv_bind_ip or "0.0.0.0").strip() or "0.0.0.0"
        try:
            self._rsock.bind((bind_host, self.recv_port))
        except Exception as e:
            self._emit("log", msg=f"Recv bind error {bind_host}:{self.recv_port} – {e}")

        threading.Thread(target=self._recv_loop, daemon=True).start()

    # ── LED helpers ───────────────────────────────────────────────────────────
    def _set(self, ch, led, r, g, b):
        with self._led_lock:
            if r == g == b == 0:
                self._led.pop((ch, led), None)
            else:
                self._led[(ch, led)] = (r, g, b)

    def _flush(self):
        with self._led_lock:
            states = dict(self._led)
        frame = _make_frame(states)
        self._seq = (self._seq + 1) & 0xFFFF
        seq = self._seq
        ep  = (self.device_ip, self.send_port)
        try:
            self._ssock.sendto(_build_start(seq), ep)
            time.sleep(0.005)
            self._ssock.sendto(_build_fff0(seq), ep)
            time.sleep(0.005)
            self._ssock.sendto(_build_cmd(seq, 0x8877, 0x0000, frame), ep)
            time.sleep(0.005)
            self._ssock.sendto(_build_end(seq), ep)
        except Exception:
            pass

    def _all_off(self):
        with self._led_lock:
            self._led.clear()
        self._flush()

    def _set_eyes(self, r, g, b):
        for ch in self.active_players:
            self._set(ch, _EYE, r, g, b)

    # ── Button receiver ───────────────────────────────────────────────────────
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
                base = 2 + (ch-1)*171
                for idx in range(LEDS_PER_CHANNEL):
                    trig = (data[base+1+idx] == 0xCC)
                    if trig and not self._prev_btn.get((ch,idx), False):
                        self._on_btn_down(ch, idx)
                    self._prev_btn[(ch,idx)] = trig

    def _on_btn_down(self, ch, idx):
        if ch not in self.active_players or not self._react_open:
            return
        # Only the currently lit button on this wall counts
        if self._cur_lit.get(ch) != idx:
            return
        # Already decided → ignore
        if self._react_winner is not None:
            return

        if self._fire_color == 'red':
            # Correct! First press wins
            self._react_winner = ch
            self._react_ev.set()
        else:
            # Wrong timing or green-fire trap → fail sound + penalty
            self.scores[ch] -= 1
            _play(_FAIL)
            self._emit("wrong_press", player=ch, scores=dict(self.scores))

    # ── Emit ──────────────────────────────────────────────────────────────────
    def _emit(self, event, **kw):
        if self.on_event:
            try:
                self.on_event(event, **kw)
            except Exception:
                pass

    # ── Public API ────────────────────────────────────────────────────────────
    def start(self, total_rounds=10, active_players=None):
        if self._running:
            return
        self.total_rounds   = total_rounds
        self.active_players = active_players or [1,2,3,4]
        self.scores         = {p: 0 for p in range(1,5)}
        self.round_num      = 0
        self._running       = True
        threading.Thread(target=self._game_loop, daemon=True).start()

    def stop(self):
        self._running = False
        self._react_ev.set()

    # ── Sound folder picker ───────────────────────────────────────────────────
    def _pick_sound_folder(self):
        available = [f for f in FOLDER_WEIGHTS if f in _SOUND_FILES]
        if not available:
            return None
        # Force fire if streak exceeded
        if self._no_fire_streak >= MAX_NO_FIRE_STREAK and 'fire' in available:
            self._no_fire_streak = 0
            return 'fire'
        weights = [FOLDER_WEIGHTS[f] for f in available]
        folder  = random.choices(available, weights=weights)[0]
        if folder == 'fire':
            self._no_fire_streak = 0
        else:
            self._no_fire_streak += 1
        return folder

    # ── Game loop ─────────────────────────────────────────────────────────────
    def _game_loop(self):
        self._all_off()
        self._no_fire_streak = 0

        # Optional rules clip (must use absolute path — MCI cwd is not this script's folder)
        if os.path.isfile(_RULES_MP3):
            _play_mp3_blocking(os.path.abspath(_RULES_MP3))

        # Countdown – one random clip from sounds/ready/
        go_sounds = list(_SOUND_FILES.get('ready', []))
        if go_sounds:
            self._set_eyes(255, 165, 0)
            self._flush()
            _play_mp3_blocking(random.choice(go_sounds))
            self._all_off()
        else:
            # Fallback: fast TTS
            for n in (3, 2, 1):
                self._set_eyes(255, 165, 0)
                self._flush()
                self._tts.speak(str(n), vary=False)
                self._all_off()
            self._tts.speak("Go!", vary=False)

        _wait_interruptible(PRE_GAME_PAUSE, self)
        if not self._running:
            return

        while self.round_num < self.total_rounds and self._running:
            self._play_round()

        self._all_off()
        if not self._running:
            self._emit("stopped")
            return

        winner = max(self.active_players, key=lambda p: self.scores[p])
        self._emit("game_over", scores=dict(self.scores),
                   winner=winner, rounds=self.total_rounds)
        _play(_BOOM)
        time.sleep(0.3)
        self._tts.speak(f"Game over! Player {winner} wins!", vary=False)
        self._winner_flash(winner, rounds=7)
        self._running = False

    def _play_round(self):
        self.round_num += 1
        self._emit("round_start", round_num=self.round_num,
                   total=self.total_rounds, scores=dict(self.scores))

        folder = self._pick_sound_folder()
        if folder is None or folder not in _SOUND_FILES:
            time.sleep(0.5)
            return

        sound_file = random.choice(_SOUND_FILES[folder])
        self._play_word(is_fire=(folder == 'fire'), sound_file=sound_file)

    def _play_word(self, is_fire, sound_file):
        # ── Setup ─────────────────────────────────────────────────────────
        if is_fire:
            self._fire_color = random.choices(['red','green'], weights=[3,1])[0]
        else:
            self._fire_color = None

        self._cur_lit      = {ch: random.randint(1,10) for ch in self.active_players}
        self._react_winner = None
        self._react_open   = False
        if is_fire:
            self._react_ev.clear()

        self._emit("word",
                   word=os.path.splitext(os.path.basename(sound_file))[0],
                   is_fire=is_fire, fire_color=self._fire_color,
                   lit=dict(self._cur_lit))

        # ── 1. Wait PRE_SOUND_DELAY, then start sound ────────────────────
        _wait_interruptible(PRE_SOUND_DELAY, self)
        if not self._running:
            return
        sound_start, sound_dur = _play_mp3_start(sound_file)

        # ── 2. Wait LIGHT_START_DELAY then turn on white buttons ──────────
        _wait_interruptible(LIGHT_START_DELAY, self)
        if not self._running:
            return

        self._all_off()
        for ch, led in self._cur_lit.items():
            self._set(ch, led, 255, 255, 255)
        if is_fire:
            eye_rgb = (255,0,0) if self._fire_color=='red' else (0,255,0)
            self._set_eyes(*eye_rgb)
        self._react_open = True
        self._flush()

        # ── 3. Wait until sound finishes ──────────────────────────────────
        deadline = sound_start + sound_dur + 3.0   # +3 s safety margin
        while self._running and time.time() < deadline:
            if not _mp3_still_playing():
                break
            if is_fire and self._react_winner is not None:
                break
            time.sleep(0.02)

        # ── 4. Keep lights on for LIGHT_END_DELAY after sound ends ────────
        end_deadline = time.time() + LIGHT_END_DELAY
        while self._running and time.time() < end_deadline:
            if is_fire and self._react_winner is not None:
                break
            time.sleep(0.02)

        # ── 5. Lights OFF ─────────────────────────────────────────────────
        self._react_open = False
        self._all_off()

        # ── 6. Handle outcome ─────────────────────────────────────────────
        if is_fire:
            if self._react_winner:
                w = self._react_winner
                self.scores[w] += 1
                _stop_mp3()
                _play(_BOOM)
                self._emit("round_win", winner=w,
                           fire_color=self._fire_color,
                           round_num=self.round_num,
                           scores=dict(self.scores))
                time.sleep(0.25)
                self._tts.speak(f"Player {w} survives!", block=True, vary=False)
                self._winner_flash(w)
                _wait_interruptible(ROUND_PAUSE, self)
                return
            else:
                if self._fire_color == 'red':
                    self._emit("round_miss", round_num=self.round_num)
                else:
                    self._emit("round_safe", round_num=self.round_num)

        # Pause between rounds (after lights off, before next sound)
        _wait_interruptible(ROUND_PAUSE, self)

    def _winner_flash(self, winner, rounds=4):
        col = _PCOL[winner]
        for _ in range(rounds):
            for ch in self.active_players:
                self._set(ch, _EYE, *(col if ch == winner else (80, 0, 0)))
                for led in range(1, 11):
                    self._set(ch, led, *(col if ch == winner else (0, 0, 0)))
            self._flush()
            time.sleep(0.16)
            self._all_off()
            time.sleep(0.10)


def _wait_interruptible(secs, game):
    end = time.time() + secs
    while time.time() < end and game._running:
        time.sleep(0.05)

# ─────────────────────────────────────────────────────────────────────────────
# UI
# ─────────────────────────────────────────────────────────────────────────────
class FireGameUI:
    def __init__(self, root):
        self.root     = root
        self.root.title("FIRE! – Reaction Game")
        self.root.configure(bg="#0d0d0d")
        self.root.minsize(640, 480)
        self.game     = None
        self._running = False
        self._score_lbl = {}
        self._scores_win = None
        self._build_ui()
        self._apply_eye_cfg_to_ui()
        self._build_scores_window()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_eye_cfg_to_ui(self):
        cfg = _load_eye_ctrl_config()
        ip, _, _, _ = _fire_network_from_cfg(cfg)
        self._ip_var.set(ip)

    def _build_ui(self):
        # ── Top bar ──────────────────────────────────────────────────────────
        top = tk.Frame(self.root, bg="#1a1a1a", pady=10, padx=0)
        top.pack(fill=tk.X)
        tk.Label(top, text="FIRE! Reaction Game",
                 bg="#1a1a1a", fg="#ff6600",
                 font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT, padx=(16, 8))
        self._lbl_status = tk.Label(top, text="IDLE",
                                    bg="#1a1a1a", fg="#666666",
                                    font=("Segoe UI", 11, "bold"))
        self._lbl_status.pack(side=tk.RIGHT, padx=(8, 16))

        # ── Config (aligned grid) ─────────────────────────────────────────────
        cfg_outer = tk.Frame(self.root, bg="#0d0d0d", padx=16, pady=12)
        cfg_outer.pack(fill=tk.X)
        cfg = tk.Frame(cfg_outer, bg="#141414", highlightbackground="#2a2a2a",
                       highlightthickness=1, padx=12, pady=10)
        cfg.pack(fill=tk.X)

        def lbl(t):
            return tk.Label(cfg, text=t, bg="#141414", fg="#9a9a9a",
                            font=("Segoe UI", 9))

        self._ip_var = tk.StringVar(value="")
        self._rounds_var = tk.IntVar(value=10)
        self._pvar = {}

        lbl("Device IP").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 4))
        ip_e = tk.Entry(cfg, textvariable=self._ip_var, width=18,
                        bg="#0a0a0a", fg="#33dd66", insertbackground="#cccccc",
                        relief="flat", highlightthickness=1,
                        highlightbackground="#2a6633", highlightcolor="#33aa44",
                        font=("Consolas", 10))
        ip_e.grid(row=1, column=0, sticky="w", padx=(0, 20), pady=(0, 8))

        lbl("Rounds").grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 4))
        tk.Spinbox(cfg, from_=2, to=99, textvariable=self._rounds_var,
                   width=5, bg="#0a0a0a", fg="#33dd66",
                   buttonbackground="#333", font=("Consolas", 10),
                   highlightthickness=0).grid(row=1, column=1, sticky="w",
                                              padx=(0, 24), pady=(0, 8))

        lbl("Players").grid(row=0, column=2, sticky="w", pady=(0, 4))
        pfrm = tk.Frame(cfg, bg="#141414")
        pfrm.grid(row=1, column=2, rowspan=1, sticky="w", pady=(0, 8))
        for p in (1, 2, 3, 4):
            v = tk.BooleanVar(value=True)
            self._pvar[p] = v
            tk.Checkbutton(
                pfrm, text=f"P{p}", variable=v,
                bg="#141414", fg=_PCOL_HEX[p],
                selectcolor="#252525", activebackground="#141414",
                activeforeground=_PCOL_HEX[p],
                font=("Segoe UI", 9, "bold"),
            ).pack(side=tk.LEFT, padx=(0, 10))

        cfg.columnconfigure(0, weight=0)
        cfg.columnconfigure(1, weight=0)
        cfg.columnconfigure(2, weight=1)

        # ── Main play area ────────────────────────────────────────────────────
        play = tk.Frame(self.root, bg="#0d0d0d")
        play.pack(fill=tk.BOTH, expand=True, pady=(16, 8))
        self._lbl_word = tk.Label(play, text="",
                                  bg="#0d0d0d", fg="#f0f0f0",
                                  font=("Segoe UI", 40, "bold"))
        self._lbl_word.pack(pady=(8, 4))

        self._lbl_eye = tk.Label(play, text="",
                                 bg="#0d0d0d", fg="#ff3333",
                                 font=("Segoe UI", 15, "bold"))
        self._lbl_eye.pack(pady=(0, 12))

        self._btn = tk.Button(
            play, text="START GAME",
            command=self._toggle,
            bg="#1e5c2e", fg="#ffffff",
            activebackground="#267a3a", activeforeground="#ffffff",
            font=("Segoe UI", 11, "bold"),
            relief="flat", padx=28, pady=10, cursor="hand2",
        )
        self._btn.pack(pady=(8, 20))

        # ── Log ────────────────────────────────────────────────────────────────
        log_frame = tk.Frame(self.root, bg="#0d0d0d")
        log_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=(0, 12))
        tk.Label(log_frame, text="Log", bg="#0d0d0d", fg="#666",
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 4))
        self._log = scrolledtext.ScrolledText(
            log_frame, bg="#080808", fg="#22bb55",
            font=("Consolas", 9), state="disabled",
            height=8, borderwidth=0, highlightthickness=1,
            highlightbackground="#222", insertbackground="#ccc",
        )
        self._log.pack(fill=tk.BOTH, expand=True)

    def _build_scores_window(self):
        w = tk.Toplevel(self.root)
        w.title("FIRE! – Scores")
        w.configure(bg="#111111")
        w.minsize(340, 140)
        w.transient(self.root)

        def place_scores_window():
            self.root.update_idletasks()
            try:
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw = self.root.winfo_width()
                w.geometry(f"+{rx + rw + 12}+{ry}")
            except tk.TclError:
                pass

        place_scores_window()

        hdr = tk.Frame(w, bg="#1a1a1a", pady=8)
        hdr.pack(fill=tk.X)
        tk.Label(hdr, text="Scores", bg="#1a1a1a", fg="#ff8800",
                 font=("Segoe UI", 12, "bold")).pack()

        body = tk.Frame(w, bg="#111111", padx=16, pady=14)
        body.pack(fill=tk.BOTH, expand=True)

        self._score_lbl.clear()
        for p in (1, 2, 3, 4):
            col = tk.Frame(body, bg="#111111")
            col.pack(side=tk.LEFT, padx=(0, 18), expand=True, fill=tk.BOTH)
            tk.Label(col, text=f"Player {p}", bg="#111111",
                     fg=_PCOL_HEX[p], font=("Segoe UI", 9, "bold")).pack()
            s = tk.Label(col, text="0", bg="#111111", fg="#f5f5f5",
                         font=("Segoe UI", 28, "bold"))
            s.pack(pady=(4, 0))
            self._score_lbl[p] = s

        def on_scores_close():
            w.withdraw()

        w.protocol("WM_DELETE_WINDOW", on_scores_close)
        self._scores_win = w

    def _scores_deiconify(self):
        if self._scores_win is not None:
            try:
                self.root.update_idletasks()
                rx, ry = self.root.winfo_rootx(), self.root.winfo_rooty()
                rw = self.root.winfo_width()
                self._scores_win.geometry(f"+{rx + rw + 12}+{ry}")
                self._scores_win.deiconify()
                self._scores_win.lift()
            except tk.TclError:
                pass

    def _apply_scores(self, sc):
        for p, lbl in list(self._score_lbl.items()):
            try:
                lbl.config(text=str(sc.get(p, 0)))
            except tk.TclError:
                pass

    def _log_msg(self, msg):
        if msg and "ttsmp3.com" in msg.lower():
            return
        ts = datetime.now().strftime("%H:%M:%S")
        self._log.configure(state="normal")
        self._log.insert(tk.END, f"[{ts}] {msg}\n")
        self._log.see(tk.END)
        self._log.configure(state="disabled")

    def _set_status(self, text, color="#00cc00"):
        self._lbl_status.config(text=text, fg=color)

    def _toggle(self):
        if self._running:
            self._stop_game()
        else:
            self._start_game()

    def _start_game(self):
        active = [p for p, v in self._pvar.items() if v.get()]
        if not active:
            self._log_msg("Select at least one player!")
            return
        self._running = True
        self._scores_deiconify()
        self._btn.config(text="STOP", bg="#8b2a2a", activebackground="#a83333")
        self._set_status("PLAYING", "#33ee66")
        self._apply_scores({1: 0, 2: 0, 3: 0, 4: 0})
        self._lbl_word.config(text="", fg="white")
        self._lbl_eye.config(text="")
        cfg = _load_eye_ctrl_config()
        ip, send_port, recv_port, recv_bind = _fire_network_from_cfg(cfg)
        self._ip_var.set(ip)
        self.game = FireGame(
            device_ip    = ip,
            send_port    = send_port,
            recv_port    = recv_port,
            recv_bind_ip = recv_bind,
            on_event     = self._on_game_event,
        )
        self.game.start(
            total_rounds   = self._rounds_var.get(),
            active_players = active,
        )

    def _stop_game(self):
        if self.game:
            self.game.stop()
        self._running = False
        self._btn.config(text="START GAME", bg="#1e5c2e", activebackground="#267a3a")
        self._set_status("STOPPED", "#666666")
        self._lbl_word.config(text="")
        self._lbl_eye.config(text="")

    def _on_game_event(self, event, **kw):
        self.root.after(0, self._handle_event, event, kw)

    def _handle_event(self, event, kw):
        if event == "log":
            self._log_msg(kw.get("msg", ""))

        elif event == "round_start":
            rn, tot = kw["round_num"], kw["total"]
            self._lbl_word.config(text="", fg="#f0f0f0")
            self._lbl_eye.config(text="")
            self._set_status(f"Round {rn} / {tot}", "#44dd77")
            self._log_msg(f"── Round {rn}/{tot} ──")

        elif event == "word":
            word, is_f, fcol = kw["word"], kw["is_fire"], kw.get("fire_color")
            show = _word_for_display(word)
            logw = _word_for_log(word)
            if is_f:
                self._lbl_word.config(text=show, fg="#ff4422")
                if fcol == 'red':
                    self._lbl_eye.config(text="[ RED – PRESS! ]", fg="#ff3333")
                else:
                    self._lbl_eye.config(text="[ GREEN – DON'T! ]", fg="#33ff66")
            else:
                self._lbl_word.config(text=show, fg="#f0f0f0")
                self._lbl_eye.config(text="")
            self._log_msg(f"  {logw}" + (f" [{fcol.upper()} EYE]" if is_f else ""))

        elif event == "round_win":
            w, sc = kw["winner"], kw["scores"]
            self._apply_scores(sc)
            self._set_status(f"Player {w} survives!", _PCOL_HEX[w])
            self._lbl_eye.config(text=f"Player {w} survives!", fg=_PCOL_HEX[w])
            self._log_msg(f"BOOM  Player {w} survives! | {sc}")

        elif event == "round_miss":
            self._set_status("Nobody pressed!", "#ff8800")
            self._lbl_eye.config(text="Too slow…", fg="#ff8800")
            self._log_msg("No reaction in time.")

        elif event == "round_safe":
            self._set_status("Safe – green eye survived!", "#00ff88")
            self._lbl_eye.config(text="Safe!", fg="#00ff88")
            self._log_msg("GREEN eye – nobody pressed, safe.")

        elif event == "wrong_press":
            p, sc = kw["player"], kw.get("scores", {})
            self._apply_scores(sc)
            self._lbl_eye.config(text=f"Player {p}: WRONG! -1", fg="#ff0055")
            self._log_msg(f"  WRONG PRESS – Player {p} → {sc.get(p, '?')}")

        elif event == "stopped":
            self._running = False
            self._btn.config(text="START GAME", bg="#1e5c2e", activebackground="#267a3a")
            self._set_status("STOPPED", "#666666")

        elif event == "game_over":
            sc, w = kw["scores"], kw["winner"]
            self._running = False
            self._btn.config(text="START GAME", bg="#1e5c2e", activebackground="#267a3a")
            self._apply_scores(sc)
            self._set_status(f"GAME OVER – Player {w} wins!", _PCOL_HEX[w])
            self._lbl_word.config(text=f"Player {w} wins!", fg=_PCOL_HEX[w])
            self._lbl_eye.config(text="")
            self._log_msg(f"GAME OVER | {sc} | Winner: Player {w}")

    def _on_close(self):
        if self.game:
            self.game.stop()
        try:
            if self._scores_win is not None:
                self._scores_win.destroy()
        except tk.TclError:
            pass
        self.root.destroy()


# ─────────────────────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    FireGameUI(root)
    root.mainloop()

if __name__ == "__main__":
    _evileye_root = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    if _evileye_root not in sys.path:
        sys.path.insert(0, _evileye_root)
    import evil_eye_network_setup

    evil_eye_network_setup.run_startup_discovery_and_save_config()
    main()
