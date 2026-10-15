# Pendientes en la tienda (AltaDensidadPAGE)

Cosas que se encontraron trabajando en el modelo y que hay que hacer en el repo de la tienda.
Prioridad baja: primero el modelo. Al hacer uno, se marca `[x]` con la fecha y el commit.

## Widget AURA (`src/tienda/Aura.jsx`)

- [ ] **Respuestas fijas que saltan la IA.** `respuestaLocalDirecta` responde sin consultar al modelo todo mensaje con palabras como «envío», «pago», «tarjeta», «duración», «feromonas» (`KNOWLEDGE_BASE`). Usar esos textos solo en *modo básico* (IA caída) y dejar que el modelo responda lo demás. Excepción razonable: los saludos solos con sus chips.
  - Visto el 2026-10-07: «te paso mi tarjeta…» y «hacen envíos a Cali» los respondió el widget, no AURA.
- [ ] **Textos fijos desactualizados** (`KNOWLEDGE_BASE`, sirven para el modo básico):
  - Duración: dice «+12 horas» y «12 a 16 horas»; la decisión es **de 8 a 12 horas en piel**.
  - Pagos: falta **Addi y Sistecrédito** (financiación, coordinando con un asesor por WhatsApp). Mercado Pago y transferencia se mantienen.
  - Feromonas: «microcápsulas de feromonas … de alta afinidad» promete más de lo que AURA puede decir (no prometer efectos).
  - Entrega el mismo día (decisión del 2026-10-14): ya no es «si se confirma antes de las 9 a.m.». En **Medellín y el Área Metropolitana** llega el mismo día si el pedido se confirma **dentro de la jornada laboral**; cerca del cierre no se garantiza y sale al siguiente día hábil (se puede coordinar por WhatsApp). Revisar también la página de envíos y el checkout si muestran la regla de las 9 a.m.
  - Aplicación (decisión del 2026-10-14): **mínimo 6 atomizaciones repartidas en pecho, hombros y brazos** (antes decía 3 o 4 en cuello, pecho y muñecas).
- [ ] **Respuesta más legible: intro → tarjetas → cierre.** Hoy toda la respuesta va en una burbuja con la lista de productos en viñetas y debajo se repiten los mismos productos como tarjetas.
  - Partir `data.response`: líneas antes del primer `- **Producto**` = burbuja de intro; las líneas de producto se quitan del texto; líneas después = burbuja de cierre (debajo de las tarjetas).
  - Pasar a cada tarjeta la frase de AURA de su línea (lo que va después de `·`, p. ej. «para hombre, amaderado y aromático con…») y mostrarla bajo el precio.
  - Viene de la revisión del usuario: «responde con unas cards muy bacanas pero antes en un texto totalmente plano, sin organizar los párrafos».

## Backend (`backend/routes/chatbot.js`)

- [ ] Modo `openai`: la comprobación de estado llama `GET /v1/models`, que la API propia de AURA no tiene. Solo importa si algún día se usa ese modo con la API de AURA (hoy se usa `nativo`).
