# Plano de construção

Cada fase termina com um critério de aceite verificável e com um resumo didático para o Matheus.
Não avance de fase sem o aceite da anterior. Construa e teste localmente primeiro; a VPS entra na Fase 7.

## Fase 0 — Fundação
- Repositório git com a estrutura do `CLAUDE.md`, `.gitignore` (inclui `.env`, `biblioteca/`, `data/`), `.env.example`.
- Projeto Python com `uv`, `config.py` lendo o `.env`, `db.py` com as tabelas: livros, capítulos, sessões, progresso, pacotes.
- Repositório privado no GitHub e primeiro push.
- **Aceite**: `uv run pytest` passa com um teste básico de configuração; nada sensível no git.
- **Ensinar**: ambiente virtual, gerenciador de pacotes, variáveis de ambiente, por que segredos não vão para o git.

## Fase 1 — Biblioteca e RAG
- Ingestão de PDF (PyMuPDF) e EPUB (ebooklib): extrair sumário e texto por capítulo; guardar no SQLite.
- Avisar quando um PDF não tiver texto selecionável (escaneado) ou passar de 100 MB.
- Criar o File Search store no Gemini e enviar os livros, com metadados (título, autor, capítulo).
- Comando de linha `uv run estudo-ia ingerir` (só processa livros novos).
- **Aceite**: a lista de livros mostra o número de capítulos de cada um; uma pergunta de teste em
  português retorna resposta citando livro e capítulo.
- **Ensinar**: o que são chunks, embeddings e busca semântica; por que a resposta cita a fonte.

## Fase 2 — Bot do Telegram (local)
- Long polling, aceitando mensagens **somente do chat_id do Matheus**.
- Perguntas livres → RAG → resposta em pt-BR com citação.
- Comandos: `/livros`, `/livro <nome>` (define o livro da trilha), `/status`, `/proximo`, `/pular`, `/pacote` (gera o pacote agora).
- **Aceite**: os comandos funcionam no celular do Matheus com o bot rodando no notebook.
- **Ensinar**: long polling × webhook; como um bot recebe mensagens.

## Fase 3 — Trilha e pacote de texto
- Ao escolher um livro, o planejador divide os capítulos em sessões de 90 minutos (em geral 15 a 30 páginas) e salva o plano.
- Gerador do pacote com a Claude API: newsletter animada, 15 questões com gabarito comentado,
  inglês técnico do dia (5 termos), revisão espaçada (3 perguntas de sessões anteriores),
  roteiro do vídeo e material-fonte do podcast.
- Templates jinja2 → HTML (corpo do e-mail) e PDF (weasyprint), legíveis no celular.
- Respeitar as regras de direitos autorais do `CLAUDE.md`.
- **Aceite**: `uv run estudo-ia pacote --teste` gera o HTML e o PDF de uma sessão real; o Matheus revisa e aprova o formato.
- **Ensinar**: prompt engineering na prática, saídas estruturadas (JSON), templates.

## Fase 4 — Podcast (máximo 25 minutos)
- Caminho principal: `notebooklm-py` cria um caderno do dia com o material da sessão, gera o
  Audio Overview em pt-BR e baixa o MP3. A autenticação é feita uma vez com `notebooklm login`
  no notebook do Matheus; a sessão salva vai para a VPS como segredo.
- Medir a duração com `ffprobe`. Se passar de 25 minutos, falhar ou exceder o tempo limite,
  usar o fallback: roteiro de cerca de 20 minutos (Claude) → Gemini TTS com duas vozes, gerado em blocos e concatenado.
- Avisar no Telegram quando o fallback for usado (sinal de que a sessão do NotebookLM pode ter expirado).
- **Aceite**: um MP3 de até 25 minutos gerado pelos dois caminhos (forçar o fallback num teste).
- **Ensinar**: integrações frágeis, fallback e degradação graciosa.

## Fase 5 — Vídeo (máximo 15 minutos)
- Roteiro do vídeo → slides em HTML com identidade visual simples → PNG (Playwright).
- Narração de cada slide com Gemini TTS (uma voz, pt-BR) → ffmpeg monta o MP4 720p.
- Controlar a duração pelo tamanho do roteiro; validar com `ffprobe` (≤ 15 min) e o tamanho do arquivo (< 50 MB).
- **Aceite**: um MP4 de uma sessão real, assistível no celular, dentro dos dois limites.
- **Ensinar**: pipelines de mídia, codecs, por que slides estáticos geram arquivos leves.

## Fase 6 — Entrega
- E-mail via SMTP do Gmail (senha de app): newsletter no corpo, PDF anexo.
- Telegram: envia PDF, MP3 e MP4 com legendas curtas.
- **Aceite**: o Matheus recebe tudo no celular e consegue baixar para usar offline.

## Fase 7 — Deploy na VPS
- Antes de tudo: checar recursos da VPS e o que já roda nela; reportar ao Matheus e pedir confirmação.
- Dockerfile (Python, ffmpeg, Chromium do Playwright, fontes) e serviço no EasyPanel com volume `/data`.
- Segredos nas variáveis de ambiente do EasyPanel.
- Agendador: 04:00 inicia o pipeline, 06:00 entrega (America/Sao_Paulo). Retentativas e alertas no Telegram.
- Logs com rotação; limpeza de arquivos gerados com mais de 30 dias.
- **Aceite**: o container sobe, o bot responde pela VPS e o Quanto Gastou continua funcionando normalmente.
- **Ensinar**: Docker, volumes, variáveis de ambiente em produção, cron.

## Fase 8 — Rodagem
- Três dias seguidos de pacotes reais. Ajustar duração, tom da newsletter e dificuldade das questões a partir do feedback do Matheus.
- README do repositório pensado como portfólio: o problema, a arquitetura, as decisões e as lições aprendidas.
- **Aceite**: três entregas consecutivas no horário, sem intervenção manual.
