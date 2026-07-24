"""
Inferencia conjunta atacando el piso de desajuste.

Marginaliza dos fuentes de incertidumbre de la MEDICION, ademas de la bio-optica:
  - Posicion del sensor: prior gaussiano N(0, sigma_xy) horizontal y N(0, sigma_z)
    en profundidad; se integra sobre el stencil de vecindad guardado por attack_sweep.
    La irradiancia esperada bajo el prior de posicion es el promedio LINEAL ponderado
    del campo en la vecindad.
  - Inclinacion del sensor plano (respuesta coseno): un cabeceo aleatorio beta ~ N(0,
    sigma_tilt) introduce ruido MULTIPLICATIVO cuya magnitud relativa escala con tan(theta),
    donde theta es el angulo cenital de incidencia (derivado de la geometria lampara->punto).
    Entra como varianza de observacion heteroscedastica: puntos con luz oblicua (lejos de
    lamparas) pesan menos.

Se barre (sigma_xy, sigma_tilt) y se obtiene el posterior de (c550, omega, eta, dz)
marginalizando todo, mas una estimacion de la propia sigma_xy (cuan mal ubicado estuvo
el sensor). Compara R2 baseline vs con posicion vs con posicion+inclinacion.
"""
import os
import glob
import numpy as np

from meas_parser import load_measurements
from sim_interface import LAMP_XY, LAMP_Z_NOMINAL

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
_OUT = os.path.join(_HERE, "out")
_ATK = os.path.join(_OUT, os.environ.get("ATK_SUBDIR", "attack"))
_MEAS = os.environ.get("MEAS_SUBDIR", "puntaiglesiaa")
USE_BANDS = ["blue", "green"]
OUTLIER_PT = (10.0, 10.0, 8.0)
S_DISC = 0.15            # ruido base de medicion/discrepancia en log10 (factor ~1.4)
LN10 = np.log(10.0)
CAL_NAMES = ["c550", "omega", "eta", "dz"]


def load_sweep():
    cand = np.load(os.path.join(_ATK, "candidates.npz"), allow_pickle=True)
    offsets = cand["offsets"]                     # [Noff,2]
    z_planes = cand["z_planes"]                   # [3]
    pts = cand["pts"]                             # [npts,3]
    files = sorted(glob.glob(os.path.join(_ATK, "chunk_*.npz"))) + \
            sorted(glob.glob(os.path.join(_ATK, "ref_*.npz")))
    params, Ys = [], []
    for f in files:
        d = np.load(f)
        params.append(d["params"]); Ys.append(d["Y"])
    return (np.array(params), np.stack(Ys).astype(np.float32),
            offsets, z_planes, pts)


def zenith_tan(pts):
    """tan(theta) de incidencia por punto: distancia horiz. a la lampara mas cercana /
    caida vertical. Cap a 4 para evitar divergencia."""
    lamp = np.array(LAMP_XY, dtype=float)
    out = []
    for (x, y, z) in pts:
        dh = np.min(np.hypot(lamp[:, 0] - x, lamp[:, 1] - y))
        dz = max(z - LAMP_Z_NOMINAL, 1.0)
        out.append(min(dh / dz, 4.0))
    return np.array(out)


def _importance_weights(params):
    """Correccion MIS: prior uniforme / propuesta-mezcla (uniforme 300 + refine Normal).
    Los primeros len-n_ref son uniformes (chunk_), los ultimos n_ref son refine (ref_)."""
    from sim_interface import LAMP_XY  # noqa
    bounds = np.array([[0.10, 1.50], [0.50, 0.97], [-1.50, 2.50], [-1.50, 2.00]])
    vol = float(np.prod(bounds[:, 1] - bounds[:, 0]))
    n_ref = len(glob.glob(os.path.join(_ATK, "ref_*.npz")))
    n_uni = len(params) - n_ref
    if n_ref == 0:
        return np.ones(len(params))
    mu = np.array([float(v) for v in os.environ.get("REF_MU", "1.23,0.71,0.19,0.32").split(",")])
    sd = np.array([float(v) for v in os.environ.get("REF_SD", "0.30,0.12,0.70,0.90").split(",")])
    q_uni = np.full(len(params), 1.0 / vol)
    q_ref = np.prod(np.exp(-0.5 * ((params - mu) / sd) ** 2) / (np.sqrt(2*np.pi) * sd), axis=1)
    m = (n_uni * q_uni + n_ref * q_ref) / (n_uni + n_ref)
    return (1.0 / vol) / np.maximum(m, 1e-300)


def main():
    params, Y, offsets, z_planes, pts = load_sweep()
    n_design, npts, nband, nz, noff = Y.shape
    iw = _importance_weights(params)
    log_iw = np.log(iw)
    print(f"cargadas {n_design} corridas | Y{Y.shape} | {noff} offsets, {nz} planos z")

    recs = load_measurements(os.path.join(_ROOT, "measurements", _MEAS))
    excl_xge = float(os.environ.get("EXCLUDE_XGE", "999"))  # excluir puntos con x >= umbral
    n_excl = 0
    # log10 meas por punto/banda + mascara de uso
    logmeas = np.full((npts, nband), np.nan)
    use = np.zeros((npts, nband), bool)
    for i, r in enumerate(recs):
        if r["censored"] or (r["x"], r["y"], r["z"]) == OUTLIER_PT:
            continue
        if r["x"] >= excl_xge:
            n_excl += 1
            continue
        for bi, b in enumerate(USE_BANDS):
            m = r[f"band_{b}"]
            if m > 0:
                logmeas[i, bi] = np.log10(m); use[i, bi] = True
    lm = logmeas[use]                              # vector de mediciones usadas
    print(f"{use.sum()} residuos (azul+verde, sin censura ni outlier)")

    dist_h = np.hypot(offsets[:, 0], offsets[:, 1])   # [noff]
    dz_plane = z_planes[None, :] - pts[:, 2][:, None] # [npts,nz]
    tan_th = zenith_tan(pts)                           # [npts]

    # Candidatos por residuo usado: aplanar (nz,noff) -> ncand, seleccionar (punto,banda) usados.
    ncand = nz * noff
    Yflat = Y.reshape(n_design, npts, nband, ncand)          # [nd,npts,nb,ncand]
    dh2 = (dist_h**2)                                        # [noff]
    dz2_cand = np.repeat(dz_plane**2, noff, axis=1)          # [npts, ncand]

    # --- Modelo a NIVEL DE PUNTO: azul y verde comparten la misma posicion latente ---
    both = use[:, 0] & use[:, 1]                             # puntos con ambas bandas
    P = np.where(both)[0]                                    # [n_pt]
    n_pt = len(P)
    Ypt = Yflat[:, P, :, :]                                  # [nd, n_pt, 2, ncand]
    lm_pt = logmeas[P, :]                                    # [n_pt, 2]
    tan_pt = tan_th[P]                                       # [n_pt]
    dz2_pt = dz2_cand[P, :]                                  # [n_pt, ncand]
    lm_flat = lm_pt.reshape(-1)                              # para R2 global (2*n_pt)
    print(f"modelo a nivel de punto: {n_pt} puntos (azul+verde con posicion comun)")

    # Las grillas se pueden ampliar por entorno para diagnosticar si la evidencia
    # queda truncada en un borde (p. ej. TILT_GRID=0,10,20,30,45,60).
    SIG_XY = [float(v) for v in os.environ.get(
        "POS_GRID", "0.3,0.5,1.0,1.5,2.0,2.5").split(",")]
    SIG_TILT = [float(v) for v in os.environ.get(
        "TILT_GRID", "0,10,20,30").split(",")]     # grados
    SIG_Z = float(os.environ.get("SIG_Z", "1.0"))
    O_GRID = np.linspace(-3.5, 0.5, 41)    # offset de potencia (log10) a perfilar
    tile_h = np.tile(np.exp(-0.5 * dh2), 1)                  # placeholder

    print(f"\n{'sigma_xy':>9}{'sigma_tilt':>11}{'R2fix':>8}{'R2pos':>8}{'R2xval':>8}{'RMSE':>8}{'logZ':>10}")
    results = []
    for sxy in SIG_XY:
        wh = np.exp(-0.5 * dh2 / sxy**2)                     # [noff]
        wpos = np.exp(-0.5 * dz2_pt / SIG_Z**2) * np.tile(wh, nz)[None, :]  # [n_pt,ncand]
        wpos = wpos / wpos.sum(axis=1, keepdims=True)
        for stilt in SIG_TILT:
            s_t = (1.0 / LN10) * np.sqrt(0.5) * tan_pt * np.radians(stilt)  # [n_pt]
            s2 = S_DISC**2 + s_t**2                          # [n_pt] (misma para ambas bandas)
            s2b = s2[None, :, None, None]                    # broadcast a [.,n_pt,band,cand]
            best_ll = np.full(n_design, -np.inf); best_O = np.zeros(n_design)
            for O in O_GRID:
                diff = lm_pt[None, :, :, None] - (Ypt + O)   # [nd,n_pt,2,ncand]
                logg = -0.5 * diff**2 / s2b - 0.5*np.log(2*np.pi*s2b)
                gb = np.exp(logg.sum(axis=2))                # producto sobre banda -> [nd,n_pt,ncand]
                mix = np.sum(wpos[None, :, :] * gb, axis=2)  # [nd,n_pt]
                ll = np.sum(np.log(mix + 1e-300), axis=1)
                upd = ll > best_ll; best_ll[upd] = ll[upd]; best_O[upd] = O
            ll = best_ll + log_iw            # correccion de importancia (MIS)
            w = np.exp(ll - ll.max()); w /= w.sum()
            logZ = ll.max() + np.log(np.mean(np.exp(ll - ll.max())))

            # posicion posterior (informada por AMBAS bandas) con O perfilado
            diff = lm_pt[None, :, :, None] - (Ypt + best_O[:, None, None, None])
            gb = np.exp((-0.5*diff**2/s2b).sum(axis=2))      # [nd,n_pt,ncand]
            postp = wpos[None, :, :] * gb
            postp = postp / (postp.sum(axis=2, keepdims=True) + 1e-300)
            pred = np.sum(postp[:, :, None, :] * (Ypt + best_O[:, None, None, None]), axis=3)  # [nd,n_pt,2]
            resid = lm_pt[None, :, :] - pred
            rpm = np.sum(w[:, None, None] * resid, axis=0).reshape(-1)
            r2pos = 1 - np.sum(rpm**2)/np.sum((lm_flat-lm_flat.mean())**2)
            rmse = np.sqrt(np.mean(rpm**2))

            # (a) R2 posicion fija (candidato central)
            zsel = np.argmin(np.abs(dz_plane[P]), axis=1)
            center = zsel * noff + np.argmin(dh2)            # [n_pt]
            idxc = np.broadcast_to(center[None, :, None, None], (n_design, n_pt, 2, 1))
            Yfix = np.take_along_axis(Ypt, idxc, axis=3)[..., 0]   # [nd,n_pt,2]
            Ofix = np.median((lm_pt[None]-Yfix).reshape(n_design,-1),axis=1)
            residf = lm_pt[None]-(Yfix+Ofix[:,None,None])
            wf = np.exp(-0.5*np.sum((residf**2).reshape(n_design,-1)/S_DISC**2,axis=1)); wf/=wf.sum()
            rpmf = np.sum(wf[:,None,None]*residf,axis=0).reshape(-1)
            r2fix = 1-np.sum(rpmf**2)/np.sum((lm_flat-lm_flat.mean())**2)

            # (b) VALIDACION CRUZADA: posicion inferida SOLO con azul, predice verde
            diffB = lm_pt[None,:,0,None]-(Ypt[:,:,0,:]+best_O[:,None,None])
            gB = np.exp(-0.5*diffB**2/s2[None,:,None])
            postB = wpos[None,:,:]*gB; postB/= (postB.sum(2,keepdims=True)+1e-300)
            predG = np.sum(postB*(Ypt[:,:,1,:]+best_O[:,None,None]),axis=2)  # verde en pos de azul
            residG = lm_pt[None,:,1]-predG
            rpmG = np.sum(w[:,None]*residG,axis=0)
            r2xval = 1-np.sum(rpmG**2)/np.sum((lm_pt[:,1]-lm_pt[:,1].mean())**2)

            results.append(dict(sxy=sxy, stilt=stilt, ll=ll, w=w, logZ=logZ,
                                r2=r2pos, r2fix=r2fix, r2xval=r2xval, rmse=rmse))
            print(f"{sxy:>9}{stilt:>11}{r2fix:>8.3f}{r2pos:>8.3f}{r2xval:>8.3f}{rmse:>8.3f}{logZ:>10.1f}")

    # baseline exacto (sigma muy chico, sin tilt) ya esta en sxy=0.3,stilt=0
    # --- Posterior conjunto marginalizando hiperparametros por evidencia logZ ---
    logZs = np.array([r["logZ"] for r in results])
    hw = np.exp(logZs - logZs.max()); hw /= hw.sum()
    post_w = np.zeros(n_design)
    for r, hwi in zip(results, hw):
        post_w += hwi * r["w"]
    post_w /= post_w.sum()

    best = max(results, key=lambda r: r["logZ"])
    print(f"\nMejor evidencia: sigma_xy={best['sxy']} m, sigma_tilt={best['stilt']}deg "
          f"-> R2={best['r2']:.3f}, RMSE={best['rmse']:.3f}")
    # posterior marginal de sigma_xy
    sxy_post = {}
    for r, hwi in zip(results, hw):
        sxy_post[r["sxy"]] = sxy_post.get(r["sxy"], 0) + hwi
    print("Posterior de sigma_xy (m):", {k: round(v, 2) for k, v in sxy_post.items()})
    stilt_post = {}
    for r, hwi in zip(results, hw):
        stilt_post[r["stilt"]] = stilt_post.get(r["stilt"], 0) + hwi
    print("Posterior de sigma_tilt (deg):", {k: round(v, 2) for k, v in stilt_post.items()})

    _summary(params, post_w)
    np.savez(os.path.join(_OUT, "attack_posterior.npz"),
             params=params, w=post_w, cal_names=CAL_NAMES,
             sxy_post=np.array(list(sxy_post.items())),
             stilt_post=np.array(list(stilt_post.items())))
    _figures(params, post_w, results, SIG_XY, SIG_TILT, sxy_post)
    return params, post_w, results


def _wq(x, w, qs):
    o = np.argsort(x); x, w = x[o], w[o]
    cw = np.cumsum(w) - 0.5 * w; cw /= w.sum()
    return np.interp(qs, cw, x)


def _summary(params, w):
    ess = w.sum()**2 / np.sum(w**2)
    print(f"\n=== Posterior conjunto (marg. posicion+inclinacion)  ESS={ess:.0f} ===")
    d = {"c550": params[:, 0], "omega": params[:, 1], "eta": params[:, 2], "dz": params[:, 3],
         "a550": params[:, 0]*(1-params[:, 1]), "b550": params[:, 0]*params[:, 1]}
    for k, v in d.items():
        lo, med, hi = _wq(v, w, [0.05, 0.5, 0.95])
        print(f"  {k:<6} med={med:7.3f}  90%CI=[{lo:7.3f}, {hi:7.3f}]")


def _figures(params, w, results, SIG_XY, SIG_TILT, sxy_post):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # R2 vs sigma_xy: in-sample (r2pos) vs validado cruzado (r2xval), tilt=0
    fig, ax = plt.subplots(figsize=(8.5, 5.2))
    r0 = [r for r in results if r["stilt"] == 0.0]
    xs = [r["sxy"] for r in r0]
    ax.plot(xs, [r["r2"] for r in r0], "o-", color="#8FAADC",
            label="R² in-sample (posición informada por dato)")
    ax.plot(xs, [r["r2xval"] for r in r0], "s-", color="#2E75B6", lw=2.4,
            label="R² validación cruzada (azul→verde) — honesto")
    ax.axhline(0.452, color="#C00000", ls="--", label="posición nominal fija (R²=0.45)")
    ax.axhline(0.42, color="grey", ls=":", label="piso previo Fase 2 (R²=0.42)")
    ax.set_xlabel("σ incertidumbre de posición del sensor [m]")
    ax.set_ylabel("R² (log, banda azul+verde)")
    ax.set_title("Atacar el piso: modelar la posición del sensor recupera el ajuste")
    ax.set_ylim(0.3, 1.0); ax.legend(fontsize=9); ax.grid(ls=":", alpha=0.5)
    fig.tight_layout(); fig.savefig(os.path.join(_OUT, "attack_r2.png"), dpi=130)
    plt.close(fig)

    # Posterior a,b marginal
    d = {"a550": params[:, 0]*(1-params[:, 1]), "b550": params[:, 0]*params[:, 1],
         "omega": params[:, 1], "c550": params[:, 0]}
    fig, axes = plt.subplots(1, 4, figsize=(15, 3.6))
    for ax, (k, v) in zip(axes, d.items()):
        ax.hist(v, bins=28, weights=w, density=True, color="#2E75B6", alpha=0.85)
        lo, med, hi = _wq(v, w, [0.05, 0.5, 0.95])
        for xl, ls in [(med, "-"), (lo, "--"), (hi, "--")]:
            ax.axvline(xl, color="#C00000", ls=ls, lw=1.2)
        ax.set_title(k); ax.set_yticks([])
    fig.suptitle("Posterior tras marginalizar posición e inclinación del sensor",
                 color="#1F3864", weight="bold")
    fig.tight_layout(rect=[0, 0, 1, 0.94])
    fig.savefig(os.path.join(_OUT, "attack_posterior.png"), dpi=130)
    plt.close(fig)
    print("Figuras: attack_r2.png, attack_posterior.png")


if __name__ == "__main__":
    main()
