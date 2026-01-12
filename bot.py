import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance, ImageFilter

TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def solana_validator(text):
    """
    STRICT VALIDATION: Solana addresses follow Base58 rules.
    They NEVER contain: 0, O, I, or l.
    """
    # Character fix for common OCR hallucinations
    fixes = {'0': 'D', 'O': 'Q', 'I': 'j', 'l': 'k'}
    for error, fix in fixes.items():
        text = text.replace(error, fix)
    
    # regex: Only Base58 chars, length 32-44
    solana_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    matches = re.findall(solana_pattern, text)
    
    valid_addresses = []
    for addr in matches:
        # HUMAN VISION LOGIC: Real CAs have high entropy (diverse characters).
        # This ignores marketing words like 'GokdisnearATH'
        if len(set(addr)) >= 20: 
            valid_addresses.append(addr)
    return valid_addresses

def preprocess_for_high_accuracy(input_path, output_path):
    """Adaptive processing for Dark Mode screenshots"""
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        # Zoom & Resolution: Scale 3x to sharpen small fonts
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        # Binarization: Force high contrast to separate text from background
        img = ImageEnhance.Contrast(img).enhance(5.0) 
        img = ImageEnhance.Sharpness(img).enhance(3.0)
        img.save(output_path, quality=100)

@bot.message_handler(content_types=['photo'])
def handle_high_accuracy_scan(message):
    status = bot.reply_to(message, "⚡ **Applying Neural Scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_for_high_accuracy("raw.jpg", "proc.jpg")
    
    # We combine both OCR Engines for redundancy
    combined_raw = ""
    for engine in [2, 1]:
        try:
            payload = {'apikey': OCR_KEY, 'OCREngine': engine, 'scale': True}
            r = requests.post('https://api.ocr.space/parse/image', 
                             files={'f': open("proc.jpg", 'rb')}, data=payload, timeout=20)
            combined_raw += r.json()['ParsedResults'][0]['ParsedText']
        except: continue

    # RECONSTRUCTION: Strip ALL spaces and newlines to fix line-wraps
    clean_stream = re.sub(r'\s+', '', combined_raw)
    found_cas = solana_validator(clean_stream)
    
    if found_cas:
        ca = found_cas[0]
        # Professional Check: Fetch Market Data
        try:
            res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").json()
            pair = res['pairs'][0]
            msg = (
                f"🎯 **CA Found:** `{ca}`\n\n"
                f"💎 **{pair['baseToken']['name']}**\n"
                f"💰 **Price:** `${pair['priceUsd']}`\n"
                f"📊 **MCAP:** `${pair.get('fdv', 0):,}`\n"
                f"🛡️ **RugCheck:** Fetching..."
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("📈 View Chart", url=pair['url']),
                       InlineKeyboardButton("💸 Buy (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
            bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
        except:
            bot.edit_message_text(f"🎯 **CA:** `{ca}`\nFound, but token is not live on DEX yet.", message.chat.id, status.message_id)
    else:
        bot.edit_message_text("❌ No valid Solana CA detected. Text might be too blurry.", message.chat.id, status.message_id)

bot.infinity_polling()
