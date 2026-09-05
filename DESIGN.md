# Design System

## Direction

Knowledge Orchestrator usa un centro documental oscuro, denso y tranquilo. Separa el resumen, el trabajo operativo y la biblioteca publicada, pero conserva el patrón maestro-detalle cuando hay que consultar o actuar sobre un documento.

## Color

- Fondo raíz: `#0b1115`.
- Superficie principal: `#11191e`.
- Superficie elevada: `#182228`.
- Borde: `#2b3941`.
- Texto principal: `#f2f6f8`.
- Texto secundario: `#aebbc2`.
- Acento y foco: `#25c5df`.
- Acento seleccionado: `#123649`.
- Correcto: `#42d17d`.
- Atención: `#f5ad2d`.
- Error: `#ff646d`.

## Typography

Segoe UI es la tipografía de sistema. Los títulos usan 18–22 px equivalentes y peso semibold; los encabezados de sección 12–14 px semibold; el cuerpo 10–11 px. Identificadores y rutas pueden usar Consolas cuando el dato técnico lo justifique.

## Layout

- Cabecera de producto y navegación horizontal fija: Resumen, Documentos, Biblioteca, Revisión, Organización y Ajustes.
- Barra de acciones y salud del servicio debajo de la navegación.
- En Documentos, panel maestro y panel de detalle separados por un divisor redimensionable.
- En Biblioteca, catálogo de notas publicadas y detalle de su ubicación en Obsidian.
- La lista presenta nombre y ruta juntos, con estado, antigüedad y última actualización alineados.
- El detalle agrupa resumen, explicación, cronología y acciones; no usa modales salvo confirmaciones destructivas.

## Components

- Botón primario cian para la acción principal del contexto.
- Botones secundarios oscuros con borde visible.
- Filtros segmentados con etiqueta y recuento.
- Filas seleccionadas con fondo azul petróleo y borde/foco cian.
- Mensajes de incidencia con título humano, explicación y recuperación.
- Barra de estado inferior con evento más reciente y actualización automática.

## Interaction

- La selección de un trabajo persiste durante las actualizaciones automáticas.
- Si un filtro o una actualización oculta el elemento seleccionado, la interfaz queda sin selección y nunca reasigna una acción a otro documento de forma automática.
- Filtros y búsqueda se aplican inmediatamente.
- Estados de carga, vacío, error y selección ausente tienen texto explícito.
- Importar copia los archivos a la carpeta vigilada y confirma cuántos se aceptaron.
- Las acciones solo se habilitan cuando son válidas para el elemento seleccionado.

## Direction Contract

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas como pantalla principal.  
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado para acción, selección y actividad.  
STORY: el usuario entiende qué documentos avanzan, cuáles requieren atención y qué conocimiento ya está disponible en los vaults.
FIRST VIEWPORT: resumen documental con accesos a trabajo, incidencias, revisión y biblioteca; Documentos conserva el diagnóstico maestro-detalle.
FORM: centro documental con vistas especializadas y registros maestro-detalle donde la tarea lo exige.
