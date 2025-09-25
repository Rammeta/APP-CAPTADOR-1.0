# =========================
# TALÃO FISCAL (Relação de Notas)
# =========================

URL_TALAO = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/notafiscal/notaFiscalTalaoList.jsf"

def _painel_por_titulo(pagina: Page, titulo: str):
    """
    Encontra o container do painel cujo <h3> contém 'titulo'.
    Funciona para 'Emissão', 'Competência', etc.
    """
    h3 = pagina.locator(f"h3:has-text('{titulo}')").first
    if h3.count() == 0:
        raise PWTimeoutError(f"Painel '{titulo}' não encontrado.")
    painel = h3.locator("xpath=ancestor::div[contains(@class,'ui-panel') or contains(@class,'card')][1]").first
    if painel.count() == 0:
        # fallback: pega o contêiner pai mais próximo
        painel = h3.locator("xpath=parent::*/parent::*").first
    return painel

def _clear_input(loc):
    loc.scroll_into_view_if_needed()
    loc.click()
    try:
        loc.clear()
    except Exception:
        loc.press("Control+A")
        loc.press("Delete")

def abrir_talao_e_limpar_emissao(pagina: Page):
    """
    Abre a tela do Talão Fiscal e limpa as datas da seção 'Emissão'
    (Data Início e Data Fim) para não influenciarem o filtro por Competência.
    """
    pagina.goto(URL_TALAO, wait_until="domcontentloaded")
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 700)

    painel_emissao = _painel_por_titulo(pagina, "Emissão")

    # Tenta IDs usuais do PrimeFaces. Se não achar, limpa TODOS os inputs de texto do painel.
    candidatos = [
        "input[id$=':dtEmissaoIni_input']",
        "input[id$=':dtEmissaoInicio_input']",
        "input[id$=':dataInicio_input']",
        "input[id$=':dtEmissaoInicio']",
        "input[aria-label='Data Início']",
        "input[data-p-label='Data Início']",
        "input[data-p-label='Data Inicio']",
    ]
    candidatos2 = [
        "input[id$=':dtEmissaoFim_input']",
        "input[id$=':dtEmissaoFinal_input']",
        "input[id$=':dataFim_input']",
        "input[id$=':dtEmissaoFim']",
        "input[aria-label='Data Fim']",
        "input[data-p-label='Data Fim']",
    ]

    def _primeiro_valido(painel, seletores):
        for s in seletores:
            loc = painel.locator(s).first
            if loc.count() > 0:
                return loc
        return None

    ini = _primeiro_valido(painel_emissao, candidatos)
    fim = _primeiro_valido(painel_emissao, candidatos2)

    if ini is None or fim is None:
        # fallback genérico: limpa todos os inputs de texto dentro do painel Emissão
        inputs = painel_emissao.locator("input[type='text'], input.ui-inputfield").all()
        if not inputs:
            raise PWTimeoutError("Campos de 'Emissão' não encontrados para limpeza.")
        for inp in inputs:
            _clear_input(inp)
    else:
        _clear_input(ini)
        _clear_input(fim)

    _esperar_overlay_sumir(pagina, 400)
    _esperar_ajax_quieto(pagina, 600)
    log_info("Talão Fiscal: datas da seção 'Emissão' limpas.")

def preencher_competencia_talao(pagina: Page, competencia: str):
    """
    Preenche a seção 'Competência' na tela do Talão Fiscal (Inicio/Fim).
    Usa o mesmo formato do robo: 'AAAA-MM' ou 'MM/AAAA'.
    """
    alvo = _fmt_comp(competencia)
    painel_comp = _painel_por_titulo(pagina, "Competência")
    # Seletores prováveis (segue padrão do site)
    candidatos_ini = [
        "input[id$=':idStart_input']",
        "input[data-p-label='Inicio']",
        "input[data-p-label='Início']",
        "input[aria-label='Inicio']",
        "input[aria-label='Início']",
    ]
    candidatos_fim = [
        "input[id$=':idEnd_input']",
        "input[data-p-label='Fim']",
        "input[aria-label='Fim']",
    ]
    def _loc(painel, ols):
        for s in ols:
            loc = painel.locator(s).first
            if loc.count() > 0:
                return loc
        return None

    ini = _loc(painel_comp, candidatos_ini)
    fim = _loc(painel_comp, candidatos_fim)
    if ini is None or fim is None:
        raise PWTimeoutError("Campos de Competência (Talão) não encontrados.")

    for loc in (ini, fim):
        _clear_input(loc)
        loc.type(alvo, delay=18)
        pagina.keyboard.press("Tab")
        pagina.wait_for_timeout(40)

    log_info("Talão Fiscal: competência preenchida (Início
