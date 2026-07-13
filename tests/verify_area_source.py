"""Verificación del modelo de fuente extendida (COB) vs fuente puntual.

Comprueba tres cosas:
  1. Conservación de flujo: el flujo total que cruza un plano no cambia con el
     modelo de fuente (el área sólo redistribuye orígenes, no crea/destruye luz).
  2. Campo lejano: a distancia >> tamaño del COB, punto y área convergen.
  3. Campo cercano: cerca del emisor, el área baja el pico y ensancha el spot
     (elimina la singularidad 1/r^2 de la fuente puntual).
"""
import os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from simulation_engine import SimulationEngine

LAMP = "TEMPEST 600W.xml"
LAMP_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "uploaded_lamps", LAMP)

Z_LAMP = 1.0          # profundidad de la lámpara [m]
NEAR = Z_LAMP + 0.3   # plano a 0.3 m bajo la lámpara (campo cercano)
FAR = Z_LAMP + 10.0   # plano a 10 m (campo lejano)
COB_L = 1.5           # COB exagerado (1.5 m) para que el efecto supere el ruido MC
RAYS = 300000


def base_config(source_model):
    return {
        "env": {"type": "jaula", "shape": "rect", "x": 40, "y": 40, "z": 20},
        "optics": {"mode": "kd_fijo", "kd_fijo": 0.05, "atten_coef_type": "c"},
        "optics_mode": "kd_fijo",
        "target_depths": [NEAR, FAR],
        "rays": RAYS,
        "source_model": source_model,
        "lamps": [{
            "xml": LAMP, "x": 20, "y": 20, "z": Z_LAMP,
            "power": 600, "dim": 1, "efficiency": 1.0,
            "rot_x": 0, "rot_y": 0, "rot_z": 0,
            "cob": {"length": COB_L, "width": COB_L, "shape": "rect"},
        }],
    }


def plane_stats(res, key, cx=20, cy=20):
    x = np.array(res[key]["x"]); y = np.array(res[key]["y"]); v = np.array(res[key]["val"])
    if len(v) == 0:
        return dict(flux=0.0, peak=0.0, n=0)
    total_flux = float(v.sum())
    # pico de irradiancia: binning fino y máximo cerca del eje
    r = np.hypot(x - cx, y - cy)
    # Pico robusto: irradiancia media en el disco central (r<0.75 m ~ medio COB).
    # Media sobre área -> estable frente al ruido de conteo, a diferencia del
    # máximo de una sola celda.
    core = r < 0.75
    peak = float(v[core].sum() / (np.pi * 0.75 ** 2)) if core.any() else 0.0
    return dict(flux=total_flux, peak=peak, n=int(len(v)))


def main():
    with open(LAMP_PATH, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    np.random.seed(0)
    eng_p = SimulationEngine(); eng_p.load_file(LAMP, content)
    res_p = eng_p.run(base_config("point"))

    np.random.seed(0)
    eng_a = SimulationEngine(); eng_a.load_file(LAMP, content)
    res_a = eng_a.run(base_config("area"))

    print(f"Lámpara: {LAMP} | COB {COB_L} m | rayos {RAYS}")
    print(f"{'':10s}{'PUNTO':>28s}{'ÁREA':>28s}")
    for key, label in [(str(NEAR), f"CERCA ({NEAR-Z_LAMP:.1f} m)"),
                       (str(FAR),  f"LEJOS ({FAR-Z_LAMP:.1f} m)")]:
        sp = plane_stats(res_p, key); sa = plane_stats(res_a, key)
        print(f"\n{label}")
        print(f"  flujo total [W]  {sp['flux']:>12.3f}{sa['flux']:>28.3f}   Δ={100*(sa['flux']-sp['flux'])/max(sp['flux'],1e-9):+.2f}%")
        print(f"  pico E [W/m^2]   {sp['peak']:>12.3f}{sa['peak']:>28.3f}   Δ={100*(sa['peak']-sp['peak'])/max(sp['peak'],1e-9):+.2f}%")

    # --- Asserts de verificación ---
    near_p, near_a = plane_stats(res_p, str(NEAR)), plane_stats(res_a, str(NEAR))
    far_p, far_a = plane_stats(res_p, str(FAR)), plane_stats(res_a, str(FAR))

    print("\n=== CHEQUEOS ===")
    # 1. flujo conservado en ambos planos (< 3% por ruido MC)
    for nm, a, b in [("cerca", near_p['flux'], near_a['flux']), ("lejos", far_p['flux'], far_a['flux'])]:
        d = abs(b - a) / max(a, 1e-9)
        print(f"[{'OK' if d < 0.03 else 'FAIL'}] flujo conservado {nm}: Δ={100*d:.2f}%")
    # 2. campo lejano converge dentro del ruido MC (pico difiere < 12%) y la
    #    diferencia es mucho menor que en campo cercano (convergencia clara).
    dfar = abs(far_a['peak'] - far_p['peak']) / max(far_p['peak'], 1e-9)
    dnear_pk = abs(near_a['peak'] - near_p['peak']) / max(near_p['peak'], 1e-9)
    ok_far = dfar < 0.12 and dfar < 0.5 * dnear_pk
    print(f"[{'OK' if ok_far else 'FAIL'}] campo lejano converge: Δpico={100*dfar:.2f}% (cercano {100*dnear_pk:.2f}%)")
    # 3. campo cercano: el área reduce el pico de forma apreciable (> 15%)
    dnear = (near_p['peak'] - near_a['peak']) / max(near_p['peak'], 1e-9)
    print(f"[{'OK' if dnear > 0.15 else 'FAIL'}] campo cercano suaviza pico: -{100*dnear:.2f}%")


if __name__ == "__main__":
    main()
