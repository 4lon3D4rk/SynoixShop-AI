import discord, json, os
from discord.ext import commands
import google.generativeai as genai
from google.api_core import exceptions
from keep_alive import keep_alive

keep_alive()

# --- AYARLAR ---
with open('config.json', 'r') as f:
    config = json.load(f)

DISCORD_TOKEN = os.environ("DC_TOKEN")
GEMINI_API_KEY = os.environ("API_KEY")

genai.configure(api_key=GEMINI_API_KEY)

intents = discord.Intents.all()
bot = commands.Bot(command_prefix="...", intents=intents)

current_model_index = 0
MODEL_PRIORITY_LIST = [
    'models/gemini-3.1-pro-preview',
    'models/gemini-3.1-flash-lite',
    'models/gemini-2.5-pro',
    'models/gemma-4-31b-it',
    'models/gemini-2.5-flash'
]

# --- HAFIZA (MEMORY) SİSTEMİ ---
HISTORY_FILE = "history.json"

def load_history():
    """JSON dosyasından geçmişi okur. Yoksa boş sözlük döner."""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_history(history_data):
    """Güncel geçmişi JSON dosyasına yazar."""
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history_data, f, ensure_ascii=False, indent=4)

def analyze_server(guild):
    if not guild:
        return "Bu bir özel mesaj (DM), sunucu bilgisi yok."

    # Kuruluş tarihini daha okunabilir yapalım (Örn: 12 Mart 2024)
    created_at = guild.created_at.strftime("%d %B %Y")

    # Güvenlik ve Filtre Ayarları
    v_level = str(guild.verification_level)
    security_map = {
        "none": "Yok", "low": "Düşük", "medium": "Orta", 
        "high": "Yüksek", "extreme": "Çok Yüksek"
    }
    
    # Rolleri listele (İlk 10 rolü alalım ki prompt çok şişmesin)
    roles = [role.name for role in guild.roles if not role.is_default()]
    role_summary = ", ".join(roles[:10]) + ("..." if len(roles) > 10 else "")

    # Botları listele
    bots = [m.display_name for m in guild.members if m.bot and m.id != bot.user.id]
    
    # Kapsamlı Analiz Metni
    analysis = (
        f"--- SUNUCU KİMLİK KARTI ---\n"
        f"- Sunucu Adı: {guild.name}\n"
        f"- Sunucu Sahibi: {guild.owner} (ID: {guild.owner_id})\n"
        f"- Kuruluş Tarihi: {created_at}\n"
        f"- Toplam Üye: {guild.member_count}\n"
        f"- Kanal Sayısı: {len(guild.channels)} (Kategoriler dahil)\n"
        f"- Güvenlik Seviyesi: {security_map.get(v_level.lower(), v_level)}\n"
        f"- Önemli Roller: {role_summary}\n"
        f"- Mevcut Diğer Botlar: {', '.join(bots) if bots else 'Yok'}\n"
        f"- Sunucu Bölgesi/Özellikleri: {', '.join(guild.features) if guild.features else 'Standart'}"
    )
    return analysis

async def ask_gemini_with_fallback(prompt):
    global current_model_index
    
    for _ in range(len(MODEL_PRIORITY_LIST)):
        model_name = MODEL_PRIORITY_LIST[current_model_index]
        try:
            model = genai.GenerativeModel(model_name)
            # DİKKAT: Artık programı dondurmayan asenkron metodu kullanıyoruz!
            response = await model.generate_content_async(prompt)
            return response.text
            
        except exceptions.ResourceExhausted:
            print(f"⚠️ {model_name} kotası dolmuş. Bir sonraki modele geçiliyor...")
            current_model_index = (current_model_index + 1) % len(MODEL_PRIORITY_LIST)
            continue
            
        except Exception as e:
            print(f"❌ {model_name} hatası: {e}")
            current_model_index = (current_model_index + 1) % len(MODEL_PRIORITY_LIST)
            continue
            
    return None

@bot.event
async def on_ready():
    # Bot açıldığında tüm sunuculardaki üye listesini günceller
    for guild in bot.guilds:
        await guild.chunk() 
    print(f'{bot.user} hazır ve sunucuları taradı!')

@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message) or isinstance(message.channel, discord.DMChannel):
        async with message.channel.typing():
            try:
                server_name = message.guild.name if message.guild else "Özel Mesaj"
                user_name = message.author.display_name
                channel_name = message.channel.name if message.channel.type != discord.ChannelType.private else "DM"
                user_id = str(message.author.id) # Kişileri ID'lerine göre tanıyacağız
                
                user_input = message.content.replace(f'<@!{bot.user.id}>', '').replace(f'<@{bot.user.id}>', '').strip()

                if not user_input:
                    await message.reply("Efendim?")
                    return

                # Kullanıcının geçmişini yükle
                history_data = load_history()
                if user_id not in history_data:
                    history_data[user_id] = []

                # Geçmiş mesajları tek bir metin haline getir
                past_messages = "\n".join(history_data[user_id])

                # on_message içindeki ilgili bölüm
                server_info = analyze_server(message.guild)

                prompt_with_context = (
                    f"Senin adın 'Syno'. Şu an '{server_name}' sunucusundasın.\n\n"
                    f"{server_info}\n\n" # Tüm sunucu verisi burada
                    "TALİMATLAR:\n"
                    "1- Sunucuyla ilgili (sahibi kim, ne zaman kuruldu, kaç kanal var vb.) sorular gelirse "
                    "yukarıdaki 'SUNUCU KİMLİK KARTI' bilgilerini kullanarak kesin cevaplar ver.\n"
                    "2- 'Bilmiyorum' demek yerine bu verileri analiz et.\n"
                    "3- Eğer bilgi kartında olmayan çok teknik bir şey sorulursa, nazikçe o konuda yetkim olmadığını belirt.\n"
                    f"\n--- GEÇMİŞ ---\n{past_messages}\n"
                    f"\nKullanıcı ({user_name}): {user_input}\nSyno:"
                )

                # Asenkron fonksiyonu çağır (bot artık donmayacak)
                answer = await ask_gemini_with_fallback(prompt_with_context)

                if answer:
                    # Başarılı cevap gelirse bunu JSON'a kaydet
                    history_data[user_id].append(f"Kullanıcı: {user_input}")
                    history_data[user_id].append(f"Syno: {answer}")
                    
                    # Sadece son 10 mesajı tut (Hafızanın şişmesini engeller)
                    if len(history_data[user_id]) > 10:
                        history_data[user_id] = history_data[user_id][-10:]
                        
                    save_history(history_data)

                    # Discord mesaj sınırını kontrol et
                    if len(answer) > 2000:
                        await message.reply("Yanıtım Discord sınırlarını aşıyor, biraz kısaltmamı ister misin?")
                    else:
                        await message.reply(answer)
                else:
                    await message.reply("Şu an tüm zihnim çok yoğun, daha sonra tekrar deneyebilir misin?")

            except Exception as e:
                print(f"Genel Hata: {e}")
                await message.reply("Küçük bir teknik aksaklık oldu.")

    await bot.process_commands(message)

bot.run(DISCORD_TOKEN)