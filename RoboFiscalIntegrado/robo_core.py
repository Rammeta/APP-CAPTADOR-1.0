#--------------------------------------------------------------------------
# robo_core.py - v1.4 CORREÇÃO DEFINITIVA DA ROTINA COMPLETA
#--------------------------------------------------------------------------
import os
import re
import time
import sys
from datetime import datetime
from typing import List, Dict, Optional

from modulos import logger, capturador_nf_taubate, portal_livros_taubate

_FORBIDDEN = r'<>:"/\\|?*\0'

def _update_status(status_obj: Dict, progress: int, message: str, is_done: bool = False, has_error: bool = False):
    if not status_obj: return
    status_obj['progress'] = progress
    status_obj['message'] = message
    status_obj['is_done'] = is_done
    status_obj['has_error'] = has_error

def run_baixa_livros(clientes_selecionados: List[Dict], config_geral: Dict, competencia: str, download_dir: str, headful_mode: bool, status_obj: Optional[Dict] = None, part_of_routine: bool = False):
    total_clientes = len(clientes_selecionados)
    if not part_of_routine:
        _update_status(status_obj, 5, f"Iniciando baixa de livros para {total_clientes} cliente(s)...")
    try:
        if not clientes_selecionados:
            if not part_of_routine:
                _update_status(status_obj, 100, "Nenhum cliente selecionado.", is_done=True)
            return
        final_download_dir = download_dir or config_geral.get('pasta_saida_padrao') or os.getcwd()
        portal_livros_taubate.executar_baixa_livros(
            clientes_selecionados, config_geral, competencia, final_download_dir, headful=headful_mode, status_obj=status_obj
        )
        if not part_of_routine:
            _update_status(status_obj, 100, "Baixa de livros concluída com sucesso!", is_done=True)
    except Exception as e:
        error_message = f"Erro ao baixar livros: {e}"
        logger.log_error(error_message, exc_info=sys.exc_info())
        _update_status(status_obj, 100, error_message, is_done=True, has_error=True)

def run_captura_nf_both(clientes_selecionados: List[Dict], config_geral: Dict, data_inicio_str: str, data_fim_str: str, pasta_saida: str, status_obj: Optional[Dict] = None, part_of_routine: bool = False):
    total_clientes = len(clientes_selecionados)
    start_progress = 50 if part_of_routine else 0
    _update_status(status_obj, start_progress, f"Iniciando captura de notas para {total_clientes} cliente(s)...")
    
    final_pasta_saida = pasta_saida or config_geral.get('pasta_saida_padrao') or os.getcwd()
    
    for i, cliente in enumerate(clientes_selecionados):
        try:
            progress_slice = int(((i + 1) / total_clientes) * 50)
            progress = start_progress + progress_slice
            
            _update_status(status_obj, progress - 5, f"({i+1}/{total_clientes}) Capturando PRESTADAS de {cliente.get('id')}...")
            capturador_nf_taubate.capturar_notas(cliente, config_geral, datetime.strptime(data_inicio_str, "%d/%m/%Y").date(), datetime.strptime(data_fim_str, "%d/%m/%Y").date(), final_pasta_saida)
            
            _update_status(status_obj, progress, f"({i+1}/{total_clientes}) Capturando TOMADAS de {cliente.get('id')}...")
            capturador_nf_taubate.capturar_notas_tomadas(cliente, config_geral, datetime.strptime(data_inicio_str, "%d/%m/%Y").date(), datetime.strptime(data_fim_str, "%d/%m/%Y").date(), final_pasta_saida)
        except Exception as e:
            error_message = f"Erro ao processar cliente {cliente.get('id')}: {e}"
            logger.log_error(error_message, exc_info=sys.exc_info())
            _update_status(status_obj, 100, error_message, is_done=True, has_error=True)
            return

    if not part_of_routine:
        _update_status(status_obj, 100, "Captura de notas concluída com sucesso!", is_done=True)

def run_full_routine(clientes_selecionados: List[Dict], config_geral: Dict, competencia: str, data_inicio_str: str, data_fim_str: str, pasta_saida: str, headful_mode: bool, status_obj: Optional[Dict] = None):
    logger.log_info(f"\n{'='*20}\n--- INICIANDO ROTINA COMPLETA ---\n{'='*20}")
    
    try:
        _update_status(status_obj, 0, "Iniciando Etapa 1: Baixa de Livros...")
        time.sleep(1)
        run_baixa_livros(clientes_selecionados, config_geral, competencia, pasta_saida, headful_mode, status_obj, part_of_routine=True)
        if status_obj and status_obj.get('has_error'):
            return

        _update_status(status_obj, 50, "Etapa 1 concluída. Iniciando Etapa 2: Captura de Notas...")
        time.sleep(1)

        run_captura_nf_both(clientes_selecionados, config_geral, data_inicio_str, data_fim_str, pasta_saida, status_obj, part_of_routine=True)
        if status_obj and status_obj.get('has_error'):
            return

        _update_status(status_obj, 100, "Rotina completa finalizada com sucesso!", is_done=True)
    except Exception as e:
        error_message = f"Erro fatal na rotina completa: {e}"
        logger.log_error(error_message, exc_info=sys.exc_info())
        _update_status(status_obj, 100, error_message, is_done=True, has_error=True)

    logger.log_info(f"\n{'='*20}\n--- ROTINA COMPLETA FINALIZADA ---\n{'='*20}")