"""Caminho principal do podcast: Audio Overview do NotebookLM.

ATENÇÃO: usamos a biblioteca notebooklm-py, que NÃO é oficial. Ela conversa
com APIs internas do Google, que podem mudar sem aviso. Por isso este
caminho sempre tem um plano B (o fallback com Gemini TTS, em tts.py).

O login é feito uma vez no notebook com
`python -m notebooklm --profile estudo login --browser chrome`, e a sessão
fica salva em ~/.notebooklm/profiles/estudo (ou na pasta de NOTEBOOKLM_HOME).
Usamos o Chrome de verdade porque o Chromium embutido salvava a sessão sem
um cookie obrigatório do Google (__Secure-1PSIDTS).
"""

import asyncio
import os
from datetime import date
from pathlib import Path

from notebooklm import AudioFormat, AudioLength, NotebookLMClient

from estudo_ia.pacote.modelos import Pacote

INSTRUCOES = """Podcast em português do Brasil para o Matheus, que faz um MBA em AI Leadership
e está em transição de carreira para tecnologia. Tom descontraído, divertido e didático,
com analogias do dia a dia. Explique os conceitos e dê exemplos práticos de uso no trabalho.
Duração ideal: cerca de 20 minutos."""

# Aulas do MBA: o podcast é um complemento da aula, então curto e objetivo.
INSTRUCOES_AULA = """Podcast CURTO e objetivo em português do Brasil para o Matheus, que faz um MBA em
AI Leadership e não é da área de tecnologia. É um complemento da aula, não uma aula nova:
revise os conceitos principais, explique do zero os termos técnicos e dê exemplos práticos.
Tom descontraído e didático. Duração ideal: de 8 a 10 minutos."""


def _material(pacote: Pacote) -> str:
    """Fonte do podcast: só material original (notas de estudo e newsletter)."""
    c = pacote.conteudo
    secoes = "\n\n".join(f"## {s.titulo}\n{s.texto}\nAnalogia: {s.analogia}" for s in c.secoes)
    referencia = (f"Aula de {pacote.livro} (Prof. {pacote.autor})" if pacote.tipo == "aula"
                  else f"Livro de referência: {pacote.livro}, de {pacote.autor}")
    return (
        f"# {c.titulo}\n{referencia}\n\n"
        f"{pacote.midia.fonte_podcast}\n\n# Resumo da newsletter\n{secoes}\n\n"
        f"Na prática: {c.na_pratica}\nCuriosidade: {c.curiosidade}"
    )


async def _gerar(pacote: Pacote, destino: Path, limite_min: float, perfil: str) -> Path:
    # Na VPS a sessão vem da variável NOTEBOOKLM_AUTH_JSON (conteúdo do
    # storage_state.json); um perfil explícito teria prioridade sobre ela.
    perfil_usado = None if os.environ.get("NOTEBOOKLM_AUTH_JSON") else perfil
    async with NotebookLMClient.from_storage(profile=perfil_usado) as cliente:
        caderno = await cliente.notebooks.create(f"Estudo IA — {date.today().isoformat()}")
        try:
            await cliente.sources.add_text(caderno.id, pacote.conteudo.titulo, _material(pacote), wait=True)
            aula = pacote.tipo == "aula"
            status = await cliente.artifacts.generate_audio(
                caderno.id,
                language="pt-BR",
                instructions=INSTRUCOES_AULA if aula else INSTRUCOES,
                audio_format=AudioFormat.DEEP_DIVE,
                audio_length=AudioLength.SHORT if aula else AudioLength.DEFAULT,
            )
            # A geração costuma levar de 5 a 15 minutos.
            await cliente.artifacts.wait_for_completion(
                caderno.id, status.task_id, max_interval=30.0, timeout=limite_min * 60
            )
            return Path(await cliente.artifacts.download_audio(caderno.id, str(destino)))
        finally:
            # O caderno do dia não precisa ficar guardado no NotebookLM.
            await cliente.notebooks.delete(caderno.id)


def gerar_audio_notebooklm(pacote: Pacote, destino: Path, perfil: str = "estudo",
                           limite_min: float = 30) -> Path:
    """Gera o Audio Overview e baixa o arquivo (formato do Google, ex.: .m4a)."""
    return asyncio.run(_gerar(pacote, destino, limite_min, perfil))
