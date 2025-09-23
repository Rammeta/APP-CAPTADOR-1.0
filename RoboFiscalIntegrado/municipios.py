"""Lista simplificada de municípios brasileiros e mapeamento para modelos de integração.

Este módulo expõe:
- `MUNICIPIOS_LIST`: lista de nomes apresentáveis para a UI (pode ser estendida).
- `get_model_for_municipio(municipio)`: retorna a chave do modelo a ser usado para integrações.

Notas:
- A lista aqui não é exaustiva. Para suportar todos os municípios do Brasil, substitua
  `MUNICIPIOS_LIST` por uma lista completa (por ex. importando um CSV com IBGE).
- O mapeamento é case-insensitive e normaliza acentos ao comparar.
"""
from typing import List
import unicodedata


MUNICIPIOS_LIST: List[str] = [
    "Taubaté",
    "São Paulo",
    "Campinas",
    "Santo André",
    "São Bernardo do Campo",
    "Ribeirão Preto",
    "Belo Horizonte",
    "Rio de Janeiro",
    "Niterói",
    "Salvador",
    "Porto Alegre",
    "Curitiba",
    "Florianópolis",
    "Brasília",
    "Goiânia",
    "Fortaleza",
]

# Mapeamento simples: município -> modelo/chave que indica qual estratégia usar.
# Os nomes aqui devem coincidir (após normalização) com valores de `MUNICIPIOS_LIST`.
MUNICIPIO_MODELS = {
    "taubate": "taubate",  # uso do módulo específico para Taubaté
    "sao paulo": "sao_paulo_municipal",
    "campinas": "campinas",
    "rio de janeiro": "rio_de_janeiro",
    "belo horizonte": "belo_horizonte",
}


def _normalize(name: str) -> str:
    if not name:
        return ""
    # Remove acentos e transforma para minúsculas
    nf = unicodedata.normalize('NFKD', name)
    only_ascii = ''.join(c for c in nf if not unicodedata.combining(c))
    return only_ascii.strip().lower()


def get_model_for_municipio(municipio: str) -> str:
    """Retorna a chave do modelo para um município, ou 'generic' quando desconhecido."""
    if not municipio:
        return "generic"
    key = _normalize(municipio)
    return MUNICIPIO_MODELS.get(key, "generic")


def add_municipio(name: str, model_key: str = "generic"):
    """Adiciona um município à lista e ao mapeamento (útil para configuração dinâmica)."""
    if not name:
        return
    if name not in MUNICIPIOS_LIST:
        MUNICIPIOS_LIST.append(name)
    MUNICIPIO_MODELS[_normalize(name)] = model_key