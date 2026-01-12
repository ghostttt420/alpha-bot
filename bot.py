import os
import re
import requests
import telebot
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import time

# Config from GitHub Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

# EasyOCR Fallback Logic (Only if you have 8GB+ RAM, otherwise stick to API)
try:
    import easyocr
    # Initialization can take 30s on GitHub runners
    easy_reader = easyocr.Reader(['en'], gpu=False) 
    EASYOCR_AVAILABLE = True
except Exception:
    EASYOCR_AVAILABLE = False

def solana_fuzzy_fix(text):
    """Fixes common OCR misreads for Base58"""
    fixes = {'0': 'D', 'O': 'Q', 'I': 'j', 'l': 'k'}
    for error, fix in fixes.items():
        text = text.replace(error, fix)
    return text

def preprocess_image(input_path, output_path):
    """Claude's enhanced preprocessing for dark-mode screenshots"""
    with Image.open(input_path) as img:
        if img.mode != 'RGB': img = img.convert('RGB')
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = ImageEnhance.Brightness(img).enhance(1.5)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img.save(output_path, quality=100)

def ocr_smart_scan(file_path, engine=2):
    """API-based OCR with high-accuracy Engine 2"""
    try:
        payload = {'apikey': OCR_KEY, 'language': 'eng', 'OCREngine': engine, 'scale': True}
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={'file': f}, data=payload, timeout=30)
        result = r.json()
        if result.get('ParsedResults'):
            # THE FIX: Strip ALL whitespace to reconnect wrapped characters like 'k'
            return re.sub(r'\s+', '', result['ParsedResults'][0]['ParsedText'])
        return ""
    except: return ""

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚙️ **Engineering Strategy Scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    preprocess_image("raw.jpg", "proc.jpg")
    
    # Try Strategy 1: Smart Scan Engine 2 (Best for Alphanumeric)
    raw_text = ocr_smart_scan("proc.jpg", engine=2)
    
    # Fallback to EasyOCR only if API fails and memory allows
    if not raw_text and EASYOCR_AVAILABLE:
        bot.edit_message_text("🔄 **API Busy. Switching to Local Neural OCR...**", message.chat.id, status.message_id)
        results = easy_reader.readtext("proc.jpg", detail=0)
        raw_text = "".join(results)
    
    clean_text = solana_fuzzy_fix(raw_text)
    
    # Regex search for Solana Base58 (32-44 chars)
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', clean_text)
    
    if ca_match:
        ca = ca_match.group(0)
        bot.edit_message_text(f"🎯 **CA Found:** `{ca}`\nFetching Market Data...", message.chat.id, status.message_id)
        # (Insert your DexScreener/RugCheck data logic here)
    else:
        bot.edit_message_text("❌ CA not found. The image is too noisy or the CA is fragmented.", message.chat.id, status.message_id)

bot.infinity_polling()
