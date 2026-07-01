import os
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

from app.database import (
    get_all_active_events,
    get_guild_settings,
    init_db,
    save_event,
    save_guild_settings,
)

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


def parse_event_datetime(date_text: str, time_text: str) -> datetime:
    raw = f"{date_text.strip()} {time_text.strip()}"

    formats = [
        "%m/%d/%Y %I:%M %p",  # 07/11/2026 5:00 PM
        "%m/%d/%Y %H:%M",     # 07/11/2026 17:00
    ]

    for fmt in formats:
        try:
            naive_local_dt = datetime.strptime(raw, fmt)

            # Interpret the entered time as the computer/container's local time.
            local_dt = naive_local_dt.astimezone()

            return local_dt.astimezone(timezone.utc)
        except ValueError:
            pass

    raise ValueError("Use date MM/DD/YYYY and time like 5:00 PM or 17:00.")


def parse_stored_utc_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def format_remaining(event_time_utc: datetime) -> str:
    now = datetime.now(timezone.utc)
    remaining = event_time_utc - now

    if remaining.total_seconds() <= 0:
        return "now"

    # Round up so 5d 0h 59m still displays as 5d-01h.
    total_hours = int(remaining.total_seconds() // 3600)

    days = total_hours // 24
    hours = total_hours % 24

    return f"{days}d-{hours:02d}h"


def make_channel_name(event_name: str, event_time_utc: datetime) -> str:
    countdown = format_remaining(event_time_utc)

    safe_name = (
        event_name.lower()
        .strip()
        .replace(" ", "-")
        .replace(":", "")
    )

    return f"{safe_name}-{countdown}"[:100]


async def update_one_countdown(row):
    guild = bot.get_guild(row["guild_id"])
    if guild is None:
        return

    channel = guild.get_channel(row["channel_id"])
    if not isinstance(channel, discord.TextChannel):
        return

    event_time_utc = parse_stored_utc_datetime(row["event_time_utc"])
    new_name = make_channel_name(row["event_name"], event_time_utc)

    new_topic = f"{row['event_name']} starts at <t:{int(event_time_utc.timestamp())}:F>"

    if channel.name != new_name or channel.topic != new_topic:
        await channel.edit(
            name=new_name,
            topic=new_topic,
        )
        print(f"Updated countdown channel: {channel.name} -> {new_name}")


@tasks.loop(hours=1)
async def update_countdowns():
    rows = get_all_active_events()

    for row in rows:
        try:
            await update_one_countdown(row)
        except discord.Forbidden:
            print(f"Missing permission to update channel for guild {row['guild_id']}")
        except Exception as error:
            print(f"Error updating countdown for guild {row['guild_id']}: {error}")


@update_countdowns.before_loop
async def before_update_countdowns():
    await bot.wait_until_ready()


@bot.event
async def on_ready():
    init_db()

    print("=" * 40)
    print(f"Logged in as: {bot.user}")
    print(f"Bot ID: {bot.user.id}")
    print("Syncing slash commands...")
    await bot.tree.sync()
    print("Slash commands synced.")

    # if not update_countdowns.is_running():
    #     update_countdowns.start()
    #     print("Countdown updater started.")

    print("=" * 40)


@bot.tree.command(name="setup_clock", description="Configure the countdown clock role and category.")
@app_commands.describe(
    role="Role that can see the countdown channel",
    category="Category where the countdown channel should be created",
)
async def setup_clock(
    interaction: discord.Interaction,
    role: discord.Role,
    category: discord.CategoryChannel,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    save_guild_settings(
        guild_id=interaction.guild.id,
        role_id=role.id,
        category_id=category.id,
    )

    await interaction.response.send_message(
        f"Clock configured.\nRole: {role.mention}\nCategory: {category.name}",
        ephemeral=True,
    )


@bot.tree.command(name="create_event", description="Create or update the countdown event.")
@app_commands.describe(
    name="Event name, such as Next Session",
    date="Event date in MM/DD/YYYY format",
    time="Event time, such as 5:00 PM or 17:00",
)
async def create_event(
    interaction: discord.Interaction,
    name: str,
    date: str,
    time: str,
):
    if interaction.guild is None:
        await interaction.response.send_message(
            "This command can only be used inside a server.",
            ephemeral=True,
        )
        return

    settings = get_guild_settings(interaction.guild.id)

    if settings is None:
        await interaction.response.send_message(
            "Run /setup_clock first.",
            ephemeral=True,
        )
        return

    try:
        event_time_utc = parse_event_datetime(date, time)
    except ValueError as error:
        await interaction.response.send_message(str(error), ephemeral=True)
        return

    role = interaction.guild.get_role(settings["role_id"])
    category = interaction.guild.get_channel(settings["category_id"])

    if role is None or category is None:
        await interaction.response.send_message(
            "Saved role or category could not be found. Run /setup_clock again.",
            ephemeral=True,
        )
        return

    channel_name = make_channel_name(name, event_time_utc)

    overwrites = {
        interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
        role: discord.PermissionOverwrite(view_channel=True),
        interaction.guild.me: discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=True,
            send_messages=True,
            read_message_history=True,
        ),
    }

    channel = None
    if settings["channel_id"]:
        existing = interaction.guild.get_channel(settings["channel_id"])
        if isinstance(existing, discord.TextChannel):
            channel = existing

    try:
        if channel is None:
            channel = await interaction.guild.create_text_channel(
                name=channel_name,
                category=category,
                overwrites=overwrites,
                topic=f"{name} starts at <t:{int(event_time_utc.timestamp())}:F>",
            )
        else:
            new_topic = f"{name} starts at <t:{int(event_time_utc.timestamp())}:F>"

            needs_edit = (
                channel.name != channel_name
                or channel.category_id != category.id
                or channel.topic != new_topic
            )

            if needs_edit:
                await channel.edit(
                    name=channel_name,
                    category=category,
                    topic=new_topic,
                )
    except discord.Forbidden:
        await interaction.response.send_message(
            "I do not have permission to create or update that channel. "
            "Grant me Manage Channels and make sure my role is high enough.",
            ephemeral=True,
        )
        return

    save_event(
        guild_id=interaction.guild.id,
        channel_id=channel.id,
        event_name=name,
        event_time_utc=event_time_utc.isoformat(),
    )

    await interaction.response.send_message(
        f"Countdown set: {channel.mention}\nStarts: <t:{int(event_time_utc.timestamp())}:F>",
        ephemeral=True,
    )


def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN not found in .env")

    bot.run(TOKEN)


if __name__ == "__main__":
    main()