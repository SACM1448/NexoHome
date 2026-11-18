# ADR 0003 — Monitorización local y HTTPS LAN

Estado: aceptado dentro del alcance autorizado de 1.4.

Se conserva el monolito FastAPI y la autenticación 1.2. Un módulo de lectura
administrativa reutiliza SQLAlchemy, auditoría y autorización existentes. El panel
y la administración de terminales comparten estructura, login, cookie y código CSRF.
La revisión visual autorizada separa resumen, terminales, recursos, auditoría y
actualizaciones en rutas HTML independientes. Se reutiliza una estructura local
común y fragmentos de una lista cerrada, sin motor de plantillas ni datos de usuario
en la interpolación. Cada página consulta solo su API; únicamente recursos sondea
métricas. Tablas semánticas y gráficos con `meter`/CSS no añaden dependencias.

Se incorpora psutil 7.2.2 (BSD-3-Clause, https://github.com/giampaolo/psutil),
sin dependencias Python adicionales. Su API de CPU, RAM, disco, proceso y sensores
evita implementaciones específicas de Windows/Linux. Caché compartida y bloqueo
de muestreo, 30 s por defecto (5–300), sin hilo residente ni espera para CPU.
CPU necesita dos muestras; sensores ausentes se declaran. Las métricas del sistema
visible pueden ser del kernel/VM de Docker, mientras RSS y actividad del servicio
pertenecen al proceso NEXO. No se montan /proc del anfitrión ni el socket Docker.
No se afirma conocer límites cgroup o consumo físico Raspberry.

Se incorpora Caddy oficial 2.11.9 (Apache-2.0,
https://github.com/caddyserver/caddy, imagen https://github.com/caddyserver/caddy-docker),
fijado por digest multiarch. TLS con CA interna persistente y distribución manual
del certificado público de raíz. No hay ACME público, cambios de confianza global
automáticos ni redirecciones/puerto HTTP público. API de Caddy deshabilitada;
healthcheck solo en loopback. El backend solo pertenece a una red interna y Caddy
también tiene una red de publicación; una única red interna no publicó correctamente
el puerto en Docker Desktop durante la prueba real y se corrigió esa separación.

Compose LAN es independiente del Compose de desarrollo; no se fusionan archivos.
El proyecto y volumen SQLite conservan sus nombres para una transición explícita
sin duplicar el administrador. El preflight limita la publicación a IPv4 RFC1918 y
el nombre a home.arpa o esa IP; el operador configura resolución, firewall LAN y
confianza en cada cliente. Cambiar de nombre/IP cambia el origen y exige nuevo login.

Alternativas: biblioteca estándar para cada plataforma implicaría mayor código
propio; Prometheus/Grafana añaden residentes y complejidad fuera del presupuesto.
Caddy centraliza TLS sin incorporar certificados privados a FastAPI. Se verificaron
wheels psutil ARM64, build backend ARM64 e importación/métricas bajo emulación;
el manifiesto Caddy publica ARM64. Memoria y estabilidad físicas siguen pendientes.
Límites configurados: backend 256 MiB y Caddy 128 MiB; no son mediciones reales.

Riesgos: la CA privada debe protegerse en el volumen; robarla compromete confianza
en los dispositivos que la instalen. La confianza Android depende del dispositivo,
navegador y políticas; no se evitan advertencias para resolverla. No se realizó
auditoría exhaustiva de vulnerabilidades. El inventario solo consulta metadatos
locales y declara ausente el evaluador futuro, sin comandos ni solicitudes remotas.

Fuentes oficiales consultadas: https://psutil.io/,
https://caddyserver.com/docs/automatic-https y
https://caddyserver.com/docs/caddyfile/directives/reverse_proxy.
