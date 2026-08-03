import os
import time
import asyncio
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

# Globálna premenná pre stiahnuté obedové menu z webu
DAILY_MENU_DATA = ""

# --- 1. SCRAPING OBEDOVÉHO MENU Z WEBU ---
def sync_scrape_menu_only():
    global DAILY_MENU_DATA
    url = "https://www.vegnella.sk/obedy.html"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Cache-Control': 'no-cache, no-store, must-revalidate',
        'Pragma': 'no-cache',
        'Expires': '0'
    }
    try:
        fresh_url = f"{url}?_nocache={int(time.time())}"
        response = requests.get(fresh_url, headers=headers, timeout=5)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            
            text = soup.get_text(separator='\n', strip=True)
            if len(text) > 50:
                DAILY_MENU_DATA = text[:4000]
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Obedové menu úspešne obnovené z webu.")
                return ["OK: Menu obnovené"]
    except Exception as e:
        print(f"[CHYBA] Scraping zlyhal: {str(e)}")
    
    return ["ZLYHALO: Menu sa nepodarilo obnoviť"]

async def async_scrape_menu():
    return await asyncio.to_thread(sync_scrape_menu_only)

# --- 2. ČASOVAČ (LIFESPAN): SPUSTENIE O 7:00 RÁNO ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pri štarte aplikácie hneď stiahne menu
    await async_scrape_menu()
    
    # Nastavenie plánovača na 07:00 ráno v pracovné dni
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(sync_scrape_menu_only, trigger='cron', day_of_week='mon-fri', hour=7, minute=0)
    scheduler.start()
    
    yield
    scheduler.shutdown()

# --- 3. FASTAPI A CORS (BEZPEČNOSŤ) ---
app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://www.vegnella.sk", "https://vegnella.sk"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

class ChatRequest(BaseModel):
    messages: list

# --- 4. TAJNÉ VOLANIE: ZISTENIE HESLA S KONTEXTOM (MENU / OBJEDNAVKA / INE) ---
def zisti_tajne_heslo(messages_history: list) -> str:
    """
    Analyzuje posledné správy z chatu, aby tajná AI poznala kontext
    a správne zaradila aj nadväzujúce skrátené otázky.
    """
    # Vyberieme posledných max 6 správ (3 otázky + 3 odpovede)
    recent_messages = messages_history[-6:]
    
    konverzacia_text = ""
    for msg in recent_messages:
        rola = "Zákazník" if msg.get("role") == "user" else "Bot"
        konverzacia_text += f"{rola}: {msg.get('content', '')}\n"

    prompt = f"""
    Zatrieď CELKOVÝ ZÁMER ZÁKAZNÍKA na základe konverzácie do JEDNÉHO z nasledujúcich hestiel:

    - MENU        (ak sa rieši obedové menu, ponuka jedál na obed, polievky, čo je navarené)
    - OBJEDNAVKA  (ak sa rieši objednávka, rezervácia, donáška, čas doručenia alebo otázky či si môže objednať dnes/zajtra)
    - INE         (ak ide o správu mimo obedového menu alebo bez nadväznosti)

    Vráť IBA JEDNO SLOVO (heslo) v plnom znení a NIČ INÉ!

    HISTÓRIA KONVERZÁCIE:
    {konverzacia_text}
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content.strip().upper()
    except Exception as e:
        print(f"[CHYBA KLASIFIKÁCIE]: {str(e)}")
        return "INE"

# --- 5. ENDPOINTY ---
@app.get("/")
def home():
    return {"status": "Vegnella Menu Bot (Core) running"}

@app.get("/api/refresh")
async def refresh_data():
    log = await async_scrape_menu()
    return {"status": "Obedové menu obnovené", "log": log}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        # Ak menu ešte nie je stiahnuté, stiahne ho
        if not DAILY_MENU_DATA:
            await async_scrape_menu()

        # Aktuálny reálny čas v SR
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)

        # KROK A: Tajné zistenie hesla cez AI s celým kontextom
        heslo = zisti_tajne_heslo(req.messages)

        # KROK B: Rozdelenie mantinelov podľa zisteného hesla

        # 1. VETVA: MENU
        if heslo == "MENU":
            system_prompt = f"""
            Si oficiálny, priateľský asistent pre bistro Vegnella.
            AKTUÁLNY REÁLNY ČAS: {now.strftime('%A, %d.%m.%Y %H:%M hodín')}

            RÁMEC PÔSOBNOSTI:
            Odpovedaj VÝHRADNE na otázky týkajúce sa obedového menu na základe týchto presných dát z webu:
            --------------------------------------------------
            {DAILY_MENU_DATA}
            --------------------------------------------------

            STRIKTNÉ PRAVIDLÁ:
            1. Odpovedaj milo a vecne. ZÁKAZ Markdown hviezdičiek (**text**). Pre odrážky používaj výhradne pomlčky (-).
            2. Drž sa striktne textu obedového menu uvedeného vyššie. Nevymýšľaj si žiadne jedlá.
            3. Ak sa zákazník pýta na niečo mimo obedového menu, slušne vysvetli, že odpovedáš len na otázky k obedovému menu.
            """

        # 2. VETVA: OBJEDNAVKA
        elif heslo == "OBJEDNAVKA":
            system_prompt = f"""
            Si oficiálny, priateľský asistent pre bistro Vegnella.
            AKTUÁLNY REÁLNY ČAS: {now.strftime('%A, %d.%m.%Y %H:%M hodín')}

            RÁMEC PÔSOBNOSTI:
            Odpovedaj VÝHRADNE na otázky týkajúce sa objednávok, rezervácií a donášky obedového menu.

            ZÁKLADNÉ PRAVIDLÁ PRE OBJEDNÁVKY:
            - Donášku obedového menu prijímame v pracovné dni ráno od 8:00 do 10:00.
            - Rozvoz menu prebieha v čase 11:00 - 13:00.
            - Osobný odber menu je možný v čase 11:00 - 16:00 (rezervácia na 0951 747 893).
            - Cez víkend donášku neaplikujeme a bistro je zavreté.

            STRIKTNÉ PRAVIDLÁ:
            1. Odpovedaj milo a vecne. ZÁKAZ Markdown hviezdičiek (**text**). Pre odrážky používaj výhradne pomlčky (-).
            2. Sústreď sa na vysvetlenie podmienok objednávky.
            """

        # 3. VETVA: INE (Všetko ostatné)
        else:
            return {
                "odpoved": "Dobrý deň! Som AI asistent pre Vegnellu. Momentálne vám viem poskytnúť informácie výhradne o našom obedovom menu a objednávkach. Ako vám môžem pomôcť?"
            }

        # KROK C: Finálne zavolanie AI pre vybranú vetvu (MENU alebo OBJEDNAVKA)
        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation,
            temperature=0.2
        )

        reply = response.choices[0].message.content or ""
        clean_reply = reply.replace("**", "")

        return {"odpoved": clean_reply}

    except Exception as e:
        print(f"[ERROR]: {str(e)}")
        return {"odpoved": "Ospravedlňujem sa, momentálne pripojenie trvá dlhšie ako zvyčajne. Skúste prosím otázku zopakovať."}