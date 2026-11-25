'''
The music cog: slash commands, button logic, playback and cleanup.

Each server gets its own song queue and one "live" player message that
updates as songs change. Song lookups live in youtube.py, the cards in
embeds.py, and the buttons in controls.py.
'''
import asyncio
import os
import random
from collections import deque
from typing import Deque, Optional

import discord
from discord import app_commands
from discord.ext import commands

from .controls import MusicControls
from .embeds import closed_player_embed, now_playing_embed, queue_embed
from .youtube import DownloadError, Song, extract_audio, identify_song_input


# The project folder (one level above this "music" folder), where bin/ffmpeg.exe lives
PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class MusicPlayer(commands.Cog):
    '''Discord cog that plays, queues and controls music for every server.'''

    # ==================================================================
    # Configuration
    # ==================================================================

    # Bundled ffmpeg.exe on Windows; the system-installed ffmpeg everywhere else (e.g. Linux server)
    FFMPEG_PATH = (
        os.path.join(PROJECT_DIR, 'bin', 'ffmpeg.exe')
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

    # Leave voice after this many seconds with nothing playing (use ~20 while testing)
    IDLE_TIMEOUT = 300

    def __init__(self, bot: commands.Bot):
        self.bot = bot

        # Everything below is stored per server, keyed by the server's ID (guild.id)
        self.queues: dict[int, Deque[Song]] = {}               # songs waiting to play
        self.current_audio: dict[int, Song] = {}               # the song playing right now
        self.player_messages: dict[int, discord.Message] = {}  # the live player message
        self.idle_timers: dict[int, asyncio.Task] = {}         # countdown to leave when idle

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
        '''Adds a song to the end of the queue, joining the user's voice channel if needed.

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

            added = await self._add_song(interaction, query)
            if not added:
                # the bot may have joined just for this song; don't leave it sitting there
                await self._leave_if_idle(guild_id, voice_client)

        except Exception as e:  # catches any other error
            await interaction.followup.send(f"Error: {str(e)}")
            await self._leave_if_idle(guild_id, voice_client)

    @app_commands.command(name="playnext", description="play a YouTube link or song right after the current one")
    @app_commands.describe(query="A YouTube link or a song name")
    async def playnext(self, interaction: discord.Interaction, query: str):
        '''Adds a song to the front of the queue, so it plays right after the current one.

        Unlike /play, Muse must already be in the user's voice channel.

        Args:
            query: A YouTube link (with or without https://) or a song name
        '''
        if not await self._check_listener(interaction):
            return

        try:
            # looking up a song takes a few seconds; tell Discord we're working on it
            await interaction.response.defer()
            await self._add_song(interaction, query, to_front=True)

        except Exception as e:  # catches any other error
            await interaction.followup.send(f"Error: {str(e)}")

    @app_commands.command(name="remove", description="remove a song from the queue")
    @app_commands.describe(index="The song's number in View Queue")
    async def remove(self, interaction: discord.Interaction, index: app_commands.Range[int, 1, 100]):
        '''Removes one song from the queue, using the numbers shown in View Queue.

        Args:
            index: The song's position in the queue (1 = plays next)
        '''
        if not await self._check_listener(interaction):
            return

        server_queue = self._get_queue(interaction.guild.id)
        if index > len(server_queue):
            await interaction.response.send_message(
                f"There's no song #{index} in the queue. Check View Queue for the numbers.",
                ephemeral=True
            )
            return

        removed = server_queue[index - 1]
        del server_queue[index - 1]

        await interaction.response.send_message(
            f"{interaction.user.display_name} removed \"{removed.title}\" from the queue."
        )
        await self._refresh_player(interaction)

    @app_commands.command(name="options", description="brings up music player interface")
    async def options(self, interaction: discord.Interaction):
        '''Moves the player message to the bottom of the channel.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        if not voice_client:
            await interaction.response.send_message("Muse is not connected to a voice chat.", ephemeral=True)
            return

        if self.current_audio.get(guild_id) is None or not self._is_active(voice_client):
            await interaction.response.send_message("Nothing is playing.", ephemeral=True)
            return

        # delete the old player; _refresh_player then posts a fresh one at the bottom
        old_message = self.player_messages.pop(guild_id, None)
        if old_message:
            try:
                await old_message.delete()
            except discord.HTTPException:
                pass  # already deleted

        await self._refresh_player(interaction)
        await interaction.response.send_message("Player moved to the bottom.", ephemeral=True)

    # ==================================================================
    # Button handlers (called by MusicControls)
    # ==================================================================

    async def skip(self, interaction: discord.Interaction):
        '''Skip button: stops the current song. The next one (if any) starts automatically.'''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        if not self._is_active(voice_client):
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
                    "I'm not connected to any voice channel.",
                    ephemeral=True
                )
                return

            await self._reset_and_disconnect(interaction.guild.id, voice_client)

            user = interaction.user.display_name
            await interaction.response.send_message(
                f"{user} stopped playback and disconnected bot from voice channel."
            )

        except Exception as e:
            print(f"Error in end: {e}")
            if not interaction.response.is_done():
                await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    async def shuffle(self, interaction: discord.Interaction):
        '''Shuffle button: shuffles the upcoming songs and updates "Up next" on the player.'''
        guild_id = interaction.guild.id
        server_queue = self._get_queue(guild_id)

        if len(server_queue) < 2:
            await interaction.response.send_message("Not enough songs in the queue to shuffle.", ephemeral=True)
            return

        random.shuffle(server_queue)  # shuffles in place

        voice_client = interaction.guild.voice_client
        paused = bool(voice_client and voice_client.is_paused())
        await interaction.response.edit_message(
            embed=self._now_playing_embed(guild_id, paused=paused),
            view=MusicControls(self, paused=paused)
        )

    async def view_queue(self, interaction: discord.Interaction):
        '''View Queue button: privately shows the next five songs.'''
        embed = queue_embed(self._get_queue(interaction.guild.id))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ==================================================================
    # Shared checks
    # ==================================================================

    @staticmethod
    def _is_active(voice_client: Optional[discord.VoiceClient]) -> bool:
        '''True if Muse is connected and a song is playing or paused.'''
        return bool(voice_client and (voice_client.is_playing() or voice_client.is_paused()))

    async def _check_listener(self, interaction: discord.Interaction) -> bool:
        '''Makes sure the user is in Muse's voice channel before changing the queue.

        Returns True if they are. Otherwise privately tells them why not and returns False.
        '''
        voice_client = interaction.guild.voice_client

        if not interaction.user.voice:
            problem = "You need to be in a voice chat to use this command."
        elif not voice_client:
            problem = "Muse isn't playing anything right now."
        elif interaction.user.voice.channel != voice_client.channel:
            problem = "Join Muse's voice channel to use this command."
        else:
            return True

        await interaction.response.send_message(problem, ephemeral=True)
        return False

    # ==================================================================
    # Playback
    # ==================================================================

    async def _add_song(self, interaction: discord.Interaction, query: str, to_front: bool = False) -> bool:
        '''Looks up a song and adds it to the queue, then starts it or refreshes the player.

        Used by /play (end of the queue) and /playnext (front of the queue).
        The interaction must already be deferred.

        Returns True if the song was added. If it couldn't be found, tells the user and returns False.
        '''
        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        # a link plays directly; anything else becomes a YouTube search.
        # The lookup runs in a background thread so the bot doesn't freeze meanwhile.
        try:
            source = identify_song_input(query)
            song = await asyncio.to_thread(extract_audio, source)
        except DownloadError:  # video is private, deleted, restricted, etc.
            await interaction.followup.send(
                "Couldn't load that link. It may be privated, deleted, restricted or not a valid video."
            )
            return False
        except ValueError as e:  # a playlist, page or search with nothing in it
            await interaction.followup.send(str(e))
            return False

        song.requester = interaction.user.mention
        server_queue = self._get_queue(guild_id)
        user = interaction.user.display_name

        if to_front:
            server_queue.appendleft(song)
            await interaction.followup.send(f"{user} added \"{song.title}\" to play next.")
        else:
            server_queue.append(song)
            await interaction.followup.send(f"{user} added \"{song.title}\" to queue.")

        if self._is_active(voice_client):
            # something is already playing: just refresh "Up next" on the player
            await self._refresh_player(interaction)
        else:
            # nothing playing yet: start this song
            await self.play_next(interaction)

        return True

    async def play_next(self, interaction: discord.Interaction, error=None):
        '''Starts the next song in the server's queue.

        Runs when /play or /playnext starts the first song, and again every time
        a song ends (through after_playing below), so the queue keeps going by itself.

        Args:
            interaction: The interaction that started this session.
            error: An error from the song that just finished, if any.
        '''
        if error:
            await interaction.channel.send(f"Playback error: {error}")

        guild_id = interaction.guild.id
        voice_client = interaction.guild.voice_client

        # queue is empty: the session is over (but stay in voice a while in case more songs come)
        server_queue = self.queues.get(guild_id)
        if not server_queue:
            await self._reset_state(guild_id, "Queue finished, use /play to add more")
            if voice_client and voice_client.is_connected():
                self._start_idle_timer(interaction.guild)
            return

        # Muse is no longer in voice (e.g. kicked): clean up instead of trying every song
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

    def _now_playing_embed(self, guild_id: int, paused: bool = False) -> discord.Embed:
        '''Builds the "Now Playing" card for this server's current song and queue.'''
        return now_playing_embed(self.current_audio.get(guild_id), self._get_queue(guild_id), paused=paused)

    async def _refresh_player(self, interaction: discord.Interaction):
        '''Updates the player for the interaction's server, if a song is playing or paused.

        Used after the queue changes (a song is added or removed) or the player is moved.
        '''
        voice_client = interaction.guild.voice_client
        if self._is_active(voice_client) and self.current_audio.get(interaction.guild.id):
            await self._update_player(interaction.guild.id, interaction.channel, paused=voice_client.is_paused())

    async def _update_player(self, guild_id: int, channel, paused: bool = False):
        '''Shows the current song on the server's player message.

        Edits the existing player if there is one, otherwise posts a new one.
        Always uses channel.send (never an interaction reply), because interaction
        replies can only be edited for 15 minutes.
        '''
        embed = self._now_playing_embed(guild_id, paused=paused)
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

        view = MusicControls(self)
        for item in view.children:
            item.disabled = True

        try:
            await message.edit(embed=closed_player_embed(text), view=view)
        except discord.HTTPException as e:
            print(f"Couldn't close player: {e}")

    # ==================================================================
    # Session cleanup
    # ==================================================================

    def _start_idle_timer(self, guild: discord.Guild):
        '''Starts the countdown to leave voice (replacing any countdown already running).'''
        self._cancel_idle_timer(guild.id)
        self.idle_timers[guild.id] = asyncio.create_task(self._leave_after_idle(guild))

    def _cancel_idle_timer(self, guild_id: int):
        '''Stops the countdown to leave voice, if one is running.'''
        timer = self.idle_timers.pop(guild_id, None)
        if timer:
            timer.cancel()

    async def _leave_after_idle(self, guild: discord.Guild):
        '''The countdown itself: waits IDLE_TIMEOUT seconds, then leaves if still idle.'''
        await asyncio.sleep(self.IDLE_TIMEOUT)
        self.idle_timers.pop(guild.id, None)  # this timer is done; forget it before cleaning up

        voice_client = guild.voice_client
        if voice_client and voice_client.is_connected() and not self._is_active(voice_client):
            await self._reset_and_disconnect(guild.id, voice_client)

    async def _reset_state(self, guild_id: int, text: str):
        '''Forgets this server's music session: clears the queue, current song and idle timer,
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
        '''Disconnects right away, but only if the bot is connected and nothing is playing or paused.'''
        if voice_client and not self._is_active(voice_client):
            await self._reset_and_disconnect(guild_id, voice_client)

    # ==================================================================
    # Queue
    # ==================================================================

    def _get_queue(self, guild_id: int) -> Deque[Song]:
        '''Returns the server's queue, creating an empty one if needed.'''
        return self.queues.setdefault(guild_id, deque())
