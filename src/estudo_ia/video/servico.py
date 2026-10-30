"""Gera o vídeo da sessão: slides (PNG) + narração (Gemini TTS) → MP4 720p."""

import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from estudo_ia.config import Config
from estudo_ia.ingestao.file_search import criar_cliente as criar_cliente_gemini
from estudo_ia.pacote.modelos import Pacote
from estudo_ia.podcast.audio import duracao_minutos
from estudo_ia.podcast.tts import sintetizar
from estudo_ia.video.montagem import juntar_trechos, montar_trecho
from estudo_ia.video.slides import gerar_pngs

VOZ_NARRADOR = "Sadaltager"  # "Knowledgeable": tom de professor
LIMITE_MB = 50  # limite de arquivos enviados por bots do Telegram
PALAVRAS_POR_MINUTO = 140  # ritmo médio de narração em português


@dataclass
class ResultadoVideo:
    mp4: Path
    minutos: float
    megabytes: float
    avisos: list[str] = field(default_factory=list)


def estimar_minutos(pacote: Pacote) -> float:
    palavras = sum(len(s.narracao.split()) for s in pacote.midia.roteiro_video)
    return palavras / PALAVRAS_POR_MINUTO


def gerar_video(pacote: Pacote, pasta: Path, config: Config, avisar=print) -> ResultadoVideo:
    avisos = []
    # Controle de duração ANTES de gastar com a narração: o tamanho do roteiro decide.
    estimativa = estimar_minutos(pacote)
    if estimativa > config.video_max_min:
        avisos.append(f"Roteiro longo: ~{estimativa:.0f} min estimados (limite {config.video_max_min}).")

    cliente = criar_cliente_gemini(config)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        avisar("Desenhando os slides...")
        pngs = gerar_pngs(pacote, tmp)
        trechos = []
        for i, (png, slide) in enumerate(zip(pngs, pacote.midia.roteiro_video), 1):
            avisar(f"Narrando slide {i} de {len(pngs)}")
            wav = sintetizar(cliente, config, [{"type": "text", "text": slide.narracao}],
                             [{"voice": VOZ_NARRADOR}], tmp / f"fala{i:02}.wav")
            trechos.append(montar_trecho(png, wav, tmp / f"trecho{i:02}.mp4"))
        avisar("Montando o vídeo...")
        pasta.mkdir(parents=True, exist_ok=True)
        mp4 = juntar_trechos(trechos, pasta / "video.mp4")

    minutos = duracao_minutos(mp4)
    megabytes = mp4.stat().st_size / 1024 / 1024
    if minutos > config.video_max_min:
        avisos.append(f"O vídeo ficou com {minutos:.1f} min (limite {config.video_max_min}).")
    if megabytes >= LIMITE_MB:
        avisos.append(f"O vídeo tem {megabytes:.0f} MB e não pode ser enviado pelo bot (limite {LIMITE_MB} MB).")
    return ResultadoVideo(mp4, round(minutos, 1), round(megabytes, 1), avisos)
