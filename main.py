import os
import time
import json
import smtplib
import asyncio
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
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

# --- E-MAIL NASTAVENIA (SMTP) ---
# Odporúčame použiť systémové premenné prostredia
# --- E-MAIL NASTAVENIA (FORPSI SMTP) ---
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.forpsi.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 587))
SMTP_EMAIL = os.environ.get("SMTP_EMAIL", "postmaster@vegnella.sk")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "bc62QFm@V5") 
BISTRO_EMAIL = os.environ.get("BISTRO_EMAIL", "postmaster@vegnella.sk")

# --- 1. FUNKCIA NA ODOSLANIE E-MAILU OBJEDNÁVKY ---
def odosli_objednavku_email(polozky: str, meno: str, telefon: str, adresa: str, poznamka: str = "Bez poznámky") -> str:
    """
    Fyzicky odosiela e-mail s detailmi objednávky do bistra prostredníctvom SMTP.
    """
    try:
        slovakia_tz = ZoneInfo("Europe/Bratislava")
        cas_objednavky = datetime.now(slovakia_tz).strftime('%d.%m.%Y o %H:%M')

        predmet = f"NOVÁ OBJEDNÁVKA - Donáška Menu ({meno})"
        
        telo_spravy = f"""
        Nová objednávka donášky obedového menu!

        Čas objednávky: {cas_objednavky}
        --------------------------------------------------
        ZÁKAZNÍK: {meno}
        TELEFÓN:  {telefon}
        ADRESA:   {adresa}
        --------------------------------------------------
        OBJEDNANÉ POLOŽKY:
        {polozky}

        POZNÁMKA:
        {poznamka}
        --------------------------------------------------
        Správa bola automaticky vygenerovaná AI asistentom Vegnella.
        """

        msg = MIMEMultipart()
        msg['From'] = SMTP_EMAIL
        msg['To'] = BISTRO_EMAIL
        msg['Subject'] = predmet
        msg.attach(MIMEText(telo_spravy, 'plain', 'utf-8'))

        # Pripojenie na SMTP server a odoslanie
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_EMAIL, SMTP_PASSWORD)
            server.send_message(msg)

        print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] E-mail objednávky bol úspešne odoslaný na {BISTRO_EMAIL}.")
        return "SUCCESS: Objednávka bola úspešne zaznamenaná a e-mail bol odoslaný do bistra."

    except Exception as e:
        print(f"[CHYBA E-MAILU]: {str(e)}")
        return f"ERROR: Nepodarilo sa odoslať e-mail. Chyba: {str(e)}"

# --- 2. DEFINÍCIA OPENAI TOOL (FUNCTION CALLING) ---
tools = [
    {
        "type": "function",
        "function": {
            "name": "odosli_objednavku_email",
            "description": "Odošle e-mail s kompletnou objednávkou donášky obedového menu do bistra, keď zákazník poskytne všetky potrebné údaje.",
            "parameters": {
                "type": "object",
                "properties": {
                    "polozky": {
                        "type": "string",
                        "description": "Presný popis a počet objednaných obedových menu / polievok (napr. 2x Dnešné menu č. 1, 1x Polievka)."
                    },
                    "meno": {
                        "type": "string",
                        "description": "Meno a priezvisko zákazníka."
                    },
                    "telefon": {
                        "type": "string",
                        "description": "Kontaktné telefónne číslo zákazníka."
                    },
                    "adresa": {
                        "type": "string",
                        "description": "Presná adresa doručenia (ulica, číslo, mesto/poschodie)."
                    },
                    "poznamka": {
                        "type": "string",
                        "description": "Doplňujúca poznámka k objednávke alebo dovozu (voliteľné)."
                    }
                },
                "required": ["polozky", "meno", "telefon", "adresa"]
            }
        }
    }
]

# --- 3. SCRAPING OBEDOVÉHO MENU Z WEBU ---
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

# --- 4. ČASOVAČ (LIFESPAN): SPUSTENIE O 7:00 RÁNO ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    await async_scrape_menu()
    
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(sync_scrape_menu_only, trigger='cron', day_of_week='mon-fri', hour=7, minute=0)
    scheduler.start()
    
    yield
    scheduler.shutdown()

# --- 5. FASTAPI A CORS ---
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

# --- 6. TAJNÉ VOLANIE: ZISTENIE HESLA S KONTEXTOM ---
def zisti_tajne_heslo(messages_history: list) -> str:
    recent_messages = messages_history[-6:]
    
    konverzacia_text = ""
    for msg in recent_messages:
        rola = "Zákazník" if msg.get("role") == "user" else "Bot"
        konverzacia_text += f"{rola}: {msg.get('content', '')}\n"

    prompt = f"""
    Zatrieď CELKOVÝ ZÁMER ZÁKAZNÍKA na základe konverzácie do JEDNÉHO z nasledujúcich hesiel:

    - MENU             (ak sa rieši obedové menu, aké je menu na dnes a budúce dni, jedlo, polievky, čo je navarené)
    - OBJEDNAVKA_MENU  (ak chce zákazník vytvoriť objednávku, chystá sa objednať menu, diktuje adresu, meno, telefón alebo rieši čas doručenia donášky)
    - RAW_TORTY        (ak sa rieši čokoľvek ohľadom raw toriet, zákuskov, ich zloženia, cien, objednávok toriet)
    - PONUKA           (ak sa rieši ponuka jedál, nápoje, stály jedálny lístok bistra mimo obedového menu)
    - INFO             (ak sa riešia otváracie hodiny, adresa, lokalita, kontakt, e-mail, telefón)
    - INE              (ak ide o správu mimo bistra alebo sa nedá jednoznačne určiť)

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

# --- 7. ENDPOINTY ---
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

        slovakia_tz = ZoneInfo("Europe/Bratislava")
        now = datetime.now(slovakia_tz)
        cas_str = now.strftime('%A, %d.%m.%Y %H:%M hodín')

        base_prompt = f"""
        Si oficiálny, priateľský a profesionálny AI asistent pre bistro a bio obchod Vegnella.
        AKTUÁLNY REÁLNY ČAS V BISTRE: {cas_str}

        VŠEOBECNÉ FORMÁTOVACIE A SPRÁVANIA PRAVIDLÁ:
        1. Odpovedaj slušne, prirodzene a stručne.
        2. PRÍSNY ZÁKAZ používania Markdown hviezdičiek (**text**). Píš čistý text!
        3. Pre odrážky používaj výhradne pomlčky (-).
        4. Pri odpovediach sa riaď len informáciami priloženými nižšie. Nevymýšľaj si vlastné jedlá ani fakty.
        """

        heslo = zisti_tajne_heslo(req.messages)

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

        # 2. OBJEDNAVKA MENU (S FUNKCIOU OBJEDNÁVANIA)
        elif heslo == "OBJEDNAVKA_MENU":
            specific_prompt = f"""
            TVOJA AKTUÁLNA TÉMA: OBJEDNÁVKY A DONÁŠKA OBEDOVÉHO MENU
            DNEŠNÁ PONUKA OBEDOVÉHO MENU:
            --------------------------------------------------
            {DAILY_MENU_DATA}
            --------------------------------------------------

            PRAVIDLÁ OBJEDNÁVOK A ZBERU ÚDAJOV:
            - Donášku obedového menu prijímame v pracovné dni ráno od 8:00 do 10:00. Rozvoz prebieha 11:00 - 13:00.
            - Ak chce zákazník vytvoriť objednávku na donášku, postupne od neho zisti tieto POVINNÉ ÚDAJE:
              1. Presné položky a počet kusov (ktoré obedové menu/polievku chce)
              2. Meno a priezvisko
              3. Telefónne číslo
              4. Adresu doručenia
              5. Poznamku (voliteľné)
            - Pýtaj sa prirodzene a krok za krokom, ak niektoré údaje chýbajú.
            - KÝM NEMÁŠ VŠETKY 4 POVINNÉ ÚDAJE (Položky, Meno, Telefón, Adresa), NEVOLAJ funkciu odosli_objednavku_email!
            - HNEĎ AKO MÁŠ VŠETKY ÚDAJE, spusti funkciu 'odosli_objednavku_email', ktorá odošle objednávku do bistra!
            """

        # 3. RAW_TORTY
        elif heslo == "RAW_TORTY":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: RAW TORTY (zloženie, alergény, ceny, objednávky)
            PRAVIDLÁ OBJEDNÁVOK:
            - Objednávky na raw torty prijímame najneskôr 24h vopred na tel. čísle: 0951 747 893.
            """

        # 4. INFO
        elif heslo == "INFO":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: INFORMÁCIE O BISTRE A BIO OBCHODE
            Lokalita: Vranov nad Topľou, za ČSOB. Adresa: Štúrova 99, 093 01 Vranov nad Topľou
            Otváracie hodiny: Po-Pi 8:00 - 16:00, So 10:00 - 12:00, Ne zatvorené. Mobil: 0951 747 893
            """

        # 5. PONUKA
        elif heslo == "PONUKA":
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: STÁLA PONUKA JEDÁL (MIMO OBEDOVÉHO MENU)
            Rozvoz na jedlá zo stálej ponuky zatiaľ nerobíme, možný je len osobný odber na 0951 747 893.
            """

        # 6. INE
        else:
            specific_prompt = """
            TVOJA AKTUÁLNA TÉMA: OTÁZKA MIMO PÔSOBNOSTI BISTRA
            Milo a slušne vysvetli zákazníkovi, že s tým mu nevieš pomôcť.
            """

        full_system_prompt = base_prompt + "\n" + specific_prompt
        full_conversation = [{"role": "system", "content": full_system_prompt}] + req.messages

        # --- PRVÉ VOLANIE OPENAI (s nastavenými tools) ---
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation,
            tools=tools if heslo == "OBJEDNAVKA_MENU" else None,
            tool_choice="auto" if heslo == "OBJEDNAVKA_MENU" else None,
            temperature=0.2
        )

        response_message = response.choices[0].message

        # --- AK AI ROZHODLA, ŽE MÁ SPUSŤIŤ FUNKCIU (MÁ VŠETKY ÚDAJE) ---
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "odosli_objednavku_email":
                    # Extrahujeme argumenty dodané modelom
                    args = json.loads(tool_call.function.arguments)
                    
                    # Spustíme našu Python funkciu
                    vysledok_odeslania = odosli_objednavku_email(
                        polozky=args.get("polozky"),
                        meno=args.get("meno"),
                        telefon=args.get("telefon"),
                        adresa=args.get("adresa"),
                        poznamka=args.get("poznamka", "Bez poznámky")
                    )

                    # Pridáme odpoveď z funkcie do histórie konverzácie
                    full_conversation.append(response_message)
                    full_conversation.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": vysledok_odeslania
                    })

                    # Druhé volanie OpenAI, aby zrekapitulovala výsledok pre zákazníka
                    second_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=full_conversation,
                        temperature=0.2
                    )
                    
                    reply = second_response.choices[0].message.content or ""
                    return {"odpoved": reply.replace("**", "")}

        # Ak funkcia nebola vyvolaná (bežná konverzácia alebo zber chýbajúcich údajov)
        reply = response_message.content or ""
        clean_reply = reply.replace("**", "")

        return {"odpoved": clean_reply}

    except Exception as e:
        print(f"[ERROR]: {str(e)}")
        return {"odpoved": "Ospravedlňujem sa, momentálne pripojenie trvá dlhšie ako zvyčajne. Skúste prosím otázku zopakovať."}