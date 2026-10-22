"""Entry point: wires together the bot, dispatcher, database and scheduler."""
from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import load_config
from app.database.base import Database
from app.handlers import get_routers
from app.middlewares import DatabaseMiddleware
from app.services.scheduler import ReminderScheduler
from app.utils import setup_logging

logger = logging.getLogger(__name__)


async def main() -> None:
    setup_logging()
    config = load_config()

    bot = Bot(
        token=config.token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    database = Database(config.database_url)
    await database.create_all()

    scheduler = ReminderScheduler(bot, database, config.default_timezone)

    dispatcher = Dispatcher()
    dispatcher["scheduler"] = scheduler
    db_mw = DatabaseMiddleware(database, config.default_timezone)
    dispatcher.message.middleware(db_mw)
    dispatcher.callback_query.middleware(db_mw)
    dispatcher.include_routers(*get_routers())

    await scheduler.start()
    logger.info("Toddy is up")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dispatcher.start_polling(bot)
    finally:
        scheduler.shutdown()
        await database.dispose()
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Toddy stopped")
