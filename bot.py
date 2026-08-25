import os
import re
import time
import json
import base64
import hashlib
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
VISION_MODEL = os.getenv("VISION_MODEL", "").strip()

AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
TZ_HOURS = int(os.getenv("RELATIVE_DATE_TZ_OFFSET_HOURS", "3"))

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"

MAX_SEARCHES = 3
MAX_RESULTS_PER_QUERY = 6
MAX_EXTRACT_URLS = 4
MAX_AI_SOURCES = 6
MAX_TG_SOURCES = 5

MAX_NEWS_CHARS = 5000
MAX_EXTRACT_CHARS = 1600
MAX_SNIPPET_CHARS = 700
MAX_TOTAL_SOURCE_CHARS = 9000

CACHE_TTL = 6 * 60 * 60
PLAN_CACHE_TTL = 6 * 60 * 60
RETRIEVAL_CACHE_TTL = 60 * 60
CACHE_MAX_ITEMS = 300
MEDIA_GROUP_TTL = 3600

FACTCHECK_CACHE = {}
PLAN_CACHE = {}
RETRIEVAL_CACHE = {}
MEDIA_GROUP_TEXT_CACHE = {}
RECENT_MEDIA_ACTIONS = {}


# =========================================================
# CONSTANTS
# =========================================================

URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.I,
)

HANDLE_RE = re.compile(
    r"(?<!\w)@[A-Za-z0-9_]{3,}"
)

DOCUMENT_RE = re.compile(
    r"\b(?:"
    r"указ\w*|"
    r"постановлен\w*|"
    r"распоряжен\w*|"
    r"закон\w*|"
    r"приказ\w*|"
    r"документ\w*|"
    r"decree|"
    r"law|"
    r"order|"
    r"resolution"
    r")\b",
    re.I,
)

CHECK_WORDS = (
    "проверь",
    "проверить",
    "фактчек",
    "чекни",
    "проверка",
    "это правда",
    "это правда?",
)

VERDICTS = (
    "🟢 НЕ ПИЗДЁЖ",
    "🟡 ПОЛУПИЗДЁЖ",
    "🟠 НАЕБАЛИ С КОНТЕКСТОМ",
    "🔴 ПИЗДЁЖ",
    "⚪ ХУЙ ПОЙМЁШЬ ПОКА",
)

VERDICT_LABELS = (
    (
        "наебали с контекстом",
        "🟠 НАЕБАЛИ С КОНТЕКСТОМ",
    ),
    (
        "хуй поймёшь пока",
        "⚪ ХУЙ ПОЙМЁШЬ ПОКА",
    ),
    (
        "хуй поймешь пока",
        "⚪ ХУЙ ПОЙМЁШЬ ПОКА",
    ),
    (
        "полупиздёж",
        "🟡 ПОЛУПИЗДЁЖ",
    ),
    (
        "полупиздеж",
        "🟡 ПОЛУПИЗДЁЖ",
    ),
    (
        "не пиздёж",
        "🟢 НЕ ПИЗДЁЖ",
    ),
    (
        "не пиздеж",
        "🟢 НЕ ПИЗДЁЖ",
    ),
    (
        "пиздёж",
        "🔴 ПИЗДЁЖ",
    ),
    (
        "пиздеж",
        "🔴 ПИЗДЁЖ",
    ),
)

KNOWN_SOURCE_DOMAINS = {
    "the new york times":
        "nytimes.com",

    "new york times":
        "nytimes.com",

    "nyt":
        "nytimes.com",

    "reuters":
        "reuters.com",

    "bbc":
        "bbc.com",

    "bloomberg":
        "bloomberg.com",

    "wall street journal":
        "wsj.com",

    "wsj":
        "wsj.com",

    "associated press":
        "apnews.com",

    "ap news":
        "apnews.com",

    "financial times":
        "ft.com",

    "the guardian":
        "theguardian.com",

    "guardian":
        "theguardian.com",

    "тасс":
        "tass.ru",

    "tass":
        "tass.ru",

    "интерфакс":
        "interfax.ru",
}

TRUSTED_DOMAINS = (
    "reuters.com",
    "apnews.com",
    "afp.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "tass.ru",
    "interfax.ru",
    "yle.fi",
    "err.ee",
)

OFFICIAL_DOMAINS = (
    "kremlin.ru",
    "government.ru",
    "pravo.gov.ru",
    "publication.pravo.gov.ru",
    "sledcom.ru",
    "genproc.gov.ru",
    "epp.genproc.gov.ru",
    "europa.eu",
    "consilium.europa.eu",
    "un.org",
    "who.int",
    "nato.int",
    "president.gov.ua",
    "presidentti.fi",
    "valtioneuvosto.fi",
    "whitehouse.gov",
    "state.gov",
    "defense.gov",
)

SOURCE_NAMES = {
    "reuters.com":
        "Reuters",

    "apnews.com":
        "AP",

    "bbc.com":
        "BBC",

    "bbc.co.uk":
        "BBC",

    "nytimes.com":
        "The New York Times",

    "bloomberg.com":
        "Bloomberg",

    "wsj.com":
        "WSJ",

    "ft.com":
        "Financial Times",

    "tass.ru":
        "ТАСС",

    "interfax.ru":
        "Интерфакс",

    "yle.fi":
        "Yle",

    "err.ee":
        "ERR",
}


# =========================================================
# PROMPTS
# =========================================================

PLANNER_SYSTEM = """
Ты поисковый планировщик фактчекера.

Пойми смысл новости
и сделай компактный план веб-поиска.

Не выноси вердикт
и не придумывай факты.

Возвращай только JSON.
""".strip()


FINAL_SYSTEM = """
Ты фактчекер Telegram-новостей.

Отвечай пользователю
ТОЛЬКО на русском языке.

Используй только
переданные источники.

Ничего не выдумывай.

Базовые правила:

- проверяй смысл,
а не буквальное совпадение слов;

- составную новость
мысленно дели
на отдельные утверждения;

- разные утверждения
могут подтверждаться
разными источниками;

- отсутствие подтверждения
НЕ является доказательством лжи;

- старые данные
не опровергают
более свежий апдейт;

- не смешивай
разные события,
документы,
модели,
версии,
комплектации,
рынки
и даты;

- названный первоисточник
важнее пересказа,
если он действительно найден;

- локальный официальный
или региональный источник
может быть лучшим
для локальной новости;

- иностранные цитаты
сравнивай по смыслу,
а не по буквальному переводу;

- 🔴 ПИЗДЁЖ
разрешён только
при прямом надёжном
опровержении
центрального факта;

- если уверенность
ниже 7/10,
🔴 запрещён;

- если доказательств
недостаточно
или нельзя уверенно
сопоставить объекты —

⚪ ХУЙ ПОЙМЁШЬ ПОКА.


Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА


Формат:

первая строка —
один вердикт;

далее 2–4
коротких предложения
на русском;

последняя видимая строка:

Уверенность: N/10

после неё техническая строка:

USED: 1,2

URL в текст ответа
не вставляй.
""".strip()


# =========================================================
# BASIC HELPERS
# =========================================================

def norm(text):

    return re.sub(
        r"\s+",
        " ",
        text or "",
    ).strip()


def norm_lines(text):

    text = (
        text
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )

    return "\n".join(
        line
        for line in (
            re.sub(
                r"[ \t]+",
                " ",
                x,
            ).strip()
            for x
            in text.split("\n")
        )
        if line
    )


def msg_text(message):

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


def domain(url):

    return (
        urlparse(url)
        .netloc
        .lower()
        .removeprefix("www.")
    )


def short_query(
    text,
    limit=300,
):

    text = norm(text)

    if len(text) <= limit:
        return text

    cut = text[:limit]

    pos = cut.rfind(" ")

    if pos > limit * 0.6:
        return cut[:pos].strip()

    return cut.strip()


def parse_json(text):

    text = (
        text
        or ""
    ).replace(
        "```json",
        "",
    ).replace(
        "```",
        "",
    ).strip()

    a = text.find("{")
    b = text.rfind("}")

    if a < 0 or b <= a:
        return {}

    try:

        return json.loads(
            text[a:b + 1]
        )

    except Exception:

        return {}


def unique_strings(
    values,
    limit=None,
):

    out = []
    seen = set()

    for value in (
        values
        or []
    ):

        value = norm(
            str(
                value
                or ""
            )
        )

        if not value:
            continue

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        out.append(value)

        if (
            limit
            and len(out) >= limit
        ):
            break

    return out


def clean_search_text(text):

    original = norm_lines(
        text
    )

    work = URL_RE.sub(
        " ",
        original,
    )

    work = HANDLE_RE.sub(
        " ",
        work,
    )

    lines = []

    for raw in work.splitlines():

        line = norm(raw)

        if not line:
            continue

        line = re.sub(
            (
                r"(?i)\bFTT\b"
                r"\s*[-—|:]?"
                r"\s*подпис\w*.*$"
            ),
            " ",
            line,
        )

        line = re.sub(
            (
                r"(?i)\b"
                r"подпис"
                r"(?:аться|ывайтесь)"
                r"\b.*$"
            ),
            " ",
            line,
        )

        arrow = line.find(
            "👉"
        )

        if arrow >= 0:

            tail = line[
                arrow:
            ].lower()

            if any(
                x in tail
                for x in (
                    "подпис",
                    "@",
                    "канал",
                    "ftt",
                )
            ):

                line = line[
                    :arrow
                ]

        line = re.sub(
            r"(?i)\bFTT\b",
            " ",
            line,
        )

        line = norm(line)

        if line:
            lines.append(line)

    return (
        norm(
            " ".join(lines)
        )
        or norm(original)
    )


def lexical_tokens(
    text,
    limit=30,
):

    stop = {
        "который",
        "которая",
        "которые",
        "этого",
        "этой",
        "также",
        "после",
        "перед",
        "через",
        "сегодня",
        "вчера",
        "завтра",
        "только",
        "сейчас",
        "было",
        "будет",
        "стало",
        "сообщил",
        "сообщила",
        "сообщили",
        "заявил",
        "заявила",
        "заявили",
        "данным",
        "словам",
        "новость",
        "информация",
        "источник",
        "подписаться",

        "about",
        "after",
        "before",
        "their",
        "there",
        "these",
        "those",
        "today",
        "yesterday",
        "tomorrow",
        "said",
        "says",
        "according",
        "reported",
        "reports",
        "with",
        "from",
        "that",
        "this",
        "have",
        "were",
        "will",
        "news",
    }

    out = []
    seen = set()

    for token in re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{2,}"
        ),
        text
        or "",
    ):

        low = token.lower()

        if (
            low in stop
            or low in seen
        ):
            continue

        seen.add(low)
        out.append(token)

        if len(out) >= limit:
            break

    return out


def is_document_text(text):

    return bool(
        DOCUMENT_RE.search(
            text
            or ""
        )
    )


def detect_preferred_domain(text):

    low = (
        text
        or ""
    ).lower()

    for (
        marker,
        source_domain,
    ) in KNOWN_SOURCE_DOMAINS.items():

        if marker in low:
            return source_domain

    for raw in URL_RE.findall(
        text
        or ""
    ):

        d = domain(
            clean_url(raw)
        )

        if (
            d
            and d not in {
                "t.me",
                "telegram.me",
                "telegram.org",
            }
        ):

            return d

    return ""


def source_priority(
    url,
    preferred_domain="",
):

    d = domain(url)

    if (
        preferred_domain
        and (
            d == preferred_domain
            or d.endswith(
                "." + preferred_domain
            )
        )
    ):

        return 0

    if any(
        (
            d == x
            or d.endswith(
                "." + x
            )
        )
        for x
        in OFFICIAL_DOMAINS
    ):

        return 1

    if (
        ".gov" in d
        or d.startswith(
            (
                "government.",
                "president.",
                "court.",
            )
        )
    ):

        return 1

    if any(
        (
            d == x
            or d.endswith(
                "." + x
            )
        )
        for x
        in TRUSTED_DOMAINS
    ):

        return 2

    return 3


# =========================================================
# CACHE
# =========================================================

def make_key(
    text,
    extra="",
):

    raw = (
        norm(text).lower()
        + "\n"
        + (
            extra
            or ""
        )
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


def cleanup_ttl_cache(
    cache,
    ttl,
    max_items=CACHE_MAX_ITEMS,
):

    now = time.time()

    for key in list(
        cache
    ):

        if (
            now
            - cache[key].get(
                "ts",
                0,
            )
            > ttl
        ):

            cache.pop(
                key,
                None,
            )

    if len(cache) > max_items:

        ordered = sorted(
            cache.items(),
            key=lambda x:
                x[1].get(
                    "ts",
                    0,
                ),
        )

        remove_count = (
            len(cache)
            - max_items
        )

        for (
            key,
            _,
        ) in ordered[
            :remove_count
        ]:

            cache.pop(
                key,
                None,
            )


def cache_get(
    cache,
    key,
    ttl,
):

    cleanup_ttl_cache(
        cache,
        ttl,
    )

    item = cache.get(
        key
    )

    if not item:

        return None

    if (
        time.time()
        - item.get(
            "ts",
            0,
        )
        > ttl
    ):

        return None

    return item.get(
        "value"
    )


def cache_put(
    cache,
    key,
    value,
):

    cache[key] = {
        "ts":
            time.time(),

        "value":
            value,
    }


# =========================================================
# DATE
# =========================================================

def source_date(message):

    origin = (
        message.get(
            "forward_origin"
        )
        or {}
    )

    ts = (
        origin.get(
            "date"
        )
        or message.get(
            "forward_date"
        )
    )

    if not isinstance(
        ts,
        (
            int,
            float,
        ),
    ):

        return ""

    try:

        tz = timezone(
            timedelta(
                hours=
                    TZ_HOURS
            )
        )

        return datetime.fromtimestamp(
            ts,
            tz=tz,
        ).strftime(
            "%Y-%m-%d"
        )

    except Exception:

        return ""


def date_context(value):

    if value:

        return (
            "Дата исходного Telegram-поста: "
            f"{value}. "
            "Относительные слова вроде "
            "«сегодня/вчера» "
            "считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна; "
        "не придумывай её."
    )


# =========================================================
# TELEGRAM
# =========================================================

def tg(
    method,
    payload=None,
    timeout=35,
):

    response = requests.post(
        f"{TG_API}/{method}",
        json=payload
        or {},
        timeout=timeout,
    )

    response.raise_for_status()

    data = response.json()

    if not data.get(
        "ok"
    ):

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
    reply_to=None,
    keyboard=None,
):

    payload = {
        "chat_id":
            chat_id,

        "text":
            text[
                :4096
            ],

        "disable_web_page_preview":
            True,
    }

    if reply_to:

        payload[
            "reply_parameters"
        ] = {
            "message_id":
                reply_to,

            "allow_sending_without_reply":
                True,
        }

    if keyboard:

        payload[
            "reply_markup"
        ] = keyboard

    return tg(
        "sendMessage",
        payload,
    )


def edit_message(
    chat_id,
    message_id,
    text,
    keyboard=None,
):

    payload = {
        "chat_id":
            chat_id,

        "message_id":
            message_id,

        "text":
            text[
                :4096
            ],

        "disable_web_page_preview":
            True,
    }

    if keyboard:

        payload[
            "reply_markup"
        ] = keyboard

    return tg(
        "editMessageText",
        payload,
    )


# =========================================================
# MEDIA GROUPS
# =========================================================

def cleanup_media_cache():

    now = time.time()

    for storage in (
        MEDIA_GROUP_TEXT_CACHE,
        RECENT_MEDIA_ACTIONS,
    ):

        for key in list(
            storage
        ):

            if (
                now
                - storage[
                    key
                ].get(
                    "ts",
                    0,
                )
                > MEDIA_GROUP_TTL
            ):

                storage.pop(
                    key,
                    None,
                )


def remember_media_text(message):

    gid = message.get(
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

    text = msg_text(
        message
    )

    if (
        not gid
        or not chat_id
        or not text
    ):

        return

    key = (
        str(chat_id),
        str(gid),
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


def extract_news_text(message):

    text = msg_text(
        message
    )

    if text:

        return text

    gid = message.get(
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
        not gid
        or not chat_id
    ):

        return ""

    return (
        MEDIA_GROUP_TEXT_CACHE
        .get(
            (
                str(chat_id),
                str(gid),
            )
        )
        or {}
    ).get(
        "text",
        "",
    )


def media_done(
    message,
    action,
):

    gid = message.get(
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
        not gid
        or not chat_id
    ):

        return False

    cleanup_media_cache()

    key = (
        action,
        str(chat_id),
        str(gid),
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
# MESSAGE DETECTION
# =========================================================

def is_forwarded(message):

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


def looks_like_news(message):

    text = norm(
        extract_news_text(
            message
        )
    )

    return bool(
        URL_RE.search(
            text
        )
        or is_forwarded(
            message
        )
        or len(text) >= 80
    )


def group_auto_checkable(message):

    text = norm(
        extract_news_text(
            message
        )
    )

    return bool(
        URL_RE.search(
            text
        )
        or is_forwarded(
            message
        )
    )


def private_checkable(message):

    text = norm(
        extract_news_text(
            message
        )
    )

    return bool(
        text
        and not text.startswith(
            "/"
        )
        and (
            URL_RE.search(
                text
            )
            or is_forwarded(
                message
            )
            or len(text) >= 8
        )
    )


def parse_manual_check(message):

    raw = msg_text(
        message
    )

    if not raw:

        return None

    low = norm(
        raw
    ).lower()

    cmd = re.match(
        (
            r"^/(?:check|factcheck)"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s+|$)"
        ),
        raw,
        re.I,
    )

    trigger = None

    if not cmd:

        for word in CHECK_WORDS:

            if (
                low == word
                or low.startswith(
                    word + " "
                )
            ):

                trigger = word
                break

    if (
        not cmd
        and not trigger
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
                    True
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
                source_date(
                    replied
                ),

            "_source_message":
                replied,
        }

    if cmd:

        text = raw[
            cmd.end():
        ].strip()

    else:

        text = raw[
            len(trigger):
        ].strip()

    return {
        "news_text":
            text,

        "source_message_id":
            message.get(
                "message_id"
            ),

        "source_date":
            "",

        "_source_message":
            message,
    }


# =========================================================
# GROQ + RATE LIMIT DIAGNOSTICS
# =========================================================

def log_groq_429(
    response,
    stage,
):

    interesting = {}

    for (
        key,
        value,
    ) in response.headers.items():

        k = key.lower()

        if (
            k == "retry-after"
            or k.startswith(
                "x-ratelimit"
            )
        ):

            interesting[
                k
            ] = value

    try:

        body = response.json()

    except Exception:

        body = response.text[
            :1200
        ]

    print(
        (
            "GROQ_429_DETAIL "
            + json.dumps(
                {
                    "stage":
                        stage,

                    "model":
                        GROQ_MODEL,

                    "headers":
                        interesting,

                    "body":
                        body,
                },
                ensure_ascii=False,
            )[
                :3500
            ]
        ),
        flush=True,
    )


def groq_text(
    system_text,
    user_text,
    max_tokens=600,
    temperature=0.03,
    retries=2,
    stage="unknown",
):

    last_error = None

    for attempt in range(
        retries
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

                "max_completion_tokens":
                    max_tokens,

                "stream":
                    False,
            },

            timeout=60,
        )

        if response.status_code == 429:

            log_groq_429(
                response,
                stage,
            )

            last_error = RuntimeError(
                f"GROQ_429:{stage}"
            )

            if (
                attempt
                == retries - 1
            ):

                break

            try:

                wait = float(
                    response.headers.get(
                        "retry-after",
                        "8",
                    )
                )

            except Exception:

                wait = 8

            wait = min(
                max(
                    wait + 1,
                    1,
                ),
                30,
            )

            print(
                (
                    "Groq 429 "
                    f"stage={stage}; "
                    f"retry in {wait}s"
                ),
                flush=True,
            )

            time.sleep(
                wait
            )

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
                (
                    "GROQ_400: "
                    + response.text[
                        :700
                    ]
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
            choices[
                0
            ].get(
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

        return ""

    if last_error:

        raise last_error

    return ""


# =========================================================
# OPTIONAL OCR
# =========================================================

def best_photo_file_id(message):

    photos = (
        message
        or {}
    ).get(
        "photo"
    ) or []

    if not photos:

        return ""

    best = max(
        photos,

        key=lambda x: (
            x.get(
                "file_size"
            )
            or 0,

            x.get(
                "width"
            )
            or 0,
        ),
    )

    return (
        best.get(
            "file_id"
        )
        or ""
    )


def telegram_photo_bytes(message):

    file_id = best_photo_file_id(
        message
    )

    if not file_id:

        return b""

    data = tg(
        "getFile",
        {
            "file_id":
                file_id
        },
    )

    file_path = (
        data.get(
            "result"
        )
        or {}
    ).get(
        "file_path"
    )

    if not file_path:

        return b""

    url = (
        "https://api.telegram.org/"
        "file/"
        f"bot{TELEGRAM_BOT_TOKEN}/"
        f"{file_path}"
    )

    response = requests.get(
        url,
        timeout=40,
    )

    response.raise_for_status()

    return response.content


def groq_ocr_image(image_bytes):

    if (
        not VISION_MODEL
        or not image_bytes
    ):

        return ""

    data_url = (
        "data:image/jpeg;base64,"
        + base64.b64encode(
            image_bytes
        ).decode(
            "ascii"
        )
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
            "model":
                VISION_MODEL,

            "messages": [
                {
                    "role":
                        "user",

                    "content": [
                        {
                            "type":
                                "text",

                            "text":
                                (
                                    "Распознай текст на изображении. "
                                    "Если это официальный документ, "
                                    "особенно точно выпиши номер, дату, "
                                    "название, орган, фамилии и ключевую "
                                    "формулировку. Верни только "
                                    "распознанный текст без анализа."
                                ),
                        },

                        {
                            "type":
                                "image_url",

                            "image_url": {
                                "url":
                                    data_url
                            },
                        },
                    ],
                }
            ],

            "temperature":
                0,

            "max_completion_tokens":
                700,
        },

        timeout=70,
    )

    if response.status_code == 429:

        log_groq_429(
            response,
            "ocr",
        )

        return ""

    if response.status_code in (
        400,
        401,
    ):

        print(
            (
                "OCR skipped: "
                f"{response.status_code} "
                f"{response.text[:300]}"
            ),
            flush=True,
        )

        return ""

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
        choices[
            0
        ].get(
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

        return norm(
            content
        )[
            :2800
        ]

    return ""


def maybe_ocr(
    message,
    news_text,
):

    if (
        not VISION_MODEL
        or not best_photo_file_id(
            message
        )
    ):

        return ""

    # На обычное фото с полноценной подписью
    # vision-вызов не тратим.
    if (
        not is_document_text(
            news_text
        )
        and len(
            norm(
                news_text
            )
        ) > 160
    ):

        return ""

    try:

        return groq_ocr_image(
            telegram_photo_bytes(
                message
            )
        )

    except Exception as exc:

        print(
            (
                "OCR warning: "
                f"{type(exc).__name__}: "
                f"{exc}"
            ),
            flush=True,
        )

        return ""


# =========================================================
# SEARCH PLAN
# =========================================================

def fallback_queries(
    news_text,
    preferred_domain="",
):

    cleaned = clean_search_text(
        news_text
    )

    tokens = lexical_tokens(
        cleaned,
        22,
    )

    base = short_query(
        (
            " ".join(
                tokens[
                    :14
                ]
            )
            or cleaned
            or preferred_domain
        ),
        280,
    )

    queries = []

    if (
        preferred_domain
        and base
    ):

        queries.append(
            (
                f"site:{preferred_domain} "
                f"{base}"
            )
        )

    if base:

        queries.append(
            base
        )

    alt = short_query(
        " ".join(
            tokens[
                6:22
            ]
        ),
        260,
    )

    if (
        alt
        and alt.lower()
        != base.lower()
    ):

        queries.append(
            alt
        )

    return unique_strings(
        queries,
        MAX_SEARCHES,
    )


def normalize_plan(
    data,
    fallback_text,
    preferred_domain="",
):

    claims = unique_strings(
        data.get(
            "claims"
        )
        or [],
        5,
    )

    entities = unique_strings(
        data.get(
            "entities"
        )
        or [],
        12,
    )

    aliases = unique_strings(
        data.get(
            "aliases"
        )
        or [],
        12,
    )

    queries = unique_strings(
        data.get(
            "queries"
        )
        or [],
        MAX_SEARCHES,
    )

    if not claims:

        claims = [
            short_query(
                clean_search_text(
                    fallback_text
                ),
                700,
            )
        ]

    if not queries:

        queries = fallback_queries(
            fallback_text,
            preferred_domain,
        )

    return {
        "claims":
            claims[
                :5
            ],

        "entities":
            entities[
                :12
            ],

        "aliases":
            aliases[
                :12
            ],

        "queries": [
            short_query(
                q,
                300,
            )
            for q
            in queries[
                :MAX_SEARCHES
            ]
            if norm(q)
        ],

        "freshness":
            norm(
                data.get(
                    "freshness"
                )
                or "normal"
            ).lower(),

        "document":
            bool(
                data.get(
                    "document"
                )
            ),
    }


def build_ai_plan(
    news_text,
    source_date_value,
    preferred_domain="",
):

    cleaned = clean_search_text(
        news_text
    )

    prompt = f"""
{date_context(source_date_value)}

НОВОСТЬ:

{cleaned[:MAX_NEWS_CHARS]}

Названный/приложенный первоисточник:

{preferred_domain or "не указан"}


Сделай компактный поисковый план.

Правила:

- выдели до 5 самостоятельных
проверяемых утверждений;

- определи главные сущности,
а не объекты сравнения;

- сам нормализуй разговорные,
региональные,
сокращённые
и переводные названия;

- в aliases добавь
полезные варианты названий
для поиска;

- иностранные имена
и цитаты
ищи также
на языке оригинала;

- если утверждений несколько,
запросы должны покрывать
разные важные утверждения;

- если указан первоисточник,
один запрос должен
целиться именно в него;

- не придумывай место,
дату,
номер документа
или источник,
которых нет в тексте;

- максимум 3
коротких естественных запроса
без кавычек
и Telegram-рекламы;

- freshness:
normal / fast_update / historical;

- document:
true только если новость
про официальный документ.


Верни только JSON:

{{
  "claims": ["..."],
  "entities": ["..."],
  "aliases": ["..."],
  "queries": ["..."],
  "freshness": "normal",
  "document": false
}}
""".strip()

    text = groq_text(
        PLANNER_SYSTEM,
        prompt,

        max_tokens=500,

        temperature=0,

        retries=2,

        stage="planner",
    )

    return normalize_plan(
        parse_json(
            text
        ),
        news_text,
        preferred_domain,
    )


def build_plan(
    news_text,
    source_date_value,
    preferred_domain="",
):

    key = make_key(
        news_text,
        (
            source_date_value
            + "|"
            + preferred_domain
        ),
    )

    cached = cache_get(
        PLAN_CACHE,
        key,
        PLAN_CACHE_TTL,
    )

    if cached:

        print(
            "PLAN CACHE HIT",
            flush=True,
        )

        return cached

    try:

        plan = build_ai_plan(
            news_text,
            source_date_value,
            preferred_domain,
        )

        print(
            "Planner: AI",
            flush=True,
        )

    except RuntimeError as exc:

        if "GROQ_429" not in str(
            exc
        ):

            raise

        # Если Groq упёрся в лимит именно
        # на планировщике —
        # весь фактчек не валим.
        # Строим обычные запросы
        # и сохраняем шанс на финальный ответ.

        print(
            (
                "Planner: fallback without AI "
                "because of Groq limit"
            ),
            flush=True,
        )

        plan = normalize_plan(
            {},
            news_text,
            preferred_domain,
        )

    if preferred_domain:

        marker = (
            f"site:{preferred_domain}"
            .lower()
        )

        if not any(
            marker in q.lower()
            for q
            in plan[
                "queries"
            ]
        ):

            if plan[
                "queries"
            ]:

                seed = plan[
                    "queries"
                ][
                    0
                ]

            else:

                seed = clean_search_text(
                    news_text
                )

            targeted = short_query(
                (
                    f"site:{preferred_domain} "
                    f"{seed}"
                ),
                300,
            )

            plan[
                "queries"
            ] = unique_strings(
                [
                    targeted
                ]
                + plan[
                    "queries"
                ],
                MAX_SEARCHES,
            )

    cache_put(
        PLAN_CACHE,
        key,
        plan,
    )

    return plan


# =========================================================
# TAVILY
# =========================================================

def tavily_search(
    query,
    query_index,
):

    query = short_query(
        query,
        320,
    )

    def request(q):

        return requests.post(
            TAVILY_SEARCH_API,

            headers={
                "Authorization":
                    f"Bearer {TAVILY_API_KEY}",

                "Content-Type":
                    "application/json",
            },

            json={
                "query":
                    q,

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

    response = request(
        query
    )

    if response.status_code == 400:

        response = request(
            short_query(
                query,
                240,
            )
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
            (
                "TAVILY_400: "
                + response.text[
                    :500
                ]
            )
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
                norm(
                    item.get(
                        "title"
                    )
                    or "Источник"
                ),

            "url":
                url,

            "content":
                norm(
                    item.get(
                        "content"
                    )
                    or ""
                ),

            "raw_content":
                "",

            "published_date":
                norm(
                    item.get(
                        "published_date"
                    )
                    or ""
                ),

            "tavily_score":
                float(
                    item.get(
                        "score"
                    )
                    or 0
                ),

            "query_index":
                query_index,
        })

    return out


def source_relevance(
    item,
    plan,
    news_text,
    preferred_domain="",
):

    hay = norm(
        (
            f"{item.get('title', '')} "
            f"{item.get('content', '')}"
        )
    ).lower()

    plan_text = " ".join(
        plan.get(
            "claims",
            [],
        )
        + plan.get(
            "entities",
            [],
        )
        + plan.get(
            "aliases",
            [],
        )
        + lexical_tokens(
            news_text,
            18,
        )
    )

    tokens = [
        x.lower()
        for x
        in lexical_tokens(
            plan_text,
            28,
        )
    ]

    hits = sum(
        1
        for token
        in tokens
        if token in hay
    )

    if not tokens:

        overlap = 0

    else:

        overlap = (
            70
            * hits
            / min(
                len(tokens),
                16,
            )
        )

    priority_bonus = {
        0:
            25,

        1:
            14,

        2:
            8,

        3:
            0,
    }[
        source_priority(
            item[
                "url"
            ],
            preferred_domain,
        )
    ]

    tavily_bonus = min(
        12,

        float(
            item.get(
                "tavily_score",
                0,
            )
        )
        * 12,
    )

    return round(
        min(
            100,
            overlap
            + priority_bonus
            + tavily_bonus,
        ),
        1,
    )


def merge_results(
    existing,
    fresh,
    plan,
    news_text,
    preferred_domain="",
):

    by_url = {
        item[
            "url"
        ].lower():
            item
        for item
        in existing
    }

    for item in fresh:

        item[
            "retrieval_score"
        ] = source_relevance(
            item,
            plan,
            news_text,
            preferred_domain,
        )

        key = item[
            "url"
        ].lower()

        old = by_url.get(
            key
        )

        if (
            not old
            or item[
                "retrieval_score"
            ]
            > old.get(
                "retrieval_score",
                0,
            )
        ):

            by_url[
                key
            ] = item

    return list(
        by_url.values()
    )


def add_original_urls(
    news_text,
    results,
):

    known = {
        x[
            "url"
        ].lower()
        for x
        in results
    }

    out = list(
        results
    )

    for raw in URL_RE.findall(
        news_text
        or ""
    ):

        url = clean_url(
            raw
        )

        d = domain(
            url
        )

        if (
            not url
            or d in {
                "t.me",
                "telegram.me",
                "telegram.org",
            }
            or url.lower()
            in known
        ):

            continue

        out.append({
            "title":
                "Исходная ссылка",

            "url":
                url,

            "content":
                "",

            "raw_content":
                "",

            "published_date":
                "",

            "tavily_score":
                1,

            "retrieval_score":
                100,

            "query_index":
                -1,

            "is_original":
                True,
        })

        known.add(
            url.lower()
        )

    return out


def search_plan(
    plan,
    news_text,
    preferred_domain="",
):

    key = make_key(
        news_text,
        json.dumps(
            plan.get(
                "queries",
                [],
            ),
            ensure_ascii=False,
        ),
    )

    cached = cache_get(
        RETRIEVAL_CACHE,
        key,
        RETRIEVAL_CACHE_TTL,
    )

    if cached:

        print(
            "RETRIEVAL CACHE HIT",
            flush=True,
        )

        return cached

    results = []
    used_queries = []

    for (
        index,
        query,
    ) in enumerate(
        plan.get(
            "queries",
            [],
        )[
            :MAX_SEARCHES
        ]
    ):

        print(
            (
                f"Tavily "
                f"{index + 1}/"
                f"{MAX_SEARCHES}: "
                f"{query}"
            ),
            flush=True,
        )

        fresh = tavily_search(
            query,
            index,
        )

        used_queries.append(
            query
        )

        results = merge_results(
            results,
            fresh,
            plan,
            news_text,
            preferred_domain,
        )

    results = add_original_urls(
        news_text,
        results,
    )

    value = (
        results,
        used_queries,
    )

    cache_put(
        RETRIEVAL_CACHE,
        key,
        value,
    )

    return value


def ranked_sources(
    results,
    preferred_domain="",
):

    return sorted(
        results,

        key=lambda item: (
            -float(
                item.get(
                    "retrieval_score",
                    0,
                )
            ),

            source_priority(
                item.get(
                    "url",
                    "",
                ),
                preferred_domain,
            ),

            -float(
                item.get(
                    "tavily_score",
                    0,
                )
            ),
        ),
    )


def select_sources(
    results,
    limit,
    preferred_domain="",
):

    items = ranked_sources(
        results,
        preferred_domain,
    )

    selected = []
    seen_urls = set()
    seen_domains = set()

    # Заявленный первоисточник
    # стараемся включить обязательно.

    if preferred_domain:

        for item in items:

            d = domain(
                item[
                    "url"
                ]
            )

            if (
                d == preferred_domain
                or d.endswith(
                    "."
                    + preferred_domain
                )
            ):

                selected.append(
                    item
                )

                seen_urls.add(
                    item[
                        "url"
                    ].lower()
                )

                seen_domains.add(
                    d
                )

                break

    # Сначала разнообразные домены.

    for item in items:

        if len(
            selected
        ) >= limit:

            break

        key = item[
            "url"
        ].lower()

        d = domain(
            item[
                "url"
            ]
        )

        if (
            key in seen_urls
            or d in seen_domains
        ):

            continue

        selected.append(
            item
        )

        seen_urls.add(
            key
        )

        seen_domains.add(
            d
        )

    # Если не набрали лимит —
    # разрешаем повтор домена.

    for item in items:

        if len(
            selected
        ) >= limit:

            break

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

    return selected


def tavily_extract(urls):

    urls = unique_strings(
        [
            clean_url(x)
            for x
            in urls
            if x
        ],
        MAX_EXTRACT_URLS,
    )

    if not urls:

        return {}

    try:

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

        out = {}

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

            content = norm(
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
                and content
            ):

                out[
                    url.lower()
                ] = content

        return out

    except RuntimeError:

        raise

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


def enrich_sources(
    results,
    preferred_domain="",
):

    selected = select_sources(
        results,
        MAX_EXTRACT_URLS,
        preferred_domain,
    )

    extracted = tavily_extract(
        [
            item[
                "url"
            ]
            for item
            in selected
        ]
    )

    for item in results:

        raw = extracted.get(
            item[
                "url"
            ].lower()
        )

        if raw:

            item[
                "raw_content"
            ] = raw

    return results


# =========================================================
# FINAL ANSWER NORMALIZATION
# =========================================================

def parse_used_sources(
    answer,
    sources,
):

    match = re.search(
        (
            r"(?i)\b"
            r"USED\s*:\s*"
            r"([0-9][0-9,\s]*)"
        ),
        answer
        or "",
    )

    used = []

    if match:

        for raw in match.group(
            1
        ).split(
            ","
        ):

            raw = raw.strip()

            if not raw.isdigit():

                continue

            index = int(
                raw
            )

            if (
                1 <= index
                <= len(
                    sources
                )
                and sources[
                    index - 1
                ] not in used
            ):

                used.append(
                    sources[
                        index - 1
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

        used = sources[
            :min(
                3,
                len(sources),
            )
        ]

    return (
        answer,
        used,
    )


def detect_verdict(answer):

    head = (
        answer
        or ""
    )[
        :900
    ]

    candidates = []

    # Сначала точные варианты.

    for verdict in VERDICTS:

        pos = head.find(
            verdict
        )

        if pos >= 0:

            candidates.append(
                (
                    pos,
                    verdict,
                    pos + len(
                        verdict
                    ),
                )
            )

    # Если модель изменила emoji,
    # markdown или регистр —
    # ищем текст метки.

    low = (
        head.lower()
        .replace(
            "ё",
            "е",
        )
    )

    for (
        label,
        verdict,
    ) in VERDICT_LABELS:

        label_low = (
            label.lower()
            .replace(
                "ё",
                "е",
            )
        )

        pos = low.find(
            label_low
        )

        if pos >= 0:

            candidates.append(
                (
                    pos,
                    verdict,
                    pos + len(
                        label_low
                    ),
                )
            )

    if not candidates:

        return None

    return min(
        candidates,
        key=lambda x:
            x[0],
    )


def normalize_final_answer(answer):

    answer = (
        answer
        or ""
    ).strip()

    # В Railway теперь видно,
    # что именно реально вернул Groq.

    print(
        (
            "GROQ_RAW_FINAL: "
            + answer[
                :1800
            ].replace(
                "\n",
                "\\n",
            )
        ),
        flush=True,
    )

    found = detect_verdict(
        answer
    )

    if not found:

        return (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Модель не выдала понятный вердикт. "
            "Источники найдены, но ответ лучше перепроверить.\n"
            "Уверенность: 2/10"
        )

    (
        start,
        verdict,
        end,
    ) = found

    tail = answer[
        end:
    ]

    # Убираем:
    # **,
    # ###,
    # Вердикт:,
    # тире,
    # двоеточия и т.д.

    tail = re.sub(
        (
            r"^[\s*_`#.:;"
            r"—–\-\]\)]+"
        ),
        "",
        tail,
    )

    if tail:

        answer = (
            verdict
            + "\n"
            + tail
        )

    else:

        answer = verdict

    # Остатки markdown
    # на отдельных строках.

    answer = re.sub(
        r"(?m)^\s*\*\*\s*",
        "",
        answer,
    )

    answer = re.sub(
        r"(?m)\s*\*\*\s*$",
        "",
        answer,
    )

    confidence_match = re.search(
        (
            r"(?i)"
            r"Уверенность\s*:\s*"
            r"(\d{1,2})"
            r"\s*/\s*10"
        ),
        answer,
    )

    confidence = None

    if confidence_match:

        confidence = max(
            0,

            min(
                10,

                int(
                    confidence_match.group(
                        1
                    )
                ),
            ),
        )

    # Красный запрещён,
    # если сама модель
    # не уверена минимум на 7/10.

    if (
        verdict
        == "🔴 ПИЗДЁЖ"
        and (
            confidence is None
            or confidence < 7
        )
    ):

        answer = answer.replace(
            "🔴 ПИЗДЁЖ",
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА",
            1,
        )

    # Защита от внезапного
    # английского ответа.

    latin = len(
        re.findall(
            r"[A-Za-z]",
            answer,
        )
    )

    cyr = len(
        re.findall(
            r"[А-Яа-яЁё]",
            answer,
        )
    )

    if (
        latin
        > max(
            100,
            cyr * 1.5,
        )
    ):

        return (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Модель вернула пояснение не на русском, "
            "поэтому этот ответ лучше перепроверить.\n"
            "Уверенность: 2/10"
        )

    return answer[
        :3900
    ]


def analyze(
    news_text,
    source_date_value,
    plan,
    used_queries,
    results,
    preferred_domain="",
):

    sources = select_sources(
        results,
        MAX_AI_SOURCES,
        preferred_domain,
    )

    blocks = []
    total = 0

    for (
        index,
        item,
    ) in enumerate(
        sources,
        1,
    ):

        raw = norm(
            item.get(
                "raw_content"
            )
            or ""
        )

        if raw:

            evidence = (
                "ИЗВЛЕЧЁННЫЙ ТЕКСТ:\n"
                + raw[
                    :MAX_EXTRACT_CHARS
                ]
            )

        else:

            evidence = (
                "ПОИСКОВЫЙ СНИППЕТ:\n"
                + norm(
                    item.get(
                        "content"
                    )
                    or ""
                )[
                    :MAX_SNIPPET_CHARS
                ]
            )

        block = (
            f"[{index}]\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{domain(item['url'])}\n"
            f"Дата материала: "
            f"{item.get('published_date') or 'неизвестна'}\n"
            f"Релевантность: "
            f"{item.get('retrieval_score', 0)}\n"
            f"{evidence}"
        )

        remaining = (
            MAX_TOTAL_SOURCE_CHARS
            - total
        )

        if remaining <= 0:

            break

        block = block[
            :remaining
        ]

        blocks.append(
            block
        )

        total += (
            len(block)
            + 2
        )

    claims_text = "\n".join(
        (
            "- "
            + x
        )
        for x
        in plan.get(
            "claims",
            [],
        )
    )

    entities_text = ", ".join(
        plan.get(
            "entities",
            [],
        )
        + plan.get(
            "aliases",
            [],
        )
    )

    query_text = "\n".join(
        (
            "- "
            + x
        )
        for x
        in used_queries
    )

    source_text = "\n\n".join(
        blocks
    )

    prompt = f"""
{date_context(source_date_value)}

ИСХОДНАЯ НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}


УТВЕРЖДЕНИЯ,
КОТОРЫЕ ВЫДЕЛИЛ ПЛАНИРОВЩИК:

{claims_text or "- не выделены"}


СУЩНОСТИ И АЛИАСЫ:

{entities_text or "не выделены"}


FRESHNESS:

{plan.get("freshness", "normal")}


ДОКУМЕНТ:

{"ДА" if plan.get("document") else "НЕТ"}


НАЗВАННЫЙ ПЕРВОИСТОЧНИК:

{preferred_domain or "не указан"}


ПОИСКОВЫЕ ЗАПРОСЫ:

{query_text}


ИСТОЧНИКИ:

{source_text}


Сделай финальный фактчек.

Оцени центральный смысл новости
и существенные утверждения.

Если центральный тезис подтверждён,
но одна второстепенная деталь
не найдена,
не называй всю новость ложью.

Если источник использует
другую формулировку
того же смысла,
учитывай смысловую эквивалентность.

Если найден только
похожий объект,
документ
или версия —
не считай это опровержением.

Обязательно закончи строками:

Уверенность: N/10
USED: 1,2
""".strip()

    raw_answer = groq_text(
        FINAL_SYSTEM,
        prompt,

        max_tokens=650,

        temperature=0.02,

        retries=2,

        stage="final",
    )

    if not raw_answer:

        raise RuntimeError(
            "Groq вернул пустой ответ"
        )

    (
        answer,
        used,
    ) = parse_used_sources(
        raw_answer,
        sources,
    )

    answer = normalize_final_answer(
        answer
    )

    return (
        answer,
        used,
    )


# =========================================================
# SOURCE BUTTONS
# =========================================================

def source_name(
    item,
    index,
):

    d = domain(
        item[
            "url"
        ]
    )

    for (
        known,
        name,
    ) in SOURCE_NAMES.items():

        if (
            d == known
            or d.endswith(
                "."
                + known
            )
        ):

            return (
                f"{index} · {name}"
            )

    title = norm(
        item.get(
            "title"
        )
        or d
    )

    if len(title) > 28:

        title = (
            title[
                :27
            ].rstrip()
            + "…"
        )

    return (
        f"{index} · {title}"
    )


def keyboard(results):

    buttons = []
    seen = set()

    for (
        index,
        item,
    ) in enumerate(
        results[
            :MAX_TG_SOURCES
        ],
        1,
    ):

        url = clean_url(
            item.get(
                "url"
            )
            or ""
        )

        if (
            not url.startswith(
                (
                    "http://",
                    "https://",
                )
            )
            or url.lower()
            in seen
        ):

            continue

        seen.add(
            url.lower()
        )

        buttons.append({
            "text":
                source_name(
                    item,
                    index,
                ),

            "url":
                url,
        })

    if not buttons:

        return None

    return {
        "inline_keyboard": [
            buttons[
                i:i + 2
            ]
            for i
            in range(
                0,
                len(buttons),
                2,
            )
        ]
    }


# =========================================================
# FACTCHECK
# =========================================================

def factcheck(
    news_text,
    source_date_value="",
):

    news_text = norm_lines(
        news_text
    )

    final_key = make_key(
        news_text,
        source_date_value,
    )

    cached = cache_get(
        FACTCHECK_CACHE,
        final_key,
        CACHE_TTL,
    )

    if cached:

        print(
            "FACTCHECK CACHE HIT",
            flush=True,
        )

        return cached

    preferred_domain = detect_preferred_domain(
        news_text
    )

    plan = build_plan(
        news_text,
        source_date_value,
        preferred_domain,
    )

    print(
        (
            "PLAN: "
            + json.dumps(
                {
                    "claims":
                        plan.get(
                            "claims",
                            [],
                        ),

                    "entities":
                        plan.get(
                            "entities",
                            [],
                        ),

                    "aliases":
                        plan.get(
                            "aliases",
                            [],
                        ),

                    "queries":
                        plan.get(
                            "queries",
                            [],
                        ),

                    "preferred_domain":
                        preferred_domain,
                },
                ensure_ascii=False,
            )[
                :3000
            ]
        ),
        flush=True,
    )

    if not plan.get(
        "queries"
    ):

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Не получилось построить "
                "нормальный поисковый план.\n"
                "Уверенность: 1/10"
            ),
            [],
        )

    (
        results,
        used_queries,
    ) = search_plan(
        plan,
        news_text,
        preferred_domain,
    )

    filtered = []

    for item in results:

        priority = source_priority(
            item[
                "url"
            ],
            preferred_domain,
        )

        if (
            item.get(
                "retrieval_score",
                0,
            ) >= 18
            or priority <= 2
            or item.get(
                "is_original"
            )
        ):

            filtered.append(
                item
            )

    if not filtered:

        answer = (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Поиск не нашёл достаточно точных источников. "
            "Это не доказательство лжи.\n"
            "Уверенность: 2/10"
        )

        value = (
            answer,
            [],
        )

        cache_put(
            FACTCHECK_CACHE,
            final_key,
            value,
        )

        return value

    filtered = enrich_sources(
        filtered,
        preferred_domain,
    )

    (
        answer,
        used,
    ) = analyze(
        news_text,
        source_date_value,
        plan,
        used_queries,
        filtered,
        preferred_domain,
    )

    value = (
        answer,
        used,
    )

    cache_put(
        FACTCHECK_CACHE,
        final_key,
        value,
    )

    return value


# =========================================================
# ERRORS
# =========================================================

def friendly_error(exc):

    text = str(
        exc
    )

    if "TAVILY_401" in text:

        return (
            "Tavily не пускает по ключу. "
            "Проверь TAVILY_API_KEY."
        )

    if "TAVILY_429" in text:

        return (
            "У Tavily закончился лимит "
            "или прилетел rate limit."
        )

    if "GROQ_401" in text:

        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY."
        )

    if "GROQ_429" in text:

        return (
            "Groq упёрся в лимит. "
            "Подробности лимита записал в Railway. "
            "Попробуй позже."
        )

    if "GROQ_413" in text:

        return (
            "Для Groq запрос "
            "слишком большой."
        )

    if "GROQ_400" in text:

        return (
            "Groq отклонил запрос. "
            "Подробность есть в Railway."
        )

    if "TAVILY_400" in text:

        return (
            "Tavily отклонил поисковый запрос. "
            "Подробность есть в Railway."
        )

    return (
        "Чёт фактчек наебнулся. "
        "Ошибка записана в Railway."
    )


# =========================================================
# HANDLER
# =========================================================

def handle_message(message):

    cleanup_media_cache()

    remember_media_text(
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

    user = (
        message.get(
            "from"
        )
        or {}
    )

    raw = msg_text(
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
        re.I,
    ):

        send_message(
            chat_id,
            (
                "Кидай новость, ссылку "
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
        re.I,
    ):

        send_message(
            chat_id,
            (
                "Твой Telegram ID: "
                f"{user.get('id', 'неизвестно')}"
            ),
            message_id,
        )

        return

    request_data = parse_manual_check(
        message
    )

    if (
        request_data
        and request_data.get(
            "invalid_reply"
        )
    ):

        send_message(
            chat_id,
            (
                "Это не похоже на новость 😄 "
                "Я фактчекаю посты, "
                "ссылки и новостные тексты."
            ),
            message_id,
        )

        return

    # =====================================================
    # ЛИЧКА
    # =====================================================

    if (
        request_data is None
        and chat_type
        == "private"
        and private_checkable(
            message
        )
    ):

        if media_done(
            message,
            "private_auto",
        ):

            return

        request_data = {
            "news_text":
                extract_news_text(
                    message
                ),

            "source_message_id":
                message_id,

            "source_date":
                source_date(
                    message
                ),

            "_source_message":
                message,
        }

    # =====================================================
    # ГРУППА
    #
    # AUTO_CHECK строгий:
    # только пересылка или ссылка.
    #
    # Обычная длинная переписка
    # больше не триггерит бота.
    # =====================================================

    if (
        request_data is None
        and chat_type
        in {
            "group",
            "supergroup",
        }
        and AUTO_CHECK
        and group_auto_checkable(
            message
        )
    ):

        if media_done(
            message,
            "group_auto",
        ):

            return

        request_data = {
            "news_text":
                extract_news_text(
                    message
                ),

            "source_message_id":
                message_id,

            "source_date":
                source_date(
                    message
                ),

            "_source_message":
                message,
        }

    if not request_data:

        return

    news_text = norm_lines(
        request_data.get(
            "news_text"
        )
        or ""
    )

    if len(
        norm(
            news_text
        )
    ) < 4:

        return

    reply_to = (
        request_data.get(
            "source_message_id"
        )
        or message_id
    )

    date_value = (
        request_data.get(
            "source_date"
        )
        or ""
    )

    source_message = (
        request_data.get(
            "_source_message"
        )
        or message
    )

    status = send_message(
        chat_id,
        (
            "🔎 Ща разберу новость "
            "и пробью источники…"
        ),
        reply_to,
    )

    status_id = (
        status.get(
            "result"
        )
        or {}
    ).get(
        "message_id"
    )

    try:

        ocr_text = maybe_ocr(
            source_message,
            news_text,
        )

        check_text = news_text

        if ocr_text:

            check_text += (
                "\n\n"
                "ТЕКСТ С ИЗОБРАЖЕНИЯ:\n"
                + ocr_text
            )

        (
            answer,
            used,
        ) = factcheck(
            check_text,
            date_value,
        )

        kb = keyboard(
            used
        )

        if status_id:

            edit_message(
                chat_id,
                status_id,
                answer,
                kb,
            )

        else:

            send_message(
                chat_id,
                answer,
                reply_to,
                kb,
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

        if status_id:

            try:

                edit_message(
                    chat_id,
                    status_id,
                    error_text,
                )

                return

            except Exception:

                pass

        send_message(
            chat_id,
            error_text,
            reply_to,
        )


# =========================================================
# MAIN
# =========================================================

def validate():

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
                "Не заданы переменные: "
                + ", ".join(
                    missing
                )
            )
        )


def main():

    validate()

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
                f"{exc}"
            ),
            flush=True,
        )

    print(
        (
            "Chicken Company bot started; "
            "ai_planner=True; "
            "searches=max3; "
            "output_normalizer=True; "
            "plan_cache=6h; "
            "retrieval_cache=1h; "
            "group_auto_strict=True; "
            f"ocr={'ON' if VISION_MODEL else 'OFF'}"
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

                if update.get(
                    "message"
                ):

                    handle_message(
                        update[
                            "message"
                        ]
                    )

        except requests.HTTPError as exc:

            code = (
                exc.response.status_code
                if exc.response
                is not None
                else None
            )

            if code == 409:

                print(
                    (
                        "Telegram 409: "
                        "другой экземпляр "
                        "уже делает getUpdates. "
                        "В Railway оставь "
                        "1 worker / 1 replica."
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