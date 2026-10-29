"""Orquestra a criação do pacote: gera o conteúdo, os arquivos e registra no banco."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from estudo_ia.config import Config
from estudo_ia.db import Pacote as PacoteDB, abrir_sessao
from estudo_ia.leitura.claude_livro import criar_cliente
from estudo_ia.pacote.gerador import gerar_pacote
from estudo_ia.pacote.renderizar import gerar_arquivos
from estudo_ia.trilha import planejador


@dataclass
class ArquivosPacote:
    pasta: Path
    html: Path
    pdf: Path
    json: Path
    titulo: str


def criar_pacote(engine, config: Config, teste: bool = False, avisar=print) -> ArquivosPacote:
    """Cria o pacote da próxima sessão do livro da trilha.

    Em modo teste, os arquivos vão para data/pacotes/teste e nada é registrado
    no banco (assim o teste não entra na revisão espaçada).
    """
    situacao = planejador.situacao_atual(engine)
    if situacao is None:
        raise RuntimeError("Nenhum livro na trilha. Escolha um com /livro.")
    if situacao.proxima is None:
        raise RuntimeError("Todas as sessões deste livro já foram feitas.")
    sessao = situacao.proxima

    nome = "teste" if teste else f"{date.today().isoformat()}-sessao{sessao.id}"
    pasta = config.data_dir / "pacotes" / nome

    # Gerar o texto pode levar alguns minutos: tempo limite maior que o do bot.
    cliente = criar_cliente(config).with_options(timeout=600.0)
    pacote, caminho_json = gerar_pacote(engine, config, cliente, sessao.id, pasta, avisar=avisar)
    avisar("Montando HTML e PDF...")
    html, pdf = gerar_arquivos(pacote, pasta)

    if not teste:
        with abrir_sessao(engine) as s:
            s.add(PacoteDB(
                sessao_id=sessao.id,
                data=date.today(),
                caminho_json=str(caminho_json),
                caminho_html=str(html),
                caminho_pdf=str(pdf),
                status="pronto",
            ))
            s.commit()

    return ArquivosPacote(pasta=pasta, html=html, pdf=pdf, json=caminho_json, titulo=pacote.conteudo.titulo)
