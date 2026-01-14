import sys
import time

# CRASH REPORTER: If the bot fails to load, this prints WHY.
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

# --- CONFIGURATION ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
if not TOKEN:
    print("❌ Error: TELEGRAM_TOKEN is missing from Secrets!", flush=True)
    sys.exit(1)

bot = telebot.TeleBot(TOKEN)

# SOLANA ALPHABET (Strict Whitelist)
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

print("🧠 Loading Neural Network...", flush=True)
try:
    reader = easyocr.Reader(['en'], gpu=False)
except Exception as e:
    print(f"❌ FATAL ERROR loading EasyOCR: {e}", flush=True)
    sys.exit(1)

def preprocess_image(input_path, output_path):
    try:
        with Image.open(input_path) as img:
            img = img.convert('RGB')
            w, h = img.size
            # SPEED: Scale 2x (Balance of speed/quality)
            img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
            img = ImageOps.grayscale(img)
            img = ImageEnhance.Contrast(img).enhance(2.0)
            img.save(output_path, quality=100)
    except Exception as e:
        print(f"⚠️ Image Error: {e}")

def batch_check_dex(candidates):
    valid_pairs = []
    unique_candidates = list(set(candidates))
    
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
        for length in range(42, 45): 
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                if len(set(sub)) < 20: continue
                variants = generate_mutations(sub)
                all_candidates.extend(variants)

    if not all_candidates: return None, None
    
    valid_pairs = batch_check_dex(all_candidates)
    if valid_pairs:
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    print(f"📩 Photo received from {message.from_user.username}", flush=True)
    try:
        status = bot.reply_to(message, "⚡ **Speed Scan Active...**")
        
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
        
        preprocess_image("scan.jpg", "proc.jpg")
        
        results = reader.readtext("proc.jpg", detail=0, allowlist=SOLANA_CHARS)
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
            bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
        else:
            bot.edit_message_text(f"❌ **Scan Failed.**\nChecked {len(results)} text blocks.", message.chat.id, status.message_id)
    
    except Exception as e:
        print(f"❌ Error processing photo: {e}", flush=True)
        bot.reply_to(message, "❌ System Error. Check Logs.")

print("✅ Bot is Online and Polling!", flush=True)
bot.infinity_polling()
