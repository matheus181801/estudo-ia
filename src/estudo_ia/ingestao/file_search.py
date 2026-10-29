"""Integração com o Gemini File Search (o "R" do RAG).

Como funciona:
1. Criamos um *store* (um repositório de documentos) no Gemini.
2. Enviamos cada capítulo como um arquivo de texto. O Gemini corta o texto
   em pedaços (chunks), transforma cada pedaço num vetor de números
   (embedding) e guarda esses vetores.
3. Na hora da pergunta, o Gemini busca os pedaços mais parecidos com a
   pergunta (busca semântica) e responde usando esses pedaços como fonte.

Cada capítulo vai com metadados (livro, autor, capítulo), e é isso que
permite a resposta citar a fonte.
"""

import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from google import genai
from google.genai import types
from sqlmodel import select

from estudo_ia.config import Config
from estudo_ia.db import Capitulo, Livro, abrir_sessao

NOME_STORE = "estudo-ia-biblioteca"

INSTRUCOES_RESPOSTA = """Você é um tutor de estudos. Responda sempre em português do Brasil,
de forma clara e didática, usando os trechos dos livros encontrados pela busca.
Termos técnicos ficam em inglês, com a explicação em português ao lado.
Ao final, liste as fontes no formato: Livro — Capítulo.
Se citar o livro literalmente, use no máximo duas frases, entre aspas.
Se os livros não tiverem a resposta, diga isso claramente em vez de inventar."""


def criar_cliente(config: Config) -> genai.Client:
    if not config.gemini_api_key:
        raise RuntimeError("GEMINI_API_KEY está vazia no .env.")
    # Sem isso, a biblioteca insiste por vários minutos quando o modelo está
    # sobrecarregado. Preferimos desistir em ~1 minuto e tentar o modelo reserva.
    opcoes = types.HttpOptions(timeout=60_000, retry_options=types.HttpRetryOptions(attempts=2))
    return genai.Client(api_key=config.gemini_api_key, http_options=opcoes)


def obter_store(cliente: genai.Client, config: Config) -> str:
    """Procura o store do projeto pelo nome; cria se ainda não existir."""
    for store in cliente.file_search_stores.list():
        if store.display_name == NOME_STORE:
            return store.name
    novo = cliente.file_search_stores.create(
        config={"display_name": NOME_STORE, "embedding_model": config.gemini_modelo_embedding}
    )
    return novo.name


def _esperar(cliente: genai.Client, operacao, limite_s: int = 600):
    """O envio é assíncrono: o Gemini devolve uma 'operação' que vamos consultando."""
    inicio = time.time()
    while not operacao.done:
        if time.time() - inicio > limite_s:
            raise TimeoutError("O Gemini demorou demais para indexar o documento.")
        time.sleep(3)
        operacao = cliente.operations.get(operacao)
    if operacao.error:
        raise RuntimeError(f"Falha na indexação: {operacao.error}")
    return operacao


def enviar_pendentes(cliente: genai.Client, store: str, engine, avisar=print, lote: int = 8,
                     limite: int | None = None) -> int:
    """Envia ao File Search os capítulos que ainda não foram enviados.

    Manda até `lote` capítulos de uma vez e espera todos indexarem. Se cair
    no meio, basta rodar de novo: continua de onde parou.
    """
    enviados = 0
    with abrir_sessao(engine) as s:
        pendentes = s.exec(
            select(Capitulo, Livro)
            .join(Livro)
            .where(Capitulo.file_search_doc == None)  # noqa: E711 (sintaxe do SQLModel)
            .order_by(Livro.titulo, Capitulo.ordem)
        ).all()[:limite]  # limite=None envia todos
        if pendentes:
            avisar(f"Enviando {len(pendentes)} capítulos ao Gemini File Search...")

        with tempfile.TemporaryDirectory() as pasta_tmp:
            for i in range(0, len(pendentes), lote):
                grupo = pendentes[i : i + lote]
                operacoes = []
                for cap, livro in grupo:
                    arquivo = Path(pasta_tmp) / f"cap_{cap.id}.txt"
                    # O cabeçalho ajuda o modelo a saber de onde vem o trecho.
                    arquivo.write_text(
                        f"Livro: {livro.titulo}\nAutor: {livro.autor}\n"
                        f"Capítulo {cap.ordem}: {cap.titulo}\n\n{cap.texto}",
                        encoding="utf-8",
                    )
                    op = cliente.file_search_stores.upload_to_file_search_store(
                        file_search_store_name=store,
                        file=str(arquivo),
                        config={
                            "display_name": f"{livro.titulo} — Cap. {cap.ordem}: {cap.titulo}"[:500],
                            "mime_type": "text/plain",
                            "custom_metadata": [
                                {"key": "livro", "string_value": livro.titulo[:250]},
                                {"key": "autor", "string_value": livro.autor[:250]},
                                {"key": "capitulo", "string_value": f"{cap.ordem}. {cap.titulo}"[:250]},
                                {"key": "livro_id", "numeric_value": livro.id},
                            ],
                        },
                    )
                    operacoes.append((cap, op))

                for cap, op in operacoes:
                    pronta = _esperar(cliente, op)
                    nome_doc = getattr(pronta.response, "document_name", None) or "enviado"
                    cap.file_search_doc = nome_doc
                    s.add(cap)
                    enviados += 1
                s.commit()
                avisar(f"  {enviados}/{len(pendentes)} capítulos indexados")
    return enviados


@dataclass
class Resposta:
    texto: str
    fontes: list[str]


def perguntar(cliente: genai.Client, store: str, config: Config, pergunta: str,
              livro_id: int | None = None) -> Resposta:
    """Faz uma pergunta usando os livros como fonte (RAG)."""
    busca = types.FileSearch(file_search_store_names=[store])
    if livro_id is not None:
        busca.metadata_filter = f"livro_id={livro_id}"

    configuracao = types.GenerateContentConfig(
        system_instruction=INSTRUCOES_RESPOSTA,
        tools=[types.Tool(file_search=busca)],
    )
    # Tenta o modelo principal; se falhar (sobrecarga, tempo esgotado), usa o reserva.
    try:
        resposta = cliente.models.generate_content(
            model=config.gemini_modelo_texto, contents=pergunta, config=configuracao
        )
    except Exception:
        resposta = cliente.models.generate_content(
            model=config.gemini_modelo_reserva, contents=pergunta, config=configuracao
        )

    # As fontes vêm nos metadados de "grounding" (aterramento) da resposta.
    fontes = []
    candidato = resposta.candidates[0] if resposta.candidates else None
    grounding = candidato.grounding_metadata if candidato else None
    for chunk in (grounding.grounding_chunks or []) if grounding else []:
        ctx = chunk.retrieved_context
        if not ctx:
            continue
        meta = {m.key: m.string_value for m in (ctx.custom_metadata or []) if m.string_value}
        fonte = f"{meta['livro']} — Cap. {meta['capitulo']}" if "livro" in meta else (ctx.title or "")
        if fonte and fonte not in fontes:
            fontes.append(fonte)

    return Resposta(texto=resposta.text or "", fontes=fontes)
