import os
import json
import datetime

import discord
from discord import app_commands
from dotenv import load_dotenv

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
DATA_FILE = "data.json"


# ---------- التخزين ----------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


data = load_data()


def cfg(guild_id):
    return data.setdefault(str(guild_id), {
        "welcome_channel": None,
        "welcome_msg": "أهلاً {member} في {server}! 🎉",
        "auto_role": None,
        "replies": {},
    })


# ---------- البوت ----------
intents = discord.Intents.default()
intents.members = True          # للترحيب والرتب التلقائية
intents.message_content = True  # للرد التلقائي


class Bot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

    async def setup_hook(self):
        await self.tree.sync()


bot = Bot()
NO_PERM = "❌ مفيش صلاحية. تأكد إن رتبة البوت أعلى من رتبة العضو/الرتبة."


@bot.event
async def on_ready():
    print(f"Logged in as {bot.user} ({bot.user.id})")


# ---------- الترحيب والرتبة التلقائية ----------
@bot.event
async def on_member_join(member: discord.Member):
    c = cfg(member.guild.id)
    if c["auto_role"]:
        role = member.guild.get_role(c["auto_role"])
        if role:
            try:
                await member.add_roles(role, reason="Auto role")
            except discord.Forbidden:
                pass
    if c["welcome_channel"]:
        ch = member.guild.get_channel(c["welcome_channel"])
        if ch:
            msg = c["welcome_msg"].format(member=member.mention, server=member.guild.name)
            await ch.send(msg)


# ---------- الرد التلقائي ----------
@bot.event
async def on_message(message: discord.Message):
    if message.author.bot or not message.guild:
        return
    text = message.content.lower()
    for trigger, response in cfg(message.guild.id)["replies"].items():
        if trigger in text:
            await message.reply(response, mention_author=False)
            break


# ---------- أوامر عامة ----------
@bot.tree.command(name="ping", description="اختبار سرعة البوت")
async def ping(i: discord.Interaction):
    await i.response.send_message(f"🏓 {round(bot.latency * 1000)}ms")


# ---------- أوامر المودريشن ----------
@bot.tree.command(name="ban", description="حظر عضو")
@app_commands.default_permissions(ban_members=True)
@app_commands.guild_only()
async def ban(i: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    try:
        await member.ban(reason=reason)
        await i.response.send_message(f"🔨 تم حظر {member} — {reason}")
    except discord.Forbidden:
        await i.response.send_message(NO_PERM, ephemeral=True)


@bot.tree.command(name="kick", description="طرد عضو")
@app_commands.default_permissions(kick_members=True)
@app_commands.guild_only()
async def kick(i: discord.Interaction, member: discord.Member, reason: str = "بدون سبب"):
    try:
        await member.kick(reason=reason)
        await i.response.send_message(f"👢 تم طرد {member} — {reason}")
    except discord.Forbidden:
        await i.response.send_message(NO_PERM, ephemeral=True)


@bot.tree.command(name="mute", description="ميوت (Timeout) لعضو بالدقائق")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def mute(i: discord.Interaction, member: discord.Member,
               minutes: app_commands.Range[int, 1, 40320], reason: str = "بدون سبب"):
    try:
        await member.timeout(datetime.timedelta(minutes=minutes), reason=reason)
        await i.response.send_message(f"🔇 تم ميوت {member} لمدة {minutes} دقيقة — {reason}")
    except discord.Forbidden:
        await i.response.send_message(NO_PERM, ephemeral=True)


@bot.tree.command(name="unmute", description="فك الميوت عن عضو")
@app_commands.default_permissions(moderate_members=True)
@app_commands.guild_only()
async def unmute(i: discord.Interaction, member: discord.Member):
    try:
        await member.timeout(None)
        await i.response.send_message(f"🔊 تم فك الميوت عن {member}")
    except discord.Forbidden:
        await i.response.send_message(NO_PERM, ephemeral=True)


@bot.tree.command(name="clear", description="مسح رسائل من الشات")
@app_commands.default_permissions(manage_messages=True)
@app_commands.guild_only()
async def clear(i: discord.Interaction, amount: app_commands.Range[int, 1, 100]):
    await i.response.defer(ephemeral=True)
    try:
        deleted = await i.channel.purge(limit=amount)
        await i.followup.send(f"🧹 تم مسح {len(deleted)} رسالة", ephemeral=True)
    except discord.Forbidden:
        await i.followup.send(NO_PERM, ephemeral=True)


# ---------- إعدادات الترحيب والرتبة ----------
@bot.tree.command(name="setwelcome", description="تحديد روم الترحيب (ورسالة اختيارية)")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def setwelcome(i: discord.Interaction, channel: discord.TextChannel, message: str = None):
    c = cfg(i.guild_id)
    c["welcome_channel"] = channel.id
    if message:
        c["welcome_msg"] = message  # استخدم {member} و {server}
    save_data()
    await i.response.send_message(f"✅ الترحيب هيتبعت في {channel.mention}")


@bot.tree.command(name="setautorole", description="تحديد الرتبة التلقائية للأعضاء الجدد")
@app_commands.default_permissions(manage_roles=True)
@app_commands.guild_only()
async def setautorole(i: discord.Interaction, role: discord.Role):
    cfg(i.guild_id)["auto_role"] = role.id
    save_data()
    await i.response.send_message(f"✅ الرتبة التلقائية: {role.mention}")


# ---------- إدارة الردود التلقائية ----------
@bot.tree.command(name="addreply", description="إضافة رد تلقائي لكلمة")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def addreply(i: discord.Interaction, trigger: str, response: str):
    cfg(i.guild_id)["replies"][trigger.lower()] = response
    save_data()
    await i.response.send_message(f"✅ لو حد كتب «{trigger}» هرد: {response}")


@bot.tree.command(name="delreply", description="حذف رد تلقائي")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def delreply(i: discord.Interaction, trigger: str):
    if cfg(i.guild_id)["replies"].pop(trigger.lower(), None) is None:
        await i.response.send_message("❌ الكلمة دي مش موجودة", ephemeral=True)
        return
    save_data()
    await i.response.send_message(f"🗑️ اتحذف الرد على «{trigger}»")


@bot.tree.command(name="replies", description="عرض الردود التلقائية")
@app_commands.default_permissions(manage_guild=True)
@app_commands.guild_only()
async def replies(i: discord.Interaction):
    r = cfg(i.guild_id)["replies"]
    if not r:
        await i.response.send_message("مفيش ردود لسه.", ephemeral=True)
        return
    lines = "\n".join(f"• {k} ← {v}" for k, v in r.items())
    await i.response.send_message(lines[:1900], ephemeral=True)


if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("حط DISCORD_BOT_TOKEN في ملف .env")
    bot.run(TOKEN)
