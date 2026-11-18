\# NEXO HOME — ESPECIFICACIÓN MAESTRA



\*\*Versión:\*\* 1.0  

\*\*Estado:\*\* Línea base de requisitos para implementación  

\*\*Plataforma objetivo:\*\* Raspberry Pi 4, 2 GB RAM, Raspberry Pi OS Lite 64-bit  

\*\*Idioma de interfaces:\*\* Español  

\*\*Arquitectura:\*\* Monolito modular con integraciones y agentes externos



\---



\## 1. Propósito



NEXO Home es un asistente doméstico inteligente, multiagente y multicanal, diseñado para funcionar permanentemente en una Raspberry Pi y atender solicitudes desde terminales autorizados, una interfaz administrativa y Telegram.



Su propósito es integrar inteligencia artificial, control de dispositivos, servicios personales, automatizaciones y administración de un PC Windows mediante una plataforma segura, modular y eficiente.



La Raspberry será autónoma: no dependerá de que el PC Windows esté encendido, salvo para funcionalidades que requieran específicamente ese computador.



\### Principios



1\. Seguridad por defecto.

2\. Funcionalidad real y verificable.

3\. Uso eficiente de los recursos.

4\. Modularidad sin microservicios innecesarios.

5\. Reutilización responsable de software existente.

6\. Independencia entre terminales.

7\. Integraciones externas desacopladas.

8\. Sin cargos de API no autorizados.

9\. Implementación incremental.

10\. Pruebas antes de avanzar.



\## 2. Entornos



\### Desarrollo



\- Windows como sistema principal.

\- Python, Git y Codex ya instalados.

\- WSL2 configurado.

\- Docker Desktop con motor Linux.

\- Docker Compose disponible.

\- Prueba `docker run --rm hello-world` superada.

\- Directorio del proyecto en Windows, preferiblemente SSD.

\- No se requiere Ubuntu independiente.



\### Producción



\- Raspberry Pi 4.

\- 2 GB RAM.

\- microSD 32 GB.

\- Raspberry Pi OS Lite 64-bit.

\- Docker Engine y Compose.

\- Arquitectura ARM64.

\- Operación sin entorno gráfico.

\- Acceso desde navegadores de la red local.



Las imágenes y dependencias deben ser compatibles con ARM64. El desarrollo en AMD64 no demuestra por sí solo la compatibilidad de producción.



\### Restricciones



\- No ejecutar LLM grandes localmente.

\- Evitar Kubernetes.

\- Evitar Redis, PostgreSQL, Qdrant y otros servicios sin necesidad justificada.

\- Minimizar procesos residentes, escrituras en microSD y uso de memoria.

\- Utilizar límites de concurrencia, timeouts y health checks.

\- Priorizar imágenes ligeras y dependencias mantenidas.

\- No utilizar servicios cloud pagos sin autorización.



\## 3. Arquitectura



\### Componentes



\- Frontend HTML, CSS y JavaScript ligero.

\- Backend Python/FastAPI.

\- API REST versionada.

\- WebSocket para eventos.

\- Orquestador central.

\- Router de intenciones.

\- Motor de permisos.

\- Registro de herramientas.

\- Gestor de tareas y bloqueos.

\- Gestor de sesiones independientes.

\- Adaptadores de dispositivos.

\- Router de proveedores LLM.

\- Servicios STT y TTS.

\- Integraciones OAuth.

\- Servicio Telegram.

\- Agente Windows independiente.

\- SQLite.

\- Observabilidad y auditoría.

\- Módulo de respaldos, activado al final.



\### Diagrama general



```mermaid

flowchart TB

&#x20;   M\[Motorola] --> P\[HTTPS / Caddy]

&#x20;   T\[Tableta Android] --> P

&#x20;   PC\[Navegador PC] --> P

&#x20;   P --> API\[FastAPI]



&#x20;   TG\[Telegram] --> BOT\[Adaptador Telegram]

&#x20;   BOT --> API



&#x20;   API --> SEC\[Autenticación y permisos]

&#x20;   API --> ORQ\[Orquestador]

&#x20;   ORQ --> INT\[Router de intenciones]

&#x20;   INT --> TASK\[Gestor de tareas]

&#x20;   TASK --> LOCK\[Bloqueos por recurso]

&#x20;   TASK --> TOOLS\[Registro de herramientas]



&#x20;   TOOLS --> IOT\[Adaptadores IoT]

&#x20;   TOOLS --> LLM\[Router LLM]

&#x20;   TOOLS --> OAUTH\[Google / Spotify]

&#x20;   TOOLS --> GAME\[Integración Gaming]

&#x20;   GAME --> WA\[Agente Windows]



&#x20;   API --> DB\[(SQLite)]

&#x20;   API --> VOICE\[STT / TTS]

&#x20;   API --> OBS\[Logs y métricas]



&#x20;   LLM --> CLOUD\[APIs externas]

```



\### Decisiones arquitectónicas



\- El núcleo será un monolito modular.

\- No se creará un contenedor por cada agente lógico.

\- Telegram podrá ejecutarse en proceso separado si mejora aislamiento y recuperación.

\- Caddy será evaluado como proxy HTTPS.

\- SQLite será la persistencia inicial.

\- El estado conversacional será temporal y separado por terminal.

\- Los adaptadores externos deben implementar interfaces claras.

\- El futuro traslado a cloud debe permitir que la Raspberry funcione como puente LAN autenticado mediante conexión saliente.



\## 4. Interfaz web



\### `/terminal`



Interfaz de interacción con NEXO.



Debe incluir:



\- Robot animado.

\- Entrada textual.

\- Micrófono.

\- Respuestas escritas y habladas.

\- Estado de escucha, procesamiento, ejecución y reproducción.

\- Diseño responsivo.

\- Soporte para pantalla completa.

\- Reconexión.

\- Identidad del terminal.

\- Visualización de errores.

\- Interrupción de audio.



No incluirá controles de administración.



\### `/dashboard`



Panel de información y operación, con acceso según permisos.



Métricas previstas:



\- CPU.

\- RAM.

\- Disco.

\- Temperatura disponible.

\- Red.

\- Uptime.

\- Estado de contenedores.

\- Latencia API.

\- Estado LLM.

\- Dispositivos.

\- Tareas.

\- Alertas.

\- Incidentes.



Las métricas deben ser reales. Si una no puede obtenerse, indicar que no está disponible.



\### `/admin`



Única interfaz autorizada para modificar la configuración del sistema.



Secciones:



\- Seguridad.

\- Terminales.

\- Permisos.

\- Voces.

\- Proveedores de IA.

\- Integraciones.

\- Cuentas vinculadas.

\- Dispositivos.

\- Gaming.

\- Automatizaciones.

\- Diagnóstico.

\- Auditoría.

\- Sistema.

\- Respaldos.



Las autorizaciones deben verificarse en el backend.



\## 5. Identidad, usuarios y terminales



Inicialmente habrá dos terminales principales:



\- Motorola.

\- Tableta Android.



Cada terminal debe tener:



\- Identificador único.

\- Nombre.

\- Estado de vinculación.

\- Credencial de sesión.

\- Permisos.

\- Voz configurada.

\- Contexto conversacional independiente.

\- Tareas propias.

\- Estado de presencia.

\- Posibilidad de revocación.



Las conversaciones no deben mezclarse.



No se guardarán transcripciones ni audio de forma persistente.



La sesión de autorización y el contexto conversacional son conceptos diferentes.



\### Vinculación



\- Código alfanumérico generado por el administrador.

\- Vigencia inicial de cinco minutos.

\- Un solo uso.

\- Intentos limitados.

\- Almacenamiento protegido.

\- Revocación desde administración.



La vinculación debe proporcionar una credencial posterior para operar sin contraseña personal en cada consulta.



Las credenciales de navegador no deben presentarse como identidad criptográfica invulnerable. Una futura aplicación Android podrá utilizar Android Keystore.



\## 6. Seguridad administrativa



\- Contraseña alfanumérica robusta, no PIN.

\- Argon2id con salt.

\- Longitud recomendada mínima de 12 caracteres.

\- Protección contra fuerza bruta.

\- Sesión administrativa de duración absoluta máxima de 60 minutos.

\- Una sesión administrativa activa inicialmente.

\- Cookies HttpOnly, Secure y SameSite apropiado.

\- Sesiones opacas verificadas en servidor.

\- Protección CSRF.

\- Validación de origen en HTTP y WebSocket.

\- Revocación de sesiones.

\- Cambio de contraseña invalida sesiones.

\- Autorización por endpoint y operación.

\- Sin ejecución arbitraria de comandos.

\- Sin secretos en logs.

\- Sin credenciales hardcodeadas.



Los tokens de integraciones deberán cifrarse en reposo. Las claves de cifrado no deben almacenarse junto con los datos protegidos sin una estrategia de separación y recuperación.



\### Red



Inicialmente LAN únicamente.



No abrir puertos WAN.



Nombre sugerido: `https://nexo.home.arpa`.



Caddy con certificados locales es una alternativa propuesta, pendiente de validación práctica en Android y PC.



El acceso al micrófono y las sesiones sensibles requieren un origen seguro.



\## 7. Orquestador



El orquestador debe:



1\. Recibir la solicitud.

2\. Identificar canal y terminal.

3\. Autenticar.

4\. Autorizar.

5\. Interpretar intención.

6\. Determinar si existe una operación determinista.

7\. Seleccionar herramienta o proveedor LLM.

8\. Validar argumentos.

9\. Comprobar política y disponibilidad.

10\. Ejecutar.

11\. Registrar resultado operativo.

12\. Responder al canal original.



Los modelos LLM no ejecutarán comandos directamente.



Cada herramienta tendrá:



\- Nombre.

\- Descripción.

\- Esquema de parámetros.

\- Permisos requeridos.

\- Nivel de riesgo.

\- Recursos utilizados.

\- Timeout.

\- Manejo de errores.

\- Política de auditoría.



El sistema debe evitar que texto procedente de Internet, documentos o respuestas de modelos pueda modificar permisos o convertirse en instrucciones privilegiadas.



\## 8. Tareas y concurrencia



Cada tarea tendrá:



\- `task\_id`.

\- Identidad del solicitante.

\- `terminal\_id`, cuando aplique.

\- `resource\_id`, cuando aplique.

\- Tipo.

\- Estado.

\- Correlation ID.

\- Inicio.

\- Timeout.

\- Resultado o error.



Estados sugeridos:



\- pending.

\- running.

\- completed.

\- failed.

\- cancelled.

\- interrupted.

\- unknown.



\### Política obligatoria



\*\*Primero en llegar, primero en obtener el recurso; rechazo inmediato de solicitudes conflictivas.\*\*



No hay cola automática de comandos conflictivos ni reintento automático.



Ejemplo:



1\. Motorola envía una instrucción al televisor Samsung.

2\. NEXO obtiene el bloqueo.

3\. La tableta envía una instrucción incompatible al mismo televisor.

4\. NEXO rechaza inmediatamente la segunda operación.

5\. La tableta muestra y reproduce:



"El televisor Samsung está ejecutando una instrucción solicitada desde otro terminal. Espera a que termine e inténtalo nuevamente."



6\. El bloqueo se libera al confirmar el resultado o alcanzar un estado seguro.

7\. La tableta puede intentar de nuevo manualmente.



Diferentes recursos podrán operar simultáneamente.



Las lecturas paralelas dependerán de las capacidades del adaptador.



Los bloqueos deben ser atómicos y resistentes a errores.



Un timeout no implica necesariamente que la operación física haya terminado.



Después de reinicios no se reejecutarán automáticamente acciones físicas interrumpidas.



\## 9. Voz



\### Entrada



Primera versión:



\- Pulsar para hablar.

\- Permiso de micrófono.

\- Captura.

\- STT.

\- Procesamiento.



Evolución:



\- Palabra de activación configurable.

\- Evaluación de escucha continua.

\- Posible APK Android para capacidades de segundo plano.



No prometer escucha permanente desde navegador Android en segundo plano.



\### Salida



Todas las respuestas relevantes destinadas a terminales deben aparecer en pantalla y reproducirse con la voz configurada para ese terminal.



Incluye:



\- Respuestas finales.

\- Confirmaciones.

\- Errores.

\- Advertencias.

\- Rechazos por concurrencia.



La lectura automática de todos los estados intermedios queda pendiente de decisión.



Cada terminal tendrá reproducción independiente, cola de audio propia e interrupción.



Si falla TTS, debe mantenerse la respuesta textual.



Piper es candidato, no dependencia aprobada definitivamente.



La selección STT/TTS requiere pruebas de RAM, latencia y compatibilidad.



\## 10. Proveedores LLM



Candidatos:



\- Gemini.

\- Groq.

\- OpenRouter.

\- APIs compatibles con OpenAI.



El administrador podrá:



\- Agregar proveedor.

\- Configurar endpoint.

\- Guardar credencial.

\- Elegir modelo.

\- Establecer prioridad.

\- Probar conexión.

\- Activar o desactivar.

\- Consultar errores.

\- Consultar uso disponible.



Requisitos:



\- Sin cargos automáticos.

\- Control de cuotas.

\- Timeouts.

\- Manejo de 429.

\- Fallback.

\- Circuit breaker o cooldown cuando sea apropiado.

\- Validación de URLs y prevención SSRF.

\- TLS.

\- Redacción de secretos en logs.



ChatGPT Plus o Codex no equivalen a una API gratuita.



No implementar RAG ni base vectorial inicialmente.



\## 11. Telegram



\- Bot privado.

\- Un usuario autorizado inicialmente.

\- Validación de user ID y chat ID.

\- Long polling saliente.

\- Sin webhook público.

\- Consultas, notificaciones y acciones autorizadas.

\- Motor de permisos compartido.

\- Auditoría de acciones sensibles.

\- Sin ejecución de shell arbitraria.



No requerir confirmación redundante para cada acción permitida desde Telegram, pero las operaciones sensibles deberán seguir una política de autorización explícita.



\## 12. Google Calendar



\- OAuth 2.0.

\- PKCE cuando corresponda.

\- Validación de state.

\- Scopes mínimos.

\- Tokens cifrados.

\- Renovación y revocación.

\- Consulta de eventos.

\- Creación y modificación según permisos.

\- Protección de información privada.



La estrategia de callback debe validarse para un entorno LAN.



\## 13. Spotify



\- OAuth oficial.

\- Búsqueda.

\- Consulta de reproducción.

\- Control de reproducción cuando esté permitido.

\- Selección de dispositivos compatibles.

\- Gestión de tokens.



Validar restricciones de API, cuenta y Premium.



No almacenar contraseñas.



\## 14. Domótica



Marcas iniciales de televisores:



\- Samsung.

\- Xiaomi.

\- Kalley.



Luces: marcas pendientes.



Implementar:



\- Descubrimiento.

\- Registro.

\- Identificación de capacidades.

\- Adaptadores.

\- Control.

\- Estado.

\- Autorización.

\- Concurrencia.

\- Diagnóstico.



Tecnologías candidatas:



\- mDNS.

\- SSDP.

\- Google Cast.

\- Android TV.

\- DLNA.

\- APIs de fabricantes.

\- Integración opcional con Home Assistant.



Descubrimiento no garantiza control.



La compatibilidad se valida por modelo y protocolo, no solamente por marca.



\## 15. Gaming y agente Windows



Plataformas:



\- Steam.

\- Epic Games.

\- GOG.



Funciones objetivo:



\- Consultar bibliotecas cuando exista API o mecanismo permitido.

\- Buscar juegos.

\- Consultar instalaciones locales.

\- Abrir launchers.

\- Iniciar juegos.

\- Consultar descargas cuando sea posible.

\- Wake-on-LAN.

\- Consultar CPU, RAM y GPU del PC.

\- Instalar juegos únicamente mediante mecanismos compatibles, autorizados y seguros.



No asumir APIs equivalentes entre plataformas.



\### Agente Windows



Aplicación independiente con:



\- Autenticación.

\- Canal protegido.

\- Lista de acciones permitidas.

\- Ejecución de juegos.

\- Consulta de métricas.

\- Estado de launchers.

\- Reporte de resultados.



No permitir shell arbitraria.



El PC puede estar apagado mientras NEXO ejecuta otras funciones.



\## 16. Persistencia



SQLite almacenará:



\- Configuraciones.

\- Terminales.

\- Permisos.

\- Dispositivos.

\- Integraciones.

\- Metadatos de tokens cifrados.

\- Automatizaciones.

\- Auditoría.

\- Estado persistente estrictamente necesario.



No almacenará:



\- Conversaciones completas.

\- Audio.

\- Transcripciones permanentes.



Utilizar migraciones, transacciones y snapshots consistentes.



\## 17. Observabilidad



Métricas reales y ligeras.



\- psutil cuando corresponda.

\- Logs estructurados.

\- Correlation IDs.

\- Health checks.

\- Diagnósticos.

\- Estado de integraciones.

\- Errores normalizados.



Retención de logs operativos: 30 días.



La auditoría de seguridad tendrá retención diferenciada y control de eliminación administrativa.



No exponer el socket Docker al backend sin análisis de seguridad.



\## 18. Resiliencia



El sistema deberá manejar:



\- Pérdida de Internet.

\- Proveedor LLM no disponible.

\- Reinicio Raspberry.

\- Desconexión de terminal.

\- Error de voz.

\- Dispositivo no disponible.

\- Token expirado.

\- Acción interrumpida.

\- Bloqueo de recurso.

\- Fallo de persistencia.



Las funciones locales continuarán cuando sea técnicamente posible.



No ejecutar automáticamente comandos físicos interrumpidos sin reconciliación.



\## 19. Respaldos GitHub



\*\*Fase final. No activar antes de completar y probar las demás funcionalidades.\*\*



El usuario creará manualmente:



\- Repositorio privado.

\- Token de acceso restringido.



Política:



\- Semanal.

\- Incremental.

\- Cifrado local.

\- Dos puntos de restauración como máximo.

\- Verificación de integridad.

\- Rotación automática.

\- Restauración desde administración.

\- Alertas ante fallos.



No subir SQLite sin cifrar.



No almacenar la clave de recuperación exclusivamente en la Raspberry.



La retención de dos puntos debe contemplar dependencias incrementales e historial Git.



No eliminar el respaldo anterior antes de verificar el nuevo.



La implementación real y las credenciales se configurarán exclusivamente al final.



\## 20. Reutilización de GitHub y software abierto



\*\*Requisito arquitectónico aprobado: evaluar reutilización antes de desarrollar desde cero.\*\*



Fuentes preferidas:



1\. Bibliotecas oficiales.

2\. SDK oficiales.

3\. Proyectos open source mantenidos.

4\. Componentes reutilizables con licencia compatible.

5\. Implementación propia cuando las opciones anteriores no sean adecuadas.



Para cada componente externo evaluar:



\- Repositorio y mantenedor.

\- Licencia.

\- Fecha de mantenimiento.

\- Compatibilidad Python.

\- Compatibilidad ARM64.

\- Consumo de RAM.

\- Dependencias transitivas.

\- Seguridad.

\- Complejidad.

\- API disponible.

\- Facilidad de actualización.

\- Riesgo de abandono.



No copiar código de repositorios sin licencia compatible.



No asumir que un repositorio público concede permiso para redistribuir código.



Registrar dependencias, licencias y procedencia.



No incorporar repositorios enteros cuando una biblioteca pequeña sea suficiente.



No ejecutar scripts remotos sin inspección.



No reutilizar código que solicite credenciales de forma insegura.



La reutilización deberá reducir trabajo y complejidad, no aumentar innecesariamente el peso del sistema.



\## 21. Estrategia de pruebas



Tipos:



\- Unitarias.

\- Integración.

\- API.

\- Seguridad.

\- Concurrencia.

\- Docker.

\- ARM64.

\- Hardware.

\- Rendimiento.

\- Recuperación.



Distinguir:



\- Simulado.

\- Implementado.

\- Probado localmente.

\- Probado con servicio externo.

\- Probado en Raspberry.



\### Criterios críticos



\- No acceder desde terminal no autorizado.

\- Revocación efectiva.

\- Administración protegida.

\- Sesiones aisladas.

\- Rechazo inmediato de comandos conflictivos.

\- Respuesta visible y hablada.

\- Sin secretos en logs.

\- Fallos LLM no bloquean funciones locales.

\- No repetir acciones físicas interrumpidas.

\- Contenedores compatibles con ARM64.

\- Consumo aceptable en 2 GB RAM.

\- Restauración GitHub probada al final.



\## 22. Fases



\### Fase 0 — Preparación



\- Leer especificación.

\- Leer AGENTS.md.

\- Inspeccionar entorno.

\- Validar dependencias.

\- Evaluar reutilización.

\- Proponer estructura mínima.

\- Identificar bloqueos.



\### Fase 1 — Núcleo



\- FastAPI.

\- Docker.

\- SQLite.

\- Seguridad.

\- Terminales.

\- Portal inicial.

\- Métricas.

\- Pruebas.



\### Fase 2 — Sesiones y voz



\- Orquestación de tareas.

\- Concurrencia.

\- WebSocket.

\- Terminales independientes.

\- Robot animado.

\- STT/TTS.

\- Pruebas.



\### Fase 3 — IA y servicios



\- Router LLM.

\- Proveedores.

\- Telegram.

\- OAuth.

\- Google Calendar.

\- Spotify.



\### Fase 4 — Domótica y gaming



\- Dispositivos.

\- Adaptadores.

\- Agente Windows.

\- Steam.

\- Epic.

\- GOG.



\### Fase 5 — Automatización y estabilización



\- Automatizaciones.

\- Notificaciones.

\- Diagnósticos.

\- Seguridad.

\- Rendimiento.

\- Pruebas Raspberry.



\### Fase 6 — Respaldos



\- GitHub privado.

\- Token.

\- Cifrado.

\- Incrementales.

\- Dos puntos.

\- Restauración.

\- Validación final.



\*\*No avanzar de fase sin autorización del usuario.\*\*



\## 23. Estados de requisitos



Utilizar identificadores y estados:



\- APROBADO.

\- PROPUESTO.

\- PENDIENTE.

\- IMPLEMENTADO.

\- PROBADO.

\- LIMITADO.



No convertir una propuesta en requisito aprobado sin confirmación.



\## 24. Decisiones pendientes



\- Motor STT definitivo.

\- Motor TTS y voces definitivas.

\- Política de lectura de estados intermedios.

\- Modelos exactos de televisores.

\- Marcas de iluminación.

\- Capacidades concretas de cada plataforma gaming.

\- Estrategia OAuth callback LAN.

\- Estrategia de certificados Android.

\- Wake-word y eventual APK.

\- Umbrales de rendimiento en Raspberry.

\- Implementación exacta del motor incremental GitHub.

\- Detalles de automatizaciones y futuras integraciones.



Resolverlas en la fase correspondiente, sin bloquear anticipadamente todo el proyecto.



\## 25. Definición de terminado



Una funcionalidad se considera terminada únicamente cuando:



1\. Está implementada.

2\. Está integrada.

3\. Tiene pruebas apropiadas.

4\. Se ejecutaron las pruebas.

5\. Se documentaron los resultados.

6\. Se comprobaron permisos y errores.

7\. Se verificó el consumo de recursos cuando corresponda.

8\. Se indicaron limitaciones reales.

9\. Fue aceptada por el usuario.



\*\*Prioridad: seguridad, correctitud, estabilidad, eficiencia, mantenibilidad y funcionalidad.\*\*

## 26. Gestión de actualizaciones y vulnerabilidades

**Estado: requisito aprobado, implementación pendiente.**

NEXO Home deberá disponer de un gestor de actualizaciones accesible desde el panel administrativo y mediante acciones autorizadas del bot de Telegram.

### Detección

- Comprobar periódicamente versiones de dependencias Python, imágenes Docker, sistema operativo y componentes externos administrados por NEXO.
- Consultar fuentes confiables de vulnerabilidades y avisos de seguridad.
- Diferenciar actualizaciones funcionales de actualizaciones de seguridad.
- Informar versión instalada, versión disponible, vulnerabilidades conocidas y nivel de riesgo.
- No afirmar que un componente es seguro únicamente porque está actualizado.
- Evitar notificaciones duplicadas sobre el mismo hallazgo.

### Notificaciones

Cuando Telegram esté configurado, enviar alertas al usuario autorizado sobre actualizaciones relevantes.

El panel administrativo mostrará actualizaciones pendientes, historial, errores y resultados.

### Ejecución

El administrador podrá iniciar una actualización desde el panel o autorizarla desde Telegram.

La autorización permitirá ejecutar automáticamente un procedimiento controlado:

1. Verificar identidad y permisos.
2. Comprobar compatibilidad.
3. Obtener componentes desde fuentes confiables.
4. Validar integridad y procedencia.
5. Ejecutar pruebas o comprobaciones previas.
6. Preparar un punto de recuperación local cuando corresponda.
7. Desplegar de forma controlada.
8. Comprobar salud y funcionamiento.
9. Revertir si falla, cuando sea técnicamente posible.
10. Informar el resultado.

No ejecutar `pip install --upgrade` indiscriminadamente dentro del contenedor activo.

No otorgar al backend principal acceso irrestricto a Docker ni al sistema operativo.

El motor de actualización deberá operar mediante un componente independiente y de privilegios mínimos, con acciones permitidas explícitamente.

Las actualizaciones del sistema operativo y firmware deberán tener un procedimiento diferenciado y podrán requerir intervención manual o reinicio.

### Seguridad y recuperación

- No ejecutar comandos arbitrarios enviados desde Telegram.
- No permitir que una respuesta de IA autorice actualizaciones.
- No realizar actualizaciones simultáneas.
- No desplegar versiones sin verificar compatibilidad.
- No prometer reversión automática de cambios irreversibles, firmware o migraciones incompatibles.
- Mantener registro de versiones y resultados.
- Preservar el último estado funcional recuperable.

La integración de respaldos cifrados con GitHub seguirá siendo la última fase. Los puntos de recuperación locales utilizados durante actualizaciones son mecanismos operativos distintos de los respaldos remotos.

### Planificación

- Fase 1.4: interfaz administrativa de consulta, sin ejecución real.
- Fase 3: alertas y autorización desde Telegram.
- Fase 5: implementación y pruebas del actualizador.
- Fase 6: integración final de respaldos remotos.

