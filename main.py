import re
import os
import asyncio
from datetime import datetime, timedelta
from collections import deque
from telethon import TelegramClient, events
from telegram import Bot
import statistics

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
            'taker_buy': deque(maxlen=288),
            'taker_sell': deque(maxlen=288)
        }

    def add_data(self, data):
        for key in self.history:
            if key in data:
                self.history[key].append(data[key])

tracker = MomentumTracker()

def parse_message(text):
    data = {}
    try:
        p = re.search(r'\$ ([\d,]+\.\d+)', text)
        if p: data['price'] = float(p.group(1).replace(',', ''))
        oi = re.search(r'Open Interest\s+([\d,]+\.\d+) BTC', text)
        if oi: data['oi'] = float(oi.group(1).replace(',', ''))
        long_m = re.search(r'🟢 LONG : ([\d.]+)%', text)
        if long_m: data['long_ratio'] = float(long_m.group(1))
        fr = re.search(r'Funding Rate\s+([\d.]+) %', text)
        if fr: data['funding_rate'] = float(fr.group(1))
        buy = re.search(r'Buy \+(\d+\.\d+)', text)
        if buy: data['taker_buy'] = float(buy.group(1))
        sell = re.search(r'Sell \+(\d+\.\d+)', text)
        if sell: data['taker_sell'] = float(sell.group(1))
    except Exception as e:
        print(f"⚠️ Parse hatası: {e}")
    return data

async def check_momentum(data, bot):
    signals = []
    t_price = float(os.getenv('THRESHOLD_PRICE', '1.0'))
    t_oi = float(os.getenv('THRESHOLD_OI', '3.0'))
    t_vol = float(os.getenv('THRESHOLD_VOLUME', '100.0'))
    t_ratio = float(os.getenv('THRESHOLD_RATIO', '5.0'))
    t_fr = float(os.getenv('THRESHOLD_FR', '50.0'))

    # 1. Long/Short Oranı (Özel Mutlak Puan Filtresi)
    if 'long_ratio' in data and len(tracker.history['long_ratio']) >= 2:
        diff = data['long_ratio'] - tracker.history['long_ratio'][-2]
        if abs(diff) >= t_ratio:
            direction = "🟢 LONG GÜÇLENDİ" if diff > 0 else "🔴 SHORT GÜÇLENDİ"
            signals.append(f"⚖️ <b>L/S MAKAS DEĞİŞİMİ</b>\n{direction}: {diff:+.2f} Puan")

    # 2. Diğer Momentum Kontrolleri (Önceki Veriyle Kıyaslama)
    checks = [
        ('price', '💰 Fiyat', t_price, "{:,.2f}"),
        ('oi', '📊 Open Interest', t_oi, "{:,.2f}"),
        ('taker_buy', '🔥 Buy Vol', t_vol, "{:,.2f}"),
        ('funding_rate', '💸 Funding Rate', t_fr, "{:.4f}")
    ]

    for key, label, threshold, fmt in checks:
        if key in data and len(tracker.history[key]) >= 2:
            current = data[key]
            prev = tracker.history[key][-2]
            if prev == 0: continue
            
            change = ((current - prev) / prev) * 100
            if abs(change) >= threshold:
                icon = "🚀" if change > 0 else "📉"
                signals.append(
                    f"{icon} <b>{label} Anomali</b>\n"
                    f"Değişim: %{change:+.2f}\n"
                    f"Önceki: {fmt.format(prev)} | Güncel: {fmt.format(current)}"
                )

    if signals:
        now = datetime.now().strftime("%H:%M")
        msg = f"🚨 <b>MOMENTUM RAPORU</b> (⏰ {now})\n\n" + "\n\n".join(signals)
        try:
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')
            print(f"✅ [{now}] Sinyal gönderildi.")
        except Exception as e:
            print(f"❌ Mesaj hatası: {e}")

async def main():
    print("🚀 Bot başlatma süreci başladı...")
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    await client.start(phone=PHONE)
    print("🌐 Telegram Client başarıyla bağlandı!")
    
    # Başlangıç Mesajı
    start_text = (
        "<b>🤖 BTC Momentum Bot Aktif!</b>\n\n"
        "📈 5 dakikalık periyotlarla uçurum farklar takip ediliyor.\n"
        "⚖️ L/S Oranı: 5 Puan Sapma\n"
        "🔥 Hacim: %100 Sapma\n"
        "💰 Fiyat: %1 Sapma"
    )
    try:
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=start_text, parse_mode='HTML')
    except: pass

    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        now = datetime.now().strftime("%H:%M:%S")
        print(f"📩 [{now}] Veri geldi, analiz ediliyor...")
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await check_momentum(data, bot)
    
    print(f"👂 {SOURCE_CHANNEL} dinleniyor. Loglar akmaya hazır!")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
