"""Ferramentas de áudio: medir duração, juntar trechos e converter para MP3.

Usamos o ffmpeg (converte e junta mídia) e o ffprobe (lê informações de um
arquivo de mídia, como a duração). Os dois são programas de linha de
comando; o Python só os chama com `subprocess`.
"""

import shutil
import subprocess
import wave
from pathlib import Path


def _programa(nome: str) -> str:
    caminho = shutil.which(nome)
    if caminho is None:
        raise RuntimeError(f"{nome} não encontrado. Instale o ffmpeg (winget install Gyan.FFmpeg).")
    return caminho


def duracao_minutos(arquivo: Path) -> float:
    """Duração do áudio em minutos, lida pelo ffprobe."""
    saida = subprocess.run(
        [_programa("ffprobe"), "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(arquivo)],
        capture_output=True, text=True, check=True,
    )
    return float(saida.stdout.strip()) / 60


def para_mp3(entrada: Path, saida: Path) -> Path:
    """Converte para MP3 mono de 64 kbps: voz fica clara e o arquivo, leve
    (25 minutos ≈ 12 MB, bem abaixo do limite de 50 MB do Telegram)."""
    subprocess.run(
        [_programa("ffmpeg"), "-y", "-v", "error", "-i", str(entrada),
         "-ac", "1", "-b:a", "64k", str(saida)],
        check=True,
    )
    return saida


def juntar_wavs(trechos: list[Path], saida: Path, pausa_s: float = 0.4) -> Path:
    """Junta vários WAV no mesmo formato, com uma pequena pausa entre eles."""
    with wave.open(str(trechos[0])) as primeiro:
        parametros = primeiro.getparams()
    silencio = b"\x00" * int(parametros.framerate * pausa_s) * parametros.sampwidth * parametros.nchannels

    with wave.open(str(saida), "wb") as destino:
        destino.setparams(parametros)
        for i, trecho in enumerate(trechos):
            with wave.open(str(trecho)) as origem:
                destino.writeframes(origem.readframes(origem.getnframes()))
            if i < len(trechos) - 1:
                destino.writeframes(silencio)
    return saida
