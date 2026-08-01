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
    Ošetruje vyrovnávaciu pamäť (cache), HTML balast a chybové stavy.
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
            # Unikátny timestamp pre obídenie serverovej cache
            fresh_url = f"{url}?_nocache={int(time.time())}"
            response = requests.get(fresh_url, headers=headers, timeout=4, allow_redirects=True)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                # Odstránenie JS kódov a CSS štýlov pre čistý text
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
    
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Dáta z Vegnella.sk boli úspešne obnovené.")
    return status_log

# --- 2. ASYNCHRÓNNY OBAL (NEBLOKUJE SERVER) ---
async def async_scrape_vegnella():
    """Deleguje blokujúci scraping do samostatného vlákna (Thread Pool)."""
    return await asyncio.to_thread(sync_scrape_vegnella)

# --- 3. LIFESPAN A PLÁNOVAČ (APSCHEDULER) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Prvé načítanie pri štarte aplikácie
    await async_scrape_vegnella()
    
    # Nastavenie plánovača: každý pracovný deň o 07:00 ráno
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
        # Poistka pre prípad prázdnych dát
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

        # PRESNÉ ČASOVÉ ÚSEKY PRE AKTUÁLNY MOMENT
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
- Objednávky Menu (Osobný odber): POVOLENÉ (prijíma sa na čas vyzdvihnutia 11:00 - 16:00)
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

        # SYSTEM PROMPT S NEPRIESTRELNOU BIZNIS LOGIKOU
        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}

AKTUÁLNE POVOLENÉ A ZAKÁZANÉ ČINNOSTI PRE TÚTO CHVÍĽU:
{STATUS_TERAZ}

FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

STRIKTNÁ LOGIKA PRE OTÁZKY O OBJEDNÁVANÍ (DÔLEŽITÉ!):
Dôsledne rozlišuj medzi ČASOM ZADÁVANIA OBJEDNÁVKY a ČASOM PLÁNOVANÉHO DORUČENIA/VYZDVIHNUTIA!

1. ROZVOZ / DONÁŠKA MENU:
   - Čas prijímania/zadávania objednávky: IBA v pracovné dni od 08:00 do 10:00 ráno.
   - Čas doručovania jedla: Medzi 11:00 a 13:00.
   - AK SA ZÁKAZNÍK PÝTA, ČI MÔŽE OBJEDNAŤ ROZVOZ O 11:00 (alebo kedykoľvek po 10:00): 
     Odpovedaj STRIKTNE NIE! Vysvetli, že o 11:00 sa rozvoz už nedá objednať (uzávierka bola o 10:00). O 11:00 sa rozvoz už len doručuje zákazníkom.

2. OSOBNÝ ODBER MENU:
   - Čas zadávania objednávky cez bota: V pracovné dni od 08:00 do 10:00 ráno.
   - Čas vyzdvihnutia jedla: V pracovné dni od 11:00 do 16:00.
   - AK SA ZÁKAZNÍK PÝTA, ČI MÔŽE OBJEDNAŤ OSOBNÝ ODBER PO 10:00 (napr. o 11:00 alebo 12:00):
     Odpovedaj, že po 10:00 už bot automatické objednávky neprijíma a z dôvodu overenia voľných porcií musí zákazník zavolať na +421 910 824 923.

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA A BEZPEČNOSTI (STRIKTNÉ):
1. TÉMA KONVERZÁCIE: Odpovedaj na otázky výlučne ohľadom bistra a bio obchodu Vegnella. Ak sa zákazník pýta na cudziu tému, zdvorilo ho odmietni s tým, že odpovedáš len k témam bistra Vegnella.
2. ZÁKAZ VYMÝŠĽANIA (HALUCINÁCIÍ): Vždy sa drž výhradne faktov uvedených v týchto inštrukciách a v dodaných dátach z webu. NIKDY si nevymýšľaj informácie ani nepoužívaj všeobecné vedomosti mimo dodaných dát.
3. PREDAJNÝ TÓN: NIKDY na silu netlač zákazníka do objednávok.
4. STRUČNOSŤ: Hovor iba priamo k veci bez zbytočnej omáčky.

PRAVIDLÁ SÚVISIACE S ČASOM A PONUKOU:
1. NONSTOP INFORMOVANIE (24/7): Bez ohľadu na otváracie hodiny VŽDY odpovedaj na otázky ohľadom ponuky, zloženia, cenníkov a otváracích hodín.
2. OVEROVANIE DÁTUMU OBEDOVÉHO MENU: Ak je víkend/večer a na webe sú staré dáta z minulého týždňa, nevydávaj ich za nové menu na nadchádzajúci týždeň. Vysvetli, že nové menu bude zverejnené v pondelok ráno.
3. ŽIADNE "ZAJTRA" CEZ VÍKEND: V sobotu a v nedeľu NIKDY nehovor "príďte zajtra" alebo "spýtajte sa zajtra", pretože v nedeľu je zatvorené. Vždy použi formuláciu "v najbližší pracovný deň, teda v pondelok ({next_monday_date})".

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