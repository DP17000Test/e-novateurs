#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze of CNIL resolutions -> LLM -> JSON file.
"""
import yaml
import json
import re
import sys
import os
import time
from typing import Dict, Any

import requests
from bs4 import BeautifulSoup

# ----- CONFIGURATION -----
HEADERS = {"User-Agent": "Mozilla/5.0"}
YAML_FILE = "../sources.yaml"
INPUT_FOLDER = "extracts"

# ----- CONFIGURATION -----
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")  # Clé depuis variable d'environnement

#MODEL_NAME= "mistral-large-latest"
MODEL = "open-mistral-nemo"  # Modèle free tier
API_URL = "https://api.mistral.ai/v1/chat/completions"
TIME_OUT = 120

# ---------------------------------------------------------------------
"""
Call Mistral with the appropriate prompt. Retries if time out.
"""
def call_mistral (resolution: str, authority: str, country: str, text_to_analyze: str, max_retries: int = 3) -> Dict[str, Any]:
    system_prompt = """
    Tu es un assistant spécialisé dans l'extraction d'informations structurées des extaits de délibération de la CNIL.
    Les extraits peuvent être en francais ou en anglais. Analyse la résolution suivante et extrais
    les informations demandées au format JSON.
    Si une information n'est pas présente, laisse la valeur vide (string vide ou null).
    Réponds UNIQUEMENT avec un tableau JSON valide, même s'il y a une seule sanction, sans texte supplémentaire avant ou après, 
    respectant exactement la structure suivante :
    {
      "source": 
      "country":
      "resolution":
      "company":
      "amount":
      "currency":
      "date":
    },
    ....
    
    Exemple de sortie attendue:
    {
      "source": "CNIL",
      "country": "FR",
      "resolution": "CNIL-O07"
      "company": "GOOGLE",
      "amount": "5000000",
      "currency": "euros",
      "date": "12/24/2022"
    }
    """

    user_prompt = """
    Règles à respecter impérativement :

    1. Ne considère que les délibérations qui sanctionne une ou plusieurs companies. Ignore les délibérations qui traitent
    de bilan d'activité, de rapport ou de cloture d'injonction.
    2. "company": indique le nom complet de la société tel qu'écrit dans le document. Si le nom n'est pas mentionné, laisse le champ vide.
    3. Si plusieurs sociétés sont mentionnées, créer un enregistrement pour chacune.
    4. "amount": indique le montant de la sanction en format float. 
        Par exemple, pour une sanction de deux millions tu écriras 2000000
    5. Si tu ne trouves pas de montant de sanction, ne crée pas d'enregistrement
    6. "currency": indique l'unité monétaire de la sanction (euros, dollars)
    7. "date": indique la date de la sanction au format yyyy/mm/dd
        Par exemple, pour une date "23 novembre 2024" tu écriras "2024/11/23"
        Si le document est en francais, pour une date "23/11/2024" tu écriras "2024/11/23" 
    """

    user_message = user_prompt + "\n"
    user_message += f"La valeur du champs 'source' sera toujours '{authority}' \n"
    user_message += f"La valeur du champs 'country' sera toujours {country}\n"
    user_message += f"La valeur du champs 'resolution' sera toujours {resolution}\n"
    user_message += "Voici le texte à analyser: \n"
    user_message += text_to_analyze

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message}
        ],
        "temperature": 0.1,
        "max_tokens": 2000
    }

    # Try to connect to Mistral AI
    for attempt in range(max_retries):

        try:
            response = requests.post(API_URL, headers=headers, json=payload, timeout=TIME_OUT)
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]

            # Extract JSON from the reply
            json_match = re.search(r"\{.*\}", content, re.DOTALL)

            if json_match:
                return json_match.group(0).strip()

            return None
        except requests.exceptions.Timeout:
            print(f"Timeout (attempt {attempt + 1}/{max_retries}). Retrying...")
            if attempt == max_retries - 1:
                return {"error": "Timeout despite multiple attempts"}
            time.sleep(5)  # Wait 5s before trying again
        
        except Exception as e:
            return {"error": f"API error: {e}"}

    return {"error": "Error accessing Nemo"}

# ---------------------------------------------------------------------

def main():

    with open(YAML_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get the archive to be scraped
    data = config ["countries"]["FR"]
    archive = data ["archive"]
    country = data ["country"]
    authority = data ["authority"]
    json_file = authority.lower() + ".json"

    session = requests.Session()

    print("Analyzing with Mistral...")
    all_json = []
    with os.scandir(INPUT_FOLDER) as es:
        for e in es:
            if e.is_file() and e.name.endswith('.txt'):
                with open(e.path, encoding='utf-8') as f:
                    resolution = f.read()
                resolution_nb = os.path.splitext(os.path.basename(e))[0]
                print (f"Processing {resolution_nb}")
                result = call_mistral (resolution_nb, authority, country, resolution)
                if result:
                    stripped = result.strip()
                    if not stripped.startswith("["):
                        stripped = "[" + stripped + "]"
                    parsed = json.loads(stripped)
                    all_json.extend(parsed)
                    
    # Write once, at the end
    with open(json_file, "w", encoding="utf-8") as f:
        json.dump(all_json, f, ensure_ascii=False, indent=2)                    
    print(f"Résultat sauvegardé dans {json_file}")

# ---------------------------------------------------------------------

if __name__ == "__main__":
    main()