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

# Garante que apenas 1 RPA rode por vez (browsers simultâneos se interferem)
_sem = asyncio.Semaphore(1)


class ManifestoInput(BaseModel):
    motorista: str
    placa_veiculo: str
    placa_carreta: Optional[str] = None
    classificacao: str
    notas_fiscais: List[str]
    cidade_origem: str
    cidade_destino: str
    valor_frete: str


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/emitir")
async def emitir(body: ManifestoInput, x_api_key: Optional[str] = Header(None)):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API Key invalida")

    # Normaliza placa_carreta: ignora valores vazios, nulos ou inválidos ("?", "-", etc.)
    placa_carreta = body.placa_carreta
    if not placa_carreta or len(placa_carreta.strip()) < 4:
        placa_carreta = None

    config = {
        "url_base":      ESL_URL,
        "email":         ESL_EMAIL,
        "senha":         ESL_SENHA,
        "motorista":     body.motorista,
        "placa_veiculo": body.placa_veiculo,
        "placa_carreta": placa_carreta,
        "classificacao": body.classificacao,
        "notas_fiscais": body.notas_fiscais,
        "cidade_origem": body.cidade_origem,
        "cidade_destino": body.cidade_destino,
        "valor_frete":   body.valor_frete,
    }

    print(f"[API] Requisicao recebida | motorista={body.motorista} | carreta={placa_carreta} | frete={body.valor_frete}")

    async with _sem:
        print(f"[API] Iniciando RPA (semaforo adquirido)")
        try:
            numero = await emitir_manifesto(config, headless=True)
            return {"sucesso": True, "numero_manifesto": numero}
        except Exception as e:
            print(f"[API] Erro: {e}")
            return {"sucesso": False, "erro": str(e)}
