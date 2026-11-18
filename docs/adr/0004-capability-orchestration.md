# ADR 0004 — Capacidades explícitas y bloqueos operativos

Estado: implementado para Fase 2 / entregable 2.2.

## Decisión

Separar `orchestration.py` (registro, reglas, autorización, exclusión, ejecución y
resultado) de `interactions.py` (recepción autenticada, contexto acotado y HTTP).
El registro se construye con código local de confianza. No hay API para modificar
capacidades, reglas ni bloqueos, ni importación dinámica.

Cada `Capability` declara identificador único, nombre, permisos y recursos
inmutables, modelo Pydantic de entrada, manejador async, modelo de resultado,
timeout positivo de hasta 60 s y reserva de confirmación. El modelo recibe
`{"text": texto}`; futuros parámetros requieren un contrato validado adicional.
Los recursos son estáticos por capacidad. Los adaptadores futuros deberán
resolverlos desde inventario autorizado, nunca desde claves libres del cliente.
El contexto de ejecución contiene ID de terminal y snapshot efímero de mensajes;
nunca credenciales ni permisos suministrados por el cliente.

Las reglas comparan frases completas normalizadas. Varias capacidades para la
misma frase producen indisponibilidad, sin ejecución. La alternativa explícita
de la aplicación solo genera el mensaje de función no disponible. Los permisos
provienen de la identidad autenticada y se comprueban antes de adquirir recursos.
La reserva de confirmación rechaza siempre: todavía no existe confirmación
consumible por el cliente.

`ResourceLocks.acquire` usa un conjunto de claves canónicas y `threading.Lock`
solo para metadatos. Adquiere todos los recursos o ninguno, incluyendo
`terminal:<id>`, sin await en la sección crítica. Ante un recurso adquirido
devuelve conflicto inmediato. `finally` libera sin puntos de cancelación.
La protección del contexto conserva el 409 `terminal_busy` para otra interacción
del mismo terminal. No hay colas ni reintentos.

Los manejadores deben usar E/S async acotada y propagar cancelación.
`asyncio.timeout` acota ejecución cooperativa; no interrumpe código bloqueante
ni manejadores que supriman cancelación. El único puente a un hilo es el
procesador puro heredado de texto, sin E/S ni efectos externos. Su hilo podría
terminar tras una cancelación, pero no restaura contexto ni ejecuta acciones.
No usar ese puente para futuras operaciones físicas. Los fallos no registran
excepciones, parámetros, resultados ni contenido privado.

## Reutilización evaluada

Se consultaron las API oficiales de [modelos Pydantic](https://docs.pydantic.dev/latest/concepts/models/)
y [cancelación/timeouts de Python 3.12](https://docs.python.org/3.12/library/asyncio-task.html).
Se reutilizan Pydantic instalado (MIT,
[repositorio](https://github.com/pydantic/pydantic)) y biblioteca estándar Python
(PSF-2.0, [repositorio](https://github.com/python/cpython)). Proyectos oficiales
mantenidos; sin copiar código externo ni añadir dependencias o binarios ARM64.
API pequeña integrada con modelos y pruebas existentes. Memoria del gestor
proporcional a recursos activos; medición física pendiente. Riesgos: cooperación
del manejador y disciplina de claves canónicas de cada futuro adaptador.

No se necesita SDK de servicio. Se descartan frameworks de agentes, Redis y
gestores con espera FIFO por peso o semántica innecesarios para exclusión
inmediata en un proceso. SQLite conserva su función de persistencia.

## Contrato y recuperación

Se conservan los seis campos HTTP y las respuestas deterministas de 2.1.
`completed/text` significa respuesta completada; `completed/unavailable`, función
no disponible. `failed/error` distingue por código `forbidden` (403),
`terminal_busy` o `resource_busy` (409), `invalid_input` (422),
`processing_error` (500) y `execution_timeout` (504).
`confirmation_required` (409) queda reservado y bloquea la ejecución.
Autenticación, límites y protección contra abuso existentes siguen vigentes.
Los mensajes sirven para pantalla y futura voz; sin TTS.

El campo de código admite en el futuro `outcome_unknown`: no significa éxito ni
autoriza otro intento. Un timeout/cancelación local no demuestra que una operación
externa terminó. Antes de incorporar efectos externos se requieren reconciliación,
estado desconocido persistente cuando corresponda y auditoría de acciones sensibles.
Esta entrega no implementa ese motor ni acciones externas.

Un worker obligatorio. Contextos y bloqueos se pierden al reiniciar; nunca se
reconstruyen o reejecutan acciones desde mensajes. Varios procesos o réplicas no
comparten exclusión y no están soportados. El gestor en memoria por sí solo no
garantiza seguridad de operaciones físicas tras reinicios.

## Validación

Eventos y TCP/Uvicorn real verifican conflicto inmediato, recursos independientes
simultáneos, atomicidad múltiple, permisos, aislamiento, cancelación, timeout,
excepciones, resultados inválidos, liberación y ausencia de reintentos/logs
privados. Manejadores de prueba solo en `tests/test_orchestration.py`.
Resultados de Windows, Docker y ARM64 en `PROGRESS.md`.
