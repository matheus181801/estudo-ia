"""Testes da Fase 0: configuração, banco e proteção dos segredos."""

from pathlib import Path

import pytest
from sqlmodel import select

from estudo_ia.config import carregar_config
from estudo_ia.db import Livro, abrir_sessao, criar_engine

RAIZ = Path(__file__).resolve().parent.parent

VARIAVEIS = [
    "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "PROVEDOR_TEXTO", "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID", "EMAIL_DESTINO", "GMAIL_REMETENTE", "GMAIL_SENHA_DE_APP",
    "FUSO", "HORA_INICIO_PIPELINE", "HORA_ENTREGA", "PODCAST_MAX_MIN",
    "VIDEO_MAX_MIN", "DATA_DIR", "BIBLIOTECA_DIR",
    "GEMINI_MODELO_TEXTO", "GEMINI_MODELO_RESERVA", "GEMINI_MODELO_EMBEDDING", "GEMINI_MODELO_TTS", "GEMINI_MODELO_TTS_VIDEO", "CLAUDE_MODELO", "NOTEBOOKLM_PERFIL",
    "TELEGRAM_BOT_TOKEN_MBA", "TELEGRAM_GRUPO_MBA_ID", "DRIVE_PONTE_URL", "DRIVE_PONTE_CHAVE",
    "HORA_ENTREGA_MBA", "MBA_GERAR_VIDEO", "MBA_GERAR_PODCAST",
]


@pytest.fixture(autouse=True)
def ambiente_limpo(monkeypatch):
    """Cada teste começa sem nenhuma variável do projeto no ambiente."""
    for nome in VARIAVEIS:
        monkeypatch.delenv(nome, raising=False)


def test_le_o_arquivo_env(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "PROVEDOR_TEXTO=gemini   # comentário no fim da linha\n"
        "PODCAST_MAX_MIN=20\n"
        "ANTHROPIC_API_KEY=chave-falsa-de-teste\n",
        encoding="utf-8",
    )
    config = carregar_config(env)
    assert config.provedor_texto == "gemini"
    assert config.podcast_max_min == 20
    assert config.anthropic_api_key == "chave-falsa-de-teste"


def test_senha_com_cerquilha_nao_e_cortada(tmp_path):
    env = tmp_path / ".env"
    env.write_text("GMAIL_SENHA_DE_APP=abc#123\nPROVEDOR_TEXTO=gemini # comentário\n", encoding="utf-8")
    config = carregar_config(env)
    assert config.gmail_senha_de_app == "abc#123"
    assert config.provedor_texto == "gemini"


def test_valores_padrao_sem_env(tmp_path):
    config = carregar_config(tmp_path / "nao-existe.env")
    assert config.provedor_texto == "claude"
    assert config.fuso == "America/Sao_Paulo"
    assert config.video_max_min == 15


def test_provedor_invalido_da_erro(monkeypatch):
    monkeypatch.setenv("PROVEDOR_TEXTO", "openai")
    with pytest.raises(ValueError):
        carregar_config(None)


def test_segredos_nao_aparecem_na_tela(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token-super-secreto")
    config = carregar_config(None)
    assert "token-super-secreto" not in repr(config)
    assert "token-super-secreto" not in str(config.resumo_seguro())
    assert config.resumo_seguro()["telegram_bot_token"] == "definido"


def test_banco_cria_tabelas_e_grava(tmp_path):
    engine = criar_engine(tmp_path / "teste.db")
    with abrir_sessao(engine) as s:
        s.add(Livro(titulo="Livro de teste", arquivo="teste.pdf", formato="pdf"))
        s.commit()
        assert s.exec(select(Livro)).one().titulo == "Livro de teste"


def test_gitignore_protege_o_que_e_sensivel():
    regras = (RAIZ / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env" in regras
    assert "data/" in regras
    assert "biblioteca/*" in regras
