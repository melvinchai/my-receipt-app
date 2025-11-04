import pandas as pd

class RuleLoader:
    def __init__(self, excel_path="parsing_rules.xlsx"):
        self.excel_path = excel_path
        try:
            self.df = pd.read_excel(self.excel_path)
        except Exception as e:
            raise ValueError(f"Failed to load parsing rules: {e}")

    def get_supported_insurers(self):
        """Return a sorted list of all supported insurers."""
        return sorted(self.df["Insurer"].dropna().unique())

    def validate_insurer(self, insurer_name):
        """Check if the insurer is supported."""
        return insurer_name.lower() in [i.lower() for i in self.df["Insurer"].dropna().unique()]

    def get_rules_for_insurer(self, insurer_name):
        """Return all parsing rules for a given insurer."""
        rules = self.df[self.df["Insurer"].str.lower() == insurer_name.lower()]
        if rules.empty:
            return None
        return rules.to_dict(orient="records")
