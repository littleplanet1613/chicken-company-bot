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

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
NIKOLAI_USER_ID = os.getenv("NIKOLAI_USER_ID", "").strip()

AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_SEARCH_API = "https://api.tavily.com/search"
TAVILY_EXTRACT_API = "https://api.tavily.com/extract"

URL_RE = re.compile(r"https?://[^\s<>()]+", re.IGNORECASE)

# Текст новости
MAX_NEWS_CHARS = 3200

# Tavily
MAX_SEARCH_QUERY_CHARS = 350
MAX_SEARCH_QUERIES = 4
MAX_RESULTS_PER_QUERY = 5

# Extract и контекст для Groq.
# Специально держим маленькими, чтобы не выбивать бесплатный TPM Groq.
MAX_EXTRACT_URLS = 3
MAX_EXTRACT_CHARS_PER_SOURCE = 1200
MAX_SEARCH_SNIPPET_CHARS = 550
MAX_AI_SOURCES = 6
MAX_TG_SOURCES = 6
MAX_TOTAL_SOURCE_CHARS = 7000

# Если пользователь прислал почти только ссылку —
# сначала читаем исходную статью и по ней строим запросы.
MIN_TEXT_FOR_PREEXTRACT = 180
MAX_QUERY_SEED_CHARS = 2600

# Groq 429: бот сам ждёт и повторяет.
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


# =========================================================
# ПРОМПТ — КОРОТКИЙ, ЧТОБЫ НЕ ЖРАТЬ TPM
# =========================================================

SYSTEM_PROMPT = """
Ты фактчекер в дружеском Telegram-чате.

Проверяй утверждение ТОЛЬКО по переданным источникам.
Ничего не выдумывай.

Правила:
1. Сначала мысленно разбей составную новость на отдельные факты.
2. Разные части новости могут подтверждаться разными источниками.
3. Сопоставляй имена, организации, даты, места, турниры, суммы и другие ключевые детали.
4. Русские и английские источники оценивай на равных.
5. Для локальных событий важны местные официальные органы и СМИ.
6. Для спорта, киберспорта, технологий и науки профильный надежный источник может быть важнее обычного СМИ.
7. Извлечённый текст страницы надежнее короткого поискового сниппета.
8. "Не нашёл подтверждения" НЕ значит "доказал ложность".
9. НЕЛЬЗЯ ставить 🔴 ПИЗДЁЖ только из-за отсутствия публикации Reuters, BBC, федеральных СМИ или статьи с точно такой же формулировкой.
10. 🔴 ПИЗДЁЖ ставь только если надежные данные прямо опровергают ключевой факт или несовместимы с ним.
11. Если данных недостаточно — ⚪ ХУЙ ПОЙМЁШЬ ПОКА.

Вердикты:
🟢 НЕ ПИЗДЁЖ — ключевой факт нормально подтверждается.
🟡 ПОЛУПИЗДЁЖ — событие настоящее, но важная часть деталей неверна/не подтверждена.
🟠 НАЕБАЛИ С КОНТЕКСТОМ — факты настоящие, но подача/вывод вводит в заблуждение.
🔴 ПИЗДЁЖ — ключевой факт доказанно ложный.
⚪ ХУЙ ПОЙМЁШЬ ПОКА — данных недостаточно или они противоречат друг другу.

Формат:
Первая строка — только один вердикт.
Дальше 2–4 коротких предложения: что подтвердилось, что нет и где подвох.
Последняя строка: Уверенность: N/10

Стиль короткий, понятный, по-пацански. Мат допустим умеренно.
URL и отдельный список источников в текст не вставляй — бот покажет кнопки.
Не шути про семью, детей, болезни, смерть и трагедии.
""".strip()


# =========================================================
# ОБЩИЕ ФУНКЦИИ
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
    return urlparse(url).netloc.lower().removeprefix("www.")


def short_query(text, limit=MAX_SEARCH_QUERY_CHARS):
    text = normalize(text)

    if len(text) <= limit:
        return text

    cut = text[:limit]
    space = cut.rfind(" ")

    if space >= int(limit * 0.65):
        cut = cut[:space]

    return cut.strip()


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
            if now - value["ts"] > MEDIA_GROUP_TTL
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
        or len(text) > len(
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
        user.get(
            "username"
        )
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
# ОПРЕДЕЛЕНИЕ НОВОСТИ
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


def is_forwarded_from_channel(message):
    origin = (
        message.get(
            "forward_origin"
        )
        or {}
    )

    if origin.get(
        "type"
    ) == "channel":
        return True

    forward_chat = (
        message.get(
            "forward_from_chat"
        )
        or {}
    )

    return (
        forward_chat.get(
            "type"
        )
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
                "invalid_reply":
                    True,

                "source_message_id":
                    replied.get(
                        "message_id"
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
    }


# =========================================================
# GROQ С АВТОПОВТОРОМ ПРИ 429
# =========================================================

def parse_retry_after(response):
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

        wait = GROQ_DEFAULT_RETRY_SECONDS

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
    last_response_text = ""

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

            timeout=50,
        )

        last_response_text = response.text[
            :500
        ]

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
                    "Groq 429 rate limit. "
                    f"Waiting {wait:.0f}s "
                    f"before retry "
                    f"{attempt + 1}/{GROQ_MAX_ATTEMPTS}..."
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
                    + last_response_text
                )
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
# RU + EN ПОИСК
# =========================================================

def build_base_query(
    news_text
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

        query = without_urls

    else:

        urls = URL_RE.findall(
            text
        )

        query = (
            urls[
                0
            ]
            if urls
            else text
        )

    return short_query(
        query
    )


def groq_build_search_queries(
    seed_text
):
    prompt = (
        "Сделай поисковые запросы для проверки новости.\n"

        "Нужны максимум 3 строки: русский и английский поиск, "
        "а если утверждение составное — отдельный запрос по второй части.\n"

        "Каждый запрос до 180 символов. "
        "Ничего не объясняй и не выдумывай.\n"

        "Формат:\n"
        "RU | запрос\n"
        "EN | query\n\n"

        "Материал:\n"
        f"{seed_text[:MAX_QUERY_SEED_CHARS]}"
    )

    content = groq_text(
        (
            "Ты создаёшь только короткие "
            "поисковые запросы."
        ),

        prompt,

        max_tokens=180,

        temperature=0.0,
    )

    queries = []
    seen = set()

    for raw_line in content.splitlines():

        line = (
            raw_line
            .strip()
            .strip(
                "`"
            )
            .strip()
        )

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

        line = short_query(
            line,
            200,
        )

        if len(
            line
        ) < 4:
            continue

        key = line.lower()

        if key in seen:
            continue

        seen.add(
            key
        )

        queries.append(
            line
        )

        if len(
            queries
        ) >= 3:
            break

    return queries


def build_search_queries(
    news_text,
    seed_text,
):
    queries = []
    seen = set()

    def add_query(
        query
    ):
        query = short_query(
            query
        )

        if len(
            query
        ) < 4:
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
        build_base_query(
            news_text
        )
    )

    # Если генерация RU+EN упёрлась в Groq,
    # сам фактчек всё равно продолжится.
    try:

        generated = groq_build_search_queries(
            seed_text
        )

    except Exception as exc:

        print(
            (
                "Search-query generation warning: "
                f"{type(exc).__name__}: "
                f"{exc}. "
                "Continuing with base query."
            ),
            flush=True,
        )

        generated = []

    for query in generated:

        add_query(
            query
        )

        if len(
            queries
        ) >= MAX_SEARCH_QUERIES:
            break

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
        domain == item
        or domain.endswith(
            "."
            + item
        )
        for item
        in candidates
    )


def source_priority(
    url
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
        "who.int",
        "un.org",
        "nato.int",
        "nih.gov",
        "pubmed.ncbi.nlm.nih.gov",
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
    )

    specialist_domains = (
        "hltv.org",
        "liquipedia.net",
        "esportsworldcup.com",
        "teamspirit.gg",
        "arxiv.org",
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

def tavily_search_once(
    query,
    query_index,
):
    query = short_query(
        query
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
                query,

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
                    :250
                ]
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
    queries
):
    merged = {}
    successful_queries = 0

    for query_index, query in enumerate(
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

    print(
        (
            "Tavily successful queries: "
            f"{successful_queries}/{len(queries)}"
        ),
        flush=True,
    )

    results = list(
        merged.values()
    )

    results.sort(
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

            -(
                item.get(
                    "score"
                )
                or 0
            ),
        )
    )

    return results


# =========================================================
# БАЛАНС ИСТОЧНИКОВ
# =========================================================

def select_balanced_sources(
    results,
    limit,
):
    if not results:
        return []

    selected = []
    selected_urls = set()

    query_ids = sorted({
        query_id

        for item
        in results

        for query_id
        in item.get(
            "matched_queries",
            {
                item.get(
                    "query_index",
                    0,
                )
            },
        )

        if isinstance(
            query_id,
            int,
        )
        and query_id >= 0
    })

    # По одному лучшему источнику из каждого запроса.
    for query_id in query_ids:

        for item in results:

            key = item[
                "url"
            ].lower()

            if (
                key
                in selected_urls
            ):
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

            if (
                query_id
                not in matched
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

    # Потом добиваем лучшими общими.
    for item in results:

        key = item[
            "url"
        ].lower()

        if (
            key
            in selected_urls
        ):
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
# EXTRACT ЛУЧШИХ ИСТОЧНИКОВ
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

    original_urls = unique_urls(
        URL_RE.findall(
            news_text
        ),
        1,
    )

    best = select_balanced_sources(
        results,
        MAX_EXTRACT_URLS,
    )

    candidate_urls = unique_urls(
        original_urls
        + [
            item[
                "url"
            ]
            for item
            in best
        ],
        MAX_EXTRACT_URLS,
    )

    extracted = dict(
        preextracted
    )

    already_have = {
        key.lower()
        for key
        in extracted
    }

    need_extract = [
        url

        for url
        in candidate_urls

        if url.lower()
        not in already_have
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

    # Исходную ссылку сохраняем,
    # даже если Search её не вернул.
    for url in original_urls:

        key = url.lower()

        if key not in by_url:

            item = {
                "title":
                    "Исходная ссылка",

                "url":
                    url,

                "content":
                    "",

                "raw_content":
                    "",

                "score":
                    1.0,

                "query_index":
                    -1,

                "matched_queries":
                    set(),
            }

            results.insert(
                0,
                item,
            )

            by_url[
                key
            ] = item

    extract_success = 0

    for key, raw_content in extracted.items():

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

        extract_success += 1

    print(
        (
            "Tavily Extract: "
            f"{extract_success} source(s) enriched"
        ),
        flush=True,
    )

    return results


# =========================================================
# КОНТЕКСТ ДЛЯ GROQ
# =========================================================

def sources_for_ai(
    results
):
    selected = select_balanced_sources(
        results,
        MAX_AI_SOURCES,
    )

    original = [
        item

        for item
        in results

        if item.get(
            "query_index"
        ) == -1

        and item
        not in selected
    ]

    if original:

        selected = (
            original[
                :1
            ]
            + selected
        )[
            :MAX_AI_SOURCES
        ]

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

        block = (
            f"[{index}]\n"

            f"Источник: "
            f"{item['title']}\n"

            f"Домен: "
            f"{source_domain(item['url'])}\n"

            f"{evidence}"
        )

        remaining = (
            MAX_TOTAL_SOURCE_CHARS
            - total_chars
        )

        if (
            remaining
            <= 0
        ):
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

    return "\n\n".join(
        blocks
    )


# =========================================================
# ФИНАЛЬНЫЙ АНАЛИЗ
# =========================================================

def groq_analyze(
    news_text,
    results,
):
    user_prompt = (
        "НОВОСТЬ:\n"
        f"{news_text[:MAX_NEWS_CHARS]}"

        "\n\n"

        "ИСТОЧНИКИ:\n"
        f"{sources_for_ai(results)}"

        "\n\n"

        "Перед вердиктом мысленно проверь каждый ключевой факт отдельно. "
        "Если разные части подтверждены разными надежными источниками — "
        "сопоставь их вместе. "

        "Не путай отсутствие подтверждения с опровержением. "
        "Красный вердикт — только при доказанной ложности."
    )

    text = groq_text(
        SYSTEM_PROMPT,
        user_prompt,
        max_tokens=650,
        temperature=0.12,
    )

    if not text:

        print(
            (
                "Groq returned empty content; "
                "retrying once..."
            ),
            flush=True,
        )

        time.sleep(
            2
        )

        text = groq_text(
            SYSTEM_PROMPT,
            user_prompt,
            max_tokens=750,
            temperature=0.08,
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
            f"{index} · {title}"
        )

    return (
        f"{index} · "
        f"{domain[:28]}"
    )


def source_keyboard(
    results
):
    selected = select_balanced_sources(
        results,
        MAX_TG_SOURCES,
    )

    original = [
        item

        for item
        in results

        if item.get(
            "query_index"
        ) == -1

        and item
        not in selected
    ]

    if original:

        selected = (
            original[
                :1
            ]
            + selected
        )[
            :MAX_TG_SOURCES
        ]

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
                item[
                    "url"
                ],
        })

    if not buttons:
        return None

    rows = []

    for i in range(
        0,
        len(
            buttons
        ),
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

def factcheck(
    news_text
):
    # 1. Если пришла почти только ссылка —
    # читаем исходную страницу.
    (
        preextracted,
        seed_text,
    ) = preextract_original_if_needed(
        news_text
    )

    # 2. Делаем базовый + короткие RU/EN запросы.
    queries = build_search_queries(
        news_text,
        seed_text,
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

    # 3. Ищем.
    results = merge_search_results(
        queries
    )

    print(
        (
            "Factcheck unique search sources: "
            f"{len(results)}"
        ),
        flush=True,
    )

    # 4. Читаем максимум 3 лучшие страницы.
    results = enrich_with_extract(
        news_text,
        results,
        preextracted=preextracted,
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

    # 5. Финальный Groq-запрос.
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

    if "GROQ_401" in text:

        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY в Railway."
        )

    if "GROQ_413" in text:

        return (
            "Для Groq запрос всё ещё слишком большой. "
            "Скинь Factcheck error из Railway."
        )

    if "GROQ_400" in text:

        return (
            "Groq отклонил запрос. "
            "Скинь строку Factcheck error из Railway."
        )

    if "GROQ_429" in text:

        return (
            "Groq всё ещё упёрся в лимит даже после автоповторов. "
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
    message
):
    cleanup_media_caches()

    remember_media_group_text(
        message
    )

    chat_id = (
        message.get(
            "chat"
        )
        or {}
    ).get(
        "id"
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
        "🔎 Ща пробью и прочитаю источники…",
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

            "search=Tavily RU+EN; "

            f"extract_urls={MAX_EXTRACT_URLS}; "

            f"source_context={MAX_TOTAL_SOURCE_CHARS}; "

            f"groq_attempts={GROQ_MAX_ATTEMPTS}"
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