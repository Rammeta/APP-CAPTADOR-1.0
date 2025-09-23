#--------------------------------------------------------------------------
# interface_principal.py - v2.3 (Refatorado para usar robo_core)
#--------------------------------------------------------------------------
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
import threading
import sys
import os
import subprocess
import queue
from typing import List, Dict, Optional
from datetime import datetime
import re

# Módulos do projeto
import robo_core # <- NOSSA GRANDE MUDANÇA!
from modulos import logger
from modulos.logger import log_queue
import gestor_db as db
import gestor_config as config

# ======================================================================
# CLASSE PRINCIPAL DA APLICAÇÃO
# ======================================================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("Robô Fiscal Integrado")
        self.root.geometry("1000x700")

        style = ttk.Style()
        style.theme_use('clam')

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(pady=10, padx=10, fill="both", expand=True)

        # --- Criar as abas PRIMEIRO ---
        self.tab_gestao_clientes = ttk.Frame(self.notebook)
        self.tab_captura_nf = ttk.Frame(self.notebook)
        self.tab_baixa_livros = ttk.Frame(self.notebook)
        self.tab_config = ttk.Frame(self.notebook)
        self.tab_log = ttk.Frame(self.notebook)

        # --- Adicionar as abas ao Notebook ---
        self.notebook.add(self.tab_gestao_clientes, text='  Gestão de Clientes  ')
        self.notebook.add(self.tab_captura_nf, text='  Capturar Notas Fiscais  ')
        self.notebook.add(self.tab_baixa_livros, text='  Baixar Livros Fiscais  ')
        self.notebook.add(self.tab_config, text='  Configurações  ')
        self.notebook.add(self.tab_log, text='  Log de Execução  ')

        # --- Agora, popular cada aba com seu conteúdo ---
        self.setup_gestao_clientes_tab()
        self.setup_captura_nf_tab()
        self.setup_baixa_livros_tab()
        self.setup_config_tab()
        self.setup_log_tab()

        # --- Inicialização ---
        self.load_clients()
        self.load_settings()
        self.process_log_queue()

    def setup_gestao_clientes_tab(self):
        tree_frame = ttk.Frame(self.tab_gestao_clientes)
        tree_frame.pack(pady=10, padx=10, fill="both", expand=True)
        scrollbar = ttk.Scrollbar(tree_frame)
        scrollbar.pack(side="right", fill="y")
        self.tree = ttk.Treeview(
            tree_frame,
            columns=("ID", "Nome", "CNPJ", "Certificado", "Senha"),
            show="headings",
            yscrollcommand=scrollbar.set
        )
        self.tree.pack(fill="both", expand=True)
        scrollbar.config(command=self.tree.yview)
        self.tree.heading("ID", text="ID"); self.tree.column("ID", width=50)
        self.tree.heading("Nome", text="Nome"); self.tree.column("Nome", width=200)
        self.tree.heading("CNPJ", text="CNPJ"); self.tree.column("CNPJ", width=120)
        self.tree.heading("Certificado", text="Caminho do Certificado"); self.tree.column("Certificado", width=300)
        self.tree.heading("Senha", text="Senha"); self.tree.column("Senha", width=80)
        
        crud_buttons_frame = ttk.Frame(self.tab_gestao_clientes)
        crud_buttons_frame.pack(pady=10)
        ttk.Button(crud_buttons_frame, text="Adicionar Cliente", command=self.add_client).pack(side="left", padx=5)
        ttk.Button(crud_buttons_frame, text="Editar Cliente", command=self.edit_client).pack(side="left", padx=5)
        ttk.Button(crud_buttons_frame, text="Excluir Cliente", command=self.delete_client).pack(side="left", padx=5)
        ttk.Button(crud_buttons_frame, text="Importar CSV", command=lambda: self.iniciar_thread(self.import_clients_csv)).pack(side="left", padx=5)
        ttk.Button(crud_buttons_frame, text="Baixar Modelo CSV", command=lambda: self.iniciar_thread(self.export_clients_csv_template)).pack(side="left", padx=5)

    def setup_captura_nf_tab(self):
        captura_frame = ttk.Frame(self.tab_captura_nf)
        captura_frame.pack(pady=20, padx=10, fill="x")
        ttk.Label(captura_frame, text="Data Início (DD/MM/AAAA):").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.data_inicio_var = tk.StringVar(value=(datetime.now().replace(day=1)).strftime("%d/%m/%Y"))
        ttk.Entry(captura_frame, textvariable=self.data_inicio_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(captura_frame, text="Data Fim (DD/MM/AAAA):").grid(row=1, column=0, padx=5, pady=5, sticky="w")
        self.data_fim_var = tk.StringVar(value=datetime.now().strftime("%d/%m/%Y"))
        ttk.Entry(captura_frame, textvariable=self.data_fim_var).grid(row=1, column=1, padx=5, pady=5, sticky="ew")
        ttk.Label(captura_frame, text="Pasta de Saída:").grid(row=2, column=0, padx=5, pady=5, sticky="w")
        self.pasta_saida_nf_var = tk.StringVar(value=os.path.join(os.getcwd(), "saida_nf"))
        ttk.Entry(captura_frame, textvariable=self.pasta_saida_nf_var).grid(row=2, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(captura_frame, text="Procurar...", command=self.browse_saida_nf_dir).grid(row=2, column=2, padx=5)
        captura_frame.columnconfigure(1, weight=1)
        
        self.btn_iniciar_captura = ttk.Button(self.tab_captura_nf, text="Iniciar Captura de Notas Prestadas", command=self.start_run_captura_nf)
        self.btn_iniciar_captura.pack(pady=20)
        
        self.btn_iniciar_captura_tomadas = ttk.Button(self.tab_captura_nf, text="Iniciar Captura de Notas Tomadas", command=self.start_run_captura_nf_tomadas)
        self.btn_iniciar_captura_tomadas.pack(pady=5)
        
        self.btn_iniciar_captura_both = ttk.Button(self.tab_captura_nf, text="Capturar Notas Prestadas e Tomadas", command=self.start_run_captura_nf_both)
        self.btn_iniciar_captura_both.pack(pady=5)

    def setup_baixa_livros_tab(self):
        baixa_frame = ttk.Frame(self.tab_baixa_livros)
        baixa_frame.pack(pady=20, padx=10, fill="x")
        ttk.Label(baixa_frame, text="Competência (AAAA-MM):").pack(pady=(10, 0))
        self.competencia_var = tk.StringVar(value=datetime.now().strftime("%Y-%m"))
        ttk.Entry(baixa_frame, textvariable=self.competencia_var).pack(pady=5)
        
        self.headful_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(baixa_frame, text="Ver Execução do Navegador (Modo de Depuração)", variable=self.headful_var).pack(pady=10)

        download_frame = ttk.Frame(baixa_frame)
        download_frame.pack(fill="x", expand=True)
        ttk.Label(download_frame, text="Pasta de Download:").grid(row=0, column=0, padx=5, pady=5, sticky="w")
        self.pasta_download_livros_var = tk.StringVar(value=os.path.join(os.getcwd(), "downloads"))
        ttk.Entry(download_frame, textvariable=self.pasta_download_livros_var).grid(row=0, column=1, padx=5, pady=5, sticky="ew")
        ttk.Button(download_frame, text="Procurar...", command=self.browse_download_livros_dir).grid(row=0, column=2, padx=5)
        download_frame.columnconfigure(1, weight=1)
        
        self.btn_iniciar_baixa = ttk.Button(self.tab_baixa_livros, text="Iniciar Baixa de Livros", command=self.start_run_baixa_livros)
        self.btn_iniciar_baixa.pack(pady=20)

    def setup_config_tab(self):
        config_frame = ttk.LabelFrame(self.tab_config, text="Configurações Gerais", padding=(10, 5))
        config_frame.pack(pady=20, padx=10, fill="x")
        self.config_vars = {
            "pfx_padrao_path": tk.StringVar(), "pfx_padrao_pwd": tk.StringVar(),
            "crc": tk.StringVar(), "crc_senha": tk.StringVar(),
            "pasta_saida_padrao": tk.StringVar()
        }
        labels = {
            "pfx_padrao_path": "Certificado Padrão (.pfx)", "pfx_padrao_pwd": "Senha do Certificado",
            "crc": "Login CRC", "crc_senha": "Senha CRC",
            "pasta_saida_padrao": "Pasta de Saída Padrão"
        }
        for i, (key, label_text) in enumerate(labels.items()):
            ttk.Label(config_frame, text=label_text + ":").grid(row=i, column=0, padx=5, pady=8, sticky="w")
            entry = ttk.Entry(config_frame, textvariable=self.config_vars[key], width=60, show="*" if "senha" in key or "pwd" in key else "")
            entry.grid(row=i, column=1, padx=5, pady=8, sticky="ew")
            if key == "pfx_padrao_path":
                ttk.Button(config_frame, text="Procurar...", command=lambda v=self.config_vars[key]: self.browse_pfx_file(v)).grid(row=i, column=2, padx=5)
            if key == "pasta_saida_padrao":
                ttk.Button(config_frame, text="Procurar...", command=lambda v=self.config_vars[key]: self.browse_folder_var(v)).grid(row=i, column=2, padx=5)

        config_frame.columnconfigure(1, weight=1)
        save_button = ttk.Button(config_frame, text="Salvar Configurações", command=self.save_settings)
        save_button.grid(row=len(labels), column=0, columnspan=3, pady=20)
        
        playwright_frame = ttk.LabelFrame(self.tab_config, text="Ambiente de Automação", padding=(10, 5))
        playwright_frame.pack(pady=20, padx=10, fill="x")
        ttk.Label(playwright_frame, text="O robô de baixa de livros fiscais usa a tecnologia Playwright.\nClique no botão abaixo para instalar os navegadores necessários para a automação.").pack(pady=10)
        install_button = ttk.Button(playwright_frame, text="Instalar/Atualizar Navegadores do Playwright", command=lambda: self.iniciar_thread(self.install_playwright))
        install_button.pack(pady=10)

    def setup_log_tab(self):
        log_frame = ttk.LabelFrame(self.tab_log, text="Console de Saída Global", padding=(10, 5))
        log_frame.pack(pady=10, padx=10, fill="both", expand=True)
        controls = ttk.Frame(log_frame)
        controls.pack(fill="x", pady=(0, 5))
        ttk.Button(controls, text="Limpar Console", command=self.clear_console).pack(side="right")
        self.log_console = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, state='disabled')
        self.log_console.pack(fill="both", expand=True)

    def clear_console(self):
        try:
            self.log_console.configure(state='normal')
            self.log_console.delete('1.0', tk.END)
            self.log_console.configure(state='disabled')
        except Exception as e:
            logger.log_error(f"Falha ao limpar o console da GUI: {e}")

        try:
            while not log_queue.empty():
                log_queue.get_nowait()
        except queue.Empty:
            pass
        except Exception as e:
            logger.log_error(f"Falha ao esvaziar a fila de logs: {e}")

        log_path_candidates = []
        if hasattr(logger, 'LOG_FILE_PATH'):
            log_path_candidates.append(logger.LOG_FILE_PATH)
        root_log = os.path.join(os.getcwd(), 'robo_log.txt')
        if os.path.exists(root_log):
            log_path_candidates.append(root_log)

        for p in set(log_path_candidates):
            try:
                with open(p, 'w', encoding='utf-8') as fh:
                    fh.truncate(0)
            except Exception as e:
                logger.log_error(f"Falha ao truncar o arquivo de log {p}: {e}")

    def process_log_queue(self):
        try:
            while True:
                record = log_queue.get_nowait()
                self.log_console.configure(state='normal')
                self.log_console.insert(tk.END, record + '\n')
                self.log_console.configure(state='disabled')
                self.log_console.see(tk.END)
        except queue.Empty:
            pass
        self.root.after(100, self.process_log_queue)

    def iniciar_thread(self, target_func, *args):
        thread = threading.Thread(target=target_func, args=args)
        thread.daemon = True
        thread.start()

    def get_selected_clients_data(self) -> Optional[List[Dict]]:
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Nenhuma Seleção", "Por favor, selecione um ou mais clientes.")
            self.notebook.select(0)
            return None
        all_clients = db.get_all_clients()
        selected_ids = {str(self.tree.item(item)['values'][0]) for item in selected_items}
        return [dict(c) for c in all_clients if c['id'] in selected_ids]

    # --- Funções de "Start" que coletam dados da UI e chamam o robo_core ---
    
    def start_run_baixa_livros(self):
        clientes_selecionados = self.get_selected_clients_data()
        if not clientes_selecionados: return
        
        self.btn_iniciar_baixa.config(state="disabled")
        
        # Coleta os dados da UI
        competencia = self.competencia_var.get()
        download_dir = self.pasta_download_livros_var.get()
        headful_mode = self.headful_var.get()

        # Inicia a thread com a função do robo_core e reabilita o botão no final
        self.iniciar_thread(
            lambda: (
                robo_core.run_baixa_livros(clientes_selecionados, self.config_geral, competencia, download_dir, headful_mode),
                self.btn_iniciar_baixa.config(state="normal")
            )
        )

    def start_run_captura_nf(self):
        clientes_selecionados = self.get_selected_clients_data()
        if not clientes_selecionados: return

        self.btn_iniciar_captura.config(state="disabled")
        data_inicio = self.data_inicio_var.get()
        data_fim = self.data_fim_var.get()
        pasta_saida = self.pasta_saida_nf_var.get()

        self.iniciar_thread(
            lambda: (
                robo_core.run_captura_nf(clientes_selecionados, self.config_geral, data_inicio, data_fim, pasta_saida),
                self.btn_iniciar_captura.config(state="normal")
            )
        )
        
    def start_run_captura_nf_tomadas(self):
        clientes_selecionados = self.get_selected_clients_data()
        if not clientes_selecionados: return

        self.btn_iniciar_captura_tomadas.config(state="disabled")
        data_inicio = self.data_inicio_var.get()
        data_fim = self.data_fim_var.get()
        pasta_saida = self.pasta_saida_nf_var.get()

        self.iniciar_thread(
            lambda: (
                robo_core.run_captura_nf_tomadas(clientes_selecionados, self.config_geral, data_inicio, data_fim, pasta_saida),
                self.btn_iniciar_captura_tomadas.config(state="normal")
            )
        )

    def start_run_captura_nf_both(self):
        clientes_selecionados = self.get_selected_clients_data()
        if not clientes_selecionados: return
        
        self.btn_iniciar_captura.config(state="disabled")
        self.btn_iniciar_captura_tomadas.config(state="disabled")
        self.btn_iniciar_captura_both.config(state="disabled")

        data_inicio = self.data_inicio_var.get()
        data_fim = self.data_fim_var.get()
        pasta_saida = self.pasta_saida_nf_var.get()
        
        self.iniciar_thread(
            lambda: (
                robo_core.run_captura_nf_both(clientes_selecionados, self.config_geral, data_inicio, data_fim, pasta_saida),
                self.btn_iniciar_captura.config(state="normal"),
                self.btn_iniciar_captura_tomadas.config(state="normal"),
                self.btn_iniciar_captura_both.config(state="normal")
            )
        )

    # --- Funções de gestão de clientes e UI ---

    def load_clients(self):
        for i in self.tree.get_children(): self.tree.delete(i)
        for client in db.get_all_clients():
            self.tree.insert("", "end", values=(
                client['id'], client['razao_social'], client['cnpj'],
                client['pfx_path'], client['pfx_pwd']
            ))

    def add_client(self): self.show_client_dialog()
    
    def edit_client(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Nenhuma Seleção", "Por favor, selecione um cliente para editar.")
            return
        client_id_original = self.tree.item(selected_items[0])['values'][0]
        client_data = db.get_client_by_id(client_id_original)
        if not client_data:
            messagebox.showerror("Erro", f"Cliente com ID {client_id_original} não encontrado.")
            return
        self.show_client_dialog(client_data=dict(client_data), client_id_original=client_id_original)

    def delete_client(self):
        selected_items = self.tree.selection()
        if not selected_items:
            messagebox.showwarning("Nenhuma Seleção", "Por favor, selecione um cliente para excluir.")
            return
        item = self.tree.item(selected_items[0])['values']
        client_id, client_name = item[0], item[1]
        if messagebox.askyesno("Confirmar Exclusão", f"Tem certeza que deseja excluir '{client_name}'?"):
            db.delete_client(str(client_id))
            self.load_clients()

    def show_client_dialog(self, client_data=None, client_id_original=None):
        import municipios

        dialog = tk.Toplevel(self.root); dialog.title("Adicionar/Editar Cliente")
        fields = ["id", "razao_social", "cnpj", "ccm", "municipio", "pfx_path", "pfx_pwd"]
        entries = {}
        for i, field in enumerate(fields):
            ttk.Label(dialog, text=field.replace('_', ' ').title() + ":").grid(row=i, column=0, padx=10, pady=5, sticky="w")
            var = tk.StringVar(value=client_data.get(field, "") if client_data else "")
            if field == 'municipio':
                combo = ttk.Combobox(dialog, values=municipios.MUNICIPIOS_LIST, textvariable=var)
                combo.grid(row=i, column=1, padx=10, pady=5, sticky='ew')
                entries[field] = var
                model_label_var = tk.StringVar(value=f"Modelo: {municipios.get_model_for_municipio(var.get())}")
                lbl = ttk.Label(dialog, textvariable=model_label_var)
                lbl.grid(row=i, column=2, padx=5)

                def on_municipio_change(event, v=var, mlv=model_label_var):
                    mlv.set(f"Modelo: {municipios.get_model_for_municipio(v.get())}")

                combo.bind('<<ComboboxSelected>>', on_municipio_change)
                combo.bind('<FocusOut>', on_municipio_change)
            else:
                entry = ttk.Entry(dialog, textvariable=var, width=50)
                entry.grid(row=i, column=1, padx=10, pady=5)
                entries[field] = var
                if field == "pfx_path":
                    ttk.Button(dialog, text="Procurar...", command=lambda v=var: self.browse_pfx_file(v)).grid(row=i, column=2, padx=5)
        ttk.Button(dialog, text="Salvar", command=lambda: self.save_client(dialog, entries, client_id_original)).grid(row=len(fields), column=0, columnspan=3, pady=10)

    def save_client(self, dialog, entries, client_id_original=None):
        client_data = {key: var.get() for key, var in entries.items()}
        if not all(client_data.get(k) for k in ["id", "razao_social", "cnpj", "ccm"]):
            messagebox.showerror("Campos Obrigatórios", "ID, Razão Social, CNPJ e CCM são obrigatórios.")
            return
        try:
            if client_id_original:
                if client_data['id'] != str(client_id_original):
                    db.add_client(client_data)
                    db.delete_client(str(client_id_original))
                else:
                    db.update_client(str(client_id_original), client_data)
            else:
                db.add_client(client_data)
            self.load_clients()
            dialog.destroy()
        except Exception as e:
            messagebox.showerror("Erro ao Salvar", f"Ocorreu um erro: {e}")

    def browse_pfx_file(self, path_var):
        filepath = filedialog.askopenfilename(title="Selecione o Certificado", filetypes=[("Certificados PFX", "*.pfx"), ("Todos", "*.*")])
        if filepath: path_var.set(filepath)
    def browse_saida_nf_dir(self):
        dirpath = filedialog.askdirectory(title="Selecione a Pasta de Saída para as Notas")
        if dirpath: self.pasta_saida_nf_var.set(dirpath)
    def browse_download_livros_dir(self):
        dirpath = filedialog.askdirectory(title="Selecione a Pasta de Download para os Livros")
        if dirpath: self.pasta_download_livros_var.set(dirpath)
    def browse_folder_var(self, var: tk.StringVar):
        dirpath = filedialog.askdirectory(title="Selecione a Pasta")
        if dirpath: var.set(dirpath)

    def import_clients_csv(self):
        from csv import DictReader
        filepath = filedialog.askopenfilename(title="Selecionar CSV de Clientes", filetypes=[("CSV", "*.csv")])
        if not filepath: return
        
        try:
            with open(filepath, newline='', encoding='utf-8-sig') as f:
                # Detect delimiter
                sniffer = csv.Sniffer()
                dialect = sniffer.sniff(f.read(1024), delimiters=';,')
                f.seek(0)
                reader = DictReader(f, dialect=dialect)
                parsed_rows = [row for row in reader]

            self.preview_and_import_csv(parsed_rows)
        except Exception as e:
            logger.log_error(f"Erro ao importar CSV: {e}")
            messagebox.showerror("Erro de Importação", f"Não foi possível ler o arquivo CSV. Verifique o formato e a codificação (use UTF-8).\n\nDetalhe: {e}")
    
    def export_clients_csv_template(self):
        import csv
        save_path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV files", "*.csv")])
        if not save_path: return
        try:
            with open(save_path, 'w', newline='', encoding='utf-8-sig') as f:
                writer = csv.writer(f, delimiter=';')
                writer.writerow(['id','razao_social','cnpj','ccm','pfx_path','pfx_pwd','municipio'])
                writer.writerow(['123','Empresa Exemplo LTDA','12345678000195','000123','C:\\certs\\exemplo.pfx','senha123','Taubate'])
            messagebox.showinfo("Sucesso", f"Modelo CSV salvo em:\n{save_path}")
        except Exception as e:
            logger.log_error(f"Erro ao exportar modelo CSV: {e}")
            messagebox.showerror("Erro", f"Não foi possível salvar o arquivo:\n{e}")


    def preview_and_import_csv(self, rows: list):
        if not rows:
            messagebox.showinfo("Importar CSV", "Nenhum dado encontrado no arquivo.")
            return

        preview_win = tk.Toplevel(self.root)
        preview_win.title("Preview da Importação de Clientes")
        
        cols = list(rows[0].keys())
        tree = ttk.Treeview(preview_win, columns=cols, show='headings')
        for c in cols:
            tree.heading(c, text=c)
        tree.pack(fill='both', expand=True, padx=10, pady=5)

        for r in rows[:20]: # Mostra as primeiras 20 linhas
            tree.insert('', 'end', values=[r.get(c,'') for c in cols])
        
        update_var = tk.BooleanVar()
        ttk.Checkbutton(preview_win, text="Atualizar clientes existentes se o ID já existir", variable=update_var).pack(pady=5)
        
        def do_import():
            preview_win.destroy()
            self.iniciar_thread(self._do_import_rows, rows, update_var.get())
            
        ttk.Button(preview_win, text="Confirmar Importação", command=do_import).pack(pady=10)

    def _do_import_rows(self, rows: list, update_existing: bool):
        successes, failures = 0, []
        for row in rows:
            try:
                # Normaliza os cabeçalhos para minúsculo
                client_data = {k.lower(): v for k, v in row.items()}
                
                if update_existing and db.get_client_by_id(client_data['id']):
                    db.update_client(client_data['id'], client_data)
                else:
                    db.add_client(client_data)
                successes += 1
            except Exception as e:
                failures.append((row.get('id', 'ID não encontrado'), str(e)))
        
        summary = f"Importação concluída!\n\nSucessos: {successes}\nFalhas: {len(failures)}"
        if failures:
            logger.log_error(f"Falhas na importação de CSV: {failures}")
            summary += "\n\nVerifique o log de execução para detalhes sobre as falhas."
        
        messagebox.showinfo("Resultado da Importação", summary)
        self.load_clients()

    def load_settings(self):
        self.config_geral = config.load()
        for key, var in self.config_vars.items():
            var.set(self.config_geral.get(key, ""))
            
    def save_settings(self):
        for key, var in self.config_vars.items():
            self.config_geral[key] = var.get()
        config.save(self.config_geral)
        self.load_settings() # Recarrega para garantir consistência
        messagebox.showinfo("Sucesso", "Configurações salvas com sucesso!")

    def install_playwright(self):
        logger.log_info("Iniciando a instalação dos navegadores do Playwright...")
        try:
            command = [sys.executable, "-m", "playwright", "install"]
            # CREATE_NO_WINDOW evita que uma janela de console preta apareça no Windows
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, creationflags=subprocess.CREATE_NO_WINDOW)
            
            for line in iter(process.stdout.readline, ''):
                logger.log_info(line.strip())
            
            stderr_output = process.stderr.read()
            if stderr_output:
                logger.log_error(stderr_output.strip())
            
            process.wait()

            if process.returncode == 0:
                messagebox.showinfo("Sucesso", "Navegadores do Playwright instalados/atualizados com sucesso!")
            else:
                messagebox.showerror("Erro na Instalação", f"Ocorreu um erro durante a instalação. Verifique o log de execução para mais detalhes.")
        except Exception as e:
            logger.log_error(f"Falha ao executar o comando de instalação do Playwright: {e}")
            messagebox.showerror("Erro", f"Não foi possível iniciar a instalação: {e}")

if __name__ == "__main__":
    try:
        # Inicializa o banco de dados antes de iniciar a UI
        db.initialize_db()
        
        logger.log_info("Aplicação iniciada.")
        root = tk.Tk()
        app = App(root)
        root.mainloop()
        logger.log_info("Aplicação encerrada.")
    except Exception as e:
        logger.log_error(f"Erro fatal na aplicação: {e}")
        messagebox.showerror("Erro Crítico", f"A aplicação encontrou um erro fatal e precisa ser fechada.\n\nDetalhes: {e}")