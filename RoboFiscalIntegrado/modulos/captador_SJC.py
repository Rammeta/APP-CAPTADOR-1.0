#--------------------------------------------------------------------------
# modulos/captador_SJC.py - v4.4 (Correção final dos seletores de data)
#--------------------------------------------------------------------------
import os
import re
import sys
import time
from pathlib import Path
from typing import List, Dict, Optional
import random

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
SJC_LOGIN_URL = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/portal/index.html#/login"
URL_LIVROS_FISCAIS = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/livrofiscal/relatorioLivroFiscal.jsf"
URL_SELECIONA_CADASTRO = "https://notajoseense.sjc.sp.gov.br/notafiscal/paginas/selecionacadastro/selecionaCadastro.jsf"

# --- Função para Selecionar a Empresa ---
def selecionar_empresa(pagina: Page, cnpj: str):
    # (código desta função permanece o mesmo)
    log_info(f"Iniciando a busca pelo CNPJ: {cnpj}...")
    try:
        seletor_campo_cnpj = "#frmDados\\:j_idt91\\:idCpfCnpj\\:idInputMaskCpfCnpj\\:inputText"
        pagina.wait_for_selector(seletor_campo_cnpj, state="visible", timeout=30000)
        campo_cnpj = pagina.locator(seletor_campo_cnpj)
        campo_cnpj.fill(cnpj)
        time.sleep(random.uniform(0.5, 1.0))
        
        botao_pesquisar = pagina.get_by_role("link", name="Pesquisar")
        botao_pesquisar.click()
        log_info("Botão 'Pesquisar' clicado. Aguardando a página de resultados carregar...")
        pagina.wait_for_load_state("networkidle", timeout=20000)
        
        seletor_botao_selecionar = "#frmDados\\:j_idt118\\:dtResultado\\:0\\:j_idt122"
        pagina.wait_for_selector(seletor_botao_selecionar, state="visible", timeout=15000)
        pagina.locator(seletor_botao_selecionar).click()
        log_info("Empresa selecionada. Aguardando o painel...")

    except PWTimeoutError:
        log_error(f"Não foi possível encontrar ou selecionar a empresa com CNPJ {cnpj}. O site pode estar lento.")
        raise

# --- Função para Baixar os Livros Fiscais ---
def baixar_livros_fiscais(pagina: Page, competencia: str, cliente_id: str, config_geral: Dict):
    log_info(f"Iniciando processo de download dos livros para a competência: {competencia}")
    try:
        log_info(f"Navegando para a página de relatórios...")
        pagina.goto(URL_LIVROS_FISCAIS, wait_until="networkidle")
        
        try:
            toast = pagina.locator("#toast-container")
            toast.wait_for(state="visible", timeout=3000)
            if "Inscrição Municipal Obrigatória" in toast.inner_text():
                log_info(f"Cliente {cliente_id} não possui Inscrição Municipal. Pulando download.")
                pagina.goto(URL_SELECIONA_CADASTRO, wait_until="networkidle")
                return
        except PWTimeoutError:
            log_info("Nenhuma notificação de erro de IM encontrada.")
            
        ano, mes = competencia.split('-')
        competencia_formatada = f"{mes}/{ano}"
        
        # <<< MUDANÇA: Usando os seletores corretos com o sufixo '_input' >>>
        seletor_data_inicio = "#frmRelatorio\\:j_idt90\\:j_idt93\\:idStart_input"
        seletor_data_fim = "#frmRelatorio\\:j_idt90\\:j_idt93\\:idEnd_input"

        log_info("Aguardando campo de competência ficar visível...")
        pagina.wait_for_selector(seletor_data_inicio, state="visible", timeout=30000)
        
        log_info(f"Preenchendo competência: {competencia_formatada}")
        pagina.locator(seletor_data_inicio).fill(competencia_formatada)
        time.sleep(random.uniform(0.3, 0.7))
        pagina.locator(seletor_data_fim).fill(competencia_formatada)
        log_info("Campos de competência preenchidos.")
        
        # --- O resto da lógica de download ---
        seletor_situacao_normal = "#frmRelatorio\\:j_idt90\\:j_idt117\\:j_idt122"
        seletor_situacao_cancelada = "#frmRelatorio\\:j_idt90\\:j_idt117\\:j_idt126"
        seletor_botao_gerar = "#frmRelatorio\\:j_idt90\\:j_idt208"
        
        pasta_saida = Path(config_geral.get("pasta_saida_padrao") or "downloads") / cliente_id
        pasta_saida.mkdir(parents=True, exist_ok=True)

        def gerar_e_salvar_relatorio(tipo_nota: str, tipo_situacao: str):
            # ... (código interno desta função permanece o mesmo)
            log_info(f"Gerando relatório para: {tipo_nota} - Situação {tipo_situacao}")
            seletor_situacao = seletor_situacao_normal if tipo_situacao == "Normal" else seletor_situacao_cancelada
            pagina.locator(seletor_situacao).click()
            time.sleep(1)
            try:
                with pagina.expect_download(timeout=15000) as download_info:
                    pagina.locator(seletor_botao_gerar).click()
                download = download_info.value
                nome_arquivo = f"{cliente_id}_Livro_{tipo_nota}_{tipo_situacao}_{mes}-{ano}.pdf"
                caminho_arquivo = pasta_saida / nome_arquivo
                download.save_as(caminho_arquivo)
                log_info(f"Salvo com sucesso: {caminho_arquivo}")
            except PWTimeoutError:
                log_info(f"Download não iniciado para {tipo_situacao}. Verificando se há notificação de 'sem movimento'...")
                toast = pagina.locator("#toast-container")
                if toast.is_visible(timeout=3000):
                    texto_toast = toast.inner_text()
                    log_info(f"Notificação encontrada: '{texto_toast}'")
                    nome_print = f"{cliente_id}_Livro_{tipo_nota}_{tipo_situacao}_SEM_MOVIMENTO_{mes}-{ano}.png"
                    caminho_print = pasta_saida / nome_print
                    pagina.screenshot(path=caminho_print, full_page=True)
                    log_info(f"Print de 'Sem Movimento' salvo em: {caminho_print}")
                else:
                    log_error(f"O download para {tipo_situacao} falhou e nenhuma notificação de erro foi encontrada.")

        log_info("--- Baixando Livros de Notas PRESTADAS ---")
        gerar_e_salvar_relatorio("Prestadas", "Normal")
        log_info("Desmarcando a situação 'Normal' para a próxima captura.")
        pagina.locator(seletor_situacao_normal).click()
        time.sleep(1)
        gerar_e_salvar_relatorio("Prestadas", "Cancelada")
        
    except Exception as e:
        log_error(f"Erro inesperado ao baixar livros para {cliente_id}: {e}")

# --- Função Principal de Execução ---
def executar_captura_sjc(clientes: List[Dict], config_geral: Dict, competencia: str, headful: bool, status_obj: Optional[Dict] = None):
    # (O código desta função permanece o mesmo)
    # ...
    log_info("--- INICIANDO ROTINA PARA SÃO JOSÉ DOS CAMPOS ---")
    if not clientes: return
    
    cliente_contador = clientes[0]
    usuario = cliente_contador.get("sjc_usuario")
    senha = cliente_contador.get("sjc_senha")
    if not all([usuario, senha]):
        log_error("O primeiro cliente da lista não possui 'sjc_usuario' ou 'sjc_senha'.")
        return

    with sync_playwright() as p:
        contexto = None
        try:
            contexto = p.chromium.launch_persistent_context("", headless=False)
            pagina = contexto.new_page()
            
            log_info(f"Acessando o portal de SJC...")
            pagina.goto(SJC_LOGIN_URL, wait_until="networkidle")
            pagina.get_by_label("CPF/CNPJ").press_sequentially(usuario, delay=100)
            pagina.get_by_label("Senha de acesso").press_sequentially(senha, delay=100)
            frame_captcha = pagina.frame_locator("iframe[title='reCAPTCHA']")
            frame_captcha.locator("#recaptcha-anchor").click()
            log_info("!!! AÇÃO NECESSÁRIA: Resolva o CAPTCHA para continuar... !!!")
            frame_captcha.locator("#recaptcha-anchor[aria-checked='true']").wait_for(timeout=120000)
            pagina.get_by_role("button", name="Entrar").click()
            
            for i, cliente_alvo in enumerate(clientes):
                log_info(f"--- Processando cliente {i+1}/{len(clientes)}: ID {cliente_alvo.get('id')} ---")
                
                if i > 0:
                    pagina.goto(URL_SELECIONA_CADASTRO, wait_until="domcontentloaded")

                cnpj_alvo = cliente_alvo.get("cnpj")
                if not cnpj_alvo:
                    log_error(f"Cliente {cliente_alvo.get('id')} está sem CNPJ. Pulando.")
                    continue

                selecionar_empresa(pagina, cnpj_alvo)
                
                log_info("Painel da empresa selecionado. Aguardando carregamento e estabilização...")
                pagina.wait_for_url("**/bemVindo.jsf", timeout=30000)
                log_info("Painel da empresa acessado com SUCESSO!")
                
                baixar_livros_fiscais(pagina, competencia, cliente_alvo.get('id'), config_geral)
                
                log_info(f"Processamento do cliente {cliente_alvo.get('id')} finalizado.")
                time.sleep(2)
            
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
        "sjc_usuario": "25.322.826/0001-06", 
        "sjc_senha": "Tr@253647!?",
        "cnpj": "29.366.802/0001-00"
    }]
    executar_captura_sjc(clientes=clientes_teste, config_geral={"pasta_saida_padrao": "downloads"}, competencia="2025-09", headful=True)