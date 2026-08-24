import os
import re
import time
import json
import random
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests


# =========================================================
# CONFIG
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
MAX_QUERY_SEED_CHARS = 3200
MAX_SEARCH_QUERY_CHARS = 340
SEARCH_RETRY_QUERY_CHARS = 250

MAX_INITIAL_QUERIES = 4
MAX_REFINED_QUERIES = 2
MAX_RESULTS_PER_QUERY = 6

MAX_EXTRACT_URLS = 4
MAX_EXTRACT_CHARS_PER_SOURCE = 1500
MAX_SEARCH_SNIPPET_CHARS = 650
MAX_AI_SOURCES = 6
MAX_TG_SOURCES = 5
MAX_TOTAL_SOURCE_CHARS = 8500

MIN_TEXT_FOR_PREEXTRACT = 180

STRONG_RESULT_SCORE = 52
RETRY_TOP_SCORE = 58
MIN_RESULTS_FOR_NO_RETRY = 2

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
    "were", "will", "just", "now", "tonight", "news",
}


SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.

Тебе передают:
1) проверяемую новость;
2) дату исходного Telegram-поста, если она известна;
3) поисковые запросы;
4) найденные источники, иногда с полным извлечённым текстом.

Твоя задача — вынести вердикт по СУТИ новости.

КРИТИЧЕСКИЕ ПРАВИЛА:

1. Работай только по переданным источникам. Ничего не выдумывай.

2. Мысленно разбивай составную новость на ключевые утверждения,
но пользователю не показывай C1/C2/C3 и внутреннюю разметку.

3. Разные части новости могут подтверждаться разными источниками.
Не требуй одну статью, где написано абсолютно всё.

4. "Не нашли подтверждение" НЕ означает "доказали ложность".

5. 🔴 ПИЗДЁЖ ставь только если центральный факт прямо и надёжно опровергнут.

6. 🟡 ПОЛУПИЗДЁЖ ставь только если основное событие реально,
но ВАЖНАЯ часть действительно неверна или существенно искажена.
Отсутствие мелкой детали в другом источнике не делает новость полупиздежом.

7. 🟠 НАЕБАЛИ С КОНТЕКСТОМ — если факты в основе реальные,
но старая дата, вырванная цитата или подача создают ложное впечатление.

8. ⚪ ХУЙ ПОЙМЁШЬ ПОКА — когда данных действительно недостаточно
или хорошие источники противоречат друг другу.

9. Не смешивай похожие события. Сверяй точное место, объект,
людей, дату, число пострадавших и обстоятельства.

10. "Огонь не дошёл до Сафари-парка" НЕ означает
"пожара рядом с Сафари-парком не было".
Различай пожар рядом с объектом и пожар самого объекта.

11. Если пост говорит "сегодня/вчера/этой ночью":
- если дата исходного поста известна — считай от неё;
- если дата неизвестна — не подставляй текущую дату сервера.

12. Для иностранной цитаты русский текст может быть переводом или пересказом.
Не требуй дословного совпадения с английским.
Сравнивай автора, смысл, контекст и ключевую мысль.

13. Официальный первоисточник особенно силён,
когда организация сообщает о собственном решении/продукте,
суд — о своём решении, организатор — о результатах.
Но заявление заинтересованной стороны о спорном внешнем событии
не всегда достаточно без независимой проверки.

14. Для локального события местный официальный орган или региональное СМИ
могут быть лучшим источником.

15. Извлечённый текст страницы сильнее короткого поискового сниппета.

Вердикты:
🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА

Формат:
Первая строка — только один вердикт.
Дальше 2–4 коротких предложения простым языком.
Последняя видимая строка:
Уверенность: N/10

После неё обязательная техническая строка:
USED: 1,2

USED — только номера реально использованных источников.
URL в текст не вставляй.
Не шути про семью, детей, болезни, смерть и трагедии.
""".strip()


# =========================================================
# BASIC HELPERS
# =========================================================

def normalize(text):
    return re.sub(r"\s+", " ", text or "").strip()


def message_text(message):
    return (message.get("text") or message.get("caption") or "").strip()


def clean_url(url):
    return (
        (url or "")
        .strip()
        .split("#", 1)[0]
        .rstrip(").,!?;:'\"")
        .rstrip("/")
    )


def unique_urls(urls, limit=None):
    out = []
    seen = set()

    for url in urls:
        url = clean_url(url)

        if not url:
            continue

        key = url.lower()

        if key in seen:
            continue

        seen.add(key)
        out.append(url)

        if limit and len(out) >= limit:
            break

    return out


def source_domain(url):
    return urlparse(url).netloc.lower().removeprefix("www.")


def short_query(text, limit=MAX_SEARCH_QUERY_CHARS):
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
        return json.loads(text[start:end + 1])

    except Exception:
        return None


def meaningful_tokens(text):
    words = re.findall(
        r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]{2,}",
        (text or "").lower(),
    )

    return {
        word
        for word in words
        if word not in STOPWORDS and (len(word) >= 4 or word.isdigit())
    }


def numeric_anchors(text):
    text = text or ""
    found = []

    patterns = (
        r"\b\d{1,2}:\d{2}\b",
        r"\b\d+[.,]\d+\s*(?:га|км|м|%|млн|млрд)?\b",
        r"\b\d{3,4}\b",
    )

    for pattern in patterns:
        for value in re.findall(pattern, text, flags=re.IGNORECASE):
            value = normalize(value)

            if value and value not in found:
                found.append(value)

    return found[:8]


def query_tokens(query):
    return meaningful_tokens(
        re.sub(
            r"\bsite:[^\s]+",
            " ",
            query or "",
            flags=re.IGNORECASE,
        )
    )


# =========================================================
# SOURCE DATE
# =========================================================

def telegram_source_date(message):
    origin = message.get("forward_origin") or {}

    epoch = (
        origin.get("date")
        or message.get("forward_date")
    )

    if not isinstance(epoch, (int, float)):
        return ""

    tz = timezone(
        timedelta(
            hours=RELATIVE_DATE_TZ_OFFSET_HOURS
        )
    )

    try:
        return datetime.fromtimestamp(
            epoch,
            tz=tz,
        ).strftime("%Y-%m-%d")

    except Exception:
        return ""


def relative_date_context(source_date):
    if source_date:

        return (
            f"Дата исходного Telegram-поста: {source_date}. "
            "Слова «сегодня/вчера/этой ночью» считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна. "
        "Не превращай «сегодня/вчера/этой ночью» "
        "в текущую дату сервера. "
        "Ищи событие по людям, месту, объекту, цифрам и обстоятельствам."
    )


# =========================================================
# TELEGRAM API
# =========================================================

def tg(method, payload=None, timeout=35):
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
# MEDIA GROUP CACHE
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
            if now - value["ts"] > MEDIA_GROUP_TTL
        ]

        for key in stale:
            storage.pop(key, None)


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
        > len(
            old.get(
                "text",
                "",
            )
        )
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
# NIKOLAI
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
        return user_id == NIKOLAI_USER_ID

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
    return random.choice([
        "Коля-либераха опять вышел на смену в Министерство Набросов 😄",
        "Либераха Николай снова на доставке инфошизы 📦",
        "Коля, ты опять в телеграм-помойке купался? 😄",
        "Коля-либераха опять что-то нарыл. Пацаны, держимся.",
        "Николай опять принёс свежак из информационной канализации.",
        "А, новость от Коли. Отдел набросов работает без выходных.",
        "Коля, телеграм-каналы тебе уже процент должны платить.",
        "Коля опять открыл оптовый склад охуительных историй.",
    ])


# =========================================================
# MESSAGE TYPE
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

    return (
        message.get("forward_from_chat")
        or {}
    ).get(
        "type"
    ) == "channel"


def has_link(message):
    return bool(
        URL_RE.search(
            extract_news_text(message)
        )
    )


def news_like_text(message):
    text = normalize(
        extract_news_text(message)
    )

    if len(text) < 90:
        return False

    return len(
        re.findall(
            r"\w+",
            text,
            flags=re.UNICODE,
        )
    ) >= 10


def looks_like_news(message):
    return bool(
        has_link(message)
        or is_forwarded_from_channel(message)
        or (
            is_forwarded(message)
            and len(
                normalize(
                    extract_news_text(message)
                )
            ) >= 40
        )
        or news_like_text(message)
    )


def private_message_can_be_checked(message):
    raw = normalize(
        extract_news_text(message)
    )

    if (
        not raw
        or raw.startswith("/")
    ):
        return False

    return (
        has_link(message)
        or is_forwarded(message)
        or len(raw) >= 8
    )


def parse_manual_check(message):
    raw = message_text(message)

    if not raw:
        return None

    lower = normalize(raw).lower()

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

def parse_retry_after(response):
    raw = (
        response.headers.get(
            "retry-after"
        )
        or ""
    ).strip()

    try:
        wait = float(raw)

    except (
        TypeError,
        ValueError,
    ):
        wait = GROQ_DEFAULT_RETRY_SECONDS

    return min(
        max(
            1,
            wait + 1,
        ),
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

        if response.status_code == 429:

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

            time.sleep(wait)

            continue

        if response.status_code == 401:

            raise RuntimeError(
                "GROQ_401"
            )

        if response.status_code == 413:

            raise RuntimeError(
                "GROQ_413"
            )

        if response.status_code == 400:

            raise RuntimeError(
                "GROQ_400: "
                + response.text[:500]
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

def tavily_extract_urls(urls):
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
            url
            and raw_content
        ):

            extracted[
                url.lower()
            ] = normalize(
                raw_content
            )

    if data.get(
        "failed_results"
    ):

        print(
            (
                "Tavily Extract failed: "
                f"{data['failed_results']}"
            ),
            flush=True,
        )

    return extracted


def safe_tavily_extract_urls(urls):
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
    news_text
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
        ) >= MIN_TEXT_FOR_PREEXTRACT
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
# V4 RETRIEVAL PLAN
# =========================================================

def fallback_precision_query(news_text):
    clean = normalize(
        URL_RE.sub(
            " ",
            news_text,
        )
    )

    nums = numeric_anchors(
        clean
    )

    tokens = []

    seen = set()

    for token in re.findall(
        r"[A-Za-zА-Яа-яЁё0-9]"
        r"[A-Za-zА-Яа-яЁё0-9\-]{3,}",
        clean,
    ):

        lower = token.lower()

        if (
            lower in STOPWORDS
            or lower in seen
        ):

            continue

        seen.add(
            lower
        )

        tokens.append(
            token
        )

        if len(
            tokens
        ) >= 10:

            break

    parts = (
        tokens[:8]
        + nums[:5]
    )

    return short_query(
        " ".join(
            parts
        ),
        260,
    )


def groq_build_retrieval_plan(
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
Построй ПЛАН ПОИСКА для фактчека новости.

Нужно не рассуждать о вердикте,
а создать максимально точные запросы.

{date_context}

Верни JSON:

{{
  "anchors": ["..."],
  "queries": [
    {{"q":"...", "kind":"precision"}},
    {{"q":"...", "kind":"official"}},
    {{"q":"...", "kind":"original_language"}}
  ]
}}

ANCHORS:

Выбери 4–8 САМЫХ отличительных признаков новости:

- точное место;
- фамилия/организация/объект;
- редкое название;
- точные числа;
- площадь;
- время вида 06:20;
- короткий уникальный фрагмент цитаты;
- название игры/турнира/компании.

НЕ выбирай общие слова вроде:

"пожар",
"новость",
"сообщил",
"Украина",

если есть более точные детали.

QUERIES:

Максимум {MAX_INITIAL_QUERIES} запроса.

1. precision:

обязательно используй несколько самых редких anchors.

Для локального события:

точное место + объект + числа/время/редкие детали.

Пример хорошего запроса:

Геленджик Сафари-парк 0,04 га 06:20 07:10

2. official:

если понятен возможный первоисточник,
ищи его:

ведомство,
компания,
суд,
организатор,
официальный транскрипт.

Не придумывай site: домен,
если не уверен.

3. original_language:

ОБЯЗАТЕЛЕН для иностранного политика,
компании или цитаты.

Пиши имя латиницей
и смысл цитаты на вероятном языке оригинала.

Для английского пересказа
используй смысловые синонимы,
а не буквальный русский перевод.

Пример:

Alexander Stubb Ukraine charity altruism learn from Ukraine support

4. Если новость составная,
четвёртый запрос может проверять
вторую важную часть.

ВАЖНО:

- не вставляй текущую дату сервера,
если дата исходного поста неизвестна;

- не делай запрос из всего длинного Telegram-поста;

- каждый запрос до 260 символов;

- запрос должен быть пригоден
для обычного веб-поиска.

НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

ИСХОДНЫЙ ТЕКСТ ПО ССЫЛКЕ, ЕСЛИ ЕСТЬ:

{seed_text[:MAX_QUERY_SEED_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты строишь точный retrieval-план "
            "для веб-фактчека. "
            "Не выдумывай даты и факты."
        ),

        prompt,

        max_tokens=460,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    anchors = []

    seen_anchors = set()

    for item in (
        data.get(
            "anchors"
        )
        or []
    ):

        if not isinstance(
            item,
            str,
        ):

            continue

        item = normalize(
            item
        )[:90]

        if len(item) < 2:

            continue

        key = item.lower()

        if key in seen_anchors:

            continue

        seen_anchors.add(
            key
        )

        anchors.append(
            item
        )

        if len(
            anchors
        ) >= 8:

            break

    for item in numeric_anchors(
        news_text
    ):

        key = item.lower()

        if key not in seen_anchors:

            seen_anchors.add(
                key
            )

            anchors.append(
                item
            )

        if len(
            anchors
        ) >= 8:

            break

    queries = []

    seen_queries = set()

    def add_query(
        q,
        kind,
    ):
        q = short_query(
            q,
            260,
        )

        if len(q) < 4:

            return

        key = q.lower()

        if key in seen_queries:

            return

        seen_queries.add(
            key
        )

        queries.append({
            "q":
                q,

            "kind":
                kind
                or "precision",
        })

    if anchors:

        add_query(
            " ".join(
                anchors[:8]
            ),
            "anchors",
        )

    for item in (
        data.get(
            "queries"
        )
        or []
    ):

        if isinstance(
            item,
            str,
        ):

            add_query(
                item,
                "precision",
            )

        elif isinstance(
            item,
            dict,
        ):

            add_query(
                (
                    item.get(
                        "q"
                    )
                    or item.get(
                        "query"
                    )
                    or ""
                ),

                normalize(
                    item.get(
                        "kind"
                    )
                    or "precision"
                ).lower(),
            )

        if len(
            queries
        ) >= MAX_INITIAL_QUERIES:

            break

    if not queries:

        add_query(
            fallback_precision_query(
                news_text
            ),
            "fallback",
        )

    return {
        "anchors":
            anchors,

        "queries":
            queries[
                :MAX_INITIAL_QUERIES
            ],
    }


# =========================================================
# SOURCE PRIORITY
# =========================================================

def domain_matches(
    domain,
    candidates,
):
    return any(
        domain == item
        or domain.endswith(
            "."
            + item
        )
        for item
        in candidates
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
    plan_item,
    query_index,
):
    query = plan_item[
        "q"
    ]

    (
        response,
        safe_query,
    ) = _tavily_search_request(
        query,
        MAX_SEARCH_QUERY_CHARS,
    )

    if response.status_code == 400:

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

    if response.status_code == 401:

        raise RuntimeError(
            "TAVILY_401"
        )

    if response.status_code == 429:

        raise RuntimeError(
            "TAVILY_429"
        )

    if response.status_code == 400:

        raise RuntimeError(
            "TAVILY_400: "
            + response.text[:300]
        )

    response.raise_for_status()

    out = []

    for item in (
        response.json()
        .get(
            "results",
            [],
        )
    ):

        url = clean_url(
            item.get(
                "url"
            )
            or ""
        )

        if not url:

            continue

        out.append({
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

            "query_kind":
                plan_item.get(
                    "kind"
                )
                or "precision",

            "matched_queries":
                {
                    query_index
                },
        })

    return out


def run_search_plan(
    plan_items,
    index_offset=0,
):
    merged = {}

    successful = 0

    for (
        local_index,
        plan_item,
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
            ).add(
                query_index
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
                    "query_kind",
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
                    "query_kind",
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


# =========================================================
# RETRIEVAL QUALITY
# =========================================================

def query_result_relevance(
    item,
    query,
):
    haystack = normalize(
        (
            f"{item.get('title', '')} "
            f"{item.get('content', '')}"
        )
    ).lower()

    tokens = query_tokens(
        query
    )

    if tokens:

        hits = sum(
            1
            for token in tokens
            if token in haystack
        )

        token_score = (
            100
            * hits
            / max(
                3,
                min(
                    len(tokens),
                    10,
                ),
            )
        )

    else:

        token_score = 0

    nums = numeric_anchors(
        query
    )

    if nums:

        normalized_haystack = haystack.replace(
            ",",
            ".",
        )

        num_hits = sum(
            1
            for number in nums
            if (
                number.lower()
                .replace(
                    ",",
                    ".",
                )
                in normalized_haystack
            )
        )

        number_score = (
            25
            * num_hits
            / len(nums)
        )

    else:

        number_score = 0

    tavily_score = float(
        item.get(
            "score"
        )
        or 0
    )

    tavily_bonus = min(
        18,
        tavily_score * 18,
    )

    priority = source_priority(
        item.get(
            "url"
        )
        or ""
    )

    if priority == 0:

        source_bonus = 8

    elif priority == 1:

        source_bonus = 6

    elif priority == 2:

        source_bonus = 4

    else:

        source_bonus = 0

    return min(
        100,

        round(
            token_score * 0.72
            + number_score
            + tavily_bonus
            + source_bonus,
            1,
        ),
    )


def attach_retrieval_scores(
    results,
    query_map,
):
    for item in results:

        matched = item.get(
            "matched_queries",
            set(),
        )

        per_query = {}

        for query_index in matched:

            query = query_map.get(
                query_index,
                "",
            )

            if not query:

                continue

            per_query[
                query_index
            ] = query_result_relevance(
                item,
                query,
            )

        item[
            "query_relevance"
        ] = per_query

        item[
            "retrieval_score"
        ] = max(
            per_query.values(),
            default=0,
        )

    return results


def retrieval_is_weak(
    results,
    search_plan,
):
    if not results:
        return True

    scores = sorted(
        (
            float(
                item.get(
                    "retrieval_score"
                )
                or 0
            )
            for item
            in results
        ),
        reverse=True,
    )

    top_score = (
        scores[0]
        if scores
        else 0
    )

    strong_count = sum(
        score >= STRONG_RESULT_SCORE
        for score in scores
    )

    top_by_query = {}

    for item in results:

        per_query = (
            item.get(
                "query_relevance"
            )
            or {}
        )

        for (
            query_index,
            score,
        ) in per_query.items():

            top_by_query[
                query_index
            ] = max(
                float(score),

                float(
                    top_by_query.get(
                        query_index,
                        0,
                    )
                ),
            )

    critical_scores = []

    for (
        query_index,
        plan_item,
    ) in enumerate(
        search_plan
    ):

        kind = (
            plan_item.get(
                "kind"
            )
            or ""
        )

        if kind in {
            "anchors",
            "precision",
            "original_language",
        }:

            critical_scores.append(
                (
                    kind,

                    float(
                        top_by_query.get(
                            query_index,
                            0,
                        )
                    ),
                )
            )

    for (
        kind,
        score,
    ) in critical_scores:

        if (
            kind
            == "original_language"

            and score < 48
        ):

            return True

    precision_scores = [
        score
        for (
            kind,
            score,
        ) in critical_scores
        if kind in {
            "anchors",
            "precision",
        }
    ]

    if (
        precision_scores
        and max(
            precision_scores
        ) < 50
    ):

        return True

    return (
        top_score < RETRY_TOP_SCORE

        or strong_count
        < MIN_RESULTS_FOR_NO_RETRY
    )


def rank_results(
    results
):
    return sorted(
        results,

        key=lambda item: (
            -float(
                item.get(
                    "retrieval_score"
                )
                or 0
            ),

            source_priority(
                item.get(
                    "url"
                )
                or ""
            ),

            -len(
                item.get(
                    "matched_queries",
                    set(),
                )
            ),

            -float(
                item.get(
                    "score"
                )
                or 0
            ),
        ),
    )


def light_filter_results(
    results
):
    if not results:

        return []

    ranked = rank_results(
        results
    )

    top_score = float(
        ranked[0].get(
            "retrieval_score"
        )
        or 0
    )

    clean = []

    for item in ranked:

        score = float(
            item.get(
                "retrieval_score"
            )
            or 0
        )

        priority = source_priority(
            item.get(
                "url"
            )
            or ""
        )

        matched_count = len(
            item.get(
                "matched_queries",
                set(),
            )
        )

        keep = (
            score >= 24

            or matched_count >= 2

            or (
                priority <= 2
                and score >= 16
            )

            or score >= max(
                18,
                top_score - 38,
            )
        )

        if keep:

            clean.append(
                item
            )

        else:

            print(
                (
                    "Dropped obvious retrieval junk: "
                    f"{source_domain(item['url'])} | "
                    f"score={score} | "
                    f"{item.get('title', '')[:80]}"
                ),
                flush=True,
            )

    return clean


# =========================================================
# QUERY REFINEMENT
# =========================================================

def refinement_pack(
    results,
    limit=8,
):
    lines = []

    for (
        index,
        item,
    ) in enumerate(
        rank_results(
            results
        )[:limit],
        1,
    ):

        lines.append(
            (
                f"{index}. "
                f"{item.get('title', 'Источник')} | "
                f"{source_domain(item.get('url', ''))} | "
                f"score={item.get('retrieval_score', 0)} | "
                f"{normalize(item.get('content', ''))[:280]}"
            )
        )

    return "\n".join(
        lines
    )


def groq_refine_queries(
    news_text,
    source_date,
    anchors,
    current_plan,
    results,
):
    date_context = (
        relative_date_context(
            source_date
        )
    )

    current_queries = "\n".join(
        (
            f"- {item['kind']}: "
            f"{item['q']}"
        )
        for item
        in current_plan
    )

    prompt = f"""
Первый поиск для фактчека
дал слабые или неточные результаты.

Сделай максимум {MAX_REFINED_QUERIES}
НОВЫХ уточняющих запроса.

{date_context}

ОСОБО ВАЖНЫЕ ЯКОРЯ:

{", ".join(anchors) if anchors else "не выделены"}

ПЕРВЫЕ ЗАПРОСЫ:

{current_queries}

СЛАБЫЕ РЕЗУЛЬТАТЫ:

{refinement_pack(results)}

ПРАВИЛА:

1. Не повторяй старые запросы.

2. Для локального события
собери в одном запросе
самые уникальные детали:

место + объект + точные числа + площадь + время.

3. Если есть:

0,04 га
06:20
07:10
Сафари-парк

не выбрасывай эти детали из запроса.

4. Для иностранной цитаты
сделай запрос на языке оригинала:

имя латиницей + смысловые слова/синонимы.

Не ищи только русский перевод.

5. Если известен вероятный официальный первоисточник,
второй запрос может искать его,
но не выдумывай домен.

6. Не добавляй текущую дату сервера,
если дата исходного поста неизвестна.

Ответ ТОЛЬКО JSON:

{{
  "queries": [
    {{
      "q":"...",
      "kind":"refined_precision"
    }},
    {{
      "q":"...",
      "kind":"refined_original_language"
    }}
  ]
}}

НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты улучшаешь веб-поиск "
            "по слабой выдаче. "
            "Не выдумывай факты."
        ),

        prompt,

        max_tokens=300,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    out = []

    seen = {
        item[
            "q"
        ].lower()
        for item
        in current_plan
    }

    for item in (
        data.get(
            "queries"
        )
        or []
    ):

        if isinstance(
            item,
            str,
        ):

            q = short_query(
                item,
                260,
            )

            kind = "refined"

        elif isinstance(
            item,
            dict,
        ):

            q = short_query(
                (
                    item.get(
                        "q"
                    )
                    or item.get(
                        "query"
                    )
                    or ""
                ),
                260,
            )

            kind = normalize(
                item.get(
                    "kind"
                )
                or "refined"
            ).lower()

        else:

            continue

        if len(q) < 4:

            continue

        key = q.lower()

        if key in seen:

            continue

        seen.add(
            key
        )

        out.append({
            "q":
                q,

            "kind":
                kind,
        })

        if len(
            out
        ) >= MAX_REFINED_QUERIES:

            break

    return out


# =========================================================
# ORIGINAL LINK
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

            "query_kind":
                "original",

            "matched_queries":
                set(),

            "query_relevance":
                {},

            "retrieval_score":
                100,
        },
    )

    return results


# =========================================================
# BALANCED SOURCES
# =========================================================

def select_balanced_sources(
    results,
    limit,
):
    if not results:

        return []

    ranked = rank_results(
        results
    )

    selected = []

    seen_urls = set()

    original = [
        item
        for item
        in ranked
        if item.get(
            "query_index"
        ) == -1
    ]

    if original:

        item = original[
            0
        ]

        selected.append(
            item
        )

        seen_urls.add(
            item[
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
        in ranked

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

    for query_id in query_ids:

        candidates = [
            item

            for item
            in ranked

            if (
                query_id
                in item.get(
                    "matched_queries",
                    set(),
                )

                and item[
                    "url"
                ].lower()
                not in seen_urls
            )
        ]

        if not candidates:

            continue

        candidates.sort(
            key=lambda item: (
                -float(
                    (
                        item.get(
                            "query_relevance"
                        )
                        or {}
                    ).get(
                        query_id,

                        item.get(
                            "retrieval_score"
                        )
                        or 0,
                    )
                ),

                source_priority(
                    item[
                        "url"
                    ]
                ),

                -float(
                    item.get(
                        "score"
                    )
                    or 0
                ),
            )
        )

        item = candidates[
            0
        ]

        selected.append(
            item
        )

        seen_urls.add(
            item[
                "url"
            ].lower()
        )

        if len(
            selected
        ) >= limit:

            return selected

    for item in ranked:

        key = item[
            "url"
        ].lower()

        if key in seen_urls:

            continue

        selected.append(
            item
        )

        seen_urls.add(
            key
        )

        if len(
            selected
        ) >= limit:

            break

    return selected


# =========================================================
# EXTRACT
# =========================================================

def enrich_with_extract(
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
        raw_content,
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
            f"{success} "
            "source(s) enriched"
        ),
        flush=True,
    )

    return results


# =========================================================
# FINAL CONTEXT
# =========================================================

def sources_for_ai(
    results
):
    selected = select_balanced_sources(
        results,
        MAX_AI_SOURCES,
    )

    blocks = []

    total_chars = 0

    for (
        index,
        item,
    ) in enumerate(
        selected,
        1,
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
                query_id
                + 1
            )

            for query_id
            in sorted(
                item.get(
                    "matched_queries",
                    set(),
                )
            )

            if (
                isinstance(
                    query_id,
                    int,
                )

                and query_id >= 0
            )
        ) or "-"

        block = (
            f"[{index}]\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{source_domain(item['url'])}\n"
            f"Retrieval score: "
            f"{item.get('retrieval_score', 0)}\n"
            f"Найден запросами: "
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
        answer
        or "",
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
# FINAL ANALYSIS
# =========================================================

def groq_analyze(
    news_text,
    source_date,
    search_plan,
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
            f"[{item.get('kind', 'query')}] "
            f"{item['q']}"
        )

        for (
            index,
            item,
        ) in enumerate(
            search_plan,
            1,
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

ПОИСКОВЫЕ ЗАПРОСЫ:

{query_text}

ЛУЧШИЕ НАЙДЕННЫЕ ИСТОЧНИКИ:

{source_text}

Сделай финальный фактчек.

Перед ответом обязательно:

- определи центральный факт новости;

- отдели его от второстепенных деталей;

- проверь, что источники относятся именно к этому событию;

- не превращай отсутствие подтверждения в опровержение;

- не считай "огонь не дошёл до объекта"
  опровержением пожара рядом с объектом;

- для переведённой иностранной цитаты
  сравни смысл, а не буквальное совпадение;

- если один хороший источник подтверждает событие,
  а другие просто молчат о деталях —
  молчание не является опровержением;

- если источники всё ещё слабые
  и не доказывают ни правду, ни ложь —
  ставь ⚪,
  а не придумывай уверенное опровержение.

После:

Уверенность: N/10

обязательно:

USED: 1,2
""".strip()

    answer = groq_text(
        SYSTEM_PROMPT,

        prompt,

        max_tokens=760,

        temperature=0.06,
    )

    if not answer:

        time.sleep(
            2
        )

        answer = groq_text(
            SYSTEM_PROMPT,

            prompt,

            max_tokens=820,

            temperature=0.03,
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
# SOURCE BUTTONS
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
    results
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

    buttons = [
        {
            "text":
                source_button_name(
                    item,
                    index,
                ),

            "url":
                item[
                    "url"
                ],
        }

        for (
            index,
            item,
        ) in enumerate(
            clean,
            1,
        )
    ]

    return {
        "inline_keyboard": [
            buttons[
                index:index + 2
            ]

            for index
            in range(
                0,
                len(
                    buttons
                ),
                2,
            )
        ]
    }


# =========================================================
# FACTCHECK V4
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

    plan = groq_build_retrieval_plan(
        news_text,
        seed_text,
        source_date=
            source_date,
    )

    search_plan = plan[
        "queries"
    ]

    if not search_plan:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Не получилось построить нормальный поиск.\n"
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
            "Factcheck anchors: "
            + " | ".join(
                plan.get(
                    "anchors"
                )
                or []
            )
        ),
        flush=True,
    )

    print(
        (
            "Factcheck initial queries: "
            + " || ".join(
                (
                    f"{item['kind']}:"
                    f"{item['q']}"
                )
                for item
                in search_plan
            )
        ),
        flush=True,
    )

    results = run_search_plan(
        search_plan,
        index_offset=0,
    )

    query_map = {
        index:
            item[
                "q"
            ]

        for (
            index,
            item,
        ) in enumerate(
            search_plan
        )
    }

    results = attach_retrieval_scores(
        results,
        query_map,
    )

    weak = retrieval_is_weak(
        results,
        search_plan,
    )

    if weak:

        top_score = max(
            (
                float(
                    item.get(
                        "retrieval_score"
                    )
                    or 0
                )

                for item
                in results
            ),
            default=0,
        )

        print(
            (
                "Retrieval weak. "
                f"top_score={top_score}. "
                "Refining queries..."
            ),
            flush=True,
        )

        try:

            refined = groq_refine_queries(
                news_text,
                source_date,
                plan.get(
                    "anchors"
                )
                or [],
                search_plan,
                results,
            )

        except Exception as exc:

            print(
                (
                    "Query refinement warning: "
                    f"{type(exc).__name__}: "
                    f"{exc}"
                ),
                flush=True,
            )

            refined = []

        if refined:

            print(
                (
                    "Factcheck refined queries: "
                    + " || ".join(
                        (
                            f"{item['kind']}:"
                            f"{item['q']}"
                        )
                        for item
                        in refined
                    )
                ),
                flush=True,
            )

            more = run_search_plan(
                refined,
                index_offset=
                    len(
                        search_plan
                    ),
            )

            search_plan = (
                search_plan
                + refined
            )

            query_map = {
                index:
                    item[
                        "q"
                    ]

                for (
                    index,
                    item,
                ) in enumerate(
                    search_plan
                )
            }

            results = merge_result_sets(
                results,
                more,
            )

            results = attach_retrieval_scores(
                results,
                query_map,
            )

    results = light_filter_results(
        results
    )

    results = add_original_source(
        news_text,
        results,
        preextracted,
    )

    print(
        (
            "Factcheck retained sources: "
            f"{len(results)}"
        ),
        flush=True,
    )

    if not results:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Поиск не нашёл источников, "
                "которые достаточно точно совпадают с новостью. "
                "Это не доказательство лжи.\n"
                "Уверенность: 2/10"
            ),

            [],
        )

    results = enrich_with_extract(
        results,
        preextracted=
            preextracted,
    )

    return groq_analyze(
        news_text,
        source_date,
        search_plan,
        results,
    )


# =========================================================
# ERRORS
# =========================================================

def friendly_error(
    exc
):
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

    if "TAVILY_400" in text:

        return (
            "Tavily отклонил поисковый запрос. "
            "Скинь Factcheck error из Railway."
        )

    if "GROQ_401" in text:

        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY в Railway."
        )

    if "GROQ_413" in text:

        return (
            "Для Groq запрос слишком большой. "
            "Скинь Factcheck error из Railway."
        )

    if "GROQ_400" in text:

        return (
            "Groq отклонил запрос. "
            "Скинь Factcheck error из Railway."
        )

    if "GROQ_429" in text:

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
# MESSAGE HANDLER
# =========================================================

def handle_message(
    message
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

    # PRIVATE CHAT AUTO CHECK

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

    # NIKOLAI GROUP JOKE

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

    # OPTIONAL GROUP AUTO CHECK

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
            "🔎 Ща найду точные совпадения "
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
# STARTUP
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
            "Chicken Company bot V4 started. "

            f"Groq model="
            f"{GROQ_MODEL}; "

            f"AUTO_CHECK="
            f"{AUTO_CHECK}; "

            "retrieval="
            "anchors+precision+original_language+refine; "

            f"initial_queries="
            f"{MAX_INITIAL_QUERIES}; "

            f"refined_queries="
            f"{MAX_REFINED_QUERIES}; "

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