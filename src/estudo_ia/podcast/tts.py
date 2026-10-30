"""Fallback do podcast: roteiro de diálogo (Claude) + duas vozes (Gemini TTS).

1. O Claude escreve um diálogo de ~20 minutos entre dois apresentadores.
2. O Gemini TTS transforma o diálogo em fala, em blocos de ~2 minutos
   (pedidos menores falham menos e, se um falhar, só ele é refeito).
3. Os blocos são juntados e convertidos para MP3.
"""

import base64
import logging
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import anthropic
from google import genai
from pydantic import BaseModel, Field

from estudo_ia.config import Config
from estudo_ia.pacote.modelos import Pacote
from estudo_ia.podcast.audio import juntar_wavs, para_mp3

# Os nomes dos apresentadores e as vozes do Gemini (lista de vozes na documentação).
APRESENTADORES = {"Ana": "Aoede", "Leo": "Puck"}  # Aoede: leve; Puck: animado
PALAVRAS_POR_BLOCO = 300  # ~2 minutos de fala
LIMITE_POR_PEDIDO_S = 60  # um pedido normal leva de 7 a 30 s; acima de 1 min consideramos travado

log = logging.getLogger(__name__)

PEDIDO_ROTEIRO = """Escreva o roteiro de um podcast em português do Brasil com dois apresentadores,
Ana e Leo, conversando sobre o material de estudo abaixo. O ouvinte é o Matheus, que faz um MBA
em AI Leadership. Regras:
- {tamanho}
- Conversa natural e divertida: perguntas, analogias do dia a dia, pequenas brincadeiras,
  um apresentador desafiando o outro. Nada de leitura de apostila.
- Falas curtas (no máximo 80 palavras cada), alternando bastante entre os dois.
- Comece com "Bem-vindos ao Estudo IA" e termine com um resumo das ideias principais.
- Explique com palavras originais; não invente dados que não estão no material.
- Escreva números e siglas como devem ser falados (ex.: "dois mil e vinte e quatro", "R L H F")."""


TAMANHO_LIVRO = """Entre 3.000 e 3.400 palavras no total (cerca de 20 minutos falados). É um episódio longo:
  aprofunde cada conceito com exemplos, perguntas e casos antes de passar ao próximo."""
TAMANHO_AULA = """Entre 1.300 e 1.600 palavras no total (cerca de 10 minutos falados). É um complemento
  CURTO e objetivo de uma aula: revise os conceitos principais e explique do zero os termos técnicos."""


class Fala(BaseModel):
    apresentador: str = Field(description="Ana ou Leo")
    texto: str
    estilo: str = Field(description="Como falar, em inglês curto (ex.: excited, curious, calm)")


class RoteiroPodcast(BaseModel):
    falas: list[Fala]


def escrever_roteiro(cliente: anthropic.Anthropic, config: Config, pacote: Pacote) -> RoteiroPodcast:
    with cliente.messages.stream(
        model=config.claude_modelo,
        max_tokens=64000,
        messages=[{
            "role": "user",
            "content": PEDIDO_ROTEIRO.format(tamanho=TAMANHO_AULA if pacote.tipo == "aula" else TAMANHO_LIVRO)
                       + f"\n\n# Material de estudo\n\n{pacote.midia.fonte_podcast}",
        }],
        output_format=RoteiroPodcast,
    ) as stream:
        resposta = stream.get_final_message()
    roteiro = resposta.parsed_output
    for fala in roteiro.falas:  # garante que só existem os dois nomes conhecidos
        if fala.apresentador not in APRESENTADORES:
            fala.apresentador = "Ana"
    return roteiro


def dividir_em_blocos(falas: list[Fala], limite: int = PALAVRAS_POR_BLOCO) -> list[list[Fala]]:
    blocos, atual, palavras = [], [], 0
    for fala in falas:
        n = len(fala.texto.split())
        if atual and palavras + n > limite:
            blocos.append(atual)
            atual, palavras = [], 0
        atual.append(fala)
        palavras += n
    if atual:
        blocos.append(atual)
    return blocos


def criar_cliente_tts(config: Config) -> genai.Client:
    """Cliente do Gemini só para voz: sem as retentativas automáticas da biblioteca,
    porque as nossas (em `sintetizar`) já cuidam disso e duas camadas multiplicam a espera."""
    return genai.Client(api_key=config.gemini_api_key)


def sintetizar(cliente: genai.Client, config: Config, conteudo: list[dict], speech_config,
               destino: Path, modelo: str | None = None) -> Path:
    """Um pedido ao Gemini TTS, salvo como WAV.

    Tenta de novo com espera crescente se der erro (no plano gratuito é comum
    bater no limite de pedidos por minuto). Usado pelo podcast e pelo vídeo.
    """
    # Alternamos entre dois modelos de voz a cada tentativa: quando um deles
    # "engasga" no mesmo pedido, o outro costuma responder normalmente.
    modelos = [modelo or config.gemini_modelo_tts, config.gemini_modelo_tts_video]
    if modelos[1] == modelos[0]:
        modelos[1] = config.gemini_modelo_tts
    for tentativa in range(5):
        # Tempo limite "duro": já vimos um pedido ficar preso para sempre sem
        # resposta (o timeout da biblioteca não valeu). A chamada roda numa
        # thread e, se passar do limite, desistimos dela e tentamos de novo.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            futuro = executor.submit(
                cliente.interactions.create,
                model=modelos[tentativa % 2],
                input=[{"type": "user_input", "content": conteudo}],
                response_format={"type": "audio"},
                generation_config={"speech_config": speech_config},
            )
            resposta = futuro.result(timeout=LIMITE_POR_PEDIDO_S)
            # A resposta já vem como WAV completo (com cabeçalho), em base64.
            destino.write_bytes(base64.b64decode(resposta.output_audio.data))
            return destino
        except Exception as erro:
            log.warning("Gemini TTS falhou (tentativa %d de 5): %s", tentativa + 1, type(erro).__name__)
            if tentativa == 4:
                raise
            time.sleep(10 * (tentativa + 1))  # espera crescente: 10s, 20s, 30s...
        finally:
            executor.shutdown(wait=False)  # não espera a thread presa terminar
    return destino


def _falar_bloco(cliente: genai.Client, config: Config, bloco: list[Fala], destino: Path) -> Path:
    conteudo = [
        {
            "type": "text",
            "text": fala.texto,
            "annotations": [{"type": "speech_metadata", "speaker": fala.apresentador, "style": fala.estilo}],
        }
        for fala in bloco
    ]
    vozes = {"speakers": [{"speaker": nome, "voice": voz} for nome, voz in APRESENTADORES.items()]}
    return sintetizar(cliente, config, conteudo, vozes, destino)


def gerar_audio_tts(cliente_claude: anthropic.Anthropic, cliente_gemini: genai.Client,
                    config: Config, pacote: Pacote, destino_mp3: Path, avisar=print) -> Path:
    avisar("Escrevendo o roteiro do podcast...")
    roteiro = escrever_roteiro(cliente_claude, config, pacote)
    # Guardamos o roteiro junto do MP3: ajuda a revisar e a ajustar o tamanho.
    destino_mp3.with_name("podcast_roteiro.json").write_text(roteiro.model_dump_json(indent=2), encoding="utf-8")
    palavras = sum(len(f.texto.split()) for f in roteiro.falas)
    avisar(f"Roteiro com {len(roteiro.falas)} falas e {palavras} palavras")
    blocos = dividir_em_blocos(roteiro.falas)
    with tempfile.TemporaryDirectory() as pasta:
        trechos = []
        for i, bloco in enumerate(blocos, 1):
            avisar(f"Gerando voz: bloco {i} de {len(blocos)}")
            trechos.append(_falar_bloco(cliente_gemini, config, bloco, Path(pasta) / f"bloco{i:02}.wav"))
        juntado = juntar_wavs(trechos, Path(pasta) / "podcast.wav")
        return para_mp3(juntado, destino_mp3)
