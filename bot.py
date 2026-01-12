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
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # High Contrast Binarization
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def verify_on_chain(ca):
    """
    Queries DexScreener to see if the CA is real.
    """
    try:
        # Rate limit protection: Only check if format looks vague valid
        if len(ca) < 32 or len(ca) > 44: return None
        
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=2).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except: pass
    return None

def nuclear_extract(raw_text_list):
    """
    THE NUCLEAR OPTION:
    1. Stitches all text.
    2. Takes any long block (up to 100 chars).
    3. 'Slides' a window across it to find the hidden valid address.
    """
    full_block = "".join(raw_text_list)
    # Remove ONLY spaces/newlines
    clean_block = re.sub(r'\s+', '', full_block)

    # 1. Capture HUGE blocks (handling "DYOR" + "NFA" + "Address" glued together)
    # We look for anything 32 to 100 chars long
    matches = re.findall(r'[a-zA-Z0-9]{32,100}', clean_block)
    
    for candidate in matches:
        # 2. Repair common typos in the whole block first
        # Fix 0->D, O->Q, l->1, I->j
        clean_candidate = candidate.replace('0', 'D').replace('O', 'Q').replace('l', '1').replace('I', 'j')

        # 3. SLIDING WINDOW (The "Scanner")
        # We check every possible substring of length 32 to 44
        # This solves "DYORNFAD8FY..." by testing "DYORN...", then "YORNF...", then "ORNFA...", etc.
        
        limit = len(clean_candidate)
        for length in range(32, 45): # Test lengths 32 to 44
            for start in range(0, limit - length + 1):
                sub_slice = clean_candidate[start : start + length]
                
                # OPTIMIZATION: Don't API check if it has obvious illegal chars
                # (Solana Base58 has no 0, O, I, l - we already fixed them, but double check regex)
                if re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', sub_slice):
                    pair = verify_on_chain(sub_slice)
                    if pair:
                        return sub_slice, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚡ **Nuclear Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("scan.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("scan.jpg", "proc.jpg")
    
    try:
        result_list = reader.readtext("proc.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ OCR Error: {e}", message.chat.id, status.message_id)
        return

    # Run Nuclear Extraction
    ca, pair = nuclear_extract(result_list)
    
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
        # Debug: Show the user what text was seen so you know if the image is the problem
        debug_text = "".join(result_list)[:50]
        bot.edit_message_text(
            f"❌ **Scan Failed.**\n\n"
            f"I saw: `{debug_text}...`\n"
            f"I ran the slider but found no valid Solana CA.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
