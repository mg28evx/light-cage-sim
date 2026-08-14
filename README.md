Software para la simulación de irradiancia según archivos TM-33-18, con parámetros para posición, dimmerizado y rotación de lámparas. 

La instalación se realiza mediante la ejecución de iniciar_simulador.bat, creando un entorno virtual y abriendo la interfaz del simulador en una ventana del navegador.

El software contiene un motor de simulación por ray-tracing, que integra los efectos de refracción, reflexión y atenuación derivados del cambio de medio aire-agua.
Es posible simular estanques y jaulas. Los estanques siguen una lógica de altura desde nivel de piso, y las jaulas siguen una lógica de profundidad desde superficie.
Opción de descarga de gráficos integrada, para evaluaciones rápidas.
Opción de cargar y guardar parámetros.

## Presets bio-ópticos por centro

### Origen de parámetros: una modalidad seleccionable

El modo `scattering -> bio` necesita tres números —`TSS`, `CDOM a440` y `Chl-a`—
de los que se derivan `a(λ)`, `b(λ)` y `c(λ)`. El selector **Origen de
parámetros**, dentro del panel de óptica, define de dónde salen:

| Modalidad | Qué hace |
| --- | --- |
| **Manual** (por defecto) | Los tres valores se escriben a mano. No se ejecuta ninguna consulta de red. |
| **Teledetección** | Abre el asistente satelital en un panel lateral: centro o coordenadas, fuente, período, buffer y escenario. Al pulsar «Aplicar al modelo» escribe los tres parámetros. |
| **Medición local** | Carga un CSV de observaciones propias y lo procesa con las mismas conversiones y cuantiles que la ruta satelital. |

El modelo físico posterior es idéntico en las tres. Lo que cambia es la
procedencia, que queda registrada por parámetro (`manual`, `satélite`,
`proxy FNU→TSS`, `CSV local`), se muestra en el panel de corrida y se guarda
dentro del archivo de configuración.

La cadena completa de transformaciones —conversiones proxy, agregación por
semana ISO, cuantiles, ajuste inverso al `Kd(490)` observado, IOP espectrales,
cierres `Kd` y modelos de Secchi— está documentada ecuación por ecuación, con
unidades y con los valores activos sustituidos, en el panel **Método y
ecuaciones** de la ayuda de la aplicación, y en `docs/documentacion_fisica.tex`.

### Presets

El módulo `optical_lookup.py` genera presets `claro` (P25), `tipico` (P50) y
`turbio` (P75). Puede trabajar con un CSV de observaciones satelitales/proxy,
NOAA CoastWatch ERDDAP sin credenciales, conectores remotos configurables o, si
aun no hay datos, con una clase de agua conservadora por centro.

Cuando falta el cuantil directo de una variable, el preset **no** deja el valor
por defecto tal cual: lo reescala para reproducir el `Kd(490)` observado,
mediante un factor `r = clamp(Kd_obs/Kd_est, 0.35, 3.0)` aplicado a TSS y CDOM.
Si ese factor satura con frecuencia, la clase de agua base no representa el
sitio y conviene medir localmente.

### Modo RAS (Bårdsnes 2020)

La opción `scattering -> ras_bardsnes` está **operativa**. De Bårdsnes (2020) se
toman las *formas* espectrales medidas en agua de RAS —pendiente particulada
`η_p ≈ 1.8` y pendiente de absorción `S_CDOM ≈ 0.0141 nm⁻¹`, más la regresión de
tanque `TSS = 3.0411·NTU − 0.376`— con atenuación que crece hacia el azul,
inverso al océano.

La *magnitud absoluta* no es transferible entre instalaciones: la medición del
trabajo original tiene re-entrada de luz por las paredes del tanque. Por eso
`b*550` y `ω_p` quedan expuestos como parámetros calibrables en la interfaz, con
valores por defecto elegidos para preservar continuidad con el modo marino, no
por ser universales. Antes de usar esta ruta para dimensionar, calíbrelos con una
medida óptica del propio sistema: `c(λ)`, `Kd(λ)` o transmitancia espectral.

La interfaz bio-óptica utiliza un perfil estacional por semana ISO en lugar de
fechas arbitrarias. Para cada semana resume primero cada año completo y luego
combina los años con igual ponderación, evitando que un año con mayor cobertura
satelital domine el resultado. Una semana se marca como útil cuando reúne al
menos cuatro días válidos y cubre el mínimo de años representables por el
historial elegido: un año para historial de 1 año, dos años para historiales de
2 o más años. El endpoint
`/api/optical_weekly_profile` devuelve las 53 semanas, su cobertura, medianas,
rangos intercuartílicos y presets `claro`, `tipico` y `turbio`.
Para analizar datos del año calendario/ISO en curso, use el modo de semana ISO
puntual (`target_year` + `target_week`); el modo de historial por años completos
termina en el año cerrado anterior.

Ejemplo:

```bash
python optical_lookup.py --center pilpilehue --source auto --observations data/optical_observations_example.csv
```

También queda disponible en el backend:

```text
GET /api/optical_presets?center=pilpilehue
GET /api/optical_centers
GET /api/optical_sources/status
```

También puede subirse un CSV desde la interfaz con la modalidad **Medición
local**, que lo guarda en `data/optical_cache/uploads/` y lo entrega al mismo
flujo mediante `observations_path`:

```text
POST /api/optical_observations/upload   (multipart, campo "file")
```

Columnas soportadas para observaciones: `center_id,date,source,tss,spm,
turbidity_fnu,turbidity_algorithm,turbidity_uncertainty_fnu,chl,cdom_a440,
cdom_a443,kd490,zsd,quality`. Si `tss` falta se usa `spm` como proxy; si falta
`tss` pero existe `turbidity_fnu`, se convierte con `TSS = pendiente*FNU +
intercepto`. La pendiente y el intercepto pueden configurarse desde la interfaz
o por CLI con `--fnu-to-tss-slope` y `--fnu-to-tss-intercept`. Si falta
`cdom_a440` y existe `cdom_a443`, se convierte con una pendiente CDOM típica; si
falta `kd490` y existe `zsd`, se estima `Kd ~= 1.7/ZSD`.

Los conectores remotos quedan desacoplados en `optical_sources/`. El conector
`noaa_coastwatch.py` descarga datos reales desde ERDDAP publico usando productos
DINEOF globales diarios de `chlor_a` y `kd_490`. Los conectores
`copernicus.py`, `nasa_oceancolor.py` y `sentinel2.py` reportan
disponibilidad/configuración.

Sentinel-2 se integra mediante salidas ACOLITE. Por defecto el conector lee
archivos `.nc` o `.csv` desde:

```text
data/optical_cache/sentinel2_acolite
```

También puede apuntarse a otro directorio con `SENTINEL2_ACOLITE_OUTPUT_DIR`.
El conector busca variables de turbidez ya calculadas por ACOLITE/Nechad o,
si solo existe reflectancia de agua `rhow_665`, puede aplicar la forma de
Nechad cuando se configuren `SENTINEL2_NECHAD_AT`, `SENTINEL2_NECHAD_C` y
opcionalmente `SENTINEL2_NECHAD_BT`. Si se desea lanzar ACOLITE desde el
simulador, se puede definir `ACOLITE_CMD_TEMPLATE`; el comando se renderiza con
`{lat}`, `{lon}`, `{center_id}`, `{start_date}`, `{end_date}`, `{buffer_m}` y
`{output_dir}`. Esta ruta mantiene separadas tres capas: corrección atmosférica
ACOLITE/DSF, estimación de turbidez FNU y calibración local FNU -> TSS.

Copernicus Marine usa GlobColour global L3 diario de 4 km:

```text
cmems_obs-oc_glo_bgc-plankton_my_l3-multi-4km_P1D
cmems_obs-oc_glo_bgc-transp_my_l3-multi-4km_P1D
cmems_obs-oc_glo_bgc-optics_my_l3-multi-4km_P1D
```

Para períodos recientes cambia automáticamente a las variantes `_nrt_`.
El conector entrega `CHL`, `KD490`, `SPM`, `CDM` y sus incertidumbres
porcentuales cuando estan disponibles.

NASA OceanColor usa las colecciones `VIIRSN_L3m_CHL`,
`VIIRSN_L3m_KD`, `VIIRSN_L3m_IOP`, `PACE_OCI_L3M_CHL`,
`PACE_OCI_L3M_KD` y `PACE_OCI_L3M_IOP`. El conector descarga archivos L3m
diarios de 4 km, extrae `chlor_a`, `Kd_490` y `adg_443`, limita las consultas
interactivas a 14 días y reutiliza archivos en `data/optical_cache/`.

En modo `auto`, los centros de fiordo/costa priorizan Sentinel-2/ACOLITE cuando
hay productos configurados; si no hay datos válidos, se usan Copernicus,
NASA OceanColor o NOAA CoastWatch como respaldo. NASA OceanColor se puede
seleccionar explicitamente como fuente de contraste; sus archivos L3m usados
aqui no incluyen una incertidumbre porcentual por píxel equivalente.

## Temperatura y salinidad Copernicus

El script `ocean_physics_extract.py` extrae series diarias de temperatura
potencial (`thetao`) y salinidad (`so`) desde Copernicus Marine Global Ocean
Physics Analysis and Forecast (`GLOBAL_ANALYSISFORECAST_PHY_001_024`). Usa los
centros de `data/optical_centers.csv`, un buffer espacial en metros y la capa
superficial del modelo por defecto (`--depth-m 0.5`, equivalente al nivel
Copernicus cercano a 0.494 m).

Ejemplo para todos los centros del repo:

```bash
python ocean_physics_extract.py \
  --all-centers \
  --start-date 2026-05-01 \
  --end-date 2026-06-26 \
  --buffer-m 6000 \
  --depth-m 0.5
```

La salida por defecto se guarda en `data/ocean_physics/` como CSV, con una fila
por centro y día. Para una ubicación manual use `--lat` y `--lon`; para resumir
una capa vertical use `--depth-window-m`, por ejemplo `--depth-m 5
--depth-window-m 5`.
