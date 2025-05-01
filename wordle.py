import discord
import random
from discord.ext import commands
from discord import app_commands

class Wordle(commands.Cog):
    NUMWORDS = 0
    WORDLEN = 0
    NUMGUESSES = 5

    def __init__(self, bot):
        self.bot = bot

    '''
    Function: loadWords()
    Description: Loads words from text file containing words. 
    Also updates the number of words available.    
    '''
    def loadWords(self) -> list[str]:
        try:
            # open word file and load words into game
            with open("wordlist.txt", "r") as file:
                lines = [line.rstrip() for line in file]
            
            self.NUMWORDS = len(lines)
            self.WORDLEN = len(lines[0])
            print(f"Loaded a total of {self.NUMWORDS} words of size {self.WORDLEN}.")

            return lines

        except Exception as e:
            print(f"There was an error with loading words: {e}")

    '''
    Function: selectWord()
    Description: randomly selects a word from the word list
    and returns the selected word.
    '''
    def selectWord(self, wordList : list[str]) -> str:
        rand = random.randint(0, self.NUMWORDS - 1)
        
        return wordList[rand]

    '''
    Function: boardSetup()
    Description: Sets up an empty board
    '''
    def boardSetup(self):
        return ["_"*5 for line in range(self.NUMGUESSES)]        


    @app_commands.command(name="wordle", description="starts a game of wordle")
    async def wordle(self, interaction: discord.Interaction):
        await interaction.response.send_message("Starting a game of Wordle!")
        
        wordList = self.loadWords()
        word = self.selectWord(wordList)
        inPlay = True

        def check(message: discord.Message):
            return message.author == interaction.user and message.channel == interaction.channel
        try:
            while inPlay:
                #wait for player input
                message = await self.bot.wait_for("message", check=check, timeout=30.0)
                user_guess = message.content

                #user guess should be a string of size 5        
                if (len(user_guess) != 5) or user_guess.isDigit():
                    await interaction.followup.send("Invalid guess. Please guess a word 5 letters long and no numbers.")
                else:
                    print("valid guess")
                    inPlay = False

        except TimeoutError:
            await interaction.followup.send("You took too long to respond!")            

    @commands.Cog.listener()
    async def on_ready(self):
        try:
            synced = await self.bot.tree.sync()
            print(f"Wordle Game added.")
        except Exception as e:
            print(f"Failed to add Wordle Game: {e}")
    
async def setup(bot):
    await bot.add_cog(Wordle(bot))