'''
Looking up songs on YouTube.

Turns what a user typed in /play (a link or a song name) into a Song
with a playable audio stream, using yt_dlp.
'''
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlsplit

import yt_dlp as youtube_dl


# Matches YouTube links typed without "https://", e.g. "youtube.com/watch?v=..." or "youtu.be/..."
YT_PATTERN = r'^(?:(?:www|m|music)\.)?(?:youtube\.com|youtu\.be)/'

# Options for yt_dlp
YDL_OPTIONS = {
    'format': 'bestaudio/best',
    'quiet': True,
    'no_warnings': True,
    # Force IPv4: YouTube returns 403 Forbidden for stream links tied to our IPv6 address
    'source_address': '0.0.0.0',
    # Other YouTube clients (tv, web, android) often return links that fail with 403;
    # visionos was the only one that worked for every video tested (Nov 2026)
    'extractor_args': {'youtube': {'player_client': ['visionos']}},
    # A video link with &list=... plays just that video, not the whole playlist
    'noplaylist': True,
    # For playlist links, only load the first video (must be a string, not an int)
    'playlist_items': '1'
}

# Raised by extract_audio when a video can't be loaded (private, deleted, restricted, ...)
DownloadError = youtube_dl.utils.DownloadError


@dataclass
class Song:
    '''Everything the bot needs to play and display one song.'''
    stream_url: str            # direct audio link that FFmpeg plays
    title: str
    webpage_url: str           # normal YouTube link, used for the clickable title
    thumbnail: Optional[str]
    duration: Optional[str]    # e.g. "3:33" or "1:02:05"; None for live streams
    uploader: Optional[str]    # YouTube channel name
    requester: str = ""        # mention of the user who added it, e.g. "<@123>"


def identify_song_input(query: str) -> str:
    '''Turns what the user typed in /play into something yt_dlp understands.

    Returns the link unchanged, adds "https://" to a YouTube link typed
    without it, or turns anything else into a YouTube search.
    '''
    query = query.strip()

    # a full link (http:// or https://), play it as-is
    if urlsplit(query).scheme in ('http', 'https'):
        return query

    # found youtube or youtu.be, just needs the https:// part
    if re.match(YT_PATTERN, query):
        return "https://" + query

    # not a link, so it's a song query: use the first YouTube search result.
    # (Checking for http/https above, instead of any scheme, keeps queries with
    # a colon like "Re:Zero opening" from being mistaken for a link.)
    return "ytsearch1:" + query


def extract_audio(url: str) -> Song:
    '''Uses yt_dlp to look up a link or search and return it as a Song.

    This is slow (a few seconds) and blocking, so call it in a background thread.

    Raises:
        DownloadError: If the video can't be loaded.
        ValueError: If the link is a playlist/page/search with no videos.
    '''
    with youtube_dl.YoutubeDL(YDL_OPTIONS) as ydl:
        info = ydl.extract_info(url, download=False)

    # playlists and searches come back as a list of entries; use the first one
    if 'entries' in info:
        entries = list(info['entries'])
        if not entries:
            raise ValueError("Couldn't find anything to play. Try a different link or song name.")
        info = entries[0]

    return Song(
        stream_url=info['url'],
        title=info.get('title', 'Unknown Title'),
        webpage_url=info.get('webpage_url', url),
        thumbnail=info.get('thumbnail'),
        duration=format_duration(info.get('duration')),
        uploader=info.get('uploader'),
    )


def format_duration(total_seconds: Optional[int]) -> Optional[str]:
    '''Formats seconds as "m:ss" or "h:mm:ss". Returns None for live streams.'''
    if total_seconds is None:
        return None

    minutes, seconds = divmod(total_seconds, 60)
    if minutes >= 60:
        hours, minutes = divmod(minutes, 60)
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"
