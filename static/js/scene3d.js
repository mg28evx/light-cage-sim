import * as THREE from '../vendor/three/three.module.js';
import { OrbitControls } from '../vendor/three/OrbitControls.js';
import { TransformControls } from '../vendor/three/TransformControls.js';

const state = {
    initialized: false,
    renderer: null,
    scene: null,
    camera: null,
    controls: null,
    transformControls: null,
    raycaster: new THREE.Raycaster(),
    pointer: new THREE.Vector2(),
    root: null,
    selectable: [],
    selectedLamp: null,
    selectedLampItem: null,
    label: null,
    volumePanel: null,
    mode: '2d',
    frameRequested: false
};

window.scene3dModuleReady = true;

function num(id, fallback = 0) {
    const el = document.getElementById(id);
    const v = el ? parseFloat(el.value) : NaN;
    return Number.isFinite(v) ? v : fallback;
}

function checkbox(id, fallback = true) {
    const el = document.getElementById(id);
    return el ? el.checked : fallback;
}

function overlayValue(key, fallback) {
    const el = document.querySelector(`[data-scene3d-setting="${key}"]`);
    if (!el) return fallback;
    if (el.type === 'checkbox') return el.checked;
    const n = parseFloat(el.value);
    return Number.isFinite(n) ? n : fallback;
}

function overlaySelectValue(key, fallback) {
    const el = document.querySelector(`[data-scene3d-setting="${key}"]`);
    return el ? el.value : fallback;
}

function getRenderSettings() {
    return {
        showWater: overlayValue('showWater', checkbox('scene3d_show_water', true)),
        showWalls: overlayValue('showWalls', checkbox('scene3d_show_walls', true)),
        showGrid: overlayValue('showGrid', checkbox('scene3d_show_grid', true)),
        showAxes: overlayValue('showAxes', checkbox('scene3d_show_axes', true)),
        showBeams: overlayValue('showBeams', checkbox('scene3d_show_beams', true)),
        showLabels: overlayValue('showLabels', checkbox('scene3d_show_labels', true)),
        showRaytrace: overlayValue('showRaytrace', checkbox('scene3d_show_raytrace', true)),
        bioAttenuation: overlayValue('bioAttenuation', checkbox('scene3d_bio_attenuation', true)),
        showLightGlobes: checkbox('scene3d_show_light_globes', true),
        waterOpacity: Math.min(1, Math.max(0, overlayValue('waterOpacity', num('scene3d_water_opacity', 0.22)))),
        beamOpacity: Math.min(1, Math.max(0, overlayValue('beamOpacity', num('scene3d_beam_opacity', 0.28)))),
        lampScale: Math.max(0.05, overlayValue('lampScale', num('scene3d_lamp_scale', 1.0))),
        exposure: Math.max(0.2, overlayValue('exposure', num('scene3d_exposure', 1.0))),
        raytraceOpacity: Math.min(1, Math.max(0, overlayValue('raytraceOpacity', num('scene3d_raytrace_opacity', 0.72)))),
        lightGlobeThreshold: Math.max(1e-9, num('scene3d_light_globe_threshold', 0.1)),
        lightGlobeOpacity: Math.min(1, Math.max(0.05, num('scene3d_light_globe_opacity', 0.34))),
        preset: overlaySelectValue('preset', document.getElementById('scene3d_preset')?.value || 'technical')
    };
}

function getLampModelConfig(xml) {
    const overlayRow = document.querySelector(`.scene3d-overlay-model-row[data-xml="${xml}"]`);
    if (overlayRow) {
        return {
            shape: overlayRow.querySelector('[data-model-field="shape"]')?.value || 'cylinder',
            length: parseFloat(overlayRow.querySelector('[data-model-field="length"]')?.value) || 0.6,
            width: parseFloat(overlayRow.querySelector('[data-model-field="width"]')?.value) || 0.25,
            height: parseFloat(overlayRow.querySelector('[data-model-field="height"]')?.value) || 0.25
        };
    }
    const row = document.querySelector(`.scene3d-model-row[data-xml="${xml}"]`);
    if (!row) return {shape: 'cylinder', length: 0.6, width: 0.25, height: 0.25};
    return {
        shape: row.querySelector('.scene3d-model-shape')?.value || 'cylinder',
        length: parseFloat(row.querySelector('.scene3d-model-length')?.value) || 0.6,
        width: parseFloat(row.querySelector('.scene3d-model-width')?.value) || 0.25,
        height: parseFloat(row.querySelector('.scene3d-model-height')?.value) || 0.25
    };
}

function getVisualAttenuationCoefficient() {
    const mode = document.getElementById('optics_mode')?.value || 'kd_fijo';
    if (mode === 'kd_fijo') return Math.max(0, num('kd_list', 0.2));
    if (mode === 'kd_espectral') {
        try {
            const data = JSON.parse(document.getElementById('kd_spectral_json')?.value || '{}');
            const keys = Object.keys(data).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
            if (!keys.length) return 0.2;
            const target = 500;
            let best = keys[0];
            keys.forEach(k => { if (Math.abs(k - target) < Math.abs(best - target)) best = k; });
            return Math.max(0, parseFloat(data[best]) || 0.2);
        } catch {
            return 0.2;
        }
    }
    const mcType = document.getElementById('mc_input_type')?.value || 'scalar';
    if (mcType === 'scalar') return Math.max(0, num('scatter_c', 0.5));
    if (mcType === 'bio') {
        const wl = 500;
        const tss = Math.max(0, num('scat_tss', 15));
        const cdom = Math.max(0, num('scat_cdom', 1));
        const chl = Math.max(0, num('scat_chl', 0));
        const aw = 0.02;
        const bStar = 0.35;
        const aCdom = cdom * Math.exp(-0.015 * (wl - 440));
        const aChl = 0.015 * Math.pow(chl, 0.75);
        return aw + aCdom + bStar * tss + aChl;
    }
    try {
        const data = JSON.parse(document.getElementById('scatter_c_json')?.value || '{}');
        const keys = Object.keys(data).map(Number).filter(Number.isFinite).sort((a, b) => a - b);
        if (!keys.length) return 0.5;
        let best = keys[0];
        keys.forEach(k => { if (Math.abs(k - 500) < Math.abs(best - 500)) best = k; });
        return Math.max(0, parseFloat(data[best]) || 0.5);
    } catch {
        return 0.5;
    }
}

function currentEnvType() {
    const el = document.getElementById('mode-selector');
    return el ? el.value : 'estanque';
}

function getDims() {
    if (window.getSpaceDimensions) return window.getSpaceDimensions();
    const shape = document.getElementById('env_shape')?.value || 'circle';
    if (shape === 'circle') {
        const radius = num('env_radio', 20);
        return {x: radius * 2, y: radius * 2, shape, radius};
    }
    return {x: num('env_x', 40), y: num('env_y', 40), shape};
}

function simPointToThree(x, y, z, dims) {
    const envType = currentEnvType();
    const vertical = envType === 'jaula' ? -z : z;
    return new THREE.Vector3(x - dims.x / 2, vertical, y - dims.y / 2);
}

function threePointToSim(pos, dims) {
    const envType = currentEnvType();
    return {
        x: pos.x + dims.x / 2,
        y: pos.z + dims.y / 2,
        z: envType === 'jaula' ? -pos.y : pos.y
    };
}

function simVectorToThree(v) {
    return new THREE.Vector3(v.x, v.z, v.y);
}

function rotateSimVector(vec, rxDeg, ryDeg, rzDeg) {
    const rx = THREE.MathUtils.degToRad(rxDeg || 0);
    const ry = THREE.MathUtils.degToRad(ryDeg || 0);
    const rz = THREE.MathUtils.degToRad(rzDeg || 0);

    const cx = Math.cos(rx), sx = Math.sin(rx);
    const cy = Math.cos(ry), sy = Math.sin(ry);
    const cz = Math.cos(rz), sz = Math.sin(rz);

    const x1 = vec.x;
    const y1 = vec.y * cx - vec.z * sx;
    const z1 = vec.y * sx + vec.z * cx;

    const x2 = x1 * cy + z1 * sy;
    const y2 = y1;
    const z2 = -x1 * sy + z1 * cy;

    return new THREE.Vector3(
        x2 * cz - y2 * sz,
        x2 * sz + y2 * cz,
        z2
    );
}

function clearRoot() {
    if (!state.root) return;
    while (state.root.children.length) {
        const obj = state.root.children.pop();
        obj.traverse(child => {
            if (child.geometry) child.geometry.dispose();
            if (child.material) {
                const materials = Array.isArray(child.material) ? child.material : [child.material];
                materials.forEach(m => {
                    if (m.userData?.texture) m.userData.texture.dispose();
                    if (m.map) m.map.dispose();
                    m.dispose();
                });
            }
            if (child.userData?.texture) child.userData.texture.dispose();
        });
    }
}

function initScene() {
    if (state.initialized) return;
    const container = document.getElementById('scene3d_preview');
    if (!container) return;
    container.querySelectorAll('.scene3d-loading').forEach(el => el.remove());

    state.scene = new THREE.Scene();
    state.scene.background = new THREE.Color(0x101820);
    state.scene.fog = new THREE.Fog(0x101820, 45, 120);

    state.camera = new THREE.PerspectiveCamera(45, 1, 0.1, 1000);
    state.camera.position.set(24, 26, 28);

    state.renderer = new THREE.WebGLRenderer({antialias: true, alpha: false});
    state.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    state.renderer.shadowMap.enabled = true;
    state.renderer.outputColorSpace = THREE.SRGBColorSpace;
    state.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    container.appendChild(state.renderer.domElement);

    state.controls = new OrbitControls(state.camera, state.renderer.domElement);
    state.controls.enableDamping = true;
    state.controls.dampingFactor = 0.08;
    state.controls.target.set(0, 2.5, 0);

    const ambient = new THREE.HemisphereLight(0xb9e6ff, 0x202020, 2.2);
    state.scene.add(ambient);

    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(20, 35, 10);
    key.castShadow = true;
    state.scene.add(key);

    state.root = new THREE.Group();
    state.scene.add(state.root);

    state.label = document.createElement('div');
    state.label.className = 'scene3d-label';
    state.label.textContent = 'Vista 3D: recinto, agua, lámparas, eje óptico y lóbulo normalizado.';
    container.appendChild(state.label);

    state.volumePanel = document.createElement('div');
    state.volumePanel.className = 'scene3d-volume-panel';
    state.volumePanel.setAttribute('aria-live', 'polite');
    container.appendChild(state.volumePanel);
    ensureOverlayConfig(container);

    window.addEventListener('resize', resize);
    state.controls.addEventListener('change', requestRender);

    state.transformControls = new TransformControls(state.camera, state.renderer.domElement);
    state.transformControls.setSize(0.85);
    state.transformControls.addEventListener('dragging-changed', event => {
        state.controls.enabled = !event.value;
    });
    state.transformControls.addEventListener('objectChange', syncSelectedLampFrom3D);
    state.scene.add(state.transformControls);

    state.renderer.domElement.addEventListener('pointerdown', onPointerDown);
    state.initialized = true;
    resize();
    animate();
}

function ensureOverlayConfig(container) {
    if (document.getElementById('scene3d_config_panel')) return;

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'scene3d-config-button';
    btn.textContent = 'Config 3D';
    btn.onclick = () => {
        document.getElementById('scene3d_config_panel')?.classList.toggle('show');
    };
    container.appendChild(btn);

    const panel = document.createElement('div');
    panel.id = 'scene3d_config_panel';
    panel.className = 'scene3d-config-panel';
    panel.innerHTML = `
        <h5>Visualización 3D</h5>
        <div class="scene3d-overlay-checks">
            <label><input type="checkbox" data-scene3d-setting="showWater" checked> Agua</label>
            <label><input type="checkbox" data-scene3d-setting="showWalls" checked> Paredes</label>
            <label><input type="checkbox" data-scene3d-setting="showGrid" checked> Grilla</label>
            <label><input type="checkbox" data-scene3d-setting="showAxes" checked> Ejes</label>
            <label><input type="checkbox" data-scene3d-setting="showBeams" checked> Haces</label>
            <label><input type="checkbox" data-scene3d-setting="showLabels" checked> Etiquetas</label>
            <label><input type="checkbox" data-scene3d-setting="showRaytrace" checked> Planos RT</label>
            <label><input type="checkbox" data-scene3d-setting="bioAttenuation" checked> Medio bio-óptico</label>
        </div>
        <div class="scene3d-overlay-grid">
            <div><label>Opacidad agua</label><input type="number" data-scene3d-setting="waterOpacity" value="0.22" min="0" max="1" step="0.05"></div>
            <div><label>Opacidad haz</label><input type="number" data-scene3d-setting="beamOpacity" value="0.28" min="0" max="1" step="0.05"></div>
            <div><label>Escala lámpara</label><input type="number" data-scene3d-setting="lampScale" value="1.0" min="0.1" max="5" step="0.1"></div>
            <div><label>Exposición</label><input type="number" data-scene3d-setting="exposure" value="1.0" min="0.2" max="3" step="0.1"></div>
            <div><label>Opacidad RT</label><input type="number" data-scene3d-setting="raytraceOpacity" value="0.72" min="0" max="1" step="0.05"></div>
            <div><label>Preset</label><select data-scene3d-setting="preset">
                <option value="technical">Técnico</option>
                <option value="presentation">Presentación</option>
                <option value="turbid">Agua turbia</option>
                <option value="wireframe">Wireframe</option>
            </select></div>
        </div>
        <div style="display:flex; gap:6px; margin-bottom:10px;">
            <button type="button" class="btn-save" style="flex:1; font-size:11px !important;" data-action="translate">Mover</button>
            <button type="button" class="btn-save" style="flex:1; font-size:11px !important;" data-action="rotate">Rotar</button>
            <button type="button" class="btn-save" style="flex:1; font-size:11px !important;" data-action="clear">Soltar</button>
        </div>
        <h5>Modelos físicos</h5>
        <div id="scene3d_overlay_models" class="scene3d-overlay-models">
            <span style="font-size:11px; color:#777;">Agregue lámparas para configurar dimensiones.</span>
        </div>
    `;
    container.appendChild(panel);

    panel.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('input', () => {
            if (el.dataset.scene3dSetting === 'preset') applyOverlayPreset(el.value);
            window.updateScene3D();
        });
        el.addEventListener('change', () => {
            if (el.dataset.scene3dSetting === 'preset') applyOverlayPreset(el.value);
            window.updateScene3D();
        });
    });
    panel.querySelector('[data-action="translate"]').onclick = () => window.scene3dSetTransformMode('translate');
    panel.querySelector('[data-action="rotate"]').onclick = () => window.scene3dSetTransformMode('rotate');
    panel.querySelector('[data-action="clear"]').onclick = () => window.scene3dClearSelection();
}

function applyOverlayPreset(preset) {
    const presets = {
        technical: {showWater:true, showWalls:true, showGrid:true, showAxes:true, showBeams:true, showLabels:true, showRaytrace:true, bioAttenuation:true, waterOpacity:0.20, beamOpacity:0.24, lampScale:1.0, exposure:1.0, raytraceOpacity:0.72},
        presentation: {showWater:true, showWalls:true, showGrid:false, showAxes:false, showBeams:true, showLabels:true, showRaytrace:true, bioAttenuation:true, waterOpacity:0.32, beamOpacity:0.38, lampScale:1.2, exposure:1.25, raytraceOpacity:0.80},
        turbid: {showWater:true, showWalls:true, showGrid:false, showAxes:false, showBeams:true, showLabels:true, showRaytrace:true, bioAttenuation:true, waterOpacity:0.48, beamOpacity:0.52, lampScale:1.15, exposure:0.9, raytraceOpacity:0.85},
        wireframe: {showWater:false, showWalls:true, showGrid:true, showAxes:true, showBeams:false, showLabels:true, showRaytrace:false, bioAttenuation:false, waterOpacity:0.1, beamOpacity:0.1, lampScale:1.0, exposure:1.0, raytraceOpacity:0.5}
    };
    const cfg = presets[preset] || presets.technical;
    Object.entries(cfg).forEach(([key, value]) => {
        const el = document.querySelector(`[data-scene3d-setting="${key}"]`);
        if (!el) return;
        if (el.type === 'checkbox') el.checked = Boolean(value);
        else el.value = value;
    });
}

function inferOverlayModelDefaults(xml) {
    const name = String(xml || '').toLowerCase();
    if (name.includes('nexus') || name.includes('slim') || name.includes('fish')) {
        return {shape: 'box', length: 1.25, width: 0.16, height: 0.10};
    }
    if (name.includes('tempest') || name.includes('asteria')) {
        return {shape: 'cylinder', length: 0.55, width: 0.22, height: 0.22};
    }
    return {shape: 'cylinder', length: 0.60, width: 0.25, height: 0.25};
}

function updateOverlayModelControls() {
    const container = document.getElementById('scene3d_overlay_models');
    if (!container) return;

    const existing = {};
    container.querySelectorAll('.scene3d-overlay-model-row').forEach(row => {
        const xml = row.getAttribute('data-xml');
        existing[xml] = {
            shape: row.querySelector('[data-model-field="shape"]').value,
            length: row.querySelector('[data-model-field="length"]').value,
            width: row.querySelector('[data-model-field="width"]').value,
            height: row.querySelector('[data-model-field="height"]').value
        };
    });

    const uniqueLamps = new Set();
    document.querySelectorAll('.lamp-xml').forEach(input => uniqueLamps.add(input.value));
    if (!uniqueLamps.size) {
        container.innerHTML = '<span style="font-size:11px; color:#777;">Agregue lámparas para configurar dimensiones.</span>';
        return;
    }

    let html = '';
    uniqueLamps.forEach(xml => {
        const cfg = existing[xml] || inferOverlayModelDefaults(xml);
        html += `
            <div class="scene3d-overlay-model-row" data-xml="${xml}">
                <div class="scene3d-overlay-model-title">${xml}</div>
                <div class="scene3d-overlay-model-controls">
                    <div><label>Forma</label><select data-model-field="shape">
                        <option value="cylinder" ${cfg.shape === 'cylinder' ? 'selected' : ''}>Circular</option>
                        <option value="box" ${cfg.shape === 'box' ? 'selected' : ''}>Paralelep.</option>
                    </select></div>
                    <div><label>Largo</label><input type="number" data-model-field="length" value="${cfg.length}" min="0.01" step="0.05"></div>
                    <div><label>Ancho</label><input type="number" data-model-field="width" value="${cfg.width}" min="0.01" step="0.05"></div>
                    <div><label>Alto</label><input type="number" data-model-field="height" value="${cfg.height}" min="0.01" step="0.05"></div>
                </div>
            </div>`;
    });
    container.innerHTML = html;
    container.querySelectorAll('input, select').forEach(el => {
        el.addEventListener('input', () => window.updateScene3D());
        el.addEventListener('change', () => window.updateScene3D());
    });
}

function resize() {
    if (!state.initialized) return;
    const container = document.getElementById('scene3d_preview');
    if (!container) return;
    const width = Math.max(1, container.clientWidth);
    const height = Math.max(1, container.clientHeight);
    state.camera.aspect = width / height;
    state.camera.updateProjectionMatrix();
    state.renderer.setSize(width, height, false);
    requestRender();
}

function animate() {
    if (!state.initialized) return;
    requestAnimationFrame(animate);
    state.controls.update();
    if (state.mode === '3d' || state.frameRequested) {
        state.renderer.render(state.scene, state.camera);
        state.frameRequested = false;
    }
}

function requestRender() {
    state.frameRequested = true;
}

function makeFloorTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#2e3940';
    ctx.fillRect(0, 0, 256, 256);
    for (let i = 0; i < 900; i++) {
        const v = 50 + Math.random() * 55;
        ctx.fillStyle = `rgba(${v},${v + 8},${v + 10},${0.05 + Math.random() * 0.08})`;
        const x = Math.random() * 256;
        const y = Math.random() * 256;
        const r = 0.7 + Math.random() * 2.4;
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fill();
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(6, 6);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

function makeWaterTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 256;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#66d6ff';
    ctx.fillRect(0, 0, 256, 256);
    ctx.strokeStyle = 'rgba(255,255,255,0.28)';
    ctx.lineWidth = 2;
    for (let y = -40; y < 300; y += 18) {
        ctx.beginPath();
        for (let x = -10; x <= 266; x += 8) {
            const yy = y + Math.sin(x * 0.055 + y * 0.03) * 5;
            if (x === -10) ctx.moveTo(x, yy);
            else ctx.lineTo(x, yy);
        }
        ctx.stroke();
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.wrapS = THREE.RepeatWrapping;
    texture.wrapT = THREE.RepeatWrapping;
    texture.repeat.set(4, 4);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

function makeLabelTexture(text, color = '#ffffff') {
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 80;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = 'rgba(0,0,0,0.58)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.strokeStyle = color;
    ctx.lineWidth = 4;
    ctx.strokeRect(2, 2, canvas.width - 4, canvas.height - 4);
    ctx.fillStyle = color;
    ctx.font = 'bold 28px Segoe UI, Arial, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    return texture;
}

function addTextSprite(group, text, color, yOffset) {
    const texture = makeLabelTexture(text, color);
    const material = new THREE.SpriteMaterial({map: texture, transparent: true, depthTest: false});
    const sprite = new THREE.Sprite(material);
    sprite.scale.set(2.6, 0.82, 1);
    sprite.position.set(0, yOffset, 0);
    sprite.userData.texture = texture;
    group.add(sprite);
}

function addEnvironment() {
    const render = getRenderSettings();
    const dims = getDims();
    const envType = currentEnvType();
    const zInterface = num('z_water', 3.2);
    const envZ = num('env_z', zInterface);
    const waterHeight = envType === 'estanque' ? zInterface : envZ;
    const waterCenterY = envType === 'estanque' ? waterHeight / 2 : -waterHeight / 2;
    const bottomY = envType === 'estanque' ? 0 : -waterHeight;

    state.renderer.toneMappingExposure = render.exposure;

    const waterTexture = makeWaterTexture();
    const floorTexture = makeFloorTexture();

    const waterMaterial = new THREE.MeshPhysicalMaterial({
        color: 0x39c2ff,
        map: waterTexture,
        transparent: true,
        opacity: render.waterOpacity,
        roughness: 0.25,
        metalness: 0,
        transmission: 0.15,
        side: THREE.DoubleSide,
        depthWrite: false
    });

    waterMaterial.userData.texture = waterTexture;

    const wallMaterial = new THREE.LineBasicMaterial({color: 0xbfefff, transparent: true, opacity: 0.65});
    const floorMaterial = new THREE.MeshStandardMaterial({
        color: 0x56616a,
        map: floorTexture,
        roughness: 0.92,
        metalness: 0.02
    });
    floorMaterial.userData.texture = floorTexture;

    if (dims.shape === 'circle') {
        const radius = dims.radius || dims.x / 2;
        const water = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, waterHeight, 96, 1, true), waterMaterial);
        water.position.y = waterCenterY;
        if (render.showWater) state.root.add(water);

        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(water.geometry), wallMaterial);
        edges.position.copy(water.position);
        if (render.showWalls) state.root.add(edges);

        const floor = new THREE.Mesh(new THREE.CircleGeometry(radius, 96), floorMaterial);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = bottomY;
        state.root.add(floor);

        const surface = new THREE.Mesh(new THREE.CircleGeometry(radius, 96), new THREE.MeshBasicMaterial({
            color: 0x9de7ff, map: waterTexture, transparent: true, opacity: Math.min(0.55, render.waterOpacity + 0.1), side: THREE.DoubleSide, depthWrite: false
        }));
        surface.rotation.x = -Math.PI / 2;
        surface.position.y = envType === 'estanque' ? zInterface : 0;
        if (render.showWater) state.root.add(surface);
    } else {
        const water = new THREE.Mesh(new THREE.BoxGeometry(dims.x, waterHeight, dims.y), waterMaterial);
        water.position.y = waterCenterY;
        if (render.showWater) state.root.add(water);

        const edges = new THREE.LineSegments(new THREE.EdgesGeometry(water.geometry), wallMaterial);
        edges.position.copy(water.position);
        if (render.showWalls) state.root.add(edges);

        const floor = new THREE.Mesh(new THREE.PlaneGeometry(dims.x, dims.y), floorMaterial);
        floor.rotation.x = -Math.PI / 2;
        floor.position.y = bottomY;
        state.root.add(floor);

        const surface = new THREE.Mesh(new THREE.PlaneGeometry(dims.x, dims.y), new THREE.MeshBasicMaterial({
            color: 0x9de7ff, map: waterTexture, transparent: true, opacity: Math.min(0.55, render.waterOpacity + 0.1), side: THREE.DoubleSide, depthWrite: false
        }));
        surface.rotation.x = -Math.PI / 2;
        surface.position.y = envType === 'estanque' ? zInterface : 0;
        if (render.showWater) state.root.add(surface);
    }

    const grid = new THREE.GridHelper(Math.max(dims.x, dims.y), Math.max(4, Math.round(Math.max(dims.x, dims.y) / 2)), 0x5d7482, 0x2c414c);
    grid.position.y = bottomY + 0.012;
    if (render.showGrid) state.root.add(grid);

    const axes = new THREE.AxesHelper(Math.min(8, Math.max(dims.x, dims.y) / 4));
    axes.position.set(-dims.x / 2, bottomY + 0.05, -dims.y / 2);
    if (render.showAxes) state.root.add(axes);

    return {dims, waterHeight, bottomY};
}

function addArrow(group, dir, color, isOn) {
    const length = 2.8;
    const arrow = new THREE.ArrowHelper(dir.clone().normalize(), new THREE.Vector3(0, 0, 0), length, color, 0.7, 0.35);
    arrow.traverse(obj => {
        if (obj.material) obj.material.transparent = true;
        if (obj.material) obj.material.opacity = isOn ? 0.95 : 0.25;
    });
    group.add(arrow);
}

function onPointerDown(event) {
    if (state.mode !== '3d' || !state.initialized) return;
    const rect = state.renderer.domElement.getBoundingClientRect();
    state.pointer.x = ((event.clientX - rect.left) / rect.width) * 2 - 1;
    state.pointer.y = -((event.clientY - rect.top) / rect.height) * 2 + 1;
    state.raycaster.setFromCamera(state.pointer, state.camera);
    const hits = state.raycaster.intersectObjects(state.selectable, true);
    if (!hits.length) return;
    let obj = hits[0].object;
    while (obj && !obj.userData.lampGroup) obj = obj.parent;
    if (obj) selectLampGroup(obj);
}

function selectLampGroup(group) {
    state.selectedLamp = group;
    state.selectedLampItem = group.userData.item || null;
    state.transformControls.attach(group);
    if (state.selectedLampItem) {
        state.selectedLampItem.scrollIntoView({behavior: 'smooth', block: 'center'});
        state.selectedLampItem.style.outline = '2px solid #ffc72c';
        setTimeout(() => { if (state.selectedLampItem) state.selectedLampItem.style.outline = ''; }, 1800);
    }
    updateInfoLabel();
    requestRender();
}

function syncSelectedLampFrom3D() {
    if (!state.selectedLamp || !state.selectedLampItem) return;
    const dims = getDims();
    const sim = threePointToSim(state.selectedLamp.position, dims);
    const xInput = state.selectedLampItem.querySelector('.lamp-x');
    const yInput = state.selectedLampItem.querySelector('.lamp-y');
    const zInput = state.selectedLampItem.querySelector('.lamp-z');
    if (xInput) xInput.value = sim.x.toFixed(2);
    if (yInput) yInput.value = sim.y.toFixed(2);
    if (zInput) {
        zInput.value = sim.z.toFixed(2);
        zInput.setAttribute('data-manual', 'true');
        zInput.style.opacity = '1';
    }

    const euler = new THREE.Euler().setFromQuaternion(state.selectedLamp.quaternion, 'XYZ');
    const rxInput = state.selectedLampItem.querySelector('.lamp-rot-x');
    const ryInput = state.selectedLampItem.querySelector('.lamp-rot-y');
    const rzInput = state.selectedLampItem.querySelector('.lamp-rot-z');
    if (state.transformControls.mode === 'rotate') {
        if (rxInput) rxInput.value = THREE.MathUtils.radToDeg(euler.x).toFixed(1);
        if (ryInput) ryInput.value = THREE.MathUtils.radToDeg(euler.y).toFixed(1);
        if (rzInput) rzInput.value = THREE.MathUtils.radToDeg(euler.z).toFixed(1);
    }
    requestRender();
}

window.scene3dSetTransformMode = function scene3dSetTransformMode(mode) {
    if (!state.transformControls) return;
    state.transformControls.setMode(mode === 'rotate' ? 'rotate' : 'translate');
    if (state.selectedLamp) state.transformControls.attach(state.selectedLamp);
    requestRender();
};

window.scene3dClearSelection = function scene3dClearSelection() {
    if (state.transformControls) state.transformControls.detach();
    state.selectedLamp = null;
    state.selectedLampItem = null;
    updateInfoLabel();
    requestRender();
};

function addLampBody(group, dir, color, isAerial, isOn, modelCfg, render) {
    const scale = render.lampScale;
    const length = Math.max(0.03, modelCfg.length * scale);
    const width = Math.max(0.03, modelCfg.width * scale);
    const height = Math.max(0.03, modelCfg.height * scale);
    const bodyGeometry = modelCfg.shape === 'box'
        ? new THREE.BoxGeometry(width, length, height)
        : new THREE.CylinderGeometry(width / 2, width / 2, length, 32);

    const bodyMaterial = new THREE.MeshStandardMaterial({
        color,
        emissive: color,
        emissiveIntensity: isOn ? 0.35 : 0.04,
        roughness: 0.28,
        metalness: 0.45,
        transparent: true,
        opacity: isOn ? 1.0 : 0.35
    });
    const body = new THREE.Mesh(bodyGeometry, bodyMaterial);
    body.castShadow = true;
    body.receiveShadow = true;
    body.quaternion.setFromUnitVectors(new THREE.Vector3(0, -1, 0), dir.clone().normalize());
    group.add(body);

    const edge = new THREE.LineSegments(
        new THREE.EdgesGeometry(bodyGeometry),
        new THREE.LineBasicMaterial({color: 0x111111, transparent: true, opacity: isOn ? 0.65 : 0.18})
    );
    edge.quaternion.copy(body.quaternion);
    group.add(edge);

    if (modelCfg.shape !== 'box') {
        const ring = new THREE.Mesh(
            new THREE.TorusGeometry(width * 0.58, Math.max(0.01, width * 0.05), 12, 32),
            new THREE.MeshBasicMaterial({color: 0x111111, transparent: true, opacity: isOn ? 0.75 : 0.2})
        );
        ring.quaternion.copy(body.quaternion);
        group.add(ring);
    }
}

function addBeamMesh(group, profile, rx, ry, rz, beamScale, color, isOn, render) {
    const sg = profile?.sphere_grid;
    if (!sg || !sg.rad_norm || !sg.rad_norm.length) return;

    const h = sg.h_deg;
    const v = sg.v_deg;
    const positions = [];
    const colors = [];
    const indices = [];
    const colorObj = new THREE.Color();
    const cMedium = render.bioAttenuation ? getVisualAttenuationCoefficient() : 0;

    for (let i = 0; i < h.length; i++) {
        const phi = THREE.MathUtils.degToRad(h[i]);
        for (let j = 0; j < v.length; j++) {
            const theta = THREE.MathUtils.degToRad(v[j]);
            const intensity = Math.max(0.001, sg.rad_norm[i][j] || 0);
            const r = intensity * beamScale * 0.42;
            const attenuation = Math.exp(-cMedium * r * 0.25);
            const localSim = new THREE.Vector3(
                r * Math.sin(theta) * Math.cos(phi),
                r * Math.sin(theta) * Math.sin(phi),
                -r * Math.cos(theta)
            );
            const rotated = rotateSimVector(localSim, rx, ry, rz);
            const p = simVectorToThree(rotated);
            positions.push(p.x, p.y, p.z);

            const visualIntensity = intensity * attenuation;
            colorObj.setHSL(0.12 - visualIntensity * 0.12, 0.95, 0.22 + visualIntensity * 0.45);
            if (!isOn) colorObj.lerp(new THREE.Color(0x777777), 0.75);
            colors.push(colorObj.r, colorObj.g, colorObj.b);
        }
    }

    const nV = v.length;
    for (let i = 0; i < h.length; i++) {
        const nextI = (i + 1) % h.length;
        for (let j = 0; j < v.length - 1; j++) {
            const a = i * nV + j;
            const b = nextI * nV + j;
            const c = nextI * nV + j + 1;
            const d = i * nV + j + 1;
            indices.push(a, b, d, b, c, d);
        }
    }

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
    geometry.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();

    const material = new THREE.MeshBasicMaterial({
        vertexColors: true,
        transparent: true,
        opacity: isOn ? render.beamOpacity : Math.min(0.1, render.beamOpacity * 0.3),
        side: THREE.DoubleSide,
        depthWrite: false,
        blending: THREE.AdditiveBlending
    });
    const mesh = new THREE.Mesh(geometry, material);
    group.add(mesh);
}

function heatColor(t) {
    const x = Math.min(1, Math.max(0, t));
    const c = new THREE.Color();
    c.setHSL(0.68 - x * 0.68, 0.95, 0.22 + x * 0.38);
    return c;
}

function makeRaytraceTexture(grid, maxVal) {
    const rows = grid.length;
    const cols = rows ? grid[0].length : 0;
    if (!rows || !cols) return null;
    const canvas = document.createElement('canvas');
    canvas.width = cols;
    canvas.height = rows;
    const ctx = canvas.getContext('2d');
    const img = ctx.createImageData(cols, rows);
    const safeMax = maxVal > 0 ? maxVal : Math.max(...grid.flat(), 1e-9);
    for (let y = 0; y < rows; y++) {
        for (let x = 0; x < cols; x++) {
            const val = grid[y][x] || 0;
            const norm = Math.min(1, Math.max(0, Math.log10(1 + 80 * val / safeMax) / Math.log10(81)));
            const color = heatColor(norm);
            const idx = ((rows - 1 - y) * cols + x) * 4;
            img.data[idx] = Math.round(color.r * 255);
            img.data[idx + 1] = Math.round(color.g * 255);
            img.data[idx + 2] = Math.round(color.b * 255);
            img.data[idx + 3] = Math.round(35 + norm * 220);
        }
    }
    ctx.putImageData(img, 0, 0);
    const texture = new THREE.CanvasTexture(canvas);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.minFilter = THREE.LinearFilter;
    texture.magFilter = THREE.LinearFilter;
    return texture;
}

function addRaytracePlanes(dims) {
    const render = getRenderSettings();
    if (!render.showRaytrace || !window.lastResults?.results_by_kd) return;
    const kd = window.lastResults.kds && window.lastResults.kds.length ? window.lastResults.kds[0] : 'default';
    const kdRes = window.lastResults.results_by_kd[kd];
    if (!kdRes?.depths) return;

    Object.keys(kdRes.depths).forEach(depthKey => {
        const depthData = kdRes.depths[depthKey];
        if (!depthData?.grid) return;
        const depth = parseFloat(depthKey);
        if (!Number.isFinite(depth)) return;
        const texture = makeRaytraceTexture(depthData.grid, depthData.max || 0);
        if (!texture) return;

        const mat = new THREE.MeshBasicMaterial({
            map: texture,
            transparent: true,
            opacity: render.raytraceOpacity,
            side: THREE.DoubleSide,
            depthWrite: false
        });
        mat.userData.texture = texture;
        const plane = new THREE.Mesh(new THREE.PlaneGeometry(dims.x, dims.y), mat);
        plane.rotation.x = -Math.PI / 2;
        plane.position.y = currentEnvType() === 'jaula' ? -depth : depth;
        plane.position.y += currentEnvType() === 'jaula' ? -0.018 : 0.018;
        plane.userData.raytracePlane = true;
        state.root.add(plane);
    });
}

function getLightGlobeData() {
    if (!window.lastResults?.results_by_kd) return null;
    const kd = window.lastResults.kds?.[0] ?? Object.keys(window.lastResults.results_by_kd)[0];
    return window.lastResults.results_by_kd[kd]?.light_globes || null;
}

function lightGlobeGeometryIsCurrent() {
    const previous = window.lastPayload?.lamps || [];
    const current = Array.from(document.querySelectorAll('.lamp-item'));
    if (previous.length !== current.length) return false;
    const close = (a, b) => Math.abs(Number(a || 0) - Number(b || 0)) <= 1e-6;
    return current.every((item, index) => {
        const lamp = previous[index] || {};
        return lamp.xml === (item.querySelector('.lamp-xml')?.value || '') &&
            close(lamp.x, item.querySelector('.lamp-x')?.value) &&
            close(lamp.y, item.querySelector('.lamp-y')?.value) &&
            close(lamp.z, item.querySelector('.lamp-z')?.value) &&
            close(lamp.nominal_power ?? lamp.power, item.querySelector('.lamp-power')?.value) &&
            close(lamp.efficiency, item.querySelector('.lamp-eff')?.value) &&
            close(lamp.rot_x, item.querySelector('.lamp-rot-x')?.value) &&
            close(lamp.rot_y, item.querySelector('.lamp-rot-y')?.value) &&
            close(lamp.rot_z, item.querySelector('.lamp-rot-z')?.value);
    });
}

function interpolateIsoPoint(a, b, threshold) {
    const span = b.value - a.value;
    const t = Math.abs(span) < 1e-15 ? 0.5 : Math.min(1, Math.max(0, (threshold - a.value) / span));
    return {
        x: a.x + (b.x - a.x) * t,
        y: a.y + (b.y - a.y) * t,
        depth: a.depth + (b.depth - a.depth) * t
    };
}

function addIndexedTriangle(vertices, indices, vertexMap, points, dims) {
    const tri = [];
    points.forEach(point => {
        const zSim = currentEnvType() === 'estanque'
            ? num('z_water', 3.2) - point.depth
            : point.depth;
        const p = simPointToThree(point.x, point.y, zSim, dims);
        const key = `${p.x.toFixed(5)}|${p.y.toFixed(5)}|${p.z.toFixed(5)}`;
        let index = vertexMap.get(key);
        if (index === undefined) {
            index = vertices.length / 3;
            vertices.push(p.x, p.y, p.z);
            vertexMap.set(key, index);
        }
        tri.push(index);
    });
    if (tri.length === 3 && tri[0] !== tri[1] && tri[1] !== tri[2] && tri[0] !== tri[2]) {
        indices.push(tri[0], tri[1], tri[2]);
    }
}

function triangulateTetra(corners, tetra, threshold, vertices, indices, vertexMap, dims) {
    const inside = tetra.filter(index => corners[index].value >= threshold);
    const outside = tetra.filter(index => corners[index].value < threshold);
    if (!inside.length || !outside.length) return;

    if (inside.length === 1 || outside.length === 1) {
        const pivotInside = inside.length === 1;
        const pivot = (pivotInside ? inside : outside)[0];
        const others = pivotInside ? outside : inside;
        const points = others.map(index => interpolateIsoPoint(corners[pivot], corners[index], threshold));
        if (!pivotInside) points.reverse();
        addIndexedTriangle(vertices, indices, vertexMap, points, dims);
        return;
    }

    const a = interpolateIsoPoint(corners[inside[0]], corners[outside[0]], threshold);
    const b = interpolateIsoPoint(corners[inside[0]], corners[outside[1]], threshold);
    const c = interpolateIsoPoint(corners[inside[1]], corners[outside[0]], threshold);
    const d = interpolateIsoPoint(corners[inside[1]], corners[outside[1]], threshold);
    addIndexedTriangle(vertices, indices, vertexMap, [a, b, c], dims);
    addIndexedTriangle(vertices, indices, vertexMap, [b, d, c], dims);
}

function buildLightGlobeMesh(field, globeData, threshold, dims, color, opacity) {
    const xs = globeData.x_centers_m || [];
    const ys = globeData.y_centers_m || [];
    const depths = globeData.depth_centers_m || [];
    if (xs.length < 2 || ys.length < 2 || depths.length < 2) return null;

    const vertices = [];
    const indices = [];
    const vertexMap = new Map();
    const tetrahedra = [
        [0, 5, 1, 6], [0, 1, 2, 6], [0, 2, 3, 6],
        [0, 3, 7, 6], [0, 7, 4, 6], [0, 4, 5, 6]
    ];
    const offsets = [
        [0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0],
        [0, 0, 1], [1, 0, 1], [1, 1, 1], [0, 1, 1]
    ];

    for (let iz = 0; iz < depths.length - 1; iz++) {
        for (let iy = 0; iy < ys.length - 1; iy++) {
            for (let ix = 0; ix < xs.length - 1; ix++) {
                const corners = offsets.map(([ox, oy, oz]) => ({
                    x: xs[ix + ox],
                    y: ys[iy + oy],
                    depth: depths[iz + oz],
                    value: Number(field[iz + oz]?.[iy + oy]?.[ix + ox] || 0)
                }));
                const values = corners.map(corner => corner.value);
                if (Math.max(...values) < threshold || Math.min(...values) >= threshold) continue;
                tetrahedra.forEach(tetra => {
                    triangulateTetra(corners, tetra, threshold, vertices, indices, vertexMap, dims);
                });
            }
        }
    }
    if (!indices.length) return null;

    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.Float32BufferAttribute(vertices, 3));
    geometry.setIndex(indices);
    geometry.computeVertexNormals();
    const material = new THREE.MeshPhysicalMaterial({
        color,
        emissive: color,
        emissiveIntensity: 0.18,
        transparent: true,
        opacity,
        roughness: 0.35,
        metalness: 0,
        side: THREE.DoubleSide,
        depthWrite: false
    });
    return new THREE.Mesh(geometry, material);
}

function volumeAtThreshold(field, globeData, threshold) {
    const xe = globeData.x_edges_m || [];
    const ye = globeData.y_edges_m || [];
    const de = globeData.depth_edges_m || [];
    let volume = 0;
    for (let iz = 0; iz < field.length; iz++) {
        const dz = Number(de[iz + 1]) - Number(de[iz]);
        for (let iy = 0; iy < (field[iz] || []).length; iy++) {
            const dy = Number(ye[iy + 1]) - Number(ye[iy]);
            for (let ix = 0; ix < (field[iz][iy] || []).length; ix++) {
                if (Number(field[iz][iy][ix]) >= threshold) {
                    volume += (Number(xe[ix + 1]) - Number(xe[ix])) * dy * dz;
                }
            }
        }
    }
    return volume;
}

function formatVolume(value) {
    if (!Number.isFinite(value)) return '—';
    if (value >= 1000) return value.toLocaleString('es-CL', {maximumFractionDigits: 0});
    if (value >= 10) return value.toLocaleString('es-CL', {maximumFractionDigits: 1});
    return value.toLocaleString('es-CL', {maximumFractionDigits: 2});
}

function updateLightGlobePanel(globeData, threshold, entries, status = '') {
    if (!state.volumePanel) return;
    state.volumePanel.innerHTML = '';
    const heading = document.createElement('div');
    heading.className = 'scene3d-volume-heading';
    heading.textContent = `Volumen por lámpara · E ≥ ${threshold.toLocaleString('es-CL')} W/m²`;
    state.volumePanel.appendChild(heading);
    if (status) {
        const message = document.createElement('div');
        message.className = 'scene3d-volume-status';
        message.textContent = status;
        state.volumePanel.appendChild(message);
        return;
    }
    entries.forEach(entry => {
        const row = document.createElement('div');
        row.className = 'scene3d-volume-row';
        const swatch = document.createElement('span');
        swatch.className = 'scene3d-volume-swatch';
        swatch.style.backgroundColor = `#${entry.color.toString(16).padStart(6, '0')}`;
        const label = document.createElement('span');
        label.textContent = entry.label;
        const value = document.createElement('strong');
        value.textContent = `${formatVolume(entry.volume)} m³`;
        row.append(swatch, label, value);
        state.volumePanel.appendChild(row);
    });
    const resolution = document.createElement('div');
    resolution.className = 'scene3d-volume-resolution';
    const dx = Math.abs(Number(globeData.x_edges_m?.[1]) - Number(globeData.x_edges_m?.[0]));
    const dy = Math.abs(Number(globeData.y_edges_m?.[1]) - Number(globeData.y_edges_m?.[0]));
    const dz = Math.abs(Number(globeData.depth_edges_m?.[1]) - Number(globeData.depth_edges_m?.[0]));
    resolution.textContent = `Celda ${dx.toFixed(2)} × ${dy.toFixed(2)} × ${dz.toFixed(2)} m`;
    state.volumePanel.appendChild(resolution);
}

function addLightGlobes(dims) {
    const render = getRenderSettings();
    const globeData = getLightGlobeData();
    const threshold = render.lightGlobeThreshold;
    if (!render.showLightGlobes) {
        if (state.volumePanel) state.volumePanel.style.display = 'none';
        return;
    }
    if (state.volumePanel) state.volumePanel.style.display = 'block';
    if (!globeData) {
        updateLightGlobePanel({}, threshold, [], 'Simule para calcular los globos y sus volúmenes.');
        return;
    }
    if (!lightGlobeGeometryIsCurrent()) {
        updateLightGlobePanel(globeData, threshold, [], 'La geometría cambió; vuelva a simular para actualizar el volumen.');
        return;
    }

    const palette = [0xffc72c, 0x00bfff, 0xff5fa2, 0x65d46e, 0xff8a3d, 0x8b7cff];
    const entries = [];
    (globeData.lamps || []).forEach((lamp, index) => {
        const field = lamp.E_W_m2 || [];
        const color = palette[index % palette.length];
        const mesh = buildLightGlobeMesh(
            field, globeData, threshold, dims, color, render.lightGlobeOpacity
        );
        if (mesh) {
            mesh.userData.lightGlobe = true;
            mesh.userData.lampIndex = index;
            state.root.add(mesh);
        }
        const key = String(Number(threshold));
        const cached = lamp.volumes_m3?.[key];
        entries.push({
            label: lamp.label || `L${index + 1}`,
            color,
            volume: cached === undefined ? volumeAtThreshold(field, globeData, threshold) : Number(cached)
        });
    });
    updateLightGlobePanel(globeData, threshold, entries);
}

function addLamps(dims) {
    const render = getRenderSettings();
    const zInterface = num('z_water', 3.2);
    const activeAerial = document.getElementById('toggle_aerial')?.checked ?? true;
    const activeSubmerged = document.getElementById('toggle_submerged')?.checked ?? true;
    const beamScale = num('beam_scale', 8);

    document.querySelectorAll('.lamp-item').forEach((item, index) => {
        const x = parseFloat(item.querySelector('.lamp-x')?.value) || 0;
        const y = parseFloat(item.querySelector('.lamp-y')?.value) || 0;
        const z = parseFloat(item.querySelector('.lamp-z')?.value) || 0;
        const rx = parseFloat(item.querySelector('.lamp-rot-x')?.value) || 0;
        const ry = parseFloat(item.querySelector('.lamp-rot-y')?.value) || 0;
        const rz = parseFloat(item.querySelector('.lamp-rot-z')?.value) || 0;
        const xml = item.querySelector('.lamp-xml')?.value || '';
        const label = item.getAttribute('data-label') || `L${index + 1}`;
        const envType = currentEnvType();
        const isAerial = (envType === 'estanque' && z > zInterface) || (envType === 'jaula' && z < 0);
        const isOn = isAerial ? activeAerial : activeSubmerged;
        const color = isAerial ? 0xffc72c : 0x00bfff;
        const colorCss = isAerial ? '#ffc72c' : '#00bfff';
        const modelCfg = getLampModelConfig(xml);

        const group = new THREE.Group();
        group.position.copy(simPointToThree(x, y, z, dims));
        group.userData.lampGroup = true;
        group.userData.item = item;
        group.userData.label = label;

        const opticalDirSim = rotateSimVector(new THREE.Vector3(0, 0, -1), rx, ry, rz);
        const opticalDir = simVectorToThree(opticalDirSim).normalize();

        addLampBody(group, opticalDir, color, isAerial, isOn, modelCfg, render);
        addArrow(group, opticalDir, color, isOn);
        if (render.showLabels) {
            addTextSprite(group, isOn ? label : `${label} OFF`, colorCss, isAerial ? 1.1 : 0.85);
        }

        const profile = window.lampProfiles?.[xml];
        if (profile && render.showBeams) {
            addBeamMesh(group, profile, rx, ry, rz, beamScale, color, isOn, render);
        } else if (xml && window.fetchLampProfile) {
            window.fetchLampProfile(xml).then(() => {
                if (state.mode === '3d') window.updateScene3D();
            });
        }

        state.root.add(group);
        state.selectable.push(group);
    });
}

function updateInfoLabel() {
    if (!state.label) return;
    const dims = getDims();
    const envType = currentEnvType();
    const lamps = document.querySelectorAll('.lamp-item').length;
    const shape = dims.shape === 'circle' ? `circular R=${dims.radius}m` : `rectangular ${dims.x}x${dims.y}m`;
    const selected = state.selectedLamp ? ` · seleccionada: <strong>${state.selectedLamp.userData.label}</strong>` : '';
    const rt = window.lastResults ? ' · planos RT disponibles' : ' · simule para ver planos RT';
    const globe = getLightGlobeData() ? ' · globos volumétricos disponibles' : '';
    state.label.innerHTML = `<strong>${envType.toUpperCase()}</strong> · ${shape} · ${lamps} lámparas${selected}${rt}${globe}<br>Click para seleccionar; gizmo para mover/rotar. Las superficies coloreadas son límites de irradiancia por lámpara.`;
}

window.updateScene3D = function updateScene3D() {
    initScene();
    if (!state.initialized) return;
    if (state.transformControls) state.transformControls.detach();
    state.selectedLamp = null;
    state.selectedLampItem = null;
    state.selectable = [];
    clearRoot();
    updateOverlayModelControls();
    const env = addEnvironment();
    addLamps(env.dims);
    addRaytracePlanes(env.dims);
    addLightGlobes(env.dims);
    updateInfoLabel();

    const maxSpan = Math.max(env.dims.x, env.dims.y, env.waterHeight);
    state.controls.target.set(0, currentEnvType() === 'jaula' ? -env.waterHeight / 2 : env.waterHeight / 2, 0);
    if (!state.camera.userData.initializedForScene) {
        state.camera.position.set(maxSpan * 0.75, Math.max(10, maxSpan * 0.75), maxSpan * 0.95);
        state.camera.userData.initializedForScene = true;
    }
    state.controls.update();
    resize();
    requestRender();
};

window.togglePreviewMode = function togglePreviewMode(mode) {
    state.mode = mode === '3d' ? '3d' : '2d';
    const div2d = document.getElementById('heatmap_div_preview');
    const div3d = document.getElementById('scene3d_preview');
    const btn2d = document.getElementById('btn_preview_2d');
    const btn3d = document.getElementById('btn_preview_3d');

    if (div2d) div2d.style.display = state.mode === '2d' ? 'block' : 'none';
    if (div3d) div3d.style.display = state.mode === '3d' ? 'block' : 'none';
    if (btn2d) btn2d.classList.toggle('active', state.mode === '2d');
    if (btn3d) btn3d.classList.toggle('active', state.mode === '3d');

    if (state.mode === '3d') {
        window.updateScene3D();
    } else if (window.updateScene) {
        window.updateScene();
    }
};

function bootScene3D() {
    const div = document.getElementById('scene3d_preview');
    if (!div) return;
    initScene();
    if (div.style.display !== 'none') {
        window.updateScene3D();
    }
}

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', bootScene3D);
} else {
    bootScene3D();
}
