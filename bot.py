import os
import re
import time
import json
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests


# =========================================================
# НАСТРОЙКИ
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
NIKOLAI_USER_ID = os.getenv("NIKOLAI_USER_ID", "").strip()

AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

RELATIVE_DATE_TZ_OFFSET_HOURS = int(
    os.getenv("RELATIVE_DATE_TZ_OFFSET_HOURS", "3")
)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

MAX_NEWS_CHARS = 4000
MAX_QUERY_SEED_CHARS = 3000

MAX_SEARCH_QUERY_CHARS = 350
SEARCH_RETRY_QUERY_CHARS = 260
MAX_SEARCH_QUERIES = 4
MAX_RESULTS_PER_QUERY = 6

MAX_EXTRACT_URLS = 4
MAX_EXTRACT_CHARS_PER_SOURCE = 1250
MAX_SEARCH_SNIPPET_CHARS = 550
MAX_AI_SOURCES = 6
MAX_TG_SOURCES = 5
MAX_TOTAL_SOURCE_CHARS = 7200

MIN_TEXT_FOR_PREEXTRACT = 180

GROQ_MAX_ATTEMPTS = 3
GROQ_DEFAULT_RETRY_SECONDS = 15
GROQ_MAX_RETRY_SECONDS = 60

MEDIA_GROUP_TTL = 3600
RECENT_MEDIA_ACTIONS = {}
MEDIA_GROUP_TEXT_CACHE = {}

CHECK_WORDS = (
    "проверь",
    "проверить",
    "фактчек",
    "чекни",
    "проверка",
    "это правда",
    "это правда?",
)

STOPWORDS = {
    "который", "которая", "которые", "этого", "этой", "также",
    "после", "перед", "через", "сегодня", "вчера", "завтра",
    "ночью", "накануне", "только", "что", "прямо", "сейчас",
    "было", "будет", "стало", "своей", "своего", "своих",
    "одного", "одной", "якобы", "сообщил", "сообщила", "сообщили",
    "заявил", "заявила", "заявили", "говорит", "отметил", "отметила",
    "утверждает", "данным", "словам", "новость", "информация",

    "about", "after", "before", "their", "there", "these", "those",
    "today", "yesterday", "tomorrow", "said", "says", "according",
    "reported", "reports", "with", "from", "that", "this", "have",
    "were", "will", "just", "now", "tonight",
}


# =========================================================
# ФИНАЛЬНЫЙ ПРОМПТ
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.

Тебе передают:
1) проверяемую новость;
2) дату исходного Telegram-поста, если она известна;
3) результаты поиска и извлечённый текст некоторых страниц.

Твоя задача — вынести аккуратный вердикт по СУТИ новости.

КРИТИЧЕСКИЕ ПРАВИЛА:

1. Не выдумывай факты и не используй знания вне переданных источников.

2. Мысленно разбивай составную новость на ключевые утверждения,
но пользователю не показывай C1/C2/C3 и другую внутреннюю разметку.

3. Разные части новости могут подтверждаться разными источниками.
Не требуй одну статью, в которой написано абсолютно всё.

4. "Не нашёл подтверждения" НЕ означает "доказал ложность".

5. 🔴 ПИЗДЁЖ ставь только если надёжный источник прямо опровергает
центральный факт или даёт несовместимые с ним данные.

6. 🟡 ПОЛУПИЗДЁЖ ставь только если событие в основе реальное,
но ВАЖНАЯ часть реально неверна или существенно искажена.
Отсутствие второстепенной детали в другом источнике само по себе
не делает новость "полупиздежом".

7. 🟠 НАЕБАЛИ С КОНТЕКСТОМ — когда факты в основном настоящие,
но дата, старый материал, вырванная цитата или подача создают
ложное впечатление.

8. ⚪ ХУЙ ПОЙМЁШЬ ПОКА — когда данных реально недостаточно
или источники противоречат друг другу.

9. Источник про ПОХОЖЕЕ событие не подтверждает и не опровергает
проверяемое событие.
Сверяй место, объект, людей, дату, число пострадавших и обстоятельства.

10. Очень важно различать:

"пожар был в районе Сафари-парка, но огонь не дошёл до самого парка"

и

"пожара в районе Сафари-парка не было".

Первое НЕ опровергает утверждение о наличии пожара рядом с парком.

11. Если исходный пост говорит "сегодня", "вчера", "этой ночью":

- если дата исходного поста известна — отсчитывай от неё;

- если дата неизвестна — НЕ подставляй текущую дату сервера
и не объявляй новость ложной из-за расхождения календарной даты.

12. Для иностранной цитаты русский пост может быть переводом.
Англоязычный источник не обязан повторять русский перевод дословно.
Сравнивай автора, смысл, контекст и ключевую мысль.

13. Официальный первоисточник особенно силён,
когда организация сообщает о собственном решении/продукте,
суд — о своём решении,
организатор — о результатах и т.п.

Но заявление заинтересованной стороны о спорном внешнем событии
не всегда достаточно без независимой проверки.

14. Локальные официальные органы и региональные СМИ могут быть
лучшими источниками для локального пожара, аварии
или другого местного события.

15. Извлечённый текст страницы сильнее короткого поискового сниппета.

Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА

Формат ответа:

Первая строка — только один вердикт.

Дальше 2–4 коротких предложения простым языком.

Последняя видимая строка:

Уверенность: N/10

После неё техническая строка:

USED: 1,2

USED должен содержать номера ТОЛЬКО тех источников,
на которых реально основан вывод.

URL в текст не вставляй — бот покажет кнопки.

Не шути про семью, детей, болезни, смерть и трагедии.
""".strip()


# =========================================================
# ОБЩИЕ ФУНКЦИИ
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


def clean_url(url):
    return (
        (url or "")
        .strip()
        .split("#", 1)[0]
        .rstrip(").,!?;:'\"")
        .rstrip("/")
    )


def unique_urls(urls, limit=None):
    result = []
    seen = set()

    for url in urls:
        url = clean_url(url)

        if not url:
            continue

        key = url.lower()

        if key in seen:
            continue

        seen.add(key)
        result.append(url)

        if limit and len(result) >= limit:
            break

    return result


def source_domain(url):
    return (
        urlparse(url)
        .netloc
        .lower()
        .removeprefix("www.")
    )


def short_query(
    text,
    limit=MAX_SEARCH_QUERY_CHARS,
):
    text = normalize(text)

    if len(text) <= limit:
        return text

    cut = text[:limit]
    pos = cut.rfind(" ")

    if pos >= int(limit * 0.65):
        cut = cut[:pos]

    return cut.strip()


def parse_json_object(text):
    text = (
        (text or "")
        .strip()
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    start = text.find("{")
    end = text.rfind("}")

    if start < 0 or end <= start:
        return None

    try:
        return json.loads(
            text[start:end + 1]
        )

    except Exception:
        return None


def meaningful_tokens(text):
    words = re.findall(
        r"[A-Za-zА-Яа-яЁё0-9]"
        r"[A-Za-zА-Яа-яЁё0-9\-]{2,}",
        (text or "").lower(),
    )

    return {
        word
        for word in words
        if (
            word not in STOPWORDS
            and (
                len(word) >= 4
                or word.isdigit()
            )
        )
    }


def lexical_relevance(
    news_text,
    item,
):
    news_tokens = meaningful_tokens(
        news_text
    )

    source_tokens = meaningful_tokens(
        (
            f"{item.get('title', '')} "
            f"{item.get('content', '')}"
        )
    )

    if not news_tokens:
        return 0

    overlap = len(
        news_tokens
        & source_tokens
    )

    return min(
        100,
        int(
            100
            * overlap
            / max(
                4,
                min(
                    len(news_tokens),
                    18,
                ),
            )
        ),
    )


# =========================================================
# ДАТА ИСХОДНОГО TELEGRAM-ПОСТА
# =========================================================

def telegram_source_date(message):
    """
    Берём дату оригинального пересланного поста.

    Обычный message["date"] не используем:
    это может быть время,
    когда пользователь просто отправил
    текст/пересылку боту.
    """

    origin = (
        message.get(
            "forward_origin"
        )
        or {}
    )

    epoch = (
        origin.get(
            "date"
        )
        or message.get(
            "forward_date"
        )
    )

    if not isinstance(
        epoch,
        (int, float),
    ):
        return ""

    tz = timezone(
        timedelta(
            hours=
                RELATIVE_DATE_TZ_OFFSET_HOURS
        )
    )

    try:

        return datetime.fromtimestamp(
            epoch,
            tz=tz,
        ).strftime(
            "%Y-%m-%d"
        )

    except Exception:

        return ""


def relative_date_context(
    source_date,
):
    if source_date:

        return (
            "Дата исходного Telegram-поста: "
            f"{source_date}. "
            "Слова «сегодня/вчера/этой ночью» "
            "считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна. "
        "Нельзя превращать "
        "«сегодня/вчера/этой ночью» "
        "в текущую дату сервера. "
        "Ищи событие по людям, месту, "
        "объекту и обстоятельствам."
    )


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
            (
                "Telegram API error: "
                f"{data}"
            )
        )

    return data


def send_message(
    chat_id,
    text,
    reply_to_message_id=None,
    reply_markup=None,
):
    payload = {
        "chat_id":
            chat_id,

        "text":
            text[:4096],

        "disable_web_page_preview":
            True,
    }

    if reply_to_message_id:

        payload[
            "reply_parameters"
        ] = {
            "message_id":
                reply_to_message_id,

            "allow_sending_without_reply":
                True,
        }

    if reply_markup:

        payload[
            "reply_markup"
        ] = reply_markup

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
        "chat_id":
            chat_id,

        "message_id":
            message_id,

        "text":
            text[:4096],

        "disable_web_page_preview":
            True,
    }

    if reply_markup:

        payload[
            "reply_markup"
        ] = reply_markup

    return tg(
        "editMessageText",
        payload,
    )


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
            for key, value
            in storage.items()
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


def remember_media_group_text(
    message,
):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get(
            "chat"
        )
        or {}
    ).get(
        "id"
    )

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

    old = (
        MEDIA_GROUP_TEXT_CACHE
        .get(
            key
        )
    )

    if (
        not old
        or len(text)
        > len(
            old.get(
                "text",
                "",
            )
        )
    ):

        MEDIA_GROUP_TEXT_CACHE[
            key
        ] = {
            "ts":
                time.time(),

            "text":
                text,
        }


def cached_media_group_text(
    message,
):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get(
            "chat"
        )
        or {}
    ).get(
        "id"
    )

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
        MEDIA_GROUP_TEXT_CACHE
        .get(
            key
        )
        or {}
    ).get(
        "text",
        "",
    )


def extract_news_text(
    message,
):
    return (
        message_text(
            message
        )
        or cached_media_group_text(
            message
        )
    )


def media_action_already_done(
    message,
    action,
):
    media_group_id = message.get(
        "media_group_id"
    )

    chat_id = (
        message.get(
            "chat"
        )
        or {}
    ).get(
        "id"
    )

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

    RECENT_MEDIA_ACTIONS[
        key
    ] = {
        "ts":
            time.time()
    }

    return False


# =========================================================
# КОЛЯ
# =========================================================

def is_nikolai(
    user,
):
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
        user.get(
            "username"
        )
        or ""
    ).lower()

    full_name = normalize(
        (
            f"{user.get('first_name', '')} "
            f"{user.get('last_name', '')}"
        )
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
        (
            marker in username
            or marker in full_name
        )
        for marker
        in markers
    )


def kolya_roast():
    return random.choice([
        (
            "Коля-либераха опять вышел "
            "на смену в Министерство Набросов 😄"
        ),
        (
            "Либераха Николай снова "
            "на доставке инфошизы 📦"
        ),
        (
            "Коля, ты опять "
            "в телеграм-помойке купался? 😄"
        ),
        (
            "Коля-либераха опять что-то нарыл. "
            "Пацаны, держимся."
        ),
        (
            "Николай опять принёс свежак "
            "из информационной канализации."
        ),
        (
            "А, новость от Коли. "
            "Отдел набросов работает без выходных."
        ),
        (
            "Коля, телеграм-каналы тебе "
            "уже процент должны платить."
        ),
        (
            "Коля опять открыл оптовый склад "
            "охуительных историй."
        ),
    ])


# =========================================================
# ОПРЕДЕЛЕНИЕ НОВОСТИ
# =========================================================

def is_forwarded(
    message,
):
    return bool(
        message.get(
            "forward_origin"
        )
        or message.get(
            "forward_date"
        )
        or message.get(
            "forward_from"
        )
        or message.get(
            "forward_from_chat"
        )
    )


def is_forwarded_from_channel(
    message,
):
    origin = (
        message.get(
            "forward_origin"
        )
        or {}
    )

    if (
        origin.get(
            "type"
        )
        == "channel"
    ):

        return True

    return (
        message.get(
            "forward_from_chat"
        )
        or {}
    ).get(
        "type"
    ) == "channel"


def has_link(
    message,
):
    return bool(
        URL_RE.search(
            extract_news_text(
                message
            )
        )
    )


def news_like_text(
    message,
):
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


def looks_like_news(
    message,
):
    return bool(
        has_link(
            message
        )
        or is_forwarded_from_channel(
            message
        )
        or (
            is_forwarded(
                message
            )
            and len(
                normalize(
                    extract_news_text(
                        message
                    )
                )
            ) >= 40
        )
        or news_like_text(
            message
        )
    )


def private_message_can_be_checked(
    message,
):
    raw = normalize(
        extract_news_text(
            message
        )
    )

    if (
        not raw
        or raw.startswith("/")
    ):

        return False

    return (
        has_link(
            message
        )
        or is_forwarded(
            message
        )
        or len(raw) >= 8
    )


# =========================================================
# КОМАНДА «ПРОВЕРЬ»
# =========================================================

def parse_manual_check(
    message,
):
    raw = message_text(
        message
    )

    if not raw:

        return None

    lower = normalize(
        raw
    ).lower()

    command_match = re.match(
        (
            r"^/(?:check|factcheck)"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s+|$)"
        ),
        raw,
        flags=re.IGNORECASE,
    )

    natural_trigger = None

    if not command_match:

        for trigger in CHECK_WORDS:

            if (
                lower == trigger
                or lower.startswith(
                    trigger
                    + " "
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
                "invalid_reply":
                    True,

                "source_message_id":
                    replied.get(
                        "message_id"
                    ),

                "source_date":
                    telegram_source_date(
                        replied
                    ),
            }

        return {
            "news_text":
                extract_news_text(
                    replied
                ),

            "source_message_id":
                replied.get(
                    "message_id"
                ),

            "source_date":
                telegram_source_date(
                    replied
                ),
        }

    if command_match:

        news_text = raw[
            command_match.end():
        ].strip()

    else:

        news_text = raw[
            len(
                natural_trigger
            ):
        ].strip()

    return {
        "news_text":
            news_text,

        "source_message_id":
            message.get(
                "message_id"
            ),

        "source_date":
            "",
    }


# =========================================================
# GROQ
# =========================================================

def parse_retry_after(
    response,
):
    raw = (
        response.headers.get(
            "retry-after"
        )
        or ""
    ).strip()

    try:

        wait = float(
            raw
        )

    except (
        TypeError,
        ValueError,
    ):

        wait = (
            GROQ_DEFAULT_RETRY_SECONDS
        )

    wait = max(
        1,
        wait + 1,
    )

    return min(
        wait,
        GROQ_MAX_RETRY_SECONDS,
    )


def groq_text(
    system_text,
    user_text,
    max_tokens=600,
    temperature=0.10,
):
    for attempt in range(
        1,
        GROQ_MAX_ATTEMPTS + 1,
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
                "model":
                    GROQ_MODEL,

                "messages": [
                    {
                        "role":
                            "system",

                        "content":
                            system_text,
                    },
                    {
                        "role":
                            "user",

                        "content":
                            user_text,
                    },
                ],

                "temperature":
                    temperature,

                "reasoning_effort":
                    "low",

                "include_reasoning":
                    False,

                "max_completion_tokens":
                    max_tokens,

                "stream":
                    False,
            },

            timeout=55,
        )

        if (
            response.status_code
            == 429
        ):

            if (
                attempt
                >= GROQ_MAX_ATTEMPTS
            ):

                raise RuntimeError(
                    "GROQ_429"
                )

            wait = parse_retry_after(
                response
            )

            print(
                (
                    "Groq 429. "
                    f"Waiting {wait:.0f}s, "
                    f"retry {attempt + 1}/"
                    f"{GROQ_MAX_ATTEMPTS}"
                ),
                flush=True,
            )

            time.sleep(
                wait
            )

            continue

        if (
            response.status_code
            == 401
        ):

            raise RuntimeError(
                "GROQ_401"
            )

        if (
            response.status_code
            == 413
        ):

            raise RuntimeError(
                "GROQ_413"
            )

        if (
            response.status_code
            == 400
        ):

            raise RuntimeError(
                (
                    "GROQ_400: "
                    + response.text[:500]
                )
            )

        response.raise_for_status()

        choices = (
            response.json()
            .get(
                "choices"
            )
            or []
        )

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

    return ""


# =========================================================
# TAVILY EXTRACT
# =========================================================

def tavily_extract_urls(
    urls,
):
    urls = unique_urls(
        urls,
        MAX_EXTRACT_URLS,
    )

    if not urls:

        return {}

    response = requests.post(
        TAVILY_EXTRACT_API,

        headers={
            "Authorization":
                f"Bearer {TAVILY_API_KEY}",

            "Content-Type":
                "application/json",
        },

        json={
            "urls":
                urls,

            "extract_depth":
                "basic",

            "include_images":
                False,
        },

        timeout=45,
    )

    if (
        response.status_code
        == 401
    ):

        raise RuntimeError(
            "TAVILY_401"
        )

    if (
        response.status_code
        == 429
    ):

        raise RuntimeError(
            "TAVILY_429"
        )

    response.raise_for_status()

    data = response.json()

    extracted = {}

    for item in data.get(
        "results",
        [],
    ):

        url = clean_url(
            item.get(
                "url"
            )
            or ""
        )

        raw_content = (
            item.get(
                "raw_content"
            )
            or item.get(
                "content"
            )
            or ""
        )

        if (
            not url
            or not raw_content
        ):

            continue

        extracted[
            url.lower()
        ] = normalize(
            raw_content
        )

    failed = data.get(
        "failed_results",
        [],
    )

    if failed:

        print(
            (
                "Tavily Extract failed: "
                f"{failed}"
            ),
            flush=True,
        )

    return extracted


def safe_tavily_extract_urls(
    urls,
):
    try:

        return tavily_extract_urls(
            urls
        )

    except Exception as exc:

        print(
            (
                "Tavily Extract warning: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

        return {}


def preextract_original_if_needed(
    news_text,
):
    urls = unique_urls(
        URL_RE.findall(
            news_text
        ),
        1,
    )

    text_without_urls = normalize(
        URL_RE.sub(
            " ",
            news_text,
        )
    )

    if (
        not urls
        or len(
            text_without_urls
        )
        >= MIN_TEXT_FOR_PREEXTRACT
    ):

        return (
            {},
            news_text,
        )

    print(
        (
            "Pre-extracting original URL "
            "for search seed..."
        ),
        flush=True,
    )

    extracted = safe_tavily_extract_urls(
        urls
    )

    parts = [
        news_text
    ]

    for content in extracted.values():

        parts.append(
            content[
                :MAX_QUERY_SEED_CHARS
            ]
        )

    return (
        extracted,

        "\n\n".join(
            parts
        )[
            :MAX_QUERY_SEED_CHARS
        ],
    )


# =========================================================
# ПОИСКОВЫЕ ЗАПРОСЫ — V3
# =========================================================

def build_base_query(
    news_text,
):
    text = normalize(
        news_text
    )[
        :MAX_NEWS_CHARS
    ]

    without_urls = normalize(
        URL_RE.sub(
            " ",
            text,
        )
    )

    if without_urls:

        return short_query(
            without_urls
        )

    urls = URL_RE.findall(
        text
    )

    return short_query(
        (
            urls[0]
            if urls
            else text
        )
    )


def groq_build_search_queries(
    news_text,
    seed_text,
    source_date="",
):
    date_context = (
        relative_date_context(
            source_date
        )
    )

    prompt = f"""
Сделай поисковые запросы для проверки новости.

Нужны максимум 4 запроса.

Правила:

1. Один запрос должен максимально точно искать саму суть события.

2. Если можно определить официальный первоисточник
(компания, ведомство, суд, организатор, команда,
президент, официальный транскрипт),
один запрос направь на поиск первоисточника.

site: используй только если уверен в домене.

3. Если новость про иностранного политика,
иностранную компанию,
международное событие
или содержит переведённую иностранную цитату —

ОБЯЗАТЕЛЬНО добавь английский/оригинальный запрос.

Имя человека/организации пиши латиницей.

Не переводи русскую цитату дословно в кавычках,
если не знаешь точную оригинальную фразу.

Используй:
имя + 4–10 ключевых смысловых слов.

Например:

Alexander Stubb Ukraine charity learn from Ukraine

4. Если в новости несколько независимых утверждений,
можно сделать отдельный запрос по второй важной части.

5. Для локального события используй:
точное место + объект + событие.

Не забивай запрос общими словами.

6. КРИТИЧЕСКИ ВАЖНО ПО ДАТЕ:

{date_context}

7. Если дата исходного поста неизвестна,
не добавляй текущую дату сервера
только потому,
что в тексте написано "сегодня".

Верни ТОЛЬКО JSON:

{{
  "queries": [
    "...",
    "...",
    "..."
  ]
}}

НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

ИСХОДНЫЙ ТЕКСТ ПО ССЫЛКЕ, ЕСЛИ ЕСТЬ:

{seed_text[:MAX_QUERY_SEED_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты создаёшь короткие и точные "
            "поисковые запросы для фактчека. "
            "Не выдумывай факты и даты."
        ),

        prompt,

        max_tokens=320,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    queries = []

    seen = set()

    for item in (
        data.get(
            "queries"
        )
        or []
    ):

        if not isinstance(
            item,
            str,
        ):

            continue

        query = short_query(
            item,
            260,
        )

        if len(query) < 4:

            continue

        key = query.lower()

        if key in seen:

            continue

        seen.add(
            key
        )

        queries.append(
            query
        )

        if len(
            queries
        ) >= MAX_SEARCH_QUERIES:

            break

    return queries


def build_search_queries(
    news_text,
    seed_text,
    source_date="",
):
    queries = []

    seen = set()

    def add(
        query,
    ):
        query = short_query(
            query
        )

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

    try:

        generated = (
            groq_build_search_queries(
                news_text,
                seed_text,
                source_date=
                    source_date,
            )
        )

    except Exception as exc:

        print(
            (
                "Search-query generation warning: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

        generated = []

    for query in generated:

        add(
            query
        )

    # Базовый запрос — страховка.

    add(
        build_base_query(
            news_text
        )
    )

    return queries[
        :MAX_SEARCH_QUERIES
    ]


# =========================================================
# ПРИОРИТЕТ ИСТОЧНИКОВ
# =========================================================

def domain_matches(
    domain,
    candidates,
):
    return any(
        (
            domain == item
            or domain.endswith(
                "."
                + item
            )
        )
        for item
        in candidates
    )


def source_priority(
    url,
):
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
        "consilium.europa.eu",

        "who.int",
        "un.org",
        "nato.int",

        "nih.gov",
        "pubmed.ncbi.nlm.nih.gov",

        "whitehouse.gov",
        "state.gov",
        "defense.gov",

        "president.gov.ua",

        "presidentti.fi",
        "valtioneuvosto.fi",
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
        "cnn.com",
        "nbcnews.com",
        "abcnews.go.com",
        "cbsnews.com",
        "theguardian.com",
        "nytimes.com",
        "washingtonpost.com",
        "ft.com",
        "dw.com",
        "france24.com",
        "yle.fi",
        "err.ee",

        "tass.ru",
        "interfax.ru",
    )

    specialist_domains = (
        "hltv.org",
        "liquipedia.net",
        "esportsworldcup.com",
        "teamspirit.gg",
        "riotgames.com",
        "arxiv.org",
        "brookings.edu",
    )

    if domain_matches(
        domain,
        official_domains,
    ):

        return 0

    if any(
        marker in domain
        for marker
        in official_markers
    ):

        return 0

    if domain_matches(
        domain,
        wire_domains,
    ):

        return 1

    if domain_matches(
        domain,
        major_domains,
    ):

        return 2

    if domain_matches(
        domain,
        specialist_domains,
    ):

        return 2

    return 3


# =========================================================
# TAVILY SEARCH
# =========================================================

def _tavily_search_request(
    query,
    max_chars,
):
    safe_query = short_query(
        query,
        max_chars,
    )

    response = requests.post(
        TAVILY_SEARCH_API,

        headers={
            "Authorization":
                f"Bearer {TAVILY_API_KEY}",

            "Content-Type":
                "application/json",
        },

        json={
            "query":
                safe_query,

            "search_depth":
                "basic",

            "topic":
                "general",

            "max_results":
                MAX_RESULTS_PER_QUERY,

            "include_answer":
                False,

            "include_raw_content":
                False,

            "include_images":
                False,

            "auto_parameters":
                False,
        },

        timeout=30,
    )

    return (
        response,
        safe_query,
    )


def tavily_search_once(
    query,
    query_index,
):
    (
        response,
        safe_query,
    ) = _tavily_search_request(
        query,
        MAX_SEARCH_QUERY_CHARS,
    )

    if (
        response.status_code
        == 400
    ):

        print(
            (
                "Tavily 400; "
                "retry shorter: "
                f"{safe_query[:120]}"
            ),
            flush=True,
        )

        (
            response,
            safe_query,
        ) = _tavily_search_request(
            query,
            SEARCH_RETRY_QUERY_CHARS,
        )

    if (
        response.status_code
        == 401
    ):

        raise RuntimeError(
            "TAVILY_401"
        )

    if (
        response.status_code
        == 429
    ):

        raise RuntimeError(
            "TAVILY_429"
        )

    if (
        response.status_code
        == 400
    ):

        raise RuntimeError(
            (
                "TAVILY_400: "
                + response.text[:300]
            )
        )

    response.raise_for_status()

    results = []

    for item in response.json().get(
        "results",
        [],
    ):

        url = clean_url(
            item.get(
                "url"
            )
            or ""
        )

        if not url:

            continue

        results.append({
            "title":
                normalize(
                    item.get(
                        "title"
                    )
                    or "Источник"
                ),

            "url":
                url,

            "content":
                normalize(
                    item.get(
                        "content"
                    )
                    or ""
                ),

            "raw_content":
                "",

            "published_date":
                normalize(
                    item.get(
                        "published_date"
                    )
                    or ""
                ),

            "score":
                item.get(
                    "score"
                )
                or 0,

            "query_index":
                query_index,

            "matched_queries":
                {
                    query_index
                },
        })

    return results


def merge_search_results(
    queries,
):
    merged = {}

    successful_queries = 0

    for (
        query_index,
        query
    ) in enumerate(
        queries
    ):

        try:

            items = tavily_search_once(
                query,
                query_index,
            )

            successful_queries += 1

        except RuntimeError as exc:

            text = str(
                exc
            )

            if (
                "TAVILY_401"
                in text
                or "TAVILY_429"
                in text
            ):

                raise

            print(
                (
                    "Tavily query skipped: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                flush=True,
            )

            continue

        except requests.RequestException as exc:

            print(
                (
                    "Tavily network warning: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                flush=True,
            )

            continue

        for item in items:

            key = item[
                "url"
            ].lower()

            old = merged.get(
                key
            )

            if old is None:

                merged[
                    key
                ] = item

                continue

            old.setdefault(
                "matched_queries",
                set(),
            ).add(
                query_index
            )

            if (
                item.get(
                    "score",
                    0,
                )
                > old.get(
                    "score",
                    0,
                )
            ):

                old[
                    "score"
                ] = (
                    item.get(
                        "score"
                    )
                    or 0
                )

                old[
                    "title"
                ] = (
                    item.get(
                        "title"
                    )
                    or old.get(
                        "title"
                    )
                )

                old[
                    "content"
                ] = (
                    item.get(
                        "content"
                    )
                    or old.get(
                        "content"
                    )
                )

                old[
                    "published_date"
                ] = (
                    item.get(
                        "published_date"
                    )
                    or old.get(
                        "published_date"
                    )
                )

    print(
        (
            "Tavily successful queries: "
            f"{successful_queries}/"
            f"{len(queries)}"
        ),
        flush=True,
    )

    return list(
        merged.values()
    )


# =========================================================
# ЛЁГКАЯ ФИЛЬТРАЦИЯ
# ТОЛЬКО ЯВНЫЙ МУСОР
# =========================================================

def is_obvious_junk(
    news_text,
    item,
):
    """
    Здесь НЕ решаем,
    подтверждает ли источник новость.

    Только убираем совсем явный
    поисковый мусор.
    """

    if (
        item.get(
            "query_index"
        )
        == -1
    ):

        return False

    relevance = lexical_relevance(
        news_text,
        item,
    )

    matched_count = len(
        item.get(
            "matched_queries",
            set(),
        )
    )

    priority = source_priority(
        item[
            "url"
        ]
    )

    # Если источник нашёлся
    # по нескольким нашим запросам —
    # скорее всего он связан с темой.

    if matched_count >= 2:

        return False

    # Надёжные источники
    # не выбрасываем агрессивно.

    if (
        priority <= 2
        and relevance >= 4
    ):

        return False

    # Для обычного сайта
    # нужен хоть какой-то
    # нормальный контакт с новостью.

    if relevance >= 10:

        return False

    return True


def rank_search_results(
    news_text,
    results,
):
    clean = []

    for item in results:

        if is_obvious_junk(
            news_text,
            item,
        ):

            print(
                (
                    "Dropped obvious junk: "
                    f"{source_domain(item['url'])} | "
                    f"{item.get('title', '')[:80]}"
                ),
                flush=True,
            )

            continue

        clean.append(
            item
        )

    clean.sort(
        key=lambda item: (
            source_priority(
                item[
                    "url"
                ]
            ),

            -len(
                item.get(
                    "matched_queries",
                    set(),
                )
            ),

            -lexical_relevance(
                news_text,
                item,
            ),

            -(
                item.get(
                    "score"
                )
                or 0
            ),
        )
    )

    return clean


# =========================================================
# БАЛАНС РЕЗУЛЬТАТОВ
# =========================================================

def select_balanced_sources(
    results,
    limit,
):
    if not results:

        return []

    selected = []

    selected_urls = set()

    # Исходная ссылка пользователя
    # всегда важна.

    original = [
        item
        for item
        in results
        if (
            item.get(
                "query_index"
            )
            == -1
        )
    ]

    if original:

        first = original[
            0
        ]

        selected.append(
            first
        )

        selected_urls.add(
            first[
                "url"
            ].lower()
        )

        if len(
            selected
        ) >= limit:

            return selected

    query_ids = sorted({
        query_id

        for item
        in results

        for query_id
        in item.get(
            "matched_queries",
            set(),
        )

        if (
            isinstance(
                query_id,
                int,
            )
            and query_id >= 0
        )
    })

    # Берём хотя бы по одному
    # результату каждого направления поиска.

    for query_id in query_ids:

        for item in results:

            key = item[
                "url"
            ].lower()

            if key in selected_urls:

                continue

            if query_id not in item.get(
                "matched_queries",
                set(),
            ):

                continue

            selected.append(
                item
            )

            selected_urls.add(
                key
            )

            break

        if len(
            selected
        ) >= limit:

            return selected

    # Потом добиваем лучшими.

    for item in results:

        key = item[
            "url"
        ].lower()

        if key in selected_urls:

            continue

        selected.append(
            item
        )

        selected_urls.add(
            key
        )

        if len(
            selected
        ) >= limit:

            break

    return selected


# =========================================================
# ИСХОДНАЯ ССЫЛКА
# =========================================================

def add_original_source(
    news_text,
    results,
    preextracted,
):
    urls = unique_urls(
        URL_RE.findall(
            news_text
        ),
        1,
    )

    if not urls:

        return results

    url = urls[
        0
    ]

    key = url.lower()

    for item in results:

        if (
            item[
                "url"
            ].lower()
            == key
        ):

            if key in preextracted:

                item[
                    "raw_content"
                ] = preextracted[
                    key
                ]

            return results

    results = list(
        results
    )

    results.insert(
        0,
        {
            "title":
                "Исходная ссылка",

            "url":
                url,

            "content":
                "",

            "raw_content":
                preextracted.get(
                    key,
                    "",
                ),

            "published_date":
                "",

            "score":
                1.0,

            "query_index":
                -1,

            "matched_queries":
                set(),
        },
    )

    return results


# =========================================================
# EXTRACT
# =========================================================

def enrich_with_extract(
    news_text,
    results,
    preextracted=None,
):
    preextracted = (
        preextracted
        or {}
    )

    chosen = select_balanced_sources(
        results,
        MAX_EXTRACT_URLS,
    )

    candidate_urls = [
        item[
            "url"
        ]
        for item
        in chosen
    ]

    extracted = dict(
        preextracted
    )

    need_extract = [
        url

        for url
        in unique_urls(
            candidate_urls,
            MAX_EXTRACT_URLS,
        )

        if (
            url.lower()
            not in extracted
        )
    ]

    if need_extract:

        extracted.update(
            safe_tavily_extract_urls(
                need_extract
            )
        )

    by_url = {
        item[
            "url"
        ].lower():
            item

        for item
        in results
    }

    success = 0

    for (
        key,
        raw_content
    ) in extracted.items():

        item = by_url.get(
            clean_url(
                key
            ).lower()
        )

        if item is None:

            continue

        item[
            "raw_content"
        ] = raw_content

        success += 1

    print(
        (
            "Tavily Extract: "
            f"{success} source(s) enriched"
        ),
        flush=True,
    )

    return results


# =========================================================
# КОНТЕКСТ ДЛЯ ФИНАЛЬНОГО GROQ
# =========================================================

def sources_for_ai(
    results,
):
    selected = select_balanced_sources(
        results,
        MAX_AI_SOURCES,
    )

    blocks = []

    total_chars = 0

    for index, item in enumerate(
        selected,
        start=1,
    ):

        raw_content = normalize(
            item.get(
                "raw_content"
            )
            or ""
        )

        snippet = normalize(
            item.get(
                "content"
            )
            or ""
        )

        if raw_content:

            evidence = (
                "ИЗВЛЕЧЁННЫЙ ТЕКСТ:\n"
                + raw_content[
                    :MAX_EXTRACT_CHARS_PER_SOURCE
                ]
            )

        else:

            evidence = (
                "ПОИСКОВЫЙ СНИППЕТ:\n"
                + snippet[
                    :MAX_SEARCH_SNIPPET_CHARS
                ]
            )

        matched = ",".join(
            str(
                item_id
                + 1
            )

            for item_id
            in sorted(
                item.get(
                    "matched_queries",
                    set(),
                )
            )
        ) or "-"

        block = (
            f"[{index}]\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{source_domain(item['url'])}\n"
            f"Найден поисковыми запросами: "
            f"{matched}\n"
        )

        if item.get(
            "published_date"
        ):

            block += (
                "Дата материала: "
                f"{item['published_date']}\n"
            )

        block += evidence

        remaining = (
            MAX_TOTAL_SOURCE_CHARS
            - total_chars
        )

        if remaining <= 0:

            break

        if len(
            block
        ) > remaining:

            block = block[
                :remaining
            ]

        blocks.append(
            block
        )

        total_chars += (
            len(
                block
            )
            + 2
        )

    return (
        "\n\n".join(
            blocks
        ),

        selected,
    )


def parse_used_sources(
    answer,
    selected,
):
    match = re.search(
        (
            r"(?im)^\s*"
            r"USED\s*:\s*"
            r"([0-9,\s]+)"
            r"\s*$"
        ),
        answer or "",
    )

    used = []

    if match:

        seen = set()

        for raw in match.group(
            1
        ).split(
            ","
        ):

            raw = raw.strip()

            if not raw.isdigit():

                continue

            number = int(
                raw
            )

            if (
                1 <= number
                <= len(
                    selected
                )

                and number
                not in seen
            ):

                seen.add(
                    number
                )

                used.append(
                    selected[
                        number - 1
                    ]
                )

        answer = (
            answer[
                :match.start()
            ]
            + answer[
                match.end():
            ]
        ).strip()

    if not used:

        used = selected[
            :min(
                3,
                len(
                    selected
                ),
            )
        ]

    return (
        answer,
        used,
    )


# =========================================================
# ФИНАЛЬНЫЙ АНАЛИЗ
# ОДИН GROQ
# =========================================================

def groq_analyze(
    news_text,
    source_date,
    queries,
    results,
):
    (
        source_text,
        selected,
    ) = sources_for_ai(
        results
    )

    query_text = "\n".join(
        (
            f"{index}. "
            f"{query}"
        )

        for index, query
        in enumerate(
            queries,
            start=1,
        )
    )

    date_context = (
        relative_date_context(
            source_date
        )
    )

    prompt = f"""
КОНТЕКСТ ДАТЫ:

{date_context}

ПРОВЕРЯЕМАЯ НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

КАК ИСКАЛИ:

{query_text}

ИСТОЧНИКИ:

{source_text}

Сделай финальный фактчек.

Перед ответом мысленно:

- выдели ключевые утверждения;

- проверь каждое по подходящим источникам;

- не смешивай похожие события;

- не превращай отсутствие подтверждения
  в опровержение;

- отличай:
  "пожар рядом с объектом"
  от
  "сам объект горел";

- фраза "огонь не дошёл до Сафари-парка"
  НЕ означает,
  что пожара рядом с Сафари-парком не было;

- для иностранной цитаты
  сравни смысл оригинала
  с русским переводом;

- если источник подтверждает основное событие,
  но не повторяет мелкие детали,
  не объявляй эти детали ложными
  без прямого опровержения.

После строки:

Уверенность: N/10

обязательно напиши:

USED: 1,2
""".strip()

    answer = groq_text(
        SYSTEM_PROMPT,

        prompt,

        max_tokens=720,

        temperature=0.08,
    )

    if not answer:

        time.sleep(
            2
        )

        answer = groq_text(
            SYSTEM_PROMPT,

            prompt,

            max_tokens=800,

            temperature=0.05,
        )

    if not answer:

        raise RuntimeError(
            "Groq дважды вернул пустой текст"
        )

    (
        answer,
        used,
    ) = parse_used_sources(
        answer,
        selected,
    )

    return (
        answer[
            :3900
        ],

        used,
    )


# =========================================================
# КНОПКИ
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

    "tass.ru":
        "ТАСС",

    "interfax.ru":
        "Интерфакс",

    "yle.fi":
        "Yle",

    "err.ee":
        "ERR",

    "brookings.edu":
        "Brookings",

    "pubmed.ncbi.nlm.nih.gov":
        "PubMed",

    "nih.gov":
        "NIH",

    "hltv.org":
        "HLTV",

    "liquipedia.net":
        "Liquipedia",

    "esportsworldcup.com":
        "EWC",

    "teamspirit.gg":
        "Team Spirit",

    "riotgames.com":
        "Riot Games",

    "presidentti.fi":
        "Президент Финляндии",

    "valtioneuvosto.fi":
        "Правительство Финляндии",

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
}


def source_button_name(
    item,
    index,
):
    domain = source_domain(
        item[
            "url"
        ]
    )

    for (
        known_domain,
        name,
    ) in KNOWN_SOURCE_NAMES.items():

        if (
            domain == known_domain
            or domain.endswith(
                "."
                + known_domain
            )
        ):

            return (
                f"{index} · "
                f"{name}"
            )

    title = normalize(
        item.get(
            "title"
        )
        or ""
    )

    if title:

        if len(
            title
        ) > 28:

            title = (
                title[
                    :27
                ]
                .rstrip()
                + "…"
            )

        return (
            f"{index} · "
            f"{title}"
        )

    return (
        f"{index} · "
        f"{domain[:28]}"
    )


def source_keyboard(
    results,
):
    clean = []

    seen = set()

    for item in results:

        url = clean_url(
            item.get(
                "url"
            )
            or ""
        )

        if not url.startswith(
            (
                "http://",
                "https://",
            )
        ):

            continue

        key = url.lower()

        if key in seen:

            continue

        seen.add(
            key
        )

        clean.append(
            item
        )

        if len(
            clean
        ) >= MAX_TG_SOURCES:

            break

    if not clean:

        return None

    buttons = []

    for index, item in enumerate(
        clean,
        start=1,
    ):

        buttons.append({
            "text":
                source_button_name(
                    item,
                    index,
                ),

            "url":
                item[
                    "url"
                ],
        })

    rows = []

    for index in range(
        0,
        len(
            buttons
        ),
        2,
    ):

        rows.append(
            buttons[
                index:index + 2
            ]
        )

    return {
        "inline_keyboard":
            rows
    }


# =========================================================
# ФАКТЧЕК V3
# =========================================================

def factcheck(
    news_text,
    source_date="",
):
    (
        preextracted,
        seed_text,
    ) = preextract_original_if_needed(
        news_text
    )

    queries = build_search_queries(
        news_text,
        seed_text,
        source_date=
            source_date,
    )

    if not queries:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Не получилось построить "
                "нормальный поиск.\n"
                "Уверенность: 1/10"
            ),
            [],
        )

    print(
        (
            "Factcheck source_date: "
            + (
                source_date
                or "unknown"
            )
        ),
        flush=True,
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

    results = merge_search_results(
        queries
    )

    results = add_original_source(
        news_text,
        results,
        preextracted,
    )

    # Только лёгкая фильтрация.
    # Никакого AI-фильтра.

    results = rank_search_results(
        news_text,
        results,
    )

    print(
        (
            "Factcheck relevant search sources: "
            f"{len(results)}"
        ),
        flush=True,
    )

    if not results:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Поиск не дал нормальных источников. "
                "Это не значит, что новость ложная — "
                "сейчас её просто не удалось "
                "надёжно проверить.\n"
                "Уверенность: 2/10"
            ),
            [],
        )

    results = enrich_with_extract(
        news_text,
        results,
        preextracted=
            preextracted,
    )

    # Один финальный Groq.
    # Он сам видит всё вместе.

    return groq_analyze(
        news_text,
        source_date,
        queries,
        results,
    )


# =========================================================
# ОШИБКИ
# =========================================================

def friendly_error(
    exc,
):
    text = str(
        exc
    )

    if (
        "TAVILY_401"
        in text
    ):

        return (
            "Tavily не пускает по ключу. "
            "Проверь TAVILY_API_KEY в Railway."
        )

    if (
        "TAVILY_429"
        in text
    ):

        return (
            "У Tavily закончился лимит "
            "или прилетел rate limit."
        )

    if (
        "TAVILY_400"
        in text
    ):

        return (
            "Tavily отклонил поисковый запрос. "
            "Скинь Factcheck error из Railway."
        )

    if (
        "GROQ_401"
        in text
    ):

        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY в Railway."
        )

    if (
        "GROQ_413"
        in text
    ):

        return (
            "Для Groq запрос слишком большой. "
            "Скинь Factcheck error из Railway."
        )

    if (
        "GROQ_400"
        in text
    ):

        return (
            "Groq отклонил запрос. "
            "Скинь Factcheck error из Railway."
        )

    if (
        "GROQ_429"
        in text
    ):

        return (
            "Groq всё ещё упёрся в лимит "
            "после автоповторов. "
            "Подожди минуту и попробуй ещё раз."
        )

    if (
        "Groq дважды вернул пустой текст"
        in text
    ):

        return (
            "Groq дважды вернул пустой ответ. "
            "Попробуй ещё раз чуть позже."
        )

    return (
        "Чёт фактчек наебнулся. "
        "Ошибку я кинул в лог Railway."
    )


# =========================================================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================================================

def handle_message(
    message,
):
    cleanup_media_caches()

    remember_media_group_text(
        message
    )

    chat = (
        message.get(
            "chat"
        )
        or {}
    )

    chat_id = chat.get(
        "id"
    )

    chat_type = (
        chat.get(
            "type"
        )
        or ""
    )

    message_id = message.get(
        "message_id"
    )

    from_user = (
        message.get(
            "from"
        )
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
    # /start
    # =====================================================

    if re.match(
        (
            r"^/start"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s|$)"
        ),
        raw,
        flags=re.IGNORECASE,
    ):

        send_message(
            chat_id,

            (
                "Кидай сюда новость, ссылку "
                "или пересланный пост — "
                "в личке проверю сразу.\n"
                "В группе ответь на новость "
                "словом «Проверь»."
            ),

            message_id,
        )

        return

    # =====================================================
    # /id
    # =====================================================

    if re.match(
        (
            r"^/(?:id|whoami)"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s|$)"
        ),
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
            replied.get(
                "from"
            )
            or from_user
        )

        target_id = target_user.get(
            "id"
        )

        if (
            replied
            and replied.get(
                "from"
            )
            and target_id
        ):

            name = normalize(
                (
                    f"{target_user.get('first_name', '')} "
                    f"{target_user.get('last_name', '')}"
                )
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
    # РУЧНОЙ ФАКТЧЕК
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
                    "и новостные тексты, "
                    "а не вашу переписку."
                ),

                message_id,
            )

            return

        if not normalize(
            request_data.get(
                "news_text"
            )
            or ""
        ):

            send_message(
                chat_id,

                (
                    "Мне нечего проверять. "
                    "Ответь «Проверь» на новость "
                    "или пришли сам текст/ссылку."
                ),

                message_id,
            )

            return

    # =====================================================
    # В ЛИЧКЕ ПРОВЕРЯЕМ АВТОМАТИЧЕСКИ
    # =====================================================

    if (
        request_data is None

        and chat_type
        == "private"

        and private_message_can_be_checked(
            message
        )
    ):

        if media_action_already_done(
            message,
            "private_auto_check",
        ):

            return

        text = normalize(
            extract_news_text(
                message
            )
        )

        if text:

            request_data = {
                "news_text":
                    text,

                "source_message_id":
                    message_id,

                "source_date":
                    telegram_source_date(
                        message
                    ),
            }

    # =====================================================
    # КОЛЯ — ТОЛЬКО ГРУППА
    # =====================================================

    if (
        request_data is None

        and chat_type
        in {
            "group",
            "supergroup",
        }

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
    # AUTO_CHECK В ГРУППЕ
    # =====================================================

    if (
        request_data is None

        and chat_type
        in {
            "group",
            "supergroup",
        }

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

        text = normalize(
            extract_news_text(
                message
            )
        )

        if text:

            request_data = {
                "news_text":
                    text,

                "source_message_id":
                    message_id,

                "source_date":
                    telegram_source_date(
                        message
                    ),
            }

    if request_data is None:

        return

    # =====================================================
    # ЗАПУСК
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

    source_date = (
        request_data.get(
            "source_date"
        )
        or ""
    )

    if len(
        news_text
    ) < 4:

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

        (
            "🔎 Ща пробью "
            "и прочитаю источники…"
        ),

        source_message_id,
    )

    status_message_id = (
        status.get(
            "result"
        )
        or {}
    ).get(
        "message_id"
    )

    try:

        (
            answer,
            used_results,
        ) = factcheck(
            news_text,
            source_date=
                source_date,
        )

        keyboard = source_keyboard(
            used_results
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
# КОНФИГ
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
            "Chicken Company bot V3 started. "

            f"Groq model="
            f"{GROQ_MODEL}; "

            f"AUTO_CHECK="
            f"{AUTO_CHECK}; "

            "search="
            "Tavily RU+EN/original; "

            "filter="
            "light-junk-only; "

            f"max_queries="
            f"{MAX_SEARCH_QUERIES}; "

            f"extract_urls="
            f"{MAX_EXTRACT_URLS}; "

            "private_auto_check=True"
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
                        "Telegram 409: "
                        "другой экземпляр уже делает getUpdates. "
                        "Railway: 1 worker / 1 replica."
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