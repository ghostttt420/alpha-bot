import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr
import numpy as np

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# DIRTY WHITELIST
# We INCLUDE illegal chars (0, O, I, l) so we can catch and fix them later.
# If we exclude them here, EasyOCR just deletes them, breaking the address length.
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0OIl"

print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image_to_memory(input_path):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # 1.5x Scale (Balance of speed and accuracy)
        new_w, new_h = int(w * 1.5), int(h * 1.5)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        
        return np.array(img)

def batch_check_dex(candidates):
    valid_pairs = []
    unique_candidates = list(set(candidates))
    
    # Batch check 30 at a time
    chunk_size = 30
    for i in range(0, len(unique_candidates), chunk_size):
        batch = unique_candidates[i : i + chunk_size]
        try:
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            res = requests.get(url, timeout=3).json() # 3s timeout for safety
            if res.get('pairs'):
                valid_pairs.extend(res['pairs'])
        except: pass
            
    return valid_pairs

def generate_mutations(candidate):
    """
    EXPANDED MUTATIONS: Handles illegal chars and common shape errors.
    """
    mutations = {candidate}
    
    # Map of OCR mix-ups. 
    # Key = The mistake we see. Value = What it might actually be.
    confusions = {
        'A': ['4'], '4': ['A'],
        'B': ['8'], '8': ['B'],
        'G': ['6'], '6': ['G'],
        'S': ['5'], '5': ['S'],  # Fixes Test Case C
        'Q': ['O', '0', 'D'], 
        'D': ['O', '0'],
        '0': ['D', 'O', 'Q'],    # Illegal '0' fix
        'O': ['D', '0', 'Q'],    # Illegal 'O' fix
        'l': ['1', 'I'],         # Illegal 'l' fix
        'I': ['1', 'l'],         # Illegal 'I' fix
        'Z': ['2'], '2': ['Z']
    }
    
    for i, char in enumerate(candidate):
        if char in confusions:
            for replacement in confusions[char]:
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.add(new_variant)
                
    return list(mutations)

def fast_mine(text_results):
    full_stream = "".join(text_results)
    
    # 1. Extract blocks (Include illegal chars 0,O,I,l in regex now)
    # This ensures we don't split the CA if a '0' is inside it.
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z0OIl]{32,}', full_stream)
    
    all_candidates = []
    
    for chunk in chunks:
        chunk_len = len(chunk)
        # Check lengths 32-45 (Covering standard 43/44 and rare vanity ones)
        for length in range(32, 45): 
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # Entropy Filter: <20 unique chars = probably noise
                if len(set(sub)) < 20: continue

                # Generate fixes for "Dirty" chars
                variants = generate_mutations(sub)
                all_candidates.extend(variants)

    if not all_candidates: return None, None
    
    valid_pairs = batch_check_dex(all_candidates)
    
    if valid_pairs:
        # Return most liquid pair
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    try:
        img_array = preprocess_image_to_memory("scan.jpg")
        # Read using the DIRTY whitelist
        results = reader.readtext(img_array, detail=0, allowlist=SOLANA_CHARS)
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {e}")
        return

    ca, pair = fast_mine(results)
    
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
        
        bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=markup)
    else:
        # Debug helper
        debug_tail = "".join(results)[-50:]
        bot.reply_to(message, f"❌ No Valid Token Found.\nDebug: `...{debug_tail}`", parse_mode='Markdown')

bot.infinity_polling()
