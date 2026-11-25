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
- **To'lov kiritishda tavsiya etilgan summa**: o'quvchining sinfiga qarab (11-sinf: 600 000, 10-sinf: 550 000,
  9-sinf: 500 000, 8/7-sinf: 450 000, 6/5-sinf: 400 000 so'm) tavsiya ko'rsatiladi - "✅ ... so'm to'landi"
  tugmasini bossa, programma shu summa to'landi deb hisoblaydi. Agar summa boshqacha bo'lsa, "✏️ Boshqa summa
  kiritish" tugmasi orqali istalgan summa qo'lda kiritiladi. Boshqa sinflar uchun tavsiya ko'rsatilmaydi, to'g'ridan-to'g'ri summa so'raladi. Chat va Mini App'da ham ishlaydi.
- **O'qituvchi**: o'z guruhiga o'quvchi qo'shish, davomat (PDF adminga), oylik (o'tgan oylar ham), barcha guruhlari qarzdorlari. **To'lov kiritish huquqi yo'q** - faqat admin va direktor to'lov kirita oladi (Mini App'da ham, chatda ham); bu qoida ataylab shunday - o'qituvchi pul yig'ib, o'zi tizimga kiritib qo'yishiga yo'l qo'yilmaydi. **O'quvchini o'chirish huquqi ham yo'q** - xuddi shu sababda, faqat admin/direktor o'quvchini o'chira oladi (Mini App'da ham, chatda ham).
- **Oylik hisob-kitobi va hisobotlar doimiy saqlanadi**: agar o'quvchi biror oy uchun to'lov qilgandan keyin
  guruhdan chiqarilsa/o'chirilsa (masalan keyingi oy boshida), o'sha o'tgan oyning o'qituvchi oyligi
  **o'zgarmaydi** — "o'quvchi boshiga" turidagi oylik ham, Excel hisobotlar ham, shu jumladan, to'g'ridan-to'g'ri
  to'lovlar yozuvidan hisoblanadi, o'quvchi hozir ro'yxatda bor-yo'qligidan qat'i nazar. Xuddi shunday, agar
  **butun guruh** o'chirilsa va unda to'lov/davomat tarixi bo'lsa, guruh butunlay o'chirilmaydi, balki nomi
  o'zgartirilib (masalan "G1 (arxiv, 2026-12-05)") **arxivlanadi** — shunda o'tgan oylardagi o'qituvchi oyligi,
  reyestr hisobi va Excel hisobotlar to'liq saqlanadi, va asl nom (masalan "G1") bo'shab qoladi, keyinroq xuddi
  shu nomda yangi guruh ochish mumkin. Arxivlangan guruhlar kundalik ro'yxatlarda (guruhlar sahifasi, bugungi
  davomat, bildirishnomalar) ko'rinmaydi, faqat tarixiy hisob-kitoblarda inobatga olinadi. Hech qanday to'lov/
  davomat tarixi bo'lmagan bo'sh guruh oldingidek butunlay o'chiriladi.
- Oy oxirgi kuni (Toshkent vaqti bilan 09:00) admin va direktorga qarzdorlar ro'yxati avtomatik yuboriladi.
- To'lov summasi qanday bo'lishidan qat'i nazar, shu oy uchun o'quvchi qarzdor emas; yangi oyda qayta qarzdor.
- **Qidirish** (hamma): ism/familiya/telefon bo'yicha; o'qituvchi faqat o'z guruhlarida qidiradi.
- **Excel** (admin, direktor): qarzdorlar, barcha o'quvchilar, oylik hisobot (.xlsx).
- **Statistika** (direktor): tushum, oylik, o'quvchilar, qarzdorlik va davomat foizi.
- **Reyestr o'quvchilari** (kam ta'minlangan oila, davlat to'laydi): o'quvchi qo'shishda "🏛 Reyestr" ni tanlash mumkin (admin, direktor va **o'qituvchi** ham - hammasiga so'raladi). Bitta dars narxi **o'qituvchi ma'lumotida** (reyestr narxi) saqlanadi, har o'qituvchida har xil bo'lishi mumkin. Davomatda kelgan har bir dars uchun shu narx (dars paytidagi) o'qituvchi oyligiga **100%** qo'shiladi va **o'sha kunga qarab doimiy saqlanadi** - keyinroq o'qituvchining reyestr narxi oshirilsa/tushirilsa ham, o'tgan kunlardagi (allaqachon "keldi" deb belgilangan) yozuvlar narxi o'zgarmaydi, hatto o'sha eski kunning davomati keyinroq boshqa sababda (masalan bitta o'quvchini tuzatish uchun) qayta saqlansa ham. Reyestr o'quvchisi qarzdor hisoblanmaydi. "🏛 Reyestr belgilash" - mavjud o'quvchini reyestr/oddiy qilish (faqat admin/direktor, chunki mavjud o'quvchining holatini keyinroq o'zgartirish moliyaviy tarixga ta'sir qiladi).
- **Reyestrni yashirish/ochish** (direktor): yashirilgan reyestr o'quvchilar ro'yxat, davomat, qarzdor va hisobda ko'rinmaydi. Yashirin rejimda yangi qo'shilgan reyestr o'quvchilar ham yashirin bo'ladi. Ochilgan kundan hisoblanadi.
- **O'qituvchini tahrirlash** (direktor): ism, oylik turi/qiymati, reyestr dars narxi. Oylik qiymati **0** ham
  bo'lishi mumkin (masalan markaz boshlig'i o'zi ham bir guruhni olib borsa, lekin oylik olmasa) - bunday
  o'qituvchining oyligi doim 0 bo'lib hisoblanadi, guruh/o'quvchi soni va boshqa hisob-kitoblarga ta'sir qilmaydi.
- **Fayldan yuklash** (admin, direktor, o'qituvchi - o'z guruhi): guruhni tanlab, Excel (.xlsx) yoki Word (.docx) fayl yuboriladi, o'quvchilar shu guruhga oddiy (reyestrsiz) bo'lib qo'shiladi. Ustunlar: Familiya, Ism, Sinf, Telefon (sarlavhasiz ham bo'ladi). Takrorlar o'tkazib yuboriladi, xatolar ro'yxati beriladi.

## Mini App va yangi interfeys
- **Davomat Mini App** (o'qituvchi): "✅ Davomat" -> sahifa ochiladi. Har o'quvchi yonida oxirgi 3 ta dars (sana + belgi),
  qaysi kunlari kelmagani, telefon qo'ng'irog'i tugmasi. Oxirgi **2 hafta** ichida 2 yoki undan ko'p marta kelmagan bo'lsa
  ogohlantirish chiqadi (faqat oxirgi 3 ta darsga emas, 2 haftalik davrga qarab). "Batafsil" tugmasi orqali oxirgi 20 tagacha
  dars (taxminan 1 oy) ko'rinadi. Holatlar: ✅ keldi, ❌ kelmadi, 🕒 kechikdi, 📝 sababli. O'tgan kun davomatini ham
  tuzatish mumkin. Saqlanganda adminga PDF boradi, va **"❌ Kelmadi"** yoki **"🕒 Kechikdi"** deb belgilangan har bir
  o'quvchining ulangan ota-onasiga avtomatik Telegram xabari ketadi ("sababli" uchun bormaydi). Ota-onasi ulanmagan
  bo'lsa, shunchaki xabar yuborilmaydi (xato chiqmaydi).
- **Panel** (admin/direktor): tushum, qarzdorlar, davomat, 6 oylik grafik, guruhlar bo'yicha ko'rsatkichlar.
- **O'quvchilar bo'limi (Mini App)** (hamma, pastki "O'quvchilar" tab): guruh tanlab yoki qidirib o'quvchini topish,
  **bitta formada** yangi o'quvchi qo'shish (ism, familiya, sinf, telefon, guruh, admin/direktorga reyestr belgisi),
  qo'shgandan keyin forma guruh/sinfni saqlab, faqat ism-familiyani tozalab, ketma-ket tez qo'shishga imkon beradi.
  O'quvchi kartochkasida: to'lov kiritish, tahrirlash, boshqa guruhga ko'chirish, o'chirish. Admin/direktor shu yerdan
  yangi guruh ham yarata oladi (nomi + o'qituvchi). Admin va direktorga har bir guruh kartochkasida **"📝 Oxirgi
  davomat"** sanasi ham ko'rinadi - shu guruhda o'qituvchi oxirgi marta qachon davomat belgilaganini bildiradi
  (agar umuman olinmagan bo'lsa "hali olinmagan" deb ko'rsatiladi).
- O'quvchi kartochkasida **to'lovlar tarixi** (oxirgi 10 ta) va admin/direktor uchun **to'lovni bekor qilish**.
- Guruh va qidiruv ro'yxatlarida **"❌ Faqat qarzdorlar"** filtri, guruh kartochkasida qarzdorlar soni darhol ko'rinadi.
- O'qituvchi uchun pastki **"💰 Oylik"** tab: oy tanlab (oxirgi 6 oy), guruh-guruh tushum/to'laganlar, reyestr va jami oylik.
  Har bir guruh uchun qarzdorlar foizi va davomat foizi taqqoslab ko'rsatiladi,
  "eng yaxshi davomat" va "eng ko'p qarzdor" guruh alohida ajratib chiqariladi.
- Direktorga pastki **"👨‍🏫 Xodimlar"** tab: o'qituvchi qo'shish/tahrirlash/o'chirish, admin qo'shish/o'chirish, reyestr yashirish/ochish.
- Panelda **"📥"** tugmasi: qarzdorlar, barcha o'quvchilar va oylik hisobotni .xlsx qilib to'g'ridan-to'g'ri telefonga yuklab olish.
- Guruh kartochkasidagi **"⚙️"** (admin/direktor): guruh nomini o'zgartirish, o'qituvchisini almashtirish, guruhni o'chirish.
- O'quvchilar ro'yxatida (guruh ichida) **"📄"** tugmasi (faqat admin/direktor): shu guruhni **Word (.docx)** fayl qilib
  yuklab oladi — guruh nomi, o'qituvchi, dars kunlari/vaqti sarlavhada; jadvalda T/r, ism-sharifi, sinfi, telefoni
  avtomatik to'ldirilgan, "Kelgan sana", "Jami to'lov", "To'lagan summasi", "Sana" ustunlari bo'sh — qo'lda to'ldirish
  uchun (qog'ozdagi to'lov yig'ish ro'yxati o'rnini bosadi). Pastda yangi o'quvchi qo'shish uchun bir nechta bo'sh qator.
- **Fayl yuklab olish** (Excel va Word): Telegramning ichki brauzeri oddiy havola yuklashni to'g'ri ishlatmagani uchun,
  fayl havolasi qisqa muddatli (2 daqiqalik) token bilan alohida (tashqi) brauzerda ochiladi — shunda fayl haqiqatda
  qurilmaga yuklanadi, "havolani ochish" deb so'ramaydi.
- Davomatda **"Hammasi ❌"** tezkor tugmasi (bayram va h.k. uchun).
- **🔔 Bildirishnomalar**: davomat olinmagan guruhlar, qarzdorlar, reyestr narxi kiritilmagan o'qituvchilar — bitta ro'yxatda, bosib tegishli joyga o'tiladi. Belgi raqami Panel/Davomat sahifasida ko'rinadi.
- **Tuzatilgan xato:** qarzdorlar soni (guruh kartochkasi va bildirishnomada) oyning birinchi kunlarida, hali hech kim to'lov qilmagan paytda, noto'g'ri "0" ko'rsatayotgan edi.
- Autentifikatsiya: Telegram `initData` imzosi (BOT_TOKEN bilan HMAC), rol bazadan olinadi.
- Menyu bo'limlarga bo'lingan (O'quvchilar, Moliya, Guruh boshqaruvi, Hisobotlar, Xodimlar), `🏠 Asosiy menyu` tugmasi.
- Guruhlar: o'qituvchi -> guruh -> o'quvchi -> kartochka (bitta xabar tahrirlanadi), sahifalash, davomat tarixi.
- **Dars jadvali** (🗓): dars kunlari va vaqti; davomat olinmasa o'qituvchiga (20 daqiqadan keyin) va adminga (2 soatdan keyin) eslatma.
- Vaqt Toshkent bo'yicha (`TZ_OFFSET=5`).

## Guruhsiz qolgan o'quvchilarni tozalash (faqat direktor)
Xodimlar sahifasida, agar shunday o'quvchilar bo'lsa, **"🧹 Guruhsiz qolgan o'quvchilar"** bo'limi chiqadi:
guruhi (masalan eski kod versiyasi orqali) o'chirilgan-u, lekin o'zi texnik sabab bilan o'chmay qolgan o'quvchilar
ro'yxati va soni. **"🗑 Hammasini bittada o'chirish"** tugmasi — ularning barchasini bir zumda tozalaydi (agar
ulardan birortasida sertifikat yoki 189 ball belgisi bo'lsa, u hali ham arxivlanadi, butunlay o'chirilmaydi -
odatdagi o'chirish qoidasi bilan bir xil). Bunday o'quvchilar yo'q bo'lsa, bu bo'lim umuman ko'rinmaydi.

## O'qituvchi oylik turlari
O'qituvchi qo'shish/tahrirlashda (faqat direktor) uch xil oylik turidan birini tanlash mumkin: **Foiz (%)**
(guruh tushumidan foiz), **O'quvchi boshiga** (har o'quvchi uchun belgilangan summa, kam to'lasa pastroq foiz
bilan), va **Aniq oylik** — masalan 1 500 000 so'm/oy — bu holda guruhlardagi o'quvchilar soni, tushum yoki
to'lovlardan qat'i nazar, o'qituvchi har oy aynan shu summani oladi (reyestr darslari bo'lsa, ular ustiga
qo'shiladi, chunki bu alohida davlat to'lovi).

## O'qituvchi oyligini direktor ko'rishi
Xodimlar bo'limidagi har bir o'qituvchi qatorida **"💰"** tugmasi bor — bosilsa, o'sha o'qituvchining to'liq
oylik tafsiloti ochiladi (xuddi o'qituvchining o'zi "💰 Oylik" bo'limida ko'radigani kabi): har bir guruh
bo'yicha tushum, to'laganlar/qarzdorlar soni, davomat foizi, reyestr hisob-kitobi va jami oylik summasi,
oylar bo'yicha ham (oxirgi 6 oy) ko'rish mumkin. Avval direktor faqat barcha o'qituvchilarning **yig'indi**
summasini (Panelda "O'qituvchilar oyligi" KPI) yoki Excel hisobotdagi jami raqamlarni ko'rar edi, endi har
bir o'qituvchining alohida tafsilotini ham to'g'ridan-to'g'ri Mini App'da ko'rish mumkin.

## O'qituvchiga avans berish (admin, direktor)
Ba'zi o'qituvchilar oyligidan oldin avans olib turishadi - buni tizimga kiritib, keyin oyligi hisoblanganda
avtomatik ayirib ko'rsatish mumkin. **Avans qaysi oyga kiritilsa, o'sha oyning oyligidan ayiriladi** (masalan
dekabrda berilgan avans - dekabr oyligidan kamayadi, noyabr oyligiga ta'sir qilmaydi).
- **Mini App**: Xodimlar bo'limida o'qituvchining "💰" tugmasi orqali ochilgan oylik sahifasida **"➕ Avans
  kiritish"** tugmasi bor - summasi va ixtiyoriy izoh bilan. Pastda shu oydagi barcha avanslar ro'yxati va
  har birini o'chirish (xato kiritilgan bo'lsa) imkoniyati ko'rsatiladi. Admin uchun Xodimlar bo'limi
  qisqartirilgan ko'rinishda: faqat o'qituvchilar ro'yxati va har birining "💰" tugmasi (avans kiritish uchun)
  ko'rinadi - o'qituvchi/admin qo'shish-tahrirlash-o'chirish, reyestr va filiallar bo'limlari faqat direktorga xos
  qolaveradi.
- **Chat**: "💰 Moliya" bo'limida **"💸 Avans kiritish"** tugmasi - o'qituvchini tanlab, summa va izoh kiritiladi.
- Oylik ko'rinishida endi uch qator chiqadi (agar shu oyda avans bo'lsa): **"Jami hisoblangan"** (guruhlar/reyestrdan
  hisoblangan to'liq summa), **"Avans olingan"** (ayriladigan summa, qizil rangda), **"Beriladigan"** (sof,
  qo'lga tegadigan summa - agar avans oylikdan ko'p bo'lib ketsa, bu manfiy ham chiqishi mumkin, direktorga
  o'qituvchi "qarzdor" ekanini bildiradi). Avans bo'lmagan oylarda oddiy "Jami oylik" ko'rinishida qoladi
  (o'zgarishsiz). O'qituvchining o'zi ham "💰 Oylik" bo'limida (va chatda "💰 Oylikni ko'rish"da) bu uch summani
  ko'radi, lekin avans kirita/o'chira olmaydi - faqat ko'rish uchun.

## O'qituvchilar reytingi (faqat direktor)
Panelda **"🏆"** tugmasi — barcha o'qituvchilarni solishtiruvchi ro'yxat: har biri uchun guruhlar/o'quvchilar soni,
joriy oy tushumi, qarzdorlar foizi va davomat foizi. Ro'yxat **eng kam qarzdorlikdan eng ko'pigacha** tartiblanadi
(eng yaxshi natija birinchi), va alohida "🏆 eng yaxshi davomat" / "⚠️ eng ko'p qarzdor" o'qituvchi ajratib
ko'rsatiladi. Panel'dagi filial filtri bilan birga ishlaydi — faqat shu filialdagi guruhlar bo'yicha hisoblanadi.
Hech qanday guruhi yo'q o'qituvchilar ro'yxatda ko'rinmaydi.

## Lidlar (potentsial o'quvchilar, faqat admin/direktor)
Hali ro'yxatdan o'tmagan, lekin qiziqish bildirgan odamlarni ("lid") kuzatib borish uchun. Mini App'da
**"🧲 Lidlar"** tab, bot chatida esa asosiy menyuda **"🧲 Lidlar"** tugmasi orqali ishlaydi (ikkisida ham bir
xil funksiya).
- **Qo'shish**: ism, familiya, qiziqqan sinf, telefon, manba (Instagram / tanishlar orqali / ko'chadagi
  reklama / boshqa), filial (bir nechta filial bo'lsa) va izoh kiritiladi.
- **Bosqichlar**: 🆕 Yangi → 📞 Bog'lanildi → 🎓 Sinov darsida → 🎉 O'quvchi bo'ldi / ❌ Voz kechdi.
- **"🎉 O'quvchi qilish"**: guruh tanlanadi, lidning ma'lumotlari asosida yangi o'quvchi yozuvi avtomatik
  yaratiladi (qayta kiritish shart emas), lid "O'quvchi bo'ldi" deb yopiladi.
- **"❌ Voz kechish"**: sababini yozish mumkin (ixtiyoriy), lid yopiladi.
- **5 kunlik eslatma**: agar lid qo'shilganidan beri 5 kun o'tib hali qaror qilinmagan bo'lsa (hali Yangi/
  Bog'lanildi/Sinov darsida holatida), admin va direktorga har kuni (ertalab) eslatma xabari boradi - qaror
  qilinmaguncha har kuni takrorlanadi. **Agar sinov darsi sanasi belgilangan bo'lsa, bu 5 kunlik eslatma
  o'chadi** - o'rniga sinov darsi kuni va undan keyingi kunlarda (natija bo'lmasa) eslatiladi.
- **Sinov darsi sanasi**: "Sinov darsida" bosqichiga o'tganda sana kiritish so'raladi (ixtiyoriy, keyinroq
  ✏️ Tahrirlash orqali ham qo'shish/o'zgartirish mumkin). O'sha kuni ertalab "bugun sinov darsi bor" eslatmasi
  keladi; agar sinov darsidan keyin ham qaror qilinmasa (o'quvchi qilinmasa yoki voz kechilmasa), ertasi kundan
  boshlab har kuni qayta eslatiladi (yuqoridagi 5 kunlik eslatma mexanizmi orqali).
- **✏️ Tahrirlash**: lidning istalgan maydonini (ism, familiya, telefon, sinf, manba, izoh) keyinchalik
  o'zgartirish mumkin - xato kiritilgan bo'lsa, o'chirib qayta qo'shish shart emas.
- **📊 Statistika**: manba bo'yicha nechta lid kelgani va ularning necha foizi o'quvchi bo'lganini (konversiya),
  shuningdek eng ko'p takrorlanadigan "voz kechish" sabablarini ko'rsatadi - qaysi reklama kanali samaraliroq
  ekanini va narx/shartlar bo'yicha qaysi e'tirozlar ko'p uchrashini bilish uchun.

## Qarzdorlarga to'lov eslatmasi (faqat direktor)
Panel sahifasida (yuqorida) **"📢"** tugmasi — shu oydagi **barcha** qarzdor o'quvchilarning ulangan ota-onalariga
avtomatik Telegram xabari yuboradi ("Hurmatli ota-ona! [O'quvchi] uchun [oy] oyi kurs to'lovini hali amalga
oshirmagansiz..."). Agar Panelda filial tanlangan bo'lsa, faqat o'sha filialdagi qarzdorlarga yuboriladi.
Har bir guruh kartochkasida ham alohida **"📢 Shu guruh qarzdorlariga xabar"** tugmasi bor — faqat o'sha bitta
guruhning (demak, o'sha o'qituvchining) qarzdorlariga yuboradi. Reyestr o'quvchilari hech qachon qarzdor
hisoblanmagani uchun ularga xabar bormaydi. Ota-onasi hali ulanmagan qarzdorlar bo'lsa, ularning ismlari
yuborilgandan keyin chiqadigan xabarda ko'rsatiladi. Bu funksiya faqat direktorga ko'rinadi, admin/o'qituvchiga yo'q.

## Yangi o'quvchi qo'shishda telefon va sana majburiy
Yangi o'quvchi qo'shilayotganda (admin, direktor, o'qituvchi - hammasi uchun, Mini App'da ham, chatda ham)
endi **telefon raqami** va **qo'shilgan sana** majburiy - bo'lmasa saqlanmaydi. Mini App'da sana maydoni
avtomatik bugungi kun bilan to'ldirilgan holda chiqadi (xohlasa o'zgartirishi mumkin), chatda esa "📅 Bugun"
tugmasi yoki sanani qo'lda yozish (masalan 24.11.2026) orqali kiritiladi. **Bu qoida faqat yangi qo'shiladigan
o'quvchilarga tegishli** - bazada avvaldan mavjud, telefon raqami yoki sanasi kiritilmagan o'quvchilar
o'zgarishsiz qoladi va ularni tahrirlashda bu maydonlar majburiy emas.

## O'quvchini muzlatish (tanaffusga chiqarish)
Ba'zi o'quvchilar orada ikki-uch oylab tanaffus qilib, keyin yana kelishni davom ettirishadi. Bunday o'quvchini
butunlay o'chirib tashlamasdan, **"❄️ Muzlatish"** qilish mumkin (o'quvchi kartochkasida, "✏️ Tahrirlash" tugmasi
yonida — Mini App'da ham, chatda ham). Muzlatilgan o'quvchi:
- Hech qachon **qarzdor** hisoblanmaydi (❄️ belgisi bilan ko'rsatiladi, qarzdorlar sonidan chiqarib tashlanadi,
  qarzdorlarga avtomatik to'lov eslatmasi ham bormaydi).
- **Davomat** ro'yxatida chiqmaydi - o'qituvchi tanaffusdagi o'quvchiga davomat belgilamaydi.
- Guruh/o'quvchilar ro'yxatida, qidiruvda va hisobotlarda hali ham ko'rinadi (❄️ belgisi bilan), shuning uchun
  qaytib kelganda topib, **"♨️ Qayta faollashtirish"** tugmasi bilan oson qaytarish mumkin.
Muzlatish/qaytarish - admin, direktor va o'qituvchi uchun ham ochiq (kundalik ishda shuni ko'proq o'qituvchi
payqaydi).

## Filiallar
O'quv markaz bir nechta filial (shahar/tuman bo'limi) bilan ishlashi mumkin. Direktorga **"👨‍🏫 Xodimlar"** bo'limida
**"🏢 Filiallar"** bo'limi: filial qo'shish/nomini o'zgartirish/o'chirish (faqat direktor huquqi). Guruh
qo'shish/tahrirlashda (admin/direktor) guruhga filial tanlanadi (ixtiyoriy — filialsiz ham bo'lishi mumkin).
Yangi o'qituvchi yoki admin qo'shishda ham (Xodimlar bo'limi) filial so'raladi (ixtiyoriy, keyinroq ham
o'zgartirish/qo'shish mumkin). O'qituvchi uchun bu faqat ma'lumot uchun (u olib boradigan guruhlar istalgan
filialda bo'lishi mumkin). **Admin uchun esa bu haqiqiy cheklov**: agar adminga filial biriktirilgan bo'lsa,
u **faqat shu filialni** ko'radi va boshqara oladi — guruhlar, o'quvchilar (qidirish ham), Panel, Excel
hisobotlar, bildirishnomalar va lidlar faqat o'z filiali bo'yicha chiqadi; boshqa filialga guruh/lid
yaratish, o'zgartirish yoki o'chirish, boshqa filial guruhiga o'quvchi qo'shish rad etiladi. Filialga
biriktirilmagan (ixtiyoriy, bo'sh qoldirilgan) admin esa avvalgidek hamma filialni ko'radi. Direktorga bu
cheklov hech qachon qo'llanilmaydi — direktor doim hammasini ko'radi. **Panel** sahifasida filial bo'yicha
filtr chiplari bor —
"🏢 Barchasi" yoki aniq bitta filialni tanlab, shu filialning tushumi, qarzdorlari, davomat foizi, 6 oylik grafigi
va (direktorga) o'sha filialdagi guruhlar uchun hisoblangan o'qituvchilar oyligi alohida ko'rsatiladi. Panelda
tanlangan filial **"O'quvchilar" bo'limidagi guruhlar ro'yxatiga ham tegishli** — Panelda masalan "Karmana"ni
tanlasangiz, O'quvchilar bo'limiga o'tganingizda ham faqat Karmana guruhlari ko'rinadi, boshqa filial guruhlari
chiqmaydi (qaysi filialni ko'rib tursangiz, hammasi o'sha filialga mos keladi). Filial
o'chirilsa, undagi guruhlar o'chmaydi — faqat filialsiz holatga o'tadi. Filiallar funksiyasi qo'shilishidan oldin
yaratilgan barcha guruhlar (hozirgi asosiy markaz) avtomatik "filialsiz" holatda qoladi — hech qaysi filialga
majburan biriktirilmaydi, "Barchasi" ko'rinishida baribir hisoblanadi. Agar ularni ham bitta filialga (masalan
"Asosiy") yig'moqchi bo'lsangiz, filial ichida **"📥 Filialsiz guruhlarni bu filialga ko'chirish"** tugmasi bor —
hali hech qaysi filialga biriktirilmagan barcha guruhlarni bir bosishda shu filialga o'tkazadi (allaqachon boshqa
filialga biriktirilgan guruhlarga tegmaydi). Agar o'tmishda biror guruh o'chirilgan bo'lsa-yu, uning to'lovlari
tarix sifatida saqlanib qolgan bo'lsa — bunday to'lovlarning qaysi filialga tegishli ekani endi aniqlanmaydi,
shuning uchun **aniq bitta filial tanlanganda** ular hisobga kirmaydi ("🏢 Barchasi"da esa to'liq hisoblanadi).
Bunday holatda Panelda sariq ogohlantirish chiqib, qancha summa va nega ko'rinmayotgani tushuntiriladi.

## Sertifikatlar
Pastki **"🎓 Sertifikat"** tab (hamma rollar). Guruhni tanlab, o'quvchini oching — har bir fan bo'yicha
(Matematika, Fizika, Kimyo, Biologiya, Ona tili va adabiyot, Ingliz tili, Rus tili, Tarix, Geografiya, Informatika)
sertifikat belgilanadi: fan nomini bosib, darajasini tanlang (A+, A, B+, B, C+, C). O'qituvchi o'quvchi kartochkasida
qaysi fanlardan sertifikati borligini darhol ko'radi (ro'yxatda 🎓 belgisi bilan). Alohida **"🏆 189 bormi?"** tugmasi —
bosilganda o'quvchi 189 ball (milliy sertifikat) olgan deb belgilanadi, ro'yxatda boshqacha (oltin) rangda ajralib turadi.
189 ball olgan yoki sertifikati bor o'quvchi guruhdan o'chirilsa (kursdan ketsa) ham, uning ma'lumotlari **o'chmaydi** —
yashirin holatda saqlanadi va "🏅 Bitirganlar" ro'yxatida (Sertifikat tab'ining yuqorisida) yil oxirida hisob-kitob
qilish uchun ko'rinib turadi. Sertifikati yo'q oddiy o'quvchi o'chirilsa, odatdagidek butunlay o'chiriladi.

## Ota-onalar uchun (faqat ko'rish)
O'quvchi kartochkasida (chatda "📚 Guruhlar" -> o'quvchi, yoki Mini App'da "👪 Ota-onaga havola") maxsus havola
yaratiladi. Ota-ona shu havolani bosib botni ochsa, `/parent` Mini App sahifasida farzandining sinfi, guruhi,
shu oy to'lov holati (**to'langan/to'lanmagan — faqat shu, summasi ko'rsatilmaydi**) va oxirgi darslar davomati
ko'rinadi — hech narsani o'zgartira olmaydi. To'lov summasi maxfiy saqlanadi, faqat xodimlarga (admin, direktor,
o'qituvchi) Mini App'da ko'rinadi. Bir nechta farzand bo'lsa, hammasi ro'yxatda chiqadi. Havola doimiy ishlaydi
(muddati tugamaydi), istalgan vaqt qayta yuborilishi mumkin. Har bir farzand kartochkasida
**"🔓 Ushbu farzand bilan bog'lanishni bekor qilish"** tugmasi bor — bosilsa (tasdiqlagandan keyin) shu
bog'lanish bazadan butunlay o'chiriladi, ota-ona endi o'sha o'quvchi haqida hech narsa ko'rmaydi (boshqa
farzandlari bilan bog'lanish, agar bo'lsa, o'zgarmay qoladi). Havola doimiy (o'zgarmas) bo'lgani uchun, bekor
qilingandan keyin **o'sha eski havolani qayta bossa ham endi avtomatik qayta ulanib qolmaydi** — tizim buni
eslab qoladi va "markazga murojaat qiling" deb javob beradi (boshqa ota-ona, masalan otasi, bu bog'lanishni
bekor qilgan onasidan mustaqil ravishda hali ham bog'lana oladi).
Havolani **kim bossa, o'sha ota-ona sifatida bog'lanadi** — tizim bu kishi haqiqiy ota-ona ekanligini tekshirmaydi,
shuning uchun havolani faqat haqiqiy ota-onaga yuborish kerak. Buning uchun havola yonida **"📤 Telegramda ulashish"**
(Telegramning o'z ulashish oynasi orqali to'g'ridan-to'g'ri kerakli kishiga yuboriladi) va, agar o'quvchining telefon
raqami kiritilgan bo'lsa, **"💬 WhatsApp'da yuborish"** tugmalari bor (WhatsApp'da shu raqamga tayyor xabar bilan ochiladi).
Qaysi o'quvchining ota-onasi ulangan-ulanmaganini **o'qituvchi, admin va direktor hammasi** ko'radi: o'quvchilar
ro'yxatida har bir ism yonida 👪✅ (ulangan) yoki 👪❌ (ulanmagan) belgisi, o'quvchi kartochkasida esa to'liq
"Ota-ona ulangan / ulanmagan" yozuvi chiqadi.

## Chat menyusi (WEBAPP_URL o'rnatilganda)
Mini App to'liq ishlayotgan bo'lsa, chat menyusi ikki tugmaga qisqaradi: **"📱 Ilovani ochish"** (bosilganda
alohida xabarda ishonchli inline tugma yuboradi — doimiy klaviaturadagi web_app tugmasi ba'zi hollarda eskirgan
imzo bilan ochilib xato berishi mumkin edi, shuning uchun shunday qilindi) va
**"📤 Fayldan yuklash"** (direktorga qo'shimcha **"📈 Statistika"**). Hamma boshqa funksiya (davomat, o'quvchilar,
moliya, xodimlar, dars jadvali, to'lov, qarzdorlar) Mini App ichida. Eski chat buyruqlari (masalan "📚 Guruhlar",
"🔎 Qidirish" va h.k.) — ularning matnini kimdir yuborsa ham (eski klaviatura keshi, odat bo'yicha yozish) —
Mini App'da bor bo'lgani uchun endi ishlamaydi, o'rniga "Mini App'dan foydalaning" deb javob qaytaradi.
`WEBAPP_URL` o'rnatilmagan bo'lsa (Background Worker holatida), bot avtomatik eski, to'liq chat menyusiga qaytadi -
hech narsa buzilmaydi, faqat qulaylik yo'qoladi.

## Nazorat/sinov natijalari
O'quvchilar bo'limida guruh ichida **"📝"** tugmasi (nazorat natijalari). O'qituvchi/admin/direktor
yangi nazorat yaratadi (nomi, maksimal ball, sana), so'ng shu guruhdagi hamma o'quvchiga baho kiritadi
(bitta ekranda, ketma-ket) — har bir o'quvchiga **ball** bilan bir qatorda **daraja** ham tanlanadi
(A+, A, B+, B, C+, C — tanlov ro'yxatidan, qo'lda yozilmaydi). Har bir nazorat uchun guruh o'rtacha balli
ko'rinadi. O'quvchi kartochkasida oxirgi 10 ta nazorat natijasi (ball va daraja bilan) ko'rinadi. Ota-ona
sahifasida ham farzandining oxirgi 5 ta nazorat natijasi (ball + daraja) chiqadi. Baholarni saqlagandan
keyin **"👪 Ota-onalarga yuborish"** tugmasi: shu nazorat natijasi (ball va daraja bilan) ulangan har bir
o'quvchining ota-onasiga avtomatik xabar qilib yuboriladi. Ota-onasi hali ulanmagan o'quvchilar bo'lsa,
ularning ismi o'qituvchiga shu yerning o'zida ko'rsatiladi — shulardan "👪 Ota-onaga havola" orqali
ulanish mumkin.

## To'lov cheki
To'lov kiritilganda chek (PDF) **endi avtomatik yuborilmaydi** (vaqt yo'qotmaslik uchun) — faqat talab bo'yicha:
Mini App'da o'quvchi kartochkasidagi "📜 To'lovlar tarixi"da har bir to'lov qatorida **"🧾"** tugmasi, chatda esa
to'lov qabul qilingan tasdiq xabari ostida **"🧾 Chek olish"** tugmasi bor — bosilganda PDF chek (markaz nomi,
o'quvchi, sinf, guruh, oy, sana, kim qabul qildi, summa) shu tugmani bosgan xodimga yuboriladi. Ota-onaga
to'lov haqida hech qachon alohida xabar yuborilmaydi (ota-ona to'lov holatini istalgan vaqt `/parent` sahifasida
o'zi ko'rishi mumkin). Markaz nomini `CENTER_NAME` muhit o'zgaruvchisi orqali o'zgartirish mumkin (standart:
"O'quv markazi").
