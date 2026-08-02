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

# Globálna premenná výhradne pre dynamické obedové menu
DAILY_MENU_DATA = ""

# --- STATICKÉ INFORMÁCIE O BISTRE (STÁLA PONUKA, RAW TORTY, KONTAKT) ---
STATIC_INFO = """
GENERAL INFO:
Obedové menu
Varíme pre vás čerstvé, zdravé a chutné špeciality. Špecializujeme sa na vegetariánske/vegánske jedlá. Bez aditív, dochucovadiel a iných chemikálií. U nás len čistá príroda. Naše jedlá vám zabezpečia dostatok všetkých živín dôležitých pre organizmus a udržia vám zdravie, mladosť a vitalitu po dlhý čas.
Príďte si k nám na kávičku alebo latté so zdravým dezertom alebo si vyberte z našej ponuky jedál.
Raw Torty na objednávku
Na rozdiel od tradičných zákuskov, naše raw torty nevyžadujú pečenie a neobsahujú lepok, vajcia, mliečne výrobky a rafinované cukry. Namiesto toho obsahujú iba celé, prírodné, rastlinné a nespracované zložky, ako sú orechy, semená, ovocie, superpotraviny, nerafinované sladidlá a panenské oleje.
Predajňa prírodných produktov
Nájdete u nás aj široký výber zdravých potravín, prírodné a kvalitné doplnky výživy, drogériu a kozmetiku a veľa ďalších produktov pre zdravý život. Naši experti vám s výberom radi poradia.

OBEDOVÉ MENU:
Objednávky na donášku prijímame do 10:00h. Rozvoz menu prebieha v čase 11:00h - 13:00h.
Cena MENU (hlavné jedlo + polievka) je 8,40€. Polievka samostatne 2,20€.
ZĽAVA pri objednávke minimálne 3 MENU platíte za každé iba 7,40€. Rovnaká cena ak si predobjednáte na celý týždeň.
Menu podávame v čase 11:00h - 13:00h alebo do vypredania.
Jedlo si môžete aj telefonicky rezervovať alebo vám ho môžeme zabaliť a pripraviť na dohodnutý čas pre osobné vyzdvihnutie do 16:00h (0951 747 893).
Naše EKO obaly na menu sú za príplatok 0,50€ (veľký) a 0,30€ (malý - polievka, raw torta a pod.). Môžete priniesť aj svoje vlastné obaly.

PONUKA STÁLYCH JEDÁL:
Ku každému jedlu je možné pridať polievku z obedového menu za akciovú cenu 1,20€ (platí do vypredania)
Počas obedov môže byť príprava niektorých jedál dlhšia ako obyčajne
EKO obal na jedlo je za príplatok 0,50€
Vegan Mac and Cheese
8,60€ 450g, cestoviny s domácim veg-cheese krémom, doplnené opečenými tekvicovými semienkami (1,8) 
Vyprážaný syr, hranolky, zelenina, dresing
8,60€ 400g, klasický vyprážaný syr, zemiakové hranolky (možnosť zameniť za batátové + 1,50eur), dresing na výber kečup/brusnicový/cesnakový/tatárka (1,3) 
Vegan burger
8,50€ 350g, domáca cícerová placka, veg syr, veg mayo, BBQ (1) 
Teriyaki tofu miska
9,50€ 450g, tofu nugetky v teriyaki omáčke, zelenina, jazmínová ryža 
Vegan Wrap
7,90€ 400g, vegan proteínové kúsky, ryža, zelenina, mayo, bbq 
Dezerty
od 2,90€

RAW TORTY:
Torty a zákusky dodávame na podnose zabalené v krabici.
Raw torty skladujte v chladničke (4-8°C), v uzatvorenej nádobe kde vydržia cca 4 dni alebo v mrazničke 3 mesiace.
RAW TORTY
Na rozdiel od tradičných zákuskov, naše raw torty nevyžadujú pečenie a neobsahujú lepok, vajcia, mliečne výrobky a rafinované cukry. Namiesto toho obsahujú iba celé, prírodné, rastlinné a nespracované zložky, ako sú orechy, semená, ovocie, superpotraviny, nerafinované sladidlá a panenské oleje.
1000g    |    38,00€ Snickers Vlastnosti: vegan | bez lepku. Zloženie: mandle, datle, kešu, bio kokosový cukor, kokos, raw kakao, bio kokosový olej, raw mesquite, raw karob, jemne pražené arašidy, himalájska soľ 
Raffaello 36,00 € | 1000 g Vlastnosti: raw | vegan | bez lepku. Zloženie: mandle, kokosový krém, vanilka extrakt, datle, kešu, kokosový olej, agáve, kokos 
Jahoda 38,00 € | 1000 g Vlastnosti: raw | vegan | bez lepku. Zloženie: bio kokosový olej, kešu, mandle, datle, raw kakao, raw čoko kúsky, agáve sirup, lyofilizované jahody, kokos 
Slaný Karamel 36,00 € | 1000 g Vlastnosti: raw | vegan | bez lepku. Zloženie: mandle, bio kokosový olej, kešu, datle, datľový sirup, kokosový cukor, himalájska soľ, raw mesquite, kokos, raw karob, prírodný vanilkový extrakt, raw čoko kúsky 
Čokoláda 36,00 € | 1000 g Vlastnosti: raw | vegan | bez lepku. Zloženie: kokos, kešu, bio kokosový olej, mandle, datle, raw kakao, prírodná vanilka, raw čokoládové kúsky 
Lemon & Matcha 36,00 € | 1000 g Vlastnosti: raw | vegan | bez lepku. Zloženie: mandle, kešu, datle, bio kokosový olej, citrón, agáve sirup, chia semienka, matcha prášok

KONTAKT A ADRESA:
Lokalita
Nachádzame sa v meste Vranov nad Topľou.
Presnejšie nás nájdete za ČSOB, asi 20 metrov od hlavného chodníka.
Otváracie hodiny
Pondelok - Piatok: 8:00h - 16:00h
Sobota: 10:00h - 12:00h
Nedeľa: zatvorené
Kontakt
Adresa: Štúrova 99, 093 01 Vranov nad Topľou
Mobil (Obedové menu / Stála ponuka / Všeobecný kontakt): 0951 747 893
Mobil (RAW torty): 0951 747 893
E-mail: vegnella@vegnella.sk
"""

# --- 1. TARGETING SCRAPING (LEN OBEDOVÉ MENU) ---
def sync_scrape_menu_only():
    """
    Stiahne výhradne text z podstránky obedy.html, kde sa nachádza aktuálne týždenné menu.
    """
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
        response = requests.get(fresh_url, headers=headers, timeout=5, allow_redirects=True)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            
            text = soup.get_text(separator='\n', strip=True)
            if len(text) > 50:
                DAILY_MENU_DATA = text[:4000] # Bohato stačí na týždenné menu
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Obedové menu bolo úspešne obnovené.")
                return ["OK: Menu obnovené"]
            else:
                print("[VAROVANIE] Stiahnutá stranka menu bola prázdna.")
        else:
            print(f"[CHYBA] Nepodarilo sa stiahnuť menu, status code: {response.status_code}")
    except Exception as e:
        print(f"[CHYBA] Zlyhal scraping menu: {str(e)}")
    
    return ["ZLYHALO: Menu sa nepodarilo obnoviť"]

# --- 2. ASYNCHRÓNNY OBAL ---
async def async_scrape_menu():
    return await asyncio.to_thread(sync_scrape_menu_only)

# --- 3. LIFESPAN A PLÁNOVAČ (APSCHEDULER) ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Načítanie menu pri štarte servera
    await async_scrape_menu()
    
    # Plánovač: Každý pracovný deň o 07:00 ráno stiahne čerstvé menu
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(
        sync_scrape_menu_only, 
        trigger='cron', 
        day_of_week='mon-fri', 
        hour=7, 
        minute=0
    )
    scheduler.start()
    yield
    scheduler.shutdown()

# --- 4. INICIALIZÁCIA FASTAPI ---
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

# --- 5. ENDPOINTY ---
@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running (Optimized)"}

@app.get("/api/refresh")
async def refresh_data():
    log = await async_scrape_menu()
    return {
        "status": "Obedové menu bolo manuálne obnovené!",
        "log": log,
        "dlzka_menu_textu": len(DAILY_MENU_DATA)
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        # Poistka, ak by menu ešte nebolo stiahnuté
        if not DAILY_MENU_DATA:
            await async_scrape_menu()

        # ČASOVÁ LOGIKA
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        
        dni_sk = {
            'Monday': 'Pondelok', 'Tuesday': 'Utorok', 'Wednesday': 'Streda',
            'Thursday': 'Štvrtok', 'Friday': 'Piatok', 'Saturday': 'Sobota', 'Sunday': 'Nedeľa'
        }
        day_en = now.strftime("%A")
        day_sk = dni_sk.get(day_en, day_en)
        current_time_str = f"{day_sk}, {now.strftime('%d.%m.%Y %H:%M hodín')}"

        # Dátum najbližšieho pondelka
        days_ahead = (0 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 16:
            days_ahead = 7
        elif day_en in ['Saturday', 'Sunday']:
            days_ahead = (7 - now.weekday()) % 7
            
        next_monday_date = (now + timedelta(days=days_ahead)).strftime("%d.%m.%Y")

        # ČISTÝ PROMPT
        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}

FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA (STRIKTNÉ):
- Poskytovanie všeobecných informácií (otváracie hodiny, cenník, zloženie, adresa): POVOLENÉ NONSTOP (24/7).
- Pri každej objednávke typu osobný odber sa spýtaj, či zákazník chce jedlo zabaliť do našich obalov alebo bude jesť priamo u nás. Ak chce zabaliť, upozorni ho na poplatok za obal (0.50 € veľký pre všetky jedlá / 0.30 € malý pre polievky a dezerty).
- Pri každej objednávke typu rozvoz upozorni zákazníka, že sa účtuje poplatok za obaly (0.50 € veľký / 0.30 € malý).
- TÉMA KONVERZÁCIE: Odpovedaj výlučne ohľadom bistra a bio obchodu Vegnella. Iné témy zdvorilo odmietni.
- ZÁKAZ VYMÝŠĽANIA: Drž sa výhradne faktov z týchto inštrukcií a dodaných dát z webu.
- ŽIADNE "ZAJTRA" CEZ VÍKEND: V sobotu a nedeľu nepoužívaj výraz "zajtra", ale "v najbližší pracovný deň, teda v pondelok ({next_monday_date})".
- Neponúkaj zákazníkovi volať na naše číslo z akéhokoľvek dôvodu ak niesu práve teraz pracovné hodiny. Ak zákazník volá mimo pracovných hodín, zdvorilo ho informuj, že je momentálne zatvorené a že môže zavolať počas otváracích hodín.

URČENIE ČASU OTÁZKY:
- Ak zákazník v otázke NEUVIEDOL konkrétny deň ani čas, AUTOMATICKY vyhodnocuj pravidlá pre AKTUÁLNY ČAS ({current_time_str}).
- Ak zákazník UVIEDOL konkrétny deň alebo čas (napr. "v utorok o 10:00"), vyhodnoť pravidlá pre ním zadaný čas.

TYPY OBJEDNÁVOK:
1. OBEDOVÉ MENU (Donáška / Osobný odber na určitý čas)
2. STÁLA PONUKA (Osobný odber na určitý čas)
3. RAW TORTY (Osobný odber, min. 24h vopred)

1. VYJASNENIE NEJASNÝCH OTÁZOK:
   - Ak sa otázka týka objednávky a zákazník NEUVIEDOL presný typ objednávky (1. Obedové menu, 2. Stála ponuka, 3. RAW torty), NIKDY nehádaj odpoveď! Zdvorilo ho požiadaj o spresnenie typu objednávky (a prípadne času, ak sa nepýta na aktuálny moment).
   - Až po spresnení typu a času objednávky poskytni informáciu podľa univerzálnych pravidiel.
   - Okrem objednávky vopred je možné jedlo zakúpiť aj osobným nákupom priamo v bistre podľa otváracích hodín.

2. UNIVERZÁLNE PRAVIDLÁ PRE AKÝKOĽVEK DEŇ A ČAS:
   - MENU ROZVOZ / DONÁŠKA: Objednávky sa prijímajú IBA v pracovné dni od 08:00 do 10:00 ráno na tel. 0951 747 893. Ak chce niekto objednať rozvoz na neskorší čas (napr. o 11:00), vysvetli, že uzávierka objednávok na rozvoz je do 10:00 v daný deň. Rozvoz prebieha od 11:00 do 13:00.
   - MENU OSOBNÝ ODBER (OBJEDNÁVKA VOPRED): Prijíma sa v pracovné dni od 08:00 do 16:00 na tel. 0951 747 893 na čas vyzdvihnutia od 11:00 do 16:00. Ak zákazník volá/objednáva po 10:00, upozorni ho, že dostupnosť porcií je nutné overiť telefonicky.
   - MENU OSOBNÝ ODBER (BEZ OBJEDNÁVKY): Dostupné priamo v bistre v pracovné dni 11:00 - 13:00 (alebo do vypredania zásob).
   - STÁLA PONUKA (OSOBNÝ ODBER OBJEDNÁVKA): Možné objednať vopred na dohodnutý čas v pracovné dni 08:00 - 16:00 na tel. 0951 747 893.
   - STÁLA PONUKA (BEZ OBJEDNÁVKY): Jedlá dostupné priamo v bistre v pracovné dni 08:00 - 16:00.
   - RAW TORTY: Osobný odber v pracovné dni 08:00 - 16:00 aj v sobotu 10:00 - 12:00. Nutné objednať min. 24h vopred na tel. 0918 914 922.
   - BIO OBCHOD OTVÁRACIE HODINY: Pracovné dni 08:00 - 16:00, Sobota 10:00 - 12:00 (len osobný nákup a RAW torty), Nedeľa a sviatky ZATVORENÉ.

3. OCHRANA PRED HALUCINOVANÍM MENU NA BUDÚCE DNI:
   Ak sa zákazník pýta na konkrétne jedlá obedového menu na budúci deň / najbližší pondelok ({next_monday_date}):
   - Skontroluj, či sa v DÁTACH OBEDOVÉHO MENU nachádza presné menu pre tento konkrétny dátum.
   - Ak menu pre tento dátum v dátach CHÝBA, NIKDY si nevymýšľaj jedlá a nepoužívaj staré menu!
   - Odpovedz presne takto: "Obedové menu na tento deň zatiaľ nie je zverejnené. Nové menu zverejňujeme každý pondelok na celý týždeň ráno do 07:00."

STATICKÉ INFORMÁCIE O BISTRE (STÁLA PONUKA, TORTY, KONTAKT):
--------------------------------------------------
{STATIC_INFO}
--------------------------------------------------

AKTUÁLNE STIAHNUTÉ OBEDOVÉ MENU Z WEBU:
--------------------------------------------------
{DAILY_MENU_DATA}
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