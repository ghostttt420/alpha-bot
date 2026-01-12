import os
import re
import requests
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Config from Environment Variables
TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def ocr_from_image(file_path):
    """Reads text from image using OCR.space API"""
    try:
        payload = {
            'apikey': OCR_KEY,
            'language': 'eng',
            'isOverlayRequired': False,
            'filetype': 'JPG'
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
    """Gets price and liquidity from DexScreener"""
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{ca}", timeout=10).json()
        if not res.get('pairs'): return None
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

def check_rug_score(ca):
    """Checks RugCheck.xyz for safety score"""
    try:
        res = requests.get(f"https://api.rugcheck.xyz/v1/tokens/{ca}/report", timeout=10).json()
        score = res.get('score', 'Unknown')
        # Map score to a readable status
        if isinstance(score, int):
            if score < 500: status = "✅ Safe"
            elif score < 2000: status = "⚠️ Risky"
            else: status = "🚨 High Risk"
            return f"{score} ({status})"
        return score
    except: return "N/A"

@bot.message_handler(commands=['start'])
def welcome(message):
    bot.reply_to(message, "🚀 **SnapAlpha is Active!**\nSend me a screenshot of a CA and I'll pull the stats.")

@bot.message_handler(content_types=['photo'])
def handle_alpha_image(message):
    status_msg = bot.reply_to(message, "🔍 **Scanning for Alpha...**", parse_mode="Markdown")
    
    # Download Photo
    file_info = bot.get_file(message.photo[-1].file_id)
    downloaded_file = bot.download_file(file_info.file_path)
    with open("scan.jpg", 'wb') as f:
        f.write(downloaded_file)
    
    # Run OCR
    raw_text = ocr_from_image("scan.jpg")
    
    # Extract Solana CA (Base58 regex)
    ca_match = re.search(r'[1-9A-HJ-NP-Za-km-z]{32,44}', raw_text)
    
    if ca_match:
        ca = ca_match.group(0)
        data = get_market_data(ca)
        safety = check_rug_score(ca)
        
        if data:
            msg = (
                f"💎 **{data['name']} ({data['symbol']})**\n"
                f"━━━━━━━━━━━━━━━\n"
                f"💰 **Price:** `${data['price']}`\n"
                f"📊 **MCAP:** `${data['mcap']:,}`\n"
                f"🌊 **Liquidity:** `${data['liq']:,}`\n"
                f"🛡️ **Rug Score:** `{safety}`\n"
                f"━━━━━━━━━━━━━━━\n"
                f"📍 ` {ca} ` (Tap to copy)"
            )
            
            # Create Buttons
            markup = InlineKeyboardMarkup()
            btn_chart = InlineKeyboardButton("📈 View Chart", url=data['url'])
            btn_buy = InlineKeyboardButton("💸 Buy (Trojan)", url=f"https://t.me/pro_onchain_dex_bot?start=r-ghostt-{ca}")
            markup.add(btn_chart, btn_buy)
            
            bot.edit_message_text(msg, message.chat.id, status_msg.message_id, 
                                parse_mode="Markdown", reply_markup=markup)
        else:
            bot.edit_message_text(f"✅ Found CA: `{ca}`\nToken found, but no market data available yet.", 
                                message.chat.id, status_msg.message_id)
    else:
        bot.edit_message_text("❌ No Solana CA detected in that image. Make sure the text is clear!", 
                            message.chat.id, status_msg.message_id)

bot.infinity_polling()
