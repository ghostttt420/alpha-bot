import os
import re
import requests
import telebot
from PIL import Image, ImageOps, ImageEnhance

TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def preprocess_image(input_path, output_path):
    """Enhances image for OCR: Grayscale -> Contrast -> Scale"""
    with Image.open(input_path) as img:
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        # Resize to 2x for better character definition
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        img.save(output_path, quality=95)

def ocr_smart_scan(file_path):
    """Engine 2 with scale enabled for maximum accuracy"""
    try:
        payload = {
            'apikey': OCR_KEY,
            'language': 'eng',
            'OCREngine': 2, 
            'scale': True
        }
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={file_path: f}, data=payload, timeout=30)
        
        result = r.json()
        if result.get('ParsedResults'):
            full_text = result['ParsedResults'][0]['ParsedText']
            # REMOVE ALL WHITESPACE to handle multi-line CAs
            return re.sub(r'\s+', '', full_text)
        return ""
    except: return ""

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚙️ **Engineering high-accuracy scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    raw_path = "raw.jpg"
    proc_path = "processed.jpg"
    
    with open(raw_path, 'wb') as f: f.write(downloaded_file)
    
    # Apply pre-processing before sending to OCR
    preprocess_image(raw_path, proc_path)
    
    clean_text = ocr_smart_scan(proc_path)
    
    # Robust Regex for Base58 (Solana)
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', clean_text)
    
    if ca_match:
        ca = ca_match.group(0)
        bot.edit_message_text(f"🎯 **CA Found:** `{ca}`\nFetching market data...", message.chat.id, status.message_id)
        # ... your get_market_data and check_rug logic here ...
    else:
        bot.edit_message_text("❌ OCR failed to reconstruct the CA. Ensure the text isn't blurry.", message.chat.id, status.message_id)

bot.infinity_polling()
