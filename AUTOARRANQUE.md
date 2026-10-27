# 🚀 Guía de Servidor Local y Autoarranque (Windows)

Este conjunto de ejecutables y scripts permite que la **API local de IA (AURA)** y su **túnel público seguro (ngrok)** se inicien automáticamente en segundo plano cada vez que el equipo se reinicie o se encienda, manteniendo la API disponible 24/7 sin necesidad de abrir terminales manualmente.

> [!NOTE]
> Para especificaciones de arquitectura completas, diagramas de flujo de arranque, topología de red, presupuestos de VRAM y detalles del supervisor Watchdog, consulta el **[Manual Técnico de Especificaciones](file:///c:/Users/aleja/Desktop/Proyectos/modelo/MANUAL_TECNICO_SERVIDOR.md)**.

---

## 📁 Archivos Ejecutables Creados

Todos los archivos ejecutables están en la raíz del proyecto para uso con doble clic:

| Archivo | Función |
| :--- | :--- |
| **`instalar_autoarranque.bat`** | **Instalador de 1 Clic**: Registra el inicio automático en Windows (carpeta de Inicio y Tarea Programada) para que arranque al encender/reiniciar el PC. |
| **`estado_servidor.bat`** | **Diagnóstico en Vivo**: Muestra si la API local (`:8000`), el túnel ngrok y el autoarranque están activos, y muestra los últimos logs. |
| **`detener_servidor.bat`** | **Detener Servidor**: Apaga el servicio, uvicorn y ngrok limpiamente. Útil cuando necesitas liberar la GPU (RTX 3050) para reentrenar modelos. |
| **`iniciar_servidor.bat`** | **Lanzador Interactivo**: Inicia el servidor mostrando una consola con logs en vivo (ideal para depurar o hacer pruebas). |
| **`iniciar_servidor_silencioso.vbs`** | **Lanzador Silencioso**: Inicia el servidor en segundo plano sin mostrar ninguna ventana de consola negra. Es el que ejecuta Windows al encender. |
| **`desinstalar_autoarranque.bat`** | **Desinstalador**: Desactiva el autoarranque en Windows de forma limpia. |
| **`servidor_daemon.ps1`** | **Demonio y Watchdog**: El motor supervisor que cuida que la API y el túnel nunca se caigan, reintentando si se corta internet o reiniciando si fallan. |

---

## ⚙️ ¿Cómo funciona tras reiniciar o encender el equipo?

1. **Al iniciar sesión en Windows**, se ejecuta silenciosamente `iniciar_servidor_silencioso.vbs`.
2. **Espera de Red Inteligente**: El script verifica la conexión a Internet (reintentando hasta que el Wi-Fi o Ethernet se conecten) para evitar que ngrok falle al arrancar.
3. **Carga del Modelo en GPU**: Inicia `api.py` con FastAPI/uvicorn y carga los pesos del modelo en VRAM con aceleración CUDA.
4. **Verificación de Salud**: Espera a que el endpoint `http://127.0.0.1:8000/health` responda HTTP 200.
5. **Apertura del Túnel ngrok**: Conecta el dominio fijo asignado:
   ```text
   https://expend-chaplain-degraded.ngrok-free.dev
   ```
6. **Supervisor Activo (Watchdog)**: El script se queda monitoreando en segundo plano. Si por alguna razón la API o ngrok se cierran, los reinicia automáticamente.

---

## 📝 Ubicación de los Registros (Logs)

Todos los eventos quedan registrados en la carpeta `logs/`:
- `logs/servidor.log`: Registro general del supervisor (inicios, reinicios, caídas, estados).
- `logs/api.log`: Salida estándar de la API uvicorn y FastAPI.
- `logs/api_error.log`: Errores o excepciones de la API.
- `logs/ngrok.log`: Estado de conexiones y peticiones del túnel ngrok.

---

## 💡 Consejos de Uso

> [!IMPORTANT]
> **Antes de Entrenar Modelos**:  
> Como la tarjeta gráfica RTX 3050 cuenta con 4 GB de VRAM, no se puede entrenar con la API encendida. Simplemente haz doble clic en **`detener_servidor.bat`**, realiza tu entrenamiento (`src/train_sft.py` o `src/train_dpo.py`), y al terminar vuelve a ejecutar **`iniciar_servidor.bat`** o reinicia tu PC.

> [!TIP]
> **Comprobar el estado desde tu celular u otro equipo**:  
> Abre en cualquier navegador: `https://expend-chaplain-degraded.ngrok-free.dev/health`  
> Si devuelve `{"status":"ok", ...}`, tu servidor está 100% operativo en internet.
