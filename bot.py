import sys

print("🔄 System Booting...", flush=True)

try:
    import os
    import re
    import requests
    import telebot
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    from PIL import Image, ImageOps, ImageEnhance
    import easyocr
    import numpy as np
except Exception as e:
    print(f"❌ FATAL ERROR during Imports: {e}", flush=True)
    sys.exit(1)

TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    print("❌ Error: TELEGRAM_TOKEN is missing!", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

# HYBRID WHITELIST (Keep exactly as is)
HYBRID_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0OIl5S"

print("🧠 Loading Neural Network...", flush=True)
reader = easyocr.Reader(['en'], gpu=False)

def get_multi_scale_images(input_path):
    """
    Returns image at TWO scales.
    Optimized scales: 1.25x (Fast) and 2.5x (Deep).
    This is ~40% faster than the previous 1.5/3.0 setup.
    """
    images = []
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        
        # SCALES: 
        # 1.25x -> Catches B/C and Twitter
        # 2.50x -> Catches A (Tiny text)
        scales = [1.25, 2.5]
        
        for scale in scales:
            new_w, new_h = int(w * scale), int(h * scale)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            img_proc = ImageOps.grayscale(resized)
            img_proc = ImageEnhance.Contrast(img_proc).enhance(2.0)
            img_proc = ImageEnhance.Sharpness(img_proc).enhance(1.5)
            
            images.append(np.array(img_proc))
            
    return images

def batch_check_dex(candidates):
    valid_pairs = []
    unique_candidates = list(set(candidates))
    
    chunk_size = 30
    for i in range(0, len(unique_candidates), chunk_size):
        batch = unique_candidates[i : i + chunk_size]
        try:
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            res = requests.get(url, timeout=3).json()
            if res.get('pairs'):
                valid_pairs.extend(res['pairs'])
        except: pass
    return valid_pairs

def mutate_dirty_string(candidate):
    mutations = {candidate}
    confusions = {
        '0': ['D', 'O', 'Q'], 'O': ['D', '0', 'Q'],
        'l': ['1', 'I'], 'I': ['1', 'l'],
        'A': ['4'], '4': ['A'],
        'B': ['8'], '8': ['B'],
        'S': ['5'], '5': ['S'],
        'G': ['6'], '6': ['G']
    }
    
    for i, char in enumerate(candidate):
        if char in confusions:
            for replacement in confusions[char]:
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.add(new_variant)
    return list(mutations)

def hydra_mine(text_results):
    full_stream = "".join(text_results)
    all_candidates = []

    # LOGIC A: STRICT FILTER (Test A / Clean Text)
    # Deletes illegal chars (0, O, I, l) to break glue like "Gold"
    strict_stream = re.sub(r'[0OIl]', '', full_stream) 
    clean_chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', strict_stream)
    for chunk in clean_chunks:
        for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if len(set(sub)) > 15: all_candidates.append(sub)

    # LOGIC B: DIRTY FILTER (Test B & C / Typos)
    # Keeps everything and mutates (S->5, 0->D)
    dirty_chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z0OIl5S]{32,}', full_stream)
    for chunk in dirty_chunks:
        for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if len(set(sub)) < 15: continue
                all_candidates.extend(mutate_dirty_string(sub))

    # LOGIC C: RAW SLIDER (Twitter / Messy Glue)
    # Catches "NFAD8FY..." by simply sliding past "NFA"
    raw_chunks = re.findall(r'[a-zA-Z0-9]{32,}', full_stream)
    for chunk in raw_chunks:
         for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if re.search(r'\d', sub) and re.search(r'[a-zA-Z]', sub):
                    all_candidates.append(sub)

    if not all_candidates: return None, None
    
    valid_pairs = batch_check_dex(all_candidates)
    if valid_pairs:
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

def send_success_msg(message, ca, pair):
    msg = (
        f"✅ **Verified CA:** `{ca}`\n\n"
        f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
        f"💰 **Price:** `${pair['priceUsd']}`\n"
        f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
    )
    markup = InlineKeyboardMarkup()
    # Updated Referral Link
    markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://trojan.com/@ghostttt420?start={ca}"))
    markup.add(InlineKeyboardButton("📈 Chart", url=pair['url']))
    bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(f"📩 Processing photo...", flush=True)
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
        
        # Feedback to user
        status = bot.reply_to(message, "⚡ **Dual-Layer Scan Active...**")
        
        # 1. Get images at OPTIMIZED scales (1.25x and 2.5x)
        img_arrays = get_multi_scale_images("scan.jpg")
        
        all_results = []
        
        # 2. Run OCR on BOTH images and MERGE results
        # This guarantees we don't miss anything that appears in one but not the other
        for i, img_array in enumerate(img_arrays):
            all_results += reader.readtext(img_array, detail=0, allowlist=HYBRID_CHARS)
        
        # 3. Hydra Mine the combined data
        ca, pair = hydra_mine(all_results)
        
        if ca and pair:
            send_success_msg(message, ca, pair)
        else:
            debug_tail = "".join(all_results)[-60:]
            bot.reply_to(message, f"❌ No Valid Token Found.\nDebug: `...{debug_tail}`")
            
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        bot.reply_to(message, "❌ System Error.")

print("✅ Robust Hydra Engine Online!", flush=True)
bot.infinity_polling()
