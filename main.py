import re
import json
from datetime import datetime
from collections import deque
import asyncio
from telegram import Bot
from telegram.ext import Application, MessageHandler, filters
import statistics

# ===== AYARLAR =====
BOT_TOKEN = "YOUR_BOT_TOKEN"  # Sinyal göndermek için
SOURCE_CHAT_ID = "SOURCE_CHAT_ID"  # Verileri aldığınız bot/kanal ID
SIGNAL_CHAT_ID = "YOUR_USER_ID"  # Sinyal gönderilecek chat ID

# Eşik değerleri (% olarak)
THRESHOLDS = {
    'price_change': 2.0,           # Fiyat değişimi %2'den fazlaysa
    'open_interest': 5.0,          # OI değişimi %5'ten fazlaysa
    'funding_rate': 50.0,          # Funding rate %50'den fazla değişirse
    'long_short_ratio': 3.0,       # Long/Short oranı %3'ten fazla değişirse
    'taker_volume': 30.0           # Taker volume %30'dan fazla değişirse
}

# Son N veriyi saklayacağız (ortalama için)
HISTORY_SIZE = 12  # 12 * 5dk = son 1 saat

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
        """Yeni veriyi ekle"""
        self.price_history.append(data.get('price', 0))
        self.oi_history.append(data.get('open_interest', 0))
        self.funding_rate_history.append(data.get('funding_rate', 0))
        self.long_ratio_history.append(data.get('long_ratio', 0))
        self.short_ratio_history.append(data.get('short_ratio', 0))
        self.taker_buy_history.append(data.get('taker_buy', 0))
        self.taker_sell_history.append(data.get('taker_sell', 0))
    
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
        print(f"Parse hatası: {e}")
    
    return data

# ===== SİNYAL KONTROLÜ =====
async def check_signals(data, bot):
    """Anormal değişimleri kontrol et ve sinyal gönder"""
    signals = []
    
    # Yeterli veri var mı?
    if len(tracker.price_history) < 3:
        return
    
    # 1. Fiyat değişimi kontrolü
    avg_price = tracker.get_average(tracker.price_history)
    if avg_price:
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
    if avg_oi:
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
    if avg_fr:
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
    if avg_long:
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
    if avg_buy:
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
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=message)
            print(f"✅ Sinyal gönderildi: {len(signals)} adet")
        except Exception as e:
            print(f"❌ Sinyal gönderme hatası: {e}")

# ===== MESAJ İŞLEYİCİ =====
async def handle_message(update, context):
    """Gelen mesajları işle"""
    if not update.message or not update.message.text:
        return
    
    text = update.message.text
    
    # Veriyi parse et
    data = parse_message(text)
    
    if data:
        print(f"📥 Veri alındı: Price=${data.get('price', 0):,.2f}")
        
        # Veriyi kaydet
        tracker.add_data(data)
        
        # Sinyalleri kontrol et
        await check_signals(data, context.bot)

# ===== MAIN =====
def main():
    """Botu başlat"""
    print("🤖 Bot başlatılıyor...")
    
    # Bot oluştur
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Mesaj dinleyici ekle
    application.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    
    print("✅ Bot çalışıyor! Veriler bekleniyor...")
    
    # Botu çalıştır
    application.run_polling(allowed_updates=["message"])

if __name__ == "__main__":
    main()
