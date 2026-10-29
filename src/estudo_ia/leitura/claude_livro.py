"""Perguntas sobre o livro da trilha, respondidas pelo Claude lendo o livro inteiro.

Diferente do RAG (que busca pedaços), aqui mandamos todos os capítulos do
livro na mesma chamada, cada um como um "documento" com o título do capítulo.

Não ligamos as citações automáticas da API: com elas, o modelo tende a
copiar trechos literais do livro, e nossa regra de direitos autorais pede
explicações originais (citação literal só de até duas frases, entre aspas).
Em vez disso, pedimos que ele indique os capítulos usados no final.

Para não pagar o livro inteiro a cada pergunta, usamos *prompt caching*:
o Claude guarda o livro por alguns minutos e as perguntas seguintes leem
do cache, que custa cerca de 10% do preço normal.
"""

from dataclasses import dataclass

import anthropic
from sqlmodel import select

from estudo_ia.config import Config
from estudo_ia.db import Capitulo, Livro, abrir_sessao

INSTRUCOES = """Você é um tutor de estudos. Responda sempre em português do Brasil,
de forma clara e didática, usando apenas o livro fornecido nos documentos.
Explique com as suas próprias palavras: não copie trechos do livro.
Se uma citação literal for realmente importante, use no máximo duas frases, entre aspas.
Termos técnicos ficam em inglês, com a explicação em português ao lado.
Termine com uma linha "Fontes:" listando os capítulos usados, exatamente como no título
dos documentos (ex.: "Fontes: Cap. 4: Quatro regras para a cointeligência").
Se o livro não tiver a resposta, diga isso claramente em vez de inventar."""


@dataclass
class RespostaClaude:
    texto: str
    recusou: bool = False


def criar_cliente(config: Config) -> anthropic.Anthropic:
    if not config.anthropic_api_key:
        raise RuntimeError("ANTHROPIC_API_KEY está vazia no .env.")
    # Desiste em 2 minutos (com 1 nova tentativa) para o bot não ficar travado.
    return anthropic.Anthropic(api_key=config.anthropic_api_key, timeout=120.0, max_retries=1)


def montar_documentos(livro: Livro, capitulos: list[Capitulo]) -> list[dict]:
    """Um bloco 'document' por capítulo, com o título do capítulo."""
    documentos = [
        {
            "type": "document",
            "source": {"type": "text", "media_type": "text/plain", "data": cap.texto},
            "title": f"Cap. {cap.ordem}: {cap.titulo}",
            "context": f"Livro: {livro.titulo}, de {livro.autor}",
        }
        for cap in capitulos
    ]
    # O cache guarda tudo até este ponto (o livro inteiro). Como o livro vem
    # antes da pergunta, perguntas diferentes reaproveitam o mesmo cache.
    documentos[-1]["cache_control"] = {"type": "ephemeral"}
    return documentos


def perguntar_livro(cliente: anthropic.Anthropic, config: Config, engine, livro_id: int,
                    pergunta: str) -> RespostaClaude:
    with abrir_sessao(engine) as s:
        livro = s.get(Livro, livro_id)
        capitulos = list(s.exec(
            select(Capitulo).where(Capitulo.livro_id == livro_id).order_by(Capitulo.ordem)
        ).all())

    resposta = cliente.messages.create(
        model=config.claude_modelo,
        max_tokens=4000,
        system=INSTRUCOES,
        output_config={"effort": "low"},  # perguntas de estudo não precisam de raciocínio longo
        messages=[{
            "role": "user",
            "content": montar_documentos(livro, capitulos) + [{"type": "text", "text": pergunta}],
        }],
    )

    if resposta.stop_reason == "refusal":
        return RespostaClaude(texto="", recusou=True)

    texto = "".join(b.text for b in resposta.content if b.type == "text").strip()
    return RespostaClaude(texto=f"{texto}\n\n📖 {livro.titulo}")
