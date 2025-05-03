import discord
import random
from discord.ext import commands
from discord import app_commands

class Wordle(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.activeGames = {}
        self.wordLen = 0
        self.totalGuesses = 5
        self.wordList = []
        self.numWords = 0

    '''
    Function: loadWords()
    Description: Loads words from text file containing words. 
    Also updates the number of words available.    
    '''
    def loadWords(self):
        try:
            # open word file and load words into game
            with open("wordlist.txt", "r") as file:
                lines = [line.rstrip() for line in file]
            
            self.numWords = len(lines)
            self.wordLen = len(lines[0])
            self.wordList = lines

            print(f"Loaded {self.numWords} words of size {self.wordLen}.")

        except Exception as e:
            print(f"There was an error with loading words: {e}")

    '''
    Function: selectWord()
    Description: randomly selects a word from the word list
    and returns the selected word.
    '''
    def selectWord(self) -> str:
        return self.wordList[random.randint(0, self.numWords - 1)]

    '''
    Function: boardSetup()
    Description: Sets up an empty board
    '''
    def boardSetup(self):
        return ["#"*5 for line in range(self.totalGuesses)]

    def display(self, board):
        result = ""
        for line in board:
            result+=line+"\n"

        return result.rstrip()

    '''
    Function: wordle()
    Description: main function that controls wordle game
    '''
    async def game(self, interaction : discord.Interaction):
        word = self.selectWord()
        play = True
        tries = self.totalGuesses
        board = self.boardSetup()

        #intro prompt
        await interaction.response.send_message(f"Starting a game of Wordle!\n{self.display(board)}")

        def check(message: discord.Message):
            return message.author == interaction.user and message.channel == interaction.channel
        
        while play:
            #wait for player input
            message = await self.bot.wait_for("message", check=check, timeout=30.0)
            userGuess = message.content
            followup = ""

            #user guess should be a string of size 5        
            if (len(userGuess) != 5) or not userGuess.isalpha():
                await interaction.followup.send("Please guess a word 5 letters long.")
            else:
                followup = f"You guessed: {userGuess}.\n"
                
                if tries <= 1:
                    play = False
                    followup += f"You are out of guesses. The word was: {word}."
                else:
                    tries-=1
                    followup += f"{tries} guesses remaining."
                
                await interaction.followup.send(followup)
                

        await interaction.followup.send("Thanks for playing!")

    '''
    command that triggers wordle game.
    '''
    @app_commands.command(name="wordle", description="starts a game of wordle")
    async def wordle(self, interaction: discord.Interaction):
        userId = interaction.user

        #prevents user from starting multiple games at once.
        if userId in self.activeGames:
            await interaction.response.send_message("You are in an existing game already. Please complete current game.")
            return
                
        self.activeGames[userId] = True
        
        #load words
        if not self.wordList:
            self.loadWords()
        
        try:
            # play wordle
            await self.game(interaction)

        except TimeoutError:
            await interaction.followup.send("Game timed out.")

        except Exception as e:
            print(f"encountered error {e}")

        finally:
            del self.activeGames[userId]            

    '''
    syncs commands from this cog to discord.
    '''
    @commands.Cog.listener()
    async def on_ready(self):
        try:
            await self.bot.tree.sync()
            print(f"Wordle Game added.")
        except Exception as e:
            print(f"Failed to add Wordle Game: {e}")
    
async def setup(bot):
    await bot.add_cog(Wordle(bot))