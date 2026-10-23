import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from . import config, db as D
from .browse import router as browse_router
from .extras import router as extras_router, scheduler
from .handlers import router
from .webapp import start_server

log = logging.getLogger(__name__)


async def setup_bot(bot: Bot):
    """Buyruqlar menyusi va bot tavsifi (xato bo'lsa bot to'xtamaydi)."""
    try:
        await bot.set_my_commands([
            BotCommand(command="start", description="Asosiy menyu"),
            BotCommand(command="menu", description="Menyuni ochish"),
            BotCommand(command="davomat", description="Davomat olish (o'qituvchi)"),
            BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
        ])
        await bot.set_my_short_description("O'quv markaz: davomat, to'lov, hisobotlar")
        await bot.set_my_description("O'quv markaz boti: o'quvchilar, davomat, to'lovlar va oyliklar. "
                                     "Boshlash uchun /start ni bosing.")
    except Exception:
        log.warning("Bot sozlamalarini o'rnatib bo'lmadi", exc_info=True)


async def main():
    logging.basicConfig(level=logging.INFO)
    db = await D.connect()
    dp = Dispatcher(storage=MemoryStorage(), db=db)
    dp.include_router(router)
    dp.include_router(extras_router)
    dp.include_router(browse_router)

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
    await setup_bot(bot)
    runner = await start_server(db, bot, config.PORT) if config.PORT else None  # Render Web Service
    task = asyncio.create_task(scheduler(bot, db))
    try:
        await dp.start_polling(bot)
    finally:
        task.cancel()
        if runner:
            await runner.cleanup()
        await db.close()


if __name__ == "__main__":
    asyncio.run(main())
