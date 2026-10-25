---
name: grocery-prices-browser
description: Исследовать продуктовые магазины и сравнивать список покупок через подключённые каталоги и браузер клиента с выводом наблюдений в Корзину. Координирует поиск по нескольким сетям.
---

# Исследование магазинов через браузер клиента

Определить продукты, город и выбранные сети из запроса и контекста панели. Город не фиксирован; Казань используется только в тестовом прогоне. Если сети не заданы, использовать 12 сетей таблицы. Если указаны другие поддерживаемые панелью сети, проверить их по общему сценарию без утверждения, что для них существует отдельный скилл.

Сначала прочитать [общий сценарий](references/browser-workflow.md). Загрузить только скиллы нужных сетей:

| Сеть | ID | Скилл |
| --- | --- | --- |
| Пятёрочка | `5ka` | [grocery-pyaterochka](../grocery-pyaterochka/SKILL.md) |
| Перекрёсток | `perekrestok` | [grocery-perekrestok](../grocery-perekrestok/SKILL.md) |
| Чижик | `chizhik` | [grocery-chizhik](../grocery-chizhik/SKILL.md) |
| Магнит | `magnit` | [grocery-magnit](../grocery-magnit/SKILL.md) |
| Лента | `lenta` | [grocery-lenta](../grocery-lenta/SKILL.md) |
| ВкусВилл | `vv` | [grocery-vkusvill](../grocery-vkusvill/SKILL.md) |
| Светофор | `svetofor` | [grocery-svetofor](../grocery-svetofor/SKILL.md) |
| Самокат | `samokat` | [grocery-samokat](../grocery-samokat/SKILL.md) |
| Ашан | `auchan` | [grocery-auchan](../grocery-auchan/SKILL.md) |
| METRO | `metro` | [grocery-metro](../grocery-metro/SKILL.md) |
| SPAR Middle Volga | `spar-middle-volga` | [grocery-spar-middle-volga](../grocery-spar-middle-volga/SKILL.md) |
| Smart | `smart` | [grocery-smart](../grocery-smart/SKILL.md) |

Для поиска использовать подходящий подключённый источник; `prices_search` даёт публичный ВкусВилл и Бахетле Павлюхина 57 в Казани, но не региональные цены всех сетей. Для недостающих сведений применять браузер клиента. Сервер MCP не управляет клиентским браузером самостоятельно.

Собирать результаты последовательно, отправляя завершённые магазины через `prices_browser_show`; панель объединяет порции. Для нескольких продуктов делать отдельный вызов на каждый запрос `q`. Использовать [формат](references/observations.md) и [сопоставление](references/matching.md). При ограничениях продолжать остальные сети и возвращать точный охват. Не оформлять заказы и не создавать расписания. Сохранить прежние пользовательские списки.

Проверенные возможности и ограничения: [матрица прогона](references/verification.md).
