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
    Standardizes image for EasyOCR.
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # Mild Binarization to keep grey text visible
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.0) 
        img = ImageEnhance.Sharpness(img).enhance(1.5)
        img.save(output_path, quality=100)

def check_dexscreener(ca):
    """
    The 'Truth' Oracle. Returns pair data if CA is valid.
    """
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        res = requests.get(url, timeout=2).json()
        if res.get('pairs'):
            return res['pairs'][0]
    except: pass
    return None

def mine_for_ca(text_list):
    """
    MINING LOGIC:
    Takes the noisy text stream and slides a window over it 
    to find the specific substring that works on-chain.
    """
    # 1. Create the "Dirt Pile" (Join everything, remove spaces)
    full_stream = "".join(text_list)
    clean_stream = re.sub(r'\s+', '', full_stream)
    
    # 2. Extract potential "chunks" (long alphanumeric strings)
    # We look for anything that *could* contain a CA (32+ chars)
    # This grabs "NFAD8FY...bonk501"
    chunks = re.findall(r'[a-zA-Z0-9]{32,}', clean_stream)
    
    for chunk in chunks:
        # A. Quick cleanup (Fix common OCR typos)
        chunk = chunk.replace('0', 'D').replace('O', 'Q').replace('l', '1').replace('I', 'j')
        
        # B. THE SLIDER (Brute Force Validation)
        # We test every possible substring of length 32 to 44.
        # This strips "NFA" from the front and "501" from the back.
        chunk_len = len(chunk)
        
        # Optimization: Only check substrings that regex match Solana rules first
        for length in range(32, 45): # Solana addresses are 32-44 chars
            for start in range(0, chunk_len - length + 1):
                candidate = chunk[start : start + length]
                
                # Regex Pre-check: Don't API check if it has illegal chars
                if re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', candidate):
                    # API Check: The final verdict
                    pair = check_dexscreener(candidate)
                    if pair:
                        return candidate, pair

    return None, None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⛏️ **Mining for Alpha...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    preprocess_image("raw.jpg", "proc.jpg")
    
    try:
        # Scan processed AND raw (in case contrast killed the grey text)
        results = reader.readtext("proc.jpg", detail=0) + reader.readtext("raw.jpg", detail=0)
    except Exception as e:
        bot.edit_message_text(f"❌ Error: {e}", message.chat.id, status.message_id)
        return

    # Mine the text
    ca, pair = mine_for_ca(results)
    
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
        # Debug: Show the last 100 chars to verify we saw the text
        debug_tail = "".join(results)[-100:]
        bot.edit_message_text(
            f"❌ **Mining Failed.**\n\n"
            f"I saw this dirt pile:\n`...{debug_tail}`\n"
            f"I sifted through it but found no valid matches.", 
            message.chat.id, status.message_id, parse_mode='Markdown'
        )

bot.infinity_polling()
