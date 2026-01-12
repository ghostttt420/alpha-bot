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

# Fallback Local OCR
try:
    import easyocr
    easy_reader = easyocr.Reader(['en'], gpu=False)
    EASYOCR_AVAILABLE = True
except:
    EASYOCR_AVAILABLE = False

def solana_fuzzy_fix(text):
    """Corrects common OCR misreads in Base58 strings"""
    # Solana doesn't use 0, O, I, or l
    fixes = {'0': 'D', 'O': 'Q', 'I': 'j', 'l': 'k'}
    for error, fix in fixes.items():
        text = text.replace(error, fix)
    return text

def preprocess_image(input_path, output_path):
    """Advanced binarization to separate text from dark backgrounds"""
    with Image.open(input_path) as img:
        if img.mode != 'RGB': img = img.convert('RGB')
        # Scale 3x to help OCR engines see small characters
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0) # High contrast for dark mode
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def ocr_smart_scan(file_path, engine=2):
    """API-based OCR using Neural Engine 2"""
    try:
        payload = {'apikey': OCR_KEY, 'language': 'eng', 'OCREngine': engine, 'scale': True}
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={'f': f}, data=payload, timeout=30)
        result = r.json()
        if result.get('ParsedResults'):
            return result['ParsedResults'][0]['ParsedText']
        return ""
    except: return ""

def extract_ca(text):
    """RECONSTRUCTION: Stitches broken lines and validates CA"""
    # KILL ALL WHITESPACE: Reconnects wrapped characters like the 'k'
    clean_text = re.sub(r'\s+', '', text)
    clean_text = solana_fuzzy_fix(clean_text)
    
    # Strict Solana Regex (32-44 chars)
    solana_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    matches = re.findall(solana_pattern, clean_text)
    
    addresses = []
    seen = set()
    for addr in matches:
        if addr not in seen and len(set(addr)) > 20: # Entropy/Quality check
            seen.add(addr)
            addresses.append(addr)
    return addresses

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚙️ **Engineering Strategy Scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("raw.jpg", "proc.jpg")
    
    # Run Multi-Engine Scan (Combining Engine 1, 2, and Local Fallback)
    results = [ocr_smart_scan("proc.jpg", engine=2), ocr_smart_scan("proc.jpg", engine=1)]
    if EASYOCR_AVAILABLE:
        results.append(" ".join(easy_reader.readtext("proc.jpg", detail=0)))
    
    combined_text = " ".join(results)
    found_cas = extract_ca(combined_text)
    
    if found_cas:
        ca = found_cas[0]
        bot.edit_message_text(f"🎯 **CA Found:** `{ca}`\nFetching Alpha data...", message.chat.id, status.message_id)
        
        # DEXSCREENER API CALL
        try:
            res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").json()
            pair = max(res['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
            msg = (
                f"💎 **{pair['baseToken']['name']}**\n"
                f"💰 **Price:** `${pair['priceUsd']}`\n"
                f"📊 **MCAP:** `${pair.get('fdv', 0):,}`\n"
                f"🛡️ **Status:** Fetching Rug Report...\n\n"
                f"📍 `{ca}`"
            )
            bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown')
        except:
            bot.edit_message_text(f"✅ CA: `{ca}`\nFound, but no market data yet.", message.chat.id, status.message_id)
    else:
        bot.edit_message_text("❌ No CA detected. Image may be too noisy.", message.chat.id, status.message_id)

bot.infinity_polling()
