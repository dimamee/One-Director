# Глоссарий узбекский ↔ русский

Единые термины для интерфейса, справок LLM, PDF и презентации. Узбекский — латиница (официальный алфавит).
Колонка «Статус»: **✓** — устоявшийся термин; **?** — рабочий перевод, проверить носителем языка и юристом до использования в справках и UI.
Агенты используют только термины из этой таблицы; новые термины добавляются через PR.

## 1. Закупки и торги

| Русский | O'zbekcha | Статус | Примечание |
|---|---|---|---|
| государственные закупки | davlat xaridlari | ✓ | |
| торги | savdolar | ✓ | ед. ч. savdo |
| электронная торговая площадка | elektron savdo maydonchasi | ✓ | |
| тендер | tender | ✓ | |
| конкурс (отбор) | tanlov | ✓ | |
| аукцион | auksion | ✓ | |
| электронный магазин | elektron do'kon | ✓ | |
| лот | lot | ✓ | |
| сделка | bitim | ✓ | |
| договор | shartnoma | ✓ | |
| заказчик | buyurtmachi | ✓ | |
| участник | ishtirokchi | ✓ | |
| победитель | g'olib | ✓ | |
| заявка / предложение | taklif | ✓ | также ariza (заявление) |
| стартовая цена | boshlang'ich narx | ✓ | |
| цена договора | shartnoma narxi | ✓ | |
| скидка (снижение цены) | chegirma (narxning pasayishi) | ? | в справках предпочтительно «narxning pasayishi» |
| категория | toifa | ✓ | |
| регион / область / район | hudud / viloyat / tuman | ✓ | |

## 2. Субъекты и идентификаторы

| Русский | O'zbekcha | Статус | Примечание |
|---|---|---|---|
| ИНН | STIR (soliq to'lovchining identifikatsiya raqami) | ✓ | 9 цифр |
| ПИНФЛ | JShShIR (jismoniy shaxsning shaxsiy identifikatsiya raqami) | ✓ | 14 цифр; **не собираем** |
| юридическое лицо | yuridik shaxs | ✓ | |
| индивидуальный предприниматель (ИП) | yakka tartibdagi tadbirkor (YaTT) | ✓ | маскируется |
| физическое лицо | jismoniy shaxs | ✓ | маскируется |
| учредитель | ta'sischi | ✓ | |
| руководитель / директор | rahbar / direktor | ✓ | |
| аффилированные лица | affillangan shaxslar | ✓ | |
| адрес | manzil | ✓ | хранится хешем |
| телефон | telefon raqami | ✓ | хранится хешем |

## 3. Конкуренция и признаки

| Русский | O'zbekcha | Код признака | Статус |
|---|---|---|---|
| конкуренция | raqobat | — | ✓ |
| соглашение, ограничивающее конкуренцию | raqobatni cheklovchi kelishuv | — | ✓ |
| сговор | til biriktirish | — | ✓ (только в общем описании, не о конкретной фирме) |
| картель | kartel | — | ✓ (только в общем описании, не о конкретной фирме) |
| признак | belgi | — | ✓ |
| **признаки возможного нарушения** | **ehtimoliy qoidabuzarlik belgilari** | — | ? |
| требует проверки | tekshiruv talab etiladi | — | ? |
| индикатор риска / уровень риска | xavf ko'rsatkichi / xavf darajasi | — | ? |
| малая скидка от стартовой цены | boshlang'ich narxdan past chegirma | `LOW_DISCOUNT` | ? |
| один участник / мало участников | yagona ishtirokchi / ishtirokchilar soni kam | `SINGLE_BIDDER` / `FEW_BIDDERS` | ? |
| устойчивое соучастие | muntazam birgalikda ishtirok etish | `CO_BIDDING` | ? |
| ротация победителей | g'oliblarning navbatma-navbat almashishi | `WINNER_ROTATION` | ? |
| «вечный второй» | «doimiy ikkinchi o'rin» egasi | `PERPETUAL_RUNNER_UP` | ? |
| общий учредитель | umumiy ta'sischi | `SHARED_FOUNDER` | ? |
| общий директор | umumiy rahbar | `SHARED_DIRECTOR` | ? |
| общий адрес / телефон | umumiy manzil / telefon raqami | `SHARED_ADDRESS` / `SHARED_PHONE` | ? |
| «прикрывающие» заявки | «niqob» takliflar (ko'rinish uchun berilgan takliflar) | `COVER_BID_PATTERN` | ? |

## 4. Органы и законы

| Русский | O'zbekcha | Статус | Примечание |
|---|---|---|---|
| Комитет по развитию конкуренции и защите прав потребителей | Raqobatni rivojlantirish va iste'molchilar huquqlarini himoya qilish qo'mitasi | ? | точное официальное название проверить |
| Закон «О конкуренции» (ЗРУ-850) | «Raqobat to'g'risida»gi Qonun (O'RQ-850) | ? | ст. 19 ч. 2, ст. 29 — тексты по lex.uz |
| Закон «О персональных данных» (ЗРУ-547) | «Shaxsga doir ma'lumotlar to'g'risida»gi Qonun (O'RQ-547) | ? | |
| статья / часть | modda / qism | ✓ | «19-modda 2-qismi» |
| инспектор | inspektor | ✓ | |
| проверка | tekshiruv | ✓ | |

## 5. Интерфейс и система

| Русский | O'zbekcha | Статус |
|---|---|---|
| очередь рисков | xavflar navbati | ? |
| карточка лота / фирмы | lot / kompaniya kartochkasi | ? |
| граф связей | aloqalar grafi | ? |
| справка | ma'lumotnoma | ✓ |
| справка сформирована ИИ / по шаблону | ma'lumotnoma sun'iy intellekt / shablon asosida tuzilgan | ? |
| это не доказательство нарушения | bu qoidabuzarlik dalili emas | ? |
| безопасность, конфиденциальность и объяснимый ИИ | xavfsizlik, maxfiylik va tushuntiriladigan AI | ✓ (формулировка жюри) |
| персональные данные | shaxsga doir ma'lumotlar | ✓ |
| замаскировано | yashirilgan | ? |
| экспорт PDF | PDF eksport | ✓ |

## 6. Запрещённые формулировки о конкретной фирме

| Русский (нельзя) | O'zbekcha (mumkin emas) | Вместо этого |
|---|---|---|
| нарушение доказано / установлено | qoidabuzarlik isbotlangan / aniqlangan | признаки возможного нарушения — ehtimoliy qoidabuzarlik belgilari |
| фирма — картель / участник картеля | kompaniya — kartel / kartel ishtirokchisi | выявлены признаки, требующие проверки — tekshiruv talab etadigan belgilar aniqlandi |
| виновен | aybdor | — |
| сговор установлен | til biriktirish aniqlangan | — |
