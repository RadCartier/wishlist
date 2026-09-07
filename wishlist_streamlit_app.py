DATA_FILE = "wishlist_data.json"

st.set_page_config(page_title="Ma Wishlist", page_icon="🎁", layout="wide")


# ----------------------------
# Stockage local (fichier JSON)
# ----------------------------
def load_data():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {
        "items": [],
        "categories": ["Général", "Gaming", "Photo", "Cuisine", "Watches"],
        "daily_saving": 5.0,
    }


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


if "data" not in st.session_state:
    st.session_state.data = load_data()

data = st.session_state.data


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

        # 1. Métadonnées Open Graph (titre + image)
        og_title = soup.find("meta", property="og:title")
        og_image = soup.find("meta", property="og:image")
        if og_title and og_title.get("content"):
            result["name"] = og_title["content"].strip()
        elif soup.title:
            result["name"] = soup.title.get_text(strip=True)

        if og_image and og_image.get("content"):
            result["image"] = og_image["content"].strip()

        # 2. JSON-LD (souvent utilisé pour le prix structuré)
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

        # 3. Fallback : meta og:price / itemprop price
        if result["price"] is None:
            og_price = soup.find("meta", property="product:price:amount") or soup.find(
                "meta", attrs={"itemprop": "price"}
            )
            if og_price and og_price.get("content"):
                result["price"] = extract_price_from_text(og_price["content"])

        # 4. Dernier recours : chercher un motif prix dans le texte visible
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

# --- Barre latérale : épargne + gestion des catégories ---
with st.sidebar:
    st.header("⚙️ Paramètres")

    daily_saving = st.number_input(
        "Épargne mise de côté par jour (€)",
        min_value=0.0,
        step=0.5,
        value=float(data["daily_saving"]),
    )
    if daily_saving != data["daily_saving"]:
        data["daily_saving"] = daily_saving
        save_data(data)

    st.divider()
    st.subheader("📁 Catégories")
    new_cat = st.text_input("Nouvelle catégorie", key="new_cat_input")
    if st.button("Ajouter la catégorie", use_container_width=True):
        if new_cat.strip() and new_cat.strip() not in data["categories"]:
            data["categories"].append(new_cat.strip())
            save_data(data)
            st.rerun()
        elif new_cat.strip() in data["categories"]:
            st.warning("Cette catégorie existe déjà.")

    for cat in list(data["categories"]):
        col1, col2 = st.columns([4, 1])
        col1.write(f"- {cat}")
        if col2.button("✕", key=f"del_cat_{cat}"):
            used = any(i["category"] == cat for i in data["items"])
            for item in data["items"]:
                if item["category"] == cat:
                    item["category"] = "Général"
            if "Général" not in data["categories"]:
                data["categories"].insert(0, "Général")
            data["categories"].remove(cat)
            save_data(data)
            st.rerun()

    st.divider()
    st.subheader("💾 Sauvegarde")
    st.download_button(
        "⬇️ Exporter en JSON",
        data=json.dumps(data, ensure_ascii=False, indent=2),
        file_name=f"ma_wishlist_{datetime.now().strftime('%Y-%m-%d')}.json",
        mime="application/json",
        use_container_width=True,
    )
    imported = st.file_uploader("⬆️ Importer un JSON", type="json")
    if imported is not None:
        try:
            new_data = json.load(imported)
            st.session_state.data = new_data
            save_data(new_data)
            st.success("Import réussi !")
            st.rerun()
        except Exception:
            st.error("Fichier invalide.")


# --- Résumé en haut de page ---
total = sum(item["price"] for item in data["items"])
nb_items = len(data["items"])
days_needed = int(total / daily_saving) + (1 if daily_saving > 0 and total % daily_saving else 0) if daily_saving > 0 else None

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
        category = col_b.selectbox("Catégorie", data["categories"])
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
                data["items"].append({
                    "id": datetime.now().strftime("%Y%m%d%H%M%S%f"),
                    "name": name.strip(),
                    "price": price,
                    "category": category,
                    "link": link.strip(),
                    "image": image_url.strip(),
                    "added_at": datetime.now().isoformat(),
                })
                save_data(data)
                st.session_state["fetched_info"] = {}
                st.success(f"« {name} » ajouté à ta wishlist !")
                st.rerun()

st.divider()

# --- Filtre + affichage groupé par catégorie ---
filter_cat = st.selectbox("Filtrer par catégorie", ["Toutes les catégories"] + data["categories"])

if nb_items == 0:
    st.info("Ta wishlist est vide pour l'instant. Ajoute un premier article ci-dessus !")
else:
    filtered_items = (
        data["items"] if filter_cat == "Toutes les catégories"
        else [i for i in data["items"] if i["category"] == filter_cat]
    )

    grouped = {}
    for item in filtered_items:
        grouped.setdefault(item["category"], []).append(item)

    for cat in sorted(grouped.keys()):
        cat_items = grouped[cat]
        cat_total = sum(i["price"] for i in cat_items)
        st.subheader(f"{cat}  ·  {len(cat_items)} article(s)  ·  {cat_total:,.2f} €".replace(",", " "))

        cols = st.columns(3)
        for idx, item in enumerate(cat_items):
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

                    col_e, col_d = st.columns(2)
                    if col_d.button("🗑️ Supprimer", key=f"del_{item['id']}", use_container_width=True):
                        data["items"] = [i for i in data["items"] if i["id"] != item["id"]]
                        save_data(data)
                        st.rerun()

st.divider()
st.caption("Toutes les données sont stockées localement dans le fichier wishlist_data.json, à côté de ce script. Aucune donnée n'est envoyée sur un serveur externe (hors requêtes de récupération des pages produit que tu déclenches toi-même).")
