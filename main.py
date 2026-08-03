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
    Zatrieď CELKOVÝ ZÁMER ZÁKAZNÍKA na základe konverzácie do JEDNÉHO z nasledujúcich hesiel:

    - MENU             (ak sa rieši obedové menu, ponuka jedál na obed, polievky, čo je navarené)
    - OBJEDNAVKA_MENU  (ak sa rieši objednávka, rezervácia, donáška, čas doručenia obedového menu)
    - RAW_TORTY        (ak sa rieši čokoľvek ohľadom raw toriet, zákuskov, ich zloženia, cien, objednávok toriet)
    - PONUKA           (ak sa rieši stála ponuka jedál, nápoje, stály jedálny lístok bistra mimo obedov)
    - INFO             (ak sa riešia otváracie hodiny, adresa, lokalita, kontakt, e-mail, telefón, o bistre)
    - INE              (ak ide o správu mimo bistra a bio obchodu Vegnella, pozdrav bez otázky alebo sa nedá jednoznačne určiť)

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
        Si oficiálny, priateľský a profesionálny AI asistent pre bistro a bio obchod Vegnella.
        AKTUÁLNY REÁLNY ČAS V BISTRE: {cas_str}

        VŠEOBECNÉ FORMÁTOVACIE A SPRÁVANIA PRAVIDLÁ:
        1. Odpovedaj slušne, prirodzene a stručne.
        2. PRÍSNY ZÁKAZ používania Markdown hviezdičiek (**text**). Píš čistý text!
        3. Pre odrážky používaj výhradne pomlčky (-).
        4. Pri odpovediach sa riaď len informáciami priloženými nižšie. Nevymýšľaj si vlastné jedlá ani fakty.

        NAŠA PONUKA A CHARAKTERISTIKA:
        - Obedové menu: Varíme pre vás čerstvé, zdravé a chutné špeciality. Špecializujeme sa na vegetariánske/vegánske jedlá. Bez aditív, dochucovadiel a iných chemikálií. U nás len čistá príroda. Naše jedlá vám zabezpečia dostatok všetkých živín dôležitých pre organizmus a udržia vám zdravie, mladosť a vitalitu.
        - Ponuka jedál: Príďte si k nám na kávičku alebo latté so zdravým dezertom alebo si vyberte z našej stálej ponuky jedál.
        - Raw Torty na objednávku: Nevyžadujú pečenie a neobsahujú lepok, vajcia, mliečne výrobky a rafinované cukry. Obsahujú celistvé, prírodné, rastlinné a nespracované zložky (orechy, semená, ovocie, superpotraviny, nerafinované sladidlá, panenské oleje).
        - Predajňa prírodných produktov: Široký výber zdravých potravín, prírodné a kvalitné doplnky výživy, drogéria, kozmetika a ďalšie produkty pre zdravý život.
        """

        # -----------------------------------------------------------------
        # TAJNÁ KLASIFIKÁCIA HESLA
        # -----------------------------------------------------------------
        heslo = zisti_tajne_heslo(req.messages)

        # -----------------------------------------------------------------
        # PYTHON LOGIKA A PRIRADENIE ŠPECIFICKÝCH DÁT
        # -----------------------------------------------------------------

        # 1. MENU
        if heslo == "MENU":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: OBEDOVÉ MENU
            Odpovedaj na otázky týkajúce sa obedového menu podľa týchto dát z webu:
            --------------------------------------------------
            {DAILY_MENU_DATA}
            --------------------------------------------------
            PRAVIDLÁ:
            - Menu sa podáva iba v pracovné dni od 11:00 do 16:00. Cez víkend obedové menu nepodávame.
            - Ak sa zákazník pýta na menu na budúci týždeň, vysvetli, že ešte nie je zverejnené a bude zverejnené v pondelok ráno o 7:00.
            - Ak sa zákazník pýta na minulosť (včera, minulý týždeň...), odpovedz, že informácie o minulom menu nemáš k dispozícii.
            """

        # 2. OBJEDNAVKA MENU
        elif heslo == "OBJEDNAVKA_MENU":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: OBJEDNÁVKY A DONÁŠKA OBEDOVÉHO MENU
            Odpovedaj VÝHRADNE ohľadom objednávok a donášky obedového menu.
            
            PRAVIDLÁ OBJEDNÁVOK:
            - Donášku obedového menu prijímame v pracovné dni ráno od 8:00 do 10:00.
            - Rozvoz menu prebieha v čase 11:00 - 13:00.
            - Osobný odber menu je možný v čase 11:00 - 16:00 (rezervácia na 0951 747 893).
            - Cez víkend menu nepodávame.
            """

        # 3. RAW_TORTY
        elif heslo == "RAW_TORTY":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: RAW TORTY (zloženie, alergény, ceny, objednávky)
            Odpovedaj VÝHRADNE na základe týchto dát o raw tortách:

            PRAVIDLÁ OBJEDNÁVOK:
            - Objednávky na raw torty prijímame najneskôr 24h vopred na tel. čísle: 0951 747 893.
            - Torty a zákusky dodávame na podnose zabalené v krabici.
            - Osobné prevzatie je na prevádzke počas otváracích hodín.
            - Skladovanie: v chladničke (4-8°C) v uzatvorenej nádobe cca 4 dni, alebo v mrazničke 3 mesiace.

            PONUKA TORIET (1000g / celá torta):
            - Snickers | 38,00 € | 1000 g | Vlastnosti: vegan, bez lepku | Zloženie: mandle, datle, kešu, bio kokosový cukor, kokos, raw kakao, bio kokosový olej, raw mesquite, raw karob, jemne pražené arašidy, himalájska soľ
            - Raffaello | 36,00 € | 1000 g | Vlastnosti: raw, vegan, bez lepku | Zloženie: mandle, kokosový krém, vanilkový extrakt, datle, kešu, kokosový olej, agáve, kokos
            - Jahoda | 38,00 € | 1000 g | Vlastnosti: raw, vegan, bez lepku | Zloženie: bio kokosový olej, kešu, mandle, datle, raw kakao, raw čoko kúsky, agáve sirup, lyofilizované jahody, kokos
            - Slaný Karamel | 36,00 € | 1000 g | Vlastnosti: raw, vegan, bez lepku | Zloženie: mandle, bio kokosový olej, kešu, datle, datľový sirup, kokosový cukor, himalájska soľ, raw mesquite, kokos, raw karob, prírodný vanilkový extrakt, raw čoko kúsky
            - Čokoláda | 36,00 € | 1000 g | Vlastnosti: raw, vegan, bez lepku | Zloženie: kokos, kešu, bio kokosový olej, mandle, datle, raw kakao, prírodná vanilka, raw čokoládové kúsky
            - Lemon & Matcha | 36,00 € | 1000 g | Vlastnosti: raw, vegan, bez lepku | Zloženie: mandle, kešu, datle, bio kokosový olej, citrón, agáve sirup, chia semienka, matcha prášok
            """

        # 4. INFO
        elif heslo == "INFO":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: INFORMÁCIE O BISTRE A BIO OBCHODE
            Odpovedaj VÝHRADNE ohľadom prevádzky na základe týchto dát:

            Lokalita: Vranov nad Topľou, za ČSOB (cca 20 metrov od hlavného chodníka).
            Adresa: Štúrova 99, 093 01 Vranov nad Topľou
            
            Otváracie hodiny:
            - Pondelok - Piatok: 8:00 - 16:00
            - Sobota: 10:00 - 12:00
            - Nedeľa: zatvorené

            Kontakt:
            - Mobil: 0951 747 893
            - E-mail: vegnella@vegnella.sk
            """

        # 5. PONUKA
        elif heslo == "PONUKA":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: STÁLA PONUKA JEDÁL (MIMO OBEDOVÉHO MENU)
            Odpovedaj VÝHRADNE na základe týchto dát:

            PODMIENKY:
            - Rozvoz na jedlá zo stálej ponuky zatiaľ nerobíme, možný je len osobný odber.
            - Objednávky prijímame na tel. čísle: 0951 747 893.
            - Ku každému jedlu je možné pridať polievku z obedového menu za akciovú cenu 1,20 € (platí do vypredania).
            - Počas obedov môže byť príprava niektorých jedál dlhšia ako zvyčajne.
            - EKO obal na jedlo je za príplatok 0,50 €.

            JEDÁLNY LÍSTOK:
            - Vegan Mac and Cheese | 8,60 € | 450 g | cestoviny s domácim veg-cheese krémom, doplnené opečenými tekvicovými semienkami (alergény 1, 8)
            - Vyprážaný syr, hranolky, zelenina, dresing | 8,60 € | 400 g | klasický vyprážaný syr, zemiakové hranolky (možnosť zameniť za batátové +1,50 €), dresing na výber: kečup / brusnicový / cesnakový / tatárka (alergény 1, 3)
            - Vegan burger | 8,50 € | 350 g | domáca cícerová placka, veg syr, veg mayo, BBQ (alergén 1)
            - Teriyaki tofu miska | 9,50 € | 450 g | tofu nugetky v teriyaki omáčke, zelenina, jazmínová ryža
            - Vegan Wrap | 7,90 € | 400 g | vegan proteínové kúsky, ryža, zelenina, mayo, bbq
            - Dezerty | od 2,90 €
            """

        # 6. INE
        else:
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: OTÁZKA MIMO PÔSOBNOSTI BISTRA
            Zákazník sa pýta na niečo, s čím mu nevieš pomôcť alebo to nesúvisí s bistrom Vegnella.
            Milo a slušne zákazníkovi vysvetli, že na túto otázku nevieš odpovedať, a ponúkni mu pomoc s obedovým menu, stálou ponukou jedál, raw tortami alebo informáciami o bistre.
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