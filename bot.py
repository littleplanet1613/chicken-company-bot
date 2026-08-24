import os
import re
import time
import json
import random
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
NIKOLAI_USER_ID = os.getenv("NIKOLAI_USER_ID", "").strip()
AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {"1", "true", "yes", "on"}
TZ_HOURS = int(os.getenv("RELATIVE_DATE_TZ_OFFSET_HOURS", "3"))

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"


# =========================================================
# V8 BUDGETS
# =========================================================

# Главное изменение V8:
#
# Groq НЕ строит обычные поисковые запросы.
#
# Обычная новость:
# Python -> Tavily -> Groq только финальный ответ.
#
# Сложная иностранная тема:
# Python -> Tavily -> при слабой выдаче
# 1 Groq для original-language query -> Tavily -> Groq финал.

MAX_PRIMARY_SEARCHES = 2
MAX_TOTAL_SEARCHES = 3
MAX_RESULTS_PER_QUERY = 6

MAX_EXTRACT_URLS = 3
MAX_AI_SOURCES = 4
MAX_TG_SOURCES = 4

MAX_EXTRACT_CHARS_PER_SOURCE = 1200
MAX_SEARCH_SNIPPET_CHARS = 550
MAX_TOTAL_SOURCE_CHARS = 6200

EARLY_STOP_TRUSTED_SCORE = 56
EARLY_STOP_OTHER_SCORE = 68
FINAL_WEAK_SCORE = 48


# =========================================================
# CACHE
# =========================================================

CACHE_TTL_SECONDS = 6 * 60 * 60
CACHE_MAX_ITEMS = 300

FACTCHECK_CACHE = {}


# =========================================================
# MEDIA CACHE
# =========================================================

MEDIA_GROUP_TTL = 3600

RECENT_MEDIA_ACTIONS = {}
MEDIA_GROUP_TEXT_CACHE = {}


# =========================================================
# REGEX
# =========================================================

URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.I,
)

HANDLE_RE = re.compile(
    r"(?<!\w)@[A-Za-z0-9_]{3,}"
)

UPDATE_RE = re.compile(
    r"(?:"
    r"\bвырос(?:ло|ла|ли)?\b|"
    r"\bувеличил(?:ось|ась|ись)?\b|"
    r"\bвозрос(?:ло|ла|ли)?\b|"
    r"\bпо последним данным\b|"
    r"\bпо уточн[её]нным данным\b|"
    r"\bстало известно\b|"
    r"\bтеперь составляет\b|"
    r"\bдостигло\b|"
    r"\brises? to\b|"
    r"\brose to\b|"
    r"\bhas risen to\b|"
    r"\blatest figures?\b|"
    r"\bupdated figures?\b"
    r")",
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


STOPWORDS = {
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
    "ночью",
    "накануне",
    "только",
    "что",
    "прямо",
    "сейчас",
    "было",
    "будет",
    "стало",
    "своей",
    "своего",
    "своих",
    "якобы",
    "сообщил",
    "сообщила",
    "сообщили",
    "заявил",
    "заявила",
    "заявили",
    "говорит",
    "отметил",
    "отметила",
    "утверждает",
    "данным",
    "словам",
    "новость",
    "информация",
    "подписаться",
    "подписывайтесь",
    "канал",
    "источник",

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
    "just",
    "now",
    "tonight",
    "news",
    "subscribe",
}


FOREIGN_MARKERS = (
    "финлянд",
    "стубб",
    "сша",
    "америк",
    "трамп",
    "байден",
    "франц",
    "макрон",
    "германи",
    "мерц",
    "шольц",
    "британ",
    "стармер",
    "евросоюз",
    "европейск",
    "нато",
    "брюссел",
    "китай",
    "си цзиньпин",
    "израил",
    "нетаньяху",
    "турци",
    "эрдоган",
    "польш",
    "туск",
    "итал",
    "мелони",
    "эстони",
    "латви",
    "литв",
    "швец",
    "норвег",
    "дани",

    "riot games",
    "bloomberg",
    "wall street journal",
    "wsj",
    "reuters",
    "bbc",
)


RUS_NUMBER_WORDS = {
    "ноль": "0",

    "один": "1",
    "одна": "1",
    "одно": "1",

    "два": "2",
    "две": "2",

    "три": "3",
    "трех": "3",
    "трёх": "3",

    "четыре": "4",
    "четырех": "4",
    "четырёх": "4",

    "пять": "5",
    "пяти": "5",

    "шесть": "6",
    "шести": "6",

    "семь": "7",
    "семи": "7",

    "восемь": "8",
    "восьми": "8",

    "девять": "9",
    "девяти": "9",

    "десять": "10",
    "десяти": "10",

    "одиннадцать": "11",
    "одиннадцати": "11",

    "двенадцать": "12",
    "двенадцати": "12",

    "тринадцать": "13",
    "тринадцати": "13",

    "четырнадцать": "14",
    "четырнадцати": "14",

    "пятнадцать": "15",
    "пятнадцати": "15",

    "шестнадцать": "16",
    "шестнадцати": "16",

    "семнадцать": "17",
    "семнадцати": "17",

    "восемнадцать": "18",
    "восемнадцати": "18",

    "девятнадцать": "19",
    "девятнадцати": "19",

    "двадцать": "20",
    "двадцати": "20",
}


# =========================================================
# FINAL FACTCHECK PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.

Работай только по переданным источникам.
Ничего не выдумывай.

Правила:

1. Мысленно разбивай составную новость
на ключевые факты,
но не показывай C1/C2/C3.

2. Разные части новости
могут подтверждаться разными источниками.

3. «Не найдено подтверждение»
НЕ означает
«доказано, что это ложь».

4. 🔴 ПИЗДЁЖ —
только если центральный факт
надёжно опровергнут.

5. 🟡 ПОЛУПИЗДЁЖ —
событие реально,
но важная часть действительно неверна.

Молчание источника
о детали
не является опровержением.

6. 🟠 НАЕБАЛИ С КОНТЕКСТОМ —
факты реальные,
но дата/контекст/цитата
создают ложное впечатление.

7. ⚪ ХУЙ ПОЙМЁШЬ ПОКА —
данных реально недостаточно.

8. Не смешивай похожие события.

Сверяй:

место,
объект,
людей,
дату,
цифры,
обстоятельства.

9. «Огонь не дошёл до парка»
не опровергает
пожар рядом с парком.

10. Иностранную цитату
сравнивай по смыслу и контексту,
а не по буквальному русскому переводу.

11. Для локального события
местный официальный орган
или региональное СМИ
могут быть лучшим источником.

12. Извлечённый текст страницы
сильнее поискового сниппета.

13. Для быстро меняющихся новостей
старый источник с меньшим числом
не опровергает
более свежий апдейт.

14. Строго различай:

пострадавшие,
раненые,
госпитализированные,
погибшие,
погибшие дети,
дети среди раненых,
дети среди госпитализированных.


Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА


Формат:

Первая строка —
только вердикт.

Дальше 2–4 коротких предложения.

Последняя видимая строка:

Уверенность: N/10

После неё:

USED: 1,2

URL в текст не вставляй.
""".strip()


# =========================================================
# HELPERS
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

    lines = []

    for line in text.split("\n"):

        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if line:

            lines.append(
                line
            )

    return "\n".join(
        lines
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
        .split(
            "#",
            1,
        )[0]
        .rstrip(
            ").,!?;:'\""
        )
        .rstrip("/")
    )


def domain(url):

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


def short_query(
    text,
    limit=280,
):

    text = norm(
        text
    )

    if len(text) <= limit:

        return text

    cut = text[
        :limit
    ]

    pos = cut.rfind(
        " "
    )

    if pos > limit * 0.6:

        cut = cut[
            :pos
        ]

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

    a = text.find(
        "{"
    )

    b = text.rfind(
        "}"
    )

    if (
        a < 0
        or b <= a
    ):

        return {}

    try:

        return json.loads(
            text[
                a:b + 1
            ]
        )

    except Exception:

        return {}


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

    out = []

    for raw_line in work.splitlines():

        line = norm(
            raw_line
        )

        if not line:

            continue

        line = re.sub(
            (
                r"(?i)\bFTT\b"
                r"\s*[-—|:]?\s*"
                r"подпис\w*.*$"
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

        line = norm(
            line
        )

        if line:

            out.append(
                line
            )

    cleaned = norm(
        " ".join(
            out
        )
    )

    return (
        cleaned
        or norm(
            original
        )
    )


def important_tokens(
    text,
    limit=12,
):

    result = []
    seen = set()

    for token in re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{3,}"
        ),
        text or "",
    ):

        low = token.lower()

        if (
            low in STOPWORDS
            or low in seen
        ):

            continue

        seen.add(
            low
        )

        result.append(
            token
        )

        if len(
            result
        ) >= limit:

            break

    return result


def extract_numbers(text):

    vals = re.findall(
        (
            r"\b\d{1,2}:\d{2}\b|"
            r"\b\d+(?:[.,]\d+)?\s*"
            r"(?:га|км|м|%|млн|млрд)?\b"
        ),
        text or "",
        flags=re.I,
    )

    out = []

    for item in vals:

        item = norm(
            item
        )

        if (
            item
            and item not in out
        ):

            out.append(
                item
            )

    lowered = (
        text
        or ""
    ).lower()

    for (
        word,
        digit,
    ) in RUS_NUMBER_WORDS.items():

        if re.search(
            (
                rf"(?<![а-яё])"
                rf"{re.escape(word)}"
                rf"(?![а-яё])"
            ),
            lowered,
            re.I,
        ):

            if digit not in out:

                out.append(
                    digit
                )

    return out[
        :12
    ]


def extract_capitalized_tokens(
    text,
    limit=8,
):

    out = []
    seen = set()

    for token in re.findall(
        (
            r"\b"
            r"[А-ЯЁA-Z]"
            r"[А-ЯЁA-Za-zа-яё\-]{2,}"
            r"\b"
        ),
        text or "",
    ):

        low = token.lower()

        if (
            low in STOPWORDS
            or low in seen
        ):

            continue

        if low in {
            "президент",
            "власти",
            "число",
            "информация",
            "сегодня",
            "ранее",
        }:

            continue

        seen.add(
            low
        )

        out.append(
            token
        )

        if len(
            out
        ) >= limit:

            break

    return out


def is_fast_update(text):

    return bool(
        UPDATE_RE.search(
            text
            or ""
        )
    )


def looks_foreign(text):

    low = (
        text
        or ""
    ).lower()

    if any(
        marker in low

        for marker
        in FOREIGN_MARKERS
    ):

        return True

    latin_words = re.findall(
        (
            r"\b"
            r"[A-Za-z]"
            r"[A-Za-z\-]{3,}"
            r"\b"
        ),
        text or "",
    )

    return (
        len(
            latin_words
        )
        >= 2
    )


# =========================================================
# CACHE
# =========================================================

def cache_key(
    news_text,
    source_date_value,
):

    raw = (
        norm(
            news_text
        ).lower()
        + "\n"
        + (
            source_date_value
            or ""
        )
    )

    return hashlib.sha256(
        raw.encode(
            "utf-8"
        )
    ).hexdigest()


def cleanup_factcheck_cache():

    now = time.time()

    for key in list(
        FACTCHECK_CACHE
    ):

        if (
            now
            - FACTCHECK_CACHE[
                key
            ].get(
                "ts",
                0,
            )
            > CACHE_TTL_SECONDS
        ):

            FACTCHECK_CACHE.pop(
                key,
                None,
            )

    if (
        len(
            FACTCHECK_CACHE
        )
        > CACHE_MAX_ITEMS
    ):

        ordered = sorted(
            FACTCHECK_CACHE.items(),
            key=lambda pair:
                pair[
                    1
                ].get(
                    "ts",
                    0,
                ),
        )

        remove_count = (
            len(
                FACTCHECK_CACHE
            )
            - CACHE_MAX_ITEMS
        )

        for (
            key,
            _,
        ) in ordered[
            :remove_count
        ]:

            FACTCHECK_CACHE.pop(
                key,
                None,
            )


def cache_get(
    news_text,
    source_date_value,
):

    cleanup_factcheck_cache()

    item = FACTCHECK_CACHE.get(
        cache_key(
            news_text,
            source_date_value,
        )
    )

    if not item:

        return None

    if (
        time.time()
        - item.get(
            "ts",
            0,
        )
        > CACHE_TTL_SECONDS
    ):

        return None

    print(
        "FACTCHECK CACHE HIT",
        flush=True,
    )

    return (
        item[
            "answer"
        ],
        item[
            "sources"
        ],
    )


def cache_put(
    news_text,
    source_date_value,
    answer,
    sources,
):

    cleanup_factcheck_cache()

    FACTCHECK_CACHE[
        cache_key(
            news_text,
            source_date_value,
        )
    ] = {
        "ts":
            time.time(),

        "answer":
            answer,

        "sources":
            sources,
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

    tz = timezone(
        timedelta(
            hours=
                TZ_HOURS
        )
    )

    try:

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
            "Слова сегодня/вчера/этой ночью "
            "считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна. "
        "Не подставляй текущую дату сервера "
        "вместо сегодня/вчера."
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
        json=payload or {},
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
# MEDIA CACHE
# =========================================================

def cleanup_media_cache():

    now = time.time()

    for storage in (
        RECENT_MEDIA_ACTIONS,
        MEDIA_GROUP_TEXT_CACHE,
    ):

        for key in list(
            storage
        ):

            if (
                now
                - storage[
                    key
                ]["ts"]
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
        str(
            chat_id
        ),
        str(
            gid
        ),
    )

    old = (
        MEDIA_GROUP_TEXT_CACHE
        .get(
            key
        )
    )

    if (
        not old
        or len(
            text
        ) > len(
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
                str(
                    chat_id
                ),
                str(
                    gid
                ),
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
        str(
            chat_id
        ),
        str(
            gid
        ),
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
        or len(
            text
        ) >= 80
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
            or len(
                text
            ) >= 8
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
        }

    if cmd:

        text = raw[
            cmd.end():
        ].strip()

    else:

        text = raw[
            len(
                trigger
            ):
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
    }


# =========================================================
# NIKOLAI
# =========================================================

def is_nikolai(user):

    if not user:

        return False

    if NIKOLAI_USER_ID:

        return (
            str(
                user.get(
                    "id",
                    "",
                )
            )
            == NIKOLAI_USER_ID
        )

    name = norm(
        (
            f"{user.get('first_name', '')} "
            f"{user.get('last_name', '')} "
            f"{user.get('username', '')}"
        )
    ).lower()

    return any(
        x in name

        for x in (
            "николай",
            "коля",
            "nikolai",
            "nikolay",
            "kolya",
        )
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
            "Николай опять принёс свежак "
            "из информационной канализации."
        ),
    ])


# =========================================================
# GROQ
# =========================================================

def groq_text(
    system,
    user,
    max_tokens=520,
    temperature=0.04,
):

    for attempt in range(
        3
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
                            system,
                    },

                    {
                        "role":
                            "user",

                        "content":
                            user,
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

            if attempt == 2:

                raise RuntimeError(
                    "GROQ_429"
                )

            wait = 15

            try:

                wait = min(
                    60,

                    max(
                        1,

                        float(
                            response.headers.get(
                                "retry-after",
                                "15",
                            )
                        )
                        + 1,
                    ),
                )

            except Exception:

                pass

            print(
                f"Groq 429, wait {wait}s",
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

    return ""


# =========================================================
# DETERMINISTIC SEARCH PLAN
# =========================================================

def build_precision_query(
    cleaned,
    source_date_value,
    update_mode,
):

    names = extract_capitalized_tokens(
        cleaned,
        6,
    )

    tokens = important_tokens(
        cleaned,
        10,
    )

    numbers = extract_numbers(
        cleaned
    )

    parts = []

    for item in (
        names
        + tokens
        + numbers
    ):

        if item not in parts:

            parts.append(
                item
            )

    if (
        update_mode
        and source_date_value
    ):

        parts.append(
            source_date_value
        )

    return short_query(
        " ".join(
            parts
        ),
        280,
    )


def build_second_query(
    cleaned,
    source_date_value,
    update_mode,
):

    names = extract_capitalized_tokens(
        cleaned,
        5,
    )

    nums = extract_numbers(
        cleaned
    )

    categories = []

    for token in re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{2,}"
        ),
        cleaned,
    ):

        low = token.lower()

        if any(
            root in low

            for root in (
                "пожар",
                "сафари",
                "атак",
                "бпла",
                "дрон",
                "пострадав",
                "ранен",
                "госпитал",
                "погиб",
                "дет",
                "президент",
                "помощ",
                "украин",
                "благотвор",
                "цитат",
                "турнир",
                "побед",
                "игр",
                "компан",
                "закры",
                "разработ",
                "сервер",
            )
        ):

            if token not in categories:

                categories.append(
                    token
                )

    fallback = important_tokens(
        cleaned,
        8,
    )

    parts = []

    for item in (
        names
        + categories[:7]
        + nums[:8]
        + fallback[:5]
    ):

        if item not in parts:

            parts.append(
                item
            )

    if (
        update_mode
        and source_date_value
    ):

        parts.append(
            source_date_value
        )

    return short_query(
        " ".join(
            parts
        ),
        280,
    )


def build_search_plan(
    news_text,
    source_date_value,
):

    cleaned = clean_search_text(
        news_text
    )

    update_mode = is_fast_update(
        cleaned
    )

    foreign = looks_foreign(
        cleaned
    )

    first = build_precision_query(
        cleaned,
        source_date_value,
        update_mode,
    )

    second = build_second_query(
        cleaned,
        source_date_value,
        update_mode,
    )

    queries = []
    seen = set()

    for (
        q,
        kind,
    ) in (
        (
            first,
            (
                "latest_update"
                if update_mode
                else "precision"
            ),
        ),

        (
            second,
            "alternative",
        ),
    ):

        q = short_query(
            q,
            280,
        )

        if (
            not q
            or q.lower()
            in seen
        ):

            continue

        seen.add(
            q.lower()
        )

        queries.append({
            "q":
                q,

            "kind":
                kind,
        })

        if len(
            queries
        ) >= MAX_PRIMARY_SEARCHES:

            break

    return {
        "cleaned_news":
            cleaned,

        "foreign_subject":
            foreign,

        "update_mode":
            update_mode,

        "queries":
            queries,
    }


# =========================================================
# SOURCE PRIORITY
# =========================================================

def source_priority(url):

    d = domain(
        url
    )

    official = (
        "government.ru",
        "kremlin.ru",
        "pravo.gov.ru",
        "sledcom.ru",
        "genproc.gov.ru",
        "epp.genproc.gov.ru",
        "мвд.рф",
        "xn--b1aew.xn--p1ai",

        "presidentti.fi",
        "valtioneuvosto.fi",

        "europa.eu",
        "consilium.europa.eu",

        "who.int",
        "un.org",
        "nato.int",

        "whitehouse.gov",
        "state.gov",
        "defense.gov",

        "president.gov.ua",
    )

    trusted = (
        "reuters.com",
        "apnews.com",
        "afp.com",

        "bbc.com",
        "bbc.co.uk",

        "tass.ru",
        "interfax.ru",

        "yle.fi",
        "err.ee",

        "brookings.edu",

        "riotgames.com",

        "hltv.org",
        "liquipedia.net",

        "teamspirit.gg",
        "esportsworldcup.com",
    )

    if any(
        (
            d == x
            or d.endswith(
                "." + x
            )
        )

        for x
        in official
    ):

        return 0

    if (
        ".gov" in d

        or d.startswith(
            (
                "president.",
                "government.",
                "court.",
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
        in trusted
    ):

        return 1

    return 2


# =========================================================
# TAVILY SEARCH
# =========================================================

def tavily_search(
    query,
    query_index,
    kind,
):

    q = short_query(
        query,
        320,
    )

    def do_request(value):

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
                    value,

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

    response = do_request(
        q
    )

    if (
        response.status_code
        == 400
    ):

        response = do_request(
            short_query(
                q,
                240,
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

            "query_kind":
                kind,
        })

    return out


# =========================================================
# RETRIEVAL SCORE
# =========================================================

def relevance(
    item,
    query,
):

    text = norm(
        (
            f"{item.get('title', '')} "
            f"{item.get('content', '')}"
        )
    ).lower()

    tokens = [
        x.lower()

        for x in important_tokens(
            query,
            10,
        )
    ]

    hits = sum(
        1

        for x
        in tokens

        if x in text
    )

    if tokens:

        token_score = (
            100
            * hits
            / max(
                3,
                len(
                    tokens
                ),
            )
        )

    else:

        token_score = 0

    nums = extract_numbers(
        query
    )

    num_hits = sum(
        1

        for x
        in nums

        if (
            x.replace(
                ",",
                ".",
            ).lower()

            in text.replace(
                ",",
                ".",
            )
        )
    )

    if nums:

        num_score = (
            22
            * num_hits
            / len(
                nums
            )
        )

    else:

        num_score = 0

    bonus = {
        0:
            8,

        1:
            5,
    }.get(
        source_priority(
            item[
                "url"
            ]
        ),
        0,
    )

    return min(
        100,

        round(
            (
                token_score
                * 0.72

                + num_score

                + min(
                    15,

                    item.get(
                        "tavily_score",
                        0,
                    )
                    * 15,
                )

                + bonus
            ),
            1,
        ),
    )


def merge_results(
    old,
    new,
    query,
):

    by_url = {
        x[
            "url"
        ].lower():
            x

        for x
        in old
    }

    for item in new:

        item[
            "retrieval_score"
        ] = relevance(
            item,
            query,
        )

        key = item[
            "url"
        ].lower()

        if (
            key not in by_url

            or item[
                "retrieval_score"
            ]
            > by_url[
                key
            ].get(
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


def ranked(results):

    return sorted(
        results,

        key=lambda x: (
            -float(
                x.get(
                    "retrieval_score",
                    0,
                )
            ),

            source_priority(
                x.get(
                    "url",
                    "",
                )
            ),

            -float(
                x.get(
                    "tavily_score",
                    0,
                )
            ),
        ),
    )


def strong_enough(results):

    items = ranked(
        results
    )

    if not items:

        return False

    top = items[
        0
    ]

    score = float(
        top.get(
            "retrieval_score",
            0,
        )
    )

    if (
        source_priority(
            top[
                "url"
            ]
        )
        <= 1
    ):

        return (
            score
            >= EARLY_STOP_TRUSTED_SCORE
        )

    return (
        score
        >= EARLY_STOP_OTHER_SCORE
    )


def weak_results(results):

    items = ranked(
        results
    )

    if not items:

        return True

    return (
        float(
            items[
                0
            ].get(
                "retrieval_score",
                0,
            )
        )
        < FINAL_WEAK_SCORE
    )


# =========================================================
# OPTIONAL THIRD QUERY
# =========================================================

def build_foreign_query_with_groq(
    news_text,
    source_date_value,
    used_queries,
):

    previous = "\n".join(
        (
            "- "
            + x[
                "q"
            ]
        )

        for x
        in used_queries
    )

    prompt = f"""
Нужен ОДИН английский поисковый запрос
для проверки иностранной новости/цитаты.

{date_context(source_date_value)}

Два обычных поиска
уже дали слабую выдачу.

Старые запросы:

{previous}

Правила:

- верни только JSON;
- один запрос;
- имя/организацию пиши на языке оригинала;
- передай СМЫСЛ цитаты или утверждения;
- используй естественные английские синонимы;
- не делай буквальный машинный перевод;
- не используй FTT, Telegram-канал, подписаться;
- не придумывай место выступления;
- без кавычек;
- до 250 символов.

Пример для Стубба:

Alexander Stubb Ukraine support altruism Europe needs Ukraine learn from Ukraine

JSON:

{{"q":"..."}}

Новость:

{clean_search_text(news_text)[:3000]}
""".strip()

    data = parse_json(
        groq_text(
            (
                "Ты создаёшь один точный "
                "original-language веб-запрос."
            ),

            prompt,

            max_tokens=130,

            temperature=0.0,
        )
    )

    q = norm(
        (
            data.get(
                "q"
            )
            or ""
        )
        .replace(
            '"',
            " ",
        )
        .replace(
            "«",
            " ",
        )
        .replace(
            "»",
            " ",
        )
    )

    q = short_query(
        q,
        250,
    )

    if not q:

        return None

    old = {
        x[
            "q"
        ].lower()

        for x
        in used_queries
    }

    if q.lower() in old:

        return None

    return {
        "q":
            q,

        "kind":
            "original_language_fallback",
    }


def build_deterministic_third_query(
    cleaned,
    source_date_value,
    update_mode,
    used_queries,
):

    names = extract_capitalized_tokens(
        cleaned,
        6,
    )

    nums = extract_numbers(
        cleaned
    )

    tokens = important_tokens(
        cleaned,
        14,
    )

    parts = (
        names
        + nums
        + tokens[
            5:14
        ]
    )

    if (
        update_mode
        and source_date_value
    ):

        parts.append(
            source_date_value
        )

    q = short_query(
        " ".join(
            dict.fromkeys(
                parts
            )
        ),
        280,
    )

    old = {
        x[
            "q"
        ].lower()

        for x
        in used_queries
    }

    if (
        not q
        or q.lower()
        in old
    ):

        return None

    return {
        "q":
            q,

        "kind":
            "deterministic_fallback",
    }


# =========================================================
# SEARCH BUDGET
# =========================================================

def search_with_budget(
    news_text,
    source_date_value,
    plan,
):

    results = []
    used_plan = []
    searches = 0

    for item in plan[
        "queries"
    ]:

        idx = len(
            used_plan
        )

        print(
            (
                f"Tavily search "
                f"{searches + 1}/"
                f"{MAX_TOTAL_SEARCHES}: "
                f"{item['kind']}: "
                f"{item['q']}"
            ),
            flush=True,
        )

        try:

            fresh = tavily_search(
                item[
                    "q"
                ],
                idx,
                item[
                    "kind"
                ],
            )

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
                    f"{exc}"
                ),
                flush=True,
            )

            fresh = []

        used_plan.append(
            item
        )

        searches += 1

        results = merge_results(
            results,
            fresh,
            item[
                "q"
            ],
        )

        if strong_enough(
            results
        ):

            print(
                (
                    "Search early-stop: "
                    "strong result found."
                ),
                flush=True,
            )

            break

    if (
        searches
        < MAX_TOTAL_SEARCHES

        and weak_results(
            results
        )
    ):

        third = None

        if plan[
            "foreign_subject"
        ]:

            try:

                print(
                    (
                        "Foreign weak retrieval: "
                        "using 1 Groq fallback query"
                    ),
                    flush=True,
                )

                third = build_foreign_query_with_groq(
                    news_text,
                    source_date_value,
                    used_plan,
                )

            except RuntimeError as exc:

                if (
                    "GROQ_429"
                    in str(
                        exc
                    )
                ):

                    print(
                        (
                            "Foreign fallback skipped: "
                            "GROQ_429"
                        ),
                        flush=True,
                    )

                    third = None

                else:

                    raise

        else:

            third = build_deterministic_third_query(
                plan[
                    "cleaned_news"
                ],
                source_date_value,
                plan[
                    "update_mode"
                ],
                used_plan,
            )

        if third:

            idx = len(
                used_plan
            )

            print(
                (
                    f"Tavily search "
                    f"{searches + 1}/"
                    f"{MAX_TOTAL_SEARCHES}: "
                    f"{third['kind']}: "
                    f"{third['q']}"
                ),
                flush=True,
            )

            fresh = tavily_search(
                third[
                    "q"
                ],
                idx,
                third[
                    "kind"
                ],
            )

            used_plan.append(
                third
            )

            searches += 1

            results = merge_results(
                results,
                fresh,
                third[
                    "q"
                ],
            )

    print(
        (
            f"Search budget used: "
            f"{searches}/"
            f"{MAX_TOTAL_SEARCHES}"
        ),
        flush=True,
    )

    return (
        results,
        used_plan,
    )


# =========================================================
# TAVILY EXTRACT
# =========================================================

def tavily_extract(urls):

    clean = []
    seen = set()

    for url in urls:

        url = clean_url(
            url
        )

        if (
            not url
            or url.lower()
            in seen
        ):

            continue

        seen.add(
            url.lower()
        )

        clean.append(
            url
        )

        if len(
            clean
        ) >= MAX_EXTRACT_URLS:

            break

    if not clean:

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
                    clean,

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

    except Exception as exc:

        print(
            (
                "Tavily Extract warning: "
                f"{exc}"
            ),
            flush=True,
        )

        return {}


def add_original_url(
    news_text,
    results,
):

    urls = URL_RE.findall(
        news_text
    )

    if not urls:

        return results

    url = clean_url(
        urls[
            0
        ]
    )

    if any(
        x[
            "url"
        ].lower()
        == url.lower()

        for x
        in results
    ):

        return results

    return [
        {
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

            "query_kind":
                "original",
        }
    ] + results


def select_sources(
    results,
    limit,
):

    items = ranked(
        results
    )

    selected = []
    seen_urls = set()
    seen_domains = set()

    for item in items:

        if (
            item.get(
                "query_kind"
            )
            == "original"
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
                domain(
                    item[
                        "url"
                    ]
                )
            )

            break

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

        d = domain(
            item[
                "url"
            ]
        )

        if (
            d in seen_domains

            and len(
                items
            ) > limit
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


def enrich_sources(results):

    selected = select_sources(
        results,
        MAX_EXTRACT_URLS,
    )

    extracted = tavily_extract(
        [
            x[
                "url"
            ]

            for x
            in selected
        ]
    )

    for item in results:

        content = extracted.get(
            item[
                "url"
            ].lower()
        )

        if content:

            item[
                "raw_content"
            ] = content

    return results


# =========================================================
# FINAL ANALYSIS — 1 GROQ
# =========================================================

def analyze(
    news_text,
    source_date_value,
    used_plan,
    results,
    update_mode,
):

    sources = select_sources(
        results,
        MAX_AI_SOURCES,
    )

    blocks = []
    total_chars = 0

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
                    :MAX_EXTRACT_CHARS_PER_SOURCE
                ]
            )

        else:

            evidence = (
                "СНИППЕТ:\n"
                + norm(
                    item.get(
                        "content"
                    )
                    or ""
                )[
                    :MAX_SEARCH_SNIPPET_CHARS
                ]
            )

        block = (
            f"[{index}]\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{domain(item['url'])}\n"
            f"Дата: "
            f"{item.get('published_date') or 'неизвестна'}\n"
            f"Retrieval score: "
            f"{item.get('retrieval_score', 0)}\n"
            f"{evidence}"
        )

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

    source_text = "\n\n".join(
        blocks
    )

    query_text = "\n".join(
        (
            f"- [{x['kind']}] "
            f"{x['q']}"
        )

        for x
        in used_plan
    )

    prompt = f"""
{date_context(source_date_value)}

Быстро обновляющаяся новость:
{"ДА" if update_mode else "НЕТ"}.

НОВОСТЬ:

{news_text[:4000]}

КАК ИСКАЛИ:

{query_text}

ИСТОЧНИКИ:

{source_text}

Сделай финальный фактчек.

Критично:

- суди по содержанию источников;

- старый меньший показатель
не опровергает свежий апдейт;

- не смешивай погибших,
пострадавших,
раненых
и госпитализированных;

- иностранную цитату
сравнивай по смыслу;

- отсутствие детали
не равно опровержению;

- если свежий апдейт не найден,
но старые цифры подтверждаются,
лучше ⚪,
а не 🟡/🔴.

После:

Уверенность: N/10

напиши:

USED: 1,2
""".strip()

    answer = groq_text(
        SYSTEM_PROMPT,
        prompt,

        max_tokens=520,

        temperature=0.03,
    )

    if not answer:

        raise RuntimeError(
            "Groq вернул пустой ответ"
        )

    match = re.search(
        (
            r"(?im)^\s*"
            r"USED\s*:\s*"
            r"([0-9,\s]+)"
            r"\s*$"
        ),
        answer,
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

            number = int(
                raw
            )

            if (
                1 <= number
                <= len(
                    sources
                )
            ):

                item = sources[
                    number - 1
                ]

                if item not in used:

                    used.append(
                        item
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
                len(
                    sources
                ),
            )
        ]

    return (
        answer[
            :3900
        ],
        used,
    )


# =========================================================
# BUTTONS
# =========================================================

SOURCE_NAMES = {
    "reuters.com":
        "Reuters",

    "apnews.com":
        "AP",

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

    "riotgames.com":
        "Riot Games",

    "hltv.org":
        "HLTV",

    "liquipedia.net":
        "Liquipedia",

    "teamspirit.gg":
        "Team Spirit",
}


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

        d = domain(
            url
        )

        name = (
            SOURCE_NAMES.get(
                d
            )

            or norm(
                item.get(
                    "title"
                )
                or d
            )
        )

        if len(
            name
        ) > 27:

            name = (
                name[
                    :26
                ].rstrip()
                + "…"
            )

        buttons.append({
            "text":
                f"{index} · {name}",

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
                len(
                    buttons
                ),
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

    cached = cache_get(
        news_text,
        source_date_value,
    )

    if cached:

        return cached

    plan = build_search_plan(
        news_text,
        source_date_value,
    )

    print(
        (
            "V8 deterministic queries: "
            + " || ".join(
                (
                    f"{x['kind']}:"
                    f"{x['q']}"
                )

                for x
                in plan[
                    "queries"
                ]
            )
        ),
        flush=True,
    )

    print(
        (
            "V8 foreign_subject="
            f"{plan['foreign_subject']}; "
            "update_mode="
            f"{plan['update_mode']}"
        ),
        flush=True,
    )

    if not plan[
        "queries"
    ]:

        return (
            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
                "Не получилось построить "
                "нормальный поиск.\n"
                "Уверенность: 1/10"
            ),
            [],
        )

    results, used_plan = search_with_budget(
        news_text,
        source_date_value,
        plan,
    )

    results = [
        item

        for item
        in ranked(
            results
        )

        if (
            item.get(
                "retrieval_score",
                0,
            )
            >= 18

            or source_priority(
                item[
                    "url"
                ]
            )
            <= 1
        )
    ]

    results = add_original_url(
        news_text,
        results,
    )

    if not results:

        answer = (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Поиск не нашёл достаточно "
            "точных источников. "
            "Это не доказательство лжи.\n"
            "Уверенность: 2/10"
        )

        cache_put(
            news_text,
            source_date_value,
            answer,
            [],
        )

        return (
            answer,
            [],
        )

    results = enrich_sources(
        results
    )

    answer, used = analyze(
        news_text,
        source_date_value,
        used_plan,
        results,
        plan[
            "update_mode"
        ],
    )

    cache_put(
        news_text,
        source_date_value,
        answer,
        used,
    )

    return (
        answer,
        used,
    )


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
            "В V8 он используется намного реже. "
            "Попробуй чуть позже."
        )

    if "GROQ_413" in text:

        return (
            "Для Groq запрос "
            "слишком большой."
        )

    if "GROQ_400" in text:

        return (
            "Groq отклонил запрос. "
            "Глянь лог Railway."
        )

    return (
        "Чёт фактчек наебнулся. "
        "Ошибка есть в Railway."
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
                "Кидай новость/ссылку/"
                "пересланный пост — "
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
                "Это не новость 😄 "
                "Я фактчекаю посты, "
                "ссылки и новостные тексты."
            ),

            message_id,
        )

        return

    # ЛИЧКА:
    # проверяем сразу,
    # без слова "Проверь".

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
            "private_auto_check",
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
        }

    # КОЛЯ —
    # только в группе.

    if (
        request_data is None

        and chat_type
        in {
            "group",
            "supergroup",
        }

        and is_nikolai(
            user
        )

        and looks_like_news(
            message
        )
    ):

        if media_done(
            message,
            "kolya",
        ):

            return

        send_message(
            chat_id,
            kolya_roast(),
            message_id,
        )

        return

    # AUTO CHECK GROUP

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

    date = (
        request_data.get(
            "source_date"
        )
        or ""
    )

    status = send_message(
        chat_id,
        "🔎 Ща пробью источники…",
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

        answer, used = factcheck(
            news_text,
            date,
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

        text = friendly_error(
            exc
        )

        if status_id:

            try:

                edit_message(
                    chat_id,
                    status_id,
                    text,
                )

                return

            except Exception:

                pass

        send_message(
            chat_id,
            text,
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
            "Chicken Company bot V8 started; "
            "groq_search_planning=OFF; "
            "groq_normal_check=1_call; "
            "foreign_weak_check=max_2_calls; "
            "search_budget=1->2->optional3; "
            "cache=6h; "
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

                uid = update.get(
                    "update_id"
                )

                if isinstance(
                    uid,
                    int,
                ):

                    offset = (
                        uid
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

            code = (
                exc.response.status_code

                if exc.response is not None

                else None
            )

            if code == 409:

                print(
                    (
                        "Telegram 409: "
                        "оставь только "
                        "1 worker/replica."
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
                    f"{exc}"
                ),
                flush=True,
            )

            time.sleep(
                5
            )


if __name__ == "__main__":
    main()