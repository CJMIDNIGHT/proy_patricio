#!/usr/bin/env python3

import subprocess
import random
import time
import math

WORLD = "house"
ENTITY = "child"

# posición inicial
x = 0.0
y = 0.0

def move_child(x, y, z=0.05):
    cmd = [
        "gz", "service",
        "-s", f"/world/{WORLD}/set_pose",
        "--reqtype", "gz.msgs.Pose",
        "--reptype", "gz.msgs.Boolean",
        "--timeout", "2000",
        "--req",
        f'name: "{ENTITY}", position: {{x: {x}, y: {y}, z: {z}}}'
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL)

def main():
    global x, y

    print("Niño andando suavemente...")

    while True:
        # destino aleatorio
        target_x = random.uniform(-4, 4)
        target_y = random.uniform(-3, 3)

        dx = target_x - x
        dy = target_y - y
        dist = math.sqrt(dx**2 + dy**2)

        steps = int(dist / 0.05)  # 👈 controla suavidad

        if steps == 0:
            continue

        step_x = dx / steps
        step_y = dy / steps

        for _ in range(steps):
            x += step_x
            y += step_y

            move_child(x, y)

            time.sleep(0.05)  # 👈 velocidad (más pequeño = más fluido)

        time.sleep(0.5)  # pequeña pausa entre destinos


if __name__ == "__main__":
    main()