import os
import re
import time
import random
from urllib.parse import urlparse

import requests


# =========================================================
# НАСТРОЙКИ
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

GROQ_MODEL = os.getenv(
    "GROQ_MODEL",
    "openai/gpt-oss-20b"
).strip()

NIKOLAI_USER_ID = os.getenv(
    "NIKOLAI_USER_ID",
    ""
).strip()

AUTO_CHECK = os.getenv(
    "AUTO_CHECK",
    "false"
).strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

TG_API = (
    f"https://api.telegram.org/"
    f"bot{TELEGRAM_BOT_TOKEN}"
)

GROQ_API = (
    "https://api.groq.com/"
    "openai/v1/chat/completions"
)

TAVILY_API = (
    "https://api.tavily.com/search"
)

URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.IGNORECASE,
)

MAX_NEWS_CHARS = 3200
MAX_SEARCH_QUERY_CHARS = 700

MAX_SEARCH_QUERIES = 4
MAX_RESULTS_PER_QUERY = 5

MAX_AI_SOURCES = 12
MAX_TG_SOURCES = 6
MAX_SOURCE_SNIPPET_CHARS = 750


# =========================================================
# TELEGRAM-АЛЬБОМЫ
# =========================================================

MEDIA_GROUP_TTL = 3600

RECENT_MEDIA_ACTIONS = {}
MEDIA_GROUP_TEXT_CACHE = {}


# =========================================================
# КОМАНДЫ ФАКТЧЕКА
# =========================================================

CHECK_WORDS = (
    "проверь",
    "проверить",
    "фактчек",
    "чекни",
    "проверка",
    "это правда",
    "это правда?",
)


# =========================================================
# ПРОМПТ ФАКТЧЕКА
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер в дружеском пацанском Telegram-чате.

Тебе передают:
1. текст новости;
2. результаты нескольких веб-поисков Tavily;
3. среди результатов могут быть русскоязычные и англоязычные источники.

Проверяй только по найденным данным.
Ничего не выдумывай.

========================================
СНАЧАЛА РАЗЛОЖИ УТВЕРЖДЕНИЕ
========================================

Перед вердиктом мысленно разбей новость
на отдельные проверяемые утверждения.

Например фраза:

"Организация за один день выиграла два турнира:
утром по Dota 2, вечером по CS2"

содержит несколько отдельных фактов:

1. победа команды/состава по Dota 2;
2. победа команды/состава по CS2;
3. обе команды относятся к одной организации;
4. события произошли в одну календарную дату.

НЕЛЬЗЯ требовать, чтобы один источник
обязательно подтверждал всю длинную фразу целиком.

Разные части утверждения могут подтверждаться
разными независимыми источниками.

Если две части новости подтверждаются
разными надежными источниками,
сопоставь их по:

- названию организации;
- названию команды/состава;
- турниру;
- дате;
- времени;
- сумме;
- месту;
- другим ключевым деталям.

========================================
ЯЗЫК ИСТОЧНИКОВ
========================================

Русские и английские источники
проверяй на равных.

Если событие международное,
киберспортивное, технологическое,
научное, игровое, финансовое
или связано с зарубежной компанией,
англоязычные профильные источники
могут быть важнее русскоязычных пересказов.

Не игнорируй источник только потому,
что он на английском.

========================================
МАСШТАБ СОБЫТИЯ
========================================

Мысленно определи масштаб:

- локальное / городское;
- региональное;
- федеральное;
- международное;
- профильное событие
  (спорт, киберспорт, технологии, наука и т.д.).

Не обязательно писать этот масштаб пользователю.

========================================
ГЛАВНОЕ ПРАВИЛО
========================================

ОТСУТСТВИЕ публикации
НЕ является доказательством того,
что новость ложная.

Никогда не ставь:

🔴 ПИЗДЁЖ

только потому, что:

- Reuters не написал;
- BBC не написал;
- федеральные СМИ не написали;
- крупные СМИ не нашли эту историю;
- нет статьи с точно такой же формулировкой;
- один конкретный источник не упоминает
  другую часть составного утверждения.

"Не нашёл подтверждения"
НЕ равно
"нашёл опровержение".

========================================
ЛОКАЛЬНЫЕ / ГОРОДСКИЕ НОВОСТИ
========================================

Для локальных событий важными источниками являются:

1. местный суд;
2. судебные органы;
3. прокуратура;
4. Следственный комитет;
5. МВД;
6. администрация города;
7. администрация района;
8. другие официальные местные ведомства;
9. городские СМИ;
10. региональные СМИ;
11. несколько независимых местных источников.

Если событие происходит, например,
в Новороссийске, Reuters вообще
не обязан об этом писать.

Для такой новости нужно учитывать:

- суд Новороссийска;
- прокуратуру;
- Следственный комитет;
- МВД;
- администрацию;
- СМИ Новороссийска;
- СМИ Краснодарского края.

Отсутствие федеральных публикаций
для городского события нормально.

========================================
РЕГИОНАЛЬНЫЕ НОВОСТИ
========================================

Приоритет:

1. официальные органы региона;
2. прокуратура;
3. суд;
4. Следственный комитет;
5. МВД;
6. региональные СМИ;
7. федеральные СМИ.

Федеральные СМИ являются дополнительным
подтверждением, но не обязательным.

========================================
ФЕДЕРАЛЬНЫЕ И МЕЖДУНАРОДНЫЕ НОВОСТИ
========================================

Приоритет:

1. официальные документы;
2. первичные источники;
3. профильные официальные источники;
4. Reuters;
5. AP;
6. AFP;
7. крупные СМИ;
8. профильные авторитетные СМИ;
9. остальные источники.

========================================
ПРОФИЛЬНЫЕ СОБЫТИЯ
========================================

Для спорта, киберспорта, технологий,
науки, игр и других профильных тем
не требуй подтверждения от обычных
новостных СМИ, если есть надежные
профильные источники.

Примеры:

- официальный сайт турнира;
- официальный сайт лиги;
- официальный сайт команды;
- официальный аккаунт организатора;
- профильная статистическая база;
- крупное профильное издание.

Профильный надежный источник
может быть достаточным подтверждением
профильного факта.

========================================
НЕЗАВИСИМОСТЬ ИСТОЧНИКОВ
========================================

Несколько сайтов могут подтверждать событие.

НО:

если 5 сайтов просто перепечатали
один и тот же текст из одного источника,
не считай это пятью независимыми
подтверждениями.

========================================
ВЕРДИКТЫ
========================================

Используй РОВНО один вердикт:

🟢 НЕ ПИЗДЁЖ

Ставь, если ключевое утверждение
нормально подтверждается подходящими
для темы и масштаба события источниками.

🟡 ПОЛУПИЗДЁЖ

Ставь, если основное событие подтверждается,
но часть деталей:

- преувеличена;
- искажена;
- не подтверждена;
- подана неточно.

🟠 НАЕБАЛИ С КОНТЕКСТОМ

Ставь, если факты формально настоящие,
но:

- вырваны из контекста;
- из них сделали неправильный вывод;
- заголовок вводит в заблуждение;
- важные обстоятельства специально опущены.

🔴 ПИЗДЁЖ

Ставь ТОЛЬКО если:

- надежный источник прямо опровергает утверждение;
- найдены факты, несовместимые с утверждением;
- ключевой факт доказанно ложный.

КРИТИЧЕСКИ ВАЖНО:

НЕЛЬЗЯ ставить 🔴 ПИЗДЁЖ
просто потому, что подтверждений мало.

⚪ ХУЙ ПОЙМЁШЬ ПОКА

Ставь, если:

- данных недостаточно;
- событие слишком свежее;
- есть только неподтвержденные сообщения;
- источники противоречат друг другу;
- невозможно уверенно подтвердить
  или опровергнуть ключевой факт.

========================================
ФОРМАТ ОТВЕТА
========================================

Первая строка:

ТОЛЬКО вердикт.

Потом 2–4 коротких предложения:

- что подтверждается;
- что не подтверждается;
- где подвох;
- насколько надежны найденные данные.

Если новость составная,
кратко укажи результат по её ключевым частям.

Последняя строка:

Уверенность: N/10

========================================
СТИЛЬ
========================================

- коротко;
- понятно;
- по-пацански;
- мат допустим;
- не пихай мат в каждое предложение;
- без канцелярита;
- без длинных лекций;
- URL в ответ не вставляй;
- список источников не пиши;
- источники бот покажет кнопками.

Не шути про:

- родителей;
- родственников;
- семью;
- детей;
- болезни;
- смерть;
- трагедии.
""".strip()


# =========================================================
# TELEGRAM API
# =========================================================

def tg(
    method,
    payload=None,
    timeout=35,
):
    response = requests.post(
        f"{TG_API}/{method}",
        json=payload or {},
        timeout=timeout,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {data}"
        )

    return data


def send_message(
    chat_id,
    text,
    reply_to_message_id=None,
    reply_markup=None,
):
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }

    if reply_to_message_id:
        payload["reply_parameters"] = {
            "message_id": reply_to_message_id,
            "allow_sending_without_reply": True,
        }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return tg(
        "sendMessage",
        payload,
    )


def edit_message(
    chat_id,
    message_id,
    text,
    reply_markup=None,
):
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }

    if reply_markup:
        payload["reply_markup"] = reply_markup

    return tg(
        "editMessageText",
        payload,
    )


# =========================================================
# ТЕКСТ
# =========================================================

def normalize(text):
    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def message_text(message):
    return (
        message.get("text")
        or message.get("caption")
        or ""
    ).strip()


# =========================================================
# TELEGRAM-АЛЬБОМЫ
# =========================================================

def cleanup_media_caches():
    now = time.time()

    for storage in (
        RECENT_MEDIA_ACTIONS,
        MEDIA_GROUP_TEXT_CACHE,
    ):
        stale = [
            key
            for key, value in storage.items()
            if (
                now - value["ts"]
                > MEDIA_GROUP_TTL
            )
        ]

        for key in stale:
            storage.pop(
                key,
                None,
            )


def remember_media_group_text(message):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get("chat")
        or {}
    ).get("id")

    text = message_text(
        message
    )

    if (
        not media_group_id
        or not chat_id
        or not text
    ):
        return

    key = (
        str(chat_id),
        str(media_group_id),
    )

    old = MEDIA_GROUP_TEXT_CACHE.get(
        key
    )

    if (
        not old
        or len(text)
        > len(old.get("text", ""))
    ):
        MEDIA_GROUP_TEXT_CACHE[key] = {
            "ts": time.time(),
            "text": text,
        }


def cached_media_group_text(message):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get("chat")
        or {}
    ).get("id")

    if (
        not media_group_id
        or not chat_id
    ):
        return ""

    key = (
        str(chat_id),
        str(media_group_id),
    )

    return (
        MEDIA_GROUP_TEXT_CACHE.get(key)
        or {}
    ).get(
        "text",
        "",
    )


def extract_news_text(message):
    return (
        message_text(message)
        or cached_media_group_text(message)
    )


def media_action_already_done(
    message,
    action,
):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get("chat")
        or {}
    ).get("id")

    if (
        not media_group_id
        or not chat_id
    ):
        return False

    cleanup_media_caches()

    key = (
        action,
        str(chat_id),
        str(media_group_id),
    )

    if key in RECENT_MEDIA_ACTIONS:
        return True

    RECENT_MEDIA_ACTIONS[key] = {
        "ts": time.time()
    }

    return False


# =========================================================
# КОЛЯ
# =========================================================

def is_nikolai(user):
    if not user:
        return False

    user_id = str(
        user.get(
            "id",
            "",
        )
    )

    if NIKOLAI_USER_ID:
        return (
            user_id
            == NIKOLAI_USER_ID
        )

    username = (
        user.get("username")
        or ""
    ).lower()

    full_name = normalize(
        f"{user.get('first_name', '')} "
        f"{user.get('last_name', '')}"
    ).lower()

    markers = (
        "николай",
        "коля",
        "nikolai",
        "nikolay",
        "kolya",
        "kolia",
    )

    return any(
        marker in username
        or marker in full_name
        for marker in markers
    )


def kolya_roast():
    variants = [
        "Коля-либераха опять вышел на смену в Министерство Набросов 😄",
        "Либераха Николай снова на доставке инфошизы 📦",
        "Коля, ты опять в телеграм-помойке купался? 😄",
        "Коля-либераха опять что-то нарыл. Пацаны, держимся.",
        "Либераха пойман на очередной доставке полупиздежа 📦",
        "Коля, ну ёбаный ты поставщик сенсаций.",
        "Николай опять принёс свежак из информационной канализации.",
        "А, новость от Коли. Отдел набросов работает без выходных.",
        "Коля-либераха снова разгоняет информационный туман.",
        "Коля, телеграм-каналы тебе уже процент должны платить.",
        "Николай, ну ты хуесос информационного пространства 😄 Опять привёз свежак.",
        "Коля-либераха на посту: новость доставлена, здравый смысл в пути.",
        "Коля опять открыл оптовый склад охуительных историй.",
        "Коля-либераха, ну хоть раз принеси новость без запаха наброса 😄",
        "Так, пацаны, Коля снова притащил интернет в пакете.",
    ]

    return random.choice(
        variants
    )


# =========================================================
# НОВОСТЬ ИЛИ ОБЫЧНАЯ ПЕРЕПИСКА
# =========================================================

def is_forwarded(message):
    return bool(
        message.get("forward_origin")
        or message.get("forward_date")
        or message.get("forward_from")
        or message.get("forward_from_chat")
    )


def is_forwarded_from_channel(message):
    origin = (
        message.get("forward_origin")
        or {}
    )

    if origin.get("type") == "channel":
        return True

    forward_chat = (
        message.get("forward_from_chat")
        or {}
    )

    return (
        forward_chat.get("type")
        == "channel"
    )


def has_link(message):
    return bool(
        URL_RE.search(
            extract_news_text(
                message
            )
        )
    )


def news_like_text(message):
    text = normalize(
        extract_news_text(
            message
        )
    )

    if len(text) < 90:
        return False

    words = re.findall(
        r"\w+",
        text,
        flags=re.UNICODE,
    )

    return (
        len(words)
        >= 10
    )


def looks_like_news(message):
    return bool(
        has_link(message)
        or is_forwarded_from_channel(message)
        or (
            is_forwarded(message)
            and len(
                normalize(
                    extract_news_text(
                        message
                    )
                )
            ) >= 40
        )
        or news_like_text(message)
    )


# =========================================================
# КОМАНДА "ПРОВЕРЬ"
# =========================================================

def parse_manual_check(message):
    raw = message_text(
        message
    )

    if not raw:
        return None

    lower = normalize(
        raw
    ).lower()

    command_match = re.match(
        r"^/(?:check|factcheck)"
        r"(?:@[A-Za-z0-9_]+)?"
        r"(?:\s+|$)",
        raw,
        flags=re.IGNORECASE,
    )

    natural_trigger = None

    if not command_match:
        for trigger in CHECK_WORDS:
            if (
                lower == trigger
                or lower.startswith(
                    trigger + " "
                )
            ):
                natural_trigger = trigger
                break

    if (
        not command_match
        and not natural_trigger
    ):
        return None

    replied = message.get(
        "reply_to_message"
    )

    if replied:
        if not looks_like_news(
            replied
        ):
            return {
                "invalid_reply": True,
                "source_message_id": replied.get(
                    "message_id"
                ),
            }

        return {
            "news_text": extract_news_text(
                replied
            ),
            "source_message_id": replied.get(
                "message_id"
            ),
        }

    if command_match:
        news_text = raw[
            command_match.end():
        ].strip()
    else:
        news_text = raw[
            len(natural_trigger):
        ].strip()

    return {
        "news_text": news_text,
        "source_message_id": message.get(
            "message_id"
        ),
    }


# =========================================================
# ПОИСКОВЫЕ ЗАПРОСЫ
# =========================================================

def build_search_query(news_text):
    text = normalize(
        news_text
    )[:MAX_NEWS_CHARS]

    urls = URL_RE.findall(
        text
    )

    without_urls = normalize(
        URL_RE.sub(
            " ",
            text,
        )
    )

    if without_urls:
        query = without_urls

        if urls:
            query += (
                " "
                + urls[0]
            )

    elif urls:
        query = urls[0]

    else:
        query = text

    return query[
        :MAX_SEARCH_QUERY_CHARS
    ]


def groq_build_search_queries(news_text):
    prompt = (
        "Ты готовишь поисковые запросы для фактчека.\n"
        "Разбери новость на 1-2 ключевых проверяемых утверждения.\n"
        "Сделай короткие поисковые запросы на русском и английском.\n\n"
        "Правила:\n"
        "- сохраняй имена, команды, компании, турниры, города и даты;\n"
        "- не придумывай новые имена, даты и события;\n"
        "- если утверждение составное, ищи его части отдельно;\n"
        "- английский запрос должен быть естественным;\n"
        "- максимум 4 строки;\n"
        "- постарайся дать минимум один RU и один EN;\n"
        "- не делай фактчек и не пиши объяснения.\n\n"
        "Формат каждой строки:\n"
        "RU | поисковый запрос\n"
        "EN | search query\n\n"
        "НОВОСТЬ:\n"
        f"{news_text[:MAX_NEWS_CHARS]}"
    )

    response = requests.post(
        GROQ_API,
        headers={
            "Authorization":
                f"Bearer {GROQ_API_KEY}",
            "Content-Type":
                "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Ты создаёшь только поисковые запросы "
                        "для веб-поиска. Ничего не выдумывай."
                    ),
                },
                {
                    "role": "user",
                    "content": prompt,
                },
            ],
            "temperature": 0.10,
            "reasoning_effort": "low",
            "include_reasoning": False,
            "max_completion_tokens": 500,
            "stream": False,
        },
        timeout=35,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "GROQ_401"
        )

    if response.status_code == 429:
        raise RuntimeError(
            "GROQ_429"
        )

    response.raise_for_status()

    data = response.json()

    choices = data.get(
        "choices"
    ) or []

    if not choices:
        return []

    content = (
        choices[0].get(
            "message"
        )
        or {}
    ).get(
        "content"
    ) or ""

    if isinstance(
        content,
        list,
    ):
        parts = []

        for item in content:
            if (
                isinstance(
                    item,
                    dict,
                )
                and item.get(
                    "text"
                )
            ):
                parts.append(
                    str(
                        item[
                            "text"
                        ]
                    )
                )

        content = "\n".join(
            parts
        )

    if not isinstance(
        content,
        str,
    ):
        return []

    queries = []
    seen = set()

    for raw_line in content.splitlines():
        line = (
            raw_line
            .strip()
            .strip("`")
            .strip()
        )

        if not line:
            continue

        line = re.sub(
            r"^(?:[-*]\s*)?"
            r"(?:RU|EN)\s*"
            r"[\|\:\-–—]\s*",
            "",
            line,
            flags=re.IGNORECASE,
        ).strip()

        line = re.sub(
            r"^\d+[\.\)]\s*",
            "",
            line,
        ).strip()

        if len(line) < 4:
            continue

        line = line[
            :MAX_SEARCH_QUERY_CHARS
        ]

        key = line.lower()

        if key in seen:
            continue

        seen.add(
            key
        )

        queries.append(
            line
        )

        if (
            len(queries)
            >= MAX_SEARCH_QUERIES
        ):
            break

    return queries


def build_search_queries(news_text):
    base_query = build_search_query(
        news_text
    )

    queries = []
    seen = set()

    def add_query(query):
        query = normalize(
            query
        )[:MAX_SEARCH_QUERY_CHARS]

        if len(query) < 4:
            return

        key = query.lower()

        if key in seen:
            return

        seen.add(
            key
        )

        queries.append(
            query
        )

    add_query(
        base_query
    )

    try:
        generated = groq_build_search_queries(
            news_text
        )

    except Exception as exc:
        print(
            (
                "Search-query generation warning: "
                f"{type(exc).__name__}: {exc}"
            ),
            flush=True,
        )

        generated = []

    for query in generated:
        add_query(
            query
        )

        if (
            len(queries)
            >= MAX_SEARCH_QUERIES
        ):
            break

    return queries[
        :MAX_SEARCH_QUERIES
    ]


# =========================================================
# ПРИОРИТЕТ ИСТОЧНИКОВ
# =========================================================

def source_domain(url):
    return (
        urlparse(
            url
        )
        .netloc
        .lower()
        .removeprefix(
            "www."
        )
    )


def source_priority(url):
    domain = source_domain(
        url
    )

    official_domains = (
        "sudrf.ru",
        "genproc.gov.ru",
        "epp.genproc.gov.ru",
        "sledcom.ru",
        "мвд.рф",
        "xn--b1aew.xn--p1ai",
        "government.ru",
        "kremlin.ru",
        "publication.pravo.gov.ru",
        "pravo.gov.ru",
        "europa.eu",
        "who.int",
        "un.org",
        "nato.int",
    )

    official_markers = (
        ".gov",
        ".gov.",
        "gov.",
        "president.",
        "government.",
        "parliament.",
        "prokuratura.",
        "prosecutor.",
        "court.",
        "courts.",
    )

    wire_domains = (
        "reuters.com",
        "apnews.com",
        "afp.com",
    )

    major_domains = (
        "bbc.com",
        "bbc.co.uk",
        "yle.fi",
        "dw.com",
        "france24.com",
        "theguardian.com",
        "nytimes.com",
        "ft.com",
    )

    specialist_domains = (
        "hltv.org",
        "liquipedia.net",
        "esportsworldcup.com",
        "teamspirit.gg",
        "steamcommunity.com",
        "github.com",
        "arxiv.org",
    )

    if any(
        domain == item
        or domain.endswith(
            "." + item
        )
        for item in official_domains
    ):
        return 0

    if any(
        marker in domain
        for marker in official_markers
    ):
        return 0

    if any(
        domain == item
        or domain.endswith(
            "." + item
        )
        for item in wire_domains
    ):
        return 1

    if any(
        domain == item
        or domain.endswith(
            "." + item
        )
        for item in specialist_domains
    ):
        return 2

    if any(
        domain == item
        or domain.endswith(
            "." + item
        )
        for item in major_domains
    ):
        return 2

    return 3


# =========================================================
# TAVILY
# =========================================================

def tavily_search_once(
    query,
    query_index,
):
    response = requests.post(
        TAVILY_API,
        headers={
            "Authorization":
                f"Bearer {TAVILY_API_KEY}",
            "Content-Type":
                "application/json",
        },
        json={
            "query": query,
            "search_depth": "basic",
            "topic": "general",
            "max_results":
                MAX_RESULTS_PER_QUERY,
            "include_answer": False,
            "include_raw_content": False,
            "include_images": False,
            "auto_parameters": False,
        },
        timeout=30,
    )

    if response.status_code == 401:
        raise RuntimeError(
            "TAVILY_401"
        )

    if response.status_code == 429:
        raise RuntimeError(
            "TAVILY_429"
        )

    response.raise_for_status()

    data = response.json()

    results = []

    for item in data.get(
        "results",
        [],
    ):
        url = (
            item.get("url")
            or ""
        ).strip()

        if not url:
            continue

        results.append({
            "title": normalize(
                item.get("title")
                or "Источник"
            ),
            "url": url,
            "content": normalize(
                item.get("content")
                or ""
            ),
            "score": (
                item.get("score")
                or 0
            ),
            "query_index":
                query_index,
            "search_query":
                query,
        })

    return results


def tavily_search(news_text):
    queries = build_search_queries(
        news_text
    )

    print(
        (
            "Factcheck search queries: "
            + " || ".join(
                queries
            )
        ),
        flush=True,
    )

    merged = {}
    order = []

    for query_index, query in enumerate(
        queries
    ):
        items = tavily_search_once(
            query,
            query_index,
        )

        for item in items:
            clean_url = (
                item["url"]
                .split("#", 1)[0]
                .rstrip("/")
            )

            if not clean_url:
                continue

            old = merged.get(
                clean_url
            )

            if old is None:
                item[
                    "matched_queries"
                ] = {
                    query_index
                }

                merged[
                    clean_url
                ] = item

                order.append(
                    clean_url
                )

                continue

            old.setdefault(
                "matched_queries",
                set(),
            ).add(
                query_index
            )

            if (
                item.get("score", 0)
                > old.get("score", 0)
            ):
                old["score"] = (
                    item.get("score")
                    or 0
                )

                old["title"] = (
                    item.get("title")
                    or old.get("title")
                )

                old["content"] = (
                    item.get("content")
                    or old.get("content")
                )

    results = [
        merged[url]
        for url in order
    ]

    results.sort(
        key=lambda item: (
            source_priority(
                item["url"]
            ),
            -len(
                item.get(
                    "matched_queries",
                    set(),
                )
            ),
            -(
                item.get("score")
                or 0
            ),
        )
    )

    return results


# =========================================================
# БАЛАНС ИСТОЧНИКОВ ДЛЯ ИИ
# =========================================================

def select_ai_sources(
    results,
    limit=MAX_AI_SOURCES,
):
    if not results:
        return []

    selected = []
    selected_urls = set()

    query_ids = sorted({
        query_id
        for item in results
        for query_id in item.get(
            "matched_queries",
            {
                item.get(
                    "query_index",
                    0,
                )
            },
        )
    })

    for _ in range(2):
        for query_id in query_ids:
            candidate = None

            for item in results:
                clean_url = (
                    item["url"]
                    .split("#", 1)[0]
                    .rstrip("/")
                )

                if clean_url in selected_urls:
                    continue

                matched = item.get(
                    "matched_queries",
                    {
                        item.get(
                            "query_index",
                            0,
                        )
                    },
                )

                if query_id not in matched:
                    continue

                candidate = item
                break

            if candidate is None:
                continue

            clean_url = (
                candidate["url"]
                .split("#", 1)[0]
                .rstrip("/")
            )

            selected.append(
                candidate
            )

            selected_urls.add(
                clean_url
            )

            if (
                len(selected)
                >= limit
            ):
                return selected

    for item in results:
        clean_url = (
            item["url"]
            .split("#", 1)[0]
            .rstrip("/")
        )

        if clean_url in selected_urls:
            continue

        selected.append(
            item
        )

        selected_urls.add(
            clean_url
        )

        if len(selected) >= limit:
            break

    return selected


def sources_for_ai(results):
    blocks = []

    selected = select_ai_sources(
        results,
        MAX_AI_SOURCES,
    )

    for index, item in enumerate(
        selected,
        start=1,
    ):
        snippet = item[
            "content"
        ][
            :MAX_SOURCE_SNIPPET_CHARS
        ]

        domain = source_domain(
            item["url"]
        )

        matched_queries = sorted(
            item.get(
                "matched_queries",
                {
                    item.get(
                        "query_index",
                        0,
                    )
                },
            )
        )

        blocks.append(
            f"[{index}]\n"
            f"Источник: {item['title']}\n"
            f"Домен: {domain}\n"
            f"Найден по поискам: {matched_queries}\n"
            f"URL: {item['url']}\n"
            f"Фрагмент: {snippet}"
        )

    return "\n\n".join(
        blocks
    )


# =========================================================
# GROQ — АНАЛИЗ
# =========================================================

def groq_analyze(
    news_text,
    results,
):
    user_prompt = (
        "НОВОСТЬ:\n"
        f"{news_text[:MAX_NEWS_CHARS]}"
        "\n\n"
        "РЕЗУЛЬТАТЫ НЕСКОЛЬКИХ ПОИСКОВ:\n"
        f"{sources_for_ai(results)}"
        "\n\n"
        "ВАЖНО ПЕРЕД ВЕРДИКТОМ:\n"
        "1. Разложи новость на отдельные проверяемые утверждения.\n"
        "2. Проверь каждое утверждение отдельно.\n"
        "3. Если общая фраза объединяет два события, подтверждения "
        "могут находиться в разных источниках.\n"
        "4. Сопоставляй даты, названия организаций, составов, "
        "турниров, суммы и другие ключевые детали.\n"
        "5. Англоязычный надежный источник имеет такой же вес, "
        "как русскоязычный.\n"
        "6. Отсутствие статьи с точной формулировкой новости "
        "не является опровержением.\n"
        "7. 🔴 ПИЗДЁЖ ставь только при прямом противоречии "
        "или доказанной ложности ключевого факта.\n\n"
        "Дай короткий фактчек строго в заданном формате."
    )

    def request_once(
        max_tokens,
    ):
        response = requests.post(
            GROQ_API,
            headers={
                "Authorization":
                    f"Bearer {GROQ_API_KEY}",
                "Content-Type":
                    "application/json",
            },
            json={
                "model": GROQ_MODEL,
                "messages": [
                    {
                        "role":
                            "system",
                        "content":
                            SYSTEM_PROMPT,
                    },
                    {
                        "role":
                            "user",
                        "content":
                            user_prompt,
                    },
                ],
                "temperature": 0.20,
                "reasoning_effort": "low",
                "include_reasoning": False,
                "max_completion_tokens":
                    max_tokens,
                "stream": False,
            },
            timeout=45,
        )

        if response.status_code == 401:
            raise RuntimeError(
                "GROQ_401"
            )

        if response.status_code == 429:
            raise RuntimeError(
                "GROQ_429"
            )

        response.raise_for_status()

        data = response.json()

        choices = data.get(
            "choices"
        ) or []

        if not choices:
            return ""

        content = (
            choices[0]
            .get(
                "message"
            )
            or {}
        ).get(
            "content"
        )

        if isinstance(
            content,
            str,
        ):
            return content.strip()

        if isinstance(
            content,
            list,
        ):
            parts = []

            for item in content:
                if (
                    isinstance(
                        item,
                        dict,
                    )
                    and item.get(
                        "text"
                    )
                ):
                    parts.append(
                        str(
                            item[
                                "text"
                            ]
                        )
                    )

            return "\n".join(
                parts
            ).strip()

        return ""

    text = request_once(
        1200
    )

    if not text:
        print(
            (
                "Groq returned empty "
                "content; retrying once..."
            ),
            flush=True,
        )

        time.sleep(
            1
        )

        text = request_once(
            1800
        )

    if not text:
        raise RuntimeError(
            "Groq дважды вернул пустой текст"
        )

    return text[
        :3900
    ]


# =========================================================
# КНОПКИ ИСТОЧНИКОВ
# =========================================================

KNOWN_SOURCE_NAMES = {
    "reuters.com":
        "Reuters",

    "apnews.com":
        "AP",

    "afp.com":
        "AFP",

    "bbc.com":
        "BBC",

    "bbc.co.uk":
        "BBC",

    "yle.fi":
        "Yle",

    "dw.com":
        "DW",

    "france24.com":
        "France 24",

    "theguardian.com":
        "The Guardian",

    "nytimes.com":
        "NY Times",

    "ft.com":
        "Financial Times",

    "sudrf.ru":
        "Суд",

    "genproc.gov.ru":
        "Прокуратура",

    "epp.genproc.gov.ru":
        "Прокуратура",

    "sledcom.ru":
        "СК",

    "мвд.рф":
        "МВД",

    "xn--b1aew.xn--p1ai":
        "МВД",

    "hltv.org":
        "HLTV",

    "liquipedia.net":
        "Liquipedia",

    "esportsworldcup.com":
        "EWC",

    "teamspirit.gg":
        "Team Spirit",
}


def source_button_name(
    item,
    index,
):
    domain = source_domain(
        item["url"]
    )

    for (
        known_domain,
        name,
    ) in KNOWN_SOURCE_NAMES.items():
        if (
            domain
            == known_domain
            or domain.endswith(
                "."
                + known_domain
            )
        ):
            return (
                f"{index} · {name}"
            )

    title = normalize(
        item.get("title")
        or ""
    )

    if title:
        if len(title) > 28:
            title = (
                title[:27]
                .rstrip()
                + "…"
            )

        return (
            f"{index} · {title}"
        )

    return (
        f"{index} · "
        f"{domain[:28]}"
    )


def source_keyboard(results):
    selected = select_ai_sources(
        results,
        MAX_TG_SOURCES,
    )

    buttons = []

    for index, item in enumerate(
        selected,
        start=1,
    ):
        buttons.append({
            "text":
                source_button_name(
                    item,
                    index,
                ),
            "url":
                item["url"],
        })

    if not buttons:
        return None

    rows = []

    for i in range(
        0,
        len(buttons),
        2,
    ):
        rows.append(
            buttons[
                i:i + 2
            ]
        )

    return {
        "inline_keyboard":
            rows
    }


# =========================================================
# ФАКТЧЕК
# =========================================================

def factcheck(news_text):
    results = tavily_search(
        news_text
    )

    print(
        (
            "Factcheck unique sources: "
            f"{len(results)}"
        ),
        flush=True,
    )

    if not results:
        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Поиск не дал нормальных источников. "
                "Это не значит, что новость пиздёж — "
                "просто сейчас её не удалось нормально "
                "подтвердить или опровергнуть.\n"
                "Уверенность: 2/10"
            ),
            [],
        )

    answer = groq_analyze(
        news_text,
        results,
    )

    return (
        answer,
        results,
    )


# =========================================================
# ОШИБКИ
# =========================================================

def friendly_error(exc):
    text = str(
        exc
    )

    if "TAVILY_401" in text:
        return (
            "Tavily не пускает по ключу. "
            "Проверь TAVILY_API_KEY в Railway."
        )

    if "TAVILY_429" in text:
        return (
            "У Tavily закончился лимит "
            "или прилетел rate limit."
        )

    if "GROQ_401" in text:
        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY в Railway."
        )

    if "GROQ_429" in text:
        return (
            "Groq упёрся в лимит. "
            "Чуть позже попробуй ещё раз."
        )

    if (
        "Groq дважды вернул пустой текст"
        in text
    ):
        return (
            "Groq сегодня решил молчать как партизан. "
            "Я уже повторил запрос дважды — "
            "попробуй ещё раз чуть позже."
        )

    return (
        "Чёт фактчек наебнулся. "
        "Ошибку я кинул в лог Railway."
    )


# =========================================================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================================================

def handle_message(message):
    cleanup_media_caches()

    remember_media_group_text(
        message
    )

    chat_id = (
        message.get("chat")
        or {}
    ).get("id")

    message_id = message.get(
        "message_id"
    )

    from_user = (
        message.get("from")
        or {}
    )

    raw = message_text(
        message
    )

    if (
        not chat_id
        or not message_id
    ):
        return

    # =====================================================
    # /id
    # =====================================================

    if re.match(
        r"^/(?:id|whoami)"
        r"(?:@[A-Za-z0-9_]+)?"
        r"(?:\s|$)",
        raw,
        flags=re.IGNORECASE,
    ):
        replied = (
            message.get(
                "reply_to_message"
            )
            or {}
        )

        target_user = (
            replied.get("from")
            or from_user
        )

        target_id = target_user.get(
            "id"
        )

        if (
            replied
            and replied.get("from")
            and target_id
        ):
            name = normalize(
                f"{target_user.get('first_name', '')} "
                f"{target_user.get('last_name', '')}"
            ) or "пользователя"

            send_message(
                chat_id,
                (
                    f"Telegram ID "
                    f"{name}: "
                    f"{target_id}"
                ),
                message_id,
            )

        else:
            send_message(
                chat_id,
                (
                    "Твой Telegram ID: "
                    f"{from_user.get('id', 'неизвестно')}"
                ),
                message_id,
            )

        return

    # =====================================================
    # ПРОСЯТ "ПРОВЕРЬ"
    # =====================================================

    request_data = parse_manual_check(
        message
    )

    if request_data is not None:
        if request_data.get(
            "invalid_reply"
        ):
            send_message(
                chat_id,
                (
                    "Это не новость 😄 "
                    "Я фактчекаю посты, ссылки "
                    "и нормальные новостные тексты, "
                    "а не вашу переписку."
                ),
                message_id,
            )

            return

        news_text = normalize(
            request_data.get(
                "news_text"
            )
            or ""
        )

        if not news_text:
            send_message(
                chat_id,
                (
                    "Мне нечего проверять. "
                    "Ответь «Проверь» на новость "
                    "или напиши "
                    "«Проверь <текст/ссылка>»."
                ),
                message_id,
            )

            return

    # =====================================================
    # КОЛЯ КИДАЕТ НОВОСТЬ
    # =====================================================

    if (
        request_data is None
        and is_nikolai(
            from_user
        )
        and looks_like_news(
            message
        )
    ):
        if media_action_already_done(
            message,
            "kolya_roast",
        ):
            return

        send_message(
            chat_id,
            kolya_roast(),
            message_id,
        )

        return

    # =====================================================
    # АВТОФАКТЧЕК
    # =====================================================

    if (
        request_data is None
        and AUTO_CHECK
        and looks_like_news(
            message
        )
    ):
        if media_action_already_done(
            message,
            "auto_check",
        ):
            return

        news_text = normalize(
            extract_news_text(
                message
            )
        )

        if not news_text:
            return

        request_data = {
            "news_text":
                news_text,
            "source_message_id":
                message_id,
        }

    if request_data is None:
        return

    # =====================================================
    # ЗАПУСК ФАКТЧЕКА
    # =====================================================

    news_text = normalize(
        request_data.get(
            "news_text"
        )
        or ""
    )

    source_message_id = (
        request_data.get(
            "source_message_id"
        )
        or message_id
    )

    if len(news_text) < 4:
        send_message(
            chat_id,
            (
                "Там почти нет текста. "
                "Кинь саму новость или ссылку."
            ),
            message_id,
        )

        return

    status = send_message(
        chat_id,
        "🔎 Ща пробью, где тут пиздёж…",
        source_message_id,
    )

    status_message_id = (
        status
        .get(
            "result",
            {},
        )
        .get(
            "message_id"
        )
    )

    try:
        answer, results = factcheck(
            news_text
        )

        keyboard = source_keyboard(
            results
        )

        if status_message_id:
            edit_message(
                chat_id,
                status_message_id,
                answer,
                keyboard,
            )

        else:
            send_message(
                chat_id,
                answer,
                source_message_id,
                keyboard,
            )

    except Exception as exc:
        print(
            (
                "Factcheck error: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

        error_text = friendly_error(
            exc
        )

        if status_message_id:
            try:
                edit_message(
                    chat_id,
                    status_message_id,
                    error_text,
                )

                return

            except Exception:
                pass

        send_message(
            chat_id,
            error_text,
            source_message_id,
        )


# =========================================================
# ПРОВЕРКА ПЕРЕМЕННЫХ
# =========================================================

def validate_config():
    missing = []

    if not TELEGRAM_BOT_TOKEN:
        missing.append(
            "TELEGRAM_BOT_TOKEN"
        )

    if not GROQ_API_KEY:
        missing.append(
            "GROQ_API_KEY"
        )

    if not TAVILY_API_KEY:
        missing.append(
            "TAVILY_API_KEY"
        )

    if missing:
        raise RuntimeError(
            (
                "Не заданы переменные Railway: "
                + ", ".join(
                    missing
                )
            )
        )


# =========================================================
# ЗАПУСК
# =========================================================

def main():
    validate_config()

    try:
        tg(
            "deleteWebhook",
            {
                "drop_pending_updates":
                    False
            },
        )

    except Exception as exc:
        print(
            (
                "deleteWebhook warning: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

    print(
        (
            "Chicken Company bot started. "
            f"Groq model={GROQ_MODEL}; "
            f"AUTO_CHECK={AUTO_CHECK}; "
            "NIKOLAI_USER_ID="
            f"{'set' if NIKOLAI_USER_ID else 'fallback-by-name'}; "
            "search=Tavily RU+EN; "
            f"max_queries={MAX_SEARCH_QUERIES}"
        ),
        flush=True,
    )

    offset = None

    while True:
        try:
            payload = {
                "timeout":
                    30,
                "allowed_updates":
                    [
                        "message"
                    ],
            }

            if offset is not None:
                payload[
                    "offset"
                ] = offset

            data = tg(
                "getUpdates",
                payload,
                timeout=40,
            )

            for update in data.get(
                "result",
                [],
            ):
                update_id = update.get(
                    "update_id"
                )

                if isinstance(
                    update_id,
                    int,
                ):
                    offset = (
                        update_id
                        + 1
                    )

                message = update.get(
                    "message"
                )

                if message:
                    handle_message(
                        message
                    )

        except requests.HTTPError as exc:
            status_code = (
                exc.response.status_code
                if exc.response is not None
                else None
            )

            if status_code == 409:
                print(
                    (
                        "Telegram 409 Conflict: "
                        "другой экземпляр бота "
                        "уже делает getUpdates. "
                        "В Railway должен быть "
                        "только 1 worker / 1 replica."
                    ),
                    flush=True,
                )

                time.sleep(
                    8
                )

                continue

            print(
                (
                    "Network error: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                flush=True,
            )

            time.sleep(
                5
            )

        except Exception as exc:
            print(
                (
                    "Bot loop error: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                flush=True,
            )

            time.sleep(
                5
            )


if __name__ == "__main__":
    main()