import asyncio
import logging

from aiogram import Router, F, Bot
from aiogram.filters import CommandStart
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton,
    ChatPermissions,
)

import rofl
import storage
from config import CAPTCHA_TIMEOUT, MAX_ATTEMPTS

router = Router()
log = logging.getLogger(__name__)


def _key(chat_id: int, user_id: int) -> str:
    return f"{chat_id}:{user_id}"


def _captcha_text(name: str, q: dict) -> str:
    return (
        f"👋 <b>{name}</b>, докажи, что ты не бот!\n\n"
        f"❓ <b>{q['q']}</b>\n\n"
        f"⏱ Время: {CAPTCHA_TIMEOUT} сек. Попыток: {MAX_ATTEMPTS}"
    )


def _captcha_kb(options) -> InlineKeyboardMarkup:
    rows = []
    for i, opt in enumerate(options):
        rows.append([InlineKeyboardButton(text=opt, callback_data=f"cap:{i}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def _send_captcha(bot: Bot, chat_id: int, user_id: int, name: str, scope: str):
    q = rofl.get_question()
    key = _key(chat_id, user_id)
    storage.pending[key] = {
        "chat_id": chat_id,
        "user_id": user_id,
        "message_id": None,
        "correct": q["correct"],
        "attempts": 0,
        "scope": scope,
        "name": name,
    }
    storage.save()
    try:
        msg = await bot.send_message(
            chat_id=chat_id,
            text=_captcha_text(name, q),
            reply_markup=_captcha_kb(q["options"]),
        )
    except Exception as e:
        log.warning(f"send captcha failed in {chat_id}: {e}")
        storage.pending.pop(key, None)
        storage.save()
        return
    storage.pending[key]["message_id"] = msg.message_id
    storage.save()
    asyncio.create_task(_timeout_task(bot, chat_id, user_id, msg.message_id))


async def _start_captcha(bot: Bot, chat_id: int, user_id: int, name: str, scope: str):
    """Запустить капчу, снеся старую активную (если была)."""
    key = _key(chat_id, user_id)
    old = storage.pending.get(key)
    if old and old.get("message_id"):
        try:
            await bot.delete_message(old["chat_id"], old["message_id"])
        except Exception:
            pass
        storage.pending.pop(key, None)
        storage.save()
    await _send_captcha(bot, chat_id, user_id, name, scope)


async def _timeout_task(bot: Bot, chat_id: int, user_id: int, message_id: int):
    await asyncio.sleep(CAPTCHA_TIMEOUT)
    key = _key(chat_id, user_id)
    data = storage.pending.get(key)
    if not data or data.get("message_id") != message_id:
        return
    storage.pending.pop(key, None)
    storage.save()
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception:
        pass
    if data["scope"] == "group":
        try:
            await bot.ban_chat_member(chat_id, user_id)
            await bot.unban_chat_member(chat_id, user_id)
        except Exception as e:
            log.warning(f"timeout kick failed: {e}")
        try:
            await bot.send_message(
                chat_id,
                f"⏱ {data['name']} не прошёл капчу за {CAPTCHA_TIMEOUT} сек. Пока.",
            )
        except Exception:
            pass
    else:
        try:
            await bot.send_message(
                chat_id,
                "⏱ Время вышло. Напиши любое сообщение, чтобы получить новую капчу.",
            )
        except Exception:
            pass


@router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    await _start_captcha(
        bot, message.chat.id, message.from_user.id,
        message.from_user.full_name, "private",
    )


# НОВОЕ: любое текстовое сообщение в личке → новая капча, если активной нет
@router.message(F.chat.type == "private", F.text)
async def on_private_text(message: Message, bot: Bot):
    if message.text.startswith("/"):
        return  # команды пропускаем
    key = _key(message.chat.id, message.from_user.id)
    if key in storage.pending:
        return  # уже есть активная капча — не спамим
    await _start_captcha(
        bot, message.chat.id, message.from_user.id,
        message.from_user.full_name, "private",
    )


@router.message(F.new_chat_members)
async def on_new_members(message: Message, bot: Bot):
    for member in message.new_chat_members:
        if member.is_bot:
            continue
        try:
            await bot.restrict_chat_member(
                chat_id=message.chat.id,
                user_id=member.id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        except Exception as e:
            log.warning(f"mute failed: {e} (бот админ с правом ограничивать?)")
        await _start_captcha(bot, message.chat.id, member.id, member.full_name, "group")


@router.callback_query(F.data.startswith("cap:"))
async def on_answer(callback: CallbackQuery, bot: Bot):
    try:
        idx = int(callback.data.split(":", 1)[1])
    except Exception:
        await callback.answer("Кривая кнопка", show_alert=True)
        return

    chat_id = callback.message.chat.id
    user_id = callback.from_user.id
    key = _key(chat_id, user_id)
    data = storage.pending.get(key)

    if not data or data.get("message_id") != callback.message.message_id:
        await callback.answer("Эта капча неактуальна", show_alert=True)
        return

    if idx == data["correct"]:
        storage.pending.pop(key, None)
        storage.save()
        phrase = rofl.success_phrase()
        hint = "Напиши любое сообщение, чтобы пройти ещё одну." if data["scope"] == "private" else ""
        text = f"✅ <b>{callback.from_user.full_name}</b> — человек. {phrase}"
        if hint:
            text += f"\n\n{hint}"
        try:
            await callback.message.edit_text(text, reply_markup=None)
        except Exception:
            pass
        await callback.answer(phrase)
        if data["scope"] == "group":
            try:
                await bot.restrict_chat_member(
                    chat_id=data["chat_id"],
                    user_id=data["user_id"],
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True,
                    ),
                )
            except Exception as e:
                log.warning(f"unmute failed: {e}")
        return

    data["attempts"] += 1
    if data["attempts"] >= MAX_ATTEMPTS:
        storage.pending.pop(key, None)
        storage.save()
        phrase = rofl.kick_phrase()
        try:
            await callback.message.edit_text(
                f"❌ <b>{callback.from_user.full_name}</b> не прошёл капчу. {phrase}",
                reply_markup=None,
            )
        except Exception:
            pass
        await callback.answer(phrase, show_alert=True)
        if data["scope"] == "group":
            try:
                await bot.ban_chat_member(data["chat_id"], data["user_id"])
                await bot.unban_chat_member(data["chat_id"], data["user_id"])
            except Exception as e:
                log.warning(f"kick failed: {e}")
        else:
            try:
                await bot.send_message(
                    data["chat_id"],
                    "Напиши любое сообщение, чтобы попробовать ещё раз.",
                )
            except Exception:
                pass
    else:
        storage.save()
        left = MAX_ATTEMPTS - data["attempts"]
        await callback.answer(
            f"{rofl.fail_phrase()} Осталось попыток: {left}",
            show_alert=True,
        )
