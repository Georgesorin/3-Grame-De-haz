# Hot Potato – Team Mode Game
### Evil Eye Hardware · Turn-Based LED Game

---

## Quick Start

```bash
cd EvilEye
python hot_potato.py
```

Requires `Controller.py` in the same directory (already present).

---

## Hardware Setup

| Wall (Channel) | Team         | Colour      |
|---------------|--------------|-------------|
| Wall 1        | Team A       | Orange-Red  |
| Wall 2        | Team B       | Blue        |
| Wall 3        | Team C       | Green       |
| Wall 4        | Team D       | Purple      |

Each wall has:
- **LED 0** – The Eye (team indicator)
- **LED 1–10** – Buttons (targets / interactive)

---

## Setup Screen

Configure before starting:

| Setting        | Options          | Default  |
|---------------|------------------|----------|
| Teams          | 2 / 3 / 4        | 2        |
| Difficulty     | Easy / Medium / Hard | Medium |
| Win Score      | 5 / 10 / 15 / 20 | 10       |
| Team Names     | Custom text      | TEAM A–D |
| Device IP      | IP address       | from config |

Press **▶ START GAME** when ready.

---

## LED Colour Guide

| Colour        | Meaning                          |
|--------------|----------------------------------|
| 🔴 Red        | Hot potato – press this button!  |
| 🟢 Green      | Correct hit confirmed            |
| ⚪ Team colour | Active team's eye indicator      |
| ⬛ Off         | Button is inactive               |

---

## Gameplay

### Turn Flow

```
[ TRANSITION ] → active team's eye pulses 3×
       ↓
[ PLAYING ] → N red targets appear on active wall
       ↓
  Press red buttons before timer runs out
       ↓
  ┌────────────┬──────────────────┐
  │   All hit  │   Timer expired  │
  │   → HIT    │   → MISS         │
  └────────────┴──────────────────┘
       ↓                ↓
  +1 point         No points
  Green flash      Red flash
       ↓                ↓
        Next team's turn
```

### Rules

- Only the **active team's wall** is live – other walls are ignored
- Press **all** lit red buttons to clear the round
- Each correct press turns green immediately
- If time expires with any targets remaining → MISS
- No penalty score for misses – next team gets the turn

### Win Condition

First team to reach the configured **Win Score** wins.
The winner's wall strobes in their team colour.

---

## Difficulty Scaling

Difficulty increases automatically as total hits accumulate:

| Difficulty | Start Targets | Start Time | Min Time | Levels up every |
|-----------|--------------|------------|----------|-----------------|
| Easy      | 1            | 5.0 s      | 2.5 s    | 6 hits          |
| Medium    | 1            | 3.5 s      | 1.5 s    | 4 hits          |
| Hard      | 2            | 2.5 s      | 1.0 s    | 3 hits          |

Each level increase:
- Adds 0.3 s less reaction time (down to the floor)
- May add an extra simultaneous target (max 3)

The **level bar** on the game screen shows progress to the next level.

---

## Display Layout

### Game Screen

```
┌──────────────────────────────────────────────────────┐
│  [TEAM A  3] [TEAM B  1] [TEAM C  0]  ← score panels│
├──────────────────────────────────────────────────────┤
│                                                      │
│              ▶  TEAM A                               │
│         Press the RED buttons!                       │
│                                                      │
│                  3.2                                 │  ← timer
│             2 targets remaining                      │
│                                                      │
│  LEVEL  3  ██████████░░░░░░░░░  MEDIUM               │  ← progress
│                                                      │
│  [⚙ Setup]  [⏹ Stop Game]                           │
└──────────────────────────────────────────────────────┘
```

**Timer colour:**
- Green → time is comfortable
- Gold  → less than 2 seconds
- Red   → less than 1 second

---

## Keyboard Shortcuts

| Key   | Action            |
|-------|-------------------|
| F11   | Toggle fullscreen |
| ESC   | Exit fullscreen   |

---

## Network Configuration

Settings are read from `eye_ctrl_config.json`:

```json
{
  "device_ip":       "192.168.1.7",
  "udp_port":        4626,
  "receiver_port":   7800,
  "polling_rate_ms": 100
}
```

You can also change the device IP directly in the Setup screen and press **APPLY**.

To use with the **Simulator** instead of real hardware:
1. Run `python Simulator.py`
2. Set Device IP to `127.0.0.1`
3. Simulator Port IN: `4626`, Port OUT: `7800`

---

## Files

```
EvilEye/
├── hot_potato.py          ← this game
├── Controller.py          ← LED service + UI controller
├── Simulator.py           ← software simulator
└── eye_ctrl_config.json   ← connection settings
```
