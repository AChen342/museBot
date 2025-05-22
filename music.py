import discord
from discord.ext import commands
from discord import app_commands
import yt_dlp as youtube_dl
import os

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.queue = {}
        

    @app_commands.command(name="play", description="plays a youtube link")
    async def play(self, interaction: discord.Interaction, url : str):
        #check if user is in voice chat
        if not interaction.user.voice:
            return await interaction.response.send_message("You need to be in a voice chat to use this command.", ephemeral=True)
        
        #get server name
        server_name = interaction.guild.name

        #voice chat where user is when command was entered
        voice_channel = interaction.user.voice.channel

        #creates a voice client
        voice_client = interaction.guild.voice_client

        await interaction.response.send_message(f"Added to queue: {url}")

        try:
            if not voice_client:
                #if bot not already in vc, connect to vc.
                voice_client = await voice_channel.connect()
            elif not voice_client.channel != voice_channel:
                #if bot is in different vc than user
                await voice_client.move_to(voice_channel)

            YDL_OPTIONS = {
                'format': 'bestaudio/best',
                'extract_flat': True,
                'quiet': True,
                'no_warnings': True
            }
            
            FFMPEG_PATH = os.path.join(os.path.dirname(__file__), 'ffmpeg', 'ffmpeg.exe')

            FFMPEG_OPTIONS = {
                'executable': FFMPEG_PATH,
                'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
                'options': '-vn -c:a libopus -b:a 128k -ar 48000 -ac 2 -application lowdelay -bufsize 256k'
            }

            # process youtube video into audio
            with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:  # Playlist case
                    info = info['entries'][0]
                audio_url = info['url']
                title = info.get('title', 'Unknown Title')
                
                source = await discord.FFmpegOpusAudio.from_probe(
                    audio_url,
                    **FFMPEG_OPTIONS
                )
                
                # if bot is already playing audio, stop and play next audio
                if voice_client.is_playing():
                    voice_client.stop()
                
                voice_client.play(source)
                await interaction.followup.send(f"Now playing: {title}")
                
        except Exception as e:
            await interaction.followup.send(f"Error: {str(e)}")
            if voice_client and voice_client.is_connected():
                await voice_client.disconnect()

    @app_commands.command(name="stop", description="Stops playing current audio and clears the queue")
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

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            synced = await self.bot.tree.sync()
            print(f"successfully synced music commands")
        except Exception as e:
            print(f"Failed to sync music commands due to: {e}")
    
async def setup(bot):
    await bot.add_cog(Music(bot))