import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _normalizar_frete(valor: str) -> tuple:
    """Retorna (inteiro, centavos). Ex: 'R$ 2.421,60' -> ('2421', '60')"""
    v = re.sub(r'[^\d.,]', '', valor)
    if "," in v:
        inteiro, centavos = v.split(",", 1)
        inteiro = inteiro.replace(".", "")
        centavos = centavos[:2].ljust(2, "0")
    elif "." in v:
        inteiro, centavos = v.split(".", 1)
        centavos = centavos[:2].ljust(2, "0")
    else:
        inteiro, centavos = v, "00"
    return inteiro, centavos


async def emitir_manifesto(config: dict, headless: bool = True) -> str:
    _log(f"[RPA] Iniciando | motorista={config['motorista']} | veiculo={config['placa_veiculo']} | frete={config['valor_frete']}")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            _log("[RPA] Etapa 1/8: Login")
            await login(page, config)
            _log("[RPA] Etapa 2/8: Novo manifesto")
            await novo_manifesto(page, config)
            _log("[RPA] Etapa 3/8: Motorista")
            await preencher_motorista(page, config["motorista"])
            _log("[RPA] Etapa 4/8: Veiculo/Carreta")
            await verificar_e_corrigir_veiculo(page, config["placa_veiculo"])
            if config.get("placa_carreta"):
                await verificar_e_corrigir_carreta(page, config["placa_carreta"])
            _log("[RPA] Etapa 5/8: Classificacao")
            await preencher_classificacao(page, config["classificacao"])
            _log("[RPA] Etapa 6/8: 1o salvamento")
            await salvar_manifesto(page)
            _log("[RPA] Etapa 7/8: Notas fiscais")
            notas_validas = [
                n for n in config["notas_fiscais"]
                if n and n.strip() not in ("", "-", "null", "N/A", "n/a", "0")
            ]
            _log(f"Notas a inserir: {notas_validas}")
            for nota in notas_validas:
                await inserir_nota_fiscal(page, nota)
            _log("[RPA] Etapa 8/8: Vale-Frete")
            await ir_para_aba_vale_frete(page)
            await preencher_frete(
                page,
                config["cidade_origem"],
                config["cidade_destino"],
                config["valor_frete"],
            )
            await salvar_manifesto(page)
            numero = await obter_numero_manifesto(page)
            _log(f"[RPA] Concluido! Manifesto nr {numero}")
            return numero
        finally:
            await browser.close()


async def login(page, config):
    await page.goto(f"{config['url_base']}/manifests")
    await page.wait_for_load_state("networkidle")
    if "/sign_in" in page.url:
        _log("Sessao expirada. Fazendo login...")
        await page.fill("input[name='user[email]']", config["email"])
        await page.fill("input[name='user[password]']", config["senha"])
        await page.click("input[type='submit'], button:has-text('Entrar')")
        await page.wait_for_url("**/manifests**", timeout=15000)
        _log("Login realizado.")
    else:
        _log("Sessao ativa.")


async def novo_manifesto(page, config):
    await page.goto(f"{config['url_base']}/manifests")
    await page.wait_for_load_state("networkidle")
    await page.click("a:has-text('Novo manifesto')")
    await page.wait_for_url("**/manifests/new**", timeout=10000)
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    _log("Pagina de novo manifesto aberta.")


async def _selecionar_via_modal(page, div_class, termo, label):
    locator = page.locator(f"div.{div_class} a.listModal")
    await locator.wait_for(state="attached", timeout=10000)
    await locator.scroll_into_view_if_needed()
    await locator.click()
    await page.wait_for_selector("input[placeholder='Filtrar...']", timeout=8000)
    await page.fill("input[placeholder='Filtrar...']", termo)
    await page.keyboard.press("Enter")
    await page.wait_for_timeout(2500)

    # Verifica se retornou resultados
    sem_resultado = page.locator("table tbody tr td:has-text('Nenhum resultado'), table tbody:not(:has(tr))")
    try:
        if await sem_resultado.first.is_visible(timeout=1000):
            raise Exception(f"{label} '{termo}' nao encontrado(a) no sistema.")
    except Exception as e:
        if "nao encontrado" in str(e):
            raise
        pass

    await page.click(
        "table tbody tr:first-child button:has-text('Selecionar'), "
        "table tbody tr:first-child a:has-text('Selecionar')",
        timeout=10000
    )
    await page.wait_for_timeout(1500)
    _log(f"{label} '{termo}' selecionado(a).")


async def preencher_motorista(page, motorista):
    await _selecionar_via_modal(page, "manifest_main_driver", motorista, "Motorista")


async def verificar_e_corrigir_veiculo(page, placa_esperada):
    await page.wait_for_timeout(500)
    placa_atual = await page.eval_on_selector(
        "select#vehicle",
        "el => el.options[el.selectedIndex]?.text || ''"
    )
    placa_atual = placa_atual.strip().upper()
    _log(f"Placa atual: '{placa_atual}' | Esperada: '{placa_esperada}'")
    if placa_esperada.upper() not in placa_atual:
        await _selecionar_via_modal(page, "manifest_vehicle", placa_esperada, "Veiculo")
    else:
        _log("Placa correta.")


async def verificar_e_corrigir_carreta(page, placa_esperada):
    await page.wait_for_timeout(500)
    placa_atual = await page.eval_on_selector(
        "select#trailer_1",
        "el => el.options[el.selectedIndex]?.text || ''"
    )
    placa_atual = placa_atual.strip().upper()
    _log(f"Carreta atual: '{placa_atual}' | Esperada: '{placa_esperada}'")
    if placa_esperada.upper() not in placa_atual:
        await _selecionar_via_modal(page, "manifest_trailer_1", placa_esperada, "Carreta")
    else:
        _log("Carreta correta.")


async def preencher_classificacao(page, classificacao):
    container = page.locator("#select2-manifest_classification-container")
    await container.wait_for(state="attached", timeout=10000)
    await container.scroll_into_view_if_needed()
    await container.click()
    search = page.locator(".select2-dropdown .select2-search__field, "
                          ".select2-container--open .select2-search__field")
    await search.first.wait_for(state="visible", timeout=5000)
    await search.first.fill(classificacao)
    await page.wait_for_timeout(2000)
    await page.click(f".select2-results__option:has-text('{classificacao}')")
    await page.wait_for_timeout(500)
    _log(f"Classificacao '{classificacao}' selecionada.")


async def salvar_manifesto(page):
    try:
        if await page.locator(".swal2-container.swal2-shown").is_visible(timeout=1500):
            _log("Modal SweetAlert aberto — fechando antes de salvar...")
            await page.click(".swal2-confirm, .swal2-cancel, button:has-text('OK')", timeout=3000)
            await page.wait_for_timeout(1000)
    except Exception:
        pass

    btn = page.locator("button.btn-primary:has(.fa-save), button.btn-primary:has-text('Salvar')")
    await btn.last.wait_for(state="attached", timeout=10000)
    await btn.last.scroll_into_view_if_needed()
    await btn.last.click()
    await page.wait_for_selector("text=Tem certeza que deseja salvar", timeout=5000)
    await page.click("button:has-text('Sim')")
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(2000)
    _log("Manifesto salvo.")


async def inserir_nota_fiscal(page, nota):
    # Garante que a aba Entregas está ativa antes de interagir com o campo de NF
    try:
        aba = page.locator("a:has-text('Entregas'), li:has-text('Entregas') a")
        await aba.first.wait_for(state="visible", timeout=5000)
        await aba.first.click()
        await page.wait_for_timeout(1000)
    except Exception:
        pass

    container = page.locator("#selected-tab-deliveries #select2-term-container")
    await container.wait_for(state="visible", timeout=10000)
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
            _log(f"Nota {nota} ja vinculada (aviso ignorado).")
            await page.click("button:has-text('OK')")
            await page.wait_for_timeout(1000)
    except Exception:
        pass
    _log(f"Nota fiscal '{nota}' inserida.")
    _log("Recarregando pagina para confirmar insercao da NF...")
    await page.reload()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    _log("Pagina recarregada.")


async def ir_para_aba_vale_frete(page):
    aba = page.locator("a:has-text('Vale-Frete'), li:has-text('Vale-Frete') a")
    await aba.first.wait_for(state="visible", timeout=10000)
    await aba.first.scroll_into_view_if_needed()
    await aba.first.click()
    await page.wait_for_timeout(1500)
    _log("Aba Vale-Frete aberta.")


async def preencher_frete(page, cidade_origem, cidade_destino, valor_frete):
    _log(f"Preenchendo cidade origem: {cidade_origem}")
    await page.click("#select2-calculation_origin_city-container")
    await page.wait_for_timeout(800)
    await page.wait_for_selector(".select2-container--open input.select2-search__field", state="visible", timeout=5000)
    await page.keyboard.type(cidade_origem, delay=80)
    await page.wait_for_selector(".select2-results__option:not(.select2-results__option--loading)", state="visible", timeout=10000)
    await page.click(f".select2-results__option:has-text('{cidade_origem}')")
    await page.wait_for_timeout(800)
    _log(f"Cidade origem: {cidade_origem}")

    _log(f"Preenchendo cidade destino: {cidade_destino}")
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
    _log(f"Cidade destino: {cidade_destino}")

    _log(f"Preenchendo valor do frete: {valor_frete}")
    inteiro, centavos = _normalizar_frete(valor_frete)
    campo = page.locator("#closed_freight_subtotal")
    await campo.wait_for(state="attached", timeout=10000)
    await campo.scroll_into_view_if_needed()
    await campo.click()
    await page.keyboard.press("Control+a")
    await page.wait_for_timeout(300)
    await page.keyboard.type(inteiro, delay=100)
    await page.wait_for_timeout(400)
    if centavos != "00":
        await page.keyboard.press(",")
        await page.wait_for_timeout(400)
        await page.keyboard.type(centavos, delay=100)
        await page.wait_for_timeout(300)
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(800)
    _log(f"Valor frete: {valor_frete} (inteiro={inteiro}, centavos={centavos})")


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
