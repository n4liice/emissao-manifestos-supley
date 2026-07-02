import asyncio
import os
import sys
sys.stdout.reconfigure(encoding='utf-8')

from playwright.async_api import async_playwright
from rpa import login, novo_manifesto, preencher_motorista, verificar_e_corrigir_veiculo, \
    verificar_e_corrigir_carreta, preencher_classificacao, salvar_manifesto, \
    inserir_referencia_oc, ir_para_aba_vale_frete, preencher_frete, obter_numero_manifesto

CONFIG = {
    "url_base":       "https://mandalog.eslcloud.com.br",
    "email":          "automacao.ia@mandalog.com.br",
    "senha":          os.environ.get("ESL_SENHA", ""),
    "motorista":      "ADRIANO JOSÉ DOS SANTOS",
    "placa_veiculo":  "BSF1284",
    "placa_carreta":  "ALH3D10",
    "classificacao":  "ARCOR",
    "tipo_motorista": "TABELA",
    "tipo_nota":      "oc",
    "notas_fiscais":  [],
    "referencias":    ["52175357"],
    "cidade_origem":  "BRAGANÇA",
    "cidade_destino": "MANDALOG",
    "valor_frete":    "",
}


async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await login(page, CONFIG)
            await novo_manifesto(page, CONFIG)
            await preencher_motorista(page, CONFIG["motorista"])
            await verificar_e_corrigir_veiculo(page, CONFIG["placa_veiculo"])
            if CONFIG.get("placa_carreta"):
                await verificar_e_corrigir_carreta(page, CONFIG["placa_carreta"])
            await preencher_classificacao(page, CONFIG["classificacao"])
            await salvar_manifesto(page)

            for ref in CONFIG["referencias"]:
                await inserir_referencia_oc(page, ref)

            await ir_para_aba_vale_frete(page)
            await preencher_frete(page, CONFIG["cidade_origem"], CONFIG["cidade_destino"], CONFIG["valor_frete"], CONFIG["tipo_motorista"])
            await salvar_manifesto(page)
            numero = await obter_numero_manifesto(page)
            print(f"\nConcluido! Manifesto nr {numero}")
        except Exception as e:
            print(f"\nERRO: {e}")
            input("\nChrome aberto para inspeção. Pressione ENTER para fechar...")
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(run())
