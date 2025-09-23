#--------------------------------------------------------------------------
# modulos/portal_livros_taubate.py - v1.7 COM RETRIES E TIMEOUT MAIOR
#--------------------------------------------------------------------------
import os, re, sys, time
from pathlib import Path
from dotenv import load_dotenv
from typing import List, Dict, Optional

import pytesseract
from PIL import Image
import io
import requests
from modulos.logger import log_info, log_error

try:
    from playwright.sync_api import TimeoutError as PWTimeoutError, Dialog
except ImportError:
    class PWTimeoutError(Exception): ...
    class Dialog: ...

load_dotenv()
# --- Configurações Globais ---
CRC = os.getenv("CRC", "")
CRC_SENHA = os.getenv("CRC_SENHA")
CONTADOR_LOGIN_URL = os.getenv("CONTADOR_LOGIN_URL", "https://taubateiss.meumunicipio.digital/taubateiss/contador/login.php")
PROFILE_DIR = os.path.join("dados", ".profile_taubate")
DOWNLOAD_DIR = Path("downloads")

try:
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except Exception:
    print("AVISO: Tesseract OCR não encontrado no caminho padrão.")

# ======================== Utils ========================
_FORBIDDEN = r'<>:"/\\|?*\0'
def _sanitize_filename_part(txt: str) -> str:
    if not txt: return ""
    txt = re.sub(r"\s+", " ", txt).strip()
    for ch in _FORBIDDEN: txt = txt.replace(ch, " ")
    return txt.strip()

def parse_competencia(comp: str) -> tuple[int,int]:
    y,m = comp.split("-"); return int(y), int(m)

def _contador_root_only(url: str) -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(url)
    path = parts.path or ""
    i = path.lower().find("/contador")
    base_path = path[: i + len("/contador")] if i != -1 else "/taubateiss/contador"
    return f"{parts.scheme}://{parts.netloc}{base_path}"

def _update_status(status_obj: Optional[Dict], progress: int, message: str):
    if not status_obj: return
    final_progress = 50 if progress == 100 else int(progress * 0.5)
    status_obj['progress'] = final_progress
    status_obj['message'] = message

# ======================== Funções do Robô ========================
def login_contador(page, url, crc, senha) -> None:
    portal_url = url or CONTADOR_LOGIN_URL
    
    MAX_RETRIES = 3 # <<< NOVO: Número máximo de tentativas
    for tentativa in range(1, MAX_RETRIES + 1):
        try:
            log_info(f"Tentando acessar o portal... (Tentativa {tentativa}/{MAX_RETRIES})")
            # <<< MUDANÇA: Aumentamos o timeout para 60 segundos
            page.goto(portal_url, wait_until="domcontentloaded", timeout=60000)
            
            log_info("Página de login carregada. Preenchendo formulário...")
            
            page.locator("input[name='crc']").wait_for(timeout=15000)
            page.locator("input[name='crc']").fill(crc or CRC)
            page.locator("input[name='senha']").fill(senha or CRC_SENHA)
            
            captcha_image_loc = page.locator("img[src*='imagem.php']").first
            captcha_image_bytes = captcha_image_loc.screenshot()
            
            img = Image.open(io.BytesIO(captcha_image_bytes)).convert('L')
            lut = [0] * 128 + [255] * (256 - 128)
            img = img.point(lut, '1')

            config = '--psm 8 -c tessedit_char_whitelist=0123456789'
            captcha_text = pytesseract.image_to_string(img, config=config).strip()
            
            if len(captcha_text) >= 4:
                page.locator("input[name='confirma']").fill(captcha_text)
                page.locator("button:has-text('Acessar')").first.click()
                try:
                    page.wait_for_url("**/contador/main.php**", timeout=10000) # Timeout maior para pós-login
                    log_info("Login bem-sucedido.")
                    return # <<< SUCESSO: Sai da função
                except PWTimeoutError:
                    log_info("Login falhou. Tentando resolver o CAPTCHA novamente.")
                    # A própria estrutura do loop já fará ele recarregar a página
            else:
                 log_info("CAPTCHA não resolvido corretamente. Tentando novamente.")
        
        except PWTimeoutError as e:
            log_error(f"Timeout ao tentar carregar a página na tentativa {tentativa}: {e}")
            if tentativa < MAX_RETRIES:
                log_info("Aguardando 5 segundos antes de tentar novamente...")
                time.sleep(5)
            else:
                log_error("Número máximo de tentativas de login atingido. Desistindo.")
                raise e # <<< ERRO: Levanta a exceção após todas as tentativas falharem
        except Exception as e:
            log_error(f"Erro inesperado durante o login (tentativa {tentativa}): {e}")
            if tentativa < MAX_RETRIES:
                time.sleep(5)
            else:
                raise e
        
        # Recarrega a página se não deu certo, para pegar um novo captcha
        if page.url != portal_url:
            page.goto(portal_url)


def acessar_empresa_via_link(page, cnpj: str, ccm: str, base_root: str) -> None:
    url_emp = f"{base_root}/main.php?acao=acessar&ccm={ccm}&cnpj={cnpj}"
    page.goto(url_emp, wait_until="domcontentloaded", timeout=30000)
    
    try:
        body_text = page.frame_locator("#main").locator("body").inner_text(timeout=5000)
    except Exception:
        body_text = page.locator("body").inner_text(timeout=5000)
    
    text_lower = body_text.lower()
    if "contribuinte não possui procuração eletrônica" in text_lower or "contribuinte não encontrado" in text_lower:
        raise Exception("Empresa sem procuração, ou CNPJ/CCM incorretos.")
        
    log_info(f"Acesso à empresa {cnpj} bem-sucedido.")

def ir_para_movimento(page) -> None:
    page.locator("td.menu:has-text('Movimento (Contribuinte)')").first.click()
    page.frame_locator("#main").locator("body").first.wait_for()

def selecionar_competencia(page, comp: str) -> None:
    ano, mes = parse_competencia(comp)
    MESES = ["Janeiro","Fevereiro","Março","Abril","Maio","Junho","Julho","Agosto","Setembro","Outubro","Novembro","Dezembro"]
    fl = page.frame_locator("#main")
    fl.locator("select[name='mes']").select_option(label=MESES[mes-1])
    fl.locator("input[name='ano']").fill(str(ano))
    fl.locator("button[name='btnOk']").click()
    fl.locator("text='Serviços Prestados'").first.wait_for()

def encerrar_escrituracao(page, comp: str) -> None:
    for tipo_sufixo, tipo_nome in [("p", "Prestados"), ("t", "Tomados")]:
        fl = page.frame_locator("#main")
        table_id = f"tableEncerra_{tipo_sufixo}"
        
        try:
            if fl.locator(f"#{table_id}[style*='display:none']").count():
                fl.locator(f"td[onclick*='{table_id}']").first.click()
        except Exception: pass

        link_loc = fl.locator(f"#{table_id} a")
        if "encerrar escrituração" in link_loc.inner_text(timeout=5000).lower():
            log_info(f"A encerrar livro de Serviços {tipo_nome}...")
            link_loc.click()

            try:
                fl.locator("text='Encerrar Escrituração \"SEM MOVIMENTO\"'").wait_for(timeout=3000)
                log_info(f"AVISO: Livro de Serviços {tipo_nome} tem notas para validar. O encerramento será ignorado.")
                ir_para_movimento(page)
                selecionar_competencia(page, comp)
                continue
            except PWTimeoutError:
                log_info("Confirmando encerramento...")
                fl.get_by_role("button", name=re.compile("encerrar", re.IGNORECASE)).first.click()
                log_info("Encerrado com sucesso.")
                ir_para_movimento(page)
                selecionar_competencia(page, comp)
        else:
            log_info(f"Livro de Serviços {tipo_nome} já está encerrado.")

def baixar_livro_mensal_pdf(page, tipo: str, comp: str, client_id: str, cnpj: str, ccm: str, download_dir: Path) -> None:
    ano, mes = parse_competencia(comp)
    comp_formatada_arquivo = f"{mes:02d}{ano:04d}"

    full_folder_path = download_dir / 'LIVROS'
    full_folder_path.mkdir(parents=True, exist_ok=True)

    file_name = f"{client_id} - LIVRO {tipo.upper()} - {comp_formatada_arquivo}.pdf"
    destino = full_folder_path / _sanitize_filename_part(file_name)

    sufixo_url = "prestado" if tipo.lower().startswith("p") else "tomado"
    url_livro = f"https://taubateiss.meumunicipio.digital/taubateiss/cgi-local/contribuinte/livro/livro_fiscal_mensal_{sufixo_url}_pdf.php?ccm={ccm}&cnpj={cnpj}&mes={mes:02d}&ano={ano:04d}"

    s = requests.Session()
    for cookie in page.context.cookies():
        s.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'])

    response = s.get(url_livro, timeout=60)
    response.raise_for_status()
    if "application/pdf" in response.headers.get("Content-Type", ""):
        with open(destino, "wb") as f: f.write(response.content)
        log_info(f"SUCESSO: Livro de {tipo} salvo em '{destino}'")

# --- Função Principal do Módulo ---
def executar_baixa_livros(clientes: List[Dict], config_geral: Dict, competencia: str, download_dir: str, headful: bool, status_obj: Optional[Dict] = None):
    from playwright.sync_api import sync_playwright
    
    total_clientes = len(clientes)
    final_download_dir = Path(download_dir or config_geral.get('pasta_saida_padrao') or DOWNLOAD_DIR)
    ctx = None
    
    with sync_playwright() as p:
        try:
            _update_status(status_obj, 10, "Iniciando navegador para baixar livros...")
            ctx = p.chromium.launch_persistent_context(PROFILE_DIR, headless=not headful)
            page = ctx.new_page()
            
            _update_status(status_obj, 15, "Fazendo login no portal do contador...")
            login_contador(page,
                           url=config_geral.get("url_taubate", CONTADOR_LOGIN_URL),
                           crc=config_geral.get("crc"),
                           senha=config_geral.get("crc_senha"))
            
            base_root = _contador_root_only(page.url)

            for i, cliente in enumerate(clientes):
                progress = 20 + int((i / total_clientes) * 80)
                _update_status(status_obj, progress, f"Livros ({i+1}/{total_clientes}): Acessando {cliente['id']}...")
                
                try:
                    razao = cliente.get('razao_social') or str(cliente.get('id'))
                    safe_name = _sanitize_filename_part(f"{cliente.get('id')}-{razao}")
                    download_dir_client = final_download_dir / safe_name
                    download_dir_client.mkdir(parents=True, exist_ok=True)
                    
                    acessar_empresa_via_link(page, cliente['cnpj'], cliente['ccm'], base_root)
                    ir_para_movimento(page)
                    selecionar_competencia(page, competencia)
                    
                    encerrar_escrituracao(page, competencia) 
                    
                    baixar_livro_mensal_pdf(page, "Prestados", competencia, cliente['id'], cliente['cnpj'], cliente['ccm'], download_dir_client)
                    baixar_livro_mensal_pdf(page, "Tomados", competencia, cliente['id'], cliente['cnpj'], cliente['ccm'], download_dir_client)
                    
                    log_info(f">>> Sucesso para o ID: {cliente['id']} <<<")

                except Exception as e:
                    log_error(f"ERRO ao processar ID {cliente['id']}: {e}")
            
            _update_status(status_obj, 100, "Baixa de livros finalizada.")

        except Exception as e:
            log_error(f"ERRO CRÍTICO no módulo de baixar livros: {e}")
            if status_obj:
                status_obj['has_error'] = True
                status_obj['message'] = f"Erro crítico ao baixar livros: {e}"
            if ctx:
                ctx.close()
            raise
        
        finally:
            if ctx:
                ctx.close()