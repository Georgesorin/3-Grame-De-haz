import pygame
import pretty_midi
import time

# ------------------------
# 1️⃣ Încarcă fișierul MIDI
# ------------------------
midi_file = r"C:\Users\bmdma\ledhack\3-Grame-De-haz\Matrix\Pirates of the Caribbean - He's a Pirate (2).mid"
pm = pretty_midi.PrettyMIDI(midi_file)

# Extrage notele și timestamp-urile lor
melodie = []
for instr in pm.instruments:
    for nota in instr.notes:
        melodie.append({"nota": nota.pitch, "t_imp": nota.start, "hit": False})

# Sortează după timp
melodie.sort(key=lambda x: x["t_imp"])

# ------------------------
# 2️⃣ Filtrare pentru jucabilitate
# ------------------------
interval_minim = 0.35  # secunde între tile-uri
ult_t_imp = -1
melodie_filtrata = []

for nota in melodie:
    # păstrează doar note cu interval >= interval_minim
    if nota["t_imp"] - ult_t_imp >= interval_minim:
        # optional: filtrare după pitch (note medii/joase)
        if 50 <= nota["nota"] <= 75:
            melodie_filtrata.append(nota)
            ult_t_imp = nota["t_imp"]

melodie = melodie_filtrata

# ------------------------
# 3️⃣ Setări tile-uri și ecran
# ------------------------
y_start = 600
y_hit = 50
viteza = 180  # pixeli/sec
screen_width = 400
screen_height = y_start + 100
col_count = 4

# distribuție pe coloane
def get_x(idx):
    return 50 + (idx % col_count) * 80

# interval toleranță pentru scor
toleranta = 0.2  # secunde

# ------------------------
# 4️⃣ Inițializare pygame
# ------------------------
pygame.init()
screen = pygame.display.set_mode((screen_width, screen_height))
pygame.display.set_caption("Mini Piano Tiles - He's a Pirate")
clock = pygame.time.Clock()

# ------------------------
# 5️⃣ Redă audio
# ------------------------
pygame.mixer.music.load(r"C:\Users\bmdma\ledhack\3-Grame-De-haz\Matrix\Pirates of the Caribbean - Hes a Pirate (2).mp3")
pygame.mixer.music.play()
start_time = time.time()

score = 0
font = pygame.font.SysFont(None, 36)
running = True

# ------------------------
# 6️⃣ Loop principal
# ------------------------
while running:
    t_curent = time.time() - start_time
    screen.fill((255, 255, 255))

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            key_to_col = {pygame.K_a:0, pygame.K_s:1, pygame.K_d:2, pygame.K_f:3}
            if event.key in key_to_col:
                col = key_to_col[event.key]
                # verificăm tile-urile active din această coloană
                for idx, nota in enumerate(melodie):
                    if nota["hit"]:
                        continue
                    y_pos = y_hit + (nota["t_imp"] - t_curent) * viteza
                    nota_col = idx % col_count
                    if nota_col == col and abs(y_pos - y_hit) <= toleranta * viteza:
                        score += 1
                        nota["hit"] = True
                        break

    # desenăm linia de hit
    pygame.draw.line(screen, (255, 0, 0), (0, y_hit), (screen_width, y_hit), 3)

    # desenăm tile-urile active
    for idx, nota in enumerate(melodie):
        if nota["hit"]:
            continue
        t_ramane = nota["t_imp"] - t_curent
        y = y_hit + t_ramane * viteza
        if y > y_hit:
            pygame.draw.rect(screen, (0, 0, 0), (get_x(idx), y-20, 60, 20))

    # afișăm scorul
    score_text = font.render(f"Score: {score}", True, (0,0,0))
    screen.blit(score_text, (10, 10))

    pygame.display.flip()
    clock.tick(60)

pygame.quit()