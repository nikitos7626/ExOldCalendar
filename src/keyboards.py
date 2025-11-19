from __future__ import annotations

from datetime import date
from typing import Iterable, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def build_dates_keyboard(
    dates: List[Tuple[date, str]],
    page: int,
    page_size: int,
) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    total = len(dates)
    start = page * page_size
    end = start + page_size
    slice_items = dates[start:end]

    for day, label in slice_items:
        row.append(InlineKeyboardButton(label, callback_data=f"DATE|{day.isoformat()}"))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    if not buttons:
        return InlineKeyboardMarkup([[InlineKeyboardButton("Нет доступных дней", callback_data="IGNORE")]])

    total_pages = max((total + page_size - 1) // page_size, 1)
    nav_row: List[InlineKeyboardButton] = []
    if page > 0:
        nav_row.append(InlineKeyboardButton("◀️", callback_data=f"DATES|{page-1}"))
    nav_row.append(
        InlineKeyboardButton(f"{min(page + 1, total_pages)}/{total_pages}", callback_data="IGNORE")
    )
    if end < total:
        nav_row.append(InlineKeyboardButton("▶️", callback_data=f"DATES|{page+1}"))
    buttons.append(nav_row)

    return InlineKeyboardMarkup(buttons)


def build_times_keyboard(date_str: str, times: Iterable[str], back_page: int) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for time_str in times:
        row.append(
            InlineKeyboardButton(
                time_str,
                callback_data=f"TIME|{date_str}|{time_str}",
            )
        )
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет свободных слотов", callback_data="IGNORE")]]
    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Выбрать другой день",
                callback_data=f"BACK_TO_DATES|{back_page}",
            )
        ]
    )
    return InlineKeyboardMarkup(buttons)


def build_request_review_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ Принять", callback_data=f"REVIEW|{request_id}|approve"),
                InlineKeyboardButton("❌ Отклонить", callback_data=f"REVIEW|{request_id}|decline"),
            ]
        ]
    )


def build_decline_reason_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Отклонить без причины",
                    callback_data=f"DECLINE_SKIP|{request_id}",
                )
            ]
        ]
    )


def build_cancel_select_keyboard(options: Iterable[Tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for request_id, label in options:
        buttons.append([InlineKeyboardButton(label, callback_data=f"CANCEL|{request_id}")])
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("Нет активных записей", callback_data="IGNORE")]])


def build_cancel_reason_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Отменить без причины",
                    callback_data=f"CANCEL_SKIP|{request_id}",
                )
            ]
        ]
    )


def build_admin_cancel_keyboard(options: Iterable[Tuple[str, str]]) -> InlineKeyboardMarkup:
    buttons: List[List[InlineKeyboardButton]] = []
    for request_id, label in options:
        buttons.append(
            [
                InlineKeyboardButton(
                    label,
                    callback_data=f"ADMIN_CANCEL|{request_id}",
                )
            ]
        )
    if not buttons:
        buttons = [[InlineKeyboardButton("Нет активных записей", callback_data="IGNORE")]]
    return InlineKeyboardMarkup(buttons)


def build_admin_cancel_reason_keyboard(request_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Отменить без причины",
                    callback_data=f"ADMIN_CANCEL_SKIP|{request_id}",
                )
            ]
        ]
    )

