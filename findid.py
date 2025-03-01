import telebot
import time
from telebot import apihelper
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

# Validate required environment variables
required_vars = ['BOT_TOKEN', 'ADMIN_CHAT_ID']
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    raise ValueError(f"Missing required environment variables: {', '.join(missing_vars)}")

TOKEN = os.getenv('BOT_TOKEN')
ADMIN_CHAT_ID = os.getenv('ADMIN_CHAT_ID')

# افزایش تایم‌اوت‌ها
apihelper.CONNECT_TIMEOUT = 30
apihelper.READ_TIMEOUT = 30

bot = telebot.TeleBot(TOKEN)

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
    bot.send_message(ADMIN_CHAT_ID, admin_message)

def run_bot():
    while True:
        try:
            print("Bot started. Press Ctrl+C to stop.")
            bot.polling(none_stop=True, interval=3, timeout=30)
        except Exception as e:
            print(f"Bot encountered an error: {e}")
            print("Restarting in 10 seconds...")
            time.sleep(10)
            continue

if __name__ == '__main__':
    run_bot()