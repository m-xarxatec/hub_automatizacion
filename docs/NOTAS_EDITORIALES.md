# Mejora de la redacción sin modificar el core

El bot organiza notas con el redactor de `core/app/acciones/redactor.py`. El puente de OpenClaw llama al modelo directamente, así que las instrucciones del agente general de OpenClaw no intervienen en este flujo.

`openclaw/plugins/hub-puente/redactor.js` añade criterios editoriales al prompt recibido exclusivamente cuando reconoce el contrato del redactor. Mantiene su JSON y hace la misma llamada al modelo. El core sigue validando rutas y cobertura, y aplicando las operaciones sin borrar ni reescribir notas anteriores.

## Qué se busca mejorar

- Separar apariencia, personalidad, relaciones e historia en las fichas; reutilizar secciones existentes.
- Limpiar órdenes y muletillas, conservando todos los detalles y el carácter tentativo de una idea.
- Evitar repetir hechos que ya constan en el contexto enviado al modelo.
- Detectar contradicciones de fechas, edades y parentescos, señalando el dato nuevo como pendiente de confirmar.
- Conservar escenas, diálogos y relaciones de causa y efecto completos.

Las instrucciones añaden un coste de entrada al redactar notas. No añaden llamadas ni texto a los prompts de consulta, interpretación, router o análisis. La cantidad exacta de tokens depende del modelo; no se ha medido con un proveedor real.

## Ejemplo para la demo

Mensaje: «Anota que el protagonista quizá mida 1,85 m, lleva tatuajes excepto en la cara y va en moto. Su hija se llama Mara».

Resultado esperado: apariencia tentativa, tatuajes y moto en la ficha del protagonista; relación con Mara en Relaciones, con enlace si existe su ficha. El modelo debe conservar «quizá», omitir «anota que» y evitar copiar la misma descripción en varias fichas.

Las pruebas sin conexión comprueban que el puente reconoce el prompt real del core, modifica solo el prompt del redactor, conserva mensajes y respuesta y hace una sola llamada por petición. La calidad de la redacción requiere una prueba posterior con el modelo real; no se han enviado notas ni gastado tokens para validar este cambio.

## Aplicación posterior

El plugin se copia dentro de la imagen. Cuando corresponda desplegar, basta reconstruir OpenClaw para esta mejora:

```powershell
docker compose --profile consulta up -d --build --no-deps openclaw
```

El core no necesita reconstrucción para estos criterios. Los cambios no editan las notas existentes y no tendrán efecto en el servidor de casa hasta que se desplieguen allí.
