import os
import time
import json
import asyncio
import requests
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from contextlib import asynccontextmanager

# Globálna premenná pre dynamické obedové menu
DAILY_MENU_DATA = ""

# --- STATICKÉ INFORMÁCIE O BISTRE ---
STATIC_INFO = """
GENERAL INFO:
Obedové menu
Varíme pre vás čerstvé, zdravé a chutné špeciality. Špecializujeme sa na vegetariánske/vegánske jedlá. Bez aditív, dochucovadiel a iných chemikálií. U nás len čistá príroda. Naše jedlá vám zabezpečia dostatok všetkých živín dôležitých pre organizmus a udržia vám zdravie, mladosť a vitalitu po dlhý čas.
Príďte si k nám na kávičku alebo latté so zdravým dezertom alebo si vyberte z našej ponuky jedál.
Raw Torty na objednávku
Na rozdiel od tradičných zákuskov, naše raw torty nevyžadujú pečenie a neobsahujú lepok, vajcia, mliečne výrobky a rafinované cukry. Namiesto toho obsahujú iba celé, prírodné, rastlinné a nespracované zložky, ako sú orechy, semená, ovocie, superpotraviny, nerafinované sladidlá a panenské oleje. Torty dodávame na podnose zabalené v krabici.
Predajňa prírodných produktov
Nájdete u nás aj široký výber zdravých potravín, prírodné a kvalitné doplnky výživy, drogériu a kozmetiku a veľa ďalších produktov pre zdravý život.

OBEDOVÉ MENU:
Objednávky na donášku prijímame od 8:00h do 10:00h. Rozvoz menu prebieha v čase 11:00h - 13:00h.
Cena MENU (hlavné jedlo + polievka) je 8,40€. Polievka samostatne 2,20€.
ZĽAVA pri objednávke minimálne 3 MENU platíte za každé iba 7,40€. Rovnaká cena ak si predobjednáte na celý týždeň.
Menu podávame v čase 11:00h - 13:00h alebo do vypredania.
Jedlo si môžete aj telefonicky rezervovať alebo vám ho môžeme zabaliť a pripraviť na dohodnutý čas pre osobné vyzdvihnutie od 11:00h do 16:00h (0951 747 893).
EKO obaly na obedové menu a stálu ponuku sú za príplatok 0,50€ (veľký) a 0,30€ (malý - polievka). Môžete priniesť aj svoje vlastné obaly.

PONUKA STÁLYCH JEDÁL:
Počas obedov môže byť príprava niektorých jedál dlhšia ako obyčajne
EKO obal na jedlo je za príplatok 0,50€
Vegan Mac and Cheese (8,60€, 450g)
Vyprážaný syr, hranolky, zelenina, dresing (8,60€, 400g)
Vegan burger (8,50€, 350g)
Teriyaki tofu miska (9,50€, 450g)
Vegan Wrap (7,90€, 400g)
Dezerty (od 2,90€)

RAW TORTY PONUKA (na objednávku):
Snickers (1000g | 38,00€)
Raffaello (1000g | 36,00€)
Jahoda (1000g | 38,00€)
Slaný Karamel (1000g | 36,00€)
Čokoláda (1000g | 36,00€)
Lemon & Matcha (1000g | 36,00€)
Skladovanie: v chladničke (4-8°C) vydržia 4 dni, v mrazničke 3 mesiace.

KONTAKT A ADRESA:
Lokalita: Štúrova 99, 093 01 Vranov nad Topľou (za ČSOB, 20m od hlavného chodníka)
Otváracie hodiny: Po - Pi: 8:00 - 16:00, So: 10:00 - 12:00, Ne: zatvorené
Mobil pre objednávky a informácie: 0951 747 893
E-mail: vegnella@vegnella.sk
"""

# --- POMOCNÁ FUNKCIA: ODOSLANIE E-MAILU S OBJEDNÁVKOU ---
def send_order_email(meno: str, telefon: str, adresa: str, pocet_ks_menu: int, poznamka: str = "") -> bool:
    """
    Odošle e-mail s detailmi objednávky na vegnella pomocou SMTP.
    """
    smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
    smtp_port = int(os.environ.get("SMTP_PORT", 587))
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if not smtp_user or not smtp_password:
        print("[ERROR] Chýbajú SMTP prihlasovacie údaje v os.environ!")
        return False

    msg = MIMEMultipart()
    msg['From'] = smtp_user
    msg['To'] = "postmaster@vegnella.sk"
    msg['Subject'] = f"Nová objednávka DONÁŠKY ({pocet_ks_menu}x Menu) - {meno}"

    text_poznamka = poznamka if poznamka else "Bez poznámky"

    body = f"""
    NOVÁ OBJEDNÁVKA CEZ AI CHATBOT:
    ----------------------------------
    Meno zákazníka: {meno}
    Telefónne číslo: {telefon}
    Adresa doručenia: {adresa}
    Počet kusov menu: {pocet_ks_menu}
    Poznámka: {text_poznamka}
    ----------------------------------
    Čas prijatia: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}
    """
    msg.attach(MIMEText(body, 'plain', 'utf-8'))

    try:
        server = smtplib.SMTP(smtp_server, smtp_port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.send_message(msg)
        server.quit()
        print(f"[SUCCESS] E-mail s objednávkou pre {meno} ({pocet_ks_menu}x menu) bol úspešne odoslaný.")
        return True
    except Exception as e:
        print(f"[ERROR] Zlyhalo odosielanie e-mailu: {str(e)}")
        return False

# --- 1. TARGETING SCRAPING ---
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
        response = requests.get(fresh_url, headers=headers, timeout=5, allow_redirects=True)
        response.encoding = 'utf-8'
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            for script in soup(["script", "style"]):
                script.extract()
            
            text = soup.get_text(separator='\n', strip=True)
            if len(text) > 50:
                DAILY_MENU_DATA = text[:4000]
                print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Obedové menu obnovené.")
                return ["OK: Menu obnovené"]
    except Exception as e:
        print(f"[CHYBA] Scraping zlyhal: {str(e)}")
    
    return ["ZLYHALO: Menu sa nepodarilo obnoviť"]

async def async_scrape_menu():
    return await asyncio.to_thread(sync_scrape_menu_only)

@asynccontextmanager
async def lifespan(app: FastAPI):
    await async_scrape_menu()
    scheduler = BackgroundScheduler(timezone="Europe/Bratislava")
    scheduler.add_job(sync_scrape_menu_only, trigger='cron', day_of_week='mon-fri', hour=7, minute=0)
    scheduler.start()
    yield
    scheduler.shutdown()

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

@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running"}

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
        
        dni_sk = {
            'Monday': 'Pondelok', 'Tuesday': 'Utorok', 'Wednesday': 'Streda',
            'Thursday': 'Štvrtok', 'Friday': 'Piatok', 'Saturday': 'Sobota', 'Sunday': 'Nedeľa'
        }
        day_en = now.strftime("%A")
        day_sk = dni_sk.get(day_en, day_en)
        current_time_str = f"{day_sk}, {now.strftime('%d.%m.%Y %H:%M hodín')}"

        # Výpočet pracovného dňa a časového okna pre donášku
        is_workday = now.weekday() < 5  # 0=Pondelok až 4=Piatok
        is_delivery_open = is_workday and (8 <= now.hour < 10)
        
        delivery_status_str = "OTVORENÉ (Možné prijímať objednávky na donášku)" if is_delivery_open else "ZATVORENÉ (Momentálne nie je možné objednať donášku)"

        days_ahead = (0 - now.weekday()) % 7
        if days_ahead == 0 and now.hour >= 16:
            days_ahead = 7
        elif day_en in ['Saturday', 'Sunday']:
            days_ahead = (7 - now.weekday()) % 7
            
        next_monday_date = (now + timedelta(days=days_ahead)).strftime("%d.%m.%Y")

        # OBNOVENÝ SYSTEM PROMPT SO VŠETKÝMI TVOJIMI INŠTRUKCIAMI
        system_prompt = f"""
AKTUÁLNY REÁLNY ČAS V BRATISLAVE: {current_time_str}
DÁTUM NAJBLIŽŠIEHO PONDELKA: {next_monday_date}
STAV PRÍJMU OBJEDNÁVOK NA DONÁŠKU OBEDOVÉHO MENU: {delivery_status_str}

FORMÁTOVANIE: ZÁKAZ Markdown hviezdičiek (**text**) aj mriežok (#). Píš čistý text! Pre odrážky používaj výhradne pomlčky (-).

Si oficiálny, priateľský a nápomocný AI asistent pre bistro a bio obchod Vegnella.

TVOJA ÚLOHA:
- Poskytovanie všeobecných informácií výhradne ohľadom bistra a bio obchodu Vegnella.
  Tu je zahrnuté: info o dennom menu, adresa, otváracie hodiny, kontakt, info o ponuke jedál, info o raw tortách a predajni prírodných produktov a informácie ohľadom objednávok.
- Zariadenie objednávok pre donášku obedového menu.
- Akékoľvek iné činnosti striktne zakázané. 

INŠTRUKCIE pre objednávky denného menu na donášku:
- Objednávky na donášku môžeš prijať iba v čase, kedy je STAV PRÍJMU OBJEDNÁVOK: OTVORENÉ (od 8:00h do 10:00h a iba každý pracovný deň).
- Ak je STAV PRÍJMU OBJEDNÁVOK: ZATVORENÉ, zdvorilo vysvetli, že to momentálne nie je možné a povedz, kedy najbližšie je to možné (v najbližší pracovný deň ráno od 08:00 do 10:00).
- Ak je STAV 'OTVORENÉ', pre úspešnú objednávku donášky musíte od zákazníka zozbierať tieto údaje:
  a) Počet kusov obedového menu (pocet_ks_menu)
  b) Meno a priezvisko (meno)
  c) Adresu doručenia (adresa)
  d) Telefónne číslo (telefon)
  Taktiež sa spýtaj, či má zákazník nejakú voliteľnú poznámku (poznamka).
  AKONÁHLE MÁŠ VŠETKY POVINNÉ ÚDAJE, zavolaj nástroj `odeslat_objednavku_emailom` a až po jeho úspešnom zavolaní potvrdzuj objednávku zákazníkovi!

Inštrukcie pre informácie ohľadom iných objednávok:
- Najskor musíš overiť, čo chce zákazník objednať. MENU(donáška,osobne)/RAW TORTA/JEDLO Z PONUKY
- MENU pre osobné vyzdvihnutie: možné objednať, poskytni kontakt na telefónne číslo 0951 747 893. Ale výlučne len v pracovné dni v čase 8:00h - 10:00h.
- MENU donáška: (použi osobitné informácie vyššie)
- RAW TORTA: možné objednať, poskytni kontakt na telefónne číslo 0951 747 893. Ale výlučne počas otváracích hodín aj v sobotu (vopred min. 24h).
- Jedlo zo stálej ponuky: možné objednať ale len osobné vyzdvihnutie, poskytni kontakt na telefónne číslo 0951 747 893. Ale výlučne počas otváracích hodín a len v pracovné dni.
- Ak chcú objednať mimo časového okna pre objednávky povedz, že to momentálne nieje možné. A povedz kedy najbližšie je to možné.

VŠEOBECNÉ PRAVIDLÁ SPRÁVANIA:
- Dbaj na časové okná pre správne informácie. 
- Ak sa niekto spýta na budúce menu, skontroluj dátum pri menu dátach, ak je tam staré menu, povedz, že nové menu bude k dispozícii od najbližšieho pondelka.
- ZÁKAZ VYMÝŠĽANIA: Drž sa výhradne faktov z týchto inštrukcií a dodaných dát z webu.
- TÉMA KONVERZÁCIE: Odpovedaj výlučne ohľadom bistra a bio obchodu Vegnella. Iné témy zdvorilo odmietni.
- Ak nevieš odpovedať, a zvážiš že by si mohol vymyslieť odpoveď, radšej povedz, že nevieš a odporuč kontaktovať priamo bistro ale iba v prípade, že zvážis že je to pre bistro relevantné a dôležité.

STATICKÉ INFORMÁCIE O BISTRE:
--------------------------------------------------
{STATIC_INFO}
--------------------------------------------------

AKTUÁLNE STIAHNUTÉ OBEDOVÉ MENU Z WEBU:
--------------------------------------------------
{DAILY_MENU_DATA}
--------------------------------------------------
"""

        # Definícia nástrojov pre OpenAI (Function Calling)
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "odeslat_objednavku_emailom",
                    "description": "Odošle potvrdenú objednávku donášky obedového menu na e-mail bistra.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "meno": {"type": "string", "description": "Meno a priezvisko zákazníka"},
                            "telefon": {"type": "string", "description": "Telefónne číslo zákazníka"},
                            "adresa": {"type": "string", "description": "Adresa doručenia"},
                            "pocet_ks_menu": {"type": "integer", "description": "Počet kusov obedového menu"},
                            "poznamka": {"type": "string", "description": "Voliteľná poznámka k objednávke (napr. poschodie, bez cibule)"}
                        },
                        "required": ["meno", "telefon", "adresa", "pocet_ks_menu"]
                    }
                }
            }
        ]

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation,
            tools=tools,
            tool_choice="auto",
            timeout=10.0
        )

        response_message = response.choices[0].message

        # Ak AI vyhodnotila, že má všetky údaje a zavolala funkciu odoslania e-mailu:
        if response_message.tool_calls:
            for tool_call in response_message.tool_calls:
                if tool_call.function.name == "odeslat_objednavku_emailom":
                    args = json.loads(tool_call.function.arguments)
                    
                    email_success = send_order_email(
                        meno=args.get("meno"),
                        telefon=args.get("telefon"),
                        adresa=args.get("adresa"),
                        pocet_ks_menu=args.get("pocet_ks_menu"),
                        poznamka=args.get("poznamka", "")
                    )

                    full_conversation.append(response_message)
                    full_conversation.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"status": "SUCCESS" if email_success else "FAILED"})
                    })

                    second_response = client.chat.completions.create(
                        model="gpt-4o-mini",
                        messages=full_conversation
                    )
                    reply = second_response.choices[0].message.content or ""
                    clean_reply = reply.replace("**", "")
                    return {"odpoved": clean_reply}

        reply = response_message.content or ""
        clean_reply = reply.replace("**", "")
        return {"odpoved": clean_reply}

    except Exception as e:
        print(f"[ERROR] Chyba pri spracovaní chatu: {str(e)}")
        return {"odpoved": "Ospravedlňujem sa, momentálne pripojenie trvá dlhšie ako zvyčajne. Skúste prosím otázku zopakovať."}