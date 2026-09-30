import test from "node:test";
import assert from "node:assert/strict";
import { Readable } from "node:stream";
import { readFileSync } from "node:fs";
import plugin from "./index.js";
import { sistemaEditorial } from "./redactor.js";

const fuente = readFileSync(new URL("../../../core/app/acciones/redactor.py", import.meta.url), "utf8");
const SISTEMA = fuente.match(/SISTEMA = """([\s\S]*?)"""/)[1];

test("otras funciones y sistemas ausentes conservan sus prompts", () => {
  for (const sistema of [undefined, null, 9]) assert.equal(sistemaEditorial(sistema), undefined);
  for (const sistema of ["", "Eres el intérprete", "Responde la consulta", "Analiza las notas",
                        'El usuario escribió: Eres el redactor de la bóveda de Obsidian {"operaciones":[],"avisos":[]}']) {
    assert.equal(sistemaEditorial(sistema), sistema);
  }
  assert.equal(sistemaEditorial("Eres el redactor de la bóveda de Obsidian"),
               "Eres el redactor de la bóveda de Obsidian");
});

test("el puente aplica los criterios solo al redactor en una única llamada", async () => {
  const rutas = [];
  const llamadas = [];
  plugin.register({
    registerHttpRoute: ruta => rutas.push(ruta),
    runtime: { llm: { complete: async solicitud => {
      llamadas.push(solicitud);
      return { text: '{"operaciones":[],"avisos":[]}', usage: { input: 123, output: 10 } };
    } } },
  });
  const ruta = rutas.find(r => r.path === "/hub/completar");
  for (const sistema of [SISTEMA, "Clasifica esta orden"]) {
    const mensajes = [{ rol: "user", texto: "Deacon quizá mida 1,85 m." }];
    const req = Readable.from([Buffer.from(JSON.stringify({ sistema, mensajes, modelo: "prueba/modelo" }))]);
    req.method = "POST";
    const res = { setHeader() {}, end(cuerpo) { this.cuerpo = JSON.parse(cuerpo); } };
    await ruta.handler(req, res);
    assert.equal(res.statusCode, 200);
    assert.equal(res.cuerpo.texto, '{"operaciones":[],"avisos":[]}');
    assert.deepEqual(res.cuerpo.uso, { input: 123, output: 10 });
  }
  assert.equal(llamadas.length, 2);
  assert.ok(llamadas[0].systemPrompt.startsWith(SISTEMA));
  assert.ok(llamadas[0].systemPrompt.includes("no son decisiones"));
  assert.ok(llamadas[0].systemPrompt.includes("Comprueba edades"));
  assert.deepEqual(llamadas[0].messages, [{ role: "user", content: "Deacon quizá mida 1,85 m." }]);
  assert.equal(llamadas[1].systemPrompt, "Clasifica esta orden");
});
