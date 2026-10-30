"""Gera o conteúdo do pacote diário com o Claude.

São duas chamadas:
1. conteúdo: newsletter, 15 questões e inglês técnico;
2. mídia: roteiro do vídeo e material-fonte do podcast.

Dividir em duas deixa cada resposta menor (menos chance de corte) e permite
refazer só a parte que falhou.
"""

import json
from datetime import date
from pathlib import Path

import anthropic
from pydantic import ValidationError
from sqlmodel import select

from estudo_ia.config import Config
from estudo_ia.db import Capitulo, Livro, Pacote as PacoteDB, Sessao, abrir_sessao
from estudo_ia.pacote.modelos import ConteudoPacote, MidiaPacote, Pacote, QuestaoMultipla
from estudo_ia.pacote.pesquisa import ResultadoPesquisa, pesquisar_conceitos

REGRAS = """Você prepara o material diário de estudo do Matheus, que está em transição de carreira
para tecnologia e IA (MBA em AI Leadership). Ele estuda 90 minutos por dia, offline.

Você recebe dois documentos: o trecho do livro (ponto de partida) e notas de pesquisa na web
que aprofundam os mesmos conceitos. O objetivo é que ele entenda os CONCEITOS de verdade,
não que decore o que o autor disse.

Regras obrigatórias:
- Escreva em português do Brasil. Termos técnicos ficam em inglês, com a explicação ao lado.
- Tudo deve ser explicação ORIGINAL, com as suas palavras. Não copie nem traduza trechos do livro
  nem das fontes da web.
- Citação literal só se for essencial: no máximo duas frases, entre aspas, indicando a origem.
- Use só o que está nos dois documentos; não invente dados, números, nomes ou estudos.

Tom: DIVERTIDO e leve, para o entendimento fluir sem esforço.
- Escreva como um amigo que manja muito do assunto explicando num café.
- Use analogias do cotidiano (cozinha, futebol, trânsito, séries, games, vida no escritório).
- Pode ter humor, referências de cultura pop e frases de efeito, desde que o conceito fique certo.
- Frases curtas, parágrafos curtos, nada de tom de apostila.
- Divertido não é infantil: ele é um adulto num MBA, então o conteúdo continua profundo."""

PEDIDO_CONTEUDO = """Com base nos documentos acima (sessão {ordem} de {total}), crie:
- a newsletter da sessão: título, abertura, 4 a 6 seções (cada uma com uma analogia do dia a dia),
  5 ideias-chave, "na prática" e uma curiosidade (de preferência algo que veio da pesquisa web);
- 5 termos de inglês técnico importantes para os conceitos da sessão;
- 10 questões de múltipla escolha (4 alternativas, uma correta, comentário explicando)
  e 5 questões abertas com a resposta esperada.

Sobre as questões:
- Pergunte sobre os CONCEITOS, não sobre o livro. Evite "segundo o autor...", "como o livro chama..."
  ou detalhes que só servem para decorar (nomes de personagens, datas, números soltos).
- Pelo menos metade deve usar o que a pesquisa web acrescentou (exemplos reais, debates, outras definições).
- Prefira cenários práticos: "uma empresa quer..., o que fazer?", "qual o risco de...?", "compare X e Y".
- Misture níveis: entender, aplicar, analisar. Varie a posição da alternativa correta.
- As questões abertas devem fazer pensar (ex.: aplicar o conceito no trabalho dele)."""

PEDIDO_MIDIA = """Com base nos documentos acima (sessão {ordem} de {total}), no mesmo tom divertido, crie:
- o roteiro de um vídeo-aula com slides: 10 a 14 slides; a narração somada deve ter entre
  1.100 e 1.500 palavras (cerca de 10 minutos falados);
- notas de estudo originais de 1.500 a 2.000 palavras, que servirão de fonte para um podcast
  com dois apresentadores conversando sobre o tema."""


def texto_da_sessao(engine, sessao: Sessao) -> tuple[list[Capitulo], str]:
    """Junta o texto dos capítulos da sessão.

    Quando a sessão é só uma parte de um capítulo longo, pegamos a fatia
    proporcional às páginas (o texto foi salvo por capítulo, não por página).
    """
    with abrir_sessao(engine) as s:
        caps = s.exec(
            select(Capitulo)
            .where(Capitulo.livro_id == sessao.livro_id)
            .where(Capitulo.ordem >= s.get(Capitulo, sessao.capitulo_inicio_id).ordem)
            .where(Capitulo.ordem <= s.get(Capitulo, sessao.capitulo_fim_id).ordem)
            .order_by(Capitulo.ordem)
        ).all()

    partes = []
    for cap in caps:
        paginas = cap.pagina_fim - cap.pagina_inicio + 1
        inicio = max(sessao.pagina_inicio, cap.pagina_inicio) - cap.pagina_inicio
        fim = min(sessao.pagina_fim, cap.pagina_fim) - cap.pagina_inicio + 1
        corte_ini = len(cap.texto) * inicio // paginas
        corte_fim = len(cap.texto) * fim // paginas
        partes.append(f"## Capítulo {cap.ordem}: {cap.titulo}\n\n{cap.texto[corte_ini:corte_fim]}")
    return list(caps), "\n\n".join(partes)


def _gerar(cliente, config: Config, livro: Livro, texto: str, notas: str, pedido: str, formato):
    # Streaming: a resposta chega aos poucos, o que evita o tempo limite em
    # respostas longas. O limite de tokens é alto porque o raciocínio interno
    # (thinking) do modelo também conta nele.
    try:
        with cliente.messages.stream(
            model=config.claude_modelo,
            max_tokens=64000,
            system=REGRAS,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "document",
                        "source": {"type": "text", "media_type": "text/plain", "data": texto},
                        "title": f"Trecho do livro: {livro.titulo} — {livro.autor}",
                    },
                    {
                        "type": "document",
                        "source": {"type": "text", "media_type": "text/plain",
                                   "data": notas or "(pesquisa web indisponível hoje)"},
                        "title": "Notas de pesquisa na web sobre os conceitos da sessão",
                        # Os dois documentos são iguais nas duas chamadas: o cache economiza na segunda.
                        "cache_control": {"type": "ephemeral"},
                    },
                    {"type": "text", "text": pedido},
                ],
            }],
            output_format=formato,
        ) as stream:
            resposta = stream.get_final_message()
    except ValidationError as erro:
        # JSON incompleto quase sempre significa resposta cortada no meio.
        raise RuntimeError("A resposta do Claude veio incompleta (JSON cortado).") from erro
    if resposta.stop_reason == "max_tokens":
        raise RuntimeError("A resposta do Claude foi cortada (max_tokens).")
    if resposta.stop_reason == "refusal":
        raise RuntimeError("O Claude recusou gerar este pacote.")
    return resposta.parsed_output


def conferir_conteudo(conteudo: ConteudoPacote) -> list[str]:
    """O formato é garantido pela API, mas as quantidades não: conferimos aqui."""
    problemas = []
    if len(conteudo.multipla_escolha) != 10:
        problemas.append(f"{len(conteudo.multipla_escolha)} questões de múltipla escolha (esperado 10)")
    if len(conteudo.abertas) != 5:
        problemas.append(f"{len(conteudo.abertas)} questões abertas (esperado 5)")
    if len(conteudo.ingles) != 5:
        problemas.append(f"{len(conteudo.ingles)} termos de inglês (esperado 5)")
    for i, q in enumerate(conteudo.multipla_escolha, 1):
        if len(q.alternativas) != 4 or not 0 <= q.correta < len(q.alternativas):
            problemas.append(f"questão {i} com alternativas ou gabarito inválidos")
    return problemas


def escolher_revisao(engine, sessao: Sessao) -> list[QuestaoMultipla]:
    """Revisão espaçada: 3 questões de sessões anteriores.

    Pegamos a sessão de ontem, a de 3 sessões atrás e a de 7 sessões atrás
    (quanto mais antiga, maior o intervalo, como nas técnicas de memorização).
    """
    with abrir_sessao(engine) as s:
        anteriores = s.exec(
            select(PacoteDB)
            .where(PacoteDB.sessao_id != sessao.id, PacoteDB.caminho_json != None)  # noqa: E711
            .order_by(PacoteDB.criado_em.desc())
        ).all()
    if not anteriores:
        return []

    posicoes = [p for p in (0, 2, 6) if p < len(anteriores)]
    posicoes += [p for p in range(len(anteriores)) if p not in posicoes]
    questoes = []
    for pos in posicoes[:3]:
        caminho = Path(anteriores[pos].caminho_json)
        if not caminho.exists():
            continue
        # Lemos só as questões: assim pacotes antigos continuam servindo para a
        # revisão mesmo quando o formato do resto do pacote muda.
        dados = json.loads(caminho.read_text(encoding="utf-8"))
        lista = [QuestaoMultipla.model_validate(q) for q in dados["conteudo"]["multipla_escolha"]]
        if lista:
            questoes.append(lista[(date.today().toordinal() + pos) % len(lista)])
    return questoes


def gerar_pacote(engine, config: Config, cliente: anthropic.Anthropic, sessao_id: int,
                 pasta: Path, avisar=print) -> tuple[Pacote, Path]:
    """Gera o pacote de uma sessão e salva o pacote.json na pasta indicada."""
    with abrir_sessao(engine) as s:
        sessao = s.get(Sessao, sessao_id)
        livro = s.get(Livro, sessao.livro_id)
        total = len(s.exec(select(Sessao.id).where(Sessao.livro_id == livro.id)).all())

    capitulos, texto = texto_da_sessao(engine, sessao)
    formato = {"ordem": sessao.ordem, "total": total}
    revisao = escolher_revisao(engine, sessao)  # antes das chamadas pagas: se falhar, não gasta nada

    avisar("Pesquisando os conceitos na web...")
    try:
        pesquisa = pesquisar_conceitos(cliente, config, f"{livro.titulo} — {livro.autor}", texto)
    except Exception as erro:
        # A pesquisa enriquece o pacote, mas não é essencial: sem ela, seguimos só com o livro.
        avisar(f"! Pesquisa web falhou ({type(erro).__name__}); seguindo só com o livro.")
        pesquisa = ResultadoPesquisa(notas="")

    avisar("Gerando newsletter e questões...")
    conteudo = _gerar(cliente, config, livro, texto, pesquisa.notas,
                      PEDIDO_CONTEUDO.format(**formato), ConteudoPacote)
    for problema in conferir_conteudo(conteudo):
        avisar(f"! {problema}")

    avisar("Gerando roteiro do vídeo e fonte do podcast...")
    midia = _gerar(cliente, config, livro, texto, pesquisa.notas,
                   PEDIDO_MIDIA.format(**formato), MidiaPacote)

    pacote = Pacote(
        livro=livro.titulo,
        autor=livro.autor,
        sessao_ordem=sessao.ordem,
        sessao_total=total,
        capitulos=[c.titulo for c in capitulos],
        data=date.today().isoformat(),
        conteudo=conteudo,
        midia=midia,
        revisao=revisao,
        fontes_web=pesquisa.fontes,
    )
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / "pacote.json"
    caminho.write_text(pacote.model_dump_json(indent=2), encoding="utf-8")
    return pacote, caminho


def carregar_pacote(caminho: Path) -> Pacote:
    return Pacote.model_validate(json.loads(Path(caminho).read_text(encoding="utf-8")))
