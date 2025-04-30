'''
Author: Andrew Chen
Date: 04/29/2025
Description: Contains basic commands for Muse bot
'''

import discord
import math
import random
from discord.ext import commands
from discord import app_commands

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
    
    @app_commands.command(name="math", description="command for basic integer arithmetic")
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
                
    @app_commands.command(name="guess", description="simple guessing game")
    async def guess(self, interaction: discord.Interaction):
        #generate number
        rand = random.randint(1, 10)
        numGuesses = 3
        correct = False

        #start game
        await interaction.response.send_message("I'm thinking of a number between 1-10...")

        #makes sure guess is from same user and in the same channel
        def check(message: discord.Message):
            return message.author == interaction.user and message.channel == interaction.channel
        
        try:
            while not correct and numGuesses > 0:
                #waits for a message, checks if it is from same user in same channel, sets a 30s timer.
                message = await self.bot.wait_for("message", check=check, timeout=30.0)

                #get message text
                user_guess = message.content

                #checks if user guess is valid, meaning guess is integer value and between 1-10
                if (not user_guess.isdigit()) or (int(user_guess) < 1 or int(user_guess) > 10) :
                    await interaction.followup.send(f"Invalid guess! Please enter a number between 1-10.")                    
                else:
                    user_guess = int(user_guess)

                    if user_guess == rand:
                        await interaction.followup.send(f"Winner! The number I was thinking of was {rand}.")
                        correct = True
                    else:
                        #decrement num guesses remaining
                        numGuesses-=1

                        #game over if player is not able to guess number in three turns.
                        if numGuesses == 0:
                            await interaction.followup.send(f"Game over! The number I was thinking of was {rand}.")
                        else:
                            await interaction.followup.send(f"Incorrect guess! You have {numGuesses} guesses.")

        except TimeoutError:
            await interaction.followup.send("You took too long to respond!")

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
        

    
    
