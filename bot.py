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

# SOLANA ALPHABET (Strict Whitelist)
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

print("Loading Neural Network...")
# optimization: quantize=False might be slightly faster on some CPUs, but default is fine
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image_to_memory(input_path):
    """
    SPEED UPGRADE: 
    1. Crops top 25% (Waste)
    2. No Upscaling (Native 1x speed)
    3. Returns Numpy Array (No disk write)
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        
        # CROP: Remove top 20% of the screen (Status bars/Headers)
        # This instantly makes the scan 20% faster
        img = img.crop((0, int(h * 0.20), w, h))
        
        # SCALE: Keep 1x (Native). 
        # Previous 2x scale = 4x pixels = 4x slower time.
        # We rely on "Contrast" to make it readable at 1x.
        
        # FILTER: High Contrast Binarization
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.5)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        
        # Convert to Numpy for EasyOCR (skips saving file to disk)
        return np.array(img)

def batch_check_dex(candidates):
    valid_pairs = []
    unique_candidates = list(set(candidates))
    
    # Check 30 at a time
    chunk_size = 30
    for i in range(0, len(unique_candidates), chunk_size):
        batch = unique_candidates[i : i + chunk_size]
        try:
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            res = requests.get(url, timeout=2).json()
            if res.get('pairs'):
                valid_pairs.extend(res['pairs'])
        except: pass
            
    return valid_pairs

def generate_mutations(candidate):
    mutations = {candidate}
    confusions = {'A': ['4'], '4': ['A'], 'B': ['8'], '8': ['B'], 'G': ['6'], '6': ['G'], 'Q': ['O', 'D'], 'D': ['0', 'O']}
    
    for i, char in enumerate(candidate):
        if char in confusions:
            for replacement in confusions[char]:
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.add(new_variant)
    return list(mutations)

def fast_mine(text_results):
    full_stream = "".join(text_results)
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', full_stream)
    all_candidates = []
    
    for chunk in chunks:
        chunk_len = len(chunk)
        # Scan for lengths 42-44 (Common Solana CA lengths)
        for length in range(42, 45): 
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # Entropy Filter: Fast reject non-random text
                if len(set(sub)) < 20: continue

                variants = generate_mutations(sub)
                all_candidates.extend(variants)

    if not all_candidates: return None, None
    
    # Sort candidates by length (check longest/most likely first) to prioritize good matches
    # But batch check handles them all anyway.
    valid_pairs = batch_check_dex(all_candidates)
    
    if valid_pairs:
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    # Don't waste time replying "Scanning..." - just do it.
    # Every millisecond counts.
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    # Save raw for safety, but process in memory
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    try:
        # Preprocess directly to RAM
        img_array = preprocess_image_to_memory("scan.jpg")
        
        # OCR directly from RAM
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
        bot.reply_to(message, "❌ No Valid Token Found.")

bot.infinity_polling()
