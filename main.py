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

# Zaman pencereleri (saat cinsinden)
WINDOWS = [1, 4, 8, 12, 24]

# ===== VERİ TAKİBİ VE ANALİZ MERKEZİ =====
class AnomalyTracker:
    def __init__(self):
        # Verileri zaman damgasıyla tutuyoruz
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

# ===== PARSER =====
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

# ===== SİNYAL ÜRETİCİ =====
async def process_signals(data, bot):
    signals = []
    now_str = datetime.now().strftime("%H:%M:%S")

    # 1. ÖZEL FİLTRE: Long/Short %5 Mutlak Değişim (Son veriye göre)
    if len(tracker.history['long_ratio']) >= 2:
        current_long = data['long_ratio']
        last_long = tracker.history['long_ratio'][-2][0] # Bir önceki veri
        diff = current_long - last_long
        
        if abs(diff) >= 5.0:
            direction = "🟢 LONG AGRESİF ARTIŞ" if diff > 0 else "🔴 SHORT AGRESİF ARTIŞ"
            signals.append(f"⚡ <b>LS SERT SAPMA SİNYALİ</b>\n{direction}: %{abs(diff):.2f}\nGüncel Long: %{current_long:.2f}")

    # 2. ORTALAMA DIŞI ANOMALİLER (Diğer tüm veriler için)
    check_map = {
        'price': ('💰 Fiyat', '$', '{:,.2f}'),
        'oi': ('📊 Open Interest', 'BTC', '{:,.2f}'),
        'funding_rate': ('💸 Funding', '%', '{:.4f}'),
        'taker_buy': ('🔥 Buy Vol', 'BTC', '{:,.2f}')
    }

    for key, (label, unit, fmt) in check_map.items():
        if key in data:
            current_val = data[key]
            for hr in WINDOWS:
                avg = tracker.get_avg(key, hr)
                if avg:
                    # Ortalamadan % sapma (Eşik değerlerini Railway'den alır veya default %2/5 kullanırız)
                    change = ((current_val - avg) / avg) * 100
                    # OI ve Fiyat için farklı duyarlılıklar eklenebilir, şimdilik %2 sapma anomali sayılır
                    if abs(change) >= 2.0: 
                        signals.append(
                            f"⚠️ <b>{label} Anomalisi ({hr}s Ort.)</b>\n"
                            f"Değişim: %{change:+.2f}\n"
                            f"Güncel: {fmt.format(current_val)} {unit}"
                        )
                        break # Bir veri için en küçük zaman diliminde anomali varsa diğer saatlere bakmaya gerek yok

    if signals:
        msg = f"🚨 <b>ANOMALİ TESPİT EDİLDİ</b> (⏰ {now_str})\n\n" + "\n\n".join(signals)
        try:
            await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')
        except Exception as e: print(f"Gönderim hatası: {e}")

# ===== ANA DÖNGÜ =====
async def main():
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient('bot_session', API_ID, API_HASH)
    
    await client.start(phone=PHONE)
    
    # Giriş Mesajı
    await bot.send_message(chat_id=SIGNAL_CHAT_ID, 
        text="<b>🤖 Bot Başlatıldı</b>\n\n• L/S Oranı: %5 Mutlak Değişim Takibi\n• Diğer: 1-24s Ortalama Dışı Anomaliler", 
        parse_mode='HTML')

    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await process_signals(data, bot)
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
