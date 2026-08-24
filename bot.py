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
HANDLE_RE = re.compile(r"(?<!\w)@[A-Za-z0-9_]{3,}")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}\b")
NUMBER_RE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:га|км|м|%|млн|млрд)?\b",
    re.I,
)

MAX_NEWS_CHARS = 4000
MAX_QUERY_SEED_CHARS = 3200
MAX_SEARCH_QUERY_CHARS = 340
SEARCH_RETRY_QUERY_CHARS = 250

MAX_INITIAL_QUERIES = 5
MAX_REFINED_QUERIES = 3
MAX_RESULTS_PER_QUERY = 6

MAX_EXTRACT_URLS = 4
MAX_EXTRACT_CHARS_PER_SOURCE = 1600
MAX_SEARCH_SNIPPET_CHARS = 700
MAX_AI_SOURCES = 6
MAX_TG_SOURCES = 5
MAX_TOTAL_SOURCE_CHARS = 9000

MIN_TEXT_FOR_PREEXTRACT = 180

RETRY_TOP_SCORE = 54
STRONG_RESULT_SCORE = 48
MIN_STRONG_RESULTS = 2

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
    "одного",
    "одной",
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

NOISE_EXACT = {
    "ftt",
    "подписаться",
    "подписывайтесь",
    "читать",
    "источник",
    "наш канал",
    "подробнее",
    "прислать новость",
    "предложить новость",
}

INVENTED_VENUE_MARKERS = (
    "parliament",
    "парламент",
    "summit",
    "саммит",
    "conference",
    "конференц",
    "forum",
    "форум",
    "congress",
    "конгресс",
    "hearing",
    "слушан",
    "white house",
    "белый дом",
    "kremlin",
    "кремл",
    "ministry",
    "министерств",
)


SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.

Тебе передают проверяемую новость,
дату исходного поста если она известна,
поисковые запросы и найденные источники.

Правила:

1. Работай только по переданным источникам.
Ничего не выдумывай.

2. Мысленно разбивай новость
на ключевые утверждения,
но не показывай C1/C2/C3.

3. Разные части новости
могут подтверждаться разными источниками.

4. "Не найдено подтверждение"
НЕ означает
"доказано, что это ложь".

5. 🔴 ПИЗДЁЖ —
только когда центральный факт
надёжно опровергнут.

6. 🟡 ПОЛУПИЗДЁЖ —
когда событие реально,
но важная часть действительно неверна.

Отсутствие второстепенной детали
в другом источнике
не является опровержением.

7. 🟠 НАЕБАЛИ С КОНТЕКСТОМ —
реальные факты,
но неверная дата,
старый контекст,
вырванная цитата
или вводящая в заблуждение подача.

8. ⚪ ХУЙ ПОЙМЁШЬ ПОКА —
если данных действительно недостаточно.

9. Не смешивай похожие события.

Сверяй:

место,
объект,
людей,
дату,
цифры,
обстоятельства.

10. Фраза:

"Огонь не дошёл до Сафари-парка"

НЕ означает:

"Пожара рядом с Сафари-парком не было".

11. Если дата исходного поста известна,
"сегодня/вчера/этой ночью"
считай от неё.

Если неизвестна —
не подставляй текущую дату сервера.

12. Иностранная цитата
может быть переводом.

Сравнивай смысл,
а не дословный русский текст.

13. Официальный первоисточник
особенно силён для:

собственного решения,
продукта,
судебного решения,
результатов соревнования,
официального транскрипта.

14. Для локальных событий
местный официальный орган
или региональное СМИ
могут быть лучшим источником.

15. Извлечённый текст страницы
сильнее короткого поискового сниппета.

Вердикты:

🟢 НЕ ПИЗДЁЖ
🟡 ПОЛУПИЗДЁЖ
🟠 НАЕБАЛИ С КОНТЕКСТОМ
🔴 ПИЗДЁЖ
⚪ ХУЙ ПОЙМЁШЬ ПОКА

Формат:

Первая строка —
только один вердикт.

Дальше 2–4 коротких предложения.

Последняя видимая строка:

Уверенность: N/10

После неё техническая строка:

USED: 1,2

URL не печатай.

Не шути про семью,
детей,
болезни,
смерть
и трагедии.
""".strip()


# =========================================================
# HELPERS
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


def unique_urls(
    urls,
    limit=None,
):
    out = []
    seen = set()

    for url in urls:

        url = clean_url(
            url
        )

        if not url:
            continue

        key = url.lower()

        if key in seen:
            continue

        seen.add(
            key
        )

        out.append(
            url
        )

        if (
            limit
            and len(out) >= limit
        ):
            break

    return out


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
    text = normalize(
        text
    )

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

    if (
        start < 0
        or end <= start
    ):

        return None

    try:

        return json.loads(
            text[start:end + 1]
        )

    except Exception:

        return None


def meaningful_tokens(text):

    words = re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{2,}"
        ),
        (text or "").lower(),
    )

    return {
        word

        for word
        in words

        if (
            word not in STOPWORDS

            and (
                len(word) >= 4
                or word.isdigit()
            )
        )
    }


def numeric_anchors(text):

    values = []

    for value in TIME_RE.findall(
        text or ""
    ):

        if value not in values:

            values.append(
                value
            )

    for value in NUMBER_RE.findall(
        text or ""
    ):

        value = normalize(
            value
        )

        if (
            value
            and value not in values
            and len(value) <= 20
        ):

            values.append(
                value
            )

    return values[:8]


# =========================================================
# НОВОЕ:
# УБИРАЕМ FTT / TELEGRAM-ПОДПИСИ
# =========================================================

def clean_search_text(text):
    """
    Чистим текст только для поиска.

    Сам исходный текст новости
    для финального анализа не меняется.
    """

    text = URL_RE.sub(
        " ",
        text or "",
    )

    text = HANDLE_RE.sub(
        " ",
        text,
    )

    lines = []

    for line in (
        text or ""
    ).splitlines():

        line = normalize(
            line
        )

        if not line:

            continue

        low = line.lower()

        if any(
            marker in low

            for marker in (
                "👉",
                "подписаться",
                "подписывайтесь",
                "наш канал",
                "прислать новость",
                "предложить новость",
                "читать далее",
            )
        ):

            continue

        compact = re.sub(
            r"[^a-zа-яё0-9]+",
            "",
            low,
        )

        if compact in {
            "ftt",
        }:

            continue

        lines.append(
            line
        )

    return normalize(
        " ".join(
            lines
        )
    )


def is_noise_anchor(anchor):

    low = (
        normalize(anchor)
        .lower()
        .strip(
            " .,:;!?-—_"
        )
    )

    compact = re.sub(
        r"[^a-zа-яё0-9]+",
        "",
        low,
    )

    if (
        low in NOISE_EXACT
        or compact in {"ftt"}
    ):

        return True

    if low.startswith("@"):

        return True

    if (
        "подпис" in low
        or "subscribe" in low
    ):

        return True

    return False


# =========================================================
# НОВОЕ:
# НЕ ДАЁМ GROQ ПРИДУМЫВАТЬ
# FINNISH PARLIAMENT И Т.П.
# =========================================================

def sanitize_generated_query(
    query,
    kind,
    source_text,
):

    query = short_query(
        query,
        260,
    )

    if len(query) < 4:

        return ""

    low_query = query.lower()

    low_source = (
        source_text
        or ""
    ).lower()

    if kind == "official":

        for marker in INVENTED_VENUE_MARKERS:

            if (
                marker in low_query

                and marker
                not in low_source
            ):

                print(
                    (
                        "Dropped invented official query: "
                        f"{query}"
                    ),
                    flush=True,
                )

                return ""

    query = HANDLE_RE.sub(
        " ",
        query,
    )

    query = re.sub(
        r"(?i)\bFTT\b",
        " ",
        query,
    )

    query = re.sub(
        (
            r"(?i)\b"
            r"подпис(?:аться|ывайтесь)?"
            r"\b"
        ),
        " ",
        query,
    )

    return short_query(
        normalize(
            query
        ),
        260,
    )


# =========================================================
# SOURCE DATE
# =========================================================

def telegram_source_date(message):

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
        "Не превращай «сегодня/вчера/этой ночью» "
        "в текущую дату сервера. "
        "Ищи событие по месту, людям, "
        "объекту, цифрам и обстоятельствам."
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
# MEDIA CACHE
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


def extract_news_text(message):

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

    return (
        len(text) >= 90

        and len(
            re.findall(
                r"\w+",
                text,
                flags=re.UNICODE,
            )
        ) >= 10
    )


def looks_like_news(message):

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
        (
            r"^/(?:check|factcheck)"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s+|$)"
        ),
        raw,
        flags=re.I,
    )

    trigger = None

    if not command_match:

        for item in CHECK_WORDS:

            if (
                lower == item

                or lower.startswith(
                    item
                    + " "
                )
            ):

                trigger = item

                break

    if (
        not command_match
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
            len(trigger):
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

    try:

        wait = float(
            (
                response.headers.get(
                    "retry-after"
                )
                or ""
            ).strip()
        )

    except (
        TypeError,
        ValueError,
    ):

        wait = (
            GROQ_DEFAULT_RETRY_SECONDS
        )

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

            return "\n".join(
                str(
                    item.get(
                        "text"
                    )
                )

                for item
                in content

                if (
                    isinstance(
                        item,
                        dict,
                    )

                    and item.get(
                        "text"
                    )
                )
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

    parts.extend(
        content[
            :MAX_QUERY_SEED_CHARS
        ]

        for content
        in extracted.values()
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
# V5 QUERY GENERATION
# =========================================================

def fallback_precision_query(
    news_text,
):

    cleaned = clean_search_text(
        news_text
    )

    numbers = numeric_anchors(
        cleaned
    )

    tokens = []
    seen = set()

    for token in re.findall(
        (
            r"[A-Za-zА-Яа-яЁё0-9]"
            r"[A-Za-zА-Яа-яЁё0-9\-]{3,}"
        ),
        cleaned,
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

        tokens.append(
            token
        )

        if len(tokens) >= 10:

            break

    return short_query(
        " ".join(
            tokens[:8]
            + numbers[:5]
        ),
        260,
    )


def groq_build_retrieval_plan(
    news_text,
    seed_text,
    source_date="",
):

    cleaned_news = clean_search_text(
        news_text
    )

    cleaned_seed = clean_search_text(
        seed_text
    )

    source_for_validation = normalize(
        (
            f"{cleaned_news} "
            f"{cleaned_seed}"
        )
    )

    date_context = (
        relative_date_context(
            source_date
        )
    )

    prompt = f"""
Построй точные веб-поисковые запросы
для фактчека.

{date_context}

ВАЖНО:

Текст уже очищен
от рекламного хвоста Telegram.

НЕ используй:

FTT,
@username,
"подписаться",
название Telegram-канала,
рекламные подписи

как факты или anchors.

Верни ТОЛЬКО JSON:

{{
  "foreign_subject": true,

  "anchors": [
    "...",
    "..."
  ],

  "queries": [

    {{
      "q": "...",
      "kind": "precision"
    }},

    {{
      "q": "...",
      "kind": "official"
    }},

    {{
      "q": "...",
      "kind": "original_language_meaning"
    }},

    {{
      "q": "...",
      "kind": "original_language_synonyms"
    }}
  ]
}}

ПРАВИЛА ANCHORS:

Выбери 4–8
самых отличительных фактов.

Приоритет:

- фамилия;
- организация;
- точное место;
- объект;
- редкое название;
- точное время;
- площадь;
- числа;
- необычная мысль цитаты.

Не бери общие слова.

Не бери подписи Telegram.

ПРАВИЛА QUERIES:

1. precision

Используй самые редкие детали.

Для локальной новости:

место + объект + цифры + время.

Хороший пример:

Геленджик Сафари-парк 0,04 га 06:20 07:10

2. official

НЕ ПРИДУМЫВАЙ,
где человек выступал.

Нельзя добавлять:

Parliament,
summit,
conference,
forum,
ministry

и т.п.,

если такого места или органа
НЕТ в исходном тексте.

Если место выступления неизвестно,
делай нейтральный запрос:

Имя + тема +
official transcript interview speech remarks

3. Если субъект иностранный
или цитата переведена на русский:

foreign_subject=true

и ОБЯЗАТЕЛЬНО дай
ДВА разных original-language запроса.

original_language_meaning:

- имя латиницей;
- основная мысль;
- 5–10 смысловых слов;
- НЕ буквальный машинный перевод.

original_language_synonyms:

- тот же факт;
- но другими английскими словами;
- естественные синонимы;
- формулировки,
которые реально могли быть
в транскрипте или статье.

Пример.

ПЛОХО:

Alexander Stubb Ukraine charity help

ХОРОШО:

Alexander Stubb Ukraine support altruism Europe needs Ukraine learn from Ukraine

ВТОРОЙ ВАРИАНТ:

Alexander Stubb Europe needs Ukraine more support not charity learning from Ukrainians

4. Не вставляй текущую дату сервера,
если она не известна
из исходного поста.

5. Максимум {MAX_INITIAL_QUERIES}
запросов.

Каждый до 260 символов.

ОЧИЩЕННАЯ НОВОСТЬ:

{cleaned_news[:MAX_NEWS_CHARS]}

ОЧИЩЕННЫЙ ТЕКСТ
ИСХОДНОЙ ССЫЛКИ,
ЕСЛИ ЕСТЬ:

{cleaned_seed[:MAX_QUERY_SEED_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты строишь retrieval-план. "
            "Не выдумывай место выступления, "
            "источник, дату или организацию."
        ),

        prompt,

        max_tokens=520,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    foreign_subject = bool(
        data.get(
            "foreign_subject"
        )
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
        )[:100]

        if (
            len(item) < 2
            or is_noise_anchor(
                item
            )
        ):

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

    # Цифры/время добавляем сами.
    # Groq не сможет их случайно потерять.

    for item in numeric_anchors(
        cleaned_news
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

    def add(
        query,
        kind,
    ):

        kind = normalize(
            kind
            or "precision"
        ).lower()

        query = sanitize_generated_query(
            query,
            kind,
            source_for_validation,
        )

        if len(query) < 4:

            return

        key = query.lower()

        if key in seen_queries:

            return

        seen_queries.add(
            key
        )

        queries.append({
            "q":
                query,

            "kind":
                kind,
        })

    if anchors:

        add(
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

            add(
                item,
                "precision",
            )

        elif isinstance(
            item,
            dict,
        ):

            add(
                (
                    item.get(
                        "q"
                    )
                    or item.get(
                        "query"
                    )
                    or ""
                ),

                (
                    item.get(
                        "kind"
                    )
                    or "precision"
                ),
            )

        if len(
            queries
        ) >= MAX_INITIAL_QUERIES:

            break

    # Если иностранная тема,
    # обязательно должны быть два
    # разных смысловых запроса.

    if foreign_subject:

        original_count = sum(
            1

            for item
            in queries

            if item[
                "kind"
            ].startswith(
                "original_language"
            )
        )

        if original_count < 2:

            extra_prompt = f"""
Нужны только ДВА разных
английских поисковых запроса
для этой новости.

Не указывай место выступления,
если его нет в тексте.

Первый запрос:
по основной мысли.

Второй запрос:
другими естественными
английскими словами/синонимами.

Не используй:

FTT,
Telegram-канал,
@username.

Не делай буквальный
машинный перевод.

Верни JSON:

{{
  "queries": [
    "...",
    "..."
  ]
}}

НОВОСТЬ:

{cleaned_news[:2200]}
""".strip()

            try:

                extra_content = groq_text(
                    (
                        "Ты создаёшь два "
                        "английских поисковых запроса "
                        "по смыслу иностранной цитаты."
                    ),

                    extra_prompt,

                    max_tokens=220,

                    temperature=0.0,
                )

                extra = (
                    parse_json_object(
                        extra_content
                    )
                    or {}
                )

                for index, query in enumerate(
                    extra.get(
                        "queries"
                    )
                    or []
                ):

                    add(
                        query,
                        (
                            "original_language_"
                            f"fallback_{index + 1}"
                        ),
                    )

            except Exception as exc:

                print(
                    (
                        "Original-language "
                        "fallback warning: "
                        f"{type(exc).__name__}: "
                        f"{exc}"
                    ),
                    flush=True,
                )

    if not queries:

        add(
            fallback_precision_query(
                cleaned_news
            ),
            "fallback",
        )

    return {
        "foreign_subject":
            foreign_subject,

        "anchors":
            anchors,

        "queries":
            queries[
                :MAX_INITIAL_QUERIES
            ],

        "cleaned_news":
            cleaned_news,
    }


# =========================================================
# SOURCE PRIORITY
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


def source_priority(url):

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

    wires = (
        "reuters.com",
        "apnews.com",
        "afp.com",
    )

    major = (
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

    specialist = (
        "hltv.org",
        "liquipedia.net",
        "esportsworldcup.com",
        "teamspirit.gg",
        "riotgames.com",
        "arxiv.org",
        "brookings.edu",
    )

    if (
        domain_matches(
            domain,
            official,
        )

        or any(
            marker in domain
            for marker
            in official_markers
        )
    ):

        return 0

    if domain_matches(
        domain,
        wires,
    ):

        return 1

    if (
        domain_matches(
            domain,
            major,
        )

        or domain_matches(
            domain,
            specialist,
        )
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

    response, safe_query = (
        _tavily_search_request(
            plan_item[
                "q"
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
                    "q"
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

    return results


def run_search_plan(
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
# RETRIEVAL SCORE
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

    tokens = meaningful_tokens(
        re.sub(
            r"\bsite:[^\s]+",
            " ",
            query or "",
            flags=re.I,
        )
    )

    if tokens:

        hits = sum(
            1

            for token
            in tokens

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

    numbers = numeric_anchors(
        query
    )

    number_score = 0

    if numbers:

        normalized_haystack = (
            haystack.replace(
                ",",
                ".",
            )
        )

        number_hits = sum(
            1

            for value
            in numbers

            if (
                value.lower()
                .replace(
                    ",",
                    ".",
                )
                in normalized_haystack
            )
        )

        number_score = (
            22
            * number_hits
            / len(numbers)
        )

    tavily_bonus = min(
        18,
        float(
            item.get(
                "score"
            )
            or 0
        )
        * 18,
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
            (
                token_score
                * 0.72

                + number_score

                + tavily_bonus

                + source_bonus
            ),
            1,
        ),
    )


def attach_retrieval_scores(
    results,
    query_map,
):

    for item in results:

        per_query = {}

        for query_index in item.get(
            "matched_queries",
            set(),
        ):

            query = query_map.get(
                query_index,
                "",
            )

            if query:

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


def rank_results(results):

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


def retrieval_is_weak(
    results,
    search_plan,
):

    if not results:

        return True

    ranked = rank_results(
        results
    )

    top_score = float(
        ranked[
            0
        ].get(
            "retrieval_score"
        )
        or 0
    )

    strong_count = sum(
        (
            float(
                item.get(
                    "retrieval_score"
                )
                or 0
            )
            >= STRONG_RESULT_SCORE
        )

        for item
        in ranked
    )

    original_indexes = {
        index

        for index, item
        in enumerate(
            search_plan
        )

        if (
            item.get(
                "kind",
                "",
            ).startswith(
                "original_language"
            )
        )
    }

    if original_indexes:

        original_best = 0

        for item in results:

            for (
                query_index,
                score
            ) in (
                item.get(
                    "query_relevance"
                )
                or {}
            ).items():

                if (
                    query_index
                    in original_indexes
                ):

                    original_best = max(
                        original_best,
                        float(
                            score
                        ),
                    )

        if original_best < 44:

            return True

    return (
        top_score
        < RETRY_TOP_SCORE

        or strong_count
        < MIN_STRONG_RESULTS
    )


def light_filter_results(results):

    ranked = rank_results(
        results
    )

    if not ranked:

        return []

    top_score = float(
        ranked[
            0
        ].get(
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
            score >= 22

            or matched_count >= 2

            or (
                priority <= 2
                and score >= 14
            )

            or score >= max(
                16,
                top_score - 40,
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
# REFINEMENT
# =========================================================

def refinement_pack(
    results,
    limit=8,
):

    lines = []

    for index, item in enumerate(
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
                f"score="
                f"{item.get('retrieval_score', 0)} | "
                f"{normalize(item.get('content', ''))[:300]}"
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
    foreign_subject,
):

    cleaned_news = clean_search_text(
        news_text
    )

    date_context = relative_date_context(
        source_date
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
Первый поиск дал слабую выдачу.

Создай максимум
{MAX_REFINED_QUERIES}
НОВЫХ запросов.

{date_context}

ANCHORS:

{", ".join(anchors) if anchors else "не выделены"}

СТАРЫЕ ЗАПРОСЫ:

{current_queries}

СЛАБАЯ ВЫДАЧА:

{refinement_pack(results)}

ПРАВИЛА:

- не повторяй старые запросы;

- не используй FTT,
@username,
"подписаться"
и название Telegram-канала;

- не придумывай
Parliament,
summit,
conference,
forum,
ministry
или место выступления;

- локальное событие:
место + объект + редкие цифры + время;

- если иностранная тема =
{str(bool(foreign_subject)).lower()},
хотя бы один новый запрос
должен быть на английском
и ПЕРЕФОРМУЛИРОВАТЬ смысл
другими синонимами;

- ищи возможные слова
оригинального транскрипта,
а не буквальный русский перевод;

- не добавляй текущую дату сервера,
если она не известна
из исходного поста.

Верни только JSON:

{{
  "queries": [

    {{
      "q": "...",
      "kind": "refined_precision"
    }},

    {{
      "q": "...",
      "kind": "refined_original_language"
    }}
  ]
}}

НОВОСТЬ:

{cleaned_news[:MAX_NEWS_CHARS]}
""".strip()

    content = groq_text(
        (
            "Ты улучшаешь слабый веб-поиск. "
            "Не выдумывай место выступления "
            "или источник."
        ),

        prompt,

        max_tokens=340,

        temperature=0.0,
    )

    data = (
        parse_json_object(
            content
        )
        or {}
    )

    seen = {
        item[
            "q"
        ].lower()

        for item
        in current_plan
    }

    out = []

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

            query = item

            kind = "refined"

        elif isinstance(
            item,
            dict,
        ):

            query = (
                item.get(
                    "q"
                )
                or item.get(
                    "query"
                )
                or ""
            )

            kind = normalize(
                item.get(
                    "kind"
                )
                or "refined"
            ).lower()

        else:

            continue

        query = sanitize_generated_query(
            query,
            kind,
            cleaned_news,
        )

        if (
            len(query) < 4

            or query.lower()
            in seen
        ):

            continue

        seen.add(
            query.lower()
        )

        out.append({
            "q":
                query,

            "kind":
                kind,
        })

        if len(
            out
        ) >= MAX_REFINED_QUERIES:

            break

    return out


# =========================================================
# ORIGINAL SOURCE
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
# SOURCE SELECTION
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

    originals = [
        item

        for item
        in ranked

        if (
            item.get(
                "query_index"
            )
            == -1
        )
    ]

    if originals:

        item = originals[
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

        chosen = candidates[
            0
        ]

        selected.append(
            chosen
        )

        seen_urls.add(
            chosen[
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
        raw_content
    ) in extracted.items():

        item = by_url.get(
            clean_url(
                key
            ).lower()
        )

        if item is not None:

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
# FINAL CONTEXT
# =========================================================

def sources_for_ai(results):

    selected = select_balanced_sources(
        results,
        MAX_AI_SOURCES,
    )

    blocks = []
    total_chars = 0

    for (
        index,
        item
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

        block = (
            f"[{index}]\n"
            f"Источник: "
            f"{item.get('title', 'Источник')}\n"
            f"Домен: "
            f"{source_domain(item['url'])}\n"
            f"Retrieval score: "
            f"{item.get('retrieval_score', 0)}\n"
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
# FINAL GROQ
# =========================================================

def groq_analyze(
    news_text,
    source_date,
    search_plan,
    results,
):

    source_text, selected = sources_for_ai(
        results
    )

    queries = "\n".join(
        (
            f"{index}. "
            f"[{item.get('kind', 'query')}] "
            f"{item['q']}"
        )

        for index, item
        in enumerate(
            search_plan,
            1,
        )
    )

    prompt = f"""
КОНТЕКСТ ДАТЫ:

{relative_date_context(source_date)}

ПРОВЕРЯЕМАЯ НОВОСТЬ:

{news_text[:MAX_NEWS_CHARS]}

ПОИСКОВЫЕ ЗАПРОСЫ:

{queries}

ИСТОЧНИКИ:

{source_text}

Сделай финальный фактчек.

Не суди по качеству
самого поискового запроса.

Суди по содержанию
найденных источников.

Особенно:

- не смешивай похожие события;

- отсутствие факта в источнике
не является его опровержением;

- "огонь не дошёл до парка"
не опровергает пожар рядом с парком;

- иностранную цитату
сравнивай по смыслу и контексту,
а не по буквальному переводу;

- если источник подтверждает
центральный смысл,
небольшое отличие перевода
не делает цитату ложной.

После:

Уверенность: N/10

обязательно напиши:

USED: 1,2
""".strip()

    answer = groq_text(
        SYSTEM_PROMPT,

        prompt,

        max_tokens=780,

        temperature=0.05,
    )

    if not answer:

        time.sleep(
            2
        )

        answer = groq_text(
            SYSTEM_PROMPT,

            prompt,

            max_tokens=840,

            temperature=0.03,
        )

    if not answer:

        raise RuntimeError(
            "Groq дважды вернул пустой текст"
        )

    answer, used = parse_used_sources(
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
# BUTTONS
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
        name
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


def source_keyboard(results):

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

        for index, item
        in enumerate(
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
# FACTCHECK V5
# =========================================================

def factcheck(
    news_text,
    source_date="",
):

    preextracted, seed_text = (
        preextract_original_if_needed(
            news_text
        )
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
                "Не получилось построить "
                "нормальный поиск.\n"
                "Уверенность: 1/10"
            ),

            [],
        )

    print(
        (
            "Factcheck source_date: "
            f"{source_date or 'unknown'}"
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

        for index, item
        in enumerate(
            search_plan
        )
    }

    results = attach_retrieval_scores(
        results,
        query_map,
    )

    if retrieval_is_weak(
        results,
        search_plan,
    ):

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
                plan.get(
                    "foreign_subject",
                    False,
                ),
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

                for index, item
                in enumerate(
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
                "Поиск не нашёл достаточно "
                "точных источников. "
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
# HANDLER
# =========================================================

def handle_message(message):

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

    # /start

    if re.match(
        (
            r"^/start"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s|$)"
        ),
        raw,
        flags=re.I,
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

    # /id

    if re.match(
        (
            r"^/(?:id|whoami)"
            r"(?:@[A-Za-z0-9_]+)?"
            r"(?:\s|$)"
        ),
        raw,
        flags=re.I,
    ):

        replied = (
            message.get(
                "reply_to_message"
            )
            or {}
        )

        target = (
            replied.get(
                "from"
            )
            or from_user
        )

        target_id = (
            target.get(
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
                    f"{target.get('first_name', '')} "
                    f"{target.get('last_name', '')}"
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
                    "Я фактчекаю посты, "
                    "ссылки и новостные тексты, "
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

    # PRIVATE AUTO CHECK

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

    # NIKOLAI

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

    # OPTIONAL AUTO CHECK GROUP

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
            "🔎 Ща соберу точные запросы "
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

        answer, used_results = factcheck(
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
            "Chicken Company bot V5 started. "

            f"Groq model="
            f"{GROQ_MODEL}; "

            f"AUTO_CHECK="
            f"{AUTO_CHECK}; "

            "retrieval="
            "clean+anchors+"
            "2x-original-language+refine; "

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

                if exc.response is not None

                else None
            )

            if code == 409:

                print(
                    (
                        "Telegram 409: "
                        "другой экземпляр "
                        "уже делает getUpdates. "
                        "Railway: "
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