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

# --- 4. TAJNÉ VOLANIE: ZISTENIE HESLA (MENU / INE) ---
def zisti_tajne_heslo(sprava_zakaznika: str) -> str:
    prompt = f"""
    Zatrieď správu zákazníka do JEDNÉHO z dvoch hestiel:

    - MENU (ak sa pýta na obedové menu, dennú ponuku, obed, polievky, čo je navarené)
    - INE  (ak sa pýta na cokoľvek iné, zdraví, alebo má otázku mimo obedového menu)

    Vráť IBA JEDNO SLOVO (heslo) v plnom znení a NIČ INÉ!
    Správa zákazníka: "{sprava_zakaznika}"
    """
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        return response.choices[0].message.content.strip().upper()
    except Exception:
        return "MENU"

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

        posledna_sprava = req.messages[-1]["content"] if req.messages else ""

        # Aktuálny reálny čas v SR
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)

        # KROK A: Tajné zistenie hesla cez AI
        heslo = zisti_tajne_heslo(posledna_sprava)

        # KROK B: Python logika pre vetvu INE
        if heslo == "INE":
            return {
                "odpoved": "Dobrý deň! Som AI asistent pre Vegnellu. Momentálne vám viem poskytnúť informácie výhradne o našom obedovom menu. Ako vám môžem pomôcť s dnešným obedom?"
            }

        # KROK C: Python logika pre vetvu MENU (Mantinely pre AI)
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