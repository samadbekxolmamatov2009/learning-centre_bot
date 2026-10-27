# O'quv markaz boti

Telegram bot (aiogram 3): direktor / admin / o'qituvchi rollari. Ma'lumotlar bazasi: **Turso** (yoki lokal SQLite).

## Render sozlamalari
Mini App (davomat sahifasi va panel) ishlashi uchun **Web Service** kerak (Background Worker emas):
- Type: **Web Service** (pullik reja, bepul reja uxlab qoladi va bot to'xtaydi)
- Build: `pip install -r requirements.txt`
- Start: `python -m bot.main`
- Env: `BOT_TOKEN`, `DIRECTOR_IDS`, `TURSO_DATABASE_URL`, `TURSO_AUTH_TOKEN`, `PYTHON_VERSION=3.11.9`
- `PORT` va `RENDER_EXTERNAL_URL` ni Render o'zi beradi. Mini App manzili avtomatik olinadi
  (kerak bo'lsa `WEBAPP_URL=https://nom.onrender.com` deb qo'lda yozing).
- Health check path: `/`
- Background Worker sifatida ham ishlaydi, faqat Mini App tugmalari chiqmaydi (davomat chatda belgilanadi).

## Turso olish
```
turso db create markaz
turso db show markaz --url        # -> TURSO_DATABASE_URL
turso db tokens create markaz     # -> TURSO_AUTH_TOKEN
```
(Yoki turso.tech dashboard orqali.) Jadvallar bot birinchi ishga tushganda o'zi yaratiladi.
Turso o'rnatilmasa lokal `DB_PATH` (SQLite) ishlatiladi - Render'da deploydan keyin o'chib ketadi.

## Imkoniyatlar
- **Direktor**: o'qituvchi (foiz / o'quvchi boshiga: stavkaning 2 baravarigacha to'lagan o'quvchidan to'lovning 40%, undan ko'pidan stavka) va admin qo'shish, oyliklar, admin funksiyalari.
- **Admin**: guruh, o'quvchi qo'shish; to'lov kiritish va bekor qilish; o'quvchini ko'chirish; guruh/o'qituvchi/o'quvchini o'chirish; guruh o'qituvchisini almashtirish; qarzdorlar; oylik hisobot (o'tgan oylar ham).
- O'quvchining telefon raqami saqlanadi: qarzdorlar ro'yxati, davomat xabari va PDF'da ko'rinadi; "📞 Telefonni o'zgartirish" tugmasi bor.
- **O'qituvchi**: o'z guruhiga o'quvchi qo'shish/o'chirish, davomat (PDF adminga), oylik (o'tgan oylar ham), barcha guruhlari qarzdorlari.
- Oy oxirgi kuni (Toshkent vaqti bilan 09:00) admin va direktorga qarzdorlar ro'yxati avtomatik yuboriladi.
- To'lov summasi qanday bo'lishidan qat'i nazar, shu oy uchun o'quvchi qarzdor emas; yangi oyda qayta qarzdor.
- **Qidirish** (hamma): ism/familiya/telefon bo'yicha; o'qituvchi faqat o'z guruhlarida qidiradi.
- **Excel** (admin, direktor): qarzdorlar, barcha o'quvchilar, oylik hisobot (.xlsx).
- **Statistika** (direktor): tushum, oylik, o'quvchilar, qarzdorlik va davomat foizi.
- **Reyestr o'quvchilari** (kam ta'minlangan oila, davlat to'laydi): o'quvchi qo'shishda admin/direktor "🏛 Reyestr" ni tanlaydi. Bitta dars narxi **o'qituvchi ma'lumotida** (reyestr narxi) saqlanadi, har o'qituvchida har xil bo'lishi mumkin. Davomatda kelgan har bir dars uchun shu narx (dars paytidagi) o'qituvchi oyligiga **100%** qo'shiladi. Reyestr o'quvchisi qarzdor hisoblanmaydi. "🏛 Reyestr belgilash" - mavjud o'quvchini reyestr/oddiy qilish.
- **Reyestrni yashirish/ochish** (direktor): yashirilgan reyestr o'quvchilar ro'yxat, davomat, qarzdor va hisobda ko'rinmaydi. Yashirin rejimda yangi qo'shilgan reyestr o'quvchilar ham yashirin bo'ladi. Ochilgan kundan hisoblanadi.
- **O'qituvchini tahrirlash** (direktor): ism, oylik turi/qiymati, reyestr dars narxi.
- **Fayldan yuklash** (admin, direktor, o'qituvchi - o'z guruhi): guruhni tanlab, Excel (.xlsx) yoki Word (.docx) fayl yuboriladi, o'quvchilar shu guruhga oddiy (reyestrsiz) bo'lib qo'shiladi. Ustunlar: Familiya, Ism, Sinf, Telefon (sarlavhasiz ham bo'ladi). Takrorlar o'tkazib yuboriladi, xatolar ro'yxati beriladi.

## Mini App va yangi interfeys
- **Davomat Mini App** (o'qituvchi): "✅ Davomat" -> sahifa ochiladi. Har o'quvchi yonida oxirgi 3 ta dars (sana + belgi),
  qaysi kunlari kelmagani, 2 marta kelmagan bo'lsa ogohlantirish, telefon qo'ng'irog'i tugmasi. Holatlar:
  ✅ keldi, ❌ kelmadi, 🕒 kechikdi, 📝 sababli. O'tgan kun davomatini ham tuzatish mumkin. Saqlanganda adminga PDF boradi.
- **Panel** (admin/direktor): tushum, qarzdorlar, davomat, 6 oylik grafik, guruhlar bo'yicha ko'rsatkichlar.
- **O'quvchilar bo'limi (Mini App)** (hamma, pastki "O'quvchilar" tab): guruh tanlab yoki qidirib o'quvchini topish,
  **bitta formada** yangi o'quvchi qo'shish (ism, familiya, sinf, telefon, guruh, admin/direktorga reyestr belgisi),
  qo'shgandan keyin forma guruh/sinfni saqlab, faqat ism-familiyani tozalab, ketma-ket tez qo'shishga imkon beradi.
  O'quvchi kartochkasida: to'lov kiritish, tahrirlash, boshqa guruhga ko'chirish, o'chirish. Admin/direktor shu yerdan
  yangi guruh ham yarata oladi (nomi + o'qituvchi).
- Autentifikatsiya: Telegram `initData` imzosi (BOT_TOKEN bilan HMAC), rol bazadan olinadi.
- Menyu bo'limlarga bo'lingan (O'quvchilar, Moliya, Guruh boshqaruvi, Hisobotlar, Xodimlar), `🏠 Asosiy menyu` tugmasi.
- Guruhlar: o'qituvchi -> guruh -> o'quvchi -> kartochka (bitta xabar tahrirlanadi), sahifalash, davomat tarixi.
- **Dars jadvali** (🗓): dars kunlari va vaqti; davomat olinmasa o'qituvchiga (20 daqiqadan keyin) va adminga (2 soatdan keyin) eslatma.
- Vaqt Toshkent bo'yicha (`TZ_OFFSET=5`).
