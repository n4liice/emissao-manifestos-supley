import asyncio
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

from rpa import emitir_manifesto

CONFIG = {
    "url_base":        "https://mandalog.eslcloud.com.br",
    "email":           "automacao.ia@mandalog.com.br",
    "senha":           os.environ.get("ESL_SENHA", ""),
    "motorista":       "ALCEBIADES GALDINO DE LIMA FILHO",
    "placa_veiculo":   "JAM4H35",
    "placa_carreta":   "UFZ4D78",
    "classificacao":   "SUPLEY",
    "notas_fiscais":   ["141144"],
    "cidade_origem":   "Matão",
    "cidade_destino":  "Jundiai",
    "valor_frete":     "3.250,00",
}


async def run():
    numero = await emitir_manifesto(CONFIG, headless=False)
    print(f"\n🎉 Concluído! Manifesto nº {numero}")


if __name__ == "__main__":
    asyncio.run(run())
