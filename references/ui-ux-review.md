# Revisión UI/UX — metodología objetiva del toolkit

Este documento destila una metodología UI/UX **objetiva y propia del
toolkit**: una checklist de doce áreas y una lista mínima de patrones
genéricos de interfaces generadas por IA ("AI-tells"), cada uno exigiendo
evidencia observable. No copia contenido ni listas verbatim de ninguna skill
externa (por ejemplo `frontend-design`): es una síntesis independiente,
calibrada para lo que un reviewer o un autor de steering puede verificar
mirando código o diseño, no gusto.

## Qué es este documento — y qué no es

- **Es** una fuente metodológica para **autorar y mantener**: la usa quien
  escribe el steering frontend/design-system de un proyecto (`/sdd:init`) y
  quien redacta la plantilla del reviewer especializado
  (`templates/reviewer-ui-ux.md`).
- **No es** un referent citable por el panel de revisión. El contrato de
  referent del panel se mantiene cerrado a regla de steering del proyecto,
  requisito (`R#`) o decisión de diseño (`D#`); un finding que solo cite este
  documento no tiene referente válido y no se reporta. La plantilla del
  reviewer lo declara explícitamente.
- **No** introduce ninguna dependencia runtime: el reviewer generado no
  necesita leer este archivo durante la ejecución del panel, y su
  metodología es completamente independiente de que cualquier plugin o
  skill externo esté instalado.

## Autoridad estética

Este documento no prescribe ninguna estética de marca concreta (por ejemplo
las Human Interface Guidelines de Apple, Material Design de Google, o
cualquier otro sistema de diseño de terceros) como estándar normativo. El
steering del proyecto es la autoridad sobre las decisiones estéticas: tokens,
paleta, tipografía y lenguaje visual los define cada proyecto. Toda mención a
sistemas de diseño de terceros en este documento es ilustrativa, nunca una
norma a cumplir.

## Checklist objetiva — las doce áreas

Cada área se formula como señales verificables observando código, markup,
estilos o capturas en el scope — no como juicios de gusto.

### 1. Layout, espaciado y whitespace

- Espaciados repetidos usan una escala consistente (tokens/variables), no
  valores arbitrarios distintos para el mismo propósito.
- No hay elementos que se solapen, se corten o queden pegados al borde del
  contenedor sin margen/padding.
- El ritmo vertical entre bloques es uniforme dentro de una misma jerarquía
  de sección.

### 2. Jerarquía visual

- Existe una diferenciación clara y consistente (tamaño, peso, color) entre
  niveles de título/contenido, no solo variación azarosa.
- El elemento con mayor peso visual corresponde al contenido más relevante
  de la pantalla, no al inverso.

### 3. Tipografía

- El número de familias/tamaños/pesos tipográficos usados está acotado y es
  consistente con los tokens declarados, no una mezcla ad hoc.
- El interlineado y la longitud de línea permiten lectura cómoda (sin líneas
  excesivamente largas o interlineado insuficiente verificable en el CSS).

### 4. Color, contraste y semántica

- El contraste texto/fondo de los pares usados es medible y cumple un
  umbral objetivo (p. ej. WCAG AA) allí donde el steering lo exija.
- El color no es el único portador de significado (estado de error, éxito,
  advertencia) sin un refuerzo adicional (icono, texto, patrón).
- Los colores usados provienen de los tokens declarados, no de valores hex
  sueltos sin relación con la paleta del proyecto.

### 5. Responsive / mobile

- El layout tiene puntos de quiebre verificables (media queries, utilidades
  responsive) y no depende de un único ancho fijo.
- Elementos interactivos y texto permanecen usables (sin overflow, sin
  corte) en los anchos mínimos que el proyecto declare soportar.

### 6. Estados: loading / empty / error / disabled / hover / focus

- Cada estado transaccional (carga, vacío, error) tiene una representación
  explícita en el código, no solo el estado "feliz".
- Los estados `disabled`, `hover` y `focus` tienen estilos distintos y
  observables del estado por defecto.

### 7. Accesibilidad y navegación por teclado

- Los elementos interactivos son alcanzables y operables por teclado (orden
  de tabulación, `:focus-visible` u equivalente presente en el código).
- Los elementos no textuales relevantes (imágenes, iconos con función)
  tienen texto alternativo o etiqueta accesible.
- Los formularios asocian etiquetas con sus campos de forma programática
  (`label`/`for`, `aria-label` u equivalente).

### 8. Consistencia con tokens de diseño y componentes existentes

- Un componente nuevo reutiliza componentes/tokens ya existentes en el
  proyecto para necesidades equivalentes, en vez de reimplementar variantes
  paralelas.
- Los valores de espaciado, color, tipografía y radios coinciden con los
  tokens declarados, no con constantes locales redundantes.

### 9. Formularios e interacción

- Los campos requeridos, sus validaciones y sus mensajes de error están
  expresados en el código (no solo en el happy path).
- El estado de envío (enviando, éxito, error) es observable y evita doble
  envío accidental (botón deshabilitado o equivalente durante el envío).

### 10. Densidad y legibilidad de tablas y dashboards

- Las tablas con muchas columnas/filas tienen un mecanismo de manejo del
  overflow (scroll, columnas fijas, paginación) verificable en el código.
- Los valores numéricos comparables están alineados de forma consistente
  (p. ej. alineación a la derecha) y con formato uniforme.

### 11. Patrones genéricos de UI generada por IA

- Ver la lista de AI-tells más abajo: solo se reporta un patrón cuando hay
  evidencia observable en el código o diseño del scope, nunca una
  afirmación de gusto.

### 12. Claridad de la acción principal y usabilidad

- Existe una acción primaria identificable por pantalla/flujo, y su
  tratamiento visual (jerarquía, posición) la distingue de las acciones
  secundarias.
- El texto de las acciones describe el resultado concreto de la acción, no
  una etiqueta genérica sin relación con el efecto (verificable comparando
  el label con lo que el handler asociado hace).

## AI-tells: patrones genéricos de UI generada por IA

Lista mínima y objetiva, propia del toolkit, de patrones que suelen delatar
una interfaz generada sin dirección propia. Cada patrón solo se reporta
cuando hay **evidencia observable** en el código o el diseño en scope — un
valor concreto, una clase, un token, una captura — nunca como una afirmación
de gusto ("se ve genérico"). Si no hay evidencia localizable, el patrón no
se reporta.

- **Gradiente violeta-azul por defecto sin relación con la marca.** Evidencia:
  un valor de gradiente (CSS, token o clase de utilidad) entre tonos
  índigo/violeta/azul aplicado a elementos destacados (hero, CTA) sin
  correspondencia con los tokens de color declarados en el steering del
  proyecto.
- **Iconografía genérica sin curar.** Evidencia: un set de iconos importado
  y usado de forma extensiva sin que el steering o los tokens del proyecto
  lo mencionen como elección deliberada, o mezclando sets de iconos
  distintos para el mismo nivel de jerarquía.
- **Radio de borde uniforme sin variación jerárquica.** Evidencia: el mismo
  valor de `border-radius` (u otra propiedad de estilo) aplicado a
  componentes de distinto nivel de jerarquía (botón, card, modal) cuando el
  steering o los tokens del proyecto definen una escala distinta por nivel.
- **Sombra "flotante" genérica repetida sin token de profundidad.** Evidencia:
  el mismo valor de `box-shadow` (u otra propiedad equivalente) reutilizado
  en componentes sin relación jerárquica entre sí y sin que exista un token
  de elevación/sombra en el proyecto que lo respalde.
- **Copy de relleno dejado en el código enviado.** Evidencia: cadenas de
  texto de marcador de posición (p. ej. "Lorem ipsum", "Feature description
  goes here", "Título de ejemplo") presentes en el código o el diseño en
  scope, no en un comentario o fixture de test.
- **Bloques de "tres columnas de features" replicados sin variación de
  contenido.** Evidencia: tres o más bloques estructuralmente idénticos
  (icono + título + párrafo) en el mismo layout, sin que el contenido real
  de cada bloque justifique tratamiento repetido.
- **Micro-copy motivacional desconectado del dominio del producto.**
  Evidencia: cadenas de texto en el código o diseño (p. ej. "Empower your
  workflow", "Unlock your potential") sin relación verificable con el
  dominio o la funcionalidad concreta que describen.
- **Emoji usados como iconografía funcional de producto.** Evidencia: emoji
  presentes en el markup/código como reemplazo de iconos funcionales,
  cuando el resto del sistema de iconos del proyecto no usa emoji.

## Cómo se usa en la práctica

- **Autoría de steering** (`/sdd:init`, `templates/steering/frontend.md`):
  esta checklist orienta qué reglas objetivas debe recoger el steering
  frontend/design-system de un proyecto para que existan referentes
  citables por el panel.
- **Autoría del reviewer** (`templates/reviewer-ui-ux.md`): las doce áreas y
  la lista de AI-tells orientan el cuerpo de la plantilla del reviewer
  especializado, que las declara autosuficientes en su propio texto.
- **Durante la ejecución del panel**, ni el reviewer ni ningún otro
  participante necesita leer este archivo: es un documento de referencia
  para quien mantiene el toolkit y sus plantillas, no una entrada del
  contrato de referent del panel.
