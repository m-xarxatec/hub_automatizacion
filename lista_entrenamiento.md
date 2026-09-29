# Lista de entrenamiento del router

Frases para enviar al bot (por voz o por texto) y enseñarle al router las que hoy confunde o
duda. **Todas se midieron con el router de la laptop el 2026-09-29** (120 ejemplos, sin
correcciones): las que ya clasifica con seguridad no están aquí porque no le enseñarían nada.

## Antes de empezar

1. `/proyecto nuevo Pruebas`: todo lo que se guarde queda en ese proyecto y se puede borrar
   después sin tocar tus proyectos reales.
2. Envía **cada frase una sola vez**, tal cual o con tus palabras. Por voz es mejor: el router
   aprende también cómo transcribe Whisper tu manera de hablar.
3. Solo el equipo que sea servidor en ese momento aprende. No importa cuál: la carpeta
   `hub-router` de Syncthing lleva lo aprendido al otro (ver README §2).

## Cómo aprende (y qué cuesta)

- Si el bot **duda**, primero pregunta a ChatGPT (~350 tokens). Si ChatGPT está seguro, lo
  ejecuta y la frase queda en `aprendidos.yaml` sin preguntarte nada.
- Si ChatGPT tampoco está seguro, el bot te muestra **botones**: elige la acción de la columna
  "Respuesta". Tu elección va a `correcciones.yaml` y siempre gana a la de la IA.
- El botón elegido **se ejecuta de verdad**:
  - *Nota* y *Tarea*: se guardan en `Pruebas` (gratis).
  - *Consulta*: ChatGPT responde (~300 tokens).
  - *Imagen*: genera una imagen (~1 min, gasta cuota de ChatGPT).
  - *Análisis*: aprende al pulsarlo; luego pulsa **Cancelar** al elegir modelo y no gasta nada.
  - *Búsqueda*: responde "fase 3" (gratis).
- Si el bot ejecuta sin preguntar, esa frase ya la sabe: pasa a la siguiente.

## 1. Prioridad alta: hoy se equivoca, pero pregunta

| ✓ | Frase | Hoy cree que es | Respuesta |
|---|---|---|---|
| [ ] | No se me puede olvidar comprar tinta | nota (0,45) | Tarea |
| [ ] | Ojo con la entrega del jueves | nota (0,45) | Tarea |
| [ ] | Me puedes decir cuánto mide una tira de webtoon | nota (0,45) | Consulta |
| [ ] | Oye, y cuántos capítulos suele tener una temporada | nota (0,45) | Consulta |
| [ ] | Quisiera saber cuánto cobra un colorista | nota (0,45) | Consulta |
| [ ] | Tienes idea de cómo se numeran las páginas | nota (0,45) | Consulta |
| [ ] | Sabes si Clip Studio sirve para webtoon | análisis (0,54) | Consulta |
| [ ] | Una duda, cada cuánto se publica un webtoon | análisis (0,65) | Consulta |
| [ ] | Crees que encaja que el protagonista pierda sus poderes | nota (0,66) | Análisis |
| [ ] | Funciona que el zorro hable desde el principio | nota (0,69) | Análisis |
| [ ] | Hay algo que no cuadre en la historia del maestro | nota (0,45) | Análisis |
| [ ] | Está bien planteado el conflicto entre los hermanos | nota (0,63) | Análisis |
| [ ] | Enséñame cómo sería el protagonista de niño | nota (0,45) | Imagen |
| [ ] | A ver cómo quedaría la portada en tonos rojos | nota (0,45) | Imagen |
| [ ] | Columnas rotas cubiertas de musgo | imagen (0,74) | Nota |
| [ ] | Una espada que pesa lo que pesan tus culpas | consulta (0,63) | Nota |

## 2. Acierta, pero sin seguridad (confirma con botones)

| ✓ | Frase | Hoy cree que es | Respuesta |
|---|---|---|---|
| [ ] | Tengo pendiente escanear los bocetos | tarea (0,61) | Tarea |
| [ ] | Y eso cómo se hace en Photoshop | consulta (0,80) | Consulta |
| [ ] | Me explicas la regla de los tercios | consulta (0,56) | Consulta |
| [ ] | Qué opinas de la trama hasta ahora | análisis (0,55) | Análisis |
| [ ] | Dibújame el templo en ruinas de noche | imagen (0,77) | Imagen |
| [ ] | Me haces un dibujo de la hermana menor | imagen (0,53) | Imagen |
| [ ] | Faroles de papel en el puente | nota (0,45) | Nota |

## 3. Frases cortas y ambiguas (tú decides qué significan)

Sin contexto, lo más útil es que una frase suelta sea una **nota**; elige otra cosa si para ti
significa otra.

| ✓ | Frase | Hoy cree que es | Sugerida |
|---|---|---|---|
| [ ] | El templo | nota (0,56) | Nota |
| [ ] | Lo del capítulo tres | nota (0,56) | Nota |
| [ ] | Colores para la villana | consulta (0,57) | Nota |
| [ ] | La escena del puente | imagen (0,56) | Nota |
| [ ] | Armaduras | consulta (0,51) | Nota |
| [ ] | El zorro de noche | nota (0,72) | Nota |

## 4. No las envíes: se equivoca con seguridad y no pregunta

El bot las ejecuta directamente, sin botones para corregir. Hay que añadirlas a mano a
`core/app/router/datos/ejemplos.yaml` (ejemplos base, van en git).

| Frase | Haría | Debería ser |
|---|---|---|
| Máscaras de zorro | **imagen (0,87): generaría una imagen** | Nota |
| Quedé en mandarle las páginas a Laura | nota (0,80) | Tarea |
| Te parece bien que la villana muera en el capítulo diez | nota (0,94) | Análisis |

## Al terminar

1. `/estado` muestra cuántas correcciones y aprendidos faltan por entrenar.
2. `/reentrenar` (unos 5 min en la laptop). Después, las frases de la sección 1 deberían
   ejecutarse sin preguntar; si alguna sigue fallando, anótala aquí.
3. `/proyecto ninguno` para volver a guardar en la bandeja, y borra `Proyectos/Pruebas` cuando
   ya no la necesites.
