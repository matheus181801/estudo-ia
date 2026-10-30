# Imagem do Estudo IA: Python 3.12 + ffmpeg + Chromium (Playwright) + fontes.
#
# Docker empacota o programa com tudo de que ele precisa (sistema, bibliotecas,
# programas) numa "imagem". O EasyPanel roda essa imagem como um "container":
# o mesmo ambiente no notebook, na VPS ou em qualquer lugar.

FROM python:3.12-slim-bookworm

# uv (gerenciador de pacotes), copiado da imagem oficial.
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /usr/local/bin/uv

# ffmpeg (podcast e vídeo), fontes com acentos e emoji (PDF e slides), fuso horário.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ffmpeg fonts-noto-core fonts-noto-color-emoji tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=America/Sao_Paulo \
    DATA_DIR=/data \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# Primeiro só as dependências: essa camada fica em cache e o build fica rápido
# quando só o nosso código muda.
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-dev --no-install-project

# Chromium do Playwright, com as bibliotecas de sistema que ele exige.
RUN uv run --no-sync playwright install --with-deps chromium

# Agora o código do projeto.
COPY src ./src
RUN uv sync --frozen --no-dev

# Pasta de dados persistente: banco, pacotes gerados e logs (volume no EasyPanel).
VOLUME ["/data"]

CMD ["uv", "run", "--no-sync", "estudo-ia", "servico"]
