import os
import sys
import yaml
import urllib.request
from datetime import datetime, timezone

BIOCYPHER_REPO = os.environ.get("BIOCYPHER_REPO_PATH")
if not BIOCYPHER_REPO:
    print("Error: BIOCYPHER_REPO_PATH environment variable not set.")
    sys.exit(1)

HSA_SCHEMA_PATH = os.path.join(BIOCYPHER_REPO, "config", "hsa", "hsa_schema_config.yaml")
BIOLINK_MODEL_URL = "https://raw.githubusercontent.com/biolink/biolink-model/master/biolink-model.yaml"
OUTPUT_METTA_PATH = os.path.join(os.path.dirname(__file__), "bio_rules.metta")

def load_yaml(path: str) -> dict:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading {path}: {e}")
        return {}

def fetch_biolink_model(url: str) -> dict:
    try:
        with urllib.request.urlopen(url) as response:
            content = response.read().decode('utf-8')
            return yaml.safe_load(content)
    except Exception as e:
        print(f"Error fetching Biolink model: {e}")
        return {}

def extract_active_predicates(schema: dict) -> set:
    predicates = set()
    for key, value in schema.items():
        if isinstance(value, dict) and value.get("represented_as") == "edge":
            pred = value.get("biolink_predicate")
            if pred:
                predicates.add(pred.replace("biolink:", ""))
    return predicates

def get_property(slot_name: str, prop: str, slots: dict) -> any:
    current = slot_name
    visited = set()
    while current and current not in visited:
        visited.add(current)
        slot = slots.get(current)
        if not slot:
            break
        if prop in slot:
            return slot[prop]
        current = slot.get("is_a")
    return None

def parse_biolink_slots(biolink_model: dict) -> dict:
    return biolink_model.get("slots", {})

def generate_metta_rules(active_preds: set, slots: dict) -> list:
    rules = [
        "; Bio-Claw Axioms (Auto-Generated)",
        f"; Generated at: {datetime.now(timezone.utc).isoformat()}",
        ""
    ]
    
    for pred in sorted(active_preds):
        slot = slots.get(pred)
        if not slot:
            continue
            
        is_transitive = get_property(pred, "transitive", slots)
        is_symmetric = get_property(pred, "symmetric", slots)
        inverse_pred = get_property(pred, "inverse", slots)
        
        if not (is_transitive or is_symmetric or inverse_pred):
            continue

        rules.append(f"; biolink:{pred}")
        
        if is_transitive:
            rules.append(f"(Inheritance biolink:{pred} biolink:{pred})")
            
        if is_symmetric:
            rules.append(f"(Similarity biolink:{pred} biolink:{pred})")
            
        if inverse_pred:
            rules.append(f"(= (biolink:{pred} $a $b) (biolink:{inverse_pred} $b $a))")
            
        rules.append("")
        
    return rules

def main():
    schema = load_yaml(HSA_SCHEMA_PATH)
    if not schema:
        sys.exit(1)
        
    biolink_model = fetch_biolink_model(BIOLINK_MODEL_URL)
    if not biolink_model:
        sys.exit(1)
        
    active_preds = extract_active_predicates(schema)
    slots = parse_biolink_slots(biolink_model)
    rules = generate_metta_rules(active_preds, slots)
    
    with open(OUTPUT_METTA_PATH, 'w', encoding='utf-8') as f:
        f.write("\n".join(rules))

if __name__ == "__main__":
    main()
