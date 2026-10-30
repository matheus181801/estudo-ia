"""Pesquisa na web sobre os conceitos da sessão.

O livro é o ponto de partida, mas o Matheus quer entender os conceitos em
si (ex.: human-in-the-loop) e não só "o que o autor disse". Aqui o Claude
usa a ferramenta de busca na web da própria API (roda nos servidores da
Anthropic, não precisamos programar a busca) para aprofundar os conceitos.

As fontes (título e URL) vêm dos resultados reais da busca, nunca do texto
do modelo: assim não corremos o risco de um link inventado.
"""

from dataclasses import dataclass, field

import anthropic

from estudo_ia.config import Config
from estudo_ia.db import Livro
from estudo_ia.pacote.modelos import FonteWeb

MAX_BUSCAS = 5  # cada busca custa cerca de US$ 0,01

PEDIDO_PESQUISA = """Leia o trecho do livro acima e identifique os 3 conceitos centrais da sessão.
Depois pesquise na web para aprofundar cada conceito além do livro: definições de outras fontes,
exemplos reais e recentes (empresas, produtos, casos), números, debates e críticas.
Prefira fontes confiáveis: artigos acadêmicos, documentação oficial, institutos de pesquisa e
veículos de tecnologia reconhecidos.

Escreva notas de pesquisa em português do Brasil, com as suas palavras (não copie trechos),
organizadas por conceito: o que a web acrescenta ao que o livro diz."""


@dataclass
class ResultadoPesquisa:
    notas: str
    fontes: list[FonteWeb] = field(default_factory=list)


def pesquisar_conceitos(cliente: anthropic.Anthropic, config: Config, livro: Livro,
                        texto: str) -> ResultadoPesquisa:
    mensagens = [{
        "role": "user",
        "content": [
            {
                "type": "document",
                "source": {"type": "text", "media_type": "text/plain", "data": texto},
                "title": f"{livro.titulo} — {livro.autor}",
            },
            {"type": "text", "text": PEDIDO_PESQUISA},
        ],
    }]
    ferramentas = [{"type": "web_search_20260209", "name": "web_search", "max_uses": MAX_BUSCAS}]

    # Em pesquisas longas, a API pode "pausar" a resposta (pause_turn). Para
    # continuar, devolvemos o que veio até ali e pedimos o resto.
    blocos = []
    for _ in range(3):
        with cliente.messages.stream(
            model=config.claude_modelo, max_tokens=32000, tools=ferramentas, messages=mensagens,
        ) as stream:
            resposta = stream.get_final_message()
        blocos += resposta.content
        if resposta.stop_reason != "pause_turn":
            break
        mensagens = mensagens + [{"role": "assistant", "content": resposta.content}]

    notas, fontes, vistas = [], [], set()

    def guardar(titulo: str, url: str):
        if url and url not in vistas:
            vistas.add(url)
            fontes.append(FonteWeb(titulo=titulo or url, url=url))

    # 1º: as fontes que o modelo realmente citou nas notas; 2º: os demais resultados.
    for bloco in blocos:
        if bloco.type == "text":
            notas.append(bloco.text)
            for citacao in bloco.citations or []:
                guardar(getattr(citacao, "title", ""), getattr(citacao, "url", ""))
    for bloco in blocos:
        if bloco.type == "web_search_tool_result" and isinstance(bloco.content, list):
            for resultado in bloco.content:
                guardar(resultado.title, resultado.url)

    return ResultadoPesquisa(notas="".join(notas).strip(), fontes=fontes[:8])
