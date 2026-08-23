import os
import time
import requests
from openai import OpenAI

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

TG_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

client = OpenAI(api_key=OPENAI_API_KEY)

SYSTEM_PROMPT = """
Ты — фактчекер в небольшом дружеском Telegram-чате из трёх друзей.

Твоя задача — проверять новости, слухи, заявления, посты из Telegram,
СМИ и соцсетей.

Перед вердиктом ОБЯЗАТЕЛЬНО используй веб-поиск.

Проверь:
- произошло ли событие;
- актуальна ли дата;
- есть ли первоисточник;
- подтверждают ли информацию независимые источники;
- не вырван ли факт из контекста;
- не раздут ли заголовок;
- не является ли старое событие новой сенсацией;
- не является ли это слухом или прогнозом.

Вердикты:

🟢 ПОДТВЕРЖДЕНО
🟡 ПРАВДА, НО РАЗДУТО
🟠 МАНИПУЛЯЦИЯ / НЕТ КОНТЕКСТА
🔴 ФЕЙК
⚪ ХРЕН ЕГО ЗНАЕТ — МАЛО ИНФОРМАЦИИ

Стиль:
Ты четвёртый кореш в компании.
Пиши коротко, разговорно и по-пацански.
Можно материться, подкалывать и использовать сарказм.

Мат должен звучать естественно.
Не надо вставлять мат в каждое предложение.

Можно писать:
"раздули пиздец"
"хуйня какая-то"
"кликбейт ебаный"
"высосано из пальца"
"ну тут нихуя не доказано"
"инфопомойка"
"наброс"

Запрещены подколы про:
- родителей;
- родственников;
- детей;
- семью;
- болезни;
- смерть;
- реальные трагедии.

Если сообщение отправил Николай,
можешь дружески называть его:
"либераха"
"Коля-либераха"
"либераха Николай"

Не используй это обращение к другим людям.

Важно:
Мат и стёб не должны влиять на точность фактчекинга.
Если информации недостаточно — прямо скажи об этом.
Не выдумывай факты.

Формат:

[ВЕРДИКТ]

Короткое объяснение.

Что реально:
...

Где наебали / раздули:
...

Раздутость: X/10
Уверенность: X/10

Источники:
2–4 нормальных источника.
"""


def tg(method, data=None):
    response = requests.post(
        f"{TG_API}/{method}",
        json=data or {},
        timeout=60,
    )
    return response.json()


def send_message(chat_id, text, reply_to=None):
    data = {
        "chat_id": chat_id,
        "text": text[:4000],
    }

    if reply_to:
        data["reply_parameters"] = {
            "message_id": reply_to,
        }

    tg("sendMessage", data)


def check_news(text, sender_name):
    prompt = f"""
Проверь эту новость.

Текст новости:
{text}

Имя отправителя:
{sender_name}
"""

    response = client.responses.create(
        model="gpt-5.6",
        tools=[
            {
                "type": "web_search",
                "search_context_size": "high",
            }
        ],
        input=[
            {
                "role": "system",
                "content": SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": prompt,
            },
        ],
    )

    return response.output_text


def handle_message(message):
    text = message.get("text", "").strip()

    if not text:
        return

    command = text.lower()

    triggers = [
        "проверь",
        "/check",
        "фактчек",
        "это правда?",
    ]

    if not any(trigger in command for trigger in triggers):
        return

    chat_id = message["chat"]["id"]
    replied = message.get("reply_to_message")

    if not replied:
        send_message(
            chat_id,
            "Ответь словом «проверь» на сообщение с новостью.",
            message["message_id"],
        )
        return

    news_text = replied.get("text") or replied.get("caption")

    if not news_text:
        send_message(
            chat_id,
            "Пока нормально умею проверять текст и ссылки.",
            message["message_id"],
        )
        return

    sender = replied.get("from", {})

    sender_name = (
        sender.get("first_name")
        or sender.get("username")
        or "неизвестно кто"
    )

    send_message(
        chat_id,
        "🔎 Ща гляну, что за хуйня...",
        message["message_id"],
    )

    try:
        result = check_news(news_text, sender_name)

        send_message(
            chat_id,
            result,
            replied["message_id"],
        )

    except Exception as e:
        print("OpenAI error:", e)

        send_message(
            chat_id,
            "Чёт я обосрался при проверке. Попробуйте ещё раз 😄",
            message["message_id"],
        )


def main():
    offset = None

    print("Chicken Company bot started")

    while True:
        try:
            params = {
                "timeout": 30,
            }

            if offset is not None:
                params["offset"] = offset

            response = requests.get(
                f"{TG_API}/getUpdates",
                params=params,
                timeout=40,
            ).json()

            for update in response.get("result", []):
                offset = update["update_id"] + 1

                message = update.get("message")

                if message:
                    handle_message(message)

        except Exception as e:
            print("Telegram error:", e)
            time.sleep(3)


if __name__ == "__main__":
    main()