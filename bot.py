import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# SOLANA ALPHABET (No 0, O, I, l)
# We use this to force the OCR to stay on track
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image(input_path, output_path):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def check_dex(ca):
    if len(ca) < 32 or len(ca) > 44: return None
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=1).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except: pass
    return None

def surgical_mutations(candidate):
    """
    THE FIX: Swaps ambiguous chars ONE BY ONE.
    Solves the problem where 'A' exists correctly in one spot 
    but is a typo for '4' in another spot.
    """
    mutations = []
    
    # Map of common OCR mix-ups
    confusions = {
        'A': ['4'], '4': ['A'],
        'B': ['8'], '8': ['B'],
        'G': ['6'], '6': ['G'],
        'Q': ['O', 'D'], # Q often mistaken for O/D
        'D': ['0', 'O'], # If we allowed 0/O, we'd map them here
    }
    
    # Iterate through every character in the string
    for i, char in enumerate(candidate):
        if char in confusions:
            # For each confusion, create a new string with JUST THIS ONE char swapped
            for replacement in confusions[char]:
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.append(new_variant)
                
    return mutations

def smart_mine(text_results):
    full_stream = "".join(text_results)
    
    # Extract long blocks (we use the Whitelist, so data is cleaner)
    # We look for anything 32+ chars long
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', full_stream)
    
    for chunk in chunks:
        chunk_len = len(chunk)
        # SLIDING WINDOW (32-44 chars)
        for length in range(32, 45):
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # Check 1: Is the raw OCR correct?
                pair = check_dex(sub)
                if pair: return sub, pair
                
                # Check 2: Try Surgical Mutations
                # This will generate "WAY...CRJ4X" from "WAY...CRJAX"
                variants = surgical_mutations(sub)
                for v in variants:
                    pair = check_dex(v)
                    if pair: return v, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🧬 **Surgical Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("scan.jpg", "proc.jpg")
    
    try:
        # Strict Whitelist + Detail=0
        results = reader.readtext("proc.jpg", detail=0, allowlist=SOLANA_CHARS)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status.message_id)
        return

    ca, pair = smart_mine(results)
    
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
        # Debug: Show the raw text so we can see if the 'A' is still there
        debug_tail = "".join(results)[-80:]
        bot.edit_message_text(
            f"❌ **Scan Failed.**\n\n"
            f"Raw Output:\n`...{debug_tail}`\n"
            f"Surgical mutations failed to fix the typo.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
