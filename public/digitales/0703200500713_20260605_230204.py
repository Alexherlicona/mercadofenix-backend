import asyncio
import pygame
import random
import platform

# Initialize Pygame
pygame.init()
WIDTH, HEIGHT = 800, 600
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Painting: A Beautiful Bouquet of Roses")

# Colors
WHITE = (255, 255, 255)
RED = (200, 0, 0)
GREEN = (0, 100, 0)
DARK_GREEN = (0, 50, 0)
BLACK = (0, 0, 0)

# Font for signature
try:
    font = pygame.font.SysFont('timesnewroman', 20, italic=True)
except:
    font = pygame.font.Font(None, 24)  # Fallback font

# Rose parameters
ROSE_COUNT = 5
PETAL_COUNT = 8
PETAL_SIZE = 20
STEM_LENGTH = 150
LEAF_SIZE = 30

# Animation state
frame = 0
max_frames = 200
roses = []

def setup():
    screen.fill(WHITE)
    # Define rose positions
    for i in range(ROSE_COUNT):
        x = 200 + i * 100 + random.randint(-20, 20)
        y = HEIGHT - 100 + random.randint(-20, 20)
        roses.append({'x': x, 'y': y, 'petals_drawn': 0, 'stem_drawn': 0, 'leaves_drawn': 0})

def draw_petal(x, y, angle, size):
    points = []
    for i in range(4):
        rad = (angle + i * 90) * 3.14159 / 180
        px = x + size * (1 - i/6) * pygame.math.Vector2(1, 0).rotate(angle).x
        py = y + size * (1 - i/6) * pygame.math.Vector2(1, 0).rotate(angle).y
        points.append((px, py))
    pygame.draw.polygon(screen, RED, points)

def draw_rose(rose):
    x, y = rose['x'], rose['y']
    # Draw stem
    if rose['stem_drawn'] < STEM_LENGTH:
        stem_progress = min(rose['stem_drawn'], STEM_LENGTH)
        pygame.draw.line(screen, GREEN, (x, y), (x, y - stem_progress), 5)
        rose['stem_drawn'] += 2
    # Draw leaves
    elif rose['leaves_drawn'] < 2:
        leaf_y = y - STEM_LENGTH * 0.6
        leaf_x_offset = 20 if rose['leaves_drawn'] == 0 else -20
        leaf_angle = 45 if rose['leaves_drawn'] == 0 else -45
        points = [
            (x + leaf_x_offset, leaf_y),
            (x + leaf_x_offset + LEAF_SIZE * pygame.math.Vector2(1, 0).rotate(leaf_angle).x,
             leaf_y + LEAF_SIZE * pygame.math.Vector2(1, 0).rotate(leaf_angle).y),
            (x + leaf_x_offset + LEAF_SIZE * pygame.math.Vector2(1, 0).rotate(leaf_angle + 90).x,
             leaf_y + LEAF_SIZE * pygame.math.Vector2(1, 0).rotate(leaf_angle + 90).y)
        ]
        pygame.draw.polygon(screen, DARK_GREEN, points)
        rose['leaves_drawn'] += 1
    # Draw petals
    elif rose['petals_drawn'] < PETAL_COUNT:
        angle = rose['petals_drawn'] * 360 / PETAL_COUNT
        draw_petal(x, y - STEM_LENGTH, angle, PETAL_SIZE)
        rose['petals_drawn'] += 1

def draw_signature():
    signature = font.render("Alexander Licona for Lilin Castellanos", True, BLACK)
    screen.blit(signature, (WIDTH - signature.get_width() - 10, HEIGHT - 30))

def update_loop():
    global frame
    if frame < max_frames:
        for rose in roses:
            draw_rose(rose)
        frame += 1
    else:
        draw_signature()
    pygame.display.flip()

async def main():
    setup()
    while True:
        update_loop()
        await asyncio.sleep(1.0 / 60)  # 60 FPS

if platform.system() == "Emscripten":
    asyncio.ensure_future(main())
else:
    if __name__ == "__main__":
        asyncio.run(main())