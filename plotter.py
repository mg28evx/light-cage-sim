import numpy as np
import io
import base64
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.collections import LineCollection
import matplotlib.colors as mcolors
import matplotlib.ticker as ticker

try:
    trapz_func = np.trapezoid
except AttributeError:
    trapz_func = np.trapz


# =============================================================================
#  PALETA DE GRÁFICOS
# =============================================================================
# Los PNG se muestran sobre la "placa" clara de la interfaz (#f4f6f9), así que
# la paleta se valida contra esa superficie, no contra el fondo oscuro del
# panel. Cada color tiene un trabajo asignado; no se reutilizan entre trabajos.
#
#   secuencial  -> magnitud (irradiancia). Un solo tono, luminancia monótona.
#   estado      -> umbrales. Escala de severidad + patrón de línea (no solo color).
#   categórico  -> identidad (curvas por profundidad). Orden fijo, nunca ciclado.
#   estructura  -> contorno del dominio, ROI, ejes. Tinta neutra, recesiva.
#
# El conjunto categórico está validado para daltonismo sobre la placa: el peor
# par adyacente da ΔE 7,3 (protan), dentro de la banda que exige codificación
# secundaria — por eso cada serie lleva además su propio patrón de línea.
# =============================================================================

# --- Tinta y estructura (recesivas) ---
INK           = '#16202b'   # texto principal
INK_SOFT      = '#46545f'   # texto secundario
INK_FAINT     = '#8d9aa8'   # rejilla y ejes
PLATE         = '#f4f6f9'   # superficie de la placa
PLATE_LINE    = '#d5dde6'
BOUNDARY      = '#46545f'   # contorno del dominio
ROI_EDGE      = '#16202b'   # región de evaluación
ROI_FACE      = (0.086, 0.125, 0.169, 0.05)

# --- Marca ---
GOLD          = '#ffc72c'
GOLD_DEEP     = '#a87d10'

# --- Secuencial: irradiancia. Oscuro = poca luz, dorado brillante = mucha.
#     Luminancia monótona L* 5,3 -> 91,9 sobre un único tono cálido. ---
SEQ_IRRADIANCE = ['#1b2028', '#403214', '#6d5210', '#96700f', '#c19212', '#e8b41d', '#ffc72c', '#ffe6a3']

# --- Estado: umbrales, de menor a mayor severidad.
#
#     Escala casi neutra a propósito: sobre una rampa cálida, unas isocurvas
#     saturadas compiten con el dato en vez de anotarlo. La jerarquía la dan la
#     luminancia y el patrón de línea; el único que lleva tono es el crítico,
#     que así destaca por ser el único cromático.
#
#     La luminancia baja según sube el umbral porque los umbrales altos caen en
#     la zona clara del mapa y los bajos en la oscura. Cada paso lleva su propio
#     halo, del signo contrario, para leerse también donde eso no se cumpla.
#     (color, patrón, color del halo)
THRESHOLD_STEPS = [
    ('#eef3f8', (0, ()),             '#0d1218'),  # 1º  continua
    ('#9fb0c2', (0, (7, 3)),         '#0d1218'),  # 2º  discontinua
    ('#41576d', (0, (7, 2, 1, 2)),   '#ffe6a3'),  # 3º  raya-punto
    ('#a33224', (0, (1.5, 2)),       '#ffe6a3'),  # 4º  punteada (crítico)
]

# --- Categórico: identidad de serie. Orden fijo, validado para CVD. ---
CATEGORICAL = ['#1f5fa8', '#c2521f', '#12805a', '#9c6b00', '#b4547a']
CATEGORICAL_DASHES = [(0, ()), (0, (7, 3)), (0, (7, 2, 1, 2)), (0, (2, 2)), (0, (10, 2, 2, 2))]

# --- Bandas espectrales: el color está atado a la longitud de onda real. ---
BAND_COLORS = {'blue': '#1f5fa8', 'green': '#12805a', 'red': '#c2521f'}

# --- Lámparas ---
LAMP_AERIAL   = '#ffc72c'
LAMP_SUBMERGED = '#1f5fa8'


def _irradiance_cmap():
    """Rampa secuencial de un solo tono para la irradiancia."""
    return mcolors.LinearSegmentedColormap.from_list('evolux_irradiance', SEQ_IRRADIANCE)


def _threshold_style(index):
    """Color, patrón y halo del umbral i-ésimo, por orden de severidad."""
    return THRESHOLD_STEPS[index % len(THRESHOLD_STEPS)]


def _halo(width=2.4, color='#0d1218', alpha=0.55):
    """Contorno alrededor de una marca para que se lea sobre cualquier zona del
    mapa. Permite mantener el color de la marca desaturado en vez de subirle la
    saturación para ganar contraste."""
    import matplotlib.patheffects as pe
    return [pe.withStroke(linewidth=width, foreground=color, alpha=alpha)]


def setup_matplotlib():
    plt.rcParams.update({
        "font.family": "serif",
        "font.serif": ["DejaVu Serif", "Times New Roman", "Computer Modern Roman"],
        "mathtext.fontset": "cm", 
        "axes.labelsize": 10,
        "axes.titlesize": 12,
        "font.size": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "figure.dpi": 150,
        # Ejes y rejilla recesivos: la tinta estructural nunca compite con el dato.
        "figure.facecolor": PLATE,
        "axes.facecolor": PLATE,
        "savefig.facecolor": PLATE,
        "text.color": INK,
        "axes.labelcolor": INK,
        "axes.edgecolor": INK_FAINT,
        "axes.linewidth": 0.8,
        "xtick.color": INK_SOFT,
        "ytick.color": INK_SOFT,
        "grid.color": INK_FAINT,
        "grid.alpha": 0.35,
        "grid.linewidth": 0.6,
        "legend.framealpha": 0.92,
        "legend.edgecolor": PLATE_LINE,
        "legend.facecolor": PLATE,
    })

def wavelength_to_rgb(wavelength):
    wavelength = float(wavelength)
    if wavelength >= 380 and wavelength <= 440:
        attenuation = 0.3 + 0.7 * (wavelength - 380) / (440 - 380)
        R = (-(wavelength - 440) / (440 - 380)) * attenuation
        G, B = 0.0, 1.0 * attenuation
    elif wavelength >= 440 and wavelength <= 490:
        R, G, B = 0.0, (wavelength - 440) / (490 - 440), 1.0
    elif wavelength >= 490 and wavelength <= 510:
        R, G, B = 0.0, 1.0, -(wavelength - 510) / (510 - 490)
    elif wavelength >= 510 and wavelength <= 580:
        R, G, B = (wavelength - 510) / (580 - 510), 1.0, 0.0
    elif wavelength >= 580 and wavelength <= 645:
        R, G, B = 1.0, -(wavelength - 645) / (645 - 580), 0.0
    elif wavelength >= 645 and wavelength <= 750:
        attenuation = 0.3 + 0.7 * (750 - wavelength) / (750 - 645)
        R, G, B = 1.0 * attenuation, 0.0, 0.0
    else:
        R, G, B = 0.0, 0.0, 0.0
    return (R, G, B)

def get_base64_image(fig, transparent=False):
    buf = io.BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', transparent=transparent)
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

def plot_initial_spectrum(xml_name, wls, pwrs, ranges):
    setup_matplotlib()
    total_auc = trapz_func(pwrs, wls)
    if total_auc == 0: total_auc = 1e-9
    
    fig_spec, ax_spec = plt.subplots(figsize=(7, 4))
    points = np.array([wls, pwrs]).T.reshape(-1, 1, 2)
    segments = np.concatenate([points[:-1], points[1:]], axis=1)
    norm = plt.Normalize(380, 780)
    # 'turbo' es un arcoíris genérico. Aquí el eje ya ES longitud de onda, así
    # que la curva se colorea con el color real de cada lambda usando la misma
    # función que pinta la banda inferior: el color deja de ser decorativo.
    _spec_cmap = mcolors.LinearSegmentedColormap.from_list(
        'evolux_spectral', [wavelength_to_rgb(w) for w in np.linspace(380, 780, 96)])
    lc = LineCollection(segments, cmap=_spec_cmap, norm=norm)
    lc.set_array(wls)
    lc.set_linewidth(2.5)
    ax_spec.add_collection(lc)
    
    colors = BAND_COLORS
    labels_es = {'blue': 'Azul', 'green': 'Verde', 'red': 'Rojo'}
    
    for color_name, (w_min, w_max) in ranges.items():
        mask = (wls >= w_min) & (wls <= w_max)
        if np.any(mask):
            pct = (trapz_func(pwrs[mask], wls[mask]) / total_auc) * 100
            label = rf"{labels_es.get(color_name, color_name)} ({w_min}-{w_max}nm): {pct:.1f}%"
            ax_spec.fill_between(wls, pwrs, where=mask, color=colors.get(color_name, 'gray'), alpha=0.3, label=label)
    
    for wl_i in range(len(wls)-1):
        if 380 <= wls[wl_i] <= 780:
            c_rgb = wavelength_to_rgb(wls[wl_i])
            ax_spec.axvspan(wls[wl_i], wls[wl_i+1], ymin=0, ymax=0.035, color=c_rgb, alpha=0.7, zorder=1)

    ax_spec.set_title(rf"Espectro absoluto inicial (0m) - {xml_name}")
    ax_spec.set_xlabel(r"Longitud de onda $[nm]$")
    ax_spec.set_ylabel(r"Potencia radiométrica relativa")
    ax_spec.legend(loc='upper right', fontsize=9)
    ax_spec.grid(True, linestyle=':', alpha=0.6)
    ax_spec.set_xlim(380, 780)
    ax_spec.set_ylim(0, np.max(pwrs) * 1.1)
    return get_base64_image(fig_spec, transparent=True)

def plot_env_optics(wls_env, kd_env_plot, titulo_escenario, y_label_env):
    setup_matplotlib()
    fig_env, ax_env = plt.subplots(figsize=(7, 4))
    ax_env.plot(wls_env, kd_env_plot, 'k-', linewidth=2.5)

    for wl_i in range(len(wls_env)-1):
        if 380 <= wls_env[wl_i] <= 780:
            c_rgb = wavelength_to_rgb(wls_env[wl_i])
            ax_env.axvspan(wls_env[wl_i], wls_env[wl_i+1], ymin=0, ymax=0.035, color=c_rgb, alpha=0.7, zorder=1)

    ax_env.set_title(rf"Caracterización Óptica del Medio")
    ax_env.set_xlabel("Longitud de onda [nm]")
    ax_env.set_ylabel(y_label_env)
    ax_env.grid(True, linestyle=':', alpha=0.6)
    ax_env.set_xlim(380, 780)
    
    ymin_plot, ymax_plot = np.min(kd_env_plot), np.max(kd_env_plot)
    if ymin_plot == ymax_plot:
        ax_env.set_ylim(max(0, ymin_plot - 0.1), ymax_plot + 0.1)
    else:
        ax_env.set_ylim(max(0, ymin_plot - 0.1), ymax_plot * 1.1)

    return get_base64_image(fig_env, transparent=True)

def plot_normalized_shift(xml_name, wls, pwrs, kd_interp_plot, target_depths, ref_z, env_type):
    setup_matplotlib()
    colors_depth = CATEGORICAL
    
    fig_norm, ax_norm = plt.subplots(figsize=(7, 4))
    ax_norm.plot(wls, pwrs / np.max(pwrs), 'k--', label="Emisión inicial", linewidth=2)

    valid_plots = 0
    for d in target_depths:
        if valid_plots >= 5: break
        target_z = float(d) if env_type == 'estanque' else -float(d)
        
        if target_z > ref_z: continue
        
        dist = abs(ref_z - target_z)
        trans_pwrs = pwrs * np.exp(-kd_interp_plot * dist)
        if np.max(trans_pwrs) > 0:
            # Identidad por color Y por patrón: el par adyacente más próximo del
            # conjunto queda en la banda ΔE 6-8 para daltonismo, que exige
            # codificación secundaria.
            ax_norm.plot(wls, trans_pwrs / np.max(trans_pwrs),
                         color=colors_depth[valid_plots % len(colors_depth)],
                         linestyle=CATEGORICAL_DASHES[valid_plots % len(CATEGORICAL_DASHES)],
                         label=f"Z = {d}m (\u0394={dist:.1f}m)", linewidth=2)
        valid_plots += 1
    
    for wl_i in range(len(wls)-1):
        if 380 <= wls[wl_i] <= 780:
            c_rgb = wavelength_to_rgb(wls[wl_i])
            ax_norm.axvspan(wls[wl_i], wls[wl_i+1], ymin=0, ymax=0.035, color=c_rgb, alpha=0.7, zorder=1)

    ax_norm.set_title(rf"Color Shift Normalizado - {xml_name}")
    ax_norm.set_xlabel("Longitud de onda [nm]")
    ax_norm.set_ylabel("Espectro auto-normalizado (Máx = 1.0)")
    ax_norm.legend(loc='upper right')
    ax_norm.grid(True, linestyle=':', alpha=0.6)
    ax_norm.set_xlim(380, 780)
    ax_norm.set_ylim(0, 1.1)

    return get_base64_image(fig_norm, transparent=True)

def _roi_metric_enabled(config, key, legacy_key=None):
    metrics = (config or {}).get('roi_plot_metrics', {}) or {}
    if key in metrics:
        return metrics[key] is not False
    if legacy_key and legacy_key in metrics:
        return metrics[legacy_key] is not False
    return metrics.get(key, True) is not False

def _format_roi_stats(roi_stats, config=None):
    if not roi_stats or not roi_stats.get('valid', False):
        return None
    if roi_stats.get('scope') == 'volume':
        lines = [f"ROI volumen: {roi_stats.get('label', '')}"]
        if _roi_metric_enabled(config, 'volume_avg'):
            lines.append(f"Prom vol {roi_stats.get('avg', 0.0):.3f} W/m²")
        if _roi_metric_enabled(config, 'volume_threshold'):
            lines.append(f"V >= umbral {roi_stats.get('volume_ge_threshold', 0.0):.1f} m³")
        if _roi_metric_enabled(config, 'volume_pct'):
            lines.append(f"Cobertura {roi_stats.get('vol_pct', 0.0):.1f}%")
        return "\n".join(lines)
    lines = [f"ROI plano: {roi_stats.get('label', '')}"]
    if _roi_metric_enabled(config, 'plane_area'):
        lines.append(f"Área ROI {roi_stats.get('area', 0.0):.1f} m²")
    if _roi_metric_enabled(config, 'plane_avg'):
        lines.append(f"Prom {roi_stats.get('avg', 0.0):.3f} W/m²")
    if _roi_metric_enabled(config, 'plane_min', legacy_key='plane_minmax'):
        lines.append(f"Min {roi_stats.get('min', 0.0):.3f} W/m²")
    if _roi_metric_enabled(config, 'plane_max', legacy_key='plane_minmax'):
        lines.append(f"Máx {roi_stats.get('max', 0.0):.3f} W/m²")
    peak_fine = roi_stats.get('peak_fine')
    if peak_fine is not None and _roi_metric_enabled(config, 'plane_peak'):
        lines.append(f"Pico real (malla fina) {peak_fine:.1f} W/m²")
    n_over = roi_stats.get('n_lamps_over_max_thr')
    if n_over is not None and _roi_metric_enabled(config, 'plane_stress_lamps'):
        lines.append(f"Lámparas ≥ estrés: {n_over}")
    if _roi_metric_enabled(config, 'plane_threshold'):
        areas = roi_stats.get('area_ge_thresholds') or {}
        thrs = (config or {}).get('contour_vals') or None
        if areas and thrs:
            for thr in sorted({float(t) for t in thrs}):
                a = areas.get(str(float(thr)), roi_stats.get('area_ge_threshold', 0.0))
                lines.append(f"Área ≥ {thr:g}: {a:.1f} m²")
        else:
            lines.append(f"Área >= umbral {roi_stats.get('area_ge_threshold', 0.0):.1f} m²")
    return "\n".join(lines)

def _add_roi_stats_label(ax, x, y, text, ha='center', va='center', transform=None):
    if not text:
        return
    text_kwargs = {
        'ha': ha,
        'va': va,
        'fontsize': 8.5,
        'color': INK,
        'bbox': dict(boxstyle='round,pad=0.35', facecolor=PLATE, edgecolor=PLATE_LINE, alpha=0.94),
        'zorder': 8,
    }
    if transform is not None:
        text_kwargs['transform'] = transform
    ax.text(x, y, text, **text_kwargs)

def _add_heatmap_to_ax(ax, E, X, Y, config, env_dict, contour_val, max_irr_local, roi, depth_val, roi_stats=None):
    scale_type = config.get('color_scale_type', 'log')
    env_type = env_dict['type']
    
    if scale_type == 'log':
        vmin = contour_val if contour_val > 0 else 1e-4
        vmax = max_irr_local if max_irr_local > vmin else vmin + 1.0
        E_plot = np.maximum(E, vmin)
        norm = mcolors.LogNorm(vmin=vmin, vmax=vmax)
        levels = np.logspace(np.log10(vmin), np.log10(vmax), 25)
    else:
        vmin = 0.0
        vmax = max_irr_local if max_irr_local > vmin else vmin + 1.0
        E_plot = E
        norm = mcolors.Normalize(vmin=vmin, vmax=vmax)
        levels = np.linspace(vmin, vmax, 25)
        
    # Rampa de un solo tono: sustituye a YlGnBu_r, que recorría tres tonos
    # (amarillo-verde-azul) y hacía leer cambios de tono como cambios de
    # naturaleza del dato, no de magnitud.
    cmap = _irradiance_cmap().copy()
    if scale_type == 'log':
        cmap.set_under(PLATE)
    
    cf = ax.contourf(X, Y, E_plot, levels=levels, cmap=cmap, norm=norm, extend='min' if scale_type == 'log' else 'neither')
    
    if config.get('draw_contour'):
        thr_list = config.get('contour_vals') or [contour_val]
        thr_list = sorted({float(t) for t in thr_list})
        # Suavizado SÓLO para trazar las isocurvas. En mallas finas con pocos
        # rayos por celda, el ruido Monte Carlo hace que E cruce el umbral en
        # miles de celdas moteadas y el contorno "inunda" el mapa. Suavizamos el
        # campo para dibujar bordes limpios; el heatmap sigue mostrando E crudo.
        try:
            from scipy.ndimage import gaussian_filter
            sigma = max(1.0, E.shape[0] / 300.0)
            E_contour = gaussian_filter(np.asarray(E, dtype=float), sigma=sigma)
        except Exception:
            E_contour = E
        # Los umbrales son estado, no identidad: escala de severidad de menor a
        # mayor, con patrón de línea propio para que no dependan solo del color,
        # y halo para que se lean tanto sobre la zona oscura como sobre la clara.
        for i, thr in enumerate(thr_list):
            if np.max(E_contour) < thr:
                continue
            col, dash, halo_col = _threshold_style(i)
            try:
                CS = ax.contour(X, Y, E_contour, levels=[thr], colors=col,
                                linewidths=2.0, linestyles=[dash])
            except Exception:
                continue

            # matplotlib >= 3.10 retiró ContourSet.collections; el propio
            # ContourSet ya es una Collection. Se prueba la vía moderna primero
            # y se cae a la antigua, en vez de envolver todo en un except que
            # se tragaba el fallo y dejaba las isocurvas sin etiqueta ni halo.
            try:
                CS.set_path_effects(_halo(3.6, halo_col, 0.65))
            except AttributeError:
                for coll in getattr(CS, 'collections', []):
                    coll.set_path_effects(_halo(3.6, halo_col, 0.65))

            try:
                labels = ax.clabel(CS, inline=True, fontsize=8.5,
                                   fmt=f'{thr:g}', colors=col)
                for lab in labels:
                    lab.set_fontweight('bold')
                    lab.set_path_effects(_halo(3.0, halo_col, 0.9))
            except Exception:
                pass

    if env_dict['shape'] == 'circle':
        roi_circle = plt.Circle((env_dict['center_x'], env_dict['center_y']), env_dict['radio'],
                                edgecolor=BOUNDARY, facecolor='none', linestyle='--', linewidth=1.4)
        roi_circle.set_path_effects(_halo(2.6))
        ax.add_patch(roi_circle)
        ax.plot(env_dict['center_x'], env_dict['center_y'], '+', color=BOUNDARY, markersize=9,
                markeredgewidth=1.3, path_effects=_halo(2.6))
    else:
        rect = plt.Rectangle((0, 0), env_dict['x'], env_dict['y'],
                             edgecolor=BOUNDARY, facecolor='none', linestyle='--', linewidth=1.4)
        ax.add_patch(rect)

    roi_label = _format_roi_stats(roi_stats, config)
    roi_type = roi.get('type')
    roi_is_active = roi_stats.get('valid', False) if roi_stats else False

    if roi_type == 'paralelepipedo':
        if abs(depth_val - float(roi.get('cz', 0))) <= float(roi.get('h', 0)) / 2.0:
            rx = float(roi['cx']) - float(roi['l']) / 2
            ry = float(roi['cy']) - float(roi['w']) / 2
            r_rect = plt.Rectangle(
                (rx, ry), float(roi['l']), float(roi['w']),
                edgecolor=ROI_EDGE, facecolor=ROI_FACE,
                linestyle='-.', linewidth=2.5, zorder=4
            )
            ax.add_patch(r_rect)
            if roi_is_active:
                label_x = rx
                if ry + float(roi['w']) + 1.0 <= float(env_dict['y']):
                    label_y = ry + float(roi['w']) + 1.0
                    label_va = 'bottom'
                else:
                    label_y = max(0.0, ry - 1.0)
                    label_va = 'top'
                _add_roi_stats_label(
                    ax,
                    label_x,
                    label_y,
                    roi_label,
                    ha='left',
                    va=label_va
                )
    elif roi_type == 'cilindro':
        if abs(depth_val - float(roi.get('cz', 0))) <= float(roi.get('h', 0)) / 2.0:
            circ = plt.Circle(
                (float(roi['cx']), float(roi['cy'])), float(roi['r']),
                edgecolor=ROI_EDGE, facecolor=ROI_FACE,
                linestyle='-.', linewidth=2.5, zorder=4
            )
            ax.add_patch(circ)
            if roi_is_active:
                cy = float(roi['cy'])
                radius = float(roi['r'])
                if cy + radius + 1.0 <= float(env_dict['y']):
                    label_y = cy + radius + 1.0
                    label_va = 'bottom'
                else:
                    label_y = max(0.0, cy - radius - 1.0)
                    label_va = 'top'
                _add_roi_stats_label(ax, float(roi['cx']), label_y, roi_label, va=label_va)
    elif roi_is_active:
        _add_roi_stats_label(ax, 0.02, 0.98, roi_label, ha='left', va='top', transform=ax.transAxes)

    seen_aerial = seen_sub = False
    for lamp in config.get('lamps', []):
        lz = float(lamp['z'])
        is_aerial = (env_type == 'estanque' and lz > env_dict['z_interface']) or (env_type == 'jaula' and lz < 0)
        alpha = 1.0 if float(lamp.get('power', 0)) > 0 else 0.25
        if is_aerial:
            ax.plot(float(lamp['x']), float(lamp['y']), marker='D', color=LAMP_AERIAL,
                    markeredgecolor=INK, markeredgewidth=1.0, markersize=9, zorder=5, alpha=alpha,
                    label='Lámpara aérea' if not seen_aerial else '')
            seen_aerial = True
        else:
            ax.plot(float(lamp['x']), float(lamp['y']), marker='*', color=LAMP_SUBMERGED,
                    markeredgecolor=INK, markeredgewidth=1.0, markersize=13, zorder=5, alpha=alpha,
                    label='Lámpara sumergida' if not seen_sub else '')
            seen_sub = True
    if seen_aerial or seen_sub:
        ax.legend(loc='upper right', fontsize=8, framealpha=0.8)

    ax.set_aspect('equal')
    ax.set_xlim(0, env_dict['x'])
    ax.set_ylim(0, env_dict['y'])
    ax.grid(True, linestyle=':', alpha=0.4)
    ax.set_xlabel("X (m)")
    ax.set_ylabel("Y (m)")
    return cf

def plot_individual_heatmap(E, X, Y, config, env_dict, contour_val, max_irr, roi, depth_val, stats_text, roi_stats=None):
    setup_matplotlib()
    fig, ax = plt.subplots(figsize=(7, 6), constrained_layout=True)
    cf = _add_heatmap_to_ax(ax, E, X, Y, config, env_dict, contour_val, max_irr, roi, depth_val, roi_stats)
    plt.colorbar(cf, ax=ax, label="$W/m^2$", shrink=0.6, aspect=35, format="%.3f")
    
    if roi.get('type') != 'global':
        props = dict(boxstyle='round', facecolor=PLATE, edgecolor=PLATE_LINE, alpha=0.92)
        ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10, verticalalignment='top', bbox=props)
    
    return get_base64_image(fig)

def plot_hue_angle_heatmap(hue_grid, X, Y, config, env_dict, roi, depth_val, alpha_e_roi=None):
    """Mapa de calidad de luz: ángulo de matiz CIE α_E (°) por celda (Lee et al. 2022).
    El color sigue el matiz angular (rojo≈0/360°, verde≈110°, azul≈240°)."""
    setup_matplotlib()
    env_type = env_dict['type']
    fig, ax = plt.subplots(figsize=(7, 6), constrained_layout=True)

    H = np.ma.masked_invalid(np.asarray(hue_grid, dtype=float))
    cmap = plt.cm.hsv.copy()
    cmap.set_bad(PLATE_LINE)
    cf = ax.pcolormesh(X, Y, H, cmap=cmap, vmin=0.0, vmax=360.0, shading='auto')
    cbar = plt.colorbar(cf, ax=ax, label=r"$\alpha_E$ (matiz, °)", shrink=0.6, aspect=35)
    cbar.set_ticks([0, 60, 120, 180, 240, 300, 360])

    if env_dict['shape'] == 'circle':
        ax.add_patch(plt.Circle((env_dict['center_x'], env_dict['center_y']), env_dict['radio'],
                                edgecolor=BOUNDARY, facecolor='none', linestyle='--', linewidth=1.4))
        ax.plot(env_dict['center_x'], env_dict['center_y'], '+', color=BOUNDARY, markersize=9)
    else:
        ax.add_patch(plt.Rectangle((0, 0), env_dict['x'], env_dict['y'],
                                   edgecolor=BOUNDARY, facecolor='none', linestyle='--', linewidth=1.4))

    for lamp in config.get('lamps', []):
        lz = float(lamp['z'])
        is_aerial = (env_type == 'estanque' and lz > env_dict['z_interface']) or (env_type == 'jaula' and lz < 0)
        ax.plot(float(lamp['x']), float(lamp['y']), marker='D' if is_aerial else '*',
                color=LAMP_AERIAL if is_aerial else LAMP_SUBMERGED, markeredgecolor=INK,
                markersize=9 if is_aerial else 13, zorder=5)

    subtitle = f"α_E ROI = {alpha_e_roi:.1f}°" if alpha_e_roi is not None else "α_E n/d"
    ax.set_title(f"Calidad de luz (matiz) · Z = {depth_val} m\n{subtitle}", fontsize=11)
    ax.set_aspect('equal'); ax.set_xlim(0, env_dict['x']); ax.set_ylim(0, env_dict['y'])
    ax.grid(True, linestyle=':', alpha=0.4); ax.set_xlabel("X (m)"); ax.set_ylabel("Y (m)")
    return get_base64_image(fig)


def plot_combined_heatmaps(heatmaps_data, X, Y, config, env_dict, contour_val, roi, project_title, depths_txt):
    setup_matplotlib()
    num_plots = len(heatmaps_data)
    if num_plots == 0: return ""
    
    fig, axes = plt.subplots(1, num_plots, figsize=(7 * num_plots, 6), constrained_layout=True)
    if num_plots == 1: axes = [axes]
    
    for idx, data in enumerate(heatmaps_data):
        ax = axes[idx]
        cf = _add_heatmap_to_ax(ax, data['E'], X, Y, config, env_dict, contour_val, data['max_irr'], roi, data['depth_val'], data.get('roi_stats'))
        volume_stats = data.get('roi_stats') or {}
        plane_stats = data.get('plane_roi_stats') or {}
        if plane_stats.get('valid') and volume_stats.get('valid') and volume_stats.get('scope') == 'volume':
            plane_parts = []
            volume_parts = []
            if _roi_metric_enabled(config, 'plane_area'):
                plane_parts.append(f"área ROI {plane_stats.get('area', 0.0):.1f} m²")
            if _roi_metric_enabled(config, 'plane_avg'):
                plane_parts.append(f"prom {plane_stats['avg']:.3f} W/m²")
            if _roi_metric_enabled(config, 'plane_min', legacy_key='plane_minmax'):
                plane_parts.append(f"min {plane_stats['min']:.3f}")
            if _roi_metric_enabled(config, 'plane_max', legacy_key='plane_minmax'):
                plane_parts.append(f"máx {plane_stats['max']:.3f}")
            if plane_stats.get('peak_fine') is not None and _roi_metric_enabled(config, 'plane_peak'):
                plane_parts.append(f"pico {plane_stats['peak_fine']:.1f} W/m²")
            if (plane_stats.get('n_lamps_over_max_thr') is not None and
                    _roi_metric_enabled(config, 'plane_stress_lamps')):
                plane_parts.append(f"lámparas≥estrés {plane_stats['n_lamps_over_max_thr']}")
            if _roi_metric_enabled(config, 'plane_threshold'):
                plane_parts.append(f"área≥ {plane_stats['area_ge_threshold']:.1f} m²")
            if _roi_metric_enabled(config, 'volume_avg'):
                volume_parts.append(f"prom {volume_stats['avg']:.3f} W/m²")
            if _roi_metric_enabled(config, 'volume_threshold'):
                volume_parts.append(f"V≥ {volume_stats['volume_ge_threshold']:.1f} m³")
            if _roi_metric_enabled(config, 'volume_pct'):
                volume_parts.append(f"cob {volume_stats['vol_pct']:.1f}%")
            subtitle_lines = []
            if plane_parts:
                subtitle_lines.append(f"Plano: {' · '.join(plane_parts)}")
            if volume_parts:
                subtitle_lines.append(f"Volumen: {' · '.join(volume_parts)}")
            subtitle = "\n".join(subtitle_lines) if subtitle_lines else "ROI activo"
        elif volume_stats.get('valid'):
            roi_parts = []
            if _roi_metric_enabled(config, 'plane_area') and 'area' in volume_stats:
                roi_parts.append(f"área ROI {volume_stats['area']:.1f} m²")
            if _roi_metric_enabled(config, 'plane_avg'):
                roi_parts.append(f"prom {volume_stats['avg']:.3f}")
            if _roi_metric_enabled(config, 'plane_min', legacy_key='plane_minmax'):
                roi_parts.append(f"min {volume_stats['min']:.3f}")
            if _roi_metric_enabled(config, 'plane_max', legacy_key='plane_minmax'):
                roi_parts.append(f"máx {volume_stats['max']:.3f}")
            if volume_stats.get('peak_fine') is not None and _roi_metric_enabled(config, 'plane_peak'):
                roi_parts.append(f"pico {volume_stats['peak_fine']:.1f}")
            if (volume_stats.get('n_lamps_over_max_thr') is not None and
                    _roi_metric_enabled(config, 'plane_stress_lamps')):
                roi_parts.append(f"lámparas≥estrés {volume_stats['n_lamps_over_max_thr']}")
            if _roi_metric_enabled(config, 'plane_threshold') and 'area_ge_threshold' in volume_stats:
                roi_parts.append(f"área≥ {volume_stats['area_ge_threshold']:.1f} m²")
            subtitle = f"ROI: {' · '.join(roi_parts)}" if roi_parts else "ROI activo"
        else:
            subtitle = "ROI fuera del plano"
        ax.set_title(f"Z = {data['depth_val']}m\n{subtitle}", fontsize=11)
        plt.colorbar(cf, ax=ax, shrink=0.5, aspect=20, format="%.3f")

    fig.suptitle(f"Irradiancia simulada a {depths_txt} m del fondo\n({project_title})", fontsize=14, fontfamily='serif')
    return get_base64_image(fig)

def plot_depth_profile(irr_vals_plot, z_vals, cum_vol_pct, env_type, contour_val, profile_step):
    """Perfil vertical: irradiancia acumulada y cobertura volumétrica.

    Antes iba en un solo eje con dos escalas X superpuestas (twiny). Un doble eje
    no tiene origen ni escala común, así que la posición relativa de las dos
    curvas es un artefacto del encuadre: acercarlas o cruzarlas depende de los
    límites elegidos, no del dato. Se separa en dos paneles que comparten el eje
    de profundidad, que es la variable realmente común. Los valores no cambian.
    """
    setup_matplotlib()
    fig_dp, (ax_irr, ax_vol) = plt.subplots(
        1, 2, figsize=(8.4, 5), sharey=True, constrained_layout=True)

    depth_label = 'Profundidad Z [m]' if env_type != 'estanque' else 'Altura desde el fondo [m]'

    # --- Panel 1: irradiancia (log) ---
    ax_irr.plot(irr_vals_plot, z_vals, color=CATEGORICAL[0], linewidth=2.2,
                linestyle=CATEGORICAL_DASHES[0])
    ax_irr.set_xscale('log')
    ax_irr.set_xlabel('Irradiancia promedio volumétrica\n[W/m²] (log)', weight='bold')
    ax_irr.set_ylabel(depth_label, weight='bold')
    ax_irr.xaxis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0, 2.0, 5.0), numticks=15))
    ax_irr.xaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: '{:g}'.format(y)))
    ax_irr.yaxis.set_major_locator(ticker.MaxNLocator(nbins=20))
    ax_irr.grid(True, which='major', linestyle='-')
    ax_irr.grid(True, which='minor', linestyle=':', alpha=0.22)

    # --- Panel 2: cobertura volumétrica ---
    ax_vol.plot(cum_vol_pct, z_vals, color=CATEGORICAL[1], linewidth=2.2,
                linestyle=CATEGORICAL_DASHES[1])
    ax_vol.set_xlabel(f'% volumen acumulado\n(≥ {contour_val} W/m²)', weight='bold')
    ax_vol.set_xlim(-2, 102)
    ax_vol.xaxis.set_major_locator(ticker.MultipleLocator(20))
    ax_vol.grid(True, which='major', linestyle='-')

    if env_type != 'estanque':
        ax_irr.invert_yaxis()

    fig_dp.suptitle("Perfil volumétrico acumulado", fontsize=12)
    return get_base64_image(fig_dp)

def plot_comparison(m_arr, s_arr, z_arr, env_type, comp_x, comp_y, r2, rmse):
    setup_matplotlib()
    fig_comp, ax_comp = plt.subplots(figsize=(6, 5))
    ax_comp.plot(m_arr, z_arr, marker='o', color=CATEGORICAL[0], label='Medición',
                 markersize=6, linewidth=2, linestyle=CATEGORICAL_DASHES[0])
    ax_comp.plot(s_arr, z_arr, marker='s', color=CATEGORICAL[1], label='Simulación',
                 markersize=6, linewidth=2, linestyle=CATEGORICAL_DASHES[1])
    
    ax_comp.set_ylabel(r"Profundidad $Z$ $[m]$" if env_type != 'estanque' else r"Altura desde el fondo $Z$ $[m]$")
    if env_type != 'estanque':
        ax_comp.invert_yaxis()
        
    ax_comp.set_title(rf"Atenuación: Simulación vs Medición en $(X={comp_x}, Y={comp_y})$")
    ax_comp.set_xlabel(r"Irradiancia $[W/m^2]$")
    ax_comp.text(0.95, 0.05, f"Métricas:\n$R^2$: {r2:.4f}\nRMSE: {rmse:.4f}", transform=ax_comp.transAxes, fontsize=10,
                 verticalalignment='bottom', horizontalalignment='right', bbox=dict(boxstyle='round', facecolor=PLATE, edgecolor=PLATE_LINE, alpha=0.92))
    ax_comp.grid(True, linestyle=':', alpha=0.6)
    ax_comp.legend(loc='upper right')
    return get_base64_image(fig_comp)
