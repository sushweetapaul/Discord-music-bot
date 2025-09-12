#!/usr/bin/env python3
"""
Auralux Discord Music Bot
A feature-rich Discord music bot with YouTube and Spotify integration
"""

from keep_alive import keep_alive
import discord
from discord.ext import commands, tasks
import asyncio
import yt_dlp
#import spotipy
#from spotipy.oauth2 import SpotifyClientCredentials
import os
from collections import deque
import sys

# Load opus library properly on Linux
try:
    discord.opus.load_opus('libopus.so.0')
    print("✅ Opus library loaded successfully")
except:
    try:
        discord.opus.load_opus('opus')
        print("✅ Opus library loaded (fallback)")
    except:
        print("❌ Failed to load opus library. Install with: sudo apt install libopus0 libopus-dev")
        sys.exit(1)

# Bot configuration
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents, help_command=None)

# Premium users and servers - Edit these lists to add premium access
PREMIUM_USERS = []  # Add Discord user IDs: [123456789, 987654321]
PREMIUM_SERVERS = []  # Add Discord server IDs: [123456789, 987654321]

# Music state storage
music_queues = {}      # server_id: deque of songs
current_songs = {}     # server_id: current song info
voice_clients = {}     # server_id: voice_client
loop_states = {}       # server_id: True/False
stay_forever = {}      # server_id: True/False
volumes = {}           # server_id: volume (0.0-1.0)

# YT-DLP configuration for regular quality
ytdl_format_options = {
    'format': 'bestaudio[ext=m4a]/bestaudio[ext=mp3]/bestaudio',
    'outtmpl': '/tmp/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1:',
    'extractaudio': False,
    'skip_download': True
    'cookiefile': 'cookies.txt', 
}

# YT-DLP configuration for high quality (premium users)
ytdl_format_options_hq = {
    'format': 'bestaudio[acodec=opus]/bestaudio[ext=m4a]/bestaudio',
    'outtmpl': '/tmp/%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'ytsearch1:',
    'extractaudio': False,
    'skip_download': True
    'cookiefile': 'cookies.txt', 
}

# FFmpeg options for audio processing
ffmpeg_options = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)
ytdl_hq = yt_dlp.YoutubeDL(ytdl_format_options_hq)

# Spotify client (optional - set credentials in environment)
#spotify = None
#try:
    #if os.getenv('SPOTIFY_CLIENT_ID') and os.getenv('SPOTIFY_CLIENT_SECRET'):
      #  client_credentials_manager = SpotifyClientCredentials(
        #    client_id=os.getenv('SPOTIFY_CLIENT_ID'),
        #    client_secret=os.getenv('SPOTIFY_CLIENT_SECRET')
     #   )
     #   spotify = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
    #    print("✅ Spotify integration enabled")
  #  else:
    #    print("⚠️ Spotify credentials not found. Only YouTube search available.")
#except Exception as e:
 #   print(f"⚠️ Spotify setup failed: {e}")

def is_premium(ctx):
    """Check if user or server has premium access"""
    return ctx.author.id in PREMIUM_USERS or ctx.guild.id in PREMIUM_SERVERS

async def search_youtube(query):
    """Search YouTube for a song"""
    try:
        loop = asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(f"ytsearch:{query}", download=False))
        if data and 'entries' in data and data['entries']:
            return data['entries'][0]
    except Exception as e:
        print(f"YouTube search error: {e}")
    return None

#async def search_spotify(query):
 #   """Search Spotify for a song"""
 #   if not spotify:
    #    return None
    
#    try:
   #     results = spotify.search(q=query, type='track', limit=1)
  #      if results and 'tracks' in results and results['tracks']['items']:
 #           track = results['tracks']['items'][0]
   #         search_query = f"{track['artists'][0]['name']} {track['name']}"
       #     return await search_youtube(search_query)
  #  except Exception as e:
     #   print(f"Spotify search error: {e}")
    #return None

async def get_song_info(query, high_quality=False):
    """Get song information from YouTube or Spotify"""
    song_info = await search_youtube(query)
    
 #   if not song_info:
  #      song_info = await search_spotify(query)
    
    if song_info:
        if high_quality:
            try:
                loop = asyncio.get_event_loop()
                hq_data = await loop.run_in_executor(None, lambda: ytdl_hq.extract_info(song_info['webpage_url'], download=False))
                song_info = hq_data
            except:
                pass
        
        return {
            'url': song_info.get('url', ''),
            'title': song_info.get('title', 'Unknown'),
            'duration': song_info.get('duration', 0),
            'webpage_url': song_info.get('webpage_url', '')
        }
    return None

@bot.event
async def on_ready():
    print(f'🎵 {bot.user} is online and ready to rock!')
    print(f'📊 Servers: {len(bot.guilds)}')
    cleanup_disconnected.start()

@tasks.loop(minutes=1)
async def cleanup_disconnected():
    """Clean up disconnected voice clients"""
    to_remove = []
    for guild_id, vc in voice_clients.items():
        if not vc.is_connected():
            to_remove.append(guild_id)
    
    for guild_id in to_remove:
        for storage in [voice_clients, music_queues, current_songs]:
            storage.pop(guild_id, None)

@bot.command(name='play')
async def play(ctx, *, query):
    """Play a song or add it to queue"""
    if not ctx.author.voice:
        await ctx.send("❌ You need to be in a voice channel to use this command!")
        return
    
    use_hq = is_premium(ctx)
    song_info = await get_song_info(query, use_hq)
    
    if not song_info:
        await ctx.send("❌ Could not find the song. Please try a different search term.")
        return
    
    guild_id = ctx.guild.id
    
    # Initialize guild data
    if guild_id not in music_queues:
        music_queues[guild_id] = deque()
        volumes[guild_id] = 0.5
        loop_states[guild_id] = False
        stay_forever[guild_id] = False
    
    # Connect to voice channel
    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        voice_channel = ctx.author.voice.channel
        voice_clients[guild_id] = await voice_channel.connect()
    
    # Add to queue
    music_queues[guild_id].append(song_info)
    
    # Start playing if nothing is playing
    if guild_id not in current_songs or not voice_clients[guild_id].is_playing():
        await play_next(ctx)
    else:
        position = len(music_queues[guild_id])
        await ctx.send(f"✅ Added to queue: **{song_info['title']}** (Position: {position})")

async def play_next(ctx):
    """Play the next song in queue"""
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or not music_queues[guild_id]:
        if not stay_forever.get(guild_id, False):
            await start_disconnect_timer(ctx)
        return
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_connected():
        return
    
    # Get next song
    if not loop_states.get(guild_id, False):
        song_info = music_queues[guild_id].popleft()
    else:
        song_info = music_queues[guild_id][0] if music_queues[guild_id] else None
        if not song_info:
            return
    
    current_songs[guild_id] = song_info
    
    # Create audio source
    try:
        source = discord.FFmpegPCMAudio(song_info['url'], **ffmpeg_options)
        volume = volumes.get(guild_id, 0.5)
        source = discord.PCMVolumeTransformer(source, volume=volume)
    except Exception as e:
        print(f"Audio source error: {e}")
        await ctx.send("❌ Error creating audio source. Skipping...")
        await play_next(ctx)
        return
    
    # Play the song
    def after_song(error):
        if error:
            print(f'Player error: {error}')
        asyncio.run_coroutine_threadsafe(after_play(ctx, error), bot.loop)
    
    try:
        voice_clients[guild_id].play(source, after=after_song)
        duration_str = f"{song_info['duration'] // 60}:{song_info['duration'] % 60:02d}" if song_info['duration'] else "Unknown"
        await ctx.send(f"🎵 Now playing: **{song_info['title']}** ({duration_str})")
    except Exception as e:
        print(f"Playback error: {e}")
        await ctx.send("❌ Playback failed. Skipping...")
        await play_next(ctx)

async def after_play(ctx, error):
    """Called after a song finishes playing"""
    if error:
        print(f'Player error: {error}')
    
    await asyncio.sleep(1)
    await play_next(ctx)

async def start_disconnect_timer(ctx):
    """Start 5-minute disconnect timer"""
    guild_id = ctx.guild.id
    
    await asyncio.sleep(300)  # 5 minutes
    
    if (guild_id in voice_clients and 
        voice_clients[guild_id].is_connected() and 
        not voice_clients[guild_id].is_playing() and
        not stay_forever.get(guild_id, False)):
        
        await ctx.send("Thanks for using Auralux music bot, hope you had a good experience 😊")
        await voice_clients[guild_id].disconnect()
        
        for storage in [voice_clients, current_songs]:
            storage.pop(guild_id, None)

@bot.command(name='skip')
async def skip(ctx):
    """Skip the current song"""
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_playing():
        await ctx.send("❌ No music is currently playing!")
        return
    
    voice_clients[guild_id].stop()
    await ctx.send("⏭️ Skipped the current song!")

@bot.command(name='pause')
async def pause(ctx):
    """Pause the current song"""
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_playing():
        await ctx.send("❌ No music is currently playing!")
        return
    
    voice_clients[guild_id].pause()
    await ctx.send("⏸️ Music paused!")

@bot.command(name='resume')
async def resume(ctx):
    """Resume the paused song"""
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients or not voice_clients[guild_id].is_paused():
        await ctx.send("❌ No music is currently paused!")
        return
    
    voice_clients[guild_id].resume()
    await ctx.send("▶️ Music resumed!")

@bot.command(name='stop')
async def stop(ctx):
    """Stop the music and start disconnect timer"""
    guild_id = ctx.guild.id
    
    if guild_id not in voice_clients:
        await ctx.send("❌ Bot is not connected to a voice channel!")
        return
    
    voice_clients[guild_id].stop()
    music_queues[guild_id].clear()
    current_songs.pop(guild_id, None)
    
    await ctx.send("⏹️ Music stopped! I'll stay here for 5 more minutes.")
    await start_disconnect_timer(ctx)

@bot.command(name='volume')
async def volume(ctx, vol: int):
    """Change the volume (0-100)"""
    guild_id = ctx.guild.id
    
    if vol < 0 or vol > 100:
        await ctx.send("❌ Volume must be between 0 and 100!")
        return
    
    volumes[guild_id] = vol / 100
    
    if guild_id in voice_clients and voice_clients[guild_id].source:
        voice_clients[guild_id].source.volume = vol / 100
    
    await ctx.send(f"🔊 Volume set to {vol}%!")

@bot.command(name='loop')
async def loop(ctx):
    """Toggle loop for current song"""
    guild_id = ctx.guild.id
    
    if guild_id not in current_songs:
        await ctx.send("❌ No music is currently playing!")
        return
    
    loop_states[guild_id] = not loop_states.get(guild_id, False)
    status = "enabled" if loop_states[guild_id] else "disabled"
    await ctx.send(f"🔄 Loop {status}!")

@bot.command(name='queue')
async def queue(ctx):
    """Show the current queue"""
    guild_id = ctx.guild.id
    
    if guild_id not in music_queues or not music_queues[guild_id]:
        await ctx.send("📭 The queue is empty!")
        return
    
    queue_text = "📋 **Current Queue:**\n"
    for i, song in enumerate(list(music_queues[guild_id])[:10], 1):
        queue_text += f"{i}. {song['title']}\n"
    
    if len(music_queues[guild_id]) > 10:
        queue_text += f"... and {len(music_queues[guild_id]) - 10} more songs"
    
    await ctx.send(queue_text)

@bot.command(name='nowplaying')
async def nowplaying(ctx):
    """Show currently playing song"""
    guild_id = ctx.guild.id
    
    if guild_id not in current_songs:
        await ctx.send("❌ No music is currently playing!")
        return
    
    song = current_songs[guild_id]
    duration_str = f"{song['duration'] // 60}:{song['duration'] % 60:02d}" if song['duration'] else "Unknown"
    
    embed = discord.Embed(title="🎵 Now Playing", color=0x00ff00)
    embed.add_field(name="Title", value=song['title'], inline=False)
    embed.add_field(name="Duration", value=duration_str, inline=True)
    embed.add_field(name="Loop", value="✅" if loop_states.get(guild_id, False) else "❌", inline=True)
    
    await ctx.send(embed=embed)

@bot.command(name='hq')
async def high_quality(ctx):
    """Enable high quality mode (Premium feature)"""
    if not is_premium(ctx):
        await ctx.send("🔒 It is a premium feature, dm windyy_918 to get premium.")
        return
    
    await ctx.send("✨ High quality mode is now active for your next songs!")

@bot.command(name='stay')
async def stay(ctx):
    """Make bot stay in voice channel forever (Premium feature)"""
    if not is_premium(ctx):
        await ctx.send("🔒 It is a premium feature, dm windyy_918 to get premium.")
        return
    
    guild_id = ctx.guild.id
    stay_forever[guild_id] = not stay_forever.get(guild_id, False)
    
    status = "enabled" if stay_forever[guild_id] else "disabled"
    await ctx.send(f"🏠 Stay forever mode {status}!")

@bot.command(name='help')
async def help_command(ctx):
    """Show bot commands"""
    embed = discord.Embed(title="🎵 Auralux Music Bot Commands", color=0x0099ff)
    
    embed.add_field(name="🎵 Music Commands", 
                   value="`!play <song>` - Play a song\n"
                         "`!skip` - Skip current song\n"
                         "`!pause` - Pause music\n"
                         "`!resume` - Resume music\n"
                         "`!stop` - Stop music\n"
                         "`!volume <0-100>` - Set volume\n"
                         "`!loop` - Toggle loop\n"
                         "`!queue` - Show queue\n"
                         "`!nowplaying` - Show current song", 
                   inline=False)
    
    embed.add_field(name="⭐ Premium Commands", 
                   value="`!hq` - High quality mode\n"
                         "`!stay` - Stay in VC forever\n"
                         "*DM windyy_918 for premium access*", 
                   inline=False)
    
    await ctx.send(embed=embed)

@bot.event
async def on_command_error(ctx, error):
    """Handle command errors"""
    if isinstance(error, commands.CommandNotFound):
        return
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required argument! Use `!help` for command usage.")
    else:
        print(f"Command error: {error}")
        await ctx.send("❌ An error occurred while processing the command.")

if __name__ == "__main__":
    token = os.getenv('DISCORD_TOKEN')
    if not token:
        print("❌ DISCORD_TOKEN environment variable not set!")
        print("Set it with: export DISCORD_TOKEN='DISCORD_TOKEN'")
        sys.exit(1)
    
    print("🚀 Starting Auralux Music Bot...")
    try:
        bot.run(token)
    except discord.LoginFailure:
        print("❌ Invalid Discord token!")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped by user")
    except Exception as e:
        print(f"❌ Bot crashed: {e}")
        sys.exit(1)
