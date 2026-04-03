import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, MessageHandler, filters, ContextTypes
import anthropic

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
MEMORY_FILE = "memory.json"
MONTHLY_LIMIT_EUR = 20.0
COST_PER_1K_INPUT = 0.003
COST_PER_1K_OUTPUT = 0.015

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

SYSTEM_PROMPT = """Du bist SB Assistent, ein persönlicher KI-Assistent für Sahin Güzel, Inhaber eines Bauunternehmens.

WICHTIGE REGELN:
- Antworte IMMER auf Deutsch, kurz und knapp
- Keine langen Erklärungen, nur das Wesentliche
- Nur detailliert wenn der Nutzer explizit darum bittet
- Gib direkte Antworten oder kurze Empfehlungen

GEDÄCHTNIS:
Du hast Zugriff auf ein Gedächtnis-System. Wenn du wichtige Infos bekommst (Mitarbeiter, Termine, Aufgaben, etc.), speichere sie mit dem Befehl: [SPEICHERN: kategorie | info]
Kategorien: mitarbeiter, samstage, baustellen, rechnungen, todos, erinnerungen, sonstiges

Beispiele:
- "Mehmet hat heute Samstag gearbeitet" → [SPEICHERN: samstage | Mehmet - Samstag {datum}]
- "Ruf morgen Giovanni an" → [SPEICHERN: erinnerungen | Anruf Giovanni - {datum+1}]

FÄHIGKEITEN:
- Mitarbeiter & Samstage tracken
- Rechnungen & Angebote erstellen
- To-Do Listen & Erinnerungen
- Fragen zu gespeicherten Daten beantworten
"""

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "mitarbeiter": [],
        "samstage": [],
        "baustellen": [],
        "rechnungen": [],
        "todos": [],
        "erinnerungen": [],
        "sonstiges": [],
        "kosten": {"monat": datetime.now().strftime("%Y-%m"), "gesamt_eur": 0.0}
    }

def save_memory(memory):
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(memory, f, ensure_ascii=False, indent=2)

def check_and_reset_costs(memory):
    current_month = datetime.now().strftime("%Y-%m")
    if memory["kosten"]["monat"] != current_month:
        memory["kosten"] = {"monat": current_month, "gesamt_eur": 0.0}
    return memory

def parse_and_save(response_text, memory):
    import re
    pattern = r'\[SPEICHERN:\s*(\w+)\s*\|\s*(.+?)\]'
    matches = re.findall(pattern, response_text)
    for kategorie, info in matches:
        kategorie = kategorie.lower().strip()
        info = info.strip()
        if kategorie in memory:
            entry = {"info": info, "datum": datetime.now().strftime("%d.%m.%Y %H:%M")}
            memory[kategorie].append(entry)
    clean_response = re.sub(pattern, '', response_text).strip()
    return clean_response, memory

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    memory = load_memory()
    memory = check_and_reset_costs(memory)
    
    # Kostenlimit prüfen
    if memory["kosten"]["gesamt_eur"] >= MONTHLY_LIMIT_EUR:
        await update.message.reply_text(
            f"⚠️ Monatliches Limit von {MONTHLY_LIMIT_EUR}€ erreicht. Bot pausiert bis nächsten Monat."
        )
        return

    user_message = update.message.text or ""
    
    # Gedächtnis als Kontext aufbereiten
    memory_context = "\n\nAKTUELLES GEDÄCHTNIS:\n"
    for kategorie, eintraege in memory.items():
        if kategorie == "kosten" or not eintraege:
            continue
        memory_context += f"\n{kategorie.upper()}:\n"
        for e in eintraege[-10:]:  # Nur letzte 10 Einträge
            memory_context += f"  - {e['info']} ({e['datum']})\n"
    
    memory_context += f"\nKOSTEN DIESEN MONAT: {memory['kosten']['gesamt_eur']:.2f}€ / {MONTHLY_LIMIT_EUR}€"

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1000,
            system=SYSTEM_PROMPT + memory_context,
            messages=[{"role": "user", "content": user_message}]
        )
        
        # Kosten berechnen
        input_tokens = response.usage.input_tokens
        output_tokens = response.usage.output_tokens
        kosten = (input_tokens / 1000 * COST_PER_1K_INPUT) + (output_tokens / 1000 * COST_PER_1K_OUTPUT)
        memory["kosten"]["gesamt_eur"] += kosten
        
        response_text = response.content[0].text
        clean_response, memory = parse_and_save(response_text, memory)
        
        save_memory(memory)
        await update.message.reply_text(clean_response)
        
    except Exception as e:
        logger.error(f"Fehler: {e}")
        await update.message.reply_text("Fehler aufgetreten. Bitte nochmal versuchen.")

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🎤 Sprachnachrichten folgen in einem Update. Bitte als Text schreiben.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    logger.info("SB Assistent gestartet...")
    app.run_polling()

if __name__ == "__main__":
    main()
