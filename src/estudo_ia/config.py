"""Leitura da configuração do projeto.

Tudo o que muda entre o notebook e a VPS (chaves, horários, pastas) vem de
variáveis de ambiente. No notebook elas ficam no arquivo `.env`; na VPS,
nas variáveis do EasyPanel. Assim o código é o mesmo nos dois lugares e
nenhum segredo fica escrito no código ou no git.
"""

import os
import re
from dataclasses import dataclass, field, fields
from pathlib import Path

from dotenv import load_dotenv

# Campos que são segredos: nunca aparecem em logs nem na tela.
CAMPOS_SECRETOS = {
    "anthropic_api_key",
    "gemini_api_key",
    "telegram_bot_token",
    "gmail_senha_de_app",
    "telegram_bot_token_mba",
    "drive_ponte_url",
    "drive_ponte_chave",
}


@dataclass(frozen=True)
class Config:
    # Chaves e segredos (podem ficar vazios até a fase que os usa).
    anthropic_api_key: str = field(default="", repr=False)
    gemini_api_key: str = field(default="", repr=False)
    telegram_bot_token: str = field(default="", repr=False)
    gmail_senha_de_app: str = field(default="", repr=False)

    # Dados que não são segredos.
    provedor_texto: str = "claude"  # "claude" ou "gemini"

    # Nomes de modelos mudam com frequência: ficam aqui, nunca espalhados pelo código.
    # Conferidos na documentação do Gemini em 29/10/2026.
    gemini_modelo_texto: str = "gemini-3.8-flash"
    gemini_modelo_reserva: str = "gemini-3.6-flash"  # usado se o principal estiver sobrecarregado
    gemini_modelo_embedding: str = "models/gemini-embedding-2"
    gemini_modelo_tts: str = "gemini-3.8-flash-tts"  # podcast: vozes mais expressivas
    gemini_modelo_tts_video: str = "gemini-3.8-flash-lite-tts"  # narrador do vídeo: mais rápido
    # Claude lê o livro da trilha inteiro (escolha do Matheus: Haiku 5.5, o mais barato).
    claude_modelo: str = "claude-haiku-5-5"
    telegram_chat_id: str = ""
    email_destino: str = ""
    gmail_remetente: str = ""

    # Agenda e limites.
    fuso: str = "America/Sao_Paulo"
    hora_inicio_pipeline: str = "04:00"
    hora_entrega: str = "06:00"
    podcast_max_min: int = 25
    notebooklm_perfil: str = "estudo"  # perfil de login do notebooklm-py
    video_max_min: int = 15

    # MBA (aulas do Google Drive).
    telegram_bot_token_mba: str = field(default="", repr=False)
    telegram_grupo_mba_id: str = ""
    drive_ponte_url: str = field(default="", repr=False)
    drive_ponte_chave: str = field(default="", repr=False)
    hora_entrega_mba: str = "06:30"

    # Pastas.
    data_dir: Path = Path("./data")
    biblioteca_dir: Path = Path("./biblioteca")

    @property
    def caminho_banco(self) -> Path:
        """Arquivo do SQLite, sempre dentro da pasta de dados."""
        return self.data_dir / "estudo.db"

    def resumo_seguro(self) -> dict[str, str]:
        """Mostra a configuração escondendo os segredos (bom para depurar)."""
        resumo = {}
        for campo in fields(self):
            valor = getattr(self, campo.name)
            if campo.name in CAMPOS_SECRETOS:
                resumo[campo.name] = "definido" if valor else "vazio"
            else:
                resumo[campo.name] = str(valor)
        return resumo


def _limpa(valor: str) -> str:
    """Remove comentários no fim da linha (ex.: 'claude   # claude ou gemini').

    Só conta como comentário um '#' com espaço antes: assim uma senha que
    contém '#' (ex.: 'abc#123') não é cortada.
    """
    return re.split(r"\s+#", valor, maxsplit=1)[0].strip()


def carregar_config(arquivo_env: str | Path | None = ".env") -> Config:
    """Lê o `.env` (se existir) e as variáveis de ambiente e devolve um Config.

    Variáveis já definidas no ambiente têm prioridade sobre o arquivo,
    que é o comportamento esperado na VPS.
    """
    if arquivo_env and Path(arquivo_env).exists():
        load_dotenv(arquivo_env, override=False)

    def ler(nome: str, padrao: str = "") -> str:
        return _limpa(os.environ.get(nome, padrao))

    provedor = ler("PROVEDOR_TEXTO", "claude").lower()
    if provedor not in {"claude", "gemini"}:
        raise ValueError(f"PROVEDOR_TEXTO deve ser 'claude' ou 'gemini', recebi '{provedor}'.")

    return Config(
        anthropic_api_key=ler("ANTHROPIC_API_KEY"),
        gemini_api_key=ler("GEMINI_API_KEY"),
        telegram_bot_token=ler("TELEGRAM_BOT_TOKEN"),
        gmail_senha_de_app=ler("GMAIL_SENHA_DE_APP"),
        provedor_texto=provedor,
        gemini_modelo_texto=ler("GEMINI_MODELO_TEXTO", "gemini-3.8-flash"),
        gemini_modelo_reserva=ler("GEMINI_MODELO_RESERVA", "gemini-3.6-flash"),
        gemini_modelo_embedding=ler("GEMINI_MODELO_EMBEDDING", "models/gemini-embedding-2"),
        gemini_modelo_tts=ler("GEMINI_MODELO_TTS", "gemini-3.8-flash-tts"),
        gemini_modelo_tts_video=ler("GEMINI_MODELO_TTS_VIDEO", "gemini-3.8-flash-lite-tts"),
        claude_modelo=ler("CLAUDE_MODELO", "claude-haiku-5-5"),
        telegram_chat_id=ler("TELEGRAM_CHAT_ID"),
        email_destino=ler("EMAIL_DESTINO"),
        gmail_remetente=ler("GMAIL_REMETENTE"),
        fuso=ler("FUSO", "America/Sao_Paulo"),
        hora_inicio_pipeline=ler("HORA_INICIO_PIPELINE", "04:00"),
        hora_entrega=ler("HORA_ENTREGA", "06:00"),
        podcast_max_min=int(ler("PODCAST_MAX_MIN", "25")),
        notebooklm_perfil=ler("NOTEBOOKLM_PERFIL", "estudo"),
        video_max_min=int(ler("VIDEO_MAX_MIN", "15")),
        telegram_bot_token_mba=ler("TELEGRAM_BOT_TOKEN_MBA"),
        telegram_grupo_mba_id=ler("TELEGRAM_GRUPO_MBA_ID"),
        drive_ponte_url=ler("DRIVE_PONTE_URL"),
        drive_ponte_chave=ler("DRIVE_PONTE_CHAVE"),
        hora_entrega_mba=ler("HORA_ENTREGA_MBA", "06:30"),
        data_dir=Path(ler("DATA_DIR", "./data")),
        biblioteca_dir=Path(ler("BIBLIOTECA_DIR", "./biblioteca")),
    )
