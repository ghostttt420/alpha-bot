import os
import requests
import telebot
import re

# Config from Environment Variables (GitHub Secrets)
TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def ocr_from_image(file_path):
    """Sends image to OCR.space and returns extracted text"""
    payload = {
        'apikey': OCR_KEY,
        'language': 'eng',
        'isOverlayRequired': False,
    }
    with open(file_path, 'rb') as f:
        r = requests.post('https://api.ocr.space/parse/image',
                          files={file_path: f},
                          data=payload)
    result = r.json()
    if result.get('ParsedResults'):
        return result['ParsedResults'][0]['ParsedText']
    return ""

def find_ca(text):
    sol_regex = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    found = re.findall(sol_regex, text)
    return found[0] if found else None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    bot.reply_to(message, "⚡ Screenshot received! Scanning for Alpha...")
    
    # Download photo to current directory
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("temp.jpg", 'wb') as new_file:
        new_file.write(downloaded_file)
    
    # Run OCR
    raw_text = ocr_from_image("temp.jpg")
    ca = find_ca(raw_text)
    
    if ca:
        # Re-use your market stats & rug check logic from earlier
        bot.send_message(message.chat.id, f"🎯 Found CA: `{ca}`\nGetting stats...")
        # (Call your get_stats and check_security functions here)
    else:
        bot.reply_to(message, "❌ No Solana address detected in that image.")

bot.infinity_polling()
