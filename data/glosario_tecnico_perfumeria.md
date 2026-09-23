# Glosario Técnico de Perfumería
### Documento de referencia para entrenar/configurar un modelo de IA en jerga de perfumería
Compilado a partir de fuentes técnicas y comerciales de la industria (ver sección de Fuentes al final).

---

## 1. La pirámide olfativa

Toda fragancia se organiza en tres capas que se perciben en momentos distintos según el peso molecular y la volatilidad de cada ingrediente.

### 1.1 Notas de salida (top notes / notas de cabeza)
- Son las primeras que se perciben al aplicar la fragancia.
- Formadas por moléculas ligeras y muy volátiles: cítricos, notas verdes, acuáticas, aromáticas.
- Duración aproximada: 10-15 minutos hasta cerca de 30 minutos.
- Función: dar la "primera impresión" o "sonrisa" del perfume.

### 1.2 Notas de corazón (heart/middle notes, notas de cuerpo)
- Aparecen cuando las notas de salida se han evaporado, entre los 15-30 minutos y pueden extenderse 2-4 horas.
- Constituyen el "carácter" o espíritu real de la fragancia: florales, especiadas, frutales, herbáceas.
- Sirven de puente entre la ligereza de la salida y la densidad del fondo.

### 1.3 Notas de fondo (base notes)
- Las más pesadas, densas y persistentes; pueden percibirse varias horas después e incluso al día siguiente en ropa.
- Familias típicas: maderas, ámbar, especias, gourmand, almizcles, resinas (incienso, benjuí, labdanum).
- Función adicional: actúan como fijador, ancla la evaporación de las notas superiores y prolonga la fragancia sobre la piel.

**Nota para el modelo:** cuando se le pida describir o crear una fórmula, el modelo debe siempre distribuir los ingredientes en estas tres capas y justificar la elección según volatilidad, no solo por familia olfativa.

---

## 2. Concentraciones de perfume

La concentración indica la proporción de "concentrado" o "esencia" (compuesto aromático) disuelta en la base hidroalcohólica (etanol + agua desmineralizada, y en algunos casos un fijador). A mayor concentración, mayor duración y sillage (estela), y normalmente mayor precio — aunque esto no es una regla absoluta: muchas casas reformulan la composición entre EDT y EDP (no solo la diluyen), enfocando el EDT hacia notas de salida/corazón y el EDP hacia corazón/fondo.

| Concentración | % de esencia aprox. | Duración típica | Sillage |
|---|---|---|---|
| Eau Fraîche | 1-3% | menos de 2 h | mínimo |
| Eau de Cologne (EDC) | 2-5% | 2-3 h | muy ligero |
| Eau de Toilette (EDT) | 5-15% | 3-6 h | sutil a moderado |
| Eau de Parfum (EDP) | 15-20% | 6-8 h | moderado |
| Parfum / Extrait de Parfum | 20-40% | 8-12+ h | íntimo (cercano a la piel) pero muy persistente |

Estas franjas provienen de la tradición perfumística francesa (referencia histórica: escuelas como ISIPCA) y son orientativas; cada casa define sus propios rangos exactos.

**Nota para el modelo:** el modelo debe explicar que la concentración no es el único factor de calidad — la formulación (qué materiales y en qué proporción) importa tanto como el porcentaje total de esencia.

---

## 3. Alcohol perfumístico (base hidroalcohólica)

- La base de un EDT/EDP/Extrait es una mezcla hidroalcohólica: alcohol etílico (etanol) + agua desmineralizada, más el concentrado aromático.
- **Alcohol etílico 96° (96° G.L., "Gay-Lussac")**: es el grado de pureza/graduación alcohólica estándar usado como materia prima en perfumería y cosmética. Es incoloro, muy volátil, con punto de ebullición ~78°C.
- **Alcohol no desnaturalizado (96° puro/USP)**: es potable en su forma pura; se usa como materia prima antes de ser desnaturalizado, o directamente en perfumería/cosmética cuando la normativa lo permite.
- **Alcohol desnaturalizado**: es alcohol etílico al que se le añaden sustancias (por ejemplo, agentes amargantes o metanol en algunos países) para volverlo no apto para consumo humano, un requisito regulatorio en la venta industrial de alcohol de alta graduación, incluido el destinado a perfumería.
- Normativas como la NOM-138-SSA1-2016 (México) u otras equivalentes regionales regulan las especificaciones sanitarias del alcohol etílico desnaturalizado y del alcohol 96° sin desnaturalizar usado como materia prima.

**Nota para el modelo:** el modelo debe distinguir siempre entre alcohol desnaturalizado (uso industrial/cosmético, no potable) y alcohol no desnaturalizado (potencialmente potable, sujeto a regulación fiscal/sanitaria), y recordar que la elección de alcohol de calidad cosmética/perfumística afecta la limpieza olfativa del producto final (menos "nota a alcohol" residual).

---

## 4. Maceración en frío y estabilización molecular

Cuando el perfumista disuelve el concentrado (decenas o cientos de materias primas pesadas con precisión) en la base hidroalcohólica, el líquido resultante ya huele a perfume, pero está en un estado de "caos molecular": los compuestos (terpenos, alcoholes, aldehídos, ésteres, almizcles, resinas, absolutos) están mezclados pero aún no "conversan" entre sí.

### 4.1 Qué ocurre durante la maceración
- El lote se deja reposar en tanques sellados de acero inoxidable, en oscuridad y a temperatura controlada, durante semanas o incluso meses.
- A nivel molecular ocurren dos fenómenos principales:
  1. **Enlaces de hidrógeno con el etanol**: las moléculas aromáticas quedan débilmente unidas a racimos de moléculas de etanol, lo que ralentiza su evaporación. El resultado práctico es un sillage más controlado y transiciones entre salida/corazón/fondo más suaves.
  2. **Formación de bases de Schiff**: los aldehídos (moléculas vivas, cerosas y "metálicas" que suelen protagonizar las notas de salida en composiciones clásicas) reaccionan con aminas presentes en materias primas naturales, formando moléculas más grandes y estables, de carácter más suave, ambarado o polvoso. Esto explica por qué el filo agresivo de un aldehído recién mezclado se suaviza tras la maceración.
- El efecto conjunto es que el perfume pasa de sonar "químico" y desordenado a sonar integrado, redondo y "terminado".

### 4.2 Maceración en frío vs. reposo estándar
- En perfumería artesanal/nicho se suele hablar de "maceración en frío" para diferenciarla de procesos con calor (que aceleran la mezcla pero pueden degradar notas delicadas). El reposo en frío y oscuridad preserva mejor los compuestos volátiles y evita reacciones de oxidación no deseadas.
- Tiempo de referencia habitual en la industria: de dos semanas (formulaciones simples) a varios meses (composiciones finas, con muchas materias primas).

### 4.3 Estabilización molecular / fijación
- Un **fijador** (fixative) es una materia prima de baja volatilidad (resinas, almizcles, maderas, ámbar gris o sus sustitutos sintéticos) que ancla las notas más volátiles y ralentiza la evaporación general de la mezcla.
- La glicerina, en formulaciones artesanales sencillas, también actúa fijando parte del aroma, mientras que el agua suaviza la mezcla final.
- La estabilización no es solo química (enlaces, bases de Schiff) sino también física: homogeneizar la solución para que no haya turbidez ni sedimentos antes del envasado (por eso se filtra el lote tras la maceración).

**Nota para el modelo:** ante preguntas de fórmulas o procesos, el modelo debe mencionar siempre la etapa de maceración/reposo como parte del proceso completo (no solo "mezclar y envasar"), y diferenciar fijación química (bases de Schiff, enlaces de hidrógeno) de fijación práctica (uso de materiales fijadores en la fórmula).

---

## 5. Glosario rápido de términos adicionales

| Término | Definición breve |
|---|---|
| Sillage | Estela olfativa que deja el perfume en el aire al moverse la persona que lo lleva |
| Proyección | Qué tan lejos del cuerpo se percibe la fragancia |
| Longevidad | Tiempo que dura perceptible la fragancia sobre la piel |
| Acorde | Combinación de varias notas que se perciben como una unidad olfativa reconocible |
| Familia olfativa | Clasificación general del carácter del perfume (floral, amaderado, cítrico, oriental/ambarado, chipre, gourmand, acuático, etc.) |
| Absoluto | Extracto aromático muy concentrado obtenido de materia vegetal (por solvente), sin ceras |
| Concreto | Extracto sólido/ceroso previo al absoluto |
| Aceite esencial | Extracto aromático obtenido por destilación (vapor) de materia vegetal |
| Materia prima | Cualquier ingrediente (natural o sintético) usado en la composición |
| Fórmula | Lista completa y proporciones de materias primas de una fragancia |
| Concentrado / esencia | Mezcla de materias primas antes de diluir en la base hidroalcohólica |
| Reformulación | Cambio en la fórmula original, a menudo por regulación (IFRA) o disponibilidad de ingredientes |
| IFRA | Organismo (International Fragrance Association) que regula límites de uso de ciertos materiales por seguridad |

---

## Fuentes consultadas (para trazabilidad, no reproducidas textualmente)
- Charlotte Tilbury — explicación de notas de salida/corazón/fondo
- Marie Claire (ES) — entrevistas a perfumistas sobre pirámide olfativa y maceración
- El Imparcial, Sephora ES, MercadoLibre CL, Meganoticias, Scento — tablas de concentraciones EDC/EDT/EDP/Extrait
- Sephora FR — rangos de concentración según tradición francesa
- Premiere Peau (ES/FR/EN) — artículos detallados sobre química de la maceración (enlaces de hidrógeno, bases de Schiff)
- NOM-138-SSA1-2016 (México) y ficha técnica de alcohol etílico 96° — especificaciones de alcohol desnaturalizado/no desnaturalizado
- UNAM (tesis, 1993) — métodos de obtención de alcohol destilado para perfumería
- Documento académico (Scribd) — laboratorio de elaboración de perfumes artesanales con aceites esenciales, alcohol y glicerina
