from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data/prepared"
POLICY = "fixed-km-1"
SOURCE_REVISION = "0f3663e31ea6610eb2a00256ca0d984ebc7c586b"
MODELS = {"ALD": "Alder Compact", "BIR": "Birch Sedan", "CED": "Cedar SUV", "ELM": "Elm Van"}
