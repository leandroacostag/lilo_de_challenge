import json
import re
from pathlib import Path

from rapidfuzz import fuzz, process

from config import get_settings
from models.product import NormalizedProduct, Product, TextField


class ProductNormalizer:
    """
    Normalizes raw product data using fuzzy matching for attribute keys.

    Uses rapidfuzz to match typo-ridden attribute keys to canonical names,
    eliminating the need to manually map every possible typo variation.
    """

    def __init__(self):
        settings = get_settings()
        self._data_path = Path(settings.data_path)

        # Load normalizer config
        config = self._load_config()
        # Key aliases for common variations (e.g., "colour" -> "color")
        # These are optional hints - unknown keys will be normalized automatically
        self.key_aliases = config.get("attribute_key_aliases", {})
        self.fuzzy_threshold = config.get("fuzzy_match_threshold", 80)
        self.unit_mapping = config.get("unit_mapping", {})
        self.weight_to_kg = config.get("weight_to_kg", {})
        self.junk_patterns = config.get("junk_patterns", [])
        self.bulk_quantity_words = config.get("bulk_quantity_words", {})

        # Load data files
        self.synonyms = self._load_synonyms(self._data_path / "synonyms.json")
        self.category_mapping = self._load_category_mapping(
            self._data_path / "categories.json"
        )

    def _load_config(self) -> dict:
        """Load normalizer configuration from JSON file."""
        config_path = Path(__file__).parent.parent / "config" / "normalizer.json"
        with open(config_path) as f:
            config = json.load(f)
        config.pop("$comment", None)
        return config

    def _load_synonyms(self, path: Path) -> dict[str, str]:
        """Load synonyms and create bidirectional mapping."""
        synonyms = {}
        if path.exists():
            with open(path) as f:
                pairs = json.load(f)
                for pair in pairs:
                    if len(pair) == 2:
                        synonyms[pair[0].lower()] = pair[0].lower()
                        synonyms[pair[1].lower()] = pair[0].lower()
        return synonyms

    def _load_category_mapping(self, path: Path) -> dict[str, str]:
        """Load category mapping from messy to clean."""
        mapping = {}
        if path.exists():
            with open(path) as f:
                data = json.load(f)
                clean_categories = data.get("clean", [])
                messy_categories = data.get("messy", [])

                for clean in clean_categories:
                    normalized = self._normalize_category_for_matching(clean)
                    mapping[normalized] = clean

                for messy in messy_categories:
                    normalized = self._normalize_category_for_matching(messy)
                    if normalized not in mapping:
                        best_match = self._find_best_category_match(
                            messy, clean_categories
                        )
                        if best_match:
                            mapping[normalized] = best_match
        return mapping

    def _normalize_category_for_matching(self, category: str) -> str:
        """Normalize category string for matching purposes."""
        normalized = re.sub(r"\s*>\s*", ">", category.lower())
        normalized = re.sub(r">+", ">", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized

    def _find_best_category_match(
        self, messy: str, clean_categories: list[str]
    ) -> str | None:
        """Find the best matching clean category using fuzzy matching."""
        if not clean_categories:
            return None

        # Use rapidfuzz to find best match
        result = process.extractOne(
            messy.lower(),
            [c.lower() for c in clean_categories],
            scorer=fuzz.token_sort_ratio,
        )

        if result and result[1] >= 60:  # 60% threshold for categories
            # Find original case version
            idx = [c.lower() for c in clean_categories].index(result[0])
            return clean_categories[idx]

        return None

    def _normalize_attribute_key(self, key: str) -> str:
        """
        Normalize an attribute key to a consistent format.

        Strategy:
        1. Check aliases for common variations (e.g., "colour" -> "color")
        2. Normalize the key: lowercase, replace spaces/hyphens with underscores
        3. All attributes are kept as-is - no hardcoded canonical list

        This allows the system to handle any attributes dynamically without
        requiring a predefined list.

        Args:
            key: Raw attribute key from product data

        Returns:
            Normalized attribute key
        """
        key_lower = key.lower().strip()

        # Check aliases first (optional hints for common variations)
        if key_lower in self.key_aliases:
            return self.key_aliases[key_lower]
        if key in self.key_aliases:
            return self.key_aliases[key]

        # Normalize: lowercase, replace spaces/hyphens with underscores
        # Remove any special characters that aren't alphanumeric or underscore
        normalized = re.sub(r"[^\w]", "_", key_lower)
        # Collapse multiple underscores
        normalized = re.sub(r"_+", "_", normalized)
        # Remove leading/trailing underscores
        normalized = normalized.strip("_")

        return normalized if normalized else key_lower

    def normalize(self, product: Product) -> NormalizedProduct:
        """Normalize a raw product into a clean, searchable format."""
        category_path, levels = self._parse_category(product.category)
        weights = self._convert_weights(product.unit_of_measure)
        attributes, attributes_search = self._normalize_attributes(
            product.attributes or {}
        )

        return NormalizedProduct(
            id=product.id,
            sku=product.sku,
            vendor=TextField(
                raw=product.vendor,
                value=product.vendor.lower().strip() if product.vendor else None,
            ),
            title=TextField(
                raw=product.title,
                value=self._clean_text(product.title),
            ),
            description=TextField(
                raw=product.description,
                value=self._clean_text(product.description)
                if product.description
                else None,
            ),
            unit_of_measure=self._normalize_unit(product.unit_of_measure),
            weight_kg=weights["kg"],
            weight_g=weights["g"],
            weight_lb=weights["lb"],
            weight_oz=weights["oz"],
            category=category_path,
            category_level1=levels.get("level1"),
            category_level2=levels.get("level2"),
            category_level3=levels.get("level3"),
            attributes=attributes,
            attributes_search=attributes_search,
            region_availability=product.region_availability,
            supplier_rating=product.supplier_rating,
            inventory_status=product.inventory_status,
            bulk_pack_quantity=self._parse_bulk_quantity(product.bulk_pack_size),
        )

    def _clean_text(self, text: str) -> str:
        """Remove junk patterns and normalize whitespace."""
        if not text:
            return ""

        cleaned = text
        for pattern in self.junk_patterns:
            cleaned = re.sub(pattern, "", cleaned)

        cleaned = re.sub(r"\s+", " ", cleaned).strip()

        # Remove duplicate consecutive words
        words = cleaned.split()
        deduped = []
        prev_word = None
        for word in words:
            if word.lower() != prev_word:
                deduped.append(word)
            prev_word = word.lower()

        return " ".join(deduped)

    def _normalize_unit(self, unit: str | None) -> str | None:
        """Normalize unit of measure to standard format."""
        if not unit:
            return None

        # Try exact match first
        if unit in self.unit_mapping:
            return self.unit_mapping[unit]

        unit_lower = unit.lower().strip()
        return self.unit_mapping.get(unit_lower, unit_lower)

    def _convert_to_kg(self, unit: str | None) -> float | None:
        """Get conversion factor to kg for weight units."""
        if not unit:
            return None

        normalized = self._normalize_unit(unit)
        if normalized in self.weight_to_kg:
            return self.weight_to_kg[normalized]
        return None

    def _convert_weights(self, unit: str | None) -> dict[str, float | None]:
        """
        Convert unit to all weight formats.
        Returns dict with weight_kg, weight_g, weight_lb, weight_oz.
        """
        result = {"kg": None, "g": None, "lb": None, "oz": None}

        weight_kg = self._convert_to_kg(unit)
        if weight_kg is None:
            return result

        result["kg"] = round(weight_kg, 6)
        result["g"] = round(weight_kg * 1000, 6)
        result["lb"] = round(weight_kg / 0.453592, 6)
        result["oz"] = round(weight_kg / 0.0283495, 6)

        return result

    def _parse_category(self, category: str | None) -> tuple[str | None, dict]:
        """Parse and clean category hierarchy."""
        levels = {"level1": None, "level2": None, "level3": None}

        if not category:
            return None, levels

        normalized = self._normalize_category_for_matching(category)
        clean_category = self.category_mapping.get(normalized, category)

        parts = [p.strip() for p in re.split(r"\s*>\s*", clean_category) if p.strip()]

        if len(parts) >= 1:
            levels["level1"] = parts[0]
        if len(parts) >= 2:
            levels["level2"] = parts[1]
        if len(parts) >= 3:
            levels["level3"] = parts[2]

        clean_path = " > ".join(parts) if parts else None

        return clean_path, levels

    def _normalize_attributes(self, attrs: dict) -> tuple[list[dict], str]:
        """
        Normalize attribute keys and values dynamically.

        All attributes are normalized and kept - no hardcoded list required.
        - Keys are normalized (lowercase, underscores)
        - Numeric values are parsed (handles strings like "3 HP" -> 3.0)
        - Text values are cleaned
        - All attributes stored dynamically in the model

        Returns:
            Tuple of (attributes_list, attributes_search_string)
            attributes_search_string format: "key1: value1, key2: value2, ..."
        """
        normalized_list: list[dict] = []
        search_parts = []

        for key, value in attrs.items():
            if value is None:
                continue

            normalized_key = self._normalize_attribute_key(key)

            numeric_value = self._parse_numeric(value)
            cleaned_value = str(value).strip()

            field = {
                "key": normalized_key,
                "value": {
                    "raw": str(value) if value is not None else None,
                    "value": cleaned_value,
                    "numeric_values": [numeric_value]
                    if numeric_value is not None
                    else [],
                },
            }

            normalized_list.append(field)

            # Search string entry
            search_parts.append(f"{normalized_key}: {cleaned_value}")

        attributes_search = ", ".join(search_parts) if search_parts else None

        return normalized_list, attributes_search

    def _parse_numeric(self, value) -> float | None:
        """Parse numeric value, stripping unit suffix if present."""
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)

        match = re.search(r"([\d.]+)", str(value))
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                return None
        return None

    def _parse_int(self, value) -> int | None:
        """Parse integer value."""
        numeric = self._parse_numeric(value)
        return int(numeric) if numeric is not None else None

    def _parse_bulk_quantity(self, bulk_size: str | None) -> int | None:
        """Parse bulk pack size to numeric quantity."""
        if not bulk_size:
            return None

        bulk_lower = bulk_size.lower()

        for word, quantity in self.bulk_quantity_words.items():
            if word in bulk_lower:
                return quantity

        match = re.search(r"(\d+)", bulk_size)
        if match:
            return int(match.group(1))

        return None
