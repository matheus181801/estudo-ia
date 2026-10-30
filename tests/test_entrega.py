"""Testes da Fase 6: entrega (com dublês: nada é enviado de verdade)."""

from datetime import date
from pathlib import Path

import pytest

from estudo_ia.config import Config
from estudo_ia.db import Pacote as PacoteDB, Sessao, abrir_sessao, criar_engine
from estudo_ia.entrega import email, pipeline
from estudo_ia.trilha import planejador
from tests.test_pacote import pacote_falso
from tests.test_trilha_bot import criar_livro

CONFIG = Config(gmail_remetente="eu@gmail.com", gmail_senha_de_app="abcd efgh ijkl mnop",
                email_destino="eu@gmail.com", telegram_bot_token="t", telegram_chat_id="1")


def test_email_tem_html_e_pdf_anexo(tmp_path):
    pdf = tmp_path / "pacote.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste")
    msg = email.montar_email(CONFIG, "Assunto", "<h1>Oi</h1>", pdf)
    assert msg["To"] == "eu@gmail.com" and "Estudo IA" in msg["From"]
    anexos = list(msg.iter_attachments())
    assert len(anexos) == 1 and anexos[0].get_filename() == "pacote.pdf"
    assert "<h1>Oi</h1>" in msg.get_body(preferencelist=("html",)).get_content()


def test_email_reclama_do_que_falta_no_env(tmp_path):
    with pytest.raises(RuntimeError, match="GMAIL_SENHA_DE_APP"):
        email.enviar_email(Config(gmail_remetente="a@b.com", email_destino="a@b.com"), "x", "y", tmp_path / "p.pdf")


@pytest.fixture
def ambiente(tmp_path, monkeypatch):
    """Banco com um livro na trilha e dublês para geração e envio."""
    engine = criar_engine(tmp_path / "t.db")
    livro_id = criar_livro(engine)
    planejador.escolher_livro(engine, livro_id)
    registro = {"alertas": [], "emails": [], "arquivos": []}

    def criar_pacote_falso(engine, config, teste=False, avisar=print):
        pasta = tmp_path / "pacote"
        pasta.mkdir(exist_ok=True)
        (pasta / "pacote.json").write_text(pacote_falso().model_dump_json(), encoding="utf-8")
        (pasta / "newsletter.html").write_text("<p>news</p>", encoding="utf-8")
        (pasta / "pacote.pdf").write_bytes(b"%PDF")
        sessao = planejador.situacao_atual(engine).proxima
        with abrir_sessao(engine) as s:
            s.add(PacoteDB(sessao_id=sessao.id, data=date.today(), status="pronto",
                           caminho_json=str(pasta / "pacote.json"), caminho_html=str(pasta / "newsletter.html"),
                           caminho_pdf=str(pasta / "pacote.pdf")))
            s.commit()

    monkeypatch.setattr(pipeline, "criar_pacote", criar_pacote_falso)
    monkeypatch.setattr(pipeline.telegram, "avisar", lambda c, texto: registro["alertas"].append(texto))
    monkeypatch.setattr(pipeline.telegram, "enviar_arquivos",
                        lambda c, arquivos: registro["arquivos"].extend(arquivos) or [])
    monkeypatch.setattr(pipeline.email, "enviar_email",
                        lambda c, assunto, html, pdf: registro["emails"].append(assunto))
    return engine, registro, tmp_path


def test_video_falhando_nao_impede_o_resto(ambiente, monkeypatch):
    engine, registro, tmp_path = ambiente
    import estudo_ia.podcast.servico as podcast
    import estudo_ia.video.servico as video

    def podcast_falso(pacote, pasta, config, avisar=print):
        (pasta / "podcast.mp3").write_bytes(b"mp3")
        return podcast.ResultadoPodcast(pasta / "podcast.mp3", podcast.GEMINI_TTS, 18.0, ["NotebookLM falhou"])

    def video_quebrado(*a, **k):
        raise TimeoutError()

    monkeypatch.setattr(podcast, "gerar_podcast", podcast_falso)
    monkeypatch.setattr(video, "gerar_video", video_quebrado)

    pacote_id = pipeline.gerar(engine, CONFIG, avisar=lambda *_: None)
    assert pacote_id is not None
    assert any("vídeo de hoje falhou" in a for a in registro["alertas"])
    assert any("NotebookLM falhou" in a for a in registro["alertas"])

    assert pipeline.entregar(engine, CONFIG, pacote_id, avisar=lambda *_: None)
    assert len(registro["emails"]) == 1 and "Sessão 2/7" in registro["emails"][0]
    nomes = [Path(a).name for a, _ in registro["arquivos"]]
    assert nomes == ["pacote.pdf", "podcast.mp3"]  # sem vídeo, mas o resto chegou

    with abrir_sessao(engine) as s:
        pacote = s.get(PacoteDB, pacote_id)
        assert pacote.status == "entregue"
        assert s.get(Sessao, pacote.sessao_id).status == "entregue"
    assert planejador.situacao_atual(engine).proxima.ordem == 2  # trilha avançou


def test_gerar_reaproveita_pacote_pronto(ambiente, monkeypatch):
    engine, registro, _ = ambiente
    import estudo_ia.podcast.servico as podcast
    import estudo_ia.video.servico as video

    chamadas = []
    monkeypatch.setattr(podcast, "gerar_podcast", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(video, "gerar_video", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    original = pipeline.criar_pacote
    monkeypatch.setattr(pipeline, "criar_pacote", lambda *a, **k: chamadas.append(1) or original(*a, **k))

    primeiro = pipeline.gerar(engine, CONFIG, avisar=lambda *_: None)
    segundo = pipeline.gerar(engine, CONFIG, avisar=lambda *_: None)
    assert primeiro == segundo and len(chamadas) == 1  # o texto não é gerado (nem pago) duas vezes
