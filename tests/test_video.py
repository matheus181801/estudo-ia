"""Testes da Fase 5: slides e montagem do vídeo (sem chamar a API de voz)."""

import shutil
import subprocess

import pytest

from estudo_ia.pacote.modelos import Slide
from estudo_ia.podcast.audio import duracao_minutos
from estudo_ia.video.montagem import PAUSA_ENTRE_SLIDES_S, juntar_trechos, montar_trecho
from estudo_ia.video.servico import estimar_minutos
from estudo_ia.video.slides import renderizar_slides_html
from tests.test_pacote import pacote_falso
from tests.test_podcast import criar_wav

tem_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg não instalado")


def pacote_com_slides(n: int = 3, palavras: int = 140):
    p = pacote_falso()
    p.midia.roteiro_video = [
        Slide(titulo=f"Slide <{i}>", topicos=["tópico A", "tópico B"], narracao="fala " * palavras)
        for i in range(1, n + 1)
    ]
    return p


def test_slides_html_capa_e_progresso():
    htmls = renderizar_slides_html(pacote_com_slides(4))
    assert len(htmls) == 4
    assert "Sessão 2" in htmls[0] and "tópico A" not in htmls[0]  # o 1º slide é a capa
    assert "tópico A" in htmls[1] and "2 / 4" in htmls[1]
    assert "Slide &lt;3&gt;" in htmls[2]  # texto escapado
    assert "width: 100.0%" in htmls[3]  # barra de progresso cheia no último


def test_estimativa_de_duracao():
    assert estimar_minutos(pacote_com_slides(n=10, palavras=140)) == 10.0


@tem_ffmpeg
def test_monta_mp4_720p_com_duracao_certa(tmp_path):
    png = tmp_path / "slide.png"
    subprocess.run([shutil.which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                    "-i", "color=c=purple:s=1280x720", "-frames:v", "1", str(png)], check=True)
    trechos = [montar_trecho(png, criar_wav(tmp_path / f"f{i}.wav", 2.0), tmp_path / f"t{i}.mp4") for i in range(2)]
    video = juntar_trechos(trechos, tmp_path / "video.mp4")

    esperado_s = 2 * (2.0 + PAUSA_ENTRE_SLIDES_S)
    assert abs(duracao_minutos(video) * 60 - esperado_s) < 0.8
    largura_altura = subprocess.run(
        [shutil.which("ffprobe"), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video)],
        capture_output=True, text=True, check=True).stdout.strip()
    assert largura_altura == "1280,720"
    assert video.stat().st_size < 200_000  # imagens paradas: arquivo bem pequeno
