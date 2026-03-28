import mido
import numpy as np
import sounddevice as sd

mid = mido.MidiFile(r"C:\Users\bmdma\ledhack\3-Grame-De-haz\Matrix\Pirates of the Caribbean - He's a Pirate (2).mid")
tempo = 500000

NOTE_TO_FREQ = {n: round(440 * 2 ** ((n - 69) / 12)) for n in range(128)}

notes = []  # list of (freq, duration_in_seconds)
active = {}  # note -> start_time

elapsed = 0
for track in mid.tracks:
    elapsed = 0
    for msg in track:
        elapsed += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
        if msg.type == 'set_tempo':
            tempo = msg.tempo
        if msg.type == 'note_on' and msg.velocity > 0:
            active[msg.note] = elapsed
        if msg.type == 'note_off' or (msg.type == 'note_on' and msg.velocity == 0):
            if msg.note in active:
                duration = elapsed - active.pop(msg.note)
                notes.append((NOTE_TO_FREQ[msg.note], round(duration, 3)))

print(notes)

fs = 44100
notes = notes[:1000]  # limit to first 100 notes for testing``

signal = np.array([])
for freq, dur in notes:
    dur = max(dur, 0.05)  # minimum 50ms so nothing is silent
    t = np.linspace(0, dur, int(fs * dur), False)
    note = np.sin(2 * np.pi * freq * t)
    # fade out to avoid clicks between notes
    fade = np.linspace(1, 0, len(note))
    signal = np.concatenate((signal, note * fade))

signal = signal / np.max(np.abs(signal))
sd.play(signal, fs)
sd.wait()