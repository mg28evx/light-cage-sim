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
        "figure.dpi": 150 
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
    lc = LineCollection(segments, cmap='turbo', norm=norm)
    lc.set_array(wls)
    lc.set_linewidth(2.5)
    ax_spec.add_collection(lc)
    
    colors = {'blue': '#1f77b4', 'green': '#2ca02c', 'red': '#d62728'}
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
    colors_depth = ['#1f77b4', '#d62728', '#2ca02c', '#9467bd', '#8c564b']
    
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
            ax_norm.plot(wls, trans_pwrs / np.max(trans_pwrs), color=colors_depth[valid_plots % len(colors_depth)], label=f"Z = {d}m (\u0394={dist:.1f}m)", linewidth=2)
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

def _roi_metric_enabled(config, key):
    metrics = (config or {}).get('roi_plot_metrics', {}) or {}
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
    if _roi_metric_enabled(config, 'plane_avg'):
        lines.append(f"Prom {roi_stats.get('avg', 0.0):.3f} W/m²")
    if _roi_metric_enabled(config, 'plane_minmax'):
        lines.append(f"Min {roi_stats.get('min', 0.0):.3f} W/m²")
        lines.append(f"Máx {roi_stats.get('max', 0.0):.3f} W/m²")
    if _roi_metric_enabled(config, 'plane_threshold'):
        lines.append(f"Área >= umbral {roi_stats.get('area_ge_threshold', 0.0):.1f} m²")
    return "\n".join(lines)

def _add_roi_stats_label(ax, x, y, text, ha='center', va='center', transform=None):
    if not text:
        return
    text_kwargs = {
        'ha': ha,
        'va': va,
        'fontsize': 8.5,
        'color': '#4b0055',
        'bbox': dict(boxstyle='round,pad=0.35', facecolor='white', edgecolor='#cc00cc', alpha=0.88),
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
        
    cmap = plt.cm.YlGnBu_r.copy()
    if scale_type == 'log':
        cmap.set_under('#ffffff')
    
    cf = ax.contourf(X, Y, E_plot, levels=levels, cmap=cmap, norm=norm, extend='min' if scale_type == 'log' else 'neither')
    
    if config.get('draw_contour') and np.max(E) >= contour_val:
        try:
            CS_high = ax.contour(X, Y, E, levels=[contour_val], colors='lime', linewidths=2.5)
            ax.clabel(CS_high, inline=True, fontsize=9, fmt=f'{contour_val}', colors='lime')
        except Exception: pass

    if env_dict['shape'] == 'circle':
        roi_circle = plt.Circle((env_dict['center_x'], env_dict['center_y']), env_dict['radio'], edgecolor='cyan', facecolor='none', linestyle='--', linewidth=2)
        ax.add_patch(roi_circle)
        ax.plot(env_dict['center_x'], env_dict['center_y'], '+', color='cyan', markersize=10)
    else:
        rect = plt.Rectangle((0, 0), env_dict['x'], env_dict['y'], edgecolor='cyan', facecolor='none', linestyle='--', linewidth=2)
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
                edgecolor='magenta', facecolor=(1, 0, 1, 0.08),
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
                edgecolor='magenta', facecolor=(1, 0, 1, 0.08),
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
            ax.plot(float(lamp['x']), float(lamp['y']), marker='D', color='#FFD700',
                    markeredgecolor='black', markersize=9, zorder=5, alpha=alpha,
                    label='Lámpara aérea' if not seen_aerial else '')
            seen_aerial = True
        else:
            ax.plot(float(lamp['x']), float(lamp['y']), marker='*', color='#00BFFF',
                    markeredgecolor='black', markersize=13, zorder=5, alpha=alpha,
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
        props = dict(boxstyle='round', facecolor='white', alpha=0.8)
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
    cmap.set_bad('#f2f2f2')
    cf = ax.pcolormesh(X, Y, H, cmap=cmap, vmin=0.0, vmax=360.0, shading='auto')
    cbar = plt.colorbar(cf, ax=ax, label=r"$\alpha_E$ (matiz, °)", shrink=0.6, aspect=35)
    cbar.set_ticks([0, 60, 120, 180, 240, 300, 360])

    if env_dict['shape'] == 'circle':
        ax.add_patch(plt.Circle((env_dict['center_x'], env_dict['center_y']), env_dict['radio'],
                                edgecolor='k', facecolor='none', linestyle='--', linewidth=1.5))
        ax.plot(env_dict['center_x'], env_dict['center_y'], '+', color='k', markersize=9)
    else:
        ax.add_patch(plt.Rectangle((0, 0), env_dict['x'], env_dict['y'],
                                   edgecolor='k', facecolor='none', linestyle='--', linewidth=1.5))

    for lamp in config.get('lamps', []):
        lz = float(lamp['z'])
        is_aerial = (env_type == 'estanque' and lz > env_dict['z_interface']) or (env_type == 'jaula' and lz < 0)
        ax.plot(float(lamp['x']), float(lamp['y']), marker='D' if is_aerial else '*',
                color='#FFD700' if is_aerial else '#00BFFF', markeredgecolor='black',
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
            if _roi_metric_enabled(config, 'plane_avg'):
                plane_parts.append(f"prom {plane_stats['avg']:.3f} W/m²")
            if _roi_metric_enabled(config, 'plane_minmax'):
                plane_parts.append(f"min {plane_stats['min']:.3f}")
                plane_parts.append(f"máx {plane_stats['max']:.3f}")
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
            if _roi_metric_enabled(config, 'plane_avg'):
                roi_parts.append(f"prom {volume_stats['avg']:.3f}")
            if _roi_metric_enabled(config, 'plane_minmax'):
                roi_parts.append(f"min {volume_stats['min']:.3f}")
                roi_parts.append(f"máx {volume_stats['max']:.3f}")
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
    setup_matplotlib()
    fig_dp, ax_dp = plt.subplots(figsize=(6, 5))
    
    ax_dp.plot(irr_vals_plot, z_vals, 'b-', label='Irradiancia prom. acumulada', linewidth=2.5)
    ax_dp.set_xscale('log')
    ax_dp.set_xlabel('Irradiancia promedio volumétrica [W/m²] (Log)', color='b', weight='bold')
    ax_dp.tick_params(axis='x', labelcolor='b')
    
    ax_dp.set_ylabel('Profundidad Z [m]' if env_type != 'estanque' else 'Altura desde el fondo [m]', weight='bold')
    
    ax_dp.xaxis.set_major_locator(ticker.LogLocator(base=10.0, subs=(1.0, 2.0, 5.0), numticks=15))
    ax_dp.xaxis.set_major_formatter(ticker.FuncFormatter(lambda y, _: '{:g}'.format(y)))
    ax_dp.yaxis.set_major_locator(ticker.MaxNLocator(nbins=20))
    ax_dp.grid(True, which='major', linestyle='-', alpha=0.6)
    ax_dp.grid(True, which='minor', linestyle=':', alpha=0.3)
    
    if env_type != 'estanque':
        ax_dp.invert_yaxis()
    
    ax_vol = ax_dp.twiny()
    ax_vol.plot(cum_vol_pct, z_vals, 'm-', label='% Vol. iluminado acumulado', linewidth=2.5)
    ax_vol.set_xlabel(f'% Volumen acumulado (>= {contour_val} W/m²)', color='m', weight='bold')
    ax_vol.tick_params(axis='x', labelcolor='m')
    ax_vol.set_xlim(-5, 105)
    ax_vol.xaxis.set_major_locator(ticker.MultipleLocator(10))
    
    lines_1, labels_1 = ax_dp.get_legend_handles_labels()
    lines_2, labels_2 = ax_vol.get_legend_handles_labels()
    ax_dp.legend(lines_1 + lines_2, labels_1 + labels_2, loc='lower right')
    
    fig_dp.suptitle(f"Perfil volumétrico acumulado", fontsize=12)
    plt.tight_layout()
    return get_base64_image(fig_dp)

def plot_comparison(m_arr, s_arr, z_arr, env_type, comp_x, comp_y, r2, rmse):
    setup_matplotlib()
    fig_comp, ax_comp = plt.subplots(figsize=(6, 5))
    ax_comp.plot(m_arr, z_arr, 'b-o', label='Medición', markersize=6, linewidth=2)
    ax_comp.plot(s_arr, z_arr, 'r--s', label='Simulación', markersize=6, linewidth=2)
    
    ax_comp.set_ylabel(r"Profundidad $Z$ $[m]$" if env_type != 'estanque' else r"Altura desde el fondo $Z$ $[m]$")
    if env_type != 'estanque':
        ax_comp.invert_yaxis()
        
    ax_comp.set_title(rf"Atenuación: Simulación vs Medición en $(X={comp_x}, Y={comp_y})$")
    ax_comp.set_xlabel(r"Irradiancia $[W/m^2]$")
    ax_comp.text(0.95, 0.05, f"Métricas:\n$R^2$: {r2:.4f}\nRMSE: {rmse:.4f}", transform=ax_comp.transAxes, fontsize=10,
                 verticalalignment='bottom', horizontalalignment='right', bbox=dict(boxstyle='round', facecolor='white', alpha=0.8))
    ax_comp.grid(True, linestyle=':', alpha=0.6)
    ax_comp.legend(loc='upper right')
    return get_base64_image(fig_comp)
