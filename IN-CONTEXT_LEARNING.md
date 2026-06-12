Tu tarea es IMPLEMENTAR una funcionalidad
nueva: un módulo que transforma los documentos ya procesados en el "MASTER" de cada
licitación. Programa, integra y prueba el código; no ejecutes la extracción manualmente, aunque puedes ejecutar tu mismo extracciones para probar que esté funcionando.

═══════════════════════════════════════════════════════════════════════
OBJETIVO
═══════════════════════════════════════════════════════════════════════
Añadir una etapa nueva que, por licitación, consuma los textos ya extraídos
(converted-texts) agrupados por partida y produzca el MASTER de esa licitación,
respetando que cada licitación tiene un esquema de columnas distinto.

═══════════════════════════════════════════════════════════════════════
DISEÑO REQUERIDO: DOS CAPAS
═══════════════════════════════════════════════════════════════════════
CAPA 1 — Extracción canónica (estable, igual para todas las licitaciones)
  Extrae 14 hechos regulatorios desde los documentos hacia un esquema canónico fijo.
  Implementación: una llamada al LLM con un system prompt embebido (ver APÉNDICE A),
  con salida JSON validada por un modelo pydantic. Reusa la config de OpenAI/visión
  existente. Procesa por partida; una partida puede producir varios registros (uno
  por medicamento ofertado).

CAPA 2 — Proyección por licitación (configurable, determinista, SIN LLM)
  Toma el JSON canónico y lo convierte al MASTER concreto de cada licitación:
    a) Renombra cada campo canónico al encabezado de columna de esa licitación.
    b) Inyecta el "front-matter" (clave de catálogo, nº de partida, cantidad,
       descripción, unidad, presentación) desde la convocatoria/Anexo, uniendo por
       `partida_ref`.
    c) Calcula los campos derivados (estatus de vigencia, estatus prórroga,
       concatenaciones).
    d) Rellena columnas específicas de esa licitación (p.ej. códigos de barras,
       concentración, tipo de controlado, leyenda sector salud) cuando aplique.
  Cada licitación se describe con UN archivo de configuración (YAML) — ver APÉNDICE B.

═══════════════════════════════════════════════════════════════════════
ENTREGABLES DE CÓDIGO
═══════════════════════════════════════════════════════════════════════
1. Servicio/módulo nuevo `services/master_extractor` siguiendo el patrón de los
   servicios existentes (estructura, Dockerfile, Makefile, tests, healthcheck).
2. Tareas Celery: agrupar documentos por partida, ejecutar Capa 1, ejecutar Capa 2,
   exportar. Disparables por licitación desde el scheduler o un endpoint.
3. Modelo de datos (migración Alembic en schema/rag-schema):
   - Tabla `master_canonical_rows`: registros canónicos crudos (con evidencia y
     confianza por campo, y la tripleta de identidad registro_sanitario +
     denominacion_comercial + empresa_que_da_apoyo).
   - Tabla `master_rows`: filas proyectadas al formato de la licitación.
   - Ambas con columna de licitación (tenant) y trazabilidad al documento fuente.
4. Cargador de configuración de licitación (lee los YAML de APÉNDICE B).
5. Exportador a .xlsx en el formato/columnas exactas de cada licitación (openpyxl).
6. Validación de salida con pydantic; manejo de baja confianza (marcar para revisión,
   nunca inventar).
7. docker-compose: registrar el servicio nuevo. Variables de entorno documentadas en
   .env.example.

═══════════════════════════════════════════════════════════════════════
FUERA DE ALCANCE (no lo implementes en esta tarea)
═══════════════════════════════════════════════════════════════════════
- UI / dashboard / gestor de licitaciones. Solo el backend del módulo de extracción.
- Cambios al pipeline de embeddings o al chat. Quedan intactos.

═══════════════════════════════════════════════════════════════════════
PARÁMETROS / TODO (expón como configuración, no los hardcodees)
═══════════════════════════════════════════════════════════════════════
- `estatus_vigencia_rs`: la regla VIGENTE/VENCIDO NO se calcula contra la fecha de hoy.
  Existe un caso real marcado VENCIDO con fecha de vigencia futura → la referencia es
  una fecha de la licitación/entrega. Expón la fecha de referencia como parámetro de la
  config de licitación.
- `tipo_marca` (COMERCIAL vs GENÉRICA): criterio aún por confirmar; impleméntalo como
  función reemplazable.
- `partida_ref`: cada licitación numera distinto (anexo, progresivo, renglón, clave).
  La unión con el front-matter debe ser parametrizable por licitación.

═══════════════════════════════════════════════════════════════════════
CRITERIOS DE ACEPTACIÓN
═══════════════════════════════════════════════════════════════════════
- Tests unitarios de Capa 2 (mapeo, derivados, unión por partida_ref) con fixtures.
- Test de Capa 1 con un documento de ejemplo y aserción del JSON canónico.
- Una corrida end-to-end por licitación produce un .xlsx con las columnas correctas.
- No se rompe ningún test existente; el pipeline actual sigue funcionando.
- Sigue las convenciones del repo (lint, estructura de servicios, Alembic, env vars).

Antes de programar: explora el repo, propón el plan de archivos y migraciones, y
señala cualquier supuesto del README que no se sostenga en el código real.
