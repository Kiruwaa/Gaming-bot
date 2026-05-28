"""
Bot Discord — Gaming Community
================================
Fonctionnalités :
  - Commandes slash custom (/ping, /info, /regles, /userinfo)
  - Modération (/ban, /kick, /mute, /unmute, /warn, /warns, /clear)
  - Rôles par réaction automatiques
  - Message de bienvenue + auto-rôle Nouveau
  - Logs de modération
  - Notifications Twitch automatiques

Dépendances : pip install discord.py aiohttp
Python : 3.8+
"""

import discord
from discord import app_commands
from discord.ext import commands, tasks
import json
import os
import aiohttp
from datetime import datetime, timedelta

# ─── CONFIG — à modifier ──────────────────────────────────────────────────────

TOKEN = os.environ.get("DISCORD_TOKEN", "VOTRE_TOKEN_ICI")
TWITCH_CLIENT_ID = os.environ.get("TWITCH_CLIENT_ID", "ufmytitwt42r3ttlsxislzf9xh44pa")
TWITCH_CLIENT_SECRET = os.environ.get("TWITCH_CLIENT_SECRET", "g8384v1lt0fcobkhvj6pkmzab7i003")
TWITCH_CHANNEL_NAME = "lives-twitch"          # Token du bot (Discord Developer Portal)
GUILD_ID = None                    # ID de votre serveur pour sync instantanée (int), ou None (global, ~1h)
LOG_CHANNEL_NAME = "logs-modération"

# Reaction roles : rempli dynamiquement avec /setup_reaction_roles
# Format : { "message_id_str": { "emoji": "Nom du rôle" } }
# Exemple : { "123456789": { "🎮": "Gamer", "⭐": "VIP" } }
REACTION_ROLES: dict[str, dict[str, str]] = {}

# ─── INTENTS ──────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.reactions = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ─── TWITCH (stockage JSON local) ────────────────────────────────────────────

TWITCH_FILE = "twitch.json"
twitch_token = None
live_streamers = set()  # streamers actuellement en live (pour éviter les doublons)

def load_twitch() -> dict:
    if os.path.exists(TWITCH_FILE):
        with open(TWITCH_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}  # { discord_user_id: twitch_username }

def save_twitch(data: dict):
    with open(TWITCH_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

async def get_twitch_token() -> str:
    global twitch_token
    async with aiohttp.ClientSession() as session:
        resp = await session.post(
            "https://id.twitch.tv/oauth2/token",
            params={
                "client_id": TWITCH_CLIENT_ID,
                "client_secret": TWITCH_CLIENT_SECRET,
                "grant_type": "client_credentials"
            }
        )
        data = await resp.json()
        twitch_token = data.get("access_token")
    return twitch_token

async def check_twitch_live(usernames: list) -> list:
    """Retourne la liste des streamers actuellement en live avec leurs infos."""
    if not usernames:
        return []
    token = await get_twitch_token()
    headers = {"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {token}"}
    params = [("user_login", u) for u in usernames]
    async with aiohttp.ClientSession() as session:
        resp = await session.get("https://api.twitch.tv/helix/streams", headers=headers, params=params)
        data = await resp.json()
        return data.get("data", [])

# ─── WARNINGS (stockage JSON local) ──────────────────────────────────────────

WARNINGS_FILE = "warnings.json"

def load_warnings() -> dict:
    if os.path.exists(WARNINGS_FILE):
        with open(WARNINGS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_warnings(data: dict):
    with open(WARNINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ─── HELPERS ─────────────────────────────────────────────────────────────────

async def get_log_channel(guild: discord.Guild) -> discord.TextChannel | None:
    return discord.utils.get(guild.text_channels, name=LOG_CHANNEL_NAME)

async def log_action(guild: discord.Guild, action: str, moderator: discord.Member,
                     target: discord.Member | discord.User, reason: str = None):
    """Envoie un embed de log dans #logs-modération."""
    channel = await get_log_channel(guild)
    if not channel:
        return
    embed = discord.Embed(
        title=f"🔨 {action}",
        color=discord.Color.red(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="Cible", value=f"{target.mention} (`{target}`)", inline=True)
    embed.add_field(name="Modérateur", value=moderator.mention, inline=True)
    if reason:
        embed.add_field(name="Raison", value=reason, inline=False)
    embed.set_footer(text=f"ID cible : {target.id}")
    await channel.send(embed=embed)

# ─── EVENTS ──────────────────────────────────────────────────────────────────

@tasks.loop(minutes=5)
async def check_streams():
    """Vérifie toutes les 5 minutes si des membres streament sur Twitch."""
    global live_streamers
    twitch_data = load_twitch()
    if not twitch_data:
        return

    usernames = list(twitch_data.values())
    live_list = await check_twitch_live(usernames)
    currently_live = {s["user_login"].lower() for s in live_list}

    for guild in bot.guilds:
        channel = discord.utils.get(guild.text_channels, name=TWITCH_CHANNEL_NAME)
        if not channel:
            continue

        # Notifier les nouveaux streamers (pas encore annoncés)
        for stream in live_list:
            username = stream["user_login"].lower()
            if username not in live_streamers:
                embed = discord.Embed(
                    title=f"🔴 {stream['user_name']} est en live !",
                    description=f"**{stream['title']}**",
                    color=discord.Color.purple(),
                    url=f"https://twitch.tv/{stream['user_login']}"
                )
                embed.add_field(name="🎮 Jeu", value=stream.get("game_name", "Inconnu"), inline=True)
                embed.add_field(name="👥 Viewers", value=stream.get("viewer_count", 0), inline=True)
                embed.set_footer(text="Twitch • Live maintenant")
                await channel.send(embed=embed)

    # Mettre à jour les streamers en live
    live_streamers = currently_live

@check_streams.before_loop
async def before_check():
    await bot.wait_until_ready()

@bot.event
async def on_ready():
    print(f"✅ Connecté : {bot.user} (ID: {bot.user.id})")
    await bot.change_presence(activity=discord.Game(name="🎮 Gaming Community"))
    check_streams.start()
    try:
        if GUILD_ID:
            guild_obj = discord.Object(id=GUILD_ID)
            bot.tree.copy_global_to(guild=guild_obj)
            synced = await bot.tree.sync(guild=guild_obj)
        else:
            synced = await bot.tree.sync()
        print(f"✅ {len(synced)} commandes slash synchronisées")
    except Exception as e:
        print(f"❌ Erreur sync commandes : {e}")

@bot.event
async def on_member_join(member: discord.Member):
    """Donne le rôle Nouveau et envoie un message de bienvenue."""
    # Auto-rôle
    role = discord.utils.get(member.guild.roles, name="Nouveau")
    if role:
        await member.add_roles(role)

    # Message de bienvenue
    channel = discord.utils.get(member.guild.text_channels, name="bienvenue")
    if channel:
        embed = discord.Embed(
            title=f"👋 Bienvenue {member.display_name} !",
            description=(
                f"Tu es le **{member.guild.member_count}ème** membre du serveur.\n\n"
                "📋 Lis les règles dans **#règles**\n"
                "🎭 Choisis tes rôles dans **#rôles**\n"
                "💬 Présente-toi dans **#général** !"
            ),
            color=discord.Color.green()
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(text=member.guild.name)
        await channel.send(embed=embed)

# Mapping emoji -> rôle pour le canal #rôles (sans dépendre du message ID)
EMOJI_ROLE_MAP = {
    "🎮": "Gamer",
}

@bot.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    """Ajoute un rôle quand un membre réagit dans #rôles."""
    if payload.user_id == bot.user.id:
        return
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    channel = guild.get_channel(payload.channel_id)
    if not channel or channel.name != "rôles":
        return
    emoji = str(payload.emoji)
    role_name = EMOJI_ROLE_MAP.get(emoji)
    if not role_name:
        return
    role = discord.utils.get(guild.roles, name=role_name)
    member = guild.get_member(payload.user_id)
    if role and member and not member.bot:
        await member.add_roles(role)

@bot.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent):
    """Retire un rôle quand un membre enlève sa réaction dans #rôles."""
    guild = bot.get_guild(payload.guild_id)
    if not guild:
        return
    channel = guild.get_channel(payload.channel_id)
    if not channel or channel.name != "rôles":
        return
    emoji = str(payload.emoji)
    role_name = EMOJI_ROLE_MAP.get(emoji)
    if not role_name:
        return
    role = discord.utils.get(guild.roles, name=role_name)
    member = guild.get_member(payload.user_id)
    if role and member:
        await member.remove_roles(role)

# ─── COMMANDES TWITCH ────────────────────────────────────────────────────────

@bot.tree.command(name="addtwitch", description="Enregistre ton pseudo Twitch pour les notifs de live")
@app_commands.describe(pseudo="Ton nom d'utilisateur Twitch")
async def addtwitch(interaction: discord.Interaction, pseudo: str):
    data = load_twitch()
    data[str(interaction.user.id)] = pseudo.lower()
    save_twitch(data)
    embed = discord.Embed(
        description=f"✅ Ton Twitch **{pseudo}** est enregistré ! Le serveur sera notifié quand tu seras en live 🔴",
        color=discord.Color.purple()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="removetwitch", description="Retire ton pseudo Twitch des notifs")
async def removetwitch(interaction: discord.Interaction):
    data = load_twitch()
    uid = str(interaction.user.id)
    if uid in data:
        pseudo = data.pop(uid)
        save_twitch(data)
        await interaction.response.send_message(f"✅ **{pseudo}** retiré des notifs de live.", ephemeral=True)
    else:
        await interaction.response.send_message("❌ Tu n'as pas de Twitch enregistré.", ephemeral=True)

@bot.tree.command(name="liststreamers", description="Voir les streamers enregistrés [MOD]")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def liststreamers(interaction: discord.Interaction):
    data = load_twitch()
    if not data:
        await interaction.response.send_message("Aucun streamer enregistré.", ephemeral=True)
        return
    lines = []
    for uid, username in data.items():
        member = interaction.guild.get_member(int(uid))
        name = member.display_name if member else f"ID:{uid}"
        lines.append(f"🎮 **{name}** → [twitch.tv/{username}](https://twitch.tv/{username})")
    embed = discord.Embed(title="📋 Streamers enregistrés", description="\n".join(lines), color=discord.Color.purple())
    await interaction.response.send_message(embed=embed, ephemeral=True)

# ─── COMMANDES GÉNÉRALES ─────────────────────────────────────────────────────

@bot.tree.command(name="ping", description="Vérifie la latence du bot")
async def ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    color = discord.Color.green() if latency < 100 else discord.Color.orange() if latency < 200 else discord.Color.red()
    embed = discord.Embed(description=f"🏓 **{latency}ms**", color=color)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="info", description="Informations sur le serveur")
async def info(interaction: discord.Interaction):
    guild = interaction.guild
    online = sum(1 for m in guild.members if m.status != discord.Status.offline)
    embed = discord.Embed(
        title=f"🎮 {guild.name}",
        color=discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    embed.add_field(name="👥 Membres", value=f"{guild.member_count} ({online} en ligne)", inline=True)
    embed.add_field(name="📅 Créé le", value=guild.created_at.strftime("%d/%m/%Y"), inline=True)
    embed.add_field(name="📢 Canaux", value=len(guild.channels), inline=True)
    embed.add_field(name="🎭 Rôles", value=len(guild.roles), inline=True)
    embed.add_field(name="😄 Emojis", value=len(guild.emojis), inline=True)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"ID : {guild.id}")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="regles", description="Affiche les règles du serveur")
async def regles(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📋 Règles du serveur",
        color=discord.Color.gold()
    )
    rules = [
        ("Respect", "Aucune insulte, harcèlement ou discrimination tolérée."),
        ("Spam", "Pas de flood, spam ou pub non autorisée."),
        ("NSFW", "Contenu explicite strictement interdit."),
        ("Langue", "Français uniquement dans les canaux généraux."),
        ("Staff", "Les décisions du staff sont finales — ne pas les contester en public."),
        ("Pseudo", "Pseudo lisible et sans caractères spéciaux abusifs."),
    ]
    for i, (title, desc) in enumerate(rules, 1):
        embed.add_field(name=f"{i}. {title}", value=desc, inline=False)
    embed.set_footer(text="Le non-respect des règles entraîne des sanctions pouvant aller jusqu'au ban.")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="Informations sur un membre")
@app_commands.describe(membre="Le membre à inspecter (toi par défaut)")
async def userinfo(interaction: discord.Interaction, membre: discord.Member = None):
    membre = membre or interaction.user
    embed = discord.Embed(
        title=f"👤 {membre}",
        color=membre.color if membre.color != discord.Color.default() else discord.Color.blurple(),
        timestamp=datetime.utcnow()
    )
    embed.set_thumbnail(url=membre.display_avatar.url)
    embed.add_field(name="ID", value=membre.id, inline=True)
    embed.add_field(name="Pseudo", value=membre.display_name, inline=True)
    embed.add_field(name="Bot ?", value="✅" if membre.bot else "❌", inline=True)
    embed.add_field(name="Rejoint le", value=membre.joined_at.strftime("%d/%m/%Y à %H:%M"), inline=True)
    embed.add_field(name="Compte créé", value=membre.created_at.strftime("%d/%m/%Y"), inline=True)
    roles = [r.mention for r in reversed(membre.roles[1:])]  # sans @everyone
    embed.add_field(
        name=f"Rôles ({len(roles)})",
        value=" ".join(roles) if roles else "Aucun",
        inline=False
    )
    await interaction.response.send_message(embed=embed)

# ─── COMMANDES DE MODÉRATION ─────────────────────────────────────────────────

@bot.tree.command(name="ban", description="Bannir un membre [MOD]")
@app_commands.describe(membre="Le membre à bannir", raison="Raison du ban")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def ban(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
    if membre.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ Tu ne peux pas bannir quelqu'un de rang égal ou supérieur.", ephemeral=True)
        return
    try:
        await membre.send(f"🔨 Tu as été banni de **{interaction.guild.name}**.\nRaison : {raison}")
    except Exception:
        pass  # Le DM peut échouer si le membre a les DMs fermés
    await membre.ban(reason=raison, delete_message_days=0)
    embed = discord.Embed(description=f"✅ **{membre}** a été banni.\nRaison : {raison}", color=discord.Color.red())
    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "BAN", interaction.user, membre, raison)

@bot.tree.command(name="kick", description="Expulser un membre [MOD]")
@app_commands.describe(membre="Le membre à expulser", raison="Raison du kick")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def kick(interaction: discord.Interaction, membre: discord.Member, raison: str = "Aucune raison fournie"):
    if membre.top_role >= interaction.user.top_role:
        await interaction.response.send_message("❌ Tu ne peux pas expulser quelqu'un de rang égal ou supérieur.", ephemeral=True)
        return
    try:
        await membre.send(f"👢 Tu as été expulsé de **{interaction.guild.name}**.\nRaison : {raison}")
    except Exception:
        pass
    await membre.kick(reason=raison)
    embed = discord.Embed(description=f"✅ **{membre}** a été expulsé.\nRaison : {raison}", color=discord.Color.orange())
    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "KICK", interaction.user, membre, raison)

@bot.tree.command(name="mute", description="Mettre un membre en timeout [MOD]")
@app_commands.describe(membre="Le membre à muter", duree="Durée en minutes (défaut : 10)", raison="Raison")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def mute(interaction: discord.Interaction, membre: discord.Member, duree: int = 10, raison: str = "Aucune raison fournie"):
    if duree < 1 or duree > 40320:  # max 28 jours
        await interaction.response.send_message("❌ Durée entre 1 minute et 28 jours (40 320 min).", ephemeral=True)
        return
    until = discord.utils.utcnow() + timedelta(minutes=duree)
    await membre.timeout(until, reason=raison)
    embed = discord.Embed(
        description=f"🔇 **{membre}** muté pendant **{duree} min**.\nRaison : {raison}",
        color=discord.Color.greyple()
    )
    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, f"MUTE ({duree}min)", interaction.user, membre, raison)

@bot.tree.command(name="unmute", description="Retirer le timeout d'un membre [MOD]")
@app_commands.describe(membre="Le membre à démuter")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def unmute(interaction: discord.Interaction, membre: discord.Member):
    await membre.timeout(None)
    embed = discord.Embed(description=f"🔊 **{membre}** n'est plus muté.", color=discord.Color.green())
    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, "UNMUTE", interaction.user, membre)

@bot.tree.command(name="warn", description="Avertir un membre [MOD]")
@app_commands.describe(membre="Le membre à avertir", raison="Raison de l'avertissement")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def warn(interaction: discord.Interaction, membre: discord.Member, raison: str):
    warnings = load_warnings()
    uid = str(membre.id)
    if uid not in warnings:
        warnings[uid] = []
    warnings[uid].append({
        "raison": raison,
        "date": datetime.utcnow().strftime("%Y-%m-%d %H:%M"),
        "par": str(interaction.user)
    })
    save_warnings(warnings)
    count = len(warnings[uid])
    embed = discord.Embed(
        description=f"⚠️ **{membre}** a reçu un avertissement (**{count}** au total).\nRaison : {raison}",
        color=discord.Color.yellow()
    )
    await interaction.response.send_message(embed=embed)
    await log_action(interaction.guild, f"WARN (total: {count})", interaction.user, membre, raison)

@bot.tree.command(name="warns", description="Voir les avertissements d'un membre [MOD]")
@app_commands.describe(membre="Le membre à vérifier")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def warns(interaction: discord.Interaction, membre: discord.Member):
    warnings = load_warnings()
    user_warns = warnings.get(str(membre.id), [])
    if not user_warns:
        await interaction.response.send_message(f"✅ **{membre}** n'a aucun avertissement.", ephemeral=True)
        return
    embed = discord.Embed(
        title=f"⚠️ Avertissements de {membre}",
        color=discord.Color.orange()
    )
    for i, w in enumerate(user_warns, 1):
        embed.add_field(name=f"#{i} — {w['date']}", value=f"{w['raison']} *(par {w['par']})*", inline=False)
    embed.set_footer(text=f"Total : {len(user_warns)} avertissement(s)")
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="clearwarns", description="Effacer les avertissements d'un membre [ADMIN]")
@app_commands.describe(membre="Le membre dont effacer les warns")
@app_commands.checks.has_role("Admin")
async def clearwarns(interaction: discord.Interaction, membre: discord.Member):
    warnings = load_warnings()
    uid = str(membre.id)
    count = len(warnings.get(uid, []))
    warnings.pop(uid, None)
    save_warnings(warnings)
    await interaction.response.send_message(f"🗑️ **{count}** avertissement(s) de **{membre}** supprimés.", ephemeral=True)

@bot.tree.command(name="clear", description="Supprimer des messages dans le canal [MOD]")
@app_commands.describe(nombre="Nombre de messages à supprimer (1 à 100)")
@app_commands.checks.has_any_role("Admin", "Modérateur")
async def clear(interaction: discord.Interaction, nombre: int):
    if not 1 <= nombre <= 100:
        await interaction.response.send_message("❌ Nombre entre 1 et 100.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=nombre)
    await interaction.followup.send(f"🗑️ **{len(deleted)}** message(s) supprimé(s).", ephemeral=True)

# ─── RÔLES PAR RÉACTION ──────────────────────────────────────────────────────

@bot.tree.command(name="setup_reaction_roles", description="Créer le message de rôles par réaction [ADMIN]")
@app_commands.checks.has_role("Admin")
async def setup_reaction_roles(interaction: discord.Interaction):
    """
    Envoie le message de réaction-rôles dans le canal courant.
    Les rôles 'Gamer' et 'VIP' doivent exister sur le serveur.
    """
    embed = discord.Embed(
        title="🎭 Choisis tes rôles",
        description=(
            "Réagis pour obtenir ton rôle automatiquement :\n\n"
            "🎮 → **Gamer** — accès aux canaux gaming\n\n"
            "*Clique à nouveau pour retirer le rôle.*"
        ),
        color=discord.Color.purple()
    )
    await interaction.response.send_message("✅ Message de rôles envoyé.", ephemeral=True)
    msg = await interaction.channel.send(embed=embed)
    await msg.add_reaction("🎮")

    # Enregistrement en mémoire
    REACTION_ROLES[str(msg.id)] = {
        "🎮": "Gamer",
    }

    # Afficher l'ID pour sauvegarde manuelle
    print(f"\n⚠️  REACTION ROLES — Message ID : {msg.id}")
    print("   Ajoute ceci dans REACTION_ROLES au début du fichier pour persister après redémarrage :")
    print(f'   REACTION_ROLES = {{"{msg.id}": {{"🎮": "Gamer", "⭐": "VIP"}}}}')
    print()

# ─── GESTION DES ERREURS ─────────────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingAnyRole):
        await interaction.response.send_message("❌ Tu n'as pas les permissions nécessaires.", ephemeral=True)
    elif isinstance(error, app_commands.MissingRole):
        await interaction.response.send_message("❌ Cette commande est réservée aux admins.", ephemeral=True)
    elif isinstance(error, app_commands.BotMissingPermissions):
        await interaction.response.send_message("❌ Je n'ai pas les permissions nécessaires sur ce serveur.", ephemeral=True)
    else:
        print(f"Erreur commande slash : {error}")
        if not interaction.response.is_done():
            await interaction.response.send_message(f"❌ Erreur inattendue : `{error}`", ephemeral=True)

# ─── LANCEMENT ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    bot.run(TOKEN)
