# TM-33-18 sintético Porter 2005: reconstrucción corregida

La fuente primaria es Porter, Langland, Woolcott y Pankhurst (2005), informe FRDC 2001/246. Los métodos establecen que las luces fueron “either Aquabeam (Pisces 400 watt) or C&T Lighting (400 watt units)”, ubicadas “at 5m in a 10m deep cage”. El apéndice 3 describe la matriz como “Light attenuation from a 400 watt submersible light” en agua de mar con una lectura Secchi de 8 m. La fuente exacta del apéndice, su espectro y su goniofotometría no se publicaron.

La frase “dominant wavelength 535nm” aparece únicamente en Commercial Trial 1, Year 1. No se usa como espectro de la tabla del apéndice porque Pisces 400 era una tecnología de halogenuros metálicos de emisión blanca. La versión corregida aplica un prior histórico de 33–38 klm y 100–124 W radiantes visibles para una lámpara de 400 W. El nominal elegido es 35,50 klm y 116,01 W: 88,76 lm/W eléctricos y 29,00 % de eficiencia eléctrica-radiante. El SPD es un sustituto blanco de 3700 K, formado por continuo más líneas representativas de halogenuros metálicos, con eficacia radiométrica fotópica de 306,03 lm/W. Es una hipótesis tecnológica, no una medición del equipo original.

El modelo inverso es

\[
E_v(r,z)=B+\frac{I_v(\theta)\cos\theta}{d^2}\exp(-cd),
\qquad d=\sqrt{r^2+z^2},\quad \theta=\tan^{-1}(r/z).
\]

La intensidad axisimétrica se regulariza angularmente y su integral se condiciona al flujo histórico. El ajuste final entrega \(c=0{,}28183\ \mathrm{m^{-1}}\), con intervalo bootstrap-prior del 90 % de 0,21584–0,33612 m⁻¹, y fondo difuso efectivo \(B=32{,}108\ \mathrm{lx}\), con intervalo 25,278–35,455 lx. El fondo no se incorpora a la potencia de la lámpara: sólo se suma para comparar con la luxometría del informe.

La reconstrucción analítica logra \(R^2_{\log}=0{,}9060\), MAPE mediano de 19,51 % y RMSE multiplicativo ×1,416. La verificación independiente con el motor, un millón de rayos y receptores de 1 m² entrega \(R^2_{\log}=0{,}9045\), MAPE 20,78 % y RMSE multiplicativo ×1,420. La cobertura predictiva empírica del intervalo central del 90 % es 91,7 %. La conversión irradiancia-iluminancia nominal es \(E_e=E_v/306{,}03\), con un rango de eficacia de escenario del 90 % de 281,08–358,47 lm/W.

Para validar el apéndice se usa `confgs/porter_2005_synthetic.json`: una sola lámpara, potencia eléctrica 400 W, eficiencia 0,2900203, fuente puntual, atenuación de haz `c=0.2818330`, fondo externo 32,108 lx, grilla relativa horizontal 1–8 m y vertical 1–6 m, y un millón de rayos. La tabla completa con lux observados, lux simulados, irradiancia equivalente observada, irradiancia de lámpara, intervalos y residuos está en `sensitivity/out/porter_2005/porter_simulated_measurements.csv`.

Para replicar Commercial Trial 1, Year 2 se usa `confgs/porter_2005_trial2_80m_perimeter.json`: jaula circular de 80 m de perímetro —radio 12,7324 m, diámetro 25,4648 m—, profundidad 10 m y ocho lámparas de 400 W a 5 m. El informe dice literalmente “80m diameter”, pero diámetro se interpreta como perímetro porque una jaula de 80 m de diámetro es incompatible con la densidad de cosecha indicada y con la escala comercial descrita. Como el plano de instalación no está publicado, las ocho lámparas se colocan nominalmente cada 45° sobre un anillo de radio R/2; esta distribución es una hipótesis explícita y debe sustituirse si aparece el layout real.

El TM-33-18 corregido está en `uploaded_lamps/PORTER_2005_SYNTHETIC_400W.xml`. Se regenera junto con configuraciones, tablas, bootstrap y figuras mediante `MPLCONFIGDIR=/tmp/porter-mpl venv/bin/python sensitivity/porter_tm33_synthetic.py --bootstrap 500 --engine-rays 1000000`. La limitación dominante ya no es la eficiencia histórica, sino la falta del modelo exacto de lámpara, SPD medido, orientación del sensor LI-COR, medición con lámpara apagada y propiedades ópticas inherentes del agua.

## Trial 3: configuración asociada al 18 % de crecimiento

El resultado de crecimiento corresponde a Trial 3, no al ensayo de ocho luces. El informe especifica una población mixta de 132.000 post-smolts transferida al mar el 28 de mayo de 2002, peso inicial medio 98 g, mitad control y mitad iluminada, cuatro luces sumergibles de 400 W, iluminación adicional constante hasta el 5 de noviembre de 2002 y alimentación diaria equivalente al 2,3 % del peso corporal. El tratamiento iluminado se representa en `confgs/porter_2005_growth18_lit.json`; el contrafactual sin iluminación artificial está en `confgs/porter_2005_growth18_control.json`.

La jaula se interpreta como 80 m de perímetro, radio 12,7324 m y 10 m de profundidad. Por aplicación de los métodos generales, las luces quedan a 5 m. Como el plano de cuatro luminarias no fue publicado, se distribuyen cada 90° sobre un anillo de radio R/2. La configuración conserva como metadatos los 66.000 peces por tratamiento, las fechas, 161 días de luz artificial, el régimen nominal 24L:0D, la alimentación y los resultados de peso.

El informe resume el efecto como 18 % de ventaja de crecimiento durante doce meses, pero también publica 2280±80 g frente a 1880±70 g; la razón directa entre esas medias es 21,28 %. Ambos valores se conservan porque no son matemáticamente equivalentes y el documento no entrega el cálculo exacto usado para obtener 18 %. El simulador óptico no predice biomasa: reproduce la dosis y distribución de luz asociadas al tratamiento. Para predecir el 18 % se necesita acoplar irradiancia, fotoperiodo, temperatura, ración y crecimiento específico en un modelo longitudinal calibrado contra la serie de la Figura 13.
