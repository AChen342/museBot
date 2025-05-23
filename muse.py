'''
Author: Andrew Chen
Date: 04/29/2025
Description: Main Muse bot program.
'''
import discord
import os
from discord.ext import commands
from dotenv import load_dotenv
import asyncio
import webserver

# Load .env variables
load_dotenv()

# bot info
TOKEN = os.getenv('TOKEN')
APP_ID = os.getenv('APP_ID')

intents = discord.Intents.default()
# manages new slash commands
intents.message_content = True
# don't use both client and bot, use one otherwise the bot won't work
bot = commands.Bot(command_prefix="!", intents=intents, application_id=APP_ID)
tree = bot.tree

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')

# load cog
async def main():
    async with bot:
        await bot.load_extension("musicPlayer")
        await bot.load_extension("utils")
        webserver.keep_alive()
        await bot.start(TOKEN)

# requires bot token to run
asyncio.run(main())