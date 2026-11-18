# ADR 0001 — Persistencia y seguridad administrativa (entregable 1.2)

Estado: implementado dentro del alcance autorizado de 1.2.

## Decisión

Reutilizar SQLAlchemy 2, SQLite de Python, Alembic y argon2-cffi. Mantener
un proceso Uvicorn y las tres tablas administrativas más `alembic_version`.
No hay JWT, proveedores externos, roles complejos ni identidad de terminales.

- SQLite utiliza claves foráneas y transacciones explícitas. Las escrituras
  ejecutan `BEGIN IMMEDIATE`, sin espera ni reintento (`timeout=0`). La contención
  devuelve HTTP 503; el cliente decide cuándo volver a intentar.
- La restricción `administrators.id = 1` y el índice parcial único de sesiones
  no revocadas impiden duplicados incluso con procesos concurrentes.
- Argon2id usa el perfil RFC 9106 LOW MEMORY de la biblioteca: 64 MiB, tres
  iteraciones, cuatro hilos. Solo una verificación simultánea por proceso;
  además, el bloqueo SQLite serializa verificaciones entre procesos. Medir en Pi.
- Sesiones con 32 bytes aleatorios (`secrets`), digest SHA-256 en SQLite y
  expiración absoluta de 3600 segundos. La cookie es HttpOnly, SameSite=Strict,
  Path=/, sin Domain; Secure y prefijo `__Host-` con origen HTTPS. Un login
  revoca la sesión anterior en la misma transacción que crea la nueva.
- El login exige origen exacto configurado y JSON. Toda mutación autenticada
  exige además `X-CSRF-Token`. Se deriva mediante HMAC-SHA256 de la sesión,
  se entrega por login y `/auth/me` y se compara en tiempo constante. La
  política reside en la dependencia reutilizable, no solo en logout.
  No se configura CORS. Un cliente HTTP explícito también debe enviar Origin.
- HTTP se permite solo con origen loopback en desarrollo. Producción exige
  origen HTTPS; el certificado/proxy queda fuera de 1.2. No confiar en
  `X-Forwarded-*` ni abrir puertos LAN/WAN en esta entrega.
- Límite global persistente: cinco verificaciones por ventana móvil de 60 s,
  incluyendo éxitos y fallos. Los eventos de auditoría son la fuente del
  contador, bajo bloqueo transaccional. No depende del usuario/IP presentado
  y no se elude reiniciando o cambiando cabeceras. HTTP 429 indica espera;
  nunca se programa un reintento. Puede causar denegación temporal de acceso
  por otro cliente; es una elección conservadora para un único administrador
  y un servidor local. Un usuario inexistente verifica un hash señuelo.
- Auditoría de metadatos cerrados: evento, resultado, identificador interno y
  motivo fijo; sin IP, usuario introducido, cuerpos ni secretos. Retención
  automática al insertar: hasta 90 días y 10 000 eventos, conservando siempre
  los cinco eventos recientes que necesita el limitador. Las sesiones expiradas
  se eliminan en el siguiente login correcto. No se implementa borrado por API.

## Consecuencias y límites

Errores SQL producen 503 genérico y rollback. Los fallos de auditoría impiden
confirmar cambios sensibles. No se registran parámetros SQL ni access logs de
Uvicorn en el arranque Docker. Las respuestas de seguridad llevan `no-store`;
la validación no refleja entradas. `/health` mantiene el contrato de liveness
de 1.1; el arranque comprueba la revisión de base de datos, pero el endpoint
no es un diagnóstico continuo de disco. La aplicación no migra al importarse:
la CLI/arranque Docker aplica Alembic antes de aceptar tráfico.

Volumen Docker privado a UID/GID 10001, directorio 0700, umask 0077 y raíz
de solo lectura. SQLite no se cifra en este entregable: proteger el host y
el volumen; las credenciales en reposo son hashes. En Windows deben revisarse
los ACL del directorio local. No hay recuperación/cambio de contraseña ni
administradores adicionales; no editar la base manualmente como procedimiento.
Las dependencias administrativas están separadas de las futuras identidades
de terminal, que quedan fuera de alcance.
