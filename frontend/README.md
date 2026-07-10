# MiniSED — фронтенд (Vue 3 + TypeScript + Vite)

Новый SPA-фронт MiniSED. Django остаётся чистым JSON API, nginx в проде
отдаёт собранную статику из `dist/`.

## Требования

- Node.js 20+ (LTS) и npm. На момент создания каркаса Node на машине не был
  установлен — поставьте с https://nodejs.org (LTS), затем перезапустите терминал.

## Запуск для разработки

```bash
cd frontend
npm install
npm run dev
```

Vite поднимется на http://localhost:5173 и проксирует `/api`, `/media`,
`/external` на Django (http://127.0.0.1:8000). То есть параллельно должен
работать бэкенд:

```bash
# из корня miniSED
venv/Scripts/python manage.py runserver
```

Для локальной отладки авторизации откройте фронт с параметром:
`http://localhost:5173/?b24_user_id=100` — этот id уйдёт в заголовке
`X-B24-User` (текущий контракт бэкенда, будет заменён на Этапе 2).

## Сборка

```bash
npm run build      # type-check + vite build -> dist/
npm run preview    # локальный предпросмотр собранного
```

## Структура

```
src/
  main.ts              точка входа
  App.vue              каркас: шапка + <RouterView>
  router/index.ts      маршруты
  stores/auth.ts       текущий пользователь (b24_user_id из URL или BX24)
  services/api.ts      обёртка над fetch (заголовок X-B24-User)
  types/models.ts      типы под сериализаторы Django
  views/               экраны (TasksView, AgreementDetailView)
  assets/main.css      базовая адаптивная тема (свет/тёмная)
```

## Что дальше

- Этап 2: заменить `X-B24-User` на серверную сессию/токен MiniSED
  (правки локализованы в `stores/auth.ts` и `services/api.ts`).
- Перенести формы создания согласования, реестры (my/all), шаблоны,
  выбор CRM-сделок и сотрудников на серверные endpoint'ы Bitrix Connector.
