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

# Zaman pencereleri
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
        # Sadece yeterli veri varsa ortalama döndür
        return statistics.mean(values) if len(values) >= 2 else None

    def get_count(self, key, hours):
        """Belirli zaman dilimindeki veri adedini döndürür"""
        now = datetime.now()
        target = now - timedelta(hours=hours)
        return len([v for v, t in self.history[key] if t >= target])

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
    except: pass
    return data

async def process_signals(data, bot):
    signals = []
    threshold_vol = float(os.getenv('THRESHOLD_VOLUME', '100.0'))
    
    # 1. LS Oranı (Mutlak %5 - Her zaman aktif)
    if len(tracker.history['long_ratio']) >= 2:
        diff = data['long_ratio'] - tracker.history['long_ratio'][-2][0]
        if abs(diff) >= 5.0:
            signals.append(f"⚡ <b>LS SERT SAPMA</b>: %{abs(diff):.2f}")

    # 2. Diğer Anomaliler
    check_map = {'price': 'Fiyat', 'oi': 'OI', 'funding_rate': 'Funding', 'taker_buy': 'Buy Vol'}
    for key, label in check_map.items():
        if key in data:
            current_val = data[key]
            for hr in WINDOWS:
                avg = tracker.get_avg(key, hr)
                count = tracker.get_count(key, hr)
                
                if avg:
                    # ÖZEL ŞART: Buy Vol için en az 4 saatlik (48 adet) veri birikmiş olmalı
                    if key == 'taker_buy' and count < 48:
                        continue 
                        
                    change = ((current_val - avg) / avg) * 100
                    
                    # Eşik kontrolü
                    threshold = threshold_vol if key == 'taker_buy' else 2.0
                    if abs(change) >= threshold:
                        signals.append(f"⚠️ {label} Anomalisi ({hr}s Ort.): %{change:+.2f}")
                        break

    if signals:
        msg = f"🚨 <b>STRATEJİK ANOMALİ</b>\n\n" + "\n\n".join(signals)
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')

async def main():
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient('bot_session', API_ID, API_HASH)
    await client.start(phone=PHONE)
    
    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await process_signals(data, bot)
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
