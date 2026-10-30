"""Gera o podcast do dia com degradação graciosa.

Degradação graciosa: se a parte mais "chique" falhar (NotebookLM), o
sistema não para; cai para uma alternativa um pouco mais simples (Gemini
TTS) e avisa. O Matheus sempre recebe um podcast.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from estudo_ia.config import Config
from estudo_ia.leitura.claude_livro import criar_cliente as criar_cliente_claude
from estudo_ia.pacote.modelos import Pacote
from estudo_ia.podcast.audio import duracao_minutos, para_mp3

log = logging.getLogger(__name__)

NOTEBOOKLM = "notebooklm"
GEMINI_TTS = "gemini_tts"


@dataclass
class ResultadoPodcast:
    mp3: Path
    origem: str  # "notebooklm" ou "gemini_tts"
    minutos: float
    avisos: list[str] = field(default_factory=list)


def gerar_podcast(pacote: Pacote, pasta: Path, config: Config, forcar_fallback: bool = False,
                  avisar=print) -> ResultadoPodcast:
    pasta.mkdir(parents=True, exist_ok=True)
    mp3 = pasta / "podcast.mp3"
    avisos = []

    if not forcar_fallback:
        try:
            from estudo_ia.podcast.notebooklm import gerar_audio_notebooklm

            avisar("Gerando o podcast no NotebookLM (pode levar uns 15 minutos)...")
            original = gerar_audio_notebooklm(pacote, pasta / "podcast_notebooklm.m4a",
                                              perfil=config.notebooklm_perfil)
            minutos = duracao_minutos(original)
            if minutos <= config.podcast_max_min:
                para_mp3(original, mp3)
                original.unlink(missing_ok=True)
                return ResultadoPodcast(mp3, NOTEBOOKLM, round(minutos, 1))
            avisos.append(f"O áudio do NotebookLM teve {minutos:.0f} min (limite: {config.podcast_max_min}).")
        except Exception as erro:
            log.exception("Falha no NotebookLM")
            avisos.append(f"NotebookLM falhou ({type(erro).__name__}: {str(erro)[:150]}). "
                          "A sessão do login pode ter expirado.")

    from estudo_ia.podcast.tts import criar_cliente_tts, gerar_audio_tts

    gerar_audio_tts(criar_cliente_claude(config).with_options(timeout=600.0),
                    criar_cliente_tts(config), config, pacote, mp3, avisar=avisar)
    minutos = duracao_minutos(mp3)
    if minutos > config.podcast_max_min:
        avisos.append(f"Mesmo o podcast do Gemini TTS passou do limite ({minutos:.0f} min).")
    return ResultadoPodcast(mp3, GEMINI_TTS, round(minutos, 1), avisos)
