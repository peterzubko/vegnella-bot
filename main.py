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

# Správa životného cyklu aplikácie (Lifespan)
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. Pri štarte servera stiahneme aktuálne dáta
    scrape_vegnella()
    
    # 2. Nastavíme plánovač na každý pracovný deň (Po-Pi) o 07:00 ráno
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(
        scrape_vegnella, 
        trigger='cron', 
        day_of_week='mon-fri', 
        hour=7, 
        minute=0
    )
    scheduler.start()
    
    yield  # Aplikácia beží...
    
    # 3. Pri vypnutí servera vypneme plánovač
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
        # Ak by bola pamäť z nejakého dôvodu prázdna, poistka:
        if not WEBSITE_DATA:
            scrape_vegnella()

        # Získanie presného dátumu a času na Slovensku
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        current_time_str = now.strftime("%A, %d.%m.%Y, %H:%M hodín")
        
        dni_sk = {
            'Monday': 'Pondelok', 'Tuesday': 'Utorok', 'Wednesday': 'Streda',
            'Thursday': 'Štvrtok', 'Friday': 'Piatok', 'Saturday': 'Sobota', 'Sunday': 'Nedeľa'
        }
        for en, sk in dni_sk.items():
            current_time_str = current_time_str.replace(en, sk)

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro Vegnella.

AKTUÁLNY REÁLNY ČAS A DÁTUM (Slovensko):
{current_time_str}

PRAVIDLÁ PRE DONÁŠKU A ODBER (Pondelok – Piatok):
- Prijímanie objednávok na DONÁŠKU prebieha LEN do 10:00 hod.
- OSOBNÝ ODBER jedla je možný do 16:00 hod.
- Po 16:00 hod. je bistro pre daný deň ZATVORENÉ!

DÔLEŽITÉ INŠTRUKCIE K VÍKENDOM A ČASU:
- Ak je SOBOTA alebo NEDEĽA a zákazník sa pýta na menu, obedy alebo chce objednať:
  HNEĎ na začiatku ho upozorni, že cez víkend nevaríte (v sobotu je otvorený iba bio obchod a v nedeľu je zatvorené).
  Ak na webe nájdeš ponuku, môžeš mu ju ukázať ako ukážku/stálu ponuku, ale ZDÔRAZNI, že objednávku je možné spraviť až na najbližší pracovný deň (pondelok).

- Ak je PRACOVNÝ DEŇ a aktuálny čas je PO 16:00 hod:
  Oznám, že máte zatvorené a ponúkni predobjednávku na zajtra.

- Ak je PRACOVNÝ DEŇ MEDZI 10:00 a 16:00 hod:
  Dnešná donáška už nie je možná (bola do 10:00), ale je možný osobný odber do 16:00.

PRAVIDLÁ A INŠTRUKCIE PRE ODPOVEĎ:
1. Odpovedaj priamo, bez zbytočných omáčok.
2. NIKDY nepoužívaj Markdown formátovanie (nepoužívaj hviezdičky ** ani # pre nadpisy), píš čisto obyčajný text.
3. Pri zoznamoch jedál použi obyčajné pomlčky (-).
4. Odpovedaj VÝHRADNE na základe textu nižšie:

AKTUÁLNE TEXTOVÉ DÁTA ZO VŠETKÝCH PODSTRÁNOK VEGNELLA.SK:
---
{WEBSITE_DATA}
---

PRAVIDLÁ A INŠTRUKCIE PRE ODPOVEĎ:
1. Ak sa zákazník pýta "aké je menu", "čo máte na obed", "aké sú jedlá" a pod., HNEĎ VYPIŠ konkrétne názvy polievok, hlavných jedál alebo ponuky pre dnešný deň!
2. NIKDY neodpovedaj len všeobecnými omáčkami typu "máme čerstvé a zdravé jedlá". Daj zákazníkovi PRIAMO zoznam jedál z textu!
3. Odpovedaj VÝHRADNE na základe textu vyššie. Ak konkrétne informácie v texte chýbajú, zdvorilo to priznaj a nehalucinuj.
4. Pri bežných pozdravoch alebo odpovediach typu "ok", "vďaka" odpovedaj krátko a zdvorilo.
5. Odpovedaj stále priamo a stručne, bez zbytočných omáčok. Ak je otázka zložitá, rozdeľ odpoveď do odsekov.
"""

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation
        )
        reply = response.choices[0].message.content
        return {"odpoved": reply}
    except Exception as e:
        return {"odpoved": f"Chyba na serveri: {str(e)}"}