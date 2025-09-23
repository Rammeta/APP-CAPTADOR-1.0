# RoboFiscalIntegrado AI Agent Instructions

This document provides essential guidance for an AI agent working on the `RoboFiscalIntegrado` codebase.

## 1. Project Overview & Architecture

`RoboFiscalIntegrado` is a Python desktop application built with **Tkinter** for its GUI. It automates fiscal tasks for accounting professionals, initially focused on Taubaté but now supports multiple Brazilian municipalities.

The application follows a modular architecture with clear separation of concerns:

- **`interface_principal.py`**: The application's entry point and central controller. Builds a tabbed GUI, manages user interactions, and invokes business logic in separate threads to prevent UI freezing.
- **`gestor_db.py`**: SQLite database layer managing client data (`RoboFiscalIntegrado/dados/clientes.db`). Includes migration support (see `_migration_add_municipio` example).
- **`gestor_config.py`**: Manages application-wide settings in `app_settings.json` (credentials, default paths).
- **`municipios.py`**: Municipality management system with normalized name matching and extensible model mapping for different integration strategies.
- **`modulos/`**: Core business logic modules:
  - **`capturador_nf_taubate.py`**: SOAP client for NFS-e download using `requests` and `requests_pkcs12` with digital certificate authentication.
  - **`portal_livros_taubate.py`**: Playwright-based web scraper with Tesseract OCR for CAPTCHA solving and fiscal book PDF downloads.
  - **`zeep_client.py`**: Optional enhanced SOAP client wrapper (fallback to manual SOAP if zeep unavailable).
  - **`logger.py`**: Thread-safe logging to both file (`robo_log.txt`) and GUI queue for real-time display.

## 2. Key Developer Workflows

### Running the Application
```bash
python RoboFiscalIntegrado/interface_principal.py
```

### Testing
Run unit tests with pytest from the root directory:
```bash
python -m pytest tests/
```
The test setup automatically adjusts `sys.path` to import the `RoboFiscalIntegrado` package correctly.

### Dependencies & Setup
Key dependencies (no `requirements.txt` exists yet):
- `tkinter` (usually included with Python)
- `playwright` + browsers (`playwright install`)
- `requests` + `requests-pkcs12` (certificate authentication)
- `pytesseract` + Tesseract OCR system dependency
- `Pillow`, `python-dotenv`, `pyOpenSSL`, `lxml`
- Optional: `zeep` (enhanced SOAP client), `pytest` (testing)

**Critical Setup Steps:**
1. **Playwright Browsers**: Use the "Configurações" tab button or run `playwright install`
2. **Tesseract OCR**: Install system binary; path hardcoded in `portal_livros_taubate.py` (may need OS-specific adjustment)
3. **Environment Variables**: `portal_livros_taubate.py` supports `.env` file for CRC credentials and login URL overrides

## 3. Important Coding Patterns & Conventions

- **UI and Logic Separation**: The UI code in `interface_principal.py` is responsible for gathering user input and displaying results. It delegates all heavy lifting (API calls, web scraping) to the functions in the `modulos/` directory.
- **Threading for Responsiveness**: Long-running tasks like capturing notes or downloading books are executed in separate threads (`threading.Thread`) to avoid blocking the Tkinter main loop. See the `iniciar_thread` method in `interface_principal.py`.
- **Configuration Management**: Sensitive data (like passwords) and paths are managed through `gestor_config.py` and `app_settings.json`. When adding a new global setting, update `gestor_config.py` to include the new key and a default value.
- **Client Data**: All client-specific information (CNPJ, CCM, certificate paths) is managed via `gestor_db.py`. Any changes to the client data structure should be handled there, including database migrations if necessary (see `_migration_add_municipio` for an example).
- **Municipality Extensibility**: Use `municipios.py` for adding new municipalities. The `get_model_for_municipio()` function maps normalized municipality names to integration strategies, supporting future expansion beyond Taubaté.
- **Certificate Handling**: The application supports both a global default certificate (from `app_settings.json`) and a client-specific certificate (from `clientes.db`). The logic in `capturador_nf_taubate.py` prioritizes the client-specific certificate if it exists.
- **Optional Dependencies**: `zeep_client.py` demonstrates graceful degradation - if `zeep` is unavailable, the system falls back to manual SOAP implementation.
- **Error Handling**: Errors in the business logic modules are logged using the `logger` module and often re-raised to be caught by the main UI, which then displays a `messagebox` to the user.
