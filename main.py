import re
import os
import asyncio
from datetime import datetime
from collections import deque
from telethon import TelegramClient, events
from telethon.sessions import StringSession 
from telegram import Bot

# ===== AYARLAR =====
API_ID = int(os.getenv('API_ID', '0'))
API_HASH = os.getenv('API_HASH', '')
STRING_SESSION = os.getenv('TELEGRAM_STRING_SESSION', '')
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
    if not val_str: return 0.0
    val_str = val_str.replace(',', '').upper().strip()
    multiplier = 1.0
    if 'K' in val_str: multiplier = 1000.0
    elif 'M' in val_str: multiplier = 1000000.0
    elif 'B' in val_str: multiplier = 1000000000.0
    num_part = re.sub(r'[^\d.]', '', val_str)
    try:
        return float(num_part) * multiplier
    except:
        return 0.0

def parse_message(text):
    data = {}
    try:
        p = re.search(r'\$ ([\d,.]+)', text)
        if p: data['price'] = clean_value(p.group(1))
        oi = re.search(r'Open Interest\s+([\d,.]+[KMB]?) BTC', text)
        if oi: data['oi'] = clean_value(oi.group(1))
        long_m = re.search(r'🟢 LONG : ([\d.]+)%', text)
        if long_m: data['long_ratio'] = float(long_m.group(1))
        fr = re.search(r'Funding Rate\s+([\d.-]+) %', text)
        if fr: data['funding_rate'] = float(fr.group(1))
        buy = re.search(r'Buy \+([\d,.]+[KMB]?)', text)
        if buy: data['taker_buy'] = clean_value(buy.group(1))
    except: pass
    return data

async def check_momentum(data, bot):
    signals = []
    t_price = float(os.getenv('THRESHOLD_PRICE', '1.0'))
    t_oi = float(os.getenv('THRESHOLD_OI', '3.0'))
    t_vol = float(os.getenv('THRESHOLD_VOLUME', '100.0'))
    t_ratio = float(os.getenv('THRESHOLD_RATIO', '5.0'))

    # ⚖️ L/S Makas Değişimi (Önceki vs Güncel Puan)
    if 'long_ratio' in data and len(tracker.history['long_ratio']) >= 2:
        current_lr = data['long_ratio']
        prev_lr = tracker.history['long_ratio'][-2]
        diff = current_lr - prev_lr
        
        if abs(diff) >= t_ratio:
            direction = f"🟢 LONG ARTIŞI: +{diff:.2f} P" if diff > 0 else f"🔴 SHORT ARTIŞI: {abs(diff):.2f} P"
            signals.append(
                f"⚖️ <b>L/S MAKAS DEĞİŞİMİ</b>\n{direction}\n"
                f"<code>Eski: %{prev_lr:.2f} | Yeni: %{current_lr:.2f}</code>"
            )

    # 💰 📊 🔥 Diğerleri (Önceki vs Güncel Değer)
    checks = [
        ('price', '💰 Fiyat', t_price, "$"),
        ('oi', '📊 OI', t_oi, "BTC"),
        ('taker_buy', '🔥 Buy Vol', t_vol, "BTC")
    ]

    for key, label, threshold, unit in checks:
        if key in data and len(tracker.history[key]) >= 2:
            current, prev = data[key], tracker.history[key][-2]
            if prev <= 0: continue
            
            change = ((current - prev) / prev) * 100
            if abs(change) >= threshold:
                icon = "🚀" if change > 0 else "📉"
                # Rakamları binlik ayırıcı ile güzelleştiriyoruz
                signals.append(
                    f"{icon} <b>{label} Anomali</b>: %{change:+.2f}\n"
                    f"<code>Eski: {prev:,.2f} {unit}</code>\n"
                    f"<code>Yeni: {current:,.2f} {unit}</code>"
                )

    if signals:
        now = datetime.now().strftime("%H:%M")
        msg = f"🚨 <b>MOMENTUM RAPORU</b> (⏰ {now})\n\n" + "\n\n".join(signals)
        await bot.send_message(chat_id=SIGNAL_CHAT_ID, text=msg, parse_mode='HTML')

async def main():
    bot = Bot(token=SIGNAL_BOT_TOKEN)
    client = TelegramClient(StringSession(STRING_SESSION), API_ID, API_HASH)
    await client.start()
    
    print("🌐 Bot değer göstergeli sinyal moduyla başlatıldı!")

    @client.on(events.NewMessage(chats=SOURCE_CHANNEL))
    async def handler(event):
        data = parse_message(event.message.message)
        if data:
            tracker.add_data(data)
            await check_momentum(data, bot)
    
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
