import discord
from discord.ext import commands
from discord import app_commands
import psutil
import os
import time
import subprocess
import platform
import re

class Utils(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.start_time = time.time()

    @commands.Cog.listener()
    async def on_ready(self):        
        try:
            await self.bot.tree.sync()
            print(f"Utility commands ready.")
        except Exception as e:
            print(f"Failed to load utility commands: {e}")
    
    def ping_google(self):
        # checks if user is on windows or other os
        param = "-n" if platform.system().lower() == "windows" else "-c"

        try:
            return subprocess.check_output(
                ["ping", param, "1", "8.8.8.8"],
                stderr=subprocess.STDOUT,
                universal_newlines=True
            )
        
        except subprocess.CalledProcessError:
            return "Unable to ping google. Check your internet connection"
        
    def parse_connection_time(self, ping_results):
        match = re.search(r'time=([\d]+)ms', ping_results)

        if match:
            return f"{match.group(1)} ms"
        else:
            return "No connection"
     
    @app_commands.command(name="invite", description="shows bot invite link")
    async def invite(self, interaction: discord.Interaction):
        bot_link = "https://discord.com/oauth2/authorize?client_id=1366550966350123018"
        await interaction.response.send_message(f"Sure! Here is my invite link: {bot_link}")
    
    
    @app_commands.command(name="ping", description="does a speed test by pinging Google")
    async def ping(self, interaction: discord.Interaction):
        await interaction.response.defer()

        # network stats
        net_io = psutil.net_io_counters()
        bytes_sent = net_io.bytes_sent
        bytes_recv = net_io.bytes_recv

        mb_sent = bytes_sent / (1024 ** 2)
        mb_recv = bytes_recv / (1024 ** 2)

        # ping google results
        ping_result = self.ping_google()
        ping_ms = self.parse_connection_time(ping_result)

        embed = discord.Embed(
            title="Muse Bot Internet Connection",
            description="View internet connection stats",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Network Usage",
            value=f"Sent: {mb_sent:.2f} MB\nReceived: {mb_recv:.2f} MB",
            inline=False
        )

        embed.add_field(
            name="Speed test",
            value=f"Latency: {ping_ms}\nServer: 8.8.8.8",
            inline=False
        )

        await interaction.followup.send(embed=embed)
    
    @app_commands.command(name="stats", description="displays system resource statistics")
    async def stats(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer()

            # system memory stats
            mem = psutil.virtual_memory()
            avail_ram_mb = mem.available / (1024 ** 2)
            total_ram_mb = mem.total / (1024 ** 2)

            # bot system stats
            process = psutil.Process(os.getpid())
            process.cpu_percent(interval=None)
            bot_cpu = process.cpu_percent(interval=0.1)
            bot_mem = process.memory_percent()
            bot_rss_mb  = process.memory_info().rss / (1024 ** 2)

            # uptime stats
            uptime_seconds = time.time() - self.start_time

            embed = discord.Embed(
                title="System Resource Stats",
                description="See CPU and RAM usage of the system.",
                color=discord.Color.blue()
            )
            
            embed.add_field(
                name="System CPU Usage",
                value=f"{psutil.cpu_percent(interval=0):.2f}%",
                inline=False
            )

            embed.add_field(
                name="System Memory usage",
                value=f"{mem.percent:.2f}% ({avail_ram_mb:,.0f} MB free / {total_ram_mb:,.0f} MB total)",
                inline=False
            )

            uptime_msg = "Bot unavailable."
            if (uptime_seconds // 60) < 1: # less than a minute
                uptime_msg = "A few seconds ago."
            
            elif (uptime_seconds // 60) < 5: # less than 5 minutes
                uptime_msg = "A few minutes ago."
            
            elif (uptime_seconds // 60) < 30: # less than 30 minutes
                uptime_msg = "Less than an hour ago."

            else:
                uptime_msg = f"{(uptime_seconds // 3600):.2f} hours."

            embed.add_field(
                name="System Uptime",
                value=uptime_msg,
                inline=False
            )

            embed.add_field(
                name="Bot Memory Usage",
                value=f"{bot_mem:.2f}% ({bot_rss_mb:.2f} MB)",
                inline=False
            )
            
            await interaction.followup.send(embed=embed)
        
        except Exception as e:
            print(f"There was an error: {e}")


async def setup(bot):
    await bot.add_cog(Utils(bot))