"""Lista simplificada de municípios brasileiros e mapeamento para modelos de integração."""
from typing import List
import unicodedata

MUNICIPIOS_LIST: List[str] = [
    "Taubaté", "São Paulo", "Campinas", "Santo André", "São Bernardo do Campo",
    "Ribeirão Preto", "Belo Horizonte", "Rio de Janeiro", "Niterói", "Salvador",
    "Porto Alegre", "Curitiba", "Florianópolis", "Brasília", "Goiânia", "Fortaleza",
]

MUNICIPIO_MODELS = {
    "taubate": "taubate",
    "sao paulo": "sao_paulo_municipal",
    "campinas": "campinas",
    "rio de janeiro": "rio_de_janeiro",
    "belo horizonte": "belo_horizonte",
}

def _normalize(name: str) -> str:
    if not name: return ""
    nf = unicodedata.normalize('NFKD', name)
    only_ascii = ''.join(c for c in nf if not unicodedata.combining(c))
    return only_ascii.strip().lower()

def get_model_for_municipio(municipio: str) -> str:
    if not municipio: return "generic"
    key = _normalize(municipio)
    return MUNICIPIO_MODELS.get(key, "generic")

def add_municipio(name: str, model_key: str = "generic"):
    if not name: return
    if name not in MUNICIPIOS_LIST:
        MUNICIPIOS_LIST.append(name)
    MUNICIPIO_MODELS[_normalize(name)] = model_key