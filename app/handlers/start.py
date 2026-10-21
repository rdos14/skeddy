"""/start, /help and /timezone."""

from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from app.database.repository import UserRepository
from app.services.scheduler import is_valid_timezone

router = Router(name="start")

WELCOME = (
    "👋 Hello! I'm <b>Skeddy</b>, your reminder bot.\n\n"
    "Tell me what to remind you about and when:\n\n"
    "• <i>tomorrow at 09:00 call the dentist</i>\n"
    "• <i>every day at 22:00 drink water</i>\n"
    "• <i>every monday at 10:00 send the report</i>\n"
    "• <i>in 30 min check the kettle</i>\n\n"
    "📋 /list — active reminders\n"
    "🌍 /timezone — view or change your timezone\n"
    "❓ /help — examples and instructions"
)

HELP = (
    "<b>How Skeddy works</b>\n\n"
    "Send a message describing what to remember and when. "
    "The parser supports English, Uzbek and bounded Spanish dates.\n\n"
    "<b>One-time reminders</b>\n"
    "• <code>tomorrow at 09:00 call the dentist</code>\n"
    "• <code>today at 18:00 check the server</code>\n"
    "• <code>in 30 min take a break</code>\n"
    "• <code>27.09 at 15:30 pay the bill</code>\n\n"
    "<b>Recurring reminders</b>\n"
    "• <code>every day at 08:00 exercise</code>\n"
    "• <code>every monday at 10:00 send the report</code>\n"
    "• <code>every hour stretch</code>\n"
    "• <code>every 15 min check the oven</code>\n\n"
    "<b>Manage reminders</b>: /list, then use the delete button.\n"
    "<b>Timezone</b>: <code>/timezone America/Mexico_City</code>\n"
    "For durations, use digits or 'one' (for example, in one minute).\n"
    "<b>Spanish: date + explicit time required</b>\n"
    "• <code>mañana a las 10am revisar equipo</code>\n"
    "• <code>próximo sábado a las 830am revisar equipo</code>\n"
    "• <code>30 de julio a las 9:00 a. m. revisar equipo</code>\n"
    "'próximo' excludes today; 'este' means the current week. "
    "Past 'hoy/este' times are rejected. No default hour is chosen.\n"
    "English one-off 'next weekday', Spanish recurrence/fractional phrases, "
    "and voice messages are not supported yet."
)


@router.message(Command("start"))
async def cmd_start(message: Message, users: UserRepository, default_tz: str) -> None:
    await users.get_or_create(message.chat.id, default_tz)
    await message.answer(WELCOME)


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    await message.answer(HELP)


@router.message(Command("timezone"))
async def cmd_timezone(
    message: Message,
    command: CommandObject,
    users: UserRepository,
    default_tz: str,
) -> None:
    tz = (command.args or "").strip()
    if not tz:
        user = await users.get_or_create(message.chat.id, default_tz)
        await message.answer(
            f"Current timezone: <code>{user.timezone}</code>\n"
            "To change it: <code>/timezone America/Mexico_City</code>"
        )
        return
    if not is_valid_timezone(tz):
        await message.answer(
            "Invalid timezone. Example: <code>America/Mexico_City</code>."
        )
        return
    await users.get_or_create(message.chat.id, default_tz)
    await users.set_timezone(message.chat.id, tz)
    await message.answer(f"✅ Timezone set to <code>{tz}</code>.")
