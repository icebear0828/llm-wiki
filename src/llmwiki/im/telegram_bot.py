from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from urllib.parse import urlparse

from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from llmwiki.im.common import IncomingMessage, ingest
from llmwiki.im.config import ImConfig
from llmwiki.vault import Vault

logger = logging.getLogger(__name__)

_TASK_COMMANDS: tuple[str, ...] = ("audio", "report", "slides", "video", "flashcards")

_HELP_TEXT = (
    "llmwiki bot — send text/URL/file/voice and I'll ingest it.\n"
    "Commands:\n"
    "  /note <text>          plain text note\n"
    "  /audio <text|url>     ingest with task/audio\n"
    "  /report <text|url>    ingest with task/report\n"
    "  /slides <text|url>    ingest with task/slides\n"
    "  /video <text|url>     ingest with task/video\n"
    "  /flashcards <text|url> ingest with task/flashcards"
)


def _is_url(text: str) -> bool:
    stripped = text.strip()
    if not stripped or any(c.isspace() for c in stripped):
        return False
    try:
        parsed = urlparse(stripped)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _source_for(user_id: int | None) -> str:
    return f"telegram:{user_id}" if user_id is not None else "telegram:unknown"


def _relpath(path: Path, vault: Vault) -> str:
    try:
        return str(path.relative_to(vault.root))
    except ValueError:
        return str(path)


class TelegramBot:
    def __init__(self, vault: Vault, cfg: ImConfig) -> None:
        if not cfg.telegram.bot_token:
            raise ValueError("telegram.bot_token is empty (set LLMWIKI_TG_TOKEN)")
        self.vault = vault
        self.cfg = cfg
        self._app: Application | None = None  # type: ignore[type-arg]

    # --- authorization -----------------------------------------------------
    # allowed_user_ids empty == open to anyone (documented default).
    def _authorized(self, user_id: int | None) -> bool:
        allowed = self.cfg.telegram.allowed_user_ids
        if not allowed:
            return True
        return user_id is not None and user_id in allowed

    # --- ingest helpers ----------------------------------------------------
    async def _do_ingest_and_reply(
        self,
        update: Update,
        msg: IncomingMessage,
    ) -> None:
        try:
            path = ingest(msg, self.vault, self.cfg)
        except Exception as e:  # noqa: BLE001
            logger.exception("ingest failed")
            if update.effective_message is not None:
                await update.effective_message.reply_text(f"❌ ingest failed: {e}")
            return
        rel = _relpath(path, self.vault)
        if update.effective_message is not None:
            await update.effective_message.reply_text(f"✅ ingested as {rel}")

    async def _reject_if_unauthorized(self, update: Update) -> bool:
        user = update.effective_user
        uid = user.id if user is not None else None
        if self._authorized(uid):
            return False
        if update.effective_message is not None:
            await update.effective_message.reply_text("unauthorized")
        return True

    # --- handlers ----------------------------------------------------------
    async def handle_text(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        message = update.effective_message
        if message is None or message.text is None:
            return
        user = update.effective_user
        uid = user.id if user is not None else None
        text = message.text
        if _is_url(text):
            msg = IncomingMessage(
                kind="url",
                url=text.strip(),
                source=_source_for(uid),
            )
        else:
            msg = IncomingMessage(
                kind="text",
                text=text,
                source=_source_for(uid),
            )
        await self._do_ingest_and_reply(update, msg)

    async def handle_document(
        self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE
    ) -> None:
        if await self._reject_if_unauthorized(update):
            return
        message = update.effective_message
        if message is None or message.document is None:
            return
        doc = message.document
        user = update.effective_user
        uid = user.id if user is not None else None
        suffix = Path(doc.file_name or "file").suffix
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
        tg_file = await doc.get_file()
        await tg_file.download_to_drive(custom_path=str(tmp_path))
        if doc.file_name:
            renamed = tmp_path.with_name(doc.file_name)
            try:
                tmp_path.replace(renamed)
                tmp_path = renamed
            except OSError:
                pass
        msg = IncomingMessage(
            kind="file",
            file_path=tmp_path,
            source=_source_for(uid),
            title=doc.file_name,
        )
        await self._do_ingest_and_reply(update, msg)

    async def handle_photo(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        message = update.effective_message
        if message is None or not message.photo:
            return
        user = update.effective_user
        uid = user.id if user is not None else None
        photo = message.photo[-1]
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp:
            tmp_path = Path(tmp.name)
        tg_file = await photo.get_file()
        await tg_file.download_to_drive(custom_path=str(tmp_path))
        msg = IncomingMessage(
            kind="file",
            file_path=tmp_path,
            source=_source_for(uid),
        )
        await self._do_ingest_and_reply(update, msg)

    async def handle_voice(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        message = update.effective_message
        if message is None or message.voice is None:
            return
        user = update.effective_user
        uid = user.id if user is not None else None
        voice = message.voice
        with tempfile.NamedTemporaryFile(delete=False, suffix=".ogg") as tmp:
            tmp_path = Path(tmp.name)
        tg_file = await voice.get_file()
        await tg_file.download_to_drive(custom_path=str(tmp_path))
        msg = IncomingMessage(
            kind="voice",
            voice_path=tmp_path,
            source=_source_for(uid),
            tags=["task/voice"],
        )
        await self._do_ingest_and_reply(update, msg)

    async def handle_help(self, update: Update, _ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        if update.effective_message is not None:
            await update.effective_message.reply_text(_HELP_TEXT)

    async def handle_note(self, update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
        if await self._reject_if_unauthorized(update):
            return
        message = update.effective_message
        if message is None:
            return
        body = _command_argument(message.text or "", ctx.args)
        if not body:
            await message.reply_text("usage: /note <text>")
            return
        user = update.effective_user
        uid = user.id if user is not None else None
        msg = IncomingMessage(
            kind="text",
            text=body,
            source=_source_for(uid),
        )
        await self._do_ingest_and_reply(update, msg)

    def _make_task_handler(self, name: str):  # noqa: ANN202
        async def handler(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
            if await self._reject_if_unauthorized(update):
                return
            message = update.effective_message
            if message is None:
                return
            body = _command_argument(message.text or "", ctx.args)
            if not body:
                await message.reply_text(f"usage: /{name} <text-or-url>")
                return
            user = update.effective_user
            uid = user.id if user is not None else None
            tag = f"task/{name}"
            extra = list(self.cfg.telegram.command_default_tags.get(name, []))
            tags = [tag] + [t for t in extra if t != tag]
            if _is_url(body):
                msg = IncomingMessage(
                    kind="url",
                    url=body.strip(),
                    source=_source_for(uid),
                    tags=tags,
                )
            else:
                msg = IncomingMessage(
                    kind="text",
                    text=body,
                    source=_source_for(uid),
                    tags=tags,
                )
            await self._do_ingest_and_reply(update, msg)

        return handler

    # --- lifecycle ---------------------------------------------------------
    def build_application(self) -> Application:  # type: ignore[type-arg]
        application: Application = (  # type: ignore[type-arg]
            ApplicationBuilder().token(self.cfg.telegram.bot_token).build()
        )
        application.add_handler(CommandHandler(["start", "help"], self.handle_help))
        application.add_handler(CommandHandler("note", self.handle_note))
        for name in _TASK_COMMANDS:
            application.add_handler(CommandHandler(name, self._make_task_handler(name)))
        application.add_handler(MessageHandler(filters.VOICE, self.handle_voice))
        application.add_handler(MessageHandler(filters.PHOTO, self.handle_photo))
        application.add_handler(MessageHandler(filters.Document.ALL, self.handle_document))
        application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text)
        )
        return application

    async def start(self) -> None:
        if self._app is not None:
            return
        application = self.build_application()
        await application.initialize()
        await application.start()
        if application.updater is None:
            raise RuntimeError("Application has no updater (polling unavailable)")
        await application.updater.start_polling()
        self._app = application

    async def stop(self) -> None:
        if self._app is None:
            return
        application = self._app
        try:
            if application.updater is not None and application.updater.running:
                await application.updater.stop()
        finally:
            try:
                await application.stop()
            finally:
                await application.shutdown()
                self._app = None

    async def run_forever(self) -> None:
        import asyncio

        await self.start()
        try:
            await asyncio.Event().wait()
        finally:
            await self.stop()


def _command_argument(text: str, args: list[str] | None) -> str:
    if args:
        joined = " ".join(args).strip()
        if joined:
            return joined
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return ""
    return parts[1].strip()
