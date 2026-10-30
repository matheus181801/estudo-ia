"""Monta o MP4: cada slide (imagem parada) fica na tela durante a sua narração.

Por que o arquivo fica leve: o vídeo é feito de imagens paradas. O codec
H.264 com `-tune stillimage` guarda o quadro uma vez e depois só registra
"nada mudou", e usamos poucos quadros por segundo. Quase todo o tamanho do
arquivo é o áudio.
"""

import subprocess
from pathlib import Path

from estudo_ia.podcast.audio import _programa

PAUSA_ENTRE_SLIDES_S = 0.7


def montar_trecho(png: Path, wav: Path, destino: Path) -> Path:
    """Um trecho de vídeo: o slide parado enquanto toca a narração (+ uma pausa)."""
    subprocess.run(
        [_programa("ffmpeg"), "-y", "-v", "error",
         "-loop", "1", "-framerate", "2", "-i", str(png),   # imagem repetida, 2 quadros/segundo
         "-i", str(wav),
         "-af", f"apad=pad_dur={PAUSA_ENTRE_SLIDES_S}",      # silêncio no fim do slide
         "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast", "-crf", "26",
         "-pix_fmt", "yuv420p", "-r", "2",
         "-c:a", "aac", "-b:a", "96k", "-ac", "1", "-ar", "24000",
         "-shortest", str(destino)],                        # termina junto com o áudio
        check=True,
    )
    return destino


def juntar_trechos(trechos: list[Path], destino: Path) -> Path:
    """Junta os trechos sem recodificar (todos têm o mesmo formato)."""
    lista = destino.with_suffix(".txt")
    lista.write_text("".join(f"file '{t.resolve().as_posix()}'\n" for t in trechos), encoding="utf-8")
    subprocess.run(
        [_programa("ffmpeg"), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lista),
         "-c", "copy", "-movflags", "+faststart", str(destino)],  # faststart: começa a tocar antes de baixar tudo
        check=True,
    )
    lista.unlink()
    return destino
