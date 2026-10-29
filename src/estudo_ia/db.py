"""Banco de dados (SQLite) com as tabelas do projeto.

Usamos o SQLModel: cada classe abaixo vira uma tabela, e cada atributo vira
uma coluna. O SQLite é um banco inteiro dentro de um único arquivo
(`data/estudo.db`), sem servidor para instalar.
"""

from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import inspect, text
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
    # Um capítulo muito longo pode virar mais de uma sessão; por isso guardamos as páginas.
    pagina_inicio: int
    pagina_fim: int
    caracteres: int = 0  # tamanho do texto da sessão (mede o esforço de leitura)
    status: str = "pendente"  # pendente, entregue, pulada
    data_prevista: date | None = None


class Progresso(SQLModel, table=True):
    """Qual livro está na trilha e em que ponto o Matheus está."""

    id: int | None = Field(default=None, primary_key=True)
    livro_id: int = Field(foreign_key="livro.id", index=True)
    ativo: bool = True  # só um livro fica ativo por vez
    atualizado_em: datetime = Field(default_factory=agora)


class Pacote(SQLModel, table=True):
    """O pacote diário gerado para uma sessão (arquivos e status de entrega)."""

    id: int | None = Field(default=None, primary_key=True)
    sessao_id: int = Field(foreign_key="sessao.id", index=True)
    data: date
    caminho_json: str | None = None  # conteúdo completo (usado na revisão espaçada)
    caminho_pdf: str | None = None
    caminho_html: str | None = None
    caminho_mp3: str | None = None
    caminho_mp4: str | None = None
    podcast_origem: str | None = None  # "notebooklm" ou "gemini_tts"
    status: str = "gerando"  # gerando, pronto, entregue, falhou
    erro: str | None = None
    criado_em: datetime = Field(default_factory=agora)


def _migrar_colunas_novas(engine) -> None:
    """Migração simples: acrescenta colunas novas em tabelas que já existem.

    O `create_all` cria tabelas que faltam, mas não altera as existentes.
    Quando acrescentamos um campo numa classe acima, esta função cria a
    coluna no banco (vazia), sem apagar nenhum dado.
    """
    inspetor = inspect(engine)
    with engine.begin() as conexao:
        for tabela in SQLModel.metadata.sorted_tables:
            if not inspetor.has_table(tabela.name):
                continue
            existentes = {c["name"] for c in inspetor.get_columns(tabela.name)}
            for coluna in tabela.columns:
                if coluna.name not in existentes:
                    tipo = coluna.type.compile(engine.dialect)
                    conexao.execute(text(f'ALTER TABLE {tabela.name} ADD COLUMN "{coluna.name}" {tipo}'))


def criar_engine(caminho_banco: Path):
    """Abre (ou cria) o arquivo do banco e garante que as tabelas existem."""
    caminho_banco.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{caminho_banco}")
    SQLModel.metadata.create_all(engine)
    _migrar_colunas_novas(engine)
    return engine


def abrir_sessao(engine) -> Session:
    """Atalho para conversar com o banco: `with abrir_sessao(engine) as s: ...`."""
    return Session(engine)
