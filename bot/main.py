import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from . import config, db as D
from .handlers import router
from .extras import router as extras_router, scheduler


async def main():
    logging.basicConfig(level=logging.INFO)
    db = await D.connect()
    dp = Dispatcher(storage=MemoryStorage(), db=db)
    dp.include_router(router)
    dp.include_router(extras_router)
    bot = Bot(config.BOT_TOKEN)
    task = asyncio.create_task(scheduler(bot, db))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
