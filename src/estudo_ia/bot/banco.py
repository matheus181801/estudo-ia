"""Leva o banco (com o texto dos capítulos) do notebook para a VPS pelo Telegram.

Os livros não vão para o git nem para a VPS (direitos autorais). O que a
VPS precisa é do banco SQLite com os capítulos já extraídos. Fluxo:

1. No notebook: `uv run estudo-ia enviar-banco` → o bot manda o banco
   compactado (.gz) no chat do Matheus.
2. No celular: o Matheus responde a essa mensagem com /importar.
3. O bot da VPS baixa o arquivo e troca o banco, guardando uma cópia do antigo.
"""

import asyncio
import gzip
import shutil
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from telegram import Bot

from estudo_ia.config import Config
from estudo_ia.entrega.telegram import TEMPOS

NOME_ARQUIVO = "estudo-ia-banco.db.gz"
TABELAS_OBRIGATORIAS = {"livro", "capitulo", "sessao", "progresso", "pacote"}


def compactar_banco(origem: Path, destino_gz: Path) -> Path:
    """Copia o banco de forma segura (API de backup do SQLite) e compacta."""
    with tempfile.TemporaryDirectory() as tmp:
        copia = Path(tmp) / "copia.db"
        # closing(): o "with" do sqlite3 sozinho não fecha a conexão, só confirma a transação.
        with closing(sqlite3.connect(origem)) as fonte, closing(sqlite3.connect(copia)) as alvo:
            fonte.backup(alvo)  # cópia consistente mesmo com o banco em uso
        with open(copia, "rb") as entrada, gzip.open(destino_gz, "wb") as saida:
            shutil.copyfileobj(entrada, saida)
    return destino_gz


def validar_banco(caminho: Path) -> None:
    """Confere se o arquivo é mesmo um banco do Estudo IA antes de trocar."""
    try:
        with closing(sqlite3.connect(caminho)) as con:
            tabelas = {linha[0] for linha in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            capitulos = con.execute("SELECT count(*) FROM capitulo").fetchone()[0]
    except sqlite3.DatabaseError as erro:
        raise ValueError(f"o arquivo não é um banco SQLite válido ({erro})") from erro
    faltando = TABELAS_OBRIGATORIAS - tabelas
    if faltando:
        raise ValueError(f"faltam tabelas no banco: {', '.join(sorted(faltando))}")
    if capitulos == 0:
        raise ValueError("o banco não tem capítulos")


def instalar_banco(arquivo_gz: Path, destino: Path) -> Path | None:
    """Descompacta, valida e troca o banco. Devolve o caminho da cópia de segurança."""
    with tempfile.TemporaryDirectory() as tmp:
        novo = Path(tmp) / "novo.db"
        with gzip.open(arquivo_gz, "rb") as entrada, open(novo, "wb") as saida:
            shutil.copyfileobj(entrada, saida)
        validar_banco(novo)
        destino.parent.mkdir(parents=True, exist_ok=True)
        backup = None
        if destino.exists():
            backup = destino.with_suffix(".db.bak")
            shutil.copy2(destino, backup)
        shutil.copy2(novo, destino)
    return backup


async def _enviar(config: Config, arquivo: Path) -> None:
    async with Bot(config.telegram_bot_token) as bot:
        with open(arquivo, "rb") as f:
            await bot.send_document(
                config.telegram_chat_id, f, filename=NOME_ARQUIVO,
                caption="🗄️ Banco do Estudo IA. Responda a esta mensagem com /importar no bot da VPS.",
                **TEMPOS,
            )


def enviar_banco(config: Config) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        arquivo = compactar_banco(config.caminho_banco, Path(tmp) / NOME_ARQUIVO)
        asyncio.run(_enviar(config, arquivo))
