import asyncio
import subprocess
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import os
from collections import deque
from discord.ui import Button, View
import copy


class MusicControls(discord.ui.View):
    def __init__(self, musicPlayer):
        super().__init__(timeout=None)
        self.musicPlayer = musicPlayer

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple)
    async def skip_button(self, interaction, button):
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="End", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction, button):
        await self.musicPlayer.end(interaction)

    @discord.ui.button(label="View Queue", style=discord.ButtonStyle.green)
    async def view_queue_button(self, interaction, button):
        await self.musicPlayer.view_queue(interaction)

    @discord.ui.button(label="Pause", style=discord.ButtonStyle.gray)
    async def pause_button(self, interaction, button):
        await self.musicPlayer.pause(interaction)

    @discord.ui.button(label="Resume", style=discord.ButtonStyle.blurple)
    async def resume_button(self, interaction, button):
        await self.musicPlayer.resume(interaction)

    @discord.ui.button(label="Loop Song", style=discord.ButtonStyle.green)
    async def loop_button(self, interaction, button):
        await self.musicPlayer.loopSong(interaction)

    @discord.ui.button(label="Loop Queue", style=discord.ButtonStyle.red)
    async def is_queue_looping_button(self, interaction, button):
        await self.musicPlayer.loopQueue(interaction)
    

class MusicPlayer(commands.Cog):
    TEST_AUDIO = "https://www.youtube.com/watch?v=V4QuRe-JLDo"

    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.loop_audio = False
        self.is_queue_looping = False
        self.loop_queues = {}
        self.current_audio = None

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
            print(f"Music Player commands ready.")
        except Exception as e:
            print(f"Failed to load music commands: {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild:
            return
        
        voice_client = member.guild.voice_client
        if not voice_client or not voice_client.is_connected():
            return
        
        channel = voice_client.channel
        if not channel:
            return

        non_bot_members = [m for m in channel.members if not m.bot]
        if len(non_bot_members) == 0:
            await voice_client.disconnect()


    async def to_queue(self, server_name, source):
        # adds song to queue
        if len(self.queues) == 0 or server_name not in self.queues.keys():
            new_queue = deque()
            new_queue.append(source)
            self.queues.update({server_name: new_queue})
        else:
            queue = self.queues[server_name]
            queue.append(source)

    async def play_next(self, interaction: discord.Interaction, error=None):
        if error:
            await interaction.response.send_message(f"Playback error: {error}")

        server_name = interaction.guild.name
        
        if self.is_queue_looping and len(self.queues[server_name]) == 0:
            self.queues[server_name] = copy.deepcopy(self.loop_queues[server_name])

        queue = self.queues[server_name]
        if not queue and not self.loop_audio:
            return

        FFMPEG_PATH = os.path.join(
            os.path.dirname(__file__),
            'bin',
            'ffmpeg.exe'
        )

        FFMPEG_OPTIONS = {
            'executable': FFMPEG_PATH,
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn -af loudnorm=I=-16:LRA=11:TP=-1.5 -c:a libopus -b:a 32k -ar 48000 -ac 2 -application lowdelay -bufsize 256k',
            'creationflags': subprocess.CREATE_NO_WINDOW
        }

        voice_client = interaction.guild.voice_client

        if not self.loop_audio:
            audio_url, audio_title = queue.pop()
            self.current_audio = (audio_url, audio_title)
        else:
            audio_url, audio_title = self.current_audio

        source = await discord.FFmpegOpusAudio.from_probe(
            audio_url,
            **FFMPEG_OPTIONS
        )      
    
        def after_playing(error):
            asyncio.run_coroutine_threadsafe(
            self.play_next(interaction, error),
            self.bot.loop
            )

        view = MusicControls(self)
        await interaction.followup.send(
            f"Now Playing: {audio_title}",
            view=view
        )
        
        voice_client.play(source, after=after_playing)

    @app_commands.command(name="play", description="plays a youtube link")
    async def play(self, interaction: discord.Interaction, url: str):
        # check if user is in voice chat
        if not interaction.user.voice:
            return await interaction.response.send_message(
                "You need to be in a voice chat to use this command.",
                ephemeral=True
            )

        server_name = interaction.guild.name

        # voice chat where user is when command was entered
        voice_channel = interaction.user.voice.channel

        # creates a voice client
        voice_client = interaction.guild.voice_client

        try:
            await interaction.response.send_message(f"Adding music to queue.")

            if not voice_client:
                # if bot not already in vc, connect to vc.
                voice_client = await voice_channel.connect()
            elif not voice_client.channel != voice_channel:
                # if bot is in different vc than user
                await voice_client.move_to(voice_channel)

            YDL_OPTIONS = {
                'format': 'bestaudio/best',
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True
            }

            # process youtube video into audio
            with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:  # Playlist case
                    info = info['entries'][0]
                audio_url = info['url']
                audio_title = info.get('title', 'Unknown Title')

                # add audio to queue
                await self.to_queue(
                    server_name, 
                    (audio_url, audio_title) # youtube link, youtube title
                )
                await interaction.followup.send(f"Added {audio_title} to queue.")

                # plays next song in queue
                if not voice_client.is_playing() and not voice_client.is_paused():
                    await self.play_next(interaction)
                

        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}")
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()
    
    @app_commands.command(name="options", description="brings up music player interface")
    async def options(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        
        if not voice_client or not voice_client.is_connected():
            await interaction.response.send_message("Muse is not connected to a voice chat")
            return
        
        view = MusicControls(self)
        _, audio_title = self.current_audio
        if voice_client.is_paused():
            await interaction.response.send_message(f"Now Paused: {audio_title}", view=view)
        else:
            await interaction.response.send_message(f"Now Playing: {audio_title}", view=view)

    async def loopQueue(self, interaction: discord.Interaction):
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
        msg = ""
        if not self.loop_audio:
            self.loop_audio = True
            msg = "Current song will now loop"
        
        else:
            self.loop_audio = False
            msg = "This song will stop looping"
        
        await interaction.response.send_message(msg)

    async def resume(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_paused():
            voice_client.resume()
            await interaction.response.send_message("Resumed music.")
        else:
            await interaction.response.send_message("Nothing is paused.")

    async def pause(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client
        if voice_client and voice_client.is_playing():
            voice_client.pause()
            self.paused = True
            await interaction.response.send_message("Paused music.")
        else:
            await interaction.response.send_message("Nothing is playing.")

    async def view_queue(self, interaction: discord.Interaction):
        server_name = interaction.guild.name
        queue = self.queues[server_name]
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


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
