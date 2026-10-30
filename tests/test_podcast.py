"""Testes da Fase 4: podcast (sem chamar APIs: usamos áudio sintético e dublês)."""

import shutil
import wave
from pathlib import Path

import pytest

from estudo_ia.config import Config
from estudo_ia.podcast import servico
from estudo_ia.podcast.audio import duracao_minutos, juntar_wavs
from estudo_ia.podcast.tts import Fala, dividir_em_blocos

tem_ffmpeg = pytest.mark.skipif(shutil.which("ffprobe") is None, reason="ffmpeg não instalado")


def criar_wav(caminho: Path, segundos: float, taxa: int = 24000) -> Path:
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(taxa)
        w.writeframes(b"\x00\x00" * int(taxa * segundos))
    return caminho


def test_juntar_wavs_soma_duracoes_com_pausa(tmp_path):
    trechos = [criar_wav(tmp_path / f"{i}.wav", 1.0) for i in range(3)]
    saida = juntar_wavs(trechos, tmp_path / "junto.wav", pausa_s=0.5)
    with wave.open(str(saida)) as w:
        assert abs(w.getnframes() / w.getframerate() - 4.0) < 0.01  # 3 × 1s + 2 pausas de 0,5s


@tem_ffmpeg
def test_duracao_com_ffprobe(tmp_path):
    arquivo = criar_wav(tmp_path / "um_minuto.wav", 60)
    assert abs(duracao_minutos(arquivo) - 1.0) < 0.01


def test_dividir_em_blocos_respeita_limite():
    falas = [Fala(apresentador="Ana" if i % 2 else "Leo", texto="palavra " * 100, estilo="calm") for i in range(7)]
    blocos = dividir_em_blocos(falas, limite=300)
    assert [len(b) for b in blocos] == [3, 3, 1]
    assert sum(len(b) for b in blocos) == 7  # nenhuma fala perdida


def _dublar(monkeypatch, tmp_path, minutos_notebooklm=None, erro_notebooklm=None):
    """Troca as partes que chamam APIs por versões falsas e rápidas."""
    import estudo_ia.podcast.notebooklm as nb
    import estudo_ia.podcast.tts as tts

    def notebooklm_falso(pacote, destino, perfil="estudo", limite_min=30):
        if erro_notebooklm:
            raise erro_notebooklm
        destino.write_text("audio")
        return destino

    def tts_falso(cliente_claude, cliente_gemini, config, pacote, destino, avisar=print):
        destino.write_text("audio tts")
        return destino

    duracoes = {"m4a": minutos_notebooklm, "mp3": 18.0}
    monkeypatch.setattr(nb, "gerar_audio_notebooklm", notebooklm_falso)
    monkeypatch.setattr(tts, "gerar_audio_tts", tts_falso)
    monkeypatch.setattr(servico, "duracao_minutos", lambda arq: duracoes[Path(arq).suffix.lstrip(".")])
    monkeypatch.setattr(servico, "para_mp3", lambda entrada, saida: shutil.copy(entrada, saida))
    monkeypatch.setattr(servico, "criar_cliente_claude", lambda c: type("C", (), {"with_options": lambda s, **k: s})())
    monkeypatch.setattr(tts, "criar_cliente_tts", lambda c: None)


def test_usa_notebooklm_quando_da_certo(monkeypatch, tmp_path):
    _dublar(monkeypatch, tmp_path, minutos_notebooklm=19.0)
    r = servico.gerar_podcast(None, tmp_path, Config(), avisar=lambda *_: None)
    assert r.origem == servico.NOTEBOOKLM and r.avisos == []


def test_fallback_quando_notebooklm_passa_de_25_min(monkeypatch, tmp_path):
    _dublar(monkeypatch, tmp_path, minutos_notebooklm=31.0)
    r = servico.gerar_podcast(None, tmp_path, Config(), avisar=lambda *_: None)
    assert r.origem == servico.GEMINI_TTS
    assert "31 min" in r.avisos[0]


def test_fallback_quando_notebooklm_falha(monkeypatch, tmp_path):
    _dublar(monkeypatch, tmp_path, erro_notebooklm=RuntimeError("sessão expirada"))
    r = servico.gerar_podcast(None, tmp_path, Config(), avisar=lambda *_: None)
    assert r.origem == servico.GEMINI_TTS
    assert "expirado" in r.avisos[0]


def test_sintetizar_desiste_de_pedido_travado(monkeypatch, tmp_path):
    import base64
    import threading

    from estudo_ia.podcast import tts

    chamadas = []
    liberar = threading.Event()

    class InteracoesFalsas:
        def create(self, **_):
            chamadas.append(1)
            if len(chamadas) == 1:
                liberar.wait(5)  # 1º pedido "trava" (nunca responde a tempo)
            return type("R", (), {"output_audio": type("A", (), {"data": base64.b64encode(b"RIFF").decode()})})()

    cliente = type("C", (), {"interactions": InteracoesFalsas()})()
    monkeypatch.setattr(tts, "LIMITE_POR_PEDIDO_S", 0.2)
    monkeypatch.setattr(tts.time, "sleep", lambda s: None)  # não espera de verdade entre tentativas

    destino = tts.sintetizar(cliente, Config(), [], {}, tmp_path / "fala.wav")
    liberar.set()
    assert len(chamadas) == 2  # desistiu do travado e tentou de novo
    assert destino.read_bytes() == b"RIFF"


def test_sintetizar_alterna_modelos_entre_tentativas(monkeypatch, tmp_path):
    import base64

    from estudo_ia.podcast import tts

    modelos_usados = []

    class InteracoesFalsas:
        def create(self, model, **_):
            modelos_usados.append(model)
            if len(modelos_usados) < 3:
                raise RuntimeError("servidor engasgou")
            return type("R", (), {"output_audio": type("A", (), {"data": base64.b64encode(b"RIFF").decode()})})()

    monkeypatch.setattr(tts.time, "sleep", lambda s: None)
    config = Config(gemini_modelo_tts="voz-normal", gemini_modelo_tts_video="voz-lite")
    tts.sintetizar(type("C", (), {"interactions": InteracoesFalsas()})(), config, [], {},
                   tmp_path / "f.wav", modelo="voz-lite")
    assert modelos_usados == ["voz-lite", "voz-normal", "voz-lite"]
