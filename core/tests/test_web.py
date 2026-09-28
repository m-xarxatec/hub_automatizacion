import asyncio

import httpx
from fastapi.testclient import TestClient

from app.entradas.web import servidor as web


def test_salud():
    cliente = TestClient(web.crear_app("pc-casa"))
    datos = cliente.get("/salud").json()
    assert datos["ok"] is True and datos["servidor"] == "pc-casa"


def test_servidor_arranca_y_se_detiene():
    async def go():
        srv = web.servidor(web.crear_app("x"), puerto=18080)
        tarea = asyncio.create_task(srv.serve())
        for _ in range(50):
            if srv.started:
                break
            await asyncio.sleep(0.05)
        async with httpx.AsyncClient(trust_env=False) as cli:
            resp = await cli.get("http://127.0.0.1:18080/salud")
        srv.should_exit = True
        await tarea
        return resp.status_code
    assert asyncio.run(go()) == 200
