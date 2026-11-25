'''
The buttons under the player message.
'''
from typing import TYPE_CHECKING

import discord
from discord.ui import Button

if TYPE_CHECKING:
    # only for type hints: importing cog.py for real would be circular,
    # because cog.py imports this file to create the buttons
    from .cog import MusicPlayer


class MusicControls(discord.ui.View):
    '''The buttons under the player message.

    Skip, End, Shuffle and View Queue call the matching handler on MusicPlayer.
    Pause/Resume is one button that switches between the two.
    '''

    def __init__(self, musicPlayer: "MusicPlayer", paused: bool = False):
        '''
        Args:
            musicPlayer: The MusicPlayer cog the buttons control.
            paused: Whether the music is paused right now (decides Pause vs Resume).
        '''
        super().__init__(timeout=None)
        self.musicPlayer = musicPlayer
        self._show_paused(paused)

    def _show_paused(self, paused: bool):
        '''Makes the toggle look like "Resume" (when paused) or "Pause" (when playing).'''
        button = self.pause_resume_button
        if paused:
            button.label, button.emoji, button.style = "Resume", "▶️", discord.ButtonStyle.green
        else:
            button.label, button.emoji, button.style = "Pause", "⏸️", discord.ButtonStyle.gray

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        '''Runs before every button press: only people in Muse's voice channel can control it.

        View Queue is allowed for everyone (it's private and read-only). If Muse isn't in
        voice, the click goes through so the button can answer "Nothing is playing."
        '''
        if interaction.data.get("custom_id") == self.view_queue_button.custom_id:
            return True

        voice_client = interaction.guild.voice_client
        if not voice_client:
            return True

        if not interaction.user.voice or interaction.user.voice.channel != voice_client.channel:
            await interaction.response.send_message("Join Muse's voice channel to control the music.", ephemeral=True)
            return False

        return True

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.red, emoji="⏹️")
    async def end_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.end(interaction)

    @discord.ui.button(label="Shuffle", style=discord.ButtonStyle.green, emoji="🔀")
    async def shuffle_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.shuffle(interaction)

    @discord.ui.button(label="View Queue", style=discord.ButtonStyle.green, emoji="📜")
    async def view_queue_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.view_queue(interaction)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.gray, emoji="⏸️")
    async def pause_resume_button(self, interaction: discord.Interaction, button: Button):
        '''Pauses if playing, resumes if paused, and updates the player to match.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        # decide by the real state, not the button label (labels on old messages can be stale)
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            paused = False
        elif voice_client and voice_client.is_playing():
            voice_client.pause()
            paused = True
        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        self._show_paused(paused)
        await interaction.response.edit_message(
            embed=self.musicPlayer._now_playing_embed(guild_id, paused=paused),
            view=self
        )
