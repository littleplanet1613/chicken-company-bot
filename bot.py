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

# Для русскоязычных Telegram-каналов по умолчанию Москва (+3).
# При необходимости можно изменить в Railway.
RELATIVE_DATE_TZ_OFFSET_HOURS = int(
    os.getenv("RELATIVE_DATE_TZ_OFFSET_HOURS", "3")
)

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)
QUOTE_RE = re.compile(r'[«“\"]([^»”\"]{15,220})[»”\"]')

MAX_NEWS_CHARS = 4000
MAX_QUERY_SEED_CHARS = 3000
MAX_SEARCH_QUERY_CHARS = 350
SEARCH_RETRY_QUERY_CHARS = 260

# Было 4. Увеличили, потому что теперь может добавляться
# отдельный запрос на языке оригинала.
MAX_SEARCH_QUERIES = 6

MAX_RESULTS_PER_QUERY = 5
MAX_TARGETED_SEARCHES = 3
MAX_FILTER_CANDIDATES = 14
MAX_FILTER_SNIPPET_CHARS = 420

MAX_EXTRACT_URLS = 3
MAX_EXTRACT_CHARS_PER_SOURCE = 1400
MAX_SEARCH_SNIPPET_CHARS = 600
MAX_AI_SOURCES = 5
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
    "утверждает", "данным", "словам",

    "about", "after", "before",
    "their", "there", "these", "those",
    "today", "yesterday", "tomorrow",
    "said", "says", "according", "reported", "reports",
    "with", "from", "that", "this", "have", "were", "will",
    "just", "now", "tonight",
}

ROLE_RANK = {
    "PRIMARY_STRONG": 0,
    "PRIMARY_CLAIM": 1,
    "INDEPENDENT": 2,
    "PROFILE": 3,
    "ORIGINAL": 4,
    "UNKNOWN": 5,
}


# =========================================================
# ПРОМПТ ФИНАЛЬНОГО ФАКТЧЕКА
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.
Работай ТОЛЬКО по переданным источникам.
Ничего не выдумывай.

Правила:

1. Составную новость проверяй по отдельным атомарным фактам.

2. Разные факты могут подтверждаться разными источниками.

3. Источник про похожее событие НЕ является доказательством.
Сверяй:
- дату/время;
- точное место;
- объект;
- людей;
- число погибших/пострадавших;
- обстоятельства.

4. Общая статья, памятка, справочник или страница
с совпавшими словами не подтверждает конкретное событие.

5. PRIMARY_STRONG — сильный первоисточник:
организация сообщает о собственном решении/продукте,
суд публикует решение,
ведомство публикует собственные данные,
организатор публикует результаты и т.п.

6. PRIMARY_CLAIM — заявление заинтересованной стороны
о спорном внешнем событии.
Оно важно, но не всегда достаточно само по себе.

7. Русские и английские источники оценивай на равных.

8. Для локальной новости местный официальный орган
или региональное СМИ могут быть важнее BBC/Reuters.

9. Для иностранной цитаты оригинальная
англоязычная/иноязычная публикация сильнее русского пересказа.

10. Извлечённый текст страницы сильнее поискового сниппета.

11. «Не нашёл подтверждения» НЕ означает «это ложь».

12. Если основное событие подтверждено,
а мелкая деталь просто не нашлась,
обычно ставь 🟢 с оговоркой.

13. 🟡 ставь, когда важная часть реально
опровергнута или существенно искажена,
а не просто отсутствует.

14. 🟠 ставь, если факты в основном настоящие,
но дата, контекст или подача вводят в заблуждение.

15. 🔴 ставь только когда центральный факт
надёжно опровергнут.

16. Если ключевой факт остаётся неразрешённым — ⚪.

17. Для очень свежей новости лучше ⚪,
чем подменять её похожим старым событием.

18. Цитату нельзя объявлять неподтверждённой
лишь потому, что её нет в одном материале.

19. Слова:
«сегодня»,
«вчера»,
«этой ночью»,
«накануне»
нельзя привязывать к текущей дате сервера,
если дата исходного поста не известна.

Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА

Формат:

Первая строка — только один вердикт.

Дальше 2–4 коротких предложения:
что подтвердилось,
что не подтвердилось,
есть ли подвох.

Последняя видимая строка:

Уверенность: N/10

После неё ОБЯЗАТЕЛЬНО техническая строка:

USED: 1,2

где числа — только реально использованные источники.

URL не печатай.
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

    return min(
        100,
        int(
            100
            * len(
                news_tokens
                & source_tokens
            )
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
    Берём дату именно оригинального пересланного поста.

    Обычный message["date"] специально не используем:
    это может быть просто время, когда пользователь
    отправил скопированный текст боту.
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
            "Дата исходного Telegram-поста "
            f"известна: {source_date}. "
            "Если в исходном посте написано "
            "«сегодня», «вчера», «этой ночью» "
            "и т.п., отсчитывай относительную "
            "дату ТОЛЬКО от даты публикации "
            "исходного поста, а не от текущей "
            "даты сервера."
        )

    return (
        "Дата публикации исходного материала "
        "неизвестна. "
        "НЕЛЬЗЯ превращать слова "
        "«сегодня», «вчера», «этой ночью», "
        "«накануне» в текущую дату сервера. "
        "В поисковых запросах убирай "
        "относительную дату и ищи событие "
        "по месту, людям, объекту и обстоятельствам. "
        "Абсолютную дату добавляй только если "
        "она прямо указана в новости "
        "или подтверждена источником."
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
                now
                - value["ts"]
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
# GROQ С АВТОПОВТОРОМ
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
                            item["text"]
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
# ПЛАН ФАКТЧЕКА + RU/EN/ORIGINAL LANGUAGE
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


def groq_plan_factcheck(
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
Разбери новость на максимум 4 КЛЮЧЕВЫХ проверяемых факта.
Не дроби мелочи без необходимости.

КРИТИЧЕСКОЕ ПРАВИЛО ПО ДАТЕ:

{date_context}

Для каждого факта дай короткий поисковый запрос query.

Если есть точная русская цитата русскоязычного автора,
query может содержать цитату и имя автора.

Если цитируется ИНОСТРАННЫЙ политик, компания, организация,
спортсмен, разработчик и т.п., а пост переведён на русский:

- ОБЯЗАТЕЛЬНО дай alt_query на вероятном языке оригинала;

- для международных политиков обычно используй английский;

- имя пиши латиницей;

- добавь 4–10 характерных смысловых слов из цитаты;

- НЕ заключай собственный перевод в кавычки,
  если точная оригинальная фраза неизвестна;

- alt_query должен искать оригинальное выступление,
  транскрипт, официальный пост или англоязычное СМИ.

Если дополнительный языковой запрос не нужен:

alt_query=""

Для локальной российской новости
важнее точное место и местный официальный источник.

Отдельно дай primary_query —
запрос, который прежде всего пытается найти официальный первоисточник:

сайт компании / ведомства / суда /
организатора / команды.

Если официальный домен известен уверенно,
допустим site:.

fresh=true только если свежесть события
подтверждается известной датой исходного поста
или в тексте прямо есть абсолютная дата.

Если дата исходного поста неизвестна,
а есть только:
«сегодня»,
«вчера»,
«этой ночью»,
«только что»,
не ставь fresh=true только из-за этого.

Верни ТОЛЬКО JSON:

{{
  "fresh": false,
  "primary_query": "...",
  "claims": [
    {{
      "id": "C1",
      "text": "...",
      "query": "...",
      "alt_query": "..."
    }}
  ]
}}

НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

ИСХОДНЫЙ МАТЕРИАЛ, ЕСЛИ ЕСТЬ:

{seed_text[:MAX_QUERY_SEED_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты строишь короткий план "
            "интернет-фактчека. "
            "Не выдумывай новые факты "
            "и даты."
        ),

        prompt,

        max_tokens=500,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    claims = []

    for idx, item in enumerate(
        data.get(
            "claims"
        )
        or [],
        start=1,
    ):

        if not isinstance(
            item,
            dict,
        ):
            continue

        text = normalize(
            item.get(
                "text"
            )
            or ""
        )

        query = short_query(
            item.get(
                "query"
            )
            or text,
            260,
        )

        alt_query = short_query(
            item.get(
                "alt_query"
            )
            or "",
            260,
        )

        if (
            not text
            or not query
        ):
            continue

        cid = normalize(
            item.get(
                "id"
            )
            or f"C{idx}"
        ).upper()

        if not re.fullmatch(
            r"C\d{1,2}",
            cid,
        ):

            cid = f"C{idx}"

        claims.append({
            "id":
                cid,

            "text":
                text[:500],

            "query":
                query,

            "alt_query":
                alt_query,
        })

        if len(
            claims
        ) >= 4:

            break

    if not claims:

        base = build_base_query(
            news_text
        )

        claims = [{
            "id":
                "C1",

            "text":
                (
                    normalize(
                        URL_RE.sub(
                            " ",
                            news_text,
                        )
                    )[:500]
                    or news_text[:500]
                ),

            "query":
                base,

            "alt_query":
                "",
        }]

    return {
        "fresh":
            bool(
                data.get(
                    "fresh"
                )
            ),

        "source_date":
            source_date,

        "primary_query":
            short_query(
                (
                    data.get(
                        "primary_query"
                    )
                    or claims[0][
                        "query"
                    ]
                ),
                300,
            ),

        "claims":
            claims,
    }


def build_search_plan(
    news_text,
    plan,
):
    items = []
    seen = set()

    all_ids = [
        claim[
            "id"
        ]
        for claim
        in plan[
            "claims"
        ]
    ]

    def add(
        query,
        claim_ids,
        kind,
    ):
        query = short_query(
            query
        )

        if (
            len(query) < 4
            or query.lower()
            in seen
        ):
            return

        seen.add(
            query.lower()
        )

        items.append({
            "query":
                query,

            "claim_ids":
                list(
                    claim_ids
                ),

            "kind":
                kind,
        })

    add(
        plan.get(
            "primary_query"
        ),
        all_ids,
        "primary",
    )

    for claim in plan[
        "claims"
    ]:

        add(
            claim[
                "query"
            ],
            [
                claim[
                    "id"
                ]
            ],
            "claim",
        )

        # Для иностранной цитаты/события
        # сразу запускаем поиск
        # на вероятном языке оригинала.

        if claim.get(
            "alt_query"
        ):

            add(
                claim[
                    "alt_query"
                ],
                [
                    claim[
                        "id"
                    ]
                ],
                "original_language",
            )

        if len(
            items
        ) >= MAX_SEARCH_QUERIES:

            break

    if len(
        items
    ) < 2:

        add(
            build_base_query(
                news_text
            ),
            all_ids,
            "base",
        )

    return items[
        :MAX_SEARCH_QUERIES
    ]


def targeted_query_for_claim(
    claim,
):
    # Если модель уже построила
    # запрос на языке оригинала —
    # используем его первым
    # для точечного допоиска.

    alt_query = short_query(
        claim.get(
            "alt_query"
        )
        or "",
        300,
    )

    if alt_query:
        return alt_query

    text = normalize(
        claim.get(
            "text"
        )
        or ""
    )

    quotes = QUOTE_RE.findall(
        text
    )

    if quotes:

        quote = max(
            quotes,
            key=len,
        )[
            :170
        ]

        rest = normalize(
            QUOTE_RE.sub(
                " ",
                text,
            )
        )[
            :90
        ]

        return short_query(
            (
                f'"{quote}" '
                f"{rest}"
            ),
            300,
        )

    return short_query(
        text,
        300,
    )


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

    official = (
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
        official,
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


def site_domain_from_query(
    query,
):
    match = re.search(
        (
            r"\bsite:"
            r"([A-Za-z0-9.-]+\."
            r"[A-Za-z]{2,})"
        ),
        query or "",
        re.IGNORECASE,
    )

    if not match:
        return ""

    return (
        match.group(
            1
        )
        .lower()
        .removeprefix(
            "www."
        )
    )


def looks_like_primary_candidate(
    item,
    primary_query,
):
    domain = source_domain(
        item.get(
            "url",
            "",
        )
    )

    if source_priority(
        item.get(
            "url",
            "",
        )
    ) == 0:

        return True

    site_domain = site_domain_from_query(
        primary_query
    )

    if (
        site_domain
        and (
            domain == site_domain
            or domain.endswith(
                "."
                + site_domain
            )
        )
    ):

        return True

    stem = re.sub(
        r"[^a-z0-9]",
        "",
        domain.split(
            "."
        )[0].lower(),
    )

    query_compact = re.sub(
        r"[^a-z0-9]",
        "",
        (
            primary_query
            or ""
        ).lower(),
    )

    return (
        len(stem) >= 6
        and stem
        in query_compact
    )


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
    plan_item,
    query_index,
):
    response, safe_query = (
        _tavily_search_request(
            plan_item[
                "query"
            ],
            MAX_SEARCH_QUERY_CHARS,
        )
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

        response, safe_query = (
            _tavily_search_request(
                plan_item[
                    "query"
                ],
                SEARCH_RETRY_QUERY_CHARS,
            )
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

            "query_claim_ids":
                set(
                    plan_item.get(
                        "claim_ids"
                    )
                    or []
                ),

            "query_kind":
                plan_item.get(
                    "kind"
                )
                or "claim",
        })

    return results


def run_search_items(
    plan_items,
    index_offset=0,
):
    merged = {}

    successful = 0

    for (
        local_index,
        plan_item
    ) in enumerate(
        plan_items
    ):

        query_index = (
            index_offset
            + local_index
        )

        try:

            items = tavily_search_once(
                plan_item,
                query_index,
            )

            successful += 1

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
            ).update(
                item.get(
                    "matched_queries",
                    set(),
                )
            )

            old.setdefault(
                "query_claim_ids",
                set(),
            ).update(
                item.get(
                    "query_claim_ids",
                    set(),
                )
            )

            if (
                item.get(
                    "score"
                )
                or 0
            ) > (
                old.get(
                    "score"
                )
                or 0
            ):

                for field in (
                    "title",
                    "content",
                    "published_date",
                    "score",
                ):

                    if item.get(
                        field
                    ):

                        old[
                            field
                        ] = item[
                            field
                        ]

    print(
        (
            "Tavily successful queries: "
            f"{successful}/"
            f"{len(plan_items)}"
        ),
        flush=True,
    )

    return list(
        merged.values()
    )


def merge_result_sets(
    *sets_,
):
    merged = {}

    for results in sets_:

        for item in results:

            key = item[
                "url"
            ].lower()

            old = merged.get(
                key
            )

            if old is None:

                copied = dict(
                    item
                )

                copied[
                    "matched_queries"
                ] = set(
                    item.get(
                        "matched_queries",
                        set(),
                    )
                )

                copied[
                    "query_claim_ids"
                ] = set(
                    item.get(
                        "query_claim_ids",
                        set(),
                    )
                )

                merged[
                    key
                ] = copied

                continue

            old.setdefault(
                "matched_queries",
                set(),
            ).update(
                item.get(
                    "matched_queries",
                    set(),
                )
            )

            old.setdefault(
                "query_claim_ids",
                set(),
            ).update(
                item.get(
                    "query_claim_ids",
                    set(),
                )
            )

            if (
                item.get(
                    "score"
                )
                or 0
            ) > (
                old.get(
                    "score"
                )
                or 0
            ):

                for field in (
                    "title",
                    "content",
                    "published_date",
                    "score",
                ):

                    if item.get(
                        field
                    ):

                        old[
                            field
                        ] = item[
                            field
                        ]

    return list(
        merged.values()
    )


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

    url = urls[0]

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

    results.append({
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

        "query_claim_ids":
            set(),

        "query_kind":
            "original",
    })

    return results


# =========================================================
# ФИЛЬТРАЦИЯ МУСОРА / ДРУГИХ СОБЫТИЙ
# =========================================================

def initial_candidate_sort(
    news_text,
    results,
):
    return sorted(
        results,

        key=lambda item: (
            source_priority(
                item[
                    "url"
                ]
            ),

            -len(
                item.get(
                    "query_claim_ids",
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
        ),
    )


def compact_claims(
    claims,
):
    return "\n".join(
        (
            f"{claim['id']}: "
            f"{claim['text']}"
        )
        for claim
        in claims
    )


def source_filter_pack(
    news_text,
    results,
):
    candidates = (
        initial_candidate_sort(
            news_text,
            results,
        )[
            :MAX_FILTER_CANDIDATES
        ]
    )

    lines = []

    for index, item in enumerate(
        candidates,
        start=1,
    ):

        hinted = ",".join(
            sorted(
                item.get(
                    "query_claim_ids",
                    set(),
                )
            )
        ) or "-"

        snippet = normalize(
            item.get(
                "content"
            )
            or ""
        )[
            :MAX_FILTER_SNIPPET_CHARS
        ]

        lines.append(
            (
                f"{index}. "
                f"{item.get('title', 'Источник')} | "
                f"{source_domain(item['url'])} | "
                f"query_kind="
                f"{item.get('query_kind', 'claim')} | "
                f"query_claims={hinted} | "
                f"{snippet}"
            )
        )

    return (
        candidates,
        "\n".join(
            lines
        ),
    )


def fallback_filter(
    news_text,
    results,
):
    kept = []

    for item in initial_candidate_sort(
        news_text,
        results,
    ):

        relevance = lexical_relevance(
            news_text,
            item,
        )

        priority = source_priority(
            item[
                "url"
            ]
        )

        query_kind = (
            item.get(
                "query_kind"
            )
            or "claim"
        )

        should_keep = (
            item.get(
                "query_index"
            ) == -1

            or relevance >= 12

            or (
                query_kind
                in {
                    "primary",
                    "original_language",
                }

                and priority <= 2

                and relevance >= 5
            )
        )

        if not should_keep:
            continue

        copied = dict(
            item
        )

        copied[
            "source_role"
        ] = (
            "ORIGINAL"

            if item.get(
                "query_index"
            ) == -1

            else "UNKNOWN"
        )

        copied[
            "relevance"
        ] = max(
            relevance,

            (
                50

                if (
                    priority <= 2
                    and relevance >= 5
                )

                else relevance
            ),
        )

        copied[
            "claim_ids"
        ] = set(
            item.get(
                "query_claim_ids",
                set(),
            )
        )

        kept.append(
            copied
        )

        if len(
            kept
        ) >= 8:

            break

    return kept


def groq_filter_sources(
    news_text,
    claims,
    results,
    source_date="",
):
    if not results:
        return []

    (
        candidates,
        pack,
    ) = source_filter_pack(
        news_text,
        results,
    )

    date_context = (
        relative_date_context(
            source_date
        )
    )

    prompt = f"""
Отфильтруй источники для фактчека.

КОНТЕКСТ ДАТЫ:

{date_context}

НОВОСТЬ:

{news_text[:2200]}

КЛЮЧЕВЫЕ ФАКТЫ:

{compact_claims(claims)}

ИСТОЧНИКИ:

{pack}

KEEP роли:

PRIMARY_STRONG =
авторитетный первоисточник именно для факта:
компания о собственном продукте/решении,
суд о своём решении,
ведомство о своих данных,
организатор о результатах,
официальный транскрипт цитаты.

PRIMARY_CLAIM =
заявление заинтересованной стороны
о спорном внешнем событии.

INDEPENDENT =
независимый материал именно об этом событии.

PROFILE =
надёжный профильный ресурс именно об этом событии.

ORIGINAL =
исходная ссылка пользователя,
если относится к новости.

DROP роли:

OTHER_EVENT =
похожая, но другая история.
Сверяй точное место,
объект,
людей,
жертв
и обстоятельства.

BACKGROUND =
общая статья,
памятка,
справка,
не доказательство события.

IRRELEVANT =
совпали слова,
но тема другая.

ВАЖНО ПО ДАТЕ:

Если дата исходного поста неизвестна,
НЕ выбрасывай источник только потому,
что слово «сегодня» в новости
не совпадает с текущей датой сервера.

Если дата исходного поста известна —
относительные даты считай от неё.

ВАЖНО ПО ИНОСТРАННЫМ ЦИТАТАМ:

Англоязычный источник может быть релевантен
русскому переводу цитаты,
даже если слова не совпадают дословно.

Сравни:
автора,
смысл,
контекст выступления.

Нельзя считать новость про Краснодар
подтверждённой источником про Ейский район
лишь из-за БПЛА/двух детей.

Нельзя считать страницу про Zenit релевантной
только из-за St. Petersburg.

Последнее поле —
какие факты C1,C2...
источник реально способен подтверждать
или опровергать.

Ответ ТОЛЬКО строками:

номер|KEEP или DROP|РОЛЬ|релевантность 0-100|C1,C2
""".strip()

    try:

        response = groq_text(
            (
                "Ты строгий фильтр доказательств. "
                "Итоговый вердикт не выносишь."
            ),

            prompt,

            max_tokens=500,

            temperature=0.0,
        )

    except Exception as exc:

        print(
            (
                "Source-filter warning: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

        return fallback_filter(
            news_text,
            results,
        )

    decisions = {}

    for raw in response.splitlines():

        parts = [
            part.strip()
            for part
            in raw.split("|")
        ]

        if len(parts) < 4:
            continue

        try:

            index_text = re.sub(
                r"\D",
                "",
                parts[0],
            )

            relevance_text = (
                re.sub(
                    r"\D",
                    "",
                    parts[3],
                )
                or "0"
            )

            if not index_text:
                continue

            index = int(
                index_text
            )

            relevance = int(
                relevance_text
            )

        except Exception:
            continue

        decisions[
            index
        ] = {
            "action":
                parts[1].upper(),

            "role":
                parts[2].upper(),

            "relevance":
                max(
                    0,
                    min(
                        100,
                        relevance,
                    ),
                ),

            "claim_ids":
                set(
                    re.findall(
                        r"C\d{1,2}",
                        (
                            parts[4]
                            if len(parts) >= 5
                            else ""
                        ).upper(),
                    )
                ),
        }

    if not decisions:

        print(
            (
                "Source-filter returned no "
                "parseable decisions; fallback."
            ),
            flush=True,
        )

        return fallback_filter(
            news_text,
            results,
        )

    kept = []
    dropped = []

    for index, item in enumerate(
        candidates,
        start=1,
    ):

        decision = decisions.get(
            index
        )

        if not decision:
            continue

        if (
            decision[
                "action"
            ]
            != "KEEP"
        ):

            dropped.append(
                (
                    f"{source_domain(item['url'])}:"
                    f"{decision['role']}"
                )
            )

            continue

        role = (
            decision[
                "role"
            ]

            if decision[
                "role"
            ] in ROLE_RANK

            else "UNKNOWN"
        )

        if (
            decision[
                "relevance"
            ] < 45

            and role not in {
                "PRIMARY_STRONG",
                "PRIMARY_CLAIM",
            }
        ):

            dropped.append(
                (
                    f"{source_domain(item['url'])}:"
                    f"LOW_{decision['relevance']}"
                )
            )

            continue

        copied = dict(
            item
        )

        copied[
            "source_role"
        ] = role

        copied[
            "relevance"
        ] = decision[
            "relevance"
        ]

        copied[
            "claim_ids"
        ] = (
            decision[
                "claim_ids"
            ]

            or set(
                item.get(
                    "query_claim_ids",
                    set(),
                )
            )
        )

        kept.append(
            copied
        )

    if dropped:

        print(
            (
                "Dropped sources: "
                + " | ".join(
                    dropped[:10]
                )
            ),
            flush=True,
        )

    if not kept:

        print(
            (
                "AI source filter kept zero; "
                "conservative fallback."
            ),
            flush=True,
        )

        return fallback_filter(
            news_text,
            results,
        )

    kept.sort(
        key=lambda item: (
            ROLE_RANK.get(
                item.get(
                    "source_role",
                    "UNKNOWN",
                ),
                9,
            ),

            source_priority(
                item[
                    "url"
                ]
            ),

            -(
                item.get(
                    "relevance"
                )
                or 0
            ),

            -(
                item.get(
                    "score"
                )
                or 0
            ),
        )
    )

    print(
        (
            "Relevant sources kept: "
            f"{len(kept)}/"
            f"{len(candidates)}"
        ),
        flush=True,
    )

    return kept


def covered_claim_ids(
    results,
):
    out = set()

    for item in results:

        out.update(
            item.get(
                "claim_ids",
                set(),
            )
        )

    return out


def primary_source_covers_all(
    claims,
    results,
):
    needed = {
        claim[
            "id"
        ]
        for claim
        in claims
    }

    if not needed:
        return False

    for item in results:

        if (
            item.get(
                "source_role"
            )
            == "PRIMARY_STRONG"

            and (
                item.get(
                    "relevance"
                )
                or 0
            ) >= 90

            and needed.issubset(
                item.get(
                    "claim_ids",
                    set(),
                )
            )
        ):

            return True

    strong = [
        item
        for item
        in results
        if (
            item.get(
                "source_role"
            )
            == "PRIMARY_STRONG"

            and (
                item.get(
                    "relevance"
                )
                or 0
            ) >= 90
        )
    ]

    if strong:

        domains = {
            source_domain(
                item[
                    "url"
                ]
            )
            for item
            in strong
        }

        union = set()

        for item in strong:

            union.update(
                item.get(
                    "claim_ids",
                    set(),
                )
            )

        if (
            len(domains) == 1
            and needed.issubset(
                union
            )
        ):

            return True

    return False


# =========================================================
# ВЫБОР И ЧТЕНИЕ ЛУЧШИХ ИСТОЧНИКОВ
# =========================================================

def evidence_sort_key(
    item,
):
    return (
        ROLE_RANK.get(
            item.get(
                "source_role",
                "UNKNOWN",
            ),
            9,
        ),

        source_priority(
            item[
                "url"
            ]
        ),

        -(
            item.get(
                "relevance"
            )
            or 0
        ),

        -(
            item.get(
                "score"
            )
            or 0
        ),
    )


def select_evidence_sources(
    results,
    claims,
    limit,
):
    if not results:
        return []

    ordered = sorted(
        results,
        key=evidence_sort_key,
    )

    selected = []
    seen = set()

    uncovered = {
        claim[
            "id"
        ]
        for claim
        in claims
    }

    while (
        uncovered
        and len(
            selected
        ) < limit
    ):

        best = None

        best_gain = -1

        for item in ordered:

            key = item[
                "url"
            ].lower()

            if key in seen:
                continue

            gain = len(
                uncovered
                & set(
                    item.get(
                        "claim_ids",
                        set(),
                    )
                )
            )

            if gain > best_gain:

                best = item

                best_gain = gain

        if (
            best is None
            or best_gain <= 0
        ):

            break

        selected.append(
            best
        )

        seen.add(
            best[
                "url"
            ].lower()
        )

        uncovered -= set(
            best.get(
                "claim_ids",
                set(),
            )
        )

    for item in ordered:

        if len(
            selected
        ) >= limit:

            break

        key = item[
            "url"
        ].lower()

        if key in seen:
            continue

        selected.append(
            item
        )

        seen.add(
            key
        )

    return selected


def enrich_filtered_sources(
    filtered_results,
    claims,
    preextracted=None,
):
    preextracted = (
        preextracted
        or {}
    )

    chosen = (
        select_evidence_sources(
            filtered_results,
            claims,
            MAX_EXTRACT_URLS,
        )
    )

    urls = [
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
            urls,
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

    success = 0

    enriched = []

    for item in filtered_results:

        copied = dict(
            item
        )

        raw = extracted.get(
            item[
                "url"
            ].lower(),
            "",
        )

        if raw:

            copied[
                "raw_content"
            ] = raw

            success += 1

        enriched.append(
            copied
        )

    print(
        (
            "Tavily Extract: "
            f"{success} "
            "relevant source(s) enriched"
        ),
        flush=True,
    )

    return enriched


def sources_for_ai(
    results,
    claims,
):
    selected = (
        select_evidence_sources(
            results,
            claims,
            MAX_AI_SOURCES,
        )
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
                "СНИППЕТ:\n"
                + snippet[
                    :MAX_SEARCH_SNIPPET_CHARS
                ]
            )

        claims_text = ",".join(
            sorted(
                item.get(
                    "claim_ids",
                    set(),
                )
            )
        ) or "-"

        block = (
            f"[{index}]\n"
            f"Роль: "
            f"{item.get('source_role', 'UNKNOWN')}\n"
            f"Факты: {claims_text}\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{source_domain(item['url'])}\n"
        )

        if item.get(
            "published_date"
        ):

            block += (
                "Дата источника: "
                f"{item['published_date']}\n"
            )

        block += evidence

        remaining = (
            MAX_TOTAL_SOURCE_CHARS
            - total_chars
        )

        if remaining <= 0:
            break

        if len(block) > remaining:

            block = block[
                :remaining
            ]

        blocks.append(
            block
        )

        total_chars += (
            len(block)
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
# =========================================================

def groq_analyze(
    news_text,
    plan,
    results,
):
    (
        source_text,
        selected,
    ) = sources_for_ai(
        results,
        plan[
            "claims"
        ],
    )

    date_context = (
        relative_date_context(
            plan.get(
                "source_date"
            )
            or ""
        )
    )

    prompt = f"""
КОНТЕКСТ ДАТЫ ИСХОДНОГО ПОСТА:

{date_context}

НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

КЛЮЧЕВЫЕ ФАКТЫ:

{compact_claims(plan['claims'])}

НОВОСТЬ ОЧЕНЬ СВЕЖАЯ ПО ПЛАНУ:

{'ДА' if plan.get('fresh') else 'НЕТ/НЕЯСНО'}

ОТФИЛЬТРОВАННЫЕ ИСТОЧНИКИ:

{source_text}

Проверь каждый ключевой факт отдельно.

Не используй источник как доказательство,
если он говорит о другом событии.

Если сильный первоисточник подтверждает
собственное решение/данные — учитывай это.

Если проверяется переведённая иностранная цитата —
сравнивай смысл с оригинальной формулировкой,
а не требуй дословного совпадения русского перевода.

Не штрафуй новость за мелкую деталь
только потому,
что она отсутствует в другом источнике.

Для 🟡 нужна реальная существенная
ошибка/противоречие.

Если ключевой факт не разрешён —
лучше ⚪.

Не привязывай слова
«сегодня/вчера/этой ночью»
к текущей дате сервера,
если дата исходного поста неизвестна.

Если дата исходного поста известна —
относительные даты считай от неё.

Если старая история реально выдана
за свежую — 🟠.

После уверенности обязательно напиши:

USED:

с номерами реально использованных источников.
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
        answer[:3900],
        used,
    )


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

        if len(title) > 28:

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
# ФАКТЧЕК
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

    plan = groq_plan_factcheck(
        news_text,
        seed_text,
        source_date=source_date,
    )

    claims = plan[
        "claims"
    ]

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
            "Factcheck claims: "
            + " || ".join(
                (
                    f"{claim['id']}="
                    f"{claim['text'][:120]}"
                )
                for claim
                in claims
            )
        ),
        flush=True,
    )

    search_plan = build_search_plan(
        news_text,
        plan,
    )

    print(
        (
            "Factcheck search plan: "
            + " || ".join(
                (
                    f"{item['kind']}:"
                    f"{item['query']}"
                )
                for item
                in search_plan
            )
        ),
        flush=True,
    )

    if not search_plan:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Не получилось построить "
                "нормальный поиск.\n"
                "Уверенность: 1/10"
            ),
            [],
        )

    # =====================================================
    # 1. СНАЧАЛА ИЩЕМ ПЕРВОИСТОЧНИК
    # =====================================================

    first_results = run_search_items(
        search_plan[
            :1
        ],
        0,
    )

    first_results = add_original_source(
        news_text,
        first_results,
        preextracted,
    )

    primary_query = (
        search_plan[
            0
        ][
            "query"
        ]
    )

    if any(
        looks_like_primary_candidate(
            item,
            primary_query,
        )
        for item
        in first_results
    ):

        early_filtered = (
            groq_filter_sources(
                news_text,
                claims,
                first_results,
                source_date=
                    source_date,
            )
        )

        if primary_source_covers_all(
            claims,
            early_filtered,
        ):

            print(
                (
                    "Early stop: "
                    "strong primary source "
                    "covers all key claims."
                ),
                flush=True,
            )

            enriched = (
                enrich_filtered_sources(
                    early_filtered,
                    claims,
                    preextracted,
                )
            )

            return groq_analyze(
                news_text,
                plan,
                enriched,
            )

    # =====================================================
    # 2. ОСТАЛЬНЫЕ АТОМАРНЫЕ
    # + ORIGINAL_LANGUAGE ЗАПРОСЫ
    # =====================================================

    if len(
        search_plan
    ) > 1:

        rest_results = run_search_items(
            search_plan[
                1:
            ],
            1,
        )

    else:

        rest_results = []

    all_results = merge_result_sets(
        first_results,
        rest_results,
    )

    all_results = add_original_source(
        news_text,
        all_results,
        preextracted,
    )

    print(
        (
            "Factcheck unique raw "
            "search sources: "
            f"{len(all_results)}"
        ),
        flush=True,
    )

    # =====================================================
    # 3. УБИРАЕМ МУСОР
    # И ПОХОЖИЕ, НО ДРУГИЕ СОБЫТИЯ
    # =====================================================

    filtered = groq_filter_sources(
        news_text,
        claims,
        all_results,
        source_date=
            source_date,
    )

    # =====================================================
    # 4. ДОПОИСК НЕЗАКРЫТЫХ ФАКТОВ
    # =====================================================

    missing_ids = (
        {
            claim[
                "id"
            ]
            for claim
            in claims
        }
        - covered_claim_ids(
            filtered
        )
    )

    missing = [
        claim
        for claim
        in claims
        if (
            claim[
                "id"
            ]
            in missing_ids
        )
    ]

    if missing:

        print(
            (
                "Missing claims after "
                "first pass: "
                + ", ".join(
                    claim[
                        "id"
                    ]
                    for claim
                    in missing
                )
            ),
            flush=True,
        )

    searched = {
        item[
            "query"
        ].lower()
        for item
        in search_plan
    }

    targeted = []

    for claim in missing[
        :MAX_TARGETED_SEARCHES
    ]:

        query = targeted_query_for_claim(
            claim
        )

        if not query:
            continue

        if query.lower() in searched:

            # Если original_language
            # уже запускался —
            # делаем второй уточняющий
            # оригинальный запрос.

            if claim.get(
                "alt_query"
            ):

                query = short_query(
                    (
                        f"{claim['alt_query']} "
                        "official transcript "
                        "interview speech"
                    ),
                    320,
                )

            else:

                query = short_query(
                    (
                        f"{query} "
                        "подтверждение источник"
                    ),
                    320,
                )

        if query.lower() in searched:
            continue

        targeted.append({
            "query":
                query,

            "claim_ids":
                [
                    claim[
                        "id"
                    ]
                ],

            "kind":
                "targeted",
        })

        searched.add(
            query.lower()
        )

    if targeted:

        print(
            (
                "Targeted follow-up: "
                + " || ".join(
                    item[
                        "query"
                    ]
                    for item
                    in targeted
                )
            ),
            flush=True,
        )

        more = run_search_items(
            targeted,
            len(
                search_plan
            ),
        )

        combined = merge_result_sets(
            all_results,
            more,
        )

        combined = add_original_source(
            news_text,
            combined,
            preextracted,
        )

        filtered = groq_filter_sources(
            news_text,
            claims,
            combined,
            source_date=
                source_date,
        )

    if not filtered:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Поиск не дал источников, "
                "которые уверенно относятся "
                "именно к этому событию. "
                "Это не доказательство лжи.\n"
                "Уверенность: 2/10"
            ),
            [],
        )

    # =====================================================
    # 5. ЧИТАЕМ ТОЛЬКО ЛУЧШИЕ
    # РЕЛЕВАНТНЫЕ СТРАНИЦЫ
    # =====================================================

    enriched = enrich_filtered_sources(
        filtered,
        claims,
        preextracted,
    )

    return groq_analyze(
        news_text,
        plan,
        enriched,
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

        target_id = (
            target_user.get(
                "id"
            )
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
    # В ЛИЧКЕ «ПРОВЕРЬ» НЕ НУЖНО
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
            "🔎 Ща разложу по фактам "
            "и пробью источники…"
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

            "search="
            "Tavily atomic "
            "RU+EN+original_language; "

            "source_filter="
            "AI same-event; "

            f"max_search_queries="
            f"{MAX_SEARCH_QUERIES}; "

            f"targeted="
            f"{MAX_TARGETED_SEARCHES}; "

            f"extract_urls="
            f"{MAX_EXTRACT_URLS}; "

            "private_auto_check=True; "

            f"date_tz="
            f"UTC"
            f"{RELATIVE_DATE_TZ_OFFSET_HOURS:+d}"
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