import os
import re
import time
import json
import hashlib
import base64
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
VISION_MODEL = os.getenv("VISION_MODEL", "qwen/qwen3.6-27b").strip()

AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {
    "1", "true", "yes", "on"
}
TZ_HOURS = int(os.getenv("RELATIVE_DATE_TZ_OFFSET_HOURS", "3"))

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"

MAX_PRIMARY_SEARCHES = 2
MAX_TOTAL_SEARCHES = 3
MAX_RESULTS_PER_QUERY = 6
MAX_EXTRACT_URLS = 3
MAX_AI_SOURCES = 5
MAX_TG_SOURCES = 5
MAX_EXTRACT_CHARS = 1500
MAX_SNIPPET_CHARS = 650
MAX_TOTAL_SOURCE_CHARS = 8000
MAX_OCR_CHARS = 2800

EARLY_STOP_TRUSTED_SCORE = 58
EARLY_STOP_OTHER_SCORE = 72
WEAK_SCORE = 48

CACHE_TTL = 6 * 60 * 60
CACHE_MAX_ITEMS = 300
MEDIA_GROUP_TTL = 3600

FACTCHECK_CACHE = {}
MEDIA_GROUP_TEXT_CACHE = {}
RECENT_MEDIA_ACTIONS = {}


# =========================================================
# REGEX / DICTIONARIES
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

DOCUMENT_RE = re.compile(
    r"\b(?:"
    r"указ|"
    r"указа|"
    r"постановлен\w*|"
    r"распоряжен\w*|"
    r"федеральн\w+\s+закон\w*|"
    r"закон\w*|"
    r"приказ\w*|"
    r"официальн\w+\s+документ\w*"
    r")\b",
    re.I,
)

MODEL_RE = re.compile(
    r"\b(?:"
    r"[A-ZА-ЯЁ]{1,6}\s*[- ]?\d{1,4}[A-Za-zА-Яа-яЁё]?|"
    r"[A-Z][A-Za-z]{2,}\s+[A-Z]{0,3}\d{1,4}[A-Za-z]?"
    r")\b"
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

SOURCE_HINTS = {
    "the new york times": "nytimes.com",
    "new york times": "nytimes.com",
    "nyt": "nytimes.com",
    "reuters": "reuters.com",
    "bbc": "bbc.com",
    "bloomberg": "bloomberg.com",
    "wall street journal": "wsj.com",
    "wsj": "wsj.com",
    "associated press": "apnews.com",
    "financial times": "ft.com",
    "the guardian": "theguardian.com",
    "guardian": "theguardian.com",
    "cnn": "cnn.com",
    "tass": "tass.ru",
    "тасс": "tass.ru",
    "интерфакс": "interfax.ru",
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
    "new york times",
    "reuters",
    "bbc",
)


# =========================================================
# FINAL PROMPT
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер Telegram-новостей.

ОБЯЗАТЕЛЬНО отвечай пользователю только на русском языке,
даже если все источники и цитаты на английском.

Работай только по переданным источникам.
Ничего не выдумывай.

Правила:

1. Мысленно разбивай составную новость
на отдельные проверяемые факты.

Не показывай C1/C2/C3.

2. Разные части новости
могут подтверждаться
разными источниками.

3. «Не найдено подтверждение»
НЕ означает
«доказано, что это ложь».

4. 🔴 ПИЗДЁЖ
ставь только если
центральный факт
прямо и надёжно опровергнут.

5. 🟡 ПОЛУПИЗДЁЖ —
событие реально,
но существенная часть
действительно неверна.

Отсутствие детали
в источнике
не является опровержением.

6. 🟠 НАЕБАЛИ С КОНТЕКСТОМ —
факты реальные,
но дата,
контекст
или подача
создают ложное впечатление.

7. ⚪ ХУЙ ПОЙМЁШЬ ПОКА —
данных недостаточно,
источники слабые
или нельзя уверенно
сопоставить объекты.

8. Не смешивай
похожие события.

Сверяй:

людей,
место,
объект,
дату,
цифры,
обстоятельства.

9. «Огонь не дошёл
до Сафари-парка»

не означает:

«пожара рядом
с Сафари-парком
не было».

10. Быстро обновляющиеся новости:

старый источник
с меньшей цифрой

НЕ опровергает
более поздний апдейт.

11. Никогда не смешивай:

пострадавших,
раненых,
госпитализированных,
погибших,
погибших детей,
детей среди раненых,
детей среди госпитализированных.

12. Иностранные цитаты
сравнивай по смыслу
и контексту,

а не по буквальному
русскому переводу.

13. Если в новости
назван первоисточник:

NYT,
Reuters,
BBC,
Bloomberg,
WSJ,
AP
и т.п.,

его материал
имеет приоритет
над пересказами.

Пересказы можно использовать
как дополнительное подтверждение.

14. Для моделей автомобилей,
устройств,
игр
и товаров

сначала определи
ГЛАВНЫЙ объект новости.

Фразы:

«как Porsche»,
«убийца Tesla»,
«по цене Lada»

и подобные —

это сравнение,

а не автоматически
главный объект.

15. Перед опровержением
характеристик товара
или автомобиля

убедись,
что совпадают:

модель,
версия,
комплектация,
рынок,
дата,
метод измерения.

Если это не установлено —

не ставь 🔴.

16. Документы:

перед выводом
сопоставь:

дату,
номер,
название,
орган,
содержание.

Старый указ
или закон
на похожую тему

НЕ опровергает
новый документ.

Если найден
только похожий
старый документ —

это не основание
для 🔴 или 🟡.

17. Извлечённый текст страницы
сильнее
поискового сниппета.

18. Локальное
официальное ведомство
или региональное СМИ

могут быть
лучшим источником
для локального события.

19. Если уверенность
ниже 7/10 —

НЕ ставь
🔴 ПИЗДЁЖ.

При недостатке доказательств
используй ⚪.


Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА


Формат:

Первая строка —
только один вердикт.

Далее 2–4
коротких предложения

ТОЛЬКО НА РУССКОМ.

Последняя видимая строка:

Уверенность: N/10

После неё
техническая строка:

USED: 1,2

URL в текст
не вставляй.
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

    return "\n".join(
        line

        for line in (
            re.sub(
                r"[ \t]+",
                " ",
                x,
            ).strip()

            for x
            in text.split(
                "\n"
            )
        )

        if line
    )


def msg_text(message):

    return (
        message.get(
            "text"
        )
        or message.get(
            "caption"
        )
        or ""
    ).strip()


def clean_url(url):

    return (
        (
            url
            or ""
        )
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
    limit=300,
):

    text = norm(
        text
    )

    if len(
        text
    ) <= limit:

        return text

    cut = text[
        :limit
    ]

    pos = cut.rfind(
        " "
    )

    if pos > int(
        limit * 0.6
    ):

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

    for raw in work.splitlines():

        line = norm(
            raw
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

    return (
        norm(
            " ".join(
                out
            )
        )
        or norm(
            original
        )
    )


def important_tokens(
    text,
    limit=14,
):

    out = []
    seen = set()

    for token in re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{3,}"
        ),
        text
        or "",
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

        out.append(
            token
        )

        if len(
            out
        ) >= limit:

            break

    return out


def extract_numbers(text):

    values = re.findall(
        (
            r"\b\d{1,2}:\d{2}\b|"
            r"\b\d+(?:[.,]\d+)?\s*"
            r"(?:"
            r"га|"
            r"км|"
            r"м|"
            r"%|"
            r"млн|"
            r"млрд|"
            r"руб(?:лей)?|"
            r"юан(?:ей)?|"
            r"км/ч"
            r")?"
            r"\b"
        ),
        text
        or "",
        re.I,
    )

    out = []

    for item in values:

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

    return out[
        :12
    ]


def extract_capitalized(
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
        text
        or "",
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
            "сегодня",
            "ранее",
            "число",
            "информация",
            "запад",
            "после",
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


def model_candidates(text):

    out = []

    for match in MODEL_RE.findall(
        text
        or ""
    ):

        value = norm(
            match
        )

        if (
            value
            and value not in out
        ):

            out.append(
                value
            )

    return out


def detect_primary_subject(text):

    models = model_candidates(
        text
    )

    if models:

        return models[
            0
        ]

    caps = extract_capitalized(
        text,
        4,
    )

    return " ".join(
        caps[
            :3
        ]
    )


def remove_comparison_noise(
    text,
    primary_subject,
):

    cleaned = (
        text
        or ""
    )

    patterns = (
        (
            r"(?i)\bкак\s+"
            r"(?:у\s+)?"
            r"[A-ZА-ЯЁ]"
            r"[^,.;]{1,45}"
        ),

        (
            r"(?i)\b"
            r"убийц[аы]\s+"
            r"[A-ZА-ЯЁ]"
            r"[^,.;]{1,45}"
        ),

        (
            r"(?i)\b"
            r"по цене\s+"
            r"[A-ZА-ЯЁ]"
            r"[^,.;]{1,45}"
        ),

        (
            r"(?i)\b"
            r"конкурент\s+"
            r"[A-ZА-ЯЁ]"
            r"[^,.;]{1,45}"
        ),
    )

    for pattern in patterns:

        cleaned = re.sub(
            pattern,
            " ",
            cleaned,
        )

    for candidate in model_candidates(
        cleaned
    )[
        1:
    ]:

        if (
            candidate.lower()
            != (
                primary_subject
                or ""
            ).lower()
        ):

            cleaned = re.sub(
                re.escape(
                    candidate
                ),
                " ",
                cleaned,
                flags=re.I,
            )

    return norm(
        cleaned
    )


def is_fast_update(text):

    return bool(
        UPDATE_RE.search(
            text
            or ""
        )
    )


def is_document_news(text):

    return bool(
        DOCUMENT_RE.search(
            text
            or ""
        )
    )


def document_markers(text):

    nums = re.findall(
        (
            r"(?:"
            r"№\s*"
            r"[A-Za-zА-Яа-я0-9\-\/]+|"
            r"\b\d{2,5}\b"
            r")"
        ),
        text
        or "",
        re.I,
    )

    dates = re.findall(
        (
            r"\b"
            r"\d{1,2}[./-]"
            r"\d{1,2}[./-]"
            r"\d{2,4}"
            r"\b"
        ),
        text
        or "",
    )

    out = []

    for item in (
        nums
        + dates
    ):

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

    return out[
        :8
    ]


def detect_source_hint(text):

    low = (
        text
        or ""
    ).lower()

    for url in URL_RE.findall(
        text
        or ""
    ):

        d = domain(
            clean_url(
                url
            )
        )

        if d:

            for known in set(
                SOURCE_HINTS.values()
            ):

                if (
                    d == known
                    or d.endswith(
                        "."
                        + known
                    )
                ):

                    return known

    for (
        marker,
        source,
    ) in SOURCE_HINTS.items():

        if marker in low:

            return source

    return ""


def looks_foreign(text):

    low = (
        text
        or ""
    ).lower()

    if any(
        x in low

        for x in FOREIGN_MARKERS
    ):

        return True

    latin = re.findall(
        (
            r"\b"
            r"[A-Za-z]"
            r"[A-Za-z\-]{3,}"
            r"\b"
        ),
        text
        or "",
    )

    return (
        len(
            latin
        ) >= 2
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


def cleanup_cache():

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
            > CACHE_TTL
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

    cleanup_cache()

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
        > CACHE_TTL
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

    cleanup_cache()

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
            "Слова «сегодня/вчера/этой ночью» "
            "считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна. "
        "Не подставляй текущую дату сервера "
        "вместо «сегодня/вчера»."
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
                ][
                    "ts"
                ]
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
        )
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
                    word
                    + " "
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

        "_source_message":
            message,
    }


# =========================================================
# GROQ
# =========================================================

def groq_text(
    system_text,
    user_text,
    max_tokens=600,
    temperature=0.03,
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

            if attempt == 2:

                raise RuntimeError(
                    "GROQ_429"
                )

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

                wait = 15

            print(
                (
                    "Groq 429. "
                    f"Waiting {wait}s"
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
                    + response.text[
                        :500
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
            str
        ):

            return content.strip()

        return ""

    return ""


# =========================================================
# DOCUMENT OCR
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

    if not image_bytes:

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
                                    "Распознай текст документа "
                                    "на изображении. "
                                    "Особенно точно выпиши "
                                    "номер, дату, название, "
                                    "орган, фамилии и ключевую "
                                    "формулировку. "
                                    "Верни только распознанный "
                                    "текст без анализа."
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

    if (
        response.status_code
        == 429
    ):

        print(
            "OCR skipped: GROQ_429",
            flush=True,
        )

        return ""

    if (
        response.status_code
        == 401
    ):

        print(
            "OCR skipped: GROQ_401",
            flush=True,
        )

        return ""

    if (
        response.status_code
        == 400
    ):

        print(
            (
                "OCR skipped: "
                + response.text[
                    :300
                ]
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
        str
    ):

        return norm(
            content
        )[
            :MAX_OCR_CHARS
        ]

    return ""


def maybe_ocr_document(
    message,
    news_text,
):

    if not is_document_news(
        news_text
    ):

        return ""

    if not best_photo_file_id(
        message
    ):

        return ""

    try:

        print(
            (
                "Document photo detected. "
                "OCR..."
            ),
            flush=True,
        )

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

def build_query_material(cleaned):

    subject = detect_primary_subject(
        cleaned
    )

    query_text = remove_comparison_noise(
        cleaned,
        subject,
    )

    return (
        subject,
        query_text,
    )


def build_search_plan(
    news_text,
    source_date_value,
):

    cleaned = clean_search_text(
        news_text
    )

    (
        subject,
        query_text,
    ) = build_query_material(
        cleaned
    )

    update_mode = is_fast_update(
        cleaned
    )

    document_mode = is_document_news(
        cleaned
    )

    foreign = looks_foreign(
        cleaned
    )

    source_hint = detect_source_hint(
        news_text
    )

    nums = extract_numbers(
        query_text
    )

    tokens = important_tokens(
        query_text,
        12,
    )

    if document_mode:

        doc_marks = document_markers(
            cleaned
        )

    else:

        doc_marks = []

    base_parts = []

    for item in (
        [
            subject
        ]
        + doc_marks
        + tokens[
            :9
        ]
        + nums[
            :8
        ]
    ):

        item = norm(
            item
        )

        if not item:

            continue

        if item.lower() not in {
            x.lower()
            for x in base_parts
        }:

            base_parts.append(
                item
            )

    if (
        update_mode
        and source_date_value
    ):

        base_parts.append(
            source_date_value
        )

    base_query = short_query(
        " ".join(
            base_parts
        ),
        290,
    )

    queries = []
    seen = set()

    def add(
        q,
        kind,
    ):

        q = short_query(
            q,
            300,
        )

        if (
            not q
            or q.lower()
            in seen
        ):

            return

        seen.add(
            q.lower()
        )

        queries.append({
            "q":
                q,

            "kind":
                kind,
        })

    if source_hint:

        add(
            (
                f"site:{source_hint} "
                f"{base_query}"
            ),
            "claimed_primary_source",
        )

    add(
        base_query,

        (
            "document_exact"

            if document_mode

            else (
                "latest_update"

                if update_mode

                else "precision"
            )
        ),
    )

    alt_parts = (
        [
            subject
        ]
        + nums[
            :8
        ]
        + tokens[
            3:10
        ]
    )

    alt_query = short_query(
        " ".join(
            dict.fromkeys(
                x

                for x
                in alt_parts

                if x
            )
        ),
        280,
    )

    add(
        alt_query,
        "alternative",
    )

    return {
        "cleaned_news":
            cleaned,

        "primary_subject":
            subject,

        "source_hint":
            source_hint,

        "foreign_subject":
            foreign,

        "update_mode":
            update_mode,

        "document_mode":
            document_mode,

        "queries":
            queries[
                :MAX_PRIMARY_SEARCHES
            ],
    }


# =========================================================
# SOURCE PRIORITY
# =========================================================

def source_priority(
    url,
    claimed_domain="",
):

    d = domain(
        url
    )

    if (
        claimed_domain

        and (
            d == claimed_domain
            or d.endswith(
                "."
                + claimed_domain
            )
        )
    ):

        return -1

    official = (
        "government.ru",
        "kremlin.ru",
        "pravo.gov.ru",
        "publication.pravo.gov.ru",
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

        "nytimes.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",

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
                "."
                + x
            )
        )

        for x
        in official
    ):

        return 0

    if (
        ".gov"
        in d

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
                "."
                + x
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

    if (
        response.status_code
        == 400
    ):

        response = request(
            short_query(
                query,
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
                + response.text[
                    :300
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
    claimed_domain="",
):

    haystack = norm(
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

        for x in tokens

        if x in haystack
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

    normalized_haystack = (
        haystack.replace(
            ",",
            ".",
        )
    )

    num_hits = sum(
        1

        for x in nums

        if (
            x.lower()
            .replace(
                ",",
                ".",
            )
            in normalized_haystack
        )
    )

    if nums:

        num_score = (
            24
            * num_hits
            / len(
                nums
            )
        )

    else:

        num_score = 0

    priority = source_priority(
        item[
            "url"
        ],
        claimed_domain,
    )

    bonus = {
        -1:
            14,

        0:
            9,

        1:
            5,
    }.get(
        priority,
        0,
    )

    return min(
        100,

        round(
            (
                token_score
                * 0.70

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
    claimed_domain="",
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
            claimed_domain,
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


def ranked(
    results,
    claimed_domain="",
):

    return sorted(
        results,

        key=lambda x: (
            source_priority(
                x.get(
                    "url",
                    "",
                ),
                claimed_domain,
            ),

            -float(
                x.get(
                    "retrieval_score",
                    0,
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


def strong_enough(
    results,
    claimed_domain="",
):

    if not results:

        return False

    if claimed_domain:

        for item in results:

            d = domain(
                item[
                    "url"
                ]
            )

            if (
                (
                    d == claimed_domain

                    or d.endswith(
                        "."
                        + claimed_domain
                    )
                )

                and item.get(
                    "retrieval_score",
                    0,
                ) >= 45
            ):

                return True

    best = max(
        results,

        key=lambda x:
            float(
                x.get(
                    "retrieval_score",
                    0,
                )
            ),
    )

    score = float(
        best.get(
            "retrieval_score",
            0,
        )
    )

    priority = source_priority(
        best[
            "url"
        ],
        claimed_domain,
    )

    if priority <= 1:

        return (
            score
            >= EARLY_STOP_TRUSTED_SCORE
        )

    return (
        score
        >= EARLY_STOP_OTHER_SCORE
    )


def weak_results(results):

    if not results:

        return True

    top = max(
        float(
            x.get(
                "retrieval_score",
                0,
            )
        )

        for x
        in results
    )

    return (
        top
        < WEAK_SCORE
    )


# =========================================================
# OPTIONAL THIRD SEARCH
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
для проверки иностранной новости или цитаты.

{date_context(source_date_value)}

Два обычных поиска
уже дали слабую выдачу.

Старые запросы:

{previous}

Правила:

- верни только JSON вида {{"q":"..."}};
- имя и организацию пиши на языке оригинала;
- передай смысл утверждения естественными английскими словами;
- используй синонимы;
- не используй FTT и Telegram-подпись;
- не придумывай место выступления;
- без кавычек;
- до 250 символов.

Пример:

Alexander Stubb Ukraine support altruism Europe needs Ukraine learn from Ukraine

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
            "original_language_fallback",
    }


def build_deterministic_third(
    plan,
    source_date_value,
    used_queries,
):

    cleaned = plan[
        "cleaned_news"
    ]

    subject = plan[
        "primary_subject"
    ]

    parts = (
        [
            subject
        ]
        + document_markers(
            cleaned
        )
        + extract_numbers(
            cleaned
        )
        + important_tokens(
            cleaned,
            15,
        )[
            5:
        ]
    )

    if (
        plan[
            "update_mode"
        ]
        and source_date_value
    ):

        parts.append(
            source_date_value
        )

    q = short_query(
        " ".join(
            dict.fromkeys(
                x

                for x
                in parts

                if x
            )
        ),
        290,
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

    claimed_domain = plan[
        "source_hint"
    ]

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

            if (
                "TAVILY_401"
                in str(
                    exc
                )

                or "TAVILY_429"
                in str(
                    exc
                )
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
            claimed_domain,
        )

        if strong_enough(
            results,
            claimed_domain,
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
                        "one Groq query fallback"
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

                else:

                    raise

        else:

            third = build_deterministic_third(
                plan,
                source_date_value,
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
                claimed_domain,
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
                f"{type(exc).__name__}: "
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

    for item in results:

        if (
            item[
                "url"
            ].lower()
            == url.lower()
        ):

            item[
                "is_original"
            ] = True

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

            "is_original":
                True,
        }
    ] + results


def select_sources(
    results,
    limit,
    claimed_domain="",
):

    items = ranked(
        results,
        claimed_domain,
    )

    selected = []
    seen_urls = set()
    seen_domains = set()

    for item in items:

        if item.get(
            "is_original"
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

    if claimed_domain:

        for item in items:

            d = domain(
                item[
                    "url"
                ]
            )

            if (
                (
                    d == claimed_domain
                    or d.endswith(
                        "."
                        + claimed_domain
                    )
                )

                and item[
                    "url"
                ].lower()
                not in seen_urls
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


def enrich_sources(
    results,
    claimed_domain="",
):

    selected = select_sources(
        results,
        MAX_EXTRACT_URLS,
        claimed_domain,
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
# FINAL ANALYSIS
# =========================================================

def parse_used_sources(
    answer,
    sources,
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

        for raw in match.group(
            1
        ).split(
            ","
        ):

            raw = raw.strip()

            if not raw.isdigit():

                continue

            num = int(
                raw
            )

            if (
                1 <= num
                <= len(
                    sources
                )
            ):

                item = sources[
                    num - 1
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
        answer,
        used,
    )


def output_guard(answer):

    answer = (
        answer
        or ""
    ).strip()

    confidence_match = re.search(
        (
            r"(?i)"
            r"Уверенность\s*:\s*"
            r"(\d{1,2})\s*/\s*10"
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

    if (
        answer.startswith(
            "🔴 ПИЗДЁЖ"
        )

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

    letters = re.findall(
        r"[A-Za-zА-Яа-яЁё]",
        answer,
    )

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
        letters

        and latin
        > max(
            80,
            cyr * 1.5,
        )
    ):

        return (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Модель вернула пояснение "
            "не на русском, поэтому "
            "сомнительный ответ не показываю. "
            "Повтори проверку.\n"
            "Уверенность: 2/10"
        )

    return answer


def analyze(
    news_text,
    source_date_value,
    used_plan,
    results,
    plan,
):

    claimed_domain = plan[
        "source_hint"
    ]

    sources = select_sources(
        results,
        MAX_AI_SOURCES,
        claimed_domain,
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

    query_text = "\n".join(
        (
            f"- [{x['kind']}] "
            f"{x['q']}"
        )

        for x
        in used_plan
    )

    source_text = "\n\n".join(
        blocks
    )

    prompt = f"""
{date_context(source_date_value)}

ГЛАВНЫЙ ОБЪЕКТ:

{plan['primary_subject'] or 'не определён'}

ЗАЯВЛЕННЫЙ ПЕРВОИСТОЧНИК:

{claimed_domain or 'не указан'}

БЫСТРО ОБНОВЛЯЮЩАЯСЯ НОВОСТЬ:

{"ДА" if plan['update_mode'] else "НЕТ"}

ДОКУМЕНТ:

{"ДА" if plan['document_mode'] else "НЕТ"}

НОВОСТЬ:

{news_text[:5000]}

ПОИСКОВЫЕ ЗАПРОСЫ:

{query_text}

ИСТОЧНИКИ:

{source_text}

Сделай финальный фактчек.

Обязательные правила:

- весь ответ пользователю только на русском;

- сначала проверяй главный объект,
а не объект сравнения;

- если заявлен первоисточник
и он найден,
дай ему приоритет;

- не опровергай
одну комплектацию,
рынок
или версию
данными другой;

- старый похожий указ
или закон
не опровергает
новый документ;

- если точная идентичность
документа или версии
не установлена —
не ставь 🔴;

- старые меньшие цифры
не опровергают
более свежий апдейт;

- при уверенности
ниже 7/10
запрещён 🔴.

После строки:

Уверенность: N/10

обязательно напиши:

USED: 1,2
""".strip()

    answer = groq_text(
        SYSTEM_PROMPT,
        prompt,

        max_tokens=650,

        temperature=0.02,
    )

    if not answer:

        raise RuntimeError(
            "Groq вернул пустой ответ"
        )

    (
        answer,
        used,
    ) = parse_used_sources(
        answer,
        sources,
    )

    answer = output_guard(
        answer
    )

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

    if len(
        title
    ) > 28:

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
                len(
                    buttons
                ),
                2,
            )
        ]
    }


# =========================================================
# FACTCHECK V9.1
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
            "V9.1 search plan: "
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
            "V9.1 subject="
            f"{plan['primary_subject'] or '-'}; "

            "source_hint="
            f"{plan['source_hint'] or '-'}; "

            "document="
            f"{plan['document_mode']}; "

            "update="
            f"{plan['update_mode']}; "

            "foreign="
            f"{plan['foreign_subject']}"
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

    (
        results,
        used_plan,
    ) = search_with_budget(
        news_text,
        source_date_value,
        plan,
    )

    claimed_domain = plan[
        "source_hint"
    ]

    filtered = []

    for item in results:

        priority = source_priority(
            item[
                "url"
            ],
            claimed_domain,
        )

        if (
            item.get(
                "retrieval_score",
                0,
            )
            >= 18

            or priority <= 1
        ):

            filtered.append(
                item
            )

    results = add_original_url(
        news_text,
        filtered,
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
        results,
        claimed_domain,
    )

    (
        answer,
        used,
    ) = analyze(
        news_text,
        source_date_value,
        used_plan,
        results,
        plan,
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
            "В обычной проверке V9.1 "
            "использует его только "
            "для финального ответа. "
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

    if "TAVILY_400" in text:

        return (
            "Tavily отклонил запрос. "
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
    # Никаких отдельных пользователей и подколов.
    # AUTO_CHECK работает одинаково для всех.
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

        ocr_text = maybe_ocr_document(
            source_message,
            news_text,
        )

        check_text = news_text

        if ocr_text:

            check_text += (
                "\n\n"
                "ТЕКСТ С ИЗОБРАЖЕНИЯ ДОКУМЕНТА:\n"
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
            "Chicken Company bot V9.1 started; "
            "nikolai_roasts=OFF; "
            "russian_only=True; "
            "primary_source_priority=True; "
            "primary_subject=True; "
            "document_guard=True; "
            "document_ocr=True; "
            "red_confidence_guard=True; "
            "groq_normal_check=1_call; "
            "search_budget=1->2->optional3; "
            "cache=6h"
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