# setup_sjc_profile.py
# Este script serve apenas para a configuração inicial do perfil do navegador.
import os
import sys
from playwright.sync_api import sync_playwright

# Define o caminho para a pasta de perfil
PROFILE_PATH = os.path.join(os.getcwd(), "RoboFiscalIntegrado", "dados", "perfil_sjc")

print(f"Iniciando navegador com perfil em: {PROFILE_PATH}")
print("----------------------------------------------------------------")
print("1. A janela do navegador irá abrir.")
print("2. NAVEGUE ATÉ O SITE da prefeitura de SJC.")
print("3. FAÇA O LOGIN com seu certificado digital (selecione-o no pop-up).")
print("4. Após o login ser bem-sucedido, pode FECHAR A JANELA do navegador.")
print("5. O terminal ficará aguardando. Pressione Ctrl+C para sair se necessário.")
print("----------------------------------------------------------------")

with sync_playwright() as p:
    context = p.chromium.launch_persistent_context(
        user_data_dir=PROFILE_PATH,
        headless=False,  # Garante que vejamos o navegador
    )
    # Mantém o script rodando até o navegador ser fechado
    try:
        # page = context.new_page() # Opcional, o navegador já abre com uma página
        context.wait_for_event("close")
    except Exception as e:
        print(f"\nNavegador fechado ou erro: {e}")

print("\nConfiguração concluída! O perfil foi salvo.")
print("Agora você pode rodar o robô principal 'captador_SJC.py'.")