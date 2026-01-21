# ==========================================
# 🤖 STEP 4: THE BOT ENGINE (OPTIMIZED HYBRID MODE)
# ==========================================
import userdata
import re
import requests
import telebot
import time
import cv2
import numpy as np
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from PIL import Image, ImageOps, ImageEnhance
import easyocr
import torch

print("🔄 Booting ScanAlpha Engine v4.4 (OPTIMIZED)...", flush=True)

try:
    TOKEN = userdata.get('TELEGRAM_TOKEN')
except:
    TOKEN = "PASTE_TOKEN_HERE_IF_NOT_USING_SECRETS"

bot = telebot.TeleBot(TOKEN)
reader = easyocr.Reader(['en'], gpu=True, quantize=False)

# HYBRID CHARACTER SET (From working script)
HYBRID_CHARS = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz0OIl5S"

# ==========================================
# 🖼️ IMAGE PROCESSING - OPTIMIZED
# ==========================================
def get_multi_scale_images(input_path):
    """Optimized image processing"""
    images = []
    
    try:
        # 1. GAUSSIAN ADAPTIVE THRESHOLDING (KEY FIX from working script)
        cv_img = cv2.imread(input_path, cv2.IMREAD_GRAYSCALE)
        
        if cv_img is not None:
            # Upscale 2x for small text
            cv_img = cv2.resize(cv_img, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            
            # Adaptive Gaussian Thresholding
            thresh = cv2.adaptiveThreshold(cv_img, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                          cv2.THRESH_BINARY, 31, 10)
            
            # Invert for EasyOCR (prefers black text on white background)
            final_scan = cv2.bitwise_not(thresh)
            images.append(final_scan)
            
        # 2. Original PIL Processing (scaled back)
        with Image.open(input_path) as img:
            img = img.convert('RGB')
            w, h = img.size
            
            # Use only 2.5x scale (best balance)
            scale = 2.5
            new_w, new_h = int(w * scale), int(h * scale)
            resized = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            img_proc = ImageOps.grayscale(resized)
            img_proc = ImageEnhance.Contrast(img_proc).enhance(2.0)
            img_proc = ImageEnhance.Sharpness(img_proc).enhance(1.5)
            images.append(np.array(img_proc))
            
    except Exception as e:
        print(f"⚠️ Image processing error: {e}")
        # Fallback
        img = cv2.imread(input_path, cv2.IMREAD_GRAYSCALE)
        if img is not None:
            images.append(img)
    
    return images

def extract_text_from_images(image_path):
    """Extract text using OPTIMIZED OCR strategies"""
    all_text = []
    
    # Get enhanced images
    images = get_multi_scale_images(image_path)
    
    if not images:
        # Fallback to original image
        images = [cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)]
    
    # Use only 2 strategies instead of 4
    for img in images:
        try:
            # STRATEGY 1: HYBRID CHARACTER SET (primary)
            results1 = reader.readtext(
                img,
                detail=0,
                allowlist=HYBRID_CHARS,
                batch_size=4,
                width_ths=0.7,
                height_ths=0.7,
                min_size=2,
                paragraph=False
            )
            all_text.extend(results1)
            
            # STRATEGY 2: Very lenient (for social media)
            results2 = reader.readtext(
                img,
                detail=0,
                batch_size=4,
                width_ths=1.5,
                height_ths=1.5,
                ycenter_ths=1.0,
                text_threshold=0.3,
                low_text=0.3
            )
            all_text.extend(results2)
            
        except Exception as e:
            continue
    
    # Clean and deduplicate
    clean_text = []
    seen = set()
    for text in all_text:
        text = str(text).strip()
        # Filter out very short or common words
        if (text and len(text) >= 5 and text not in seen and
            not text.isalpha() and  # Not pure letters
            not text.isdigit()):    # Not pure numbers
            seen.add(text)
            clean_text.append(text)
    
    return clean_text

# ==========================================
# ⛏️ OPTIMIZED HYDRA MINE EXTRACTION
# ==========================================
def mutate_dirty_string(candidate):
    """Optimized mutation - limited variations"""
    mutations = {candidate}
    confusions = {
        '0': ['D', 'O', 'Q'],
        'O': ['D', '0', 'Q'],
        'l': ['1', 'I'],
        'I': ['1', 'l'],
        'A': ['4'],
        '4': ['A'],
        'B': ['8'],
        '8': ['B'],
        'S': ['5'],
        '5': ['S'],
        'G': ['6'],
        '6': ['G'],
        '7': ['T'],
        'T': ['7']
    }
    
    # Only mutate first 3 ambiguous characters to limit variations
    ambiguous_count = 0
    for i, char in enumerate(candidate):
        if char in confusions and ambiguous_count < 3:
            ambiguous_count += 1
            for replacement in confusions[char]:
                new_variant = candidate[:i] + replacement + candidate[i+1:]
                mutations.add(new_variant)
    
    return list(mutations)[:10]  # Limit to 10 variations

def is_likely_solana(candidate):
    """Strict check if string looks like Solana address"""
    if len(candidate) < 32 or len(candidate) > 44:
        return False
    
    # Must be Base58 with no confusing chars
    if re.search(r'[^1-9A-HJ-NP-Za-km-z]', candidate):
        return False
    
    # Must have both letters and numbers
    if not (re.search(r'\d', candidate) and re.search(r'[A-Za-z]', candidate)):
        return False
    
    # Must have reasonable character diversity (not just repeating patterns)
    unique_chars = len(set(candidate))
    if unique_chars < 10:
        return False
    
    return True

def optimized_hydra_mine(text_results):
    """OPTIMIZED extraction - generates far fewer candidates"""
    all_candidates = []
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    
    # Join all text but keep track of original chunks
    full_stream = "".join(text_results)
    
    # STRATEGY 1: Look for exact Base58 strings 32-44 chars
    exact_matches = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,44}', full_stream)
    all_candidates.extend(exact_matches)
    
    # STRATEGY 2: Look for longer Base58 strings and extract 32-44 char substrings from them
    long_base58_chunks = re.findall(r'[1-9A-HJ-NP-Za-km-z]{45,100}', full_stream)
    for chunk in long_base58_chunks:
        # Take first 44 chars, last 44 chars, and middle section
        if len(chunk) >= 44:
            all_candidates.append(chunk[:44])
            all_candidates.append(chunk[-44:])
            
            # If very long, take a middle section
            if len(chunk) > 60:
                start = len(chunk) // 2 - 22
                all_candidates.append(chunk[start:start+44])
    
    # STRATEGY 3: Look for strings with confusing chars
    dirty_matches = re.findall(r'[1-9A-HJ-NP-Za-km-z0OIl5S]{32,44}', full_stream)
    for match in dirty_matches:
        # Only add if it looks promising
        if re.search(r'\d', match) and re.search(r'[A-Za-z]', match):
            all_candidates.append(match)
            # Limited mutations
            all_candidates.extend(mutate_dirty_string(match)[:3])
    
    # STRATEGY 4: Check individual text chunks that look like addresses
    for chunk in text_results:
        chunk_str = str(chunk).strip()
        # Remove common file extensions
        if chunk_str.endswith('.mp') and len(chunk_str) > 35:
            clean = chunk_str[:-3]  # Remove .mp
            if len(clean) >= 32 and len(clean) <= 44:
                all_candidates.append(clean)
        
        # Check if chunk itself looks like an address
        clean_chunk = re.sub(r'[^A-Za-z0-9]', '', chunk_str)
        if 32 <= len(clean_chunk) <= 44:
            if re.search(r'\d', clean_chunk) and re.search(r'[A-Za-z]', clean_chunk):
                all_candidates.append(clean_chunk)
    
    # Remove duplicates and invalid candidates
    unique_candidates = []
    seen = set()
    
    for cand in all_candidates:
        if cand not in seen:
            seen.add(cand)
            # Quick filter before expensive check
            if 32 <= len(cand) <= 44:
                # Count Base58 chars
                base58_count = sum(1 for c in cand if c in base58_chars)
                if base58_count / len(cand) > 0.9:  # At least 90% Base58
                    unique_candidates.append(cand)
    
    print(f"   ⛏️ Generated {len(unique_candidates)} candidates (optimized)")
    return unique_candidates[:500]  # LIMIT to 500 candidates max!

# ==========================================
# 🔍 MAIN ADDRESS FINDING FUNCTION
# ==========================================
def batch_check_dex(candidates):
    """Batch check candidates with DexScreener - OPTIMIZED"""
    if not candidates:
        return []
    
    # Filter and deduplicate
    unique_candidates = list(set(candidates))
    clean_candidates = []
    
    for cand in unique_candidates:
        if is_likely_solana(cand):
            clean_candidates.append(cand)
    
    print(f"   - Checking {len(clean_candidates)} likely candidates...")
    
    if not clean_candidates:
        return []
    
    valid_pairs = []
    chunk_size = 10  # Smaller chunks to avoid timeouts
    
    for i in range(0, len(clean_candidates), chunk_size):
        batch = clean_candidates[i : i + chunk_size]
        try:
            query_string = ",".join(batch)
            url = f"https://api.dexscreener.com/latest/dex/tokens/{query_string}"
            response = requests.get(url, timeout=10)  # Longer timeout
            if response.status_code == 200:
                data = response.json()
                if data.get('pairs'):
                    valid_pairs.extend(data['pairs'])
        except requests.exceptions.Timeout:
            print(f"   - Timeout on batch {i//chunk_size + 1}")
            continue
        except Exception as e:
            print(f"   - Batch error: {type(e).__name__}")
            continue
    
    return valid_pairs

def find_solana_address_in_text(text_chunks):
    """Main address finding function - OPTIMIZED"""
    print("   🔄 Running OPTIMIZED extraction...")
    
    # Try optimized hydra_mine
    candidates = optimized_hydra_mine(text_chunks)
    
    if candidates:
        valid_pairs = batch_check_dex(candidates)
        
        if valid_pairs:
            # Sort by liquidity
            valid_pairs.sort(key=lambda x: float(x.get('liquidity', {}).get('usd', 0)), reverse=True)
            best_pair = valid_pairs[0]
            ca = best_pair['baseToken']['address']
            print(f"✅ Found via optimized extraction: {ca[:15]}...")
            return ca, best_pair
    
    # Fallback: Direct pattern matching in text chunks
    print("   🔄 Trying direct pattern matching...")
    base58_chars = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    
    for chunk in text_chunks:
        chunk_str = str(chunk).strip()
        
        # Remove .mp extension if present
        if chunk_str.endswith('.mp'):
            chunk_str = chunk_str[:-3]
        
        # Look for Base58 strings 32-44 chars
        matches = re.findall(r'[1-9A-HJ-NP-Za-km-z]{32,44}', chunk_str)
        for match in matches:
            if is_likely_solana(match):
                # Check directly
                try:
                    url = f"https://api.dexscreener.com/latest/dex/tokens/{match}"
                    response = requests.get(url, timeout=5)
                    if response.status_code == 200:
                        data = response.json()
                        if data.get('pairs'):
                            ca = match
                            pair = data['pairs'][0]
                            print(f"✅ Found via direct match: {ca[:15]}...")
                            return ca, pair
                except:
                    continue
    
    return None, None

# ==========================================
# 💬 MESSAGE HANDLERS (UNCHANGED)
# ==========================================
def send_success_msg(message, ca, pair, time_taken):
    """Send success message with token info"""
    fdv = pair.get('fdv', 0)
    vol_24h = pair.get('volume', {}).get('h24', 0)
    change_24h = pair.get('priceChange', {}).get('h24', 0)
    change_icon = "🟢" if change_24h >= 0 else "🔴"
    
    # Format numbers
    def format_num(num):
        try:
            num = float(num)
            if num >= 1_000_000_000:
                return f"${num/1_000_000_000:.2f}B"
            elif num >= 1_000_000:
                return f"${num/1_000_000:.2f}M"
            elif num >= 1_000:
                return f"${num/1_000:.2f}K"
            return f"${num:.2f}"
        except:
            return "N/A"
    
    msg = (
        f"✅ **SOLANA CA FOUND**\n"
        f"`{ca}`\n\n"
        f"⏱️ **Scan Time:** `{time_taken:.2f}s`\n\n"
        f"💎 **{pair['baseToken']['name']}** (${pair['baseToken']['symbol']})\n"
        f"💰 **Price:** `${pair['priceUsd']}`\n"
        f"📈 **24h Change:** {change_icon} `{change_24h}%`\n"
        f"🧢 **Market Cap:** {format_num(fdv)}\n"
        f"💧 **Liquidity:** {format_num(pair['liquidity']['usd'])}\n"
        f"📊 **24h Volume:** {format_num(vol_24h)}\n"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 Trade (Trojan)", url=f"https://trojan.com/@ghostttt420?start={ca}"))
    markup.add(InlineKeyboardButton("📈 DexScreener", url=pair['url']))
    markup.add(InlineKeyboardButton("🔗 Solscan", url=f"https://solscan.io/token/{ca}"))
    
    bot.reply_to(message, msg, parse_mode='Markdown', reply_markup=markup)

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    """Handle incoming photo messages - OPTIMIZED"""
    start_time = time.time()
    user_info = f"@{message.from_user.username}" if message.from_user.username else f"ID:{message.from_user.id}"
    print(f"📩 Processing image from {user_info}...", flush=True)
    
    try:
        # Send initial status
        status = bot.reply_to(message, "🔍 **Scanning image (OPTIMIZED)...**")
        
        # Download the photo
        file_info = bot.get_file(message.photo[-1].file_id)
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Save to disk
        filename = f"scan_{int(time.time())}.jpg"
        with open(filename, 'wb') as f:
            f.write(downloaded_file)
        
        # Extract text from image
        print("   Extracting text...")
        text_chunks = extract_text_from_images(filename)
        
        if not text_chunks:
            bot.edit_message_text(
                "❌ No text detected in image.\n\n"
                "Please ensure the screenshot contains visible text.",
                message.chat.id,
                status.message_id
            )
            return
        
        print(f"📝 Found {len(text_chunks)} text chunks")
        if len(text_chunks) > 0:
            print(f"📝 Sample text (first 3): {text_chunks[:3]}")
        
        # Find Solana address
        print("   Searching for Solana address...")
        ca, pair = find_solana_address_in_text(text_chunks)
        
        total_time = time.time() - start_time
        
        if ca and pair:
            send_success_msg(message, ca, pair, total_time)
            bot.delete_message(message.chat.id, status.message_id)
            print(f"✅ Success! Found token in {total_time:.2f}s")
        else:
            # Show debug info
            sample_text = "\n".join([t[:50] for t in text_chunks[:5]])
            debug_msg = (
                f"❌ No valid Solana address found ({total_time:.2f}s)\n\n"
                f"**Text detected (first 300 chars):**\n"
                f"```\n{sample_text[:300]}\n```\n\n"
                f"**Tips for better results:**\n"
                f"1. Ensure entire address is visible\n"
                f"2. Crop to just the address area\n"
                f"3. Use higher contrast screenshots\n"
                f"4. Try light mode if using dark mode"
            )
            
            bot.edit_message_text(
                debug_msg,
                message.chat.id,
                status.message_id,
                parse_mode='Markdown'
            )
            print(f"❌ No address found in {total_time:.2f}s")
            
    except Exception as e:
        print(f"❌ Error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        try:
            bot.reply_to(message, "❌ System error. Please try again with a different screenshot.")
        except:
            pass

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Welcome message"""
    welcome_text = (
        "🤖 **ScanAlpha Bot v4.4 (OPTIMIZED)**\n\n"
        "I can extract Solana contract addresses from screenshots!\n\n"
        "**How to use:**\n"
        "1. Send me a screenshot containing a Solana address\n"
        "2. I'll use optimized OCR with candidate limiting\n"
        "3. Get instant token info and trading links\n\n"
        "**New in v4.4:**\n"
        "• Limited candidate generation to 500 max\n"
        "• Optimized batch checking with smaller chunks\n"
        "• Reduced API timeouts and errors\n"
        "• Better filtering of invalid candidates\n\n"
        "Just send me a screenshot! 📱"
    )
    bot.reply_to(message, welcome_text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    """Handle text messages"""
    if len(message.text) > 30:
        # Try to find address in text
        text_chunks = [message.text]
        ca, pair = find_solana_address_in_text(text_chunks)
        if ca and pair:
            send_success_msg(message, ca, pair, 0.1)
        else:
            bot.reply_to(message, "📸 Send me a screenshot for best results!")
    else:
        bot.reply_to(message, "📱 Send me a screenshot containing a Solana address!")

print("✅ ScanAlpha LIVE v4.4 (OPTIMIZED)!", flush=True)
print("🤖 Bot is ready to receive screenshots...", flush=True)

# Start polling
try:
    bot.infinity_polling(timeout=60, long_polling_timeout=60)
except Exception as e:
    print(f"❌ Polling error: {e}", flush=True)
    print("🔄 Restarting bot...", flush=True)
    time.sleep(5)
    bot.infinity_polling()