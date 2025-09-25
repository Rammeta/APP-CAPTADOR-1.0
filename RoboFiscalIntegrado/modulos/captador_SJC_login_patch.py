#---------------------------------------------------------------------------
# modulos/captador_SJC_login_patch.py - v10.1
#  - Livros (Prestados/Tomados) estável
#  - Talão (Emitidas/Recebidas) com confirmação
#  - XML (Emitidas/Recebidas) na página oficial exportacaonota/exportacaoNota.jsf
#    * Emissão limpa, competência preenchida, Situação (Ativa+Cancelada), confirmação "Download"
#    * Salvamento via FS scanning (zip/xml), print em "Nenhuma nota..."
#---------------------------------------------------------------------------

import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional, Iterable, Tuple, Set

# --- sys.path ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from modulos.logger import log_info, log_error

try:
    from playwright.sync_api import (
        sync_playwright, Page, TimeoutError as PWTimeoutError
    )
except ImportError:
    class PWTimeoutError(Exception): ...
    class Page: ...

# --- URLs ---
SJC_LOGIN_URL            = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/login/login.jsf"
URL_LIVROS_FISCAIS       = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/livrofiscal/relatorioLivroFiscal.jsf"
URL_SELECIONA_CADASTRO   = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/selecionacadastro/selecionaCadastro.jsf"
URL_BEM_VINDO            = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/login/bemVindo.jsf"
URL_TALAO_FISCAL         = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/notafiscal/notaFiscalTalaoList.jsf"
# XML (link fornecido por você)
URL_XML_EXPORT           = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/exportacaonota/exportacaoNota.jsf"

# --- Timeouts (ms) — ajustáveis via ENV ---
CLICK_WAIT_OVERLAY_MS = int(os.getenv("SJC_CLICK_OVERLAY_MS", "700"))
POST_CLICK_PAUSE_MS   = int(os.getenv("SJC_POST_CLICK_MS", "120"))

TOAST_FAST_MS         = int(os.getenv("SJC_TOAST_FAST_MS", "3500"))
FS_FALLBACK_WAIT_MS   = int(os.getenv("SJC_FS_FALLBACK_WAIT_MS", "22000"))
FS_POLL_INTERVAL_MS   = int(os.getenv("SJC_FS_POLL_INTERVAL_MS", "200"))

OVERLAY_SELECTORS = [
    ".ui-widget-overlay", ".ui-dialog-mask", ".ui-blockui",
    "[aria-busy='true']",
    "div:has-text('Processando')", "div:has-text('Processando...')",
]

# Mensagens conhecidas
MSG_SEM_REGISTRO         = "Nenhum registro encontrado no período informado para a geração do livro fiscal"
MSG_SEM_DADOS_IMPRESSAO  = "Não existe(m) dado(s) para impressão"
MSG_ERRO_IMPREVISTO      = "Ocorreu um erro imprevisto no sistema"
MSG_NENHUMA_NOTA         = "Nenhuma nota fiscal foi encontrada com o filtro informado"

# =========================
# Utilitários visuais/ajax
# =========================

def _toast_text(pagina: Page, timeout: int = TOAST_FAST_MS) -> Optional[str]:
    try:
        msg = pagina.locator("#toast-container .toast-message")
        if msg.count() > 0:
            msg.first.wait_for(state="visible", timeout=timeout)
            return (msg.first.inner_text() or "").strip()
    except PWTimeoutError:
        pass
    try:
        t = pagina.locator("#toast-container, .ui-growl-item-container, .ui-growl-message, "
                           ".ui-messages-error, .ui-message-error, .ui-messages-warn, .ui-messages-info")
        if t.count() > 0:
            t.first.wait_for(state="visible", timeout=timeout)
            return (t.first.inner_text() or "").strip()
    except PWTimeoutError:
        pass
    return None

def _esperar_ajax_quieto(pagina: Page, timeout_ms: int = 1500):
    try:
        pagina.wait_for_function(
            """() => {
                const pfOk = !!(window.PrimeFaces && PrimeFaces.ajax?.Queue?.isEmpty?.());
                const jqOk = !!(window.jQuery && jQuery.active === 0);
                return pfOk || jqOk;
            }""",
            timeout=timeout_ms
        )
    except PWTimeoutError:
        pagina.wait_for_timeout(60)

def _overlay_visivel(pagina: Page) -> bool:
    for sel in OVERLAY_SELECTORS:
        try:
            loc = pagina.locator(sel)
            if loc.count() > 0 and loc.first.is_visible():
                return True
        except Exception:
            continue
    return False

def _esperar_overlay_sumir(pagina: Page, timeout_ms: int = CLICK_WAIT_OVERLAY_MS):
    fim = time.time() + timeout_ms/1000
    while time.time() < fim:
        if not _overlay_visivel(pagina):
            return
        pagina.wait_for_timeout(50)

def _safe_click(pagina: Page, locator, descricao: str = "elemento", timeout: int = 6000):
    locator.scroll_into_view_if_needed()
    locator.wait_for(state="visible", timeout=timeout)
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 500)
    locator.click()
    pagina.wait_for_timeout(POST_CLICK_PAUSE_MS)

def _limpar_sessao(contexto, url_base: str = SJC_LOGIN_URL):
    try:
        contexto.clear_cookies(); log_info("Cookies do contexto limpos.")
    except Exception as e:
        log_info(f"Não foi possível limpar cookies: {e}")
    try:
        tmp = contexto.new_page()
        tmp.goto(url_base, wait_until="domcontentloaded")
        tmp.evaluate("""() => {
            try { localStorage.clear(); } catch(e) {}
            try { sessionStorage.clear(); } catch(e) {}
            try {
              if ('indexedDB' in window && indexedDB.databases) {
                return indexedDB.databases().then(dbs => { dbs.forEach(db => { try { indexedDB.deleteDatabase(db.name); } catch(_) {} }); });
              }
            } catch(e) {}
        }""")
        log_info("Storages limpos."); tmp.close()
    except Exception as e:
        log_info(f"Falha ao limpar storages: {e}")

# =========================
# Helpers diversos
# =========================

def _fmt_comp(competencia: str) -> str:
    s = (competencia or "").strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        a, m = s.split("-"); return f"{m}/{a}"
    if re.fullmatch(r"\d{2}/\d{4}", s):
        return s
    return s

# =========================
# Competência
# =========================

def preencher_competencia_livro(pagina: Page, competencia: str):
    alvo = _fmt_comp(competencia)
    ini = pagina.locator("input[id$=':idStart_input'][data-p-label='Inicio']").first
    fim = pagina.locator("input[id$=':idEnd_input'][data-p-label='Fim']").first
    for loc in (ini, fim):
        loc.scroll_into_view_if_needed()
        loc.wait_for(state="visible", timeout=6000)
        loc.click()
        try: loc.clear()
        except Exception:
            loc.press("Control+A"); loc.press("Delete")
        loc.type(alvo, delay=18)
        pagina.keyboard.press("Tab")
        pagina.wait_for_timeout(40)
    if not ini.input_value().strip() or not fim.input_value().strip():
        raise PWTimeoutError("Não foi possível fixar a competência (Livros).")

def preencher_competencia_talao(pagina: Page, competencia: str):
    alvo = _fmt_comp(competencia)
    ini = pagina.locator("#j_idt92\\:j_idt96\\:idStart_input")
    fim = pagina.locator("#j_idt92\\:j_idt96\\:idEnd_input")
    for loc in (ini, fim):
        loc.scroll_into_view_if_needed()
        loc.wait_for(state="visible", timeout=6000)
        loc.click()
        try: loc.clear()
        except Exception:
            loc.press("Control+A"); loc.press("Delete")
        loc.type(alvo, delay=18)
        pagina.keyboard.press("Tab")
        pagina.wait_for_timeout(40)

# ---- XML (com seletores exatos que você trouxe)
def preencher_competencia_xml(pagina: Page, competencia: str):
    alvo = _fmt_comp(competencia)
    ini = pagina.locator("#j_idt92\\:j_idt96\\:idStart_input")
    fim = pagina.locator("#j_idt92\\:j_idt96\\:idEnd_input")
    for loc in (ini, fim):
        loc.scroll_into_view_if_needed()
        loc.wait_for(state="visible", timeout=6000)
        loc.click()
        try: loc.clear()
        except Exception:
            loc.press("Control+A"); loc.press("Delete")
        loc.type(alvo, delay=18)
        pagina.keyboard.press("Tab")
        pagina.wait_for_timeout(40)

# =========================
# Login e Seleção
# =========================

def login_sjc(pagina: Page, usuario: str, senha: str):
    log_info("Abrindo tela de login (sem captcha)…")
    pagina.goto(SJC_LOGIN_URL, wait_until="domcontentloaded")
    pagina.fill("#inputLogin", usuario)
    pagina.fill("#inputPassword", senha)
    _safe_click(pagina, pagina.locator("#formLogin\\:buttonLogin"), "Entrar")
    try: pagina.wait_for_load_state("networkidle", timeout=6000)
    except PWTimeoutError: pass

def _resolver_grid_empresas(pagina: Page):
    for css in ["tbody.ui-datatable-data[id$='_data']",
                "[id$=':dtResultado_data']",
                "table.ui-datatable > tbody.ui-datatable-data"]:
        tb = pagina.locator(css).first
        if tb.count() > 0:
            rows = tb.locator(":scope > tr, :scope tr[role='row']")
            return tb, rows
    raise PWTimeoutError("Grid de empresas não encontrado.")

def _definir_rpp_1000(pagina: Page):
    rpps = pagina.locator("select.ui-paginator-rpp-options")
    if rpps.count() == 0: return
    try:
        rpps.nth(rpps.count()-1).select_option(label="1000")
        log_info("Linhas por página alteradas para 1000.")
    except Exception:
        try:
            rpps.nth(rpps.count()-1).select_option(value="1000")
            log_info("Linhas por página alteradas para 1000.")
        except Exception:
            pass
    _esperar_ajax_quieto(pagina, 900)

def _cnpj_norm(cnpj: str) -> str: return re.sub(r"\D", "", cnpj or "")
def _cnpj_mask(cnpj: str) -> str:
    d = _cnpj_norm(cnpj)
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}" if len(d) == 14 else cnpj

def selecionar_empresa(pagina: Page, cnpj: str):
    log_info(f"Selecionando empresa SEM usar pesquisa. CNPJ: {cnpj}")
    pagina.goto(URL_SELECIONA_CADASTRO, wait_until="domcontentloaded")
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 700)
    _, rows = _resolver_grid_empresas(pagina)
    _definir_rpp_1000(pagina)
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 700)
    _, rows = _resolver_grid_empresas(pagina)

    alvo = None
    for txt in (_cnpj_mask(cnpj), _cnpj_norm(cnpj)):
        if txt:
            cand = rows.filter(has_text=txt)
            if cand.count() > 0:
                alvo = cand.first; break
    if not alvo: raise PWTimeoutError("CNPJ não encontrado no grid.")

    btn = alvo.locator("a[title='Selecionar'], a:has-text('Selecionar'), button:has-text('Selecionar')").first
    if btn.count() == 0: raise PWTimeoutError("Botão 'Selecionar' não encontrado.")
    _safe_click(pagina, btn, "Selecionar empresa")
    try: pagina.wait_for_url("**/bemVindo.jsf", timeout=8000)
    except PWTimeoutError: pass
    log_info("Painel da empresa acessado com SUCESSO!")

# =========================
# Situação / Tipo / Livro Fiscal / Talão / XML
# =========================

def _find_checkbox_elements(pagina: Page, label_text: str):
    lab = pagina.locator(f"label:has-text('{label_text}')").first
    if lab.count() == 0:
        lab = pagina.locator(f"span.ui-outputlabel-label:has-text('{label_text}')").first
    if lab.count() == 0:
        lab = pagina.locator(f"text={label_text}").first
    if lab.count() == 0:
        raise PWTimeoutError(f"Label '{label_text}' não encontrado.")

    for_attr = (lab.get_attribute("for") or "").strip()
    if for_attr:
        hidden = pagina.locator(f"id={for_attr}").first
        box = pagina.locator(
            f"xpath=//label[@for='{for_attr}']/parent::td//div[contains(@class,'ui-chkbox')]"
            f"//div[contains(@class,'ui-chkbox-box')]"
        ).first
        if box.count() == 0:
            box = pagina.locator(
                f"xpath=//label[@for='{for_attr}']/preceding-sibling::div[contains(@class,'ui-chkbox')][1]"
                f"//div[contains(@class,'ui-chkbox-box')]"
            ).first
        clicavel = box if box.count() > 0 else lab
        if hidden.count() > 0:
            return clicavel, hidden

    td = lab.locator("xpath=ancestor::td[1]").first
    if td.count() > 0:
        hidden = td.locator("input[type='checkbox']").first
        box    = td.locator(".ui-chkbox-box").first
        if hidden.count() > 0 and (box.count() > 0 or lab.count() > 0):
            return (box if box.count() > 0 else lab), hidden

    wrapper = lab.locator("xpath=following::div[contains(@class,'ui-selectbooleancheckbox')][1]").first
    if wrapper.count() > 0:
        hidden = wrapper.locator("input[type='checkbox']").first
        box    = wrapper.locator(".ui-chkbox-box").first
        if hidden.count() > 0:
            return (box if box.count() > 0 else wrapper), hidden

    raise PWTimeoutError(f"Checkbox para '{label_text}' não encontrado.")

def set_checkbox_by_label(pagina: Page, label_text: str, checked: bool,
                          wait_overlay_ms: int = CLICK_WAIT_OVERLAY_MS,
                          wait_ajax_ms: int = 600):
    clicavel, hidden = _find_checkbox_elements(pagina, label_text)

    def _is_checked():
        try:
            return bool(hidden.evaluate("el => !!el.checked"))
        except Exception:
            v = (hidden.get_attribute("checked") or "").lower()
            return v in ("true", "checked", "1")

    estado_atual = _is_checked()
    if estado_atual == checked:
        return

    try: clicavel.scroll_into_view_if_needed()
    except Exception: pass

    try:
        _esperar_overlay_sumir(pagina, wait_overlay_ms)
        _esperar_ajax_quieto(pagina, 400)
    except Exception:
        pass

    clicavel.click()
    pagina.wait_for_timeout(POST_CLICK_PAUSE_MS)

    try:
        _esperar_overlay_sumir(pagina, wait_overlay_ms)
        _esperar_ajax_quieto(pagina, wait_ajax_ms)
    except Exception:
        pass

    if _is_checked() != checked:
        clicavel.click()
        pagina.wait_for_timeout(POST_CLICK_PAUSE_MS)
        try:
            _esperar_overlay_sumir(pagina, wait_overlay_ms)
            _esperar_ajax_quieto(pagina, wait_ajax_ms + 200)
        except Exception:
            pass
        if _is_checked() != checked:
            raise PWTimeoutError(f"Não consegui alterar o estado de '{label_text}' para {checked}.")

def set_livro_fiscal(pagina: Page, label: str):
    span_label = pagina.locator("span[id$=':idSelectOneMenu_label']").first
    _safe_click(pagina, span_label, "Abrir Livro Fiscal")
    painel = pagina.locator("div.ui-selectonemenu-panel:visible").first
    try:
        painel.wait_for(state="visible", timeout=2000)
    except PWTimeoutError:
        _safe_click(pagina, span_label, "Abrir Livro Fiscal (2ª)")
        painel = pagina.locator("div.ui-selectonemenu-panel:visible").first
        painel.wait_for(state="visible", timeout=2000)
    alvo = painel.locator(f"li:has-text('{label}')").first
    _safe_click(pagina, alvo, f"Selecionar {label}")
    _esperar_overlay_sumir(pagina, 600)
    _esperar_ajax_quieto(pagina, 700)
    log_info(f"Livro Fiscal ajustado para: {label}")

def set_servico_radio_talao(pagina: Page, label: str):
    radio_label = pagina.locator(f"label:has-text('{label}')").first
    _safe_click(pagina, radio_label, f"Serviço {label}")
    _esperar_overlay_sumir(pagina, 600)
    _esperar_ajax_quieto(pagina, 700)

# =========================
# Download helpers (FS)
# =========================

def _candidate_download_dirs(perfil_dir: Path, downloads_tmp_dir: Path) -> list[Path]:
    cands: list[Path] = []
    for p in [downloads_tmp_dir, perfil_dir / "Downloads", perfil_dir / "Default" / "Downloads"]:
        try:
            if p and p.exists():
                cands.append(p.resolve())
        except Exception:
            pass
    try:
        for p in perfil_dir.glob("**/Downloads"):
            rp = p.resolve()
            if rp not in cands:
                cands.append(rp)
    except Exception:
        pass
    seen = set(); uniq = []
    for p in cands:
        if p not in seen:
            seen.add(p); uniq.append(p)
    return uniq

def _snapshot_all(dirs: Iterable[Path]) -> Tuple[Set[Path], float]:
    before: Set[Path] = set()
    ts = time.time()
    for d in dirs:
        try:
            for p in d.glob("*"):
                before.add(p.resolve())
        except Exception:
            continue
    return before, ts

def _pick_new_file_any(dirs: Iterable[Path], before: Set[Path], start_ts: float,
                       timeout_ms: int, poll_ms: int = FS_POLL_INTERVAL_MS) -> Optional[Path]:
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for d in dirs:
            try:
                for p in d.glob("*"):
                    try:
                        rp = p.resolve()
                        if rp in before:
                            continue
                        st = p.stat()
                        if st.st_mtime + 0.3 < start_ts:
                            continue
                        sz1 = st.st_size
                        time.sleep(0.12)
                        if not rp.exists():
                            continue
                        sz2 = rp.stat().st_size
                        if sz2 == 0 or sz1 != sz2:
                            continue
                        return rp
                    except Exception:
                        continue
            except Exception:
                continue
        time.sleep(poll_ms / 1000)
    return None

def _move_to_dest_force_pdf(src: Path, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.suffix.lower() != ".pdf":
        dest = dest.with_suffix(".pdf")
    if dest.exists():
        base, ext = dest.stem, dest.suffix
        i = 2
        while dest.with_name(f"{base} ({i}){ext}").exists():
            i += 1
        dest = dest.with_name(f"{base} ({i}){ext}")
    try:
        with open(src, "rb") as f:
            head = f.read(5)
        is_pdf = (head == b"%PDF-")
    except Exception:
        is_pdf = False
    try:
        src.replace(dest)
    except Exception:
        try:
            data = src.read_bytes()
            dest.write_bytes(data)
            src.unlink(missing_ok=True)
        except Exception:
            pass
    if is_pdf:
        log_info(f"Download salvo com sucesso (FS): {dest}")
    else:
        log_info(f"Arquivo salvo (FS; header não PDF para diagnóstico): {dest}")
    return dest

def _move_to_dest_dynamic_ext(src: Path, dest_base: Path, prefer_exts=(".zip", ".xml", ".pdf")) -> Path:
    dest_base.parent.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    try:
        head = src.read_bytes()[:5]
    except Exception:
        head = b""
    if head.startswith(b"%PDF-"):
        final = dest_base.with_suffix(".pdf")
    elif head.startswith(b"PK\x03\x04"):
        final = dest_base.with_suffix(".zip")
    elif head.startswith(b"<?xml") or b"<" in head:
        final = dest_base.with_suffix(".xml")
    else:
        final = dest_base.with_suffix(ext if ext in prefer_exts else prefer_exts[0])

    if final.exists():
        base, ext2 = final.stem, final.suffix
        i = 2
        while final.with_name(f"{base} ({i}){ext2}").exists():
            i += 1
        final = final.with_name(f"{base} ({i}){ext2}")

    try:
        src.replace(final)
    except Exception:
        try:
            data = src.read_bytes()
            final.write_bytes(data)
            src.unlink(missing_ok=True)
        except Exception:
            pass
    log_info(f"Download salvo com sucesso (FS): {final}")
    return final

# =========================
# Geração/Print - Livros
# =========================

def click_download_and_wait_fast(pagina: Page, destino: Path,
                                 perfil_dir: Path,
                                 downloads_tmp_dir: Path,
                                 btn_selector: str) -> bool:
    btn = pagina.locator(btn_selector).first
    if btn.count() == 0:
        raise PWTimeoutError("Botão de download/geração não encontrado.")

    cand_dirs = _candidate_download_dirs(perfil_dir, downloads_tmp_dir)
    before_set, start_ts = _snapshot_all(cand_dirs)

    _safe_click(pagina, btn, "Download/Gerar")

    msg = _toast_text(pagina, timeout=TOAST_FAST_MS)
    if msg:
        return False

    novo = _pick_new_file_any(cand_dirs, before_set, start_ts, timeout_ms=FS_FALLBACK_WAIT_MS)
    if novo:
        _move_to_dest_force_pdf(novo, destino)  # Livros => PDF
        return True

    dialogs = pagina.locator("div.ui-dialog[role='dialog']:visible")
    if dialogs.count() > 0:
        dlg = dialogs.first
        btn_dlg = dlg.locator(
            "a:has-text('Download'), button:has-text('Download'), "
            "a[id$=':btnDownload'], button[id$=':btnDownload']"
        ).first
        if btn_dlg.count() > 0 and btn_dlg.is_visible():
            before_set2, start_ts2 = _snapshot_all(cand_dirs)
            _safe_click(pagina, btn_dlg, "Download (diálogo)")
            msg2 = _toast_text(pagina, timeout=TOAST_FAST_MS)
            if msg2:
                return False
            novo2 = _pick_new_file_any(cand_dirs, before_set2, start_ts2, timeout_ms=int(FS_FALLBACK_WAIT_MS*0.7))
            if novo2:
                _move_to_dest_force_pdf(novo2, destino)
                return True

    return False

def gerar_relatorio_livro(pagina: Page, pasta_saida: Path,
                          cliente_id: str, competencia: str,
                          tipo_nota: str,       # "Prestadas" | "Tomados"
                          situacao_label: str,  # "Normal" | "Cancelada"
                          perfil_dir: Path,
                          downloads_tmp_dir: Path):
    set_checkbox_by_label(pagina, "Normal",    situacao_label == "Normal")
    set_checkbox_by_label(pagina, "Cancelada", situacao_label == "Cancelada")

    ano, mes = competencia.split("-")
    nome_base = f"{cliente_id}_Livro_{tipo_nota}_{situacao_label}_{mes}-{ano}"
    destino   = pasta_saida / f"{nome_base}.pdf"

    ok = click_download_and_wait_fast(
        pagina, destino, perfil_dir, downloads_tmp_dir,
        btn_selector="#frmRelatorio\\:j_idt94\\:j_idt212, a:has-text('Download'), button:has-text('Download')"
    )
    if ok:
        return

    msg = _toast_text(pagina, timeout=TOAST_FAST_MS)
    if msg and (MSG_SEM_REGISTRO in msg or MSG_SEM_DADOS_IMPRESSAO in msg or MSG_ERRO_IMPREVISTO in msg):
        img = pasta_saida / f"{nome_base}_SEM_REGISTRO.png"
        pagina.screenshot(path=str(img), full_page=True)
        log_info(f"Mensagem detectada ('{msg}'). Print salvo: {img}")
        return

    img = pasta_saida / f"{nome_base}_FALHA_SEM_TOAST.png"
    pagina.screenshot(path=str(img), full_page=True)
    log_error(f"Falha no download ({situacao_label}) e sem mensagem detectada. Print: {img}")

# =========================
# Geração/Print - Talão
# =========================

def _click_gerar_relacao_e_confirmar(pagina: Page) -> bool:
    btn_gerar = pagina.locator("a:has-text('Gerar Relação Notas'), button:has-text('Gerar Relação Notas')").first
    if btn_gerar.count() == 0:
        raise PWTimeoutError("Botão 'Gerar Relação Notas' não encontrado.")
    _safe_click(pagina, btn_gerar, "Gerar Relação Notas")

    dlg = pagina.locator("div.ui-dialog[role='dialog']:visible").filter(has_text="Deseja Realmente Confirmar").first
    if dlg.count() == 0:
        dlg = pagina.locator("div.ui-dialog[role='dialog']:visible").first

    if dlg.count() > 0:
        btn_conf = dlg.locator(
            "a:has-text('Download'), button:has-text('Download'), a[id$=':btnDownload']"
        ).first
        if btn_conf.count() > 0 and btn_conf.is_visible():
            _safe_click(pagina, btn_conf, "Confirmar Download")
            return True
    return False

def gerar_relacao_talao_combined(pagina: Page, pasta_saida: Path,
                                 cliente_id: str, competencia: str,
                                 servico_label: str,   # "Emitidas" | "Recebidas"
                                 perfil_dir: Path,
                                 downloads_tmp_dir: Path):
    set_checkbox_by_label(pagina, "Ativa", True)
    set_checkbox_by_label(pagina, "Cancelada", True)
    try: set_checkbox_by_label(pagina, "Substituida", False)
    except Exception: pass

    radio_label = pagina.locator(f"label:has-text('{servico_label}')").first
    _safe_click(pagina, radio_label, f"Serviço {servico_label}")
    _esperar_overlay_sumir(pagina, 600); _esperar_ajax_quieto(pagina, 700)

    ano, mes = competencia.split("-")
    nome_base = f"{cliente_id}_Talao_{servico_label}_AtivaCancelada_{mes}-{ano}"
    destino   = pasta_saida / f"{nome_base}.pdf"

    cand_dirs = _candidate_download_dirs(perfil_dir, downloads_tmp_dir)
    before_set, start_ts = _snapshot_all(cand_dirs)

    confirmou = _click_gerar_relacao_e_confirmar(pagina)

    msg = _toast_text(pagina, timeout=TOAST_FAST_MS)
    if msg and (MSG_NENHUMA_NOTA in msg or MSG_SEM_DADOS_IMPRESSAO in msg or MSG_ERRO_IMPREVISTO in msg):
        img = pasta_saida / f"{nome_base}_SEM_REGISTRO.png"
        pagina.screenshot(path=str(img), full_page=True)
        log_info(f"Mensagem detectada ('{msg}'). Print salvo: {img}")
        return

    if not confirmou:
        btn_fallback = pagina.locator(
            "a:has-text('Download'), button:has-text('Download'), a[id$=':btnDownload']"
        ).first
        if btn_fallback.count() > 0 and btn_fallback.is_visible():
            _safe_click(pagina, btn_fallback, "Download (fallback sem diálogo)")

    novo = _pick_new_file_any(cand_dirs, before_set, start_ts, timeout_ms=FS_FALLBACK_WAIT_MS)
    if novo:
        _move_to_dest_force_pdf(novo, destino)
        return

    img = pasta_saida / f"{nome_base}_FALHA_SEM_TOAST.png"
    pagina.screenshot(path=str(img), full_page=True)
    log_error(f"Falha ao gerar Talão ({servico_label} A+Cancelada) sem toast e sem arquivo. Print: {img}")

# =========================
# Geração/Print - XML (Emitidas/Recebidas) — PÁGINA NOVA
# =========================

def limpar_emissao_xml(pagina: Page):
    # exatamente como no HTML enviado
    alvos = [
        pagina.locator("#j_idt92\\:j_idt109\\:idStart_input"),
        pagina.locator("#j_idt92\\:j_idt109\\:idEnd_input"),
    ]
    for loc in alvos:
        try:
            el = loc.first if loc.count() > 0 else None
            if not el: continue
            el.scroll_into_view_if_needed()
            el.wait_for(state="visible", timeout=1500)
            el.click()
            try: el.clear()
            except Exception:
                el.press("Control+A"); el.press("Delete")
            pagina.wait_for_timeout(40)
        except Exception:
            continue
    _esperar_ajax_quieto(pagina, 400)

def _click_gerar_xml_e_confirmar(pagina: Page) -> bool:
    # Botão "Gerar Relação Notas" com id j_idt92:j_idt160
    btn = pagina.locator("#j_idt92\\:j_idt160, a:has-text('Gerar Relação Notas'), button:has-text('Gerar Relação Notas')").first
    if btn.count() == 0:
        raise PWTimeoutError("Botão 'Gerar Relação Notas' (XML) não encontrado.")
    _safe_click(pagina, btn, "Gerar Relação Notas (XML)")

    # Diálogo "Deseja Realmente Confirmar?" com botão Download (id j_idt92:j_idt173:btnDownload)
    dlg = pagina.locator("div.ui-dialog[role='dialog']:visible").filter(has_text="Deseja Realmente Confirmar").first
    if dlg.count() == 0:
        dlg = pagina.locator("div.ui-dialog[role='dialog']:visible").first

    if dlg.count() > 0:
        btn_conf = dlg.locator(
            "#j_idt92\\:j_idt173\\:btnDownload, a:has-text('Download'), button:has-text('Download')"
        ).first
        if btn_conf.count() > 0 and btn_conf.is_visible():
            _safe_click(pagina, btn_conf, "Confirmar Download XML")
            return True
    return False

def set_servico_radio_xml(pagina: Page, label: str):
    # “Emitidas” / “Recebidas”
    radio_label = pagina.locator(f"label:has-text('{label}')").first
    _safe_click(pagina, radio_label, f"Serviço {label}")
    _esperar_overlay_sumir(pagina, 600)
    _esperar_ajax_quieto(pagina, 700)

def gerar_xml_combined(pagina: Page, pasta_saida: Path,
                       cliente_id: str, competencia: str,
                       servico_label: str,     # "Emitidas" | "Recebidas"
                       perfil_dir: Path,
                       downloads_tmp_dir: Path):
    # Situação: Ativa + Cancelada; Substituida OFF
    try: set_checkbox_by_label(pagina, "Ativa", True)
    except Exception: pass
    try: set_checkbox_by_label(pagina, "Cancelada", True)
    except Exception: pass
    try: set_checkbox_by_label(pagina, "Substituida", False)
    except Exception: pass

    # Serviço
    set_servico_radio_xml(pagina, servico_label)

    ano, mes = competencia.split("-")
    nome_base = f"{cliente_id}_XML_{servico_label}_AtivaCancelada_{mes}-{ano}"
    dest_base = pasta_saida / f"{nome_base}"  # extensão dinâmica (.zip/.xml/.pdf)

    cand_dirs = _candidate_download_dirs(perfil_dir, downloads_tmp_dir)
    before_set, start_ts = _snapshot_all(cand_dirs)

    confirmou = _click_gerar_xml_e_confirmar(pagina)

    # Toast de "Nenhuma nota..." -> print e return
    msg = _toast_text(pagina, timeout=TOAST_FAST_MS)
    if msg and (MSG_NENHUMA_NOTA in msg or MSG_SEM_DADOS_IMPRESSAO in msg or MSG_ERRO_IMPREVISTO in msg):
        img = pasta_saida / f"{nome_base}_SEM_REGISTRO.png"
        pagina.screenshot(path=str(img), full_page=True)
        log_info(f"Mensagem detectada ('{msg}'). Print salvo: {img}")
        return

    # Fallback: botão “Download” direto (se o diálogo sumiu rápido)
    if not confirmou:
        btn_fallback = pagina.locator(
            "a:has-text('Download'), button:has-text('Download'), a[id$=':btnDownload'], a.btn-download-final"
        ).first
        if btn_fallback.count() > 0 and btn_fallback.is_visible():
            _safe_click(pagina, btn_fallback, "Download XML (fallback)")

    # Espera arquivo aparecer na(s) pasta(s) de download
    novo = _pick_new_file_any(cand_dirs, before_set, start_ts, timeout_ms=FS_FALLBACK_WAIT_MS)
    if novo:
        _move_to_dest_dynamic_ext(novo, dest_base, prefer_exts=(".zip", ".xml", ".pdf"))
        return

    img = pasta_saida / f"{nome_base}_FALHA_SEM_TOAST.png"
    pagina.screenshot(path=str(img), full_page=True)
    log_error(f"Falha ao gerar XML ({servico_label}) sem toast e sem arquivo. Print: {img}")

def baixar_xmls(pagina: Page, competencia: str, cliente_id: str, config_geral: Dict,
                perfil_dir: Path, downloads_tmp_dir: Path):
    log_info(f"Iniciando processo de XML para a competência: {competencia}")
    pagina.goto(URL_XML_EXPORT, wait_until="domcontentloaded")
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS); _esperar_ajax_quieto(pagina, 700)

    # 1) Limpar "Emissão"
    limpar_emissao_xml(pagina)
    # 2) Competência
    preencher_competencia_xml(pagina, competencia)

    pasta_saida = Path(config_geral.get("pasta_saida_padrao") or "downloads") / cliente_id
    pasta_saida.mkdir(parents=True, exist_ok=True)

    # Emitidas (Prestados) + Cancelada; Recebidas (Tomados) + Cancelada
    for servico in ("Emitidas", "Recebidas"):
        gerar_xml_combined(
            pagina, pasta_saida, cliente_id, competencia,
            servico_label=servico, perfil_dir=perfil_dir, downloads_tmp_dir=downloads_tmp_dir
        )
    log_info("XML finalizado.")

# =========================
# Fluxos principais (Livros / Talão)
# =========================

def baixar_livros_fiscais(pagina: Page, competencia: str, cliente_id: str, config_geral: Dict,
                          perfil_dir: Path, downloads_tmp_dir: Path):
    log_info(f"Iniciando processo de download dos livros para a competência: {competencia}")
    pagina.goto(URL_LIVROS_FISCAIS, wait_until="domcontentloaded")
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 700)

    preencher_competencia_livro(pagina, competencia)
    log_info("Competência preenchida (Inicio e Fim).")

    pasta_saida = Path(config_geral.get("pasta_saida_padrao") or "downloads") / cliente_id
    pasta_saida.mkdir(parents=True, exist_ok=True)

    # Prestados
    log_info("Livro Fiscal (padrão): Serviços Prestados")
    gerar_relatorio_livro(pagina, pasta_saida, cliente_id, competencia, "Prestadas", "Normal",    perfil_dir, downloads_tmp_dir)
    gerar_relatorio_livro(pagina, pasta_saida, cliente_id, competencia, "Prestadas", "Cancelada", perfil_dir, downloads_tmp_dir)
    try: set_checkbox_by_label(pagina, "Cancelada", False)
    except Exception: pass

    # Tomados
    set_livro_fiscal(pagina, "Serviços Tomados")
    gerar_relatorio_livro(pagina, pasta_saida, cliente_id, competencia, "Tomados", "Normal",    perfil_dir, downloads_tmp_dir)
    gerar_relatorio_livro(pagina, pasta_saida, cliente_id, competencia, "Tomados", "Cancelada", perfil_dir, downloads_tmp_dir)

def limpar_emissao_talao(pagina: Page):
    alvos = [
        pagina.locator("#j_idt92\\:j_idt109\\:idStart_input"),
        pagina.locator("#j_idt92\\:j_idt109\\:idEnd_input"),
        pagina.locator("fieldset:has(legend:has-text('Emissão')) input").nth(0),
        pagina.locator("fieldset:has(legend:has-text('Emissão')) input").nth(1),
    ]
    for loc in alvos:
        try:
            if loc and loc.count() > 0:
                el = loc.first
                el.scroll_into_view_if_needed()
                el.wait_for(state="visible", timeout=1500)
                el.click()
                try: el.clear()
                except Exception:
                    el.press("Control+A"); el.press("Delete")
                pagina.wait_for_timeout(40)
        except Exception:
            continue
    _esperar_ajax_quieto(pagina, 400)

def baixar_talao_fiscal(pagina: Page, competencia: str, cliente_id: str, config_geral: Dict,
                        perfil_dir: Path, downloads_tmp_dir: Path):
    log_info(f"Iniciando processo de TALÃO FISCAL para a competência: {competencia}")
    pagina.goto(URL_TALAO_FISCAL, wait_until="domcontentloaded")
    _esperar_overlay_sumir(pagina, CLICK_WAIT_OVERLAY_MS)
    _esperar_ajax_quieto(pagina, 700)

    # 1) Limpar "Emissão"
    limpar_emissao_talao(pagina)
    # 2) Preencher "Competência"
    preencher_competencia_talao(pagina, competencia)

    pasta_saida = Path(config_geral.get("pasta_saida_padrao") or "downloads") / cliente_id
    pasta_saida.mkdir(parents=True, exist_ok=True)

    # 3) UM PDF por serviço (Ativa+Cancelada), com confirmação
    for servico in ("Emitidas", "Recebidas"):
        gerar_relacao_talao_combined(
            pagina, pasta_saida, cliente_id, competencia,
            servico_label=servico, perfil_dir=perfil_dir, downloads_tmp_dir=downloads_tmp_dir
        )
    log_info("Talão Fiscal finalizado.")

# =========================
# Principal
# =========================

def executar_captura_sjc(clientes: List[Dict], config_geral: Dict, competencia: str, headful: bool, status_obj: Optional[Dict] = None):
    log_info("--- INICIANDO ROTINA PARA SÃO JOSÉ DOS CAMPOS ---")
    if not clientes: return

    c0 = clientes[0]
    usuario = c0.get("sjc_usuario")
    senha   = c0.get("sjc_senha")
    if not all([usuario, senha]):
        log_error("O primeiro cliente não possui 'sjc_usuario' ou 'sjc_senha'.")
        return

    downloads_tmp_dir = Path(config_geral.get("downloads_tmp_dir") or r"C:\AUTOMA-O-TESTE\APP-CAPTADOR-1.0\.playwright\sjc_downloads").resolve()
    downloads_tmp_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        contexto = None
        try:
            perfil_dir = Path(config_geral.get("perfil_sjc_dir", ".playwright/sjc")).resolve()
            perfil_dir.mkdir(parents=True, exist_ok=True)

            try:
                contexto = p.chromium.launch_persistent_context(
                    str(perfil_dir),
                    headless=not headful,
                    accept_downloads=True,
                    downloads_path=str(downloads_tmp_dir),  # se versão suportar
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )
            except TypeError:
                contexto = p.chromium.launch_persistent_context(
                    str(perfil_dir),
                    headless=not headful,
                    accept_downloads=True,
                    locale="pt-BR",
                    timezone_id="America/Sao_Paulo",
                )

            try: _limpar_sessao(contexto)
            except Exception: pass

            pagina = contexto.new_page()

            # LOGIN
            login_sjc(pagina, usuario, senha)

            for i, cli in enumerate(clientes):
                log_info(f"--- Processando cliente {i+1}/{len(clientes)}: ID {cli.get('id')} ---")
                if i > 0:
                    pagina.goto(URL_SELECIONA_CADASTRO, wait_until="domcontentloaded")
                selecionar_empresa(pagina, cli.get("cnpj"))

                try:
                    # LIVROS
                    baixar_livros_fiscais(
                        pagina, competencia, cli.get('id'), config_geral,
                        perfil_dir=perfil_dir, downloads_tmp_dir=downloads_tmp_dir
                    )
                    # TALÃO (Emitidas/Recebidas; Ativa+Cancelada)
                    baixar_talao_fiscal(
                        pagina, competencia, cli.get('id'), config_geral,
                        perfil_dir=perfil_dir, downloads_tmp_dir=downloads_tmp_dir
                    )
                    # XML (Emitidas/Recebidas; Ativa+Cancelada) — página nova
                    baixar_xmls(
                        pagina, competencia, cli.get('id'), config_geral,
                        perfil_dir=perfil_dir, downloads_tmp_dir=downloads_tmp_dir
                    )
                except Exception as e:
                    log_error(f"Falha no processamento de {cli.get('id')}: {e}")

                log_info(f"Processamento do cliente {cli.get('id')} finalizado.")

            log_info("--- TODOS OS CLIENTES FORAM PROCESSADOS ---")

        except Exception as e:
            log_error(f"ERRO CRÍTICO na rotina de São José dos Campos: {e}")
        finally:
            if contexto:
                contexto.close()
                log_info("Navegador fechado.")

# --- Execução direta (teste) ---
if __name__ == "__main__":
    clientes_teste = [{
        "id": "SJC-COM-IM",
        "sjc_usuario": os.getenv("SJC_USUARIO", "25.322.826/0001-06"),
        "sjc_senha":   os.getenv("SJC_SENHA",   "Tr@253647!?"),
        "cnpj":        os.getenv("SJC_CNPJ",    "29.366.802/0001-00"),
    }]
    executar_captura_sjc(
        clientes=clientes_teste,
        config_geral={
            "pasta_saida_padrao": "downloads",
            "perfil_sjc_dir": ".playwright/sjc",
            "downloads_tmp_dir": r"C:\AUTOMA-O-TESTE\APP-CAPTADOR-1.0\.playwright\sjc_downloads",
        },
        competencia=os.getenv("SJC_COMPETENCIA", "2025-09"),
        headful=True
    )
