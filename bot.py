import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Initialize Neural Network (CPU Mode)
# This will download the model on the first run (approx 2-3 mins)
print("Loading EasyOCR Model...")
reader = easyocr.Reader(['en'], gpu=False) 

def preprocess_image(input_path, output_path):
    """
    Prepares image for Neural OCR.
    High contrast helps the AI differentiate text from dark backgrounds.
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        # Scale 2x for better character recognition
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # Binarize: Make text bright white, background pure black
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def extract_solana_ca(text_list):
    """
    Logic: Finds the valid CA hidden in the noise.
    """
    # 1. Join all text chunks into one continuous stream (fixes the broken 'k')
    # We use a unique separator just in case, then strip it for the stitch check
    raw_stream = "".join(text_list)
    
    # 2. Clean up common OCR mix-ups 
    # (Fixes '0' -> 'D', 'l' -> 'k' which might happen in the CA)
    # But be careful not to turn "Gold" (G-o-l-d) into valid chars yet.
    # Strategy: First look for potential candidates, THEN fix them.
    
    # 3. Sliding Window / Regex Search
    # We look for long strings of alphanumerics.
    # Then we check if they fit the STRICT Solana profile.
    
    # Remove spaces/newlines to stitch lines
    clean_stream = re.sub(r'\s+', '', raw_stream)
    
    # Regex: Find potential Base58 blocks (32-44 chars)
    # This pattern excludes 0, O, I, l which are illegal in Solana
    strict_pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    matches = re.findall(strict_pattern, clean_stream)
    
    best_candidate = None
    
    for match in matches:
        # 4. ENTROPY CHECK (The "English Word" Filter)
        # Marketing text like "ThisGoesMultiMillions" has repeating letters.
        # A real CA is random. We check for >20 unique characters.
        unique_chars = len(set(match))
        if unique_chars >= 25:
            # If we find multiple, prefer the longer one (usually the CA)
            if best_candidate is None or len(match) > len(best_candidate):
                best_candidate = match
                
    return best_candidate

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🧠 **Neural Scan Active...**")
    
    # Download image
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    # 1. Preprocess
    preprocess_image("scan.jpg", "proc.jpg")
    
    # 2. EasyOCR Scan
    try:
        # detail=0 gives us just the list of strings found
        result_list = reader.readtext("proc.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ OCR Error: {str(e)}", message.chat.id, status.message_id)
        return

    # 3. Extraction
    ca = extract_solana_ca(result_list)
    
    if ca:
        # Success! Fetch Data
        try:
            res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", timeout=5).json()
            if res.get('pairs'):
                pair = res['pairs'][0]
                msg = (
                    f"🎯 **CA:** `{ca}`\n\n"
                    f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
                    f"💰 **Price:** `${pair['priceUsd']}`\n"
                    f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
                )
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
                bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
            else:
                bot.edit_message_text(f"✅ **CA Found:** `{ca}`\n(Token is live but no market data yet)", message.chat.id, status.message_id)
        except:
             bot.edit_message_text(f"✅ **CA Found:** `{ca}`", message.chat.id, status.message_id)
    else:
        # If no CA is found, show what text WAS found to help debug (optional)
        debug_text = "".join(result_list)[:50] + "..."
        bot.edit_message_text(f"❌ No valid Solana CA found.\nDebug: Saw '{debug_text}'", message.chat.id, status.message_id)

bot.infinity_polling()
