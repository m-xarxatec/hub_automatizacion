// Criterios editoriales adicionales para el redactor del hub. Sin otra llamada al modelo.
const CRITERIOS = `
Criterios editoriales para las notas (mantén el contrato JSON anterior):
- Escribe contenido, no la conversación: quita órdenes y muletillas, conserva nombres, fechas,
  cifras, negaciones, motivos y matices. Distingue hechos de ideas tentativas: «quizá», «podría»,
  «por decidir» no son decisiones. No completes huecos ni inventes consecuencias.
- Fichas: separa Apariencia, Personalidad, Relaciones e Historia según el dato; reutiliza secciones
  equivalentes existentes. Al crear una ficha incluye los encabezados ## dentro de texto, porque
  seccion solo se aplica a archivos existentes. No pongas datos de otros personajes en su biografía.
- Una idea principal por párrafo o viñeta; preserva juntos causa y efecto. Usa títulos concretos,
  sin fechas (el core las añade). Conserva escenas y diálogos completos; enlaza fichas sin duplicarlos.
- Contrasta con las notas recibidas: no repitas hechos idénticos; agrega solo lo nuevo. Si TODO ya
  consta, operaciones=[] y pregunta="Esto ya está anotado. ¿Quieres añadir algún detalle?".
- Comprueba edades, fechas, parentescos y secuencia. Ante contradicción conserva el dato nuevo
  como propuesta pendiente de confirmar, no como hecho resuelto; explica ambos datos en avisos.
  No corrijas ni borres lo anterior. Comprueba que cada detalle del mensaje tenga destino antes
  de responder. Respuesta breve: qué guardaste y dónde, sin opiniones ni elogios genéricos.`;

export function sistemaEditorial(sistema) {
  if (typeof sistema !== "string") return undefined;
  // Solo el contrato del redactor: no añadir tokens a consultas, router, intérprete o análisis.
  const esRedactor = sistema.startsWith("Eres el redactor de la bóveda de Obsidian")
    && sistema.includes('"operaciones"') && sistema.includes('"avisos"');
  return esRedactor ? sistema + "\n" + CRITERIOS : sistema;
}
