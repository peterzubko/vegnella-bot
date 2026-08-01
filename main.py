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

WEBSITE_DATA = ""

# --- SYNCHRÓNNA FUNKCIA NA SCRAPING (Spúšťaná vo vlastnom vlákne) ---
def sync_scrape_vegnella():
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
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Dáta z Vegnella.sk obnovené.")
    return status_log

# ASYNCHRÓNNY OBAL (Neblokuje event loop FastAPI servera)
async def async_scrape_vegnella():
    return await asyncio.to_thread(sync_scrape_vegnella)

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

        # --- LOGIKA REÁLNEHO ČASU A KALENDÁRA (BRATISLAVA) ---
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
        hour = now.hour

        # AKTUÁLNY STAV PREVÁDZKY
        if day_en == 'Sunday':
            STATUS_TERAZ = "Dnes je NEDEĽA - CELÝ DEŇ ZATVORENÉ. Nevarí sa a neprijímajú sa žiadne objednávky."
        elif day_en == 'Saturday':
            if 10 <= hour < 12:
                STATUS_TERAZ = "Dnes je SOBOTA (10:00 - 12:00) - Bio obchod je OTVORENÝ. Prijímajú sa aj objednávky na RAW torty (min. 24h vopred). Teplé jedlá sa nevaria."
            else:
                STATUS_TERAZ = "Dnes je SOBOTA - ZATVORENÉ. Bio obchod bol otvorený 10:00 - 12:00. Teplé jedlá sa nevaria."
        else: # PRACOVNÉ DNI
            if hour < 8:
                STATUS_TERAZ = "Je pracovný deň pred 08:00 (ZATVORENÉ). Otvárame o 08:00."
            elif 8 <= hour < 10:
                STATUS_TERAZ = "Je pracovný deň (08:00 - 10:00) - OTVORENÉ. Prijíma sa donáška aj osobný odber obeda, stála ponuka, RAW torty aj Bio obchod."
            elif 10 <= hour < 16:
                STATUS_TERAZ = "Je pracovný deň (10:00 - 16:00) - OTVORENÉ. Donáška obeda na dnes skončila (bola do 10:00). Možný je osobný odber obeda po overení dostupnosti, stála ponuka na osobný odber, RAW torty a Bio obchod."
            else:
                STATUS_TERAZ = "Je po 16:00 - ZATVORENÉ."

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}
AKTUÁLNY PREVÁDZKOVÝ STAV: {STATUS_TERAZ}

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA:
- NIKDY na silu netlač zákazníka, aby si čokoľvek objednal, ak sa na to priamo nepýta.
- Hovor iba priamo k veci ohľadom toho, čo sa zákazník pýta. Nepíš mu o iných veciach, ktoré si nevyžiadal.
- Vždy sa drž výhradne faktov uvedených v týchto systémových inštrukciách a v dodaných dátach z webu Vegnella.
- NIKDY si nevymýšľaj informácie ani nepoužívaj svoje všeobecné vedomosti mimo dodaných dát.
- Odpovedaj na otázky výlučne ohľadom bistra a bio obchodu Vegnella. Ak sa zákazník pýta na cudziu tému, zdvorilo mu vysvetli, že sa môže pýtať len na informácie ohľadom bistra a bio obchodu Vegnella.
- FORMÁTOVANIE: ZÁKAZ Markdown hviezdičKA (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

Pravidlá odpovedí sú rozdelené do 5 kategórií:

1. KATEGÓRIA: DENNÉ / OBEDOVÉ MENU
- INFORMÁCIE: Poskytuj kedykoľvek z webu. POZOR: Ak je víkend/po 16:00 a na webe sú uvedené staré dátumy z minulého týždňa, NIKDY ich nezamieňaj za ponuku na najbližší pondelok ({next_monday_date})! Ak nové menu na pondelok {next_monday_date} na webe ešte nie je zverejnené, vysvetli, že nové týždenné menu sa zverejňuje pred/počas pondelka ranných hodín.
- OBJEDNANIE NA OSOBNÝ ODBER: Prijíma sa v pracovné dni od 08:00 do 16:00. Upozorni zákazníka, že pri osobnom odbere je potrebné si dostupnosť porcií overiť telefonicky na +421 910 824 923.
- OBJEDNANIE NA DOVOZ (DONÁŠKA): Prijíma sa IBA v pracovné dni od 08:00 do 10:00.
- PRAVIDLÁ DOVOZU: Vždy oznám, že rozvoz prebieha medzi 11:00 a 13:00. K cene menu sa pripočítava obal: 0.50 € veľký obal na hlavné jedlo a 0.30 € malý obal na polievku.

2. KATEGÓRIA: STÁLA PONUKA A NÁPOJE
- INFORMÁCIE: Poskytuj kedykoľvek z webu (ponuka.html).
- OBJEDNANIE: Stálu ponuku a nápoje je možné objednať IBA OSOBNE (osobný odber) a IBA v pracovné dni od 08:00 do 16:00.
- V sobotu ani v nedeľu sa stála ponuka a nápoje NEDAJÚ objednať.

3. KATEGÓRIA: RAW TORTY
- INFORMÁCIE: Poskytuj kedykoľvek z webu (raw-torty.html).
- OBJEDNANIE: Môžu sa objednať kedykoľvek počas otváracích hodín (Pracovné dni 08:00-16:00, Sobota 10:00-12:00) telefonicky na +421 910 824 923 alebo osobne.
- PRAVIDLÁ: Výhradne OSOBNÝ ODBER. Objednávka musí byť zadaná minimálne 24 HODÍN VOPRED, pretože RAW torty sa vyrábajú čerstvé a musia sa zamraziť.

4. KATEGÓRIA: BIO OBCHOD
- Nákup na predajni je možný počas všetkých otváracích hodín (Pracovné dni 08:00 - 16:00, Sobota 10:00 - 12:00).

5. KATEGÓRIA: VŠEOBECNÉ INFORMÁCIE A OTVÁRACIE HODINY
- Informácie o otváracích hodinách, kontakte a fungovaní bistra poskytuj kedykoľvek.
- Otváracie hodiny: Pracovné dni 08:00 - 16:00, Sobota 10:00 - 12:00 (Bio obchod a objednávky RAW toriet), Nedeľa CELÝ DEŇ ZATVORENÉ.

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
        
        reply = response.choices[0].message.content
        clean_reply = reply.replace("**", "")
        
        return {"odpoved": clean_reply}
        
    except Exception as e:
        print(f"[ERROR] Chyba pri spracovaní chatu: {str(e)}")
        return {"odpoved": "Ospravedlňujem sa, momentálne pripojenie trvá dlhšie ako zvyčajne. Skúste prosím otázku zopakovať."}