import re
import asyncio
from playwright.async_api import async_playwright


async def emitir_manifesto(config: dict, headless: bool = True) -> str:
    """Executa o RPA completo e retorna o número do manifesto criado."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            await login(page, config)
            await novo_manifesto(page, config)
            await preencher_motorista(page, config["motorista"])
            await verificar_e_corrigir_veiculo(page, config["placa_veiculo"])
            if config.get("placa_carreta"):
                await verificar_e_corrigir_carreta(page, config["placa_carreta"])
            await preencher_classificacao(page, config["classificacao"])
            await salvar_manifesto(page)

            for nota in config["notas_fiscais"]:
                await inserir_nota_fiscal(page, nota)

            await ir_para_aba_vale_frete(page)
            await preencher_frete(
                page,
                config["cidade_origem"],
                config["cidade_destino"],
                config["valor_frete"],
            )
            await salvar_manifesto(page)
            return await obter_numero_manifesto(page)
        finally:
            await browser.close()


async def login(page, config):
    await page.goto(f"{config['url_base']}/manifests")
    await page.wait_for_load_state("networkidle")
    if "/sign_in" in page.url:
        print("Sessao expirada. Fazendo login...")
        await page.fill("input[name='user[email]']", config["email"])
        await page.fill("input[name='user[password]']", config["senha"])
        await page.click("input[type='submit'], button:has-text('Entrar')")
        await page.wait_for_url("**/manifests**", timeout=15000)
        print("Login realizado.")
    else:
        print("Sessao ativa.")


async def novo_manifesto(page, config):
    await page.goto(f"{config['url_base']}/manifests")
    await page.wait_for_load_state("networkidle")
    await page.click("a:has-text('Novo manifesto')")
    await page.wait_for_url("**/manifests/new**", timeout=10000)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    print("Pagina de novo manifesto aberta.")


async def _selecionar_via_modal(page, div_class, termo, label):
    locator = page.locator(f"div.{div_class} a.listModal")
    await locator.scroll_into_view_if_needed()
    await locator.click()
    await page.wait_for_selector("input[placeholder='Filtrar...']", timeout=8000)
    await page.fill("input[placeholder='Filtrar...']", termo)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2000)
    await page.click("table tbody tr:first-child button:has-text('Selecionar'), "
                     "table tbody tr:first-child a:has-text('Selecionar')")
    await page.wait_for_timeout(1500)
    print(f"{label} '{termo}' selecionado(a).")


async def preencher_motorista(page, motorista):
    await _selecionar_via_modal(page, "manifest_main_driver", motorista, "Motorista")


async def verificar_e_corrigir_veiculo(page, placa_esperada):
    await page.wait_for_timeout(500)
    placa_atual = await page.eval_on_selector(
        "select#vehicle",
        "el => el.options[el.selectedIndex]?.text || ''"
    )
    placa_atual = placa_atual.strip().upper()
    print(f"Placa atual: '{placa_atual}' | Esperada: '{placa_esperada}'")
    if placa_esperada.upper() not in placa_atual:
        await _selecionar_via_modal(page, "manifest_vehicle", placa_esperada, "Veiculo")
    else:
        print("Placa correta.")


async def verificar_e_corrigir_carreta(page, placa_esperada):
    await page.wait_for_timeout(500)
    placa_atual = await page.eval_on_selector(
        "select#trailer_1",
        "el => el.options[el.selectedIndex]?.text || ''"
    )
    placa_atual = placa_atual.strip().upper()
    print(f"Carreta atual: '{placa_atual}' | Esperada: '{placa_esperada}'")
    if placa_esperada.upper() not in placa_atual:
        await _selecionar_via_modal(page, "manifest_trailer_1", placa_esperada, "Carreta")
    else:
        print("Carreta correta.")


async def preencher_classificacao(page, classificacao):
    container = page.locator("#select2-manifest_classification-container")
    await container.scroll_into_view_if_needed()
    await container.click()
    search = page.locator(".select2-dropdown .select2-search__field, "
                          ".select2-container--open .select2-search__field")
    await search.first.wait_for(state="visible", timeout=5000)
    await search.first.fill(classificacao)
    await page.wait_for_timeout(2000)
    await page.click(f".select2-results__option:has-text('{classificacao}')")
    await page.wait_for_timeout(500)
    print(f"Classificacao '{classificacao}' selecionada.")


async def salvar_manifesto(page):
    try:
        if await page.locator(".swal2-container.swal2-shown").is_visible(timeout=1500):
            print("Modal SweetAlert aberto — fechando antes de salvar...")
            await page.click(".swal2-confirm, .swal2-cancel, button:has-text('OK')", timeout=3000)
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    btn = page.locator("button.btn-primary:has(.fa-save), button.btn-primary:has-text('Salvar')")
    await btn.last.scroll_into_view_if_needed()
    await btn.last.click()
    await page.wait_for_selector("text=Tem certeza que deseja salvar", timeout=5000)
    await page.click("button:has-text('Sim')")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)
    print("Manifesto salvo.")


async def inserir_nota_fiscal(page, nota):
    container = page.locator("#selected-tab-deliveries #select2-term-container")
    await container.scroll_into_view_if_needed()
    await container.click()
    await page.wait_for_timeout(800)
    await page.keyboard.type(nota)
    await page.wait_for_timeout(2500)
    try:
        await page.click(f".select2-results__option:has-text('{nota}')", timeout=3000)
    except Exception:
        await page.keyboard.press("Enter")
    await page.wait_for_timeout(4000)
    try:
        if await page.is_visible("text=Frete possui entrega vinculada", timeout=2000):
            print(f"Nota {nota} ja vinculada (aviso ignorado).")
            await page.click("button:has-text('OK')")
            await page.wait_for_timeout(1000)
    except Exception:
        pass
    print(f"Nota fiscal '{nota}' inserida.")
    print("Recarregando pagina para confirmar insercao da NF...")
    await page.reload()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    print("Pagina recarregada.")


async def ir_para_aba_vale_frete(page):
    aba = page.locator("a:has-text('Vale-Frete'), li:has-text('Vale-Frete') a")
    await aba.first.scroll_into_view_if_needed()
    await aba.first.click()
    await page.wait_for_timeout(1500)
    print("Aba Vale-Frete aberta.")


async def preencher_frete(page, cidade_origem, cidade_destino, valor_frete):
    print(f"Preenchendo cidade origem: {cidade_origem}")
    await page.click("#select2-calculation_origin_city-container")
    await page.wait_for_timeout(800)
    await page.wait_for_selector(".select2-container--open input.select2-search__field", state="visible", timeout=5000)
    await page.keyboard.type(cidade_origem, delay=80)
    await page.wait_for_selector(".select2-results__option:not(.select2-results__option--loading)", state="visible", timeout=10000)
    await page.click(f".select2-results__option:has-text('{cidade_origem}')")
    await page.wait_for_timeout(800)
    print(f"Cidade origem: {cidade_origem}")

    print(f"Preenchendo cidade destino: {cidade_destino}")
    await page.click("#select2-calculation_destination_city-container")
    await page.wait_for_timeout(800)
    await page.wait_for_selector(".select2-container--open input.select2-search__field", state="visible", timeout=5000)
    await page.keyboard.type(cidade_destino, delay=80)
    await page.wait_for_timeout(2000)
    await page.wait_for_selector(
        "#select2-calculation_destination_city-results .select2-results__option",
        state="visible", timeout=8000
    )
    await page.click("#select2-calculation_destination_city-results .select2-results__option:first-child")
    await page.wait_for_timeout(800)
    print(f"Cidade destino: {cidade_destino}")

    print(f"Preenchendo valor do frete: R$ {valor_frete}")
    apenas_digitos = valor_frete.split(",")[0].replace(".", "")
    campo = page.locator("#closed_freight_subtotal")
    await campo.click()
    await page.keyboard.press("Control+a")
    await page.keyboard.press("Delete")
    await page.wait_for_timeout(300)
    await campo.type(apenas_digitos)
    await page.wait_for_timeout(500)
    print(f"Valor frete: R$ {valor_frete}")


async def obter_numero_manifesto(page):
    try:
        texto = await page.text_content("span.caption-subject")
        if texto:
            m = re.search(r'\d+', texto)
            if m:
                return m.group(0)
    except Exception:
        pass
    m = re.search(r'/manifests/(\d+)', page.url)
    if m:
        return m.group(1)
    return ""
