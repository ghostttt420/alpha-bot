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
        # 3x Scale for maximum clarity
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img.save(output_path, quality=100)

def batch_check_dex(candidates):
    """
    THE SPEED FIX: Checks up to 30 addresses in ONE network call.
    """
    valid_pairs = []
    
    # Remove duplicates to save space
    unique_candidates = list(set(candidates))
    
    # DexScreener allows max 30 addresses per call
    chunk_size = 30
    for i in range(0, len(unique_candidates), chunk_size):
        batch = unique_candidates[i : i + chunk_size]
        try:
            # Join with commas: "addr1,addr2,addr3"
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            
            res = requests.get(url, timeout=3).json()
            if res.get('pairs'):
                # We found matches! Add them to our list.
                valid_pairs.extend(res['pairs'])
        except:
            pass
            
    return valid_pairs

def generate_mutations(candidate):
    """
    Creates variations to fix common OCR typos (A->4, B->8, etc)
    """
    mutations = {candidate} # Start with the raw string
    
    confusions = {
        'A': ['4'], '4': ['A'],
        'B': ['8'], '8': ['B'],
        'G': ['6'], '6': ['G'],
        'Q': ['O', 'D'], 
        'D': ['0', 'O']
    }
    
    # Generate all simple 1-char swaps
    for i, char in enumerate(candidate):
        if char in confusions:
            for replacement in confusions[char]:
                # Swap just this one character
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.add(new_variant)
                
    return list(mutations)

def fast_mine(text_results):
    full_stream = "".join(text_results)
    
    # 1. Collect ALL possible chunks (32+ chars)
    # We use the whitelist so this data is cleaner than before
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', full_stream)
    
    all_candidates = []
    
    for chunk in chunks:
        chunk_len = len(chunk)
        # 2. Sliding Window (32-44 chars)
        for length in range(32, 45):
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # 3. Generate Mutations for THIS window
                # Instead of checking immediately, we just ADD to the list
                variants = generate_mutations(sub)
                all_candidates.extend(variants)

    # 4. THE SHOTGUN: Check all 100+ candidates in 1-2 API calls
    if not all_candidates:
        return None, None
        
    print(f"Checking {len(all_candidates)} candidates...") # Debug log
    valid_pairs = batch_check_dex(all_candidates)
    
    if valid_pairs:
        # Return the most liquid pair found
        # (Sort by liquidity to avoid low-liq scam clones)
        best_pair = max(valid_pairs, key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return best_pair['baseToken']['address'], best_pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🚀 **Turbo Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("scan.jpg", "proc.jpg")
    
    try:
        # Strict Whitelist scan
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
        # Debug output only if it fails
        bot.edit_message_text(
            f"❌ **Scan Failed.**\nChecked {len(results)} text blocks but found no valid token.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
