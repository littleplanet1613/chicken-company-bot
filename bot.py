import os
import re
import time
import json
import base64
import hashlib
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse

import requests


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
MAX_RESULTS_PER_QUERY = 7
MAX_AI_SOURCES = 7
MAX_EXTRACT_URLS = 4
MAX_POST_CHARS = 6000

FACTCHECK_CACHE_TTL = 6 * 60 * 60
MEDIA_GROUP_TTL = 90

FACTCHECK_CACHE = {}
MEDIA_TEXT_CACHE = {}
MEDIA_ACTION_CACHE = {}

URL_RE = re.compile(r"https?://[^\s<>()]+", re.I)

CHECK_WORDS = (
    "проверь",
    "проверить",
    "фактчек",
    "чекни",
    "проверка",
    "это правда",
    "это правда?",
)

VERDICTS = {
    "TRUE": "🟢 НЕ ПИЗДЁЖ",
    "TRUE_NUANCE": "🟢 НЕ ПИЗДЁЖ, НО ЕСТЬ НЮАНС",
    "PARTLY_TRUE": "🟡 ПОЛУПИЗДЁЖ",
    "MISLEADING": "🟠 НАЕБАЛИ С КОНТЕКСТОМ",
    "FALSE": "🔴 ПИЗДЁЖ",
    "UNCLEAR": "⚪ ХУЙ ПОЙМЁШЬ ПОКА",
}

TRUSTED_DOMAINS = {
    "reuters.com",
    "apnews.com",
    "bbc.com",
    "bbc.co.uk",
    "nytimes.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "tass.ru",
    "interfax.ru",
    "ria.ru",
    "kommersant.ru",
    "rbc.ru",
    "fontanka.ru",
    "donland.ru",
}

OFFICIAL_DOMAINS = {
    "kremlin.ru",
    "government.ru",
    "pravo.gov.ru",
    "publication.pravo.gov.ru",
    "sledcom.ru",
    "genproc.gov.ru",
    "epp.genproc.gov.ru",
    "donland.ru",
    "europa.eu",
    "consilium.europa.eu",
    "un.org",
    "who.int",
    "nato.int",
    "whitehouse.gov",
    "state.gov",
    "defense.gov",
    "president.gov.ua",
}

SOURCE_NAMES = {
    "reuters.com": "Reuters",
    "apnews.com": "AP",
    "bbc.com": "BBC",
    "bbc.co.uk": "BBC",
    "tass.ru": "ТАСС",
    "interfax.ru": "Интерфакс",
    "ria.ru": "РИА Новости",
    "rbc.ru": "РБК",
    "kommersant.ru": "Коммерсантъ",
    "fontanka.ru": "Фонтанка",
    "donland.ru": "Правительство Ростовской области",
}


PLANNER_SYSTEM = """
Ты поисковый планировщик фактчекера Telegram.

Раздели пост на проверяемые факты и эмоциональную оболочку.

КРИТИЧЕСКИ ВАЖНО:

1. Выдели ОДИН центральный проверяемый факт.
2. Отдельно выдели второстепенные проверяемые факты.
3. Оскорбления, сарказм, риторические вопросы, политические оценки и эмоции
   не являются фактами.
4. Для локальных событий ищи региональные официальные источники и местные СМИ.
5. Отсутствие Reuters/BBC/ТАСС НЕ делает локальную новость сомнительной.
6. Если в посте назван источник или есть ссылка, один запрос направь на него.
7. Не выноси финальный вердикт.
8. Верни ТОЛЬКО JSON.
""".strip()


FINAL_SYSTEM = """
Ты фактчекер Telegram.

Используй ТОЛЬКО переданные источники.
Верни ТОЛЬКО валидный JSON без Markdown.

ГЛАВНОЕ ПРАВИЛО:

Вердикт определяется по ЦЕНТРАЛЬНОМУ ФАКТУ,
а не по эмоциональному посту целиком.

Разделяй тезисы на:

- central — главный проверяемый факт;
- secondary — второстепенная проверяемая деталь;
- opinion — мнение, оценка, обобщение;
- nonliteral — сарказм, ругань, риторический вопрос, ирония.

Opinion и nonliteral НЕ должны снижать достоверность центрального факта.

Фразы вроде:

«никто не понимает, что делать»
«ну что, довольны?»
«всё по плану?»

не надо доказывать как факты, если это очевидная оценка автора.

ВЕРДИКТЫ:

TRUE
Центральный факт подтверждён.

TRUE_NUANCE
Центральный факт подтверждён,
но важная второстепенная деталь требует оговорки.

PARTLY_TRUE
В посте несколько важных фактов.
Часть подтверждена, часть опровергнута или существенно не подтверждена.

MISLEADING
Факты могут быть частично верны,
но дата, причина, масштаб или контекст создают ложное впечатление.

FALSE
Центральный факт прямо опровергнут надёжными источниками.

UNCLEAR
Данных недостаточно ИМЕННО для центрального факта.

НЕ СТАВЬ UNCLEAR только потому, что:

- не подтверждена второстепенная деталь;
- пост содержит мат;
- пост содержит сарказм;
- пост содержит политическую оценку;
- новость локальная;
- новости нет у Reuters/BBC/ТАСС;
- найден один качественный региональный официальный первоисточник.

Для локальной новости официальный сайт губернатора,
правительства региона, ведомства региона,
распоряжение, постановление или другой первичный региональный источник
может быть достаточным подтверждением центрального факта.

Если главный факт подтверждён,
но фраза вроде «склады переполнены» не подтверждена,
обычно выбирай TRUE_NUANCE, а не UNCLEAR.

FALSE разрешён только при прямом опровержении
центрального факта и confidence >= 7.

Верни JSON:

{
  "verdict": "TRUE|TRUE_NUANCE|PARTLY_TRUE|MISLEADING|FALSE|UNCLEAR",
  "confidence": 1,
  "central_claim": "...",
  "explanation": "2-4 коротких предложения по-русски",
  "claims": [
    {
      "claim": "...",
      "role": "central|secondary|opinion|nonliteral",
      "status": "confirmed|refuted|unsupported|not_applicable",
      "sources": [1, 2]
    }
  ],
  "used_sources": [1, 2]
}
""".strip()


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def norm_lines(text):
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    return "\n".join(
        line.strip()
        for line in text.split("\n")
        if line.strip()
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
    try:
        return (
            urlparse(url)
            .netloc
            .lower()
            .removeprefix("www.")
        )
    except Exception:
        return ""


def short(text, limit):
    text = norm(text)

    if len(text) <= limit:
        return text

    return text[:limit].rsplit(" ", 1)[0].strip()


def unique(values, limit=None):
    out = []
    seen = set()

    for value in values or []:
        value = norm(str(value or ""))

        if not value:
            continue

        key = value.lower()

        if key in seen:
            continue

        seen.add(key)
        out.append(value)

        if limit and len(out) >= limit:
            break

    return out


def parse_json(text):
    text = (
        (text or "")
        .replace("```json", "")
        .replace("```", "")
        .strip()
    )

    a = text.find("{")
    b = text.rfind("}")

    if a < 0 or b <= a:
        return {}

    try:
        return json.loads(text[a:b + 1])
    except Exception:
        return {}


def make_key(text, extra=""):
    raw = norm(text).lower() + "\n" + extra

    return hashlib.sha256(
        raw.encode("utf-8")
    ).hexdigest()


def cache_get(key):
    item = FACTCHECK_CACHE.get(key)

    if not item:
        return None

    if time.time() - item["ts"] > FACTCHECK_CACHE_TTL:
        FACTCHECK_CACHE.pop(key, None)
        return None

    return item["value"]


def cache_put(key, value):
    FACTCHECK_CACHE[key] = {
        "ts": time.time(),
        "value": value,
    }

    if len(FACTCHECK_CACHE) > 300:
        oldest = sorted(
            FACTCHECK_CACHE,
            key=lambda k: FACTCHECK_CACHE[k]["ts"],
        )[:50]

        for k in oldest:
            FACTCHECK_CACHE.pop(k, None)


def source_date(message):
    origin = message.get("forward_origin") or {}

    ts = (
        origin.get("date")
        or message.get("forward_date")
    )

    if not isinstance(ts, (int, float)):
        return ""

    try:
        tz = timezone(
            timedelta(hours=TZ_HOURS)
        )

        return datetime.fromtimestamp(
            ts,
            tz=tz,
        ).strftime("%Y-%m-%d")

    except Exception:
        return ""


def date_context(value):
    if value:
        return (
            f"Дата исходного Telegram-поста: {value}. "
            "Слова сегодня/вчера/завтра считай от этой даты."
        )

    return (
        "Дата исходного поста неизвестна. "
        "Не придумывай её."
    )


def detect_preferred_domain(text):
    for raw in URL_RE.findall(text or ""):
        d = domain(clean_url(raw))

        if d and d not in {
            "t.me",
            "telegram.me",
            "telegram.org",
        }:
            return d

    low = (text or "").lower()

    names = {
        "reuters": "reuters.com",
        "bbc": "bbc.com",
        "тасс": "tass.ru",
        "интерфакс": "interfax.ru",
        "риа": "ria.ru",
        "рбк": "rbc.ru",
        "эксперт юг": "expertsouth.ru",
    }

    for marker, d in names.items():
        if marker in low:
            return d

    return ""


def search_tokens(text):
    stop = {
        "который",
        "которая",
        "которые",
        "этого",
        "этой",
        "после",
        "перед",
        "через",
        "сегодня",
        "вчера",
        "завтра",
        "только",
        "сейчас",
        "сообщил",
        "сообщила",
        "сообщили",
        "заявил",
        "заявила",
        "заявили",
        "данным",
        "словам",
        "новость",
        "источник",
        "подписаться",
        "подписывайтесь",
    }

    out = []
    seen = set()

    for token in re.findall(
        r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9\-]{2,}",
        text or "",
    ):
        low = token.lower()

        if low in stop:
            continue

        if low in seen:
            continue

        seen.add(low)
        out.append(token)

        if len(out) >= 25:
            break

    return out


# =========================================================
# TELEGRAM
# =========================================================

def tg(method, payload=None, timeout=35):
    r = requests.post(
        f"{TG_API}/{method}",
        json=payload or {},
        timeout=timeout,
    )

    r.raise_for_status()

    data = r.json()

    if not data.get("ok"):
        raise RuntimeError(
            f"Telegram API error: {data}"
        )

    return data


def send_message(
    chat_id,
    text,
    reply_to=None,
    keyboard=None,
):
    payload = {
        "chat_id": chat_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }

    if reply_to:
        payload["reply_parameters"] = {
            "message_id": reply_to,
            "allow_sending_without_reply": True,
        }

    if keyboard:
        payload["reply_markup"] = keyboard

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
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text[:4096],
        "disable_web_page_preview": True,
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    return tg(
        "editMessageText",
        payload,
    )


# =========================================================
# MEDIA GROUPS
# =========================================================

def cleanup_media():
    now = time.time()

    for store in (
        MEDIA_TEXT_CACHE,
        MEDIA_ACTION_CACHE,
    ):
        for key in list(store):
            if (
                now - store[key]["ts"]
                > MEDIA_GROUP_TTL
            ):
                store.pop(key, None)


def remember_media_text(message):
    cleanup_media()

    gid = message.get("media_group_id")

    chat_id = (
        message.get("chat") or {}
    ).get("id")

    text = msg_text(message)

    if not gid or not chat_id or not text:
        return

    key = (
        str(chat_id),
        str(gid),
    )

    old = MEDIA_TEXT_CACHE.get(key)

    if (
        not old
        or len(text) > len(old.get("text", ""))
    ):
        MEDIA_TEXT_CACHE[key] = {
            "ts": time.time(),
            "text": text,
        }


def extract_news_text(message):
    text = msg_text(message)

    if text:
        return text

    gid = message.get("media_group_id")

    chat_id = (
        message.get("chat") or {}
    ).get("id")

    if not gid or not chat_id:
        return ""

    return (
        MEDIA_TEXT_CACHE.get(
            (
                str(chat_id),
                str(gid),
            )
        )
        or {}
    ).get("text", "")


def media_done(message, action):
    cleanup_media()

    gid = message.get("media_group_id")

    chat_id = (
        message.get("chat") or {}
    ).get("id")

    if not gid or not chat_id:
        return False

    key = (
        action,
        str(chat_id),
        str(gid),
    )

    if key in MEDIA_ACTION_CACHE:
        return True

    MEDIA_ACTION_CACHE[key] = {
        "ts": time.time()
    }

    return False


# =========================================================
# MESSAGE DETECTION
# =========================================================

def is_forwarded(message):
    return bool(
        message.get("forward_origin")
        or message.get("forward_date")
        or message.get("forward_from")
        or message.get("forward_from_chat")
    )


def looks_like_news(message):
    text = norm(
        extract_news_text(message)
    )

    return bool(
        URL_RE.search(text)
        or is_forwarded(message)
        or len(text) >= 60
        or message.get("photo")
    )


def parse_manual_check(message):
    raw = msg_text(message)

    if not raw:
        return None

    cmd = re.match(
        r"^/(?:check|factcheck)(?:@[A-Za-z0-9_]+)?(?:\s+|$)",
        raw,
        re.I,
    )

    trigger = None

    if not cmd:
        low = norm(raw).lower()

        for word in CHECK_WORDS:
            if (
                low == word
                or low.startswith(word + " ")
            ):
                trigger = word
                break

    if not cmd and not trigger:
        return None

    replied = message.get(
        "reply_to_message"
    )

    if replied:
        if not looks_like_news(replied):
            return {
                "invalid_reply": True
            }

        return {
            "news_text":
                extract_news_text(replied),

            "source_message_id":
                replied.get("message_id"),

            "source_date":
                source_date(replied),

            "source_message":
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
        "news_text": text,
        "source_message_id":
            message.get("message_id"),
        "source_date": "",
        "source_message": message,
    }


# =========================================================
# GROQ
# =========================================================

def groq_text(
    system_text,
    user_text,
    max_tokens=900,
    stage="main",
    json_mode=False,
    retries=2,
):
    last_error = None

    for attempt in range(retries):

        body = {
            "model": GROQ_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": system_text,
                },
                {
                    "role": "user",
                    "content": user_text,
                },
            ],
            "temperature": 0,
            "max_completion_tokens":
                max_tokens,
            "stream": False,
        }

        if json_mode:
            body["response_format"] = {
                "type": "json_object"
            }

        r = requests.post(
            GROQ_API,
            headers={
                "Authorization":
                    f"Bearer {GROQ_API_KEY}",
                "Content-Type":
                    "application/json",
            },
            json=body,
            timeout=75,
        )

        # Некоторые модели Groq
        # не принимают response_format.
        if (
            r.status_code == 400
            and json_mode
        ):
            body.pop(
                "response_format",
                None,
            )

            r = requests.post(
                GROQ_API,
                headers={
                    "Authorization":
                        f"Bearer {GROQ_API_KEY}",
                    "Content-Type":
                        "application/json",
                },
                json=body,
                timeout=75,
            )

        if r.status_code == 429:

            last_error = RuntimeError(
                f"GROQ_429:{stage}"
            )

            if attempt == retries - 1:
                break

            try:
                wait = float(
                    r.headers.get(
                        "retry-after",
                        "7",
                    )
                )
            except Exception:
                wait = 7

            time.sleep(
                min(
                    max(wait + 1, 2),
                    25,
                )
            )

            continue

        if r.status_code == 401:
            raise RuntimeError(
                "GROQ_401"
            )

        if r.status_code == 413:
            raise RuntimeError(
                "GROQ_413"
            )

        if r.status_code == 400:
            raise RuntimeError(
                "GROQ_400: "
                + r.text[:700]
            )

        r.raise_for_status()

        choices = (
            r.json()
            .get("choices")
            or []
        )

        if not choices:
            return ""

        content = (
            choices[0]
            .get("message")
            or {}
        ).get("content")

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
# OCR
# =========================================================

def best_photo_file_id(message):
    photos = (
        message or {}
    ).get("photo") or []

    if not photos:
        return ""

    best = max(
        photos,
        key=lambda p: (
            p.get("file_size") or 0,
            p.get("width") or 0,
        ),
    )

    return (
        best.get("file_id")
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
            "file_id": file_id
        },
    )

    file_path = (
        data.get("result")
        or {}
    ).get("file_path")

    if not file_path:
        return b""

    r = requests.get(
        (
            "https://api.telegram.org/"
            f"file/bot{TELEGRAM_BOT_TOKEN}/"
            f"{file_path}"
        ),
        timeout=40,
    )

    r.raise_for_status()

    return r.content


def ocr_photo(message):
    if not VISION_MODEL:
        return ""

    if not best_photo_file_id(
        message
    ):
        return ""

    image = telegram_photo_bytes(
        message
    )

    if not image:
        return ""

    data_url = (
        "data:image/jpeg;base64,"
        + base64.b64encode(
            image
        ).decode("ascii")
    )

    body = {
        "model": VISION_MODEL,

        "messages": [
            {
                "role": "user",

                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Распознай текст на изображении максимально точно. "
                            "Если это скрин новости или документ, сохрани даты, "
                            "номера, фамилии, названия и ключевые формулировки. "
                            "Верни только распознанный текст."
                        ),
                    },

                    {
                        "type": "image_url",
                        "image_url": {
                            "url": data_url
                        },
                    },
                ],
            }
        ],

        "temperature": 0,

        "max_completion_tokens":
            1000,
    }

    r = requests.post(
        GROQ_API,
        headers={
            "Authorization":
                f"Bearer {GROQ_API_KEY}",
            "Content-Type":
                "application/json",
        },
        json=body,
        timeout=80,
    )

    if r.status_code in (
        400,
        429,
    ):
        return ""

    if r.status_code == 401:
        raise RuntimeError(
            "GROQ_401"
        )

    r.raise_for_status()

    choices = (
        r.json()
        .get("choices")
        or []
    )

    if not choices:
        return ""

    content = (
        choices[0]
        .get("message")
        or {}
    ).get("content")

    return norm(
        content or ""
    )[:3500]


# =========================================================
# SEARCH PLAN
# =========================================================

def fallback_queries(
    news_text,
    preferred_domain="",
):
    cleaned = URL_RE.sub(
        " ",
        news_text or "",
    )

    tokens = search_tokens(
        cleaned
    )

    base = short(
        " ".join(
            tokens[:16]
        )
        or cleaned,
        280,
    )

    queries = []

    if preferred_domain and base:
        queries.append(
            f"site:{preferred_domain} {base}"
        )

    if base:
        queries.append(
            base
        )

    alt = short(
        " ".join(
            tokens[7:23]
        ),
        260,
    )

    if alt:
        queries.append(
            alt
        )

    return unique(
        queries,
        MAX_SEARCHES,
    )


def build_plan(
    news_text,
    source_date_value,
    preferred_domain="",
):
    prompt = f"""
{date_context(source_date_value)}

ПОСТ:

{news_text[:MAX_POST_CHARS]}

Названный/исходный домен:
{preferred_domain or "не указан"}

Верни JSON:

{{
  "central_claim": "один главный проверяемый факт",
  "secondary_claims": ["второстепенные факты"],
  "opinions": ["мнения и оценки"],
  "nonliteral": ["сарказм, риторика, ругань"],
  "entities": ["люди, места, организации"],
  "queries": ["до 3 поисковых запросов"]
}}

Запросы должны искать центральный факт.

Для локального события ищи региональные источники.

Если указан домен,
один запрос делай через site:домен.
""".strip()

    try:
        raw = groq_text(
            PLANNER_SYSTEM,
            prompt,
            max_tokens=800,
            stage="planner",
            json_mode=True,
        )

        data = parse_json(
            raw
        )

    except RuntimeError as exc:

        if "GROQ_429" not in str(exc):
            raise

        data = {}

    central = norm(
        data.get(
            "central_claim"
        )
        or ""
    )

    if not central:
        central = short(
            URL_RE.sub(
                " ",
                news_text,
            ),
            700,
        )

    queries = unique(
        data.get("queries")
        or [],
        MAX_SEARCHES,
    )

    if not queries:
        queries = fallback_queries(
            news_text,
            preferred_domain,
        )

    if (
        preferred_domain
        and not any(
            f"site:{preferred_domain}"
            in q.lower()
            for q in queries
        )
    ):
        seed = (
            queries[0]
            if queries
            else central
        )

        queries = unique(
            [
                f"site:{preferred_domain} "
                f"{short(seed, 250)}"
            ]
            + queries,
            MAX_SEARCHES,
        )

    return {
        "central_claim":
            central,

        "secondary_claims":
            unique(
                data.get(
                    "secondary_claims"
                )
                or [],
                6,
            ),

        "opinions":
            unique(
                data.get(
                    "opinions"
                )
                or [],
                6,
            ),

        "nonliteral":
            unique(
                data.get(
                    "nonliteral"
                )
                or [],
                8,
            ),

        "entities":
            unique(
                data.get(
                    "entities"
                )
                or [],
                12,
            ),

        "queries": [
            short(q, 300)
            for q in queries[
                :MAX_SEARCHES
            ]
        ],
    }


# =========================================================
# TAVILY
# =========================================================

def tavily_search(query):

    r = requests.post(
        TAVILY_SEARCH_API,

        headers={
            "Authorization":
                f"Bearer {TAVILY_API_KEY}",
            "Content-Type":
                "application/json",
        },

        json={
            "query":
                short(query, 320),

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
        },

        timeout=35,
    )

    if r.status_code == 401:
        raise RuntimeError(
            "TAVILY_401"
        )

    if r.status_code == 429:
        raise RuntimeError(
            "TAVILY_429"
        )

    if r.status_code == 400:
        raise RuntimeError(
            "TAVILY_400: "
            + r.text[:500]
        )

    r.raise_for_status()

    out = []

    for item in (
        r.json()
        .get("results", [])
    ):

        url = clean_url(
            item.get("url")
            or ""
        )

        if not url:
            continue

        out.append(
            {
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

                "raw":
                    "",

                "score":
                    float(
                        item.get(
                            "score"
                        )
                        or 0
                    ),

                "published_date":
                    norm(
                        item.get(
                            "published_date"
                        )
                        or ""
                    ),
            }
        )

    return out


def source_priority(
    item,
    preferred_domain="",
):
    d = domain(
        item.get(
            "url",
            "",
        )
    )

    if preferred_domain:
        if (
            d == preferred_domain
            or d.endswith(
                "." + preferred_domain
            )
        ):
            return 0

    if (
        d in OFFICIAL_DOMAINS
        or ".gov." in d
        or d.endswith(".gov")
    ):
        return 1

    if d in TRUSTED_DOMAINS:
        return 2

    return 3


def gather_sources(
    plan,
    news_text,
    preferred_domain="",
):
    by_url = {}

    for i, query in enumerate(
        plan["queries"],
        1,
    ):
        print(
            f"Tavily {i}/"
            f"{len(plan['queries'])}: "
            f"{query}",
            flush=True,
        )

        results = tavily_search(
            query
        )

        for item in results:
            key = item[
                "url"
            ].lower()

            if (
                key not in by_url
                or item["score"]
                > by_url[key]["score"]
            ):
                by_url[key] = item

    # Добавляем ссылку из самого поста
    for raw in URL_RE.findall(
        news_text or ""
    ):

        url = clean_url(
            raw
        )

        d = domain(
            url
        )

        if not url:
            continue

        if d in {
            "t.me",
            "telegram.me",
            "telegram.org",
        }:
            continue

        if (
            url.lower()
            in by_url
        ):
            continue

        by_url[
            url.lower()
        ] = {
            "title":
                "Исходная ссылка",

            "url":
                url,

            "content":
                "",

            "raw":
                "",

            "score":
                1.0,

            "published_date":
                "",
        }

    sources = list(
        by_url.values()
    )

    sources.sort(
        key=lambda x: (
            source_priority(
                x,
                preferred_domain,
            ),
            -x["score"],
        )
    )

    selected = []
    seen_domains = set()

    # Сначала разные сайты
    for item in sources:

        d = domain(
            item["url"]
        )

        if d in seen_domains:
            continue

        selected.append(
            item
        )

        seen_domains.add(
            d
        )

        if (
            len(selected)
            >= MAX_AI_SOURCES
        ):
            break

    # Потом добираем
    for item in sources:

        if item in selected:
            continue

        selected.append(
            item
        )

        if (
            len(selected)
            >= MAX_AI_SOURCES
        ):
            break

    return selected


def tavily_extract(sources):

    urls = [
        x["url"]
        for x in sources[
            :MAX_EXTRACT_URLS
        ]
    ]

    if not urls:
        return

    r = requests.post(
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

    # Если лимит Extract —
    # продолжаем по сниппетам поиска.
    if r.status_code == 429:
        return

    if r.status_code == 401:
        raise RuntimeError(
            "TAVILY_401"
        )

    if r.status_code == 400:
        return

    r.raise_for_status()

    extracted = {}

    for item in (
        r.json()
        .get("results", [])
    ):

        url = clean_url(
            item.get("url")
            or ""
        )

        text = norm(
            item.get(
                "raw_content"
            )
            or item.get(
                "content"
            )
            or ""
        )

        if url and text:
            extracted[
                url.lower()
            ] = text

    for source in sources:

        source["raw"] = (
            extracted.get(
                source[
                    "url"
                ].lower(),
                "",
            )
        )


# =========================================================
# FINAL FACTCHECK
# =========================================================

def normalize_verdict(value):

    key = (
        norm(
            str(value or "")
        )
        .upper()
        .replace("-", "_")
        .replace(" ", "_")
    )

    aliases = {
        "TRUE":
            "TRUE",

        "CONFIRMED":
            "TRUE",

        "VERIFIED":
            "TRUE",

        "TRUE_NUANCE":
            "TRUE_NUANCE",

        "TRUE_WITH_NUANCE":
            "TRUE_NUANCE",

        "PARTLY_TRUE":
            "PARTLY_TRUE",

        "PARTIAL":
            "PARTLY_TRUE",

        "MISLEADING":
            "MISLEADING",

        "FALSE":
            "FALSE",

        "REFUTED":
            "FALSE",

        "UNCLEAR":
            "UNCLEAR",

        "UNKNOWN":
            "UNCLEAR",

        "INSUFFICIENT":
            "UNCLEAR",
    }

    return aliases.get(
        key,
        "",
    )


def source_blocks(
    sources,
    preferred_domain="",
):
    blocks = []
    total = 0

    for i, item in enumerate(
        sources,
        1,
    ):

        d = domain(
            item["url"]
        )

        p = source_priority(
            item,
            preferred_domain,
        )

        kind = {
            0:
                "названный/исходный источник",

            1:
                "официальный источник",

            2:
                "крупное СМИ",

            3:
                "локальный/обычный источник",
        }[p]

        evidence = (
            item.get("raw")
            or item.get("content")
            or ""
        )

        if item.get("raw"):
            evidence = evidence[:2200]
        else:
            evidence = evidence[:900]

        block = (
            f"[{i}]\n"
            f"Источник: {item['title']}\n"
            f"Домен: {d}\n"
            f"Тип: {kind}\n"
            f"Дата: "
            f"{item.get('published_date') or 'неизвестна'}\n"
            f"Текст: {evidence}"
        )

        if (
            total + len(block)
            > 12000
        ):
            break

        blocks.append(
            block
        )

        total += len(
            block
        )

    return "\n\n".join(
        blocks
    )


def repair_json(
    raw,
    source_count,
):
    prompt = f"""
Исправь этот ответ в валидный JSON.

Не добавляй новые факты.

Допустимый verdict:

TRUE
TRUE_NUANCE
PARTLY_TRUE
MISLEADING
FALSE
UNCLEAR

confidence:
целое число от 1 до 10.

used_sources:
номера источников от 1 до {source_count}.

ОТВЕТ:

{raw[:3500]}
""".strip()

    fixed = groq_text(
        "Верни только исправленный JSON.",
        prompt,
        max_tokens=500,
        stage="repair",
        json_mode=True,
        retries=1,
    )

    return parse_json(
        fixed
    )


def analyze(
    news_text,
    source_date_value,
    plan,
    sources,
    preferred_domain="",
):
    prompt = f"""
{date_context(source_date_value)}

ИСХОДНЫЙ ПОСТ:

{news_text[:MAX_POST_CHARS]}

ПЛАНЕР:

Центральный факт:
{plan["central_claim"]}

Второстепенные факты:
{json.dumps(plan["secondary_claims"], ensure_ascii=False)}

Мнения/оценки:
{json.dumps(plan["opinions"], ensure_ascii=False)}

Сарказм/риторика/ругательства:
{json.dumps(plan["nonliteral"], ensure_ascii=False)}

Сущности:
{json.dumps(plan["entities"], ensure_ascii=False)}

ИСТОЧНИКИ:

{source_blocks(sources, preferred_domain) or "Источников нет"}

ПЕРЕД ВЕРДИКТОМ ОБЯЗАТЕЛЬНО:

1. Сначала реши,
подтверждён ли центральный факт.

2. Потом отдельно оцени
второстепенные детали.

3. Не штрафуй новость
за эмоции, мат, сарказм,
риторические вопросы
и политические комментарии.

4. Локальный официальный источник
может полностью подтвердить
локальное событие.

5. Если главный факт подтверждён,
но одна важная деталь не подтверждена —
TRUE_NUANCE.

6. Если главный факт подтверждён,
а остальные неподтверждённые фразы
являются просто эмоциями автора —
TRUE.

7. FALSE только при прямом
опровержении центрального факта
и confidence >= 7.

Верни JSON по схеме system prompt.
""".strip()

    raw = groq_text(
        FINAL_SYSTEM,
        prompt,
        max_tokens=1100,
        stage="final",
        json_mode=True,
    )

    if not raw:
        raise RuntimeError(
            "Groq вернул пустой ответ"
        )

    print(
        "FINAL RAW:",
        raw[:2000],
        flush=True,
    )

    data = parse_json(
        raw
    )

    verdict = (
        normalize_verdict(
            data.get(
                "verdict"
            )
        )
        if data
        else ""
    )

    # Если модель сломала JSON —
    # пытаемся починить.
    if not verdict:

        try:
            data = repair_json(
                raw,
                len(sources),
            )

            verdict = (
                normalize_verdict(
                    data.get(
                        "verdict"
                    )
                )
                if data
                else ""
            )

        except Exception as exc:

            print(
                "JSON repair error:",
                exc,
                flush=True,
            )

            verdict = ""

    if not verdict:

        return (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "Источники нашлись, но модель сломала структурированный ответ. "
            "Это техническая ошибка, а не вердикт по новости.\n"
            "Уверенность: 4/10",

            sources[:3],
        )

    try:
        confidence = int(
            data.get(
                "confidence",
                5,
            )
        )

    except Exception:
        confidence = 5

    confidence = max(
        1,
        min(
            10,
            confidence,
        ),
    )

    # Защита от слишком смелого
    # обвинения новости во лжи.
    if (
        verdict == "FALSE"
        and confidence < 7
    ):
        verdict = "UNCLEAR"

    explanation = norm_lines(
        data.get(
            "explanation"
        )
        or ""
    )

    if not explanation:
        explanation = (
            "Модель не смогла нормально "
            "сформулировать пояснение."
        )

    used = []

    for raw_index in (
        data.get(
            "used_sources"
        )
        or []
    ):
        try:
            idx = int(
                raw_index
            )
        except Exception:
            continue

        if not (
            1 <= idx <= len(sources)
        ):
            continue

        item = sources[
            idx - 1
        ]

        if item not in used:
            used.append(
                item
            )

    if not used:
        used = sources[:3]

    answer = (
        f"{VERDICTS[verdict]}\n"
        f"{explanation[:2600]}\n"
        f"Уверенность: {confidence}/10"
    )

    return (
        answer[:3900],
        used,
    )


def factcheck(
    news_text,
    source_date_value="",
):
    # v11 специально меняем,
    # чтобы старые ответы кэша
    # не использовались.
    key = make_key(
        news_text,
        source_date_value
        + "|v11-central-claim",
    )

    cached = cache_get(
        key
    )

    if cached:
        print(
            "FACTCHECK CACHE HIT",
            flush=True,
        )

        return cached

    preferred_domain = (
        detect_preferred_domain(
            news_text
        )
    )

    plan = build_plan(
        news_text,
        source_date_value,
        preferred_domain,
    )

    print(
        "PLAN:",
        json.dumps(
            plan,
            ensure_ascii=False,
        )[:2500],
        flush=True,
    )

    sources = gather_sources(
        plan,
        news_text,
        preferred_domain,
    )

    if not sources:

        value = (
            "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"
            "По центральному факту не нашлось пригодных источников.\n"
            "Уверенность: 2/10",

            [],
        )

        cache_put(
            key,
            value,
        )

        return value

    tavily_extract(
        sources
    )

    value = analyze(
        news_text,
        source_date_value,
        plan,
        sources,
        preferred_domain,
    )

    cache_put(
        key,
        value,
    )

    return value


# =========================================================
# SOURCE BUTTONS
# =========================================================

def source_name(
    item,
    index,
):
    d = domain(
        item["url"]
    )

    for known, name in (
        SOURCE_NAMES.items()
    ):
        if (
            d == known
            or d.endswith(
                "." + known
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

    if len(title) > 30:
        title = (
            title[:27]
            .rstrip()
            + "…"
        )

    return (
        f"{index} · "
        f"{title or d}"
    )


def keyboard(sources):
    rows = []
    row = []

    for i, item in enumerate(
        sources[:6],
        1,
    ):
        url = (
            item.get("url")
            or ""
        )

        if not url.startswith(
            (
                "http://",
                "https://",
            )
        ):
            continue

        row.append(
            {
                "text":
                    source_name(
                        item,
                        i,
                    ),

                "url":
                    url,
            }
        )

        if len(row) == 2:
            rows.append(
                row
            )
            row = []

    if row:
        rows.append(
            row
        )

    if not rows:
        return None

    return {
        "inline_keyboard":
            rows
    }


# =========================================================
# ERRORS
# =========================================================

def friendly_error(exc):
    text = str(
        exc
    )

    if "GROQ_429" in text:
        return (
            "⏳ Groq упёрся в лимит. "
            "Попробуй ещё раз через несколько секунд."
        )

    if "GROQ_401" in text:
        return (
            "❌ Ошибка GROQ_API_KEY. "
            "Проверь переменную в Railway."
        )

    if "GROQ_413" in text:
        return (
            "❌ Слишком большой запрос для Groq."
        )

    if "GROQ_400" in text:
        return (
            "❌ Groq отклонил запрос. "
            "Подробности есть в логах Railway."
        )

    if "TAVILY_401" in text:
        return (
            "❌ Ошибка TAVILY_API_KEY. "
            "Проверь переменную в Railway."
        )

    if "TAVILY_429" in text:
        return (
            "⏳ Tavily упёрся в лимит. "
            "Попробуй позже."
        )

    if "TAVILY_400" in text:
        return (
            "❌ Tavily не принял поисковый запрос."
        )

    return (
        "❌ Не смог проверить новость. "
        "Посмотри логи Railway."
    )


# =========================================================
# HANDLER
# =========================================================

def handle_message(message):
    remember_media_text(
        message
    )

    chat = (
        message.get("chat")
        or {}
    )

    chat_id = chat.get(
        "id"
    )

    chat_type = (
        chat.get("type")
        or ""
    )

    message_id = message.get(
        "message_id"
    )

    raw = msg_text(
        message
    )

    if (
        not chat_id
        or not message_id
    ):
        return

    if raw.startswith(
        "/start"
    ):
        send_message(
            chat_id,

            "🐔 Chicken Company factcheck\n\n"
            "В группе: ответь «проверь» на новость.\n"
            "Можно и так: «проверь <текст>».\n"
            "В личке: просто перешли пост или отправь ссылку/текст.",

            message_id,
        )

        return

    request_data = None

    manual = parse_manual_check(
        message
    )

    if manual:

        if manual.get(
            "invalid_reply"
        ):
            send_message(
                chat_id,
                "Ответь «проверь» именно на новость/пост/скрин.",
                message_id,
            )

            return

        if media_done(
            message,
            "manual",
        ):
            return

        request_data = manual

    # В личке проверяем
    # любой текст/ссылку/пересланный пост.
    if (
        request_data is None
        and chat_type == "private"
    ):
        text = norm(
            extract_news_text(
                message
            )
        )

        if (
            (
                text
                and not text.startswith("/")
            )
            or is_forwarded(message)
            or message.get("photo")
        ):

            if media_done(
                message,
                "private",
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

                "source_message":
                    message,
            }

    # В группе автоматическая
    # проверка только при AUTO_CHECK=true.
    if (
        request_data is None
        and chat_type
        in {
            "group",
            "supergroup",
        }
        and AUTO_CHECK
    ):
        text = norm(
            extract_news_text(
                message
            )
        )

        if (
            URL_RE.search(text)
            or is_forwarded(message)
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

                "source_message":
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

    source_message = (
        request_data.get(
            "source_message"
        )
        or message
    )

    if (
        len(norm(news_text)) < 4
        and not source_message.get("photo")
    ):
        send_message(
            chat_id,

            "Не вижу, что проверять. "
            "Пришли текст/пост или ответь «проверь» на него.",

            message_id,
        )

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

    status = send_message(
        chat_id,

        "🔎 Ща отделю факты от эмоций и пробью источники…",

        reply_to,
    )

    status_id = (
        status.get("result")
        or {}
    ).get(
        "message_id"
    )

    try:

        check_text = news_text

        # OCR работает,
        # если в Railway указан VISION_MODEL.
        if (
            source_message.get("photo")
            and VISION_MODEL
        ):
            try:
                ocr = ocr_photo(
                    source_message
                )

                if ocr:
                    check_text += (
                        "\n\n"
                        "ТЕКСТ С ИЗОБРАЖЕНИЯ:\n"
                        + ocr
                    )

            except Exception as exc:

                print(
                    "OCR warning:",
                    type(exc).__name__,
                    exc,
                    flush=True,
                )

        if len(
            norm(check_text)
        ) < 4:
            raise RuntimeError(
                "На изображении не удалось получить текст"
            )

        answer, used = factcheck(
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
            "Factcheck error:",
            type(exc).__name__,
            exc,
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
            "Не заданы переменные: "
            + ", ".join(missing)
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
            "deleteWebhook warning:",
            exc,
            flush=True,
        )

    print(
        "Chicken Company bot V11 started; "
        "central_claim_logic=True; "
        "local_sources=True; "
        "structured_json=True; "
        f"auto_check={AUTO_CHECK}; "
        f"ocr={'ON' if VISION_MODEL else 'OFF'}",
        flush=True,
    )

    offset = None

    while True:

        try:

            payload = {
                "timeout":
                    30,

                "allowed_updates":
                    ["message"],
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

            for update in (
                data.get(
                    "result",
                    [],
                )
            ):

                update_id = (
                    update.get(
                        "update_id"
                    )
                )

                if isinstance(
                    update_id,
                    int,
                ):
                    offset = (
                        update_id + 1
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
                    "Telegram 409: другой экземпляр уже делает getUpdates. "
                    "В Railway оставь 1 replica/worker.",
                    flush=True,
                )

                time.sleep(
                    8
                )

                continue

            print(
                "Network error:",
                type(exc).__name__,
                exc,
                flush=True,
            )

            time.sleep(
                5
            )

        except Exception as exc:

            print(
                "Bot loop error:",
                type(exc).__name__,
                exc,
                flush=True,
            )

            time.sleep(
                5
            )


if __name__ == "__main__":
    main()