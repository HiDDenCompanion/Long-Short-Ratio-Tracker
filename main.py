import re
import os
from datetime import datetime
from collections import deque
import asyncio
from telethon import TelegramClient, events
from telegram import Bot
import statistics

# ===== AYARLAR (Railway Environment Variables) =====
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PHONE = os.getenv('PHONE', '')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL', '@longshortoi')
SIGNAL_BOT_TOKEN = os.getenv('SIGNAL_BOT_TOKEN', '')
SIGNAL_CHAT_ID = int(os.getenv('SIGNAL_CHAT_ID', '0'))

THRESHOLDS = {
    'price_change': float(os.getenv('THRESHOLD_PRICE', '2.0')),
    'open_interest': float(os.getenv('THRESHOLD_OI', '5.0')),
    'funding_rate': float(os.getenv('THRESHOLD_FR', '50.0')),
    'long_short_ratio': float(os.getenv('THRESHOLD_RATIO', '3.0')),
    'taker_volume': float(os.getenv('THRESHOLD_VOLUME', '30.0'))
}

HISTORY_SIZE = int(os.getenv('HISTORY_SIZE', '12'))

# ===== VERİ DEPOLAMA =====
class DataTracker:
    def __init__(self, max_size=HISTORY_SIZE):
        self.price_history = deque(maxlen=max_size)
        self.oi_history = deque(maxlen=max_size)
        self.funding_rate_history = deque(maxlen=max_size)
        self.long_ratio_history = deque(maxlen=max_size)
        self.short_ratio_history = deque(maxlen=max_size)
        self.taker_buy_history = deque(maxlen=max_size)
        self.taker_sell_history = deque(maxlen=max_size)
        self.last_data = {}
    
    def add_data(self, data):
        self.price_history.append(data.get('price', 0))
        self.oi_history.append(data.get('open_interest', 0))
        self.funding_rate_history.append(data.get('funding_rate', 0))
        self.long_ratio_history.append(data.get('long_ratio', 0))
        self.short_ratio_history.append(data.get('short_ratio', 0))
        self.taker_buy_history.append(data.get('taker_buy', 0))
        self.taker_sell_history.append(data.get('taker_sell', 0))
        self.last_data = data
    
    def get_average(self, data_list):
        if len(data_list) < 2: return None
        return statistics.mean(data_list)
    
    def calculate_change_percent(self, current, average):
        if average == 0: return 0
        return ((current - average) / average) * 100

tracker = DataTracker()

# ===== VERİ PARSE ETME =====
def parse_message(text):
    data = {}
    try:
        price_match = re.search(r'\$ ([\d,]+\.\d+)', text)
        if price_match: data['price'] = float(price_match.group(1).replace(',', ''))
        
        oi_match = re.search(r'Open Interest\s+([\d,]+\.\d+) BTC', text)
        if oi_match: data['open_interest'] = float(oi_match.group(1).replace(',', ''))
        
        fr_match = re.search(r'Funding Rate\s+([\d.]+) %', text)
        if fr_match: data['funding_rate'] = float(fr_match.group(1))
        
        long_match = re.search(r'🟢 LONG : ([\d.]+)%', text)
        short_match = re.search(r'🔴 SHORT : ([\d.]+)%', text)
        if long_match and short_match:
            data['long_ratio'] = float(long_match.group(1))
            data['short_ratio'] = float(short_match.group(1))
        
        buy_match = re.search(r'Buy \+(\d+\.\d+)', text)
        sell_match = re.search(r'Sell \+(\d+\.\d+)', text)
        if buy_match: data['taker_buy'] = float(buy_match.group(1))
        if sell_match: data['taker_sell'] = float(sell_match.group(1))
    except Exception as e:
        print(f"⚠️ Parse hatası: {e}")
    return data

# ===== BAŞLANGIÇ MESAJI =====
async def send_startup_notification(bot):
    """Bot başladığında kullanıcıya bilgi verir"""
    msg = (
        "✅ **BTC Analiz Botu Başlatıldı!**\n\n"
        "Aşağıdaki veriler anlık olarak takip ediliyor:\n"
        "💰 **Fiyat Hareketleri**\n"
        "📊 **Open Interest (OI)**\n"
        "💸 **Funding Rates**\n"
        "⚖️ **Long/Short Oranları**\n"
        "🔥 **Taker Buy/Sell Hacmi**\n\n"
        "🚀 Anomaliler tespit edildiğinde sinyal gönderilecektir."
    )
    try:
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='Markdown')
    except Exception as e:
        print(f"❌ Başlangıç mesajı hatası: {e}")

# ===== SİNYAL KONTROLÜ VE GÖNDERME =====
async def check_and_send_signals(data):
    signals = []
    if len(tracker.price_history) < 3:
        return

    # Fiyat
    avg_price = tracker.get_average(tracker.price_history)
    if avg_price and data.get('price'):
        p_change = tracker.calculate_change_percent(data['price'], avg_price)
        if abs(p_change) > THRESHOLDS['price_change']:
            emoji = "📈" if p_change > 0 else "📉"
            signals.append(f"{emoji} **Fiyat:** ${data['price']:,.2f} ({p_change:+.2f}%)")

    # OI
    avg_oi = tracker.get_average(tracker.oi_history)
    if avg_oi and data.get('open_interest'):
        oi_change = tracker.calculate_change_percent(data['open_interest'], avg_oi)
        if abs(oi_change) > THRESHOLDS['open_interest']:
            signals.append(f"⚠️ **OI Değişimi:** {oi_change:+.2f}%")

    # Sinyal Gönderimi
    if signals:
        final_msg = f"🚨 **ANOMALİ TESPİT EDİLDİ** 🚨\n\n" + "\n".join(signals)
        try:
            bot = Bot(token=SIGNAL_BOT_TOKEN)
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=final_msg, parse_mode='Markdown')
        except Exception as e:
            print(f"❌ Mesaj gönderme hatası: {e}")

# ===== MAIN =====
async def main():
    if not all([API_ID, API_HASH, PHONE, SIGNAL_BOT_TOKEN, SIGNAL_CHAT_ID]):
        print("❌ Eksik environment variables!")
        return
    
    client = TelegramClient('bot_session', API_ID, API_HASH)
    bot_instance = Bot(token=SIGNAL_BOT_TOKEN)
    
    await client.start(phone=PHONE)
    
    # Başlatıldı mesajı gönder
    await send_startup_notification(bot_instance)
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data and data.get('price'):
            tracker.add_data(data)
            await check_and_send_signals(data)
    
    print("👂 Bot dinlemede...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
