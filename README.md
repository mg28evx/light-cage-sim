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

## Fotoperíodo e irradiancia objetivo (Oldham 2023)

La pestaña **Fotoperíodo** propone la irradiancia artificial que hay que
alcanzar para que el lote lea el régimen como iluminación, a partir del modelo
de interpretación adaptativa de Oldham, Oppedal, Fjelldal & Hansen (2023),
*Adaptive photoperiod interpretation modulates phenological timing in Atlantic
salmon*, Sci. Rep. 13:2618. No dimensiona luminarias: el objetivo se verifica
después con el trazado de rayos.

Ese trabajo expuso parr macho a ocho regímenes 12:12 combinando dos
intensidades diurnas (≈69 y 1,0 µmol m⁻² s⁻¹) con cuatro niveles nocturnos
definidos como porcentaje del día (100 %, 10 %, 1 %, 0 %), y deja dos
resultados utilizables:

1. **Umbral fijo de detección** entre 0,01 y 0,1 µmol m⁻² s⁻¹. El grupo Low1,
   con 0,01 µmol nocturnos, no maduró y se comportó como oscuridad completa.
2. **Interpretación adaptativa** por encima de ese umbral: lo que el pez lee
   como «noche» escala con la intensidad diurna reciente.

De ahí la regla que implementa `ambient_light.target_irradiance`:

```
E_objetivo(z_obj) = max( E_umbral , término adaptativo )

  luminarias sólo de noche :  r · E_nat
  luminarias 24 h          :  r · E_nat / (1 − r)
```

La razón de Oldham se define sobre la luz **total** que recibe el pez. Con
luminarias encendidas 24 h —la práctica habitual de luz continua en jaula— el
día percibido es natural más artificial, y usar `r · E_nat` subdimensiona: con
r = 10 % se logra 9,1 %, y con r = 100 % sólo 50 %. En 24 h la razón 1 es
inalcanzable mientras haya sol. Los ocho regímenes de Oldham corresponden al
modo nocturno, porque en sus estanques no había luz natural que se sumara.

**Advertencia.** La razón no explica sola la respuesta: con el mismo 10 %
nocturno maduró el 20 % del grupo High10 y sólo el 6 % del Low10. La intensidad
absoluta del día sigue pesando y el paper deja esa dependencia abierta. La
salida es una cota operativa, no una curva de respuesta.

### Cadena de cálculo

`ambient_light.py` resuelve, en W/m² de PAR sobre plano horizontal:

| Paso | Modelo |
| --- | --- |
| Posición solar | Algoritmo NOAA con ecuación del tiempo y ángulo horario; recorre el día completo |
| Cielo | **PAR horario observado**: NASA POWER (directo y difuso, CERES SYN1deg) o CSV propio. Respaldo sin datos: cielo despejado de Meinel × transmitancia, con difusa por Erbs et al. (1982) |
| Espectro de superficie | Reparto del PAR entre bandas según ASTM G173-03 AM1.5 global, 400–700 nm cada 10 nm |
| Interfaz aire-agua | Fresnel al ángulo solar para el directo, 0,934 para el difuso |
| Columna de agua | Por longitud de onda, con **las mismas a(λ) y b_b(λ) del trazado de rayos** y el cierre de Lee, Du & Arnone (2005); directo al cenit del instante, difuso a 43,3° equivalente (Kirk) |
| Agregación | Media de fotofase por día, resumida con la media de los días en o sobre el percentil pedido |

Las IOP se resuelven con `app_sim.build_optical_diagnostics` sobre el mismo
bloque `optics` que recibe la simulación, así que funcionan todos los modos de
la sección Óptica: bio-óptico marino, RAS de Bårdsnes, `c/ω` manual y
coeficiente declarado. En los modos bio-ópticos se puede usar además el
**perfil estacional** de Teledetección: cada semana ISO con observaciones toma
el TSS, CDOM y Chl-a de su escenario (claro, típico o turbio), ya ajustados al
Kd490 satelital.

Trabajar por espectro captura el endurecimiento espectral que un Kd escalar
pierde: el agua filtra primero azul y rojo, y el Kd de PAR equivalente baja con
la profundidad (con TSS 3 mg/L, CDOM 0,3 1/m y Chl-a 1,5 mg/m³, ≈0,45 1/m
entre 0 y 5 m y ≈0,37 1/m en torno a 8 m).

### Parámetros y salida

Dos profundidades distintas: la **de referencia**, donde se evalúa la luz
natural que constituye la historia lumínica del lote, y la **objetivo**, donde
debe cumplirse la irradiancia artificial. El **percentil de agregación** es un
estadístico continuo — 0 devuelve la media de toda la ventana, 50 la media de
la mitad superior, 100 tiende al máximo.

El **umbral de detección** por defecto es 0,016 W/m², el mismo valor que la
vista 3D usa como límite de globos de luz; equivale a 0,060–0,073 µmol m⁻² s⁻¹
según el espectro (LED azul a PAR diurno), dentro de la banda de Oldham y sobre
el 0,05–0,07 de Migaud (2006) y Vera (2010).

La salida principal es una **tabla de objetivos propuestos**: percentil ×
razón, con la fracción de días de la ventana que cada combinación sostiene. Se
acompaña del objetivo día a día, que acota el rango útil de atenuación, y del
perfil vertical del estadístico recalculado a cada profundidad.

### Cielo observado

La nubosidad es, después del agua, lo que más mueve el objetivo, y varía mucho
día a día. En la celda de Puerto Montt, la razón diaria entre el PAR con cielo
real y el de cielo despejado (NASA POWER, 2015–2024) es:

| Mes | P10 | Mediana | P90 |
| --- | --- | --- | --- |
| Ene | 0,53 | 0,84 | 0,99 |
| Mar | 0,47 | 0,78 | 0,98 |
| May | 0,32 | 0,63 | 0,90 |
| Jun | 0,29 | 0,57 | 0,93 |
| Ago | 0,31 | 0,64 | 0,88 |
| Oct | 0,43 | 0,72 | 0,97 |
| Dic | 0,49 | 0,79 | 0,99 |

Una transmitancia fija de 0,7 coincide con la media anual (0,71) pero
sobrestima el invierno y borra la variabilidad diaria, de la que depende
justamente el percentil. `sky_forcing.py` reemplaza ese parámetro por datos:

- **NASA POWER** (por defecto): PAR horario con cielo real, ya separado en
  directo horizontal y difuso (`ALLSKY_SFC_PAR_DIRH`, `ALLSKY_SFC_PAR_DIFF`),
  más el de cielo despejado como diagnóstico. Sin credenciales, desde 2001, con
  ~3 meses de rezago (las horas sin dato llegan como −999 y los días
  incompletos se excluyen). ~300 kB y ~2 s por año; queda en
  `data/sky_cache/`. Los años cerrados se guardan de forma permanente y el año
  en curso se renueva cada 7 días. Resolución ≈1°: la celda mezcla mar, costa y
  cordillera.
- **CSV propio**: sensores del centro, estaciones o Explorador Solar. Horario o
  subhorario; PAR (`par_dirh` + `par_diff`, `par`, `par_umol`) o global
  (`ghi`/`radiacion_global`, con `dhi`/`difusa` opcional). El desfase horario
  y la convención de la marca de tiempo se detectan por correlación con la
  geometría solar si el archivo no los declara.

Con datos observados se evalúa el **año exacto** de la ventana o una
**climatología multianual**, en la que la ventana se repite en cada año y el
percentil se toma sobre todos los días-año.

El huso horario y el paso temporal movían el objetivo menos de 1 %, y por eso
no son parámetros de la interfaz.

### Endpoint

```text
POST /api/photoperiod_target
POST /api/sky_observations/upload   (multipart, campo "file")
```

Pruebas en `tests/test_ambient_light.py` (66 casos: geometría solar contra
valores astronómicos cerrados, agua gris que reproduce Beer-Lambert, monotonías
espectrales, perfil estacional, tabla de propuestas y la lógica de los ocho
regímenes de Oldham), `tests/test_sky_forcing.py` (23 casos: un día real de
NASA POWER como fixture, caché y descarga simulada, CSV con desfase y
convención de marca, y un camino observado que reproduce exactamente el modelo
manual con datos sintéticos) y `tests/test_photoperiod_endpoint.py` (14 casos).
Ninguna prueba accede a la red.
