import os
import time
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
                
                # Záchrana formátu: Riadky oddeľujeme novým riadkom '\n'
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

    WEBSITE_DATA = combined_text[:20000]
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
        "nahlad": WEBSITE_DATA[:1000]
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        if not WEBSITE_DATA:
            scrape_vegnella()

        # --- LOGIKA REÁLNEHO ČASU A KALENDÁRA ---
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
            days_ahead = 7  # Ak je pondelok po 16:00, najbližší pondelok je ten o týždeň
        elif day_en in ['Saturday', 'Sunday']:
            days_ahead = (7 - now.weekday()) % 7  # Cez víkend hľadáme nasledujúci pondelok
            
        next_monday_date = (now + timedelta(days=days_ahead)).strftime("%d.%m.%Y")

        hour = now.hour

        # PREVÁDZKOVÝ STAV
        if day_en == 'Sunday':
            STATUS_TERAZ = "Dnes je NEDEĽA - bistro aj obchod sú CELÝ DEŇ ZATVORENÉ. Nevarí sa."
        elif day_en == 'Saturday':
            if 10 <= hour < 12:
                STATUS_TERAZ = "Dnes je SOBOTA (10:00 - 12:00) - Bio obchod je OTVORENÝ. Bistro nevarí."
            else:
                STATUS_TERAZ = "Dnes je SOBOTA - ZATVORENÉ. Bistro nevarí."
        else:
            if hour < 8:
                STATUS_TERAZ = "Je pracovný deň pred 08:00 (ZATVORENÉ). Otvárame o 08:00."
            elif 8 <= hour < 10:
                STATUS_TERAZ = "Je pracovný deň (08:00 - 10:00) - OTVORENÉ. Donáška obedov sa prijíma."
            elif 10 <= hour < 16:
                STATUS_TERAZ = "Je pracovný deň (10:00 - 16:00) - OTVORENÉ. Donáška na dnes skončila (bola do 10:00), možný osobný odber."
            else:
                STATUS_TERAZ = "Je po 16:00 - ZATVORENÉ."

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}
AKTUÁLNY PREVÁDZKOVÝ STAV: {STATUS_TERAZ}

PRAVIDLÁ SPRÁVANIA:
- Hovor priamo k veci, stručne a priateľsky.
- Odpovedaj výhradne na otázky ohľadom bistra a bio obchodu Vegnella.
- FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

KONTROLA AKTUÁLNOSTI OBEDOVÉHO MENU (KĽÚČOVÉ):
1. STÁLA PONUKA:
   - Stála ponuka (stále jedlá, burger, burrito, šaláty atď.) z podstránky ponuka.html platí VŽDY a môžeš ju zákazníkovi vymenovať kedykoľvek.
2. DENNÉ/TÝŽDENNÉ MENU A PONDELOK:
   - V dátach z webu nižšie skontroluj, či sa tam nachádza týždenné menu pre AKTUÁLNY týždeň alebo nadchádzajúci týždeň s dátumom {next_monday_date}.
   - Ak je víkend (sobota/nedeľa) a text na webe obsahuje STARÉ dátumy z minulého týždňa, NIKDY ich nezamieňaj za ponuku na najbližší pondelok ({next_monday_date})!
   - Ak menu pre nový týždeň s dátumom {next_monday_date} ešte nie je na webe zverejnené, zákazníkovi vysvetli, že týždenné menu na nový týždeň sa zverejňuje pred/počas pondelka, ale vymenuj mu STÁLU PONUKU, ktorú si môže dať vždy.

DÁTA Z WEBU VEGNELLA:
--------------------------------------------------
{WEBSITE_DATA}
--------------------------------------------------
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