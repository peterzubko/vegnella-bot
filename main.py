import os
import time
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from datetime import datetime
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

WEBSITE_DATA = ""

def scrape_vegnella():
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
            response = requests.get(fresh_url, headers=headers, timeout=8, allow_redirects=True)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                for script in soup(["script", "style"]):
                    script.extract()
                    
                text = soup.get_text(separator=' ', strip=True)
                if len(text) > 50:
                    combined_text += f"\n--- OBSAH Z PODSTRÁNKY: {url} ---\n{text}\n"
                    status_log.append(f"OK ({len(text)} znakov): {url}")
                else:
                    status_log.append(f"PRÁZDNE: {url}")
            else:
                status_log.append(f"CHYBA {response.status_code}: {url}")
        except Exception as e:
            status_log.append(f"ZLYHALO: {url} ({str(e)})")

    WEBSITE_DATA = combined_text[:15000]
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Dáta z Vegnella.sk boli úspešne aktualizované.")
    return status_log

@asynccontextmanager
async def lifespan(app: FastAPI):
    scrape_vegnella()
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(
        scrape_vegnella, 
        trigger='cron', 
        day_of_week='mon-fri', 
        hour=7, 
        minute=0
    )
    scheduler.start()
    yield
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    messages: list

@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running"}

@app.get("/api/refresh")
def refresh_data():
    log = scrape_vegnella()
    return {
        "status": "Dáta boli manuálne obnovené!",
        "prehlad_stranok": log,
        "celkova_dlzka": len(WEBSITE_DATA),
        "nahlad": WEBSITE_DATA[:800]
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        if not WEBSITE_DATA:
            scrape_vegnella()

        # --- LOGIKA REÁLNEHO ČASU A DŇA (SLOVENSKO) ---
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        
        dni_sk = {
            'Monday': 'Pondelok', 'Tuesday': 'Utorok', 'Wednesday': 'Streda',
            'Thursday': 'Štvrtok', 'Friday': 'Piatok', 'Saturday': 'Sobota', 'Sunday': 'Nedeľa'
        }
        day_en = now.strftime("%A")
        day_sk = dni_sk.get(day_en, day_en)
        current_time_str = f"{day_sk}, {now.strftime('%d.%m.%Y %H:%M hodín')}"

        hour = now.hour

        # PREVÁDZKOVÁ LOGIKA PODĽA ČASOVÝCH OBDOBÍ
        if day_en == 'Sunday':
            STATUS_TEXT = """
            STAV PREVÁDZKY: Dnes je NEDEĽA.
            - VARENÉ JEDLÁ A MENU: Nevarí sa. Donáška ani osobný odber obeda NIE SÚ MOŽNÉ. Nové menu na pondelok sa ešte len pripravuje.
            - RAW TORTY: Obnednať sa môžu iba počas otváracích hodín (pondelok - piatok 08:00 - 16:00, sobota 10:00 - 12:00) na t.č. +421 910 824 923.
            """
        elif day_en == 'Saturday':
            is_shop_open = (10 <= hour < 12)
            shop_status = "BIO OBCHOD je aktuálne OTVORENÝ (10:00 - 12:00)." if is_shop_open else "BIO OBCHOD je dnes otvorený od 10:00 do 12:00 (v tejto chvíli je ZATVORENÝ)."
            
            STATUS_TEXT = f"""
            STAV PREVÁDZKY: Dnes je SOBOTA. {shop_status}
            - VARENIE / DENNÉ MENU / STÁLA PONUKA: Cez víkend sa NEVARÍ! Žiadne jedlá ani obedy sa nedajú objednať ani vyzdvihnúť. Nové menu bude v pondelok.
            - Zákazník si RAW TORTU MÔŽE OBJEDNAŤ kedykoľvek telefonicky na +421 910 824 923 ale len počas otváracích hodín (sobota je to 10:00 - 12:00)!
            """
        else: # PRACOVNÉ DNI (PONDELOK - PIATOK)
            if hour < 8:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (pred 08:00). Otvárame o 08:00.
                - Donáška denného menu sa prijíma od 08:00 do 10:00.
                - RAW torty sa dajú objednať na +421 910 824 923.
                """
            elif 8 <= hour < 10:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (08:00 - 10:00).
                - DONÁŠKA DENNÉHO MENU JE OTVORENÁ A MOŽNÁ (do 10:00).
                - RAW torty sa dajú objednať vopred.
                """
            elif 10 <= hour < 16:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (10:00 - 16:00).
                - Donáška denného menu je ZATVORENÁ (bola do 10:00). Osobný odber obeda je možný do 16:00 po overení dostupnosti porcie na +421 910 824 923.
                - RAW torty sa dajú objednať.
                """
            else:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je po 16:00. Bistro aj predajňa sú zatvorené.
                """

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.
NIKDY na silu netlač zákazníka aby si čokoľvek objednal ak sa na to priamo nepýta.
Hovor iba priamo k veci, ohľadom toho čo zákazník pýta. Nepíš mu o iných veciach, ktoré si nevyžiadal.

AKTUÁLNY REÁLNY ČAS: {current_time_str}

==================================================
PRÍSNE NARIADENIE STAVU PREVÁDZKY:
{STATUS_TEXT}
==================================================

PRAVIDLÁ ODPOVEDE:
1. AK SA ZÁKAZNÍK PÝTA NA RAW TORTY ALEBO SI CHCE JEDNU OBJEDNAŤ:
   - Pripomeň, že RAW torty sa pripravujú čerstvo a potom sa musia zamraziť a je potrebné ich objednať aspoň 24 hodín vopred.
2. AK SA ZÁKAZNÍK PÝTA NA VARENÉ MENU / OBEDY CEZ VÍKEND:
   - Dôrazne vysvetli, že cez víkend sa nevarí a nové týždenné menu bude pripravené až na pondelok.
3. FORMÁTOVANIE:
   - ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text!
   - Používaj obyčajné pomlčky (-).

DÁTA Z WEBU VEGNELLA:
---
{WEBSITE_DATA}
---
"""

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation
        )
        
        reply = response.choices[0].message.content
        clean_reply = reply.replace("**", "")
        
        return {"odpoved": clean_reply}
        
    except Exception as e:
        return {"odpoved": f"Chyba na serveri: {str(e)}"}