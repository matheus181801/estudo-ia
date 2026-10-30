"""O pipeline do dia: gerar o pacote completo e entregar.

São duas etapas separadas porque, na VPS, a geração começa às 04:00
(podcast e vídeo demoram) e a entrega acontece às 06:00.

Regra de ouro: uma etapa que falha não derruba as outras. Se o vídeo der
erro, o Matheus ainda recebe newsletter, PDF e podcast, e um alerta no
Telegram explica o que faltou.
"""

import logging
from datetime import date
from pathlib import Path

from sqlmodel import select

from estudo_ia.config import Config
from estudo_ia.db import Pacote as PacoteDB, Sessao, abrir_sessao
from estudo_ia.entrega import email, telegram
from estudo_ia.pacote.gerador import carregar_pacote
from estudo_ia.pacote.servico import criar_pacote
from estudo_ia.trilha import planejador

log = logging.getLogger(__name__)


def _alertar(config: Config, texto: str, avisar=print) -> None:
    avisar(f"! {texto}")
    try:
        telegram.avisar(config, f"⚠️ Estudo IA: {texto}")
    except Exception:
        log.exception("Não consegui mandar o alerta no Telegram")


def pacote_pronto_da_proxima_sessao(engine) -> PacoteDB | None:
    """Se já existe um pacote gerado (e não entregue) para a próxima sessão, reaproveita."""
    situacao = planejador.situacao_atual(engine)
    if situacao is None or situacao.proxima is None:
        return None
    with abrir_sessao(engine) as s:
        return s.exec(
            select(PacoteDB)
            .where(PacoteDB.sessao_id == situacao.proxima.id, PacoteDB.status == "pronto")
            .order_by(PacoteDB.criado_em.desc())
        ).first()


def gerar(engine, config: Config, avisar=print) -> int | None:
    """Gera texto, podcast e vídeo da próxima sessão. Devolve o id do pacote."""
    registro = pacote_pronto_da_proxima_sessao(engine)
    if registro is None:
        try:
            criar_pacote(engine, config, teste=False, avisar=avisar)
        except Exception as erro:
            log.exception("Falha ao gerar o pacote")
            _alertar(config, f"não consegui gerar o pacote de hoje ({erro}).", avisar)
            return None
        registro = pacote_pronto_da_proxima_sessao(engine)

    pasta = Path(registro.caminho_json).parent
    pacote = carregar_pacote(Path(registro.caminho_json))
    atualizacoes = {}

    if not registro.caminho_mp3:
        try:
            from estudo_ia.podcast.servico import gerar_podcast

            podcast = gerar_podcast(pacote, pasta, config, avisar=avisar)
            atualizacoes.update(caminho_mp3=str(podcast.mp3), podcast_origem=podcast.origem)
            for aviso in podcast.avisos:
                _alertar(config, f"podcast: {aviso}", avisar)
        except Exception as erro:
            log.exception("Falha no podcast")
            _alertar(config, f"o podcast de hoje falhou ({type(erro).__name__}).", avisar)

    if not registro.caminho_mp4:
        try:
            from estudo_ia.video.servico import gerar_video

            video = gerar_video(pacote, pasta, config, avisar=avisar)
            atualizacoes["caminho_mp4"] = str(video.mp4)
            for aviso in video.avisos:
                _alertar(config, f"vídeo: {aviso}", avisar)
        except Exception as erro:
            log.exception("Falha no vídeo")
            _alertar(config, f"o vídeo de hoje falhou ({type(erro).__name__}).", avisar)

    with abrir_sessao(engine) as s:
        atual = s.get(PacoteDB, registro.id)
        for campo, valor in atualizacoes.items():
            setattr(atual, campo, valor)
        s.add(atual)
        s.commit()
    return registro.id


def entregar(engine, config: Config, pacote_id: int | None = None, avisar=print) -> bool:
    """Envia e-mail e arquivos no Telegram. Marca a sessão como entregue."""
    if pacote_id is None:
        registro = pacote_pronto_da_proxima_sessao(engine)
        if registro is None:
            _alertar(config, "não há pacote pronto para entregar hoje.", avisar)
            return False
        pacote_id = registro.id

    with abrir_sessao(engine) as s:
        registro = s.get(PacoteDB, pacote_id)
    pacote = carregar_pacote(Path(registro.caminho_json))
    titulo = pacote.conteudo.titulo
    entregou_algo = False

    try:
        avisar("Enviando e-mail...")
        html = Path(registro.caminho_html).read_text(encoding="utf-8")
        assunto = f"📚 Sessão {pacote.sessao_ordem}/{pacote.sessao_total}: {titulo}"
        email.enviar_email(config, assunto, html, Path(registro.caminho_pdf))
        entregou_algo = True
    except Exception as erro:
        log.exception("Falha no e-mail")
        _alertar(config, f"o e-mail de hoje falhou ({type(erro).__name__}: {erro}).", avisar)

    try:
        avisar("Enviando arquivos no Telegram...")
        telegram.avisar(config, f"☀️ Bom dia! Sessão {pacote.sessao_ordem} de {pacote.sessao_total} "
                                f"de {pacote.livro}:\n{titulo}")
        arquivos = [(Path(registro.caminho_pdf), "📄 Newsletter, questões e gabarito")]
        if registro.caminho_mp3:
            arquivos.append((Path(registro.caminho_mp3), "🎧 Podcast do dia"))
        if registro.caminho_mp4:
            arquivos.append((Path(registro.caminho_mp4), "🎬 Vídeo-aula do dia"))
        for aviso in telegram.enviar_arquivos(config, arquivos):
            _alertar(config, aviso, avisar)
        entregou_algo = True
    except Exception as erro:
        log.exception("Falha no Telegram")
        _alertar(config, f"o envio no Telegram falhou ({type(erro).__name__}).", avisar)

    if entregou_algo:
        with abrir_sessao(engine) as s:
            atual = s.get(PacoteDB, pacote_id)
            atual.status = "entregue"
            sessao = s.get(Sessao, atual.sessao_id)
            sessao.status = "entregue"
            sessao.data_prevista = date.today()
            s.add(atual)
            s.add(sessao)
            s.commit()
    return entregou_algo
