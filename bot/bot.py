import os
import json
import datetime
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATA_FILE = "data.json"

# Discord presence is applied when the bot process connects.
# A running process is still required for the bot to appear online.
PRESENCE_STATUS = os.getenv("BOT_STATUS", "online").strip().lower()
ACTIVITY_TYPE = os.getenv("BOT_ACTIVITY_TYPE", "watching").strip().lower()
ACTIVITY_TEXT = os.getenv("BOT_ACTIVITY_TEXT", "your community").strip()

PRESENCE_STATUSES = {
    "online": discord.Status.online,
    "idle": discord.Status.idle,
    "dnd": discord.Status.dnd,
    "invisible": discord.Status.invisible,
}
PRESENCE_ACTIVITIES = {
    "playing": discord.ActivityType.playing,
    "listening": discord.ActivityType.listening,
    "watching": discord.ActivityType.watching,
    "competing": discord.ActivityType.competing,
}


# ---------- Local per-server storage ----------
def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    try:
        with open(DATA_FILE, encoding="utf-8") as f:
            value = json.load(f)
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        print("Warning: data.json could not be read; starting with empty in-memory data.")
        return {}


def save_data():
    temporary_file = DATA_FILE + ".tmp"
    with open(temporary_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.flush()
        os.fsync(f.fileno())
    os.replace(temporary_file, DATA_FILE)


data = load_data()


def cfg(guild_id: int):
    """Return a server config and add defaults for older data.json files."""
    current = data.setdefault(str(guild_id), {})
    defaults = {
        "welcome_channel": None,
        "welcome_msg": "أهلاً [user] في [server]! 🎉",
        "auto_role": None,
        "replies": {},
        "warnings": {},
        "logs_channel": None,
    }
    for key, default in defaults.items():
        if key not in current:
            current[key] = default.copy() if isinstance(default, (dict, list)) else default

    if not isinstance(current.get("replies"), dict):
        current["replies"] = {}
    if not isinstance(current.get("warnings"), dict):
        current["warnings"] = {}
    return current


# ---------- Bot setup ----------
intents = discord.Intents.default()
intents.members = True
intents.message_content = True


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


bot = Bot()

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        message = "مش معاك صلاحية استخدام الأمر ده."
    elif isinstance(error, app_commands.BotMissingPermissions):
        message = "البوت ناقصه صلاحية مطلوبة. راجع إعدادات أدوار البوت والقناة."
    elif isinstance(error, app_commands.NoPrivateMessage):
        message = "الأمر ده متاح داخل السيرفرات فقط."
    else:
        original = getattr(error, "original", error)
        print(f"Slash command error: {type(original).__name__}: {original}")
        message = "حصل خطأ أثناء تنفيذ الأمر. حاول مرة أخرى أو راجع سجل تشغيل البوت."

    try:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)
    except discord.HTTPException:
        pass

NO_PERM = "❌ البوت مش معاه الصلاحية المطلوبة. راجع صلاحياته وترتيب رتبته."
PURPLE = discord.Color.from_rgb(148, 80, 213)
GREEN = discord.Color.from_rgb(74, 222, 128)
ORANGE = discord.Color.from_rgb(245, 158, 66)
RED = discord.Color.from_rgb(239, 93, 121)


def member_action_error(interaction: discord.Interaction, target: discord.Member, check_bot=True) -> Optional[str]:
    """Enforce Discord's role hierarchy before a moderation action."""
    guild = interaction.guild
    actor = interaction.user

    if target.id == guild.owner_id:
        return "مش ممكن تنفيذ الإجراء على مالك السيرفر."
    if target.id == actor.id:
        return "مش ممكن تنفيذ الإجراء على نفسك."
    if actor.id != guild.owner_id and target.top_role >= actor.top_role:
        return "رتبة العضو لازم تكون أقل من رتبتك عشان تقدر تنفذ الإجراء."
    if check_bot:
        bot_member = guild.me
        if bot_member is None or target.top_role >= bot_member.top_role:
            return "رتبة العضو أعلى من رتبة البوت أو مساوية لها. ارفع رتبة Creatix فوقها."
    return None


async def send_log(
    guild: discord.Guild,
    title: str,
    description: str,
    color: discord.Color = PURPLE,
):
    """Send an event to the configured per-server log channel."""
    channel_id = cfg(guild.id).get("logs_channel")
    if not channel_id:
        return

    channel = guild.get_channel(int(channel_id))
    if not isinstance(channel, discord.TextChannel):
        return

    embed = discord.Embed(
        title=title,
        description=description[:4000],
        color=color,
        timestamp=discord.utils.utcnow(),
    )
    try:
        await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except (discord.Forbidden, discord.HTTPException):
        return


async def send_moderation_result(interaction: discord.Interaction, message: str):
    if interaction.response.is_done():
        await interaction.followup.send(message, ephemeral=True)
    else:
        await interaction.response.send_message(message, ephemeral=True)


@bot.event
async def on_ready():
    status = PRESENCE_STATUSES.get(PRESENCE_STATUS)
    if status is None:
        print(f"Warning: BOT_STATUS={PRESENCE_STATUS!r} is invalid; using online.")
        status = discord.Status.online

    activity = None
    activity_type = PRESENCE_ACTIVITIES.get(ACTIVITY_TYPE)
    if ACTIVITY_TEXT and activity_type is not None:
        activity = discord.Activity(type=activity_type, name=ACTIVITY_TEXT)
    elif ACTIVITY_TEXT and ACTIVITY_TYPE not in {"none", "off"}:
        print(f"Warning: BOT_ACTIVITY_TYPE={ACTIVITY_TYPE!r} is invalid; no activity will be shown.")

    try:
        await bot.change_presence(status=status, activity=activity)
        print(
            f"Logged in as {bot.user} ({bot.user.id}) "
            f"with status={status.name} and activity={ACTIVITY_TYPE!r}"
        )
    except discord.HTTPException as error:
        print(f"Could not update Discord presence: {error}")


# ---------- Member events ----------
@bot.event
async def on_member_join(member: discord.Member):
    server_cfg = cfg(member.guild.id)

    role_id = server_cfg.get("auto_role")
    if role_id:
        role = member.guild.get_role(int(role_id))
        bot_member = member.guild.me
        if role and bot_member and role < bot_member.top_role and not role.managed:
            try:
                await member.add_roles(role, reason="Creatix automatic role")
            except (discord.Forbidden, discord.HTTPException):
                pass

    channel_id = server_cfg.get("welcome_channel")
    if channel_id:
        channel = member.guild.get_channel(int(channel_id))
        if isinstance(channel, discord.TextChannel):
            message = server_cfg.get("welcome_msg") or "أهلاً [user] في [server]! 🎉"
            member_count = str(member.guild.member_count or "?")
            replacements = {
                "[user]": member.mention,
                "[userName]": member.display_name,
                "[memberCount]": member_count,
                "[server]": member.guild.name,
                # Backward-compatible placeholders used by older saved messages.
                "{member}": member.mention,
                "{user}": member.mention,
                "{userName}": member.display_name,
                "{memberCount}": member_count,
                "{server}": member.guild.name,
                "{count}": member_count,
            }
            for token, value in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
                message = message.replace(token, str(value))

            try:
                await channel.send(
                    message,
                    allowed_mentions=discord.AllowedMentions(
                        users=True,
                        roles=False,
                        everyone=False,
                    ),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    await send_log(
        member.guild,
        "عضو جديد",
        f"**العضو:** {member.mention}\n**الحساب:** {member}\n**عدد الأعضاء:** {member.guild.member_count or 'غير متاح'}",
        GREEN,
    )


# ---------- Automatic replies ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return

    text = message.content.casefold()
    for trigger, response in cfg(message.guild.id)["replies"].items():
        if trigger and trigger.casefold() in text:
            try:
                await message.reply(
                    response,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
            break


# ---------- General utilities ----------
@bot.tree.command(name="ping", description="اختبار سرعة البوت")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="Creatix is online",
        description=f"🏓 سرعة الاستجابة: **{latency}ms**",
        color=GREEN,
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="serverinfo", description="عرض معلومات السيرفر")
@app_commands.guild_only()
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"معلومات {guild.name}", color=PURPLE)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="المالك", value=guild.owner.mention if guild.owner else "غير متاح", inline=True)
    embed.add_field(name="الأعضاء", value=str(guild.member_count or "غير متاح"), inline=True)
    embed.add_field(name="القنوات", value=str(len(guild.channels)), inline=True)
    embed.add_field(name="الرتب", value=str(len(guild.roles)), inline=True)
    embed.add_field(name="تاريخ الإنشاء", value=discord.utils.format_dt(guild.created_at, style="D"), inline=True)
    embed.set_footer(text=f"Server ID: {guild.id}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="userinfo", description="عرض معلومات عضو في السيرفر")
@app_commands.guild_only()
@app_commands.describe(member="العضو المطلوب، واتركه فارغًا لعرض معلوماتك")
async def userinfo(interaction: discord.Interaction, member: Optional[discord.Member] = None):
    target = member or interaction.user
    embed = discord.Embed(title=f"معلومات {target.display_name}", color=PURPLE)
    embed.set_thumbnail(url=target.display_avatar.url)
    embed.add_field(name="اسم الحساب", value=str(target), inline=True)
    embed.add_field(name="المعرف", value=str(target.id), inline=True)
    embed.add_field(name="أعلى رتبة", value=target.top_role.mention, inline=True)
    embed.add_field(
        name="انضم للسيرفر",
        value=discord.utils.format_dt(target.joined_at, style="D") if target.joined_at else "غير متاح",
        inline=True,
    )
    embed.add_field(
        name="تاريخ إنشاء الحساب",
        value=discord.utils.format_dt(target.created_at, style="D"),
        inline=True,
    )
    await interaction.response.send_message(embed=embed)


# ---------- Moderation: ban, kick, timeout, clear ----------
@bot.tree.command(name="ban", description="حظر عضو من السيرفر")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
async def ban(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    error = member_action_error(interaction, member)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    try:
        await member.ban(reason=reason[:500])
        await interaction.response.send_message(f"🔨 تم حظر {member.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "حظر عضو",
            f"**العضو:** {member.mention}\n**بواسطة:** {interaction.user.mention}\n**السبب:** {reason[:500]}",
            RED,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر تنفيذ الحظر من Discord. حاول مرة أخرى.")


@bot.tree.command(name="kick", description="طرد عضو من السيرفر")
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.checks.bot_has_permissions(kick_members=True)
@app_commands.guild_only()
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    error = member_action_error(interaction, member)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    try:
        await member.kick(reason=reason[:500])
        await interaction.response.send_message(f"👢 تم طرد {member.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "طرد عضو",
            f"**العضو:** {member}\n**بواسطة:** {interaction.user.mention}\n**السبب:** {reason[:500]}",
            ORANGE,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر تنفيذ الطرد من Discord. حاول مرة أخرى.")


@bot.tree.command(name="unban", description="فك حظر مستخدم باستخدام Discord ID")
@app_commands.default_permissions(ban_members=True)
@app_commands.checks.has_permissions(ban_members=True)
@app_commands.checks.bot_has_permissions(ban_members=True)
@app_commands.guild_only()
@app_commands.describe(user_id="Discord ID للمستخدم المحظور", reason="سبب فك الحظر")
async def unban(
    interaction: discord.Interaction,
    user_id: str,
    reason: str = "بدون سبب",
):
    raw_id = user_id.strip()
    if not raw_id.isdigit() or not 17 <= len(raw_id) <= 20:
        return await interaction.response.send_message(
            "اكتب Discord ID صحيح للمستخدم.",
            ephemeral=True,
        )

    await interaction.response.defer(ephemeral=True)
    try:
        user = await bot.fetch_user(int(raw_id))
        await interaction.guild.unban(user, reason=reason[:500])
        await interaction.followup.send(f"✅ تم فك الحظر عن {user}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "فك حظر مستخدم",
            f"**المستخدم:** {user}\n**بواسطة:** {interaction.user.mention}\n**السبب:** {reason[:500]}",
            GREEN,
        )
    except discord.NotFound:
        await interaction.followup.send("المستخدم ده مش موجود أو مش موجود في قائمة المحظورين.", ephemeral=True)
    except discord.Forbidden:
        await interaction.followup.send(NO_PERM, ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("تعذّر فك الحظر من Discord. حاول مرة أخرى.", ephemeral=True)


@bot.tree.command(name="mute", description="إسكات عضو لمدة محددة بالدقائق")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
@app_commands.guild_only()
async def mute(
    interaction: discord.Interaction,
    member: discord.Member,
    minutes: app_commands.Range[int, 1, 40320],
    reason: str = "بدون سبب",
):
    error = member_action_error(interaction, member)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    try:
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason[:500])
        await interaction.response.send_message(
            f"🔇 تم إسكات {member.mention} لمدة **{minutes} دقيقة**.",
            ephemeral=True,
        )
        await send_log(
            interaction.guild,
            "إسكات عضو",
            f"**العضو:** {member.mention}\n**المدة:** {minutes} دقيقة\n**بواسطة:** {interaction.user.mention}\n**السبب:** {reason[:500]}",
            ORANGE,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر تنفيذ الإسكات من Discord. حاول مرة أخرى.")


@bot.tree.command(name="unmute", description="إلغاء الإسكات عن عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.checks.bot_has_permissions(moderate_members=True)
@app_commands.guild_only()
async def unmute(interaction: discord.Interaction, member: discord.Member):
    error = member_action_error(interaction, member)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    try:
        await member.timeout(None, reason=f"Timeout removed by {interaction.user}")
        await interaction.response.send_message(f"🔊 تم إلغاء الإسكات عن {member.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "إلغاء إسكات عضو",
            f"**العضو:** {member.mention}\n**بواسطة:** {interaction.user.mention}",
            GREEN,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر إلغاء الإسكات من Discord. حاول مرة أخرى.")


@bot.tree.command(name="clear", description="مسح عدد من الرسائل في القناة")
@app_commands.default_permissions(manage_messages=True)
@app_commands.checks.has_permissions(manage_messages=True)
@app_commands.checks.bot_has_permissions(manage_messages=True)
@app_commands.guild_only()
async def clear(interaction: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    if not isinstance(interaction.channel, discord.TextChannel):
        return await interaction.response.send_message("الأمر ده متاح في القنوات النصية فقط.", ephemeral=True)

    await interaction.response.defer(ephemeral=True)
    try:
        deleted = await interaction.channel.purge(limit=amount)
        await interaction.followup.send(f"🧹 تم مسح **{len(deleted)} رسالة**.", ephemeral=True)
        await send_log(
            interaction.guild,
            "مسح رسائل",
            f"**القناة:** {interaction.channel.mention}\n**العدد:** {len(deleted)}\n**بواسطة:** {interaction.user.mention}",
            ORANGE,
        )
    except discord.Forbidden:
        await interaction.followup.send(NO_PERM, ephemeral=True)
    except discord.HTTPException:
        await interaction.followup.send("تعذّر مسح الرسائل من Discord. حاول مرة أخرى.", ephemeral=True)


# ---------- Warning system ----------
@bot.tree.command(name="warn", description="تسجيل تحذير على عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    error = member_action_error(interaction, member, check_bot=False)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    server_cfg = cfg(interaction.guild_id)
    entries = server_cfg["warnings"].setdefault(str(member.id), [])
    record = {
        "reason": reason[:500],
        "moderator_id": interaction.user.id,
        "created_at": discord.utils.utcnow().isoformat(),
    }
    entries.append(record)
    if len(entries) > 100:
        del entries[:-100]
    save_data()

    await interaction.response.send_message(
        f"⚠️ تم تسجيل تحذير على {member.mention}. إجمالي التحذيرات: **{len(entries)}**.",
        ephemeral=True,
    )
    try:
        await member.send(
            f"تم تسجيل تحذير لك في سيرفر **{interaction.guild.name}**.\nالسبب: {reason[:500]}"
        )
    except (discord.Forbidden, discord.HTTPException):
        pass

    await send_log(
        interaction.guild,
        "تحذير عضو",
        f"**العضو:** {member.mention}\n**بواسطة:** {interaction.user.mention}\n**عدد التحذيرات:** {len(entries)}\n**السبب:** {reason[:500]}",
        ORANGE,
    )


@bot.tree.command(name="warnings", description="عرض التحذيرات المسجلة على عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def warnings(interaction: discord.Interaction, member: discord.Member):
    entries = cfg(interaction.guild_id)["warnings"].get(str(member.id), [])
    if not entries:
        return await interaction.response.send_message(
            f"✅ مفيش تحذيرات مسجلة على {member.mention}.",
            ephemeral=True,
        )

    embed = discord.Embed(
        title=f"تحذيرات {member.display_name}",
        description=f"إجمالي التحذيرات: **{len(entries)}** — أحدث 10 تحذيرات",
        color=ORANGE,
    )
    for index, entry in enumerate(reversed(entries[-10:]), start=1):
        timestamp = entry.get("created_at", "")
        try:
            when = discord.utils.format_dt(datetime.datetime.fromisoformat(timestamp), style="R")
        except (TypeError, ValueError):
            when = "تاريخ غير متاح"
        moderator = interaction.guild.get_member(int(entry.get("moderator_id", 0)))
        moderator_name = moderator.mention if moderator else "مشرف سابق"
        embed.add_field(
            name=f"تحذير #{len(entries) - index + 1}",
            value=f"**السبب:** {entry.get('reason', 'بدون سبب')[:700]}\n**بواسطة:** {moderator_name}\n**الوقت:** {when}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarnings", description="مسح كل تحذيرات عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.guild_only()
async def clearwarnings(interaction: discord.Interaction, member: discord.Member):
    error = member_action_error(interaction, member, check_bot=False)
    if error:
        return await send_moderation_result(interaction, f"⚠️ {error}")

    server_cfg = cfg(interaction.guild_id)
    entries = server_cfg["warnings"].pop(str(member.id), [])
    if not entries:
        return await interaction.response.send_message("العضو ده مفيش عليه تحذيرات.", ephemeral=True)

    save_data()
    await interaction.response.send_message(
        f"🧹 تم مسح **{len(entries)} تحذير** من {member.mention}.",
        ephemeral=True,
    )
    await send_log(
        interaction.guild,
        "مسح تحذيرات",
        f"**العضو:** {member.mention}\n**عدد التحذيرات المحذوفة:** {len(entries)}\n**بواسطة:** {interaction.user.mention}",
        GREEN,
    )


# ---------- Channel controls ----------
@bot.tree.command(name="lock", description="منع الأعضاء من إرسال الرسائل في قناة")
@app_commands.default_permissions(manage_channels=True, manage_roles=True)
@app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
@app_commands.describe(channel="القناة المطلوب قفلها، واتركها فارغة للقناة الحالية")
async def lock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await interaction.response.send_message("اختار قناة نصية صالحة.", ephemeral=True)

    bot_member = interaction.guild.me
    if bot_member is None or not target.permissions_for(bot_member).manage_roles:
        return await interaction.response.send_message(NO_PERM, ephemeral=True)

    overwrite = target.overwrites_for(interaction.guild.default_role)
    if overwrite.send_messages is False:
        return await interaction.response.send_message("القناة مقفولة بالفعل.", ephemeral=True)

    overwrite.send_messages = False
    try:
        await target.set_permissions(
            interaction.guild.default_role,
            overwrite=overwrite,
            reason=f"Channel locked by {interaction.user}",
        )
        await interaction.response.send_message(f"🔒 تم قفل {target.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "قفل قناة",
            f"**القناة:** {target.mention}\n**بواسطة:** {interaction.user.mention}",
            ORANGE,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر قفل القناة. حاول مرة أخرى.")


@bot.tree.command(name="unlock", description="السماح للأعضاء بإرسال الرسائل في قناة")
@app_commands.default_permissions(manage_channels=True, manage_roles=True)
@app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
@app_commands.describe(channel="القناة المطلوب فتحها، واتركها فارغة للقناة الحالية")
async def unlock(interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None):
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await interaction.response.send_message("اختار قناة نصية صالحة.", ephemeral=True)

    bot_member = interaction.guild.me
    if bot_member is None or not target.permissions_for(bot_member).manage_roles:
        return await interaction.response.send_message(NO_PERM, ephemeral=True)

    overwrite = target.overwrites_for(interaction.guild.default_role)
    if overwrite.send_messages is not False:
        return await interaction.response.send_message("القناة مش مقفولة بواسطة Creatix.", ephemeral=True)

    overwrite.send_messages = None
    try:
        await target.set_permissions(
            interaction.guild.default_role,
            overwrite=None if overwrite.is_empty() else overwrite,
            reason=f"Channel unlocked by {interaction.user}",
        )
        await interaction.response.send_message(f"🔓 تم فتح {target.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "فتح قناة",
            f"**القناة:** {target.mention}\n**بواسطة:** {interaction.user.mention}",
            GREEN,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر فتح القناة. حاول مرة أخرى.")


@bot.tree.command(name="slowmode", description="تحديد وقت الانتظار بين الرسائل في قناة")
@app_commands.default_permissions(manage_channels=True)
@app_commands.checks.has_permissions(manage_channels=True)
@app_commands.checks.bot_has_permissions(manage_channels=True)
@app_commands.guild_only()
@app_commands.describe(
    seconds="عدد الثواني بين الرسائل (0 لإلغاء الوضع البطيء، والحد الأقصى 21600)",
    channel="القناة المطلوب تعديلها، واتركها فارغة للقناة الحالية",
)
async def slowmode(
    interaction: discord.Interaction,
    seconds: app_commands.Range[int, 0, 21600],
    channel: Optional[discord.TextChannel] = None,
):
    target = channel or interaction.channel
    if not isinstance(target, discord.TextChannel):
        return await interaction.response.send_message("اختار قناة نصية صالحة.", ephemeral=True)

    bot_member = interaction.guild.me
    if bot_member is None or not target.permissions_for(bot_member).manage_channels:
        return await interaction.response.send_message(NO_PERM, ephemeral=True)

    try:
        await target.edit(
            slowmode_delay=seconds,
            reason=f"Slowmode updated by {interaction.user}",
        )
        status = "تم إلغاء الوضع البطيء" if seconds == 0 else f"تم ضبط الوضع البطيء على **{seconds} ثانية**"
        await interaction.response.send_message(f"⏱️ {status} في {target.mention}.", ephemeral=True)
        await send_log(
            interaction.guild,
            "تعديل الوضع البطيء",
            f"**القناة:** {target.mention}\n**المدة:** {seconds} ثانية\n**بواسطة:** {interaction.user.mention}",
            PURPLE,
        )
    except discord.Forbidden:
        await send_moderation_result(interaction, NO_PERM)
    except discord.HTTPException:
        await send_moderation_result(interaction, "تعذّر تعديل الوضع البطيء. حاول مرة أخرى.")


# ---------- Server logs configuration ----------
@bot.tree.command(name="setlogs", description="تحديد قناة سجلات Creatix")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
@app_commands.describe(channel="القناة التي ستستقبل سجلات الأعضاء والإشراف")
async def setlogs(interaction: discord.Interaction, channel: discord.TextChannel):
    bot_member = interaction.guild.me
    if bot_member is None:
        return await interaction.response.send_message(NO_PERM, ephemeral=True)

    permissions = channel.permissions_for(bot_member)
    if not (permissions.view_channel and permissions.send_messages and permissions.embed_links):
        return await interaction.response.send_message(
            "البوت محتاج View Channel وSend Messages وEmbed Links في القناة المختارة.",
            ephemeral=True,
        )

    cfg(interaction.guild_id)["logs_channel"] = channel.id
    save_data()
    await interaction.response.send_message(
        f"✅ تم تحديد {channel.mention} كقناة سجلات Creatix.",
        ephemeral=True,
    )
    await send_log(
        interaction.guild,
        "تم إعداد قناة السجلات",
        f"من الآن هتظهر سجلات الأعضاء والإشراف هنا.\n**بواسطة:** {interaction.user.mention}",
        GREEN,
    )


@bot.tree.command(name="disablelogs", description="إيقاف سجلات Creatix في هذا السيرفر")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def disablelogs(interaction: discord.Interaction):
    cfg(interaction.guild_id)["logs_channel"] = None
    save_data()
    await interaction.response.send_message("تم إيقاف سجلات Creatix في السيرفر.", ephemeral=True)


# ---------- Welcome and automatic role setup ----------
@bot.tree.command(name="setwelcome", description="تحديد قناة الترحيب ورسالة اختيارية")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
@app_commands.describe(
    channel="قناة إرسال رسالة الترحيب",
    message="المتغيرات: [user] منشن، [userName] الاسم، [memberCount] عدد الأعضاء، [server] اسم السيرفر.",
)
async def setwelcome(
    interaction: discord.Interaction,
    channel: discord.TextChannel,
    message: str = "أهلاً [user] في [server]! 🎉",
):
    bot_member = interaction.guild.me
    if bot_member is None or not channel.permissions_for(bot_member).send_messages:
        return await interaction.response.send_message(
            "البوت محتاج صلاحية Send Messages في قناة الترحيب المختارة.",
            ephemeral=True,
        )
    cfg(interaction.guild_id)["welcome_channel"] = channel.id
    cfg(interaction.guild_id)["welcome_msg"] = message[:1000]
    save_data()
    await interaction.response.send_message(f"✅ الترحيب هيتبعت في {channel.mention}.", ephemeral=True)


@bot.tree.command(name="setautorole", description="تحديد الرتبة التلقائية للأعضاء الجدد")
@app_commands.default_permissions(manage_roles=True)
@app_commands.checks.has_permissions(manage_roles=True)
@app_commands.checks.bot_has_permissions(manage_roles=True)
@app_commands.guild_only()
async def setautorole(interaction: discord.Interaction, role: discord.Role):
    bot_member = interaction.guild.me
    if role.is_default() or role.managed or bot_member is None or role >= bot_member.top_role:
        return await interaction.response.send_message(
            "اختار رتبة أقل من أعلى رتبة للبوت، وتأكد إنها مش رتبة مُدارة.",
            ephemeral=True,
        )

    cfg(interaction.guild_id)["auto_role"] = role.id
    save_data()
    await interaction.response.send_message(f"✅ الرتبة التلقائية: {role.mention}.", ephemeral=True)


# ---------- Automatic replies management ----------
@bot.tree.command(name="addreply", description="إضافة رد تلقائي لكلمة")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def addreply(interaction: discord.Interaction, trigger: str, response: str):
    trigger = trigger.strip().casefold()
    response = response.strip()
    if not trigger or not response:
        return await interaction.response.send_message("اكتب الكلمة والرد بشكل صحيح.", ephemeral=True)

    replies = cfg(interaction.guild_id)["replies"]
    if trigger not in replies and len(replies) >= 50:
        return await interaction.response.send_message("وصلت للحد الأقصى: 50 رد تلقائي.", ephemeral=True)

    replies[trigger[:100]] = response[:1000]
    save_data()
    await interaction.response.send_message(
        f"✅ لو حد كتب «{trigger[:100]}» هرد عليه بالرد المحدد.",
        ephemeral=True,
    )


@bot.tree.command(name="delreply", description="حذف رد تلقائي")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def delreply(interaction: discord.Interaction, trigger: str):
    trigger = trigger.strip().casefold()
    if cfg(interaction.guild_id)["replies"].pop(trigger, None) is None:
        return await interaction.response.send_message("❌ الكلمة دي مش موجودة.", ephemeral=True)

    save_data()
    await interaction.response.send_message(f"🗑️ اتحذف الرد على «{trigger[:100]}».", ephemeral=True)


@bot.tree.command(name="replies", description="عرض الردود التلقائية")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.guild_only()
async def replies(interaction: discord.Interaction):
    items = cfg(interaction.guild_id)["replies"]
    if not items:
        return await interaction.response.send_message("مفيش ردود لسه.", ephemeral=True)

    embed = discord.Embed(title="الردود التلقائية", color=PURPLE)
    for trigger, response in list(items.items())[:20]:
        embed.add_field(name=trigger[:256], value=response[:900], inline=False)
    if len(items) > 20:
        embed.set_footer(text=f"معروض 20 من أصل {len(items)} رد")
    await interaction.response.send_message(embed=embed, ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("حط DISCORD_BOT_TOKEN في ملف .env")
    bot.run(TOKEN)
