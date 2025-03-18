import os
import json
import re
import subprocess
import time
import sys
import shutil
from pyrogram import Client, filters
from pyrogram.types import Message

# Telegram API credentials
API_ID = "22609670"
API_HASH = "3506d8474ad1f4f5e79b7c52a5c3e88d"
BOT_TOKEN = "7814158198:AAEOvS9q-bLhUeHQrHcM-Zs8UIQuVrRSSSg"

# Linux defaults for VPS deployment
FFMPEG_PATH = "ffmpeg"
DOWNLOADER_PATH = "./N_m3u8DL-RE"
SAVE_DIR = "downloads"

# Initialize the bot
bot = Client("video_downloader_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

def progress(current, total, message, name):
    percent = current * 100 / total
    try:
        message.edit_text(f"Uploading {name}: {percent:.1f}%")
    except Exception:
        pass

def sanitize_filename(filename):
    # Replace any character that is not alphanumeric, underscore, or dash with an underscore.
    return re.sub(r'[^a-zA-Z0-9_-]', '_', filename)

###############################
# JSON file processing
###############################
def download_video_json(entry, temp_dir):
    mpd = entry["mpd"]
    name = sanitize_filename(entry["name"])
    keys = entry.get("keys", [])

    if not os.path.isfile(DOWNLOADER_PATH):
        raise Exception("Downloader tool is missing!")

    command = [
        DOWNLOADER_PATH,
        mpd,
        "-M", "format=mp4",
        "--save-name", name,
        "--thread-count", "64",
        "--append-url-params",
        "-mt",
        "--auto-select"
    ]
    for key in keys:
        command.extend(["--key", key])

    os.makedirs(temp_dir, exist_ok=True)
    command.extend(["--save-dir", temp_dir])

    try:
        result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        print("N_m3u8DL-RE output:", result.stdout)
        return os.path.join(temp_dir, f"{name}.mp4")
    except subprocess.CalledProcessError as e:
        error_details = f"Download failed with exit code {e.returncode}. Stderr: {e.stderr}"
        raise Exception(error_details)

def process_json_file(client, message: Message):
    try:
        file_path = message.download()
        message.reply_text("JSON file received. Processing...")
        with open(file_path, "r") as f:
            data = json.load(f)

        temp_dir = SAVE_DIR
        for entry in data:
            name = sanitize_filename(entry["name"])
            message.reply_text(f"Starting download for: {name}")
            try:
                # Download the video using the JSON-specific method
                video_path = download_video_json(entry, temp_dir)
                if not os.path.exists(video_path):
                    message.reply_text(f"Download failed for {name}: File not found")
                    continue

                message.reply_text(f"Download complete. Starting upload for: {name}")
                start_time = time.time()
                client.send_video(
                    chat_id=message.chat.id,
                    video=video_path,
                    caption=f"Uploaded: {name}",
                    progress=lambda current, total: progress(current, total, message, name),
                    width=1920,
                    height=1080
                )
                end_time = time.time()
                message.reply_text(f"Upload complete for {name}. Time taken: {end_time - start_time:.2f} seconds")
                # Delete the downloaded file after upload
                if os.path.exists(video_path):
                    os.remove(video_path)
            except Exception as e:
                message.reply_text(f"Error processing {name}: {str(e)}")
                continue

        message.reply_text("All videos processed successfully!")
    except Exception as e:
        message.reply_text(f"An error occurred: {str(e)}")

###############################
# TXT file processing
###############################
def process_txt_file(client, message: Message):
    try:
        file_path = message.download()
        message.reply_text("Text file received. Processing...")
        with open(file_path, "r", encoding="utf-8") as f:
            input_text = f.read()

        # Parse the text file line by line using regex
        videos = []
        for line in input_text.strip().splitlines():
            match = re.match(r"\((.*?)\)\s*\(.*?\)\s*\(video\):(.+?)HLS_KEY=(.+)", line)
            if match:
                title, url, key = match.groups()
                videos.append((title.strip(), url.strip(), key.strip()))

        if not videos:
            message.reply_text("No valid video links found in the text file.")
            return

        os.makedirs(SAVE_DIR, exist_ok=True)
        for title, url, key in videos:
            safe_title = sanitize_filename(title)
            message.reply_text(f"Starting download for: {title}")

            # Create a temporary directory for this video
            temp_dir = os.path.join(SAVE_DIR, safe_title + "_temp")
            os.makedirs(temp_dir, exist_ok=True)

            command = [
                DOWNLOADER_PATH,
                url,
                "--save-dir", temp_dir,
                "--save-name", safe_title,
                "--custom-hls-key", key,
                "--ffmpeg-binary-path", FFMPEG_PATH,
                "--auto-select"
            ]
            try:
                result = subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                print("N_m3u8DL-RE output:", result.stdout)
            except subprocess.CalledProcessError as e:
                raise Exception(f"Download failed with exit code {e.returncode}. Stderr: {e.stderr}")

            # Look for an audio file (with .m4a extension)
            audio_file = None
            for file in os.listdir(temp_dir):
                if file.startswith(safe_title) and file.endswith(".m4a"):
                    audio_file = os.path.join(temp_dir, file)
                    break

            video_file = os.path.join(temp_dir, safe_title + ".mp4")
            final_output = os.path.join(SAVE_DIR, safe_title + ".mp4")

            if audio_file:
                merge_command = [
                    FFMPEG_PATH,
                    "-i", video_file,
                    "-i", audio_file,
                    "-c:v", "copy",
                    "-c:a", "copy",
                    final_output
                ]
                try:
                    result = subprocess.run(merge_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    print("ffmpeg merge output:", result.stdout)
                except subprocess.CalledProcessError as e:
                    raise Exception(f"Merging failed with exit code {e.returncode}. Stderr: {e.stderr}")

                # Clean up video and audio files
                if os.path.exists(video_file):
                    os.remove(video_file)
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                # Remove the temp directory if it's empty
                try:
                    os.rmdir(temp_dir)
                except OSError:
                    shutil.rmtree(temp_dir)
            else:
                final_output = video_file
                message.reply_text(f"Warning: No audio file found for {title}, skipping merge.")
                # Attempt to remove temp directory if possible
                try:
                    os.rmdir(temp_dir)
                except OSError:
                    shutil.rmtree(temp_dir)

            message.reply_text(f"Download complete. Starting upload for: {title}")
            start_time = time.time()
            client.send_video(
                chat_id=message.chat.id,
                video=final_output,
                caption=f"Uploaded: {title}",
                progress=lambda current, total: progress(current, total, message, title),
                width=1920,
                height=1080
            )
            end_time = time.time()
            message.reply_text(f"Upload complete for {title}. Time taken: {end_time - start_time:.2f} seconds")

            if os.path.exists(final_output):
                os.remove(final_output)

        message.reply_text("All videos processed successfully!")
    except Exception as e:
        message.reply_text(f"An error occurred while processing text file: {str(e)}")

###############################
# General file handler
###############################
@bot.on_message(filters.private & filters.document)
def handle_file(client, message: Message):
    file_name = message.document.file_name
    if file_name.endswith(".json"):
        process_json_file(client, message)
    elif file_name.endswith(".txt"):
        process_txt_file(client, message)
    else:
        message.reply_text("Please send a valid .json or .txt file.")

###############################
# Bot restart command
###############################
@bot.on_message(filters.private & filters.command("restart"))
def restart_bot(client, message: Message):
    try:
        message.reply_text("Restarting the bot...")
        python_executable = sys.executable
        os.execl(python_executable, python_executable, *sys.argv)
    except Exception as e:
        message.reply_text(f"Failed to restart: {str(e)}")

if __name__ == "__main__":
    bot.run()
