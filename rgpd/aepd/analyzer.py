#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Analyze of AED resolutions -> LLM -> JSON file.
Note: the program saves all new json object created at a frequency json_save_freq with the last object
      added being displayed. 
      In case of error... re-run the program starting at the extract next to the last one saved.
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
MODEL_NAME = "open-mistral-nemo"  # Modèle free tier

API_URL = "https://api.mistral.ai/v1/chat/completions"
TIME_OUT = 120

# ---------------------------------------------------------------------
"""
Call Mistral with the appropriate prompt. Retries if time out.
"""
def call_mistral (resolution: str, authority: str, country: str, text_to_analyze: str, max_retries: int = 3) -> Dict[str, Any]:
    system_prompt = """
    Tu es un assistant spécialisé dans l'extraction d'informations structurées des extaits des résolutions de l'AEPD  
    (Agence Espagnole de Protection des Données). 
    Les extraits sont en espagnol ou en anglais. Analyse la résolution suivante et extrais
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
      "source": "AEPD",
      "country": "SP",
      "resolution": "PS-00042-2007"
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
    6. "currency": indique l'unité monétaire de la sanction (euros, dollars) quand il y en a une
    6. "date": indique la date de la sanction au format yyyy/mm/dd quand il y en a une
        Par exemple, pour une date "23 novembre 2024" tu écriras "2024/11/23"
        Si le document est en francais, pour une date "23/11/2024" tu écriras "2024/11/23" 
    """

    user_message = user_prompt + "\n"
    user_message += f"La valeur du champs 'source' sera toujours '{authority}' \n"
    user_message += f"La valeur du champs 'country' sera toujours {country}\n"
    user_message += f"La valeur du champs 'resolution' sera toujours {resolution}\n"
    user_message += f"La valeur du champs 'date' est indiqué dans les lignes ==== PAGE x DATE xxxx - xx - xx ===="
    user_message += "Voici le texte à analyser: \n"
    user_message += text_to_analyze

    headers = {
        "Authorization": f"Bearer {MISTRAL_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": MODEL_NAME,
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

            print ("no JSON created.")
            return None
        except requests.exceptions.Timeout:
            print(f"Timeout (attempt {attempt + 1}/{max_retries}). Retrying...")
            if attempt == max_retries - 1:
                return {"error": "Timeout despite multiple attempts"}
            time.sleep(5)  # Wait 5s before trying again
        
        except Exception as e:
            return {"error": f"API error: {e}"}

    return {"error": "Error accessing Nemo"}

"""Add json records not saved yet."""
def save_new_json (all_json, last_saved, output_file):
    with open(output_file, "a", encoding="utf-8") as f:
        for record in all_json[last_saved:]:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    if all_json:
        print("Last record saved:")
        print(json.dumps(all_json[-1], ensure_ascii=False, indent=2))

    return len(all_json)  # nouveau last_saved
# ---------------------------------------------------------------------

def main():

    with open(YAML_FILE, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Get the archive to be scraped
    data = config ["countries"]["ES"]
    archive = data ["archive"]
    country = data ["country"]
    authority = data ["authority"]
    json_file = authority.lower() + ".json"
    session = requests.Session()

    json_save_freq = 20     # Save frequency of json objects
    last_saved_index = 0    # index of last saved json object

    start_file = None
    end_file = None
    # Get parameters if any
    if len(sys.argv) >= 2:
        start_file = str(sys.argv[1]) + ".txt"

    if len(sys.argv) >= 3:
        end_file = str(sys.argv[2]) + ".txt"

    # Get all files to be processed
    path = "./" + INPUT_FOLDER
    all_files = [f for f in os.listdir(path) 
                if os.path.isfile(os.path.join(path, f))]
    
    # Sort by name
    all_files_sorted = sorted(all_files)
    #start_file = "PS-00109-2018.txt"
    #end_file = "PS-00109-2024.txt"

    print("Analyzing with Mistral ...")
    all_json = []
    for fi in all_files_sorted:
        if start_file is not None and fi < start_file:
            continue
        if end_file is not None and fi > end_file:
            break
        if fi.endswith('.txt'):
            file_name = path + "/" + fi
            resolution_nb = os.path.splitext(os.path.basename(file_name))[0]
            print (f"Processing {resolution_nb}")
            with open(file_name, encoding='utf-8') as f:
                resolution = f.read()
                result = call_mistral (resolution_nb, authority, country, resolution)
                if result:
                    # For some result, result comes back as a dict sometimes
                    try:
                        stripped = result.strip()
                    except Exception as e:
                        last_saved_index = save_new_json (all_json, last_saved_index, json_file)
                        print (f"stripping result error : {e}\n on: {resolution_nb}")
                        print (f"result = {result}")
                        print ("Program stop.")
                        sys.exit ()

                    if not stripped.startswith("["):
                        stripped = "[" + stripped + "]"
                    parsed = json.loads(stripped)
                    all_json.extend(parsed)
                    if len(all_json) - last_saved_index >= json_save_freq:
                        last_saved_index = save_new_json (all_json, last_saved_index, json_file)

    # Write the remaining at the end
    last_saved_index = save_new_json (all_json, last_saved_index, json_file)
    print(f"Résultat sauvegardé dans {json_file}")

# ---------------------------------------------------------------------

if __name__ == "__main__":
    main()