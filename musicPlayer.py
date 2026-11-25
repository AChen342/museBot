'''
Music player cog for Muse bot.

Plays music from YouTube in Discord voice channels. Each server gets its own
song queue and one "live" player message that updates as songs change.

How this file is laid out:
    Song             - the data stored for each queued song
    MusicPlayer      - the cog: commands, events, playback and cleanup
    MusicControls    - the buttons under the player message
'''
import asyncio
import os
import re
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional
from urllib.parse import urlsplit

import discord
import yt_dlp as youtube_dl
from discord import app_commands
from discord.ext import commands
from discord.ui import Button


# Matches YouTube links typed without "https://", e.g. "youtube.com/watch?v=..." or "youtu.be/..."
YT_PATTERN = r'^(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/'


@dataclass
class Song:
    '''Everything the bot needs to play and display one song.'''
    stream_url: str            # direct audio link that FFmpeg plays
    title: str
    webpage_url: str           # normal YouTube link, used for the clickable title
    thumbnail: Optional[str]
    duration: Optional[str]    # e.g. "3:33" or "1:02:05"; None for live streams
    uploader: Optional[str]    # YouTube channel name
    requester: str = ""        # mention of the user who added it, e.g. "<@123>"


class MusicPlayer(commands.Cog):
    '''Discord cog that plays, queues and controls music for every server.'''

    # ==================================================================
    # Configuration
    # ==================================================================

    # Bundled ffmpeg.exe on Windows; the system-installed ffmpeg everywhere else (e.g. Linux server)
    FFMPEG_PATH = (
        os.path.join(os.path.dirname(__file__), 'bin', 'ffmpeg.exe')
        if os.name == 'nt' else 'ffmpeg'
    )

    # Options for FFmpeg audio processing
    FFMPEG_OPTIONS = {
        'executable': FFMPEG_PATH,
        # retry for a few seconds if the stream connection drops
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        # even out loudness between songs and encode for Discord at 128 kbps
        'options': '-vn -af loudnorm=I=-16:LRA=11:TP=-1.5 -c:a libopus -b:a 128k -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
    }

    # used to disconnect bot when idle
    IDLE_TIMEOUT = 20 # change as needed default is 300s (5 minutes)

    # Options for yt_dlp
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
        self.bot = bot

        # Everything below is stored per server, keyed by the server's ID (guild.id)
        self.queues: dict[int, Deque[Song]] = {}               # songs waiting to play
        self.current_audio: dict[int, Song] = {}               # the song playing right now
        self.player_messages: dict[int, discord.Message] = {}  # the live player message
        self.idle_timers: dict[int, asyncio.Task] = {}

    # ==================================================================
    # Events
    # ==================================================================

    @commands.Cog.listener()
    async def on_ready(self):
        '''Registers the slash commands with Discord when the bot starts.'''
        try:
            await self.bot.tree.sync()
        except Exception as e:
            print(f"Failed to load music commands: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        '''Runs whenever someone joins, leaves or changes state in a voice channel.

        - If Muse itself was disconnected (kicked, channel deleted, ...), clean up.
        - If everyone else left Muse's channel, disconnect.

        Args:
            member: The user whose voice state changed.
            before: Their voice state before the change (which channel they were in).
            after: Their voice state after the change.
        '''
        if not member.guild:
            return

        # Muse was disconnected without going through our own code: clean up
        if member.id == self.bot.user.id and before.channel and after.channel is None:
            await self._reset_state(member.guild.id, "Disconnected from voice chat")
            return

        voice_client = member.guild.voice_client
        if not voice_client or not voice_client.channel:
            return

        # Nobody but bots left in Muse's channel: leave
        non_bot_members = [m for m in voice_client.channel.members if not m.bot]
        if not non_bot_members:
            await self._reset_and_disconnect(member.guild.id, voice_client)

    # ==================================================================
    # Slash commands
    # ==================================================================

    @app_commands.command(name="play", description="play a YouTube link or search for a song")
    @app_commands.describe(query="A YouTube link or a song name")
    async def play(self, interaction: discord.Interaction, query: str):
        '''Plays a YouTube link, or searches YouTube and plays the best match.

        Args:
            query: A YouTube link (with or without https://) or a song name
        '''
        if not interaction.user.voice:
            await interaction.response.send_message(
                "You need to be in a voice chat to use this command.",
                ephemeral=True
            )
            return

        guild_id = interaction.guild.id
        user_voice_channel = interaction.user.voice.channel
        voice_client = interaction.guild.voice_client

        try:
            # looking up a song takes a few seconds; tell Discord we're working on it
            await interaction.response.defer()

            # join (or move to) the user's voice channel
            if not voice_client:
                voice_client = await user_voice_channel.connect()
            if voice_client.channel != user_voice_channel:
                await voice_client.move_to(user_voice_channel)

            # a link plays directly; anything else becomes a YouTube search.
            # The lookup runs in a background thread so the bot doesn't freeze meanwhile.
            source = self._identify_song_input(query)
            song = await asyncio.to_thread(self._extract_audio, source)
            song.requester = interaction.user.mention

            self._get_queue(guild_id).append(song)
            await interaction.followup.send(f"{interaction.user.display_name} added \"{song.title}\" to queue.")

            if not voice_client.is_playing() and not voice_client.is_paused():
                # nothing playing yet: start this song
                await self.play_next(interaction)
            else:
                # something is already playing: just refresh "Up next" on the player
                await self._update_player(guild_id, interaction.channel, paused=voice_client.is_paused())

        except youtube_dl.utils.DownloadError:  # video is private, deleted, restricted, etc.
            await interaction.followup.send(
                "Couldn't load that link. It may be privated, deleted, restricted or not a valid video."
            )
            await self._leave_if_idle(guild_id, voice_client)

        except Exception as e:  # catches any other error
            await interaction.followup.send(f"Error: {str(e)}")
            await self._leave_if_idle(guild_id, voice_client)

    @app_commands.command(name="options", description="brings up music player interface")
    async def options(self, interaction: discord.Interaction):
        '''Moves the player message to the bottom of the channel.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        if not voice_client:
            await interaction.response.send_message("Muse is not connected to a voice chat", ephemeral=True)
            return

        current = self.current_audio.get(guild_id)
        if current is None or not (voice_client.is_playing() or voice_client.is_paused()):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        # delete the old player; _update_player then posts a fresh one at the bottom
        old_message = self.player_messages.pop(guild_id, None)
        if old_message:
            try:
                await old_message.delete()
            except discord.HTTPException:
                pass  # already deleted

        await self._update_player(guild_id, interaction.channel, paused=voice_client.is_paused())
        await interaction.response.send_message("Player moved to the bottom", ephemeral=True)

    # ==================================================================
    # Button handlers (called by MusicControls)
    # ==================================================================

    async def skip(self, interaction: discord.Interaction):
        '''Skip button: stops the current song. The next one (if any) starts automatically.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        if not (voice_client and (voice_client.is_playing() or voice_client.is_paused())):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        song = self.current_audio.get(guild_id)
        # stopping triggers after_playing -> play_next, which starts the next song if there is one
        voice_client.stop()

        user = interaction.user.display_name
        if not self._get_queue(guild_id):
            await interaction.response.send_message(f"{user} stopped {song.title}.")
        else:
            await interaction.response.send_message(f"{user} skipped {song.title}.")

    async def end(self, interaction: discord.Interaction):
        '''End button: clears everything and disconnects from voice.'''
        try:
            voice_client = interaction.guild.voice_client

            if not voice_client or not voice_client.is_connected():
                await interaction.response.send_message(
                    "I'm not connected to any voice channel",
                    ephemeral=True
                )
                return

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
        '''View Queue button: privately shows the next five songs.'''
        queue = self._get_queue(interaction.guild.id)
        embed = discord.Embed(
            title="Next on your queue",
            description="Displays next five songs in your queue.",
            color=discord.Color.purple()
        )

        if not queue:
            msg = "Your queue is empty."
        else:
            msg = ""
            for i, song in enumerate(list(queue)[:5], start=1):
                msg += f"{i}. {song.title} ({song.duration})\n"

        embed.add_field(name="Upcoming:", value=msg, inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================================================================
    # Playback
    # ==================================================================

    async def play_next(self, interaction: discord.Interaction, error=None):
        '''Starts the next song in the server's queue.

        Runs when /play starts the first song, and again every time a song ends
        (through after_playing below), so the queue keeps going by itself.

        Args:
            interaction: The /play interaction that started this session.
            error: An error from the song that just finished, if any.
        '''
        if error:
            await interaction.channel.send(f"Playback error: {error}")

        guild_id = interaction.guild.id

        # queue is empty: the session is over
        server_queue = self.queues.get(guild_id)
        if not server_queue:
            await self._reset_state(guild_id, "Queue finished, use /play to add more")
            if voice_client and voice_client.is_connected():
                self._start_idle_timer(interaction.guild)

            return

        # Muse is no longer in voice (e.g. kicked): clean up instead of trying every song
        voice_client = interaction.guild.voice_client
        if not (voice_client and voice_client.is_connected()):
            await self._reset_state(guild_id, "Disconnected from voice chat")
            return

        song = server_queue.popleft()
        self.current_audio[guild_id] = song

        def after_playing(error):
            '''Called by discord.py (on another thread) when the song ends.'''
            future = asyncio.run_coroutine_threadsafe(
                self.play_next(interaction, error),
                self.bot.loop
            )
            # errors inside play_next would otherwise disappear silently; print them instead
            future.add_done_callback(
                lambda f: f.exception() and print(f"play_next failed: {f.exception()!r}")
            )

        try:
            source = await discord.FFmpegOpusAudio.from_probe(song.stream_url, **self.FFMPEG_OPTIONS)
            voice_client.play(source, after=after_playing)
            self._cancel_idle_timer(guild_id)

        except Exception as e:
            # this song can't be played (e.g. its link expired): skip it so the queue doesn't freeze
            print(f"Unable to play song: {e}")
            await interaction.channel.send(f"Couldn't play {song.title}, skipping.")
            await self.play_next(interaction)
            return

        await self._update_player(guild_id, interaction.channel)

    # ==================================================================
    # Player message (the one embed per server that keeps updating)
    # ==================================================================

    def _now_playing_embed(self, song: Song, guild_id: int, paused: bool = False) -> discord.Embed:
        '''Builds the "Now Playing" card for a song.'''
        embed = discord.Embed(
            title=song.title,
            url=song.webpage_url,
            description=song.uploader,
            color=discord.Color.blue()
        )
        embed.set_author(name="⏸️ Paused" if paused else "🎶 Now Playing")
        embed.set_thumbnail(url=song.thumbnail)
        embed.add_field(name="Duration", value=song.duration or "Live", inline=True)
        embed.add_field(name="Requested by", value=song.requester, inline=True)

        # footer: what plays next
        server_queue = self._get_queue(guild_id)
        if server_queue:
            footer = f"Up next: {server_queue[0].title}"
            if len(server_queue) > 1:
                footer += f" + {len(server_queue) - 1} more"
        else:
            footer = "Queue is empty"
        embed.set_footer(text=footer)

        return embed

    async def _update_player(self, guild_id: int, channel, paused: bool = False):
        '''Shows the current song on the server's player message.

        Edits the existing player if there is one, otherwise posts a new one.
        Always uses channel.send (never an interaction reply), because interaction
        replies can only be edited for 15 minutes.
        '''
        song = self.current_audio.get(guild_id)
        embed = self._now_playing_embed(song, guild_id, paused=paused)
        view = MusicControls(self, paused=paused)

        try:
            message = self.player_messages.get(guild_id)
            if message:
                await message.edit(embed=embed, view=view)
            else:
                self.player_messages[guild_id] = await channel.send(embed=embed, view=view)

        except discord.NotFound:
            # someone deleted the player message: post a new one
            try:
                self.player_messages[guild_id] = await channel.send(embed=embed, view=view)
            except discord.HTTPException as e:
                print(f"Couldn't update player: {e}")

        except discord.HTTPException as e:
            print(f"Couldn't update player: {e}")

    async def _close_player(self, guild_id: int, text: str):
        '''Turns the player into a gray "ended" card with disabled buttons, then forgets it.'''
        message = self.player_messages.pop(guild_id, None)
        if not message:
            return

        closed_card = discord.Embed(title=text, color=discord.Color.dark_gray())

        view = MusicControls(self)
        for item in view.children:
            item.disabled = True

        try:
            await message.edit(embed=closed_card, view=view)
        except discord.HTTPException as e:
            print(f"Couldn't close player: {e}")

    # ==================================================================
    # Session cleanup
    # ==================================================================
    def _cancel_idle_timer(self, guild_id):
        '''
        Cancels bot timeout timer
        '''
        timer = self.idle_timer.pop(guild_id, None)
        if timer:
            timer.cancel()

    def _start_idle_timer(self, guild):
        '''
        Starts timeout timer when bot starts idling
        '''
        self._cancel_idle_timer(guild) # cancels existing timer
        self.idle_timer[guild.id] = asyncio.create_task(self._leave_after_idle(guild))

    async def _leave_after_idle(self, guild):
        '''
        After timer finishes, cleanly disconnect the bot
        '''
        await asyncio.sleep(self.IDLE_TIMEOUT)
        self.idle_timers.pop(guild.id, None)
        voice_client = guild.voice_client

        if voice_client and voice_client.is_connected() and not (voice_client.is_playing() and voice_client.is_paused()):
            await self._reset_and_disconnect(guild.id, voice_client)

    async def _reset_state(self, guild_id: int, text: str):
        '''Forgets this server's music session: clears the queue and current song,
        and closes the player message with `text`.

        Safe to call more than once: if everything is already cleared, it does nothing.
        '''
        self._get_queue(guild_id).clear()
        self.current_audio.pop(guild_id, None)
        self._cancel_idle_timer(guild_id)
        await self._close_player(guild_id, text)

    async def _reset_and_disconnect(self, guild_id: int, voice_client: discord.VoiceClient):
        '''Clears the session, then disconnects from voice.

        The queue is cleared before disconnecting so play_next (triggered when
        playback stops) finds nothing left to play.
        '''
        await self._reset_state(guild_id, "Session ended")
        await voice_client.disconnect()

    async def _leave_if_idle(self, guild_id: int, voice_client: Optional[discord.VoiceClient]):
        '''Disconnects only if the bot is connected and not playing or paused.'''
        if voice_client and not (voice_client.is_playing() or voice_client.is_paused()):
            await self._reset_and_disconnect(guild_id, voice_client)

    # ==================================================================
    # Song lookup (YouTube)
    # ==================================================================

    def _identify_song_input(self, query: str) -> str:
        '''Turns what the user typed in /play into something yt_dlp understands.

        Returns the link unchanged, adds "https://" to a YouTube link typed
        without it, or turns anything else into a YouTube search.
        '''
        query = query.strip()

        # a full link (http:// or https://), play it as-is
        if urlsplit(query).scheme in ('http', 'https'):
            return query

        # found youtube or youtu.be, just needs the https:// part
        if re.match(YT_PATTERN, query):
            return "https://" + query

        # not a link, so it's a song query: use the first YouTube search result.
        # (Checking for http/https above, instead of any scheme, keeps queries with
        # a colon like "Re:Zero opening" from being mistaken for a link.)
        return "ytsearch1:" + query

    def _extract_audio(self, url: str) -> Song:
        '''Uses yt_dlp to look up a link or search and return it as a Song.

        Raises:
            youtube_dl.utils.DownloadError: If the video can't be loaded.
            ValueError: If the link is a playlist/page/search with no videos.
        '''
        with youtube_dl.YoutubeDL(self.YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)

        # playlists and searches come back as a list of entries; use the first one
        if 'entries' in info:
            entries = list(info['entries'])
            if not entries:
                raise ValueError("Couldn't find anything to play. Try a different link or song name.")
            info = entries[0]

        return Song(
            stream_url=info['url'],
            title=info.get('title', 'Unknown Title'),
            webpage_url=info.get('webpage_url', url),
            thumbnail=info.get('thumbnail'),
            duration=self._format_duration(info.get('duration')),
            uploader=info.get('uploader'),
        )

    @staticmethod
    def _format_duration(total_seconds: Optional[int]) -> Optional[str]:
        '''Formats seconds as "m:ss" or "h:mm:ss". Returns None for live streams.'''
        if total_seconds is None:
            return None

        minutes, seconds = divmod(total_seconds, 60)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    # ==================================================================
    # Queue
    # ==================================================================

    def _get_queue(self, guild_id: int) -> Deque[Song]:
        '''Returns the server's queue, creating an empty one if needed.'''
        return self.queues.setdefault(guild_id, deque())


class MusicControls(discord.ui.View):
    '''The buttons under the player message.

    Skip, End and View Queue call the matching handler on MusicPlayer.
    Pause/Resume is one button that switches between the two.
    '''

    def __init__(self, musicPlayer: MusicPlayer, paused: bool = False):
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
        '''Pauses if playing, resumes if paused, and updates the player to match.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client
        song = self.musicPlayer.current_audio.get(guild_id)

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
            embed=self.musicPlayer._now_playing_embed(song, guild_id, paused=paused),
            view=self
        )


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
