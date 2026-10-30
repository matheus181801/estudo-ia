"""Cliente da Ponte Drive (o Apps Script em apps_script/ponte_drive.gs).

A VPS não tem acesso direto ao Google Drive. Quem tem é um Apps Script que
roda dentro da conta Google do Matheus e responde a pedidos HTTP protegidos
por uma chave secreta. Este módulo faz esses pedidos.
"""

import base64
from dataclasses import dataclass, field

import requests

TEMPO_LIMITE_S = 120  # o Apps Script pode demorar alguns segundos para "acordar"


@dataclass
class ArquivoDrive:
    id: str
    nome: str
    tipo: str
    tamanho: int


@dataclass
class PastaAula:
    id: str
    nome: str
    criada: str
    arquivos: list[ArquivoDrive] = field(default_factory=list)


class PonteDrive:
    def __init__(self, url: str, chave: str):
        if not url or not chave:
            raise RuntimeError("DRIVE_PONTE_URL ou DRIVE_PONTE_CHAVE vazio no .env.")
        self.url = url
        self.chave = chave

    def _resposta(self, r: requests.Response) -> dict:
        r.raise_for_status()
        dados = r.json()
        if not dados.get("ok"):
            raise RuntimeError(f"Ponte Drive recusou o pedido: {dados.get('erro')}")
        return dados

    def _get(self, **parametros) -> dict:
        # O Apps Script responde com um redirecionamento; o requests segue sozinho.
        r = requests.get(self.url, params={"chave": self.chave, **parametros}, timeout=TEMPO_LIMITE_S)
        return self._resposta(r)

    def ping(self) -> bool:
        return self._get(acao="ping")["ok"]

    def listar_aulas(self) -> list[PastaAula]:
        return [
            PastaAula(id=a["id"], nome=a["nome"], criada=a["criada"],
                      arquivos=[ArquivoDrive(**arq) for arq in a["arquivos"]])
            for a in self._get(acao="listar")["aulas"]
        ]

    def listar_processadas(self) -> dict[str, list[PastaAula]]:
        """O que já existe em "Aprofundamento das Aulas": {matéria: [pastas de aula]}."""
        return {
            m["nome"]: [PastaAula(id=a["id"], nome=a["nome"], criada=a["criada"],
                                  arquivos=[ArquivoDrive(**arq) for arq in a["arquivos"]])
                        for a in m["aulas"]]
            for m in self._get(acao="processadas")["materias"]
        }

    def baixar(self, arquivo_id: str) -> bytes:
        return base64.b64decode(self._get(acao="baixar", id=arquivo_id)["arquivo"]["base64"])

    def salvar(self, caminho: list[str], nome: str, conteudo: bytes, tipo: str) -> str:
        """Salva em "Aprofundamento das Aulas/<caminho...>/<nome>". Devolve o link do arquivo."""
        r = requests.post(self.url, json={
            "chave": self.chave, "acao": "salvar", "caminho": caminho, "nome": nome,
            "tipo": tipo, "base64": base64.b64encode(conteudo).decode(),
        }, timeout=300)
        return self._resposta(r)["arquivo"]["url"]
