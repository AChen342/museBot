'''
Author: Andrew Chen
Date: 04/29/2025
Description: Contains basic commands for Muse bot
'''

import discord
from discord.ext import commands
from discord import app_commands
import math

class Basic(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    #repeat command
    @app_commands.command(name="repeat", description="repeats a message a number of times")
    async def repeat(self, interaction: discord.Interaction, times: int, message: str = "repeating..."):
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
    
    @app_commands.command(name="intcalc", description="command for basic integer arithmetic")
    async def math(self, interaction: discord.Interaction, op:str, x:int, y:int):
        result = 0

        await interaction.response.defer()

        #perform integer math
        match op:
            case "add":
                result=x+y
            case "sub":
                result=x-y
            case "mult":
                result=x*y
            case "div":
                if y==0:
                    result="undefined"
                else:
                    result=math.floor(x/y)
            case "mod":
                result=x%y
            case "pow":
                result=pow(x,y)
            case _:
                result="unknown operation"
            
        await interaction.channel.send(f"Answer: {result}")
        await interaction.followup.send("Done!")
                

    #syncs commands to Discord
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            synced = await self.bot.tree.sync() #sync slash commands
            print(f"Successfully synced {len(synced)} slash commands.")
        except Exception as e:
            print(f"Failed to sync commands: {e}")

async def setup(bot):
    await bot.add_cog(Basic(bot))
        

    
    
