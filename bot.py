import sys

# CRASH PROOFING
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

# HYBRID WHITELIST: Capture standard chars + illegal ones (0,O,I,l) + common typos (5, S)
# We capture everything here so the 3 Engines can filter it differently later.
HYBRID_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0OIl5S"

print("🧠 Loading Neural Network...", flush=True)
# gpu=False is CRITICAL for GitHub Actions stability
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image_to_memory(input_path):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # 1.5x Scale: Validated as the best speed/accuracy balance
        new_w, new_h = int(w * 1.5), int(h * 1.5)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        return np.array(img)

def batch_check_dex(candidates):
    valid_pairs = []
    # DEDUPLICATION IS CRITICAL HERE FOR SPEED
    unique_candidates = list(set(candidates))
    
    # Check 30 at a time (DexScreener API Limit)
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
    """
    Used by Engine 2: Swaps illegal chars for valid ones.
    """
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

    # --- ENGINE 1: THE PURIST (Solves Test A) ---
    # Strategy: Aggressively delete all illegal chars (0, O, I, l).
    # This effectively "unglues" words like "Gold" (l,o) or "Dior" (o) from the CA.
    strict_stream = re.sub(r'[0OIl5S]', '', full_stream) 
    # Look for clean Base58 blocks
    clean_chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', strict_stream)
    for chunk in clean_chunks:
        # Standard sliding window
        for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if len(set(sub)) > 15: all_candidates.append(sub)

    # --- ENGINE 2: THE MUTANT (Solves Test B & C) ---
    # Strategy: Keep illegal chars and mutate them.
    # Essential for when the address itself has a typo (Test C) or wrapped with '0' (Test B).
    dirty_chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z0OIl5S]{32,}', full_stream)
    for chunk in dirty_chunks:
        for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if len(set(sub)) < 15: continue
                # Apply mutations
                all_candidates.extend(mutate_dirty_string(sub))

    # --- ENGINE 3: THE RAW SLIDER (Solves Twitter/Messy) ---
    # Strategy: Trust the OCR. Sometimes the text is perfect but our regex filters ruin it.
    # We grab ANY long alphanumeric string and check it raw.
    raw_chunks = re.findall(r'[a-zA-Z0-9]{32,}', full_stream)
    for chunk in raw_chunks:
         for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                if re.search(r'\d', sub) and re.search(r'[a-zA-Z]', sub):
                    all_candidates.append(sub)

    if not all_candidates: return None, None
    
    # CONSOLIDATION: Batch Check All Candidates
    valid_pairs = batch_check_dex(all_candidates)
    
    if valid_pairs:
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(f"📩 Processing photo...", flush=True)
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
        
        img_array = preprocess_image_to_memory("scan.jpg")
        
        # SINGLE OCR PASS (Fast)
        results = reader.readtext(img_array, detail=0, allowlist=HYBRID_CHARS)
        
        # HYBRID LOGIC PROCESSING
        ca, pair = hydra_mine(results)
        
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
            debug_tail = "".join(results)[-60:]
            bot.reply_to(message, f"❌ No Valid Token Found.\nDebug: `...{debug_tail}`", parse_mode='Markdown')
            
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        bot.reply_to(message, "❌ System Error.")

print("✅ Hydra Engine Online!", flush=True)
bot.infinity_polling()
