import re
import os
from datetime import datetime, timedelta
from collections import deque
import asyncio
from telethon import TelegramClient, events
from telegram import Bot
import statistics

# ===== AYARLAR =====
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
PHONE = os.getenv('PHONE', '')
SOURCE_CHANNEL = os.getenv('SOURCE_CHANNEL', '@longshortoi')
SIGNAL_BOT_TOKEN = os.getenv('SIGNAL_BOT_TOKEN', '')
SIGNAL_CHAT_ID = int(os.getenv('SIGNAL_CHAT_ID', '0'))

WINDOWS = [1, 4, 8, 12, 24]

class AnomalyTracker:
    def __init__(self):
        self.history = {
            'price': deque(),
            'oi': deque(),
            'long_ratio': deque(),
            'funding_rate': deque(),
            'taker_buy': deque()
        }
        self.max_age = timedelta(hours=24)

    def add_data(self, data):
        now = datetime.now()
        for key in self.history:
            if key in data:
                self.history[key].append((data[key], now))
        self._cleanup()

    def _cleanup(self):
        now = datetime.now()
        for key in self.history:
            while self.history[key] and (now - self.history[key][0][1]) > self.max_age:
                self.history[key].popleft()

    def get_avg(self, key, hours):
        now = datetime.now()
        target = now - timedelta(hours=hours)
        values = [v for v, t in self.history[key] if t >= target]
        return statistics.mean(values) if len(values) >= 2 else None

tracker = AnomalyTracker()

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
    except Exception as e:
        print(f"⚠️ Parse hatası: {e}")
    return data

async def process_signals(data, bot):
    signals = []
    now_str = datetime.now().strftime("%H:%M:%S")

    # LOG: Analiz başlıyor
    print(f"🔍 [{now_str}] Veri analiz ediliyor...")

    # 1. LS Oranı Kontrolü
    if len(tracker.history['long_ratio']) >= 2:
        current_long = data['long_ratio']
        last_long = tracker.history['long_ratio'][-2][0]
        diff = current_long - last_long
        if abs(diff) >= 5.0:
            signals.append(f"⚡ <b>LS SERT SAPMA</b>: %{abs(diff):.2f}")

    # 2. Ortalama Anomalileri
    check_map = {'price': 'Fiyat', 'oi': 'OI', 'funding_rate': 'Funding', 'taker_buy': 'Buy Vol'}
    for key, label in check_map.items():
        if key in data:
            current_val = data[key]
            for hr in WINDOWS:
                avg = tracker.get_avg(key, hr)
                if avg:
                    change = ((current_val - avg) / avg) * 100
                    if abs(change) >= 2.0:
                        signals.append(f"⚠️ {label} Anomalisi ({hr}s Ort.): %{change:+.2f}")
                        break

    if signals:
        msg = f"🚨 <b>ANOMALİ TESPİT EDİLDİ</b>\n\n" + "\n\n".join(signals)
        try:
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')
            print(f"🚀 Sinyal Telegram'a gönderildi!")
        except Exception as e:
            print(f"❌ Telegram gönderim hatası: {e}")
    else:
        print("✅ Veriler normal seyrinde.")

async def main():
    print("🚀 Bot başlatma süreci başladı...")
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    await client.start(phone=PHONE)
    print("🌐 Telegram Client başarıyla bağlandı!")
    
    # Başlangıç bildirimi
    try:
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text="<b>✅ Bot Aktif ve Log Akışı Başladı!</b>", parse_mode='HTML')
    except: pass

    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        print(f"\n📩 [@longshortoi] Yeni mesaj yakalandı.")
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await process_signals(data, bot)
    
    print(f"👂 {SOURCE_CHANNEL} dinleniyor. Loglar burada görünecek...")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
