# Interfaz bio-optica relativa para Caligus

Esta capa agrega una salida separada del simulador optico para evaluar indices relativos de solapamiento vertical pez-copepodito. No cambia el significado fisico de las salidas existentes: los mapas y tablas principales siguen reportando irradiancia simulada segun la configuracion optica activa.

## Que calcula el motor optico

El motor `simulation_engine.py` simula propagacion de luz desde archivos TM-33/IES y entrega irradiancia radiometrica en `W/m2`. Para TM-33 usa la distribucion angular radiometrica y el SPD espectral del archivo. Para el analisis bio-optico se exige SPD real en los TM-33 usados.

La nueva ruta volumetrica es opt-in mediante `volume_tally`. Usa un estimador por longitud de trayectoria: acumula `W * ds` dentro de cada celda y divide por el volumen de celda, entregando una magnitud radiometrica volumetrica en `W/m2` comparable como irradiancia escalar/fluence-rate por celda. Esta ruta se apaga por defecto y no altera los mapas por plano existentes.

## Que calcula el post-procesamiento biologico

El modulo `biooptical_analysis.py` resume la grilla 3D por capas verticales y calcula:

- `IC = sum_i C_i * F_i`
- `IE_pez_total = sum_i F_i * E_total_i`
- `IE_contacto_total = sum_i C_i * F_i * E_total_i`
- `IE_contacto_spectral = sum_i C_i * F_i * (w_blue E_blue_i + w_green E_green_i + w_red E_red_i)`

Los perfiles `C(z)` y `F(z)` se normalizan para sumar 1 sobre las capas analizadas. Los indices son relativos; no son probabilidad de infeccion ni abundancia esperada.

## Salidas

La UI agrega la seccion `BIO-OPTICA CALIGUS`. Desde ahi se puede:

- activar salida bio-optica para la simulacion actual;
- configurar capas, resolucion horizontal, paso de tally y umbrales;
- seleccionar perfiles larvales y de pez;
- guardar configuraciones completas como escenarios batch;
- comparar escenarios contra una base de normalizacion.

El backend devuelve:

- CSV por capas con medias, medianas, P90/P95, maximos, bandas azul/verde/rojo y fracciones de volumen sobre umbrales;
- CSV de indices `IC`, `IE_pez`, `IE_contacto` e `IE_contacto_spectral`;
- CSV opcional de celdas 3D;
- graficos prudentes para irradiancia por capa, bandas, heatmap escenario-profundidad e indice espectral de contacto.

## Supuestos y limites

- La luz se trata como modulador secundario, principalmente via cambios en `F(z)`.
- Las distribuciones larvales por defecto son escenarios de sensibilidad, no una distribucion fija universal.
- Los pesos espectrales por defecto (`blue=1.0`, `green=0.7`, `red=0.2`) son exploratorios y deben validarse con datos biologicos.
- Los umbrales `0.054`, `0.54`, `5.4` y `8.7 W/m2` son anclas experimentales configurables, no limites biologicos universales.
- El modelo no reemplaza salinidad, temperatura, circulacion, presion larval local ni ventana temporal de siembra.
- Frenzl/Nordtug/Genna se usan como respaldo cualitativo/proxy; no se implementan como funciones universales de fijacion.

## Validaciones implementadas

- Capas con rango positivo y sin solapamiento.
- Bandas espectrales no solapadas.
- Umbrales y pesos no negativos.
- `C_i` y `F_i` suman 1.
- Irradiancia finita y no negativa.
- Escenario base de normalizacion obligatorio cuando se solicita ratio relativo.
