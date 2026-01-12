import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Initialize Neural Network (CPU Mode)
print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False)

def preprocess_image(input_path, output_path):
    """
    Standardizes image for the Neural Network.
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        # 2x Scale is the sweet spot for EasyOCR
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # High Contrast Binarization
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def verify_on_chain(ca):
    """
    The Source of Truth. Queries DexScreener to see if the CA is real.
    Returns: Pair Data (dict) or None
    """
    # Quick filter: Sol addresses are rarely < 32 or > 44 chars
    if len(ca) < 32 or len(ca) > 46: 
        return None
        
    try:
        # We suppress errors to keep logs clean during "brute force" checks
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=3).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except:
        pass
    return None

def deep_repair_and_extract(raw_text_list):
    """
    The Logic Engine:
    1. Stitches text.
    2. Repairs typos.
    3. Brute-forces prefixes (NFA, BUY, etc) by checking against API.
    """
    # 1. Stitch: Join all lines and remove spaces to fix broken lines
    full_block = "".join(raw_text_list)
    # Remove ONLY spaces/newlines, keep everything else
    clean_block = re.sub(r'\s+', '', full_block)

    # 2. Extract potential candidates (broad regex)
    # We allow '0', 'O', 'I', 'l' initially so we can repair them later
    matches = re.findall(r'[a-zA-Z0-9]{32,50}', clean_block)
    
    unique_candidates = set(matches)
    
    for candidate in unique_candidates:
        # A. Try Raw Candidate
        pair = verify_on_chain(candidate)
        if pair: return candidate, pair

        # B. Try "Repaired" Candidate (Fix OCR Typos)
        # Fix: 0->D, O->Q, l->1 (common mistakes)
        repaired = candidate.replace('0', 'D').replace('O', 'Q').replace('l', '1')
        if repaired != candidate:
            pair = verify_on_chain(repaired)
            if pair: return repaired, pair

        # C. Try "Prefix Stripping" (The "NFA" Fix)
        # If OCR glued "NFA" (3 chars) or "BUY" (3 chars) or "DYOR" (4 chars)
        # We try slicing off the first 3, 4, and 5 characters.
        for i in range(1, 6): # Try slicing 1 to 5 chars from start
            sliced = candidate[i:]
            pair = verify_on_chain(sliced)
            if pair: return sliced, pair
            
            # Also try repairing the sliced version
            repaired_sliced = sliced.replace('0', 'D').replace('O', 'Q').replace('l', '1')
            pair = verify_on_chain(repaired_sliced)
            if pair: return repaired_sliced, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚡ **Scanning & Verifying...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    # 1. Preprocess
    preprocess_image("scan.jpg", "proc.jpg")
    
    # 2. EasyOCR Scan
    try:
        # detail=0 gives simple list of strings
        result_list = reader.readtext("proc.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ OCR Error: {e}", message.chat.id, status.message_id)
        return

    # 3. Deep Extraction & Verification
    ca, pair = deep_repair_and_extract(result_list)
    
    if ca and pair:
        # SUCCESS
        msg = (
            f"✅ **Verified CA:** `{ca}`\n\n"
            f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
            f"💰 **Price:** `${pair['priceUsd']}`\n"
            f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
            f"📉 **1H Chg:** `{pair['priceChange']['h1']}%`"
        )
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
        markup.add(InlineKeyboardButton("📈 Chart", url=pair['url']))
        
        bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
    else:
        # FAIL (Debug Info)
        # Show the user what text was actually seen, so you know if it's a blurry image issue
        debug_text = "".join(result_list)[:60]
        bot.edit_message_text(
            f"❌ **No Valid Token Found.**\n\n"
            f"I saw this text: `{debug_text}...`\n"
            f"I checked variants but DexScreener said they don't exist.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
