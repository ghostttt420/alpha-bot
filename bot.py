import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def ocr_and_reconstruct(file_path):
    """Upgraded Engine 2 with Newline Stripping"""
    try:
        payload = {
            'apikey': OCR_KEY,
            'language': 'eng',
            'OCREngine': 2,    # Engine 2 is best for numbers/CAs
            'scale': True      # Auto-enlarge for clarity
        }
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={file_path: f}, data=payload, timeout=30)
        
        result = r.json()
        if result.get('ParsedResults'):
            text = result['ParsedResults'][0]['ParsedText']
            # REMOVE ALL NEWLINES AND SPACES: This fixes the "wrap-around" problem
            return text.replace("\n", "").replace("\r", "").replace(" ", "")
        return ""
    except: return ""

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚡ **Scanning full image...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("temp.jpg", 'wb') as f: f.write(downloaded_file)
    
    clean_text = ocr_and_reconstruct("temp.jpg")
    
    # Powerful regex for Base58 Solana addresses
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', clean_text)
    
    if ca_match:
        ca = ca_match.group(0)
        # Fetch stats as before...
        bot.edit_message_text(f"🎯 **Found CA:** `{ca}`\nFetching Alpha...", message.chat.id, status.message_id)
        # (Insert market stats/rug check logic here)
    else:
        bot.edit_message_text("❌ CA not found. If it's there, the OCR missed it.", message.chat.id, status.message_id)

bot.infinity_polling()
