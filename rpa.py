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
        numero = ""
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
            _log("[RPA] Etapa 5b: Data do frete")
            await preencher_data_frete(page, config.get("data_frete", ""))
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
            elif tipo_nota == "sem_nota":
                _log("[RPA] Etapa 7: Sem nota - preenchendo observacao")
                await preencher_observacao(page, config.get("observacao", ""))

            _log(f"[RPA] Etapa 8: Vale-Frete (tipo_motorista={tipo_motorista})")
            await ir_para_aba_vale_frete(page)
            await preencher_frete(
                page,
                config["cidade_origem"],
                config["cidade_destino"],
                config.get("valor_frete", ""),
                tipo_motorista,
                config.get("tabela_preco", ""),
            )
            await salvar_manifesto(page)
            numero = await obter_numero_manifesto(page)
            _log(f"[RPA] Concluido! Manifesto nr {numero}")
            return numero
        except Exception as e:
            try:
                numero = await obter_numero_manifesto(page)
            except Exception:
                numero = ""
            _log(f"[RPA] ERRO: {e} | Manifesto nr: '{numero}'")
            raise RuntimeError(f"{e}||{numero}")
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


async def preencher_data_frete(page, data: str = ""):
    from datetime import date
    valor = data.strip() if data and data.strip() else date.today().strftime("%d/%m/%Y")
    campo = page.locator("input#manifest_service_date")
    await campo.wait_for(state="visible", timeout=10000)
    await campo.click(click_count=3)
    await page.keyboard.type(valor, delay=50)
    await page.keyboard.press("Tab")
    await page.wait_for_timeout(500)
    _log(f"Data do frete preenchida: {valor}")


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


async def _verificar_erro_pagina(page):
    try:
        el = page.locator("#vue-error-component")
        await el.wait_for(state="visible", timeout=3000)
        texto = (await el.inner_text()).strip()
        if texto:
            raise Exception(f"Erro ESL: {texto}")
    except Exception as e:
        if "Erro ESL:" in str(e):
            raise


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
    await _verificar_erro_pagina(page)
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
    await page.wait_for_timeout(3000)
    nenhum = page.locator(".select2-results__option:has-text('Nenhum resultado')")
    if await nenhum.count() > 0:
        raise Exception(f"Nota fiscal '{nota}' ja manifestada ou inexistente.")
    option = page.locator(f".select2-results__option:has-text('{nota}')")
    if await option.count() > 0:
        await option.first.click()
    await page.wait_for_timeout(4000)
    try:
        if await page.is_visible("text=Frete possui entrega vinculada", timeout=2000):
            _log(f"Nota {nota} ja vinculada (aviso ignorado).")
            await page.click("button:has-text('OK')")
            await page.wait_for_timeout(1000)
    except Exception:
        pass
    await _verificar_erro_pagina(page)
    await page.reload()
    await page.wait_for_load_state("networkidle")
    await page.wait_for_timeout(3000)
    _log("Pagina recarregada.")

    # Verificar se NF aparece na tabela de entregas
    await aba.first.click()
    await page.wait_for_timeout(1500)
    count = await page.locator(f"#selected-tab-deliveries td:has-text('{nota}')").count()
    if count == 0:
        raise Exception(f"Nota fiscal '{nota}' nao encontrada na lista de entregas apos insercao.")
    _log(f"Nota fiscal '{nota}' inserida e confirmada.")


def _pos_visivel(seletor_js):
    """Retorna JS que acha o primeiro elemento visivel (bbox > 0) e retorna suas coordenadas centrais."""
    return f"""
        () => {{
            const els = Array.from(document.querySelectorAll({seletor_js!r}));
            for (const el of els) {{
                const r = el.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
            }}
            return null;
        }}
    """


async def _mouse_click_visivel(page, seletor_js, label):
    pos = await page.evaluate(_pos_visivel(seletor_js))
    _log(f"{label}: pos = {pos}")
    if pos:
        await page.mouse.click(pos['x'], pos['y'])
    else:
        _log(f"{label}: AVISO - elemento nao visivel")
    return pos


async def inserir_referencia_oc(page, referencia):
    _log(f"OC: Iniciando insercao de referencia '{referencia}'")

    # Step 1: Aba Entregas + botao + Entregas
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
        _log("OC: modal nao abriu via click, abrindo via jQuery...")
        await page.evaluate("$('#search-freights').modal('show')")
        await page.wait_for_timeout(1000)

    await page.wait_for_selector("#search-freights", state="visible", timeout=15000)
    await page.wait_for_timeout(500)

    # Step 2: Ativar aba Fretes
    await page.evaluate("$('#search-freights a[href=\"#tab-freights\"]').tab('show')")
    await page.wait_for_timeout(800)

    # Step 3: Clicar no campo Data do Frete (visivel na tela) para abrir datepicker
    _log("OC Step 3: Clicando campo Data do Frete")
    await _mouse_click_visivel(page, 'input[id*="service_at"]', "campo data")
    await page.wait_for_timeout(500)

    # Clicar Limpar no datepicker visivel
    await _mouse_click_visivel(page, '.daterangepicker .cancelBtn', "Limpar")
    await page.wait_for_timeout(300)

    # Confirmar — apos Limpar o picker pode ja ter fechado, tentamos mesmo assim
    await _mouse_click_visivel(page, '.daterangepicker .applyBtn', "Confirmar")
    await page.wait_for_timeout(300)

    # Conferir valor do campo data apos limpeza
    valor_data = await page.evaluate("""
        () => {
            const inputs = Array.from(document.querySelectorAll('input[id*="service_at"]'));
            for (const el of inputs) {
                const r = el.getBoundingClientRect();
                if (r.width > 0) return el.value;
            }
            return null;
        }
    """)
    _log(f"OC Step 3: valor data = '{valor_data}'")

    # Step 3b: Expandir filtros (seta para baixo) — elemento visivel no modal
    _log("OC Step 3b: Expandindo filtros")
    await _mouse_click_visivel(page, '#search-freights .fa-angle-down', "seta filtros")
    await page.wait_for_timeout(500)

    # Step 4: Clicar no campo Referencia visivel e digitar como humano
    _log(f"OC Step 4: Preenchendo N° Referencia '{referencia}'")
    pos_ref = await _mouse_click_visivel(page, 'input[id*="reference_number"]', "campo referencia")
    if pos_ref:
        await page.keyboard.press("Control+a")
        await page.keyboard.type(referencia, delay=50)
        _log(f"OC Step 4: digitou '{referencia}'")
    await page.wait_for_timeout(300)

    # Step 5: Clicar na lupa (submit visivel)
    _log("OC Step 5: Clicando na lupa")
    await _mouse_click_visivel(page, '#search-freights button[type="submit"]', "lupa")
    await page.wait_for_timeout(2000)
    await page.wait_for_function(
        "() => document.querySelectorAll('#search-freights tbody tr').length > 0",
        timeout=15000
    )

    nao_encontrado = await page.locator("#search-freights .alert-info").is_visible()
    if nao_encontrado:
        raise Exception(f"Referencia OC '{referencia}' nao encontrada no sistema ESL.")

    # Step 6: Selecionar todos — clicar no checkbox visivel (span.checker do uniform.js)
    _log("OC Step 6: Selecionando todos")
    await page.wait_for_function(
        "() => Array.from(document.querySelectorAll('#search-freights input[type=\"checkbox\"]')).some(cb => cb.offsetParent !== null && !cb.disabled)",
        timeout=15000
    )
    await _mouse_click_visivel(page, '#search-freights span.checker, #search-freights input[type="checkbox"]', "checkbox")
    await page.wait_for_timeout(500)

    # Step 7: Clicar em + Adicionar visivel
    _log("OC Step 7: Clicando em '+ Adicionar'")
    await _mouse_click_visivel(page, '#search-freights a.btn i.fa-plus', "+ Adicionar")
    await page.wait_for_timeout(2000)

    # Step 8: SweetAlert2
    _log("OC Step 8: Aguardando SweetAlert2")
    await page.wait_for_selector(".swal2-popup", state="visible", timeout=15000)
    await _mouse_click_visivel(page, 'button.swal2-confirm', "SweetAlert Confirmar")

    # Step 9: Aguardar fechamento
    _log("OC Step 9: Aguardando confirmacao")
    await page.wait_for_selector(".swal2-popup", state="hidden", timeout=30000)

    # Step 10: Fechar modal
    _log("OC Step 10: Fechando modal")
    try:
        btn_close = page.locator("#search-freights button.close")
        await btn_close.wait_for(state="visible", timeout=5000)
        await btn_close.click()
    except Exception:
        await page.evaluate("$('#search-freights').modal('hide')")
    await page.wait_for_selector("#search-freights", state="hidden", timeout=15000)

    _log(f"Referencia OC '{referencia}' inserida.")


async def ir_para_aba_vale_frete(page):
    # Aguardar modal de progresso do ESL fechar antes de clicar na aba
    try:
        await page.wait_for_selector("#async-progress-bar", state="hidden", timeout=90000)
        _log("Modal de progresso fechado.")
    except Exception:
        pass

    aba = page.locator("a:has-text('Vale-Frete'), li:has-text('Vale-Frete') a")
    await aba.first.wait_for(state="visible", timeout=10000)
    await aba.first.scroll_into_view_if_needed()
    await aba.first.click()
    await page.wait_for_load_state("networkidle", timeout=15000)
    try:
        await page.wait_for_selector("#select2-calculation_origin_city-container", state="visible", timeout=5000)
    except Exception:
        pass
    await _verificar_erro_pagina(page)
    _log("Aba Vale-Frete aberta.")


async def preencher_observacao(page, observacao: str):
    campo = page.locator("#operational_comments")
    await campo.wait_for(state="visible", timeout=10000)
    await campo.click()
    await page.keyboard.press("Control+a")
    await page.keyboard.type(observacao, delay=30)
    await page.wait_for_timeout(500)
    _log(f"Observacao preenchida: {observacao}")


async def _clicar_radio_calculo(page, value):
    await page.evaluate(f"""
        () => {{
            const el = document.querySelector('input[name="manifest[calculation_type]"][value="{value}"]');
            if (el) {{
                const div = el.closest('div.radio') || el.parentElement;
                div.scrollIntoView({{block: 'center'}});
            }}
        }}
    """)
    await page.wait_for_timeout(300)
    pos = await page.evaluate(f"""
        () => {{
            const el = document.querySelector('input[name="manifest[calculation_type]"][value="{value}"]');
            if (el) {{
                const div = el.closest('div.radio') || el.parentElement;
                const r = div.getBoundingClientRect();
                if (r.width > 0 && r.height > 0) return {{x: r.left + r.width / 2, y: r.top + r.height / 2}};
            }}
            return null;
        }}
    """)
    if pos:
        await page.mouse.click(pos['x'], pos['y'])
        _log(f"Radio calculation_type='{value}' clicado em ({pos['x']:.0f}, {pos['y']:.0f}).")
    else:
        _log(f"AVISO: radio calculation_type='{value}' nao encontrado.")
    await page.wait_for_timeout(800)


async def preencher_frete(page, cidade_origem, cidade_destino, valor_frete, tipo_motorista="Dedicado", tabela_preco=""):
    tipo_upper = tipo_motorista.strip().upper()
    tipo = "Tabela" if "TABELA" in tipo_upper else ("Frota" if "FROTA" in tipo_upper else tipo_motorista.strip().capitalize())

    # Clicar no radio antes de preencher cidades (desbloqueia os campos)
    if tipo == "Tabela":
        await _clicar_radio_calculo(page, "price_table")
    else:
        await _clicar_radio_calculo(page, "agreed")

    if cidade_origem:
        _log(f"Preenchendo cidade origem: {cidade_origem}")
        await page.click("#select2-calculation_origin_city-container")
        await page.wait_for_timeout(800)
        await page.wait_for_selector(".select2-container--open input.select2-search__field", state="visible", timeout=5000)
        await page.keyboard.type(cidade_origem, delay=80)
        await page.wait_for_selector(".select2-results__option:not(.select2-results__option--loading)", state="visible", timeout=10000)
        await page.click(f".select2-results__option:has-text('{cidade_origem}')")
        await page.wait_for_timeout(800)
        _log(f"Cidade origem: {cidade_origem}")

    if cidade_destino:
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

    if tipo == "Tabela":

        if tabela_preco:
            _log(f"Selecionando tabela de preco: {tabela_preco}")
            await page.click("#select2-aggregate_price_table-container")
            await page.wait_for_timeout(500)
            await page.wait_for_selector(".select2-container--open input.select2-search__field", state="visible", timeout=5000)
            await page.keyboard.type(tabela_preco, delay=80)
            await page.wait_for_selector(".select2-results__option:not(.select2-results__option--loading)", state="visible", timeout=10000)
            await page.click(f".select2-results__option:has-text('{tabela_preco}')")
            await page.wait_for_timeout(800)
            _log(f"Tabela de preco selecionada: {tabela_preco}")

        _log("Clicando em Calcular...")
        btn_calcular = page.locator("button:has-text('Calcular'), input[value='Calcular']")
        await btn_calcular.wait_for(state="visible", timeout=5000)
        await btn_calcular.click()
        await page.wait_for_timeout(5000)
        _log("Calculo concluido.")

    elif tipo == "Frota":
        pass  # radio já clicado acima

    else:
        _log(f"Tipo {tipo_motorista}: preenchendo valor: {valor_frete}")
        inteiro, centavos = _normalizar_frete(valor_frete)
        campo = None
        for sel in ["#freight_subtotal", "#closed_freight_subtotal"]:
            try:
                el = page.locator(sel)
                await el.wait_for(state="visible", timeout=8000)
                campo = el
                _log(f"Campo valor frete encontrado: {sel}")
                break
            except Exception:
                continue
        if campo is None:
            raise Exception("Campo de valor frete nao encontrado apos selecionar radio")
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
    return ""
