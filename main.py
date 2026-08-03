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

    - MENU             (ak sa rieši obedové menu, ponuka jedál na obed, polievky, čo je navarené)
    - OBJEDNAVKA_MENU  (ak sa rieši objednávka, rezervácia, donáška, čas doručenia alebo otázky či si môže objednať dnes/zajtra)
    - INFO             (ak sa rieši informácia o vegnella bistre alebo bio obchode, naša ponuka, otváracie hodiny, kontakt, adresa...)
    - INE              (ak ide o správu mimo bistra a bio obchodu vegnella, alebo sa nedá jednoznačne určiť)
    - RAW_TORTY         (ak sa rieši čokoľvek ohľadom raw toriet)
    - PONUKA           (ak sa rieši čokoľvek ohľadom našej stálej ponuky jedál)


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

        NAŠA PONUKA:
        Obedové menu - Varíme pre vás čerstvé, zdravé a chutné špeciality. Špecializujeme sa na vegetriánske/vegánske jedlá. 
        Bez aditív, dochucovadiel a iných chemikálii. U nás len čistá príroda. 
        Naše jedlá vám zabezpečia dostatok všetkých živín dôležitých pre organizmus a udržia vám zdravie, mladosť a vitalitu po dlhý čas.
        Ponuka jedál - Prídte si k nám na kávičku alebo latté so zdravým dezertom alebo si vyberte z našej ponuky jedál.
        Raw Torty na objednávku - Na rozdiel od tradičných zákuskov, naše raw torty nevyžadujú pečenie a neobsahujú lepok, vajcia, 
        mliečne výrobky a rafinované cukry. Namiesto toho obsahujú iba celé, prírodné, rastlinné a nespracované zložky, 
        ako sú orechy, semená, ovocie, superpotraviny, nerafinované sladidlá a panenské oleje.
        Predajňa prírodných produktov - Nájdete u nás aj široký výber zdravých potravín, prírodné a kvalitné doplnky výživy, 
        drogériu a kozmetku a veľa ďalších produktov pre zdravý život. Naši experti vám s výberom radi poradia.
        """
        # -----------------------------------------------------------------
        # TAJNÁ KLASIFIKÁCIA HESLA
        # -----------------------------------------------------------------
        heslo = zisti_tajne_heslo(req.messages)
        # -----------------------------------------------------------------
        # PYTHON LOGIKA A PRIRADENIE ŠPECIFICKÝCH DÁT
        # -----------------------------------------------------------------
        # MENU
        if heslo == "MENU":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: OBEDOVÉ MENU
            Odpovedaj na otázky týkajúce sa obedového menu podľa týchto dát z webu:
            {DAILY_MENU_DATA}
            Menu sa podáva iba v pracovné dni od 11:00 do 16:00. Cez víkend obedové menu nepodávame.
            Ak sa zákazník pýta na menu na budúci týždeň, vysvetli, že ešte nie je zverejnené a bude zverejnené v pondelok ráno o 7:00.
            Ak sa zákazník pýta na minulosť (včera, minulý týždeň...), odpovedz, že informácie o minulom menu nemáš.
            """

        # OBJEDNAVKA MENU
        elif heslo == "OBJEDNAVKA_MENU":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: OBJEDNÁVKY A DONÁŠKA obedového menu
            Odpovedaj VÝHRADNE ohľadom objednávok a donášky obedového menu.
            
            PRAVIDLÁ OBJEDNÁVOK:
            - Donášku obedového menu prijímame v pracovné dni ráno od 8:00 do 10:00.
            - Rozvoz menu prebieha v čase 11:00 - 13:00.
            - Osobný odber menu je možný v čase 11:00 - 16:00 (rezervácia na 0951 747 893).
            - Cez víkend menu nepodávame.
            """

        # RAW_TORTY
        elif heslo == "RAW_TORTY":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: raw torty, ich zloženie, alergény, cenová ponuka
            Odpovedaj VÝHRADNE ohľadom dát o raw tortách
            PRAVIDLÁ OBJEDNÁVOK:
            Objednávky na raw torty prijímame najneskôr 24h vopred (0918 914 922).
            Torty a zákusky dodávame na podnose zabalené v krabici.
            Osobné prevzatie na našej prevádzke počas pracovných hodín.
            Raw torty skladujte v chladničke (4-8°C), v uzatvorenej nádobe kde vydržia cca 4 dni alebo v mrazničke 3 mesiace.          
            Snickers 1000g    |    38,00€
            Vlastnosti: vegan | bez lepku
            Zloženie:
            mandle, datle, kešu, bio kokosový cukor, kokos, raw kakao, bio kokosový olej, raw mesquite, raw karob, jemne pražené arašidy, himalájska soľ 
            Raffaello36,00 €   |   1000 gVlastnosti:
            raw | vegan | bez lepku
            Zloženie:
            mandle, kokosový krém, vanilka extrakt, datle, kešu, kokosový olej, agáve, kokos 
            Jahoda38,00 €   |   1000 gVlastnosti:
            raw | vegan | bez lepku
            Zloženie:
            bio kokosový olej, kešu, mandle, datle, raw kakao, raw čoko kúsky, agáve sirup, lyofilizované jahody, kokos 
            Slaný Karamel36,00 €   |   1000 gVlastnosti:
            raw | vegan | bez lepku
            Zloženie:
            mandle, bio kokosový olej, kešu, datle, datľový sirup, kokosový cukor, himalájska soľ, raw mesquite, kokos, raw karob, prírodný vanilkový extrakt, raw čoko kúsky 
            Čokoláda36,00 €   |   1000 gVlastnosti:
            raw | vegan | bez lepku
            Zloženie:
            kokos, kešu, bio koksový olej, mandle, ďatle, raw kakao, prírodná vanilka, raw čokoládové kúsky 
            Lemon & Matcha36,00 €   |   1000 g
            Vlastnosti:
            raw | vegan | bez lepku
            Zloženie:
            mandle, kešu, ďatle, bio kokosový olej, citrón, agáve sirup, chia semienka, matcha prášok
            """

        # INFO
        elif heslo == "INFO":
            specific_prompt = f"""
            Povedz zákazníkovy výhradne témy ohľadom bistra a bio obchodu napr. otváracie hodiny, kontakt, adresu a dalšie z dostupných dát.
            Lokalita
            Nachádzame sa v meste Vranov nad Topľou.
            Presnejšie nás nájdete za ČSOB, asi 20 metrov od hlavného chodníka.
            Otváracie hodiny
            Pondelok - Piatok: 8:00h - 16:00h
            Sobota: 10:00h - 12:00h
            Nedeľa: zatvorené
            Kontakt
            Adresa: Štúrova 99, 093 01 Vranov nad Topľou
            Mobil: 0951 747 893
            E-mail: vegnella@vegnella.sk
            """ 

        # PONUKA
        elif heslo == "PONUKA":
            specific_prompt = f"""
            Rozvoz na jedlo z ponuky zatiaľ nerobíme, možnost objednať pre osobný odber
            Objednávky prijímame na našom tel. čísle 0951 747 893.
            Ku každému jedlu je možné pridať polievku z obedového menu za akciovú cenu 1,20€ (platí do vypredania)
            Počas obedov môže byť príprava niektorých jedál dlhšia ako obyčajne
            EKO obal na jedlo je za príplatok 0,50€
            Vegan Mac and Cheese
            8,60€450g, cestoviny s domácim veg-cheese krémom, doplnené opečenými tekvicovými semienkami (1,8) 
            Vyprážaný syr, hranolky, zelenina, dresing
            8,60€400g, klasický vyprážaný syr, zemiakové hranolky (možnosť zameniť za batátové + 1,50eur), dresing na výber kečup/brusnicový/cesnakový/tatárka (1,3) 
            Vegan burger
            8,50€350g, domáca cícerová placka, veg syr, veg mayo, BBQ (1) 
            Teriyaki tofu miska
            9,50€450g, tofu nugetky v teriyaki omáčke, zelenina, jazmínová rzža 
            Vegan Wrap
            7,90€400g, vegan proteínové kúsky, ryža, zelenina, mayo, bbq 
            Dezerty
            od 2,90€
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