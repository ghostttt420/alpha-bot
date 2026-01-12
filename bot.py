import os
import re
import requests
import telebot
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import time

TOKEN = os.getenv('TELEGRAM_TOKEN')
OCR_KEY = os.getenv('OCR_API_KEY')
bot = telebot.TeleBot(TOKEN)

# Try to import EasyOCR as fallback (optional but recommended)
try:
    import easyocr
    EASYOCR_AVAILABLE = True
    # Initialize reader once (reuse across requests)
    easy_reader = easyocr.Reader(['en'], gpu=False)
except ImportError:
    EASYOCR_AVAILABLE = False
    easy_reader = None
    print("⚠️ EasyOCR not available. Install with: pip install easyocr")

# Common OCR character confusions
OCR_CORRECTIONS = {
    'A': ['4'],  # OCR often reads 4 as A
    '4': ['A'],
    'O': ['0'],
    '0': ['O'],
    'I': ['1', 'l'],
    '1': ['I', 'l'],
    'l': ['1', 'I'],
    'S': ['5'],
    '5': ['S'],
    'B': ['8'],
    '8': ['B'],
    'Z': ['2'],
    '2': ['Z'],
}

def preprocess_image(input_path, output_path):
    """
    Multi-stage preprocessing for better OCR on dark/stylized screenshots
    """
    with Image.open(input_path) as img:
        # Convert to RGB first (handles RGBA, P mode, etc.)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        
        # 1. Increase size even more for character accuracy
        w, h = img.size
        img = img.resize((w*4, h*4), Image.Resampling.LANCZOS)
        
        # 2. Convert to grayscale
        img = ImageOps.grayscale(img)
        
        # 3. Increase contrast significantly (helps with dark backgrounds)
        img = ImageEnhance.Contrast(img).enhance(3.5)
        
        # 4. Increase brightness (crucial for dark screenshots)
        img = ImageEnhance.Brightness(img).enhance(1.8)
        
        # 5. Sharpen to enhance text edges
        img = ImageEnhance.Sharpness(img).enhance(2.5)
        
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
        img = img.resize((w*4, h*4), Image.Resampling.LANCZOS)
        
        # Invert colors BEFORE grayscale
        img = ImageOps.invert(img)
        img = ImageOps.grayscale(img)
        img = ImageEnhance.Contrast(img).enhance(3.0)
        img = ImageEnhance.Sharpness(img).enhance(2.5)
        img = ImageOps.autocontrast(img)
        
        img.save(output_path, quality=100, dpi=(300, 300))

def ocr_easyocr_scan(file_path):
    """
    Fallback OCR using EasyOCR (runs locally, no API key needed)
    Often better for screenshots with styled text
    """
    if not EASYOCR_AVAILABLE:
        return ""
    
    try:
        result = easy_reader.readtext(file_path, detail=0, paragraph=False)
        return ' '.join(result)
    except Exception as e:
        print(f"EasyOCR Error: {e}")
        return ""

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

def generate_address_variants(address):
    """
    Generate variants of an address by correcting common OCR errors
    """
    variants = [address]
    
    # Try fixing common character confusions
    for i, char in enumerate(address):
        if char in OCR_CORRECTIONS:
            for replacement in OCR_CORRECTIONS[char]:
                variant = address[:i] + replacement + address[i+1:]
                variants.append(variant)
    
    return variants

def validate_solana_address(address):
    """
    Quick validation for Solana addresses
    Returns True if the address looks valid
    """
    # Must be 32-44 characters (most are 43-44)
    if len(address) < 40 or len(address) > 44:  # More lenient for truncated
        return False
    
    # Must only contain Base58 characters
    if not re.match(r'^[1-9A-HJ-NP-Za-km-z]+$', address):
        return False
    
    # Should have good character distribution (not all same chars)
    if len(set(address)) < 15:  # Lower threshold for shorter addresses
        return False
    
    return True

def test_address_on_chain(address, chain='solana'):
    """
    Test if an address exists on-chain by querying DexScreener
    Returns True if the address is found
    """
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{address}"
        response = requests.get(url, timeout=5)
        data = response.json()
        return data.get('pairs') and len(data['pairs']) > 0
    except:
        return False

def find_best_address_match(potential_addresses):
    """
    Given multiple potential addresses (including OCR errors),
    find the one that actually exists on-chain
    """
    print(f"Testing {len(potential_addresses)} potential addresses...")
    
    for addr in potential_addresses:
        print(f"  Testing: {addr}")
        if test_address_on_chain(addr):
            print(f"  ✅ FOUND: {addr}")
            return addr
    
    print("  ❌ No valid address found")
    return None

def generate_truncated_variants(address):
    """
    Generate variants by adding possible missing characters at the end
    Common Solana address endings
    """
    if len(address) >= 44:
        return [address]  # Already full length
    
    # Most common Base58 characters that appear at end of Solana addresses
    common_endings = ['k', 'h', 'n', 't', 'p', 'm', 'K', 'H', 'N', 'T', 'P', 'M',
                      '1', '2', '3', '4', '5', '6', '7', '8', '9',
                      'A', 'B', 'C', 'D', 'E', 'F', 'G', 'J', 'L', 'Q', 'R', 'S', 'U', 'V', 'W', 'X', 'Y', 'Z',
                      'a', 'b', 'c', 'd', 'e', 'f', 'g', 'j', 'k', 'm', 'n', 'p', 'q', 'r', 's', 'u', 'v', 'w', 'x', 'y', 'z']
    
    variants = [address]
    
    # If address is 42-43 chars, add 1-2 characters
    chars_needed = 44 - len(address)
    
    if chars_needed == 1:
        # Try adding each possible character
        for char in common_endings:
            variants.append(address + char)
    elif chars_needed == 2:
        # Try common 2-char endings
        for char1 in common_endings[:30]:  # Limit to most common
            for char2 in common_endings[:30]:
                variants.append(address + char1 + char2)
    
    return variants

def extract_contract_addresses(text):
    """
    Extract contract addresses for multiple blockchains
    Returns dict with blockchain type and address
    """
    addresses = []
    
    # CRITICAL: Remove whitespace for matching (handles multi-line CAs)
    clean_text = re.sub(r'\s+', '', text)
    
    # Also try on original text with just newlines removed
    text_no_newlines = text.replace('\n', '').replace('\r', '')
    
    # Combine both for better matching
    all_text = clean_text + " " + text_no_newlines + " " + text
    
    seen = set()
    candidates = []
    
    # Try multiple patterns for Solana addresses
    solana_patterns = [
        r'[1-9A-HJ-NP-Za-km-z]{43,44}',  # Full length
        r'[1-9A-HJ-NP-Za-km-z]{42,43}',  # Missing 1-2 chars
        r'[1-9A-HJ-NP-Za-km-z]{40,42}',  # Missing 2-4 chars (very lenient)
    ]
    
    for pattern in solana_patterns:
        solana_matches = re.findall(pattern, all_text)
        
        for addr in solana_matches:
            if addr in seen:
                continue
            
            # For short addresses, generate truncated variants
            if len(addr) < 44:
                truncated_variants = generate_truncated_variants(addr)
                print(f"Generated {len(truncated_variants)} variants for truncated address: {addr}")
            else:
                truncated_variants = [addr]
            
            seen.add(addr)
            
            # For each truncated variant, also apply OCR corrections
            for trunc_variant in truncated_variants:
                if not validate_solana_address(trunc_variant):
                    continue
                
                # Apply OCR corrections to this variant
                ocr_variants = generate_address_variants(trunc_variant)
                
                for final_variant in ocr_variants:
                    if validate_solana_address(final_variant) and final_variant not in [c['address'] for c in candidates]:
                        candidates.append({
                            'chain': 'solana',
                            'address': final_variant,
                            'original': addr,
                            'is_variant': final_variant != addr
                        })
    
    # Smart selection: Test candidates on-chain to find valid ones
    print(f"Found {len(candidates)} candidates (including variants)")
    
    # First, try original addresses (full length, no modifications)
    for candidate in candidates:
        if not candidate['is_variant']:
            if test_address_on_chain(candidate['address']):
                addresses.append(candidate)
                print(f"✅ Original address works: {candidate['address']}")
                return addresses  # Found it!
    
    # If no originals work, try variants (batch test for speed)
    print("Testing corrected variants...")
    for candidate in candidates[:100]:  # Limit to first 100 to avoid too many API calls
        if candidate['is_variant']:
            if test_address_on_chain(candidate['address']):
                addresses.append(candidate)
                print(f"✅ Corrected address works: {candidate['address']} (was: {candidate['original']})")
                return addresses  # Found it!
    
    # Ethereum/Base/BSC (0x + 40 hex chars)
    eth_matches = re.findall(r'0x[a-fA-F0-9]{40}', all_text)
    for addr in eth_matches:
        if addr not in [a['address'] for a in addresses]:
            addresses.append({'chain': 'ethereum', 'address': addr, 'original': addr, 'is_variant': False})
    
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

def format_token_message(token_data, ca, chain, was_corrected=False):
    """
    Format token data into a nice Telegram message
    """
    if not token_data:
        return f"❌ No data found for CA: `{ca}`"
    
    emoji_chain = "🔵" if chain == "ethereum" else "🟣"
    price_emoji = "📈" if token_data['price_change_24h'] > 0 else "📉"
    
    msg = ""
    if was_corrected:
        msg += "🔧 **Auto-corrected OCR errors!**\n\n"
    
    msg += f"{emoji_chain} **{token_data['name']} (${token_data['symbol']})**\n\n"
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
            "⚙️ **Analyzing image with AI...**",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        
        # Strategy 1: Enhanced preprocessing with engine 2
        preprocess_image(raw_path, proc_path)
        text1 = ocr_smart_scan(proc_path, engine=2)
        
        # Strategy 2: Same preprocessing with engine 1
        text2 = ocr_smart_scan(proc_path, engine=1)
        
        # Strategy 3: Inverted colors with engine 2
        preprocess_inverted(raw_path, proc_inv_path)
        text3 = ocr_smart_scan(proc_inv_path, engine=2)
        
        # Strategy 4: Inverted with engine 1
        text4 = ocr_smart_scan(proc_inv_path, engine=1)
        
        # Strategy 5-6: EasyOCR on both versions
        text5 = ""
        text6 = ""
        if EASYOCR_AVAILABLE:
            text5 = ocr_easyocr_scan(proc_path)
            text6 = ocr_easyocr_scan(proc_inv_path)
        
        # Combine all results
        combined_text = f"{text1}\n{text2}\n{text3}\n{text4}\n{text5}\n{text6}"
        
        print(f"OCR Results Combined Length: {len(combined_text)}")
        
        bot.edit_message_text(
            "🔍 **Detecting contract addresses...**",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        
        # Extract contract addresses with smart correction
        addresses = extract_contract_addresses(combined_text)
        
        if not addresses:
            bot.edit_message_text(
                "❌ **No contract address found**\n\n"
                "💡 The screenshot might be:\n"
                "• Too blurry or low resolution\n"
                "• Missing the full contract address\n"
                "• Using an unsupported format\n\n"
                "Try sending a clearer screenshot!",
                message.chat.id,
                status.message_id,
                parse_mode='Markdown'
            )
            return
        
        # Process each found address
        for idx, addr_info in enumerate(addresses[:3]):
            ca = addr_info['address']
            chain = addr_info['chain']
            was_corrected = addr_info.get('is_variant', False)
            
            bot.edit_message_text(
                f"✅ **CA Detected!**\n`{ca}`\n\n"
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
            result_msg = format_token_message(token_data, ca, chain, was_corrected)
            
            if idx == 0:
                bot.edit_message_text(
                    result_msg,
                    message.chat.id,
                    status.message_id,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            else:
                bot.send_message(
                    message.chat.id,
                    result_msg,
                    parse_mode='Markdown',
                    disable_web_page_preview=True
                )
            
            time.sleep(0.5)
        
        # Clean up
        for path in [raw_path, proc_path, proc_inv_path]:
            if os.path.exists(path):
                os.remove(path)
                
    except Exception as e:
        bot.edit_message_text(
            f"❌ **Error:** {str(e)}\n\nPlease try again!",
            message.chat.id,
            status.message_id,
            parse_mode='Markdown'
        )
        print(f"Error in handle_photo: {e}")
        import traceback
        traceback.print_exc()

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(
        message,
        "👋 **Welcome to Snap Alpha!**\n\n"
        "📸 **How it works:**\n"
        "1. Send me ANY crypto screenshot\n"
        "2. I'll auto-detect the contract address\n"
        "3. Get instant token data!\n\n"
        "✨ **Features:**\n"
        "• Auto-corrects OCR errors\n"
        "• Works with dark/light screenshots\n"
        "• Supports Solana, ETH, Base, BSC\n"
        "• No cropping needed!\n\n"
        "🚀 Just send a screenshot and I'll handle the rest!",
        parse_mode='Markdown'
    )

@bot.message_handler(commands=['test'])
def test_address(message):
    """
    Test command to manually input a CA
    Usage: /test D8FYTqJGSmJx2cchFDUgzMYEe4VDvUyGWAYCRJ4Xbonk
    """
    try:
        parts = message.text.split(maxsplit=1)
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /test <contract_address>")
            return
        
        ca = parts[1].strip()
        
        # Determine chain
        if ca.startswith('0x'):
            chain = 'ethereum'
            token_data = get_eth_token_data(ca)
        else:
            chain = 'solana'
            token_data = get_solana_token_data(ca)
        
        result_msg = format_token_message(token_data, ca, chain)
        bot.reply_to(message, result_msg, parse_mode='Markdown', disable_web_page_preview=True)
        
    except Exception as e:
        bot.reply_to(message, f"❌ Error: {str(e)}")

if __name__ == "__main__":
    print("🤖 Snap Alpha Bot started...")
    print(f"📊 EasyOCR Available: {EASYOCR_AVAILABLE}")
    bot.infinity_polling()