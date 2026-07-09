Software para la simulación de irradiancia según archivos TM-33-18, con parámetros para posición, dimmerizado y rotación de lámparas. 

La instalación se realiza mediante la ejecución de iniciar_simulador.bat, creando un entorno virtual y abriendo la interfaz del simulador en una ventana del navegador.

El software contiene un motor de simulación por ray-tracing, que integra los efectos de refracción, reflexión y atenuación derivados del cambio de medio aire-agua.
Es posible simular estanques y jaulas. Los estanques siguen una lógica de altura desde nivel de piso, y las jaulas siguen una lógica de profundidad desde superficie.
Opción de descarga de gráficos integrada, para evaluaciones rápidas.
Opción de cargar y guardar parámetros.

## Presets bio-ópticos por centro

El módulo `optical_lookup.py` genera presets `claro`, `tipico` y `turbio`
compatibles con el modo `scattering -> bio` del simulador. Puede trabajar con
un CSV de observaciones satelitales/proxy, NOAA CoastWatch ERDDAP sin
credenciales, conectores remotos configurables o, si aun no hay datos, con una
clase de agua conservadora por centro. La interfaz
incluye un asistente dentro del panel bio-óptico para buscar por centro o
coordenadas, elegir fuente/período/buffer y aplicar el preset directamente a
TSS, CDOM, Chl-a y g.

El método operativo `scattering -> bio` corresponde a una parametrización
bio-óptica espectral general basada en absorción y dispersión. Se presenta por
separado de la opción `scattering -> ras_bardsnes`: Bårdsnes (2020) respalda la
influencia de la carga orgánica y las micropartículas sobre la luz en RAS, pero
no entrega coeficientes universales transferibles a cualquier instalación. La
opción RAS queda bloqueada hasta incorporar una calibración propia que relacione
carga orgánica o micropartículas con `c(λ)`, `Kd(λ)` o transmitancia espectral.

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
