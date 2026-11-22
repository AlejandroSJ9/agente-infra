"""
Bot de Telegram (long polling: el bot pregunta a Telegram si hay mensajes; no abre puertos).

    docker compose up -d bot
    docker compose logs -f bot

Protecciones:
    - Una respuesta a la vez (el modelo en CPU atiende de a una); los demás esperan su turno.
    - Límite por usuario: MAX_PREGUNTAS_POR_MINUTO (cuida CPU y créditos de OpenRouter).
    - Preguntas de máximo MAX_CARACTERES.
    - En las trazas, el usuario se guarda como un hash, no con su ID de Telegram.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import os
import re
import time
from collections import defaultdict, deque

from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.error import BadRequest
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

from agente.agente import crear_agente_desde_entorno

MAX_CARACTERES = 500
MAX_PREGUNTAS_POR_MINUTO = 5

logging.basicConfig(format="%(asctime)s %(levelname)s %(name)s: %(message)s", level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)       # no registrar URLs con el token
log = logging.getLogger("bot")

BIENVENIDA = (
    "👋 Hola, soy el asistente de <b>Infraestructura de TI</b>.\n\n"
    "Respondo dudas de la materia citando los documentos del curso, y calculo subredes IPv4 "
    "(con humor ácido incluido, sin costo adicional).\n\n"
    "Prueba con:\n"
    "• ¿Qué es el teorema CAP?\n"
    "• ¿Por qué la red no es confiable?\n"
    "• haz VLSM de 10.0.0.0/24 para 50, 20 y 10 hosts\n"
    "• divide 172.31.0.0/16 de mi VPC de AWS en 4 subredes\n\n"
    "Ojo: pienso en CPU, así que tardo unos 30 segundos. Como las buenas respuestas en una relación. ⏳"
)


def a_html(texto: str) -> str:
    """El modelo escribe **negritas** estilo Markdown; Telegram recibe HTML seguro."""
    return re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", html.escape(texto), flags=re.DOTALL)


def usuario_anonimo(user_id: int) -> str:
    return hashlib.sha256(f"agente-infra:{user_id}".encode()).hexdigest()[:10]


class LimitePorUsuario:
    def __init__(self, maximo: int, ventana_s: float = 60):
        self.maximo, self.ventana = maximo, ventana_s
        self.historial: dict[int, deque] = defaultdict(deque)

    def permitir(self, user_id: int) -> bool:
        ahora, h = time.monotonic(), self.historial[user_id]
        while h and ahora - h[0] > self.ventana:
            h.popleft()
        if len(h) >= self.maximo:
            return False
        h.append(ahora)
        return True


async def _escribiendo(chat, parar: asyncio.Event) -> None:
    """Telegram borra el 'escribiendo…' a los ~5 s: se reenvía cada 4 s mientras el agente trabaja."""
    while not parar.is_set():
        try:
            await chat.send_action(ChatAction.TYPING)
        except Exception:
            pass
        try:
            await asyncio.wait_for(parar.wait(), timeout=4)
        except asyncio.TimeoutError:
            pass


async def _enviar(update: Update, texto: str) -> None:
    try:
        await update.message.reply_text(a_html(texto), parse_mode=ParseMode.HTML)
    except BadRequest:                                   # si el HTML no le gusta a Telegram, va como texto plano
        await update.message.reply_text(texto)


def main() -> None:
    token = os.environ["TELEGRAM_TOKEN"]
    agente = crear_agente_desde_entorno()
    turno = asyncio.Semaphore(1)
    limite = LimitePorUsuario(MAX_PREGUNTAS_POR_MINUTO)

    async def inicio(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        await update.message.reply_text(BIENVENIDA, parse_mode=ParseMode.HTML)

    async def mensaje(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        pregunta = (update.message.text or "").strip()
        user_id = update.effective_user.id
        if len(pregunta) > MAX_CARACTERES:
            await update.message.reply_text(f"Uf, eso es más largo que mensaje de ex arrepentido. "
                                            f"Máximo {MAX_CARACTERES} caracteres, por favor. ✂️")
            return
        if not limite.permitir(user_id):
            await update.message.reply_text("Calma, que no soy tu crush para contestarte al instante. "
                                            "Espera un minuto y me vuelves a escribir. ⏳")
            return
        if turno.locked():
            await update.message.reply_text("Estoy atendiendo otra pregunta; quedas en la fila. 🙋")

        parar = asyncio.Event()
        animacion = asyncio.create_task(_escribiendo(update.effective_chat, parar))
        try:
            async with turno:
                r = await asyncio.to_thread(agente.responder, pregunta, "telegram", usuario_anonimo(user_id))
            log.info("traza=%s tipo=%s total_ms=%s", r["traza"]["id"], r["traza"]["decision"]["tipo"],
                     r["traza"]["tiempos"]["total_ms"])
            await _enviar(update, r["texto"])
        except Exception:
            log.exception("Error respondiendo")
            await update.message.reply_text("Algo se rompió de mi lado (no fuiste tú, fui yo). 💔 Intenta de nuevo.")
        finally:
            parar.set()
            await animacion

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "ayuda"], inicio))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, mensaje))
    log.info("Bot iniciado (long polling)")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
