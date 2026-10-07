# O'quv markaz boti

Telegram bot (aiogram 3): direktor / admin / o'qituvchi rollari. Ma'lumotlar bazasi: **Turso** (yoki lokal SQLite).

## Render sozlamalari
- Type: Background Worker
- Build: `pip install -r requirements.txt`
- Start: `python -m bot.main`
- Env: `BOT_TOKEN`, `DIRECTOR_IDS`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `PYTHON_VERSION=3.11.9`

## Turso olish
```
turso db create markaz
turso db show markaz --url        # -> TURSO_DATABASE_URL
turso db tokens create markaz     # -> TURSO_AUTH_TOKEN
```
(Yoki turso.tech dashboard orqali.) Jadvallar bot birinchi ishga tushganda o'zi yaratiladi.
Turso o'rnatilmasa lokal `DB_PATH` (SQLite) ishlatiladi - Render'da deploydan keyin o'chib ketadi.

## Imkoniyatlar
- **Direktor**: o'qituvchi (foiz / o'quvchi boshiga) va admin qo'shish, oyliklar, admin funksiyalari.
- **Admin**: guruh, o'quvchi qo'shish; to'lov kiritish va bekor qilish; o'quvchini ko'chirish; guruh/o'qituvchi/o'quvchini o'chirish; guruh o'qituvchisini almashtirish; qarzdorlar; oylik hisobot (o'tgan oylar ham).
- O'quvchining telefon raqami saqlanadi: qarzdorlar ro'yxati, davomat xabari va PDF'da ko'rinadi; "📞 Telefonni o'zgartirish" tugmasi bor.
- **O'qituvchi**: o'z guruhiga o'quvchi qo'shish/o'chirish, davomat (PDF adminga), oylik (o'tgan oylar ham), barcha guruhlari qarzdorlari.
- Oy oxirgi kuni (Toshkent vaqti bilan 09:00) admin va direktorga qarzdorlar ro'yxati avtomatik yuboriladi.
- To'lov summasi qanday bo'lishidan qat'i nazar, shu oy uchun o'quvchi qarzdor emas; yangi oyda qayta qarzdor.
