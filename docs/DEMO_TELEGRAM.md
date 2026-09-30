# Demo del Hub creativo

El acabado visual se genera en el core: no consume tokens adicionales ni necesita nuevas dependencias. Telegram muestra títulos en negrita, iconos y listas; las consultas admiten títulos Markdown, negritas y bloques de código. La voz sigue usando el texto original.

## Recorrido de presentación

1. Envía `/start`: bienvenida con botones para proyectos, tareas y tokens.
2. Envía `/proyecto nuevo Demo creativa`: activa el proyecto y pregunta qué guardar primero.
3. Envía `/nota idea: una ciudad flotante donde los barcos son peces`: confirma el guardado. Con redactor activo, muestra los archivos donde organizó la idea.
4. Envía `/tarea preparar el storyboard`: confirmación con título visual.
5. Pulsa **Mis tareas** en la bienvenida: muestra los pendientes del proyecto actual.
6. Envía `/tokens`: muestra el consumo registrado; los comandos locales no llaman a modelos.
7. Abre Obsidian para enseñar las notas y tareas guardadas.

Ejemplo de respuesta al guardar una tarea:

> **✅ Un paso más hacia tu idea**
>
> Tarea agregada a Proyectos/Demo creativa/tareas.md

Los mensajes largos se reparten en varias respuestas. Los botones aparecen en la última. Los caracteres especiales de nombres y respuestas se escapan para que Telegram los muestre correctamente.

Para aplicar el código a un contenedor ya construido, reconstruye el servicio desde la raíz del repositorio:

```powershell
docker compose up -d --build core
```

Después envía `/start` para ver la nueva bienvenida.
