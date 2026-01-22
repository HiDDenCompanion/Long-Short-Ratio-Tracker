import re
import os
import asyncio
from datetime import datetime
from collections import deque
from telethon import TelegramClient, events
from telegram import Bot

# ===== AYARLAR (Railway Variables) =====
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PHONE = os.getenv('PHONE', '')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL', '@longshortoi')
SIGNAL_BOT_TOKEN = os.getenv('SIGNAL_BOT_TOKEN', '')
SIGNAL_CHAT_ID = int(os.getenv('SIGNAL_CHAT_ID', '0'))

class MomentumTracker:
    def __init__(self):
        self.history = {
            'price': deque(maxlen=288),
            'oi': deque(maxlen=288),
            'long_ratio': deque(maxlen=288),
            'funding_rate': deque(maxlen=288),
            'taker_buy': deque(maxlen=288)
        }

    def add_data(self, data):
        for key in self.history:
            if key in data:
                self.history[key].append(data[key])

tracker = MomentumTracker()

def clean_value(val_str):
    """K, M, B gibi birimleri sayıya çevirir"""
    if not val_str: return 0.0
    val_str = val_str.replace(',', '').upper().strip()
    
    # Harf ve rakam ayıklama
    multiplier = 1.0
    if 'K' in val_str: multiplier = 1000.0
    elif 'M' in val_str: multiplier = 1000000.0
    elif 'B' in val_str: multiplier = 1000000000.0
    
    # Sadece rakam ve nokta kalsın
    num_part = re.sub(r'[^\d.]', '', val_str)
    try:
        return float(num_part) * multiplier
    except:
        return 0.0

def parse_message(text):
    data = {}
    try:
        # Fiyat
        p = re.search(r'\$ ([\d,.]+)', text)
        if p: data['price'] = clean_value(p.group(1))
        
        # Open Interest (BTC cinsinden olanı alıyoruz)
        oi = re.search(r'Open Interest\s+([\d,.]+[KMB]?) BTC', text)
        if oi: data['oi'] = clean_value(oi.group(1))

        # L/S Oranı
        long_m = re.search(r'🟢 LONG : ([\d.]+)%', text)
        if long_m: data['long_ratio'] = float(long_m.group(1))
        
        # Funding Rate
        fr = re.search(r'Funding Rate\s+([\d.-]+) %', text)
        if fr: data['funding_rate'] = float(fr.group(1))
        
        # Taker Buy Volume
        buy = re.search(r'Buy \+([\d,.]+[KMB]?)', text)
        if buy: data['taker_buy'] = clean_value(buy.group(1))
        
    except Exception as e:
        print(f"⚠️ Parse hatası: {e}")
    return data

async def check_momentum(data, bot):
    signals = []
    t_price = float(os.getenv('THRESHOLD_PRICE', '1.0'))
    t_oi = float(os.getenv('THRESHOLD_OI', '3.0'))
    t_vol = float(os.getenv('THRESHOLD_VOLUME', '100.0'))
    t_ratio = float(os.getenv('THRESHOLD_RATIO', '5.0'))

    # 1. Long/Short Oranı (Mutlak Puan Filtresi)
    if 'long_ratio' in data and len(tracker.history['long_ratio']) >= 2:
        diff = data['long_ratio'] - tracker.history['long_ratio'][-2]
        if abs(diff) >= t_ratio:
            # Burayı güncelledik: Eksi değer kafa karışıklığını giderdik
            if diff > 0:
                direction = f"🟢 LONG ARTIŞI: +{diff:.2f} Puan"
            else:
                direction = f"🔴 SHORT ARTIŞI: {abs(diff):.2f} Puan"
            
            signals.append(f"⚖️ <b>L/S MAKAS DEĞİŞİMİ</b>\n{direction}")

    # 2. Diğerleri (Yüzdesel Momentum)
    checks = [
        ('price', '💰 Fiyat', t_price),
        ('oi', '📊 Open Interest', t_oi),
        ('taker_buy', '🔥 Buy Vol', t_vol)
    ]

    for key, label, threshold in checks:
        if key in data and len(tracker.history[key]) >= 2:
            current = data[key]
            prev = tracker.history[key][-2]
            if prev <= 0: continue
            
            change = ((current - prev) / prev) * 100
            if abs(change) >= threshold:
                icon = "🚀" if change > 0 else "📉"
                signals.append(f"{icon} <b>{label} Anomali</b>: %{change:+.2f}")

    if signals:
        now = datetime.now().strftime("%H:%M")
        msg = f"🚨 <b>MOMENTUM RAPORU</b> (⏰ {now})\n\n" + "\n\n".join(signals)
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')

async def main():
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(phone=PHONE)
    
    print("🌐 Bot Birim Dönüştürücü Desteğiyle Başlatıldı!")
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await check_momentum(data, bot)
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
