/** Diacritic-insensitive text folding for search. NFKD does NOT decompose ł/Ł (nor ø, đ, ß, æ, œ, ı), so they are mapped explicitly. */
const SPECIAL: Record<string, string> = {
  ł: "l",
  Ł: "L",
  ø: "o",
  Ø: "O",
  đ: "d",
  Đ: "D",
  ð: "d",
  Ð: "D",
  ħ: "h",
  Ħ: "H",
  ı: "i",
  ß: "ss",
  æ: "ae",
  Æ: "AE",
  œ: "oe",
  Œ: "OE",
  þ: "th",
  Þ: "TH",
};
const SPECIAL_RE = new RegExp(`[${Object.keys(SPECIAL).join("")}]`, "g");

/** "Łódź – Gdańsk" → "lodz – gdansk" (lower-case, accents stripped). */
export function foldText(text: string): string {
  return text
    .replace(SPECIAL_RE, (c) => SPECIAL[c])
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}
