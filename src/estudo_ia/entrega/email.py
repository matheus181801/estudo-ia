"""Entrega por e-mail: newsletter no corpo e PDF anexo, via SMTP do Gmail.

SMTP é o protocolo padrão de envio de e-mails. O Gmail aceita conexões
SMTP autenticadas com uma "senha de app": uma senha de 16 letras criada
só para este programa, que pode ser revogada sem mexer na senha da conta.
"""

import smtplib
from email.message import EmailMessage
from pathlib import Path

from estudo_ia.config import Config

SERVIDOR_SMTP = "smtp.gmail.com"
PORTA_SMTP = 465  # SMTP com SSL (conexão criptografada desde o início)


def montar_email(config: Config, assunto: str, html: str, pdf: Path) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"Estudo IA <{config.gmail_remetente}>"
    msg["To"] = config.email_destino
    msg["Subject"] = assunto
    # Texto simples para leitores de e-mail que não mostram HTML.
    msg.set_content("Sua newsletter de hoje está em HTML. O PDF com as questões vai anexo.")
    msg.add_alternative(html, subtype="html")
    msg.add_attachment(pdf.read_bytes(), maintype="application", subtype="pdf", filename=pdf.name)
    return msg


def enviar_email(config: Config, assunto: str, html: str, pdf: Path) -> None:
    faltando = [nome for nome, valor in [("GMAIL_REMETENTE", config.gmail_remetente),
                                         ("GMAIL_SENHA_DE_APP", config.gmail_senha_de_app),
                                         ("EMAIL_DESTINO", config.email_destino)] if not valor]
    if faltando:
        raise RuntimeError(f"Preencha no .env: {', '.join(faltando)}")

    msg = montar_email(config, assunto, html, pdf)
    with smtplib.SMTP_SSL(SERVIDOR_SMTP, PORTA_SMTP, timeout=60) as smtp:
        # A senha de app às vezes é copiada com espaços ("abcd efgh ..."): tiramos.
        smtp.login(config.gmail_remetente, config.gmail_senha_de_app.replace(" ", ""))
        smtp.send_message(msg)
