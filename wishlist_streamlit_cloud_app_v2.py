import streamlit as st
import pandas as pd
import requests
from bs4 import BeautifulSoup
from datetime import datetime
import re
import json
from streamlit_gsheets import GSheetsConnection

st.set_page_config(page_title="Ma Wishlist", page_icon="🎁", layout="wide")

DEFAULT_CATEGORIES = ["Général", "Gaming", "Photo", "Cuisine", "Watches"]
ITEMS_COLUMNS = ["id", "name", "price", "category", "link", "image", "added_at"]

conn = st.connection("gsheets", type=GSheetsConnection)


def _empty_items_df():
    return pd.DataFrame(columns=ITEMS_COLUMNS)


def load_items():
    try:
        df = conn.read(worksheet="items", ttl=0)
    except Exception as e:
        st.error(f"Impossible de lire l'onglet 'items' : {e}")
        return _empty_items_df()

    if df is None or df.empty:
        return _empty_items_df()

    df = df.dropna(how="all")
    for col in ITEMS_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "price" else 0.0
    df = df[ITEMS_COLUMNS]

    df["id"] = df["id"].astype(str).str.replace(r"\.0$", "", regex=True)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    for col in ["name", "category", "link", "image", "added_at"]:
        df[col] = df[col].fillna("").astype(str)

    return df.reset_index(drop=True)


def load_categories():
    try:
        df = conn.read(worksheet="categories", ttl=0)
    except Exception as e:
        st.error(f"Impossible de lire l'onglet 'categories' : {e}")
        return DEFAULT_CATEGORIES.copy()

    if df is None or df.empty or "category" not in df.columns:
        return DEFAULT_CATEGORIES.copy()

    cats = [str(c).strip() for c in df["category"].dropna().tolist() if str(c).strip()]
    return cats if cats else DEFAULT_CATEGORIES.copy()


def load_settings():
    try:
        df = conn.read(worksheet="settings", ttl=0)
    except Exception as e:
        st.error(f"Impossible de lire l'onglet 'settings' : {e}")
        return 5.0

    if df is None or df.empty or "key" not in df.columns or "value" not in df.columns:
        return 5.0

    rows = df.loc[df["key"] == "daily_saving", "value"]
    if rows.empty:
        return 5.0
    try:
        return float(rows.iloc[0])
    except (ValueError, TypeError):
        return 5.0


def save_items(df):
    df = df.copy()
    for col in ITEMS_COLUMNS:
        if col not in df.columns:
            df[col] = "" if col != "price" else 0.0
    df = df[ITEMS_COLUMNS]
    df["id"] = df["id"].astype(str)
    df["price"] = pd.to_numeric(df["price"], errors="coerce").fillna(0.0)
    try:
        conn.update(worksheet="items", data=df)
    except Exception as e:
        st.error(f"Erreur lors de l'écriture dans l'onglet 'items' : {e}")
        return False
    st.cache_data.clear()
    return True


def save_categories(cats):
    cats = [c for c in cats if c and str(c).strip()]
    try:
        conn.update(worksheet="categories", data=pd.DataFrame({"category": cats}))
    except Exception as e:
        st.error(f"Erreur lors de l'écriture dans l'onglet 'categories' : {e}")
        return False
    st.cache_data.clear()
    return True


def save_settings(daily_saving):
    try:
        conn.update(
            worksheet="settings",
            data=pd.DataFrame({"key": ["daily_saving"], "value": [daily_saving]}),
        )
    except Exception as e:
        st.error(f"Erreur lors de l'écriture dans l'onglet 'settings' : {e}")
        return False
    st.cache_data.clear()
    return True


if "items_df" not in st.session_state:
    st.session_state.items_df = load_items()
if "categories" not in st.session_state:
    st.session_state.categories = load_categories()
if "daily_saving_val" not in st.session_state:
    st.session_state.daily_saving_val = load_settings()

items_df = st.session_state.items_df
categories = st.session_state.categories
daily_saving_saved = st.session_state.daily_saving_val


def refresh_all():
    st.session_state.items_df = load_items()
    st.session_state.categories = load_categories()
    st.session_state.daily_saving_val = load_settings()


# ----------------------------
# Extraction auto (image / prix / titre) depuis une URL produit
# ----------------------------
def extract_price_from_text(text):
    if not text:
        return None
    text = text.replace("\xa0", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d{1,2})?)", text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


def fetch_product_info(url):
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0 Safari/537.36"
        )
    }
    result = {"name": "", "image": "", "price": None, "error": None}
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        og_title = soup.find("meta", property="og:title")
        og_image = soup.find("meta", property="og:image")
        if og_title and og_title.get("content"):
            result["name"] = og_title["content"].strip()
        elif soup.title:
            result["name"] = soup.title.get_text(strip=True)

        if og_image and og_image.get("content"):
            result["image"] = og_image["content"].strip()

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                payload = json.loads(script.string)
            except (TypeError, ValueError):
                continue
            candidates = payload if isinstance(payload, list) else [payload]
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                offers = candidate.get("offers")
                if isinstance(offers, list):
                    offers = offers[0] if offers else {}
                if isinstance(offers, dict) and offers.get("price"):
                    price_val = extract_price_from_text(str(offers["price"]))
                    if price_val:
                        result["price"] = price_val
                if not result["name"] and candidate.get("name"):
                    result["name"] = candidate["name"]
                if not result["image"] and candidate.get("image"):
                    img = candidate["image"]
                    result["image"] = img[0] if isinstance(img, list) else img

        if result["price"] is None:
            og_price = soup.find("meta", property="product:price:amount") or soup.find(
                "meta", attrs={"itemprop": "price"}
            )
            if og_price and og_price.get("content"):
                result["price"] = extract_price_from_text(og_price["content"])

        if result["price"] is None:
            text_blob = soup.get_text(" ", strip=True)
            match = re.search(r"(\d+[.,]\d{2})\s?€", text_blob)
            if match:
                result["price"] = extract_price_from_text(match.group(1))

    except requests.exceptions.RequestException as exc:
        result["error"] = f"Impossible de récupérer la page : {exc}"
    except Exception as exc:
        result["error"] = f"Erreur lors de l'analyse de la page : {exc}"

    return result


# ----------------------------
# Interface
# ----------------------------
st.markdown(
    "<h1 style='text-align:center;'>🎁 Ma Wishlist</h1>"
    "<p style='text-align:center;color:gray;'>Organise tes envies, suis ton budget, "
    "calcule ton temps d'attente</p>",
    unsafe_allow_html=True,
)

with st.sidebar:
    st.header("⚙️ Paramètres")

    daily_saving = st.number_input(
        "Épargne mise de côté par jour (€)",
        min_value=0.0,
        step=0.5,
        value=float(daily_saving_saved),
        key="daily_saving_input",
    )
    if daily_saving != daily_saving_saved:
        if save_settings(daily_saving):
            refresh_all()
            st.rerun()

    st.divider()
    st.subheader("📁 Catégories")
    new_cat = st.text_input("Nouvelle catégorie", key="new_cat_input")
    if st.button("Ajouter la catégorie", use_container_width=True):
        if new_cat.strip() and new_cat.strip() not in categories:
            new_cats = categories + [new_cat.strip()]
            if save_categories(new_cats):
                refresh_all()
                st.rerun()
        elif new_cat.strip() in categories:
            st.warning("Cette catégorie existe déjà.")

    for cat in list(categories):
        col1, col2 = st.columns([4, 1])
        col1.write(f"- {cat}")
        if col2.button("✕", key=f"del_cat_{cat}"):
            updated_items = items_df.copy()
            mask = updated_items["category"] == cat
            if mask.any():
                updated_items.loc[mask, "category"] = "Général"
            new_cats = [c for c in categories if c != cat]
            if "Général" not in new_cats:
                new_cats.insert(0, "Général")
            ok1 = save_items(updated_items) if mask.any() else True
            ok2 = save_categories(new_cats)
            if ok1 and ok2:
                refresh_all()
                st.rerun()

    st.divider()
    if st.button("🔄 Recharger depuis Google Sheets", use_container_width=True):
        refresh_all()
        st.rerun()

    st.divider()
    st.subheader("💾 Export")
    st.download_button(
        "⬇️ Exporter en CSV",
        data=items_df.to_csv(index=False).encode("utf-8"),
        file_name=f"ma_wishlist_{datetime.now().strftime('%Y-%m-%d')}.csv",
        mime="text/csv",
        use_container_width=True,
    )


# --- Résumé en haut de page ---
total = items_df["price"].sum() if not items_df.empty else 0.0
nb_items = len(items_df)
days_needed = None
if daily_saving > 0:
    days_needed = int(total / daily_saving) + (1 if total % daily_saving else 0)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Nombre d'articles", nb_items)
c2.metric("Total wishlist", f"{total:,.2f} €".replace(",", " "))
c3.metric("Épargne / jour", f"{daily_saving:.2f} €")
c4.metric("Jours pour tout acheter", f"{days_needed} j" if days_needed is not None else "–")

st.divider()

# --- Formulaire d'ajout ---
with st.expander("➕ Ajouter un article", expanded=nb_items == 0):
    url_input = st.text_input(
        "Lien de la page produit (optionnel, pour préremplir automatiquement)",
        key="fetch_url_input",
        placeholder="https://www.exemple.com/produit...",
    )

    fetched = st.session_state.get("fetched_info", {})

    if st.button("🔍 Récupérer les infos du produit"):
        if url_input.strip():
            with st.spinner("Récupération des informations en cours..."):
                fetched = fetch_product_info(url_input.strip())
                st.session_state["fetched_info"] = fetched
            if fetched.get("error"):
                st.error(fetched["error"])
            else:
                st.success("Informations récupérées ! Vérifie et complète les champs ci-dessous avant d'enregistrer.")
        else:
            st.warning("Colle d'abord un lien produit.")

    with st.form("add_item_form", clear_on_submit=True):
        name = st.text_input("Nom de l'article *", value=fetched.get("name", ""))
        col_a, col_b = st.columns(2)
        price = col_a.number_input(
            "Prix (€) *", min_value=0.0, step=0.01,
            value=float(fetched.get("price") or 0.0),
        )
        category = col_b.selectbox("Catégorie", categories if categories else ["Général"])
        link = st.text_input("Lien d'achat", value=url_input.strip())
        image_url = st.text_input("URL de l'image", value=fetched.get("image", ""))
        if image_url:
            st.image(image_url, width=180)

        submitted = st.form_submit_button("Enregistrer l'article", use_container_width=True)
        if submitted:
            if not name.strip():
                st.error("Le nom est obligatoire.")
            elif price <= 0:
                st.error("Merci d'indiquer un prix valide.")
            else:
                new_row = pd.DataFrame([{
                    "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "name": name.strip(),
                    "price": price,
                    "category": category,
                    "link": link.strip(),
                    "image": image_url.strip(),
                    "added_at": datetime.now().isoformat(),
                }])
                updated_df = pd.concat([items_df, new_row], ignore_index=True)
                if save_items(updated_df):
                    st.session_state["fetched_info"] = {}
                    refresh_all()
                    st.success(f"« {name} » ajouté à ta wishlist !")
                    st.rerun()

st.divider()

# --- Filtre + affichage groupé par catégorie ---
filter_cat = st.selectbox("Filtrer par catégorie", ["Toutes les catégories"] + categories)

if nb_items == 0:
    st.info("Ta wishlist est vide pour l'instant. Ajoute un premier article ci-dessus !")
else:
    filtered_df = items_df if filter_cat == "Toutes les catégories" else items_df[items_df["category"] == filter_cat]

    for cat in sorted(filtered_df["category"].dropna().unique()):
        cat_items = filtered_df[filtered_df["category"] == cat]
        cat_total = cat_items["price"].sum()
        st.subheader(f"{cat}  ·  {len(cat_items)} article(s)  ·  {cat_total:,.2f} €".replace(",", " "))

        cols = st.columns(3)
        for idx, (_, item) in enumerate(cat_items.iterrows()):
            with cols[idx % 3]:
                with st.container(border=True):
                    if item.get("image"):
                        try:
                            st.image(item["image"], use_container_width=True)
                        except Exception:
                            st.caption("📦 Image non chargeable")
                    else:
                        st.caption("📦 Pas d'image")

                    st.markdown(f"**{item['name']}**")
                    st.markdown(f"💶 **{item['price']:,.2f} €**".replace(",", " "))

                    if daily_saving > 0:
                        item_days = int(item["price"] / daily_saving) + (
                            1 if item["price"] % daily_saving else 0
                        )
                        st.caption(f"⏳ {item_days} jour(s) à {daily_saving:.2f} €/jour")
                    else:
                        st.caption("Renseigne une épargne journalière dans le menu de gauche")

                    if item.get("link"):
                        st.link_button("🛒 Acheter", item["link"], use_container_width=True)

                    if st.button("🗑️ Supprimer", key=f"del_{item['id']}", use_container_width=True):
                        updated_df = items_df[items_df["id"] != item["id"]]
                        if save_items(updated_df):
                            refresh_all()
                            st.rerun()

st.divider()
st.caption("Les données sont stockées dans une Google Sheet connectée à cette application, ce qui garantit qu'elles ne sont jamais perdues même après un redémarrage sur Streamlit Cloud.")
