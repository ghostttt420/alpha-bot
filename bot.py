import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# SOLANA ALPHABET (Strict Whitelist)
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image(input_path, output_path):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # SPEED HACK 1: Scale 2x instead of 3x (Much faster on CPU)
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img.save(output_path, quality=100)

def batch_check_dex(candidates):
    """
    Checks up to 30 addresses in ONE network call.
    """
    valid_pairs = []
    unique_candidates = list(set(candidates))
    
    # DexScreener allows max 30 addresses per call
    chunk_size = 30
    for i in range(0, len(unique_candidates), chunk_size):
        batch = unique_candidates[i : i + chunk_size]
        try:
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            res = requests.get(url, timeout=2).json() # Reduced timeout
            if res.get('pairs'):
                valid_pairs.extend(res['pairs'])
        except:
            pass
            
    return valid_pairs

def generate_mutations(candidate):
    """
    Creates variations for common OCR typos.
    """
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
    
    # 1. Broad extraction (Whitelisted chars only)
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', full_stream)
    
    all_candidates = []
    
    for chunk in chunks:
        chunk_len = len(chunk)
        
        # SPEED HACK 2: Only check lengths 42-44
        # 99.9% of Solana CAs are 43 or 44 chars. Ignoring 32-41 saves massive time.
        for length in range(42, 45): 
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # SPEED HACK 3: Entropy Filter
                # If it doesn't have at least 25 unique chars, it's probably noise.
                # Don't waste time generating mutations for "NFA_DYOR_Marketing"
                if len(set(sub)) < 25:
                    continue

                variants = generate_mutations(sub)
                all_candidates.extend(variants)

    if not all_candidates:
        return None, None
        
    # Check them all in batches
    valid_pairs = batch_check_dex(all_candidates)
    
    if valid_pairs:
        # Sort by liquidity to find the real token
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚡ **Speed Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("scan.jpg", "proc.jpg")
    
    try:
        # Reading text...
        results = reader.readtext("proc.jpg", detail=0, allowlist=SOLANA_CHARS)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status.message_id)
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
        
        bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.edit_message_text(
            f"❌ **Scan Failed.**\nNo valid token found in {len(results)} text blocks.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
