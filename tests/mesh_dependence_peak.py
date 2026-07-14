"""Demuestra que el 'pico' de irradiancia del mapa depende del tamaño de celda.
Reproduce ~ el escenario del usuario (300 W, plano 5 cm bajo la lámpara) y
bina los mismos impactos de rayo a resoluciones crecientes."""
import os, sys, numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulation_engine import SimulationEngine

LAMP = "TEMPEST 600W.xml"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Z_LAMP, DEPTH = 1.0, 1.05           # plano 5 cm bajo la lámpara
ENV = 30.0; CX = CY = 15.0
RAYS = 500000

cfg = {
    "env": {"type": "jaula", "shape": "rect", "x": ENV, "y": ENV, "z": 20},
    "optics": {"mode": "kd_fijo", "kd_fijo": 0.1, "atten_coef_type": "c"},
    "optics_mode": "kd_fijo",
    "target_depths": [DEPTH], "rays": RAYS, "source_model": "point",
    "lamps": [{"xml": LAMP, "x": CX, "y": CY, "z": Z_LAMP,
               "power": 300, "dim": 1, "efficiency": 1.0,
               "rot_x": 0, "rot_y": 0, "rot_z": 0}],
}

with open(os.path.join(ROOT, "uploaded_lamps", LAMP), errors="ignore") as f:
    content = f.read()
np.random.seed(1)
eng = SimulationEngine(); eng.load_file(LAMP, content)
res = eng.run(cfg)
r = res[str(DEPTH)]
x, y, v = np.array(r["x"]), np.array(r["y"]), np.array(r["val"])
print(f"Impactos en el plano: {len(v)} | flujo total = {v.sum():.1f} W")

def peak(cell):
    # malla centrada, celda 'cell' m, sobre todo el dominio
    edges = np.arange(0, ENV + cell, cell)
    H, _, _ = np.histogram2d(x, y, bins=[edges, edges], weights=v)
    return H.max() / (cell * cell)

print(f"\n{'celda [m]':>10} {'#celdas':>8} {'pico E [W/m^2]':>16}")
for cell in [0.303, 0.15, 0.05, 0.02, 0.01]:
    print(f"{cell:>10.3f} {int(ENV/cell):>8} {peak(cell):>16.1f}")

# valor analítico de referencia (lambertiano puntual): Phi/(pi D^2)
D = DEPTH - Z_LAMP
print(f"\nReferencia analitica punto lambertiano  Phi/(pi D^2) = {300/(np.pi*D*D):.1f} W/m^2")
print(f"'Malla de 100 bins' del simulador (celda {ENV/99:.3f} m) -> pico {peak(ENV/99):.1f} W/m^2")
