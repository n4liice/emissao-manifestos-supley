import asyncio
import os
from typing import List, Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from rpa import emitir_manifesto

app = FastAPI(title="Emissao de Manifestos")

ESL_EMAIL = os.environ.get("ESL_EMAIL", "automacao.ia@mandalog.com.br")
ESL_SENHA = os.environ.get("ESL_SENHA", "")
ESL_URL   = os.environ.get("ESL_URL", "https://mandalog.eslcloud.com.br")
API_KEY   = os.environ.get("API_KEY", "")

_sem = asyncio.Semaphore(1)


class ManifestoInput(BaseModel):
    motorista: str
    placa_veiculo: str
    placa_carreta: Optional[str] = None
    classificacao: str
    tipo_motorista: str                        # "Dedicado" | "Combinado" | "Tabela"
    tipo_nota: str                             # "nf" | "oc"
    notas_fiscais: Optional[List[str]] = None  # usado quando tipo_nota = "nf"
    referencias: Optional[List[str]] = None   # usado quando tipo_nota = "oc"
    cidade_origem: str
    cidade_destino: str
    valor_frete: Optional[str] = None         # usado quando tipo_motorista != "Tabela"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/emitir")
async def emitir(body: ManifestoInput, x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key invalida")

    placa_carreta = body.placa_carreta
    if not placa_carreta or len(placa_carreta.strip()) < 4:
        placa_carreta = None

    config = {
        "url_base":        ESL_URL,
        "email":           ESL_EMAIL,
        "senha":           ESL_SENHA,
        "motorista":       body.motorista,
        "placa_veiculo":   body.placa_veiculo,
        "placa_carreta":   placa_carreta,
        "classificacao":   body.classificacao,
        "tipo_motorista":  body.tipo_motorista,
        "tipo_nota":       body.tipo_nota,
        "notas_fiscais":   body.notas_fiscais or [],
        "referencias":     body.referencias or [],
        "cidade_origem":   body.cidade_origem,
        "cidade_destino":  body.cidade_destino,
        "valor_frete":     body.valor_frete or "",
    }

    print(
        f"[API] Requisicao recebida | motorista={body.motorista} | "
        f"tipo_nota={body.tipo_nota} | tipo_motorista={body.tipo_motorista}",
        flush=True
    )

    async with _sem:
        print("[API] Iniciando RPA (semaforo adquirido)", flush=True)
        try:
            numero = await emitir_manifesto(config, headless=True)
            return {"sucesso": True, "numero_manifesto": numero}
        except Exception as e:
            print(f"[API] Erro: {e}", flush=True)
            return {"sucesso": False, "erro": str(e)}
