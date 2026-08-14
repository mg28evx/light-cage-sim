window.measurements = [];
window.lastResults = null;
window.lastPayload = null;
window.lampProfiles = {}; 
window.opticalCenters = [];
window.currentOpticalPresets = null;
window.currentOpticalWeeklyProfile = null;
window.bioOpticalScenarios = [];
let lampCount = 0; 
let currentAbortController = null;

const modeConfigs = {
    'estanque': { type: 'estanque', shape: 'circle', radio: 10, z_water: 3.2, env_z: 15.0, depths: '2.0, 1.0', kd_list: '0.20', n1: 1.0, n2: 1.33 },
    'jaula': { type: 'jaula', shape: 'rect', env_x: 30, env_y: 30, z_water: 20.0, env_z: 15.0, depths: '5.0, 10.0, 15.0', kd_list: '0.50', n1: 1.0, n2: 1.33 }
};

let currentSpaceType = 'estanque';

window.togglePreviewMode = window.togglePreviewMode || function togglePreviewModeFallback(mode) {
    const div2d = document.getElementById('heatmap_div_preview');
    const div3d = document.getElementById('scene3d_preview');
    const btn2d = document.getElementById('btn_preview_2d');
    const btn3d = document.getElementById('btn_preview_3d');
    const is3d = mode === '3d';

    if (div2d) setShown(div2d, !is3d);
    if (div3d) {
        setShown(div3d, is3d);
        if (is3d && !window.scene3dModuleReady) {
            div3d.innerHTML = '<div class="scene3d-loading">Cargando visor 3D...</div>';
            setTimeout(() => {
                if (!window.scene3dModuleReady && !div3d.classList.contains('is-hidden')) {
                    div3d.innerHTML = '<div class="scene3d-loading scene3d-error">No se pudo inicializar Three.js. Reinicia el servidor y recarga la página.</div>';
                }
            }, 2500);
        }
    }
    if (btn2d) btn2d.classList.toggle('active', !is3d);
    if (btn3d) btn3d.classList.toggle('active', is3d);
};

/* =============================================================================
 *  UTILIDADES DE INTERFAZ
 * ========================================================================== */

/** Muestra u oculta un elemento sin destruir su modo de display (flex/grid).
 *  Sustituye el uso directo de style.display, que aplanaba a 'block' los
 *  contenedores flex y rompía su espaciado. */
function setShown(target, visible) {
    const el = (typeof target === 'string') ? document.getElementById(target) : target;
    if (!el) return;
    el.classList.toggle('is-hidden', !visible);
    if (el.style.display === 'none' || el.style.display === 'block') el.style.display = '';
}

let statusResetTimer = null;

function showStatusMessage(msg, color = null) {
    const status = document.getElementById('status-text');
    const box = document.getElementById('runstate');
    if (!status) return;
    status.innerText = msg;
    status.style.color = color || '';
    if (box) box.classList.toggle('is-error', color === 'red' || color === '#d9534f');
    clearTimeout(statusResetTimer);
    statusResetTimer = setTimeout(() => {
        status.innerText = "Listo";
        status.style.color = '';
        if (box) box.classList.remove('is-error');
    }, 4000);
}

/** Estado de progreso de la corrida en la barra superior. */
function setRunProgress(state, label) {
    const box = document.getElementById('runstate');
    const fill = document.getElementById('runstate_fill');
    const bar = box ? box.querySelector('.runstate__bar') : null;
    if (!box) return;
    box.classList.toggle('is-busy', state === 'busy');
    box.classList.toggle('is-error', state === 'error');
    box.classList.toggle('is-done', state === 'done');
    if (fill && state !== 'busy') {
        const pct = state === 'done' ? 100 : 0;
        fill.style.width = pct + '%';
        if (bar) bar.setAttribute('aria-valuenow', String(pct));
    }
    if (label) {
        const status = document.getElementById('status-text');
        if (status) { clearTimeout(statusResetTimer); status.innerText = label; }
    }
}

/* --- Navegación por secciones (sustituye el acordeón apilado) ------------- */

const SECTION_META = {
    geometry: { title: 'Geometría del entorno',    help: 'environment_geometry' },
    lamps:    { title: 'Lámparas y focos',          help: 'lamp_photometry' },
    optics:   { title: 'Óptica y medio acuático',   help: 'propagation_modes' },
    params:   { title: 'Parámetros y gráficos',     help: 'sampling_and_metric' },
    bio:      { title: 'Bio-óptica Caligus',        help: 'biooptical_caligus' },
    scene3d:  { title: 'Visualización 3D',          help: 'scene3d_render' },
    measure:  { title: 'Medición y comparación',    help: 'measurement_import' }
};

function setActiveSection(key) {
    const meta = SECTION_META[key];
    if (!meta) return;

    document.querySelectorAll('.rail__btn').forEach(btn => {
        const on = btn.dataset.section === key;
        btn.classList.toggle('is-active', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    document.querySelectorAll('.config-section').forEach(sec => {
        sec.classList.toggle('is-active', sec.id === 'section_' + key);
    });

    const title = document.getElementById('active_section_title');
    if (title) title.textContent = meta.title;
    const help = document.getElementById('active_section_help');
    if (help) help.setAttribute('onclick', `showContextHelp(event, '${meta.help}')`);

    const body = document.querySelector('.config-panel__body');
    if (body) body.scrollTop = 0;

    try { localStorage.setItem('evolux_section', key); } catch (e) {}
    setTimeout(updateScene, 60);
}

/* --- Densidad de la interfaz --------------------------------------------- */

function applyDensity(mode) {
    document.documentElement.setAttribute('data-density', mode);
    const btn = document.getElementById('btn_density');
    if (btn) btn.textContent = mode === 'compact' ? '⇔ Cómodo' : '⇔ Compacto';
    try { localStorage.setItem('evolux_density', mode); } catch (e) {}
    setTimeout(() => { try { window.dispatchEvent(new Event('resize')); } catch (e) {} }, 80);
}

function toggleDensity() {
    const current = document.documentElement.getAttribute('data-density') || 'comfortable';
    applyDensity(current === 'compact' ? 'comfortable' : 'compact');
}

/** En pantallas estrechas el panel de corrida se superpone en vez de robar ancho. */
function toggleRunPanel() {
    const panel = document.getElementById('summary_container');
    if (panel) panel.classList.toggle('is-open');
}

function getLampPrefix(xmlName) {
    let base = xmlName.replace(/\.(xml|ies)$/i, '').trim();
    let parts = base.split(/[\s_\-]+/); 
    let prefix = "";
    if (parts.length > 1) {
        prefix = parts.slice(0, 3).map(p => p.charAt(0).toUpperCase()).join('');
    } else {
        prefix = base.substring(0, 3).toUpperCase();
    }
    return prefix;
}

function updateLampNames() {
    const containers = document.querySelectorAll('.lamp-group-container');
    containers.forEach(container => {
        const model = container.getAttribute('data-model');
        const prefix = getLampPrefix(model);
        const items = container.querySelectorAll('.lamp-item');
        
        const profile = window.lampProfiles[model];
        let extraInfo = '';
        if (profile && profile.elec_power && profile.efficiency) {
            let wpe = (profile.efficiency * 100).toFixed(1);
            extraInfo = ` <span class="wpe-note">[Eficiencia WPE: ${wpe}%]</span>`;
        }

        items.forEach((item, index) => {
            const label = `${prefix}${index + 1}`;
            item.setAttribute('data-label', label);
            const titleEl = item.querySelector('.lamp-title-text');
            if(titleEl) titleEl.innerHTML = `${label} - ${model}${extraInfo}`;
        });
    });
}

function togglePinealParams() {
    const el = document.getElementById('irradiance_type');
    const panel = document.getElementById('pineal_params');
    if (el && panel) {
        setShown(panel, el.value === 'pineal');
    }
}

async function fetchLampProfile(xml_name) {
    if (!xml_name) return null;
    
    const applyDataToUI = (data) => {
        document.querySelectorAll('.lamp-item').forEach(item => {
            if (item.querySelector('.lamp-xml').value === xml_name) {
                const effInput = item.querySelector('.lamp-eff');
                if (effInput && data.efficiency) {
                    effInput.value = data.efficiency;
                }
                updateLampEfficiency(item.querySelector('.lamp-power'));
            }
        });
        updateLampNames();
    };

    if (window.lampProfiles[xml_name]) {
        applyDataToUI(window.lampProfiles[xml_name]);
        updateScene();
        return window.lampProfiles[xml_name];
    }
    
    try {
        const res = await fetch('/api/lamp_profile/' + encodeURIComponent(xml_name));
        const data = await res.json();
        if (!data.error) {
            window.lampProfiles[xml_name] = data;
            applyDataToUI(data);
            updateScene();
            return data;
        }
    } catch(e) { console.error("Error trayendo curva polar", e); }
}

// =============================================================================
//  Visualizador de lámparas (polar IES + beam 3D)
// =============================================================================
function ensureLampDiagModal() {
    let modal = document.getElementById('lamp_diag_modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'lamp_diag_modal';
    modal.style.cssText = 'display:none; position:fixed; top:0; left:0; width:100vw; height:100vh; background:rgba(0,0,0,0.55); z-index:9999; align-items:center; justify-content:center;';
    modal.innerHTML = `
        <div id="lamp_diag_box" class="lamp-diag__box">
            <div class="lamp-diag__head">
                <h3 id="lamp_diag_title" class="lamp-diag__title">Inspección de lámpara</h3>
                <button type="button" class="btn" onclick="closeLampDiagnostic()">Cerrar ✕</button>
            </div>
            <div class="lamp-diag__tabs">
                <button type="button" class="btn grow" id="lamp_diag_tab_polar" onclick="switchLampDiagTab('polar')">Polar IES (C0/180 y C90/270)</button>
                <button type="button" class="btn grow" id="lamp_diag_tab_3d" onclick="switchLampDiagTab('3d')">Beam 3D</button>
            </div>
            <div id="lamp_diag_meta" class="lamp-diag__meta"></div>
            <div id="lamp_diag_polar_plot" class="lamp-diag__plot"></div>
            <div id="lamp_diag_3d_plot" class="lamp-diag__plot is-hidden"></div>
        </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', (e) => { if (e.target === modal) closeLampDiagnostic(); });
    return modal;
}

function closeLampDiagnostic() {
    const m = document.getElementById('lamp_diag_modal');
    if (m) m.style.display = 'none';
}

function switchLampDiagTab(which) {
    const polar = document.getElementById('lamp_diag_polar_plot');
    const beam3 = document.getElementById('lamp_diag_3d_plot');
    const tabP = document.getElementById('lamp_diag_tab_polar');
    const tabB = document.getElementById('lamp_diag_tab_3d');
    if (which === 'polar') {
        polar.style.display = 'block'; beam3.style.display = 'none';
        tabP.style.background = 'var(--evolux-yellow)'; tabP.style.fontWeight = 'bold';
        tabB.style.background = '#fff'; tabB.style.fontWeight = 'normal';
    } else {
        polar.style.display = 'none'; beam3.style.display = 'block';
        tabB.style.background = 'var(--evolux-yellow)'; tabB.style.fontWeight = 'bold';
        tabP.style.background = '#fff'; tabP.style.fontWeight = 'normal';
        // Forzar relayout en caso de que el div estuviera oculto al crear la figura
        try { Plotly.Plots.resize(beam3); } catch(e) {}
    }
}

async function showLampDiagnostic(xml, initialTab) {
    const modal = ensureLampDiagModal();
    document.getElementById('lamp_diag_title').textContent = `Inspección de lámpara: ${xml.replace(/\.(xml|ies)$/i, '')}`;
    modal.style.display = 'flex';

    let profile = window.lampProfiles[xml];
    if (!profile) {
        profile = await fetchLampProfile(xml);
    }
    if (!profile) {
        document.getElementById('lamp_diag_meta').textContent = 'No se pudo cargar el perfil radiométrico de esta lámpara.';
        return;
    }

    const meta = [];
    if (profile.elec_power) meta.push(`Potencia eléctrica: <strong>${Number(profile.elec_power).toFixed(1)} W</strong>`);
    if (profile.rad_power) meta.push(`Flujo radiante: <strong>${Number(profile.rad_power).toFixed(1)} W</strong>`);
    if (profile.efficiency) meta.push(`WPE: <strong>${(profile.efficiency * 100).toFixed(1)}%</strong>`);
    document.getElementById('lamp_diag_meta').innerHTML = meta.join(' · ');

    // --- Curva polar (C0/180 y C90/270) en plotly polar -------------------
    const polarData = [
        {
            type: 'scatterpolar',
            r: profile.c0_180.rad,
            theta: profile.c0_180.theta,
            mode: 'lines', name: 'C0 / C180', line: { color: '#1f77b4', width: 3 }
        },
        {
            type: 'scatterpolar',
            r: profile.c90_270.rad,
            theta: profile.c90_270.theta,
            mode: 'lines', name: 'C90 / C270', line: { color: '#d62728', width: 3, dash: 'dot' }
        }
    ];
    const polarLayout = {
        title: { text: 'Distribución polar normalizada (radiante)', font: { size: 13 } },
        polar: {
            radialaxis: { tickformat: '.1f', range: [0, 1.05], showticklabels: true },
            angularaxis: { tickfont: { size: 10 }, rotation: 90, direction: 'clockwise' }
        },
        margin: { l: 50, r: 50, t: 60, b: 30 },
        showlegend: true
    };
    Plotly.newPlot('lamp_diag_polar_plot', polarData, polarLayout, { responsive: true });

    // --- Beam 3D (superficie sobre esfera normalizada por intensidad) ----
    const sg = profile.sphere_grid;
    if (sg && sg.rad_norm && sg.rad_norm.length) {
        const nH = sg.h_deg.length, nV = sg.v_deg.length;
        // r = intensidad normalizada (0..1) — escala visual
        const X = [], Y = [], Z = [], C = [];
        for (let i = 0; i < nH; i++) {
            const xr = [], yr = [], zr = [], cr = [];
            const phi = sg.h_deg[i] * Math.PI / 180;
            for (let j = 0; j < nV; j++) {
                const theta = sg.v_deg[j] * Math.PI / 180;
                const r = Math.max(sg.rad_norm[i][j], 0.001); // evita degenerate
                xr.push(r * Math.sin(theta) * Math.cos(phi));
                yr.push(r * Math.sin(theta) * Math.sin(phi));
                zr.push(-r * Math.cos(theta));               // lámpara apunta -Z
                cr.push(sg.rad_norm[i][j]);
            }
            X.push(xr); Y.push(yr); Z.push(zr); C.push(cr);
        }
        const beamData = [{
            type: 'surface', x: X, y: Y, z: Z, surfacecolor: C,
            colorscale: 'Hot', cmin: 0, cmax: 1, showscale: true,
            colorbar: { title: 'I(θ,φ) normalizada', thickness: 14 },
            contours: { z: { show: false } }
        }];
        const beamLayout = {
            title: { text: 'Lóbulo radiante 3D (radio ∝ I normalizada)', font: { size: 13 } },
            scene: {
                xaxis: { title: 'X', range: [-1.1, 1.1] },
                yaxis: { title: 'Y', range: [-1.1, 1.1] },
                zaxis: { title: 'Z (−z = abajo)', range: [-1.1, 1.1] },
                aspectmode: 'cube',
                camera: { eye: { x: 1.4, y: 1.4, z: 0.6 } }
            },
            margin: { l: 0, r: 0, t: 40, b: 0 }
        };
        Plotly.newPlot('lamp_diag_3d_plot', beamData, beamLayout, { responsive: true });
    } else {
        document.getElementById('lamp_diag_3d_plot').innerHTML = '<p class="empty-note">Grilla 3D no disponible para esta lámpara.</p>';
    }

    switchLampDiagTab(initialTab || 'polar');
    return null;
}

function toggleOpticsPanel() {
    const mode = document.getElementById('optics_mode').value;
    setShown('optics_kd_fijo', mode === 'kd_fijo');
    setShown('optics_kd_espectral', mode === 'kd_espectral');
    setShown('optics_scattering', mode === 'scattering');
    setShown('atten_coef_type_container', mode !== 'scattering');
}

function toggleScatteringMode() {
    const val = document.getElementById('mc_input_type').value;
    setShown('scat_bio', val === 'bio');
    setShown('scat_ras_bardsnes', val === 'ras_bardsnes');
    setShown('scat_scalar', val === 'scalar');
    setShown('scat_spectral', val === 'json');
    if (val === 'scalar') updateSecchiScatter();
    if (val === 'bio') toggleBioParamSource();
}

/* =============================================================================
 *  ORIGEN DE PARÁMETROS BIO-ÓPTICOS
 *  Modalidad seleccionable: manual (por defecto), teledetección o CSV local.
 *  La recuperación satelital deja de ser un bloque permanente y pasa a un
 *  asistente que se abre bajo demanda.
 * ========================================================================== */

const BIO_SOURCE_HINTS = {
    manual: 'Los tres parámetros se ingresan a mano. Ninguna consulta de red se ejecuta en esta modalidad.',
    satellite: 'El asistente consulta productos satelitales, resume la semana ISA elegida y escribe TSS, CDOM y Chl-a. Cada valor queda marcado con su procedencia.',
    csv: 'Cargue observaciones propias (mediciones de terreno o laboratorio). Se aplican las mismas conversiones proxy y cuantiles que en la ruta satelital.'
};

/* Procedencia por parámetro. Se persiste en la configuración para poder
   reconstruir de dónde salió cada número. */
window.bioProvenance = { tss: 'manual', cdom_a440: 'manual', chl: 'manual', detail: null };

function toggleBioParamSource() {
    const sel = document.getElementById('bio_param_source');
    if (!sel) return;
    const mode = sel.value;
    setShown('bio_source_satellite', mode === 'satellite');
    setShown('bio_source_csv', mode === 'csv');
    const hint = document.getElementById('bio_param_source_hint');
    if (hint) hint.textContent = BIO_SOURCE_HINTS[mode] || '';
    try { localStorage.setItem('evolux_bio_param_source', mode); } catch (e) {}
}

const PROVENANCE_LABELS = {
    manual: { text: 'manual', cls: 'badge--manual' },
    satellite: { text: 'satélite', cls: 'badge--sat' },
    proxy: { text: 'proxy FNU→TSS', cls: 'badge--proxy' },
    csv: { text: 'CSV local', cls: 'badge--csv' },
    water_class: { text: 'clase de agua', cls: 'badge--proxy' }
};

function renderBioProvenance() {
    const map = { tss: 'prov_tss', cdom_a440: 'prov_cdom', chl: 'prov_chl' };
    Object.entries(map).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (!el) return;
        const info = PROVENANCE_LABELS[window.bioProvenance[key]] || PROVENANCE_LABELS.manual;
        el.className = 'badge ' + info.cls;
        el.textContent = info.text;
        el.title = window.bioProvenance.detail || 'Valor ingresado manualmente';
    });
    updateRunSummary();
}

/** Un cambio manual sobre el input degrada la procedencia de ese parámetro. */
function markBioParamManual(key) {
    if (window.bioProvenance[key] !== 'manual') {
        window.bioProvenance[key] = 'manual';
        renderBioProvenance();
    }
}

function setBioProvenance(origin, detail, keys) {
    (keys || ['tss', 'cdom_a440', 'chl']).forEach(k => { window.bioProvenance[k] = origin; });
    window.bioProvenance.detail = detail || null;
    renderBioProvenance();
}

function openSatelliteDrawer() {
    const drawer = document.getElementById('satellite_drawer');
    const backdrop = document.getElementById('help_backdrop');
    if (!drawer) return;
    drawer.classList.add('is-open');
    drawer.setAttribute('aria-hidden', 'false');
    if (backdrop) backdrop.classList.add('is-open');
    if (!window.opticalCenters || !window.opticalCenters.length) loadOpticalCenters();
    setTimeout(() => {
        const plot = document.getElementById('optical_weekly_plot');
        if (plot && plot.data) { try { Plotly.Plots.resize(plot); } catch (e) {} }
    }, 260);
}

function closeSatelliteDrawer() {
    const drawer = document.getElementById('satellite_drawer');
    if (drawer) {
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
    }
    syncBackdrop();
}

/** Sube un CSV de observaciones locales y lo deja disponible para el asistente. */
function uploadOpticalObservations(event) {
    const file = event.target.files && event.target.files[0];
    const status = document.getElementById('optical_csv_status');
    if (!file) return;
    const fd = new FormData();
    fd.append('file', file);
    if (status) status.textContent = 'Subiendo ' + file.name + '…';

    fetch('/api/optical_observations/upload', { method: 'POST', body: fd })
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'ok') throw new Error(data.msg || 'Error al subir el archivo');
            window.opticalObservationsPath = data.path;
            if (status) {
                status.textContent = `${file.name}: ${data.rows} filas, ${data.centers} centro(s). Listo para el asistente.`;
            }
            showStatusMessage('Observaciones locales cargadas');
        })
        .catch(err => {
            window.opticalObservationsPath = null;
            if (status) status.textContent = 'Error: ' + err.message;
            showStatusMessage('No se pudo cargar el CSV', 'red');
        })
        .finally(() => { event.target.value = ''; });
}

// Autocompleta TSS desde turbidez con la regresión RAS de Bårdsnes (2020, tanque):
// TSS = 3.0411·NTU − 0.376 (R²=0.86). Deja TSS en 0 si el resultado es negativo.
function updateRasTssFromTurbidity() {
    const ntuEl = document.getElementById('ras_turbidity_ntu');
    const tssEl = document.getElementById('ras_tss');
    if (!ntuEl || !tssEl) return;
    const ntu = parseFloat(ntuEl.value);
    if (isNaN(ntu)) return;
    tssEl.value = Math.max(3.0411 * ntu - 0.376, 0.0).toFixed(3);
}

const contextHelpContent = {
    simulation_workflow: {
        title: 'Cómo funciona el simulador',
        body: `
            El simulador transforma una configuración física y óptica en mapas y métricas de irradiancia mediante ray tracing.<br><br>
            <strong>1. Geometría.</strong> Define el volumen, el sistema de coordenadas y las regiones donde se evaluarán resultados.<br><br>
            <strong>2. Lámparas.</strong> Cada archivo fotométrico aporta la distribución angular y espectral de emisión. La potencia, posición y orientación determinan desde dónde y con qué energía se generan los rayos.<br><br>
            <strong>3. Óptica.</strong> La interfaz aire-agua refracta y refleja rayos; el modo de propagación define cómo se atenúan, absorben o dispersan dentro del agua.<br><br>
            <strong>4. Cálculo y salidas.</strong> El número de rayos controla el muestreo estadístico. Las profundidades, umbrales, ROI y gráficos definen cómo se resumen los resultados.<br><br>
            <strong>5. Visualización 3D.</strong> Permite inspeccionar la configuración, pero sus ajustes de render no cambian la física calculada.<br><br>
            <strong>6. Validación.</strong> Las mediciones permiten estimar Kd y comparar el modelo con datos reales. Para decisiones de diseño, esta etapa es tan importante como la simulación.
        `
    },
    environment_geometry: {
        title: 'Volumen físico y coordenadas',
        body: `
            La geometría delimita el espacio donde se propagan los rayos y donde se construyen los mapas de irradiancia.<br><br>
            <strong>Estanque.</strong> La cota <code>Z</code> se interpreta como altura desde el piso. El radio o las dimensiones <code>X/Y</code> definen el contorno horizontal, y la altura del agua se configura en la lámina óptica.<br><br>
            <strong>Jaula.</strong> <code>X</code> e <code>Y</code> definen el área horizontal y la profundidad total <code>Z</code> define el dominio bajo la superficie. Las profundidades de lámparas y resultados se interpretan desde la superficie hacia abajo.<br><br>
            Los ejes <code>X</code>, <code>Y</code> y <code>Z</code> deben usar el mismo origen y unidades que las posiciones de lámparas, regiones de evaluación y mediciones importadas. Una geometría incoherente desplaza tanto la simulación como la comparación.
        `
    },
    reference_polygon: {
        title: 'Polígono de referencia',
        body: `
            El polígono es una guía visual para distribuir lámparas o representar simetrías operacionales alrededor del centro del espacio.<br><br>
            <strong>Vértices.</strong> Define la cantidad de puntos equidistantes del polígono regular.<br><br>
            <strong>Distancia.</strong> Define la distancia radial desde el centro hasta cada vértice.<br><br>
            Este polígono no crea paredes, no limita el agua y no modifica el cálculo físico. Solo aparece como referencia en la vista previa.
        `
    },
    lamp_photometry: {
        title: 'Fotometría y modelos de lámpara',
        body: `
            Los archivos <code>IES</code> o <code>XML</code> describen cómo una luminaria distribuye su intensidad en distintos ángulos. El motor usa esa fotometría para muestrear la dirección inicial de cada rayo.<br><br>
            Cuando el archivo contiene espectro, potencia eléctrica y eficiencia WPE, el simulador puede estimar la potencia radiante efectiva y muestrear longitudes de onda. Si faltan datos, la interpretación espectral o energética será más aproximada.<br><br>
            <strong>Potencia eléctrica.</strong> Escala la energía emitida por la instancia de lámpara.<br><br>
            <strong>Eficiencia WPE.</strong> Convierte potencia eléctrica en potencia radiante. La distribución fotométrica define la forma del haz; la potencia y eficiencia definen su magnitud.<br><br>
            Use archivos medidos del modelo real cuando se requiera comparar alternativas de diseño.
        `
    },
    lamp_placement: {
        title: 'Posición, orientación y grupos',
        body: `
            Cada lámpara es una instancia independiente del modelo fotométrico seleccionado.<br><br>
            <strong>X, Y y Z.</strong> Definen el origen del haz dentro del mismo sistema de coordenadas de la geometría. En estanques, <code>Z</code> es altura desde el piso; en jaulas, es profundidad desde la superficie.<br><br>
            <strong>Rotaciones X/Y/Z.</strong> Orientan la fotometría antes de emitir los rayos. Una rotación cambia la dirección del haz, pero no su potencia total.<br><br>
            <strong>Parámetros globales por modelo.</strong> Permiten actualizar potencia o altura de todas las instancias de un mismo modelo; una edición manual posterior puede independizar una lámpara específica.<br><br>
            <strong>Aéreas y sumergidas.</strong> Los interruptores permiten incluir o excluir grupos completos de la simulación sin eliminar su configuración.
        `
    },
    water_interface: {
        title: 'Interfaz aire-agua',
        body: `
            <strong>Altura del agua.</strong> En un estanque define la cota vertical donde el rayo cambia de aire a agua. Determina qué luminarias están sobre o bajo la superficie y en qué punto se aplican refracción y pérdidas de Fresnel. En una jaula, la superficie se representa en la cota de referencia del modelo.<br><br>
            <strong>Índices de refracción.</strong> El índice 1 corresponde al medio incidente y el índice 2 al medio transmitido. El motor usa la ley de Snell para cambiar la dirección del rayo y las ecuaciones de Fresnel para calcular la fracción de potencia transmitida o reflejada.<br><br>
            <strong>Valores recomendados.</strong> Aire ≈ 1,00 y agua ≈ 1,33 son valores adecuados para la mayoría de las simulaciones. Modifíquelos solo si el medio está caracterizado. Estos índices afectan la dirección y la transmisión en la superficie, pero no sustituyen la atenuación dentro del agua.
        `
    },
    propagation_modes: {
        title: 'Modos de propagación de luz',
        body: `
            Todos los modos consideran la geometría del entorno y el cruce aire-agua. La diferencia está en cómo representan la pérdida y redistribución de luz dentro del agua.<br><br>
            <strong>Atenuación fija.</strong> Usa un único coeficiente, <code>c</code> o <code>Kd</code>, para todas las longitudes de onda. Es rápido y útil para comparaciones preliminares, pero no representa cambios de color ni dispersión direccional.<br><br>
            <strong>Atenuación espectral.</strong> Usa una curva de <code>c(λ)</code> o <code>Kd(λ)</code>. Permite representar que el agua atenúa colores de forma diferente, pero todavía trata la pérdida como una ley exponencial sin redistribuir fotones por dispersión.<br><br>
            <strong>Trazado 3D dispersivo (Monte Carlo).</strong> Simula eventos de absorción, dispersión, reflexión de paredes y salida por la superficie. Es el modo más físico para evaluar distribución espacial y espectral, pero requiere más parámetros, más rayos y mayor tiempo de cálculo.
        `
    },
    attenuation_type: {
        title: 'Tipo de coeficiente de atenuación',
        body: `
            Este selector se aplica únicamente a los modos <strong>Atenuación fija</strong> y <strong>Atenuación espectral</strong>. No se utiliza en Monte Carlo, donde el motor calcula <code>c(λ) = a(λ) + b(λ)</code> a partir de absorción y dispersión.<br><br>
            <strong>c, atenuación de haz.</strong> Describe la pérdida de un haz colimado a lo largo del camino real recorrido por el rayo: <code>I = I₀·exp(-c·s)</code>. Incluye absorción y luz dispersada fuera del haz. Es recomendable cuando se dispone de mediciones con transmisómetro o cuando se quiere representar físicamente el recorrido oblicuo de una luminaria.<br><br>
            <strong>Kd, atenuación difusa.</strong> Describe cómo disminuye la irradiancia descendente con la profundidad vertical: <code>E<sub>d</sub>(z) = E<sub>d</sub>(0)·exp(-Kd·|Δz|)</code>. Es una propiedad óptica aparente que depende del agua y del campo de iluminación. Es recomendable para datos oceanográficos o satelitales como Kd(490).<br><br>
            <strong>No son intercambiables.</strong> Use <code>c</code> para atenuación de haz medida ópticamente y <code>Kd</code> para irradiancia difusa medida o recuperada por productos oceanográficos. Si necesita absorción, dispersión o reflexión explícitas, utilice Monte Carlo.
        `
    },
    secchi_model: {
        title: 'Modelo de disco de Secchi',
        body: `
            Selecciona cómo se estima la profundidad de disco de Secchi equivalente <code>Z<sub>SD</sub></code> que se reporta en la tabla de resultados. Es una métrica interpretativa de transparencia derivada de los coeficientes ópticos del escenario; no interviene en la propagación de rayos del motor.<br><br>
            <strong>Preisendorfer (1986), clásico.</strong> Teoría de visibilidad acoplada: <code>Z<sub>SD</sub> ≈ 8,69/(c + Kd)</code>, dominada por el coeficiente de atenuación de haz <code>c</code>. Se aplica de forma unificada a ambos tipos de coeficiente: si ingresa <code>c</code> se deriva <code>Kd</code>, y si ingresa <code>Kd</code> se deriva <code>c</code>, con el mismo cierre bio-óptico, de modo que una misma agua entrega el mismo Secchi por cualquier vía.<br><br>
            <strong>Poole–Atkins (1929), clásico de un coeficiente.</strong> Relación empírica <code>Z<sub>SD</sub> ≈ 1,7/Kd</code>. El producto <code>Z·Kd</code> ronda 1,2–1,9 en aguas naturales; 1,7 es un promedio. Si ingresa <code>c</code>, se deriva <code>Kd</code> con el mismo cierre para mantener coherencia.<br><br>
            <strong>Lee et al. (2015), revisado.</strong> <code>Z<sub>SD</sub> = 1/(2,5·Kd<sub>mín</sub>)·ln(|r<sub>T</sub> − r<sub>w</sub>|/C<sub>t</sub>)</code>, gobernada por el <code>Kd</code> mínimo del visible (ventana transparente), no por <code>c</code>. Es el modelo mecanístico más reciente incluido aquí y es preferible en aguas donde <code>c ≫ Kd</code> (fiordo/jaula), donde el modelo clásico tiende a sesgar.<br><br>
            La tabla muestra el valor del modelo activo y, al pasar el cursor, los modelos calculados para comparación.
        `
    },
    phase_function: {
        title: 'Función de fase de dispersión',
        body: `
            Define la distribución angular de cada evento de dispersión en el motor Monte Carlo.<br><br>
            <strong>Henyey–Greenstein.</strong> Forma clásica de un solo parámetro (la asimetría <code>g</code>). Su fracción de retrodispersión queda atada a <code>g</code> (para <code>g=0,85</code>, <code>b<sub>b</sub>/b≈0,036</code>) y representa pobremente el lóbulo hacia atrás.<br><br>
            <strong>Fournier–Forand.</strong> Forma de mayor fidelidad (Fournier & Forand 1994) que reproduce el pico forward agudo y el lóbulo de retrodispersión. Permite fijar la <strong>retrodispersión <code>b<sub>b</sub>/b</code></strong> de forma independiente: el motor resuelve el índice de refracción de partícula que iguala ese valor (a pendiente de Junge <code>μ</code> dada) y muestrea por CDF inversa. Recomendada cuando se quiere control físico de la retrodispersión, que gobierna Kd, reflectancia y visibilidad.
        `
    },
    kd_closure: {
        title: 'Cierre IOP → Kd',
        body: `
            Relación usada para convertir absorción y dispersión en el coeficiente de atenuación difusa <code>Kd</code> (interviene en el Secchi equivalente y las estimaciones de Kd, no en la propagación de rayos).<br><br>
            <strong>Kirk / Gershun.</strong> <code>Kd ≈ (a + (1−g)·b)/μ̄<sub>d</sub></code>, con <code>μ̄<sub>d</sub></code> fijo. Aproximación de cierre simple; se sesga al crecer la dispersión.<br><br>
            <strong>Lee et al. (2005).</strong> <code>Kd = (1 + 0,005·θ<sub>a</sub>)·a + 4,18·(1 − 0,52·e<sup>−10,8·a</sup>)·b<sub>b</sub></code>, con <code>b<sub>b</sub></code> explícito (de la fase activa) y ángulo cenital nominal <code>θ<sub>a</sub></code>. Más fiel en aguas dispersoras.
        `
    },
    monte_carlo_methods: {
        title: 'Métodos ópticos para Monte Carlo',
        body: `
            Monte Carlo necesita separar cuánto se absorbe, cuánto se dispersa y hacia dónde cambia la dirección de cada rayo. El método seleccionado define cómo se obtienen esos parámetros.<br><br>
            <strong>Parametrización bio-óptica espectral.</strong> Convierte TSS, CDOM y Chl-a en absorción <code>a(λ)</code>, dispersión <code>b(λ)</code>, atenuación <code>c(λ)</code> y albedo de dispersión <code>ω(λ)</code>. Es la opción recomendada cuando se dispone de datos ambientales o satelitales, pero no de una medición óptica completa.<br><br>
            <strong>Calibración empírica RAS (Bårdsnes, 2020).</strong> Usa las formas espectrales medidas en agua de RAS: atenuación creciente hacia el azul por CDOM + micropartículas orgánicas finas (pendiente particulada η≈1.8, S<sub>CDOM</sub>≈0.0141 nm⁻¹, conversión turbidez→TSS = 3.0411·NTU − 0.376). La magnitud absoluta no es transferible entre instalaciones: los coeficientes b*₅₅₀ y ω<sub>p</sub> son calibrables con una medición óptica del sistema (c(λ), Kd(λ) o transmitancia).<br><br>
            <strong>Valores escalares globales.</strong> Usa un único <code>c</code> y <code>ω</code> para todo el espectro. Es útil para sensibilidad o cuando solo existe una caracterización global.<br><br>
            <strong>Distribución espectral manual.</strong> Permite ingresar directamente <code>c(λ)</code> y <code>ω(λ)</code>. Es la opción preferida cuando existen mediciones espectrales propias.<br><br>
            La fase de asimetría <code>g</code> controla la dirección de dispersión y el albedo de pared controla la reflexión difusa en el límite del estanque.
        `
    },
    sampling_and_metric: {
        title: 'Muestreo y métrica de irradiancia',
        body: `
            <strong>Rayos simulados.</strong> El ray tracing es un método estadístico: más rayos reducen ruido y estabilizan mapas, promedios e isocurvas, pero aumentan el tiempo de cálculo. Para comparar diseños, use el mismo número de rayos y aumente el muestreo hasta que las métricas relevantes cambien poco entre ejecuciones.<br><br>
            <strong>Irradiancia escalar.</strong> Acumula la magnitud de luz que llega al plano de cálculo, sin ponderar una dirección receptora específica. Es la métrica general para distribución de energía.<br><br>
            <strong>Irradiancia ponderada.</strong> Aplica el peso <code>I₀·[1 + cos(μ)]</code> para rayos dentro del ángulo límite <code>μ_max</code> y descarta los rayos fuera de ese campo receptor. Se utiliza para representar una respuesta direccional tipo pineal, no como sustituto universal de irradiancia escalar.<br><br>
            La normalización divide la ponderación máxima para facilitar comparación de magnitudes. Debe mantenerse consistente entre escenarios.
        `
    },
    maps_and_thresholds: {
        title: 'Mapas, profundidades y umbrales',
        body: `
            <strong>Profundidades a graficar.</strong> Definen los planos horizontales donde el motor acumula impactos y genera mapas. Deben estar dentro del dominio físico y usar la convención vertical correspondiente a estanque o jaula.<br><br>
            <strong>Umbrales de volumen e isocurvas.</strong> Puede ingresar uno o varios valores positivos separados por coma. Para cada umbral, el simulador integra el volumen combinado del ROI y calcula además el volumen individual de cada lámpara mediante el tally 3D; la tabla muestra ambos en m³ y el porcentaje de su dominio de evaluación. Los mismos valores controlan las isocurvas para mantener trazabilidad entre mapa y tabla.<br><br>
            <strong>Escala lineal.</strong> Conserva proporciones absolutas y es adecuada para comparar magnitudes.<br><br>
            <strong>Escala logarítmica.</strong> Hace visibles zonas de baja irradiancia y gradientes amplios, pero puede exagerar visualmente diferencias pequeñas. La escala cambia la presentación, no los valores calculados.
        `
    },
    evaluation_roi: {
        title: 'Volumen de evaluación (ROI)',
        body: `
            La ROI delimita el volumen usado para calcular promedios, mínimos, máximos, flujo integrado y porcentaje de volumen sobre el umbral.<br><br>
            <strong>Global.</strong> Evalúa todo el espacio simulado.<br><br>
            <strong>Paralelepípedo o cilindro.</strong> Permiten aislar una zona productiva, un corredor de interés o una región donde se espera una respuesta biológica específica. Sus dimensiones y centro usan las mismas coordenadas de la geometría.<br><br>
            La ROI no bloquea ni refleja rayos y no modifica la propagación. Solo cambia qué parte del resultado se incluye en las estadísticas.
        `
    },
    lamp_contribution_points: {
        title: 'Aporte lumínico por lámpara',
        body: `
            Esta herramienta calcula cuánto aporta cada lámpara a puntos 3D específicos después de la simulación.<br><br>
            Ingrese cada punto como <code>X,Y,Z</code> en metros y separe varios puntos con punto y coma. Ejemplo: <code>10,10,2; 15,15,1</code>.<br><br>
            El motor incorpora automáticamente las cotas <code>Z</code> solicitadas a los planos de cálculo, interpola la irradiancia en cada coordenada y entrega el total, los W/m² por lámpara y su porcentaje relativo.<br><br>
            Es útil para explicar solapamiento de haces, identificar luminarias dominantes y contrastar ubicaciones de sensores.
        `
    },
    output_reports: {
        title: 'Tablas y gráficos de salida',
        body: `
            Estas opciones controlan qué resultados se presentan y exportan; no cambian la propagación de la luz.<br><br>
            <strong>Tabla resumen.</strong> Puede incluir modelos de lámpara, posiciones, potencia eléctrica efectiva y volumen cubierto para documentar cada escenario.<br><br>
            <strong>Perfil por profundidad.</strong> Resume cómo cambia la cobertura o irradiancia a lo largo de la columna de agua. El paso controla la resolución vertical y el costo adicional de cálculo.<br><br>
            <strong>Métricas ROI en mapas.</strong> Controlan qué estadísticas se anotan sobre los mapas de profundidad. El ROI de plano resume el corte 2D mostrado; el ROI de volumen resume la integración 3D. Estas opciones no cambian la simulación ni las tablas, sólo la rotulación gráfica.<br><br>
            <strong>Gráficos espectrales.</strong> Permiten revisar la emisión inicial, la atenuación óptica del medio y el cambio relativo de color. Solo tienen sentido cuando la lámpara y el método óptico contienen información espectral suficiente.<br><br>
            Los rangos AUC azul, verde y rojo agrupan energía espectral para facilitar comparaciones, pero sus límites deben adaptarse al objetivo biológico o técnico.
        `
    },
    biooptical_caligus: {
        title: 'Análisis bio-óptico relativo',
        body: `
            Esta sección genera insumos capa-a-capa e índices relativos para evaluar solapamiento vertical entre peces y copepoditos.<br><br>
            El motor óptico entrega irradiancia radiométrica simulada en <code>W/m²</code>. El post-procesamiento calcula <code>IC</code>, <code>IE_pez</code>, <code>IE_contacto</code> e <code>IE_contacto_spectral</code> usando perfiles configurables <code>C(z)</code> y <code>F(z)</code>.<br><br>
            Estos resultados no son probabilidad de infección ni abundancia esperada. Sirven para comparación relativa entre escenarios de lámpara, geometría, profundidad, orientación y agua.
        `
    },
    biooptical_batch: {
        title: 'Escenarios completos',
        body: `
            Cada escenario del batch guarda la configuración completa actual del simulador: geometría, óptica, lámparas, potencia, posición, orientación y resolución.<br><br>
            Use esta ruta para comparar alternativas como Omni y Tempest bajo el mismo análisis C(z)/F(z), y defina un escenario base para obtener índices relativos normalizados.<br><br>
            La salida incluye CSV por capas, CSV de índices biológicos y, opcionalmente, CSV de celdas 3D.
        `
    },
    scene3d_render: {
        title: 'Capas y controles de render 3D',
        body: `
            La vista 3D sirve para inspeccionar geometría, posiciones, orientaciones y relaciones espaciales antes de simular.<br><br>
            Agua, paredes, grilla, ejes, haces, etiquetas y planos de ray tracing son capas visuales. Opacidad, escala de lámpara, exposición y presets modifican únicamente la presentación.<br><br>
            <strong>Globos de luz.</strong> Después de simular, muestran por lámpara la isosuperficie donde la irradiancia escalar volumétrica alcanza el límite seleccionado. Los valores 0,1 y 0,016 W/m² quedan disponibles como referencias directas; también puede ingresar otro umbral. El volumen en m³ se integra sobre la misma malla 3D que genera la superficie.<br><br>
            La resolución volumétrica controla el tamaño de celda del tally: una celda menor suaviza el límite y mejora el volumen estimado, a costa de tiempo, memoria y ruido Monte Carlo.<br><br>
            La opción de atenuación del medio modifica cómo se representa visualmente el haz en 3D, pero no reemplaza ni altera el modelo óptico usado por el motor numérico.<br><br>
            Los controles mover, rotar y soltar sí modifican la posición u orientación configurada de la lámpara y, por lo tanto, afectan la siguiente simulación.
        `
    },
    scene3d_models: {
        title: 'Geometría visual por modelo',
        body: `
            Estas dimensiones describen la carcasa visual de cada modelo de lámpara en la escena 3D: forma, largo, ancho o diámetro y alto.<br><br>
            Su propósito es revisar interferencias, escala y orientación de equipos. No modifican la fotometría, la potencia, el origen del haz ni las colisiones físicas del ray tracing.<br><br>
            Para cambiar el comportamiento lumínico use el archivo fotométrico, la potencia, la eficiencia, la posición y la rotación de la lámpara.
        `
    },
    measurement_import: {
        title: 'Importación de mediciones',
        body: `
            El archivo de medición permite superponer datos reales y preparar una comparación con la simulación.<br><br>
            El importador busca columnas para <code>X</code>, <code>Y</code>, <code>Z</code> o profundidad, y una columna de valor de irradiancia. Todas las coordenadas deben usar el mismo origen, convención vertical y unidades que el modelo.<br><br>
            Para estimar Kd en un punto deben existir al menos dos mediciones positivas con el mismo <code>X/Y</code> y distintas cotas <code>Z</code>.<br><br>
            Antes de comparar, verifique unidades, calibración del sensor, orientación del receptor, condiciones operacionales de las lámparas y estabilidad del agua.
        `
    },
    measurement_comparison: {
        title: 'Estimación de Kd y comparación',
        body: `
            <strong>Calcular Kd.</strong> Para pares de mediciones positivas en el mismo punto horizontal, el simulador estima <code>Kd = [ln(E₁) - ln(E₂)] / |z₂ - z₁|</code>. El resultado representa la atenuación difusa aparente entre esas cotas y puede variar con profundidad, iluminación y condiciones del agua.<br><br>
            <strong>Comparar medición y simulación.</strong> Ejecuta el modelo y contrasta la irradiancia simulada con las mediciones del punto seleccionado. Esta comparación ayuda a detectar sesgos en potencia, geometría, fotometría o parámetros ópticos.<br><br>
            Una coincidencia local no valida automáticamente todo el volumen. Para calibración rigurosa use varios puntos, profundidades, fechas y condiciones operacionales, y documente la incertidumbre de medición.
        `
    },
    query_group: {
        title: 'Consulta bio-óptica',
        body: `
            <p class="note">Este asistente pertenece a la modalidad <strong>Teledetección</strong> del selector
            <em>Origen de parámetros</em>. Nada de lo que haga aquí cambia el modelo hasta que pulse
            <strong>Aplicar al modelo</strong>; en ese momento se escriben TSS, CDOM y Chl-a y cada uno queda
            marcado con su procedencia. Ver
            <button type="button" class="btn btn--sm" onclick="showContextHelp(event, 'param_source')">Origen de los parámetros</button>.</p>
            <strong>Centro, latitud y longitud.</strong> Definen el punto central de extracción en coordenadas WGS84. Si un centro no tiene coordenadas oficiales registradas, deben ingresarse manualmente.<br><br>
            <strong>Fuente.</strong> La opción automática prioriza Sentinel-2/ACOLITE para centros de fiordo/costa cuando esté configurado, porque permite turbidez de mayor resolución espacial a partir de reflectancia de agua corregida atmosféricamente. Si no hay productos ACOLITE válidos, usa Copernicus Marine, NASA OceanColor o NOAA CoastWatch como respaldo. Los productos satelitales representan principalmente la capa superficial.<br><br>
            <strong>Periodo.</strong> El modo de historial usa años completos cerrados y por eso termina en el año anterior al actual. El modo de semana ISO puntual permite consultar una semana específica de un año específico, por ejemplo una semana de 2026 aunque el año todavía esté en curso.<br><br>
            <strong>Historial y semana.</strong> En modo histórico, el análisis agrupa la misma semana ISO a través de varios años completos. Primero resume cada año y luego combina esos resúmenes con igual ponderación, evitando que un año con más días satelitales domine el resultado. Una semana se marca como útil cuando reúne al menos cuatro días válidos y cubre el mínimo de años posible para el historial elegido: un año si se consulta 1 año, dos años si se consultan 2 o más.<br><br>
            <strong>Buffer.</strong> Es el radio alrededor del punto dentro del cual se reúnen píxeles válidos. Un radio pequeño representa mejor el centro, pero puede quedar sin datos; uno grande aumenta cobertura y también el riesgo de mezclar costa, canales o masas de agua diferentes. Para productos de 4 km suele ser razonable usar entre 6.000 y 10.000 m.<br><br>
            <strong>Calibración FNU → TSS.</strong> Cuando la fuente entrega turbidez satelital en FNU, el simulador puede convertirla a TSS mediante <code>TSS = pendiente·FNU + intercepto</code>. La equivalencia por defecto es operacional y debe reemplazarse por una calibración local cuando exista. Si ACOLITE entrega solo <code>rhow_665</code>, el conector puede aplicar Nechad si los coeficientes <code>SENTINEL2_NECHAD_AT</code> y <code>SENTINEL2_NECHAD_C</code> están configurados.<br><br>
            <strong>Escenario.</strong> Claro, típico y turbio corresponden a los percentiles 25, 50 y 75 de las observaciones disponibles.
        `
    },
    confidence_group: {
        title: 'Resultado, incertidumbre y confianza',
        body: `
            El resultado resume las observaciones disponibles en un conjunto de parámetros listo para el simulador. La confianza considera la cantidad de días y píxeles válidos, la dispersión temporal de los datos y, cuando la fuente la publica, su incertidumbre por píxel.<br><br>
            Si el resumen indica <strong>TSS proxy</strong>, el valor no proviene de una medición directa de sólidos suspendidos, sino de turbidez FNU u otro producto satelital convertido mediante la calibración indicada. Para Sentinel-2/ACOLITE/Nechad en Reloncaví se usa como referencia documental una incertidumbre de orden <code>RMSE ≈ 0,66 FNU</code> para Nv09, por lo que el resultado es útil para escenarios y estacionalidad, pero no reemplaza validación en terreno.<br><br>
            Cuando falta el cuantil directo de una variable, el preset no la deja en su valor por defecto: la
            reescala para reproducir el <code>Kd(490)</code> observado, con un factor acotado a
            <code>[0,35 · 3,0]</code>. Esa transformación está en la sección 3 de
            <button type="button" class="btn btn--sm" onclick="showContextHelp(event, 'equations')">ƒ Método y ecuaciones</button>
            y conviene revisarla antes de reportar un TSS o un CDOM derivados por esta vía.<br><br>
            Una confianza baja no significa que la simulación esté rota: indica que el preset depende de pocos datos, de una cobertura espacial limitada o de proxies con mayor incertidumbre. En ese caso conviene ampliar el período o el buffer, contrastar otra fuente y, para decisiones críticas, validar con mediciones en terreno.
        `
    },
    seasonal_dynamics: {
        title: 'Dinámica estacional y Secchi equivalente',
        body: `
            <p class="note note--optics">Las ecuaciones de agregación semanal, cuantiles y modelos de Secchi están
            en <button type="button" class="btn btn--sm" onclick="showContextHelp(event, 'equations')">ƒ Método y ecuaciones</button>,
            secciones 2 y 7.</p>
            <strong>Agregación semanal.</strong> El gráfico agrupa observaciones por semana ISO. Para evitar sesgo por años con más escenas satelitales, primero se resume cada año con su mediana semanal y luego se combinan esos años con igual ponderación. Una semana se considera útil cuando tiene al menos cuatro días válidos y cubre el mínimo de años posible para el historial elegido: un año para historial de 1 año, dos años para historiales de 2 o más años; con menos cobertura queda marcada como limitada.<br><br>
            <strong>Índice relativo.</strong> Las curvas de TSS, turbidez FNU, CDOM y Chl-a se muestran como <code>índice = valor semanal / máximo estacional de esa variable</code>. Esta normalización solo sirve para comparar fase estacional y co-variación entre variables; no cambia los valores usados por el simulador ni permite comparar magnitudes absolutas entre variables distintas.<br><br>
            <strong>Disco Secchi equivalente.</strong> El valor graficado no es una medición de campo, sino una estimación óptica equivalente. Se calcula a 490 nm, longitud de onda habitual para productos oceancolor como <code>Kd(490)</code>. El selector <strong>Modelo Secchi</strong> permite alternar Lee 2015, Preisendorfer, Poole-Atkins, Effler-Kirk y el cierre IOP del Monte Carlo.<br><br>
            <strong>Lee 2015.</strong> Ruta recomendada por ser la teoría mecanística más reciente disponible en el simulador: usa <code>Z<sub>SD</sub>=ln(|r<sub>T</sub>-r<sub>w</sub>|/C<sub>t</sub>)/(2,5 Kd)</code>. En el gráfico semanal usa <code>Kd490</code> observado/proxy cuando existe; si no existe, usa el cierre IOP como aproximación de la ventana transparente.<br><br>
            <strong>Referencia histórica de comparación.</strong> Preisendorfer usa <code>Z<sub>SD</sub>=8,69/(c+Kd)</code> y Poole-Atkins usa <code>Z<sub>SD</sub>=1,7/Kd</code>. Ambos son útiles para sensibilidad y trazabilidad con literatura previa.<br><br>
            <strong>Effler-Kirk.</strong> Usa la forma de contraste <code>Z<sub>SD</sub> = N/(c + Kd)</code>, con <code>N = 8,69</code> como valor central y rango de incertidumbre <code>N = 8,0–9,6</code>. La atenuación difusa se estima como:<br>
            <code>Kd<sub>490,Kirk</sub> = sqrt(a<sub>490</sub>² + 0,256·a<sub>490</sub>·b<sub>490</sub>)</code><br>
            Si hay turbidez FNU/NTU, la dispersión se estima con la relación documentada por Effler y literatura asociada:<br>
            <code>T<sub>n</sub> = α·b</code>, por lo tanto <code>b<sub>490</sub> = T<sub>n</sub>/α</code><br>
            con valor central <code>α = 1,0 NTU·m</code> y rango <code>α = 0,8–1,27 NTU·m</code>. El gráfico muestra ese rango como barras de incertidumbre verticales. Si no hay turbidez, usa <code>b<sub>490</sub> = b*<sub>TSS,490</sub>·[TSS]</code> como respaldo.<br><br>
            <strong>Monte Carlo IOP.</strong> Mantiene la formulación usada inicialmente para coherencia con el motor de propagación, donde la dispersión efectiva depende de la anisotropía:<br>
            <code>Kd<sub>490,MC</sub> = [a<sub>490</sub> + (1 − g)·b<sub>490</sub>] / μ̄<sub>d</sub></code><br><br>
            <strong>Absorción y atenuación de haz comunes a ambos modos.</strong><br>
            <code>a<sub>490</sub> = a<sub>w,490</sub> + a<sub>440</sub>·exp[-S·(490 − 440)] + a*<sub>phy,490</sub>·[Chl-a]</code><br>
            <code>c<sub>490</sub> = a<sub>490</sub> + b<sub>490</sub></code><br>
            <code>Z<sub>SD</sub> ≈ N / (c<sub>490</sub> + Kd<sub>490</sub>)</code><br><br>
            <strong>Constantes implementadas.</strong> Actualmente usa <code>a<sub>w,490</sub> = 0,026 m⁻¹</code>, <code>a*<sub>phy,490</sub> = 0,012 m²·mg⁻¹</code>, <code>b*<sub>TSS,490</sub> = 0,35 m²·g⁻¹</code>, <code>S = 0,015 nm⁻¹</code>, <code>g = 0,85</code> y <code>μ̄<sub>d</sub> = 0,85</code>. Estas constantes son una parametrización transferible para análisis exploratorio; deben calibrarse localmente si se requiere validación contractual o predicción absoluta.<br><br>
            <strong>Respaldo empírico.</strong> Effler (1988) revisa que Secchi depende simultáneamente de absorción y dispersión, mientras la turbidez nefelométrica es principalmente sensible a dispersión. Por eso el modo Effler-Kirk usa <code>T<sub>n</sub> = αb</code>, <code>c = a+b</code> y <code>Kd = sqrt(a²+0,256ab)</code>, dentro de <code>Z<sub>SD</sub>=N/(c+Kd)</code>. La descomposición de absorción/dispersión se apoya además en modelos bio-ópticos clásicos: agua pura de Smith y Baker / Pope y Fry, CDOM exponencial de Bricaud, Morel y Prieur, absorción fitoplanctónica específica de Bricaud et al., y la lectura de <code>Kd(λ)</code> como propiedad óptica aparente dependiente de IOPs y geometría según Lee et al. (2013). Algoritmos tipo Nechad requieren reflectancia atmosféricamente corregida, por ejemplo ACOLITE/DSF para Sentinel-2.<br><br>
            <strong>Lectura recomendada.</strong> Use Secchi equivalente para interpretar transparencia relativa y estacionalidad, no como sustituto directo de una lectura con disco Secchi en terreno. Si el gráfico depende de caché/proxy o pocas escenas, el valor debe reportarse junto con fuente, período, buffer, criterio de agregación e incertidumbre.
        `
    },
    bio_optical_model: {
        title: 'Parametrización bio-óptica espectral',
        body: `
            <p class="note note--optics">La cadena completa de transformaciones —desde el producto satelital hasta
            <code>a(λ)</code>, <code>b(λ)</code> y <code>c(λ)</code>— está desarrollada ecuación por ecuación, con
            unidades y con los valores activos sustituidos, en
            <button type="button" class="btn btn--sm" onclick="showContextHelp(event, 'equations')">ƒ Método y ecuaciones</button>.</p>
            <strong>Formulación utilizada.</strong><br>
            <code>a(λ) = a<sub>w</sub>(λ) + a<sub>CDOM</sub>(λ) + a*<sub>phy</sub>(λ)·[Chl-a]</code><br>
            <code>a<sub>CDOM</sub>(λ) = a<sub>440</sub>·exp[-S·(λ − 440)]</code>, con <code>S = 0,015 nm⁻¹</code><br>
            <code>b(λ) = b*<sub>TSS</sub>(λ)·[TSS]</code><br>
            <code>c(λ) = a(λ) + b(λ)</code> y <code>ω(λ) = b(λ) / c(λ)</code><br><br>
            <strong>Interacción de variables.</strong> TSS o SPM controla principalmente la dispersión; CDOM incrementa especialmente la absorción azul; Chl-a aporta la absorción espectral asociada al fitoplancton. La fase de asimetría <code>g</code> define la dirección de dispersión mediante Henyey-Greenstein. El albedo de pared solo controla la reflexión difusa en el límite del estanque y no es una propiedad del agua.<br><br>
            <strong>Lectura satelital.</strong> Turbidez FNU, SPM, Kd(490), Chl-a y CDOM no son equivalentes entre sí. Sentinel-2/ACOLITE/Nechad estima turbidez desde reflectancia roja corregida atmosféricamente y debe calibrarse antes de transformarla en TSS o dispersión. Lee et al. (2013) muestra que <code>Kd(λ)</code> es una propiedad óptica aparente dependiente de absorción, retrodispersión y geometría angular; por eso <code>Kd(490)</code> ayuda a ajustar magnitud, pero no basta por sí solo para reconstruir color y dispersión espectral.<br><br>
            <strong>Relación con el gráfico estacional.</strong> El disco Secchi equivalente del gráfico se calcula desde esta misma familia de IOPs, pero evaluada de forma resumida en 490 nm para obtener <code>c<sub>490</sub></code>, <code>Kd<sub>490</sub></code> y <code>Z<sub>SD</sub></code>. El selector del gráfico permite usar la ruta <strong>Effler-Kirk</strong>, más compatible con Secchi/turbidez, o la ruta <strong>Monte Carlo IOP</strong>, más coherente con la propagación del motor. Es una métrica interpretativa de transparencia, no una variable que el motor Monte Carlo use directamente para propagar rayos.<br><br>
            <strong>Elección de S = 0,015 nm⁻¹.</strong> La absorción de CDOM se representa habitualmente mediante una función exponencial decreciente desde una longitud de onda de referencia, siguiendo a <a href="https://doi.org/10.4319/lo.1981.26.1.0043" target="_blank" rel="noopener">Bricaud, Morel y Prieur (1981)</a>. El valor <code>0,015 nm⁻¹</code> es una pendiente histórica típica para el visible y es coherente con valores publicados cercanos a 0,014–0,015 nm⁻¹; <a href="https://doi.org/10.1016/j.marchem.2004.02.008" target="_blank" rel="noopener">Twardowski et al. (2004)</a> advierten que la pendiente varía con el tipo de agua, el rango espectral y el método de ajuste. Por ello, debe reemplazarse cuando exista una medición local.<br><br>
            <strong>Referencias orientativas.</strong> CDOM a₄₄₀: 0,3 m⁻¹ representa agua relativamente clara; 1,0 m⁻¹ una referencia media; 3,0 m⁻¹ una condición turbia. Chl-a: 0 mg/m³ representa una condición sin aporte fitoplanctónico; 1–3 mg/m³ una condición intermedia; valores mayores a 10 mg/m³ una condición elevada o eutrófica. Son guías para interpretar magnitud, no límites universales ni una clasificación RAS.<br><br>
            <strong>Respaldo óptico.</strong> Esta parametrización combina absorción de agua pura basada en Smith y Baker (1981) y Pope y Fry (1997), absorción específica de fitoplancton basada en Bricaud et al. (1995/1998), una representación exponencial para CDOM y coeficientes empíricos genéricos de dispersión por TSS. Es un método distinto de la calibración empírica RAS asociada a Bårdsnes (2020).<br><br>
            <strong>Prioridad de calibración local.</strong> Para dimensionar lámparas con mayor capacidad predictiva, el orden de impacto suele ser: <code>FNU/SPM → TSS</code>, <code>TSS → b(λ)</code>, <code>CDOM → a<sub>CDOM</sub>(λ)</code>, y finalmente <code>b<sub>b</sub>/b</code> o función de fase. Una lectura Secchi o Kd(490) ayuda a restringir transparencia, pero no separa absorción y dispersión por sí sola.<br><br>
            <strong>Alcance.</strong> Los coeficientes de TSS y el valor de <code>g</code> son aproximaciones transferibles, pero deberían calibrarse con mediciones ópticas del RAS o del sitio cuando se requiera precisión de diseño o validación contractual.
        `
    },
    param_source: {
        title: 'Origen de los parámetros bio-ópticos',
        body: `
            <p>El motor Monte Carlo necesita tres números: <code>TSS</code>, <code>CDOM a₄₄₀</code> y <code>Chl-a</code>.
            De ahí se construyen <code>a(λ)</code>, <code>b(λ)</code> y <code>c(λ)</code>. El selector define de dónde
            salen esos tres números; el modelo físico posterior es idéntico en las tres modalidades.</p>

            <h5>Manual — ingreso directo</h5>
            <p>Usted escribe los valores. No se ejecuta ninguna consulta de red. Es la modalidad por defecto y la
            adecuada cuando ya dispone de análisis de laboratorio, de una calibración previa del centro o cuando
            quiere explorar sensibilidad variando un parámetro a la vez.</p>

            <h5>Teledetección — recuperación satelital</h5>
            <p>El asistente consulta productos satelitales, agrega por semana ISO y escribe los tres parámetros.
            Entre el píxel satelital y el valor que entra al motor hay una cadena de transformaciones que no es
            neutral: conversión proxy, agregación por cuantiles y, cuando falta el dato directo, un ajuste inverso
            que reescala TSS y CDOM para reproducir el <code>Kd(490)</code> observado. Esa cadena está desarrollada
            paso a paso en <strong>Método y ecuaciones</strong>.</p>
            <p>Los productos representan principalmente la capa superficial y una escala espacial de píxel
            (4 km en productos globales, decenas de metros en Sentinel-2). No describen la columna de agua bajo la
            jaula ni la variabilidad intradiaria.</p>

            <h5>Medición local — archivo CSV</h5>
            <p>Carga sus propias observaciones de terreno o laboratorio. Se aplican las mismas conversiones proxy y
            los mismos cuantiles que en la ruta satelital, de modo que los escenarios claro/típico/turbio conservan
            el mismo significado. Es la ruta con mayor capacidad predictiva cuando existe una campaña de medición.</p>

            <h5>Procedencia</h5>
            <p>Cada parámetro conserva una etiqueta con su origen: <span class="badge badge--manual">manual</span>,
            <span class="badge badge--sat">satélite</span>, <span class="badge badge--proxy">proxy FNU→TSS</span> o
            <span class="badge badge--csv">CSV local</span>. Editar un campo a mano degrada su etiqueta a
            <em>manual</em>. La procedencia se muestra en el panel de corrida y se guarda dentro del archivo de
            configuración, para poder reconstruir meses después de dónde salió cada número.</p>
            <p>Una etiqueta <strong>proxy</strong> significa que el valor no proviene de una medición directa de la
            variable, sino de otra magnitud convertida mediante la calibración indicada. Es información que debe
            acompañar a cualquier reporte.</p>
        `
    },
    equations: {
        title: 'Método y ecuaciones',
        body: `
            <p>Cadena completa desde el producto observado hasta las propiedades ópticas que propaga el motor.
            Los valores marcados en <strong>azul</strong> son los que están activos ahora mismo en la interfaz.</p>

            <h5>1. Ingesta y conversiones proxy</h5>
            <p>Se aplican al leer las observaciones, antes de cualquier agregación
            (<code>optical_lookup.load_observations</code>). Solo actúan cuando falta la variable directa.</p>

            <p>Turbidez satelital en FNU a sólidos suspendidos, con la pendiente y el intercepto configurables en
            el asistente:</p>
            <div class="eq" data-tex="\\mathrm{TSS} \\;=\\; m \\cdot \\mathrm{FNU} \\;+\\; b"><span class="eq__num">(1)</span></div>
            <p class="eq-live">Calibración activa: <strong>m = <span data-live="fnu_slope">—</span></strong>,
            <strong>b = <span data-live="fnu_intercept">—</span></strong>. La equivalencia por defecto
            (<code>m = 1</code>, <code>b = 0</code>) es operacional, no una calibración local.</p>

            <p>Turbidez nefelométrica en agua de RAS (Bårdsnes 2020, regresión de tanque, R²=0,86):</p>
            <div class="eq" data-tex="\\mathrm{TSS} \\;=\\; 3{,}0411 \\cdot \\mathrm{NTU} \\;-\\; 0{,}376"><span class="eq__num">(2)</span></div>

            <p>CDOM medido a 443 nm llevado a la referencia de 440 nm por la pendiente exponencial:</p>
            <div class="eq" data-tex="a_{440} \\;=\\; a_{443}\\,\\exp\\!\\big[S\\,(443-440)\\big], \\qquad S = 0{,}015\\ \\mathrm{nm^{-1}}"><span class="eq__num">(3)</span></div>

            <p>Profundidad de disco Secchi de terreno a atenuación difusa (Poole–Atkins invertida):</p>
            <div class="eq" data-tex="K_{d,490} \\;=\\; \\frac{1{,}7}{Z_{SD}}"><span class="eq__num">(4)</span></div>

            <h5>2. Agregación temporal</h5>
            <p>Para evitar que un año con más escenas satelitales domine el resultado, la agregación es en dos
            niveles: primero la mediana dentro de cada año, después el promedio entre años con peso igual.</p>
            <div class="eq" data-tex="\\tilde{x}_{w,y} \\;=\\; \\operatorname{mediana}\\big(\\{x_i : i \\in \\text{semana } w \\text{ del año } y\\}\\big)"><span class="eq__num">(5)</span></div>
            <div class="eq" data-tex="\\bar{x}_{w} \\;=\\; \\frac{1}{N_y}\\sum_{y=1}^{N_y} \\tilde{x}_{w,y}"><span class="eq__num">(6)</span></div>
            <p>Una semana se marca como útil cuando reúne al menos cuatro días válidos y cubre el mínimo de años
            representables por el historial elegido: un año para historial de 1 año, dos años para 2 o más.</p>

            <p>Los tres escenarios son cuantiles de la distribución de observaciones, no perturbaciones arbitrarias:</p>
            <div class="eq" data-tex="\\text{claro} = Q_{0{,}25}, \\qquad \\text{típico} = Q_{0{,}50}, \\qquad \\text{turbio} = Q_{0{,}75}"><span class="eq__num">(7)</span></div>

            <h5>3. Ajuste inverso al <em>K</em><sub>d</sub>(490) observado</h5>
            <p>Este paso reescala los valores por defecto de la clase de agua para que reproduzcan el
            <code>Kd(490)</code> observado por satélite. <strong>Solo se aplica a los parámetros que faltan</strong>:
            si el cuantil directo de TSS, CDOM o Chl-a existe, ese valor observado se usa tal cual y el ajuste no
            interviene. Implementado en <code>optical_lookup._fit_defaults_to_kd</code>.</p>

            <p>Primero se estima el <code>Kd(490)</code> que producirían los valores por defecto:</p>
            <div class="eq" data-tex="a_{490} \\;=\\; a_{w,490} \\;+\\; a_{440}\\,e^{-S\\,(490-440)} \\;+\\; a^{*}_{phy,490}\\,[\\mathrm{Chl}]"><span class="eq__num">(8)</span></div>
            <div class="eq" data-tex="b_{490} \\;=\\; b^{*}_{TSS,490}\\,[\\mathrm{TSS}]"><span class="eq__num">(9)</span></div>
            <div class="eq" data-tex="K_{d,490}^{\\;est} \\;=\\; \\frac{a_{490} + (1-g)\\,b_{490}}{\\bar{\\mu}_d}"><span class="eq__num">(10)</span></div>
            <p class="eq-live">Con los valores activos: <strong>a₄₉₀ = <span data-live="a490">—</span> m⁻¹</strong>,
            <strong>b₄₉₀ = <span data-live="b490">—</span> m⁻¹</strong>,
            <strong>Kd₄₉₀ = <span data-live="kd490">—</span> m⁻¹</strong>.
            Estas ecuaciones usan constantes fijas a 490 nm (<code>a_w=0,026</code>, <code>b*=0,35</code>,
            <code>a*_phy=0,012</code>), no la tabla interpolada de la sección 5: son dos caminos de cálculo
            distintos y a 490 nm no coinciden exactamente.</p>

            <p>Después se calcula la razón entre lo observado y lo estimado, acotada para evitar extrapolaciones
            sin sentido físico:</p>
            <div class="eq" data-tex="r \\;=\\; \\operatorname{clamp}\\!\\left(\\frac{K_{d,490}^{\\;obs}}{K_{d,490}^{\\;est}},\\; 0{,}35,\\; 3{,}0\\right)"><span class="eq__num">(11)</span></div>
            <div class="eq" data-tex="[\\mathrm{TSS}] \\leftarrow r\\,[\\mathrm{TSS}], \\qquad a_{440} \\leftarrow r\\,a_{440}"><span class="eq__num">(12)</span></div>
            <p class="note note--warn">El recorte a <code>[0,35 · 3,0]</code> significa que un <code>Kd</code> observado
            muy alejado del estimado <strong>no</strong> se reproduce exactamente: el preset queda en el borde del
            intervalo. Si el ajuste satura con frecuencia, la clase de agua base no representa el sitio y conviene
            medir localmente. Chl-a no se reescala en este paso.</p>

            <h5>4. Propiedades ópticas inherentes</h5>
            <p>Los tres parámetros del panel se convierten en absorción y dispersión espectrales
            (<code>simulation_engine.bio_optical_iop</code>). Esto es lo que el motor propaga.</p>
            <div class="eq eq--bio" data-tex="a(\\lambda) \\;=\\; a_w(\\lambda) \\;+\\; \\underbrace{a_{440}\\,e^{-S\\,(\\lambda-440)}}_{\\text{CDOM}} \\;+\\; \\underbrace{a^{*}_{phy}(\\lambda)\\,[\\mathrm{Chl}]}_{\\text{fitoplancton}}"><span class="eq__num">(13)</span></div>
            <div class="eq eq--bio" data-tex="b(\\lambda) \\;=\\; b^{*}_{TSS}(\\lambda)\\,[\\mathrm{TSS}]"><span class="eq__num">(14)</span></div>
            <div class="eq eq--bio" data-tex="c(\\lambda) \\;=\\; a(\\lambda) + b(\\lambda), \\qquad \\omega(\\lambda) \\;=\\; \\frac{b(\\lambda)}{c(\\lambda)}"><span class="eq__num">(15)</span></div>
            <p class="eq-live">Valores activos del panel: <strong>TSS = <span data-live="tss">—</span> mg/L</strong>,
            <strong>CDOM a₄₄₀ = <span data-live="cdom">—</span> m⁻¹</strong>,
            <strong>Chl-a = <span data-live="chl">—</span> mg/m³</strong> ⟶
            <strong>c₄₉₀ = <span data-live="c490">—</span> m⁻¹</strong>.</p>

            <h5>5. Constantes tabuladas e interpolación</h5>
            <p>Las funciones espectrales <code>a_w(λ)</code>, <code>b*_TSS(λ)</code> y <code>a*_phy(λ)</code> no son
            curvas analíticas: son <strong>siete nodos tabulados</strong> que el motor
            <strong>interpola linealmente</strong> con <code>numpy.interp</code>. Fuera del rango 400–700 nm el valor
            se mantiene constante en el extremo. Definidas en <code>simulation_engine.py</code>.</p>
            <div class="table-scroll">
            <table class="symtable">
                <tr><th>λ (nm)</th><th>400</th><th>450</th><th>500</th><th>550</th><th>600</th><th>650</th><th>700</th></tr>
                <tr><td>a<sub>w</sub></td><td>0,018</td><td>0,015</td><td>0,026</td><td>0,064</td><td>0,245</td><td>0,349</td><td>0,624</td></tr>
                <tr><td>b*<sub>TSS</sub></td><td>0,50</td><td>0,42</td><td>0,35</td><td>0,31</td><td>0,28</td><td>0,25</td><td>0,22</td></tr>
                <tr><td>a*<sub>phy</sub></td><td>0,022</td><td>0,038</td><td>0,012</td><td>0,005</td><td>0,005</td><td>0,018</td><td>0,008</td></tr>
            </table>
            </div>
            <p><code>a_w</code> en m⁻¹ (Pope y Fry 1997 + Smith y Baker 1981, redondeados);
            <code>b*_TSS</code> en m²/g; <code>a*_phy</code> en m²/mg (promedio de Bricaud et al. 1995/1998, con
            picos cerca de 440 y 675 nm). Con solo siete nodos, los detalles espectrales finos entre ellos
            —en particular el pico de clorofila en el rojo— quedan suavizados por la interpolación.</p>

            <h5>6. Cierre IOP → K<sub>d</sub></h5>
            <p>Kirk/Gershun, régimen difuso, usa la asimetría <code>g</code>:</p>
            <div class="eq" data-tex="K_d \\;=\\; \\frac{a + (1-g)\\,b}{\\bar{\\mu}_d}"><span class="eq__num">(16)</span></div>
            <p>Lee, Du y Arnone (2005), semianalítico, usa retrodispersión explícita y geometría de iluminación
            (<code>θ_a</code> = ángulo cenital en aire, 30° por defecto para fuente artificial):</p>
            <div class="eq" data-tex="K_d \\;=\\; (1 + 0{,}005\\,\\theta_a)\\,a \\;+\\; 4{,}18\\,\\big(1 - 0{,}52\\,e^{-10{,}8\\,a}\\big)\\,b_b"><span class="eq__num">(17)</span></div>

            <h5>7. Disco de Secchi equivalente</h5>
            <p>Métrica interpretativa de transparencia. El motor no la usa para propagar rayos.</p>
            <div class="eq" data-tex="\\text{Lee 2015:}\\quad Z_{SD} \\;=\\; \\frac{1}{2{,}5\\,K_{d}^{tr}}\\,\\ln\\!\\frac{|r_T - r_w|}{C_t}"><span class="eq__num">(18)</span></div>
            <div class="eq" data-tex="\\text{Preisendorfer:}\\quad Z_{SD} \\;=\\; \\frac{8{,}69}{c + K_d} \\qquad\\qquad \\text{Poole–Atkins:}\\quad Z_{SD} \\;=\\; \\frac{1{,}7}{K_d}"><span class="eq__num">(19)</span></div>
            <div class="eq" data-tex="\\text{Effler–Kirk:}\\quad K_{d,490} \\;=\\; \\sqrt{a_{490}^{2} + 0{,}256\\,a_{490}\\,b_{490}}, \\qquad Z_{SD} \\;=\\; \\frac{N}{c_{490} + K_{d,490}}"><span class="eq__num">(20)</span></div>
            <p class="eq-live">Con los valores activos y <code>N = 8,69</code>:
            <strong>Z<sub>SD</sub> ≈ <span data-live="zsd">—</span> m</strong>.
            En Effler–Kirk el rango de incertidumbre es <code>N = 8,0–9,6</code> y, si hay turbidez,
            <code>b = T_n/α</code> con <code>α = 1,0 NTU·m</code> (rango 0,8–1,27).</p>

            <h5>8. Variante RAS (Bårdsnes 2020)</h5>
            <p>Estructura distinta: la atenuación particulada se modela como ley de potencia y crece hacia el azul,
            al revés que en agua marina.</p>
            <div class="eq eq--warn" data-tex="c_p(\\lambda) \\;=\\; b^{*}_{550}\\,[\\mathrm{TSS}]\\left(\\frac{\\lambda}{550}\\right)^{-\\eta_p}"><span class="eq__num">(21)</span></div>
            <div class="eq eq--warn" data-tex="b(\\lambda) = \\omega_p\\,c_p(\\lambda), \\qquad a_p(\\lambda) = (1-\\omega_p)\\,c_p(\\lambda)"><span class="eq__num">(22)</span></div>
            <div class="eq eq--warn" data-tex="a(\\lambda) \\;=\\; a_w(\\lambda) + a_{440}e^{-S_{CDOM}(\\lambda-440)} + a^{*}_{phy}(\\lambda)[\\mathrm{Chl}] + a_p(\\lambda)"><span class="eq__num">(23)</span></div>
            <p>Del trabajo de Bårdsnes se toman las <strong>formas</strong> espectrales —<code>η_p ≈ 1,8</code> y
            <code>S_CDOM ≈ 0,0141 nm⁻¹</code>, ajustadas a la Tabla 4.1— pero <strong>no la magnitud absoluta</strong>:
            la medición del paper tiene re-entrada de luz por las paredes del tanque. Por eso <code>b*₅₅₀</code> y
            <code>ω_p</code> quedan como parámetros calibrables por instalación, y deben ajustarse con una medida
            óptica propia del sistema —<code>c(λ)</code>, <code>Kd(λ)</code> o transmitancia espectral— antes de
            usar la ruta RAS para dimensionar.</p>

            <h5>Símbolos y unidades</h5>
            <div class="table-scroll">
            <table class="symtable">
                <tr><th>Símbolo</th><th>Unidad</th><th>Significado</th></tr>
                <tr><td>a(λ)</td><td>m⁻¹</td><td>Coeficiente de absorción espectral</td></tr>
                <tr><td>b(λ)</td><td>m⁻¹</td><td>Coeficiente de dispersión espectral</td></tr>
                <tr><td>b_b</td><td>m⁻¹</td><td>Retrodispersión</td></tr>
                <tr><td>c(λ)</td><td>m⁻¹</td><td>Atenuación de haz, <code>a + b</code></td></tr>
                <tr><td>ω(λ)</td><td>—</td><td>Albedo de dispersión simple, <code>b/c</code></td></tr>
                <tr><td>K_d</td><td>m⁻¹</td><td>Atenuación difusa descendente (propiedad aparente)</td></tr>
                <tr><td>TSS</td><td>mg/L ≡ g/m³</td><td>Sólidos suspendidos totales</td></tr>
                <tr><td>a₄₄₀</td><td>m⁻¹</td><td>Absorción de CDOM a 440 nm</td></tr>
                <tr><td>Chl-a</td><td>mg/m³</td><td>Clorofila-a</td></tr>
                <tr><td>S</td><td>nm⁻¹</td><td>Pendiente espectral del CDOM (0,015 marino; 0,0141 RAS)</td></tr>
                <tr><td>g</td><td>—</td><td>Factor de asimetría de la función de fase</td></tr>
                <tr><td>μ̄_d</td><td>—</td><td>Coseno medio del campo descendente (0,85)</td></tr>
                <tr><td>η_p</td><td>—</td><td>Pendiente espectral particulada (ley de potencia)</td></tr>
                <tr><td>ω_p</td><td>—</td><td>Albedo de dispersión simple particulado</td></tr>
                <tr><td>Z_SD</td><td>m</td><td>Profundidad de disco de Secchi equivalente</td></tr>
                <tr><td>Q_p</td><td>—</td><td>Cuantil p de las observaciones disponibles</td></tr>
            </table>
            </div>

            <h5>Qué calibrar primero</h5>
            <p>Por orden de impacto sobre la irradiancia simulada:
            <code>FNU/SPM → TSS</code>, luego <code>TSS → b(λ)</code>, luego <code>CDOM → a_CDOM(λ)</code>, y por
            último <code>b_b/b</code> o la función de fase. Una lectura de Secchi o de <code>Kd(490)</code> restringe
            la transparencia total, pero por sí sola no separa absorción de dispersión: dos combinaciones muy
            distintas de <code>a</code> y <code>b</code> pueden dar el mismo <code>Kd</code> y campos de luz
            diferentes bajo la lámpara.</p>
        `
    }
};

/* =============================================================================
 *  DRAWER DE DOCUMENTACIÓN
 *  Sustituye el popover flotante: índice de temas, buscador y anclas, con
 *  espacio suficiente para ecuaciones y tablas de símbolos.
 * ========================================================================== */

/** Agrupación del índice. El orden define cómo se lee la documentación. */
const HELP_GROUPS = [
    { title: 'Flujo general', keys: ['simulation_workflow'] },
    { title: 'Escena', keys: ['environment_geometry', 'reference_polygon', 'lamp_photometry', 'lamp_placement'] },
    { title: 'Óptica', keys: ['water_interface', 'propagation_modes', 'attenuation_type', 'secchi_model',
                              'monte_carlo_methods', 'phase_function', 'kd_closure'] },
    { title: 'Bio-óptica', keys: ['param_source', 'bio_optical_model', 'equations', 'query_group',
                                  'seasonal_dynamics', 'confidence_group', 'biooptical_caligus', 'biooptical_batch'] },
    { title: 'Cálculo y salidas', keys: ['sampling_and_metric', 'maps_and_thresholds', 'evaluation_roi',
                                         'lamp_contribution_points', 'output_reports'] },
    { title: 'Visualización', keys: ['scene3d_render', 'scene3d_models'] },
    { title: 'Validación', keys: ['measurement_import', 'measurement_comparison'] }
];

function syncBackdrop() {
    const backdrop = document.getElementById('help_backdrop');
    if (!backdrop) return;
    const anyOpen = document.querySelector('.drawer.is-open');
    backdrop.classList.toggle('is-open', Boolean(anyOpen));
}

function closeContextHelp() {
    const drawer = document.getElementById('help_drawer');
    if (drawer) {
        drawer.classList.remove('is-open');
        drawer.setAttribute('aria-hidden', 'true');
    }
    closeSatelliteDrawer();
    syncBackdrop();
}

function buildHelpNav() {
    const nav = document.getElementById('help_nav');
    if (!nav || nav.dataset.built === '1') return;
    let html = '';
    HELP_GROUPS.forEach(group => {
        const items = group.keys.filter(k => contextHelpContent[k]);
        if (!items.length) return;
        html += `<div class="drawer__nav-group"><div class="drawer__nav-title">${group.title}</div>`;
        items.forEach(k => {
            html += `<button type="button" class="drawer__nav-item" data-help-key="${k}"
                        onclick="showContextHelp(event, '${k}')">${contextHelpContent[k].title}</button>`;
        });
        html += '</div>';
    });
    nav.innerHTML = html;
    nav.dataset.built = '1';
}

function showContextHelp(event, key) {
    if (event) { event.preventDefault(); event.stopPropagation(); }
    const content = contextHelpContent[key];
    if (!content) return;

    buildHelpNav();

    let body = content.body;
    if (key === 'confidence_group' && window.currentOpticalPresets) {
        body += `<p><strong>Resultado actual:</strong> ${explainOpticalConfidence(window.currentOpticalPresets)}</p>`;
    }

    const titleEl = document.getElementById('help_drawer_title');
    const bodyEl = document.getElementById('help_body');
    if (titleEl) titleEl.textContent = content.title;
    if (bodyEl) {
        bodyEl.innerHTML = body;
        bodyEl.scrollTop = 0;
        renderKatexIn(bodyEl);
        if (typeof refreshEquationValues === 'function') refreshEquationValues(bodyEl);
    }

    document.querySelectorAll('.drawer__nav-item').forEach(item => {
        item.classList.toggle('is-active', item.dataset.helpKey === key);
    });

    const drawer = document.getElementById('help_drawer');
    if (drawer) {
        drawer.classList.add('is-open');
        drawer.setAttribute('aria-hidden', 'false');
    }
    syncBackdrop();
}

/** Filtra el índice por título y por contenido del tema. */
function filterHelpTopics(query) {
    const q = (query || '').trim().toLowerCase();
    document.querySelectorAll('.drawer__nav-item').forEach(item => {
        const key = item.dataset.helpKey;
        const entry = contextHelpContent[key];
        if (!entry) return;
        const haystack = (entry.title + ' ' + entry.body.replace(/<[^>]+>/g, ' ')).toLowerCase();
        item.classList.toggle('is-hidden', Boolean(q) && !haystack.includes(q));
    });
    document.querySelectorAll('.drawer__nav-group').forEach(group => {
        const visible = group.querySelectorAll('.drawer__nav-item:not(.is-hidden)').length;
        group.classList.toggle('is-hidden', visible === 0);
    });
}

function setOpticalAssistantStatus(text, isError = false) {
    const el = document.getElementById('optical_assistant_status');
    if (!el) return;
    el.innerHTML = text;
    el.classList.toggle('is-error', Boolean(isError));
}

function loadOpticalCenters() {
    const select = document.getElementById('optical_center_select');
    if (!select) return;
    fetch('/api/optical_centers')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'ok') return;
            window.opticalCenters = data.centers || [];
            data.centers.forEach(center => {
                const opt = document.createElement('option');
                opt.value = center.center_id;
                opt.text = center.name;
                opt.dataset.lat = center.lat;
                opt.dataset.lon = center.lon;
                select.add(opt);
            });
        })
        .catch(() => setOpticalAssistantStatus('No se pudo cargar la lista de centros.', true));
}

function getCurrentIsoWeek() {
    return getCurrentIsoPeriod().week;
}

function getCurrentIsoPeriod() {
    const now = new Date();
    const utcDate = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
    const day = utcDate.getUTCDay() || 7;
    utcDate.setUTCDate(utcDate.getUTCDate() + 4 - day);
    const yearStart = new Date(Date.UTC(utcDate.getUTCFullYear(), 0, 1));
    return {
        year: utcDate.getUTCFullYear(),
        week: Math.ceil((((utcDate - yearStart) / 86400000) + 1) / 7)
    };
}

function toggleOpticalPeriodMode() {
    const mode = (document.getElementById('optical_period_mode') || {}).value || 'history';
    const historyBox = document.getElementById('optical_years_back_container');
    const yearBox = document.getElementById('optical_target_year_container');
    const weekBox = document.getElementById('optical_target_week_container');
    if (historyBox) setShown(historyBox, mode === 'history');
    if (yearBox) setShown(yearBox, mode === 'iso_week');
    if (weekBox) setShown(weekBox, mode === 'iso_week');
    if (mode === 'iso_week') {
        const current = getCurrentIsoPeriod();
        const yearInput = document.getElementById('optical_target_year');
        const weekInput = document.getElementById('optical_target_week');
        if (yearInput && !yearInput.value) yearInput.value = current.year;
        if (weekInput && !weekInput.value) weekInput.value = current.week;
    }
}

function formatWeekOption(week) {
    const number = String(week.iso_week).padStart(2, '0');
    if (week.status === 'util') {
        return `Semana ${number} · útil · ${week.years.length} años / ${week.valid_days} días`;
    }
    if (week.status === 'limitada') {
        return `Semana ${number} · datos limitados · ${week.years.length} años / ${week.valid_days} días`;
    }
    return `Semana ${number} · sin datos`;
}

function loadOpticalSourceStatus() {
    fetch('/api/optical_sources/status')
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'ok') return;
            const sources = data.sources || {};
            const available = [];
            const unavailable = [];
            Object.keys(sources).forEach(key => {
                const src = sources[key];
                if (src.available && src.configured) available.push(src.label);
                else unavailable.push(`${src.label}: ${src.available ? 'sin config' : 'no disponible'}`);
            });
            const bits = [];
            if (available.length) bits.push(`<strong>Fuentes disponibles:</strong> ${available.join(', ')}`);
            if (unavailable.length) bits.push(`<span class="text-muted">${unavailable.join(' · ')}</span>`);
            if (bits.length) setOpticalAssistantStatus(bits.join('<br>'));
        })
        .catch(() => {});
}

function syncOpticalCenterFields() {
    const select = document.getElementById('optical_center_select');
    if (!select || !select.value) return;
    const center = window.opticalCenters.find(c => c.center_id === select.value);
    if (!center) return;
    const latInput = document.getElementById('optical_lat');
    const lonInput = document.getElementById('optical_lon');
    if (center.lat !== null && center.lat !== undefined && center.lon !== null && center.lon !== undefined) {
        latInput.value = center.lat;
        lonInput.value = center.lon;
        setOpticalAssistantStatus(`Centro seleccionado: ${center.name}. Coordenadas cargadas.`);
    } else {
        latInput.value = '';
        lonInput.value = '';
        setOpticalAssistantStatus(`El centro ${center.name} no tiene coordenadas oficiales cargadas. Ingrese Latitud y Longitud antes de consultar.`, true);
    }
}

function buildSelectedWeekData(profile, week) {
    return {
        center: profile.center,
        presets: week.presets,
        confidence: week.confidence,
        medians: week.medians || {},
        ranges: week.ranges || {},
        diagnostics: profile.diagnostics || [],
        source_status: profile.source_status || {},
        selected_week: week.iso_week,
        weekly_status: week.status,
        period_mode: profile.period_mode || 'history',
        historical_period: profile.historical_period
    };
}

function populateOpticalWeekSelect(profile) {
    const select = document.getElementById('optical_week_select');
    if (!select) return;
    select.innerHTML = '';
    const weeks = profile.weeks || [];
    weeks.forEach(week => {
        const option = document.createElement('option');
        option.value = String(week.iso_week);
        option.textContent = formatWeekOption(week);
        option.disabled = week.status === 'sin_datos';
        select.appendChild(option);
    });
    select.disabled = !weeks.some(week => week.status !== 'sin_datos');

    const currentWeek = getCurrentIsoWeek();
    const preferred = weeks.find(week => week.iso_week === currentWeek && week.useful)
        || weeks.find(week => week.useful)
        || weeks.find(week => week.status === 'limitada');
    if (preferred) select.value = String(preferred.iso_week);
}

function opticalPlotNumber(value) {
    if (value === null || value === undefined || value === '') return null;
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
}

function opticalPlotQuantile(values, q) {
    const sorted = values
        .filter(value => Number.isFinite(value))
        .sort((a, b) => a - b);
    if (!sorted.length) return null;
    const position = (sorted.length - 1) * q;
    const lower = Math.floor(position);
    const upper = Math.ceil(position);
    if (lower === upper) return sorted[lower];
    return sorted[lower] + (sorted[upper] - sorted[lower]) * (position - lower);
}

function escapePlotText(value) {
    return String(value === null || value === undefined ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');
}

function wrapPlotText(text, maxChars = 80) {
    const words = escapePlotText(text).split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    words.forEach(word => {
        const next = line ? `${line} ${word}` : word;
        if (next.length > maxChars && line) {
            lines.push(line);
            line = word;
        } else {
            line = next;
        }
    });
    if (line) lines.push(line);
    return lines.join('<br>');
}

function opticalHgBackscatterFraction(g) {
    const gg = Number(g);
    if (!Number.isFinite(gg)) return 0.036;
    if (Math.abs(gg) < 1e-6) return 0.5;
    return ((1 - gg) / (2 * gg)) * (((1 + gg) / Math.sqrt(1 + gg * gg)) - 1);
}

function estimateBioOpticalSecchi(tss, cdom, chl, turbidityFnu = null, model = 'lee2015', g = 0.85, muD = 0.85, observedKd490 = null) {
    const tssValue = opticalPlotNumber(tss);
    const cdomValue = opticalPlotNumber(cdom);
    const chlValue = opticalPlotNumber(chl);
    const turbidityValue = opticalPlotNumber(turbidityFnu);
    const observedKdValue = opticalPlotNumber(observedKd490);
    const normalizedModel = (model || 'lee2015').toLowerCase();
    const useEffler = normalizedModel === 'effler_kirk';
    if (cdomValue === null || chlValue === null) return null;
    if (tssValue === null && turbidityValue === null && observedKdValue === null) return null;

    const wl = 490;
    const aw490 = 0.026;
    const bTssStar490 = 0.35;
    const aPhyStar490 = 0.012;
    const cdomSlope = 0.015;
    const aCdom = cdomValue * Math.exp(-cdomSlope * (wl - 440));
    const aPhy = aPhyStar490 * chlValue;
    const alphaRef = 1.0;
    const alphaMin = 0.8;
    const alphaMax = 1.27;
    const bParticulate = useEffler && turbidityValue !== null
        ? turbidityValue / alphaRef
        : (tssValue !== null ? bTssStar490 * tssValue : null);
    const aTotal = aw490 + aCdom + aPhy;
    const c490 = bParticulate !== null ? aTotal + bParticulate : null;
    const kdEffler = bParticulate !== null
        ? Math.sqrt(Math.max(0, aTotal * aTotal + 0.256 * aTotal * bParticulate))
        : null;
    const kdMc = bParticulate !== null
        ? (aTotal + (1 - g) * bParticulate) / muD
        : null;
    const nRef = 8.69;
    let kd490 = observedKdValue !== null ? observedKdValue : kdMc;
    let kdSource = observedKdValue !== null ? 'Kd490 observado/proxy' : 'IOP Monte Carlo';
    let secchi = null;

    if (normalizedModel === 'effler_kirk') {
        kd490 = kdEffler;
        kdSource = 'Effler-Kirk';
        secchi = c490 !== null && kd490 !== null ? nRef / (c490 + kd490) : null;
    } else if (normalizedModel === 'monte_carlo') {
        kd490 = kdMc;
        kdSource = 'IOP Monte Carlo';
        secchi = c490 !== null && kd490 !== null ? nRef / (c490 + kd490) : null;
    } else if (normalizedModel === 'preisendorfer') {
        secchi = c490 !== null && kd490 !== null ? nRef / (c490 + kd490) : null;
    } else if (normalizedModel === 'poole_atkins') {
        secchi = kd490 !== null && kd490 > 0 ? 1.7 / kd490 : null;
    } else {
        const rT = 0.85 / Math.PI;
        const bb490 = bParticulate !== null ? opticalHgBackscatterFraction(g) * bParticulate : null;
        const rW = bb490 !== null ? (0.33 * bb490 / Math.max(aTotal + bb490, 1e-9)) / Math.PI : 0.02;
        const contrast = Math.abs(rT - rW) / 0.013;
        secchi = kd490 !== null && kd490 > 0 && contrast > 1
            ? Math.log(contrast) / (2.5 * kd490)
            : null;
    }

    if (!Number.isFinite(secchi) || secchi <= 0) return null;
    let secchiMin = secchi;
    let secchiMax = secchi;
    if (useEffler && c490 !== null && bParticulate !== null) {
        const nMin = 8.0;
        const nMax = 9.6;
        const bForMin = turbidityValue !== null ? turbidityValue / alphaMin : bParticulate;
        const bForMax = turbidityValue !== null ? turbidityValue / alphaMax : bParticulate;
        const kdForMin = Math.sqrt(Math.max(0, aTotal * aTotal + 0.256 * aTotal * bForMin));
        const kdForMax = Math.sqrt(Math.max(0, aTotal * aTotal + 0.256 * aTotal * bForMax));
        secchiMin = nMin / (aTotal + bForMin + kdForMin);
        secchiMax = nMax / (aTotal + bForMax + kdForMax);
    }
    return {
        secchi,
        secchiMin,
        secchiMax,
        kd490,
        c490,
        a490: aTotal,
        b490: bParticulate,
        model: normalizedModel,
        kdSource,
        bSource: bParticulate === null
            ? 'sin TSS/FNU'
            : (useEffler && turbidityValue !== null ? 'turbidez FNU / α' : 'TSS · b*')
    };
}

function getOpticalSecchiModel() {
    const select = document.getElementById('optical_secchi_model');
    return select ? select.value : 'lee2015';
}

function opticalSecchiModelLabel(model) {
    const m = (model || 'lee2015').toLowerCase();
    if (m === 'monte_carlo') return 'Monte Carlo IOP: Kd=[a+(1-g)b]/mu_d, N=8,69';
    if (m === 'effler_kirk') return 'Effler-Kirk: Kd=sqrt(a^2+0,256ab), N=8,0-9,6';
    if (m === 'preisendorfer') return 'Preisendorfer: Z=8,69/(c+Kd)';
    if (m === 'poole_atkins') return 'Poole-Atkins: Z=1,7/Kd';
    return 'Lee et al. 2015: Z=ln(|rT-rw|/Ct)/(2,5 Kd)';
}

function opticalSecchiTraceName(model) {
    const m = (model || 'lee2015').toLowerCase();
    if (m === 'monte_carlo') return 'Secchi MC IOP';
    if (m === 'effler_kirk') return 'Secchi Effler-Kirk';
    if (m === 'preisendorfer') return 'Secchi Preisendorfer';
    if (m === 'poole_atkins') return 'Secchi Poole-Atkins';
    return 'Secchi Lee 2015';
}

function rerenderOpticalWeeklyPlot() {
    const profile = window.currentOpticalWeeklyProfile;
    if (!profile || !profile.weeks) return;
    const select = document.getElementById('optical_week_select');
    const selectedWeek = select && select.value ? Number(select.value) : null;
    renderOpticalWeeklyPlot(profile, selectedWeek);
    const fullscreenModal = document.getElementById('optical_weekly_plot_modal');
    if (fullscreenModal && fullscreenModal.style.display === 'flex') {
        renderOpticalWeeklyPlot(profile, selectedWeek, {
            plotId: 'optical_weekly_plot_fullscreen',
            fullscreen: true,
            updateButtons: false
        });
    }
}

function summarizeOpticalPlotSource(profile, compact = false, secchiModel = 'lee2015') {
    const center = profile.center || {};
    const diagnostics = profile.diagnostics || [];
    const historical = profile.historical_period || {};
    const sourceNames = diagnostics
        .filter(item => item && item.status && item.status !== 'skipped')
        .map(item => item.source)
        .filter(Boolean);
    const uniqueSources = [...new Set(sourceNames)];
    const sourceText = uniqueSources.length ? uniqueSources.join(', ') : 'sin fuente remota válida; valores por defecto/cache si aplica';
    const periodText = historical.start_date && historical.end_date
        ? `${historical.start_date} a ${historical.end_date}`
        : 'periodo histórico configurado';
    const centerText = center.name || center.center_id || 'coordenadas manuales';
    if (compact) {
        return `Fuente: ${sourceText}. Periodo: ${periodText}. Semana ISO ponderada por año. Secchi: ${opticalSecchiModelLabel(secchiModel)}.`;
    }
    return `Fuente: ${sourceText}. Centro: ${centerText}. Periodo: ${periodText}. Método: semana ISO, mediana anual y ponderación igual por año. Secchi: ${opticalSecchiModelLabel(secchiModel)}.`;
}

function opticalPlotFilename(profile) {
    const center = (profile.center && (profile.center.center_id || profile.center.name)) || 'sitio';
    const safeCenter = String(center).toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'sitio';
    return `dinamica_estacional_bio_optica_${safeCenter}`;
}

function setOpticalPlotDownloadEnabled(enabled) {
    const button = document.getElementById('download_optical_weekly_plot');
    if (button) button.disabled = !enabled;
    const fullscreenButton = document.getElementById('fullscreen_optical_weekly_plot');
    if (fullscreenButton) fullscreenButton.disabled = !enabled;
}

function downloadOpticalWeeklyPlot() {
    const fullscreenModal = document.getElementById('optical_weekly_plot_modal');
    const fullscreenPlot = document.getElementById('optical_weekly_plot_fullscreen');
    const plotDiv = fullscreenModal && fullscreenModal.style.display === 'flex' && fullscreenPlot
        ? fullscreenPlot
        : document.getElementById('optical_weekly_plot');
    if (!plotDiv || typeof Plotly === 'undefined') return;
    const filename = plotDiv._opticalPlotFilename || 'dinamica_estacional_bio_optica';
    Plotly.downloadImage(plotDiv, {
        format: 'png',
        filename,
        width: 1300,
        height: 760,
        scale: 3
    });
}

function ensureOpticalPlotFullscreenModal() {
    let modal = document.getElementById('optical_weekly_plot_modal');
    if (modal) return modal;
    modal = document.createElement('div');
    modal.id = 'optical_weekly_plot_modal';
    modal.className = 'optical-plot-modal';
    modal.innerHTML = `
        <div class="optical-plot-modal-box">
            <div class="optical-plot-modal-header">
                <div class="optical-plot-modal-title">Dinámica estacional bio-óptica</div>
                <div class="optical-plot-modal-actions">
                    <button type="button" class="btn-load optical-plot-button" onclick="downloadOpticalWeeklyPlot()">Descargar gráfico</button>
                    <button type="button" class="btn-load optical-plot-button" onclick="closeOpticalWeeklyPlotFullscreen()">Cerrar</button>
                </div>
            </div>
            <div id="optical_weekly_plot_fullscreen" class="optical-weekly-plot-fullscreen"></div>
        </div>`;
    document.body.appendChild(modal);
    modal.addEventListener('click', event => {
        if (event.target === modal) closeOpticalWeeklyPlotFullscreen();
    });
    document.addEventListener('keydown', event => {
        if (event.key === 'Escape') closeOpticalWeeklyPlotFullscreen();
    });
    return modal;
}

function openOpticalWeeklyPlotFullscreen() {
    const profile = window.currentOpticalWeeklyProfile;
    if (!profile || !profile.weeks) return;
    const select = document.getElementById('optical_week_select');
    const selectedWeek = select && select.value ? Number(select.value) : null;
    const modal = ensureOpticalPlotFullscreenModal();
    modal.style.display = 'flex';
    renderOpticalWeeklyPlot(profile, selectedWeek, {
        plotId: 'optical_weekly_plot_fullscreen',
        fullscreen: true,
        updateButtons: false
    });
    const fullscreenPlot = document.getElementById('optical_weekly_plot_fullscreen');
    if (fullscreenPlot && typeof Plotly !== 'undefined') {
        setTimeout(() => Plotly.Plots.resize(fullscreenPlot), 60);
    }
}

function closeOpticalWeeklyPlotFullscreen() {
    const modal = document.getElementById('optical_weekly_plot_modal');
    if (modal) modal.style.display = 'none';
}

function renderOpticalWeeklyPlot(profile, selectedWeek, options = {}) {
    const plotDiv = document.getElementById(options.plotId || 'optical_weekly_plot');
    const isFullscreen = Boolean(options.fullscreen);
    const secchiModel = options.secchiModel || getOpticalSecchiModel();
    if (!plotDiv || typeof Plotly === 'undefined') {
        if (options.updateButtons !== false) setOpticalPlotDownloadEnabled(false);
        return;
    }
    const weeks = profile.weeks || [];
    const x = weeks.map(week => week.iso_week);
    const variables = [
        { key: 'turbidity_fnu', name: 'Turbidez FNU', color: '#c026d3', dash: 'dot' },
        { key: 'tss', name: 'TSS o proxy', color: '#f97316', dash: 'solid' },
        { key: 'cdom_a440', name: 'CDOM a440', color: '#0ea5e9', dash: 'solid' },
        { key: 'chl', name: 'Chl-a', color: '#22c55e', dash: 'solid' }
    ].filter(variable => weeks.some(week => week.medians && opticalPlotNumber(week.medians[variable.key]) !== null));
    const traces = variables.map(variable => {
        const raw = weeks.map(week => opticalPlotNumber(week.medians && week.medians[variable.key]));
        const valid = raw.filter(value => value !== null);
        const maxValue = valid.length ? Math.max(...valid) : 1;
        const divisor = maxValue > 0 ? maxValue : 1;
        return {
            x,
            y: raw.map(value => value === null ? null : value / divisor),
            customdata: raw,
            name: variable.name,
            type: 'scatter',
            mode: 'lines+markers',
            line: { color: variable.color, width: isFullscreen ? 2.8 : 2.35, dash: variable.dash },
            marker: { color: variable.color, size: isFullscreen ? 6.2 : 5.2, symbol: 'circle', line: { color: '#ffffff', width: 0.65 } },
            connectgaps: false,
            hovertemplate: `Semana %{x}<br>${variable.name}: %{customdata:.3f}<br>Índice relativo: %{y:.2f}<extra></extra>`
        };
    });
    const secchiRows = weeks.map(week => {
        const medians = week.medians || {};
        return estimateBioOpticalSecchi(
            medians.tss,
            medians.cdom_a440,
            medians.chl,
            medians.turbidity_fnu,
            secchiModel,
            0.85,
            0.85,
            medians.kd490
        );
    });
    const secchiValues = secchiRows.map(row => row ? row.secchi : null);
    const secchiMinValues = secchiRows.map(row => row ? row.secchiMin : null);
    const secchiMaxValues = secchiRows.map(row => row ? row.secchiMax : null);
    const secchiValid = [
        ...secchiValues,
        ...secchiMinValues,
        ...secchiMaxValues
    ].filter(value => value !== null && Number.isFinite(value));
    const secchiP95 = opticalPlotQuantile(secchiValid, 0.95);
    const secchiMax = secchiValid.length ? Math.max(...secchiValid) : null;
    const secchiAxisUpper = secchiValid.length
        ? Math.max(0.5, Math.min(secchiMax * 1.15, (secchiP95 || secchiMax) * 1.35))
        : 1;
    if (secchiValid.length) {
        traces.push({
            x,
            y: secchiValues,
            customdata: secchiRows.map(row => row ? [row.kd490, row.c490, row.a490, row.b490, row.bSource, row.kdSource] : [null, null, null, null, '', '']),
            name: opticalSecchiTraceName(secchiModel),
            type: 'scatter',
            mode: 'lines+markers',
            yaxis: 'y2',
            error_y: secchiModel === 'effler_kirk' ? {
                type: 'data',
                symmetric: false,
                array: secchiRows.map(row => row && row.secchiMax !== null ? Math.max(row.secchiMax - row.secchi, 0) : 0),
                arrayminus: secchiRows.map(row => row && row.secchiMin !== null ? Math.max(row.secchi - row.secchiMin, 0) : 0),
                color: 'rgba(225, 29, 72, 0.38)',
                thickness: 1.2,
                width: 2.5
            } : undefined,
            line: { color: '#e11d48', width: isFullscreen ? 2.9 : 2.45, dash: 'dash' },
            marker: { color: '#ffffff', size: isFullscreen ? 7 : 5.8, symbol: 'diamond', line: { color: '#e11d48', width: 1.35 } },
            connectgaps: false,
            hovertemplate: 'Semana %{x}<br>Secchi eq.: %{y:.2f} m<br>Kd490: %{customdata[0]:.3f} 1/m<br>Kd desde: %{customdata[5]}<br>c490 est.: %{customdata[1]:.3f} 1/m<br>a490: %{customdata[2]:.3f} 1/m<br>b490: %{customdata[3]:.3f} 1/m<br>b desde: %{customdata[4]}<extra></extra>'
        });
    }
    const selectedShape = selectedWeek ? [{
        type: 'line',
        x0: selectedWeek,
        x1: selectedWeek,
        y0: 0,
        y1: 1,
        xref: 'x',
        yref: 'paper',
        line: { color: '#334155', width: 1.2, dash: 'dot' }
    }] : [];
    const plotWidth = plotDiv.clientWidth || (isFullscreen ? 1100 : 320);
    const isCompact = !isFullscreen && plotWidth < 460;
    const sourceText = summarizeOpticalPlotSource(profile, isCompact, secchiModel);
    const sourceWrapped = wrapPlotText(sourceText, isFullscreen ? 128 : 48);
    const centerName = escapePlotText((profile.center && profile.center.name) || 'sitio');
    const layout = {
        margin: isFullscreen
            ? { l: 78, r: 86, t: 98, b: 108 }
            : { l: 56, r: 56, t: isCompact ? 54 : 78, b: 116 },
        paper_bgcolor: '#ffffff',
        plot_bgcolor: '#ffffff',
        font: {
            family: isFullscreen ? 'Times New Roman, Georgia, serif' : 'Arial, Helvetica, sans-serif',
            size: isFullscreen ? 13 : 10,
            color: '#17212b'
        },
        title: {
            text: isCompact
                ? ''
                : `Dinámica estacional bio-óptica<br><span style="font-size:${isFullscreen ? 14 : 11}px;">${centerName}: índice relativo y disco Secchi equivalente</span>`,
            x: 0.5,
            xanchor: 'center',
            font: { size: isFullscreen ? 21 : 14, color: '#111827' }
        },
        showlegend: true,
        legend: {
            orientation: 'h',
            x: 0.5,
            xanchor: 'center',
            y: isCompact ? 1.2 : 1.06,
            yanchor: 'bottom',
            bgcolor: 'rgba(255,255,255,0.92)',
            bordercolor: '#cbd5e1',
            borderwidth: 1,
            font: { size: isFullscreen ? 12 : 9 },
            tracegroupgap: 6
        },
        xaxis: {
            title: { text: isCompact ? 'Semana ISO' : 'Semana ISO del año', font: { size: isFullscreen ? 13 : 10 } },
            tickfont: { size: isFullscreen ? 12 : 9 },
            dtick: 4,
            range: [1, 53],
            fixedrange: true,
            showline: true,
            linewidth: 1,
            linecolor: '#111827',
            mirror: true,
            ticks: 'outside',
            gridcolor: '#e7edf3',
            zeroline: false
        },
        yaxis: {
            title: { text: isCompact ? 'Índice (0-1)' : 'Índice relativo por variable (0-1)', font: { size: isFullscreen ? 13 : 10 } },
            tickfont: { size: isFullscreen ? 12 : 9 },
            range: [0, 1.05],
            fixedrange: true,
            showline: true,
            linewidth: 1,
            linecolor: '#111827',
            mirror: true,
            ticks: 'outside',
            gridcolor: '#e7edf3',
            zeroline: false
        },
        yaxis2: {
            title: { text: isCompact ? 'Secchi eq. (m)' : 'Disco Secchi equivalente (m)', font: { size: isFullscreen ? 13 : 10, color: '#e11d48' } },
            tickfont: { size: isFullscreen ? 12 : 9, color: '#e11d48' },
            overlaying: 'y',
            side: 'right',
            autorange: false,
            range: [0, secchiAxisUpper],
            tickformat: '.2f',
            fixedrange: true,
            showline: true,
            linewidth: 1,
            linecolor: '#e11d48',
            ticks: 'outside',
            zeroline: false,
            gridcolor: 'rgba(0,0,0,0)'
        },
        shapes: selectedShape,
        annotations: [{
            xref: 'paper',
            yref: 'paper',
            x: 0,
            y: isFullscreen ? -0.21 : -0.36,
            xanchor: 'left',
            yanchor: 'top',
            align: 'left',
            showarrow: false,
            text: sourceWrapped,
            font: { size: isFullscreen ? 10 : 8.5, color: '#334155' }
        }],
        hovermode: 'x unified'
    };
    Plotly.react(plotDiv, traces, layout, {
        responsive: true,
        displayModeBar: false,
        toImageButtonOptions: {
            format: 'png',
            filename: opticalPlotFilename(profile),
            width: 1300,
            height: 760,
            scale: 3
        }
    });
    if (secchiValid.length) {
        Plotly.relayout(plotDiv, {
            'yaxis2.autorange': false,
            'yaxis2.range': [0, secchiAxisUpper],
            'yaxis2.tickformat': '.2f'
        });
    }
    plotDiv._opticalPlotFilename = opticalPlotFilename(profile);
    if (options.updateButtons !== false) setOpticalPlotDownloadEnabled(traces.length > 0);
    if (!plotDiv._opticalWeekClickBound) {
        plotDiv.on('plotly_click', event => {
            const weekNumber = event.points && event.points[0] && event.points[0].x;
            const select = document.getElementById('optical_week_select');
            const option = select && Array.from(select.options).find(item => item.value === String(weekNumber) && !item.disabled);
            if (option) {
                select.value = String(weekNumber);
                selectOpticalWeek();
            }
        });
        plotDiv._opticalWeekClickBound = true;
    }
}

function selectOpticalWeek() {
    const profile = window.currentOpticalWeeklyProfile;
    const select = document.getElementById('optical_week_select');
    if (!profile || !select || !select.value) return;
    const week = (profile.weeks || []).find(item => String(item.iso_week) === select.value);
    if (!week) return;
    window.currentOpticalPresets = buildSelectedWeekData(profile, week);
    const coverage = document.getElementById('optical_week_coverage');
    if (coverage) {
        const status = week.status === 'util' ? 'útil' : 'datos limitados';
        coverage.textContent = `Semana ${String(week.iso_week).padStart(2, '0')} · ${status}`;
    }
    const scenario = document.getElementById('optical_scenario_select').value || 'tipico';
    setOpticalAssistantStatus(summarizeOpticalPreset(window.currentOpticalPresets, scenario));
    renderOpticalWeeklyPlot(profile, week.iso_week);
}

function summarizeOpticalPreset(data, scenario) {
    const preset = data.presets && data.presets[scenario];
    if (!preset) return 'Sin preset seleccionado.';
    const optics = preset.optics || {};
    const conf = data.confidence || {};
    const kdTxt = conf.kd490_median ? ` · Kd490 med: ${conf.kd490_median}` : '';
    const yearRange = conf.years && conf.years.length
        ? `${conf.years[0]}–${conf.years[conf.years.length - 1]}`
        : 'sin años';
    const weekTxt = data.selected_week
        ? `Semana ISO ${String(data.selected_week).padStart(2, '0')} · ${yearRange} · `
        : '';
    const uncertaintyBits = [];
    if (conf.kd490_uncertainty_pct_median !== undefined) uncertaintyBits.push(`Kd490 ±${conf.kd490_uncertainty_pct_median}%`);
    if (conf.tss_uncertainty_pct_median !== undefined) uncertaintyBits.push(`SPM ±${conf.tss_uncertainty_pct_median}%`);
    if (conf.chl_uncertainty_pct_median !== undefined) uncertaintyBits.push(`Chl-a ±${conf.chl_uncertainty_pct_median}%`);
    if (conf.cdom_uncertainty_pct_median !== undefined) uncertaintyBits.push(`CDM ±${conf.cdom_uncertainty_pct_median}%`);
    if (conf.turbidity_uncertainty_fnu_median !== undefined) uncertaintyBits.push(`Turbidez ±${conf.turbidity_uncertainty_fnu_median} FNU`);
    if (conf.n_valid_pixels_median !== undefined) uncertaintyBits.push(`${conf.n_valid_pixels_median} px válidos`);
    const proxyBits = [];
    if (conf.tss_proxy_count) {
        const conversion = conf.tss_conversion || conf.fnu_to_tss_calibration || {};
        proxyBits.push(
            `TSS proxy: ${conf.tss_proxy_count}/${conf.n_observations || '?'} obs desde ${conf.tss_proxy_source || 'turbidez'}`
        );
        if (conversion.slope !== undefined) {
            proxyBits.push(`FNU→TSS: ${conversion.slope}·FNU + ${conversion.intercept || 0}`);
        }
    }
    const diagnostics = data.diagnostics || [];
    const diag = diagnostics
        .map(d => `${d.source || 'fuente'}: ${translateOpticalStatus(d.status)}`)
        .join(' · ');
    const reason = explainOpticalConfidence(data);
    return `${weekTxt}Confianza: <strong>${conf.level || 'n/d'}</strong>${kdTxt}<br>` +
        `TSS ${optics.tss} mg/L${conf.tss_proxy_count ? ' (proxy)' : ''} · CDOM ${optics.cdom_a440} 1/m · Chl-a ${optics.chl} mg/m3<br>` +
        `${proxyBits.length ? proxyBits.join(' · ') + '<br>' : ''}` +
        `${uncertaintyBits.length ? uncertaintyBits.join(' · ') + '<br>' : ''}` +
        `<strong>Motivo:</strong> ${reason}<br>` +
        `<span class="text-muted">${diag || conf.reason || ''}</span>`;
}

function translateOpticalStatus(status) {
    const labels = {
        ok: 'correcto',
        empty: 'sin datos válidos',
        skipped: 'omitida',
        error: 'error',
        not_implemented: 'no implementada'
    };
    return labels[status] || status || 'sin estado';
}

function explainOpticalConfidence(data) {
    const conf = data.confidence || {};
    const diagnostics = data.diagnostics || [];
    const isSingleWeek = data.period_mode === 'iso_week';
    if (data.weekly_status === 'limitada') {
        return isSingleWeek
            ? `La semana ISO puntual tiene cobertura limitada: ${conf.valid_days || 0} días válidos en ${conf.years && conf.years[0] ? conf.years[0] : 'el año solicitado'}.`
            : `La semana seleccionada tiene cobertura limitada: ${conf.valid_days || 0} días válidos en ${(conf.years || []).length} años.`;
    }
    if (conf.tss_proxy_count) {
        return `${conf.valid_days || conf.n_observations || 0} días válidos; TSS se obtuvo como proxy desde turbidez FNU en ${conf.tss_proxy_count} observaciones, por lo que conviene validar la conversión localmente.`;
    }
    if (data.weekly_status === 'util') {
        return isSingleWeek
            ? `${conf.valid_days || 0} días válidos respaldan la semana ISO puntual de ${conf.years && conf.years[0] ? conf.years[0] : 'el año solicitado'}.`
            : `${conf.valid_days || 0} días válidos distribuidos en ${(conf.years || []).length} años respaldan la semana con igual ponderación anual.`;
    }
    if (!conf.n_observations) {
        const details = diagnostics
            .filter(d => d.detail)
            .map(d => d.detail)
            .slice(0, 2);
        return details.length
            ? `No hubo observaciones satelitales válidas. ${details.join(' ')}`
            : 'No hubo observaciones satelitales válidas; se usaron proxies por clase de agua.';
    }
    if ((conf.valid_days || 0) < 4) {
        return `Solo ${conf.valid_days || conf.n_observations} días válidos respaldan el escenario.`;
    }
    if ((conf.valid_days || 0) < 10) {
        return `${conf.valid_days} días válidos permiten una estimación útil, pero todavía limitada.`;
    }
    if (conf.n_valid_pixels_median !== undefined && conf.n_valid_pixels_median < 4) {
        return 'La cantidad mediana de píxeles válidos es baja para el área consultada.';
    }
    return `${conf.valid_days} días válidos respaldan el escenario con cobertura suficiente.`;
}

function fetchOpticalWeeklyProfile() {
    const center = document.getElementById('optical_center_select').value;
    const lat = document.getElementById('optical_lat').value;
    const lon = document.getElementById('optical_lon').value;
    const source = document.getElementById('optical_source_select').value;
    const bufferM = document.getElementById('optical_buffer_m').value || 1000;
    const periodMode = (document.getElementById('optical_period_mode') || {}).value || 'history';
    const yearsBack = document.getElementById('optical_years_back').value || 3;
    const targetYear = document.getElementById('optical_target_year') ? document.getElementById('optical_target_year').value : '';
    const targetWeek = document.getElementById('optical_target_week') ? document.getElementById('optical_target_week').value : '';
    const fnuToTssSlope = document.getElementById('optical_fnu_tss_slope').value || 1.0;
    const fnuToTssIntercept = document.getElementById('optical_fnu_tss_intercept').value || 0.0;

    if (!center && (!lat || !lon)) {
        setOpticalAssistantStatus('Seleccione un centro o ingrese lat/lon.', true);
        return;
    }
    if (periodMode === 'iso_week') {
        const y = Number(targetYear);
        const w = Number(targetWeek);
        if (!Number.isInteger(y) || y < 2000 || y > 2100 || !Number.isInteger(w) || w < 1 || w > 53) {
            setOpticalAssistantStatus('Ingrese un año ISO válido y una semana ISO entre 1 y 53.', true);
            return;
        }
    }

    const params = new URLSearchParams();
    if (center) params.set('center', center);
    if (lat) params.set('lat', lat);
    if (lon) params.set('lon', lon);
    params.set('source', source);
    params.set('buffer_m', bufferM);
    if (periodMode === 'iso_week') {
        params.set('target_year', targetYear);
        params.set('target_week', targetWeek);
    } else {
        params.set('years_back', yearsBack);
    }
    params.set('fnu_to_tss_slope', fnuToTssSlope);
    params.set('fnu_to_tss_intercept', fnuToTssIntercept);
    // Modalidad "Medición local": el CSV subido reemplaza la consulta remota.
    if (isLocalObservationsMode()) params.set('observations_path', window.opticalObservationsPath);

    setOpticalAssistantStatus(periodMode === 'iso_week'
        ? `Analizando semana ISO ${String(targetWeek).padStart(2, '0')} de ${targetYear}. Esta consulta puede tardar...`
        : 'Analizando semanas históricas. Esta consulta puede tardar...');
    fetch(`/api/optical_weekly_profile?${params.toString()}`)
        .then(r => r.json())
        .then(data => {
            if (data.status !== 'ok') {
                setOpticalAssistantStatus(data.msg || 'No se pudieron obtener parámetros.', true);
                return;
            }
            window.currentOpticalWeeklyProfile = data;
            populateOpticalWeekSelect(data);
            const usefulCount = (data.weeks || []).filter(week => week.useful).length;
            const availableCount = (data.weeks || []).filter(week => week.status !== 'sin_datos').length;
            renderOpticalWeeklyPlot(data, null);
            if (availableCount) {
                selectOpticalWeek();
            } else {
                window.currentOpticalPresets = null;
                setOpticalAssistantStatus('No se encontraron semanas con datos válidos para la consulta.', true);
            }
            showStatusMessage(`${usefulCount} semanas bio-ópticas útiles encontradas`);
        })
        .catch(err => {
            console.error(err);
            setOpticalAssistantStatus('Error analizando las semanas bio-ópticas.', true);
        });
}

function fetchOpticalPresets() {
    fetchOpticalWeeklyProfile();
}

function applySelectedOpticalPreset() {
    const data = window.currentOpticalPresets;
    const scenario = document.getElementById('optical_scenario_select').value || 'tipico';
    const preset = data && data.presets && data.presets[scenario];
    if (!preset || !preset.optics) {
        setOpticalAssistantStatus('Primero obtenga parámetros para el escenario seleccionado.', true);
        return;
    }

    document.getElementById('optics_mode').value = preset.optics_mode || 'scattering';
    toggleOpticsPanel();
    document.getElementById('mc_input_type').value = preset.optics.mc_input_type || 'bio';
    toggleScatteringMode();
    document.getElementById('scat_tss').value = preset.optics.tss;
    document.getElementById('scat_cdom').value = preset.optics.cdom_a440;
    document.getElementById('scat_chl').value = preset.optics.chl;
    document.getElementById('scatter_g').value = preset.optics.g || 0.85;
    if (preset.optics.r_wall !== undefined) document.getElementById('scatter_rwall').value = preset.optics.r_wall;

    // Procedencia: de dónde salió cada número que acaba de escribirse.
    const local = isLocalObservationsMode();
    const conf = data.confidence || {};
    const parts = [];
    if (data.source) parts.push('fuente ' + data.source);
    if (data.week) parts.push('semana ISO ' + data.week);
    if (data.center_id) parts.push('centro ' + data.center_id);
    const bufferEl = document.getElementById('optical_buffer_m');
    if (bufferEl && bufferEl.value) parts.push('buffer ' + bufferEl.value + ' m');
    parts.push('escenario ' + scenario);
    const detail = parts.join(' · ');

    const origin = local ? 'csv' : 'satellite';
    setBioProvenance(origin, detail);
    // TSS derivado de turbidez no es una medición directa de sólidos suspendidos.
    if (conf.tss_is_proxy || conf.tss_proxy || preset.optics.tss_is_proxy) {
        window.bioProvenance.tss = 'proxy';
        renderBioProvenance();
    }
    const lastRun = document.getElementById('satellite_last_run');
    if (lastRun) lastRun.textContent = 'Último preset aplicado: ' + detail;

    updateBioOpticalReference();
    updateScene();
    updateRunSummary();
    setOpticalAssistantStatus(summarizeOpticalPreset(data, scenario));
    showStatusMessage(`Preset bio-óptico ${scenario} aplicado`);
}

/** True cuando la modalidad activa es CSV local y hay un archivo cargado. */
function isLocalObservationsMode() {
    const sel = document.getElementById('bio_param_source');
    return Boolean(sel && sel.value === 'csv' && window.opticalObservationsPath);
}

function toggleRoiPanel() {
    const type = document.getElementById('roi_type').value;
    setShown('roi_paral_panel', type === 'paralelepipedo');
    setShown('roi_cil_panel', type === 'cilindro');
    updateScene();
}

function toggleShapePanel() {
    const shape = document.getElementById('env_shape').value;
    setShown('shape_circle_inputs', shape === 'circle');
    setShown('shape_rect_inputs', shape === 'rect');
    updateScene();
}

/**
 * Disco Secchi equivalente coherente con el backend:
 *   - Si el coeficiente declarado es Kd (atenuación difusa): Poole-Atkins, Z_SD = 1.7/Kd
 *   - Si el coeficiente declarado es c (atenuación del haz): se estima Kd ≈ c·(1-ω·g)/μ̄_d
 *     con ω=0.8, g=0.85, μ̄_d=0.85 (Gershun/Kirk) y se aplica Preisendorfer
 *     Z_SD ≈ 8.69/(c+Kd).
 */
function hgBackscatterFraction(g) {
    if (Math.abs(g) < 1e-6) return 0.5;
    return ((1 - g) / (2 * g)) * ((1 + g) / Math.sqrt(1 + g * g) - 1);
}

// Lectura en vivo del disco de Secchi equivalente en el método escalar de Monte Carlo.
// Espeja el backend: c -> Kd (cierre Kirk o Lee 2005) -> modelo de Secchi.
function updateSecchiScatter() {
    const el = document.getElementById('secchi_display_scatter');
    if (!el) return;
    const cEl = document.getElementById('scatter_c');
    if (!cEl) { el.innerHTML = ''; return; }
    const c = parseFloat(cEl.value);
    if (!(c > 0)) { el.innerHTML = ''; return; }
    const omega = parseFloat((document.getElementById('scatter_omega') || {}).value) || 0.8;
    const g = parseFloat((document.getElementById('scatter_g') || {}).value) || 0.85;
    const mu_d = 0.85;
    const a = c * (1 - omega), b = c * omega;

    const phase = (document.getElementById('phase_function') || {}).value || 'hg';
    let B;
    if (phase === 'fournier_forand') {
        const bb = parseFloat((document.getElementById('bb_ratio') || {}).value);
        B = isNaN(bb) ? hgBackscatterFraction(g) : bb;
    } else { B = hgBackscatterFraction(g); }
    const bbCoef = B * b;

    const closure = (document.getElementById('kd_closure') || {}).value || 'kirk';
    const kd = (closure === 'lee2005')
        ? ((1 + 0.005 * 30) * a + 4.18 * (1 - 0.52 * Math.exp(-10.8 * a)) * bbCoef)
        : (a + (1 - g) * b) / mu_d;
    if (!(kd > 0)) { el.innerHTML = ''; return; }

    const model = (document.getElementById('secchi_model') || {}).value || 'preisendorfer';
    let Z;
    if (model === 'lee2015') {
        // r_w (reflectancia de fondo) desde la retrodispersión activa: Gordon R(0-)≈f·bb/(a+bb)
        const r_w = 0.33 * bbCoef / Math.max(a + bbCoef, 1e-9) / Math.PI;
        const r_T = 0.85 / Math.PI, c_t = 0.013;
        Z = Math.log(Math.abs(r_T - r_w) / c_t) / (2.5 * kd);
    } else if (model === 'poole_atkins') {
        Z = 1.7 / kd;
    } else {
        Z = 8.69 / (c + kd);
    }
    const closLbl = closure === 'lee2005' ? 'Lee 2005' : 'Kirk';
    el.innerHTML = `Eq. Disco Secchi (${secchiModelLabel(model)}): <span class="readout__value">${Z.toFixed(2)} m</span> · Kd≈${kd.toFixed(3)} 1/m (cierre ${closLbl})`;
}

function togglePhaseParams() {
    const sel = document.getElementById('phase_function');
    const box = document.getElementById('ff_params');
    if (sel && box) setShown(box, sel.value === 'fournier_forand');
}

function secchiModelLabel(model) {
    const m = (model || 'preisendorfer').toLowerCase();
    if (m === 'lee2015') return 'Lee 2015';
    if (m === 'poole_atkins') return 'Poole–Atkins';
    return 'Preisendorfer';
}

function computeSecchi(coefVal, coefType, model) {
    if (!(coefVal > 0)) return 0;
    const omega = 0.8, g = 0.85, mu_d = 0.85;
    const isKd = (coefType || 'c').toLowerCase() === 'kd';
    // Kd y c representativos según el tipo de coeficiente ingresado
    const kd = isKd ? coefVal : coefVal * (1.0 - omega * g) / mu_d;
    const c = isKd ? coefVal * mu_d / Math.max(1.0 - omega * g, 1e-3) : coefVal;
    const m = (model || 'preisendorfer').toLowerCase();
    if (m === 'lee2015') {
        // Lee et al. (2015): Z_SD = 1/(2.5·Kd_tr)·ln(|r_T-r_w|/C_t)
        const r_T = 0.85 / Math.PI, r_w = 0.02, c_t = 0.013;
        const contrast = Math.abs(r_T - r_w) / c_t;
        if (kd <= 0 || contrast <= 1) return 0;
        return Math.log(contrast) / (2.5 * kd);
    }
    if (m === 'poole_atkins') {
        // Poole & Atkins (1929): Z_SD ≈ 1.7/Kd (deriva Kd desde c cuando aplique)
        return kd > 0 ? 1.7 / kd : 0;
    }
    // Preisendorfer (1986) acoplado unificado: Z=8.69/(c+Kd) para c y Kd por igual,
    // derivando el coeficiente faltante con el mismo cierre bio-óptico.
    return 8.69 / (c + kd);
}

function updateSecchi() {
    const secchiEl = document.getElementById('secchi_display');
    if (!secchiEl) return;
    const coefType = (document.getElementById('atten_coef_type') || {}).value || 'c';
    const model = (document.getElementById('secchi_model') || {}).value || 'lee2015';
    const modelLbl = secchiModelLabel(model);
    const kdRaw = document.getElementById('kd_list').value;
    const kds = kdRaw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v) && v > 0);
    const secchis = kds.map(kd => computeSecchi(kd, coefType, model).toFixed(2) + 'm');
    const labelCoef = coefType.toLowerCase() === 'kd' ? 'Kd' : 'c';
    secchiEl.innerHTML = secchis.length ? `Eq. Disco Secchi (${labelCoef}, ${modelLbl}): ${secchis.join(' | ')}` : '';
}

function updateAporteBadge() {
    const input = document.getElementById('aporte_puntos');
    const badge = document.getElementById('aporte_puntos_badge');
    if (!input || !badge) return;
    const raw = input.value.trim();
    if (!raw) { badge.textContent = '0 pts'; badge.style.color = '#888'; return; }
    let n_ok = 0, n_bad = 0;
    raw.split(';').forEach(part => {
        const c = part.split(',');
        if (c.length === 3 && c.every(v => !isNaN(parseFloat(v.trim())))) n_ok++;
        else if (part.trim().length > 0) n_bad++;
    });
    if (n_bad > 0) {
        badge.innerHTML = `<span class="num--bad">${n_ok} ok · ${n_bad} mal formado</span>`;
    } else {
        badge.innerHTML = `<span class="num--ok">${n_ok} pts ✓</span>`;
    }
}

function updateAttenLabels() {
    const selEl = document.getElementById('atten_coef_type');
    if (!selEl) return;
    const isKd = selEl.value.toLowerCase() === 'kd';
    const labelTxt = isKd ? 'Kd' : 'c';
    const lblFijo = document.getElementById('atten_coef_label_fijo');
    if (lblFijo) lblFijo.innerHTML = `<strong>${labelTxt} (fijo) [1/m]</strong>`;
    const lblEspect = document.getElementById('atten_coef_label_espect');
    if (lblEspect) lblEspect.innerHTML = `<strong>${labelTxt}(λ)</strong> <span class="normal-case">(JSON [nm: ${labelTxt}])</span>`;
}

function updateBioOpticalReference() {
    const tssInput = document.getElementById('scat_tss');
    const cdomInput = document.getElementById('scat_cdom');
    if (!tssInput || !cdomInput) return;

    const tss = parseFloat(tssInput.value) || 0;
    const cdom = parseFloat(cdomInput.value) || 0;

    const b_star = { 400: 0.50, 500: 0.35, 600: 0.28, 700: 0.22 };
    const aw = { 400: 0.01, 500: 0.02, 600: 0.24, 700: 0.65 };

    const calcC = (wl) => {
        const a_cdom = cdom * Math.exp(-0.015 * (wl - 440));
        const b_total = b_star[wl] * tss;
        const a_total = aw[wl] + a_cdom;
        return (a_total + b_total).toFixed(2);
    };

    const refText = `Equivalencia Atenuación (c): 400nm: ${calcC(400)} | 500nm: ${calcC(500)} | 600nm: ${calcC(600)} | 700nm: ${calcC(700)}`;

    let displayDiv = document.getElementById('bio_optics_ref_display');
    if (!displayDiv) {
        displayDiv = document.createElement('div');
        displayDiv.id = 'bio_optics_ref_display';
        displayDiv.style = "font-size:11px; color:#1f77b4; margin-top:8px; font-weight:bold; text-align:center; padding: 4px; border: 1px dashed #1f77b4; border-radius: 4px; background: white;";
        const scatBio = document.getElementById('scat_bio');
        if (scatBio) scatBio.appendChild(displayDiv);
    }
    displayDiv.innerText = refText;
}

function handleMeasurementUpload(event) {
    const file = event.target.files[0];
    if (!file) return;

    showStatusMessage("Leyendo archivo...", "white");
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const data = new Uint8Array(e.target.result);
            const workbook = XLSX.read(data, {type: 'array'});
            const worksheet = workbook.Sheets[workbook.SheetNames[0]];
            const json = XLSX.utils.sheet_to_json(worksheet, {header: 1, defval: null});
            
            let parsedData = [];
            const pointsValidForKd = {}; 
            let xIdx = -1, yIdx = -1, zIdx = -1, valIdx = -1, startRow = -1;

            for (let i = 0; i < json.length; i++) {
                const row = json[i];
                if (!row || !row.length) continue;
                let tempX = -1, tempY = -1, tempZ = -1, tempVal = -1;
                for (let j = 0; j < row.length; j++) {
                    let cell = String(row[j] || '').toLowerCase().trim();
                    if (cell === 'x') tempX = j;
                    else if (cell === 'y') tempY = j;
                    else if (cell === 'z' || cell === 'profundidad' || cell === 'altura') tempZ = j;
                    else if (cell.includes('w/m') || cell.includes('val') || cell.includes('irr') || cell === 'e') tempVal = j;
                }
                if (tempX !== -1 && tempY !== -1 && tempZ !== -1 && tempVal !== -1) {
                    xIdx = tempX; yIdx = tempY; zIdx = tempZ; valIdx = tempVal; startRow = i + 1; break;
                }
            }

            if (startRow !== -1) {
                for (let i = startRow; i < json.length; i++) {
                    const row = json[i];
                    if (!row || row.length <= Math.max(xIdx, yIdx, zIdx, valIdx)) continue;
                    let x = parseFloat(row[xIdx]), y = parseFloat(row[yIdx]), z = parseFloat(row[zIdx]), val = parseFloat(row[valIdx]);
                    if (!isNaN(x) && !isNaN(y) && !isNaN(z) && !isNaN(val)) {
                        parsedData.push({x, y, z, val});
                        if (val > 0) {
                            const ptKey = `${x},${y}`;
                            if (!pointsValidForKd[ptKey]) pointsValidForKd[ptKey] = 0;
                            pointsValidForKd[ptKey]++;
                        }
                    }
                }
            }

            if (parsedData.length > 0) {
                window.measurements = parsedData;
                document.getElementById('meas_status').innerText = `Cargados ${parsedData.length} puntos.`;
                
                const kdSelector = document.getElementById('meas_point_selector');
                kdSelector.innerHTML = '<option value="">Seleccione coordenada (X,Y)...</option>';
                let addedPoints = 0;
                Object.keys(pointsValidForKd).forEach(pt => {
                    if (pointsValidForKd[pt] >= 2) {
                        kdSelector.innerHTML += `<option value="${pt}">Punto X=${pt.split(',')[0]}, Y=${pt.split(',')[1]}</option>`;
                        addedPoints++;
                    }
                });
                if (addedPoints === 0) kdSelector.innerHTML = '<option value="">Ningún punto con pares válidos (>0 W/m²)</option>';
                updateScene(); showStatusMessage("Archivo listo");
            } else {
                document.getElementById('meas_status').innerText = "Error: Columnas inválidas.";
            }
        } catch (err) { console.error(err); document.getElementById('meas_status').innerText = "Error al procesar."; }
    };
    reader.readAsArrayBuffer(file);
}

function calcKdFromMeasurements() {
    const pt = document.getElementById('meas_point_selector').value;
    if (!pt) { alert("Seleccione un punto válido."); return; }
    const targetX = parseFloat(pt.split(',')[0]);
    const targetY = parseFloat(pt.split(',')[1]);

    fetch('/api/calc_kd', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ x: targetX, y: targetY, measurements: window.measurements })
    }).then(r => r.json()).then(data => {
        if (data.status === 'ok') {
            const resArea = document.getElementById('results_dynamic_area');
            if(!resArea) return;
            let html = `<div class="result-card result-card--measure">
                            <div class="result-card__head">Resultados Kd empírico en (X=${targetX}, Y=${targetY})</div>
                            <div class="stack stack--tight">`;
            if (data.kds.length === 0) { html += `<div>No hay pares válidos.</div>`; } 
            else {
                data.kds.forEach(r => {
                    html += `<div class="kd-pair">
                               Z=${r.z1}m ➔ Z=${r.z2}m: <strong>Kd = ${r.kd.toFixed(3)}</strong>
                             </div>`;
                });
            }
            html += `</div></div>`;
            resArea.insertAdjacentHTML('afterbegin', html);
        }
    });
}

function applyModeSettings() {
    const config = modeConfigs[document.getElementById('mode-selector').value] || modeConfigs['estanque'];
    if(config) {
        currentSpaceType = config.type;
        document.getElementById('env_shape').value = config.shape;

        if(config.type === 'estanque') {
            setShown('env_z_container', false);
            document.getElementById('env_radio').value = config.radio;
            
            setShown('z_water_container', true);
            document.getElementById('z_water').value = config.z_water;
            setShown('env_n1_container', true);
            document.getElementById('env_n2_label').innerHTML = '<strong>Índice de refracción 2</strong> <span class="normal-case">(agua)</span>';
            setShown('wall_albedo_container', true);
        } else {
            setShown('env_z_container', true);
            document.getElementById('env_x').value = config.env_x;
            document.getElementById('env_y').value = config.env_y;
            document.getElementById('env_z').value = config.env_z;
            
            setShown('z_water_container', false);
            setShown('env_n1_container', false);
            document.getElementById('env_n2_label').innerHTML = '<strong>Índice de refracción</strong> <span class="normal-case">(agua)</span>';
            setShown('wall_albedo_container', false);
        }
        
        toggleShapePanel();
        
        document.getElementById('kd_list').value = config.kd_list;
        document.getElementById('target_depths').value = config.depths;
        document.getElementById('env_n1').value = config.n1 || 1.0;
        document.getElementById('env_n2').value = config.n2 || 1.33;
        
        updateSecchi();
        updateGlobalLampControls();
        updateScene(); updateLampLabels();
    }
}

function toggleSpectrumPanel() {
    const show = document.getElementById('plot_spectrum_initial').checked || document.getElementById('plot_spectrum_normalized').checked || document.getElementById('plot_env_optics').checked;
    setShown('spectrum_panel', show);
}

function infer3DModelDefaults(xml) {
    const name = String(xml || '').toLowerCase();
    if (name.includes('nexus') || name.includes('slim') || name.includes('fish')) {
        return {shape: 'box', length: 1.25, width: 0.16, height: 0.10};
    }
    if (name.includes('tempest') || name.includes('asteria')) {
        return {shape: 'cylinder', length: 0.55, width: 0.22, height: 0.22};
    }
    return {shape: 'cylinder', length: 0.60, width: 0.25, height: 0.25};
}

function get3DModelSettings() {
    const settings = {};
    document.querySelectorAll('.scene3d-model-row').forEach(row => {
        const xml = row.getAttribute('data-xml');
        settings[xml] = {
            shape: row.querySelector('.scene3d-model-shape').value,
            length: parseFloat(row.querySelector('.scene3d-model-length').value) || 0.6,
            width: parseFloat(row.querySelector('.scene3d-model-width').value) || 0.25,
            height: parseFloat(row.querySelector('.scene3d-model-height').value) || 0.25
        };
    });
    return settings;
}

function get3DRenderSettings() {
    return {
        show_water: document.getElementById('scene3d_show_water') ? document.getElementById('scene3d_show_water').checked : true,
        show_walls: document.getElementById('scene3d_show_walls') ? document.getElementById('scene3d_show_walls').checked : true,
        show_grid: document.getElementById('scene3d_show_grid') ? document.getElementById('scene3d_show_grid').checked : true,
        show_axes: document.getElementById('scene3d_show_axes') ? document.getElementById('scene3d_show_axes').checked : true,
        show_beams: document.getElementById('scene3d_show_beams') ? document.getElementById('scene3d_show_beams').checked : true,
        show_labels: document.getElementById('scene3d_show_labels') ? document.getElementById('scene3d_show_labels').checked : true,
        show_raytrace: document.getElementById('scene3d_show_raytrace') ? document.getElementById('scene3d_show_raytrace').checked : true,
        bio_attenuation: document.getElementById('scene3d_bio_attenuation') ? document.getElementById('scene3d_bio_attenuation').checked : true,
        show_light_globes: document.getElementById('scene3d_show_light_globes') ? document.getElementById('scene3d_show_light_globes').checked : true,
        water_opacity: parseFloat(document.getElementById('scene3d_water_opacity')?.value) || 0.22,
        beam_opacity: parseFloat(document.getElementById('scene3d_beam_opacity')?.value) || 0.28,
        lamp_scale: parseFloat(document.getElementById('scene3d_lamp_scale')?.value) || 1.0,
        exposure: parseFloat(document.getElementById('scene3d_exposure')?.value) || 1.0,
        raytrace_opacity: parseFloat(document.getElementById('scene3d_raytrace_opacity')?.value) || 0.72,
        light_globe_threshold_W_m2: parseFloat(document.getElementById('scene3d_light_globe_threshold')?.value) || 0.1,
        light_globe_resolution_m: parseFloat(document.getElementById('scene3d_light_globe_resolution')?.value) || 1.0,
        light_globe_opacity: parseFloat(document.getElementById('scene3d_light_globe_opacity')?.value) || 0.34,
        preset: document.getElementById('scene3d_preset')?.value || 'technical'
    };
}

function open3DSettingsPanel() {
    setActiveSection('scene3d');
    const section = document.getElementById('section_scene3d');
    if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function apply3DRenderPreset(preset) {
    const presets = {
        technical: {
            show_water: true, show_walls: true, show_grid: true, show_axes: true,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true, show_light_globes: true,
            water_opacity: 0.20, beam_opacity: 0.24, lamp_scale: 1.0, exposure: 1.0, raytrace_opacity: 0.72
        },
        presentation: {
            show_water: true, show_walls: true, show_grid: false, show_axes: false,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true, show_light_globes: true,
            water_opacity: 0.32, beam_opacity: 0.38, lamp_scale: 1.2, exposure: 1.25, raytrace_opacity: 0.80
        },
        turbid: {
            show_water: true, show_walls: true, show_grid: false, show_axes: false,
            show_beams: true, show_labels: true, show_raytrace: true, bio_attenuation: true, show_light_globes: true,
            water_opacity: 0.48, beam_opacity: 0.52, lamp_scale: 1.15, exposure: 0.9, raytrace_opacity: 0.85
        },
        wireframe: {
            show_water: false, show_walls: true, show_grid: true, show_axes: true,
            show_beams: false, show_labels: true, show_raytrace: false, bio_attenuation: false, show_light_globes: false,
            water_opacity: 0.1, beam_opacity: 0.1, lamp_scale: 1.0, exposure: 1.0, raytrace_opacity: 0.5
        }
    };
    const cfg = presets[preset] || presets.technical;
    const ids = {
        show_water: 'scene3d_show_water',
        show_walls: 'scene3d_show_walls',
        show_grid: 'scene3d_show_grid',
        show_axes: 'scene3d_show_axes',
        show_beams: 'scene3d_show_beams',
        show_labels: 'scene3d_show_labels',
        show_raytrace: 'scene3d_show_raytrace',
        bio_attenuation: 'scene3d_bio_attenuation',
        show_light_globes: 'scene3d_show_light_globes'
    };
    Object.entries(ids).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (el) el.checked = cfg[key];
    });
    const nums = {
        water_opacity: 'scene3d_water_opacity',
        beam_opacity: 'scene3d_beam_opacity',
        lamp_scale: 'scene3d_lamp_scale',
        exposure: 'scene3d_exposure',
        raytrace_opacity: 'scene3d_raytrace_opacity'
    };
    Object.entries(nums).forEach(([key, id]) => {
        const el = document.getElementById(id);
        if (el) el.value = cfg[key];
    });
    const presetEl = document.getElementById('scene3d_preset');
    if (presetEl) presetEl.value = preset;
    updateScene();
}

function setScene3DTransformMode(mode) {
    if (window.scene3dSetTransformMode) window.scene3dSetTransformMode(mode);
    else showStatusMessage("Abra la vista 3D antes de usar el gizmo", "white");
}

function clearScene3DSelection() {
    if (window.scene3dClearSelection) window.scene3dClearSelection();
}

function update3DLampModelControls() {
    const container = document.getElementById('scene3d_lamp_models');
    if (!container) return;

    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const existing = get3DModelSettings();

    if (uniqueLamps.size === 0) {
        container.innerHTML = '<span class="hint">Agregue lámparas para configurar su geometría 3D.</span>';
        return;
    }

    let html = '';
    uniqueLamps.forEach(xml => {
        const defaults = infer3DModelDefaults(xml);
        const cfg = existing[xml] || defaults;
        html += `
            <div class="scene3d-model-row" data-xml="${xml}">
                <div class="scene3d-model-title">${xml}</div>
                <div class="scene3d-model-controls">
                    <div>
                        <label>Forma</label>
                        <select class="scene3d-model-shape" onchange="updateScene()">
                            <option value="cylinder" ${cfg.shape === 'cylinder' ? 'selected' : ''}>Circular</option>
                            <option value="box" ${cfg.shape === 'box' ? 'selected' : ''}>Paralelepípeda</option>
                        </select>
                    </div>
                    <div>
                        <label>Largo (m)</label>
                        <input type="number" class="scene3d-model-length" value="${cfg.length}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                    <div>
                        <label>Ancho/Diam. (m)</label>
                        <input type="number" class="scene3d-model-width" value="${cfg.width}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                    <div>
                        <label>Alto (m)</label>
                        <input type="number" class="scene3d-model-height" value="${cfg.height}" min="0.01" step="0.05" oninput="updateScene()">
                    </div>
                </div>
            </div>`;
    });
    container.innerHTML = html;
}

function apply3DSceneSettings(scene3dConfig) {
    if (!scene3dConfig) return;
    const render = scene3dConfig.render || {};
    const checkboxMap = {
        show_water: 'scene3d_show_water',
        show_walls: 'scene3d_show_walls',
        show_grid: 'scene3d_show_grid',
        show_axes: 'scene3d_show_axes',
        show_beams: 'scene3d_show_beams',
        show_labels: 'scene3d_show_labels',
        show_raytrace: 'scene3d_show_raytrace',
        bio_attenuation: 'scene3d_bio_attenuation',
        show_light_globes: 'scene3d_show_light_globes'
    };
    Object.keys(checkboxMap).forEach(key => {
        if (render[key] !== undefined && document.getElementById(checkboxMap[key])) {
            document.getElementById(checkboxMap[key]).checked = Boolean(render[key]);
        }
    });

    const numericMap = {
        water_opacity: 'scene3d_water_opacity',
        beam_opacity: 'scene3d_beam_opacity',
        lamp_scale: 'scene3d_lamp_scale',
        exposure: 'scene3d_exposure',
        raytrace_opacity: 'scene3d_raytrace_opacity',
        light_globe_threshold_W_m2: 'scene3d_light_globe_threshold',
        light_globe_resolution_m: 'scene3d_light_globe_resolution',
        light_globe_opacity: 'scene3d_light_globe_opacity',
        preset: 'scene3d_preset'
    };
    Object.keys(numericMap).forEach(key => {
        if (render[key] !== undefined && document.getElementById(numericMap[key])) {
            document.getElementById(numericMap[key]).value = render[key];
        }
    });

    const models = scene3dConfig.lamp_models || {};
    Object.keys(models).forEach(xml => {
        const row = document.querySelector(`.scene3d-model-row[data-xml="${xml}"]`);
        if (!row) return;
        const cfg = models[xml];
        if (cfg.shape !== undefined) row.querySelector('.scene3d-model-shape').value = cfg.shape;
        if (cfg.length !== undefined) row.querySelector('.scene3d-model-length').value = cfg.length;
        if (cfg.width !== undefined) row.querySelector('.scene3d-model-width').value = cfg.width;
        if (cfg.height !== undefined) row.querySelector('.scene3d-model-height').value = cfg.height;
    });
}

function updateGlobalLampControls() {
    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const container = document.getElementById('global_lamps_container');

    const existing = {};
    container.querySelectorAll('.global-lamp-group').forEach(group => {
        const xml = group.getAttribute('data-xml');
        existing[xml] = {
            power: group.querySelector('.glob-power').value,
            z: group.querySelector('.glob-z').value
        };
    });

    let html = '';
    if (uniqueLamps.size > 0) {
        html += '<div class="subhead">Parámetros Globales por Modelo</div>';
    }
    uniqueLamps.forEach(xml => {
        const firstLampForModel = Array.from(document.querySelectorAll('.lamp-item')).find(item => {
            const xmlInput = item.querySelector('.lamp-xml');
            return xmlInput && xmlInput.value === xml;
        });
        const firstPower = firstLampForModel ? firstLampForModel.querySelector('.lamp-power')?.value : null;
        const firstZ = firstLampForModel ? firstLampForModel.querySelector('.lamp-z')?.value : null;
        const fallbackZ = currentSpaceType === 'estanque' ? parseFloat(document.getElementById('z_water').value) + 0.5 : 2.0;
        const pwr = existing[xml] ? existing[xml].power : (firstPower !== null && firstPower !== undefined ? firstPower : 600);
        const defZ = existing[xml] ? existing[xml].z : (firstZ !== null && firstZ !== undefined ? firstZ : fallbackZ);

        html += `
        <div class="global-lamp-group" data-xml="${xml}">
            <div class="global-lamp-group__title">${xml}</div>
            <div class="grid grid--2">
                <div class="field"><label class="field__label">Potencia eléctrica (W)</label><input type="number" class="glob-power" value="${pwr}" oninput="applyGlobal('${xml}', 'power', this.value)"></div>
                <div class="field"><label class="field__label">Altura Z (m)</label><input type="number" class="glob-z" value="${defZ}" oninput="applyGlobal('${xml}', 'z', this.value)"></div>
            </div>
        </div>`;
    });
    container.innerHTML = html;
    updateUniqueLampsForSpectrum();
    update3DLampModelControls();
}

function getGlobalLampSettings() {
    const settings = {};
    document.querySelectorAll('.global-lamp-group').forEach(group => {
        const xml = group.getAttribute('data-xml');
        settings[xml] = {
            power: parseFloat(group.querySelector('.glob-power').value) || 0,
            z: parseFloat(group.querySelector('.glob-z').value) || 0
        };
    });
    return settings;
}

function updateLampEfficiency(input) {
    if (!input) return;
    const item = input.closest('.lamp-item');
    if (!item) return;
    const power = parseFloat(input.value) || 0;
    const effInput = item.querySelector('.lamp-eff');
    const eff = effInput ? parseFloat(effInput.value) || 1.0 : 1.0;
    const rad = power * eff;
    const badge = item.querySelector('.eff-badge');
    if (badge) {
        badge.innerHTML = `Eficiencia WPE: <strong>${(eff*100).toFixed(1)}%</strong> | F. Radiante: <strong class="num--irr">${rad.toFixed(2)} W</strong>`;
    }
}

function applyGlobal(xml, type, value) {
    document.querySelectorAll('.lamp-item').forEach(item => {
        if (item.querySelector('.lamp-xml').value === xml) {
            const input = item.querySelector(type === 'power' ? '.lamp-power' : '.lamp-z');
            if (input.getAttribute('data-manual') !== 'true') {
                input.value = value;
                input.style.opacity = '0.5';
                if (type === 'power') updateLampEfficiency(input);
            }
        }
    });
    updateScene();
}

function removeLampManualOverride(inputElement) {
    inputElement.style.opacity = '1';
    inputElement.setAttribute('data-manual', 'true');
    updateScene();
}

function updateUniqueLampsForSpectrum() {
    const container = document.getElementById('spectrum_lamp_list');
    if (!container) return;
    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    const currentlyChecked = new Set();
    container.querySelectorAll('.spectrum-lamp-cb:checked').forEach(cb => currentlyChecked.add(cb.value));
    container.innerHTML = '';
    if(uniqueLamps.size === 0) { container.innerHTML = '<span class="hint">Agregue lámparas primero</span>'; return; }
    
    uniqueLamps.forEach(lampXml => {
        const isChecked = currentlyChecked.has(lampXml) || currentlyChecked.size === 0 ? 'checked' : '';
        container.innerHTML += `<label class="checkline"><input type="checkbox" class="spectrum-lamp-cb" value="${lampXml}" ${isChecked}> <span class="mono">${lampXml}</span></label>`;
        if (currentlyChecked.size === 0) currentlyChecked.add(lampXml);
    });
}

function updateLampLabels() {
    const txt = currentSpaceType === 'estanque' ? 'Altura desde fondo (m)' : 'Profundidad Z (m)';
    document.querySelectorAll('.z-label').forEach(lbl => lbl.innerHTML = `<strong>${txt}</strong>`);
    const simLbl = document.getElementById('lbl_target_depths');
    if (simLbl) simLbl.innerHTML = currentSpaceType === 'estanque' ? '<strong>Profundidades a graficar irradiancia</strong> <span class="normal-case">(metros desde el fondo, separadas por coma)</span>' : '<strong>Profundidades a graficar irradiancia</strong> <span class="normal-case">(metros, separadas por coma)</span>';
}

function getSpaceDimensions() {
    const shape = document.getElementById('env_shape').value;
    if (shape === 'circle') {
        const r = parseFloat(document.getElementById('env_radio').value) || 20;
        return { x: r * 2, y: r * 2, shape: 'circle', radius: r };
    } else {
        return { x: parseFloat(document.getElementById('env_x').value) || 40, y: parseFloat(document.getElementById('env_y').value) || 40, shape: 'rect' };
    }
}

function toggleLocalRefine() {
    const on = document.getElementById('local_refine');
    const params = document.getElementById('local_refine_params');
    if (on && params) setShown(params, on.checked);
}

function updateGridCellHint() {
    const el = document.getElementById('grid_cell_hint');
    const binsEl = document.getElementById('grid_bins');
    if (!el || !binsEl) return;
    let bins = parseInt(binsEl.value) || 100;
    bins = Math.max(20, Math.min(bins, 2000));
    try {
        const d = getSpaceDimensions();
        const ext = Math.max(d.x || 0, d.y || 0);
        const cell = ext / (bins - 1);
        const cm = cell * 100;
        el.textContent = `Celda ≈ ${cell >= 1 ? cell.toFixed(2) + ' m' : cm.toFixed(1) + ' cm'} (${bins-1}×${bins-1} celdas). Subir para resolver el campo cercano.`;
    } catch (e) { /* env aún no definido */ }
}

function getAxisTicks(maxVal) {
    let labelStep = 1;
    if (maxVal > 50) labelStep = 10;
    else if (maxVal > 20) labelStep = 5;
    else if (maxVal > 10) labelStep = 2;

    let vals = [];
    let texts = [];
    for (let i = -1; i <= Math.ceil(maxVal) + 1; i++) {
        vals.push(i);
        texts.push(i % labelStep === 0 ? i.toString() : '');
    }
    return { vals, texts };
}

function getPlotTraces() {
    const traces = [];
    const dims = getSpaceDimensions();
    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;
    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;

    const bgSize = 20;
    const zBg = Array(bgSize).fill().map(() => Array(bgSize).fill(0));
    const xBg = Array.from({length: bgSize}, (_, i) => (i / (bgSize-1)) * dims.x);
    const yBg = Array.from({length: bgSize}, (_, i) => (i / (bgSize-1)) * dims.y);
    
    traces.push({
        z: zBg, x: xBg, y: yBg, type: 'heatmap', showscale: false,
        colorscale: [[0, 'rgba(0,0,0,0)'], [1, 'rgba(0,0,0,0)']], hoverinfo: 'none', name: 'Fondo'
    });

    if (dims.shape === 'circle') {
        let cx = dims.x / 2, cy = dims.y / 2, r = dims.radius;
        let bx = [], by = [];
        for(let i=0; i<=100; i++) {
            let angle = i * 2 * Math.PI / 100;
            bx.push(cx + r * Math.cos(angle));
            by.push(cy + r * Math.sin(angle));
        }
        traces.push({x: bx, y: by, mode: 'lines', line: {color: 'rgba(255, 199, 44, 1)', width: 2, dash: 'dash'}, hoverinfo: 'none', showlegend: false, name: 'Límite Estanque'});
    } else {
        traces.push({x: [0, dims.x, dims.x, 0, 0], y: [0, 0, dims.y, dims.y, 0], mode: 'lines', line: {color: 'rgba(255, 199, 44, 1)', width: 2, dash: 'dash'}, hoverinfo: 'none', showlegend: false, name: 'Límite Jaula'});
    }

    let roiType = document.getElementById('roi_type').value;
    if (roiType === 'paralelepipedo') {
        let cx = parseFloat(document.getElementById('roi_p_cx').value) || 0;
        let cy = parseFloat(document.getElementById('roi_p_cy').value) || 0;
        let l = parseFloat(document.getElementById('roi_p_l').value) || 0;
        let w = parseFloat(document.getElementById('roi_p_w').value) || 0;
        traces.push({x: [cx-l/2, cx+l/2, cx+l/2, cx-l/2, cx-l/2], y: [cy-w/2, cy-w/2, cy+w/2, cy+w/2, cy-w/2], mode: 'lines', line: {color: 'rgba(214, 39, 40, 0.8)', width: 2, dash: 'dashdot'}, hoverinfo: 'none', showlegend: false, name: 'ROI'});
    } else if (roiType === 'cilindro') {
        let cx = parseFloat(document.getElementById('roi_c_cx').value) || 0;
        let cy = parseFloat(document.getElementById('roi_c_cy').value) || 0;
        let r = parseFloat(document.getElementById('roi_c_r').value) || 0;
        let bx = [], by = [];
        for(let i=0; i<=50; i++) {
            let angle = i * 2 * Math.PI / 50;
            bx.push(cx + r * Math.cos(angle));
            by.push(cy + r * Math.sin(angle));
        }
        traces.push({x: bx, y: by, mode: 'lines', line: {color: 'rgba(214, 39, 40, 0.8)', width: 2, dash: 'dashdot'}, hoverinfo: 'none', showlegend: false, name: 'ROI'});
    }

    let numSides = parseInt(document.getElementById('poly_sides').value) || 0;
    let polyDist = parseFloat(document.getElementById('poly_dist').value) || 0;
    if (numSides >= 3 && polyDist > 0) {
        let cx = dims.x / 2, cy = dims.y / 2;
        let px = [], py = [];
        for (let i = 0; i <= numSides; i++) {
            let angle = (i * 2 * Math.PI) / numSides - Math.PI / 2; 
            px.push(cx + polyDist * Math.cos(angle));
            py.push(cy + polyDist * Math.sin(angle));
        }
        traces.push({ x: px, y: py, mode: 'lines', line: { color: 'rgba(31, 119, 180, 0.8)', width: 1.5, dash: 'dot' }, hoverinfo: 'none', showlegend: false, name: 'Polígono Ref.' });
    }

    const lampTextX = [], lampTextY = [], lampText = [];
    const aerialX = [], aerialY = [], aerialText = [], aerialOpacity = [];
    const submergedX = [], submergedY = [], submergedText = [], submergedOpacity = [];
    
    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        let x = parseFloat(item.querySelector('.lamp-x').value) || 0;
        let y = parseFloat(item.querySelector('.lamp-y').value) || 0;
        let z = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let rx = parseFloat(item.querySelector('.lamp-rot-x').value) || 0;
        let ry = parseFloat(item.querySelector('.lamp-rot-y').value) || 0;
        let rz = parseFloat(item.querySelector('.lamp-rot-z').value) || 0;
        let xml = item.querySelector('.lamp-xml').value;

        let isAerial = (currentSpaceType === 'estanque' && z > zInterface) || (currentSpaceType === 'jaula' && z < 0);
        const isOn = isAerial ? activeAerial : activeSubmerged;

        let label = item.getAttribute('data-label') || `L${index + 1}`;
        lampTextX.push(x); lampTextY.push(y); lampText.push(isOn ? label : `${label} OFF`);
        if (isAerial) {
            aerialX.push(x); aerialY.push(y); aerialText.push(label); aerialOpacity.push(isOn ? 1.0 : 0.25);
        } else {
            submergedX.push(x); submergedY.push(y); submergedText.push(label); submergedOpacity.push(isOn ? 1.0 : 0.25);
        }

        let profile = window.lampProfiles[xml];
        if (profile) {
            const VISUAL_SCALE = parseFloat(document.getElementById('beam_scale').value) || 8.0; 
            const radX = rx * Math.PI / 180, radY = ry * Math.PI / 180, radZ = rz * Math.PI / 180;
            const cosX = Math.cos(radX), sinX = Math.sin(radX);
            const cosY = Math.cos(radY), sinY = Math.sin(radY);
            const cosZ = Math.cos(radZ), sinZ = Math.sin(radZ);
            
            let polyAlpha = isOn ? 0.8 : 0.25;
            let fillAlpha = isOn ? 0.25 : 0.07;
            let polyColor = isAerial ? `rgba(255, 199, 44, ${polyAlpha})` : `rgba(0, 191, 255, ${polyAlpha})`;
            let polyFill = isAerial ? `rgba(255, 199, 44, ${fillAlpha})` : `rgba(0, 191, 255, ${fillAlpha})`;

            function projectPlane(planeData, isC90) {
                let ptsX = [], ptsY = [];
                for (let i=0; i < planeData.theta.length; i++) {
                    let theta = planeData.theta[i] * Math.PI / 180;
                    let r = planeData.rad[i] * VISUAL_SCALE;
                    let lx = 0, lz = 0, ly = 0; 
                    
                    if (!isC90) {
                        lx = r * Math.sin(theta);
                        lz = -r * Math.cos(theta);
                    } else {
                        ly = r * Math.sin(theta);
                        lz = -r * Math.cos(theta);
                    }

                    let y1 = ly * cosX - lz * sinX;
                    let z1 = ly * sinX + lz * cosX;
                    let x1 = lx * cosY + z1 * sinY;
                    let x2 = x1 * cosZ - y1 * sinZ;
                    let y2 = x1 * sinZ + y1 * cosZ;
                    
                    ptsX.push(x + x2); ptsY.push(y + y2);
                }
                return {x: ptsX, y: ptsY};
            }
            
            let p0 = projectPlane(profile.c0_180, false);
            let p90 = projectPlane(profile.c90_270, true);

            traces.push({
                x: p0.x, y: p0.y, mode: 'lines', fill: 'toself',
                fillcolor: polyFill, line: {color: polyColor, width: 2},
                hoverinfo: 'none', showlegend: false, name: `${label} C0`
            });

            traces.push({
                x: p90.x, y: p90.y, mode: 'lines', fill: 'toself',
                fillcolor: 'rgba(31, 119, 180, 0.1)', line: {color: polyColor, width: 2, dash: 'dot'},
                hoverinfo: 'none', showlegend: false, name: `${label} C90`
            });
        } else {
            fetchLampProfile(xml);
        }
    });

    if (aerialX.length > 0) {
        traces.push({
            x: aerialX, y: aerialY, mode: 'markers', type: 'scatter', name: 'Lámparas aéreas',
            marker: { size: 12, color: '#FFD700', symbol: 'diamond', line: { color: 'black', width: 1.5 }, opacity: aerialOpacity },
            text: aerialText, hovertemplate: '%{text}<br>Aérea<extra></extra>', showlegend: true
        });
    }

    if (submergedX.length > 0) {
        traces.push({
            x: submergedX, y: submergedY, mode: 'markers', type: 'scatter', name: 'Lámparas sumergidas',
            marker: { size: 14, color: '#00BFFF', symbol: 'star', line: { color: 'black', width: 1.5 }, opacity: submergedOpacity },
            text: submergedText, hovertemplate: '%{text}<br>Sumergida<extra></extra>', showlegend: true
        });
    }

    traces.push({ 
        x: lampTextX, y: lampTextY, mode: 'text', type: 'scatter', name: 'Lámparas_Texto', 
        text: lampText, textposition: 'top right', textfont: { color: 'var(--evolux-black)', size: 14, weight: 'bold' }, 
        hoverinfo: 'none', showlegend: false 
    });

    if (window.measurements && window.measurements.length > 0) {
        const measX = [], measY = [];
        window.measurements.forEach(m => { measX.push(m.x); measY.push(m.y); });
        traces.push({ 
            x: measX, y: measY, mode: 'markers', type: 'scatter', name: 'Mediciones', 
            marker: { size: 8, color: '#1f77b4', symbol: 'diamond', line: { color: 'white', width: 1 } }, 
            hoverinfo: 'none', showlegend: false 
        });
    }

    let aporteStr = document.getElementById('aporte_puntos').value;
    if (aporteStr.trim()) {
        let apX=[], apY=[];
        aporteStr.split(';').forEach(part => {
            let c = part.split(',');
            if (c.length === 3 && !isNaN(parseFloat(c[0])) && !isNaN(parseFloat(c[1]))) {
                apX.push(parseFloat(c[0])); apY.push(parseFloat(c[1]));
            }
        });
        if (apX.length > 0) {
            traces.push({ 
                x: apX, y: apY, mode: 'markers+text', type: 'scatter', name: 'Puntos Aporte', 
                text: Array(apX.length).fill('📌'), textposition: 'top center', textfont: {size: 16},
                marker: { size: 10, color: 'magenta', symbol: 'cross', line: { color: 'white', width: 1 } }, 
                hoverinfo: 'none', showlegend: false 
            });
        }
    }

    return traces;
}

function getLayoutWithBoundary() {
    const dims = getSpaceDimensions();
    const xTicks = getAxisTicks(dims.x);
    const yTicks = getAxisTicks(dims.y);

    const layout = { 
        margin: {t: 20, r: 20, l: 40, b: 40}, 
        xaxis: { 
            title: 'Coordenada X (m)', 
            range: [-1, dims.x + 1], 
            tickmode: 'array', 
            tickvals: xTicks.vals, 
            ticktext: xTicks.texts, 
            gridcolor: '#eee'
        }, 
        yaxis: { 
            title: 'Coordenada Y (m)', 
            range: [-1, dims.y + 1], 
            scaleanchor: 'x', 
            scaleratio: 1, 
            tickmode: 'array', 
            tickvals: yTicks.vals, 
            ticktext: yTicks.texts, 
            gridcolor: '#eee'
        }, 
        shapes: [], annotations: []
    };

    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;
    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;

    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        let x = parseFloat(item.querySelector('.lamp-x').value) || 0;
        let y = parseFloat(item.querySelector('.lamp-y').value) || 0;
        let z = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let rx = parseFloat(item.querySelector('.lamp-rot-x').value) || 0;
        let ry = parseFloat(item.querySelector('.lamp-rot-y').value) || 0;
        
        let isAerial = (currentSpaceType === 'estanque' && z > zInterface) || (currentSpaceType === 'jaula' && z < 0);
        const isOn = isAerial ? activeAerial : activeSubmerged;

        let coreColor = isAerial ? 'var(--evolux-yellow)' : '#00bfff';

        layout.shapes.push({
            type: 'circle',
            x0: x - 0.4, y0: y - 0.4, x1: x + 0.4, y1: y + 0.4,
            fillcolor: coreColor, opacity: isOn ? 1.0 : 0.25, line: { color: 'black', width: 2 }
        });

        if (rx !== 0 || ry !== 0) {
            layout.annotations.push({ x: x, y: y + 1.2, text: `Tilt: ${rx}°, ${ry}°`, showarrow: false, font: {size: 11, color: '#1f77b4', weight: 'bold'} });
        }
    });

    return layout;
}

function updateScene() {
    if (typeof Plotly === 'undefined') {
        if (window.updateScene3D) window.updateScene3D();
        return;
    }
    const layout = getLayoutWithBoundary();
    const traces = getPlotTraces();
    
    Plotly.react('heatmap_div_preview', traces, layout, {
        responsive: true, displaylogo: false, 
        edits: {shapePosition: true} 
    }).then(function(plotDiv){
        
        if (!plotDiv.__clickAttached) {
            plotDiv.on('plotly_click', function(data){
                if(data.points.length > 0){
                    let x = data.points[0].x.toFixed(2);
                    let y = data.points[0].y.toFixed(2);
                    document.getElementById('preview_coords').innerHTML = `📍 Coordenada: <strong>X=${x}, Y=${y}</strong>`;
                }
            });
            plotDiv.__clickAttached = true;
        }

        if (!plotDiv.__dragAttached) {
            plotDiv.on('plotly_relayout', function(eventData){
                let updated = false;
                let lampItems = document.querySelectorAll('.lamp-item');

                for (let key in eventData) {
                    let match = key.match(/shapes\[(\d+)\]\.(x0|x1|y0|y1)/);
                    if (match) {
                        let shapeIdx = parseInt(match[1]);
                        if (shapeIdx >= 0 && shapeIdx < lampItems.length) {
                            let shape = plotDiv.layout.shapes[shapeIdx];
                            let newX = (shape.x0 + shape.x1) / 2;
                            let newY = (shape.y0 + shape.y1) / 2;
                            
                            let inputX = lampItems[shapeIdx].querySelector('.lamp-x');
                            let inputY = lampItems[shapeIdx].querySelector('.lamp-y');
                            let oldX = parseFloat(inputX.value) || 0;
                            let oldY = parseFloat(inputY.value) || 0;
                            
                            if (Math.abs(newX - oldX) > 0.05 || Math.abs(newY - oldY) > 0.05) {
                                inputX.value = newX.toFixed(2);
                                inputY.value = newY.toFixed(2);
                                updated = true;
                            }
                        }
                    }
                }
                if (updated) {
                    setTimeout(() => { updateScene(); }, 150);
                }
            });
            plotDiv.__dragAttached = true;
        }
    });

    if (window.updateScene3D) window.updateScene3D();
}

function loadAvailableLamps() {
    fetch('/api/get_lamps').then(r => r.json()).then(data => {
        if(data.status === 'ok') {
            const sel = document.getElementById('lamp_model_selector');
            sel.innerHTML = ''; 
            if(data.lamps.length === 0) sel.innerHTML = '<option value="">No hay lámparas (suba una)</option>';
            else { data.lamps.forEach(lamp => { const opt = document.createElement('option'); opt.value = lamp; opt.text = lamp; sel.add(opt); }); sel.value = data.lamps[0]; }
        }
    });
}

window.onload = function() {
    applyModeSettings();
    loadAvailableLamps();
    loadOpticalCenters();
    loadOpticalSourceStatus();
    updateAttenLabels();
    updateSecchi();
    updateAporteBadge();
    togglePinealParams();
    toggleOpticalPeriodMode();
    updateGridCellHint();

    const tssInput = document.getElementById('scat_tss');
    const cdomInput = document.getElementById('scat_cdom');
    const chlInput = document.getElementById('scat_chl');
    if (tssInput) tssInput.addEventListener('input', updateBioOpticalReference);
    if (cdomInput) cdomInput.addEventListener('input', updateBioOpticalReference);
    if (chlInput) chlInput.addEventListener('input', updateBioOpticalReference);
    const opticalScenario = document.getElementById('optical_scenario_select');
    if (opticalScenario) {
        opticalScenario.addEventListener('change', () => {
            if (window.currentOpticalPresets) {
                setOpticalAssistantStatus(summarizeOpticalPreset(window.currentOpticalPresets, opticalScenario.value));
            }
        });
    }
    const opticalWeek = document.getElementById('optical_week_select');
    if (opticalWeek) opticalWeek.addEventListener('change', selectOpticalWeek);

    updateBioOpticalReference();
};

document.addEventListener('keydown', event => {
    if (event.key === 'Escape') closeContextHelp();
});

/* =============================================================================
 *  ECUACIONES
 *  Render con KaTeX y sustitución de los valores activos del modelo, para que
 *  la documentación muestre la transformación con los números reales en uso.
 * ========================================================================== */

/** Renderiza todo bloque [data-tex] dentro de un contenedor. Si KaTeX no está
 *  disponible, deja el TeX legible en monoespaciado en vez de fallar en silencio. */
function renderKatexIn(root) {
    if (!root) return;
    const blocks = root.querySelectorAll('[data-tex]');
    blocks.forEach(el => {
        const tex = el.getAttribute('data-tex');
        if (!tex) return;
        // katex.render() reemplaza el contenido del nodo, así que el número de
        // ecuación se rescata y se vuelve a insertar después.
        const numEl = el.querySelector('.eq__num');
        const numHtml = numEl ? numEl.outerHTML : '';

        if (typeof katex === 'undefined') {
            el.textContent = tex;
            el.insertAdjacentHTML('beforeend', numHtml);
            el.setAttribute('data-katex-failed', '1');
            return;
        }
        try {
            katex.render(tex, el, { displayMode: true, throwOnError: false, output: 'html' });
            el.removeAttribute('data-katex-failed');
        } catch (err) {
            el.textContent = tex;
            el.setAttribute('data-katex-failed', '1');
        }
        el.insertAdjacentHTML('beforeend', numHtml);
    });
}

/** Sustituye los marcadores [data-live] por el valor activo del formulario. */
function refreshEquationValues(root) {
    if (!root) return;
    const num = (id, dflt) => {
        const el = document.getElementById(id);
        const v = el ? parseFloat(el.value) : NaN;
        return isNaN(v) ? dflt : v;
    };
    const values = {
        tss: num('scat_tss', 15).toFixed(2),
        cdom: num('scat_cdom', 1).toFixed(3),
        chl: num('scat_chl', 0).toFixed(2),
        g: num('scatter_g', 0.85).toFixed(2),
        fnu_slope: num('optical_fnu_tss_slope', 1).toFixed(3),
        fnu_intercept: num('optical_fnu_tss_intercept', 0).toFixed(3),
        buffer: num('optical_buffer_m', 6000).toFixed(0),
        bb_ratio: num('bb_ratio', 0.018).toFixed(4)
    };
    const tss = parseFloat(values.tss), cdom = parseFloat(values.cdom), chl = parseFloat(values.chl);
    const g = parseFloat(values.g);
    const aCdom490 = cdom * Math.exp(-0.015 * 50.0);

    // --- Ecuaciones (8)-(11): espejan _estimate_kd490() de optical_lookup.py,
    //     que usa constantes fijas a 490 nm, no la tabla interpolada. ---
    const a490fit = 0.026 + aCdom490 + 0.012 * chl;
    const b490fit = 0.35 * tss;
    const kd490fit = (a490fit + (1 - g) * b490fit) / 0.85;
    values.a490 = a490fit.toFixed(4);
    values.b490 = b490fit.toFixed(3);
    values.kd490 = kd490fit.toFixed(4);

    // --- Ecuaciones (13)-(15): espejan bio_optical_iop() del motor, que
    //     interpola linealmente la tabla de 7 nodos. A 490 nm los dos caminos
    //     no coinciden exactamente; por eso se calculan por separado. ---
    const WL = [400, 450, 500, 550, 600, 650, 700];
    const interpAt = (nodes, wl) => {
        if (wl <= WL[0]) return nodes[0];
        if (wl >= WL[WL.length - 1]) return nodes[nodes.length - 1];
        let i = 0;
        while (WL[i + 1] < wl) i++;
        const t = (wl - WL[i]) / (WL[i + 1] - WL[i]);
        return nodes[i] + t * (nodes[i + 1] - nodes[i]);
    };
    const aw490 = interpAt([0.018, 0.015, 0.026, 0.064, 0.245, 0.349, 0.624], 490);
    const bstar490 = interpAt([0.50, 0.42, 0.35, 0.31, 0.28, 0.25, 0.22], 490);
    const aphy490 = interpAt([0.022, 0.038, 0.012, 0.005, 0.005, 0.018, 0.008], 490);
    const a490 = aw490 + aCdom490 + aphy490 * chl;
    const b490 = bstar490 * tss;
    const kd490 = (a490 + (1 - g) * b490) / 0.85;
    values.c490 = (a490 + b490).toFixed(3);
    values.zsd = (8.69 / (a490 + b490 + kd490)).toFixed(2);

    root.querySelectorAll('[data-live]').forEach(el => {
        const key = el.getAttribute('data-live');
        if (values[key] !== undefined) el.textContent = values[key];
    });
}

function uploadXML(input) {
    const file = input.files[0]; if(!file) return;
    const formData = new FormData(); formData.append('file', file);
    fetch('/api/upload_lamp', { method: 'POST', body: formData }).then(r => r.json()).then(data => {
        if(data.status === 'ok') {
            const sel = document.getElementById('lamp_model_selector');
            if (sel.options[0] && sel.options[0].value === "") sel.remove(0); 
            let exists = Array.from(sel.options).some(opt => opt.value === data.filename);
            if (!exists) { const opt = document.createElement('option'); opt.value = data.filename; opt.text = data.filename; sel.add(opt); }
            sel.value = data.filename; showStatusMessage(`Lámpara guardada: ${data.filename}`);
        } else { alert("Error: " + data.msg); }
        input.value = '';
    });
}

function createLampElement(lampObj) {
    const model = lampObj.xml;
    const containerId = `group-${model.replace(/[^a-zA-Z0-9]/g, '-')}`;
    let groupContainer = document.getElementById(containerId);
    
    if (!groupContainer) {
        const list = document.getElementById('lamp-list');
        groupContainer = document.createElement('div');
        groupContainer.id = containerId;
        groupContainer.className = 'lamp-group-container';
        groupContainer.setAttribute('data-model', model);
        
        const safeModel = model.replace(/'/g, "&#39;").replace(/"/g, '&quot;');
        groupContainer.innerHTML = `
            <div class="lamp-group__head">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"></path></svg>
                <span class="lamp-group__name">${model.replace('.xml', '').replace('.ies', '')}</span>
                <button type="button" class="btn btn--sm" title="Ver curva polar IES" onclick="showLampDiagnostic('${safeModel}', 'polar')">📈 Polar</button>
                <button type="button" class="btn btn--sm" title="Ver beam 3D" onclick="showLampDiagnostic('${safeModel}', '3d')">🔦 Beam 3D</button>
            </div>
            <div class="lamp-items-wrapper"></div>
        `;
        list.appendChild(groupContainer);
    }

    const wrapper = groupContainer.querySelector('.lamp-items-wrapper');
    
    lampCount++;
    const id = lampCount;
    
    const div = document.createElement('div');
    div.className = 'lamp-item';
    div.id = `lamp-${id}`;

    const zLabelText = currentSpaceType === 'estanque' ? 'Altura (m)' : 'Profundidad (m)';
    const zOpacity = lampObj.manual_z ? '1.0' : (lampObj.opacity || '1.0');
    const pOpacity = lampObj.manual_power ? '1.0' : (lampObj.opacity || '1.0');

    div.innerHTML = `
        <div class="lamp-item__head">
            <span class="lamp-title-text"></span>
            <button type="button" class="btn-remove" title="Eliminar lámpara" aria-label="Eliminar lámpara" onclick="removeLamp(${id})">×</button>
        </div>
        <input type="hidden" class="lamp-xml" value="${model}">
        <div class="lamp-item__grid">
            <div class="field"><label class="field__label">X</label><input type="number" class="lamp-x" value="${lampObj.x}" oninput="updateScene()"></div>
            <div class="field"><label class="field__label">Y</label><input type="number" class="lamp-y" value="${lampObj.y}" oninput="updateScene()"></div>
            <div class="field z-label-container"><label class="field__label">${zLabelText}</label><input type="number" class="lamp-z" value="${lampObj.z}" data-manual="${lampObj.manual_z ? 'true' : 'false'}" style="opacity:${zOpacity};" oninput="removeLampManualOverride(this)"></div>

            <div class="lamp-item__power span-all">
                <div class="row row--between">
                    <span class="field__label">Potencia eléctrica de consumo (W)</span>
                    <span class="eff-badge badge">Flujo radiante: -- W</span>
                </div>
                <input type="number" class="lamp-power" value="${lampObj.power}" data-manual="${lampObj.manual_power ? 'true' : 'false'}" style="opacity:${pOpacity};" oninput="removeLampManualOverride(this); updateLampEfficiency(this)">
                <input type="hidden" class="lamp-eff" value="${lampObj.efficiency || 1.0}">
            </div>

            <div class="field"><label class="field__label">Rot X°</label><input type="number" class="lamp-rot-x" value="${lampObj.rot_x || 0}" oninput="updateScene()"></div>
            <div class="field"><label class="field__label">Rot Y°</label><input type="number" class="lamp-rot-y" value="${lampObj.rot_y || 0}" oninput="updateScene()"></div>
            <div class="field"><label class="field__label">Rot Z°</label><input type="number" class="lamp-rot-z" value="${lampObj.rot_z || 0}" oninput="updateScene()"></div>

            <div class="span-all lamp-item__cob-note">
                <span class="hint">COB (fuente de área, sólo en modo "Área finita") — dimensiones en metros</span>
            </div>
            <div class="field"><label class="field__label">COB Largo (m)</label><input type="number" step="0.001" class="lamp-cob-length" value="${(lampObj.cob && lampObj.cob.length) || 0}"></div>
            <div class="field"><label class="field__label">COB Ancho (m)</label><input type="number" step="0.001" class="lamp-cob-width" value="${(lampObj.cob && lampObj.cob.width) || 0}"></div>
            <div class="field"><label class="field__label">COB Forma</label>
                <select class="lamp-cob-shape">
                    <option value="rect" ${(lampObj.cob && lampObj.cob.shape === 'disk') ? '' : 'selected'}>Rectángulo</option>
                    <option value="disk" ${(lampObj.cob && lampObj.cob.shape === 'disk') ? 'selected' : ''}>Disco (Ø = Largo)</option>
                </select>
            </div>
        </div>
    `;
    wrapper.appendChild(div);
    updateRunSummary();
    
    updateLampNames();
    updateGlobalLampControls(); 
    updateLampEfficiency(div.querySelector('.lamp-power'));
    fetchLampProfile(model); 
    updateScene();
}

async function addLamp() {
    try {
        const sel = document.getElementById('lamp_model_selector');
        const model = sel ? sel.value : null;
        if(!model || model === "") { alert("Primero seleccione un modelo de lámpara."); return; }

        let profile = window.lampProfiles[model];
        if (!profile) {
            profile = await fetchLampProfile(model);
        }

        const dims = getSpaceDimensions();
        
        let defaultX = dims.shape === 'circle' ? dims.radius : dims.x / 2;
        let defaultY = dims.shape === 'circle' ? dims.radius : dims.y / 2;
        let defaultZ = currentSpaceType === 'estanque' ? parseFloat(document.getElementById('z_water').value) + 0.5 : 2.0;
        
        let defaultPower = 600;
        let defaultEff = 1.0;

        if (profile) {
            if (profile.elec_power) defaultPower = profile.elec_power;
            if (profile.efficiency) defaultEff = profile.efficiency;
        } else {
            const modelLower = model.toLowerCase();
            if (modelLower.includes('nexus') || modelLower.includes('fish')) defaultPower = 40;
            else if (modelLower.includes('asteria')) defaultPower = 150;
            else if (modelLower.includes('tempest')) defaultPower = 600;
        }

        let defaultRotX = 0;
        let defaultRotY = 0;
        let defaultRotZ = 0;

        const globalGroup = document.querySelector(`.global-lamp-group[data-xml="${model}"]`);
        if (globalGroup) {
            defaultPower = parseFloat(globalGroup.querySelector('.glob-power').value) || defaultPower;
            defaultZ = parseFloat(globalGroup.querySelector('.glob-z').value) || defaultZ;
        }

        const containerId = `group-${model.replace(/[^a-zA-Z0-9]/g, '-')}`;
        const groupContainer = document.getElementById(containerId);
        if (groupContainer) {
            const lastLamp = groupContainer.querySelector('.lamp-item:last-child');
            if (lastLamp) {
                defaultX = parseFloat(lastLamp.querySelector('.lamp-x').value) || defaultX;
                defaultY = parseFloat(lastLamp.querySelector('.lamp-y').value) || defaultY;
                defaultRotX = parseFloat(lastLamp.querySelector('.lamp-rot-x').value) || 0;
                defaultRotY = parseFloat(lastLamp.querySelector('.lamp-rot-y').value) || 0;
                defaultRotZ = parseFloat(lastLamp.querySelector('.lamp-rot-z').value) || 0;
            }
        }

        let initOpacity = globalGroup ? '0.5' : '1.0';

        createLampElement({
            xml: model, x: defaultX, y: defaultY, z: defaultZ, power: defaultPower,
            rot_x: defaultRotX, rot_y: defaultRotY, rot_z: defaultRotZ, opacity: initOpacity,
            efficiency: defaultEff 
        });
    } catch(e) { console.error(e); alert("Error al añadir lámpara."); }
}

function removeLamp(id) { 
    const el = document.getElementById(`lamp-${id}`); 
    if(el) { 
        const wrapper = el.parentElement;
        const group = wrapper.parentElement;
        el.remove(); 
        
        if (wrapper.children.length === 0) {
            group.remove();
        }
        
        updateLampNames();
        updateGlobalLampControls();
        updateScene();
        updateRunSummary();
    } 
}

function parseJsonSafe(id) {
    try {
        const el = document.getElementById(id);
        return el ? JSON.parse(el.value) : {};
    } catch(e) {
        return {};
    }
}

function selectedCheckboxValues(selector) {
    return Array.from(document.querySelectorAll(selector + ':checked')).map(el => el.value);
}

function parseNumberListInput(id, fallback) {
    const el = document.getElementById(id);
    const raw = el ? el.value : '';
    const values = raw.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    return values.length ? values : fallback;
}

function getBioAnalysisConfig() {
    const larvalProfiles = selectedCheckboxValues('.bio-larval-profile');
    const fishProfiles = selectedCheckboxValues('.bio-fish-profile');
    return {
        enabled: Boolean(document.getElementById('bio_enabled')?.checked),
        scenario_id: document.getElementById('bio_scenario_id')?.value || 'escenario_actual',
        depth_min_m: parseFloat(document.getElementById('bio_depth_min')?.value) || 0.0,
        depth_max_m: parseFloat(document.getElementById('bio_depth_max')?.value) || 15.0,
        layer_height_m: parseFloat(document.getElementById('bio_layer_height')?.value) || 1.0,
        grid_dx_m: parseFloat(document.getElementById('bio_grid_dx')?.value) || 1.0,
        grid_dy_m: parseFloat(document.getElementById('bio_grid_dy')?.value) || 1.0,
        tally_step_m: parseFloat(document.getElementById('bio_tally_step')?.value) || 0.5,
        bands: {blue: [400, 500], green: [500, 600], red: [600, 700]},
        thresholds_W_m2: parseNumberListInput('bio_thresholds', [0.054, 0.54, 5.4, 8.7]),
        spectral_weights: {
            blue: parseFloat(document.getElementById('bio_weight_blue')?.value) || 0.0,
            green: parseFloat(document.getElementById('bio_weight_green')?.value) || 0.0,
            red: parseFloat(document.getElementById('bio_weight_red')?.value) || 0.0
        },
        larval_profiles: larvalProfiles.length ? larvalProfiles : ['surface_strong', 'surface_moderate', 'uniform_0_15'],
        fish_profiles: fishProfiles.length ? fishProfiles : ['day_surface_feeding', 'day_distributed', 'night_lamp_centered', 'uniform_0_15'],
        fish_sigma_m: parseFloat(document.getElementById('bio_fish_sigma')?.value) || 2.0,
        normalize_against: document.getElementById('bio_normalize_against')?.value || '',
        grid_cells_csv: Boolean(document.getElementById('bio_grid_csv')?.checked)
    };
}

function applyBioAnalysisConfig(config) {
    if (!config) return;
    if (document.getElementById('bio_enabled')) document.getElementById('bio_enabled').checked = Boolean(config.enabled);
    if (document.getElementById('bio_scenario_id')) document.getElementById('bio_scenario_id').value = config.scenario_id || 'escenario_actual';
    if (config.depth_min_m !== undefined) document.getElementById('bio_depth_min').value = config.depth_min_m;
    if (config.depth_max_m !== undefined) document.getElementById('bio_depth_max').value = config.depth_max_m;
    if (config.layer_height_m !== undefined) document.getElementById('bio_layer_height').value = config.layer_height_m;
    if (config.grid_dx_m !== undefined) document.getElementById('bio_grid_dx').value = config.grid_dx_m;
    if (config.grid_dy_m !== undefined) document.getElementById('bio_grid_dy').value = config.grid_dy_m;
    if (config.tally_step_m !== undefined) document.getElementById('bio_tally_step').value = config.tally_step_m;
    if (config.thresholds_W_m2) document.getElementById('bio_thresholds').value = config.thresholds_W_m2.join(', ');
    if (config.spectral_weights) {
        if (config.spectral_weights.blue !== undefined) document.getElementById('bio_weight_blue').value = config.spectral_weights.blue;
        if (config.spectral_weights.green !== undefined) document.getElementById('bio_weight_green').value = config.spectral_weights.green;
        if (config.spectral_weights.red !== undefined) document.getElementById('bio_weight_red').value = config.spectral_weights.red;
    }
    document.querySelectorAll('.bio-larval-profile').forEach(el => {
        el.checked = !config.larval_profiles || config.larval_profiles.includes(el.value);
    });
    document.querySelectorAll('.bio-fish-profile').forEach(el => {
        el.checked = !config.fish_profiles || config.fish_profiles.includes(el.value);
    });
    if (config.fish_sigma_m !== undefined) document.getElementById('bio_fish_sigma').value = config.fish_sigma_m;
    if (config.normalize_against !== undefined) document.getElementById('bio_normalize_against').value = config.normalize_against;
    if (config.grid_cells_csv !== undefined) document.getElementById('bio_grid_csv').checked = Boolean(config.grid_cells_csv);
}

function addBioScenarioFromCurrentConfig() {
    const payload = getPayload(false);
    if (!payload) return;
    const scenarioId = document.getElementById('bio_batch_scenario_id')?.value || payload.project_title || `scenario_${window.bioOpticalScenarios.length + 1}`;
    const lampType = document.getElementById('bio_batch_lamp_type')?.value || '';
    payload.bio_analysis = Object.assign({}, payload.bio_analysis || {}, {enabled: false});
    window.bioOpticalScenarios.push({scenario_id: scenarioId, lamp_type: lampType, config: payload});
    renderBioScenarioList();
    showStatusMessage("Escenario bio-óptico agregado");
}

function clearBioScenarios() {
    window.bioOpticalScenarios = [];
    renderBioScenarioList();
    showStatusMessage("Batch bio-óptico limpio");
}

function renderBioScenarioList() {
    const list = document.getElementById('bio_scenario_list');
    if (!list) return;
    if (!window.bioOpticalScenarios.length) {
        list.textContent = 'Sin escenarios guardados.';
        return;
    }
    list.innerHTML = window.bioOpticalScenarios.map((s, idx) => {
        const lamps = (s.config.lamps || []).map(l => l.xml).join(', ');
        return `<div class="scenario-row"><strong>${idx + 1}. ${s.scenario_id}</strong> · ${s.lamp_type || 'tipo n/d'}<br><span class="text-muted">${lamps}</span></div>`;
    }).join('');
}

function downloadTextFile(filename, text, mimeType) {
    const blob = new Blob([text], {type: mimeType || 'text/plain;charset=utf-8'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

function addBioCsvDownload(label, filename, csvText) {
    if (!csvText) return '';
    const key = `bio_csv_${Math.random().toString(36).slice(2)}`;
    window[key] = csvText;
    return `<button class="btn-download btn-download--bio" onclick="downloadTextFile('${filename}', window['${key}'], 'text/csv;charset=utf-8')">${label}</button>`;
}

function renderBioAnalysisResults(result, title) {
    const workspace = document.getElementById('results_dynamic_area');
    const dlContainer = document.getElementById('downloads_container');
    if (!workspace || !result) return;
    workspace.querySelectorAll('.bio-analysis-result').forEach(el => el.remove());
    const layerRows = result.layer_rows || [];
    const indexRows = (result.index_rows || []).filter(r => !r.relative_metric);
    const relativeRows = (result.index_rows || []).filter(r => r.relative_metric);
    let html = `<h4 class="result-block__title result-block__title--bio">${title || 'Análisis bio-óptico relativo'}</h4>`;
    if (result.scenario_ids && result.scenario_ids.length) {
        html += `<div class="hint">Escenarios procesados (${result.scenario_ids.length}): <strong>${result.scenario_ids.join(', ')}</strong></div>`;
    }
    html += `<div class="table-scroll"><table class="summary-table">
        <tr><th>Escenario</th><th>Capa (m)</th><th>Volumen (m³)</th><th>E total media</th><th>P90 total</th><th>Azul media</th><th>Verde media</th><th>Rojo media</th></tr>`;
    layerRows.slice(0, 40).forEach(row => {
        html += `<tr><td>${row.scenario_id}</td><td>${Number(row.layer_top_m).toFixed(1)}–${Number(row.layer_bottom_m).toFixed(1)}</td><td>${Number(row.volume_m3).toFixed(2)}</td><td>${Number(row.E_total_mean_W_m2).toExponential(3)}</td><td>${Number(row.E_total_p90_W_m2).toExponential(3)}</td><td>${Number(row.E_blue_mean_W_m2).toExponential(3)}</td><td>${Number(row.E_green_mean_W_m2).toExponential(3)}</td><td>${Number(row.E_red_mean_W_m2).toExponential(3)}</td></tr>`;
    });
    html += `</table></div>`;
    html += `<div class="table-scroll"><table class="summary-table">
        <tr><th>Escenario</th><th>C(z)</th><th>F(z)</th><th>IC</th><th>IE pez total</th><th>IE contacto total</th><th>IE contacto espectral</th></tr>`;
    indexRows.slice(0, 60).forEach(row => {
        html += `<tr><td>${row.scenario_id}</td><td>${row.larval_profile}</td><td>${row.fish_profile}</td><td>${Number(row.IC).toExponential(3)}</td><td>${Number(row.IE_pez_total).toExponential(3)}</td><td>${Number(row.IE_contacto_total).toExponential(3)}</td><td>${Number(row.IE_contacto_spectral).toExponential(3)}</td></tr>`;
    });
    html += `</table></div>`;
    if (relativeRows.length) {
        html += `<div class="table-scroll"><table class="summary-table">
            <tr><th>Escenario</th><th>Base</th><th>C(z)</th><th>F(z)</th><th>Métrica</th><th>Índice relativo</th></tr>`;
        relativeRows.slice(0, 80).forEach(row => {
            const value = row.relative_value === '' ? '-' : Number(row.relative_value).toFixed(4);
            html += `<tr><td>${row.scenario_id}</td><td>${row.normalization_base}</td><td>${row.larval_profile}</td><td>${row.fish_profile}</td><td>${row.relative_metric}</td><td>${value}</td></tr>`;
        });
        html += `</table></div>`;
    }
    if (result.notes && result.notes.length) {
        html += `<div class="note">${result.notes.map(n => `<div>${n}</div>`).join('')}</div>`;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'graph-wrapper result-graph bio-analysis-result';
    wrapper.style.width = '100%';
    wrapper.innerHTML = html;
    workspace.appendChild(wrapper);

    if (result.plots) {
        Object.keys(result.plots).forEach(key => {
            const div = document.createElement('div');
            div.className = 'graph-wrapper result-graph bio-analysis-result';
            div.style.width = '100%';
            div.innerHTML = `<h4 class="result-block__title result-block__title--bio">${key.replace(/_/g, ' ')}</h4><div class="img-center"><img src="data:image/png;base64,${result.plots[key]}"></div>`;
            workspace.appendChild(div);
        });
    }
    if (dlContainer) {
        const clean = (window.lastResults && window.lastResults.clean_title) || 'biooptico';
        const oldBioDownloads = document.getElementById('bio_downloads_block');
        if (oldBioDownloads) oldBioDownloads.remove();
        const bioDownloads = document.createElement('div');
        bioDownloads.id = 'bio_downloads_block';
        bioDownloads.innerHTML = `<div class="dl-group__title dl-group__title--bio">BIO-ÓPTICA</div>` +
            addBioCsvDownload('CSV parámetros de análisis', `${clean}_bio_parametros.csv`, result.analysis_parameters_csv) +
            addBioCsvDownload('CSV capas bio-ópticas', `${clean}_bio_capas.csv`, result.layer_summary_csv) +
            addBioCsvDownload('CSV índices relativos', `${clean}_bio_indices.csv`, result.biological_indices_csv) +
            (result.grid_cells_csv ? addBioCsvDownload('CSV celdas 3D', `${clean}_bio_celdas.csv`, result.grid_cells_csv) : '');
        dlContainer.appendChild(bioDownloads);
    }
}

function runBioOpticalBatch() {
    if (!window.bioOpticalScenarios.length) {
        alert("Agregue al menos un escenario completo al batch.");
        return;
    }
    const analysis = getBioAnalysisConfig();
    analysis.enabled = true;
    const btn = document.getElementById('btn_run');
    if (btn) { btn.innerHTML = "⏳ BIO-ÓPTICA..."; btn.disabled = true; }
    fetch('/api/run_biooptical_batch', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({analysis, scenarios: window.bioOpticalScenarios})
    })
    .then(r => r.json())
    .then(data => {
        if (btn) { btn.innerHTML = "▶ Simular"; btn.disabled = false; }
        if (data.status !== 'ok') {
            alert("Error en batch bio-óptico:\n" + (data.msg || 'Error desconocido'));
            return;
        }
        window.lastResults = {clean_title: 'biooptico_batch'};
        renderBioAnalysisResults(data.bio_analysis, 'Comparación bio-óptica de escenarios');
        showStatusMessage("Batch bio-óptico completado");
    })
    .catch(err => {
        if (btn) { btn.innerHTML = "▶ Simular"; btn.disabled = false; }
        console.error(err);
        alert("Error de conexión en batch bio-óptico:\n" + err.message);
    });
}

function getPayload(isCompareMode) {
    let depthsArray = document.getElementById('target_depths').value.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
    let compare_x = null, compare_y = null;

    if (isCompareMode) {
        const pt = document.getElementById('meas_point_selector').value;
        if (!pt) { alert("Seleccione un punto válido (X, Y)."); return null; }
        compare_x = parseFloat(pt.split(',')[0]); compare_y = parseFloat(pt.split(',')[1]);
        const pointMeas = window.measurements.filter(m => Math.abs(m.x - compare_x) < 0.1 && Math.abs(m.y - compare_y) < 0.1);
        const uniqueZ = [...new Set(pointMeas.map(m => m.z))];
        if (uniqueZ.length === 0) { alert("No hay profundidades para este punto."); return null; }
        depthsArray = uniqueZ;
    } else if (depthsArray.length === 0) { alert("Ingrese alturas a graficar."); return null; }

    let aporteStr = document.getElementById('aporte_puntos').value;
    let aporte_puntos = [];
    if (aporteStr.trim()) {
        let parts = aporteStr.split(';');
        parts.forEach(part => {
            let coords = part.split(',');
            if (coords.length === 3) {
                let x = parseFloat(coords[0]), y = parseFloat(coords[1]), z = parseFloat(coords[2]);
                if (!isNaN(x) && !isNaN(y) && !isNaN(z)) {
                    aporte_puntos.push({x, y, z});
                    if (!depthsArray.includes(z)) depthsArray.push(z); 
                }
            }
        });
    }
    depthsArray.sort((a,b) => currentSpaceType === 'estanque' ? b-a : a-b);

    const activeAerial = document.getElementById('toggle_aerial').checked;
    const activeSubmerged = document.getElementById('toggle_submerged').checked;
    const zInterface = parseFloat(document.getElementById('z_water').value) || 0;

    const lamps = [];
    document.querySelectorAll('.lamp-item').forEach(item => {
        let zVal = parseFloat(item.querySelector('.lamp-z').value) || 0;
        let pwrInputVal = parseFloat(item.querySelector('.lamp-power').value) || 0;
        let pwrVal = pwrInputVal;
        let effVal = parseFloat(item.querySelector('.lamp-eff').value) || 1.0;

        let isAerial = (currentSpaceType === 'estanque' && zVal > zInterface) || (currentSpaceType === 'jaula' && zVal < 0);
        if (isAerial && !activeAerial) pwrVal = 0;
        if (!isAerial && !activeSubmerged) pwrVal = 0;
        const lampZInput = item.querySelector('.lamp-z');
        const lampPowerInput = item.querySelector('.lamp-power');

        lamps.push({
            label: item.getAttribute('data-label'),
            xml: item.querySelector('.lamp-xml').value,
            type: isAerial ? 'aerial' : 'submerged',
            enabled: isAerial ? activeAerial : activeSubmerged,
            x: parseFloat(item.querySelector('.lamp-x').value) || 0, 
            y: parseFloat(item.querySelector('.lamp-y').value) || 0, 
            z: zVal,
            power: pwrVal,
            nominal_power: pwrInputVal,
            efficiency: effVal,
            manual_z: lampZInput ? lampZInput.getAttribute('data-manual') === 'true' : false,
            manual_power: lampPowerInput ? lampPowerInput.getAttribute('data-manual') === 'true' : false,
            rot_x: parseFloat(item.querySelector('.lamp-rot-x').value) || 0,
            rot_y: parseFloat(item.querySelector('.lamp-rot-y').value) || 0,
            rot_z: parseFloat(item.querySelector('.lamp-rot-z').value) || 0,
            cob: {
                length: parseFloat((item.querySelector('.lamp-cob-length') || {}).value) || 0,
                width: parseFloat((item.querySelector('.lamp-cob-width') || {}).value) || 0,
                shape: (item.querySelector('.lamp-cob-shape') || {}).value || 'rect'
            }
        });
    });
    if(lamps.length === 0) { alert("Agregue lámparas."); return null; }

    const spectrum_lamps = [];
    if (document.getElementById('plot_spectrum_initial').checked || document.getElementById('plot_spectrum_normalized').checked || document.getElementById('plot_env_optics').checked) {
        document.querySelectorAll('.spectrum-lamp-cb:checked').forEach(cb => spectrum_lamps.push(cb.value));
    }
    
    let roi = { type: document.getElementById('roi_type').value };
    if (roi.type === 'paralelepipedo') {
        roi.l = parseFloat(document.getElementById('roi_p_l').value) || 0;
        roi.w = parseFloat(document.getElementById('roi_p_w').value) || 0;
        roi.h = parseFloat(document.getElementById('roi_p_h').value) || 0;
        roi.cx = parseFloat(document.getElementById('roi_p_cx').value) || 0;
        roi.cy = parseFloat(document.getElementById('roi_p_cy').value) || 0;
        roi.cz = parseFloat(document.getElementById('roi_p_cz').value) || 0;
    } else if (roi.type === 'cilindro') {
        roi.r = parseFloat(document.getElementById('roi_c_r').value) || 0;
        roi.h = parseFloat(document.getElementById('roi_c_h').value) || 0;
        roi.cx = parseFloat(document.getElementById('roi_c_cx').value) || 0;
        roi.cy = parseFloat(document.getElementById('roi_c_cy').value) || 0;
        roi.cz = parseFloat(document.getElementById('roi_c_cz').value) || 0;
    }

    const dims = getSpaceDimensions();
    const optics_mode = document.getElementById('optics_mode').value;
    const mc_input_type = document.getElementById('mc_input_type').value;

    const isRasBardsnes = (optics_mode === 'scattering' && mc_input_type === 'ras_bardsnes');
    const rasTssEl = document.getElementById('ras_tss');
    const rasCdomEl = document.getElementById('ras_cdom');
    const tssValue = (isRasBardsnes && rasTssEl)
        ? (parseFloat(rasTssEl.value) || 15.0)
        : (parseFloat(document.getElementById('scat_tss').value) || 15.0);
    const cdomValue = (isRasBardsnes && rasCdomEl)
        ? (parseFloat(rasCdomEl.value) || 1.0)
        : (parseFloat(document.getElementById('scat_cdom').value) || 1.0);

    let kdList = [];
    if (optics_mode === 'kd_fijo') {
        kdList = document.getElementById('kd_list').value.split(',').map(v => parseFloat(v.trim())).filter(v => !isNaN(v));
        if (kdList.length === 0) kdList = [0.2];
    } else if (optics_mode === 'scattering') {
        if (mc_input_type === 'scalar') {
            const c_val = parseFloat(document.getElementById('scatter_c').value);
            kdList = isNaN(c_val) ? [0.5] : [c_val];
        } else {
            kdList = [0.0];
        }
    } else {
        kdList = [0.0];
    }

    return {
        project_title: document.getElementById('project_title').value || 'simulacion_evolux',
        lamp_type_toggles: {
            aerial: activeAerial,
            submerged: activeSubmerged
        },
        lamp_globals: getGlobalLampSettings(),
        scene3d: {
            render: get3DRenderSettings(),
            lamp_models: get3DModelSettings()
        },
        env: { 
            type: currentSpaceType, 
            shape: dims.shape,
            radio: dims.shape === 'circle' ? dims.radius : null, 
            x: dims.x, 
            y: dims.y, 
            z: parseFloat(document.getElementById('env_z').value) || 15.0,
            z_interface: parseFloat(document.getElementById('z_water').value) || 3.2,
            n1: parseFloat(document.getElementById('env_n1').value) || 1.0,
            n2: parseFloat(document.getElementById('env_n2').value) || 1.33
        },
        poly: {
            sides: parseInt(document.getElementById('poly_sides').value) || 0,
            dist: parseFloat(document.getElementById('poly_dist').value) || 0
        },
        roi: roi,
        optics_mode: optics_mode,
        secchi_model: (document.getElementById('secchi_model') || {}).value || 'lee2015',
        optics: {
            kd_fijo: kdList[0],
            kd_spectral: parseJsonSafe('kd_spectral_json'),
            atten_coef_type: (document.getElementById('atten_coef_type') || {}).value || 'c',
            mc_input_type: mc_input_type,
            tss: tssValue,
            cdom_a440: cdomValue,
            chl: parseFloat((document.getElementById('scat_chl') || {}).value) || 0.0,
            turbidity_ntu: (function(){ const v = parseFloat((document.getElementById('ras_turbidity_ntu') || {}).value); return isNaN(v) ? null : v; })(),
            ras_bstar_550: parseFloat((document.getElementById('ras_bstar550') || {}).value) || 0.31,
            ras_omega_p: parseFloat((document.getElementById('ras_omega_p') || {}).value) || 0.90,
            ras_eta_p: parseFloat((document.getElementById('ras_eta_p') || {}).value) || 1.8,
            ras_s_cdom: parseFloat((document.getElementById('ras_s_cdom') || {}).value) || 0.0141,
            c: parseFloat(document.getElementById('scatter_c').value) || 0.5,
            omega: parseFloat(document.getElementById('scatter_omega').value) || 0.8,
            g: parseFloat(document.getElementById('scatter_g').value) || 0.85,
            r_wall: parseFloat(document.getElementById('scatter_rwall').value) || 0.15,
            c_json: parseJsonSafe('scatter_c_json'),
            omega_json: parseJsonSafe('scatter_omega_json'),
            phase_function: (document.getElementById('phase_function') || {}).value || 'hg',
            bb_ratio: (function(){ const v = parseFloat((document.getElementById('bb_ratio') || {}).value); return isNaN(v) ? null : v; })(),
            ff_mu: parseFloat((document.getElementById('ff_mu') || {}).value) || 3.5,
            kd_closure: (document.getElementById('kd_closure') || {}).value || 'kirk',
            // Trazabilidad: modalidad de origen y procedencia por parámetro. No
            // interviene en el cálculo; permite reconstruir de dónde salió cada valor.
            param_source: (document.getElementById('bio_param_source') || {}).value || 'manual',
            provenance: JSON.parse(JSON.stringify(window.bioProvenance || {})),
            observations_path: window.opticalObservationsPath || null
        },
        kd_list: kdList,
        target_depths: depthsArray,
        rays: parseInt(document.getElementById('rays_count').value) || 50000,
        source_model: (document.getElementById('source_model') || {}).value || 'point',
        grid_bins: parseInt((document.getElementById('grid_bins') || {}).value) || 100,
        local_refine: (document.getElementById('local_refine') || {}).checked || false,
        local_window_m: parseFloat((document.getElementById('local_window_m') || {}).value) || 0.75,
        local_cell_m: parseFloat((document.getElementById('local_cell_m') || {}).value) || 0.01,
        draw_contour: document.getElementById('draw_contour').checked,
        contour_vals: (function(){
            const raw = (document.getElementById('contour_val').value || '0.016');
            const arr = raw.split(',').map(s => parseFloat(s.trim())).filter(v => !isNaN(v) && v > 0);
            return arr.length ? Array.from(new Set(arr)).sort((a,b)=>a-b) : [0.016];
        })(),
        contour_val: (function(){
            const raw = (document.getElementById('contour_val').value || '0.016');
            const arr = raw.split(',').map(s => parseFloat(s.trim())).filter(v => !isNaN(v) && v > 0);
            return arr.length ? Math.min(...arr) : 0.016;
        })(),
        color_scale_type: document.getElementById('color_scale_type').value,
        
        irradiance_type: document.getElementById('irradiance_type') ? document.getElementById('irradiance_type').value : 'scalar',
        mu_max: document.getElementById('mu_max') ? parseFloat(document.getElementById('mu_max').value) : 85.0,
        normalize_pineal: document.getElementById('normalize_pineal') ? document.getElementById('normalize_pineal').checked : true,
        
        plot_depth_profile: document.getElementById('plot_depth_profile').checked,
        profile_step: parseFloat(document.getElementById('profile_step').value) || 0.5,
        plot_depth_summary_table: document.getElementById('plot_depth_summary_table') ? document.getElementById('plot_depth_summary_table').checked : true,
        roi_plot_metrics: {
            plane_area: document.getElementById('roi_metric_plane_area') ? document.getElementById('roi_metric_plane_area').checked : true,
            plane_avg: document.getElementById('roi_metric_plane_avg') ? document.getElementById('roi_metric_plane_avg').checked : true,
            plane_min: document.getElementById('roi_metric_plane_min') ? document.getElementById('roi_metric_plane_min').checked : true,
            plane_max: document.getElementById('roi_metric_plane_max') ? document.getElementById('roi_metric_plane_max').checked : true,
            plane_minmax: (document.getElementById('roi_metric_plane_min') ? document.getElementById('roi_metric_plane_min').checked : true) &&
                          (document.getElementById('roi_metric_plane_max') ? document.getElementById('roi_metric_plane_max').checked : true),
            plane_peak: document.getElementById('roi_metric_plane_peak') ? document.getElementById('roi_metric_plane_peak').checked : true,
            plane_stress_lamps: document.getElementById('roi_metric_plane_stress_lamps') ? document.getElementById('roi_metric_plane_stress_lamps').checked : true,
            plane_threshold: document.getElementById('roi_metric_plane_threshold') ? document.getElementById('roi_metric_plane_threshold').checked : true,
            volume_avg: document.getElementById('roi_metric_volume_avg') ? document.getElementById('roi_metric_volume_avg').checked : true,
            volume_threshold: document.getElementById('roi_metric_volume_threshold') ? document.getElementById('roi_metric_volume_threshold').checked : true,
            volume_pct: document.getElementById('roi_metric_volume_pct') ? document.getElementById('roi_metric_volume_pct').checked : true
        },
        
        plot_env_optics: document.getElementById('plot_env_optics').checked,
        plot_light_quality: (document.getElementById('plot_light_quality') || {}).checked || false,
        plot_spectrum_initial: document.getElementById('plot_spectrum_initial').checked, 
        plot_spectrum_normalized: document.getElementById('plot_spectrum_normalized').checked, 
        spectrum_lamps: spectrum_lamps,
        spectrum_ranges: { 
            'blue': [parseFloat(document.getElementById('spec_b_min').value) || 400, parseFloat(document.getElementById('spec_b_max').value) || 499], 
            'green': [parseFloat(document.getElementById('spec_g_min').value) || 500, parseFloat(document.getElementById('spec_g_max').value) || 599], 
            'red': [parseFloat(document.getElementById('spec_r_min').value) || 600, parseFloat(document.getElementById('spec_r_max').value) || 750] 
        },
        compare_measurements: isCompareMode, compare_x: compare_x, compare_y: compare_y, measurements: isCompareMode ? window.measurements : [],
        aporte_puntos: aporte_puntos,
        aporte_puntos_raw: document.getElementById('aporte_puntos').value,
        lamps: lamps,
        bio_analysis: getBioAnalysisConfig(),
        summary_cols: { 
            lamps: document.getElementById('col_lamps').checked, 
            pos: document.getElementById('col_pos').checked, 
            power: document.getElementById('col_power').checked, 
            vol: document.getElementById('col_vol').checked 
        }
    };
}

function createReportBlob(payload, data) {
    data = data || window.lastResults || {};
    let txt = "=================================================\n";
    txt += "   REPORTE DE SIMULACION DE IRRADIANCIA EVOLUX\n";
    txt += "=================================================\n\n";
    txt += "PROYECTO: " + payload.project_title + "\n";
    txt += "FECHA: " + new Date().toLocaleString() + "\n";
    txt += "ENTORNO: " + (payload.env.type === 'estanque' ? 'Estanque' : 'Jaula') + "\n";
    txt += "FORMA: " + (payload.env.shape === 'circle' ? 'Cilíndrica' : 'Rectangular') + "\n";
    if (payload.env.shape === 'circle') txt += "RADIO: " + payload.env.radio + " m\n";
    else txt += "DIMENSIONES: " + payload.env.x + "x" + payload.env.y + " m\n";
    txt += "PROFUNDIDAD TOTAL Z: " + payload.env.z + " m\n";
    txt += "ALTURA DEL AGUA: " + payload.env.z_interface + " m\n";
    txt += "INDICE REF. MEDIO 1: " + payload.env.n1 + "\n";
    txt += "INDICE REF. MEDIO 2: " + payload.env.n2 + "\n";
    txt += "POLIGONO REF.: " + payload.poly.sides + " vertices, distancia " + payload.poly.dist + " m\n";
    txt += "ROI: " + JSON.stringify(payload.roi) + "\n";
    
    txt += "\n--- MODELADO DE IRRADIANCIA ---\n";
    txt += "METRICA: " + (payload.irradiance_type === 'pineal' ? 'Ponderada (Fisica Pineal)' : 'Escalar (Magnitud Bruta)') + "\n";
    if (payload.irradiance_type === 'pineal') {
        txt += "ANGULO LIMITE (u_max): " + payload.mu_max + " grados\n";
        txt += "NORMALIZACION A 1.0: " + (payload.normalize_pineal ? 'Activada' : 'Desactivada') + "\n";
    }
    
    txt += "\n--- OPTICA ---\n";
    txt += "MODO: " + payload.optics_mode + "\n";
    txt += "TIPO COEFICIENTE: " + (payload.optics.atten_coef_type || 'c') + "\n";
    if (payload.optics_mode === 'scattering') {
         txt += "INPUT: " + payload.optics.mc_input_type + "\n";
         if (payload.optics.mc_input_type === 'bio') {
             txt += "TSS: " + payload.optics.tss + " mg/L\n";
             txt += "CDOM a(440): " + payload.optics.cdom_a440 + " m^-1\n";
             txt += "Chl-a: " + payload.optics.chl + " mg/m^3\n";
         } else if (payload.optics.mc_input_type === 'scalar') {
             txt += "ATENUACION C: " + payload.optics.c + "\n";
             txt += "ALBEDO OMEGA: " + payload.optics.omega + "\n";
         } else {
             txt += "C JSON: " + JSON.stringify(payload.optics.c_json) + "\n";
             txt += "OMEGA JSON: " + JSON.stringify(payload.optics.omega_json) + "\n";
         }
         txt += "FASE g: " + payload.optics.g + "\n";
         txt += "ALBEDO PARED: " + payload.optics.r_wall + "\n";
    } else if (payload.optics_mode === 'kd_fijo') {
         txt += "KD FIJO: " + payload.optics.kd_fijo + "\n";
    } else if (payload.optics_mode === 'kd_espectral') {
         txt += "KD/C ESPECTRAL JSON: " + JSON.stringify(payload.optics.kd_spectral) + "\n";
    }
    
    txt += "\n--- LAMPARAS ---\n";
    txt += "SWITCH AEREAS: " + (payload.lamp_type_toggles && payload.lamp_type_toggles.aerial ? 'ON' : 'OFF') + "\n";
    txt += "SWITCH SUMERGIDAS: " + (payload.lamp_type_toggles && payload.lamp_type_toggles.submerged ? 'ON' : 'OFF') + "\n";
    txt += "PARAMETROS GLOBALES POR MODELO: " + JSON.stringify(payload.lamp_globals || {}) + "\n";
    let activas = 0;
    payload.lamps.forEach((l, i) => {
         if (l.power > 0) activas++;
         let label = l.label || `L${i+1}`;
         txt += `${label}: ${l.xml} | Tipo: ${l.type || '-'} | Estado tipo: ${l.enabled === false ? 'OFF' : 'ON'} | Pos(${l.x}, ${l.y}, ${l.z}) | Rot(${l.rot_x}, ${l.rot_y}, ${l.rot_z})\n`;
         txt += `       └─ Pwr Nominal: ${l.nominal_power !== undefined ? l.nominal_power : l.power}W | Pwr Efectiva: ${l.power}W | Eficiencia WPE: ${(l.efficiency*100).toFixed(1)}% | Pwr Radiante efectiva (Φe): ${(l.power*l.efficiency).toFixed(2)}W\n`;
         txt += `       └─ Override individual: potencia=${l.manual_power ? 'si' : 'no'}, altura=${l.manual_z ? 'si' : 'no'}\n`;
    });
    txt += "TOTAL ACTIVAS: " + activas + "\n";
    
    txt += "\n--- RAY TRACING ---\n";
    txt += "RAYOS POR LÁMPARA: " + payload.rays + "\n";
    txt += "PROFUNDIDADES OBJETIVO: " + payload.target_depths.join(', ') + "\n";
    txt += "ISOCURVA: " + (payload.draw_contour ? 'activada' : 'desactivada') + " >= " + payload.contour_val + " W/m^2\n";
    txt += "ESCALA COLOR: " + payload.color_scale_type + "\n";
    txt += "GRAFICOS ACTIVOS: perfil=" + payload.plot_depth_profile + ", tabla_z=" + payload.plot_depth_summary_table + ", medio=" + payload.plot_env_optics + ", espectro_inicial=" + payload.plot_spectrum_initial + ", color_shift=" + payload.plot_spectrum_normalized + "\n";
    txt += "\n--- VISUALIZACION 3D ---\n";
    txt += "RENDER: " + JSON.stringify(payload.scene3d ? payload.scene3d.render : {}) + "\n";
    txt += "MODELOS FISICOS: " + JSON.stringify(payload.scene3d ? payload.scene3d.lamp_models : {}) + "\n";

    const opticalDiag = getOpticalDiagnostics(data);
    if (opticalDiag) {
        txt += "\n--- DIAGNOSTICO IOP/AOP ---\n";
        txt += "FUENTE INFERENCIA: " + (opticalDiag.inferred_from || '-') + "\n";
        txt += "TRANSPORTE: " + (opticalDiag.transport_label || '-') + "\n";
        txt += "FASE: " + (opticalDiag.phase_function || '-') + " | g=" + opticalDiag.g + " | bb/b=" + opticalDiag.bb_ratio + "\n";
        txt += "CIERRE Kd ACTIVO: " + (opticalDiag.kd_closure || '-') + "\n";
        txt += "lambda_nm,a,b,c,omega0,bb,Kd_kirk,Kd_lee2005,Kd_activo\n";
        const nDiag = (opticalDiag.wavelength_nm || []).length;
        for (let i = 0; i < nDiag; i++) {
            txt += [
                opticalDiag.wavelength_nm[i],
                opticalDiag.a_m_inv[i],
                opticalDiag.b_m_inv[i],
                opticalDiag.c_m_inv[i],
                opticalDiag.omega0[i],
                opticalDiag.bb_m_inv[i],
                opticalDiag.kd_kirk_m_inv[i],
                opticalDiag.kd_lee2005_m_inv[i],
                opticalDiag.kd_active_m_inv[i]
            ].join(',') + "\n";
        }
        txt += "NOTA: " + (opticalDiag.model_note || '') + "\n";
    }

    if (data.table_data && Array.isArray(data.table_data) && data.table_data.length > 0) {
        txt += "\n--- RESULTADOS RESUMEN ---\n";
        data.table_data.forEach((row, i) => {
            txt += `ESCENARIO ${i + 1}: ${row.kd}\n`;
            txt += `  Prom W/m2: ${Number(row.avg || 0).toFixed(6)} | Max: ${Number(row.max || 0).toFixed(6)} | Min: ${Number(row.min || 0).toFixed(6)}\n`;
            txt += `  Prom Lux: ${Number(row.avg_lux || 0).toFixed(3)} | Prom PPFD: ${Number(row.avg_ppfd || 0).toFixed(3)} | Flujo prom: ${Number(row.avg_flux_w || 0).toFixed(3)} W\n`;
            const resultThresholds = row.volume_thresholds_W_m2 || [];
            if (resultThresholds.length) {
                resultThresholds.forEach(threshold => {
                    const key = thresholdResultKey(threshold);
                    const volume = Number(row.volumes_ge_thresholds_m3?.[key] || 0);
                    const percentage = Number(row.volume_pcts_by_threshold?.[key] || 0);
                    txt += `  Vol E>=${threshold} W/m2: ${volume.toFixed(3)} m3 / ${percentage.toFixed(3)}%\n`;
                });
            } else {
                txt += `  Vol iluminado: ${Number(row.vol_ilum_m3 || 0).toFixed(3)} m3 / ${Number(row.vol_pct || 0).toFixed(3)}%\n`;
            }
            txt += `  Secchi eq.: ${row.secchi ? Number(row.secchi).toFixed(3) + ' m' : '-'}\n`;
        });
    }

    return new Blob([txt], {type: "text/plain;charset=utf-8"});
}

function getOpticalDiagnostics(data) {
    if (!data) return null;
    if (data.optical_diagnostics) return data.optical_diagnostics;
    if (data.results_by_kd) {
        const firstKey = Object.keys(data.results_by_kd)[0];
        if (firstKey && data.results_by_kd[firstKey].optical_diagnostics) {
            return data.results_by_kd[firstKey].optical_diagnostics;
        }
    }
    return null;
}

function fmtDiag(value, digits = 4) {
    const n = Number(value);
    if (!isFinite(n)) return '-';
    return n.toFixed(digits);
}

function renderOpticalDiagnosticsTable(data) {
    const diag = getOpticalDiagnostics(data);
    if (!diag || !diag.wavelength_nm || !diag.wavelength_nm.length) return '';

    let html = `<h4 class="result-block__title">Diagnóstico físico IOP/AOP</h4>
                <div class="hint">
                    Inferencia: <strong>${diag.inferred_from || '-'}</strong> ·
                    Transporte: <strong>${diag.transport_label || '-'}</strong> ·
                    Fase: <strong>${diag.phase_function || '-'}</strong> ·
                    g=<strong>${fmtDiag(diag.g, 3)}</strong> ·
                    b<sub>b</sub>/b=<strong>${fmtDiag(diag.bb_ratio, 4)}</strong> ·
                    cierre Kd=<strong>${diag.kd_closure || '-'}</strong>
                </div>
                <div class="table-scroll">
                <table class="summary-table">
                    <tr>
                        <th>λ (nm)</th><th>a</th><th>b</th><th>c</th><th>ω0</th>
                        <th>b<sub>b</sub></th><th>Kd Kirk</th><th>Kd Lee 2005</th><th>Kd activo</th>
                    </tr>`;

    for (let i = 0; i < diag.wavelength_nm.length; i++) {
        html += `<tr>
                    <td><strong>${fmtDiag(diag.wavelength_nm[i], 0)}</strong></td>
                    <td>${fmtDiag(diag.a_m_inv[i])}</td>
                    <td>${fmtDiag(diag.b_m_inv[i])}</td>
                    <td>${fmtDiag(diag.c_m_inv[i])}</td>
                    <td>${fmtDiag(diag.omega0[i])}</td>
                    <td>${fmtDiag(diag.bb_m_inv[i])}</td>
                    <td>${fmtDiag(diag.kd_kirk_m_inv[i])}</td>
                    <td>${fmtDiag(diag.kd_lee2005_m_inv[i])}</td>
                    <td><strong>${fmtDiag(diag.kd_active_m_inv[i])}</strong></td>
                 </tr>`;
    }

    html += `</table></div>
             <div class="hint">
                ${diag.model_note || ''}
             </div>`;
    return html;
}

function runSimulation(isCompareMode = false) {
    const payload = getPayload(isCompareMode);
    if (!payload) return;
    const btn = document.getElementById('btn_run');
    
    btn.innerHTML = "⏳ CALCULANDO..."; btn.disabled = true;
    setRunProgress('busy', 'Calculando…');

    currentAbortController = new AbortController();

    fetch('/api/run_simulation', { 
        method: 'POST', 
        headers: {'Content-Type': 'application/json'}, 
        body: JSON.stringify(payload),
        signal: currentAbortController.signal
    })
    .then(r => r.json())
    .then(data => {
        btn.innerHTML = "▶ Simular"; btn.disabled = false;
        if(data.status === 'ok') { 
            window.lastResults = data; 
            window.lastPayload = payload;
            try {
                renderResults(data, payload); 
                if (window.updateScene3D) window.updateScene3D();
                buildResultsNav();
                updateRunSummary();
                setRunProgress('done');
                showStatusMessage("Simulación completada con éxito"); 
            } catch (renderErr) {
                console.error(renderErr);
                setRunProgress('error', 'Error de renderizado');
                alert("Error en el renderizado de los gráficos:\n" + renderErr.name + ": " + renderErr.message);
            }
        } 
        else { setRunProgress('error', 'Error del servidor'); alert("Error en el Servidor:\n" + data.msg); }
    })
    .catch(e => { 
        setRunProgress('error');
        if(e.name === 'AbortError') {
            showStatusMessage("Simulación cancelada", "red");
        } else {
            console.error("Fetch Error:", e); 
            alert("Error de Conexión/JS en el Navegador:\n" + e.message); 
        }
        btn.innerHTML = "▶ Simular"; 
        btn.disabled = false; 
    });
}

function thresholdResultKey(value) {
    return String(Number(value));
}

function formatThreshold(value) {
    const number = Number(value);
    return Number.isFinite(number)
        ? number.toLocaleString('es-CL', {maximumSignificantDigits: 6})
        : String(value);
}

function renderResults(data, payload) {
    const workspace = document.getElementById('results_dynamic_area');
    const dlContainer = document.getElementById('downloads_container');
    
    if (!workspace || !dlContainer) {
        alert("Error Crítico: No se encontraron los contenedores HTML para dibujar los resultados. Asegúrate de haber copiado el archivo simulation.html completamente sin cortar el final.");
        throw new Error("Contenedores HTML faltantes.");
    }
    
    workspace.innerHTML = ''; dlContainer.innerHTML = '';

    if (data.kds && data.results_by_kd) {
        data.kds = data.kds.map(kd => {
            return Object.keys(data.results_by_kd).find(k => parseFloat(k) === parseFloat(kd)) || kd;
        });
    }
    
    if (data.depths && Array.isArray(data.depths)) {
        data.depths.forEach(depth => {
            const rowDiv = document.createElement('div');
            rowDiv.className = 'depth-group result-graph';
            
            let html = `<div class="kd-grid">`;
            
            if (data.kds && Array.isArray(data.kds)) {
                data.kds.forEach(kd => {
                    if (data.results_by_kd && data.results_by_kd[kd] && data.results_by_kd[kd].depths) {
                        const imgData = data.results_by_kd[kd].depths[depth];
                        let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                        let combinedTitle = currentSpaceType === 'estanque' ? `<div class="kd-card-title__main">ALTURA Z = ${depth}m</div> <span class="kd-card-title__sub">ESCENARIO: ${scenName}</span>` : `<div class="kd-card-title__main">PROFUNDIDAD Z = ${depth}m</div> <span class="kd-card-title__sub">ESCENARIO: ${scenName}</span>`;
                        
                        if(imgData && imgData.image) {
                            html += `<div class="kd-card">
                                        <div class="kd-card-title">${combinedTitle}</div>
                                        <img src="data:image/png;base64,${imgData.image}">
                                     </div>`;
                        }
                        if(imgData && imgData.hue_image) {
                            let aeTxt = (imgData.alpha_e !== null && imgData.alpha_e !== undefined) ? ` · α_E ${Number(imgData.alpha_e).toFixed(1)}°` : '';
                            html += `<div class="kd-card">
                                        <div class="kd-card-title"><div class="kd-card-title__main">CALIDAD DE LUZ · Z = ${depth}m</div><span class="kd-card-title__sub">${scenName}${aeTxt}</span></div>
                                        <img src="data:image/png;base64,${imgData.hue_image}">
                                     </div>`;
                        }
                    }
                });
            }
            html += `</div>`;
            rowDiv.innerHTML = html;
            workspace.appendChild(rowDiv);
        });
    }

    let htmlTablas = "";

    let hasAportes = false;
    if(data.kds) { data.kds.forEach(kd => { if(data.results_by_kd[kd] && data.results_by_kd[kd].aportes && data.results_by_kd[kd].aportes.length > 0) hasAportes = true; }); }

    if (hasAportes && data.lamps_names) {
        htmlTablas += `<h4 class="result-block__title">Aporte lumínico en puntos específicos</h4>
                       <div class="table-scroll">
                       <table class="summary-table">
                       <tr><th>PUNTO (X,Y,Z)</th><th>PARÁMETROS ÓPTICOS</th><th>TOTAL (W/m²)</th><th>LÁMPARA</th><th>APORTE (W/m² | %)</th></tr>`;
        data.kds.forEach(kd => {
            if(data.results_by_kd[kd] && data.results_by_kd[kd].aportes) {
                data.results_by_kd[kd].aportes.forEach(ap => {
                    let numLamps = ap.lamps.length;
                    let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                    ap.lamps.forEach((l, idx) => {
                        htmlTablas += `<tr>`;
                        if (idx === 0) {
                            htmlTablas += `<td rowspan="${numLamps}"><strong>${ap.x}, ${ap.y}, ${ap.z}</strong></td>
                                           <td rowspan="${numLamps}">${scenName}</td>
                                           <td rowspan="${numLamps}"><strong>${ap.total.toFixed(3)}</strong></td>`;
                        }
                        let lampName = data.lamps_names[l.lamp_idx] || `Lámpara ${l.lamp_idx + 1}`;
                        let lampConfig = payload.lamps[l.lamp_idx];
                        let label = lampConfig && lampConfig.label ? lampConfig.label : `L${l.lamp_idx + 1}`;
                        htmlTablas += `<td>${label}: ${lampName}</td>
                                       <td>${l.val.toFixed(3)} <strong class="num--optics">(${l.pct.toFixed(1)}%)</strong></td>
                                       </tr>`;
                    });
                });
            }
        });
        htmlTablas += `</table></div>`;
    }

    let numLamps = payload.lamps.length;
    let summaryCols = payload.summary_cols;
    const summaryVolumeThresholds = Array.from(new Set(
        (data.table_data || []).flatMap(row => row.volume_thresholds_W_m2 || [])
            .concat(data.contour_vals || payload.contour_vals || [])
            .map(Number)
            .filter(value => Number.isFinite(value) && value > 0)
    )).sort((a, b) => a - b);
    if (!summaryVolumeThresholds.length) summaryVolumeThresholds.push(Number(payload.contour_val || 0.016));
    const showVolumeColumns = summaryCols.vol !== false;
    const headerRowspan = showVolumeColumns ? 2 : 1;
    
    htmlTablas += `<h4 class="result-block__title">Resumen volumétrico de escenarios</h4>
                   <div class="table-scroll">
                   <table class="summary-table">
                   <tr><th rowspan="${headerRowspan}">PARÁMETROS ÓPTICOS</th><th rowspan="${headerRowspan}">DISCO SECCHI EQ.</th><th rowspan="${headerRowspan}">FLUJO TOTAL (W)</th><th rowspan="${headerRowspan}">PROM (W/m²)</th><th rowspan="${headerRowspan}">PROM (Lux)</th><th rowspan="${headerRowspan}">PROM (μmol)</th><th rowspan="${headerRowspan}">MÁX (W/m²)</th><th rowspan="${headerRowspan}">MÍN (W/m²)</th>`;
    if (showVolumeColumns) {
        htmlTablas += `<th colspan="${summaryVolumeThresholds.length}">VOLUMEN COMBINADO · ROI</th>`;
        htmlTablas += `<th colspan="${summaryVolumeThresholds.length}">VOLUMEN POR LÁMPARA · TALLY 3D</th>`;
    }
    if (summaryCols.lamps) htmlTablas += `<th rowspan="${headerRowspan}">LÁMPARA</th>`;
    if (summaryCols.pos) htmlTablas += `<th rowspan="${headerRowspan}">POSICIÓN (X,Y,Z)</th>`;
    if (summaryCols.power) htmlTablas += `<th rowspan="${headerRowspan}">POTENCIA ELÉCT. (W)</th>`;
    htmlTablas += `</tr>`;
    if (showVolumeColumns) {
        const combinedThresholdHeaders = summaryVolumeThresholds.map(threshold =>
            `<th>E ≥ ${formatThreshold(threshold)} W/m²<br><span class="th-sub">m³ / % del ROI</span></th>`
        ).join('');
        const lampThresholdHeaders = summaryVolumeThresholds.map(threshold =>
            `<th>E ≥ ${formatThreshold(threshold)} W/m²<br><span class="th-sub">m³ / % dominio 3D</span></th>`
        ).join('');
        htmlTablas += `<tr>${combinedThresholdHeaders}${lampThresholdHeaders}</tr>`;
    }

    if (data.table_data && Array.isArray(data.table_data)) {
        data.table_data.forEach(row => {
            let r_avg_flux = row.avg_flux_w !== undefined ? row.avg_flux_w.toFixed(2) : "0.00";
            let r_avg = row.avg !== undefined ? row.avg.toFixed(3) : "0.000";
            let r_avg_lux = row.avg_lux !== undefined ? row.avg_lux.toFixed(1) : "0.0";
            let r_avg_ppfd = row.avg_ppfd !== undefined ? row.avg_ppfd.toFixed(2) : "0.00";
            let r_max = row.max !== undefined ? row.max.toFixed(3) : "0.000";
            let r_min = row.min !== undefined ? row.min.toFixed(3) : "0.000";
            let r_secchi = row.secchi !== undefined && row.secchi > 0 ? row.secchi.toFixed(2) + 'm' : "-";
            let secModelLbl = secchiModelLabel(row.secchi_model);
            let secPreisTxt = row.secchi_preisendorfer > 0 ? row.secchi_preisendorfer.toFixed(2) + ' m' : '-';
            let secLeeTxt = row.secchi_lee2015 > 0 ? row.secchi_lee2015.toFixed(2) + ' m' : '-';
            let secPooleTxt = row.secchi_poole_atkins > 0 ? row.secchi_poole_atkins.toFixed(2) + ' m' : '-';
            let secTitle = `Modelo activo: ${secModelLbl}&#10;Preisendorfer (c+Kd): ${secPreisTxt}&#10;Poole–Atkins (1,7/Kd): ${secPooleTxt}&#10;Lee et al. 2015 (Kd mín.): ${secLeeTxt}`;

            let rawKd = row.kd.split(' ')[0];
            let scenName = data.scenario_names?.[rawKd] || data.scenario_names?.default || row.kd;

            payload.lamps.forEach((lamp, idx) => {
                htmlTablas += `<tr>`;
                if (idx === 0) {
                    htmlTablas += `<td rowspan="${numLamps}"><strong>${scenName}</strong></td>
                                    <td rowspan="${numLamps}" title="${secTitle}"><strong class="num--optics">${r_secchi}</strong><br><span class="th-sub">${secModelLbl}</span></td>
                                    <td rowspan="${numLamps}" class="num--flux">${r_avg_flux}</td>
                                    <td rowspan="${numLamps}">${r_avg}</td>
                                    <td rowspan="${numLamps}" class="num--lux">${r_avg_lux}</td>
                                    <td rowspan="${numLamps}" class="num--ppfd">${r_avg_ppfd}</td>
                                    <td rowspan="${numLamps}">${r_max}</td>
                                    <td rowspan="${numLamps}">${r_min}</td>`;
                    if (showVolumeColumns) {
                        summaryVolumeThresholds.forEach((threshold, thresholdIndex) => {
                            const key = thresholdResultKey(threshold);
                            const volumeValue = row.volumes_ge_thresholds_m3?.[key];
                            const percentageValue = row.volume_pcts_by_threshold?.[key];
                            const fallbackVolume = thresholdIndex === 0 ? Number(row.vol_ilum_m3 || 0) : 0;
                            const fallbackPercentage = thresholdIndex === 0 ? Number(row.vol_pct || 0) : 0;
                            const volume = Number(volumeValue === undefined ? fallbackVolume : volumeValue);
                            const percentage = Number(percentageValue === undefined ? fallbackPercentage : percentageValue);
                            htmlTablas += `<td rowspan="${numLamps}" class="nowrap"><strong>${volume.toFixed(2)} m³</strong><br><span class="num--optics">${percentage.toFixed(2)}%</span></td>`;
                        });
                    }
                }
                if (showVolumeColumns) {
                    const lampVolumeStats = (row.lamp_volume_stats || []).find(item => Number(item.lamp_index) === idx);
                    summaryVolumeThresholds.forEach(threshold => {
                        const key = thresholdResultKey(threshold);
                        const lampVolume = lampVolumeStats?.volumes_m3?.[key];
                        const lampPercentage = lampVolumeStats?.volume_pcts?.[key];
                        htmlTablas += lampVolume === undefined
                            ? `<td class="nowrap text-muted">—</td>`
                            : `<td class="nowrap"><strong>${Number(lampVolume).toFixed(2)} m³</strong><br><span class="num--vol">${Number(lampPercentage || 0).toFixed(2)}%</span></td>`;
                    });
                }
                if (summaryCols.lamps) {
                    let lName = lamp.xml.replace('.xml', '').replace('.ies', '');
                    let label = lamp.label || `L${idx + 1}`;
                    htmlTablas += `<td>${label}: ${lName}</td>`;
                }
                if (summaryCols.pos) {
                    htmlTablas += `<td>(${lamp.x}, ${lamp.y}, ${lamp.z})</td>`;
                }
                if (summaryCols.power) {
                    htmlTablas += `<td>${lamp.power}</td>`;
                }
                htmlTablas += `</tr>`;
            });
        });
    }
    htmlTablas += `</table></div>`;

    const tablesWrapper = document.createElement('div');
    tablesWrapper.className = 'graph-wrapper result-graph';
    tablesWrapper.style.width = "100%";
    tablesWrapper.innerHTML = htmlTablas;
    workspace.appendChild(tablesWrapper);

    const opticalDiagHtml = renderOpticalDiagnosticsTable(data);
    if (opticalDiagHtml) {
        const diagDiv = document.createElement('div');
        diagDiv.className = 'graph-wrapper result-graph';
        diagDiv.style.width = "100%";
        diagDiv.innerHTML = opticalDiagHtml;
        workspace.appendChild(diagDiv);
    }
    
    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].depth_table && data.results_by_kd[kd].depth_table.length > 0) {
                let scenName = data.scenario_names ? data.scenario_names[kd] : kd;
                let depthTableHtml = `<h4 class="result-block__title">Irradiancia por Profundidad - ${scenName}</h4>
                               <div class="table-scroll">
                               <table class="summary-table">
                               <tr>
                                   <th rowspan="2">Z (m)</th>
                                   <th rowspan="2">Flujo Total (W)</th>
                                   <th colspan="3">Promedio</th>
                                   <th colspan="3">Máximo</th>
                                   <th colspan="3">Mínimo</th>
                               </tr>
                               <tr>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                                   <th>W/m²</th><th>Lux</th><th>μmol/m²/s</th>
                               </tr>`;
                               
                data.results_by_kd[kd].depth_table.sort((a,b) => currentSpaceType === 'estanque' ? b.z - a.z : a.z - b.z).forEach(row => {
                    depthTableHtml += `<tr>
                                    <td><strong>${row.z}</strong></td>
                                    <td class="num--flux">${row.flux_w.toFixed(2)}</td>
                                    
                                    <td class="num--irr">${row.avg_w.toFixed(3)}</td>
                                    <td>${row.avg_lux.toFixed(1)}</td>
                                    <td class="num--ppfd">${row.avg_ppfd.toFixed(2)}</td>
                                    
                                    <td class="num--irr">${row.max_w.toFixed(3)}</td>
                                    <td>${row.max_lux.toFixed(1)}</td>
                                    <td class="num--ppfd">${row.max_ppfd.toFixed(2)}</td>
                                    
                                    <td class="num--irr">${row.min_w.toFixed(3)}</td>
                                    <td>${row.min_lux.toFixed(1)}</td>
                                    <td class="num--ppfd">${row.min_ppfd.toFixed(2)}</td>
                                  </tr>`;
                });
                depthTableHtml += `</table></div>`;
                
                const tableDiv = document.createElement('div');
                tableDiv.className = 'graph-wrapper result-graph';
                tableDiv.style.width = "100%";
                tableDiv.innerHTML = depthTableHtml;
                workspace.appendChild(tableDiv);
            }
        });
    }

    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].depth_profile_image) {
                const dpDiv = document.createElement('div');
                dpDiv.className = 'graph-wrapper result-graph';
                dpDiv.style.width = "100%";
                dpDiv.innerHTML = `<h4 class="result-block__title">PERFIL DE PROFUNDIDAD: ÁREA Y VOLUMEN</h4>
                                   <div class="img-center"><img src="data:image/png;base64,${data.results_by_kd[kd].depth_profile_image}"></div>`;
                workspace.appendChild(dpDiv);
            }
        });
    }

    if (data.kds && data.kds.length > 0) {
        let firstKd = data.kds[0];
        if (data.results_by_kd[firstKd] && data.results_by_kd[firstKd].comparison_image) {
            const compDiv = document.createElement('div');
            compDiv.className = 'graph-wrapper result-graph';
            compDiv.style.width = "100%";
            compDiv.innerHTML = `<h4 class="result-block__title">ATENUACIÓN: MEDICIÓN VS SIMULACIÓN</h4>
                                 <div class="img-center"><img src="data:image/png;base64,${data.results_by_kd[firstKd].comparison_image}"></div>`;
            workspace.appendChild(compDiv);
        }
    }
    
    if (data.kds && data.kds.length > 0) {
        data.kds.forEach(kd => {
            if (data.results_by_kd[kd] && data.results_by_kd[kd].env_optics_image) {
                const envDiv = document.createElement('div');
                envDiv.className = 'graph-wrapper result-graph';
                envDiv.style.width = "100%";
                envDiv.innerHTML = `<h4 class="result-block__title">CARACTERIZACIÓN ÓPTICA DEL MEDIO</h4>
                                     <div class="img-center"><img src="data:image/png;base64,${data.results_by_kd[kd].env_optics_image}"></div>`;
                workspace.appendChild(envDiv);
            }
        });
    }

    if (data.spectrums && typeof data.spectrums === 'object') {
        Object.keys(data.spectrums).forEach(key => {
            const specDiv = document.createElement('div');
            specDiv.className = 'graph-wrapper result-graph';
            specDiv.style.width = "100%";
            specDiv.innerHTML = `<h4 class="result-block__title">ANÁLISIS ESPECTRAL</h4>
                                 <div class="img-center"><img src="data:image/png;base64,${data.spectrums[key]}"></div>`;
            workspace.appendChild(specDiv);
        });
    }

    let dlHtml = `<div class="dl-group__title">EXPORTAR RESULTADOS</div>`;
    dlHtml += `<button class="btn-download" onclick="downloadCombined()" title="Descargar vista general">📄 DESCARGAR CONSOLIDADO</button>`;
    if (data.kds && Array.isArray(data.kds)) {
        dlHtml += `<div class="dl-group__title">MAPAS INDIVIDUALES</div>`;
        data.kds.forEach(kd => {
            const kdRes = data.results_by_kd && data.results_by_kd[kd];
            if (!kdRes || !kdRes.depths) return;
            Object.keys(kdRes.depths).forEach(depth => {
                if (!kdRes.depths[depth] || !kdRes.depths[depth].image) return;
                const label = currentSpaceType === 'estanque' ? `Altura ${depth}m` : `Prof. ${depth}m`;
                dlHtml += `<button class="btn-download btn-download--map" onclick="downloadSingleMap('${encodeURIComponent(kd)}', '${encodeURIComponent(depth)}')">🖼 ${label}</button>`;
            });
        });
    }
    dlHtml += `<button class="btn-download btn-download--zip" onclick="downloadAllZip()">⬇ DESCARGAR PAQUETE COMPLETO (ZIP)</button>`;
    dlHtml += `<div class="hint dl-footnote">Las descargas individuales y consolidadas guardan el gráfico junto a su TXT de parámetros. En navegadores sin selector de carpeta, se descarga un ZIP con ambos archivos.</div>`;
    
    dlContainer.innerHTML = dlHtml;
    if (data.bio_analysis) {
        renderBioAnalysisResults(data.bio_analysis, 'Análisis bio-óptico de la simulación actual');
    }
}

function base64PngToBlob(base64Img) {
    return fetch("data:image/png;base64," + base64Img).then(response => response.blob());
}

function textBlobToFileBlob(blob) {
    return blob;
}

async function writeBlobToFile(handle, blob) {
    const writable = await handle.createWritable();
    await writable.write(blob);
    await writable.close();
}

async function downloadZipPair(baseName, imageBase64, payload, data) {
    const zip = new JSZip();
    zip.file(`${baseName}.png`, imageBase64, {base64: true});
    zip.file(`${baseName}_parametros.txt`, createReportBlob(payload, data));
    const content = await zip.generateAsync({type: "blob"});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(content);
    a.download = `${baseName}.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function downloadImageWithReport(baseName, imageBase64, payload, data) {
    if (!imageBase64) return;
    payload = payload || window.lastPayload || getPayload(false);
    data = data || window.lastResults;
    if (!payload || !data) return;

    try {
        if (window.showDirectoryPicker) {
            const dirHandle = await window.showDirectoryPicker({
                id: 'export_images',
                mode: 'readwrite',
                startIn: 'downloads'
            });
            const imgHandle = await dirHandle.getFileHandle(`${baseName}.png`, {create: true});
            await writeBlobToFile(imgHandle, await base64PngToBlob(imageBase64));

            const txtHandle = await dirHandle.getFileHandle(`${baseName}_parametros.txt`, {create: true});
            await writeBlobToFile(txtHandle, textBlobToFileBlob(createReportBlob(payload, data)));
            showStatusMessage("Gráfico y parámetros guardados");
            return;
        }

        throw new Error("Directory picker no soportado");
    } catch (e) {
        if (e && e.name === 'AbortError') return;
        await downloadZipPair(baseName, imageBase64, payload, data);
        showStatusMessage("ZIP con gráfico y parámetros descargado");
    }
}

function downloadSingleMap(kdEncoded, depthEncoded) {
    if(!window.lastResults || !window.lastResults.results_by_kd) return;
    const kd = decodeURIComponent(kdEncoded);
    const depth = decodeURIComponent(depthEncoded);
    const kdRes = window.lastResults.results_by_kd[kd];
    if (!kdRes || !kdRes.depths || !kdRes.depths[depth] || !kdRes.depths[depth].image) return;

    const cleanTitle = window.lastResults.clean_title;
    const suffix = window.lastResults.file_suffixes[kd] || kd;
    const dClean = String(depth).replace('.', '_').replace(',', '_');
    downloadImageWithReport(`${cleanTitle}_z${dClean}_${suffix}`, kdRes.depths[depth].image, window.lastPayload, window.lastResults);
}

async function downloadCombined() {
    if(!window.lastResults || !window.lastResults.kds || window.lastResults.kds.length === 0) return;
    const kd = window.lastResults.kds[0];
    const img = window.lastResults.results_by_kd[kd].combined_image;
    if(img) {
        const cleanTitle = window.lastResults.clean_title;
        const suffix = window.lastResults.file_suffixes[kd];
        await downloadImageWithReport(`${cleanTitle}_consolidado_${suffix}`, img, window.lastPayload, window.lastResults);
    }
}

async function downloadAllZip() {
    if(!window.lastResults || !window.lastResults.results_by_kd) return;
    const cleanTitle = window.lastResults.clean_title;
    showStatusMessage("Generando archivo ZIP...", "white");
    
    try {
        const zip = new JSZip();
        
        window.lastResults.kds.forEach(kd => {
            const suffix = window.lastResults.file_suffixes[kd];
            const depths = window.lastResults.results_by_kd[kd].depths;
            if (depths) {
                for (const d of Object.keys(depths)) {
                    const img = depths[d].image;
                    if(img) {
                        let dClean = d.replace('.', '_').replace(',', '_');
                        zip.file(`${cleanTitle}_z${dClean}_${suffix}.png`, img, {base64: true});
                    }
                }
            }
            
            if(window.lastResults.results_by_kd[kd].combined_image) {
                zip.file(`${cleanTitle}_consolidado_${suffix}.png`, window.lastResults.results_by_kd[kd].combined_image, {base64: true});
            }
            
            if(window.lastResults.results_by_kd[kd].depth_profile_image) {
                zip.file(`${cleanTitle}_perfil_vol_${suffix}.png`, window.lastResults.results_by_kd[kd].depth_profile_image, {base64: true});
            }
            
            if(window.lastResults.results_by_kd[kd].env_optics_image) {
                zip.file(`${cleanTitle}_med_optico_${suffix}.png`, window.lastResults.results_by_kd[kd].env_optics_image, {base64: true});
            }
        });

        if (window.lastResults.spectrums) {
            Object.keys(window.lastResults.spectrums).forEach(specKey => {
                let sClean = specKey.toLowerCase().replace(/[\s\.,\-\(\)]+/g, '_').replace(/_+/g, '_');
                zip.file(`${cleanTitle}_${sClean}.png`, window.lastResults.spectrums[specKey], {base64: true});
            });
        }

        const reportBlob = createReportBlob(window.lastPayload || getPayload(false), window.lastResults);
        zip.file(`${cleanTitle}_reporte.txt`, reportBlob);
        
        const content = await zip.generateAsync({type:"blob"});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(content);
        a.download = `${cleanTitle}_resultados.zip`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        
        showStatusMessage("Archivo ZIP descargado correctamente.");
        
    } catch (e) {
        console.error("Error al generar el ZIP:", e);
        alert("Ocurrió un error al intentar comprimir las imágenes. Por favor, revise la consola para más detalles.");
    }
}

async function saveConfiguration() {
    const payload = getPayload(false);
    if(!payload) return;
    
    let cleanTitle = payload.project_title.toLowerCase().replace(/[\s\.,\-]+/g, '_').replace(/_+/g, '_').replace(/^_|_$/g, '');
    if (!cleanTitle) cleanTitle = 'simulacion_evolux';
    
    const jsonString = JSON.stringify(payload, null, 4);

    try {
        if (window.showSaveFilePicker) {
            const handle = await window.showSaveFilePicker({
                id: 'config_files',
                suggestedName: `${cleanTitle}_config.json`,
                types: [{ description: 'Simulation Config File', accept: {'application/json': ['.json', '.confg']} }]
            });
            const writable = await handle.createWritable();
            await writable.write(jsonString);
            await writable.close();
            showStatusMessage("Configuración guardada");
        } else {
            let filename = prompt("Ingrese el nombre para el archivo:", `${cleanTitle}_config.json`);
            if (!filename) return; 
            if (!filename.endsWith('.json')) filename += '.json';
            const blob = new Blob([jsonString], { type: "application/json" });
            const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
            a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a);
            showStatusMessage("Configuración guardada");
        }
    } catch (err) {
        console.error(err);
    }
}

async function openConfigurationPicker() {
    if (!window.showOpenFilePicker) {
        document.getElementById('config_input').click();
        return;
    }

    try {
        const [handle] = await window.showOpenFilePicker({
            id: 'config_files',
            startIn: 'documents',
            multiple: false,
            types: [{ description: 'Simulation Config File', accept: {'application/json': ['.json', '.confg']} }]
        });
        const file = await handle.getFile();
        loadConfiguration({target: {files: [file], value: ''}});
    } catch (err) {
        if (err && err.name !== 'AbortError') console.error(err);
    }
}

function loadConfiguration(event) {
    const file = event.target.files[0]; if (!file) return;
    const reader = new FileReader();
    reader.onload = function(e) {
        try {
            const config = JSON.parse(e.target.result);
            
            if(config.project_title !== undefined) {
                document.getElementById('project_title').value = config.project_title;
            }

            if(config.lamp_type_toggles) {
                if (config.lamp_type_toggles.aerial !== undefined) {
                    document.getElementById('toggle_aerial').checked = Boolean(config.lamp_type_toggles.aerial);
                }
                if (config.lamp_type_toggles.submerged !== undefined) {
                    document.getElementById('toggle_submerged').checked = Boolean(config.lamp_type_toggles.submerged);
                }
            }

            if(config.env) {
                document.getElementById('mode-selector').value = config.env.type || 'estanque';
                currentSpaceType = config.env.type || 'estanque';
                document.getElementById('env_shape').value = config.env.shape || (config.env.type === 'estanque' ? 'circle' : 'rect');
                document.getElementById('env_radio').value = config.env.radio || 20;
                document.getElementById('env_x').value = config.env.x || 40;
                document.getElementById('env_y').value = config.env.y || 40;
                document.getElementById('z_water').value = config.env.z_interface || 3.2;
                document.getElementById('env_n1').value = config.env.n1 || 1.0;
                document.getElementById('env_n2').value = config.env.n2 || 1.33;
                document.getElementById('env_z').value = config.env.z || 15.0;
                
                if(currentSpaceType === 'estanque') {
                    setShown('env_z_container', false);
                    setShown('z_water_container', true);
                    setShown('env_n1_container', true);
                    document.getElementById('env_n2_label').innerHTML = '<strong>Índice de refracción 2</strong> <span class="normal-case">(agua)</span>';
                    setShown('wall_albedo_container', true);
                } else {
                    setShown('env_z_container', true);
                    document.getElementById('env_x').value = config.env.x || 40;
                    document.getElementById('env_y').value = config.env.y || 40;
                    document.getElementById('env_z').value = config.env.z || 15.0;
                    
                    setShown('z_water_container', false);
                    setShown('env_n1_container', false);
                    document.getElementById('env_n2_label').innerHTML = '<strong>Índice de refracción</strong> <span class="normal-case">(agua)</span>';
                    setShown('wall_albedo_container', false);
                }
                toggleShapePanel();
            }
            
            if(config.poly) {
                document.getElementById('poly_sides').value = config.poly.sides || 0;
                document.getElementById('poly_dist').value = config.poly.dist || 0;
            }
            
            if(config.roi) {
                document.getElementById('roi_type').value = config.roi.type || 'global';
                toggleRoiPanel();
                if(config.roi.type === 'paralelepipedo') {
                    document.getElementById('roi_p_l').value = config.roi.l || 10;
                    document.getElementById('roi_p_w').value = config.roi.w || 10;
                    document.getElementById('roi_p_h').value = config.roi.h || 5;
                    document.getElementById('roi_p_cx').value = config.roi.cx || 10;
                    document.getElementById('roi_p_cy').value = config.roi.cy || 10;
                    document.getElementById('roi_p_cz').value = config.roi.cz || 2.5;
                } else if(config.roi.type === 'cilindro') {
                    document.getElementById('roi_c_r').value = config.roi.r || 5;
                    document.getElementById('roi_c_h').value = config.roi.h || 5;
                    document.getElementById('roi_c_cx').value = config.roi.cx || 10;
                    document.getElementById('roi_c_cy').value = config.roi.cy || 10;
                    document.getElementById('roi_c_cz').value = config.roi.cz || 2.5;
                }
            }

            if(config.optics_mode) {
                document.getElementById('optics_mode').value = config.optics_mode;
                toggleOpticsPanel();
            }

            if(config.secchi_model) {
                const smEl = document.getElementById('secchi_model');
                if (smEl) smEl.value = config.secchi_model;
            }

            if(config.optics) {
                if (config.optics.kd_spectral) document.getElementById('kd_spectral_json').value = JSON.stringify(config.optics.kd_spectral);
                if (config.optics.c) document.getElementById('scatter_c').value = config.optics.c;
                if (config.optics.omega) document.getElementById('scatter_omega').value = config.optics.omega;
                if (config.optics.g) document.getElementById('scatter_g').value = config.optics.g;
                if (config.optics.r_wall) document.getElementById('scatter_rwall').value = config.optics.r_wall;
                if (config.optics.phase_function && document.getElementById('phase_function')) document.getElementById('phase_function').value = config.optics.phase_function;
                if (config.optics.bb_ratio !== undefined && config.optics.bb_ratio !== null && document.getElementById('bb_ratio')) document.getElementById('bb_ratio').value = config.optics.bb_ratio;
                if (config.optics.ff_mu !== undefined && document.getElementById('ff_mu')) document.getElementById('ff_mu').value = config.optics.ff_mu;
                if (config.optics.kd_closure && document.getElementById('kd_closure')) document.getElementById('kd_closure').value = config.optics.kd_closure;
                togglePhaseParams();

                if (config.optics.mc_input_type) {
                    document.getElementById('mc_input_type').value = config.optics.mc_input_type;
                }
                if (config.optics.tss !== undefined) document.getElementById('scat_tss').value = config.optics.tss;
                if (config.optics.cdom_a440 !== undefined) document.getElementById('scat_cdom').value = config.optics.cdom_a440;
                if (config.optics.chl !== undefined && document.getElementById('scat_chl')) {
                    document.getElementById('scat_chl').value = config.optics.chl;
                }
                if (config.optics.atten_coef_type !== undefined && document.getElementById('atten_coef_type')) {
                    const tval = String(config.optics.atten_coef_type).toLowerCase();
                    document.getElementById('atten_coef_type').value = (tval === 'kd' ? 'Kd' : 'c');
                    updateAttenLabels();
                }

                toggleScatteringMode();

                if (config.optics.c_json) document.getElementById('scatter_c_json').value = JSON.stringify(config.optics.c_json);
                if (config.optics.omega_json) document.getElementById('scatter_omega_json').value = JSON.stringify(config.optics.omega_json);

                // Modalidad de origen y procedencia por parámetro.
                const sourceSel = document.getElementById('bio_param_source');
                if (sourceSel && config.optics.param_source) {
                    sourceSel.value = config.optics.param_source;
                    toggleBioParamSource();
                }
                if (config.optics.observations_path) {
                    window.opticalObservationsPath = config.optics.observations_path;
                    const csvStatus = document.getElementById('optical_csv_status');
                    if (csvStatus) csvStatus.textContent = 'Archivo de la configuración: ' + config.optics.observations_path;
                }
                if (config.optics.provenance) {
                    window.bioProvenance = Object.assign(
                        { tss: 'manual', cdom_a440: 'manual', chl: 'manual', detail: null },
                        config.optics.provenance
                    );
                    renderBioProvenance();
                }
            }

            if(config.target_depths) document.getElementById('target_depths').value = config.target_depths.join(', ');
            if(config.rays) document.getElementById('rays_count').value = config.rays;
            if(config.source_model && document.getElementById('source_model')) document.getElementById('source_model').value = config.source_model;
            if(config.grid_bins && document.getElementById('grid_bins')) { document.getElementById('grid_bins').value = config.grid_bins; }
            if(document.getElementById('local_refine')) document.getElementById('local_refine').checked = !!config.local_refine;
            if(config.local_window_m && document.getElementById('local_window_m')) document.getElementById('local_window_m').value = config.local_window_m;
            if(config.local_cell_m && document.getElementById('local_cell_m')) document.getElementById('local_cell_m').value = config.local_cell_m;
            toggleLocalRefine();
            updateGridCellHint();
            if(config.kd_list) document.getElementById('kd_list').value = config.kd_list.join(', ');
            if(config.aporte_puntos_raw !== undefined) document.getElementById('aporte_puntos').value = config.aporte_puntos_raw;

            if(config.draw_contour !== undefined) document.getElementById('draw_contour').checked = config.draw_contour;
            if(config.contour_vals && Array.isArray(config.contour_vals)) document.getElementById('contour_val').value = config.contour_vals.join(', ');
            else if(config.contour_val !== undefined) document.getElementById('contour_val').value = config.contour_val;
            if(config.color_scale_type !== undefined) document.getElementById('color_scale_type').value = config.color_scale_type;
            
            if(config.irradiance_type !== undefined && document.getElementById('irradiance_type')) {
                document.getElementById('irradiance_type').value = config.irradiance_type;
                if(config.mu_max !== undefined && document.getElementById('mu_max')) document.getElementById('mu_max').value = config.mu_max;
                if(config.normalize_pineal !== undefined && document.getElementById('normalize_pineal')) document.getElementById('normalize_pineal').checked = config.normalize_pineal;
                togglePinealParams();
            }
            
            if(config.plot_depth_profile !== undefined) document.getElementById('plot_depth_profile').checked = config.plot_depth_profile;
            if(config.profile_step !== undefined) document.getElementById('profile_step').value = config.profile_step;
            
            if(config.plot_depth_summary_table !== undefined && document.getElementById('plot_depth_summary_table')) {
                document.getElementById('plot_depth_summary_table').checked = config.plot_depth_summary_table;
            }
            if(config.roi_plot_metrics) {
                if(document.getElementById('roi_metric_plane_area')) document.getElementById('roi_metric_plane_area').checked = config.roi_plot_metrics.plane_area !== false;
                if(document.getElementById('roi_metric_plane_avg')) document.getElementById('roi_metric_plane_avg').checked = config.roi_plot_metrics.plane_avg !== false;
                if(document.getElementById('roi_metric_plane_min')) {
                    document.getElementById('roi_metric_plane_min').checked = config.roi_plot_metrics.plane_min !== undefined
                        ? config.roi_plot_metrics.plane_min !== false
                        : config.roi_plot_metrics.plane_minmax !== false;
                }
                if(document.getElementById('roi_metric_plane_max')) {
                    document.getElementById('roi_metric_plane_max').checked = config.roi_plot_metrics.plane_max !== undefined
                        ? config.roi_plot_metrics.plane_max !== false
                        : config.roi_plot_metrics.plane_minmax !== false;
                }
                if(document.getElementById('roi_metric_plane_peak')) document.getElementById('roi_metric_plane_peak').checked = config.roi_plot_metrics.plane_peak !== false;
                if(document.getElementById('roi_metric_plane_stress_lamps')) document.getElementById('roi_metric_plane_stress_lamps').checked = config.roi_plot_metrics.plane_stress_lamps !== false;
                if(document.getElementById('roi_metric_plane_threshold')) document.getElementById('roi_metric_plane_threshold').checked = config.roi_plot_metrics.plane_threshold !== false;
                if(document.getElementById('roi_metric_volume_avg')) document.getElementById('roi_metric_volume_avg').checked = config.roi_plot_metrics.volume_avg !== false;
                if(document.getElementById('roi_metric_volume_threshold')) document.getElementById('roi_metric_volume_threshold').checked = config.roi_plot_metrics.volume_threshold !== false;
                if(document.getElementById('roi_metric_volume_pct')) document.getElementById('roi_metric_volume_pct').checked = config.roi_plot_metrics.volume_pct !== false;
            }
            
            if(config.plot_env_optics !== undefined) document.getElementById('plot_env_optics').checked = config.plot_env_optics;
            if(config.plot_light_quality !== undefined && document.getElementById('plot_light_quality')) document.getElementById('plot_light_quality').checked = config.plot_light_quality;
            if(config.plot_spectrum_initial !== undefined) document.getElementById('plot_spectrum_initial').checked = config.plot_spectrum_initial;
            if(config.plot_spectrum_normalized !== undefined) document.getElementById('plot_spectrum_normalized').checked = config.plot_spectrum_normalized;

            toggleSpectrumPanel();

            if(config.spectrum_ranges) {
                document.getElementById('spec_b_min').value = config.spectrum_ranges.blue[0];
                document.getElementById('spec_b_max').value = config.spectrum_ranges.blue[1];
                document.getElementById('spec_g_min').value = config.spectrum_ranges.green[0];
                document.getElementById('spec_g_max').value = config.spectrum_ranges.green[1];
                document.getElementById('spec_r_min').value = config.spectrum_ranges.red[0];
                document.getElementById('spec_r_max').value = config.spectrum_ranges.red[1];
            }

            if(config.bio_analysis) {
                applyBioAnalysisConfig(config.bio_analysis);
            }

            if(config.summary_cols) {
                document.getElementById('col_lamps').checked = config.summary_cols.lamps;
                document.getElementById('col_pos').checked = config.summary_cols.pos;
                document.getElementById('col_power').checked = config.summary_cols.power;
                document.getElementById('col_vol').checked = config.summary_cols.vol;
            }
            
            const container = document.getElementById('lamp-list'); container.innerHTML = ''; lampCount = 0;
            if(config.lamps) {
                config.lamps.forEach(lamp => {
                    const globalSettings = config.lamp_globals && config.lamp_globals[lamp.xml] ? config.lamp_globals[lamp.xml] : null;
                    const globalZ = globalSettings && globalSettings.z !== undefined ? Number(globalSettings.z) : null;
                    const globalPower = globalSettings && globalSettings.power !== undefined ? Number(globalSettings.power) : null;
                    const lampZ = lamp.z !== undefined ? Number(lamp.z) : null;
                    const lampPower = lamp.nominal_power !== undefined ? Number(lamp.nominal_power) : (lamp.power !== undefined ? Number(lamp.power) : null);
                    const inferredManualZ = lamp.manual_z === true || (
                        lamp.manual_z === undefined && globalZ !== null && lampZ !== null && Math.abs(lampZ - globalZ) > 1e-9
                    );
                    const inferredManualPower = lamp.manual_power === true || (
                        lamp.manual_power === undefined && globalPower !== null && lampPower !== null && Math.abs(lampPower - globalPower) > 1e-9
                    );
                    createLampElement({
                        xml: lamp.xml, 
                        x: lamp.x, 
                        y: lamp.y, 
                        z: lamp.z,
                        power: lamp.nominal_power !== undefined ? lamp.nominal_power : (lamp.power || 600), 
                        efficiency: lamp.efficiency || 1.0,
                        rot_x: lamp.rot_x || 0,
                        rot_y: lamp.rot_y || 0,
                        rot_z: lamp.rot_z || 0,
                        cob: lamp.cob || null,
                        opacity: (inferredManualPower || inferredManualZ) ? '1.0' : '0.5',
                        manual_power: inferredManualPower,
                        manual_z: inferredManualZ
                    });
                });
            }
            updateGlobalLampControls();
            if(config.lamp_globals) {
                Object.keys(config.lamp_globals).forEach(xml => {
                    const group = document.querySelector(`.global-lamp-group[data-xml="${xml}"]`);
                    if (!group) return;
                    const settings = config.lamp_globals[xml];
                    if (settings.power !== undefined) group.querySelector('.glob-power').value = settings.power;
                    if (settings.z !== undefined) group.querySelector('.glob-z').value = settings.z;
                    if (settings.power !== undefined) applyGlobal(xml, 'power', settings.power);
                    if (settings.z !== undefined) applyGlobal(xml, 'z', settings.z);
                });
            }
            apply3DSceneSettings(config.scene3d);
            updateSecchi(); updateScene(); updateRunSummary();
            event.target.value = ''; showStatusMessage("Configuración cargada");
        } catch (err) { alert("Error al leer el archivo JSON."); }
    };
    reader.readAsText(file);
}

document.addEventListener("DOMContentLoaded", function() {
    // Densidad y última sección visitada.
    let density = 'comfortable';
    let section = 'geometry';
    let paramSource = 'manual';
    try {
        density = localStorage.getItem('evolux_density') || 'comfortable';
        section = localStorage.getItem('evolux_section') || 'geometry';
        paramSource = localStorage.getItem('evolux_bio_param_source') || 'manual';
    } catch (e) {}

    applyDensity(density);
    if (SECTION_META[section]) setActiveSection(section);

    const sourceSel = document.getElementById('bio_param_source');
    if (sourceSel) {
        sourceSel.value = paramSource;
        toggleBioParamSource();
    }
    renderBioProvenance();
    buildHelpNav();
    updateRunSummary();

    // Navegación por teclado entre secciones del rail.
    const rail = document.getElementById('section_rail');
    if (rail) {
        rail.addEventListener('keydown', event => {
            if (event.key !== 'ArrowDown' && event.key !== 'ArrowUp') return;
            const buttons = Array.from(rail.querySelectorAll('.rail__btn'));
            const idx = buttons.indexOf(document.activeElement);
            if (idx < 0) return;
            event.preventDefault();
            const next = buttons[(idx + (event.key === 'ArrowDown' ? 1 : -1) + buttons.length) % buttons.length];
            next.focus();
            setActiveSection(next.dataset.section);
        });
    }

    // Cualquier cambio de configuración refresca el resumen del panel derecho.
    ['optics_mode', 'mc_input_type', 'rays_count', 'grid_bins', 'irradiance_type',
     'source_model', 'roi_type', 'bio_enabled', 'mode-selector'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.addEventListener('change', updateRunSummary);
    });
});

/* =============================================================================
 *  PANEL DE CORRIDA (columna derecha)
 * ========================================================================== */

const OPTICS_MODE_LABELS = {
    kd_fijo: 'Atenuación fija',
    kd_espectral: 'Atenuación espectral',
    scattering: 'Monte Carlo dispersivo'
};

const MC_LABELS = {
    bio: 'Bio-óptica espectral',
    ras_bardsnes: 'RAS (Bårdsnes 2020)',
    scalar: 'Escalares globales',
    json: 'Espectral manual'
};

function updateRunSummary() {
    const box = document.getElementById('run_summary');
    if (!box) return;
    const val = id => { const el = document.getElementById(id); return el ? el.value : ''; };
    const opticsMode = val('optics_mode');
    const rows = [];

    rows.push(['Entorno', val('mode-selector') === 'jaula' ? 'Jaula' : 'Estanque']);
    rows.push(['Lámparas activas', String(document.querySelectorAll('.lamp-group-container').length || 0)]);
    rows.push(['Propagación', OPTICS_MODE_LABELS[opticsMode] || opticsMode || '—']);

    if (opticsMode === 'scattering') {
        const mc = val('mc_input_type');
        rows.push(['Método MC', MC_LABELS[mc] || mc]);
        if (mc === 'bio') {
            const src = val('bio_param_source');
            const label = src === 'satellite' ? 'Teledetección' : (src === 'csv' ? 'CSV local' : 'Manual');
            rows.push(['Origen parámetros', label]);
            const prov = window.bioProvenance || {};
            const uniq = [...new Set([prov.tss, prov.cdom_a440, prov.chl])]
                .map(k => (PROVENANCE_LABELS[k] || PROVENANCE_LABELS.manual).text);
            rows.push(['Procedencia', uniq.join(' · ')]);
            rows.push(['TSS · CDOM · Chl', `${val('scat_tss')} · ${val('scat_cdom')} · ${val('scat_chl')}`]);
        }
    } else if (opticsMode === 'kd_fijo') {
        rows.push([val('atten_coef_type') === 'Kd' ? 'Kd' : 'c', val('kd_list') || '—']);
    }

    rows.push(['Rayos', Number(val('rays_count') || 0).toLocaleString('es-CL')]);
    rows.push(['Malla', `${val('grid_bins')} nodos/eje`]);
    rows.push(['ROI', val('roi_type') || 'global']);
    const bioEl = document.getElementById('bio_enabled');
    if (bioEl && bioEl.checked) rows.push(['Bio-óptica Caligus', 'activa']);

    box.innerHTML = rows.map(([k, v]) =>
        `<div class="runsum__row"><span class="runsum__key">${k}</span><span class="runsum__val">${v}</span></div>`
    ).join('');
}

/** Índice sticky para saltar entre bloques de resultados. */
function buildResultsNav() {
    const nav = document.getElementById('results_nav');
    const area = document.getElementById('results_dynamic_area');
    if (!nav || !area) return;

    const SELECTOR = '.result-block__title, .result-card__head, .graph-title, .kd-card-title';
    const blocks = Array.from(area.children).filter(el => el.querySelector(SELECTOR) || el.matches(SELECTOR));
    if (!blocks.length) {
        nav.classList.remove('is-visible');
        nav.innerHTML = '';
        return;
    }

    let html = '<span class="results-nav__label">Ir a</span>';
    blocks.forEach((block, i) => {
        if (!block.id) block.id = 'result_block_' + i;
        const titleEl = block.querySelector('.result-block__title, .result-card__titlebox > span, .graph-title span, .graph-title, .kd-card-title');
        let label = (titleEl ? titleEl.textContent : 'Bloque ' + (i + 1)).trim();
        if (label.length > 34) label = label.slice(0, 32) + '…';
        html += `<button type="button" class="results-nav__link" onclick="document.getElementById('${block.id}').scrollIntoView({behavior:'smooth', block:'start'})">${label}</button>`;
    });
    nav.innerHTML = html;
    nav.classList.add('is-visible');
}
