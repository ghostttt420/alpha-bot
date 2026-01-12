import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# DEFINING THE CONSTRAINTS
# Solana Base58 Alphabet (No 0, O, I, l)
SOLANA_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"

# Initialize EasyOCR with strict whitelist
# This tells the AI: "Only recognize these characters. Ignore everything else."
print("Loading Neural Network with Constraints...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image(input_path, output_path):
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # 3x Scale for maximum clarity on the characters
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        
        # High Contrast
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.5)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def check_dex(ca):
    """
    Checks if a CA is valid on DexScreener.
    """
    if len(ca) < 32 or len(ca) > 44: return None
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=1).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except: pass
    return None

def generate_mutations(candidate):
    """
    The 'Fuzzy' Fixer.
    If OCR mistook a '4' for an 'A', this creates a variant to test.
    """
    mutations = [candidate]
    
    # Common OCR confusions in Crypto Fonts
    # We only swap if the char exists, to save API calls
    if 'A' in candidate: mutations.append(candidate.replace('A', '4'))
    if '4' in candidate: mutations.append(candidate.replace('4', 'A'))
    if '8' in candidate: mutations.append(candidate.replace('8', 'B'))
    if 'B' in candidate: mutations.append(candidate.replace('B', '8'))
    
    return list(set(mutations)) # Return unique mutations only

def smart_mine(text_results):
    # 1. Join everything. The Whitelist means we have less garbage to clean.
    full_stream = "".join(text_results)
    
    # 2. Extract anything that looks vaguely like a CA
    # Since we whitelisted, almost everything remaining is a potential char
    # We look for long blocks
    chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,}', full_stream)
    
    for chunk in chunks:
        # THE SLIDER
        chunk_len = len(chunk)
        # Test every window of 32-44 chars
        for length in range(32, 45):
            for start in range(0, chunk_len - length + 1):
                sub = chunk[start : start + length]
                
                # LEVEL 1: Check raw extraction
                pair = check_dex(sub)
                if pair: return sub, pair
                
                # LEVEL 2: Check Mutations (Fixing A vs 4, etc)
                variants = generate_mutations(sub)
                for v in variants:
                    if v == sub: continue
                    pair = check_dex(v)
                    if pair: return v, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🧠 **Constrained Neural Scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("scan.jpg", "proc.jpg")
    
    try:
        # THE MAGIC LINE: allowlist=SOLANA_CHARS
        # We force the OCR to ignore "NFA" (if we removed F/A from list, but we can't)
        # Instead, this ensures it never reads a '?' or '@' or '0'.
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
        # Debug
        debug_tail = "".join(results)[-80:]
        bot.edit_message_text(
            f"❌ **Mining Failed.**\n\n"
            f"Constrained Output:\n`...{debug_tail}`\n"
            f"Tried mutations but found no match.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
