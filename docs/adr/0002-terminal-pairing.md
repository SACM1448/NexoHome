# ADR 0002 — Identidad y vinculación de terminales

Estado: implementado para Fase 1 / entregable 1.3. No modifica la especificación maestra.

## Decisión

Reutilizar FastAPI/Pydantic, Alembic, SQLAlchemy/SQLite, `security.record` y la
dependencia administrativa de 1.2. Sin nuevas dependencias, servicios ni WebSocket.
Se consultaron las API oficiales de [secrets de Python 3.12](https://docs.python.org/3.12/library/secrets.html)
y [transacciones SQLite en SQLAlchemy](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html).
La evaluación y licencias de las bibliotecas existentes siguen en README.
`secrets`, SHA-256 y comparación constante reutilizan la biblioteca estándar
de Python (PSF-2.0, [procedencia](https://github.com/python/cpython)); sin código externo copiado,
dependencias transitivas nuevas ni coste nativo adicional en ARM64. No se introduce
un framework de cuentas/OAuth: no existe proveedor externo y ya hay sesiones opacas.
RAM real pendiente de medición en Raspberry.

El código alfanumérico tiene 96 caracteres hexadecimales: selector UUID de 32
caracteres y secreto aleatorio de 256 bits. El selector permite contar hasta cinco
intentos por código sin guardar el secreto. SHA-256 protege secretos de alta
entropía; no sustituye Argon2id para contraseñas humanas. Expiración absoluta de
300 segundos y máximo global de diez solicitudes válidamente estructuradas por
ventana de 60 segundos, persistido aparte de la auditoría. No se confía en IP ni
cabeceras de proxy. Esto permite denegación temporal de servicio de vinculación;
se prefiere ese riesgo al intento ilimitado. El límite administrativo 1.2 permanece
independiente. Entradas rechazadas por Pydantic no consumen intentos.

`BEGIN IMMEDIATE`, timeout SQLite cero y sin reintentos protegen en una transacción
consumo, alta, permisos y auditoría. Una operación concurrente pierde con 401 o
503; nunca obtiene una segunda identidad. Los fallos auditados se confirman antes
de devolver 401/429; si falla persistencia/auditoría, no se emiten credenciales.
Los códigos caducados se depuran al generar otro; su estado puede pasar a 404.

Credencial opaca `nt_` + 256 bits, emitida una sola vez, digest único y caducidad
absoluta de 30 días. Esta duración es una decisión técnica de esta entrega, sin
renovación automática. Revocar o caducar exige volver a vincular con código nuevo.
Nunca se acepta en URL ni cookie administrativa: solo `Authorization: Bearer`.
La administración rechaza peticiones con Authorization, incluso si también
contienen cookie administrativa. Identidad y permisos se consultan en SQLite en
cada petición; no hay caché de autorización. La revocación impide nuevas
autenticaciones una vez confirmada, sin cancelar respuestas ya en curso.

El navegador omite cookies en las peticiones de terminal y mantiene la credencial
en `sessionStorage` de su pestaña (o memoria si no está disponible). Permite recarga
sin guardar indefinidamente, pero XSS, extensiones, copia/duplicación de pestañas,
restauración del navegador o acceso al perfil pueden copiarla. El servidor no
puede distinguir una copia robada de un cliente legítimo antes de revocar/caducar;
no hay prueba de posesión vinculada a hardware ni protección absoluta contra replay
de un Bearer vigente. CSP restringida, no-store, sin HTML dinámico de entradas,
sin secretos en logs, TLS en producción y revocación reducen el riesgo.
Android podrá usar el mismo contrato Bearer y guardar la credencial con Keystore
en una fase posterior. No se implementa aplicación Android aquí.

Los permisos se guardan en filas independientes, extensibles sin migrar el modelo.
Solo se aceptan claves registradas; ausencia implica denegación. `terminal.status`
autoriza el endpoint de estado; `terminal.chat` queda reservado, sin chat todavía.
`/terminal/me` identifica al propio principal autenticado incluso sin permisos.
`TerminalContextScope` transporta únicamente el identificador para un proveedor
efímero futuro; no guarda mensajes ni crea el orquestador. La voz futura contiene
solo idioma e identificador opcional, sin motor ni audio.

## Consecuencias y límites

Las pantallas `/admin/terminals` y `/terminal` son estáticas públicas; todos sus
datos y operaciones están protegidos en backend. Mutaciones administrativas
heredan origen exacto/CSRF. Todo Origin presente en terminal debe coincidir con
la configuración; clientes nativos pueden omitirlo. No hay CORS. El despliegue
debe mantener el backend tras un proxy HTTPS confiable; configurar un origen
HTTPS por sí solo no cifra el transporte. HTTP de desarrollo queda en loopback.

Presencia aproximada actualizada como máximo una vez/minuto; se adquiere bloqueo
transaccional al autenticar para mantener validación y lectura consistentes, sin
escritura de actividad en cada petición. Contención devuelve 503. Auditoría
reutiliza retención 1.2 y añade `subject_id` público, nunca nombres introducidos,
digest ni secretos. No se borran terminales revocados automáticamente; quedan
visibles para administración. La validación física de RAM, rendimiento y HTTPS
entre dispositivos sigue pendiente. No se inicia 1.4.
