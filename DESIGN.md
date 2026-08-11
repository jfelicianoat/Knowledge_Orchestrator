# Design System

## Direction

Knowledge Orchestrator usa una mesa de operaciones oscura, densa y tranquila: una lista maestra de trabajos a la izquierda y el contexto accionable a la derecha. El diseño evita el aspecto de panel estadístico genérico y hace que cada estado del documento se lea como una entrada de registro operativa.

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

- Cabecera de producto y navegación horizontal fija.
- Barra de acciones y salud del servicio debajo de la navegación.
- En Trabajo, panel maestro y panel de detalle separados por un divisor redimensionable.
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
- Filtros y búsqueda se aplican inmediatamente.
- Estados de carga, vacío, error y selección ausente tienen texto explícito.
- Importar copia los archivos a la carpeta vigilada y confirma cuántos se aceptaron.
- Las acciones solo se habilitan cuando son válidas para el elemento seleccionado.

## Direction Contract

THESIS: el trabajo activo es el producto; se rechaza la cuadrícula de métricas como pantalla principal.  
OWN-WORLD: superficies grafito, divisores precisos, texto claro y cian reservado para acción, selección y actividad.  
STORY: el usuario ve qué documentos avanzan, detecta qué requiere atención y actúa sin buscar otra pantalla.  
FIRST VIEWPORT: navegación y acciones arriba; lista filtrable a la izquierda; diagnóstico y cronología del trabajo seleccionado a la derecha.  
FORM: registro de operaciones maestro-detalle, fiel a la opción visual 2 aprobada.
