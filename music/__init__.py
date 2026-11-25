'''
Muse's music feature, split into files by job:

    youtube.py   - Song, and looking songs up on YouTube
    embeds.py    - the cards the bot shows (player, closed player, queue)
    controls.py  - the buttons under the player
    cog.py       - MusicPlayer: slash commands, playback and cleanup

muse.py loads this package with bot.load_extension("music"), which calls setup() below.
'''
from .cog import MusicPlayer


async def setup(bot):
    await bot.add_cog(MusicPlayer(bot))
