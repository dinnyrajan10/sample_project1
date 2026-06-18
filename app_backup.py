from flask import Flask, render_template, request, jsonify, session, redirect
from werkzeug.utils import secure_filename
import os
import json

app = Flask(__name__)
app.secret_key = "nepalthrift_secret_2026"  # change this in production!

# ── In-memory product catalog (replace with a database later) ──
PRODUCTS = [
    {
        "id": 1,
        "name": "Sherpa Wool Jacket",
        "category": "Outerwear",
        "size": "EU 46",
        "price": 1800,
        "badge": "New In",
        "emoji": "🧥",
        "description": "Thick sherpa-lined jacket, perfect for Kathmandu winters.",
    },
    {
        "id": 2,
        "name": "Embroidered Kurta",
        "category": "Tops",
        "size": "EU 42",
        "price": 950,
        "badge": None,
        "emoji": "👘",
        "description": "Hand-embroidered cotton kurta from Bhaktapur market.",
    },
    {
        "id": 3,
        "name": "Corduroy Blazer",
        "category": "Tops",
        "size": "EU 44",
        "price": 1200,
        "badge": None,
        "emoji": "🥼",
        "description": "80s corduroy blazer in warm caramel brown.",
    },
    {
        "id": 4,
        "name": "Oversized Tee",
        "category": "Tops",
        "size": "EU 44",
        "price": 600,
        "badge": None,
        "emoji": "👕",
        "description": "Faded vintage tee, washed and worn-in look.",
    },
    {
        "id": 5,
        "name": "High-Waist Denim",
        "category": "Bottoms",
        "size": "EU 40",
        "price": 900,
        "badge": "Last One",
        "emoji": "👖",
        "description": "90s high-waist denim, barely worn.",
    },
    {
        "id": 6,
        "name": "Ikat Print Blouse",
        "category": "Tops",
        "size": "EU 38",
        "price": 750,
        "badge": "New In",
        "emoji": "🌸",
        "description": "Traditional ikat weave in sunset tones.",
    },
]

# ── ROUTES ──

@app.route("/")
def home():
    return render_template("index.html", products=PRODUCTS)


@app.route("/api/products")
def get_products():
    """Return all products as JSON (useful for filtering)."""
    category = request.args.get("category")
    if category and category != "All":
        filtered = [p for p in PRODUCTS if p["category"] == category]
    else:
        filtered = PRODUCTS
    return jsonify(filtered)


@app.route("/api/cart", methods=["GET"])
def get_cart():
    cart = session.get("cart", [])
    return jsonify(cart)


@app.route("/api/cart/add", methods=["POST"])
def add_to_cart():
    """Add a product to the cart stored in the session."""
    data = request.get_json()
    product_id = data.get("id")

    product = next((p for p in PRODUCTS if p["id"] == product_id), None)
    if not product:
        return jsonify({"error": "Product not found"}), 404

    cart = session.get("cart", [])

    # Check if already in cart; if so, just note it
    if any(item["id"] == product_id for item in cart):
        return jsonify({"message": "Already in cart", "cart": cart})

    cart.append(product)
    session["cart"] = cart
    return jsonify({"message": "Added to cart", "cart": cart})


@app.route("/api/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.get_json()
    product_id = data.get("id")
    cart = session.get("cart", [])
    cart = [item for item in cart if item["id"] != product_id]
    session["cart"] = cart
    return jsonify({"message": "Removed", "cart": cart})


@app.route("/api/outfit/suggest", methods=["POST"])
def suggest_outfit():
    """Return a random outfit combo from the catalog."""
    import random
    tops = [p for p in PRODUCTS if p["category"] == "Tops"]
    bottoms = [p for p in PRODUCTS if p["category"] == "Bottoms"]
    outerwear = [p for p in PRODUCTS if p["category"] == "Outerwear"]

    combo = []
    if tops:
        combo.append(random.choice(tops))
    if bottoms:
        combo.append(random.choice(bottoms))
    if outerwear:
        combo.append(random.choice(outerwear))

    tips = [
        "Layer the jacket over the tee for a Thamel streetwear moment.",
        "Roll the cuffs on the denim — instant elevation.",
        "A woven bag ties the whole heritage look together.",
        "Try tucking the blouse for that effortless 90s silhouette.",
        "Mix the textures: corduroy + cotton is a timeless combo.",
    ]

    return jsonify({
        "items": combo,
        "tip": random.choice(tips),
    })


@app.route("/api/checkout", methods=["POST"])
def checkout():
    """
    Pretend payment processing.
    In a real app: integrate eSewa / Khalti / Stripe here.
    """
    data = request.get_json()
    method = data.get("method", "card")
    name = data.get("name", "")

    if not name:
        return jsonify({"error": "Name is required"}), 400

    # Clear the cart after "payment"
    session["cart"] = []

    return jsonify({
        "success": True,
        "message": f"Order confirmed! You'll get a WhatsApp confirmation shortly.",
        "method": method,
    })
@app.route("/upload")
def upload_page():
    return render_template("upload.html")


@app.route("/upload-product", methods=["POST"])
def upload_product():

    name = request.form["name"]
    price = request.form["price"]

    image = request.files["image"]

    filename = secure_filename(image.filename)

    image.save(
        os.path.join(
            app.config["UPLOAD_FOLDER"],
            filename
        )
    )

    new_product = {
        "id": len(PRODUCTS) + 1,
        "name": name,
        "category": "Tops",
        "size": "EU 44",
        "price": int(price),
        "badge": "New",
        "emoji": "",
        "description": "Uploaded Product",
        "image": filename
    }

    PRODUCTS.append(new_product)

    return redirect("/")

if __name__ == "__main__":
    app.run(debug=True)
