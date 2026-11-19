import re
import pandas as pd
from jinja2 import Template
from playwright.sync_api import sync_playwright

# Your live Google Sheet CSV export link (Sheet2)
SHEET_CSV_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1n7OQ4lg7S2BeeLX01t-L-sd9bcVvq8pgKyozZCmgEhg/export?format=csv&gid=2073319162"
)

# Combine smaller sheet categories under one PDF section header (edit anytime)
SECTION_MAP = {
    "Health Faucet": "HEALTH FAUCET & JET SPRAYS",
    "JET SPRAY": "HEALTH FAUCET & JET SPRAYS",
    "HOOK": "HEALTH FAUCET & JET SPRAYS",
    "SHOWER CHAIN": "HEALTH FAUCET & JET SPRAYS",
}


def drive_to_direct_img(url: str) -> str:
    """Convert Google Drive /view links into direct image URLs."""
    if not url or not isinstance(url, str):
        return ""
    url = url.strip()
    match = re.search(r"/d/([a-zA-Z0-9_-]+)", url) or re.search(r"id=([a-zA-Z0-9_-]+)", url)
    if match:
        return f"https://lh3.googleusercontent.com/d/{match.group(1)}=w600"
    return url


def format_rate(val) -> str:
    """Format prices cleanly (e.g., 275.0 -> ₹ 275)."""
    s = str(val).strip()
    if not s or s.lower() == "nan":
        return ""
    try:
        num = float(s)
        return f"₹ {int(num)}" if num.is_integer() else f"₹ {num:.2f}"
    except ValueError:
        return f"₹ {s}" if not s.startswith("₹") else s


def load_sections():
    df = pd.read_csv(SHEET_CSV_URL).fillna("")
    df.columns = [c.strip() for c in df.columns]

    # Clean whitespace from all text cells
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()

    # Drop completely empty rows
    df = df[df["Item Id"] != ""].copy()

    # Fallback if any row is missing a Group ID
    missing_grp = df["Group ID"] == ""
    df.loc[missing_grp, "Group ID"] = "SINGLE_" + df.loc[missing_grp, "Item Id"]

    # Map each row to its PDF Section Header
    df["Section"] = df["Category"].apply(lambda c: SECTION_MAP.get(c, c.upper()))

    sections = []
    # sort=False preserves the exact order from your Google Sheet
    for section_name, sec_df in df.groupby("Section", sort=False):
        cards = []
        for grp_id, grp_df in sec_df.groupby("Group ID", sort=False):
            # Pick the first non-empty image URL in this group
            imgs = [drive_to_direct_img(u) for u in grp_df["Image"] if u]
            image_url = imgs[0] if imgs else ""

            unique_names = [n for n in grp_df["Name"].unique() if n]
            category_name = grp_df["Category"].iloc[0]

            # Decide card title vs row spec label
            if len(unique_names) == 1:
                base_name = unique_names[0]
                if category_name.lower() in base_name.lower():
                    card_title = base_name.upper()
                else:
                    card_title = f"{category_name} {base_name}".upper()
                multi_name = False
            else:
                card_title = category_name.upper()
                multi_name = True

            variants = []
            for _, row in grp_df.iterrows():
                if multi_name:
                    spec = " ".join(x for x in [row["Name"], row["Varient"]] if x)
                else:
                    spec = row["Varient"] or row["Material"] or ""

                variants.append({
                    "id": row["Item Id"],
                    "spec": spec.upper(),
                    "rate": format_rate(row["Rate"]),
                })

            cards.append({
                "title": card_title,
                "image": image_url,
                "variants": variants,
            })

        sections.append({"title": section_name, "cards": cards})

    return sections


def main():
    print("Fetching data from Google Sheets...")
    sections = load_sections()
    print(f"Loaded {len(sections)} sections.")

    with open("template.html", "r", encoding="utf-8") as f:
        template = Template(f.read())

    html_output = template.render(sections=sections)
    with open("preview.html", "w", encoding="utf-8") as f:
        f.write(html_output)

    print("Rendering PDF...")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_output, wait_until="networkidle")
        # Wait briefly for all Google Drive images to finish decoding
        page.evaluate(
            """async () => {
                const imgs = Array.from(document.images);
                await Promise.all(imgs.map(img =>
                    img.complete ? Promise.resolve() : new Promise(r => { img.onload = img.onerror = r; })
                ));
            }"""
        )
        page.pdf(
            path="KBS_Catalogue.pdf",
            format="A4",
            landscape=True,
            print_background=True,
            margin={"top": "0mm", "bottom": "0mm", "left": "0mm", "right": "0mm"},
        )
        browser.close()

    print("Done! Saved KBS_Catalogue.pdf")


if __name__ == "__main__":
    main()
