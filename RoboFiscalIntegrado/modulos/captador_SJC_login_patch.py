#---------------------------------------------------------------------------
# modulos/captador_SJC.py - v6.6
# - Seleção de empresa robusta (independente de j_idt***)
# - Competência robusta (IDs dinâmicos + máscara PrimeFaces)
# - Situação: marca Normal -> Gerar (screenshot se "Nenhum registro..."),
#             depois Cancelada -> Gerar (mesma lógica)
# - Sem mexer no que já funcionava fora dessas partes
#---------------------------------------------------------------------------

import os
import re
import sys
import time
import shutil
import random
from pathlib import Path
from typing import List, Dict, Optional

# --- Bloco para correção de importação em modo de teste ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)
# --- Fim da correção ---

from modulos.logger import log_info, log_error

try:
    from playwright.sync_api import sync_playwright, Page, TimeoutError as PWTimeoutError
except ImportError:
    class PWTimeoutError(Exception): ...
    class Page: ...

# --- Constantes e Configurações ---
SJC_LOGIN_URL = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/login/login.jsf"
URL_LIVROS_FISCAIS = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/livrofiscal/relatorioLivroFiscal.jsf"
URL_SELECIONA_CADASTRO = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/selecionacadastro/selecionaCadastro.jsf"
URL_BEM_VINDO = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/login/bemVindo.jsf"

# Overlays/mascaras comuns em PrimeFaces
OVERLAY_SELECTORS = [
    ".ui-widget-overlay",
    ".ui-dialog-mask",
    ".ui-blockui",
    ".ui-overlay",
    "[aria-busy='true']",
    "div:has-text('Processando')",
    "div:has-text('Processando...')",
]

# Texto de ausência de registros
MSG_SEM_REGISTRO = "Nenhum registro encontrado no período informado para a geração do livro fiscal"

# --- Utilidades ---
def _rand_ms(lo: float, hi: float) -> int:
    return int(random.uniform(lo * 1000.0, hi * 1000.0))

def _toast_text(pagina: Page, timeout: int = 3000) -> Optional[str]:
    try:
        t = pagina.locator("#toast-container")
        t.wait_for(state="visible", timeout=timeout)
        return t.inner_text()
    except PWTimeoutError:
        return None

def normalizar_cnpj(cnpj: str) -> str:
    return re.sub(r"\D", "", cnpj or "")

def cnpj_masked(cnpj: str) -> str:
    d = normalizar_cnpj(cnpj)
    return (f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d) == 14 else cnpj)

# --- Limpeza de sessão (cookies + storages) ---
def limpar_sessao(contexto, url_base: str = SJC_LOGIN_URL):
    try:
        contexto.clear_cookies()
        log_info("Cookies do contexto limpos.")
    except Exception as e:
        log_info(f"Não foi possível limpar cookies do contexto: {e}")

    try:
        tmp = contexto.new_page()
        tmp.goto(url_base, wait_until="domcontentloaded")
        tmp.evaluate("""() => {
            try { localStorage.clear(); } catch(e) {}
            try { sessionStorage.clear(); } catch(e) {}
            try {
                if ('indexedDB' in window && indexedDB.databases) {
                    return indexedDB.databases().then(dbs => {
                        dbs.forEach(db => { try { indexedDB.deleteDatabase(db.name); } catch(_) {} });
                    });
                }
            } catch(e) {}
        }""")
        log_info("Storages (local/session/IndexedDB) limpos para o domínio alvo.")
        tmp.close()
    except Exception as e:
        log_info(f"Falha ao limpar storages: {e}")

# --- Guardiões de estabilidade (AJAX + overlay) ---
def esperar_ajax_quieto(pagina: Page, timeout: int = 20_000):
    try:
        pagina.wait_for_function(
            """() => {
                const pfOk = !!(window.PrimeFaces && PrimeFaces.ajax && PrimeFaces.ajax.Queue
                                && PrimeFaces.ajax.Queue.isEmpty && PrimeFaces.ajax.Queue.isEmpty());
                const jqOk = !!(window.jQuery && jQuery.active === 0);
                return pfOk || jqOk;
            }""",
            timeout=timeout
        )
    except PWTimeoutError:
        pagina.wait_for_timeout(300)

def esperar_overlay_sumir(pagina: Page, timeout: int = 20_000):
    deadline = time.time() + (timeout / 1000.0)
    while time.time() < deadline:
        visivel = False
        for sel in OVERLAY_SELECTORS:
            loc = pagina.locator(sel)
            try:
                if loc.count() > 0 and loc.first.is_visible(timeout=200):
                    visivel = True
                    break
            except Exception:
                continue
        if not visivel:
            return
        pagina.wait_for_timeout(150)
    raise PWTimeoutError("Overlay de processamento não sumiu a tempo.")

def safe_click(pagina: Page, locator, descricao: str = "alvo", timeout: int = 10_000):
    locator.scroll_into_view_if_needed()
    locator.wait_for(state="visible", timeout=timeout)
    esperar_ajax_quieto(pagina, 10_000)
    try:
        esperar_overlay_sumir(pagina, 10_000)
    except PWTimeoutError:
        pass
    try:
        locator.click()
        return
    except Exception as e:
        log_info(f"Primeiro clique em {descricao} falhou: {e}. Re-tentando...")
        esperar_ajax_quieto(pagina, 10_000)
        try:
            esperar_overlay_sumir(pagina, 10_000)
        except PWTimeoutError:
            pass
        locator.click()

# --- Login (sem captcha; com detecção opcional de reCAPTCHA) ---
def login_sjc(pagina: Page, usuario: str, senha: str, timeout_captcha_ms: int = 120_000):
    log_info("Abrindo tela de login (sem captcha)...")
    pagina.goto(SJC_LOGIN_URL, wait_until="domcontentloaded")
    pagina.fill("#inputLogin", usuario)
    pagina.fill("#inputPassword", senha)

    captcha_existe = False
    try:
        recaptcha_iframes = pagina.locator("iframe[title='reCAPTCHA']")
        captcha_existe = recaptcha_iframes.count() > 0 and recaptcha_iframes.first.is_visible(timeout=1500)
    except Exception:
        captcha_existe = False

    if not captcha_existe:
        log_info("Sem reCAPTCHA visível. Entrando...")
        safe_click(pagina, pagina.locator("#formLogin\\:buttonLogin"), "Entrar (login)")
    else:
        log_info("reCAPTCHA detectado — aguardando resolução manual...")
        try:
            frame = pagina.frame_locator("iframe[title='reCAPTCHA']")
            frame.locator("#recaptcha-anchor[aria-checked='true']").wait_for(timeout=timeout_captcha_ms)
            log_info("Captcha marcado. Prosseguindo com o login.")
        except PWTimeoutError:
            log_info("Timeout aguardando o captcha; tentando entrar assim mesmo.")
        finally:
            safe_click(pagina, pagina.locator("#formLogin\\:buttonLogin"), "Entrar (login)")

    try:
        pagina.wait_for_load_state("networkidle", timeout=30_000)
    except PWTimeoutError:
        pass

# =========================
#  SELEÇÃO DE EMPRESA (robusta a IDs dinâmicos)
# =========================

def _resolver_tbody_e_linhas(pagina: Page, timeout: int = 20_000):
    candidatos_tbody = [
        "tbody.ui-datatable-data[id$='_data']",
        "[id$=':dtResultado_data']",
        "table.ui-datatable > tbody.ui-datatable-data",
        "tbody.ui-widget-content[id$='_data']",
    ]
    deadline = time.time() + (timeout / 1000.0)
    ultimo_erro = None
    while time.time() < deadline:
        for css in candidatos_tbody:
            tb = pagina.locator(css)
            try:
                if tb.count() > 0:
                    tb.first.wait_for(state="attached", timeout=1500)
                    rows = tb.first.locator(":scope > tr")
                    if rows.count() == 0:
                        rows = tb.first.locator(":scope tr[role='row']")
                    return tb.first, rows
            except Exception as e:
                ultimo_erro = e
                continue
        pagina.wait_for_timeout(200)
    raise PWTimeoutError(f"Não foi possível localizar o grid (tbody). Último erro: {ultimo_erro}")

def _definir_rpp_1000_generico(pagina: Page):
    rpps = pagina.locator("select.ui-paginator-rpp-options")
    total = rpps.count()
    if total == 0:
        log_info("Dropdown de 'linhas por página' não encontrado; seguindo com a configuração atual.")
        return
    alvo = rpps.nth(total - 1)  # último (rodapé)
    try:
        alvo.scroll_into_view_if_needed()
        try:
            alvo.select_option(label="1000")
        except Exception:
            alvo.select_option(value="1000")
        log_info("Linhas por página alteradas para 1000.")
    except Exception as e:
        log_info(f"Falha ao alterar linhas por página: {e}")
        return
    esperar_ajax_quieto(pagina, 20_000)
    try:
        esperar_overlay_sumir(pagina, 10_000)
    except PWTimeoutError:
        pass
    # pequena estabilização
    try:
        _, rows = _resolver_tbody_e_linhas(pagina, timeout=10_000)
        prev = rows.count()
        pagina.wait_for_timeout(300)
        for _ in range(10):
            curr = rows.count()
            if curr == prev:
                break
            prev = curr
            pagina.wait_for_timeout(200)
    except Exception:
        pass

def selecionar_empresa(pagina: Page, cnpj: str):
    log_info(f"Selecionando empresa SEM usar pesquisa. CNPJ: {cnpj}")
    try:
        pagina.goto(URL_SELECIONA_CADASTRO, wait_until="domcontentloaded")
        try:
            esperar_overlay_sumir(pagina, 10_000)
        except PWTimeoutError:
            pass
        esperar_ajax_quieto(pagina, 20_000)

        _, rows = _resolver_tbody_e_linhas(pagina, timeout=25_000)
        if rows.count() == 0:
            raise PWTimeoutError("Grid presente, mas sem linhas visíveis.")

        _definir_rpp_1000_generico(pagina)
        try:
            esperar_overlay_sumir(pagina, 10_000)
        except PWTimeoutError:
            pass
        esperar_ajax_quieto(pagina, 20_000)
        _, rows = _resolver_tbody_e_linhas(pagina, timeout=20_000)

        mask   = cnpj_masked(cnpj)
        digits = normalizar_cnpj(cnpj)

        linha = None
        if mask:
            cand = rows.filter(has_text=mask)
            if cand.count() > 0:
                linha = cand.first
        if linha is None and digits:
            cand = rows.filter(has_text=digits)
            if cand.count() > 0:
                linha = cand.first

        if linha is None:
            raise PWTimeoutError(f"CNPJ não encontrado no grid (mask='{mask}', digits='{digits}').")

        sel_btn = linha.locator("a[title='Selecionar'], a:has-text('Selecionar'), button:has-text('Selecionar')")
        if sel_btn.count() == 0:
            raise PWTimeoutError("Botão 'Selecionar' não encontrado na linha localizada.")

        safe_click(pagina, sel_btn.first, "Selecionar (grid)")

        try:
            pagina.wait_for_url("**/bemVindo.jsf", timeout=20_000)
        except PWTimeoutError:
            esperar_ajax_quieto(pagina, 15_000)
            try:
                esperar_overlay_sumir(pagina, 10_000)
            except PWTimeoutError:
                pass
            pagina.wait_for_url("**/bemVindo.jsf", timeout=15_000)

        log_info("Painel da empresa acessado com SUCESSO!")

    except PWTimeoutError as e:
        t = _toast_text(pagina, 2000)
        if t:
            log_error(f"Toast na seleção: {t.strip()}")
        try:
            Path("diagnosticos").mkdir(exist_ok=True)
            shot = Path("diagnosticos") / f"selecionaCadastro_fail_{int(time.time())}.png"
            pagina.screenshot(path=str(shot), full_page=True)
            log_info(f"Screenshot salvo para diagnóstico: {shot}")
        except Exception:
            pass
        log_error(f"Falha ao selecionar empresa (detalhe: {e}).")
        raise

# =========================
#  COMPETÊNCIA (robusta)
# =========================

def preencher_competencia(pagina: Page, competencia: str):
    sel_inicio = "input.ui-inputfield[data-p-label='Inicio'], input[id$=':idStart_input']"
    sel_fim    = "input.ui-inputfield[data-p-label='Fim'],    input[id$=':idEnd_input']"

    def _fmt(texto: str):
        texto = (texto or "").strip()
        if re.fullmatch(r"\d{4}-\d{2}", texto):
            ano, mes = texto.split("-")
            return f"{mes}/{ano}"
        if re.fullmatch(r"\d{2}/\d{4}", texto):
            return texto
        return texto

    alvo_mm_yyyy = _fmt(competencia)
    if re.fullmatch(r"\d{2}/\d{4}", alvo_mm_yyyy):
        mes, ano4 = alvo_mm_yyyy.split("/")
        alvo_mm_yy = f"{mes}/{ano4[-2:]}"
    else:
        alvo_mm_yy = alvo_mm_yyyy

    def _digitar(locator, valor: str):
        locator.scroll_into_view_if_needed()
        locator.wait_for(state="visible", timeout=15_000)
        locator.click()
        try:
            locator.clear()
        except Exception:
            locator.press("Control+A")
            locator.press("Delete")
        locator.type(valor, delay=40)
        pagina.keyboard.press("Tab")

    def _fixou(locator, esperado: str) -> bool:
        try:
            pagina.wait_for_timeout(200)
            v = locator.input_value().strip()
            return v == esperado
        except Exception:
            return False

    try:
        pagina.locator("h3:has-text('Competência')").first.scroll_into_view_if_needed()
    except Exception:
        pass
    try:
        esperar_overlay_sumir(pagina, 10_000)
    except Exception:
        pass

    inp_inicio = pagina.locator(sel_inicio).first
    inp_fim    = pagina.locator(sel_fim).first
    if inp_inicio.count() == 0 or inp_fim.count() == 0:
        raise PWTimeoutError("Campos de competência não encontrados (Inicio/Fim).")

    _digitar(inp_inicio, alvo_mm_yyyy)
    _digitar(inp_fim,    alvo_mm_yyyy)
    ok_inicio = _fixou(inp_inicio, alvo_mm_yyyy)
    ok_fim    = _fixou(inp_fim,    alvo_mm_yyyy)

    if not (ok_inicio and ok_fim):
        _digitar(inp_inicio, alvo_mm_yy)
        _digitar(inp_fim,    alvo_mm_yy)
        ok_inicio = _fixou(inp_inicio, alvo_mm_yy)
        ok_fim    = _fixou(inp_fim,    alvo_mm_yy)

    if not (ok_inicio and ok_fim):
        try:
            el_ini = inp_inicio.element_handle(timeout=3000)
            el_fim = inp_fim.element_handle(timeout=3000)
            if el_ini and el_fim:
                pagina.evaluate(
                    """([e1, e2, v]) => {
                        for (const el of [e1, e2]) {
                            el.value = v;
                            el.dispatchEvent(new Event('input', {bubbles: true}));
                            el.dispatchEvent(new Event('change', {bubbles: true}));
                        }
                    }""",
                    [el_ini, el_fim, alvo_mm_yyyy]
                )
                pagina.keyboard.press("Tab")
                pagina.wait_for_timeout(200)
                ok_inicio = (inp_inicio.input_value().strip() in (alvo_mm_yyyy, alvo_mm_yy))
                ok_fim    = (inp_fim.input_value().strip()    in (alvo_mm_yyyy, alvo_mm_yy))
        except Exception:
            pass

    if not (ok_inicio and ok_fim):
        v1 = ""
        v2 = ""
        try: v1 = inp_inicio.input_value()
        except Exception: pass
        try: v2 = inp_fim.input_value()
        except Exception: pass
        raise PWTimeoutError(f"Não foi possível fixar a competência. Inicio='{v1}' Fim='{v2}'")

# =========================
#  SITUAÇÃO + DOWNLOAD
# =========================

def _checkbox_box_by_label(pagina: Page, label_text: str):
    """
    Localiza a caixa visual (.ui-chkbox-box) da checkbox cujo label tem o texto fornecido.
    Evita depender de IDs voláteis (j_idt***).
    """
    lab = pagina.locator(f"label:has-text('{label_text}')").first
    if lab.count() == 0:
        # alguns temas usam <span class="ui-outputlabel-label">Dentro do label</span>
        lab = pagina.locator(f"span.ui-outputlabel-label:has-text('{label_text}')").first
        if lab.count() == 0:
            raise PWTimeoutError(f"Label da situação '{label_text}' não encontrado.")
    # pega a primeira ui-selectbooleancheckbox logo após o label
    box = lab.locator("xpath=following::div[contains(@class,'ui-selectbooleancheckbox')][1]//div[contains(@class,'ui-chkbox-box')]").first
    if box.count() == 0:
        raise PWTimeoutError(f"Checkbox visual da situação '{label_text}' não encontrado.")
    return box

def _is_checked_from_box(box) -> bool:
    try:
        ic = box.locator("span.ui-chkbox-icon").first
        cls = ic.get_attribute("class") or ""
        return "ui-icon-check" in cls
    except Exception:
        return False

def set_checkbox_by_label(pagina: Page, label_text: str, value: bool):
    """
    Garante que a checkbox com label 'label_text' esteja marcada (=True) ou desmarcada (=False).
    """
    box = _checkbox_box_by_label(pagina, label_text)
    atual = _is_checked_from_box(box)
    if atual != value:
        safe_click(pagina, box, f"Checkbox '{label_text}'")
        # aguarda qualquer ajax/overlay da mudança
        try:
            esperar_overlay_sumir(pagina, 8_000)
        except PWTimeoutError:
            pass
        esperar_ajax_quieto(pagina, 10_000)

def localizar_botao_gerar(pagina: Page):
    """
    Tenta localizar o botão 'Gerar' de forma flexível.
    """
    candidatos = [
        "#frmRelatorio\\:j_idt90\\:j_idt208",
        "button:has-text('Gerar')",
        "a:has-text('Gerar')",
    ]
    for css in candidatos:
        loc = pagina.locator(css)
        if loc.count() > 0:
            return loc.first
    # tentar por ARIA role
    loc = pagina.get_by_role("button", name=re.compile("Gerar", re.I))
    if loc.count() > 0:
        return loc.first
    # fallback por texto interno de span
    loc = pagina.locator("span.ui-button-text:has-text('Gerar')")
    if loc.count() > 0:
        return loc.first.locator("xpath=ancestor::button | ancestor::a").first
    raise PWTimeoutError("Botão 'Gerar' não encontrado.")

def capturar_se_erro_sem_registro(pagina: Page, pasta_saida: Path, prefixo_print: str, timeout_ms: int = 5000) -> bool:
    """
    Verifica se a mensagem 'Nenhum registro...' aparece em até timeout_ms.
    Se aparecer, tira um screenshot de página inteira e retorna True.
    """
    deadline = time.time() + (timeout_ms / 1000.0)
    alvo = pagina.locator(f"text={MSG_SEM_REGISTRO}")
    found = False
    while time.time() < deadline:
        try:
            if alvo.count() > 0 and alvo.first.is_visible(timeout=200):
                found = True
                break
        except Exception:
            pass
        # às vezes vem em toast/growl
        t = _toast_text(pagina, timeout=500)
        if t and MSG_SEM_REGISTRO in t:
            found = True
            break
        pagina.wait_for_timeout(120)
    if found:
        pasta_saida.mkdir(parents=True, exist_ok=True)
        img_path = pasta_saida / f"{prefixo_print}_SEM_REGISTRO.png"
        pagina.screenshot(path=str(img_path), full_page=True)
        log_info(f"Mensagem de 'Nenhum registro...' detectada. Print salvo em: {img_path}")
    return found

def gerar_e_salvar(pagina: Page, competencia: str, cliente_id: str, pasta_saida: Path, situacao_label: str, tipo_nota: str = "Prestadas"):
    """
    Marca a situação pedida, clica em Gerar e tenta baixar.
    Se não baixar, procura 'Nenhum registro...' e tira print.
    """
    # Ajusta as caixas: liga a pedida, desliga a outra
    if situacao_label.lower() == "normal":
        set_checkbox_by_label(pagina, "Cancelada", False)
        set_checkbox_by_label(pagina, "Normal", True)
    elif situacao_label.lower() == "cancelada":
        set_checkbox_by_label(pagina, "Normal", False)
        set_checkbox_by_label(pagina, "Cancelada", True)
    else:
        raise ValueError("situacao_label deve ser 'Normal' ou 'Cancelada'.")

    # Botão Gerar
    btn_gerar = localizar_botao_gerar(pagina)

    # Nomes de arquivo
    # extrai mm e aaaa da competência para nome
    if re.fullmatch(r"\d{4}-\d{2}", competencia):
        ano, mes = competencia.split("-")
    else:
        m = re.search(r"(\d{2})/(\d{2}|\d{4})", competencia)
        mes = m.group(1) if m else "??"
        ano = (m.group(2) if m else "????")
        if len(ano) == 2:
            ano = "20" + ano

    nome_pdf  = f"{cliente_id}_Livro_{tipo_nota}_{situacao_label}_{mes}-{ano}.pdf"
    prefixo_print = f"{cliente_id}_Livro_{tipo_nota}_{situacao_label}_{mes}-{ano}"

    # Tenta baixar (expect_download). Se der timeout, checa mensagem e tira print.
    try:
        with pagina.expect_download(timeout=60_000) as download_info:
            safe_click(pagina, btn_gerar, "Gerar Relatório")
        download = download_info.value
        caminho_arquivo = pasta_saida / nome_pdf
        download.save_as(caminho_arquivo)
        log_info(f"Download salvo com sucesso: {caminho_arquivo}")
        return True
    except PWTimeoutError:
        log_info("Download não iniciou dentro do tempo. Verificando mensagem 'Nenhum registro...'...")
        tem_msg = capturar_se_erro_sem_registro(pagina, pasta_saida, prefixo_print, timeout_ms=6000)
        if not tem_msg:
            # não baixou e não tem mensagem => salva print diagnóstico também
            pasta_saida.mkdir(parents=True, exist_ok=True)
            diag = pasta_saida / f"{prefixo_print}_FALHA_SEM_TOAST.png"
            pagina.screenshot(path=str(diag), full_page=True)
            log_error(f"Falha no download ({situacao_label}) e sem mensagem detectada. Print de diagnóstico: {diag}")
        return False

# --- Baixar Livros Fiscais ---
def baixar_livros_fiscais(pagina: Page, competencia: str, cliente_id: str, config_geral: Dict):
    log_info(f"Iniciando processo de download dos livros para a competência: {competencia}")
    try:
        log_info("Navegando para a página de relatórios...")
        pagina.goto(URL_LIVROS_FISCAIS, wait_until="domcontentloaded")

        try: esperar_ajax_quieto(pagina, 20_000)
        except Exception: pass
        try: esperar_overlay_sumir(pagina, 10_000)
        except Exception: pass

        # Checagem de IM obrigatória
        texto_im = _toast_text(pagina, 2500)
        if texto_im and "Inscrição Municipal Obrigatória" in texto_im:
            log_info(f"Cliente {cliente_id} sem IM. Pulando download e retornando à seleção.")
            pagina.goto(URL_SELECIONA_CADASTRO, wait_until="domcontentloaded")
            return

        # Preenche competência (robusto)
        preencher_competencia(pagina, competencia)
        log_info("Campos de competência preenchidos com sucesso.")

        pasta_saida = Path(config_geral.get("pasta_saida_padrao") or "downloads") / cliente_id
        pasta_saida.mkdir(parents=True, exist_ok=True)

        # Fluxo solicitado:
        # 1) Normal -> Gerar -> se "Nenhum registro...", print.
        gerar_e_salvar(pagina, competencia, cliente_id, pasta_saida, situacao_label="Normal", tipo_nota="Prestadas")

        # 2) Cancelada -> Gerar -> se "Nenhum registro...", print.
        gerar_e_salvar(pagina, competencia, cliente_id, pasta_saida, situacao_label="Cancelada", tipo_nota="Prestadas")

    except Exception as e:
        raise e

# --- Função Principal ---
def executar_captura_sjc(clientes: List[Dict], config_geral: Dict, competencia: str, headful: bool, status_obj: Optional[Dict] = None):
    log_info("--- INICIANDO ROTINA PARA SÃO JOSÉ DOS CAMPOS ---")
    if not clientes:
        return

    cliente_contador = clientes[0]
    usuario = cliente_contador.get("sjc_usuario")
    senha = cliente_contador.get("sjc_senha")
    if not all([usuario, senha]):
        log_error("O primeiro cliente da lista não possui 'sjc_usuario' ou 'sjc_senha'.")
        return

    slow = int(config_geral.get("slow_mo", 0))  # 0, 50, 100…

    with sync_playwright() as p:
        contexto = None
        try:
            user_data = Path(config_geral.get("perfil_sjc_dir", ".playwright/sjc")).resolve()

            if config_geral.get("limpar_perfil", False) and user_data.exists():
                shutil.rmtree(user_data, ignore_errors=True)
                log_info("Perfil persistente removido (opção 'limpar_perfil').")

            user_data.mkdir(parents=True, exist_ok=True)

            contexto = p.chromium.launch_persistent_context(
                str(user_data),
                headless=not headful,
                accept_downloads=True,
                locale="pt-BR",
                timezone_id="America/Sao_Paulo",
                slow_mo=slow if slow > 0 else 0,
            )

            if config_geral.get("limpar_sessao", True):
                limpar_sessao(contexto)

            pagina = contexto.new_page()

            log_info("Acessando o portal de SJC...")
            login_sjc(pagina, usuario, senha)

            for i, cliente_alvo in enumerate(clientes):
                log_info(f"--- Processando cliente {i+1}/{len(clientes)}: ID {cliente_alvo.get('id')} ---")

                selecionar_empresa(pagina, cliente_alvo.get("cnpj"))

                # Download dos livros
                try:
                    baixar_livros_fiscais(pagina, competencia, cliente_alvo.get('id'), config_geral)
                except Exception as e:
                    log_error(f"Falha ao baixar os livros para {cliente_alvo.get('id')}: {e}")
                    # tenta voltar ao painel para próximo cliente
                    try:
                        pagina.goto(URL_BEM_VINDO, wait_until="domcontentloaded")
                    except Exception:
                        pass

                log_info(f"Processamento do cliente {cliente_alvo.get('id')} finalizado.")

            log_info("--- TODOS OS CLIENTES FORAM PROCESSADOS ---")

        except Exception as e:
            log_error(f"ERRO CRÍTICO na rotina de São José dos Campos: {e}")

        finally:
            if contexto:
                contexto.close()
                log_info("Navegador fechado.")

# --- Teste ---
if __name__ == '__main__':
    clientes_teste = [{
        "id": "SJC-COM-IM",
        "sjc_usuario": os.getenv("SJC_USUARIO", "25.322.826/0001-06"),
        "sjc_senha": os.getenv("SJC_SENHA", "Tr@253647!?"),
        "cnpj": os.getenv("SJC_CNPJ", "29.366.802/0001-00")
    }]
    executar_captura_sjc(
        clientes=clientes_teste,
        config_geral={
            "pasta_saida_padrao": "downloads",
            "perfil_sjc_dir": ".playwright/sjc",
            "limpar_sessao": True,
            "limpar_perfil": False,
            "slow_mo": 0
        },
        competencia=os.getenv("SJC_COMPETENCIA", "2025-09"),
        headful=True
    )
#---------------------------------------------------------------------------