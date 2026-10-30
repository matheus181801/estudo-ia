"""Entrega no Telegram: arquivos do pacote e alertas para o Matheus.

Aqui não precisamos do bot "ouvindo" mensagens: só enviamos. Por isso
usamos o objeto `Bot` do python-telegram-bot diretamente.
"""

import asyncio
from pathlib import Path

from telegram import Bot
from telegram.request import HTTPXRequest

from estudo_ia.config import Config

LIMITE_MB = 50  # bots do Telegram enviam arquivos de até 50 MB
# Os métodos de envio de arquivo da biblioteca usam por padrão só 20 s para
# o upload (e ignoram o que foi configurado no cliente). Um MP3 de 12 MB não
# sobe nesse tempo numa conexão comum, então passamos o limite em cada envio.
TEMPOS = {"write_timeout": 300, "read_timeout": 120, "connect_timeout": 30}


def _bot(config: Config) -> Bot:
    if not config.telegram_bot_token or not config.telegram_chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID vazio no .env.")
    # Envio de arquivo grande demora: tempo limite de escrita generoso.
    return Bot(config.telegram_bot_token, request=HTTPXRequest(write_timeout=300, read_timeout=120))


async def _enviar_arquivos(config: Config, arquivos: list[tuple[Path, str]]) -> list[str]:
    avisos = []
    async with _bot(config) as bot:
        for caminho, legenda in arquivos:
            if not caminho.exists():
                avisos.append(f"{caminho.name} não foi gerado hoje.")
                continue
            megas = caminho.stat().st_size / 1024 / 1024
            if megas >= LIMITE_MB:
                avisos.append(f"{caminho.name} tem {megas:.0f} MB, acima do limite do Telegram.")
                continue
            with open(caminho, "rb") as arquivo:
                if caminho.suffix == ".mp3":
                    await bot.send_audio(config.telegram_chat_id, arquivo, caption=legenda,
                                         title=legenda, filename=caminho.name, **TEMPOS)
                elif caminho.suffix == ".mp4":
                    await bot.send_video(config.telegram_chat_id, arquivo, caption=legenda,
                                         supports_streaming=True, filename=caminho.name, **TEMPOS)
                else:
                    await bot.send_document(config.telegram_chat_id, arquivo, caption=legenda,
                                            filename=caminho.name, **TEMPOS)
    return avisos


def enviar_arquivos(config: Config, arquivos: list[tuple[Path, str]]) -> list[str]:
    """Envia cada (arquivo, legenda). Devolve avisos do que não pôde ser enviado."""
    return asyncio.run(_enviar_arquivos(config, arquivos))


async def _avisar(config: Config, texto: str) -> None:
    async with _bot(config) as bot:
        await bot.send_message(config.telegram_chat_id, texto)


def avisar(config: Config, texto: str) -> None:
    """Mensagem de texto para o Matheus (alertas de falha, avisos do pipeline)."""
    asyncio.run(_avisar(config, texto))
