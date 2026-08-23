import os
import re
import time
import random
from urllib.parse import urlparse

import requests


# =========================
# НАСТРОЙКИ
# =========================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "").strip()

GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b").strip()
NIKOLAI_USER_ID = os.getenv("NIKOLAI_USER_ID", "").strip()

# false = бот сам НЕ фактчекает новости.
# При этом Колю на его новостях всё равно подкалывает.
AUTO_CHECK = os.getenv("AUTO_CHECK", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"
GROQ_API = "https://api.groq.com/openai/v1/chat/completions"
TAVILY_API = "https://api.tavily.com/search"

URL_RE = re.compile(
    r"https?://[^\s<>()]+",
    re.IGNORECASE
)

MAX_NEWS_CHARS = 3200
MAX_SEARCH_QUERY_CHARS = 650
MAX_AI_SOURCES = 5
MAX_TG_SOURCES = 4
MAX_SOURCE_SNIPPET_CHARS = 700

CHECK_WORDS = (
    "проверь",
    "проверить",
    "фактчек",
    "чекни",
    "проверка",
    "это правда",
    "это правда?",
)


SYSTEM_PROMPT = """
Ты фактчекер в дружеском пацанском Telegram-чате.

Тебе передают текст новости и результаты веб-поиска Tavily.
Проверяй только по этим результатам.
Ничего не выдумывай.

Правила:

- Первичные документы и официальные источники используй
  для проверки прямых фактов.

- Спорные заявления сверяй с независимыми надежными СМИ.

- Reuters, AP, AFP, BBC, Yle и другие крупные редакции
  ценнее случайных агрегаторов и Telegram-каналов.

- Если надежных подтверждений мало — так и скажи.

Используй РОВНО один вердикт:

🟢 НЕ ПИЗДЁЖ

🟡 ПОЛУПИЗДЁЖ

🟠 НАЕБАЛИ С КОНТЕКСТОМ

🔴 ПИЗДЁЖ

⚪ ХУЙ ПОЙМЁШЬ ПОКА


Формат ответа:

Первая строка — только вердикт.

После него 2–4 коротких предложения:
что реально подтверждается и где подвох.

Последняя строка:

Уверенность: N/10


Стиль:

- коротко;
- по-пацански;
- мат допустим;
- не пихай мат в каждое предложение;
- без канцелярита;
- без длинных лекций;
- не вставляй URL;
- список источников не пиши;
- ссылки бот покажет отдельными кнопками.

Не шути про:

- родителей;
- родственников;
- семью;
- детей;
- болезни;
- смерть;
- трагедии.
""".strip()


# =========================
# TELEGRAM
# =========================

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
    reply_markup=None
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
        payload
    )


def edit_message(
    chat_id,
    message_id,
    text,
    reply_markup=None
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
        payload
    )


# =========================
# ВСПОМОГАТЕЛЬНОЕ
# =========================

def normalize(text):

    return re.sub(
        r"\s+",
        " ",
        text or ""
    ).strip()


def message_text(message):

    return (
        message.get("text")
        or message.get("caption")
        or ""
    ).strip()


def is_nikolai(user):

    if not user:
        return False

    user_id = str(
        user.get(
            "id",
            ""
        )
    )

    # Если ID Коли прописан в Railway —
    # определяем его строго по ID.
    if NIKOLAI_USER_ID:

        return (
            user_id
            == NIKOLAI_USER_ID
        )

    # Запасной вариант,
    # пока ID Коли не прописан.
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

        for marker
        in markers
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


def is_forwarded(message):

    return bool(

        message.get("forward_origin")

        or message.get("forward_date")

        or message.get("forward_from")

        or message.get("forward_from_chat")
    )


def has_link(message):

    return bool(

        URL_RE.search(
            message_text(
                message
            )
        )
    )


def looks_like_news(message):

    return (
        is_forwarded(
            message
        )

        or has_link(
            message
        )
    )


# =========================
# РУЧНОЙ ФАКТЧЕК
# =========================

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

    # Если "Проверь" написано
    # ответом на сообщение —
    # проверяем именно это сообщение.
    #
    # НЕВАЖНО кто его прислал.
    if replied:

        return {

            "news_text":
                message_text(
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


# =========================
# TAVILY
# =========================

def build_search_query(
    news_text
):

    text = normalize(
        news_text
    )[:MAX_NEWS_CHARS]

    urls = URL_RE.findall(
        text
    )

    without_urls = normalize(

        URL_RE.sub(
            " ",
            text
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


def source_priority(url):

    domain = (
        urlparse(
            url
        )
        .netloc
        .lower()
        .removeprefix(
            "www."
        )
    )

    official_markers = (

        ".gov",
        "gov.",
        "europa.eu",
        "who.int",
        "un.org",
        "nato.int",
        "president.",
        "government.",
        "parliament.",
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

    if any(

        marker in domain

        for marker
        in official_markers
    ):

        return 0

    if any(

        domain.endswith(
            item
        )

        for item
        in wire_domains
    ):

        return 1

    if any(

        domain.endswith(
            item
        )

        for item
        in major_domains
    ):

        return 2

    return 3


def tavily_search(
    news_text
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

            "query":
                build_search_query(
                    news_text
                ),

            "search_depth":
                "basic",

            "topic":
                "general",

            "max_results":
                7,

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

    response.raise_for_status()

    data = response.json()

    results = []
    seen = set()

    for item in data.get(
        "results",
        []
    ):

        url = (
            item.get(
                "url"
            )
            or ""
        ).strip()

        if (
            not url
            or url in seen
        ):

            continue

        seen.add(
            url
        )

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

            "score":
                item.get(
                    "score"
                )
                or 0,
        })

    results.sort(

        key=lambda item: (

            source_priority(
                item["url"]
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


def sources_for_ai(
    results
):

    blocks = []

    for index, item in enumerate(

        results[
            :MAX_AI_SOURCES
        ],

        start=1
    ):

        snippet = item[
            "content"
        ][
            :MAX_SOURCE_SNIPPET_CHARS
        ]

        blocks.append(

            f"[{index}]\n"

            f"Название: "
            f"{item['title']}\n"

            f"URL: "
            f"{item['url']}\n"

            f"Фрагмент: "
            f"{snippet}"
        )

    return "\n\n".join(
        blocks
    )


# =========================
# GROQ
# =========================

def groq_analyze(
    news_text,
    results
):

    prompt = (

        f"{SYSTEM_PROMPT}\n\n"

        "НОВОСТЬ:\n"

        f"{news_text[:MAX_NEWS_CHARS]}"

        "\n\n"

        "РЕЗУЛЬТАТЫ ПОИСКА:\n"

        f"{sources_for_ai(results)}"

        "\n\n"

        "Дай короткий фактчек "
        "строго в заданном формате."
    )


    def request_once(
        max_tokens
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
                            "user",

                        "content":
                            prompt,
                    },
                ],

                "temperature":
                    0.25,

                "reasoning_effort":
                    "low",

                "include_reasoning":
                    False,

                "max_completion_tokens":
                    max_tokens,

                "stream":
                    False,
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


        message = (
            choices[0]
            .get(
                "message"
            )
            or {}
        )

        return (
            message
            .get(
                "content"
            )
            or ""
        ).strip()


    # Первый запрос
    text = request_once(
        1200
    )


    # Если Groq вдруг вернул пустой content,
    # автоматически пробуем ещё один раз.
    if not text:

        print(
            "Groq returned empty content; retrying once...",
            flush=True,
        )

        text = request_once(
            1800
        )


    if not text:

        raise RuntimeError(
            "Groq дважды вернул пустой текст"
        )


    return text[:3900]


# =========================
# КОМПАКТНЫЕ ИСТОЧНИКИ
# =========================

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
}


def source_button_name(
    item,
    index
):

    domain = (

        urlparse(
            item["url"]
        )
        .netloc
        .lower()
        .removeprefix(
            "www."
        )
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
                f"{index} · {name}"
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


def source_keyboard(
    results
):

    buttons = []


    for index, item in enumerate(

        results[
            :MAX_TG_SOURCES
        ],

        start=1
    ):

        buttons.append({

            "text":
                source_button_name(
                    item,
                    index
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
        2
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


# =========================
# ФАКТЧЕК
# =========================

def factcheck(
    news_text
):

    results = tavily_search(
        news_text
    )


    if not results:

        return (

            (
                "⚪ ХУЙ ПОЙМЁШЬ ПОКА\n"

                "Нормальных подтверждений "
                "не нашлось. "

                "Без источников уверенно "
                "рубить вердикт было бы "
                "пиздежом уже с моей стороны.\n"

                "Уверенность: 2/10"
            ),

            []
        )


    answer = groq_analyze(
        news_text,
        results
    )


    return (
        answer,
        results
    )


def friendly_error(
    exc
):

    text = str(
        exc
    )


    if "TAVILY_401" in text:

        return (
            "Tavily не пускает по ключу. "
            "Проверь TAVILY_API_KEY "
            "в Railway."
        )


    if "TAVILY_429" in text:

        return (
            "У Tavily закончился лимит "
            "или прилетел rate limit."
        )


    if "GROQ_401" in text:

        return (
            "Groq не пускает по ключу. "
            "Проверь GROQ_API_KEY "
            "в Railway."
        )


    if "GROQ_429" in text:

        return (
            "Groq упёрся в лимит. "
            "Чуть позже попробуй ещё раз."
        )


    return (
        "Чёт фактчек наебнулся. "
        "Ошибку я кинул в лог Railway."
    )


# =========================
# ОБРАБОТКА СООБЩЕНИЙ
# =========================

def handle_message(
    message
):

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


    # =========================
    # /id
    # =========================

    if re.match(

        r"^/(?:id|whoami)"
        r"(?:@[A-Za-z0-9_]+)?"
        r"(?:\s|$)",

        raw,

        flags=re.IGNORECASE,
    ):

        send_message(

            chat_id,

            (
                "Твой Telegram ID: "
                f"{from_user.get('id', 'неизвестно')}"
            ),

            message_id,
        )

        return


    # =========================
    # СНАЧАЛА ФАКТЧЕК
    # =========================

    request_data = parse_manual_check(
        message
    )


    if request_data is not None:

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


    # =========================
    # КОЛЯ КИДАЕТ НОВОСТЬ
    # =========================

    # Если фактчек никто НЕ просил,
    # а Коля просто прислал:
    #
    # - пересланную новость
    # или
    # - ссылку
    #
    # Tavily и Groq НЕ запускаем.
    # Просто подкалываем.

    if (
        request_data is None

        and is_nikolai(
            from_user
        )

        and looks_like_news(
            message
        )
    ):

        send_message(

            chat_id,

            kolya_roast(),

            message_id,
        )

        return


    # =========================
    # АВТОФАКТЧЕК
    # =========================

    if (
        request_data is None

        and AUTO_CHECK

        and looks_like_news(
            message
        )
    ):

        request_data = {

            "news_text":
                message_text(
                    message
                ),

            "source_message_id":
                message_id,
        }


    # Если никто не просил фактчек —
    # молчим.

    if request_data is None:

        return


    # =========================
    # ЗАПУСК ФАКТЧЕКА
    # =========================

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
            {}
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


# =========================
# ПРОВЕРКА ПЕРЕМЕННЫХ
# =========================

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


# =========================
# ЗАПУСК БОТА
# =========================

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
            "search=Tavily"
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
                []
            ):

                update_id = update.get(
                    "update_id"
                )


                if isinstance(
                    update_id,
                    int
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