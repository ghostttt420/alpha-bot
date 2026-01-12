import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Config from GitHub Secrets
TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def ocr_from_image(file_path):
    """Upgraded for Alphanumeric Accuracy (Engine 2)"""
    try:
        payload = {
            'apikey': OCR_KEY,
            'language': 'eng',
            'isOverlayRequired': False,
            'scale': True,      # Helps with small/blurry text
            'OCREngine': 2      # Superior for Solana CA detection
        }
        with open(file_path, 'rb') as f:
            r = requests.post('https://api.ocr.space/parse/image', 
                             files={file_path: f}, 
                             data=payload, 
                             timeout=30)
        result = r.json()
        if result.get('ParsedResults'):
            return result['ParsedResults'][0]['ParsedText']
        return "ERROR: No text detected"
    except Exception as e:
        return f"ERROR: {str(e)}"

def get_market_data(ca):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}").json()
        pair = res['pairs'][0]
        return {
            "name": pair['baseToken']['name'],
            "symbol": pair['baseToken']['symbol'],
            "price": pair['priceUsd'],
            "mcap": pair.get('fdv', 0),
            "liq": pair['liquidity']['usd'],
            "url": pair['url']
        }
    except: return None

def check_rug(ca):
    try:
        res = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report").json()
        score = res.get('score', 'N/A')
        return f"{score} (Lower is better)"
    except: return "N/A"

@bot.message_handler(content_types=['photo'])
def handle_alpha_image(message):
    status = bot.reply_to(message, "⚡ **Reading Alpha (Engine 2)...**", parse_mode="Markdown")
    
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f:
        f.write(downloaded_file)
    
    raw_text = ocr_from_image("scan.jpg")
    
    # Improved Regex for 32-44 character Solana addresses
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', raw_text)
    
    if ca_match:
        ca = ca_match.group(0)
        data = get_market_data(ca)
        safety = check_rug(ca)
        
        if data:
            msg = (
                f"💎 **{data['name']} ({data['symbol']})**\n"
                f"💰 Price: `${data['price']}`\n"
                f"📊 MCAP: `${data['mcap']:,}`\n"
                f"🛡️ Rug Score: `{safety}`\n\n"
                f"📍 `{ca}`"
            )
            markup = InlineKeyboardMarkup()
            # Added a referral link to monetize your bot
            btn_buy = InlineKeyboardButton("💸 Trade on Trojan", url=f"https://t.me/solana_trojanbot?start=r-ghostt-{ca}")
            markup.add(btn_buy)
            
            bot.edit_message_text(msg, message.chat.id, status.message_id, 
                                parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text(f"✅ Found CA: `{ca}`\nWaiting for market data...", message.chat.id, status.message_id)
    else:
        bot.edit_message_text("❌ CA not detected. Try cropping the image to just the text!", message.chat.id, status.message_id)

bot.infinity_polling()
