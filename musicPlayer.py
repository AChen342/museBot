import asyncio
from typing import Deque, Tuple
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import os
from collections import deque
from discord.ui import Button, View
import copy

class MusicPlayer(commands.Cog):
    '''Discord Cog for playing music through Muse bot

    Handles commands and events for playing, queuing, looping,
    and controlling music in Discord voice channels.
    '''
    FFMPEG_PATH = os.path.join(
        os.path.dirname(__file__),
        'bin',
        'ffmpeg.exe'
    )
    # Options for ffmpeg audio processing
    FFMPEG_OPTIONS = {
        'executable': FFMPEG_PATH,
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -af loudnorm=I=-16:LRA=11:TP=-1.5 -c:a libopus -b:a 32k -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
    }
    # Options yt_dlp extraction
    YDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extract_flat': True,
        'quiet': True,
        'no_warnings': True
    }

    def __init__(self, bot: commands.Bot):
        '''Initializes the MusicPlayer Cog.

        Args:
            bot: The Discord bot instance
        '''
        self.bot = bot
        self.queues = {}
        self.loop_audio = False
        self.is_queue_looping = False
        self.loop_queues = {}
        self.current_audio = None

    @commands.Cog.listener()
    async def on_ready(self):
        '''When bot is ready, loads all custom commands into Discord.

        Args:
            None
        
        Raises:
            Exception: When the bot fails to load music commands into Discord.
        '''
        try:
            await self.bot.tree.sync()
        except Exception as e:
            print(f"Failed to load music commands: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        '''Disconnects bot from voice channel when there are no one in voice chat.

        Args:
            member: Discord user whose voice state changed (joined, disconnect, muted, etc.).
            before: User's voice state before the change (which channel they were in).
            after: The user's voice state after the update.        
        '''
        if not member.guild:
            return
        
        bot_voice_client = member.guild.voice_client
        if not bot_voice_client:
            return
        
        channel = bot_voice_client.channel
        if not channel:
            return

        non_bot_members = [m for m in channel.members if not m.bot]
        if len(non_bot_members) == 0:
            await bot_voice_client.disconnect()

    async def to_queue(self, queue: Deque[Tuple[str, str]], audio_source: Tuple[str, str]):
        ''' Helper function that adds audio source into Deque object.

        Args:
            queue: A Deque object that will be updated.
            audio_source: A tuple containing audio url and audio title.        
        '''
        queue.append(audio_source)

    async def play_next(self, interaction: discord.Interaction, error=None):
        '''Plays the next audio url from a queue.

        Args:
            interaction: Contains information about an interaction between user and bot.
            error: Stores any errors that occurred during audio playback.
        '''
        if error:
            await interaction.response.send_message(f"Playback error: {error}")

        server_name = interaction.guild.name

        if not self.queues[server_name] and self.is_queue_looping:
            self.queues[server_name] = copy.deepcopy(self.loop_queues[server_name])

        server_queue = self.queues[server_name]
        if not server_queue and not self.loop_audio:
            return

        voice_client = interaction.guild.voice_client

        if not self.loop_audio:
            audio_url, audio_title = server_queue.pop()
            self.current_audio = (audio_url, audio_title)
        else:
            audio_url, audio_title = self.current_audio

        source = await discord.FFmpegOpusAudio.from_probe(
            audio_url,
            **self.FFMPEG_OPTIONS
        )      
    
        def after_playing(error):
            asyncio.run_coroutine_threadsafe(
            self.play_next(interaction, error),
            self.bot.loop
            )

        view = MusicControls(self)
        await interaction.followup.send(
            f"Now Playing: \"{audio_title}\"",
            view=view
        )
        
        voice_client.play(source, after=after_playing)

    @app_commands.command(name="play", description="plays a youtube link")
    async def play(self, interaction: discord.Interaction, url: str):
        '''Processes youtube link into audio and plays it through the bot.

        Args:
            url: Youtube url provided by user input to be processed into audio
        
        Raises:
            Exception: If anything goes wrong while processing Youtube link
        '''
        if not interaction.user.voice:
            await interaction.response.send_message(
                "You need to be in a voice chat to use this command.",
                ephemeral=True
            )
            return

        server_name = interaction.guild.name
        user_voice_channel = interaction.user.voice.channel
        bot_voice_client = interaction.guild.voice_client

        try:
            await interaction.response.send_message(f"Adding music to queue.")

            if not bot_voice_client:
                bot_voice_client = await user_voice_channel.connect()

            if bot_voice_client.channel != user_voice_channel:
                await bot_voice_client.move_to(user_voice_channel)

            with youtube_dl.YoutubeDL(self.YDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:  # Playlist case
                    info = info['entries'][0]
                audio_url = info['url']
                audio_title = info.get('title', 'Unknown Title')

            if self.queues.get(server_name) == None:
                self.queues.update({server_name: deque()})
            
            # if queue is not looping then add audio source to regular queue
            # if queue is looping then add audio source to looping queue
            queue = self.loop_queues[server_name] if self.is_queue_looping else self.queues[server_name]

            # add audio to queue            
            await self.to_queue(queue, (audio_url, audio_title))
            await interaction.followup.send(f"Added \"{audio_title}\" to queue.")

            # plays next song in queue
            if not bot_voice_client.is_playing() and not bot_voice_client.is_paused():
                await self.play_next(interaction)

        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}")
            if bot_voice_client and bot_voice_client.is_connected():
                await bot_voice_client.disconnect()
    
    @app_commands.command(name="options", description="brings up music player interface")
    async def options(self, interaction: discord.Interaction):
        '''Discord command that brings up music player options (ie. pause, resume, stop buttons).

        Args:
            interaction: Contains information about an interaction between user and bot.
        '''
        bot_voice_client = interaction.guild.voice_client
        
        if not bot_voice_client:
            await interaction.response.send_message("Muse is not connected to a voice chat")
            return
        
        view = MusicControls(self)
        _, audio_title = self.current_audio
        msg = "Now Paused: " if bot_voice_client.is_paused() else "Now Playing: "
        await interaction.response.send_message(f"{msg}\"{audio_title}\"", view=view)
        
    async def loopQueue(self, interaction: discord.Interaction):
        '''Handles the Loop Queue button interaction
        When the user interacts with the "Loop Queue" button, the bot will loop
        all the audio that are in the server queue.
        '''
        msg = ""
        server_name = interaction.guild.name

        if not self.is_queue_looping:
            self.is_queue_looping = True    
            server_queue = self.queues[server_name]

            if self.loop_queues.get(server_name) is not None:
                self.loop_queues[server_name] = copy.deepcopy(server_queue)
            else:
                self.loop_queues.update({server_name: copy.deepcopy(server_queue)})

            # add first entry
            self.loop_queues[server_name].appendleft(self.current_audio)
            msg = "Current queue will now loop."

        else:
            self.is_queue_looping = False
            self.loop_queues[server_name].clear()
            msg = "Current queue will stop looping."

        await interaction.response.send_message(msg)

    async def loopSong(self, interaction: discord.Interaction):
        '''Handles Loop Song button interaction.
        When the user interacts with the "Loop Song" button, the bot will
        repeat the current audio.
        '''
        msg = ""
        if not self.loop_audio:
            self.loop_audio = True
            msg = "Current song will now loop"
        
        else:
            self.loop_audio = False
            msg = "This song will stop looping"
        
        await interaction.response.send_message(msg)

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

    async def pause(self, interaction: discord.Interaction):
        '''Handles the Pause button interaction.
        Pauses the music player if music player is playing audio.
        '''
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            self.paused = True
            await interaction.response.send_message("Paused music.")
        else:
            await interaction.response.send_message("Nothing is playing.")

    async def view_queue(self, interaction: discord.Interaction):
        '''Handles View Queue button interaction.
        Displays the next five audio in server queue.
        '''
        server_name = interaction.guild.name
        queue = self.queues[server_name] if not self.is_queue_looping else self.loop_queues[server_name]
        msg = ""
        embed = discord.Embed(
            title="Next on your queue",
            description="Displays next five songs in your queue.",
            color=discord.Color.purple()
        )

        if len(queue) == 0:
            msg = "Your queue is empty."
        else:
            for i in range(min(5, len(queue))):
                _, title = queue[i]
                msg += f"{i + 1}. {title}\n"

        embed.add_field(
            name="Upcoming:",
            value=msg,
            inline=False
        )

        await interaction.response.send_message(embed=embed)

    async def skip(self, interaction: discord.Interaction):
        '''Handles the Skip button interaction.
        Skips the current audio playing. Will not skip if there server queue is empty.
        '''
        voice_client = interaction.guild.voice_client
        server_name = interaction.guild.name
        server_queue = self.queues[server_name]

        if len(server_queue) == 0:
            await interaction.response.send_message("Your queue is empty.")
            return
  
        _, current_audio_title = server_queue[0]

        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message(f"Skipped {current_audio_title}.")
        
        elif voice_client and voice_client.is_paused():
            voice_client.resume()
            voice_client.stop()
            await interaction.response.send_message(f"Skipped {current_audio_title}.")
        
        else:
            await interaction.response.send_message("Nothing is playing.")

    async def end(self, interaction: discord.Interaction):
        '''Handles the End button interaction.
        Stops the bot from playing and disconnects the bot from voice channel.
        '''
        voice_client = interaction.guild.voice_client
        server_name = interaction.guild.name

        if not voice_client or not voice_client.is_connected():
            return await interaction.response.send_message(
                "I'm not connected to any voice channel",
                ephemeral=True
            )

        self.loop_audio = False
        self.current_audio = None
        self.is_queue_looping = False
        self.queues[server_name].clear()
        self.loop_queues[server_name].clear()

        if voice_client.is_playing():
            voice_client.stop()

        await voice_client.disconnect()

        await interaction.response.send_message(
            "Stopped playback and disconnected from voice channel"
        )


class MusicControls(discord.ui.View):
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
        '''Skip Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction, button):
        '''End Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.end(interaction)

    @discord.ui.button(label="View Queue", style=discord.ButtonStyle.green)
    async def view_queue_button(self, interaction, button):
        '''View Queue Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.view_queue(interaction)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.gray)
    async def pause_button(self, interaction, button):
        '''Pause Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.pause(interaction)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.blurple)
    async def resume_button(self, interaction, button):
        '''Resume Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.resume(interaction)

    @discord.ui.button(label="Loop Song", style=discord.ButtonStyle.green)
    async def loop_button(self, interaction, button):
        '''Loop Song Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.loopSong(interaction)

    @discord.ui.button(label="Loop Queue", style=discord.ButtonStyle.red)
    async def is_queue_looping_button(self, interaction, button):
        '''Loop Queue Button UI

        Args:
            interaction: Contains information about an interaction between user and bot.
            button: The Button object that was clicked by user
        '''
        await self.musicPlayer.loopQueue(interaction)


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
