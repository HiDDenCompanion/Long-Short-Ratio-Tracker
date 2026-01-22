import re
import os
from datetime import datetime
from collections import deque
import asyncio
from telethon import TelegramClient, events
from telegram import Bot
import statistics

# ===== AYARLAR (Railway Environment Variables'dan alınacak) =====
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PHONE = os.getenv('PHONE', '')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL', '@longshortoi')
SIGNAL_BOT_TOKEN = os.getenv('SIGNAL_BOT_TOKEN', '')
SIGNAL_CHAT_ID = int(os.getenv('SIGNAL_CHAT_ID', '0'))

# Eşik değerleri (% olarak) - İsterseniz bunları da env'den alabilirsiniz
THRESHOLDS = {
    'price_change': float(os.getenv('THRESHOLD_PRICE', '2.0')),
    'open_interest': float(os.getenv('THRESHOLD_OI', '5.0')),
    'funding_rate': float(os.getenv('THRESHOLD_FR', '50.0')),
    'long_short_ratio': float(os.getenv('THRESHOLD_RATIO', '3.0')),
    'taker_volume': float(os.getenv('THRESHOLD_VOLUME', '30.0'))
}

# Son N veriyi saklayacağız (ortalama için)
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
        """Yeni veriyi ekle"""
        self.price_history.append(data.get('price', 0))
        self.oi_history.append(data.get('open_interest', 0))
        self.funding_rate_history.append(data.get('funding_rate', 0))
        self.long_ratio_history.append(data.get('long_ratio', 0))
        self.short_ratio_history.append(data.get('short_ratio', 0))
        self.taker_buy_history.append(data.get('taker_buy', 0))
        self.taker_sell_history.append(data.get('taker_sell', 0))
        self.last_data = data
    
    def get_average(self, data_list):
        """Ortalama hesapla"""
        if len(data_list) < 2:
            return None
        return statistics.mean(data_list)
    
    def calculate_change_percent(self, current, average):
        """Yüzdelik değişim hesapla"""
        if average == 0:
            return 0
        return ((current - average) / average) * 100

tracker = DataTracker()

# ===== VERİ PARSE ETME =====
def parse_message(text):
    """Telegram mesajını parse et"""
    data = {}
    
    try:
        # BTC Price
        price_match = re.search(r'\$ ([\d,]+\.\d+)', text)
        if price_match:
            data['price'] = float(price_match.group(1).replace(',', ''))
        
        # Open Interest
        oi_match = re.search(r'Open Interest\s+([\d,]+\.\d+) BTC', text)
        if oi_match:
            data['open_interest'] = float(oi_match.group(1).replace(',', ''))
        
        # Funding Rate
        fr_match = re.search(r'Funding Rate\s+([\d.]+) %', text)
        if fr_match:
            data['funding_rate'] = float(fr_match.group(1))
        
        # Long/Short Ratio
        long_match = re.search(r'🟢 LONG : ([\d.]+)%', text)
        short_match = re.search(r'🔴 SHORT : ([\d.]+)%', text)
        if long_match and short_match:
            data['long_ratio'] = float(long_match.group(1))
            data['short_ratio'] = float(short_match.group(1))
        
        # Taker Volume
        buy_match = re.search(r'Buy \+(\d+\.\d+)', text)
        sell_match = re.search(r'Sell \+(\d+\.\d+)', text)
        if buy_match:
            data['taker_buy'] = float(buy_match.group(1))
        if sell_match:
            data['taker_sell'] = float(sell_match.group(1))
        
    except Exception as e:
        print(f"⚠️ Parse hatası: {e}")
    
    return data

# ===== SİNYAL KONTROLÜ VE GÖNDERME =====
async def check_and_send_signals(data):
    """Anormal değişimleri kontrol et ve sinyal gönder"""
    signals = []
    
    # Yeterli veri var mı?
    if len(tracker.price_history) < 3:
        print(f"📊 Veri biriktiriliyor... ({len(tracker.price_history)}/{HISTORY_SIZE})")
        return
    
    # 1. Fiyat değişimi kontrolü
    avg_price = tracker.get_average(tracker.price_history)
    if avg_price and data.get('price'):
        price_change = tracker.calculate_change_percent(data['price'], avg_price)
        if abs(price_change) > THRESHOLDS['price_change']:
            direction = "📈 YÜKSELİŞ" if price_change > 0 else "📉 DÜŞÜŞ"
            signals.append(
                f"{direction} SİNYALİ\n"
                f"💰 Fiyat: ${data['price']:,.2f}\n"
                f"📊 Değişim: {price_change:+.2f}%\n"
                f"📌 Ortalama: ${avg_price:,.2f}"
            )
    
    # 2. Open Interest kontrolü
    avg_oi = tracker.get_average(tracker.oi_history)
    if avg_oi and data.get('open_interest'):
        oi_change = tracker.calculate_change_percent(data['open_interest'], avg_oi)
        if abs(oi_change) > THRESHOLDS['open_interest']:
            signals.append(
                f"⚠️ OPEN INTEREST UYARISI\n"
                f"📊 Değişim: {oi_change:+.2f}%\n"
                f"💼 Mevcut OI: {data['open_interest']:,.2f} BTC\n"
                f"📈 Ortalama: {avg_oi:,.2f} BTC"
            )
    
    # 3. Funding Rate kontrolü
    avg_fr = tracker.get_average(tracker.funding_rate_history)
    if avg_fr and data.get('funding_rate'):
        fr_change = tracker.calculate_change_percent(data['funding_rate'], avg_fr)
        if abs(fr_change) > THRESHOLDS['funding_rate']:
            signals.append(
                f"💸 FUNDING RATE UYARISI\n"
                f"📊 Değişim: {fr_change:+.2f}%\n"
                f"💵 Mevcut FR: {data['funding_rate']:.6f}%\n"
                f"📊 Ortalama: {avg_fr:.6f}%"
            )
    
    # 4. Long/Short Ratio kontrolü
    avg_long = tracker.get_average(tracker.long_ratio_history)
    if avg_long and data.get('long_ratio'):
        ratio_change = tracker.calculate_change_percent(data['long_ratio'], avg_long)
        if abs(ratio_change) > THRESHOLDS['long_short_ratio']:
            signals.append(
                f"⚖️ POZİSYON ORANI UYARISI\n"
                f"📊 Değişim: {ratio_change:+.2f}%\n"
                f"🟢 Long: {data['long_ratio']:.2f}%\n"
                f"🔴 Short: {data['short_ratio']:.2f}%\n"
                f"📌 Ortalama Long: {avg_long:.2f}%"
            )
    
    # 5. Taker Volume kontrolü
    avg_buy = tracker.get_average(tracker.taker_buy_history)
    if avg_buy and data.get('taker_buy'):
        buy_change = tracker.calculate_change_percent(data['taker_buy'], avg_buy)
        if abs(buy_change) > THRESHOLDS['taker_volume']:
            signals.append(
                f"🔥 TAKER VOLUME UYARISI\n"
                f"📊 Buy Değişim: {buy_change:+.2f}%\n"
                f"💚 Mevcut Buy: {data['taker_buy']:.2f} BTC\n"
                f"📊 Ortalama: {avg_buy:.2f} BTC"
            )
    
    # Sinyalleri gönder
    if signals:
        timestamp = datetime.now().strftime("%H:%M:%S")
        message = f"🚨 ANOMALİ TESPİT EDİLDİ! 🚨\n⏰ {timestamp}\n\n" + "\n\n".join(signals)
        
        try:
            bot = Bot(token=SIGNAL_BOT_TOKEN)
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=message)
            print(f"✅ Sinyal gönderildi: {len(signals)} adet anomali")
        except Exception as e:
            print(f"❌ Sinyal gönderme hatası: {e}")
    else:
        print(f"✓ Veri normal - Anomali yok")

# ===== MAIN =====
async def main():
    """Ana fonksiyon"""
    # Environment variables kontrolü
    if not all([API_ID, API_HASH, PHONE, SIGNAL_BOT_TOKEN, SIGNAL_CHAT_ID]):
        print("❌ HATA: Gerekli environment variables eksik!")
        print("Lütfen Railway'de şunları ayarlayın:")
        print("- API_ID")
        print("- API_HASH") 
        print("- PHONE")
        print("- SIGNAL_BOT_TOKEN")
        print("- SIGNAL_CHAT_ID")
        print("- SOURCE_CHANNEL (opsiyonel, default: @longshortoi)")
        return
    
    print("🤖 Bot başlatılıyor...")
    print(f"📡 Dinlenecek kanal: {SOURCE_CHANNEL}")
    print(f"📢 Sinyaller gönderilecek: {SIGNAL_CHAT_ID}")
    
    # Telethon client oluştur
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    await client.start(phone=PHONE)
    print("✅ Telegram'a bağlanıldı!")
    
    # Kanal mesajlarını dinle
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        text = event.message.message
        
        # Veriyi parse et
        data = parse_message(text)
        
        if data and data.get('price'):  # En azından fiyat varsa
            print(f"\n📥 Yeni veri alındı: ${data.get('price', 0):,.2f}")
            
            # Veriyi kaydet
            tracker.add_data(data)
            
            # Sinyalleri kontrol et ve gönder
            await check_and_send_signals(data)
        else:
            print("⚠️ Bu mesaj veri içermiyor, atlanıyor...")
    
    print(f"👂 {SOURCE_CHANNEL} kanalı dinleniyor...")
    print("⏳ Veriler bekleniyor...\n")
    print(f"📊 Eşik Değerleri:")
    print(f"  - Fiyat Değişimi: {THRESHOLDS['price_change']}%")
    print(f"  - Open Interest: {THRESHOLDS['open_interest']}%")
    print(f"  - Funding Rate: {THRESHOLDS['funding_rate']}%")
    print(f"  - Long/Short Ratio: {THRESHOLDS['long_short_ratio']}%")
    print(f"  - Taker Volume: {THRESHOLDS['taker_volume']}%\n")
    
    # Sürekli çalışır durumda tut
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
