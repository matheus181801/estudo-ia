"""Formato do pacote diário (saída estruturada).

Cada classe abaixo descreve um pedaço do JSON que o Claude deve devolver.
A API usa essas classes como "molde" (JSON Schema) e garante que a resposta
segue o formato; o Pydantic valida e transforma o JSON em objetos Python.
"""

from pydantic import BaseModel, Field


class Secao(BaseModel):
    emoji: str = Field(description="Um emoji que represente a seção")
    titulo: str
    texto: str = Field(description="Explicação original, 2 a 4 parágrafos curtos")


class Termo(BaseModel):
    termo: str = Field(description="Termo técnico em inglês que aparece no capítulo")
    traducao: str
    explicacao: str = Field(description="O que significa, em português, em 1 ou 2 frases")
    exemplo: str = Field(description="Uma frase de exemplo em inglês usando o termo")


class QuestaoMultipla(BaseModel):
    enunciado: str
    alternativas: list[str] = Field(description="Exatamente 4 alternativas, sem letras na frente")
    correta: int = Field(description="Índice da alternativa correta: 0, 1, 2 ou 3")
    comentario: str = Field(description="Por que a correta está certa e as outras não")


class QuestaoAberta(BaseModel):
    enunciado: str
    resposta_esperada: str = Field(description="Os pontos que uma boa resposta deve cobrir")


class ConteudoPacote(BaseModel):
    """Newsletter, questões e inglês técnico (o que vai no e-mail e no PDF)."""

    titulo: str = Field(description="Título chamativo da edição")
    abertura: str = Field(description="Gancho de 2 ou 3 frases que desperta curiosidade")
    secoes: list[Secao] = Field(description="4 a 6 seções explicando os conceitos da sessão")
    ideias_chave: list[str] = Field(description="Exatamente 5 ideias-chave, uma frase cada")
    na_pratica: str = Field(description="Como aplicar no trabalho de um líder de IA")
    curiosidade: str = Field(description="Um fato curioso ou provocação ligada ao tema")
    ingles: list[Termo] = Field(description="Exatamente 5 termos")
    multipla_escolha: list[QuestaoMultipla] = Field(description="Exatamente 10 questões")
    abertas: list[QuestaoAberta] = Field(description="Exatamente 5 questões")


class Slide(BaseModel):
    titulo: str
    topicos: list[str] = Field(description="2 a 4 tópicos curtos que aparecem no slide")
    narracao: str = Field(description="O que o narrador fala neste slide, em tom de aula")


class MidiaPacote(BaseModel):
    """Material para o vídeo (Fase 5) e para o podcast (Fase 4)."""

    roteiro_video: list[Slide] = Field(description="10 a 14 slides")
    fonte_podcast: str = Field(description="Notas de estudo originais, de 1.500 a 2.000 palavras")


class Pacote(BaseModel):
    """O pacote completo, como é salvo em disco (pacote.json)."""

    livro: str
    autor: str
    sessao_ordem: int
    sessao_total: int
    capitulos: list[str]
    data: str
    conteudo: ConteudoPacote
    midia: MidiaPacote
    revisao: list[QuestaoMultipla] = []
