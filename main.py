import os
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# Globálna premenná pre uloženie dát zo všetkých podstránok webu
WEBSITE_DATA = ""

def scrape_vegnella():
    global WEBSITE_DATA
    
urls = [
        "https://vegnella.sk",
        "https://vegnella.sk/obedy",
        "https://vegnella.sk/denne-menu",
        "https://vegnella.sk/menu",
        "https://vegnella.sk/ponuka",
        "https://vegnella.sk/raw-torty",
        "https://vegnella.sk/kontakt"
    ]
    
    combined_text = ""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for url in urls:
        try:
            response = requests.get(url, headers=headers, timeout=8)
            # Oprava kódovania slovenčiny (diakritiky)
            response.encoding = 'utf-8'
            
            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                
                # Odstránime len neviditeľný kód (skripty a štýly)
                for script in soup(["script", "style"]):
                    script.extract()
                    
                text = soup.get_text(separator=' ', strip=True)
                if text:
                    combined_text += f"\n--- OBSAH Z PODSTRÁNKY: {url} ---\n{text}\n"
                print(f"✅ Načítaná adresa: {url} (dĺžka textu: {len(text)})")
            else:
                print(f"⚠️ Stránka {url} vrátila kód: {response.status_code}")
        except Exception as e:
            print(f"❌ Chyba pri sťahovaní {url}: {e}")

    WEBSITE_DATA = combined_text[:15000]
    print(f"🚀 Celkovo stiahnutých {len(WEBSITE_DATA)} znakov.")

# Načítame dáta hneď pri štarte aplikácie
scrape_vegnella()

class ChatRequest(BaseModel):
    messages: list

@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running"}

@app.get("/api/refresh")
def refresh_data():
    log = scrape_vegnella()
    return {
        "status": "Dáta boli obnovené!",
        "prehlad_stranok": log,
        "celkova_dlzka": len(WEBSITE_DATA),
        "nahlad": WEBSITE_DATA[:500]
    }

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        # Ak by bola pamäť náhodou prázdna, vynútime stiahnutie
        if not WEBSITE_DATA:
            scrape_vegnella()

        system_prompt = f"""
Si oficiálny, priateľský a nápomocný AI asistent pre bistro Vegnella.

AKTUÁLNE TEXTOVÉ DÁTA ZO VŠETKÝCH PODSTRÁNOK VEGNELLA.SK:
---
{WEBSITE_DATA}
---

PRAVIDLÁ A INŠTRUKCIE PRE ODPOVEĎ:
1. Ak sa zákazník pýta "aké je menu", "čo máte na obed", "aké sú jedlá" a pod., HNEĎ VYPIŠ konkrétne názvy polievok, hlavných jedál alebo ponuky, ktoré vidíš v texte vyššie!
2. NIKDY neodpovedaj len všeobecnými omáčkami typu "máme čerstvé a zdravé jedlá, pozrite na web". Daj zákazníkovi PRIAMO zoznam jedál z textu!
3. Odpovedaj VÝHRADNE na základe textu vyššie. Ak konkrétne informácie (napr. presné ingrediencie konkrétneho koláča) v texte chýbajú, zdvorilo to priznaj a nehalucinuj/nevymýšľaj si vlastné recepty.
4. Pri bežných pozdravoch alebo odpovediach typu "ok", "vďaka", "super" odpovedaj krátko, zdvorilo a bez opätovného vnucovania celého menu.
"""

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation
        )
        reply = response.choices[0].message.content
        return {"odpoved": reply}
    except Exception as e:
        return {"odpoved": f"Chyba na serveri: {str(e)}"}