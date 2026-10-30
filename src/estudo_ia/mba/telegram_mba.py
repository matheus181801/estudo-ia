"""Envios do bot do MBA para o grupo com tópicos (um tópico por matéria).

No Telegram, cada tópico de um grupo tem um número (message_thread_id).
Enviar uma mensagem com esse número faz ela aparecer dentro do tópico.
O tópico "Geral" já existe em todo grupo com tópicos e não precisa de número.
"""

import asyncio
from pathlib import Path

from telegram import Bot
from telegram.request import HTTPXRequest

from estudo_ia.config import Config
from estudo_ia.entrega.telegram import LIMITE_MB, TEMPOS
from estudo_ia.mba.aulas import MATERIA_GERAL


def _bot(config: Config) -> Bot:
    if not config.telegram_bot_token_mba or not config.telegram_grupo_mba_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN_MBA ou TELEGRAM_GRUPO_MBA_ID vazio no .env.")
    return Bot(config.telegram_bot_token_mba, request=HTTPXRequest(write_timeout=300, read_timeout=120))


def criar_topico(config: Config, nome: str) -> int | None:
    """Cria o tópico da matéria e devolve o número dele (None para "Geral")."""
    if nome == MATERIA_GERAL:
        return None

    async def _criar():
        async with _bot(config) as bot:
            topico = await bot.create_forum_topic(config.telegram_grupo_mba_id, nome[:128])
            return topico.message_thread_id
    return asyncio.run(_criar())


def enviar_no_topico(config: Config, topico_id: int | None, texto: str,
                     arquivos: list[tuple[Path, str]] = ()) -> list[str]:
    """Manda um texto e arquivos (PDF, MP3, MP4) no tópico. Devolve avisos do que não foi."""
    avisos = []

    async def _enviar():
        async with _bot(config) as bot:
            destino = {"chat_id": config.telegram_grupo_mba_id, "message_thread_id": topico_id}
            await bot.send_message(text=texto, **destino)
            for caminho, legenda in arquivos:
                if not caminho or not Path(caminho).exists():
                    avisos.append(f"{legenda}: arquivo não gerado.")
                    continue
                caminho = Path(caminho)
                if caminho.stat().st_size / 1024 / 1024 >= LIMITE_MB:
                    avisos.append(f"{caminho.name} passa de {LIMITE_MB} MB.")
                    continue
                with open(caminho, "rb") as f:
                    if caminho.suffix == ".mp3":
                        await bot.send_audio(audio=f, caption=legenda, title=legenda,
                                             filename=caminho.name, **destino, **TEMPOS)
                    elif caminho.suffix == ".mp4":
                        await bot.send_video(video=f, caption=legenda, supports_streaming=True,
                                             filename=caminho.name, **destino, **TEMPOS)
                    else:
                        await bot.send_document(document=f, caption=legenda, filename=caminho.name,
                                                **destino, **TEMPOS)
    asyncio.run(_enviar())
    return avisos
