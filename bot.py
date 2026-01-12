import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Initialize EasyOCR (CPU Mode)
print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False) 

def preprocess_image(input_path, output_path):
    """
    Standardizes image.
    We use a milder contrast here (2.0 instead of 4.0) to avoid 
    erasing grey text (like the CA in your screenshot).
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # 2x Scale is optimal for EasyOCR
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # Mild Binarization
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0) 
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        img.save(output_path, quality=100)

def verify_on_chain(ca):
    """
    Queries DexScreener to see if the CA is real.
    """
    if len(ca) < 32 or len(ca) > 46: return None
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=3).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except: pass
    return None

def extract_from_text(text_list):
    """
    SCANS BACKWARDS (Bottom-up) to find the CA first.
    """
    # 1. Reverse the list to check the bottom lines first
    reversed_list = text_list[::-1]
    
    # 2. Join it all into one big string for "Stitching"
    # (We also keep the reversed list for line-by-line checks)
    full_block = "".join(text_list)
    clean_block = re.sub(r'\s+', '', full_block)

    # 3. PATTERN MATCHING
    # Look for long alphanumeric strings (32-100 chars)
    # This captures "DYORNFA" + "Address"
    candidates = re.findall(r'[a-zA-Z0-9]{32,100}', clean_block)
    
    for candidate in candidates:
        # A. Repair common typos
        clean_cand = candidate.replace('0', 'D').replace('O', 'Q').replace('l', '1').replace('I', 'j')
        
        # B. SLIDING WINDOW (The "Un-Gluer")
        # Check every 32-44 char substring inside the candidate
        # This separates "NFA" from "D8FY..."
        limit = len(clean_cand)
        for length in range(32, 45):
            for start in range(0, limit - length + 1):
                sub_slice = clean_cand[start : start + length]
                
                # Regex Check: Must look like Solana (No 0, O, I, l)
                if re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', sub_slice):
                    pair = verify_on_chain(sub_slice)
                    if pair: return sub_slice, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚡ **Dual-Layer Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    
    # Generate Processed Image
    preprocess_image("raw.jpg", "proc.jpg")
    
    # STRATEGY: Scan BOTH images.
    # Sometimes 'proc.jpg' kills grey text. 'raw.jpg' saves it.
    text_results = []
    
    try:
        # Pass 1: Processed Image
        text_results += reader.readtext("proc.jpg", detail=0)
        # Pass 2: Raw Image (in case contrast killed the CA)
        text_results += reader.readtext("raw.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status.message_id)
        return

    # Extract
    ca, pair = extract_from_text(text_results)
    
    if ca and pair:
        msg = (
            f"✅ **Verified CA:** `{ca}`\n\n"
            f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
            f"💰 **Price:** `${pair['priceUsd']}`\n"
            f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
        markup.add(InlineKeyboardButton("📈 Chart", url=pair['url']))
        
        bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
    else:
        # DEBUG: Show the LAST 100 characters found (Bottom of the image)
        # This tells us if the bot even reached the CA line.
        debug_tail = "".join(text_results)[-100:]
        bot.edit_message_text(
            f"❌ **Scan Failed.**\n\n"
            f"Bottom of text scan:\n`...{debug_tail}`\n"
            f"Is the CA visible here?", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
