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
# Downloads model on first run (~2 mins)
print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image(input_path, output_path):
    """
    Industrial Pre-processing:
    Forces text to be pure black/white to remove 'noise' from dark mode.
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        # Scale 2x for Neural Net readability
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # Binarize (High Contrast)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def fetch_market_data(ca):
    """Returns pair data if valid, None if invalid"""
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=5).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except:
        pass
    return None

def smart_extract_ca(raw_text_list):
    """
    The Brain: Stitches broken lines, filters noise, and validates against the market.
    """
    # 1. Join everything into one block to fix the "broken k" issue
    # We strip all spaces so "D8FY... k" becomes "D8FY...k"
    full_block = "".join(raw_text_list)
    clean_block = re.sub(r'\s+', '', full_block)

    # 2. Strict Regex: Excludes 0, O, I, l (Solana Illegal Chars)
    # This automatically removes "Gold" (has l), "DYOR" (has O)
    pattern = r'[1-9A-HJ-NP-Za-km-z]{32,48}' # Allow slightly longer to catch "NFA"+CA
    matches = re.findall(pattern, clean_block)

    for candidate in matches:
        # 3. The "Prefix Stripper" Logic
        # Sometimes "NFA" (valid chars) gets glued to the front. 
        # We test the raw string, then test it with first 3-4 chars removed.
        
        # Attempt 1: Raw Match
        if fetch_market_data(candidate):
            return candidate
            
        # Attempt 2: Strip common noise prefixes (NFA, ATH are 3 chars)
        # If candidate is 46 chars, and we strip 3, we get 43 (Valid CA length)
        if len(candidate) > 40:
            trimmed = candidate[3:] # Try removing "NFA"
            if fetch_market_data(trimmed):
                return trimmed
                
            trimmed_4 = candidate[4:] # Try removing "BUY "
            if fetch_market_data(trimmed_4):
                return trimmed_4

    return None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🧠 **Neural Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    # 1. Preprocess Image
    preprocess_image("scan.jpg", "proc.jpg")
    
    # 2. EasyOCR Scan
    try:
        # detail=0 gives just the text strings
        result_list = reader.readtext("proc.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ System Error: {str(e)}", message.chat.id, status.message_id)
        return

    # 3. Intelligent Extraction
    ca = smart_extract_ca(result_list)
    
    if ca:
        pair = fetch_market_data(ca) # Fetch again for display
        if pair:
            msg = (
                f"🎯 **CA:** `{ca}`\n\n"
                f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
                f"💰 **Price:** `${pair['priceUsd']}`\n"
                f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
                f"📉 **1H Chg:** `{pair['priceChange']['h1']}%`"
            )
            markup = InlineKeyboardMarkup()
            # Direct deep-link to Trojan for 1-tap buy
            markup.add(InlineKeyboardButton("🚀 Fast Buy (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
            markup.add(InlineKeyboardButton("📈 DexScreener", url=pair['url']))
            
            bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            # Valid CA format but no liquidity (Brand new launch)
            bot.edit_message_text(f"⚠️ **CA Found:** `{ca}`\n\nToken is live on-chain but has no trading pairs yet.", message.chat.id, status.message_id)
    else:
        # Debug info for you
        bot.edit_message_text("❌ No valid CA found.\n(Filtered out noise like 'Gold'/'DYOR')", message.chat.id, status.message_id)

bot.infinity_polling()
