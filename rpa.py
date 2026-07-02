import re
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright


def _log(msg: str):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _normalizar_frete(valor: str) -> tuple:
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


def _filtrar_itens(lista: list) -> list:
    return [
        item for item in (lista or [])
        if item and item.strip() not in ("", "-", "null", "N/A", "n/a", "0")
    ]


async def emitir_manifesto(config: dict, headless: bool = True) -> str:
    tipo_nota = config.get("tipo_nota", "nf")
    tipo_motorista = config.get("tipo_motorista", "Dedicado")
    _log(
        f"[RPA] Iniciando | motorista={config['motorista']} | veiculo={config['placa_veiculo']} "
        f"| tipo_nota={tipo_nota} | tipo_motorista={tipo_motorista}"
    )
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=headless)
        context = await browser.new_context()
        page = await context.new_page()
        try:
            _log("[RPA] Etapa 1: Login")
            await login(page, config)
            _log("[RPA] Etapa 2: Novo manifesto")
            await novo_manifesto(page, config)
            _log("[RPA] Etapa 3: Motorista")
            await preencher_motorista(page, config["motorista"])
            _log("[RPA] Etapa 4: Veiculo/Carreta")
            await verificar_e_corrigir_veiculo(page, config["placa_veiculo"])
            if config.get("placa_carreta"):
                await verificar_e_corrigir_carreta(page, config["placa_carreta"])
            _log("[RPA] Etapa 5: Classificacao")
            await preencher_classificacao(page, config["classificacao"])
            _log("[RPA] Etapa 6: 1o salvamento")
            await salvar_manifesto(page)

            _log(f"[RPA] Etapa 7: Adicionar itens (tipo_nota={tipo_nota})")
            if tipo_nota == "nf":
                notas = _filtrar_itens(config.get("notas_fiscais", []))
                _log(f"Notas a inserir: {notas}")
                for nota in notas:
                    await inserir_nota_fiscal(page, nota)
            elif tipo_nota == "oc":
                referencias = _filtrar_itens(config.get("referencias", []))
                _log(f"Referencias OC a inserir: {referencias}")
                for ref in referencias:
                    await inserir_referencia_oc(page, ref)

            _log(f"[RPA] Etapa 8: Vale-Frete (tipo_motorista={tipo_motorista})")
            await ir_para_aba_vale_frete(page)
            await preencher_frete(
                page,
                config["cidade_origem"],
                config["cidade_destino"],
                config.get("valor_frete", ""),
                tipo_motorista,
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

    sem_resultado = page.locator("table tbody tr td:has-text('Nenhum resultado')")
    if await sem_resultado.is_visible(timeout=1500):
        raise Exception(f"{label} '{termo}' nao encontrado(a) no sistema ESL.")

    try:
        await page.click(
            "table tbody tr:first-child button:has-text('Selecionar'), "
            "table tbody tr:first-child a:has-text('Selecionar')",
            timeout=10000
        )
    except Exception:
        raise Exception(f"{label} '{termo}' nao encontrado(a) no sistema ESL.")
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
    aba = page.locator("a:has-text('Entregas'), li:has-text('Entregas') a")
    await aba.first.wait_for(state="visible", timeout=10000)
    await aba.first.click()
    await page.wait_for_timeout(1500)

    container = page.locator("#selected-tab-deliveries #select2-term-container")
    await container.wait_for(state="visible", timeout=10000)
    await page.wait_for_timeout(500)
    await page.evaluate(
        "document.querySelector('#selected-tab-deliveries #select2-term-container')?.scrollIntoView()"
    )
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
    await page.reload()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    _log("Pagina recarregada.")


async def inserir_referencia_oc(page, referencia):
    _log(f"OC Step 1: Abrindo aba Entregas e clicando em '+ Entregas' para referencia '{referencia}'")
    aba = page.locator("a:has-text('Entregas'), li:has-text('Entregas') a")
    await aba.first.wait_for(state="visible", timeout=10000)
    await aba.first.click()
    await page.wait_for_timeout(2000)

    await page.wait_for_selector("#search-freights", state="hidden", timeout=15000)
    btn_entregas = page.locator("button:has(i.fa-plus):has-text('Entregas')").first
    await btn_entregas.wait_for(state="visible", timeout=15000)
    await btn_entregas.scroll_into_view_if_needed()
    await btn_entregas.click()
    await page.wait_for_timeout(1000)

    modal_visivel = await page.locator("#search-freights").is_visible()
    if not modal_visivel:
        _log("OC Step 1: modal nao abriu via click, abrindo via jQuery...")
        await page.evaluate("$('#search-freights').modal('show')")
        await page.wait_for_timeout(1000)

    _log("OC Step 2: Aguardando modal e ativando aba Fretes")
    await page.wait_for_selector("#search-freights", state="visible", timeout=15000)
    await page.wait_for_timeout(500)
    # garante que a aba correta (Fretes) esta ativa dentro do modal
    try:
        aba_fretes = page.locator("#search-freights a[href='#tab-freights'], #search-freights a[data-target='#tab-freights']")
        if await aba_fretes.first.is_visible(timeout=2000):
            await aba_fretes.first.click()
            await page.wait_for_timeout(500)
    except Exception:
        pass

    date_field = page.locator("#tab-freights input#search_freights_service_at").first
    await date_field.wait_for(state="visible", timeout=15000)
    await date_field.click()
    await page.wait_for_selector(".daterangepicker", state="visible", timeout=15000)

    _log("OC Step 3: Limpando filtro de datas")
    await page.wait_for_selector(".daterangepicker .cancelBtn", state="visible", timeout=15000)
    await page.evaluate(
        "Array.from(document.querySelectorAll('.daterangepicker'))"
        ".find(el => el.offsetParent !== null)?.querySelector('.cancelBtn')?.click()"
    )
    await page.wait_for_timeout(500)
    await page.evaluate(
        "Array.from(document.querySelectorAll('.daterangepicker'))"
        ".find(el => el.offsetParent !== null)?.querySelector('.applyBtn')?.click()"
    )
    await page.wait_for_timeout(800)

    _log(f"OC Step 4: Preenchendo N° Referencia '{referencia}'")
    await page.evaluate(
        f"document.querySelector('#search-freights input#search_freights_reference_number').value = '{referencia}'"
    )
    await page.wait_for_timeout(500)

    _log("OC Step 5: Clicando na lupa")
    search_btn = page.locator("#tab-freights button#submit[type='submit']")
    await search_btn.wait_for(state="visible", timeout=15000)
    await search_btn.click()
    await page.wait_for_selector("#tab-freights tbody tr", state="visible", timeout=15000)

    nao_encontrado = await page.locator("#tab-freights").get_by_text("Fretes não localizados").is_visible()
    if nao_encontrado:
        raise Exception(f"Referencia OC '{referencia}' nao encontrada no sistema ESL.")

    _log("OC Step 6: Selecionando todos")
    checkbox = page.locator("#tab-freights input[type='checkbox'].toggle.uniform")
    await checkbox.wait_for(state="visible", timeout=15000)
    await page.wait_for_function(
        "() => { const cb = document.querySelector('#search-freights input[type=\"checkbox\"].toggle.uniform'); return cb && !cb.disabled; }",
        timeout=15000
    )
    await checkbox.click()

    _log("OC Step 7: Clicando em '+ Adicionar'")
    try:
        btn_adicionar = page.locator("#search-freights a.btn:has(i.fa-plus):has-text('Adicionar')")
        await btn_adicionar.wait_for(state="visible", timeout=15000)
        await btn_adicionar.click()
    except Exception:
        btn_adicionar_alt = page.locator("#search-freights a.btn:not([data-dismiss])").first
        await btn_adicionar_alt.wait_for(state="visible", timeout=15000)
        await btn_adicionar_alt.click()

    _log("OC Step 8: Confirmando SweetAlert2")
    await page.wait_for_selector("button.swal2-confirm", state="visible", timeout=15000)
    await page.locator("button.swal2-confirm").click()

    _log("OC Step 9: Aguardando confirmacao")
    await page.wait_for_selector(".swal2-popup", state="visible", timeout=15000)
    await page.wait_for_selector(".swal2-popup", state="hidden", timeout=30000)

    _log("OC Step 10: Fechando modal")
    try:
        btn_close = page.locator("#search-freights button.close[data-dismiss='modal']")
        await btn_close.wait_for(state="visible", timeout=15000)
        await btn_close.click()
        await page.wait_for_selector("#search-freights", state="hidden", timeout=15000)
    except Exception:
        btn_close_alt = page.locator("a[name='close_modal_button'][data-dismiss='modal']")
        await btn_close_alt.click()
        await page.wait_for_selector("#search-freights", state="hidden", timeout=15000)

    _log(f"Referencia OC '{referencia}' inserida.")


async def ir_para_aba_vale_frete(page):
    aba = page.locator("a:has-text('Vale-Frete'), li:has-text('Vale-Frete') a")
    await aba.first.wait_for(state="visible", timeout=10000)
    await aba.first.scroll_into_view_if_needed()
    await aba.first.click()
    await page.wait_for_timeout(1500)
    _log("Aba Vale-Frete aberta.")


async def preencher_frete(page, cidade_origem, cidade_destino, valor_frete, tipo_motorista="Dedicado"):
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

    if tipo_motorista.capitalize() == "Tabela":
        _log("Tipo Tabela: clicando em Calcular e aguardando calculo automatico...")
        try:
            btn_calcular = page.locator("button:has-text('Calcular'), input[value='Calcular']")
            await btn_calcular.wait_for(state="visible", timeout=5000)
            await btn_calcular.click()
            _log("Botao Calcular clicado.")
        except Exception:
            _log("Botao Calcular nao encontrado, aguardando calculo automatico...")
        await page.wait_for_timeout(5000)
        _log("Calculo automatico concluido.")
    else:
        _log(f"Tipo {tipo_motorista}: preenchendo valor do frete manual: {valor_frete}")
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
