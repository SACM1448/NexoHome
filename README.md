# NEXO Home

Fase 2 · Entregable 2.3. Terminal con rostro animado, conversación temporal y estados conectados al orquestador local existente. Conserva permisos, concurrencia, panel, SQLite y HTTPS LAN. Sin voz, LLM, Telegram, domótica ni motor de actualizaciones.

## Rostro y experiencia del terminal — entregable 2.3

`/terminal` combina un rostro dibujado con HTML/CSS, mensajes en burbujas y entrada textual. `web/css/terminal.css` aísla el diseño del panel; reutiliza su paleta. `web/js/terminal.js` conserva vinculación, Bearer, consulta de identidad y estado autorizado. No cambia backend, contrato, CSP, dependencias, migraciones ni Compose. En la sección «Vinculación del terminal» se puede consultar identidad o olvidar la credencial; no ofrece administración.

La máquina explícita `setRobotState(state)` admite `idle`, `listening`, `processing`, `speaking`, `success`, `error`, `resource_busy`, `disconnected` y `unpaired`. Solo el envío real activa `processing`; una respuesta correcta activa `success` y vuelve a reposo tras 1,8 s. HTTP 409 con `resource_busy` tiene expresión propia; `terminal_busy` muestra el conflicto en texto y estado de error. Los demás errores HTTP permanecen visibles. HTTP 401 elimina la credencial y el historial y abre la vinculación; 403 conserva identidad. No reintenta, no encola y bloquea dobles envíos. Timeout de transporte: 15 s; puede haber resultado desconocido y se advierte que debe consultarse antes de repetir manualmente. Una generación de identidad impide mostrar respuestas tardías tras olvidar o cambiar de terminal.

Los veinte mensajes más recientes existen únicamente en el DOM, sin almacenamiento de conversación ni logs. Recargar borra el historial visual; el contexto temporal del servidor conserva los límites y caducidad anteriores. La credencial sigue usando exclusivamente la clave `nexo-terminal` de `sessionStorage`, con alternativa en memoria si está bloqueado; nunca se muestra. Olvidar limpia también el campo y los mensajes. Todo contenido variable usa `textContent`.

Accesibilidad: etiquetas, enlace para saltar al mensaje, envío con Enter, controles nativos, foco visible, estado y última respuesta con `aria-live`, errores explicados en texto y botones de al menos 44 px. El historial no anuncia por duplicado la última respuesta. CSS respeta `prefers-reduced-motion`; las animaciones quedan pausadas cuando la pestaña está oculta. Sin timers de alta frecuencia, imágenes del robot, Canvas, audio, CDN ni bibliotecas nuevas.

**Preparación para 2.4:** `listening` y `speaking` solo están definidos, sin activación en el flujo de texto. El futuro adaptador de voz podrá usar `setRobotState`; la configuración de idioma/voz sigue en el contrato de terminal existente. Captura, STT, TTS, selección de voz e interrupción de reproducción requieren el entregable 2.4 y su autorización. No hay controles de voz simulados.

**Verificación:** `node --test tests/test_terminal_ui.cjs tests/test_terminals_admin_ui.cjs` cubre estados, vinculación, revocación, conflictos, red, timeout, respuesta inválida, historial, inyección y dobles envíos con DOM/transporte simulados; además revisa reglas de movimiento reducido y semántica de teclado. Las pruebas Python comprueban entrega de assets y conservación de CSP, además de seguridad y orquestación previas. Resultados finales y límites de Docker/ARM64 en `PROGRESS.md`. Revisión real en navegador integrado con backend aislado: vinculación, Enter, foco con Tab, HTML literal y recarga sin historial; viewports simulados 1440×900, 1366×768, 768×1024, 390×844 y 320×568. Evidencia en `docs/validation/terminal-escritorio-2.3.jpg` y `terminal-movil-2.3.jpg`.

**Limitaciones:** sin pruebas físicas en Android/Raspberry, lector de pantalla ni teclado virtual real; no se midió RAM/CPU en ese hardware. En móvil la página permite desplazarse hacia el campo al abrir el teclado; no usa alturas fijas de pantalla ni bloquea el scroll. La desconexión se detecta al consultar/enviar y la revocación al siguiente acceso autorizado; no incorpora polling ni reconexión con reenvío automático. Se conserva el contenedor operativo anterior hasta un despliegue explícito; para instalar la imagen validada, usar el procedimiento de inicio documentado.

## Interacción de terminales — entregable 2.1

En `/terminal`, vincula una identidad con permiso `terminal.chat` usando el panel administrativo. Escribe `hola`, `estado` o `ayuda`. El controlador usa coincidencias locales explícitas, sin IA ni ejecución de acciones. Una segunda bienvenida usa el contexto temporal del mismo terminal; entradas desconocidas informan que las capacidades futuras no están disponibles. `estado` describe solo este servicio local, no verifica integraciones futuras. No requiere el permiso administrativo ni `terminal.status`.

`POST /api/v1/terminal/interact` requiere `Authorization: Bearer <credencial de terminal>` y JSON `{"text":"hola"}`. Solo acepta `text`; rechaza identificadores de otro terminal y campos adicionales. La identidad proviene exclusivamente de la autenticación existente. La cookie administrativa sola recibe 401. Todo `Origin` presente debe coincidir con `NEXO_ORIGIN`.

Ejemplo de respuesta 200 (identificadores ilustrativos, sin credenciales):

```json
{
  "request_id": "identificador-unico-generado-por-el-servidor",
  "terminal_id": "identidad-del-terminal-autenticado",
  "status": "completed",
  "message": "Hola. Soy NEXO Home.",
  "response_type": "text",
  "error": null
}
```

`request_id` es un UUID hexadecimal nuevo por intento, también en errores; no es una clave de idempotencia ni se admite reejecución automática. `status`: `completed` o `failed`. `response_type`: `text`, `unavailable` o `error`. En error se conserva la estructura y `error` contiene `{"code":"codigo_estable"}`. `terminal_id` puede ser nulo si el rechazo ocurre antes de entrar al controlador autorizado. Sin cuerpos, secretos ni detalles internos en errores. Respuestas sin caché. Contrato extensible por el orquestador futuro, sin implementar acciones, confirmaciones, audio o proveedores en 2.1.

| HTTP | Código de error | Motivo |
| --- | --- | --- |
| 401 | `invalid_credential` | No vinculado, revocado, expirado o credencial inválida; conserva `WWW-Authenticate: Bearer` |
| 403 | `forbidden` | Falta `terminal.chat` u origen rechazado |
| 409 | `terminal_busy` | Una solicitud del mismo terminal sigue procesándose; rechazo inmediato |
| 409 | `resource_busy` | Otra operación posee un recurso necesario; sin adquisición parcial |
| 409 | `confirmation_required` | Reserva de confirmación futura; ejecución bloqueada |
| 413 | `input_too_large` | Cuerpo superior a 32 KiB, incluso fragmentado |
| 422 | `invalid_input` | Texto inválido, excesivo o JSON/campos inválidos |
| 429 | `rate_limited` | Más de 20 solicitudes admitidas por terminal en ventana de 60 s; `Retry-After: 60` |
| 500 | `processing_error` | Error controlado del procesador; sin volcado de la excepción |
| 503 | `capacity_unavailable` | Capacidad de contextos agotada |
| 503 | `persistence_unavailable` | SQLite ocupado/no disponible durante controles de identidad o limpieza |
| 504 | `execution_timeout` | Tiempo de ejecución cooperativa agotado; sin reintento |

La UI muestra procesamiento, respuesta o error; no reintenta ni pone solicitudes en cola. Usa `textContent` para mostrar respuestas y no guarda mensajes en almacenamiento del navegador. Solo conserva la credencial mediante el mecanismo anterior de `sessionStorage`. El campo de entrada se vacía al enviar; recargar pierde la respuesta visible.

**Contexto y límites:** biblioteca estándar (`threading.Lock`, reloj monotónico, estructuras acotadas), sin dependencias nuevas. Hasta 128 contextos por proceso, 20 mensajes (10 pares completos) y 16 KiB de texto UTF-8 por contexto; elimina pares antiguos al superar límites. Hasta 2.000 caracteres por entrada; cuerpo JSON hasta 32 KiB para permitir escapes Unicode. El límite de texto retenido es aproximadamente 2 MiB globales, además de objetos Python y solicitudes en curso; no es una medición de RSS. Reutiliza el límite existente de Uvicorn de 64 conexiones/tareas concurrentes. Las estructuras compartidas se protegen con secciones críticas cortas; terminales distintos pueden procesar simultáneamente. Una solicitud del mismo terminal en curso recibe 409, sin bloqueos de recursos externos, colas ni reintentos.

Caducidad por inactividad: `NEXO_CONTEXT_TTL=900` segundos, configurable entre 60 y 86400, tanto en ejecución local como en ambos Compose. Limpieza diferida al siguiente acceso a la API de interacción, incluso con credencial rechazada; sin proceso residente adicional. En ausencia de tráfico pueden permanecer objetos caducados hasta ese ciclo, siempre dentro del límite global. Revocar por la API elimina inmediatamente el contexto; cambios externos en SQLite y credenciales expiradas se detectan en el siguiente ciclo. Una respuesta ya iniciada puede terminar después de revocar, pero no restaura el contexto eliminado. Se limpia al cerrar el servicio y se pierde tras reinicio.

**Un solo proceso/worker obligatorio:** el almacén en memoria garantiza consistencia únicamente dentro del proceso. La CLI ya fija `--workers 1`; no ejecutar varias réplicas ni workers compartiendo terminales. No se añade persistencia ni migración: mensajes nunca se escriben en SQLite, auditoría o logs. La sesión de autorización sigue siendo independiente del contexto.

**Reutilización:** FastAPI/Pydantic, autenticación y permisos de terminal, `TerminalContextScope`, transacciones SQLite, pytest/HTTPX y Compose existentes. Sus procedencias/licencias se conservan en la evaluación previa; no se incorporó software externo. No se necesita un nuevo ADR: se aplica la decisión aprobada de contexto temporal en memoria del monolito.

Pruebas: `python -m pytest -q` incluye aislamiento, caducidad, límites, Unicode, permisos, errores, concurrencia HTTP, revocación durante procesamiento y ausencia de conversaciones en SQLite/logs. `node --test tests/test_terminal_ui.cjs` comprueba envío, Bearer, estado, errores, dobles envíos y respuestas tardías con DOM/transporte simulados; no sustituye una revisión visual en navegador/dispositivos. `python tests/docker_smoke.py` comprueba HTTP real en Compose aislado, reinicio sin contexto y preservación de identidad, además de los controles existentes.

## Iniciar y comprobar

Desde `E:\NexoHome`, con Docker Desktop usando contenedores Linux:

```powershell
docker compose up --build -d
docker compose ps
Invoke-RestMethod -TimeoutSec 5 http://localhost:8000/api/v1/health
```

Abrir [NEXO Home](http://localhost:8000/). El contrato de salud es HTTP 200, `application/json`, con `{"status":"ok","service":"nexo-home"}`. Describe la disponibilidad del proceso, no servicios futuros. OpenAPI está en `/openapi.json`.

Detener y retirar el contenedor y la red del proyecto:

```powershell
docker compose down
```

Compose publica exclusivamente en `127.0.0.1`, sin acceso LAN/WAN. No abrir puertos externos. No requiere `.env` para iniciar; `.env.example` documenta puerto, origen, entorno y directorio local. Si cambias el puerto, ajusta también `NEXO_ORIGIN`. `localhost` y `127.0.0.1` son orígenes distintos. La configuración Python local se lee del entorno del proceso; solo Compose carga `.env` automáticamente.

## Migraciones e inicialización administrativa

El arranque Docker aplica `alembic upgrade head` mediante la CLI antes de aceptar tráfico. Para ejecutarlo explícitamente y crear el único administrador, desde una terminal interactiva:

```powershell
docker compose exec nexo python -m nexo.cli migrate
docker compose exec nexo python -m nexo.cli init-admin
```

Introduce usuario y contraseña cuando se soliciten. Usuario: 3–64 caracteres ASCII en minúsculas, números, `_`, `.` o `-`, comenzando por letra o número. Contraseña: 12–128 caracteres, letras y números; usa una contraseña larga y exclusiva. Se confirma sin eco, nunca se recibe como argumento ni por variable de entorno. La CLI falla si no dispone de entrada sin eco, o si ya existe administrador, incluso inactivo. No hay alta HTTP, credenciales predeterminadas ni segundo administrador. No introduzcas tu contraseña en el chat.

El volumen `nexo-home_nexo_data` conserva base de datos, sesiones y auditoría al recrear o retirar contenedores. `docker compose down` conserva datos; **`down --volumes` los elimina**. No uses este último contra el proyecto operativo. No incluyas el volumen en Git ni copias sin proteger. La contraseña definitiva la elige el operador; la validación automatizada crea un administrador aleatorio únicamente en un proyecto y volumen temporales.

## API administrativa

| Método y ruta | Contrato |
| --- | --- |
| `POST /api/v1/auth/login` | JSON `username` y `password`, con `Origin` exactamente igual a `NEXO_ORIGIN`; devuelve `username`, `expires_at` (Unix UTC) y `csrf_token`, y establece cookie |
| `GET /api/v1/auth/me` | Cookie válida; devuelve identidad, expiración original y token CSRF, sin extender sesión |
| `GET /api/v1/admin/status` | Cookie válida; devuelve `status` y `username` |
| `POST /api/v1/auth/logout` | Cookie válida, `Origin` permitido y cabecera `X-CSRF-Token` recibida en login/me; revoca sesión y elimina cookie, HTTP 204 |

El cliente debe mantener la cookie HttpOnly y conservar CSRF solo temporalmente. Ningún token debe escribirse en logs o informes. Toda futura mutación que use `require_admin_permission`/`require_admin_session` hereda validación de origen y CSRF. Los terminales no deben usar esta identidad. HTTP 401: credenciales uniformemente inválidas o sesión no válida; 403: origen/CSRF rechazado; 422: solicitud inválida sin reflejar datos; 429: límite de cinco verificaciones globales en 60 s; 503: persistencia o autenticación ocupada. No hay cola ni reintento automático. `Retry-After` es orientativo para el cliente.

La sesión expira absolutamente a los 60 minutos; cada nuevo login revoca la anterior. SQLite almacena solo digest del token y hash Argon2id de contraseña. La cookie usa HttpOnly, SameSite=Strict y Path=/; HTTPS activa Secure y prefijo `__Host-`. Desarrollo HTTP se limita a orígenes loopback. Producción requiere `NEXO_ENV=production` y origen HTTPS exacto, además de un proxy/certificado correctamente configurado por el operador; el despliegue reproducible se describe en HTTPS LAN más abajo. No se habilita CORS.

Auditoría: creación inicial, login correcto/fallido/limitado, cierre, revocación y acceso denegado, sin cuerpos, contraseñas, cookies, tokens ni usuario introducido. Se depura al insertar: máximo 90 días y 10 000 eventos; se preservan los eventos recientes del limitador. Las sesiones expiradas se retiran en el próximo login correcto. No hay borrado administrativo por API en 1.2. Decisiones y riesgos en [ADR 0001](docs/adr/0001-administrative-security.md).

## Desarrollo y pruebas

Python 3.12 recomendado; también se verificó con Python 3.13.3 en Windows. Sin modificar Python global:

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.lock
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m pip check
```

Ejecución local opcional desde la raíz:

```powershell
.\.venv\Scripts\python -m uvicorn nexo.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

Antes del arranque Python local, ejecuta las migraciones y la inicialización contra el directorio local (por defecto `./data`):

```powershell
.\.venv\Scripts\python -m alembic upgrade head
.\.venv\Scripts\python -m nexo.cli init-admin
```

Las pruebas de seguridad usan SQLite temporal con migraciones reales, Argon2id y HTTPX/TestClient. Cubren inicialización, autenticación, cookies, expiración, revocación, CSRF, origen, auditoría, retención, integridad, contención, rollback y persistencia. Las siete pruebas ASGI de 1.1 siguen incluidas. Starlette emite una advertencia de obsolescencia sobre el puente TestClient/HTTPX; no se añade otra biblioteca de cliente en esta entrega. No sustituyen pruebas de navegador.

Con Docker disponible e imagen construida, prueba real y aislada (reserva puerto local 18000):

```powershell
.\.venv\Scripts\python tests/docker_smoke.py
```

El script crea un proyecto con nombre aleatorio, valida healthcheck, CLI con PTY sin eco, HTTP, CSRF y persistencia tras recreación; retira únicamente sus contenedores y volumen temporales. No imprime secretos. El estado visual de 1.1 consulta salud al cargar y al pulsar el botón; mantiene timeout de cinco segundos y error visible.

## Docker y ARM64

Imagen oficial Python 3.12 slim Bookworm fijada por digest multiarch. Dependencias de producción y transitivas fijadas en `requirements.lock`; para actualizarlas, resolver versiones compatibles y repetir pruebas y builds en ambas arquitecturas. Las herramientas de pruebas no se instalan en producción. Uvicorn usa un proceso y concurrencia limitada.

Usuario 10001 sin privilegios; raíz de solo lectura, capacidades eliminadas y volumen explícito `/data` con propietario 10001, directorio 0700 y archivos privados mediante umask 0077. Healthcheck con timeout, reinicio `unless-stopped`, logs rotados y límite de 256 MiB. El healthcheck conserva el contrato de liveness de 1.1; no es un diagnóstico continuo del disco. El arranque verifica migraciones. Los datos no se copian a la imagen ni se exponen por red. En desarrollo Windows, protege también los ACL de `NEXO_DATA_DIR`.

Argon2id usa el perfil RFC 9106 LOW MEMORY de argon2-cffi: 64 MiB por verificación, tres iteraciones, cuatro hilos. Se admite una verificación simultánea y se rechazan conflictos. El límite del contenedor es preventivo; falta medir RAM, latencia y escrituras en Raspberry. El límite global de intentos puede bloquear temporalmente también al operador por actividad de otro cliente. No se habilitan access logs de Uvicorn en Docker. La política completa de logs operativos queda pendiente.

Construir ARM64 localmente sin publicar ni reemplazar la imagen de Compose:

```powershell
docker buildx build --platform linux/arm64 --load -t nexo-home:arm64 .
docker image inspect nexo-home:arm64 --format '{{.Os}}/{{.Architecture}}'
```

En Raspberry, `docker compose up --build -d` selecciona la arquitectura nativa. La construcción ARM64 en Windows con Docker Desktop no acredita funcionamiento ni consumo en hardware Raspberry.

## Componentes reutilizados y procedencia

Se reutilizan rutas, respuestas y estáticos de FastAPI/Starlette, ASGI de Uvicorn, modelos de Pydantic y transporte de HTTPX. Sin motor de plantillas ni frontend compilado. Consulta oficial: [estáticos](https://fastapi.tiangolo.com/tutorial/static-files/), [pruebas](https://fastapi.tiangolo.com/tutorial/testing/) e [imagen Python](https://hub.docker.com/_/python).

| Componente | Procedencia | Licencia | Uso |
| --- | --- | --- | --- |
| FastAPI | https://github.com/fastapi/fastapi | MIT | API y rutas |
| Starlette | https://github.com/Kludex/starlette | BSD-3-Clause | Estáticos y respuestas; transitiva |
| Uvicorn | https://github.com/Kludex/uvicorn | BSD-3-Clause | Servidor ASGI |
| Pydantic / core | https://github.com/pydantic/pydantic | MIT | Contrato JSON; transitivas |
| pytest | https://github.com/pytest-dev/pytest | MIT | Pruebas, solo desarrollo |
| HTTPX | https://github.com/encode/httpx | BSD-3-Clause | Cliente de pruebas, solo desarrollo |
| SQLAlchemy 2.0.58 | https://github.com/sqlalchemy/sqlalchemy | MIT | Motor SQLite, sesiones transaccionales y restricciones |
| Alembic 1.20.1 | https://github.com/sqlalchemy/alembic | MIT | Migraciones versionadas |
| argon2-cffi 25.1.0 | https://github.com/hynek/argon2-cffi | MIT | Hash/verificación Argon2id |

Transitivas nuevas, versiones y licencias verificadas en metadatos instalados: argon2-cffi-bindings 26.2.0 ([origen](https://github.com/hynek/argon2-cffi-bindings), MIT), cffi 2.1.1 ([origen](https://github.com/python-cffi/cffi), MIT-0), greenlet 3.5.6 ([origen](https://github.com/python-greenlet/greenlet), MIT y PSF-2.0), Mako 1.4.3 ([origen](https://github.com/sqlalchemy/mako), MIT), MarkupSafe 3.0.4 ([origen](https://github.com/pallets/markupsafe), BSD-3-Clause) y pycparser 3.12 ([origen](https://github.com/eliben/pycparser), BSD-3-Clause). SQLite y `secrets`/`hashlib`/`hmac` proceden de Python; no se añade otra biblioteca de tokens.

Evaluación proporcional: estas bibliotecas oficiales mantenidas resuelven los requisitos sin framework de autenticación completo. SQLAlchemy ofrece API Core y Session; Alembic integra la misma conexión para migraciones atómicas; argon2-cffi evita criptografía propia. Son compatibles con Python 3.12; las wheels nativas ARM64 se verifican mediante build sin compilación de fuentes. SQLAlchemy/greenlet añaden coste acotado; Mako/MarkupSafe se usan para migraciones; Argon2 domina RAM/CPU y exige medición real. Se conservan metadatos/licencias en las instalaciones, sin copiar código de terceros. No se promete ausencia de vulnerabilidades ni se ha auditado exhaustivamente código transitivo. Documentación consultada: [SQLite y transacciones](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html), [Alembic](https://alembic.sqlalchemy.org/en/latest/tutorial.html) y [parámetros Argon2](https://argon2-cffi.readthedocs.io/en/stable/parameters.html).

Son bibliotecas mantenidas obtenidas de PyPI, con API pública y dependencias resueltas por pip. Se evita `uvicorn[standard]` para reducir dependencias nativas. El build exige wheels (`--only-binary`) y comprueba disponibilidad ARM64; no se incorporó código copiado. Las transitivas quedan enumeradas en el lock y sus licencias permanecen en los metadatos instalados. OpenTelemetry API es transitiva de FastAPI, sin exportador configurado. La selección no equivale a una auditoría de vulnerabilidades; RAM y latencia deben medirse en hardware.

## Alcance y continuidad

`src/nexo/main.py` conserva la fábrica y portal, con módulos separados para seguridad administrativa y terminales. El panel 1.4 reutiliza la administración existente; cambio/recuperación de contraseña siguen pendientes. Los archivos web, Alembic y migraciones se resuelven desde el árbol del proyecto, conservado en Docker; un wheel aislado no los incluye. Estado real y pendientes en [PROGRESS.md](PROGRESS.md). Los documentos maestros no se modifican.

## Terminales — entregable 1.3

1. Arranca la imagen actualizada con `docker compose up --build -d`. Aplica la migración **0002** conservando administrador y sesiones previas. Si aún no existe administrador, usa la CLI `init-admin` descrita arriba con tu propia contraseña.
2. Abre [administración de terminales](http://localhost:8000/admin/terminals) e inicia sesión. Genera un código: aparece una sola vez, dura cinco minutos y concede inicialmente solo `terminal.status`. Puedes consultar su estado o revocarlo.
3. Abre [terminal](http://localhost:8000/terminal) en otra pestaña, perfil o navegador del mismo PC, en el origen exacto configurado. Introduce nombre y código. La pantalla muestra identidad y permite consultar el estado autorizado.
4. Actualiza la lista administrativa para renombrar, asignar/quitar permisos o revocar. Tras revocar, la siguiente consulta del terminal devuelve 401 y elimina su credencial local. Una consulta ya en curso puede finalizar.

Otro dispositivo requiere el modo HTTPS LAN documentado abajo. El Compose de desarrollo sigue publicado solo en loopback: **no** se abrió LAN/Internet ni se desactivó Secure/origen/CSRF para probar. No se comprobó vinculación física entre dispositivos; se comprobó localmente con navegadores y con HTTP real de Docker.

| Método y ruta (`/api/v1`) | Contrato |
| --- | --- |
| `POST /admin/pairing-codes` | Administrador + origen + CSRF; JSON `permissions` (por defecto `["terminal.status"]`); 201 con `id`, `code`, `expires_at`, `state`, `attempts_remaining` |
| `GET /admin/pairing-codes/{id}` | Administrador; estado sin revelar código; 404 si no existe o fue depurado |
| `DELETE /admin/pairing-codes/{id}` | Administrador + origen + CSRF; revoca código, 204 |
| `POST /terminal/pair` | JSON `code`, `name`; 201 con `credential`, `token_type: Bearer` y `terminal`; sin sesión administrativa |
| `GET /terminal/me` | Bearer de terminal; identidad propia y estado de vinculación, sin exigir permiso adicional |
| `GET /terminal/status` | Bearer + `terminal.status`; identidad/estado propio |
| `GET /admin/terminals` | Administrador; lista de identidades, permisos y estados |
| `PATCH /admin/terminals/{id}/name` | Administrador + origen + CSRF; JSON `name`; identidad actualizada |
| `PUT /admin/terminals/{id}/permissions` | Administrador + origen + CSRF; JSON `permissions`; reemplazo completo, identidad actualizada |
| `DELETE /admin/terminals/{id}` | Administrador + origen + CSRF; revocación idempotente, 204 |

Contratos Pydantic y errores `{"detail":"..."}`; 401 uniforme para código inválido, consumido, bloqueado, revocado o caducado y para credencial inválida. 403 para permiso/origen/CSRF; 404 para recurso administrativo inexistente; 422 para entrada inválida sin reflejar secretos; 429 para límite global de vinculación; 503 ante contención/fallo de persistencia. No se reintenta automáticamente. Respuestas de terminal y administración llevan `Cache-Control: no-store`.

Modelo persistente: `terminals` contiene UUID, nombre, creación/última actividad (Unix UTC), `revoked_at`, `expires_at`, configuración futura de voz y digest de credencial. Estados derivados: `linked`, `expired`, `revoked`. `terminal_permissions` contiene asignaciones independientes. `pairing_codes` guarda selector público, digest, expiración, intentos, consumo/revocación y permisos iniciales; `pairing_rate` conserva el límite global. Auditoría añade `subject_id` público. No se guardan conversaciones, transcripciones ni audio.

Permisos conocidos: `terminal.status` para consultar estado; `terminal.chat` reservado para la futura conversación, sin endpoint de chat en esta entrega. Lista vacía deniega operaciones con permiso; identidad propia sigue consultable. Nuevas claves se registran en código sin reconstruir tablas. Configuración de voz inicial: `language: es`, `voice_id: null`, sin motor. `TerminalContextScope` prepara una clave independiente para contexto temporal sin implementarlo.

Seguridad: códigos alfanuméricos de 96 caracteres con 256 bits secretos, solo digest SHA-256, uso único y cinco intentos por código. Máximo global de diez solicitudes de vinculación/60 s, persistente incluso tras reinicios; puede bloquear temporalmente intentos legítimos. El consumo y el alta son una sola transacción SQLite sin espera/reintento. Los códigos caducados se retiran al generar otro. Las credenciales independientes (`nt_` + 256 bits) expiran absolutamente a los **30 días**, sin renovación automática: vuelve a vincular tras caducar/revocar. Nunca envíes secretos en URL; usa `Authorization: Bearer ...`. Un terminal no genera códigos ni usa cookies administrativas. Peticiones administrativas que incluyen Authorization se rechazan incluso con cookie válida.

La UI del terminal conserva el Bearer en `sessionStorage`, o solo memoria si está bloqueado. Cerrar la pestaña normalmente lo descarta; olvidar localmente no revoca copias. XSS, extensiones, duplicación/restauración de pestañas o acceso al perfil pueden robar/copiar una credencial; **un Bearer vigente copiado puede reutilizarse hasta revocar/caducar**. No es identidad invulnerable ni ligada al hardware. Se aplican CSP y salidas con `textContent`; producción necesita TLS. Android podrá usar Keystore en el futuro; el contrato actual no depende del navegador. Decisiones, reutilización y límites: [ADR 0002](docs/adr/0002-terminal-pairing.md).

Las pruebas nuevas cubren códigos autorizados/denegados, expiración/reutilización/error/revocación, límites persistentes, carrera real con SQLite, identidades y permisos independientes, rechazo administrativo, revocación inmediata, reinicio, auditoría sin secretos y rollback. La comprobación antigua de inventario de tablas ahora incluye las cuatro tablas aprobadas de 1.3; se mantienen las 50 pruebas anteriores. `tests/docker_smoke.py` añade vinculación, renombrado, permisos, revocación y persistencia de terminales sobre HTTP real en un volumen desechable. Los resultados ejecutados y las limitaciones de plataforma se registran en PROGRESS.md.

## Panel y monitorización — entregable 1.4

Abre [el panel local](http://localhost:8000/admin/dashboard). `/admin/terminals`
abre la página independiente de terminales. Todas las páginas comparten diseño,
formulario de acceso, sesión y protección CSRF.
El HTML y los estáticos son públicos; los datos se cargan exclusivamente desde
endpoints administrativos protegidos. Incluye resumen, terminales, recursos,
20 eventos de auditoría y «Actualizaciones y seguridad». Los terminales con
credencial vigente no se presentan como dispositivos necesariamente conectados.

El panel tiene páginas independientes con banner y navegación mediante botones:

| Página | Ruta |
| --- | --- |
| Resumen y accesos | `/admin/dashboard` |
| Vinculación, permisos y terminales | `/admin/terminals` |
| Gráficos CSS de CPU, RAM y disco; tabla detallada | `/admin/resources` |
| Tabla de eventos recientes | `/admin/audit` |
| Tablas de versiones y estado de comprobaciones | `/admin/updates` |

Las explicaciones extensas están en apartados desplegables. Los gráficos muestran
lecturas actuales, sin inventar historial. Solo recursos sondea periódicamente;
las otras páginas cargan al entrar o al pulsar su botón de actualización. Los
enlaces de la interfaz tienen presentación de botón. Sin nuevas dependencias.

| GET bajo `/api/v1/admin` | Respuesta |
| --- | --- |
| `/summary` | Servicio, versión, disponibilidad SQLite y recuento de terminales |
| `/metrics` | Fecha Unix UTC de muestra, intervalo, SO visible y métricas con valor, unidad, ámbito y limitación |
| `/persistence` | Consulta SQLite de lectura y revisión 0002; no ejecuta chequeos integrales costosos |
| `/audit?limit=20` | Eventos más recientes primero; límite de 1 a 100; 422 fuera de rango |
| `/updates` | Versiones locales, despliegue conocido y estado informativo del evaluador futuro |

Todos requieren la cookie administrativa; un encabezado Authorization se rechaza,
incluso acompañado de cookie válida. Son solo lectura y llevan `no-store`.
Se reutilizan los controles de origen y CSRF para login/logout y operaciones de
terminales. No se exportan secretos, variables de entorno ni logs completos.

`NEXO_METRICS_INTERVAL` controla caché y refresco (30 s; rango 5–300). La página de recursos
suspende el sondeo al ocultar la pestaña y lo detiene al cerrar sesión o fallar;
permite volver a consultar manualmente. El primer muestreo de CPU muestra
«No disponible»: necesita dos muestras. RAM, disco, RSS y actividad se leen de
psutil; sensores de CPU ausentes muestran su limitación. RSS y actividad de NEXO
son del proceso; RAM/CPU/actividad del sistema pueden corresponder al kernel
visible o VM Docker. **No equivalen al consumo del contenedor ni a mediciones de
Raspberry.** El disco corresponde al sistema de archivos del volumen de datos.
No se monta el anfitrión ni se conoce su límite cgroup desde estas lecturas.

El inventario consulta `importlib.metadata` y la versión real de Python; no accede
a Internet, no ejecuta comandos y no afirma ausencia de vulnerabilidades. Digest
de imagen y última evaluación se declaran no disponibles cuando no existen.
La versión NEXO es la misma constante usada por la aplicación y su API.

## HTTPS LAN (configuración independiente)

Usa **solo** `compose.lan.yaml`, nunca `-f compose.yaml -f compose.lan.yaml`:
la fusión de puertos mezclaría desarrollo y LAN. El backend no publica puertos;
Caddy publica únicamente TCP 443 en una IP privada concreta. No hay publicación
HTTP, API Caddy ni socket Docker. No abrir puertos del router, UPnP ni túneles.
Configura el firewall del servidor para permitir TCP 443 solo desde tu subred LAN;
el repositorio no cambia el firewall automáticamente.

1. Identifica una IPv4 privada estable del servidor (por ejemplo, una reserva DHCP).
   En `.env`, añade `NEXO_LAN_IP` con **tu IP real** y `NEXO_LAN_HOST=nexo.home.arpa`.
   Los números de `.env.example` son ejemplos, nunca credenciales/configuración de
   producción. El archivo LAN fija `production` y deriva el origen HTTPS del nombre;
   ignora las variables de entorno/origen del Compose de desarrollo.
2. Comprueba si puedes resolver `nexo.home.arpa` a esa IP desde cada dispositivo.
   Si hay DNS local configurable, crea el registro allí. Para Windows sin DNS,
   el operador puede añadir su asociación IP/nombre al archivo hosts como administrador.
   **Android no hereda el hosts de Windows.** Si no hay DNS utilizable por todos,
   configura `NEXO_LAN_HOST` con la misma IP privada de `NEXO_LAN_IP`: Caddy puede
   emitir el certificado local para esa IP y el origen pasa a ser `https://IP`.
   No se necesita editar el móvil ni asumir DNS configurable. Cambiar de IP/nombre
   exige actualizar `.env`, certificado/origen y acceder de nuevo.
3. Desde Windows, ejecuta `.\.venv\Scripts\python scripts/lan.py check`.
   En Raspberry con Python, `python3 scripts/lan.py check`. El preflight rechaza
   publicaciones fuera de RFC1918, nombres externos y exposición del backend.
   Comprueba también que la IP elegida pertenece al servidor.
4. Para pasar del modo desarrollo al LAN, detén primero `docker compose down`
   (sin `--volumes`); después ejecuta `python scripts/lan.py up` con el Python
   correspondiente. Ambos modos comparten proyecto y volumen SQLite: conservan
   administrador, terminales y auditoría. No se ejecutan simultáneamente. El
   arranque aplica las migraciones existentes. Consulta estado con
   `docker compose -f compose.lan.yaml ps`.
5. Si aún no hay administrador, usa
   `docker compose -f compose.lan.yaml exec nexo python -m nexo.cli init-admin`.
   Introduce tu propia contraseña en esa terminal, nunca en el chat.

### Confianza del certificado (paso manual en cada cliente)

Caddy genera una CA interna y la guarda en `caddy_data`; no instala confianza
fuera de su contenedor. Su clave privada **no se debe copiar ni compartir**.
Conserva ese volumen entre recreaciones para no cambiar la CA. Para exportar solo
el certificado público, desde la raíz del repositorio:

```powershell
New-Item -ItemType Directory -Force .validation
# Copia solo root.crt: NO root.key ni el directorio completo.
docker compose -f compose.lan.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt .validation/nexo-root.crt
certutil -hashfile .validation/nexo-root.crt SHA256
```

Obtén el certificado directamente del servidor y verifica su huella por un medio
confiable antes de instalarlo. En Windows, abre ese `.crt`, elige instalar para el
usuario actual y el almacén de autoridades raíz de confianza; comprueba la huella
y acepta únicamente tu propia CA. Firefox u otros clientes pueden utilizar un
almacén independiente: verifica su configuración/documentación.

En Android, transfiere únicamente el certificado público y busca en Ajustes la
opción de instalar un certificado de CA (la ruta/nombre depende del fabricante y
versión). La instalación puede exigir desbloqueo y mostrar un aviso sobre confianza
en una CA de usuario. Comprende su alcance antes de instalarla: quien controle
su clave privada puede emitir certificados que ese dispositivo confiará. Algunos
perfiles administrados, navegadores o aplicaciones restringen CA de usuario;
la instalación no garantiza confianza en todas las aplicaciones. Comprueba en el
navegador elegido que HTTPS es válido. Si no puedes instalar/verificar confianza,
no continúes por una advertencia ni introduzcas credenciales. Resuelve la política
con el administrador del dispositivo; no desactives TLS ni Secure.

Después, abre `https://nexo.home.arpa/admin/dashboard` en Windows o móvil (o
`https://TU-IP/admin/dashboard` si elegiste IP). El terminal usa el mismo origen,
ruta `/terminal`. No se ha probado todavía desde dispositivos físicos. HSTS se
entrega por Caddy; HTTP no se publica ni redirige. El modo localhost continúa en
`http://localhost:8000`, únicamente para desarrollo en el mismo equipo.

Para detener LAN: `docker compose -f compose.lan.yaml down`, sin borrar volúmenes.
Para regresar al modo desarrollo: tras detener LAN, `docker compose up --build -d`.

### Componentes, compatibilidad y validación 1.4

Se añade **psutil 7.2.2**, [repositorio oficial](https://github.com/giampaolo/psutil),
BSD-3-Clause, sin dependencias Python transitivas nuevas; API local pequeña frente
a un agente residente. [Documentación oficial](https://psutil.io/). Se añade el
contenedor oficial **Caddy 2.11.9**, Apache-2.0, [repositorio](https://github.com/caddyserver/caddy),
imagen Alpine fijada por digest multiarch; el manifiesto publica AMD64 y ARM64.
Se consultaron [TLS local y confianza](https://caddyserver.com/docs/automatic-https)
y [proxy y timeouts](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy).
No se copió código externo. Licencias conservadas en distribuciones/imágenes.
Mantenimiento activo y wheels ARM64 verificados; no equivale a auditoría exhaustiva
ni a medir RAM en Raspberry. Caddy tiene límite de 128 MiB, backend de 256 MiB.
Arquitectura, riesgos y alternativas: [ADR 0003](docs/adr/0003-local-monitoring-https.md).

```powershell
.\.venv\Scripts\python -m pytest -q
.\.venv\Scripts\python -m pip check
.\.venv\Scripts\python tests/docker_smoke.py
.\.venv\Scripts\python tests/https_smoke.py
```

El smoke HTTPS levanta un proyecto/volúmenes aleatorios y publica únicamente
`127.0.0.1:18443`; resuelve `nexo.home.arpa` solo dentro del proceso de prueba.
Carga su CA temporal en un contexto TLS específico y verifica nombre y cadena;
comprueba rechazo sin confianza, cookie Secure, origen/CSRF, encabezados y
persistencia tras recrear Caddy/backend. No instala una CA global, no modifica DNS
ni usa `verify=False`. El smoke HTTP usa loopback:18000. Ambos retiran únicamente
sus volúmenes temporales. Las credenciales de prueba no llegan al volumen operativo.

Resultados, archivos y pendientes de aceptación se mantienen en
[PROGRESS.md](PROGRESS.md). La revisión posterior del rediseño se completó en el navegador integrado: login,
navegación entre las cinco páginas, edición de nombre de terminal, tablas, gráficos
y cierre de sesión. Se comprobaron escritorio y viewport móvil sin desbordamiento
general; no equivale a probar un teléfono físico. Móviles reales y hardware
Raspberry siguen pendientes. No avanzar a nuevos entregables sin autorización.

## Fase 2 / entregable 2.2 — Orquestación local

En `/admin/terminals`, el botón existente «Actualizar terminales» vuelve a consultar
el backend y muestra únicamente registros `linked` sin fecha de revocación.
Revocados y caducados desaparecen de la lista visible; sus registros y auditoría
se conservan. Si no quedan activos, muestra «No hay terminales vinculados activos».
Durante la consulta se retira la lista anterior; ante un fallo se muestra un error
sin conservar datos antiguos como actuales. No cambia el endpoint, los permisos,
las sesiones ni la revocación de credenciales.

El endpoint de interacción conserva los seis campos de 2.1 y sus límites,
autenticación y contextos. Las capacidades se registran explícitamente mediante
`CapabilityRegistry`: identificador, nombre, permisos, recursos canónicos, modelo
Pydantic de entrada, manejador async, modelo de resultado y timeout. Solo se
registran saludo, estado, ayuda y respuesta de indisponibilidad. Sin acciones,
integraciones ni capacidades de prueba en el panel operativo.

El enrutamiento usa frases completas normalizadas; ambigüedad implica función
no disponible. Se comprueban permisos del servidor antes de ejecutar.
Los recursos se adquieren de forma atómica, todos o ninguno; otra solicitud que
necesite un recurso ocupado recibe 409 inmediatamente, sin cola ni reintento.
Recursos independientes permiten concurrencia. Un terminal admite una interacción.
Errores, cancelaciones y timeouts cooperativos liberan los bloqueos.

Estados compatibles: `completed/text`, `completed/unavailable` y `failed/error`.
Los conflictos tienen códigos `terminal_busy` o `resource_busy`; permisos,
`forbidden`; fallo de ejecución, `processing_error`; timeout, `execution_timeout`
(504). `confirmation_required` está reservado y nunca ejecuta el manejador.
Los mensajes se muestran con el frontend existente; voz pendiente.

Un worker y un proceso. Reiniciar pierde bloqueos y contexto; no reejecuta nada.
El contrato reserva el código futuro `outcome_unknown`: una operación externa
interrumpida deberá reconciliarse antes de volver a ejecutarse. No hay motor de
recuperación ni operaciones físicas en esta entrega. Los manejadores futuros
deben ser async, cooperativos y acotar E/S; un timeout no detiene código bloqueante.

Sin dependencias nuevas. Contrato, evaluación de reutilización, licencias,
limitaciones y recuperación: [ADR 0004](docs/adr/0004-capability-orchestration.md).
Pruebas nuevas: `tests/test_orchestration.py`, con eventos deterministas y HTTP
TCP real en loopback mediante Uvicorn. Resultados completos en [PROGRESS.md](PROGRESS.md).
