# O'quv markaz boti

Telegram bot (aiogram 3 + SQLite): direktor / admin / o'qituvchi rollari.

## Ishga tushirish
```
pip install -r requirements.txt
export BOT_TOKEN=... DIRECTOR_IDS=123456789
python -m bot.main
```

## Imkoniyatlar
- **Direktor**: o'qituvchi qo'shish (foiz yoki o'quvchi boshiga), admin qo'shish, barcha oyliklar, admin funksiyalari.
- **Admin**: guruh, o'quvchi (ism, familiya, sinf, guruh) qo'shish, to'lov kiritish (har qanday summa = shu oy uchun qarzdor emas, yangi oyda qayta qarzdor), qarzdorlar, guruh tushumi.
- **O'qituvchi**: davomat (kelmaganlarni belgilab yuborish -> adminlarga PDF), oylikni ko'rish, o'z guruhi qarzdorlari.
