"""
Interfaz programatica al SimulationEngine para el screening de sensibilidad.

Construye una config de jaula de Punta Iglesia a partir de un vector de parametros
(las fuentes de incertidumbre), corre el ray tracer y extrae la irradiancia por
banda espectral en los puntos de sensor (x,y,z) que coinciden con las mediciones.

Fuentes de incertidumbre parametrizadas (vector theta):
    f_power    : factor global de potencia radiante de las lamparas   [-]
    dz         : desplazamiento comun de altura de las lamparas        [m]
    pos_jitter : magnitud del desplazamiento horizontal de lamparas    [m]
    c550       : atenuacion de haz c=a+b a 550 nm                       [1/m]
    omega      : albedo de dispersion simple  b/(a+b)                   [-]
    eta        : pendiente espectral  c(λ)=c550*(λ/550)^(-eta)          [-]

Las tres primeras cubren "agencia radiante", posicion y altura de las lamparas.
Las tres ultimas cubren los parametros bio-opticos desconocidos (magnitud a+b,
reparto absorcion/dispersion, y tilt espectral) del ray tracing escalar.
"""
import os
import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)

import sys
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from simulation_engine import SimulationEngine  # noqa: E402

from meas_parser import BANDS  # noqa: E402

# --- Geometria por sitio (seleccionable con env SITE) ------------------------
LAMP_XML = "TEMPEST 600W.xml"
SITE = os.environ.get("SITE", "puntaiglesia")
if SITE == "hueihue":
    # Jaula 50x50; 8 lamparas de 650 W, todas a 3 m. Profundidades medidas {8,10}.
    NOMINAL_POWER = 650.0
    CAGE = dict(type="jaula", radio=None, x=50, y=50, z=40, z_interface=0, n1=1, n2=1.33)
    LAMP_XY = [(12.5, 12.5), (37.5, 12.5), (12.5, 25), (37.5, 25),
               (12.5, 37.5), (37.5, 37.5), (25, 16.5), (25, 33.5)]
    LAMP_Z_NOMINAL = 3.0
    TARGET_DEPTHS = [8, 10]
else:  # Punta Iglesia (por defecto)
    NOMINAL_POWER = 600.0
    CAGE = dict(type="jaula", radio=None, x=40, y=40, z=20, z_interface=0, n1=1, n2=1.33)
    LAMP_XY = [(12, 10), (28, 10), (12, 20), (28, 20), (12, 30), (28, 30)]
    LAMP_Z_NOMINAL = 3.0
    TARGET_DEPTHS = [8, 10, 12]

# Malla de extraccion (irradiancia = flujo por area de celda).
_CELL = 1.0
_GRID_X = np.arange(0.0, CAGE["x"] + _CELL, _CELL)
_GRID_Y = np.arange(0.0, CAGE["y"] + _CELL, _CELL)
_XC = 0.5 * (_GRID_X[:-1] + _GRID_X[1:])
_YC = 0.5 * (_GRID_Y[:-1] + _GRID_Y[1:])
_AREA = _CELL * _CELL

# Direcciones fijas (seeded) del jitter posicional por lampara: hace que
# pos_jitter sea un factor escalar reproducible y monotono.
_JIT_RNG = np.random.default_rng(12345)
_JIT_DIRS = _JIT_RNG.uniform(-1, 1, size=(len(LAMP_XY), 2))
_JIT_DIRS /= np.linalg.norm(_JIT_DIRS, axis=1, keepdims=True)

PARAM_NAMES = ["f_power", "dz", "pos_jitter", "c550", "omega", "eta"]

# Rango (prior uniforme) por defecto para cada fuente.
DEFAULT_BOUNDS = {
    "f_power":    (0.7, 1.3),      # +-30% de la potencia nominal
    "dz":         (-1.0, 1.5),     # altura de lampara +-1..1.5 m
    "pos_jitter": (0.0, 2.0),      # hasta 2 m de error de posicion
    "c550":       (0.15, 1.2),     # aguas claras -> turbias
    "omega":      (0.55, 0.95),    # dominado por absorcion -> por dispersion
    "eta":        (-1.5, 2.0),     # tilt espectral (azul<->rojo)
}


class SimRunner:
    """Envuelve el engine: parser cargado una vez, corridas por vector theta."""

    def __init__(self, rays=20000, seed=0):
        self.rays = int(rays)
        self.seed = seed
        self.eng = SimulationEngine()
        with open(os.path.join(_ROOT, "uploaded_lamps", LAMP_XML)) as fh:
            self.eng.load_file(LAMP_XML, fh.read())

    def build_config(self, theta):
        f_power, dz, pos_jitter, c550, omega, eta = theta
        lamps = []
        for i, (x, y) in enumerate(LAMP_XY):
            dx, dy = _JIT_DIRS[i] * pos_jitter
            lamps.append(dict(
                xml=LAMP_XML,
                x=float(x + dx), y=float(y + dy),
                z=float(LAMP_Z_NOMINAL + dz),
                power=float(NOMINAL_POWER * f_power),
                dim=1, rot_x=0, rot_y=0, rot_z=0,
            ))
        # c(λ) espectral en nodos; omega constante.
        wls = [450.0, 500.0, 550.0, 600.0, 650.0]
        c_json = {str(w): float(max(c550 * (w / 550.0) ** (-eta), 1e-4)) for w in wls}
        omega_json = {"550": float(np.clip(omega, 0.01, 0.98))}
        return dict(
            env=dict(CAGE), lamps=lamps, target_depths=TARGET_DEPTHS,
            rays=self.rays, irradiance_type="downwelling",
            optics=dict(mode="scattering", mc_input_type="json",
                        c_json=c_json, omega_json=omega_json),
        )

    def build_config_ab(self, theta):
        """Parametrizacion alternativa: pendientes espectrales INDEPENDIENTES para a y b.
            a(λ) = a550·(λ/550)^(−eta_a)   (absorcion)
            b(λ) = b550·(λ/550)^(−eta_b)   (dispersion)
            c(λ) = a(λ)+b(λ),  omega(λ) = b(λ)/c(λ)   (ambos espectrales)
        theta = [a550, b550, eta_a, eta_b, dz]."""
        a550, b550, eta_a, eta_b, dz = theta
        lamps = []
        for (x, y) in LAMP_XY:
            lamps.append(dict(
                xml=LAMP_XML, x=float(x), y=float(y),
                z=float(LAMP_Z_NOMINAL + dz), power=NOMINAL_POWER,
                dim=1, rot_x=0, rot_y=0, rot_z=0,
            ))
        wls = [450.0, 500.0, 550.0, 600.0, 650.0]
        c_json, omega_json = {}, {}
        for w in wls:
            a = max(a550 * (w / 550.0) ** (-eta_a), 1e-5)
            b = max(b550 * (w / 550.0) ** (-eta_b), 1e-5)
            c = a + b
            c_json[str(w)] = float(c)
            omega_json[str(w)] = float(np.clip(b / c, 0.01, 0.98))
        return dict(
            env=dict(CAGE), lamps=lamps, target_depths=TARGET_DEPTHS,
            rays=self.rays, irradiance_type="downwelling",
            optics=dict(mode="scattering", mc_input_type="json",
                        c_json=c_json, omega_json=omega_json),
        )

    def _band_grids(self, res, depth):
        """Devuelve dict banda->interpolador RegularGridInterpolator de E(x,y)."""
        from scipy.interpolate import RegularGridInterpolator
        r = res[str(depth)]
        x = np.asarray(r["x"]); y = np.asarray(r["y"])
        val = np.asarray(r["val"]); wl = np.asarray(r["wl"])
        interps = {}
        for name, (lo, hi) in BANDS.items():
            m = (wl >= lo) & (wl < hi)
            if m.sum() == 0:
                interps[name] = None
                continue
            H, _, _ = np.histogram2d(x[m], y[m], bins=[_GRID_X, _GRID_Y],
                                     weights=val[m])
            E = H / _AREA  # W/m2, orientacion (x, y)
            interps[name] = RegularGridInterpolator(
                (_XC, _YC), E, bounds_error=False, fill_value=0.0)
        return interps

    def run(self, theta, sensor_points):
        """theta -> dict {(x,y,z): {band: E_sim [W/m2]}} en los puntos dados."""
        if self.seed is not None:
            np.random.seed(self.seed)
        cfg = self.build_config(theta)
        res = self.eng.run(cfg)
        # Precalcula interpoladores por profundidad.
        interp_by_depth = {d: self._band_grids(res, d) for d in TARGET_DEPTHS}
        out = {}
        for (sx, sy, sz) in sensor_points:
            d = min(TARGET_DEPTHS, key=lambda dd: abs(dd - sz))
            interps = interp_by_depth[d]
            bands = {}
            for name, itp in interps.items():
                bands[name] = 0.0 if itp is None else float(itp((sx, sy)))
            out[(sx, sy, sz)] = bands
        return out


if __name__ == "__main__":
    from meas_parser import load_measurements
    recs = load_measurements(os.path.join(_ROOT, "measurements", "puntaiglesiaa"))
    pts = [(r["x"], r["y"], r["z"]) for r in recs]
    runner = SimRunner(rays=20000)
    theta0 = [1.0, 0.0, 0.0, 0.4, 0.8, 1.0]
    import time
    t = time.time()
    sim = runner.run(theta0, pts)
    print(f"corrida nominal en {time.time()-t:.2f}s, {len(sim)} puntos")
    print(f"{'x':>3}{'y':>4}{'z':>4} {'blue_sim':>10} {'green_sim':>10} {'red_sim':>10}")
    for p in sorted(sim)[:8]:
        b = sim[p]
        print(f"{p[0]:>3.0f}{p[1]:>4.0f}{p[2]:>4.0f} "
              f"{b['blue']:>10.4f} {b['green']:>10.4f} {b['red']:>10.4f}")
