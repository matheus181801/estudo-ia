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
from datetime import date
from pathlib import Path

from notebooklm import AudioFormat, AudioLength, NotebookLMClient

from estudo_ia.pacote.modelos import Pacote

INSTRUCOES = """Podcast em português do Brasil para o Matheus, que faz um MBA em AI Leadership
e está em transição de carreira para tecnologia. Tom descontraído, divertido e didático,
com analogias do dia a dia. Explique os conceitos e dê exemplos práticos de uso no trabalho.
Duração ideal: cerca de 20 minutos."""


def _material(pacote: Pacote) -> str:
    """Fonte do podcast: só material original (notas de estudo e newsletter)."""
    c = pacote.conteudo
    secoes = "\n\n".join(f"## {s.titulo}\n{s.texto}\nAnalogia: {s.analogia}" for s in c.secoes)
    return (
        f"# {c.titulo}\nLivro de referência: {pacote.livro}, de {pacote.autor}\n\n"
        f"{pacote.midia.fonte_podcast}\n\n# Resumo da newsletter\n{secoes}\n\n"
        f"Na prática: {c.na_pratica}\nCuriosidade: {c.curiosidade}"
    )


async def _gerar(pacote: Pacote, destino: Path, limite_min: float, perfil: str) -> Path:
    async with NotebookLMClient.from_storage(profile=perfil) as cliente:
        caderno = await cliente.notebooks.create(f"Estudo IA — {date.today().isoformat()}")
        try:
            await cliente.sources.add_text(caderno.id, pacote.conteudo.titulo, _material(pacote), wait=True)
            status = await cliente.artifacts.generate_audio(
                caderno.id,
                language="pt-BR",
                instructions=INSTRUCOES,
                audio_format=AudioFormat.DEEP_DIVE,
                audio_length=AudioLength.DEFAULT,
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
