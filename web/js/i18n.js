// Interface language: English (as written in the templates) or Russian (translated here, on the rendered page).
// Text nodes and a few attributes are matched against a dictionary of whole strings, then against patterns for
// strings with numbers, then piece by piece across " · " and " → ". Anything unmatched stays as it is.

const KEY = 'swarmsight.lang';
export const lang = (() => { try { return localStorage.getItem(KEY) || 'ru'; } catch { return 'ru'; } })();
export function setLang(l) { try { localStorage.setItem(KEY, l); } catch {} location.reload(); }

// Russian plural: 1 событие, 2 события, 5 событий
const pl = (n, one, few, many) => {
  const a = Math.abs(n) % 100, b = a % 10;
  return a > 10 && a < 20 ? many : b === 1 ? one : b >= 2 && b <= 4 ? few : many;
};

const RU = {
  // header, footer
  'Overview': 'Обзор', 'Trips': 'Поездки', 'Upload': 'Загрузка', 'Review': 'Проверка', 'Modules': 'Модули',
  'Evidence': 'Доказательства', 'Sections': 'Разделы', 'Language': 'Язык', 'SwarmSight, overview': 'SwarmSight, обзор',
  'connecting': 'подключение', 'server unreachable': 'сервер недоступен', 'server': 'сервер',
  'Taxi fleets as road sensors, Tashkent. Every result on this site is computed by this server or by a script in our repository. Nothing is hard-coded.':
    'Таксопарки как дорожные сенсоры, Ташкент. Каждый результат на сайте посчитан этим сервером или скриптом из нашего репозитория. Ничего не вписано вручную.',
  'Measured quality, speed and cost': 'Измеренное качество, скорость и стоимость',
  'Data, licences and known failures': 'Данные, лицензии и известные ошибки',
  'API': 'API', 'OpenAPI reference': 'Справка OpenAPI', 'Partner road feed': 'Фид для партнёров', 'GeoJSON': 'GeoJSON',

  // home
  'SwarmSight · Taxi fleet intelligence network · Tashkent': 'SwarmSight · Сеть данных таксопарков · Ташкент',
  'Every taxi trip makes roads safer and AI smarter.': 'Каждая поездка такси делает дороги безопаснее, а ИИ умнее.',
  'Taxi fleets already drive every street, every day. SwarmSight turns their dashcams and phones into road sensors: a trip becomes a handful of short, anonymised, verifiable clips that feed three products at once.':
    'Такси каждый день проезжают каждую улицу. SwarmSight превращает их регистраторы и телефоны в дорожные сенсоры: поездка становится несколькими короткими анонимными клипами, которые можно проверить и которые питают сразу три продукта.',
  'Upload a trip': 'Загрузить поездку', 'Run a sample trip': 'Запустить пример поездки',
  'How it works': 'Как это работает', 'Two steps, then three modules': 'Два шага, затем три модуля',
  'Step 1': 'Шаг 1', 'Step 2': 'Шаг 2', 'A trip goes in': 'Загружается поездка',
  'Dashcam or phone video, a GPS track if there is one. The server finds the few moments that matter, cuts a short clip for each and blurs faces and plates.':
    'Видео с регистратора или телефона и GPS-трек, если он есть. Сервер находит немногие важные моменты, вырезает для каждого короткий клип и размывает лица и номера.',
  'A person decides': 'Решает человек',
  'Every event is a candidate until someone confirms, rejects or corrects it. Every decision is logged.':
    'Каждое событие остаётся кандидатом, пока человек его не подтвердит, не отклонит или не исправит. Каждое решение записывается в журнал.',
  'Module': 'Модуль', 'Verified road events': 'Подтверждённые дорожные события',
  'Potholes and cracks, merged across taxis, with position and uncertainty. A map and partner feeds (GeoJSON, CIFS).':
    'Ямы и трещины, объединённые по наблюдениям разных машин, с координатами и погрешностью. Карта и фиды для партнёров (GeoJSON, CIFS).',
  'for maps': 'для карт', 'road services': 'дорожных служб', 'fleets': 'таксопарков',
  'Open RoadSense': 'Открыть RoadSense', 'Open Safety': 'Открыть Safety', 'Open DataMine': 'Открыть DataMine',
  'Explained safety episodes': 'Объяснённые эпизоды безопасности',
  'Collision risks, pedestrians in our path, cut-ins and hard braking, with what the camera saw. For coaching; never a fine, never public.':
    'Риски столкновения, пешеходы на пути, подрезания и резкие торможения вместе с тем, что видела камера. Для обучения водителей; никогда не штраф и никогда не публично.',
  'for fleet safety teams': 'для служб безопасности таксопарков', 'Regional dataset': 'Региональный датасет',
  'The rare, uncertain, well-exposed moments plus ordinary driving, with rights, split by trip, exported as versions.':
    'Редкие, неуверенные для модели, хорошо снятые моменты плюс обычная езда; с правами на использование, разбиением по поездкам и версиями экспорта.',
  'for automotive AI': 'для автомобильного ИИ', 'ADAS teams': 'команд ADAS',
  'On this server': 'На этом сервере', 'Live, from real uploads': 'Вживую, по реальным загрузкам',
  'trips processed': 'поездок обработано', 'of video kept as clips': 'видео сохранено в клипах',
  'the rest is analysed and discarded': 'остальное проанализировано и удалено',
  'events reviewed by a person': 'событий проверено человеком',
  'verified road events in the partner feed': 'подтверждённых дорожных событий в фиде для партнёров',
  'Measured': 'Измерено', 'On data the models never saw': 'На данных, которых модели не видели',
  'road-damage detector we trained': 'наш детектор дефектов дороги',
  'on Tashkent street photos': 'на фото улиц Ташкента', 'event recall on labelled trips': 'полнота по событиям на размеченных поездках',
  'of labelled video kept in event clips': 'размеченного видео попало в клипы событий',
  'Sources, splits, licences and failure cases:': 'Источники, разбиения, лицензии и случаи ошибок:',
  'What SwarmSight is not: an autopilot, a way to blame drivers from one camera, or access to Yandex or carmaker data.':
    'Чем SwarmSight не является: автопилотом, способом обвинить водителя по одной камере или доступом к данным Яндекса или автопроизводителей.',

  // upload
  'Step 1 · Upload a trip': 'Шаг 1 · Загрузка поездки',
  'A trip goes in. A few verifiable moments come out.': 'На входе поездка. На выходе несколько проверяемых моментов.',
  'Drop dashcam or phone footage from a drive. The server detects and tracks road users and road damage, proposes events, cuts each one into a short clip with context before and after, blurs faces and plates, and sends them to review. Nothing is published before a person confirms it.':
    'Перетащите видео поездки с регистратора или телефона. Сервер находит и отслеживает участников движения и дефекты дороги, предлагает события, вырезает для каждого короткий клип с контекстом до и после, размывает лица и номера и отправляет на проверку. Ничего не публикуется, пока человек не подтвердит.',
  'Drop a trip video or a road photo': 'Перетащите видео поездки или фото дороги', 'Drop another trip or photo': 'Перетащите другую поездку или фото',
  'MP4, MOV, WEBM up to 300 MB (under 100 MB uploads fastest)': 'MP4, MOV, WEBM до 300 МБ (до 100 МБ загружается быстрее всего)',
  'the first 2 minutes are analysed': 'анализируются первые 2 минуты', 'or a JPG/PNG road photo': 'или фото дороги JPG/PNG',
  'input': 'вход', 'uploading…': 'загрузка…', 'No footage at hand': 'Нет своего видео',
  'Run this trip through the pipeline': 'Прогнать эту поездку через систему', 'same code path as an upload': 'тот же код, что и для загрузки',
  'no GPS: place it on the map in Review': 'без GPS: место можно отметить на карте в Проверке', 'with its GPS track': 'с GPS-треком',
  'Or a Tashkent street photo': 'Или фото улицы Ташкента', 'captions are our labels': 'подписи — наша разметка',
  'No damage': 'Нет дефектов', 'no damage': 'нет дефектов', 'Tashkent street': 'Улица Ташкента', 'uploaded photo': 'загруженное фото',
  'Where it was driven (optional)': 'Где ехали (необязательно)',
  'GPS track · GPX or CSV (t, lat, lon[, speed_kmh][, accel_long_ms2])': 'GPS-трек · GPX или CSV (t, lat, lon[, speed_kmh][, accel_long_ms2])',
  'Track time at the start of the video, s': 'Время трека в начале видео, с',
  'No track? Pin one position for the whole video:': 'Нет трека? Отметьте одну точку на всё видео:',
  'Use device GPS': 'GPS устройства', 'Clear': 'Очистить',
  'No location: events get no coordinates. We never invent them; a moderator can place an event by hand.':
    'Без местоположения у событий не будет координат. Мы их никогда не выдумываем; модератор может поставить событие на карту вручную.',
  'GPS unavailable.': 'GPS недоступен.', 'pinned on the map': 'отмечено на карте', 'device GPS': 'GPS устройства',
  'Rights': 'Права', 'Road events only': 'Только дорожные события', 'Road events and the regional dataset': 'Дорожные события и региональный датасет',
  'Choose the dataset only for footage you have the right to share for model training. Faces and plates are blurred either way; the original upload is deleted after processing.':
    'Выбирайте датасет, только если у вас есть право передавать это видео для обучения моделей. Лица и номера размываются в любом случае; исходный файл удаляется после обработки.',
  'queued on the server…': 'в очереди на сервере…', 'cutting clips, blurring faces and plates…': 'нарезка клипов, размытие лиц и номеров…',
  'a large file: on a slow connection, trim it to the minute that matters': 'большой файл: при медленной связи обрежьте его до нужной минуты',
  // sample trips (samples/samples.json)
  'Taxi ride, Frederiksted (St. Croix), 90 s': 'Поездка на такси, Фредерикстед (Сент-Круа), 90 с',
  'A real taxi (a 15-seat van) through town to the cruise pier, filmed from beside the driver: parked cars, narrow streets, pedestrians on the pier. No GPS track. Wikimedia Commons, CC BY 3.0, John Edwards; faces and plates blurred by us.':
    'Настоящее такси (микроавтобус на 15 мест) через город к круизному причалу, снято рядом с водителем: припаркованные машины, узкие улицы, пешеходы на причале. Без GPS-трека. Wikimedia Commons, CC BY 3.0, John Edwards; лица и номера размыты нами.',
  'Tashkent, 134 s along one street, phone in a car': 'Ташкент, 134 с по одной улице, телефон в машине',
  "120 photos a phone took about once a second while driving (Mapillary, CC BY-SA 4.0, contributor georgiysys; faces and plates blurred by Mapillary), one video frame per photo, with the phone's GPS. The phone-on-a-mount scenario of a taxi pilot.":
    '120 фото, которые телефон снимал примерно раз в секунду во время езды (Mapillary, CC BY-SA 4.0, автор georgiysys; лица и номера размыты Mapillary), один кадр видео на фото, с GPS телефона. Сценарий пилота с телефоном на держателе.',
  'Dashcam, office district, 90 s': 'Регистратор, офисный район, 90 с',
  'A windscreen dashcam (140° lens) on city streets and an arterial road in strong sun and glare. No GPS track. Wikimedia Commons, CC0, Fernost; faces and plates blurred by us.':
    'Регистратор на лобовом стекле (объектив 140°) на городских улицах и магистрали, яркое солнце и блики. Без GPS-трека. Wikimedia Commons, CC0, Fernost; лица и номера размыты нами.',
  'City centre, Kraków, 90 s': 'Центр города, Краков, 90 с',
  "A car camera through Kraków's centre: tram tracks, parked cars on both sides, a queue behind an SUV. No GPS track. Wikimedia Commons, CC BY 3.0, Relaxing Roads 4K; faces and plates blurred by us.":
    'Камера в машине в центре Кракова: трамвайные пути, машины припаркованы с обеих сторон, очередь за внедорожником. Без GPS-трека. Wikimedia Commons, CC BY 3.0, Relaxing Roads 4K; лица и номера размыты нами.',

  // trip report
  'Loading the trip…': 'Загрузка поездки…', 'Still processing on the server…': 'Сервер ещё обрабатывает…', 'Processing failed': 'Обработка не удалась',
  'No road damage in this photo': 'На этом фото нет дефектов дороги',
  'That is a valid result: we do not invent an event when the footage has none.': 'Это нормальный результат: мы не выдумываем событие, если на видео его нет.',
  'Kept in event clips': 'В клипах событий', 'Clips': 'Клипы', 'Analysed': 'Проанализировано', 'Server time': 'Время сервера',
  'Location': 'Местоположение', 'Input': 'Вход', 'one photo': 'одно фото', 'Analysed in': 'Анализ за',
  'none: events have no coordinates': 'нет: у событий нет координат', 'none': 'нет',
  'GPS track (GPX)': 'GPS-трек (GPX)', 'GPS track (CSV)': 'GPS-трек (CSV)', 'one pin for the whole video': 'одна точка на всё видео',
  'photo EXIF': 'EXIF фото', 'pin': 'точка', 'GPS track': 'GPS-трек', 'set by a moderator': 'поставлено модератором',
  'road events + regional dataset': 'дорожные события + региональный датасет', 'road events only': 'только дорожные события',
  'road + dataset': 'дорога + датасет', 'road only': 'только дорога',
  'Timeline': 'Таймлайн', 'Shaded: what is kept as clips. Everything else is analysed and discarded.': 'Закрашено то, что сохранено в клипах. Всё остальное проанализировано и удалено.',
  'Road': 'Дорога', 'Safety': 'Safety', 'Baseline': 'Обычная езда',
  'road events map and partner API after review': 'карта дорожных событий и API для партнёров после проверки',
  'fleet safety review (never public)': 'проверка службой безопасности таксопарка (никогда не публично)',
  'dataset only: ordinary driving against selection bias': 'только в датасет: обычная езда против смещения выборки',
  'Events by module': 'События по модулям', 'Review here or in the': 'Проверьте здесь или в', 'review center': 'центре проверки',
  'Confirmed road damage with a location becomes a verified road event.': 'Подтверждённый дефект с координатами становится подтверждённым дорожным событием.',
  'needs review': 'на проверке', 'confirmed': 'подтверждено', 'corrected': 'исправлено', 'rejected': 'отклонено',
  'When': 'Когда', 'Model': 'Модель', 'Where': 'Где', 'Goes to': 'Куда идёт', 'Data value': 'Ценность для данных',
  'no location (video without GPS)': 'нет местоположения (видео без GPS)', 'Nothing to review.': 'Нечего проверять.',
  'Route': 'Маршрут', "The trip's GPS track (internal: never in the partner feed) and where each event was observed.":
    'GPS-трек поездки (внутренний: никогда не попадает в фид для партнёров) и где замечено каждое событие.',
  'Confirm': 'Подтвердить', 'Reject': 'Отклонить', 'Correct type': 'Исправить тип', 'correct the type': 'исправить тип',
  'note for the audit log (optional)': 'заметка для журнала (необязательно)',
  'seeded random, away from events': 'случайно (с фиксированным зерном), вдали от событий',
  'cause: not established': 'причина: не установлена', 'driver fault: not determined': 'вина водителя: не определена',
  'road event': 'дорожное событие',
  // types and classes
  'Pothole': 'Яма', 'Alligator crack': 'Сетка трещин', 'Transverse crack': 'Поперечная трещина', 'Longitudinal crack': 'Продольная трещина',
  'Forward collision risk': 'Риск столкновения впереди', 'Pedestrian or rider in path': 'Пешеход или райдер на пути', 'Cut-in ahead': 'Подрезание',
  'Hard braking': 'Резкое торможение', 'Ordinary driving (baseline)': 'Обычная езда (базовая)',
  'Pedestrian': 'Пешеход', 'Cyclist': 'Велосипедист', 'Motorcyclist': 'Мотоциклист', 'Car': 'Машина', 'Truck': 'Грузовик', 'Bus': 'Автобус',
  'Bicycle': 'Велосипед', 'Motorcycle': 'Мотоцикл', 'Vehicle': 'ТС', 'Two-wheeler': 'Двухколёсное',
  'car': 'машина', 'person': 'пешеход', 'truck': 'грузовик', 'bus': 'автобус', 'bicycle': 'велосипед', 'motorcycle': 'мотоцикл',
  'cyclist': 'велосипедист', 'motorcyclist': 'мотоциклист', 'two wheeler': 'двухколёсное', 'vehicle': 'ТС',

  // review
  'Step 2 · Review center': 'Шаг 2 · Центр проверки', 'A person decides what the model only suspects.': 'Человек решает то, что модель только подозревает.',
  "Every mined event waits here as a candidate: confirm it, reject it or correct its type. Decisions are logged, change each device's reliability, turn confirmed road damage into verified road events and make clips eligible for the dataset.":
    'Каждое найденное событие ждёт здесь как кандидат: подтвердите, отклоните или исправьте тип. Решения записываются в журнал, меняют надёжность устройства, превращают подтверждённые дефекты в дорожные события и допускают клипы в датасет.',
  'All open': 'Все открытые', 'Decided': 'Решённые', 'reviewer': 'проверяющий', 'your name': 'ваше имя',
  'Pick an item from the queue. Keys:': 'Выберите элемент в очереди. Клавиши:', 'confirm': 'подтвердить', 'reject': 'отклонить', 'next/previous.': 'следующий/предыдущий.',
  'No decisions yet.': 'Решений пока нет.', 'The queue is empty.': 'Очередь пуста.', 'to fill it.': 'чтобы её заполнить.', 'Nothing selected.': 'Ничего не выбрано.',
  'Trip': 'Поездка', 'Device': 'Устройство', 'photo report': 'фото', 'selected at random (seeded), not by the model': 'выбрано случайно (с фиксированным зерном), не моделью',
  'model said': 'модель сказала', 'Audit log': 'Журнал', 'No location': 'Нет местоположения',
  'The video had no GPS. Click where the damage is to place it by hand (recorded as "set by a moderator").':
    'У видео не было GPS. Нажмите на карте, где дефект, чтобы поставить его вручную (запишется как «поставлено модератором»).',
  'correct': 'исправить', 'Safety tab': 'вкладка Safety', 'Script': 'Скрипт',

  // RoadSense
  'Module · RoadSense · road events and partner API': 'Модуль · RoadSense · дорожные события и API для партнёров',
  'Five taxis, one pothole, one event.': 'Пять такси, одна яма, одно событие.',
  "Observations of the same damage from different trips merge into one event. Confidence grows only with independent devices; a moderator's confirmation makes it verified. Only verified events reach partners, without device identities, routes or video.":
    'Наблюдения одного дефекта из разных поездок сливаются в одно событие. Уверенность растёт только с независимыми устройствами; подтверждение модератора делает его подтверждённым. Партнёрам уходят только подтверждённые события, без устройств, маршрутов и видео.',
  'Verified': 'Подтверждённые', 'Open': 'Открытые', 'All': 'Все',
  'candidate': 'кандидат', 'corroborated': 'подтверждено машинами', 'verified': 'подтверждено', 'expired': 'истекло',
  'Event': 'Событие', 'Click an event on the map.': 'Нажмите на событие на карте.',
  'No verified events yet. Confirm road damage in the': 'Подтверждённых событий пока нет. Подтвердите дефекты в',
  ', or look at open events.': ', или посмотрите открытые события.', 'No events yet.': 'Событий пока нет.', 'with a GPS track or a pin.': 'с GPS-треком или точкой.',
  'Confidence': 'Уверенность', 'Position': 'Координаты', 'Seen': 'Замечено', 'Valid until': 'Действует до', 'unless re-observed': 'если не замечено снова',
  'Observations': 'Наблюдения', 'History': 'История', 'evidence': 'доказательство',
  'Partner API': 'API для партнёров', 'Read-only feeds for maps, road services and fleets': 'Фиды только для чтения для карт, дорожных служб и таксопарков',
  'Live on this server. In a pilot: API keys, rate limits, an audit log and a data-use agreement per partner.':
    'Работают на этом сервере. В пилоте: ключи API, лимиты запросов, журнал доступа и соглашение об использовании данных с каждым партнёром.',
  'Endpoint': 'Адрес', 'What it returns': 'Что возвращает', 'Now': 'Сейчас',
  'Verified road events, GeoJSON: type, status, confidence, independent sources, position uncertainty, validity':
    'Подтверждённые дорожные события, GeoJSON: тип, статус, уверенность, независимые источники, погрешность координат, срок действия',
  'The same events as CIFS-style incidents (the format Waze for Cities ingests); not a certified feed':
    'Те же события как инциденты в стиле CIFS (формат, который принимает Waze for Cities); не сертифицированный фид',
  'Open candidates (internal): what is waiting for confirmation': 'Открытые кандидаты (внутреннее): что ждёт подтверждения',
  'Safety episodes for the fleet safety team (internal role, never in partner feeds)': 'Эпизоды безопасности для службы безопасности таксопарка (внутренняя роль, никогда не в фидах для партнёров)',
  'DataMine: samples by label, level and split; exports': 'DataMine: примеры по меткам, уровням и разбиениям; экспорты',
  'Zoom in': 'Приблизить', 'Zoom out': 'Отдалить',

  // Safety
  'A hard brake, with what the camera saw before it.': 'Резкое торможение и то, что камера видела перед ним.',
  "Safety episodes for the fleet's safety team: collision risks, pedestrians or riders in our path, cut-ins and hard braking, each with its clip. They are for coaching, never a fine and never public, and none of them claims a cause or a fault.":
    'Эпизоды безопасности для службы безопасности таксопарка: риски столкновения, пешеходы или райдеры на пути, подрезания и резкие торможения, каждый со своим клипом. Они для обучения водителей, никогда не штраф и не публично, и ни один не утверждает причину или вину.',
  'safety episodes on this server': 'эпизодов безопасности на этом сервере', 'waiting for a person': 'ждут человека',
  'every episode goes to review': 'каждый эпизод идёт на проверку', 'confirmed by a reviewer': 'подтверждено проверяющим', 'rejected as false alerts': 'отклонено как ложные',
  'By type': 'По типам', "What one front camera and the phone's telemetry can support, nothing more.": 'Только то, что может подтвердить одна передняя камера и телеметрия телефона.',
  'Episodes': 'Эпизоды', 'Newest first. Decide on them in the': 'Сначала новые. Решения принимаются в', '(Safety tab).': '(вкладка Safety).',
  'No safety episodes yet.': 'Эпизодов безопасности пока нет.', 'or run one of the sample trips.': 'или запустите один из примеров.',

  // DataMine
  'Not every hour of driving. The moments worth labelling.': 'Не каждый час езды. Только моменты, которые стоит разметить.',
  'The same clips that feed road events become a regional dataset for automotive AI: chosen by how new, uncertain and well exposed they are, balanced with ordinary driving, split by trip and exported with their rights.':
    'Те же клипы, что питают дорожные события, становятся региональным датасетом для автомобильного ИИ: отобраны по новизне, неуверенности модели и качеству съёмки, сбалансированы обычной ездой, разбиты по поездкам и экспортируются с правами.',
  'trips processed on this server': 'поездок обработано на этом сервере', 'clips with dataset rights': 'клипов с правами на датасет',
  'dataset versions exported': 'версий датасета выгружено', 'Coverage': 'Покрытие',
  'Clips from trips uploaded with dataset rights, excluding rejected ones. Train, val and test are split by trip, never by frame.':
    'Клипы из поездок, загруженных с правами на датасет, без отклонённых. Train, val и test разбиты по поездкам, никогда не по кадрам.',
  'By label': 'По меткам', 'By line': 'По линиям', 'Reviewed, by split': 'Проверенные, по разбиениям', 'none yet': 'пока нет',
  'road': 'дорога', 'safety': 'безопасность', 'baseline': 'обычная езда',
  'Most valuable': 'Самые ценные',
  'Novelty against what is already collected, model uncertainty, image quality and how rare the label still is. The weights are our starting point, not a tuned standard.':
    'Новизна относительно уже собранного, неуверенность модели, качество кадра и редкость метки. Веса — наша отправная точка, а не настроенный стандарт.',
  'Upload a trip with dataset rights to see its clips ranked here.': 'Загрузите поездку с правами на датасет, чтобы увидеть здесь её клипы по ценности.',
  'Export': 'Экспорт', 'Versioned, with provenance': 'С версиями и происхождением',
  'A ZIP with a manifest (label after review, the model\'s label, interval, location and its source, rights scope, data value), anonymised clips, key frames with YOLO boxes and COCO-style annotations. Boxes are model pre-annotations, not checked by a person: we do not call any sample "benchmark-ready".':
    'ZIP с манифестом (метка после проверки, метка модели, интервал, местоположение и его источник, права, ценность), анонимными клипами, ключевыми кадрами с рамками YOLO и разметкой в стиле COCO. Рамки — предразметка моделью, человек их не проверял: мы не называем ни один пример «готовым для бенчмарка».',
  'Export reviewed samples': 'Выгрузить проверенные примеры', 'include unreviewed (raw candidates)': 'включить непроверенные (сырые кандидаты)',
  'Version': 'Версия', 'Created': 'Создано', 'Samples': 'Примеры', 'Contents': 'Содержимое', 'No exports yet.': 'Экспортов пока нет.',
  'exporting…': 'выгрузка…', 'incl. unreviewed': 'вкл. непроверенные', 'Rules': 'Правила', 'Rights first.': 'Сначала права.',
  'road events and the regional dataset (consent recorded at upload). Trips uploaded as "road events only: clips are not used for datasets" never enter an export.':
    'дорожные события и региональный датасет (согласие записывается при загрузке). Поездки, загруженные как «только дорожные события: клипы не используются для датасетов», никогда не попадают в экспорт.',
  'Not only incidents.': 'Не только инциденты.',
  'Each trip adds one random stretch of ordinary driving, so the dataset can still tell how rare an incident is.':
    'Каждая поездка добавляет один случайный отрезок обычной езды, чтобы по датасету было видно, насколько редки инциденты.',
  'No leakage.': 'Без утечек.', 'Split by trip: frames of one drive never sit in both train and test.': 'Разбиение по поездкам: кадры одной поездки никогда не попадают и в train, и в test.',
  'Honest levels.': 'Честные уровни.', 'raw candidate → reviewed (a person confirmed the label). Boxes are model pre-annotations.':
    'сырой кандидат → проверено (человек подтвердил метку). Рамки — предразметка моделью.',
  'Privacy.': 'Приватность.', 'Faces and plate areas are blurred from detector boxes before anything is stored. Best effort, not a guarantee.':
    'Лица и номера размываются по рамкам детектора до сохранения. Это лучшее, что мы можем, но не гарантия.',
  'novelty': 'новизна', 'uncertainty': 'неуверенность', 'quality': 'качество', 'coverage gap': 'пробел в покрытии',

  // Evidence
  'What we measured, on data the models never saw.': 'Что мы измерили на данных, которых модели не видели.',
  'A good detector score does not prove a good event. We report the detector, the events, the data reduction and the speed separately, with the data behind each number and where it fails.':
    'Хорошая оценка детектора ещё не значит хорошие события. Мы отдельно показываем детектор, события, сокращение данных и скорость, с данными за каждым числом и случаями, где система ошибается.',
  'Events': 'События', 'Event mining on labelled trips': 'Поиск событий на размеченных поездках',
  "Each trip's events marked by the team as time intervals; a mined event counts when it overlaps one of the same type. Script:":
    'События каждой поездки размечены командой как интервалы времени; найденное событие засчитывается, если пересекается с размеченным того же типа. Скрипт:',
  'mined events that are real': 'найденных событий настоящие', 'event recall': 'полнота по событиям',
  'false alerts per hour of video': 'ложных срабатываний на час видео', 'every one goes to review, none is published': 'каждое идёт на проверку, ни одно не публикуется',
  'of video kept in event clips': 'видео сохранено в клипах событий',
  'Live': 'Вживую', 'Precision as moderators decide on this server': 'Точность по решениям модераторов на этом сервере',
  'Of the candidates a person has decided on, how many the model got right. Grows with every review.': 'Из кандидатов, по которым человек принял решение, сколько модель угадала. Растёт с каждой проверкой.',
  'No moderator decisions yet on this server.': 'На этом сервере модераторы ещё не принимали решений.',
  'Mined as': 'Найдено как', 'Right': 'Верно', 'Precision': 'Точность', 'No labelled trips evaluated yet.': 'Размеченные поездки ещё не оценивались.',
  'Detector': 'Детектор', 'Road damage, trained by us': 'Дефекты дороги, обучено нами',
  'YOLO11n trained on RDD2022 (6,000 images, 6 countries), evaluated on 1,500 held-out images and on our Tashkent test set.':
    'YOLO11n обучен на RDD2022 (6 000 изображений, 6 стран), проверен на 1 500 отложенных изображениях и на нашем тестовом наборе из Ташкента.',
  'all four damage types, 1,500 held-out RDD2022 images': 'все четыре типа дефектов, 1 500 отложенных изображений RDD2022', 'potholes': 'ямы',
  'Speed': 'Скорость', 'On the server that runs this site': 'На сервере, где работает этот сайт',
  'per analysed frame, both detectors (p50, live on this server)': 'на проанализированный кадр, оба детектора (p50, вживую на этом сервере)',
  'inference device': 'устройство инференса', 'server time per minute of video, including clips': 'время сервера на минуту видео, включая клипы',
  'no trips processed yet': 'поездок ещё не было', 'ms': 'мс', 's': 'с', '/h': '/ч',
  'Known failures': 'Известные ошибки', 'Distant and small objects.': 'Далёкие и мелкие объекты.',
  'A motorcycle 25–50 px tall is missed (our own Tashkent crossing trip): the conflict in that video is not mined.':
    'Мотоцикл высотой 25–50 пикселей не находится (наша поездка через перекрёсток в Ташкенте): конфликт на том видео не найден.',
  'Our own car turning': 'Поворот нашей машины',
  "moves every box sideways; the cut-in rule compensates with the scene's median motion, which fails when few other cars are tracked.":
    'сдвигает все рамки вбок; правило подрезания компенсирует это медианным движением сцены, что не работает, когда в кадре мало других машин.',
  'Time to contact from box growth': 'Время до контакта по росту рамки',
  'also fires when we brake normally behind a queue. That is why safety episodes go to review, never straight to a score.':
    'срабатывает и при обычном торможении в очереди. Поэтому эпизоды безопасности идут на проверку, а не сразу в оценку.',
  'Shadows, patches, manholes, wet asphalt': 'Тени, заплатки, люки, мокрый асфальт',
  'look like damage; night and rain reduce recall (−58% mAP at night in our robustness test).': 'похожи на дефекты; ночь и дождь снижают полноту (−58% mAP ночью в нашем тесте устойчивости).',
  'One forward camera': 'Одна передняя камера',
  'does not see side lanes; GPS on a phone is ±5–15 m, so a pothole can land in the next lane. Positions carry their uncertainty.':
    'не видит боковые полосы; GPS телефона даёт ±5–15 м, поэтому яма может оказаться в соседней полосе. Координаты хранятся с погрешностью.',
  'Privacy': 'Приватность',
  'blurring comes from detector boxes: a face or plate the detector misses can stay visible. Production needs dedicated face and plate models.':
    'размытие идёт по рамкам детектора: пропущенное детектором лицо или номер может остаться видимым. Для продакшена нужны отдельные модели лиц и номеров.',
  'Data': 'Данные', 'Datasets, licences, models': 'Датасеты, лицензии, модели', 'Role': 'Роль', 'Licence': 'Лицензия', 'Source': 'Источник', 'source': 'источник',
  'Labels by the team (one annotator, no second-annotator agreement), from frames reviewed every 0.5 s (video) or every photo (photo sequences) and frame by frame around events; judgement calls are in the label file\'s note column. On a road cracked almost everywhere, which crack counts as \'clearly visible\' is subjective: the family-level road-damage row is more robust than the per-type rows.':
    'Разметка командой (один разметчик, без проверки вторым), по кадрам каждые 0,5 с (видео) или каждому фото (фотопоследовательности) и покадрово вокруг событий; спорные решения описаны в колонке заметок файла разметки. На дороге, где трещины почти везде, какая трещина «хорошо видна» — субъективно: строка по всем дефектам надёжнее строк по типам.',
  "Two sources only: the team's dashcam (one 24 s clip) and one phone's Mapillary photo sequence (134 s, one photo every 1.1 s); one city, daylight; no night, rain or other mounts.":
    'Только два источника: регистратор команды (один клип 24 с) и фотопоследовательность одного телефона из Mapillary (134 с, фото каждые 1,1 с); один город, днём; без ночи, дождя и других креплений.',
  'False alerts per hour are extrapolated from the short labelled footage: one false alert in a minute of video reads as 60 per hour.':
    'Ложные срабатывания в час экстраполированы с короткого размеченного видео: одно ложное за минуту видео — это 60 в час.',
  'kept_ratio includes the 5 s random baseline clip the product keeps per trip; event-only figures are reported next to it.':
    'kept_ratio включает случайный 5-секундный клип обычной езды на поездку; цифры только по событиям показаны рядом.',
  // data registry (docs/data_registry.json)
  'RDD2022 · multi-national road damage': 'RDD2022 · дефекты дорог разных стран',
  'training and held-out test for the road-damage detector': 'обучение и отложенный тест детектора дефектов',
  'Tashkent street imagery · our labels': 'Фото улиц Ташкента · наша разметка',
  'local test set on Uzbek roads; never used for training': 'локальный тестовый набор на дорогах Узбекистана; для обучения не использовался',
  'Tashkent crossing trip · our dashcam': 'Поездка через перекрёсток в Ташкенте · наш регистратор',
  'first labelled trip of the event-mining test (never used for training); not a public sample on the site, since it ends at a crash':
    'первая размеченная поездка теста поиска событий (для обучения не использовалась); не публичный пример на сайте, так как заканчивается аварией',
  'Tashkent street trip · Mapillary photo sequence': 'Поездка по улице Ташкента · фотопоследовательность Mapillary',
  'bundled sample trip (phone-on-a-mount scenario) and the second labelled trip of the event-mining test; never used for training':
    'встроенный пример (сценарий телефона на держателе) и вторая размеченная поездка теста поиска событий; для обучения не использовалась',
  'Taxi ride, Frederiksted · Wikimedia Commons': 'Поездка на такси, Фредерикстед · Wikimedia Commons',
  'Urban dashcam · Wikimedia Commons': 'Городской регистратор · Wikimedia Commons',
  'City driving, Kraków · Wikimedia Commons': 'Езда по городу, Краков · Wikimedia Commons',
  'bundled sample trip for visitors without footage; not labelled, not used for training or metrics':
    'встроенный пример для посетителей без своего видео; не размечен, не используется для обучения и метрик',
  'COCO-pretrained YOLO11n weights': 'Веса YOLO11n, предобученные на COCO',
  'road-user detector (person, bicycle, car, motorcycle, bus, truck) and starting point for our road-damage model':
    'детектор участников движения (пешеход, велосипед, машина, мотоцикл, автобус, грузовик) и отправная точка для нашей модели дефектов',
  'YOLO11n (COCO) · road users': 'YOLO11n (COCO) · участники движения',
  'pedestrians, riders, cars, trucks, buses: tracking, collision risk, cut-ins, blurring': 'пешеходы, райдеры, машины, грузовики, автобусы: трекинг, риск столкновения, подрезания, размытие',
  'YOLO11n road damage · trained by us': 'YOLO11n дефекты дороги · обучено нами',
  'pothole, alligator, transverse and longitudinal cracks': 'ямы, сетка трещин, поперечные и продольные трещины',
  'dashcam footage recorded and provided by the SwarmSight team (benchmarks/trips/tashkent_crossing.mp4: benchmark only, not a public sample)':
    'запись регистратора, снятая и предоставленная командой SwarmSight (benchmarks/trips/tashkent_crossing.mp4: только для бенчмарка, не публичный пример)',
  'Moderator token (set by the team for this deployment):': 'Токен модератора (задаётся командой для этого сайта):',
};

const W = { confidence: 'уверенность', severity: 'серьёзность', uncertainty: 'неуверенность', novelty: 'новизна', quality: 'качество',
  'coverage gap': 'пробел в покрытии', reliability: 'надёжность', conf: 'увер.' };
const num = '([\\d.,]+)';
const PATTERNS = [
  [/^(\d+) events? in ([\d.]+) s of driving$/, (m, n, s) => `${n} ${pl(+n, 'событие', 'события', 'событий')} за ${s} с поездки`],
  [/^(\d+) events? in one photo$/, (m, n) => `${n} ${pl(+n, 'событие', 'события', 'событий')} на одном фото`],
  [/^No events in ([\d.]+) s of driving$/, (m, s) => `Нет событий за ${s} с поездки`],
  [/^(\d+) road$/, (m, n) => `дорога: ${n}`],
  [/^(\d+) safety\. Each is a candidate until a person confirms it\.$/, (m, n) => `безопасность: ${n}. Каждое остаётся кандидатом, пока человек его не подтвердит.`],
  [/^Trip (\w+)$/, (m, id) => `Поездка ${id}`],
  [/^Road event #(\d+)$/, (m, id) => `Дорожное событие №${id}`],
  [/^road event #(\d+)$/, (m, id) => `дорожное событие №${id}`],
  [new RegExp(`^${num} s of ${num} s$`), (m, a, b) => `${a} с из ${b} с`],
  [/^(\d+) \(incl\. ([\d.]+) s baseline\)$/, (m, n, s) => `${n} (вкл. ${s} с обычной езды)`],
  [new RegExp(`^(\\d+) frames at ${num} fps$`), (m, n, f) => `${n} кадров при ${f} к/с`],
  [new RegExp(`^${num} ms per frame$`), (m, v) => `${v} мс на кадр`],
  [new RegExp(`^p95 ${num} ms per frame$`), (m, v) => `p95 ${v} мс на кадр`],
  [new RegExp(`^${num} s for ${num} s of video \\(${num} s cutting clips\\)$`), (m, a, b, c) => `${a} с на ${b} с видео (${c} с на нарезку клипов)`],
  [new RegExp(`^${num}–${num} s$`), (m, a, b) => `${a}–${b} с`],
  [new RegExp(`^${num} s$`), (m, a) => `${a} с`],
  [new RegExp(`^peak ${num} s$`), (m, a) => `пик ${a} с`],
  [new RegExp(`^(confidence|severity|uncertainty|novelty|quality|coverage gap|reliability|conf) ${num}$`), (m, w, v) => `${W[w]} ${v}`],
  [new RegExp(`^time to contact ${num} s$`), (m, v) => `время до контакта ${v} с`],
  [new RegExp(`^contact ${num} s$`), (m, v) => `контакт ${v} с`],
  [/^seen in (\d+) analysed frames?$/, (m, n) => `замечено на ${n} ${pl(+n, 'кадре', 'кадрах', 'кадрах')}`],
  [/^(\d+) instance\(s\) in the photo$/, (m, n) => `${n} на фото`],
  [new RegExp(`^moved in from the (left|right) over ${num} s$`), (m, side, v) => `перестроился ${side === 'left' ? 'слева' : 'справа'} за ${v} с`],
  [/^also: (.+)$/, (m, rest) => `также: ${rest.split(', ').map(x => RU[x] || x).join(', ')}`],
  [/^peak deceleration (.+) m\/s² \((IMU|GPS speed)\), (.+) km\/h$/, (m, a, sig, b) => `пиковое замедление ${a} м/с² (${sig === 'IMU' ? 'IMU' : 'скорость по GPS'}), ${b} км/ч`],
  [/^(\d+) models$/, (m, n) => `${n} ${pl(+n, 'модель', 'модели', 'моделей')}`],
  [/^(\d+) frames$/, (m, n) => `${n} ${pl(+n, 'кадр', 'кадра', 'кадров')}`],
  [new RegExp(`^p95 ${num} ms$`), (m, v) => `p95 ${v} мс`],
  [/^(\d+) of (\d+) labelled events$/, (m, a, b) => `${a} из ${b} размеченных событий`],
  [/^(\d+) of (\d+) labelled events found$/, (m, a, b) => `найдено ${a} из ${b} размеченных событий`],
  [/^(\d+) false alerts?$/, (m, n) => `${n} ложных`],
  [/^(\d+) trips?$/, (m, n) => `${n} ${pl(+n, 'поездка', 'поездки', 'поездок')}`],
  [/^(\d+%) of labelled events inside them$/, (m, p) => `${p} размеченных событий внутри них`],
  [/^\+5 s baseline per trip$/, () => '+5 с обычной езды на поездку'],
  [/^precision (\d+%) at the operating point$/, (m, p) => `точность ${p} в рабочей точке`],
  [/^RDD2022 · (.+) held-out images, 6 countries$/, (m, n) => `RDD2022 · ${n} отложенных изображений, 6 стран`],
  [/^(\d+) new$/, (m, n) => `${n} новых`],
  [/^(\d+) repeat sightings of an event already found$/, (m, n) => `${n} повторных наблюдений уже найденного события`],
  [/^(\d+) false$/, (m, n) => `${n} ложных`],
  [/^of (\d+) s of video kept as clips$/, (m, n) => `из ${n} с видео сохранено в клипах`],
  [/^(\d+) reviewed$/, (m, n) => `${n} проверено`], [/^(\d+) raw$/, (m, n) => `${n} сырых`], [/^(\d+) rejected$/, (m, n) => `${n} отклонено`],
  [/^Data value = (.+)$/, (m, f) => `Ценность = ${f.replace(/coverage gap|novelty|uncertainty|quality/g, w => W[w])}`],
  [/^Tashkent street photos, image level \((\d+) images; random ([\d.]+)\)$/, (m, n, r) => `Фото улиц Ташкента, по изображениям (${n} изображений; случайно ${r})`],
  [/^precision in Tashkent at the operating threshold$/, () => 'точность в Ташкенте при рабочем пороге'],
  [/^recall (\d+%)$/, (m, p) => `полнота ${p}`],
  [/^By country \(mAP@\.5\): (.+)$/, (m, rest) => `По странам (mAP@.5): ${rest}`],
  [/^Tashkent labels: image-level, first pass by Claude \(LLM vision\) without model pre-labels; human verification pending\.$/, () => 'Разметка Ташкента: по изображениям, первый проход Claude (зрение LLM) без предразметки моделью; проверка человеком ещё не сделана.'],
  [/^Tiny test set: (\d+) video\(s\), ([\d.]+) s of video, (\d+) labelled event\(s\); 95 % intervals are given for every rate\.$/, (m, v, s, e) => `Маленький тестовый набор: ${v} видео, ${s} с видео, ${e} размеченных событий; для каждой доли даны 95% интервалы.`],
  [/^(\d+) labelled trip\(s\), (\d+) s of video\.$/, (m, n, s) => `${n} размеченных поездки, ${s} с видео.`],
  [/^(\d+) device\(s\)$/, (m, n) => `${n} ${pl(+n, 'устройство', 'устройства', 'устройств')}`],
  [/^(\d+) observation\(s\)$/, (m, n) => `${n} ${pl(+n, 'наблюдение', 'наблюдения', 'наблюдений')}`],
  [/^\(model: (.+)\)$/, (m, t) => `(модель: ${RU[t] || t})`],
  [/^(.+) unless re-observed$/, (m, d) => `${d}, если не замечено снова`],
  [/^uploading ([\d.]+) MB…(.*)$/, (m, n, rest) => `загрузка ${n} МБ…${rest ? ' ' + (RU[rest.trim()] || rest.trim()) : ''}`],
  [/^analysing$/, () => 'анализ'],
  [/^t = ([\d.]+) s$/, (m, v) => `t = ${v} с`],
  [/^Download$/, () => 'Скачать'], [/^([\d.]+) MB$/, (m, n) => `${n} МБ`],
  [/^exported (\S+): (\d+) samples?(.*)$/, (m, v, n, rest) => `выгружено ${v}: ${n} ${pl(+n, 'пример', 'примера', 'примеров')}${rest ? ' (сначала подтвердите клипы из поездок, загруженных с правами на датасет)' : ''}`],
  [/^our label: (.+)$/, (m, rest) => `наша метка: ${rest.split(', ').map(x => RU[x] || x).join(', ')}`],
  [/^(.+) \+(\d+)$/, (m, t, n) => RU[t] ? `${RU[t]} +${n}` : m],
  [/^Tashkent · Mapillary (\d+)$/, (m, id) => `Ташкент · Mapillary ${id}`],
];

const EDGE = /^([\s.·,:;()→]*)([\s\S]*?)([\s.·,:;()→]*)$/;

function core(s) {
  if (RU[s] != null) return RU[s];
  for (const [re, fn] of PATTERNS) { const m = s.match(re); if (m) { const r = fn(...m); if (r !== m[0]) return r; } }
  return null;
}

export function t(text) {
  if (lang !== 'ru' || !text || !/[A-Za-z]/.test(text)) return text;
  const lead = text.match(/^\s*/)[0], trail = text.match(/\s*$/)[0];
  const s = text.trim().replace(/\s+/g, ' ');
  let r = core(s);
  if (r == null) {
    // punctuation around a fragment between inline elements: try without it on the left, the right, then both
    const a = s.replace(/^[\s.·,:;()→]+/, ''), b = s.replace(/[\s.·,:;()→]+$/, '');
    const [, pre, mid, post] = s.match(EDGE);
    let c;
    if (a !== s && (c = core(a)) != null) r = s.slice(0, s.length - a.length) + c;
    else if (b !== s && (c = core(b)) != null) r = c + s.slice(b.length);
    else if (mid !== s && (c = core(mid)) != null) r = pre + c + post;
  }
  if (r == null) {
    for (const sep of [' · ', ' → ']) {
      if (!s.includes(sep)) continue;
      const parts = s.split(sep);
      const tr = parts.map(x => t(x));
      if (tr.some((x, i) => x !== parts[i])) { r = tr.join(sep); break; }
    }
  }
  return r == null ? text : lead + r + trail;
}

const ATTRS = ['placeholder', 'title', 'alt', 'aria-label'];
const done = new WeakMap();

function translateNode(n) {
  if (n.nodeType === 3) {
    const p = n.parentElement;
    if (!p || p.closest('script,style,code,.leaflet-control-attribution')) return;
    if (done.get(n) === n.nodeValue) return;
    const v = t(n.nodeValue);
    if (v !== n.nodeValue) n.nodeValue = v;
    done.set(n, n.nodeValue);
  } else if (n.nodeType === 1) {
    for (const a of ATTRS) { const v = n.getAttribute(a); if (v) { const tv = t(v); if (tv !== v) n.setAttribute(a, tv); } }
    const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let c;
    while ((c = w.nextNode())) {
      if (c.nodeType === 3) translateNode(c);
      else for (const a of ATTRS) { const v = c.getAttribute(a); if (v) { const tv = t(v); if (tv !== v) c.setAttribute(a, tv); } }
    }
  }
}

export function startI18n() {
  document.documentElement.lang = lang;
  const btn = document.getElementById('lang');
  if (btn) { btn.textContent = lang === 'ru' ? 'EN' : 'RU'; btn.title = lang === 'ru' ? 'English' : 'Русский'; btn.onclick = () => setLang(lang === 'ru' ? 'en' : 'ru'); }
  if (lang !== 'ru') return;
  document.title = 'SwarmSight · Сеть данных таксопарков';
  translateNode(document.body);
  new MutationObserver(ms => {
    for (const m of ms) {
      if (m.type === 'characterData') translateNode(m.target);
      else { m.addedNodes.forEach(translateNode); if (m.type === 'attributes') translateNode(m.target); }
    }
  }).observe(document.body, { childList: true, subtree: true, characterData: true });
}
