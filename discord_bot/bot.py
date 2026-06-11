import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
import urllib.request
import urllib.parse
import time
import database
import json
import asyncio
import sys
import io

# Force UTF-8 encoding for stdout/stderr to prevent Windows charmap print crashes
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Load environment variables
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True
intents.members = True

class CustomBot(commands.Bot):
    async def close(self):
        print("Bot is shutting down. Cleaning up setup and temporary channels...")
        for guild in self.guilds:
            setup_channel = discord.utils.get(guild.text_channels, name="➕-создать-комнату")
            if setup_channel:
                try:
                    await setup_channel.delete()
                    print(f"Deleted setup channel in {guild.name}")
                except Exception as e:
                    print(f"Failed to delete setup channel in {guild.name}: {e}")
            
            # Delete any active temporary voice channels
            for chan_id in list(temp_channels.keys()):
                chan = self.get_channel(chan_id)
                if chan:
                    try:
                        await chan.delete()
                        print(f"Deleted temporary channel: {chan.name}")
                    except Exception:
                        pass
        temp_channels.clear()
        await super().close()

bot = CustomBot(command_prefix="!", intents=intents)

import json

# Dictionary to keep track of dynamic channels: {channel_id: owner_id}
temp_channels = {}
# Whitelist memory dictionary: {owner_id: set(friend_ids)}
whitelists = {}
# Voice start times cache for dynamic tracking: {(guild_id, user_id): start_time}
voice_start_times = {}

WHITELIST_FILE = "whitelist.json"

def load_whitelist():
    global whitelists
    if os.path.exists(WHITELIST_FILE):
        try:
            with open(WHITELIST_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Convert keys back to int, and values back to set of ints
                whitelists = {int(k): set(int(v) for v in vs) for k, vs in data.items()}
                print("Loaded whitelists from file.")
        except Exception as e:
            print(f"Error loading whitelist: {e}")
            whitelists = {}
    else:
        whitelists = {}

def save_whitelist():
    try:
        with open(WHITELIST_FILE, "w", encoding="utf-8") as f:
            # Convert keys and values to serializable types
            data = {str(k): list(vs) for k, vs in whitelists.items()}
            json.dump(data, f, indent=4, ensure_ascii=False)
            print("Saved whitelists to file.")
    except Exception as e:
        print(f"Error saving whitelist: {e}")

# Load the whitelist immediately on start
load_whitelist()

# Helper for localizing text
def get_txt(ru: str, en: str, is_russian: bool) -> str:
    return ru if is_russian else en

# --- Modals ---
class RenameModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        title = get_txt("Переименовать канал", "Rename Channel", is_russian)
        super().__init__(title=title)
        self.channel = channel
        self.is_russian = is_russian

        self.channel_name = discord.ui.TextInput(
            label=get_txt("Новое название", "New Name", is_russian),
            placeholder=get_txt("Например: Комната MyPvP", "e.g. MyPvP Room", is_russian),
            min_length=1,
            max_length=100,
            required=True
        )
        self.add_item(self.channel_name)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await self.channel.edit(name=self.channel_name.value)
            msg = get_txt(
                f"✅ Канал переименован в: **{self.channel_name.value}**",
                f"✅ Channel renamed to: **{self.channel_name.value}**",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            msg = get_txt(
                f"❌ Не удалось изменить название: {e}",
                f"❌ Failed to rename channel: {e}",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


class LimitModal(discord.ui.Modal):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        title = get_txt("Лимит участников", "User Limit", is_russian)
        super().__init__(title=title)
        self.channel = channel
        self.is_russian = is_russian

        self.user_limit = discord.ui.TextInput(
            label=get_txt("Количество мест (0 - без лимита)", "User capacity (0 = no limit)", is_russian),
            placeholder=get_txt("Например: 5", "e.g. 5", is_russian),
            min_length=1,
            max_length=2,
            required=True
        )
        self.add_item(self.user_limit)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            val = int(self.user_limit.value)
            if 0 <= val <= 99:
                await self.channel.edit(user_limit=val)
                limit_text = get_txt("без лимита", "no limit", self.is_russian) if val == 0 else get_txt(f"{val} участников", f"{val} users", self.is_russian)
                msg = get_txt(
                    f"✅ Установлен лимит: **{limit_text}**",
                    f"✅ Limit set to: **{limit_text}**",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
            else:
                msg = get_txt(
                    "❌ Укажите число от 0 до 99.",
                    "❌ Enter a number between 0 and 99.",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
        except ValueError:
            msg = get_txt(
                "❌ Пожалуйста, введите корректное число.",
                "❌ Please enter a valid number.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            msg = get_txt(
                f"❌ Не удалось изменить лимит: {e}",
                f"❌ Failed to set limit: {e}",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


# --- Dropdown Select Menus ---
class KickSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Выберите кого выгнать...", "Choose who to kick...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        kicked_mentions = []
        failed_mentions = []

        for member in self.values:
            if not isinstance(member, discord.Member):
                continue
            
            # Security check
            if member.guild_permissions.administrator or member.id == interaction.guild.owner_id or member.top_role >= interaction.user.top_role:
                failed_mentions.append(member.display_name)
                continue

            if member.voice and member.voice.channel == self.channel:
                try:
                    await member.move_to(None)
                    kicked_mentions.append(member.mention)
                except Exception:
                    failed_mentions.append(member.display_name)
            else:
                failed_mentions.append(member.display_name)

        msgs = []
        if kicked_mentions:
            msgs.append(get_txt(
                f"✅ Выгнаны из канала: {', '.join(kicked_mentions)}",
                f"✅ Kicked from channel: {', '.join(kicked_mentions)}",
                self.is_russian
            ))
        if failed_mentions:
            msgs.append(get_txt(
                f"❌ Не удалось выгнать (или нет в канале/превышены права): {', '.join(failed_mentions)}",
                f"❌ Failed to kick (or not in channel/higher role): {', '.join(failed_mentions)}",
                self.is_russian
            ))

        await interaction.response.send_message("\n".join(msgs), ephemeral=True)


class MuteSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Выберите кого мут/размут...", "Mute/unmute users...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        muted_mentions = []
        unmuted_mentions = []
        failed_mentions = []

        for member in self.values:
            if not isinstance(member, discord.Member):
                continue

            # Security check
            if member.guild_permissions.administrator or member.id == interaction.guild.owner_id or member.top_role >= interaction.user.top_role:
                failed_mentions.append(member.display_name)
                continue

            if member.voice and member.voice.channel == self.channel:
                try:
                    current_mute = member.voice.mute
                    await member.edit(mute=not current_mute)
                    if not current_mute:
                        muted_mentions.append(member.mention)
                    else:
                        unmuted_mentions.append(member.mention)
                except Exception:
                    failed_mentions.append(member.display_name)
            else:
                failed_mentions.append(member.display_name)

        msgs = []
        if muted_mentions:
            msgs.append(get_txt(
                f"🔇 Заглушены: {', '.join(muted_mentions)}",
                f"🔇 Muted: {', '.join(muted_mentions)}",
                self.is_russian
            ))
        if unmuted_mentions:
            msgs.append(get_txt(
                f"🔊 Разглушены: {', '.join(unmuted_mentions)}",
                f"🔊 Unmuted: {', '.join(unmuted_mentions)}",
                self.is_russian
            ))
        if failed_mentions:
            msgs.append(get_txt(
                f"❌ Не удалось заглушить/разглушить (или не в канале/превышены права): {', '.join(failed_mentions)}",
                f"❌ Failed to mute/unmute (or not in channel/higher role): {', '.join(failed_mentions)}",
                self.is_russian
            ))

        await interaction.response.send_message("\n".join(msgs), ephemeral=True)


class InviteSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Выберите кого пригласить...", "Select users to invite...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        invited_mentions = []
        failed_mentions = []

        for member in self.values:
            if not isinstance(member, discord.Member):
                continue

            try:
                overwrite = self.channel.overwrites_for(member)
                overwrite.connect = True
                overwrite.view_channel = True
                await self.channel.set_permissions(member, overwrite=overwrite)
                
                # Generate a temporary invite link
                try:
                    invite = await self.channel.create_invite(max_age=300, max_uses=1)
                    invite_url = invite.url
                except Exception:
                    invite_url = None

                invited_mentions.append(member.mention)

                try:
                    link_ru = f"\n👉 Ссылка для входа: {invite_url}" if invite_url else ""
                    link_en = f"\n👉 Join link: {invite_url}" if invite_url else ""
                    dm_msg = get_txt(
                        f"✉️ Вас пригласили в приватный голосовой канал **{self.channel.name}** на сервере **{interaction.guild.name}**!{link_ru}",
                        f"✉️ You have been invited to a private voice channel **{self.channel.name}** on server **{interaction.guild.name}**!{link_en}",
                        self.is_russian
                    )
                    await member.send(dm_msg)
                except Exception:
                    pass
            except Exception:
                failed_mentions.append(member.display_name)

        msgs = []
        if invited_mentions:
            msgs.append(get_txt(
                f"✅ Успешно приглашены: {', '.join(invited_mentions)}",
                f"✅ Successfully invited: {', '.join(invited_mentions)}",
                self.is_russian
            ))
        if failed_mentions:
            msgs.append(get_txt(
                f"❌ Не удалось выдать права/пригласить: {', '.join(failed_mentions)}",
                f"❌ Failed to invite: {', '.join(failed_mentions)}",
                self.is_russian
            ))

        await interaction.response.send_message("\n".join(msgs), ephemeral=True)


class AddFriendSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Добавить друзей в вайт-лист...", "Add friends to whitelist...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        owner_id = interaction.user.id
        if owner_id not in whitelists:
            whitelists[owner_id] = set()

        added_mentions = []
        for member in self.values:
            if not isinstance(member, discord.Member):
                continue
            if member.id == owner_id:
                continue

            whitelists[owner_id].add(member.id)
            added_mentions.append(member.mention)

            try:
                overwrite = self.channel.overwrites_for(member)
                overwrite.connect = True
                overwrite.view_channel = True
                await self.channel.set_permissions(member, overwrite=overwrite)
            except Exception:
                pass

        if added_mentions:
            save_whitelist()
            msg = get_txt(
                f"✅ Добавлены в вайт-лист: {', '.join(added_mentions)}",
                f"✅ Added to whitelist: {', '.join(added_mentions)}",
                self.is_russian
            )
        else:
            msg = get_txt(
                "❌ Ни один пользователь не был добавлен (нельзя добавить себя).",
                "❌ No users were added (you cannot add yourself).",
                self.is_russian
            )
        await interaction.response.send_message(msg, ephemeral=True)


class RemoveFriendSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Удалить друзей из вайт-листа...", "Remove friends from whitelist...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=25)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        owner_id = interaction.user.id
        owner_whitelist = whitelists.get(owner_id, set())

        removed_mentions = []
        for member in self.values:
            if not isinstance(member, discord.Member):
                continue

            # Remove from whitelist if present
            if member.id in owner_whitelist:
                owner_whitelist.remove(member.id)

            # Explicitly deny channel access (Blacklist)
            try:
                overwrite = self.channel.overwrites_for(member)
                overwrite.connect = False
                overwrite.view_channel = False
                await self.channel.set_permissions(member, overwrite=overwrite)
                
                # Kick them from the voice channel immediately if they are in it
                if member.voice and member.voice.channel == self.channel:
                    await member.move_to(None)
                
                removed_mentions.append(member.mention)
            except Exception:
                pass

        if removed_mentions:
            save_whitelist()
            msg = get_txt(
                f"✅ Заблокированы в канале и удалены из вайт-листа: {', '.join(removed_mentions)}",
                f"✅ Blocked from the channel and removed from whitelist: {', '.join(removed_mentions)}",
                self.is_russian
            )
        else:
            msg = get_txt(
                "❌ Ни один пользователь не был удален/заблокирован.",
                "❌ No users were removed/blocked.",
                self.is_russian
            )
        await interaction.response.send_message(msg, ephemeral=True)


# --- Dropdown Views ---
class DropdownView(discord.ui.View):
    def __init__(self, select_item):
        super().__init__(timeout=60)
        self.add_item(select_item)


# --- Channel Control Panel (GUI inside channel text chat) ---
class VoiceControlView(discord.ui.View):
    def __init__(self, channel: discord.VoiceChannel, owner: discord.Member, is_russian: bool):
        super().__init__(timeout=None)
        self.channel = channel
        self.owner = owner
        self.is_russian = is_russian
        self.locked = False
        self.hidden = False

        # Set button labels dynamically based on owner's locale
        self.rename_btn.label = get_txt("📝 Имя", "📝 Rename", is_russian)
        self.lock_btn.label = get_txt("🔒 Закрыть/Открыть", "🔒 Lock/Unlock", is_russian)
        self.hide_btn.label = get_txt("👁️ Скрыть/Показать", "👁️ Hide/Show", is_russian)
        self.limit_btn.label = get_txt("👥 Лимит", "👥 Limit", is_russian)
        self.kick_btn.label = get_txt("🚫 Выгнать", "🚫 Kick", is_russian)
        self.mute_btn.label = get_txt("🔇 Мут/Размут", "🔇 Mute/Unmute", is_russian)
        self.invite_btn.label = get_txt("📩 Пригласить", "📩 Invite", is_russian)
        self.add_friend_btn.label = get_txt("➕ Друг", "➕ Add Friend", is_russian)
        self.remove_friend_btn.label = get_txt("➖ Друг", "➖ Remove Friend", is_russian)

    async def check_owner_or_claim(self, interaction: discord.Interaction) -> bool:
        current_owner_id = temp_channels.get(self.channel.id)
        if current_owner_id == interaction.user.id:
            return True
        return False

    @discord.ui.button(style=discord.ButtonStyle.primary, custom_id="vc_rename", row=0)
    async def rename_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_modal(RenameModal(self.channel, self.is_russian))

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_lock", row=0)
    async def lock_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        self.locked = not self.locked
        overwrite = self.channel.overwrites_for(interaction.guild.default_role)
        overwrite.connect = False if self.locked else None
        
        try:
            await self.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            status = get_txt("закрыт 🔒", "locked 🔒", self.is_russian) if self.locked else get_txt("открыт 🔓", "unlocked 🔓", self.is_russian)
            msg = get_txt(
                f"✅ Канал теперь **{status}** для всех.",
                f"✅ Channel is now **{status}** for everyone.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            msg = get_txt(
                f"❌ Не удалось изменить доступ: {e}",
                f"❌ Failed to edit access: {e}",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.secondary, custom_id="vc_hide", row=0)
    async def hide_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        self.hidden = not self.hidden
        overwrite = self.channel.overwrites_for(interaction.guild.default_role)
        if self.hidden:
            overwrite.view_channel = False
            overwrite.connect = False
        else:
            overwrite.view_channel = None
            overwrite.connect = None
        
        try:
            await self.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            status = get_txt("скрыт 👁️‍🗨️", "hidden 👁️‍🗨️", self.is_russian) if self.hidden else get_txt("видим 👁️", "visible 👁️", self.is_russian)
            msg = get_txt(
                f"✅ Канал теперь **{status}** для всех.",
                f"✅ Channel is now **{status}** for everyone.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
        except Exception as e:
            msg = get_txt(
                f"❌ Не удалось настроить видимость: {e}",
                f"❌ Failed to change visibility: {e}",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="vc_limit", row=0)
    async def limit_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        await interaction.response.send_modal(LimitModal(self.channel, self.is_russian))

    @discord.ui.button(style=discord.ButtonStyle.danger, custom_id="vc_kick", row=1)
    async def kick_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        view = DropdownView(KickSelect(self.channel, self.is_russian))
        msg = get_txt("Выберите пользователя, которого хотите отключить:", "Choose user to disconnect:", self.is_russian)
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.danger, custom_id="vc_mute", row=1)
    async def mute_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        view = DropdownView(MuteSelect(self.channel, self.is_russian))
        msg = get_txt("Выберите пользователя, чтобы переключить его микрофон:", "Choose user to toggle mic:", self.is_russian)
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="vc_invite", row=1)
    async def invite_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        view = DropdownView(InviteSelect(self.channel, self.is_russian))
        msg = get_txt("Выберите пользователя, которому хотите дать доступ:", "Choose user to grant access:", self.is_russian)
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.success, custom_id="vc_add_friend", row=1)
    async def add_friend_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        view = DropdownView(AddFriendSelect(self.channel, self.is_russian))
        msg = get_txt("Выберите пользователя, которого хотите добавить в вайт-лист:", "Choose user to add to whitelist:", self.is_russian)
        await interaction.response.send_message(msg, view=view, ephemeral=True)

    @discord.ui.button(style=discord.ButtonStyle.danger, custom_id="vc_remove_friend", row=1)
    async def remove_friend_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await self.check_owner_or_claim(interaction):
            msg = get_txt("❌ Вы не владелец этого канала!", "❌ You are not the owner of this channel!", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        view = DropdownView(RemoveFriendSelect(self.channel, self.is_russian))
        msg = get_txt("Выберите пользователя, которого хотите удалить из вайт-листа:", "Choose user to remove from whitelist:", self.is_russian)
        await interaction.response.send_message(msg, view=view, ephemeral=True)


# Shared helper to create voice channels
async def create_voice_channel_helper(interaction: discord.Interaction, member: discord.Member, guild: discord.Guild, category):
    is_russian = (interaction.locale == discord.Locale.russian)
    
    # Self-healing: Clean up any stale manually deleted channels for this user
    stale_channels = []
    for chan_id, owner_id in list(temp_channels.items()):
        if owner_id == member.id:
            exist_channel = guild.get_channel(chan_id)
            if not exist_channel:
                stale_channels.append(chan_id)
    for chan_id in stale_channels:
        temp_channels.pop(chan_id, None)

    # Check if user already owns an active temporary channel
    if member.id in temp_channels.values():
        msg = get_txt(
            "❌ Вы уже являетесь владельцем активного голосового канала!",
            "❌ You already own an active voice channel!",
            is_russian
        )
        await interaction.response.send_message(msg, ephemeral=True)
        return

    try:
        channel_name = f"🔊 {member.display_name}"
        new_channel = await guild.create_voice_channel(
            name=channel_name,
            category=category
        )
        
        temp_channels[new_channel.id] = member.id
        
        # Apply whitelisted friends overwrites
        owner_whitelist = whitelists.get(member.id, set())
        for friend_id in owner_whitelist:
            friend_member = guild.get_member(friend_id)
            if friend_member:
                try:
                    overwrite = new_channel.overwrites_for(friend_member)
                    overwrite.connect = True
                    overwrite.view_channel = True
                    await new_channel.set_permissions(friend_member, overwrite=overwrite)
                except Exception:
                    pass
        
        moved_status = get_txt(
            " и вы были перемещены туда!",
            " and you have been moved there!",
            is_russian
        ) if member.voice and member.voice.channel else get_txt(
            ". Подключитесь самостоятельно.",
            ". Join it manually.",
            is_russian
        )

        success_msg = get_txt(
            f"✅ Канал {new_channel.mention} создан{moved_status}",
            f"✅ Channel {new_channel.mention} created{moved_status}",
            is_russian
        )

        await interaction.response.send_message(success_msg, ephemeral=True)

        # Control Panel Embed
        embed_title = get_txt(
            f"Панель управления комнаты: {member.display_name}",
            f"Room Control Panel: {member.display_name}",
            is_russian
        )
        
        description_ru = (
            "Используйте кнопки ниже для управления голосовым каналом:\n\n"
            "📝 **Имя** — Изменить имя комнаты\n"
            "🔒 **Закрыть/Открыть** — Запретить/разрешить вход другим\n"
            "👁️ **Скрыть/Показать** — Спрятать комнату из общего списка\n"
            "👥 **Лимит** — Настроить количество мест\n"
            "🚫 **Выгнать** — Отключить любого пользователя\n"
            "🔇 **Мут/Размут** — Выключить микрофон игроку\n"
            "📩 **Пригласить** — Дать персональный доступ в закрытую комнату"
        )
        
        description_en = (
            "Use the buttons below to manage your voice channel:\n\n"
            "📝 **Rename** — Change channel name\n"
            "🔒 **Lock/Unlock** — Toggle join access for everyone\n"
            "👁️ **Hide/Show** — Hide room from list\n"
            "👥 **Limit** — Change player capacity limit\n"
            "🚫 **Kick** — Disconnect a user from the channel\n"
            "🔇 **Mute/Unmute** — Server-mute/unmute a user's mic\n"
            "📩 **Invite** — Grant personal access to private channel"
        )

        embed = discord.Embed(
            title=embed_title,
            description=get_txt(description_ru, description_en, is_russian),
            color=discord.Color.blue()
        )
        
        content_msg = get_txt(
            f"{member.mention}, вот dynamic панель управления:",
            f"{member.mention}, here is your control panel:",
            is_russian
        )
        
        await new_channel.send(
            content=content_msg,
            embed=embed,
            view=VoiceControlView(new_channel, member, is_russian)
        )

    except Exception as e:
        err_msg = get_txt(
            f"❌ Не удалось создать канал: {e}",
            f"❌ Failed to create channel: {e}",
            is_russian
        )
        await interaction.response.send_message(err_msg, ephemeral=True)


# --- Main Persistent Creation Panel ---
class VoiceCreatorView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="➕ Создать канал / Create Voice", style=discord.ButtonStyle.success, custom_id="create_voice_btn")
    async def create_voice(self, interaction: discord.Interaction, button: discord.ui.Button):
        guild = interaction.guild
        member = interaction.user
        category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
        await create_voice_channel_helper(interaction, member, guild, category)


# --- Auto-setup Channel helper ---
async def auto_create_setup_channel(guild: discord.Guild):
    channel_name = "➕-создать-комнату"
    
    # Check if channel already exists
    channel = discord.utils.get(guild.text_channels, name=channel_name)
    
    if not channel:
        try:
            # Overwrites: read and view is allowed, sending messages is locked for everyone
            overwrites = {
                guild.default_role: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=False,
                    read_message_history=True
                ),
                guild.me: discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    manage_channels=True,
                    manage_messages=True
                )
            }
            channel = await guild.create_text_channel(name=channel_name, overwrites=overwrites)
            print(f"Created setup channel in guild: {guild.name}")
        except Exception as e:
            print(f"Failed to create setup channel in guild {guild.name}: {e}")
            return

    # Clear old messages and post the fresh GUI panel
    try:
        await channel.purge(limit=10)
        embed = discord.Embed(
            title="🎙️ Создание приватных комнат MyPvP / Private Room Creation",
            description=(
                "Нажмите кнопку ниже, чтобы создать временный голосовой канал.\n"
                "Вы станете его владельцем и сможете полностью его настраивать.\n\n"
                "Press the button below to create a temporary voice channel.\n"
                "You will become the owner and can fully customize it using the control panel."
            ),
            color=discord.Color.purple()
        )
        await channel.send(embed=embed, view=VoiceCreatorView())
    except Exception as e:
        print(f"Failed to send panel in guild {guild.name}: {e}")


# --- Slash Command Groups ---
class SetupGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="setup", description="Setup commands / Настройка бота")

    @app_commands.command(name="voice", description="Setup private rooms panel / Настройка панели комнат")
    @app_commands.checks.has_permissions(administrator=True)
    async def voice(self, interaction: discord.Interaction):
        # Allow manually triggering setup channel setup
        await auto_create_setup_channel(interaction.guild)
        is_russian = (interaction.locale == discord.Locale.russian)
        success_msg = get_txt("✅ Канал настройки успешно создан/обновлен!", "✅ Setup channel successfully created/updated!", is_russian)
        await interaction.response.send_message(success_msg, ephemeral=True)

    @voice.error
    async def voice_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.errors.MissingPermissions):
            is_russian = (interaction.locale == discord.Locale.russian)
            msg = get_txt(
                "❌ Недостаточно прав для команды (нужен Администратор).",
                "❌ Insufficient permissions (Administrator required).",
                is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


class CreateRuGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="создать", description="Создать голосовой канал")

    @app_commands.command(name="войс", description="Создать временный голосовой канал")
    async def voice(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
        await create_voice_channel_helper(interaction, member, guild, category)


class CreateEnGroup(app_commands.Group):
    def __init__(self):
        super().__init__(name="create", description="Create voice channel")

    @app_commands.command(name="voice", description="Create temporary voice channel")
    async def voice(self, interaction: discord.Interaction):
        guild = interaction.guild
        member = interaction.user
        category = interaction.channel.category if isinstance(interaction.channel, discord.TextChannel) else None
        await create_voice_channel_helper(interaction, member, guild, category)


# Register slash command groups at module level
bot.tree.add_command(SetupGroup())
bot.tree.add_command(CreateRuGroup())
bot.tree.add_command(CreateEnGroup())

@bot.tree.command(name="stats", description="Link to the server statistics dashboard / Ссылка на статистику сервера")
async def stats_command(interaction: discord.Interaction):
    is_russian = (interaction.locale == discord.Locale.russian)
    
    web_url = os.getenv("RENDER_EXTERNAL_URL")
    if not web_url:
        web_url = "http://localhost:8080"
        
    full_url = f"{web_url}/?guild_id={interaction.guild.id}" if interaction.guild else web_url
    
    title = get_txt("📈 Статистика сервера", "📈 Server Statistics", is_russian)
    desc_ru = (
        f"Посмотреть рейтинг активности участников, топ в голосовых каналах и чатах "
        f"можно на нашем сайте:\n\n"
        f"👉 **[Открыть панель статистики]({full_url})**"
    )
    desc_en = (
        f"You can view the member activity leaderboard, top voice, and chat stats "
        f"on our dashboard website:\n\n"
        f"👉 **[Open Statistics Dashboard]({full_url})**"
    )
    
    embed = discord.Embed(
        title=title,
        description=get_txt(desc_ru, desc_en, is_russian),
        color=discord.Color.blurple()
    )
    if interaction.guild and interaction.guild.icon:
        embed.set_thumbnail(url=interaction.guild.icon.url)
        
    await interaction.response.send_message(embed=embed, ephemeral=True)

async def run_full_history_sync(interaction: discord.Interaction, guild: discord.Guild, is_ru: bool):
    try:
        msg_start = get_txt(
            "⏳ Начинается полная синхронизация истории сообщений. Это может занять некоторое время...",
            "⏳ Starting full message history synchronization. This may take some time...",
            is_ru
        )
        await interaction.followup.send(msg_start, ephemeral=True)
        
        # 1. Reset message counts
        await asyncio.to_thread(database.reset_messages_count, guild.id)
        
        # 2. Sync members
        print(f"Syncing members before full crawl: {guild.name}...")
        async for member in guild.fetch_members(limit=None):
            if member.bot:
                continue
            await asyncio.to_thread(
                database.sync_member,
                guild.id,
                member.id,
                member.name,
                member.global_name or member.name,
                str(member.display_avatar.url)
            )
            
        # 3. Crawl history of all visible channels
        total_channels = 0
        total_messages = 0
        
        for channel in guild.text_channels:
            perms = channel.permissions_for(guild.me)
            if not perms.read_message_history or not perms.read_messages:
                continue
            
            total_channels += 1
            print(f"Full sync crawling: {channel.name}...")
            try:
                async for msg in channel.history(limit=None):
                    if msg.author.bot:
                        continue
                    
                    await asyncio.to_thread(
                        database.update_message_count,
                        guild.id,
                        msg.author.id,
                        msg.author.name,
                        msg.author.global_name or msg.author.name,
                        str(msg.author.display_avatar.url),
                        1
                    )
                    total_messages += 1
            except Exception as e:
                print(f"Error crawling history in {channel.name}: {e}")
                
        msg_end = get_txt(
            f"✅ Синхронизация завершена!\n"
            f"Успешно просканировано текстовых каналов: **{total_channels}**\n"
            f"Всего обработано сообщений: **{total_messages}**",
            f"✅ Synchronization completed!\n"
            f"Successfully scanned text channels: **{total_channels}**\n"
            f"Total messages processed: **{total_messages}**",
            is_ru
        )
        await interaction.followup.send(msg_end, ephemeral=True)
        
        # Mark guild as synced so startup crawls bypass it
        mark_guild_synced(guild.id)
        
    except Exception as e:
        print(f"Error in run_full_history_sync: {e}")
        err_msg = get_txt(
            f"❌ Произошла ошибка во время синхронизации: {e}",
            f"❌ An error occurred during synchronization: {e}",
            is_ru
        )
        try:
            await interaction.followup.send(err_msg, ephemeral=True)
        except Exception:
            pass

@bot.tree.command(name="sync-history", description="Full sync of message history for accurate stats / Полная синхронизация истории")
@app_commands.checks.has_permissions(administrator=True)
async def sync_history_command(interaction: discord.Interaction):
    # Defer since crawling history takes longer than 3 seconds
    await interaction.response.defer(ephemeral=True)
    
    guild = interaction.guild
    is_ru = (interaction.locale == discord.Locale.russian)
    
    if not guild:
        msg = get_txt("❌ Эта команда может быть запущена только на сервере.", "❌ This command can only be run on a server.", is_ru)
        await interaction.followup.send(msg, ephemeral=True)
        return
        
    bot.loop.create_task(run_full_history_sync(interaction, guild, is_ru))

@sync_history_command.error
async def sync_history_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.errors.MissingPermissions):
        is_ru = (interaction.locale == discord.Locale.russian)
        msg = get_txt(
            "❌ Недостаточно прав для команды (нужен Администратор).",
            "❌ Insufficient permissions (Administrator required).",
            is_ru
        )
        await interaction.response.send_message(msg, ephemeral=True)


# --- Events ---
SYNC_FLAG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "synced_flags")

def is_guild_synced(guild_id):
    os.makedirs(SYNC_FLAG_DIR, exist_ok=True)
    return os.path.exists(os.path.join(SYNC_FLAG_DIR, f"{guild_id}.flag"))

def mark_guild_synced(guild_id):
    os.makedirs(SYNC_FLAG_DIR, exist_ok=True)
    with open(os.path.join(SYNC_FLAG_DIR, f"{guild_id}.flag"), "w") as f:
        f.write("synced")

async def sync_and_crawl_history():
    await bot.wait_until_ready()
    # Initialize DB
    await asyncio.to_thread(database.init_db)
    
    for guild in bot.guilds:
        try:
            # 1. Sync member list and profiles
            print(f"Syncing members for guild: {guild.name} ({guild.id})...")
            async for member in guild.fetch_members(limit=None):
                if member.bot:
                    continue
                await asyncio.to_thread(
                    database.sync_member,
                    guild.id,
                    member.id,
                    member.name,
                    member.global_name or member.name,
                    str(member.display_avatar.url)
                )

            # 2. Track already active voice users on start
            for voice_channel in guild.voice_channels:
                for member in voice_channel.members:
                    if member.bot:
                        continue
                    voice_key = (guild.id, member.id)
                    if voice_key not in voice_start_times:
                        voice_start_times[voice_key] = time.time()
                        print(f"Registered initial voice timer for {member.name} in {voice_channel.name}")

            # 3. Message crawl (seed stats from history)
            if not is_guild_synced(guild.id):
                print(f"Crawling message history for guild: {guild.name} to seed database...")
                total_crawled = 0
                for channel in guild.text_channels:
                    perms = channel.permissions_for(guild.me)
                    if not perms.read_message_history or not perms.read_messages:
                        continue
                    
                    try:
                        async for msg in channel.history(limit=100):
                            if msg.author.bot:
                                continue
                            
                            await asyncio.to_thread(
                                database.update_message_count,
                                guild.id,
                                msg.author.id,
                                msg.author.name,
                                msg.author.global_name or msg.author.name,
                                str(msg.author.display_avatar.url),
                                1
                            )
                            total_crawled += 1
                    except Exception as e:
                        print(f"Error crawling channel {channel.name}: {e}")
                
                mark_guild_synced(guild.id)
                print(f"Finished crawling history for {guild.name}. Seeded {total_crawled} messages.")
            else:
                print(f"Guild {guild.name} message history already synced. Skipping crawl.")

        except Exception as e:
            print(f"Error syncing guild {guild.name}: {e}")
    print("Member sync and history crawl completed.")

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name} ({bot.user.id})")
    print("------")
    bot.add_view(VoiceCreatorView())
    
    # Register and sync slash commands
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s) globally")
    except Exception as e:
        print(f"Error syncing commands: {e}")

    # Auto-setup panel channels for all guilds on start
    for guild in bot.guilds:
        await auto_create_setup_channel(guild)

    # Start background member synchronization and history crawl
    bot.loop.create_task(sync_and_crawl_history())

@bot.event
async def on_guild_join(guild):
    # Auto-setup panel channel when joining a new server
    await auto_create_setup_channel(guild)

@bot.event
async def on_guild_channel_delete(channel):
    # If the deleted channel was a tracked temporary channel, remove it from memory
    if channel.id in temp_channels:
        temp_channels.pop(channel.id, None)
        print(f"Removed manually deleted channel {channel.name} ({channel.id}) from memory.")

@bot.event
async def on_voice_state_update(member, before, after):
    # Track voice activity duration
    guild = member.guild
    
    # User left or switched channels
    if before.channel and (not after.channel or before.channel.id != after.channel.id):
        if not member.bot:
            voice_key = (guild.id, member.id)
            start_time = voice_start_times.pop(voice_key, None)
            if start_time:
                duration = time.time() - start_time
                if duration > 0:
                    await asyncio.to_thread(
                    database.update_voice_time,
                    guild.id,
                    member.id,
                    member.name,
                    member.global_name or member.name,
                    str(member.display_avatar.url),
                    int(duration)
                )
                print(f"Added {int(duration)}s voice time to {member.name} in {guild.name}")

    # User joined or switched channels
    if after.channel and (not before.channel or before.channel.id != after.channel.id):
        if not member.bot:
            voice_key = (guild.id, member.id)
            voice_start_times[voice_key] = time.time()

    # 1. Check if member joined a tracked temporary channel
    if after.channel and after.channel.id in temp_channels:
        channel = after.channel
        owner_id = temp_channels[channel.id]
        
        # Check if the channel is locked (default connect permission is denied)
        default_overwrite = channel.overwrites_for(member.guild.default_role)
        if default_overwrite.connect is False:
            # If the user who joined is not the owner
            if member.id != owner_id:
                # Check if they are in the owner's whitelist
                owner_whitelist = whitelists.get(owner_id, set())
                if member.id not in owner_whitelist:
                    # Check if they have an explicit user overwrite allowing them
                    user_overwrite = channel.overwrites_for(member)
                    if user_overwrite.connect is not True:
                        try:
                            # Kick them out of the voice channel (disconnect)
                            await member.move_to(None)
                            try:
                                is_ru = (str(member.guild.preferred_locale) == "ru")
                                msg = get_txt(
                                    "🔒 Этот канал закрыт владельцем.",
                                    "🔒 This channel is locked by the owner.",
                                    is_ru
                                )
                                await member.send(msg)
                            except Exception:
                                pass
                        except Exception as e:
                            print(f"Error kicking unauthorized member: {e}")

    # 2. Check if member left a tracked temporary channel
    if before.channel and before.channel.id in temp_channels:
        channel = before.channel
        owner_id = temp_channels[channel.id]
        
        # If the channel is completely empty, delete it
        if len(channel.members) == 0:
            try:
                await channel.delete()
                temp_channels.pop(channel.id, None)
                print(f"Deleted empty temporary channel: {channel.name}")
            except Exception as e:
                print(f"Error deleting channel {channel.id}: {e}")
        # If the owner left but others are still in the channel, auto-transfer ownership
        elif member.id == owner_id:
            new_owner = channel.members[0]
            temp_channels[channel.id] = new_owner.id
            try:
                is_ru = (str(member.guild.preferred_locale) == "ru")
                msg = get_txt(
                    f"👑 Владелец покинул канал. Новым владельцем назначен {new_owner.mention}!",
                    f"👑 The owner left. New owner is {new_owner.mention}!",
                    is_ru
                )
                await channel.send(msg)
            except Exception as e:
                print(f"Error sending transfer message: {e}")

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    if message.guild:
        await asyncio.to_thread(
            database.update_message_count,
            message.guild.id,
            message.author.id,
            message.author.name,
            message.author.global_name or message.author.name,
            str(message.author.display_avatar.url)
        )
    
    await bot.process_commands(message)


# --- Admin Text Sync Command ---
@bot.command(name="sync")
@commands.has_permissions(administrator=True)
async def sync_guild_commands(ctx):
    try:
        bot.tree.copy_global_to(guild=ctx.guild)
        synced = await bot.tree.sync(guild=ctx.guild)
        await ctx.send(f"✅ Слэш-команды успешно синхронизированы для этого сервера! (Зарегистрировано: {len(synced)})")
    except Exception as e:
        await ctx.send(f"❌ Ошибка при синхронизации команд: {e}")

@sync_guild_commands.error
async def sync_guild_commands_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ У вас должны быть права Администратора для синхронизации команд.", delete_after=5)


# Web server runner for Render.com hosting and Web Dashboard
class DashboardHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Prevent console cluttering with health checks and static requests
        pass

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query = urllib.parse.parse_qs(parsed_path.query)

        # Handle API routes
        if path == "/api/guilds":
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            
            guilds_data = []
            for g in bot.guilds:
                icon_url = str(g.icon.url) if g.icon else ""
                guilds_data.append({
                    "id": str(g.id),
                    "name": g.name,
                    "iconUrl": icon_url,
                    "memberCount": g.member_count
                })
            self.wfile.write(json.dumps(guilds_data, ensure_ascii=False).encode('utf-8'))
            return

        elif path == "/api/stats":
            guild_id_str = query.get("guild_id", [None])[0]
            if not guild_id_str:
                if bot.guilds:
                    guild_id = bot.guilds[0].id
                else:
                    guild_id = 0
            else:
                try:
                    guild_id = int(guild_id_str)
                except ValueError:
                    guild_id = 0

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            stats = database.get_guild_stats(guild_id)
            
            guild = bot.get_guild(guild_id)
            if guild:
                stats["guildName"] = guild.name
                stats["guildIcon"] = str(guild.icon.url) if guild.icon else ""
            else:
                stats["guildName"] = "Unknown Guild"
                stats["guildIcon"] = ""

            self.wfile.write(json.dumps(stats, ensure_ascii=False).encode('utf-8'))
            return

        elif path == "/api/member":
            guild_id_str = query.get("guild_id", [None])[0]
            user_id_str = query.get("user_id", [None])[0]
            
            if not guild_id_str or not user_id_str:
                self.send_error(400, "Missing guild_id or user_id")
                return
                
            try:
                guild_id = int(guild_id_str)
                user_id = int(user_id_str)
            except ValueError:
                self.send_error(400, "Invalid guild_id or user_id")
                return

            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            member_info = {
                "userId": str(user_id),
                "username": f"User_{user_id}",
                "globalName": f"User_{user_id}",
                "avatarUrl": "",
                "joinedAt": None,
                "createdAt": None,
                "status": "offline",
                "isOwner": False,
                "isAdmin": False,
                "roles": []
            }

            guild = bot.get_guild(guild_id)
            if guild:
                member = guild.get_member(user_id)
                if not member:
                    try:
                        future = asyncio.run_coroutine_threadsafe(guild.fetch_member(user_id), bot.loop)
                        member = future.result(timeout=2.0)
                    except Exception:
                        member = None

                if member:
                    status_str = str(member.status)
                    
                    roles_list = []
                    for r in reversed(member.roles):
                        if r.is_default():
                            continue
                        
                        color_hex = f"#{r.color.value:06x}" if r.color.value != 0 else "#8b8d99"
                        roles_list.append({
                            "name": r.name,
                            "color": color_hex
                        })
                    
                    is_admin = member.guild_permissions.administrator
                    is_owner = (member.id == guild.owner_id)

                    member_info.update({
                        "username": member.name,
                        "globalName": member.global_name or member.name,
                        "avatarUrl": str(member.display_avatar.url),
                        "joinedAt": member.joined_at.isoformat() if member.joined_at else None,
                        "createdAt": member.created_at.isoformat() if member.created_at else None,
                        "status": status_str,
                        "isOwner": is_owner,
                        "isAdmin": is_admin,
                        "roles": roles_list
                    })

            self.wfile.write(json.dumps(member_info, ensure_ascii=False).encode('utf-8'))
            return

        # Handle Static files
        base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
        
        safe_path = path.lstrip("/")
        if not safe_path or safe_path == "index.html":
            file_path = os.path.join(base_dir, "index.html")
            content_type = "text/html; charset=utf-8"
        elif safe_path == "styles.css":
            file_path = os.path.join(base_dir, "styles.css")
            content_type = "text/css; charset=utf-8"
        elif safe_path == "app.js":
            file_path = os.path.join(base_dir, "app.js")
            content_type = "application/javascript; charset=utf-8"
        else:
            self.send_error(404, "File Not Found")
            return

        if os.path.exists(file_path):
            try:
                with open(file_path, "rb") as f:
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.end_headers()
                    self.wfile.write(f.read())
            except Exception as e:
                self.send_error(500, f"Internal Server Error: {e}")
        else:
            if safe_path == "":
                self.send_response(200)
                self.send_header("Content-type", "text/plain")
                self.end_headers()
                self.wfile.write(b"Bot is online. Dashboard web/ files are not yet created.")
            else:
                self.send_error(404, "File Not Found")

def run_web_server():
    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), DashboardHTTPHandler)
    print(f"Web server listening on port {port}")
    server.serve_forever()

def self_ping():
    # Wait 30 seconds for the server to spin up completely
    time.sleep(30)
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        print("self_ping: RENDER_EXTERNAL_URL environment variable is not set. Cannot self-ping.")
        return
    
    print(f"self_ping: Started self-pinging loop for {url}")
    while True:
        try:
            # Send HTTP GET request to self
            with urllib.request.urlopen(url) as response:
                status = response.getcode()
                print(f"self_ping: Successfully pinged self. HTTP Status: {status}")
        except Exception as e:
            print(f"self_ping: Error pinging self: {e}")
        
        # Ping every 10 minutes (600 seconds) to prevent Render's 15 min sleep
        time.sleep(600)

# Run the Bot
if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("Error: Please specify a valid DISCORD_TOKEN in the .env file.")
    else:
        # Start web server thread
        threading.Thread(target=run_web_server, daemon=True).start()
        # Start self-pinging thread
        threading.Thread(target=self_ping, daemon=True).start()
        bot.run(TOKEN)
