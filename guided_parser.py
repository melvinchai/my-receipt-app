import re
from rule_loader import RuleLoader

class GuidedParser:
    def __init__(self, ocr_text, insurer_name, rule_loader: RuleLoader):
        self.lines = [line.strip() for line in ocr_text.split("\n") if line.strip()]
        self.insurer = insurer_name
        self.rules = rule_loader.get_rules_for_insurer(insurer_name)

    def extract_fields(self):
        if not self.rules:
            return {"error": f"Insurer '{self.insurer}' not supported."}

        results = {}
        for rule in self.rules:
            field = rule["Field"]
            anchor = rule["Anchor Phrase"]
            pattern = rule["Regex Pattern"]
            notes = rule.get("Notes", "")

            value = self.extract_from_lines(anchor, pattern)
            results[field] = {
                "value": value,
                "source": anchor,
                "notes": notes
            }
        return results

    def extract_from_lines(self, anchor, pattern):
        for line in self.lines:
            if anchor.lower() in line.lower():
                match = re.search(pattern, line)
                return match.group() if match else line
        return None
