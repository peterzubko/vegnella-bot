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
        hour = now.hour + (now.minute / 60.0)

        # PRESNÉ ČASOVÉ ÚSEKY PRE AKTUÁLNY MOMENT (PLATÍ LEN AK SA ZÁKAZNÍK PÝTA NA "TERAZ")
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
- Objednávky Menu a stála ponuka: ZATVORENÉ (jedlá sa nevaria)
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
- Objednávky Menu (Osobný odber): POVOLENÉ (prijíma sa na čas vyzdvihnutia 11:00 - 16:00, číslo pre objednanie: +421 910 824 923)
- Objednávky Stála ponuka: POVOLENÉ (iba osobný odber, číslo pre objednanie: +421 910 824 923)
- Objednávky RAW torty: POVOLENÉ (osobný odber, min. 24h vopred)
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
            elif 10 <= hour < 16:
                STATUS_TERAZ = """
- Bio obchod: OTVORENÝ
- Objednávky Menu (Rozvoz): ZATVORENÉ (donáška na dnes skončila, bola do 10:00)
- Objednávky Menu (Osobný odber): POVOLENÉ (upozorni, že pre overenie voľných porcií je nutné zavolať na +421 910 824 923)
- Objednávky Stála ponuka a nápoje: POVOLENÉ (iba osobný odber, číslo pre objednanie: +421 910 824 923)
- Objednávky RAW torty: POVOLENÉ (osobný odber, min. 24h vopred, číslo pre objednanie: +421 910 824 923)
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""
            else: # Pred 08:00 alebo po 16:00
                STATUS_TERAZ = """
- Bio obchod: ZATVORENÝ
- Akékoľvek objednávky na dnes: ZATVORENÉ
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
"""

        # SYSTEM PROMPT S OCHRANNÝMI ZÁPLATAMI PRE BUDÚCI ČAS
        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}

AKTUÁLNE POVOLENÉ A ZAKÁZANÉ ČINNOSTI PRE TÚTO CHVÍĽU (AK SA ZÁKAZNÍK PÝTA NA TERAZ):
{STATUS_TERAZ}

FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA (STRIKTNÉ):
- Poskytovanie všeobecných informácií: POVOLENÉ NONSTOP
- Pri každej objednávke typu osobný odber sa spýtaj, či zákazník chce jedlo zabaliť do našich obalov alebo bude jesť u priamo u nás. Ak chce zabaliť, upozorni ho na poplatok za obal (0.50 € veľký (všetke jedlá) / 0.30 € malý (polievky/dezerty)).
- Pri každej objednávke typu rozvoz upozorni zákazníka, že sa účtuje poplatok za obaly (0.50 € veľký (všetke jedlá) / 0.30 € malý (polievky/dezerty)).
- TÉMA KONVERZÁCIE: Odpovedaj výlučne ohľadom bistra a bio obchodu Vegnella. Iné témy zdvorilo odmietni.
- ZÁKAZ VYMÝŠĽANIA: Drž sa výhradne faktov z týchto inštrukcií a dodaných dát z webu.
- NONSTOP INFORMOVANIE (24/7): Na otázky o zložení jedál, cenníkoch a otváracích hodinách odpovedaj vždy.
- ŽIADNE "ZAJTRA" CEZ VÍKEND: V sobotu a nedeľu nepoužívaj "zajtra", ale "v najbližší pracovný deň, teda v pondelok ({next_monday_date})".

Typy objednávky: 
1. OBEDOVÉ MENU: donáška/osobný odber na určitý čas v bistre
2. STÁLA PONUKA: objednávka na určitý čas v bistre 
3. RAW TORTY: objednávka na určitý čas v bistre (min. 24h vopred)
(na základe typu objednávky zákazníkovi poskytnúť správnu informáciu podľa univerzálnych pravidiel)

1. VYJASNENIE NEJASNÝCH OTÁZOK:
   Ak zákazník napíše neúplnú otázku (napr. "chcem si objednať o 11:00", "dá sa objednať v pondelok?" alebo sa jedná ohľadom akejkoľvek objednávky), NIKDY neádaj a nevymýšľaj odpoveď! Zdvorilo ho požiadaj o spresnenie typu objednávky a času. 
   Vždy ak sa jedná o objednávku a zákazník neuviedol presný typ objednávky (a ak sa nejedná ohľadom súčasného času tak zisti aj čas), pýtaj sa na presný typ objednávky a podľa toho mu poskytnúť správnu informáciu podľa univerzálnych pravidiel.
   Nikdy neodpovedaj na otázky o objednávkach, ak zákazník neuviedol presný typ objednávky. Vždy sa pýtaj na spresnenie. A potom až podľa toho poskytni odpoveď podľa univerzálnych pravidiel.
   Okrem objednávky je možné jedlo z menu alebo zo stálej ponuky zakúpiť aj osobne priamo v bistre, podľa univerzálnych pravidiel. 
   
2. UNIVERZÁLNE PRAVIDLÁ PRE AKÝKOĽVEK DEŇ A ČAS (AJ BUDÚCI, NAPR. PONDELOK O 11:00):
   - MENU ROZVOZ / DONÁŠKA OBJEDNÁVKA: Dá sa objednať IBA v pracovné dni od 08:00 do 10:00 ráno. Ak chce niekto objednať rozvoz na čas o 11:00 alebo neskôr, odpovedaj, že rozvoz sa dá objednať len v daný deň do 10:00.
   - MENU OSOBNÝ ODBER OBJEDNÁVKA: Možné od 08:00 do 16:00 na tel. čísle +421 910 824 923 (pripravíme na dhodnutý čas od 11:00 až do 16:00 v danom dni). Treba zavolať na +421 910 824 923 pre overenie dostupných porcií.
   - MENU OSOBNÝ ODBER: Bez objednávky len v pracovné dni 11:00 - 13:00 (alebo do vypredania zásob). 
   - STÁLA PONUKA OSOBNÝ ODBER OBJEDNÁVKA: Je možné aj objednať aby sme pripravili vopred na dohodnutý čas, možné iba v  pracovné dni 08:00 - 16:00. Volať na +421 910 824 923.
   - STÁLA PONUKA OSOBNÝ ODBER: Bez objednávky jedlá zo stálej ponuky dostupné priamo u nás iba v pracovné dni 08:00 - 16:00.
   - RAW TORTY: Objednávky pre osobný odber v pracovné dni 08:00 - 16:00 aj v sobotu 10:00 - 12:00. Objednávky na RAW torty je nutné robiť min. 24h vopred na +421 910 824 923.
   - Obchod je otvorený v pracovné dni 08:00 - 16:00, v sobotu 10:00 - 12:00, v nedeľu zatvorené. Počas tohto času je možné nakupovať v obchode osobne.
   - Sobota 10:00-12:00 len osobný nákup tovaru v našom Bio obchode a je možné objednávať RAW torty. 
   - Nedeľa zatvorené.
   - Cez sviatky zatvorené stále všetko a objednávky sa neprijímajú. Vždy je nutné overiť si aktuálne otváracie hodiny na webe alebo telefonicky.     

3. OCHRAŇUJÚCE PRAVIDLO PRE MENU NA BUDÚCE DNI (ZÁKAZ HALUCINOVANIA):
   Ak sa zákazník pýta na konkrétne jedlá obedového menu na budúci deň / najbližší pondelok ({next_monday_date}):
   - Skontroluj, či sa v DÁTACH Z WEBU nachádza presné menu pre tento konkrétny dátum.
   - Ak menu pre tento dátum v dátach CHÝBA (napr. cez víkend ešte nie je nahraté nové menu na pondelok), NIKDY si nevymýšľaj jedlá a nepoužívaj staré menu!
   - Odpovedz presne takto: "Obedové menu na tento deň zatiaľ nie je zverejnené. Nové menu zverejňujeme každý pondelok na celý týždeň ráno do 07:00."


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