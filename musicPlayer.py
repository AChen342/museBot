'''
Music player cog for Muse bot.

Plays audio from YouTube links in Discord voice channels, keeps one song
queue per server, and provides button controls (skip, end, view queue,
pause, resume).
'''
import asyncio
import os
from collections import deque
from typing import Deque, Optional, Tuple

import discord
import yt_dlp as youtube_dl
from discord import app_commands
from discord.ext import commands
from discord.ui import Button

# A queued song: (audio stream url, title)
Song = Tuple[str, str]


class MusicPlayer(commands.Cog):
    '''Discord Cog for playing music through Muse bot.

    Handles commands and events for playing, queuing,
    and controlling music in Discord voice channels.
    '''

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    FFMPEG_PATH = os.path.join(os.path.dirname(__file__), 'bin', 'ffmpeg.exe')

    # Options for ffmpeg audio processing
    FFMPEG_OPTIONS = {
        'executable': FFMPEG_PATH,
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -af loudnorm=I=-16:LRA=11:TP=-1.5 -c:a libopus -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
    }

    # Options for yt_dlp extraction
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        # Force IPv4: YouTube returns 403 Forbidden for stream links tied to our IPv6 address
        'source_address': '0.0.0.0',
        # Other YouTube clients (tv, web, android) often return links that fail with 403;
        # visionos was the only one that worked for every video tested (Nov 2026)
        'extractor_args': {'youtube': {'player_client': ['visionos']}},
        # A video link with &list=... plays just that video, not the whole playlist
        'noplaylist': True,
        # For playlist links, only load the first video (must be a string, not an int)
        'playlist_items': '1'
    }

    def __init__(self, bot: commands.Bot):
        '''Initializes the MusicPlayer Cog.

        Args:
            bot: The Discord bot instance
        '''
        self.bot = bot
        self.queues: dict[int, Deque[Song]] = {}
        self.current_audio: dict[int, Song] = {}

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @commands.Cog.listener()
    async def on_ready(self):
        '''When bot is ready, loads all custom commands into Discord.'''
        try:
            await self.bot.tree.sync()
        except Exception as e:
            print(f"Failed to load music commands: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        '''Disconnects bot from voice channel when no one else is in it.

        Args:
            member: Discord user whose voice state changed (joined, disconnect, muted, etc.).
            before: User's voice state before the change (which channel they were in).
            after: The user's voice state after the update.
        '''
        if not member.guild:
            return

        bot_voice_client = member.guild.voice_client
        if not bot_voice_client or not bot_voice_client.channel:
            return

        non_bot_members = [m for m in bot_voice_client.channel.members if not m.bot]
        if len(non_bot_members) == 0:
            await self._reset_and_disconnect(member.guild.id, bot_voice_client)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_queue(self, server_id: int) -> Deque[Song]:
        '''Returns the server's queue, creating an empty one if needed.'''
        return self.queues.setdefault(server_id, deque())

    def _extract_audio(self, url: str) -> Song:
        '''Uses yt_dlp to turn a YouTube link into (audio stream url, title).

        Raises:
            youtube_dl.utils.DownloadError: If the video can't be loaded.
            ValueError: If the link is a playlist/page with no videos.
        '''
        with youtube_dl.YoutubeDL(self.YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)

        if 'entries' in info:  # Playlist case
            entries = list(info['entries'])
            if len(entries) <= 0:
                raise ValueError("That link has no audio to play. Use a link to a specific video.")
            info = entries[0]

        return info['url'], info.get('title', 'Unknown Title')

    async def _reset_and_disconnect(self, server_id: int, voice_client: discord.VoiceClient):
        '''Clears the current audio and the server's queue, then disconnects.

        The queue is cleared before disconnecting so play_next (triggered when
        playback stops) finds nothing left to play.
        '''
        self.current_audio.pop(server_id, None)

        queue = self.queues.get(server_id)
        if queue:
            queue.clear()

        await voice_client.disconnect()

    async def _leave_if_idle(self, server_id: int, voice_client: Optional[discord.VoiceClient]):
        '''Disconnects only if the bot is connected and not playing or paused.'''
        if voice_client and not (voice_client.is_playing() or voice_client.is_paused()):
            await self._reset_and_disconnect(server_id, voice_client)

    async def play_next(self, interaction: discord.Interaction, error=None):
        '''Plays the next audio url from a queue.

        Args:
            interaction: Contains information about an interaction between user and bot.
            error: Stores any errors that occurred during audio playback.
        '''
        if error:
            await interaction.channel.send(f"Playback error: {error}")
        
        guild_id = interaction.guild.id
        server_queue = self.queues.get(interaction.guild.id)
        if not server_queue:
            self.current_audio.pop(guild_id, None)
            return

        voice_client = interaction.guild.voice_client

        self.current_audio[guild_id] = server_queue.popleft()
        audio_url, audio_title = self.current_audio[guild_id]

        source = await discord.FFmpegOpusAudio.from_probe(audio_url, **self.FFMPEG_OPTIONS)

        def after_playing(error):
            asyncio.run_coroutine_threadsafe(
                self.play_next(interaction, error),
                self.bot.loop
            )

        voice_client.play(source, after=after_playing)

        # Sent to the channel (not as an interaction reply) so it still works
        # after the interaction expires (15 minutes)
        try:
            await interaction.channel.send(
                f"Now Playing: \"{audio_title}\"",
                view=MusicControls(self)
            )
        except discord.HTTPException as e:
            print(f"Couldn't send Now Playing message: {e}")

    # ------------------------------------------------------------------
    # Slash commands
    # ------------------------------------------------------------------

    @app_commands.command(name="play", description="plays a youtube link")
    async def play(self, interaction: discord.Interaction, url: str):
        '''Processes youtube link into audio and plays it through the bot.

        Args:
            url: Youtube url provided by user input to be processed into audio
        '''
        if not interaction.user.voice:
            await interaction.response.send_message(
                "You need to be in a voice chat to use this command.",
                ephemeral=True
            )
            return

        server_id = interaction.guild.id
        user_voice_channel = interaction.user.voice.channel
        bot_voice_client = interaction.guild.voice_client

        try:
            await interaction.response.send_message("Adding music to queue.")

            if not bot_voice_client:
                bot_voice_client = await user_voice_channel.connect()

            if bot_voice_client.channel != user_voice_channel:
                await bot_voice_client.move_to(user_voice_channel)

            audio_url, audio_title = await asyncio.to_thread(self._extract_audio, url)

            # add audio to queue
            self._get_queue(server_id).append((audio_url, audio_title))
            await interaction.followup.send(f"Added \"{audio_title}\" to queue.")

            # plays next song in queue
            if not bot_voice_client.is_playing() and not bot_voice_client.is_paused():
                await self.play_next(interaction)

        except youtube_dl.utils.DownloadError:  # video is private, deleted, restricted, etc.
            await interaction.followup.send(
                "Couldn't load that link. It may be privated, deleted, restricted or not a valid video."
            )
            await self._leave_if_idle(server_id, bot_voice_client)

        except Exception as e:  # catches any other error
            await interaction.followup.send(f"Error: {str(e)}")
            await self._leave_if_idle(server_id, bot_voice_client)

    @app_commands.command(name="options", description="brings up music player interface")
    async def options(self, interaction: discord.Interaction):
        '''Discord command that brings up music player options (ie. pause, resume, stop buttons).'''
        bot_voice_client = interaction.guild.voice_client

        if not bot_voice_client:
            await interaction.response.send_message("Muse is not connected to a voice chat")
            return

        current = self.current_audio.get(interaction.guild.id)
        if current is None or not (bot_voice_client.is_playing() or bot_voice_client.is_paused()):
            await interaction.response.send_message("Nothing is playing")
            return

        _, audio_title = current
        msg = "Now Paused: " if bot_voice_client.is_paused() else "Now Playing: "
        await interaction.response.send_message(f"{msg}\"{audio_title}\"", view=MusicControls(self))

    # ------------------------------------------------------------------
    # Button handlers (called by MusicControls)
    # ------------------------------------------------------------------

    async def skip(self, interaction: discord.Interaction):
        '''Handles the Skip button interaction.
        Skips the current audio playing. Stops current audio if nothing in queue.
        '''
        voice_client = interaction.guild.voice_client
        server_queue = self._get_queue(interaction.guild.id)

        if not (voice_client and (voice_client.is_playing() or voice_client.is_paused())):
            await interaction.response.send_message("Nothing is playing.")
            return

        _, current_audio_title = self.current_audio.get(interaction.guild.id)
        # stopping triggers after_playing -> play_next, which starts the next song if there is one
        voice_client.stop()

        if len(server_queue) <= 0:
            await interaction.response.send_message(f"Stopped {current_audio_title}.")
        else:
            await interaction.response.send_message(f"Skipped {current_audio_title}.")

    async def end(self, interaction: discord.Interaction):
        '''Handles the End button interaction.
        Stops the bot from playing and disconnects the bot from voice channel.
        '''
        try:
            voice_client = interaction.guild.voice_client

            if not voice_client or not voice_client.is_connected():
                return await interaction.response.send_message(
                    "I'm not connected to any voice channel",
                    ephemeral=True
                )

            await self._reset_and_disconnect(interaction.guild.id, voice_client)

            await interaction.response.send_message(
                "Stopped playback and disconnected from voice channel"
            )
        except Exception as e:
            print(f"Error in end: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}")

    async def view_queue(self, interaction: discord.Interaction):
        '''Handles View Queue button interaction.
        Displays the next five audio in server queue.
        '''
        queue = self._get_queue(interaction.guild.id)
        embed = discord.Embed(
            title="Next on your queue",
            description="Displays next five songs in your queue.",
            color=discord.Color.purple()
        )

        if len(queue) == 0:
            msg = "Your queue is empty."
        else:
            msg = ""
            for i in range(min(5, len(queue))):
                _, title = queue[i]
                msg += f"{i + 1}. {title}\n"

        embed.add_field(name="Upcoming:", value=msg, inline=False)
        await interaction.response.send_message(embed=embed)

    async def pause(self, interaction: discord.Interaction):
        '''Handles the Pause button interaction.
        Pauses the music player if music player is playing audio.
        '''
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            await interaction.response.send_message("Paused music.")
        else:
            await interaction.response.send_message("Nothing is playing.")

    async def resume(self, interaction: discord.Interaction):
        '''Handles the Resume button interaction.
        If current audio is paused, the bot will unpause the music player.
        '''
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("Resumed music.")
        else:
            await interaction.response.send_message("Nothing is paused.")


class MusicControls(discord.ui.View):
    '''Buttons shown under "Now Playing" messages.

    Each button just calls the matching handler on MusicPlayer.
    '''

    def __init__(self, musicPlayer: MusicPlayer):
        '''Initializes the UI for musicPlayer

        Args:
            musicPlayer: Instance of MusicPlayer which holds the
                functionality for all the music player UI.
        '''
        super().__init__(timeout=None)
        self.musicPlayer = musicPlayer

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple)
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.red)
    async def end_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.end(interaction)

    @discord.ui.button(label="View Queue", style=discord.ButtonStyle.green)
    async def view_queue_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.view_queue(interaction)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.gray)
    async def pause_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.pause(interaction)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.blurple)
    async def resume_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.resume(interaction)


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
