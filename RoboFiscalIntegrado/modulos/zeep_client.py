"""Helper to create a zeep Client with optional requests_pkcs12 Transport."""
from typing import Optional
try:
    from zeep import Client, Settings
    from zeep.transports import Transport
except Exception:
    Client = None
    Settings = None
    Transport = None

import requests
try:
    from requests_pkcs12 import Pkcs12Adapter
except Exception:
    Pkcs12Adapter = None

def make_zeep_client(wsdl_path: str, pfx_path: Optional[str]=None, pfx_password: Optional[str]=None, timeout: int=60):
    if Client is None:
        return None

    session = requests.Session()
    if pfx_path and pfx_password and Pkcs12Adapter is not None:
        try:
            session.mount('https://', Pkcs12Adapter(pkcs12_filename=pfx_path, pkcs12_password=pfx_password))
        except Exception:
            pass

    transport = Transport(session=session, timeout=timeout)
    settings = Settings(strict=False, xml_huge_tree=True)
    client = Client(wsdl=wsdl_path, transport=transport, settings=settings)
    return client