import discord
import os
from discord.ext import commands
from dotenv import load_dotenv

# Load .env variables
load_dotenv()

#bot info
TOKEN = os.getenv('TOKEN')
APP_ID = os.getenv('APP_ID')

intents = discord.Intents.default()
#manages new slash commands
intents.message_content = True
#don't use both client and bot, use one otherwise the bot won't work
bot = commands.Bot(command_prefix="!", intents=intents, application_id=APP_ID)
tree = bot.tree

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user} (ID: {bot.user.id})')
    #need to sync tree so that custom slash commands will appear in Discord
    try:
        synced = await tree.sync() #sync slash commands
        print(f"Successfully synced {len(synced)} slash commands.")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    print('------')

#repeat command
@tree.command(name="repeat", description="repeats a message a number of times")
async def repeat(interaction: discord.Interaction, times: int, message: str = "repeating..."):
    MAX_REPEAT = 10

    # limits repeat amount to 10
    try:
        if times > MAX_REPEAT:
            await interaction.response.send_message("Number of repetitions cannot exceed 10.")

        else:
            await interaction.response.defer()

            for i in range(times):
                await interaction.channel.send(message)

            await interaction.followup.send("Done!", ephemeral=True)
    
    except Exception as e:
        await interaction.response.send_message("Command failed.")
        print(f"Failed to execute command: {e}")

#basic arithmetic command
'''
@tree.command()
async def calc(ctx, op, x:int, y:int):
    result = 0

    match op:
        case "add":
            result=x+y
        case "sub":
            result=x-y
        case "mult":
            result=x*y
        case "div":
            if y==0:
                result="Undefined"
            else:
                result=x/y
        case "mod":
            result=x%y
        case "pow":
            result=x**y
        case _:
            result= "Undefined operation"

    await ctx.send(result)
'''

# requires bot token to run
bot.run(TOKEN)