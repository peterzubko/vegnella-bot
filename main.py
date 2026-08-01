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

        # PREVÁDZKOVÁ LOGIKA PODĽA OTVÁRACÍCH HODÍN
        if day_en == 'Sunday':
            STATUS_TEXT = """
            STAV PREVÁDZKY: Dnes je NEDEĽA – CELÝ DEŇ ZATVORENÉ.
            - VARENÉ JEDLÁ A MENU: Nevarí sa. Donáška ani osobný odber obeda NIE SÚ MOŽNÉ. Nové menu na pondelok sa ešte len pripravuje.
            - RAW TORTY: Telefonické objednávky (+421 910 824 923) sú dnes ZATVORENÉ. Zákazník si ich môže objednať až v najbližších otváracích hodinách (Pondelok 08:00 - 16:00).
            """
        elif day_en == 'Saturday':
            if 10 <= hour < 12:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Dnes je SOBOTA (10:00 - 12:00) – BIO OBCHOD JE AKTUÁLNE OTVORENÝ.
                - VARENIE / DENNÉ MENU / STÁLA PONUKA: Cez víkend sa NEVARÍ! Žiadne teplé jedlá sa nedajú objednať ani vyzdvihnúť.
                - RAW TORTY: TELEFONICKÉ OBJEDNÁVKY NA +421 910 824 923 SÚ TERAZ OTVORENÉ (do 12:00)! RAW torty sa vyrábajú čerstvé a mrazia sa, preto je potrebné objednať ich aspoň 24 hodín vopred.
                """
            else:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Dnes je SOBOTA – MIMO OTVÁRACÍCH HODÍN (ZATVORENÉ).
                - BIO OBCHOD: Otvorený bol/bude LEN od 10:00 do 12:00. Momentálne je zatvorený.
                - VARENIE / DENNÉ MENU: Nevarí sa.
                - RAW TORTY: Telefonické objednávky na +421 910 824 923 sú v tejto chvíli ZATVORENÉ. Zavolať a objednať tortu bude možné opäť v Pondelok od 08:00.
                """
        else: # PRACOVNÉ DNI (PONDELOK - PIATOK)
            if hour < 8:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň PRED OTVÁRACÍMI HODINAMI (pred 08:00). ZATVORENÉ.
                - Otvárame o 08:00. Telefonické objednávky na RAW torty na +421 910 824 923 aj donášku obeda spustíme o 08:00.
                """
            elif 8 <= hour < 10:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (08:00 - 10:00) – VŠETKO JE OTVORENÉ.
                - DONÁŠKA DENNÉHO MENU: Prijíma sa (LEN do 10:00).
                - RAW TORTY: Telefonické objednávky na +421 910 824 923 SÚ OTVORENÉ (objednať 24h vopred).
                """
            elif 10 <= hour < 16:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (10:00 - 16:00) – OTVORENÉ.
                - DONÁŠKA DENNÉHO MENU: ZATVORENÁ (bola do 10:00). Osobný odber obeda je možný do 16:00 po overení dostupnosti na +421 910 824 923.
                - RAW TORTY: Telefonické objednávky na +421 910 824 923 SÚ OTVORENÉ (objednať 24h vopred).
                """
            else:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň PO OTVÁRACÍCH HODINÁCH (po 16:00). ZATVORENÉ.
                - Bistro, obchod aj telefónne linky sú na dnes ZATVORENÉ. Telefonické objednávky na RAW torty (+421 910 824 923) aj obedy budú možné opäť zajtra od 08:00.
                """

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

PRAVIDLÁ SPRÁVANIA:
- NIKDY na silu netlač zákazníka, aby si čokoľvek objednal, ak sa na to priamo nepýta.
- Hovor iba priamo k veci ohľadom toho, čo sa zákazník pýta. Nepíš mu o iných veciach, ktoré si nevyžiadal.
- Vždy sa drž výhradne faktov uvedených v týchto systémových inštrukciách a v dodaných dátach z webu Vegnella.
- NIKDY si nevymýšľaj informácie ani nepoužívaj svoje všeobecné vedomosti mimo dodaných dát.
- Odpovedaj zákazníkovi výlučne na základe aktuálnych dát z webu Vegnella a podľa aktuálneho reálneho času a dňa v Bratislave, Slovensko.
- Odpovedaj na otázky výlučne ohľadom bistra Vegnella. Ak sa zákazník pýta na čokoľvek iné (mimo tematiky obchodu, bistra, ponuky či otváracích hodín), zdvorilo mu vysvetli, že odpovedáš len na informácie ohľadom bistra a bio obchodu Vegnella.

AKTUÁLNY REÁLNY ČAS: {current_time_str}

==================================================
PRÍSNE NARIADENIE STAVU PREVÁDZKY:
{STATUS_TEXT}
==================================================

PRAVIDLÁ ODPOVEDE:
1. AK SA ZÁKAZNÍK PÝTA NA RAW TORTY ALEBO SI CHCE JEDNU OBJEDNAŤ:
   - Ak sú otváracie hodiny OTVORENÉ: Potvrď, že môže zavolať na +421 910 824 923 a objednať si. Pripomeň, že RAW torty sa pripravujú čerstvé, zamrazujú sa a je potrebné ich objednať aspoň 24 hodín vopred.
   - Ak je ZATVORENÉ: Vysvetli, že telefonické objednávky prijímate len počas otváracích hodín a uveď, kedy najbližšie otvárate.
2. AK SA ZÁKAZNÍK PÝTA NA VARENÉ MENU / OBEDY CEZ VÍKEND:
   - Dôrazne vysvetli, že cez víkend sa nevarí a nové týždenné menu bude pripravené až na pondelok.
3. FORMÁTOVANIE:
   - ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text!
   - Pre odrážky používaj výhradne pomlčky (-).

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