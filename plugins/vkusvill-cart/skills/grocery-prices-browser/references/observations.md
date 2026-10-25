# prices_browser_show: контракт

Вызов: `q` (один запрос, 2–120 символов), `city`, `products` (0–40), `checks` (0–40). Хотя бы один массив непустой. Для списка продуктов отправлять отдельный вызов на каждый q. Передавать все проверенные кандидаты одного магазина/контекста вместе: новая порция заменяет предыдущую для того же q, city, store, scope, fulfillment.

Обязательные поля продукта: store, id (стабильный ID карточки), name (точное название), price (положительная цена в рублях), url (HTTPS официального сайта), quantity и unit (л/кг/шт или null/null), scope (публичный магазин/зона, не домашний адрес), condition (условия), checkedAt (фактическое время UTC ISO 8601).

Дополнительные поля, которые следует заполнять по наблюдению:
- availability: available / unavailable / unknown;
- priceType: regular / loyalty / personal / promotion / unknown;
- fulfillment: delivery / pickup / in_store / unknown;
- match: exact / substitute / similar / unknown;
- locationConfirmed: подтверждены город и публичная точка/зона;
- conditionsConfirmed: применимы все условия цены к данному пользователю и количеству;
- offerKind: offer / advertisement / catalog / unknown.

Пропущенные поля означают unknown/false. Для подтверждённого итога нужны available, locationConfirmed=true, известный fulfillment, match=exact/substitute, offerKind=offer и regular либо подтверждённые условия loyalty/personal/promotion. Само наличие цены не доказывает наличие товара.

`checks`: store, scope, fulfillment (если известен), checkedAt, status, message; url необязателен, но при наличии тоже должен быть официальным HTTPS-источником. Статусы: not_found, unsupported_city, login_required, address_required, captcha, browser_unavailable, catalog_only, error. Для неизвестной локации scope="Локация не подтверждена". unsupported_city требует явного подтверждения отсутствия обслуживания; ошибка загрузки — error. Для каталога без цены передавать check, не нулевую цену. Нельзя передавать одновременно товары и check для одного контекста.

Разрешённые домены основных сетей: vv — vkusvill.ru/www.vkusvill.ru; 5ka — 5ka.ru/www.5ka.ru; perekrestok — perekrestok.ru/www.perekrestok.ru; chizhik — chizhik.club/www.chizhik.club; magnit — magnit.ru/dostavka.magnit.ru; lenta — lenta.com/www.lenta.com; auchan — auchan.ru/www.auchan.ru; metro — online.metro-cc.ru/metro-cc.ru/www.metro-cc.ru; samokat — samokat.ru/www.samokat.ru; svetofor — svetofor-rls.ru; spar-middle-volga — myspar.ru/www.myspar.ru; smart — smart.swnn.ru. Дополнительный региональный источник не включать автоматически; вернуть ссылку в чате до подтверждения принадлежности и расширения списка.

Данные сохраняются только в локальном кэше панели на 24 часа. Сервер не проверяет наблюдение независимо. Для подтверждения успешного импорта нужен успешный ответ инструмента; если инструмент недоступен, сохранить тот же JSON локально и дать таблицу со ссылками.
