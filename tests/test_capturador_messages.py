import os
import sys

# Ensure the package can be imported from the workspace
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
# Insert the RoboFiscalIntegrado package folder first so internal imports like 'modulos.logger' resolve
RP = os.path.join(ROOT, 'RoboFiscalIntegrado')
sys.path.insert(0, RP)
if not os.path.isdir(RP):
    raise RuntimeError(f"RoboFiscalIntegrado package path not found: {RP}")

from modulos import capturador_nf_taubate as cap


def test_extrair_mensagens_retorno_e_sem_notas():
    sample_response = '''<?xml version="1.0" encoding="UTF-8"?>
    <SOAP-ENV:Envelope xmlns:SOAP-ENV="http://schemas.xmlsoap.org/soap/envelope/">
      <SOAP-ENV:Body>
        <ns1:ConsultarNfseServicoTomadoResponse xmlns:ns1="https://abrasftaubate.meumunicipio.online/ws/nfs">
          <outputXML>&lt;ListaMensagemRetorno&gt;&lt;MensagemRetorno&gt;&lt;Codigo&gt;E160&lt;/Codigo&gt;&lt;Mensagem&gt;Arquivo em desacordo com o XML Schema.&lt;/Mensagem&gt;&lt;Correcao&gt;Consulte o Manual da NFS-e.&lt;/Correcao&gt;&lt;/MensagemRetorno&gt;&lt;/ListaMensagemRetorno&gt;</outputXML>
        </ns1:ConsultarNfseServicoTomadoResponse>
      </SOAP-ENV:Body>
    </SOAP-ENV:Envelope>'''

    msgs = cap.extrair_mensagens_retorno(sample_response)
    assert isinstance(msgs, list)
    assert len(msgs) == 1
    assert msgs[0].get('codigo') == 'E160'

    nodes = cap.extrair_nfse_nodes(sample_response)
    assert nodes == []
