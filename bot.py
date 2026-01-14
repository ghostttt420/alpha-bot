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

# HYBRID WHITELIST
HYBRID_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0OIl5S"

print("🧠 Loading Neural Network...", flush=True)
reader = easyocr.Reader(['en'], gpu=False)

def process_image_at_scale(input_path, scale):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        new_w, new_h = int(w * scale), int(h * scale)
        img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        return np.array(img)

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
    # This was missing! It catches "NFAD8FY..." by simply sliding past "NFA"
    raw_chunks = re.findall(r'[a-zA-Z0-9]{32,}', full_stream)
    for chunk in raw_chunks:
         for length in range(32, 45):
            for start in range(0, len(chunk) - length + 1):
                sub = chunk[start : start + length]
                # Must contain numbers and letters
                if re.search(r'\d', sub) and re.search(r'[a-zA-Z]', sub):
                    all_candidates.append(sub)

    if not all_candidates: return None, None
    
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
        
        # --- ATTEMPT 1: FAST MODE (1.5x) ---
        # Solves Test B, C, and Twitter (via Logic C)
        status = bot.reply_to(message, "⚡ **Scanning (Fast Mode)...**")
        
        img_fast = process_image_at_scale("scan.jpg", 1.5)
        results_fast = reader.readtext(img_fast, detail=0, allowlist=HYBRID_CHARS)
        ca, pair = hydra_mine(results_fast)
        
        if ca and pair:
            send_success_msg(message, ca, pair)
            return

        # --- ATTEMPT 2: SLOW MODE (3.0x) ---
        # Solves Test A (Tiny Text)
        bot.edit_message_text("🔍 **Zooming in (High-Res Mode)...**", message.chat.id, status.message_id)
        
        img_slow = process_image_at_scale("scan.jpg", 3.0)
        results_slow = reader.readtext(img_slow, detail=0, allowlist=HYBRID_CHARS)
        ca, pair = hydra_mine(results_slow)
        
        if ca and pair:
            send_success_msg(message, ca, pair)
        else:
            debug_tail = "".join(results_fast + results_slow)[-60:]
            bot.reply_to(message, f"❌ No Valid Token Found.\nDebug: `...{debug_tail}`")
            
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        bot.reply_to(message, "❌ System Error.")

def send_success_msg(message, ca, pair):
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

print("✅ Final Hydra Engine Online!", flush=True)
bot.infinity_polling()
