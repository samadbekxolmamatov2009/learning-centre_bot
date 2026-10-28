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
- O'quvchi kartochkasida **to'lovlar tarixi** (oxirgi 10 ta) va admin/direktor uchun **to'lovni bekor qilish**.
- Guruh va qidiruv ro'yxatlarida **"❌ Faqat qarzdorlar"** filtri, guruh kartochkasida qarzdorlar soni darhol ko'rinadi.
- O'qituvchi uchun pastki **"💰 Oylik"** tab: oy tanlab (oxirgi 6 oy), guruh-guruh tushum/to'laganlar, reyestr va jami oylik.
  Har bir guruh uchun qarzdorlar foizi va davomat foizi taqqoslab ko'rsatiladi,
  "eng yaxshi davomat" va "eng ko'p qarzdor" guruh alohida ajratib chiqariladi.
- Direktorga pastki **"👨‍🏫 Xodimlar"** tab: o'qituvchi qo'shish/tahrirlash/o'chirish, admin qo'shish/o'chirish, reyestr yashirish/ochish.
- Panelda **"📥"** tugmasi: qarzdorlar, barcha o'quvchilar va oylik hisobotni .xlsx qilib to'g'ridan-to'g'ri telefonga yuklab olish.
- Guruh kartochkasidagi **"⚙️"** (admin/direktor): guruh nomini o'zgartirish, o'qituvchisini almashtirish, guruhni o'chirish.
- Davomatda **"Hammasi ❌"** tezkor tugmasi (bayram va h.k. uchun).
- **🔔 Bildirishnomalar**: davomat olinmagan guruhlar, qarzdorlar, reyestr narxi kiritilmagan o'qituvchilar — bitta ro'yxatda, bosib tegishli joyga o'tiladi. Belgi raqami Panel/Davomat sahifasida ko'rinadi.
- **Tuzatilgan xato:** qarzdorlar soni (guruh kartochkasi va bildirishnomada) oyning birinchi kunlarida, hali hech kim to'lov qilmagan paytda, noto'g'ri "0" ko'rsatayotgan edi.
- Autentifikatsiya: Telegram `initData` imzosi (BOT_TOKEN bilan HMAC), rol bazadan olinadi.
- Menyu bo'limlarga bo'lingan (O'quvchilar, Moliya, Guruh boshqaruvi, Hisobotlar, Xodimlar), `🏠 Asosiy menyu` tugmasi.
- Guruhlar: o'qituvchi -> guruh -> o'quvchi -> kartochka (bitta xabar tahrirlanadi), sahifalash, davomat tarixi.
- **Dars jadvali** (🗓): dars kunlari va vaqti; davomat olinmasa o'qituvchiga (20 daqiqadan keyin) va adminga (2 soatdan keyin) eslatma.
- Vaqt Toshkent bo'yicha (`TZ_OFFSET=5`).

## Ota-onalar uchun (faqat ko'rish)
O'quvchi kartochkasida (chatda "📚 Guruhlar" -> o'quvchi, yoki Mini App'da "👪 Ota-onaga havola") maxsus havola
yaratiladi. Ota-ona shu havolani bosib botni ochsa, `/parent` Mini App sahifasida farzandining sinfi, guruhi,
shu oy to'lov holati va oxirgi darslar davomati ko'rinadi — hech narsani o'zgartira olmaydi. Bir nechta farzand
bo'lsa, hammasi ro'yxatda chiqadi. Havola doimiy ishlaydi (muddati tugamaydi), istalgan vaqt qayta yuborilishi mumkin.
Havolani **kim bossa, o'sha ota-ona sifatida bog'lanadi** — tizim bu kishi haqiqiy ota-ona ekanligini tekshirmaydi,
shuning uchun havolani faqat haqiqiy ota-onaga yuborish kerak. Buning uchun havola yonida **"📤 Telegramda ulashish"**
(Telegramning o'z ulashish oynasi orqali to'g'ridan-to'g'ri kerakli kishiga yuboriladi) va, agar o'quvchining telefon
raqami kiritilgan bo'lsa, **"💬 WhatsApp'da yuborish"** tugmalari bor (WhatsApp'da shu raqamga tayyor xabar bilan ochiladi).

## Chat menyusi (WEBAPP_URL o'rnatilganda)
Mini App to'liq ishlayotgan bo'lsa, chat menyusi bitta tugmaga qisqaradi: **"📱 Ilovani ochish"**.
Hamma funksiya (davomat, o'quvchilar, moliya, xodimlar, dars jadvali) Mini App ichida.
`WEBAPP_URL` o'rnatilmagan bo'lsa (Background Worker holatida), bot avtomatik eski, to'liq chat menyusiga qaytadi -
hech narsa buzilmaydi, faqat qulaylik yo'qoladi.

## Nazorat/sinov natijalari
O'quvchilar bo'limida guruh ichida **"📝"** tugmasi (nazorat natijalari). O'qituvchi/admin/direktor
yangi nazorat yaratadi (nomi, maksimal ball, sana), so'ng shu guruhdagi hamma o'quvchiga baho kiritadi
(bitta ekranda, ketma-ket). Har bir nazorat uchun guruh o'rtacha balli ko'rinadi. O'quvchi kartochkasida
oxirgi 10 ta nazorat natijasi ko'rinadi. Ota-ona sahifasida ham farzandining oxirgi 5 ta nazorat
natijasi chiqadi.

## To'lov cheki
Har bir to'lov kiritilganda (chatda ham, Mini App'da ham) avtomatik PDF chek yaratiladi: markaz nomi, o'quvchi,
sinf, guruh, oy, sana, kim qabul qildi, summa. Chek kiritgan admin/o'qituvchiga va o'sha o'quvchiga bog'langan
barcha ota-onalarga yuboriladi. Markaz nomini `CENTER_NAME` muhit o'zgaruvchisi orqali o'zgartirish mumkin
(standart: "O'quv markazi").
