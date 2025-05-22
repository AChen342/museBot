import asyncio
import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import os
from collections import deque
from discord.ui import Button, View


class MusicControls(discord.ui.View):
    def __init__(self, musicPlayer):
        super().__init__(timeout=None)
        self.musicPlayer = musicPlayer

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.blurple)
    async def skip_button(self, interaction, button):
        await self.musicPlayer.skip(interaction)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.red)
    async def stop_button(self, interaction, button):
        await self.musicPlayer.stop(interaction)

    @discord.ui.button(label="Queue", style=discord.ButtonStyle.green)
    async def view_button(self, interaction, button):
        await self.musicPlayer.view(interaction)


class MusicPlayer(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queues = {}
        self.current_song = "Unknown Title"
        self.prev_song = "Unknown Title"

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
            print(f"successfully synced music commands")
        except Exception as e:
            print(f"Failed to sync music commands due to: {e}")

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

        queue = self.queues[interaction.guild.name]
        if not queue:
            return

        self.prev_song = self.current_song

        audio_url, title = queue.pop()

        FFMPEG_PATH = os.path.join(
            os.path.dirname(__file__),
            'ffmpeg',
            'ffmpeg.exe'
        )

        FFMPEG_OPTIONS = {
            'executable': FFMPEG_PATH,
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn -c:a libopus -b:a 128k -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
        }

        source = await discord.FFmpegOpusAudio.from_probe(
            audio_url,
            **FFMPEG_OPTIONS
        )      
        voice_client = interaction.guild.voice_client

        def after_playing(error):
            asyncio.run_coroutine_threadsafe(
               self.play_next(interaction, error),
               self.bot.loop
            )

        view = MusicControls(self)
        await interaction.followup.send(
            f"Now Playing: {self.current_song}",
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
                self.current_song = info.get('title', 'Unknown Title')

                # add audio to queue
                await self.to_queue(server_name, (audio_url, self.current_song))
                await interaction.followup.send(f"Added {self.current_song} to queue.")

                # plays next song in queue
                if not voice_client.is_playing():
                    await self.play_next(interaction)

        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}")
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()

    async def view(self, interaction: discord.Interaction):
        server_name = interaction.guild.name
        queue = self.queues[server_name]
        msg = "Next on your queue:\n"

        if len(queue) == 0:
            msg = "Your queue is empty."
        else:
            for i in range(min(5, len(queue))):
                _, title = queue[i]
                msg += f"{i + 1}. {title}\n"

        if interaction.response.is_done():
            await interaction.followup.send(msg)
        else:
            await interaction.response.send_message(msg)

    async def skip(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if voice_client and voice_client.is_playing():
            voice_client.stop()
            await interaction.response.send_message(f"Skipped {self.prev_song}.")
        else:
            await interaction.response.send_message("Nothing is playing.")

    async def stop(self, interaction: discord.Interaction):
        voice_client = interaction.guild.voice_client

        if not voice_client or not voice_client.is_connected():
            return await interaction.response.send_message(
                "I'm not connected to any voice channel",
                ephemeral=True
            )

        if not voice_client.is_playing():
            return await interaction.response.send_message(
                "I'm not currently playing anything",
                ephemeral=True
            )

        # Stop playback and clear any remaining audio packets
        voice_client.stop()

        # Properly clean up the connection
        await voice_client.disconnect()

        await interaction.response.send_message(
            "Stopped playback and disconnected from voice channel"
        )


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
