"""Gera o vídeo da sessão: slides (PNG) + narração (Gemini TTS) → MP4 720p."""

import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from estudo_ia.config import Config
from estudo_ia.pacote.modelos import Pacote
from estudo_ia.podcast.audio import duracao_minutos, juntar_wavs
from estudo_ia.podcast.tts import criar_cliente_tts, sintetizar
from estudo_ia.video.montagem import juntar_trechos, montar_trecho
from estudo_ia.video.slides import gerar_pngs

VOZ_NARRADOR = "Sadaltager"  # "Knowledgeable": tom de professor
LIMITE_MB = 50  # limite de arquivos enviados por bots do Telegram
PALAVRAS_POR_MINUTO = 140  # ritmo médio de narração em português

log = logging.getLogger(__name__)


@dataclass
class ResultadoVideo:
    mp4: Path
    minutos: float
    megabytes: float
    avisos: list[str] = field(default_factory=list)


def estimar_minutos(pacote: Pacote) -> float:
    palavras = sum(len(s.narracao.split()) for s in pacote.midia.roteiro_video)
    return palavras / PALAVRAS_POR_MINUTO


def dividir_ao_meio(texto: str) -> tuple[str, str]:
    """Divide o texto em duas metades, cortando no fim de uma frase."""
    frases = re.split(r"(?<=[.!?])\s+", texto.strip())
    if len(frases) < 2:
        palavras = texto.split()
        meio = len(palavras) // 2
        return " ".join(palavras[:meio]), " ".join(palavras[meio:])
    meio = len(frases) // 2
    return " ".join(frases[:meio]), " ".join(frases[meio:])


def narrar_slide(cliente, config: Config, texto: str, destino: Path) -> Path:
    """Narra um slide. Se o texto travar o modelo em todas as tentativas,
    narra em duas metades e junta (textos menores costumam destravar)."""
    def falar(trecho: str, arquivo: Path) -> Path:
        return sintetizar(cliente, config, [{"type": "text", "text": trecho}],
                          [{"voice": VOZ_NARRADOR}], arquivo, modelo=config.gemini_modelo_tts_video)

    try:
        return falar(texto, destino)
    except Exception:
        log.warning("Narração travou em todas as tentativas; tentando em duas metades")
        primeira, segunda = dividir_ao_meio(texto)
        partes = [falar(primeira, destino.with_name(destino.stem + "_a.wav")),
                  falar(segunda, destino.with_name(destino.stem + "_b.wav"))]
        juntar_wavs(partes, destino, pausa_s=0.2)
        for parte in partes:
            parte.unlink()
        return destino


def gerar_video(pacote: Pacote, pasta: Path, config: Config, avisar=print) -> ResultadoVideo:
    avisos = []
    # Controle de duração ANTES de gastar com a narração: o tamanho do roteiro decide.
    estimativa = estimar_minutos(pacote)
    if estimativa > config.video_max_min:
        avisos.append(f"Roteiro longo: ~{estimativa:.0f} min estimados (limite {config.video_max_min}).")

    cliente = criar_cliente_tts(config)
    # As narrações ficam guardadas: se o vídeo falhar no meio, a próxima
    # execução reaproveita o que já foi narrado (não paga nem espera de novo).
    pasta_narracao = pasta / "narracao"
    pasta_narracao.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        avisar("Desenhando os slides...")
        pngs = gerar_pngs(pacote, tmp)
        trechos = []
        for i, (png, slide) in enumerate(zip(pngs, pacote.midia.roteiro_video), 1):
            wav = pasta_narracao / f"fala{i:02}.wav"
            if not wav.exists():
                avisar(f"Narrando slide {i} de {len(pngs)}")
                narrar_slide(cliente, config, slide.narracao, wav)
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
