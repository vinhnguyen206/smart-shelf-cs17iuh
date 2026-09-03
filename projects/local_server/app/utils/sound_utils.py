'''
* Copyright 2025 Vo Duong Khang [C]
*
* Licensed under the Apache License, Version 2.0 (the "License");
* you may not use this file except in compliance with the License.
* You may obtain a copy of the License at
*
*     http://www.apache.org/licenses/LICENSE-2.0
*
* Unless required by applicable law or agreed to in writing, software
* distributed under the License is distributed on an "AS IS" BASIS,
* WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
* See the License for the specific language governing permissions and
* limitations under the License.
'''
# from gtts import gTTS
# import vlc
# import os

# def speech_text(text):
#     path = os.path.abspath(os.path.join(__file__, "../../..", "app/static/sounds/temp.mp3"))
#     tts = gTTS(text=text, lang='vi', slow=False)
#     tts.save(path)
#     player = vlc.MediaPlayer(path)
#     player.play()

# def play_sound(path):
#     player = vlc.MediaPlayer(path)
#     player.play()

from gtts import gTTS
import hashlib
import subprocess
import os

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../"))
SOUND_PATH = os.path.join(BASE_DIR, "app/static/sounds/temp.mp3")
TTS_CACHE_DIR = os.path.join(BASE_DIR, "app/static/sounds/tts_cache")

def speech_text(text):
    """Speak Vietnamese text via gTTS with an on-disk cache.

    gTTS needs the internet; caching by text hash means any phrase spoken
    once while online keeps working offline, and repeated phrases skip the
    network round-trip entirely."""
    try:
        cache_path = os.path.join(
            TTS_CACHE_DIR, hashlib.md5(text.encode("utf-8")).hexdigest() + ".mp3")
        if not os.path.exists(cache_path):
            os.makedirs(TTS_CACHE_DIR, exist_ok=True)
            tts = gTTS(text=text, lang='vi', slow=False)
            # write to a temp name first so a failed download never leaves a
            # corrupt mp3 in the cache
            tts.save(cache_path + ".part")
            os.replace(cache_path + ".part", cache_path)
        # play_sound handles device fallback and a 10s timeout
        play_sound(cache_path)
    except Exception as e:
        print(f"speech_text failed (offline and phrase not cached?): {e}")

def play_sound(path):
    # print(f"DEBUG play_sound: Attempting to play: {path}")
    # print(f"DEBUG play_sound: File exists: {os.path.exists(path)}")
    
    try:
        # Use ALSA backend instead of JACK, and specify the audio device
        result = subprocess.run(
            ["mpg123", "-q", "-a", "hw:Device,0", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            # print(f"DEBUG play_sound ERROR: Return code: {result.returncode}")
            # print(f"DEBUG play_sound ERROR: stderr: {result.stderr}")
            
            # Fallback: try with ALSA but default device
            # print(f"DEBUG play_sound: Trying with ALSA default device...")
            result = subprocess.run(
                ["mpg123", "-q", "-o", "alsa", path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                print(f"DEBUG play_sound: Sound played successfully (ALSA default)")
            else:
                print(f"DEBUG play_sound ERROR: ALSA default failed - {result.stderr}")
        else:
            print(f"DEBUG play_sound: Sound played successfully")
            
    except subprocess.TimeoutExpired:
        print(f"DEBUG play_sound ERROR: Command timed out after 10 seconds")
    except FileNotFoundError:
        print(f"DEBUG play_sound ERROR: mpg123 command not found")
    except Exception as e:
        print(f"DEBUG play_sound ERROR: Unexpected exception - {e}")
