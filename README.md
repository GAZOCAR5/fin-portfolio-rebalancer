# Portfolio Manager

Módulo de portafolio para una app de inversiones personales. Un `Portfolio`
contiene una colección de acciones y una asignación objetivo (por ejemplo,
40% META / 60% AAPL). Su método `rebalance()` indica qué acciones vender y
cuáles comprar para llegar a esa asignación.

```python
provider = InMemoryPriceProvider({"META": "500", "AAPL": "200"}) #Editable con stocks extra en demo.py (ajustando después los parámetros de portfolio)
meta, aapl = Stock("META", provider), Stock("AAPL", provider)

portfolio = Portfolio(
    holdings=[Holding(meta, 10), Holding(aapl, 10)],        # hoy: 71% / 29%
    allocations=[Allocation(meta, "0.4"), Allocation(aapl, "0.6")],
)

plan = portfolio.rebalance()                   # acciones fraccionadas (por defecto)
plan = portfolio.rebalance(whole_shares=True)  # acciones enteras, el resto queda en caja
```

| Modo | Órdenes | Caja final | Pesos finales |
|---|---|---|---|
| Fraccionado | SELL 4.4 META, BUY 11 AAPL | $0 | 40% / 60% |
| Acciones enteras | SELL 5 META, BUY 11 AAPL | $300 (4.3%) | 35.7% / 60% |

## Cómo ejecutarlo

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m pytest
python -m examples.demo
```

Requiere Python 3.11+ y no tiene dependencias en tiempo de ejecución.

## Estructura

```
portfolio_manager/
├── stock.py       Stock + PriceProvider (punto de integración con datos de mercado)
├── portfolio.py   Holding, Allocation, Portfolio y el algoritmo de rebalance
└── orders.py      TradeOrder / RebalancePlan: la salida estructurada
```

Las dependencias van en un solo sentido: `portfolio` usa `stock` y `orders`,
y ninguno de esos dos módulos conoce al portafolio.

## El algoritmo

1. **Tomar un solo snapshot de precios.** Se llama a `current_price()` de cada
   acción exactamente una vez en el t=0. Si se le volviera a pedir el precio al proveedor
   a mitad del cálculo, el plan podría mezclar precios de momentos distintos.
2. **Valor total** = caja + Σ cantidad × precio.
3. **Valor ideal por acción** = valor total × peso objetivo. Una acción que se
   tiene pero no está en la asignación tiene peso 0, así que se vende completa.
4. **Redondear hacia abajo cada cantidad ideal** a un lote transable: 0.000001
   en modo fraccionado y 1 en modo de acciones enteras. Redondear hacia abajo
   garantiza que el plan nunca asigne más del 100% del portafolio.
5. **Relleno greedy.** El redondeo deja caja ociosa. Mientras alcance para
   algún lote, se compra un lote más de la acción que está más lejos por debajo
   de su valor ideal.
6. **Órdenes** = cantidad objetivo − cantidad actual. Las ventas van primero
   porque con lo que se obtiene de ellas se financian las compras.

Los dos modos corren el mismo código; solo cambia el tamaño del lote. En modo
fraccionado, lo que sobra del paso 4 son a lo más unos centavos. En modo de
acciones enteras es dinero real, y queda como caja en el plan.

### Por qué greedy en modo de acciones enteras

Después de redondear hacia abajo, a cada acción le falta menos de un lote para
llegar a su valor ideal. Por eso, un lote extra siempre la deja por sobre su
objetivo. Hay dos consecuencias:

- Cada acción recibe **como máximo un lote extra**, así que el ciclo corre a lo
  más N veces.
- Cada compra mueve caja ociosa hacia una acción que estaba bajo su objetivo.
  Eso siempre reduce la desviación total respecto de la asignación, contando la
  caja como un objetivo de 0%.

Encontrar la mejor combinación posible de acciones enteras es un problema de la
mochila (knapsack). Sería mucho más complejo a cambio de ganar una fracción del
valor de una acción, por lo tanto se elige greedy para el ejercicio.

El test aleatorio de `tests/test_rebalance.py` verifica estas garantías en
1.000 portafolios generados:

- La caja nunca queda negativa y no aparece ni desaparece dinero.
- La caja ociosa siempre es menor que un lote de la acción más cara.
- Ninguna acción termina más de un lote por sobre su valor ideal.

## Decisiones y supuestos

- **"Current Price method that receives the last available price"** se
  interpreta como que *devuelve* el último precio disponible.
- **`whole_shares` asume que los holdings actuales son enteros.** Lo que se
  redondea a entero es la *posición final*, no la orden (orden = objetivo −
  actual). Si el portafolio ya parte con fracciones, por ejemplo por dividendos
  reinvertidos, un split no entero o un uso previo del modo fraccionado, las
  órdenes también salen fraccionarias. Con 0.5 acciones y un objetivo de 1, la
  orden es `BUY 0.5`.

  La solución es redondear la orden en vez de la posición, conservando el resto
  fraccionario que ya se tiene. Eso obliga a ajustar también el greedy, que hoy
  razona sobre posiciones. `_fund_buys` seguiría protegiendo la caja, así que el
  ajuste no debería provocar errores en cascada, pero para este ejercicio se
  deja identificado y no implementado.
- **`Decimal`, no `float`.** Es dinero: `0.1 + 0.2 != 0.3` en punto flotante
  binario. Los `float` de entrada se convierten pasando por `str()`.
- **La fuente de precios se inyecta.** `Stock` depende de un protocolo
  `PriceProvider` de un solo método. Conectar una API real de datos de mercado
  es crear una clase nueva con un método `get_last_price(ticker)`, sin tocar
  `Stock`.
- **El núcleo es una función pura.** `compute_rebalance()` recibe diccionarios
  simples y no hace I/O. `Portfolio.rebalance()` solo toma el snapshot y le
  delega el cálculo.
- **Fallar rápido ante entradas inválidas.** El constructor de `Portfolio`
  rechaza:
  - pesos que no suman 1 (±0.000001);
  - pesos, cantidades o caja negativos;
  - tickers duplicados.

  Los precios ≤ 0 se rechazan con el mismo principio, pero en
  `Stock.current_price()`, que es donde entra el dato de mercado. Eso ocurre al
  rebalancear y no al construir el portafolio, porque el precio no existe hasta
  que se consulta.

  Una asignación que suma 90% se trata como un bug, no se normaliza en
  silencio.
- **`min_trade_value` (opcional).** Omite órdenes demasiado pequeñas para
  justificar sus comisiones. Si una *venta* omitida estaba financiando una
  compra, esa compra se recorta. Al final es para que en margen de la operación no se lo coma el spread/comisión en lo que se acercaría a un trade real.
- **El plan es una salida estructurada.** Cada orden guarda el precio con que
  se calculó, así quien la ejecute puede detectar cuánto se movió el mercado
  antes de ejecutarla. `to_dict()` serializa los `Decimal` como strings para no
  perder precisión en JSON, entregando así los pasos a seguir y el estado de resultado a través de un paquete event-friendly.

## Fuera de alcance (posibles siguientes pasos)

- **Caja como objetivo propio** (por ejemplo, "mantener 5% en caja"). Hoy la
  caja es solo el remanente del redondeo.
- **Comisiones, impuestos, tamaños de lote por broker y montos mínimos de
  orden.**
- **Rebalance por bandas de tolerancia.** Rebalancear solo cuando alguna acción
  se desvía más de X% de su objetivo, en vez de converger siempre exacto.
- **Ejecución de órdenes y ejecuciones parciales.** El plan es una propuesta;
  ejecutarlo le corresponde a otro componente.

## Uso de LLMs

Esta solución se diseñó y escribió con ayuda de Claude (Claude Code). Las
conversaciones están en [`docs/llm-conversations/`](docs/llm-conversations/).

La arquitectura en tres módulos y las decisiones de modelo (fraccionado por
defecto, acciones enteras con el remanente en caja, redondeo hacia abajo y
greedy) fueron mías. La implementación la hizo Claude Code; después la revisé y
la probé con casos nuevos, como una acción que sale de la asignación (GOOG con
peso 0 en la demo).

Como siguiente paso, priorizaría modelar la caja como objetivo propio, porque
con acciones enteras deja de ser un simple remanente.