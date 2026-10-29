"""Banco de dados (SQLite) com as tabelas do projeto.

Usamos o SQLModel: cada classe abaixo vira uma tabela, e cada atributo vira
uma coluna. O SQLite é um banco inteiro dentro de um único arquivo
(`data/estudo.db`), sem servidor para instalar.
"""

from datetime import date, datetime, timezone
from pathlib import Path

from sqlmodel import Field, Session, SQLModel, create_engine


def agora() -> datetime:
    """Data e hora atuais em UTC. Guardamos tudo em UTC e convertemos
    para America/Sao_Paulo só na hora de mostrar."""
    return datetime.now(timezone.utc)


class Livro(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    titulo: str
    autor: str = ""
    arquivo: str = Field(unique=True)  # nome do arquivo em biblioteca/
    formato: str  # pdf, epub, mobi...
    total_paginas: int | None = None
    criado_em: datetime = Field(default_factory=agora)


class Capitulo(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    livro_id: int = Field(foreign_key="livro.id", index=True)
    ordem: int  # 1, 2, 3... na ordem do sumário
    titulo: str
    pagina_inicio: int | None = None
    pagina_fim: int | None = None
    texto: str = ""  # texto extraído, só para uso local
    file_search_doc: str | None = None  # documento deste capítulo no Gemini File Search


class Sessao(SQLModel, table=True):
    """Uma sessão de estudo de ~90 minutos dentro da trilha de um livro."""

    id: int | None = Field(default=None, primary_key=True)
    livro_id: int = Field(foreign_key="livro.id", index=True)
    ordem: int
    capitulo_inicio_id: int = Field(foreign_key="capitulo.id")
    capitulo_fim_id: int = Field(foreign_key="capitulo.id")
    status: str = "pendente"  # pendente, entregue, pulada
    data_prevista: date | None = None


class Progresso(SQLModel, table=True):
    """Qual livro está na trilha e em que ponto o Matheus está."""

    id: int | None = Field(default=None, primary_key=True)
    livro_id: int = Field(foreign_key="livro.id", index=True)
    sessao_atual_id: int | None = Field(default=None, foreign_key="sessao.id")
    ativo: bool = True
    atualizado_em: datetime = Field(default_factory=agora)


class Pacote(SQLModel, table=True):
    """O pacote diário gerado para uma sessão (arquivos e status de entrega)."""

    id: int | None = Field(default=None, primary_key=True)
    sessao_id: int = Field(foreign_key="sessao.id", index=True)
    data: date
    caminho_pdf: str | None = None
    caminho_html: str | None = None
    caminho_mp3: str | None = None
    caminho_mp4: str | None = None
    podcast_origem: str | None = None  # "notebooklm" ou "gemini_tts"
    status: str = "gerando"  # gerando, pronto, entregue, falhou
    erro: str | None = None
    criado_em: datetime = Field(default_factory=agora)


def criar_engine(caminho_banco: Path):
    """Abre (ou cria) o arquivo do banco e garante que as tabelas existem."""
    caminho_banco.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{caminho_banco}")
    SQLModel.metadata.create_all(engine)
    return engine


def abrir_sessao(engine) -> Session:
    """Atalho para conversar com o banco: `with abrir_sessao(engine) as s: ...`."""
    return Session(engine)
