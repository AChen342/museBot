# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v3.1.0] - 2026-11-25
### Added
- Loop button that switches between three modes: off, song (repeat the current song)
  and queue (repeat the whole queue); loop modes are unique to each server
- The Loop button shows the current mode (🔁 Loop: Off, 🔂 Loop: Song, 🔁 Loop: Queue)
- Muse announces who changed the loop mode

### Changed
- Player buttons are now in two rows: Skip, End, Shuffle, Pause on the first,
  Loop and View Queue on the second
- Skip while looping a song moves on to the next song (which then loops);
  skip while looping the queue keeps the skipped song in the rotation
- Loop turns off when the session ends (End, idle timeout, kicked, or everyone leaves)

### Fixed
- Songs whose stream link expired (after a few hours, e.g. in a long loop) are looked up
  again and keep playing instead of being skipped
- A song that really can't be played is skipped once instead of repeating "Couldn't play"
  forever while looping

## [v3.0.0] - 2026-11-25
### Added
- "/play" can now search YouTube by song name, not just play links
  (links without "https://", like "youtu.be/...", also work)
- New "/playnext" command to add a song to the front of the queue
- New "/remove" command to remove a song from the queue by its View Queue number
- Shuffle button to shuffle the upcoming songs
- "Now Playing" card (embed) with thumbnail, clickable title, channel, duration,
  who requested it, and what plays next
- One live player message per server that updates as songs change, instead of a
  new message for every song; it closes with "Queue finished" or "Session ended"
- Emoji icons on all player buttons
- Song durations shown on the player and in View Queue
- Muse leaves the voice channel after 5 minutes with nothing playing
- Muse names who skipped, stopped, added or removed a song

### Changed
- Pause and Resume are now one button that switches between the two
- "/options" now moves the player to the bottom of the channel
- Only people in Muse's voice channel can use the player buttons, "/playnext" and "/remove"
  (View Queue stays open to everyone)
- Error messages and button feedback ("Nothing is playing", View Queue) are now private
- Queues and the current song are now tracked per server by server ID
- Song lookups run in the background, so the bot no longer freezes while searching
- Audio bitrate raised from 32 kbps to 128 kbps
- Updated to discord.py 2.7.1 (needed for Discord's new voice encryption) and pinned
  davey 0.1.7; requires Python 3.14
- Updated yt-dlp; YouTube lookups now use IPv4 and the "visionos" client to avoid
  403 errors
- Uses the system FFmpeg on Linux so the bot can run on a Linux server
- Split musicPlayer.py into a "music" package (youtube, embeds, controls, cog)

### Fixed
- Queue no longer stops after 15 minutes
- Skip now works on the last song and names the song being skipped
- A song that fails to load is skipped instead of freezing the queue
- One bad link no longer disconnects the bot while other songs are playing
- Muse cleans up its queue and player when kicked from voice or when everyone leaves
- Playlist and "Mix" links no longer show "Unknown Title" or fail to play
- Playback errors are now logged instead of disappearing silently

### Removed
- "/ping", "/stats" and "/invite" commands (utils cog no longer loaded)

## [v2.2.0] - 2025-09-08
### Removed
- Removed all looping functions

### Updated
- Updated discord.py and yt-dlp

## [v2.1.0] - 2025-05-25
### Added
- Loop song button to repeat current song
- Loop queue button to repeat entire queue, loop queues are now unique to each discord server
- New "/options" command to bring up music player user interface
- Added FFMPEG flag to make volume for all audio sources consistent

### Changed
- When clicking on view queue button, bot should send an embedded message

## [v2.0.0] - 2025-05-23
### Added
- Skip Button to skip songs in queue
- End Button to end listening session
- View Queue Button to view next five songs in queue
- Pause Button to pause current song playing
- Resume Button to resume playing song
- New "/ping" command to see bot internet connection
- New "/stats" command to see bot system resource stats such as
    cpu and memory usage

### Changed
- Switch '/stop' command to be a button

## [v1.0.0] - 2025-05-22
### Added
- New '/play [url]' command to play audio from youtube links
- New '/stop' command to stop playing audio and disconnect from voice channel

### Changed
- Improved audio lag with optimized FFmpeg flags