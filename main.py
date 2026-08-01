import os
import time
import asyncio
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

# Globálna premenná pre ukladanie stiahnutého obsahu z webu
WEBSITE_DATA = ""

# --- 1. SYNCHRÓNNA FUNKCIA NA SCRAPING ---
def sync_scrape_vegnella():
    """
    Stiahne textový obsah zo všetkých kľúčových podstránok Vegnella.sk.
    Ošetruje vyrovnávaciu pamäť (cache), HTML balast a chybové stavy.
    """
    global WEBSITE_DATA
    urls = [
        "https://www.vegnella.sk",
        "https://www.vegnella.sk/obedy.html",
        "https://www.vegnella.sk/ponuka.html",
        "https://www.vegnella.sk/raw-torty.html",
        "https://www.vegnella.sk/kontakt.html"
    ]
    combined_text = ""
    status_log = []
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }

    for url in urls:
        try:
            fresh_url = f"{url}?_nocache={int(time.time())}"
            response = requests.get(fresh_url, headers=headers, timeout=4, allow_redirects=True)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                for script in soup(["script", "style"]):
                    script.extract()
                
                text = soup.get_text(separator='\n', strip=True)
                if len(text) > 50:
                    combined_text += f"\n=== OBSAH Z PODSTRÁNKY: {url} ===\n{text}\n"
                    status_log.append(f"OK ({len(text)} znakov): {url}")
                else:
                    status_log.append(f"PRÁZDNE: {url}")
            else:
                status_log.append(f"CHYBA {response.status_code}: {url}")
        except Exception as e:
            status_log.append(f"ZLYHALO: {url} ({str(e)})")

    if combined_text:
        WEBSITE_DATA = combined_text[:20000]
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Dáta z Vegnella.sk boli úspešne obnovené.")
    return status_log

# --- 2. ASYNCHRÓNNY OBAL (NEBLOKUJE SERVER) ---
async def async_scrape_vegnella():
    """Deleguje blokujúci scraping do samostatného vlákna (Thread Pool)."""
    return await asyncio.to_thread(sync_scrape_vegnella)

# --- 3. LIFESPAN A PLÁNOVAČ (APSCHEDULER) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await async_scrape_vegnella()
    
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(
        sync_scrape_vegnella, 
        trigger='cron', 
        day_of_week='mon-fri', 
        hour=7, 
        minute=0
    )
    scheduler.start()
    yield
    scheduler.shutdown()

# --- 4. INICIALIZÁCIA FASTAPI A MIDDLEWARE ---
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.vegnella.sk", "https://vegnella.sk", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    messages: list

# --- 5. ENDPOINTY ---
@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running"}

@app.get("/api/refresh")
async def refresh_data():
    log = await async_scrape_vegnella()
    return {
        "status": "Dáta boli manuálne obnovené!",
        "prehlad_stranok": log,
        "celkova_dlzka": len(WEBSITE_DATA)
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        if not WEBSITE_DATA:
            await async_scrape_vegnella()

        # LOGIKA ČASU A DÁTUMU (BRATISLAVA)
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        
        dni_sk = {
            'Monday': 'Pondelok', 'Tuesday': 'Utorok', 'Wednesday': 'Streda',
            'Thursday': 'Štvrtok', 'Friday': 'Piatok', 'Saturday': 'Sobota', 'Sunday': 'Nedeľa'
        }
        day_en = now.strftime("%A")
        day_sk = dni_sk.get(day_en, day_en)
        current_time_str = f"{day_sk}, {now.strftime('%d.%m.%Y %H:%M hodín')}"

        # Výpočet dátumu najbližšieho pondelka
        days_ahead = (0 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 16:
            days_ahead = 7
        elif day_en in ['Saturday', 'Sunday']:
            days_ahead = (7 - now.weekday()) % 7
            
        next_monday_date = (now + timedelta(days=days_ahead)).strftime("%d.%m.%Y")

# JEDNODUCHÝ SYSTEM PROMPT SO UNIVERZÁLNYMI PRAVIDLAMI
        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY ČAS SERVERA (BRATISLAVA): {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}

VŠEOBECNÉ PRAVIDLÁ OTVÁRACÍCH HODÍN A OBJEDNÁVANIA (PLATIA PRE AKÝKOĽVEK ČAS - TERAZ AJ V BUDÚCNOSTI):

DÔLEŽITÉ PRAVIDLO PRE VYHODNOCOVANIE ČASU:
- Ak zákazník v otázke NEUVEDIE žiadny konkrétny deň ani čas (napr. "Môžem si objednať menu?"), AUTOMATICKY vyhodnocuj pravidlá podľa AKTUÁLNEHO ČASU SERVERA ({current_time_str}).
- Ak zákazník v otázke UVDIE konkrétny čas alebo deň (napr. "v utorok o 10:00", "v pondelok poobede"), vyhodnoť pravidlá podľa ním zadaného času.

1. PRACOVNÉ DNI (PONDELOK až PIATOK):
   - Čas 08:00 až 10:00 (vrátane 10:00):
     * Obedové menu (Rozvoz / Donáška): POVOLENÉ (doručenie 11:00-13:00, obal 0.50 € / 0.30 €).
     * Obedové menu (Osobný odber): POVOLENÉ (vyzdvihnutie 11:00-16:00).
     * Stála ponuka jedál a nápoje: POVOLENÉ (iba osobný odber).
     * RAW torty: POVOLENÉ (osobný odber, min. 24h vopred).
     * Bio obchod: OTVORENÝ (08:00-16:00).
   
   - Čas po 10:00 do 16:00 (10:01 - 16:00):
     * Obedové menu (Rozvoz / Donáška): ZATVORENÉ (uzávierka bola o 10:00, o 11:00 alebo neskôr sa rozvoz nedá objednať).
     * Obedové menu (Osobný odber): Bot automaticky neobjedná, zákazník musí zavolať na +421 910 824 923 pre overenie porcií.
     * Stála ponuka, nápoje, RAW torty: POVOLENÉ.
     * Bio obchod: OTVORENÝ.

   - Čas pred 08:00 alebo po 16:00:
     * Objednávky na tento čas sú ZATVORENÉ.

2. SOBOTA:
   - Čas 10:00 až 12:00: Otvorený LEN Bio obchod a RAW torty (min. 24h vopred na +421 910 824 923). Jedlo nepripravujeme.
   - Mimo 10:00 - 12:00: ZATVORENÉ. Objednávky na tento čas sú ZATVORENÉ.
   - Nikdy nehovor "príďte zajtra", ale "v pondelok ({next_monday_date})".

3. NEDEĽA:
   - Celý deň ZATVORENÉ. Nikdy nehovor "príďte zajtra", ale "v pondelok ({next_monday_date})".

ŠTÝL A PRAVIDLÁ SPRÁVANIA (STRIKTNÉ):
- FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).
- TÉMA KONVERZÁCIE: Odpovedaj výlučne ohľadom bistra a bio obchodu Vegnella. Iné témy zdvorilo odmietni.
- ZÁKAZ VYMÝŠĽANIA: Drž sa výhradne faktov z týchto inštrukcií a dodaných dát z webu.
- NONSTOP INFORMOVANIE (24/7): Na otázky o ponuke, zložení jedál, cenníkoch a otváracích hodinách odpovedaj VŽDY bez ohľadu na otváracie hodiny.
- AK SI ZÁKAZNÍK CHCE OBJEDNAŤ: Vždy sa uisti, o aký typ objednávky má záujem (Obedové menu rozvoz/osobný odber, Stála ponuka, RAW torta) a vysvetli podmienky.

DÁTA Z WEBU VEGNELLA:
--------------------------------------------------
{WEBSITE_DATA}
--------------------------------------------------
"""

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation,
            timeout=10.0
        )
        
        reply = response.choices[0].message.content or ""
        clean_reply = reply.replace("**", "")
        
        return {"odpoved": clean_reply}
        
    except Exception as e:
        print(f"[ERROR] Chyba pri spracovaní chatu: {str(e)}")
        return {"odpoved": "Ospravedlňujem sa, momentálne pripojenie trvá dlhšie ako zvyčajne. Skúste prosím otázku zopakovať."}