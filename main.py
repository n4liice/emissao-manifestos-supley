import asyncio
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

from rpa import emitir_manifesto

CONFIG = {
    "url_base":       "https://mandalog.eslcloud.com.br",
    "email":          "automacao.ia@mandalog.com.br",
    "senha":          os.environ.get("ESL_SENHA", ""),
    "motorista":      "CARLOS HENRIQUE COUTINHO",
    "placa_veiculo":  "DPC5B98",
    "placa_carreta":  "TLL4D81",
    "classificacao":  "ARCOR",
    "tipo_motorista": "DEDICADO",
    "tipo_nota":      "nf",
    "notas_fiscais":  ["295584"],
    "referencias":    [],
    "observacao":     "",
    "cidade_origem":  "CAMPINAS",
    "cidade_destino": "EXTREMA",
    "valor_frete":    "R$0,00",
    "tabela_preco":   "",
    "data_frete":     "02/07/2026",
}


async def run():
    try:
        numero = await emitir_manifesto(CONFIG, headless=False)
        print(f"\nConcluido! Manifesto nr {numero}")
    except Exception as e:
        print(f"\nERRO: {e}")
        input("\nPressione ENTER para fechar...")


if __name__ == "__main__":
    asyncio.run(run())
