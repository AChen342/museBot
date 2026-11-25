'''
The cards (embeds) the bot shows: the "Now Playing" player, the closed
player, and the View Queue list.
'''
from typing import Deque

import discord

from .youtube import Song


def now_playing_embed(song: Song, server_queue: Deque[Song], paused: bool = False) -> discord.Embed:
    '''Builds the "Now Playing" card for a song, with "Up next" from the queue.'''
    embed = discord.Embed(
        title=song.title,
        url=song.webpage_url,
        description=song.uploader,
        color=discord.Color.blue()
    )
    embed.set_author(name="⏸️ Paused" if paused else "🎶 Now Playing")
    embed.set_thumbnail(url=song.thumbnail)
    embed.add_field(name="Duration", value=song.duration or "Live", inline=True)
    embed.add_field(name="Requested by", value=song.requester, inline=True)

    # footer: what plays next
    if server_queue:
        footer = f"Up next: {server_queue[0].title}"
        if len(server_queue) > 1:
            footer += f" + {len(server_queue) - 1} more"
    else:
        footer = "Queue is empty"
    embed.set_footer(text=footer)

    return embed


def closed_player_embed(text: str) -> discord.Embed:
    '''The gray card the player turns into when the session ends.'''
    return discord.Embed(title=text, color=discord.Color.dark_gray())


def queue_embed(server_queue: Deque[Song]) -> discord.Embed:
    '''The private View Queue card: the next five songs.'''
    embed = discord.Embed(
        title="Next on your queue",
        description="Displays next five songs in your queue.",
        color=discord.Color.purple()
    )

    if not server_queue:
        msg = "Your queue is empty."
    else:
        msg = ""
        for i, song in enumerate(list(server_queue)[:5], start=1):
            msg += f"{i}. {song.title} ({song.duration or 'Live'})\n"

    embed.add_field(name="Upcoming:", value=msg, inline=False)
    return embed
