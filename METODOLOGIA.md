# Metodología del motor cuantitativo ProfitLab

Versión de cálculo: **`2026.11.26-pro15b`** (se devuelve en `meta.calc_version` de cada respuesta).
Todos los cálculos se hacen en este backend; web, iOS y Android solo dibujan lo que devuelve la API, así que las cifras son idénticas en las tres plataformas.

## Flujo de datos

```
Proveedor (Massive/Polygon · respaldo Yahoo)
 → Validación (vencimientos vigentes, IV presente, OI, barras sin duplicados ni OHLC incoherente)
 → Normalización de instrumento (profitlab/instruments.py)
 → Cálculo (profitlab/exposures.py, volume_profile.py, api/main.py)
 → Caché por instrumento (30 s; cadena 90 s con clave por spot y ventana)
 → API REST con `meta`
 → Web / iOS / Android
```

## Metadatos de cada respuesta (`meta`)

| Campo | Significado |
|---|---|
| `instrument` | símbolo pedido, tipo (cfd/future/index/equity), subyacente de opciones, de barras y si es **proxy** |
| `options_underlying`, `options_fallback_used` | cadena realmente usada; `true` si el índice no tenía datos y se usó el ETF |
| `spot`, `spot_source`, `spot_estimated` | `aggregates` = precio negociado; `options_parity`/`options_max_oi` = **estimado** |
| `chain` | contratos, vencimientos, cobertura de IV y OI, % de IV rellenada |
| `bars_symbol`, `bars_source`, `bars_session`, `bars_last_ts` | barras usadas, fuente, sesión y hora de la última barra (hora NY) |
| `estimated` | qué partes son estimaciones y con qué método |
| `warnings` | avisos (proxy, datos desactualizados, duplicados, respaldo gratuito…) |
| `strike_bucket` | ancho del tramo si se agruparon strikes |
| `generated_at`, `cache_age_s`, `timezone`, `status` | hora de cálculo (UTC), edad en caché, zona del mercado, `ok`/`degraded` |

## Instrumentos

| Pedido | Opciones | Barras / volumen | Nota |
|---|---|---|---|
| SPX500 / US500 | SPX (si falla → SPY) | SPY | proxy |
| NAS100 / US100 | NDX (si falla → QQQ) | QQQ | proxy |
| US30 | DIA | DIA | DJX casi no tiene liquidez |
| XAUUSD | GLD | GLD | el oro al contado no tiene opciones |
| WTI / USOIL | USO | USO | escala de precio distinta al barril |
| Futuros (ES, NQ, YM, CL, GC…) | índice/ETF asociado | ETF | proxy |
| Índices (SPX, NDX, RUT…) | el índice | su ETF | los índices no tienen volumen |

## Cadena de opciones

- Solo vencimientos **≥ hoy** (hora de Nueva York), ordenados por vencimiento.
- Strikes dentro de **±12 % del spot** (±25 % en Net Drift).
- Se completan exactamente `max_expiries` vencimientos (el siguiente, incompleto, se descarta).
- IV absurda (≤ 1 % o > 500 %) se descarta; los huecos se rellenan con la **mediana del mismo vencimiento**. Sin ninguna IV real la cadena se rechaza (antes se usaba un 22 % fijo).
- `T` (años) = max(días hasta vencimiento, 1) / 365, con `r = 4,5 %` y `q = 0` (sin cambios respecto a la versión anterior).

## Modo pro con 15 min de retraso (plan actual: Options Starter + Basic)

Todo el motor trabaja con los datos que da el plan actual, sin contratar nada más, y declara el retraso en `meta.data_delay_min` (15).

**Volatilidad implícita desde el precio.** Cuando Massive no trae la IV de un contrato, se calcula invirtiendo Black-Scholes sobre su precio real (mid bid/ask; si no hay, el último). Se usa bisección de 80 iteraciones entre 1 % y 500 %, con el mismo `T`, `r` y `q` que las griegas. Si el precio no es coherente (≤ valor intrínseco descontado o ≥ cota superior), no se fuerza: queda la mediana del vencimiento o NaN. `meta.chain.iv_sources` indica el % de IV del proveedor, calculada (`quotes`), por mediana o sin dato.

**Precio del subyacente (orden de calidad):**
1. barra de 1 min de hoy (agregados) — precio negociado;
2. subyacente del snapshot de opciones;
3. paridad put-call con las cotizaciones de opciones (estimado, mismo retraso que la cadena). Si el spot inicial es burdo (strike con más OI o cierre de ayer), se refina por paridad con la propia cadena cargada (strikes ±4 % de los 2 primeros vencimientos, mediana de `C − P + K·e^(−rT)`) antes de calcular la IV y las griegas (`options_parity_chain`);
4. cierre de ayer (planes Basic) — estimado y viejo;
5. strike con más open interest — estimación burda.

Antes, el cierre de ayer se marcaba como "precio negociado".

**Barras intradía.**
- **Caché compartida:** una descarga por (símbolo, intervalo, periodo) cada 60 s (`PROFITLAB_BARS_TTL`), para todas las vistas y usuarios, con un solo hilo descargando.
- **Fuente más reciente:** se usa la primera fuente que tenga la sesión esperada. Si Massive (Basic) solo trae hasta ayer, se pasa a Yahoo.
- **Último dato bueno:** si todas las fuentes fallan, se sirve el último válido con aviso.
- **Cortocircuito:** si el plan no da la barra de hoy, Massive no se vuelve a consultar en 10 minutos (`PROFITLAB_INTRADAY_COOLDOWN`), para no frenar las respuestas con los reintentos del límite de 5 llamadas/min.

**Diagnóstico público:** `GET /api/health?probe=SPX500` indica el subyacente usado, el motivo del sustituto, el origen del spot, las fuentes de IV y las barras (fuente, sesión y errores). No incluye datos de usuarios.

## GEX / DEX (Gamma & Flow, Espectro 2D/3D, GEX Heatmap)

Convención de signo: dealers **cortos en calls y largos en puts**.

```
GEX_contrato = signo × gamma_BS × OI × 100 × spot² × 0,01        signo = +1 call, −1 put   [USD por 1 % de movimiento]
DEX_contrato = signo × delta_BS × OI × 100 × spot                 signo = −1 call, +1 put   [USD de delta]
```

Se suman por strike o por (strike, vencimiento). En el Espectro 3D la **altura** se comprime con `tanh(valor / p88)` para que un strike extremo no aplaste al resto; el **color** muestra el valor real.

## Delta Surface (reemplazada en esta versión)

**Antes:** delta teórico de una opción hipotética ATM sobre una rejilla de precio ±15 % × 1–60 días con una sola IV. Como el delta solo depende de spot/strike y σ√T, la superficie era casi idéntica en todos los activos y no usaba open interest.

**Ahora:** exposición delta real de los dealers, `DEX` por **strike × vencimiento** (8 vencimientos, ±24 pasos de strike), opción `net` (calls + puts), `call` o `put`. Sin open interest no se calcula.

## Agrupación de strikes

Si la ventana tiene más de 40 strikes, se agrupan en tramos "redondos" (paso base × 1, 2, 2,5, 5, 10…) y se **suma** la exposición del tramo. Conserva el total exacto y evita el patrón en dientes de sierra de índices como SPX, donde el open interest se concentra en strikes redondos.

## Volume Profile

Estimación desde velas OHLCV (declarada en `meta.estimated.volume_by_price`): el volumen de cada vela se reparte **uniformemente** entre los niveles que abarca su rango [low, high]. El proveedor no entrega volumen negociado en cada precio.

- **POC:** nivel con más volumen.
- **Value Area (70 % por defecto):** desde el POC se añade el nivel vecino con más volumen hasta alcanzar la fracción pedida. VAH y VAL son sus bordes.
- **HVN:** máximo local del perfil suavizado (media de 3 niveles) con volumen ≥ 1,25 × la media.
- **LVN:** mínimo local con volumen ≤ 0,5 × la media, solo entre zonas con volumen.
- **Rango:** `sessions=1` (sesión), `5` (semana) o `N` (personalizado). 1 sesión usa velas de 1 minuto; varias, de 5 minutos.
- Sesión regular **09:30–16:00 hora de Nueva York**. Antes era 08:00–15:00 sobre timestamps UTC (Massive) o locales (Yahoo), lo que dejaba el perfil vacío o con premercado.
- Índices y CFD usan el volumen de su ETF. Sin volumen → error "sin volumen", nunca un perfil vacío dibujado.

## Volatility Drift (fórmula conservada)

```
r_t   = ln(C_t / C_{t−1})                                  velas de 1 minuto, sesión regular
ARV_t = desv_muestral(r_{t−w+1..t}) × √(252 × 390) × 100   [% anual], w = 20 minutos por defecto
IV    = IV ATM del primer vencimiento (%)
```

Añadido sin cambiar la fórmula: dirección del drift (cambio de ARV en la última ventana: `up` si > +0,5 puntos, `down` si < −0,5, si no `flat`) y la diferencia ARV − IV. Sin IV real, `iv = null` (antes, 20 % fijo).

## Net Drift (fórmula conservada, curva etiquetada)

- **Totales reales:** `prima = volumen_día × precio_contrato (mid, o último) × 100`, sumada por calls y por puts en 12 vencimientos y strikes ±25 %. Antes eran 4 vencimientos con tope de 500 contratos.
- **Curva intradía estimada** (`meta.estimated.curve`): sin operaciones de opciones con hora, el total se reparte por minuto con `w_call ∝ volumen_barra × (0,5 + 0,5·tanh(r/(1,2σ)))` y `w_put ∝ volumen_barra × (1 − …)`, y se acumula. El punto final es el total real; la forma es un modelo.

## Frescura y validación

- Barras duplicadas o con high < low se descartan (con aviso).
- Con el mercado abierto, una última barra con más de 20 minutos marca "datos desactualizados".
- Mercado abierto sin barras de hoy: se avisa que se muestra la sesión anterior.
- El proveedor `demo` (datos simulados) y el modo `PROFITLAB_DEMO` (sin control de acceso) están **bloqueados en producción** (`RENDER` o `PROFITLAB_ENV=production`).

## Pruebas

`tests/test_motor_auditoria.py` (26 pruebas con datos fijos y reproducibles): instrumentos, zona horaria, filtros de la cadena, IV sin constantes, sesión, aislamiento entre activos y caché, cálculo manual de una celda DEX, linealidad en el OI, Volume Profile, HVN/LVN, Volatility Drift contra la fórmula, Net Drift contra los totales y agrupación de strikes. Ejecutar con `pytest -q`.
