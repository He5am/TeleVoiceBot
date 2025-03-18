import telebot
import paramiko
import os
import time
import logging
import traceback
from datetime import datetime
import pytz
from dotenv import load_dotenv
import threading

# Load environment variables
load_dotenv()

# Configuration Constants
CONFIG = {
    'TOKEN': os.getenv('BOT_TOKEN'),
    'ADMIN_CHAT_ID': os.getenv('ADMIN_CHAT_ID'),
    'SSH': {
        'HOST': os.getenv('SSH_HOST'),
        'PORT': int(os.getenv('SSH_PORT', 22)),
        'USERNAME': os.getenv('SSH_USERNAME'),
        'PASSWORD': os.getenv('SSH_PASSWORD')
    },
    'VOICEMAIL_DIRS': [
        os.getenv('VOICEMAIL_DIR_1'),
        os.getenv('VOICEMAIL_DIR_2'),
        os.getenv('VOICEMAIL_DIR_3'),
        os.getenv('VOICEMAIL_DIR_4'),
        os.getenv('VOICEMAIL_DIR_5')
    ],
    'CHAT_MAPPING': {
        '1': [{'chat_id': os.getenv('CHAT_1_ID'), 'thread_id': int(os.getenv('THREAD_1', 0))}],
        '2': [{'chat_id': os.getenv('CHAT_2_ID'), 'thread_id': int(os.getenv('THREAD_2', 0))}],
        '3': [{'chat_id': os.getenv('CHAT_3_ID'), 'thread_id': int(os.getenv('THREAD_3', 0))}],
        '4': [
            {'chat_id': os.getenv('CHAT_4_ID_1'), 'thread_id': int(os.getenv('THREAD_4_1', 0))},
            {'chat_id': os.getenv('CHAT_4_ID_2'), 'thread_id': int(os.getenv('THREAD_4_2', 0))}
        ],
        '5': [
            {'chat_id': os.getenv('CHAT_5_ID_1'), 'thread_id': int(os.getenv('THREAD_5_1', 0))},
            {'chat_id': os.getenv('CHAT_5_ID_2'), 'thread_id': int(os.getenv('THREAD_5_2', 0))}
        ]
    },
    'CHECK_INTERVAL': int(os.getenv('CHECK_INTERVAL', 60))  # Seconds
}

# Validate required environment variables
required_vars = [
    'BOT_TOKEN', 'ADMIN_CHAT_ID', 'SSH_HOST', 'SSH_USERNAME', 'SSH_PASSWORD',
    'VOICEMAIL_DIR_1', 'VOICEMAIL_DIR_2', 'VOICEMAIL_DIR_3', 'VOICEMAIL_DIR_4', 'VOICEMAIL_DIR_5'
]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

# Initialize logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('voicemail_bot.log'),
        logging.StreamHandler()
    ]
)

# Initialize Telegram Bot
bot = telebot.TeleBot(CONFIG['TOKEN'])
telebot.apihelper.CONNECT_TIMEOUT = 30
telebot.apihelper.READ_TIMEOUT = 30

# Add start command handler for findid functionality
@bot.message_handler(commands=['start'])
def handle_start(message):
    chat_id = message.chat.id
    thread_id = message.message_thread_id if message.message_thread_id else 0
    chat_type = message.chat.type
    chat_title = message.chat.title if message.chat.title else "Private Chat"
    
    # پیام به کاربر
    if chat_type == 'private':
        bot.reply_to(message, "سلام! اطلاعات چت شما ثبت شد.")
    else:
        bot.reply_to(message, "سلام! اطلاعات گروه و تاپیک ثبت شد.", message_thread_id=thread_id)
    
    # ارسال اطلاعات به ادمین
    admin_message = f"""
🆔 New Bot Start:
Chat Type: {chat_type}
Chat Title: {chat_title}
Chat ID: {chat_id}
Thread ID: {thread_id}
"""
    bot.send_message(CONFIG['ADMIN_CHAT_ID'], admin_message)

class VoicemailMonitor:
    def __init__(self):
        self.sent_files = {dir: [] for dir in CONFIG['VOICEMAIL_DIRS']}
        self.ssh_client = None  # To hold the SSH connection

    def convert_utc_to_tehran(self, utc_time_str):
        try:
            utc_zone = pytz.utc
            tehran_zone = pytz.timezone('Asia/Tehran')
            utc_time = datetime.strptime(utc_time_str, '%a %b %d %I:%M:%S %p %Z %Y')
            return utc_zone.localize(utc_time).astimezone(tehran_zone).strftime('%Y-%m-%d %H:%M:%S')
        except Exception as e:
            logging.error(f"Time conversion error: {str(e)}")
            return utc_time_str

    def send_error_notification(self, error):
        try:
            bot.send_message(CONFIG['ADMIN_CHAT_ID'], f"🚨 Error occurred:\n{error}")
        except Exception as e:
            logging.error(f"Failed to send error notification: {str(e)}")

    def read_voicemail_info(self, sftp_client, txt_file_path):
        try:
            with sftp_client.open(txt_file_path, 'r') as file:
                content = file.read().decode('utf-8')
                callerid, origdate = None, None

                for line in content.splitlines():
                    if line.startswith("callerid="):
                        callerid = line.split("=", 1)[1].strip().replace('"', '')
                    elif line.startswith("origdate="):
                        origdate = line.split("=", 1)[1].strip()

                if callerid and origdate:
                    return callerid, origdate
                raise ValueError("Missing caller ID or orig date")
        except Exception as e:
            logging.error(f"Error reading voicemail info: {str(e)}")
            raise

    def process_voicemail(self, ssh_client, file_path):
        voicemail_number = file_path.split('/')[-2]
        temp_dir = f"/var/spool/asterisk/voicemail/default/{voicemail_number}/tmp"

        try:
            stdin, stdout, stderr = ssh_client.exec_command(f'ls {file_path}/*.wav')
            audio_files = stdout.read().decode().splitlines()
            new_files = [f for f in audio_files if f not in self.sent_files[file_path]]

            for audio_file in new_files:
                file_name = os.path.basename(audio_file)
                txt_file_path = os.path.splitext(audio_file)[0] + '.txt'

                try:
                    with ssh_client.open_sftp() as sftp:
                        sftp.stat(txt_file_path)
                        callerid, origdate = self.read_voicemail_info(sftp, txt_file_path)

                        with sftp.open(audio_file, 'rb') as f:
                            self.send_audio(
                                f.read(), file_name, callerid,
                                origdate, voicemail_number
                            )

                        # Create temp dir if not exists and move file
                        ssh_client.exec_command(f'mkdir -p {temp_dir} && mv {audio_file} {temp_dir}/{file_name}')
                        self.sent_files[file_path].append(audio_file)

                except FileNotFoundError:
                    logging.warning(f"Text file missing: {txt_file_path}")
                except Exception as e:
                    logging.error(f"Error processing {audio_file}: {str(e)}")

        except Exception as e:
            logging.error(f"SSH command error: {str(e)}")
            raise

    def send_audio(self, audio_data, file_name, callerid, origdate, vm_number):
        try:
            configs = CONFIG['CHAT_MAPPING'].get(vm_number, [])
            if not configs:
                raise ValueError(f"No configuration found for voicemail {vm_number}")

            caption = f"callerid=\"{callerid}\"\norigdate={self.convert_utc_to_tehran(origdate)}"

            for config in configs:
                chat_id = config.get('chat_id')
                thread_id = config.get('thread_id', 0)

                if not chat_id:
                    logging.error(f"Missing chat_id in config for voicemail {vm_number}")
                    continue

                try:
                    bot.send_audio(
                        chat_id, audio_data,
                        title=file_name, caption=caption,
                        message_thread_id=thread_id
                    )
                    logging.info(f"Sent {file_name} to {chat_id} (Thread: {thread_id})")
                except Exception as e:
                    logging.error(f"Failed to send to {chat_id}: {str(e)}")
                    self.send_error_notification(f"Failed to send to {chat_id}: {str(e)}")

        except Exception as e:
            logging.error(f"Audio send failed: {str(e)}")
            self.send_error_notification(f"Audio send failed: {str(e)}")
            raise

    def start_monitoring(self):
        logging.info("Starting voicemail monitoring service")

        # Establish SSH connection once
        try:
            self.ssh_client = paramiko.SSHClient()
            self.ssh_client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            self.ssh_client.connect(
                CONFIG['SSH']['HOST'],
                port=CONFIG['SSH']['PORT'],
                username=CONFIG['SSH']['USERNAME'],
                password=CONFIG['SSH']['PASSWORD']
            )
            logging.info("SSH connection established successfully")

            while True:
                try:
                    for dir_path in CONFIG['VOICEMAIL_DIRS']:
                        logging.info(f"Processing directory: {dir_path}")
                        self.process_voicemail(self.ssh_client, dir_path)

                    time.sleep(CONFIG['CHECK_INTERVAL'])

                except KeyboardInterrupt:
                    logging.info("Service stopped by user")
                    break
                except Exception as e:
                    error_msg = f"Critical error: {str(e)}\n{traceback.format_exc()}"
                    logging.error(error_msg)
                    self.send_error_notification(error_msg)
                    time.sleep(60)

        except Exception as e:
            error_msg = f"SSH connection failed: {str(e)}"
            logging.error(error_msg)
            self.send_error_notification(error_msg)

        finally:
            if self.ssh_client:
                self.ssh_client.close()
                logging.info("SSH connection closed")

def run_bot():
    monitor = VoicemailMonitor()
    while True:
        try:
            print("Bot started. Press Ctrl+C to stop.")
            # Start voicemail monitoring in a separate thread
            monitor_thread = threading.Thread(target=monitor.start_monitoring)
            monitor_thread.daemon = True
            monitor_thread.start()
            
            # Start bot polling
            bot.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"Bot encountered an error: {e}")
            print("Restarting in 10 seconds...")
            time.sleep(10)
            continue

if __name__ == "__main__":
    run_bot() 