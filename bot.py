import os
import re
import requests
import telebot
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import time

TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

def preprocess_image(input_path, output_path):
    """
    Multi-stage preprocessing for better OCR on dark/stylized screenshots
    """
    with Image.open(input_path) as img:
        # Convert to RGB first (handles RGBA, P mode, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 1. Increase size first for better detail
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        
        # 2. Convert to grayscale
        img = ImageOps.grayscale(img)
        
        # 3. Increase contrast significantly (helps with dark backgrounds)
        img = ImageEnhance.Contrast(img).enhance(3.0)
        
        # 4. Increase brightness (crucial for dark screenshots)
        img = ImageEnhance.Brightness(img).enhance(1.5)
        
        # 5. Sharpen to enhance text edges
        img = ImageEnhance.Sharpness(img).enhance(2.0)
        
        # 6. Apply slight blur then sharpen (reduces noise)
        img = img.filter(ImageFilter.MedianFilter(size=3))
        img = img.filter(ImageFilter.SHARPEN)
        
        # 7. Auto-level (normalize histogram)
        img = ImageOps.autocontrast(img, cutoff=2)
        
        img.save(output_path, quality=100, dpi=(300, 300))

def preprocess_inverted(input_path, output_path):
    """
    Alternative preprocessing with inversion (white text on black -> black text on white)
    Better for OCR engines that expect dark text on light backgrounds
    """
    with Image.open(input_path) as img:
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        w, h = img.size
        img = img.resize((w*3, h*3), Image.Resampling.LANCZOS)
        
        # Invert colors BEFORE grayscale
        img = ImageOps.invert(img)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(2.5)
        img = ImageEnhance.Sharpness(img).enhance(1.8)
        img = ImageOps.autocontrast(img)
        
        img.save(output_path, quality=100, dpi=(300, 300))

def ocr_smart_scan(file_path, engine=2):
    """
    OCR with configurable engine
    Engine 1: Legacy (sometimes better for stylized text)
    Engine 2: Neural network-based (better for clean text)
    """
    try:
        payload = {
            'apikey': OCR_KEY,
            'language': 'eng',
            'OCREngine': engine,
            'scale': True,
            'isTable': False,
            'detectOrientation': True
        }
        with open(file_path, 'rb') as f:
            r = requests.post(
                'https://api.ocr.space/parse/image',
                files={'file': f},
                data=payload,
                timeout=30
            )
        
        result = r.json()
        if result.get('IsErroredOnProcessing'):
            return ""
        
        if result.get('ParsedResults'):
            full_text = result['ParsedResults'][0]['ParsedText']
            return full_text
        return ""
    except Exception as e:
        print(f"OCR Error: {e}")
        return ""

def extract_contract_addresses(text):
    """
    Extract contract addresses for multiple blockchains
    Returns dict with blockchain type and address
    """
    # Remove all whitespace and newlines for multi-line addresses
    clean_text = re.sub(r'\s+', '', text)
    
    addresses = []
    
    # Solana (Base58, 32-44 chars, starts with specific chars)
    solana_matches = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,44}', clean_text)
    for addr in solana_matches:
        # Filter out common false positives
        if not re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', addr):
            continue
        addresses.append({'chain': 'solana', 'address': addr})
    
    # Ethereum/Base/BSC (0x + 40 hex chars)
    # Keep original text for these (preserve 0x)
    eth_text = re.sub(r'\s+', '', text)
    eth_matches = re.findall(r'0x[a-fA-F0-9]{40}', eth_text)
    for addr in eth_matches:
        addresses.append({'chain': 'ethereum', 'address': addr})
    
    return addresses

def get_solana_token_data(ca):
    """
    Fetch Solana token data from DexScreener API
    """
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('pairs') and len(data['pairs']) > 0:
            # Get the pair with highest liquidity
            pair = max(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
            
            return {
                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                'symbol': pair.get('baseToken', {}).get('symbol', 'Unknown'),
                'price': float(pair.get('priceUsd', 0)),
                'liquidity': float(pair.get('liquidity', {}).get('usd', 0)),
                'market_cap': float(pair.get('fdv', 0)),
                'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                'dex': pair.get('dexId', 'Unknown'),
                'url': pair.get('url', '')
            }
    except Exception as e:
        print(f"Error fetching Solana data: {e}")
    return None

def get_eth_token_data(ca):
    """
    Fetch Ethereum/Base token data from DexScreener API
    """
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{ca}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get('pairs') and len(data['pairs']) > 0:
            pair = max(data['pairs'], key=lambda x: float(x.get('liquidity', {}).get('usd', 0)))
            
            return {
                'name': pair.get('baseToken', {}).get('name', 'Unknown'),
                'symbol': pair.get('baseToken', {}).get('symbol', 'Unknown'),
                'price': float(pair.get('priceUsd', 0)),
                'liquidity': float(pair.get('liquidity', {}).get('usd', 0)),
                'market_cap': float(pair.get('fdv', 0)),
                'volume_24h': float(pair.get('volume', {}).get('h24', 0)),
                'price_change_24h': float(pair.get('priceChange', {}).get('h24', 0)),
                'chain': pair.get('chainId', 'Unknown'),
                'dex': pair.get('dexId', 'Unknown'),
                'url': pair.get('url', '')
            }
    except Exception as e:
        print(f"Error fetching ETH data: {e}")
    return None

def format_token_message(token_data, ca, chain):
    """
    Format token data into a nice Telegram message
    """
    if not token_data:
        return f"❌ No data found for CA: `{ca}`"
    
    emoji_chain = "🔵" if chain == "ethereum" else "🟣"
    price_emoji = "📈" if token_data['price_change_24h'] > 0 else "📉"
    
    msg = f"{emoji_chain} **{token_data['name']} (${token_data['symbol']})**\n\n"
    msg += f"💰 **Price:** ${token_data['price']:.8f}\n"
    msg += f"{price_emoji} **24h Change:** {token_data['price_change_24h']:.2f}%\n"
    msg += f"💧 **Liquidity:** ${token_data['liquidity']:,.2f}\n"
    msg += f"📊 **Market Cap:** ${token_data['market_cap']:,.2f}\n"
    msg += f"📈 **24h Volume:** ${token_data['volume_24h']:,.2f}\n"
    msg += f"🏪 **DEX:** {token_data['dex']}\n\n"
    msg += f"📝 **CA:** `{ca}`\n\n"
    
    if token_data.get('url'):
        msg += f"🔗 [View on DexScreener]({token_data['url']})"
    
    return msg

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    status = bot.reply_to(message, "🔍 **Scanning screenshot...**", parse_mode='Markdown')
    
    try:
        # Download image
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        raw_path = "raw.jpg"
        proc_path = "processed.jpg"
        proc_inv_path = "processed_inverted.jpg"
        
        with open(raw_path, 'wb') as f:
            f.write(downloaded_file)
        
        # Try multiple preprocessing strategies
        bot.edit_message_text(
            "⚙️ **Processing image (Strategy 1/3)...**",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        
        # Strategy 1: Enhanced preprocessing
        preprocess_image(raw_path, proc_path)
        text1 = ocr_smart_scan(proc_path, engine=2)
        
        bot.edit_message_text(
            "⚙️ **Processing image (Strategy 2/3)...**",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        
        # Strategy 2: Inverted colors
        preprocess_inverted(raw_path, proc_inv_path)
        text2 = ocr_smart_scan(proc_inv_path, engine=2)
        
        bot.edit_message_text(
            "⚙️ **Processing image (Strategy 3/3)...**",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        
        # Strategy 3: Try engine 1 on inverted
        text3 = ocr_smart_scan(proc_inv_path, engine=1)
        
        # Combine all results
        combined_text = text1 + "\n" + text2 + "\n" + text3
        
        # Extract contract addresses
        addresses = extract_contract_addresses(combined_text)
        
        if not addresses:
            bot.edit_message_text(
                "❌ **No contract address found**\n\n"
                "💡 Tips:\n"
                "• Ensure the screenshot is clear\n"
                "• CA should be visible and not cut off\n"
                "• Try cropping to just the CA text",
                message.chat.id,
                status.message_id,
                parse_mode='Markdown'
            )
            return
        
        # Process each found address
        for idx, addr_info in enumerate(addresses[:3]):  # Limit to 3 addresses
            ca = addr_info['address']
            chain = addr_info['chain']
            
            bot.edit_message_text(
                f"🎯 **CA Found ({idx+1}/{len(addresses[:3])}):**\n`{ca}`\n\n"
                f"📊 Fetching {chain.title()} market data...",
                message.chat.id,
                status.message_id,
                parse_mode='Markdown'
            )
            
            # Fetch token data based on chain
            if chain == 'solana':
                token_data = get_solana_token_data(ca)
            else:
                token_data = get_eth_token_data(ca)
            
            # Send results
            result_msg = format_token_message(token_data, ca, chain)
            
            if idx == 0:
                # Edit the status message for the first result
                bot.edit_message_text(
                    result_msg,
                    message.chat.id,
                    status.message_id,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            else:
                # Send new message for additional results
                bot.send_message(
                    message.chat.id,
                    result_msg,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            
            time.sleep(0.5)  # Rate limit protection
        
        # Clean up
        for path in [raw_path, proc_path, proc_inv_path]:
            if os.path.exists(path):
                os.remove(path)
                
    except Exception as e:
        bot.edit_message_text(
            f"❌ **Error:** {str(e)}\n\nPlease try again or contact support.",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        print(f"Error in handle_photo: {e}")

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 **Welcome to Crypto CA Scanner!**\n\n"
        "📸 Send me a screenshot with a contract address and I'll fetch:\n"
        "• Token price & market cap\n"
        "• 24h volume & liquidity\n"
        "• Price changes\n"
        "• DEX info\n\n"
        "🔗 Supports: Solana, Ethereum, Base, BSC\n\n"
        "Just send a screenshot and I'll do the rest! 🚀",
        parse_mode='Markdown'
    )

if __name__ == "__main__":
    print("🤖 Bot started...")
    bot.infinity_polling()