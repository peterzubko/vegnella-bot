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
    await async_scrape_menu()
    
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

# --- 4. TAJNÉ VOLANIE: ZISTENIE HESLA S KONTEXTOM ---
def zisti_tajne_heslo(messages_history: list) -> str:
    recent_messages = messages_history[-6:]
    
    konverzacia_text = ""
    for msg in recent_messages:
        rola = "Zákazník" if msg.get("role") == "user" else "Bot"
        konverzacia_text += f"{rola}: {msg.get('content', '')}\n"

    prompt = f"""
    Zatrieď CELKOVÝ ZÁMER ZÁKAZNÍKA na základe konverzácie do JEDNÉHO z nasledujúcich hestiel:

    - MENU        (ak sa rieši obedové menu, ponuka jedál na obed, polievky, čo je navarené)
    - OBJEDNAVKA  (ak sa rieši objednávka, rezervácia, donáška, čas doručenia alebo otázky či si môže objednať dnes/zajtra)
    - INFO        (ak sa rieši informácia o vegnella, otváracie hodiny, kontakt, adresa)
    - INE         (ak ide o správu mimo bistra a bio obchodu vegnella, alebo sa nedá jednoznačne určiť)

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
        if not DAILY_MENU_DATA:
            await async_scrape_menu()

        # Jednorazové zistenie aktuálneho času na začiatku
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        cas_str = now.strftime('%A, %d.%m.%Y %H:%M hodín')

        # -----------------------------------------------------------------
        # VŠEOBECNÉ PRAVIDLÁ PRE VŠETKY VETVY (Základný rámec)
        # -----------------------------------------------------------------
        base_prompt = f"""
        Si oficiálny, priateľský a profesionálny AI asistent pre bistro Vegnella.
        AKTUÁLNY REÁLNY ČAS V BISTRE: {cas_str}

        VŠEOBECNÉ FORMÁTOVACIE A SPRÁVANIA PRAVIDLÁ:
        1. Odpovedaj slušne, prirodzene a stručne.
        2. PRÍSNY ZÁKAZ používania Markdown hviezdičiek (**text**). Píš čistý text!
        3. Pre odrážky používaj výhradne pomlčky (-).
        4. Pri odpovediach sa riaď len informáciami priloženými nižšie. Nevymýšľaj si vlastné jedlá ani fakty.
        """

        # -----------------------------------------------------------------
        # TAJNÁ KLASIFIKÁCIA HESLA
        # -----------------------------------------------------------------
        heslo = zisti_tajne_heslo(req.messages)

        # -----------------------------------------------------------------
        # PYTHON LOGIKA A PRIRADENIE ŠPECIFICKÝCH DÁT
        # -----------------------------------------------------------------
        
        # VETVA 1: MENU
        if heslo == "MENU":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: OBEDOVÉ MENU
            Odpovedaj VÝHRADNE na otázky týkajúce sa obedového menu podľa týchto dát z webu:
            --------------------------------------------------
            {DAILY_MENU_DATA}
            --------------------------------------------------
            Ak sa zákazník pýta na iné témy, povedz mu, že sa sústredíš na obedové menu.
            """

        # OBJEDNAVKA
        elif heslo == "OBJEDNAVKA":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: OBJEDNÁVKY A DONÁŠKA
            Odpovedaj VÝHRADNE ohľadom objednávok a donášky obedového menu.

            PRAVIDLÁ OBJEDNÁVOK:
            - Donášku obedového menu prijímame v pracovné dni ráno od 8:00 do 10:00.
            - Rozvoz menu prebieha v čase 11:00 - 13:00.
            - Osobný odber menu je možný v čase 11:00 - 16:00 (rezervácia na 0951 747 893).
            - Cez víkend donášku neaplikujeme a bistro je zavreté.
            """

        # INE
        else:
            specific_prompt = f"""
            Zákazník sa pýta na niečo s čím mu nevieš pomôcť.
            Milo vysvetli zákazníkovi, že s tým mu nevieš pomôcť, čí nechce niečo iné.
            """ 

        # -----------------------------------------------------------------
        # FINÁLNE SPOJENIE BASE_PROMPT + SPECIFIC_PROMPT
        # -----------------------------------------------------------------
        full_system_prompt = base_prompt + "\n" + specific_prompt
        
        full_conversation = [{"role": "system", "content": full_system_prompt}] + req.messages

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