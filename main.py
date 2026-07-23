import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI

# 1. Vytvorenie FastAPI aplikácie
app = FastAPI(title="Vegnella Bot")

# 2. Nastavenie CORS (povolenie komunikácie s webstránkou)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. OpenAI Klient
client = OpenAI()

# 4. Denné menu bistra Vegnella
DENNE_MENU = """
PONDELOK:
- Polievka: Hráškový krém s mätou
- Hlavné jedlo: Vegánske lasagne so špenátom

UTOROK:
- Polievka: Paradajková s bazalkou
- Hlavné jedlo: Cícerové curry s ryžou

STREDA:
- Polievka: Šošovicová kyslá
- Hlavné jedlo: Vegánsky burger s hranolkami

ŠTVRTOK:
- Polievka: Hlivová gulašovka
- Hlavné jedlo: Tofu poke bowl

PIATOK:
- Polievka: Tekvicový krém
- Hlavné jedlo: Pad Thai rezance s tofu

Cena menu: 7,90 € | Výdaj od 11:00 do 1:00 alebo do vypredania.
"""

# 5. System Prompt (inštrukcie a mantinely pre AI)
SYSTEM_PROMPT = f"""
Si milý a ochotný asistent pre vegánske bistro Vegnella (vegnella.sk).
Tvoja JEDINÁ úloha je odpovedať zákazníkom na otázky ohľadom denného menu a bistra.

AKTUÁLNE MENU A INFO O BISTRE:
{DENNE_MENU}

Otváracie hodiny: Pondelok - Piatok od 08:00 do 17:00.

PRAVIDLÁ:
1. Odpovedaj stručne, milo a v slovenčine s použitím emodži 🌿.
2. Ak sa pýtajú na dnešné menu, pozri sa, aký je dnes deň v týždni, a vypíš len menu pre ten konkrétny deň.
3. Ak sa pýtajú na menu na celý týždeň, vypíš kompletne celý týždeň.
4. Ak sa pýtajú na akékoľvek iné témy (počasie, politika, vtipy...), zdvorilo ich odmietni:
   "Ospravedlňujem sa, ale som asistent bistra Vegnella a viem vám pomôcť len s ponukou nášho menu! 🌿"
"""

class SpravaRequest(BaseModel):
    text: str

# 6. API Endpoint, ktorý prijíma správu z chatu
@app.post("/api/chat")
async def chat_endpoint(data: SpravaRequest):
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": data.text}
            ],
            temperature=0.3
        )
        odpoved = response.choices[0].message.content
        return {"odpoved": odpoved}
    except Exception as e:
        print(f"Chyba pri komunikácii s OpenAI: {e}")
        return {"odpoved": "Ospravedlňujem sa, momentálne sa mi nedá spojiť s databázou menu."}