#--------------------------------------------------------------------------
# modulos/capturador_nf_taubate.py - v12.0 A LÓGICA CORRETA
# Usa uma sessão de requests 100% limpa e separada para baixar o PDF,
# exatamente como no script de referência que já funcionava.
#--------------------------------------------------------------------------
import os
import re
import sys
import time
import html
from pathlib import Path
import requests
from lxml import etree
from typing import Dict, List, Optional
from datetime import date
from modulos.logger import log_info, log_error
from urllib.parse import urljoin

try:
    from requests_pkcs12 import Pkcs12Adapter
except ImportError:
    Pkcs12Adapter = None

ABRASF_NS  = "http://www.abrasf.org.br/nfse.xsd"
SOAP_NS    = "http://schemas.xmlsoap.org/soap/envelope/"
TNAMESPACE = "https://abrasftaubate.meumunicipio.online/ws/nfs"
ENDPOINT   = "https://abrasftaubate.meumunicipio.online/ws/nfs"

class CapturadorTaubate:
    def __init__(self, cliente_info: Dict, config_geral: Dict):
        if Pkcs12Adapter is None:
            raise ImportError("A biblioteca 'requests-pkcs12' é necessária.")
        self.cnpj = cliente_info['cnpj']
        self.im = cliente_info['ccm']
        self.pfx_path = cliente_info.get('pfx_path') or config_geral.get('pfx_padrao_path')
        self.pfx_pwd = cliente_info.get('pfx_pwd') or config_geral.get('pfx_padrao_pwd')
        self.timeout = 90
        # Sessão exclusiva para as chamadas SOAP com certificado
        self.soap_session = requests.Session()
        if self.pfx_path and self.pfx_pwd:
            try:
                adapter = Pkcs12Adapter(pkcs12_filename=self.pfx_path, pkcs12_password=self.pfx_pwd.encode('utf-8'))
                self.soap_session.mount(ENDPOINT, adapter)
            except Exception as e:
                raise Exception(f"Falha ao carregar o certificado PFX '{self.pfx_path}': {e}")
        self.headers = {"Content-Type": "text/xml; charset=utf-8"}

    def _build_soap_envelope(self, operation: str, body_xml: str) -> str:
        cabec_msg = f'<cabecalho versao="2.04" xmlns="{ABRASF_NS}"><versaoDados>2.04</versaoDados></cabecalho>'
        soap_body = f'<tns:{operation}Request xmlns:tns="{TNAMESPACE}"><tns:nfseCabecMsg><![CDATA[{cabec_msg}]]></tns:nfseCabecMsg><tns:nfseDadosMsg><![CDATA[{body_xml}]]></tns:nfseDadosMsg></tns:{operation}Request>'
        return f'<soapenv:Envelope xmlns:soapenv="{SOAP_NS}"><soapenv:Body>{soap_body}</soapenv:Body></soapenv:Envelope>'

    def _send_request(self, operation: str, body_xml: str) -> str:
        self.headers["SOAPAction"] = f"nfs#{operation}"
        envelope = self._build_soap_envelope(operation, body_xml)
        response = self.soap_session.post(ENDPOINT, data=envelope.encode('utf-8'), headers=self.headers, timeout=self.timeout)
        response.raise_for_status()
        return response.text

    def consultar_prestados_periodo(self, data_inicio: date, data_fim: date, pagina: int = 1) -> str:
        di, df = data_inicio.isoformat(), data_fim.isoformat()
        body_xml = f'<ConsultarNfseServicoPrestadoEnvio xmlns="{ABRASF_NS}"><Prestador><CpfCnpj><Cnpj>{self.cnpj}</Cnpj></CpfCnpj><InscricaoMunicipal>{self.im}</InscricaoMunicipal></Prestador><PeriodoEmissao><DataInicial>{di}</DataInicial><DataFinal>{df}</DataFinal></PeriodoEmissao><Pagina>{pagina}</Pagina></ConsultarNfseServicoPrestadoEnvio>'
        return self._send_request("ConsultarNfseServicoPrestado", body_xml)

    def consultar_tomados_periodo(self, data_inicio: date, data_fim: date, pagina: int = 1) -> str:
        di, df = data_inicio.isoformat(), data_fim.isoformat()
        inscricao_tag = f"<InscricaoMunicipal>{self.im}</InscricaoMunicipal>" if self.im else ""
        body_xml = f'<ConsultarNfseServicoTomadoEnvio xmlns="{ABRASF_NS}"><Consulente><CpfCnpj><Cnpj>{self.cnpj}</Cnpj></CpfCnpj>{inscricao_tag}</Consulente><PeriodoEmissao><DataInicial>{di}</DataInicial><DataFinal>{df}</DataFinal></PeriodoEmissao><Pagina>{pagina}</Pagina></ConsultarNfseServicoTomadoEnvio>'
        return self._send_request("ConsultarNfseServicoTomado", body_xml)

def _parse_response_tolerant(xml_content: str) -> Optional[etree._Element]:
    try:
        root = etree.fromstring(xml_content.encode('utf-8'))
        output_xml = root.xpath('//outputXML/text()')
        if output_xml:
            unescaped = html.unescape(output_xml[0])
            clean = re.sub(r'^\s*<\?xml[^>]*\?>', '', unescaped).strip()
            parser = etree.XMLParser(recover=True, encoding='utf-8')
            return etree.fromstring(clean.encode('utf-8'), parser=parser)
    except Exception:
        pass
    return None

def _get_nodes_and_messages(xml_content: str):
    nodes, messages = [], []
    inner_root = _parse_response_tolerant(xml_content)
    if inner_root is not None:
        ns = {'ns': ABRASF_NS}
        nodes = inner_root.xpath('//ns:CompNfse', namespaces=ns)
        for msg_node in inner_root.xpath('//ns:MensagemRetorno', namespaces=ns):
            code = msg_node.findtext('ns:Codigo', namespaces=ns)
            msg = msg_node.findtext('ns:Mensagem', namespaces=ns)
            messages.append(f"({code}) {msg}")
    return nodes, messages

def _sanitize_path_component(name: Optional[str]) -> str:
    if not name: return ""
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]+', '_', name).strip()

def baixar_pdf_nota(url_visualizacao: str, caminho_pdf: Path):
    try:
        id_match = re.search(r'id=(\d+)', url_visualizacao)
        if not id_match:
            log_error(f"Não foi possível extrair o ID da nota da URL: {url_visualizacao}")
            return
        id_nota = id_match.group(1)
        url_corrigida = f"https://taubateiss.meumunicipio.digital/taubateiss/contribuinte/nfe/nfe_ver.php?id={id_nota}"
        
        # Nova lógica: Primeiro verifica se a URL já retorna PDF diretamente
        with requests.Session() as session:
            log_info(f"Acessando página de visualização com URL reconstruída: {url_corrigida}")
            view_page_resp = session.get(url_corrigida, timeout=60)
            view_page_resp.raise_for_status()
            
            # Verifica se a resposta já é um PDF
            content_type = view_page_resp.headers.get('content-type', '').lower()
            if 'application/pdf' in content_type and view_page_resp.content.startswith(b'%PDF'):
                log_info(f"URL já retorna PDF diretamente. Salvando...")
                with open(caminho_pdf, 'wb') as f:
                    f.write(view_page_resp.content)
                log_info(f"PDF salvo com sucesso em: {caminho_pdf}")
                return
            
            # Caso contrário, procura pelo link de impressão na página HTML
            pdf_link_match = re.search(r'href=["\'](nfe_imp\.php[^"\']+)["\']', view_page_resp.text)
            if not pdf_link_match:
                log_error(f"Não foi possível encontrar o link de impressão na página: {url_corrigida}")
                return

            pdf_url = urljoin(url_corrigida, html.unescape(pdf_link_match.group(1)))
            log_info(f"Link de PDF encontrado. Baixando de: {pdf_url}")

            pdf_resp = session.get(pdf_url, timeout=60)
            pdf_resp.raise_for_status()

            if pdf_resp.content.startswith(b'%PDF'):
                with open(caminho_pdf, 'wb') as f:
                    f.write(pdf_resp.content)
                log_info(f"PDF salvo com sucesso em: {caminho_pdf}")
            else:
                log_error(f"O link de impressão não retornou um PDF. URL: {pdf_url}")

    except Exception as e:
        log_error(f"Falha crítica ao baixar PDF da nota. URL: {url_visualizacao} | Erro: {e}")

def _processar_captura(capturador: CapturadorTaubate, tipo_nota: str, data_inicio: date, data_fim: date, pasta_saida_base: str, id_cliente: str, cliente_info: Dict):
    log_info(f"--- Iniciando captura de notas {tipo_nota} para ID {id_cliente} ---")
    pagina, notas_salvas = 1, 0
    razao_social = _sanitize_path_component(cliente_info.get('razao_social', ''))
    pasta_destino = Path(pasta_saida_base) / f"{id_cliente}-{razao_social}"
    ns_map = {'ns': ABRASF_NS}
    capturador_func = capturador.consultar_prestados_periodo if tipo_nota == "prestadas" else capturador.consultar_tomados_periodo
    
    while True:
        log_info(f"Buscando página {pagina} de notas {tipo_nota}...")
        try:
            xml_resposta = capturador_func(data_inicio, data_fim, pagina)
            nodes, messages = _get_nodes_and_messages(xml_resposta)

            if messages and any("E016" in m for m in messages):
                log_info(f"Nenhuma nota {tipo_nota} nova encontrada para o ID {id_cliente}.")
                break
            
            if not nodes:
                log_info(f"Fim da busca. Nenhuma nota {tipo_nota} adicional na página {pagina}.")
                break
            
            for node in nodes:
                num_nf = node.findtext('.//ns:Numero', namespaces=ns_map)
                data_emissao = node.findtext('.//ns:DataEmissao', namespaces=ns_map)
                link_visualizacao = node.findtext('.//ns:LinkNota', namespaces=ns_map)

                if num_nf and data_emissao:
                    prefixo = "PRESTADA" if tipo_nota == "prestadas" else "TOMADA"
                    nome_base = f"NF_{prefixo}_{num_nf}_{data_emissao.split('T')[0]}"
                    pasta_destino.mkdir(parents=True, exist_ok=True)
                    
                    caminho_xml = pasta_destino / f"{nome_base}.xml"
                    xml_content = etree.tostring(node, pretty_print=True, encoding='utf-8', xml_declaration=True)
                    with open(caminho_xml, 'wb') as f: f.write(xml_content)
                    
                    if link_visualizacao:
                        caminho_pdf = pasta_destino / f"{nome_base}.pdf"
                        # Chamada corrigida para não passar a sessão
                        baixar_pdf_nota(link_visualizacao, caminho_pdf)

                    notas_salvas += 1
            
            if len(nodes) < 50: break
            pagina += 1
            time.sleep(1)

        except requests.exceptions.HTTPError as e:
            log_error(f"Erro de servidor ao buscar notas {tipo_nota} para ID {id_cliente}: {e}")
            break
        except Exception as e:
            log_error(f"Erro inesperado no processamento de {tipo_nota} para ID {id_cliente}: {e}", exc_info=sys.exc_info())
            break
            
    log_info(f"--- Captura de {tipo_nota} finalizada para ID {id_cliente}. Total salvo: {notas_salvas} ---")

def capturar_notas(cliente_info: Dict, config_geral: Dict, data_inicio: date, data_fim: date, pasta_saida: str):
    try:
        capturador = CapturadorTaubate(cliente_info, config_geral)
        _processar_captura(capturador, "prestadas", data_inicio, data_fim, pasta_saida, cliente_info['id'], cliente_info)
    except Exception as e:
        log_error(f"Erro CRÍTICO ao configurar captura de PRESTADAS para ID {cliente_info['id']}: {e}", exc_info=sys.exc_info())
        
def capturar_notas_tomadas(cliente_info: Dict, config_geral: Dict, data_inicio: date, data_fim: date, pasta_saida: str):
    try:
        capturador = CapturadorTaubate(cliente_info, config_geral)
        _processar_captura(capturador, "tomadas", data_inicio, data_fim, pasta_saida, cliente_info['id'], cliente_info)
    except Exception as e:
        log_error(f"Erro CRÍTICO ao configurar captura de TOMADAS para ID {cliente_info['id']}: {e}", exc_info=sys.exc_info())