from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from typing import Dict, Iterable, List, Tuple

import pytz
from telegram import ReplyKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from .booking_store import BookingStore, BookingRequest
from .config import Settings, load_settings
from .keyboards import (
    build_admin_cancel_keyboard,
    build_admin_cancel_reason_keyboard,
    build_cancel_reason_keyboard,
    build_cancel_select_keyboard,
    build_dates_keyboard,
    build_decline_reason_keyboard,
    build_request_review_keyboard,
    build_times_keyboard,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


settings: Settings = load_settings()
store = BookingStore(settings=settings)
timezone = pytz.timezone(settings.timezone)
daily_slots = []
CLIENT_CANCELABLE_STATUSES = {"pending", "confirmed"}
TRAINER_CANCELABLE_STATUSES = {"pending", "confirmed"}
STATUS_BADGES = {
    "pending": "⌛ Ожидает подтверждения",
    "confirmed": "✅ Подтверждена",
    "cancelled_by_trainer": "🚫 Отменена тренером",
    "cancelled_by_client": "🚫 Отменена клиентом",
    "declined": "❌ Отклонена",
}
BUTTON_BOOK = "📅 Записаться"
BUTTON_MY = "🗓 Мои записи"
BUTTON_TRAINER = "📘 Записи тренера"
MENU_BUTTONS = {BUTTON_BOOK, BUTTON_MY, BUTTON_TRAINER}
DATES_PAGE_SIZE = 6


def is_instructor(user_id: int) -> bool:
    return user_id == settings.instructor_chat_id


def build_main_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    if is_instructor(user_id):
        rows = [[BUTTON_TRAINER]]
    else:
        rows = [[BUTTON_BOOK, BUTTON_MY]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)

MONTHS_RU_GEN = [
    "января",
    "февраля",
    "марта",
    "апреля",
    "мая",
    "июня",
    "июля",
    "августа",
    "сентября",
    "октября",
    "ноября",
    "декабря",
]
MONTHS_RU_SHORT = [
    "янв",
    "фев",
    "мар",
    "апр",
    "мая",
    "июн",
    "июл",
    "авг",
    "сен",
    "окт",
    "ноя",
    "дек",
]
WEEKDAYS_RU_FULL = [
    "понедельник",
    "вторник",
    "среда",
    "четверг",
    "пятница",
    "суббота",
    "воскресенье",
]
WEEKDAYS_RU_SHORT = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def _generate_daily_slots() -> List[str]:
    slots: List[str] = []
    slot_delta = timedelta(minutes=settings.slot_duration_minutes)
    cursor = datetime.combine(date.today(), time(hour=settings.work_start_hour))
    end_time = time(hour=settings.work_end_hour)
    while cursor.time() < end_time:
        slots.append(cursor.strftime("%H:%M"))
        cursor += slot_delta
        if cursor.time() == time(0, 0):
            break
    return slots


daily_slots = _generate_daily_slots()


def collect_available_dates_with_labels() -> List[Tuple[date, str]]:
    cleanup_expired_requests()
    today = datetime.now(timezone).date()
    result: List[Tuple[date, str]] = []
    for offset in range(settings.booking_horizon_days):
        candidate = today + timedelta(days=offset)
        if candidate.weekday() in settings.workdays:
            result.append((candidate, format_day_short(candidate)))
    return result


def format_day_short(day: date) -> str:
    return f"{day.day:02d} {MONTHS_RU_SHORT[day.month - 1]} ({WEEKDAYS_RU_SHORT[day.weekday()]})"


def format_day_full(day: date) -> str:
    return f"{day.day:02d} {MONTHS_RU_GEN[day.month - 1]} ({WEEKDAYS_RU_FULL[day.weekday()]})"


def find_dates_and_page(date_str: str) -> Tuple[List[Tuple[date, str]], int, bool]:
    dates = collect_available_dates_with_labels()
    page = 0
    found = False
    for idx, (day, _) in enumerate(dates):
        if day.isoformat() == date_str:
            page = idx // DATES_PAGE_SIZE
            found = True
            break
    return dates, page, found


def humanize_slot(date_str: str, time_str: str) -> str:
    dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    localized = timezone.localize(dt)
    return f"{format_day_full(localized.date())} · {localized.strftime('%H:%M')}"


def build_cancel_options(requests: List[BookingRequest]) -> List[Tuple[str, str]]:
    options: List[Tuple[str, str]] = []
    for req in requests:
        status_text = STATUS_BADGES.get(req.status, "")
        label = f"{status_text} · {humanize_slot(req.date, req.time)}" if status_text else humanize_slot(req.date, req.time)
        options.append((req.id, label))
    return options


def cleanup_expired_requests() -> None:
    now_local = datetime.now(timezone).replace(tzinfo=None)
    store.cleanup_expired(now_local)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await update.message.reply_text(
        "Привет! Я помогу записаться на индивидуальную тренировку.\n"
        "Нажми «📅 Записаться», чтобы выбрать дату и время (1 час).\n"
        "В разделе «🗓 Мои записи» можно увидеть активные заявки и отменить их.",
        reply_markup=build_main_keyboard(user.id),
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Алгоритм записи:\n"
        "1. Кнопка «📅 Записаться» — выбираешь день и свободный час.\n"
        "2. Я отправляю запрос тренеру.\n"
        "3. После подтверждения приходит уведомление.\n"
        "4. Кнопка «🗓 Мои записи» — посмотреть активные заявки и отменить их.\n\n"
        "Если нужна другая длительность или есть вопросы, напиши тренеру напрямую.",
        reply_markup=build_main_keyboard(update.effective_user.id),
    )


async def start_booking(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_instructor(user.id):
        await update.message.reply_text(
            "Тренеру недоступна запись. Используйте кнопку «📘 Записи тренера».",
            reply_markup=build_main_keyboard(user.id),
        )
        return
    dates = collect_available_dates_with_labels()
    if not dates:
        await update.message.reply_text(
            "На ближайшее время нет рабочих дней для записи. Попробуйте позже.",
            reply_markup=build_main_keyboard(user.id),
        )
        return
    keyboard = build_dates_keyboard(dates, page=0, page_size=DATES_PAGE_SIZE)
    await update.message.reply_text(
        "Выбери подходящий день:",
        reply_markup=keyboard,
    )


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if is_instructor(user.id):
        await update.message.reply_text(
            "Эта функция доступна только клиентам. Используйте «📘 Записи тренера».",
            reply_markup=build_main_keyboard(user.id),
        )
        return
    cleanup_expired_requests()
    requests = [
        req
        for req in store.list_user_requests(user.id)
        if req.status in CLIENT_CANCELABLE_STATUSES
    ]
    if not requests:
        await update.message.reply_text(
            "У вас нет активных записей, которые можно отменить.",
            reply_markup=build_main_keyboard(user.id),
        )
        return
    keyboard = build_cancel_select_keyboard(build_cancel_options(requests))
    await update.message.reply_text(
        "Выберите запись, которую хотите отменить:",
        reply_markup=keyboard,
    )


async def show_instructor_bookings(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_instructor(update.effective_user.id):
        await update.message.reply_text(
            "Только тренер может просматривать этот список.",
            reply_markup=build_main_keyboard(update.effective_user.id),
        )
        return
    cleanup_expired_requests()
    requests = store.list_all_requests()
    now = datetime.now(timezone)
    lines: List[str] = []
    options: List[Tuple[str, str]] = []
    for req in requests:
        slot_dt = timezone.localize(datetime.strptime(f"{req.date} {req.time}", "%Y-%m-%d %H:%M"))
        if slot_dt < now:
            continue
        status = STATUS_BADGES.get(req.status, req.status)
        lines.append(f"{humanize_slot(req.date, req.time)} — {req.full_name} ({status})")
        if req.status in TRAINER_CANCELABLE_STATUSES:
            label = f"{humanize_slot(req.date, req.time)} · {req.full_name}"
            options.append((req.id, label))
    if lines:
        await update.message.reply_text(
            "\n".join(lines),
            reply_markup=build_main_keyboard(update.effective_user.id),
        )
    else:
        await update.message.reply_text(
            "Нет активных записей. Заявки появятся после выбора времени клиентом.",
            reply_markup=build_main_keyboard(update.effective_user.id),
        )
    if options:
        await update.message.reply_text(
            "Выбери запись, чтобы отменить её:",
            reply_markup=build_admin_cancel_keyboard(options),
        )


async def date_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    _, date_str = query.data.split("|", maxsplit=1)
    dates, page, found = find_dates_and_page(date_str)
    if not found:
        await query.edit_message_text(
            "Эта дата больше недоступна. Выберите заново:",
            reply_markup=build_dates_keyboard(dates, page=0, page_size=DATES_PAGE_SIZE),
        )
        return
    day_label = format_day_full(datetime.strptime(date_str, "%Y-%m-%d").date())
    busy_map = store.list_day_states(date_str)
    free_slots = [
        slot
        for slot in daily_slots
        if slot not in busy_map or busy_map[slot] not in {"pending", "confirmed"}
    ]
    keyboard = build_times_keyboard(date_str, free_slots, back_page=page)
    await query.edit_message_text(
        text=f"Свободные часы на {day_label}:",
        reply_markup=keyboard,
    )


async def back_to_dates(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    parts = query.data.split("|", maxsplit=1)
    page = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
    dates = collect_available_dates_with_labels()
    max_page = max((len(dates) - 1) // DATES_PAGE_SIZE, 0)
    page = max(0, min(page, max_page))
    if not dates:
        await query.edit_message_text(
            "На ближайшие даты запись недоступна. Попробуйте позже.",
            reply_markup=build_main_keyboard(query.from_user.id),
        )
        return
    await query.edit_message_text(
        "Выбери подходящий день:",
        reply_markup=build_dates_keyboard(dates, page=page, page_size=DATES_PAGE_SIZE),
    )


async def time_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, date_str, time_str = query.data.split("|", maxsplit=2)

    slot_dt = timezone.localize(datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M"))
    if slot_dt < datetime.now(timezone):
        await query.answer("Нельзя выбрать прошедшее время", show_alert=True)
        return

    dates, page, _ = find_dates_and_page(date_str)
    user = query.from_user
    try:
        request = store.create_request(
            user_id=user.id,
            username=user.username,
            full_name=user.full_name,
            date_str=date_str,
            time_str=time_str,
        )
    except ValueError:
        await query.answer("Слот уже занят. Выбери другой.", show_alert=True)
        await query.edit_message_text(
            "Этот час уже занят. Выбери другую дату:",
            reply_markup=build_dates_keyboard(dates, page=page, page_size=DATES_PAGE_SIZE),
        )
        return

    await query.edit_message_text(
        f"Запрос на {humanize_slot(date_str, time_str)} отправлен тренеру.\n"
        "Я напомню, когда он подтвердит запись."
    )

    admin_text = (
        "<b>Новая заявка</b>\n"
        f"Дата: {humanize_slot(date_str, time_str)}\n"
        f"Клиент: {user.full_name} "
        f"(@{user.username or 'нет'} | id {user.id})"
    )
    message = await context.bot.send_message(
        chat_id=settings.instructor_chat_id,
        text=admin_text,
        parse_mode=ParseMode.HTML,
        reply_markup=build_request_review_keyboard(request.id),
    )


async def cancel_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, request_id = query.data.split("|", maxsplit=1)
    user = query.from_user
    try:
        request = store.get_request(request_id)
    except KeyError:
        await query.edit_message_text("Запись не найдена.")
        return
    if request.user_id != user.id:
        await query.answer("Эта запись принадлежит другому пользователю.", show_alert=True)
        return
    if request.status not in CLIENT_CANCELABLE_STATUSES:
        await query.edit_message_text("Эту запись уже нельзя отменить.")
        return

    context.user_data["awaiting_cancel_reason"] = {
        "request_id": request_id,
        "message_chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }
    await query.edit_message_text(
        f"Укажите причину отмены записи на {humanize_slot(request.date, request.time)} (по желанию) "
        "или нажмите кнопку ниже.",
        reply_markup=build_cancel_reason_keyboard(request_id),
    )


async def admin_cancel_select_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_instructor(query.from_user.id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    await query.answer()
    _, request_id = query.data.split("|", maxsplit=1)
    try:
        request = store.get_request(request_id)
    except KeyError:
        await query.edit_message_text("Запись не найдена.")
        return
    if request.status not in TRAINER_CANCELABLE_STATUSES:
        await query.edit_message_text("Эту запись уже нельзя отменить.")
        return
    context.chat_data["awaiting_admin_cancel"] = {
        "request_id": request_id,
        "message_chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }
    await query.edit_message_text(
        f"Напишите причину отмены тренировки {humanize_slot(request.date, request.time)} (по желанию)\n"
        "или нажмите кнопку ниже.",
        reply_markup=build_admin_cancel_reason_keyboard(request_id),
    )


async def dates_page_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, page_str = query.data.split("|", maxsplit=1)
    page = int(page_str) if page_str.isdigit() else 0
    dates = collect_available_dates_with_labels()
    max_page = max((len(dates) - 1) // DATES_PAGE_SIZE, 0)
    page = max(0, min(page, max_page))
    if not dates:
        await query.edit_message_text(
            "Нет доступных дат. Попробуйте позже.",
            reply_markup=build_main_keyboard(query.from_user.id),
        )
        return
    await query.edit_message_text(
        "Выбери подходящий день:",
        reply_markup=build_dates_keyboard(dates, page=page, page_size=DATES_PAGE_SIZE),
    )


async def review_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != settings.instructor_chat_id:
        await query.answer("Только тренер может управлять заявками", show_alert=True)
        return

    await query.answer()
    _, request_id, action = query.data.split("|", maxsplit=2)
    try:
        request = store.get_request(request_id)
    except KeyError:
        await query.edit_message_text("Заявка не найдена или уже удалена.")
        return

    if request.status != "pending":
        await query.edit_message_text(f"Заявка уже {request.status}.")
        return

    if action == "approve":
        await finalize_request_decision(
            request=request,
            new_status="confirmed",
            context=context,
            edit_target=(query.message.chat_id, query.message.message_id),
        )
        return

    pending_decline = context.chat_data.get("awaiting_reason")
    if pending_decline and pending_decline["request_id"] != request_id:
        await query.answer("Сначала завершите отказ по предыдущей заявке.", show_alert=True)
        return

    context.chat_data["awaiting_reason"] = {
        "request_id": request_id,
        "message_chat_id": query.message.chat_id,
        "message_id": query.message.message_id,
    }
    await query.edit_message_text(
        "Напишите причину отказа ответным сообщением (или нажмите кнопку ниже, чтобы отказаться без причины).",
        reply_markup=build_decline_reason_keyboard(request_id),
    )


async def decline_without_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if query.from_user.id != settings.instructor_chat_id:
        await query.answer("Недостаточно прав", show_alert=True)
        return
    await query.answer()
    _, request_id = query.data.split("|", maxsplit=1)
    await complete_decline_flow(context, request_id, reason=None)


async def cancel_without_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    _, request_id = query.data.split("|", maxsplit=1)
    await complete_client_cancel_flow(
        context=context,
        user=query.from_user,
        request_id=request_id,
        reason=None,
    )


async def admin_cancel_without_reason_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_instructor(query.from_user.id):
        await query.answer("Недостаточно прав", show_alert=True)
        return
    await query.answer()
    _, request_id = query.data.split("|", maxsplit=1)
    await complete_admin_cancel_flow(context, request_id, reason=None)


async def menu_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    text = (message.text or "").strip()
    user = update.effective_user

    if is_instructor(user.id):
        pending_decline = context.chat_data.get("awaiting_reason")
        if pending_decline:
            if text in MENU_BUTTONS:
                context.chat_data.pop("awaiting_reason", None)
            else:
                await complete_decline_flow(context, pending_decline["request_id"], reason=text)
                await message.reply_text(
                    "Причина отправлена, клиент уведомлён.",
                    reply_markup=build_main_keyboard(user.id),
                )
                return
        pending_admin_cancel = context.chat_data.get("awaiting_admin_cancel")
        if pending_admin_cancel:
            if text in MENU_BUTTONS:
                context.chat_data.pop("awaiting_admin_cancel", None)
            else:
                await complete_admin_cancel_flow(context, pending_admin_cancel["request_id"], reason=text)
                await message.reply_text(
                    "Отмена тренировки выполнена.",
                    reply_markup=build_main_keyboard(user.id),
                )
                return

    pending_cancel = context.user_data.get("awaiting_cancel_reason")
    if pending_cancel:
        if text in MENU_BUTTONS:
            context.user_data.pop("awaiting_cancel_reason", None)
        else:
            await complete_client_cancel_flow(
                context=context,
                user=user,
                request_id=pending_cancel["request_id"],
                reason=text,
            )
            return

    if text == BUTTON_BOOK:
        await start_booking(update, context)
        return
    if text == BUTTON_MY:
        await cancel_command(update, context)
        return
    if is_instructor(user.id) and text == BUTTON_TRAINER:
        await show_instructor_bookings(update, context)
        return

    await message.reply_text(
        "Используйте кнопки ниже, чтобы продолжить.",
        reply_markup=build_main_keyboard(user.id),
    )


async def complete_decline_flow(
    context: ContextTypes.DEFAULT_TYPE,
    request_id: str,
    reason: str | None,
) -> None:
    pending: Dict | None = context.chat_data.get("awaiting_reason")
    if not pending or pending["request_id"] != request_id:
        return
    try:
        request = store.get_request(request_id)
    except KeyError:
        context.chat_data.pop("awaiting_reason", None)
        return
    if request.status != "pending":
        context.chat_data.pop("awaiting_reason", None)
        return

    await finalize_request_decision(
        request=request,
        new_status="declined",
        context=context,
        edit_target=(pending["message_chat_id"], pending["message_id"]),
        reason=reason,
    )
    context.chat_data.pop("awaiting_reason", None)


async def complete_client_cancel_flow(
    *,
    context: ContextTypes.DEFAULT_TYPE,
    user,
    request_id: str,
    reason: str | None,
) -> None:
    pending = context.user_data.get("awaiting_cancel_reason")
    if not pending or pending["request_id"] != request_id:
        return
    try:
        request = store.get_request(request_id)
    except KeyError:
        await context.bot.send_message(chat_id=user.id, text="Запись не найдена или уже удалена.")
        context.user_data.pop("awaiting_cancel_reason", None)
        return
    if request.user_id != user.id:
        await context.bot.send_message(chat_id=user.id, text="Нельзя отменить чужую запись.")
        context.user_data.pop("awaiting_cancel_reason", None)
        return
    if request.status not in CLIENT_CANCELABLE_STATUSES:
        await context.bot.send_message(
            chat_id=user.id,
            text="Эту запись больше нельзя отменить. При необходимости выберите другую.",
        )
        context.user_data.pop("awaiting_cancel_reason", None)
        return

    await finalize_client_cancel(
        request=request,
        context=context,
        edit_target=(pending["message_chat_id"], pending["message_id"]),
        reason=reason,
    )
    context.user_data.pop("awaiting_cancel_reason", None)


async def complete_admin_cancel_flow(
    context: ContextTypes.DEFAULT_TYPE,
    request_id: str,
    reason: str | None,
) -> None:
    pending = context.chat_data.get("awaiting_admin_cancel")
    if not pending or pending["request_id"] != request_id:
        return
    try:
        request = store.get_request(request_id)
    except KeyError:
        context.chat_data.pop("awaiting_admin_cancel", None)
        return
    if request.status not in TRAINER_CANCELABLE_STATUSES:
        await context.bot.edit_message_text(
            chat_id=pending["message_chat_id"],
            message_id=pending["message_id"],
            text="Эту запись уже нельзя отменить.",
        )
        context.chat_data.pop("awaiting_admin_cancel", None)
        return

    await finalize_trainer_cancel(
        request=request,
        context=context,
        edit_target=(pending["message_chat_id"], pending["message_id"]),
        reason=reason,
    )
    context.chat_data.pop("awaiting_admin_cancel", None)


async def finalize_request_decision(
    *,
    request,
    new_status: str,
    context: ContextTypes.DEFAULT_TYPE,
    edit_target: Tuple[int, int],
    reason: str | None = None,
) -> None:
    updated = store.update_status(request.id, new_status)
    status_text = "подтверждена ✅" if new_status == "confirmed" else "отклонена ❌"
    trainer_text = (
        f"Заявка {humanize_slot(updated.date, updated.time)} для {updated.full_name} {status_text}."
    )
    if reason and new_status == "declined":
        trainer_text += f"\nПричина: {reason}"
    await context.bot.edit_message_text(
        chat_id=edit_target[0],
        message_id=edit_target[1],
        text=trainer_text,
    )

    if new_status == "confirmed":
        user_message = (
            f"Тренер подтвердил вашу запись на {humanize_slot(updated.date, updated.time)}."
        )
    else:
        base = f"К сожалению, тренер отклонил запись на {humanize_slot(updated.date, updated.time)}."
        if reason:
            base += f"\nПричина: {reason}"
        base += "\nПопробуйте выбрать другое время с помощью /book."
        user_message = base
    await context.bot.send_message(chat_id=updated.user_id, text=user_message)


async def finalize_client_cancel(
    *,
    request,
    context: ContextTypes.DEFAULT_TYPE,
    edit_target: Tuple[int, int],
    reason: str | None,
) -> None:
    previous_status = request.status
    updated = store.update_status(request.id, "cancelled_by_client")
    await context.bot.edit_message_text(
        chat_id=edit_target[0],
        message_id=edit_target[1],
        text=f"Запись на {humanize_slot(updated.date, updated.time)} отменена.",
    )

    user_text = f"Вы отменили запись на {humanize_slot(updated.date, updated.time)}."
    if reason:
        user_text += f"\nПричина: {reason}"
    await context.bot.send_message(
        chat_id=updated.user_id,
        text=user_text,
        reply_markup=build_main_keyboard(updated.user_id),
    )

    admin_text = (
        "<b>Отмена клиентом</b>\n"
        f"Дата: {humanize_slot(updated.date, updated.time)}\n"
        f"Клиент: {updated.full_name} (@{updated.username or 'нет'} | id {updated.user_id})\n"
        f"Статус до отмены: {STATUS_BADGES.get(previous_status, previous_status)}"
    )
    if reason:
        admin_text += f"\nПричина клиента: {reason}"
    await context.bot.send_message(
        chat_id=settings.instructor_chat_id,
        text=admin_text,
        parse_mode=ParseMode.HTML,
    )


async def finalize_trainer_cancel(
    *,
    request,
    context: ContextTypes.DEFAULT_TYPE,
    edit_target: Tuple[int, int],
    reason: str | None,
) -> None:
    previous_status = request.status
    updated = store.update_status(request.id, "cancelled_by_trainer")
    text = (
        f"Тренировка {humanize_slot(updated.date, updated.time)} с {updated.full_name} отменена тренером."
    )
    if reason:
        text += f"\nПричина: {reason}"
    await context.bot.edit_message_text(
        chat_id=edit_target[0],
        message_id=edit_target[1],
        text=text,
    )

    client_text = (
        "Тренер отменил вашу индивидуальную тренировку.\n"
        f"Время: {humanize_slot(updated.date, updated.time)}."
    )
    if reason:
        client_text += f"\nПричина: {reason}"
    client_text += "\nВы можете выбрать другое время с помощью кнопки «📅 Записаться»."
    await context.bot.send_message(
        chat_id=updated.user_id,
        text=client_text,
        reply_markup=build_main_keyboard(updated.user_id),
    )

    admin_text = (
        "<b>Отмена тренером</b>\n"
        f"Дата: {humanize_slot(updated.date, updated.time)}\n"
        f"Клиент: {updated.full_name} (@{updated.username or 'нет'} | id {updated.user_id})\n"
        f"Статус до отмены: {STATUS_BADGES.get(previous_status, previous_status)}"
    )
    if reason:
        admin_text += f"\nПричина: {reason}"
    await context.bot.send_message(
        chat_id=settings.instructor_chat_id,
        text=admin_text,
        parse_mode=ParseMode.HTML,
    )


async def ignore_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()


def main() -> None:
    application = Application.builder().token(settings.bot_token).build()

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("book", start_booking))
    application.add_handler(CommandHandler("cancel", cancel_command))

    application.add_handler(CallbackQueryHandler(date_callback, pattern=r"^DATE\|"))
    application.add_handler(CallbackQueryHandler(time_callback, pattern=r"^TIME\|"))
    application.add_handler(CallbackQueryHandler(back_to_dates, pattern=r"^BACK_TO_DATES"))
    application.add_handler(CallbackQueryHandler(dates_page_callback, pattern=r"^DATES\|"))
    application.add_handler(CallbackQueryHandler(cancel_select_callback, pattern=r"^CANCEL\|"))
    application.add_handler(CallbackQueryHandler(admin_cancel_select_callback, pattern=r"^ADMIN_CANCEL\|"))
    application.add_handler(CallbackQueryHandler(review_callback, pattern=r"^REVIEW\|"))
    application.add_handler(CallbackQueryHandler(decline_without_reason_callback, pattern=r"^DECLINE_SKIP\|"))
    application.add_handler(CallbackQueryHandler(cancel_without_reason_callback, pattern=r"^CANCEL_SKIP\|"))
    application.add_handler(CallbackQueryHandler(admin_cancel_without_reason_callback, pattern=r"^ADMIN_CANCEL_SKIP\|"))
    application.add_handler(CallbackQueryHandler(ignore_callback, pattern=r"^IGNORE$"))
    application.add_handler(
        MessageHandler(
            filters.ChatType.PRIVATE
            & filters.TEXT
            & (~filters.COMMAND),
            menu_text_handler,
        )
    )

    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

