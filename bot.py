from __future__ import annotations

import asyncio
import base64
import html
import importlib.util
import json
import logging
import os
import random
import re
import sqlite3
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import BytesIO
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFilter, ImageFont

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None

# ============================================================
# UZUMAKI BOT - all-in-one single file version
# Python 3.10+
# pip install -U "discord.py[voice]" python-dotenv pillow yt-dlp PyNaCl imageio-ffmpeg
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(ROOT_DIR / ".env")


def _int_env(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    raw = raw.strip()
    if raw == "":
        return default
    return int(raw)


TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GUILD_ID = _int_env("GUILD_ID", 0)
WELCOME_CHANNEL_ID = _int_env("WELCOME_CHANNEL_ID", 0)
LOG_CHANNEL_ID = _int_env("LOG_CHANNEL_ID", 0)
ANNOUNCE_CHANNEL_ID = _int_env("ANNOUNCE_CHANNEL_ID", 0)
LEVEL_CHANNEL_ID = _int_env("LEVEL_CHANNEL_ID", 0)
STAFF_ROLE_ID = _int_env("STAFF_ROLE_ID", 0)
BRAND_NAME = os.getenv("BRAND_NAME", "neko").strip() or "neko"
BRAND_COLOR = int((os.getenv("BRAND_COLOR", "0xffffff").strip() or "0xffffff"), 16)
WHITE_EMBED_COLOR = 0xFFFFFF
DB_PATH = ROOT_DIR / "uzumaki_bot.db"
BAKERY_OWNER_ID = _int_env("BAKERY_OWNER_ID", 0)
BAKERY_OWNER_NAME = os.getenv("BAKERY_OWNER_NAME", "matheossi.").strip().lower()


def _resolve_ffmpeg_path() -> str:
    configured = os.getenv("FFMPEG_PATH", "").strip()
    if configured:
        return configured
    if imageio_ffmpeg is not None:
        try:
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            pass
    return "ffmpeg"


FFMPEG_PATH = _resolve_ffmpeg_path()




if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing in the .env file")

# -----------------------------
# Logging
# -----------------------------
logger = logging.getLogger("uzumaki")
logger.setLevel(logging.INFO)
formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
if not logger.handlers:
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    (ROOT_DIR / "logs").mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(ROOT_DIR / "logs" / "bot.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)




# -----------------------------
# Intents
# -----------------------------
intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.messages = True
intents.reactions = True
intents.message_content = True

# -----------------------------
# Core helpers
# -----------------------------


def utc_now() -> datetime:
    return datetime.now(timezone.utc)



def brand_color() -> discord.Color:
    return discord.Color(WHITE_EMBED_COLOR)



def build_embed(title: str, description: str, *, color: Optional[discord.Color] = None) -> discord.Embed:
    # Tous les embeds gardent une barre blanche pour une identité visuelle clean.
    embed = discord.Embed(
        title=title,
        description=description,
        color=color or brand_color(),
        timestamp=utc_now(),
    )
    embed.set_author(name=BRAND_NAME)
    embed.set_footer(text=f"{BRAND_NAME} - fun, économie et animations")
    return embed


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _parse_color(value: Optional[str]) -> Optional[discord.Color]:
    if not value:
        return None
    value = value.strip()
    if value.startswith("#"):
        value = value[1:]
    if not value:
        return None
    try:
        return discord.Color(int(value, 16))
    except ValueError:
        try:
            return discord.Color(int(value))
        except ValueError:
            return None


def _parse_ticket_reasons(raw: Optional[str]) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"\r?\n|[|;]", raw)
    return [part.strip() for part in parts if part.strip()]


def _format_ticket_template(template: str, values: dict[str, str]) -> str:
    try:
        return template.format_map(_SafeDict(values))
    except Exception:
        return template


def _build_ticket_embed(
    bot: "UzumakiBot",
    guild: discord.Guild,
    author: discord.Member,
    subject: str,
    description: str,
    reason: Optional[str],
    channel: discord.TextChannel,
    staff_role: Optional[discord.Role],
) -> discord.Embed:
    title_template = bot.db.get_setting(guild.id, "ticket_embed_title") or "Ticket ouvert"
    description_template = bot.db.get_setting(guild.id, "ticket_embed_description") or (
        "**Sujet :** {subject}\n**Créé par :** {user}\n**Raison :** {reason}\n\n{description}"
    )
    color = _parse_color(bot.db.get_setting(guild.id, "ticket_embed_color"))
    embed = build_embed(
        _format_ticket_template(
            title_template,
            {
                "user": author.mention,
                "user_name": author.name,
                "user_id": str(author.id),
                "subject": subject,
                "description": description,
                "reason": reason or "Non fournie",
                "guild": guild.name,
                "guild_id": str(guild.id),
                "ticket_channel": channel.mention,
                "ticket_channel_name": channel.name,
                "category": guild.get_channel(int(bot.db.get_setting(guild.id, "ticket_category_id"))) if bot.db.get_setting(guild.id, "ticket_category_id") and bot.db.get_setting(guild.id, "ticket_category_id").isdigit() else "N/A",
                "staff_role": staff_role.mention if staff_role else "Non configuré",
            },
        ),
        _format_ticket_template(
            description_template,
            {
                "user": author.mention,
                "user_name": author.name,
                "user_id": str(author.id),
                "subject": subject,
                "description": description,
                "reason": reason or "Non fournie",
                "guild": guild.name,
                "guild_id": str(guild.id),
                "ticket_channel": channel.mention,
                "ticket_channel_name": channel.name,
                "category": guild.get_channel(int(bot.db.get_setting(guild.id, "ticket_category_id"))) if bot.db.get_setting(guild.id, "ticket_category_id") and bot.db.get_setting(guild.id, "ticket_category_id").isdigit() else "N/A",
                "staff_role": staff_role.mention if staff_role else "Non configuré",
            },
        ),
        color=color,
    )
    image_url = bot.db.get_setting(guild.id, "ticket_embed_image_url")
    if image_url:
        embed.set_image(url=image_url)
    thumbnail_url = bot.db.get_setting(guild.id, "ticket_embed_thumbnail_url")
    if thumbnail_url:
        embed.set_thumbnail(url=thumbnail_url)
    return embed



def format_coins(amount: int) -> str:
    return f"{amount:,}".replace(",", " ")



def progress_bar(current: int, total: int, size: int = 12) -> str:
    if total <= 0:
        return "-" * size
    filled = max(0, min(size, round((current / total) * size)))
    return "█" * filled + "░" * (size - filled)



def parse_amount(raw: str, current_amount: int) -> int:
    value = raw.lower().strip()
    if value in {"all", "max"}:
        return current_amount
    if not value.isdigit():
        raise ValueError("Montant invalide. Mets un nombre ou 'all'.")
    return int(value)



def cooldown_remaining(last_value: Optional[str], duration: timedelta) -> Optional[datetime]:
    if not last_value:
        return None
    next_time = datetime.fromisoformat(last_value) + duration
    if utc_now() < next_time:
        return next_time
    return None


# -----------------------------
# Database
# -----------------------------


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _column_names(self, table: str) -> set[str]:
        with self._connect() as conn:
            rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
            return {str(row["name"]) for row in rows}

    def _ensure_column(self, table: str, column_def: str):
        name = column_def.split()[0]
        if name not in self._column_names(table):
            with self._connect() as conn:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_def}")
                conn.commit()

    def _init_db(self):
        with self._connect() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS settings (
                    guild_id INTEGER NOT NULL,
                    key TEXT NOT NULL,
                    value TEXT NOT NULL,
                    PRIMARY KEY (guild_id, key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS economy (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    wallet INTEGER NOT NULL DEFAULT 0,
                    bank INTEGER NOT NULL DEFAULT 0,
                    bank_limit INTEGER NOT NULL DEFAULT 2500,
                    level INTEGER NOT NULL DEFAULT 1,
                    xp INTEGER NOT NULL DEFAULT 0,
                    streak_daily INTEGER NOT NULL DEFAULT 0,
                    work_bonus REAL NOT NULL DEFAULT 0,
                    crime_bonus REAL NOT NULL DEFAULT 0,
                    interest_bonus REAL NOT NULL DEFAULT 0,
                    heist_bonus REAL NOT NULL DEFAULT 0,
                    prestige INTEGER NOT NULL DEFAULT 0,
                    rep INTEGER NOT NULL DEFAULT 0,
                    last_daily TEXT,
                    last_weekly TEXT,
                    last_work TEXT,
                    last_crime TEXT,
                    last_heist TEXT,
                    last_interest TEXT,
                    last_rep TEXT,
                    PRIMARY KEY (guild_id, user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS inventory (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    item_key TEXT NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    PRIMARY KEY (guild_id, user_id, item_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS shop_roles (
                    guild_id INTEGER NOT NULL,
                    item_key TEXT NOT NULL,
                    title TEXT NOT NULL,
                    role_id INTEGER NOT NULL,
                    price INTEGER NOT NULL,
                    required_level INTEGER NOT NULL DEFAULT 1,
                    description TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (guild_id, item_key)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS event_rsvps (
                    message_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (message_id, user_id)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rp_actions (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, target_id, action)
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rp_action_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ticket_threads (
                    guild_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL PRIMARY KEY,
                    user_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    reason TEXT,
                    status TEXT NOT NULL DEFAULT 'open',
                    created_at TEXT NOT NULL,
                    closed_at TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS message_counts (
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    day TEXT NOT NULL,
                    count INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, day)
                )
                """
            )
            conn.commit()

        for column in [
            "wallet INTEGER NOT NULL DEFAULT 0",
            "bank INTEGER NOT NULL DEFAULT 0",
            "bank_limit INTEGER NOT NULL DEFAULT 2500",
            "level INTEGER NOT NULL DEFAULT 1",
            "xp INTEGER NOT NULL DEFAULT 0",
            "streak_daily INTEGER NOT NULL DEFAULT 0",
            "work_bonus REAL NOT NULL DEFAULT 0",
            "crime_bonus REAL NOT NULL DEFAULT 0",
            "interest_bonus REAL NOT NULL DEFAULT 0",
            "heist_bonus REAL NOT NULL DEFAULT 0",
            "prestige INTEGER NOT NULL DEFAULT 0",
            "rep INTEGER NOT NULL DEFAULT 0",
            "last_daily TEXT",
            "last_weekly TEXT",
            "last_work TEXT",
            "last_crime TEXT",
            "last_heist TEXT",
            "last_interest TEXT",
            "last_rep TEXT",
        ]:
            self._ensure_column("economy", column)
        self._ensure_column("ticket_threads", "reason TEXT")

    # settings
    def set_setting(self, guild_id: int, key: str, value: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (guild_id, key, value)
                VALUES (?, ?, ?)
                ON CONFLICT(guild_id, key)
                DO UPDATE SET value = excluded.value
                """,
                (guild_id, key, value),
            )
            conn.commit()

    def get_setting(self, guild_id: int, key: str) -> Optional[str]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE guild_id = ? AND key = ?",
                (guild_id, key),
            ).fetchone()
            return str(row["value"]) if row else None

    # tickets
    def create_ticket_thread(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int,
        subject: str,
        created_at: str,
        reason: Optional[str] = None,
    ):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ticket_threads (guild_id, channel_id, user_id, subject, reason, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'open', ?)
                """,
                (guild_id, channel_id, user_id, subject, reason, created_at),
            )
            conn.commit()

    def get_open_ticket_for_user(self, guild_id: int, user_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM ticket_threads WHERE guild_id = ? AND user_id = ? AND status = 'open'",
                (guild_id, user_id),
            ).fetchone()

    def get_ticket_thread(self, guild_id: int, channel_id: int) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM ticket_threads WHERE guild_id = ? AND channel_id = ?",
                (guild_id, channel_id),
            ).fetchone()

    def close_ticket_thread(self, guild_id: int, channel_id: int, closed_at: str):
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE ticket_threads
                SET status = 'closed', closed_at = ?
                WHERE guild_id = ? AND channel_id = ?
                """,
                (closed_at, guild_id, channel_id),
            )
            conn.commit()

    # economy
    def ensure_profile(self, guild_id: int, user_id: int):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO economy (
                    guild_id, user_id, wallet, bank, bank_limit, level, xp, streak_daily,
                    work_bonus, crime_bonus, interest_bonus, heist_bonus, prestige, rep,
                    last_daily, last_weekly, last_work, last_crime, last_heist, last_interest, last_rep
                ) VALUES (?, ?, 0, 0, 2500, 1, 0, 0, 0, 0, 0, 0, 0, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL)
                """,
                (guild_id, user_id),
            )
            conn.commit()

    def get_profile(self, guild_id: int, user_id: int) -> sqlite3.Row:
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM economy WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()

    def update_money(self, guild_id: int, user_id: int, wallet_delta: int = 0, bank_delta: int = 0):
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE economy
                SET wallet = MAX(wallet + ?, 0),
                    bank = MAX(bank + ?, 0)
                WHERE guild_id = ? AND user_id = ?
                """,
                (wallet_delta, bank_delta, guild_id, user_id),
            )
            conn.commit()

    def set_last(self, guild_id: int, user_id: int, field: str, value: Optional[str]):
        if field not in {"last_daily", "last_weekly", "last_work", "last_crime", "last_heist", "last_interest", "last_rep"}:
            raise ValueError("Invalid field")
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            conn.execute(f"UPDATE economy SET {field} = ? WHERE guild_id = ? AND user_id = ?", (value, guild_id, user_id))
            conn.commit()

    def set_daily_streak(self, guild_id: int, user_id: int, streak: int):
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE economy SET streak_daily = ? WHERE guild_id = ? AND user_id = ?",
                (streak, guild_id, user_id),
            )
            conn.commit()

    def add_xp(self, guild_id: int, user_id: int, amount: int) -> tuple[int, int, int, bool]:
        profile = self.get_profile(guild_id, user_id)
        xp = int(profile["xp"]) + amount
        level = int(profile["level"])
        bank_limit = int(profile["bank_limit"])
        leveled_up = False
        while xp >= level * 120:
            xp -= level * 120
            level += 1
            bank_limit += 500
            leveled_up = True
        with self._connect() as conn:
            conn.execute(
                "UPDATE economy SET xp = ?, level = ?, bank_limit = ? WHERE guild_id = ? AND user_id = ?",
                (xp, level, bank_limit, guild_id, user_id),
            )
            conn.commit()
        return level, xp, bank_limit, leveled_up

    def add_rep(self, guild_id: int, user_id: int, amount: int = 1):
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            conn.execute(
                "UPDATE economy SET rep = MAX(rep + ?, 0) WHERE guild_id = ? AND user_id = ?",
                (amount, guild_id, user_id),
            )
            conn.commit()

    def get_top_levels(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT user_id, level, xp, rep, prestige FROM economy WHERE guild_id = ? ORDER BY level DESC, xp DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()

    def get_top_rep(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT user_id, rep FROM economy WHERE guild_id = ? ORDER BY rep DESC, level DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()

    #  stats
    def record_rp_action(self, guild_id: int, user_id: int, target_id: int, action: str) -> int:
        now = utc_now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO rp_action_log (guild_id, user_id, target_id, action, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (guild_id, user_id, target_id, action, now),
            )
            conn.execute(
                """
                INSERT INTO rp_actions (guild_id, user_id, target_id, action, count, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(guild_id, user_id, target_id, action)
                DO UPDATE SET count = count + 1, updated_at = excluded.updated_at
                """,
                (guild_id, user_id, target_id, action, now),
            )
            row = conn.execute(
                """
                SELECT count FROM rp_actions
                WHERE guild_id = ? AND user_id = ? AND target_id = ? AND action = ?
                """,
                (guild_id, user_id, target_id, action),
            ).fetchone()
            conn.commit()
        return int(row["count"]) if row else 1

    def get_rp_sent_total(self, guild_id: int, user_id: int, action: Optional[str] = None) -> int:
        query = "SELECT COALESCE(SUM(count), 0) AS total FROM rp_actions WHERE guild_id = ? AND user_id = ?"
        params: list[object] = [guild_id, user_id]
        if action:
            query += " AND action = ?"
            params.append(action)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["total"]) if row else 0

    def get_rp_received_total(self, guild_id: int, user_id: int, action: Optional[str] = None) -> int:
        query = "SELECT COALESCE(SUM(count), 0) AS total FROM rp_actions WHERE guild_id = ? AND target_id = ?"
        params: list[object] = [guild_id, user_id]
        if action:
            query += " AND action = ?"
            params.append(action)
        with self._connect() as conn:
            row = conn.execute(query, params).fetchone()
            return int(row["total"]) if row else 0

    def get_rp_daily_received_total(self, guild_id: int, user_id: int, action: str) -> int:
        start = utc_now().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT COUNT(*) AS total FROM rp_action_log
                WHERE guild_id = ? AND target_id = ? AND action = ? AND created_at >= ?
                """,
                (guild_id, user_id, action, start),
            ).fetchone()
            return int(row["total"]) if row else 0

    def get_rp_top_actions(self, guild_id: int, user_id: int, limit: int = 3) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                """
                SELECT action, SUM(count) AS total
                FROM rp_actions
                WHERE guild_id = ? AND user_id = ?
                GROUP BY action
                ORDER BY total DESC, action ASC
                LIMIT ?
                """,
                (guild_id, user_id, limit),
            ).fetchall()

    def increment_message_count(self, guild_id: int, user_id: int, day: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO message_counts (guild_id, user_id, day, count)
                VALUES (?, ?, ?, 1)
                ON CONFLICT(guild_id, user_id, day)
                DO UPDATE SET count = count + 1
                """,
                (guild_id, user_id, day),
            )
            conn.commit()

    def get_message_count(self, guild_id: int, user_id: int, day: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT count FROM message_counts WHERE guild_id = ? AND user_id = ? AND day = ?",
                (guild_id, user_id, day),
            ).fetchone()
            return int(row["count"]) if row else 0

    def apply_upgrade(
        self,
        guild_id: int,
        user_id: int,
        *,
        bank_limit: int = 0,
        work_bonus: float = 0,
        crime_bonus: float = 0,
        interest_bonus: float = 0,
        heist_bonus: float = 0,
    ):
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE economy
                SET bank_limit = bank_limit + ?,
                    work_bonus = work_bonus + ?,
                    crime_bonus = crime_bonus + ?,
                    interest_bonus = interest_bonus + ?,
                    heist_bonus = heist_bonus + ?
                WHERE guild_id = ? AND user_id = ?
                """,
                (bank_limit, work_bonus, crime_bonus, interest_bonus, heist_bonus, guild_id, user_id),
            )
            conn.commit()

    def prestige_player(self, guild_id: int, user_id: int) -> int:
        self.ensure_profile(guild_id, user_id)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT prestige FROM economy WHERE guild_id = ? AND user_id = ?",
                (guild_id, user_id),
            ).fetchone()
            new_prestige = int(row["prestige"]) + 1
            conn.execute(
                """
                UPDATE economy
                SET wallet = 0,
                    bank = 0,
                    bank_limit = 2500 + (? * 1000),
                    level = 1,
                    xp = 0,
                    streak_daily = 0,
                    prestige = ?,
                    work_bonus = work_bonus + 0.03,
                    interest_bonus = interest_bonus + 0.002,
                    last_daily = NULL,
                    last_weekly = NULL,
                    last_work = NULL,
                    last_crime = NULL,
                    last_heist = NULL,
                    last_interest = NULL
                WHERE guild_id = ? AND user_id = ?
                """,
                (new_prestige, new_prestige, guild_id, user_id),
            )
            conn.commit()
            return new_prestige

    # inventory
    def get_item_quantity(self, guild_id: int, user_id: int, item_key: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT quantity FROM inventory WHERE guild_id = ? AND user_id = ? AND item_key = ?",
                (guild_id, user_id, item_key),
            ).fetchone()
            return int(row["quantity"]) if row else 0

    def add_inventory_item(self, guild_id: int, user_id: int, item_key: str, quantity: int = 1):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO inventory (guild_id, user_id, item_key, quantity)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(guild_id, user_id, item_key)
                DO UPDATE SET quantity = inventory.quantity + excluded.quantity
                """,
                (guild_id, user_id, item_key, quantity),
            )
            conn.execute(
                "DELETE FROM inventory WHERE guild_id = ? AND user_id = ? AND item_key = ? AND quantity <= 0",
                (guild_id, user_id, item_key),
            )
            conn.commit()

    def get_inventory(self, guild_id: int, user_id: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT item_key, quantity FROM inventory WHERE guild_id = ? AND user_id = ? ORDER BY item_key",
                (guild_id, user_id),
            ).fetchall()

    # shop roles
    def add_shop_role(self, guild_id: int, item_key: str, title: str, role_id: int, price: int, required_level: int, description: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO shop_roles (guild_id, item_key, title, role_id, price, required_level, description)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id, item_key)
                DO UPDATE SET title = excluded.title,
                              role_id = excluded.role_id,
                              price = excluded.price,
                              required_level = excluded.required_level,
                              description = excluded.description
                """,
                (guild_id, item_key, title, role_id, price, required_level, description),
            )
            conn.commit()

    def remove_shop_role(self, guild_id: int, item_key: str):
        with self._connect() as conn:
            conn.execute("DELETE FROM shop_roles WHERE guild_id = ? AND item_key = ?", (guild_id, item_key))
            conn.commit()

    def get_shop_roles(self, guild_id: int) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM shop_roles WHERE guild_id = ? ORDER BY price ASC, title ASC",
                (guild_id,),
            ).fetchall()

    def get_shop_role(self, guild_id: int, item_key: str) -> Optional[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT * FROM shop_roles WHERE guild_id = ? AND item_key = ?",
                (guild_id, item_key),
            ).fetchone()

    def get_top_wallet(self, guild_id: int, limit: int = 10) -> list[sqlite3.Row]:
        with self._connect() as conn:
            return conn.execute(
                "SELECT user_id, wallet, bank, prestige FROM economy WHERE guild_id = ? ORDER BY (wallet + bank) DESC LIMIT ?",
                (guild_id, limit),
            ).fetchall()

    # event RSVP
    def set_rsvp(self, message_id: int, user_id: int, status: str):
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO event_rsvps (message_id, user_id, status, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(message_id, user_id)
                DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at
                """,
                (message_id, user_id, status, utc_now().isoformat()),
            )
            conn.commit()

    def get_rsvp_counts(self, message_id: int) -> dict[str, int]:
        counts = {"yes": 0, "maybe": 0, "no": 0}
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS total FROM event_rsvps WHERE message_id = ? GROUP BY status",
                (message_id,),
            ).fetchall()
            for row in rows:
                if row["status"] in counts:
                    counts[str(row["status"])] = int(row["total"])
        return counts


# -----------------------------
# Shop data / economy logic
# -----------------------------


@dataclass(frozen=True)
class BuiltinShopItem:
    key: str
    title: str
    price: int
    required_level: int
    description: str
    kind: str
    value: float | int
    repeatable: bool = False


BUILTIN_SHOP_ITEMS: dict[str, BuiltinShopItem] = {
    "bank-note": BuiltinShopItem("bank-note", "Note bancaire", 850, 1, "+1 000 de capacité banque", "bank_limit", 1000, True),
    "sakura-vault": BuiltinShopItem("sakura-vault", "Coffre Sakura", 2200, 4, "+2 500 de capacité banque", "bank_limit", 2500, True),
    "work-kit": BuiltinShopItem("work-kit", "Kit de travail", 1400, 2, "+8% sur les gains de /work", "work_bonus", 0.08),
    "shadow-mask": BuiltinShopItem("shadow-mask", "Masque d'ombre", 1800, 3, "+4% de chance de réussite sur /crime", "crime_bonus", 0.04),
    "gold-passbook": BuiltinShopItem("gold-passbook", "Livret doré", 2600, 5, "+0.5% d'intérêt sur /interest", "interest_bonus", 0.005),
    "heist-blueprint": BuiltinShopItem("heist-blueprint", "Plan de casse", 3200, 5, "Débloque /heist et +5% de réussite sur les casses", "heist_unlock", 0.05),
    "sakura-badge": BuiltinShopItem("sakura-badge", "Badge Sakura", 600, 1, "Objet cosmétique à collectionner", "cosmetic", 1, False),
    "pain-au-chocolat": BuiltinShopItem("pain-au-chocolat", "Pain au chocolat", 45, 1, "Une douceur de la boulangerie", "bakery_food", 1, True),
    "croissant": BuiltinShopItem("croissant", "Croissant", 40, 1, "Un croissant bien chaud", "bakery_food", 1, True),
    "brioche": BuiltinShopItem("brioche", "Brioche", 55, 1, "Une brioche moelleuse", "bakery_food", 1, True),
    "baguette": BuiltinShopItem("baguette", "Baguette", 35, 1, "Le classique de la boulangerie", "bakery_food", 1, True),
    "pain": BuiltinShopItem("pain", "Pain", 30, 1, "Un bon pain tout frais", "bakery_food", 1, True),
}




def get_shop_entries(db: Database, guild_id: int) -> list[dict]:
    entries: list[dict] = []

    for item in BUILTIN_SHOP_ITEMS.values():
        category = "boosts"
        if item.kind == "cosmetic":
            category = "cosmetics"
        elif item.kind == "bakery_food":
            category = "bakery"

        entries.append({
            "key": item.key,
            "title": item.title,
            "price": item.price,
            "required_level": item.required_level,
            "description": item.description,
            "category": category,
            "kind": "builtin",
        })

    for row in db.get_shop_roles(guild_id):
        entries.append({
            "key": str(row["item_key"]),
            "title": str(row["title"]),
            "price": int(row["price"]),
            "required_level": int(row["required_level"]),
            "description": str(row["description"] or "Rôle serveur"),
            "category": "roles",
            "kind": "role",
        })

    entries.sort(key=lambda x: (x["category"], x["price"], x["title"].lower()))
    return entries


def build_shop_page_embed(bot: "UzumakiBot", guild: discord.Guild, member: discord.Member, category: str, page: int) -> tuple[discord.Embed, list[dict], int]:
    entries = get_shop_entries(bot.db, guild.id)
    if category != "all":
        entries = [entry for entry in entries if entry["category"] == category]
    per_page = 6
    total_pages = max(1, (len(entries) + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    chunk = entries[page * per_page:(page + 1) * per_page]

    category_names = {
        "all": "Toute la boutique",
        "boosts": "Boosts & upgrades",
        "roles": "Rôles prestige",
        "cosmetics": "Cosmétiques",
        "bakery": "Boulangerie",
    }
    profile = bot.db.get_profile(guild.id, member.id)
    embed = build_embed(
        f"🛍️ Boutique Uzumaki • {category_names.get(category, category)}",
        "Choisis un objet dans le sélecteur puis utilise les boutons en bas.\n```\nClé              Prix     Lvl  Objet\n```",
    )
    if chunk:
        lines = []
        for entry in chunk:
            key = entry["key"][:14].ljust(14)
            price = str(entry["price"]).rjust(6)
            lvl = str(entry["required_level"]).rjust(3)
            lines.append(f"`{key} {price} {lvl}  {entry['title'][:22]}`")
        embed.description = "Choisis un objet dans le sélecteur puis utilise les boutons en bas.\n" + "\n".join(lines)
    else:
        embed.description = "Aucun objet dans cette catégorie pour l'instant."
    embed.add_field(name="Ton cash", value=f"{format_coins(int(profile['wallet']))} ¥", inline=True)
    embed.add_field(name="Ton niveau", value=str(int(profile["level"])), inline=True)
    embed.add_field(name="Page", value=f"{page + 1}/{total_pages}", inline=True)
    if chunk:
        preview = chunk[0]
        embed.add_field(name="Astuce", value=f"Les rôles prestige s'achètent comme les objets normaux. Certains achats demandent un niveau minimum.", inline=False)
    return embed, chunk, total_pages

def configured_channel_id(db: Database, guild_id: int, key: str, fallback: int) -> int:
    raw = db.get_setting(guild_id, key)
    if raw and raw.isdigit():
        return int(raw)
    return fallback



def get_confession_channel(bot: "UzumakiBot", guild: discord.Guild) -> Optional[discord.TextChannel]:
    channel_id = configured_channel_id(bot.db, guild.id, "confession_channel_id", 0)
    if channel_id:
        channel = guild.get_channel(channel_id)
        if isinstance(channel, discord.TextChannel):
            return channel

    category_id = configured_channel_id(bot.db, guild.id, "confession_category_id", 0)
    if category_id:
        category = guild.get_channel(category_id)
        if isinstance(category, discord.CategoryChannel) and category.text_channels:
            return category.text_channels[0]

    return None



def is_staff(member: discord.Member, db: Optional[Database] = None) -> bool:
    if member.guild_permissions and (member.guild_permissions.manage_guild or member.guild_permissions.manage_messages):
        return True
    role_id = STAFF_ROLE_ID
    if db is not None:
        raw = db.get_setting(member.guild.id, "staff_role_id")
        if raw and raw.isdigit():
            role_id = int(raw)
    if role_id:
        return any(role.id == role_id for role in member.roles)
    return False



def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise app_commands.CheckFailure("Commande utilisable seulement en serveur.")
        if is_staff(interaction.user, getattr(interaction.client, "db", None)):
            return True
        raise app_commands.CheckFailure("Tu n'as pas la permission pour cette commande.")

    return app_commands.check(predicate)



def build_profile_embed(db: Database, member: discord.Member) -> discord.Embed:
    row = db.get_profile(member.guild.id, member.id)
    total = int(row["wallet"]) + int(row["bank"])
    next_level = int(row["level"]) * 120
    embed = build_embed("Profil membre", f"Voici le profil de {member.mention}")
    embed.set_thumbnail(url=member.display_avatar.url)
    title = db.get_setting(member.guild.id, f"title:{member.id}")
    badges = db.get_setting(member.guild.id, f"badges:{member.id}")
    if title:
        embed.add_field(name="Titre équipé", value=title, inline=False)
    if badges:
        embed.add_field(name="Badges", value=badges.replace("|", " • "), inline=False)
    relations = relation_lines(db, member)
    if relations:
        embed.add_field(name="Relations", value="\n".join(relations), inline=False)
    rp_sent = db.get_rp_sent_total(member.guild.id, member.id)
    rp_received = db.get_rp_received_total(member.guild.id, member.id)
    rp_title = rp_title_for(db, member.guild.id, member.id)
    top_actions = db.get_rp_top_actions(member.guild.id, member.id, 3)
    if rp_sent or rp_received or rp_title:
        details = [
            f"Actions donnees : **{rp_sent}**",
            f"Actions recues : **{rp_received}**",
        ]
        if rp_title:
            details.append(f"Titre : **{rp_title}**")
        if top_actions:
            top = ", ".join(f"{rp_action_label(str(row['action']))} x{int(row['total'])}" for row in top_actions)
            details.append(f"Top : {top}")
        embed.add_field(name="Stats ", value="\n".join(details), inline=False)
    embed.add_field(name="Portefeuille", value=f"{format_coins(int(row['wallet']))} ¥", inline=True)
    embed.add_field(name="Banque", value=f"{format_coins(int(row['bank']))} ¥", inline=True)
    embed.add_field(name="Total", value=f"{format_coins(total)} ¥", inline=True)
    embed.add_field(name="Niveau", value=str(int(row["level"])), inline=True)
    embed.add_field(name="XP", value=f"{progress_bar(int(row['xp']), next_level)}\n{int(row['xp'])}/{next_level}", inline=False)
    embed.add_field(name="Capacité banque", value=f"{format_coins(int(row['bank_limit']))} ¥", inline=True)
    embed.add_field(name="Série daily", value=f"{int(row['streak_daily'])} jour(s)", inline=True)
    embed.add_field(name="Bonus travail", value=f"+{int(float(row['work_bonus']) * 100)}%", inline=True)
    embed.add_field(name="Bonus crime", value=f"+{int(float(row['crime_bonus']) * 100)}%", inline=True)
    embed.add_field(name="Prestige", value=str(int(row["prestige"])), inline=True)
    embed.add_field(name="Rep", value=str(int(row["rep"])), inline=True)
    if member.joined_at:
        embed.add_field(name="A rejoint le serv", value=discord.utils.format_dt(member.joined_at, style="R"), inline=False)
    return embed



def claim_daily(db: Database, guild_id: int, user_id: int) -> tuple[bool, discord.Embed]:
    row = db.get_profile(guild_id, user_id)
    next_claim = cooldown_remaining(row["last_daily"], timedelta(hours=24))
    if next_claim:
        return False, build_embed(
            "Daily indisponible",
            f"Tu as déjà pris ton daily. Reviens <t:{int(next_claim.timestamp())}:R>.",
            color=discord.Color.red(),
        )

    now = utc_now()
    streak = int(row["streak_daily"])
    if row["last_daily"]:
        previous = datetime.fromisoformat(row["last_daily"])
        streak = streak + 1 if now - previous <= timedelta(hours=48) else 1
    else:
        streak = 1

    prestige_bonus = int(row["prestige"]) * 12
    streak_bonus = min((streak - 1) * 10, 60)
    reward = 120 + streak_bonus + prestige_bonus
    db.update_money(guild_id, user_id, wallet_delta=reward)
    db.set_last(guild_id, user_id, "last_daily", now.isoformat())
    db.set_daily_streak(guild_id, user_id, streak)
    level, _, bank_limit, leveled = db.add_xp(guild_id, user_id, random.randint(15, 24))
    profile = db.get_profile(guild_id, user_id)

    embed = build_embed(
        "Daily récupéré",
        f"Tu as gagné **{format_coins(reward)} ¥**.\n"
        f"Série : **{streak}** jour(s)\n"
        f"Portefeuille : **{format_coins(int(profile['wallet']))} ¥**",
        color=discord.Color.green(),
    )
    if leveled:
        embed.add_field(name="Level up", value=f"Niveau **{level}** atteint. Capacité banque : **{format_coins(bank_limit)} ¥**", inline=False)
    return True, embed



def apply_builtin_purchase(db: Database, guild_id: int, user_id: int, item_key: str) -> tuple[bool, str]:
    item = BUILTIN_SHOP_ITEMS[item_key]
    profile = db.get_profile(guild_id, user_id)

    if int(profile["level"]) < item.required_level:
        return False, f"Niveau requis : **{item.required_level}**."
    if int(profile["wallet"]) < item.price:
        return False, "Tu n'as pas assez dans ton portefeuille."
    if not item.repeatable and db.get_item_quantity(guild_id, user_id, item_key) > 0:
        return False, "Tu possèdes déjà cet objet."

    db.update_money(guild_id, user_id, wallet_delta=-item.price)

    if item.kind == "bank_limit":
        db.apply_upgrade(guild_id, user_id, bank_limit=int(item.value))
    elif item.kind == "work_bonus":
        db.apply_upgrade(guild_id, user_id, work_bonus=float(item.value))
    elif item.kind == "crime_bonus":
        db.apply_upgrade(guild_id, user_id, crime_bonus=float(item.value))
    elif item.kind == "interest_bonus":
        db.apply_upgrade(guild_id, user_id, interest_bonus=float(item.value))
    elif item.kind == "heist_unlock":
        db.apply_upgrade(guild_id, user_id, heist_bonus=float(item.value))
    elif item.kind == "bakery_food":
        pass

    db.add_inventory_item(guild_id, user_id, item_key, 1)
    return True, f"Achat réussi : **{item.title}** pour **{format_coins(item.price)} ¥**."



def can_use_heist(db: Database, guild_id: int, user_id: int) -> bool:
    profile = db.get_profile(guild_id, user_id)
    return int(profile["level"]) >= 5 or db.get_item_quantity(guild_id, user_id, "heist-blueprint") > 0


# -----------------------------
# Welcome image
# -----------------------------



def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for font_name in ["DejaVuSans.ttf", "arial.ttf"]:
        try:
            return ImageFont.truetype(font_name, size)
        except OSError:
            continue
    return ImageFont.load_default()


async def create_welcome_image(member: discord.Member) -> BytesIO:
    width, height = 1280, 480
    img = Image.new("RGBA", (width, height), (247, 228, 238, 255))
    draw = ImageDraw.Draw(img)

    # sakura gradient background
    for y in range(height):
        ratio = y / max(height - 1, 1)
        r = int(248 * (1 - ratio) + 214 * ratio)
        g = int(229 * (1 - ratio) + 194 * ratio)
        b = int(239 * (1 - ratio) + 233 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))

    # soft vignette and light panels
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    o = ImageDraw.Draw(overlay)
    o.rounded_rectangle((40, 40, width - 40, height - 40), radius=36, fill=(255, 255, 255, 75))
    overlay = overlay.filter(ImageFilter.GaussianBlur(2))
    img = Image.alpha_composite(img, overlay)

    # petals
    petals_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    petals = ImageDraw.Draw(petals_layer)
    random.seed(member.id % 100000)
    for _ in range(70):
        x = random.randint(-20, width + 20)
        y = random.randint(-20, height + 20)
        s = random.randint(8, 20)
        color = random.choice([(255, 198, 222, 120), (255, 214, 230, 110), (246, 184, 214, 95)])
        petals.ellipse((x, y, x + s, y + s // 2 + 4), fill=color)
    petals_layer = petals_layer.filter(ImageFilter.GaussianBlur(1))
    img = Image.alpha_composite(img, petals_layer)

    # avatar large
    avatar_bytes = await member.display_avatar.with_size(512).read()
    avatar = Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((320, 320))
    mask = Image.new("L", avatar.size, 0)
    md = ImageDraw.Draw(mask)
    md.ellipse((0, 0, 320, 320), fill=255)
    avatar_circle = Image.new("RGBA", avatar.size, (0, 0, 0, 0))
    avatar_circle.paste(avatar, (0, 0), mask)

    glow = Image.new("RGBA", (380, 380), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((15, 15, 365, 365), fill=(255, 210, 232, 130))
    glow = glow.filter(ImageFilter.GaussianBlur(18))
    img.alpha_composite(glow, (72, 52))
    img.alpha_composite(avatar_circle, (102, 82))

    # texts
    title_font = _load_font(52)
    name_font = _load_font(44)
    sub_font = _load_font(26)
    small_font = _load_font(24)

    draw = ImageDraw.Draw(img)
    draw.text((470, 88), "Bienvenue sur le serveur", font=title_font, fill=(95, 40, 82, 255))
    draw.text((470, 162), member.display_name[:26], font=name_font, fill=(153, 50, 108, 255))
    draw.text((470, 230), "Prends place, découvre les salons et amuse-toi bien 🌸", font=sub_font, fill=(88, 60, 88, 255))
    draw.rounded_rectangle((470, 300, 1110, 350), radius=24, fill=(255, 255, 255, 95), outline=(221, 166, 196, 180), width=2)
    draw.text((495, 311), f"{BRAND_NAME} t'accueille avec une vraie vibe sakura.", font=small_font, fill=(112, 64, 100, 255))

    out = BytesIO()
    img.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


async def _avatar_rgba(member: discord.Member, size: int = 256) -> Image.Image:
    try:
        avatar_bytes = await member.display_avatar.with_size(size).read()
        return Image.open(BytesIO(avatar_bytes)).convert("RGBA").resize((size, size))
    except Exception:
        img = Image.new("RGBA", (size, size), (245, 245, 245, 255))
        draw = ImageDraw.Draw(img)
        draw.ellipse((8, 8, size - 8, size - 8), fill=(220, 220, 220, 255))
        draw.text((size // 2 - 12, size // 2 - 18), "", font=_load_font(42), fill=(80, 80, 80, 255))
        return img


def _circle_crop(image: Image.Image) -> Image.Image:
    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((0, 0, image.size[0] - 1, image.size[1] - 1), fill=255)
    out = Image.new("RGBA", image.size, (0, 0, 0, 0))
    out.paste(image, (0, 0), mask)
    return out


def _draw_card_background(width: int, height: int, accent: tuple[int, int, int]) -> Image.Image:
    if sum(accent) > 720:
        accent = (116, 72, 38)
    base = tuple(max(18, min(210, int(channel))) for channel in accent)
    img = Image.new("RGBA", (width, height), (31, 29, 34, 255))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int((base[0] * 0.34 + 24) * (1 - ratio) + (base[0] * 0.12 + 18) * ratio)
        g = int((base[1] * 0.34 + 24) * (1 - ratio) + (base[1] * 0.12 + 18) * ratio)
        b = int((base[2] * 0.34 + 28) * (1 - ratio) + (base[2] * 0.12 + 24) * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))
    for _ in range(280):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        alpha = random.randint(20, 48)
        draw.point((x, y), fill=(255, 241, 210, alpha))
    draw.rounded_rectangle((28, 28, width - 28, height - 28), radius=30, outline=(235, 205, 142, 255), width=8)
    draw.rounded_rectangle((48, 48, width - 48, height - 48), radius=22, outline=(*base, 255), width=4)
    draw.rectangle((0, 0, 22, height), fill=(*base, 255))
    return img


def _text(draw: ImageDraw.ImageDraw, xy: tuple[int, int], value: str, font: ImageFont.ImageFont, fill=(20, 20, 24, 255), limit: int = 44):
    value = value if len(value) <= limit else value[: limit - 1] + "…"
    draw.text(xy, value, font=font, fill=fill)


def relation_lines(db: Database, member: discord.Member) -> list[str]:
    guild_id = member.guild.id
    lines: list[str] = []
    partner_id = db.get_setting(guild_id, f"marry:{member.id}")
    if partner_id and partner_id.isdigit():
        since = db.get_setting(guild_id, f"marry_since:{member.id}")
        when = short_when(since)
        lines.append(f"Partenaire : <@{partner_id}>" + (f" ({when})" if when else ""))
    parent_id = db.get_setting(guild_id, f"adopt:{member.id}")
    if parent_id and parent_id.isdigit():
        since = db.get_setting(guild_id, f"adopted_at:{member.id}")
        when = short_when(since)
        lines.append(f"Parent : <@{parent_id}>" + (f" ({when})" if when else ""))
    try:
        with db._connect() as conn:
            rows = conn.execute(
                "SELECT key FROM settings WHERE guild_id = ? AND key LIKE 'adopt:%' AND value = ? LIMIT 5",
                (guild_id, str(member.id)),
            ).fetchall()
        children = [row["key"].split(":", 1)[1] for row in rows if str(row["key"]).split(":", 1)[1].isdigit()]
        if children:
            lines.append("Enfants : " + ", ".join(f"<@{child_id}>" for child_id in children))
    except sqlite3.Error:
        pass
    return lines


def short_when(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        return discord.utils.format_dt(datetime.fromisoformat(value), style="R")
    except ValueError:
        return ""


async def create_member_card(
    member: discord.Member,
    title: str,
    subtitle: str,
    stats: list[tuple[str, str]],
    *,
    accent: tuple[int, int, int] = (245, 245, 245),
) -> BytesIO:
    width, height = 1100, 520
    img = _draw_card_background(width, height, accent)
    draw = ImageDraw.Draw(img)
    avatar = _circle_crop(await _avatar_rgba(member, 240))
    shadow = Image.new("RGBA", (280, 280), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse((20, 20, 260, 260), fill=(0, 0, 0, 120))
    shadow = shadow.filter(ImageFilter.GaussianBlur(14))
    img.alpha_composite(shadow, (65, 105))
    img.alpha_composite(avatar, (85, 120))
    title_font = _load_font(48)
    name_font = _load_font(38)
    body_font = _load_font(25)
    small_font = _load_font(22)
    draw.rounded_rectangle((72, 108, 338, 376), radius=140, outline=(235, 205, 142, 255), width=6)
    _text(draw, (380, 88), title, title_font, (255, 239, 194, 255), 32)
    _text(draw, (380, 150), member.display_name, name_font, (255, 255, 255, 255), 28)
    _text(draw, (380, 202), subtitle, body_font, (220, 220, 226, 255), 62)
    x, y = 380, 280
    for index, (label, value) in enumerate(stats[:6]):
        col = index % 2
        row = index // 2
        bx = x + col * 330
        by = y + row * 72
        draw.rounded_rectangle((bx, by, bx + 300, by + 54), radius=14, fill=(18, 18, 22, 210), outline=(235, 205, 142, 180), width=2)
        _text(draw, (bx + 18, by + 8), label, small_font, (198, 172, 115, 255), 18)
        _text(draw, (bx + 152, by + 8), value, small_font, (255, 255, 255, 255), 20)
    out = BytesIO()
    img.convert("RGB").save(out, "PNG", quality=95)
    out.seek(0)
    return out


async def create_wanted_poster_image(member: discord.Member, bounty: int) -> BytesIO:
    width, height = 900, 1250
    img = Image.new("RGBA", (width, height), (229, 202, 150, 255))
    draw = ImageDraw.Draw(img)
    for y in range(height):
        ratio = y / max(1, height - 1)
        r = int(236 * (1 - ratio) + 186 * ratio)
        g = int(213 * (1 - ratio) + 154 * ratio)
        b = int(163 * (1 - ratio) + 92 * ratio)
        draw.line((0, y, width, y), fill=(r, g, b, 255))
    for _ in range(1800):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        shade = random.randint(70, 135)
        draw.point((x, y), fill=(shade, max(45, shade - 26), 28, random.randint(18, 48)))
    draw.rectangle((34, 34, width - 34, height - 34), outline=(88, 48, 22, 255), width=8)
    draw.rectangle((58, 58, width - 58, height - 58), outline=(146, 82, 35, 255), width=3)
    title_font = _load_font(112)
    sub_font = _load_font(44)
    name_font = _load_font(58)
    bounty_font = _load_font(54)
    small_font = _load_font(26)

    draw.text((width // 2, 86), "WANTED", font=title_font, fill=(52, 27, 12, 255), anchor="ma")
    draw.text((width // 2, 205), "DEAD OR ALIVE", font=sub_font, fill=(89, 35, 15, 255), anchor="ma")

    avatar = await _avatar_rgba(member, 512)
    avatar = avatar.resize((560, 560))
    photo_x, photo_y = 170, 290
    draw.rectangle((photo_x - 18, photo_y - 18, photo_x + 578, photo_y + 578), fill=(62, 34, 18, 255))
    draw.rectangle((photo_x - 7, photo_y - 7, photo_x + 567, photo_y + 567), fill=(219, 188, 130, 255))
    img.alpha_composite(avatar, (photo_x, photo_y))
    draw.rectangle((photo_x, photo_y, photo_x + 560, photo_y + 560), outline=(60, 35, 22, 255), width=6)

    name = member.display_name.upper()[:22]
    draw.text((width // 2, 915), name, font=name_font, fill=(45, 24, 12, 255), anchor="ma")
    draw.text((width // 2, 1002), f"PRIME {format_coins(bounty)} ¥", font=bounty_font, fill=(82, 38, 19, 255), anchor="ma")
    draw.line((120, 1075, width - 120, 1075), fill=(90, 54, 31, 255), width=4)
    draw.text((width // 2, 1110), "WORLD GOVERNMENT - GRAND LINE NOTICE", font=small_font, fill=(72, 45, 28, 255), anchor="ma")
    draw.text((width // 2, 1152), f"issued by {BRAND_NAME}", font=small_font, fill=(94, 58, 36, 255), anchor="ma")

    out = BytesIO()
    img.convert("RGB").save(out, "PNG", quality=95)
    out.seek(0)
    return out



async def create_profile_card_image(db: Database, member: discord.Member) -> BytesIO:
    row = db.get_profile(member.guild.id, member.id)
    total = int(row["wallet"]) + int(row["bank"])
    title = db.get_setting(member.guild.id, f"title:{member.id}") or "Membre Uzumaki"
    badges = db.get_setting(member.guild.id, f"badges:{member.id}") or "Aucun badge"
    relations = relation_lines(db, member)
    subtitle = title if not relations else f"{title} • {relations[0].replace('<@', '@').replace('>', '')}"
    return await create_member_card(
        member,
        "Profile Card",
        subtitle,
        [
            ("Wallet", f"{format_coins(int(row['wallet']))} ¥"),
            ("Banque", f"{format_coins(int(row['bank']))} ¥"),
            ("Total", f"{format_coins(total)} ¥"),
            ("Niveau", str(int(row["level"]))),
            ("Prestige", str(int(row["prestige"]))),
            ("Badges", badges.replace("|", " • ")[:22]),
        ],
        accent=(255, 255, 255),
    )


async def create_rank_card_image(db: Database, member: discord.Member) -> BytesIO:
    row = db.get_profile(member.guild.id, member.id)
    next_level = int(row["level"]) * 120
    return await create_member_card(
        member,
        "Rank Card",
        f"{progress_bar(int(row['xp']), next_level)}  {int(row['xp'])}/{next_level} XP",
        [
            ("Niveau", str(int(row["level"]))),
            ("XP", f"{int(row['xp'])}/{next_level}"),
            ("Prestige", str(int(row["prestige"])),
            ),
            ("Rep", str(int(row["rep"]))),
            ("Daily", f"{int(row['streak_daily'])}j"),
            ("Banque max", f"{format_coins(int(row['bank_limit']))} ¥"),
        ],
        accent=(255, 255, 255),
    )


async def create_ship_card_image(member1: discord.Member, member2: discord.Member, score: int) -> BytesIO:
    width, height = 1100, 520
    img = _draw_card_background(width, height, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    left = _circle_crop(await _avatar_rgba(member1, 220))
    right = _circle_crop(await _avatar_rgba(member2, 220))
    img.alpha_composite(left, (130, 150))
    img.alpha_composite(right, (750, 150))
    title_font = _load_font(54)
    body_font = _load_font(30)
    draw.text((438, 130), "SHIP", font=title_font, fill=(25, 25, 28, 255))
    draw.text((470, 210), f"{score}%", font=_load_font(72), fill=(25, 25, 28, 255))
    _text(draw, (120, 392), member1.display_name, body_font, (40, 40, 45, 255), 18)
    _text(draw, (742, 392), member2.display_name, body_font, (40, 40, 45, 255), 18)
    draw.line((410, 272, 690, 272), fill=(210, 210, 215, 255), width=5)
    out = BytesIO()
    img.convert("RGB").save(out, "PNG", quality=95)
    out.seek(0)
    return out


# -----------------------------
# Views
# -----------------------------


class ShopCategorySelect(discord.ui.Select):
    def __init__(self, view: "ShopBrowserView"):
        options = [
            discord.SelectOption(label="Toute la boutique", value="all", emoji="🛍️"),
            discord.SelectOption(label="Boosts & upgrades", value="boosts", emoji="⚙️"),
            discord.SelectOption(label="Rôles prestige", value="roles", emoji="👑"),
            discord.SelectOption(label="Cosmétiques", value="cosmetics", emoji="🌸"),
        ]
        super().__init__(placeholder="Choisis une catégorie...", min_values=1, max_values=1, options=options)
        self.shop_view = view

    async def callback(self, interaction: discord.Interaction):
        self.shop_view.category = self.values[0]
        self.shop_view.page = 0
        self.shop_view.selected_item = None
        await self.shop_view.refresh(interaction)


class ShopItemSelect(discord.ui.Select):
    def __init__(self, view: "ShopBrowserView", entries: list[dict]):
        options = []
        for entry in entries[:25]:
            options.append(discord.SelectOption(
                label=entry["title"][:100],
                value=entry["key"],
                description=f"{format_coins(int(entry['price']))} ¥ • niveau {entry['required_level']}"[:100],
                emoji="👑" if entry["category"] == "roles" else ("⚙️" if entry["category"] == "boosts" else "🌸"),
            ))
        if not options:
            options = [discord.SelectOption(label="Aucun objet", value="none", description="Aucun objet dans cette catégorie")]
        super().__init__(placeholder="Choisis un objet...", min_values=1, max_values=1, options=options)
        self.shop_view = view

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            return await interaction.response.send_message("Aucun objet dans cette catégorie.", ephemeral=True)
        self.shop_view.selected_item = self.values[0]
        entry = next((entry for entry in get_shop_entries(self.shop_view.bot.db, interaction.guild.id) if entry["key"] == self.values[0]), None)
        if entry is None:
            return await interaction.response.send_message("Objet introuvable.", ephemeral=True)
        embed = build_embed(entry["title"], entry["description"])
        embed.add_field(name="Prix", value=f"{format_coins(int(entry['price']))} ¥")
        embed.add_field(name="Niveau requis", value=str(entry["required_level"]))
        embed.add_field(name="Clé", value=f"`{entry['key']}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class ShopBrowserView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", guild_id: int, category: str = "all", page: int = 0):
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.category = category
        self.page = page
        self.selected_item: Optional[str] = None
        self.rebuild_items()

    def rebuild_items(self):
        self.clear_items()
        self.add_item(ShopCategorySelect(self))
        entries = get_shop_entries(self.bot.db, self.guild_id)
        if self.category != "all":
            entries = [entry for entry in entries if entry["category"] == self.category]
        per_page = 6
        total_pages = max(1, (len(entries) + per_page - 1) // per_page)
        self.page = max(0, min(self.page, total_pages - 1))
        entries = entries[self.page * per_page:(self.page + 1) * per_page]
        self.add_item(ShopItemSelect(self, entries))
        self.add_item(self.prev_button)
        self.add_item(self.next_button)
        self.add_item(self.buy_button)
        self.add_item(self.refresh_button)

    async def refresh(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        embed, _, total_pages = build_shop_page_embed(self.bot, interaction.guild, interaction.user, self.category, self.page)
        self.page = max(0, min(self.page, total_pages - 1))
        self.rebuild_items()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        await self.refresh(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        await self.refresh(interaction)

    @discord.ui.button(label="Acheter", style=discord.ButtonStyle.green, emoji="💸")
    async def buy_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.selected_item:
            return await interaction.response.send_message("Choisis d'abord un objet dans le menu.", ephemeral=True)
        economy_cog = interaction.client.get_cog("Economy")
        if economy_cog is None:
            return await interaction.response.send_message("Module économie introuvable.", ephemeral=True)
        await economy_cog.buy_from_key(interaction, self.selected_item)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.blurple, emoji="🔄")
    async def refresh_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.refresh(interaction)


class ShopLaunchView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ouvrir la boutique", style=discord.ButtonStyle.green, emoji="🛍️", custom_id="uzumaki:shop:open")
    async def open_shop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Utilisable seulement en serveur.", ephemeral=True)
        embed, _, _ = build_shop_page_embed(self.bot, interaction.guild, interaction.user, "all", 0)
        await interaction.response.send_message(embed=embed, view=ShopBrowserView(self.bot, interaction.guild.id), ephemeral=True)

    @discord.ui.button(label="Mon inventaire", style=discord.ButtonStyle.secondary, emoji="🎒", custom_id="uzumaki:shop:inventory")
    async def open_inventory(self, interaction: discord.Interaction, button: discord.ui.Button):
        economy_cog = interaction.client.get_cog("Economy")
        if economy_cog is None or not interaction.guild:
            return await interaction.response.send_message("Module économie introuvable.", ephemeral=True)
        embed = economy_cog.build_inventory_embed(interaction.guild.id, interaction.user.id, interaction.user.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=None)
        self.bot = bot

    @discord.ui.button(label="Ouvrir un ticket", style=discord.ButtonStyle.green, emoji="🎫", custom_id="uzumaki:ticket:create")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Utilisable seulement en serveur.", ephemeral=True)

        existing = self.bot.db.get_open_ticket_for_user(interaction.guild.id, interaction.user.id)
        if existing:
            channel = interaction.guild.get_channel(int(existing["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message(f"Tu as déjà un ticket ouvert : {channel.mention}", ephemeral=True)

        reasons = _parse_ticket_reasons(self.bot.db.get_setting(interaction.guild.id, "ticket_reasons"))
        if reasons:
            await interaction.response.send_message(
                "Sélectionne une raison pour ton ticket :",
                view=TicketReasonSelectView(self.bot, interaction.guild, interaction.user, reasons),
                ephemeral=True,
            )
            return

        await interaction.response.send_modal(TicketCreationModal(self.bot, interaction.guild, interaction.user))


class TicketReasonSelect(discord.ui.Select):
    def __init__(self, bot: "UzumakiBot", guild: discord.Guild, author: discord.Member, reasons: list[str]):
        options = [
            discord.SelectOption(
                label=reason if len(reason) <= 100 else reason[:97] + "...",
                value=str(index),
                description=None,
            )
            for index, reason in enumerate(reasons[:25])
        ]
        super().__init__(placeholder="Sélectionne une raison", min_values=1, max_values=1, options=options, custom_id="uzumaki:ticket:reason")
        self.bot = bot
        self.guild = guild
        self.author = author
        self.reasons = reasons

    async def callback(self, interaction: discord.Interaction):
        selected_index = int(self.values[0])
        reason = self.reasons[selected_index] if selected_index < len(self.reasons) else None
        await interaction.response.send_modal(TicketCreationModal(self.bot, self.guild, self.author, reason))


class TicketReasonSelectView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", guild: discord.Guild, author: discord.Member, reasons: list[str]):
        super().__init__(timeout=120)
        self.add_item(TicketReasonSelect(bot, guild, author, reasons))


class TicketCreationModal(discord.ui.Modal, title="Ouvrir un ticket"):
    subject = discord.ui.TextInput(label="Sujet du ticket", placeholder="Résumé du problème", max_length=64, required=True)
    description = discord.ui.TextInput(label="Description", style=discord.TextStyle.paragraph, placeholder="Décris ton problème en détail", max_length=512, required=True)
    reason = discord.ui.TextInput(label="Raison", placeholder="Facultatif si pas de raison prédéfinie", max_length=128, required=False)

    def __init__(self, bot: "UzumakiBot", guild: discord.Guild, author: discord.Member, reason: Optional[str] = None):
        self.bot = bot
        self.guild = guild
        self.author = author
        self.selected_reason = reason
        super().__init__()
        if reason:
            self.reason.default = reason

    async def on_submit(self, interaction: discord.Interaction):
        category_id = self.bot.db.get_setting(self.guild.id, "ticket_category_id")
        if not category_id or not category_id.isdigit():
            return await interaction.response.send_message(
                "Aucune catégorie ticket configurée. Utilise /ticket setcategory pour définir une catégorie.",
                ephemeral=True,
            )

        category = self.guild.get_channel(int(category_id))
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.response.send_message(
                "La catégorie ticket configurée est introuvable ou n'est pas une catégorie.",
                ephemeral=True,
            )

        existing = self.bot.db.get_open_ticket_for_user(self.guild.id, self.author.id)
        if existing:
            channel = self.guild.get_channel(int(existing["channel_id"]))
            if isinstance(channel, discord.TextChannel):
                return await interaction.response.send_message(f"Tu as déjà un ticket ouvert : {channel.mention}", ephemeral=True)

        base_name = f"ticket-{self.author.name}-{self.author.discriminator}".lower()
        safe_name = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in base_name)
        safe_name = "-".join(part for part in safe_name.split("-") if part)[:80]
        channel_name = f"ticket-{safe_name}"

        overwrites = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            self.author: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
            self.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True),
        }
        staff_role_id = self.bot.db.get_setting(self.guild.id, "ticket_staff_role_id")
        staff_role = None
        if staff_role_id and staff_role_id.isdigit():
            staff_role = self.guild.get_role(int(staff_role_id))
            if isinstance(staff_role, discord.Role):
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_messages=True)

        channel = await self.guild.create_text_channel(
            name=channel_name,
            category=category,
            topic=f"Ticket créé par {self.author} - {self.subject.value}",
            overwrites=overwrites,
            reason="Nouveau ticket ouvert par ticket panel",
        )

        ticket_reason = self.reason.value.strip() or self.selected_reason
        self.bot.db.create_ticket_thread(
            self.guild.id,
            channel.id,
            self.author.id,
            self.subject.value.strip(),
            datetime.now(timezone.utc).isoformat(),
            ticket_reason,
        )

        embed = _build_ticket_embed(
            self.bot,
            self.guild,
            self.author,
            self.subject.value.strip(),
            self.description.value.strip(),
            ticket_reason,
            channel,
            staff_role,
        )
        embed.add_field(name="Statut", value="Ouvert", inline=True)
        embed.add_field(name="Staff assigné", value=staff_role.mention if staff_role else "Non configuré", inline=True)

        await channel.send(
            content=staff_role.mention if staff_role else None,
            embed=embed,
            view=TicketCloseView(self.bot),
        )
        await interaction.response.send_message(f"Ton ticket a été créé : {channel.mention}", ephemeral=True)


class TicketCloseView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", disabled: bool = False):
        super().__init__(timeout=None)
        self.bot = bot
        for child in self.children:
            if isinstance(child, discord.ui.Button) and child.custom_id == "uzumaki:ticket:close":
                child.disabled = disabled

    @discord.ui.button(label="Fermer le ticket", style=discord.ButtonStyle.red, custom_id="uzumaki:ticket:close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Utilisable seulement dans un salon de ticket.", ephemeral=True)

        ticket = self.bot.db.get_ticket_thread(interaction.guild.id, interaction.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await interaction.response.send_message("Ce salon n'est pas un ticket ouvert.", ephemeral=True)

        if interaction.user.id != int(ticket["user_id"]) and not is_staff(interaction.user, self.bot.db):
            return await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)

        self.bot.db.close_ticket_thread(
            interaction.guild.id,
            interaction.channel.id,
            datetime.now(timezone.utc).isoformat(),
        )

        await interaction.channel.edit(name=f"closed-{interaction.channel.name}", topic="Ticket fermé")
        ticket_owner = interaction.guild.get_member(int(ticket["user_id"]))
        if ticket_owner:
            await interaction.channel.set_permissions(ticket_owner, view_channel=False, send_messages=False)

        try:
            await interaction.message.edit(view=TicketCloseView(self.bot, disabled=True))
        except discord.HTTPException:
            pass

        await interaction.response.send_message("Ticket fermé avec succès.", ephemeral=True)


QOTD_LIST = [

    "Quel jeu tu pourrais relancer à n'importe quel moment ",
    "Ton perso fictif préféré de tous les temps ",
    "Tu préfères vocal chill, game night ou débat ",
    "Le meilleur opening que t'as écouté en boucle ",
    "Ton snack ultime pour une soirée Discord ",
    "Si tu pouvais vivre dans un univers fictif, lequel ",
    "Quel event tu veux voir plus souvent sur le serv ",
]

NEKOS_BEST_BASE_URL = "https://nekos.best/api/v2"
NEKOS_BEST_USER_AGENT = f"{BRAND_NAME}/1.0 DiscordBot"
CAT_GIF_BASE_URL = "https://cataas.com/cat/gif"
_COOLDOWN_SECONDS = 6
_GIF_CATEGORIES = {
    "hug": "hug",
    "kiss": "kiss",
    "pat": "pat",
    "slap": "slap",
    "cry": "cry",
    "dance": "dance",
    "sleep": "sleep",
    "bite": "bite",
    "poke": "poke",
    "cuddle": "cuddle",
    "highfive": "highfive",
    "blush": "blush",
    "wave": "wave",
    "bonk": "bonk",
    "neko": "neko",
    "waifu": "waifu",
    "smug": "smug",
    "baka": "baka",
    "happy": "happy",
    "wink": "wink",
    "kick": "kick",
    "shoot": "shoot",
    "angry": "angry",
    "handhold": "handhold",
}

MESSAGE_MISSION_TARGET = 25
MESSAGE_MISSION_REWARD = 280
MESSAGE_MISSION_XP = 35
ORE_ITEMS = {
    "coal": {"title": "Charbon", "value": 12, "weight": 42},
    "copper": {"title": "Cuivre", "value": 20, "weight": 32},
    "iron": {"title": "Fer", "value": 34, "weight": 24},
    "gold": {"title": "Or", "value": 85, "weight": 11},
    "ruby": {"title": "Rubis", "value": 150, "weight": 5},
    "diamond": {"title": "Diamant", "value": 240, "weight": 3},
    "obsidian": {"title": "Obsidienne", "value": 420, "weight": 1},
}


def ore_item_key(ore_key: str) -> str:
    return f"ore:{ore_key}"


def ore_label(item_key: str) -> str:
    ore_key = item_key.split(":", 1)[1] if item_key.startswith("ore:") else item_key
    return str(ORE_ITEMS.get(ore_key, {}).get("title", item_key))


def choose_ore_key() -> str:
    keys = list(ORE_ITEMS.keys())
    weights = [int(ORE_ITEMS[key]["weight"]) for key in keys]
    return random.choices(keys, weights=weights, k=1)[0]

_ACTION_LABELS = {
    "hug": "calin",
    "kiss": "bisou",
    "pat": "pat pat",
    "slap": "gifle cartoon",
    "cry": "drama",
    "dance": "danse",
    "sleep": "sieste",
    "bite": "mordillage",
    "poke": "poke",
    "cuddle": "gros calin",
    "highfive": "high five",
    "blush": "blush",
    "wave": "coucou",
    "bonk": "bonk",
    "duel": "duel",
    "kick": "kick",
    "shoot": "tir anime",
    "angry": "colere anime",
}

_ACTION_MESSAGES = {
    "hug": [
        "{user} fait un calin a {target}.",
        "{user} serre {target}.",
        "{user} prend {target} dans ses bras.",
    ],
    "kiss": [
        "{user} embrasse {target}.",
        "{user} fait un bisou a {target}.",
        "{user} vole un bisou a {target}.",
    ],
    "pat": [
        "{user} tapote la tete de {target}.",
        "{user} encourage {target}.",
        "{user} felicite {target}.",
    ],
    "slap": [
        "{user} met une claque a {target}.",
        "{user} claque {target}.",
        "{user} remet {target} en place.",
    ],
    "cry": [
        "{user} pleure en silence.",
        "{user} est triste.",
        "{user} craque un peu.",
    ],
    "dance": [
        "{user} lance une danse impeccable.",
        "{user} prend la piste comme dans un opening.",
        "{user} sort les moves du boss final.",
    ],
    "sleep": [
        "{user} va dormir.",
        "{user} s'endort en plein episode.",
        "{user} part recharger son energie.",
    ],
    "bite": [
        "{user} mordille {target}.",
        "{user} mord {target}.",
        "{user} croque {target}.",
    ],
    "poke": [
        "{user} poke {target}.",
        "{user} embete {target} avec un poke discret.",
        "{user} verifie si {target} est encore la.",
    ],
    "cuddle": [
        "{user} fait un gros calin a {target}.",
        "{user} se colle a {target}.",
        "{user} garde {target} contre lui.",
    ],
    "highfive": [
        "{user} tape dans la main de {target}.",
        "{user} celebre avec {target} en high five.",
        "{user} et {target} valident le moment.",
    ],
    "blush": [
        "{user} rougit d'un coup.",
        "{user} cache son visage, c'est trop mignon.",
        "{user} vient de prendre +10 en timidite.",
    ],
    "wave": [
        "{user} fait coucou a {target}.",
        "{user} salue {target} avec style.",
        "{user} dit bonjour a {target}.",
    ],
    "bonk": [
        "{user} bonk {target}.",
        "{user} remet {target} sur le droit chemin avec un bonk.",
        "{user} applique la justice cartoon sur {target}.",
    ],
}

_TITLE_THRESHOLDS = [
    (100, "Machine a calins", "hug"),
    (50, "Ambassadeur du bisou", "kiss"),
    (35, "Danger public", "slap"),
    (25, "Drama Queen", "cry"),
    (25, "Roi de la piste", "dance"),
]

MOOD_OPTIONS = [
    ("Chill", "sleep", "calme mais intouchable"),
    ("Solaire", "happy", "energie positive maximum"),
    ("Timide", "blush", "rougit mais garde le style"),
    ("Chaotique", "bonk", "pret a mettre l'ambiance"),
    ("Drama", "cry", "opening triste en fond"),
    ("Taquin", "smug", "petit sourire suspect"),
]


async def fetch_rp_gif(category: str) -> Optional[str]:
    endpoint = _GIF_CATEGORIES.get(category.lower())
    if endpoint is None:
        return None

    def _fetch() -> Optional[str]:
        request = Request(
            f"{NEKOS_BEST_BASE_URL}/{endpoint}",
            headers={"User-Agent": NEKOS_BEST_USER_AGENT},
        )
        with urlopen(request, timeout=4) as response:
            payload = json.loads(response.read().decode("utf-8"))
        results = payload.get("results") or []
        if not results:
            return None
        url = results[0].get("url")
        return str(url) if url else None

    try:
        return await asyncio.to_thread(_fetch)
    except (OSError, URLError, ValueError, KeyError, TimeoutError) as exc:
        logger.warning("Could not fetch  GIF from nekos.best/%s: %s", endpoint, exc)
        return None


def random_cat_gif_url() -> str:
    return f"{CAT_GIF_BASE_URL}t={random.randint(1, 1_000_000)}"


def rp_action_label(action: str) -> str:
    return _ACTION_LABELS.get(action.lower(), action.lower())


def rp_title_for(db: Database, guild_id: int, user_id: int) -> Optional[str]:
    for required, title, action in _TITLE_THRESHOLDS:
        if db.get_rp_sent_total(guild_id, user_id, action) >= required:
            return title
    total = db.get_rp_sent_total(guild_id, user_id)
    if total >= 150:
        return "Légende "
    return None


def template_context(
    guild: discord.Guild,
    *,
    member: Optional[discord.Member] = None,
    user: Optional[discord.abc.User] = None,
    target: Optional[discord.abc.User] = None,
    message: str = "",
) -> dict[str, object]:
    subject = member or target or (None if isinstance(user, str) else user)
    actor = user or member or target
    return {
        "server": guild.name,
        "member": subject.mention if subject else "",
        "member_name": getattr(subject, "display_name", ""),
        "user": actor if isinstance(actor, str) else (actor.mention if actor else ""),
        "user_name": actor if isinstance(actor, str) else getattr(actor, "display_name", ""),
        "target": target.mention if target else (member.mention if member else ""),
        "target_name": getattr(target or member, "display_name", ""),
        "message": message,
        "count": guild.member_count or 0,
        "boosts": guild.premium_subscription_count or 0,
    }


def render_template_text(raw: str, context: dict[str, object]) -> str:
    try:
        return raw.format(**context)
    except Exception:
        return raw


def build_managed_embed(
    db: Database,
    guild: discord.Guild,
    kind: str,
    *,
    default_title: str,
    default_description: str,
    member: Optional[discord.Member] = None,
    user: Optional[discord.abc.User] = None,
    target: Optional[discord.abc.User] = None,
    message: str = "",
) -> discord.Embed:
    context = template_context(guild, member=member, user=user, target=target, message=message)
    title = db.get_setting(guild.id, f"{kind}_embed_title") or default_title
    description = db.get_setting(guild.id, f"{kind}_embed_description") or default_description
    embed = build_embed(
        render_template_text(title, context)[:256],
        render_template_text(description, context)[:4000],
    )

    thumbnail = db.get_setting(guild.id, f"{kind}_embed_thumbnail_url")
    image_url = db.get_setting(guild.id, f"{kind}_embed_image_url")
    if thumbnail:
        thumbnail = render_template_text(thumbnail, context).strip()
        if thumbnail.lower() not in {"none", "off", "no"}:
            embed.set_thumbnail(url=thumbnail)
    elif member:
        embed.set_thumbnail(url=member.display_avatar.url)

    if image_url:
        image_url = render_template_text(image_url, context).strip()
        if image_url.lower() not in {"none", "off", "no"}:
            embed.set_image(url=image_url)
    return embed


def save_managed_embed_settings(
    db: Database,
    guild_id: int,
    kind: str,
    title: str,
    description: str,
    image_url: Optional[str] = None,
):
    db.set_setting(guild_id, f"{kind}_embed_title", title[:256])
    db.set_setting(guild_id, f"{kind}_embed_description", description[:4000])
    if image_url is not None:
        db.set_setting(guild_id, f"{kind}_embed_image_url", image_url.strip()[:1000])


class ActionView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", action: str, actor_id: int, target_id: int):
        super().__init__(timeout=120)
        self.bot = bot
        self.action = action
        self.actor_id = actor_id
        self.target_id = target_id

    async def _target_only(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.target_id:
            return True
        await interaction.response.send_message("Seule la personne visee peut utiliser ces boutons.", ephemeral=True)
        return False

    async def _send_button_embed(self, interaction: discord.Interaction, title: str, description: str, gif_category: Optional[str] = None):
        embed = build_embed(title, description)
        gif_url = await fetch_rp_gif(gif_category or self.action)
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        label = rp_action_label(self.action)
        await self._send_button_embed(
            interaction,
            "Action acceptee",
            f"<@{self.target_id}> accepte le {label} de <@{self.actor_id}>.",
        )

    @discord.ui.button(label="Renvoyer", style=discord.ButtonStyle.blurple)
    async def return_action(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        label = rp_action_label(self.action)
        embed = build_embed("Action renvoyee", f"<@{self.target_id}> renvoie le {label} a <@{self.actor_id}>.")
        if interaction.guild:
            count = self.bot.db.record_rp_action(interaction.guild.id, self.target_id, self.actor_id, self.action)
            embed.add_field(name="Compteur", value=f"{label} renvoye **{count}** fois.", inline=False)
        gif_url = await fetch_rp_gif(self.action)
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @discord.ui.button(label="Repondre", style=discord.ButtonStyle.secondary)
    async def reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        await self._send_button_embed(
            interaction,
            "Reponse ",
            f"<@{self.target_id}> repond a <@{self.actor_id}> avec une reaction anime.",
            random.choice(["happy", "wink", "smug"]),
        )

    @discord.ui.button(label="Esquiver", style=discord.ButtonStyle.red)
    async def dodge(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        await self._send_button_embed(
            interaction,
            "Esquive",
            f"<@{self.target_id}> esquive le {rp_action_label(self.action)} de <@{self.actor_id}>.",
            "smug",
        )


class LoveConfessionView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", author_id: int, target_id: int, anonymous: bool = False):
        super().__init__(timeout=180)
        self.bot = bot
        self.author_id = author_id
        self.target_id = target_id
        self.anonymous = anonymous

    async def _target_only(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.target_id:
            return True
        await interaction.response.send_message("Seule la personne visee peut repondre a cette confession.", ephemeral=True)
        return False

    @discord.ui.button(label="Accepter", style=discord.ButtonStyle.green)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        author = "quelqu'un" if self.anonymous else f"<@{self.author_id}>"
        embed = build_embed("Confession acceptee", f"<@{self.target_id}> accepte la confession de {author}.")
        gif_url = await fetch_rp_gif("happy")
        if gif_url:
            embed.set_image(url=gif_url)
        if interaction.guild:
            self.bot.db.set_setting(interaction.guild.id, f"love:last:{self.author_id}", str(self.target_id))
        await interaction.response.edit_message(embed=embed, view=None)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.red)
    async def refuse(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._target_only(interaction):
            return
        author = "quelqu'un" if self.anonymous else f"<@{self.author_id}>"
        embed = build_embed("Confession refusee", f"<@{self.target_id}> refuse gentiment la confession de {author}.")
        gif_url = await fetch_rp_gif("cry")
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.edit_message(embed=embed, view=None)


class ConfessionReplyModal(discord.ui.Modal, title="Répondre au message anonyme"):
    def __init__(self, bot: "UzumakiBot", original_author_id: int, target_id: int, anonymous: bool = False):
        super().__init__()
        self.bot = bot
        self.original_author_id = original_author_id
        self.target_id = target_id
        self.anonymous = anonymous

    reply = discord.ui.TextInput(
        label="Ta réponse",
        placeholder="Écris ta réponse au message anonyme...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        author_text = "Quelqu'un" if self.anonymous else interaction.user.mention
        embed = build_embed(
            "💌 Réponse au message",
            f"**De :** {author_text}\n**À :** <@{self.original_author_id}>\n\n**Message :**\n{self.reply.value}"
        )
        embed.set_footer(text=f"Réponse au message de <@{self.original_author_id}>")

        channel = get_confession_channel(self.bot, interaction.guild)
        if channel is None and isinstance(interaction.channel, discord.TextChannel):
            channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message("Impossible d'envoyer le message dans ce salon.", ephemeral=True)

        if self.anonymous and isinstance(channel, discord.TextChannel):
            # Use webhook for anonymous reply
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if webhook:
                await webhook.send(embed=embed, username="Anonymous", avatar_url=None)
            else:
                await channel.send(embed=embed)
        else:
            await channel.send(embed=embed)
        await interaction.response.send_message("Ta réponse a été envoyée ! 💌", ephemeral=True)


class ConfessionCreateModal(discord.ui.Modal, title="Envoyer un message anonyme"):
    def __init__(self, bot: "UzumakiBot", anonymous: bool = False):
        super().__init__()
        self.bot = bot
        self.anonymous = anonymous

    target = discord.ui.TextInput(
        label="À qui ? (optionnel)",
        placeholder="@mentionne la personne ou laisse vide pour message général",
        max_length=100,
        required=False
    )

    message = discord.ui.TextInput(
        label="Ton message",
        placeholder="Écris ton message anonyme...",
        style=discord.TextStyle.paragraph,
        max_length=500,
        required=True
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Essayer de trouver le membre si spécifié
        target_member = None
        target_input = self.target.value.strip() if self.target.value else ""

        if target_input:
            # Chercher par mention
            if target_input.startswith('<@') and target_input.endswith('>'):
                user_id = target_input[2:-1]
                if user_id.startswith('!'):
                    user_id = user_id[1:]
                try:
                    target_member = interaction.guild.get_member(int(user_id))
                except:
                    pass
            else:
                # Chercher par nom
                for member in interaction.guild.members:
                    if member.display_name.lower() == target_input.lower() or member.name.lower() == target_input.lower():
                        target_member = member
                        break

            if not target_member:
                return await interaction.response.send_message("Je n'ai pas trouvé cette personne sur le serveur.", ephemeral=True)

            if target_member.bot or target_member.id == interaction.user.id:
                return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)

        # Créer l'embed selon si c'est un message général ou à quelqu'un
        if target_member:
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "confession",
                default_title="📝 Nouveau Message Anonyme",
                default_description="{user} envoie un message anonyme à {member}.\n\n**Message :** {message}",
                member=target_member,
                user="Quelqu'un" if self.anonymous else interaction.user,
                message=self.message.value.strip()[:300],
            )
            if self.anonymous:
                embed._author = None
                if not self.bot.db.get_setting(interaction.guild.id, "confession_embed_description"):
                    embed.description = f"Quelqu'un envoie un message anonyme à {target_member.mention}.\n\n**Message :** {self.message.value.strip()[:300]}"
        else:
            # Message général
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "confession",
                default_title="📝 Nouveau Message Anonyme",
                default_description="Quelqu'un partage un message anonyme.\n\n**Message :** {message}",
                member=None,
                user="Quelqu'un" if self.anonymous else interaction.user,
                message=self.message.value.strip()[:300],
            )
            if self.anonymous:
                embed._author = None
                if not self.bot.db.get_setting(interaction.guild.id, "confession_embed_description"):
                    embed.description = f"Quelqu'un partage un message anonyme.\n\n**Message :** {self.message.value.strip()[:300]}"

        view = PublicConfessionView(self.bot, interaction.user.id, target_member.id if target_member else 0, anonymous=self.anonymous)

        channel = get_confession_channel(self.bot, interaction.guild)
        if channel is None and isinstance(interaction.channel, discord.TextChannel):
            channel = interaction.channel
        if channel is None:
            return await interaction.response.send_message("Impossible d'envoyer ton message dans ce salon.", ephemeral=True)

        if self.anonymous and isinstance(channel, discord.TextChannel):
            # Use webhook for anonymous message
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if not webhook:
                try:
                    webhook = await channel.create_webhook(name="Anonymous Confessions")
                except discord.Forbidden:
                    await channel.send(embed=embed, view=view)
                else:
                    await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
            else:
                await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
        else:
            await channel.send(embed=embed, view=view)
        await interaction.response.send_message(f"Ton message a été envoyé dans {channel.mention} ! 📝", ephemeral=True)


class PublicConfessionView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot", author_id: int, target_id: int, anonymous: bool = False):
        super().__init__(timeout=180)
        self.bot = bot
        self.author_id = author_id
        self.target_id = target_id
        self.anonymous = anonymous

    @discord.ui.button(label="💬 Répondre", style=discord.ButtonStyle.primary, emoji="💌")
    async def reply(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvrir un modal pour répondre
        modal = ConfessionReplyModal(self.bot, self.author_id, self.target_id, self.anonymous)
        await interaction.response.send_modal(modal)

    @discord.ui.button(label="📝 Nouveau message", style=discord.ButtonStyle.secondary, emoji="✨")
    async def make_confession(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Ouvrir un modal pour faire un nouveau message
        modal = ConfessionCreateModal(self.bot, self.anonymous)
        await interaction.response.send_modal(modal)


class GameSelect(discord.ui.Select):
    def __init__(self, bot: "UzumakiBot"):
        options = [
            discord.SelectOption(label="Lancer un dé", value="dice", emoji="🎲", description="Un lancer rapide"),
            discord.SelectOption(label="Daily", value="daily", emoji="💸", description="Récupère tes pièces"),
            discord.SelectOption(label="Boutique", value="shop", emoji="🛍️", description="Voir les achats du serveur"),
        ]
        super().__init__(
            placeholder="Choisis une action...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="uzumaki:hub:select",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        choice = self.values[0]
        if choice == "dice":
            return await interaction.response.send_message(embed=build_embed("🎲 Lancer de dé", f"Tu as obtenu **{random.randint(1, 6)}**."), ephemeral=True)
        if choice == "qotd":
            return await interaction.response.send_message(embed=build_embed("Question du jour", random.choice(QOTD_LIST)), ephemeral=True)
        if choice == "daily":
            _, embed = claim_daily(self.bot.db, interaction.guild.id, interaction.user.id)
            return await interaction.response.send_message(embed=embed, ephemeral=True)
        if choice == "shop":
            embed, _, _ = build_shop_page_embed(self.bot, interaction.guild, interaction.user, "all", 0)
            return await interaction.response.send_message(embed=embed, view=ShopBrowserView(self.bot, interaction.guild.id), ephemeral=True)


class AnimationHubView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(GameSelect(bot))

    @discord.ui.button(label="Mon profil", style=discord.ButtonStyle.blurple, emoji="👤", custom_id="uzumaki:hub:profile")
    async def profile_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Utilisable seulement en serveur.", ephemeral=True)
        await interaction.response.send_message(embed=build_profile_embed(self.bot.db, interaction.user), ephemeral=True)

    @discord.ui.button(label="Daily", style=discord.ButtonStyle.green, emoji="💸", custom_id="uzumaki:hub:daily")
    async def daily_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        _, embed = claim_daily(self.bot.db, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Shop", style=discord.ButtonStyle.secondary, emoji="🛍️", custom_id="uzumaki:hub:shop")
    async def shop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed, _, _ = build_shop_page_embed(self.bot, interaction.guild, interaction.user, "all", 0)
        await interaction.response.send_message(embed=embed, view=ShopBrowserView(self.bot, interaction.guild.id), ephemeral=True)


class HelpCategorySelect(discord.ui.Select):
    def __init__(self, bot: "UzumakiBot"):
        options = [
            discord.SelectOption(label="Vue d'ensemble", value="overview", emoji="📌"),
            discord.SelectOption(label="Interactions", value="actions", emoji="✨"),
            discord.SelectOption(label="Économie", value="economy", emoji="💰"),
            discord.SelectOption(label="Jeux", value="games", emoji="🎮"),
            discord.SelectOption(label="Anime", value="anime", emoji="🎭"),
            discord.SelectOption(label="Utilitaires", value="util", emoji="🛠️"),
            discord.SelectOption(label="Events", value="events", emoji="📅"),
        ]
        super().__init__(
            placeholder="Choisis une catégorie d'aide...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="uzumaki:help:category",
        )
        self.bot = bot

    async def callback(self, interaction: discord.Interaction):
        category = self.values[0]
        if category == "overview":
            embed = build_embed("Aide générale", "Bot communautaire pour animer Uzumaki avec slash commands, boutons, panels et économie.")
            embed.add_field(name="Commandes clés", value="`/hub` `/help` `/serverinfo` `/userinfo` `/avatar`", inline=False)
        elif category == "actions":
            embed = build_embed("Interactions", "Commandes simples visibles pour les membres.")
            embed.add_field(name="Actions", value="`/rp kiss` `/rp hug` `/rp pat` `/rp slap` `/rp highfive` `/image wanted` `/image jailcard`", inline=False)
        elif category == "economy":
            embed = build_embed("Économie", "Système profond avec banque, upgrades, boutique, prestige et mini-jeux d'argent.")
            embed.add_field(name="Économie", value="`/daily` `/weekly` `/missions` `/claimmission` `/work` `/mine` `/ores` `/sellores` `/balance` `/bank` `/deposit` `/withdraw` `/interest` `/shop` `/buy` `/inventory` `/sell` `/prestige` `/rank` `/rep`", inline=False)
        elif category == "games":
            embed = build_embed("Jeux", "Activités amusantes pour gagner des récompenses ou simplement s'amuser.")
            embed.add_field(name="Mini-jeux", value="`/dice` `/rps` `/roulette` `/coinflip` `/guessnumber` `/duel` `/ship` `/rate`", inline=False)
        elif category == "anime":
            embed = build_embed("Anime & fun", "Images et réactions animées à partager en serveur.")
            embed.add_field(name="Anime", value="`/anime quote` `/anime waifu` `/anime neko` `/anime smug` `/anime baka` `/anime fight` `/mood`", inline=False)
        elif category == "util":
            embed = build_embed("Utilitaires", "Commandes pratiques pour gérer le serveur et trouver des informations.")
            embed.add_field(name="Utilitaires", value="`/serverinfo` `/userinfo` `/avatar` `/profile` `/balance` `/help` `/hub`", inline=False)
        else:
            embed = build_embed("Events", "Lance des activités directement depuis Discord")
            embed.add_field(name="Events", value="`/event` pour poster un event avec boutons RSVP", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class HelpPanelView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=None)
        self.bot = bot
        self.add_item(HelpCategorySelect(bot))

    @discord.ui.button(label="Ouvrir le hub", style=discord.ButtonStyle.blurple, emoji="🌀", custom_id="uzumaki:help:hub")
    async def open_hub(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = build_embed("Centre d'animation", "Utilise ce panneau pour lancer les actions principales du bot.")
        await interaction.response.send_message(embed=embed, view=AnimationHubView(self.bot), ephemeral=True)


async def refresh_event_embed(bot: "UzumakiBot", message: discord.Message):
    if not message.embeds:
        return
    counts = bot.db.get_rsvp_counts(message.id)
    embed = discord.Embed.from_dict(message.embeds[0].to_dict())
    stats_value = (
        f"✅ Intéressé : **{counts['yes']}**\n"
        f"🤔 Peut-être : **{counts['maybe']}**\n"
        f"❌ Indisponible : **{counts['no']}**"
    )
    field_index = None
    for idx, field in enumerate(embed.fields):
        if field.name == "Participants":
            field_index = idx
            break
    if field_index is None:
        embed.add_field(name="Participants", value=stats_value, inline=False)
    else:
        embed.set_field_at(field_index, name="Participants", value=stats_value, inline=False)
    await message.edit(embed=embed, view=EventRSVPView(bot))


class EventRSVPView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=None)
        self.bot = bot

    async def _save(self, interaction: discord.Interaction, status: str, label: str):
        if not interaction.message:
            return await interaction.response.send_message("Message introuvable.", ephemeral=True)
        self.bot.db.set_rsvp(interaction.message.id, interaction.user.id, status)
        await refresh_event_embed(self.bot, interaction.message)
        await interaction.response.send_message(f"Ton statut a été mis à jour : **{label}**.", ephemeral=True)

    @discord.ui.button(label="Intéressé", style=discord.ButtonStyle.green, emoji="✅", custom_id="uzumaki:event:yes")
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._save(interaction, "yes", "Intéressé")

    @discord.ui.button(label="Peut-être", style=discord.ButtonStyle.secondary, emoji="🤔", custom_id="uzumaki:event:maybe")
    async def maybe(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._save(interaction, "maybe", "Peut-être")

    @discord.ui.button(label="Indisponible", style=discord.ButtonStyle.red, emoji="❌", custom_id="uzumaki:event:no")
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._save(interaction, "no", "Indisponible")


def build_config_panel_embed(bot: "UzumakiBot", guild: discord.Guild) -> discord.Embed:
    embed = build_embed("Config panel", "Choisis un réglage dans le menu puis remplis le formulaire.")
    keys = [
        ("Welcome", "welcome_channel_id"),
        ("Boosts", "boost_channel_id"),
        ("Confessions", "confession_channel_id"),
        ("Logs", "log_channel_id"),
        ("Annonces", "announce_channel_id"),
        ("Niveaux", "level_channel_id"),
        ("Autorole", "autorole_id"),
    ]
    for label, key in keys:
        raw = bot.db.get_setting(guild.id, key)
        value = "Non configuré"
        if raw and raw.isdigit():
            value = f"<#{raw}>" if "channel" in key else f"<@&{raw}>"
        embed.add_field(name=label, value=value, inline=True)
    embed.add_field(name="Welcome custom", value="Configuré" if bot.db.get_setting(guild.id, "welcome_message") else "Non configuré", inline=False)
    embed.add_field(name="Welcome embed", value="Configure" if bot.db.get_setting(guild.id, "welcome_embed_description") or bot.db.get_setting(guild.id, "welcome_message") else "Non configure", inline=True)
    embed.add_field(name="Boost embed", value="Configure" if bot.db.get_setting(guild.id, "boost_embed_description") else "Non configure", inline=True)
    embed.add_field(name="Confession embed", value="Configure" if bot.db.get_setting(guild.id, "confession_embed_description") else "Non configure", inline=True)
    return embed


class ConfigValueModal(discord.ui.Modal):
    def __init__(self, bot: "UzumakiBot", setting_key: str, title: str, label: str, placeholder: str, max_length: int = 1000):
        super().__init__(title=title)
        self.bot = bot
        self.setting_key = setting_key
        self.value = discord.ui.TextInput(label=label, placeholder=placeholder, max_length=max_length, required=True)
        self.add_item(self.value)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, self.bot.db):
            return await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, self.setting_key, str(self.value.value).strip())
        embed = build_config_panel_embed(self.bot, interaction.guild)
        await interaction.response.send_message("Configuration mise à jour.", embed=embed, view=ConfigPanelView(self.bot), ephemeral=True)


class LevelRewardModal(discord.ui.Modal):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(title="Récompense de niveau")
        self.bot = bot
        self.level = discord.ui.TextInput(label="Niveau", placeholder="Ex: 10", max_length=3, required=True)
        self.role_id = discord.ui.TextInput(label="ID du rôle", placeholder="Ex: 123456789012345678", max_length=24, required=True)
        self.add_item(self.level)
        self.add_item(self.role_id)

    async def on_submit(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, self.bot.db):
            return await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
        level = str(self.level.value).strip()
        role_id = str(self.role_id.value).strip()
        if not level.isdigit() or not role_id.isdigit():
            return await interaction.response.send_message("Le niveau et l'ID rôle doivent être numériques.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, f"level_reward:{int(level)}", role_id)
        await interaction.response.send_message(f"Récompense niveau **{level}** configurée sur <@&{role_id}>.", ephemeral=True)


class ConfigActionSelect(discord.ui.Select):
    def __init__(self, bot: "UzumakiBot"):
        self.bot = bot
        options = [
            discord.SelectOption(label="Salon welcome", value="welcome_channel_id", description="Colle l'ID du salon de bienvenue"),
            discord.SelectOption(label="Salon boosts", value="boost_channel_id", description="Colle l'ID du salon de boosts"),
            discord.SelectOption(label="Salon confessions", value="confession_channel_id", description="Colle l'ID du salon de confessions"),
            discord.SelectOption(label="Salon logs", value="log_channel_id", description="Colle l'ID du salon de logs"),
            discord.SelectOption(label="Salon annonces", value="announce_channel_id", description="Colle l'ID du salon d'annonces"),
            discord.SelectOption(label="Salon niveaux", value="level_channel_id", description="Colle l'ID du salon level up"),
            discord.SelectOption(label="Autorole", value="autorole_id", description="Colle l'ID du rôle auto"),
            discord.SelectOption(label="Message bienvenue", value="welcome_message", description="Variables: {member}, {server}"),
            discord.SelectOption(label="Récompense niveau", value="level_reward", description="Niveau + ID rôle"),
        ]
        super().__init__(placeholder="Sélectionne un réglage à modifier", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.user, discord.Member) or not is_staff(interaction.user, self.bot.db):
            return await interaction.response.send_message("Tu n'as pas la permission.", ephemeral=True)
        value = self.values[0]
        if value == "level_reward":
            return await interaction.response.send_modal(LevelRewardModal(self.bot))
        labels = {
            "welcome_channel_id": ("Salon welcome", "ID du salon", "Colle l'ID du salon welcome"),
            "boost_channel_id": ("Salon boosts", "ID du salon", "Colle l'ID du salon boosts"),
            "confession_channel_id": ("Salon confessions", "ID du salon", "Colle l'ID du salon confessions"),
            "log_channel_id": ("Salon logs", "ID du salon", "Colle l'ID du salon logs"),
            "announce_channel_id": ("Salon annonces", "ID du salon", "Colle l'ID du salon annonces"),
            "level_channel_id": ("Salon niveaux", "ID du salon", "Colle l'ID du salon niveaux"),
            "autorole_id": ("Autorole", "ID du rôle", "Colle l'ID du rôle auto"),
            "welcome_message": ("Message bienvenue", "Message", "Bienvenue {member} sur {server}"),
        }
        title, label, placeholder = labels[value]
        return await interaction.response.send_modal(ConfigValueModal(self.bot, value, title, label, placeholder))


class ConfigPanelView(discord.ui.View):
    def __init__(self, bot: "UzumakiBot"):
        super().__init__(timeout=300)
        self.bot = bot
        self.add_item(ConfigActionSelect(bot))

    @discord.ui.button(label="Actualiser", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        await interaction.response.edit_message(embed=build_config_panel_embed(self.bot, interaction.guild), view=ConfigPanelView(self.bot))


# -----------------------------
# Music player
# -----------------------------


MUSIC_YTDL_OPTIONS = {
    "format": "bestaudio[ext=m4a]/bestaudio/best",
    "default_search": "ytsearch1",
    "noplaylist": True,
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "source_address": "0.0.0.0",
}

MUSIC_FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn -loglevel warning",
}


class MusicError(Exception):
    pass


@dataclass
class MusicTrack:
    title: str
    webpage_url: str
    duration: Optional[int]
    requester_id: int
    stream_url: str = ""
    thumbnail: Optional[str] = None
    source: str = "YouTube"
    search_query: str = ""
    youtube_url: str = ""

    @property
    def requester_mention(self) -> str:
        return f"<@{self.requester_id}>"


@dataclass
class MusicLoadResult:
    tracks: list[MusicTrack]
    source_name: str = "YouTube"
    playlist_name: Optional[str] = None


class MusicState:
    def __init__(self):
        self.queue: deque[MusicTrack] = deque()
        self.current: Optional[MusicTrack] = None
        self.volume: float = 0.55
        self.loop: bool = False
        self.repeat_mode: str = "off"
        self.autoplay: bool = False
        self.shuffle: bool = False
        self.history: deque[MusicTrack] = deque(maxlen=25)
        self.skip_requested: bool = False
        self.stop_requested: bool = False
        self.text_channel_id: int = 0
        self.panel_channel_id: int = 0
        self.panel_message_id: int = 0
        self.vote_skip_ids: set[int] = set()
        self.started_at: Optional[datetime] = None
        self.paused_at: Optional[datetime] = None
        self.elapsed_offset: int = 0
        self.progress_task: Optional[asyncio.Task] = None


def format_music_duration(duration: Optional[int]) -> str:
    if not duration:
        return "live"
    duration = int(duration)
    hours, remainder = divmod(duration, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def format_music_progress(elapsed: int, duration: Optional[int], size: int = 18) -> str:
    if not duration:
        return "[live]"
    elapsed = max(0, min(int(duration), int(elapsed)))
    filled = max(0, min(size, round((elapsed / max(duration, 1)) * size)))
    return f"[{'=' * filled}{'-' * (size - filled)}] {format_music_duration(elapsed)} / {format_music_duration(duration)}"


def _music_get_json(url: str) -> dict:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Uzumaki music bot)"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _music_get_text(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 (Uzumaki music bot)"})
    with urlopen(request, timeout=15) as response:
        return response.read().decode("utf-8", errors="replace")


def _music_post_json(url: str, data: dict[str, str], headers: Optional[dict[str, str]] = None) -> dict:
    body = urlencode(data).encode("utf-8")
    request_headers = {"User-Agent": "Mozilla/5.0 (Uzumaki music bot)", "Content-Type": "application/x-www-form-urlencoded"}
    if headers:
        request_headers.update(headers)
    request = Request(url, data=body, headers=request_headers, method="POST")
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def _first_music_image(*values) -> Optional[str]:
    for value in values:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
        if isinstance(value, list):
            images = [item for item in value if isinstance(item, dict) and item.get("url")]
            if images:
                images.sort(key=lambda item: int(item.get("maxHeight") or item.get("height") or 0), reverse=True)
                return str(images[0]["url"])
        if isinstance(value, dict):
            sources = value.get("sources")
            if isinstance(sources, list):
                found = _first_music_image(sources)
                if found:
                    return found
            image = value.get("image")
            if isinstance(image, list):
                found = _first_music_image(image)
                if found:
                    return found
            for key in ("picture_xl", "picture_big", "cover_xl", "cover_big", "thumbnail_url", "url"):
                image_url = value.get(key)
                if isinstance(image_url, str) and image_url.startswith(("http://", "https://")):
                    return image_url
    return None


def _spotify_match(url: str) -> Optional[re.Match]:
    return re.search(r"open\.spotify\.com/(?:intl-[a-z]{2}/)?(track|playlist|album)/([A-Za-z0-9]+)", url)


def _deezer_match(url: str) -> Optional[re.Match]:
    return re.search(r"deezer\.com/(?:[a-z]{2}/)?(track|playlist|album)/(\d+)", url)


class Music(commands.Cog):
    music = app_commands.Group(name="music", description="Connecte le bot en vocal et joue de la musique")

    def __init__(self, bot: "UzumakiBot"):
        self.bot = bot
        self.states: dict[int, MusicState] = {}

    def _state(self, guild_id: int) -> MusicState:
        state = self.states.get(guild_id)
        if state is None:
            state = MusicState()
            self.states[guild_id] = state
        return state

    def _voice_client(self, guild: discord.Guild) -> Optional[discord.VoiceClient]:
        voice = guild.voice_client
        return voice if isinstance(voice, discord.VoiceClient) else None

    def _configured_music_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        raw = self.bot.db.get_setting(guild.id, "music_channel_id")
        if raw and raw.isdigit():
            channel = guild.get_channel(int(raw))
            if isinstance(channel, discord.TextChannel):
                return channel
        return None

    def _music_setting_int(self, guild_id: int, key: str, default: int, minimum: int, maximum: int) -> int:
        raw = self.bot.db.get_setting(guild_id, key)
        try:
            value = int(raw) if raw not in (None, "") else int(default)
        except (TypeError, ValueError):
            value = int(default)
        return max(minimum, min(maximum, value))

    def _music_setting_bool(self, guild_id: int, key: str, default: bool = False) -> bool:
        raw = self.bot.db.get_setting(guild_id, key)
        if raw is None or raw == "":
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on", "oui", "active"}

    def _dj_role(self, guild: discord.Guild) -> Optional[discord.Role]:
        raw = self.bot.db.get_setting(guild.id, "music_dj_role_id")
        if raw and raw.isdigit():
            return guild.get_role(int(raw))
        return None

    def _is_music_dj(self, member: discord.Member) -> bool:
        if member.guild.owner_id == member.id:
            return True
        if is_staff(member, self.bot.db) or member.guild_permissions.manage_guild:
            return True
        role = self._dj_role(member.guild)
        return bool(role and role in member.roles)

    def _music_output_channel_id(self, guild: discord.Guild, fallback_channel_id: int = 0) -> int:
        channel = self._configured_music_channel(guild)
        return channel.id if channel else fallback_channel_id

    def _listener_count(self, guild: discord.Guild) -> int:
        voice = self._voice_client(guild)
        if not voice or not voice.channel:
            return 0
        return sum(1 for member in voice.channel.members if not member.bot)

    def _vote_skip_threshold(self, guild: discord.Guild) -> int:
        listeners = self._listener_count(guild)
        percent = self._music_setting_int(guild.id, "music_voteskip_percent", 50, 1, 100)
        return max(1, (listeners * percent + 99) // 100)

    def _track_link(self, track: MusicTrack) -> str:
        title = discord.utils.escape_markdown(track.title)[:90]
        if track.webpage_url.startswith(("http://", "https://")):
            return f"[{title}]({track.webpage_url})"
        return f"**{title}**"

    def _build_track_embed(self, title: str, track: MusicTrack) -> discord.Embed:
        embed = build_embed(
            title,
            f"{self._track_link(track)}\nDuree : **{format_music_duration(track.duration)}**\nDemande par : {track.requester_mention}\nSource : **{track.source}**",
        )
        if track.thumbnail:
            embed.set_thumbnail(url=track.thumbnail)
        return embed

    def _track_elapsed_seconds(self, state: MusicState) -> int:
        if not state.started_at:
            return max(0, int(state.elapsed_offset))
        if state.paused_at:
            return max(0, int(state.elapsed_offset))
        return max(0, int(state.elapsed_offset + (utc_now() - state.started_at).total_seconds()))

    def _reset_track_clock(self, state: MusicState):
        state.started_at = None
        state.paused_at = None
        state.elapsed_offset = 0

    def _start_track_clock(self, state: MusicState):
        state.started_at = utc_now()
        state.paused_at = None
        state.elapsed_offset = 0

    def _pause_track_clock(self, state: MusicState):
        if state.paused_at:
            return
        state.elapsed_offset = self._track_elapsed_seconds(state)
        state.paused_at = utc_now()
        state.started_at = None

    def _resume_track_clock(self, state: MusicState):
        if not state.current:
            return
        state.started_at = utc_now()
        state.paused_at = None

    def _queue_page_count(self, guild_id: int) -> int:
        state = self._state(guild_id)
        return max(1, (len(state.queue) + 9) // 10)

    def _build_queue_embed(self, guild_id: int, page: int = 0) -> discord.Embed:
        state = self._state(guild_id)
        lines = []
        total_pages = self._queue_page_count(guild_id)
        page = max(0, min(page, total_pages - 1))
        if state.current:
            lines.append(f"En cours : {self._track_link(state.current)}")
        if state.queue:
            start = page * 10
            tracks = list(state.queue)[start:start + 10]
            for index, track in enumerate(tracks, start=start + 1):
                lines.append(f"`{index}.` {self._track_link(track)} - {format_music_duration(track.duration)}")
            if len(state.queue) > start + len(tracks):
                lines.append(f"... et {len(state.queue) - start - len(tracks)} autre(s) titre(s).")
        if not lines:
            lines.append("La file est vide.")
        embed = build_embed(f"File musique ({page + 1}/{total_pages})", "\n".join(lines))
        embed.add_field(name="Volume", value=f"{round(state.volume * 100)}%", inline=True)
        embed.add_field(name="Repeat", value=state.repeat_mode, inline=True)
        embed.add_field(name="En attente", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Autoplay", value="on" if state.autoplay else "off", inline=True)
        embed.add_field(name="Shuffle", value="on" if state.shuffle else "off", inline=True)
        return embed

    def _build_panel_embed(self, guild: discord.Guild, track: MusicTrack) -> discord.Embed:
        voice = self._voice_client(guild)
        connected = voice.channel.mention if voice and voice.channel else "Aucun vocal"
        state = self._state(guild.id)
        elapsed = self._track_elapsed_seconds(state)
        next_title = self._track_link(state.queue[0]) if state.queue else "Aucun titre en attente"
        mode_text = (
            f"Repeat: **{state.repeat_mode}** | "
            f"Autoplay: **{'on' if state.autoplay else 'off'}** | "
            f"Shuffle: **{'on' if state.shuffle else 'off'}**"
        )
        embed = build_embed(
            "Now playing",
            f"{self._track_link(track)}\n"
            f"`{format_music_progress(elapsed, track.duration)}`\n"
            f"Demandee par : {track.requester_mention}\n"
            f"Vocal : {connected}\n"
            f"{mode_text}",
        )
        embed.add_field(name="Source", value=track.source, inline=True)
        embed.add_field(name="Volume", value=f"{round(state.volume * 100)}%", inline=True)
        embed.add_field(name="Queue", value=str(len(state.queue)), inline=True)
        embed.add_field(name="Vote skip", value=f"{len(state.vote_skip_ids)}/{self._vote_skip_threshold(guild)}", inline=True)
        embed.add_field(name="Prochain titre", value=next_title, inline=False)
        embed.add_field(name="Favorites", value="Clique sur le bouton pour l'ajouter a tes favoris.", inline=False)
        if track.thumbnail:
            embed.set_image(url=track.thumbnail)
        return embed

    async def _show_player_panel(self, guild_id: int, track: MusicTrack, *, bump: bool = False):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        state = self._state(guild_id)
        channel = self.bot.get_channel(state.text_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return

        embed = self._build_panel_embed(guild, track)
        view = MusicPanelView(self, guild_id)

        if state.panel_message_id and state.panel_channel_id:
            panel_channel = self.bot.get_channel(state.panel_channel_id)
            if panel_channel is not None and hasattr(panel_channel, "fetch_message"):
                try:
                    message = await panel_channel.fetch_message(state.panel_message_id)
                    if bump:
                        await message.delete()
                    else:
                        await message.edit(embed=embed, view=view)
                        return
                except discord.HTTPException:
                    pass
            state.panel_message_id = 0
            state.panel_channel_id = 0

        try:
            message = await channel.send(embed=embed, view=view)
            state.panel_channel_id = message.channel.id
            state.panel_message_id = message.id
        except discord.HTTPException:
            logger.exception("Failed to send music panel")

    async def _refresh_player_panel(self, guild_id: int):
        state = self._state(guild_id)
        if state.current:
            await self._show_player_panel(guild_id, state.current, bump=False)

    async def _bump_player_panel(self, guild_id: int):
        state = self._state(guild_id)
        if state.current:
            await self._show_player_panel(guild_id, state.current, bump=True)

    async def _show_idle_panel(self, guild_id: int, message: str):
        state = self._state(guild_id)
        if not state.panel_message_id or not state.panel_channel_id:
            return
        panel_channel = self.bot.get_channel(state.panel_channel_id)
        if panel_channel is None or not hasattr(panel_channel, "fetch_message"):
            return
        try:
            panel_message = await panel_channel.fetch_message(state.panel_message_id)
            await panel_message.edit(embed=build_embed("Music player", message), view=MusicPanelView(self, guild_id))
        except discord.HTTPException:
            state.panel_message_id = 0
            state.panel_channel_id = 0

    def _cancel_progress_updater(self, guild_id: int):
        state = self._state(guild_id)
        task = state.progress_task
        if task and not task.done():
            task.cancel()
        state.progress_task = None

    def _start_progress_updater(self, guild_id: int):
        self._cancel_progress_updater(guild_id)
        state = self._state(guild_id)
        state.progress_task = asyncio.create_task(self._progress_updater(guild_id))

    async def _edit_existing_player_panel(self, guild_id: int):
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return
        state = self._state(guild_id)
        if not state.current or not state.panel_channel_id or not state.panel_message_id:
            return
        panel_channel = self.bot.get_channel(state.panel_channel_id)
        if not isinstance(panel_channel, discord.TextChannel):
            return
        try:
            message = panel_channel.get_partial_message(state.panel_message_id)
            await message.edit(embed=self._build_panel_embed(guild, state.current), view=MusicPanelView(self, guild_id))
        except discord.NotFound:
            state.panel_message_id = 0
            state.panel_channel_id = 0
        except discord.HTTPException:
            logger.debug("Music progress panel update failed", exc_info=True)

    async def _progress_updater(self, guild_id: int):
        try:
            while True:
                await asyncio.sleep(1)
                guild = self.bot.get_guild(guild_id)
                if not guild:
                    return
                state = self._state(guild_id)
                voice = self._voice_client(guild)
                if not state.current or (not state.started_at and not state.paused_at):
                    return
                if not voice or not voice.is_connected():
                    return
                if voice.is_paused():
                    continue
                if not voice.is_playing():
                    return
                await self._edit_existing_player_panel(guild_id)
        except asyncio.CancelledError:
            return

    async def _delete_later(self, message: Optional[discord.Message], guild_id: int):
        if message is None:
            return
        delay = self._music_setting_int(guild_id, "music_cleanup_seconds", 12, 0, 120)
        if delay <= 0:
            return
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except discord.HTTPException:
            pass

    def _track_to_dict(self, track: MusicTrack) -> dict:
        return {
            "title": track.title,
            "url": track.webpage_url or track.youtube_url or track.search_query or track.title,
            "duration": track.duration,
            "source": track.source,
            "thumbnail": track.thumbnail or "",
            "search_query": track.search_query or track.youtube_url or track.webpage_url or track.title,
        }

    def _track_from_saved(self, item: dict, requester_id: int) -> MusicTrack:
        title = str(item.get("title") or "Musique")
        url = str(item.get("url") or item.get("search_query") or title)
        source = str(item.get("source") or "YouTube")
        raw_duration = item.get("duration")
        try:
            duration = int(raw_duration) if raw_duration else None
        except (TypeError, ValueError):
            duration = None
        thumbnail = str(item.get("thumbnail") or "") or None
        return MusicTrack(
            title=title,
            webpage_url=url,
            duration=duration,
            requester_id=requester_id,
            thumbnail=thumbnail,
            source=source,
            search_query=str(item.get("search_query") or url or title),
            youtube_url=url if "youtube.com" in url or "youtu.be" in url else "",
        )

    def _load_track_list(self, guild_id: int, key: str) -> list[dict]:
        raw = self.bot.db.get_setting(guild_id, key) or "[]"
        try:
            data = json.loads(raw)
            return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _save_track_list(self, guild_id: int, key: str, items: list[dict], limit: int):
        self.bot.db.set_setting(guild_id, key, json.dumps(items[:limit], ensure_ascii=False))

    def _add_history(self, guild_id: int, track: MusicTrack):
        state = self._state(guild_id)
        state.history.appendleft(track)
        key = "music_history"
        history = self._load_track_list(guild_id, key)
        item = self._track_to_dict(track)
        url = item.get("url")
        if history and history[0].get("url") == url:
            history[0] = item
        else:
            history.insert(0, item)
        self._save_track_list(guild_id, key, history, 25)

    def _add_favorite(self, guild_id: int, user_id: int, track: MusicTrack) -> bool:
        key = f"music_favorites:{user_id}"
        favorites = self._load_track_list(guild_id, key)

        url = track.webpage_url or track.youtube_url or track.search_query or track.title
        if any(isinstance(item, dict) and item.get("url") == url for item in favorites):
            return False

        favorites.insert(0, self._track_to_dict(track))
        self._save_track_list(guild_id, key, favorites, 50)
        return True

    async def _enqueue_saved_item(self, interaction: discord.Interaction, item: dict) -> str:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return "Commande utilisable seulement en serveur."
        state = self._state(interaction.guild.id)
        fallback_channel_id = interaction.channel.id if interaction.channel else state.text_channel_id
        state.text_channel_id = self._music_output_channel_id(interaction.guild, fallback_channel_id)
        voice = await self._ensure_voice(interaction)
        track = self._track_from_saved(item, interaction.user.id)
        start_now = not voice.is_playing() and not voice.is_paused() and state.current is None
        state.queue.append(track)
        if start_now:
            started = await self._play_next(interaction.guild.id, announce=True)
            if started:
                return f"Lecture lancee : **{discord.utils.escape_markdown(track.title)}**."
            return "Le titre a ete ajoute, mais je n'ai pas pu lancer la lecture."
        return f"Ajoute a la file : **{discord.utils.escape_markdown(track.title)}**."

    async def _register_skip_vote(self, interaction: discord.Interaction) -> str:
        error = self._control_error(interaction)
        if error:
            return error
        if not interaction.guild:
            return "Commande utilisable seulement en serveur."
        state = self._state(interaction.guild.id)
        voice = self._voice_client(interaction.guild)
        if not state.current or not voice or not (voice.is_playing() or voice.is_paused()):
            return "Aucune musique n'est en lecture."

        state.vote_skip_ids.add(interaction.user.id)
        threshold = self._vote_skip_threshold(interaction.guild)
        votes = len(state.vote_skip_ids)
        if votes >= threshold:
            state.skip_requested = True
            state.vote_skip_ids.clear()
            voice.stop()
            return f"Vote skip valide ({votes}/{threshold}). Je passe au titre suivant."

        await self._refresh_player_panel(interaction.guild.id)
        return f"Vote skip ajoute ({votes}/{threshold})."

    async def _notify(self, guild_id: int, embed: discord.Embed):
        state = self._state(guild_id)
        if not state.text_channel_id:
            return
        channel = self.bot.get_channel(state.text_channel_id)
        if channel is None or not hasattr(channel, "send"):
            return
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            logger.exception("Failed to send music notification")

    async def _ensure_voice(self, interaction: discord.Interaction) -> discord.VoiceClient:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            raise MusicError("Commande utilisable seulement en serveur.")
        if not interaction.user.voice or not interaction.user.voice.channel:
            raise MusicError("Rejoins d'abord un salon vocal, puis relance la commande.")

        channel = interaction.user.voice.channel
        voice = self._voice_client(interaction.guild)

        try:
            if voice and voice.is_connected():
                if voice.channel != channel:
                    await voice.move_to(channel)
                return voice
            connected = await channel.connect(self_deaf=True)
        except discord.Forbidden as exc:
            raise MusicError("Je n'ai pas la permission de rejoindre ou parler dans ce vocal.") from exc
        except discord.ClientException as exc:
            raise MusicError(f"Impossible de rejoindre le vocal : {exc}") from exc
        except RuntimeError as exc:
            if "PyNaCl" in str(exc) or "voice" in str(exc).lower():
                nacl_status = "detecte" if importlib.util.find_spec("nacl") else "introuvable"
                raise MusicError(
                    "Le support vocal Discord n'est pas installe dans le Python qui lance le bot. "
                    f"Python utilise : `{sys.executable}`. Module nacl : **{nacl_status}**. "
                    'Lance le bot avec `start_bot_voice.bat` ou avec `py -3.10 bot.py` apres installation des requirements.'
                ) from exc
            raise MusicError(f"Impossible de rejoindre le vocal : {exc}") from exc

        if not isinstance(connected, discord.VoiceClient):
            raise MusicError("Connexion vocale impossible avec cette configuration.")
        return connected

    def _control_error(self, interaction: discord.Interaction, *, require_dj: bool = False) -> Optional[str]:
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return "Commande utilisable seulement en serveur."
        voice = self._voice_client(interaction.guild)
        if not voice or not voice.is_connected():
            return "Je ne suis connecte a aucun salon vocal."
        user_voice = interaction.user.voice.channel if interaction.user.voice else None
        if user_voice != voice.channel and not is_staff(interaction.user, self.bot.db):
            return "Tu dois etre dans le meme vocal que moi pour controler la musique."
        if require_dj and not self._is_music_dj(interaction.user):
            role = self._dj_role(interaction.guild)
            role_text = role.mention if role else "un role DJ configure avec `/music setdjrole`"
            return f"Seuls les DJ peuvent faire ca ({role_text}). Les autres peuvent ajouter des musiques et utiliser Vote Skip."
        return None

    async def _extract_track(self, query: str, requester_id: int) -> MusicTrack:
        if yt_dlp is None:
            raise MusicError('La dependance "yt-dlp" manque. Installe-la avec: pip install -U yt-dlp')
        query = query.strip()
        if not query:
            raise MusicError("Donne un lien ou une recherche.")

        info = await asyncio.to_thread(self._extract_track_sync, query)
        entries = info.get("entries") if isinstance(info, dict) else None
        if entries:
            info = next((entry for entry in entries if entry), None)
        if not isinstance(info, dict):
            raise MusicError("Je n'ai trouve aucun resultat pour cette recherche.")

        stream_url = info.get("url")
        title = info.get("title") or "Musique"
        webpage_url = info.get("webpage_url") or info.get("original_url") or query
        thumbnail = info.get("thumbnail")
        raw_duration = info.get("duration")
        try:
            duration = int(raw_duration) if raw_duration else None
        except (TypeError, ValueError):
            duration = None

        if not stream_url:
            raise MusicError("Impossible de recuperer le flux audio de cette musique.")

        return MusicTrack(
            title=str(title),
            webpage_url=str(webpage_url),
            duration=duration,
            requester_id=requester_id,
            stream_url=str(stream_url),
            thumbnail=str(thumbnail) if thumbnail else None,
            source="YouTube",
            search_query=query,
            youtube_url=str(webpage_url),
        )

    def _extract_track_sync(self, query: str) -> dict:
        search = query if re.match(r"https?://", query, re.IGNORECASE) else f"ytsearch1:{query}"
        try:
            with yt_dlp.YoutubeDL(MUSIC_YTDL_OPTIONS) as ytdl:
                return ytdl.extract_info(search, download=False)
        except Exception as exc:
            raise MusicError("Impossible de lire ce lien ou cette recherche.") from exc

    async def _search_youtube_choices(self, query: str, requester_id: int, limit: int = 5) -> list[MusicTrack]:
        return await asyncio.to_thread(self._search_youtube_choices_sync, query, requester_id, limit)

    def _search_youtube_choices_sync(self, query: str, requester_id: int, limit: int = 5) -> list[MusicTrack]:
        if yt_dlp is None:
            raise MusicError('La dependance "yt-dlp" manque. Installe-la avec: pip install -U yt-dlp')
        options = dict(MUSIC_YTDL_OPTIONS)
        options.update({"extract_flat": "in_playlist", "noplaylist": True})
        with yt_dlp.YoutubeDL(options) as ytdl:
            info = ytdl.extract_info(f"ytsearch{max(1, min(limit, 10))}:{query}", download=False)
        entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)] if isinstance(info, dict) else []
        tracks: list[MusicTrack] = []
        for entry in entries[:limit]:
            title = str(entry.get("title") or "YouTube track")
            entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
            if entry_url and not entry_url.startswith(("http://", "https://")):
                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
            raw_duration = entry.get("duration")
            try:
                duration = int(raw_duration) if raw_duration else None
            except (TypeError, ValueError):
                duration = None
            tracks.append(MusicTrack(
                title=title,
                webpage_url=entry_url,
                duration=duration,
                requester_id=requester_id,
                thumbnail=_first_music_image(entry.get("thumbnails"), entry.get("thumbnail")),
                source="YouTube",
                search_query=entry_url or title,
                youtube_url=entry_url,
            ))
        if not tracks:
            raise MusicError("Je n'ai trouve aucun resultat pour cette recherche.")
        return tracks

    async def _prepare_stream(self, track: MusicTrack) -> MusicTrack:
        if track.stream_url:
            return track
        if yt_dlp is None:
            raise MusicError('La dependance "yt-dlp" manque. Installe-la avec: pip install -U yt-dlp')

        search = track.search_query or track.youtube_url or track.webpage_url or track.title
        info = await asyncio.to_thread(self._extract_track_sync, search)
        entries = info.get("entries") if isinstance(info, dict) else None
        if entries:
            info = next((entry for entry in entries if entry), None)
        if not isinstance(info, dict) or not info.get("url"):
            raise MusicError(f"Impossible de trouver l'audio pour **{track.title}**.")

        track.stream_url = str(info["url"])
        track.youtube_url = str(info.get("webpage_url") or info.get("original_url") or track.youtube_url or "")
        if not track.thumbnail and info.get("thumbnail"):
            track.thumbnail = str(info["thumbnail"])
        if not track.duration and info.get("duration"):
            try:
                track.duration = int(info["duration"])
            except (TypeError, ValueError):
                pass
        return track

    async def _resolve_music_items(self, query: str, requester_id: int, *, shuffle: bool, limit: int) -> MusicLoadResult:
        query = query.strip()
        if not query:
            raise MusicError("Donne un lien ou une recherche.")

        max_tracks = max(1, min(int(limit or 50), 100))

        if _spotify_match(query):
            result = await asyncio.to_thread(self._resolve_spotify_sync, query, requester_id, max_tracks)
        elif _deezer_match(query):
            result = await asyncio.to_thread(self._resolve_deezer_sync, query, requester_id, max_tracks)
        else:
            result = MusicLoadResult([], "YouTube")
            if re.match(r"https?://", query, re.IGNORECASE):
                try:
                    result = await asyncio.to_thread(self._resolve_ytdl_playlist_sync, query, requester_id, max_tracks)
                except Exception:
                    result = MusicLoadResult([], "YouTube")
            if not result.tracks:
                result = MusicLoadResult([await self._extract_track(query, requester_id)], "YouTube")

        if len(result.tracks) > 1 and shuffle:
            random.shuffle(result.tracks)
        return result

    def _spotify_artist_text(self, artists: object) -> str:
        if not isinstance(artists, list):
            return ""
        return ", ".join(str(artist.get("name")) for artist in artists if isinstance(artist, dict) and artist.get("name"))

    def _spotify_token_sync(self) -> Optional[str]:
        client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
        client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            return None
        credentials = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")
        payload = _music_post_json(
            "https://accounts.spotify.com/api/token",
            {"grant_type": "client_credentials"},
            {"Authorization": f"Basic {credentials}"},
        )
        token = payload.get("access_token")
        return str(token) if token else None

    def _spotify_api_get_sync(self, url_or_path: str, token: str) -> dict:
        url = url_or_path if url_or_path.startswith("http") else f"https://api.spotify.com/v1/{url_or_path.lstrip('/')}"
        request = Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "Mozilla/5.0 (Uzumaki music bot)"})
        with urlopen(request, timeout=15) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))

    def _spotify_track_from_api(self, data: dict, requester_id: int, fallback_image: Optional[str] = None) -> Optional[MusicTrack]:
        if not isinstance(data, dict) or not data.get("name"):
            return None
        track_id = str(data.get("id") or "")
        title = str(data.get("name") or "Spotify track")
        artist_text = self._spotify_artist_text(data.get("artists"))
        display_title = f"{artist_text} - {title}" if artist_text else title
        external = data.get("external_urls") if isinstance(data.get("external_urls"), dict) else {}
        album = data.get("album") if isinstance(data.get("album"), dict) else {}
        source_url = str(external.get("spotify") or (f"https://open.spotify.com/track/{track_id}" if track_id else ""))
        image_url = _first_music_image(album.get("images"), fallback_image)
        duration_ms = data.get("duration_ms")
        duration = int(duration_ms) // 1000 if isinstance(duration_ms, int) and duration_ms > 1000 else None
        return MusicTrack(
            title=display_title,
            webpage_url=source_url,
            duration=duration,
            requester_id=requester_id,
            thumbnail=image_url,
            source="Spotify",
            search_query=f"{artist_text} - {title} audio" if artist_text else f"{title} audio",
        )

    def _spotify_track_from_embed_entity(self, entity: dict, requester_id: int, source_url: str, image_url: Optional[str]) -> MusicTrack:
        title = str(entity.get("title") or entity.get("name") or "Spotify track")
        artist_text = self._spotify_artist_text(entity.get("artists"))
        if not artist_text:
            artist_text = str(entity.get("subtitle") or "").replace("\xa0", " ").strip()
        display_title = f"{artist_text} - {title}" if artist_text else title
        duration_ms = entity.get("duration")
        duration = int(duration_ms) // 1000 if isinstance(duration_ms, int) and duration_ms > 1000 else None
        track_image = _first_music_image(entity.get("visualIdentity", {}).get("image") if isinstance(entity.get("visualIdentity"), dict) else None, image_url)
        return MusicTrack(
            title=display_title,
            webpage_url=source_url,
            duration=duration,
            requester_id=requester_id,
            thumbnail=track_image,
            source="Spotify",
            search_query=f"{artist_text} - {title} audio" if artist_text else f"{title} audio",
        )

    def _resolve_spotify_with_api_sync(self, kind: str, spotify_id: str, url: str, requester_id: int, limit: int, token: str) -> MusicLoadResult:
        if kind == "track":
            data = self._spotify_api_get_sync(f"tracks/{spotify_id}", token)
            track = self._spotify_track_from_api(data, requester_id)
            if track:
                return MusicLoadResult([track], "Spotify")

        if kind == "album":
            album = self._spotify_api_get_sync(f"albums/{spotify_id}", token)
            image_url = _first_music_image(album.get("images"))
            tracks = []
            for item in (album.get("tracks", {}).get("items") or [])[:limit]:
                if isinstance(item, dict):
                    item["album"] = {"images": album.get("images") or []}
                    track = self._spotify_track_from_api(item, requester_id, image_url)
                    if track:
                        tracks.append(track)
            if tracks:
                return MusicLoadResult(tracks, "Spotify", str(album.get("name") or "Album Spotify"))

        if kind == "playlist":
            playlist = self._spotify_api_get_sync(f"playlists/{spotify_id}", token)
            image_url = _first_music_image(playlist.get("images"))
            tracks: list[MusicTrack] = []
            page = playlist.get("tracks") if isinstance(playlist.get("tracks"), dict) else {}
            while page and len(tracks) < limit:
                for item in page.get("items") or []:
                    if len(tracks) >= limit:
                        break
                    if not isinstance(item, dict):
                        continue
                    track_data = item.get("track")
                    if not isinstance(track_data, dict) or track_data.get("is_local"):
                        continue
                    track = self._spotify_track_from_api(track_data, requester_id, image_url)
                    if track:
                        tracks.append(track)
                next_url = page.get("next")
                if not next_url or len(tracks) >= limit:
                    break
                page = self._spotify_api_get_sync(str(next_url), token)
            if tracks:
                return MusicLoadResult(tracks, "Spotify", str(playlist.get("name") or "Playlist Spotify"))

        raise MusicError("Spotify n'a pas renvoye les infos de ce lien.")

    def _resolve_spotify_with_oembed_sync(self, url: str, requester_id: int) -> MusicLoadResult:
        data = _music_get_json(f"https://open.spotify.com/oembed?url={quote(url, safe='')}")
        title = str(data.get("title") or "Spotify track")
        thumbnail = str(data.get("thumbnail_url") or "") or None
        clean_title = title.replace(" - song and lyrics by ", " - ").replace(" | Spotify", "").strip()
        return MusicLoadResult([
            MusicTrack(
                title=clean_title,
                webpage_url=url,
                duration=None,
                requester_id=requester_id,
                thumbnail=thumbnail,
                source="Spotify",
                search_query=f"{clean_title} audio",
            )
        ], "Spotify")

    def _resolve_spotify_with_embed_page_sync(self, kind: str, spotify_id: str, url: str, requester_id: int, limit: int) -> MusicLoadResult:
        embed_url = f"https://open.spotify.com/embed/{kind}/{spotify_id}?utm_source=oembed"
        page = _music_get_text(embed_url)
        script = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.+?)</script>', page)
        if not script:
            raise MusicError("Spotify n'a pas renvoye les infos de ce lien.")
        payload = json.loads(html.unescape(script.group(1)))
        entity = payload.get("props", {}).get("pageProps", {}).get("state", {}).get("data", {}).get("entity", {})
        if not isinstance(entity, dict):
            raise MusicError("Spotify n'a pas renvoye les infos de ce lien.")

        image_url = _first_music_image(
            entity.get("visualIdentity", {}).get("image") if isinstance(entity.get("visualIdentity"), dict) else None,
            entity.get("coverArt"),
        )

        if kind == "track":
            return MusicLoadResult([self._spotify_track_from_embed_entity(entity, requester_id, url, image_url)], "Spotify")

        tracks: list[MusicTrack] = []
        for item in (entity.get("trackList") or [])[:limit]:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Spotify track")
            artist_text = str(item.get("subtitle") or "").replace("\xa0", " ").strip()
            source_url = url
            uri = str(item.get("uri") or "")
            if uri.startswith("spotify:track:"):
                source_url = f"https://open.spotify.com/track/{uri.rsplit(':', 1)[-1]}"
            duration_ms = item.get("duration")
            duration = int(duration_ms) // 1000 if isinstance(duration_ms, int) and duration_ms > 1000 else None
            tracks.append(MusicTrack(
                title=f"{artist_text} - {title}" if artist_text else title,
                webpage_url=source_url,
                duration=duration,
                requester_id=requester_id,
                thumbnail=image_url,
                source="Spotify",
                search_query=f"{artist_text} - {title} audio" if artist_text else f"{title} audio",
            ))

        if not tracks:
            raise MusicError("Je n'ai trouve aucun titre dans cette playlist Spotify.")
        playlist_name = str(entity.get("title") or entity.get("name") or "Playlist Spotify")
        return MusicLoadResult(tracks, "Spotify", playlist_name)

    def _resolve_spotify_sync(self, url: str, requester_id: int, limit: int) -> MusicLoadResult:
        match = _spotify_match(url)
        if not match:
            raise MusicError("Lien Spotify invalide.")
        kind, spotify_id = match.group(1), match.group(2)

        token = None
        try:
            token = self._spotify_token_sync()
        except Exception:
            logger.warning("Spotify token request failed", exc_info=True)
        if token:
            try:
                return self._resolve_spotify_with_api_sync(kind, spotify_id, url, requester_id, limit, token)
            except Exception:
                logger.warning("Spotify Web API resolution failed", exc_info=True)

        try:
            return self._resolve_spotify_with_embed_page_sync(kind, spotify_id, url, requester_id, limit)
        except Exception as exc:
            if kind == "track":
                try:
                    return self._resolve_spotify_with_oembed_sync(url, requester_id)
                except Exception:
                    logger.warning("Spotify oEmbed resolution failed", exc_info=True)
            if kind in {"playlist", "album"} and not token:
                raise MusicError(
                    "Je n'arrive pas a lire cette playlist/album Spotify sans acces API. "
                    "Ajoute `SPOTIFY_CLIENT_ID` et `SPOTIFY_CLIENT_SECRET` dans `.env`, puis relance le bot."
                ) from exc
            raise MusicError("Je n'arrive pas a lire ce lien Spotify.") from exc

    def _deezer_track_from_data(self, data: dict, requester_id: int, image_url: Optional[str] = None) -> MusicTrack:
        title = str(data.get("title") or data.get("title_short") or "Deezer track")
        artist = data.get("artist") if isinstance(data.get("artist"), dict) else {}
        artist_text = str(artist.get("name") or "").strip()
        album = data.get("album") if isinstance(data.get("album"), dict) else {}
        image = _first_music_image(image_url, data, album)
        try:
            duration = int(data.get("duration")) if data.get("duration") else None
        except (TypeError, ValueError):
            duration = None
        return MusicTrack(
            title=f"{artist_text} - {title}" if artist_text else title,
            webpage_url=str(data.get("link") or ""),
            duration=duration,
            requester_id=requester_id,
            thumbnail=image,
            source="Deezer",
            search_query=f"{artist_text} - {title} audio" if artist_text else f"{title} audio",
        )

    def _resolve_deezer_sync(self, url: str, requester_id: int, limit: int) -> MusicLoadResult:
        match = _deezer_match(url)
        if not match:
            raise MusicError("Lien Deezer invalide.")
        kind, deezer_id = match.group(1), match.group(2)
        try:
            data = _music_get_json(f"https://api.deezer.com/{kind}/{deezer_id}")
        except Exception as exc:
            raise MusicError("Je n'arrive pas a lire ce lien Deezer.") from exc
        if data.get("error"):
            raise MusicError("Deezer n'a pas renvoye les infos de ce lien.")

        if kind == "track":
            return MusicLoadResult([self._deezer_track_from_data(data, requester_id)], "Deezer")

        image_url = _first_music_image(data)
        tracks_data: list[dict] = []
        tracks_block = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
        tracks_data.extend(item for item in tracks_block.get("data", []) if isinstance(item, dict))
        next_url = tracks_block.get("next")
        while next_url and len(tracks_data) < limit:
            page = _music_get_json(str(next_url))
            tracks_data.extend(item for item in page.get("data", []) if isinstance(item, dict))
            next_url = page.get("next")

        tracks = [self._deezer_track_from_data(item, requester_id, image_url) for item in tracks_data[:limit]]
        if not tracks:
            raise MusicError("Je n'ai trouve aucun titre dans cette playlist Deezer.")
        playlist_name = str(data.get("title") or ("Album Deezer" if kind == "album" else "Playlist Deezer"))
        return MusicLoadResult(tracks, "Deezer", playlist_name)

    def _resolve_ytdl_playlist_sync(self, url: str, requester_id: int, limit: int) -> MusicLoadResult:
        if yt_dlp is None:
            raise MusicError('La dependance "yt-dlp" manque. Installe-la avec: pip install -U yt-dlp')
        options = dict(MUSIC_YTDL_OPTIONS)
        options.update({"extract_flat": "in_playlist", "noplaylist": False, "ignoreerrors": True})
        with yt_dlp.YoutubeDL(options) as ytdl:
            info = ytdl.extract_info(url, download=False)
        if not isinstance(info, dict):
            return MusicLoadResult([], "YouTube")
        entries = [entry for entry in (info.get("entries") or []) if isinstance(entry, dict)]
        if len(entries) <= 1:
            return MusicLoadResult([], "YouTube")

        tracks: list[MusicTrack] = []
        for entry in entries[:limit]:
            title = str(entry.get("title") or "YouTube track")
            entry_url = str(entry.get("webpage_url") or entry.get("url") or "")
            if entry_url and not entry_url.startswith(("http://", "https://")):
                entry_url = f"https://www.youtube.com/watch?v={entry_url}"
            image_url = _first_music_image(entry.get("thumbnails"), entry.get("thumbnail"))
            raw_duration = entry.get("duration")
            try:
                duration = int(raw_duration) if raw_duration else None
            except (TypeError, ValueError):
                duration = None
            tracks.append(MusicTrack(
                title=title,
                webpage_url=entry_url or url,
                duration=duration,
                requester_id=requester_id,
                thumbnail=image_url,
                source="YouTube",
                search_query=entry_url or title,
                youtube_url=entry_url,
            ))
        playlist_name = str(info.get("title") or "Playlist YouTube")
        return MusicLoadResult(tracks, "YouTube", playlist_name)

    async def _build_autoplay_track(self, guild_id: int, previous: Optional[MusicTrack]) -> Optional[MusicTrack]:
        if previous is None:
            return None
        query = f"{previous.title} radio music"
        try:
            choices = await self._search_youtube_choices(query, previous.requester_id, 5)
        except Exception:
            logger.warning("Autoplay search failed", exc_info=True)
            return None
        previous_url = previous.youtube_url or previous.webpage_url
        previous_title = previous.title.lower().strip()
        for track in choices:
            candidate_url = track.youtube_url or track.webpage_url
            if candidate_url and previous_url and candidate_url == previous_url:
                continue
            if track.title.lower().strip() == previous_title:
                continue
            track.source = "YouTube Autoplay"
            return track
        return choices[0] if choices else None

    async def _play_next(self, guild_id: int, *, announce: bool = True) -> Optional[MusicTrack]:
        self._cancel_progress_updater(guild_id)
        guild = self.bot.get_guild(guild_id)
        if not guild:
            return None
        voice = self._voice_client(guild)
        if not voice or not voice.is_connected():
            return None

        state = self._state(guild_id)
        if state.stop_requested:
            state.current = None
            state.skip_requested = False
            state.stop_requested = False
            state.vote_skip_ids.clear()
            self._reset_track_clock(state)
            return None

        previous = state.current
        if state.loop and state.repeat_mode == "off":
            state.repeat_mode = "song"
        if state.repeat_mode == "song" and previous and not state.skip_requested:
            state.queue.appendleft(state.current)
        elif state.repeat_mode == "queue" and previous and not state.stop_requested:
            state.queue.append(previous)

        state.current = None
        state.skip_requested = False
        state.vote_skip_ids.clear()
        self._reset_track_clock(state)

        if not state.queue:
            if state.autoplay and previous and not state.stop_requested:
                autoplay_track = await self._build_autoplay_track(guild_id, previous)
                if autoplay_track:
                    state.queue.append(autoplay_track)
            if not state.queue:
                await self._show_idle_panel(guild_id, "File vide. Ajoute une musique avec `/music play`.")
                return None

        if state.shuffle and len(state.queue) > 1:
            random.shuffle(state.queue)

        track = state.queue.popleft()
        state.current = track
        self._start_track_clock(state)

        try:
            await self._prepare_stream(track)
            audio = discord.FFmpegPCMAudio(track.stream_url, executable=FFMPEG_PATH, **MUSIC_FFMPEG_OPTIONS)
            source = discord.PCMVolumeTransformer(audio, volume=state.volume)
            voice.play(source, after=lambda error: self._after_track(guild_id, error))
        except MusicError as exc:
            logger.warning("Failed to resolve music track: %s", exc)
            state.current = None
            self._reset_track_clock(state)
            await self._notify(guild_id, build_embed("Musique", str(exc)))
            return await self._play_next(guild_id, announce=announce)
        except FileNotFoundError:
            state.current = None
            self._reset_track_clock(state)
            state.queue.clear()
            await self._notify(guild_id, build_embed("Musique", "FFmpeg est introuvable. Installe FFmpeg ou configure `FFMPEG_PATH` dans `.env`."))
            return None
        except Exception:
            logger.exception("Failed to start music track")
            state.current = None
            self._reset_track_clock(state)
            await self._notify(guild_id, build_embed("Musique", "Impossible de lancer ce titre. Je passe au suivant si la file continue."))
            return await self._play_next(guild_id, announce=announce)

        self._add_history(guild_id, track)
        if announce:
            await self._show_player_panel(guild_id, track, bump=True)
        self._start_progress_updater(guild_id)
        return track

    def _after_track(self, guild_id: int, error: Optional[Exception]):
        if error:
            logger.warning("Music playback error for guild %s: %s", guild_id, error)
        future = asyncio.run_coroutine_threadsafe(self._play_next(guild_id), self.bot.loop)

        def _log_result(task):
            try:
                task.result()
            except Exception:
                logger.exception("Failed to advance music queue")

        future.add_done_callback(_log_result)

    @music.command(name="join", description="Connecte le bot dans ton salon vocal")
    async def join(self, interaction: discord.Interaction):
        try:
            voice = await self._ensure_voice(interaction)
        except MusicError as exc:
            return await interaction.response.send_message(str(exc), ephemeral=True)
        await interaction.response.send_message(f"Connecte dans **{voice.channel.name}**.", ephemeral=True)

    @music.command(name="setchannel", description="Definit le salon ou le panel musique sera envoye")
    @staff_only()
    async def setchannel(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message("Choisis un salon texte.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "music_channel_id", str(target.id))
        state = self._state(interaction.guild.id)
        state.text_channel_id = target.id
        if state.current:
            await self._bump_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Salon musique fixe defini sur {target.mention}.", ephemeral=True)

    @music.command(name="clearchannel", description="Retire le salon musique fixe")
    @staff_only()
    async def clearchannel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "music_channel_id", "")
        await interaction.response.send_message("Salon musique fixe retire. Le panel ira dans le salon de la commande.", ephemeral=True)

    @music.command(name="setdjrole", description="Definit ou retire le role DJ pour skip/stop/shuffle/volume")
    @staff_only()
    async def setdjrole(self, interaction: discord.Interaction, role: Optional[discord.Role] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "music_dj_role_id", str(role.id) if role else "")
        if role:
            await interaction.response.send_message(f"Role DJ configure sur {role.mention}.", ephemeral=True)
        else:
            await interaction.response.send_message("Role DJ retire. Les permissions staff restent DJ.", ephemeral=True)

    @music.command(name="voteskippercent", description="Regle le pourcentage requis pour Vote Skip")
    @staff_only()
    async def voteskippercent(self, interaction: discord.Interaction, percent: app_commands.Range[int, 1, 100] = 50):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "music_voteskip_percent", str(int(percent)))
        await interaction.response.send_message(f"Vote Skip regle a **{int(percent)}%** des humains dans le vocal.", ephemeral=True)

    @music.command(name="cleanup", description="Regle la suppression auto des messages musique")
    @staff_only()
    async def cleanup(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 120] = 12):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "music_cleanup_seconds", str(int(seconds)))
        text = "desactive" if int(seconds) <= 0 else f"{int(seconds)} secondes"
        await interaction.response.send_message(f"Nettoyage auto musique : **{text}**.", ephemeral=True)

    @music.command(name="play", description="Joue une recherche ou un lien YouTube, Spotify ou Deezer")
    @app_commands.describe(
        query="Lien ou recherche a jouer",
        shuffle="Melanger les titres si le lien est une playlist",
        limit="Nombre maximum de titres a ajouter depuis une playlist",
        choose="Afficher 5 resultats quand tu fais une recherche texte",
    )
    async def play(
        self,
        interaction: discord.Interaction,
        query: str,
        shuffle: bool = False,
        limit: app_commands.Range[int, 1, 100] = 50,
        choose: bool = True,
    ):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)

        is_link = bool(re.match(r"https?://", query.strip(), re.IGNORECASE))
        wants_choices = choose and not is_link
        await interaction.response.defer(thinking=True, ephemeral=wants_choices)
        state = self._state(interaction.guild.id)
        fallback_channel_id = interaction.channel.id if interaction.channel else 0
        state.text_channel_id = self._music_output_channel_id(interaction.guild, fallback_channel_id)

        try:
            voice = await self._ensure_voice(interaction)
            if wants_choices:
                tracks = await self._search_youtube_choices(query, interaction.user.id, 5)
                view = MusicSearchView(self, interaction.guild.id, tracks, state.text_channel_id)
                embed = build_embed("Choisis une musique", "Selectionne le resultat a jouer dans le menu ci-dessous.")
                for index, track in enumerate(tracks, start=1):
                    embed.add_field(name=f"{index}. {track.title[:80]}", value=f"Duree : {format_music_duration(track.duration)}", inline=False)
                return await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            result = await self._resolve_music_items(query, interaction.user.id, shuffle=shuffle, limit=int(limit))
        except MusicError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        except Exception as exc:
            logger.exception("Failed to prepare music track")
            return await interaction.followup.send(
                f"Je n'ai pas reussi a preparer cette musique. Detail : `{type(exc).__name__}: {str(exc)[:160]}`",
                ephemeral=True,
            )

        start_now = not voice.is_playing() and not voice.is_paused() and state.current is None
        for track in result.tracks:
            state.queue.append(track)

        if start_now:
            started = await self._play_next(interaction.guild.id, announce=True)
            if started:
                return await interaction.followup.send("Lecture lancee, le panel est affiche dans le salon.", ephemeral=True)
            return await interaction.followup.send("La musique a ete ajoutee, mais je n'ai pas pu lancer la lecture.", ephemeral=True)

        added_count = len(result.tracks)
        playlist_text = f" depuis **{discord.utils.escape_markdown(result.playlist_name)}**" if result.playlist_name else ""
        embed = build_embed(
            "Ajoute a la file",
            f"**{added_count}** titre(s) ajoute(s){playlist_text}.\nSource : **{result.source_name}**\nMelange : **{'oui' if shuffle and added_count > 1 else 'non'}**",
        )
        if result.tracks:
            embed.add_field(name="Premier titre ajoute", value=self._track_link(result.tracks[0]), inline=False)
        embed.add_field(name="Position", value=str(max(1, len(state.queue) - added_count + 1)), inline=True)
        message = await interaction.followup.send(embed=embed, wait=True)
        asyncio.create_task(self._delete_later(message, interaction.guild.id))

    @music.command(name="pause", description="Met la musique en pause")
    async def pause(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        voice = self._voice_client(interaction.guild)
        if not voice or not voice.is_playing():
            return await interaction.response.send_message("Aucune musique n'est en lecture.", ephemeral=True)
        state = self._state(interaction.guild.id)
        self._pause_track_clock(state)
        voice.pause()
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message("Pause.", ephemeral=True)

    @music.command(name="resume", description="Reprend la musique")
    async def resume(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        voice = self._voice_client(interaction.guild)
        if not voice or not voice.is_paused():
            return await interaction.response.send_message("La musique n'est pas en pause.", ephemeral=True)
        voice.resume()
        state = self._state(interaction.guild.id)
        self._resume_track_clock(state)
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message("Lecture reprise.", ephemeral=True)

    @music.command(name="skip", description="Passe a la musique suivante")
    async def skip(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        voice = self._voice_client(interaction.guild)
        if not voice or not (voice.is_playing() or voice.is_paused()):
            return await interaction.response.send_message("Aucune musique a passer.", ephemeral=True)
        state.skip_requested = True
        voice.stop()
        await interaction.response.send_message("Je passe au titre suivant.", ephemeral=True)

    @music.command(name="voteskip", description="Vote pour passer a la musique suivante")
    async def voteskip(self, interaction: discord.Interaction):
        message = await self._register_skip_vote(interaction)
        await interaction.response.send_message(message, ephemeral=True)

    @music.command(name="stop", description="Stoppe la musique et vide la file")
    async def stop(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.queue.clear()
        state.current = None
        state.vote_skip_ids.clear()
        self._reset_track_clock(state)
        self._cancel_progress_updater(interaction.guild.id)
        state.stop_requested = True
        voice = self._voice_client(interaction.guild)
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        else:
            state.stop_requested = False
        await self._show_idle_panel(interaction.guild.id, "Musique stoppee et file videe.")
        await interaction.response.send_message("Musique stoppee et file videe.", ephemeral=True)

    @music.command(name="leave", description="Deconnecte le bot du vocal")
    async def leave(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.queue.clear()
        state.current = None
        state.vote_skip_ids.clear()
        self._reset_track_clock(state)
        self._cancel_progress_updater(interaction.guild.id)
        state.stop_requested = True
        voice = self._voice_client(interaction.guild)
        if voice:
            if voice.is_playing() or voice.is_paused():
                voice.stop()
            await voice.disconnect(force=True)
        state.stop_requested = False
        await self._show_idle_panel(interaction.guild.id, "Deconnecte du vocal.")
        await interaction.response.send_message("Deconnecte du vocal.", ephemeral=True)

    @music.command(name="queue", description="Affiche la file d'attente")
    async def queue(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        await interaction.response.send_message(
            embed=self._build_queue_embed(interaction.guild.id, 0),
            view=MusicQueueView(self, interaction.guild.id, 0),
            ephemeral=True,
        )

    @music.command(name="now", description="Affiche le titre en cours")
    async def now(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        state = self._state(interaction.guild.id)
        if not state.current:
            return await interaction.response.send_message("Aucune musique n'est en lecture.", ephemeral=True)
        await interaction.response.send_message(embed=self._build_track_embed("Lecture en cours", state.current), ephemeral=True)

    @music.command(name="panel", description="Remet le panel musique en bas du salon")
    async def panel(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        state = self._state(interaction.guild.id)
        if not state.current:
            return await interaction.response.send_message("Aucune musique n'est en lecture.", ephemeral=True)
        fallback_channel_id = interaction.channel.id if interaction.channel else state.text_channel_id
        state.text_channel_id = self._music_output_channel_id(interaction.guild, fallback_channel_id)
        await self._bump_player_panel(interaction.guild.id)
        await interaction.response.send_message("Panel remis en bas.", ephemeral=True)

    @music.command(name="volume", description="Regle le volume entre 1 et 200")
    @app_commands.describe(amount="Volume en pourcentage")
    async def volume(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 200]):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.volume = amount / 100
        voice = self._voice_client(interaction.guild)
        if voice and isinstance(voice.source, discord.PCMVolumeTransformer):
            voice.source.volume = state.volume
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Volume regle a **{amount}%**.", ephemeral=True)

    @music.command(name="loop", description="Active ou desactive la repetition du titre")
    async def loop(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.repeat_mode = "off" if state.repeat_mode == "song" else "song"
        state.loop = state.repeat_mode == "song"
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Repeat song {'active' if state.loop else 'desactive'}.", ephemeral=True)

    @music.command(name="repeat", description="Regle le mode repeat")
    @app_commands.choices(mode=[
        app_commands.Choice(name="off", value="off"),
        app_commands.Choice(name="song", value="song"),
        app_commands.Choice(name="queue", value="queue"),
    ])
    async def repeat(self, interaction: discord.Interaction, mode: app_commands.Choice[str]):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.repeat_mode = mode.value
        state.loop = mode.value == "song"
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Repeat regle sur **{mode.value}**.", ephemeral=True)

    @music.command(name="autoplay", description="Active ou desactive l'autoplay")
    async def autoplay(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.autoplay = not state.autoplay
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Autoplay {'active' if state.autoplay else 'desactive'}.", ephemeral=True)

    @music.command(name="shuffle", description="Melange la file et active/desactive le mode shuffle")
    async def shuffle(self, interaction: discord.Interaction):
        error = self._control_error(interaction, require_dj=True)
        if error:
            return await interaction.response.send_message(error, ephemeral=True)
        state = self._state(interaction.guild.id)
        state.shuffle = not state.shuffle
        if len(state.queue) > 1:
            random.shuffle(state.queue)
        await self._refresh_player_panel(interaction.guild.id)
        await interaction.response.send_message(f"Shuffle {'active' if state.shuffle else 'desactive'}.", ephemeral=True)

    @music.command(name="favorites", description="Affiche tes musiques favorites")
    async def favorites(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        favorites = self._load_track_list(interaction.guild.id, f"music_favorites:{interaction.user.id}")
        if not favorites:
            return await interaction.response.send_message("Tu n'as pas encore de favoris musique.", ephemeral=True)
        lines = []
        for index, item in enumerate(favorites[:10], start=1):
            if not isinstance(item, dict):
                continue
            title = discord.utils.escape_markdown(str(item.get("title") or "Musique"))[:80]
            url = str(item.get("url") or "")
            duration = format_music_duration(item.get("duration"))
            source = str(item.get("source") or "Source")
            label = f"[{title}]({url})" if url.startswith(("http://", "https://")) else f"**{title}**"
            lines.append(f"`{index}.` {label} - {duration} - {source}")
        await interaction.response.send_message(
            embed=build_embed("Tes favoris musique", "\n".join(lines)),
            view=MusicSavedTracksView(self, interaction.guild.id, favorites[:10], "favorites"),
            ephemeral=True,
        )

    @music.command(name="playfavorite", description="Rejoue un favori par numero ou affiche les boutons")
    async def playfavorite(self, interaction: discord.Interaction, index: Optional[app_commands.Range[int, 1, 50]] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        favorites = self._load_track_list(interaction.guild.id, f"music_favorites:{interaction.user.id}")
        if not favorites:
            return await interaction.response.send_message("Tu n'as pas encore de favoris musique.", ephemeral=True)
        if index is None:
            lines = [f"`{i}.` **{discord.utils.escape_markdown(str(item.get('title') or 'Musique'))[:80]}**" for i, item in enumerate(favorites[:10], start=1)]
            return await interaction.response.send_message(
                embed=build_embed("Rejouer un favori", "\n".join(lines)),
                view=MusicSavedTracksView(self, interaction.guild.id, favorites[:10], "favorites"),
                ephemeral=True,
            )
        if int(index) > len(favorites):
            return await interaction.response.send_message("Ce favori n'existe pas.", ephemeral=True)
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            message = await self._enqueue_saved_item(interaction, favorites[int(index) - 1])
        except MusicError as exc:
            message = str(exc)
        await interaction.followup.send(message, ephemeral=True)

    @music.command(name="history", description="Affiche les dernieres musiques jouees")
    async def history(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        history = self._load_track_list(interaction.guild.id, "music_history")
        if not history:
            return await interaction.response.send_message("Aucun historique musique pour l'instant.", ephemeral=True)
        lines = []
        for index, item in enumerate(history[:10], start=1):
            title = discord.utils.escape_markdown(str(item.get("title") or "Musique"))[:80]
            source = str(item.get("source") or "Source")
            lines.append(f"`{index}.` **{title}** - {source}")
        await interaction.response.send_message(
            embed=build_embed("Historique musique", "\n".join(lines)),
            view=MusicSavedTracksView(self, interaction.guild.id, history[:10], "history"),
            ephemeral=True,
        )

    def _split_lyrics_title(self, raw: str) -> tuple[str, str]:
        value = re.sub(r"\s+", " ", raw).strip()
        for separator in [" - ", " -- ", " by "]:
            if separator in value:
                left, right = value.split(separator, 1)
                return left.strip(), right.strip()
        return "", value

    def _fetch_lyrics_sync(self, artist: str, title: str) -> str:
        if not artist or not title:
            raise MusicError("Je n'ai pas assez d'info pour chercher les paroles. Essaie `/music lyrics artiste - titre`.")
        data = _music_get_json(f"https://api.lyrics.ovh/v1/{quote(artist)}/{quote(title)}")
        lyrics = str(data.get("lyrics") or "").strip()
        if not lyrics:
            raise MusicError("Paroles introuvables pour ce titre.")
        return lyrics

    @music.command(name="lyrics", description="Affiche les paroles de la musique en cours ou d'une recherche")
    async def lyrics(self, interaction: discord.Interaction, query: Optional[str] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        state = self._state(interaction.guild.id)
        raw = (query or (state.current.title if state.current else "")).strip()
        if not raw:
            return await interaction.response.send_message("Aucune musique en cours. Essaie `/music lyrics artiste - titre`.", ephemeral=True)
        artist, title = self._split_lyrics_title(raw)
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            lyrics = await asyncio.to_thread(self._fetch_lyrics_sync, artist, title)
        except MusicError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)
        except Exception:
            logger.warning("Lyrics lookup failed", exc_info=True)
            return await interaction.followup.send("Je n'ai pas trouve les paroles pour ce titre.", ephemeral=True)
        chunks = [lyrics[i:i + 3500] for i in range(0, min(len(lyrics), 7000), 3500)]
        for index, chunk in enumerate(chunks[:2], start=1):
            suffix = f" ({index}/{len(chunks[:2])})" if len(chunks) > 1 else ""
            await interaction.followup.send(embed=build_embed(f"Lyrics{suffix}", chunk), ephemeral=True)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if member.bot:
            return
        voice = self._voice_client(member.guild)
        if not voice or not voice.channel:
            return
        if before.channel != voice.channel and after.channel != voice.channel:
            return
        if any(not m.bot for m in voice.channel.members):
            return

        await asyncio.sleep(90)
        voice = self._voice_client(member.guild)
        if not voice or not voice.channel:
            return
        if any(not m.bot for m in voice.channel.members):
            return

        state = self._state(member.guild.id)
        state.queue.clear()
        state.current = None
        state.vote_skip_ids.clear()
        self._reset_track_clock(state)
        self._cancel_progress_updater(member.guild.id)
        state.stop_requested = True
        if voice.is_playing() or voice.is_paused():
            voice.stop()
        await voice.disconnect(force=True)
        state.stop_requested = False


class MusicSearchSelect(discord.ui.Select):
    def __init__(self, parent: "MusicSearchView"):
        self.parent_view = parent
        options = []
        for index, track in enumerate(parent.tracks):
            label = track.title[:100]
            description = f"{format_music_duration(track.duration)} - {track.source}"[:100]
            options.append(discord.SelectOption(label=label, description=description, value=str(index)))
        super().__init__(placeholder="Choisis la musique a jouer", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.requester_id:
            return await interaction.response.send_message("Seule la personne qui a lance la recherche peut choisir.", ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        index = int(self.values[0])
        track = self.parent_view.tracks[index]
        state = self.parent_view.cog._state(interaction.guild.id)
        state.text_channel_id = self.parent_view.output_channel_id or (interaction.channel.id if interaction.channel else 0)

        try:
            voice = await self.parent_view.cog._ensure_voice(interaction)
        except MusicError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)

        start_now = not voice.is_playing() and not voice.is_paused() and state.current is None
        state.queue.append(track)

        for item in self.parent_view.children:
            item.disabled = True
        try:
            await interaction.message.edit(view=self.parent_view)
        except discord.HTTPException:
            pass

        if start_now:
            started = await self.parent_view.cog._play_next(interaction.guild.id, announce=True)
            if started:
                return await interaction.followup.send("Lecture lancee, le panel est affiche dans le salon.", ephemeral=True)
            return await interaction.followup.send("Le titre a ete ajoute, mais je n'ai pas pu lancer la lecture.", ephemeral=True)

        await interaction.followup.send(f"Ajoute a la file : **{track.title}**.", ephemeral=True)


class MusicSearchButton(discord.ui.Button):
    def __init__(self, parent: "MusicSearchView", index: int):
        label = f"{index + 1}. {parent.tracks[index].title[:70]}"
        super().__init__(label=label, style=discord.ButtonStyle.primary, row=index // 2)
        self.parent_view = parent
        self.index = index

    async def callback(self, interaction: discord.Interaction):
        if interaction.user.id != self.parent_view.requester_id:
            return await interaction.response.send_message("Seule la personne qui a lance la recherche peut choisir.", ephemeral=True)
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)

        await interaction.response.defer(thinking=True, ephemeral=True)
        track = self.parent_view.tracks[self.index]
        state = self.parent_view.cog._state(interaction.guild.id)
        state.text_channel_id = self.parent_view.output_channel_id or (interaction.channel.id if interaction.channel else 0)

        try:
            voice = await self.parent_view.cog._ensure_voice(interaction)
        except MusicError as exc:
            return await interaction.followup.send(str(exc), ephemeral=True)

        start_now = not voice.is_playing() and not voice.is_paused() and state.current is None
        state.queue.append(track)

        for item in self.parent_view.children:
            item.disabled = True
        try:
            if interaction.message:
                await interaction.message.edit(view=self.parent_view)
        except discord.HTTPException:
            pass

        if start_now:
            started = await self.parent_view.cog._play_next(interaction.guild.id, announce=True)
            if started:
                return await interaction.followup.send("Lecture lancee, le panel est affiche dans le salon.", ephemeral=True)
            return await interaction.followup.send("Le titre a ete ajoute, mais je n'ai pas pu lancer la lecture.", ephemeral=True)

        await interaction.followup.send(f"Ajoute a la file : **{track.title}**.", ephemeral=True)


class MusicSearchView(discord.ui.View):
    def __init__(self, cog: Music, guild_id: int, tracks: list[MusicTrack], output_channel_id: int):
        super().__init__(timeout=60)
        self.cog = cog
        self.guild_id = guild_id
        self.tracks = tracks
        self.output_channel_id = output_channel_id
        self.requester_id = tracks[0].requester_id if tracks else 0
        for index in range(min(len(tracks), 5)):
            self.add_item(MusicSearchButton(self, index))


class MusicQueueView(discord.ui.View):
    def __init__(self, cog: Music, guild_id: int, page: int = 0):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.page = page
        self._sync_buttons()

    def _sync_buttons(self):
        total = self.cog._queue_page_count(self.guild_id)
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                if item.custom_id == "music_queue_prev":
                    item.disabled = self.page <= 0
                elif item.custom_id == "music_queue_next":
                    item.disabled = self.page >= total - 1

    @discord.ui.button(label="Precedent", style=discord.ButtonStyle.secondary, custom_id="music_queue_prev")
    async def previous(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = max(0, self.page - 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.cog._build_queue_embed(self.guild_id, self.page), view=self)

    @discord.ui.button(label="Suivant", style=discord.ButtonStyle.secondary, custom_id="music_queue_next")
    async def next(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page = min(self.cog._queue_page_count(self.guild_id) - 1, self.page + 1)
        self._sync_buttons()
        await interaction.response.edit_message(embed=self.cog._build_queue_embed(self.guild_id, self.page), view=self)


class MusicSavedTrackButton(discord.ui.Button):
    def __init__(self, parent: "MusicSavedTracksView", index: int, item: dict):
        title = str(item.get("title") or "Musique")
        super().__init__(label=f"Play {index + 1}", style=discord.ButtonStyle.success, row=index // 5)
        self.parent_view = parent
        self.index = index
        self.item = item

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True, ephemeral=True)
        try:
            message = await self.parent_view.cog._enqueue_saved_item(interaction, self.item)
        except MusicError as exc:
            message = str(exc)
        except Exception as exc:
            logger.exception("Failed to replay saved music")
            message = f"Impossible de relancer ce titre (`{type(exc).__name__}`)."
        await interaction.followup.send(message, ephemeral=True)


class MusicSavedTracksView(discord.ui.View):
    def __init__(self, cog: Music, guild_id: int, items: list[dict], source: str):
        super().__init__(timeout=120)
        self.cog = cog
        self.guild_id = guild_id
        self.items = items
        self.source = source
        for index, item in enumerate(items[:10]):
            self.add_item(MusicSavedTrackButton(self, index, item))


class MusicPanelView(discord.ui.View):
    def __init__(self, cog: Music, guild_id: int):
        super().__init__(timeout=3600)
        self.cog = cog
        self.guild_id = guild_id

    async def _guard_control(self, interaction: discord.Interaction) -> bool:
        error = self.cog._control_error(interaction, require_dj=True)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Pause / Resume", style=discord.ButtonStyle.secondary, row=0)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        voice = self.cog._voice_client(interaction.guild)
        if not voice:
            return await interaction.response.send_message("Je ne suis connecte a aucun vocal.", ephemeral=True)
        state = self.cog._state(self.guild_id)
        if voice.is_paused():
            voice.resume()
            self.cog._resume_track_clock(state)
            message = "Lecture reprise."
        elif voice.is_playing():
            self.cog._pause_track_clock(state)
            voice.pause()
            message = "Pause."
        else:
            message = "Aucune musique n'est en lecture."
        await self.cog._refresh_player_panel(self.guild_id)
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Vote skip", style=discord.ButtonStyle.primary, row=0)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        message = await self.cog._register_skip_vote(interaction)
        await interaction.response.send_message(message, ephemeral=True)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger, row=0)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        state = self.cog._state(self.guild_id)
        state.queue.clear()
        state.current = None
        state.stop_requested = True
        self.cog._reset_track_clock(state)
        self.cog._cancel_progress_updater(self.guild_id)
        voice = self.cog._voice_client(interaction.guild)
        if voice and (voice.is_playing() or voice.is_paused()):
            voice.stop()
        else:
            state.stop_requested = False
        await self.cog._show_idle_panel(self.guild_id, "Musique stoppee et file videe.")
        await interaction.response.send_message("Musique stoppee et file videe.", ephemeral=True)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.secondary, row=1)
    async def queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        await interaction.response.send_message(
            embed=self.cog._build_queue_embed(self.guild_id, 0),
            view=MusicQueueView(self.cog, self.guild_id, 0),
            ephemeral=True,
        )

    @discord.ui.button(label="Shuffle queue", style=discord.ButtonStyle.secondary, row=1)
    async def shuffle_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        state = self.cog._state(self.guild_id)
        if len(state.queue) < 2:
            return await interaction.response.send_message("Il faut au moins 2 titres en attente pour melanger.", ephemeral=True)
        state.shuffle = True
        random.shuffle(state.queue)
        await self.cog._refresh_player_panel(self.guild_id)
        await interaction.response.send_message("File d'attente melangee.", ephemeral=True)

    @discord.ui.button(label="Add to your favorites", style=discord.ButtonStyle.success, row=1)
    async def favorite(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        state = self.cog._state(self.guild_id)
        if not state.current:
            return await interaction.response.send_message("Aucune musique en cours a ajouter.", ephemeral=True)
        added = self.cog._add_favorite(interaction.guild.id, interaction.user.id, state.current)
        if added:
            await interaction.response.send_message("Ajoute a tes favoris musique.", ephemeral=True)
        else:
            await interaction.response.send_message("Cette musique est deja dans tes favoris.", ephemeral=True)

    @discord.ui.button(label="Repeat song", style=discord.ButtonStyle.secondary, row=2)
    async def repeat_song(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        state = self.cog._state(self.guild_id)
        state.repeat_mode = "off" if state.repeat_mode == "song" else "song"
        state.loop = state.repeat_mode == "song"
        await self.cog._refresh_player_panel(self.guild_id)
        await interaction.response.send_message(f"Repeat song {'active' if state.repeat_mode == 'song' else 'desactive'}.", ephemeral=True)

    @discord.ui.button(label="Repeat queue", style=discord.ButtonStyle.secondary, row=2)
    async def repeat_queue(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        state = self.cog._state(self.guild_id)
        state.repeat_mode = "off" if state.repeat_mode == "queue" else "queue"
        state.loop = False
        await self.cog._refresh_player_panel(self.guild_id)
        await interaction.response.send_message(f"Repeat queue {'active' if state.repeat_mode == 'queue' else 'desactive'}.", ephemeral=True)

    @discord.ui.button(label="Autoplay", style=discord.ButtonStyle.secondary, row=2)
    async def autoplay(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self._guard_control(interaction):
            return
        state = self.cog._state(self.guild_id)
        state.autoplay = not state.autoplay
        await self.cog._refresh_player_panel(self.guild_id)
        await interaction.response.send_message(f"Autoplay {'active' if state.autoplay else 'desactive'}.", ephemeral=True)


# -----------------------------
# Bot
# -----------------------------


DISABLED_COMMAND_GROUPS: set[str] = set()
DISABLED_GROUP_COMMANDS: dict[str, set[str]] = {
    "pro": {"setwelcomechannel"},
    "stats": {"server", "activity", "topchat"},
}
DISABLED_ROOT_COMMANDS: set[str] = {
    "compatibility",
    "rankcard",
    "wanted",
}


def trim_cog_app_commands(cog: commands.Cog):
    kept: list[app_commands.Command | app_commands.Group] = []
    for command in getattr(cog, "__cog_app_commands__", []):
        if command.name in DISABLED_COMMAND_GROUPS or command.name in DISABLED_ROOT_COMMANDS:
            continue
        if isinstance(command, app_commands.Group):
            for child_name in DISABLED_GROUP_COMMANDS.get(command.name, set()):
                command.remove_command(child_name)
            if not command.commands:
                continue
        kept.append(command)
    cog.__cog_app_commands__ = kept


async def safe_interaction_send(interaction: discord.Interaction, *args, **kwargs):
    if interaction.response.is_done():
        return await interaction.followup.send(*args, **kwargs)
    try:
        return await interaction.response.send_message(*args, **kwargs)
    except discord.HTTPException as exc:
        if getattr(exc, "code", None) == 40060:
            return await interaction.followup.send(*args, **kwargs)
        raise


class UzumakiBot(commands.Bot):
    def __init__(self):
        super().__init__(
            command_prefix=commands.when_mentioned,
            intents=intents,
            help_command=None,
            allowed_mentions=discord.AllowedMentions(everyone=False, roles=False, users=True),
            activity=discord.Activity(type=discord.ActivityType.watching, name=f"{BRAND_NAME} | /help"),
        )
        self.db = Database(DB_PATH)
        self.logger = logger

    async def setup_hook(self):
        cogs = [
            Configuration(self),
            Panels(self),
            Music(self),
            Welcome(self),
            Leveling(self),
            Economy(self),
            Fun(self),
            Events(self),
            Extras(self),
        ]
        for cog in cogs:
            try:
                trim_cog_app_commands(cog)
                await self.add_cog(cog)
                logger.info("Loaded cog: %s", cog.qualified_name)
            except Exception:
                logger.exception("Failed to load cog: %s", cog.__class__.__name__)

        self.message_xp_cooldowns: dict[tuple[int, int], datetime] = {}

        self.add_view(AnimationHubView(self))
        self.add_view(HelpPanelView(self))
        self.add_view(EventRSVPView(self))
        self.add_view(ShopLaunchView(self))
        self.add_view(TicketPanelView(self))
        self.add_view(TicketCloseView(self))

        for group_name in DISABLED_COMMAND_GROUPS:
            self.tree.remove_command(group_name)

        for group_name, command_names in DISABLED_GROUP_COMMANDS.items():
            group = self.tree.get_command(group_name)
            if isinstance(group, app_commands.Group):
                for command_name in command_names:
                    group.remove_command(command_name)
        for command_name in DISABLED_ROOT_COMMANDS:
            self.tree.remove_command(command_name)

        admin_roots = {"staff", "pro"}
        admin_names = {
            "addshoprole",
            "clear",
            "clearchannel",
            "dm",
            "event",
            "giveaway",
            "panel",
            "poll",
            "removeshoprole",
            "say",
            "setwelcome",
            "setlogs",
            "setannounce",
            "setchannel",
            "setlevelchannel",
            "setstaffrole",
            "setupuzumakilevels",
            "shoppanel",
        }
        admin_permissions = discord.Permissions(manage_guild=True)
        for command in self.tree.get_commands():
            if command.name in admin_roots or command.name in admin_names:
                command.default_permissions = admin_permissions
        for command in self.tree.walk_commands():
            root_name = command.qualified_name.split(" ", 1)[0]
            if root_name in admin_roots or command.name in admin_names:
                command.default_permissions = admin_permissions

        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)

            # Copie les commandes dans le serveur de test, puis nettoie les anciennes globales.
            self.tree.copy_global_to(guild=guild)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()

            synced = await self.tree.sync(guild=guild)
            logger.info("Slash commands synced for guild %s (%s commands)", GUILD_ID, len(synced))
        else:
            synced = await self.tree.sync()
            logger.info("Global slash commands synced (%s commands)", len(synced))

        if synced:
            logger.info("Synced commands: %s", ", ".join(sorted(command.name for command in synced)))
        else:
            logger.warning("No application commands were synced")

        if not rotate_status.is_running():
            rotate_status.start()


bot = UzumakiBot()


@tasks.loop(minutes=15)
async def rotate_status():
    choices = [
        discord.Activity(type=discord.ActivityType.watching, name=f"{BRAND_NAME} | /help"),
        discord.Game("/hub pour le panel"),
        discord.Activity(type=discord.ActivityType.listening, name="les membres du serv"),
    ]
    current = getattr(rotate_status, "_idx", 0)
    await bot.change_presence(activity=choices[current % len(choices)])
    setattr(rotate_status, "_idx", current + 1)


@rotate_status.before_loop
async def before_status():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    logger.info("Connected as %s (%s)", bot.user, bot.user.id)


@bot.tree.error
async def on_tree_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    logger.warning("App command error: %s", error)
    message = str(error)
    if isinstance(error, app_commands.CheckFailure):
        message = str(error)
    try:
        await safe_interaction_send(interaction, message, ephemeral=True)
    except discord.HTTPException:
        logger.exception("Failed to send command error response")


# -----------------------------
# Cogs
# -----------------------------


class Configuration(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @app_commands.command(name="dm", description="Envoyer un message privé")
    @staff_only()
    async def dm(self, interaction: discord.Interaction, membre: discord.Member, message: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

        try:
            await membre.send(message)
            await interaction.response.send_message(f"✅ Message envoyé à {membre.mention}", ephemeral=True)
        except discord.Forbidden:
            await interaction.response.send_message("❌ Impossible (DM fermés)", ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Erreur: {e}", ephemeral=True)

    @app_commands.command(name="setwelcome", description="Définit le salon de bienvenue")
    @staff_only()
    async def setwelcome(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "welcome_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon de bienvenue défini sur {channel.mention}.", ephemeral=True)

    @app_commands.command(name="setlogs", description="Définit le salon de logs")
    @staff_only()
    async def setlogs(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "log_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon de logs défini sur {channel.mention}.", ephemeral=True)

    config = app_commands.Group(name="config", description="Configurer le bot")

    @config.command(name="confess", description="Configure le salon ou la catégorie pour les confessions anonymes")
    @staff_only()
    async def confess(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        category: Optional[discord.CategoryChannel] = None,
    ):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)

        if channel is None and category is None:
            current_channel_id = configured_channel_id(self.bot.db, interaction.guild.id, "confession_channel_id", 0)
            current_category_id = configured_channel_id(self.bot.db, interaction.guild.id, "confession_category_id", 0)
            current_channel = interaction.guild.get_channel(current_channel_id) if current_channel_id else None
            current_category = interaction.guild.get_channel(current_category_id) if current_category_id else None
            lines = []
            if current_channel and isinstance(current_channel, discord.TextChannel):
                lines.append(f"Salon de confession actuel : {current_channel.mention}")
            if current_category and isinstance(current_category, discord.CategoryChannel):
                lines.append(f"Catégorie de confession actuelle : {current_category.name}")
            if not lines:
                lines.append("Aucun salon ni catégorie de confession configuré.")
            return await interaction.response.send_message("\n".join(lines), ephemeral=True)

        responses = []
        if channel is not None:
            self.bot.db.set_setting(interaction.guild.id, "confession_channel_id", str(channel.id))
            responses.append(f"Salon de confession configuré sur {channel.mention}.")
        if category is not None:
            self.bot.db.set_setting(interaction.guild.id, "confession_category_id", str(category.id))
            responses.append(f"Catégorie de confession configurée sur {category.name}.")

        await interaction.response.send_message(" ".join(responses), ephemeral=True)

    @app_commands.command(name="setannounce", description="Définit le salon d'annonce pour les events")
    @staff_only()
    async def setannounce(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "announce_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon d'annonce défini sur {channel.mention}.", ephemeral=True)

    @app_commands.command(name="setlevelchannel", description="Définit le salon d'annonce des niveaux")
    @staff_only()
    async def setlevelchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "level_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon des niveaux défini sur {channel.mention}.", ephemeral=True)

    @app_commands.command(name="setstaffrole", description="Définit le rôle staff utilisé par le bot")
    @staff_only()
    async def setstaffrole(self, interaction: discord.Interaction, role: discord.Role):
        self.bot.db.set_setting(interaction.guild.id, "staff_role_id", str(role.id))
        await interaction.response.send_message(f"Rôle staff défini sur {role.mention}.", ephemeral=True)

    @app_commands.command(name="addshoprole", description="Ajoute un rôle achetable dans la boutique")
    @staff_only()
    @app_commands.describe(
        item_key="Clé courte sans espace, ex: uzumaki-lvl-1",
        title="Nom affiché en boutique",
        role="Rôle donné à l'achat",
        price="Prix en ¥",
        required_level="Niveau requis",
        description="Description de l'achat",
    )
    async def addshoprole(
        self,
        interaction: discord.Interaction,
        item_key: str,
        title: str,
        role: discord.Role,
        price: app_commands.Range[int, 100, 1_000_000],
        required_level: app_commands.Range[int, 1, 100],
        description: str,
    ):
        clean_key = item_key.lower().replace(" ", "-")
        self.bot.db.add_shop_role(interaction.guild.id, clean_key, title, role.id, price, required_level, description)
        embed = build_embed("Rôle boutique ajouté", f"**{title}** a été ajouté à la boutique sous la clé `{clean_key}`.")
        embed.add_field(name="Prix", value=f"{price} ¥")
        embed.add_field(name="Niveau requis", value=str(required_level))
        embed.add_field(name="Rôle", value=role.mention)
        await interaction.response.send_message(embed=embed, ephemeral=True)


    @app_commands.command(name="setupuzumakilevels", description="Ajoute rapidement les 4 rôles Uzumaki prestige à la boutique")
    @staff_only()
    async def setupuzumakilevels(
        self,
        interaction: discord.Interaction,
        role_lvl_1: discord.Role,
        role_lvl_2: discord.Role,
        role_lvl_3: discord.Role,
        role_lvl_4: discord.Role,
    ):
        presets = [
            ("uzumaki-lvl-1", "Uzumaki LVL 1", role_lvl_1, 2200, 3, "Premier rôle prestige Uzumaki"),
            ("uzumaki-lvl-2", "Uzumaki LVL 2", role_lvl_2, 4800, 6, "Rôle prestige intermédiaire"),
            ("uzumaki-lvl-3", "Uzumaki LVL 3", role_lvl_3, 9000, 10, "Rôle prestige avancé"),
            ("uzumaki-lvl-4", "Uzumaki LVL 4", role_lvl_4, 15000, 15, "Rôle prestige ultime"),
        ]
        for item_key, title, role, price, required_level, description in presets:
            self.bot.db.add_shop_role(interaction.guild.id, item_key, title, role.id, price, required_level, description)
        embed = build_embed("Rôles prestige ajoutés", "Les 4 rôles Uzumaki ont été ajoutés à la boutique.")
        embed.add_field(name="Liste", value="\n".join(f"• {title} — {format_coins(price)} ¥ • niveau {required_level}" for _, title, _, price, required_level, _ in presets), inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="removeshoprole", description="Retire un rôle de la boutique")
    @staff_only()
    async def removeshoprole(self, interaction: discord.Interaction, item_key: str):
        self.bot.db.remove_shop_role(interaction.guild.id, item_key.lower().strip())
        await interaction.response.send_message(f"Objet boutique `{item_key}` supprimé.", ephemeral=True)


class Panels(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @app_commands.command(name="help", description="Affiche l'aide du bot")
    async def help(self, interaction: discord.Interaction):
        embed = build_embed("Aide Uzumaki", "Commandes principales du serveur : économie, niveaux, mini-jeux, images et interactions.")
        embed.add_field(name="Économie", value="`/daily` `/weekly` `/missions` `/claimmission` `/work` `/mine` `/ores` `/sellores` `/balance` `/bank` `/deposit` `/withdraw` `/interest` `/shop` `/buy` `/inventory` `/sell` `/prestige` `/rank` `/rep`", inline=False)
        embed.add_field(name="Jeux", value="`/dice` `/rps` `/roulette` `/coinflip` `/guessnumber` `/duel` `/ship` `/rate`", inline=False)
        embed.add_field(name="Musique", value="`/music play` `/music queue` `/music voteskip` `/music repeat` `/music autoplay` `/music shuffle` `/music favorites` `/music playfavorite` `/music history` `/music lyrics` `/music setchannel` `/music setdjrole`", inline=False)
        embed.add_field(name="Interactions", value="`/rp kiss` `/rp hug` `/rp pat` `/rp slap` `/rp highfive` `/image wanted` `/image jailcard` `/avatar` `/userinfo`", inline=False)
        if interaction.guild and isinstance(interaction.user, discord.Member) and is_staff(interaction.user, self.bot.db):
            embed.add_field(name="Staff", value="`/setwelcome` `/setlogs` `/setannounce` `/panel` `/event` `/staff`", inline=False)
        await interaction.response.send_message(embed=embed, view=HelpPanelView(self.bot), ephemeral=True)

    @app_commands.command(name="hub", description="Ouvre le centre d'animation du bot")
    async def hub(self, interaction: discord.Interaction):
        embed = build_embed("Centre d'animation", "Lance rapidement ton daily, ton profil, la boutique ou une animation depuis ce panneau.")
        embed.add_field(name="Accès rapide", value="Daily  Profil  Boutique", inline=False)
        await interaction.response.send_message(embed=embed, view=AnimationHubView(self.bot))

    @app_commands.command(name="panel", description="Envoie le panneau d'animation dans un salon")
    @staff_only()
    async def panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = build_embed("🌀 Hub Uzumaki", "Bienvenue dans le panneau d'animation. Utilise les boutons ci-dessous ou le menu de sélection pour interagir avec le bot.")
        embed.add_field(name="Accès rapide", value="Daily • Profil • Boutique", inline=False)
        await channel.send(embed=embed, view=AnimationHubView(self.bot))
        await interaction.response.send_message(f"Panneau envoyé dans {channel.mention}.", ephemeral=True)

    @app_commands.command(name="shoppanel", description="Envoie un panneau boutique dans un salon")
    @staff_only()
    async def shoppanel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = build_embed("🛍️ Boutique Uzumaki", "Ouvre la boutique avec le bouton ci-dessous. Tu y trouveras les boosts, cosmétiques et rôles prestige Uzumaki.")
        await channel.send(embed=embed, view=ShopLaunchView(self.bot))
        await interaction.response.send_message(f"Panneau boutique envoyé dans {channel.mention}.", ephemeral=True)

    @app_commands.command(name="confession", description="Partage un message anonyme avec boutons d'interaction")
    async def confession(self, interaction: discord.Interaction, message: str, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        text = message.strip()[:300]

        # Si pas de membre spécifié, c'est un message général anonyme
        if member is None or member.bot or member.id == interaction.user.id:
            if member and (member.bot or member.id == interaction.user.id):
                return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
            # Message général anonyme
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "confession",
                default_title="📝 Message Anonyme",
                default_description="Quelqu'un partage un message anonyme.\n\n**Message :** {message}",
                member=None,
                user="Quelqu'un",
                message=text,
            )
            embed._author = None
            if not self.bot.db.get_setting(interaction.guild.id, "confession_embed_description"):
                embed.description = f"Quelqu'un partage un message anonyme.\n\n**Message :** {text}"
        else:
            # Message à quelqu'un
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "confession",
                default_title="📝 Message Anonyme",
                default_description="{user} envoie un message anonyme à {member}.\n\n**Message :** {message}",
                member=member,
                user="Quelqu'un",
                message=text,
            )
            embed._author = None
            if not self.bot.db.get_setting(interaction.guild.id, "confession_embed_description"):
                embed.description = f"Quelqu'un envoie un message anonyme à {member.mention}.\n\n**Message :** {text}"

        view = PublicConfessionView(self.bot, interaction.user.id, member.id if member else 0, anonymous=True)
        channel_id = configured_channel_id(self.bot.db, interaction.guild.id, "confession_channel_id", 0)
        channel = interaction.guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            # Always use webhook for anonymity
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if not webhook:
                try:
                    webhook = await channel.create_webhook(name="Anonymous Confessions")
                except discord.Forbidden:
                    # Fallback to normal send if no permission
                    await channel.send(embed=embed, view=view)
                    return await safe_interaction_send(interaction, f"Message envoyé dans {channel.mention}.", ephemeral=True)
            await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
            return await safe_interaction_send(interaction, f"Message envoyé dans {channel.mention}.", ephemeral=True)
        # If no channel configured, send in current channel
        try:
            webhooks = await interaction.channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if not webhook:
                webhook = await interaction.channel.create_webhook(name="Anonymous Confessions")
            await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
        except (discord.Forbidden, AttributeError):
            # Fallback
            await safe_interaction_send(interaction, embed=embed, view=view)


class Welcome(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        autorole_id = self.bot.db.get_setting(member.guild.id, "autorole_id")
        if autorole_id and autorole_id.isdigit():
            role = member.guild.get_role(int(autorole_id))
            if role and member.guild.me and member.guild.me.guild_permissions.manage_roles and role < member.guild.me.top_role:
                try:
                    await member.add_roles(role, reason="Autorole Uzumaki")
                except discord.HTTPException:
                    pass

        channel_id = configured_channel_id(self.bot.db, member.guild.id, "welcome_channel_id", WELCOME_CHANNEL_ID)
        channel = member.guild.get_channel(channel_id) if channel_id else None
        if isinstance(channel, discord.TextChannel):
            fallback_description = self.bot.db.get_setting(member.guild.id, "welcome_message") or "Bienvenue {member} sur **{server}**.\nProfite du serveur, decouvre les salons et amuse-toi bien."
            embed = build_managed_embed(
                self.bot.db,
                member.guild,
                "welcome",
                default_title="Bienvenue sur {server}",
                default_description=fallback_description,
                member=member,
            )
            if self.bot.db.get_setting(member.guild.id, "welcome_embed_image_url"):
                await channel.send(embed=embed)
            else:
                try:
                    image_bytes = await create_welcome_image(member)
                    file = discord.File(image_bytes, filename="welcome_card.png")
                    embed.set_image(url="attachment://welcome_card.png")
                    await channel.send(embed=embed, file=file)
                except Exception:
                    logger.exception("Failed to generate welcome image")
                    await channel.send(embed=embed)
            return
            template = self.bot.db.get_setting(member.guild.id, "welcome_message")
            if template:
                try:
                    welcome_text = template.format(member=member.mention, server=member.guild.name)
                except Exception:
                    welcome_text = template
            else:
                welcome_text = f"Bienvenue {member.mention} sur **{member.guild.name}**.\nProfite du serveur, découvre les salons et amuse-toi bien 🌸"
            embed = build_embed(
                f"Bienvenue sur {member.guild.name}",
                welcome_text,
            )
            embed.set_thumbnail(url=member.display_avatar.url)
            try:
                image_bytes = await create_welcome_image(member)
                file = discord.File(image_bytes, filename="welcome_card.png")
                embed.set_image(url="attachment://welcome_card.png")
                await channel.send(embed=embed, file=file)
            except Exception:
                logger.exception("Failed to generate welcome image")
                await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member):
        if before.premium_since is not None or after.premium_since is None:
            return
        channel_id = configured_channel_id(self.bot.db, after.guild.id, "boost_channel_id", 0)
        channel = after.guild.get_channel(channel_id) if channel_id else after.guild.system_channel
        if not isinstance(channel, discord.TextChannel):
            return
        embed = build_managed_embed(
            self.bot.db,
            after.guild,
            "boost",
            default_title="Nouveau boost",
            default_description="{member} vient de booster **{server}** !\nBoosts serveur : **{boosts}**.",
            member=after,
        )
        await channel.send(embed=embed)


class Events(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @app_commands.command(name="event", description="Crée un event avec boutons RSVP")
    @staff_only()
    async def event(self, interaction: discord.Interaction, title: str, when: str, description: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        channel_id = configured_channel_id(self.bot.db, interaction.guild.id, "announce_channel_id", ANNOUNCE_CHANNEL_ID)
        target = interaction.guild.get_channel(channel_id) if channel_id else interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message("Salon d'annonce introuvable. Configure-le d'abord.", ephemeral=True)
        embed = build_embed(f"📅 {title}", description)
        embed.add_field(name="Quand", value=when, inline=False)
        embed.add_field(name="Participants", value="✅ Intéressé : **0**\n🤔 Peut-être : **0**\n❌ Indisponible : **0**", inline=False)
        if interaction.guild.icon:
            embed.set_thumbnail(url=interaction.guild.icon.url)
        await target.send(embed=embed, view=EventRSVPView(self.bot))
        await interaction.response.send_message(f"Event envoyé dans {target.mention}.", ephemeral=True)




class Leveling(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot or not isinstance(message.author, discord.Member):
            return

        content = (message.content or "").strip()
        if not content:
            return

        self.bot.db.increment_message_count(message.guild.id, message.author.id, utc_now().date().isoformat())

        normalized = content.lower().strip(" !.;,:")
        if normalized == "quoi":
            try:
                await message.reply("feurrr", mention_author=False)
            except discord.HTTPException:
                pass

        if len(content) < 3:
            return

        now = utc_now()
        key = (message.guild.id, message.author.id)
        last_time = self.bot.message_xp_cooldowns.get(key)
        if last_time and (now - last_time).total_seconds() < 60:
            return
        self.bot.message_xp_cooldowns[key] = now
        level, xp, bank_limit, leveled = self.bot.db.add_xp(message.guild.id, message.author.id, random.randint(8, 14))
        if not leveled:
            return
        channel_id = configured_channel_id(self.bot.db, message.guild.id, "level_channel_id", LEVEL_CHANNEL_ID)
        target = message.guild.get_channel(channel_id) if channel_id else message.channel
        if isinstance(target, discord.TextChannel):
            reward_role_id = self.bot.db.get_setting(message.guild.id, f"level_reward:{level}")
            if reward_role_id and reward_role_id.isdigit():
                role = message.guild.get_role(int(reward_role_id))
                if role and role not in message.author.roles and message.guild.me and message.guild.me.guild_permissions.manage_roles and role < message.guild.me.top_role:
                    try:
                        await message.author.add_roles(role, reason=f"Récompense niveau {level}")
                    except discord.HTTPException:
                        pass
            embed = build_embed(
                "🌸 Level up",
                f"{message.author.mention} passe niveau **{level}** !\nNouvelle capacité banque : **{format_coins(bank_limit)} ¥**",
                color=discord.Color.purple(),
            )
            embed.set_thumbnail(url=message.author.display_avatar.url)
            try:
                await target.send(embed=embed)
            except discord.HTTPException:
                pass

class Economy(commands.Cog, name="Economy"):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    def build_inventory_embed(self, guild_id: int, user_id: int, mention: str) -> discord.Embed:
        rows = self.bot.db.get_inventory(guild_id, user_id)
        if not rows:
            return build_embed("Inventaire", f"{mention} n'a aucun objet pour l'instant.")
        lines = []
        for row in rows[:20]:
            key = str(row["item_key"])
            qty = int(row["quantity"])
            title = ore_label(key) if key.startswith("ore:") else (BUILTIN_SHOP_ITEMS[key].title if key in BUILTIN_SHOP_ITEMS else key)
            lines.append(f"• **{title}** (`{key}`) × **{qty}**")
        return build_embed("Inventaire", "\n".join(lines))

    async def credit_bakery_owner(self, guild: discord.Guild, amount: int) -> bool:
        owner: Optional[discord.Member] = None

        if BAKERY_OWNER_ID:
            owner = guild.get_member(BAKERY_OWNER_ID)

        if owner is None:
            for member in guild.members:
                if member.name.lower() == BAKERY_OWNER_NAME or member.display_name.lower() == BAKERY_OWNER_NAME:
                    owner = member
                    break

        if owner is None:
            return False

        self.bot.db.update_money(guild.id, owner.id, wallet_delta=amount)
        return True

    async def buy_from_key(self, interaction: discord.Interaction, item_key: str):
        if not interaction.guild or not isinstance(interaction.user, discord.Member):
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)

        key = item_key.lower().strip()
        if key in BUILTIN_SHOP_ITEMS:
            ok, message = apply_builtin_purchase(self.bot.db, interaction.guild.id, interaction.user.id, key)

            if ok and BUILTIN_SHOP_ITEMS[key].kind == "bakery_food":
                owner_gain = max(1, int(BUILTIN_SHOP_ITEMS[key].price * 0.25))
                credited = await self.credit_bakery_owner(interaction.guild, owner_gain)

                if credited:
                    message += f"\n🥐 **{format_coins(owner_gain)} ¥** ont été versés à la boulangerie de **@matheossi.**"
                else:
                    message += "\n🥐 Vente effectuée, mais le propriétaire de la boulangerie est introuvable."

            color = discord.Color.green() if ok else discord.Color.red()
            return await interaction.response.send_message(embed=build_embed("Boutique", message, color=color), ephemeral=True)

        row = self.bot.db.get_shop_role(interaction.guild.id, key)
        if row is None:
            return await interaction.response.send_message("Objet boutique introuvable.", ephemeral=True)

        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        if int(profile["level"]) < int(row["required_level"]):
            return await interaction.response.send_message(f"Niveau requis : **{int(row['required_level'])}**.", ephemeral=True)
        if int(profile["wallet"]) < int(row["price"]):
            return await interaction.response.send_message("Tu n'as pas assez dans ton portefeuille.", ephemeral=True)

        role = interaction.guild.get_role(int(row["role_id"]))
        if role is None:
            return await interaction.response.send_message("Le rôle lié à cet objet est introuvable.", ephemeral=True)
        if role in interaction.user.roles:
            return await interaction.response.send_message("Tu possèdes déjà ce rôle.", ephemeral=True)

        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-int(row["price"]))
        await interaction.user.add_roles(role, reason="Achat boutique Uzumaki")
        await interaction.response.send_message(embed=build_embed("Boutique", f"Achat réussi : **{row['title']}** pour **{format_coins(int(row['price']))} ¥**.", color=discord.Color.green()), ephemeral=True)

    @app_commands.command(name="profile", description="Affiche ton profil économie complet")
    async def profile(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        await interaction.response.send_message(embed=build_profile_embed(self.bot.db, target))


    @app_commands.command(name="rank", description="Affiche le rang niveau d'un membre")
    async def rank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self.bot.db.get_profile(interaction.guild.id, target.id)
        next_level = int(row["level"]) * 120
        embed = build_embed("Rang", f"Progression de {target.mention}")
        embed.add_field(name="Niveau", value=str(int(row["level"])), inline=True)
        embed.add_field(name="XP", value=f"{progress_bar(int(row['xp']), next_level)}\n{int(row['xp'])}/{next_level}", inline=False)
        embed.add_field(name="Prestige", value=str(int(row["prestige"])), inline=True)
        embed.add_field(name="Rep", value=str(int(row["rep"])), inline=True)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="levelboard", description="Classement des niveaux du serveur")
    async def levelboard(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        rows = self.bot.db.get_top_levels(interaction.guild.id, 10)
        if not rows:
            return await interaction.response.send_message("Aucun classement pour l'instant.")
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(row["user_id"]))
            display = member.mention if member else f"<@{row['user_id']}>"
            rank = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(f"{rank} {display} — niveau **{int(row['level'])}** • xp **{int(row['xp'])}** • rep **{int(row['rep'])}**")
        await interaction.response.send_message(embed=build_embed("Classement niveaux", "\n".join(lines), color=discord.Color.purple()))

    @app_commands.command(name="rep", description="Donne 1 point de réputation à un membre")
    async def rep(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_rep"], timedelta(hours=12))
        if next_time:
            return await interaction.response.send_message(f"Tu as déjà donné une rep. Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        self.bot.db.add_rep(interaction.guild.id, member.id, 1)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_rep", utc_now().isoformat())
        target = self.bot.db.get_profile(interaction.guild.id, member.id)
        await interaction.response.send_message(embed=build_embed("Réputation donnée", f"Tu as donné **+1 rep** à {member.mention}.\nTotal : **{int(target['rep'])} rep**", color=discord.Color.green()))

    @app_commands.command(name="repboard", description="Classement de réputation du serveur")
    async def repboard(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        rows = self.bot.db.get_top_rep(interaction.guild.id, 10)
        if not rows:
            return await interaction.response.send_message("Aucun classement pour l'instant.")
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(row["user_id"]))
            display = member.mention if member else f"<@{row['user_id']}>"
            rank = medals[index - 1] if index <= 3 else f"`#{index}`"
            lines.append(f"{rank} {display} — **{int(row['rep'])} rep**")
        await interaction.response.send_message(embed=build_embed("Classement réputation", "\n".join(lines), color=discord.Color.green()))

    @app_commands.command(name="daily", description="Récupère ta récompense quotidienne")
    async def daily(self, interaction: discord.Interaction):
        _, embed = claim_daily(self.bot.db, interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="weekly", description="Récupère une récompense hebdomadaire")
    async def weekly(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_claim = cooldown_remaining(row["last_weekly"], timedelta(days=7))
        if next_claim:
            return await interaction.response.send_message(f"Tu as déjà pris ton weekly. Reviens <t:{int(next_claim.timestamp())}:R>.", ephemeral=True)
        reward = 450 + int(row["prestige"]) * 40
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_weekly", utc_now().isoformat())
        level, _, bank_limit, leveled = self.bot.db.add_xp(interaction.guild.id, interaction.user.id, 45)
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed("Weekly récupéré", f"Tu as gagné **{format_coins(reward)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.green())
        if leveled:
            embed.add_field(name="Level up", value=f"Niveau **{level}** atteint. Capacité banque : **{format_coins(bank_limit)} ¥**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="work", description="Travaille pour gagner un peu d'argent")
    async def work(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_work"], timedelta(hours=1, minutes=30))
        if next_time:
            return await interaction.response.send_message(f"Tu as déjà travaillé. Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        jobs = [
            ("tu as aidé à modérer un salon", 70),
            ("tu as organisé une petite animation", 85),
            ("tu as fait le service dans un café sakura", 95),
            ("tu as vendu des snacks au vocal", 110),
            ("tu as aidé à préparer un event", 125),
        ]
        text, base = random.choice(jobs)
        reward = int(round(base * (1 + float(row["work_bonus"]) + int(row["prestige"]) * 0.03)))
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_work", utc_now().isoformat())
        self.bot.db.add_xp(interaction.guild.id, interaction.user.id, random.randint(10, 18))
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        await interaction.response.send_message(embed=build_embed("Travail terminé", f"{interaction.user.mention}, {text}.\nTu gagnes **{format_coins(reward)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.blurple()))

    @app_commands.command(name="missions", description="Affiche tes missions pour gagner de l'argent")
    async def missions(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        day = utc_now().date().isoformat()
        count = self.bot.db.get_message_count(interaction.guild.id, interaction.user.id, day)
        claimed = self.bot.db.get_setting(interaction.guild.id, f"mission:messages:{day}:{interaction.user.id}") == "claimed"
        remaining = max(MESSAGE_MISSION_TARGET - count, 0)
        embed = build_embed(
            "Missions du jour",
            f"Messages envoyes : **{min(count, MESSAGE_MISSION_TARGET)}/{MESSAGE_MISSION_TARGET}**\n"
            f"Récompense : **{format_coins(MESSAGE_MISSION_REWARD)} ¥** + **{MESSAGE_MISSION_XP} XP**\n"
            f"Statut : **{'réclamée' if claimed else 'prête' if remaining == 0 else f'{remaining} messages restants'}**",
            color=discord.Color.gold(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="claimmission", description="Récupère la récompense de ta mission messages")
    async def claimmission(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        day = utc_now().date().isoformat()
        key = f"mission:messages:{day}:{interaction.user.id}"
        if self.bot.db.get_setting(interaction.guild.id, key) == "claimed":
            return await interaction.response.send_message("Tu as déjà réclamé cette mission aujourd'hui.", ephemeral=True)
        count = self.bot.db.get_message_count(interaction.guild.id, interaction.user.id, day)
        if count < MESSAGE_MISSION_TARGET:
            return await interaction.response.send_message(f"Mission pas finie : **{count}/{MESSAGE_MISSION_TARGET}** messages.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=MESSAGE_MISSION_REWARD)
        self.bot.db.add_xp(interaction.guild.id, interaction.user.id, MESSAGE_MISSION_XP)
        self.bot.db.set_setting(interaction.guild.id, key, "claimed")
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed(
            "Mission terminée",
            f"Tu gagnes **{format_coins(MESSAGE_MISSION_REWARD)} ¥** et **{MESSAGE_MISSION_XP} XP**.\n"
            f"Portefeuille : **{format_coins(int(profile['wallet']))} ¥**",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="mine", description="Mine des minerais à revendre")
    async def mine(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_work"], timedelta(minutes=25))
        if next_time:
            return await interaction.response.send_message(f"Tu dois attendre <t:{int(next_time.timestamp())}:R> avant de miner.", ephemeral=True)
        swings = random.randint(2, 5)
        found: dict[str, int] = {}
        for _ in range(swings):
            ore_key = choose_ore_key()
            found[ore_key] = found.get(ore_key, 0) + 1
            self.bot.db.add_inventory_item(interaction.guild.id, interaction.user.id, ore_item_key(ore_key), 1)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_work", utc_now().isoformat())
        self.bot.db.add_xp(interaction.guild.id, interaction.user.id, random.randint(10, 20))
        lines = [f"**{ORE_ITEMS[ore]['title']}** x{qty} - {format_coins(int(ORE_ITEMS[ore]['value']))} ¥/u" for ore, qty in found.items()]
        await interaction.response.send_message(embed=build_embed("Mine", "\n".join(lines), color=discord.Color.dark_gold()))

    @app_commands.command(name="ores", description="Affiche tes minerais")
    async def ores(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        rows = self.bot.db.get_inventory(interaction.guild.id, interaction.user.id)
        lines = []
        total = 0
        for row in rows:
            key = str(row["item_key"])
            if not key.startswith("ore:"):
                continue
            ore_key = key.split(":", 1)[1]
            if ore_key not in ORE_ITEMS:
                continue
            qty = int(row["quantity"])
            value = int(ORE_ITEMS[ore_key]["value"]) * qty
            total += value
            lines.append(f"**{ORE_ITEMS[ore_key]['title']}** x{qty} - {format_coins(value)} ¥")
        embed = build_embed("Minerais", "\n".join(lines) if lines else "Aucun minerai. Utilise `/mine`.", color=discord.Color.dark_gold())
        embed.add_field(name="Valeur totale", value=f"**{format_coins(total)} ¥**", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="sellores", description="Vend tes minerais (utilise all pour tout vendre)")
    async def sellores(self, interaction: discord.Interaction, ore: Optional[str] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        rows = self.bot.db.get_inventory(interaction.guild.id, interaction.user.id)
        target_ore = ore.lower().strip() if ore else "all"
        if target_ore in {"all", "tout"}:
            target_ore = None
        total = 0
        sold_lines = []
        known = False
        for row in rows:
            key = str(row["item_key"])
            if not key.startswith("ore:"):
                continue
            ore_key = key.split(":", 1)[1]
            title = str(ORE_ITEMS.get(ore_key, {}).get("title", "")).lower()
            if target_ore and target_ore not in {ore_key, title}:
                continue
            if ore_key not in ORE_ITEMS:
                continue
            known = True
            qty = int(row["quantity"])
            gain = int(ORE_ITEMS[ore_key]["value"]) * qty
            total += gain
            self.bot.db.add_inventory_item(interaction.guild.id, interaction.user.id, key, -qty)
            sold_lines.append(f"{ORE_ITEMS[ore_key]['title']} x{qty}")
        if target_ore and not known:
            return await interaction.response.send_message("Minerai introuvable. Utilise `/ores` pour voir la liste des minerais disponibles.", ephemeral=True)
        if total <= 0:
            return await interaction.response.send_message("Aucun minerai à vendre pour ce choix.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=total)
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed(
            "Minerais vendus",
            f"{', '.join(sold_lines)}\nGain : **{format_coins(total)} ¥**\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**",
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="crime", description="Tente un coup risqué")
    async def crime(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_crime"], timedelta(hours=3))
        if next_time:
            return await interaction.response.send_message(f"Trop risqué pour le moment. Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_crime", utc_now().isoformat())
        success_rate = 0.42 + float(row["crime_bonus"]) + int(row["prestige"]) * 0.01
        if random.random() < success_rate:
            reward = random.randint(140, 260)
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
            self.bot.db.add_xp(interaction.guild.id, interaction.user.id, 18)
            profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
            embed = build_embed("Coup réussi", f"Tu t'en sors avec **{format_coins(reward)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.green())
        else:
            penalty = random.randint(50, 120)
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-penalty)
            profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
            embed = build_embed("Coup raté", f"Tu t'es fait attraper et tu perds **{format_coins(penalty)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="heist", description="Tente un gros casse à haut risque")
    async def heist(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        if not can_use_heist(self.bot.db, interaction.guild.id, interaction.user.id):
            return await interaction.response.send_message("Tu dois atteindre le niveau 5 ou acheter **Plan de casse** dans la boutique.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_heist"], timedelta(hours=8))
        if next_time:
            return await interaction.response.send_message(f"Le prochain casse n'est pas prêt. Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_heist", utc_now().isoformat())
        success_rate = 0.25 + float(row["heist_bonus"]) + int(row["prestige"]) * 0.01
        if random.random() < success_rate:
            reward = random.randint(400, 850)
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
            self.bot.db.add_xp(interaction.guild.id, interaction.user.id, 35)
            profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
            embed = build_embed("Casse réussi", f"Tu reviens avec **{format_coins(reward)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.green())
        else:
            penalty = random.randint(120, 240)
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-penalty)
            profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
            embed = build_embed("Casse raté", f"Le plan a mal tourné. Tu perds **{format_coins(penalty)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="balance", description="Affiche le compte d'un membre")
    async def balance(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self.bot.db.get_profile(interaction.guild.id, target.id)
        total = int(row["wallet"]) + int(row["bank"])
        embed = build_embed("Compte", f"Résumé du compte de {target.mention}", color=discord.Color.gold())
        embed.add_field(name="Portefeuille", value=f"{format_coins(int(row['wallet']))} ¥")
        embed.add_field(name="Banque", value=f"{format_coins(int(row['bank']))} ¥")
        embed.add_field(name="Total", value=f"{format_coins(total)} ¥")
        embed.add_field(name="Capacité banque", value=f"{format_coins(int(row['bank_limit']))} ¥")
        embed.add_field(name="Niveau", value=str(int(row["level"])))
        embed.add_field(name="Prestige", value=str(int(row["prestige"])))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="bank", description="Affiche les détails bancaires")
    async def bank(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self.bot.db.get_profile(interaction.guild.id, target.id)
        remaining = max(int(row["bank_limit"]) - int(row["bank"]), 0)
        embed = build_embed("Compte bancaire", f"Informations bancaires de {target.mention}")
        embed.add_field(name="Déposé", value=f"{format_coins(int(row['bank']))} ¥", inline=True)
        embed.add_field(name="Capacité max", value=f"{format_coins(int(row['bank_limit']))} ¥", inline=True)
        embed.add_field(name="Place restante", value=f"{format_coins(remaining)} ¥", inline=True)
        embed.add_field(name="Taux intérêt", value="2% toutes les 12h via `/interest` (+ bonus shop)", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="deposit", description="Dépose de l'argent en banque")
    async def deposit(self, interaction: discord.Interaction, amount: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        wallet = int(row["wallet"])
        bank = int(row["bank"])
        bank_limit = int(row["bank_limit"])
        try:
            value = parse_amount(amount, wallet)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if value <= 0:
            return await interaction.response.send_message("Le montant doit être supérieur à 0.", ephemeral=True)
        if wallet < value:
            return await interaction.response.send_message("Tu n'as pas assez dans ton portefeuille.", ephemeral=True)
        free_space = bank_limit - bank
        if free_space <= 0:
            return await interaction.response.send_message("Ta banque est pleine. Monte de niveau ou achète des upgrades.", ephemeral=True)
        value = min(value, free_space)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-value, bank_delta=value)
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed("Dépôt effectué", f"Tu as déposé **{format_coins(value)} ¥** en banque.", color=discord.Color.green())
        embed.add_field(name="Portefeuille", value=f"{format_coins(int(profile['wallet']))} ¥")
        embed.add_field(name="Banque", value=f"{format_coins(int(profile['bank']))} ¥")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="withdraw", description="Retire de l'argent de la banque")
    async def withdraw(self, interaction: discord.Interaction, amount: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        bank = int(row["bank"])
        try:
            value = parse_amount(amount, bank)
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if value <= 0:
            return await interaction.response.send_message("Le montant doit être supérieur à 0.", ephemeral=True)
        if bank < value:
            return await interaction.response.send_message("Tu n'as pas assez en banque.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=value, bank_delta=-value)
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed("Retrait effectué", f"Tu as retiré **{format_coins(value)} ¥** de la banque.", color=discord.Color.blurple())
        embed.add_field(name="Portefeuille", value=f"{format_coins(int(profile['wallet']))} ¥")
        embed.add_field(name="Banque", value=f"{format_coins(int(profile['bank']))} ¥")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="interest", description="Récupère les intérêts de ta banque")
    async def interest(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        next_time = cooldown_remaining(row["last_interest"], timedelta(hours=12))
        if next_time:
            return await interaction.response.send_message(f"Les intérêts ne sont pas encore prêts. Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        bank_amount = int(row["bank"])
        if bank_amount < 500:
            return await interaction.response.send_message("Il faut au moins **500 ¥** en banque pour générer des intérêts.", ephemeral=True)
        rate = 0.02 + float(row["interest_bonus"])
        reward = max(10, int(bank_amount * rate))
        reward = min(reward, 220)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
        self.bot.db.set_last(interaction.guild.id, interaction.user.id, "last_interest", utc_now().isoformat())
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed("Intérêts récupérés", f"Ta banque t'a rapporté **{format_coins(reward)} ¥**.\nPortefeuille : **{format_coins(int(profile['wallet']))} ¥**", color=discord.Color.green())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @app_commands.command(name="pay", description="Envoie de l'argent à un membre (ex: 250, all)")
    async def pay(self, interaction: discord.Interaction, member: discord.Member, amount: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        if member.bot:
            return await interaction.response.send_message("Tu ne peux pas envoyer d'argent à un bot.", ephemeral=True)
        if member.id == interaction.user.id:
            return await interaction.response.send_message("Tu ne peux pas te payer toi-même.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        try:
            value = parse_amount(amount, int(row["wallet"]))
        except ValueError as e:
            return await interaction.response.send_message(str(e), ephemeral=True)
        if value <= 0:
            return await interaction.response.send_message("Le montant doit être supérieur à 0.", ephemeral=True)
        if int(row["wallet"]) < value:
            return await interaction.response.send_message("Tu n'as pas assez dans ton portefeuille.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-value)
        self.bot.db.update_money(interaction.guild.id, member.id, wallet_delta=value)
        sender = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        embed = build_embed("Transaction envoyée", f"Tu as envoyé **{format_coins(value)} ¥** à {member.mention}.", color=discord.Color.blurple())
        embed.add_field(name="Ton portefeuille", value=f"{format_coins(int(sender['wallet']))} ¥")
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="leaderboard", description="Classement de richesse du serveur")
    async def leaderboard(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        rows = self.bot.db.get_top_wallet(interaction.guild.id, 10)
        if not rows:
            return await interaction.response.send_message("Aucun classement pour l'instant.")
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for index, row in enumerate(rows, start=1):
            member = interaction.guild.get_member(int(row["user_id"]))
            display = member.mention if member else f"<@{row['user_id']}>"
            rank = medals[index - 1] if index <= 3 else f"`#{index}`"
            total = int(row["wallet"]) + int(row["bank"])
            prestige = int(row["prestige"])
            extra = f" • prestige {prestige}" if prestige else ""
            lines.append(f"{rank} {display} — **{format_coins(total)} ¥** (`cash {format_coins(int(row['wallet']))}` • `bank {format_coins(int(row['bank']))}`{extra})")
        await interaction.response.send_message(embed=build_embed("Classement Uzumaki", "\n".join(lines), color=discord.Color.gold()))

    @app_commands.command(name="inventory", description="Affiche ton inventaire")
    async def inventory(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        rows = self.bot.db.get_inventory(interaction.guild.id, target.id)
        if not rows:
            return await interaction.response.send_message(embed=build_embed("Inventaire", f"{target.mention} ne possède encore aucun objet."))
        lines = []
        for row in rows:
            item = BUILTIN_SHOP_ITEMS.get(str(row["item_key"]))
            label = item.title if item else str(row["item_key"])
            lines.append(f"• **{label}** × {int(row['quantity'])}")
        await interaction.response.send_message(embed=build_embed("Inventaire", "\n".join(lines)))


    @app_commands.command(name="use", description="Utilise un objet de ton inventaire quand c'est possible")
    async def use(self, interaction: discord.Interaction, item_key: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        key = item_key.lower().strip()
        qty = self.bot.db.get_item_quantity(interaction.guild.id, interaction.user.id, key)
        if qty <= 0:
            return await interaction.response.send_message("Tu ne possèdes pas cet objet.", ephemeral=True)
        if key == "sakura-badge":
            return await interaction.response.send_message(embed=build_embed("Badge Sakura", "Tu montres fièrement ton badge Sakura 🌸"), ephemeral=True)

        bakery_messages = {
            "pain-au-chocolat": "Tu manges un **pain au chocolat** bien chaud 🤤",
            "croissant": "Tu dégustes un **croissant** croustillant 🥐",
            "brioche": "Tu manges une **brioche** moelleuse 🍞",
            "baguette": "Tu croques dans une **baguette** fraîche 🥖",
            "pain": "Tu manges un bon **pain** tout juste sorti du four 🍞",
        }

        if key in bakery_messages:
            self.bot.db.add_inventory_item(interaction.guild.id, interaction.user.id, key, -1)
            return await interaction.response.send_message(embed=build_embed("Boulangerie", bakery_messages[key]), ephemeral=True)

        await interaction.response.send_message("Cet objet est passif ou ne peut pas être utilisé directement.", ephemeral=True)

    @app_commands.command(name="sell", description="Revends un objet de ton inventaire")
    async def sell(self, interaction: discord.Interaction, item_key: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        key = item_key.lower().strip()
        qty = self.bot.db.get_item_quantity(interaction.guild.id, interaction.user.id, key)
        if qty <= 0:
            return await interaction.response.send_message("Tu ne possèdes pas cet objet.", ephemeral=True)
        if key not in BUILTIN_SHOP_ITEMS:
            return await interaction.response.send_message("Seuls certains objets intégrés peuvent être revendus.", ephemeral=True)
        item = BUILTIN_SHOP_ITEMS[key]
        refund = max(1, int(item.price * 0.45))
        self.bot.db.add_inventory_item(interaction.guild.id, interaction.user.id, key, -1)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=refund)
        await interaction.response.send_message(embed=build_embed("Objet revendu", f"Tu as revendu **{item.title}** pour **{format_coins(refund)} ¥**.", color=discord.Color.green()), ephemeral=True)

    @app_commands.command(name="shop", description="Affiche la boutique du serveur")
    async def shop(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        embed, _, _ = build_shop_page_embed(self.bot, interaction.guild, interaction.user, "all", 0)
        await interaction.response.send_message(embed=embed, view=ShopBrowserView(self.bot, interaction.guild.id), ephemeral=True)

    @app_commands.command(name="buy", description="Achète un objet via sa clé")
    async def buy(self, interaction: discord.Interaction, item_key: str):
        await self.buy_from_key(interaction, item_key)

    @app_commands.command(name="coinflip", description="Pile ou face avec une mise")
    @app_commands.choices(choice=[
        app_commands.Choice(name="pile", value="pile"),
        app_commands.Choice(name="face", value="face"),
    ])
    async def coinflip(self, interaction: discord.Interaction, choice: app_commands.Choice[str], amount: app_commands.Range[int, 1, 350]):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        profile = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        if int(profile["wallet"]) < amount:
            return await interaction.response.send_message("Tu n'as pas assez de cash pour cette mise.", ephemeral=True)
        result = random.choice(["pile", "face"])
        if choice.value == result:
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=amount)
            total = int(self.bot.db.get_profile(interaction.guild.id, interaction.user.id)["wallet"])
            embed = build_embed("Coinflip gagné", f"Résultat : **{result}**\nTu gagnes **{format_coins(amount)} ¥**.\nCash : **{format_coins(total)} ¥**", color=discord.Color.green())
        else:
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-amount)
            total = int(self.bot.db.get_profile(interaction.guild.id, interaction.user.id)["wallet"])
            embed = build_embed("Coinflip perdu", f"Résultat : **{result}**\nTu perds **{format_coins(amount)} ¥**.\nCash : **{format_coins(total)} ¥**", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="prestige", description="Réinitialise ta progression pour gagner un prestige")
    async def prestige(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        total = int(row["wallet"]) + int(row["bank"])
        if int(row["level"]) < 15:
            return await interaction.response.send_message("Il faut être **niveau 15** minimum pour prestige.", ephemeral=True)
        if total < 10000:
            return await interaction.response.send_message("Il faut au moins **10 000 ¥** de richesse totale pour prestige.", ephemeral=True)
        new_prestige = self.bot.db.prestige_player(interaction.guild.id, interaction.user.id)
        embed = build_embed(
            "Prestige effectué",
            f"Tu passes au **prestige {new_prestige}**.\nTa progression éco est remise à zéro, mais tu gagnes des bonus permanents sur le long terme.",
            color=discord.Color.gold(),
        )
        embed.add_field(name="Nouveaux bonus", value="+3% travail • +0.2% intérêt • +1 000 capacité banque de base par prestige", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="serverinfo", description="Infos sur le serveur")
    async def serverinfo(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        guild = interaction.guild
        humans = len([m for m in guild.members if not m.bot])
        bots = len([m for m in guild.members if m.bot])
        embed = build_embed("Informations du serveur", guild.description or "Aucune description.")
        if guild.icon:
            embed.set_thumbnail(url=guild.icon.url)
        embed.add_field(name="Nom", value=guild.name)
        embed.add_field(name="Membres", value=f"{guild.member_count} total\n{humans} humains\n{bots} bots")
        embed.add_field(name="Créé", value=discord.utils.format_dt(guild.created_at, style="D"))
        embed.add_field(name="Salons", value=str(len(guild.channels)))
        embed.add_field(name="Rôles", value=str(len(guild.roles)))
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="avatar", description="Affiche l'avatar d'un membre")
    async def avatar(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        embed = build_embed("Avatar", target.mention)
        embed.set_image(url=target.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="userinfo", description="Affiche les infos d'un membre")
    async def userinfo(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self.bot.db.get_profile(interaction.guild.id, target.id)
        roles = [role.mention for role in target.roles if role != interaction.guild.default_role]
        embed = build_embed("Profil Discord", f"Informations de {target.mention}")
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.add_field(name="ID", value=f"`{target.id}`", inline=True)
        embed.add_field(name="Compte cr", value=discord.utils.format_dt(target.created_at, style="R"), inline=True)
        if target.joined_at:
            embed.add_field(name="A rejoint", value=discord.utils.format_dt(target.joined_at, style="R"), inline=True)
        embed.add_field(name="Niveau", value=str(int(row["level"])), inline=True)
        embed.add_field(name="Prestige", value=str(int(row["prestige"])), inline=True)
        embed.add_field(name="Réputation", value=str(int(row["rep"])), inline=True)
        embed.add_field(name=f"Rôles ({len(roles)})", value=", ".join(roles[:12]) if roles else "Aucun rôle", inline=False)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="poll", description="Crée un sondage rapide")
    @staff_only()
    async def poll(self, interaction: discord.Interaction, question: str, choice1: str, choice2: str, choice3: Optional[str] = None, choice4: Optional[str] = None):
        choices = [choice1, choice2]
        if choice3:
            choices.append(choice3)
        if choice4:
            choices.append(choice4)
        emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣"]
        content = "\n".join(f"{emojis[idx]} {choice}" for idx, choice in enumerate(choices))
        embed = build_embed(f"📊 {question}", content)
        await interaction.response.send_message(embed=embed)
        message = await interaction.original_response()
        for idx in range(len(choices)):
            await message.add_reaction(emojis[idx])

    
    @app_commands.command(name="say", description="Envoie un message")
    @app_commands.describe(message="Le message à envoyer")
    @staff_only()
    async def say(self, interaction: discord.Interaction, message: str):

        if interaction.guild is None:
            return await interaction.response.send_message(
                "Commande serveur uniquement.",
                ephemeral=True
            )

        await interaction.response.send_message(message)

    @app_commands.command(name="clear", description="Supprime des messages dans un salon")
    @staff_only()
    async def clear(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
        if not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Commande utilisable dans un salon texte.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"{len(deleted)} messages supprimés.", ephemeral=True)


class Fun(commands.Cog):
    def __init__(self, bot: UzumakiBot):
        self.bot = bot

    @app_commands.command(name="dice", description="Lance un ou plusieurs ds")
    async def dice(
        self,
        interaction: discord.Interaction,
        sides: app_commands.Range[int, 2, 100] = 6,
        rolls: app_commands.Range[int, 1, 10] = 1,
    ):
        results = [random.randint(1, int(sides)) for _ in range(int(rolls))]
        total = sum(results)
        detail = "  ".join(str(value) for value in results)
        description = f"{interaction.user.mention} lance **{rolls}d{sides}**.\nRsultat : **{detail}**"
        if rolls > 1:
            description += f"\nTotal : **{total}**"
        await interaction.response.send_message(embed=build_embed(" Lancer de ds", description))

    @app_commands.command(name="rps", description="Pierre / feuille / ciseaux")
    @app_commands.choices(choice=[
        app_commands.Choice(name="pierre", value="pierre"),
        app_commands.Choice(name="feuille", value="feuille"),
        app_commands.Choice(name="ciseaux", value="ciseaux"),
    ])
    async def rps(self, interaction: discord.Interaction, choice: app_commands.Choice[str]):
        user_choice = choice.value
        bot_choice = random.choice(["pierre", "feuille", "ciseaux"])
        wins = {"pierre": "ciseaux", "feuille": "pierre", "ciseaux": "feuille"}
        if user_choice == bot_choice:
            result = "Égalité."
            color = discord.Color.gold()
            reward = 0
        elif wins[user_choice] == bot_choice:
            result = "Tu gagnes."
            color = discord.Color.green()
            reward = 25
            if interaction.guild:
                self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
        else:
            result = "Tu perds."
            color = discord.Color.red()
            reward = 0
        extra = f"\nRécompense : **{format_coins(reward)} ¥**" if reward else ""
        await interaction.response.send_message(embed=build_embed("Pierre / Feuille / Ciseaux", f"Toi : **{user_choice}**\nBot : **{bot_choice}**\n\n{result}{extra}", color=color))

    @app_commands.command(name="eightball", description="Pose une question à la boule magique")
    async def eightball(self, interaction: discord.Interaction, question: str):
        answers = ["Oui clairement.", "Non clairement.", "Ça sent bien.", "Peut-être.", "Pas aujourd'hui.", "Repose la question plus tard."]
        await interaction.response.send_message(embed=build_embed("🎱 Boule magique", f"**Question :** {question}\n**Réponse :** {random.choice(answers)}"))

    @app_commands.command(name="pick", description="Choisit une option aléatoire")
    async def pick(self, interaction: discord.Interaction, options: str):
        values = [item.strip() for item in options.split(",") if item.strip()]
        if len(values) < 2:
            return await interaction.response.send_message("Mets au moins 2 choix séparés par des virgules.", ephemeral=True)
        await interaction.response.send_message(embed=build_embed("Choix aléatoire", f"Je choisis : **{random.choice(values)}**"))



    @app_commands.command(name="compliment", description="Envoie un compliment  un membre")
    async def compliment(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        compliments = [
            "tu as une nergie vraiment solaire",
            "tu rends le serveur plus vivant",
            "tu as un style impeccable",
            "tu mrites un bonus de bonne humeur",
            "ta prsence amliore le salon instantanment",
        ]
        embed = build_embed("Compliment", f"{target.mention}, {random.choice(compliments)}.")
        gif_url = await fetch_rp_gif("happy")
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="roast", description="Taquine gentiment un membre")
    async def roast(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        roasts = [
            "tu lagues mme quand tu rflchis",
            "ton sens de l'orientation ferait crash Google Maps",
            "tu as le charisme d'une mise  jour Windows  3h du matin",
            "mme ton rveil abandonne avant toi",
            "tu joues en mode tutoriel mais avec les aides dsactives",
        ]
        embed = build_embed("Roast amical", f"{target.mention}, {random.choice(roasts)}.")
        gif_url = await fetch_rp_gif(random.choice(["baka", "smug"]))
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wouldyourather", description="Lance un dilemme pour discuter")
    async def wouldyourather(self, interaction: discord.Interaction):
        questions = [
            "Tu prfres avoir un vocal toujours rempli ou un chat toujours actif ",
            "Tu prfres gagner tous tes duels ou tre premier du leaderboard ",
            "Tu prfres une soire film ou une game night ",
            "Tu prfres pouvoir changer ton pseudo chaque heure ou ton avatar chaque minute ",
            "Tu prfres un serveur trs chill ou trs comptitif ",
        ]
        await interaction.response.send_message(embed=build_embed("Tu prfres ", random.choice(questions)))

    @app_commands.command(name="roulette", description="Mise une somme et tente ta chance")
    async def roulette(self, interaction: discord.Interaction, amount: app_commands.Range[int, 1, 500]):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        row = self.bot.db.get_profile(interaction.guild.id, interaction.user.id)
        if int(row["wallet"]) < amount:
            return await interaction.response.send_message("Tu n'as pas assez de cash.", ephemeral=True)
        spin = random.randint(0, 99)
        if spin < 3:
            gain = amount * 5
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=gain)
            embed = build_embed("🎰 Jackpot", f"Incroyable, tu gagnes **{format_coins(gain)} ¥** !", color=discord.Color.gold())
        elif spin < 38:
            gain = amount
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=gain)
            embed = build_embed("🎰 Roulette", f"Tu doubles presque ta mise et gagnes **{format_coins(gain)} ¥**.", color=discord.Color.green())
        else:
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-amount)
            embed = build_embed("🎰 Roulette", f"Tu perds **{format_coins(amount)} ¥**.", color=discord.Color.red())
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="guessnumber", description="Devine un nombre entre 1 et 10")
    async def guessnumber(self, interaction: discord.Interaction, guess: app_commands.Range[int, 1, 10]):
        number = random.randint(1, 10)
        if guess == number and interaction.guild:
            self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=90)
            return await interaction.response.send_message(embed=build_embed("🎯 Bien joué", f"C'était bien **{number}**. Tu gagnes **90 ¥** !", color=discord.Color.green()))
        await interaction.response.send_message(embed=build_embed("🎯 Raté", f"Tu as choisi **{guess}** mais le nombre était **{number}**.", color=discord.Color.red()))

    @app_commands.command(name="ship", description="Mesure la compatibilité entre deux membres")
    async def ship(self, interaction: discord.Interaction, member1: discord.Member, member2: discord.Member):
        score = (member1.id + member2.id) % 101
        await interaction.response.send_message(embed=build_embed("💞 Ship", f"Compatibilité entre {member1.mention} et {member2.mention} : **{score}%**"))

    @app_commands.command(name="compatibility", description="Compatibilité entre toi et un membre")
    async def compatibility(self, interaction: discord.Interaction, member: discord.Member):
        score = (interaction.user.id * 3 + member.id) % 101
        await interaction.response.send_message(embed=build_embed("💫 Compatibilité", f"Toi et {member.mention} : **{score}%**"))

    @app_commands.command(name="aura", description="Évalue l'aura d'un membre")
    async def aura(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        score = (target.id * 7) % 100 + 1
        labels = "monstrueuse" if score >= 85 else ("solide" if score >= 60 else ("chaotique" if score >= 35 else "catastrophique"))
        await interaction.response.send_message(embed=build_embed("✨ Aura", f"Aura de {target.mention} : **{score}/100** • {labels}"))

    @app_commands.command(name="rate", description="Note quelque chose sur 10")
    async def rate(self, interaction: discord.Interaction, text: str):
        score = random.randint(1, 10)
        await interaction.response.send_message(embed=build_embed("📏 Note", f"**{text}** mérite **{score}/10**"))

    @app_commands.command(name="duel", description="Défie un membre en duel")
    async def duel(self, interaction: discord.Interaction, member: discord.Member):
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        winner = random.choice([interaction.user, member])
        loser = member if winner.id == interaction.user.id else interaction.user
        reward = random.randint(40, 80)
        if interaction.guild:
            self.bot.db.update_money(interaction.guild.id, winner.id, wallet_delta=reward)
            self.bot.db.update_money(interaction.guild.id, loser.id, wallet_delta=-min(reward // 2, int(self.bot.db.get_profile(interaction.guild.id, loser.id)["wallet"])))
        await interaction.response.send_message(embed=build_embed("⚔️ Duel", f"Le duel entre {interaction.user.mention} et {member.mention} est remporté par **{winner.mention}** !\nRécompense : **{format_coins(reward)} ¥**", color=discord.Color.blurple()))

    @app_commands.command(name="qotd", description="Envoie une question du jour")
    async def qotd(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("Question du jour", random.choice(QOTD_LIST)))


class Extras(commands.Cog):
    anime = app_commands.Group(name="anime", description="Commandes anime")
    clan = app_commands.Group(name="clan", description="Clans fun du serveur")
    love = app_commands.Group(name="love", description="Confessions et romance ")
    rp = app_commands.Group(name="rp", description="Actions RP et relations fun")
    eco = app_commands.Group(name="eco", description="Économie avancée")
    game = app_commands.Group(name="game", description="Mini-jeux")
    staff = app_commands.Group(name="staff", description="Outils staff fun et utiles", default_permissions=discord.Permissions(manage_guild=True))
    stats = app_commands.Group(name="stats", description="Statistiques serveur")
    image = app_commands.Group(name="image", description="Commandes image")
    util = app_commands.Group(name="util", description="Commandes utiles")
    pro = app_commands.Group(name="pro", description="Configuration premium/pro", default_permissions=discord.Permissions(manage_guild=True))
    ticket = app_commands.Group(name="ticket", description="Gestion du système de tickets")

    def __init__(self, bot: UzumakiBot):
        self.bot = bot
        self.rp_cooldowns: dict[tuple[int, int, str], datetime] = {}

    def _profile(self, guild_id: int, user_id: int) -> sqlite3.Row:
        return self.bot.db.get_profile(guild_id, user_id)

    async def _send_member_image_embed(self, interaction: discord.Interaction, title: str, member: discord.Member, description: str):
        embed = build_embed(title, description)
        embed.set_image(url=member.display_avatar.url)
        await interaction.response.send_message(embed=embed)

    async def _send_anime_visual(self, interaction: discord.Interaction, category: str, title: str, description: str):
        embed = build_embed(title, description)
        gif_url = await fetch_rp_gif(category)
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @app_commands.command(name="wanted", description="Avis de recherche style One Piece")
    async def wanted_direct(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        bounty = random.randint(10_000_000, 990_000_000)
        image = await create_wanted_poster_image(target, bounty)
        file = discord.File(image, filename="wanted.png")
        embed = build_embed("Wanted", f"{target.mention} est recherché avec une prime de **{format_coins(bounty)} ¥**.")
        embed.set_image(url="attachment://wanted.png")
        await interaction.response.send_message(embed=embed, file=file)

    @app_commands.command(name="title", description="Achète et équipe un titre affiché dans /profile")
    async def title(self, interaction: discord.Interaction, title: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        clean = title.strip()[:40]
        price = 500
        row = self._profile(interaction.guild.id, interaction.user.id)
        if int(row["wallet"]) < price:
            return await interaction.response.send_message(f"Il faut **{format_coins(price)} ¥** dans ton portefeuille.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-price)
        self.bot.db.set_setting(interaction.guild.id, f"title:{interaction.user.id}", clean)
        await interaction.response.send_message(embed=build_embed("Titre équipé", f"Ton nouveau titre : **{clean}**"), ephemeral=True)

    @app_commands.command(name="badge", description="Achète un badge affiché dans /profile")
    async def badge(self, interaction: discord.Interaction, badge: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        clean = badge.strip()[:24]
        price = 300
        row = self._profile(interaction.guild.id, interaction.user.id)
        if int(row["wallet"]) < price:
            return await interaction.response.send_message(f"Il faut **{format_coins(price)} ¥** dans ton portefeuille.", ephemeral=True)
        raw = self.bot.db.get_setting(interaction.guild.id, f"badges:{interaction.user.id}") or ""
        badges = [item for item in raw.split("|") if item]
        if clean in badges:
            return await interaction.response.send_message("Tu as déjà ce badge.", ephemeral=True)
        badges = (badges + [clean])[:8]
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-price)
        self.bot.db.set_setting(interaction.guild.id, f"badges:{interaction.user.id}", "|".join(badges))
        await interaction.response.send_message(embed=build_embed("Badge obtenu", f"Badge ajouté : **{clean}**"), ephemeral=True)

    @app_commands.command(name="quests", description="Affiche tes missions quotidiennes")
    async def quests(self, interaction: discord.Interaction):
        quests = ["Réclamer `/daily`", "Gagner un mini-jeu", "Envoyer une suggestion", "Donner une réputation", "Acheter un objet", "Participer à un event"]
        chosen = random.sample(quests, 3)
        await interaction.response.send_message(embed=build_embed("Quêtes du jour", "\n".join(f"• {quest}" for quest in chosen)), ephemeral=True)

    @app_commands.command(name="achievements", description="Affiche tes succès débloqués")
    async def achievements(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self._profile(interaction.guild.id, target.id)
        total = int(row["wallet"]) + int(row["bank"])
        kiss_total = self.bot.db.get_rp_sent_total(interaction.guild.id, target.id, "kiss")
        hug_total = self.bot.db.get_rp_sent_total(interaction.guild.id, target.id, "hug")
        slap_received_today = self.bot.db.get_rp_daily_received_total(interaction.guild.id, target.id, "slap")
        checks = [
            (int(row["level"]) >= 5, "Niveau 5 atteint"),
            (int(row["level"]) >= 15, "Prêt pour le prestige"),
            (total >= 5000, "5 000 ¥ de richesse"),
            (int(row["rep"]) >= 10, "10 points de réputation"),
            (int(row["prestige"]) >= 1, "Premier prestige"),
            (kiss_total >= 1, "Premier bisou"),
            (hug_total >= 100, "100 hugs envoyes"),
            (slap_received_today >= 10, "10 slaps recues aujourd'hui"),
        ]
        lines = [f"{'✅' if ok else '⬜'} {label}" for ok, label in checks]
        await interaction.response.send_message(embed=build_embed("Succès", "\n".join(lines)))

    @app_commands.command(name="suggest", description="Envoie une suggestion avec votes")
    async def suggest(self, interaction: discord.Interaction, suggestion: str):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Commande utilisable dans un salon serveur.", ephemeral=True)
        embed = build_embed("Suggestion", suggestion[:1500])
        embed.add_field(name="Auteur", value=interaction.user.mention, inline=True)
        await interaction.response.defer(ephemeral=True)
        msg = await interaction.channel.send(embed=embed)
        for emoji in ["👍", "👎"]:
            try:
                await msg.add_reaction(emoji)
            except discord.HTTPException:
                pass
        await interaction.followup.send("Suggestion envoyée.", ephemeral=True)

    @app_commands.command(name="rankcard", description="Affiche une carte de rang en embed")
    async def rankcard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        row = self._profile(interaction.guild.id, target.id)
        next_level = int(row["level"]) * 120
        image = await create_rank_card_image(self.bot.db, target)
        file = discord.File(image, filename="rankcard.png")
        embed = build_embed("Rank card", f"Carte de rang de {target.mention}")
        embed.set_image(url="attachment://rankcard.png")
        await interaction.response.send_message(embed=embed, file=file)

    @app_commands.command(name="profilecard", description="Affiche une carte profil plus visuelle")
    async def profilecard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande utilisable seulement en serveur.", ephemeral=True)
        target = member or interaction.user
        image = await create_profile_card_image(self.bot.db, target)
        file = discord.File(image, filename="profilecard.png")
        embed = build_embed("Profile card", f"Carte profil de {target.mention}")
        embed.set_image(url="attachment://profilecard.png")
        await interaction.response.send_message(embed=embed, file=file)

    @anime.command(name="quote", description="Citation anime aléatoire")
    async def anime_quote(self, interaction: discord.Interaction):
        quotes = ["Un vrai héros se relève même quand tout semble perdu.", "La force vient aussi des amis qu'on protège.", "Même une petite lumière traverse une grande obscurité.", "Le prochain niveau commence quand tu refuses d'abandonner."]
        await interaction.response.send_message(embed=build_embed("Anime quote", random.choice(quotes)))

    @anime.command(name="waifu", description="Profil waifu/husbando random")
    async def waifu(self, interaction: discord.Interaction):
        names = ["Aiko", "Ren", "Mika", "Sora", "Yuna", "Kael", "Hana"]
        anime_traits = ["tsundere", "protecteur", "mysterieux", "ultra chill", "chaotique", "genie discret"]
        return await self._send_anime_visual(
            interaction,
            "waifu",
            "Profil anime",
            f"Nom : **{random.choice(names)}**\nStyle : **{random.choice(anime_traits)}**\nRarete : **{random.randint(1, 5)}/5**",
        )

    @anime.command(name="neko", description="Image neko anime")
    async def neko(self, interaction: discord.Interaction):
        await self._send_anime_visual(interaction, "neko", "Neko", "Neko anime aleatoire.")

    @anime.command(name="smug", description="Reaction smug")
    async def smug(self, interaction: discord.Interaction):
        await self._send_anime_visual(interaction, "smug", "Smug", f"{interaction.user.mention} sort un sourire beaucoup trop confiant.")

    @anime.command(name="baka", description="Reaction baka")
    async def baka(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        await self._send_anime_visual(interaction, "baka", "Baka", f"{target.mention}, baka moment.")

    @anime.command(name="fight", description="Combat fun entre deux membres")
    async def animefight(self, interaction: discord.Interaction, member1: discord.Member, member2: Optional[discord.Member] = None):
        opponent = member2 or interaction.user
        winner = random.choice([member1, opponent])
        moves = ["Rasengan social", "combo éclair", "contre parfait", "attaque drama", "ulti de l'amitié"]
        await interaction.response.send_message(embed=build_embed("Anime fight", f"{member1.mention} affronte {opponent.mention}.\nTechnique finale : **{random.choice(moves)}**\nVainqueur : **{winner.mention}**"))

    @clan.command(name="create", description="Crée ton clan")
    async def clan_create(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        clean = name.strip()[:32]
        self.bot.db.set_setting(interaction.guild.id, f"clan:{interaction.user.id}", clean)
        await interaction.response.send_message(embed=build_embed("Clan créé", f"{interaction.user.mention} rejoint le clan **{clean}**."))

    @clan.command(name="join", description="Rejoins un clan")
    async def clan_join(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        clean = name.strip()[:32]
        self.bot.db.set_setting(interaction.guild.id, f"clan:{interaction.user.id}", clean)
        await interaction.response.send_message(embed=build_embed("Clan rejoint", f"{interaction.user.mention} est maintenant dans **{clean}**."))

    @clan.command(name="info", description="Infos sur ton clan")
    async def clan_info(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        clan_name = self.bot.db.get_setting(interaction.guild.id, f"clan:{interaction.user.id}")
        if not clan_name:
            return await interaction.response.send_message("Tu n'es dans aucun clan.", ephemeral=True)
        with self.bot.db._connect() as conn:
            count = conn.execute("SELECT COUNT(*) AS total FROM settings WHERE guild_id = ? AND key LIKE 'clan:%' AND value = ?", (interaction.guild.id, clan_name)).fetchone()["total"]
        await interaction.response.send_message(embed=build_embed("Clan", f"Clan : **{clan_name}**\nMembres connus : **{count}**"))

    @clan.command(name="war", description="Duel entre ton clan et un autre")
    async def clanwar(self, interaction: discord.Interaction, enemy: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        own = self.bot.db.get_setting(interaction.guild.id, f"clan:{interaction.user.id}") or "Ton clan"
        score_a, score_b = random.randint(1, 100), random.randint(1, 100)
        winner = own if score_a >= score_b else enemy
        await interaction.response.send_message(embed=build_embed("Clan war", f"**{own}** {score_a} - {score_b} **{enemy}**\nVainqueur : **{winner}**"))

    @app_commands.command(name="mood", description="Affiche ton humeur du moment avec GIF")
    async def mood(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        label, gif_category, description = random.choice(MOOD_OPTIONS)
        embed = build_embed("Mood", f"Humeur de {target.mention} : **{label}**\n{description}.")
        gif_url = random_cat_gif_url() if gif_category == "sleep" else await fetch_rp_gif(gif_category)
        if gif_url:
            embed.set_image(url=gif_url)
        await interaction.response.send_message(embed=embed)

    @love.command(name="confession", description="Confession anonyme avec boutons accepter/refuser")
    async def love_confession(self, interaction: discord.Interaction, member: discord.Member, message: Optional[str] = None):
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        text = (message or "J'avais juste envie de te le dire.").strip()[:300]
        embed = build_managed_embed(
            self.bot.db,
            interaction.guild,
            "confession",
            default_title="Confession",
            default_description="{user} fait une confession a {member}.\n\n**Message :** {message}",
            member=member,
            user="Quelqu'un",
            message=text,
        )
        # Always anonymous
        embed._author = None
        if not self.bot.db.get_setting(interaction.guild.id, "confession_embed_description"):
            embed.description = f"Quelqu'un fait une confession a {member.mention}.\n\n**Message :** {text}"
        gif_url = await fetch_rp_gif(random.choice(["wink", "handhold", "happy"]))
        if gif_url and not self.bot.db.get_setting(interaction.guild.id, "confession_embed_image_url"):
            embed.set_image(url=gif_url)
        view = LoveConfessionView(self.bot, interaction.user.id, member.id, anonymous=True)
        channel = get_confession_channel(self.bot, interaction.guild)
        if channel is None and isinstance(interaction.channel, discord.TextChannel):
            channel = interaction.channel
        if isinstance(channel, discord.TextChannel):
            # Always use webhook for anonymity
            webhooks = await channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if not webhook:
                try:
                    webhook = await channel.create_webhook(name="Anonymous Confessions")
                except discord.Forbidden:
                    # Fallback to normal send if no permission
                    await channel.send(embed=embed, view=view)
                    return await safe_interaction_send(interaction, f"Confession envoyee dans {channel.mention}.", ephemeral=True)
            await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
            return await safe_interaction_send(interaction, f"Confession envoyee dans {channel.mention}.", ephemeral=True)
        # If no channel configured, send in current channel
        try:
            webhooks = await interaction.channel.webhooks()
            webhook = discord.utils.get(webhooks, name="Anonymous Confessions")
            if not webhook:
                webhook = await interaction.channel.create_webhook(name="Anonymous Confessions")
            await webhook.send(embed=embed, view=view, username="Anonymous", avatar_url=None)
        except (discord.Forbidden, AttributeError):
            # Fallback
            await safe_interaction_send(interaction, embed=embed, view=view)

    async def _rp_action(self, interaction: discord.Interaction, title: str, member: Optional[discord.Member], template: str, gif_category: str = ""):
        target = member or interaction.user
        action = (gif_category or title).lower()
        guild_id = interaction.guild.id if interaction.guild else 0
        cooldown_key = (guild_id, interaction.user.id, action)
        now = utc_now()
        next_time = self.rp_cooldowns.get(cooldown_key)
        if next_time and now < next_time:
            seconds = max(1, int((next_time - now).total_seconds()))
            return await safe_interaction_send(interaction, f"Doucement, attends encore **{seconds}s**.", ephemeral=True)

        self.rp_cooldowns[cooldown_key] = now + timedelta(seconds=_COOLDOWN_SECONDS)
        chosen_template = random.choice(_ACTION_MESSAGES.get(action, [template]))
        embed = build_embed(title, chosen_template.format(user=interaction.user.mention, target=target.mention))
        if interaction.guild:
            count = self.bot.db.record_rp_action(interaction.guild.id, interaction.user.id, target.id, action)
            embed.add_field(name="Compteur", value=f"{rp_action_label(action)} entre vous : **{count}**", inline=False)
            title_unlocked = rp_title_for(self.bot.db, interaction.guild.id, interaction.user.id)
            if title_unlocked:
                embed.add_field(name="Titre ", value=title_unlocked, inline=True)

        gif_url = random_cat_gif_url() if action == "sleep" else await fetch_rp_gif(action)
        if gif_url:
            embed.set_image(url=gif_url)
        view = None
        if member is not None and target.id != interaction.user.id:
            view = ActionView(self.bot, action, interaction.user.id, target.id)
        await safe_interaction_send(interaction, embed=embed, view=view)

    @rp.command(name="hug", description="Faire un câlin à un membre")
    async def hug(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Hug", member, "{user} fait un câlin à {target}.")

    @rp.command(name="kiss", description="Bisou")
    async def kiss(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Kiss", member, "{user} envoie un bisou à {target}.")

    @rp.command(name="pat", description="Pat pat")
    async def pat(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Pat", member, "{user} tapote gentiment la tête de {target}.")

    @rp.command(name="slap", description="Gifle fun")
    async def slap(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Slap", member, "{user} met une claque à {target}.")

    @rp.command(name="cry", description="Réaction triste")
    async def cry(self, interaction: discord.Interaction):
        await self._rp_action(interaction, "Cry", None, "{user} pleure en silence.")

    @rp.command(name="bite", description="Mordillage ")
    async def bite(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Bite", member, "{user} mordille {target}.")

    @rp.command(name="poke", description="Poke un membre")
    async def poke(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Poke", member, "{user} poke {target}.")

    @rp.command(name="cuddle", description="Gros calin ")
    async def cuddle(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Cuddle", member, "{user} fait un gros calin a {target}.")

    @rp.command(name="highfive", description="High five avec un membre")
    async def highfive(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Highfive", member, "{user} tape dans la main de {target}.")

    @rp.command(name="bonk", description="Bonk cartoon")
    async def bonk(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Bonk", member, "{user} bonk {target}.")

    @rp.command(name="wave", description="Faire coucou")
    async def wave(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self._rp_action(interaction, "Wave", member, "{user} fait coucou a {target}.")

    @rp.command(name="blush", description="Reaction timide")
    async def blush(self, interaction: discord.Interaction):
        await self._rp_action(interaction, "Blush", None, "{user} rougit d'un coup.")

    @rp.command(name="dance", description="Danse")
    async def dance(self, interaction: discord.Interaction):
        await self._rp_action(interaction, "Dance", None, "{user} lance une danse impeccable.")

    @rp.command(name="sleep", description="Mode dodo")
    async def sleep(self, interaction: discord.Interaction):
        await self._rp_action(interaction, "Sleep", None, "{user} va dormir.")

    @rp.command(name="duelgif", description="Duel avec GIF anime")
    async def rp_duel(self, interaction: discord.Interaction, member: discord.Member):
        if member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        winner = random.choice([interaction.user, member])
        moves = ["kick", "shoot", "angry", "bonk"]
        move = random.choice(moves)
        embed = build_embed(
            "Duel ",
            f"{interaction.user.mention} defie {member.mention}.\nTechnique finale : **{rp_action_label(move)}**\nVainqueur : **{winner.mention}**",
        )
        gif_url = await fetch_rp_gif(move)
        if gif_url:
            embed.set_image(url=gif_url)
        if interaction.guild:
            self.bot.db.record_rp_action(interaction.guild.id, interaction.user.id, member.id, "duel")
        await interaction.response.send_message(embed=embed)

    @rp.command(name="marry", description="Mariage fun avec un membre")
    async def marry(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        if self.bot.db.get_setting(interaction.guild.id, f"marry:{interaction.user.id}"):
            return await interaction.response.send_message("Tu es déjà marié dans le bot.", ephemeral=True)
        if self.bot.db.get_setting(interaction.guild.id, f"marry:{member.id}"):
            return await interaction.response.send_message("Ce membre est déjà marié dans le bot.", ephemeral=True)
        now = utc_now().isoformat()
        self.bot.db.set_setting(interaction.guild.id, f"marry:{interaction.user.id}", str(member.id))
        self.bot.db.set_setting(interaction.guild.id, f"marry:{member.id}", str(interaction.user.id))
        self.bot.db.set_setting(interaction.guild.id, f"marry_since:{interaction.user.id}", now)
        self.bot.db.set_setting(interaction.guild.id, f"marry_since:{member.id}", now)
        embed = build_embed("Mariage", f"{interaction.user.mention} et {member.mention} sont maintenant mariés version fun.")
        embed.add_field(name="Depuis", value=discord.utils.format_dt(datetime.fromisoformat(now), style="F"), inline=False)
        await interaction.response.send_message(embed=embed)

    @rp.command(name="divorce", description="Divorce")
    async def divorce(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        partner = self.bot.db.get_setting(interaction.guild.id, f"marry:{interaction.user.id}")
        self.bot.db.set_setting(interaction.guild.id, f"marry:{interaction.user.id}", "")
        self.bot.db.set_setting(interaction.guild.id, f"marry_since:{interaction.user.id}", "")
        if partner and partner.isdigit():
            self.bot.db.set_setting(interaction.guild.id, f"marry:{partner}", "")
            self.bot.db.set_setting(interaction.guild.id, f"marry_since:{partner}", "")
        await interaction.response.send_message(embed=build_embed("Divorce", "Le mariage fun a été annulé."), ephemeral=True)

    @rp.command(name="adopt", description="Adopter un membre")
    async def adopt(self, interaction: discord.Interaction, member: discord.Member):
        if not interaction.guild or member.bot or member.id == interaction.user.id:
            return await interaction.response.send_message("Choisis un autre membre humain.", ephemeral=True)
        if self.bot.db.get_setting(interaction.guild.id, f"adopt:{member.id}"):
            return await interaction.response.send_message("Ce membre a déjà un parent .", ephemeral=True)
        now = utc_now().isoformat()
        self.bot.db.set_setting(interaction.guild.id, f"adopt:{member.id}", str(interaction.user.id))
        self.bot.db.set_setting(interaction.guild.id, f"adopted_at:{member.id}", now)
        embed = build_embed("Adoption ", f"{interaction.user.mention} adopte {member.mention} dans le lore du serveur.")
        embed.add_field(name="Depuis", value=discord.utils.format_dt(datetime.fromisoformat(now), style="F"), inline=False)
        await interaction.response.send_message(embed=embed)

    @eco.command(name="scratchcard", description="Ticket à gratter")
    async def scratchcard(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        cost = 50
        row = self._profile(interaction.guild.id, interaction.user.id)
        if int(row["wallet"]) < cost:
            return await interaction.response.send_message("Il faut 50 ¥.", ephemeral=True)
        prize = random.choice([0, 0, 25, 75, 150, 500])
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=prize - cost)
        await interaction.response.send_message(embed=build_embed("Ticket à gratter", f"Coût : **{cost} ¥**\nGain : **{prize} ¥**"))

    @eco.command(name="market", description="Marché des objets")
    async def market(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        entries = get_shop_entries(self.bot.db, interaction.guild.id)[:10]
        lines = [f"• `{e['key']}` — **{e['title']}** ({format_coins(int(e['price']))} ¥)" for e in entries]
        await interaction.response.send_message(embed=build_embed("Market", "\n".join(lines) if lines else "Marché vide."), ephemeral=True)

    @eco.command(name="trade", description="Propose un échange entre deux membres")
    async def trade(self, interaction: discord.Interaction, member: discord.Member, offer: str):
        await interaction.response.send_message(embed=build_embed("Trade", f"{interaction.user.mention} propose à {member.mention} :\n**{offer[:800]}**"))

    @eco.command(name="auction", description="Crée une enchère fun")
    async def auction(self, interaction: discord.Interaction, item: str, start_price: app_commands.Range[int, 1, 1000000]):
        await interaction.response.send_message(embed=build_embed("Enchère", f"Objet : **{item[:80]}**\nPrix de départ : **{format_coins(int(start_price))} ¥**\nRépondez dans le salon pour enchérir."))

    @eco.command(name="business", description="Achète une entreprise fun")
    async def business(self, interaction: discord.Interaction, name: str):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        cost = 2500
        row = self._profile(interaction.guild.id, interaction.user.id)
        if int(row["wallet"]) < cost:
            return await interaction.response.send_message(f"Il faut **{format_coins(cost)} ¥**.", ephemeral=True)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=-cost)
        self.bot.db.set_setting(interaction.guild.id, f"business:{interaction.user.id}", name[:40])
        await interaction.response.send_message(embed=build_embed("Business acheté", f"Entreprise : **{name[:40]}**\nUtilise `/eco rent` pour récupérer les revenus."))

    @eco.command(name="rent", description="Récupère les revenus de ton business")
    async def rent(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        business = self.bot.db.get_setting(interaction.guild.id, f"business:{interaction.user.id}")
        if not business:
            return await interaction.response.send_message("Tu n'as pas encore de business. Utilise `/eco business`.", ephemeral=True)
        last = self.bot.db.get_setting(interaction.guild.id, f"rent:{interaction.user.id}")
        next_time = cooldown_remaining(last, timedelta(hours=12)) if last else None
        if next_time:
            return await interaction.response.send_message(f"Reviens <t:{int(next_time.timestamp())}:R>.", ephemeral=True)
        reward = random.randint(160, 420)
        self.bot.db.update_money(interaction.guild.id, interaction.user.id, wallet_delta=reward)
        self.bot.db.set_setting(interaction.guild.id, f"rent:{interaction.user.id}", utc_now().isoformat())
        await interaction.response.send_message(embed=build_embed("Revenus business", f"**{business}** rapporte **{format_coins(reward)} ¥**."))

    @eco.command(name="tax", description="Taxe fun sur les plus riches")
    @staff_only()
    async def tax(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        rows = self.bot.db.get_top_wallet(interaction.guild.id, 3)
        lines = []
        for row in rows:
            user_id = int(row["user_id"])
            total = int(row["wallet"]) + int(row["bank"])
            tax_amount = min(200, max(0, total // 100))
            self.bot.db.update_money(interaction.guild.id, user_id, wallet_delta=-tax_amount)
            lines.append(f"<@{user_id}> taxé de **{format_coins(tax_amount)} ¥**")
        await interaction.response.send_message(embed=build_embed("Taxe fun", "\n".join(lines) if lines else "Aucun riche trouvé."))

    @eco.command(name="richrole", description="Donne un rôle au membre le plus riche")
    @staff_only()
    async def richrole(self, interaction: discord.Interaction, role: discord.Role):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        rows = self.bot.db.get_top_wallet(interaction.guild.id, 1)
        if not rows:
            return await interaction.response.send_message("Aucun classement.", ephemeral=True)
        member = interaction.guild.get_member(int(rows[0]["user_id"]))
        if not member:
            return await interaction.response.send_message("Membre introuvable.", ephemeral=True)
        await member.add_roles(role, reason="Rich role")
        await interaction.response.send_message(embed=build_embed("Rich role", f"{role.mention} donné à {member.mention}."))

    @game.command(name="tictactoe", description="Morpion contre un membre")
    async def tictactoe(self, interaction: discord.Interaction, member: discord.Member):
        winner = random.choice([interaction.user, member, None])
        result = "Égalité." if winner is None else f"Vainqueur : **{winner.mention}**"
        await interaction.response.send_message(embed=build_embed("Tic Tac Toe", result))

    @game.command(name="connect4", description="Puissance 4 fun")
    async def connect4(self, interaction: discord.Interaction, member: discord.Member):
        winner = random.choice([interaction.user, member])
        await interaction.response.send_message(embed=build_embed("Connect 4", f"{interaction.user.mention} vs {member.mention}\nVainqueur : **{winner.mention}**"))

    @game.command(name="hangman", description="Pendu rapide")
    async def hangman(self, interaction: discord.Interaction):
        word = random.choice(["uzumaki", "sakura", "discord", "anime", "ramen", "prestige"])
        masked = word[0] + "_" * (len(word) - 2) + word[-1]
        await interaction.response.send_message(embed=build_embed("Pendu", f"Mot : **{masked}**\nRéponse : ||{word}||"))

    @game.command(name="memory", description="Jeu de mémoire")
    async def memory(self, interaction: discord.Interaction):
        seq = " ".join(str(random.randint(1, 9)) for _ in range(6))
        await interaction.response.send_message(embed=build_embed("Memory", f"Mémorise cette suite : **{seq}**"), ephemeral=True)

    @game.command(name="typingrace", description="Course de frappe")
    async def typingrace(self, interaction: discord.Interaction):
        phrase = random.choice(["Uzumaki reste imbattable", "Le serveur est en feu", "Les ninjas aiment le ramen"])
        await interaction.response.send_message(embed=build_embed("Typing race", f"Recopie vite :\n```{phrase}```"))

    @game.command(name="trivia", description="Quiz rapide")
    async def trivia(self, interaction: discord.Interaction):
        q, a = random.choice([("Quelle plateforme utilise les serveurs et salons ", "Discord"), ("Combien de faces a un dé classique ", "6")])
        await interaction.response.send_message(embed=build_embed("Trivia", f"{q}\nRéponse : ||{a}||"))

    @game.command(name="animequiz", description="Quiz anime")
    async def animequiz(self, interaction: discord.Interaction):
        q, a = random.choice([("Qui veut devenir Hokage ", "Naruto"), ("Quel plat adore Naruto ", "Ramen")])
        await interaction.response.send_message(embed=build_embed("Anime quiz", f"{q}\nRéponse : ||{a}||"))

    @game.command(name="mathquiz", description="Calcul rapide")
    async def mathquiz(self, interaction: discord.Interaction):
        a, b = random.randint(3, 20), random.randint(3, 20)
        await interaction.response.send_message(embed=build_embed("Math quiz", f"Combien fait **{a} × {b}** \nRéponse : ||{a*b}||"))

    @game.command(name="wordle", description="Mini Wordle")
    async def wordle(self, interaction: discord.Interaction):
        word = random.choice(["salon", "badge", "anime", "daily"])
        await interaction.response.send_message(embed=build_embed("Wordle", f"Mot de 5 lettres : `{word[0]}____`\nRéponse : ||{word}||"))

    @game.command(name="game2048", description="Mini 2048 simplifié")
    async def game_2048(self, interaction: discord.Interaction):
        board = [[0, 0, 0, 0] for _ in range(4)]
        for _ in range(2):
            board[random.randint(0, 3)][random.randint(0, 3)] = 2
        lines = [" ".join("." if cell == 0 else str(cell) for cell in row) for row in board]
        await interaction.response.send_message(embed=build_embed("2048", "```\n" + "\n".join(lines) + "\n```"))

    @staff.command(name="warnfun", description="Avertissement fake drôle")
    @staff_only()
    async def warnfun(self, interaction: discord.Interaction, member: discord.Member, reason: str = "trop de style"):
        await interaction.response.send_message(embed=build_embed("Warn fun", f"{member.mention} reçoit un avertissement fake pour : **{reason}**"))

    @staff.command(name="jail", description="Met quelqu'un en prison ")
    @staff_only()
    async def jail(self, interaction: discord.Interaction, member: discord.Member):
        self.bot.db.set_setting(interaction.guild.id, f"jail:{member.id}", "1")
        await interaction.response.send_message(embed=build_embed("Jail ", f"{member.mention} est en prison ."))

    @staff.command(name="unjail", description="Retire la prison ")
    @staff_only()
    async def unjail(self, interaction: discord.Interaction, member: discord.Member):
        self.bot.db.set_setting(interaction.guild.id, f"jail:{member.id}", "0")
        await interaction.response.send_message(embed=build_embed("Unjail ", f"{member.mention} est libre."))

    @staff.command(name="slowmode", description="Règle le slowmode")
    @staff_only()
    async def slowmode(self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600], channel: Optional[discord.TextChannel] = None):
        target = channel or interaction.channel
        if not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message("Salon texte requis.", ephemeral=True)
        await target.edit(slowmode_delay=int(seconds), reason=f"Slowmode par {interaction.user}")
        await interaction.response.send_message(f"Slowmode de {target.mention} réglé à **{seconds}s**.", ephemeral=True)

    @staff.command(name="lockchat", description="Verrouille un salon")
    @staff_only()
    async def lockchat(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target = channel or interaction.channel
        if not interaction.guild or not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message("Salon texte requis.", ephemeral=True)
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Lockchat")
        await interaction.response.send_message(f"{target.mention} verrouillé.", ephemeral=True)

    @staff.command(name="unlockchat", description="Déverrouille un salon")
    @staff_only()
    async def unlockchat(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
        target = channel or interaction.channel
        if not interaction.guild or not isinstance(target, discord.TextChannel):
            return await interaction.response.send_message("Salon texte requis.", ephemeral=True)
        overwrite = target.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await target.set_permissions(interaction.guild.default_role, overwrite=overwrite, reason="Unlockchat")
        await interaction.response.send_message(f"{target.mention} déverrouillé.", ephemeral=True)

    @staff.command(name="nickname", description="Change le surnom d'un membre")
    @staff_only()
    async def nickname(self, interaction: discord.Interaction, member: discord.Member, nickname: str):
        await member.edit(nick=nickname[:32], reason=f"Nickname par {interaction.user}")
        await interaction.response.send_message(f"Surnom changé pour {member.mention}.", ephemeral=True)

    @staff.command(name="announce", description="Annonce embed blanche")
    @staff_only()
    async def announce(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, message: str):
        await channel.send(embed=build_embed(title, message))
        await interaction.response.send_message(f"Annonce envoyée dans {channel.mention}.", ephemeral=True)

    @staff.command(name="embedbuilder", description="Créer un embed personnalisé")
    @staff_only()
    async def embedbuilder(self, interaction: discord.Interaction, channel: discord.TextChannel, title: str, description: str, image_url: Optional[str] = None):
        embed = build_embed(title, description)
        if image_url:
            embed.set_image(url=image_url)
        await channel.send(embed=embed)
        await interaction.response.send_message("Embed envoyé.", ephemeral=True)

    @stats.command(name="server", description="Stats détaillées serveur")
    async def serverstats(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        embed = build_embed("Server stats", guild.description or "Aucune description.")
        embed.add_field(name="Membres", value=str(guild.member_count), inline=True)
        embed.add_field(name="Salons", value=str(len(guild.channels)), inline=True)
        embed.add_field(name="Rôles", value=str(len(guild.roles)), inline=True)
        await interaction.response.send_message(embed=embed)

    @stats.command(name="membercount", description="Nombre membres/humains/bots")
    async def membercount(self, interaction: discord.Interaction):
        guild = interaction.guild
        if not guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        humans = len([m for m in guild.members if not m.bot])
        bots = len([m for m in guild.members if m.bot])
        await interaction.response.send_message(embed=build_embed("Member count", f"Total : **{guild.member_count}**\nHumains : **{humans}**\nBots : **{bots}**"))

    @stats.command(name="activity", description="Top membres actifs selon niveaux")
    async def activity(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        rows = self.bot.db.get_top_levels(interaction.guild.id, 10)
        lines = [f"`#{i}` <@{row['user_id']}> — niveau **{int(row['level'])}**" for i, row in enumerate(rows, 1)]
        await interaction.response.send_message(embed=build_embed("Activité", "\n".join(lines) if lines else "Aucune donnée."))

    @stats.command(name="messagestats", description="Messages du jour/semaine")
    async def messagestats(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("Message stats", "Le bot utilise actuellement l'XP comme indicateur d'activité. Un tracking précis peut être ajouté ensuite."), ephemeral=True)

    @stats.command(name="voicetime", description="Temps vocal")
    async def voicetime(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        await interaction.response.send_message(embed=build_embed("Voice time", f"Tracking vocal détaillé non activé pour {target.mention}."), ephemeral=True)

    @stats.command(name="topvoice", description="Classement vocal")
    async def topvoice(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=build_embed("Top voice", "Tracking vocal à brancher dans une prochaine étape."), ephemeral=True)

    @stats.command(name="topchat", description="Classement messages")
    async def topchat(self, interaction: discord.Interaction):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        rows = self.bot.db.get_top_levels(interaction.guild.id, 10)
        lines = [f"`#{i}` <@{row['user_id']}> — niveau **{int(row['level'])}**" for i, row in enumerate(rows, 1)]
        await interaction.response.send_message(embed=build_embed("Top chat", "\n".join(lines) if lines else "Aucune donnée."))

    @image.command(name="wanted", description="Avis de recherche")
    async def wanted(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        bounty = random.randint(10_000_000, 990_000_000)
        image = await create_wanted_poster_image(target, bounty)
        file = discord.File(image, filename="wanted.png")
        embed = build_embed("Wanted", f"{target.mention} est recherché avec une prime de **{format_coins(bounty)} ¥**.")
        embed.set_image(url="attachment://wanted.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="jailcard", description="Carte prison")
    async def jailcard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        image = await create_member_card(target, "JAIL CARD", "Dossier  temporaire", [("Statut", "en cellule"), ("Caution", f"{random.randint(50, 300)} ¥")])
        file = discord.File(image, filename="jailcard.png")
        embed = build_embed("Jail card", f"{target.mention} derrière les barreaux .")
        embed.set_image(url="attachment://jailcard.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="rip", description="Carte RIP")
    async def rip(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        image = await create_member_card(target, "RIP", "Moment dramatique mais 100% fun", [("Cause", random.choice(["lag", "duel", "roulette"])), ("Retour", "bientôt")])
        file = discord.File(image, filename="rip.png")
        embed = build_embed("RIP", f"Moment dramatique pour {target.mention}.")
        embed.set_image(url="attachment://rip.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="beautiful", description="Meme beautiful")
    async def beautiful(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        image = await create_member_card(target, "BEAUTIFUL", "Une vraie œuvre du serveur", [("Style", "10/10"), ("Aura", str((target.id * 7) % 100 + 1))])
        file = discord.File(image, filename="beautiful.png")
        embed = build_embed("Beautiful", f"Regardez cette œuvre : {target.mention}.")
        embed.set_image(url="attachment://beautiful.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="triggered", description="Effet triggered")
    async def triggered(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        image = await create_member_card(target, "TRIGGERED", "Niveau d'énergie instable", [("Intensité", f"{random.randint(60, 100)}%"), ("Calme", "introuvable")])
        file = discord.File(image, filename="triggered.png")
        embed = build_embed("Triggered", f"{target.mention} est officiellement triggered.")
        embed.set_image(url="attachment://triggered.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="rankcard", description="Carte de niveau")
    async def image_rankcard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        await self.rankcard(interaction, member)

    @image.command(name="welcomecard", description="Aperçu welcome card")
    async def welcomecard(self, interaction: discord.Interaction, member: Optional[discord.Member] = None):
        target = member or interaction.user
        image = await create_member_card(target, "WELCOME", f"Bienvenue sur {interaction.guild.name if interaction.guild else 'le serveur'}", [("Membre", target.display_name), ("Vibe", "premium")])
        file = discord.File(image, filename="welcomecard.png")
        embed = build_embed("Welcome card", f"Bienvenue {target.mention} sur **{interaction.guild.name if interaction.guild else 'le serveur'}**.")
        embed.set_image(url="attachment://welcomecard.png")
        await interaction.response.send_message(embed=embed, file=file)

    @image.command(name="shipcard", description="Image compatibilité")
    async def shipcard(self, interaction: discord.Interaction, member1: discord.Member, member2: discord.Member):
        score = (member1.id + member2.id) % 101
        image = await create_ship_card_image(member1, member2, score)
        file = discord.File(image, filename="shipcard.png")
        embed = build_embed("Ship card", f"{member1.mention} + {member2.mention} = **{score}%**")
        embed.set_image(url="attachment://shipcard.png")
        await interaction.response.send_message(embed=embed, file=file)

    @util.command(name="remindme", description="Rappel personnel")
    async def remindme(self, interaction: discord.Interaction, minutes: app_commands.Range[int, 1, 1440], message: str):
        await interaction.response.send_message(f"Rappel programmé dans **{minutes} min**.", ephemeral=True)
        async def reminder():
            await asyncio.sleep(int(minutes) * 60)
            try:
                await interaction.user.send(f"Rappel : {message}")
            except discord.HTTPException:
                pass
        asyncio.create_task(reminder())

    @util.command(name="todo", description="Liste de tâches perso")
    async def todo(self, interaction: discord.Interaction, action: str, text: Optional[str] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        key = f"todo:{interaction.user.id}"
        items = [x for x in (self.bot.db.get_setting(interaction.guild.id, key) or "").split("|") if x]
        if action.lower() == "add" and text:
            items.append(text[:120])
            self.bot.db.set_setting(interaction.guild.id, key, "|".join(items[-20:]))
        elif action.lower() == "clear":
            items = []
            self.bot.db.set_setting(interaction.guild.id, key, "")
        await interaction.response.send_message(embed=build_embed("Todo", "\n".join(f"• {x}" for x in items) if items else "Aucune tâche."), ephemeral=True)

    @util.command(name="note", description="Sauvegarder une note")
    async def note(self, interaction: discord.Interaction, text: Optional[str] = None):
        if not interaction.guild:
            return await interaction.response.send_message("Commande serveur uniquement.", ephemeral=True)
        key = f"note:{interaction.user.id}"
        if text:
            self.bot.db.set_setting(interaction.guild.id, key, text[:500])
            return await interaction.response.send_message("Note sauvegardée.", ephemeral=True)
        await interaction.response.send_message(embed=build_embed("Note", self.bot.db.get_setting(interaction.guild.id, key) or "Aucune note."), ephemeral=True)

    @util.command(name="timezone", description="Afficher l'heure avec un offset UTC")
    async def timezone(self, interaction: discord.Interaction, utc_offset: str = "+01:00"):
        sign = -1 if utc_offset.startswith("-") else 1
        raw = utc_offset.strip().lstrip("+-")
        try:
            hours, minutes = [int(x) for x in raw.split(":", 1)]
        except Exception:
            return await interaction.response.send_message("Format attendu : `+01:00` ou `-05:00`.", ephemeral=True)
        now = utc_now() + timedelta(hours=sign * hours, minutes=sign * minutes)
        await interaction.response.send_message(embed=build_embed("Timezone", f"UTC{utc_offset} : **{now.strftime('%H:%M')}**"), ephemeral=True)

    @util.command(name="translate", description="Traduction fun simplifiée")
    async def translate(self, interaction: discord.Interaction, text: str, target_lang: str = "en"):
        await interaction.response.send_message(embed=build_embed("Translate", f"Texte : **{text[:300]}**\nLangue cible : **{target_lang}**\nBranche une API traduction pour une vraie traduction automatique."), ephemeral=True)

    @util.command(name="weather", description="Météo fun")
    async def weather(self, interaction: discord.Interaction, location: str):
        weather = random.choice(["grand soleil", "pluie dramatique", "vent de motivation", "nuages chill", "tempête d'énergie"])
        await interaction.response.send_message(embed=build_embed("Météo fun", f"À **{location}**, la météo  annonce : **{weather}**."))

    @util.command(name="urban", description="Définition drôle")
    async def urban(self, interaction: discord.Interaction, term: str):
        definitions = ["concept très sérieux, sauf sur Discord", "mot utilisé quand le salon part trop vite", "énergie difficile à expliquer mais facile à reconnaître"]
        await interaction.response.send_message(embed=build_embed("Urban", f"**{term}** : {random.choice(definitions)}."))

    @util.command(name="shorten", description="Raccourcir visuellement un lien")
    async def shorten(self, interaction: discord.Interaction, url: str):
        compact = url if len(url) <= 48 else url[:45] + "..."
        await interaction.response.send_message(embed=build_embed("Lien compact", f"[{compact}]({url})"), ephemeral=True)

    @pro.command(name="configpanel", description="Panneau config")
    @staff_only()
    async def configpanel(self, interaction: discord.Interaction):
        embed = build_config_panel_embed(self.bot, interaction.guild)
        await interaction.response.send_message(embed=embed, view=ConfigPanelView(self.bot), ephemeral=True)

    @pro.command(name="setcurrency", description="Change le symbole de monnaie stocké")
    @staff_only()
    async def setcurrency(self, interaction: discord.Interaction, symbol: str):
        self.bot.db.set_setting(interaction.guild.id, "currency", symbol[:6])
        await interaction.response.send_message(f"Symbole stocké : **{symbol[:6]}**. Un refactor peut ensuite l'appliquer partout.", ephemeral=True)

    @pro.command(name="setbrand", description="Change le nom brand stocké")
    @staff_only()
    async def setbrand(self, interaction: discord.Interaction, name: str):
        self.bot.db.set_setting(interaction.guild.id, "brand_name", name[:40])
        await interaction.response.send_message(f"Brand stockée : **{name[:40]}**. Redémarre/refactor pour l'appliquer partout.", ephemeral=True)

    @pro.command(name="setwelcomemessage", description="Personnalise le message de bienvenue")
    @staff_only()
    async def setwelcomemessage(self, interaction: discord.Interaction, message: str):
        self.bot.db.set_setting(interaction.guild.id, "welcome_message", message[:1000])
        await interaction.response.send_message("Message de bienvenue sauvegardé. Variables : `{member}`, `{server}`.", ephemeral=True)

    @pro.command(name="setwelcomechannel", description="Definit le salon de bienvenue")
    @staff_only()
    async def setwelcomechannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "welcome_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon welcome configure sur {channel.mention}.", ephemeral=True)

    @pro.command(name="setwelcomeembed", description="Configure l'embed de bienvenue")
    @staff_only()
    async def setwelcomeembed(self, interaction: discord.Interaction, title: str, description: str, image_url: Optional[str] = None):
        save_managed_embed_settings(self.bot.db, interaction.guild.id, "welcome", title, description, image_url)
        await interaction.response.send_message("Embed welcome sauvegarde. Variables : `{member}`, `{member_name}`, `{server}`, `{count}`.", ephemeral=True)

    @pro.command(name="setboostchannel", description="Definit le salon des boosts")
    @staff_only()
    async def setboostchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "boost_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon boosts configure sur {channel.mention}.", ephemeral=True)

    @pro.command(name="setboostembed", description="Configure l'embed de boost serveur")
    @staff_only()
    async def setboostembed(self, interaction: discord.Interaction, title: str, description: str, image_url: Optional[str] = None):
        save_managed_embed_settings(self.bot.db, interaction.guild.id, "boost", title, description, image_url)
        await interaction.response.send_message("Embed boost sauvegarde. Variables : `{member}`, `{member_name}`, `{server}`, `{boosts}`.", ephemeral=True)

    @pro.command(name="setconfessionchannel", description="Definit le salon des confessions")
    @staff_only()
    async def setconfessionchannel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        self.bot.db.set_setting(interaction.guild.id, "confession_channel_id", str(channel.id))
        await interaction.response.send_message(f"Salon confessions configure sur {channel.mention}.", ephemeral=True)

    @pro.command(name="setconfessionembed", description="Configure l'embed des confessions")
    @staff_only()
    async def setconfessionembed(self, interaction: discord.Interaction, title: str, description: str, image_url: Optional[str] = None):
        save_managed_embed_settings(self.bot.db, interaction.guild.id, "confession", title, description, image_url)
        await interaction.response.send_message("Embed confession sauvegarde. Variables : `{user}`, `{member}`, `{member_name}`, `{message}`, `{server}`.", ephemeral=True)

    @pro.command(name="previewembed", description="Previsualise un embed gere par le bot")
    @staff_only()
    @app_commands.choices(kind=[
        app_commands.Choice(name="welcome", value="welcome"),
        app_commands.Choice(name="boost", value="boost"),
        app_commands.Choice(name="confession", value="confession"),
    ])
    async def previewembed(self, interaction: discord.Interaction, kind: app_commands.Choice[str], member: Optional[discord.Member] = None):
        target = member or interaction.user
        if kind.value == "boost":
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "boost",
                default_title="Nouveau boost",
                default_description="{member} vient de booster **{server}** !\nBoosts serveur : **{boosts}**.",
                member=target,
            )
        elif kind.value == "confession":
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "confession",
                default_title="Confession",
                default_description="{user} fait une confession a {member}.\n\n**Message :** {message}",
                member=target,
                user=interaction.user,
                message="Message de test.",
            )
        else:
            fallback = self.bot.db.get_setting(interaction.guild.id, "welcome_message") or "Bienvenue {member} sur **{server}**."
            embed = build_managed_embed(
                self.bot.db,
                interaction.guild,
                "welcome",
                default_title="Bienvenue sur {server}",
                default_description=fallback,
                member=target,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @pro.command(name="clearembed", description="Reset un embed gere par le bot")
    @staff_only()
    @app_commands.choices(kind=[
        app_commands.Choice(name="welcome", value="welcome"),
        app_commands.Choice(name="boost", value="boost"),
        app_commands.Choice(name="confession", value="confession"),
    ])
    async def clearembed(self, interaction: discord.Interaction, kind: app_commands.Choice[str]):
        for suffix in ["title", "description", "image_url", "thumbnail_url"]:
            self.bot.db.set_setting(interaction.guild.id, f"{kind.value}_embed_{suffix}", "")
        await interaction.response.send_message(f"Embed **{kind.value}** reset.", ephemeral=True)

    @pro.command(name="setlevelreward", description="Donne un rôle à un niveau")
    @staff_only()
    async def setlevelreward(self, interaction: discord.Interaction, level: app_commands.Range[int, 1, 100], role: discord.Role):
        self.bot.db.set_setting(interaction.guild.id, f"level_reward:{int(level)}", str(role.id))
        await interaction.response.send_message(f"Au niveau **{level}**, le rôle {role.mention} sera donné.", ephemeral=True)

    @pro.command(name="autorole", description="Rôle auto à l'arrivée")
    @staff_only()
    async def autorole(self, interaction: discord.Interaction, role: discord.Role):
        self.bot.db.set_setting(interaction.guild.id, "autorole_id", str(role.id))
        await interaction.response.send_message(f"Autorole configuré sur {role.mention}.", ephemeral=True)

    @pro.command(name="reactionrole", description="Crée un message reaction role simple")
    @staff_only()
    async def reactionrole(self, interaction: discord.Interaction, channel: discord.TextChannel, role: discord.Role, label: str = "Prendre le rôle"):
        embed = build_embed("Reaction role", f"Réagis avec ✅ pour demander le rôle {role.mention}. Attribution automatique à brancher avec une vue persistante dédiée.")
        msg = await channel.send(embed=embed)
        await msg.add_reaction("✅")
        await interaction.response.send_message("Message reaction role envoyé.", ephemeral=True)

    @pro.command(name="ticketpanel", description="Crée un panel ticket simple")
    @staff_only()
    async def ticketpanel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        embed = build_embed("Tickets", "Réagis dans ce salon ou contacte le staff pour ouvrir un ticket. Une vue bouton persistante peut être ajoutée ensuite.")
        await channel.send(embed=embed)
        await interaction.response.send_message("Panel ticket envoyé.", ephemeral=True)

    @ticket.command(name="setcategory", description="Définit la catégorie où les tickets seront créés")
    @staff_only()
    async def setticketcategory(self, interaction: discord.Interaction, category: discord.CategoryChannel):
        self.bot.db.set_setting(interaction.guild.id, "ticket_category_id", str(category.id))
        await interaction.response.send_message(f"Catégorie ticket définie sur {category.name}.", ephemeral=True)

    @ticket.command(name="setstaffrole", description="Définit le rôle du staff pour les tickets")
    @staff_only()
    async def setticketstaff(self, interaction: discord.Interaction, role: discord.Role):
        self.bot.db.set_setting(interaction.guild.id, "ticket_staff_role_id", str(role.id))
        await interaction.response.send_message(f"Rôle staff ticket défini sur {role.mention}.", ephemeral=True)

    @ticket.command(name="settings", description="Affiche la configuration du système de tickets")
    @staff_only()
    async def tickets_settings(self, interaction: discord.Interaction):
        category_id = self.bot.db.get_setting(interaction.guild.id, "ticket_category_id")
        staff_role_id = self.bot.db.get_setting(interaction.guild.id, "ticket_staff_role_id")
        ticket_category = None
        staff_role = None
        if category_id and category_id.isdigit():
            ticket_category = interaction.guild.get_channel(int(category_id))
        if staff_role_id and staff_role_id.isdigit():
            staff_role = interaction.guild.get_role(int(staff_role_id))

        open_ticket = self.bot.db.get_open_ticket_for_user(interaction.guild.id, interaction.user.id)
        custom_title = self.bot.db.get_setting(interaction.guild.id, "ticket_embed_title")
        custom_description = self.bot.db.get_setting(interaction.guild.id, "ticket_embed_description")
        custom_color = self.bot.db.get_setting(interaction.guild.id, "ticket_embed_color")
        reasons_raw = self.bot.db.get_setting(interaction.guild.id, "ticket_reasons")
        reasons = _parse_ticket_reasons(reasons_raw) if reasons_raw else []
        embed = build_embed("Configuration tickets", "Paramètres actifs pour ton serveur")
        embed.add_field(name="Catégorie tickets", value=ticket_category.mention if isinstance(ticket_category, discord.CategoryChannel) else "Non configurée", inline=False)
        embed.add_field(name="Rôle staff", value=staff_role.mention if staff_role else "Non configuré", inline=False)
        embed.add_field(name="Ticket ouvert", value=open_ticket and f"<#{open_ticket['channel_id']}>" or "Aucun ticket ouvert pour toi", inline=False)

        embed.add_field(name="Titre embed", value=custom_title or "Ticket ouvert", inline=False)
        embed.add_field(name="Description embed", value=custom_description or "Contenu par défaut", inline=False)
        embed.add_field(name="Couleur embed", value=custom_color or "Par défaut", inline=False)
        embed.add_field(name="Raisons", value=f"{len(reasons)} entrées" if reasons else "Aucune raison prédéfinie", inline=False)

        panel_title = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_title")
        panel_description = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_description")
        panel_color = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_color")
        embed.add_field(name="Titre panneau", value=panel_title or "Support / Tickets", inline=False)
        embed.add_field(name="Description panneau", value=panel_description or "Contenu par défaut", inline=False)
        embed.add_field(name="Couleur panneau", value=panel_color or "Par défaut", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket.command(name="setembed", description="Configure l'embed du ticket")
    @staff_only()
    @app_commands.choices(type=[
        app_commands.Choice(name="title", value="title"),
        app_commands.Choice(name="description", value="description"),
        app_commands.Choice(name="color", value="color"),
        app_commands.Choice(name="image", value="image_url"),
        app_commands.Choice(name="thumbnail", value="thumbnail_url"),
    ])
    async def ticket_set_embed(self, interaction: discord.Interaction, type: app_commands.Choice[str], value: str):
        key = f"ticket_embed_{type.value}"
        self.bot.db.set_setting(interaction.guild.id, key, value)
        type_name = {
            "title": "Titre",
            "description": "Description",
            "color": "Couleur",
            "image_url": "Image",
            "thumbnail_url": "Miniature",
        }.get(type.value, type.value)
        await interaction.response.send_message(f"{type_name} d'embed enregistrée.", ephemeral=True)

    @ticket.command(name="setreasons", description="Définit les raisons proposées lors de l'ouverture d'un ticket")
    @staff_only()
    async def ticket_set_reasons(self, interaction: discord.Interaction, reasons: str):
        parsed = _parse_ticket_reasons(reasons)
        if not parsed:
            return await interaction.response.send_message("Aucune raison valide trouvée. Sépare les raisons par une nouvelle ligne, | ou ;.", ephemeral=True)
        self.bot.db.set_setting(interaction.guild.id, "ticket_reasons", "\n".join(parsed))
        await interaction.response.send_message(f"{len(parsed)} raisons de ticket enregistrées.", ephemeral=True)

    @ticket.command(name="clearreasons", description="Supprime la liste de raisons du ticket")
    @staff_only()
    async def ticket_clear_reasons(self, interaction: discord.Interaction):
        self.bot.db.set_setting(interaction.guild.id, "ticket_reasons", "")
        await interaction.response.send_message("Raisons de ticket supprimées.", ephemeral=True)

    @ticket.command(name="setpanel", description="Configure le panneau ticket")
    @staff_only()
    @app_commands.choices(type=[
        app_commands.Choice(name="title", value="title"),
        app_commands.Choice(name="description", value="description"),
        app_commands.Choice(name="color", value="color"),
        app_commands.Choice(name="image", value="image_url"),
        app_commands.Choice(name="thumbnail", value="thumbnail_url"),
    ])
    async def ticket_set_panel(self, interaction: discord.Interaction, type: app_commands.Choice[str], value: str):
        key = f"ticket_panel_{type.value}"
        self.bot.db.set_setting(interaction.guild.id, key, value)
        type_name = {
            "title": "Titre",
            "description": "Description",
            "color": "Couleur",
            "image_url": "Image",
            "thumbnail_url": "Miniature",
        }.get(type.value, type.value)
        await interaction.response.send_message(f"{type_name} du panneau enregistrée.", ephemeral=True)

    @ticket.command(name="panel", description="Envoie un panneau ticket dans un salon")
    @staff_only()
    async def ticket_panel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        title = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_title") or "Support / Tickets"
        description = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_description") or "Clique sur le bouton pour ouvrir un ticket. Personnalise la catégorie et le rôle staff avec /ticket setcategory et /ticket setstaffrole."
        color = _parse_color(self.bot.db.get_setting(interaction.guild.id, "ticket_panel_color"))
        embed = build_embed(title, description, color=color)
        image_url = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_image_url")
        if image_url:
            embed.set_image(url=image_url)
        thumbnail_url = self.bot.db.get_setting(interaction.guild.id, "ticket_panel_thumbnail_url")
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        await channel.send(embed=embed, view=TicketPanelView(self.bot))
        await interaction.response.send_message(f"Panneau ticket envoyé dans {channel.mention}.", ephemeral=True)

    @ticket.command(name="previewembed", description="Prévisualise l'embed du ticket dans un salon")
    @staff_only()
    async def ticket_preview_embed(self, interaction: discord.Interaction, channel: discord.TextChannel):
        staff_role_id = self.bot.db.get_setting(interaction.guild.id, "ticket_staff_role_id")
        staff_role = None
        if staff_role_id and staff_role_id.isdigit():
            staff_role = interaction.guild.get_role(int(staff_role_id))
        embed = _build_ticket_embed(
            self.bot,
            interaction.guild,
            interaction.user,
            "Sujet d'exemple",
            "Description d'exemple pour la prévisualisation.",
            "Raison d'exemple",
            channel,
            staff_role,
        )
        embed.add_field(name="Statut", value="Prévisualisation", inline=True)
        embed.add_field(name="Staff assigné", value=staff_role.mention if staff_role else "Non configuré", inline=True)
        await channel.send(embed=embed)
        await interaction.response.send_message(f"Embed de prévisualisation envoyé dans {channel.mention}.", ephemeral=True)

    @ticket.command(name="variables", description="Affiche les variables utiles pour personnaliser les tickets")
    @staff_only()
    async def ticket_variables(self, interaction: discord.Interaction):
        embed = build_embed(
            "Variables utiles pour les tickets",
            "Utilise ces variables dans les titres ou descriptions personnalisées :",
        )
        embed.add_field(name="Variables", value="{user}, {user_name}, {user_id}, {subject}, {description}, {reason}, {guild}, {guild_id}, {ticket_channel}, {ticket_channel_name}, {staff_role}", inline=False)
        embed.add_field(name="Exemple", value="`Sujet : {subject}`\n`Raison : {reason}`\n`Staff : {staff_role}`", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @ticket.command(name="close", description="Ferme le ticket ouvert dans ce salon")
    async def ticket_close(self, interaction: discord.Interaction):
        if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
            return await interaction.response.send_message("Commande utilisable uniquement dans un salon de ticket.", ephemeral=True)
        ticket = self.bot.db.get_ticket_thread(interaction.guild.id, interaction.channel.id)
        if not ticket or ticket["status"] == "closed":
            return await interaction.response.send_message("Ce salon n'est pas un ticket ouvert.", ephemeral=True)
        if interaction.user.id != int(ticket["user_id"]) and not is_staff(interaction.user, self.bot.db):
            return await interaction.response.send_message("Tu n'as pas la permission de fermer ce ticket.", ephemeral=True)
        self.bot.db.close_ticket_thread(interaction.guild.id, interaction.channel.id, datetime.now(timezone.utc).isoformat())
        await interaction.channel.edit(name=f"closed-{interaction.channel.name}", topic="Ticket fermé")
        ticket_owner = interaction.guild.get_member(int(ticket["user_id"]))
        if ticket_owner:
            await interaction.channel.set_permissions(ticket_owner, view_channel=False, send_messages=False)
        await interaction.response.send_message("Ticket fermé avec succès.", ephemeral=True)


if __name__ == "__main__":
    try:
        bot.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        logger.info("Bot stopped manually")
