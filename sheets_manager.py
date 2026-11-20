import asyncio
import base64
import datetime
import json
import logging
import os
from typing import Dict, List, Optional, Tuple

import gspread
from google.oauth2.service_account import Credentials

from config import settings

logger = logging.getLogger("c2.sheets")

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

MAIN_HEADERS = [
    "№",
    "Sana va Vaqt",
    "Instagram Username",
    "Mijoz Ismi",
    "Telefon Raqam",
    "Miqdor / Izoh",
    "Reels ID",
    "Lid Turi",
]

RESERVE_HEADERS = [
    "№",
    "Sana va Vaqt",
    "Instagram Username",
    "Mijoz Ismi",
    "Telefon Raqam",
    "Miqdor / Izoh",
    "Reels ID",
    "Holat",
]


def _get_gspread_client() -> Optional[gspread.Client]:
    """Load Service Account cleanly from Env JSON (Render) OR local file."""
    creds_info = None
    raw = settings.GOOGLE_CREDENTIALS_JSON

    if raw:
        try:
            if raw.startswith("{"):
                creds_info = json.loads(raw)
            else:
                decoded = base64.b64decode(raw).decode("utf-8")
                creds_info = json.loads(decoded)
        except Exception:
            logger.exception("Failed to parse GOOGLE_CREDENTIALS_JSON")
            return None
        creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
        return gspread.authorize(creds)

    if os.path.exists(settings.GOOGLE_CREDENTIALS_FILE):
        creds = Credentials.from_service_account_file(
            settings.GOOGLE_CREDENTIALS_FILE, scopes=SCOPES
        )
        return gspread.authorize(creds)

    logger.warning("Google credentials not configured (Sheets operations skipped).")
    return None


def _style_header(ws: gspread.Worksheet, bg_rgb: Dict[str, float]) -> None:
    try:
        ws.freeze(rows=1)
        ws.format(
            "A1:H1",
            {
                "backgroundColor": bg_rgb,
                "horizontalAlignment": "CENTER",
                "textFormat": {
                    "foregroundColor": {"red": 1.0, "green": 1.0, "blue": 1.0},
                    "fontSize": 10,
                    "bold": True,
                },
            },
        )
    except Exception:
        logger.warning("Header formatting skipped for %s", ws.title)


def _format_row_color(ws: gspread.Worksheet, row_idx: int, rgb: Dict[str, float]) -> None:
    try:
        ws.format(f"A{row_idx}:H{row_idx}", {"backgroundColor": rgb})
    except Exception:
        pass


def _provision_sheets_sync(
    business_name: str, owner_gmail: str
) -> Tuple[Optional[str], Optional[str], Optional[str], Optional[str]]:
    """
    Create 2 separate spreadsheets:
      1. Main CRM Sheet -> shared with owner_gmail as READER (View-Only!)
      2. Private Reserve Sheet -> shared ONLY with ADMIN_GMAIL (hidden from client until paid)
    """
    gc = _get_gspread_client()
    if not gc:
        return None, None, None, None

    # 1. Main Viewer CRM
    main_sh = gc.create(f"{business_name} — C2 Insta-Lid CRM")
    main_ws = main_sh.sheet1
    main_ws.update_title("Asosiy_Lidlar")
    main_ws.append_row(MAIN_HEADERS, value_input_option="USER_ENTERED")
    _style_header(main_ws, {"red": 0.08, "green": 0.24, "blue": 0.18})

    try:
        main_sh.share(owner_gmail, perm_type="user", role="reader", notify=True)
    except Exception:
        logger.warning("Could not share Main Sheet with %s", owner_gmail)

    if settings.ADMIN_GMAIL:
        try:
            main_sh.share(settings.ADMIN_GMAIL, perm_type="user", role="writer", notify=False)
        except Exception:
            logger.warning("Could not share Main Sheet with admin %s", settings.ADMIN_GMAIL)

    # 2. Private Reserve Sheet (client NEVER gets viewer access)
    res_sh = gc.create(f"[PRIVATE] {business_name} — Zaxira Baza")
    res_ws = res_sh.sheet1
    res_ws.update_title("Zaxira_Lidlar")
    res_ws.append_row(RESERVE_HEADERS, value_input_option="USER_ENTERED")
    _style_header(res_ws, {"red": 0.16, "green": 0.16, "blue": 0.22})

    if settings.ADMIN_GMAIL:
        try:
            res_sh.share(settings.ADMIN_GMAIL, perm_type="user", role="writer", notify=False)
        except Exception:
            logger.warning("Could not share Reserve Sheet with admin %s", settings.ADMIN_GMAIL)

    return main_sh.id, main_sh.url, res_sh.id, res_sh.url


def _append_main_lead_sync(
    main_sheet_id: str,
    row_number: int,
    username: str,
    name: str,
    phone: str,
    qty: str,
    media_id: str,
    lead_type: str,
) -> bool:
    gc = _get_gspread_client()
    if not gc or not main_sheet_id:
        return False

    sh = gc.open_by_key(main_sheet_id)
    ws = sh.worksheet("Asosiy_Lidlar")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")

    label_map = {
        "MAIN": "ASOSIY LID",
        "BONUS": "🎁 BONUS LID",
        "EXTRA_PAID": "➕ QO'SHIMCHA LID",
    }
    label = label_map.get(lead_type, lead_type)
    ws.append_row(
        [row_number, now_str, f"@{username}" if username else "-", name, phone, qty, media_id, label],
        value_input_option="USER_ENTERED",
    )

    last_row = len(ws.col_values(1))
    if lead_type == "BONUS":
        _format_row_color(ws, last_row, {"red": 0.90, "green": 0.98, "blue": 0.90})
    elif lead_type == "EXTRA_PAID":
        _format_row_color(ws, last_row, {"red": 0.88, "green": 0.94, "blue": 1.0})
    return True


def _append_reserve_lead_sync(
    reserve_sheet_id: str,
    username: str,
    name: str,
    phone: str,
    qty: str,
    media_id: str,
) -> bool:
    gc = _get_gspread_client()
    if not gc or not reserve_sheet_id:
        return False

    sh = gc.open_by_key(reserve_sheet_id)
    ws = sh.worksheet("Zaxira_Lidlar")
    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    next_num = max(1, len(ws.col_values(1)))
    ws.append_row(
        [next_num, now_str, f"@{username}" if username else "-", name, phone, qty, media_id, "KUTILMOQDA"],
        value_input_option="USER_ENTERED",
    )
    return True


def _transfer_reserve_sync(
    main_sheet_id: str,
    reserve_sheet_id: Optional[str],
    start_row_num: int,
    leads_data: List[Dict[str, str]],
) -> bool:
    """Copy paid reserve leads into Main Sheet with blue highlight & divider row."""
    gc = _get_gspread_client()
    if not gc or not main_sheet_id or not leads_data:
        return False

    main_sh = gc.open_by_key(main_sheet_id)
    main_ws = main_sh.worksheet("Asosiy_Lidlar")

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    main_ws.append_row(
        ["---", now_str, "---", f"➕ QO'SHIMCHA LIDLAR ({len(leads_data)} ta)", "---", "---", "---", "TO'LANDI"],
        value_input_option="USER_ENTERED",
    )
    div_row = len(main_ws.col_values(1))
    _format_row_color(main_ws, div_row, {"red": 0.80, "green": 0.90, "blue": 1.0})

    rows = []
    for idx, item in enumerate(leads_data):
        rows.append([
            start_row_num + idx,
            item["created_at"],
            f"@{item['username']}" if item["username"] else "-",
            item["name"],
            item["phone"],
            item["qty"],
            item["media_id"],
            "➕ QO'SHIMCHA LID",
        ])

    main_ws.append_rows(rows, value_input_option="USER_ENTERED")
    end_row = len(main_ws.col_values(1))
    start_highlight = end_row - len(rows) + 1
    try:
        main_ws.format(
            f"A{start_highlight}:H{end_row}",
            {"backgroundColor": {"red": 0.91, "green": 0.96, "blue": 1.0}},
        )
    except Exception:
        pass

    if reserve_sheet_id:
        try:
            res_sh = gc.open_by_key(reserve_sheet_id)
            res_ws = res_sh.worksheet("Zaxira_Lidlar")
            res_ws.append_row(
                ["===", now_str, "===", f"{len(leads_data)} ta lid asosiy jadvalga ko'chirildi", "===", "===", "===", "KO'CHIRILDI"],
                value_input_option="USER_ENTERED",
            )
        except Exception:
            logger.warning("Could not update Reserve Sheet marker")

    return True


async def provision_tenant_sheets(business_name: str, owner_gmail: str):
    return await asyncio.to_thread(_provision_sheets_sync, business_name, owner_gmail)


async def append_main_lead(
    main_sheet_id: str,
    row_number: int,
    username: str,
    name: str,
    phone: str,
    qty: str,
    media_id: str,
    lead_type: str,
) -> bool:
    return await asyncio.to_thread(
        _append_main_lead_sync,
        main_sheet_id,
        row_number,
        username,
        name,
        phone,
        qty,
        media_id,
        lead_type,
    )


async def append_reserve_lead(
    reserve_sheet_id: str,
    username: str,
    name: str,
    phone: str,
    qty: str,
    media_id: str,
) -> bool:
    return await asyncio.to_thread(
        _append_reserve_lead_sync,
        reserve_sheet_id,
        username,
        name,
        phone,
        qty,
        media_id,
    )


async def transfer_reserve_to_main(
    main_sheet_id: str,
    reserve_sheet_id: Optional[str],
    start_row_num: int,
    leads_data: List[Dict[str, str]],
) -> bool:
    return await asyncio.to_thread(
        _transfer_reserve_sync,
        main_sheet_id,
        reserve_sheet_id,
        start_row_num,
        leads_data,
    )
