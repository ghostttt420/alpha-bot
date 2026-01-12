import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import time

# Config from GitHub Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def solana_fuzzy_fix(text):
    """Fixes common OCR character swaps in Base58 strings"""
    # Solana doesn't use 0, O, I, or l
    fixes = {'0': 'D', 'O': 'Q', 'I': 'j', 'l': 'k'}
    for error, fix in fixes.items():
        text = text.replace(error, fix)
    return text

def preprocess_image(input_path, output_path):
    """High-contrast preprocessing for dark-mode screenshots"""
    with Image.open(input_path) as img:
        if img.mode != 'RGB': img = img.convert('RGB')
        # Scale 3x to sharpen small text
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = ImageEnhance.Brightness(img).enhance(1.2)
        img.save(output_path, quality=100)

def ocr_smart_scan(file_path):
    """Engine 2 optimized for alphanumeric strings"""
    try:
        payload = {'apikey': OCR_KEY, 'language': 'eng', 'OCREngine': 2, 'scale': True}
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', files={'file': f}, data=payload, timeout=30)
        result = r.json()
        if result.get('ParsedResults'):
            # STITCHING: Rejoin broken lines by removing ALL whitespace
            return re.sub(r'\s+', '', result['ParsedResults'][0]['ParsedText'])
        return ""
    except: return ""

def get_rug_report(ca):
    """Fetches trust score and risks from RugCheck"""
    try:
        url = f"https://api.rugcheck.xyz/v1/tokens/{ca}/report"
        res = requests.get(url, timeout=10).json()
        score = res.get('score', 0)
        risks = [r['description'] for r in res.get('risks', [])]
        return score, risks[:3] # Return score and top 3 risks
    except: return "N/A", []

def get_market_data(ca):
    """Fetches DexScreener pricing and liquidity data"""
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").json()
        pair = max(res['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
        return {
            'name': pair['baseToken']['name'],
            'price': pair['priceUsd'],
            'liq': pair['liquidity']['usd'],
            'mcap': pair.get('fdv', 0),
            'url': pair['url']
        }
    except: return None

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "⚙️ **Engineering high-accuracy scan...**")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("raw.jpg", 'wb') as f: f.write(downloaded_file)
    
    preprocess_image("raw.jpg", "proc.jpg")
    raw_text = ocr_smart_scan("proc.jpg")
    fixed_text = solana_fuzzy_fix(raw_text)
    
    # RECONSTRUCTION: Catch 32-44 char Solana addresses
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', fixed_text)
    
    if ca_match:
        ca = ca_match.group(0)
        bot.edit_message_text(f"🎯 **CA Found:** `{ca}`\nRunning Safety Audit...", message.chat.id, status.message_id)
        
        market = get_market_data(ca)
        score, risks = get_rug_report(ca)
        
        if market:
            safety_icon = "✅" if score < 500 else "⚠️" if score < 2000 else "🚨"
            risk_text = "\n🚩 " + "\n🚩 ".join(risks) if risks else "\n✅ No major risks detected."
            
            msg = (
                f"💎 **{market['name']}**\n"
                f"💰 **Price:** `${market['price']}`\n"
                f"📊 **MCAP:** `${market['mcap']:,}`\n"
                f"🛡️ **Rug Score:** `{score}` {safety_icon}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"**Top Risks:**{risk_text}\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📍 `{ca}`"
            )
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("📈 Chart", url=market['url']),
                       InlineKeyboardButton("💸 Buy", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}"))
            
            bot.edit_message_text(msg, message.chat.id, status.message_id, parse_mode='Markdown', reply_markup=markup)
    else:
        bot.edit_message_text("❌ CA not detected. The address might be too fragmented.", message.chat.id, status.message_id)

bot.infinity_polling()
