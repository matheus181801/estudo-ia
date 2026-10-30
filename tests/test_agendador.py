"""Testes da Fase 7: agendador, limpeza e importação do banco."""

import os
import sqlite3
import time
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from estudo_ia.agendador import criar_agendador, limpar_antigos
from estudo_ia.bot.banco import compactar_banco, instalar_banco
from estudo_ia.config import Config
from estudo_ia.db import criar_engine
from tests.test_trilha_bot import criar_livro


def test_agendador_nos_horarios_e_fuso_certos(tmp_path):
    config = Config(data_dir=tmp_path, hora_inicio_pipeline="04:00", hora_entrega="06:00")
    agendador = criar_agendador(config, criar_engine(tmp_path / "t.db"))
    jobs = {j.id: j for j in agendador.get_jobs()}
    assert set(jobs) == {"gerar", "entregar", "limpar"}
    assert "hour='4'" in str(jobs["gerar"].trigger) and "minute='0'" in str(jobs["gerar"].trigger)
    assert "hour='6'" in str(jobs["entregar"].trigger)
    assert str(jobs["gerar"].trigger.timezone) == "America/Sao_Paulo"


def test_limpeza_apaga_so_pacotes_antigos(tmp_path):
    pacotes = tmp_path / "pacotes"
    velho, novo = pacotes / "2026-09-01-sessao1", pacotes / "2026-10-29-sessao2"
    for pasta in (velho, novo):
        pasta.mkdir(parents=True)
    quarenta_dias = time.time() - 40 * 86400
    os.utime(velho, (quarenta_dias, quarenta_dias))
    assert limpar_antigos(Config(data_dir=tmp_path), agora=datetime.now()) == [velho.name]
    assert novo.exists() and not velho.exists()


def test_banco_vai_e_volta_compactado(tmp_path):
    origem = tmp_path / "origem.db"
    engine = criar_engine(origem)
    criar_livro(engine)
    engine.dispose()
    gz = compactar_banco(origem, tmp_path / "banco.db.gz")

    destino = tmp_path / "vps" / "estudo.db"
    destino.parent.mkdir()
    destino.write_bytes(b"banco antigo")
    backup = instalar_banco(gz, destino)
    assert backup.read_bytes() == b"banco antigo"  # cópia de segurança guardada
    with closing(sqlite3.connect(destino)) as con:
        assert con.execute("SELECT count(*) FROM capitulo").fetchone()[0] == 2


def test_importar_recusa_arquivo_que_nao_e_banco(tmp_path):
    import gzip

    lixo = tmp_path / "lixo.db.gz"
    with gzip.open(lixo, "wb") as f:
        f.write(b"isto nao e um banco")
    destino = tmp_path / "estudo.db"
    destino.write_bytes(b"banco atual")
    with pytest.raises(ValueError):
        instalar_banco(lixo, destino)
    assert destino.read_bytes() == b"banco atual"  # nada foi trocado


def test_rodada_do_mba_so_entra_com_tudo_configurado(tmp_path):
    engine = criar_engine(tmp_path / "t.db")
    sem_mba = {j.id for j in criar_agendador(Config(data_dir=tmp_path), engine).get_jobs()}
    assert "mba" not in sem_mba
    com_mba = Config(data_dir=tmp_path, telegram_bot_token_mba="t", telegram_grupo_mba_id="-1",
                     drive_ponte_url="https://x/exec", drive_ponte_chave="k")
    jobs = {j.id: j for j in criar_agendador(com_mba, engine).get_jobs()}
    assert "minute='0,30'" in str(jobs["mba"].trigger)
