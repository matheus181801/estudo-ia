"""Agendador: roda o pipeline nos horários certos, dentro do próprio container.

Usamos o APScheduler (um "cron" dentro do Python). Ele roda em segundo
plano, em threads, enquanto o bot do Telegram fica no processo principal:
um único container faz as duas coisas.

- HORA_INICIO_PIPELINE (04:00): gera texto, podcast e vídeo.
- HORA_ENTREGA (06:00): envia e-mail e Telegram.
- 03:00: apaga pacotes com mais de 30 dias (o disco da VPS é limitado).
"""

import logging
import shutil
import time
from datetime import datetime, timedelta
from logging.handlers import RotatingFileHandler
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from estudo_ia.config import Config

log = logging.getLogger(__name__)

DIAS_GUARDADOS = 30


def configurar_logs(config: Config) -> None:
    """Logs na tela e em arquivo com rotação (5 arquivos de 2 MB, os mais velhos somem)."""
    pasta = config.data_dir / "logs"
    pasta.mkdir(parents=True, exist_ok=True)
    formato = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    arquivo = RotatingFileHandler(pasta / "estudo-ia.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    arquivo.setFormatter(formato)
    tela = logging.StreamHandler()
    tela.setFormatter(formato)
    logging.basicConfig(level=logging.INFO, handlers=[tela, arquivo], force=True)
    # A URL do Telegram contém o token: não deixamos a biblioteca httpx registrá-la.
    logging.getLogger("httpx").setLevel(logging.WARNING)


def limpar_antigos(config: Config, agora: datetime | None = None) -> list[str]:
    """Apaga pastas de pacotes com mais de 30 dias. Devolve os nomes apagados."""
    pasta = config.data_dir / "pacotes"
    if not pasta.exists():
        return []
    limite = (agora or datetime.now()) - timedelta(days=DIAS_GUARDADOS)
    apagadas = []
    for item in pasta.iterdir():
        if item.is_dir() and datetime.fromtimestamp(item.stat().st_mtime) < limite:
            shutil.rmtree(item)
            apagadas.append(item.name)
    return apagadas


def _com_retentativas(nome: str, funcao, config: Config, tentativas: int = 3, espera_s: int = 300):
    """Roda uma etapa; se der erro inesperado, tenta de novo depois de alguns minutos."""
    from estudo_ia.entrega import telegram

    for tentativa in range(1, tentativas + 1):
        try:
            return funcao()
        except Exception as erro:
            log.exception("%s falhou (tentativa %d de %d)", nome, tentativa, tentativas)
            if tentativa == tentativas:
                try:
                    telegram.avisar(config, f"⚠️ Estudo IA: {nome} falhou {tentativas} vezes ({type(erro).__name__}).")
                except Exception:
                    log.exception("Não consegui avisar no Telegram")
            else:
                time.sleep(espera_s)


def _hora_minuto(texto: str) -> tuple[int, int]:
    hora, minuto = texto.split(":")
    return int(hora), int(minuto)


def criar_agendador(config: Config, engine) -> BackgroundScheduler:
    from estudo_ia.entrega import pipeline

    agendador = BackgroundScheduler(timezone=config.fuso)
    h, m = _hora_minuto(config.hora_inicio_pipeline)
    agendador.add_job(
        lambda: _com_retentativas("a geração do pacote", lambda: pipeline.gerar(engine, config, avisar=log.info), config),
        CronTrigger(hour=h, minute=m, timezone=config.fuso), id="gerar", misfire_grace_time=3600,
    )
    h, m = _hora_minuto(config.hora_entrega)
    agendador.add_job(
        lambda: _com_retentativas("a entrega", lambda: pipeline.entregar(engine, config, avisar=log.info), config),
        CronTrigger(hour=h, minute=m, timezone=config.fuso), id="entregar", misfire_grace_time=3600,
    )
    agendador.add_job(
        lambda: log.info("Limpeza: %s", limpar_antigos(config) or "nada a apagar"),
        CronTrigger(hour=3, minute=0, timezone=config.fuso), id="limpar",
    )
    if mba_configurado(config):
        from estudo_ia.mba import processador

        # A cada 30 min: procura aulas novas no Drive, processa e entrega as que
        # já passaram das 06:30 do dia seguinte. max_instances=1 (padrão) evita
        # duas rodadas ao mesmo tempo quando uma aula demora.
        agendador.add_job(
            lambda: _com_retentativas("a rodada do MBA",
                                      lambda: processador.ciclo(engine, config, avisar=log.info),
                                      config, tentativas=1),
            CronTrigger(minute="0,30", timezone=config.fuso), id="mba",
        )
    return agendador


def mba_configurado(config: Config) -> bool:
    return bool(config.telegram_bot_token_mba and config.telegram_grupo_mba_id
                and config.drive_ponte_url and config.drive_ponte_chave)


def rodar_servico(config: Config, engine) -> None:
    """O que o container roda: agendador em segundo plano + os bots no processo principal."""
    import asyncio

    from estudo_ia.bot.app import criar_app

    configurar_logs(config)
    agendador = criar_agendador(config, engine)
    agendador.start()
    for job in agendador.get_jobs():
        log.info("Agendado: %s → próxima execução %s", job.id, job.next_run_time)

    apps = [criar_app(config, engine)]
    if mba_configurado(config):
        from estudo_ia.mba.bot_mba import criar_app_mba
        apps.append(criar_app_mba(config, engine))

    async def rodar_bots():
        # Vários bots no mesmo processo: cada um faz o seu long polling.
        for app in apps:
            await app.initialize()
            await app.start()
            await app.updater.start_polling()
        log.info("Serviço Estudo IA no ar (%d bot%s).", len(apps), "s" if len(apps) > 1 else "")
        try:
            await asyncio.Event().wait()  # roda até o container ser parado
        finally:
            for app in apps:
                await app.updater.stop()
                await app.stop()
                await app.shutdown()

    asyncio.run(rodar_bots())
