import numpy as np
from scipy.interpolate import RegularGridInterpolator, make_interp_spline
from parsers import TM33Parser, IESParser

try:
    trapz_func = np.trapezoid
except AttributeError:
    trapz_func = np.trapz


# =============================================================================
#  FUNCIONES AUXILIARES DE ÓPTICA Y MUESTREO
# =============================================================================

def fresnel_transmission(n1, n2, cos_theta_i, cos_theta_t):
    """Transmitancia Fresnel no polarizada T = 1 - (Rs + Rp)/2.
    Convención: n1 = medio incidente, n2 = medio de transmisión."""
    rs = ((n1 * cos_theta_i - n2 * cos_theta_t) / (n1 * cos_theta_i + n2 * cos_theta_t))**2
    rp = ((n1 * cos_theta_t - n2 * cos_theta_i) / (n1 * cos_theta_t + n2 * cos_theta_i))**2
    return 1.0 - 0.5 * (rs + rp)


def normalize(v):
    norm = np.linalg.norm(v, axis=1, keepdims=True)
    return v / (norm + 1e-16)


def rotate_3d(vectors, rx_deg, ry_deg, rz_deg):
    rx = np.radians(rx_deg)
    ry = np.radians(ry_deg)
    rz = np.radians(rz_deg)

    cx, sx = np.cos(rx), np.sin(rx)
    Rx = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])

    cy, sy = np.cos(ry), np.sin(ry)
    Ry = np.array([[cy, 0, sy], [0, 1, 0], [-sy, 0, cy]])

    cz, sz = np.cos(rz), np.sin(rz)
    Rz = np.array([[cz, -sz, 0], [sz, cz, 0], [0, 0, 1]])

    R = Rz @ Ry @ Rx
    return vectors @ R.T


def _orthonormal_basis(W):
    """Construye una base ortonormal (U, V, W) dado W unitario."""
    A = np.where(np.abs(W[:, 0:1]) > 0.9, np.array([0., 1., 0.]), np.array([1., 0., 0.]))
    U = normalize(np.cross(A, W))
    V = np.cross(W, U)
    return U, V


def sample_henyey_greenstein(D, g):
    """Muestreo del fasor Henyey-Greenstein con asimetría g."""
    N = len(D)
    xi1 = np.random.rand(N)
    xi2 = np.random.rand(N)

    if g == 0:
        cos_theta = 1.0 - 2.0 * xi1
    else:
        sqr_term = (1.0 - g**2) / (1.0 - g + 2.0 * g * xi1)
        cos_theta = (1.0 + g**2 - sqr_term**2) / (2.0 * g)

    sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta**2))
    phi = 2.0 * np.pi * xi2

    W = normalize(D)
    U, V = _orthonormal_basis(W)

    D_new = (U * (sin_theta * np.cos(phi))[:, np.newaxis] +
             V * (sin_theta * np.sin(phi))[:, np.newaxis] +
             W * cos_theta[:, np.newaxis])
    return normalize(D_new)


# -----------------------------------------------------------------------------
#  Fase de Fournier-Forand (alternativa de mayor fidelidad a Henyey-Greenstein)
# -----------------------------------------------------------------------------

def fournier_forand_phase(theta, n, mu):
    """Función de fase de Fournier-Forand (1994), normalizada a ∫p dΩ = 1.
        n  : índice de refracción real de las partículas (rel. al agua), ~1.05–1.20
        mu : pendiente de Junge de la distribución de tamaños, ~3.0–4.5
    Reproduce el lóbulo forward agudo y el de retrodispersión mucho mejor que HG."""
    nu = (3.0 - mu) / 2.0
    s = np.sin(theta / 2.0)
    d = (4.0 / (3.0 * (n - 1.0) ** 2)) * s ** 2
    d180 = 4.0 / (3.0 * (n - 1.0) ** 2)
    t1 = 1.0 / (4.0 * np.pi * (1.0 - d) ** 2 * d ** nu) * (
        nu * (1.0 - d) - (1.0 - d ** nu)
        + (d * (1.0 - d ** nu) - nu * (1.0 - d)) / (s ** 2))
    t2 = (1.0 - d180 ** nu) / (16.0 * np.pi * (d180 - 1.0) * d180 ** nu) * (
        3.0 * np.cos(theta) ** 2 - 1.0)
    return t1 + t2


def ff_backscatter_fraction(n, mu):
    """Fracción de retrodispersión b_b/b de la fase de Fournier-Forand,
    integral analítica de 90° a 180° (Mobley, Light and Water)."""
    nu = (3.0 - mu) / 2.0
    d90 = 2.0 / (3.0 * (n - 1.0) ** 2)
    return 1.0 - (1.0 - d90 ** (nu + 1.0) - 0.5 * (1.0 - d90 ** nu)) / (
        (1.0 - d90) * d90 ** nu)


def ff_n_from_backscatter(bb_ratio, mu=3.5, lo=1.001, hi=1.35):
    """Resuelve por bisección el índice n que da una fracción de retrodispersión
    b_b/b objetivo, a pendiente de Junge mu fija. Desacopla b_b de la asimetría."""
    bb_ratio = float(np.clip(bb_ratio, 1e-4, 0.45))
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if ff_backscatter_fraction(mid, mu) < bb_ratio:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def build_ff_inverse_cdf(n, mu, ngrid=6000):
    """Construye la CDF inversa angular de la fase FF (densa en el pico forward)
    para muestreo por inversión. Devuelve (cdf, theta)."""
    th = np.concatenate([
        np.linspace(1e-4, 0.2, ngrid // 2, endpoint=False),
        np.linspace(0.2, np.pi, ngrid - ngrid // 2)])
    pdf = np.maximum(fournier_forand_phase(th, n, mu) * np.sin(th), 0.0)
    cdf = np.concatenate([[0.0], np.cumsum(0.5 * (pdf[1:] + pdf[:-1]) * np.diff(th))])
    total = cdf[-1]
    if total <= 0:
        return np.array([0.0, 1.0]), np.array([0.0, np.pi])
    return cdf / total, th


def sample_fournier_forand(D, ff_inv_cdf):
    """Muestrea nuevas direcciones desde la fase FF usando su CDF inversa
    precalculada. Espejo de sample_henyey_greenstein."""
    cdf, th_grid = ff_inv_cdf
    N = len(D)
    xi1 = np.random.rand(N)
    xi2 = np.random.rand(N)
    cos_theta = np.cos(np.interp(xi1, cdf, th_grid))
    sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta ** 2))
    phi = 2.0 * np.pi * xi2

    W = normalize(D)
    U, V = _orthonormal_basis(W)
    D_new = (U * (sin_theta * np.cos(phi))[:, np.newaxis] +
             V * (sin_theta * np.sin(phi))[:, np.newaxis] +
             W * cos_theta[:, np.newaxis])
    return normalize(D_new)


def sample_lambertian(N_normal):
    """Muestreo cos-ponderado en el hemisferio orientado por N_normal (Lambertiano)."""
    n_rays = len(N_normal)
    xi1 = np.random.rand(n_rays)
    xi2 = np.random.rand(n_rays)

    cos_theta = np.sqrt(xi1)
    sin_theta = np.sqrt(np.maximum(0.0, 1.0 - xi1))
    phi = 2.0 * np.pi * xi2

    W = normalize(N_normal)
    U, V = _orthonormal_basis(W)

    D_new = (U * (sin_theta * np.cos(phi))[:, np.newaxis] +
             V * (sin_theta * np.sin(phi))[:, np.newaxis] +
             W * cos_theta[:, np.newaxis])
    return normalize(D_new)


def sample_wavelength(wls, pwrs, n_samples):
    """Muestreo espectral con CDF trapezoidal (PDF lineal a trozos).
    Más correcto que cumsum cuando el grid de longitudes de onda no es uniforme."""
    if len(wls) < 2 or np.sum(pwrs) <= 0:
        wl0 = wls[0] if len(wls) > 0 else 500.0
        return np.full(n_samples, wl0)

    delta_wl = np.diff(wls)
    seg_area = 0.5 * (pwrs[:-1] + pwrs[1:]) * delta_wl
    total = np.sum(seg_area)
    if total <= 0:
        return np.full(n_samples, float(np.mean(wls)))

    cdf = np.concatenate([[0.0], np.cumsum(seg_area)]) / total
    xi = np.random.rand(n_samples)
    return np.interp(xi, cdf, wls)


# =============================================================================
#  MODELO BIO-ÓPTICO (4 componentes)
# =============================================================================
# Grid de referencia común
_WL_REF = np.array([400, 450, 500, 550, 600, 650, 700], dtype=float)

# Absorción del agua pura (Pope & Fry 1997 + Smith & Baker, redondeados) [1/m]
_AW_REF = np.array([0.018, 0.015, 0.026, 0.064, 0.245, 0.349, 0.624])

# Coeficiente específico de dispersión total por TSS [m²/g]
_BSTAR_REF = np.array([0.50, 0.42, 0.35, 0.31, 0.28, 0.25, 0.22])

# Absorción específica por clorofila-a [m²/(mg·m⁻³)] = [m²/mg]
# Promedio Bricaud et al. (1995/1998): picos en 440 (~0.038) y 675 (~0.022 cerca de 650)
_APHY_STAR_REF = np.array([0.022, 0.038, 0.012, 0.005, 0.005, 0.018, 0.008])


def bio_optical_iop(wls, tss=0.0, cdom_a440=0.0, chl=0.0, s_cdom=0.015):
    """Devuelve (a, b) por longitud de onda con modelo de 4 componentes:
    agua pura + CDOM + TSS + fitoplancton.
        tss: concentración de sólidos suspendidos [mg/L] ≡ [g/m³]
        cdom_a440: absorción CDOM a 440 nm [1/m]
        chl: clorofila-a [mg/m³]
        s_cdom: pendiente espectral del CDOM [1/nm] (típicamente 0.014–0.018)
    """
    aw = np.interp(wls, _WL_REF, _AW_REF)
    b_star = np.interp(wls, _WL_REF, _BSTAR_REF)
    aphy_star = np.interp(wls, _WL_REF, _APHY_STAR_REF)

    a_cdom = cdom_a440 * np.exp(-s_cdom * (wls - 440.0))
    a_phy = aphy_star * chl
    b_total = b_star * tss

    a_total = np.maximum(aw + a_cdom + a_phy, 0.0)
    b_total = np.maximum(b_total, 0.0)
    return a_total, b_total


# =============================================================================
#  MODELO BIO-ÓPTICO RAS (Bårdsnes 2020) — formas espectrales empíricas
# =============================================================================
# Formas espectrales medidas en agua de RAS sin desinfección (post-smolt de salmón
# Atlántico) por Bårdsnes (2020). A diferencia del modo marino, la atenuación en RAS
# CRECE hacia el AZUL (inverso al océano) por CDOM concentrado + micropartículas
# orgánicas finas. Resultados usados:
#   - Pendiente espectral particulada eta_p ≈ 1.8, ley de potencia (λ/550)^(−eta_p),
#     ajustada a la columna TSS de la Tabla 4.1 (más pronunciada que el ~1.5 marino:
#     las partículas de RAS son más finas).
#   - Pendiente de absorción CDOM S_cdom ≈ 0.0141 1/nm (ajuste 400–500 nm, columna DOC).
#   - Conversión turbidez→TSS: TSS = 3.0411·NTU − 0.376 (tanque, R²=0.86; Fig. 3.2A).
#
# La MAGNITUD absoluta bajo tanque/jaula NO es transferible desde el paper: la medición
# tiene re-entrada de luz por las paredes y el propio autor indica que la absorbancia
# "aparece menor que en la realidad". Por eso bstar_550 (atenuación específica) y omega_p
# (albedo de dispersión) quedan como parámetros CALIBRABLES por sistema; los defaults
# preservan continuidad de magnitud con el modo marino.
_RAS_ETA_P = 1.8            # pendiente espectral particulada (Bårdsnes 2020, Tabla 4.1)
_RAS_S_CDOM = 0.0141        # pendiente de absorción CDOM [1/nm] (Bårdsnes 2020, DOC 400-500)
_RAS_BSTAR_550 = 0.31       # atenuación específica particulada a 550 nm [m²/g] (calibrable)
_RAS_OMEGA_P = 0.90         # albedo de dispersión simple particulado (flóculos orgánicos)
_RAS_NTU_TO_TSS_SLOPE = 3.0411
_RAS_NTU_TO_TSS_INTERCEPT = -0.376

# Columna TSS de la Tabla 4.1 (absorbancia media, fase 1) normalizada a 550 nm.
# Se conserva como referencia de validación de la ley de potencia (no se usa en runtime).
_RAS_CP_SHAPE_REF = np.array([6.354, 5.080, 4.193, 3.554, 3.047, 2.614, 2.307]) / 3.554


def ras_tss_from_turbidity(turbidity_ntu,
                           slope=_RAS_NTU_TO_TSS_SLOPE,
                           intercept=_RAS_NTU_TO_TSS_INTERCEPT):
    """Convierte turbidez [NTU] a TSS [mg/L] con la regresión de Bårdsnes (2020) para
    agua de tanque RAS: TSS = 3.0411·NTU − 0.376 (R²=0.86). Devuelve un valor ≥ 0."""
    if turbidity_ntu is None:
        return None
    return max(float(slope) * float(turbidity_ntu) + float(intercept), 0.0)


def bio_optical_iop_ras_bardsnes(wls, tss=0.0, cdom_a440=0.0, chl=0.0,
                                 bstar_550=_RAS_BSTAR_550, omega_p=_RAS_OMEGA_P,
                                 eta_p=_RAS_ETA_P, s_cdom=_RAS_S_CDOM):
    """Devuelve (a, b) por longitud de onda para agua de RAS con las formas espectrales
    empíricas de Bårdsnes (2020). Estructura de 4 componentes con pendientes calibradas
    en RAS (atenuación creciente hacia el azul):

        c_p(λ)    = bstar_550 · TSS · (λ/550)^(−eta_p)     # atenuación particulada de haz
        b(λ)      = omega_p · c_p(λ)                        # dispersión particulada
        a_p(λ)    = (1 − omega_p) · c_p(λ)                  # absorción particulada
        a_cdom(λ) = cdom_a440 · exp[−s_cdom · (λ − 440)]    # CDOM (S_cdom RAS ≈ 0.0141)
        a(λ)      = a_agua(λ) + a_cdom(λ) + a_phy(λ) + a_p(λ)

    tss [mg/L], cdom_a440 [1/m], chl [mg/m³]. bstar_550 y omega_p son calibrables por
    sistema porque la magnitud absoluta bajo jaula no es transferible del paper."""
    wls = np.asarray(wls, dtype=float)
    aw = np.interp(wls, _WL_REF, _AW_REF)
    aphy_star = np.interp(wls, _WL_REF, _APHY_STAR_REF)

    omega_p = float(np.clip(omega_p, 0.0, 0.999))
    c_p = float(bstar_550) * float(tss) * (wls / 550.0) ** (-float(eta_p))
    b_total = omega_p * c_p
    a_p = (1.0 - omega_p) * c_p

    a_cdom = float(cdom_a440) * np.exp(-float(s_cdom) * (wls - 440.0))
    a_phy = aphy_star * float(chl)

    a_total = np.maximum(aw + a_cdom + a_phy + a_p, 0.0)
    b_total = np.maximum(b_total, 0.0)
    return a_total, b_total


def kd_from_iop(a, b, g=0.85, mu_d=0.85):
    """Convierte (a, b) a Kd usando una aproximación tipo Gershun/Kirk:
        Kd ≈ (a + (1 - g)·b) / μ̄_d
    válida en régimen difuso para aguas oligotróficas a mesotróficas.
    Devuelve Kd [1/m]."""
    bb_like = (1.0 - g) * b  # dispersión retrodifusa efectiva
    return (a + bb_like) / max(mu_d, 1e-3)


def kd_lee2005(a, bb, theta_a_deg=30.0):
    """Cierre semianalítico de Lee, Du & Arnone (2005) para el coeficiente de
    atenuación difusa descendente, función de absorción a, retrodispersión b_b y
    ángulo cenital solar θ_a (en aire, grados):
        Kd = (1 + 0.005·θ_a)·a + 4.18·(1 − 0.52·e^{−10.8·a})·b_b
    Más fiel que Kirk en aguas dispersoras porque usa b_b explícito y la geometría
    de iluminación. θ_a por defecto 30° (nominal, fuente artificial)."""
    a = np.asarray(a, dtype=float)
    bb = np.asarray(bb, dtype=float)
    return (1.0 + 0.005 * theta_a_deg) * a + 4.18 * (1.0 - 0.52 * np.exp(-10.8 * a)) * bb


# =============================================================================
#  CALIDAD DE LUZ: ÁNGULO DE MATIZ CIE (Lee et al. 2022)
# =============================================================================
# Funciones de igualación de color CIE 1931 (observador 2°), 400–700 nm @10 nm.
_CIE_WL = np.arange(400, 701, 10, dtype=float)
_CIE_XBAR = np.array([0.0143, 0.0435, 0.1344, 0.2839, 0.3483, 0.3362, 0.2908,
                      0.1954, 0.0956, 0.0320, 0.0049, 0.0093, 0.0633, 0.1655,
                      0.2904, 0.4334, 0.5945, 0.7621, 0.9163, 1.0263, 1.0622,
                      1.0026, 0.8544, 0.6424, 0.4479, 0.2835, 0.1649, 0.0874,
                      0.0468, 0.0227, 0.0114])
_CIE_YBAR = np.array([0.0004, 0.0012, 0.0040, 0.0116, 0.0230, 0.0380, 0.0600,
                      0.0910, 0.1390, 0.2080, 0.3230, 0.5030, 0.7100, 0.8620,
                      0.9540, 0.9950, 0.9950, 0.9520, 0.8700, 0.7570, 0.6310,
                      0.5030, 0.3810, 0.2650, 0.1750, 0.1070, 0.0610, 0.0320,
                      0.0170, 0.0082, 0.0041])
_CIE_ZBAR = np.array([0.0679, 0.2074, 0.6456, 1.3856, 1.7471, 1.7721, 1.6692,
                      1.2876, 0.8130, 0.4652, 0.2720, 0.1582, 0.0782, 0.0422,
                      0.0203, 0.0087, 0.0039, 0.0021, 0.0017, 0.0011, 0.0008,
                      0.0003, 0.0002, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0])


def cie_cmf(wls):
    """Funciones de igualación de color CIE 1931 interpoladas a wls [nm]."""
    wls = np.asarray(wls, dtype=float)
    return (np.interp(wls, _CIE_WL, _CIE_XBAR),
            np.interp(wls, _CIE_WL, _CIE_YBAR),
            np.interp(wls, _CIE_WL, _CIE_ZBAR))


def hue_angle_from_xyz(X, Y, Z):
    """Ángulo de matiz α_E (grados, 0–360) y saturación (distancia radial al punto
    blanco equienergético E, (1/3,1/3)) en el plano de cromaticidad CIE. Acepta
    escalares o arrays. Sigue la definición de Lee et al. (2022) para la calidad de
    la luz de la irradiancia descendente."""
    X = np.asarray(X, dtype=float)
    Y = np.asarray(Y, dtype=float)
    Z = np.asarray(Z, dtype=float)
    s = X + Y + Z
    with np.errstate(invalid='ignore', divide='ignore'):
        x = np.where(s > 0, X / s, np.nan)
        y = np.where(s > 0, Y / s, np.nan)
    dx = x - 1.0 / 3.0
    dy = y - 1.0 / 3.0
    ang = (np.degrees(np.arctan2(dy, dx)) + 360.0) % 360.0
    sat = np.sqrt(dx * dx + dy * dy)
    return ang, sat


def hue_angle_from_spectrum(wls, weights):
    """Ángulo de matiz y saturación de un espectro muestreado (wls [nm], pesos =
    contribución de energía/irradiancia por muestra). Devuelve (alpha_deg, sat)."""
    xb, yb, zb = cie_cmf(wls)
    w = np.asarray(weights, dtype=float)
    X = float(np.sum(w * xb)); Y = float(np.sum(w * yb)); Z = float(np.sum(w * zb))
    ang, sat = hue_angle_from_xyz(X, Y, Z)
    return float(ang), float(sat)


def c_from_kd(kd, omega=0.8, g=0.85, mu_d=0.85):
    """Inversa empírica: dado Kd, asume un omega y g típicos y devuelve un (c, a, b)
    consistentes con el bio-óptico para alimentar al ray-tracer:
        Si omega = b/c y c = a+b, entonces a = c(1-omega), b = c·omega
        Kd ≈ (c·(1-omega) + (1-g)·c·omega) / μ̄_d
        ⇒ c = Kd · μ̄_d / (1 - omega·g)
    """
    denom = max(1.0 - omega * g, 1e-3)
    c = kd * mu_d / denom
    b = c * omega
    a = c - b
    return c, a, b


# =============================================================================
#  PROFUNDIDAD DE DISCO DE SECCHI EQUIVALENTE
# =============================================================================

def hg_backscatter_fraction(g):
    """Fracción de retrodispersión b_b/b de la fase de Henyey-Greenstein,
    obtenida integrando la fase sobre el hemisferio posterior:
        B(g) = ((1-g)/(2g)) · [ (1+g)/sqrt(1+g²) − 1 ]
    Coherente con la única g usada por el ray-tracer (sample_henyey_greenstein).
    Para g=0.85 devuelve B≈0.036; para g→0 tiende a 0.5 (isótropa)."""
    g = float(g)
    if abs(g) < 1e-6:
        return 0.5
    return ((1.0 - g) / (2.0 * g)) * ((1.0 + g) / np.sqrt(1.0 + g**2) - 1.0)


def subsurface_reflectance(a, bb, f=0.33):
    """Reflectancia de irradiancia subsuperficial R(0-) ≈ f·b_b/(a+b_b)
    (aprox. de Gordon et al. 1975 con f≈0.33). Devuelve adimensional."""
    return f * bb / max(a + bb, 1e-9)


def secchi_preisendorfer(c, kd, gamma=8.69):
    """Profundidad de Secchi por la teoría clásica acoplada de Preisendorfer (1986):
        Z_SD ≈ Γ / (c + Kd),  con Γ≈8.69.
    Dominada por el coeficiente de atenuación de haz c."""
    s = float(c) + float(kd)
    return gamma / s if s > 0 else 0.0


def secchi_poole_atkins(kd, coeff=1.7):
    """Profundidad de Secchi por la relación empírica clásica de Poole & Atkins
    (1929): Z_SD ≈ coeff / Kd, con coeff≈1.7 (el producto Z_SD·Kd ronda 1.2–1.9
    en aguas naturales). Modelo de un solo coeficiente (atenuación difusa)."""
    kd = float(kd)
    return coeff / kd if kd > 0 else 0.0


def secchi_lee2015(kd_tr, r_w=0.02, r_T=0.85 / np.pi, c_t=0.013):
    """Profundidad de Secchi por la teoría revisada de Lee et al. (2015):
        Z_SD = 1/(2.5·Kd_tr) · ln(|r_T − r_w| / C_t)
    donde Kd_tr es el Kd MÍNIMO del espectro visible (ventana transparente),
    r_T la reflectancia de radiancia del disco blanco (R_T=0.85, lambertiano),
    r_w la reflectancia de fondo del agua y C_t el contraste umbral del ojo.
    Gobernada por la atenuación difusa, no por c."""
    kd_tr = float(kd_tr)
    if kd_tr <= 0:
        return 0.0
    contrast = abs(r_T - r_w) / max(c_t, 1e-6)
    if contrast <= 1.0:
        return 0.0
    return float(np.log(contrast) / (2.5 * kd_tr))


# =============================================================================
#  MOTOR
# =============================================================================

class SimulationEngine:
    def __init__(self):
        self.parsers = {}
        self.last_volume_tally = None

    def load_file(self, filename, content_str):
        try:
            if filename.lower().endswith('.ies'):
                parser = IESParser(content_str)
            else:
                parser = TM33Parser(content_str)
            self.parsers[filename] = parser
            return True
        except Exception as e:
            print(f"Error cargando {filename}: {e}")
            return False

    def _init_volume_tally(self, config, env_x, env_y, env_type, env_shape, env_radio, center_x, center_y, z_interface):
        vt_cfg = config.get('volume_tally', {}) or {}
        if not vt_cfg.get('enabled'):
            self.last_volume_tally = None
            return None

        x_min = float(vt_cfg.get('x_min_m', 0.0))
        x_max = float(vt_cfg.get('x_max_m', env_x))
        y_min = float(vt_cfg.get('y_min_m', 0.0))
        y_max = float(vt_cfg.get('y_max_m', env_y))
        d_min = float(vt_cfg.get('depth_min_m', 0.0))
        d_max = float(vt_cfg.get('depth_max_m', config.get('env', {}).get('z', 15.0)))
        dx = float(vt_cfg.get('dx_m', 1.0))
        dy = float(vt_cfg.get('dy_m', 1.0))
        dz = float(vt_cfg.get('dz_m', 1.0))
        if x_max <= x_min or y_max <= y_min or d_max <= d_min:
            raise ValueError("volume_tally tiene límites espaciales inválidos.")
        if dx <= 0 or dy <= 0 or dz <= 0:
            raise ValueError("volume_tally requiere dx_m, dy_m y dz_m positivos.")

        x_edges = np.arange(x_min, x_max + dx * 0.5, dx, dtype=float)
        y_edges = np.arange(y_min, y_max + dy * 0.5, dy, dtype=float)
        d_edges = np.arange(d_min, d_max + dz * 0.5, dz, dtype=float)
        if x_edges[-1] < x_max:
            x_edges = np.append(x_edges, x_max)
        if y_edges[-1] < y_max:
            y_edges = np.append(y_edges, y_max)
        if d_edges[-1] < d_max:
            d_edges = np.append(d_edges, d_max)

        x_centers = 0.5 * (x_edges[:-1] + x_edges[1:])
        y_centers = 0.5 * (y_edges[:-1] + y_edges[1:])
        d_centers = 0.5 * (d_edges[:-1] + d_edges[1:])
        dx_arr = np.diff(x_edges)
        dy_arr = np.diff(y_edges)
        dz_arr = np.diff(d_edges)
        shape = (len(d_centers), len(y_centers), len(x_centers))
        cell_volume = dz_arr[:, np.newaxis, np.newaxis] * dy_arr[np.newaxis, :, np.newaxis] * dx_arr[np.newaxis, np.newaxis, :]
        Xc, Yc = np.meshgrid(x_centers, y_centers)
        if env_shape == 'circle':
            xy_valid = ((Xc - center_x) ** 2 + (Yc - center_y) ** 2) <= env_radio ** 2
        else:
            xy_valid = np.ones_like(Xc, dtype=bool)
        valid_mask = np.repeat(xy_valid[np.newaxis, :, :], len(d_centers), axis=0)

        tally = {
            'enabled': True,
            'env_type': env_type,
            'env_shape': env_shape,
            'z_interface': float(z_interface),
            'x_edges_m': x_edges,
            'y_edges_m': y_edges,
            'depth_edges_m': d_edges,
            'x_centers_m': x_centers,
            'y_centers_m': y_centers,
            'depth_centers_m': d_centers,
            'path_total': np.zeros(shape, dtype=float),
            'path_bands': {band: np.zeros(shape, dtype=float) for band in vt_cfg.get('bands', {}).keys()},
            'bands': vt_cfg.get('bands', {}),
            'valid_mask': valid_mask,
            'cell_volume_m3': cell_volume,
            'step_m': max(float(vt_cfg.get('step_m', min(dx, dy, dz) * 0.5)), 1e-3),
        }
        self.last_volume_tally = tally
        return tally

    def _depth_from_world_z(self, z_world, tally):
        if tally['env_type'] == 'jaula':
            return -z_world
        return tally['z_interface'] - z_world

    def _ray_exit_distance(self, P, D, env_x, env_y, env_type, env_shape, env_radio, center_x, center_y, floor_z, surf_z):
        t_wall = np.full(len(P), np.inf)
        if env_shape == 'circle':
            a = D[:, 0] ** 2 + D[:, 1] ** 2
            b_coef = (P[:, 0] - center_x) * D[:, 0] + (P[:, 1] - center_y) * D[:, 1]
            c_coef = (P[:, 0] - center_x) ** 2 + (P[:, 1] - center_y) ** 2 - env_radio ** 2
            disc = b_coef ** 2 - a * c_coef
            valid_disc = (disc > 0) & (a > 1e-12)
            if np.any(valid_disc):
                sqrt_disc = np.sqrt(disc[valid_disc])
                t1 = (-b_coef[valid_disc] + sqrt_disc) / a[valid_disc]
                t2 = (-b_coef[valid_disc] - sqrt_disc) / a[valid_disc]
                t_pos = np.where((t1 > 1e-4) & ((t1 < t2) | (t2 <= 1e-4)), t1, t2)
                t_wall[valid_disc] = np.where(t_pos > 1e-4, t_pos, np.inf)
        else:
            tx1 = (0 - P[:, 0]) / (D[:, 0] + 1e-9)
            tx2 = (env_x - P[:, 0]) / (D[:, 0] + 1e-9)
            ty1 = (0 - P[:, 1]) / (D[:, 1] + 1e-9)
            ty2 = (env_y - P[:, 1]) / (D[:, 1] + 1e-9)
            tx_pos = np.where(tx1 > 1e-4, tx1, np.where(tx2 > 1e-4, tx2, np.inf))
            ty_pos = np.where(ty1 > 1e-4, ty1, np.where(ty2 > 1e-4, ty2, np.inf))
            t_wall = np.minimum(tx_pos, ty_pos)

        t_floor = np.full(len(P), np.inf)
        going_down = D[:, 2] < 0
        if np.any(going_down):
            t_floor[going_down] = (floor_z - P[:, 2][going_down]) / D[:, 2][going_down]

        t_surf = np.full(len(P), np.inf)
        going_up = D[:, 2] > 0
        if np.any(going_up):
            t_surf[going_up] = (surf_z - P[:, 2][going_up]) / D[:, 2][going_up]
        return np.minimum(t_wall, np.minimum(t_floor, t_surf))

    def _accumulate_volume_samples(self, tally, points, path_lengths, weights, wavelengths):
        if tally is None or len(points) == 0:
            return
        x_edges = tally['x_edges_m']
        y_edges = tally['y_edges_m']
        d_edges = tally['depth_edges_m']
        depth = self._depth_from_world_z(points[:, 2], tally)
        ix = np.searchsorted(x_edges, points[:, 0], side='right') - 1
        iy = np.searchsorted(y_edges, points[:, 1], side='right') - 1
        iz = np.searchsorted(d_edges, depth, side='right') - 1
        nx = len(x_edges) - 1
        ny = len(y_edges) - 1
        nz = len(d_edges) - 1
        valid = (ix >= 0) & (ix < nx) & (iy >= 0) & (iy < ny) & (iz >= 0) & (iz < nz)
        if not np.any(valid):
            return
        ix = ix[valid]
        iy = iy[valid]
        iz = iz[valid]
        contrib = weights[valid] * path_lengths[valid]
        wl = wavelengths[valid]
        mask_env = tally['valid_mask'][iz, iy, ix]
        if not np.any(mask_env):
            return
        ix = ix[mask_env]
        iy = iy[mask_env]
        iz = iz[mask_env]
        contrib = contrib[mask_env]
        wl = wl[mask_env]
        np.add.at(tally['path_total'], (iz, iy, ix), contrib)
        for band, bounds in tally['bands'].items():
            lo, hi = float(bounds[0]), float(bounds[1])
            band_mask = (wl >= lo) & (wl < hi)
            if np.any(band_mask):
                np.add.at(tally['path_bands'][band], (iz[band_mask], iy[band_mask], ix[band_mask]), contrib[band_mask])

    def _accumulate_volume_segments(self, tally, P0, D, distances, weights, wavelengths,
                                    attenuation=None, atten_coef_type='c'):
        if tally is None or len(P0) == 0:
            return
        step_m = tally['step_m']
        finite = np.isfinite(distances) & (distances > 1e-6) & (weights > 0)
        if not np.any(finite):
            return
        P0 = P0[finite]
        D = D[finite]
        distances = distances[finite]
        weights = weights[finite]
        wavelengths = wavelengths[finite]
        if attenuation is not None:
            attenuation = attenuation[finite]
        for start in range(0, len(P0), 2000):
            end = min(start + 2000, len(P0))
            for i in range(start, end):
                n_steps = max(1, int(np.ceil(distances[i] / step_m)))
                ds = distances[i] / n_steps
                s_mid = (np.arange(n_steps, dtype=float) + 0.5) * ds
                pts = P0[i] + D[i] * s_mid[:, np.newaxis]
                w = np.full(n_steps, weights[i], dtype=float)
                if attenuation is not None:
                    if atten_coef_type == 'kd':
                        delta_z = np.abs(pts[:, 2] - P0[i, 2])
                        w *= np.exp(-attenuation[i] * delta_z)
                    else:
                        w *= np.exp(-attenuation[i] * s_mid)
                self._accumulate_volume_samples(
                    tally,
                    pts,
                    np.full(n_steps, ds, dtype=float),
                    w,
                    np.full(n_steps, wavelengths[i], dtype=float),
                )

    def _finalize_volume_tally(self, tally):
        if tally is None:
            self.last_volume_tally = None
            return
        cell_volume = np.maximum(np.asarray(tally['cell_volume_m3'], dtype=float), 1e-12)
        result = {
            'x_edges_m': tally['x_edges_m'].tolist(),
            'y_edges_m': tally['y_edges_m'].tolist(),
            'depth_edges_m': tally['depth_edges_m'].tolist(),
            'x_centers_m': tally['x_centers_m'].tolist(),
            'y_centers_m': tally['y_centers_m'].tolist(),
            'depth_centers_m': tally['depth_centers_m'].tolist(),
            'cell_volume_m3': cell_volume.tolist(),
            'valid_mask': tally['valid_mask'].tolist(),
            'E_total_W_m2': (tally['path_total'] / cell_volume).tolist(),
        }
        for band, arr in tally['path_bands'].items():
            result[f'E_{band}_W_m2'] = (arr / cell_volume).tolist()
        self.last_volume_tally = result

    def run(self, config):
        self.last_volume_tally = None
        # ---------------------------------------------------------------
        # Configuración del entorno
        # ---------------------------------------------------------------
        env = config.get('env', {})
        env_type = env.get('type', 'estanque')
        env_shape = env.get('shape', 'circle' if env_type == 'estanque' else 'rect')

        raw_x = env.get('x'); raw_y = env.get('y')
        env_x = float(raw_x) if raw_x is not None else 40.0
        env_y = float(raw_y) if raw_y is not None else 40.0

        center_x, center_y = env_x / 2.0, env_y / 2.0

        raw_radio = env.get('radio')
        env_radio = float(raw_radio) if raw_radio is not None else env_x / 2.0

        raw_n1 = env.get('n1')
        n1 = float(raw_n1) if raw_n1 is not None else 1.0

        raw_n2 = env.get('n2')
        n2 = float(raw_n2) if raw_n2 is not None else 1.333

        raw_z_int = env.get('z_interface')
        z_interface = 0.0 if env_type == 'jaula' else (float(raw_z_int) if raw_z_int is not None else 3.2)

        # Dominio vertical efectivo: para jaula es la profundidad real (suelo en -env_z)
        raw_env_z = env.get('z')
        env_z = float(raw_env_z) if raw_env_z is not None else 15.0

        # ---------------------------------------------------------------
        # Configuración óptica
        # ---------------------------------------------------------------
        optics = config.get('optics', {})
        optics_mode = optics.get('mode', 'kd_fijo')
        kd_fijo = float(optics.get('kd_fijo', 0.2))
        kd_spectral = optics.get('kd_spectral', {})
        mc_input_type = optics.get('mc_input_type', 'scalar')
        g_hg = float(optics.get('g', 0.85))
        r_wall = float(optics.get('r_wall', 0.15))

        # Función de fase de scattering: 'hg' (Henyey-Greenstein, por defecto) o
        # 'fournier_forand'. FF desacopla la retrodispersión b_b/b de la asimetría:
        # si no se entrega bb_ratio, se usa la equivalente de la HG con la misma g
        # para continuidad. La CDF inversa FF depende sólo de (n, mu) y se construye
        # una vez por simulación.
        phase_function = str(optics.get('phase_function', 'hg')).lower()
        ff_mu = float(optics.get('ff_mu', 3.5))
        bb_ratio = optics.get('bb_ratio', None)
        ff_inv_cdf = None
        if phase_function == 'fournier_forand':
            target_bb = float(bb_ratio) if bb_ratio is not None else hg_backscatter_fraction(g_hg)
            ff_n = ff_n_from_backscatter(target_bb, mu=ff_mu)
            ff_inv_cdf = build_ff_inverse_cdf(ff_n, ff_mu)

        # Tipo de coeficiente para los modos kd_fijo / kd_espectral:
        #   'c'  → coeficiente de atenuación de haz (Beer-Lambert por camino real)
        #   'Kd' → coeficiente de atenuación difusa (Beer-Lambert por Δz vertical)
        atten_coef_type = str(optics.get('atten_coef_type', 'c')).lower()

        # Clorofila para modelo bio-óptico de 4 componentes [mg/m³]
        chl_val = float(optics.get('chl', 0.0))
        # Parámetros del modelo Kd→c (sólo se usan si atten_coef_type='Kd' en scattering, no aquí)
        omega_default = float(optics.get('omega', 0.8))

        irradiance_type = config.get('irradiance_type', 'scalar')
        mu_max_deg = float(config.get('mu_max', 85.0))
        cos_mu_max = np.cos(np.radians(mu_max_deg))
        normalize_pineal = config.get('normalize_pineal', True)
        pineal_norm_factor = 0.5 if normalize_pineal else 1.0

        target_depths_input = config.get('target_depths', [2.0])
        n_rays = int(config.get('rays', 50000))

        results = {str(d): {'x': [], 'y': [], 'val': [], 'lamp_idx': [], 'wl': []}
                   for d in target_depths_input}
        volume_tally = self._init_volume_tally(
            config, env_x, env_y, env_type, env_shape, env_radio, center_x, center_y, z_interface
        )

        if env_type == 'estanque':
            floor_z_tally = 0.0
            surf_z_tally = z_interface
        else:
            floor_z_tally = -env_z
            surf_z_tally = 0.0

        # ---------------------------------------------------------------
        # Bucle por lámparas
        # ---------------------------------------------------------------
        for i_lamp, lamp in enumerate(config.get('lamps', [])):
            xml_id = lamp['xml']
            if xml_id not in self.parsers:
                continue
            parser = self.parsers[xml_id]

            pos_z = -float(lamp['z']) if env_type == 'jaula' else float(lamp['z'])
            pos = np.array([float(lamp['x']), float(lamp['y']), pos_z])
            dimming = float(lamp['dim'])
            rot_x = float(lamp.get('rot_x', 0))
            rot_y = float(lamp.get('rot_y', 0))
            rot_z = float(lamp.get('rot_z', 0))

            # Muestreo de Fibonacci en la esfera (cuasi-uniforme)
            indices = np.arange(0, n_rays, dtype=float) + 0.5
            phi = np.arccos(1 - 2 * indices / n_rays)
            theta = np.pi * (1 + 5**0.5) * indices
            lx, ly, lz = np.sin(phi) * np.cos(theta), np.sin(phi) * np.sin(theta), np.cos(phi)
            rays_local = np.column_stack((lx, ly, lz))

            lum, rad = parser.get_intensity(rays_local)

            # --- Normalización: integral angular = potencia radiante objetivo
            total_current_power = np.sum(rad) * (4 * np.pi / n_rays)
            elec_power = float(lamp.get('power', 600))
            eff = float(lamp.get('efficiency', 1.0))
            target_rad_power = elec_power * eff

            if total_current_power > 0:
                rad = rad * (target_rad_power / total_current_power)

            mask = rad > 0
            rays_local = rays_local[mask]
            if len(rays_local) == 0:
                continue

            flux_rad = rad[mask] * (4 * np.pi / n_rays) * dimming

            rays_global = rays_local
            if rot_x != 0 or rot_y != 0 or rot_z != 0:
                rays_global = rotate_3d(rays_local, rot_x, rot_y, rot_z)

            # --- Muestreo espectral con CDF trapezoidal
            spectrum = parser.get_spectrum()
            if not spectrum:
                wls = np.array([400.0, 500.0, 600.0, 700.0])
                pwrs = np.array([1.0, 1.0, 1.0, 1.0])
            else:
                wls = np.array(sorted(spectrum.keys()), dtype=float)
                pwrs = np.array([spectrum[w] for w in wls], dtype=float)
            ray_wls = sample_wavelength(wls, pwrs, len(rays_global))

            # ---------------------------------------------------------------
            # Coeficientes ópticos para modo scattering
            # ---------------------------------------------------------------
            if optics_mode == 'scattering':
                if mc_input_type == 'ras_bardsnes':
                    # Formas espectrales empíricas de Bårdsnes (2020) para agua de RAS.
                    # Acepta TSS directo o lo deriva de turbidez NTU con la regresión del
                    # paper. bstar_550/omega_p/eta_p/s_cdom son calibrables por sistema.
                    turb_ntu = optics.get('turbidity_ntu', None)
                    tss_val = optics.get('tss', None)
                    if tss_val is None and turb_ntu is not None:
                        tss_val = ras_tss_from_turbidity(turb_ntu)
                    tss_val = float(tss_val if tss_val is not None else 15.0)
                    a440_val = float(optics.get('cdom_a440', 1.0))
                    a_ray, b_ray = bio_optical_iop_ras_bardsnes(
                        ray_wls,
                        tss=tss_val,
                        cdom_a440=a440_val,
                        chl=chl_val,
                        bstar_550=float(optics.get('ras_bstar_550', _RAS_BSTAR_550)),
                        omega_p=float(optics.get('ras_omega_p', _RAS_OMEGA_P)),
                        eta_p=float(optics.get('ras_eta_p', _RAS_ETA_P)),
                        s_cdom=float(optics.get('ras_s_cdom', _RAS_S_CDOM)),
                    )
                    ray_c_all = a_ray + b_ray
                    ray_omega_all = b_ray / (ray_c_all + 1e-9)
                elif mc_input_type == 'bio':
                    tss_val = float(optics.get('tss', 15.0))
                    a440_val = float(optics.get('cdom_a440', 1.0))
                    a_ray, b_ray = bio_optical_iop(
                        ray_wls, tss=tss_val, cdom_a440=a440_val, chl=chl_val
                    )
                    ray_c_all = a_ray + b_ray
                    ray_omega_all = b_ray / (ray_c_all + 1e-9)
                elif mc_input_type == 'json':
                    c_dict = optics.get('c_json', {})
                    omega_dict = optics.get('omega_json', {})
                    c_wls = np.array([float(k) for k in sorted(c_dict.keys())])
                    c_vals = np.array([float(c_dict[k]) for k in sorted(c_dict.keys())])
                    omega_wls = np.array([float(k) for k in sorted(omega_dict.keys())])
                    omega_vals = np.array([float(omega_dict[k]) for k in sorted(omega_dict.keys())])
                    if len(c_wls) == 0:
                        c_wls, c_vals = np.array([500.0]), np.array([0.5])
                    if len(omega_wls) == 0:
                        omega_wls, omega_vals = np.array([500.0]), np.array([0.8])
                    ray_c_all = np.interp(ray_wls, c_wls, c_vals)
                    ray_omega_all = np.interp(ray_wls, omega_wls, omega_vals)
                else:  # scalar
                    c_att = float(optics.get('c', 0.5))
                    omega = float(optics.get('omega', 0.8))
                    ray_c_all = np.full(len(rays_global), c_att)
                    ray_omega_all = np.full(len(rays_global), omega)

            v_rays = rays_global
            v_flux = flux_rad
            v_wls = ray_wls

            if optics_mode == 'scattering':
                r_c = ray_c_all
                r_omega = ray_omega_all

            P_start = np.tile(pos, (len(v_rays), 1))

            # ---------------------------------------------------------------
            # Refracción aire→agua (sólo lámparas aéreas en estanque)
            # ---------------------------------------------------------------
            if env_type == 'estanque' and pos[2] > z_interface:
                down_mask = v_rays[:, 2] < -1e-6
                v_rays = v_rays[down_mask]
                v_flux = v_flux[down_mask]
                v_wls = v_wls[down_mask]
                P_start = P_start[down_mask]

                t_int = (z_interface - P_start[:, 2]) / v_rays[:, 2]
                P_int = P_start + v_rays * t_int[:, np.newaxis]
                c_ti = -v_rays[:, 2]
                s2_tt = (n1 / n2)**2 * (1.0 - c_ti**2)
                tir_mask = s2_tt <= 1.0

                v_rays = v_rays[tir_mask]
                v_flux = v_flux[tir_mask]
                v_wls = v_wls[tir_mask]
                P_start = P_int[tir_mask]
                c_ti = c_ti[tir_mask]
                c_tt = np.sqrt(1.0 - s2_tt[tir_mask])

                T_vec = (n1 / n2) * v_rays + ((n1 / n2) * c_ti - c_tt)[:, np.newaxis] * np.array([0, 0, 1])
                T_fresnel = fresnel_transmission(n1, n2, c_ti, c_tt)

                v_rays = normalize(T_vec)
                # CORRECCIÓN #1: eliminado el factor 0.98 espurio. Fresnel ya conserva la potencia.
                v_flux = v_flux * T_fresnel

                if optics_mode == 'scattering':
                    r_c = r_c[down_mask][tir_mask]
                    r_omega = r_omega[down_mask][tir_mask]

            if len(v_rays) == 0:
                continue

            # ---------------------------------------------------------------
            # Modo Beer-Lambert simple (kd_fijo / kd_espectral) con elección Kd vs c
            # ---------------------------------------------------------------
            if optics_mode in ('kd_fijo', 'kd_espectral'):
                if optics_mode == 'kd_fijo':
                    ray_atten = np.full(len(v_rays), kd_fijo)
                else:
                    kd_wls = np.array([float(k) for k in sorted(kd_spectral.keys())])
                    kd_vals = np.array([float(kd_spectral[k]) for k in sorted(kd_spectral.keys())])
                    if len(kd_wls) == 0:
                        kd_wls, kd_vals = np.array([500.0]), np.array([0.2])
                    ray_atten = np.interp(v_wls, kd_wls, kd_vals)

                if volume_tally is not None:
                    t_exit = self._ray_exit_distance(
                        P_start, v_rays, env_x, env_y, env_type, env_shape,
                        env_radio, center_x, center_y, floor_z_tally, surf_z_tally
                    )
                    self._accumulate_volume_segments(
                        volume_tally, P_start, v_rays, t_exit, v_flux, v_wls,
                        attenuation=ray_atten, atten_coef_type=atten_coef_type
                    )

                for orig_depth in target_depths_input:
                    depth = -float(orig_depth) if env_type == 'jaula' else float(orig_depth)

                    t = (depth - P_start[:, 2]) / (v_rays[:, 2] + 1e-16)
                    # Cada rayo cruza el plano objetivo a lo sumo una vez:
                    # - Para planos por debajo de la lámpara, contribuyen los rayos descendentes.
                    # - Para planos por sobre la lámpara, contribuyen los rayos ascendentes.
                    # El signo de t resuelve naturalmente ambos casos. Equivale a
                    # |E_d| + |E_u| (flujo radiante total atravesando el plano).
                    valid = t > 0
                    if not np.any(valid):
                        continue

                    P_hit = P_start[valid] + v_rays[valid] * t[valid][:, np.newaxis]
                    d_path = np.linalg.norm(v_rays[valid] * t[valid][:, np.newaxis], axis=1)
                    delta_z = np.abs(P_hit[:, 2] - P_start[valid][:, 2])

                    # CORRECCIÓN #7: interpretación Kd vs c consistente
                    if atten_coef_type == 'kd':
                        # Kd se define para irradiancia descendente vs profundidad,
                        # por lo que se aplica al desplazamiento vertical.
                        # Esto reproduce E_d(z) = E_d(0)·exp(-Kd·z) en el agregado.
                        val = v_flux[valid] * np.exp(-ray_atten[valid] * delta_z)
                    else:
                        # c (beam attenuation): pérdida a lo largo del camino real del rayo
                        val = v_flux[valid] * np.exp(-ray_atten[valid] * d_path)

                    if irradiance_type == 'pineal':
                        # El sensor pineal mira hacia arriba: ponderación (1+cos μ) con μ
                        # medido desde el cenit del sensor (rayos descendentes).
                        cos_mu = -v_rays[valid][:, 2]
                        pineal_weight = np.where(cos_mu >= cos_mu_max,
                                                  pineal_norm_factor * (1.0 + cos_mu), 0.0)
                        val = val * pineal_weight

                    results[str(orig_depth)]['x'].extend(P_hit[:, 0].tolist())
                    results[str(orig_depth)]['y'].extend(P_hit[:, 1].tolist())
                    results[str(orig_depth)]['val'].extend(val.tolist())
                    results[str(orig_depth)]['lamp_idx'].extend(np.full(len(P_hit), i_lamp).tolist())
                    results[str(orig_depth)]['wl'].extend(v_wls[valid].tolist())

            # ---------------------------------------------------------------
            # Modo SCATTERING Monte Carlo
            # ---------------------------------------------------------------
            elif optics_mode == 'scattering':
                P_mc = P_start.copy()
                D_mc = v_rays.copy()
                W_mc = v_flux.copy()

                # CORRECCIÓN #5: el dominio vertical respeta env_z para jaulas
                if env_type == 'estanque':
                    floor_z = 0.0
                    surf_z = z_interface
                else:
                    floor_z = -env_z
                    surf_z = 0.0

                # CORRECCIÓN #6: aumentar rebotes y aplicar Russian roulette insesgada
                max_bounces = 20
                rr_start_bounce = 4
                # Umbral de RR basado en el peso inicial mediano (sólo > 0)
                pos_w = W_mc[W_mc > 0]
                w_ref = float(np.median(pos_w)) if pos_w.size > 0 else 1.0
                rr_threshold = max(w_ref * 0.05, 1e-12)

                for bounce in range(max_bounces):
                    active = W_mc > 1e-12
                    if not np.any(active):
                        break

                    P = P_mc[active]
                    D = D_mc[active]
                    W = W_mc[active]
                    c_active = r_c[active]
                    omega_active = r_omega[active]
                    wl_active = v_wls[active]
                    active_idx = active.nonzero()[0]

                    # --- Distancia a pared lateral
                    t_wall = np.full(len(P), np.inf)
                    if env_shape == 'circle':
                        a = D[:, 0]**2 + D[:, 1]**2
                        b_coef = (P[:, 0] - center_x) * D[:, 0] + (P[:, 1] - center_y) * D[:, 1]
                        c_coef = (P[:, 0] - center_x)**2 + (P[:, 1] - center_y)**2 - env_radio**2
                        disc = b_coef**2 - a * c_coef
                        valid_disc = (disc > 0) & (a > 1e-12)
                        if np.any(valid_disc):
                            sqrt_disc = np.sqrt(disc[valid_disc])
                            t1 = (-b_coef[valid_disc] + sqrt_disc) / a[valid_disc]
                            t2 = (-b_coef[valid_disc] - sqrt_disc) / a[valid_disc]
                            t_pos = np.where((t1 > 1e-4) & ((t1 < t2) | (t2 <= 1e-4)), t1, t2)
                            t_wall[valid_disc] = np.where(t_pos > 1e-4, t_pos, np.inf)
                    else:
                        tx1 = (0 - P[:, 0]) / (D[:, 0] + 1e-9)
                        tx2 = (env_x - P[:, 0]) / (D[:, 0] + 1e-9)
                        ty1 = (0 - P[:, 1]) / (D[:, 1] + 1e-9)
                        ty2 = (env_y - P[:, 1]) / (D[:, 1] + 1e-9)
                        tx_pos = np.where(tx1 > 1e-4, tx1, np.where(tx2 > 1e-4, tx2, np.inf))
                        ty_pos = np.where(ty1 > 1e-4, ty1, np.where(ty2 > 1e-4, ty2, np.inf))
                        t_wall = np.minimum(tx_pos, ty_pos)

                    # --- Distancia al suelo (absorción total)
                    t_floor = np.full(len(P), np.inf)
                    going_down = D[:, 2] < 0
                    if np.any(going_down):
                        t_floor[going_down] = (floor_z - P[:, 2][going_down]) / D[:, 2][going_down]

                    # --- Distancia a la superficie del agua (presente en ambos entornos)
                    t_surf = np.full(len(P), np.inf)
                    going_up = D[:, 2] > 0
                    if np.any(going_up):
                        t_surf[going_up] = (surf_z - P[:, 2][going_up]) / D[:, 2][going_up]

                    t_bound = np.minimum(t_wall, np.minimum(t_floor, t_surf))

                    # --- Distancia al próximo evento volumétrico
                    t_scat = -np.log(np.random.rand(len(P))) / (c_active + 1e-12)
                    t_event = np.minimum(t_bound, t_scat)

                    if volume_tally is not None:
                        self._accumulate_volume_segments(
                            volume_tally, P, D, t_event, W, wl_active,
                            attenuation=None, atten_coef_type='c'
                        )

                    # --- Clasificación del evento por argmin (mutuamente excluyente)
                    t_stack = np.column_stack([t_wall, t_floor, t_surf, t_scat])
                    event_id = np.argmin(t_stack, axis=1)
                    hit_wall = event_id == 0
                    hit_floor = event_id == 1
                    hit_surf = event_id == 2
                    hit_scat = event_id == 3

                    # --- Tally por cruces (ambas direcciones) para soportar planos
                    # tanto debajo como sobre la lámpara. La cantidad reportada es
                    # |E_d| + |E_u|, equivalente al flujo radiante total atravesando
                    # el plano por unidad de área. En ausencia de scattering se reduce
                    # a la irradiancia direccional clásica.
                    for orig_depth in target_depths_input:
                        d_val = float(orig_depth) if env_type != 'jaula' else -float(orig_depth)
                        z_start = P[:, 2]
                        z_end = P[:, 2] + t_event * D[:, 2]

                        crosses = (z_start - d_val) * (z_end - d_val) < 0
                        if np.any(crosses):
                            tc = (d_val - z_start[crosses]) / (D[:, 2][crosses] + 1e-16)
                            Px_c = P[:, 0][crosses] + tc * D[:, 0][crosses]
                            Py_c = P[:, 1][crosses] + tc * D[:, 1][crosses]

                            val_cross = W[crosses]

                            if irradiance_type == 'pineal':
                                cos_mu = -D[:, 2][crosses]
                                pineal_weight = np.where(cos_mu >= cos_mu_max,
                                                          pineal_norm_factor * (1.0 + cos_mu), 0.0)
                                val_cross = val_cross * pineal_weight

                            results[str(orig_depth)]['x'].extend(Px_c.tolist())
                            results[str(orig_depth)]['y'].extend(Py_c.tolist())
                            results[str(orig_depth)]['val'].extend(val_cross.tolist())
                            results[str(orig_depth)]['lamp_idx'].extend(np.full(len(Px_c), i_lamp).tolist())
                            results[str(orig_depth)]['wl'].extend(wl_active[crosses].tolist())

                    # --- PARED: reflexión LAMBERTIANA (CORRECCIÓN #10)
                    if np.any(hit_wall):
                        P_hw = P[hit_wall] + t_wall[hit_wall][:, np.newaxis] * D[hit_wall]
                        # Normal INTERIOR (apunta hacia el interior del recinto)
                        N_wall = np.zeros_like(P_hw)
                        if env_shape == 'circle':
                            N_wall[:, 0] = center_x - P_hw[:, 0]
                            N_wall[:, 1] = center_y - P_hw[:, 1]
                        else:
                            N_wall[:, 0] = np.where(np.abs(P_hw[:, 0]) < 1e-3, 1.0,
                                                    np.where(np.abs(P_hw[:, 0] - env_x) < 1e-3, -1.0, 0.0))
                            N_wall[:, 1] = np.where(np.abs(P_hw[:, 1]) < 1e-3, 1.0,
                                                    np.where(np.abs(P_hw[:, 1] - env_y) < 1e-3, -1.0, 0.0))
                        N_wall[:, 2] = 0.0
                        nn = np.linalg.norm(N_wall, axis=1, keepdims=True)
                        N_wall = N_wall / (nn + 1e-12)

                        D_new_wall = sample_lambertian(N_wall)

                        P_mc[active_idx[hit_wall]] = P_hw
                        D_mc[active_idx[hit_wall]] = D_new_wall
                        W_mc[active_idx[hit_wall]] *= r_wall

                    # --- SUELO: absorción total (CORRECCIÓN #5)
                    if np.any(hit_floor):
                        W_mc[active_idx[hit_floor]] = 0.0

                    # --- SUPERFICIE: Fresnel + TIR (CORRECCIÓN #3)
                    if np.any(hit_surf):
                        P_hs = P[hit_surf] + t_surf[hit_surf][:, np.newaxis] * D[hit_surf]
                        D_surf_in = D[hit_surf]

                        cos_theta_i = np.clip(np.abs(D_surf_in[:, 2]), 0.0, 1.0)
                        # Snell agua→aire: sin²θ_t = (n_water/n_air)² · sin²θ_i
                        sin2_theta_t = (n2 / n1)**2 * (1.0 - cos_theta_i**2)
                        tir_mask = sin2_theta_t >= 1.0
                        cos_theta_t = np.sqrt(np.maximum(0.0, 1.0 - sin2_theta_t))

                        # R Fresnel (medio incidente n2, medio transmisor n1)
                        R_fresnel = 1.0 - fresnel_transmission(n2, n1, cos_theta_i, cos_theta_t)
                        R = np.where(tir_mask, 1.0, R_fresnel)

                        # Reflexión especular respecto a la normal vertical (suelo de aire)
                        D_new_surf = D_surf_in.copy()
                        D_new_surf[:, 2] = -D_new_surf[:, 2]

                        P_mc[active_idx[hit_surf]] = P_hs
                        D_mc[active_idx[hit_surf]] = D_new_surf
                        W_mc[active_idx[hit_surf]] *= R

                    # --- DISPERSIÓN INTERNA
                    if np.any(hit_scat):
                        P_hs = P[hit_scat] + t_scat[hit_scat][:, np.newaxis] * D[hit_scat]
                        if ff_inv_cdf is not None:
                            D_new = sample_fournier_forand(D[hit_scat], ff_inv_cdf)
                        else:
                            D_new = sample_henyey_greenstein(D[hit_scat], g_hg)

                        P_mc[active_idx[hit_scat]] = P_hs
                        D_mc[active_idx[hit_scat]] = D_new
                        W_mc[active_idx[hit_scat]] *= omega_active[hit_scat]

                    # --- RUSSIAN ROULETTE insesgada (CORRECCIÓN #6)
                    if bounce >= rr_start_bounce:
                        alive = W_mc > 1e-12
                        alive_idx = alive.nonzero()[0]
                        if len(alive_idx) > 0:
                            low_mask = W_mc[alive_idx] < rr_threshold
                            if np.any(low_mask):
                                lw_idx = alive_idx[low_mask]
                                p_survive = np.clip(W_mc[lw_idx] / rr_threshold, 0.05, 1.0)
                                xi = np.random.rand(len(lw_idx))
                                survive = xi < p_survive
                                W_mc[lw_idx[survive]] = W_mc[lw_idx[survive]] / p_survive[survive]
                                W_mc[lw_idx[~survive]] = 0.0

        self._finalize_volume_tally(volume_tally)
        return results
