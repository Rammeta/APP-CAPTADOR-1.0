#--------------------------------------------------------------------------
# gestor_db.py - v1.1 com Campo de Município e Migração
#--------------------------------------------------------------------------
import sqlite3
import os
from typing import List, Dict, Optional

# --- Configuração do Caminho Absoluto ---
# Obter o diretório onde este script (gestor_db.py) está localizado.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# Definir o caminho absoluto para o arquivo do banco de dados.
DB_PATH = os.path.join(SCRIPT_DIR, "dados", "clientes.db")

def _migration_add_municipio(con: sqlite3.Connection):
    """Verifica se a coluna 'municipio' existe e, se não, adiciona-a."""
    cur = con.cursor()
    cur.execute("PRAGMA table_info(clientes)")
    columns = [row[1] for row in cur.fetchall()]
    if 'municipio' not in columns:
        print("A executar migração: a adicionar coluna 'municipio'...")
        cur.execute("ALTER TABLE clientes ADD COLUMN municipio TEXT DEFAULT ''")
        con.commit()
        print("Migração concluída.")

def initialize_db():
    """Cria e migra a tabela de clientes para o estado mais recente."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS clientes (
            id TEXT PRIMARY KEY,
            razao_social TEXT NOT NULL,
            cnpj TEXT NOT NULL UNIQUE,
            ccm TEXT NOT NULL,
            pfx_path TEXT,
            pfx_pwd TEXT
        )
    """)
    con.commit()
    
    # Executa as migrações necessárias
    _migration_add_municipio(con)
    
    con.close()

def get_connection():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    return con

# --- Funções de Gestão de Clientes (CRUD) ---

def get_all_clients() -> List[sqlite3.Row]:
    """Retorna todos os clientes cadastrados, incluindo o município."""
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT id, razao_social, cnpj, ccm, pfx_path, pfx_pwd, municipio FROM clientes ORDER BY id")
    clients = cur.fetchall()
    con.close()
    return clients

def get_client_by_id(client_id: str) -> Optional[sqlite3.Row]:
    """Retorna um único cliente pelo seu ID."""
    con = get_connection()
    cur = con.cursor()
    cur.execute("SELECT * FROM clientes WHERE id = ?", (client_id,))
    client = cur.fetchone()
    con.close()
    return client

def add_client(client_data: Dict):
    """Adiciona um novo cliente, incluindo o município."""
    con = get_connection()
    cur = con.cursor()
    try:
        cur.execute(
            "INSERT INTO clientes (id, razao_social, cnpj, ccm, pfx_path, pfx_pwd, municipio) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                client_data['id'], client_data['razao_social'], client_data['cnpj'],
                client_data['ccm'], client_data.get('pfx_path', ''), client_data.get('pfx_pwd', ''),
                client_data.get('municipio', '')
            )
        )
        con.commit()
    except sqlite3.IntegrityError as e:
        if "UNIQUE constraint failed: clientes.id" in str(e):
            raise ValueError(f"O ID '{client_data['id']}' já está em uso.")
        if "UNIQUE constraint failed: clientes.cnpj" in str(e):
            raise ValueError(f"O CNPJ {client_data['cnpj']} já está cadastrado.")
        raise e
    finally:
        con.close()

def update_client(client_id: str, client_data: Dict):
    """Atualiza os dados de um cliente, incluindo o município."""
    con = get_connection()
    cur = con.cursor()
    try:
        cur.execute(
            """UPDATE clientes SET 
               razao_social = ?, cnpj = ?, ccm = ?, pfx_path = ?, pfx_pwd = ?, municipio = ?
               WHERE id = ?""",
            (
                client_data['razao_social'], client_data['cnpj'], client_data['ccm'],
                client_data.get('pfx_path', ''), client_data.get('pfx_pwd', ''),
                client_data.get('municipio', ''), client_id
            )
        )
        con.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"O CNPJ {client_data['cnpj']} já pertence a outro cadastro.")
    finally:
        con.close()

def delete_client(client_id: str):
    con = get_connection()
    cur = con.cursor()
    cur.execute("DELETE FROM clientes WHERE id = ?", (client_id,))
    con.commit()
    con.close()

initialize_db()