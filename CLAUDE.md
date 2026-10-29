# Estudo IA — automação diária de estudos

Projeto pessoal do Matheus Capobianco. Ele está em transição de carreira para tecnologia/IA
(MBA AI Leadership na FIAP) e está aprendendo a programar. Este projeto é, ao mesmo tempo,
uma ferramenta de estudo e uma peça de portfólio.

## Como trabalhar com o Matheus

- Fale sempre em **português do Brasil**. Termos técnicos ficam em inglês, com a explicação ao lado.
- Ele é iniciante em programação: explique as decisões, comente o código em pt-BR e prefira
  soluções simples e legíveis a soluções "espertas".
- Trabalhe por fases (veja `docs/PLANO.md`). Ao terminar cada fase, faça um resumo curto do
  que foi construído e dos conceitos envolvidos (o que é um container, um webhook, um embedding etc.).
- Faça commits pequenos e frequentes, com mensagens em pt-BR.
- **Peça confirmação antes de qualquer ação destrutiva ou difícil de desfazer**: apagar arquivos,
  reiniciar ou alterar serviços que já existem na VPS, mexer em DNS, firewall ou banco de dados.

## O que o sistema faz

1. **Biblioteca com RAG**: os livros (PDF/EPUB) da pasta `biblioteca/` são indexados no
   Gemini File Search. O texto de cada capítulo também é extraído e guardado localmente.
2. **Bot no Telegram**: o Matheus pergunta qualquer coisa sobre os livros e recebe a resposta
   em pt-BR, citando livro e capítulo. Pelo bot ele também escolhe o livro da trilha.
3. **Pacote diário às 06:00 (America/Sao_Paulo)**, pensado para 90 minutos de estudo offline:
   - newsletter em estilo animado (HTML no corpo do e-mail + PDF);
   - 15 questões (múltipla escolha e abertas) com gabarito comentado no final do PDF;
   - quadro "inglês técnico do dia" com 5 termos do capítulo;
   - revisão espaçada: 3 perguntas de sessões anteriores;
   - **podcast de no máximo 25 minutos**, gerado no NotebookLM;
   - **vídeo com slides narrados de no máximo 15 minutos**.
4. **Entrega**: e-mail (newsletter + PDF) e Telegram (PDF, MP3 e MP4, para baixar e ouvir/assistir offline).

## Arquitetura

```
biblioteca/ (PDF, EPUB)
   └─> ingestao: extrai texto por capítulo ──> SQLite (livros, capítulos, sessões, progresso)
                 └─> Gemini File Search (RAG)
bot Telegram (long polling) ──> perguntas ──> Gemini + File Search ──> resposta com citação
                             ──> /livro, /livros, /status, /proximo, /pacote
agendador 04:00 ──> planejador (sessão do dia) ──> Claude API: newsletter, 15 questões,
                    roteiro do vídeo, fontes do podcast
                ──> podcast: NotebookLM (notebooklm-py) ──[falhou ou >25 min]──> Gemini TTS 2 vozes
                ──> vídeo: slides (HTML→PNG) + narração Gemini TTS ──> ffmpeg ──> MP4 ≤15 min
agendador 06:00 ──> entrega: e-mail (SMTP Gmail) + Telegram (arquivos)
```

### Decisões importantes

- **Telegram em long polling**, não webhook: dispensa domínio e HTTPS.
- **Podcast pelo NotebookLM via `notebooklm-py`**: é uma biblioteca **não oficial**, que usa APIs
  internas do Google e pode quebrar sem aviso. Por isso o fallback é obrigatório: se a geração falhar,
  passar do tempo limite ou o áudio tiver mais de 25 minutos (medir com `ffprobe`), gerar o podcast
  com o Gemini TTS de duas vozes, a partir de um roteiro de cerca de 20 minutos escrito pelo Claude.
  Áudio em pt-BR. A geração no NotebookLM pode levar vários minutos; por isso o pipeline começa às 04:00.
- **Vídeo**: slides gerados a partir do roteiro (HTML renderizado em PNG com Playwright),
  narração por slide com o Gemini TTS, montagem com ffmpeg. Resolução 720p, ajustes para imagem
  estática, arquivo final abaixo de 50 MB (limite de envio de bots do Telegram).
- **Texto dos pacotes**: Claude API. Deixar o provedor configurável (Claude ou Gemini) em `.env`.
- **Nomes de modelos mudam com frequência**: antes de escrever o código de cada integração,
  confira na documentação oficial os modelos atuais (Claude, Gemini, Gemini TTS, embeddings) e
  coloque os nomes em configuração, nunca espalhados pelo código.
- **Estado** em SQLite num volume persistente (`/data`), junto com os arquivos gerados e a sessão do NotebookLM.

## Infraestrutura

- VPS da HostGator com **EasyPanel**. Na mesma VPS já roda o site Quanto Gastou:
  **não derrube nem altere esse serviço**. Antes de instalar qualquer coisa, verifique RAM, CPU e
  disco livres e reporte ao Matheus.
- Deploy em Docker (Dockerfile + serviço no EasyPanel ou docker-compose), com volume persistente em `/data`.
- Agendamento dentro do container (APScheduler ou cron), fuso `America/Sao_Paulo`.
- Falhas em qualquer etapa geram aviso no Telegram do Matheus. Use retentativas com espera.
- Código versionado num repositório **privado** no GitHub.

## Regras inegociáveis

- **Direitos autorais**: só entram em `biblioteca/` livros que o Matheus adquiriu legalmente.
  Não busque, baixe ou sugira livros de fontes piratas. Os pacotes e respostas são **explicações
  originais**; citações do livro têm no máximo duas frases e sempre com referência. Não traduza nem
  reproduza capítulos inteiros. A pasta `biblioteca/` fica fora do git.
- **Segredos** (chaves de API, token do bot, senha de app do Gmail, sessão do NotebookLM) ficam
  em `.env` local e nas variáveis de ambiente do EasyPanel. Nunca no git, nunca em logs, nunca
  impressos na tela. O Matheus digita as chaves ele mesmo no `.env`.

## Stack

Python 3.12 com `uv` · `python-telegram-bot` · `anthropic` · `google-genai` · `notebooklm-py` ·
`pymupdf` e `ebooklib` (extração) · `jinja2` + `weasyprint` (HTML → PDF) · `playwright` (slides) ·
`ffmpeg` · `apscheduler` · `sqlmodel` (SQLite) · `pytest`

## Estrutura de pastas

```
estudo-ia/
├── CLAUDE.md
├── docs/            PLANO.md, PRE-REQUISITOS.md
├── biblioteca/      livros (fora do git)
├── src/estudo_ia/
│   ├── config.py        lê o .env
│   ├── db.py            modelos SQLite
│   ├── ingestao/        extração por capítulo + File Search
│   ├── bot/             Telegram
│   ├── trilha/          planejador de sessões
│   ├── pacote/          newsletter, questões, PDF (templates jinja2)
│   ├── podcast/         NotebookLM + fallback Gemini TTS
│   ├── video/           slides + narração + ffmpeg
│   ├── entrega/         e-mail e Telegram
│   └── agendador.py
├── tests/
├── Dockerfile
├── .env.example
└── .gitignore
```
