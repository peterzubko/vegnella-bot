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

# Globálna premenná pre uloženie dát z webu
WEBSITE_DATA = ""

def scrape_vegnella():
    global WEBSITE_DATA
    try:
        url = "https://vegnella.sk"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(url, headers=headers, timeout=10)
        
        if response.status_code == 200:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Vyčistíme text od skriptov a štýlov
            for script in soup(["script", "style"]):
                script.extract()
            text = soup.get_text(separator=' ', strip=True)
            WEBSITE_DATA = text[:4000] # Uložíme podstatnú časť textu z webu
            print("✅ Úspešne stiahnuté dáta z vegnella.sk")
        else:
            print(f"⚠️ Nepodarilo sa načítat web, kód: {response.status_code}")
    except Exception as e:
        print(f"❌ Chyba pri sťahovaní webu: {e}")

# Načítame dáta hneď pri spustení
scrape_vegnella()

class ChatRequest(BaseModel):
    messages: list

@app.get("/")
def home():
    return {"status": "Vegnella AI Bot running"}

@app.get("/api/refresh")
def refresh_data():
    scrape_vegnella()
    return {"status": "Dáta z vegnella.sk boli obnovené!", "preview": WEBSITE_DATA[:200]}

@app.post("/api/chat")
async def chat(req: ChatRequest):
    try:
        # Ak sú dáta prázdne, skúsim ich dočítať
        if not WEBSITE_DATA:
            scrape_vegnella()

        system_prompt = f"""
Si priateľský, prirodzený a nápomocný AI asistent pre bistro Vegnella.
Tvojou úlohou je pomáhať zákazníkom s otázkami ohľadom denného menu, ponuky, otváracích hodín a reštaurácie.

AKTUÁLNE INFORMÁCIE Z WEBU VEGNELLA.SK:
---
{WEBSITE_DATA}
---

STRIKTNÉ PRAVIDLÁ PRE ODPOVEDE:
1. Odpovedaj VÝHRADNE na základe textu z webu vyššie.
2. NIKDY SI NEVYMÝŠĽAJ ingrediencie, zloženie jedál, špeciálne ponuky ani konkrétne recepty, ak nie sú doslovne uvedené v textových dátach z webu!
3. Ak sa zákazník spýta na presné zloženie alebo ingrediencie, ktoré na webe nie sú napísané, premyslene a zdvorilo priznaj: "Presné zloženie/ingrediencie na webe uvedené nemáme, ale rád ti o tom zistím viac priamo v bistre."
4. Reaguj prirodzene a kontextuálne. Ak zákazník napíše iba "aha ok", "ďakujem" a pod., odpovedz krátko a zdvorilo.
"""

        full_conversation = [{"role": "system", "content": system_prompt}] + req.messages

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=full_conversation
        )
        reply = response.choices[0].message.content
        return {"odpoved": reply}
    except Exception as e:
        return {"odpoved": f"Chyba: {str(e)}"}