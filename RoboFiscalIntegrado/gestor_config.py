#--------------------------------------------------------------------------
# gestor_config.py - Gestor de Configurações Globais (app_settings.json)
#--------------------------------------------------------------------------
import json
import os

# --- Configuração do Caminho Absoluto ---
# Obter o diretório onde este script (gestor_config.py) está localizado.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Definir o caminho absoluto para o arquivo de configurações.
SETTINGS_FILE = os.path.join(SCRIPT_DIR, "app_settings.json")

# Define os valores padrão para TODAS as configurações
DEFAULTS = {
    "pfx_padrao_path": "",
    "pfx_padrao_pwd": "",
    "crc": "",
    "crc_senha": "",
    # Pasta de saída padrão para todos os ficheiros gerados pelo robô
    # Por padrão aponta para uma pasta 'downloads' no diretório atual de trabalho
    "pasta_saida_padrao": os.path.join(os.getcwd(), "downloads")
}

def load() -> dict:
    """Carrega as configurações do ficheiro JSON. Se não existir, cria com valores padrão."""
    if not os.path.exists(SETTINGS_FILE):
        return DEFAULTS.copy()
    
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Garante que todas as chaves padrão existem no ficheiro carregado
        settings = DEFAULTS.copy()
        settings.update(data)
        return settings
    except (json.JSONDecodeError, IOError):
        # Se o ficheiro estiver corrompido ou ilegível, retorna os padrões
        return DEFAULTS.copy()

def save(settings: dict) -> None:
    """Guarda as configurações no ficheiro JSON."""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except IOError as e:
        print(f"Erro ao guardar as configurações: {e}")