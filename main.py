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

# ÖNEMLİ: Grup ID'leri genelde - ile başlar. Env'den gelen veriyi tam sayıya çeviriyoruz.
try:
    SIGNAL_CHAT_ID = int(os.getenv('SIGNAL_CHAT_ID', '0'))
except ValueError:
    SIGNAL_CHAT_ID = os.getenv('SIGNAL_CHAT_ID', '')

# Eşik değerleri (% olarak)
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
    
    def add_data(self, data):
        if 'price' in data: self.price_history.append(data['price'])
        if 'open_interest' in data: self.oi_history.append(data['open_interest'])
        if 'funding_rate' in data: self.funding_rate_history.append(data['funding_rate'])
        if 'long_ratio' in data: self.long_ratio_history.append(data['long_ratio'])
        if 'short_ratio' in data: self.short_ratio_history.append(data['short_ratio'])
        if 'taker_buy' in data: self.taker_buy_history.append(data['taker_buy'])
        if 'taker_sell' in data: self.taker_sell_history.append(data['taker_sell'])
    
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

# ===== MESAJ GÖNDERME FONKSİYONU =====
async def send_telegram_msg(bot, message):
    try:
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=message, parse_mode='HTML')
    except Exception as e:
        print(f"❌ Mesaj gönderme hatası: {e}")

# ===== BAŞLANGIÇ BİLGİSİ =====
async def send_startup_notification(bot):
    msg = (
        "<b>✅ BTC Analiz Botu Başlatıldı!</b>\n\n"
        "Aşağıdaki veriler anlık takip ediliyor:\n"
        "💰 <b>Fiyat Hareketleri</b>\n"
        "📊 <b>Open Interest (OI)</b>\n"
        "💸 <b>Funding Rates</b>\n"
        "⚖️ <b>Long/Short Oranları</b>\n"
        "🔥 <b>Taker Buy/Sell Hacmi</b>\n\n"
        "🚀 <i>Anomaliler tespit edildiğinde burada paylaşılacaktır.</i>"
    )
    await send_telegram_msg(bot, msg)

# ===== SİNYAL KONTROLÜ =====
async def check_and_send_signals(data, bot):
    signals = []
    if len(tracker.price_history) < 3:
        print(f"📊 Veri biriktiriliyor... ({len(tracker.price_history)}/{HISTORY_SIZE})")
        return

    # 1. Fiyat
    avg_p = tracker.get_average(tracker.price_history)
    if avg_p and 'price' in data:
        diff = tracker.calculate_change_percent(data['price'], avg_p)
        if abs(diff) > THRESHOLDS['price_change']:
            emoji = "📈" if diff > 0 else "📉"
            signals.append(f"{emoji} <b>Fiyat Değişimi:</b> %{diff:+.2f}\n💰 <b>Güncel:</b> ${data['price']:,.2f}")

    # 2. Open Interest
    avg_oi = tracker.get_average(tracker.oi_history)
    if avg_oi and 'open_interest' in data:
        diff = tracker.calculate_change_percent(data['open_interest'], avg_oi)
        if abs(diff) > THRESHOLDS['open_interest']:
            signals.append(f"⚠️ <b>OI Değişimi:</b> %{diff:+.2f}\n💼 <b>Mevcut:</b> {data['open_interest']:,.2f} BTC")

    # 3. Funding Rate
    avg_fr = tracker.get_average(tracker.funding_rate_history)
    if avg_fr and 'funding_rate' in data:
        diff = tracker.calculate_change_percent(data['funding_rate'], avg_fr)
        if abs(diff) > THRESHOLDS['funding_rate']:
            signals.append(f"💸 <b>Funding Rate Değişimi:</b> %{diff:+.2f}\n💵 <b>Mevcut:</b> %{data['funding_rate']:.4f}")

    if signals:
        now = datetime.now().strftime("%H:%M:%S")
        final_msg = f"🚨 <b>ANOMALİ TESPİT EDİLDİ</b> (⏰ {now})\n\n" + "\n\n".join(signals)
        await send_telegram_msg(bot, final_msg)

# ===== MAIN =====
async def main():
    if not all([API_ID, API_HASH, PHONE, SIGNAL_BOT_TOKEN, SIGNAL_CHAT_ID]):
        print("❌ HATA: Environment variables eksik!")
        return
    
    print("🤖 Bot hazırlanıyor...")
    client = TelegramClient('bot_session', API_ID, API_HASH)
    bot_instance = Bot(token=SIGNAL_BOT_TOKEN)
    
    await client.start(phone=PHONE)
    print("✅ Telegram bağlantısı başarılı!")
    
    # Başlangıç mesajını gönder
    await send_startup_notification(bot_instance)
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data and data.get('price'):
            tracker.add_data(data)
            await check_and_send_signals(data, bot_instance)
    
    print(f"👂 {SOURCE_CHANNEL} dinleniyor...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
