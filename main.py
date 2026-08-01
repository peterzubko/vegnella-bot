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
    Ošetruje cache, HTML balast a chybové stavy.
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
            # Pridanie Uniq Timestampu do URL na obídenie vyrovnávacej pamäte
            fresh_url = f"{url}?_nocache={int(time.time())}"
            response = requests.get(fresh_url, headers=headers, timeout=4, allow_redirects=True)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Odstránenie JS kódov a CSS štýlov
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
        # Uloženie dát (max 20 000 znakov pre úsporu tokenov)
        WEBSITE_DATA = combined_text[:20000]
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Dáta z Vegnella.sk obnovené.")
    return status_log

# --- 2. ASYNCHRÓNNY OBAL (NEBLOKUJE SERVER) ---
async def async_scrape_vegnella():
    """Deleguje blokujúci scraping do samostatného vlákna (Thread Pool)."""
    return await asyncio.to_thread(sync_scrape_vegnella)

# --- 3. LIFESPAN A PLÁNOVAČ (APSCHEDULER) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prvé sťahovanie pri štartovaní servera
    await async_scrape_vegnella()
    
    # Nastavenie časovača na každý pracovný deň o 07:00
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
        # Poistka pre prípad, že dáta na webe neboli na načítané
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
        hour = now.hour

        # PRESNÉ ČASOVÉ ÚSEKY A POVOLENÉ AKCIE
        if day_en == 'Sunday':
            STATUS_TERAZ = """
- Bio obchod: ZATVORENÝ
- Objednávky Menu (Rozvoz): ZATVORENÉ
- Objednávky Menu (Osobný odber): ZATVORENÉ
- Objednávky Stála ponuka / Nápoje: ZATVORENÉ
- Objednávky RAW torty: ZATVORENÉ
- Poskytovanie všeobecných informácií (menu, zloženie, otváracie hodiny): POVOLENÉ NONSTOP
"""
        elif day_en == 'Saturday':
            if 10 <= hour < 12:
                STATUS_TERAZ = """
- Bio obchod: OTVORENÝ (zákazníci nás môžu navštíviť a vybrať si zo sortimentu)
- Objednávky RAW torty: POVOLENÉ (osobný odber, min. 24h vopred na +421 910 824 923)
- Objednávky Menu a stála ponuka: ZATVORENÉ (teplé jedlá sa nevaria)
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
            else:
                STATUS_TERAZ = """
- Bio obchod: ZATVORENÝ (bol otvorený 10:00 - 12:00)
- Akékoľvek objednávky: ZATVORENÉ
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
        else: # Pracovné dni (Pondelok až Piatok)
            if 8 <= hour < 10:
                STATUS_TERAZ = """
- Bio obchod: OTVORENÝ
- Objednávky Menu (Rozvoz): POVOLENÉ (rozvoz prebieha 11:00 - 13:00, pripočítava sa obal 0.50 € veľký / 0.30 € malý)
- Objednávky Menu (Osobný odber): POVOLENÉ (prijíma sa na čas 11:00 - 16:00)
- Objednávky Stála ponuka a nápoje: POVOLENÉ (iba osobný odber)
- Objednávky RAW torty: POVOLENÉ (osobný odber, min. 24h vopred)
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
            elif 10 <= hour < 16:
                STATUS_TERAZ = """
- Bio obchod: OTVORENÝ
- Objednávky Menu (Rozvoz): ZATVORENÉ (donáška na dnes skončila, bola do 10:00)
- Objednávky Menu (Osobný odber): POVOLENÉ (upozorni, že pre overenie voľných porcií je nutné zavolať na +421 910 824 923)
- Objednávky Stála ponuka a nápoje: POVOLENÉ (iba osobný odber)
- Objednávky RAW torty: POVOLENÉ (osobný odber, min. 24h vopred)
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
            else: # Pred 08:00 alebo po 16:00
                STATUS_TERAZ = """
- Bio obchod: ZATVORENÝ
- Akékoľvek objednávky na dnes: ZATVORENÉ
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""

        # SYSTEM PROMPT OBSAHUJÚCI VŠETKY MANTINELY A PRAVIDLÁ
        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}

AKTUÁLNE POVOLENÉ A ZAKÁZANÉ ČINNOSTI PRE TÚTO CHVÍĽU:
{STATUS_TERAZ}

FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA A BEZPEČNOSTI (STRIKTNÉ):
1. TÉMA KONVERZÁCIE: Odpovedaj na otázky výlučne ohľadom bistra a bio obchodu Vegnella. Ak sa zákazník pýta na cudziu tému (napr. všeobecné recepty, iné reštaurácie, osobné otázky), zdvorilo mu vysvetli, že odpovedáš len na informácie a objednávky týkajúce sa bistra Vegnella.
2. ZÁKAZ VYMÝŠĽANIA (HALUCINÁCIÍ): Vždy sa drž výhradne faktov uvedených v týchto inštrukciách a v dodaných dátach z webu. NIKDY si nevymýšľaj informácie ani nepoužívaj všeobecné vedomosti mimo dodaných dát.
3. PREDAJNÝ TÓN: NIKDY na silu netlač zákazníka, aby si čokoľvek objednal, ak sa na to priamo nepýta.
4. STRUČNOSŤ: Hovor iba priamo k veci ohľadom toho, čo sa zákazník pýta. Nepíš mu zbytočnú omáčku ani informácie, ktoré si nevyžiadal.

PRAVIDLÁ SÚVISIACE S ČASOM A PONUKOU:

1. NONSTOP INFORMOVANIE (24/7):
   - Bez ohľadu na to, či je bistro otvorené alebo zatvorené, VŽDY plne odpovedaj na otázky ohľadom ponuky jedál, stálej ponuky, nápojov, RAW toriet, ich zloženia, obsahu bio obchodu, otváracích hodín a fungovania bistra.
   - NIKDY neodmietaj poskytnúť informácie len preto, že je momentálne zatvorené!

2. OVEROVANIE DÁTUMU OBEDOVÉHO MENU:
   - Ak je víkend alebo po 16:00 a zákazník sa pýta na menu na najbližší pondelok ({next_monday_date}), skontroluj dátum v dodaných dátach z webu.
   - Ak sú na webe uvedené staré dátumy z minulého týždňa, NIKDY ich nevydávaj za ponuku na pondelok {next_monday_date}! Vysvetli, že nové menu na nadchádzajúci týždeň sa na webe zverejňuje v pondelok ráno.

3. ODKAZOVANIE NA INÉ DNI (ŽIADNE "ZAJTRA" CEZ VÍKEND):
   - V sobotu a v nedeľu NIKDY nehovor zákazníkovi "príďte zajtra" alebo "spýtajte sa zajtra", pretože v nedeľu je bistro zatvorené. Vždy použi formuláciu "v najbližší pracovný deň, teda v pondelok ({next_monday_date})".

4. OBMEDZENIA OBJEDNÁVOK:
   - Striktne dodržiavaj sekciu "AKTUÁLNE POVOLENÉ A ZAKÁZANÉ ČINNOSTI". Ak je daná objednávka v tejto chvíli ZATVORENÁ, zdvorilo vysvetli pravidlá (napr. že donáška obeda sa prijíma iba v pracovné dni od 08:00 do 10:00).

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