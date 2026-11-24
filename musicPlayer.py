'''
Music player cog for Muse bot.

Plays audio from YouTube links in Discord voice channels, keeps one song
queue per server, and provides button controls (skip, end, view queue,
pause, resume).
'''
import asyncio
import os
from collections import deque
from typing import Deque, Optional

import discord
import yt_dlp as youtube_dl
from discord import app_commands
from discord.ext import commands
from discord.ui import Button
from dataclasses import dataclass


@dataclass
class Song:
    stream_url: str
    title: str
    webpage_url: str
    thumbnail: Optional[str]
    duration: Optional[str]
    uploader: Optional[str]
    requester: str = ""


class MusicPlayer(commands.Cog):
    '''Discord Cog for playing music through Muse bot.

    Handles commands and events for playing, queuing,
    and controlling music in Discord voice channels.
    '''

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    # Bundled ffmpeg.exe on Windows; the system-installed ffmpeg everywhere else (e.g. Linux server)
    FFMPEG_PATH = (
        os.path.join(os.path.dirname(__file__), 'bin', 'ffmpeg.exe')
        if os.name == 'nt' else 'ffmpeg'
    )

    # Options for ffmpeg audio processing
    FFMPEG_OPTIONS = {
        'executable': FFMPEG_PATH,
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -af loudnorm=I=-16:LRA=11:TP=-1.5 -c:a libopus -b:a 128k -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
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
        self.player_messages: dict [int, discord.Message] = {}

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
    async def _close_player(self, guild_id, text):
        message = self.player_messages.get(guild_id)
        if message:
            closed_card = discord.Embed(
                title=text, 
                color=discord.Color.dark_gray()
            )

            view = MusicControls(self)
            for item in view.children:
                item.disabled = True

            try:
                await message.edit(embed=closed_card, view=view)
            except discord.HTTPException as e:
                print(f"Couldn't close player: {e}")

            self.player_messages.pop(guild_id)
    
    async def _update_player(self, guild_id, channel, paused=False):
        current_song = self.current_audio.get(guild_id)
        song_card = self._now_playing_embed(current_song, guild_id, paused=paused)
        view_panel = MusicControls(self, paused=paused)

        try:
            message = self.player_messages.get(guild_id)
            if message:
                await message.edit(embed=song_card, view=view_panel)
            else:
                self.player_messages[guild_id] = await channel.send(embed=song_card, view=view_panel)
        
        except discord.NotFound:
            try:
                self.player_messages[guild_id] = await channel.send(embed=song_card, view=view_panel)

            except discord.HTTPException as e:
                print(f"Couldn't update player: {e}")

        except discord.HTTPException as e:
            print(f"Couldn't update player: {e}")

    def _now_playing_embed(self, song, guild_id, paused=False):
        song_card = discord.Embed(
            title=song.title, 
            url=song.webpage_url,
            description=song.uploader,
            color=discord.Color.blue()
        )

        # set up author for embed card
        author = "🎶 Now Playing" if not paused else "⏸️ Paused"
        song_card.set_author(name=author)

        # setup duration
        song_card.add_field(name="Duration", value=song.duration or "Live", inline=True)

        # footer setup
        server_queue = self._get_queue(guild_id)
        queue_count = len(server_queue)

        if server_queue:
            footer = f"Up next: {server_queue[0].title}"
            footer += f" + {queue_count - 1} more" if (queue_count - 1) > 0 else ""
        else:
            footer = "Queue is empty"
        song_card.set_footer(text=footer)

        # thumbnail setup
        song_card.set_thumbnail(url=song.thumbnail)

        # requester setup
        song_card.add_field(name="Requested by", value=song.requester, inline=True)

        return song_card

    def _get_queue(self, server_id: int) -> Deque[Song]:
        '''Returns the server's queue, creating an empty one if needed.'''
        return self.queues.setdefault(server_id, deque())

    def _extract_audio(self, url: str) -> Song:
        '''Uses yt_dlp to turn a YouTube link into Song dataclass.

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

        total = info.get('duration')
        if total is None:
            duration = None
        else:
            minutes, seconds = divmod(total, 60)
            hours = 0
            if minutes >= 60:
                hours, minutes = divmod(minutes, 60)
                duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                duration = f"{minutes}:{seconds:02d}"

        return Song(stream_url=info['url'],
                    title=info.get('title', 'Unknown Title'),
                    thumbnail=info.get('thumbnail'),
                    duration=duration,
                    uploader=info.get('uploader'),
                    webpage_url=info.get('webpage_url', url))

    async def _reset_and_disconnect(self, server_id: int, voice_client: discord.VoiceClient):
        '''Clears the current audio and the server's queue, then disconnects.

        The queue is cleared before disconnecting so play_next (triggered when
        playback stops) finds nothing left to play.
        '''
        self.current_audio.pop(server_id, None)

        queue = self.queues.get(server_id)
        if queue:
            queue.clear()

        await self._close_player(guild_id=server_id, text="Session Ended")

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
            await self._close_player(guild_id, "Queue finished, use /play to add more")
            self.current_audio.pop(guild_id, None)
            return

        voice_client = interaction.guild.voice_client

        self.current_audio[guild_id] = server_queue.popleft()
        song = self.current_audio[guild_id]

        source = await discord.FFmpegOpusAudio.from_probe(song.stream_url, **self.FFMPEG_OPTIONS)

        def after_playing(error):
            asyncio.run_coroutine_threadsafe(
                self.play_next(interaction, error),
                self.bot.loop
            )

        voice_client.play(source, after=after_playing)

        # Sent to the channel (not as an interaction reply) so it still works
        # after the interaction expires (15 minutes)
        await self._update_player(guild_id, interaction.channel)

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
            await interaction.response.defer()

            if not bot_voice_client:
                bot_voice_client = await user_voice_channel.connect()

            if bot_voice_client.channel != user_voice_channel:
                await bot_voice_client.move_to(user_voice_channel)

            song = await asyncio.to_thread(self._extract_audio, url)
            song.requester = interaction.user.mention

            # add audio to queue
            self._get_queue(server_id).append(song)
            await interaction.followup.send(f"{interaction.user.display_name} added \"{song.title}\" to queue.")
            
            # plays next song in queue
            if not bot_voice_client.is_playing() and not bot_voice_client.is_paused():
                await self.play_next(interaction)
            else:
                await self._update_player(server_id, interaction.channel, paused=bot_voice_client.is_paused())

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
            await interaction.response.send_message("Muse is not connected to a voice chat", ephemeral=True)
            return

        current = self.current_audio.get(interaction.guild.id)
        if current is None or not (bot_voice_client.is_playing() or bot_voice_client.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        paused = bot_voice_client.is_paused()
        await interaction.response.send_message(
            embed=self._now_playing_embed(current, interaction.guild.id, paused=paused),
            view=MusicControls(self, paused=paused)
        )

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
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        song = self.current_audio.get(interaction.guild.id)
        # stopping triggers after_playing -> play_next, which starts the next song if there is one
        voice_client.stop()

        user = interaction.user.display_name
        if len(server_queue) <= 0:
            await interaction.response.send_message(f"{user} stopped {song.title}.")
        else:
            await interaction.response.send_message(f"{user} skipped {song.title}.")

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
            user = interaction.user.display_name
            await interaction.response.send_message(
                f"{user} stopped playback and disconnected bot from voice channel"
            )
        except Exception as e:
            print(f"Error in end: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

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
                song = queue[i]
                msg += f"{i + 1}. {song.title} ({song.duration})\n"

        embed.add_field(name="Upcoming:", value=msg, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class MusicControls(discord.ui.View):
    '''Buttons shown under "Now Playing" messages.

    Each button just calls the matching handler on MusicPlayer.
    '''

    def __init__(self, musicPlayer: MusicPlayer, paused: bool = False):
        '''Initializes the UI for musicPlayer

        Args:
            musicPlayer: Instance of MusicPlayer which holds the
                functionality for all the music player UI.
        '''
        super().__init__(timeout=None)
        self.musicPlayer = musicPlayer
        if paused:
            self.pause_resume_button.label = "Resume"
            self.pause_resume_button.emoji = "▶️"
            self.pause_resume_button.style = discord.ButtonStyle.green
        else:
            self.pause_resume_button.label = "Pause"
            self.pause_resume_button.emoji = "⏸️"
            self.pause_resume_button.style = discord.ButtonStyle.gray

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.red, emoji="⏹️")
    async def end_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.end(interaction)

    @discord.ui.button(label="View Queue", style=discord.ButtonStyle.green, emoji="📜")
    async def view_queue_button(self, interaction: discord.Interaction, button: Button):
        await self.musicPlayer.view_queue(interaction)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.gray, emoji="⏸️")
    async def pause_resume_button(self, interaction: discord.Interaction, button: Button):
        voice_client = interaction.guild.voice_client
        song = self.musicPlayer.current_audio.get(interaction.guild.id)

        if voice_client and voice_client.is_paused(): # resume if audio was paused
            voice_client.resume()
            self.pause_resume_button.label = "Pause"
            self.pause_resume_button.emoji = "⏸️"
            self.pause_resume_button.style = discord.ButtonStyle.gray

            await interaction.response.edit_message(
                embed=self.musicPlayer._now_playing_embed(song, interaction.guild.id, paused=False), view=self
            )

        elif voice_client and voice_client.is_playing(): # pause if audio is playing
            voice_client.pause()
            self.pause_resume_button.label = "Resume"
            self.pause_resume_button.emoji = "▶️"
            self.pause_resume_button.style = discord.ButtonStyle.green

            await interaction.response.edit_message(
                embed=self.musicPlayer._now_playing_embed(song, interaction.guild.id, paused=True), view=self
            )

        else:
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
