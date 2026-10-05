import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from . import config, db as D
from .handlers import router


async def main():
    logging.basicConfig(level=logging.INFO)
    db = await D.connect()
    dp = Dispatcher(storage=MemoryStorage(), db=db)
    dp.include_router(router)
    await dp.start_polling(Bot(config.BOT_TOKEN))


if __name__ == "__main__":
    asyncio.run(main())
