# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [v2.0.0] - 2025-05-23
### Added
- Skip Button to skip songs in queue
- End Button to end listening session
- View Queue Button to view next five songs in queue
- Pause Button to pause current song playing
- Resume Button to resume playing song
- New /ping command to see bot internet connection
- New /stats command to see bot system resource stats such as
    cpu and memory usage

### Changed
- Switch '/stop' command to be a button

## [v1.0.0] - 2025-05-22
### Added
- New '/play [url]' command to play audio from youtube links
- New '/stop' command to stop playing audio and disconnect from voice channel

### Changed
- Improved audio lag with optimized FFmpeg flags