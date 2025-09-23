#--------------------------------------------------------------------------
# modulos/logger.py - v1.1 COM CAPTURA GLOBAL DE ERROS
#--------------------------------------------------------------------------
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import traceback
import sys
from datetime import datetime

# --- Configuração do Caminho Absoluto ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(SCRIPT_DIR)
LOG_FILE_PATH = os.path.join(PROJECT_DIR, "robo_log.txt")

# --- Fila para comunicação com a GUI ---
log_queue = queue.Queue()

# --- Handler customizado para a GUI ---
class QueueHandler(logging.Handler):
    """Envia registros de log para uma fila para serem processados pela GUI."""
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def emit(self, record):
        self.queue.put(self.format(record))

# --- Configuração do Logger ---
log_formatter = logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s')

log_handler_file = RotatingFileHandler(LOG_FILE_PATH, maxBytes=1024 * 1024 * 5, backupCount=2, encoding='utf-8')
log_handler_file.setFormatter(log_formatter)

log_handler_queue = QueueHandler(log_queue)
log_handler_queue.setFormatter(log_formatter)

logger = logging.getLogger("RoboFiscalLogger")
logger.setLevel(logging.INFO)

if not logger.handlers:
    logger.addHandler(log_handler_file)
    logger.addHandler(log_handler_queue)

def log_info(message):
    """Regista uma mensagem informativa."""
    logger.info(message)

def log_error(message: str, exc_info=None):
    """Regista uma mensagem de erro com traceback."""
    if exc_info:
        formatted_traceback = "".join(traceback.format_exception(exc_info[0], exc_info[1], exc_info[2]))
    else:
        formatted_traceback = traceback.format_exc()
    
    parts = [f"Mensagem: {message}"]
    
    # Adiciona o traceback apenas se não for um erro "limpo" (sem traceback)
    if "NoneType: None" not in formatted_traceback:
        parts.append("--- TRACEBACK ---")
        parts.append(formatted_traceback)
        
    full_message = "\n".join(parts)
    logger.error(full_message)

# --- CAPTURA GLOBAL DE EXCEÇÕES ---
def handle_exception(exc_type, exc_value, exc_traceback):
    """
    Função "pega-tudo" que será chamada para qualquer erro não tratado no programa.
    """
    if issubclass(exc_type, KeyboardInterrupt):
        # Se o usuário apertou Ctrl+C, não trata como um erro.
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    
    # Loga o erro com todos os detalhes no nosso arquivo de log.
    log_error("Erro não capturado encontrado!", exc_info=(exc_type, exc_value, exc_traceback))

# Substitui o manipulador de exceções padrão do Python pelo nosso.
sys.excepthook = handle_exception