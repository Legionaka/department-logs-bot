# main.py
# Discord Department Logs Bot (Slash commands only)
# Fixes "Application did not respond" by deferring + safe logging.

import discord
from discord import app_commands
import yaml
from datetime import datetime
from typing import Optional

import database


# ----------------- Helpers -----------------
def now_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def load_config():
    with open("config.yml", "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    # Basic config sanity
    required = ["token", "guild_id", "channels", "roles"]
    missing = [k for k in required if k not in cfg]
    if missing:
        raise ValueError(f"Missing required config keys: {missing}")

    return cfg


CONFIG = load_config()
GUILD_ID = int(CONFIG["guild_id"])


intents = discord.Intents.default()
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)


def has_any_role(member: discord.Member, role_ids: list[int]) -> bool:
    member_role_ids = {r.id for r in member.roles}
    return any(rid in member_role_ids for rid in role_ids)


def is_authorized(interaction: discord.Interaction, category: str) -> bool:
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        return False

    member: discord.Member = interaction.user

    admin_roles = [int(x) for x in CONFIG.get("admin_roles", [])]
    if admin_roles and has_any_role(member, admin_roles):
        return True

    allowed = [int(x) for x in CONFIG["roles"].get(category, [])]
    # If you want "everyone can use commands", set roles category to [] and return True here.
    return bool(allowed) and has_any_role(member, allowed)


async def post_log(channel_key: str, content: str):
    channel_id = int(CONFIG["channels"][channel_key])
    channel = client.get_channel(channel_id)
    if channel is None:
        channel = await client.fetch_channel(channel_id)
    await channel.send(content)


async def safe_post_log(channel_key: str, content: str) -> bool:
    """Returns True if posted successfully, False otherwise."""
    try:
        await post_log(channel_key, content)
        return True
    except discord.Forbidden:
        print(f"[LOG ERROR] Missing permissions to send in '{channel_key}' channel.")
        return False
    except discord.NotFound:
        print(f"[LOG ERROR] Channel for '{channel_key}' not found (bad ID?).")
        return False
    except Exception as e:
        print(f"[LOG ERROR] Failed to send to '{channel_key}': {e}")
        return False


# ----------------- Ready / Sync -----------------
@client.event
async def on_ready():
    print("Logged in as:", client.user)
    print("Guilds I can see:", [(g.name, g.id) for g in client.guilds])

    await database.init_db()

    # Guild sync (instant command appearance)
    guild = discord.Object(id=GUILD_ID)
    synced = await tree.sync(guild=guild)
    print(f"Synced {len(synced)} commands to guild {GUILD_ID}")


# ----------------- Global Command Error Handler -----------------
@tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    # Ensure we respond even if something explodes
    msg = f"❌ Error: {type(error).__name__}"
    print("[COMMAND ERROR]", repr(error))

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


# ----------------- Commands: Shifts -----------------
@tree.command(name="shift_start", description="Start your duty shift")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(badge="Your badge number", division="Your division", rank="Your rank", notes="Optional notes")
async def shift_start(
    interaction: discord.Interaction,
    badge: str,
    division: str,
    rank: str,
    notes: Optional[str] = "",
):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "shifts"):
        return await interaction.followup.send("❌ You are not allowed to use shift commands.", ephemeral=True)

    active = await database.get_active_shift(interaction.user.id)
    if active:
        return await interaction.followup.send("⚠️ You already have an active shift. Use `/shift_end` first.", ephemeral=True)

    started_at = now_iso()
    await database.start_shift(
        interaction.user.id,
        str(interaction.user),
        badge.strip(),
        division.strip(),
        rank.strip(),
        started_at,
        (notes or "").strip(),
    )

    await safe_post_log(
        "shifts",
        f"🟩 **SHIFT START**\n"
        f"**Officer:** {interaction.user.mention} ({interaction.user})\n"
        f"**Badge:** `{badge}` | **Rank:** `{rank}` | **Division:** `{division}`\n"
        f"**Start:** `{started_at}`\n"
        f"**Notes:** {notes if notes else 'None'}",
    )

    await interaction.followup.send("✅ Shift started and logged.", ephemeral=True)


@tree.command(name="shift_end", description="End your duty shift")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(notes="Optional end-of-shift notes")
async def shift_end(interaction: discord.Interaction, notes: Optional[str] = ""):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "shifts"):
        return await interaction.followup.send("❌ You are not allowed to use shift commands.", ephemeral=True)

    active = await database.get_active_shift(interaction.user.id)
    if not active:
        return await interaction.followup.send("⚠️ You do not have an active shift. Use `/shift_start`.", ephemeral=True)

    ended_at = now_iso()
    await database.end_shift(interaction.user.id, ended_at, (notes or "").strip())

    await safe_post_log(
        "shifts",
        f"🟥 **SHIFT END**\n"
        f"**Officer:** {interaction.user.mention} ({interaction.user})\n"
        f"**End:** `{ended_at}`\n"
        f"**Notes:** {notes if notes else 'None'}",
    )

    await interaction.followup.send("✅ Shift ended and logged.", ephemeral=True)


@tree.command(name="shift_recent", description="Show recent shift logs")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(limit="How many to show (max 25)")
async def shift_recent(interaction: discord.Interaction, limit: Optional[int] = 10):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "shifts"):
        return await interaction.followup.send("❌ You are not allowed to use shift commands.", ephemeral=True)

    limit = max(1, min(25, limit or 10))
    rows = await database.list_shifts(limit)

    if not rows:
        return await interaction.followup.send("No shifts found.", ephemeral=True)

    lines = []
    for (sid, username, badge, division, rank, started, ended) in rows:
        lines.append(f"`#{sid}` **{username}** | `{badge}` `{rank}` `{division}` | {started} → {ended or 'ACTIVE'}")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


# ----------------- Commands: Arrests -----------------
@tree.command(name="arrest_log", description="Create an arrest log entry")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    date_time="Date/time of arrest (or type 'now')",
    location="Where the arrest occurred",
    suspect="Suspect name",
    charges="Charges (comma separated)",
    summary="Incident summary",
    assisting="Assisting officers (optional)",
    evidence="Evidence collected (optional)",
)
async def arrest_log(
    interaction: discord.Interaction,
    date_time: str,
    location: str,
    suspect: str,
    charges: str,
    summary: str,
    assisting: Optional[str] = "",
    evidence: Optional[str] = "",
):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "arrests"):
        return await interaction.followup.send("❌ You are not allowed to use arrest commands.", ephemeral=True)

    dt = now_iso() if date_time.lower().strip() in ("now", "today") else date_time.strip()

    await database.add_arrest(
        interaction.user.id,
        str(interaction.user),
        dt,
        location.strip(),
        suspect.strip(),
        charges.strip(),
        (assisting or "").strip(),
        (evidence or "").strip(),
        summary.strip(),
    )

    await safe_post_log(
        "arrests",
        f"🚓 **ARREST LOG**\n"
        f"**Officer:** {interaction.user.mention} ({interaction.user})\n"
        f"**Date/Time:** `{dt}`\n"
        f"**Location:** `{location}`\n"
        f"**Suspect:** `{suspect}`\n"
        f"**Charges:** `{charges}`\n"
        f"**Assisting:** {assisting if assisting else 'None'}\n"
        f"**Evidence:** {evidence if evidence else 'None'}\n"
        f"**Summary:** {summary}",
    )

    await interaction.followup.send("✅ Arrest logged.", ephemeral=True)


@tree.command(name="arrest_recent", description="Show recent arrests")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(limit="How many to show (max 25)")
async def arrest_recent(interaction: discord.Interaction, limit: Optional[int] = 10):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "arrests"):
        return await interaction.followup.send("❌ You are not allowed to use arrest commands.", ephemeral=True)

    limit = max(1, min(25, limit or 10))
    rows = await database.list_arrests(limit)
    if not rows:
        return await interaction.followup.send("No arrests found.", ephemeral=True)

    lines = []
    for (aid, username, dt, loc, suspect, charges) in rows:
        lines.append(f"`#{aid}` **{username}** | `{dt}` | `{loc}` | `{suspect}` | `{charges}`")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


# ----------------- Commands: Discharges -----------------
@tree.command(name="firearm_discharge", description="Log a firearm discharge report")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(
    date_time="Date/time of discharge (or type 'now')",
    location="Where it happened",
    firearm="Firearm used",
    rounds="Number of rounds fired",
    reason="Reason for discharge",
    summary="Summary of incident",
    injuries="Any injuries (optional)",
    supervisor="Supervisor notified (optional)",
)
async def firearm_discharge(
    interaction: discord.Interaction,
    date_time: str,
    location: str,
    firearm: str,
    rounds: int,
    reason: str,
    summary: str,
    injuries: Optional[str] = "",
    supervisor: Optional[str] = "",
):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "discharges"):
        return await interaction.followup.send("❌ You are not allowed to use discharge commands.", ephemeral=True)

    if rounds < 0 or rounds > 500:
        return await interaction.followup.send("⚠️ Rounds value looks wrong. Use a normal number.", ephemeral=True)

    dt = now_iso() if date_time.lower().strip() in ("now", "today") else date_time.strip()

    await database.add_discharge(
        interaction.user.id,
        str(interaction.user),
        dt,
        location.strip(),
        firearm.strip(),
        int(rounds),
        reason.strip(),
        (injuries or "").strip(),
        (supervisor or "").strip(),
        summary.strip(),
    )

    await safe_post_log(
        "discharges",
        f"🔫 **FIREARM DISCHARGE REPORT**\n"
        f"**Officer:** {interaction.user.mention} ({interaction.user})\n"
        f"**Date/Time:** `{dt}`\n"
        f"**Location:** `{location}`\n"
        f"**Firearm:** `{firearm}` | **Rounds:** `{rounds}`\n"
        f"**Reason:** `{reason}`\n"
        f"**Injuries:** {injuries if injuries else 'None'}\n"
        f"**Supervisor:** {supervisor if supervisor else 'None'}\n"
        f"**Summary:** {summary}",
    )

    await interaction.followup.send("✅ Discharge report logged.", ephemeral=True)


@tree.command(name="discharge_recent", description="Show recent firearm discharge reports")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(limit="How many to show (max 25)")
async def discharge_recent(interaction: discord.Interaction, limit: Optional[int] = 10):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "discharges"):
        return await interaction.followup.send("❌ You are not allowed to use discharge commands.", ephemeral=True)

    limit = max(1, min(25, limit or 10))
    rows = await database.list_discharges(limit)
    if not rows:
        return await interaction.followup.send("No discharge reports found.", ephemeral=True)

    lines = []
    for (did, username, dt, loc, firearm, rounds) in rows:
        lines.append(f"`#{did}` **{username}** | `{dt}` | `{loc}` | `{firearm}` | `{rounds} rounds`")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


# ----------------- Commands: LOA -----------------
@tree.command(name="loa_request", description="Request a Leave of Absence (LOA)")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(start_date="Start date (YYYY-MM-DD)", end_date="End date (YYYY-MM-DD)", reason="Reason for LOA")
async def loa_request(interaction: discord.Interaction, start_date: str, end_date: str, reason: str):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "loa"):
        return await interaction.followup.send("❌ You are not allowed to use LOA commands.", ephemeral=True)

    await database.add_loa(
        interaction.user.id,
        str(interaction.user),
        start_date.strip(),
        end_date.strip(),
        reason.strip(),
        "PENDING",
        "",
    )

    await safe_post_log(
        "loa",
        f"📝 **LOA REQUEST**\n"
        f"**Member:** {interaction.user.mention} ({interaction.user})\n"
        f"**From:** `{start_date}` → **To:** `{end_date}`\n"
        f"**Reason:** {reason}\n"
        f"**Status:** `PENDING`",
    )

    await interaction.followup.send("✅ LOA request submitted.", ephemeral=True)


@tree.command(name="loa_decide", description="Approve or deny a LOA by ID")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(loa_id="The LOA ID number", decision="approve or deny")
async def loa_decide(interaction: discord.Interaction, loa_id: int, decision: str):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "loa"):
        return await interaction.followup.send("❌ You are not allowed to use LOA commands.", ephemeral=True)

    dec = decision.lower().strip()
    if dec not in ("approve", "approved", "deny", "denied"):
        return await interaction.followup.send("Use `approve` or `deny`.", ephemeral=True)

    status = "APPROVED" if dec.startswith("app") else "DENIED"
    approver = str(interaction.user)

    await database.update_loa_status(int(loa_id), status, approver)

    await safe_post_log(
        "loa",
        f"✅ **LOA DECISION**\n"
        f"**LOA ID:** `#{loa_id}`\n"
        f"**Decision:** `{status}`\n"
        f"**By:** {interaction.user.mention} ({interaction.user})\n"
        f"**Time:** `{now_iso()}`",
    )

    await interaction.followup.send(f"✅ LOA `#{loa_id}` marked as `{status}`.", ephemeral=True)


@tree.command(name="loa_recent", description="Show recent LOA requests")
@app_commands.guilds(discord.Object(id=GUILD_ID))
@app_commands.describe(limit="How many to show (max 25)")
async def loa_recent(interaction: discord.Interaction, limit: Optional[int] = 10):
    await interaction.response.defer(ephemeral=True)

    if not is_authorized(interaction, "loa"):
        return await interaction.followup.send("❌ You are not allowed to use LOA commands.", ephemeral=True)

    limit = max(1, min(25, limit or 10))
    rows = await database.list_loa(limit)
    if not rows:
        return await interaction.followup.send("No LOAs found.", ephemeral=True)

    lines = []
    for (lid, username, start, end, status) in rows:
        lines.append(f"`#{lid}` **{username}** | `{start} → {end}` | `{status}`")

    await interaction.followup.send("\n".join(lines), ephemeral=True)


# ----------------- Run -----------------
if not CONFIG.get("token") or "PASTE_YOUR_BOT_TOKEN_HERE" in str(CONFIG.get("token")):
    raise ValueError("Put your bot token in config.yml (token: ...) before running.")

client.run(CONFIG["token"])
