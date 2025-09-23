#--------------------------------------------------------------------------
# app_web.py - v1.9 FINAL ESTÁVEL COM TODAS AS ROTAS
#--------------------------------------------------------------------------
import threading
import sys
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
import time
import csv
import io

# Módulos do projeto
import gestor_db as db
import gestor_config as config
import robo_core
from modulos import logger
import municipios

app = Flask(__name__)
app.secret_key = 'uma-chave-secreta-muito-segura'

task_status = {
    "is_running": False, "progress": 0, "message": "Aguardando comando...",
    "is_done": True, "has_error": False
}

@app.route('/')
def index():
    try:
        clientes = db.get_all_clients()
        clientes_dict = [dict(cliente) for cliente in clientes]
        return render_template('index.html', clientes=clientes_dict)
    except Exception as e:
        logger.log_error(f"Erro ao carregar a página inicial: {e}")
        return f"<h1>Erro ao carregar a página inicial. Verifique o log. Detalhe: {e}</h1>"

@app.route('/task_status')
def get_task_status():
    return jsonify(task_status)

def run_task(target_function, *args):
    task_status['is_running'] = True
    task_status['is_done'] = False
    task_status['has_error'] = False
    try:
        target_function(*args, status_obj=task_status)
    except Exception as e:
        error_message = f"Erro inesperado na thread: {e}"
        logger.log_error(error_message, exc_info=sys.exc_info())
        task_status['message'] = error_message
        task_status['has_error'] = True
    finally:
        task_status['is_running'] = False
        task_status['is_done'] = True

@app.route('/executar-captura-notas', methods=['POST'])
def executar_captura_notas():
    if task_status['is_running']:
        return jsonify({"status": "error", "message": "Uma tarefa já está em execução."}), 409
    ids_selecionados = request.form.getlist('clientes')
    if not ids_selecionados:
        return jsonify({"status": "error", "message": "Nenhum cliente selecionado."}), 400

    data_inicio = request.form.get('data_inicio')
    data_fim = request.form.get('data_fim')
    data_inicio_br = datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
    data_fim_br = datetime.strptime(data_fim, '%Y-%m-%d').strftime('%d/%m/%Y')
    configuracoes = config.load()
    clientes_para_rodar = [dict(c) for c in db.get_all_clients() if c['id'] in ids_selecionados]
    thread = threading.Thread(target=run_task, args=(robo_core.run_captura_nf_both, clientes_para_rodar, configuracoes, data_inicio_br, data_fim_br, ""))
    thread.start()
    return jsonify({"status": "started"})

@app.route('/executar-rotina-completa', methods=['POST'])
def executar_rotina_completa():
    if task_status['is_running']:
        return jsonify({"status": "error", "message": "Uma tarefa já está em execução."}), 409
    ids_selecionados = request.form.getlist('clientes')
    if not ids_selecionados:
        return jsonify({"status": "error", "message": "Nenhum cliente selecionado."}), 400

    competencia = request.form.get('competencia')
    data_inicio = request.form.get('data_inicio')
    data_fim = request.form.get('data_fim')
    headful_mode = request.form.get('headful_mode') == 'true'
    data_inicio_br = datetime.strptime(data_inicio, '%Y-%m-%d').strftime('%d/%m/%Y')
    data_fim_br = datetime.strptime(data_fim, '%Y-%m-%d').strftime('%d/%m/%Y')
    configuracoes = config.load()
    clientes_para_rodar = [dict(c) for c in db.get_all_clients() if c['id'] in ids_selecionados]
    thread = threading.Thread(target=run_task, args=(robo_core.run_full_routine, clientes_para_rodar, configuracoes, competencia, data_inicio_br, data_fim_br, "", headful_mode))
    thread.start()
    return jsonify({"status": "started"})
    
@app.route('/executar-baixa-livros', methods=['POST'])
def executar_baixa_livros():
    if task_status['is_running']:
        return jsonify({"status": "error", "message": "Uma tarefa já está em execução."}), 409
    ids_selecionados = request.form.getlist('clientes')
    if not ids_selecionados:
        return jsonify({"status": "error", "message": "Nenhum cliente selecionado."}), 400

    competencia = request.form.get('competencia')
    headful_mode = request.form.get('headful_mode') == 'true'
    configuracoes = config.load()
    clientes_para_rodar = [dict(c) for c in db.get_all_clients() if c['id'] in ids_selecionados]
    thread = threading.Thread(target=run_task, args=(robo_core.run_baixa_livros, clientes_para_rodar, configuracoes, competencia, "", headful_mode))
    thread.start()
    return jsonify({"status": "started"})


@app.route('/cliente/form', methods=['GET'])
def form_cliente():
    client_id = request.args.get('id')
    cliente = {}
    if client_id:
        cliente_data = db.get_client_by_id(client_id)
        if cliente_data:
            cliente = dict(cliente_data)
    return render_template('form_cliente.html', cliente=cliente, municipios_lista=municipios.MUNICIPIOS_LIST)

@app.route('/cliente/novo', methods=['POST'])
def novo_cliente():
    try:
        client_data = request.form.to_dict()
        db.add_client(client_data)
        flash(f"Cliente '{client_data['razao_social']}' adicionado com sucesso!", "success")
    except Exception as e:
        logger.log_error(f"Erro ao adicionar novo cliente: {e}")
        flash(f"Erro ao adicionar cliente: {e}", "error")
    return redirect(url_for('index'))

@app.route('/cliente/editar', methods=['POST'])
def editar_cliente():
    try:
        client_data = request.form.to_dict()
        id_original = client_data.pop('id_original', None)
        if not id_original:
            raise ValueError("ID original do cliente não encontrado para atualização.")
        if id_original != client_data['id']:
            db.add_client(client_data)
            db.delete_client(id_original)
            flash(f"Cliente ID {id_original} alterado para {client_data['id']} com sucesso!", "success")
        else:
            db.update_client(id_original, client_data)
            flash(f"Cliente '{client_data['razao_social']}' atualizado com sucesso!", "success")
    except Exception as e:
        logger.log_error(f"Erro ao editar cliente: {e}")
        flash(f"Erro ao atualizar cliente: {e}", "error")
    return redirect(url_for('index'))

@app.route('/cliente/excluir/<client_id>', methods=['POST'])
def excluir_cliente(client_id):
    try:
        db.delete_client(client_id)
        flash(f"Cliente com ID {client_id} excluído com sucesso!", "success")
    except Exception as e:
        logger.log_error(f"Erro ao excluir cliente {client_id}: {e}")
        flash(f"Erro ao excluir cliente: {e}", "error")
    return redirect(url_for('index'))

@app.route('/cliente/importar_csv', methods=['GET', 'POST'])
def importar_csv():
    if request.method == 'POST':
        if 'csvfile' not in request.files:
            flash('Nenhum arquivo selecionado.', 'warning')
            return redirect(request.url)
        
        file = request.files['csvfile']
        if file.filename == '':
            flash('Nenhum arquivo selecionado.', 'warning')
            return redirect(request.url)

        if file and file.filename.endswith('.csv'):
            try:
                update_existing = request.form.get('update_existing') == 'true'
                stream = io.StringIO(file.stream.read().decode("UTF-8-SIG"), newline=None)
                dialect = csv.Sniffer().sniff(stream.read(1024), delimiters=';,')
                stream.seek(0)
                csv_reader = csv.DictReader(stream, dialect=dialect)
                rows_to_process = [row for row in csv_reader]

                thread = threading.Thread(target=_processar_importacao_csv, args=(rows_to_process, update_existing))
                thread.start()

                flash(f'Importação de {len(rows_to_process)} linhas iniciada em segundo plano.', 'info')
                return redirect(url_for('index'))
            except Exception as e:
                logger.log_error(f"Erro ao processar arquivo CSV: {e}")
                flash(f"Erro ao ler o arquivo CSV: {e}", "error")
                return redirect(request.url)
        else:
            flash("Formato de arquivo inválido. Por favor, envie um arquivo .csv.", "warning")
            return redirect(request.url)
    return render_template('importar_csv.html')

def _processar_importacao_csv(rows, update_existing):
    success_count = 0
    failure_count = 0
    for row in rows:
        try:
            client_data = {k.strip().lower(): v for k, v in row.items()}
            if not all(client_data.get(k) for k in ["id", "razao_social", "cnpj", "ccm"]):
                raise ValueError("Linha não contém todos os campos obrigatórios.")
            if update_existing and db.get_client_by_id(client_data['id']):
                db.update_client(client_data['id'], client_data)
            else:
                db.add_client(client_data)
            success_count += 1
        except Exception as e:
            failure_count += 1
            logger.log_error(f"Falha ao importar linha do CSV (ID: {row.get('id', 'N/A')}): {e}")
    logger.log_info(f"Importação CSV finalizada. Sucessos: {success_count}, Falhas: {failure_count}.")

@app.route('/configuracoes', methods=['GET', 'POST'])
def configuracoes():
    if request.method == 'POST':
        try:
            novas_configs = request.form.to_dict()
            config.save(novas_configs)
            flash("Configurações salvas com sucesso!", "success")
        except Exception as e:
            logger.log_error(f"Erro ao salvar configurações: {e}")
            flash(f"Erro ao salvar configurações: {e}", "error")
        return redirect(url_for('configuracoes'))
    configs_atuais = config.load()
    return render_template('configuracoes.html', config=configs_atuais)

# --- Ponto de Entrada da Aplicação ---
if __name__ == '__main__':
    app.run(host='127.0.0.1', port=5000, debug=True)