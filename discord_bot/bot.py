import os
import discord
from discord.ext import commands
from discord import app_commands
from dotenv import load_dotenv
import threading
from http.server import SimpleHTTPRequestHandler, HTTPServer

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
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            msg = get_txt("❌ Пользователь не найден.", "❌ User not found.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return
        
        # Security: Prevent kicking administrators, owners, or members with equal/higher roles
        if member.guild_permissions.administrator or member.id == interaction.guild.owner_id or member.top_role >= interaction.user.top_role:
            msg = get_txt(
                "❌ Вы не можете выгнать этого пользователя (у него равные или более высокие права).",
                "❌ You cannot kick this user (equal or higher permissions).",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if member.voice and member.voice.channel == self.channel:
            try:
                await member.move_to(None)
                msg = get_txt(
                    f"✅ {member.mention} был выгнан из канала.",
                    f"✅ {member.mention} was kicked from the channel.",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
            except Exception as e:
                msg = get_txt(
                    f"❌ Не удалось выгнать: {e}",
                    f"❌ Failed to kick: {e}",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            msg = get_txt(
                "❌ Этот пользователь не находится в вашем канале.",
                "❌ This user is not in your channel.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


class MuteSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Выберите кого мут/размут...", "Mute/unmute user...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            msg = get_txt("❌ Пользователь не найден.", "❌ User not found.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        # Security: Prevent muting administrators, owners, or members with equal/higher roles
        if member.guild_permissions.administrator or member.id == interaction.guild.owner_id or member.top_role >= interaction.user.top_role:
            msg = get_txt(
                "❌ Вы не можете заглушить этого пользователя (у него равные или более высокие права).",
                "❌ You cannot mute this user (equal or higher permissions).",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
            return

        if member.voice and member.voice.channel == self.channel:
            try:
                current_mute = member.voice.mute
                await member.edit(mute=not current_mute)
                status = get_txt("заглушен 🔇", "muted 🔇", self.is_russian) if not current_mute else get_txt("разглушен 🔊", "unmuted 🔊", self.is_russian)
                msg = get_txt(
                    f"✅ {member.mention} был {status}.",
                    f"✅ {member.mention} was {status}.",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
            except Exception as e:
                msg = get_txt(
                    f"❌ Не удалось изменить микрофон: {e}",
                    f"❌ Failed to toggle mute status: {e}",
                    self.is_russian
                )
                await interaction.response.send_message(msg, ephemeral=True)
        else:
            msg = get_txt(
                "❌ Этот пользователь не находится в вашем канале.",
                "❌ This user is not in your channel.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


class InviteSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Выберите кого пригласить...", "Select user to invite...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            msg = get_txt("❌ Пользователь не найден.", "❌ User not found.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

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

            msg = get_txt(
                f"✅ {member.mention} приглашен в канал.",
                f"✅ {member.mention} has been invited to the channel.",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)
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
        except Exception as e:
            msg = get_txt(
                f"❌ Не удалось выдать права: {e}",
                f"❌ Failed to grant permissions: {e}",
                self.is_russian
            )
            await interaction.response.send_message(msg, ephemeral=True)


class AddFriendSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Добавить друга в вайт-лист...", "Add friend to whitelist...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            msg = get_txt("❌ Пользователь не найден.", "❌ User not found.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        owner_id = interaction.user.id
        if owner_id not in whitelists:
            whitelists[owner_id] = set()

        if member.id == owner_id:
            msg = get_txt("❌ Вы не можете добавить себя.", "❌ You cannot add yourself.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        whitelists[owner_id].add(member.id)
        save_whitelist()

        try:
            overwrite = self.channel.overwrites_for(member)
            overwrite.connect = True
            overwrite.view_channel = True
            await self.channel.set_permissions(member, overwrite=overwrite)
        except Exception:
            pass

        msg = get_txt(
            f"✅ {member.mention} добавлен в ваш вайт-лист!",
            f"✅ {member.mention} has been added to your whitelist!",
            self.is_russian
        )
        await interaction.response.send_message(msg, ephemeral=True)


class RemoveFriendSelect(discord.ui.UserSelect):
    def __init__(self, channel: discord.VoiceChannel, is_russian: bool):
        placeholder = get_txt("Удалить друга из вайт-листа...", "Remove friend from whitelist...", is_russian)
        super().__init__(placeholder=placeholder, min_values=1, max_values=1)
        self.channel = channel
        self.is_russian = is_russian

    async def callback(self, interaction: discord.Interaction):
        member = self.values[0]
        if not isinstance(member, discord.Member):
            msg = get_txt("❌ Пользователь не найден.", "❌ User not found.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        owner_id = interaction.user.id
        owner_whitelist = whitelists.get(owner_id, set())

        if member.id not in owner_whitelist:
            msg = get_txt("❌ Этого пользователя нет в вашем вайт-листе.", "❌ This user is not in your whitelist.", self.is_russian)
            await interaction.response.send_message(msg, ephemeral=True)
            return

        owner_whitelist.remove(member.id)
        save_whitelist()

        try:
            overwrite = self.channel.overwrites_for(member)
            overwrite.connect = None
            overwrite.view_channel = None
            await self.channel.set_permissions(member, overwrite=overwrite)
            
            default_overwrite = self.channel.overwrites_for(interaction.guild.default_role)
            if default_overwrite.connect is False and member.voice and member.voice.channel == self.channel:
                await member.move_to(None)
        except Exception:
            pass

        msg = get_txt(
            f"✅ {member.mention} удален из вашего вайт-листа.",
            f"✅ {member.mention} has been removed from your whitelist.",
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


# --- Events ---
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


# Web server runner for Render.com hosting to keep the Web Service alive
def run_web_server():
    class HealthCheckHandler(SimpleHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is online and running!")

    port = int(os.getenv("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    print(f"Web server listening on port {port}")
    server.serve_forever()

# Run the Bot
if __name__ == "__main__":
    if not TOKEN or TOKEN == "YOUR_DISCORD_BOT_TOKEN_HERE":
        print("Error: Please specify a valid DISCORD_TOKEN in the .env file.")
    else:
        # Start web server thread
        threading.Thread(target=run_web_server, daemon=True).start()
        bot.run(TOKEN)
