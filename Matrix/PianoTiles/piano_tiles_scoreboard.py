"""
Live scoreboard for Piano Tiles over UDP.

Run while Piano_Tiles_Game.py is running. The game sends JSON snapshots to
  scoreboard_host : scoreboard_udp_port  (default 127.0.0.1:7810, from piano_tiles_config.json)

Usage:
  python piano_tiles_scoreboard.py
"""

from __future__ import annotations

import json
import os
import socket
import sys
import tkinter as tk
from tkinter import font as tkfont

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import Piano_Tiles_Game as ptg  # noqa: E402


POLL_MS = 80
MAX_PLAYER_ROWS = 4


def _song_fallback() -> str:
    return ptg.read_song_title_from_chart(ptg._chart_path_from_config())


class ScoreboardApp:
    def __init__(self) -> None:
        self._last: dict | None = None
        self.sock: socket.socket | None = None
        self._bind_error: str | None = None

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("0.0.0.0", ptg.SCOREBOARD_UDP_PORT))
            s.setblocking(False)
            self.sock = s
        except OSError as e:
            self._bind_error = str(e)

        self.root = tk.Tk()
        self.root.title("Piano Tiles — Scoreboard (UDP)")
        self.root.configure(bg="#12121a")
        self.root.minsize(440, 280)

        try:
            base_family = tkfont.nametofont("TkFixedFont").actual("family")
        except tk.TclError:
            base_family = "Consolas"

        self.title_font = tkfont.Font(family=base_family, size=18, weight="bold")
        self.song_font = tkfont.Font(family=base_family, size=14)
        self.header_font = tkfont.Font(family=base_family, size=10, weight="bold")
        self.row_font = tkfont.Font(family=base_family, size=12)
        self.status_font = tkfont.Font(family=base_family, size=10)

        tk.Label(
            self.root,
            text="Piano Tiles",
            font=self.title_font,
            fg="#e8e8f0",
            bg="#12121a",
        ).pack(pady=(12, 2))

        port_lbl = f"UDP :{ptg.SCOREBOARD_UDP_PORT}"
        tk.Label(
            self.root,
            text=port_lbl,
            font=self.status_font,
            fg="#606078",
            bg="#12121a",
        ).pack(pady=(0, 4))

        self.lbl_song = tk.Label(
            self.root,
            text="—",
            font=self.song_font,
            fg="#7eb6ff",
            bg="#12121a",
            wraplength=520,
            justify=tk.CENTER,
        )
        self.lbl_song.pack(pady=(0, 8))

        self.lbl_status = tk.Label(
            self.root,
            text="",
            font=self.status_font,
            fg="#8888a0",
            bg="#12121a",
            wraplength=520,
        )
        self.lbl_status.pack(pady=(0, 6))

        hdr = tk.Frame(self.root, bg="#1e1e2e")
        hdr.pack(fill=tk.X, padx=12, pady=4)
        headers = ("Player", "Score", "Streak", "Next ×")
        widths = (14, 10, 8, 8)
        for i, text in enumerate(headers):
            tk.Label(
                hdr,
                text=text,
                font=self.header_font,
                fg="#a0a0b8",
                bg="#1e1e2e",
                width=widths[i],
                anchor=tk.W if i == 0 else tk.E,
            ).grid(row=0, column=i, sticky=tk.EW, padx=3, pady=6)
        hdr.grid_columnconfigure(0, weight=1)

        self.rows_frame = tk.Frame(self.root, bg="#12121a")
        self.rows_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 16))
        self.rows_frame.grid_columnconfigure(0, weight=1)

        self.player_labels: list[list[tk.Label]] = []
        for r in range(MAX_PLAYER_ROWS):
            row_widgets: list[tk.Label] = []
            for c in range(4):
                lbl = tk.Label(
                    self.rows_frame,
                    text="—",
                    font=self.row_font,
                    fg="#d0d0e0",
                    bg="#18182a",
                    width=widths[c],
                    anchor=tk.W if c == 0 else tk.E,
                    padx=6,
                    pady=5,
                )
                lbl.grid(row=r, column=c, sticky=tk.EW, pady=2)
                row_widgets.append(lbl)
            self.player_labels.append(row_widgets)

        if self._bind_error:
            self.lbl_status.config(
                text=f"Could not bind UDP port {ptg.SCOREBOARD_UDP_PORT}: {self._bind_error}",
                fg="#ff6666",
            )

        self.root.after(POLL_MS, self._poll)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
        self.root.destroy()

    def _drain_udp(self) -> None:
        if not self.sock:
            return
        while True:
            try:
                data, _ = self.sock.recvfrom(65535)
            except BlockingIOError:
                break
            except OSError:
                break
            try:
                obj = json.loads(data.decode("utf-8"))
                if isinstance(obj, dict):
                    self._last = obj
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue

    def _poll(self) -> None:
        if not self.root.winfo_exists():
            return

        self._drain_udp()

        if self._last is None:
            song = _song_fallback() or "—"
            self.lbl_song.config(text=song)
            if not self._bind_error:
                self.lbl_status.config(
                    text=f"Waiting for packets on UDP {ptg.SCOREBOARD_UDP_PORT}…",
                    fg="#8888a0",
                )
            for row in self.player_labels:
                for c in range(4):
                    row[c].config(text="—" if c < 2 else "", fg="#505068")
            self.root.after(POLL_MS, self._poll)
            return

        data = self._last
        song = (data.get("song") or "").strip() or _song_fallback() or "—"
        self.lbl_song.config(text=song)

        state = data.get("state", "?")
        n = data.get("num_players", 0)
        cmax = data.get("combo_max", ptg.COMBO_MAX)
        self.lbl_status.config(
            text=f"State: {state}   ·   Players: {n}   ·   Combo cap (×): {cmax}",
            fg="#8888a0",
        )

        players = data.get("players")
        if not isinstance(players, list):
            players = []

        for i in range(MAX_PLAYER_ROWS):
            row = self.player_labels[i]
            if i < len(players) and isinstance(players[i], dict):
                p = players[i]
                slot = int(p.get("slot", i))
                row[0].config(text=f"Player {slot + 1}", fg="#d0d0e0")
                row[1].config(text=str(p.get("score", 0)), fg="#d0d0e0")
                row[2].config(text=str(p.get("combo", 0)), fg="#d0d0e0")
                nx = p.get("combo_mult_next", 1)
                row[3].config(text=str(nx), fg="#a8d896")
            else:
                for c in range(4):
                    row[c].config(text="", fg="#505068")

        self.root.after(POLL_MS, self._poll)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    app = ScoreboardApp()
    app.run()


if __name__ == "__main__":
    main()
