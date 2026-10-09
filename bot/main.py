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
    @dp.errors()
    async def on_error(event):
        logging.exception("Handler xatosi", exc_info=event.exception)
        upd = event.update
        target = upd.callback_query or upd.message
        try:
            if upd.callback_query:
                await upd.callback_query.answer("Xatolik yuz berdi, qaytadan urinib ko'ring.", show_alert=True)
            elif target:
                await target.answer("Xatolik yuz berdi, qaytadan urinib ko'ring.")
        except Exception:
            pass
        return True

    bot = Bot(config.BOT_TOKEN)
    task = asyncio.create_task(scheduler(bot, db))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
