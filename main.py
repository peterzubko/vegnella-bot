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

        # --- EXACT TIME & DAY LOGIC (PYTHON) ---
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

        # 1. NEDEĽA - CELÝ DEŇ ZATVORENÉ
        if day_en == 'Sunday':
            STATUS_TEXT = """
            STAV PREVÁDZKY: Dnes je NEDEĽA – bistro aj bio obchod sú ÚPLNE ZATVORENÉ!
            - Nevarí sa denné menu ani stála ponuka jedál. Donáška ani osobný odber NIE SÚ MOŽNÉ.
            - Zákazníkovi oznám, že najbližšie otvárate v Pondelok o 08:00 a vtedy bude pripravené aj nové denné menu.
            - Ak sa pýta na ponuku, môžeš mu z textu ukázať sortiment alebo RAW torty, ale s dôrazom, že dnes je zatvorené.
            """
        # 2. SOBOTA
        elif day_en == 'Saturday':
            if 10 <= hour < 12:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Dnes je SOBOTA, otvorený je LEN BIO OBCHOD (10:00 - 12:00).
                - VŠETKO VARENIE JE ZASTAVENÉ! Nevarí sa denné menu ani stála ponuka jedál. Donáška ani odber jedál NIE SÚ MOŽNÉ.
                - Zákazníkom oznamuj, že denné menu bude pripravené až v PONDELOK.
                - V obchode je možné nakúpiť bio tovar a taktiež si vyzdvihnúť alebo OBJEDNAŤ RAW TORTY dopredu (po dohode na t.č. +421 910 824 923).
                """
            else:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Dnes je SOBOTA, ale mimo otváracích hodín obchodu (obchod bol otvorený len 10:00 - 12:00). Aktuálne je ZATVORENÉ.
                - Nevarí sa, denné menu pripravujeme až na Pondelok.
                """
        # 3. PRACOVNÉ DNI (PON - PIA)
        else:
            if hour < 8:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň, pred otváracími hodinami (otvárame o 08:00).
                - Otvorené je od 08:00 do 16:00.
                - Objednávky na DONÁŠKU spúšťame o 08:00 (do 10:00).
                - Osobný odber bude možný od 08:00 do 16:00.
                """
            elif 8 <= hour < 10:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (08:00 - 10:00 RÁNO).
                - VŠETKO JE OTVORENÉ A DOSTUPNÉ!
                - DONÁŠKA denného menu JE MOŽNÁ (objednávky len od 8:00 do 10:00).
                - OSOBNÝ ODBER denného menu je možný počas celého dňa až do 16:00.
                """
            elif 10 <= hour < 16:
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je pracovný deň (10:00 - 16:00).
                - DONÁŠKA UŽ NIE JE MOŽNÁ (bola len do 10:00 ráno).
                - OSOBNÝ ODBER DENNÉHO MENU JE MOŽNÝ do 16:00, ale zákazník si musí na t.č. +421 910 824 923 overiť, či je ešte voľná porcia!
                - Obchod a stála ponuka v bistre sú dostupné.
                """
            else: # po 16:00
                STATUS_TEXT = """
                STAV PREVÁDZKY: Je po 16:00 hodín. ZATVORENÉ!
                - Donáška ani osobný odber na dnes už nie sú možné. Otvárame opäť zajtra o 08:00.
                """

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS: {current_time_str}

==================================================
PRÍSNE NARIADENIE STAVU PREVÁDZKY:
{STATUS_TEXT}
==================================================

PRAVIDLÁ A PRÍSNE INŠTRUKCIE:
1. VŽDY sa riaď sekciou STAV PREVÁDZKY vyššie!
2. AK JE SOBOTA ALEBO NEDEĽA A ZÁKAZNÍK SA PÝTA NA MENU:
   - Zdvorilo oznam, že cez víkend nevaríte (v sobotu je otvorený len bio obchod 10:00-12:00, v nedeľu je zatvorené).
   - Ak sa zákazník pýta na menu na PONDELOK: Upozorni ho, že nové týždenné menu ešte len pripravujete a na webe bude zverejnené neskôr! NIKDY neprezentuj staré jedlá z minulého týždňa ako garantované menu na nový pondelok.
   - Ak zákazník napriek tomu chce vidieť ponuku, môžeš mu ukázať stálu ponuku alebo RAW torty zo stránky (s možnosťou objednávky na t.č. +421 910 824 923).
3. DONÁŠKA denného menu je možná LEN v pracovné dni od 08:00 do 10:00 ráno. Mimo tohto času donášku ODMIETNI!
4. OSOBNÝ ODBER denného menu po 10:00 cez týždeň: Oznám, že odber je možný do 16:00, ale odporuč zavolať na +421 910 824 923 pre overenie voľných porcií.
5. PÍŠ ČISTÝ TEXT! NIKDY nepoužívaj Markdown hviezdičky (ZÁKAZ ako **text**) ani mriežky (#). Pre odrážky používaj výhradne pomlčky (-).
6. Odpovedaj výhradne na základe dát nižšie:

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