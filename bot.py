import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr

TOKEN = os.getenv('TELEGRAM_TOKEN')
bot = telebot.TeleBot(TOKEN)

# Initialize EasyOCR once (Global) - CPU Mode
# This downloads the model on the first run (takes ~30s)
print("Loading Neural Network...")
reader = easyocr.Reader(['en'], gpu=False) 

def preprocess_image(input_path, output_path):
    """
    Standardizes image for the Neural Network.
    Converts dark mode -> bright text for easier reading.
    """
    with Image.open(input_path) as img:
        img = img.convert('RGB')
        # Scale up 2x (Neural nets love resolution)
        w, h = img.size
        img = img.resize((w*2, h*2), Image.Resampling.LANCZOS)
        
        # Binarize: High Contrast
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(4.0)
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        img.save(output_path, quality=100)

def extract_solana_ca(text):
    """
    Advanced Logic: Finds the best candidate string.
    1. Removes all spaces (fixes wrapped lines).
    2. Scans for 32-44 char strings.
    3. Validates Base58 rules (No 0, O, I, l).
    """
    # 1. Stitch everything into one block to fix newlines
    clean_block = re.sub(r'\s+', '', text)
    
    # 2. Fix common OCR mix-ups
    replacements = {'0': 'D', 'O': 'Q', 'I': 'j', 'l': 'k'}
    for k, v in replacements.items():
        clean_block = clean_block.replace(k, v)
        
    # 3. Sliding Window Regex
    # We look for the longest valid string of Base58 chars
    # This prevents "NFAD8..." because 'NFA' + 'D8...' is usually > 44 chars
    pattern = r'[1-9A-HJ-NP-Za-km-z]{32,44}'
    matches = re.findall(pattern, clean_block)
    
    # 4. Entropy Filter (Filter out marketing words)
    best_candidate = None
    for match in matches:
        # Real CAs look like noise (high variety of chars)
        if len(set(match)) >= 25: 
            # If we have multiple, prefer the longest one (safest bet)
            if best_candidate is None or len(match) > len(best_candidate):
                best_candidate = match
                
    return best_candidate

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🧠 **Neural Scan Active...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    
    # 1. Preprocess
    preprocess_image("raw.jpg", "proc.jpg")
    
    # 2. EasyOCR Scan (The Heavy Lifting)
    # detail=0 returns just the list of words
    try:
        result_list = reader.readtext("proc.jpg", detail=0)
        combined_text = "".join(result_list) # Join tightly
    except Exception as e:
        bot.edit_message_text(f"❌ OCR Error: {str(e)}", message.chat.id, status.message_id)
        return

    # 3. Extraction Logic
    ca = extract_solana_ca(combined_text)
    
    if ca:
        # Success Path
        try:
            res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").json()
            if res.get('pairs'):
                pair = res['pairs'][0]
                msg = (
                    f"🎯 **CA:** `{ca}`\n\n"
                    f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
                    f"💰 **Price:** `${pair['priceUsd']}`\n"
                    f"📊 **Liq:** `${pair['liquidity']['usd']:,}`\n"
                )
                markup = InlineKeyboardMarkup()
                markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
                bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
            else:
                bot.edit_message_text(f"✅ **CA Found:** `{ca}`\n(No market data yet - super early!)", message.chat.id, status.message_id)
        except:
             bot.edit_message_text(f"✅ **CA Found:** `{ca}`", message.chat.id, status.message_id)
    else:
        bot.edit_message_text("❌ No Solana CA found. The image might be too noisy.", message.chat.id, status.message_id)

bot.infinity_polling()
